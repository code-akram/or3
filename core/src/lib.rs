//! Browser core, compiled to `wasm32-unknown-unknown` with SIMD and threads.
//!
//! Phase 0 spike 4: proves the runtime path end to end.
//!
//! * The main thread allocates a [`Shared`] block in WASM shared memory and returns its address.
//! * A Web Worker instantiates the same module on the same memory and calls [`run_sim`], which
//!   runs a fixed-timestep loop (decoupled from `requestAnimationFrame`): a Rapier step, then a
//!   forward-kinematics pass that writes `INSTANCES * BONES` column-major 4x4 matrices into one
//!   slot of a lock-free triple buffer.
//! * The renderer calls [`acquire_pose`] once per frame (never blocks) and reads the returned slot
//!   through a `Float32Array` view on `memory.buffer`, uploading it straight to the GPU.
//!
//! Nothing here blocks on the main thread: the browser forbids `Atomics.wait` there, so the
//! hand-off is a single atomic swap and stats are plain atomic counters.

use std::sync::atomic::{AtomicU32, Ordering};

use wasm_bindgen::prelude::*;

mod physics;
mod pose;

pub use pose::{BONES, INSTANCES};

/// Re-exports for the native reference benchmark (`examples/tick_bench.rs`).
pub mod bench_support {
    pub use crate::physics::{ARENA_SEED, Arena};
    pub use crate::pose::{Rig, Root};
}

/// Floats per pose slot: one column-major 4x4 matrix per bone per instance.
pub const SLOT_FLOATS: usize = INSTANCES * BONES * 16;
/// Fixed simulation rate.
pub const TICK_HZ: f64 = 60.0;

/// Histogram bins per series in the stats block.
pub const HIST_BINS: usize = 256;
/// Bin width (microseconds) for the work-time histograms.
pub const WORK_BIN_US: f64 = 20.0;
/// Bin width (microseconds) for the tick-interval histogram.
pub const INTERVAL_BIN_US: f64 = 100.0;

/// Indices into the `u32` stats block. Mirrored in `web/src/sim.ts`.
pub mod stat {
    pub const TICKS: usize = 0;
    pub const RESYNCS: usize = 1;
    pub const CATCHUP_TICKS: usize = 2;
    pub const WORKER_STARTED: usize = 3;
    pub const LAST_TICK_US: usize = 4;
    pub const LAST_PHYS_US: usize = 5;
    pub const LAST_POSE_US: usize = 6;
    pub const PUBLISHED: usize = 7;
    pub const AWAKE_BODIES: usize = 8;
    pub const HIST_BASE: usize = 16;
    pub const HIST_TICK: usize = HIST_BASE;
    pub const HIST_PHYS: usize = HIST_BASE + super::HIST_BINS;
    pub const HIST_POSE: usize = HIST_BASE + 2 * super::HIST_BINS;
    pub const HIST_INTERVAL: usize = HIST_BASE + 3 * super::HIST_BINS;
    pub const LEN: usize = HIST_BASE + 4 * super::HIST_BINS;
}

const DIRTY: u32 = 4;
const INDEX_MASK: u32 = 3;

/// State shared between the main thread (reader) and the simulation worker (writer).
#[repr(C)]
pub struct Shared {
    /// Triple-buffer hand-off: low two bits = index of the newest complete slot, bit 2 = unread.
    middle: AtomicU32,
    /// Slot currently owned by the reader (main thread only, atomic so the struct is `Sync`).
    front: AtomicU32,
    /// Non-zero asks the worker loop to exit.
    stop: AtomicU32,
    slots: [*mut f32; 3],
    stats: Box<[AtomicU32]>,
}

// SAFETY: slots are disjoint per owner by the triple-buffer protocol; everything else is atomic.
unsafe impl Sync for Shared {}
unsafe impl Send for Shared {}

