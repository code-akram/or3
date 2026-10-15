// Separable screen-space subsurface scattering (Jimenez et al. 2015, "Separable Subsurface Scattering"),
// T17 (bench/m1/v4/checkpoint-3.md §2.2). A 'scene' pass of the Output hook (output.ts header): it runs
// on the jittered scene-linear frame before the temporal resolve, so TRAA averages its sampling.
//
// The skin materials (materials/index.ts SkinMaterial, opts.ssss) write two MRT attachments:
//   skin        rgb = the specular total (three's LightsNode 'totalSpecular'), a = 1 (the stencil)
//   skinAlbedo  rgb = the diffuse albedo
// and shade their diffuse as Lambert; every other material writes 0 (no skin). Per skin pixel the
// pass takes the diffuse D = colour - specular, divides out the post-scatter share of the albedo
// (albedo^(1 - ssssAlbedoPre): 0.5 = the usual sqrt split, which keeps pore-scale colour that a full
// post-scatter blur would smear), blurs it along x and then y with the 1D marginal of the hero
// diffusion profile (sss.ts: per channel two Gaussians, sigma 0.5 r_c and 1.5 r_c, r_c = the Cycles
// radii 3.4 / 0.75 / 0.34 mm x skin.ssssWidth), multiplies the albedo share back and adds the
// specular. Kernel offsets are in mm on the surface: px per mm = the focal length in pixels over the
// view depth. A neighbour that is not skin, or that sits more than skin.ssssFalloffMm away in depth,
// contributes the centre value instead (Jimenez's "follow surface"). N_TAPS taps per direction, placed
// densest near the centre (offset ~ t^2), weights = the profile integrated over each tap's bin.
//
// The temporal AA modes only (the MRT needs the single-sample scene target); ?aa=msaa and ?ssss=0 keep
// the pre-integrated LUT (materials/sss.ts) as the low tier.
import * as THREE from 'three/webgpu';
import * as TSL from 'three/tsl';
import type { FrameContext, Output } from './output';
import type { ParamStore } from './materials/params';
import { HERO_RADII_MM } from './materials/sss';
// TSL's TypeScript types are too narrow for shader-graph code; the graph is checked at build.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const { Fn, If, abs, float, max, mix, perspectiveDepthToViewZ, pow, step, texture, uniform, uniformArray, uv, vec2, vec3, vec4 } = TSL as any;

/* eslint-disable @typescript-eslint/no-explicit-any */
type N = any;

export const N_TAPS = 13;

/** erf (Abramowitz and Stegun 7.1.26, |error| < 1.5e-7) */
function erf(x: number): number {
  const s = Math.sign(x);
  const a = Math.abs(x);
  const t = 1 / (1 + 0.3275911 * a);
  const y = 1 - ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-a * a);
  return s * y;
}

/** CDF of the 1D marginal of the profile (two Gaussians, equal weight) for radius r (mm). */
function cdf(x: number, r: number): number {
  const g = (sig: number) => 0.5 * (1 + erf(x / (sig * Math.SQRT2)));
  return 0.5 * g(0.5 * r) + 0.5 * g(1.5 * r);
}

/** Tap offsets (mm) and per-channel weights for the profile radii (mm). */
export function ssssKernel(radiiMm: number[], n = N_TAPS): { offsets: number[]; weights: number[][]; rangeMm: number } {
  const range = 3 * 1.5 * Math.max(...radiiMm);
  const h = (n - 1) / 2;
  const offsets = Array.from({ length: n }, (_, i) => {
    const t = (i - h) / h;
    return range * Math.sign(t) * t * t;
  });
  const edges = offsets.map((o, i) => (i === 0 ? -Infinity : 0.5 * (offsets[i - 1]! + o)));
  edges.push(Infinity);
  const weights = offsets.map((_, i) =>
    radiiMm.map((r) => {
      const hi = edges[i + 1]!;
      const lo = edges[i]!;
      return (hi === Infinity ? 1 : cdf(hi, r)) - (lo === -Infinity ? 0 : cdf(lo, r));
    }),
  );
  return { offsets, weights, rangeMm: range };
}

export interface SSSSHandle {
  info(): Record<string, unknown>;
}

