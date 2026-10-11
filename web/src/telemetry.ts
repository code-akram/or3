// Frame/memory telemetry: fixed-bin histograms, periodic window records POSTed to the bench
// server (bench/server.mjs), and an on-screen frame-time graph.

/** Fixed-width histogram in milliseconds. The last bin collects overflow. */
export class Hist {
  readonly bins: Uint32Array;
  count = 0;
  sum = 0;
  max = 0;

  constructor(
    readonly binMs: number,
    readonly n: number,
  ) {
    this.bins = new Uint32Array(n);
  }

  add(ms: number): void {
    const i = Math.min(this.n - 1, Math.max(0, Math.floor(ms / this.binMs)));
    this.bins[i] = (this.bins[i] ?? 0) + 1;
    this.count++;
    this.sum += ms;
    if (ms > this.max) this.max = ms;
  }

  /** Upper edge of the bin containing quantile `q` (0..1). */
  quantile(q: number): number {
    if (this.count === 0) return 0;
    const target = Math.ceil(q * this.count);
    let acc = 0;
    for (let i = 0; i < this.n; i++) {
      acc += this.bins[i] ?? 0;
      if (acc >= target) return (i + 1) * this.binMs;
    }
    return this.n * this.binMs;
  }

  summary(): HistSummary {
    return {
      binMs: this.binMs,
      bins: this.n,
      count: this.count,
      mean: this.count ? this.sum / this.count : 0,
      max: this.max,
      p50: this.quantile(0.5),
      p95: this.quantile(0.95),
      p99: this.quantile(0.99),
      sparse: sparse(this.bins),
    };
  }

  reset(): void {
    this.bins.fill(0);
    this.count = 0;
    this.sum = 0;
    this.max = 0;
  }
}

export interface HistSummary {
  binMs: number;
  /** Number of bins; the last one is the overflow bin. */
  bins: number;
  count: number;
  mean: number;
  max: number;
  p50: number;
  p95: number;
  p99: number;
  /** [binIndex, count] pairs for non-empty bins. */
  sparse: [number, number][];
}

export function sparse(bins: ArrayLike<number>): [number, number][] {
  const out: [number, number][] = [];
  for (let i = 0; i < bins.length; i++) {
    const c = bins[i] ?? 0;
    if (c > 0) out.push([i, c]);
  }
  return out;
}

export function makeSessionId(): string {
  const d = new Date();
  const stamp = d.toISOString().replace(/[-:]/g, '').replace(/\..*$/, '');
  const rand = Math.random().toString(36).slice(2, 8);
  return `${stamp}-${rand}`;
}

export class Poster {
  ok = 0;
  failed = 0;
  lastError = '';

  constructor(
    readonly session: string,
    readonly endpoint = '/telemetry',
  ) {}

  send(record: Record<string, unknown>, beacon = false): void {
    const body = JSON.stringify({ session: this.session, sentAt: Date.now(), ...record });
    if (beacon && navigator.sendBeacon(this.endpoint, body)) {
      this.ok++;
      return;
    }
    fetch(this.endpoint, { method: 'POST', body, keepalive: body.length < 60000, headers: { 'content-type': 'application/json' } })
      .then((r) => {
        if (r.ok) this.ok++;
        else {
          this.failed++;
          this.lastError = `HTTP ${r.status}`;
        }
      })
      .catch((e: unknown) => {
        this.failed++;
        this.lastError = String(e);
      });
  }
}

/** Rolling frame-time graph: rAF interval, CPU frame time, GPU time. */
export class Graph {
  private readonly ctx: CanvasRenderingContext2D;
  private readonly raf: Float32Array;
  private readonly cpu: Float32Array;
  private readonly gpu: Float32Array;
  private head = 0;

  constructor(
    private readonly canvas: HTMLCanvasElement,
    readonly length = 360,
    readonly maxMs = 33.3,
  ) {
    const ctx = canvas.getContext('2d');
    if (!ctx) throw new Error('2D canvas unavailable');
    this.ctx = ctx;
    this.raf = new Float32Array(length);
    this.cpu = new Float32Array(length);
    this.gpu = new Float32Array(length).fill(Number.NaN);
  }

  push(rafMs: number, cpuMs: number, gpuMs: number): void {
    this.raf[this.head] = rafMs;
    this.cpu[this.head] = cpuMs;
    this.gpu[this.head] = gpuMs;
    this.head = (this.head + 1) % this.length;
  }

  draw(): void {
    const { ctx, canvas, length, maxMs } = this;
    const w = canvas.width;
    const h = canvas.height;
    ctx.clearRect(0, 0, w, h);
    const y = (ms: number) => h - (Math.min(ms, maxMs) / maxMs) * h;
    ctx.lineWidth = 1;
    for (const [ms, color] of [
      [16.67, '#ff4d6d'],
      [12, '#ffb000'],
    ] as const) {
      ctx.strokeStyle = color;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(0, y(ms));
      ctx.lineTo(w, y(ms));
      ctx.stroke();
    }
    ctx.setLineDash([]);
    const series: [Float32Array, string][] = [
      [this.raf, '#8aa0ff'],
      [this.cpu, '#2ee6c8'],
      [this.gpu, '#ff5cf0'],
    ];
    ctx.lineWidth = 2;
    for (const [data, color] of series) {
      ctx.strokeStyle = color;
      ctx.beginPath();
      let pen = false;
      for (let i = 0; i < length; i++) {
        const v = data[(this.head + i) % length] ?? Number.NaN;
        const x = (i / (length - 1)) * w;
        if (Number.isNaN(v)) {
          pen = false;
          continue;
        }
        if (pen) ctx.lineTo(x, y(v));
        else ctx.moveTo(x, y(v));
        pen = true;
      }
      ctx.stroke();
    }
    ctx.fillStyle = '#d8d8e0';
    ctx.font = '20px ui-monospace, monospace';
    ctx.fillText('rAF', 8, 22);
    ctx.fillStyle = '#2ee6c8';
    ctx.fillText('CPU', 60, 22);
    ctx.fillStyle = '#ff5cf0';
    ctx.fillText('GPU', 112, 22);
    ctx.fillStyle = '#d8d8e0';
    ctx.fillText(`${maxMs.toFixed(0)} ms`, w - 80, 22);
  }
}
