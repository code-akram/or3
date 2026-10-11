// Phase 0 spike 4: browser skeleton.
// three.js WebGPURenderer drawing INSTANCES x BONES boxes whose transforms come straight from the
// Rust/WASM pose buffer (shared memory, written by a worker thread at a fixed 60 Hz tick).
import * as THREE from 'three/webgpu';
import { color, hash, instanceIndex, instancedDynamicBufferAttribute, mat4, mix, positionLocal, uint, vec4 } from 'three/tsl';
import { arena_layout } from './core-wasm/game_core.js';
import { Stat, startSim, type Sim } from './sim';
import { Graph, Hist, Poster, makeSessionId, sparse } from './telemetry';

const params = new URLSearchParams(location.search);
const WINDOW_S = Number(params.get('window') ?? 10);
const MEMORY_EVERY_S = Number(params.get('memEvery') ?? 60);
const PIXEL_RATIO = Number(params.get('dpr') ?? 1);
const LABEL = params.get('label') ?? '';

const hud = document.getElementById('hud') as HTMLDivElement;
const fatalBox = document.getElementById('fatal') as HTMLDivElement;
const canvas = document.getElementById('view') as HTMLCanvasElement;
const graphCanvas = document.getElementById('graph') as HTMLCanvasElement;

/** Boot status for automated checks (Playwright reads this). */
interface BootState {
  phase: string;
  crossOriginIsolated: boolean;
  backend?: string;
  workerTicks?: number;
  frames?: number;
  telemetryOk?: number;
  error?: string;
  session?: string;
}
const boot: BootState = { phase: 'start', crossOriginIsolated };
(window as unknown as { __boot: BootState }).__boot = boot;

function fatal(msg: string): never {
  boot.phase = 'error';
  boot.error = msg;
  fatalBox.style.display = 'block';
  fatalBox.textContent = msg;
  throw new Error(msg);
}

interface GpuInfo {
  available: boolean;
  adapterInfo?: Record<string, string>;
  features: string[];
  wgslFeatures: string[];
  limits: Record<string, number>;
  wanted: { 'shader-f16': boolean; subgroups: boolean; 'timestamp-query': boolean };
}

async function detectGpu(): Promise<GpuInfo> {
  const info: GpuInfo = {
    available: false,
    features: [],
    wgslFeatures: [],
    limits: {},
    wanted: { 'shader-f16': false, subgroups: false, 'timestamp-query': false },
  };
  if (!('gpu' in navigator)) return info;
  const adapter = await navigator.gpu.requestAdapter({ powerPreference: 'high-performance' });
  if (!adapter) return info;
  info.available = true;
  info.features = [...adapter.features].map(String).sort();
  info.wgslFeatures = [...navigator.gpu.wgslLanguageFeatures].map(String).sort();
  const ai = adapter.info;
  info.adapterInfo = { vendor: ai.vendor, architecture: ai.architecture, device: ai.device, description: ai.description };
  for (const k of [
    'maxBufferSize',
    'maxStorageBufferBindingSize',
    'maxUniformBufferBindingSize',
    'maxComputeWorkgroupStorageSize',
    'maxComputeInvocationsPerWorkgroup',
    'maxColorAttachmentBytesPerSample',
    'maxTextureDimension2D',
  ] as const) {
    info.limits[k] = adapter.limits[k];
  }
  info.wanted = {
    'shader-f16': adapter.features.has('shader-f16'),
    subgroups: adapter.features.has('subgroups'),
    'timestamp-query': adapter.features.has('timestamp-query'),
  };
  return info;
}

async function environment(): Promise<Record<string, unknown>> {
  const nav = navigator as Navigator & {
    userAgentData?: { getHighEntropyValues(h: string[]): Promise<Record<string, unknown>> };
    getBattery?: () => Promise<{ charging: boolean; level: number }>;
    deviceMemory?: number;
  };
  const env: Record<string, unknown> = {
    userAgent: navigator.userAgent,
    hardwareConcurrency: navigator.hardwareConcurrency,
    deviceMemory: nav.deviceMemory,
    screen: { w: screen.width, h: screen.height, dpr: devicePixelRatio },
  };
  try {
    env.uaData = await nav.userAgentData?.getHighEntropyValues(['platform', 'platformVersion', 'architecture', 'model', 'fullVersionList']);
  } catch {
    /* not available */
  }
  try {
    const b = await nav.getBattery?.();
    if (b) env.battery = { charging: b.charging, level: b.level };
  } catch {
    /* not available */
  }
  return env;
}

