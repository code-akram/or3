#!/usr/bin/env bash
# Spike 1 bench: build the MPFB2 character headless N times, then validate the GLB.
# Records thread count, /proc/loadavg and per-step timings for each run.
#
# Usage: bench/m0/bench_spike1_build.sh [RUNS] [THREADS]
# Env:   DATA=/path/to/main/checkout/data (default: <repo>/data)
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
DATA="${DATA:-$REPO/data}"
RUNS="${1:-3}"
THREADS="${2:-3}"
OUT="$DATA/build/character/character.glb"
SYS="$DATA/raw/makehuman/makehuman_system_assets/unpacked"
SUIT="$DATA/raw/makehuman/suits01/unpacked"
LOG="$DATA/build/character/bench_spike1.log"
mkdir -p "$(dirname "$OUT")"
: > "$LOG"

for i in $(seq 1 "$RUNS"); do
  echo "run=$i threads=$THREADS loadavg_start=$(cat /proc/loadavg)" | tee -a "$LOG"
  start=$(date +%s.%N)
  blender -b -t "$THREADS" --factory-startup --python "$REPO/blender/build_character.py" -- \
    --system-assets "$SYS" --suit-assets "$SUIT" --out "$OUT" > "$LOG.run$i" 2>&1
  end=$(date +%s.%N)
  grep '^\[build\] .*: ' "$LOG.run$i" | tee -a "$LOG"
  python3 -c "print(f'process_wall_s={$end-$start:.2f}')" | tee -a "$LOG"
done

echo "--- validation (Khronos glTF-Validator + stats)" | tee -a "$LOG"
( cd "$REPO/bench/m0/glb-stats" && [[ -d node_modules ]] || npm install --no-fund --no-audit >/dev/null )
node "$REPO/bench/m0/glb-stats/glb_stats.mjs" "$OUT" --json "${OUT%.glb}.glbstats.json" \
  | grep -E '"(errors|warnings|totalTris|bytes)"' | tee -a "$LOG"
npx --prefix "$REPO/bench/m0/glb-stats" gltf-transform inspect "$OUT" --format md > "${OUT%.glb}.inspect.txt" 2>&1 || true
echo "inspect -> ${OUT%.glb}.inspect.txt" | tee -a "$LOG"
