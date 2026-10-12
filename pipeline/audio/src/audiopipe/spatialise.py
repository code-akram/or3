"""Step 5: convolve the footstep takes with the spike-6 alley IR via ffmpeg `afir`.

    uv run python -I -m audiopipe.spatialise                 # real IR if present, else placeholder
    uv run python -I -m audiopipe.spatialise --placeholder   # force the synthetic placeholder

IR: data/build/audio/ir/alley-01.wav (Steam Audio bake from the PLATEAU chunk, spike 6).
If it is missing, a clearly labelled synthetic placeholder is generated at
data/build/audio/spatialise/PLACEHOLDER-synthetic-alley.wav and every output is marked
`synthetic_placeholder` in provenance (the audit's --release mode then fails).

Two IR kinds are handled:
  * full IR (direct sound at t=0, e.g. alley-01.wav): the IR is scaled so the direct path has
    unity gain; out = afir(step, IR). The source keeps its level and gains the alley.
  * reflections-only IR (placeholder, alley-01-wet.wav): out = step + afir(step, IR * g), with g
    set for a direct-to-reverberant ratio of DRR_DB.
Mono takes are upmixed to stereo first; the stereo IR's two channels give the stereo image.
Inputs are padded by the IR length so the tail is kept. IR length capped at 2 s (NOTES §12).

IR snapshot: data/build/audio/ir/ belongs to spike 6 and is rewritten whenever its bake reruns
(Steam Audio is stochastic, so every rebake has a new sha256; that is how the audit's
--check-files broke on 2026-10-12). Every run therefore copies the IR it consumes to
data/build/audio/spatialise/alley-01.consumed.wav; provenance, the footsteps and the round-2
ambience reverb (audiopipe.bed) all point at that copy, so a later rebake cannot invalidate
them. To adopt a new bake, rerun `run.sh build` (bed and spatialise refresh the snapshot).
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from . import loudness as Lz
from .common import BUILD, REAL_IR, ffmpeg, file_sha256, log

SR = 48000
IR_DIR = BUILD / "spatialise"   # our working files; data/build/audio/ir/ belongs to spike 6
PLACEHOLDER = IR_DIR / "PLACEHOLDER-synthetic-alley.wav"
IR_SNAPSHOT = IR_DIR / "alley-01.consumed.wav"   # the copy of REAL_IR this build consumed
POOLS = ["dress-concrete"]
DRR_DB = 4.0
TP_CEIL_DBTP = -1.5
ALLEY_LIFT_LU = 2.0


def make_placeholder(path: Path, seed: int = 11) -> None:
    """Synthetic alley: 2 m wide street canyon flutter (lateral walls), ground bounce, and a
    frequency-dependent exponential tail (RT60 0.9 s low / 0.6 s mid / 0.35 s high). No direct path."""
    rng = np.random.default_rng(seed)
    n = int(1.2 * SR)
    ir = np.zeros((n, 2))
    c = 343.0
    # flutter between parallel walls 2 m apart, listener near the centre: images every 2 m
    for k in range(1, 40):
        d = np.hypot(2.0 * k, 4.0)                    # source 4 m along the alley
        t = int((d - 4.0) / c * SR) + int(0.002 * SR)
        if t >= n:
            break
        g = (0.85 ** k) * (4.0 / d)
        ch = k % 2
        ir[t, ch] += g
        ir[t, 1 - ch] += 0.6 * g
    # tail: three bands of decaying noise
    from scipy import signal
    t = np.arange(n) / SR
    tail = np.zeros((n, 2))
    for lo, hi, rt in ((60, 500, 0.9), (500, 4000, 0.6), (4000, 16000, 0.35)):
        b, a = signal.butter(2, [lo, hi], btype="band", fs=SR)
        nz = signal.lfilter(b, a, rng.standard_normal((n, 2)), axis=0)
        tail += nz * np.exp(-6.91 * t / rt)[:, None]
    tail *= np.clip((t - 0.015) / 0.02, 0, 1)[:, None]
    ir += tail * 0.15 / np.abs(tail).max()
    ir[-int(0.05 * SR):] *= np.linspace(1, 0, int(0.05 * SR))[:, None]
    ir /= np.abs(ir).max()
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, ir.astype(np.float32), SR, subtype="FLOAT")
    (path.with_suffix(".json")).write_text(json.dumps({
        "SYNTHETIC_PLACEHOLDER": True, "replace_with": str(REAL_IR),
        "model": "2 m flutter images + 3-band exponential tail (RT60 0.9/0.6/0.35 s), no direct path",
        "seed": seed}, indent=2))


def prepare_ir(src: Path, dst: Path) -> dict:
    """Resample to 48 kHz, stereo, cap at 2 s, scale (direct = 1, or energy for reflections-only)."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "ir.wav"
        ffmpeg("-i", str(src), "-af", f"aresample={SR}:resampler=soxr:precision=28", "-ac", "2",
               "-c:a", "pcm_f32le", str(tmp))
        ir, _ = sf.read(tmp, dtype="float64", always_2d=True)
    ir = ir[: 2 * SR]
    e = (ir ** 2).sum(axis=1)
    head = int(0.001 * SR)
    direct_peak = float(np.abs(ir[:head]).max())
    has_direct = direct_peak >= 0.5 * float(np.abs(ir).max())
    if has_direct:
        ir /= direct_peak                                 # direct path at unity gain
        drr = 10 * np.log10(e[:head].sum() / max(e[head:].sum(), 1e-20))
        mode = "full"
    else:
        ir /= np.sqrt(e.sum() / 2)                        # unit energy per channel
        ir *= 10 ** (-DRR_DB / 20)
        drr = DRR_DB
        mode = "reflections+dry"
    sf.write(dst, ir.astype(np.float32), SR, subtype="FLOAT")
    return {"mode": mode, "direct_peak_raw": round(direct_peak, 4), "drr_db": round(float(drr), 2),
            "length_s": round(len(ir) / SR, 3), "lr_correlation": round(float(np.corrcoef(ir[:, 0], ir[:, 1])[0, 1]), 3)}


