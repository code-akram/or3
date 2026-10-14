// First TSL material set for the character (neutral realistic baseline; review §3.3 table).
// Each material is a MeshPhysicalNodeMaterial with a small custom lighting model; every tunable is a
// uniform from the ParamStore. The glTF materials are replaced by name / role (assignMaterials).
//
//   skin   wrap-lit diffuse with per-channel wrap + normal blur (curvature-scaled; cheap pre-integrated
//          SSS stand-in), a terminator scatter tint, dual-lobe GGX specular
//   hair   dual-lobe Kajiya-Kay (white primary shifted to the root, albedo-tinted secondary to the tip,
//          shifts jittered per strand ID), tangent from the flow sidecar, root / depth AO, alpha to
//          coverage (4x MSAA) with hashed alpha when there is no MSAA
//   facial beard / brow / lash shells and cards on the hair path, tangent = UV bitangent
//   eye    clearcoat cornea lobe on the geometric normal, limbal darkening, iris parallax
//   cloth  glTF sheen + a 1 - N.V fuzz rim + a procedural micro-twill normal
import * as THREE from 'three/webgpu';
import * as TSL from 'three/tsl';
import type { ParamStore } from './params';
import { albedo, diffuseRamp } from './style';
// TSL's TypeScript types are too narrow for shader-graph code; the graph is checked at build.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const { BRDF_GGX, BRDF_Lambert, diffuseColor, float, fwidth, hash, mix, normalMap, normalView, normalViewGeometry, positionView, positionViewDirection, roughness, sin, smoothstep, bitangentView, tangentView, texture, uv, vec2, vec3, vec4, vertexColor } = TSL as any;

/* eslint-disable @typescript-eslint/no-explicit-any */
type N = any;
type Std = THREE.MeshStandardMaterial & Partial<THREE.MeshPhysicalMaterial>;
interface DirectInput {
  lightDirection: N;
  lightColor: N;
  reflectedLight: { directDiffuse: N; directSpecular: N };
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

class SkinLightingModel extends THREE.PhysicalLightingModel {
  constructor(private readonly P: ParamStore) {
    super();
  }

  override direct(input: unknown): void {
    const { lightDirection: L, lightColor, reflectedLight } = input as DirectInput;
    const P = this.P;
    const blur = P.u('skin.normalBlur');
    const nl = (b: N) => mix(normalView, normalViewGeometry, b).normalize().dot(L);
    const nl3 = vec3(nl(blur.x), nl(blur.y), nl(blur.z));
    // screen-space curvature (1/m), normalised so a ~5 cm radius reads 1
    const curv = fwidth(normalViewGeometry).length().div(fwidth(positionView).length().max(1e-5)).mul(0.05).clamp(0, 1);
    const g = P.u('skin.curvatureGain');
    const wrap = P.u('skin.wrap').mul(mix(float(1).sub(g), float(1).add(g), curv));
    const diff = diffuseRamp(P, nl3.add(wrap).div(wrap.add(1)).max(0));
    // terminator scatter band (centred on N.L = 0 of the blurred green normal)
    const band = smoothstep(P.u('skin.scatterWidth'), float(0), nl3.y.abs()).mul(P.u('skin.scatterStrength'));
    const tint = vec3(1).add(P.u('skin.scatterColor').mul(band));
    reflectedLight.directDiffuse.addAssign(lightColor.mul(diff).mul(tint).mul(BRDF_Lambert({ diffuseColor: diffuseColor.rgb })));
    // dual-lobe specular
    const r = roughness.clamp(0.08, 1);
    const f0 = vec3(P.u('skin.specF0'));
    const s1 = BRDF_GGX({ lightDirection: L, f0, f90: float(1), roughness: r.mul(P.u('skin.lobe1Roughness')).clamp(0.05, 1) });
    const s2 = BRDF_GGX({ lightDirection: L, f0, f90: float(1), roughness: r.mul(P.u('skin.lobe2Roughness')).clamp(0.05, 1) });
    const dotNL = normalView.dot(L).clamp();
    reflectedLight.directSpecular.addAssign(lightColor.mul(dotNL).mul(mix(s1, s2, P.u('skin.lobeMix'))).mul(P.u('skin.specGain')));
  }
}

export class SkinMaterial extends THREE.MeshPhysicalNodeMaterial {
  constructor(src: Std, private readonly P: ParamStore) {
    super();
    copyStd(this, src);
    const c = mapRGBA(src);
    this.colorNode = vec4(albedo(P, 'skin', c.rgb), 1);
    this.normalNode = normalNode(src, P.u('skin.normalScale'));
    if (src.roughnessMap) {
      this.roughnessNode = texture(src.roughnessMap).g.mul(P.u('skin.roughnessScale')).add(P.u('skin.roughnessBias')).clamp(0.05, 1);
    }
    this.metalnessNode = float(0);
    if (src.aoMap) this.aoNode = mix(float(1), texture(src.aoMap).r, P.u('skin.aoIntensity'));
  }

