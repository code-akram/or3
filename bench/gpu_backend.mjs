// GPU backend for the headless Chromium capture tools (track GPU1, bench/m1/v4/gpu1-hw-backend.md).
//
//   --gpu swiftshader   (default) WebGPU on SwiftShader (Vulkan on the CPU). Unlocked; any number may run.
//   --gpu hw            WebGPU on the real GPU through native Vulkan (here the Ryzen's Raphael iGPU,
//                       RADV from vulkan-radeon). The adapter is checked (vendor ENGINE_GPU_VENDOR,
//                       default amd; never SwiftShader, never none) or the run fails, and the whole
//                       browser session holds an exclusive flock on ENGINE_GPU_LOCK (default
//                       /tmp/or3-gpu.lock): the iGPU is small and shared with headless EEVEE.
// The env var ENGINE_GPU=hw|swiftshader sets the default; --gpu wins.
//
// Used by bench/m1/engine_shots.mjs, bench/m1/air_selftest.mjs and bench/headless-check.mjs.
import { spawn } from 'node:child_process';

export const GPU_MODES = ['swiftshader', 'hw'];
export const GPU_LOCK = process.env.ENGINE_GPU_LOCK || '/tmp/or3-gpu.lock';
export const HW_VENDOR = (process.env.ENGINE_GPU_VENDOR || 'amd').toLowerCase();

/** --gpu X, else $ENGINE_GPU, else swiftshader. */
export function gpuMode(argv, env = process.env) {
  const i = argv.indexOf('--gpu');
  const m = (i >= 0 ? argv[i + 1] : env.ENGINE_GPU || 'swiftshader').toLowerCase();
  if (!GPU_MODES.includes(m)) {
    console.error(`--gpu / ENGINE_GPU must be one of ${GPU_MODES.join('|')}, got '${m}'`);
    process.exit(2);
  }
  return m;
}

/** Chromium flags per mode. SwiftShader: found by trial in bench/headless-check.mjs (Vulkan on
 * SwiftShader and no Vulkan surface, or the canvas swap chain loses the device on first present).
 * hw: native Vulkan (RADV) with the same surface workaround; no --enable-unsafe-swiftshader, so Dawn
 * cannot hand out the CPU adapter as a fallback. --enable-webgpu-developer-features only unquantizes
 * the timestamp queries (100 us steps otherwise) and exposes adapter info; it changes no limit. */
export function chromiumArgs(mode, extra = []) {
  const sw = [
    '--enable-unsafe-webgpu',
    '--enable-unsafe-swiftshader',
    '--enable-features=Vulkan',
    '--use-vulkan=swiftshader',
    '--use-angle=swiftshader',
    '--use-webgpu-adapter=swiftshader',
    '--disable-vulkan-surface',
  ];
  const hw = [
    '--enable-unsafe-webgpu',
    '--enable-features=Vulkan',
    '--use-vulkan=native',
    '--use-angle=vulkan',
    '--disable-vulkan-surface',
    '--ignore-gpu-blocklist',
    '--enable-webgpu-developer-features',
  ];
  return [...(mode === 'hw' ? hw : sw), ...extra];
}

/** The WebGPU adapter as the page sees it (needs a secure context: a 127.0.0.1 page, not about:blank).
 * Same request as the viewer's (powerPreference high-performance). */
