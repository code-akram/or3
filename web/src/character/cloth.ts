// The suit's cloth path (T13 items 7-8): one material class for every suit cloth (the made suit's
// t13*_wool / *_lining / shirt materials and the lofted suit_wool / suit_silk / suit_vest / suit_shirt),
// separate from the T6 ClothMaterial in materials/index.ts, which stays as the fallback (?cloth=1).
//
//   - Per-cloth grazing response. T19 measured the shader balls per light against Cycles (direct
//     light only, net of the world): wool 1.02 / 1.04 / 0.67 and silk 1.06 / 1.09 / 2.20 under key /
//     fill / rim. The T6 model had one sheen scale and one fuzz rim for every cloth, calibrated under
//     the key. Here each cloth kind has its own sheen scale, fuzz strength, fuzz power and fuzz wrap,
//     fitted per light on the balls (bench/m1/v4/cloth_balls.py, report t13-suit-rebuild.md item 7).
//   - Pose-blended wrinkle normals (blender/character/suit_wrinkle.py): per made-suit material up to
//     two RGBA maps, four wrinkle groups (arms raised, arms down / crook, hip, torso) as tangent-space
//     XY deltas, weighted per frame from the suit's corrective cone weights (DeformRuntime) on the
//     vertex's own side (the bind-pose x of the vertex, +x = the character's left).
import * as THREE from 'three/webgpu';
import * as TSL from 'three/tsl';
import type { ParamStore } from './materials/params';
import { albedo } from './materials/style';
import { copyStd, directOcclusion, mapRGBA, rectAsPoint, screenAONode } from './materials/index';
import type { DirectInput, RectInput, Std, WeaveSidecar } from './materials/index';

/* eslint-disable @typescript-eslint/no-explicit-any */
type N = any;
const { faceDirection, float, fwidth, normalMap, normalView, normalViewGeometry, positionGeometry, positionViewDirection, smoothstep, texture, uniform, uv, vec2, vec3, vec4 } = TSL as any;

export type ClothKind = 'wool' | 'silk' | 'lining' | 'shirt';

/** The cloth kind of a glTF material name, or null (not a suit cloth: buttons, shoes, leather). */
export function clothKind(name: string): ClothKind | null {
  if (name === 'suit_shirt' || /^t13s_/.test(name)) return name.endsWith('_lining') ? 'lining' : 'shirt';
  if (name === 'suit_silk' || name.endsWith('_silk')) return 'silk';
  if (name.endsWith('_lining')) return 'lining';
  if (/^suit_(wool|wool_b|vest)$/.test(name) || /^t13[a-z]?_wool$/.test(name)) return 'wool';
  return null;
}

// --------------------------------------------------------------------------------------- wrinkles

/** Wrinkle groups: cone stems (character.rig.json morphs suit_<stem>_<side>; the spine's have no side).
 * The same table as blender/character/suit_wrinkle.GROUPS. */
export const WRINKLE_GROUPS: Record<string, string[]> = {
  arm_up: ['arm_abd90', 'arm_abd90_h', 'arm_abd135', 'arm_flex90', 'arm_flex90_h', 'arm_flex135'],
  arm_down: ['arm_down', 'arm_back', 'elbow90', 'elbow90_h'],
  hip: ['thigh_flex90', 'thigh_flex90_h', 'thigh_abd40', 'thigh_ext30'],
  torso: ['spine_flex40', 'spine_ext20', 'spine_tilt25_l', 'spine_tilt25_r', 'spine_turn40_l', 'spine_turn40_r'],
};
const GROUP_NAMES = Object.keys(WRINKLE_GROUPS);

/** suit_wrinkle.json: per material one array texture of three RGB layers holding the four groups'
 *  tangent-space XY deltas in order (layer 0: g0.x g0.y g1.x; layer 1: g1.y g2.x g2.y; layer 2: g3.x
 *  g3.y -). One binding per material: the fragment stage's 16 sampled textures (shadow maps and screen
 *  textures included) leave the cloth no room for two more. Opaque RGB, so the canvas decode cannot
 *  premultiply the codes away. */
