// Sampled-texture audit per material and pass (G1). WebGPU's default limit is 16 sampled textures per shader
// stage; a pipeline over the adapter's limit fails to compile and the mesh draws nothing (T17's black skin
// at 17, T24's eyes at 18 in the live hero portrait). Every texture counts: the material's own maps, the
// LUTs, every shadow map the lights it receives sample (twins share their parent's), the screen textures
// (GTAO, contact shadows) and array textures (one binding however many layers).
//
// installTextureAudit(renderer) wraps three's node manager: every pipeline state the renderer builds is
// counted once, from its generated shader (`: texture_` declarations in the fragment and vertex WGSL, not
// storage textures) with the texture names from its bindings. The count is always on (one regex per new
// pipeline): a state over the limit is a dev assertion, a console error and a viewer warning naming the
// material, the object and the count. `?texcheck=1` lists the materials at 12 or more in the HUD and puts
// the full table (every material, its maximum over its pipelines, the textures by name) in
// stats().texture_audit, so a capture's <prefix>shots.json carries it; __viewer.textureAudit() returns it
// any time.
import type * as THREE from 'three/webgpu';

export interface TexAuditRow {
  material: string;
  object: string;
  /** which pass built it: main (the frame), shadow (a depth map), or the camera's type otherwise */
  pass: string;
  fragment: number;
  vertex: number;
  samplers: number;
  /** size of the fragment WGSL (a complexity proxy) and its loops */
  fragment_chars: number;
  fragment_loops: number;
  textures: string[];
}

export interface TexAuditReport {
  limit: number;
  /** per material: the pipeline with the most fragment textures */
  materials: TexAuditRow[];
  over: TexAuditRow[];
  pipelines: number;
}

const TEX_DECL = /:\s*texture_(?!storage)[a-z_0-9]+(<[^>]*>)?\s*;/g;
const SAMPLER_DECL = /:\s*sampler(_comparison)?\s*;/g;

/* eslint-disable @typescript-eslint/no-explicit-any */
function textureName(t: any): string {
  if (!t) return '?';
  const img = t.image ?? {};
  const size = img.width && img.height ? ` ${img.width}x${img.height}${t.isDataArrayTexture || t.isArrayTexture ? `x${img.depth}` : ''}` : '';
  const kind = t.isDepthTexture ? 'depth' : t.isRenderTargetTexture ? 'rt' : t.isCompressedTexture ? 'ktx2' : t.isDataArrayTexture ? 'array' : t.isCubeTexture ? 'cube' : t.isData3DTexture ? '3d' : t.isDataTexture ? 'data' : 'tex';
  // unnamed data textures (LUTs) by element type and id, so duplicates of one table show as such
  const type = t.type === 1015 ? ' f32' : t.type === 1016 ? ' f16' : '';
  const id = t.name ? '' : ` #${String(t.uuid ?? t.id ?? '').slice(0, 6)}`;
  return `${t.name || '(unnamed)'} [${kind}${size}${type}]${id}`;
}

export class TextureAudit {
  private readonly seen = new WeakSet<object>();
  readonly rows: TexAuditRow[] = [];
  readonly over: TexAuditRow[] = [];

  constructor(
    readonly limit: number,
    private readonly onOver: (row: TexAuditRow) => void,
    private readonly passOf: (camera: THREE.Camera | null) => string,
  ) {}

  record(renderObject: any, state: any): void {
    if (!state || this.seen.has(state)) return;
    this.seen.add(state);
    const frag = typeof state.fragmentShader === 'string' ? state.fragmentShader : '';
    const vert = typeof state.vertexShader === 'string' ? state.vertexShader : '';
    if (!frag.includes('@fragment') && !vert.includes('@vertex')) return; // GLSL (WebGL2): not audited
    const names: string[] = [];
    for (const group of state.bindings ?? []) {
      for (const b of group.bindings ?? []) {
        if (!b.isSampledTexture || b.store) continue;
        if (((b.visibility ?? 0) & 2) === 0) continue; // GPUShaderStage.FRAGMENT
        names.push(`${b.name}: ${textureName(b.texture)}`);
      }
    }
    const row: TexAuditRow = {
      material: renderObject?.material?.name || renderObject?.material?.type || '?',
      object: renderObject?.object?.name || renderObject?.object?.type || '?',
      pass: this.passOf(renderObject?.camera ?? null),
      fragment: (frag.match(TEX_DECL) ?? []).length,
      vertex: (vert.match(TEX_DECL) ?? []).length,
      samplers: (frag.match(SAMPLER_DECL) ?? []).length,
      fragment_chars: frag.length,
      fragment_loops: (frag.match(/\bfor\s*\(/g) ?? []).length,
      textures: names,
    };
    this.rows.push(row);
    if (row.fragment > this.limit || row.vertex > this.limit) {
      this.over.push(row);
      this.onOver(row);
    }
  }

