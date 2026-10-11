#!/usr/bin/env node
// Summarise telemetry sessions written by bench/server.mjs.
//
//   node bench/summarize.mjs [files or dirs...] [--warmup 300] [--late 1200] [--bucket 300]
//                            [--include-hidden] [--json]
//
// Defaults to every *.jsonl in bench/m0/telemetry. For each session it merges the per-window
// histograms (only windows where the tab stayed visible and focused, after --warmup seconds)
// and prints p50/p95/p99 of the rAF interval, CPU frame time and GPU time, the simulation tick
// costs, and peak memory. --late adds a slice starting at that time (m2: "after 20 min warm-up");
// --bucket prints a per-bucket trend to expose thermal throttling.
import { readFile, readdir, stat } from 'node:fs/promises';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = fileURLToPath(new URL('.', import.meta.url));
const argv = process.argv.slice(2);
const flag = (name, dflt) => {
  const i = argv.indexOf(`--${name}`);
  return i >= 0 ? Number(argv[i + 1]) : dflt;
};
const has = (name) => argv.includes(`--${name}`);
const warmup = flag('warmup', 300);
const late = flag('late', 1200);
const bucket = flag('bucket', 300);
const includeHidden = has('include-hidden');
const asJson = has('json');
const flagsWithValue = new Set(['--warmup', '--late', '--bucket']);
const paths = argv.filter((a, i) => !a.startsWith('--') && !flagsWithValue.has(argv[i - 1]));
if (paths.length === 0) paths.push(join(here, 'm0', 'telemetry'));

const NOMINAL_MS = 1000 / 60;
/** Bins per simulation histogram (core/src/lib.rs HIST_BINS); the last is overflow. */
const SIM_BINS = 256;

class Merged {
  constructor(binMs, nBins = Infinity) {
    this.binMs = binMs;
    this.nBins = nBins;
    this.bins = new Map();
    this.count = 0;
    this.max = 0;
  }
  add(h) {
    if (!h) return;
    if (Math.abs(h.binMs - this.binMs) > 1e-9) throw new Error(`bin width mismatch ${h.binMs} vs ${this.binMs}`);
    if (h.bins) this.nBins = h.bins;
    for (const [i, c] of h.sparse) {
      this.bins.set(i, (this.bins.get(i) ?? 0) + c);
      this.count += c;
    }
    this.max = Math.max(this.max, h.max ?? 0);
  }
  /** Simulation histograms carry no exact max; use the upper edge of the highest bin. */
  addSparse(sparse, nBins) {
    this.nBins = nBins;
    for (const [i, c] of sparse) {
      this.bins.set(i, (this.bins.get(i) ?? 0) + c);
      this.count += c;
      this.max = Math.max(this.max, (i + 1) * this.binMs);
      if (i >= nBins - 1) this.overflow = true;
    }
  }
  q(p) {
    if (!this.count) return null;
    const target = Math.ceil(p * this.count);
    let acc = 0;
    for (const i of [...this.bins.keys()].sort((a, b) => a - b)) {
      acc += this.bins.get(i);
      // The last bin is an overflow bin: report its lower edge as a ">=" bound.
      if (acc >= target) return i >= this.nBins - 1 ? `>=${+(i * this.binMs).toFixed(3)}` : +((i + 1) * this.binMs).toFixed(3);
    }
    return null;
  }
  fractionAbove(ms) {
    if (!this.count) return null;
    let n = 0;
    for (const [i, c] of this.bins) if (i * this.binMs >= ms) n += c;
    return n / this.count;
  }
  stats() {
    const max = this.count ? +this.max.toFixed(2) : null;
    return { n: this.count, p50: this.q(0.5), p95: this.q(0.95), p99: this.q(0.99), max: this.overflow ? `>=${+((this.nBins - 1) * this.binMs).toFixed(3)}` : max };
  }
}

