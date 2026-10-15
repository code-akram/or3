// First TSL material set for the character (neutral realistic baseline; review §3.3 table).
// Each material is a MeshPhysicalNodeMaterial with a small custom lighting model; every tunable is a
// uniform from the ParamStore. The glTF materials are replaced by name / role (assignMaterials).
//
//   skin   wrap-lit diffuse with per-channel wrap + normal blur (curvature-scaled; cheap pre-integrated
//          SSS stand-in), a terminator scatter tint, dual-lobe GGX specular. T17: pore + micro detail-normal
//          tiles (skin_detail.json) faded by their on-screen period, the baked cavity (ORM blue) and the
//          pits as lobe-1 specular occlusion, transmission through thin parts (baked thickness), and with
//          the screen-space SSS pass (ssss.ts) a Lambert diffuse plus the MRT inputs that pass blurs
//   hair   dual-lobe Kajiya-Kay (white primary shifted to the root, albedo-tinted secondary to the tip,
//          shifts jittered per strand ID / card / along-strand wave, exponents scaled by per-strand
//          roughness), a tinted TT (backlit) lobe and a wrapped multiple-scatter body (T9b), flow / depth /
//          ORM strand maps from the GLB (KHR_materials_anisotropy + occlusion / metallicRoughness),
//          alpha to coverage (4x MSAA, the parity stills) or, on the temporal-AA path (T16), a temporally
//          hashed coverage that TRAA averages (HairMaterial.setupHashedAlpha)
//   facial beard / brow cards on the same path and maps (prefix facialHair); lashes along the UV bitangent
//   eye    T18: iris by ray refraction through the cornea, iris normal + caustic, sclera vein normal,
//          cornea GGX against the emitter rectangle (LTC); the lid shell and tear meniscus (eye_*)
//   cloth  glTF sheen + a 1 - N.V fuzz rim + a procedural micro-twill normal
import * as THREE from 'three/webgpu';
import * as TSL from 'three/tsl';
import type { ParamStore } from './params';
import { albedo, diffuseRamp } from './style';
import { RectAreaLightTexturesLib } from 'three/addons/lights/RectAreaLightTexturesLib.js';
import { HERO_RADII_MM } from './sss';
import { temporalFrame } from '../temporal';
import { rectFormFactor, screenTerm, withSharedLighting } from '../lighting';
// TSL's TypeScript types are too narrow for shader-graph code; the graph is checked at build.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const { bool, interleavedGradientNoise, mrt, screenCoordinate, BRDF_GGX, BRDF_Lambert, LTC_Evaluate, cameraWorldMatrix, exp, log, LTC_Uv, mat3, diffuseColor, faceDirection, float, fract, fwidth, hash, mix, normalMap, normalView, normalViewGeometry, positionView, positionViewDirection, roughness, screenUV, sin, smoothstep, bitangentView, tangentView, texture, uv, varying, vec2, vec3, vec4, vertexColor } = TSL as any;
// T18 eye: refraction, frames and the emitter-shaped catchlight
const { asin, atan, cameraViewMatrix, cross, dFdx, dFdy, refract, step, uniform } = TSL as any;
// T17 skin: the lighting's specular total (LightsNode's 'totalSpecular' property) for the SSS pass MRT
const { property } = TSL as any;

/* eslint-disable @typescript-eslint/no-explicit-any */
type N = any;

/** The interpolated vertex normal in view space, turned to the side being shaded. three's
 * normalViewGeometry is NOT flipped on back faces (normalView is, for double-sided materials), so
 * mixing the two, as the skin's per-channel normal blur does, put the red channel's N.L (blur 0.7)
 * on the far side of the surface on every back-facing fragment: red went dark while green and blue
 * stayed lit, and the folded lower lids and alar bases rendered teal (t7b). Every lighting term
 * that uses the geometric normal takes this one. */
const geometryNormal: N = normalViewGeometry.mul(faceDirection);
type Std = THREE.MeshStandardMaterial & Partial<THREE.MeshPhysicalMaterial>;
interface DirectInput {
  lightDirection: N;
  lightColor: N;
  lightNode?: { light?: THREE.Light };
  reflectedLight: { directDiffuse: N; directSpecular: N };
}
interface RectInput {
  lightNode?: { light?: THREE.Light };
  lightColor: N;
  lightPosition: N;
  halfWidth: N;
  halfHeight: N;
  reflectedLight: { directDiffuse: N; directSpecular: N };
  ltc_1: N;
  ltc_2: N;
}

/** A rect light (three's LTC path) as the point light the custom terms (skin SSS diffuse, cloth sheen +
 * fuzz, the hair lobes) understand. T19: the rect's VECTOR FORM FACTOR F (the sum of its edge terms,
 * Arvo 1994 / Heitz 2016): a Lambert receiver of normal n gets E = pi L (F . n) from the whole rect
 * (horizon unclipped), so the point equivalent is the direction F/|F| at the intensity of a plane facing
 * it, pi L |F|, exact for a big emitter close by. (T6 took the centre direction and L A cos / d^2, which
 * is the small-emitter limit: the hero fill (2 m square at 2.5 m) came out 24 % and the wrap 16 % hot.)
 * Zero behind the emitter (it shines along its local -z). The LTC keeps the specular. */
function rectAsPoint(i: RectInput): { L: N; color: N } {
  const c = i.lightPosition;
  const F = rectFormFactor(c, i.halfWidth, i.halfHeight, positionView);
  const toL = c.sub(positionView);
  const n = i.halfWidth.cross(i.halfHeight);
  const front = n.dot(toL).greaterThan(0); // shines along local -z: the lit side has toL along +z
  const f = F.length();
  const dir = F.div(f.max(1e-8)); // rectFormFactor orients F toward the light
  return { L: dir, color: i.lightColor.mul(front.select(f.mul(Math.PI), float(0))) };
}

export type Role = 'skin' | 'hair' | 'facial' | 'lash' | 'eye' | 'eyeshell' | 'eyewet' | 'cloth' | 'shirt' | 'generic';

export function roleOf(name: string): Role {
  if (name.startsWith('skin_')) return 'skin';
  if (name === 'hair' || name === 'hair_cards') return 'hair';
  if (/^(beard|brows)(_cards)?$/.test(name)) return 'facial';
  if (name.startsWith('eyelash')) return 'lash';
  if (name.startsWith('eyes')) return 'eye';
  if (name === 'eye_lidshell') return 'eyeshell'; // T18 game parts (eyes_hq.game_parts); not 'eye': the gaze turns 'eye' meshes only
  if (name === 'eye_meniscus') return 'eyewet';
  if (name === 'suit_shirt') return 'shirt';
  if (/^suit_(wool|wool_b|vest|silk)$/.test(name)) return 'cloth';
  return 'generic';
}

/** Light-linking groups (blender/hero/rig.py TWIN_GROUPS) by material name. */
export function groupOf(name: string): 'hair' | 'cloth' | 'skin' | 'other' {
  if (name === 'hair' || name === 'hair_cards') return 'hair';
  if (name.startsWith('skin_')) return 'skin';
  if (name.startsWith('suit_') && name !== 'suit_shirt') return 'cloth';
  return 'other';
}

/** Copy the glTF (standard / physical) inputs that the node materials keep using. */
function copyStd(dst: THREE.MeshPhysicalNodeMaterial, src: Std): void {
  dst.name = src.name;
  dst.side = src.side;
  dst.vertexColors = src.vertexColors;
  dst.color.copy(src.color);
  dst.map = src.map;
  dst.normalMap = src.normalMap;
  dst.normalScale.copy(src.normalScale);
  dst.roughness = src.roughness;
  dst.metalness = src.metalness;
  dst.roughnessMap = src.roughnessMap;
  dst.metalnessMap = src.metalnessMap;
  dst.aoMap = src.aoMap;
  dst.aoMapIntensity = src.aoMapIntensity;
  dst.emissive.copy(src.emissive);
  dst.emissiveMap = src.emissiveMap;
  // 8x anisotropic filtering: the suit's twill normal maps alias (moire) at grazing angles without it
  for (const t of [src.map, src.normalMap, src.roughnessMap, src.aoMap]) if (t) t.anisotropy = 8;
  if (src.isMeshPhysicalMaterial) {
    dst.clearcoat = src.clearcoat ?? 0;
    dst.clearcoatRoughness = src.clearcoatRoughness ?? 0;
    dst.clearcoatMap = src.clearcoatMap ?? null;
    dst.sheen = src.sheen ?? 0;
    if (src.sheenColor) dst.sheenColor.copy(src.sheenColor);
    dst.sheenRoughness = src.sheenRoughness ?? 1;
    dst.specularIntensity = src.specularIntensity ?? 1;
    if (src.specularColor) dst.specularColor.copy(src.specularColor);
    dst.anisotropy = src.anisotropy ?? 0;
  }
}

function mapRGBA(src: Std): N {
  const c = vec4(src.color.r, src.color.g, src.color.b, 1);
  return src.map ? texture(src.map).mul(c) : c;
}

function normalNode(src: Std, scale: N): N | null {
  return src.normalMap ? normalMap(texture(src.normalMap), vec2(src.normalScale.x, src.normalScale.y).mul(scale)) : null;
}

// --------------------------------------------------------------------------------------- skin

/** Direct-light occlusion factor: mix(1, baked AO, k). */
function directAO(ao: N | null, k: N): N {
  return ao ? mix(float(1), ao, k) : float(1);
}

/** The screen-space AO (ao.ts, GTAO at half resolution) at this fragment, or null when off. */
function screenAONode(tex: THREE.Texture | null | undefined): N | null {
  return tex ? texture(tex, screenUV).r : null;
}

/** Occlusion of one light's direct diffuse (T10). With the screen AO: GTAO weighted by the light's
 * aoWeight (stage.ts: its size over distance, floored by ao.lightWeightMin) x ao.strength, times a
 * little of the baked AO (ao.bakedMix, the folds GTAO at half res misses). Without it: the T6
 * stand-in, mix(1, baked AO, bakedKey). */
function directOcclusion(P: ParamStore, baked: N | null, bakedKey: string | null, screen: N | null, light: THREE.Light | undefined): N {
  if (screen) {
    const w = float((light?.userData?.aoWeight as number | undefined) ?? 1).max(P.u('ao.lightWeightMin')).min(1);
    let o: N = mix(float(1), screen, w.mul(P.u('ao.strength')));
    if (baked) o = o.mul(mix(float(1), baked, P.u('ao.bakedMix')));
    return o;
  }
  return baked && bakedKey ? directAO(baked, P.u(bakedKey)) : float(1);
}

interface SkinSSS {
  lut: THREE.Texture;
  curvature: N; // encoded curvature at this fragment (skin_tex.curvature)
}

/** T17: per-fragment inputs of the skin lighting beyond three's. */
interface SkinExtra {
  /** specular occlusion of lobe 1 (ORM blue cavity x tile pits), 1 = open; null = none */
  cavity: N | null;
  /** thickness (mm) for transmission; null = no transmission */
  thickMm: N | null;
  /** the screen-space SSS pass (ssss.ts) scatters: Lambert diffuse on a lightly blurred normal */
  ssss: boolean;
}

/** Transmittance of the skin profile (sss.ts: two Gaussians, sigma 0.5 r_c and 1.5 r_c, equal weight)
 * through a slab of thickness t (mm): the profile at radius t, peak-normalised (Jimenez 2010). */
