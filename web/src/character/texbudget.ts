// Sampled-texture AND sampler budget per shader stage (T18b). WebGPU's default maxSampledTexturesPerShaderStage is
// 16, and SwiftShader (and possibly the Air) offers no more: a pipeline that binds 17 fails to compile and
// its mesh does not draw (T24: the hero eye bound 18 under the hero rig's 5 PCSS maps). This audit records
// every render object a frame draws (scene MRT, shadow maps, the AO prepass, the hair prepass twins) and
// counts the sampled textures each pipeline binds per stage from its node-builder bindings, the same
// bind-group layouts three hands to WebGPU. `__viewer.textureAudit()` (main.ts) renders the views asked for
// with it installed; `engine_shots.mjs --texcheck` fails when any pipeline is over the limit.
import type * as THREE from 'three/webgpu';

/* eslint-disable @typescript-eslint/no-explicit-any */

/** GPUShaderStage bits (the constants are not on the global in every context). */
const VERTEX = 1;
const FRAGMENT = 2;

export interface TextureUse {
  material: string;
  object: string;
  /** the render target the pass drew into (shadow map, AO prepass, scene MRT, ...) */
  pass: string;
  fragment: number;
  vertex: number;
  /** samplers bound in the fragment / vertex stage (WebGPU's maxSamplersPerShaderStage is 16 too, and
   * real adapters that offer more sampled textures keep it at 16: the coordinator's AMD Vulkan check) */
  fragmentSamplers: number;
  vertexSamplers: number;
  /** the fragment stage's textures, by binding name */
  names: string[];
}

export interface TextureAudit {
  limit: number;
  max_fragment: number;
  max_vertex: number;
  max_fragment_samplers: number;
  max_vertex_samplers: number;
  over: TextureUse[];
  /** per material: the worst pipeline (most fragment textures) it was drawn with */
  materials: TextureUse[];
}

/** Count the sampled textures of one render object's pipeline per stage. */
function countOf(ro: any): { fragment: number; vertex: number; fragmentSamplers: number; vertexSamplers: number; names: string[] } {
  const state = ro.getNodeBuilderState();
  let fragment = 0;
  let vertex = 0;
  let fragmentSamplers = 0;
  let vertexSamplers = 0;
  const names: string[] = [];
  for (const group of state.bindings ?? []) {
    for (const b of group.bindings ?? []) {
      const vis = b.visibility ?? 0;
      // a sampler binding (NodeSampler; three's SampledTexture also extends Sampler, so exclude textures)
      if (b.isSampler && !b.isSampledTexture) {
        if (vis & FRAGMENT) fragmentSamplers++;
        if (vis & VERTEX) vertexSamplers++;
        continue;
      }
      if (!b.isSampledTexture) continue;
      if (vis & FRAGMENT) {
        fragment++;
        names.push(String(b.texture?.name || b.name || '?'));
      }
      if (vis & VERTEX) vertex++;
    }
  }
  return { fragment, vertex, fragmentSamplers, vertexSamplers, names };
}

function passName(ro: any): string {
  const rt = ro.context?.renderTarget ?? ro.renderContext?.renderTarget ?? null;
  if (!rt) return 'canvas';
  const tex = rt.texture ?? rt.textures?.[0];
  return String(rt.name || tex?.name || (rt.depthTexture && !rt.textures?.length ? 'depth' : 'target'));
}

/** Record the render objects of the frames rendered between start() and stop(). */
export class TextureBudget {
  private seen = new Map<any, string>();
  private orig: ((...a: any[]) => any) | null = null;

  constructor(private readonly renderer: THREE.WebGPURenderer) {}

  start(): void {
    const objects = (this.renderer as any)._objects;
    if (this.orig || !objects) return;
    this.seen.clear();
    const orig = objects.get.bind(objects);
    this.orig = objects.get;
    objects.get = (...a: any[]) => {
      const ro = orig(...a);
      if (ro && !this.seen.has(ro)) this.seen.set(ro, passName({ context: a[5] }));
      return ro;
    };
  }

  stop(limit: number): TextureAudit {
    const objects = (this.renderer as any)._objects;
    if (this.orig) objects.get = this.orig;
    this.orig = null;
    const r = this.report(limit);
    this.seen.clear();
    return r;
  }

  /** The audit of every render object recorded so far (recording continues). */
  report(limit: number): TextureAudit {
    const all: TextureUse[] = [];
    for (const [ro, pass] of this.seen) {
      let c;
      try {
        c = countOf(ro);
      } catch {
        continue;
      }
      all.push({ material: String(ro.material?.name || ro.material?.type || '?'), object: String(ro.object?.name || ro.object?.type || '?'), pass, ...c });
    }
    const worst = new Map<string, TextureUse>();
    for (const u of all) {
      const k = u.material;
      const w = worst.get(k);
      const sc = (x: TextureUse) => Math.max(x.fragment, x.fragmentSamplers);
      if (!w || sc(u) > sc(w) || (sc(u) === sc(w) && u.fragment > w.fragment)) worst.set(k, u);
    }
    const materials = [...worst.values()].sort((a, b) => Math.max(b.fragment, b.fragmentSamplers) - Math.max(a.fragment, a.fragmentSamplers) || a.material.localeCompare(b.material));
    return {
      limit,
      max_fragment: Math.max(0, ...all.map((u) => u.fragment)),
      max_vertex: Math.max(0, ...all.map((u) => u.vertex)),
      max_fragment_samplers: Math.max(0, ...all.map((u) => u.fragmentSamplers)),
      max_vertex_samplers: Math.max(0, ...all.map((u) => u.vertexSamplers)),
      over: all.filter((u) => u.fragment > limit || u.vertex > limit || u.fragmentSamplers > limit || u.vertexSamplers > limit),
      materials,
    };
  }
}
