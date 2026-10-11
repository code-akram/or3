# Spike 2: Turntable render test (Cycles CPU and headless EEVEE)

**Status: PASS.** The spike-1 GLB renders headless as a four-view turntable (front, ¾, profile, close-up) in both Cycles CPU and EEVEE.

- **EEVEE works with no display** through OpenGL 4.6 on a surfaceless EGL context. Two Mesa drivers were tested:
  - **radeonsi on the Raphael iGPU: 6.9 s per 1024² frame** at 64 samples.
  - **llvmpipe (software): 36 s per 1024² frame**.
- **Cycles CPU at 3 threads, 1024², 128 spp with adaptive sampling: 51 s per frame with OIDN, 42 s without.** One OIDN pass costs ~6 s at HIGH quality and ~1.4 s at FAST.
- **The Vulkan backend does not start.** No Vulkan ICD is installed, so Blender falls back to OpenGL.

Date: 2026-10-12. Branch: `worktree-agent-ae7709a9aedba6d2d`.

## What was done

| Item | Version |
|---|---|
| Blender | 5.2.2 LTS (Arch `blender 17:5.2.2-2`) |
| Cycles denoiser | OpenImageDenoise 2.4.1 (Arch `openimagedenoise 2.4.1-2`). Embree 4.4.1. |
| Mesa | 26.2.3 (`radeonsi`, `llvmpipe` LLVM 22.1.8, 256-bit). `vulkan-icd-loader` 1.4.357 is installed, but there is **no ICD** (`/usr/share/vulkan/icd.d/` is absent). |
| Input | `data/build/character/character.glb` from spike 1 (50.2k tris, 10 PNG textures). Importing it takes 0.15–0.29 s. |

**`blender/render_turntable.py`** imports the GLB, so it renders exactly what ships, and builds a neutral studio:

- dark world (0.045);
- 60 m grey floor;
- key, fill and rim area lights.

It places four cameras:

| View | Lens | Azimuth | Framing |
|---|---|---|---|
| front | 50 mm | 0° | full body |
| three_quarter | 50 mm | 40° | full body |
| profile | 50 mm | 90° | full body |
| closeup | 85 mm | 25° | 0.42 m of frame height around the `head` bone |

Each view is timed around `bpy.ops.render.render` and written to `timings.json`, which records engine, samples, OIDN settings, GPU renderer string, threads, loadavg and environment. **`blender/pose_check.py`** poses the rig (arms, elbows, knee, spine twist, head turn) to confirm that the GLB skin deforms.

**How EEVEE runs headless:** `blender -b` with no `DISPLAY` or `WAYLAND_DISPLAY`. Blender's GHOST layer creates a headless EGL context, and Mesa picks a driver:

- By default it picks **radeonsi** through `/dev/dri/renderD128`, which is world-rw. No `video` group is needed.
- `LIBGL_ALWAYS_SOFTWARE=1` forces **llvmpipe**. `LP_NUM_THREADS=3` caps its rasteriser threads, and `top` showed ~290 % CPU.
- No Xvfb, no `--gpu-backend` flag and no extra package is needed for OpenGL.

## Measured numbers

All runs used `blender -t 3`. Other Phase 0 spikes were running at the same time, and **loadavg rose from 2.2 to 10.5 during the run**. These are therefore upper bounds; rerun the bench script on an idle machine. "Mean" is over the four views.

### 1024 × 1024

| Config | Front | ¾ | Profile | Close-up | **Mean s/frame** | Warm repeat (front) | loadavg (1-min) at start → end |
|---|---|---|---|---|---|---|---|
| Cycles 128 spp, adaptive, **OIDN HIGH** | 50.6 | 51.4 | 40.4 | 61.2 | **50.9** | – | 7.9 → 10.5 |
| Cycles 128 spp, adaptive, **no denoise** | 36.1 | 36.8 | 36.8 | 58.4 | **42.0** | – | 9.4 → 10.3 |
| Cycles 32 spp, adaptive, OIDN HIGH | 17.5 | 16.8 | 18.2 | 24.9 | **19.3** | – | 5.4 → 6.0 |
| Cycles 32 spp, adaptive, OIDN FAST + fast prefilter | 13.7 | 13.8 | 11.8 | 17.1 | **14.1** | – | 7.1 → 7.3 |
| **EEVEE 64 samples, radeonsi (iGPU)** | 7.0 | 7.4 | 7.3 | 5.9 | **6.9** | 7.0 | 3.5 → 2.6 |
| **EEVEE 64 samples, llvmpipe** (`LP_NUM_THREADS=3`) | 32.4 | 40.3 | 36.1 | 35.7 | **36.1** | 36.4 | 2.2 → 6.3 |
| EEVEE 64, `--gpu-backend vulkan` → **fell back to OpenGL/radeonsi** | 7.7 | 8.1 | 7.8 | 6.2 | 7.4 | 7.6 | 6.6 → 5.9 |