function profileT(tMm: N, radii: N): N {
  const t2 = tMm.mul(tMm);
  const g = (k: number) => exp(t2.negate().div(radii.mul(k).mul(radii.mul(k)).mul(2).max(1e-6)));
  return g(0.5).add(g(1.5)).mul(0.5);
}

/** The light's colour without its shadow, for the transmission through a part that shadows itself.
 * AnalyticLightNode multiplies the shadow into colorNode and keeps the original as baseColorNode: run
 * the light node's own setupDirect on the base colour. null = not a punctual light (rects: none). */
function unshadowedColor(lightNode: unknown, builder: unknown, shadowed: N): N | null {
  type LN = { baseColorNode?: N; colorNode?: N; setupDirect?: (b: unknown) => { lightColor: N } | undefined; light?: THREE.Light };
  const ln = lightNode as LN | undefined;
  const l = ln?.light as (THREE.Light & { isSpotLight?: boolean; isPointLight?: boolean; isDirectionalLight?: boolean }) | undefined;
  if (!ln || !l || !(l.isSpotLight || l.isPointLight || l.isDirectionalLight) || !ln.setupDirect) return null;
  if (!ln.baseColorNode) return shadowed; // no shadow on this light
  const keep = ln.colorNode;
  ln.colorNode = ln.baseColorNode;
  try {
    return ln.setupDirect(builder)?.lightColor ?? null;
  } finally {
    ln.colorNode = keep;
  }
}

class SkinLightingModel extends THREE.PhysicalLightingModel {
  constructor(
    private readonly P: ParamStore,
    private readonly ao: N | null,
    private readonly sss: SkinSSS | null,
    private readonly screen: N | null = null,
    private readonly x: SkinExtra = { cavity: null, thickMm: null, ssss: false },
  ) {
    super();
  }

  override direct(input: unknown, builder?: unknown): void {
    const { lightDirection: L, lightColor, reflectedLight, lightNode } = input as DirectInput;
    const noTrans = (input as { noTransmission?: boolean }).noTransmission === true;
    const P = this.P;
    const blur = P.u(this.x.ssss ? 'skin.ssssNormalBlur' : 'skin.normalBlur');
    const nl = (b: N) => mix(normalView, geometryNormal, b).normalize().dot(L);
    const nl3 = vec3(nl(blur.x), nl(blur.y), nl(blur.z));
    const occ = directOcclusion(P, this.ao, 'skin.directAO', this.screen, lightNode?.light);
    let d: N;
    if (this.x.ssss) {
      // the screen-space pass scatters (ssss.ts): Lambert here, per channel on the lightly blurred normal
      d = diffuseRamp(P, nl3.max(0));
    } else {
      // screen-space curvature (1/m), normalised so a ~5 cm radius reads 1
      const curv = fwidth(geometryNormal).length().div(fwidth(positionView).length().max(1e-5)).mul(0.05).clamp(0, 1);
      const g = P.u('skin.curvatureGain');
      const wrap = P.u('skin.wrap').mul(mix(float(1).sub(g), float(1).add(g), curv));
      const diff = diffuseRamp(P, nl3.add(wrap).div(wrap.add(1)).max(0));
      // terminator scatter band (centred on N.L = 0 of the blurred green normal)
      const band = smoothstep(P.u('skin.scatterWidth'), float(0), nl3.y.abs()).mul(P.u('skin.scatterStrength'));
      const tint = vec3(1).add(P.u('skin.scatterColor').mul(band));
      d = diff.mul(tint);
      if (this.sss) {
        // pre-integrated SSS: per channel D(N.L of that channel's blurred normal, curvature)
        const cv = this.sss.curvature.mul(P.u('skin.sssCurvatureGain')).clamp(0.002, 1);
        const at = (x: N) => texture(this.sss!.lut, vec2(x.mul(0.5).add(0.5).clamp(0, 1), cv));
        const pre = vec3(at(nl3.x).r, at(nl3.y).g, at(nl3.z).b);
        d = mix(d, diffuseRamp(P, pre), P.u('skin.sss'));
      }
    }
    const lambert = BRDF_Lambert({ diffuseColor: diffuseColor.rgb });
    reflectedLight.directDiffuse.addAssign(lightColor.mul(d).mul(occ).mul(lambert));
    // T17 transmission: light through the thin parts from behind, unshadowed (the part shadows itself)
    if (this.x.thickMm && !noTrans && builder) {
      const lc = unshadowedColor(lightNode, builder, lightColor);
      if (lc !== null) {
        const radii = vec3(...HERO_RADII_MM).mul(P.u('skin.ssssWidth'));
        const T = profileT(this.x.thickMm.mul(P.u('skin.transThickScale')), radii);
        const w = P.u('skin.transWrap');
        const back = geometryNormal.negate().dot(L).add(w).div(w.add(1)).max(0);
        reflectedLight.directDiffuse.addAssign(lc.mul(T).mul(back).mul(P.u('skin.transmission')).mul(lambert));
      }
    }
    // dual-lobe specular; the cavity occludes the sharp lobe only (the broad one stands for the oil
    // film's sheen across the pits)
    const r = roughness.clamp(0.08, 1);
    const f0 = vec3(P.u('skin.specF0'));
    let s1: N = BRDF_GGX({ lightDirection: L, f0, f90: float(1), roughness: r.mul(P.u('skin.lobe1Roughness')).clamp(0.05, 1) });
    if (this.x.cavity) s1 = s1.mul(this.x.cavity);
    const s2 = BRDF_GGX({ lightDirection: L, f0, f90: float(1), roughness: r.mul(P.u('skin.lobe2Roughness')).clamp(0.05, 1) });
    const dotNL = normalView.dot(L).clamp();
    reflectedLight.directSpecular.addAssign(lightColor.mul(dotNL).mul(mix(s1, s2, P.u('skin.lobeMix'))).mul(P.u('skin.specGain')));
  }

  override directRectArea(input: unknown, builder?: unknown): void {
    const i = input as RectInput;
    // the area-shaped (LTC) specular, scaled like the dual lobe; the stock Lambert diffuse is dropped
    const spec = vec3(0).toVar();
    super.directRectArea({ ...(i as object), reflectedLight: { directDiffuse: vec3(0).toVar(), directSpecular: spec } } as never, builder as never);
    i.reflectedLight.directSpecular.addAssign(spec.mul(this.P.u('skin.specGain')));
    // pre-integrated SSS / wrap diffuse from the point equivalent (its punctual specular dropped)
    const pt = rectAsPoint(i);
    this.direct({ lightDirection: pt.L, lightColor: pt.color, lightNode: i.lightNode, noTransmission: true, reflectedLight: { directDiffuse: i.reflectedLight.directDiffuse, directSpecular: vec3(0).toVar() } }, builder);
  }
}

/** skin_detail.json (blender/character/skin_tex.write_detail_sidecars), as loaded by main.ts. */
export interface SkinDetail {
  /** layer 0 the pore tile, layer 1 the micro tile (one binding: the fragment stage's 16 sampled textures) */
  tiles: THREE.Texture;
  /** skin material name -> its detail map (R pore weight, G micro weight, B inside AO) and repeats */
  materials: Record<string, { map: THREE.Texture | null; poreRepeat: number; microRepeat: number }>;
  poreCells: number;
  microCells: number;
  thickDistMm: number;
  /** ORM blue holds the specular cavity */
  cavity: boolean;
  /** mean |n_xy|^2 of each tile (the toksvig term) */
  slopeVar: { pore: number; micro: number };
}

export interface SkinOptions {
  sss?: { lut: THREE.Texture; curvature: THREE.Texture } | null | undefined;
  screenAO?: THREE.Texture | null | undefined;
  detail?: SkinDetail | null | undefined;
  /** the screen-space SSS pass is on: write its MRT inputs, Lambert diffuse */
  ssss?: boolean;
}

export class SkinMaterial extends THREE.MeshPhysicalNodeMaterial {
  private aoTex: N | null = null;
  private sss: SkinSSS | null = null;
  private readonly screen: N | null;
  private readonly extra: SkinExtra = { cavity: null, thickMm: null, ssss: false };

  constructor(src: Std, private readonly P: ParamStore, opts: SkinOptions = {}) {
    super();
    copyStd(this, src);
    const c = mapRGBA(src);
    this.colorNode = vec4(albedo(P, 'skin', c.rgb), 1);
    this.normalNode = normalNode(src, P.u('skin.normalScale'));
    let rough: N = src.roughnessMap ? texture(src.roughnessMap).g.mul(P.u('skin.roughnessScale')).add(P.u('skin.roughnessBias')) : null;
    const dt = opts.detail;
    const dm = dt?.materials[src.name];
    if (dt && dm?.map && src.normalMap) {
      // T17 detail tiles: pores and micro relief tiled in the part UV, weighted per region by the detail
      // map, faded where a tile period shrinks to a few pixels (mips flatten the rest)
      const det = texture(dm.map);
      const k = P.u('skin.detail');
      const fadeOf = (uvT: N, cells: number) => {
        const px = float(1).div(fwidth(uvT).length().mul(cells).max(1e-6)); // pixels per tile period
        const f = P.u('skin.detailFadePx');
        return smoothstep(f.y, f.x, px);
      };
      const uvP = uv().mul(dm.poreRepeat);
      const uvM = uv().mul(dm.microRepeat);
      const tp = texture(dt.tiles, uvP).depth(0);
      const tm = texture(dt.tiles, uvM).depth(1);
      const fP = fadeOf(uvP, dt.poreCells);
      const fM = fadeOf(uvM, dt.microCells);
      const wP = det.r.mul(k).mul(P.u('skin.poreNormal'));
      const wM = det.g.mul(k).mul(P.u('skin.microNormal'));
      const b = texture(src.normalMap).rgb.mul(2).sub(1);
      const dxy = tp.rg.mul(2).sub(1).mul(wP.mul(fP)).add(tm.rg.mul(2).sub(1).mul(wM.mul(fM)));
      const n = vec3(b.xy.add(dxy), b.z).normalize();
      this.normalNode = normalMap(n.mul(0.5).add(0.5), vec2(src.normalScale.x, src.normalScale.y).mul(P.u('skin.normalScale')));
      if (rough) {
        // pits rougher; the slope variance a fade removes goes to roughness (toksvig: r^2 + var)
        rough = rough.add(tp.b.mul(wP).mul(fP).mul(P.u('skin.poreRough')));
        const lost = wP.mul(wP).mul(float(1).sub(fP)).mul(dt.slopeVar.pore).add(wM.mul(wM).mul(float(1).sub(fM)).mul(dt.slopeVar.micro));
        rough = rough.mul(rough).add(lost.mul(P.u('skin.toksvig'))).sqrt();
      }
      // lobe-1 cavity: the baked one (ORM blue) and the visible pits
      const orm = src.metalnessMap ?? src.roughnessMap;
      let cav: N = float(1).sub(tp.b.mul(wP).mul(fP).mul(P.u('skin.poreCavity'))).clamp(0, 1);
      if (dt.cavity && orm) cav = cav.mul(mix(float(1), texture(orm).b, P.u('skin.cavitySpec')));
      this.extra.cavity = cav;
      // thickness t = D sqrt(inside AO); AO near 1 = thicker than the bake reached: no transmission
      this.extra.thickMm = det.b.clamp(0, 1).sqrt().mul(dt.thickDistMm).div(float(1).sub(smoothstep(0.85, 0.98, det.b)).max(1e-3));
    }
    if (rough) this.roughnessNode = rough.clamp(0.05, 1);
    this.metalnessNode = float(0);
    if (src.aoMap) {
      this.aoTex = texture(src.aoMap).r;
      this.aoNode = mix(float(1), this.aoTex, P.u('skin.aoIntensity'));
    }
    if (opts.sss) this.sss = { lut: opts.sss.lut, curvature: texture(opts.sss.curvature).r };
    this.screen = screenAONode(opts.screenAO);
    if (opts.ssss) {
      this.extra.ssss = true;
      // ssss.ts: the specular (kept sharp) and the diffuse albedo (the pre / post scatter split)
      this.mrtNode = mrt({ skin: vec4(property('vec3', 'totalSpecular'), 1), skinAlbedo: vec4(diffuseColor.rgb, 1) });
    }
  }

