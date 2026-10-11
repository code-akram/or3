"""Step 7: listening gate. Writes data/build/audio/index.html (static page, served from
data/build/audio) and bench/m0/listening-playlist.md, plus seam/pool spectrogram PNGs.

    uv run python -I -m audiopipe.page
"""

from __future__ import annotations

import html
import json
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from . import provenance as prov
from .common import BUILD, ffmpeg, repo_root

SR = 48000
LISTEN = {
    "ambience": [
        "Does it read as a Shinjuku side street at night (people, distant traffic, shutters, no score)?",
        "The wrap: press 'jump to 8 s before the wrap' and listen across it several times. Any click, "
        "level step, or a sound that cuts off or restarts?",
        "The 6 s crossfade (last 6 s of the file): any phasing, flanging, or a doubled voice?",
        "Repetition: after two or three passes, is there one memorable event that gives the loop away?",
        "Top end: the 17 kHz low-pass removed ultrasonic tones; does it sound dull or fine?",
    ],
    "dry": [
        "Do they sound like hard leather soles on concrete (heel click then toe)?",
        "Round-robin: in 'walk', does any take stick out (level, pitch, a scuff)? Do pitch shifts of "
        "+-50 cents sound natural or 'tuned'?",
        "Denoise artefacts: any watery or swirly noise in the tails?",
    ],
    "wet": [
        "Does the splash read as a shoe on a wet street, or as a hiss / separate layer?",
        "Droplets: natural or 'bubbly synth'? Too many, too few?",
        "Is the wet set too much louder or brighter than the dry set?",
    ],
    "alley": [
        "Does the alley IR sound like a narrow concrete/glass alley with the source a few metres away?",
        "Tail length (~1 s) and any metallic ringing or flutter?",
        "Direct-to-reverb balance (the bake measured DRR -7.7 dB): too wet for the player's own steps?",
    ],
}


def seam_png(flac: Path, png: Path, around_s: float = 8.0) -> None:
    y, _ = sf.read(flac, dtype="float32", always_2d=True)
    n = int(around_s * SR)
    z = np.concatenate([y[-n:], y[:n]])
    with tempfile.TemporaryDirectory() as td:
        w = Path(td) / "s.wav"
        sf.write(w, z, SR, subtype="FLOAT")
        ffmpeg("-i", str(w), "-filter_complex",
               "asplit[a][b];[a]showspectrumpic=s=1400x400:legend=0:scale=log:fscale=lin:drange=100[s];"
               "[b]aformat=channel_layouts=mono,showwavespic=s=1400x120:scale=lin[w];[w][s]vstack",
               "-frames:v", "1", str(png))


def pool_png(files: list[Path], png: Path) -> None:
    args, chains = [], []
    for i, f in enumerate(files):
        args += ["-i", str(f)]
        chains.append(f"[{i}]aformat=sample_rates=48000:channel_layouts=mono,apad=pad_dur=0.15[p{i}]")
    cat = "".join(f"[p{i}]" for i in range(len(files)))
    g = ";".join(chains) + f";{cat}concat=n={len(files)}:v=0:a=1,asplit[a][b];" \
        "[a]showspectrumpic=s=1400x360:legend=0:scale=log:fscale=lin:drange=100[s];[b]showwavespic=s=1400x120:scale=lin[w];[w][s]vstack"
    ffmpeg(*args, "-filter_complex", g, "-frames:v", "1", str(png))


def fmt_stats(s: dict) -> str:
    return (f"I {s['lufs_i']} LUFS · M max {s['lufs_m_max']} LUFS · TP {s['true_peak_dbtp']} dBTP · "
            f"LRA {s['lra_lu']} LU · {s['duration_s']} s")


