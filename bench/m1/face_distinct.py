"""Face-variant distinctness check and stacked face strip (stdlib + numpy + ffmpeg).

    python3 -I bench/m1/face_distinct.py --stock RUN --variant a=RUN --variant b=RUN ... \
        --out DIR [--max-vs-stock 0.95] [--max-between 0.97]

Scores the hair-hidden face silhouettes (face_front_mask.png, face_profile_mask.png:
body + eyes only, orthographic, fixed metric scale) of each variant against
the stock head and against each other. A variant is distinct when every view
IoU vs stock is <= --max-vs-stock and every view IoU vs every other variant
is <= --max-between (bench/m1/head.md, "Bolder pass"). Writes DIR/distinct.json
and DIR/faces.png: the runs' face_strip.png rows stacked with labels.
Exit status 1 if any guard fails.
"""

import argparse
import itertools
import json
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lookdev_report import drawtext, ffmpeg  # noqa: E402

FACE_VIEWS = ("face_front", "face_profile")


def mask(run, view):
    path = os.path.join(run, f"{view}_mask.png")
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", path, "-f", "rawvideo",
                          "-pix_fmt", "gray", "-"], check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.uint8) > 127


def iou(a, b):
    u = np.logical_or(a, b).sum()
    return float(np.logical_and(a, b).sum() / u) if u else 1.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stock", required=True)
    ap.add_argument("--variant", action="append", required=True, help="name=RUN")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-vs-stock", type=float, default=0.95)
    ap.add_argument("--max-between", type=float, default=0.97)
    a = ap.parse_args()
    runs = {"stock": os.path.abspath(a.stock)}
    for v in a.variant:
        name, run = v.split("=", 1)
        runs[name] = os.path.abspath(run)
    masks = {n: {v: mask(r, v) for v in FACE_VIEWS} for n, r in runs.items()}
    names = [n for n in runs if n != "stock"]
    res = {"thresholds": {"max_vs_stock": a.max_vs_stock, "max_between": a.max_between},
           "runs": runs, "vs_stock": {}, "between": {}, "fails": []}
    for n in names:
        res["vs_stock"][n] = {v: round(iou(masks[n][v], masks["stock"][v]), 4) for v in FACE_VIEWS}
        for v, x in res["vs_stock"][n].items():
            if x > a.max_vs_stock:
                res["fails"].append(f"{n} vs stock {v} {x:.3f} > {a.max_vs_stock}")
    for p, q in itertools.combinations(names, 2):
        res["between"][f"{p}-{q}"] = {v: round(iou(masks[p][v], masks[q][v]), 4) for v in FACE_VIEWS}
        for v, x in res["between"][f"{p}-{q}"].items():
            if x > a.max_between:
                res["fails"].append(f"{p} vs {q} {v} {x:.3f} > {a.max_between}")
    res["ok"] = not res["fails"]

    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "distinct.json"), "w") as f:
        json.dump(res, f, indent=2)
    inputs, chains = [], []
    for i, n in enumerate(runs):
        lab = os.path.join(a.out, f"label_{n}.txt")
        with open(lab, "w") as f:
            f.write(n if n == "stock" else
                    f"{n}  vs stock " + " ".join(f"{x:.3f}" for x in res["vs_stock"][n].values()))
        inputs += ["-i", os.path.join(runs[n], "face_strip.png")]
        chains.append(f"[{i}]{drawtext(lab, 18)}[t{i}]")
    fc = ";".join(chains) + ";" + "".join(f"[t{i}]" for i in range(len(runs))) + f"vstack={len(runs)}"
    ffmpeg([*inputs, "-filter_complex", fc, os.path.join(a.out, "faces.png")])
    for n in runs:
        os.remove(os.path.join(a.out, f"label_{n}.txt"))
    print(json.dumps({k: res[k] for k in ("vs_stock", "between", "fails", "ok")}, indent=2))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
