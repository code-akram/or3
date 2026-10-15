// Output: scene pass -> (temporal resolve) -> post -> grade -> display, for the canvas or a capture.
//
// Frame (Output.render), in order:
//   1. jitter     temporal modes only: this frame's Halton(2,3) sub-pixel offset is added to the
//                 camera's view offset (on top of the stage lens shift); the velocity node keeps the
//                 unjittered projection
//   2. 'pre'      passes before the scene pass, on the jittered camera (built in: GTAO, ao.ts)
//   3. scene      the scene, scene-linear half float. msaa: a 4x MSAA target, alpha-to-coverage cards.
//                 traa / taau: a single-sample MRT target {output, velocity, hair, ...addMRT()} with a
//                 float depth texture; hair cards are hashed and write 1 into 'hair' (temporal.ts)
//   4. 'scene'    passes on the jittered scene-linear frame at render resolution, before the temporal
//                 resolve (the place for screen-space SSS: TAA then cleans its noise)
//   5. resolve    traa: HairTRAA (temporal.ts); taau: SizedTAAU from `scale` x the output to the output
//   6. 'resolved' passes on the resolved scene-linear frame at output resolution (built in: thin-lens
//                 DoF, dof.ts, beauty only)
//   7. display    one full-screen pass: bloom + halation (grade.py's Glare/Bloom 1.0/0.35 and Fog Glow
//                 2.0/0.12 from a mipmapped half-res bright pass) -> the grade -> vignette -> 2 % grain ->
//                 exposure -> view transform -> sRGB. The grade + view are Blender's own, baked into 3D
//                 LUTs (grade.ts, grade_lut.json); without them (or ?lut=0) the analytic CDL grade and
//                 three's AgX. Order as Blender: compositor grade on the scene-linear render, then the
//                 view exposure, then AgX. Bloom, halation, grain and DoF are beauty only (setPost).
//
// PASS HOOK (T17 screen-space SSS, T19 contact shadows / PCSS and later tracks insert passes here
// without editing this file):
//
//   output.addPass({
//     name: 'ssss',                    // unique; addPass replaces a pass of the same name
//     stage: 'scene',                  // 'pre' | 'scene' | 'resolved' (above)
//     order: 10,                       // ascending within a stage (default 0; built-ins use 0)
//     enabled: true,                   // or flip later; disabled passes are skipped
//     setup(ctx) { ... },              // optional, once, before the first render (after the targets exist)
//     render(ctx) { ...; return tex }, // 'scene' / 'resolved': return a texture (same size and a
//                                      // half-float RGBA format) to replace ctx.color for the rest of
//                                      // the frame, or nothing to leave it; 'pre': return value ignored
//     dispose() { ... },               // optional
//   });
//   output.removePass('ssss');
//   output.addMRT('skin', float(0));   // a per-pixel attachment of the temporal scene target; every
//                                      // material writes the default, a material overrides it with
//                                      // `material.mrtNode = mrt({ skin: float(1) })` (three merges it);
//                                      // read it as ctx.mrt.skin in 'scene' passes. No-op in msaa mode.
//
//   ctx (FrameContext): renderer, scene, camera (jittered during 'pre' / 'scene'), width / height (the
//   render resolution), outWidth / outHeight, color (scene-linear THREE.Texture of this point of the
//   frame), depth (float DepthTexture at render resolution; null in msaa mode), velocity (NDC xy per
//   pixel; null in msaa), mrt (every attachment by name), jitter ([x, y] render px), frame (counter),
//   beauty (post on), aa ('msaa' | 'traa' | 'taau'), still (a still accumulation subframe > 0: shadows
//   and AO may be reused), lens (the DoF lens uniforms). A pass renders with ctx.renderer into its own
//   targets and must leave the render target / MRT as it found them (Output resets them between passes).
//
// The same pass draws to the canvas or into an RGBA8 target that is read back for headless screenshots
// (the WebGPU canvas does not reach headless screenshots). A later ink-line / paint pass slots in at
// 'resolved' (style.ts).
import * as THREE from 'three/webgpu';
import * as TSL from 'three/tsl';
import type { SceneAO } from './ao';
import { GradeLUT } from './grade';
import { HALTON, HairTRAA, SizedTAAU, patchMorphVelocity, temporalFrame, type TemporalParams } from './temporal';
import { ThinLensDoF, lensUniforms, type LensUniforms } from './dof';
import type { StageCamera } from './stage';
// TSL's TypeScript types are too narrow for shader-graph code; the graph is checked at build.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const T = TSL as any;
const { agxToneMapping, float, fract, max, mix, mrt, pow, sin, texture, uniform, uv, vec2, vec3, vec4 } = T;

