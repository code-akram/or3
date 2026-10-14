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

--blend RUN/character.blend renders the same bald clay strip of a kept public build instead (no
build, no measures; hair, beard, brows, lashes, suit and the hero-only eye shells hidden), and
--turntable adds DIR/turntable.png (eight views, 45 deg apart) and DIR/vault.png (the cranium:
profile, back, high back 3/4, top-back), on a build as well:

    blender -b -t 3 --factory-startup --python-exit-code 1 --python bench/m1/head_quick.py -- \
        --blend RUN/character.blend --out DIR [--turntable]
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
    ap.add_argument("--system-assets", default="")
    ap.add_argument("--suit-assets", default="")
    ap.add_argument("--blend", default="", help="render a kept public build instead of building")
    ap.add_argument("--turntable", action="store_true")
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


HIDE = ("eyebrow", "eyelash", "teeth", "tongue", "hair", "beard", "brow", "lash", "groom", "clump", "cap_",
        "vellus", "stubble", "card", "suit", "nail", "cornea", "tear", "meniscus", "caruncle", "hero")


# the vault: the whole cranium (profile, back, high back three-quarter, top-back), framed on the
# middle of the head (85 mm behind and 30 mm above the eyes)
VAULT = [("v_profile", 90, 0, "studio"), ("v_back", 180, 0, "studio"), ("v_bq", 135, 25, "studio"),
         ("v_top", 180, 60, "studio")]


def render(b, a, views=VIEWS, name="strip", dz=-0.045, dy=0.0, shadows=True):
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_WORKBENCH"
    sc.display.shading.light = "STUDIO"
    sc.display.shading.color_type = "MATERIAL"
    sc.display.shading.show_cavity = False
    sc.display.shading.show_shadows = shadows     # off for the vault: no hard terminator across the scalp
    sc.display.shadow_focus = 0.9
    sc.render.resolution_x = sc.render.resolution_y = a.res
    sc.render.film_transparent = False
    sc.world = sc.world or bpy.data.worlds.new("w")
    sc.view_settings.view_transform = "Standard"
    m = clay()
    for o in bpy.data.objects:
        if o.type in ("CURVES", "CURVE", "POINTCLOUD"):     # strand groom, beard, vellus
            o.hide_render = True
        if o.type != "MESH":
            continue
        for md in o.modifiers:
            if md.type == "PARTICLE_SYSTEM":
                md.show_render = False
        n = o.name.lower()
        if "low-poly" in n or "eyes" in n:
            continue
        if any(k in n for k in HIDE):
            o.hide_render = True
            continue
        o.data.materials.clear()
        o.data.materials.append(m)
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    eyes = head_measure.find_eyes(bpy.data.objects) or max(
        (o for o in bpy.data.objects if o.type == "MESH" and "eyes" in o.name.lower() and not o.hide_render),
        key=lambda o: len(o.data.vertices))
    eco = [eyes.matrix_world @ v.co for v in eyes.data.vertices]
    target = sum(eco, Vector()) / len(eco) + Vector((0, dy, dz))
    cd = bpy.data.cameras.new("quick")
    cd.lens = 85
    cd.sensor_fit = "VERTICAL"
    cam = bpy.data.objects.new("quick", cd)
    sc.collection.objects.link(cam)
    sc.camera = cam
    dist = a.frame / 2 / math.tan(math.atan(cd.sensor_height / 2 / cd.lens))
    files = []
    for vname, az, el, light in views:
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
        p = os.path.join(a.out, f"quick_{vname}.png")
        sc.render.filepath = p
        bpy.ops.render.render(write_still=True)
        files.append(p)
    out = os.path.join(a.out, f"{name}.png")
    try:
        subprocess.run(["magick", *files, "+append", "-resize", "x420", out], check=True)
    except (OSError, subprocess.CalledProcessError):
        out = None
    return out, arm


def turntables(a):
    """--turntable: DIR/turntable.png (eight views, 45 deg apart) and DIR/vault.png (VAULT)."""
    if not a.turntable:
        return
    tt = [(f"tt{k:03d}", k, 4, "studio") for k in range(0, 360, 45)]
    print(f"[quick] turntable -> {render(None, a, tt, 'turntable')[0]}")
    print(f"[quick] vault -> {render(None, a, VAULT, 'vault', dz=0.03, dy=0.085, shadows=False)[0]}")


def main():
    a = args()
    os.makedirs(a.out, exist_ok=True)
    if a.blend:
        if containment.is_private(a.blend):
            raise SystemExit("head_quick.py --blend is for public builds only")
        bpy.ops.wm.open_mainfile(filepath=os.path.abspath(a.blend))
        st = os.path.splitext(a.blend)[0] + ".stats.json"
        if not os.path.exists(st) or containment.likeness(json.load(open(st))):
            raise SystemExit("head_quick.py --blend: not a public build (missing or likeness stats)")
        print(f"[quick] strip -> {render(None, a)[0]}")
        turntables(a)
        return
    if not (a.system_assets and a.suit_assets):
        raise SystemExit("--system-assets and --suit-assets are needed to build")
    b = build(a)
    m = b.notes.get("spec_landmarks", {})
    res = {"spec_landmarks": m, "spec_checks": b.notes.get("spec_checks"),
           "layers": {k: b.notes.get(k) for k in ("head_layer", "head_sculpt", "head_edits", "head_forms")}}
    with open(os.path.join(a.out, "head_measures.json"), "w") as f:
        json.dump(res, f, indent=1, default=str)
    strip, _ = render(b, a)
    turntables(a)
    if a.save_blend:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(a.out, "head.blend"))
    keys = ("bizygomatic", "bigonial", "jaw_to_cheek", "lower_face_index", "brow_overhang",
            "forehead_behind_brow_mm", "orbit_recess_mm", "eye_aperture_mm", "canthal_tilt_deg",
            "gonial_angle_deg", "nose_hump_mm", "nose_proj_ratio")
    print("[quick] " + "  ".join(f"{k}={m[k]}" for k in keys if k in m))
    print(f"[quick] strip -> {strip}")


main()
