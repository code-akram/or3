// Temporal anti-aliasing for the character viewer (T16, bench/m1/v4/checkpoint-3.md §2.6):
//
//   HairTRAA  three r186's TRAANode (temporal reprojection AA: Halton(2,3) camera jitter, per-pixel
//             velocity, 3x3 variance clipping, luminance-weighted blend) driven by Output instead of a
//             RenderPipeline, with a HAIR-RESPONSIVE history: the hair / beard / brow cards are hashed
//             (materials/index.ts) and write 1 into the MRT 'hair' attachment; on (3x3-dilated) hair
//             pixels the disocclusion test is skipped (a hashed strand in front of the scalp is not a
//             disocclusion), the clip box is wider while the pixel is still (the hash noise is the
//             variance) and tightens with screen motion (where the ghosting would come from).
//             Stills accumulate progressively (current weight max(1/(n+1), floor)) after a history reset.
//             T18b SPECULAR-AWARE: the eye writes (0, 1) into the 'hair' attachment (hair: 1s); on those
//             (3x3-dilated) pixels the blend is linear (three's flickerReduction weights each sample by
//             1 / (1 + luma), so a 1-2 px catchlight that the jitter puts in a pixel some frames and not
//             others averages toward the dark frames: T18 lost 45 % of its peak and pulsed +-10 %), the
//             clip is wider while still (the jitter moving the highlight is its variance) and the weight
//             floor is higher (the history follows the surface, a reflection does not: shorter trails).
//   SizedTAAU three's TAAUNode (TAA upsampling: render at `scale` x the output and reconstruct) sized by
//             Output (the node otherwise sizes itself from the canvas, which the headless capture is not).
//
// Both run their resolve in updateBefore when a quad that samples them is drawn (Output.render). The
// nodes' own setViewOffset / clearViewOffset are not used: Output adds the jitter on top of the stage
// camera's lens-shift view offset (stage.ts applyCamera) and keeps the velocity node on the unjittered
// projection.
//
// Velocity for skinned AND morphed meshes: three's velocity takes the previous frame's skinning
// (Skinning.js keeps the previous bone matrices) but feeds it the UNMORPHED geometry position, so any
// active corrective shape key (deform.ts drives them) reads as motion. patchMorphVelocity() makes the
// previous position the morphed one (exact while the morph weights hold still, as in a turntable or a
// held pose; a changing weight then reads as zero velocity for the morph delta, a sub-pixel error).
import * as THREE from 'three/webgpu';
import * as TSL from 'three/tsl';
import TRAANode from 'three/addons/tsl/display/TRAANode.js';
import TAAUNode from 'three/addons/tsl/display/TAAUNode.js';
import { clipAABB, flickerReduction, sampleCurrentDepth, samplePreviousDepth, computeHaltonOffsets } from 'three/addons/tsl/utils/TAAUtils.js';
// TSL's TypeScript types are too narrow for shader-graph code; the graph is checked at build.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const T = TSL as any;
const { Fn, float, ivec2, max, mix, texture, uniform, uv, vec2, exp } = T;

/* eslint-disable @typescript-eslint/no-explicit-any */
type N = any;

export const HALTON = computeHaltonOffsets(32);

let patched = false;
/** Make positionPrevious the morphed position (see the header). Idempotent; call before any build. */
export function patchMorphVelocity(): void {
  if (patched) return;
  patched = true;
  const proto = THREE.NodeMaterial.prototype as any;
  proto.setupPosition = function (this: any, builder: any) {
    const { object, geometry } = builder;
    if (geometry.morphAttributes.position || geometry.morphAttributes.normal || geometry.morphAttributes.color) {
      T.morphReference(object);
      if (geometry.morphAttributes.position && builder.needsPreviousData()) T.positionPrevious.assign(T.positionLocal);
    }
    if (object.isSkinnedMesh === true) T.skinning(object);
    if (this.displacementMap) {
      const dm = T.materialReference('displacementMap', 'texture');
      const ds = T.materialReference('displacementScale', 'float');
      const db = T.materialReference('displacementBias', 'float');
      T.positionLocal.addAssign(T.normalLocal.normalize().mul(dm.x.mul(ds).add(db)));
    }
    if (object.isBatchedMesh) T.batch(object);
    if (object.isInstancedMesh && object.instanceMatrix && object.instanceMatrix.isInstancedBufferAttribute === true) T.instancedMesh(object);
    if (this.positionNode !== null) T.positionLocal.assign(T.subBuild(this.positionNode, 'POSITION', 'vec3'));
    return T.positionLocal;
  };
}

