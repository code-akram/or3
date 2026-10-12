"""Headless MPFB2 character build: human -> game_engine rig -> suit -> skinned GLB.

Drives the stage modules in blender/character/ (stage order in its
__init__.py), from one config (blender/character/config.py defaults, an
optional --config JSON override, then the legacy CLI flags). Run:

    blender -b -t 3 --factory-startup --python blender/build_character.py -- \
        --system-assets data/raw/makehuman/makehuman_system_assets/unpacked \
        --suit-assets   data/raw/makehuman/suits01/unpacked \
        --out           data/build/character/character.glb [--config cand.json]

--factory-startup keeps the user's saved scene/prefs out of the run; the MPFB
extension is enabled explicitly. Asset roots are injected into MPFB's
in-memory preferences only (never saved), so nothing global is modified.

Writes <out>, <out minus .glb>.blend (the staged scene, for renders) and
<out minus .glb>.stats.json (per-step timings, mesh/rig statistics, config).
"""

import argparse
import json
import os
import sys
import time

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from character import (body, budgets, config, export, hair, head,  # noqa: E402
                       rig, stats, suit)
from character.context import Build, Mpfb  # noqa: E402


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--system-assets", required=True)
    ap.add_argument("--suit-assets", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--config", help="JSON override, deep-merged over the defaults")
    # Legacy spike-1 flags; when given they override the config.
    ap.add_argument("--suit")
    ap.add_argument("--shoes")
    ap.add_argument("--hair")
    ap.add_argument("--skin")
    ap.add_argument("--rig")
    ap.add_argument("--max-influences", type=int)
    return ap.parse_args(argv)


def build_config(a):
    over = {"assets": {"system": a.system_assets, "suit": a.suit_assets}}
    if a.suit or a.shoes:
        clothes = list(config.DEFAULTS["suit"]["clothes"])
        clothes[0] = a.suit or clothes[0]
        clothes[1] = a.shoes or clothes[1]
        over["suit"] = {"clothes": clothes}
    if a.hair:
        over["hair"] = {"asset": a.hair}
    if a.skin:
        over["body"] = {"skin": a.skin}
    if a.rig:
        over["rig"] = {"builtin": a.rig}
    if a.max_influences:
        over["export"] = {"max_influences": a.max_influences}
    return config.load(a.config, over)


def main():
    a = parse_args()
    b = Build(build_config(a))
    b.out_dir = os.path.dirname(os.path.abspath(a.out))

    def enable(b):
        b.mpfb = Mpfb(b.cfg["assets"]["system"], b.cfg["assets"]["suit"])
        for o in list(bpy.data.objects):  # factory startup: cube, camera, light
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
    b.step("hair_post", hair.post)  # after the suit, so hair collides with the final collar
    b.step("head_refine", head.refine)  # dense face/hands, skin and eye textures (hair/beard sampled the low-res body)
    b.step("rig_post", rig.post)
    b.step("budgets", budgets.apply)
    b.step("fix_alpha", export.fix_alpha)
    s = b.step("stats", stats.collect)

    out = os.path.abspath(a.out)
    stem = out[:-4] if out.endswith(".glb") else out
    b.step("export_glb", export.write_glb, out)
    b.step("head_hero", head.hero)  # Cycles-only skin and eyes, after the GLB export (track A)
    b.step("save_blend", export.save_blend, stem + ".blend")

    s.update(b.notes)
    s["timings_s"] = b.timings
    s["total_s"] = round(time.perf_counter() - b.t0, 3)
    s["glb_bytes"] = os.path.getsize(out)
    s["blender"] = bpy.app.version_string
    s["threads"] = bpy.context.scene.render.threads
    s["config"] = b.cfg
    with open("/proc/loadavg") as f:
        s["loadavg_end"] = f.read().strip()
    with open(stem + ".stats.json", "w") as f:
        json.dump(s, f, indent=2)
    print(json.dumps({k: v for k, v in s.items() if k not in ("meshes", "config")}, indent=2))
    for name, m in s["meshes"].items():
        print(f"  {name:40s} tris={m['tris']:6d} verts={m['verts']:6d} "
              f"infl={m['source_influence_histogram']}")


main()