function buildScene(sim: Sim) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x07070b);
  scene.fog = new THREE.Fog(0x07070b, 30, 90);

  const layout = arena_layout();
  const half = layout[0] ?? 20;
  const pillarHalf = layout[1] ?? 0.6;

  const ground = new THREE.Mesh(
    new THREE.PlaneGeometry(half * 2, half * 2),
    new THREE.MeshStandardNodeMaterial({ color: 0x15161d, roughness: 0.35, metalness: 0.0 }),
  );
  ground.rotation.x = -Math.PI / 2;
  scene.add(ground);

  const pillarMat = new THREE.MeshStandardNodeMaterial({ color: 0x2a2c38, roughness: 0.6 });
  const pillarGeo = new THREE.BoxGeometry(pillarHalf * 2, 4, pillarHalf * 2);
  for (let i = 2; i + 1 < layout.length; i += 2) {
    const p = new THREE.Mesh(pillarGeo, pillarMat);
    p.position.set(layout[i] ?? 0, 2, layout[i + 1] ?? 0);
    scene.add(p);
  }

  scene.add(new THREE.HemisphereLight(0x5070ff, 0x200818, 0.6));
  const key = new THREE.DirectionalLight(0xffe0c0, 1.6);
  key.position.set(10, 20, 8);
  scene.add(key);
  for (const [c, x, z] of [
    [0xff2fa0, -12, -12],
    [0x00e5d0, 12, 10],
    [0xffa000, 0, 16],
  ] as const) {
    const l = new THREE.PointLight(c, 80, 30, 2);
    l.position.set(x, 3, z);
    scene.add(l);
  }

  // Pose buffer -> GPU. The interleaved buffer's `array` is a Float32Array view on WASM shared
  // memory; on each new slot we swap the view (no JS copy) and three issues one writeBuffer.
  const total = sim.instances * sim.bones;
  const poseBuffer = new THREE.InstancedInterleavedBuffer(new Float32Array(sim.memory.buffer, sim.acquire(), sim.slotFloats), 16, 1);
  poseBuffer.setUsage(THREE.DynamicDrawUsage);
  const boneMatrix = mat4(
    instancedDynamicBufferAttribute(poseBuffer, 'vec4', 16, 0),
    instancedDynamicBufferAttribute(poseBuffer, 'vec4', 16, 4),
    instancedDynamicBufferAttribute(poseBuffer, 'vec4', 16, 8),
    instancedDynamicBufferAttribute(poseBuffer, 'vec4', 16, 12),
  );
  const boneMat = new THREE.MeshStandardNodeMaterial({ roughness: 0.4, metalness: 0.1 });
  boneMat.flatShading = true; // normals from screen-space derivatives; no normal matrix needed
  boneMat.positionNode = boneMatrix.mul(vec4(positionLocal, 1)).xyz;
  const character = instanceIndex.div(uint(sim.bones));
  const h = hash(character);
  boneMat.colorNode = mix(mix(color(0xff2fa0), color(0x00e5d0), h), color(0xffa000), hash(character.add(uint(7919))).mul(0.5));

  const boneGeo = new THREE.BoxGeometry(1, 1, 1);
  boneGeo.translate(0, 0.5, 0);
  const bones = new THREE.Mesh(boneGeo, boneMat);
  (bones as THREE.Mesh & { count: number }).count = total;
  bones.frustumCulled = false;
  if (params.get('bones') !== '0') scene.add(bones);

  return { scene, poseBuffer, half };
}

