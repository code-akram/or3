// Area-light shadows and the shared light terms (T19, bench/m1/v4/checkpoint-3.md §2.5, §3.1 item 4).
//
// HYBRID LTC. Every studio / hero light is an LTC rect of its Blender size (stage.ts): the specular is the
// area-shaped LTC lobe (a strip highlight from the rims on skin and the wet eyes) and the diffuse is the
// rect's exact irradiance (three's LTC form factor; the custom diffuse models take the rect's vector form
// factor as a point-equivalent, materials/index.ts rectAsPoint). three's rect lights cast no shadow, so
// each light carries the shadow of an invisible SPOT PROXY at the same place: a spot-frustum depth map
// aimed at the view's subject, multiplied into the rect's colour (rect.shadow.shadowNode). The spot path
// (?ltc=0 / light.ltc 0) uses the same proxies.
//
// ONE MAP PER LIGHT. A light's twins (the hair-only twin of T10's deep hair shadow, the exported
// rim_hair / kicker_hair / fill_hair, any _props / _cloth / _skin twin) sample their parent's depth map
// through a LinkedShadowNode: same shadow camera and matrix, the parent's render target, no render of
// their own, their own filter (the deep hair filter for hair twins). Hero rig: 10 maps -> 5.
//
// FRUSTUM. The proxy aims its shadow camera at the view's subject and opens just wide enough for a sphere
// that holds the frame (fitShadow): a 2048 map spans ~1.2 m for the hero portrait (0.6 mm texels), so
// the parent maps are as fine as T10's head-focused twin maps were.
//
// PCSS (pcssFilter): the shadow filter of every parent light. A blocker search over the region a blocker
// up to light.pcssSearch above the receiver could shadow it from, the penumbra from the emitter size and
// the mean blocker distance (w = size (z_r - z_b) / z_b, Fernando 2005), then a percentage-closer filter
// of that radius with the hardware comparison sampler. Vogel taps rotated per pixel and per frame (IGN),
// so the temporal AA integrates them. Depth tests are in metres along the light axis, with a bias that
// grows with the filter radius (a receiver-plane stand-in).
//
// SPECULAR OCCLUSION (withSharedLighting): Lagarde & de Rousiers 2014, so = saturate((N.V + ao)^exp2(-16 r - 1)
// - 1 + ao) with ao the GTAO term (ao.ts). It multiplies every material's indirect specular (the set
// bounce) and each light's direct specular weighted like T10's direct-diffuse AO (the light's size over
// distance, floored at ao.lightWeightMin), x light.specOcclusion. The hair models keep their own strand
// occlusion (off there). It wraps the lighting model a material builds, so no material class changes.
//
// RECT DIFFUSE FORM FACTOR (withSharedLighting, opts.ltcDiffuse). three's LTC diffuse (the identity-matrix
// LTC_Evaluate) turns the rect's vector form factor F into a horizon-clipped form factor with the fit
// (|F|^2 + F.n) / (|F| + 1) (LTC.js, "a Journey" p.102), which equals F.n only for a light at the
// zenith; off axis it is high by about |F|^2 / (|F| + 1): for the hero fill (2 m square at 2.5 m,
// 57 deg off the chart's normal) that is +11 % (the per-light chart's fill excess after T19's exact
// irradiance on the custom models). The wrapper rescales that diffuse to the exact clipped sphere (Snyder 1996, the
// Frostbite illuminanceSphereOrDisk form): F.n when the equivalent cap is above the horizon, the
// clipped cap otherwise. The custom diffuse models (skin, hair) take F directly (rectAsPoint).
import * as THREE from 'three/webgpu';
import * as TSL from 'three/tsl';
import type { ParamStore } from './materials/params';
import { temporalFrame } from './temporal';
// TSL's TypeScript types are too narrow for shader-graph code; the graph is checked at build.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const T = TSL as any;
const { Fn, float, ivec2, vec2, vec3, reference, renderGroup, perspectiveDepthToViewZ, viewZToPerspectiveDepth, interleavedGradientNoise, vogelDiskSample, screenCoordinate, texture, uniform, normalView, normalWorld, positionWorld, positionView, positionViewDirection, roughness, mix, screenUV } = T;

