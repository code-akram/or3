"""Upsert the provenance record of the shipped character GLB (stdlib only).

    python3 -I bench/m1/character_provenance.py --data-root DATA \
        [--glb build/character/character.glb]

Reads <glb>.stats.json written by blender/build_character.py next to the GLB
and rewrites the `mesh:character/character.glb` record in
provenance/mesh.jsonl (bytes, sha256, and transformations from the build
config). Run it after a build you intend to ship, then audit:
python3 -I provenance/audit.py --data-root DATA --check-files
"""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "provenance" / "mesh.jsonl"
RID = "mesh:character/character.glb"


def transformations(stats):
    c = stats["config"]
    out = [
        f"MPFB 2.0.18 HumanService.create_human, macros {json.dumps(c['body']['macros'], sort_keys=True)}, "
        f"race {json.dumps(c['body']['race'], sort_keys=True)}; skin {c['body']['skin']} (GAMEENGINE)",
        f"builtin rig '{c['rig']['builtin']}' with MPFB weights",
        "fitted proxies (subdiv 0, GAMEENGINE): "
        + ", ".join(p[1] for p in c["head"]["parts"])
        + f", hair {c['hair']['asset']}, clothes " + ", ".join(c["suit"]["clothes"]),
        "ExportService.create_character_copy + bake_modifiers_remove_helpers (clothes delete-masks baked)",
        "macro shape keys baked into the meshes (TargetService.bake_targets)",
    ]
    for name, d in (stats.get("decimated") or {}).items():
        if d["after"] < d["before"]:
            out.append(f"{name}: Blender Decimate COLLAPSE (triangulate) {d['before']} -> {d['after']} tris")
    out += [
        "material alpha: opaque links dropped; cut-outs (" + ", ".join(
            k for k, v in stats.get("alpha_modes", {}).items() if v == "MASK") + ") routed through ROUND -> MASK",
        f"glTF export: GLB, skins, {c['export']['max_influences']} influences/vertex, tangents, no animation, no morphs",
    ]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", required=True, type=Path)
    ap.add_argument("--glb", default="build/character/character.glb")
    a = ap.parse_args()
    glb = a.data_root / a.glb
    stats_path = glb.with_suffix(".stats.json")
    stats = json.loads(stats_path.read_text())
    data = glb.read_bytes()
    rec = {
        "id": RID, "kind": "derived", "domain": "mesh",
        "title": "Character, skinned GLB (MPFB base + suits01; m1 work in progress)",
        "licence": "CC-BY-4.0", "licence_url": "https://creativecommons.org/licenses/by/4.0/",
        "author": "project character pipeline",
        "retrieved_or_built": datetime.date.fromtimestamp(os.path.getmtime(glb)).isoformat(),
        "path": a.glb, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
        "inputs": ["makehuman:mpfb2-2.0.18", "makehuman:system-assets-cc0", "makehuman:suits01-cc0"],
        "transformations": transformations(stats),
        "tool": {"blender": stats.get("blender"), "mpfb": "2.0.18",
                 "script": "blender/build_character.py (stages in blender/character/)",
                 "config": stats["config"] | {"assets": "<data roots>"}},
        "status": "accepted",
        "status_reason": "All inputs CC0 (provenance/audit_makehuman.py: 0 flagged). Teeth decimated "
                         "for the NOTES.md §7 budget: every MPFB teeth asset is 7,120 tris.",
    }
    lines = [ln for ln in MANIFEST.read_text().splitlines() if ln.strip()]
    lines = [ln for ln in lines if json.loads(ln).get("id") != RID] + [json.dumps(rec, ensure_ascii=False)]
    MANIFEST.write_text("\n".join(lines) + "\n")
    print(f"{RID}: {len(data)} B sha256 {rec['sha256'][:12]}… -> {MANIFEST.relative_to(REPO)}")


if __name__ == "__main__":
    main()
