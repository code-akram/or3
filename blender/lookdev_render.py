"""Look-dev renders + metrics for one character GLB (m1 loop; bench/m1/lookdev.sh).

Imports the GLB (we render what ships), then per view:
  * a beauty frame: fixed neutral studio, perspective camera at a FIXED world
    position (body views) or tracking the head bone (close-up), so a change
    in proportions shows up as a change in the picture;
  * a silhouette mask: orthographic camera along the same axis, character
    only, 1 px = a fixed metric size, so IoU between runs is meaningful.
Then writes metrics.json: triangles per part, bones, weights per vertex,
landmark ratios, and mask IoU against a target set and the previous run.

    blender -b -t 4 --factory-startup --python blender/lookdev_render.py -- \
        --glb RUN/character.glb --out-dir RUN [--mode loop|signoff] \
        [--prev PREV_RUN] [--target TARGET_DIR]

Loop mode: EEVEE (iGPU via EGL) 512², 16 samples. Sign-off: Cycles CPU 1024²,
128 spp + OIDN HIGH. Masks are always EEVEE 512², 1 sample.
"""

import argparse
import json
import math
import os
import sys
import time

import bpy
import numpy as np
from mathutils import Vector

# name: (azimuth deg from the character's front, framing)
VIEWS = {
    "front": (0.0, "body"),
    "three_quarter": (40.0, "body"),
    "profile": (90.0, "body"),
    "closeup": (25.0, "head"),
}
# Fixed framing for body views (metres, character feet at z = 0, facing -Y).
BODY_TARGET_Z = 0.98
BODY_FRAME_H = 2.15
HEAD_FRAME_H = 0.42
MASK_RES = 512


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--glb", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--mode", choices=["loop", "signoff"], default="loop")
    ap.add_argument("--prev", help="previous run dir (masks + metrics) to score against")
    ap.add_argument("--target", help="dir with <view>_mask.png target silhouettes")
    ap.add_argument("--views", default=",".join(VIEWS))
    return ap.parse_args(argv)


ARGS = parse_args()
TIMINGS = {}


def timed(name):
    class _T:
        def __enter__(self):
            self.t = time.perf_counter()

        def __exit__(self, *exc):
            TIMINGS[name] = round(time.perf_counter() - self.t, 3)
            return False
    return _T()


# ---------------------------------------------------------------- scene

def import_character(path):
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    bpy.ops.import_scene.gltf(filepath=os.path.abspath(path))
    arm = next(o for o in bpy.context.scene.objects if o.type == "ARMATURE")
    # Only the skinned character meshes: the importer also adds a hidden
    # bone-shape Icosphere that is not part of the character.
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH" and o.parent == arm]
    for o in bpy.context.scene.objects:
        if o.type == "MESH" and o not in meshes:
            o.hide_render = True
    return arm, meshes


def part_name(o):
    """'Human.long01_export' -> 'long01'; the body 'Human_export' -> 'body'."""
    n = o.name.split("_export")[0]
    return n.split(".", 1)[1] if "." in n else "body"


def look_at(ob, target):
    ob.rotation_euler = (target - ob.location).to_track_quat("-Z", "Y").to_euler()