  override setupLightingModel(): THREE.PhysicalLightingModel {
    return new SkinLightingModel(this.P, this.aoTex, this.sss, this.screen, this.extra);
  }
}

// --------------------------------------------------------------------------------------- hair

interface HairNodes {
  tangent: N; // view-space fibre tangent
  shiftOff: N; // per-fragment lobe shift offset: per-strand + per-card jitter + the along-strand wave tilt
  rough: N; // per-strand roughness (ORM G): scales the lobe exponents around hair.roughRef
  specScale: N; // per-card specular scale (UV1 u: the baker's layer_spec) x the occlusion on the lobes
  tint: N; // warm scatter colour: the albedo's chroma, saturated (luminance 1)
  fibre: N; // T20, scalp hair: the colour of the TT / multiple-scatter terms (the strand's own transmittance, or tint)
  dirOcc: N | null; // T20: baked directional occlusion, L1 fit (mean, gx, gy, gz) in model axes, or null
  screen: N | null; // screen-space AO (ao.ts) or null
}

class HairLightingModel extends THREE.PhysicalLightingModel {
  constructor(
    private readonly P: ParamStore,
    private readonly prefix: string,
    private readonly h: HairNodes,
  ) {
    super();
  }

  override direct(input: unknown): void {
    const { lightDirection: L, lightColor: lightIn, reflectedLight, lightNode } = input as DirectInput;
    const P = this.P;
    const pre = this.prefix;
    // T10: screen-space AO on the diffuse and the scatter body (the jaw under the beard, the neck under
    // the hair); the fibre lobes keep the strand occlusion (specScale) only
    const occ = directOcclusion(P, null, null, this.h.screen, lightNode?.light);
    const N = normalView;
    // T10, scalp hair only: the light's path through the hair layer above the fibres the camera sees.
    // A card is one surface, but what the camera sees of a hair mass lies about an optical depth below
    // its outer fibres; light reaching that depth at a grazing angle crosses surfaceDepth / |N.L| of
    // hair (N: the mass's proxy normal). Beer-Lambert in that optical depth darkens the side of the mass
    // a rim grazes, and keeps backlit thin locks (light through the card, |N.L| large) glowing. The deep
    // shadow (hairshadow.ts) has the hair above the outer layer.
    let lightColor = pre === 'hair' ? lightIn.mul(exp(P.u('hair.surfaceDepth').negate().div(N.dot(L).abs().max(0.05)))) : lightIn;
    // T20 gameplay tier: the baked directional hair occlusion (hair_groom_cards.dir_occlusion) toward the
    // light, mean + g.L in model (= world) axes; hair.dirOcclusion 0 (hero tier: the deep shadow) = off
    if (this.h.dirOcc) {
      const Lw = cameraWorldMatrix.mul(vec4(L, 0)).xyz.normalize();
      const o = this.h.dirOcc.x.add(this.h.dirOcc.yzw.dot(Lw)).clamp(0, 1);
      lightColor = lightColor.mul(mix(float(1), o, P.u('hair.dirOcclusion')));
    }
    const V = positionViewDirection;
    const T = this.h.tangent;
    const w = P.u('hair.diffuseWrap');
    const nl = N.dot(L);
    const diff = diffuseRamp(P, nl.add(w).div(w.add(1)).max(0));
    reflectedLight.directDiffuse.addAssign(lightColor.mul(diff).mul(occ).mul(BRDF_Lambert({ diffuseColor: diffuseColor.rgb })));
    // T9b: the multiple-scattering body (the warm mid-brown of the Chiang hero along the lengths): a
    // fully wrapped, albedo-chroma tinted diffuse. Dark hair is lit mostly by light that went through
    // other fibres, which comes out with the fibre's transmittance colour, not white.
    const msWrap = nl.add(1).mul(0.5).max(0);
    reflectedLight.directDiffuse.addAssign(lightColor.mul(diffuseRamp(P, msWrap)).mul(this.h.fibre).mul(P.u(`${pre}.scatter`)).mul(occ).mul(1 / Math.PI));
    const H = L.add(V).normalize();
    // per-strand roughness: a rougher strand has a broader lobe (exponent ~ 1 / variance)
    const er = P.u('hair.roughRef').div(this.h.rough.max(0.05)).pow(2);
    const kk = (shift: N, exp: N) => {
      const t = T.add(N.mul(shift.add(this.h.shiftOff))).normalize();
      const th = t.dot(H);
      const sinTH = float(1).sub(th.mul(th)).max(0).sqrt();
      // Kajiya-Kay lobe; strength is a plain multiplier (no energy normalisation, see params)
      return sinTH.pow(exp.mul(er));
    };
    const s1 = kk(P.u('hair.shift1'), P.u('hair.exponent1'));
    const s2 = kk(P.u('hair.shift2'), P.u('hair.exponent2'));
    const atten = nl.mul(0.75).add(0.25).clamp(0, 1);
    // R: white, shifted to the root; TRT: the scatter tint (T9b; was sqrt(albedo), near grey on dark hair)
    // T20: Fresnel on R (the cuticle reflection), relative to normal incidence: Schlick at the angle between
    // L and the half vector, f0 of IOR 1.55. A light behind the hair (the studio rim, the hero rim / kicker)
    // meets the fibres at grazing incidence and reflects ~4x what a front key does; the hero's Chiang R has it,
    // Kajiya-Kay does not (Cycles per light: the rim lights 83-97 % of the crown / side / back hair).
    const lh = L.dot(H).clamp(0, 1);
    const fr = float(0.0465).add(float(0.9535).mul(float(1).sub(lh).pow(5))).div(0.0465);
    const s1f = pre === 'hair' ? s1.mul(mix(float(1), fr, P.u('hair.fresnel'))) : s1;
    const spec = P.u('hair.spec1Color').mul(s1f).mul(P.u(`${pre}.spec1`)).add(this.h.tint.mul(s2).mul(P.u(`${pre}.spec2`))).mul(this.h.specScale);
    reflectedLight.directSpecular.addAssign(lightColor.mul(spec).mul(atten));
    // TT (T9b): light passing through the fibres toward the camera when the hair is backlit (the warm
    // glow on the hero's lengths under the rim; per-light Cycles frames put ~80 % of the hero hair's
    // closeup luminance on the rim). Longitudinally a cone like R (T.L = -T.V, lobe ttExponent on the
    // jittered tangent, so it breaks up per strand); azimuthally forward scattering: the light and view
    // directions across the fibre roughly opposite, ((1 - Lp.Vp) / 2)^ttPow. In the scatter tint.
    // lightColor carries the shadow, so only hair the light reaches (edges, hanging lengths) glows.
    const tj = T.add(N.mul(this.h.shiftOff)).normalize();
    const Lp = L.sub(tj.mul(tj.dot(L))).normalize();
    const Vp = V.sub(tj.mul(tj.dot(V))).normalize();
    const fwd = float(1).sub(Lp.dot(Vp)).mul(0.5).pow(P.u('hair.ttPow'));
    const tth = tj.dot(H);
    const cone = float(1).sub(tth.mul(tth)).max(0).sqrt().pow(P.u('hair.ttExponent').mul(er));
    reflectedLight.directSpecular.addAssign(lightColor.mul(this.h.fibre).mul(fwd.mul(cone).mul(P.u(`${pre}.tt`))).mul(this.h.specScale));
  }

  override directRectArea(input: unknown): void {
    // the anisotropic fibre lobes have no LTC form: the whole term from the rect's point equivalent
    const i = input as RectInput;
    const pt = rectAsPoint(i);
    this.direct({ lightDirection: pt.L, lightColor: pt.color, lightNode: i.lightNode, reflectedLight: i.reflectedLight });
  }
}

/** Runtime inputs next to the GLB that glTF has no slot for (blender/character/export.write_sidecars). */
export interface Sidecars {
  weave?: WeaveSidecar | null;
  /** skin material name -> curvature map (skin_<part>_curvature.png) */
  curvature?: Record<string, THREE.Texture | null>;
  sssLUT?: THREE.Texture | null;
  /** T10: the screen-space AO texture (ao.ts SceneAO.texture); null = the baked direct-AO stand-in */
  screenAO?: THREE.Texture | null;
  /** T17: skin_detail.json (pore / micro tiles, detail maps, cavity) */
  skinDetail?: SkinDetail | null;
  /** T17: the screen-space SSS pass is installed (ssss.ts): skin writes its MRT inputs */
  ssss?: boolean;
}

/**
 * Hair and facial-hair cards. The strand maps ride in the GLB's standard slots (blender/character/
 * hair_strand_raster.py, export.pack_hair_maps): anisotropyMap (KHR_materials_anisotropy) RG flow in
 * the tangent frame, A depth across the card; aoMap = metalnessRoughnessMap = the ORM image: R occlusion
 * (density x depth), G roughness, B strand ID, A root-to-tip. A material without them (pre-T9 build)
 * shades along the UV bitangent with a UV hash for the ID.
 */
export class HairMaterial extends THREE.MeshPhysicalNodeMaterial {
  private readonly nodes: HairNodes;
  readonly prefix: string;
  /** the GLB strand maps were found (main.ts reports it as state.hairMaps) */
  __maps = false;
  /** KHR_materials_anisotropy texture (flow, depth), for the depth prepass */
  readonly anisoMap: THREE.Texture | null;