### OIDN cost in isolation

Measured at 1 spp, front view only, 1024². Denoise-on time minus denoise-off time; each run twice, loadavg ≈ 8–9.

| Denoise setting | s/frame | OIDN cost |
|---|---|---|
| off | 1.67, 1.68 | – |
| OIDN HIGH, prefilter ACCURATE (Blender default) | 7.72, 7.67 | **≈ 6.0 s** |
| OIDN BALANCED, prefilter ACCURATE | 4.81, 4.80 | ≈ 3.1 s |
| OIDN FAST, prefilter FAST | 3.09, 3.11 | **≈ 1.4 s** |

### 512 × 512: look-dev loop settings

| Config | Front | ¾ | Profile | Close-up | **Mean** | loadavg (1-min) at start |
|---|---|---|---|---|---|---|
| EEVEE 16 samples, radeonsi | 1.21 | 1.07 | 1.07 | 0.98 | **1.1** | 5.7 |
| EEVEE 16 samples, llvmpipe | 4.65 | 6.30 | 6.16 | 6.87 | **6.0** | 5.7 |
| Cycles 32 spp, OIDN FAST | 3.40 | 3.38 | 2.99 | 4.32 | **3.5** | 6.3 |

**Observations**

- EEVEE "warm" repeats of the front view are as slow as the first frame. Shader compilation is not a noticeable share at these settings; the cost is per-sample rendering.
- The Cycles close-up is the slowest view. Hair (alpha-MASK cards) fills the frame there, which means many transparent bounces.
- The llvmpipe result at 512² / 16 samples (6 s) matches the "~6 s per small frame" figure quoted in NOTES §7.
- On this CPU, at 3 threads, **Cycles 32 spp + FAST OIDN (3.5 s) beats llvmpipe EEVEE (6 s)** for a 512² look-dev frame.

### Committed images (`bench/m0/renders/`, all < 300 KB)

Our own renders of the CC0-derived character:

- `cycles128_oidn_{front,three_quarter,profile,closeup}.png`: the reference turntable. 1024² Cycles 128 spp + OIDN, downscaled to 512².
- `compare_closeup_crops.png`: a 1:1 232 px crop around the eyes from the same close-up frame in six configs.
  - Top row: Cycles 128 + OIDN, Cycles 128 raw, Cycles 32 + OIDN.
  - Bottom row: EEVEE radeonsi, EEVEE llvmpipe, Cycles 32 + FAST OIDN.
  - At this simple studio setup, all six are close. Cycles 128 raw shows mild grain on the skin. FAST OIDN is visually equivalent to HIGH here.
- `pose_check.png`: the skinning stress pose in EEVEE. Suit, body, hair and shoes all follow the `game_engine` rig. The jacket hem flares at the raised thigh, which is the expected case for the planned helper bones and Dem Bones work.

## Commands to reproduce

```sh
# full set (1024², 3 threads); outputs in $DATA/build/renders/<config>/{*.png,timings.json}
DATA=/home/akram/code/or3/data bench/m0/bench_spike2_render.sh 3 1024 \
  eevee_radeonsi eevee_llvmpipe eevee_vulkan cycles32_oidn cycles128_oidn cycles128_raw cycles32_oidn_fast
# OIDN cost isolation
DATA=/home/akram/code/or3/data bench/m0/bench_spike2_render.sh 3 1024 \
  cycles1_raw cycles1_oidn cycles1_oidn_balanced cycles1_oidn_fast
# look-dev loop settings at 512²
SUFFIX=_512 DATA=/home/akram/code/or3/data bench/m0/bench_spike2_render.sh 3 512 \
  eevee16_radeonsi eevee16_llvmpipe cycles32_oidn_fast
# skin check + committed PNGs
blender -b -t 3 --factory-startup --python blender/pose_check.py -- \
  --glb /home/akram/code/or3/data/build/character/character.glb \
  --out /home/akram/code/or3/data/build/renders/pose_check/pose.png --res 640
DATA=/home/akram/code/or3/data bench/m0/make_render_sheets.sh
```