impl Shared {
    fn new() -> Self {
        let alloc_slot = || {
            let mut v = vec![0.0f32; SLOT_FLOATS].into_boxed_slice();
            let p = v.as_mut_ptr();
            std::mem::forget(v);
            p
        };
        let slots = [alloc_slot(), alloc_slot(), alloc_slot()];
        let stats = (0..stat::LEN).map(|_| AtomicU32::new(0)).collect::<Vec<_>>();
        Shared {
            // Writer starts on slot 2, reader on slot 0, slot 1 is the middle.
            middle: AtomicU32::new(1),
            front: AtomicU32::new(0),
            stop: AtomicU32::new(0),
            slots,
            stats: stats.into_boxed_slice(),
        }
    }

    fn bump(&self, i: usize, by: u32) {
        self.stats[i].fetch_add(by, Ordering::Relaxed);
    }

    fn set(&self, i: usize, v: u32) {
        self.stats[i].store(v, Ordering::Relaxed);
    }

    fn hist(&self, base: usize, value_us: f64, bin_us: f64) {
        let bin = ((value_us / bin_us) as usize).min(HIST_BINS - 1);
        self.bump(base + bin, 1);
    }
}

fn shared<'a>(addr: u32) -> &'a Shared {
    // SAFETY: `addr` comes from `create_shared`, which leaks the allocation for the page lifetime.
    unsafe { &*(addr as usize as *const Shared) }
}

#[wasm_bindgen]
extern "C" {
    /// `performance.now()` exists on both `Window` and `WorkerGlobalScope`.
    #[wasm_bindgen(js_namespace = performance, js_name = now)]
    fn perf_now() -> f64;
}

/// Allocates the shared block (main thread, once). Returns its address in linear memory.
#[wasm_bindgen]
pub fn create_shared() -> u32 {
    Box::leak(Box::new(Shared::new())) as *const Shared as usize as u32
}

/// Main thread, once per frame: takes the newest published slot if there is one and returns the
/// byte offset of the slot the reader now owns. Never blocks.
#[wasm_bindgen]
pub fn acquire_pose(addr: u32) -> u32 {
    let s = shared(addr);
    if s.middle.load(Ordering::Acquire) & DIRTY != 0 {
        let front = s.front.load(Ordering::Relaxed);
        let prev = s.middle.swap(front, Ordering::AcqRel);
        s.front.store(prev & INDEX_MASK, Ordering::Relaxed);
    }
    s.slots[s.front.load(Ordering::Relaxed) as usize] as usize as u32
}

/// Byte offset of the `u32` stats block (layout in [`stat`]).
#[wasm_bindgen]
pub fn stats_ptr(addr: u32) -> u32 {
    shared(addr).stats.as_ptr() as usize as u32
}

#[wasm_bindgen]
pub fn stop_sim(addr: u32) {
    shared(addr).stop.store(1, Ordering::Release);
}

#[wasm_bindgen]
pub fn slot_floats() -> u32 {
    SLOT_FLOATS as u32
}

#[wasm_bindgen]
pub fn instance_count() -> u32 {
    INSTANCES as u32
}

#[wasm_bindgen]
pub fn bone_count() -> u32 {
    BONES as u32
}

#[wasm_bindgen]
pub fn stats_len() -> u32 {
    stat::LEN as u32
}

/// Static arena layout for the renderer: `[half_extent, pillar_half, x0, z0, x1, z1, ...]`.
#[wasm_bindgen]
pub fn arena_layout() -> Vec<f32> {
    let mut rng = physics::ARENA_SEED | 1;
    let mut out = vec![physics::HALF_EXTENT, physics::PILLAR_HALF];
    out.extend(physics::pillars(&mut rng).into_iter().flatten());
    out
}

/// `WebAssembly.Module` of this instance, posted to the worker so it does not refetch/recompile.
#[wasm_bindgen]
pub fn wasm_module() -> JsValue {
    wasm_bindgen::module()
}

/// The shared `WebAssembly.Memory`.
#[wasm_bindgen]
pub fn wasm_memory() -> JsValue {
    wasm_bindgen::memory()
}