/** Install the pass (and its MRT attachments) on a temporal Output; null in msaa mode. */
export function installSSSS(output: Output, P: ParamStore): SSSSHandle | null {
  if (output.aa === 'msaa') return null;
  output.addMRT('skin', vec4(0));
  output.addMRT('skinAlbedo', vec4(0));
  const placeholder = new THREE.DataTexture(new Uint8Array([0, 0, 0, 0]), 1, 1);
  placeholder.needsUpdate = true;
  const depthPlaceholder = new THREE.DepthTexture(1, 1);
  depthPlaceholder.type = THREE.FloatType;
  const colorH = texture(placeholder);
  const colorV = texture(placeholder);
  const skinT = texture(placeholder);
  const albT = texture(placeholder);
  const depthT = texture(depthPlaceholder);
  const near = uniform(0.05);
  const far = uniform(200);
  const focalPx = uniform(1000);
  const invSize = uniform(new THREE.Vector2(1, 1));
  let width = -1;
  let kern = ssssKernel(HERO_RADII_MM);
  const offsets = uniformArray(kern.offsets, 'float');
  const weights = uniformArray(kern.weights.map((w) => new THREE.Vector3(w[0], w[1], w[2])), 'vec3');
  const pre = P.u('skin.ssssAlbedoPre');
  const falloff = P.u('skin.ssssFalloffMm');
  const centre = (N_TAPS - 1) / 2;

  const zOf = (u: N) => perspectiveDepthToViewZ(depthT.sample(u).r, near, far).negate();
  const postOf = (alb: N) => pow(max(alb, vec3(0.02)), vec3(float(1).sub(pre)));
  const blur = (src: N, dir: [number, number]): THREE.NodeMaterial => {
    const m = new THREE.NodeMaterial();
    m.fragmentNode = Fn(() => {
      const u = uv();
      const c = src.sample(u);
      const sk = skinT.sample(u);
      const out = vec4(c.rgb, 1).toVar();
      If(sk.a.greaterThan(0.5), () => {
        const z = zOf(u);
        const pxPerMm = focalPx.div(z.mul(1000).max(1));
        const stepMm = vec2(dir[0], dir[1]).mul(invSize).mul(pxPerMm);
        const postC = postOf(albT.sample(u).rgb);
        const dc = max(c.rgb.sub(sk.rgb), vec3(0)).div(postC);
        const acc = dc.mul(weights.element(centre)).toVar();
        for (let i = 0; i < N_TAPS; i++) {
          if (i === centre) continue;
          const su = u.add(stepMm.mul(offsets.element(i)));
          const si = skinT.sample(su);
          const di = max(src.sample(su).rgb.sub(si.rgb), vec3(0)).div(postOf(albT.sample(su).rgb));
          const f = abs(zOf(su).sub(z)).mul(1000).div(falloff).clamp(0, 1);
          const valid = step(0.5, si.a).mul(float(1).sub(f));
          acc.addAssign(mix(dc, di, valid).mul(weights.element(i)));
        }
        out.assign(vec4(acc.mul(postC).add(sk.rgb), 1));
      });
      return out;
    })();
    return m;
  };
  const quadH = new THREE.QuadMesh(blur(colorH, [1, 0]));
  const quadV = new THREE.QuadMesh(blur(colorV, [0, 1]));
  let rtH: THREE.RenderTarget | null = null;
  let rtV: THREE.RenderTarget | null = null;
  let frames = 0;

  output.addPass({
    name: 'ssss',
    stage: 'scene',
    order: 10,
    render(ctx: FrameContext) {
      const skin = ctx.mrt.skin;
      const alb = ctx.mrt.skinAlbedo;
      if (!skin || !alb || !ctx.depth) return;
      const w = P.get('skin.ssssWidth') as number;
      if (w !== width) {
        width = w;
        kern = ssssKernel(HERO_RADII_MM.map((r) => r * w));
        kern.offsets.forEach((o, i) => (offsets.array[i] = o));
        kern.weights.forEach((v, i) => (weights.array[i] as THREE.Vector3).set(v[0]!, v[1]!, v[2]!));
      }
      if (!rtH || rtH.width !== ctx.width || rtH.height !== ctx.height) {
        rtH?.dispose();
        rtV?.dispose();
        const o = { type: THREE.HalfFloatType, depthBuffer: false };
        rtH = new THREE.RenderTarget(ctx.width, ctx.height, o);
        rtV = new THREE.RenderTarget(ctx.width, ctx.height, o);
      }
      const cam = ctx.camera;
      near.value = cam.near;
      far.value = cam.far;
      focalPx.value = (cam.projectionMatrix.elements[5]! * ctx.height) / 2;
      invSize.value.set(1 / ctx.width, 1 / ctx.height);
      skinT.value = skin;
      albT.value = alb;
      depthT.value = ctx.depth;
      colorH.value = ctx.color;
      ctx.renderer.setRenderTarget(rtH);
      quadH.render(ctx.renderer);
      colorV.value = rtH.texture;
      ctx.renderer.setRenderTarget(rtV);
      quadV.render(ctx.renderer);
      frames++;
      return rtV!.texture;
    },
    dispose() {
      rtH?.dispose();
      rtV?.dispose();
    },
  });
  return {
    info: () => ({
      taps: N_TAPS,
      passes: 2,
      width,
      range_mm: +kern.rangeMm.toFixed(2),
      offsets_mm: kern.offsets.map((o) => +o.toFixed(3)),
      centre_weight: kern.weights[centre]!.map((v) => +v.toFixed(3)),
      frames,
    }),
  };
}