/* eslint-disable @typescript-eslint/no-explicit-any */
type N = any;

export type AAMode = 'msaa' | 'traa' | 'taau';
export type PassStage = 'pre' | 'scene' | 'resolved';

export interface Grade {
  slope: number[];
  offset: number[];
  power: number[];
  saturation: number;
  vignette_ev: number;
  black_lift?: number;
  wb_rgb: number[];
}

export interface FrameContext {
  renderer: THREE.WebGPURenderer;
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  width: number;
  height: number;
  outWidth: number;
  outHeight: number;
  color: THREE.Texture;
  depth: THREE.DepthTexture | null;
  velocity: THREE.Texture | null;
  mrt: Record<string, THREE.Texture>;
  jitter: [number, number];
  frame: number;
  beauty: boolean;
  aa: AAMode;
  still: boolean;
  lens: LensUniforms;
}

export interface OutputPass {
  name: string;
  stage: PassStage;
  order?: number;
  enabled?: boolean;
  setup?(ctx: FrameContext): void;
  render(ctx: FrameContext): THREE.Texture | void;
  dispose?(): void;
}

export interface OutputOptions {
  aa?: AAMode;
  /** taau: render scale (0.5..1) */
  scale?: number;
  /** temporal history tuning (uniform nodes, e.g. ParamStore.u('aa.minWeight')) */
  temporal?: Partial<TemporalParams>;
  /** DoF tuning uniforms (maxPx, radiusScale, maxPassScale; e.g. ParamStore.u('dof.maxPx')) */
  lens?: Partial<LensUniforms>;
  /** DoF gathers at full resolution */
  dofFullRes?: boolean;
}

export interface RenderOptions {
  /** a subframe of a still accumulation: reuse the shadow maps and the AO of the first subframe */
  still?: boolean;
}

function srgbEncode(c: N): N {
  const lo = c.mul(12.92);
  const hi = pow(c, vec3(1 / 2.4)).mul(1.055).sub(0.055);
  return mix(lo, hi, c.greaterThan(vec3(0.0031308)));
}