export interface WrinkleSidecar {
  range: number;
  maps: Record<string, THREE.DataArrayTexture>;
}

const weightsL: N = uniform(new THREE.Vector4());
const weightsR: N = uniform(new THREE.Vector4());
let source: (() => Record<string, number>) | null = null;

/** The per-frame cone weights (DeformRuntime.morphWeights) the wrinkle groups read. */
export function setWrinkleSource(fn: (() => Record<string, number>) | null): void {
  source = fn;
}

/** Group weights per side from cone weights: each group takes its largest cone on that side. */
export function wrinkleWeights(w: Record<string, number>): { l: number[]; r: number[] } {
  const l: number[] = [];
  const r: number[] = [];
  for (const g of GROUP_NAMES) {
    let a = 0;
    let b = 0;
    for (const st of WRINKLE_GROUPS[g]!) {
      a = Math.max(a, w[`suit_${st}_l`] ?? w[`suit_${st}`] ?? 0);
      b = Math.max(b, w[`suit_${st}_r`] ?? w[`suit_${st}`] ?? 0);
    }
    l.push(a);
    r.push(b);
  }
  return { l, r };
}

weightsL.onFrameUpdate(() => {
  if (!source) return;
  const { l, r } = wrinkleWeights(source());
  (weightsL.value as THREE.Vector4).set(l[0]!, l[1]!, l[2]!, l[3]!);
  (weightsR.value as THREE.Vector4).set(r[0]!, r[1]!, r[2]!, r[3]!);
});

export async function loadWrinkles(base: string, _load?: unknown): Promise<WrinkleSidecar | null> {
  try {
    const r = await fetch(base + 'suit_wrinkle.json');
    if (!r.ok) return null;
    const j = (await r.json()) as { range: number; materials: Record<string, string[]> };
    const maps: Record<string, THREE.DataArrayTexture> = {};
    for (const [m, files] of Object.entries(j.materials)) {
      const t = await loadLayers(files.map((f) => base + f));
      if (t) maps[m] = t;
    }
    return { range: j.range, maps };
  } catch {
    return null;
  }
}

async function loadLayers(urls: string[]): Promise<THREE.DataArrayTexture | null> {
  const bmps = await Promise.all(
    urls.map(async (u) => {
      const r = await fetch(u);
      if (!r.ok) throw new Error(u);
      return createImageBitmap(await r.blob(), { colorSpaceConversion: 'none', premultiplyAlpha: 'none' });
    }),
  );
  const w = bmps[0]!.width;
  const h = bmps[0]!.height;
  if (bmps.some((b) => b.width !== w || b.height !== h)) return null;
  const data = new Uint8Array(w * h * 4 * bmps.length);
  const cx = new OffscreenCanvas(w, h).getContext('2d', { willReadFrequently: true });
  if (!cx) return null;
  bmps.forEach((b, i) => {
    cx.clearRect(0, 0, w, h);
    cx.drawImage(b, 0, 0);
    data.set(cx.getImageData(0, 0, w, h).data, i * w * h * 4);
    b.close();
  });
  const t = new THREE.DataArrayTexture(data, w, h, bmps.length);
  t.format = THREE.RGBAFormat;
  t.type = THREE.UnsignedByteType;
  t.colorSpace = THREE.NoColorSpace;
  t.generateMipmaps = true;
  t.minFilter = THREE.LinearMipmapLinearFilter;
  t.magFilter = THREE.LinearFilter;
  t.anisotropy = 4;
  t.needsUpdate = true;
  return t;
}

