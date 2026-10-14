// Engine character viewer (m1 v4 step 2, track T5): the shipped GLB in three.js WebGPU with the TSL
// material set, the rig.json deformation runtime, the look-dev and hero stages, a turntable and a
// headless capture path (bench/m1/engine_shots.mjs).
//
// URL: character.html?asset=<dir under /asset/>&view=front|three_quarter|profile|closeup|portrait
//      &rig=neutral|hero&turntable=1&pose=rest|stand|arms_up|...&amount=0..1&gl=1&dpr=1&params=<json>
//      &area=none|rims|all&post=0&gaze=0&scene=balls&view_transform=standard
//      &hairshadow=0 (T9b binary shadow on the hair) &fillshadow=0 (unshadowed fill / wrap) &gtao=0 (the
//      baked direct-AO stand-in instead of GTAO) &aoview=1 (show the AO) &lights=key,rim (debug)
//      &aa=traa|taau|msaa (T16: temporal AA with hashed hair cards, default; TAAU at &scale=0.75; msaa = the
//      4x MSAA + alpha-to-coverage parity path) &dof=0 (no thin-lens DoF on the beauty; dof=only: DoF with the rest of the post off) &lut=0 (analytic
//      grade + three's AgX instead of Blender's baked LUTs) &bounce=0 (no set-bounce environment)
//      &scene=chart (T16 grey chart under the hero rig: chart.glb next to engine_stage.json)
//      &capture=1&upload=1[&views=...&size=1024&portrait=1920x1080&perf=120]: device capture (the Air):
//      the page renders every view itself and POSTs the frames + timings to the loopback server of
//      `engine_shots.mjs --serve` (bench/m1/v4/t6-engine-parity.md, "Air capture")
import * as THREE from 'three/webgpu';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { KTX2Loader } from 'three/addons/loaders/KTX2Loader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { DeformRuntime, type RigRules } from './deform';
import { Poser, PRESETS, applyPreset } from './poses';
import { ParamStore } from './materials/params';
import { addHairDepthPrepass, assignMaterials, type Sidecars, type WeaveSidecar } from './materials';
import { skinLUT } from './materials/sss';
import { Output, type AAMode } from './output';
import { bounceTexture, type BounceJson } from './bounce';
import type { GradeLutJson } from './grade';
import { SceneAO } from './ao';
import { Stage, VIEWS, applyCamera, fallbackStage, type EngineStage, type Gaze, type RigName, type ViewName } from './stage';
import { FrameStats, textureBytes } from './hud';

const q = new URLSearchParams(location.search);
const hud = document.getElementById('hud') as HTMLDivElement;
const panel = document.getElementById('panel') as HTMLDivElement;
const fatalBox = document.getElementById('fatal') as HTMLDivElement;
const canvas = document.getElementById('view') as HTMLCanvasElement;

interface ViewerState {
  phase: string;
  ready: boolean;
  backend?: string;
  error?: string;
  load?: Record<string, number>;
  stats?: Record<string, unknown>;
  verify?: Record<string, unknown>;
  hairMaps?: Record<string, string>;
  hairPrepass?: number;
  sssLutMs?: number;
  gaze?: unknown;
  warnings: string[];
}
const state: ViewerState = { phase: 'start', ready: false, warnings: [] };

function fatal(msg: string): never {
  state.phase = 'error';
  state.error = msg;
  fatalBox.style.display = 'block';
  fatalBox.textContent = msg;
  throw new Error(msg);
}

/** Asset dir under /asset/ (relative, no '..'). */
function assetBase(): string {
  const a = (q.get('asset') ?? 'lookdev/latest').replace(/^\/+|\/+$/g, '');
  if (a.split('/').some((s) => s === '..') || /[\\:]/.test(a)) fatal(`bad asset path: ${a}`);
  return `/asset/${a === '.' || a === '' ? '' : a + '/'}`;
}

async function fetchJson<T>(url: string): Promise<T | null> {
  const r = await fetch(url);
  if (!r.ok) return null;
  return (await r.json()) as T;
}

/** Curvature maps + the pre-integrated SSS LUT (built here, ~0.2 s; sss.ts). */
function skinSidecars(P: ParamStore, head: THREE.Texture | null, hands: THREE.Texture | null): Pick<Sidecars, 'curvature' | 'sssLUT'> {
  if (!head && !hands) return {};
  for (const t of [head, hands]) if (t) t.anisotropy = 4;
  const t0 = performance.now();
  const lut = skinLUT(undefined, P.get('skin.sssRadiusScale') as number);
  state.sssLutMs = Math.round(performance.now() - t0);
  return { curvature: { skin_head: head, skin_hands: hands }, sssLUT: lut };
}

/** suit_detail.json + its tile: the weave as a tiled, mipmapped detail normal (T6). */
async function loadWeave(base: string): Promise<WeaveSidecar | null> {
  const j = await fetchJson<{ materials: WeaveSidecar['materials'] }>(base + 'suit_detail.json');
  const first = j && Object.values(j.materials)[0];
  if (!j || !first) return null;
  const tile = await loadTexture(base + (first as unknown as { tile: string }).tile);
  if (!tile) return null;
  tile.wrapS = tile.wrapT = THREE.RepeatWrapping;
  tile.anisotropy = 8;
  tile.generateMipmaps = true;
  tile.minFilter = THREE.LinearMipmapLinearFilter;
  return { tile, materials: j.materials };
}

async function loadTexture(url: string): Promise<THREE.Texture | null> {
  try {
    const t = await new THREE.TextureLoader().loadAsync(url);
    t.flipY = false; // glTF UV convention
    t.colorSpace = THREE.NoColorSpace;
    t.needsUpdate = true;
    return t;
  } catch {
    return null;
  }
}

