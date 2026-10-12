"""Step 6: master, encode, verify, and write provenance for every output.

    uv run python -I -m audiopipe.master

Per-category file-level targets (rationale in bench/m0/spike-7-audio.md):
  ambience  -26 LUFS-I, true peak <= -1.5 dBTP, gain only (no limiter: a limiter's state
            would differ at the loop wrap and could tick). Opus 96 kb/s stereo. Round 2 (the
            human-free bed, audiopipe.bed): one global gain for every layer, event and the
            3-minute preview, set so the preview meets the target and no single file passes
            the TP ceiling; the bed's internal balance is untouched.
  foley     one-shots: pool loudness-matched per take (momentary max), one pool gain so the
            hottest take is at -1.5 dBTP (heel clicks have ~30 dB peak-to-loudness ratio, so peak
            binds, not LUFS). Dry/wet mono Opus 64 kb/s; alley (stereo) Opus 96 kb/s.
  signals   -20 LUFS-I, <= -1.5 dBTP (defined; nothing produced in spike 7)
  music     -23 LUFS-I, <= -1.5 dBTP before diegetic attenuation (defined; nothing produced)
Suggested starting runtime bus gains (used by the listening page "walk" demo): ambience -6 dB,
foley +6 dB, so steps peak ~10 LU above the bed in momentary terms.
Every Opus file is decoded again and checked: exact length (Ogg end trimming), true peak
overshoot, loudness drift, and (for loops) the wrap seam.
Round-1 records that no longer have a build (the rejected street loop, the contact-mic A/B pool)
are dropped from the manifest; their files may linger in data/build (gitignored).
"""

from __future__ import annotations

import datetime as dt
import json
import tempfile
from pathlib import Path

import numpy as np
import scipy
import soundfile as sf

from . import bed, clean, loop, spatialise
from . import loudness as Lz
from . import provenance as prov
from .common import BUILD, REAL_IR, ffmpeg, ffmpeg_version, file_sha256, log

SR = 48000
WEB = BUILD / "web"
TARGETS = {
    "ambience": {"lufs_i": -26.0, "tp_ceiling_dbtp": -1.5, "opus_kbps": 96},
    "foley": {"pool_tp_ceiling_dbtp": -1.5, "opus_kbps_mono": 64, "opus_kbps_stereo": 96},
    "signals": {"lufs_i": -20.0, "tp_ceiling_dbtp": -1.5},
    "music": {"lufs_i": -23.0, "tp_ceiling_dbtp": -1.5},
}
BUS_GAINS_DB = {"ambience": -6.0, "foley": 6.0}
NAME_PREVIEW = f"{bed.NAME}-preview"
EXTERNAL: dict[str, dict] = {}   # records from other manifests (read for attribution, never written)
LOOP_PAD_S = 0.24  # 12 Opus frames; wrap padding of looped Opus files (see master_ambience)
WRAP_FIX_S = 0.02   # decoded-wrap crossfade (loop.opus_wrap_fix)


def opus(src: Path, dst: Path, kbps: int) -> dict:
    dst.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg("-i", str(src), "-c:a", "libopus", "-b:a", f"{kbps}k", "-vbr", "on", "-compression_level", "10",
           "-application", "audio", "-frame_duration", "20", "-map_metadata", "-1",
           "-fflags", "+bitexact", "-flags:a", "+bitexact", str(dst))  # bitexact: fixed Ogg serial, reproducible
    with tempfile.TemporaryDirectory() as td:
        dec = Path(td) / "d.wav"
        ffmpeg("-i", str(dst), "-c:a", "pcm_f32le", str(dec))
        y, _ = sf.read(dec, dtype="float64", always_2d=True)
    x, _ = sf.read(src, dtype="float64", always_2d=True)
    n = min(len(x), len(y))
    err = y[:n] - x[:n]
    snr = 10 * np.log10((x[:n] ** 2).sum() / max((err ** 2).sum(), 1e-20))
    return {"path": str(dst.relative_to(BUILD)), "kbps_target": kbps, "bytes": dst.stat().st_size,
            "decoded_samples": len(y), "master_samples": len(x), "length_exact": len(y) == len(x),
            "decoded_tp_dbtp": round(Lz.true_peak_db(y), 2), "decoded_lufs_m_max": round(Lz.momentary_max(y), 2),
            "decoded_lufs_i": round(Lz.integrated(y), 2), "waveform_snr_db": round(float(snr), 1),
            "_decoded": y}


