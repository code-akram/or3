"""Step 6: master, encode, verify, and write provenance for every output.

    uv run python -I -m audiopipe.master

Per-category file-level targets (rationale in bench/m0/spike-7-audio.md):
  ambience  -26 LUFS-I, true peak <= -1.5 dBTP, gain only (no limiter: a limiter's state
            would differ at the loop wrap and could tick). Opus 96 kb/s stereo.
  foley     one-shots: pool loudness-matched per take (momentary max), one pool gain so the
            hottest take is at -1.5 dBTP (heel clicks have ~30 dB peak-to-loudness ratio, so peak
            binds, not LUFS). Dry/wet mono Opus 64 kb/s; alley (stereo) Opus 96 kb/s.
  signals   -20 LUFS-I, <= -1.5 dBTP (defined; nothing produced in spike 7)
  music     -23 LUFS-I, <= -1.5 dBTP before diegetic attenuation (defined; nothing produced)
Suggested starting runtime bus gains (used by the listening page "walk" demo): ambience -6 dB,
foley +6 dB, so steps peak ~10 LU above the bed in momentary terms.
Every Opus file is decoded again and checked: exact length (Ogg end trimming), true peak
overshoot, loudness drift, and (for the loop) the wrap seam.
"""

from __future__ import annotations

import datetime as dt
import json
import tempfile
from pathlib import Path

import numpy as np
import scipy
import soundfile as sf

from . import clean, loop
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
        r = recs.get(i)
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
    pid = "plateau:13104-shinjuku-ku-2025"
    recs[pid] = {
        "id": pid, "kind": "source", "domain": "data", "title": "PLATEAU 3D city model, Shinjuku-ku (13104), FY2025",
        "licence": "CC-BY-4.0", "licence_url": "https://creativecommons.org/licenses/by/4.0/",
        "licence_note": "PLATEAU site policy (https://www.mlit.go.jp/plateau/site-policy/) states compatibility with CC BY 4.0; credit and note modifications.",
        "author": "Ministry of Land, Infrastructure, Transport and Tourism (MLIT), Japan",
        "attribution": "出典：国土交通省 PLATEAU（3D都市モデル 新宿区 2025年度）を加工して作成",
        "source_url": "https://www.geospatial.jp/ckan/dataset/plateau-13104-shinjuku-ku-2025",
        "download_url": "https://www.geospatial.jp/ckan/dataset/plateau-13104-shinjuku-ku-2025",
        "retrieved_or_built": dt.date.today().isoformat(), "status": "accepted",
        "status_reason": "recorded by spike 7 as the input of the spike-6 IR; spike 5 owns the canonical record"}
    rid = "audio:ir/alley-01.wav"
    irj = json.loads((BUILD / "ir" / "alley-01.json").read_text())
    recs[rid] = derived(rid, REAL_IR, [pid], [
        f"Steam Audio {irj.get('steam_audio')} reflection bake on PLATEAU chunk {Path(irj.get('chunk', '')).name}",
        f"alley width {irj['alley']['width_m']:.2f} m, source-listener {irj.get('separation_m')} m, line of sight",
        "direct sound at t=0, normalised, trimmed to the -60 dB EDC point"],
        {"steam_audio": irj.get("steam_audio"), "spike": "6", "settings": irj.get("settings")}, recs,
        "Kabukicho alley impulse response (spike 6)")
    return rid, False


