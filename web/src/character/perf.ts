// Frame-time report for the quality tiers (T24): p50 / p95 frame ms and per-pass ms over N frames, on top
// of T19's pass profiler (profile.ts: three's per-render-pass timestamp queries, labelled by render target).
//
// Live: ?perf=1 shows an overlay (bottom left) with the tier, the frame interval (rAF to rAF: what the
// display gets, capped by its refresh), the CPU time of the render call, the GPU time per frame (the sum of
// the frame's pass timestamps) and the top passes; "save" POSTs the report as live_perf.json to /upload/
// (the dev server's sink, web/upload-sink.mjs) or downloads it. Device capture (?capture=1&upload=1) runs the
// same monitor over a fixed rAF-paced loop and then T19's synced measure for a clean per-pass split, and
// uploads <tier>_perf.json (main.ts deviceCapture).
//
// GPU ms need the adapter's timestamp-query (Chrome on Apple silicon has it; Chrome rounds each stamp to
// 0.1 ms unless chrome://flags/#enable-webgpu-developer-features is on, so per-pass p50s are 0.1 ms steps;
// the means are not). Without it every GPU column is null and the per-pass rows are the CPU encode times.
import type { PassProfiler, PassTimes } from './profile';

export interface Dist {
  p50: number;
  p95: number;
  mean: number;
  n: number;
}

export interface PerfReport {
  kind: 'live' | 'loop';
  timestamp_query: boolean;
  source: string;
  frames: number;
  /** rAF to rAF (display paced: 16.7 ms at 60 Hz means "holds 60", not the cost) */
  frame_ms: Dist | null;
  /** wall time of the render call (CPU encode + submit) */
  cpu_render_ms: Dist | null;
  /** sum of the frame's render-pass timestamps */
  gpu_ms: Dist | null;
  passes: { label: string; gpu_ms: Dist | null; cpu_ms: Dist | null; share: number | null }[];
  /** T19's synced measure (profile.ts): each frame waited for, every pass every frame */
  synced?: PassTimes;
}

export function dist(a: number[]): Dist | null {
  if (!a.length) return null;
  const s = [...a].sort((x, y) => x - y);
  const at = (p: number) => s[Math.min(s.length - 1, Math.floor(p * s.length))]!;
  return { p50: +at(0.5).toFixed(3), p95: +at(0.95).toFixed(3), mean: +(a.reduce((x, y) => x + y, 0) / a.length).toFixed(3), n: a.length };
}

export class PerfMonitor {
  private intervals: number[] = [];
  private cpuRender: number[] = [];
  private cpuPass: Record<string, number[]> = {};
  private gpuFrames = new Map<number, Record<string, number>>();
  private last = 0;
  private polling = false;
  private running = false;

  constructor(
    private readonly profiler: PassProfiler,
    private readonly max = 3000,
  ) {}

  get timestampQuery(): boolean {
    return this.profiler.supported;
  }

  start(): void {
    this.intervals = [];
    this.cpuRender = [];
    this.cpuPass = {};
    this.gpuFrames.clear();
    this.last = 0;
    this.running = true;
    this.profiler.takeCpu();
    this.profiler.live(true);
  }

  stop(): void {
    this.running = false;
    this.profiler.live(false);
  }

  /** After each rendered frame: its rAF time and the render call's CPU ms. */
  frame(now: number, cpuMs: number): void {
    if (!this.running) return;
    if (this.last) this.intervals.push(now - this.last);
    this.last = now;
    this.cpuRender.push(cpuMs);
    for (const [k, v] of Object.entries(this.profiler.takeCpu())) (this.cpuPass[k] ??= []).push(v);
    if (this.intervals.length > this.max) this.intervals.shift();
    if (this.cpuRender.length > this.max) this.cpuRender.shift();
    if (this.profiler.supported && !this.polling) {
      this.polling = true;
      void this.poll().finally(() => (this.polling = false));
    }
  }

  private async poll(): Promise<void> {
    const m = await this.profiler.collectGPU();
    for (const [f, rec] of m) {
      const cur = this.gpuFrames.get(f) ?? {};
      for (const [k, v] of Object.entries(rec)) cur[k] = (cur[k] ?? 0) + v;
      this.gpuFrames.set(f, cur);
    }
    while (this.gpuFrames.size > this.max) this.gpuFrames.delete(this.gpuFrames.keys().next().value!);
  }

  /** Wait for the queries in flight (call before report() at the end of a loop). */
  async flush(): Promise<void> {
    while (this.polling) await new Promise((r) => setTimeout(r, 5));
    if (this.profiler.supported) await this.poll();
  }

