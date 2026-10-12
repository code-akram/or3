"""Step 4a (round 2): human-free night ambience bed: "Shinjuku side street at night, nobody left".

    uv run python -I -m audiopipe.bed

NOTES §12: or3 is the only human on Earth, so the bed has no voices, footsteps or traffic.
Round 1's street loop was rejected at the 2026-10-12 listening gate for exactly that, and
because its 96 s repetition was noticeable. Round 2 is built for the runtime, not as one file:

  * loop layers (machines still running, weather): each its own seamless loop (audiopipe.loop)
    at a different, incommensurate length (34-72 s), so the layered result does not repeat on
    any human timescale. Distance is baked: zero-phase low/high-pass and alley reverb (the spike-6
    IR snapshot, direct path removed), all applied circularly (FFT over exactly one loop period)
    so every layer stays seamless. Mono sources are panned (constant power).
  * slow gain drift per layer (runtime: a new random target every 8-20 s, +-drift_db).
  * one-shot events (wind gusts on wires, crow calls, insect patches, a cricket, distant
    pedestrian-crossing signals), drawn by a Poisson scheduler with a minimum gap, gain/pan
    jitter and no immediate repeat of a take. Parameters live in bed.json; the listening page
    and the game run the same scheduler. Events are picked from the recordings around their
    loudest moments, cut where the level falls away, and faded.
  * crossing signals are synthesised (NOTES §12: no recorded city sounds with people in them):
    Japanese accessible-pedestrian-signal tones, east-west "piyo" answered by "piyo-piyo",
    north-south "kakko" answered by "ka-kakko" (call-and-response from both kerbs), through a
    small-horn band-pass, then made distant. Many Tokyo signals switch their sound off late at
    night, so the scheduler gates them by game clock (active_hours); the preview is set at 21:00.

Every source is re-checked for human presence (Silero VAD + PANNs tagger) on the cleaned file;
loops are built inside the longest human-free stretch and events never overlap a flagged span.
Outputs (pre-master float WAV; audiopipe.master sets one global gain so the 3-minute preview
lands on the ambience target): data/build/audio/masters/ambience-v2/premaster/ and bed.json.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal

from . import loop, spatialise, tagger, vad
from . import loudness as Lz
from .clean import slug_of
from .common import BUILD, file_sha256, log

SR = 48000
OUT = BUILD / "masters" / "ambience-v2"
PRE = OUT / "premaster"
NAME = "shinjuku-side-street-empty"
SEED = 2026
PREVIEW_S = 180.0
PREVIEW_HOUR = 21.0
REF_LUFS = -30.0          # pre-master reference: the wind layer's integrated loudness

# gain_db: layer integrated loudness relative to REF_LUFS. lpf/hpf: zero-phase Butterworth
# magnitude (order 2 / 2). reverb_db: alley reflections energy relative to the dry layer.
LAYERS = [
    {"name": "wind", "id": "freesound:786004", "loop_s": (66, 72), "xfade_s": 6.0, "gain_db": 0.0,
     "hpf": 80, "lpf": None, "reverb_db": None, "pan": 0.0, "drift_db": 2.0, "role": "air moving down the street"},
    # no alley reverb on the rain: diffuse rain through one alley IR reads as rolling stock to the
    # tagger ("Train" 0.62, "Clickety-clack"), and the recording is a courtyard already
    {"name": "rain-light", "id": "freesound:612817", "loop_s": (63, 69), "xfade_s": 6.0, "gain_db": -5.0,
     "hpf": 80, "lpf": 9000, "reverb_db": None, "pan": 0.0, "drift_db": 1.5, "role": "light rain, mid distance"},
    {"name": "rain-drips", "id": "freesound:81731", "loop_s": (57, 62), "xfade_s": 5.0, "gain_db": -7.0,
     "hpf": 100, "lpf": None, "reverb_db": -12.0, "pan": 0.0, "drift_db": 2.0, "role": "drips off gutters and awnings, close"},
    {"name": "ac-alley", "id": "freesound:454261", "loop_s": (50, 56), "xfade_s": 5.0, "gain_db": -8.0,
     "hpf": 50, "lpf": 8000, "reverb_db": -9.0, "pan": -0.45, "drift_db": 1.0, "role": "condenser unit in the alley, dripping"},
    {"name": "vending", "id": "freesound:730438", "loop_s": (45, 50), "xfade_s": 5.0, "gain_db": -10.0,
     "hpf": 50, "lpf": None, "reverb_db": -10.0, "pan": 0.55, "drift_db": 0.5, "role": "vending machine compressor hum"},
    {"name": "ac-far", "id": "freesound:192240", "loop_s": (34, 38), "xfade_s": 4.0, "gain_db": -13.0,
     "hpf": 80, "lpf": 3500, "reverb_db": -3.0, "pan": 0.8, "drift_db": 1.5, "role": "rooftop condenser, far"},
    {"name": "neon", "id": "freesound:453489", "loop_s": (58, 64), "xfade_s": 5.0, "gain_db": -14.0,
     "hpf": 100, "lpf": None, "reverb_db": -12.0, "pan": 0.25, "drift_db": 0.5, "role": "neon sign ballast buzz"},
    {"name": "transformer", "id": "freesound:641208", "loop_s": (41, 45), "xfade_s": 5.0, "gain_db": -15.0,
     "hpf": 60, "lpf": 6000, "reverb_db": -6.0, "pan": -0.75, "drift_db": 0.5, "role": "pole transformer, 50 Hz family"},
]

# Event pools. peak_lu: event momentary max relative to REF_LUFS. extent: how a take is cut
# around a loudness peak (pre/post search limits, the drop that ends it, fades). distance:
# hpf/lpf/reverb as for layers. tag: an AudioSet class that must score >= TAG_MIN somewhere in
# the take (the loudest moment of a crow recording is not always a crow). schedule: mean seconds
# between events, min gap, jitter.
EVENTS = [
    {"name": "gust", "ids": ["freesound:664257"], "takes": 5, "peak_lu": 3.0, "smooth_s": 1.0,
     "extent": {"min_s": 6, "max_s": 14, "drop_db": 8, "fade_in_s": 2.5, "fade_out_s": 3.0}, "min_sep_s": 20,
     "hpf": 80, "lpf": None, "reverb_db": None,
     "schedule": {"mean_interval_s": 40, "min_gap_s": 15, "gain_jitter_db": 3, "pan": [-0.8, 0.8]}},
    {"name": "crow", "ids": ["freesound:386768", "freesound:476139"], "takes": 6, "peak_lu": 5.0, "smooth_s": 0.05,
     "extent": {"min_s": 0.6, "max_s": 4.5, "drop_db": 18, "fade_in_s": 0.02, "fade_out_s": 0.3}, "min_sep_s": 5,
     "tag": "Crow", "hpf": 250, "lpf": 7000, "reverb_db": -4.0,
     "schedule": {"mean_interval_s": 70, "min_gap_s": 30, "gain_jitter_db": 4, "pan": [-0.9, 0.9]}},
    {"name": "insects", "ids": ["freesound:365257"], "takes": 4, "peak_lu": -2.0, "smooth_s": 1.0,
     "extent": {"min_s": 6, "max_s": 12, "drop_db": 6, "fade_in_s": 2.0, "fade_out_s": 2.5}, "min_sep_s": 20,
     "tag": "Insect", "tag_min": 0.3, "hpf": 300, "lpf": 9000, "reverb_db": -8.0,
     "schedule": {"mean_interval_s": 55, "min_gap_s": 25, "gain_jitter_db": 3, "pan": [-0.7, 0.7]}},
    {"name": "cricket", "ids": ["freesound:568820"], "takes": 4, "peak_lu": -4.0, "smooth_s": 0.5,
     "extent": {"min_s": 4, "max_s": 9, "drop_db": 10, "fade_in_s": 0.8, "fade_out_s": 1.5}, "min_sep_s": 12,
     "tag": "Cricket", "hpf": 400, "lpf": None, "reverb_db": -12.0,
     "schedule": {"mean_interval_s": 45, "min_gap_s": 20, "gain_jitter_db": 3, "pan": [-0.6, 0.6]}},
    {"name": "crossing", "ids": [], "takes": 2, "peak_lu": 0.0, "synth": True,
     "hpf": 300, "lpf": 3500, "reverb_db": 2.0,
     "schedule": {"mean_interval_s": 90, "min_gap_s": 60, "gain_jitter_db": 2, "pan": [-0.5, 0.5],
                  "active_hours": [7, 22]}},
]
TAG_MIN = 0.5
DRIFT = {"retarget_s": [8, 20], "time_constant_s": 6}


# ------------------------------------------------------------------ helpers
def read(path: Path) -> np.ndarray:
    return loop.read(path)


def stereo(x: np.ndarray, pan: float) -> np.ndarray:
    """Mono -> constant-power pan; stereo -> balance (the pan law applied per channel)."""
    th = (pan + 1) * np.pi / 4
    gl, gr = np.cos(th), np.sin(th)
    if x.shape[1] == 1:
        return np.column_stack([x[:, 0] * gl, x[:, 0] * gr])
    return np.column_stack([x[:, 0] * gl * np.sqrt(2), x[:, 1] * gr * np.sqrt(2)])


def butter_mag(f: np.ndarray, hpf: float | None, lpf: float | None, order: int = 2) -> np.ndarray:
    h = np.ones_like(f)
    with np.errstate(divide="ignore"):
        if hpf:
            h /= np.sqrt(1 + (hpf / np.maximum(f, 1e-6)) ** (2 * order))
        if lpf:
            h /= np.sqrt(1 + (f / lpf) ** (2 * order))
    return h


def reflections_ir() -> tuple[np.ndarray, dict]:
    """Spike-6 alley IR snapshot, direct path (first 1 ms) removed, unit energy per channel."""
    snap = spatialise.snapshot_ir()
    if snap is None:
        raise SystemExit("bed: the alley IR is missing (data/build/audio/ir/alley-01.wav); run spike 6's bake")
    tmp = PRE / "alley-reflections.wav"
    info = spatialise.prepare_ir(snap, tmp)
    ir = read(tmp)
    tmp.unlink()
    ir[: int(0.001 * SR)] = 0
    ir /= np.sqrt((ir ** 2).sum(axis=0, keepdims=True))
    return ir, info | {"path": str(snap.relative_to(BUILD.parent.parent)), "sha256": file_sha256(snap),
                       "snapshot_of": str(spatialise.REAL_IR.relative_to(BUILD.parent.parent))}


def place(x: np.ndarray, spec: dict, ir: np.ndarray, circular: bool) -> np.ndarray:
    """Pan, filter and add reflections. circular=True treats x as one period of a loop."""
    y = stereo(x, spec.get("pan", 0.0))
    n = len(y) if circular else len(y) + len(ir)
    Y = np.fft.rfft(y, n, axis=0)
    f = np.fft.rfftfreq(n, 1 / SR)
    Y *= butter_mag(f, spec.get("hpf"), spec.get("lpf"))[:, None]
    if spec.get("reverb_db") is not None:
        h = ir
        if circular and len(h) > n:
            h = h[:n]
        H = np.fft.rfft(h, n, axis=0)
        wet = Y * H
        # reflections energy relative to the dry signal
        e_dry = (np.abs(Y) ** 2).sum()
        e_wet = (np.abs(wet) ** 2).sum()
        Y = Y + wet * np.sqrt(e_dry / max(e_wet, 1e-30)) * 10 ** (spec["reverb_db"] / 20)
    return np.fft.irfft(Y, n, axis=0)


def human_free(x: np.ndarray) -> tuple[np.ndarray, dict]:
    v = vad.check_array(x, SR)
    t = tagger.check_array(x, SR)
    m = vad.speech_free_mask(len(x), SR, v) & tagger.human_free_mask(len(x), SR, t)
    return m, {"vad_speech_s": v["speech_seconds"], "vad_p99": v["p99_prob"], "vad_max": v["max_prob"],
               "tagger_human_windows": t["human_windows"], "tagger_windows": t["windows"],
               "tagger_closest": {g: d["closest_to_threshold"] for g, d in t["groups"].items()},
               "masked_s": round(float((~m).sum() / SR), 2)}


def longest_true(m: np.ndarray) -> tuple[int, int]:
    d = np.diff(np.concatenate(([0], m.astype(np.int8), [0])))
    a, b = np.where(d == 1)[0], np.where(d == -1)[0]
    k = int(np.argmax(b - a))
    return int(a[k]), int(b[k])


def fade(y: np.ndarray, fin: float, fout: float) -> np.ndarray:
    a, b = max(1, int(fin * SR)), max(1, int(fout * SR))
    y = y.copy()
    y[:a] *= (np.sin(np.linspace(0, np.pi / 2, a)) ** 2)[:, None]
    y[-b:] *= (np.cos(np.linspace(0, np.pi / 2, b)) ** 2)[:, None]
    return y


def level_db(x: np.ndarray, smooth_s: float) -> np.ndarray:
    """Smoothed RMS level (dB) per 10 ms."""
    hop = int(0.01 * SR)
    e = (x ** 2).mean(axis=1)
    e = e[: len(e) // hop * hop].reshape(-1, hop).mean(axis=1)
    k = max(1, int(smooth_s / 0.01))
    e = np.convolve(e, np.ones(k) / k, mode="same")
    return 10 * np.log10(e + 1e-20)


def tag_ok(x: np.ndarray, cls: str | None, floor: float = TAG_MIN):
    """Predicate on (a, b): the take contains cls at >= floor (any tagger window inside it)."""
    if not cls:
        return lambda a, b: True
    sc = tagger.scores(vad.to16k(x, SR))[:, tagger.labels().index(cls)]
    w = np.arange(len(sc)) * tagger.HOP_S
    return lambda a, b: bool((sc[(w >= a / SR - 1) & (w + tagger.WIN_S <= b / SR + 1)] >= floor).any())


def pick_takes(x: np.ndarray, mask: np.ndarray, ev: dict, want: int, ok) -> list[tuple[int, int]]:
    """Cut takes around the loudest moments: extend each side until the smoothed level has
    fallen drop_db below the peak (bounded by min/max length), no overlap, no flagged span."""
    ext = ev["extent"]
    lv = level_db(x, ev["smooth_s"])
    order = np.argsort(lv)[::-1]
    taken: list[tuple[int, int]] = []
    hop = int(0.01 * SR)
    for i in order:
        if len(taken) >= want:
            break
        c = int(i) * hop
        if any(a - ev["min_sep_s"] * SR < c < b + ev["min_sep_s"] * SR for a, b in taken):
            continue
        floor = lv[i] - ext["drop_db"]
        lo = hi = int(i)
        lim = int(ext["max_s"] / 0.01)
        while lo > 0 and lv[lo] > floor and (hi - lo) < lim:
            lo -= 1
        while hi < len(lv) - 1 and lv[hi] > floor and (hi - lo) < lim:
            hi += 1
        a, b = lo * hop, hi * hop
        short = int(ext["min_s"] * SR) - (b - a)
        if short > 0:
            a, b = max(0, a - short // 2), min(len(x), b + short - short // 2)
        if b - a < int(ext["min_s"] * SR) or not mask[a:b].all() or not ok(a, b):
            continue
        if any(not (b <= ta or a >= tb) for ta, tb in taken):
            continue
        taken.append((a, b))
    return sorted(taken)


# ------------------------------------------------------------------ crossing signals
def _tone(segs: list[tuple[float, float, float, float]], harm: list[float]) -> np.ndarray:
    """segs: (start_s, dur_s, f_start, f_end); sine + harmonics, 3 ms attack, 15 ms release."""
    end = max(a + b for a, b, _, _ in segs)
    n = int((end + 0.05) * SR)
    y = np.zeros(n)
    for t0, d, f0, f1 in segs:
        m = int(d * SR)
        tt = np.arange(m) / SR
        f = f0 + (f1 - f0) * tt / d
        ph = 2 * np.pi * np.cumsum(f) / SR
        z = sum(g * np.sin((k + 1) * ph) for k, g in enumerate(harm))
        env = np.minimum(1, tt / 0.003) * np.minimum(1, (d - tt) / 0.015)
        i = int(t0 * SR)
        y[i:i + m] += z * env
    return y


def piyo() -> np.ndarray:
    return _tone([(0.0, 0.05, 2200, 3100), (0.07, 0.11, 3000, 2050)], [1.0, 0.25])


def kakko(lead: int = 1) -> np.ndarray:
    segs, t = [], 0.0
    for _ in range(lead):
        segs.append((t, 0.08, 980, 960))
        t += 0.12 if lead > 1 else 0.2
    segs.append((t, 0.3, 800, 780))
    return _tone(segs, [1.0, 0.0, 0.18])


def crossing_burst(kind: str, dur_s: float = 14.0, period_s: float = 1.5) -> np.ndarray:
    """One walk phase: call from the near kerb (left), response from the far kerb (right)."""
    n = int((dur_s + 1) * SR)
    y = np.zeros((n, 2))
    call = piyo() if kind == "piyo" else kakko(1)
    resp = np.concatenate([piyo(), piyo()]) if kind == "piyo" else kakko(2)
    t = 0.0
    while t < dur_s:
        for z, at, pan in ((call, t, -0.35), (resp, t + period_s / 2, 0.35)):
            i = int(at * SR)
            s = stereo(z[:, None], pan) * (1.0 if pan < 0 else 0.7)
            y[i:i + len(s)] += s[: n - i]
        t += period_s
    # small horn loudspeaker: band-pass and a little saturation
    b, a = signal.butter(2, [450, 5000], btype="band", fs=SR)
    y = np.tanh(1.5 * signal.lfilter(b, a, y, axis=0)) / np.tanh(1.5)
    return y


# ------------------------------------------------------------------ build
def build_layers(ir: np.ndarray, rng: np.random.Generator) -> tuple[list[dict], dict[str, np.ndarray]]:
    infos, audio = [], {}
    for spec in LAYERS:
        x = read(loop.CLEAN / f"{slug_of(spec['id'])}.flac")
        mask, hum = human_free(x)
        a, b = longest_true(mask)
        y, meta = loop.make_loop(x[a:b], spec["loop_s"], spec["xfade_s"])
        y = place(y, spec, ir, circular=True)
        g = REF_LUFS + spec["gain_db"] - Lz.integrated(y)
        y *= 10 ** (g / 20)
        seam = loop.verify(y)
        audio[spec["name"]] = y
        infos.append({k: v for k, v in spec.items() if k != "loop_s"} | {
            "loop_s_range": list(spec["loop_s"]), "len_samples": len(y), "len_s": round(len(y) / SR, 4),
            "usable_span_s": [round(a / SR, 2), round(b / SR, 2)], "loop": meta["loop"],
            "seam_raw": meta["seam"], "seam_placed": seam, "human_check": hum, "lufs_i": round(Lz.integrated(y), 2)})
        log(f"layer {spec['name']}: {len(y)/SR:.2f} s, seam 2nd-diff pct {seam['wrap_second_diff_percentile']}, "
            f"human windows {hum['tagger_human_windows']}, vad {hum['vad_speech_s']} s")
    return infos, audio


def build_events(ir: np.ndarray, rng: np.random.Generator) -> tuple[list[dict], dict[str, list[np.ndarray]]]:
    infos, audio = [], {}
    for ev in EVENTS:
        takes, meta = [], []
        if ev.get("synth"):
            for kind in ("piyo", "kakko"):
                y = crossing_burst(kind)
                takes.append(y)
                meta.append({"take": len(takes), "synth": kind, "len_s": round(len(y) / SR, 2)})
            hum = None
        else:
            per = int(np.ceil(ev["takes"] / len(ev["ids"])))
            hum = {}
            for rid in ev["ids"]:
                x = read(loop.CLEAN / f"{slug_of(rid)}.flac")
                mask, hum[rid] = human_free(x)
                for a, b in pick_takes(x, mask, ev, per, tag_ok(x, ev.get("tag"), ev.get("tag_min", TAG_MIN))):
                    y = fade(x[a:b], ev["extent"]["fade_in_s"], ev["extent"]["fade_out_s"])
                    takes.append(y)
                    meta.append({"take": len(takes), "source": rid, "from_s": round(a / SR, 2), "to_s": round(b / SR, 2)})
        out = []
        for y, m in zip(takes, meta):
            z = place(y, ev, ir, circular=False)
            z = fade(z[: len(y) + (len(ir) if ev.get("reverb_db") is not None else 0)], 0.002, 0.05)
            z *= 10 ** ((REF_LUFS + ev["peak_lu"] - Lz.momentary_max(z)) / 20)
            out.append(z)
            m |= {"len_s": round(len(z) / SR, 2), "lufs_m_max": round(Lz.momentary_max(z), 2)}
        audio[ev["name"]] = out
        infos.append({k: v for k, v in ev.items() if k not in ("ids",)} | {"sources": ev["ids"], "takes": meta,
                                                                           "human_check": hum})
        log(f"event {ev['name']}: {len(out)} takes, {[mm['len_s'] for mm in meta]} s")
    return infos, audio


def schedule(rng: np.random.Generator, dur_s: float, hour: float, takes: dict[str, int]) -> list[dict]:
    """The runtime scheduler (page.py implements the same rules in JS)."""
    out = []
    for ev in EVENTS:
        s = ev["schedule"]
        hrs = s.get("active_hours")
        if hrs and not (hrs[0] <= hour < hrs[1]):
            continue
        t, last = rng.uniform(0, s["mean_interval_s"]), -1
        while t < dur_s:
            k = int(rng.integers(takes[ev["name"]]))
            if k == last:
                k = (k + 1) % takes[ev["name"]]
            out.append({"event": ev["name"], "take": k, "t": round(t, 3),
                        "gain_db": round(float(rng.uniform(-1, 1) * s["gain_jitter_db"]), 2),
                        "pan": round(float(rng.uniform(*s["pan"])), 3)})
            last = k
            t += s["min_gap_s"] + rng.exponential(max(1e-3, s["mean_interval_s"] - s["min_gap_s"]))
    return sorted(out, key=lambda e: e["t"])


def drift_curve(rng: np.random.Generator, n: int, drift_db: float) -> np.ndarray:
    """Gain (linear) per sample: random targets every 8-20 s, one-pole smoothing (6 s)."""
    hop = int(0.05 * SR)
    steps = n // hop + 2
    tgt = np.zeros(steps)
    i, cur = 0, 0.0
    while i < steps:
        cur = rng.uniform(-drift_db, drift_db)
        k = int(rng.uniform(*DRIFT["retarget_s"]) / 0.05)
        tgt[i:i + k] = cur
        i += k
    a = np.exp(-0.05 / DRIFT["time_constant_s"])
    g = signal.lfilter([1 - a], [1, -a], tgt, zi=[a * tgt[0]])[0]
    return np.interp(np.arange(n), np.arange(steps) * hop, 10 ** (g / 20))


def render(layers: dict[str, np.ndarray], events: dict[str, list[np.ndarray]], evs: list[dict], dur_s: float,
           rng: np.random.Generator) -> np.ndarray:
    n = int(dur_s * SR)
    mix = np.zeros((n, 2))
    for spec in LAYERS:
        y = layers[spec["name"]]
        off = int(rng.integers(len(y)))                     # runtime starts every layer at a random phase
        idx = (np.arange(n) + off) % len(y)
        mix += y[idx] * drift_curve(rng, n, spec["drift_db"])[:, None]
    for e in evs:
        z = stereo(events[e["event"]][e["take"]], e["pan"]) * 10 ** (e["gain_db"] / 20)
        i = int(e["t"] * SR)
        m = min(len(z), n - i)
        mix[i:i + m] += z[:m]
    return mix


def write_float(path: Path, y: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, y.astype(np.float32), SR, subtype="FLOAT")


def build() -> dict:
    PRE.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    ir, ir_info = reflections_ir()
    layer_info, layers = build_layers(ir, rng)
    event_info, events = build_events(ir, rng)
    for k, y in layers.items():
        write_float(PRE / "layers" / f"{k}.wav", y)
    for k, zs in events.items():
        for j, z in enumerate(zs, 1):
            write_float(PRE / "events" / f"{k}-{j:02d}.wav", z)
    evs = schedule(np.random.default_rng(SEED + 1), PREVIEW_S, PREVIEW_HOUR, {k: len(v) for k, v in events.items()})
    prev = render(layers, events, evs, PREVIEW_S, np.random.default_rng(SEED + 2))
    write_float(PRE / "preview.wav", prev)
    hum = human_free(prev)[1]
    lens = [l["len_s"] for l in layer_info]
    meta = {"name": NAME, "seed": SEED, "ref_lufs_premaster": REF_LUFS, "ir": ir_info, "layers": layer_info,
            "events": event_info, "drift": DRIFT,
            "preview": {"dur_s": PREVIEW_S, "hour": PREVIEW_HOUR, "schedule": evs, "human_check": hum,
                        "lufs_i": round(Lz.integrated(prev), 2)},
            "loop_lengths_s": lens,
            "pairwise_min_beat_s": round(min(abs(a - b) for i, a in enumerate(lens) for b in lens[i + 1:]), 3)}
    (OUT / "bed.json").write_text(json.dumps(meta, indent=2))
    log(f"preview: {len(evs)} events, {meta['preview']['lufs_i']} LUFS-I (pre-master), human windows "
        f"{hum['tagger_human_windows']}/{hum['tagger_windows']}, vad {hum['vad_speech_s']} s")
    return meta


if __name__ == "__main__":
    build()
