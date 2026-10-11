"""Turntable look-dev set: front, three-quarter, profile and head close-up.

Spike 2 (NOTES.md §18). Imports the spike-1 GLB (so we render what ships),
builds a neutral studio and renders each view, timing every frame.

    blender -b -t 3 --factory-startup --python blender/render_turntable.py -- \
        --glb data/build/character/character.glb --out-dir data/build/renders/cycles \
        --engine CYCLES --res 1024 --samples 128 --denoise 1

    # EEVEE headless (OpenGL via EGL). Force llvmpipe with LIBGL_ALWAYS_SOFTWARE=1.
    blender -b -t 3 --factory-startup --python blender/render_turntable.py -- \
        --glb ... --out-dir ... --engine EEVEE --res 1024 --samples 64

Writes <out-dir>/<view>.png and <out-dir>/timings.json.
"""

import argparse
import json
import math
import os
import sys
import time

import bpy
from mathutils import Vector

VIEWS = {
    # name: (azimuth deg, measured from the character's front, framing)
    "front": (0.0, "body"),
    "three_quarter": (40.0, "body"),
    "profile": (90.0, "body"),
    "closeup": (25.0, "head"),
}


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--glb", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--engine", choices=["CYCLES", "EEVEE"], default="CYCLES")
    ap.add_argument("--res", type=int, default=1024)
    ap.add_argument("--samples", type=int, default=128)
    ap.add_argument("--denoise", type=int, default=1)
    ap.add_argument("--adaptive", type=int, default=1)
    ap.add_argument("--views", default=",".join(VIEWS))
    ap.add_argument("--warm-repeat", type=int, default=1,
                    help="render the first view again at the end (warm cache timing)")
    return ap.parse_args(argv)


ARGS = parse_args()


def clear_scene():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)


def import_character(path):
    t = time.perf_counter()
    bpy.ops.import_scene.gltf(filepath=os.path.abspath(path))
    dt = time.perf_counter() - t
    arm = next((o for o in bpy.context.scene.objects if o.type == "ARMATURE"), None)
    # Only the skinned character meshes: the importer also adds a hidden
    # bone-shape Icosphere (2 m bbox) that would wreck the framing.
    objs = [o for o in bpy.context.scene.objects
            if o.type == "MESH" and o.parent is not None and o.parent == arm]
    lo = Vector((1e9, 1e9, 1e9))
    hi = Vector((-1e9, -1e9, -1e9))
    for o in objs:
        for c in o.bound_box:
            w = o.matrix_world @ Vector(c)
            lo = Vector(map(min, lo, w))
            hi = Vector(map(max, hi, w))
    head = None
    if arm is not None and "head" in arm.data.bones:
        b = arm.data.bones["head"]
        head = arm.matrix_world @ ((b.head_local + b.tail_local) * 0.5)
    return dt, lo, hi, head


def look_at(cam, target):
    d = target - cam.location
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


def build_studio(lo, hi):
    scene = bpy.context.scene
    world = bpy.data.worlds.new("studio") if not scene.world else scene.world
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    bg.inputs[0].default_value = (0.045, 0.045, 0.05, 1.0)
    bg.inputs[1].default_value = 1.0

    bpy.ops.mesh.primitive_plane_add(size=60, location=(0, 0, lo.z))
    floor = bpy.context.active_object
    mat = bpy.data.materials.new("floor")
    mat.use_nodes = True
    p = mat.node_tree.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = (0.08, 0.08, 0.085, 1)
    p.inputs["Roughness"].default_value = 0.8
    floor.data.materials.append(mat)

    height = hi.z - lo.z

    def area(name, loc, energy, size, color=(1, 1, 1)):
        ld = bpy.data.lights.new(name, "AREA")
        ld.energy = energy
        ld.size = size
        ld.color = color
        ob = bpy.data.objects.new(name, ld)
        scene.collection.objects.link(ob)
        ob.location = loc
        look_at(ob, Vector((0, 0, lo.z + height * 0.6)))
        return ob

    # Character faces -Y. Key front-left-high, fill front-right, rim behind.
    area("key", (-2.2, -2.6, lo.z + 2.8), 900, 1.5, (1.0, 0.96, 0.9))
    area("fill", (2.6, -2.0, lo.z + 1.4), 250, 2.0, (0.85, 0.9, 1.0))
    area("rim", (0.8, 2.8, lo.z + 2.6), 700, 1.0)