def build_studio(floor_z):
    scene = bpy.context.scene
    world = scene.world or bpy.data.worlds.new("studio")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    bg.inputs[0].default_value = (0.045, 0.045, 0.05, 1.0)
    bg.inputs[1].default_value = 1.0

    bpy.ops.mesh.primitive_plane_add(size=60, location=(0, 0, floor_z))
    floor = bpy.context.active_object
    floor.name = "lookdev_floor"
    mat = bpy.data.materials.new("lookdev_floor")
    mat.use_nodes = True
    p = mat.node_tree.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = (0.08, 0.08, 0.085, 1)
    p.inputs["Roughness"].default_value = 0.8
    floor.data.materials.append(mat)

    aim = Vector((0, 0, floor_z + 1.1))

    def area(name, loc, energy, size, color=(1, 1, 1)):
        ld = bpy.data.lights.new(name, "AREA")
        ld.energy, ld.size, ld.color = energy, size, color
        ob = bpy.data.objects.new(name, ld)
        scene.collection.objects.link(ob)
        ob.location = Vector(loc) + Vector((0, 0, floor_z))
        look_at(ob, aim)
        return ob

    # Character faces -Y. Key front-left-high, fill front-right, rim behind
    # (same rig as spike 2, at fixed positions).
    lights = [area("key", (-2.2, -2.6, 2.8), 900, 1.5, (1.0, 0.96, 0.9)),
              area("fill", (2.6, -2.0, 1.4), 250, 2.0, (0.85, 0.9, 1.0)),
              area("rim", (0.8, 2.8, 2.6), 700, 1.0)]
    return floor, lights


def view_target(framing, floor_z, head):
    if framing == "body":
        return Vector((0.0, 0.0, floor_z + BODY_TARGET_Z)), BODY_FRAME_H
    t = head.copy()
    t.z -= 0.03
    return t, HEAD_FRAME_H


def make_cameras(view, floor_z, head):
    az, framing = VIEWS[view]
    target, frame_h = view_target(framing, floor_z, head)
    a = math.radians(az)
    # Azimuth 0 = in front of the character (-Y); positive shows its left side.
    axis = Vector((math.sin(a), -math.cos(a), 0.0))
    scene = bpy.context.scene

    cd = bpy.data.cameras.new(view)
    cd.lens = 50.0 if framing == "body" else 85.0
    dist = (frame_h * 0.5) / math.tan(math.atan(cd.sensor_width * 0.5 / cd.lens))
    cam = bpy.data.objects.new(view, cd)
    scene.collection.objects.link(cam)
    cam.location = target + axis * dist
    look_at(cam, target)

    od = bpy.data.cameras.new(view + "_ortho")
    od.type = "ORTHO"
    od.ortho_scale = frame_h
    od.clip_end = 100.0
    ortho = bpy.data.objects.new(view + "_ortho", od)
    scene.collection.objects.link(ortho)
    ortho.location = target + axis * 10.0
    look_at(ortho, target)
    return cam, ortho


def set_beauty_engine():
    scene = bpy.context.scene
    r = scene.render
    r.film_transparent = False
    r.image_settings.color_mode = "RGB"
    r.resolution_percentage = 100
    r.image_settings.file_format = "PNG"
    if ARGS.mode == "signoff":
        r.resolution_x = r.resolution_y = 1024
        r.engine = "CYCLES"
        c = scene.cycles
        c.device = "CPU"
        c.samples = 128
        c.use_adaptive_sampling = True
        c.use_denoising = True
        c.denoiser = "OPENIMAGEDENOISE"
        c.denoising_quality = "HIGH"
        c.denoising_prefilter = "ACCURATE"
        if hasattr(c, "denoising_use_gpu"):
            c.denoising_use_gpu = False
        c.max_bounces = 8
        c.transparent_max_bounces = 16
    else:
        r.resolution_x = r.resolution_y = 512
        r.engine = "BLENDER_EEVEE"
        scene.eevee.taa_render_samples = 16


def set_mask_engine():
    scene = bpy.context.scene
    r = scene.render
    r.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = 1
    r.resolution_x = r.resolution_y = MASK_RES
    r.film_transparent = True
    r.image_settings.color_mode = "RGBA"


def render(path):
    bpy.context.scene.render.filepath = path
    t = time.perf_counter()
    bpy.ops.render.render(write_still=True)
    return round(time.perf_counter() - t, 3)


# ---------------------------------------------------------------- masks

def load_mask(path):
    """bool[h, w] from a mask PNG (white = character), or None."""
    if not path or not os.path.exists(path):
        return None
    img = bpy.data.images.load(path, check_existing=False)
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    bpy.data.images.remove(img)
    return px.reshape(h, w, 4)[..., 0] > 0.5