/** The tangent-space XY delta of the wrinkle maps at this fragment, or null. */
function wrinkleDelta(P: ParamStore, maps: THREE.DataArrayTexture | undefined, range: number): N | null {
  if (!maps) return null;
  // side: the bind-pose x (glTF +x = the character's left), blended over +-4 cm at the centre line
  const s = smoothstep(-0.04, 0.04, positionGeometry.x);
  const w = weightsR.mix(weightsL, s);
  const l0 = texture(maps, uv()).depth(0).rgb.mul(2).sub(1);
  const l1 = texture(maps, uv()).depth(1).rgb.mul(2).sub(1);
  const l2 = texture(maps, uv()).depth(2).rgb.mul(2).sub(1);
  const d: N = l0.xy.mul(w.x)
    .add(vec2(l0.z, l1.x).mul(w.y))
    .add(l1.yz.mul(w.z))
    .add(l2.xy.mul(w.w));
  return d.mul(range).mul(P.u('suitCloth.wrinkleStrength'));
}

// --------------------------------------------------------------------------------------- lighting

class SuitClothLightingModel extends THREE.PhysicalLightingModel {
  constructor(
    private readonly P: ParamStore,
    private readonly kind: ClothKind,
    sheen: boolean,
    private readonly ao: N | null,
    private readonly screen: N | null,
  ) {
    super(false, sheen);
  }

  /** The fuzz: a retro rim of loose fibres, (1 - N.V)^power x a wrapped N.L, per cloth kind, on the
   *  interpolated geometric normal: on the weave-mapped normal it lit single silhouette pixels at full
   *  strength (4-8 px > 200 on the wool ball per light), a sparkle the fibre halo should not have. */
  private fuzz(L: N, color: N): N {
    const k = `suitCloth.${this.kind}`;
    const ng = normalViewGeometry.mul(faceDirection);
    const nv = ng.dot(positionViewDirection).clamp();
    const rim = float(1).sub(nv).pow(this.P.u(`${k}.fuzzPower`));
    const wr = this.P.u(`${k}.fuzzWrap`);
    const nl = ng.dot(L);
    const t = this.P.u('suitCloth.fuzzTerminator');
    // the wrap's tail past the terminator is self-shadowed in Cycles; here only acne holes lit it
    const wrapNL = nl.add(wr).div(float(1).add(wr)).clamp().mul(smoothstep(t.negate(), t, nl));
    return color.mul(this.P.u('cloth.fuzzColor')).mul(rim).mul(wrapNL).mul(this.P.u(`${k}.fuzzStrength`)).mul(1 / Math.PI);
  }

  /** The base specular's grazing falloff, 1 - specGraze x (1 - N.V)^specGrazePower: the silk's GGX
   *  lobe at grazing (Fresnel to white) is about twice Cycles' under the rim light (T19: 2.20), with no
   *  sheen or fuzz at all; a lower roughness or F0 would cost the key highlight instead. */
  private graze(): N {
    const k = `suitCloth.${this.kind}`;
    const nv = normalView.dot(positionViewDirection).clamp();
    return float(1).sub(float(1).sub(nv).pow(this.P.u(`${k}.specGrazePower`)).mul(this.P.u(`${k}.specGraze`))).clamp();
  }

  override direct(input: unknown, builder?: unknown): void {
    const { lightDirection: L, lightColor, reflectedLight, lightNode } = input as DirectInput;
    const diffuse = vec3(0).toVar();
    const spec = vec3(0).toVar();
    super.direct({ ...(input as object), reflectedLight: { ...reflectedLight, directDiffuse: diffuse, directSpecular: spec } } as never, builder as never);
    reflectedLight.directSpecular.addAssign(spec.mul(this.graze()));
    reflectedLight.directDiffuse.addAssign(diffuse.mul(directOcclusion(this.P, this.ao, 'cloth.directAO', this.screen, lightNode?.light)));
    reflectedLight.directDiffuse.addAssign(this.fuzz(L, lightColor));
  }

