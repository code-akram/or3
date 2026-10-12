# Phase 0 spike 3: video to motion with GVHMR on CPU

Date: 2026-10-12. Machine: Ryzen 7 7700 (Zen 4, AVX-512 bf16), 62 GB RAM, CPU only.
The box was shared with other spikes. **Every timing below uses 4 threads**, with `loadavg` recorded next to it.

## Summary

- **It runs on CPU with zero patches.**
  - The full pipeline ran end to end: shot split, YOLO + BoT-SORT, ViTPose-H, HMR2 ViT-H features, SimpleVO, GVHMR, then QC, cleanup and npz/BVH export.
  - It uses the `ryanrudes/gvhmr` fork, which is device-agnostic, plus a 3-line external `torch.autocast("cpu", bfloat16)` wrapper.
- **Throughput at 4 threads**:
  - As shipped (fp32): **2.5 s per frame**.
  - With bf16 autocast on the two ViT-H stages: **0.99 s per frame** for the whole pipeline. That is 2.8× faster on the ViTs, with no measurable quality change: 1.2 mm root-aligned MPJPE between the fp32 and bf16 runs.
- **Projection for 60 min of footage at 16 threads** (≈108k frames once resampled to 30 fps):
  - bf16: **≈ 15–17 h**.
  - bf16 + skipping duplicated frames: **≈ 13 h**.
  - bf16 + skipping duplicates + ViTPose flip-test off (an accuracy trade): **≈ 9–10 h**.
  - fp32 as shipped: **≈ 40–47 h**.
  - NOTES §8 estimated 22 h naive and 8–12 h optimised. Naive is about 2× worse than estimated. Optimised is reachable only with the accuracy trade.