def write_flac(path: Path, y: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, y, SR, subtype="PCM_24", format="FLAC")


def tool_info() -> dict:
    return {"ffmpeg": ffmpeg_version(), "libopus": "1.6.1 (via ffmpeg)", "numpy": np.__version__,
            "pipeline": "pipeline/audio (audiopipe 0.1.0)", "scipy": scipy.__version__, "soundfile": sf.__version__}


def attribution_for(ids: list[str], recs: dict) -> str:
    """Collect CREDITS lines of every attribution-requiring source behind these inputs."""
    seen, lines = set(), []

    def walk(i: str) -> None:
        r = recs.get(i) or EXTERNAL.get(i)
        if not r or i in seen:
            return
        seen.add(i)
        if r["kind"] == "source" and r.get("attribution") and r["licence"] != "CC0-1.0":
            lines.append(r["attribution"])
        for j in r.get("inputs", []):
            walk(j)
    for i in ids:
        walk(i)
    return "; ".join(lines) if lines else "Own work (CC0 sources + own synthesis), CC-BY-4.0"


def derived(rid: str, path: Path, inputs: list[str], transformations: list[str], tool: dict, recs: dict,
            title: str, placeholder: bool = False) -> dict:
    r = {"id": rid, "kind": "derived", "domain": "audio", "title": title, "licence": "CC-BY-4.0",
         "licence_url": "https://creativecommons.org/licenses/by/4.0/", "author": "project audio pipeline",
         "attribution": attribution_for(inputs, recs), "retrieved_or_built": dt.date.today().isoformat(),
         "path": prov.rel(path), "bytes": path.stat().st_size, "sha256": file_sha256(path),
         "inputs": inputs, "transformations": transformations, "tool": tool}
    if placeholder:
        r["synthetic_placeholder"] = True
    return r


def ir_records(recs: dict) -> tuple[str | None, bool]:
    """Provenance for the spike-6 IR (and the PLATEAU data behind it)."""
    meta = json.loads((BUILD / "masters" / "foley" / "dress-concrete" / "alley.json").read_text())["ir"]
    if meta["synthetic_placeholder"]:
        src = BUILD / "spatialise" / "PLACEHOLDER-synthetic-alley.wav"
        rid = "audio:ir/PLACEHOLDER-synthetic-alley.wav"
        recs[rid] = derived(rid, src, [], ["synthetic placeholder IR (audiopipe.spatialise.make_placeholder, seed 11)"],
                            {"generator": "numpy"}, recs, "SYNTHETIC PLACEHOLDER alley IR", placeholder=True)
        return rid, True
    # The PLATEAU source record lives in provenance/data.jsonl (spike 5 owns it); writing a copy
    # here makes the audit fail on a duplicate id. Read it only, so attributions still carry it.
    pid = "plateau:13104-shinjuku-ku-2025"
    for line in (prov.PROV_DIR / "data.jsonl").read_text().splitlines():
        r = json.loads(line) if line.strip() else {}
        if r.get("id") == pid:
            EXTERNAL[pid] = r
    if pid not in EXTERNAL:
        raise SystemExit(f"{pid} missing from provenance/data.jsonl")
    rid = "audio:ir/alley-01.wav"
    irj = json.loads((BUILD / "ir" / "alley-01.json").read_text())
    # The record describes the snapshot the build consumed (spatialise.IR_SNAPSHOT), not spike 6's
    # live file, which a rebake rewrites with a new sha256.
    if meta.get("source_ir_sha256") != file_sha256(spatialise.IR_SNAPSHOT):
        raise SystemExit("IR snapshot changed since the spatial stage ran; rerun spatialise")
    recs[rid] = derived(rid, spatialise.IR_SNAPSHOT, [pid], [
        f"Steam Audio {irj.get('steam_audio')} reflection bake on PLATEAU chunk {Path(irj.get('chunk', '')).name}",
        f"alley width {irj['alley']['width_m']:.2f} m, source-listener {irj.get('separation_m')} m, line of sight",
        "direct sound at t=0, normalised, trimmed to the -60 dB EDC point",
        f"copied from {prov.rel(REAL_IR)} by audiopipe.spatialise at build time (snapshot; spike 6 owns the original)"],
        {"steam_audio": irj.get("steam_audio"), "spike": "6", "settings": irj.get("settings")}, recs,
        "Kabukicho alley impulse response (spike 6)")
    return rid, False


