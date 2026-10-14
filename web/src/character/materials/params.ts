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
    wrap: [0.3, 0.12, 0.08],
    /** Screen-space curvature scales the wrap (thin, curved parts scatter more). */
    curvatureGain: 0.6,
    /** Per-channel normal blur toward the geometric normal for the diffuse (R, G, B). */
    normalBlur: [0.7, 0.35, 0.2],
    /** Terminator tint: the red band where light turns into shadow. */
    scatterColor: [0.9, 0.25, 0.12],
    scatterWidth: 0.35,
    scatterStrength: 0.25,
    /** Dual-lobe specular (Jimenez / Kelemen-Szirmay-Kalos style): roughness multipliers and mix. */
    specF0: 0.028,
    lobe1Roughness: 0.85,
    lobe2Roughness: 1.45,
    lobeMix: 0.2,
    specGain: 0.6,
    roughnessScale: 1.0,
    roughnessBias: 0.0,
    normalScale: 1.0,
    aoIntensity: 1.0,
    /** Pre-integrated SSS (sss.ts): 1 = the curvature x N.L LUT replaces wrap, terminator tint and the
     * per-channel normal blur's N.L (the blur stays for small-scale bump); 0 = the T5 wrap model.
     * Needs skin_<part>_curvature.png (builds since T6); without it the wrap model is used. */
    sss: 1,
    /** Scales the profile radii (hero Cycles radii 3.4 / 0.75 / 0.34 mm) when the LUT is built (load). */
    sssRadiusScale: 1.0,
    /** Gain on the baked curvature before the LUT lookup. */
    sssCurvatureGain: 1.0,
    /** Baked AO into the DIRECT diffuse (three's aoMap only touches indirect light, and the hero
     * world is 0.003, so without this the AO channel does nothing). Until GTAO lands. */
    directAO: 0.5,
  },
  hair: {
    albedoGain: 1.0,
    /** Primary (white, shifted toward the root) and secondary (albedo tinted, toward the tip) lobes. */
    shift1: -0.08,
    shift2: 0.12,
    shiftJitter: 0.12,
    /** T9b, lobe shift offsets that break a planar card's highlight into strands (materials HairMaterial):
     * per card (hashed COLOR_0 value), and a wave tilt along each strand, amplitude waveTilt with
     * waveCycles[0..1] waves root to tip (per strand, from the ID). idLodBias: mip bias for the ID / root-tip
     * read that feeds the jitter (trilinear IDs of a minified card average to 0.5 and kill the jitter). */
    cardJitter: 0.1,
    waveTilt: 0.2,
    waveCycles: [1.0, 2.5],
    idLodBias: -2,
    /** How much of the strand occlusion (root AO x baked AO x depth AO) reaches the lobes (0 = T9). */
    specAO: 1.0,
    /** Warm multiple-scattering body (T9b): a fully wrapped diffuse in the scatter tint, the albedo's
     * chroma ^ scatterSat at luminance 1; the TRT lobe (spec2) takes the same tint. */
    scatter: 0.004,
    scatterSat: 0.4,
    /** TT (T9b): backlit transmission in the scatter tint: gain x the R-like cone (ttExponent) x the
     * forward-scattering azimuth term ((1 - Lp.Vp) / 2)^ttPow. */
    tt: 0.13,
    ttPow: 2.0,
    ttExponent: 16,
    /** T9, calibrated on the closeup parity (bench/m1/hair_test.py --parts parity: hair-region mean
     * and median linear luminance vs the Cycles hero strands). The hero's Chiang roughness ~0.4 puts
     * a single fibre's R lobe at sin^p, p ~23 (TRT ~6); the cards need narrower lobes (60 / 12) for
     * the highlight tail (Cycles p90 / p99 0.76 / 1.6): the per-strand shift jitter and the flow map
     * already spread the highlight across a card the way the strand-to-strand variation does. */
    exponent1: 60,
    exponent2: 24,
    // T6 had 0.0175 / 0.02 (shader balls, exponents 160 / 28, a near-black atlas: hair region 0.24x Cycles).
    // T9: 0.19 / 0.07 with the per-card layer scale (front locks 0.4, under 0.7): hair region 0.98x the hero,
    // but per light (hair_test --parity-lights, viewer ?lights=) key 2.1x, fill 3.0x, rim 0.52x: ~80 % of the
    // hero hair's closeup luminance is the rim's (TT / TRT through the fibres), the engine's was the key's
    // white R. T9b, fitted per light with the TT lobe, then trimmed on the hero portrait (hair beside the
    // face 1.5x the Cycles hero relative to the forehead at R 0.05 / TT 0.15): R 0.035, TRT 0.007 (in the
    // unit-luminance scatter tint), TT 0.13, scatter 0.004: hair region 0.94x, portrait hair 1.27x / 0.95x.
    spec1: 0.035,
    spec2: 0.007,
    spec1Color: [1.0, 0.97, 0.94],
    /** Flips the flow tangent (root->tip convention check). */
    tangentSign: 1,
    diffuseWrap: 0.5,
    /** Root darkening from the ORM root-to-tip channel (A): 1 - rootAO at the root, gone by rootV. */
    rootAO: 0.45,
    rootV: 0.15,
    /** Baked occlusion (ORM R: local strand density x depth across the card). */
    bakedAO: 1.0,
    /** Back-of-card darkening from the anisotropy map's depth (A). */
    depthAO: 0.2,
    /** Per-strand roughness (ORM G) relative to this scales the lobe exponents by (ref / r)^2. */
    roughRef: 0.55,
    alphaTest: 0.32,
    /** Depth prepass for the scalp cards (materials.addHairDepthPrepass; read at load): depth-only
     * twins write where coverage > prepassAlpha and the strand depth (anisotropy A) > prepassDepth. */
    depthPrepass: 1,
    prepassAlpha: 0.85,
    prepassDepth: 0.45,
  },
  facialHair: {
    /** Atlas gain: 1 (T9: no per-build decode fix or gain; the beard / brow atlases are sRGB-encoded
     * per-strand colour from the groom, as the scalp's). */
    albedoGain: 1.0,
    // T9, closeup parity (beard-region linear luminance vs the hero strands): the lobes are the
    // hair's (exponents), the gains lower: a dense short beard self-shadows (the cards do not)
    spec1: 0.01,
    // T9b: 0.002 in the unit-luminance scatter tint (T9's 0.012 x sqrt(albedo) was ~0.0002)
    spec2: 0.002,
    scatter: 0.0,
    tt: 0.0,
    alphaTest: 0.22,
  },
  /** Brow cards (T9b; were facialHair): the same lobes and maps, own gains, calibrated on the brow
   * region of the closeup parity (bench/m1/hair_test.py --parts parity, hero brow strands). */
  brows: {
    albedoGain: 1.0,
    spec1: 0.01,
    spec2: 0.002,
    // the brow body: T9 brow region p50 0.08 vs 0.16 (Cycles), near-black strokes over skin; 0.01 with
    // the T9b brow under-layer and finer strands: brow region 1.03x, p50 0.135 vs 0.161.
    // T11: 0.006: the band is the under-layer now (a neutral dark brown); the wrapped scatter in
    // the albedo's (near-black red) tint lit the strokes ginger under the hero rig's warm key
    scatter: 0.006,
    tt: 0.0,
    alphaTest: 0.22,
  },
  eye: {
    albedoGain: 1.0,
    corneaRoughness: 0.04,
    // shader-ball calibrated (T6): 1.0 put the area-light catchlight peak at 1.35x Cycles (coat f0 ~0.025 vs 0.04)
    corneaStrength: 0.7,
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
    fuzzStrength: 0.15,
    fuzzPower: 3.0,
    // shader-ball calibrated (T6): three's Charlie sheen vs Blender's; wool read 1.35x at 0.6, 0.88x at 0
    sheenScale: 0.15,
    twillStrength: 0.12,
    /** Twill period in UV units^-1 (diagonal ridges). */
    twillFreq: 900,
    /** Gain on the tiled weave detail (suit_detail.json; replaces the procedural twill when present). */
    weaveStrength: 1.0,
    roughnessScale: 1.0,
    directAO: 0.5,
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