export interface TemporalParams {
  /** minimum current-frame weight (stock TRAA: 0.05) */
  minWeight: N;
  /** on hair pixels */
  hairMinWeight: N;
  /** variance-clip gamma on still hair pixels, and on moving ones (stock: 1 still, 0.5 moving) */
  hairGamma: N;
  hairGammaMoving: N;
  /** screen motion (px / frame) over which hair's gamma goes from still to moving (exp falloff) */
  hairMotionPx: N;
  /** T18b, specular pixels (the 'hair' attachment's green minus red: the eye writes (0, 1)): the weight
   * floor, the still clip gamma, and linear (1) vs flickerReduction (0) blending */
  specMinWeight: N;
  specGamma: N;
  specLinear: N;
  /** 0 = treat the flagged pixels as stock (the A/B of bench/m1/v4/t18b-eyes.md) */
  specAware: N;
}

const quad = new THREE.QuadMesh(null as unknown as THREE.NodeMaterial);

/** TRAANode with an Output-driven size, a reset, progressive still accumulation and the hair-aware
 * history (header). `frames` counts resolves since the last reset. */
export class HairTRAA extends (TRAANode as unknown as new (...a: any[]) => any) {
  size: [number, number] = [1, 1];
  readonly frames = uniform(0);
  private resetPending = true;
  private state: any = undefined;

  constructor(
    beauty: N,
    depth: N,
    velocity: N,
    private readonly hair: N,
    camera: THREE.Camera,
    private readonly p: TemporalParams,
  ) {
    super(beauty, depth, velocity, camera);
    this._velocityNode = T.velocity;
    // depth32float on both sides of the history copy (depth24plus cannot be copied in WebGPU)
    this._historyRenderTarget.depthTexture.type = THREE.FloatType;
  }

  /** The next resolve starts from the current frame (a new still, a cut). */
  reset(): void {
    this.resetPending = true;
  }

  updateBefore(frame: any): void {
    const r = frame.renderer as THREE.WebGPURenderer;
    this._previousCameraWorldMatrix.value.copy(this._cameraWorldMatrix.value);
    this._previousCameraProjectionMatrixInverse.value.copy(this._cameraProjectionMatrixInverse.value);
    this._cameraNearFar.value.set((this.camera as THREE.PerspectiveCamera).near, (this.camera as THREE.PerspectiveCamera).far);
    this._cameraWorldMatrix.value.copy(this.camera.matrixWorld);
    this._cameraWorldMatrixInverse.value.copy(this.camera.matrixWorldInverse);
    this._cameraProjectionMatrixInverse.value.copy(this.camera.projectionMatrixInverse);
    const [w, h] = this.size;
    this.state = THREE.RendererUtils.resetRendererState(r, this.state);
    const restart = this._historyRenderTarget.width !== w || this._historyRenderTarget.height !== h;
    this.setSize(w, h);
    if (restart) {
      r.initRenderTarget(this._historyRenderTarget);
      r.initRenderTarget(this._resolveRenderTarget);
    }
    const beautyTex = this.beautyNode.value as THREE.Texture;
    if (restart || this.resetPending) {
      r.copyTextureToTexture(beautyTex, this._historyRenderTarget.texture);
      this.frames.value = 0;
      this.resetPending = false;
    }
    r.setRenderTarget(this._resolveRenderTarget);
    quad.material = this._resolveMaterial;
    quad.name = 'TRAA (hair-aware)';
    quad.render(r);
    r.setRenderTarget(null);
    r.copyTextureToTexture(this._resolveRenderTarget.texture, this._historyRenderTarget.texture);
    r.copyTextureToTexture(this.depthNode.value, this._historyRenderTarget.depthTexture);
    this._previousDepthNode.value = this._historyRenderTarget.depthTexture;
    this.frames.value += 1;
    THREE.RendererUtils.restoreRendererState(r, this.state);
  }

