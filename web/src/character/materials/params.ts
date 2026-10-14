// The material parameter block: one JSON object, every leaf a live uniform. Override with
// ?params=<url-encoded JSON> or a material_params.json next to the GLB, or at runtime with
// __viewer.setParam('skin.wrap', [0.5, 0.2, 0.1]). Values are a NEUTRAL REALISTIC BASELINE;
// the painterly layer (C2) plugs in through `style` (see style.ts) without touching the BRDFs.
import * as THREE from 'three/webgpu';
import * as TSL from 'three/tsl';
// TSL's TypeScript types are too narrow for shader-graph code; the graph is checked at build.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const { uniform } = TSL as any;

export const DEFAULT_PARAMS = {
  style: {
    /** 0 = realistic diffuse; 1 = banded (toon ramp) diffuse. The C2 stylisation hook. */
    banded: 0,
    bands: 3,
    softness: 0.08,
  },
  skin: {
    albedoGain: 1.0,
    saturation: 1.0,
    /** Per-channel wrap (R, G, B): light bleeding past the terminator, the cheap SSS. */
    wrap: [0.42, 0.16, 0.1],
    /** Screen-space curvature scales the wrap (thin, curved parts scatter more). */
    curvatureGain: 0.6,
    /** Per-channel normal blur toward the geometric normal for the diffuse (R, G, B). */
    normalBlur: [0.7, 0.35, 0.2],
    /** Terminator tint: the red band where light turns into shadow. */
    scatterColor: [0.9, 0.25, 0.12],
    scatterWidth: 0.35,
    scatterStrength: 0.5,
    /** Dual-lobe specular (Jimenez / Kelemen-Szirmay-Kalos style): roughness multipliers and mix. */
    specF0: 0.028,
    lobe1Roughness: 0.75,
    lobe2Roughness: 1.45,
    lobeMix: 0.2,
    specGain: 1.0,
    roughnessScale: 1.0,
    roughnessBias: 0.0,
    normalScale: 1.0,
    aoIntensity: 1.0,
  },
  hair: {
    albedoGain: 1.0,
    /** Primary (white, shifted toward the root) and secondary (albedo tinted, toward the tip) lobes. */
    shift1: -0.08,
    shift2: 0.12,
    shiftJitter: 0.12,
    exponent1: 160,
    exponent2: 28,
    spec1: 0.14,
    spec2: 0.22,
    spec1Color: [1.0, 0.97, 0.94],
    /** Flips the flow tangent (root->tip convention check). */
    tangentSign: 1,
    diffuseWrap: 0.5,
    rootAO: 0.45,
    depthAO: 0.35,
    alphaTest: 0.32,
  },
  facialHair: {
    albedoGain: 1.0,
    /** Beard / brow / lash atlases carry linear values in sRGB-tagged images (review §1.9 S2):
     * 1 = read them as linear (the fix), 0 = as tagged. */
    linearFix: 1,
    spec1: 0.08,
    spec2: 0.12,
    alphaTest: 0.35,
  },
  eye: {
    albedoGain: 1.0,
    corneaRoughness: 0.04,
    corneaStrength: 1.0,
    /** Eye UV is a polar map: v from the back (0) to the cornea pole (1). Limbus and pupil rows. */
    limbusV: 0.645,
    limbalWidth: 0.012,
    limbalDarken: 0.35,
    irisDepth: 0.025,
    scleraDarken: 0.0,
  },
  cloth: {
    albedoGain: 1.0,
    fuzzColor: [0.32, 0.33, 0.38],
    fuzzStrength: 0.35,
    fuzzPower: 3.0,
    sheenScale: 1.0,
    twillStrength: 0.12,
    /** Twill period in UV units^-1 (diagonal ridges). */
    twillFreq: 900,
    roughnessScale: 1.0,
  },
  shirt: {
    fuzzStrength: 0.12,
  },
};

export type Params = typeof DEFAULT_PARAMS;
type Leaf = number | number[];

/** Every leaf becomes a uniform; materials read uniforms, so tweaks never recompile. */
export class ParamStore {
  readonly values: Params;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  private readonly uniforms = new Map<string, any>();

  constructor(overrides?: unknown) {
    this.values = structuredClone(DEFAULT_PARAMS);
    if (overrides && typeof overrides === 'object') merge(this.values as unknown as Record<string, unknown>, overrides as Record<string, unknown>);
  }

  get(path: string): Leaf {
    let o: unknown = this.values;
    for (const k of path.split('.')) o = (o as Record<string, unknown>)[k];
    if (typeof o !== 'number' && !Array.isArray(o)) throw new Error(`no param ${path}`);
    return o as Leaf;
  }

  /** The uniform node for a leaf (float, vec2, vec3 or vec4 by array length). */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  u(path: string): any {
    let n = this.uniforms.get(path);
    if (!n) {
      const v = this.get(path);
      n = typeof v === 'number' ? uniform(v) : uniform(toVec(v));
      this.uniforms.set(path, n);
    }
    return n;
  }

  set(path: string, value: Leaf): void {
    const keys = path.split('.');
    let o = this.values as unknown as Record<string, unknown>;
    for (const k of keys.slice(0, -1)) o = o[k] as Record<string, unknown>;
    const last = keys[keys.length - 1]!;
    if (!(last in o)) throw new Error(`no param ${path}`);
    o[last] = value;
    const n = this.uniforms.get(path);
    if (n) n.value = typeof value === 'number' ? value : toVec(value);
  }
}

function toVec(a: number[]): THREE.Vector2 | THREE.Vector3 | THREE.Vector4 {
  if (a.length === 2) return new THREE.Vector2(a[0], a[1]);
  if (a.length === 3) return new THREE.Vector3(a[0], a[1], a[2]);
  return new THREE.Vector4(a[0], a[1], a[2], a[3]);
}

function merge(dst: Record<string, unknown>, src: Record<string, unknown>): void {
  for (const [k, v] of Object.entries(src)) {
    if (!(k in dst)) continue;
    const d = dst[k];
    if (d && typeof d === 'object' && !Array.isArray(d) && v && typeof v === 'object') merge(d as Record<string, unknown>, v as Record<string, unknown>);
    else if (typeof v === typeof d || (Array.isArray(v) && Array.isArray(d))) dst[k] = v;
  }
}