  constructor(src: Std, private readonly P: ParamStore, opts: { prefix: 'hair' | 'facialHair' | 'brows'; msaa: boolean; screenAO?: THREE.Texture | null | undefined; dirOcc?: boolean }) {
    super();
    copyStd(this, src);
    this.prefix = opts.prefix;
    const anisoMap = (src as THREE.MeshPhysicalMaterial).anisotropyMap ?? null;
    const ormMap = src.aoMap ?? null;
    this.anisoMap = anisoMap && ormMap ? anisoMap : null;
    // the maps are read below; three's own AO / roughness / metalness / anisotropic GGX stay off
    this.aoMap = null;
    this.roughnessMap = null;
    this.metalnessMap = null;
    this.anisotropy = 0;
    const c = mapRGBA(src);
    let col = c.rgb;
    // per-card random (T9b): the baker's per-card value (COLOR_0, lognormal per card), hashed
    let card: N = float(0.5);
    if (this.vertexColors) {
      col = col.mul(vertexColor().rgb);
      card = hash(vertexColor().r.mul(65536).floor());
    }
    // scalp cards: UV1 u carries the card layer's specular scale (hair_groom_cards layer_spec; T9 builds, which
    // are the ones with the strand maps)
    const layerSpec: N = opts.prefix === 'hair' && this.anisoMap ? uv(1).x : float(1);
    let ao: N = float(1);
    let tUV: N = vec2(0, 1); // along +v (root -> tip)
    let id: N = hash(uv().mul(4096).floor().x.add(uv().mul(4096).floor().y.mul(4096)));
    let along: N = uv().y;
    let rough: N = P.u('hair.roughRef');
    this.__maps = !!(anisoMap && ormMap);
    if (anisoMap && ormMap) {
      const a = texture(anisoMap);
      const o = texture(ormMap);
      // the strand ID for the lobe jitter is read at a sharper mip (hair.idLodBias): the trilinear ID of a
      // minified card is the average of many strands (~0.5), which took the jitter out and lit the whole
      // card at one highlight angle (the T9 "silver plates")
      const oj = texture(ormMap).bias(P.u('hair.idLodBias'));
      tUV = a.rg.mul(2).sub(1);
      id = oj.b;
      along = oj.a;
      rough = o.g;
      ao = mix(float(1).sub(P.u('hair.rootAO')), float(1), smoothstep(0, P.u('hair.rootV'), o.a))
        .mul(mix(float(1), o.r, P.u('hair.bakedAO')))
        .mul(mix(float(1).sub(P.u('hair.depthAO')), float(1), a.a));
    }
    // H2: the scalp cards' COLOR_0 alpha (per-card opacity, the hairline root fade) scales the coverage after the
    // alpha test (the test stays on the map alpha, as the shadow pass and the T15 game mask see it), so a fade
    // is a smooth stochastic / A2C ramp, not cut at alphaTest; a VEC3 COLOR_0 (older builds) reads alpha 1
    this.vAlpha = opts.prefix === 'hair' && this.vertexColors && (P.get('hair.vertexAlpha') as number) > 0
      ? vertexColor().a : null;
    this.colorNode = vec4(albedo(P, opts.prefix, col).mul(ao), c.a);
    this.vertexColors = false; // folded into colorNode above
    // flow (UV space) through the exported tangent frame (glTF: +Y = the image's up = +v in Blender)
    const T = tangentView.mul(tUV.x).add(bitangentView.mul(tUV.y)).normalize().mul(P.u('hair.tangentSign'));
    // lobe shift offset (T9b): per strand (ID), per card, and a slow wave tilt along each strand (the hero
    // groom's 1-2 waves per strand tilt the fibre out of the card plane), so a planar card shows
    // separated, broken highlights instead of one sheet at the highlight angle
    const id2 = fract(id.mul(7.31).add(0.37));
    const wc = P.u('hair.waveCycles');
    const wave = sin(along.mul(mix(wc.x, wc.y, id2)).add(id).mul(2 * Math.PI)).mul(P.u('hair.waveTilt'));
    const shiftOff = id.mul(2).sub(1).mul(P.u('hair.shiftJitter')).add(card.mul(2).sub(1).mul(P.u('hair.cardJitter'))).add(wave);
    // the lobes see the strand occlusion too (root, density, back of the card): T9 darkened only the albedo,
    // so occluded strands kept their full highlight
    const specScale = layerSpec.mul(mix(float(1), ao, P.u('hair.specAO')));
    // scatter tint: the albedo's chroma raised to scatterSat, normalised to luminance 1
    const sat = col.max(1e-4).pow(P.u('hair.scatterSat'));
    const tint = sat.div(sat.dot(vec3(0.2126, 0.7152, 0.0722)).max(1e-5)).min(4);
    // T20, scalp hair: the TT and multiple-scatter colour is the strand's own fibre transmittance, not a
    // unit-luminance tint. The atlas albedo is Chiang's colour of the strand's absorption sigma
    // (hair_strand_raster.chiang_color: c = exp(-sqrt(sigma path) fac)), so sigma = (ln c)^2 / (fac^2 path) and
    // a pass through the fibre (about 2 radii) transmits exp(-2 sigma) = exp(-ttDepth (ln c)^2), ttDepth =
    // 2 / (fac^2 path). A near-black strand (melanin 0.9) transmits ~0.1 / 0.02 / 0.0005 (a dim deep red), a
    // grey one ~0.6 / 0.4 / 0.2: the unit-luminance tint gave every strand a grey strand's glow in a dark
    // strand's red (T15: front falls 1.23x the Cycles r/g, side mass 1.3x Cycles from TT alone). The colour
    // is read at the sharper mip of the ID (the mean colour of a minified card is a grey-strand average).
    let fibre: N = tint;
    if (opts.prefix === 'hair' && src.map) {
      const cs = texture(src.map).bias(P.u('hair.idLodBias')).rgb.max(1e-4);
      const lc = log(cs);
      fibre = mix(tint, exp(lc.mul(lc).mul(P.u('hair.ttDepth')).negate()), P.u('hair.fibreTint'));
    }
    // T20 directional occlusion: 4 x 6 bits packed in the strand UV v (TEXCOORD_1 y, which the exporter writes as
    // 1 - v), decoded per vertex (the packed integer does not survive interpolation; the decoded values do)
    let dirOcc: N | null = null;
    if (opts.dirOcc) {
      const p0 = float(1).sub(uv(1).y).round();
      const d = (x: N) => x.div(64).floor();
      const p1 = d(p0), p2 = d(p1), p3 = d(p2);
      const q = (x: N, y: N) => x.sub(y.mul(64)).div(63);
      dirOcc = varying(vec4(q(p0, p1), q(p1, p2).mul(2).sub(1), q(p2, p3).mul(2).sub(1), p3.div(63).mul(2).sub(1)));
    }
    this.nodes = { tangent: T, shiftOff, rough, specScale, tint, fibre, dirOcc, screen: screenAONode(opts.screenAO) };
    this.normalNode = null; // shade the card as a fibre bundle: the smooth proxy normal from the GLB
    this.roughnessNode = rough;
    this.metalnessNode = float(0);
    this.side = THREE.DoubleSide;
    this.alphaTest = P.get(`${opts.prefix}.alphaTest`) as number;
    if (opts.msaa) {
      this.alphaToCoverage = true;
      this.msaaCover = P.get('aa.msaaHairCoverage') as number;
    } else this.setupHashedAlpha(c.a, P);
  }

  /** H2: COLOR_0 alpha of the scalp cards (null = none / off) */
  private readonly vAlpha: N | null;
  /** H2: MSAA path, mix(A2C step, map alpha over the test, aa.msaaHairCoverage) (0 = three's own A2C) */
  private msaaCover = 0;

  /** H2, MSAA path: alpha-to-coverage from the same coverage the TRAA hash tests (setupHashedAlpha): the map
   * alpha where it passes alphaTest, x the COLOR_0 alpha. three's A2C (NodeMaterial.setupDiffuseColor) writes
   * smoothstep(alphaTest, alphaTest + fwidth, a): every strand texel over the test became a full sample set, so
   * the sparse outer cards covered more than their strands (the MSAA side / back hair 1.24-1.27x Cycles, TRAA
   * 1.11-1.12x). The alpha test is held off while three builds the colour (it would write its step), and the
   * coverage is written after; the material keeps alphaTest for the shadow pass. */
  override setupDiffuseColor(builder: unknown): void {
    const sup = (THREE.MeshPhysicalNodeMaterial.prototype as unknown as { setupDiffuseColor(b: unknown): void }).setupDiffuseColor;
    if (!this.alphaToCoverage || !(this.msaaCover > 0 || this.vAlpha)) {
      sup.call(this, builder);
      return;
    }
    const at = this.alphaTest;
    this.alphaTest = 0;
    try {
      sup.call(this, builder);
    } finally {
      this.alphaTest = at;
    }
    const a = diffuseColor.a;
    // three's A2C step, with the width floored (fwidth is 0 inside a card; see setupHashedAlpha)
    const edge = smoothstep(float(0), float(1), a.sub(float(at)).div(fwidth(a).max(1e-4)));
    let cov: N = mix(edge, a.mul(a.greaterThan(float(at)).select(float(1), float(0))), float(this.msaaCover));
    if (this.vAlpha) cov = cov.mul(this.vAlpha);
    cov = cov.clamp(0, 1);
    diffuseColor.a.assign(cov);
    cov.lessThanEqual(0.002).discard();
  }

  /** T16, the temporal-AA path (no MSAA): the cards' coverage is a stochastic per-pixel test against a
   * temporally rotated interleaved gradient noise (Jimenez 2014; the frame index steps it), which the
   * TRAA history averages back into a smooth coverage. aa.hairCoverage 0 = the alpha-to-coverage
   * coverage (a 1-px anti-aliased step at alphaTest, as three's A2C), 1 = the map alpha itself (the
   * strands' fractional coverage); in between, a mix. The alpha test stays on the material, so the
   * shadow pass (three's override material reads alphaTest and the map alpha) keeps T10's binary
   * cards; maskShadowNode keeps the screen-space hash out of it. The hair cards also write 1 into the
   * temporal target's 'hair' attachment (the hair-aware history, temporal.ts). */
  private setupHashedAlpha(a: N, P: ParamStore): void {
    const at = float(this.alphaTest);
    // three's A2C edge, smoothstep(at, at + fwidth(a), a), but with the width floored: inside a card the map
    // alpha is flat, fwidth is 0, and smoothstep with edge0 == edge1 is undefined (WGSL / GLSL). SwiftShader
    // returned 0 there, so whole card interiors failed the hash every frame (holes on the crown down to the
    // scalp, or to the background through the depth-prepass twins)
    const edge = smoothstep(float(0), float(1), a.sub(at).div(fwidth(a).max(1e-4)));
    let cover: N = mix(edge, a, P.u('aa.hairCoverage'));
    if (this.vAlpha) cover = cover.mul(this.vAlpha); // H2: COLOR_0 alpha
    const ign = interleavedGradientNoise(screenCoordinate.xy.add(temporalFrame.mod(64).mul(5.588238)));
    (this as unknown as { maskNode: N; maskShadowNode: N }).maskNode = cover.greaterThan(ign);
    (this as unknown as { maskNode: N; maskShadowNode: N }).maskShadowNode = bool(true);
    this.mrtNode = mrt({ hair: float(1) });
  }

  override setupLightingModel(): THREE.PhysicalLightingModel {
    return new HairLightingModel(this.P, this.prefix, this.nodes);
  }
}

/**
 * Depth prepass for the hair cards (hair.depthPrepass 1): a depth-only twin of every hair-card mesh
 * (shared geometry and skeleton, drawn first) writes depth where the card is dense (coverage over
 * hair.prepassAlpha) and in front within the card (anisotropy-map depth over hair.prepassDepth), so the
 * alpha-to-coverage pass that follows resolves the cards against the dense core and the front strands
 * instead of against draw order. Returns the number of twins; they carry userData.hairPrepass.
 */