For idle-machine numbers, run the same commands when `cat /proc/loadavg` is below 1. To use the whole CPU, pass `16` as THREADS.

## Failures and workarounds

1. **`--gpu-backend vulkan` fails.** The log shows `gpu.vulkan | ERROR Unable to initialize a Vulkan 1.2 instance.` because no ICD is installed (neither `vulkan-radeon`/RADV nor `vulkan-swrast`/lavapipe). Blender 5.2 then **silently falls back to OpenGL**; `timings.json` confirms the renderer was radeonsi. EEVEE does not need Vulkan here. Installing the ICDs would only let us compare against Vulkan (see User actions).
2. **The first renders were unusable** because of two spike-1 export bugs (un-baked shape keys; all materials BLEND). Both are fixed in `build_character.py` and documented in the spike-1 report.
3. **The glTF importer adds a hidden bone-shape `Icosphere`** (2 m bounding box) that ruined auto-framing. The fix is to frame on the meshes parented to the armature only.
4. `pkill -f <pattern>` / `pgrep -f <pattern>` match the invoking shell's own command line. To stop a stray render, use `top`/PID rather than a pattern containing the script name.
5. A first render batch was aborted and moved to `data/build/renders-run0-shoes01/` when the shoe asset changed. Its radeonsi and llvmpipe numbers (6.8–7.4 s and 32–40 s) agree with the final run.

## Risks and recommendation

- **Use EEVEE on the iGPU (radeonsi) for the look-dev loop.** It takes 1.1 s at 512² / 16 samples, 6× faster than llvmpipe. It should also leave the CPU threads to the other pipelines, but CPU use during iGPU renders was not measured. NOTES §4 calls the iGPU "useless for rendering", which is **wrong for EEVEE**: it is too small for ML, but fine for raster. Keep llvmpipe as the documented fallback (6 s per 512² frame).
- **Use Cycles CPU for "oracle" and final renders and for lightmap or texture bakes.** At full machine width (16 threads) expect roughly 4–5× the 3-thread speed. That is an estimate, not measured.
- **Use FAST OIDN for iteration frames and HIGH only for sign-off frames.** HIGH costs ~6 s per 1024² frame at 3 threads.
- **Risk: iGPU EEVEE depends on `/dev/dri/renderD128` staying world-accessible and on Mesa radeonsi.** A Mesa regression would push us to llvmpipe, about 5× slower. Pinning the bench scripts lets us detect that.
- **Risk: shared-CPU noise.** All CPU numbers here were taken at loadavg 5–10 on 16 threads. They are upper bounds.
- **The look itself is not representative yet.** Skin reads pale and overexposed under the key light; the MPFB GAMEENGINE material has no SSS and no roughness map. The suit is grey pinstripe, not black. These are §7 and §10 look-dev tasks, not render-pipeline problems.

## User actions

- Optional, only to test the Vulkan backend: `sudo pacman -S vulkan-radeon vulkan-swrast`. That provides RADV for the iGPU and lavapipe. EEVEE already works through OpenGL, so this is not a blocker.
- Optional: rerun the three bench commands above on an idle machine to replace the loaded-machine numbers.

## Proposed NOTES.md updates

- §4 Build machine: replace "iGPU … is **useless for ML or rendering**" with:
  > "iGPU (Raphael, 2 CUs) is useless for ML and Cycles, but **runs EEVEE headless via Mesa radeonsi/EGL: 1.1 s per 512² look-dev frame (16 samples), 6.9 s per 1024² frame (64 samples)**. llvmpipe fallback: 6 s / 36 s."
- §4 Available: add "Mesa 26.2.3 (radeonsi, llvmpipe), no Vulkan ICD; OIDN 2.4.1, Embree 4.4.1".
- §7 Loop step 3: replace "Render on Cycles CPU, or test EEVEE via llvmpipe (~6 s per small frame reported)" with:
  > "**Loop renders: EEVEE headless on the iGPU (radeonsi), 512², 16 samples, ~1.1 s per view.** Sign-off renders: Cycles CPU 1024², 128 spp + OIDN HIGH (~51 s per view at 3 threads, loaded machine). Scripts: `blender/render_turntable.py`, `bench/m0/bench_spike2_render.sh`."
- §6 Offline pipeline: add "EEVEE headless needs no display server: `blender -b` creates a surfaceless EGL context; `LIBGL_ALWAYS_SOFTWARE=1` forces llvmpipe."
- §18 spike 2: mark it done, with a pointer to this report.