  override directRectArea(input: unknown, builder?: unknown): void {
    const i = input as RectInput;
    const diffuse = vec3(0).toVar();
    const spec = vec3(0).toVar();
    super.directRectArea({ ...(i as object), reflectedLight: { ...i.reflectedLight, directDiffuse: diffuse, directSpecular: spec } } as never, builder as never);
    i.reflectedLight.directSpecular.addAssign(spec.mul(this.graze()));
    i.reflectedLight.directDiffuse.addAssign(diffuse.mul(directOcclusion(this.P, this.ao, 'cloth.directAO', this.screen, i.lightNode?.light)));
    // the sheen (accumulated by the physical direct()) and the fuzz from the rect's point equivalent;
    // that call's own diffuse and specular are dropped (the LTC has them)
    const pt = rectAsPoint(i);
    const scratch = { directDiffuse: vec3(0).toVar(), directSpecular: vec3(0).toVar() };
    super.direct({ lightDirection: pt.L, lightColor: pt.color, reflectedLight: scratch } as never, builder as never);
    i.reflectedLight.directDiffuse.addAssign(this.fuzz(pt.L, pt.color));
  }
}

const WEAVE_TILE_PERIODS = 8;

export class SuitClothMaterial extends THREE.MeshPhysicalNodeMaterial {
  private aoTex: N | null = null;
  private readonly screen: N | null;

  constructor(
    src: Std,
    private readonly P: ParamStore,
    readonly kind: ClothKind,
    weave?: WeaveSidecar | null,
    wrinkle?: WrinkleSidecar | null,
    screenAO?: THREE.Texture | null,
  ) {
    super();
    copyStd(this, src);
    const c = mapRGBA(src);
    this.colorNode = vec4(albedo(P, 'cloth', c.rgb), 1);
    const wd = weave?.materials[src.name];
    const wk = wrinkle ? wrinkleDelta(P, wrinkle.maps[src.name], wrinkle.range) : null;
    if (src.normalMap) {
      let n: N = texture(src.normalMap).rgb.mul(2).sub(1);
      if (weave && wd) {
        // the weave from the tiled, mipmapped detail normal (as ClothMaterial)
        const ca = Math.cos(wd.angle_rad);
        const sa = Math.sin(wd.angle_rad);
        const u0 = uv().mul(wd.repeat);
        const uvT = vec2(u0.x.mul(ca).sub(u0.y.mul(sa)), u0.x.mul(sa).add(u0.y.mul(ca)));
        const perPx = fwidth(uvT).length().mul(WEAVE_TILE_PERIODS);
        const fade = float(1).sub(smoothstep(0.3, 0.6, perPx));
        const d = texture(weave.tile, uvT).rgb.mul(2).sub(1);
        const dxy = vec2(d.x.mul(ca).add(d.y.mul(sa)), d.x.mul(sa).negate().add(d.y.mul(ca)));
        n = vec3(n.xy.add(dxy.mul(fade.mul(wd.strength).mul(P.u('cloth.weaveStrength')))), n.z);
      }
      if (wk) n = vec3(n.xy.add(wk), n.z);
      this.normalNode = normalMap(n.normalize().mul(0.5).add(0.5), vec2(src.normalScale.x, src.normalScale.y));
    }
    if (src.roughnessMap) this.roughnessNode = texture(src.roughnessMap).g.mul(P.u('cloth.roughnessScale')).clamp(0.05, 1);
    else this.roughnessNode = float(src.roughness).mul(P.u('cloth.roughnessScale')).clamp(0.05, 1);
    if (src.aoMap) {
      this.aoTex = texture(src.aoMap).r;
      this.aoNode = this.aoTex;
    }
    if (this.sheen > 0) this.sheenNode = vec3(this.sheenColor.r, this.sheenColor.g, this.sheenColor.b).mul(P.u(`suitCloth.${kind}.sheenScale`));
    this.screen = screenAONode(screenAO);
  }

  override setupLightingModel(): THREE.PhysicalLightingModel {
    return new SuitClothLightingModel(this.P, this.kind, this.useSheen, this.aoTex, this.screen);
  }
}
