// First TSL material set for the character (neutral realistic baseline; review §3.3 table).
// Each material is a MeshPhysicalNodeMaterial with a small custom lighting model; every tunable is a
// uniform from the ParamStore. The glTF materials are replaced by name / role (assignMaterials).
//
//   skin   wrap-lit diffuse with per-channel wrap + normal blur (curvature-scaled; cheap pre-integrated
//          SSS stand-in), a terminator scatter tint, dual-lobe GGX specular
//   hair   dual-lobe Kajiya-Kay (white primary shifted to the root, albedo-tinted secondary to the tip,
//          shifts jittered per strand ID / card / along-strand wave, exponents scaled by per-strand
//          roughness), a tinted TT (backlit) lobe and a wrapped multiple-scatter body (T9b), flow / depth /
//          ORM strand maps from the GLB (KHR_materials_anisotropy + occlusion / metallicRoughness),
//          alpha to coverage (4x MSAA) with hashed alpha when there is no MSAA
//   facial beard / brow cards on the same path and maps (prefix facialHair); lashes along the UV bitangent
//   eye    clearcoat cornea lobe on the geometric normal, limbal darkening, iris parallax
//   cloth  glTF sheen + a 1 - N.V fuzz rim + a procedural micro-twill normal
import * as THREE from 'three/webgpu';
import * as TSL from 'three/tsl';
import type { ParamStore } from './params';
import { albedo, diffuseRamp } from './style';
// TSL's TypeScript types are too narrow for shader-graph code; the graph is checked at build.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const { BRDF_GGX, BRDF_Lambert, LTC_Evaluate, LTC_Uv, mat3, diffuseColor, faceDirection, float, fract, fwidth, hash, mix, normalMap, normalView, normalViewGeometry, positionView, positionViewDirection, roughness, sin, smoothstep, bitangentView, tangentView, texture, uv, vec2, vec3, vec4, vertexColor } = TSL as any;

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
  reflectedLight: { directDiffuse: N; directSpecular: N };
}
interface RectInput {
  lightColor: N;
  lightPosition: N;
  halfWidth: N;
  halfHeight: N;
  reflectedLight: { directDiffuse: N; directSpecular: N };
  ltc_1: N;
  ltc_2: N;
}

/** A rect light (three's LTC path, ?area=rims|all) as the point light the custom terms (skin SSS
 * diffuse, cloth sheen + fuzz) understand: direction to the centre and the intensity of a small
 * Lambertian emitter, I = L A cos(theta_light), over d^2. The LTC keeps the specular; three's stock
 * directRectArea has no sheen and knows nothing of these terms, so without this they vanish. */
function rectAsPoint(i: RectInput): { L: N; color: N } {
  const toL = i.lightPosition.sub(positionView);
  const d2 = toL.dot(toL).max(1e-4);
  const L = toL.normalize();
  const n = i.halfWidth.cross(i.halfHeight);
  const area = n.length().mul(4);
  const cosL = n.normalize().dot(L).max(0); // shines along local -z: the lit side has L along +z
  return { L, color: i.lightColor.mul(area).mul(cosL).div(d2) };
}

export type Role = 'skin' | 'hair' | 'facial' | 'lash' | 'eye' | 'cloth' | 'shirt' | 'generic';