def alpha_to_mask(rgba_path, mask_path):
    img = bpy.data.images.load(rgba_path, check_existing=False)
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    bpy.data.images.remove(img)
    m = px.reshape(h, w, 4)[..., 3] > 0.5
    out = np.zeros((h, w, 4), dtype=np.float32)
    out[m] = 1.0
    out[..., 3] = 1.0
    mi = bpy.data.images.new("mask", w, h, alpha=False)
    mi.pixels.foreach_set(out.ravel())
    mi.filepath_raw = mask_path
    mi.file_format = "PNG"
    mi.save()
    bpy.data.images.remove(mi)
    os.remove(rgba_path)
    return m


def iou(a, b):
    if a is None or b is None or a.shape != b.shape:
        return None
    u = np.logical_or(a, b).sum()
    return round(float(np.logical_and(a, b).sum() / u), 4) if u else None


def mask_extent(m, metres_per_px):
    """Height and width of the silhouette bbox, in metres."""
    ys, xs = np.nonzero(m)
    if len(xs) == 0:
        return None
    return {"height_m": round((ys.max() - ys.min() + 1) * metres_per_px, 4),
            "width_m": round((xs.max() - xs.min() + 1) * metres_per_px, 4),
            "area_px": int(m.sum())}


# ---------------------------------------------------------------- metrics

def mesh_tris(o):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = o.evaluated_get(dg)
    me = ev.to_mesh()
    me.calc_loop_triangles()
    n = len(me.loop_triangles)
    ev.to_mesh_clear()
    return n


def landmarks(arm, meshes):
    """Proportion metrics from joint positions and the body mesh (rest pose)."""
    mw = arm.matrix_world
    j = {b.name: mw @ b.head_local for b in arm.data.bones}
    body = next(o for o in meshes if part_name(o) == "body")
    co = np.array([(body.matrix_world @ v.co)[:] for v in body.data.vertices])
    floor_z = min(float(np.array([(o.matrix_world @ Vector(c))[:] for c in o.bound_box])[:, 2].min())
                  for o in meshes)
    top_z = float(co[:, 2].max())
    stature = top_z - floor_z

    head_gi = body.vertex_groups["head"].index if "head" in body.vertex_groups else None
    hw = np.zeros(len(co))
    if head_gi is not None:
        for v in body.data.vertices:
            for g in v.groups:
                if g.group == head_gi:
                    hw[v.index] = g.weight
    head_co = co[hw >= 0.5]
    head_h = float(top_z - head_co[:, 2].min()) if len(head_co) else None
    head_w = float(np.ptp(head_co[:, 0])) if len(head_co) else None
    head_d = float(np.ptp(head_co[:, 1])) if len(head_co) else None

    def dist(a, b):
        return float((j[a] - j[b]).length) if a in j and b in j else None

    def r(x, y):
        return round(x / y, 4) if x and y else None

    shoulder_w = dist("upperarm_l", "upperarm_r")
    hip_w = dist("thigh_l", "thigh_r")
    hip_z = (j["thigh_l"].z + j["thigh_r"].z) * 0.5 if "thigh_l" in j else None
    leg = hip_z - floor_z if hip_z is not None else None
    torso = j["neck_01"].z - hip_z if "neck_01" in j and hip_z is not None else None
    arm_len = ((dist("upperarm_l", "lowerarm_l") or 0) + (dist("lowerarm_l", "hand_l") or 0)) or None
    raw = {"stature_m": stature, "head_height_m": head_h, "head_width_m": head_w,
           "head_depth_m": head_d, "shoulder_joint_width_m": shoulder_w,
           "hip_joint_width_m": hip_w, "leg_length_m": leg, "torso_length_m": torso,
           "arm_length_m": arm_len}
    out = {k: (round(v, 4) if v is not None else None) for k, v in raw.items()}
    out.update({
        "heads_tall": r(stature, head_h),
        "shoulder_to_hip": r(shoulder_w, hip_w),
        "leg_to_torso": r(leg, torso),
        "leg_to_stature": r(leg, stature),
        "arm_to_stature": r(arm_len, stature),
        "head_width_to_height": r(head_w, head_h),
        "head_width_to_shoulder": r(head_w, shoulder_w),
    })
    return out, floor_z, (mw @ ((arm.data.bones["head"].head_local + arm.data.bones["head"].tail_local) * 0.5)
                          if "head" in arm.data.bones else Vector((0, 0, top_z - 0.13)))


