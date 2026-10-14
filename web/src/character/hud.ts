// Perf telemetry stub: frame time, draw calls, triangles, an estimate of texture memory.
// Visibility only, not a benchmark (the bench ladder in NOTES §15 measures m2 on the Air).
import * as THREE from 'three/webgpu';

export function textureBytes(root: THREE.Object3D): { count: number; bytes: number } {
  const seen = new Set<THREE.Texture>();
  root.traverse((o) => {
    const m = (o as THREE.Mesh).material;
    if (!m) return;
    for (const mat of Array.isArray(m) ? m : [m]) {
      for (const v of Object.values(mat as unknown as Record<string, unknown>)) {
        if (v && (v as THREE.Texture).isTexture) seen.add(v as THREE.Texture);
      }
    }
  });
  let bytes = 0;
  for (const t of seen) {
    const img = t.image as { width?: number; height?: number } | undefined;
    if (!img?.width || !img.height) continue;
    // RGBA8, full mip chain (+1/3); no GPU compression yet (KTX2 is a later step)
    bytes += img.width * img.height * 4 * (t.generateMipmaps ? 4 / 3 : 1);
  }
  return { count: seen.size, bytes };
}

export class FrameStats {
  private readonly ms: number[] = [];
  private last = 0;

  tick(now: number): void {
    if (this.last) {
      this.ms.push(now - this.last);
      if (this.ms.length > 120) this.ms.shift();
    }
    this.last = now;
  }

  summary(): { p50: number; p95: number; fps: number } {
    if (!this.ms.length) return { p50: 0, p95: 0, fps: 0 };
    const s = [...this.ms].sort((a, b) => a - b);
    const q = (p: number) => s[Math.min(s.length - 1, Math.floor(p * s.length))] ?? 0;
    const p50 = q(0.5);
    return { p50, p95: q(0.95), fps: p50 ? 1000 / p50 : 0 };
  }
}