export function addHairDepthPrepass(root: THREE.Object3D, P: ParamStore): number {
  if (!(P.get('hair.depthPrepass') as number)) return 0;
  const twins: [THREE.Object3D, THREE.Mesh][] = [];
  const made = new Map<THREE.Material, THREE.MeshBasicNodeMaterial>();
  root.traverse((o) => {
    const m = o as THREE.SkinnedMesh;
    if (!m.isMesh || Array.isArray(m.material)) return;
    const hm = m.material as HairMaterial;
    if (!(hm instanceof HairMaterial) || hm.prefix !== 'hair' || !m.parent) return;
    let dm = made.get(hm);
    if (!dm) {
      dm = new THREE.MeshBasicNodeMaterial();
      const src = hm as unknown as Std;
      // H2: x the COLOR_0 alpha (per-card opacity, the hairline root fade), as the card's own coverage (white
      // when the geometry has no COLOR_0)
      const va = (P.get('hair.vertexAlpha') as number) > 0 ? vertexColor().a : float(1);
      const a = src.map ? texture(src.map).a.mul(va) : va;
      const depth = hm.anisoMap ? texture(hm.anisoMap).a : float(1);
      // discard thin texels and the back of the card: what is left is the opaque front of each lock
      dm.opacityNode = a.mul(smoothstep(P.u('hair.prepassDepth').sub(0.05), P.u('hair.prepassDepth'), depth));
      dm.alphaTest = P.get('hair.prepassAlpha') as number;
      dm.colorWrite = false;
      dm.depthWrite = true;
      dm.side = THREE.DoubleSide;
      dm.name = `${hm.name}_prepass`;
      made.set(hm, dm);
    }
    const t: THREE.Mesh = m.isSkinnedMesh ? new THREE.SkinnedMesh(m.geometry, dm) : new THREE.Mesh(m.geometry, dm);
    if (m.isSkinnedMesh) (t as THREE.SkinnedMesh).bind(m.skeleton, m.bindMatrix);
    t.position.copy(m.position);
    t.quaternion.copy(m.quaternion);
    t.scale.copy(m.scale);
    t.renderOrder = m.renderOrder - 1;
    t.frustumCulled = false;
    t.castShadow = false;
    t.receiveShadow = false;
    t.userData.hairPrepass = true;
    twins.push([m.parent, t]);
  });
  for (const [p, t] of twins) p.add(t);
  return twins.length;
}

// --------------------------------------------------------------------------------------- eye
//
// T18 (bench/m1/v4/checkpoint-3.md §2.4). The game eye is one skinned mesh with both globes (polar UV,
// u = phi / 2pi on each eye's half, v = 1 - sqrt(theta / pi) from the front pole, eyes_hq.py) and a
// corneal bulge. Each eye's frame (centre, axis, the phi = 0 direction, radius) is fitted from the
// bind-pose geometry in JS (refitted when the gaze edits it) and carried through the head bone every
// frame; the shader works in view space against it:
//   iris     a true refraction: the view ray refracts at the cornea (IOR eye.ior) and meets the iris
//            plane (eye.irisRecessMm below the limbus plane); the hit's polar coordinates index the
//            same albedo / normal maps (replaces the T6 parallax)
//   lighting the light refracts the same way through the cornea (entry normal of the fitted cornea
//            sphere) onto the iris normal (eyes_normal map + a shallow cone); the limbus shades the
//            iris side nearest the light and a caustic term brightens the side opposite it
//   sclera   the vein normal from the same map, a little wrap, the baked canthus gradient
//   cornea   GGX against the emitter's rectangle (LTC) for every light that carries its Blender
//            size (stage.ts userData.rect), so catchlights take the softbox / strip shape; the
//            point-GGX lobe stays for lights without one
//   eye light the Blender rig's camera catchlight lights the diffuse at eye.eyeLightDiffuse (T19: 1, as Cycles)

let ltcLib: { LTC_HALF_1: THREE.DataTexture; LTC_HALF_2: THREE.DataTexture } | null = null;
function ltcTextures(): { l1: N; l2: N } {
  ltcLib ??= RectAreaLightTexturesLib.init() as unknown as { LTC_HALF_1: THREE.DataTexture; LTC_HALF_2: THREE.DataTexture };
  return { l1: texture(ltcLib.LTC_HALF_1), l2: texture(ltcLib.LTC_HALF_2) };
}

/** Least-squares sphere through points (flat xyz array): [cx, cy, cz, r] or null. */
function fitSphere(p: number[]): [number, number, number, number] | null {
  const n = p.length / 3;
  if (n < 8) return null;
  // A x = b with A = [2x 2y 2z 1], b = x^2 + y^2 + z^2 (normal equations, 4x4)
  const M = new Array(16).fill(0);
  const r = new Array(4).fill(0);
  for (let i = 0; i < n; i++) {
    const a = [2 * p[i * 3]!, 2 * p[i * 3 + 1]!, 2 * p[i * 3 + 2]!, 1];
    const b = p[i * 3]! ** 2 + p[i * 3 + 1]! ** 2 + p[i * 3 + 2]! ** 2;
    for (let j = 0; j < 4; j++) {
      r[j] += a[j]! * b;
      for (let k = 0; k < 4; k++) M[j * 4 + k] += a[j]! * a[k]!;
    }
  }
  const m4 = new THREE.Matrix4().set(...(M as [number, number, number, number, number, number, number, number, number, number, number, number, number, number, number, number]));
  if (Math.abs(m4.determinant()) < 1e-30) return null;
  const x = new THREE.Vector4(r[0], r[1], r[2], r[3]).applyMatrix4(m4.invert());
  const rad = Math.sqrt(Math.max(x.w + x.x * x.x + x.y * x.y + x.z * x.z, 1e-12));
  return [x.x, x.y, x.z, rad];
}

interface EyeSide {
  ok: boolean;
  centre: THREE.Vector3; // bind (geometry) space
  axis: THREE.Vector3;
  ex: THREE.Vector3; // phi = 0
  radius: number;
  thetaC: number; // cornea edge (rad from the axis)
  corneaZ: number; // cornea sphere centre along the axis, from the eye centre (m)
  corneaR: number;
  vertex: number; // a vertex of this eye (its skin weights carry the frame)
}

/** Per-eye frames of the eye mesh (both eyes in one mesh), refitted from the geometry when it changes. */
class EyeFrames {
  sides: EyeSide[] = [];
  private key = -1;
  private renderId = -1;
  private obj: THREE.Object3D | null = null;
  // world-space results of the last sync, per side
  readonly wC = [new THREE.Vector3(), new THREE.Vector3()];
  readonly wA = [new THREE.Vector3(0, 0, 1), new THREE.Vector3(0, 0, 1)];
  readonly wE = [new THREE.Vector3(1, 0, 0), new THREE.Vector3(1, 0, 0)];

  private fit(geo: THREE.BufferGeometry): void {
    const pos = geo.getAttribute('position');
    const tc = geo.getAttribute('uv');
    this.sides = [];
    if (!pos || !tc) return;
    for (let side = 0; side < 2; side++) {
      const S: EyeSide = { ok: false, centre: new THREE.Vector3(), axis: new THREE.Vector3(), ex: new THREE.Vector3(1, 0, 0), radius: 0.012, thetaC: 0.54, corneaZ: 0, corneaR: 0.008, vertex: -1 };
      const back: number[] = [];
      let pole = -1;
      let poleV = -1;
      for (let i = 0; i < pos.count; i++) {
        const u = tc.getX(i);
        if (Math.abs(u - 0.5) < 1e-4 || (u > 0.5 ? 1 : 0) !== side) continue; // u = 0.5 is both eyes' seam
        if (S.vertex < 0) S.vertex = i;
        const v = tc.getY(i);
        if (v > poleV) {
          poleV = v;
          pole = i;
        }
        if (v < 0.5) back.push(pos.getX(i), pos.getY(i), pos.getZ(i)); // theta > 45 deg: the bare globe
      }
      const sp = fitSphere(back);
      if (!sp || pole < 0 || poleV < 0.99) {
        this.sides.push(S);
        continue;
      }
      S.centre.set(sp[0], sp[1], sp[2]);
      S.radius = sp[3];
      S.axis.set(pos.getX(pole), pos.getY(pole), pos.getZ(pole)).sub(S.centre).normalize();
      // phi = 0 direction and the cornea: ring vertices around the axis
      const ex = new THREE.Vector3();
      const ez = new THREE.Vector3();
      const d = new THREE.Vector3();
      const front: number[] = [];
      let thetaC = 0;
      for (let i = 0; i < pos.count; i++) {
        const u = tc.getX(i);
        if (Math.abs(u - 0.5) < 1e-4 || (u > 0.5 ? 1 : 0) !== side) continue;
        d.set(pos.getX(i), pos.getY(i), pos.getZ(i)).sub(S.centre);
        const len = d.length();
        const th = Math.acos(THREE.MathUtils.clamp(d.dot(S.axis) / Math.max(len, 1e-9), -1, 1));
        if (len > S.radius + 1e-5) thetaC = Math.max(thetaC, th);
        if (th < 0.3) front.push(d.x, d.y, d.z);
        if (th < 0.3 || th > 2.0) continue;
        const phi = (u - 0.5 * side) * 4 * Math.PI;
        const lat = d.clone().addScaledVector(S.axis, -d.dot(S.axis)).normalize();
        ex.addScaledVector(lat, Math.cos(phi));
        ez.addScaledVector(lat, Math.sin(phi));
      }
      ex.addScaledVector(S.axis, -ex.dot(S.axis)).normalize();
      S.ex.copy(ex);
      S.thetaC = thetaC > 0.1 ? thetaC : 0.54;
      const bulged = thetaC > 0.1; // a plain sphere (the shader ball) has no cornea to refract
      const cs = fitSphere(front);
      if (cs) {
        S.corneaZ = new THREE.Vector3(cs[0], cs[1], cs[2]).dot(S.axis);
        S.corneaR = cs[3];
      } else {
        S.corneaZ = 0;
        S.corneaR = S.radius;
      }
      // the right-handed frame check: ez = axis x ex must agree with the fitted sin(phi) direction
      S.ok = bulged && ez.lengthSq() > 0 && ex.lengthSq() > 0 && new THREE.Vector3().crossVectors(S.axis, ex).dot(ez) > 0;
      this.sides.push(S);
    }
  }

  /** Refit if the geometry changed (gaze), then carry the frames to world space (skinning). */
  sync(object: THREE.Object3D, renderId: number): void {
    if (renderId === this.renderId && object === this.obj) return;
    this.renderId = renderId;
    this.obj = object;
    const mesh = object as THREE.SkinnedMesh;
    const geo = mesh.geometry as THREE.BufferGeometry | undefined;
    if (!geo) return;
    const pa = geo.getAttribute('position') as THREE.BufferAttribute | THREE.InterleavedBufferAttribute;
    const key = 'isInterleavedBufferAttribute' in pa && pa.isInterleavedBufferAttribute ? pa.data.version : (pa as THREE.BufferAttribute).version;
    if (key !== this.key || this.sides.length === 0) {
      this.key = key;
      this.fit(geo);
    }
    const p = new THREE.Vector3();
    const q = new THREE.Vector3();
    const x = (v: THREE.Vector3, i: number): THREE.Vector3 => {
      if (mesh.isSkinnedMesh && mesh.skeleton && i >= 0) mesh.applyBoneTransform(i, v);
      return v.applyMatrix4(mesh.matrixWorld);
    };
    this.sides.forEach((S, k) => {
      if (!S.ok) return;
      const c = x(p.copy(S.centre), S.vertex);
      this.wC[k]!.copy(c);
      this.wA[k]!.copy(x(q.copy(S.centre).add(S.axis), S.vertex)).sub(c).normalize();
      this.wE[k]!.copy(x(q.copy(S.centre).add(S.ex), S.vertex)).sub(c).normalize();
    });
  }
}