def master_ambience(recs: dict, tool: dict, ir_id: str | None) -> list[dict]:
    """Round-2 bed: one global gain for layers, events and preview so the preview lands on the
    ambience target (layer and event levels relative to each other are the bed's mix)."""
    root = BUILD / "masters" / "ambience-v2"
    meta = json.loads((root / "bed.json").read_text())
    if ir_id and meta["ir"]["sha256"] != file_sha256(BUILD / meta["ir"]["path"].removeprefix("build/audio/")):
        raise SystemExit("ambience-v2 was built with a different IR snapshot than the current one; rerun bed")
    pre = root / "premaster"
    t = TARGETS["ambience"]
    prev, _ = sf.read(pre / "preview.wav", dtype="float64", always_2d=True)
    layers = {l["name"]: sf.read(pre / "layers" / f"{l['name']}.wav", dtype="float64", always_2d=True)[0] for l in meta["layers"]}
    events = {f.stem: sf.read(f, dtype="float64", always_2d=True)[0] for f in sorted((pre / "events").glob("*.wav"))}
    g = t["lufs_i"] - Lz.integrated(prev)
    # the TP ceiling binds on the hottest single file (an event can be the hottest)
    hottest = max(Lz.true_peak_db(y) for y in [prev, *layers.values(), *events.values()])
    if hottest + g > t["tp_ceiling_dbtp"]:
        g = t["tp_ceiling_dbtp"] - hottest
        log(f"ambience-v2: TP-bound, preview lands {g + Lz.integrated(prev):.1f} LUFS-I")
    k = 10 ** (g / 20)
    outputs = []
    by_name = {l["name"]: l for l in meta["layers"]}
    ev_meta = {e["name"]: e for e in meta["events"]}
    gain_note = f"bed global gain {g:+.2f} dB (preview to {t['lufs_i']} LUFS-I, every file <= {t['tp_ceiling_dbtp']} dBTP), 24-bit FLAC"
    layer_ids, event_ids = [], []

    def emit(kind: str, name: str, y: np.ndarray, rel: str, inputs: list[str], tr: list[str], title: str, seam: bool) -> str:
        flac = root / f"{rel}.flac"
        write_flac(flac, y * k)
        yq, _ = sf.read(flac, dtype="float64", always_2d=True)
        opus_tr = [f"libopus {t['opus_kbps']} kb/s VBR, 20 ms frames, application=audio"]
        if seam:
            # A lossy decode of the loop's end is not the decode that leads into its start (the
            # codec's noise differs by -19..-28 dB between two encodes of the same audio), so a
            # looped Opus file steps at the wrap. Encode the loop wrap-padded (its last
            # LOOP_PAD_S in front, its first LOOP_PAD_S after); after decoding, the player
            # crossfades the last WRAP_FIX_S of the loop region into the front padding's decode,
            # which runs continuously into the region's start (loop.opus_wrap_fix; page.py does
            # the same in JS), then loops [LOOP_PAD_S, LOOP_PAD_S + L).
            pad = int(LOOP_PAD_S * SR)
            with tempfile.TemporaryDirectory() as td:
                src = Path(td) / "padded.flac"
                write_flac(src, np.concatenate([yq[-pad:], yq, yq[:pad]]))
                enc = opus(src, WEB / "ambience-v2" / f"{rel}.opus", t["opus_kbps"])
            raw = enc.pop("_decoded")
            enc["seam_without_fix"] = loop.verify(raw[pad:pad + len(yq)])
            dec = loop.opus_wrap_fix(raw, pad, len(yq), int(WRAP_FIX_S * SR))[pad:pad + len(yq)]
            enc |= {"loop_start_s": LOOP_PAD_S, "loop_len_samples": len(yq), "wrap_fix_s": WRAP_FIX_S}
            opus_tr.insert(0, f"wrap-padded by {LOOP_PAD_S} s each side; loop region [{LOOP_PAD_S} s, {LOOP_PAD_S} s + {len(yq)} samples); "
                              f"player crossfades the region's last {WRAP_FIX_S} s into the front padding (loop.opus_wrap_fix)")
        else:
            enc = opus(flac, WEB / "ambience-v2" / f"{rel}.opus", t["opus_kbps"])
            dec = enc.pop("_decoded")
        o = {"category": "ambience", "kind": kind, "name": name, "flac": str(flac.relative_to(BUILD)),
             "stats": Lz.summary(yq), "opus": enc}
        if seam:
            o["seam"] = loop.verify(yq)
            o["opus"]["seam"] = loop.verify(dec)
        outputs.append(o)
        rid = f"audio:ambience-v2/{rel}.flac"
        recs[rid] = derived(rid, flac, inputs, tr + [gain_note], tool | {"seed": meta["seed"]}, recs, title)
        oid = rid.replace(".flac", ".opus")
        recs[oid] = derived(oid, BUILD / enc["path"], [rid], opus_tr,
                            tool, recs, title + " (web)")
        return rid

    def placing(s: dict) -> str:
        parts = [f"pan {s.get('pan', 0):+.2f} (constant power)" if s.get("pan") is not None else ""]
        if s.get("hpf"):
            parts.append(f"high-pass {s['hpf']} Hz")
        if s.get("lpf"):
            parts.append(f"low-pass {s['lpf']} Hz")
        if s.get("reverb_db") is not None:
            parts.append(f"alley reflections (spike-6 IR, direct path removed) at {s['reverb_db']:+.0f} dB")
        return "distance: " + ", ".join(p for p in parts if p)

    for name, y in layers.items():
        l = by_name[name]
        ins = [l["id"]] + ([ir_id] if l.get("reverb_db") is not None and ir_id else [])
        tr = ["; ".join(clean.transformations(l["id"])),
              f"human-presence check on the cleaned source (VAD speech {l['human_check']['vad_speech_s']} s, tagger "
              f"{l['human_check']['tagger_human_windows']}/{l['human_check']['tagger_windows']} windows)",
              f"seamless loop {l['loop']['loop_len_s']} s from source offset {l['loop']['source_offset_s']} s, acrossfade "
              f"{l['loop']['xfade_s']} s ({l['loop']['xfade_curve']}, fade-region correlation {l['loop']['xfade_correlation']})",
              placing(l) + " (FFT, circular over one loop period)",
              f"loudness {l['gain_db']:+.1f} LU relative to the wind layer"]
        layer_ids.append(emit("layer", name, y, f"layers/{name}", ins, tr, f"Night bed layer: {l['role']}", seam=True))
    for stem, y in events.items():
        ev, j = stem.rsplit("-", 1)
        e = ev_meta[ev]
        tk = e["takes"][int(j) - 1]
        if tk.get("synth"):
            ins = [ir_id] if ir_id else []
            tr = [f"synthesised Japanese accessible pedestrian signal, '{tk['synth']}' call and response (numpy), "
                  "450-5000 Hz band-pass and tanh saturation (small horn speaker)"]
            title = f"Distant crossing signal ({tk['synth']}), synthesised"
        else:
            ins = [tk["source"]] + ([ir_id] if e.get("reverb_db") is not None and ir_id else [])
            tr = ["; ".join(clean.transformations(tk["source"])),
                  f"take {tk['from_s']}-{tk['to_s']} s around a loudness peak, "
                  f"{e['extent']['fade_in_s']}/{e['extent']['fade_out_s']} s fades" + (f", contains '{e['tag']}' per the tagger" if e.get("tag") else "")]
            title = f"Night bed event: {ev}, take {int(j)}"
        tr += [placing(e), f"momentary max {e['peak_lu']:+.1f} LU relative to the wind layer"]
        event_ids.append(emit("event", stem, y, f"events/{stem}", ins, tr, title, seam=False))
    p = meta["preview"]
    tr = [f"3-minute render of the runtime mix at {p['hour']:.0f}:00: every layer looped from a random phase with slow gain "
          f"drift, {len(p['schedule'])} scheduled events (seeded; schedule in bed.json)"]
    emit("preview", NAME_PREVIEW, prev, NAME_PREVIEW, layer_ids + event_ids, tr, "Night bed, 3-minute preview", seam=False)
    web_meta = {"name": meta["name"], "drift": meta["drift"], "bus_gain_db": BUS_GAINS_DB["ambience"],
                "layers": [{"name": l["name"], "file": f"layers/{l['name']}.opus", "drift_db": l["drift_db"],
                            "len_s": l["len_s"], "loop_start_s": LOOP_PAD_S, "len_samples": l["len_samples"], "wrap_fix_s": WRAP_FIX_S, "role": l["role"]} for l in meta["layers"]],
                "events": [{"name": e["name"], "files": [f"events/{e['name']}-{i + 1:02d}.opus" for i in range(len(e["takes"]))],
                            "schedule": e["schedule"]} for e in meta["events"]],
                "preview": f"{NAME_PREVIEW}.opus", "preview_hour": p["hour"]}
    (WEB / "ambience-v2" / "bed.json").write_text(json.dumps(web_meta, indent=2))
    log(f"ambience-v2: global gain {g:+.2f} dB, {len(layers)} layers, {len(events)} events")
    return outputs


