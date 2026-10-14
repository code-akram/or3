"""Hero close-ups of the face from a kept build .blend (m1 v2 track A).

Renders the staged .blend (not the GLB), so the Cycles-only material chains
(skin subsurface, micro-detail, the refractive cornea, the tear meniscus)
and the `hero_only` geometry show. Shots are placed in the face frame (eye
centres from the eye mesh) at fixed metric framings, so runs compare 1:1.

    KEEP_BLEND=1 bench/m1/lookdev.sh --config CFG LABEL        # gives RUN/character.blend
    blender -b -t 4 --factory-startup --python-exit-code 1 \
        --python bench/m1/head_closeups.py -- --blend RUN/character.blend --out RUN/hero \
        [--rigs studio,neon] [--shots bust,face_front,...] [--res 640] [--samples 96] \
        [--engine cycles|eevee] [--clay]

Rigs:
  studio  the look-dev rig (bench/m1/README.md "Cameras and lighting"): key
          front-left-high 900 W, fill 250 W, rim 700 W, near-black world,
          AgX, -2.5 EV.
  neon    the neon-noir hero light after bench/m1/v2/direction.md §5: amber
          key 40° camera-left / 25° up at 1.5 m, magenta strip rim behind-
          right 0.7, teal kicker behind-left 0.4, cool fill 0.08, a small eye
          light at the camera 0.12 (ratios of the key irradiance).

Writes <out>/<rig>_<shot>.png and <out>/sheet_<rig>.png (shots side by side).
"""

import argparse
import math
import os
import subprocess
import sys

import bpy
import numpy as np
from mathutils import Vector

# name: (target, azimuth deg (+ = character's left side), elevation deg,
#        frame height m, hide hair?)
SHOTS = {
    "bust":       ("head", 25.0, 0.0, 0.42, False),
    "face_front": ("face", 0.0, 0.0, 0.26, True),
    "face_q":     ("face", -35.0, 0.0, 0.26, True),
    "profile":    ("face", -90.0, 0.0, 0.26, True),
    "eye":        ("eye_l", -20.0, 5.0, 0.06, True),
    "eye_macro":  ("eye_l", -15.0, 3.0, 0.030, True),
    "nose":       ("nose", -30.0, 0.0, 0.075, True),
    "mouth":      ("mouth", -15.0, -5.0, 0.075, True),
    "cheek":      ("cheek_l", 40.0, 0.0, 0.05, True),
    "forehead":   ("forehead", -20.0, 10.0, 0.07, True),
    "pores":      ("cheek_l", 35.0, 0.0, 0.020, True),
    "jaw_low":    ("face", -60.0, -12.0, 0.30, True),     # gonial angle and mandibular border
}
# head turntable, hair hidden (tt000 front, then every 45 deg toward the character's left)
SHOTS.update({f"tt{a:03d}": ("head", float(a if a <= 180 else a - 360), 5.0, 0.40, True) for a in range(0, 360, 45)})
HAIR = ("clump", "cap_", "hair", "long0", "groom")
KEEP = ("beard", "brow", "lash", "moustache")
STUDIO_EXPOSURE = -2.5


def parse():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--blend", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--rigs", default="studio")
    ap.add_argument("--shots", default="bust,face_q,eye,nose,mouth,cheek,forehead")
    ap.add_argument("--res", type=int, default=640)
    ap.add_argument("--samples", type=int, default=96)
    ap.add_argument("--engine", choices=["cycles", "eevee"], default="cycles")
    ap.add_argument("--clay", action="store_true", help="grey clay on the body (form check)")
    ap.add_argument("--exposure", type=float, default=None)
    return ap.parse_args(argv)


A = parse()


def look_at(ob, target):
    ob.rotation_euler = (target - ob.location).to_track_quat("-Z", "Y").to_euler()


def meshes():
    return [o for o in bpy.data.objects if o.type == "MESH"]


def is_hair(o):
    n = o.name.lower()
    return any(k in n for k in HAIR) and not any(k in n for k in KEEP)


def body_obj():
    return max((o for o in meshes() if "body" in o.vertex_groups), key=lambda o: len(o.data.vertices))


def eye_centres():
    eyes = next((o for o in meshes() if "eyes_hq" in o.name), None) \
        or next((o for o in meshes() if "low-poly" in o.name), None)
    co = np.array([(eyes.matrix_world @ v.co)[:] for v in eyes.data.vertices])
    return Vector(co[co[:, 0] > 0].mean(0)), Vector(co[co[:, 0] < 0].mean(0))


