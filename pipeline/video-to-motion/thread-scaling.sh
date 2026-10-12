#!/usr/bin/env bash
# HMR2 ViT-H torch fp32/bf16 s/frame at several thread counts (same crops, same 32 frames).
# Usage: thread-scaling.sh RUN_DIR [THREADS...]   e.g. thread-scaling.sh private/work/runs/sc-fp32 1 2 4 8 16
# Phase 0 ran only 1/2/4 (shared box, 4-thread cap); rerun with 8 16 on an idle machine.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
main_root="${MAIN_ROOT:-/home/akram/code/or3}"
run=$1
shift
export GVHMR_CHECKPOINTS="$main_root/private/models/gvhmr" GVHMR_CONFIG="$main_root/private/src/gvhmr.toml" GVHMR_DEVICE=cpu
ts=("$@")
((${#ts[@]})) || ts=(1 2 4)
for t in "${ts[@]}"; do
  echo "threads=$t loadavg=$(cut -d' ' -f1-3 /proc/loadavg)"
  OMP_NUM_THREADS=$t MKL_NUM_THREADS=$t "$main_root/private/src/gvhmr-rudes/.venv/bin/python" -I "$here/vit_backends.py" \
    "$run" --frames 32 --batch 16 --threads "$t" --stages hmr2 --tag="-t$t" 2>&1 | grep -E '^hmr2 '
done