def main() -> None:
    summary = json.loads((BUILD / "masters" / "summary.json").read_text())
    outs = summary["outputs"]
    amb = outs[0]
    (BUILD / "analysis").mkdir(exist_ok=True)
    seam_png(BUILD / amb["flac"], BUILD / "analysis" / "loop-seam.png")
    foley = [o for o in outs if o["category"] == "foley"]
    for variant in ("dry", "wet", "alley-dry", "alley-wet"):
        fs = [BUILD / o["flac"] for o in foley if o["kind"] == "main" and o["variant"] == variant]
        pool_png(fs, BUILD / "analysis" / f"pool-{variant}.png")
    recs = prov.load()
    sources = [r for r in recs.values() if r["kind"] == "source" and r["domain"] == "audio"]
    analysis = {a["id"]: a for a in json.loads((BUILD / "analysis" / "summary.json").read_text())}

    data = {
        "ambience": {"flac": amb["flac"], "opus": amb["opus"]["path"], "samples": amb["opus"]["master_samples"],
                     "stats": amb["stats"], "seam": amb["seam"], "opus_seam": amb["opus"]["seam"], "loop": amb["loop"]},
        "foley": [{"pool": o["pool"], "variant": o["variant"], "take": o["take"], "flac": o["flac"], "opus": o["opus"]["path"],
                   "samples": o["opus"]["master_samples"], "stats": o["stats"], "cents": o["pitch_cents"], "gain": o["gain_db"]}
                  for o in foley],
        "bus": summary["bus_gains_db"],
        "ir": summary["ir"],
    }
    src_rows = "".join(
        f"<tr><td><a href='{html.escape(r['source_url'])}'>{html.escape(r['id'])}</a></td><td>{html.escape(r['author'])}</td>"
        f"<td>{r['licence']}</td><td>{r['original_format']['codec']} {r['original_format']['sample_rate']}</td>"
        f"<td class='{r['status']}'>{r['status']}</td><td>{html.escape(r.get('status_reason', ''))}</td>"
        f"<td><a href='{html.escape(analysis[r['id']]['spectrogram'])}'>png</a></td></tr>" for r in sources if r["id"] in analysis)
    ir = summary["ir"]
    ir_note = ("<b class='rejected'>SYNTHETIC PLACEHOLDER IR</b>" if ir["synthetic_placeholder"] else
               f"real spike-6 IR <code>{html.escape(ir['source_ir'])}</code> (sha256 {ir['source_ir_sha256'][:12]}…)")
    page = PAGE.replace("__DATA__", json.dumps(data)).replace("__SOURCES__", src_rows).replace("__IR__", ir_note)
    page = page.replace("__LISTEN__", json.dumps(LISTEN)).replace("__BA__", f"{summary['bus_gains_db']['ambience']:+.0f}")
    page = page.replace("__BF__", f"{summary['bus_gains_db']['foley']:+.0f}")
    (BUILD / "index.html").write_text(page)

    # ------------------------------------------------------------ markdown playlist
    md = ["# Listening playlist — spike 7 (audio pipeline)", "",
          "Generated by `pipeline/audio` (`uv run python -I -m audiopipe.page`). Files live in "
          "`data/build/audio/` (gitignored, rebuildable). Listen in Chrome with headphones via the "
          "listening page (`index.html`); see *How to listen* in `bench/m0/spike-7-audio.md`.", "",
          f"Alley IR used: {'SYNTHETIC PLACEHOLDER' if ir['synthetic_placeholder'] else ir['source_ir'] + ' (sha256 ' + ir['source_ir_sha256'][:12] + '…)'}.", "",
          "Sign-off: tick each box (or write a note) and tell Claude. Anything unticked goes back into the pipeline.", "",
          "## 1. Ambience loop", "",
          f"- [ ] `{amb['flac']}` (master) / `{amb['opus']['path']}` (web, {amb['opus']['bytes'] // 1024} KiB)",
          f"  - {fmt_stats(amb['stats'])}",
          f"  - Loop {amb['loop']['loop_len_s']} s, crossfade {amb['loop']['xfade_s']} s, from {amb['loop']['source_offset_s']} s of the layered mix; "
          f"layers: " + ", ".join(f"{l['id']} ({l['gain_db']:+.0f} dB)" for l in amb["layers"]),
          f"  - Seam (master): wrap step {amb['seam']['wrap_jump_dbfs']} dBFS = {amb['seam']['wrap_jump_percentile']}th pct of the file's own sample steps; "
          f"2nd difference {amb['seam']['wrap_second_diff_percentile']}th pct; spectral flux {amb['seam']['wrap_flux_percentile']}th pct. "
          f"Opus decode: exact length {amb['opus']['length_exact']}, seam 2nd diff {amb['opus']['seam']['wrap_second_diff_percentile']}th pct.",
          "  - Listen for:"] + [f"    - {x}" for x in LISTEN["ambience"]] + ["", "## 2. Footstep pool (dress shoes, concrete)", ""]
    for variant, title in (("dry", "Dry takes"), ("wet", "Synthesised wet takes"), ("alley-dry", "Alley (dry takes through the IR)"),
                           ("alley-wet", "Alley (wet takes through the IR)")):
        md += [f"### {title}", "", "Listen for:"] + [f"- {x}" for x in LISTEN['alley' if variant.startswith('alley') else variant]] + [""]
        md += ["| ok | take | file | pitch | gain | M max LUFS | TP dBTP | length |", "|---|---|---|---|---|---|---|---|"]
        for o in foley:
            if o["kind"] == "main" and o["variant"] == variant:
                s = o["stats"]
                md.append(f"| [ ] | {o['take']} | `{o['flac']}` | {o['pitch_cents']:+d} c | {o['gain_db']:+.1f} dB | {s['lufs_m_max']} | {s['true_peak_dbtp']} | {s['duration_s']} s |")
        md.append("")
    md += ["### Alternative pool (A/B only): Yuval 205748, contact mics on the shoes (CC0)", "",
           "- [ ] Prefer this source over the Artninja airborne recording? (`masters/foley/dress-concrete-contactmic/{dry,wet}/`)", ""]
    md += ["## 3. Rejected sources (no need to listen; for the record)", ""]
    for r in sources:
        if r.get("status") == "rejected":
            md.append(f"- `{r['id']}` — {r.get('status_reason')}")
    (repo_root() / "bench" / "m0" / "listening-playlist.md").write_text("\n".join(md) + "\n")
    print(f"wrote {BUILD / 'index.html'} and bench/m0/listening-playlist.md")


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Audio Listening Gate</title>
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
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:6px}
.accepted{color:var(--ok)} .rejected{color:var(--bad)}
ul{margin:4px 0 4px 18px;padding:0} img{max-width:100%;border-radius:6px;margin-top:6px}
.row{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:6px 0}
input[type=range]{width:160px}
</style></head><body><main>
<h1>Audio listening gate — spike 7</h1>
<p class="mut">Use Chrome and headphones. Everything here is generated by <code>pipeline/audio</code>. Alley IR: __IR__.
Codec for all players: <select id="codec"><option value="opus">Opus (web encode)</option><option value="flac">FLAC (master)</option></select></p>

