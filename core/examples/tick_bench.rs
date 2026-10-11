//! Native reference for the per-tick cost measured in the browser (single thread).
//!
//!   cargo run -j3 --release -p game-core --example tick_bench
use std::time::Instant;

use game_core::{SLOT_FLOATS, TICK_HZ, bench_support::*};

fn pct(v: &mut [f64], p: f64) -> f64 {
    v.sort_by(|a, b| a.partial_cmp(b).unwrap());
    v[((v.len() as f64 * p) as usize).min(v.len() - 1)]
}

fn main() {
    let ticks = 1200;
    let mut arena = Arena::new(game_core::INSTANCES, ARENA_SEED);
    let mut rig = Rig::new();
    let mut roots = vec![Root::default(); game_core::INSTANCES];
    let mut out = vec![0.0f32; SLOT_FLOATS];
    let (mut phys, mut pose) = (Vec::new(), Vec::new());
    for t in 0..ticks {
        let t0 = Instant::now();
        arena.step(t);
        arena.roots(&mut roots);
        let t1 = Instant::now();
        rig.write(&roots, (t as f64 / TICK_HZ) as f32, &mut out);
        let t2 = Instant::now();
        phys.push((t1 - t0).as_secs_f64() * 1e3);
        pose.push((t2 - t1).as_secs_f64() * 1e3);
    }
    let skip = 120; // let the pile settle
    let (p, q) = (&mut phys[skip..], &mut pose[skip..]);
    println!("native ticks={} (after {skip} warm-up)", ticks - skip as u64);
    println!("physics ms p50 {:.3} p95 {:.3} p99 {:.3}", pct(p, 0.5), pct(p, 0.95), pct(p, 0.99));
    println!("pose    ms p50 {:.3} p95 {:.3} p99 {:.3}", pct(q, 0.5), pct(q, 0.95), pct(q, 0.99));
}
