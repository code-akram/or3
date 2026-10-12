"""Voice-activity check (NOTES.md §12: the soundscape is human-free).

    uv run python -I -m audiopipe.vad                 # every audio source in the manifest
    uv run python -I -m audiopipe.vad --built         # every master FLAC recorded in provenance/audio.jsonl
    uv run python -I -m audiopipe.vad FILE ...        # ad hoc

Model: Silero VAD v6.2.3 (MIT), ONNX, CPU via onnxruntime. The weights are not committed: they
live in the main checkout's private/models/silero-vad-v6.2.3/ (fetch command in the round-2
report). Input is resampled to 16 kHz mono (L+R)/2; the model scores 512-sample frames (32 ms)
with a 64-sample context carried over from the previous frame, as the reference wrapper does.

Per file the report gives the fraction of frames with speech probability >= 0.5, the longest
run of such frames, the maximum probability and the speech segments (runs >= MIN_RUN_S, merged
across gaps < MERGE_GAP_S). `speech_free_mask` marks samples that are safe to use: everything
except those segments plus PAD_S on each side.

Gate: a file "contains speech" when any segment exists (a run of >= MIN_RUN_S at p >= 0.5).
Positive control: freesound:679335 (takecha, Shinjuku street with crowds, the rejected spike-7 bed).
"""

from __future__ import annotations

import argparse
import json
import subprocess
from functools import lru_cache
from pathlib import Path

import numpy as np

from . import provenance as prov
from .common import BUILD, DATA_ROOT, FFMPEG, THREADS, _checkout_root, log

SR = 16000
FRAME = 512
CONTEXT = 64
THRESH = 0.5
MIN_RUN_S = 0.25      # shortest run that counts as speech (about one syllable)
MERGE_GAP_S = 0.3
PAD_S = 0.5           # margin cut around a segment when choosing speech-free windows
MODEL = _checkout_root() / "private" / "models" / "silero-vad-v6.2.3" / "silero_vad.onnx"
MODEL_SHA256 = "1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3"
OUT = BUILD / "analysis" / "vad"


@lru_cache(maxsize=1)
def _session():
    import onnxruntime as ort
    if not MODEL.exists():
        raise SystemExit(f"Silero VAD model missing: {MODEL} (see the round-2 report for the fetch command)")
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 1
    opts.inter_op_num_threads = 1
    return ort.InferenceSession(str(MODEL), sess_options=opts, providers=["CPUExecutionProvider"])


def decode16k(path: Path) -> np.ndarray:
    """Decode to 16 kHz, then average the channels (L+R)/2 in numpy (any channel count)."""
    info = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=channels",
                           "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True).stdout
    ch = int(info.strip().split(",")[0])
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-threads", THREADS, "-i", str(path),
           "-af", f"aresample={SR}:resampler=soxr:precision=28", "-f", "f32le", "-acodec", "pcm_f32le", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype="<f4").reshape(-1, ch).mean(axis=1).astype(np.float32)


