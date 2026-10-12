# Spike 4: browser skeleton (Phase 0, §18 item 4)

**Status: pass. M4 Air session done 2026-10-12 (see [M4 Air results](#m4-air-results-2026-10-12-session-20261012t075030-m5ct7g-label-air-1x)).**

The full runtime path works end to end in headless Chromium on this box:

1. Vite + strict TS page, served with COOP/COEP, so `crossOriginIsolated === true`.
2. One Rust → WASM module (wasm32, SIMD128, atomics, shared memory).
3. A Web Worker runs a Rust fixed-timestep loop at 60 Hz, decoupled from rAF. Each tick it steps Rapier, runs forward kinematics and writes 200 × 64 bone matrices into a lock-free triple buffer in WASM shared memory.
4. three.js r186 `WebGPURenderer` draws 12,800 instanced bones. It reads the pose buffer as a `Float32Array` view on WASM memory, with no JS copy, and uploads it with one `writeBuffer`.
5. Telemetry (rAF histogram, CPU frame time, GPU timestamps, memory and sim tick costs) is POSTed to a Node bench server and stored as JSONL. A summariser prints p50/p95/p99 and peak memory per session.

Frame numbers from this machine mean nothing for the Air. It has no GPU, so WebGPU runs on SwiftShader at about 3 fps. Only the sizes, the sim-thread costs (which are CPU-bound) and the plumbing checks transfer.

Branch `worktree-agent-ad1e2dfae5ddc9f5d`.

## What was built

| Path | What |
|---|---|
| `Cargo.toml` | Workspace (`members = ["core"]`) with a `wasm` profile: O3, fat LTO, 1 CGU, `panic=abort` |
| `core/` (`game-core`) | Rust core. `lib.rs`: shared block, triple buffer, stats, worker loop. `physics.rs`: Rapier arena. `pose.rs`: 64-bone FK with explicit `wasm32` SIMD |
| `core/build-web.sh` | nightly + `-Z build-std` → wasm-bindgen `--target web` → wasm-opt. Prints sizes. |
| `core/examples/tick_bench.rs` | Native x86 reference for tick cost |
| `web/` | Vite 8 + TS 7 (strict + `noUncheckedIndexedAccess` + `exactOptionalPropertyTypes`), three r186 WebGPU/TSL |
| `web/public/_headers` | Cloudflare Pages COOP/COEP/CORP headers. Copied into `dist/`. Not deployed. |
| `bench/server.mjs` | Dependency-free Node server on **127.0.0.1:8787**. Serves `web/dist` with isolation headers (gzip, immutable assets) and appends `POST /telemetry` to `bench/m0/telemetry/<session>.jsonl` |
| `bench/summarize.mjs` | Per-session p50/p95/p99 for rAF interval, CPU and GPU, plus sim tick, physics and pose. Peak memory. Warm-up and late slices. 5-min trend (throttling). `--json`. |
| `bench/headless-check.mjs` | Playwright smoke test: isolation, WebGPU backend, worker ticking, telemetry on disk, offscreen readback proving the bones render |
| `bench/wasm-size.py` | Attributes WASM code bytes to crates from the name section |
| `bench/m0/telemetry/.gitignore` | Raw JSONL never committed |

### Scene and data flow
- **Rapier.** A 40 × 40 m walled arena with 24 pillars and 200 yaw-only capsules that wander under random impulses. That is 200 dynamic bodies and 29 static colliders.
- **Pose.** Each capsule drives one 64-bone tree: a 16-bone spine, two 12-bone arms and two 12-bone legs. Per-bone sines and a gait are composed parent to child with `f32x4` SIMD matrix multiplies. The output is 12,800 column-major mat4 per tick, 819,200 bytes per slot.
- **Triple buffer.** The worker publishes with one `AtomicU32::swap`. The main thread calls `acquire_pose()`, which also does one swap and never blocks, and gets back the byte offset of its slot. A new offset means new data. JS then sets `poseBuffer.array = new Float32Array(memory.buffer, ptr, len)` and `needsUpdate = true`, and three issues `queue.writeBuffer` straight from the shared view.
- **Render.** One `Mesh` with `count = 12800` (instanced draw). A `MeshStandardNodeMaterial` with `positionNode = mat4(4 × instancedDynamicBufferAttribute(poseBuffer)) * positionLocal`, flat shading, per-character neon colour from `hash(instanceIndex / 64)`. Also a ground plane, 24 pillars, hemisphere and directional light, 3 point lights, fog and 4× MSAA. Pixel ratio is 1 by default (`?dpr=` overrides).

## Versions

| Item | Version |
|---|---|
| Rust (core) | **nightly** `rustc 1.101.0-nightly (6f5da406b 2026-10-10)`, cargo `29c5daa1a 2026-10-07`, + `rust-src`, target `wasm32-unknown-unknown` (rustup, userland) |
| Rust (stable, native tests) | 1.98.1 |
| wasm-bindgen (crate + CLI) | **0.2.129**, both pinned with `=`. CLI is the official musl tarball in `~/opt/wasm-bindgen-0.2.129-x86_64-unknown-linux-musl/`, sha256 verified |
| binaryen / wasm-opt | **version_133**, official tarball in `~/opt/binaryen-version_133/`, sha256 verified |
| rapier3d | 0.36.1 (parry3d 0.31.1, glamx 0.3) |
| three / @types/three | 0.186.1 / 0.186.0 |
| vite | 8.3.4 (rolldown) |
| typescript | 7.0.2 |
| @webgpu/types | 0.1.74 |
| Node / npm | 24.21.0 / 12.1.0 |
| Playwright / Chromium | 1.64.0 / Chromium 156.0.8078.4 (`chromium-1248`, plus `chromium_headless_shell-1248`) |

## Measured numbers

The machine was shared with other spikes. 16 threads; `loadavg` was 7–17 during the runs (for example `9.22 10.01 7.97` before and `11.27 10.62 8.34` after the O3 run). The headless browser runs were pinned to 3 CPUs (`taskset -c 13-15`). Cargo ran with `-j3`.

### Sizes

| Artifact | Raw | gzip -9 | brotli -11 |
|---|---|---|---|
| Core WASM, O3 + `wasm-opt -O3` (shipped default) | **1,799,493 B** | **664,531 B** | **505,790 B** |
| Core WASM, opt-level z + `wasm-opt -Oz` (experiment) | 1,058,496 B | 455,533 B | 364,128 B |
| Cargo output before bindgen/opt (with name section) | 2,201,484 B | – | – |
| Main JS bundle (three r186 WebGPU + app) | **902,465 B** | **244,889 B** | **196,648 B** |
| Worker JS | 2,488 B | 1,203 B | 1,042 B |

Code bytes in the cargo output by crate (`bench/wasm-size.py`):

| Crate | Share |
|---|---|
| rapier3d | 47.9% (898 KB) |
| parry3d | 37.9% (711 KB) |
| core (Rust core library) | 8.4% |
| hashbrown | 2.2% |
| alloc | 0.9% |
| game_core (our code) | 0.5% (~10 KB) |

**Physics is about 86% of the module.** Rapier 0.36 also links its soft-body and staged-island solver paths, because `PhysicsWorld::step` reaches them.

### Runtime (headless Chromium + SwiftShader on Ryzen 7 7700; NOT Air numbers)

| Metric | O3 build | Oz build |
|---|---|---|
| Sim rate (target 60 Hz) | 59.98 Hz, 0 resyncs, 0 catch-up | 59.98 Hz |
| Sim tick interval | p50 16.7 / p95 17.0 / p99 17.6 ms | p50 16.7 / p95 17.0 / p99 17.7 ms |
| Tick total (physics + pose + publish) | **p50 0.90 / p95 1.38 / p99 2.36 ms** | p50 1.62 / p95 2.14 / p99 3.52 ms |
| Rapier step (200 bodies) | p50 0.52 / p95 0.76 / p99 1.60 ms | p50 1.02 / p95 1.34 ms |
| FK, 12,800 mat4 (SIMD) | p50 0.38 / p95 0.64 / p99 0.82 ms | p50 0.60 / p95 0.84 ms |
| Native x86 reference (`tick_bench`, release) | Rapier p50 0.187 / p95 0.207 ms; FK p50 0.350 / p95 0.369 ms | – |
| 3-min O3 run (same build) | tick p50 0.96 / p95 1.42; physics p50 0.56; pose p50 0.38 ms | – |
| Worker start (postMessage → Rust loop running) | 6.4 ms | – |
| WASM memory (shared; max 256 MiB) | 6.9 MiB | 6.9 MiB |
| JS heap used (`performance.memory`) | 11.7–12.4 MiB | 12.0 MiB |
| `measureUserAgentSpecificMemory` | 24.2 MiB; **each call takes 10–18 s to resolve** | 24.2 MiB |
| Telemetry | 81 POSTs in 3 min, 0 failures | – |
| Render | ~3 fps, GPU pass 200–400 ms (SwiftShader, 1280×800, 4× MSAA) | – |

- WASM Rapier runs at about 2.8× the native time on this CPU.
- WASM SIMD FK runs at about 1.1× native. The native build uses the scalar path, which LLVM auto-vectorises.
- The Oz build is 28% smaller after brotli but makes the sim tick about 1.8× slower. **Keep O3.**

### Headless check result
`node bench/headless-check.mjs` → `ok: true`. The checks were:

- COOP `same-origin`, COEP `require-corp`, `crossOriginIsolated: true`.
- Backend `webgpu`.
- Worker ticks: 10,755 in 180 s.
- Telemetry POSTed and on disk (meta + window records).
- `rendersBones: true`. The offscreen readback has 1.5% saturated "neon" pixels; see the image at `data/build/spike4/capture.png` (gitignored).

The Vite dev server also boots cross-origin isolated with WebGPU and a ticking worker. Dev has no `/telemetry` endpoint, so POSTs fail there; that is expected.

Adapter features on SwiftShader: `subgroups` and `timestamp-query` yes, `shader-f16` no. three requests every feature the adapter has, so they are on the device automatically.

## What the threads setup actually requires (measured)

1. **Nightly + `-Z build-std=std,panic_abort` + `rust-src`.**
   - On stable 1.98.1, `-C target-feature=+atomics` only warns ("unstable feature"). The module links with a **non-shared, exported** memory, so it silently becomes single-threaded.
   - Adding `--shared-memory` on stable fails: `rust-lld: error: --shared-memory is disallowed by std-….o because it was not compiled with 'atomics' or 'bulk-memory' features`.
2. **RUSTFLAGS.** `-C target-feature=+atomics,+bulk-memory,+simd128` plus **all** of these link args:
   - `--shared-memory --import-memory --max-memory=268435456`
   - `--export=__wasm_init_tls --export=__tls_size --export=__tls_align --export=__tls_base`

   rustc nightly 1.101 no longer injects them; without them the output again has a non-shared exported memory. wasm-bindgen 0.2.129 then reports each missing piece:
   - "threading requires memory to be imported; add `-Clink-arg=--import-memory`"
   - "failed to find `__wasm_init_tls`"
3. **wasm-bindgen CLI exactly equal to the crate version**, `--target web`. On the main thread `init({ module_or_path: module })`, then `init({ module_or_path: module, memory })` in each worker. Post the compiled `WebAssembly.Module` and the shared `Memory` to the worker; structured clone shares them, so there is no refetch or recompile. Call `__wbindgen_thread_destroy()` when a worker's Rust entry returns.
4. **COOP `same-origin` + COEP `require-corp`** (CORP `same-origin` added for self-hosted assets). Without them, `crossOriginIsolated` is false and there is no `SharedArrayBuffer`. The page refuses to boot and says why.
5. **Module worker** (`new Worker(new URL('./sim.worker.ts', import.meta.url), {type:'module'})`, Vite `worker.format: 'es'`).
6. **No thread pool was needed** for one dedicated sim thread.
   - `std::thread::spawn` does not work on `wasm32-unknown-unknown`, so threads are always JS workers.
   - For data-parallel work later, `wasm-bindgen-rayon` 1.3.0 is the standard pool. It has the same build requirements as above.
7. **Main thread must never block.**
   - No contended `Mutex`/`Condvar` and no `thread::sleep`: `memory.atomic.wait32` traps on the browser main thread.
   - The hand-off is one atomic swap; stats are relaxed atomic counters read through a `Uint32Array` view.
   - `std::thread::sleep` in the worker is fine; std implements it with `memory.atomic.wait32` + timeout. Tick interval p95 was 17.0 ms with sleep only and no spinning, which matters on a fanless machine.

## Failures, pitfalls and workarounds

1. **three r186 `InstancedMesh` cannot take a swapped `instanceMatrix.array`.**
   - `nodes/accessors/Instance.js` builds its `InstancedInterleavedBuffer` once from `instanceMatrix.array` and caches it in a WeakMap. Later array swaps are ignored, so triple-buffer slots would never reach the GPU.
   - **Workaround:** a plain `Mesh` with `count = N`, our own `InstancedInterleavedBuffer`, and a TSL `positionNode` built from four `instancedDynamicBufferAttribute` columns. Swapping `poseBuffer.array` plus `needsUpdate` works; three's `updateAttribute` calls `writeBuffer` on the current `array`.
2. **Headless WebGPU on a GPU-less Linux box.**
   - Default Playwright flags give an adapter, but the first canvas present loses the device: `SharedImageStub: Unable to create shared image` → "Instance dropped in popErrorScope". Buffer-only WebGPU works.
   - Working flag set, found by trial on Chromium 156:

     ```
     --enable-unsafe-webgpu --enable-unsafe-swiftshader --enable-features=Vulkan --use-vulkan=swiftshader --use-angle=swiftshader --use-webgpu-adapter=swiftshader --disable-vulkan-surface
     ```

     `--use-angle=vulkan` gives no adapter at all.
   - Even then, **WebGPU canvas content never appears in screenshots**. The check renders into a `RenderTarget` and reads it back through `window.__capture()`. The readback width must be a multiple of 64 so rows are not padded to 256 bytes (480 px gave garbled rows).
3. **Headless-shell vs full Chromium.** Playwright's default headless uses `chromium-headless-shell`. The check uses `channel: 'chromium'` (new headless). Both fail the same way without the flag set above.
4. **`measureUserAgentSpecificMemory`.**
   - It only exists when cross-origin isolated. It resolves 10–18 s after the call, because it waits for a GC.
   - It does **not** include GPU memory, so the 1.5 GB tab budget needs a separate GPU estimate.
   - The page calls it at start and then every 60 s, and attaches the result to the next window record.
5. **CPU frame time includes WebGPU back-pressure.** On SwiftShader the rAF callback took ≥ 100 ms because the canvas texture blocks until the GPU catches up. On the Air, read CPU time together with the GPU timestamp; if CPU ≈ GPU, the main thread was waiting rather than working.
6. **GPU timestamps through three.** `renderer.resolveTimestampsAsync('render')` returns the last resolved frame's pass time and dedupes while pending. The page samples it whenever no resolve is outstanding, so the GPU histogram has fewer samples than frames. Chrome quantises timestamps to 100 µs; the histogram bins are 50 µs.
7. **Shared memory growth.** A `SharedArrayBuffer` view does not detach on `memory.grow` but goes stale. The page re-creates the view from `memory.buffer` each time the slot changes, so growth is safe.
8. **Playwright browser GC.** `playwright install chromium` (1.64) deleted older cached browsers in `~/.cache/ms-playwright` (`chromium-1208`, `chromium_headless_shell-1208`, `firefox-1509`, `ffmpeg-1011`), which no registered install referenced. Another project pinned to an older Playwright would re-download them.
9. **Vite 8 / TS 7.** No issues. `tsc` 7.0.2 (native) typechecks the strict config in under a second. Vite warns about the 902 KB chunk; that is expected with three WebGPU.

## Risks

| Risk | Severity | Note / mitigation |
|---|---|---|
| Threads need **nightly + build-std** | 🟠 | Nightly breakage can block builds. Pin a dated nightly in `core/build-web.sh` (`CORE_TOOLCHAIN=nightly-2026-10-11`) and bump it deliberately. The stable path would be single-threaded WASM with sim on the main thread. |
| Rapier is 86% of WASM (506 KB br) | 🟡 | Acceptable for load. Check later whether soft bodies can be compiled out, or use parry + a thin custom solver if size matters. |
| Full pose upload each tick (819 KB → ~49 MB/s at 60 Hz) | 🟡 | Real skinning will upload far less: 1 character × ~90 bones. Move to storage buffer + GPU skinning, with partial `updateRanges` if needed. |
| Main thread is single-threaded WASM-wise | 🟡 | A Rust panic or contended lock on the main thread traps. Keep the main-thread Rust API lock-free (enforced by design in `lib.rs`). |
| Air numbers are unknown | 🔴 until measured | This is the gate. The test scene (12.8k instanced boxes, 4 lights, 4× MSAA at 1×) is modest; it validates the plumbing and gives a baseline, not the m4 look. |
| GPU memory not observable from the page | 🟡 | Read Chrome Task Manager on the Air once per session (see User actions). |

**Recommendation:**
- Adopt this skeleton and the §6 layout as is.
- Keep the O3 build.
- Pin the nightly.
- Keep one dedicated sim worker with a lock-free triple buffer.
- Bypass `InstancedMesh` for pose data.
- Run the Air session next. If CPU p50 and GPU p50 are well under 12 ms at 1×, raise `?dpr=` to find headroom before m2.

## Commands to reproduce

```sh
# one-time toolchain (userland)
rustup toolchain install nightly --profile minimal --component rust-src --target wasm32-unknown-unknown
rustup target add wasm32-unknown-unknown --toolchain stable
# wasm-bindgen 0.2.129 + binaryen version_133: official GitHub release tarballs into ~/opt (see build-web.sh)

# build
core/build-web.sh                      # nightly, -j3; prints raw + gzip size
(cd web && npm ci && npm run build)    # tsc --noEmit + vite build -> web/dist
cargo test -j3 -p game-core            # native unit tests (stable)
cargo run -j3 --release -p game-core --example tick_bench

# serve + check
node bench/server.mjs                  # http://127.0.0.1:8787/, telemetry -> bench/m0/telemetry/
(cd bench && npm ci && npx playwright install chromium)
taskset -c 13-15 node bench/headless-check.mjs --seconds 60 --shot data/build/spike4/capture.ppm
node bench/summarize.mjs               # all sessions; --warmup 300 --late 1200 --bucket 300 --json
python3 -I bench/wasm-size.py target/wasm32-unknown-unknown/wasm/game_core.wasm

# dev
(cd web && npm run dev)                # http://127.0.0.1:5173/ with COOP/COEP
```

Page query parameters:
- `label=` tags the session.
- `dpr=` sets the render pixel ratio (default 1).
- `window=` sets the telemetry window in seconds (default 10).
- `memEvery=` sets the seconds between memory measurements (default 60).
- `timestamps=0` turns GPU timing off.
- `bones=0` drops the bone mesh.

## M4 Air session (user)

**On this machine** (main checkout, after the merge):
```sh
cd ~/code/or3
core/build-web.sh && (cd web && npm ci && npm run build)
node bench/server.mjs          # leave running; prints one line per telemetry POST
```

**On the Mac:**
1. Plug in the charger. Turn off Low Power Mode. Turn off Chrome Energy Saver (`chrome://settings/performance`). Close other heavy tabs and apps. Use the built-in display (60 Hz).
2. Open the tunnel. The hostname here is `archlinux`; use whatever resolves from the Mac (LAN IP, `archlinux.local` or a Tailscale name). sshd is running on :22.
   ```sh
   ssh -N -L 8787:127.0.0.1:8787 akram@<build-box>
   ```
3. In Chrome, open **`http://localhost:8787/?label=air-1x`**. Use `localhost` so the page is a secure context, which WebGPU and SharedArrayBuffer need. Make the window full screen with Ctrl+Cmd+F.
4. Check the HUD, top left: `webgpu isolated=true wasm=[atomics,bulk-memory,simd128]` and `telemetry ok=` counting up.
5. **Keep the tab in front and focused for at least 30 minutes:** 5 min warm-up plus 20 min measured (m2), with margin so the summariser's "late" slice (t ≥ 20 min) has data. Don't switch tabs. Hidden or blurred windows are flagged and excluded.
6. Just before closing, open Chrome Task Manager (⋮ → More tools → Task manager). Note the tab's **Memory footprint** and **GPU memory** columns. Then close the tab; a final record is sent on `pagehide`.
7. Optional: a second 10-minute run at `?label=air-2x&dpr=2` to measure native-resolution headroom.

**What gets recorded** (`bench/m0/telemetry/<session>.jsonl`, gitignored):
- One `meta` record per session: UA and high-entropy UA data, battery state, adapter info, features (`shader-f16`, `subgroups`, `timestamp-query`), limits, WGSL features, canvas size, WASM features and size.
- One `window` record every 10 s, containing:
  - histograms of rAF interval (0.1 ms bins), CPU frame time and GPU pass time (0.05 ms bins);
  - sim tick, physics, pose and tick-interval histograms;
  - JS heap, WASM memory and, every 60 s, `measureUserAgentSpecificMemory`;
  - visibility and focus flags, and a Battery-Saver suspicion flag (rAF p50 > 25 ms).

**How the main session reads it:**
- Run `node bench/summarize.mjs` (or `--json`) in the main checkout.
- It prints per session:
  - after warm-up (t ≥ 300 s) and late (t ≥ 1200 s): fps, missed-vsync %, rAF/CPU/GPU p50/p95/p99, sim costs;
  - peak memory;
  - a 5-minute trend table that shows thermal throttling.

## M4 Air results (2026-10-12, session `20261012T075030-m5ct7g`, label `air-1x`)

**Pass.** Locked 60 fps for the whole 41-minute run, with 0.00 % missed vsync and no sign of thermal throttling.

Setup:
- Chrome on macOS. Adapter `apple / metal-3`; `shader-f16`, `subgroups` and `timestamp-query` all present.
- Canvas 1654 × 1026 at dpr 1. The window was not full screen, and dpr 1 renders well below native resolution.
- Battery reported `charging=false` at 99 %.
- The tab stayed **visible** the whole time, but was **unfocused** for 236 of 249 windows: another window had focus. macOS renders visible, unfocused windows at full rate, so the numbers below use `--include-hidden`. Every window was visible. The focused-only subset (13 windows) agrees: rAF p95 17.6, CPU p50 1.7, GPU p50 4.95 ms.

`node bench/summarize.mjs --include-hidden`, after warm-up (t ≥ 300 s, 2191 s of data, 131k frames):

| Metric | p50 | p95 | p99 | max |
|---|---|---|---|---|
| rAF interval (ms) | 16.7 | 17.9 | 18.6 | 18.7 |
| CPU frame (ms) | 1.70 | 2.10 | 2.20 | 2.78 |
| GPU pass (ms) | 3.10 | 5.60 | 7.65 | 22.9 |
| Sim tick, worker (ms) | 2.66 | 3.18 | 3.36 | ≥ 5.1 |
| – physics | 1.24 | 1.60 | 1.74 | 3.54 |
| – pose | 1.34 | 1.74 | 1.80 | 4.88 |

- Late slice (t ≥ 1200 s): rAF p95 18.1, CPU p50 1.65, GPU p50 3.05 ms. The 5-minute trend is flat to improving, with no throttling.
- Sim held exactly 60 Hz with 0 resyncs and 0 catch-ups. Tick-interval p95 is 20.7 ms: worker wake-up jitter, absorbed by the fixed timestep.
- Memory:
  - Measured by the page (`measureUserAgentSpecificMemory`): peak 33.3 MiB. JS heap 11.9 MiB, WASM 6.9 MiB.
  - Chrome Task Manager: GPU Process 374 MB for the whole browser, an upper bound for this tab. Browser process 150 MB. The tab's own footprint showed "–", and the GPU-memory column was not enabled.
  - Even taking every number as the tab's, the total is far under the 1.5 GB budget.

**Reading against m2 (NOTES §15, §17 q8):**
- Work per frame is max(CPU p50, GPU p50) = **3.1 ms** against the 12 ms budget. That leaves about 9 ms of headroom for real shading.
- This scene is light: instanced bones, flat shading, no post. It proves the plumbing and the sim cost, not the Painted Neon-Noir budget, which still needs measuring at `m4`.
- **The "rAF p95 ≤ 16.6 ms" wording is unattainable as written.** rAF timestamps jitter by about ±1 ms around the 16.7 ms vsync even at 0 % missed frames, which is what this run shows. Proposed replacement: **missed vsync ≤ 1 %**, meaning frames whose rAF interval exceeds 1.5 × the refresh interval. That is the summariser's existing metric, and this run scores 0.00 %.
- Next time: full screen at `?dpr=2` to measure native-resolution cost (optional).

## User actions
1. **Run the M4 Air session** above. It is the only remaining gate for this spike.
2. Record the Chrome Task Manager memory footprint and GPU memory at the end of the session (the page cannot see GPU memory).
3. Nothing to install with `sudo`: everything ran in userland (rustup nightly, `~/opt` tarballs, npm, Playwright).

## Proposed NOTES.md updates
- **§6 Runtime › Build.** Replace "Vite + cargo / wasm-bindgen" with:
  - Vite 8 + TS 7, cargo **nightly** (pinned) with `-Z build-std=std,panic_abort`, wasm-bindgen CLI pinned to the crate version, binaryen `wasm-opt -O3`.
  - Threads need `+atomics,+bulk-memory,+simd128` plus the shared/imported memory and TLS-export link args (spike 4).
- **§6 Runtime › Core.** Add: the sim runs in a dedicated Web Worker at a fixed 60 Hz and hands poses over through a lock-free triple buffer. The main thread never blocks, and its Rust calls must be lock-free.
- **§6 Repo layout.** Confirm `core/` + `web/` + `bench/` as built. `core/build-web.sh` writes the wasm-bindgen output to `web/src/core-wasm/` (gitignored).
- **§10 Apple GPU notes / renderer.** Add: three r186 `InstancedMesh` caches `instanceMatrix.array`. For WASM-driven transforms, use a plain `Mesh.count` with our own `InstancedInterleavedBuffer` (or a storage buffer) in TSL.
- **§13 Chrome WebGPU.** Add:
  - `measureUserAgentSpecificMemory` takes 10–18 s and excludes GPU memory.
  - CPU frame time includes WebGPU back-pressure, so read it together with GPU timestamps.
- **§15 m2.** Define "frame time":
  - "p95 ≤ 16.6 ms" applies to the **rAF interval** (vsync-locked; summariser bin edge 16.7–16.8 ms).
  - "median ≤ 12 ms" applies to **max(CPU frame p50, GPU pass p50)**.
  - Measured after 5 min warm-up for ≥ 20 min, with a late slice from t = 20 min.
- **§16 Risks.** Add:
  - "Threads depend on nightly build-std" (🟠).
  - "Rapier+parry ≈ 86% of WASM, 506 KB br" (🟡).
- **§4 Build machine.** Add:
  - Headless WebGPU works via Playwright Chromium + SwiftShader (flag set in this report), at about 3 fps; useful for correctness only.
  - Chrome/Chromium is not installed system-wide; Playwright's is in `~/.cache/ms-playwright`.