export class Output {
  readonly samples: number;
  readonly aa: AAMode;
  /** taau render scale */
  scale: number;
  lastScene = { drawCalls: 0, triangles: 0 };
  frameCount = 0;
  private sceneRT: THREE.RenderTarget;
  private readonly quad: THREE.QuadMesh;
  private readonly mat: THREE.NodeMaterial;
  private readonly tex: N;
  readonly exposure = uniform(0);
  readonly gradeOn = uniform(0);
  readonly wb = uniform(new THREE.Vector3(1, 1, 1));
  readonly slope = uniform(new THREE.Vector3(1, 1, 1));
  readonly offset = uniform(new THREE.Vector3(0, 0, 0));
  readonly power = uniform(new THREE.Vector3(1, 1, 1));
  readonly saturation = uniform(1);
  readonly vignette = uniform(0);
  readonly blackLift = uniform(0);
  /** 1 = AgX view transform (the look-dev and hero frames); 0 = Standard (clamp + sRGB), the
   * shader-ball parity row, whose Cycles side renders with Blender's Standard view. */
  readonly viewAgX = uniform(1);
  readonly postOn = uniform(0);
  readonly bloomThreshold = uniform(1.0);
  readonly bloomStrength = uniform(0.35);
  readonly halationThreshold = uniform(2.0);
  readonly halationStrength = uniform(0.12);
  readonly halationTint = uniform(new THREE.Vector3(1.0, 0.32, 0.12));
  readonly grain = uniform(0.02);
  readonly res = uniform(new THREE.Vector2(1, 1));
  /** 1: write the scene-linear frame (after bloom when post is on), no grade / exposure / view (captureLinear) */
  readonly linearOut = uniform(0);
  /** Blender's grade as 3D LUTs (grade.ts); `lut.on` 0 = the analytic path */
  readonly lut = new GradeLUT();
  /** thin-lens DoF (beauty, temporal modes): on/off and the lens (setLens) */
  dofOn = false;
  readonly lens: LensUniforms;
  private readonly dofFullRes: boolean;
  private brightRT: THREE.RenderTarget;
  private readonly brightQuad: THREE.QuadMesh;
  /** T10: GTAO before the scene pass (null = off); runs as the first 'pre' pass */
  ao: SceneAO | null = null;
  private debugQuad: THREE.QuadMesh | null = null;
  private readonly passes: OutputPass[] = [];
  private readonly setupDone = new WeakSet<OutputPass>();
  // temporal
  private readonly mrtNodes: Record<string, N> = {};
  private mrtNode: N = null;
  private readonly unjittered = new THREE.Matrix4();
  private traa: HairTRAA | null = null;
  private taau: SizedTAAU | null = null;
  private resolveTrigger: THREE.QuadMesh | null = null;
  private readonly triggerRT = new THREE.RenderTarget(1, 1, { depthBuffer: false });
  private beautyNode: N = null;
  private depthNode: N = null;
  private velocityNode: N = null;
  private hairNode: N = null;
  private dof: ThinLensDoF | null = null;
  private dofColor: N = null;
  private dofTrigger: THREE.QuadMesh | null = null;
  private jitter: [number, number] = [0, 0];

  constructor(
    private readonly renderer: THREE.WebGPURenderer,
    samples: number,
    opts: OutputOptions = {},
  ) {
    this.aa = opts.aa ?? 'msaa';
    this.samples = this.aa === 'msaa' ? samples : 1;
    this.scale = Math.min(1, Math.max(0.5, opts.scale ?? 1));
    this.lens = { ...lensUniforms(), ...(opts.lens ?? {}) };
    this.dofFullRes = !!opts.dofFullRes;
    if (this.aa !== 'msaa') {
      patchMorphVelocity();
      // the velocity node is a singleton: point it at our unjittered projection for good (its uniform
      // is made from this matrix at build; we copy into it every frame)
      (T.velocity as { setProjectionMatrix(m: THREE.Matrix4 | null): void }).setProjectionMatrix(this.unjittered);
      this.mrtNodes.output = T.output;
      this.mrtNodes.velocity = T.velocity;
      this.mrtNodes.hair = float(0);
    }
    this.sceneRT = this.makeSceneRT(4, 4);
    this.tex = texture(this.sceneRT.texture);
    if (this.aa !== 'msaa') this.initTemporal(opts.temporal ?? {});
    this.mat = new THREE.NodeMaterial();
    // bright pass (half res, mipmapped): rgb above the bloom threshold, a = luminance above halation's
    this.brightRT = new THREE.RenderTarget(2, 2, { type: THREE.HalfFloatType, depthBuffer: false, generateMipmaps: true, minFilter: THREE.LinearMipmapLinearFilter });
    const bm = new THREE.NodeMaterial();
    const raw = this.tex.rgb;
    const lumW = vec3(0.2126, 0.7152, 0.0722);
    bm.fragmentNode = vec4(max(raw.sub(this.bloomThreshold), vec3(0)), max(raw.dot(lumW).sub(this.halationThreshold), float(0)));
    this.brightQuad = new THREE.QuadMesh(bm);
    const bt = texture(this.brightRT.texture);
    let glow: N = vec4(0);
    for (let k = 1; k <= 6; k++) glow = glow.add(bt.level(k));
    glow = glow.div(6);
    const c0: N = raw.add(glow.rgb.mul(this.bloomStrength).add(this.halationTint.mul(glow.a).mul(this.halationStrength)).mul(this.postOn));
    const d = uv().sub(0.5).mul(2);
    const vigAnalytic = pow(float(2), this.vignette.mul(d.dot(d).mul(0.5)));
    const px = uv().mul(this.res).floor();
    const noise = fract(sin(px.dot(vec2(12.9898, 78.233))).mul(43758.5453));
    const grainMul = mix(float(1), noise.mul(this.grain.mul(2)).add(float(1).sub(this.grain)), this.postOn);
    // analytic path (pre-T16): CDL grade (scene-linear, before exposure), vignette, grain, exposure, three's AgX
    let g: N = c0.div(this.wb);
    g = max(g.mul(this.slope).add(this.offset), vec3(0)).pow(this.power).add(this.blackLift);
    const lum = g.dot(vec3(0.2126, 0.7152, 0.0722));
    g = mix(vec3(lum), g, this.saturation);
    g = g.mul(vigAnalytic);
    let ca: N = mix(c0, g, this.gradeOn);
    ca = ca.mul(grainMul).mul(pow(float(2), this.exposure));
    const analytic = srgbEncode(mix(ca, agxToneMapping(ca, float(1)), this.viewAgX).clamp(0, 1));
    // LUT path (T16): Blender's grade and view transform by construction
    const gl: N = this.lut.grade(c0).mul(this.lut.vignette(uv(), vec3(vigAnalytic)));
    let cl: N = mix(c0, gl, this.gradeOn);
    cl = cl.mul(grainMul).mul(pow(float(2), this.exposure));
    const lutOut = mix(srgbEncode(cl.clamp(0, 1)), this.lut.view(cl).clamp(0, 1), this.viewAgX);
    const display = mix(analytic, lutOut, this.lut.on);
    this.mat.fragmentNode = mix(vec4(display, 1), vec4(c0, 1), this.linearOut);
    this.quad = new THREE.QuadMesh(this.mat);
  }

