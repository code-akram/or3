"""Step 4b: 8-take dress-shoe-on-concrete round-robin pool, dry + synthesised wet.

    uv run python -I -m audiopipe.footsteps [--source freesound:742969] [--name dress-concrete]

1. Segment the cleaned source into steps (audiopipe.steps.detect), keep isolated, unclipped,
   typical steps (peak within +-3 dB of the median, SNR >= 40 dB, gap to next >= 400 ms,
   150-450 ms long), pick the 8 most typical that are >= 2 s apart in the recording.
2. Extract mono (L+R)/2 with a 5 ms pre-roll, 2 ms raised-cosine fade-in, 40 ms fade-out.
3. Base-normalise every take to the same momentary-max loudness (FOLEY_STEP_LUFS_M).
4. Round-robin variation baked per take: pitch via `asetrate` resampling (changes pitch and
   length together, like Web Audio playbackRate; keeps the heel transient intact; rubberband
   was measured to soften the attack, see report), gain offsets in dB. Seeded and recorded.
5. Wet variant per take = dry step + synthesised splash at heel and toe impacts + EQ.
   v2 (round 2, the default): the round-1 splash (v1) was not evident on laptop speakers (user
   listening gate 2026-10-12, MacBook Air built-in speakers). Its energy sat in 350-2600 Hz (the
   slap, masked by the step itself) and above 6 kHz (spray + high shelf, where small drivers and
   the ear at low volume give little). v2 moves the splash into 1.5-6 kHz: a sharp crack
   (0.3 ms attack, 8 ms decay) over a short water body, a granular sheet of spray, louder
   Minnaert droplets, a small fall-back slap 15-25 ms after the impact, a 2.5-5 kHz presence
   lift instead of the >6 kHz shelf; the step keeps its level and the splash alone sits 1 LU
   under it (v1 renormalised the sum to dry + 1 LU with the splash peak 10 dB under the step's).
   Measured through a laptop-speaker model in audiopipe.speaker.
   v1 is still built (wet-v1/) for the before/after comparison.
Writes 24-bit FLAC to data/build/audio/masters/foley/<name>/{dry,wet,wet-v1}/ and pool.json.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal

from . import loudness as L
from .common import BUILD, clear_outputs, ffmpeg, log
from .steps import SR, detect, load

FOLEY_STEP_LUFS_M = -30.0   # per-take loudness match before variation (relative; see TP_CEIL_DBTP)
TP_CEIL_DBTP = -1.5         # hottest take of the pool (dry or wet) lands here
CENTS = [-50, -35, -20, -5, 5, 20, 35, 50]
GAINS_DB = [-1.5, -1.0, -0.5, 0.0, 0.0, 0.5, 1.0, 1.5]
WET = {
    # splash_db: splash peak relative to the dry step's peak; lift_lu: wet momentary max - dry
    "v1": {"splash_db": -10.0, "lift_lu": 1.0,
           "eq": ("firequalizer=gain_entry='entry(0,-2);entry(150,-2);entry(300,0);entry(4000,0);"
                  "entry(6000,2);entry(8000,3);entry(24000,3)':accuracy=4:fixed=1")},
    # splash_lu: the splash alone, momentary max relative to the dry step (step level kept)
    "v2": {"splash_db": -3.0, "splash_lu": -1.0,
           "eq": ("firequalizer=gain_entry='entry(0,-3);entry(150,-3);entry(300,0);entry(1200,0);"
                  "entry(2500,3);entry(5000,3);entry(8000,1);entry(24000,0)':accuracy=4:fixed=1")},
}
WET_VERSION = "v2"


PROFILES = {
    # airborne recordings: short steps
    "default": {"max_len_s": 0.6, "max_dur_ms": 450, "peak_tol_db": 3.0},
    # contact mics on the shoes (Yuval 205748): the whole roll rings for 450-700 ms
    "contact": {"max_len_s": 0.8, "max_dur_ms": 720, "peak_tol_db": 4.0},
}


def select(events: list[dict], n: int = 8, max_dur_ms: int = 450, peak_tol_db: float = 3.0, **_) -> list[dict]:
    pk = np.median([e["peak_db"] for e in events])
    good = [e for e in events if not e["truncated"] and e["snr_db"] >= 40 and abs(e["peak_db"] - pk) <= peak_tol_db
            and e["gap_next_ms"] >= 400 and 150 <= e["dur_ms"] <= max_dur_ms and e["pre_db"] <= e["floor_db"] + 6]
    if len(good) < n:
        raise SystemExit(f"only {len(good)} usable steps")
    feats = np.array([[e["peak_db"], np.log(e["centroid_hz"]), e["dur_ms"]] for e in good])
    z = np.abs((feats - np.median(feats, 0)) / (feats.std(0) + 1e-9)).sum(1)
    for spacing_s in (2.0, 1.5, 1.0, 0.5):
        chosen: list[dict] = []
        for i in np.argsort(z):
            e = good[i]
            if all(abs(e["onset"] - c["onset"]) >= spacing_s * SR for c in chosen):
                chosen.append(e)
            if len(chosen) == n:
                return sorted(chosen, key=lambda e: e["onset"])
    raise SystemExit(f"could not pick {n} spaced steps from {len(good)} candidates")


def extract(x: np.ndarray, e: dict) -> np.ndarray:
    a = max(0, e["onset"] - int(0.005 * SR))
    b = min(len(x), e["end"] + int(0.04 * SR))
    y = x[a:b].mean(axis=1).astype(np.float64)
    fi, fo = int(0.002 * SR), int(0.04 * SR)
    y[:fi] *= 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, fi))
    y[-fo:] *= 0.5 + 0.5 * np.cos(np.linspace(0, np.pi, fo))
    return y


def asetrate_pitch(y: np.ndarray, cents: float) -> np.ndarray:
    """Pitch by resampling (pitch and duration change together): ffmpeg asetrate + soxr."""
    rate = SR * 2 ** (cents / 1200)
    with tempfile.TemporaryDirectory() as td:
        i, o = Path(td) / "i.wav", Path(td) / "o.wav"
        sf.write(i, y, SR, subtype="FLOAT")
        ffmpeg("-i", str(i), "-af", f"asetrate={rate:.3f},aresample={SR}:resampler=soxr:precision=28", "-c:a", "pcm_f32le", str(o))
        z, _ = sf.read(o, dtype="float64")
    return z


def rubberband_pitch(y: np.ndarray, cents: float) -> np.ndarray:
    with tempfile.TemporaryDirectory() as td:
        i, o = Path(td) / "i.wav", Path(td) / "o.wav"
        sf.write(i, y, SR, subtype="FLOAT")
        ffmpeg("-i", str(i), "-af", f"rubberband=pitch={2 ** (cents / 1200):.6f}:transients=crisp:detector=percussive:window=short",
               "-c:a", "pcm_f32le", str(o))
        z, _ = sf.read(o, dtype="float64")
    return z


def attack_ms(y: np.ndarray) -> float:
    """10-90 % rise time of the peak-hold envelope around the first peak."""
    env = np.abs(signal.hilbert(y))
    pk = int(np.argmax(env[: int(0.08 * SR)]))
    p = env[pk]
    a = np.where(env[:pk + 1] < 0.1 * p)[0]
    b = np.where(env[:pk + 1] < 0.9 * p)[0]
    return ((b[-1] if len(b) else 0) - (a[-1] if len(a) else 0)) / SR * 1000


def impacts(y: np.ndarray) -> list[int]:
    """Heel + toe impact sample indices (two biggest envelope peaks >= 40 ms apart)."""
    env = np.abs(signal.hilbert(y))
    env = np.convolve(env, np.ones(48) / 48, mode="same")
    peaks, props = signal.find_peaks(env, distance=int(0.04 * SR), height=env.max() * 0.15)
    order = np.argsort(props["peak_heights"])[::-1][:2]
    return sorted(int(peaks[i]) for i in order)


def splash_v1(n: int, at: list[int], rng: np.random.Generator, level: float) -> np.ndarray:
    """Round-1 splash at each impact: slap + spray + bubble droplets."""
    out = np.zeros(n)
    t = np.arange(n) / SR
    for k, i0 in enumerate(at):
        s = 1.0 if k == 0 else 0.55  # toe splash is smaller than the heel's
        # slap: band-passed noise, 1 ms attack, 25 ms decay
        b, a = signal.butter(2, [350, 2600], btype="band", fs=SR)
        nz = signal.lfilter(b, a, rng.standard_normal(n))
        env = np.where(t >= i0 / SR, np.exp(-(t - i0 / SR) / 0.025), 0) * np.clip((t - i0 / SR) / 0.001, 0, 1)
        out += 0.9 * s * nz * env / (np.abs(nz).max() + 1e-9)
        # spray: high band noise, starts 4 ms later, 3 ms attack, 50 ms decay
        b, a = signal.butter(2, [2500, 12000], btype="band", fs=SR)
        nz = signal.lfilter(b, a, rng.standard_normal(n))
        t1 = i0 / SR + 0.004
        env = np.where(t >= t1, np.exp(-(t - t1) / 0.05), 0) * np.clip((t - t1) / 0.003, 0, 1)
        out += 0.35 * s * nz * env / (np.abs(nz).max() + 1e-9)
        # droplets: Minnaert bubbles, f = 3.26 / r (r in m); 1-4 kHz, rising chirp, 4-15 ms decay
        for _ in range(int(rng.integers(5, 11) * s) + 1):
            td = i0 / SR + rng.exponential(0.06) + 0.008
            if td >= n / SR - 0.02:
                continue
            f0 = rng.uniform(1100, 4200)
            tau = rng.uniform(0.004, 0.015)
            amp = 10 ** (rng.uniform(-24, -12) / 20) * s
            tt = t - td
            m = tt >= 0
            ph = 2 * np.pi * f0 * (tt + 0.5 * 18.0 * tt ** 2)  # ~+18 %/s^-1 upward glide
            out[m] += amp * np.sin(ph[m]) * np.exp(-tt[m] / tau)
    return out * level


def _burst(n: int, t: np.ndarray, t0: float, band: tuple[float, float], attack: float, decay: float,
           rng: np.random.Generator) -> np.ndarray:
    b, a = signal.butter(2, band, btype="band", fs=SR)
    nz = signal.lfilter(b, a, rng.standard_normal(n))
    env = np.where(t >= t0, np.exp(-(t - t0) / decay), 0) * np.clip((t - t0) / attack, 0, 1)
    return nz * env / (np.abs(nz).max() + 1e-9)


def splash_v2(n: int, at: list[int], rng: np.random.Generator, level: float) -> np.ndarray:
    """Small-speaker splash at each impact, energy in 1.5-6 kHz: crack + water body + granular
    spray + fall-back slap + Minnaert droplets. Peak normalised to `level`."""
    out = np.zeros(n)
    t = np.arange(n) / SR
    for k, i0 in enumerate(at):
        s = 1.0 if k == 0 else 0.6   # toe splash is smaller than the heel's
        t0 = i0 / SR
        out += 1.0 * s * _burst(n, t, t0, (1500, 6000), 0.0003, 0.008, rng)        # crack
        out += 0.45 * s * _burst(n, t, t0, (600, 2500), 0.001, 0.02, rng)          # water body
        # spray sheet: band noise gated by ~400 grains/s of 1 ms bumps (fizz, not hiss)
        grains = np.zeros(n)
        g0 = t0 + 0.003
        for tg in g0 + np.cumsum(rng.exponential(1 / 400, 80)):
            j = int(tg * SR)
            if j < n - 48:
                grains[j:j + 48] += np.hanning(48) * rng.uniform(0.3, 1.0)
        out += 0.6 * s * _burst(n, t, g0, (1800, 7000), 0.002, 0.09, rng) * (0.35 + grains)
        tf = t0 + rng.uniform(0.015, 0.025)                                          # fall-back slap
        out += 0.35 * s * _burst(n, t, tf, (1500, 5000), 0.0005, 0.006, rng)
        for _ in range(int(rng.integers(8, 17) * s) + 1):                           # Minnaert droplets
            td = t0 + rng.exponential(0.1) + 0.01
            if td >= n / SR - 0.02:
                continue
            f0 = rng.uniform(1500, 5000)
            tau = rng.uniform(0.005, 0.02)
            amp = 10 ** (rng.uniform(-18, -6) / 20) * s
            tt = t - td
            m = tt >= 0
            ph = 2 * np.pi * f0 * (tt + 0.5 * 18.0 * tt ** 2)
            out[m] += amp * np.sin(ph[m]) * np.exp(-tt[m] / tau)
    return out / (np.abs(out).max() + 1e-12) * level


SPLASH = {"v1": splash_v1, "v2": splash_v2}


def _eq_raw(y: np.ndarray, version: str) -> np.ndarray:
    with tempfile.TemporaryDirectory() as td:
        i, o = Path(td) / "i.wav", Path(td) / "o.wav"
        sf.write(i, y, SR, subtype="FLOAT")
        ffmpeg("-i", str(i), "-af", WET[version]["eq"], "-c:a", "pcm_f32le", str(o))
        z, _ = sf.read(o, dtype="float64")
    return z


_EQ_DELAY: dict[str, int] = {}


def eq_delay(version: str = WET_VERSION) -> int:
    """Group delay of the linear-phase firequalizer in samples, measured once with an impulse
    (the FIR is symmetric, so its peak sits at the delay; ~480 samples = firequalizer's 10 ms)."""
    if version not in _EQ_DELAY:
        imp = np.zeros(SR // 2)
        imp[0] = 1.0
        _EQ_DELAY[version] = int(np.argmax(np.abs(_eq_raw(imp, version))))
    return _EQ_DELAY[version]


def eq_wet(y: np.ndarray, version: str = WET_VERSION) -> np.ndarray:
    """EQ with its group delay removed, so the wet take stays sample-aligned with the dry one."""
    d = eq_delay(version)
    z = _eq_raw(np.concatenate([y, np.zeros(d)]), version)
    return z[d: d + len(y)]


def wet_parts(dry: np.ndarray, hits: list[int], seed: int, version: str = WET_VERSION) -> dict[str, np.ndarray]:
    """Wet take and its two components after EQ, end fade and loudness lift. The EQ is linear,
    so wet = step + splash exactly and the splash can be measured on its own."""
    w = WET[version]
    level = np.abs(dry).max() * 10 ** (w["splash_db"] / 20)   # splash peak relative to the step peak
    drypad = np.concatenate([dry, np.zeros(int(0.12 * SR))])  # room for the droplets to finish
    sp = SPLASH[version](len(drypad), hits, np.random.default_rng(seed), level)
    f = int(0.03 * SR)
    ramp = np.concatenate([np.ones(len(drypad) - f), np.linspace(1, 0, f)])
    step, spl = eq_wet(drypad, version) * ramp, eq_wet(sp, version) * ramp
    if "splash_lu" in w:
        # v2: the step keeps its level; the splash alone sits splash_lu under the dry step's
        # momentary max (a splash at -3 dB *peak* is much louder than the click once K-weighted,
        # so renormalising the sum, as v1 did, would pull the heel click down ~12 dB)
        spl *= 10 ** ((L.momentary_max(dry) + w["splash_lu"] - L.momentary_max(spl)) / 20)
        return {"wet": step + spl, "step": step, "splash": spl}
    # v1: a wet step is a little louder than the dry one, not a different category
    wet = step + spl
    g = 10 ** ((L.momentary_max(dry) + w["lift_lu"] - L.momentary_max(wet)) / 20)
    return {"wet": wet * g, "step": step * g, "splash": spl * g}


def write(path: Path, y: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, y, SR, subtype="PCM_24", format="FLAC")


def build(source_slug: str, name: str, seed: int, profile: str = "default") -> dict:
    x = load(source_slug)
    prof = PROFILES[profile]
    events = detect(x, max_len=prof["max_len_s"])
    chosen = select(events, **prof)
    rng = np.random.default_rng(seed)
    cents = rng.permutation(CENTS).tolist()
    gains = rng.permutation(GAINS_DB).tolist()
    root = BUILD / "masters" / "foley" / name
    for variant in ("dry", "wet", "wet-v1"):   # spatialise and master glob these folders
        clear_outputs(root / variant, "*.flac")
    takes, audio = [], []
    for k, e in enumerate(chosen, 1):
        y = extract(x, e)
        y *= 10 ** ((FOLEY_STEP_LUFS_M - L.momentary_max(y)) / 20)
        base_attack = attack_ms(y)
        dry = asetrate_pitch(y, cents[k - 1]) * 10 ** (gains[k - 1] / 20)
        hits = impacts(dry)
        wet = wet_parts(dry, hits, seed * 100 + k)["wet"]
        wet1 = wet_parts(dry, hits, seed * 100 + k, "v1")["wet"]
        audio.append((dry, wet, wet1))
        takes.append({
            "take": k, "source_onset_s": round(e["onset"] / SR, 3), "source_peak_db": e["peak_db"],
            "pitch_cents": cents[k - 1], "gain_db": gains[k - 1], "impacts_ms": [round(h / SR * 1000, 1) for h in hits],
            "attack_ms_before_pitch": round(base_attack, 2), "attack_ms_after_pitch": round(attack_ms(dry), 2),
            "wet_centroid_shift_hz": round(centroid(wet) - centroid(dry)),
        })
    # Heel clicks have a peak-to-loudness ratio near 30 dB, so the binding limit for one-shots is
    # the peak, not loudness: one gain for the whole pool puts the hottest take at TP_CEIL.
    # The pool gain comes from the dry and v1-wet takes (as in round 1, so the approved dry takes
    # stay bit-identical); a v2 wet take that would then pass the ceiling gets its own trim.
    max_tp = max(max(L.true_peak_db(d), L.true_peak_db(w1)) for d, _, w1 in audio)
    pool_gain = TP_CEIL_DBTP - max_tp
    for (dry, wet, wet1), t in zip(audio, takes):
        dry, wet, wet1 = (z * 10 ** (pool_gain / 20) for z in (dry, wet, wet1))
        t["wet_trim_db"] = round(min(0.0, TP_CEIL_DBTP - L.true_peak_db(wet)), 2)
        wet *= 10 ** (t["wet_trim_db"] / 20)
        write(root / "dry" / f"{name}-dry-{t['take']:02d}.flac", dry)
        write(root / "wet" / f"{name}-wet-{t['take']:02d}.flac", wet)
        write(root / "wet-v1" / f"{name}-wet-v1-{t['take']:02d}.flac", wet1)
        t["wet_v1_tp"] = round(L.true_peak_db(wet1), 2)
        t["dry"], t["wet"] = L.summary(dry[:, None]), L.summary(wet[:, None])
        log(f"take {t['take']}: cents {t['pitch_cents']:+d} gain {t['gain_db']:+.1f} dB "
            f"dry M {t['dry']['lufs_m_max']} TP {t['dry']['true_peak_dbtp']} | wet M {t['wet']['lufs_m_max']} TP {t['wet']['true_peak_dbtp']}")
    pool = {"name": name, "source": source_slug, "seed": seed, "profile": profile, "variation": "asetrate pitch + gain",
            "base_lufs_m": FOLEY_STEP_LUFS_M, "pool_gain_db": round(pool_gain, 2), "tp_ceiling_dbtp": TP_CEIL_DBTP,
            "wet_version": WET_VERSION, "wet": WET, "takes": takes, "candidates": len(events)}
    (root / "pool.json").write_text(json.dumps(pool, indent=2))
    return pool


def centroid(y: np.ndarray) -> float:
    f, p = signal.welch(y, SR, nperseg=1024)
    return float((f * p).sum() / p.sum())


def compare_pitch(source_slug: str) -> None:
    """Diagnostic: attack time after asetrate vs rubberband for the same take and shift."""
    x = load(source_slug)
    chosen = select(detect(x))
    for c in (-50, 50):
        rows = []
        for e in chosen:
            y = extract(x, e)
            rows.append((attack_ms(y), attack_ms(asetrate_pitch(y, c)), attack_ms(rubberband_pitch(y, c))))
        r = np.array(rows)
        print(f"{source_slug} {c:+d} cents: attack ms median original {np.median(r[:,0]):.2f} | "
              f"asetrate {np.median(r[:,1]):.2f} | rubberband {np.median(r[:,2]):.2f}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="freesound-742969")
    ap.add_argument("--name", default="dress-concrete")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--profile", default="default", choices=sorted(PROFILES))
    ap.add_argument("--compare-pitch", action="store_true")
    a = ap.parse_args()
    if a.compare_pitch:
        compare_pitch(a.source)
        return
    build(a.source, a.name, a.seed, a.profile)


if __name__ == "__main__":
    main()
