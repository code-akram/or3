#!/usr/bin/env bash
# m1 v2 hero stage: render the hero shot list (neon-noir alley, Cycles CPU +
# OIDN), grade it, render the honesty turntable, draw a contact sheet.
# See bench/m1/v2/hero-stage.md.
#
# Usage:
#   bench/m1/hero.sh [options] <character.blend|.glb> <label>
#       -> $DATA/build/hero/<UTC>-<label>/
#     --preview          (default) 50 % resolution, 64 spp adaptive
#     --final            100 % (1920x1080, 1152x2048 poster, 1080x1620 turntable), 768 spp adaptive
#     --draft            25 %, 16 spp: a framing / pose check in a few seconds per shot
#     --shots LIST       comma list from blender/hero/shots.py (default all), or none
#     --no-turntable     skip the turntable
#     --tt-views LIST    turntable views (default tt0,...,tt315)
#     --tt-poses LIST    turntable poses (default rest,stand)
#     --set alley|void   the alley (default) or the bare hero rig on black
#     --paint F          painterly A/B strength (default 0.6; 0 = off)
#   bench/m1/hero.sh --regrade <run dir>     re-grade the EXRs and redraw the sheet
#
# Env: DATA (default <main checkout>/data), THREADS (default 16 for --final,
# 8 otherwise), HERO_VENDOR (Poly Haven textures, default <main>/data/vendor).
# Build the input with KEEP_BLEND=1 bench/m1/lookdev.sh --config bench/m1/variants/direction.json <label>.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
MAIN_ROOT="$(dirname "$(git -C "$REPO" rev-parse --path-format=absolute --git-common-dir)")"
DATA="${DATA:-$MAIN_ROOT/data}"
export HERO_VENDOR="${HERO_VENDOR:-$MAIN_ROOT/data/vendor}"
ROOT="$DATA/build/hero"
BL=(blender -b --factory-startup --python-exit-code 1)

grade_and_sheet() {
  local run="$1" paint="$2"
  local exrs=()
  for e in "$run"/exr/*.exr; do [[ -e "$e" ]] && exrs+=(--exr "$e"); done
  if [[ ${#exrs[@]} -gt 0 ]]; then
    "${BL[@]}" --python "$REPO/blender/hero/grade.py" -- "${exrs[@]}" --out "$run" --paint "$paint" \
      > "$run/grade.log" 2>&1 || { echo "grade failed: $run/grade.log" >&2; tail -20 "$run/grade.log" >&2; exit 1; }
  fi
  python3 -I "$REPO/blender/hero/sheet.py" "$run"
}

if [[ "${1:-}" == "--regrade" ]]; then
  RUN="$(cd "${2:?usage: $0 --regrade <run dir>}" && pwd)"
  grade_and_sheet "$RUN" "${PAINT:-0.6}"
  exit 0
fi

QUALITY=preview; STAGE_FAIL=; SHOTS=all; TT=(--turntable); SET=alley; PAINT=0.6; TTV=(); TTP=()
while [[ $# -gt 2 ]]; do
  case "$1" in
    --preview) QUALITY=preview; shift ;;
    --final)   QUALITY=final; shift ;;
    --draft)   QUALITY=draft; shift ;;
    --shots)   SHOTS="$2"; shift 2 ;;
    --no-turntable) TT=(); shift ;;
    --tt-views) TTV=(--tt-views "$2"); shift 2 ;;
    --tt-poses) TTP=(--tt-poses "$2"); shift 2 ;;
    --set)     SET="$2"; shift 2 ;;
    --paint)   PAINT="$2"; shift 2 ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
done
IN="$(realpath "${1:?usage: $0 [options] <character.blend> <label>}")"
LABEL="${2:?label}"
[[ "$LABEL" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "label: letters, digits, . _ - only" >&2; exit 2; }
[[ -f "$IN" ]] || { echo "no such file: $IN" >&2; exit 2; }
THREADS="${THREADS:-$([[ $QUALITY == final ]] && echo 16 || echo 8)}"

RUN="$ROOT/$(date -u +%Y%m%dT%H%M%SZ)-$LABEL"
mkdir -p "$RUN"
echo "== hero $LABEL quality=$QUALITY shots=$SHOTS set=$SET threads=$THREADS loadavg=$(cut -d' ' -f1-3 /proc/loadavg)"
T0=$(date +%s)
"${BL[@]}" -t "$THREADS" --python "$REPO/blender/hero/stage.py" -- --in "$IN" --out "$RUN" \
  --quality "$QUALITY" --shots "$SHOTS" --set "$SET" "${TT[@]}" "${TTV[@]}" "${TTP[@]}" \
  > "$RUN/stage.log" 2>&1 || STAGE_FAIL=1
grep -E '^\[stage\]' "$RUN/stage.log" || true
# grade and draw whatever was rendered, even after a failure or a kill
[[ -f "$RUN/stage.json" ]] && grade_and_sheet "$RUN" "$PAINT"
if [[ -n "${STAGE_FAIL:-}" ]]; then echo "stage failed: $RUN/stage.log" >&2; tail -20 "$RUN/stage.log" >&2; exit 1; fi
ln -sfn "$(basename "$RUN")" "$ROOT/latest"
echo "-> $RUN ($(( $(date +%s) - T0 )) s)"