  // ------------------------------------------------------------------ targets

  private makeSceneRT(w: number, h: number): THREE.RenderTarget {
    if (this.aa === 'msaa') return new THREE.RenderTarget(w, h, { type: THREE.HalfFloatType, samples: this.samples, depthBuffer: true });
    const names = Object.keys(this.mrtNodes);
    const depth = new THREE.DepthTexture(w, h);
    depth.type = THREE.FloatType;
    const rt = new THREE.RenderTarget(w, h, { type: THREE.HalfFloatType, depthBuffer: true, depthTexture: depth, count: names.length });
    names.forEach((n, i) => (rt.textures[i]!.name = n));
    const m = mrt(this.mrtNodes);
    for (const n of names) if (n !== 'output') m.setClearColor(n, new THREE.Color(0, 0, 0), 0);
    this.mrtNode = m;
    return rt;
  }

  private initTemporal(tp: Partial<TemporalParams>): void {
    const rt = this.sceneRT;
    this.beautyNode = texture(rt.textures[0]);
    this.depthNode = texture(rt.depthTexture);
    this.velocityNode = texture(rt.textures[1]);
    this.hairNode = texture(rt.textures[2]);
    const p: TemporalParams = {
      minWeight: tp.minWeight ?? uniform(0.05),
      hairMinWeight: tp.hairMinWeight ?? uniform(0.05),
      hairGamma: tp.hairGamma ?? uniform(1.25),
      hairGammaMoving: tp.hairGammaMoving ?? uniform(0.75),
      hairMotionPx: tp.hairMotionPx ?? uniform(1),
    };
    let node: N;
    if (this.aa === 'traa') {
      this.traa = new HairTRAA(this.beautyNode, this.depthNode, this.velocityNode, this.hairNode, new THREE.PerspectiveCamera(), p);
      node = this.traa;
    } else {
      this.taau = new SizedTAAU(this.beautyNode, this.depthNode, this.velocityNode, new THREE.PerspectiveCamera());
      node = this.taau;
    }
    const m = new THREE.NodeMaterial();
    m.fragmentNode = vec4(node.getTextureNode().r, 0, 0, 1);
    this.resolveTrigger = new THREE.QuadMesh(m);
  }