  override setupLightingModel(): THREE.PhysicalLightingModel {
    return new SkinLightingModel(this.P);
  }
}

// --------------------------------------------------------------------------------------- hair

interface HairNodes {
  tangent: N; // view-space fibre tangent
  jitter: N; // per-strand shift jitter in [-1, 1]
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
    const N = normalView;
    const V = positionViewDirection;
    const T = this.h.tangent;
    const w = P.u('hair.diffuseWrap');
    const nl = N.dot(L);
    const diff = diffuseRamp(P, nl.add(w).div(w.add(1)).max(0));
    reflectedLight.directDiffuse.addAssign(lightColor.mul(diff).mul(BRDF_Lambert({ diffuseColor: diffuseColor.rgb })));
    const H = L.add(V).normalize();
    const j = this.h.jitter.mul(P.u('hair.shiftJitter'));
    const kk = (shift: N, exp: N) => {
      const t = T.add(N.mul(shift.add(j))).normalize();
      const th = t.dot(H);
      const sinTH = float(1).sub(th.mul(th)).max(0).sqrt();
      // Kajiya-Kay lobe; strength is a plain multiplier (no energy normalisation, see params)
      return sinTH.pow(exp);
    };
    const s1 = kk(P.u('hair.shift1'), P.u('hair.exponent1'));
    const s2 = kk(P.u('hair.shift2'), P.u('hair.exponent2'));
    const atten = nl.mul(0.75).add(0.25).clamp(0, 1);
    const tint = diffuseColor.rgb.max(1e-4).sqrt();
    const spec = P.u('hair.spec1Color').mul(s1).mul(P.u(`${this.prefix}.spec1`)).add(tint.mul(s2).mul(P.u(`${this.prefix}.spec2`)));
    reflectedLight.directSpecular.addAssign(lightColor.mul(spec).mul(atten));
  }
}

export interface HairSidecars {
  flow?: THREE.Texture | null; // RG flow (0.5 + 0.5 x), B depth, A AO
  data?: THREE.Texture | null; // R coverage, G root-to-tip, B strand ID
}

export class HairMaterial extends THREE.MeshPhysicalNodeMaterial {
  private readonly nodes: HairNodes;
  readonly prefix: string;