async function listFiles(p) {
  const s = await stat(p);
  if (s.isFile()) return [p];
  return (await readdir(p)).filter((f) => f.endsWith('.jsonl')).map((f) => join(p, f));
}

function summariseSlice(windows, from, to = Infinity) {
  const sel = windows.filter((w) => w.tStartS >= from && w.tEndS <= to);
  if (!sel.length) return null;
  const raf = new Merged(sel[0].raf.binMs);
  const cpu = new Merged(sel[0].cpu.binMs);
  const gpu = sel[0].gpu ? new Merged(sel[0].gpu.binMs) : null;
  const tick = new Merged(sel[0].sim.tickUs.binUs / 1000);
  const phys = new Merged(sel[0].sim.physUs.binUs / 1000);
  const pose = new Merged(sel[0].sim.poseUs.binUs / 1000);
  const interval = new Merged(sel[0].sim.intervalUs.binUs / 1000);
  let frames = 0;
  let ticks = 0;
  let resyncs = 0;
  let catchup = 0;
  let throttled = 0;
  for (const w of sel) {
    raf.add(w.raf);
    cpu.add(w.cpu);
    if (gpu && w.gpu) gpu.add(w.gpu);
    tick.addSparse(w.sim.tickUs.sparse, SIM_BINS);
    phys.addSparse(w.sim.physUs.sparse, SIM_BINS);
    pose.addSparse(w.sim.poseUs.sparse, SIM_BINS);
    interval.addSparse(w.sim.intervalUs.sparse, SIM_BINS);
    frames += w.frames;
    ticks += w.sim.ticks;
    resyncs += w.sim.resyncs;
    catchup += w.sim.catchup;
    if (w.throttleSuspected) throttled++;
  }
  const seconds = sel.reduce((a, w) => a + (w.tEndS - w.tStartS), 0);
  return {
    fromS: from,
    toS: Math.max(...sel.map((w) => w.tEndS)),
    windows: sel.length,
    seconds: +seconds.toFixed(1),
    fps: +(frames / seconds).toFixed(2),
    rafMs: raf.stats(),
    // A frame "missed vsync" when its rAF interval is over 1.5x nominal (60 Hz display).
    missedVsyncFraction: raf.fractionAbove(NOMINAL_MS * 1.5),
    cpuMs: cpu.stats(),
    gpuMs: gpu ? gpu.stats() : null,
    sim: {
      hz: +(ticks / seconds).toFixed(2),
      tickMs: tick.stats(),
      physicsMs: phys.stats(),
      poseMs: pose.stats(),
      tickIntervalMs: interval.stats(),
      resyncs,
      catchupTicks: catchup,
    },
    throttleSuspectedWindows: throttled,
  };
}

const sessions = new Map();
for (const p of paths) {
  for (const f of await listFiles(p)) {
    for (const line of (await readFile(f, 'utf8')).split('\n')) {
      if (!line.trim()) continue;
      let r;
      try {
        r = JSON.parse(line);
      } catch {
        continue;
      }
      if (!sessions.has(r.session)) sessions.set(r.session, { meta: null, windows: [] });
      const s = sessions.get(r.session);
      if (r.type === 'meta') s.meta = r;
      else if (r.type === 'window') s.windows.push(r);
    }
  }
}