  /** Extra per-pixel attachment of the temporal scene target (see the header). */
  addMRT(name: string, node: N): void {
    if (this.aa === 'msaa' || name in this.mrtNodes) return;
    this.mrtNodes[name] = node;
    const [w, h] = [this.sceneRT.width, this.sceneRT.height];
    const old = this.sceneRT;
    this.sceneRT = this.makeSceneRT(w, h);
    this.beautyNode.value = this.sceneRT.textures[0];
    this.depthNode.value = this.sceneRT.depthTexture;
    this.velocityNode.value = this.sceneRT.textures[1];
    this.hairNode.value = this.sceneRT.textures[2];
    old.dispose();
  }

  // ------------------------------------------------------------------ pass hook

  addPass(p: OutputPass): void {
    this.removePass(p.name);
    this.passes.push(p);
    this.passes.sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
  }

  removePass(name: string): void {
    const i = this.passes.findIndex((p) => p.name === name);
    if (i >= 0) {
      this.passes[i]!.dispose?.();
      this.passes.splice(i, 1);
    }
  }

  get passList(): readonly OutputPass[] {
    return this.passes;
  }

  private runPasses(stage: PassStage, ctx: FrameContext): void {
    for (const p of this.passes) {
      if (p.stage !== stage || p.enabled === false) continue;
      if (!this.setupDone.has(p)) {
        p.setup?.(ctx);
        this.setupDone.add(p);
      }
      const out = p.render(ctx);
      this.renderer.setRenderTarget(null);
      this.renderer.setMRT(null);
      if (out && stage !== 'pre') ctx.color = out;
    }
  }

  // ------------------------------------------------------------------ settings

  setGrade(on: boolean, exposureEV: number, g?: Grade): void {
    this.exposure.value = exposureEV;
    this.gradeOn.value = on ? 1 : 0;
    if (g) {
      const lum = 0.2126 * g.wb_rgb[0]! + 0.7152 * g.wb_rgb[1]! + 0.0722 * g.wb_rgb[2]!;
      this.wb.value.set(g.wb_rgb[0]! / lum, g.wb_rgb[1]! / lum, g.wb_rgb[2]! / lum);
      this.slope.value.fromArray(g.slope);
      this.offset.value.fromArray(g.offset);
      this.power.value.fromArray(g.power);
      this.saturation.value = g.saturation;
      this.vignette.value = g.vignette_ev;
      this.blackLift.value = g.black_lift ?? 0;
    }
  }

  /** The stage camera's lens for the DoF (lens_mm, sensor_mm of a VERTICAL fit, fstop, focus_m).
   * No f-stop (the look-dev views) = no DoF. */
  setLens(cam: StageCamera | null): void {
    const L = this.lens;
    if (!cam || !cam.fstop || !cam.focus_m) {
      this.lensValid = false;
      return;
    }
    this.lensValid = true;
    L.focus.value = cam.focus_m;
    L.fstop.value = cam.fstop;
    L.focal.value = cam.lens_mm / 1000;
    // a VERTICAL fit's sensor_mm is the height; otherwise (AUTO / HORIZONTAL) it spans the width
    L.sensorH.value = cam.sensor_mm / 1000;
    this.lensFit = cam.sensor_fit;
  }
  private lensValid = false;
  /** DoF even with the beauty post off (?dof=only: the bokeh fit against Cycles, no bloom or grain) */
  dofAlways = false;
  /** debug: show a DoF intermediate instead of the composite (?dofview=coc_near|coc_far|near|far|input) */
  dofDebug = '';
  private lensFit = 'VERTICAL';

  private ensure(w: number, h: number): [number, number] {
    const [iw, ih] = this.aa === 'taau' ? [Math.max(1, Math.round(w * this.scale)), Math.max(1, Math.round(h * this.scale))] : [w, h];
    if (this.sceneRT.width !== iw || this.sceneRT.height !== ih) {
      this.sceneRT.setSize(iw, ih);
      this.traa?.reset();
      this.taau?.reset();
    }
    const bw = Math.max(1, w >> 1);
    const bh = Math.max(1, h >> 1);
    if (this.brightRT.width !== bw || this.brightRT.height !== bh) this.brightRT.setSize(bw, bh);
    this.res.value.set(w, h);
    return [iw, ih];
  }