/* eslint-disable @typescript-eslint/no-explicit-any */
type N = any;

// ---------------------------------------------------------------------------------------------- shadows

interface MapPair {
  shadowMap: THREE.RenderTarget;
  depthTexture: THREE.DepthTexture;
}
/** One render target per parent shadow (keyed by the proxy's LightShadow), made by whichever node builds first. */
const shared = new WeakMap<THREE.LightShadow, MapPair>();

/** A texture node of a shadow depth map for textureLoad. Every node of one texture shares a binding whose
 * sampler type the first generated node decides; the PCF taps need a comparison sampler, so the load nodes
 * declare one too (unused by textureLoad), or a shader that loads before it compares fails to compile. */
export function depthLoad(tex: THREE.Texture, ip: N): N {
  const base = texture(tex);
  base._samplerComparison = true;
  const n = base.load(ip);
  n._samplerComparison = true;
  return n;
}

function sharedTarget(owner: THREE.LightShadow, make: () => MapPair): MapPair {
  let p = shared.get(owner);
  if (!p) {
    p = make();
    shared.set(owner, p);
  }
  return p;
}

/** GRAZING NORMAL OFFSET: the receiver's shadow lookup moves out along its normal by
 * light.normalOffset texels x tan(N, L) (capped at light.slopeMax): a lit surface turning away from
 * the light (a cheek or a sphere's crescent under a grazing rim) otherwise reads its own bulk in the
 * map through the PCSS kernel and darkens what the form factor already fades. Added to the shadow
 * position three computes (its constant normalBias stays). */
function grazingOffset(node: any, P: ParamStore | null, builder: unknown, sp: N, base: (b: unknown, p: N) => N): N {
  if (!P) return base(builder, sp);
  const shadow = node.shadow as THREE.LightShadow;
  const cam = shadow.camera as THREE.PerspectiveCamera;
  const M = reference('matrix', 'mat4', shadow).setGroup(renderGroup);
  const mapSize = reference('mapSize', 'vec2', shadow).setGroup(renderGroup);
  const fov = reference('fov', 'float', cam).setGroup(renderGroup);
  const lp = uniform(new THREE.Vector3()).onRenderUpdate(() => lp.value.setFromMatrixPosition(cam.matrixWorld));
  const cosT = normalWorld.dot(lp.sub(positionWorld).normalize()).clamp(0.02, 1);
  const tanT = cosT.mul(cosT).oneMinus().sqrt().div(cosT).min(P.u('light.slopeMax'));
  const texel = sp.w.mul(fov.mul(Math.PI / 360).tan()).mul(2).div(mapSize.x);
  const extra = texel.mul(P.u('light.normalOffset')).mul(tanT);
  return base(builder, sp.add(M.mul(T.vec4(normalWorld.mul(extra), 0))));
}

/** The parent's shadow node: three's ShadowNode on the proxy spot, its render target registered for twins. */
export class OwnedShadowNode extends (THREE as any).ShadowNode {
  constructor(
    proxy: THREE.SpotLight,
    private readonly P: ParamStore | null = null,
  ) {
    super(proxy, proxy.shadow);
  }
  setupShadowCoord(builder: unknown, sp: N): N {
    return grazingOffset(this, this.P, builder, sp, (b, p) => super.setupShadowCoord(b, p));
  }
  setupRenderTarget(shadow: THREE.LightShadow, builder: unknown): MapPair {
    return sharedTarget(shadow, () => super.setupRenderTarget(shadow, builder));
  }
  _reset(): void {
    shared.delete(this.shadow);
    super._reset();
  }
}

