"""Posed gate sheets from a suit_spike --posed run: one row per pose, columns tag x view.

    python3 -I bench/m1/v4/suit_sheet.py RUN OUT_DIR [--tags sim,rt] [--views front,three_quarter]
                                         [--per 6] [--poses a,b,c] [--name posed_sheet]

Frames are the run's <pose>_<tag>_<view>.png (render_views); a missing frame is left grey. Rows are
in the run's pose order (spike_stats.json "poses"); sheets of --per rows are written as
<name>_<i>.png, with <name>.txt listing each sheet's rows.
"""

import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "bench", "m1"))
sys.path.insert(0, os.path.join(REPO, "blender"))
import lookdev_report as lr  # noqa: E402
from character.suit_wrinkle import write_png  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("out")
    ap.add_argument("--tags", default="sim,rt")
    ap.add_argument("--views", default="front,three_quarter")
    ap.add_argument("--per", type=int, default=6)
    ap.add_argument("--poses")
    ap.add_argument("--name", default="posed_sheet")
    a = ap.parse_args()
    st = json.load(open(os.path.join(a.run, "spike_stats.json")))
    poses = a.poses.split(",") if a.poses else list(st.get("poses", {}))
    tags, views = a.tags.split(","), a.views.split(",")
    tile = None
    for p in poses:
        for t in tags:
            f = os.path.join(a.run, f"{p}_{t}_{views[0]}.png")
            if os.path.exists(f):
                tile = lr._png_rgb(f).shape[:2]
                break
        if tile:
            break
    if tile is None:
        raise SystemExit("no frames")
    os.makedirs(a.out, exist_ok=True)
    gap = 4
    listing = []
    for si in range(0, len(poses), a.per):
        rows = poses[si:si + a.per]
        H = len(rows) * (tile[0] + gap) - gap
        W = len(tags) * len(views) * (tile[1] + gap) - gap
        img = np.full((H, W, 3), 255, np.uint8)
        for r, p in enumerate(rows):
            c = 0
            for t in tags:
                for v in views:
                    f = os.path.join(a.run, f"{p}_{t}_{v}.png")
                    y, x = r * (tile[0] + gap), c * (tile[1] + gap)
                    if os.path.exists(f):
                        img[y:y + tile[0], x:x + tile[1]] = lr._png_rgb(f)[:tile[0], :tile[1], :3]
                    else:
                        img[y:y + tile[0], x:x + tile[1]] = 128
                    c += 1
        fn = os.path.join(a.out, f"{a.name}_{si // a.per}.png")
        write_png(fn, img)
        listing.append(f"{os.path.basename(fn)}: rows {', '.join(rows)}; columns "
                       + ", ".join(f"{t} {v}" for t in tags for v in views))
    with open(os.path.join(a.out, f"{a.name}.txt"), "w") as f:
        f.write("\n".join(listing) + "\n")
    print("\n".join(listing))


if __name__ == "__main__":
    main()
