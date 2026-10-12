#!/usr/bin/env bash
# One-time setup of the CPU GVHMR env used by Phase 0 spike 3 (no sudo, all under private/).
#
#  - ryanrudes/gvhmr (modernised, device-agnostic fork of zju3dv/GVHMR), pinned commit, no patches
#  - uv venv, Python 3.11 (the fork's floor; upstream is 3.10 but hard-codes CUDA (87 .cuda()/"cuda" sites) and needs a pytorch3d build),
#    CPU-only torch from the PyTorch CPU index via the fork's `cpu` extra, plus the `preproc` extra
#  - TransNetV2 (MIT, weights bundled in the wheel) + PySceneDetect for the shot split
#  - checkpoints (gvhmr, hmr2, vitpose, yolov8x) from the HF mirror camenduru/GVHMR into private/models/gvhmr
#  - SMPL / SMPL-X symlinked from private/body-models (registration-gated; fetched by pipeline/fetch-body-models.sh)
set -euo pipefail
main_root="${MAIN_ROOT:-/home/akram/code/or3}"
src="$main_root/private/src/gvhmr-rudes"
commit=e3876097a9c4d9c1758d058d9e70c64f0cdba4c4   # ryanrudes/gvhmr main, v1.6.1+ (2026-10-12)
models="$main_root/private/models/gvhmr"

if [[ ! -d "$src" ]]; then
  git clone https://github.com/ryanrudes/gvhmr.git "$src"
  (cd "$src" && git checkout -q "$commit")
fi
cd "$src"
uv sync --python 3.11 --frozen --extra cpu --extra preproc
uv pip install --python .venv/bin/python "scenedetect==0.7.1" "transnetv2-pytorch==1.0.5"

mkdir -p "$models/body_models"
ln -sfn "$main_root/private/body-models/smpl" "$models/body_models/smpl"
ln -sfn "$main_root/private/body-models/smplx" "$models/body_models/smplx"
GVHMR_CHECKPOINTS="$models" GVHMR_CONFIG="$main_root/private/src/gvhmr.toml" HF_HUB_DISABLE_TELEMETRY=1 \
  .venv/bin/gvhmr download demo