// LTC rect lights are opt-in: three's RectAreaLight casts no shadows, so a rim behind the head leaks
// onto the collar / under the jaw; the portrait A/B scored SSIM none 0.694 > rims 0.684 > all 0.670
// against the Cycles parity render (t6-engine-parity.md). Shadowed spots stay the default.
// The shader balls default to 'all': no occluders, so unshadowed LTC rects are the faithful model of the
// Blender area lights there (ball parity calibrates materials, not the light approximation).
function areaMode(fallback: 'none' | 'all' = 'none'): 'none' | 'rims' | 'all' {
  const a = q.get('area');
  return a === 'none' || a === 'rims' || a === 'all' ? a : fallback;
}

/** ?aa= (T16): temporal (TRAA, hashed cards) by default; msaa for the parity stills. */
function aaMode(): AAMode {
  const a = q.get('aa');
  return a === 'msaa' || a === 'taau' ? a : 'traa';
}

/** The temporal / DoF tuning uniforms from the params (live: __viewer.setParam('aa.hairGamma', 1.5)). */
function outputOptions(P: ParamStore, aa: AAMode) {
  return {
    aa,
    scale: Number(q.get('scale') ?? P.get('aa.scale')),
    temporal: {
      minWeight: P.u('aa.minWeight'),
      hairMinWeight: P.u('aa.hairMinWeight'),
      hairGamma: P.u('aa.hairGamma'),
      hairGammaMoving: P.u('aa.hairGammaMoving'),
      hairMotionPx: P.u('aa.hairMotionPx'),
    },
    lens: { maxPx: P.u('dof.maxPx'), radiusScale: P.u('dof.radiusScale'), maxPassScale: P.u('dof.maxPassScale') },
    dofFullRes: !!(P.get('dof.fullRes') as number),
  };
}

/** Which hair / facial-hair materials carry the GLB strand maps (export.pack_hair_maps, T9 builds). */
function hairMaps(mats: Map<string, THREE.Material>, roles: Map<string, string>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [name, role] of roles) {
    if (role !== 'hair' && role !== 'facial') continue;
    const m = mats.get(name) as (THREE.Material & { __maps?: boolean }) | undefined;
    out[name] = m?.__maps ? 'anisotropy+orm' : 'none (UV bitangent, hashed ID)';
  }
  return out;
}

/** The hero shot's eye turn (wet.gaze in Blender rotates the eyes' rest vertices about each eyeball
 * centre; the lids stay). Applied to the bind-pose geometry of every eye-role mesh; null restores. */
class EyeGaze {
  private readonly meshes: { mesh: THREE.Mesh; orig: Map<string, Float32Array> }[] = [];
  current: Gaze | null = null;

  constructor(model: THREE.Object3D, isEye: (m: THREE.Mesh) => boolean) {
    model.updateMatrixWorld(true);
    model.traverse((o) => {
      const m = o as THREE.Mesh;
      if (!m.isMesh || !isEye(m)) return;
      // packed xyz copies via getX/Y/Z: the attribute may be interleaved (gltf-transform's default layout,
      // e.g. the KTX2 copy), where .array is the whole vertex buffer
      const orig = new Map<string, Float32Array>();
      for (const k of ['position', 'normal', 'tangent']) {
        const a = m.geometry.getAttribute(k) as THREE.BufferAttribute | THREE.InterleavedBufferAttribute | undefined;
        if (!a) continue;
        const xyz = new Float32Array(a.count * 3);
        for (let i = 0; i < a.count; i++) xyz.set([a.getX(i), a.getY(i), a.getZ(i)], i * 3);
        orig.set(k, xyz);
      }
      this.meshes.push({ mesh: m, orig });
    });
  }

  get count(): number {
    return this.meshes.length;
  }

  apply(g: Gaze | null): void {
    if (g === this.current) return;
    this.current = g;
    const v = new THREE.Vector3();
    const w = new THREE.Vector3();
    for (const { mesh, orig } of this.meshes) {
      const M = mesh.matrixWorld.clone();
      const Mi = M.clone().invert();
      const T: Record<'l' | 'r', THREE.Matrix4> = { l: new THREE.Matrix4(), r: new THREE.Matrix4() };
      const Nm: Record<'l' | 'r', THREE.Matrix3> = { l: new THREE.Matrix3(), r: new THREE.Matrix3() };
      if (g) {
        for (const side of ['l', 'r'] as const) {
          const c = new THREE.Vector3().fromArray(g[side].centre);
          const q = new THREE.Quaternion().fromArray(g[side].quat);
          T[side] = Mi.clone()
            .multiply(new THREE.Matrix4().makeTranslation(c.x, c.y, c.z))
            .multiply(new THREE.Matrix4().makeRotationFromQuaternion(q))
            .multiply(new THREE.Matrix4().makeTranslation(-c.x, -c.y, -c.z))
            .multiply(M);
          Nm[side].getNormalMatrix(T[side]);
        }
      }
      const pos = orig.get('position')!;
      const sideOf = new Uint8Array(pos.length / 3);
      for (let i = 0; i < sideOf.length; i++) sideOf[i] = v.fromArray(pos, i * 3).applyMatrix4(M).x > 0 ? 0 : 1;
      for (const [k, src] of orig) {
        const attr = mesh.geometry.getAttribute(k) as THREE.BufferAttribute | THREE.InterleavedBufferAttribute;
        for (let i = 0; i < sideOf.length; i++) {
          w.fromArray(src, i * 3);
          if (g) {
            const side = sideOf[i] === 0 ? 'l' : 'r';
            if (k === 'position') w.applyMatrix4(T[side]);
            else w.applyMatrix3(Nm[side]).normalize();
          }
          attr.setXYZ(i, w.x, w.y, w.z); // tangent w (handedness) is left as loaded
        }
        if ('isInterleavedBufferAttribute' in attr && attr.isInterleavedBufferAttribute) attr.data.needsUpdate = true;
        else attr.needsUpdate = true;
      }
    }
  }
}