/** The geometry uniforms of one eye material (world space; view space in the shader). */
function eyeFrameNodes(frames: EyeFrames): Record<string, N> {
  const sync = (f: { object: THREE.Object3D; renderId: number }): void => frames.sync(f.object, f.renderId);
  const u3 = (get: () => THREE.Vector3): N =>
    uniform(new THREE.Vector3()).onObjectUpdate((f: never) => {
      sync(f);
      return get();
    });
  const u1 = (get: () => number): N =>
    uniform(0).onObjectUpdate((f: never) => {
      sync(f);
      return get();
    });
  const S = (k: number): EyeSide | undefined => frames.sides[k];
  return {
    c0: u3(() => frames.wC[0]!),
    c1: u3(() => frames.wC[1]!),
    a0: u3(() => frames.wA[0]!),
    a1: u3(() => frames.wA[1]!),
    e0: u3(() => frames.wE[0]!),
    e1: u3(() => frames.wE[1]!),
    r0: u1(() => S(0)?.radius ?? 0.012),
    r1: u1(() => S(1)?.radius ?? 0.012),
    tc0: u1(() => S(0)?.thetaC ?? 0.54),
    tc1: u1(() => S(1)?.thetaC ?? 0.54),
    cz0: u1(() => S(0)?.corneaZ ?? 0),
    cz1: u1(() => S(1)?.corneaZ ?? 0),
    cr0: u1(() => S(0)?.corneaR ?? 0.008),
    cr1: u1(() => S(1)?.corneaR ?? 0.008),
    ok0: u1(() => (S(0)?.ok ? 1 : 0)),
    ok1: u1(() => (S(1)?.ok ? 1 : 0)),
  };
}

/** Everything the eye's colour and lighting share (view space), built once per material. */
interface EyeShade {
  C: N; // eye centre
  A: N; // axis
  Ex: N;
  Ez: N;
  R: N;
  thetaC: N;
  corneaO: N; // cornea sphere centre
  corneaR: N;
  inCornea: N; // 0..1: the fragment is on the cornea and refracts
  H: N; // iris-plane hit relative to C
  eRho: N; // the hit's radial direction on the iris plane
  ePhi: N;
  rhoI: N; // iris radius (m)
  st: N; // refracted polar UV
  irisN: N; // iris normal at the hit
  scleraN: N; // vein-perturbed normal outside the cornea
  ior: N;
}

const TAU = 2 * Math.PI;

function eyeShade(src: Std, P: ParamStore, frames: EyeFrames): EyeShade {
  const u = eyeFrameNodes(frames);
  const view = (w: N, wv: number): N => cameraViewMatrix.mul(vec4(w, wv)).xyz;
  // which eye: the nearer centre (the UV's u = 0.5 seam belongs to both halves)
  const C0 = view(u.c0, 1);
  const C1 = view(u.c1, 1);
  const side = step(positionView.sub(C1).length(), positionView.sub(C0).length()).mul(u.ok1).max(float(1).sub(u.ok0));
  const pick = (a: N, b: N): N => mix(a, b, side);
  const C = mix(C0, C1, side);
  const A = view(pick(u.a0, u.a1), 0).normalize();
  const Ex0 = view(pick(u.e0, u.e1), 0);
  const Ex = Ex0.sub(A.mul(Ex0.dot(A))).normalize();
  const Ez = cross(A, Ex);
  const R = pick(u.r0, u.r1);
  const thetaC = pick(u.tc0, u.tc1);
  const ok = pick(u.ok0, u.ok1).mul(P.u('eye.refraction'));
  const corneaO = C.add(A.mul(pick(u.cz0, u.cz1)));
  const corneaR = pick(u.cr0, u.cr1);
  const ior = P.u('eye.ior');
  const rhoI = P.u('eye.irisRadiusMm').mul(0.001);
  const thetaI = asin(rhoI.div(R).min(0.95));
  // the fragment on the globe
  const d = positionView.sub(C);
  const a0 = d.dot(A);
  const rho0 = d.sub(A.mul(a0)).length();
  const theta0 = atan(rho0, a0);
  const inCornea = smoothstep(thetaC.add(0.004), thetaC.sub(0.02), theta0).mul(ok);
  // the view ray refracted at the cornea, to the iris plane
  const Nc = geometryNormal;
  const rd = refract(positionView.normalize(), Nc, float(1).div(ior));
  const plane = R.mul(thetaI.cos()).sub(P.u('eye.irisRecessMm').mul(0.001));
  const t = a0.sub(plane).max(0).div(rd.dot(A).negate().max(0.05));
  const H = d.add(rd.mul(t));
  const hx = H.dot(Ex);
  const hz = H.dot(Ez);
  const rho1 = vec2(hx, hz).length();
  // the opaque sclera bounds what the cornea shows: a ray past the iris root lands on its rim
  const theta1 = asin(rho1.min(rhoI.mul(0.995)).div(R).min(0.999));
  const phi1 = atan(hz, hx);
  const st = vec2(fract(phi1.div(TAU)).mul(0.5).add(side.mul(0.5)), float(1).sub(theta1.div(Math.PI).sqrt()));
  const eRho = Ex.mul(phi1.cos()).add(Ez.mul(phi1.sin()));
  const ePhi = Ez.mul(phi1.cos()).sub(Ex.mul(phi1.sin()));
  // relief: the eyes_normal map (tangent space on the polar UV: x = +u = phi, y = Blender +v = theta)
  const ns = P.u('eye.normalStrength');
  const dx = dFdx(uv());
  const dy = dFdy(uv());
  let irisN: N = A.add(eRho.mul(P.u('eye.irisCone')));
  let scleraN: N = geometryNormal;
  if (src.normalMap) {
    const ni = texture(src.normalMap, st).grad(dx, dy).xyz.mul(2).sub(1);
    irisN = irisN.add(ePhi.mul(ni.x.mul(ns))).add(eRho.mul(ni.y.mul(ns)));
    // outside the cornea: tangents along +u (phi) and Blender +v (away from the pole) on the globe
    const ns0 = texture(src.normalMap, uv()).xyz.mul(2).sub(1);
    const g = d.sub(A.mul(a0));
    const tRho = g.normalize();
    const tPhi = cross(A, tRho).normalize();
    const tTheta = tRho.mul(theta0.cos()).sub(A.mul(theta0.sin())); // away from the pole, on the sphere
    scleraN = geometryNormal.add(tPhi.mul(ns0.x.mul(ns))).add(tTheta.mul(ns0.y.mul(ns))).normalize();
  }
  return { C, A, Ex, Ez, R, thetaC, corneaO, corneaR, inCornea, H, eRho, ePhi, rhoI, st, irisN: irisN.normalize(), scleraN, ior };
}

/** A light's emitter rectangle (Blender area size; stage.ts puts it in userData.rect) in view space. */
interface RectUniforms {
  centre: N;
  hw: N;
  hh: N;
  radiance: N; // colour x intensity / area (the Blender area light's radiance)
  unshadowed: N; // colour x intensity (the spot's own colour before attenuation, shadow and cone)
}

const _m4 = new THREE.Matrix4();
const _q = new THREE.Quaternion();
const _C = new THREE.Quaternion().setFromRotationMatrix(new THREE.Matrix4().set(1, 0, 0, 0, 0, 0, 1, 0, 0, -1, 0, 0, 0, 0, 0, 1));

function rectUniforms(light: THREE.Light): RectUniforms | null {
  const rect = light.userData?.rect as { w: number; h: number; quaternion?: number[] | null } | undefined;
  const spot = light as THREE.SpotLight;
  if (!rect || !spot.isSpotLight) return null;
  const centre = uniform(new THREE.Vector3());
  const hw = uniform(new THREE.Vector3());
  const hh = uniform(new THREE.Vector3());
  const radiance = uniform(new THREE.Color());
  const unshadowed = uniform(new THREE.Color());
  // one update computes all: the rect's rotation as stage.ts would place a RectAreaLight there
  centre.onRenderUpdate((f: { camera: THREE.Camera }) => {
    const view = f.camera.matrixWorldInverse;
    spot.updateMatrixWorld();
    spot.target.updateMatrixWorld();
    const pos = new THREE.Vector3().setFromMatrixPosition(spot.matrixWorld);
    if (rect.quaternion) _q.fromArray(rect.quaternion).multiply(_C);
    else _q.setFromRotationMatrix(_m4.lookAt(pos, new THREE.Vector3().setFromMatrixPosition(spot.target.matrixWorld), spot.up));
    const rot = new THREE.Matrix4().makeRotationFromQuaternion(_q).premultiply(new THREE.Matrix4().extractRotation(view));
    hw.value.set(rect.w * 0.5, 0, 0).applyMatrix4(rot);
    hh.value.set(0, rect.h * 0.5, 0).applyMatrix4(rot);
    radiance.value.copy(spot.color).multiplyScalar(spot.intensity / Math.max(rect.w * rect.h, 1e-6));
    unshadowed.value.copy(spot.color).multiplyScalar(spot.intensity);
    return pos.applyMatrix4(view);
  });
  return { centre, hw, hh, radiance, unshadowed };
}

/** LTC GGX (f0 0.04) of a rectangle on normal Nn: the reflected radiance without the light colour. */
function ltcSpec(Nn: N, r: N, c: N, hw: N, hh: N): N {
  const { l1, l2 } = ltcTextures();
  const V = positionViewDirection;
  const t1 = l1.sample(LTC_Uv({ N: Nn, V, roughness: r }));
  const t2 = l2.sample(LTC_Uv({ N: Nn, V, roughness: r }));
  const mInv = mat3(vec3(t1.x, 0, t1.y), vec3(0, 1, 0), vec3(t1.z, 0, t1.w));
  const fres = t2.x.mul(0.04).add(t2.y.mul(0.96));
  const ev = LTC_Evaluate({ N: Nn, V, P: positionView, mInv, p0: c.add(hw).sub(hh), p1: c.sub(hw).sub(hh), p2: c.sub(hw).add(hh), p3: c.add(hw).add(hh) });
  return ev.mul(fres);
}

/** The cornea's (or any wet film's) specular for one direct light: the emitter's rectangle when the
 * light carries one (shadow and spot cone kept from three's light colour), else point GGX. */
function wetSpecular(P: ParamStore, input: DirectInput, Nn: N, rough: N): N {
  const { lightDirection: L, lightColor, lightNode } = input;
  const light = lightNode?.light;
  const ru = light && (P.get('eye.catchlightRect') as number) ? rectUniforms(light) : null;
  if (ru) {
    const toL = ru.centre.sub(positionView);
    const d2 = toL.dot(toL).max(1e-6);
    const lum = (c: N): N => c.dot(vec3(0.2126, 0.7152, 0.0722));
    // shadow x spot cone: three's light colour over the unattenuated one at this distance
    const vis = lum(lightColor).mul(d2).div(lum(ru.unshadowed).max(1e-9)).clamp(0, 1);
    return ru.radiance.mul(ltcSpec(Nn, rough, ru.centre, ru.hw, ru.hh)).mul(vis);
  }
  const s = BRDF_GGX({ lightDirection: L, f0: vec3(0.04), f90: float(1), roughness: rough, normalView: Nn });
  return lightColor.mul(Nn.dot(L).clamp()).mul(s);
}