def weights_per_vertex(meshes, bone_names):
    worst = 0
    for o in meshes:
        idx = {g.index for g in o.vertex_groups if g.name in bone_names}
        for v in o.data.vertices:
            worst = max(worst, sum(1 for g in v.groups if g.group in idx and g.weight > 1e-4))
    return worst


# ---------------------------------------------------------------- main

def main():
    out = os.path.abspath(ARGS.out_dir)
    os.makedirs(out, exist_ok=True)
    with timed("import_glb"):
        arm, meshes = import_character(ARGS.glb)
    with timed("metrics"):
        lm, floor_z, head = landmarks(arm, meshes)
        parts = {}
        for o in meshes:
            parts[part_name(o)] = parts.get(part_name(o), 0) + mesh_tris(o)
        bone_names = {b.name for b in arm.data.bones}
        metrics = {
            "glb": os.path.abspath(ARGS.glb), "mode": ARGS.mode,
            "tris": {"total": sum(parts.values()), "parts": dict(sorted(parts.items()))},
            "bones": len(arm.data.bones),
            "max_weights_per_vertex": weights_per_vertex(meshes, bone_names),
            "landmarks": lm,
        }
    floor, lights = build_studio(floor_z)
    views = [v for v in ARGS.views.split(",") if v]
    cams = {v: make_cameras(v, floor_z, head) for v in views}
    scene = bpy.context.scene

    frames = []
    set_beauty_engine()
    for v in views:
        scene.camera = cams[v][0]
        frames.append({"view": v, "pass": "beauty",
                       "seconds": render(os.path.join(out, f"{v}.png"))})
        print(f"[lookdev] {ARGS.mode} {v}: {frames[-1]['seconds']:.2f} s", flush=True)

    floor.hide_render = True
    set_mask_engine()
    masks, sil = {}, {}
    for v in views:
        scene.camera = cams[v][1]
        tmp = os.path.join(out, f"{v}_alpha.png")
        frames.append({"view": v, "pass": "mask", "seconds": render(tmp)})
        masks[v] = alpha_to_mask(tmp, os.path.join(out, f"{v}_mask.png"))
        sil[v] = mask_extent(masks[v], cams[v][1].data.ortho_scale / MASK_RES)
    floor.hide_render = False

    def score(d):
        if not d:
            return None
        return {v: iou(masks[v], load_mask(os.path.join(d, f"{v}_mask.png"))) for v in views}

    metrics["silhouette"] = sil
    metrics["iou_target"] = score(ARGS.target)
    metrics["iou_prev"] = score(ARGS.prev)
    metrics["prev_run"] = os.path.abspath(ARGS.prev) if ARGS.prev else None
    metrics["render"] = {
        "engine": "CYCLES" if ARGS.mode == "signoff" else "BLENDER_EEVEE",
        "res": 1024 if ARGS.mode == "signoff" else 512, "mask_res": MASK_RES,
        "frames": frames}
    try:
        import gpu
        metrics["render"]["gpu"] = gpu.platform.renderer_get()
    except Exception:  # noqa: BLE001 - informational only
        pass
    metrics["timings_s"] = TIMINGS
    metrics["blender"] = bpy.app.version_string
    with open(os.path.join(out, "render_metrics.json"), "w") as f:
        json.dump(metrics, f, indent=2)
    print(json.dumps({k: metrics[k] for k in ("tris", "landmarks", "iou_prev")}, indent=2))


main()