export function roleOf(name: string): Role {
  if (name.startsWith('skin_')) return 'skin';
  if (name === 'hair' || name === 'hair_cards') return 'hair';
  if (/^(beard|brows)(_cards)?$/.test(name)) return 'facial';
  if (name.startsWith('eyelash')) return 'lash';
  if (name.startsWith('eyes')) return 'eye';
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

interface SkinSSS {
  lut: THREE.Texture;
  curvature: N; // encoded curvature at this fragment (skin_tex.curvature)
}

class SkinLightingModel extends THREE.PhysicalLightingModel {
  constructor(
    private readonly P: ParamStore,
    private readonly ao: N | null,
    private readonly sss: SkinSSS | null,
  ) {
    super();
  }

  override direct(input: unknown): void {
    const { lightDirection: L, lightColor, reflectedLight } = input as DirectInput;
    const P = this.P;
    const blur = P.u('skin.normalBlur');
    const nl = (b: N) => mix(normalView, geometryNormal, b).normalize().dot(L);
    const nl3 = vec3(nl(blur.x), nl(blur.y), nl(blur.z));
    // screen-space curvature (1/m), normalised so a ~5 cm radius reads 1
    const curv = fwidth(geometryNormal).length().div(fwidth(positionView).length().max(1e-5)).mul(0.05).clamp(0, 1);
    const g = P.u('skin.curvatureGain');
    const wrap = P.u('skin.wrap').mul(mix(float(1).sub(g), float(1).add(g), curv));
    const diff = diffuseRamp(P, nl3.add(wrap).div(wrap.add(1)).max(0));
    // terminator scatter band (centred on N.L = 0 of the blurred green normal)
    const band = smoothstep(P.u('skin.scatterWidth'), float(0), nl3.y.abs()).mul(P.u('skin.scatterStrength'));
    const tint = vec3(1).add(P.u('skin.scatterColor').mul(band));
    const occ = directAO(this.ao, P.u('skin.directAO'));
    let d: N = diff.mul(tint);
    if (this.sss) {
      // pre-integrated SSS: per channel D(N.L of that channel's blurred normal, curvature)
      const cv = this.sss.curvature.mul(P.u('skin.sssCurvatureGain')).clamp(0.002, 1);
      const at = (x: N) => texture(this.sss!.lut, vec2(x.mul(0.5).add(0.5).clamp(0, 1), cv));
      const pre = vec3(at(nl3.x).r, at(nl3.y).g, at(nl3.z).b);
      d = mix(d, diffuseRamp(P, pre), P.u('skin.sss'));
    }
    reflectedLight.directDiffuse.addAssign(lightColor.mul(d).mul(occ).mul(BRDF_Lambert({ diffuseColor: diffuseColor.rgb })));
    // dual-lobe specular
    const r = roughness.clamp(0.08, 1);
    const f0 = vec3(P.u('skin.specF0'));
    const s1 = BRDF_GGX({ lightDirection: L, f0, f90: float(1), roughness: r.mul(P.u('skin.lobe1Roughness')).clamp(0.05, 1) });
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
    this.direct({ lightDirection: pt.L, lightColor: pt.color, reflectedLight: { directDiffuse: i.reflectedLight.directDiffuse, directSpecular: vec3(0).toVar() } });
  }
}

export class SkinMaterial extends THREE.MeshPhysicalNodeMaterial {
  private aoTex: N | null = null;
  private sss: SkinSSS | null = null;

  constructor(src: Std, private readonly P: ParamStore, sss?: { lut: THREE.Texture; curvature: THREE.Texture } | null) {
    super();
    copyStd(this, src);
    const c = mapRGBA(src);
    this.colorNode = vec4(albedo(P, 'skin', c.rgb), 1);
    this.normalNode = normalNode(src, P.u('skin.normalScale'));
    if (src.roughnessMap) {
      this.roughnessNode = texture(src.roughnessMap).g.mul(P.u('skin.roughnessScale')).add(P.u('skin.roughnessBias')).clamp(0.05, 1);
    }
    this.metalnessNode = float(0);
    if (src.aoMap) {
      this.aoTex = texture(src.aoMap).r;
      this.aoNode = mix(float(1), this.aoTex, P.u('skin.aoIntensity'));
    }
    if (sss) this.sss = { lut: sss.lut, curvature: texture(sss.curvature).r };
  }

  override setupLightingModel(): THREE.PhysicalLightingModel {
    return new SkinLightingModel(this.P, this.aoTex, this.sss);
  }
}

// --------------------------------------------------------------------------------------- hair

interface HairNodes {
  tangent: N; // view-space fibre tangent
  shiftOff: N; // per-fragment lobe shift offset: per-strand + per-card jitter + the along-strand wave tilt
  rough: N; // per-strand roughness (ORM G): scales the lobe exponents around hair.roughRef
  specScale: N; // per-card specular scale (UV1 u: the baker's layer_spec) x the occlusion on the lobes
  tint: N; // warm scatter colour: the albedo's chroma, saturated (luminance 1)
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
    const { lightDirection: L, lightColor, reflectedLight } = input as DirectInput;
    const P = this.P;
    const pre = this.prefix;
    const N = normalView;
    const V = positionViewDirection;
    const T = this.h.tangent;
    const w = P.u('hair.diffuseWrap');
    const nl = N.dot(L);
    const diff = diffuseRamp(P, nl.add(w).div(w.add(1)).max(0));
    reflectedLight.directDiffuse.addAssign(lightColor.mul(diff).mul(BRDF_Lambert({ diffuseColor: diffuseColor.rgb })));
    // T9b: the multiple-scattering body (the warm mid-brown of the Chiang hero along the lengths): a
    // fully wrapped, albedo-chroma tinted diffuse. Dark hair is lit mostly by light that went through
    // other fibres, which comes out with the fibre's transmittance colour, not white.
    const msWrap = nl.add(1).mul(0.5).max(0);
    reflectedLight.directDiffuse.addAssign(lightColor.mul(diffuseRamp(P, msWrap)).mul(this.h.tint).mul(P.u(`${pre}.scatter`)).mul(1 / Math.PI));
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
    const spec = P.u('hair.spec1Color').mul(s1).mul(P.u(`${pre}.spec1`)).add(this.h.tint.mul(s2).mul(P.u(`${pre}.spec2`))).mul(this.h.specScale);
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
    reflectedLight.directSpecular.addAssign(lightColor.mul(this.h.tint).mul(fwd.mul(cone).mul(P.u(`${pre}.tt`))).mul(this.h.specScale));
  }

  override directRectArea(input: unknown): void {
    // the anisotropic fibre lobes have no LTC form: the whole term from the rect's point equivalent
    const i = input as RectInput;
    const pt = rectAsPoint(i);
    this.direct({ lightDirection: pt.L, lightColor: pt.color, reflectedLight: i.reflectedLight });
  }
}