interface BallsJson {
  res: number[];
  exposure: number;
  view_transform: string;
  camera: import('./stage').StageCamera;
  balls: { material: string; circle_px?: number[] }[];
}

/** ?scene=balls: the shader-ball parity scene (blender/lookdev_render.py --shader-balls): the balls GLB
 * with the character's materials, the look-dev studio lights, the Blender camera, Standard view. */
/** Device capture (?capture=1&upload=1): the page drives the views itself on this device's GPU and
 * POSTs each frame (raw RGBA8 rows; the server writes the PNG) and a summary to /upload/ on the
 * serving origin (engine_shots.mjs --serve, which accepts only these names and writes only into its
 * one run dir). Then a timed loop of the portrait at the canvas size for frame / GPU times. */
async function deviceCapture(
  api: { capture: (v: ViewName, r: RigName, w: number, h: number, pose?: string, post?: boolean, angleDeg?: number) => Promise<{ b64: string; ms: number; draw_calls: number; triangles: number }>; stats: () => unknown; setView: (v: ViewName, r: RigName) => void },
  renderer: THREE.WebGPURenderer,
  drawCanvas: () => void,
): Promise<void> {
  // a view is `name` (its own rig) or `name:hero` (T10: closeup:hero, the hero rig around the head)
  const views = (q.get('views') ?? 'front,three_quarter,profile,closeup,portrait,closeup:hero').split(',').filter((v) => (VIEWS as readonly string[]).includes(v.split(':')[0]!));
  const size = Number(q.get('size') ?? 1024);
  const [pw, ph] = (q.get('portrait') ?? '1920x1080').split('x').map(Number) as [number, number];
  const post = async (name: string, body: BodyInit, headers: Record<string, string> = {}) => {
    const r = await fetch(`/upload/${name}`, { method: 'POST', body, headers });
    if (!r.ok) throw new Error(`upload ${name}: ${r.status}`);
  };
  const shots: unknown[] = [];
  state.phase = 'uploading';
  for (const spec of views) {
    const [v, rr] = spec.split(':') as [ViewName, string | undefined];
    const own: RigName = v === 'portrait' ? 'hero' : 'neutral';
    const rig: RigName = rr === 'hero' || rr === 'neutral' ? rr : own;
    for (const withPost of v === 'portrait' && rig === 'hero' ? [false, true] : [false]) {
      const [w, h] = v === 'portrait' ? [pw, ph] : [size, size];
      const t = performance.now();
      const r = await api.capture(v, rig, w, h, undefined, withPost);
      const bin = Uint8Array.from(atob(r.b64), (ch) => ch.charCodeAt(0));
      const name = `game_${v}${rig !== own ? `_${rig}` : ''}${withPost ? '_beauty' : ''}.png`;
      await post(name, bin, { 'x-width': String(w), 'x-height': String(h), 'content-type': 'application/octet-stream' });
      shots.push({ view: v, rig, post: withPost, file: name, res: [w, h], render_ms: r.ms, wall_ms: Math.round(performance.now() - t), draw_calls: r.draw_calls, triangles: r.triangles });
      hud.textContent = `uploaded ${name}`;
    }
  }
  // timed loop: the portrait at the canvas size, frame time (rAF to rAF) and GPU time (timestamp query)
  const nPerf = Number(q.get('perf') ?? 120);
  const frameMs: number[] = [];
  const gpuMs: number[] = [];
  api.setView('portrait', 'hero');
  let last = performance.now();
  for (let i = 0; i < nPerf; i++) {
    await new Promise((res) => requestAnimationFrame(res));
    drawCanvas();
    try {
      const g = await renderer.resolveTimestampsAsync('render');
      if (typeof g === 'number' && g > 0) gpuMs.push(g);
    } catch {
      /* no timestamp-query on this adapter */
    }
    const now = performance.now();
    if (i > 0) frameMs.push(now - last);
    last = now;
  }
  const pct = (a: number[], p: number) => (a.length ? +[...a].sort((x, y) => x - y)[Math.min(a.length - 1, Math.floor(p * a.length))]!.toFixed(2) : null);
  let adapter: unknown = null;
  try {
    const a = await (navigator as unknown as { gpu?: { requestAdapter: () => Promise<{ info: Record<string, string> } | null> } }).gpu?.requestAdapter();
    adapter = a ? { vendor: a.info.vendor, architecture: a.info.architecture, description: a.info.description } : null;
  } catch {
    adapter = null;
  }
  const summary = {
    ok: true,
    device_capture: true,
    when: new Date().toISOString(),
    user_agent: navigator.userAgent,
    backend: state.backend,
    adapter,
    dpr: devicePixelRatio,
    load: state.load,
    verify: state.verify,
    warnings: state.warnings,
    hair_maps: state.hairMaps,
    stats: api.stats(),
    shots,
    perf: { frames: frameMs.length, canvas: [canvas.width, canvas.height], frame_ms_p50: pct(frameMs, 0.5), frame_ms_p95: pct(frameMs, 0.95), gpu_ms_p50: pct(gpuMs, 0.5), gpu_ms_p95: pct(gpuMs, 0.95), gpu_samples: gpuMs.length },
  };
  await post('game_shots.json', JSON.stringify(summary, null, 1), { 'content-type': 'application/json' });
  state.phase = 'uploaded';
  hud.textContent = `done: ${shots.length} frames uploaded; frame p50 ${summary.perf.frame_ms_p50} ms, GPU p50 ${summary.perf.gpu_ms_p50} ms`;
}

