"""ITU-R BS.1770-4 / EBU R128 loudness in numpy (48 kHz), cross-checked against ffmpeg ebur128.

Mono files are measured as a single channel (no dual-mono +3 dB), like ffmpeg's default.
"""

from __future__ import annotations

import numpy as np
from scipy import signal

_B1 = [1.53512485958697, -2.69169618940638, 1.19839281085285]
_A1 = [1.0, -1.69065929318241, 0.73248077421585]
_B2 = [1.0, -2.0, 1.0]
_A2 = [1.0, -1.99004745483398, 0.99007225036621]


def _k(x: np.ndarray) -> np.ndarray:
    return signal.lfilter(_B2, _A2, signal.lfilter(_B1, _A1, x, axis=0), axis=0)


def _blocks(x: np.ndarray, sr: int, win: float, hop: float) -> np.ndarray:
    y = _k(x if x.ndim == 2 else x[:, None]) ** 2
    w, h = int(win * sr), int(hop * sr)
    if len(y) < w:
        y = np.pad(y, ((0, w - len(y)), (0, 0)))
    n = 1 + (len(y) - w) // h
    cs = np.concatenate([np.zeros((1, y.shape[1])), np.cumsum(y, axis=0)])
    idx = np.arange(n) * h
    ms = (cs[idx + w] - cs[idx]) / w
    return ms.sum(axis=1)  # all channel weights 1.0 (no surround channels here)


def lufs(z: np.ndarray) -> np.ndarray:
    return -0.691 + 10 * np.log10(np.maximum(z, 1e-20))


def integrated(x: np.ndarray, sr: int = 48000) -> float:
    z = _blocks(x, sr, 0.4, 0.1)
    l = lufs(z)
    z = z[l > -70]
    if not len(z):
        return float("-inf")
    rel = lufs(np.array([z.mean()]))[0] - 10
    z = z[lufs(z) > rel]
    return float(lufs(np.array([z.mean()]))[0])


def momentary_max(x: np.ndarray, sr: int = 48000) -> float:
    return float(lufs(_blocks(x, sr, 0.4, 0.01)).max())


def short_term(x: np.ndarray, sr: int = 48000, hop: float = 0.1) -> np.ndarray:
    return lufs(_blocks(x, sr, 3.0, hop))


def lra(x: np.ndarray, sr: int = 48000) -> float:
    st = _blocks(x, sr, 3.0, 0.1)
    l = lufs(st)
    st = st[l > -70]
    if not len(st):
        return 0.0
    rel = lufs(np.array([st.mean()]))[0] - 20
    l = lufs(st)
    l = l[l > rel]
    return float(np.percentile(l, 95) - np.percentile(l, 10))


def true_peak_db(x: np.ndarray) -> float:
    y = signal.resample_poly(x, 4, 1, axis=0)
    return float(20 * np.log10(np.abs(y).max() + 1e-12))


def sample_peak_db(x: np.ndarray) -> float:
    return float(20 * np.log10(np.abs(x).max() + 1e-12))


def summary(x: np.ndarray, sr: int = 48000) -> dict:
    return {
        "lufs_i": round(integrated(x, sr), 2),
        "lufs_m_max": round(momentary_max(x, sr), 2),
        "lra_lu": round(lra(x, sr), 2),
        "true_peak_dbtp": round(true_peak_db(x), 2),
        "sample_peak_dbfs": round(sample_peak_db(x), 2),
        "duration_s": round(len(x) / sr, 3),
    }