class EyeLightingModel extends THREE.PhysicalLightingModel {
  constructor(
    private readonly P: ParamStore,
    private readonly screen: N | null = null,
    private readonly sh: EyeShade | null = null,
  ) {
    super(true);
  }

  override direct(input: unknown, builder?: unknown): void {
    const { lightDirection: L, lightColor, reflectedLight, lightNode } = input as DirectInput;
    const P = this.P;
    // the sclera's own wet specular (three's physical, on the vein normal; masked off on the cornea
    // by the material's specular intensity); its diffuse is replaced below
    const sink = vec3(0).toVar();
    super.direct({ ...(input as object), reflectedLight: { ...reflectedLight, directDiffuse: sink } } as never, builder as never);
    const occl = directOcclusion(P, null, null, this.screen, lightNode?.light);
    const eyeLight = lightNode?.light?.name === 'eye' ? P.u('eye.eyeLightDiffuse') : float(1);
    const lambert = BRDF_Lambert({ diffuseColor: diffuseColor.rgb });
    if (this.sh) {
      const sh = this.sh;
      // sclera: wrapped Lambert on the vein normal
      const wrap = P.u('eye.scleraWrap');
      const ndl = sh.scleraN.dot(L).add(wrap).div(float(1).add(wrap)).clamp();
      const scl = lightColor.mul(diffuseRamp(P, ndl));
      // iris: the light refracted by the cornea, entering where the ray from the iris hit toward
      // the light leaves the cornea sphere
      const Hp = sh.C.add(sh.H);
      const oc = Hp.sub(sh.corneaO);
      const b = oc.dot(L);
      const s = b.negate().add(b.mul(b).sub(oc.dot(oc).sub(sh.corneaR.mul(sh.corneaR))).max(0).sqrt());
      const E = Hp.add(L.mul(s));
      const Nen = E.sub(sh.corneaO).normalize();
      const Lr = refract(L.negate(), Nen, float(1).div(sh.ior)).negate(); // toward the light, inside the eye
      // limbal shading: the refracted path back out must leave through the cornea, not the sclera
      const thE = atan(E.sub(sh.C).sub(sh.A.mul(E.sub(sh.C).dot(sh.A))).length(), E.sub(sh.C).dot(sh.A));
      const vis = smoothstep(sh.thetaC.add(0.03), sh.thetaC.sub(0.03), thE);
      const cosIn = Nen.dot(L).clamp();
      const fresIn = float(1).sub(float(0.04).add(float(0.96).mul(float(1).sub(cosIn).pow(5))));
      // irradiance: the flux through the cornea patch (T cos at entry) in the refracted beam, whose
      // cross-section grows by 1 / cos(t) at the interface, onto the iris normal: E = T E0 cos(i) nI / cos(t)
      // (the cornea's curvature, which converges the beam, is the caustic term below)
      const nI = sh.irisN.dot(Lr).clamp();
      const tilt = nI.div(Nen.dot(Lr).max(0.25)).min(2);
      // caustic: the cornea converges the light onto the iris side away from it (outer half)
      const Llat = L.sub(sh.A.mul(L.dot(sh.A)));
      const far = sh.eRho.dot(Llat.normalize()).negate().clamp().mul(smoothstep(0.2, 0.9, sh.H.sub(sh.A.mul(sh.H.dot(sh.A))).length().div(sh.rhoI)));
      const caustic = P.u('eye.causticGain').mul(nI.pow(2)).mul(far).mul(Llat.length()).mul(cosIn);
      const iris = lightColor.mul(fresIn).mul(diffuseRamp(P, cosIn.mul(tilt).mul(vis).clamp()).add(caustic.mul(vis)));
      const diff = mix(scl, iris, sh.inCornea).mul(lambert).mul(occl).mul(eyeLight);
      reflectedLight.directDiffuse.addAssign(diff);
    } else {
      reflectedLight.directDiffuse.addAssign(sink.mul(occl).mul(eyeLight));
    }
    // cornea: the wet lobe on the geometric (eyeball / cornea) normal, the emitter's shape when known
    const r = float(P.u('eye.corneaRoughness')).clamp(0.02, 1);
    reflectedLight.directSpecular.addAssign(wetSpecular(P, input as DirectInput, geometryNormal, r).mul(P.u('eye.corneaStrength')));
  }

  override directRectArea(input: unknown, builder?: unknown): void {
    const i = input as RectInput;
    super.directRectArea(input as never, builder as never);
    // the cornea's reflection of an area light is the light's shape: LTC GGX (f0 0.04) on the eyeball normal
    const r = float(this.P.u('eye.corneaRoughness')).clamp(0.02, 1);
    i.reflectedLight.directSpecular.addAssign(i.lightColor.mul(ltcSpec(geometryNormal, r, i.lightPosition, i.halfWidth, i.halfHeight)).mul(this.P.u('eye.corneaStrength')));
  }
}

export class EyeMaterial extends THREE.MeshPhysicalNodeMaterial {
  private readonly screen: N | null;
  private readonly sh: EyeShade;

  constructor(src: Std, private readonly P: ParamStore, screenAO?: THREE.Texture | null) {
    super();
    copyStd(this, src);
    const sh = eyeShade(src, P, new EyeFrames());
    this.sh = sh;
    const base = src.map ? texture(src.map, uv()) : vec4(1);
    // the iris seen through the cornea (refracted lookup); gradients from the mesh UV (the atan seam)
    const seen = src.map ? texture(src.map, sh.st).grad(dFdx(uv()), dFdy(uv())) : vec4(1);
    const limbV = float(1).sub(asin(sh.rhoI.div(sh.R).min(0.95)).div(Math.PI).sqrt());
    const ring = smoothstep(P.u('eye.limbalWidth'), float(0), sh.st.y.sub(limbV).abs()).mul(P.u('eye.limbalDarken'));
    const rgb = mix(base.rgb, seen.rgb.mul(float(1).sub(ring)), sh.inCornea);
    this.colorNode = vec4(albedo(P, 'eye', rgb), 1);
    if (src.roughnessMap) this.roughnessNode = texture(src.roughnessMap, uv()).g;
    this.normalNode = sh.scleraN;
    this.specularIntensityNode = float(1).sub(sh.inCornea);
    // the wet surface's reflection of the surroundings (the Cycles hero's set and fill veil the iris):
    // a constant radiance x Fresnel, a stand-in until the set-bounce environment (checkpoint 3 §2.5)
    const nv = geometryNormal.dot(positionViewDirection).clamp();
    const fres = float(0.04).add(float(0.96).mul(float(1).sub(nv).pow(5)));
    this.emissiveNode = P.u('eye.envVeil').mul(fres).mul(P.u('eye.corneaStrength'));
    this.metalnessNode = float(0);
    this.clearcoat = 0; // the cornea lobe lives in EyeLightingModel
    this.normalMap = null;
    this.screen = screenAONode(screenAO);
  }

  override setupLightingModel(): THREE.PhysicalLightingModel {
    return new EyeLightingModel(this.P, this.screen, this.sh);
  }
}

/** T18 lid shell (eyes_hq.game_parts): a black overlay on the globe under each lid, alpha from its
 * map (contact occlusion + the lash root shadow; <= 0.45 so the GTAO prepass's alpha test drops it),
 * scaled by eye.shellStrength. Unlit, no depth write, casts no shadow. */
export class EyeShellMaterial extends THREE.MeshPhysicalNodeMaterial {
  constructor(src: Std, P: ParamStore) {
    super();
    copyStd(this, src);
    const a = src.map ? texture(src.map).a : float(0);
    this.colorNode = vec4(0, 0, 0, 1);
    this.specularIntensityNode = float(0); // stage.link gives every material its lights: keep it black
    this.opacityNode = a.mul(P.u('eye.shellStrength')).div(0.45).clamp(0, 1);
    this.transparent = true;
    this.depthWrite = false;
    this.alphaTest = 0.001; // and a map: the AO prepass keeps the map's alpha test (ao.ts swapOf)
    this.maskShadowNode = bool(false);
  }
}

/** T18 tear meniscus: a wet, partly transparent film line; its specular takes the emitter's shape. */
class EyeWetLightingModel extends THREE.PhysicalLightingModel {
  constructor(
    private readonly P: ParamStore,
    private readonly screen: N | null,
  ) {
    super();
  }

  override direct(input: unknown, builder?: unknown): void {
    const { reflectedLight, lightNode } = input as DirectInput;
    const diffuse = vec3(0).toVar();
    const spec = vec3(0).toVar();
    super.direct({ ...(input as object), reflectedLight: { directDiffuse: diffuse, directSpecular: spec } } as never, builder as never);
    reflectedLight.directDiffuse.addAssign(diffuse.mul(directOcclusion(this.P, null, null, this.screen, lightNode?.light)));
    reflectedLight.directSpecular.addAssign(wetSpecular(this.P, input as DirectInput, normalView, float(0.05)).mul(this.P.u('eye.meniscusSpec')));
  }
}

export class EyeWetMaterial extends THREE.MeshPhysicalNodeMaterial {
  private readonly screen: N | null;

  constructor(src: Std, private readonly P: ParamStore, screenAO?: THREE.Texture | null) {
    super();
    copyStd(this, src);
    this.transparent = true;
    this.opacity = src.opacity;
    this.depthWrite = false;
    this.screen = screenAONode(screenAO);
    this.maskShadowNode = bool(false);
  }

  override setupLightingModel(): THREE.PhysicalLightingModel {
    return new EyeWetLightingModel(this.P, this.screen);
  }
}

// --------------------------------------------------------------------------------------- cloth

class ClothLightingModel extends THREE.PhysicalLightingModel {
  constructor(
    private readonly P: ParamStore,
    private readonly fuzzKey: string,
    sheen: boolean,
    private readonly ao: N | null,
    private readonly screen: N | null = null,
  ) {
    super(false, sheen);
  }

  override direct(input: unknown, builder?: unknown): void {
    const { lightDirection: L, lightColor, reflectedLight, lightNode } = input as DirectInput;
    // the physical direct term into a scratch diffuse accumulator, so only the diffuse is occluded
    const diffuse = vec3(0).toVar();
    super.direct({ ...(input as object), reflectedLight: { ...reflectedLight, directDiffuse: diffuse } } as never, builder as never);
    reflectedLight.directDiffuse.addAssign(diffuse.mul(directOcclusion(this.P, this.ao, 'cloth.directAO', this.screen, lightNode?.light)));
    const nv = normalView.dot(positionViewDirection).clamp();
    const rim = float(1).sub(nv).pow(this.P.u('cloth.fuzzPower'));
    const wrapNL = normalView.dot(L).mul(0.5).add(0.5).clamp();
    reflectedLight.directDiffuse.addAssign(
      lightColor.mul(this.P.u('cloth.fuzzColor')).mul(rim).mul(wrapNL).mul(this.P.u(this.fuzzKey)).mul(1 / Math.PI),
    );
  }

