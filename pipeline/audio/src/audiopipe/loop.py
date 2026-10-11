"""Step 4a: one seamless Shinjuku night-street ambience loop (60-120 s), layered.

    uv run python -I -m audiopipe.loop

Layers (all CC0 / CC-BY, cleaned at 48 kHz):
  L1  freesound:679335  takecha, Shinjuku 22:07, bustling street        0 dB (bed)
  L2  freesound:380726  sergeeo, Shinjuku 2016 street walk              -10 dB, low-passed 6 kHz (distance)
  L3  freesound:364865  RutgerMuller, Tokyo evening street traffic      -14 dB, band 60 Hz-2.5 kHz (far traffic)
L2/L3 windows are the most stationary stretch (lowest short-term-loudness spread and no
events > 6 LU over their median), so no single car horn or drill gets "remembered".
Layers are loudness-matched, then summed with ffmpeg `amix` (normalize=0, weights).

Loop construction (ffmpeg `acrossfade`): with mixed signal s and crossfade length X,
    loop = acrossfade(P = s[X : L+X], Q = s[0 : X], d = X, equal-power curves)
The output ends on s[X-1] and starts on s[X], so the wrap is the recording's own continuity;
the blend s[L..L+X] -> s[0..X] sits inside the file. L is chosen by spectral match (1/3-octave
band levels of the two crossfade regions), loudness match and absence of transients, and both
cut points are snapped to rising zero crossings of the mid signal with a quiet side channel.
Verification: wrap discontinuity vs the file's own sample-to-sample statistics, spectral flux at
the wrap vs its distribution, short-term loudness either side of the wrap and through the fade.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal

from . import loudness as Lz
from .common import BUILD, ffmpeg, log

SR = 48000
CLEAN = BUILD / "clean"
OUT = BUILD / "masters" / "ambience"
NAME = "shinjuku-night-street-loop"
X_S = 6.0                 # crossfade length
L_RANGE_S = (80.0, 115.0)  # candidate loop lengths (spec: 60-120 s)

LAYERS = [
    {"id": "freesound:679335", "slug": "freesound-679335", "gain_db": 0.0, "filter": None},
    {"id": "freesound:380726", "slug": "freesound-380726", "gain_db": -10.0,
     "filter": "firequalizer=gain_entry='entry(0,0);entry(4000,0);entry(6000,-6);entry(9000,-18);entry(24000,-40)':accuracy=4"},
    {"id": "freesound:364865", "slug": "freesound-364865", "gain_db": -14.0,
     "filter": "highpass=f=60:poles=2,firequalizer=gain_entry='entry(0,0);entry(1500,0);entry(2500,-6);entry(5000,-24);entry(24000,-50)':accuracy=4"},
]


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
    mid = x[:, 0] + x[:, 1]
    side = np.abs(x[:, 0] - x[:, 1])
    a, b = max(1, near - radius), min(len(x) - 1, near + radius)
    zc = np.where((mid[a - 1:b - 1] < 0) & (mid[a:b] >= 0))[0] + a
    if not len(zc):
        return near
    # prefer crossings where the side signal is also small, then closeness
    score = side[zc] / (np.median(side[a:b]) + 1e-12) + np.abs(zc - near) / radius
    return int(zc[np.argmin(score)])


def choose_loop(s: np.ndarray) -> tuple[int, int, int, dict]:
    """Pick (a, X, L): source offset a, crossfade X, loop length L, on a 0.25 s grid.

    Score = 1/3-octave RMS distance between the two crossfade regions s[a:a+X] and
    s[a+L:a+L+X] + 2 x their loudness difference + 2 x transient excess in either region
    + 1 x how far the fade regions sit from the median short-term loudness (avoids a dip
    or bulge through the fade) + a small preference for longer loops."""
    X = int(X_S * SR)
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
        for L in range(int(L_RANGE_S[0] * SR), int(L_RANGE_S[1] * SR) + 1, g):
            b = a + L
            if b + X > len(s) or b not in bands:
                continue
            d_spec = float(np.sqrt(np.mean((bands[b] - bands[a]) ** 2)))
            d_loud = abs(loud[b] - loud[a])
            t = trans[a] + trans[b]
            level = abs((loud[a] + loud[b]) / 2 - med)
            longer = 0.5 * (L_RANGE_S[1] - L / SR) / (L_RANGE_S[1] - L_RANGE_S[0])
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


def build() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        base = read(CLEAN / f"{LAYERS[0]['slug']}.flac")
        n = len(base)
        base_l = Lz.integrated(base)
        layer_info, inputs, weights = [], [], []
        for k, lay in enumerate(LAYERS):
            x = base if k == 0 else read(CLEAN / f"{lay['slug']}.flac")
            if len(x) < n:
                raise SystemExit(f"{lay['id']} shorter than the bed")
            start, info = (0, {}) if k == 0 else stationary_window(x, n)
            seg = x[start:start + n]
            p = tdp / f"l{k}.wav"
            sf.write(p, seg, SR, subtype="FLOAT")
            if lay["filter"]:
                q = tdp / f"l{k}f.wav"
                ffmpeg("-i", str(p), "-af", lay["filter"], "-c:a", "pcm_f32le", str(q))
                p = q
            filt = read(p)[:n]
            match = base_l - Lz.integrated(filt)          # loudness-match to the bed first
            weights.append(10 ** ((match + lay["gain_db"]) / 20))
            inputs.append(p)
            layer_info.append({"id": lay["id"], "start_s": round(start / SR, 2), "gain_db": lay["gain_db"],
                               "loudness_match_db": round(match, 2), "filter": lay["filter"], **info})
            log(f"layer {lay['id']}: start {start/SR:.1f}s match {match:+.1f} dB rel {lay['gain_db']} dB {info}")
        mix = tdp / "mix.wav"
        args = []
        for p in inputs:
            args += ["-i", str(p)]
        w = " ".join(f"{v:.6f}" for v in weights)
        ffmpeg(*args, "-filter_complex", f"amix=inputs={len(inputs)}:duration=shortest:normalize=0:weights={w}",
               "-c:a", "pcm_f32le", str(mix))
        s = read(mix)
        a, x0, L, choice = choose_loop(s)
        s = s[a:]
        log(f"loop choice: {choice}")
        pth, qth = tdp / "p.wav", tdp / "q.wav"
        sf.write(pth, s[x0:L + x0], SR, subtype="FLOAT")
        sf.write(qth, s[:x0], SR, subtype="FLOAT")
        raw = tdp / "loop.wav"
        ffmpeg("-i", str(pth), "-i", str(qth), "-filter_complex",
               f"acrossfade=ns={x0}:c1=qsin:c2=qsin:o=1", "-c:a", "pcm_f32le", str(raw))
        y = read(raw)
    if len(y) != L:
        log(f"note: acrossfade output {len(y)} samples, expected {L}")
    corr = float(np.corrcoef(s[L:L + x0].mean(1), s[:x0].mean(1))[0, 1])
    seam = verify(y)
    # by construction the wrap must be the source's own sample pair s[x0-1] -> s[x0]
    seam["wrap_vs_source_max_err"] = float(max(np.abs(y[-1] - s[x0 - 1]).max(), np.abs(y[0] - s[x0]).max()))
    seam["source_step_at_cut"] = round(float(np.abs(s[x0] - s[x0 - 1]).max()), 6)
    # loudness through the fade region vs the rest (equal-power fade on uncorrelated material = flat)
    st = Lz.short_term(y, SR, hop=0.1)
    fade_start = int((L - x0) / SR / 0.1)
    seam["short_term_in_fade_lufs"] = round(float(np.median(st[max(0, fade_start - 30):])), 2)
    seam["short_term_elsewhere_lufs"] = round(float(np.median(st[: max(1, fade_start - 30)])), 2)
    seam["xfade_region_correlation"] = round(corr, 3)
    np.save(BUILD / "masters" / "ambience" / f"{NAME}.premaster.npy", y.astype(np.float32))
    meta = {"name": NAME, "layers": layer_info, "loop": choice, "seam": seam,
            "construction": "acrossfade(P=s[X:L+X], Q=s[0:X], d=X, c1=c2=qsin)"}
    (OUT / f"{NAME}.json").write_text(json.dumps(meta, indent=2))
    log(json.dumps(seam, indent=1))
    return meta


if __name__ == "__main__":
    build()