const results = [];
for (const [id, s] of [...sessions].sort()) {
  const all = s.windows.sort((a, b) => a.seq - b.seq);
  const usable = all.filter((w) => includeHidden || (w.visible && w.focused));
  const peak = (f) => all.reduce((m, w) => Math.max(m, f(w) ?? 0), 0);
  const buckets = [];
  const end = Math.max(0, ...usable.map((w) => w.tEndS));
  for (let b = 0; b < end; b += bucket) {
    const sl = summariseSlice(usable, b, b + bucket);
    if (sl) buckets.push({ fromS: b, fps: sl.fps, rafP95: sl.rafMs.p95, cpuP50: sl.cpuMs.p50, cpuP95: sl.cpuMs.p95, gpuP50: sl.gpuMs?.p50 ?? null, gpuP95: sl.gpuMs?.p95 ?? null, tickP95: sl.sim.tickMs.p95 });
  }
  const m = s.meta;
  results.push({
    session: id,
    label: m?.label ?? '',
    backend: m?.backend,
    adapter: m?.gpu?.adapterInfo,
    features: m?.gpu?.wanted,
    ua: m?.env?.userAgent,
    battery: m?.env?.battery,
    canvas: m?.render?.canvas,
    pixelRatio: m?.render?.pixelRatio,
    durationS: end,
    windows: { total: all.length, usable: usable.length, excludedHiddenOrBlurred: all.length - usable.length },
    afterWarmup: summariseSlice(usable, warmup),
    late: summariseSlice(usable, late),
    peakMemory: {
      uasmBytes: peak((w) => w.mem?.uasm?.bytes),
      jsHeapUsedBytes: peak((w) => w.mem?.jsHeapUsed),
      wasmBytes: peak((w) => w.mem?.wasmBytes),
    },
    buckets,
  });
}

if (asJson) {
  console.log(JSON.stringify(results, null, 2));
} else {
  const mb = (b) => (b ? `${(b / 2 ** 20).toFixed(1)} MiB` : 'n/a');
  const ps = (x) => (x ? `p50 ${x.p50} / p95 ${x.p95} / p99 ${x.p99} / max ${x.max} (n=${x.n})` : 'n/a');
  for (const r of results) {
    console.log(`\n=== ${r.session} ${r.label ? `[${r.label}]` : ''}`);
    console.log(`backend ${r.backend}  adapter ${JSON.stringify(r.adapter)}  canvas ${r.canvas} @${r.pixelRatio}`);
    console.log(`features ${JSON.stringify(r.features)}  battery ${JSON.stringify(r.battery)}`);
    console.log(`duration ${r.durationS.toFixed(0)} s  windows ${r.windows.usable}/${r.windows.total} usable`);
    for (const [name, sl] of [
      [`after warm-up (t >= ${warmup} s)`, r.afterWarmup],
      [`late (t >= ${late} s)`, r.late],
    ]) {
      if (!sl) {
        console.log(`-- ${name}: no data`);
        continue;
      }
      console.log(`-- ${name}: ${sl.seconds} s, ${sl.fps} fps, missed-vsync ${(100 * (sl.missedVsyncFraction ?? 0)).toFixed(2)}%`);
      console.log(`   rAF interval ms  ${ps(sl.rafMs)}`);
      console.log(`   CPU frame ms     ${ps(sl.cpuMs)}`);
      console.log(`   GPU ms           ${ps(sl.gpuMs)}`);
      console.log(`   sim ${sl.sim.hz} Hz  tick ms ${ps(sl.sim.tickMs)}`);
      console.log(`   physics ms ${ps(sl.sim.physicsMs)}`);
      console.log(`   pose ms    ${ps(sl.sim.poseMs)}`);
      console.log(`   tick interval ms ${ps(sl.sim.tickIntervalMs)}  resyncs ${sl.sim.resyncs} catch-up ${sl.sim.catchupTicks}`);
    }
    console.log(`peak memory: measureUserAgentSpecificMemory ${mb(r.peakMemory.uasmBytes)}, JS heap ${mb(r.peakMemory.jsHeapUsedBytes)}, WASM ${mb(r.peakMemory.wasmBytes)}`);
    if (r.buckets.length > 1) {
      console.log(`trend per ${bucket} s: from  fps  rAFp95  CPUp50  CPUp95  GPUp50  GPUp95  tickP95`);
      for (const b of r.buckets) console.log(`   ${String(b.fromS).padStart(5)}  ${b.fps}  ${b.rafP95}  ${b.cpuP50}  ${b.cpuP95}  ${b.gpuP50}  ${b.gpuP95}  ${b.tickP95}`);
    }
  }
  if (!results.length) console.log('no sessions found');
}
