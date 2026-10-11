"""Footstep segmentation and take scoring (used by audiopipe.footsteps).

    uv run python -I -m audiopipe.steps            # survey: per-source step statistics
"""

from __future__ import annotations

import numpy as np
import soundfile as sf
from scipy import ndimage, signal

from .common import BUILD

CLEAN = BUILD / "clean"
SR = 48000


def envelope(mono: np.ndarray, sr: int = SR) -> np.ndarray:
    """Peak-hold envelope (2 ms max filter, 5 ms smoothing), in dBFS."""
    a = np.abs(mono)
    a = ndimage.maximum_filter1d(a, int(0.002 * sr))
    a = ndimage.uniform_filter1d(a, int(0.005 * sr))
    return 20 * np.log10(a + 1e-9)


def detect(x: np.ndarray, sr: int = SR, min_gap: float = 0.28, rise_db: float = 18.0, max_len: float = 0.6) -> list[dict]:
    """Find step events: envelope rises >= rise_db above the local floor, >= min_gap apart."""
    mono = x.mean(axis=1) if x.ndim == 2 else x
    env = envelope(mono, sr)
    floor = ndimage.percentile_filter(env[:: sr // 100], 10, size=300)  # 3 s running 10th pct (100 Hz grid)
    floor = np.repeat(floor, sr // 100)[: len(env)]
    floor = np.pad(floor, (0, len(env) - len(floor)), mode="edge")
    floor = np.maximum(floor, -100.0)  # gated/denoised gaps are digital silence
    over = env > floor + rise_db
    d = np.diff(over.astype(np.int8), prepend=0)
    starts = np.where(d == 1)[0]
    events = []
    last = -10 * sr
    for s in starts:
        if s - last < min_gap * sr:
            continue
        last = s
        events.append(int(s))
    out = []
    for i, s in enumerate(events):
        nxt = events[i + 1] if i + 1 < len(events) else len(mono)
        # refine onset: walk back to where the envelope was within 3 dB of the floor
        j = s
        while j > max(0, s - int(0.03 * sr)) and env[j] > floor[s] + 3:
            j -= 1
        onset = j
        seg_end = min(nxt - int(0.01 * sr), onset + int(max_len * sr))
        seg = env[onset:seg_end]
        pk = int(np.argmax(seg)) + onset
        # end: first point after the peak where the envelope stays below max(floor + 6, peak - 50)
        # for 30 ms (the peak-relative bound handles gated/denoised sources with a -inf floor)
        thr = max(floor[pk] + 6, env[pk] - 50)
        tail = env[pk:seg_end] < thr
        run = ndimage.uniform_filter1d(tail.astype(float), int(0.03 * sr)) > 0.99
        end = pk + int(np.argmax(run)) + int(0.03 * sr) if run.any() else seg_end
        end = min(end, seg_end)
        pre = mono[max(0, onset - int(0.05 * sr)):onset]
        pre_db = 20 * np.log10(np.sqrt(np.mean(pre ** 2)) + 1e-9) if len(pre) else -120
        clip = mono[onset:end]
        f, p = signal.welch(clip, sr, nperseg=min(1024, len(clip)))
        centroid = float((f * p).sum() / (p.sum() + 1e-20))
        out.append({
            "onset": onset, "end": int(end), "dur_ms": round((end - onset) / sr * 1000),
            "peak_db": round(float(env[pk]), 1), "floor_db": round(float(floor[pk]), 1),
            "snr_db": round(float(env[pk] - floor[pk]), 1), "pre_db": round(float(pre_db), 1),
            "gap_next_ms": round((nxt - onset) / sr * 1000), "centroid_hz": round(centroid),
            "truncated": bool(end >= seg_end - 1),
        })
    return out


def load(slug: str) -> np.ndarray:
    x, sr = sf.read(CLEAN / f"{slug}.flac", dtype="float32", always_2d=True)
    assert sr == SR
    return x


def survey() -> None:
    for slug in ["freesound-205748", "freesound-560478", "freesound-742969"]:
        x = load(slug)
        ev = detect(x)
        pk = np.array([e["peak_db"] for e in ev])
        snr = np.array([e["snr_db"] for e in ev])
        dur = np.array([e["dur_ms"] for e in ev])
        cen = np.array([e["centroid_hz"] for e in ev])
        gap = np.array([e["gap_next_ms"] for e in ev])
        print(f"{slug}: {len(ev)} steps | peak med {np.median(pk):.1f} dB (IQR {np.percentile(pk,25):.1f}..{np.percentile(pk,75):.1f}) "
              f"| SNR med {np.median(snr):.1f} | dur med {np.median(dur):.0f} ms | centroid med {np.median(cen):.0f} Hz "
              f"| gap med {np.median(gap):.0f} ms | truncated {sum(e['truncated'] for e in ev)}")


if __name__ == "__main__":
    survey()
