"""Laptop-speaker check: wet-step splash audibility (v1 vs v2) and the mix at 25 % / 60 % volume.

    uv run python -I -m audiopipe.speaker

The listening target is the MacBook Air's built-in speakers (user, 2026-10-12). This is a
generic small-laptop model, NOT a measured Air response (assumptions, all flagged in the report):
  * response: 4th-order Butterworth high-pass at 200 Hz (small drivers give almost nothing
    below), +2 dB peak at 2.5 kHz (Q 1, the usual small-driver presence bump), 2nd-order
    low-pass at 14 kHz;
  * volume: macOS volume steps are roughly logarithmic; assume 60 % = -10 dB and 25 % = -28 dB
    relative to full volume;
  * level: a -14 LUFS programme at full volume gives about 75 dBA at the listener (laptop on a
    desk, ~50 cm), i.e. SPL ~ LUFS(after the model) + 89 + volume dB; quiet room ~30 dBA.
LUFS is used as a dBA proxy; the absolute numbers are rough, the comparisons (v1 vs v2, step vs
bed, splash vs bed in the same band) do not depend on the calibration.

Splash metrics per take (wet = step + splash exactly, see footsteps.wet_parts; all through the
model, window 0-300 ms after the heel impact):
  splash/step 1.5-6k  splash energy relative to the step's own energy in 1.5-6 kHz (dB)
  unmasked            fraction of 1-8 kHz time-frequency cells (5.3 ms hop) where the splash is
                      at least as loud as the step, among cells within 40 dB of the take's peak
  tail 60-300 ms      wet minus dry energy, 60-300 ms after the impact (dB): the part of the
                      splash that outlasts the heel click
  dM                  wet minus dry momentary max (LU)
Mix check: bed = the 3-minute ambience preview at the ambience bus gain; steps = the main pool at
the foley bus gain (page "walk" demo gains); per volume, estimated SPL of bed, steps and of the
splash in its band, and the splash-to-bed margin in 1.5-6 kHz.
Writes data/build/audio/analysis/speaker/report.{json,md}.
"""

from __future__ import annotations

import json

import numpy as np
import soundfile as sf
from scipy import signal

from . import bed
from . import footsteps as fs
from . import loudness as Lz
from .common import BUILD, log

SR = 48000
OUT = BUILD / "analysis" / "speaker"
VOLUMES_DB = {"60%": -10.0, "25%": -28.0}
SPL_OFFSET = 89.0          # SPL ~ LUFS + 89 at full volume (assumed)
ROOM_DBA = 30.0
BAND = (1500.0, 6000.0)
BUS_GAINS_DB = {"ambience": -6.0, "foley": 6.0}   # = master.BUS_GAINS_DB (page walk demo)


def _peaking(f0: float, gain_db: float, q: float) -> tuple[np.ndarray, np.ndarray]:
    a = 10 ** (gain_db / 40)
    w = 2 * np.pi * f0 / SR
    al = np.sin(w) / (2 * q)
    b = np.array([1 + al * a, -2 * np.cos(w), 1 - al * a])
    d = np.array([1 + al / a, -2 * np.cos(w), 1 - al / a])
    return b / d[0], d / d[0]


def laptop(x: np.ndarray) -> np.ndarray:
    """The small-laptop speaker model (applied per channel)."""
    y = signal.sosfilt(signal.butter(4, 200, "highpass", fs=SR, output="sos"), x, axis=0)
    b, a = _peaking(2500, 2.0, 1.0)
    y = signal.lfilter(b, a, y, axis=0)
    return signal.sosfilt(signal.butter(2, 14000, "lowpass", fs=SR, output="sos"), y, axis=0)


def band_energy(x: np.ndarray, lo: float = BAND[0], hi: float = BAND[1]) -> float:
    m = x if x.ndim == 1 else x.mean(axis=1)
    X = np.fft.rfft(m)
    f = np.fft.rfftfreq(len(m), 1 / SR)
    return float((np.abs(X[(f >= lo) & (f < hi)]) ** 2).sum() / len(m))


def db(v: float) -> float:
    return 10 * np.log10(max(v, 1e-30))


