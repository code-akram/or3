#!/usr/bin/env bash
# T15 head views for one look-dev run (bench/m1/v4/t15-hair-volume.md): hair silhouette IoU (engine vs
# Cycles hero) at a head-framed three-quarter and profile, and per-region hair tone (crown / side / back /
# front falls), engine / Cycles.
#
#   bench/m1/hair_views.sh RUN_DIR            (needs RUN_DIR/character.blend: KEEP_BLEND=1, and
#                                              RUN_DIR/engine_stage.json: bench/m1/engine_shots.sh)
#   bench/m1/hair_views.sh --measure RUN_DIR  re-shoot the engine frames and re-measure (no Cycles)
#
# 1. hair_test.py --parts views (Cycles, under flock /tmp/or3-cycles.lock): RUN/hair_test/views/engine_stage.json,
#    hv_<view>_{cycles,hero,game}.exr
# 2. engine_shots.mjs on RUN/hair_test/views: game_<view>.png (AgX) and lin_<view>.png (Standard)
# 3. hair_test.py --parts views_measure -> RUN/hair_test/hair_test.json "views", hv_<view>_iou.png
# Env: ENGINE_PORT (default 8798), ENGINE_LOCK (flock file serialising browsers on that port, default
# /tmp/or3-engine-<port>.lock), ENGINE_CPUS (default 0-3), CYCLES_THREADS (default 6),
# VIEWS_ARGS (extra hair_test.py options for the views render, e.g. "--views-lights key,fill,rim", T20).
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
MEASURE=
[[ "${1:-}" == "--measure" ]] && { MEASURE=1; shift; }
RUN="$(realpath "${1:?usage: $0 [--measure] RUN_DIR}")"
HT="$RUN/hair_test"
VD="$HT/views"
mkdir -p "$HT"
BL=(nice -n 10 blender -b --factory-startup --python-exit-code 1)
if [[ -z "$MEASURE" ]]; then
  [[ -f "$RUN/character.blend" ]] || { echo "no character.blend in $RUN (KEEP_BLEND=1)" >&2; exit 2; }
  flock /tmp/or3-cycles.lock "${BL[@]}" -t "${CYCLES_THREADS:-6}" --python "$REPO/bench/m1/hair_test.py" -- \
    "$RUN" --parts views ${VIEWS_ARGS:-} > "$HT/views.log" 2>&1 || { echo "views render failed: $HT/views.log" >&2; tail -20 "$HT/views.log" >&2; exit 1; }
fi
[[ -f "$VD/engine_stage.json" ]] || { echo "no $VD/engine_stage.json (run without --measure first)" >&2; exit 2; }
npm run --prefix "$REPO/web" build:viewer --silent > "$HT/views_engine.log" 2>&1
PIN=()
command -v taskset > /dev/null && PIN=(taskset -c "${ENGINE_CPUS:-0-3}")
for pre in game_ lin_; do
  Q=(); [[ $pre == lin_ ]] && Q=(--query view_transform=standard)
  flock "${ENGINE_LOCK:-/tmp/or3-engine-${ENGINE_PORT:-8798}.lock}" nice -n 10 "${PIN[@]}" node "$REPO/bench/m1/engine_shots.mjs" --build "$VD" --views three_quarter,profile,front,back,closeup \
    --size 1024 --port "${ENGINE_PORT:-8798}" --prefix "$pre" "${Q[@]}" >> "$HT/views_engine.log" 2>&1 \
    || { echo "engine shots failed: $HT/views_engine.log" >&2; tail -20 "$HT/views_engine.log" >&2; exit 1; }
done
"${BL[@]}" -t 4 --python "$REPO/bench/m1/hair_test.py" -- "$RUN" --parts views_measure > "$HT/views_measure.log" 2>&1 \
  || { echo "views measure failed: $HT/views_measure.log" >&2; tail -20 "$HT/views_measure.log" >&2; exit 1; }
grep -E '^\[hair_test\] views' "$HT/views_measure.log" || true
echo "-> $HT/hair_test.json (views), $HT/hv_*_iou.png, $VD/{game,lin}_*.png"
