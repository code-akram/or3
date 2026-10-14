"""Union shot split + the cheap NOTES.md §8 shot filters, and a contact sheet per clip for review.

Reads ``<shots_dir>/shots.json`` (written by shots.py). The cut list is the **union** of TransNetV2 and
PySceneDetect cuts (cuts within ``--merge`` frames of each other count once; TransNetV2 alone missed a
hard cut in spike 3). Frames TransNetV2 leaves out of every scene (dissolves, fades) are trimmed off the
shot they fall in. Then, per shot: duration, median luma, median Laplacian variance (blur), and the
stage-1 verdict (``dur``, ``luma``, ``blur``). The expensive filters (subject size, protagonist coverage,
ViTPose confidence) need YOLO / ViTPose and are applied by footage_run.py.

Writes ``<shots_dir>/union.json`` and ``<shots_dir>/sheet-NN.jpg`` (4 frames per shot, one row per shot,
stage-1 survivors only). Both derive from film frames, so ``shots_dir`` must be under private/.

    python -I shot_filter.py VIDEO SHOTS_DIR [--min-dur 1.0] [--min-luma 15] [--min-lapvar 15]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.append(str(Path(__file__).resolve().parent.parent / "likeness"))
import containment  # noqa: E402


def union_cuts(tn: list[list[int]], sd: list[list[int]], n: int, merge: int) -> list[int]:
    cuts = sorted({s for s, _ in tn if s > 0})
    for s, _ in sd:
        if s > 0 and all(abs(s - c) > merge for c in cuts):
            cuts.append(s)
    return sorted(cuts)


def per_frame(video: str) -> tuple[np.ndarray, np.ndarray, float, int, int]:
    cap = cv2.VideoCapture(video)
    fps = cap.get(cv2.CAP_PROP_FPS)
    W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    luma, sharp = [], []
    while True:
        ok, img = cap.read()
        if not ok:
            break
        # blur on a 960-px-wide copy so the threshold does not depend on the source resolution
        g = cv2.cvtColor(cv2.resize(img, (960, round(960 * H / W)), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
        luma.append(float(np.median(g)))
        sharp.append(float(cv2.Laplacian(g, cv2.CV_64F).var()))
    cap.release()
    return np.array(luma), np.array(sharp), fps, W, H


def sheet(video: str, shots: list[dict], out_dir: Path, per_sheet: int = 12, w: int = 320) -> list[str]:
    cap = cv2.VideoCapture(video)
    paths = []
    for k in range(0, len(shots), per_sheet):
        rows = []
        for s in shots[k : k + per_sheet]:
            tiles = []
            for f in np.linspace(s["start"], s["end"], 4).round().astype(int):
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(f))
                ok, img = cap.read()
                img = cv2.resize(img, (w, round(w * img.shape[0] / img.shape[1]))) if ok else np.zeros((180, w, 3), np.uint8)
                tiles.append(img)
            row = np.hstack(tiles)
            label = f"#{s['idx']} f{s['start']}-{s['end']} {s['dur_s']}s"
            cv2.rectangle(row, (0, 0), (8 + 11 * len(label), 26), (0, 0, 0), -1)
            cv2.putText(row, label, (4, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 1, cv2.LINE_AA)
            rows.append(row)
        p = out_dir / f"sheet-{k // per_sheet:02d}.jpg"
        cv2.imwrite(str(p), np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 80])
        paths.append(str(p))
    cap.release()
    return paths


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("shots_dir")
    ap.add_argument("--merge", type=int, default=3, help="cuts closer than this (frames) are the same cut")
    ap.add_argument("--min-dur", type=float, default=1.0)
    ap.add_argument("--min-luma", type=float, default=15.0)
    ap.add_argument("--min-lapvar", type=float, default=15.0, help="median Laplacian variance at 960 px width")
    a = ap.parse_args()
    d = containment.assert_private(a.shots_dir, "shots_dir")
    js = json.loads((d / "shots.json").read_text())
    tn = [[s["start"], s["end"]] for s in js["transnetv2"]["shots"]]
    sd = js["pyscenedetect"]["shots"]
    luma, sharp, fps, W, H = per_frame(a.video)
    n = len(luma)
    covered = np.zeros(n, bool)
    for s, e in tn:
        covered[s : min(e, n - 1) + 1] = True
    cuts = union_cuts(tn, sd, n, a.merge)
    bounds = [0, *cuts, n]
    shots = []
    for i, (s, e) in enumerate(zip(bounds[:-1], bounds[1:])):
        idx = np.flatnonzero(covered[s:e]) + s  # drop transition frames TransNetV2 left out
        if len(idx) == 0:
            continue
        s2, e2 = int(idx[0]), int(idx[-1])
        dur = (e2 - s2 + 1) / fps
        rec = {
            "idx": len(shots), "start": s2, "end": e2, "t_start": round(s2 / fps, 3), "dur_s": round(dur, 3),
            "median_luma": round(float(np.median(luma[s2 : e2 + 1])), 1),
            "median_lapvar": round(float(np.median(sharp[s2 : e2 + 1])), 1),
            "only_in": "transnetv2" if s in {c for c, _ in tn} and all(abs(s - c) > a.merge for c, _ in sd) else
                       "pyscenedetect" if s > 0 and s not in {c for c, _ in tn} else None,
        }
        fails = []
        if dur < a.min_dur:
            fails.append("dur")
        if rec["median_luma"] < a.min_luma:
            fails.append("luma")
        if rec["median_lapvar"] < a.min_lapvar:
            fails.append("blur")
        rec["stage1_fail"] = fails
        shots.append(rec)
    keep = [s for s in shots if not s["stage1_fail"]]
    res = {
        "video": a.video, "fps": fps, "frames": n, "size": [W, H],
        "params": {"merge": a.merge, "min_dur": a.min_dur, "min_luma": a.min_luma, "min_lapvar": a.min_lapvar},
        "n_cuts": {"transnetv2": len(tn) - 1, "pyscenedetect": max(len(sd) - 1, 0), "union": len(cuts)},
        "shots": shots,
        "stage1_pass": [s["idx"] for s in keep],
        "sheets": sheet(a.video, keep, d),
    }
    (d / "union.json").write_text(json.dumps(res, indent=1))
    fail = {k: sum(k in s["stage1_fail"] for s in shots) for k in ("dur", "luma", "blur")}
    print(f"{Path(a.video).parent.name}: {len(shots)} shots (cuts tn {res['n_cuts']['transnetv2']} / sd "
          f"{res['n_cuts']['pyscenedetect']} / union {len(cuts)}), fail {fail}, stage-1 pass {len(keep)} "
          f"({sum(s['dur_s'] for s in keep):.1f} s)")


if __name__ == "__main__":
    main()
