"""Likeness review board: rows of reference | render | second render | 50 % overlay, each image
aligned by a similarity transform on the iris centres to the same crop and pixel IPD; plus a
blink sheet (shuffled thumbnails at fixed sizes) and a mirrored copy for the flip test.

Rows come from a JSON spec; every image needs MediaPipe landmarks (refboard.py writes them for
references; refboard.py measure --out-dir for renders):

    {"rows": [{"label": "front",
               "cells": [{"img": "ref/crops/015.jpg", "lm": "ref/crops/015_lm.npy", "title": "ref"},
                         {"img": "clay/front.png", "lm": "clay/lm/front_lm.npy", "title": "clay"}],
               "overlay": [0, 1]}]}

    python -I review_board.py board --spec rows.json --out board.jpg [--cell 384 --ipd-frac 0.30] [--flip]
    python -I review_board.py blink --spec rows.json --out blink.jpg [--sizes 96,192] [--seed 1]
"""

import argparse
import json
import random
from pathlib import Path

import cv2
import numpy as np

IRIS_R, IRIS_L = 468, 473


def aligned(img_path, lm_path, cell, ipd_frac, eye_y=0.42, flip=False):
    img = cv2.imread(str(img_path))
    lm = np.load(lm_path)
    a, b = lm[IRIS_R, :2].astype(np.float64), lm[IRIS_L, :2].astype(np.float64)
    if a[0] > b[0]:
        a, b = b, a
    src = np.float64([a, b])
    half = ipd_frac * cell / 2
    dst = np.float64([[cell / 2 - half, eye_y * cell], [cell / 2 + half, eye_y * cell]])
    M, _ = cv2.estimateAffinePartial2D(src, dst)
    out = cv2.warpAffine(img, M, (cell, cell), flags=cv2.INTER_AREA, borderValue=(24, 24, 24))
    return out[:, ::-1].copy() if flip else out


def label(im, text):
    cv2.putText(im, text, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 3)
    cv2.putText(im, text, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (235, 235, 235), 1)
    return im


def cmd_board(a):
    spec = json.load(open(a.spec))
    root = Path(a.spec).parent
    rows = []
    for row in spec["rows"]:
        ims = [aligned(root / c["img"], root / c["lm"], a.cell, a.ipd_frac, flip=a.flip) for c in row["cells"]]
        titles = [c.get("title", "") for c in row["cells"]]
        if row.get("overlay"):  # blend the unlabelled cells, then label everything
            i, j = row["overlay"]
            ims.append(cv2.addWeighted(ims[i], 0.5, ims[j], 0.5, 0))
            titles.append(f"50 % {titles[i]} / {titles[j]}")
        ims = [label(im, t) for im, t in zip(ims, titles)]
        strip = np.hstack(ims)
        cv2.putText(strip, row.get("label", ""), (6, a.cell - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (80, 220, 255), 2)
        rows.append(strip)
    w = max(r.shape[1] for r in rows)
    rows = [np.pad(r, ((0, 0), (0, w - r.shape[1]), (0, 0)), constant_values=24) for r in rows]
    cv2.imwrite(a.out, np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 92])
    print(f"[board] {len(rows)} rows -> {a.out}")


def cmd_blink(a):
    """Every cell of the spec as a thumbnail, shuffled, at each size; the key is written beside."""
    spec = json.load(open(a.spec))
    root = Path(a.spec).parent
    cells = [c for row in spec["rows"] for c in row["cells"]]
    rnd = random.Random(a.seed)
    order = list(range(len(cells)))
    rnd.shuffle(order)
    sheets = []
    for size in (int(s) for s in a.sizes.split(",")):
        ims = [aligned(root / cells[k]["img"], root / cells[k]["lm"], size, a.ipd_frac) for k in order]
        cols = max(1, min(len(ims), 1600 // size))
        rows = [np.hstack(ims[i:i + cols] + [np.full_like(ims[0], 24)] * (cols - len(ims[i:i + cols])))
                for i in range(0, len(ims), cols)]
        sheets.append(np.vstack(rows))
    w = max(s.shape[1] for s in sheets)
    sheets = [np.pad(s, ((0, 8), (0, w - s.shape[1]), (0, 0)), constant_values=24) for s in sheets]
    cv2.imwrite(a.out, np.vstack(sheets), [cv2.IMWRITE_JPEG_QUALITY, 92])
    key = Path(a.out).with_suffix(".key.json")
    json.dump([{"pos": p, "title": cells[k].get("title", ""), "img": cells[k]["img"]} for p, k in enumerate(order)],
              open(key, "w"), indent=1)
    print(f"[blink] {len(cells)} cells x {a.sizes} px -> {a.out} (key {key})")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("board")
    b.add_argument("--spec", required=True)
    b.add_argument("--out", required=True)
    b.add_argument("--cell", type=int, default=384)
    b.add_argument("--ipd-frac", type=float, default=0.30)
    b.add_argument("--flip", action="store_true", help="mirror every cell (flip test)")
    k = sub.add_parser("blink")
    k.add_argument("--spec", required=True)
    k.add_argument("--out", required=True)
    k.add_argument("--sizes", default="96,192")
    k.add_argument("--ipd-frac", type=float, default=0.30)
    k.add_argument("--seed", type=int, default=1)
    a = ap.parse_args(argv)
    {"board": cmd_board, "blink": cmd_blink}[a.cmd](a)


if __name__ == "__main__":
    main()