def main() -> None:
    tool = tool_info()
    recs = prov.load()
    outputs: list[dict] = []

    # ---------------------------------------------------------------- ambience loop
    meta = json.loads((BUILD / "masters" / "ambience" / f"{loop.NAME}.json").read_text())
    y = np.load(BUILD / "masters" / "ambience" / f"{loop.NAME}.premaster.npy").astype(np.float64)
    t = TARGETS["ambience"]
    g = t["lufs_i"] - Lz.integrated(y)
    tp = Lz.true_peak_db(y) + g
    if tp > t["tp_ceiling_dbtp"]:
        g -= tp - t["tp_ceiling_dbtp"]
        log(f"ambience: TP-bound, integrated lands {g + Lz.integrated(y):.1f} LUFS")
    y *= 10 ** (g / 20)
    flac = BUILD / "masters" / "ambience" / f"{loop.NAME}.flac"
    write_flac(flac, y)
    yq, _ = sf.read(flac, dtype="float64", always_2d=True)
    stats = Lz.summary(yq)
    seam = loop.verify(yq)
    enc = opus(flac, WEB / "ambience" / f"{loop.NAME}.opus", t["opus_kbps"])
    dec = enc.pop("_decoded")
    enc["seam"] = loop.verify(dec)
    outputs.append({"category": "ambience", "name": loop.NAME, "flac": str(flac.relative_to(BUILD)),
                    "stats": stats, "seam": seam, "opus": enc, "gain_db": round(g, 2), "loop": meta["loop"],
                    "layers": meta["layers"]})
    inputs = [l["id"] for l in meta["layers"]]
    tr = [f"{i}: " + "; ".join(clean.transformations(i)) for i in inputs]
    tr += [f"layer {l['id']} from {l['start_s']} s, loudness-matched {l['loudness_match_db']:+.2f} dB then {l['gain_db']:+.1f} dB"
           + (f", {l['filter']}" if l["filter"] else "") for l in meta["layers"]]
    tr += [f"ffmpeg amix normalize=0; loop {meta['loop']['loop_len_s']} s, acrossfade {meta['loop']['xfade_s']} s qsin/qsin "
           f"from source offset {meta['loop']['source_offset_s']} s", f"gain {g:+.2f} dB to {t['lufs_i']} LUFS-I, 24-bit FLAC"]
    rid = f"audio:ambience/{loop.NAME}.flac"
    recs[rid] = derived(rid, flac, inputs, tr, tool, recs, "Shinjuku night street ambience loop (master)")
    oid = f"audio:ambience/{loop.NAME}.opus"
    recs[oid] = derived(oid, BUILD / enc["path"], [rid],
                        [f"libopus {t['opus_kbps']} kb/s VBR, 20 ms frames, application=audio"], tool, recs,
                        "Shinjuku night street ambience loop (web)")

    # ---------------------------------------------------------------- footsteps
    ir_id, placeholder = ir_records(recs)
    for pool_name, kind in (("dress-concrete", "main"), ("dress-concrete-contactmic", "alt")):
        root = BUILD / "masters" / "foley" / pool_name
        pool = json.loads((root / "pool.json").read_text())
        src_id = "freesound:" + pool["source"].split("-")[-1]
        variants = ["dry", "wet"] + (["alley-dry", "alley-wet"] if kind == "main" else [])
        for variant in variants:
            for f in sorted((root / variant).glob("*.flac")):
                x, _ = sf.read(f, dtype="float64", always_2d=True)
                k = int(f.stem.split("-")[-1])
                take = pool["takes"][k - 1]
                stereo = x.shape[1] == 2
                kb = TARGETS["foley"]["opus_kbps_stereo" if stereo else "opus_kbps_mono"]
                enc = opus(f, WEB / "foley" / pool_name / variant / f"{f.stem}.opus", kb)
                enc.pop("_decoded")
                outputs.append({"category": "foley", "pool": pool_name, "kind": kind, "variant": variant, "take": k,
                                "flac": str(f.relative_to(BUILD)), "stats": Lz.summary(x), "opus": enc,
                                "pitch_cents": take["pitch_cents"], "gain_db": take["gain_db"]})
                rid = f"audio:foley/{pool_name}/{f.name}"
                if variant == "dry":
                    ins = [src_id]
                    tr = ["; ".join(clean.transformations(src_id)),
                          f"step {k} at {take['source_onset_s']} s, mono (L+R)/2, 5 ms pre-roll, 2/40 ms fades",
                          f"loudness-match to {pool['base_lufs_m']} LUFS-M, asetrate pitch {take['pitch_cents']:+d} cents, gain {take['gain_db']:+.1f} dB",
                          f"pool gain {pool['pool_gain_db']:+.2f} dB (hottest take at {pool['tp_ceiling_dbtp']} dBTP), seed {pool['seed']}"]
                elif variant == "wet":
                    ins = [f"audio:foley/{pool_name}/{pool_name}-dry-{k:02d}.flac"]
                    tr = ["dry take + synthesised splash (slap, spray, Minnaert droplets; numpy, seed "
                          f"{pool['seed'] * 100 + k}) at heel/toe impacts {take['impacts_ms']} ms",
                          f"shelf EQ: {pool['wet_eq']}", "wet = dry + 1 LU (momentary max), pool gain as dry"]
                else:
                    base = variant.split("-")[1]
                    ins = [f"audio:foley/{pool_name}/{pool_name}-{base}-{k:02d}.flac", ir_id]
                    tr = ["mono -> stereo, padded by IR length, ffmpeg afir (gtype=none, irnorm=-1) with the alley IR "
                          "scaled to unity direct path", "trailing silence trimmed (< -90 dBFS), 20 ms fade",
                          "alley pool gain: mean momentary max = source + 2 LU, capped at -1.5 dBTP"]
                recs[rid] = derived(rid, f, ins, tr, tool | {"seed": pool["seed"]}, recs,
                                    f"Dress shoe on concrete, {variant}, take {k} ({kind} pool)",
                                    placeholder=placeholder and variant.startswith("alley"))
                oid = rid.replace(".flac", ".opus")
                recs[oid] = derived(oid, BUILD / enc["path"], [rid], [f"libopus {kb} kb/s VBR, 20 ms frames"], tool, recs,
                                    f"Dress shoe on concrete, {variant}, take {k} (web)",
                                    placeholder=placeholder and variant.startswith("alley"))
    prov.save(recs)
    summary = {"built": dt.datetime.now().isoformat(timespec="seconds"), "targets": TARGETS, "bus_gains_db": BUS_GAINS_DB,
               "tool": tool, "ir": json.loads((BUILD / "masters" / "foley" / "dress-concrete" / "alley.json").read_text())["ir"],
               "outputs": outputs}
    (BUILD / "masters" / "summary.json").write_text(json.dumps(summary, indent=2))
    amb = outputs[0]
    log(f"ambience: {amb['stats']} seam {amb['seam']['wrap_second_diff_percentile']} pct; opus exact={amb['opus']['length_exact']} "
        f"opus seam {amb['opus']['seam']['wrap_second_diff_percentile']} pct")
    fo = [o for o in outputs if o["category"] == "foley"]
    log(f"foley: {len(fo)} masters; max TP {max(o['stats']['true_peak_dbtp'] for o in fo)}; "
        f"opus all exact length: {all(o['opus']['length_exact'] for o in fo)}; max decoded TP {max(o['opus']['decoded_tp_dbtp'] for o in fo)}")


if __name__ == "__main__":
    main()