/** A twin's shadow node: the parent's depth map and shadow matrix (this.light is the parent's proxy),
 * the twin's own LightShadow for its filter, bias and intensity; renders nothing. */
export class LinkedShadowNode extends (THREE as any).ShadowNode {
  constructor(
    proxy: THREE.SpotLight,
    twinShadow: THREE.LightShadow,
    private readonly owner: THREE.LightShadow,
    private readonly P: ParamStore | null = null,
  ) {
    super(proxy, twinShadow);
  }
  setupShadowCoord(builder: unknown, sp: N): N {
    return grazingOffset(this, this.P, builder, sp, (b, p) => super.setupShadowCoord(b, p));
  }
  setupRenderTarget(_shadow: THREE.LightShadow, builder: unknown): MapPair {
    // the parent's (the base method sizes it from the shadow it is given)
    const base = (THREE as any).ShadowNode.prototype.setupRenderTarget;
    return sharedTarget(this.owner, () => base.call(this, this.owner, builder));
  }
  updateBefore(): void {
    /* the parent renders the map */
  }
  _reset(): void {
    // the map is the parent's: drop the reference only
    this.shadowMap = null;
    this._currentShadowType = null;
  }
}

/** A twin LightShadow that shares the parent's camera, matrix and map size (the filters read them). */
export function linkedShadow(owner: THREE.LightShadow): THREE.LightShadow {
  // a SpotLightShadow (not exported by three/webgpu): the owner's class, then the shared fields
  const s = (owner as unknown as { clone(): THREE.LightShadow }).clone();
  s.camera = owner.camera;
  s.matrix = owner.matrix;
  s.mapSize = owner.mapSize;
  s.bias = 0;
  s.normalBias = 0;
  return s;
}

/** Aim a proxy's shadow frustum at a sphere (centre c, radius R) seen from the light position. */
export function fitShadow(proxy: THREE.SpotLight, c: THREE.Vector3, R: number): void {
  proxy.target.position.copy(c);
  const d = proxy.position.distanceTo(c);
  const half = Math.asin(Math.min(0.98, R / Math.max(d, 1e-3)));
  proxy.angle = Math.min(Math.PI / 2 - 0.05, half * 1.02);
  proxy.shadow.focus = 1;
  const cam = proxy.shadow.camera as THREE.PerspectiveCamera;
  // casters between the light and the sphere count: the near plane stays close to the light
  cam.near = Math.max(0.05, Math.min(d - R - 0.05, 0.25));
  cam.far = d + R + 0.25;
  cam.updateProjectionMatrix();
  proxy.updateMatrixWorld();
  proxy.target.updateMatrixWorld();
}

