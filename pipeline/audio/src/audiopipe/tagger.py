"""Human-presence check with an AudioSet tagger (NOTES.md §12: the soundscape is human-free).

    uv run python -I -m audiopipe.tagger                 # every audio source in the manifest
    uv run python -I -m audiopipe.tagger --built         # every master FLAC recorded in provenance/audio.jsonl
    uv run python -I -m audiopipe.tagger FILE ...

Why a tagger as well as the VAD: Silero VAD (audiopipe.vad) catches foreground speech, but it
scores the distant crowd in the rejected spike-7 bed (freesound:679335) at p99 0.05, no higher
than a close cricket. The listening gate heard people there, so the gate needs classes for
crowds, chatter, footsteps and traffic too.

Model: PANNs Cnn14_16k (Kong et al. 2020; code MIT, weights CC BY 4.0, Zenodo 3987831),
exported to ONNX by tools/export_panns_onnx.py; weights stay in private/models/panns-cnn14-16k/.
16 kHz mono, 2 s windows, 1 s hop. A window counts as human presence when any listed class
reaches its own threshold. Classes come in four groups (reported separately):

  voices    speech, conversation, crowd, chatter, hubbub/babble, laughter, shouting, singing, ...
  people    footsteps, running, shuffling, clapping, cough, sneeze, whistling, keys, doors, ...
  traffic   cars, motorcycles, buses, trains, aircraft, sirens, horns
  music     music (recorded music is human; the world's music is synthesised, NOTES §12)

Thresholds (calibrated 2026-10-12 on the rejected spike-7 street beds as positives and the
round-2 machinery/rain/insect sources as negatives, round-2 report):
  * specific human classes (crowd, chatter, conversation, car, motorcycle, ...): low thresholds;
    negatives score <= 0.03 on them, positives 0.5-0.9.
  * generic classes that also fire on machinery, rain or insects get high thresholds:
    'Speech' 0.30 (a close cricket scores 0.22), 'Run' 0.60 (rain on concrete 0.45),
    'Vehicle'/'Train'/'Aircraft'/'Siren' 0.55 (AC units and vending machines 0.33-0.47,
    a transformer's pure tone reads as 'Siren' 0.47; real traffic scores 0.73-0.86).
"""

from __future__ import annotations

import argparse
import csv
import json
from functools import lru_cache
from pathlib import Path

import numpy as np

from . import provenance as prov
from .common import BUILD, DATA_ROOT, _checkout_root, log
from .vad import SR, built_flacs, decode16k, to16k

MODEL_DIR = _checkout_root() / "private" / "models" / "panns-cnn14-16k"
MODEL = MODEL_DIR / "cnn14_16k.onnx"
LABELS = MODEL_DIR / "class_labels_indices.csv"
WIN_S, HOP_S = 2.0, 1.0
OUT = BUILD / "analysis" / "tagger"

_SPECIFIC_VOICE = 0.15
GROUPS: dict[str, dict[str, float]] = {
    "voices": {"Speech": 0.30, "Speech synthesizer": 0.30, "Humming": 0.50,
               **{c: _SPECIFIC_VOICE for c in (
                   "Male speech, man speaking", "Female speech, woman speaking", "Child speech, kid speaking",
                   "Conversation", "Narration, monologue", "Babbling", "Shout", "Bellow", "Whoop", "Yell",
                   "Children shouting", "Screaming", "Whispering", "Laughter", "Baby laughter", "Giggle", "Snicker",
                   "Belly laugh", "Chuckle, chortle", "Crying, sobbing", "Baby cry, infant cry", "Singing", "Choir",
                   "Chant", "Rapping", "Chatter", "Crowd", "Hubbub, speech noise, speech babble", "Children playing",
                   "Cheering", "Applause")}},
    "people": {"Run": 0.60,
               **{c: 0.35 for c in (
                   "Walk, footsteps", "Shuffle", "Clapping", "Cough", "Sneeze", "Sniff", "Whistling",
                   "Burping, eructation", "Hiccup", "Finger snapping", "Hands", "Typing", "Door", "Knock",
                   "Keys jangling", "Coin (dropping)", "Zipper (clothing)")}},
    "traffic": {**{c: 0.55 for c in ("Vehicle", "Train", "Rail transport", "Aircraft", "Jet engine", "Siren")},
                **{c: 0.30 for c in (
                    "Motor vehicle (road)", "Car", "Car passing by", "Traffic noise, roadway noise",
                    "Vehicle horn, car horn, honking", "Accelerating, revving, vroom", "Motorcycle", "Bus", "Truck",
                    "Emergency vehicle", "Police car (siren)", "Ambulance (siren)", "Fire engine, fire truck (siren)",
                    "Bicycle", "Skateboard", "Subway, metro, underground", "Fixed-wing aircraft, airplane",
                    "Helicopter", "Race car, auto racing", "Tire squeal", "Skidding", "Reversing beeps")}},
    "music": {"Music": 0.25, "Musical instrument": 0.25, "Pop music": 0.20, "Rock music": 0.20, "Electronic music": 0.20},
}


@lru_cache(maxsize=1)
def _session():
    import onnxruntime as ort
    if not MODEL.exists():
        raise SystemExit(f"PANNs ONNX model missing: {MODEL} (run tools/export_panns_onnx.py)")
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 4
    opts.inter_op_num_threads = 1
    return ort.InferenceSession(str(MODEL), sess_options=opts, providers=["CPUExecutionProvider"])