  report(): PerfReport {
    const frames = [...this.gpuFrames.values()];
    const totals = frames.map((r) => Object.values(r).reduce((x, y) => x + y, 0));
    const labels = new Set<string>([...frames.flatMap((r) => Object.keys(r)), ...Object.keys(this.cpuPass)]);
    const gpuMean = totals.length ? totals.reduce((x, y) => x + y, 0) / totals.length : 0;
    const passes = [...labels].map((label) => {
      const g = frames.map((r) => r[label] ?? 0);
      const gd = this.timestampQuery && frames.length ? dist(g) : null;
      return { label, gpu_ms: gd, cpu_ms: dist(this.cpuPass[label] ?? []), share: gd && gpuMean > 0 ? +(gd.mean / gpuMean).toFixed(3) : null };
    });
    passes.sort((a, b) => (b.gpu_ms?.mean ?? 0) - (a.gpu_ms?.mean ?? 0) || (b.cpu_ms?.mean ?? 0) - (a.cpu_ms?.mean ?? 0));
    return {
      kind: 'loop',
      timestamp_query: this.timestampQuery,
      source: this.timestampQuery ? 'gpu timestamps per render pass (timestamp-query) + CPU encode per pass' : 'no timestamp-query: CPU only (frame interval, render call, encode per pass)',
      frames: this.intervals.length,
      frame_ms: dist(this.intervals),
      cpu_render_ms: dist(this.cpuRender),
      gpu_ms: this.timestampQuery ? dist(totals) : null,
      passes,
    };
  }

  /** Overlay text: the frame numbers and the top passes. */
  text(head: string, top = 10): string {
    const r = this.report();
    const f = (d: Dist | null) => (d ? `p50 ${d.p50.toFixed(2)}  p95 ${d.p95.toFixed(2)}` : 'n/a');
    const lines = [
      head,
      `frame (rAF)   ${f(r.frame_ms)} ms  (${r.frame_ms ? (1000 / r.frame_ms.p50).toFixed(0) : '-'} fps)`,
      `render call   ${f(r.cpu_render_ms)} ms (CPU)`,
      `GPU           ${r.timestamp_query ? `${f(r.gpu_ms)} ms` : 'no timestamp-query'}`,
      `${r.timestamp_query ? 'GPU ms mean (p95)' : 'CPU encode ms mean (p95)'} per pass:`,
    ];
    for (const p of r.passes.slice(0, top)) {
      const d = r.timestamp_query ? p.gpu_ms : p.cpu_ms;
      if (d) lines.push(`  ${d.mean.toFixed(2).padStart(6)} (${d.p95.toFixed(2)})  ${p.label}`);
    }
    return lines.join('\n');
  }
}

/** ?perf=1: the overlay box and its buttons (reset; save = POST /upload/live_perf.json or a download). */
export function perfOverlay(mon: PerfMonitor, head: () => string, meta: () => Record<string, unknown>, session: string): void {
  const box = document.createElement('div');
  box.style.cssText = 'position:fixed;left:8px;bottom:8px;padding:6px 8px;background:rgba(0,0,0,.7);border-radius:4px;white-space:pre;font:11px/1.3 ui-monospace,Menlo,monospace;color:#d8f0d8;max-width:70ch';
  const pre = document.createElement('div');
  const bar = document.createElement('div');
  bar.style.cssText = 'margin-top:4px;display:flex;gap:6px';
  const btn = (label: string, on: () => void) => {
    const b = document.createElement('button');
    b.textContent = label;
    b.style.font = 'inherit';
    b.onclick = on;
    bar.append(b);
    return b;
  };
  btn('reset', () => mon.start());
  const save = btn('save', async () => {
    await mon.flush();
    const body = JSON.stringify({ ...meta(), perf: { ...mon.report(), kind: 'live' } }, null, 1);
    try {
      const r = await fetch(`/upload/live_perf.json?session=${encodeURIComponent(session)}`, { method: 'POST', body, headers: { 'content-type': 'application/json' } });
      if (!r.ok) throw new Error(String(r.status));
      save.textContent = `saved (${session})`;
    } catch {
      const a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([body], { type: 'application/json' }));
      a.download = 'live_perf.json';
      a.click();
      save.textContent = 'downloaded';
    }
  });
  box.append(pre, bar);
  document.body.append(box);
  setInterval(() => (pre.textContent = mon.text(head())), 500);
}

/** A session id for uploads (time-ordered, filesystem-safe). */
export function newSession(): string {
  return new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d+Z$/, 'Z');
}

