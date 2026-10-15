"""Headless MPFB2 character build: human -> game_engine rig -> suit -> skinned GLB.

Drives the stage modules in blender/character/ (stage order in its
__init__.py), from one config (blender/character/config.py defaults, an
optional --config JSON override, then the legacy CLI flags). Run:

    blender -b -t 3 --factory-startup --python blender/build_character.py -- \
        --system-assets data/raw/makehuman/makehuman_system_assets/unpacked \
        --suit-assets   data/raw/makehuman/suits01/unpacked \
        --out           data/build/character/character.glb [--config cand.json] [--fan fan.json]

--fan names an optional private layer: a JSON file whose "fan" block (paths relative to the
file) feeds character/head_layer.py and whose optional "config" block is deep-merged over the build
config. Without it the build is unchanged. The FAN_CONFIG environment variable is not read here
(bench/m1/lookdev.sh reads it and passes --fan). A build that carries likeness content (--fan, a
"fan" block or a private/likeness/ path in the --config file, or a --config file under private/)
must write under <main checkout>/private/: any other --out is refused before Blender does any
work (pipeline/likeness/containment.py, NOTES.md §14 rule 7).

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
sys.path.append(os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pipeline", "likeness")))

import containment  # noqa: E402

from character import (beard_groom, body, budgets, config, export, hair,  # noqa: E402
                       hand_nails, head, rig, stats, suit)
from character.context import Build, Mpfb  # noqa: E402


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--system-assets", required=True)
    ap.add_argument("--suit-assets", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--config", help="JSON override, deep-merged over the defaults")
    ap.add_argument("--fan", help="optional private layer; see character/head_layer.py")
    # Legacy spike-1 flags; when given they override the config.
    ap.add_argument("--suit")
    ap.add_argument("--shoes")
    ap.add_argument("--hair")
    ap.add_argument("--skin")
    ap.add_argument("--rig")
    ap.add_argument("--max-influences", type=int)
    ap.add_argument("--ktx2", action="store_true", help="also write <out stem>.ktx2.glb (export.ktx2)")
    ap.add_argument("--lod1", action="store_true",
                    help="also write <out stem>.lod1.glb (+ .lod1.ktx2.glb with --ktx2): the gameplay LOD (export.lod1)")
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
    cfg = config.load(a.config, over)
    return config.merge(cfg, load_fan(a.fan)) if a.fan else cfg


def load_fan(path):
    """The fan file's "config" block (deep-merged) plus its "fan" block with absolute paths."""
    path = os.path.abspath(path)
    with open(path) as f:
        spec = json.load(f)
    fan = dict(spec.get("fan", {}))
    for k in ("face_delta", "dump_base"):
        if fan.get(k):
            fan[k] = os.path.join(os.path.dirname(path), fan[k])
    return config.merge(spec.get("config", {}), {"fan": fan})


def contain(a, cfg):
    """Refuse a build carrying likeness content unless every output it writes is private."""
    if os.environ.get("FAN_CONFIG") and not a.fan:
        print("[build] note: FAN_CONFIG is not read by build_character.py; pass --fan for a fan build")
    why = (["--fan"] if a.fan else []) + containment.likeness(cfg)
    if a.config and containment.is_private(a.config):
        why.append(f"--config under {containment.private_root()}/")
    if not why:
        return
    containment.assert_private(a.out, f"--out of a likeness build ({', '.join(why[:3])})")
    if (cfg.get("fan") or {}).get("dump_base"):
        containment.assert_private(cfg["fan"]["dump_base"], "fan dump_base")


def main():
    a = parse_args()
    cfg = build_config(a)
    contain(a, cfg)
    b = Build(cfg)
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
    b.step("facial_hair_refit", beard_groom.refit)  # beard/brows/lashes follow the refined skin
    b.step("rig_post", rig.post)
    b.step("hand_nails", hand_nails.build)  # Track G: nail plates, weights copied after rig.post
    b.step("budgets", budgets.apply)
    b.step("fix_alpha", export.fix_alpha)
    s = b.step("stats", stats.collect)

    out = os.path.abspath(a.out)
    stem = out[:-4] if out.endswith(".glb") else out
    b.step("export_glb", export.write_glb, out)
    if a.ktx2:
        b.step("export_ktx2", export.ktx2, out)
    if a.lod1:
        b.step("export_lod1", export.lod1, out)
    b.step("head_hero", head.hero)  # Cycles-only skin and eyes, after the GLB export (track A)
    b.step("hand_nails_hero", hand_nails.hero)  # Cycles-only nail material (track G)
    b.step("suit_hero", suit.hero)  # hero-only (Cycles) suit detail: after the GLB, into the .blend only
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