/** The PCSS filter of one light; `size` is the emitter's equal-area disc diameter (m). */
export function pcssFilter(P: ParamStore, size: number): N {
  const ls = uniform(size);
  const blockerTaps = Math.max(4, P.get('light.pcssBlockerTaps') as number);
  const taps = Math.max(4, P.get('light.pcssTaps') as number);
  return Fn(({ depthTexture, shadowCoord, shadow }: { depthTexture: THREE.DepthTexture; shadowCoord: N; shadow: THREE.LightShadow }) => {
    const mapSize = reference('mapSize', 'vec2', shadow).setGroup(renderGroup);
    const cam = shadow.camera as THREE.PerspectiveCamera;
    const near = reference('near', 'float', cam).setGroup(renderGroup);
    const far = reference('far', 'float', cam).setGroup(renderGroup);
    const fov = reference('fov', 'float', cam).setGroup(renderGroup);
    const tanHalf = fov.mul(Math.PI / 360).tan();
    const size = ls.mul(P.u('light.pcssScale'));
    const zr = perspectiveDepthToViewZ(shadowCoord.z, near, far).negate().toVar();
    // world size of a texel at the receiver's depth
    const texel = zr.mul(tanHalf).mul(2).div(mapSize.x).toVar();
    const b0 = P.u('light.shadowBias');
    // receiver-plane bias: over a filter radius of r texels a receiver tilted by theta from the light
    // direction spans r texel tan(theta) in depth; less and a convex terminator (a sphere's lit crescent
    // under a grazing rim) shadows itself through the PCF / PCSS kernel
    const lp = uniform(new THREE.Vector3()).onRenderUpdate(() => lp.value.setFromMatrixPosition(cam.matrixWorld));
    const cosT = normalWorld.dot(lp.sub(positionWorld).normalize()).clamp(0.02, 1);
    const tanT = cosT.mul(cosT).oneMinus().sqrt().div(cosT).min(P.u('light.slopeMax'));
    const slope = P.u('light.slopeBias').mul(tanT.max(P.u('light.slopeMin')));
    const capB = P.u('light.biasMax');
    const phi = interleavedGradientNoise(screenCoordinate.xy.add(temporalFrame.mod(64).mul(5.588238))).mul(6.28318530718).toVar();
    const hi = ivec2(mapSize.sub(1));
    // 1. blocker search: blockers up to `search` above the receiver, seen through the emitter
    const search = P.u('light.pcssSearch');
    const rs = size.mul(0.5).mul(search).div(zr.sub(search).max(0.05)).div(texel).clamp(1.5, P.u('light.pcssMaxTexels')).toVar();
    const bTest = b0.add(slope.mul(rs).mul(texel)).min(capB);
    let sum: N = float(0);
    let cnt: N = float(0);
    for (let i = 0; i < blockerTaps; i++) {
      const p = shadowCoord.xy.mul(mapSize).add(vogelDiskSample(i, blockerTaps, phi).mul(rs));
      const d = depthLoad(depthTexture, ivec2(p.floor()).clamp(ivec2(0, 0), hi)).r;
      const zo = perspectiveDepthToViewZ(d, near, far).negate();
      const blk = zo.lessThan(zr.sub(bTest));
      sum = sum.add(blk.select(zo, float(0)));
      cnt = cnt.add(blk.select(float(1), float(0)));
    }
    const zb = sum.div(cnt.max(1)).toVar();
    // 2. penumbra (world, at the receiver) -> filter radius in texels
    const wp = size.mul(zr.sub(zb).max(0)).div(zb.max(0.01));
    const r = wp.mul(0.5).div(texel).clamp(P.u('light.pcssMinTexels'), P.u('light.pcssMaxTexels')).toVar();
    // 3. percentage-closer filter of that radius (hardware compare against the biased receiver depth)
    const zc = zr.sub(b0.add(slope.mul(r).mul(texel)).min(capB));
    const ref = viewZToPerspectiveDepth(zc.negate(), near, far);
    const texelUV = vec2(1).div(mapSize);
    let acc: N = float(0);
    for (let i = 0; i < taps; i++) {
      const uv = shadowCoord.xy.add(vogelDiskSample(i, taps, phi.add(1.7)).mul(r).mul(texelUV));
      acc = acc.add(texture(depthTexture, uv).compare(ref));
    }
    const lit = acc.mul(1 / taps);
    // no blocker in the search region: fully lit (skips the PCF's own bias leaks)
    return cnt.greaterThan(0.5).select(lit, float(1));
  });
}

/** Equal-area disc diameter of a w x h emitter (the PCSS light size). */
export function discDiameter(w: number, h: number): number {
  return 2 * Math.sqrt((Math.max(w, 1e-3) * Math.max(h, 1e-3)) / Math.PI);
}

// ------------------------------------------------------------------------------- specular occlusion

/** Lagarde's specular occlusion from an AO value (see the header). */
export function lagardeSO(ao: N, nv: N, r: N): N {
  return nv.add(ao).pow(r.mul(-16).sub(1).exp2()).sub(1).add(ao).clamp(0, 1);
}

