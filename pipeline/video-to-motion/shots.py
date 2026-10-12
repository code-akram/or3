"""Shot split (TransNetV2, PySceneDetect as cross-check) + the NOTES.md §8 shot filter stats.

Writes ``<out>/shots.json``: per shot the frame range, duration, median luma and a Laplacian-variance
blur score, plus timings for both detectors. Run inside the GVHMR venv:

    OMP_NUM_THREADS=4 python -I pipeline/video-to-motion/shots.py VIDEO OUT_DIR [--threads 4]
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np
import torch


def transnet_shots(video: str, threshold: float = 0.5) -> tuple[list[list[int]], float, int]:
    from transnetv2_pytorch import TransNetV2

    t0 = time.perf_counter()
    model = TransNetV2(device="cpu")
    model.eval()
    with torch.no_grad():
        frames, single, _ = model.predict_video(video, quiet=True)
    scenes = TransNetV2.predictions_to_scenes(single.cpu().numpy().reshape(-1), threshold=threshold)
    return scenes.tolist(), time.perf_counter() - t0, int(frames.shape[0])


def pyscenedetect_shots(video: str) -> tuple[list[list[int]], float]:
    from scenedetect import AdaptiveDetector, detect

    t0 = time.perf_counter()
    scenes = detect(video, AdaptiveDetector())
    out = [[s.get_frames(), e.get_frames() - 1] for s, e in scenes]
    return out, time.perf_counter() - t0


def frame_stats(video: str, shots: list[list[int]]) -> list[dict]:
    """Median luma (0-255) and median Laplacian variance (blur; low = blurry) per shot."""
    cap = cv2.VideoCapture(video)
    luma, sharp = [], []
    while True:
        ok, img = cap.read()
        if not ok:
            break
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        luma.append(float(np.median(g)))
        sharp.append(float(cv2.Laplacian(g, cv2.CV_64F).var()))
    fps = cap.get(cv2.CAP_PROP_FPS)
    cap.release()
    out = []
    for s, e in shots:
        e = min(e, len(luma) - 1)
        out.append(
            {
                "start": s,
                "end": e,
                "t_start": round(s / fps, 3),
                "t_end": round((e + 1) / fps, 3),
                "dur_s": round((e - s + 1) / fps, 3),
                "median_luma": round(float(np.median(luma[s : e + 1])), 1),
                "median_lapvar": round(float(np.median(sharp[s : e + 1])), 1),
            }
        )
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("out_dir")
    ap.add_argument("--threads", type=int, default=4)
    a = ap.parse_args()
    torch.set_num_threads(a.threads)
    cv2.setNumThreads(a.threads)
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    tn, tn_s, n = transnet_shots(a.video)
    sd, sd_s = pyscenedetect_shots(a.video)
    res = {
        "video": a.video,
        "frames": n,
        "threads": a.threads,
        "loadavg": Path("/proc/loadavg").read_text().split()[:3],
        "transnetv2": {"seconds": round(tn_s, 2), "s_per_frame": round(tn_s / n, 5), "shots": frame_stats(a.video, tn)},
        "pyscenedetect": {"seconds": round(sd_s, 2), "s_per_frame": round(sd_s / n, 5), "shots": sd},
    }
    (out / "shots.json").write_text(json.dumps(res, indent=1))
    print(f"frames={n} transnet={tn_s:.2f}s ({len(tn)} shots) pyscenedetect={sd_s:.2f}s ({len(sd)} shots)")
    for s in res["transnetv2"]["shots"]:
        print(s)
    print("pyscenedetect:", sd)


if __name__ == "__main__":
    main()