  /** ?aaview=raw|velocity|hair (temporal modes): draw the jittered scene frame (graded as the frame would
   * be: exposure + sRGB clamp), the velocity (|NDC| x 50, red / green) or the hair attachment. */
  setDebugTemporal(what: 'raw' | 'velocity' | 'hair' | null): void {
    if (!what || !this.temporal) return;
    const m = new THREE.NodeMaterial();
    const t = (i: number) => texture(this.sceneRT.textures[i]);
    if (what === 'raw') m.fragmentNode = vec4(srgbEncode(t(0).rgb.mul(pow(float(2), this.exposure)).clamp(0, 1)), 1);
    else if (what === 'velocity') m.fragmentNode = vec4(t(1).rg.abs().mul(50), t(1).r.notEqual(t(1).r).select(1, 0), 1);
    else m.fragmentNode = vec4(vec3(t(2).r), 1);
    this.debugQuad = new THREE.QuadMesh(m);
  }

  /** ?aoview=1: draw the AO texture (grey, sRGB-encoded) instead of the frame. */
  setDebugAO(tex: THREE.Texture | null, normals = false): void {
    if (!tex) {
      this.debugQuad = null;
      return;
    }
    const m = new THREE.NodeMaterial();
    m.fragmentNode = vec4(normals ? texture(tex).rgb.mul(0.5).add(0.5) : srgbEncode(vec3(texture(tex).r)), 1);
    this.debugQuad = new THREE.QuadMesh(m);
  }

  /** Beauty post (bloom, halation, grain, DoF) on or off; parity captures turn it off. */
  setPost(on: boolean): void {
    this.postOn.value = on ? 1 : 0;
  }

  /** Drop the temporal history: the next frame starts a new still / shot. */
  resetHistory(): void {
    this.traa?.reset();
    this.taau?.reset();
  }

  get temporal(): boolean {
    return this.aa !== 'msaa';
  }

  // ------------------------------------------------------------------ frame

