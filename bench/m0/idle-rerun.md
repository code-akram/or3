# m0 idle reruns: 16 threads

Spike timings were first measured at 3 threads while five spikes shared the CPU. These reruns use the full machine: Ryzen 7 7700, 16 threads, run 2026-10-12 02:03–02:08 CEST.

- **Start load:** 0.17. The higher load averages during the runs come from the 16-thread renders themselves.
- **Background load:** the only other work was the spike 3 follow-up agent, capped at 2 threads and doing light work only.
- **Raw log:** `data/build/bench-idle/idle-bench.log` (gitignored).

```
bench/m0/bench_spike1_build.sh 3 16
bench/m0/bench_spike2_render.sh 16 1024
bench/m0/spike6/bake.sh 16 3
```

## Spike 1: MPFB2 character build

| Step | 3 threads, loaded | 16 threads, idle |
|---|---|---|
| Full build (enable → GLB) | ~2.2 s | **~2.0 s** (3 runs) |
| suit / stage_for_export / export_glb | 0.4 / 0.4 / 0.4 s | 0.42 / 0.41 / 0.39 s |

The build is effectively single-threaded, so extra threads change nothing. Output is identical: 50,170 tris, glTF-Validator reports 0 errors and 9 warnings.

## Spike 2: turntable renders, 1024², seconds per view

| Config | 3 threads, loaded | 16 threads, idle: front / ¾ / profile / close-up |
|---|---|---|
| Cycles CPU, 128 spp, OIDN | ~51 | **12.5 / 13.1 / 12.9 / 18.0** |
| Cycles CPU, 128 spp, no denoise | ~42 | **10.5 / 11.0 / 10.8 / 15.7** |
| Cycles CPU, 32 spp, OIDN fast | ~14 | **7.0 / 6.9 / 6.7 / 8.2** |
| EEVEE, iGPU (radeonsi) | 6.9 | **7.0 / 7.4 / 7.3 / 5.9** (GPU-bound; threads don't matter) |
| EEVEE, llvmpipe | 36 | **12.4 / 15.6 / 15.8 / 14.8** |

**Takeaways:**
- On the full CPU, Cycles is 3.5–4× faster: a sign-off set of 4 views at 128 spp + OIDN takes about 56 s.
- EEVEE on the iGPU stays the cheapest option for the look-dev loop: 512² at 16 samples ≈ 1.1 s per view (spike 2).
- With the full CPU, llvmpipe is now within about 2× of the iGPU.

## Spike 6: Steam Audio alley IR

| Metric | 3 threads, loaded | 16 threads, idle |
|---|---|---|
| `run_reflections` (262k rays, 64 bounces) | ~0.6 s | **0.13 s** |
| End to end (load, alley search, bake, calibrate) | 2.2 s | **1.6 s** (dominated by a 1.36 s single-threaded alley search) |

The acoustics are stable across the three runs: EDT 0.20 s, T20 0.34–0.37 s, DRR −7.9 dB.

## Not rerun here
- **Spike 3 (GVHMR):** the follow-up agent measures it at 8 and 16 threads once this rerun finishes. See `spike-3-gvhmr.md`.
- **Spike 4:** frame numbers only matter on the M4 Air. The native sim tick has no thread knob.
- **Spike 5:** the chunk cut takes 0.2 s and meshopt 0.5 s, too small to matter.
- **Spike 7:** the full rebuild takes 122 s. It runs mostly as single-threaded ffmpeg stages and isn't a bottleneck.