def convolve(take: Path, ir: Path, out: Path, mode: str, ir_len_s: float) -> np.ndarray:
    pad = f"apad=pad_dur={ir_len_s + 0.05:.3f}"
    if mode == "full":
        graph = f"[0]pan=stereo|c0=c0|c1=c0,{pad}[d];[d][1]afir=gtype=none:irnorm=-1:irfmt=input:dry=1:wet=1[o]"
    else:
        graph = (f"[0]pan=stereo|c0=c0|c1=c0,{pad},asplit[d][s];[s][1]afir=gtype=none:irnorm=-1:irfmt=input:dry=1:wet=1[r];"
                 f"[d][r]amix=inputs=2:normalize=0[o]")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp.wav")
    ffmpeg("-i", str(take), "-i", str(ir), "-filter_complex", graph, "-map", "[o]", "-c:a", "pcm_f32le", str(tmp))
    y, _ = sf.read(tmp, dtype="float64", always_2d=True)
    tmp.unlink()
    # trim trailing near-silence (below -90 dBFS) and fade the last 20 ms
    a = np.abs(y).max(axis=1)
    last = int(np.where(a > 10 ** (-90 / 20))[0][-1]) + 1
    y = y[:last]
    f = min(len(y), int(0.02 * SR))
    y[-f:] *= np.linspace(1, 0, f)[:, None]
    return y  # float; written by run() after the pool gain (avoids clipping a 24-bit intermediate)


def snapshot_ir() -> Path | None:
    """Copy spike 6's current IR to IR_SNAPSHOT (None if there is no real IR)."""
    if not REAL_IR.exists():
        return None
    IR_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(REAL_IR, IR_SNAPSHOT)
    return IR_SNAPSHOT


def run(force_placeholder: bool = False) -> dict:
    IR_DIR.mkdir(parents=True, exist_ok=True)
    if REAL_IR.exists() and not force_placeholder:
        src, placeholder = snapshot_ir(), False
    else:
        if not PLACEHOLDER.exists():
            make_placeholder(PLACEHOLDER)
        src, placeholder = PLACEHOLDER, True
        log("WARNING: real IR missing; using the SYNTHETIC PLACEHOLDER")
    prepared = IR_DIR / "prepared-for-footsteps.wav"
    info = prepare_ir(src, prepared)
    info |= {"source_ir": str(src.relative_to(BUILD.parent.parent)), "source_ir_sha256": file_sha256(src),
             "snapshot_of": None if placeholder else str(REAL_IR.relative_to(BUILD.parent.parent)),
             "synthetic_placeholder": placeholder}
    log(f"IR: {info}")
    results = []
    for pool in POOLS:
        root = BUILD / "masters" / "foley" / pool
        pairs = []
        for variant in ("dry", "wet"):
            for take in sorted((root / variant).glob("*.flac")):
                out = root / f"alley-{variant}" / take.name.replace(f"-{variant}-", f"-alley-{variant}-")
                ys_raw = convolve(take, prepared, out, info["mode"], info["length_s"])
                pairs.append((take, out, ys_raw))
        # One gain for the alley pool: mean momentary-max = source pool + ALLEY_LIFT_LU
        # (a reverberant alley reads louder, but must not jump out), capped by the TP ceiling.
        xs = [sf.read(t, dtype="float64", always_2d=True)[0] for t, _, _ in pairs]
        ys = [y for _, _, y in pairs]
        # compare like with like: the mono source measured as dual-mono stereo
        src_m = np.mean([Lz.momentary_max(np.repeat(x, 2, axis=1)) for x in xs])
        out_m = np.mean([Lz.momentary_max(y) for y in ys])
        max_tp = max(Lz.true_peak_db(y) for y in ys)
        gain = min(TP_CEIL_DBTP - max_tp, src_m + ALLEY_LIFT_LU - out_m)
        for (take, out, _), x, y in zip(pairs, xs, ys):
            y = y * 10 ** (gain / 20)
            sf.write(out, y, SR, subtype="PCM_24", format="FLAC")
            results.append({"take": take.name, "out": out.name,
                            "source_m_dualmono": round(Lz.momentary_max(np.repeat(x, 2, axis=1)), 2),
                            "alley_m": round(Lz.momentary_max(y), 2), "alley_tp": round(Lz.true_peak_db(y), 2),
                            "alley_len_s": round(len(y) / SR, 3)})
        (root / "alley.json").write_text(json.dumps({"ir": info, "pool_gain_db": round(gain, 2), "takes": results}, indent=2))
        log(f"{pool}: alley pool gain {gain:+.2f} dB (src mean M {src_m:.1f}, raw alley mean M {out_m:.1f}, raw max TP {max_tp:.1f})")
    log(f"convolved {len(results)} takes")
    return info


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--placeholder", action="store_true")
    a = ap.parse_args()
    run(a.placeholder)


if __name__ == "__main__":
    main()
