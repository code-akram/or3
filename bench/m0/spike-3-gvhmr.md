# Phase 0 spike 3: video to motion with GVHMR on CPU

Date: 2026-10-12. Machine: Ryzen 7 7700 (Zen 4, AVX-512 bf16), 62 GB RAM, CPU only.
The box was shared with other spikes. **Every timing in the first part uses 4 threads**, with `loadavg` recorded next to it.
The idle 8/16-thread numbers, the foot-lock rewrite and the YouTube root cause are in **Follow-up (completion)** at the end;
where they replace a first-pass number, the first-pass text says so.

**Status after the follow-up: partial.** Everything that can run on this machine is done and measured. The one remaining
blocker is footage: YouTube refuses this machine's datacenter IP, so the Lionsgate Movies featurettes need one user step
(export cookies, `scp`, run `fetch-youtube.sh`).

## Summary

- **It runs on CPU with zero patches.**
  - The full pipeline ran end to end: shot split, YOLO + BoT-SORT, ViTPose-H, HMR2 ViT-H features, SimpleVO, GVHMR, then QC, cleanup and npz/BVH export.
  - It uses the `ryanrudes/gvhmr` fork, which is device-agnostic, plus a 3-line external `torch.autocast("cpu", bfloat16)` wrapper.
- **Throughput at 4 threads** (first pass):
  - As shipped (fp32): **2.5 s per frame**.
  - With bf16 autocast on the two ViT-H stages: **0.99 s per frame** for the whole pipeline. That is 2.8× faster on the ViTs, with no measurable quality change: 1.2 mm root-aligned MPJPE between the fp32 and bf16 runs.
  - Correction from the follow-up: ultralytics silently resets torch to 8 threads, so YOLO ran on 8 threads in every first-pass run. True 4-thread YOLO is 0.31 s/frame, so a true 4-thread bf16 total is about 1.12 s/frame.
