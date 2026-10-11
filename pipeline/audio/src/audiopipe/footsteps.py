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
5. Wet variant per take = dry step + synthesised splash transient (slap + spray + Minnaert
   bubble droplets at heel and toe impacts) + shelf EQ (firequalizer: -2 dB low shelf below
   200 Hz, +3 dB high shelf above 6 kHz).
Writes 24-bit FLAC to data/build/audio/masters/foley/<name>/{dry,wet}/ and pool.json.
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
from .common import BUILD, ffmpeg, log
from .steps import SR, detect, load

FOLEY_STEP_LUFS_M = -30.0   # per-take loudness match before variation (relative; see TP_CEIL_DBTP)
TP_CEIL_DBTP = -1.5         # hottest take of the pool (dry or wet) lands here
CENTS = [-50, -35, -20, -5, 5, 20, 35, 50]
GAINS_DB = [-1.5, -1.0, -0.5, 0.0, 0.0, 0.5, 1.0, 1.5]
SPLASH_DB = -10.0   # splash peak relative to the dry step's peak
WET_LIFT_LU = 1.0   # wet take momentary-max = dry take + 1 LU
WET_EQ = ("firequalizer=gain_entry='entry(0,-2);entry(150,-2);entry(300,0);entry(4000,0);"
          "entry(6000,2);entry(8000,3);entry(24000,3)':accuracy=4:fixed=1")


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


def splash(n: int, at: list[int], rng: np.random.Generator, level: float) -> np.ndarray:
    """Synthesised water splash at each impact: slap + spray + bubble droplets."""
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


def eq_wet(y: np.ndarray) -> np.ndarray:
    with tempfile.TemporaryDirectory() as td:
        i, o = Path(td) / "i.wav", Path(td) / "o.wav"
        sf.write(i, y, SR, subtype="FLOAT")
        ffmpeg("-i", str(i), "-af", WET_EQ, "-c:a", "pcm_f32le", str(o))
        z, _ = sf.read(o, dtype="float64")
    return z[: len(y)]


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
    takes, audio = [], []
    for k, e in enumerate(chosen, 1):
        y = extract(x, e)
        y *= 10 ** ((FOLEY_STEP_LUFS_M - L.momentary_max(y)) / 20)
        base_attack = attack_ms(y)
        dry = asetrate_pitch(y, cents[k - 1]) * 10 ** (gains[k - 1] / 20)
        hits = impacts(dry)
        level = np.abs(dry).max() * 10 ** (SPLASH_DB / 20)  # splash peak relative to the step peak
        tail = np.zeros(int(0.12 * SR))                      # room for the droplets to finish
        drypad = np.concatenate([dry, tail])
        sp = splash(len(drypad), hits, np.random.default_rng(seed * 100 + k), level)
        wet = eq_wet(drypad + sp)
        wet[-int(0.03 * SR):] *= np.linspace(1, 0, int(0.03 * SR))
        # a wet step is a little louder than the dry one, not a different category
        wet *= 10 ** ((L.momentary_max(dry) + WET_LIFT_LU - L.momentary_max(wet)) / 20)
        audio.append((dry, wet))
        takes.append({
            "take": k, "source_onset_s": round(e["onset"] / SR, 3), "source_peak_db": e["peak_db"],
            "pitch_cents": cents[k - 1], "gain_db": gains[k - 1], "impacts_ms": [round(h / SR * 1000, 1) for h in hits],
            "attack_ms_before_pitch": round(base_attack, 2), "attack_ms_after_pitch": round(attack_ms(dry), 2),
            "wet_centroid_shift_hz": round(centroid(wet) - centroid(dry)),
        })
    # Heel clicks have a peak-to-loudness ratio near 30 dB, so the binding limit for one-shots is
    # the peak, not loudness: one gain for the whole pool puts the hottest take at TP_CEIL.
    max_tp = max(max(L.true_peak_db(d), L.true_peak_db(w)) for d, w in audio)
    pool_gain = TP_CEIL_DBTP - max_tp
    for (dry, wet), t in zip(audio, takes):
        dry, wet = dry * 10 ** (pool_gain / 20), wet * 10 ** (pool_gain / 20)
        write(root / "dry" / f"{name}-dry-{t['take']:02d}.flac", dry)
        write(root / "wet" / f"{name}-wet-{t['take']:02d}.flac", wet)
        t["dry"], t["wet"] = L.summary(dry[:, None]), L.summary(wet[:, None])
        log(f"take {t['take']}: cents {t['pitch_cents']:+d} gain {t['gain_db']:+.1f} dB "
            f"dry M {t['dry']['lufs_m_max']} TP {t['dry']['true_peak_dbtp']} | wet M {t['wet']['lufs_m_max']} TP {t['wet']['true_peak_dbtp']}")
    pool = {"name": name, "source": source_slug, "seed": seed, "profile": profile, "variation": "asetrate pitch + gain",
            "base_lufs_m": FOLEY_STEP_LUFS_M, "pool_gain_db": round(pool_gain, 2), "tp_ceiling_dbtp": TP_CEIL_DBTP,
            "wet_eq": WET_EQ, "takes": takes, "candidates": len(events)}
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