def main() -> None:
    tool = tool_info()
    recs = prov.load()
    # round 1 outputs that are gone: the street loop (rejected, people in it) and the Yuval
    # contact-mic A/B pool (user picked the main pool)
    for rid in [r for r in recs if r.startswith(("audio:ambience/", "audio:foley/dress-concrete-contactmic/"))]:
        del recs[rid]
    recs.pop("plateau:13104-shinjuku-ku-2025", None)   # canonical copy is in data.jsonl (see ir_records)
    ir_id, placeholder = ir_records(recs)
    outputs = master_ambience(recs, tool, None if placeholder else ir_id)

    # ---------------------------------------------------------------- footsteps (main pool)
    pool_name = "dress-concrete"
    root = BUILD / "masters" / "foley" / pool_name
    pool = json.loads((root / "pool.json").read_text())
    src_id = "freesound:" + pool["source"].split("-")[-1]
    for variant in ("dry", "wet", "wet-v1", "alley-dry", "alley-wet"):
        for f in sorted((root / variant).glob("*.flac")):
            x, _ = sf.read(f, dtype="float64", always_2d=True)
            k = int(f.stem.split("-")[-1])
            take = pool["takes"][k - 1]
            stereo = x.shape[1] == 2
            kb = TARGETS["foley"]["opus_kbps_stereo" if stereo else "opus_kbps_mono"]
            enc = opus(f, WEB / "foley" / pool_name / variant / f"{f.stem}.opus", kb)
            enc.pop("_decoded")
            outputs.append({"category": "foley", "pool": pool_name, "variant": variant, "take": k,
                            "flac": str(f.relative_to(BUILD)), "stats": Lz.summary(x), "opus": enc,
                            "pitch_cents": take["pitch_cents"], "gain_db": take["gain_db"]})
            rid = f"audio:foley/{pool_name}/{f.name}"
            title = f"Dress shoe on concrete, {variant}, take {k}"
            seed = pool["seed"] * 100 + k
            if variant == "dry":
                ins = [src_id]
                tr = ["; ".join(clean.transformations(src_id)),
                      f"step {k} at {take['source_onset_s']} s, mono (L+R)/2, 5 ms pre-roll, 2/40 ms fades",
                      f"loudness-match to {pool['base_lufs_m']} LUFS-M, asetrate pitch {take['pitch_cents']:+d} cents, gain {take['gain_db']:+.1f} dB",
                      f"pool gain {pool['pool_gain_db']:+.2f} dB (hottest take at {pool['tp_ceiling_dbtp']} dBTP), seed {pool['seed']}"]
            elif variant == "wet":
                ins = [f"audio:foley/{pool_name}/{pool_name}-dry-{k:02d}.flac"]
                w = pool["wet"]["v2"]
                tr = [f"dry take + synthesised small-speaker splash v2 (crack, water body, granular spray, fall-back slap, "
                      f"Minnaert droplets; numpy, seed {seed}) at heel/toe impacts {take['impacts_ms']} ms",
                      f"presence EQ: {w['eq']}", f"step level kept; splash alone at {w['splash_lu']:+.0f} LU vs the dry step (momentary max)",
                      f"pool gain as dry, trim {take['wet_trim_db']:+.2f} dB to stay <= {pool['tp_ceiling_dbtp']} dBTP"]
            elif variant == "wet-v1":
                ins = [f"audio:foley/{pool_name}/{pool_name}-dry-{k:02d}.flac"]
                w = pool["wet"]["v1"]
                tr = [f"round-1 wet recipe, kept for the before/after comparison: dry take + splash v1 (slap, spray, "
                      f"Minnaert droplets; numpy, seed {seed}) at heel/toe impacts {take['impacts_ms']} ms",
                      f"shelf EQ: {w['eq']}", f"wet = dry + {w['lift_lu']} LU (momentary max), pool gain as dry"]
                title += " (round-1 recipe, comparison)"
            else:
                base = variant.split("-")[1]
                ins = [f"audio:foley/{pool_name}/{pool_name}-{base}-{k:02d}.flac", ir_id]
                tr = ["mono -> stereo, padded by IR length, ffmpeg afir (gtype=none, irnorm=-1) with the alley IR "
                      "scaled to unity direct path", "trailing silence trimmed (< -90 dBFS), 20 ms fade",
                      "alley pool gain: mean momentary max = source + 2 LU, capped at -1.5 dBTP"]
            ph = placeholder and variant.startswith("alley")
            recs[rid] = derived(rid, f, ins, tr, tool | {"seed": pool["seed"]}, recs, title, placeholder=ph)
            oid = rid.replace(".flac", ".opus")
            recs[oid] = derived(oid, BUILD / enc["path"], [rid], [f"libopus {kb} kb/s VBR, 20 ms frames"], tool, recs,
                                title + " (web)", placeholder=ph)
    prov.save(recs)
    summary = {"built": dt.datetime.now().isoformat(timespec="seconds"), "targets": TARGETS, "bus_gains_db": BUS_GAINS_DB,
               "tool": tool, "ir": json.loads((root / "alley.json").read_text())["ir"], "outputs": outputs}
    (BUILD / "masters" / "summary.json").write_text(json.dumps(summary, indent=2))
    lay = [o for o in outputs if o.get("kind") == "layer"]
    log("ambience-v2 layers: worst FLAC seam 2nd-diff pct "
        f"{max(o['seam']['wrap_second_diff_percentile'] for o in lay)}, worst opus "
        f"{max(o['opus']['seam']['wrap_second_diff_percentile'] for o in lay)}; opus exact length: "
        f"{all(o['opus']['length_exact'] for o in outputs if o['category'] == 'ambience')}")
    fo = [o for o in outputs if o["category"] == "foley"]
    log(f"foley: {len(fo)} masters; max TP {max(o['stats']['true_peak_dbtp'] for o in fo)}; "
        f"opus all exact length: {all(o['opus']['length_exact'] for o in fo)}; max decoded TP {max(o['opus']['decoded_tp_dbtp'] for o in fo)}")


if __name__ == "__main__":
    main()
