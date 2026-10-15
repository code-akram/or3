// Sampled-texture budget per shader stage (T18b). WebGPU's default maxSampledTexturesPerShaderStage is
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
  /** the fragment stage's textures, by binding name */
  names: string[];
}

export interface TextureAudit {
  limit: number;
  max_fragment: number;
  max_vertex: number;
  over: TextureUse[];
  /** per material: the worst pipeline (most fragment textures) it was drawn with */
  materials: TextureUse[];
}

/** Count the sampled textures of one render object's pipeline per stage. */
function countOf(ro: any): { fragment: number; vertex: number; names: string[] } {
  const state = ro.getNodeBuilderState();
  let fragment = 0;
  let vertex = 0;
  const names: string[] = [];
  for (const group of state.bindings ?? []) {
    for (const b of group.bindings ?? []) {
      if (!b.isSampledTexture) continue;
      const vis = b.visibility ?? 0;
      if (vis & FRAGMENT) {
        fragment++;
        names.push(String(b.texture?.name || b.name || '?'));
      }
      if (vis & VERTEX) vertex++;
    }
  }
  return { fragment, vertex, names };
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
    this.seen.clear();
    const worst = new Map<string, TextureUse>();
    for (const u of all) {
      const k = u.material;
      const w = worst.get(k);
      if (!w || u.fragment > w.fragment || (u.fragment === w.fragment && u.vertex > w.vertex)) worst.set(k, u);
    }
    const materials = [...worst.values()].sort((a, b) => b.fragment - a.fragment || a.material.localeCompare(b.material));
    return {
      limit,
      max_fragment: Math.max(0, ...all.map((u) => u.fragment)),
      max_vertex: Math.max(0, ...all.map((u) => u.vertex)),
      over: all.filter((u) => u.fragment > limit || u.vertex > limit),
      materials,
    };
  }
}