  report(): TexAuditReport {
    const best = new Map<string, TexAuditRow>();
    for (const r of this.rows) {
      const k = `${r.material}|${r.pass}`;
      const b = best.get(k);
      if (!b || r.fragment > b.fragment) best.set(k, r);
    }
    const materials = [...best.values()].sort((a, b) => b.fragment - a.fragment || a.material.localeCompare(b.material));
    return { limit: this.limit, materials, over: this.over, pipelines: this.rows.length };
  }
}

/** Wrap the renderer's node manager so every new pipeline state is counted (call after renderer.init()). */
export function installTextureAudit(renderer: THREE.WebGPURenderer, audit: TextureAudit): boolean {
  const nodes = (renderer as any)._nodes;
  if (!nodes || typeof nodes.getForRender !== 'function') return false;
  const orig = nodes.getForRender.bind(nodes);
  nodes.getForRender = (renderObject: any, useAsync = false) => {
    const r = orig(renderObject, useAsync);
    if (r && typeof r.then === 'function') return r.then((s: any) => (audit.record(renderObject, s), s));
    audit.record(renderObject, r);
    return r;
  };
  return true;
}

// --------------------------------------------------------------------------------------- texture memory

/** Bytes per texel (block formats: per 4x4 block / 16) of the WebGPU formats the viewer allocates. */
function bytesPerTexel(format: string): number {
  if (/^(bc1|bc4|etc2-rgb8unorm|etc2-rgb8a1|eac-r11)/.test(format)) return 0.5;
  if (/^(bc[2357]|bc6h|etc2-rgba8|eac-rg11|astc-4x4)/.test(format)) return 1;
  const astc = format.match(/^astc-(\d+)x(\d+)/);
  if (astc) return 16 / (Number(astc[1]) * Number(astc[2]));
  if (format === 'depth24plus-stencil8') return 5;
  if (/^(r8|stencil8)/.test(format)) return 1;
  if (/^(rg8|r16|depth16)/.test(format)) return 2;
  if (/^(rgba16|rg32|depth32float-stencil8)/.test(format)) return 8;
  if (/^rgba32/.test(format)) return 16;
  return 4; // rgba8 / bgra8 / rg16 / r32 / rgb10a2 / rg11b10 / depth24plus / depth32float
}

export interface TexMemRow {
  name: string;
  kind: 'material' | 'target';
  format: string;
  size: number[];
  mips: number;
  mb: number;
}

/** Live GPU textures (renderer.info's create / destroy hooks) and their exact GPU sizes from the backend's
 * GPUTexture (format, mips, layers, samples). `material` = sampled assets (GLB maps, sidecars, LUTs);
 * `target` = render targets and depth (shadow maps, the MRT, AO, history). */
export class TextureMemory {
  private readonly live = new Set<THREE.Texture>();

  constructor(private readonly renderer: THREE.WebGPURenderer) {
    const info = renderer.info as any;
    const create = info.createTexture.bind(info);
    const destroy = info.destroyTexture.bind(info);
    info.createTexture = (t: THREE.Texture) => {
      this.live.add(t);
      create(t);
    };
    info.destroyTexture = (t: THREE.Texture) => {
      this.live.delete(t);
      destroy(t);
    };
  }

  rows(): TexMemRow[] {
    const backend = (this.renderer as any).backend;
    const out: TexMemRow[] = [];
    for (const t of this.live) {
      const g = backend?.get?.(t)?.texture as { width: number; height: number; depthOrArrayLayers: number; mipLevelCount: number; sampleCount: number; format: string } | undefined;
      if (!g || !g.format) continue;
      const bpt = bytesPerTexel(g.format);
      const block = /^(bc|etc|eac|astc)/.test(g.format);
      let bytes = 0;
      for (let l = 0; l < g.mipLevelCount; l++) {
        const w = Math.max(1, g.width >> l);
        const h = Math.max(1, g.height >> l);
        const texels = block ? Math.ceil(w / 4) * 4 * Math.ceil(h / 4) * 4 : w * h;
        bytes += texels * bpt * g.depthOrArrayLayers * (g.sampleCount || 1);
      }
      const a = t as any;
      out.push({
        name: t.name || (a.isDepthTexture ? 'depth' : '(unnamed)'),
        kind: a.isRenderTargetTexture || a.isDepthTexture || a.isFramebufferTexture ? 'target' : 'material',
        format: g.format,
        size: [g.width, g.height, g.depthOrArrayLayers],
        mips: g.mipLevelCount,
        mb: +(bytes / 1e6).toFixed(3),
      });
    }
    return out.sort((x, y) => y.mb - x.mb);
  }

  report(top = 40): { material_mb: number; target_mb: number; material_count: number; target_count: number; formats: Record<string, number>; top: TexMemRow[] } {
    const rows = this.rows();
    const sum = (k: string) => +rows.filter((r) => r.kind === k).reduce((s, r) => s + r.mb, 0).toFixed(1);
    const formats: Record<string, number> = {};
    for (const r of rows) if (r.kind === 'material') formats[r.format] = +((formats[r.format] ?? 0) + r.mb).toFixed(1);
    return { material_mb: sum('material'), target_mb: sum('target'), material_count: rows.filter((r) => r.kind === 'material').length, target_count: rows.filter((r) => r.kind === 'target').length, formats, top: rows.slice(0, top) };
  }
}
