// Per-pass GPU times (T19, for T24's quality tiers): three's WebGPU backend writes a timestamp pair around
// every render pass when the renderer was made with trackTimestamp (the timestamp-query feature) and keeps
// the duration of each by its render-context uid after resolveTimestampsAsync(). This labels every pass as
// it begins (from its render target and camera: the shadow map of a light, the GTAO prepass, the scene,
// the temporal resolve, ...) and sums the durations per label over a few frames.
//
// No timestamp-query on the adapter: `supported` false and only the CPU wall time per frame (which, on
// SwiftShader, is the GPU time: the "GPU" is the CPU and the readback waits for it).
//
// T24 additions: the CPU fallback per pass (the wall time between the backend's beginRender and
// finishRender of each pass, exclusive of the passes nested in it, e.g. a shadow map inside the scene
// pass: the encode cost, not the GPU's), p95 per label, and a live mode for perf.ts (every pass labelled
// while the viewer runs; collectGPU() resolves what has been written and returns it per frame).
import type * as THREE from 'three/webgpu';

/* eslint-disable @typescript-eslint/no-explicit-any */

export interface PassTimes {
  supported: boolean;
  frames: number;
  /** per label: median over the frames of that label's summed ms per frame, and its pass count per frame */
  passes: { label: string; ms_p50: number; ms_p95: number; ms_mean: number; passes_per_frame: number; cpu_ms_p50: number }[];
  gpu_total_ms_p50: number | null;
  cpu_frame_ms_p50: number;
  note: string;
}

export class PassProfiler {
  private labels = new Map<string, string>();
  private on = false;
  private readonly backend: any;
  /** CPU encode ms per label since the last takeCpu() (exclusive of nested passes) */
  private cpu: Record<string, number> = {};
  private readonly stack: { label: string; t0: number; child: number }[] = [];

  constructor(
    private readonly renderer: THREE.WebGPURenderer,
    private readonly name: (renderTarget: THREE.RenderTarget | null, camera: THREE.Camera | null) => string,
  ) {
    this.backend = (renderer as any).backend;
    const b = this.backend;
    if (!b || typeof b.beginRender !== 'function' || b.__t19Profiled) return;
    b.__t19Profiled = true;
    const orig = b.beginRender.bind(b);
    b.beginRender = (rc: any) => {
      if (this.on) {
        const uid = b.get(rc)?.timestampUID as string | undefined;
        const label = this.name(rc.renderTarget ?? null, rc.camera ?? null);
        if (uid) this.labels.set(uid, label);
        this.stack.push({ label, t0: performance.now(), child: 0 });
      }
      return orig(rc);
    };
    const origFinish = b.finishRender.bind(b);
    b.finishRender = (rc: any) => {
      const r = origFinish(rc);
      const top = this.stack.pop();
      if (top) {
        const dur = performance.now() - top.t0;
        this.cpu[top.label] = (this.cpu[top.label] ?? 0) + dur - top.child;
        const parent = this.stack[this.stack.length - 1];
        if (parent) parent.child += dur;
      }
      return r;
    };
  }

  /** CPU encode ms per label since the last call (CPU fallback; the GPU time needs timestamp-query). */
  takeCpu(): Record<string, number> {
    const c = this.cpu;
    this.cpu = {};
    return c;
  }

  /** perf.ts: label every pass from now on (live), or stop. */
  live(on: boolean): void {
    this.on = on;
    this.stack.length = 0;
    if (!on) this.labels.clear();
  }