- **Measured on the idle machine, 60 min of footage (108k frames at 30 fps)** (follow-up; replaces the first pass's extrapolation):
  - fp32 as shipped, best single process (8 threads): **1.155 s/frame, about 35 h**.
  - bf16 ViTs, accuracy-neutral: 1 × 8 threads **0.66–0.68 s/frame, about 20 h**; best schedule 4 processes × 4 threads **0.593 s/frame, about 17.8 h**.
  - 16 threads gives nothing over 8 (SMT): bf16 1 × 16 is 0.727 s/frame including model loads.
  - Derived from measured stage costs: skipping duplicated frames gives about 15 h; also turning ViTPose flip-test off (accuracy trade) gives about 12 h; also running YOLO at source fps gives about 11 h.
  - NOTES §8 said 22 h naive and 8–12 h optimised. Measured naive is 1.6× worse (35 h). 8–12 h needs both the flip-test-off accuracy trade and source-fps YOLO.
- **Quality**:
  - **Clean, lit, full-body walks**: plausible, usable motion. The 2D fit is good (8.7 px median reprojection on 576×1024). Jitter is high raw and drops about 82% with zero-phase One Euro.
  - **The Sacré-Cœur stair tumble** (NOTES target #1) is **unusable**. YOLOv8x, YOLO26x and YOLO11x all lose the tumbling, dark, motion-blurred body. The protagonist's track covers 4–12% of frames, so GVHMR is fed garbage boxes.
- **Foot contact (follow-up)**: the root-level lock is replaced by contact detection plus analytic two-bone leg IK.
  - Pivot slide on contact frames: walk 23.7 → **2.5 cm/s**, Osaka 4.0 → **1.3 cm/s**.
  - Travel kept: **99.4–99.5 %** of the path, and 100 % of net displacement. The first version kept 83–91 %.
  - No new knee pops on the walks. Jitter stays at the One Euro level: Osaka 33 → 40 m/s³, against 208 raw.
- **Biggest blocker: footage access.**
  - YouTube answers every client from this machine with "Sign in to confirm you're not a bot", so the Lionsgate Movies YouTube featurettes and clips could not be fetched.
  - **Root cause** (follow-up): both public addresses are Hetzner datacenter ranges (AS24940), IPv4 and IPv6 alike. The current yt-dlp nightly, every documented player client, `-4`/`-6` and the recommended PO-token provider all still hit the wall. yt-dlp's documentation says this needs cookies.
  - The only official source that worked is **Lionsgate UK's TikTok**. Those are 576×1024 vertical re-frames with captions and fast cuts: low resolution, unknown crop intrinsics and few long clean shots.
  - The user needs to supply YouTube cookies once (see User actions). `pipeline/video-to-motion/fetch-youtube.sh` does the rest.

## What was done

### Code base choice: `ryanrudes/gvhmr` fork, not upstream

| | upstream `zju3dv/GVHMR` | fork `ryanrudes/gvhmr` (used) |
|---|---|---|
| Commit | `ee960bb6e2ea2d381aa97f08e9b71ef320b624b1` (cloned for reference only) | `e3876097a9c4d9c1758d058d9e70c64f0cdba4c4` (main, v1.6.1+) |
| CPU | 87 hard-coded `.cuda()` / `"cuda"` sites; needs a pytorch3d build (cu121 wheel only) | `get_device()` everywhere; moderngl renderer; runs on CPU as is |
| Python | 3.10, torch 2.3 cu121 | **≥ 3.11** (uses `tomllib`) |
| SMPL `.pkl` (chumpy) | needs a patched chumpy | ships `_smpl_compat` shims (`inspect.getargspec`, `np.bool`…) for numpy 2 |
| Patches we needed | many | **none**. bf16 is an external autocast wrapper in our bench script, and no diff file was needed |
| Licence | ZJU non-profit; derivatives open-source; no commercial use | **same `LICENSE` file** (its `pyproject` classifier says MIT, which contradicts the `LICENSE` file; treat it as the ZJU licence) |

**Deviation from the brief: Python 3.11 instead of 3.10.** The fork's floor is 3.11. The 3.10 rule exists to keep research code off the system Python 3.14, and that holds: the env is a uv venv with python-build-standalone 3.11.16 under `private/src/gvhmr-rudes/.venv`.

### Environment (exact versions)

- Python 3.11.16 (uv).
- torch **2.12.1+cpu** (MKL 2024.2, oneDNN 3.11.2, AVX512) and torchvision 0.27.1+cpu.
- numpy 2.4.6, ultralytics 8.4.75, pycolmap 4.0.4, timm 1.0.27, pytorch-lightning 2.6.5, hydra-core 1.3.3, smplx 0.1.28, **chumpy 0.70**, scipy 1.17.1.
- scenedetect 0.7.1, transnetv2-pytorch 1.0.5, openvino 2026.4.1 (with `openvino-telemetry` uninstalled).
- Install: `uv sync --python 3.11 --frozen --extra cpu --extra preproc` from the fork's lock. `pipeline/video-to-motion/setup-gvhmr.sh` reproduces it.

### Body models

- Symlinked: `private/models/gvhmr/body_models/{smpl,smplx}` → `private/body-models/{smpl,smplx}`.
- The SMPL v1.1.0 `.pkl` files load inside the venv only, via the fork's chumpy shims. A check gave SMPL 6890 verts and SMPL-X 10475 verts. No converted copies were needed.
- GVHMR inference itself only needs SMPL-X `.npz`. SMPL is needed only for its mesh renderer, which we did not use.

### Checkpoints and their licences

All checkpoints are in `private/models/`, with sha256 sums in `private/models/SHA256SUMS`. GVHMR's four come from the HF mirror `camenduru/GVHMR` (rev `21b32d53`), which mirrors the authors' Google Drive folder. The mirror carries no licence metadata of its own.

| File | Size | Licence | Note |
|---|---|---|---|
| `gvhmr/gvhmr_siga24_release.ckpt` | 164 MB | GVHMR (ZJU): non-profit, derivatives open-source, no commercial | trained on SMPL-X data, so the SMPL-X licence also applies in practice |
| `hmr2/epoch=10-step=25000.ckpt` | 2.7 GB | 4D-Humans code is MIT; the checkpoint is **SMPL-based** (SMPL licence, never commit) | the image feature backbone |
| `vitpose/vitpose-h-multi-coco.pth` | 2.5 GB | ViTPose: Apache-2.0 | trained on COCO + multi-dataset |
| `yolo/yolov8x.pt` | 137 MB | Ultralytics **AGPL-3.0** | offline tool use only; never shipped |
| `ultralytics/yolo26x.pt`, `yolo11x.pt` | 119 / 115 MB | AGPL-3.0 | only for the detector A/B |
| TransNetV2 weights (bundled in the wheel) | 31 MB | MIT | |

DPVO was not fetched. SimpleVO is the default, and DPVO is CUDA-only.

### Footage (official Lionsgate only, all under `private/footage/`)

- **YouTube (Lionsgate Movies, `UCJ6nMHaJPZvsJ-HmUmj1SeA`) is blocked**:
  - Clips tried: JW4 'Osaka Continental', 'New Challenges', the Sacré-Cœur stair loop, among others.
  - Every player client (`default`, `tv`, `web_safari`, `android_vr`, `mweb`, `ios`, …) returns "Sign in to confirm you're not a bot".
  - The same happens with the latest `yt-dlp[default]` via uvx.
  - It is IP-level, so it needs cookies.
- IMDb's video gallery is behind an AWS WAF challenge.
- **Lionsgate UK TikTok (`@lionsgateuk`) works without auth.** All clips are 576×1024 vertical, 23.976 fps. The clips used:

| Clip (in `private/footage/clips/`) | Source | Frames | Content |
|---|---|---|---|
| `jw4-wintry-walk.mp4` | https://www.tiktok.com/@lionsgateuk/video/7211197898581708038 (Lionsgate UK, 2023-03-16), source frames 199–273 | 75 (3.1 s) | **Wick**, profile walk, full body, tracking camera, daylight |
| `jw4-osaka-shimazu-walk.mp4` | https://www.tiktok.com/@lionsgateuk/video/7408560151441067297 (Lionsgate UK), frames 127–250 | 124 (5.2 s) | Shimazu (not Wick), clean full-body walk, long coat, neon. **Used as a quality probe only.** |
| `jw4-sacrecoeur-wide.mp4` | https://www.tiktok.com/@lionsgateuk/video/7463173066575711521 (Lionsgate UK, 2025-01-23), frames 371–753 (h265 rendition `bytevc1_540p`) | 383 (16 s) | Sacré-Cœur stair **tumble** (wide, moving camera, night) |
| `jw4-sacrecoeur-tumble.mp4` | same source, frames 398–753 (drops a cut TransNetV2 missed) | 356 | same; used for the detector A/B |

### Pipeline (CPU, 4 threads)

1. **Shot split.** `shots.py` runs TransNetV2 and PySceneDetect `AdaptiveDetector`, and adds per-shot median luma and Laplacian-variance blur.
2. **Staging.** The fork resamples 23.976 → 30 fps by nearest frame, which duplicates every 4th frame.
3. **Tracking.** YOLOv8x + BoT-SORT, conf 0.5. The protagonist is GVHMR's default "top area-sum track". Our optional `--stitch` chains fragments by box continuity.
4. **Pose and features.** One shared decode and 256² crop, then ViTPose-H with flip-test (as released), then HMR2 ViT-H features, then SimpleVO (rotation only), then the GVHMR network.
5. **QC and cleanup.** `motion_qc.py` does SMPL-X FK (22 body joints, y-up world), computes the metrics, applies cleanup and exports npz + BVH.

## Measured numbers

### Seconds per frame by stage (frames = 30 fps staged frames; 4 threads)

| Stage | fp32 as shipped (walk, 94 f) | fp32 (Sacré-Cœur, 479 f) | **bf16 ViTs** (Osaka, 155 f) | bf16 ViTs (Sacré-Cœur, 479 f) | idle micro-bench, 64 real crops, 1 pass |
|---|---|---|---|---|---|
| shot split, TransNetV2 / PySceneDetect | | 0.006 / 0.0003 (whole 64 s TikTok) | | | |
| stage to 30 fps | 0.011 | 0.005 | 0.005 | 0.004 | |
| YOLOv8x + BoT-SORT | 0.245 | 0.317 | **0.181** | reused | idle: 0.176 (yolo26x 0.160) |
| decode + crop | 0.002 | 0.002 | 0.001 | 0.002 | |
| ViTPose-H (flip-test = 2 passes) | 1.494 | 1.577 | **0.529** | 0.530 | 1 pass: fp32 0.691, bf16 0.263, OV f32 0.460, OV bf16 0.223 |
| HMR2 ViT-H features | 0.733 | 0.757 | **0.261** | 0.260 | fp32 0.688, bf16 0.261, OV f32 0.460, OV bf16 0.223 |
| SimpleVO | 0.006 | 0.004 | 0.009 | 0.004 | |
| GVHMR network | 0.001 | 0.0005 | 0.0007 | 0.0005 | |
| **Total** | **2.49** | **2.66** | **0.99** | 0.80 + YOLO | |
| loadavg (1 min) during the run | 2.3–6.5 | 5.0–14.6 | 2.2–4.0 | 3.5–4.1 | 0.1–3.8 |

How to read the table:

- The two ViT-H stages take **89% of the time in fp32** and **80% in bf16**. In bf16, YOLO becomes 18%.
- **Correction (follow-up):** every YOLO figure in this table actually ran on **8** threads, because ultralytics resets torch's thread count. Measured 4-thread YOLO is 0.309 s/frame.
- The fp32 Sacré-Cœur run overlapped heavy load from other spikes (loadavg up to 14.6). The idle micro-bench gives about 0.69 s per pass, so the true idle fp32 total is about 2.3 s per frame.
- Thread scaling, HMR2 on 32 frames, 1 / 2 / 4 threads:
  - bf16: 0.934 / 0.489 / 0.261 s per frame, which is near-linear (3.6× at 4 threads).
  - fp32: 1.845 / 0.978 / 0.683 s per frame (2.7× at 4 threads).
- bf16 and OpenVINO effect on quality:

| Variant | ViTPose-H, mean heatmap argmax shift (share of joints moving more than 1 heatmap px; 1 heatmap px = 4 crop px) | HMR2 feature cosine to fp32 (mean / min) |
|---|---|---|
| torch bf16 | 0.20 px (2.9%) | 0.9993 / 0.992 |
| OpenVINO bf16 | 0.20 px (3.0%) | 0.9994 / 0.993 |
| OpenVINO f32 | exact | exact |

- **End-to-end bf16 vs fp32 on the walk**:
  - Root-aligned MPJPE: **1.2 mm** mean, 6.5 mm p99.
  - World MPJPE: 6.4 mm mean.
  - Jitter: 498 vs 494 m/s³.
  - Foot skate: 20.2 vs 19.3 cm/s.
- **OpenVINO** (2026.4.1, `convert_model` from torch, about 56 s per model):
  - f32 is 1.5× faster than torch fp32.
  - bf16 is only about 15% faster than torch bf16 autocast.
  - Not worth the extra conversion step yet.

### Motion quality (world frame, 30 fps; `private/motion/<run>/qc.json`)

| | Wick walk (fp32) | Shimazu walk (bf16) | Sacré-Cœur tumble (fp32) |
|---|---|---|---|
| frames | 94 | 155 | 479 |
| protagonist track coverage (frames with a real detection) | 92.6% (2 IDs) | 100% (1 ID) | **4.4%** (9 IDs; only 206/479 frames have any person at conf 0.5) |
| ViTPose mean confidence / share of joints > 0.5 | 0.77 / 96% | 0.79 / 97% | 0.52 / 53% |
| reprojection of GVHMR in-cam joints vs ViTPose, median | 25 px | **8.7 px** | 59 px |
| jitter, mean \|jerk\| raw → clean (m/s³) | 494 → 85 (**−83%**) | 208 → 40 (**−81%**) | 3431 → 851 (−75%) |
| acceleration raw → clean (m/s²) | 10.4 → 3.0 | 4.8 → 1.8 | 70 → 24 |
| foot skate in contact, raw → clean (cm/s) | 19.3 → 12.0 (−38%) | 6.7 → 8.9 (**+34%, worse**) | 28 → 21 |
| joint angular speed p99 raw → clean (°/s) | 273 → 146 | 209 → 115 | 713 → 439 |
| frames with any joint > 1000 °/s | 0 | 0 | 38 |
| root speed raw / after foot lock (m/s) | 0.81 / 0.72 | 0.51 / 0.43 | n/a |

Cleanup used here:

- Zero-phase One Euro (forward and backward average): min cutoff 1.5 Hz, β 0.3, on quaternion-continuous joint rotations and on root translation.
- A root-level foot lock, which integrates and cancels the planted foot's horizontal slide. **Replaced in the follow-up** by contact-aware two-bone leg IK; the skate and root-speed rows above are from the old lock. See "Follow-up → 3".
- A global floor clamp.
- Contacts use a relative-height + velocity rule, so stairs need no floor assumption.

Other experiments:

- **Retiming** (undo the 24 → 30 fps duplication, slerp back to 30 fps) changed jerk by −5.5% on the walk and **+27%** on Osaka. The duplication stutter is not the main jitter source, so retiming is off by default (`--retime`).
- **Detector A/B on the tumble** (`--stitch`, conf 0.15):

| Detector | Top track coverage |
|---|---|
| YOLOv8x | 3.1% |
| YOLO26x | 11.7% |

  Stitching found no continuous chain to join. The detector simply does not fire on the inverted, blurred, dark body.

### Visual check

All of this stays in `private/work/vis/<run>/` and is never committed:

- `overlay_2d.mp4`: ViTPose in green and GVHMR's in-cam joints reprojected in magenta, on the staged frames.
- `stick_world.mp4`: world stick figures, raw and clean side by side, with the root trail.
- `qc_plot.png`: ankle heights with contact bands, jerk over time, and the root path.

What they show:

- **Wick walk**:
  - The stride, arm swing and torso lean are plausible.
  - GVHMR stays left/right-consistent where ViTPose swaps arms (2 of 8 sampled frames).
  - The 25 px reprojection error is partly SMPL-vs-COCO hip and shoulder joint-definition offsets; the ViTPose arm swaps above add to it.
- **Shimazu walk**:
  - The overlay is tight.
  - There is one glitch at t = 2.2 s, where the coat-hidden legs cross. Ankle heights jump and jerk spikes to about 2000 m/s³.
  - The planted-ankle height drifts about 3 cm late in the clip.
- **Sacré-Cœur tumble**:
  - The first 33 frames are a different shot. TransNetV2 missed a hard cut at source frame 397, which PySceneDetect caught.
  - After that, the boxes are held or interpolated, and the skeleton only roughly follows the body.
  - The poses are not plausible. Unusable.

### Exports

`private/motion/<run>/` holds:

- `motion_raw.npz` / `motion_clean.npz`: SMPL-X `global_orient`, `body_pose` (63), `betas`, `transl`, 22 FK joints, joint names, parents and rest joints.
- `motion_raw.bvh` / `motion_clean.bvh`: 22-joint SMPL-X body skeleton, y-up, cm, ZYX Euler, 30 fps.
- `qc.json`.

Runs: `walk-fp32`, `walk-bf16`, `osaka-bf16`, `sc-fp32`, `sc-bf16`.

## Throughput projection: 60 min of footage at 16 threads (first pass, superseded)

> **Superseded by measurement.** See "Follow-up (completion) → 4. Idle benchmark". The two assumptions below
> did not hold. 4 → 16 threads is not 1.9×: 16 threads equals 8, and the ViTs scale 1.7× from 4 to 8.
> The 4-thread YOLO figure was really 8 threads. Measured: fp32 about 35 h, bf16 17.8–20 h. The table is
> kept only as a record of the extrapolation.

Assumptions (first pass):

- 60 min of 24 fps footage is resampled to 30 fps, giving **108,000 frames**. 20% of them are duplicates.
- 4 → 16 threads gives about **1.9×** for bf16. Only 4 more physical cores are added beyond our 4, and SMT adds little to GEMM. bf16 scaled 3.6× from 1 to 4 threads.
- fp32 scales worse, about **1.6×**.
- Running 4 processes × 4 threads should give about the same throughput and is simpler to schedule.

| Configuration | s/frame at 4 threads | h per 60 min at 4 threads | **h per 60 min at 16 threads (est.)** |
|---|---|---|---|
| fp32, as shipped | 2.3–2.5 | 69–75 | **43–47** |
| bf16 ViTs (accuracy-neutral) | 0.99 | 30 | **15–17** |
| + run the ViTs only on source frames (skip the 20% duplicates) | 0.81 | 24 | **≈ 13** |
| + ViTPose flip-test off (fork's 'fast' recipe: +2.3 mm PA-MPJPE on 3DPW) | 0.60 | 18 | **≈ 9.5** |
| + OpenVINO bf16 for both ViTs | ≈ 0.55 | ≈ 16.5 | **≈ 8.7** |

Against NOTES §8 (about 22 h naive, 8–12 h optimised):

- The naive figure is about **2× too optimistic**.
- 8–12 h is reachable only with the flip-test-off accuracy trade.
- The accuracy-neutral plan is **about 13–17 h per hour of footage**.

In practice only usable shots are processed. The detection-coverage and luma gates will reject most night and fight material before the ViTs run, so wall-clock per hour of *source* footage will be far lower.

## Commands to reproduce

```bash
cd <repo>
# one-time env + checkpoints (all under private/)
pipeline/video-to-motion/setup-gvhmr.sh
# footage (official Lionsgate UK TikTok; YouTube entries need YTDLP_EXTRA="--cookies …")
pipeline/video-to-motion/fetch-footage.sh tt-7211197898581708038 tt-7408560151441067297 tt-7463173066575711521
# shot split + filter stats
OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 private/src/gvhmr-rudes/.venv/bin/python -I \
  pipeline/video-to-motion/shots.py private/footage/tt-7463173066575711521/source.mp4 private/work/shots/sc
# cut shots
pipeline/video-to-motion/cut-shot.sh private/footage/tt-7211197898581708038/source.mp4 199 273 jw4-wintry-walk
pipeline/video-to-motion/cut-shot.sh private/footage/tt-7408560151441067297/source.mp4 127 250 jw4-osaka-shimazu-walk
pipeline/video-to-motion/cut-shot.sh private/footage/tt-7463173066575711521/source.mp4 371 753 jw4-sacrecoeur-wide
# THE bench (THREADS=16 on an idle machine; default 4)
pipeline/video-to-motion/run-bench.sh private/footage/clips/jw4-osaka-shimazu-walk.mp4 osaka-fp32 --fresh
pipeline/video-to-motion/run-bench.sh private/footage/clips/jw4-osaka-shimazu-walk.mp4 osaka-bf16 --fresh --bf16 vitpose,hmr2
# ViT backends micro-bench (torch fp32/bf16, OpenVINO f32/bf16) and thread scaling
OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 GVHMR_CHECKPOINTS=private/models/gvhmr \
  private/src/gvhmr-rudes/.venv/bin/python -I pipeline/video-to-motion/vit_backends.py private/work/runs/osaka-bf16 --openvino
pipeline/video-to-motion/thread-scaling.sh private/work/runs/osaka-bf16 1 2 4 8 16
# QC + cleanup + npz/BVH export + visual check
OMP_NUM_THREADS=4 GVHMR_CHECKPOINTS=private/models/gvhmr private/src/gvhmr-rudes/.venv/bin/python -I \
  pipeline/video-to-motion/motion_qc.py private/work/runs/osaka-bf16 \
  --motion-out private/motion/osaka-bf16 --vis-out private/work/vis/osaka-bf16
private/src/gvhmr-rudes/.venv/bin/python -I pipeline/video-to-motion/compare_runs.py private/motion/walk-fp32 private/motion/walk-bf16
```

(`<repo>` paths assume the main checkout at `/home/akram/code/or3`. The scripts take `MAIN_ROOT` to override.)

## Failures and workarounds

| Problem | Workaround |
|---|---|
| YouTube bot wall on every client | Used Lionsgate UK TikTok; YouTube needs cookies from the user |
| Upstream GVHMR is CUDA-hard-coded and needs pytorch3d | Used the `ryanrudes` fork, which works on CPU as is; Python 3.11 |
| The fork autocasts only on CUDA | Our bench wraps stages in `torch.autocast("cpu", bfloat16)`; the fork's inner `autocast("cuda", enabled=False)` guards don't block it. No source patch |
| Tracker fragments the protagonist; GVHMR keeps one ID and interpolates the rest | Added `--stitch` (chains fragments by box continuity). It fails anyway when the detector does not fire at all (the tumble) |
| TransNetV2 missed a hard cut that PySceneDetect found | Use the **union** of both detectors' cuts |
| OpenVINO could not trace HMR2 (a LightningModule) | Trace a plain `nn.Module` view (backbone + smpl_head) |
| Foot lock too crude | Measured and documented: root-level lock removes 11–17% of real travel and made skating worse on the clean Osaka walk. **Fixed in the follow-up**: contact-aware two-bone leg IK (`foot_lock.py`) |
| YOLO ignores the thread cap (follow-up) | ultralytics' `select_device()` calls `torch.set_num_threads(min(8, ncpu-1))`; `bench_gvhmr.py` now overrides `ultralytics.utils.torch_utils.NUM_THREADS` |
| `exiftool` missing (focal from metadata) | Irrelevant for web video; GVHMR falls back to its diagonal-FOV heuristic. **That heuristic is wrong for vertical crops of 2.39:1 film**, which makes the root scale suspect |

## Risks

1. **Footage access and quality (🔴).**
   - Without YouTube we only have vertical, captioned TikTok re-edits (576 px from Lionsgate UK; up to 720–960 px h264 from Lionsgate US).
   - They carry unknown crop intrinsics, so GVHMR's focal guess is wrong and root speed and depth are biased.
   - They are also few in clean shots longer than 3 s.
   - The fix is one user step (cookies). See the follow-up.
2. **Most Wick footage fails at detection, not at GVHMR (🔴).**
   - Night, motion blur, tumbles and fights defeat YOLO (v8x, 11x and 26x alike).
   - The NOTES §8 luma filter (< 40/255) would reject almost all night material anyway: Sacré-Cœur shot medians are 6–23, and the Osaka walk is 36.
   - The usable yield of identity motion per hour of footage may be low.
3. **Throughput (🟠).**
   - Measured, accuracy-neutral (bf16): 17.8 h per hour of footage with 4 processes × 4 threads, and about 15 h with duplicate-frame skipping.
   - That is acceptable only with aggressive shot gating before the ViTs.
4. **Cleanup quality (🟡, was 🟠).**
   - Raw jitter is high: 200–500 m/s³ on clean walks.
   - One Euro plus the v2 IK foot lock gives pinned feet without losing travel.
   - Coat-occluded leg crossings still glitch. That needs the glitch detector.
5. **Dependencies and licences (🟡).**
   - The fork has a single third-party maintainer, so pin the commit (see follow-up §5).
   - The GVHMR licence is non-commercial; HMR2 is SMPL-based; YOLO is AGPL.
   - All are offline only and never shipped, and §17 item 6 (SMPL-derived motion) still governs shipping.

## Recommendation

- **Adopt** GVHMR via the `ryanrudes` fork at the pinned commit, with Python 3.11 in a uv venv. Run bf16 autocast on CPU for ViTPose and HMR2 by default: 2.8× faster on those stages and quality-neutral.
- **Schedule** batch runs as 4 processes × 4 threads, with the YOLO thread fix. Never use 16 threads in one process.
- **Do not chase OpenVINO yet.** It is only about 15% over torch bf16.
- **Next optimisation:** run the ViTs (and YOLO) at source fps and reuse their outputs for the duplicated 30 fps frames (−20%).
- **Spend the effort on shot selection, not compute.** Gate shots, in this order:
  1. Union of TransNetV2 and PySceneDetect cuts.
  2. Protagonist track coverage ≥ 90%.
  3. ViTPose mean confidence ≥ 0.7.
  4. Subject height ≥ 256 px.
  5. Recalibrate the luma floor down to about 15 rather than 40.
- **Prefer** walks, stands and draws in lit or daylight shots. Treat falls and fights as out of scope for video-to-motion, as NOTES already lists them among the weak spots.
- **Get the YouTube Lionsgate featurettes** (1080p horizontal) before judging Wick-identity yield. TikTok re-edits are a poor proxy.
- **Cleanup:**
  - Done: v2 foot lock (contacts + two-bone leg IK) and edge-padded translation smoothing.
  - Still to do: a lower One Euro cutoff on the torso than on the feet, and a glitch detector (angular-speed spikes) that masks and re-infills frames.

## User actions

1. **YouTube cookies: the one remaining blocker.** This takes about 3 minutes on the Mac. The steps follow the yt-dlp wiki, "Exporting YouTube cookies".
   1. Install a cookies.txt exporter from the yt-dlp FAQ:
      - Chrome: **"Get cookies.txt LOCALLY"**.
      - Firefox: **"cookies.txt"**.
      - Allow it in private windows.
   2. Open a **new private/incognito window** and log in to YouTube. yt-dlp warns that the account can be rate-limited or banned, so a secondary account is safer.
   3. In the **same tab**, go to `https://www.youtube.com/robots.txt`. It must be the only private tab.
   4. Use the extension to export the **youtube.com** cookies (Netscape format) to `~/Downloads/youtube-cookies.txt`. Then **close the private window**, so YouTube does not rotate the session.
   5. Copy the file over with its mode, then delete the local copy:
      ```bash
      chmod 600 ~/Downloads/youtube-cookies.txt
      scp -p ~/Downloads/youtube-cookies.txt akram@<this-machine>:/home/akram/code/or3/private/youtube-cookies.txt
      ssh akram@<this-machine> chmod 600 /home/akram/code/or3/private/youtube-cookies.txt
      rm ~/Downloads/youtube-cookies.txt
      ```
   6. On this machine, run `pipeline/video-to-motion/fetch-youtube.sh`. It:
      - checks the mode (600) and the format without printing the file;
      - installs the current yt-dlp nightly into `private/tools/yt-dlp`;
      - fetches every `yt-*` entry, writing no `info.json`, because those would contain cookie values.

   Alternatively, decide that TikTok-only is acceptable for now.
2. **Rule on IGN-hosted studio featurettes.** The behind-the-scenes Sacré-Cœur stair clip (NOTES §8 target 1) is an **IGN exclusive** (`youtube.com/watch?v=fdNkGq4kroQ`, also on IGN's Facebook). It is studio-supplied but not uploaded by the studio, so it is not in the fetch list until you say it counts as official.
3. Confirm the Python 3.11 deviation and the use of the third-party fork (follow-up §5 has the recommendation).
4. No `sudo pacman` was needed for this spike. OpenVINO came in as a pip wheel inside the venv.

## Proposed NOTES.md updates

- **§4 (build machine):** "Research codebases need Python 3.10 envs via uv" becomes "Research codebases run in **uv-managed Python envs at the version their lockfile requires (3.10 or 3.11)**. Never use the system Python."
- **§6:** add "GVHMR uses the `ryanrudes/gvhmr` fork (CPU-native, Python ≥ 3.11) at commit `e3876097`, installed `--frozen` from its `uv.lock`."
- **§8 Video → motion, footage source:**
  - Add: "This machine's IPs are Hetzner datacenter ranges. YouTube answers with 'confirm you're not a bot' regardless of client, IP family or PO token, so fetching needs user cookies (`private/youtube-cookies.txt`, via `fetch-youtube.sh`)."
  - Add: "Lionsgate UK and US TikTok download without auth, but give vertical re-edits (576–960 px) with captions. Use them only as a fallback."
- **§8 pipeline:**
  - "TransNetV2 shot split (PySceneDetect as cross-check)" becomes "**union** of TransNetV2 and PySceneDetect cuts (TransNetV2 missed a hard cut in testing)".
  - Filter: replace "median luma < ~40/255" with "median luma < ~15/255" (night Wick footage measures 6–36). Add "protagonist track coverage < 90%" and "ViTPose mean confidence < 0.7".
  - GVHMR line: "bf16 autocast on CPU for ViTPose/HMR2 (measured 2.8×, 1.2 mm MPJPE change). OpenVINO measured at only +15% over that."
  - Cleanup: "foot-contact lock" becomes "contact detection (height + speed, hysteresis, min duration) + **two-bone leg IK** pinning heel then ball; root horizontal untouched (measured: pivot slide 1.3–2.5 cm/s, ≥ 99.4 % travel kept)".
- **§8 throughput line:** replace with "**Measured (Phase 0, idle, 30 fps frames):**
  - fp32 as shipped: 1.155 s/frame on 8 threads, about 35 h per 60 min.
  - bf16 ViTs: 0.66 s/frame on 1 × 8 threads (about 20 h), or 0.593 s/frame aggregate on **4 processes × 4 threads (about 17.8 h)**. 16 threads gives nothing over 8.
  - About 15 h when skipping duplicated frames, about 11–12 h with ViTPose flip-test off and source-fps YOLO.
  - ViTs are about 72% of bf16 time; YOLO is about 28%."
- **§8 weak spots:** add "dark / motion-blurred / inverted bodies, where the person detector fails (YOLOv8x/11x/26x all under 12% coverage on the Sacré-Cœur tumble)" and "long coats hiding crossing legs".
- **§8 extraction targets:**
  - Demote the "Sacré-Cœur stairs (wide shots)" tumble. The usable stair content is the climbing and walking shots, not the fall.
  - Note that the behind-the-scenes stair clip is an IGN exclusive, pending the user's ruling on "official".
- **§14:** record the offline-only tool licences: YOLO weights are AGPL-3.0, the HMR2 checkpoint is SMPL-based, ViTPose is Apache-2.0, and GVHMR is non-commercial (the fork's `pyproject` "MIT" classifier contradicts its `LICENSE` file).
- **§16 risks:**
  - Update the "GVHMR CPU throughput / quality" row with the numbers above.
  - Add "footage access (YouTube bot wall from a datacenter IP; one cookie export fixes it)", rated 🔴 until the cookies land.
  - Add "detector failure on night/action shots, so low usable yield", rated 🔴.
  - Add "third-party GVHMR fork", rated 🟡, mitigated by the pin plus a source archive.
- **§18 item 3:** change "uv Python 3.10 env" to "uv Python 3.11 env". Mark it done except the YouTube footage, linking `bench/m0/spike-3-gvhmr.md`.

## Files

Committed under `pipeline/video-to-motion/`:

| File | Purpose |
|---|---|
| `setup-gvhmr.sh` | build the env |
| `fetch-footage.sh` | fetch the official clips (`YTDLP` / `YTDLP_EXTRA` overrides; no `info.json` when cookies are used) |
| `fetch-youtube.sh` | **follow-up:** the one-step cookie route: checks `private/youtube-cookies.txt` (mode, format, no printing), installs current yt-dlp under `private/tools/`, fetches the `yt-*` entries |
| `cut-shot.sh` | cut one shot by frame range |
| `shots.py` | shot split and filter stats |
| `run-bench.sh` + `bench_gvhmr.py` | the reproducible per-stage bench, plus protagonist stitching, the bf16 wrapper and (follow-up) the YOLO thread-cap fix |
| `idle-bench.sh`, `concurrency-bench.sh` | **follow-up:** idle 16/8-thread benches and N × T concurrent schedules |
| `vit_backends.py`, `thread-scaling.sh` | ViT backends micro-bench and thread scaling |
| `motion_qc.py` | metrics, cleanup, npz/BVH export and visual check; v2 foot lock by default (`--foot-lock root` for the old one) |
| `foot_lock.py` | **follow-up:** contact detection, two-bone leg IK foot lock, and the slide / travel / knee-pop metrics |
| `foot_lock_table.py` | **follow-up:** the foot-lock A/B table from `qc.json` |
| `compare_runs.py` | fp32 vs bf16 comparison |

No patch diff is needed; the fork runs unmodified.

---

## Follow-up (completion)

Date: 2026-10-12, a second pass, run unattended. The first pass was partial on three counts:

- no YouTube footage;
- 16-thread numbers that were extrapolated, not measured;
- a foot lock that lost travel.

This pass root-causes the first, measures the second and replaces the third. **Status: partial.** The only remaining
blocker is YouTube, which now needs one user step (User actions 1). Everything else is measured.

### 1. YouTube block: root cause

| Check | Result |
|---|---|
| Public IPv4 | `213.239.205.88`, **AS24940 Hetzner Online GmbH**, Falkenstein DC (`static.….clients.your-server.de`): a hosting / datacenter range |
| Public IPv6 | `2a01:4f8:222:9a0::2`, inside Hetzner's `2a01:4f8::/32`, so the same ASN |
| yt-dlp age | system `2026.08.19` (pacman, about 8 weeks old); latest nightly `2026.10.10.233141` installed in a throwaway uv venv with `yt-dlp[default,curl-cffi]` (includes `yt-dlp-ejs`; deno 2.9 present for JS challenges) |
| Player clients (`--extractor-args youtube:player_client=…`) | `default`, `tv`, `web_safari`, `android_vr`, `mweb`, `ios`, `web_embedded`, `tv_simply`, `web_creator`: **all "Sign in to confirm you're not a bot", on both `-4` and `-6`**, nightly and stable |
| PO token (yt-dlp wiki PO-Token-Guide; recommended provider `bgutil-ytdlp-pot-provider` 2.0.2, HTTP server on Node 24, plugin via pip, `fetch_pot=always`) | Tokens **were generated** (the server logged a POT per video). The player API still returned `LOGIN_REQUIRED` on every client and both IP families |

**Root cause:** YouTube's sign-in wall keys on IP reputation. Both address families are a hosting ASN.
- The yt-dlp version and the player client make no difference.
- The provider README says a PO token "does not bypass IP-based login restrictions", which is common on datacenter IPs, and that cookies are required.
- Proxies and VPNs are out of scope by rule.

So the documented route is account cookies, now one user step: `fetch-youtube.sh`, with the export steps under User actions.
- The script was tested with a dummy file. It refuses mode 644, accepts 600, reports only counts (rows, youtube.com rows, number of login-cookie names) and runs the fetch.
- With dummy cookies, YouTube still shows the wall, as expected.

**Other official sources reachable from here:**

| Source | Result |
|---|---|
| Lionsgate UK TikTok `@lionsgateuk` | works without auth (used in the first pass) |
| **Lionsgate US TikTok `@lionsgate`** | Works without auth.<br>Listed 892 posts, 69 tagged Wick/Keanu, and pulled 14 for contact sheets.<br>Renditions: h264 576–960 px, metadata up to 1080×1920 / 1440×1080.<br>Content: mostly premiere/press footage (a real person, not the film character), meme edits, trailers letterboxed to about 576×240 inside the vertical frame, and one static-camera stunt rehearsal (Osaka escalator falls).<br>**No NOTES §8 target** (stair BTS, Osaka Wick walk/turn, Paris walks) appears in better form than the UK clips, so no new GVHMR run was worth doing |
| TikTok `@johnwickmovie` | account has no videos |
| X `@JohnWickMovie`, Instagram `@johnwickmovie` | login wall |
| Vimeo / Dailymotion `lionsgate` | old or unrelated uploads only |
| IMDb video gallery | AWS WAF challenge (first pass) |
| BTS Sacré-Cœur stair clip | It is an **IGN exclusive** (YouTube `fdNkGq4kroQ`, IGN Facebook), not a studio upload. Not fetched. It needs a user ruling and is on YouTube anyway |

### 2. New pipeline runs on NOTES §8 targets

**Not run.** No new official footage of the three targets became reachable; see above.
- The pipeline, bf16 and the QC tools are ready.
- Once the cookies land: `fetch-youtube.sh`, then `shots.py`, then `cut-shot.sh`, then `run-bench.sh … --bf16 vitpose,hmr2 --stitch`, then `motion_qc.py`.
- The three existing clips were re-run through the new cleanup (below).

### 3. Foot-contact locking v2 (`foot_lock.py`, default in `motion_qc.py`)

**Contact detection**, run on the One-Euro-smoothed motion:
- Height signal: the foot's lowest point (ankle or ball) above the lower foot this frame, so stairs need no floor.
- Speed signal: 3D speed of the foot point.
- Hysteresis: a contact starts below 5 cm and 0.30 m/s, and ends above 8 cm or 0.50 m/s.
- Gaps of ≤ 2 frames are filled, and contacts shorter than 5 frames (167 ms) are dropped.
- ViTPose ankle confidence below 0.5 relaxes the exit speed up to 2×, so occlusion noise does not break a contact.

**Locking:**
- Each contact has a **heel phase**: the ankle is pinned at its mean position while within 1.5 cm of its lowest height.
- It is followed by a **toe phase** (heel-off): the ball stays where it was at the switch, and the ankle follows the foot's own rotation about it.
- Feet keep their FK world orientation, so the heel-to-toe roll survives.
- Analytic **two-bone IK** works on the hip–knee–ankle SMPL-X chain (Holden's method):
  - It keeps the current knee plane, using the knee hinge as a tie-breaker near full extension, so the knee never swivels.
  - Soft IK starts at 98% of leg length.
  - It runs two passes against fixed targets.
- Smoothstep **blend-in / blend-out** of 6 frames. Ramps never overlap the same foot's next contact.
- Pin offsets are Gaussian-smoothed with σ = 1 frame, so stance onsets do not become velocity steps.
- **Root:** the horizontal path is untouched. The only vertical change is a max-filtered, σ = 6-frame drop where a pinned ankle would be beyond 99.5% of leg length (max 0.9–2.7 cm).
- A numpy FK identical to the SMPL-X layer is asserted at < 0.1 mm.

**Also fixed:** the zero-phase One Euro on root translation pulled the clip ends inward, costing 2% of net travel on the 3 s walk. It is now edge-padded by odd reflection.

**Measured** (`foot_lock_table.py`; every variant is scored with the **same** contact labels, which the old metric did not do). Columns:
- *Foot*: speed of the ankle–ball midpoint.
- *Pivot*: speed of the slower of ankle and ball, which a correct heel-to-toe roll keeps near 0.
- *Travel*: the root's 2 Hz low-passed horizontal path and its net displacement, both relative to raw.
- *Jitter*: mean |jerk| over the 22 joints.
- *Knees*: knee local-rotation speed; a "pop" is a frame above 500 °/s.

| Clip | Variant | Slide in contact, foot / pivot (cm/s) | Travel vs raw (path / net) | Jitter (m/s³) | Knees |
|---|---|---|---|---|---|
| walk-fp32 (Wick, 94 f) | raw GVHMR | 26.3 / 23.7 | 100 / 100 % | 494 | p99 185 °/s, 0 pops |
| | One Euro | 15.3 / 12.9 | 99.4 / 100 % | 78 | |
| | root lock (v1) | 5.8 / 4.8 | **90.6 / 90.7 %** | 84 | |
| | **IK lock (v2)** | **4.4 / 2.5** | **99.4 / 100 %** | 81 | p99 271 °/s, 0 pops, 0 new; root drop ≤ 2.3 cm |
| walk-bf16 | **IK lock (v2)** (raw 26.6 / 24.0) | **4.4 / 2.5** | 99.4 / 100 % | 82 (raw 498) | 0 new pops |
| osaka-bf16 (Shimazu, 155 f) | raw GVHMR | 4.9 / 4.0 | 100 / 100 % | 208 | p99 157 °/s, 0 pops |
| | One Euro | 10.5 / 8.8 | 99.5 / 100 % | 33 | |
| | root lock (v1) | 4.7 / 3.9 | **83.5 / 82.7 %** | 40 | |
| | **IK lock (v2)** | **2.9 / 1.3** | **99.5 / 100 %** | 40 | p99 185 °/s, 0 pops, 0 new; root drop ≤ 2.7 cm |
| sc-fp32 (tumble, 479 f) | raw → **IK lock (v2)** | 48.7 / 45.0 → 10.1 / 4.7 | 89.9 / 100 % | 3431 → 849 | 0 new pops |
| sc-bf16 | raw → **IK lock (v2)** | 41.0 / 36.4 → 10.1 / 5.0 | 90.9 / 100 % | 3307 → 757 | **1 new frame > 500 °/s** |

What the table shows:

- **Travel ≥ 98 %: met on the clean clips (99.4–99.5 % path, 100 % net).** The IK leaves the root's horizontal path untouched. On the tumble, the 10 % path difference is One Euro removing raw jitter from a garbage track; the lock contributes nothing to it.
- **Slide:** pivot slide is down **10× on the walk (23.7 → 2.5 cm/s)** and **3× on Osaka (4.0 → 1.3)**. Pin error is ≤ 1.4 mm mean and ≤ 7.3 mm max.
- **One Euro alone makes skating worse.** On Osaka it doubles the slide, 4.0 → 8.8 cm/s, because smoothing the root and the legs separately de-syncs the feet. That is why v1 looked bad there. v2 fixes it.
- **Jitter:** on the walk it stays at the One Euro level (78 → 81). On Osaka it rises 33 → 40: planted feet start and stop more sharply than sliding ones, which is real. Both are still −80 to −84 % against raw.
- **Knees:** p99 knee speed rises (185 → 271 °/s on the walk), as the knees now absorb the slide, but stays well under pop range. **No new pops on any clean clip.** One frame on the unusable tumble.
- **The old in-motion skate metric** (`foot_skate_mean_cm_s` in `qc.json`, contacts re-detected on each variant) is kept for continuity but is not comparable across variants.

How the parameters were picked (Osaka sweep):

| Setting | Jitter (m/s³) | Pin error max | Root drop | Notes |
|---|---|---|---|---|
| Ankle pinned at the mean over the whole contact (first try) | 58–72 | | 6–7 cm | heel-off was being dragged down |
| Heel/toe phases | | | 2.3–2.7 cm | |
| Offset smoothing σ = 0 | 47 | | | |
| Offset smoothing σ = 1 (**chosen**) | 40 | 7 mm | | |
| Offset smoothing σ = 2.5 | 35 | 20 mm | | |

Changing the blend from 4 to 8 frames changed little.

### 4. Idle benchmark, measured (replaces the extrapolation)

Gate: `data/build/bench-idle/DONE` was present, and each run waited for 1-min loadavg < 1.5 (`idle-bench.sh`).

Clip: the same as the first bench, `jw4-osaka-shimazu-walk.mp4`, 124 source frames staged to 155 at 30 fps, with `--stitch`.

The loadavg in the logs rises during runs because of the runs themselves.

**Found on the way: YOLO ignored the thread cap.**
- Cause: ultralytics' `select_device()` calls `torch.set_num_threads(min(8, ncpu − 1))`, so YOLO always ran on 8 threads.
- Measured after the fix (`bench_gvhmr.py` now sets `ultralytics.utils.torch_utils.NUM_THREADS`): 1 / 4 / 8 / 16 threads give 1.046 / 0.309 / 0.182 / 0.207 s/frame.
- Consequence 1: the first pass's "4-thread" totals contain 8-thread YOLO. The true 4-thread bf16 total is about 1.12, not 0.99, s/frame.
- Consequence 2: before the fix, 4 concurrent 4-thread processes ran 32 YOLO threads on 16 logical CPUs. YOLO took 3.64 s/frame per process, and the aggregate was 1.36 s/frame (842 s wall).

**Per-stage seconds per frame, single process, idle:**

| Stage | bf16 t16 | fp32 t16 | **bf16 t8** | **fp32 t8** | first pass bf16 "t4" |
|---|---|---|---|---|---|
| stage to 30 fps | 0.005 | 0.005 | 0.005 | 0.005 | 0.005 |
| YOLOv8x + BoT-SORT | 0.207¹ | 0.207¹ | 0.183 | 0.180 | 0.181 (really t8) |
| decode + crop | 0.001 | 0.001 | 0.001 | 0.001 | 0.001 |
| ViTPose-H (flip-test) | 0.318 | 0.650 | **0.309** | **0.640** | 0.529 |
| HMR2 ViT-H features | 0.151 | 0.339 | **0.150** | **0.319** | 0.261 |
| SimpleVO + GVHMR | 0.010 | 0.010 | 0.010 | 0.010 | 0.010 |
| **Total** | **0.69¹** | **1.21¹** | **0.657** | **1.155** | 0.99 |
| h per 60 min (108k frames) | 20.8 | 36.4 | **19.7** | **34.7** | |

¹ The t16 runs went before the YOLO fix, with YOLO on 8 threads at 0.184. The totals substitute the post-fix 16-thread YOLO probe (0.207).

**HMR2 thread scaling** (32 frames, `thread-scaling.sh`, idle):

| Threads | 1 | 2 | 4 | 8 | 16 |
|---|---|---|---|---|---|
| fp32 (s/frame) | 1.862 | 0.979 | 0.685 | 0.302 | 0.368 |
| bf16 (s/frame) | 0.939 | 0.492 | 0.264 | **0.146** | 0.153 |

- bf16 scales 6.4× to 8 threads and 0 beyond: 8 physical cores, so SMT does not help GEMM.
- fp32 4 → 8 is 2.3× (oneDNN picks a different kernel). The fp32 bf16 gap shrinks to 2.07× at 8 threads.

**Concurrent schedules** (bf16, `concurrency-bench.sh`, wall time including model loads, after the YOLO fix):

| Schedule | Wall for N × 155 frames | **Aggregate s/frame** | h per 60 min |
|---|---|---|---|
| 1 × 16 threads | 112.6 s | 0.727 | 21.8 |
| 1 × 8 | 105.3 s | 0.679 | 20.4 |
| 2 × 8 | 195.1 s | 0.629 | 18.9 |
| 2 × 4 | 192.3 s | 0.620 | 18.6 |
| **4 × 4** | 367.8 s | **0.593** | **17.8** |

In the 4 × 4 run, each process measured YOLO 0.645, ViTPose 1.11 and HMR2 0.553 s/frame. As shares of the time, that is YOLO 28 %, ViTPose 48 % and HMR2 24 %.

**Projection for 60 min of footage (108k frames).** The 4 × 4 schedule row is measured. The rows below it are derived from the measured 4 × 4 stage shares.

| Configuration | h per 60 min |
|---|---|
| fp32 as shipped, best single process (8 threads) | **34.7** (measured) |
| bf16 ViTs, 4 × 4 schedule (accuracy-neutral) | **17.8** (measured) |
| + ViTs only on source frames (skip the 20 % duplicates) | ≈ 15.3 |
| + ViTPose flip-test off (accuracy trade: +2.3 mm PA-MPJPE on 3DPW per the fork) | ≈ 11.9 |
| + YOLO also at source fps | ≈ 10.9 |

**Against the estimates:**

| Configuration | NOTES §8 | First-pass extrapolation | **Measured** |
|---|---|---|---|
| Naive (fp32, as shipped) | 22 h | 43–47 h | **35 h** |
| bf16, accuracy-neutral | — | 15–17 h at 16 threads | **17.8 h** (4 × 4); 20–22 h as a single 8/16-thread process |
| Optimised | 8–12 h | 9.5 h | ≈ 11–12 h, and only with flip-test off and source-fps YOLO |

- NOTES' 22 h naive figure is 1.6× too optimistic.
- The first pass was too pessimistic on fp32, because fp32 scales better 4 → 8 than it assumed.
- It was too optimistic on bf16 at 16 threads: 16 threads equals 8, and YOLO had already been at 8 threads in its numbers.

### 5. Risk notes

- **Third-party fork (`ryanrudes/gvhmr`), 🟡.**
  - Risks:
    - It has one maintainer and could disappear or be rewritten.
    - Its `pyproject` says MIT while `LICENSE` is the ZJU non-commercial text.
    - It is a supply-chain surface: we run its code and its lockfile's wheels.
  - Mitigating facts:
    - Its stated prime directive is behaviour preservation, with golden-output tests against the released checkpoint. Its eval reproduces the paper (3DPW / EMDB-1).
    - Our bench uses only its public entry points (`build_demo_cfg`, `load_data_dict`, `recover_motion`).
    - It runs unmodified, and the checkpoints are the authors' own.
  - **Recommendation:** keep it, pinned at `e3876097` and installed `--frozen` from its `uv.lock`. Also:
    1. Store a `git bundle` or source tarball and the `uv.lock` hash under `private/src/` so a deleted repo cannot strand us.
    2. Treat the ZJU `LICENSE` as binding.
    3. Keep the upstream `zju3dv/GVHMR` clone as the reference. If the fork goes stale, the fallback is upstream plus CPU patches (87 `.cuda()` sites).
- **Python 3.11 instead of 3.10, 🟢.**
  - NOTES' 3.10 rule exists to keep research code off the system Python 3.14 and in uv-managed envs. A uv python-build-standalone 3.11.16 venv satisfies that intent.
  - The fork's floor is 3.11 (`tomllib`), and upstream's own 3.10 pin was just its era's default.
  - **Recommendation:** accept, and change NOTES §4 as proposed: "uv-managed envs at the version the codebase's lockfile requires (3.10 or 3.11); never the system Python".
- **Sacré-Cœur tumble unusable, 🟢 (expected).**
  - It matches the NOTES §8 weak spot "falls and ground work". The failure is upstream of GVHMR: YOLO coverage is 3–12 % on the dark, inverted, blurred body.
  - The v2 foot lock does not change that verdict: jitter is still 757–849 m/s³ after cleanup.
  - **Recommendation:** drop the tumble as a video→motion target. Keep the Sacré-Cœur **climb/walk** shots and the BTS stair clip (pending the IGN ruling) for stairs.
  - Source falls and stumbles from mocap (CMU) plus physics/ragdoll blending, or Kimodo fill-in, per §8's layering.

### Reproduce (follow-up)

```bash
# YouTube (after the user's cookie export)
pipeline/video-to-motion/fetch-youtube.sh
# idle benches: waits for loadavg < 1.5 before each step
pipeline/video-to-motion/idle-bench.sh
pipeline/video-to-motion/concurrency-bench.sh 4 4
# QC with the v2 foot lock on every run, then the A/B table
for r in walk-fp32 walk-bf16 osaka-bf16 sc-fp32 sc-bf16; do
  OMP_NUM_THREADS=2 GVHMR_CHECKPOINTS=private/models/gvhmr private/src/gvhmr-rudes/.venv/bin/python -I \
    pipeline/video-to-motion/motion_qc.py private/work/runs/$r --motion-out private/motion/$r --vis-out private/work/vis/$r
done
private/src/gvhmr-rudes/.venv/bin/python -I pipeline/video-to-motion/foot_lock_table.py private/motion/{walk-fp32,osaka-bf16,sc-fp32}
```

All outputs (`private/motion/*`, `private/work/*`, footage, logs) stay under `private/`, which is gitignored.