export async function probeAdapter(page) {
  return page.evaluate(async () => {
    if (!navigator.gpu) return { error: 'no navigator.gpu' };
    try {
      const a = await navigator.gpu.requestAdapter({ powerPreference: 'high-performance' });
      if (!a) return { error: 'requestAdapter returned null' };
      const i = a.info ?? {};
      const L = a.limits;
      return {
        vendor: i.vendor,
        architecture: i.architecture,
        device: i.device,
        description: i.description,
        driver: i.driver ?? undefined,
        backend: i.backendType ?? undefined,
        fallback: i.isFallbackAdapter ?? a.isFallbackAdapter ?? undefined,
        timestamp_query: a.features.has('timestamp-query'),
        limits: {
          maxSampledTexturesPerShaderStage: L.maxSampledTexturesPerShaderStage,
          maxSamplersPerShaderStage: L.maxSamplersPerShaderStage,
          maxColorAttachmentBytesPerSample: L.maxColorAttachmentBytesPerSample,
          maxTextureDimension2D: L.maxTextureDimension2D,
          maxBufferSize: L.maxBufferSize,
          maxStorageBufferBindingSize: L.maxStorageBufferBindingSize,
        },
      };
    } catch (e) {
      return { error: String(e?.message ?? e) };
    }
  });
}

/** Throws unless the adapter belongs to the mode: hw = a real GPU of HW_VENDOR, swiftshader = SwiftShader. */
export function checkAdapter(mode, info) {
  if (!info || info.error) throw new Error(`[gpu ${mode}] no WebGPU adapter: ${info?.error ?? 'none'}`);
  const soft = /swiftshader|llvmpipe|lavapipe|software/i.test(`${info.vendor} ${info.architecture} ${info.description} ${info.device}`) || info.fallback === true;
  if (mode === 'hw') {
    if (soft) throw new Error(`[gpu hw] the adapter fell back to software (${info.vendor} / ${info.architecture} / ${info.description}); refusing to record it as hw`);
    if ((info.vendor ?? '').toLowerCase() !== HW_VENDOR) throw new Error(`[gpu hw] adapter vendor '${info.vendor}' (${info.architecture}) is not '${HW_VENDOR}' (ENGINE_GPU_VENDOR)`);
  } else if (!soft) {
    throw new Error(`[gpu swiftshader] expected the SwiftShader adapter, got ${info.vendor} / ${info.architecture}`);
  }
  return info;
}

/** One line for logs and reports: "hw: amd rdna-2 (...)" */
export function adapterLine(mode, info) {
  if (!info || info.error) return `${mode}: no adapter`;
  return `${mode}: ${info.vendor} ${info.architecture}${info.description ? ` (${info.description})` : ''}`;
}

/** Exclusive GPU lock for hw sessions (flock(1) on GPU_LOCK, held by a child that lives until release()
 * or until this process dies: its stdin is our pipe, so the lock can't outlive us). SwiftShader: no lock.
 * Resolves to { release, waited_ms }. */
export async function acquireGpuLock(mode, { waitS = 7200, tag = 'capture' } = {}) {
  if (mode !== 'hw') return { release: async () => {}, waited_ms: 0, lock: null };
  const t0 = Date.now();
  const child = spawn('flock', ['--exclusive', '--wait', String(waitS), GPU_LOCK, 'sh', '-c', 'echo locked; exec cat > /dev/null'], { stdio: ['pipe', 'pipe', 'inherit'] });
  const note = setTimeout(() => console.error(`[gpu hw] ${tag}: waiting for ${GPU_LOCK} (another hw session holds the GPU)`), 2000);
  try {
    await new Promise((res, rej) => {
      let out = '';
      child.stdout.on('data', (d) => {
        out += d;
        if (out.includes('locked')) res();
      });
      child.once('error', (e) => rej(new Error(`[gpu hw] flock: ${e.message}`)));
      child.once('exit', (c) => rej(new Error(`[gpu hw] could not lock ${GPU_LOCK} within ${waitS} s (flock exit ${c})`)));
    });
  } finally {
    clearTimeout(note);
  }
  child.removeAllListeners('exit');
  const waited = Date.now() - t0;
  if (waited > 2000) console.error(`[gpu hw] ${tag}: got ${GPU_LOCK} after ${(waited / 1000).toFixed(1)} s`);
  let released = false;
  const release = async () => {
    if (released) return;
    released = true;
    const done = new Promise((r) => child.once('exit', r));
    child.stdin.end();
    await done;
  };
  return { release, waited_ms: waited, lock: GPU_LOCK };
}