  override directRectArea(input: unknown, builder?: unknown): void {
    const i = input as RectInput;
    // LTC diffuse + specular, the diffuse occluded like direct()
    const diffuse = vec3(0).toVar();
    super.directRectArea({ ...(i as object), reflectedLight: { ...i.reflectedLight, directDiffuse: diffuse } } as never, builder as never);
    i.reflectedLight.directDiffuse.addAssign(diffuse.mul(directOcclusion(this.P, this.ao, 'cloth.directAO', this.screen, i.lightNode?.light)));
    // sheen (accumulated by the physical direct()) and the fuzz rim from the point equivalent; the
    // punctual diffuse / specular of that call are discarded (the LTC has them)
    const pt = rectAsPoint(i);
    const scratch = { directDiffuse: vec3(0).toVar(), directSpecular: vec3(0).toVar() };
    super.direct({ lightDirection: pt.L, lightColor: pt.color, reflectedLight: scratch } as never, builder as never);
    const nv = normalView.dot(positionViewDirection).clamp();
    const rim = float(1).sub(nv).pow(this.P.u('cloth.fuzzPower'));
    const wrapNL = normalView.dot(pt.L).mul(0.5).add(0.5).clamp();
    i.reflectedLight.directDiffuse.addAssign(
      pt.color.mul(this.P.u('cloth.fuzzColor')).mul(rim).mul(wrapNL).mul(this.P.u(this.fuzzKey)).mul(1 / Math.PI),
    );
  }
}

/** suit_detail.json (blender/character/suit_textures.detail_record): the weave as a tiled detail normal. */
export interface WeaveDetail {
  repeat: number;
  angle_rad: number;
  strength: number;
}
export interface WeaveSidecar {
  tile: THREE.Texture;
  materials: Record<string, WeaveDetail>;
}
/** Rib periods across the tile (suit_textures.DETAIL_PERIODS). */
const WEAVE_TILE_PERIODS = 8;

export class ClothMaterial extends THREE.MeshPhysicalNodeMaterial {
  private aoTex: N | null = null;
  private readonly screen: N | null;

  constructor(
    src: Std,
    private readonly P: ParamStore,
    private readonly fuzzKey: 'cloth.fuzzStrength' | 'shirt.fuzzStrength',
    weave?: WeaveSidecar | null,
    screenAO?: THREE.Texture | null,
  ) {
    super();
    copyStd(this, src);
    const c = mapRGBA(src);
    this.colorNode = vec4(albedo(P, 'cloth', c.rgb), 1);
    const wd = weave?.materials[src.name];
    if (src.normalMap && weave && wd) {
      // the weave from the tiled, mipmapped detail normal (it is no longer in the baked atlas)
      const ca = Math.cos(wd.angle_rad);
      const sa = Math.sin(wd.angle_rad);
      const u0 = uv().mul(wd.repeat);
      const uvT = vec2(u0.x.mul(ca).sub(u0.y.mul(sa)), u0.x.mul(sa).add(u0.y.mul(ca)));
      // rib periods per pixel; mips flatten the tile on their own, the fade guards the last octave
      const perPx = fwidth(uvT).length().mul(WEAVE_TILE_PERIODS);
      const fade = float(1).sub(smoothstep(0.3, 0.6, perPx));
      const d = texture(weave.tile, uvT).rgb.mul(2).sub(1);
      // back to the atlas UV frame (transpose of the rotation above)
      const dxy = vec2(d.x.mul(ca).add(d.y.mul(sa)), d.x.mul(sa).negate().add(d.y.mul(ca)));
      const k = fade.mul(wd.strength).mul(P.u('cloth.weaveStrength'));
      const b = texture(src.normalMap).rgb.mul(2).sub(1);
      const n = vec3(b.xy.add(dxy.mul(k)), b.z).normalize();
      this.normalNode = normalMap(n.mul(0.5).add(0.5), vec2(src.normalScale.x, src.normalScale.y));
    } else if (src.normalMap) {
      // micro-twill: diagonal ridges added to the tangent-space normal before decoding
      const ph = uv().x.add(uv().y).mul(P.u('cloth.twillFreq'));
      // fade out where a ridge is under ~3 px (no aliasing / moire: the procedural tile is unfiltered)
      const fade = float(1).sub(fwidth(ph).mul(1 / 2.0)).clamp(0, 1);
      const slope = sin(ph).mul(P.u('cloth.twillStrength')).mul(fade).mul(0.5);
      const nTex = texture(src.normalMap).rgb.add(vec3(slope, slope.negate(), 0));
      this.normalNode = normalMap(nTex, vec2(src.normalScale.x, src.normalScale.y));
    }
    if (src.roughnessMap) this.roughnessNode = texture(src.roughnessMap).g.mul(P.u('cloth.roughnessScale')).clamp(0.05, 1);
    else this.roughnessNode = float(src.roughness).mul(P.u('cloth.roughnessScale')).clamp(0.05, 1);
    if (src.aoMap) {
      this.aoTex = texture(src.aoMap).r;
      this.aoNode = this.aoTex;
    }
    if (this.sheen > 0) this.sheenNode = vec3(this.sheenColor.r, this.sheenColor.g, this.sheenColor.b).mul(P.u('cloth.sheenScale'));
    this.screen = screenAONode(screenAO);
  }

  override setupLightingModel(): THREE.PhysicalLightingModel {
    return new ClothLightingModel(this.P, this.fuzzKey, this.useSheen, this.aoTex, this.screen);
  }
}

// --------------------------------------------------------------------------------------- generic

/** glTF PBR as exported; T10: the direct diffuse under the screen AO (teeth, tongue, nails, leather). */
class GenericLightingModel extends THREE.PhysicalLightingModel {
  constructor(
    private readonly P: ParamStore,
    private readonly screen: N,
  ) {
    super();
  }

  override direct(input: unknown, builder?: unknown): void {
    const { reflectedLight, lightNode } = input as DirectInput;
    const diffuse = vec3(0).toVar();
    super.direct({ ...(input as object), reflectedLight: { ...reflectedLight, directDiffuse: diffuse } } as never, builder as never);
    reflectedLight.directDiffuse.addAssign(diffuse.mul(directOcclusion(this.P, null, null, this.screen, lightNode?.light)));
  }
}

export class GenericMaterial extends THREE.MeshPhysicalNodeMaterial {
  private readonly screen: N | null;

  constructor(
    src: Std,
    private readonly P: ParamStore | null = null,
    screenAO?: THREE.Texture | null,
  ) {
    super();
    copyStd(this, src);
    this.alphaTest = src.alphaTest;
    this.screen = P ? screenAONode(screenAO) : null;
  }

  override setupLightingModel(): THREE.PhysicalLightingModel {
    return this.screen && this.P ? new GenericLightingModel(this.P, this.screen) : super.setupLightingModel();
  }
}

// --------------------------------------------------------------------------------------- assignment

export interface MaterialSet {
  byName: Map<string, THREE.MeshPhysicalNodeMaterial>;
  roles: Map<string, Role>;
}

/** Replace every glTF material under `root` by its node material (one instance per source material). */
export function assignMaterials(root: THREE.Object3D, P: ParamStore, side: Sidecars, msaa: boolean): MaterialSet {
  const byName = new Map<string, THREE.MeshPhysicalNodeMaterial>();
  const roles = new Map<string, Role>();
  // T20: hair materials whose meshes carry the baked directional occlusion, packed in TEXCOORD_1 y (older
  // builds hold the card side there, +-1, so 1 - v is 0 or 2; a packed value is a 24-bit integer)
  const occ = new Set<string>();
  root.traverse((o) => {
    const m = o as THREE.Mesh;
    const a = m.isMesh ? m.geometry.attributes.uv1 : undefined;
    if (!a) return;
    let packed = false;
    for (let i = 0; i < a.count && !packed; i++) packed = 1 - a.getY(i) > 2.5;
    if (!packed) return;
    for (const mt of Array.isArray(m.material) ? m.material : [m.material]) occ.add(mt.name);
  });
  const make = (src: Std): THREE.MeshPhysicalNodeMaterial => {
    const role = roleOf(src.name);
    roles.set(src.name, role);
    switch (role) {
      case 'skin': {
        const cm = side.curvature?.[src.name];
        return new SkinMaterial(src, P, {
          sss: cm && side.sssLUT ? { lut: side.sssLUT, curvature: cm } : null,
          screenAO: side.screenAO,
          detail: side.skinDetail,
          ssss: !!side.ssss,
        });
      }
      case 'hair':
        return new HairMaterial(src, P, { prefix: 'hair', msaa, screenAO: side.screenAO, dirOcc: occ.has(src.name) });
      case 'facial':
      case 'lash':
        // brows: their own gains (T9b: the brow region is calibrated apart from the beard)
        return new HairMaterial(src, P, { prefix: src.name.startsWith('brows') ? 'brows' : 'facialHair', msaa, screenAO: side.screenAO });
      case 'eye':
        return new EyeMaterial(src, P, side.screenAO);
      case 'eyeshell':
        return new EyeShellMaterial(src, P);
      case 'eyewet':
        return new EyeWetMaterial(src, P, side.screenAO);
      case 'cloth':
        return new ClothMaterial(src, P, 'cloth.fuzzStrength', side.weave, side.screenAO);
      case 'shirt':
        return new ClothMaterial(src, P, 'shirt.fuzzStrength', side.weave, side.screenAO);
      default:
        return new GenericMaterial(src, P, side.screenAO);
    }
  };
  // T19 shared light terms (lighting.ts): specular occlusion from the GTAO term on every model but the
  // hair cards' (their fibre lobes keep the strand occlusion, T10), and the direct-diffuse AO on the rect
  // path of the eye and generic models (the others apply it in their own directRectArea)
  const screen = screenTerm(side.screenAO);
  const specOcc = (P.get('light.specOcclusion') as number) > 0;
  const shared = (nm: THREE.MeshPhysicalNodeMaterial, role: Role): void => {
    const orig = nm.setupLightingModel.bind(nm);
    const opts = {
      specOcclusion: specOcc && role !== 'hair' && role !== 'facial' && role !== 'lash',
      rectDiffuseAO: role === 'generic',
      // the models whose rect diffuse is three's LTC (the skin and hair models take rectAsPoint's F)
      ltcDiffuse: role === 'generic' || role === 'cloth' || role === 'shirt',
      // the eye's diffuse (refracted iris, limbus, sclera; its own direct AO) is in direct(): under the
      // rects from their point equivalent, as the skin's
      rectDiffuseAsPoint: role === 'eye',
    };
    nm.setupLightingModel = ((b: unknown) => withSharedLighting((orig as unknown as (x: unknown) => THREE.LightingModel)(b), P, screen, opts)) as typeof nm.setupLightingModel;
  };
  root.traverse((o) => {
    const m = o as THREE.Mesh;
    if (!m.isMesh) return;
    const swap = (src: THREE.Material): THREE.Material => {
      const s = src as Std;
      let nm = byName.get(s.name);
      if (!nm) {
        nm = make(s);
        shared(nm, roles.get(s.name)!);
        byName.set(s.name, nm);
      }
      return nm;
    };
    m.material = Array.isArray(m.material) ? m.material.map(swap) : swap(m.material);
    m.castShadow = true;
    m.receiveShadow = true;
    m.frustumCulled = false; // skinned: the bind-pose bounds are wrong once posed
  });
  return { byName, roles };
}