/** A rect edge's vector form factor term: three's LTC_EdgeVectorFormFactor (not exported), cross(v1, v2)
 * theta / sin(theta) / 2 pi for unit vectors v1, v2 toward two corners. */
export function edgeFormFactor(v1: N, v2: N): N {
  const x = v1.dot(v2);
  const y = x.abs();
  const a = y.mul(0.0145206).add(0.4965155).mul(y).add(0.8543985);
  const b = y.add(4.1616724).mul(y).add(3.417594);
  const v = a.div(b);
  const ts = x.greaterThan(0).select(v, x.mul(x).oneMinus().max(1e-7).inverseSqrt().mul(0.5).sub(v));
  return v1.cross(v2).mul(ts);
}

/** The vector form factor of a rect light (three's RectAreaLight input: centre, half axes, view space) at
 * view-space point p: the sum of its four edge terms, oriented toward the light (three's corner order
 * gives -F in view space; its LTC basis has a negated tangent, which flips it back). */
export function rectFormFactor(c: N, hw: N, hh: N, p: N): N {
  const q = [c.add(hw).sub(hh), c.sub(hw).sub(hh), c.sub(hw).add(hh), c.add(hw).add(hh)].map((x) => x.sub(p).normalize());
  let F: N = vec3(0);
  for (let k = 0; k < 4; k++) F = F.add(edgeFormFactor(q[k], q[(k + 1) % 4]));
  return F.dot(c.sub(p)).lessThan(0).select(F.negate(), F);
}

/** A rect light as a point light for models without an LTC form (see materials/index.ts rectAsPoint):
 * the direction F/|F|, the intensity of a plane facing it, pi L |F|; zero behind the emitter. */
export function rectPoint(c: N, hw: N, hh: N, color: N): { L: N; color: N } {
  const F = rectFormFactor(c, hw, hh, positionView);
  const front = hw.cross(hh).dot(c.sub(positionView)).greaterThan(0); // shines along local -z
  const f = F.length();
  return { L: F.div(f.max(1e-8)), color: color.mul(front.select(f.mul(Math.PI), float(0))) };
}

/** Exact horizon-clipped form factor of the sphere cap equivalent to vector form factor F (|F| = sin^2
 * sigma, F.n = |F| cos theta) on normal n: Snyder 1996 in Frostbite's illuminanceSphereOrDisk form / pi. */
export function clippedSphereFF(F: N, n: N): N {
  const l = F.length().max(1e-7).min(0.9999);
  const ct = F.dot(n).div(l).clamp(-1, 1);
  const st = ct.mul(ct).oneMinus().max(1e-7).sqrt();
  const x = l.reciprocal().sub(1).sqrt(); // cot sigma
  const y = x.negate().mul(ct.div(st)).clamp(-1, 1);
  const sy = st.mul(y.mul(y).oneMinus().max(0).sqrt());
  const part = ct.mul(T.acos(y)).sub(x.mul(sy)).mul(l).add(T.atan(sy.div(x))).div(Math.PI);
  return ct.mul(ct).greaterThan(l).select(l.mul(ct).max(0), part.max(0));
}

/** three's fit of the same (LTC_ClippedSphereFormFactor). */
function threeClippedFF(F: N, n: N): N {
  const l = F.length();
  return l.mul(l).add(F.dot(n)).div(l.add(1)).max(0);
}

interface Wrappable {
  direct?: (input: any, builder?: any) => void;
  directRectArea?: (input: any, builder?: any) => void;
  indirect?: (builder: any) => void;
}

/** Wrap a lighting model with the shared terms: specular occlusion from the screen AO on the direct
 * (per light) and indirect specular. `screen` = the GTAO term at this fragment (null: off). */
