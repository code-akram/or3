#!/usr/bin/env bash
# Reproducible wrapper around bench_gvhmr.py. Pins the thread caps and asset roots.
#
# Usage: run-bench.sh CLIP.mp4 RUN_NAME [extra bench_gvhmr.py args...]
#   THREADS=4 (default) — set THREADS=16 on an idle machine to measure the full box.
# Outputs land in private/work/runs/RUN_NAME (gitignored).
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
main_root="${MAIN_ROOT:-/home/akram/code/or3}"
gvhmr_src="${GVHMR_SRC:-$main_root/private/src/gvhmr-rudes}"
threads="${THREADS:-4}"
clip=$1 name=$2
shift 2

export OMP_NUM_THREADS=$threads MKL_NUM_THREADS=$threads OPENBLAS_NUM_THREADS=$threads
export GVHMR_CHECKPOINTS="$main_root/private/models/gvhmr"
export GVHMR_CONFIG="$main_root/private/src/gvhmr.toml"   # need not exist: pins defaults, ignores ~/.config
export GVHMR_DEVICE=cpu HF_HUB_OFFLINE=1 YOLO_OFFLINE=1
export YOLO_CONFIG_DIR="$main_root/private/work/ultralytics"

echo "threads=$threads loadavg_before=$(cut -d' ' -f1-3 /proc/loadavg)"
exec "$gvhmr_src/.venv/bin/python" -I "$here/bench_gvhmr.py" "$clip" \
  --out "$main_root/private/work/runs/$name" --threads "$threads" "$@"