def to16k(x: np.ndarray, sr: int) -> np.ndarray:
    """In-memory resample (frames, ch) or (n,) at sr to 16 kHz mono."""
    from scipy import signal
    m = x.mean(axis=1) if x.ndim == 2 else x
    g = np.gcd(int(sr), SR)
    return signal.resample_poly(m.astype(np.float64), SR // g, int(sr) // g).astype(np.float32)


def probs(x16: np.ndarray) -> np.ndarray:
    """Speech probability per 32 ms frame of 16 kHz mono audio."""
    s = _session()
    state = np.zeros((2, 1, 128), dtype=np.float32)
    ctx = np.zeros((1, CONTEXT), dtype=np.float32)
    sr = np.array(SR, dtype=np.int64)
    n = len(x16) // FRAME
    out = np.empty(n, dtype=np.float32)
    for i in range(n):
        chunk = x16[i * FRAME:(i + 1) * FRAME][None, :].astype(np.float32)
        inp = np.concatenate([ctx, chunk], axis=1)
        p, state = s.run(None, {"input": inp, "state": state, "sr": sr})
        out[i] = p[0, 0]
        ctx = inp[:, -CONTEXT:]
    return out


def segments(p: np.ndarray) -> list[tuple[float, float, float]]:
    """(start_s, end_s, max_p) runs of p >= THRESH lasting >= MIN_RUN_S, merged across short gaps."""
    fr = FRAME / SR
    on = p >= THRESH
    d = np.diff(np.concatenate(([0], on.astype(np.int8), [0])))
    starts, ends = np.where(d == 1)[0], np.where(d == -1)[0]
    runs = [[a, b] for a, b in zip(starts, ends)]
    merged: list[list[int]] = []
    for a, b in runs:
        if merged and (a - merged[-1][1]) * fr < MERGE_GAP_S:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    return [(round(a * fr, 3), round(b * fr, 3), round(float(p[a:b].max()), 3))
            for a, b in merged if (b - a) * fr >= MIN_RUN_S]


def report(p: np.ndarray) -> dict:
    fr = FRAME / SR
    on = p >= THRESH
    longest = 0
    cur = 0
    for v in on:
        cur = cur + 1 if v else 0
        longest = max(longest, cur)
    segs = segments(p)
    return {
        "frames": int(len(p)), "seconds": round(len(p) * fr, 2),
        "speech_frame_fraction": round(float(on.mean()) if len(p) else 0.0, 5),
        "longest_run_s": round(longest * fr, 3),
        "max_prob": round(float(p.max()) if len(p) else 0.0, 3),
        "p99_prob": round(float(np.percentile(p, 99)) if len(p) else 0.0, 3),
        "speech_segments": segs,
        "speech_seconds": round(sum(b - a for a, b, _ in segs), 2),
        "contains_speech": bool(segs),
    }


def check_array(x: np.ndarray, sr: int) -> dict:
    return report(probs(to16k(x, sr)))


def check_file(path: Path) -> dict:
    return report(probs(decode16k(path)))


def built_flacs() -> list[Path]:
    """Every master FLAC the manifest records (stale files left in data/build are skipped)."""
    return sorted(DATA_ROOT / r["path"] for r in prov.load().values()
                  if r["kind"] == "derived" and r["domain"] == "audio" and r["path"].startswith("build/audio/masters/")
                  and r["path"].endswith(".flac"))


def speech_free_mask(n: int, sr: int, rep: dict, pad_s: float = PAD_S) -> np.ndarray:
    """Boolean mask over n samples at sr: False inside each speech segment +- pad_s."""
    m = np.ones(n, dtype=bool)
    for a, b, _ in rep["speech_segments"]:
        m[max(0, int((a - pad_s) * sr)):min(n, int((b + pad_s) * sr))] = False
    return m


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--built", action="store_true", help="every master FLAC in the manifest")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    if a.files:
        targets = [(f, Path(f)) for f in a.files]
    elif a.built:
        targets = [(str(f.relative_to(BUILD)), f) for f in built_flacs()]
    else:
        targets = [(rid, DATA_ROOT / r["path"]) for rid, r in prov.load().items()
                   if r["kind"] == "source" and r["domain"] == "audio" and "path" in r]
    for name, path in targets:
        rep = check_file(path)
        rows.append({"id": name, **rep})
        log(f"{name}: speech {rep['speech_seconds']} s in {len(rep['speech_segments'])} segment(s), "
            f"frames {rep['speech_frame_fraction']*100:.2f}%, max p {rep['max_prob']}")
    tag = "built" if a.built else ("adhoc" if a.files else "sources")
    (OUT / f"{tag}.json").write_text(json.dumps(rows, indent=2))
    print("| file | seconds | speech frames | longest run | max p | speech s | segments | verdict |")
    print("|---|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['id']} | {r['seconds']} | {r['speech_frame_fraction']*100:.2f}% | {r['longest_run_s']} s | {r['max_prob']} | "
              f"{r['speech_seconds']} | {len(r['speech_segments'])} | {'**speech**' if r['contains_speech'] else 'clean'} |")


if __name__ == "__main__":
    main()