async function mainBalls(): Promise<void> {
  const base = assetBase();
  const renderer = new THREE.WebGPURenderer({ canvas, antialias: true, forceWebGL: q.get('gl') === '1', powerPreference: 'high-performance' });
  await renderer.init();
  state.backend = (renderer.backend as unknown as { isWebGPUBackend?: boolean }).isWebGPUBackend ? 'webgpu' : 'webgl2';
  renderer.outputColorSpace = THREE.LinearSRGBColorSpace;
  renderer.toneMapping = THREE.NoToneMapping;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;
  renderer.setPixelRatio(1);
  const output = new Output(renderer, 4);
  state.phase = 'loading';
  const [gltf, balls, stageData, paramJson, weave, curvHead, curvHands] = await Promise.all([
    new GLTFLoader().loadAsync(base + 'shader_balls.glb'),
    fetchJson<BallsJson>(base + 'shader_balls.json'),
    fetchJson<EngineStage>(base + 'engine_stage.json'),
    fetchJson<unknown>(base + 'material_params.json'),
    loadWeave(base),
    loadTexture(base + 'skin_head_curvature.png'),
    loadTexture(base + 'skin_hands_curvature.png'),
  ]);
  if (!balls) fatal('no shader_balls.json (blender/lookdev_render.py --shader-balls)');
  if (!stageData) fatal('no engine_stage.json');
  let overrides: unknown = paramJson;
  if (q.get('params')) overrides = JSON.parse(q.get('params')!);
  const P = new ParamStore(overrides);
  const scene = new THREE.Scene();
  scene.add(gltf.scene);
  const mats = assignMaterials(gltf.scene, P, { weave, ...skinSidecars(P, curvHead, curvHands) }, true);
  const stage = new Stage(stageData!, scene, mats.byName);
  stage.areaMode = areaMode('all');
  stage.setup('front', 'neutral');
  output.setGrade(false, balls!.exposure);
  output.viewAgX.value = balls!.view_transform === 'AgX' ? 1 : 0;
  const camera = new THREE.PerspectiveCamera(30, 1, 0.05, 200);
  const api = {
    state,
    params: P,
    setParam: (path: string, v: number | number[]) => P.set(path, v),
    captureBalls: async (w: number, h: number) => {
      applyCamera(camera, balls!.camera, w, h);
      const t = performance.now();
      const px = await output.capture(scene, camera, w, h);
      let s = '';
      for (let i = 0; i < px.length; i += 0x8000) s += String.fromCharCode(...px.subarray(i, i + 0x8000));
      return { b64: btoa(s), ms: Math.round(performance.now() - t), draw_calls: output.lastScene.drawCalls };
    },
  };
  (window as unknown as { __viewer: typeof api }).__viewer = api;
  applyCamera(camera, balls!.camera, 64, 32);
  output.render(scene, camera, 64, 32, null);
  state.phase = 'running';
  state.ready = true;
  hud.textContent = 'shader balls';
  panel.style.display = 'none';
}

/** ?scene=chart (T16): the grey chart (18 / 50 / 90 % patches and an 18 % ball; blender/hero/refs.py
 * chart -> chart.glb + chart.json) under the hero portrait rig and camera, graded as the hero frame, so
 * the engine's grade + lighting can be checked against Cycles' (lookdev_report.py chart). */
async function mainChart(): Promise<void> {
  const base = assetBase();
  const aa = aaMode();
  const renderer = new THREE.WebGPURenderer({ canvas, antialias: true, forceWebGL: q.get('gl') === '1', powerPreference: 'high-performance' });
  await renderer.init();
  state.backend = (renderer.backend as unknown as { isWebGPUBackend?: boolean }).isWebGPUBackend ? 'webgpu' : 'webgl2';
  renderer.outputColorSpace = THREE.LinearSRGBColorSpace;
  renderer.toneMapping = THREE.NoToneMapping;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;
  renderer.setPixelRatio(1);
  state.phase = 'loading';
  const [gltf, stageData, paramJson, lutJson] = await Promise.all([
    new GLTFLoader().loadAsync(base + 'chart.glb'),
    fetchJson<EngineStage>(base + 'engine_stage.json'),
    fetchJson<unknown>(base + 'material_params.json'),
    q.get('lut') === '0' ? null : fetchJson<GradeLutJson>(base + 'grade_lut.json'),
  ]);
  if (!stageData) fatal('no engine_stage.json');
  const P = new ParamStore(q.get('params') ? JSON.parse(q.get('params')!) : paramJson);
  const output = new Output(renderer, aa === 'msaa' ? 4 : 1, outputOptions(P, aa));
  if (lutJson) output.lut.load(lutJson);
  else state.warnings.push('no grade_lut.json: analytic grade + three AgX');
  const scene = new THREE.Scene();
  scene.add(gltf.scene);
  const mats = assignMaterials(gltf.scene, P, {}, aa === 'msaa');
  const stage = new Stage(stageData!, scene, mats.byName, P);
  stage.areaMode = areaMode();
  const vs = stage.setup('portrait', 'hero');
  output.setGrade(true, vs.exposure, stageData!.hero.grade);
  output.viewAgX.value = q.get('view_transform') === 'standard' ? 0 : 1;
  output.setPost(false);
  const camera = new THREE.PerspectiveCamera(30, 1, 0.05, 200);
  const api = {
    state,
    params: P,
    setParam: (path: string, v: number | number[]) => P.set(path, v),
    lights: () => stage.describeLights(),
    stats: () => ({ scene: 'chart', backend: state.backend, aa: { mode: output.aa }, grade: output.lut.info ? { lut: output.lut.info } : 'analytic (CDL + three AgX)' }),
    /** the chart frame (RGBA8, or scene-linear float32 with linear) at w x h, base64, top row first */
    captureChart: async (w: number, h: number, linear = false, frames?: number) => {
      applyCamera(camera, vs.camera, w, h);
      output.resetHistory();
      const n = frames ?? (output.temporal ? (P.get('aa.stillFrames') as number) : 1);
      const t = performance.now();
      const px = linear ? await output.captureLinear(scene, camera, w, h, n) : await output.capture(scene, camera, w, h, n);
      const u8 = new Uint8Array(px.buffer, px.byteOffset, px.byteLength);
      let s = '';
      for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode(...u8.subarray(i, i + 0x8000));
      return { b64: s ? btoa(s) : '', ms: Math.round(performance.now() - t), frames: n, grade: output.lut.info ?? 'analytic', lights: stage.describeLights() };
    },
  };
  (window as unknown as { __viewer: typeof api }).__viewer = api;
  applyCamera(camera, vs.camera, 64, 36);
  output.render(scene, camera, 64, 36, null);
  state.phase = 'running';
  state.ready = true;
  hud.textContent = 'grey chart';
  panel.style.display = 'none';
}

