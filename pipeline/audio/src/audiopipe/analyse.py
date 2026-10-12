"""Step 2: measure every fetched file (Claude can't listen) and apply the quality floor.

    uv run python -I -m audiopipe.analyse            # all source records in provenance/audio.jsonl
    uv run python -I -m audiopipe.analyse --no-gate  # measure only, don't touch status

Per file it writes data/build/audio/analysis/<slug>.{json,png} and prints a table:
  * EBU R128 integrated loudness, LRA, true peak (ffmpeg ebur128)
  * astats: DC offset, peak, flat factor / peak count (clipping), effective bit depth
  * own numpy measures: clipped-sample runs, noise floor (10th pct of 50 ms RMS),
    digital-silence fraction, SNR proxy (p95 - p10 short-term RMS)
  * spectral cutoff: content edge (highest frequency 10 dB above the spectrum's own floor)
    and the steepest drop above 8 kHz in a 1 kHz window. A >=25 dB/kHz wall below
    20.5 kHz = lossy-codec origin (rejected even inside a WAV); a wall at 20.5-22 kHz
    below Nyquist = resampled from 44.1/48 kHz (accepted, noted)
  * showspectrumpic spectrogram (linear frequency, log magnitude) for visual inspection
  * human presence (NOTES §12, human-free soundscape) for ambience roles (ambience, bed-*, event-*,
    rain): Silero VAD speech segments (audiopipe.vad) and AudioSet tagger windows (audiopipe.tagger).
    A source is rejected when more than 2 % of its 2 s windows show human presence or the VAD finds
    more than 1 s of speech; below that it is accepted and the bed builder cuts around the spans.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

import numpy as np
from scipy import signal

from . import provenance as prov
from . import tagger, vad
from .common import BUILD, DATA_ROOT, FFMPEG, THREADS, ffmpeg, ffmpeg_stderr, log

OUT = BUILD / "analysis"

# Quality floor (see report for the reasoning). Applied per role.
LOSSY_WALL_HZ = 20500  # MP3/AAC encoders low-pass at 16-20 kHz; ADC/resampler walls sit at 20.5-22 kHz

FLOOR = {
    "min_bandwidth_hz": 18000,     # effective content must reach 18 kHz
    "max_clipped_fraction": 1e-5,  # samples in runs of >=3 at full scale
    "lossy_codecs": {"mp3", "aac", "vorbis", "opus"},
    "min_snr_db": {"footsteps": 30.0, "ambience": 0.0, "rain": 0.0},
    "max_human_window_fraction": 0.02,
    "max_speech_s": 1.0,
}
HUMAN_FREE_ROLES = ("ambience", "bed-", "event-", "rain")


def human_free_role(role: str) -> bool:
    return role.startswith(HUMAN_FREE_ROLES)


def human_check(x: np.ndarray, sr: int) -> dict:
    v = vad.check_array(x, sr)
    t = tagger.public(tagger.check_array(x, sr))
    return {"vad": v, "tagger": t}


def slug_of(rid: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", rid).strip("-")[:60]


def decode(path: Path, rate: int | None = None) -> tuple[np.ndarray, int]:
    """Decode any input to float32 (frames, channels) through ffmpeg."""
    info = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=sample_rate,channels",
         "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout)["streams"][0]
    sr = rate or int(info["sample_rate"])
    ch = int(info["channels"])
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-threads", THREADS, "-i", str(path)]
    if rate:
        cmd += ["-af", f"aresample={rate}:resampler=soxr:precision=28"]
    cmd += ["-f", "f32le", "-acodec", "pcm_f32le", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    x = np.frombuffer(raw, dtype="<f4").reshape(-1, ch)
    return x, sr


def ffmpeg_stats(path: Path) -> dict:
    err = ffmpeg_stderr("-i", str(path), "-af",
                        "astats=measure_perchannel=none:measure_overall=all,ebur128=peak=true:framelog=quiet",
                        "-f", "null", "-")
    def grab(pat: str, cast=float):
        m = re.findall(pat, err)
        return cast(m[-1]) if m else None
    return {
        "lufs_i": grab(r"I:\s+(-?[\d.]+|-inf) LUFS"),
        "lra_lu": grab(r"LRA:\s+([\d.]+) LU"),
        "true_peak_dbfs": grab(r"Peak:\s+(-?[\d.]+|-inf) dBFS"),
        "dc_offset": grab(r"DC offset: (-?[\d.]+)"),
        "peak_db": grab(r"Peak level dB: (-?[\d.]+|-inf)"),
        "rms_db": grab(r"RMS level dB: (-?[\d.]+|-inf)"),
        "flat_factor": grab(r"Flat factor: ([\d.]+)"),
        "peak_count": grab(r"\] Peak count: ([\d.]+)"),
        "astats_noise_floor_db": grab(r"Noise floor dB: (-?[\d.]+|-inf)"),
        "effective_bits": grab(r"Bit depth: ([\d/]+)", str),
    }


def numpy_stats(x: np.ndarray, sr: int) -> dict:
    mono = x.mean(axis=1)
    a = np.abs(x)
    fs = a.max()
    # clipping: runs of >= 3 consecutive samples within 0.01 dB of the file's absolute peak, near full scale
    clipped = 0
    if fs > 0.89:  # only meaningful near 0 dBFS (-1 dB)
        hit = a >= fs * 0.9988
        for c in range(x.shape[1]):
            h = hit[:, c].astype(np.int8)
            d = np.diff(np.concatenate(([0], h, [0])))
            starts, ends = np.where(d == 1)[0], np.where(d == -1)[0]
            runs = ends - starts
            clipped += int(runs[runs >= 3].sum())
    win = int(0.05 * sr)
    n = len(mono) // win
    frames = mono[: n * win].reshape(n, win)
    rms = np.sqrt((frames ** 2).mean(axis=1))
    silent = rms < 1e-7
    rms_db = 20 * np.log10(rms[~silent] + 1e-12)
    p10 = float(np.percentile(rms_db, 10)) if len(rms_db) else float("-inf")
    p95 = float(np.percentile(rms_db, 95)) if len(rms_db) else float("-inf")
    return {
        "clipped_samples": clipped,
        "clipped_fraction": clipped / x.size,
        "noise_floor_dbfs": round(p10, 1),
        "loud_p95_dbfs": round(p95, 1),
        "snr_proxy_db": round(p95 - p10, 1),
        "digital_silence_fraction": round(float(silent.mean()), 4),
        "dc_offset_np": float(x.mean()),
    }


def spectral(x: np.ndarray, sr: int) -> dict:
    mono = x.mean(axis=1).astype(np.float64)
    f, p = signal.welch(mono, sr, nperseg=8192, noverlap=4096, window="hann", average="median")
    pdb = 10 * np.log10(p + 1e-30)
    # smooth over ~200 Hz
    k = max(1, int(200 / (f[1] - f[0])))
    sm = np.convolve(pdb, np.ones(k) / k, mode="same")
    ref = float(np.median(sm[(f >= 1000) & (f <= 4000)]))
    floor = float(np.min(sm[f > 1000]))
    # content edge: highest frequency still 10 dB above the spectrum's own floor
    above = np.where(sm > floor + 10)[0]
    cutoff = float(f[above[-1]]) if len(above) else 0.0
    # steepest 1 kHz drop above 8 kHz
    step = max(1, int(1000 / (f[1] - f[0])))
    best_drop, best_f = 0.0, 0.0
    for i in range(np.searchsorted(f, 8000), len(sm) - step):
        d = sm[i] - sm[i + step]
        if d > best_drop:
            best_drop, best_f = float(d), float(f[i])
    nyq = sr / 2
    brick = best_drop >= 25.0 and best_f < 0.9 * nyq
    band_hi = float(np.median(sm[(f >= 15000) & (f <= 18000)]) - ref) if nyq > 18000 else None
    if brick and best_f < LOSSY_WALL_HZ:
        verdict = f"brick wall at ~{best_f/1000:.1f} kHz: lossy-codec low-pass (MP3/AAC origin)"
    elif brick:
        verdict = f"brick wall at ~{best_f/1000:.1f} kHz: resampled from a lower rate (not lossy)"
    elif cutoff < 0.8 * nyq:
        verdict = f"band-limited to ~{cutoff/1000:.1f} kHz (gentle roll-off)"
    else:
        verdict = "full-band"
    return {
        "ref_1_4k_db": round(ref, 1),
        "content_edge_hz": round(cutoff),
        "steepest_drop_db_per_khz": round(best_drop, 1),
        "steepest_drop_at_hz": round(best_f),
        "band_15_18k_rel_db": None if band_hi is None else round(band_hi, 1),
        "nyquist_hz": nyq,
        "brick_wall": bool(brick),
        "verdict": verdict,
        "effective_bandwidth_hz": round(min(cutoff, best_f) if brick else cutoff),
    }


def spectrogram(path: Path, png: Path, title: str) -> None:
    ffmpeg("-i", str(path), "-lavfi",
           "showspectrumpic=s=1200x500:mode=combined:color=intensity:scale=log:fscale=lin:legend=1:drange=120",
           "-frames:v", "1", str(png))


def gate(role: str, fmt: dict, ff: dict, npst: dict, sp: dict, human: dict | None = None) -> tuple[str, str]:
    reasons = []
    if human:
        t, v = human["tagger"], human["vad"]
        if t["human_fraction"] > FLOOR["max_human_window_fraction"] or v["speech_seconds"] > FLOOR["max_speech_s"]:
            worst = max(t["groups"].items(), key=lambda kv: kv[1]["closest_to_threshold"][1])
            reasons.append(f"human presence: {t['human_windows']}/{t['windows']} tagger windows "
                           f"(strongest {worst[0]}: {worst[1]['closest_to_threshold'][0]}), VAD speech {v['speech_seconds']} s "
                           "(NOTES §12 human-free rule)")
    if fmt.get("codec") in FLOOR["lossy_codecs"]:
        reasons.append(f"lossy original ({fmt['codec']})")
    if sp["brick_wall"] and sp["steepest_drop_at_hz"] < LOSSY_WALL_HZ and fmt.get("codec") not in FLOOR["lossy_codecs"]:
        reasons.append(f"lossy origin hidden in a {fmt['codec']} {fmt['sample_rate']} Hz container ({sp['verdict']})")
    if sp["effective_bandwidth_hz"] < FLOOR["min_bandwidth_hz"]:
        reasons.append(f"effective bandwidth {sp['effective_bandwidth_hz']/1000:.1f} kHz < 18 kHz ({sp['verdict']})")
    if npst["clipped_fraction"] > FLOOR["max_clipped_fraction"]:
        reasons.append(f"clipping ({npst['clipped_samples']} samples in flat runs)")
    if npst["snr_proxy_db"] < FLOOR["min_snr_db"].get(role, 0):
        reasons.append(f"SNR proxy {npst['snr_proxy_db']} dB < {FLOOR['min_snr_db'][role]} dB")
    if reasons:
        return "rejected", "; ".join(reasons)
    notes = []
    if sp["brick_wall"] or sp["content_edge_hz"] < 0.8 * sp["nyquist_hz"]:
        notes.append(f"nominal {fmt['sample_rate']} Hz but content stops near {sp['effective_bandwidth_hz']/1000:.1f} kHz; fine for a 48 kHz master")
    if abs(ff.get("dc_offset") or 0) > 0.001:
        notes.append(f"DC offset {ff['dc_offset']:.4f} (removed by high-pass)")
    if npst["digital_silence_fraction"] > 0.01:
        notes.append(f"{npst['digital_silence_fraction']*100:.1f}% digital silence (edited/gated source)")
    if human:
        n_t, n_v = len(human["tagger"]["human_spans_s"]), len(human["vad"]["speech_segments"])
        notes.append(f"human-free check passed (tagger {human['tagger']['human_windows']}/{human['tagger']['windows']} windows, "
                     f"VAD {human['vad']['speech_seconds']} s)" + (f"; {n_t + n_v} span(s) cut by the bed builder" if n_t + n_v else ""))
    return "accepted", "passes floor" + (": " + "; ".join(notes) if notes else "")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-gate", action="store_true")
    ap.add_argument("--only")
    a = ap.parse_args()
    import tomllib
    cfg = tomllib.loads((Path(__file__).resolve().parents[2] / "sources.toml").read_text())
    roles = {f"freesound:{e['id']}": e["role"] for e in cfg.get("freesound", [])}
    roles |= {f"archive:{e['identifier']}/{e['file']}": e["role"] for e in cfg.get("archive", [])}
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for rid, rec in prov.load().items():
        if rec["kind"] != "source" or rec["domain"] != "audio" or "path" not in rec or (a.only and a.only not in rid):
            continue
        path = DATA_ROOT / rec["path"]
        slug = slug_of(rid)
        log(f"analysing {rid}")
        ff = ffmpeg_stats(path)
        x, sr = decode(path)
        npst = numpy_stats(x, sr)
        sp = spectral(x, sr)
        png = OUT / f"{slug}.png"
        spectrogram(path, png, rec["title"])
        role = roles.get(rid, "ambience")
        human = human_check(x, sr) if human_free_role(role) else None
        status, reason = gate(role, rec["original_format"], ff, npst, sp, human)
        result = {"id": rid, "role": role, "format": rec["original_format"], "ffmpeg": ff,
                  "numpy": npst, "spectral": sp, "status": status, "reason": reason,
                  "spectrogram": str(png.relative_to(BUILD))}
        if human:
            result["human"] = human
        (OUT / f"{slug}.json").write_text(json.dumps(result, indent=2))
        rows.append(result)
        if not a.no_gate:
            prov.update(rid, status=status, status_reason=reason)
    (OUT / "summary.json").write_text(json.dumps(rows, indent=2))
    hdr = "| id | role | fmt | LUFS-I | LRA | TP dBFS | DC | eff. bits | noise floor | SNR proxy | clipped | content edge | steepest drop | verdict | human (tagger windows / VAD s) | gate |"
    print(hdr)
    print("|" + "---|" * (hdr.count("|") - 1))
    for r in rows:
        f, ff, n, s = r["format"], r["ffmpeg"], r["numpy"], r["spectral"]
        print(f"| {r['id']} | {r['role']} | {f['codec']} {f['sample_rate']//1000}k/{f['bit_depth']} | {ff['lufs_i']} | {ff['lra_lu']} | "
              f"{ff['true_peak_dbfs']} | {ff['dc_offset']:.5f} | {ff['effective_bits']} | {n['noise_floor_dbfs']} | {n['snr_proxy_db']} | "
              f"{n['clipped_samples']} | {s['content_edge_hz']/1000:.1f}k | {s['steepest_drop_db_per_khz']} dB @ {s['steepest_drop_at_hz']/1000:.1f}k | "
              f"{s['verdict']} | {hum(r)} | **{r['status']}**: {r['reason']} |")


def hum(r: dict) -> str:
    h = r.get("human")
    if not h:
        return "n/a"
    return f"{h['tagger']['human_windows']}/{h['tagger']['windows']} / {h['vad']['speech_seconds']}"


if __name__ == "__main__":
    main()
