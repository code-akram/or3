// Per-pass GPU times (T19, for T24's quality tiers): three's WebGPU backend writes a timestamp pair around
// every render pass when the renderer was made with trackTimestamp (the timestamp-query feature) and keeps
// the duration of each by its render-context uid after resolveTimestampsAsync(). This labels every pass as
// it begins (from its render target and camera: the shadow map of a light, the GTAO prepass, the scene,
// the temporal resolve, ...) and sums the durations per label over a few frames.
//
// No timestamp-query on the adapter: `supported` false and only the CPU wall time per frame (which, on
// SwiftShader, is the GPU time: the "GPU" is the CPU and the readback waits for it).
import type * as THREE from 'three/webgpu';

/* eslint-disable @typescript-eslint/no-explicit-any */

export interface PassTimes {
  supported: boolean;
  frames: number;
  /** per label: median over the frames of that label's summed ms per frame, and its pass count per frame */
  passes: { label: string; ms_p50: number; ms_mean: number; passes_per_frame: number }[];
  gpu_total_ms_p50: number | null;
  cpu_frame_ms_p50: number;
  note: string;
}

export class PassProfiler {
  private labels = new Map<string, string>();
  private on = false;
  private readonly backend: any;

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
        if (uid) this.labels.set(uid, this.name(rc.renderTarget ?? null, rc.camera ?? null));
      }
      return orig(rc);
    };
  }

  get supported(): boolean {
    const r = this.renderer as any;
    return !!(r.backend?.trackTimestamp && r.hasFeature?.('timestamp-query'));
  }

  /** Run `frame` n times (each followed by a GPU sync) and return the per-label times. */
  async measure(frame: () => void, n: number, sync: () => Promise<unknown>): Promise<PassTimes> {
    const per: Record<string, number[]> = {};
    const counts: Record<string, number[]> = {};
    const totals: number[] = [];
    const cpu: number[] = [];
    const sup = this.supported;
    for (let i = 0; i < n; i++) {
      if (sup) await this.renderer.resolveTimestampsAsync('render' as never); // drop older queries
      this.labels.clear();
      this.on = true;
      const t = performance.now();
      frame();
      await sync();
      cpu.push(performance.now() - t);
      this.on = false;
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
    const med = (a: number[]) => (a.length ? [...a].sort((x, y) => x - y)[Math.floor(a.length / 2)]! : 0);
    const mean = (a: number[]) => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : 0);
    const passes = Object.keys(per)
      .map((label) => ({ label, ms_p50: +med(per[label]!).toFixed(3), ms_mean: +mean(per[label]!).toFixed(3), passes_per_frame: +mean(counts[label]!).toFixed(2) }))
      .sort((a, b) => b.ms_p50 - a.ms_p50);
    return {
      supported: sup,
      frames: n,
      passes,
      gpu_total_ms_p50: sup ? +med(totals).toFixed(3) : null,
      cpu_frame_ms_p50: +med(cpu).toFixed(2),
      note: sup ? 'GPU timestamps per render pass (timestamp-query), labelled by target / camera' : 'no timestamp-query: CPU wall time per synced frame only',
    };
  }
}