/** Runtime inputs next to the GLB that glTF has no slot for (blender/character/export.write_sidecars). */
export interface Sidecars {
  weave?: WeaveSidecar | null;
  /** skin material name -> curvature map (skin_<part>_curvature.png) */
  curvature?: Record<string, THREE.Texture | null>;
  sssLUT?: THREE.Texture | null;
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

  constructor(src: Std, private readonly P: ParamStore, opts: { prefix: 'hair' | 'facialHair' | 'brows'; msaa: boolean }) {
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
    this.nodes = { tangent: T, shiftOff, rough, specScale, tint };
    this.normalNode = null; // shade the card as a fibre bundle: the smooth proxy normal from the GLB
    this.roughnessNode = rough;
    this.metalnessNode = float(0);
    this.side = THREE.DoubleSide;
    this.alphaTest = P.get(`${opts.prefix}.alphaTest`) as number;
    if (opts.msaa) this.alphaToCoverage = true;
    else this.alphaHash = true;
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
      const a = src.map ? texture(src.map).a : float(1);
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

class EyeLightingModel extends THREE.PhysicalLightingModel {
  constructor(private readonly P: ParamStore) {
    super(true);
  }

  override direct(input: unknown, builder?: unknown): void {
    const { lightDirection: L, lightColor, reflectedLight } = input as DirectInput;
    // iris / sclera: plain physical
    super.direct(input as never, builder as never);
    // cornea: a sharp GGX lobe on the geometric (eyeball) normal
    const Ng = geometryNormal;
    const r = float(this.P.u('eye.corneaRoughness')).clamp(0.02, 1);
    const s = BRDF_GGX({ lightDirection: L, f0: vec3(0.04), f90: float(1), roughness: r, normalView: Ng });
    reflectedLight.directSpecular.addAssign(lightColor.mul(Ng.dot(L).clamp()).mul(s).mul(this.P.u('eye.corneaStrength')));
  }

  override directRectArea(input: unknown, builder?: unknown): void {
    const i = input as RectInput;
    super.directRectArea(input as never, builder as never);
    // the cornea's reflection of an area light is the light's shape: LTC GGX (f0 0.04) on the eyeball normal
    const Ng = geometryNormal;
    const V = positionViewDirection;
    const r = float(this.P.u('eye.corneaRoughness')).clamp(0.02, 1);
    const t1 = i.ltc_1.sample(LTC_Uv({ N: Ng, V, roughness: r })).toVar();
    const t2 = i.ltc_2.sample(LTC_Uv({ N: Ng, V, roughness: r })).toVar();
    const mInv = mat3(vec3(t1.x, 0, t1.y), vec3(0, 1, 0), vec3(t1.z, 0, t1.w));
    const fres = t2.x.mul(0.04).add(t2.y.mul(0.96));
    const c = i.lightPosition;
    const hw = i.halfWidth;
    const hh = i.halfHeight;
    const ev = LTC_Evaluate({ N: Ng, V, P: positionView, mInv, p0: c.add(hw).sub(hh), p1: c.sub(hw).sub(hh), p2: c.sub(hw).add(hh), p3: c.add(hw).add(hh) });
    i.reflectedLight.directSpecular.addAssign(i.lightColor.mul(fres).mul(ev).mul(this.P.u('eye.corneaStrength')));
  }
}

export class EyeMaterial extends THREE.MeshPhysicalNodeMaterial {
  constructor(src: Std, private readonly P: ParamStore) {
    super();
    copyStd(this, src);
    const vt = vec3(positionViewDirection.dot(tangentView), positionViewDirection.dot(bitangentView), positionViewDirection.dot(normalView).max(0.2));
    const limbusV = P.u('eye.limbusV');
    const iris = smoothstep(limbusV, limbusV.add(0.01), uv().y);
    // parallax: the iris sits behind the cornea; shift its lookup against the view direction
    const off = vt.xy.div(vt.z).mul(P.u('eye.irisDepth')).mul(iris);
    const st = uv().sub(vec2(off.x, off.y.negate()));
    const base = src.map ? texture(src.map, st) : vec4(1);
    const ring = smoothstep(P.u('eye.limbalWidth'), float(0), uv().y.sub(limbusV).abs()).mul(P.u('eye.limbalDarken'));
    this.colorNode = vec4(albedo(P, 'eye', base.rgb).mul(float(1).sub(ring)), 1);
    if (src.roughnessMap) this.roughnessNode = texture(src.roughnessMap, st).g;
    this.metalnessNode = float(0);
    this.clearcoat = 0; // the cornea lobe lives in EyeLightingModel
  }

  override setupLightingModel(): THREE.PhysicalLightingModel {
    return new EyeLightingModel(this.P);
  }
}

// --------------------------------------------------------------------------------------- cloth

class ClothLightingModel extends THREE.PhysicalLightingModel {
  constructor(
    private readonly P: ParamStore,
    private readonly fuzzKey: string,
    sheen: boolean,
    private readonly ao: N | null,
  ) {
    super(false, sheen);
  }

  override direct(input: unknown, builder?: unknown): void {
    const { lightDirection: L, lightColor, reflectedLight } = input as DirectInput;
    // the physical direct term into a scratch diffuse accumulator, so only the diffuse is occluded
    const diffuse = vec3(0).toVar();
    super.direct({ ...(input as object), reflectedLight: { ...reflectedLight, directDiffuse: diffuse } } as never, builder as never);
    reflectedLight.directDiffuse.addAssign(diffuse.mul(directAO(this.ao, this.P.u('cloth.directAO'))));
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
    i.reflectedLight.directDiffuse.addAssign(diffuse.mul(directAO(this.ao, this.P.u('cloth.directAO'))));
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

  constructor(
    src: Std,
    private readonly P: ParamStore,
    private readonly fuzzKey: 'cloth.fuzzStrength' | 'shirt.fuzzStrength',
    weave?: WeaveSidecar | null,
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
  }

  override setupLightingModel(): THREE.PhysicalLightingModel {
    return new ClothLightingModel(this.P, this.fuzzKey, this.useSheen, this.aoTex);
  }
}

// --------------------------------------------------------------------------------------- generic

export class GenericMaterial extends THREE.MeshPhysicalNodeMaterial {
  constructor(src: Std) {
    super();
    copyStd(this, src);
    this.alphaTest = src.alphaTest;
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
  const make = (src: Std): THREE.MeshPhysicalNodeMaterial => {
    const role = roleOf(src.name);
    roles.set(src.name, role);
    switch (role) {
      case 'skin': {
        const cm = side.curvature?.[src.name];
        return new SkinMaterial(src, P, cm && side.sssLUT ? { lut: side.sssLUT, curvature: cm } : null);
      }
      case 'hair':
        return new HairMaterial(src, P, { prefix: 'hair', msaa });
      case 'facial':
      case 'lash':
        // brows: their own gains (T9b: the brow region is calibrated apart from the beard)
        return new HairMaterial(src, P, { prefix: src.name.startsWith('brows') ? 'brows' : 'facialHair', msaa });
      case 'eye':
        return new EyeMaterial(src, P);
      case 'cloth':
        return new ClothMaterial(src, P, 'cloth.fuzzStrength', side.weave);
      case 'shirt':
        return new ClothMaterial(src, P, 'shirt.fuzzStrength', side.weave);
      default:
        return new GenericMaterial(src);
    }
  };
  root.traverse((o) => {
    const m = o as THREE.Mesh;
    if (!m.isMesh) return;
    const swap = (src: THREE.Material): THREE.Material => {
      const s = src as Std;
      let nm = byName.get(s.name);
      if (!nm) {
        nm = make(s);
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
