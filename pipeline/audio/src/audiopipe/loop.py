"""Seamless-loop construction (library; used by audiopipe.bed for the round-2 ambience layers).

Loop construction (ffmpeg `acrossfade`): with signal s and crossfade length X,
    loop = acrossfade(P = s[X : L+X], Q = s[0 : X], d = X, equal-power curves)
The output ends on s[X-1] and starts on s[X], so the wrap is the recording's own continuity;
the blend s[L..L+X] -> s[0..X] sits inside the file. L is chosen by spectral match (1/3-octave
band levels of the two crossfade regions), loudness match and absence of transients, and all
cut points are snapped to rising zero crossings of the mid signal with a quiet side channel.
Verification: wrap discontinuity vs the file's own sample-to-sample statistics, spectral flux at
the wrap vs its distribution, short-term loudness either side of the wrap and through the fade.

Round 1's single layered street loop (spike 7) was rejected at the 2026-10-12 listening gate
for containing people (NOTES §12 human-free rule); its builder is gone, the construction stays.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal

from . import loudness as Lz
from .common import BUILD, ffmpeg

SR = 48000
CLEAN = BUILD / "clean"
X_S = 6.0                  # default crossfade length
L_RANGE_S = (80.0, 115.0)  # default candidate loop lengths
OPUS_FRAME = 960           # 20 ms at 48 kHz


def read(path: Path) -> np.ndarray:
    x, sr = sf.read(path, dtype="float64", always_2d=True)
    assert sr == SR
    return x


def stationary_window(x: np.ndarray, n: int) -> tuple[int, dict]:
    """Start index of the length-n window with the most even short-term loudness."""
    st = Lz.short_term(x, SR, hop=0.5)            # one value per 0.5 s
    w = int(round(n / SR / 0.5))
    best, best_i, info = 1e9, 0, {}
    for i in range(0, max(1, len(st) - w)):
        seg = st[i:i + w]
        med = np.median(seg)
        spread = np.percentile(seg, 95) - np.percentile(seg, 10)
        events = (seg > med + 6).sum()
        score = spread + 3 * events
        if score < best:
            best, best_i, info = score, i, {"spread_lu": round(float(spread), 2), "events_over_6lu": int(events)}
    return int(best_i * 0.5 * SR), info


def third_octave_levels(x: np.ndarray) -> np.ndarray:
    m = x.mean(axis=1)
    f, p = signal.welch(m, SR, nperseg=4096)
    centres = 1000 * 2 ** (np.arange(-17, 14) / 3)  # 20 Hz .. 20 kHz
    lv = []
    for c in centres:
        band = (f >= c * 2 ** (-1 / 6)) & (f < c * 2 ** (1 / 6))
        lv.append(10 * np.log10(p[band].sum() + 1e-20))
    return np.array(lv)


def rising_zero_cross(x: np.ndarray, near: int, radius: int) -> int:
    if x.shape[1] == 1:
        mid, side = 2 * x[:, 0], np.ones(len(x))
    else:
        mid = x[:, 0] + x[:, 1]
        side = np.abs(x[:, 0] - x[:, 1])
    a, b = max(1, near - radius), min(len(x) - 1, near + radius)
    zc = np.where((mid[a - 1:b - 1] < 0) & (mid[a:b] >= 0))[0] + a
    if not len(zc):
        return near
    # prefer crossings where the side signal is also small, then closeness
    score = side[zc] / (np.median(side[a:b]) + 1e-12) + np.abs(zc - near) / radius
    return int(zc[np.argmin(score)])


def choose_loop(s: np.ndarray, l_range_s: tuple[float, float] = L_RANGE_S, x_s: float = X_S) -> tuple[int, int, int, dict]:
    """Pick (a, X, L): source offset a, crossfade X, loop length L, on a 0.25 s grid.

    Score = 1/3-octave RMS distance between the two crossfade regions s[a:a+X] and
    s[a+L:a+L+X] + 2 x their loudness difference + 2 x transient excess in either region
    + 1 x how far the fade regions sit from the median short-term loudness (avoids a dip
    or bulge through the fade) + a small preference for longer loops."""
    X = int(x_s * SR)
    g = int(0.25 * SR)
    starts = np.arange(0, len(s) - X, g)
    bands = {int(i): third_octave_levels(s[i:i + X]) for i in starts}
    loud = {int(i): Lz.integrated(s[i:i + X]) for i in starts}
    trans = {}
    for i in starts:
        m = Lz.lufs(Lz._blocks(s[i:i + X], SR, 0.4, 0.1))
        trans[int(i)] = float(max(0.0, m.max() - np.median(m) - 3))
    med = float(np.median(Lz.short_term(s, SR, hop=0.25)))
    cands = []
    for a in starts:
        a = int(a)
        for L in range(int(l_range_s[0] * SR), int(l_range_s[1] * SR) + 1, g):
            b = a + L
            if b + X > len(s) or b not in bands:
                continue
            d_spec = float(np.sqrt(np.mean((bands[b] - bands[a]) ** 2)))
            d_loud = abs(loud[b] - loud[a])
            t = trans[a] + trans[b]
            level = abs((loud[a] + loud[b]) / 2 - med)
            longer = 0.5 * (l_range_s[1] - L / SR) / (l_range_s[1] - l_range_s[0])
            cands.append((d_spec + 2 * d_loud + 2 * t + level + longer, a, L, d_spec, d_loud, t, level))
    cands.sort()
    score, a, L, d_spec, d_loud, t, level = cands[0]
    # snap the crossfade start a, loop start a+X and loop end a+X+L to rising zero crossings (+-5 ms)
    a = rising_zero_cross(s, a, int(0.005 * SR)) if a > 0 else 0
    x0 = rising_zero_cross(s, a + X, int(0.005 * SR)) - a
    end = rising_zero_cross(s, a + x0 + L, int(0.005 * SR)) - a
    return a, x0, end - x0, {"source_offset_s": round(a / SR, 4), "loop_len_s": round((end - x0) / SR, 4),
                             "xfade_s": round(x0 / SR, 4), "score": round(score, 3),
                             "spectral_rms_db": round(d_spec, 2), "loudness_diff_lu": round(d_loud, 2),
                             "transient_lu": round(t, 2), "fade_level_offset_lu": round(level, 2),
                             "candidates": len(cands)}


def verify(y: np.ndarray) -> dict:
    """Measure the seam: wrap-point discontinuity and spectral flux vs the file's own statistics."""
    yy = np.concatenate([y, y])
    n = len(y)
    d = np.abs(np.diff(yy, axis=0)).max(axis=1)
    wrap_jump = float(d[n - 1])
    pct = float((d < wrap_jump).mean() * 100)
    # a click shows up as a linear-prediction error (second difference), not as a plain step:
    # a natural zero crossing has a large first difference but a small second difference
    d2 = np.abs(np.diff(yy, n=2, axis=0)).max(axis=1)
    e_wrap = float(max(d2[n - 2], d2[n - 1]))
    pct2 = float((d2 < e_wrap).mean() * 100)
    # spectral flux (20 ms frames, 10 ms hop) on the doubled signal
    f, t, Z = signal.stft(yy.mean(axis=1), SR, nperseg=960, noverlap=480)
    mag = np.log10(np.abs(Z) + 1e-9)
    flux = np.sqrt((np.diff(mag, axis=1) ** 2).mean(axis=0))
    wrap_frame = int(np.argmin(np.abs(t[1:] - n / SR)))
    fw = float(flux[max(0, wrap_frame - 1):wrap_frame + 2].max())
    flux_pct = float((flux < fw).mean() * 100)
    st = Lz.lufs(Lz._blocks(yy, SR, 0.4, 0.1))
    k = int(n / (0.1 * SR))
    before = float(np.mean(st[max(0, k - 12):k - 4]))   # momentary loudness 0.4-1.2 s before the wrap
    after = float(np.mean(st[k:k + 8]))
    return {
        "wrap_jump": round(wrap_jump, 6), "wrap_jump_dbfs": round(20 * np.log10(wrap_jump + 1e-12), 1),
        "median_sample_step": round(float(np.median(d)), 6),
        "wrap_jump_percentile": round(pct, 2),
        "wrap_second_diff": round(e_wrap, 6), "median_second_diff": round(float(np.median(d2)), 6),
        "wrap_second_diff_percentile": round(pct2, 2),
        "wrap_flux": round(fw, 4), "median_flux": round(float(np.median(flux)), 4),
        "wrap_flux_percentile": round(flux_pct, 2),
        "momentary_before_wrap_lufs": round(before, 2), "momentary_after_wrap_lufs": round(after, 2),
    }