@lru_cache(maxsize=1)
def labels() -> list[str]:
    with open(LABELS, newline="") as f:
        return [r["display_name"] for r in csv.DictReader(f)]


@lru_cache(maxsize=1)
def group_index() -> dict[str, np.ndarray]:
    lab = labels()
    idx = {}
    for g, names in GROUPS.items():
        missing = [n for n in names if n not in lab]
        if missing:
            raise SystemExit(f"tagger: unknown AudioSet labels {missing}")
        idx[g] = np.array([lab.index(n) for n in names])
    return idx


@lru_cache(maxsize=1)
def group_thresholds() -> dict[str, np.ndarray]:
    return {g: np.array(list(c.values())) for g, c in GROUPS.items()}


def scores(x16: np.ndarray, batch: int = 16) -> np.ndarray:
    """(windows, 527) clipwise scores for 2 s windows at a 1 s hop (the last window is zero-padded)."""
    w, h = int(WIN_S * SR), int(HOP_S * SR)
    if len(x16) < w:
        x16 = np.pad(x16, (0, w - len(x16)))
    n = 1 + int(np.ceil((len(x16) - w) / h))
    x16 = np.pad(x16, (0, (n - 1) * h + w - len(x16)))
    frames = np.stack([x16[i * h:i * h + w] for i in range(n)]).astype(np.float32)
    out = [_session().run(None, {"waveform": frames[i:i + batch]})[0] for i in range(0, n, batch)]
    return np.concatenate(out)


def report(s: np.ndarray, top: int = 6) -> dict:
    lab = labels()
    gi = group_index()
    th = group_thresholds()
    per = {g: s[:, ix].max(axis=1) for g, ix in gi.items()}
    hits = {g: (s[:, ix] >= th[g]).any(axis=1) for g, ix in gi.items()}
    any_hit = np.any(np.stack(list(hits.values())), axis=0)
    groups = {}
    for g, v in per.items():
        k = int(np.argmax(v))
        cls = gi[g][int(np.argmax(s[k, gi[g]]))]
        ratio = (s[:, gi[g]] / th[g]).max(axis=0)          # per class: max score / its threshold
        worst = int(np.argmax(ratio))
        groups[g] = {"max": round(float(v.max()), 3), "p95": round(float(np.percentile(v, 95)), 3),
                     "windows_over": int(hits[g].sum()), "top_class": lab[cls], "at_s": k * HOP_S,
                     "closest_to_threshold": [lab[gi[g][worst]], round(float(ratio[worst]), 2)]}
    mean = s.mean(axis=0)
    return {
        "windows": int(len(s)), "groups": groups,
        "human_windows": int(any_hit.sum()), "human_fraction": round(float(any_hit.mean()), 4),
        "human_spans_s": spans(any_hit),
        "contains_humans": bool(any_hit.any()),
        "top_classes": [(lab[i], round(float(mean[i]), 3)) for i in np.argsort(mean)[::-1][:top]],
        "_hits": any_hit,
    }


def spans(hit: np.ndarray) -> list[tuple[float, float]]:
    d = np.diff(np.concatenate(([0], hit.astype(np.int8), [0])))
    return [(float(a * HOP_S), float(b * HOP_S - HOP_S + WIN_S)) for a, b in zip(np.where(d == 1)[0], np.where(d == -1)[0])]


def check_array(x: np.ndarray, sr: int) -> dict:
    return report(scores(to16k(x, sr)))


def check_file(path: Path) -> dict:
    return report(scores(decode16k(path)))


def human_free_mask(n: int, sr: int, rep: dict, pad_s: float = 0.5) -> np.ndarray:
    m = np.ones(n, dtype=bool)
    for a, b in rep["human_spans_s"]:
        m[max(0, int((a - pad_s) * sr)):min(n, int((b + pad_s) * sr))] = False
    return m


def public(rep: dict) -> dict:
    return {k: v for k, v in rep.items() if not k.startswith("_")}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--built", action="store_true")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if a.files:
        targets = [(f, Path(f)) for f in a.files]
    elif a.built:
        targets = [(str(f.relative_to(BUILD)), f) for f in built_flacs()]
    else:
        targets = [(rid, DATA_ROOT / r["path"]) for rid, r in prov.load().items()
                   if r["kind"] == "source" and r["domain"] == "audio" and "path" in r]
    rows = []
    for name, path in targets:
        rep = public(check_file(path))
        rows.append({"id": name, **rep})
        g = rep["groups"]
        log(f"{name}: human windows {rep['human_windows']}/{rep['windows']} | " +
            " ".join(f"{k} {v['max']:.2f} ({v['top_class']})" for k, v in g.items()))
    tag = "built" if a.built else ("adhoc" if a.files else "sources")
    (OUT / f"{tag}.json").write_text(json.dumps(rows, indent=2))
    print("Per group: the class closest to its threshold, as score/threshold (>= 1.00 = human presence).")
    print("| file | windows | human windows | voices | people | traffic | music | top classes (mean) |")
    print("|---|---|---|---|---|---|---|---|")
    for r in rows:
        g = r["groups"]
        print(f"| {r['id']} | {r['windows']} | {r['human_windows']} | " +
              " | ".join(f"{g[k]['closest_to_threshold'][1]:.2f} {g[k]['closest_to_threshold'][0]}"
                         for k in ("voices", "people", "traffic", "music")) +
              f" | {', '.join(f'{c} {s}' for c, s in r['top_classes'][:3])} |")


if __name__ == "__main__":
    main()
