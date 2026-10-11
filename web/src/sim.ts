// Main-thread side of the Rust core: instantiate WASM on shared memory, start the simulation
// worker, and hand out zero-copy views of the newest pose slot.
import init, {
  acquire_pose,
  bench_pose,
  bone_count,
  build_features,
  create_shared,
  instance_count,
  slot_floats,
  stats_len,
  stats_ptr,
} from './core-wasm/game_core.js';
import wasmUrl from './core-wasm/game_core_bg.wasm?url';
import type { StartMessage } from './sim.worker';

/** Mirrors `core/src/lib.rs` `stat` module. */
export const Stat = {
  TICKS: 0,
  RESYNCS: 1,
  CATCHUP_TICKS: 2,
  WORKER_STARTED: 3,
  LAST_TICK_US: 4,
  LAST_PHYS_US: 5,
  LAST_POSE_US: 6,
  PUBLISHED: 7,
  AWAKE_BODIES: 8,
  HIST_BINS: 256,
  HIST_TICK: 16,
  HIST_PHYS: 16 + 256,
  HIST_POSE: 16 + 512,
  HIST_INTERVAL: 16 + 768,
  WORK_BIN_US: 20,
  INTERVAL_BIN_US: 100,
} as const;

export interface Sim {
  memory: WebAssembly.Memory;
  instances: number;
  bones: number;
  slotFloats: number;
  features: string;
  wasmBytes: number;
  /** Main-thread FK cost on this thread, ms per tick (one-off micro benchmark). */
  benchPoseMs: number;
  workerStartMs: number;
  /** Returns the byte offset of the newest pose slot (non-blocking). */
  acquire(): number;
  /** Fresh view of the shared stats block (u32). */
  stats(): Uint32Array;
}

export async function startSim(): Promise<Sim> {
  const response = await fetch(wasmUrl);
  const bytes = await response.arrayBuffer();
  const module = await WebAssembly.compile(bytes);
  const exports = await init({ module_or_path: module });
  const memory = exports.memory;
  if (!(memory.buffer instanceof SharedArrayBuffer)) {
    throw new Error('WASM memory is not shared: build is missing atomics/shared-memory');
  }

  const shared = create_shared();
  const statsOffset = stats_ptr(shared);
  const statsLength = stats_len();
  const benchPoseMs = bench_pose(30);

  const worker = new Worker(new URL('./sim.worker.ts', import.meta.url), { type: 'module', name: 'sim' });
  const t0 = performance.now();
  await new Promise<void>((resolve, reject) => {
    worker.onmessage = (e: MessageEvent<{ type: string; message?: string }>) => {
      if (e.data.type === 'started') resolve();
      else if (e.data.type === 'error') reject(new Error(`sim worker: ${e.data.message ?? ''}`));
    };
    worker.onerror = (e) => reject(new Error(`sim worker: ${e.message}`));
    const msg: StartMessage = { module, memory, shared };
    worker.postMessage(msg);
  });
  const workerStartMs = performance.now() - t0;

  return {
    memory,
    instances: instance_count(),
    bones: bone_count(),
    slotFloats: slot_floats(),
    features: build_features(),
    wasmBytes: bytes.byteLength,
    benchPoseMs,
    workerStartMs,
    acquire: () => acquire_pose(shared),
    stats: () => new Uint32Array(memory.buffer, statsOffset, statsLength),
  };
}