- **Quality**:
  - **Clean, lit, full-body walks**: plausible, usable motion. The 2D fit is good (8.7 px median reprojection on 576×1024). Jitter is high raw and drops about 82% with zero-phase One Euro.
  - **The Sacré-Cœur stair tumble** (NOTES target #1) is **unusable**. YOLOv8x, YOLO26x and YOLO11x all lose the tumbling, dark, motion-blurred body. The protagonist's track covers 4–12% of frames, so GVHMR is fed garbage boxes.
- **Biggest blocker: footage access.**
  - YouTube answers every client from this machine with "Sign in to confirm you're not a bot", so the Lionsgate Movies YouTube featurettes and clips could not be fetched.
  - The only official source that worked is **Lionsgate UK's TikTok**. Those are 576×1024 vertical re-frames with captions and fast cuts: low resolution, unknown crop intrinsics and few long clean shots.
  - The user needs to supply YouTube cookies (see User actions).

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
- A root-level foot lock, which integrates and cancels the planted foot's horizontal slide.
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

## Throughput projection: 60 min of footage at 16 threads

Assumptions:

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
| Foot lock too crude | Measured and documented: root-level lock removes 11–17% of real travel and made skating worse on the clean Osaka walk. Production needs contact-aware two-bone IK |
| `exiftool` missing (focal from metadata) | Irrelevant for web video; GVHMR falls back to its diagonal-FOV heuristic. **That heuristic is wrong for vertical crops of 2.39:1 film**, which makes the root scale suspect |

## Risks

1. **Footage access and quality (🔴).**
   - Without YouTube we only have vertical, captioned, 576-px TikTok re-edits.
   - They carry unknown crop intrinsics, so GVHMR's focal guess is wrong and root speed and depth are biased.
   - They are also few in clean shots longer than 3 s.
2. **Most Wick footage fails at detection, not at GVHMR (🔴).**
   - Night, motion blur, tumbles and fights defeat YOLO (v8x, 11x and 26x alike).
   - The NOTES §8 luma filter (< 40/255) would reject almost all night material anyway: Sacré-Cœur shot medians are 6–23, and the Osaka walk is 36.
   - The usable yield of identity motion per hour of footage may be low.
3. **Throughput (🟠).** 13–17 h per hour of footage, accuracy-neutral. Acceptable only with aggressive shot gating before the ViTs.
4. **Cleanup quality (🟠).**
   - Raw jitter is high: 200–500 m/s³ on clean walks.
   - One Euro fixes jitter, but the simple foot lock fights real locomotion.
   - Coat-occluded leg crossings glitch.
5. **Dependencies and licences (🟡).**
   - The fork has a single third-party maintainer, so pin the commit.
   - The GVHMR licence is non-commercial; HMR2 is SMPL-based; YOLO is AGPL.
   - All are offline only and never shipped, and §17 item 6 (SMPL-derived motion) still governs shipping.

## Recommendation

- **Adopt** GVHMR via the `ryanrudes` fork at the pinned commit, with Python 3.11 in a uv venv. Run bf16 autocast on CPU for ViTPose and HMR2 by default: 2.8× faster on those stages and quality-neutral.
- **Do not chase OpenVINO yet.** It is only about 15% over torch bf16.
- **Next optimisation:** run the ViTs at source fps and reuse their outputs for the duplicated 30 fps frames (−20%).
- **Spend the effort on shot selection, not compute.** Gate shots, in this order:
  1. Union of TransNetV2 and PySceneDetect cuts.
  2. Protagonist track coverage ≥ 90%.
  3. ViTPose mean confidence ≥ 0.7.
  4. Subject height ≥ 256 px.
  5. Recalibrate the luma floor down to about 15 rather than 40.
- **Prefer** walks, stands and draws in lit or daylight shots. Treat falls and fights as out of scope for video-to-motion, as NOTES already lists them among the weak spots.
- **Get the YouTube Lionsgate featurettes** (1080p horizontal) before judging Wick-identity yield. TikTok re-edits are a poor proxy.
- **Cleanup v2:**
  - Keep zero-phase One Euro, with a lower cutoff on the torso than on the feet.
  - Replace the root-level lock with contact-aware IK on the legs.
  - Add a glitch detector (angular-speed spikes) that masks and re-infills frames.

## User actions

1. **YouTube cookies.**
   - Export Netscape-format cookies for youtube.com from a logged-in browser to `/home/akram/code/or3/private/youtube-cookies.txt`, then `chmod 600` it. That path is gitignored. Treat the file as a secret.
   - Then run: `YTDLP_EXTRA="--cookies /home/akram/code/or3/private/youtube-cookies.txt" pipeline/video-to-motion/fetch-footage.sh yt-ohieMx5bSM8 yt-3oIxZLUKYtI yt-r7a4g-65SzA`.
   - Alternatively, decide that TikTok-only is acceptable for now.
2. Optional, on an idle machine: rerun `THREADS=16 pipeline/video-to-motion/run-bench.sh …` and `thread-scaling.sh … 8 16` to replace the 16-thread estimates with measurements.
3. Confirm the Python 3.11 deviation and the use of the third-party fork.
4. No `sudo pacman` was needed for this spike. OpenVINO came in as a pip wheel inside the venv.

## Proposed NOTES.md updates

- **§4 / §6:** "Python 3.10 envs via uv" becomes "Python 3.10–3.11 uv envs. GVHMR uses the `ryanrudes/gvhmr` fork (CPU-native, Python ≥ 3.11) at commit `e3876097`."
- **§8 Video → motion, footage source:**
  - Add: "YouTube blocks this machine ('confirm you're not a bot'), so fetching needs user cookies (`private/youtube-cookies.txt`)."
  - Add: "Lionsgate UK TikTok downloads without auth, but gives 576×1024 vertical re-edits with captions. Use them only as a fallback."
- **§8 pipeline:**
  - "TransNetV2 shot split (PySceneDetect as cross-check)" becomes "**union** of TransNetV2 and PySceneDetect cuts (TransNetV2 missed a hard cut in testing)".
  - Filter: replace "median luma < ~40/255" with "median luma < ~15/255" (night Wick footage measures 6–36). Add "protagonist track coverage < 90%" and "ViTPose mean confidence < 0.7".
  - GVHMR line: "bf16 autocast on CPU for ViTPose/HMR2 (measured 2.8×, 1.2 mm MPJPE change). OpenVINO measured at only +15% over that."
- **§8 throughput line:** replace with "**Measured (Phase 0):**
  - 2.5 s/frame fp32 and 0.99 s/frame bf16 at 4 threads (30 fps frames).
  - ViT-H passes are 89% (fp32) / 80% (bf16) of the time; YOLO is 18% in bf16.
  - About 15–17 h per 60 min at 16 threads with bf16 (accuracy-neutral), about 13 h when skipping duplicated frames, and about 9.5 h with ViTPose flip-test off. fp32 as shipped is about 43–47 h."
- **§8 weak spots:** add "dark / motion-blurred / inverted bodies, where the person detector fails (YOLOv8x/11x/26x all under 12% coverage on the Sacré-Cœur tumble)" and "long coats hiding crossing legs".
- **§8 extraction targets:** demote the "Sacré-Cœur stairs (wide shots)" tumble. The usable stair content is the climbing and walking shots, not the fall.
- **§14:** record the offline-only tool licences: YOLO weights are AGPL-3.0, the HMR2 checkpoint is SMPL-based, ViTPose is Apache-2.0, and GVHMR is non-commercial (the fork's `pyproject` "MIT" classifier contradicts its `LICENSE` file).
- **§16 risks:**
  - Update the "GVHMR CPU throughput / quality" row with the numbers above.
  - Add "footage access (YouTube bot wall)", rated 🔴.
  - Add "detector failure on night/action shots, so low usable yield", rated 🔴.
- **§18 item 3:** mark it done, linking `bench/m0/spike-3-gvhmr.md`.

## Files

Committed under `pipeline/video-to-motion/`:

| File | Purpose |
|---|---|
| `setup-gvhmr.sh` | build the env |
| `fetch-footage.sh` | fetch the official clips |
| `cut-shot.sh` | cut one shot by frame range |
| `shots.py` | shot split and filter stats |
| `run-bench.sh` + `bench_gvhmr.py` | the reproducible per-stage bench, plus protagonist stitching and the bf16 wrapper |
| `vit_backends.py`, `thread-scaling.sh` | ViT backends micro-bench and thread scaling |
| `motion_qc.py` | metrics, cleanup, npz/BVH export and visual check |
| `compare_runs.py` | fp32 vs bf16 comparison |

No patch diff is needed; the fork runs unmodified.