<h2>1. Ambience loop — Shinjuku night street</h2>
<div class="card">
<div class="row"><button id="ambPlay">Play loop (Web Audio, sample-accurate)</button><button id="ambSeam">Jump to 8 s before the wrap</button>
<span id="ambPos" class="mut"></span></div>
<div id="ambInfo" class="mut"></div>
<div class="mut" id="ambLen"></div>
<ul id="ambListen"></ul>
<img src="analysis/loop-seam.png" alt="spectrogram: last 8 s then first 8 s of the loop; the wrap is in the middle">
<div class="mut">Spectrogram: last 8 s, then first 8 s (the wrap is the centre line). There should be no vertical line there.</div>
</div>

<h2>2. Footsteps — dress shoes on concrete</h2>
<div class="card">
<div class="row">Set <select id="var"><option>dry</option><option>wet</option><option>alley-dry</option><option>alley-wet</option></select>
Pool <select id="pool"><option value="dress-concrete">main (Artninja 742969, airborne)</option><option value="dress-concrete-contactmic">alt (Yuval 205748, contact mic; dry/wet only)</option></select>
Cadence <input id="cad" type="range" min="1.2" max="2.6" step="0.1" value="1.8"><span id="cadv"></span>
<label><input type="checkbox" id="withAmb"> over the ambience (bus gains: ambience __BA__ dB, foley __BF__ dB)</label>
<button id="walk">Walk (round-robin, no immediate repeats)</button></div>
<div class="grid" id="takes"></div>
<div class="mut" id="takeInfo">Click a take to play it once.</div>
<ul id="footListen"></ul>
<img src="analysis/pool-dry.png" alt="dry pool"><img src="analysis/pool-wet.png" alt="wet pool">
<img src="analysis/pool-alley-dry.png" alt="alley dry pool"><img src="analysis/pool-alley-wet.png" alt="alley wet pool">
</div>

<h2>3. Sources and quality gate</h2>
<div class="card"><table><tr><th>id</th><th>author</th><th>licence</th><th>original</th><th>gate</th><th>reason</th><th>spectrogram</th></tr>
__SOURCES__</table></div>
</main>
<script>
const D = __DATA__; const LISTEN = __LISTEN__;
let ctx; const cache = {};
function ac(){ if(!ctx) ctx = new AudioContext({sampleRate:48000}); return ctx; }
const codec = () => document.getElementById('codec').value;
async function buf(item){ const url = codec()==='opus' ? item.opus : item.flac;
  if(cache[url]) return cache[url];
  const r = await fetch(url); const b = await ac().decodeAudioData(await r.arrayBuffer()); cache[url]=b; return b; }
const fill=(id,arr)=>{document.getElementById(id).innerHTML=arr.map(x=>'<li>'+x+'</li>').join('')};
fill('ambListen', LISTEN.ambience);
const A = D.ambience;
document.getElementById('ambInfo').textContent =
 `I ${A.stats.lufs_i} LUFS · TP ${A.stats.true_peak_dbtp} dBTP · LRA ${A.stats.lra_lu} LU · loop ${A.loop.loop_len_s} s · xfade ${A.loop.xfade_s} s · seam 2nd-diff pct ${A.seam.wrap_second_diff_percentile} (Opus ${A.opus_seam.wrap_second_diff_percentile})`;