async function main(): Promise<void> {
  if (q.get('scene') === 'balls') return mainBalls();
  if (q.get('scene') === 'chart') return mainChart();
  const t0 = performance.now();
  const base = assetBase();
  const forceWebGL = q.get('gl') === '1';
  const upload = q.get('capture') === '1' && q.get('upload') === '1';
  const renderer = new THREE.WebGPURenderer({ canvas, antialias: true, forceWebGL, powerPreference: 'high-performance', trackTimestamp: upload });
  await renderer.init();
  const isWebGPU = (renderer.backend as unknown as { isWebGPUBackend?: boolean }).isWebGPUBackend === true;
  state.backend = isWebGPU ? 'webgpu' : 'webgl2';
  renderer.outputColorSpace = THREE.LinearSRGBColorSpace; // Output encodes sRGB itself
  renderer.toneMapping = THREE.NoToneMapping;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap; // r186 WebGPU: PCF with per-light radius (PCFSoft is gone)
  const dpr = Number(q.get('dpr') ?? Math.min(devicePixelRatio, 2));
  renderer.setPixelRatio(dpr);
  const aa = aaMode();
  const samples = aa === 'msaa' ? 4 : 1;
  const tInit = performance.now();

  // ------------------------------------------------------------------ load
  state.phase = 'loading';
  const progress = { loaded: 0, total: 0 };
  hud.textContent = 'loading…';
  const loader = new GLTFLoader();
  // ?ktx2=1: the Basis Universal copy (web/tools/ktx2.mjs, build_character.py --ktx2); the transcoder is
  // served at /basis/ (engine_shots.mjs from three's examples/jsm/libs/basis)
  const useKTX2 = q.get('ktx2') === '1';
  if (useKTX2) loader.setKTX2Loader(new KTX2Loader().setTranscoderPath('/basis/').detectSupport(renderer));
  const glbP = loader.loadAsync(base + (useKTX2 ? 'character.ktx2.glb' : 'character.glb'), (e) => {
    progress.loaded = e.loaded;
    progress.total = e.total;
    hud.textContent = `loading character.glb ${(e.loaded / 1e6).toFixed(1)} / ${(e.total / 1e6).toFixed(1)} MB`;
  });
  const [gltf, rules, stageData, paramJson, weave, curvHead, curvHands, lutJson, bounceJson] = await Promise.all([
    glbP,
    fetchJson<RigRules>(base + 'character.rig.json'),
    fetchJson<EngineStage>(base + 'engine_stage.json'),
    fetchJson<unknown>(base + 'material_params.json'),
    loadWeave(base),
    loadTexture(base + 'skin_head_curvature.png'),
    loadTexture(base + 'skin_hands_curvature.png'),
    q.get('lut') === '0' ? null : fetchJson<GradeLutJson>(base + 'grade_lut.json'),
    q.get('bounce') === '0' ? null : fetchJson<BounceJson>(base + 'set_bounce.json'),
  ]);
  const tLoaded = performance.now();
  let overrides: unknown = paramJson;
  if (q.get('params')) {
    try {
      overrides = JSON.parse(q.get('params')!);
    } catch {
      state.warnings.push('params: bad JSON, ignored');
    }
  }
  const P = new ParamStore(overrides);
  const output = new Output(renderer, samples, outputOptions(P, aa));
  if (lutJson) output.lut.load(lutJson);
  else state.warnings.push('no grade_lut.json: analytic grade + three AgX (blender/hero/grade.py --lut)');
  output.dofOn = q.get('dof') !== '0' && !!(P.get('dof.on') as number);
  output.dofAlways = q.get('dof') === 'only';
  if (!rules) state.warnings.push('no character.rig.json: helpers and correctives stay at bind');
  if (!stageData) state.warnings.push('no engine_stage.json: approximate cameras and lights (run blender/hero/export_rig.py)');

  const scene = new THREE.Scene();
  const model = gltf.scene;
  scene.add(model);
  // T16 set bounce: the environment of the hero beauty frame (bounce.ts); off (intensity 0) elsewhere
  if (bounceJson) {
    scene.environment = bounceTexture(bounceJson);
    scene.environmentIntensity = 0;
  }

  // bind pose from the inverse bind matrices (the node rest transforms should agree)
  let skinned: THREE.SkinnedMesh | null = null;
  model.traverse((o) => {
    if ((o as THREE.SkinnedMesh).isSkinnedMesh && !skinned) skinned = o as THREE.SkinnedMesh;
  });
  if (skinned) (skinned as THREE.SkinnedMesh).skeleton.pose();
  model.updateMatrixWorld(true);

  const rt = new DeformRuntime(model, rules ?? { version: 1 });
  const poser = new Poser(rt);
  const camera = new THREE.PerspectiveCamera(30, 1, 0.05, 200);
  // T10: GTAO at half resolution (ao.ts) instead of the baked direct-AO stand-in; ?gtao=0 or ao.gtao 0 = off
  const sceneAO = q.get('gtao') !== '0' && (P.get('ao.gtao') as number) ? new SceneAO(renderer, camera, model, P) : null;
  output.ao = sceneAO;
  if (sceneAO && q.get('aoview') === '1') output.setDebugAO(sceneAO.texture);
  if (sceneAO && q.get('aoview') === 'normal') output.setDebugAO(sceneAO.normalTexture, true);
  const aaview = q.get('aaview');
  if (aaview === 'raw' || aaview === 'velocity' || aaview === 'hair') output.setDebugTemporal(aaview);
  const side: Sidecars = { weave, ...skinSidecars(P, curvHead, curvHands), screenAO: sceneAO?.texture ?? null };
  if (!curvHead) state.warnings.push('no skin_head_curvature.png: wrap-lit skin (pre-T6 build)');
  if (!weave) state.warnings.push('no suit_detail.json: procedural micro-twill (pre-T6 build: weave baked in the atlas)');
  const mats = assignMaterials(model, P, side, aa === 'msaa');
  state.hairMaps = hairMaps(mats.byName, mats.roles);
  state.hairPrepass = addHairDepthPrepass(model, P);
  const stage = new Stage(stageData ?? fallbackStage(model), scene, mats.byName, P);
  stage.areaMode = areaMode();
  // T10: hair self-shadowing (hairshadow.ts) and the shadowed fill; ?hairshadow=0 / ?fillshadow=0 = T9b
  stage.deepHair = q.get('hairshadow') !== '0' && !!(P.get('hair.deepShadow') as number);
  stage.shadowFill = q.get('fillshadow') !== '0';
  if (q.get('lights')) stage.only = q.get('lights')!.split(','); // debug: per-light parity (hair_test --parity-lights)
  const gaze = new EyeGaze(model, (m) => {
    const mm = Array.isArray(m.material) ? m.material[0] : m.material;
    return mats.roles.get(mm?.name ?? '') === 'eye';
  });
  const tSetup = performance.now();

  // ------------------------------------------------------------------ view / pose state
  let viewName = (VIEWS as readonly string[]).includes(q.get('view') ?? '') ? (q.get('view') as ViewName) : 'front';
  let rigName: RigName = q.get('rig') === 'hero' ? 'hero' : q.get('rig') === 'neutral' ? 'neutral' : viewName === 'portrait' ? 'hero' : 'neutral';
  let poseName = q.get('pose') ?? (viewName === 'portrait' ? 'stand' : 'rest');
  let amount = Number(q.get('amount') ?? 1);
  let turntable = q.get('turntable') === '1';
  let spin = 0;

  const controls = new OrbitControls(camera, canvas);
  controls.enableDamping = false;
  let userOrbit = false;
  controls.addEventListener('start', () => (userOrbit = true));

  const applyPose = (): Record<string, number> => {
    if (poseName === 'stand' && stage.hasShot('portrait')) {
      poser.applyDeform(stage.data.hero.shots.portrait!.bones, amount);
    } else {
      applyPreset(poser, rt, PRESETS[poseName] ? poseName : 'rest', amount);
    }
    return rt.apply(q.get("correctives") !== "0"); // ?correctives=0: helpers only (A/B)
  };

  /** The beauty frame (T16): post + DoF + the set-bounce environment of the alley; the parity frames are
   * on the void set, so no bounce and the world hemisphere as Cycles' --parity world. */
  const hemi = (stage as unknown as { hemi: THREE.HemisphereLight }).hemi;
  let hemiBase = hemi.intensity;
  const setBeauty = (on: boolean): void => {
    output.setPost(on);
    const bounce = on && rigName === 'hero' && !!scene.environment;
    scene.environmentIntensity = bounce ? (P.get('bounce.gain') as number) : 0;
    // the cube already holds the world where the set does not cover it
    hemi.intensity = bounce ? 0 : hemiBase;
  };

  const setView = (v: ViewName, r: RigName): void => {
    viewName = v;
    rigName = r;
    const vs = stage.setup(v, r);
    hemiBase = hemi.intensity;
    // the hero shot turns the eyes to the camera (wet.gaze); the look-dev views keep the rest gaze
    const g = vs.shot ? (stage.data.hero.shots[vs.shot]?.gaze ?? null) : null;
    if (q.get('gaze') !== '0') gaze.apply(g);
    state.gaze = g ? { deg: g.deg, meshes: gaze.count } : null;
    output.setGrade(r === 'hero', vs.exposure, stage.data.hero.grade);
    // ?view_transform=standard: clamp + sRGB instead of AgX, so a capture decodes back to scene-linear
    // (hair / beard tone parity against Cycles EXRs, bench/m1/hair_parity.py)
    output.viewAgX.value = q.get('view_transform') === 'standard' ? 0 : 1;
    // beauty post (bloom, halation, grain, DoF, set bounce) on the interactive hero frames; ?post=0 for parity
    output.setLens(vs.camera);
    setBeauty(r === 'hero' && q.get('post') !== '0');
    output.resetHistory();
    userOrbit = false;
    controls.target.fromArray(vs.camera.target);
    resize();
  };

  const size = () => [Math.max(1, Math.floor(canvas.clientWidth * dpr)), Math.max(1, Math.floor(canvas.clientHeight * dpr))] as const;
  function resize(): void {
    const [w, h] = size();
    renderer.setSize(canvas.clientWidth, canvas.clientHeight, false);
    if (!userOrbit && stage.view) applyCamera(camera, stage.view.camera, w, h);
    else {
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    }
  }
  addEventListener('resize', resize);

  setView(viewName, rigName);
  applyPose();

  // ------------------------------------------------------------------ verification against Blender
  const verify = (): Record<string, unknown> => {
    const shot = stage.data.hero.shots.portrait;
    if (!shot) return { skipped: 'no hero portrait in engine_stage.json' };
    const keepPose = poseName;
    const keepAmt = amount;
    poser.applyDeform(shot.bones, 1);
    const w = rt.apply();
    let maxW = 0;
    let worst = '';
    for (const [k, ref] of Object.entries(shot.corrective_weights)) {
      const d = Math.abs((w[k] ?? 0) - ref);
      if (d > maxW) [maxW, worst] = [d, k];
    }
    let maxQ = 0;
    for (const [bone, ref] of Object.entries(shot.helper_world_quats ?? {})) {
      const qq = rt.R(bone);
      const r = new THREE.Quaternion(ref[0], ref[1], ref[2], ref[3]);
      maxQ = Math.max(maxQ, (2 * Math.acos(Math.min(1, Math.abs(qq.dot(r)))) * 180) / Math.PI);
    }
    poseName = keepPose;
    amount = keepAmt;
    applyPose();
    return {
      corrective_max_abs_diff: +maxW.toFixed(5),
      corrective_worst: worst,
      helper_max_angle_deg: +maxQ.toFixed(4),
      weights_ts: Object.fromEntries(Object.entries(w).filter(([, v]) => v > 0.005).map(([k, v]) => [k, +v.toFixed(4)])),
    };
  };
  state.verify = verify();
  if (rt.missing.length) state.warnings.push(`rules name missing bones: ${[...new Set(rt.missing)].join(', ')}`);

  // ------------------------------------------------------------------ panel
  const sel = (label: string, opts: readonly string[], val: string, on: (v: string) => void) => {
    const l = document.createElement('label');
    l.textContent = label;
    const s = document.createElement('select');
    for (const o of opts) s.add(new Option(o, o, o === val, o === val));
    s.onchange = () => on(s.value);
    l.append(s);
    panel.append(l);
    return s;
  };
  sel('view', VIEWS, viewName, (v) => setView(v as ViewName, rigName));
  sel('rig', ['neutral', 'hero'], rigName, (v) => setView(viewName, v as RigName));
  sel('pose', ['stand', ...Object.keys(PRESETS)], poseName, (v) => {
    poseName = v;
    applyPose();
  });
  {
    const l = document.createElement('label');
    l.textContent = 'amount';
    const r = document.createElement('input');
    r.type = 'range';
    r.min = '0';
    r.max = '1';
    r.step = '0.01';
    r.value = String(amount);
    r.oninput = () => {
      amount = Number(r.value);
      applyPose();
    };
    l.append(r);
    panel.append(l);
  }
  {
    const l = document.createElement('label');
    l.textContent = 'turntable';
    const c = document.createElement('input');
    c.type = 'checkbox';
    c.checked = turntable;
    c.onchange = () => (turntable = c.checked);
    l.append(c);
    panel.append(l);
  }
  {
    const b = document.createElement('button');
    b.textContent = 'reset camera';
    b.onclick = () => setView(viewName, rigName);
    panel.append(b);
  }
  if (q.get('ui') === '0') panel.style.display = 'none';

  // ------------------------------------------------------------------ stats / capture API
  const tex = textureBytes(model);
  let tris = 0;
  model.traverse((o) => {
    const g = (o as THREE.Mesh).geometry;
    if ((o as THREE.Mesh).isMesh && g && !o.userData.hairPrepass) tris += (g.index ? g.index.count : g.attributes.position!.count) / 3;
  });
  state.load = {
    init_ms: Math.round(tInit - t0),
    load_ms: Math.round(tLoaded - tInit),
    setup_ms: Math.round(tSetup - tLoaded),
    glb_mb: +(progress.total / 1e6).toFixed(1),
  };
  const fs = new FrameStats();
  let firstFrameMs = 0;

  const statsNow = () => ({
    backend: state.backend,
    tris_model: tris,
    draw_calls: output.lastScene.drawCalls,
    triangles_rendered: output.lastScene.triangles,
    textures: tex.count,
    texture_mb_est: +(tex.bytes / 1e6).toFixed(1),
    lights: stage.lightCount(),
    shadow_maps: stage.shadowMapCount(),
    gtao: sceneAO ? { half_res: true, last_ms: Math.round(sceneAO.lastMs) } : null,
    hair_shadow: stage.deepHair ? 'deep (hair twins)' : 'binary',
    aa: output.aa === 'msaa' ? { mode: 'msaa', samples: output.samples, hair: 'alpha to coverage' } : { mode: output.aa, scale: output.aa === 'taau' ? output.scale : 1, hair: `hashed (coverage ${P.get('aa.hairCoverage')})`, still_frames: P.get('aa.stillFrames') },
    dof: output.dofOn ? { thin_lens: true, full_res: !!(P.get('dof.fullRes') as number), radius_scale: P.get('dof.radiusScale') } : null,
    grade: output.lut.info ? { lut: output.lut.info } : 'analytic (CDL + three AgX)',
    bounce: scene.environment ? { gain: P.get('bounce.gain'), irradiance: bounceJson?.irradiance ?? null } : null,
    passes: output.passList.map((p) => `${p.stage}:${p.name}`),
    fill_shadow: stage.shadowFill,
    frame: fs.summary(),
    first_frame_ms: Math.round(firstFrameMs),
  });

  let advanceRT: THREE.RenderTarget | null = null;
  const api = {
    state,
    params: P,
    setView: (v: ViewName, r: RigName) => setView(v, r),
    setPose: (p: string, a = 1) => {
      poseName = p;
      amount = a;
      return applyPose();
    },
    setParam: (path: string, v: number | number[]) => P.set(path, v),
    setTurntable: (on: boolean, angleDeg?: number) => {
      turntable = on;
      if (angleDeg !== undefined) spin = (angleDeg * Math.PI) / 180;
    },
    weights: () => rt.lastWeights,
    lights: () => stage.describeLights(),
    stats: statsNow,
    /** Render view (stage camera, rig) at w x h; returns base64 RGBA8 rows, top row first.
     * Temporal AA: a still accumulates `frames` jittered frames (default aa.stillFrames) from a fresh
     * history; keep = true continues the current history instead (same view / pose / size, the model
     * turned to angleDeg; frames default 1): the turntable (engine_shots --turntable). linear = true
     * returns scene-linear float32 RGBA (no grade / exposure / view) as base64 instead. */
    capture: async (view: ViewName, rig: RigName, w: number, h: number, pose?: string, post = false, angleDeg = 0, opts: { frames?: number; keep?: boolean; linear?: boolean } = {}) => {
      if (!opts.keep) {
        setView(view, rig);
        poseName = pose ?? (view === 'portrait' ? 'stand' : 'rest');
        amount = 1;
        applyPose();
      }
      setBeauty(post);
      // turntable frames (engine_shots --turntable): the model turns in the fixed rig, as the viewer's turntable
      model.rotation.y = (angleDeg * Math.PI) / 180;
      model.updateMatrixWorld(true);
      applyCamera(camera, stage.view!.camera, w, h);
      const frames = opts.frames ?? (output.temporal && !opts.keep ? (P.get('aa.stillFrames') as number) : 1);
      const t = performance.now();
      const px = opts.linear ? await output.captureLinear(scene, camera, w, h, frames) : await output.capture(scene, camera, w, h, frames);
      const ms = performance.now() - t;
      const st = statsNow();
      if (!opts.keep) resize();
      const u8 = new Uint8Array(px.buffer, px.byteOffset, px.byteLength);
      let s = '';
      for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode(...u8.subarray(i, i + 0x8000));
      return { b64: btoa(s), ms: Math.round(ms), frames, draw_calls: st.draw_calls, triangles: st.triangles_rendered, lights: stage.describeLights(), weights: rt.lastWeights };
    },
    /** One more frame of the current view into the temporal history (no readback): the in-between
     * frames of a turntable at the display rate (engine_shots --tt-hz). */
    advance: (angleDeg: number, w: number, h: number) => {
      model.rotation.y = (angleDeg * Math.PI) / 180;
      model.updateMatrixWorld(true);
      applyCamera(camera, stage.view!.camera, w, h);
      if (!advanceRT || advanceRT.width !== w || advanceRT.height !== h) {
        advanceRT?.dispose();
        advanceRT = new THREE.RenderTarget(w, h, { type: THREE.UnsignedByteType, depthBuffer: false });
      }
      output.render(scene, camera, w, h, advanceRT);
      return true;
    },
  };
  (window as unknown as { __viewer: typeof api }).__viewer = api;

  // ------------------------------------------------------------------ loop
  state.phase = 'running';
  let last = performance.now();
  const frame = (now: number) => {
    const dt = Math.min(0.1, (now - last) / 1000);
    last = now;
    fs.tick(now);
    if (turntable) spin += dt * ((20 * Math.PI) / 180);
    model.rotation.y = spin;
    if (userOrbit) controls.update();
    const [w, h] = size();
    const t = performance.now();
    output.render(scene, camera, w, h, null);
    if (!firstFrameMs) {
      firstFrameMs = performance.now() - t;
      state.ready = true;
    }
    if (Math.floor(now / 250) !== Math.floor((now - dt * 1000) / 250)) {
      const st = statsNow();
      const wts = Object.entries(rt.lastWeights)
        .filter(([, v]) => v > 0.005)
        .map(([k, v]) => `${k} ${v.toFixed(2)}`)
        .join('  ');
      hud.textContent = [
        `${state.backend}  ${w}x${h}  dpr ${dpr}  ${output.aa === 'msaa' ? `MSAA ${samples}x` : output.aa === 'taau' ? `TAAU x${output.scale}` : 'TRAA'}${output.dofOn ? '  DoF' : ''}${output.lut.info ? '  LUT grade' : ''}`,
        `frame p50 ${st.frame.p50.toFixed(1)} ms  p95 ${st.frame.p95.toFixed(1)} ms  (${st.frame.fps.toFixed(0)} fps)`,
        `draws ${st.draw_calls}  tris ${(st.triangles_rendered / 1000).toFixed(1)}k (model ${(tris / 1000).toFixed(1)}k)  lights ${st.lights}`,
        `textures ${tex.count}  ~${st.texture_mb_est} MB uncompressed RGBA8+mips`,
        `load ${state.load!.load_ms} ms (${state.load!.glb_mb} MB GLB)  setup ${state.load!.setup_ms} ms  first frame ${st.first_frame_ms} ms`,
        `view ${viewName}  rig ${rigName}  pose ${poseName} ${amount.toFixed(2)}`,
        `correctives ${wts || 'none'}`,
        ...state.warnings.map((w) => `! ${w}`),
      ].join('\n');
    }
  };
  if (q.get('capture') === '1') {
    // headless capture mode: no animation loop (SwiftShader is slow); one small frame compiles the
    // pipelines, then the driver calls __viewer.capture() per view
    panel.style.display = 'none';
    const t = performance.now();
    output.render(scene, camera, 64, 64, null);
    firstFrameMs = performance.now() - t;
    state.ready = true;
    hud.textContent = 'capture mode';
    if (upload) await deviceCapture(api, renderer, () => output.render(scene, camera, canvas.width, canvas.height, null));
    return;
  }
  renderer.setAnimationLoop(frame);
}

main().catch((e: unknown) => {
  if (state.phase !== 'error') {
    state.phase = 'error';
    state.error = String((e as Error)?.stack ?? e);
    fatalBox.style.display = 'block';
    fatalBox.textContent = state.error;
  }
});
(window as unknown as { __viewerState: ViewerState }).__viewerState = state;