  setup(builder: any): N {
    const p = this.p;
    const beauty = this.beautyNode;
    const varianceClip = Fn(([texel, cur, hist, gamma]: N[]) => {
      const m1 = cur.toVar();
      const m2 = cur.pow2().toVar();
      for (const [x, y] of [[-1, -1], [-1, 1], [1, -1], [1, 1], [1, 0], [0, -1], [0, 1], [-1, 0]] as const) {
        const nb = beauty.offset(ivec2(x, y)).load(texel).max(0);
        m1.addAssign(nb);
        m2.addAssign(nb.pow2());
      }
      const mean = m1.div(9);
      const sd = m2.div(9).sub(mean.pow2()).max(0).sqrt().mul(gamma);
      const lo = mean.sub(sd);
      const hi = mean.add(sd);
      return clipAABB(mean.clamp(lo, hi), hist, lo, hi);
    });
    const subpixel = Fn(([vUV, size]: N[]) => {
      const ph = vUV.mul(size).fract().abs();
      const wgt = max(ph, ph.oneMinus());
      return wgt.x.mul(wgt.y).oneMinus().div(0.75);
    });
    const historyNode = texture(this._historyRenderTarget.texture);
    const resolve = Fn(() => {
      const uvNode = uv();
      const size = beauty.size();
      const texel = uvNode.mul(size);
      const cd = sampleCurrentDepth(this.depthNode, texel, this._cameraNearFar);
      const closest = cd.get('closestDepth');
      const closestTexel = cd.get('closestPositionTexel');
      const farthest = cd.get('farthestDepth');
      const offUV = this.velocityNode.load(closestTexel).xy.mul(vec2(0.5, -0.5));
      const histUV = uvNode.sub(offUV);
      const prevDepth = samplePreviousDepth(this._previousDepthNode, histUV, this._previousCameraProjectionMatrixInverse, this._previousCameraWorldMatrix, this._cameraWorldMatrixInverse, this._cameraNearFar, this.camera);
      // hair coverage in the 3x3 (dilated, so the hashed silhouette counts)
      const h0 = this.hair.load(texel);
      let hairN: N = h0.r;
      let specN: N = h0.g.sub(h0.r);
      for (const [x, y] of [[-1, -1], [-1, 1], [1, -1], [1, 1], [1, 0], [0, -1], [0, 1], [-1, 0]] as const) {
        const hn = this.hair.offset(ivec2(x, y)).load(texel);
        hairN = max(hairN, hn.r);
        specN = max(specN, hn.g.sub(hn.r));
      }
      const isHair = hairN.greaterThan(0.5);
      const isSpec = specN.mul(p.specAware).greaterThan(0.5).and(isHair.not());
      const validUV = histUV.greaterThanEqual(0).all().and(histUV.lessThanEqual(1).all());
      const isEdge = farthest.sub(closest).greaterThan(this.edgeDepthDiff);
      const disocc = closest.sub(prevDepth).greaterThan(this.depthThreshold);
      const valid = validUV.and(isEdge.or(disocc.not()).or(isHair));
      const cur = beauty.sample(uvNode);
      const hist = historyNode.sample(histUV);
      const motionPx = uvNode.sub(histUV).mul(size).length();
      const motion = motionPx.div(this.maxVelocityLength).saturate();
      // progressive for stills: 1 / (n + 1) until the floor (an EMA from then on)
      const floorW = isSpec.select(p.specMinWeight, mix(p.minWeight, p.hairMinWeight, isHair));
      const w = max(float(1).div(this.frames.add(1)), floorW).toVar();
      w.addAssign(subpixel(offUV, size).mul(0.25));
      w.assign(valid.select(w.add(motion).saturate(), 1));
      const gStock = mix(0.5, 1, motion.oneMinus().pow2());
      const still = exp(motionPx.div(p.hairMotionPx).negate());
      const gHair = mix(p.hairGammaMoving, p.hairGamma, still);
      const gSpec = mix(gStock, p.specGamma, still);
      const clipped = varianceClip(texel, cur, hist, isSpec.select(gSpec, isHair.select(gHair, gStock)));
      const fr = flickerReduction(cur, clipped, w);
      return isSpec.select(mix(fr, mix(clipped, cur, w), p.specLinear), fr);
    });
    this._resolveMaterial.contextNode = T.context(builder.getSharedContext());
    this._resolveMaterial.colorNode = resolve();
    return this._textureNode;
  }
}

