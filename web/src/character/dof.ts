// Thin-lens depth of field for the beauty views (T16, bench/m1/v4/checkpoint-3.md §2.6).
//
// three r186's DepthOfFieldNode keeps its pass structure here (full-res CoC -> near-field CoC blur ->
// 64-tap Vogel bokeh gather + 16-tap max at half res -> composite), with three changes:
//
// 1. The circle of confusion is the thin lens of the stage camera (engine_stage.json fstop, focus_m,
//    lens_mm, sensor_mm; Cycles' camera of blender/hero/rig.camera), not the node's smoothstep of a
//    distance in arbitrary units. For a point at depth z along the camera axis (metres):
//        r_px = radiusScale * 0.5 * (f^2 / N) * |z - S| / (z (S - f)) / sensor_h * H
//    (f focal length, N f-number, S focus distance, sensor_h the vertical sensor of a VERTICAL fit,
//    H the output height). The CoC texture stores r_px / maxPx per field (near: z < S, far: z > S).
// 2. The far field is a scatter-as-gather: a tap contributes only if its own CoC reaches the pixel
//    (r_tap >= distance), and the gather radius is the smallest far CoC in front of the pixel found by
//    a 16-tap probe, so a mid-ground edge (the ear, 3 px) spreads over the dark void behind it by its own
//    radius instead of by the void's (~60 px), and nothing in focus bleeds into the blur. Cost: a sharp
//    band of background, as wide as the mid-ground CoC, next to a blurred mid-ground edge (invisible on
//    the hero's black world; the set is a lighting term, not a background).
// 3. The composite fades from the sharp frame to the blurred fields between a CoC of 0.5 and 1.5 px.
//
// The near field (in front of the focus plane: the near shoulder) is the stock node's.
import * as THREE from 'three/webgpu';
import * as TSL from 'three/tsl';
import DepthOfFieldNode from 'three/addons/tsl/display/DepthOfFieldNode.js';
import { gaussianBlur } from 'three/addons/tsl/display/GaussianBlurNode.js';
// TSL's TypeScript types are too narrow for shader-graph code; the graph is checked at build.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const T = TSL as any;
const { Fn, Loop, float, max, mix, perspectiveDepthToViewZ, property, outputStruct, smoothstep, step, texture, uniform, uniformArray, uv, vec3, vec4 } = T;

/* eslint-disable @typescript-eslint/no-explicit-any */
type N = any;

export interface LensUniforms {
  /** focus distance S (m) */
  focus: N;
  /** f-number N */
  fstop: N;
  /** focal length f (m) */
  focal: N;
  /** vertical sensor height (m) */
  sensorH: N;
  /** output height (px) */
  heightPx: N;
  near: N;
  far: N;
  /** CoC radius (px) that maps to 1 in the CoC texture (the gather's largest radius) */
  maxPx: N;
  /** an empirical correction of the measured blur radius (1 = the formula) */
  radiusScale: N;
  /** 16-tap max pass radius as a fraction of the gather radius (stock 1; near field only) */
  maxPassScale: N;
}

const quad = new THREE.QuadMesh(null as unknown as THREE.NodeMaterial);

/** Thin-lens CoC radius in output pixels for a view-space distance z (> 0). */
export function cocPx(z: N, L: LensUniforms): N {
  const k = L.focal.mul(L.focal).div(L.fstop);
  return L.radiusScale.mul(0.5).mul(k).mul(z.sub(L.focus).abs()).div(z.mul(L.focus.sub(L.focal))).div(L.sensorH).mul(L.heightPx);
}

export class ThinLensDoF extends (DepthOfFieldNode as unknown as new (...a: any[]) => any) {
  /** run the gathers at full resolution instead of half */
  fullRes = false;
  private state: any = undefined;
  private readonly farMaterial = new THREE.NodeMaterial();

  constructor(
    color: N,
    private readonly depth: N,
    private readonly L: LensUniforms,
  ) {
    super(color, float(0), float(0), float(1), L.maxPx);
  }

  setSize(width: number, height: number): void {
    this._invSize.value.set(1 / width, 1 / height);
    this._CoCRT.setSize(width, height);
    this._compositeRT.setSize(width, height);
    const s = this.fullRes ? 1 : 2;
    const bw = Math.max(1, Math.round(width / s));
    const bh = Math.max(1, Math.round(height / s));
    this._CoCBlurredRT.setSize(bw, bh);
    this._blur64RT.setSize(bw, bh);
    this._blur16NearRT.setSize(bw, bh);
    this._blur16FarRT.setSize(bw, bh);
  }

  updateBefore(frame: any): void {
    const r = frame.renderer as THREE.WebGPURenderer;
    const map = this.textureNode.value as THREE.Texture;
    const img = map.image as { width: number; height: number };
    this.setSize(img.width, img.height);
    this.state = THREE.RendererUtils.resetRendererState(r, this.state);
    r.setClearColor(0x000000, 0);
    const pass = (m: THREE.NodeMaterial, rt: THREE.RenderTarget, name: string) => {
      quad.material = m;
      quad.name = name;
      r.setRenderTarget(rt);
      quad.render(r);
    };
    pass(this._CoCMaterial, this._CoCRT, 'DoF [CoC]');
    this._CoCTextureNode.value = this._CoCRT.textures[0];
    pass(this._CoCBlurredMaterial, this._CoCBlurredRT, 'DoF [near CoC blur]');
    this._CoCTextureNode.value = this._CoCBlurredRT.texture;
    pass(this._blur64Material, this._blur64RT, 'DoF [near 64]');
    pass(this._blur16Material, this._blur16NearRT, 'DoF [near 16]');
    pass(this.farMaterial, this._blur16FarRT, 'DoF [far gather]');
    pass(this._compositeMaterial, this._compositeRT, 'DoF [composite]');
    THREE.RendererUtils.restoreRendererState(r, this.state);
  }