async function main(): Promise<void> {
  if (!crossOriginIsolated) fatal('Page is not cross-origin isolated (COOP/COEP headers missing): SharedArrayBuffer unavailable.');
  boot.phase = 'gpu-detect';
  const gpu = await detectGpu();
  const env = await environment();

  boot.phase = 'wasm';
  const sim = await startSim();
  boot.phase = 'renderer';

  const trackTimestamp = gpu.wanted['timestamp-query'] && params.get('timestamps') !== '0';
  const renderer = new THREE.WebGPURenderer({ canvas, antialias: true, trackTimestamp, powerPreference: 'high-performance' });
  await renderer.init();
  const backendAny = renderer.backend as unknown as { isWebGPUBackend?: boolean; device?: GPUDevice };
  const backend = backendAny.isWebGPUBackend ? 'webgpu' : 'webgl2';
  boot.backend = backend;
  const deviceFeatures = backendAny.device ? [...backendAny.device.features].map(String).sort() : [];
  renderer.setPixelRatio(PIXEL_RATIO);
  renderer.setSize(innerWidth, innerHeight, false);
  addEventListener('resize', () => renderer.setSize(innerWidth, innerHeight, false));

  const { scene, poseBuffer, half } = buildScene(sim);
  const camera = new THREE.PerspectiveCamera(55, innerWidth / innerHeight, 0.1, 200);
  addEventListener('resize', () => {
    camera.aspect = innerWidth / innerHeight;
    camera.updateProjectionMatrix();
  });

  const session = makeSessionId();
  boot.session = session;
  const poster = new Poster(session);
  poster.send({
    type: 'meta',
    label: LABEL,
    url: location.pathname + location.search,
    crossOriginIsolated,
    backend,
    gpu,
    deviceFeatures,
    trackTimestamp,
    env,
    build: { wasmFeatures: sim.features, wasmBytes: sim.wasmBytes, instances: sim.instances, bones: sim.bones, slotBytes: sim.slotFloats * 4 },
    sim: { benchPoseMainThreadMs: sim.benchPoseMs, workerStartMs: sim.workerStartMs, tickHz: 60 },
    render: { pixelRatio: PIXEL_RATIO, canvas: [canvas.width, canvas.height], antialias: true },
    windowS: WINDOW_S,
  });

  // --- telemetry state ---------------------------------------------------------------------
  const rafHist = new Hist(0.1, 2000); // 0..200 ms
  const cpuHist = new Hist(0.05, 2000); // 0..100 ms
  const gpuHist = new Hist(0.05, 2000); // 0..100 ms
  const graph = new Graph(graphCanvas);
  const t0 = performance.now();
  let lastRaf = 0;
  let windowStart = t0;
  let seq = 0;
  let frames = 0;
  let windowFrames = 0;
  let poseUploads = 0;
  let hiddenDuringWindow = document.visibilityState !== 'visible';
  let blurredDuringWindow = !document.hasFocus();
  let lastPtr = -1;
  let gpuPending = false;
  let lastGpuMs = Number.NaN;
  let prevStats = Uint32Array.from(sim.stats());
  let uasm: { bytes: number; at: number; tookMs: number; top: [string, number][] } | null = null;
  let uasmPending = false;
  let lastUasmAt = -Infinity;
  let peakUasm = 0;

  addEventListener('visibilitychange', () => {
    if (document.visibilityState !== 'visible') hiddenDuringWindow = true;
  });
  addEventListener('blur', () => (blurredDuringWindow = true));

  const measureMemory = () => {
    const perf = performance as Performance & {
      measureUserAgentSpecificMemory?: () => Promise<{ bytes: number; breakdown: { bytes: number; types: string[] }[] }>;
    };
    if (!perf.measureUserAgentSpecificMemory || uasmPending) return;
    uasmPending = true;
    const start = performance.now();
    perf
      .measureUserAgentSpecificMemory()
      .then((m) => {
        const byType = new Map<string, number>();
        for (const b of m.breakdown) {
          const k = b.types.join('+') || 'other';
          byType.set(k, (byType.get(k) ?? 0) + b.bytes);
        }
        uasm = { bytes: m.bytes, at: performance.now() - t0, tookMs: performance.now() - start, top: [...byType].sort((a, b) => b[1] - a[1]).slice(0, 6) };
        peakUasm = Math.max(peakUasm, m.bytes);
      })
      .catch((e: unknown) => {
        uasm = { bytes: -1, at: performance.now() - t0, tookMs: performance.now() - start, top: [['error: ' + String(e), 0]] };
      })
      .finally(() => (uasmPending = false));
  };

  const simDelta = (cur: Uint32Array) => {
    const d = (base: number) => {
      const out = new Uint32Array(Stat.HIST_BINS);
      for (let i = 0; i < Stat.HIST_BINS; i++) out[i] = (cur[base + i] ?? 0) - (prevStats[base + i] ?? 0);
      return sparse(out);
    };
    const v = (i: number) => (cur[i] ?? 0) - (prevStats[i] ?? 0);
    return {
      ticks: v(Stat.TICKS),
      resyncs: v(Stat.RESYNCS),
      catchup: v(Stat.CATCHUP_TICKS),
      awakeBodies: cur[Stat.AWAKE_BODIES] ?? 0,
      tickUs: { binUs: Stat.WORK_BIN_US, sparse: d(Stat.HIST_TICK) },
      physUs: { binUs: Stat.WORK_BIN_US, sparse: d(Stat.HIST_PHYS) },
      poseUs: { binUs: Stat.WORK_BIN_US, sparse: d(Stat.HIST_POSE) },
      intervalUs: { binUs: Stat.INTERVAL_BIN_US, sparse: d(Stat.HIST_INTERVAL) },
    };
  };

  const flushWindow = (now: number, final = false) => {
    const cur = Uint32Array.from(sim.stats());
    const perfMem = (performance as Performance & { memory?: { usedJSHeapSize: number; totalJSHeapSize: number; jsHeapSizeLimit: number } }).memory;
    const rafS = rafHist.summary();
    poster.send(
      {
        type: 'window',
        seq: seq++,
        final,
        tStartS: (windowStart - t0) / 1000,
        tEndS: (now - t0) / 1000,
        frames: windowFrames,
        poseUploads,
        visible: !hiddenDuringWindow,
        focused: !blurredDuringWindow,
        raf: rafS,
        cpu: cpuHist.summary(),
        gpu: trackTimestamp ? gpuHist.summary() : null,
        throttleSuspected: rafS.count > 30 && rafS.p50 > 25,
        sim: simDelta(cur),
        mem: {
          wasmBytes: sim.memory.buffer.byteLength,
          jsHeapUsed: perfMem?.usedJSHeapSize ?? null,
          jsHeapTotal: perfMem?.totalJSHeapSize ?? null,
          uasm,
        },
        canvas: [canvas.width, canvas.height],
        renderInfo: { calls: renderer.info.render.calls, triangles: renderer.info.render.triangles, geometries: renderer.info.memory.geometries, textures: renderer.info.memory.textures },
      },
      final,
    );
    uasm = null;
    prevStats = cur;
    rafHist.reset();
    cpuHist.reset();
    gpuHist.reset();
    windowFrames = 0;
    poseUploads = 0;
    windowStart = now;
    hiddenDuringWindow = document.visibilityState !== 'visible';
    blurredDuringWindow = !document.hasFocus();
  };
  addEventListener('pagehide', () => flushWindow(performance.now(), true));

  // Test hook: render one frame into an offscreen target and read it back (headless checks can't
  // see the WebGPU canvas in screenshots). Returns RGBA8 as base64.
  (window as unknown as { __capture: (w: number, h: number) => Promise<string> }).__capture = async (w, h) => {
    const rt = new THREE.RenderTarget(w, h);
    const aspect = camera.aspect;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setRenderTarget(rt);
    renderer.render(scene, camera);
    renderer.setRenderTarget(null);
    camera.aspect = aspect;
    camera.updateProjectionMatrix();
    const px = (await renderer.readRenderTargetPixelsAsync(rt, 0, 0, w, h)) as Uint8Array;
    rt.dispose();
    let s = '';
    for (let i = 0; i < px.length; i += 0x8000) s += String.fromCharCode(...px.subarray(i, i + 0x8000));
    return btoa(s);
  };

  boot.phase = 'running';
  measureMemory();
  lastUasmAt = performance.now();

  const frame = (now: number) => {
    requestAnimationFrame(frame);
    const start = performance.now();
    const rafMs = lastRaf ? now - lastRaf : Number.NaN;
    if (lastRaf) rafHist.add(rafMs);
    lastRaf = now;

    // Zero-copy pose hand-off: a new pointer means the worker published a new slot.
    const ptr = sim.acquire();
    if (ptr !== lastPtr) {
      poseBuffer.array = new Float32Array(sim.memory.buffer, ptr, sim.slotFloats);
      poseBuffer.needsUpdate = true;
      lastPtr = ptr;
      poseUploads++;
    }

    const t = (now - t0) / 1000;
    const r = half * 1.25;
    camera.position.set(Math.cos(t * 0.05) * r, 14 + 4 * Math.sin(t * 0.11), Math.sin(t * 0.05) * r);
    camera.lookAt(0, 0.5, 0);

    renderer.render(scene, camera);

    if (trackTimestamp && !gpuPending) {
      gpuPending = true;
      renderer
        .resolveTimestampsAsync(THREE.TimestampQuery.RENDER)
        .then((ms) => {
          if (typeof ms === 'number' && ms > 0) {
            gpuHist.add(ms);
            lastGpuMs = ms;
          }
        })
        .catch(() => undefined)
        .finally(() => (gpuPending = false));
    }

    frames++;
    windowFrames++;
    boot.frames = frames;
    graph.push(rafMs, performance.now() - start, lastGpuMs);
    graph.draw();

    if (frames % 15 === 0) {
      const st = sim.stats();
      boot.workerTicks = st[Stat.TICKS] ?? 0;
      boot.telemetryOk = poster.ok;
      const mem = sim.memory.buffer.byteLength / 2 ** 20;
      hud.textContent = [
        `session ${session}${LABEL ? ' [' + LABEL + ']' : ''}`,
        `${backend}  isolated=${crossOriginIsolated}  wasm=[${sim.features}]`,
        `f16=${gpu.wanted['shader-f16']} subgroups=${gpu.wanted.subgroups} ts=${trackTimestamp}`,
        `${sim.instances}x${sim.bones} bones  canvas ${canvas.width}x${canvas.height} @${PIXEL_RATIO}`,
        `rAF p50 ${rafHist.quantile(0.5).toFixed(1)}  p95 ${rafHist.quantile(0.95).toFixed(1)} ms`,
        `CPU p50 ${cpuHist.quantile(0.5).toFixed(2)}  p95 ${cpuHist.quantile(0.95).toFixed(2)} ms`,
        `GPU last ${Number.isNaN(lastGpuMs) ? 'n/a' : lastGpuMs.toFixed(2)} ms`,
        `sim ticks ${st[Stat.TICKS]}  tick ${st[Stat.LAST_TICK_US]}us (phys ${st[Stat.LAST_PHYS_US]} pose ${st[Stat.LAST_POSE_US]})`,
        `wasm mem ${mem.toFixed(1)} MiB  uasm peak ${(peakUasm / 2 ** 20).toFixed(0)} MiB`,
        `telemetry ok=${poster.ok} fail=${poster.failed} ${poster.lastError}`,
        `t ${((now - t0) / 1000).toFixed(0)} s`,
      ].join('\n');
    }

    cpuHist.add(performance.now() - start);

    if (now - windowStart >= WINDOW_S * 1000) {
      flushWindow(now);
      if ((now - lastUasmAt) / 1000 >= MEMORY_EVERY_S) {
        lastUasmAt = now;
        measureMemory();
      }
    }
  };
  requestAnimationFrame(frame);
}

main().catch((e: unknown) => {
  if (boot.phase !== 'error') fatal(e instanceof Error ? `${e.message}\n${e.stack ?? ''}` : String(e));
});