  constructor(src: Std, private readonly P: ParamStore, opts: { prefix: 'hair' | 'facialHair'; side?: HairSidecars; msaa: boolean }) {
    super();
    copyStd(this, src);
    this.prefix = opts.prefix;
    const flow = opts.side?.flow ?? null;
    const data = opts.side?.data ?? null;
    const c = mapRGBA(src);
    let col = c.rgb;
    if (this.vertexColors) col = col.mul(vertexColor().rgb);
    let ao: N = float(1);
    if (data) {
      const d = texture(data);
      ao = ao.mul(mix(float(1).sub(P.u('hair.rootAO')), float(1), smoothstep(0, 0.45, d.g)));
    }
    if (flow) {
      const f = texture(flow);
      ao = ao.mul(mix(float(1).sub(P.u('hair.depthAO')), float(1), f.b)).mul(f.a);
    }
    this.colorNode = vec4(albedo(P, opts.prefix, col).mul(ao), c.a);
    this.vertexColors = false; // folded into colorNode above
    // tangent: flow (UV space) through the exported tangent frame; default along +v (the bitangent)
    let tUV: N = vec2(0, 1);
    if (flow) tUV = texture(flow).rg.mul(2).sub(1);
    const T = tangentView.mul(tUV.x).add(bitangentView.mul(tUV.y)).normalize().mul(P.u('hair.tangentSign'));
    const id = data ? texture(data).b : hash(uv().mul(4096).floor().x.add(uv().mul(4096).floor().y.mul(4096)));
    this.nodes = { tangent: T, jitter: id.mul(2).sub(1) };
    this.normalNode = null; // shade the card as a fibre bundle: the smooth proxy normal from the GLB
    this.roughnessNode = float(0.6);
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
    const Ng = normalViewGeometry;
    const r = float(this.P.u('eye.corneaRoughness')).clamp(0.02, 1);
    const s = BRDF_GGX({ lightDirection: L, f0: vec3(0.04), f90: float(1), roughness: r, normalView: Ng });
    reflectedLight.directSpecular.addAssign(lightColor.mul(Ng.dot(L).clamp()).mul(s).mul(this.P.u('eye.corneaStrength')));
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
  ) {
    super(false, sheen);
  }

  override direct(input: unknown, builder?: unknown): void {
    const { lightDirection: L, lightColor, reflectedLight } = input as DirectInput;
    super.direct(input as never, builder as never);
    const nv = normalView.dot(positionViewDirection).clamp();
    const rim = float(1).sub(nv).pow(this.P.u('cloth.fuzzPower'));
    const wrapNL = normalView.dot(L).mul(0.5).add(0.5).clamp();
    reflectedLight.directDiffuse.addAssign(
      lightColor.mul(this.P.u('cloth.fuzzColor')).mul(rim).mul(wrapNL).mul(this.P.u(this.fuzzKey)).mul(1 / Math.PI),
    );
  }
}

export class ClothMaterial extends THREE.MeshPhysicalNodeMaterial {
  constructor(src: Std, private readonly P: ParamStore, private readonly fuzzKey: 'cloth.fuzzStrength' | 'shirt.fuzzStrength') {
    super();
    copyStd(this, src);
    const c = mapRGBA(src);
    this.colorNode = vec4(albedo(P, 'cloth', c.rgb), 1);
    if (src.normalMap) {
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
    if (src.aoMap) this.aoNode = texture(src.aoMap).r;
    if (this.sheen > 0) this.sheenNode = vec3(this.sheenColor.r, this.sheenColor.g, this.sheenColor.b).mul(P.u('cloth.sheenScale'));
  }

  override setupLightingModel(): THREE.PhysicalLightingModel {
    return new ClothLightingModel(this.P, this.fuzzKey, this.useSheen);
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
export function assignMaterials(root: THREE.Object3D, P: ParamStore, side: HairSidecars, msaa: boolean): MaterialSet {
  const byName = new Map<string, THREE.MeshPhysicalNodeMaterial>();
  const roles = new Map<string, Role>();
  const make = (src: Std): THREE.MeshPhysicalNodeMaterial => {
    const role = roleOf(src.name);
    roles.set(src.name, role);
    if (role === 'facial' || role === 'lash') {
      // review §1.9 S2: the bytes are linear values in an sRGB-tagged image
      if (src.map && P.get('facialHair.linearFix') === 1) {
        src.map.colorSpace = THREE.NoColorSpace;
        src.map.needsUpdate = true;
      }
    }
    switch (role) {
      case 'skin':
        return new SkinMaterial(src, P);
      case 'hair':
        return new HairMaterial(src, P, { prefix: 'hair', side: src.name === 'hair_cards' ? side : {}, msaa });
      case 'facial':
      case 'lash':
        return new HairMaterial(src, P, { prefix: 'facialHair', msaa });
      case 'eye':
        return new EyeMaterial(src, P);
      case 'cloth':
        return new ClothMaterial(src, P, 'cloth.fuzzStrength');
      case 'shirt':
        return new ClothMaterial(src, P, 'shirt.fuzzStrength');
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