def splash_metrics(dry: np.ndarray, parts: dict[str, np.ndarray], hit: int) -> dict:
    d = laptop(np.concatenate([dry, np.zeros(len(parts["wet"]) - len(dry))]))
    st, sp, wet = laptop(parts["step"]), laptop(parts["splash"]), laptop(parts["wet"])
    w = slice(hit, min(len(wet), hit + int(0.3 * SR)))
    tail = slice(min(len(wet), hit + int(0.06 * SR)), min(len(wet), hit + int(0.3 * SR)))
    f, _, S = signal.stft(st[w], SR, nperseg=512, noverlap=256)
    _, _, P = signal.stft(sp[w], SR, nperseg=512, noverlap=256)
    rows = (f >= 1000) & (f <= 8000)
    s2, p2 = np.abs(S[rows]) ** 2, np.abs(P[rows]) ** 2
    live = (s2 + p2) > (s2 + p2).max() * 1e-4
    return {
        "splash_to_step_band_db": round(db(band_energy(sp[w])) - db(band_energy(st[w])), 2),
        "unmasked_fraction": round(float(((p2 >= s2) & live).sum() / max(live.sum(), 1)), 3),
        "tail_wet_minus_dry_db": round(db((wet[tail] ** 2).sum()) - db((d[tail] ** 2).sum()), 2),
        "band_wet_minus_dry_db": round(db(band_energy(wet[w])) - db(band_energy(d[w])), 2),
        "dM_lu": round(Lz.momentary_max(wet[:, None]) - Lz.momentary_max(d[:, None]), 2),
    }


def splash_check() -> dict:
    root = BUILD / "masters" / "foley" / "dress-concrete"
    pool = json.loads((root / "pool.json").read_text())
    out = {"v1": [], "v2": []}
    for t in pool["takes"]:
        k = t["take"]
        dry, _ = sf.read(root / "dry" / f"dress-concrete-dry-{k:02d}.flac", dtype="float64")
        hits = fs.impacts(dry)
        for v in ("v1", "v2"):
            parts = fs.wet_parts(dry, hits, pool["seed"] * 100 + k, v)
            if v == fs.WET_VERSION:   # the parts must rebuild the shipped file (24-bit rounding only)
                parts = {p: y * 10 ** (t["wet_trim_db"] / 20) for p, y in parts.items()}
                shipped, _ = sf.read(root / "wet" / f"dress-concrete-wet-{k:02d}.flac", dtype="float64")
                err = np.abs(shipped - parts["wet"][:len(shipped)]).max()
                assert err < 1e-5, (k, err)
            out[v].append(splash_metrics(dry, parts, hits[0]))
    med = {v: {m: round(float(np.median([r[m] for r in rows])), 3) for m in rows[0]} for v, rows in out.items()}
    return {"per_take": out, "median": med}