def opus_wrap_fix(dec: np.ndarray, pad: int, L: int, x: int) -> np.ndarray:
    """Decoded wrap-padded loop (pad | loop | pad): replace the loop region's last x samples by a
    linear crossfade into dec[pad-x:pad], the decode of the same audio that runs on into dec[pad],
    so playing [pad, pad+L) in a loop is continuous. The page's JS does exactly this."""
    out = dec.copy()
    w = np.linspace(0, 1, x, endpoint=False)[:, None]
    out[pad + L - x:pad + L] = (1 - w) * dec[pad + L - x:pad + L] + w * dec[pad - x:pad]
    return out


def phase_align(s: np.ndarray, L: int, x0: int, radius: int, quantum: int = 1) -> tuple[int, float]:
    """L' in [L - radius, L + radius], a multiple of quantum, maximising the correlation of
    s[L':L'+x0] with s[0:x0]."""
    m = s.mean(axis=1)
    q = m[:x0]
    lo = max(x0, L - radius)
    seg = m[lo:L + radius + x0]
    num = signal.correlate(seg, q, mode="valid", method="fft")
    e = np.convolve(seg ** 2, np.ones(x0), mode="valid")
    r = num / np.sqrt(e * (q ** 2).sum() + 1e-30)
    r[(lo + np.arange(len(r))) % quantum != 0] = -np.inf
    k = int(np.argmax(r))
    return lo + k, float(r[k])


