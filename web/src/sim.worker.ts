// Simulation worker: instantiates the same WASM module on the same shared memory and runs the
// Rust fixed-timestep loop. The loop blocks this worker (it sleeps with memory.atomic.wait32),
// so the worker never receives messages after it starts; stop it via the shared stop flag.
import init, { run_sim } from './core-wasm/game_core.js';

export interface StartMessage {
  module: WebAssembly.Module;
  memory: WebAssembly.Memory;
  shared: number;
}

self.onmessage = async (event: MessageEvent<StartMessage>) => {
  const { module, memory, shared } = event.data;
  try {
    const exports = await init({ module_or_path: module, memory });
    self.postMessage({ type: 'started' });
    run_sim(shared);
    exports.__wbindgen_thread_destroy();
    self.postMessage({ type: 'stopped' });
  } catch (err) {
    self.postMessage({ type: 'error', message: String(err instanceof Error ? err.stack ?? err.message : err) });
  }
};
