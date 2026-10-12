"""Suit-track dev loop: build the character with hair off (the suit does not
depend on it), export the GLB, then render the suit detail views. One process
for the build, a second for the views (the views script resets the scene).

    blender -b -t 4 --factory-startup --python bench/m1/suit_dev.py -- \
        --out DIR [--config bench/m1/variants/direction.json] [--override '{"suit": {...}}'] \
        [--views torso,lapel] [--wire] [--hide hair] [--no-render] [--hair] [--check] [--collar]

Writes DIR/character.glb, DIR/character.stats.json, DIR/<view>.png; --check runs
suit_check.py (silhouette holes, open armhole seams) into DIR/check/; --collar runs
suit_collar.py (the collar-zone guard, suit.md §6) into DIR/collar/.
"""

import argparse
import json
import os
import subprocess
import sys
import time

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "blender"))

from character import body, budgets, config, export, hair, head, rig, stats, suit  # noqa: E402
from character.context import Build, Mpfb  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--config", default=os.path.join(HERE, "variants", "direction.json"))
ap.add_argument("--override", default="{}")
ap.add_argument("--views", default="torso,torso34,lapel,gorge,notch,knot,shoulder,shoulder_back,collar_back,side,back")
ap.add_argument("--wire", action="store_true")
ap.add_argument("--hide", default="")
ap.add_argument("--no-render", action="store_true")
ap.add_argument("--hair", action="store_true", help="build the hair and beard too")
ap.add_argument("--check", action="store_true", help="run suit_check.py (holes, open seams) on the GLB")
ap.add_argument("--collar", action="store_true",
                help="run suit_collar.py (collar-zone guard: bare skin, backfaces, intersections) on the GLB")
ap.add_argument("--res", type=int, default=600)
ap.add_argument("--save-blend", action="store_true", help="also save DIR/character.blend (the staged scene)")
A = ap.parse_args(argv)

main_root = subprocess.run(["git", "-C", REPO, "rev-parse", "--path-format=absolute",
                            "--git-common-dir"], capture_output=True, text=True).stdout.strip()
data = os.environ.get("DATA") or os.path.join(os.path.dirname(main_root), "data")
over = {"assets": {"system": os.path.join(data, "raw/makehuman/makehuman_system_assets/unpacked"),
                   "suit": os.path.join(data, "raw/makehuman/suits01/unpacked")}}
if not A.hair:
    over["hair"] = {"clumps": None, "beard": None}
cfg = config.load(A.config, over)
cfg = config.merge(cfg, json.loads(A.override))

t0 = time.perf_counter()
b = Build(cfg)


def enable(b):
    b.mpfb = Mpfb(b.cfg["assets"]["system"], b.cfg["assets"]["suit"])
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)


b.step("enable_mpfb", enable)
b.step("create_human", body.create)
b.step("head_edits", head.edit_base)
b.step("rig", rig.add)
b.step("head_parts", head.add_parts)
b.step("hair", hair.add)
b.step("suit", suit.add)
b.step("stage_for_export", export.stage)
b.step("bake_targets", export.bake_targets)
b.step("head_post", head.post)
b.step("suit_post", suit.post)
b.step("hair_post", hair.post)
b.step("budgets", budgets.apply)
b.step("fix_alpha", export.fix_alpha)
s = b.step("stats", stats.collect)
os.makedirs(A.out, exist_ok=True)
glb = os.path.join(A.out, "character.glb")
b.step("export_glb", export.write_glb, glb)
s.update(b.notes)
s["timings_s"] = b.timings
s["config"] = cfg
with open(os.path.join(A.out, "character.stats.json"), "w") as f:
    json.dump(s, f, indent=2, default=str)
if A.save_blend:
    export.save_blend(b, os.path.join(A.out, "character.blend"))
print(f"[suit_dev] build {time.perf_counter() - t0:.1f} s, total tris {s['total_tris']}")
for name, m in sorted(s["meshes"].items()):
    if "suit" in name or "shoe" in name:
        print(f"  {name:40s} tris={m['tris']:6d} infl={m['source_influence_histogram']}")

if not A.no_render:
    cmd = [bpy.app.binary_path, "-b", "-t", "4", "--factory-startup", "--python-exit-code", "1",
           "--python", os.path.join(HERE, "suit_views.py"), "--", "--glb", glb, "--out-dir", A.out,
           "--views", A.views, "--res", str(A.res)]
    if A.wire:
        cmd.append("--wire")
    if A.hide:
        cmd += ["--hide", A.hide]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        print(r.stdout[-3000:], r.stderr[-3000:])
    print(f"[suit_dev] views in {A.out} ({time.perf_counter() - t0:.1f} s total)")

if A.check:
    r = subprocess.run([bpy.app.binary_path, "-b", "-t", "4", "--factory-startup", "--python",
                        os.path.join(HERE, "suit_check.py"), "--", "--glb", glb,
                        "--out-dir", os.path.join(A.out, "check")], capture_output=True, text=True)
    print("\n".join(l for l in r.stdout.splitlines() if l.startswith("[suit_check]")))
    if r.returncode:
        print(f"[suit_dev] suit_check FAILED (see {os.path.join(A.out, 'check', 'check.json')})")

if A.collar:
    r = subprocess.run([bpy.app.binary_path, "-b", "-t", "4", "--factory-startup", "--python",
                        os.path.join(HERE, "suit_collar.py"), "--", "--glb", glb,
                        "--out-dir", os.path.join(A.out, "collar"), "--beauty"], capture_output=True, text=True)
    print("\n".join(l for l in r.stdout.splitlines() if l.startswith("[suit_collar]")))
    if r.returncode:
        print(f"[suit_dev] suit_collar FAILED (see {os.path.join(A.out, 'collar', 'collar.json')})")

if os.environ.get("SUIT_TANGENT_CHECK"):
    sys.path.insert(0, "/tmp")
    import tangent_check
    tangent_check.check(b.meshes())