def make_camera(view, lo, hi, head):
    az, framing = VIEWS[view]
    scene = bpy.context.scene
    cd = bpy.data.cameras.new(view)
    cam = bpy.data.objects.new(view, cd)
    scene.collection.objects.link(cam)
    height = hi.z - lo.z
    if framing == "body":
        cd.lens = 50.0
        frame_h = height * 1.12
        target = Vector((0.0, 0.0, lo.z + height * 0.5))
    else:
        cd.lens = 85.0
        frame_h = 0.42
        target = head.copy() if head is not None else Vector((0, 0, hi.z - 0.13))
        target.z -= 0.03
    half_fov = math.atan(cd.sensor_width * 0.5 / cd.lens)
    dist = (frame_h * 0.5) / math.tan(half_fov)
    a = math.radians(az)
    # Azimuth 0 = in front of the character (-Y), positive rotates to the
    # character's left (+X), i.e. shows its left side in "profile".
    cam.location = target + Vector((math.sin(a) * dist, -math.cos(a) * dist, 0.0))
    look_at(cam, target)
    return cam


def configure_engine():
    scene = bpy.context.scene
    r = scene.render
    r.resolution_x = r.resolution_y = ARGS.res
    r.resolution_percentage = 100
    r.image_settings.file_format = "PNG"
    r.image_settings.color_mode = "RGB"
    r.image_settings.compression = 90
    if ARGS.engine == "CYCLES":
        r.engine = "CYCLES"
        c = scene.cycles
        c.device = "CPU"
        c.samples = ARGS.samples
        c.use_adaptive_sampling = bool(ARGS.adaptive)
        c.use_denoising = bool(ARGS.denoise)
        c.denoiser = "OPENIMAGEDENOISE"
        if hasattr(c, "denoising_use_gpu"):
            c.denoising_use_gpu = False
        c.max_bounces = 8
        c.transparent_max_bounces = 16
    else:
        r.engine = "BLENDER_EEVEE"
        e = scene.eevee
        e.taa_render_samples = ARGS.samples


def main():
    clear_scene()
    import_s, lo, hi, head = import_character(ARGS.glb)
    build_studio(lo, hi)
    configure_engine()
    os.makedirs(ARGS.out_dir, exist_ok=True)
    scene = bpy.context.scene
    views = [v for v in ARGS.views.split(",") if v]
    cams = {v: make_camera(v, lo, hi, head) for v in views}
    gpu_info = None
    frames = []
    order = views + ([views[0]] if ARGS.warm_repeat else [])
    for i, v in enumerate(order):
        scene.camera = cams[v]
        warm = i >= len(views)
        scene.render.filepath = os.path.join(ARGS.out_dir, f"{v}{'_warm' if warm else ''}.png")
        with open("/proc/loadavg") as f:
            load = f.read().strip()
        t = time.perf_counter()
        bpy.ops.render.render(write_still=True)
        dt = time.perf_counter() - t
        frames.append({"view": v, "warm_repeat": warm, "seconds": round(dt, 3),
                       "loadavg_start": load})
        print(f"[render] {ARGS.engine} {v}{' (warm)' if warm else ''}: {dt:.2f} s", flush=True)
        if gpu_info is None and ARGS.engine == "EEVEE":
            import gpu
            gpu_info = {"backend": gpu.platform.backend_type_get(),
                        "renderer": gpu.platform.renderer_get(),
                        "version": gpu.platform.version_get()}
    out = {"engine": ARGS.engine, "res": ARGS.res, "samples": ARGS.samples,
           "denoise": bool(ARGS.denoise), "adaptive": bool(ARGS.adaptive),
           "threads": scene.render.threads, "blender": bpy.app.version_string,
           "gpu": gpu_info, "glb_import_s": round(import_s, 3), "frames": frames,
           "env": {k: os.environ.get(k) for k in
                   ("LIBGL_ALWAYS_SOFTWARE", "LP_NUM_THREADS", "OMP_NUM_THREADS")}}
    with open(os.path.join(ARGS.out_dir, "timings.json"), "w") as f:
        json.dump(out, f, indent=2)
    print(json.dumps(out, indent=2))


main()