  /** Render scene -> graded output into `target` (null = canvas). */
  render(scene: THREE.Scene, camera: THREE.Camera, w: number, h: number, target: THREE.RenderTarget | null = null, opts: RenderOptions = {}): void {
    const r = this.renderer;
    // the node frame drives once-per-frame work (shadow maps, GTAO, TRAA, velocity's previous
    // matrices); three only advances it from its own animation loop, which headless captures and
    // still accumulations do not wait for
    (r as unknown as { _nodes: { nodeFrame: { update(): void } } })._nodes.nodeFrame.update();
    this.frameCount++;
    temporalFrame.value = this.frameCount;
    const [iw, ih] = this.ensure(w, h);
    const cam = camera as THREE.PerspectiveCamera;
    const frozen: THREE.LightShadow[] = [];
    if (opts.still) {
      scene.traverse((o) => {
        const l = o as THREE.SpotLight;
        if (l.isLight && l.castShadow && l.shadow && l.shadow.autoUpdate) {
          l.shadow.autoUpdate = false;
          frozen.push(l.shadow);
        }
      });
    }
    const info = r.info.render;
    if (!this.temporal) {
      this.ao?.render(scene, camera, w, h);
      const ctx = this.context(scene, cam, w, h, w, h, this.sceneRT.texture, !!opts.still);
      this.runPasses('pre', ctx);
      r.setRenderTarget(this.sceneRT);
      const [d0, t0] = [info.drawCalls, info.triangles];
      r.render(scene, camera);
      this.lastScene = info.drawCalls >= d0 ? { drawCalls: info.drawCalls - d0, triangles: info.triangles - t0 } : { drawCalls: info.drawCalls, triangles: info.triangles };
      ctx.color = this.sceneRT.texture;
      this.runPasses('scene', ctx);
      this.runPasses('resolved', ctx);
      this.tex.value = ctx.color;
    } else {
      // 1. jitter (in render pixels) on top of the stage's view offset (lens shift)
      const view = cam.view && cam.view.enabled ? { ...cam.view } : null;
      cam.updateProjectionMatrix();
      this.unjittered.copy(cam.projectionMatrix);
      const j = HALTON[this.frameCount % HALTON.length]!;
      this.jitter = [j[0] - 0.5, j[1] - 0.5];
      const fw = view?.fullWidth ?? iw;
      const fh = view?.fullHeight ?? ih;
      // a render pixel is view.width / iw full-frame units (T18b: a cropped window, view.width < fullWidth)
      const vw = view?.width ?? fw;
      const vh = view?.height ?? fh;
      cam.setViewOffset(fw, fh, (view?.offsetX ?? 0) + (this.jitter[0] * vw) / iw, (view?.offsetY ?? 0) + (this.jitter[1] * vh) / ih, vw, vh);
      cam.updateProjectionMatrix();
      cam.updateMatrixWorld();
      if (this.traa) this.traa.camera = cam;
      if (this.taau) {
        this.taau.camera = cam;
        this.taau.setJitter(this.jitter[0], this.jitter[1]);
      }
      // 2. pre (GTAO once per still)
      if (!opts.still) this.ao?.render(scene, camera, iw, ih);
      const ctx = this.context(scene, cam, iw, ih, w, h, this.sceneRT.textures[0]!, !!opts.still);
      this.runPasses('pre', ctx);
      // 3. scene into the MRT target
      r.setMRT(this.mrtNode);
      r.setRenderTarget(this.sceneRT);
      const [d0, t0] = [info.drawCalls, info.triangles];
      r.render(scene, camera);
      this.lastScene = info.drawCalls >= d0 ? { drawCalls: info.drawCalls - d0, triangles: info.triangles - t0 } : { drawCalls: info.drawCalls, triangles: info.triangles };
      r.setMRT(null);
      // 4. scene passes, 5. resolve (camera still jittered: the resolve reprojects with it)
      this.runPasses('scene', ctx);
      this.beautyNode.value = ctx.color;
      if (this.traa) this.traa.size = [iw, ih];
      if (this.taau) this.taau.outSize = [w, h];
      r.setRenderTarget(this.triggerRT);
      this.resolveTrigger!.render(r);
      ctx.color = (this.traa ?? this.taau)!.getTextureNode().value as THREE.Texture;
      if (view) cam.setViewOffset(view.fullWidth, view.fullHeight, view.offsetX, view.offsetY, view.width, view.height);
      else cam.clearViewOffset();
      cam.updateProjectionMatrix();
      ctx.camera = cam;
      ctx.width = w;
      ctx.height = h;
      // 6. resolved: DoF (beauty) and the hook's passes
      if (this.dofOn && (this.postOn.value || this.dofAlways) && this.lensValid) ctx.color = this.renderDoF(ctx, cam, w, h);
      this.runPasses('resolved', ctx);
      this.tex.value = ctx.color;
    }
    for (const s of frozen) s.autoUpdate = true;
    if (this.postOn.value && !this.linearOut.value) {
      r.setRenderTarget(this.brightRT);
      this.brightQuad.render(r);
    }
    r.setRenderTarget(target);
    (this.debugQuad ?? this.quad).render(r);
    r.setRenderTarget(null);
  }

  private context(scene: THREE.Scene, cam: THREE.PerspectiveCamera, w: number, h: number, ow: number, oh: number, color: THREE.Texture, still: boolean): FrameContext {
    const rt = this.sceneRT;
    const mrtTex: Record<string, THREE.Texture> = {};
    for (const t of rt.textures) mrtTex[t.name || 'output'] = t;
    return {
      renderer: this.renderer,
      scene,
      camera: cam,
      width: w,
      height: h,
      outWidth: ow,
      outHeight: oh,
      color,
      depth: this.temporal ? rt.depthTexture : null,
      velocity: this.temporal ? rt.textures[1]! : null,
      mrt: mrtTex,
      jitter: this.jitter,
      frame: this.frameCount,
      beauty: !!this.postOn.value,
      aa: this.aa,
      still,
      lens: this.lens,
    };
  }