/// True when this build has shared memory (atomics) and SIMD enabled.
#[wasm_bindgen]
pub fn build_features() -> String {
    let mut f = Vec::new();
    if cfg!(target_feature = "atomics") {
        f.push("atomics");
    }
    if cfg!(target_feature = "bulk-memory") {
        f.push("bulk-memory");
    }
    if cfg!(target_feature = "simd128") {
        f.push("simd128");
    }
    f.join(",")
}

/// Pure-compute micro benchmark (callable from any thread): `ticks` FK passes, returns ms per tick.
#[wasm_bindgen]
pub fn bench_pose(ticks: u32) -> f64 {
    let mut out = vec![0.0f32; SLOT_FLOATS];
    let roots = physics::grid_roots();
    let mut rig = pose::Rig::new();
    let t0 = perf_now();
    for i in 0..ticks {
        rig.write(&roots, i as f32 / TICK_HZ as f32, &mut out);
    }
    (perf_now() - t0) / ticks.max(1) as f64
}

/// Simulation worker entry point. Runs until [`stop_sim`]. Must not be called on the main thread
/// (it sleeps with `memory.atomic.wait32`, which the main thread may not do).
#[wasm_bindgen]
pub fn run_sim(addr: u32) {
    let s = shared(addr);
    s.set(stat::WORKER_STARTED, 1);

    let mut world = physics::Arena::new(INSTANCES, physics::ARENA_SEED);
    let mut rig = pose::Rig::new();
    let mut roots = vec![pose::Root::default(); INSTANCES];
    let mut back = 2usize;

    let dt_ms = 1000.0 / TICK_HZ;
    let mut next = perf_now();
    let mut last_start = next;
    let mut tick: u64 = 0;

    while s.stop.load(Ordering::Acquire) == 0 {
        let now = perf_now();
        if now < next {
            let wait = next - now;
            // Coarse sleep; never spin (the Air is fanless).
            std::thread::sleep(std::time::Duration::from_micros((wait * 1000.0) as u64));
            continue;
        }
        if now - next > 250.0 {
            // Far behind (tab throttled, debugger): drop the backlog instead of spiralling.
            next = now;
            s.bump(stat::RESYNCS, 1);
        } else if now - next > dt_ms {
            s.bump(stat::CATCHUP_TICKS, 1);
        }

        let t0 = perf_now();
        if tick > 0 {
            s.hist(stat::HIST_INTERVAL, (t0 - last_start) * 1000.0, INTERVAL_BIN_US);
        }
        last_start = t0;

        world.step(tick);
        world.roots(&mut roots);
        let t1 = perf_now();

        // SAFETY: the writer exclusively owns `back` until it is published below.
        let slot = unsafe { std::slice::from_raw_parts_mut(s.slots[back], SLOT_FLOATS) };
        rig.write(&roots, (tick as f64 / TICK_HZ) as f32, slot);
        let prev = s.middle.swap(back as u32 | DIRTY, Ordering::AcqRel);
        back = (prev & INDEX_MASK) as usize;
        let t2 = perf_now();

        let phys_us = (t1 - t0) * 1000.0;
        let pose_us = (t2 - t1) * 1000.0;
        let tick_us = (t2 - t0) * 1000.0;
        s.hist(stat::HIST_PHYS, phys_us, WORK_BIN_US);
        s.hist(stat::HIST_POSE, pose_us, WORK_BIN_US);
        s.hist(stat::HIST_TICK, tick_us, WORK_BIN_US);
        s.set(stat::LAST_PHYS_US, phys_us as u32);
        s.set(stat::LAST_POSE_US, pose_us as u32);
        s.set(stat::LAST_TICK_US, tick_us as u32);
        s.set(stat::AWAKE_BODIES, world.awake() as u32);
        s.bump(stat::PUBLISHED, 1);
        s.bump(stat::TICKS, 1);

        tick += 1;
        next += dt_ms;
    }
}