export function withSharedLighting(
  model: THREE.LightingModel,
  P: ParamStore,
  screen: N | null,
  opts: { specOcclusion: boolean; rectDiffuseAO?: boolean; ltcDiffuse?: boolean; rectDiffuseAsPoint?: boolean },
): THREE.LightingModel {
  const m = model as unknown as Wrappable;
  if (opts.rectDiffuseAsPoint && m.directRectArea && m.direct) {
    // a model whose own diffuse lives in direct() (the eye: the refracted iris, the limbus, the sclera
    // wrap) keeps it under rect lights too: the rect's LTC specular from its directRectArea, the diffuse
    // from direct() at the rect's point equivalent (rectPoint; direct()'s own specular dropped)
    const origR = m.directRectArea;
    const origD = m.direct;
    m.directRectArea = (input: any, builder?: any) => {
      origR.call(model, { ...input, reflectedLight: { ...input.reflectedLight, directDiffuse: vec3(0).toVar() } }, builder);
      const pt = rectPoint(input.lightPosition, input.halfWidth, input.halfHeight, input.lightColor);
      origD.call(model, { ...input, lightDirection: pt.L, lightColor: pt.color, reflectedLight: { ...input.reflectedLight, directSpecular: vec3(0).toVar() } }, builder);
    };
  }
  if (opts.ltcDiffuse && m.directRectArea) {
    // three's LTC diffuse x exact / fitted clipped form factor (see the header); before the AO wrap below
    const orig = m.directRectArea;
    m.directRectArea = (input: any, builder?: any) => {
      const diff = vec3(0).toVar();
      orig.call(model, { ...input, reflectedLight: { ...input.reflectedLight, directDiffuse: diff } }, builder);
      const F = rectFormFactor(input.lightPosition, input.halfWidth, input.halfHeight, positionView);
      const fit = threeClippedFF(F, normalView);
      const fix = fit.greaterThan(1e-7).select(clippedSphereFF(F, normalView).div(fit.max(1e-7)), float(1));
      input.reflectedLight.directDiffuse.addAssign(diff.mul(fix));
    };
  }
  if (!screen || (!opts.specOcclusion && !opts.rectDiffuseAO)) return model;
  const so = (): N => lagardeSO(screen, normalView.dot(positionViewDirection).clamp(0, 1), roughness.clamp(0.02, 1));
  const k = P.u('light.specOcclusion');
  const wrapDirect = (name: 'direct' | 'directRectArea', diffuseAO: boolean) => {
    const orig = m[name];
    if (!orig) return;
    m[name] = (input: any, builder?: any) => {
      const spec = vec3(0).toVar();
      const diff = diffuseAO ? vec3(0).toVar() : input.reflectedLight.directDiffuse;
      orig.call(model, { ...input, reflectedLight: { ...input.reflectedLight, directDiffuse: diff, directSpecular: spec } }, builder);
      const light = input.lightNode?.light as THREE.Light | undefined;
      const w = float((light?.userData?.aoWeight as number | undefined) ?? 1).max(P.u('ao.lightWeightMin')).min(1);
      // T10's direct-diffuse AO for the models whose rect path does not apply it (eye, generic)
      if (diffuseAO) input.reflectedLight.directDiffuse.addAssign(diff.mul(mix(float(1), screen, w.mul(P.u('ao.strength')))));
      input.reflectedLight.directSpecular.addAssign(opts.specOcclusion ? spec.mul(mix(float(1), so(), w.mul(k))) : spec);
    };
  };
  wrapDirect('direct', false);
  wrapDirect('directRectArea', !!opts.rectDiffuseAO);
  const ind = m.indirect;
  if (ind && opts.specOcclusion) {
    m.indirect = (builder: any) => {
      ind.call(model, builder);
      const rl = builder.context.reflectedLight;
      rl.indirectSpecular.mulAssign(mix(float(1), so(), k));
    };
  }
  return model;
}

/** The GTAO term at this fragment for the shared lighting (ao.ts SceneAO.texture), or null. */
export function screenTerm(tex: THREE.Texture | null | undefined): N | null {
  return tex ? texture(tex, screenUV).r : null;
}

