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
    /** T10: 1.3 (was 1.0), with the R lobe halved and TRT off (see spec1 / spec2). */
    albedoGain: 1.3,
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
    scatter: 0.008,
    scatterSat: 0.4,
    /** TT (T9b): backlit transmission in the scatter tint: gain x the R-like cone (ttExponent) x the
     * forward-scattering azimuth term ((1 - Lp.Vp) / 2)^ttPow. */
    tt: 0.36,
    ttPow: 6.0,
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
    // T10, with the deep hair shadow and GTAO: fitted on per-term basis frames (each lobe alone, per studio
    // light on the closeup and with the hero rig on the portrait) against the Cycles per-light closeups and
    // the parity portrait's crown / back boxes (bench/m1/v4/t10-engine-gate.md): the Kajiya R lobe lit the
    // side mass behind the temple (Cycles lights the top), and a broad TT (ttPow 2) lit everything the rim
    // reached; the fit wants a narrow forward TT (ttPow 6) at 2.8x, more diffuse / scatter body, R at half
    // and no TRT. Per light 0.98 / 1.13 / 0.98, portrait crown / back 3.07 vs Cycles 3.21.
    spec1: 0.0175,
    spec2: 0.0,
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
    /** T10 hair self-shadowing (hairshadow.ts): every shadowed light that reaches the hair gets a hair-only
     * twin whose shadow is a one-layer deep shadow, T = exp(-shadowDensity * (depth below the first
     * occluder - shadowBias)), metres; 0 = the T9b binary shadow on the hair (read at load). */
    deepShadow: 1,
    shadowDensity: 120,
    shadowBias: 0.002,
    /** Vogel-disk radius of the deep-shadow taps, in shadow-map texels. */
    shadowRadius: 1.5,
    /** Twin shadow maps: size, and the half-width (m) of the frustum around the head (read at load). */
    shadowMapSize: 2048,
    shadowExtent: 0.45,
    /** Optical depth of the hair layer above the fibres the camera sees (materials HairLightingModel):
     * every light into the scalp hair x exp(-surfaceDepth / |N.L|); 0 = off. */
    surfaceDepth: 0.0,
  },
  /** T10 screen-space AO (ao.ts): GTAO at half resolution on a depth / normal prepass (cards with their
   * alpha), multiplied into the direct diffuse of every character material, per light by the light's
   * size over distance (a big soft light is what AO stands in for; the key's own shadow map has the
   * rest). gtao 0 = the T6 stand-in (skin / cloth directAO x the baked AO; ?gtao=0 at load). */
  ao: {
    gtao: 1,
    strength: 1.0,
    /** World radius (m), thickness (m; depth steps beyond it do not occlude) and samples of three's GTAONode. */
    radius: 0.06,
    thickness: 0.15,
    samples: 16,
    /** How much of the baked AO stays in the direct diffuse with GTAO on (fine folds GTAO misses). */
    bakedMix: 0.25,
    /** Floor of the per-light weight (min(1, size / distance) otherwise). */
    lightWeightMin: 0.3,
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
    // T11: 0.004: the band is the under-layer now (a neutral dark brown); the wrapped scatter in
    // the albedo's (near-black red) tint lit the strokes ginger under the hero rig's warm key
    scatter: 0.004,
    tt: 0.0,
    alphaTest: 0.22,
  },
  eye: {
    albedoGain: 1.0,
    corneaRoughness: 0.18, // T18: 0.04 -> 0.18 with the LTC catchlight: the tear film plus the Cycles pixel filter / OIDN spread (portrait parity: catchlight 6 px vs Cycles 9-10; 0.08 left a hard 2x2 dot and a hard-edged square of the wrap)
    // shader-ball calibrated (T6): 1.0 put the area-light catchlight peak at 1.35x Cycles (coat f0 ~0.025 vs 0.04)
    corneaStrength: 0.7,
    /** Eye UV is a polar map: v from the back (0) to the cornea pole (1). Limbus and pupil rows. */
    limbusV: 0.645,
    limbalWidth: 0.012,
    limbalDarken: 0.35,
    irisDepth: 0.025,
    scleraDarken: 0.0,
    // T18 (materials/index.ts eye section). 1 = the iris by ray refraction through the cornea (0: the
    // painted bulge, no parallax)
    refraction: 1,
    ior: 1.376,
    /** Iris radius (mm; eyes_hq iris_mm / 2) and its plane under the limbus plane (the hero's recess_mm). */
    irisRadiusMm: 5.9,
    irisRecessMm: 0.0,
    /** Iris cone: the pupil margin forward of the root (slope of the iris normal toward the rim). */
    irisCone: 0.05,
    /** Scale of the eyes_normal map's slopes (iris fibres / crypts, conjunctival vessels). */
    normalStrength: 1.0,
    /** The caustic on the iris side away from the light. */
    causticGain: 0.25,
    scleraWrap: 0.15,
    /** The hero rig's camera catchlight lights the diffuse at this share (Blender: diffuse 0.3). */
    eyeLightDiffuse: 0.3,
    /** 1 = cornea specular against each light's Blender rectangle (LTC), so catchlights take its shape. */
    catchlightRect: 1,
    /** Lid shell (eye_lidshell) opacity scale over its baked alpha; the tear meniscus specular. */
    shellStrength: 1.0,
    meniscusSpec: 1.0,
    /** Radiance of the surroundings the wet eye reflects (x Fresnel x corneaStrength; emissive). */
    envVeil: [0.03, 0.035, 0.045], // 0.05/0.07/0.12 read as a blue crescent on the nasal limbus at 100 %
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
  /** T16 temporal AA (output.ts, temporal.ts; ?aa=traa|taau|msaa at load). */
  aa: {
    /** hashed card coverage: 0 = the alpha-to-coverage step at alphaTest (parity with the MSAA path),
     * 1 = the map alpha (fractional strand coverage, as Cycles' transparent cards). T16 measured both
     * (bench/m1/v4/t16-aa-post.md): 1 is closer to Cycles on the closeup hair / beard / brows (1.00 / 0.94 /
     * 1.07 vs 1.04 / 0.90 / 0.78) and shimmers less on the turntable (3.47 vs 3.63; MSAA 6.08) */
    hairCoverage: 1,
    /** current-frame weight floor (stock TRAA 0.05) and on hair pixels */
    minWeight: 0.05,
    hairMinWeight: 0.05,
    /** variance-clip gamma on hair pixels: still, and moving (screen motion >> motionPx px / frame) */
    hairGamma: 1.25,
    hairGammaMoving: 0.75,
    hairMotionPx: 1,
    /** frames accumulated per still capture (progressive, then the EMA floor) */
    stillFrames: 24,
    /** taau render scale (?scale= at load overrides) */
    scale: 0.75,
  },
  /** T16 thin-lens depth of field (dof.ts; beauty views of a camera with an f-stop). */
  dof: {
    on: 1,
    /** CoC radius (px at the output height) that maps to 1 in the CoC texture */
    maxPx: 64,
    /** correction of the measured bokeh radius against the thin-lens formula (1 = the formula). At 1 the
     * engine's fitted disc at the ear was 3.45 / 3.24 px (helix / whole-ear ROI; the formula says 3.39),
     * Cycles' 2.87 / 2.71 px on the same fit (lookdev_report.py bokeh): Cycles' 7-blade f/2 blur reads
     * ~0.84 of the thin-lens disc. At 0.835 the engine fits 3.04 / 2.89 px (+6 % / +7 % of Cycles; the
     * half-res gather and the 0.5-1.5 px composite fade keep it from scaling linearly). */
    radiusScale: 0.835,
    /** near-field 16-tap max pass radius (fraction of the gather radius) */
    maxPassScale: 1,
    /** 1 = the gathers at full resolution */
    fullRes: 0,
  },
  /** T16 set bounce: set_bounce.json (Cycles, the alley without the character) as the environment of the
   * hero rig; gain 1 = Cycles' radiance as rendered. */
  bounce: {
    gain: 1,
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
