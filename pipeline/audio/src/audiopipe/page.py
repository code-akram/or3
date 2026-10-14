"""Step 7: listening gate, round 2. Writes data/build/audio/index.html (static page, served from
data/build/audio) and bench/m1/listening-round-2.md, plus pool spectrogram PNGs.

    uv run python -I -m audiopipe.page

Round 2 (after the 2026-10-12 gate on MacBook Air built-in speakers) lists only what changed:
the human-free night bed (live runtime mix + a fixed 3-minute preview), the small-speaker wet
steps (A/B against the round-1 recipe on the same takes), and the alley takes rebuilt from the
current IR. Round-1 items the user approved (dry steps, low-volume clarity) and the dropped
contact-mic pool are not on the page. Questions are written for laptop speakers at 60 % and 25 %.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from . import provenance as prov
from .common import BUILD, ffmpeg, repo_root

SR = 48000
POOL = "dress-concrete"
VOLUMES = "Set the Mac's output to its built-in speakers. Answer at 60 % volume first, then at 25 % (about 10 and 4 of the 16 volume-key steps)."
LISTEN = {
    "bed": [
        "60 %: does it read as a Shinjuku side street at night with nobody left: wind, light rain and drips, machines still running? "
        "Can you hear ANY voice, footstep, car, train or music, even far away? If so, note the time in the event log.",
        "Leave the live mix running for 5 minutes or more. Does anything give the loop away (a gust, a drip pattern, a crow call you recognise coming back)?",
        "Machines: can you pick out the condenser unit (left), the vending machine (right), the neon buzz and the pole transformer (far left)? "
        "On laptop speakers they are quiet by design; too quiet, right, or too loud?",
        "Events (crows, insect patches, a cricket, gusts singing on wires, a distant crossing signal): too often, too rare, or fine? Does any of them sound fake or out of place?",
        "Crossing signal: switch the game clock between 21:00 (signals sounding) and 23:00 (switched off, as many Tokyo crossings are late at night). Keep it, or drop it?",
        "25 %: the speaker model predicts the bed sits at about room-noise level here. Is the street still there for you, or gone? Is that acceptable?",
    ],
    "preview": [
        "The same mix rendered once (seeded, 21:00): use it if the live mix stutters; it is also the file the human-presence check ran on.",
    ],
    "wet": [
        "60 %, then 25 %: on the same take, switch dry -> wet (round 1) -> wet (round 2). Is the water now evident on the laptop speakers?",
        "Does round 2 still sound like a leather sole on a wet street, not a separate splash layer, a hand slap, or hiss?",
        "Walk over the bed: do wet steps stay clear of the rain? (The splash band, 1.5-6 kHz, is where the rain is too.)",
        "Is round 2 too loud or too bright next to the dry set (it is about 2-3 LU louder)?",
        "Wet takes now start sample-aligned with their dry take (they were 10 ms late, the EQ's delay). Switching dry -> wet "
        "should not move the step in time.",
    ],
    "alley": [
        "The spike-6 IR was re-baked since round 1 (tail to -60 dB now ~0.74 s, was ~1.05 s; same EDT/T20 within 5 %). Do the alley takes still sound right?",
        "Alley footstep takes only (walk set 'alley dry' / 'alley wet'): the bake scales Steam Audio's reflections down 8.6 dB "
        "(its calibration against a ground-plane run), which sets these takes' direct-to-reverb balance (DRR about -8 dB). "
        "Is that right, or should the alley be wetter? This does not apply to the night bed: the bed normalises the IR "
        "itself and sets each layer's reflections level on its own, so the calibration has no effect there.",
    ],
    "bandwidth": [
        "These recordings are dark: by the pipeline's measure their content stops below the 18 kHz quality floor, but "
        "with a natural roll-off and no codec or resampler wall (lossy or upsampled files are still rejected). On the "
        "laptop speakers, does any of them sound dull, muffled or 'cheap' next to the others? If so, name it: it goes "
        "back for a brighter replacement. The footstep one is the approved main pool.",
    ],
}
BANDWIDTH_FLAG = "bandwidth flag"   # marker in provenance status_reason (audiopipe.analyse.gate)


def pool_png(files: list[Path], png: Path) -> None:
    args, chains = [], []
    for i, f in enumerate(files):
        args += ["-i", str(f)]
        chains.append(f"[{i}]aformat=sample_rates=48000:channel_layouts=mono,apad=pad_dur=0.15[p{i}]")
    cat = "".join(f"[p{i}]" for i in range(len(files)))
    g = ";".join(chains) + f";{cat}concat=n={len(files)}:v=0:a=1,asplit[a][b];" \
        "[a]showspectrumpic=s=1400x360:legend=0:scale=log:fscale=lin:drange=100[s];[b]showwavespic=s=1400x120:scale=lin[w];[w][s]vstack"
    ffmpeg(*args, "-filter_complex", g, "-frames:v", "1", str(png))


def preview_png(flac: Path, png: Path) -> None:
    ffmpeg("-i", str(flac), "-filter_complex",
           "asplit[a][b];[a]showspectrumpic=s=1400x360:legend=0:scale=log:fscale=log:drange=90[s];"
           "[b]aformat=channel_layouts=mono,showwavespic=s=1400x100:scale=lin[w];[w][s]vstack", "-frames:v", "1", str(png))


def fmt_stats(s: dict) -> str:
    return (f"I {s['lufs_i']} LUFS · M max {s['lufs_m_max']} LUFS · TP {s['true_peak_dbtp']} dBTP · "
            f"LRA {s['lra_lu']} LU · {s['duration_s']} s")


def main() -> None:
    summary = json.loads((BUILD / "masters" / "summary.json").read_text())
    outs = summary["outputs"]
    bedj = json.loads((BUILD / "masters" / "ambience-v2" / "bed.json").read_text())
    web_bed = json.loads((BUILD / "web" / "ambience-v2" / "bed.json").read_text())
    spk = json.loads((BUILD / "analysis" / "speaker" / "report.json").read_text())
    amb = [o for o in outs if o["category"] == "ambience"]
    prev = next(o for o in amb if o["kind"] == "preview")
    layers = [o for o in amb if o["kind"] == "layer"]
    foley = [o for o in outs if o["category"] == "foley" and o["pool"] == POOL]
    (BUILD / "analysis").mkdir(exist_ok=True)
    for variant in ("dry", "wet", "wet-v1"):
        pool_png([BUILD / o["flac"] for o in foley if o["variant"] == variant], BUILD / "analysis" / f"pool-{variant}.png")
    preview_png(BUILD / prev["flac"], BUILD / "analysis" / "bed-preview.png")
    recs = prov.load()
    analysis = {a["id"]: a for a in json.loads((BUILD / "analysis" / "summary.json").read_text())}
    used = sorted({l["id"] for l in bedj["layers"]} | {i for e in bedj["events"] for i in e["sources"]})
    pool = json.loads((BUILD / "masters" / "foley" / POOL / "pool.json").read_text())
    step_src = "freesound:" + pool["source"].split("-")[-1]
    used_for: dict[str, list[str]] = {step_src: [f"footsteps ({POOL}, main pool)"]}
    for l in bedj["layers"]:
        used_for.setdefault(l["id"], []).append(f"bed layer {l['name']}")
    for e in bedj["events"]:
        for i in e["sources"]:
            used_for.setdefault(i, []).append(f"bed event {e['name']}")
    flagged = []
    for r in sorted(used_for):
        if BANDWIDTH_FLAG in recs[r].get("status_reason", ""):
            s = analysis[r]["spectral"]
            flagged.append({"id": r, "title": recs[r]["title"][:60], "author": recs[r]["author"], "used": ", ".join(used_for[r]),
                            "edge_typ_khz": s["content_edge_median_hz"] / 1000, "edge_loud_khz": s["content_edge_mean_hz"] / 1000,
                            "band_rel_db": f"{s['band_15_18k_rel_db']} / {s['band_15_18k_rel_db_loud']}", "png": analysis[r]["spectrogram"]})
    flag_rows = "".join(
        f"<tr><td><a href='{html.escape(recs[f['id']]['source_url'])}'>{html.escape(f['id'])}</a></td><td>{html.escape(f['title'])}</td>"
        f"<td>{html.escape(f['used'])}</td><td>{f['edge_typ_khz']:.1f} / {f['edge_loud_khz']:.1f} kHz</td><td>{f['band_rel_db']} dB</td>"
        f"<td><a href='{html.escape(f['png'])}'>png</a></td></tr>" for f in flagged) or "<tr><td colspan='6'>none</td></tr>"

    data = {
        "bed": web_bed, "base": "web/ambience-v2/",
        "preview": {"opus": prev["opus"]["path"], "flac": prev["flac"]},
        "foley": [{"variant": o["variant"], "take": o["take"], "flac": o["flac"], "opus": o["opus"]["path"],
                   "stats": o["stats"], "cents": o["pitch_cents"], "gain": o["gain_db"]} for o in foley],
        "bus": summary["bus_gains_db"],
    }

    def human(rid: str) -> str:
        h = analysis.get(rid, {}).get("human")
        if not h:
            return "-"
        return f"VAD {h['vad']['speech_seconds']} s · tagger {h['tagger']['human_windows']}/{h['tagger']['windows']}"

    src_rows = "".join(
        f"<tr><td><a href='{html.escape(recs[r]['source_url'])}'>{html.escape(r)}</a></td><td>{html.escape(recs[r]['title'][:60])}</td>"
        f"<td>{html.escape(recs[r]['author'])}</td><td>{recs[r]['licence']}</td><td>{human(r)}</td>"
        f"<td><a href='{html.escape(analysis[r]['spectrogram'])}'>png</a></td></tr>" for r in used)
    layer_rows = "".join(
        f"<tr><td>{l['name']}</td><td>{html.escape(l['role'])}</td><td>{l['len_s']} s</td><td>{l['gain_db']:+.0f}</td>"
        f"<td>{o['seam']['wrap_second_diff_percentile']} / {o['opus']['seam']['wrap_second_diff_percentile']}</td>"
        f"<td>{spk['mix']['layers'][l['name']]['lufs_laptop']}</td></tr>"
        for l, o in zip(bedj["layers"], layers))
    sm = spk["splash"]["median"]
    splash_rows = "".join(f"<tr><td>{m}</td><td>{sm['v1'][m]}</td><td>{sm['v2'][m]}</td></tr>" for m in sm["v1"])
    vol_rows = "".join(f"<tr><td>{v}</td><td>{r['bed_dba']}</td><td>{r['steps_dba_peak']}</td><td>{r['wet_steps_dba_peak']}</td>"
                       f"<td>{r['bed_over_room_db']:+}</td></tr>" for v, r in spk["mix"]["volumes"].items())
    ir = summary["ir"]
    ir_note = ("<b class='rejected'>SYNTHETIC PLACEHOLDER IR</b>" if ir["synthetic_placeholder"] else
               f"spike-6 IR snapshot <code>{html.escape(ir['source_ir'])}</code> (sha256 {ir['source_ir_sha256'][:12]}…)")
    rep = {"__DATA__": json.dumps(data), "__SOURCES__": src_rows, "__LAYERS__": layer_rows, "__SPLASH__": splash_rows,
           "__VOL__": vol_rows, "__IR__": ir_note, "__FLAGS__": flag_rows, "__LISTEN__": json.dumps(LISTEN), "__VOLUMES__": html.escape(VOLUMES),
           "__BA__": f"{summary['bus_gains_db']['ambience']:+.0f}", "__BF__": f"{summary['bus_gains_db']['foley']:+.0f}",
           "__PREVSTATS__": fmt_stats(prev["stats"])}
    page = PAGE
    for k, v in rep.items():
        page = page.replace(k, v)
    (BUILD / "index.html").write_text(page)

    # ------------------------------------------------------------ markdown playlist
    p = bedj["preview"]
    md = ["# Listening round 2 — audio (m1)", "",
          "Generated by `pipeline/audio` (`uv run python -I -m audiopipe.page`). Files live in `data/build/audio/` "
          "(gitignored, rebuildable); open `index.html` there in Chrome (serve the folder, e.g. "
          "`python3 -m http.server -d data/build/audio`). Only items changed since round 1 are listed.", "",
          f"**Playback: MacBook Air built-in speakers, no headphones.** {VOLUMES}", "",
          "Sign-off: tick each box or write a note and tell Claude. Anything unticked goes back into the pipeline.", "",
          "## 1. Night bed: \"Shinjuku side street at night, nobody left\" (replaces the rejected street loop)", "",
          f"- [ ] **Live mix** (page section 1): {len(bedj['layers'])} looping layers of different lengths "
          f"({', '.join(f'{l} s' for l in bedj['loop_lengths_s'])}) with slow gain drift, plus one-shot events on a random schedule. "
          "This is what the game will run.",
          f"- [ ] **3-minute preview** `{prev['flac']}` / `{prev['opus']['path']}`: {fmt_stats(prev['stats'])}; "
          f"{len(p['schedule'])} events, game clock {p['hour']:.0f}:00.",
          f"  - Human-presence check on the preview: VAD speech {p['human_check']['vad_speech_s']} s, tagger "
          f"{p['human_check']['tagger_human_windows']}/{p['human_check']['tagger_windows']} windows flagged.",
          "- Listen for:"] + [f"  - [ ] {x}" for x in LISTEN["bed"]] + [
          "", "| layer | what | loop | level (LU vs wind) |", "|---|---|---|---|"] + [
          f"| {l['name']} | {l['role']} | {l['len_s']} s | {l['gain_db']:+.0f} |" for l in bedj["layers"]] + [
          "", "Events: " + "; ".join(f"{e['name']} ({len(e['takes'])} takes, every ~{e['schedule']['mean_interval_s']} s, "
                                     f"at least {e['schedule']['min_gap_s']} s apart"
                                     + (f", {e['schedule']['active_hours'][0]}-{e['schedule']['active_hours'][1]} h only" if e['schedule'].get('active_hours') else "")
                                     + ")" for e in bedj["events"]) + ".", "",
          "## 2. Wet steps for small speakers", "",
          "Page section 2: pick a take, then play dry / wet round 1 / wet round 2. 'Walk' plays the chosen set over the bed.", "",
          "- Listen for:"] + [f"  - [ ] {x}" for x in LISTEN["wet"]] + ["",
          "Measured through a generic laptop-speaker model (200 Hz high-pass, +2 dB at 2.5 kHz; not a measurement of the Air), median of 8 takes:", "",
          "| metric | round 1 | round 2 |", "|---|---|---|"] + [f"| {m} | {sm['v1'][m]} | {sm['v2'][m]} |" for m in sm["v1"]] + [
          "", "## 3. Alley takes (rebuilt from the current IR)", ""] + [f"- [ ] {x}" for x in LISTEN["alley"]] + [
          "", "## 4. Mix at 25 % and 60 % (speaker model, rough SPL; quiet room ~30 dBA)", "",
          "| volume | bed dBA | dry step peak dBA | wet step peak dBA | bed over room |", "|---|---|---|---|---|"] + [
          f"| {v} | {r['bed_dba']} | {r['steps_dba_peak']} | {r['wet_steps_dba_peak']} | {r['bed_over_room_db']:+} |"
          for v, r in spk["mix"]["volumes"].items()] + [
          "", "## 5. Dark sources (below the 18 kHz bandwidth floor, flagged)", "",
          "Page section 4. The floor measure was broken until 2026-10-14 (it always read Nyquist); fixed, it puts these "
          "sources under 18 kHz. None shows a codec or resampler wall, so they are accepted with a flag instead of "
          "rejected (bench/m1/v4/t4-audio-bandwidth.md).", ""] + [f"- [ ] {x}" for x in LISTEN["bandwidth"]] + [
          "", "| ok | id | title | used for | content edge, typical / loud frames | 15-18 kHz vs 1-4 kHz, typical / loud |", "|---|---|---|---|---|---|"] + [
          f"| [ ] | {f['id']} | {f['title']} | {f['used']} | {f['edge_typ_khz']:.1f} / {f['edge_loud_khz']:.1f} kHz | {f['band_rel_db']} dB |"
          for f in flagged] + [
          "", "## 6. Sources (all CC0 or CC-BY 4.0; credits in provenance/audio.jsonl)", "",
          "| id | title | author | licence | human check (VAD / tagger) |", "|---|---|---|---|---|"] + [
          f"| {r} | {recs[r]['title'][:60]} | {recs[r]['author']} | {recs[r]['licence']} | {human(r)} |" for r in used] + [
          "| synthesised | crossing signals (piyo / kakko) | project | CC-BY-4.0 (own work) | - |", ""]
    out = repo_root() / "bench" / "m1" / "listening-round-2.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(md) + "\n")
    print(f"wrote {BUILD / 'index.html'} and bench/m1/listening-round-2.md")


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Audio Listening Round 2</title>
<style>
:root{--bg:#111316;--fg:#e8e6e3;--mut:#9aa0a6;--acc:#e0447a;--ok:#3fb68b;--bad:#e5534b;--card:#1b1e23;--line:#2c3036}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,sans-serif}
main{max-width:1100px;margin:0 auto;padding:16px}
h1{font-size:22px;margin:8px 0} h2{font-size:18px;margin:28px 0 8px;border-bottom:1px solid var(--line);padding-bottom:4px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px;margin:10px 0}
button,select{background:#2a2f36;color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:6px 10px;font:inherit;cursor:pointer}
button.on{border-color:var(--acc);color:#fff;background:#3a2330}
.mut{color:var(--mut);font-size:13px} code{font-size:12.5px;color:#cfd3d7}
table{border-collapse:collapse;width:100%;font-size:13px} td,th{border-bottom:1px solid var(--line);padding:4px 6px;text-align:left;vertical-align:top}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:6px}
.rejected{color:var(--bad)}
ul{margin:4px 0 4px 18px;padding:0} img{max-width:100%;border-radius:6px;margin-top:6px}
.row{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:6px 0}
#log{height:120px;overflow:auto;font:12px/1.4 ui-monospace,monospace;background:#0c0d0f;border-radius:6px;padding:6px}
.take{display:flex;flex-direction:column;gap:4px} .take .row{margin:0}
.scroll{overflow-x:auto}
</style></head><body><main>
<h1>Audio listening gate — round 2</h1>
<p><b>Laptop speakers, no headphones.</b> __VOLUMES__</p>
<p class="mut">Chrome recommended. Alley IR: __IR__.</p>

<h2>1. Night bed — Shinjuku side street, nobody left</h2>
<div class="card">
<div class="row"><button id="bedPlay">Start live mix</button>
Game clock <select id="hour"><option value="21">21:00 (crossing signals on)</option><option value="23">23:00 (signals off)</option></select>
<span id="bedPos" class="mut"></span></div>
<div class="row mut" id="layerToggles"></div>
<div id="log"></div>
<ul id="bedListen"></ul>
<div class="scroll"><table><tr><th>layer</th><th>what</th><th>loop</th><th>LU vs wind</th><th>seam pct FLAC / Opus</th><th>LUFS via laptop model (bus)</th></tr>__LAYERS__</table></div>
</div>
<div class="card">
<div class="row"><button id="prevPlay">Play the 3-minute preview</button><span class="mut">__PREVSTATS__</span></div>
<ul id="prevListen"></ul>
<img src="analysis/bed-preview.png" alt="spectrogram of the 3-minute preview">
</div>

<h2>2. Wet steps — round 1 vs round 2</h2>
<div class="card">
<div class="row">Codec <select id="codec"><option value="opus">Opus (web)</option><option value="flac">FLAC (master)</option></select>
<label><input type="checkbox" id="withBed"> walk over the bed (bus gains: bed __BA__ dB, steps __BF__ dB)</label></div>
<div class="grid" id="takes"></div>
<div class="row">Walk set <select id="var"><option value="dry">dry</option><option value="wet-v1">wet, round 1</option><option value="wet" selected>wet, round 2</option><option value="alley-dry">alley dry</option><option value="alley-wet">alley wet (round 2)</option></select>
Cadence <input id="cad" type="range" min="1.2" max="2.6" step="0.1" value="1.8"><span id="cadv"></span>
<button id="walk">Walk</button></div>
<div class="mut" id="takeInfo">Click a variant on a take to play it once.</div>
<ul id="wetListen"></ul><ul id="alleyListen"></ul>
<div class="scroll"><table><tr><th>laptop-model metric (median of 8)</th><th>round 1</th><th>round 2</th></tr>__SPLASH__</table></div>
<img src="analysis/pool-dry.png" alt="dry pool"><img src="analysis/pool-wet-v1.png" alt="wet round 1 pool"><img src="analysis/pool-wet.png" alt="wet round 2 pool">
</div>

<h2>3. Mix at 25 % / 60 % (speaker model; rough)</h2>
<div class="card scroll"><table><tr><th>volume</th><th>bed dBA</th><th>dry step peak dBA</th><th>wet step peak dBA</th><th>bed over a 30 dBA room</th></tr>__VOL__</table></div>

<h2>4. Dark sources (below the 18 kHz bandwidth floor, flagged)</h2>
<div class="card"><ul id="bwListen"></ul>
<div class="scroll"><table><tr><th>id</th><th>title</th><th>used for</th><th>content edge, typical / loud frames</th><th>15-18 kHz vs 1-4 kHz, typical / loud</th><th>spectrogram</th></tr>__FLAGS__</table></div></div>

<h2>5. Sources</h2>
<div class="card scroll"><table><tr><th>id</th><th>title</th><th>author</th><th>licence</th><th>human check</th><th>spectrogram</th></tr>
__SOURCES__<tr><td>synthesised</td><td>crossing signals (piyo / kakko)</td><td>project</td><td>CC-BY-4.0</td><td>-</td><td></td></tr></table></div>
</main>
<script>
const D = __DATA__; const LISTEN = __LISTEN__; const B = D.bed;
let ctx; const cache = {};
function ac(){ if(!ctx) ctx = new AudioContext({sampleRate:48000}); return ctx; }
const dbl = db => Math.pow(10, db/20);
const expo = m => -Math.log(1 - Math.random()) * m;
async function load(url){ if(cache[url]) return cache[url];
  const r = await fetch(url); const b = await ac().decodeAudioData(await r.arrayBuffer()); cache[url] = b; return b; }
const fill=(id,arr)=>{document.getElementById(id).innerHTML=arr.map(x=>'<li>'+x+'</li>').join('')};
fill('bedListen', LISTEN.bed); fill('prevListen', LISTEN.preview); fill('wetListen', LISTEN.wet); fill('alleyListen', LISTEN.alley); fill('bwListen', LISTEN.bandwidth);
const log = m => { const el=document.getElementById('log'); el.textContent += m + '\n'; el.scrollTop = el.scrollHeight; };

// Loops are Opus files wrap-padded by loop_start_s on both sides. A lossy decode of the loop's end
// is not the decode that runs into its start, so crossfade the region's last wrap_fix_s into the
// front padding (same as audiopipe.loop.opus_wrap_fix), then loop [start, start + len).
function wrapFix(b, L){ const sr=b.sampleRate, pad=Math.round(L.loop_start_s*sr), n=Math.round(L.len_samples*sr/48000), x=Math.round(L.wrap_fix_s*sr);
  for(let c=0;c<b.numberOfChannels;c++){ const d=b.getChannelData(c);
    for(let i=0;i<x;i++){ const w=i/x; d[pad+n-x+i] = (1-w)*d[pad+n-x+i] + w*d[pad-x+i]; } }
  return [pad/sr, (pad+n)/sr]; }

let bed = null;   // {bus, layers:[{src,gain}], timers:[]}
async function bedStart(busDb=0){
  if(bed) return; const t0=ac().currentTime;
  const bus = ac().createGain(); bus.gain.value = dbl(busDb); bus.connect(ac().destination);
  bed = {bus, layers:[], timers:[], t0, last:{}};
  const toggles = document.getElementById('layerToggles'); toggles.innerHTML = 'Layers: ';
  for(const L of B.layers){
    const b = await load(D.base + L.file); if(!b.__fixed){ b.__pts = wrapFix(b, L); b.__fixed = true; }
    const [ls, le] = b.__pts; const s = ac().createBufferSource(); s.buffer=b; s.loop=true; s.loopStart=ls; s.loopEnd=le;
    const g = ac().createGain(), mute = ac().createGain(); s.connect(g).connect(mute).connect(bus);
    s.start(0, ls + Math.random()*(le-ls));
    bed.layers.push({s, g, mute});
    const drift = () => { g.gain.setTargetAtTime(dbl((Math.random()*2-1)*L.drift_db), ac().currentTime, B.drift.time_constant_s);
      const [a, z] = B.drift.retarget_s; bed.timers.push(setTimeout(drift, 1000*(a + Math.random()*(z-a)))); };
    drift();
    const cb = document.createElement('label'); cb.innerHTML = `<input type="checkbox" checked> ${L.name} `;
    cb.querySelector('input').onchange = e => mute.gain.setTargetAtTime(e.target.checked?1:0, ac().currentTime, 0.05);
    cb.title = L.role; toggles.appendChild(cb);
  }
  for(const E of B.events){
    const bufs = await Promise.all(E.files.map(f => load(D.base + f))); const S = E.schedule;
    const fire = () => {
      const hour = +document.getElementById('hour').value; const hrs = S.active_hours;
      const t = (ac().currentTime - bed.t0).toFixed(1);
      if(!hrs || (hour >= hrs[0] && hour < hrs[1])){
        let k = Math.floor(Math.random()*bufs.length); if(k === bed.last[E.name] && bufs.length > 1) k = (k+1) % bufs.length; bed.last[E.name] = k;
        const s = ac().createBufferSource(); s.buffer = bufs[k]; const g = ac().createGain(); const p = ac().createStereoPanner();
        const gj = (Math.random()*2-1)*S.gain_jitter_db; g.gain.value = dbl(gj); p.pan.value = S.pan[0] + Math.random()*(S.pan[1]-S.pan[0]);
        s.connect(g).connect(p).connect(bed.bus); s.start();
        log(`${t} s  ${E.name} take ${k+1}  ${gj>=0?'+':''}${gj.toFixed(1)} dB  pan ${p.pan.value.toFixed(2)}`);
      } else log(`${t} s  ${E.name} skipped (game clock ${hour}:00 outside ${hrs[0]}-${hrs[1]} h)`);
      bed.timers.push(setTimeout(fire, 1000*(S.min_gap_s + expo(Math.max(0.001, S.mean_interval_s - S.min_gap_s)))));
    };
    bed.timers.push(setTimeout(fire, 1000*Math.random()*S.mean_interval_s));
  }
  document.getElementById('bedPlay').classList.add('on'); document.getElementById('bedPlay').textContent='Stop live mix';
  const tick = () => { if(!bed) return; document.getElementById('bedPos').textContent = `running ${(ac().currentTime-bed.t0).toFixed(0)} s`; bed.raf = requestAnimationFrame(tick); }; tick();
}
function bedStop(){ if(!bed) return; bed.timers.forEach(clearTimeout); bed.layers.forEach(l=>l.s.stop()); bed.bus.disconnect(); cancelAnimationFrame(bed.raf); bed=null;
  document.getElementById('bedPlay').classList.remove('on'); document.getElementById('bedPlay').textContent='Start live mix'; }
document.getElementById('bedPlay').onclick = () => bed ? bedStop() : bedStart(0);

let prevSrc = null;
document.getElementById('prevPlay').onclick = async () => { const btn=document.getElementById('prevPlay');
  if(prevSrc){ prevSrc.stop(); prevSrc=null; btn.classList.remove('on'); return; }
  const b = await load(D.preview.opus); prevSrc = ac().createBufferSource(); prevSrc.buffer=b; prevSrc.connect(ac().destination); prevSrc.start();
  prevSrc.onended = () => { prevSrc=null; btn.classList.remove('on'); }; btn.classList.add('on'); };

const codec = () => document.getElementById('codec').value;
const foley = v => D.foley.filter(f=>f.variant===v).sort((a,b)=>a.take-b.take);
const NAMES = {'dry':'dry','wet-v1':'wet r1','wet':'wet r2','alley-dry':'alley dry','alley-wet':'alley wet'};
async function playTake(f, when=0, show=false){ const b = await load(codec()==='opus' ? f.opus : f.flac);
  const s=ac().createBufferSource(); s.buffer=b; const g=ac().createGain();
  g.gain.value = document.getElementById('withBed').checked && walking ? dbl(D.bus.foley) : 1;
  s.connect(g).connect(ac().destination); s.start(when||0);
  if(show) document.getElementById('takeInfo').textContent = `${f.flac} · M max ${f.stats.lufs_m_max} LUFS · TP ${f.stats.true_peak_dbtp} dBTP · ${f.stats.duration_s} s`; }
document.getElementById('takes').innerHTML = foley('dry').map(f => `<div class="take card"><b>take ${f.take}</b>
  <span class="mut">${f.cents>0?'+':''}${f.cents} c · ${f.gain>0?'+':''}${f.gain} dB</span><div class="row">` +
  Object.keys(NAMES).map(v => `<button data-v="${v}" data-k="${f.take}">${NAMES[v]}</button>`).join('') + `</div></div>`).join('');
document.querySelectorAll('#takes button').forEach(b => b.onclick = () => playTake(foley(b.dataset.v).find(f=>f.take===+b.dataset.k), 0, true));
const cad=document.getElementById('cad'); const cadv=()=>document.getElementById('cadv').textContent=cad.value+' steps/s'; cad.oninput=cadv; cadv();
let walking=null;
document.getElementById('walk').onclick = async () => { const btn=document.getElementById('walk');
  if(walking){ clearInterval(walking); walking=null; btn.classList.remove('on'); if(document.getElementById('withBed').checked) bedStop(); return; }
  const t = foley(document.getElementById('var').value); await Promise.all(t.map(f => load(codec()==='opus' ? f.opus : f.flac)));
  if(document.getElementById('withBed').checked){ bedStop(); await bedStart(D.bus.ambience); }
  let last=-1, next=ac().currentTime+0.1; btn.classList.add('on');
  walking = setInterval(() => { while(next < ac().currentTime+0.25){ let i; do{ i=Math.floor(Math.random()*t.length); }while(i===last && t.length>1); last=i;
    playTake(t[i], next + (Math.random()-0.5)*0.03); next += 1/parseFloat(cad.value); } }, 50); };
</script></body></html>
"""


if __name__ == "__main__":
    main()
