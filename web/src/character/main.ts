// Engine character viewer (m1 v4 step 2, track T5): the shipped GLB in three.js WebGPU with the TSL
// material set, the rig.json deformation runtime, the look-dev and hero stages, a turntable and a
// headless capture path (bench/m1/engine_shots.mjs).
//
// URL: character.html?asset=<dir under /asset/>&view=front|three_quarter|profile|closeup|portrait
//      &rig=neutral|hero&turntable=1&pose=rest|stand|arms_up|...&amount=0..1&gl=1&dpr=1&params=<json>
import * as THREE from 'three/webgpu';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { DeformRuntime, type RigRules } from './deform';
import { Poser, PRESETS, applyPreset } from './poses';
import { ParamStore } from './materials/params';
import { assignMaterials, type HairSidecars } from './materials';
import { Output } from './output';
import { Stage, VIEWS, applyCamera, fallbackStage, type EngineStage, type RigName, type ViewName } from './stage';
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

async function main(): Promise<void> {
  const t0 = performance.now();
  const base = assetBase();
  const forceWebGL = q.get('gl') === '1';
  const renderer = new THREE.WebGPURenderer({ canvas, antialias: true, forceWebGL, powerPreference: 'high-performance' });
  await renderer.init();
  const isWebGPU = (renderer.backend as unknown as { isWebGPUBackend?: boolean }).isWebGPUBackend === true;
  state.backend = isWebGPU ? 'webgpu' : 'webgl2';
  renderer.outputColorSpace = THREE.LinearSRGBColorSpace; // Output encodes sRGB itself
  renderer.toneMapping = THREE.NoToneMapping;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap; // r186 WebGPU: PCF with per-light radius (PCFSoft is gone)
  const dpr = Number(q.get('dpr') ?? Math.min(devicePixelRatio, 2));
  renderer.setPixelRatio(dpr);
  const samples = 4;
  const output = new Output(renderer, samples);
  const tInit = performance.now();

  // ------------------------------------------------------------------ load
  state.phase = 'loading';
  const progress = { loaded: 0, total: 0 };
  hud.textContent = 'loading…';
  const loader = new GLTFLoader();
  const glbP = loader.loadAsync(base + 'character.glb', (e) => {
    progress.loaded = e.loaded;
    progress.total = e.total;
    hud.textContent = `loading character.glb ${(e.loaded / 1e6).toFixed(1)} / ${(e.total / 1e6).toFixed(1)} MB`;
  });
  const [gltf, rules, stageData, flow, data, paramJson] = await Promise.all([
    glbP,
    fetchJson<RigRules>(base + 'character.rig.json'),
    fetchJson<EngineStage>(base + 'engine_stage.json'),
    loadTexture(base + 'hair_atlas_flow.png'),
    loadTexture(base + 'hair_atlas_data.png'),
    fetchJson<unknown>(base + 'material_params.json'),
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
  if (!rules) state.warnings.push('no character.rig.json: helpers and correctives stay at bind');
  if (!stageData) state.warnings.push('no engine_stage.json: approximate cameras and lights (run blender/hero/export_rig.py)');
  if (!flow || !data) state.warnings.push('hair flow/data sidecars missing: tangent = UV bitangent, no strand ID');

  const scene = new THREE.Scene();
  const model = gltf.scene;
  scene.add(model);

  // bind pose from the inverse bind matrices (the node rest transforms should agree)
  let skinned: THREE.SkinnedMesh | null = null;
  model.traverse((o) => {
    if ((o as THREE.SkinnedMesh).isSkinnedMesh && !skinned) skinned = o as THREE.SkinnedMesh;
  });
  if (skinned) (skinned as THREE.SkinnedMesh).skeleton.pose();
  model.updateMatrixWorld(true);

  const rt = new DeformRuntime(model, rules ?? { version: 1 });
  const poser = new Poser(rt);
  const side: HairSidecars = { flow, data };
  const mats = assignMaterials(model, P, side, samples > 1);
  const stage = new Stage(stageData ?? fallbackStage(model), scene, mats.byName);
  const tSetup = performance.now();

  // ------------------------------------------------------------------ view / pose state
  const camera = new THREE.PerspectiveCamera(30, 1, 0.05, 200);
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

  const setView = (v: ViewName, r: RigName): void => {
    viewName = v;
    rigName = r;
    const vs = stage.setup(v, r);
    output.setGrade(r === 'hero', vs.exposure, stage.data.hero.grade);
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
    if ((o as THREE.Mesh).isMesh && g) tris += (g.index ? g.index.count : g.attributes.position!.count) / 3;
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
    frame: fs.summary(),
    first_frame_ms: Math.round(firstFrameMs),
  });

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
    /** Render view (stage camera, rig) at w x h; returns base64 RGBA8 rows, top row first. */
    capture: async (view: ViewName, rig: RigName, w: number, h: number, pose?: string) => {
      setView(view, rig);
      poseName = pose ?? (view === 'portrait' ? 'stand' : 'rest');
      amount = 1;
      applyPose();
      model.rotation.y = 0;
      applyCamera(camera, stage.view!.camera, w, h);
      const t = performance.now();
      const px = await output.capture(scene, camera, w, h);
      const ms = performance.now() - t;
      const st = statsNow();
      resize();
      let s = '';
      for (let i = 0; i < px.length; i += 0x8000) s += String.fromCharCode(...px.subarray(i, i + 0x8000));
      return { b64: btoa(s), ms: Math.round(ms), draw_calls: st.draw_calls, triangles: st.triangles_rendered, lights: stage.describeLights(), weights: rt.lastWeights };
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
        `${state.backend}  ${w}x${h}  dpr ${dpr}  MSAA ${samples}x`,
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