def make_loop(s: np.ndarray, l_range_s: tuple[float, float] = L_RANGE_S, x_s: float = X_S) -> tuple[np.ndarray, dict]:
    """Seamless loop from s (frames, channels): returns (loop, {"loop": choice, "seam": measurements})."""
    a, x0, L, choice = choose_loop(s, l_range_s, x_s)
    s = s[a:]
    # Tonal material (hum, buzz) is correlated across the fade: an equal-power fade of two
    # regions at correlation rho changes the power by (1 + rho) at its midpoint (-4.5 dB for
    # rho = -0.65). Slide L by up to one 40 Hz period to bring the regions into phase, and use
    # an equal-gain (linear) fade when they end up strongly correlated.
    # L is also kept a multiple of one Opus frame (20 ms = 960 samples): with the wrap-padded
    # encode in audiopipe.master, the frames at both ends of the loop region then see the same
    # input, so the decoded loop stays continuous at the wrap. 20 ms is one 50 Hz period, so the
    # constraint costs the (retuned, 50 Hz family) hum layers no phase.
    # (the far end of the fade is inside the blend, so it needs no zero-crossing snap)
    L, rho = phase_align(s, L, x0, int(0.025 * SR), OPUS_FRAME)
    curve = "tri" if rho > 0.5 else "qsin"
    choice |= {"loop_len_s": round(L / SR, 4), "xfade_correlation": round(rho, 3), "xfade_curve": curve}
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        pth, qth, raw = tdp / "p.wav", tdp / "q.wav", tdp / "loop.wav"
        sf.write(pth, s[x0:L + x0], SR, subtype="FLOAT")
        sf.write(qth, s[:x0], SR, subtype="FLOAT")
        ffmpeg("-i", str(pth), "-i", str(qth), "-filter_complex",
               f"acrossfade=ns={x0}:c1={curve}:c2={curve}:o=1", "-c:a", "pcm_f32le", str(raw))
        y = read(raw)
    assert len(y) == L, (len(y), L)
    seam = verify(y)
    # by construction the wrap must be the source's own sample pair s[x0-1] -> s[x0]
    seam["wrap_vs_source_max_err"] = float(max(np.abs(y[-1] - s[x0 - 1]).max(), np.abs(y[0] - s[x0]).max()))
    seam["source_step_at_cut"] = round(float(np.abs(s[x0] - s[x0 - 1]).max()), 6)
    seam["xfade_region_correlation"] = round(float(np.corrcoef(s[L:L + x0].mean(1), s[:x0].mean(1))[0, 1]), 3)
    # loudness through the fade (the last x0 samples of y) vs the loop's median, 1 s windows
    mo = Lz.lufs(Lz._blocks(y, SR, 1.0, 0.1))
    k0 = int((L - x0) / (0.1 * SR))
    fade = mo[k0:] - np.median(mo)
    seam["fade_level_lu"] = [round(float(fade.min()), 2), round(float(fade.max()), 2)]
    return y, {"loop": choice, "seam": seam}