  /** perf.ts: resolve the timestamps written since the last resolve; per frame id (three's info.frame,
   * one per animation frame), the GPU ms summed per label. Empty without timestamp-query. */
  async collectGPU(): Promise<Map<number, Record<string, number>>> {
    const out = new Map<number, Record<string, number>>();
    if (!this.supported) return out;
    await this.renderer.resolveTimestampsAsync('render' as never);
    const ts: Map<string, number> = this.backend.timestampQueryPool?.render?.timestamps ?? new Map();
    for (const [uid, ms] of ts) {
      const m = /:f(\d+)$/.exec(uid);
      if (!m) continue;
      const f = Number(m[1]);
      const lab = this.labels.get(uid) ?? 'other';
      this.labels.delete(uid);
      const rec = out.get(f) ?? {};
      rec[lab] = (rec[lab] ?? 0) + ms;
      out.set(f, rec);
    }
    if (this.labels.size > 20000) this.labels.clear(); // queries the pool dropped (overflow)
    return out;
  }

  get supported(): boolean {
    const r = this.renderer as any;
    return !!(r.backend?.trackTimestamp && r.hasFeature?.('timestamp-query'));
  }

  /** Run `frame` n times (each followed by a GPU sync) and return the per-label times. */
  async measure(frame: () => void, n: number, sync: () => Promise<unknown>): Promise<PassTimes> {
    const per: Record<string, number[]> = {};
    const cpuPer: Record<string, number[]> = {};
    const counts: Record<string, number[]> = {};
    const totals: number[] = [];
    const cpu: number[] = [];
    const sup = this.supported;
    for (let i = 0; i < n; i++) {
      if (sup) await this.renderer.resolveTimestampsAsync('render' as never); // drop older queries
      this.labels.clear();
      this.takeCpu();
      this.on = true;
      const t = performance.now();
      frame();
      await sync();
      cpu.push(performance.now() - t);
      this.on = false;
      this.stack.length = 0;
      for (const [k, v] of Object.entries(this.takeCpu())) (cpuPer[k] ??= []).push(v);
      if (!sup) continue;
      const total = (await this.renderer.resolveTimestampsAsync('render' as never)) as number;
      const pool = this.backend.timestampQueryPool?.render;
      const ts: Map<string, number> = pool?.timestamps ?? new Map();
      const sum: Record<string, number> = {};
      const cnt: Record<string, number> = {};
      for (const [uid, ms] of ts) {
        const lab = this.labels.get(uid) ?? 'other';
        sum[lab] = (sum[lab] ?? 0) + ms;
        cnt[lab] = (cnt[lab] ?? 0) + 1;
      }
      for (const k of Object.keys(sum)) {
        (per[k] ??= []).push(sum[k]!);
        (counts[k] ??= []).push(cnt[k]!);
      }
      if (typeof total === 'number') totals.push(total);
    }
    const pct = (a: number[], p: number) => (a.length ? [...a].sort((x, y) => x - y)[Math.min(a.length - 1, Math.floor(p * a.length))]! : 0);
    const med = (a: number[]) => pct(a, 0.5);
    const mean = (a: number[]) => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : 0);
    // without timestamp-query the labels come from the CPU side (encode ms), the GPU columns are 0
    const passes = Object.keys(sup ? per : cpuPer)
      .map((label) => ({
        label,
        ms_p50: +med(per[label] ?? []).toFixed(3),
        ms_p95: +pct(per[label] ?? [], 0.95).toFixed(3),
        ms_mean: +mean(per[label] ?? []).toFixed(3),
        passes_per_frame: +mean(counts[label] ?? []).toFixed(2),
        cpu_ms_p50: +med(cpuPer[label] ?? []).toFixed(3),
      }))
      .sort((a, b) => b.ms_p50 - a.ms_p50 || b.cpu_ms_p50 - a.cpu_ms_p50);
    return {
      supported: sup,
      frames: n,
      passes,
      gpu_total_ms_p50: sup ? +med(totals).toFixed(3) : null,
      cpu_frame_ms_p50: +med(cpu).toFixed(2),
      note: sup ? 'GPU timestamps per render pass (timestamp-query), labelled by target / camera; cpu_ms = encode time' : 'no timestamp-query: CPU wall time per synced frame, and per pass the CPU encode time (cpu_ms_p50) only',
    };
  }
}