def mix_check() -> dict:
    prev, _ = sf.read(BUILD / "masters" / "ambience-v2" / f"{bed.NAME}-preview.flac", dtype="float64", always_2d=True)
    amb = laptop(prev) * 10 ** (BUS_GAINS_DB["ambience"] / 20)
    root = BUILD / "masters" / "foley" / "dress-concrete"
    pool = json.loads((root / "pool.json").read_text())
    g = 10 ** (BUS_GAINS_DB["foley"] / 20)
    steps, splash_band = {"dry": [], "wet": []}, []
    for t in pool["takes"]:
        k = t["take"]
        for v in ("dry", "wet"):
            y, _ = sf.read(root / v / f"dress-concrete-{v}-{k:02d}.flac", dtype="float64")
            steps[v].append(Lz.momentary_max(laptop(y)[:, None] * g))
        dry, _ = sf.read(root / "dry" / f"dress-concrete-dry-{k:02d}.flac", dtype="float64")
        hits = fs.impacts(dry)
        sp = laptop(fs.wet_parts(dry, hits, pool["seed"] * 100 + k)["splash"]) * g
        w = slice(hits[0], hits[0] + int(0.3 * SR))
        splash_band.append(db(band_energy(sp[w])))
    bed_i = Lz.integrated(amb)
    bed_st = Lz.short_term(amb, SR, hop=0.5)
    # bed band level over 300 ms windows (median), same measure as the splash
    n = int(0.3 * SR)
    bed_band = float(np.median([db(band_energy(amb[i:i + n])) for i in range(0, len(amb) - n, n)]))
    full = Lz.integrated(prev * 10 ** (BUS_GAINS_DB["ambience"] / 20))
    layers = {}
    for spec in bed.LAYERS:
        y, _ = sf.read(BUILD / "masters" / "ambience-v2" / "layers" / f"{spec['name']}.flac", dtype="float64", always_2d=True)
        y = y * 10 ** (BUS_GAINS_DB["ambience"] / 20)
        layers[spec["name"]] = {"lufs_full": round(Lz.integrated(y), 1), "lufs_laptop": round(Lz.integrated(laptop(y)), 1)}
    res = {"bed_lufs_full_range": round(full, 2), "bed_lufs_laptop": round(bed_i, 2),
           "bed_short_term_p10_p90": [round(float(np.percentile(bed_st, 10)), 1), round(float(np.percentile(bed_st, 90)), 1)],
           "step_m_max_median": {v: round(float(np.median(s)), 2) for v, s in steps.items()},
           "step_over_bed_lu": round(float(np.median(steps["dry"])) - bed_i, 2),
           "splash_band_minus_bed_band_db": round(float(np.median(splash_band)) - bed_band, 2),
           "layers": layers, "volumes": {}}
    for name, vdb in VOLUMES_DB.items():
        spl = lambda l: round(l + SPL_OFFSET + vdb, 1)
        res["volumes"][name] = {
            "bed_dba": spl(bed_i), "steps_dba_peak": spl(float(np.median(steps["dry"]))),
            "wet_steps_dba_peak": spl(float(np.median(steps["wet"]))),
            "bed_over_room_db": round(spl(bed_i) - ROOM_DBA, 1),
            "layers_over_room_db": {k: round(spl(v["lufs_laptop"]) - ROOM_DBA, 1) for k, v in layers.items()},
        }
    return res


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    sp = splash_check()
    mx = mix_check()
    rep = {"model": {"highpass": "Butterworth 4th order 200 Hz", "peak": "+2 dB 2.5 kHz Q 1",
                     "lowpass": "Butterworth 2nd order 14 kHz", "volumes_db": VOLUMES_DB,
                     "spl_offset": SPL_OFFSET, "room_dba": ROOM_DBA, "bus_gains_db": BUS_GAINS_DB,
                     "note": "generic small-laptop model, not a measurement of the MacBook Air"},
           "splash": sp, "mix": mx}
    (OUT / "report.json").write_text(json.dumps(rep, indent=2))
    md = ["| splash metric (median of 8 takes, through the laptop model) | v1 (round 1) | v2 |", "|---|---|---|"]
    for m in sp["median"]["v1"]:
        md.append(f"| {m} | {sp['median']['v1'][m]} | {sp['median']['v2'][m]} |")
    md += ["", f"bed (preview at bus {BUS_GAINS_DB['ambience']} dB): {mx['bed_lufs_full_range']} LUFS full range, "
           f"{mx['bed_lufs_laptop']} LUFS through the model; steps (bus {BUS_GAINS_DB['foley']:+} dB) M max dry "
           f"{mx['step_m_max_median']['dry']} / wet {mx['step_m_max_median']['wet']}; step over bed {mx['step_over_bed_lu']} LU; "
           f"splash over bed in 1.5-6 kHz {mx['splash_band_minus_bed_band_db']} dB", "",
           "| volume | bed dBA | dry step peak dBA | wet step peak dBA | bed over 30 dBA room | layers over room (dB) |",
           "|---|---|---|---|---|---|"]
    for v, r in mx["volumes"].items():
        md.append(f"| {v} | {r['bed_dba']} | {r['steps_dba_peak']} | {r['wet_steps_dba_peak']} | {r['bed_over_room_db']} | "
                  + ", ".join(f"{k} {d:+.0f}" for k, d in r["layers_over_room_db"].items()) + " |")
    md += ["", "| layer | LUFS full range (bus) | LUFS laptop model | lost to the model (dB) |", "|---|---|---|---|"]
    for k, v in mx["layers"].items():
        md.append(f"| {k} | {v['lufs_full']} | {v['lufs_laptop']} | {round(v['lufs_full'] - v['lufs_laptop'], 1)} |")
    (OUT / "report.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))
    log(f"wrote {OUT / 'report.json'}")


if __name__ == "__main__":
    main()
