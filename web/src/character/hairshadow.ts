// Hair self-shadowing for the hair-only light twins (T10, bench/m1/v4/checkpoint-2.md §2 item 1).
//
// In Cycles ~80 % of the hero hair's luminance is the rim's TT through a self-shadowing mass: light
// that enters the hair is attenuated with the depth it travels through it, so the outer lengths glow
// and the crown under the mass stays dark. A binary shadow map cannot do that for cards: the outermost
// card layer is "the occluder" and is fully lit, every card under it is either fully lit (bias, PCF) or
// black, and the rim reached every top card unoccluded (t9b-hair.md "Value structure on the crown").
//
// The model here is a one-layer deep shadow (Beer-Lambert on the depth below the first occluder, as in
// the "deep opacity" / depth-difference hair shadows of realtime engines): the light's ordinary depth
// map (the cards cast with their alpha test, so it holds the outermost strands), and for a hair
// receiver at light-space depth z_r under a first occluder at z_o the transmittance
//
//     T = exp(-density * max(z_r - z_o - bias, 0))       (z in metres along the light's axis)
//
// averaged over a Vogel disk of taps (radius in shadow-map texels, IGN-rotated like three's PCF).
// Hair behind the head is under centimetres of "hair" and goes to 0, as with a binary map.
//
// It is a shadow filter (LightShadow.filterNode) on the hair twins only: Stage gives every shadowed
// light that reaches the hair a twin linked to the hair materials alone (the hero rig exports
// rim_hair / kicker_hair / fill_hair; key, wrap and the look-dev studio lights get theirs in the
// viewer), so skin and cloth keep the ordinary PCF shadow of the parent.
import type * as THREE from 'three/webgpu';
import * as TSL from 'three/tsl';
import type { ParamStore } from './materials/params';
import { depthLoad } from './lighting';
// TSL's TypeScript types are too narrow for shader-graph code; the graph is checked at build.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const { Fn, float, ivec2, exp, max, reference, renderGroup, perspectiveDepthToViewZ, interleavedGradientNoise, vogelDiskSample, screenCoordinate } = TSL as any;

/* eslint-disable @typescript-eslint/no-explicit-any */
type N = any;

const TAPS = 8;

/** The filter for one hair-twin light (three calls it with the light's shadow inputs at build). */
export function deepHairFilter(P: ParamStore): N {
  return Fn(({ depthTexture, shadowCoord, shadow }: { depthTexture: THREE.DepthTexture; shadowCoord: N; shadow: THREE.LightShadow }) => {
    const mapSize = reference('mapSize', 'vec2', shadow).setGroup(renderGroup);
    const near = reference('near', 'float', shadow.camera).setGroup(renderGroup);
    const far = reference('far', 'float', shadow.camera).setGroup(renderGroup);
    const density = P.u('hair.shadowDensity');
    const bias = P.u('hair.shadowBias');
    const radius = P.u('hair.shadowRadius');
    // receiver depth along the light axis (metres)
    const zr = perspectiveDepthToViewZ(shadowCoord.z, near, far).negate();
    const phi = interleavedGradientNoise(screenCoordinate.xy).mul(6.28318530718);
    const hi = ivec2(mapSize.sub(1));
    let acc: N = float(0);
    for (let i = 0; i < TAPS; i++) {
      const p = shadowCoord.xy.mul(mapSize).add(vogelDiskSample(i, TAPS, phi).mul(radius));
      const ip = ivec2(p.floor()).clamp(ivec2(0, 0), hi);
      // textureLoad: no sampler (the depth texture carries a comparison sampler for three's PCF)
      const d = depthLoad(depthTexture, ip).r;
      const zo = perspectiveDepthToViewZ(d, near, far).negate();
      acc = acc.add(exp(max(zr.sub(zo).sub(bias), float(0)).mul(density).negate()));
    }
    return acc.mul(1 / TAPS);
  });
}

/** The hair twin's shadow: no hardware bias (the filter's own depth bias), a tighter frustum
 * (shadow.focus) around the head so the texels are about a millimetre, its own map size. */
export function setupHairShadow(l: THREE.SpotLight, P: ParamStore, head: THREE.Vector3): void {
  const s = l.shadow;
  const size = P.get('hair.shadowMapSize') as number;
  s.mapSize.set(size, size);
  s.bias = 0;
  s.normalBias = 0;
  s.radius = 1;
  (s as unknown as { filterNode: N }).filterNode = deepHairFilter(P);
  const toHead = head.clone().sub(l.position);
  const axis = l.target.position.clone().sub(l.position).normalize();
  const dist = toHead.length();
  const off = axis.angleTo(toHead.clone().normalize());
  const half = off + Math.atan((P.get('hair.shadowExtent') as number) / dist);
  s.focus = Math.min(1, half / l.angle);
  s.camera.near = Math.max(0.05, dist - 0.6);
  s.camera.far = dist + 0.6;
}