def targets():
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    head = arm.matrix_world @ arm.data.bones["head"].head_local
    cl, cr = eye_centres()
    mid = (cl + cr) * 0.5
    s = (cl - cr).length / 0.0616
    t = {
        "head": head + Vector((0, 0, -0.03)),
        "face": mid + Vector((0, 0.01, -0.045)) * s,
        "eye_l": cl + Vector((0.0, -0.012, 0.002)) * s,
        "nose": mid + Vector((0, -0.03, -0.03)) * s,
        "mouth": mid + Vector((0, -0.02, -0.075)) * s,
        "cheek_l": mid + Vector((0.042, -0.012, -0.03)) * s,
        "forehead": mid + Vector((0.0, -0.012, 0.045)) * s,
    }
    return t, head


def clear_lights():
    for o in list(bpy.data.objects):
        if o.type in ("LIGHT", "CAMERA") or o.name.startswith("hc_floor"):
            bpy.data.objects.remove(o, do_unlink=True)


def area(name, loc, aim, energy, size, color, size_y=None):
    ld = bpy.data.lights.new(name, "AREA")
    ld.energy, ld.color = energy, color
    if size_y:
        ld.shape = "RECTANGLE"
        ld.size, ld.size_y = size, size_y
    else:
        ld.size = size
    ob = bpy.data.objects.new(name, ld)
    bpy.context.scene.collection.objects.link(ob)
    ob.location = loc
    look_at(ob, aim)
    return ob


def world(color, strength=1.0):
    sc = bpy.context.scene
    w = sc.world or bpy.data.worlds.new("hc_world")
    sc.world = w
    w.use_nodes = True
    bg = w.node_tree.nodes.get("Background")
    bg.inputs[0].default_value = (*color, 1.0)
    bg.inputs[1].default_value = strength


def floor(z):
    bpy.ops.mesh.primitive_plane_add(size=60, location=(0, 0, z))
    f = bpy.context.active_object
    f.name = "hc_floor"
    m = bpy.data.materials.new("hc_floor")
    m.use_nodes = True
    p = m.node_tree.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = (0.08, 0.08, 0.085, 1)
    p.inputs["Roughness"].default_value = 0.8
    f.data.materials.append(m)


def rig_studio(floor_z, head, cam_dir):
    world((0.045, 0.045, 0.05))
    aim = Vector((0, 0, floor_z + 1.1))
    area("key", Vector((-2.2, -2.6, 2.8 + floor_z)), aim, 900, 1.5, (1.0, 0.96, 0.9))
    area("fill", Vector((2.6, -2.0, 1.4 + floor_z)), aim, 250, 2.0, (0.85, 0.9, 1.0))
    area("rim", Vector((0.8, 2.8, 2.6 + floor_z)), aim, 700, 1.0, (1, 1, 1))
    return STUDIO_EXPOSURE


def rig_neon(floor_z, head, cam_dir):
    """direction.md §5 base rig, placed relative to the camera direction
    (cam_dir: unit vector from the head toward the camera, horizontal)."""
    world((0.004, 0.005, 0.008))
    up = Vector((0, 0, 1))
    right = cam_dir.cross(up).normalized()      # camera's left when looking at the head
    d = 1.5
    K = 160.0   # key watts at 1.5 m

    def at(az_deg, el_deg, dist):
        a, e = math.radians(az_deg), math.radians(el_deg)
        v = (cam_dir * math.cos(a) + right * math.sin(a)) * math.cos(e) + up * math.sin(e)
        return head + v * dist
    # key: 40° camera-left, 25° up, amber 3000 K
    area("key", at(40, 25, d), head, K, 0.8, (1.0, 0.66, 0.38))
    # magenta strip rim, behind-right (camera-right = -right)
    area("rim_magenta", at(-140, 10, d), head, K * 0.7 * 1.6, 0.3, (1.0, 0.18, 0.55), size_y=1.5)
    # teal kicker, behind-left
    area("kick_teal", at(135, 15, d), head, K * 0.4 * 1.6, 0.4, (0.1, 0.8, 0.9), size_y=1.0)
    # cool fill from camera-right, low
    area("fill", at(-50, 0, d), head, K * 0.08, 1.5, (0.55, 0.7, 1.0))
    return STUDIO_EXPOSURE + 0.3