  private renderDoF(ctx: FrameContext, cam: THREE.PerspectiveCamera, w: number, h: number): THREE.Texture {
    const L = this.lens;
    L.near.value = cam.near;
    L.far.value = cam.far;
    // VERTICAL: the sensor height spans the frame height; AUTO / HORIZONTAL: it spans the larger side
    L.heightPx.value = this.lensFit === 'VERTICAL' ? h : Math.max(w, h);
    if (!this.dof) {
      this.dofColor = texture(ctx.color);
      this.dof = new ThinLensDoF(this.dofColor, texture(this.sceneRT.depthTexture), L);
      this.dof.fullRes = this.dofFullRes;
      const m = new THREE.NodeMaterial();
      // the DoF node itself in the graph (its getTextureNode() is a plain texture node, unlike TRAA's
      // pass texture, and does not pull the node's updateBefore)
      m.fragmentNode = T.nodeObject(this.dof);
      this.dofTrigger = new THREE.QuadMesh(m);
    }
    this.dofColor.value = ctx.color;
    this.renderer.setRenderTarget(this.triggerRT);
    this.dofTrigger!.render(this.renderer);
    this.renderer.setRenderTarget(null);
    const d = this.dof as unknown as Record<string, THREE.RenderTarget>;
    switch (this.dofDebug) {
      case 'coc_near': return d._CoCRT!.textures[0]!;
      case 'coc_far': return d._CoCRT!.textures[1]!;
      case 'near': return d._blur16NearRT!.texture;
      case 'far': return d._blur16FarRT!.texture;
      case 'input': return ctx.color;
    }
    return this.dof.getTextureNode().value as THREE.Texture;
  }

  /** Render a w x h frame and read it back as top-down RGBA8 rows. */
  async capture(scene: THREE.Scene, camera: THREE.Camera, w: number, h: number, frames = 1): Promise<Uint8Array> {
    const out = new THREE.RenderTarget(w, h, { type: THREE.UnsignedByteType, depthBuffer: false });
    for (let i = 0; i < frames; i++) this.render(scene, camera, w, h, out, { still: i > 0 });
    const px = new Uint8Array((await this.renderer.readRenderTargetPixelsAsync(out, 0, 0, w, h)) as Uint8Array);
    out.dispose();
    flipRows(this.renderer, px, w * 4, h);
    return px;
  }

  /** Scene-linear capture (no grade, exposure or view; bloom if post is on): RGBA float32, top-down. */
  async captureLinear(scene: THREE.Scene, camera: THREE.Camera, w: number, h: number, frames = 1): Promise<Float32Array> {
    const out = new THREE.RenderTarget(w, h, { type: THREE.HalfFloatType, depthBuffer: false });
    this.linearOut.value = 1;
    try {
      for (let i = 0; i < frames; i++) this.render(scene, camera, w, h, out, { still: i > 0 });
    } finally {
      this.linearOut.value = 0;
    }
    const raw = (await this.renderer.readRenderTargetPixelsAsync(out, 0, 0, w, h)) as Uint16Array;
    out.dispose();
    const f = new Float32Array(w * h * 4);
    for (let i = 0; i < f.length; i++) f[i] = THREE.DataUtils.fromHalfFloat(raw[i]!);
    flipRows(this.renderer, f, w * 4, h);
    return f;
  }
}

/** WebGL2 readPixels returns bottom-up rows; WebGPU's buffer copy is top-down. */
function flipRows(r: THREE.WebGPURenderer, px: Uint8Array | Float32Array, row: number, h: number): void {
  if ((r.backend as unknown as { isWebGPUBackend?: boolean }).isWebGPUBackend) return;
  const tmp = px.slice(0, row);
  for (let y = 0; y < h >> 1; y++) {
    const a = y * row;
    const b = (h - 1 - y) * row;
    tmp.set(px.subarray(a, a + row));
    px.copyWithin(a, b, b + row);
    px.set(tmp, b);
  }
}
