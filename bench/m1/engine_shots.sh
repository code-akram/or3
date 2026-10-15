#!/usr/bin/env bash
# Engine frames for one look-dev run (track T5, bench/m1/v4/t5-viewer.md):
#   1. blender/hero/export_rig.py  -> RUN/engine_stage.json (look-dev + hero cameras, lights, pose)
#   1b. blender/hero/grade.py --lut  -> RUN/grade_lut.json (T16: the hero grade + AgX view as 3D LUTs)
#   2. bench/m1/engine_shots.mjs   -> RUN/game_<view>.png + RUN/game_shots.json (headless Chromium;
#      --tier T / --prefix P name them T_ / P instead)
#
#   bench/m1/engine_shots.sh RUN_DIR [--port N] [more engine_shots.mjs options, e.g. --turntable 2]
#
# --port and any further options pass through to engine_shots.mjs (--port wins over ENGINE_PORT).
#
# Everything is read from and written to RUN_DIR only (a private fan run dir stays private).
# Env: ENGINE_CPUS (taskset CPU list for the browser, default 0-3; the machine is shared),
#      ENGINE_BACKEND (auto|webgpu|webgl2, default auto: WebGPU, WebGL2 fallback),
#      ENGINE_GPU (GPU1: swiftshader|hw, default swiftshader; hw = the iGPU, adapter-checked, under
#        /tmp/or3-gpu.lock; read by engine_shots.mjs, see bench/m1/v4/gpu1-hw-backend.md),
#      ENGINE_SIZE (look-dev views, default 1024), ENGINE_PORTRAIT (default 1920x1080),
#      ENGINE_VIEWS (default front,three_quarter,profile,closeup,portrait,closeup:hero),
#      ENGINE_BOUNCE (T16: a set_bounce.json from blender/hero/refs.py --mode bounce, copied into RUN),
#      ENGINE_PORT (loopback port of the asset server, default 8796, outside the review servers' 8790-8793; shared machines pick a free one).
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
RUN="$(realpath "${1:?usage: $0 RUN_DIR [--port N] [engine_shots.mjs options]}")"
shift
PORT="${ENGINE_PORT:-8796}"
PASS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="${2:?--port N}"; shift 2 ;;
    *) PASS+=("$1"); shift ;;
  esac
done
[[ -s "$RUN/character.glb" ]] || { echo "no character.glb in $RUN" >&2; exit 2; }
LOG="$RUN/engine_shots.log"
: > "$LOG"

blender -b -t 3 --factory-startup --python-exit-code 1 --python "$REPO/blender/hero/export_rig.py" -- \
  --glb "$RUN/character.glb" --out "$RUN/engine_stage.json" >> "$LOG" 2>&1 \
  || { echo "engine stage export failed: $LOG" >&2; exit 1; }

# T16: the hero grade as data (AgX + the compositor grade baked through Blender into 33^3 LUTs and the
# vignette map; the viewer applies them with Lut3DNode). The set bounce is a Cycles render of the set
# without the character (blender/hero/refs.py --mode bounce), made once; ENGINE_BOUNCE copies it in.
blender -b -t 4 --factory-startup --python-exit-code 1 --python "$REPO/blender/hero/grade.py" -- \
  --lut "$RUN/grade_lut.json" >> "$LOG" 2>&1 \
  || { echo "grade LUT bake failed: $LOG" >&2; exit 1; }
if [[ -n "${ENGINE_BOUNCE:-}" ]]; then cp "$ENGINE_BOUNCE" "$RUN/set_bounce.json"; fi

# node deps of this checkout (fresh worktrees have none yet)
[[ -d "$REPO/bench/node_modules/playwright" ]] || npm ci --prefix "$REPO/bench" --no-fund --no-audit >> "$LOG" 2>&1
[[ -d "$REPO/web/node_modules/three" ]] || npm ci --prefix "$REPO/web" --no-fund --no-audit >> "$LOG" 2>&1
# the viewer bundle is rebuilt every run (about a second) so it always matches the checkout
npm run --prefix "$REPO/web" build:viewer --silent >> "$LOG" 2>&1 || { echo "viewer build failed: $LOG" >&2; exit 1; }

PIN=()
command -v taskset > /dev/null && PIN=(taskset -c "${ENGINE_CPUS:-0-3}")
"${PIN[@]}" node "$REPO/bench/m1/engine_shots.mjs" --build "$RUN" \
  --backend "${ENGINE_BACKEND:-auto}" --size "${ENGINE_SIZE:-1024}" --portrait "${ENGINE_PORTRAIT:-1920x1080}" \
  --views "${ENGINE_VIEWS:-front,three_quarter,profile,closeup,portrait,closeup:hero}" --port "$PORT" ${PASS[@]+"${PASS[@]}"} >> "$LOG" 2>&1 \
  || { echo "engine shots failed: $LOG" >&2; exit 1; }
# the newest <prefix>shots.json (game_shots.json, or <tier>_shots.json with --tier / --prefix)
SHOTS="$(ls -t "$RUN"/*shots.json | head -n 1)"
echo "-> $SHOTS ($(python3 -I -c "import json,sys; d=json.load(open(sys.argv[1])); print(d.get('backend'), 'on', d.get('adapter_line') or d.get('gpu', 'swiftshader'))" "$SHOTS"))"
