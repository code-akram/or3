"""Quick head loop: build only the nude head (MPFB human, head edits, rig, face parts), print the
head measures, and render a bald clay strip with Workbench (seconds, CPU, no GPU).

For iterating on head_shape / head_layer / head_sculpt and the eye block between full lookdev
runs. Public builds only (refuses a fan config, like build_character.py does for data/).

    blender -b -t 3 --factory-startup --python-exit-code 1 --python bench/m1/head_quick.py -- \
        --system-assets DATA/raw/makehuman/makehuman_system_assets/unpacked \
        --suit-assets DATA/raw/makehuman/suits01/unpacked \
        --config bench/m1/variants/direction.json [--config more.json] --out DIR [--res 640] [--save-blend]

Writes DIR/head_measures.json, DIR/strip.png (front, 3/4, profile, low 3/4 for the jaw angle,
plus a raking key on the front) and optionally DIR/head.blend.
"""

import argparse
import json
import math
import os
import subprocess
import sys

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO, "blender"))
sys.path.append(os.path.join(REPO, "pipeline", "likeness"))

import containment  # noqa: E402

from character import body, config, head, head_measure, rig  # noqa: E402
from character.context import Build, Mpfb  # noqa: E402

# name: (azimuth deg, elevation deg, light) ; azimuth 0 = front, + shows the character's left
VIEWS = [("front", 0, 0, "studio"), ("rake", 0, 0, "rake"), ("tq", 35, 3, "studio"),
         ("profile", 90, 0, "studio"), ("jaw", 60, -12, "studio")]


def args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--system-assets", required=True)
    ap.add_argument("--suit-assets", required=True)
    ap.add_argument("--config", action="append", default=[], help="JSON override; repeat to merge in order")
    ap.add_argument("--out", required=True)
    ap.add_argument("--res", type=int, default=640)
    ap.add_argument("--frame", type=float, default=0.30, help="frame height, metres")
    ap.add_argument("--save-blend", action="store_true")
    return ap.parse_args(argv)


def build(a):
    cfg = config.load(None, {"assets": {"system": a.system_assets, "suit": a.suit_assets}})
    for path in a.config:
        with open(path) as f:
            cfg = config.merge(cfg, json.load(f))
    if containment.likeness(cfg) or any(containment.is_private(p) for p in a.config):
        raise SystemExit("head_quick.py is for public builds only")
    b = Build(cfg)
    b.out_dir = os.path.abspath(a.out)
    b.mpfb = Mpfb(cfg["assets"]["system"], cfg["assets"]["suit"])
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    b.step("create_human", body.create)
    b.step("head_edits", head.edit_base)
    b.step("rig", rig.add)
    b.step("head_parts", head.add_parts)
    return b


def clay():
    m = bpy.data.materials.new("quick_clay")
    m.diffuse_color = (0.62, 0.55, 0.50, 1.0)
    return m


def render(b, a):
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_WORKBENCH"
    sc.display.shading.light = "STUDIO"
    sc.display.shading.color_type = "MATERIAL"
    sc.display.shading.show_cavity = False
    sc.display.shading.show_shadows = True
    sc.display.shadow_focus = 0.9
    sc.render.resolution_x = sc.render.resolution_y = a.res
    sc.render.film_transparent = False
    sc.world = sc.world or bpy.data.worlds.new("w")
    sc.view_settings.view_transform = "Standard"
    m = clay()
    for o in bpy.data.objects:
        if o.type != "MESH":
            continue
        n = o.name.lower()
        if any(k in n for k in ("eyebrow", "eyelash", "teeth", "tongue")):
            o.hide_render = True
            continue
        if "low-poly" in n or "eyes" in n:
            continue
        o.data.materials.clear()
        o.data.materials.append(m)
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    eyes = head_measure.find_eyes(bpy.data.objects)
    eco = [eyes.matrix_world @ v.co for v in eyes.data.vertices]
    target = sum(eco, Vector()) / len(eco) + Vector((0, 0, -0.045))
    cd = bpy.data.cameras.new("quick")
    cd.lens = 85
    cd.sensor_fit = "VERTICAL"
    cam = bpy.data.objects.new("quick", cd)
    sc.collection.objects.link(cam)
    sc.camera = cam
    dist = a.frame / 2 / math.tan(math.atan(cd.sensor_height / 2 / cd.lens))
    files = []
    for name, az, el, light in VIEWS:
        th, ph = math.radians(az), math.radians(el)
        d = Vector((math.sin(th) * math.cos(ph), -math.cos(th) * math.cos(ph), math.sin(ph)))
        cam.location = target + d * dist
        cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
        sh = sc.display.shading
        if light == "rake":                                     # high key from the character's left
            sc.display.light_direction = (0.55, -0.25, 0.80)
            sh.shadow_intensity = 0.85
        else:
            sc.display.light_direction = (0.35, -0.45, 0.82)
            sh.shadow_intensity = 0.5
        p = os.path.join(a.out, f"quick_{name}.png")
        sc.render.filepath = p
        bpy.ops.render.render(write_still=True)
        files.append(p)
    out = os.path.join(a.out, "strip.png")
    try:
        subprocess.run(["magick", *files, "+append", "-resize", "x420", out], check=True)
    except (OSError, subprocess.CalledProcessError):
        out = None
    return out, arm


def main():
    a = args()
    os.makedirs(a.out, exist_ok=True)
    b = build(a)
    m = b.notes.get("spec_landmarks", {})
    res = {"spec_landmarks": m, "spec_checks": b.notes.get("spec_checks"),
           "layers": {k: b.notes.get(k) for k in ("head_layer", "head_sculpt", "head_edits", "head_forms")}}
    with open(os.path.join(a.out, "head_measures.json"), "w") as f:
        json.dump(res, f, indent=1, default=str)
    strip, _ = render(b, a)
    if a.save_blend:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(a.out, "head.blend"))
    keys = ("bizygomatic", "bigonial", "jaw_to_cheek", "lower_face_index", "brow_overhang",
            "forehead_behind_brow_mm", "orbit_recess_mm", "eye_aperture_mm", "canthal_tilt_deg",
            "gonial_angle_deg", "nose_hump_mm", "nose_proj_ratio")
    print("[quick] " + "  ".join(f"{k}={m[k]}" for k in keys if k in m))
    print(f"[quick] strip -> {strip}")


main()