let ambSrc=null, ambGain=null, ambStart=0, ambOffset=0, ambBuf=null, raf=0;
async function ambStartAt(offset, gainDb=0){
  const b = await buf(A); ambBuf=b;
  document.getElementById('ambLen').textContent = `decoded ${b.length} samples, master ${A.samples}: ` + (b.length===A.samples ? 'exact (seamless loop possible)' : 'LENGTH MISMATCH — loop will gap/tick in this browser');
  ambStop(); ambSrc = ac().createBufferSource(); ambSrc.buffer=b; ambSrc.loop=true;
  ambGain = ac().createGain(); ambGain.gain.value = Math.pow(10,gainDb/20);
  ambSrc.connect(ambGain).connect(ac().destination); ambSrc.start(0, offset); ambStart=ac().currentTime; ambOffset=offset;
  document.getElementById('ambPlay').classList.add('on'); tick(); }
function ambStop(){ if(ambSrc){ambSrc.stop(); ambSrc=null;} document.getElementById('ambPlay').classList.remove('on'); cancelAnimationFrame(raf); }
function tick(){ if(!ambSrc||!ambBuf) return; const t=(ambOffset+ac().currentTime-ambStart); const d=ambBuf.duration;
  document.getElementById('ambPos').textContent = `${(t%d).toFixed(1)} / ${d.toFixed(1)} s · wraps ${Math.floor(t/d)}`; raf=requestAnimationFrame(tick); }
document.getElementById('ambPlay').onclick = ()=> ambSrc ? ambStop() : ambStartAt(0);
document.getElementById('ambSeam').onclick = async ()=>{ const b=await buf(A); ambStartAt(Math.max(0,b.duration-8)); };
document.getElementById('codec').onchange = ()=>{ ambStop(); };

const L2 = v => LISTEN[v.startsWith('alley')?'alley':v];
function takes(){ const v=document.getElementById('var').value, p=document.getElementById('pool').value;
  return D.foley.filter(f=>f.pool===p && f.variant===v).sort((a,b)=>a.take-b.take); }
function renderTakes(){ const t=takes(); fill('footListen', L2(document.getElementById('var').value));
  document.getElementById('takes').innerHTML = t.length ? t.map((f,i)=>`<button data-i="${i}">take ${f.take}<br><span class="mut">${f.cents>0?'+':''}${f.cents} c · ${f.gain>0?'+':''}${f.gain} dB</span></button>`).join('') : '<span class="mut">not built for this pool</span>';
  document.querySelectorAll('#takes button').forEach(b=>b.onclick=()=>playTake(t[+b.dataset.i], 0, true)); }
async function playTake(f, when=0, show=false){ const b=await buf(f); const s=ac().createBufferSource(); s.buffer=b;
  const g=ac().createGain(); g.gain.value = document.getElementById('withAmb').checked ? Math.pow(10,D.bus.foley/20) : 1;
  s.connect(g).connect(ac().destination); s.start(when||0);
  if(show) document.getElementById('takeInfo').textContent = `${f.flac} · M max ${f.stats.lufs_m_max} LUFS · TP ${f.stats.true_peak_dbtp} dBTP · ${f.stats.duration_s} s`; }
['var','pool'].forEach(id=>document.getElementById(id).onchange=renderTakes); renderTakes();
const cad=document.getElementById('cad'); const cadv=()=>document.getElementById('cadv').textContent=cad.value+' steps/s'; cad.oninput=cadv; cadv();
let walking=null;
document.getElementById('walk').onclick = async ()=>{
  const btn=document.getElementById('walk');
  if(walking){ clearInterval(walking); walking=null; btn.classList.remove('on'); if(document.getElementById('withAmb').checked) ambStop(); return; }
  const t=takes(); if(!t.length) return; await Promise.all(t.map(buf));
  if(document.getElementById('withAmb').checked) await ambStartAt(0, D.bus.ambience);
  let last=-1, next=ac().currentTime+0.1; btn.classList.add('on');
  walking=setInterval(()=>{ while(next < ac().currentTime+0.25){ let i; do{ i=Math.floor(Math.random()*t.length);}while(i===last && t.length>1); last=i;
      const jitter=(Math.random()-0.5)*0.03; playTake(t[i], next+jitter); next += 1/parseFloat(cad.value);} }, 50); };
</script></body></html>
"""


if __name__ == "__main__":
    main()