  setup(builder: any): N {
    const L = this.L;
    const ctx = T.context(builder.getSharedContext());
    const kernels = this._generateKernels();
    const zOf = (u: N) => perspectiveDepthToViewZ(this.depth.sample(u).r, L.near, L.far).negate();

    // 1. CoC (normalised by maxPx) per field
    const nearF = property('float');
    const farF = property('float');
    this._CoCMaterial.contextNode = ctx;
    this._CoCMaterial.colorNode = Fn(() => {
      const z = zOf(uv());
      const c = cocPx(z, L).div(L.maxPx).min(1);
      nearF.assign(step(z, L.focus).mul(c));
      farF.assign(step(L.focus, z).mul(c));
      return float(0);
    })();
    this._CoCMaterial.outputNode = outputStruct(nearF, farF);
    this._CoCMaterial.needsUpdate = true;

    // 2. near field: the stock node's (gaussian-blurred CoC, 64-tap mean, 16-tap max)
    this._CoCBlurNode = gaussianBlur(this._CoCTextureNode, 1, 2);
    this._CoCBlurredMaterial.colorNode = this._CoCBlurNode;
    this._CoCBlurredMaterial.needsUpdate = true;
    const k64 = uniformArray(kernels.points64);
    const k16 = uniformArray(kernels.points16);
    this._blur64Material.contextNode = ctx;
    this._blur64Material.fragmentNode = Fn(() => {
      const acc = vec3(0).toVar();
      const u = uv();
      const c = this._CoCTextureNode.sample(u).r;
      const step_ = this._invSize.mul(L.maxPx).mul(c);
      Loop(64, ({ i }: N) => {
        acc.addAssign(this.textureNode.sample(u.add(step_.mul(k64.element(i)))).rgb);
      });
      return vec4(acc.div(64), c);
    })();
    this._blur64Material.needsUpdate = true;
    this._blur16Material.contextNode = ctx;
    this._blur16Material.fragmentNode = Fn(() => {
      const u = uv();
      const col = this._blur64TextureNode.sample(u).toVar();
      const mx = col.rgb.toVar();
      const step_ = this._invSize.mul(L.maxPx).mul(col.a).mul(L.maxPassScale);
      Loop(16, ({ i }: N) => {
        mx.assign(max(this._blur64TextureNode.sample(u.add(step_.mul(k16.element(i)))).rgb, mx));
      });
      return vec4(mx, col.a);
    })();
    this._blur16Material.needsUpdate = true;

    // 3. far field: scatter-as-gather with the probed radius (header, item 2)
    const farCoC = texture(this._CoCRT.textures[1]);
    this.farMaterial.contextNode = ctx;
    this.farMaterial.fragmentNode = Fn(() => {
      const u = uv();
      const c = farCoC.sample(u).r;
      // probe: the smallest far CoC in front of this pixel (0 < c_tap < c) within its own radius
      const probe = this._invSize.mul(L.maxPx).mul(c);
      const rmin = c.toVar();
      Loop(16, ({ i }: N) => {
        const ct = farCoC.sample(u.add(probe.mul(k16.element(i)))).r;
        rmin.assign(ct.greaterThan(0.0001).and(ct.lessThan(rmin)).select(ct, rmin));
      });
      const R = rmin.mul(L.maxPx); // px
      const stepUV = this._invSize.mul(R);
      const acc = vec3(0).toVar();
      const wsum = float(0).toVar();
      Loop(64, ({ i }: N) => {
        const k = k64.element(i);
        const su = u.add(stepUV.mul(k));
        const dist = k.length().mul(R);
        const w = farCoC.sample(su).r.mul(L.maxPx).sub(dist).add(0.5).saturate();
        acc.addAssign(this.textureNode.sample(su).rgb.mul(w));
        wsum.addAssign(w);
      });
      const centre = this.textureNode.sample(u).rgb;
      return vec4(mix(centre, acc.div(wsum.max(1e-4)), wsum.greaterThan(0.01)), c);
    })();
    this.farMaterial.needsUpdate = true;

    // 4. composite
    this._compositeMaterial.contextNode = ctx;
    this._compositeMaterial.fragmentNode = Fn(() => {
      const u = uv();
      const nearS = this._blur16NearTextureNode.sample(u);
      const farS = this._blur16FarTextureNode.sample(u);
      const beauty = this.textureNode.sample(u);
      const cFar = farCoC.sample(u).r.mul(L.maxPx);
      const bFar = smoothstep(0.5, 1.5, cFar);
      const bNear = smoothstep(0.5, 1.5, nearS.a.mul(L.maxPx));
      const out = mix(beauty.rgb, farS.rgb, bFar).toVar();
      out.assign(mix(out, nearS.rgb, bNear));
      return vec4(out, 1);
    })();
    this._compositeMaterial.needsUpdate = true;
    return this._textureNode;
  }
}

/** The lens uniforms for a stage camera (lens_mm, sensor_mm vertical, fstop, focus_m). */
export function lensUniforms(): LensUniforms {
  return {
    focus: uniform(1.5),
    fstop: uniform(2),
    focal: uniform(0.085),
    sensorH: uniform(0.024),
    heightPx: uniform(1080),
    near: uniform(0.05),
    far: uniform(200),
    maxPx: uniform(64),
    radiusScale: uniform(1),
    maxPassScale: uniform(1),
  };
}