def add_eye_light(cam, head):
    ld = bpy.data.lights.new("eye_light", "AREA")
    ld.size = 0.10
    ld.energy = 160.0 * 0.12 * ((cam.location - head).length / 1.5) ** 2
    ob = bpy.data.objects.new("eye_light", ld)
    bpy.context.scene.collection.objects.link(ob)
    ob.location = cam.location + Vector((0, 0, 0.12))
    look_at(ob, head)
    return ob


def clay():
    m = bpy.data.materials.new("hc_clay")
    m.use_nodes = True
    p = m.node_tree.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = (0.42, 0.40, 0.38, 1)
    p.inputs["Roughness"].default_value = 0.55
    b = body_obj()
    for i in range(len(b.data.materials)):
        b.data.materials[i] = m


def engine():
    sc = bpy.context.scene
    r = sc.render
    r.resolution_x = r.resolution_y = A.res
    r.resolution_percentage = 100
    r.film_transparent = False
    r.image_settings.file_format = "PNG"
    r.image_settings.color_mode = "RGB"
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.look = "None"
    if A.engine == "cycles":
        r.engine = "CYCLES"
        c = sc.cycles
        c.device = "CPU"
        c.samples = A.samples
        c.use_adaptive_sampling = True
        c.adaptive_threshold = 0.02
        c.use_denoising = True
        c.denoiser = "OPENIMAGEDENOISE"
        c.denoising_quality = "HIGH"
        c.denoising_prefilter = "ACCURATE"
        c.max_bounces = 12
        c.diffuse_bounces = 4
        c.glossy_bounces = 4
        c.transmission_bounces = 8
        c.transparent_max_bounces = 64
        c.caustics_reflective = False
        c.caustics_refractive = False
        c.blur_glossy = 0.5
    else:
        r.engine = "BLENDER_EEVEE"
        sc.eevee.taa_render_samples = 32


def main():
    bpy.ops.wm.open_mainfile(filepath=os.path.abspath(A.blend))
    os.makedirs(A.out, exist_ok=True)
    engine()
    if A.clay:
        clay()
    sc = bpy.context.scene
    zs = [(o.matrix_world @ Vector(o.bound_box[i])).z for o in meshes() for i in range(8)]
    floor_z = min(zs)
    T, head = targets()
    hair = [o for o in meshes() if is_hair(o)]
    for rig in [r for r in A.rigs.split(",") if r]:
        paths = []
        for shot in [s for s in A.shots.split(",") if s]:
            tname, az, el, frame_h, hide = SHOTS[shot]
            clear_lights()
            floor(floor_z)
            for o in hair:
                o.hide_render = hide
            a, e = math.radians(az), math.radians(el)
            cam_dir = Vector((math.sin(a), -math.cos(a), 0.0))
            axis = Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)))
            ev = (rig_studio if rig == "studio" else rig_neon)(floor_z, head, cam_dir)
            cd = bpy.data.cameras.new("hc_cam")
            cd.lens = 100.0 if frame_h < 0.2 else 85.0
            cd.clip_start = 0.01
            dist = (frame_h * 0.5) / math.tan(math.atan(cd.sensor_width * 0.5 / cd.lens))
            cam = bpy.data.objects.new("hc_cam", cd)
            sc.collection.objects.link(cam)
            cam.location = T[tname] + axis * dist
            look_at(cam, T[tname])
            sc.camera = cam
            if rig == "neon":
                add_eye_light(cam, T[tname])
            sc.view_settings.exposure = A.exposure if A.exposure is not None else ev
            p = os.path.join(A.out, f"{rig}_{shot}.png")
            sc.render.filepath = p
            bpy.ops.render.render(write_still=True)
            print(f"[closeups] {rig} {shot} -> {p} ({frame_h / A.res * 1000:.3f} mm/px)", flush=True)
            paths.append(p)
        for o in hair:
            o.hide_render = False
        inputs = [x for p in paths for x in ("-i", p)]
        fc = "".join(f"[{i}]" for i in range(len(paths))) + f"hstack={len(paths)}" if len(paths) > 1 else "null"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *inputs, "-filter_complex", fc,
                        os.path.join(A.out, f"sheet_{rig}.png")], check=True)


main()
