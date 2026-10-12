#!/usr/bin/env python3
"""Fetch the CC0 Poly Haven textures the hero stage uses (render-only; they
never ship in the GLB) and print one provenance record per texture set.

    python3 -I blender/hero/fetch_textures.py --vendor /home/akram/code/or3/data/vendor [--records]

Each set lands in its own new directory, <vendor>/polyhaven/<asset>/, with the
2k JPG maps (diffuse, OpenGL normal, roughness, displacement) and a
manifest.json (urls, md5 from the API, sha256 of what was written). Already
present files with the right md5 are kept. --records prints the
provenance/mesh.jsonl lines (domain "texture", kind "source").
"""

import argparse
import datetime
import hashlib
import json
import os
import urllib.request

# asset: what it is used for in the stage
ASSETS = {
    "road_damaged": "wet street ground (its height map drives the puddles)",
    "red_brick_03": "alley wall",
    "concrete_wall_008": "side wall / signage back plate",
}
MAPS = {"Diffuse": "diff", "nor_gl": "nor_gl", "Rough": "rough", "Displacement": "disp"}
RES = "2k"
API = "https://api.polyhaven.com"
UA = {"User-Agent": "hero-stage-fetch/1.0"}


def get_json(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return json.load(r)


def md5_of(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(vendor, asset):
    d = os.path.join(vendor, "polyhaven", asset)
    os.makedirs(d, exist_ok=True)
    files = get_json(f"{API}/files/{asset}")
    info = get_json(f"{API}/info/{asset}")
    man = {"asset": asset, "name": info.get("name"), "authors": sorted(info.get("authors", {})),
           "licence": "CC0-1.0", "source_url": f"https://polyhaven.com/a/{asset}",
           "retrieved": datetime.date.today().isoformat(), "files": {}}
    for key, short in MAPS.items():
        ent = files[key][RES]["jpg"]
        out = os.path.join(d, f"{asset}_{short}_{RES}.jpg")
        if not (os.path.exists(out) and md5_of(out) == ent["md5"]):
            req = urllib.request.Request(ent["url"], headers=UA)
            with urllib.request.urlopen(req, timeout=120) as r, open(out, "wb") as f:
                f.write(r.read())
            if md5_of(out) != ent["md5"]:
                raise SystemExit(f"md5 mismatch for {out}")
        man["files"][short] = {"path": os.path.basename(out), "url": ent["url"],
                               "md5": ent["md5"], "bytes": os.path.getsize(out),
                               "sha256": sha256_of(out)}
    old = os.path.join(d, "manifest.json")
    if os.path.exists(old):
        with open(old) as f:
            man["retrieved"] = json.load(f).get("retrieved", man["retrieved"])
    with open(old, "w") as f:
        json.dump(man, f, indent=1)
    return man


def record(man):
    diff = man["files"]["diff"]
    return {
        "id": f"polyhaven:{man['asset']}",
        "kind": "source", "domain": "texture",
        "title": f"Poly Haven '{man['name']}' {RES} texture set (diffuse, normal GL, rough, disp; JPG)",
        "licence": "CC0-1.0",
        "licence_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "author": ", ".join(man["authors"]),
        "source_url": man["source_url"],
        "download_url": diff["url"],
        "retrieved_or_built": man["retrieved"],
        "path": f"vendor/polyhaven/{man['asset']}/{diff['path']}",
        "bytes": diff["bytes"], "sha256": diff["sha256"],
        "status": "accepted",
        "status_reason": ("Hero stage set dressing only (blender/hero, render-only, never in the GLB): "
                          + ASSETS[man["asset"]] + ". Poly Haven assets are CC0. Sibling maps in the "
                          "same directory; their sha256 are in manifest.json."),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vendor", required=True)
    ap.add_argument("--records", action="store_true")
    a = ap.parse_args()
    for asset in ASSETS:
        man = fetch(os.path.abspath(a.vendor), asset)
        if a.records:
            print(json.dumps(record(man)))
        else:
            print(asset, "ok", ", ".join(man["files"]))


if __name__ == "__main__":
    main()