/** TAAUNode sized by Output (input = the scene target, output = `outSize`), jittered by Output. */
export class SizedTAAU extends (TAAUNode as unknown as new (...a: any[]) => any) {
  outSize: [number, number] = [1, 1];
  private resetPending = true;
  private state: any = undefined;

  constructor(beauty: N, depth: N, velocity: N, camera: THREE.Camera) {
    super(beauty, depth, velocity, camera);
    this._previousDepthRenderTarget.depthTexture.type = THREE.FloatType;
  }

  reset(): void {
    this.resetPending = true;
  }

  /** this frame's jitter in input pixels (Output applies the same offset to the camera) */
  setJitter(x: number, y: number): void {
    this._jitterOffset.value.set(x, y);
  }

  updateBefore(frame: any): void {
    const r = frame.renderer as THREE.WebGPURenderer;
    this._previousCameraWorldMatrix.value.copy(this._cameraWorldMatrix.value);
    this._previousCameraProjectionMatrixInverse.value.copy(this._cameraProjectionMatrixInverse.value);
    this._cameraNearFar.value.set((this.camera as THREE.PerspectiveCamera).near, (this.camera as THREE.PerspectiveCamera).far);
    this._cameraWorldMatrix.value.copy(this.camera.matrixWorld);
    this._cameraWorldMatrixInverse.value.copy(this.camera.matrixWorldInverse);
    this._cameraProjectionMatrixInverse.value.copy(this.camera.projectionMatrixInverse);
    const [ow, oh] = this.outSize;
    this.state = THREE.RendererUtils.resetRendererState(r, this.state);
    const restart = this._historyRenderTarget.width !== ow || this._historyRenderTarget.height !== oh;
    this.setSize(ow, oh);
    if (restart) {
      r.initRenderTarget(this._historyRenderTarget);
      r.initRenderTarget(this._resolveRenderTarget);
    }
    if (restart || this.resetPending) {
      r.setRenderTarget(this._historyRenderTarget);
      quad.material = this._seedMaterial;
      quad.name = 'TAAU.seed';
      quad.render(r);
      this.resetPending = false;
    }
    r.setRenderTarget(this._resolveRenderTarget);
    quad.material = this._resolveMaterial;
    quad.name = 'TAAU';
    quad.render(r);
    r.setRenderTarget(null);
    r.copyTextureToTexture(this._resolveRenderTarget.texture, this._historyRenderTarget.texture);
    const depth = this.depthNode.value as THREE.Texture;
    const img = depth.image as { width: number; height: number };
    if (this._previousDepthRenderTarget.width !== img.width || this._previousDepthRenderTarget.height !== img.height) {
      this._previousDepthRenderTarget.setSize(img.width, img.height);
      r.initRenderTarget(this._previousDepthRenderTarget);
    }
    r.copyTextureToTexture(depth, this._previousDepthRenderTarget.depthTexture);
    this._previousDepthNode.value = this._previousDepthRenderTarget.depthTexture;
    THREE.RendererUtils.restoreRendererState(r, this.state);
  }
}

/** The frame index of the temporal hash (materials' hashed hair alpha); Output.render advances it. */
export const temporalFrame = uniform(0);
