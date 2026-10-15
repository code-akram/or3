#!/usr/bin/env bash
# m1 v2 hero stage: render the hero shot list (neon-noir alley, Cycles CPU +
# OIDN), grade it, render the honesty turntable, draw a contact sheet.
# See bench/m1/v2/hero-stage.md.
#
# Usage:
#   bench/m1/hero.sh [options] <character.blend|.glb> <label>
#       -> $DATA/build/hero/<UTC>-<label>/
#       -> <main>/private/likeness/hero/<UTC>-<label>/ for a fan build (private: see
#          bench/m1/v3/BRIEF.md). A fan build is detected from its stats.json
#          (likeness content: a "fan" block or a private/likeness/ path), from an
#          input under private/, or from FAN_CONFIG / --fan; its runs never go under
#          data/. Fails closed: an input without a readable <stem>.stats.json next to
#          it is treated as a fan build.
#     --preview          (default) 50 % resolution, 64 spp adaptive
#     --final            100 % (1920x1080, 1152x2048 poster, 1080x1620 turntable), 256 spp adaptive 0.02
#     --max              100 %, 768 spp adaptive 0.012 (single hero frames; ~3x --final)
#     --pct N            resolution % override (e.g. --pct 100 at preview samples)
#     --draft            25 %, 16 spp: a framing / pose check in a few seconds per shot
#     --shots LIST       comma list from blender/hero/shots.py (default all), or none
#     --no-turntable     skip the turntable
#     --tt-views LIST    turntable views (default tt0,...,tt315)
#     --tt-poses LIST    turntable poses (default rest,stand)
#     --set alley|void   the alley (default) or the bare hero rig on black
#     --paint F          painterly A/B strength (default 0.6; 0 = off)
#     --crop LIST|close  also render a 100 % crop (half the frame each way) around the
#                        eye / focus point of these shots ('close' = portrait,profile,hands,eye)
#     --into RUN         add to an existing run dir (stage.json merged; e.g. the turntable
#                        at another thread count)
#     --fan              treat the input as a fan build (private output); normally detected
#     --no-hair-rim      saturated hero lights light the hair at full saturation (rig.HAIR_RIM off)
#     --parity           engine-parity variant (bench/m1/v4/checkpoint-1.md §1.3 #5): void set, no
#                        haze/rain/beads/wet hair, DoF off, 1 px filter, grade without bloom,
#                        halation, dispersion, grain or paint; implies --no-turntable and --set void.
#                        Default shots: portrait. 64 spp (preview samples) at --pct 100 unless given.
#     --wb K             grade white point in K (default: grade.py GRADE wb_kelvin, 3900; 0 = off;
#                        with --regrade pass it as WB=K in the environment)
#   bench/m1/hero.sh --regrade <run dir>     re-grade the EXRs and redraw the sheet
#
# Env: DATA (default <main checkout>/data), THREADS (default 16 for --final,
# 8 otherwise), HERO_VENDOR (Poly Haven textures, default <main>/data/vendor),
# ENGINE_SHOTS (default 1): when the input sits in a look-dev run dir (character.glb next to it),
# also capture the engine frames and draw engine_sheet.png / regression_strip.png against this run's
# portrait, in <hero run>/engine/ (bench/m1/engine_shots.sh); 0 skips it. hero.sh writes only into its
# own hero run: the source look-dev run is read through explicit symlinks to its input files and is
# never written, so a render for one track cannot overwrite another track's sheets.
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
      ${WB:+--wb "$WB"} ${PARITY:+--parity} \
      > "$run/grade.log" 2>&1 || { echo "grade failed: $run/grade.log" >&2; tail -20 "$run/grade.log" >&2; exit 1; }
  fi
  python3 -I "$REPO/blender/hero/sheet.py" "$run"
}

if [[ "${1:-}" == "--regrade" ]]; then
  RUN="$(cd "${2:?usage: $0 --regrade <run dir>}" && pwd)"
  grade_and_sheet "$RUN" "${PAINT:-0.6}"
  exit 0
fi

FAN=; HAIR_RIM=on; PARITY=
QUALITY=preview; STAGE_FAIL=; SHOTS=all; TT=(--turntable); SET=alley; PAINT=0.6; TTV=(); TTP=(); CROP=none; PCT=()
while [[ $# -gt 2 ]]; do
  case "$1" in
    --preview) QUALITY=preview; shift ;;
    --final)   QUALITY=final; shift ;;
    --max)     QUALITY=max; shift ;;
    --pct)     PCT=(--pct "$2"); shift 2 ;;
    --draft)   QUALITY=draft; shift ;;
    --shots)   SHOTS="$2"; shift 2 ;;
    --no-turntable) TT=(); shift ;;
    --tt-views) TTV=(--tt-views "$2"); shift 2 ;;
    --tt-poses) TTP=(--tt-poses "$2"); shift 2 ;;
    --set)     SET="$2"; shift 2 ;;
    --paint)   PAINT="$2"; shift 2 ;;
    --crop)    CROP="$2"; shift 2 ;;
    --wb)      export WB="$2"; shift 2 ;;
    --into)    INTO="$2"; shift 2 ;;
    --fan)     FAN=1; shift ;;
    --no-hair-rim) HAIR_RIM=off; shift ;;
    --parity)  PARITY=1; shift ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
done
if [[ -n "$PARITY" ]]; then
  TT=(); SET=void; PAINT=0
  [[ "$SHOTS" == all ]] && SHOTS=portrait
  [[ ${#PCT[@]} -eq 0 && "$QUALITY" == preview ]] && PCT=(--pct 100)
fi
IN="$(realpath "${1:?usage: $0 [options] <character.blend> <label>}")"
LABEL="${2:?label}"
[[ "$LABEL" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "label: letters, digits, . _ - only" >&2; exit 2; }
[[ -f "$IN" ]] || { echo "no such file: $IN" >&2; exit 2; }
THREADS="${THREADS:-$([[ $QUALITY == final || $QUALITY == max ]] && echo 16 || echo 8)}"

# Fan builds (private likeness content) render under private/, never data/.
# Fails closed: a missing, unreadable or malformed stats file counts as a fan build.
PRIVATE="$(realpath -m "$MAIN_ROOT/private")"
STATS="${IN%.*}.stats.json"
if [[ -z "$FAN" ]]; then
  [[ -n "${FAN_CONFIG:-}" || "$IN" == "$PRIVATE"/* ]] && FAN=1
  if [[ -z "$FAN" ]] && ! python3 -I "$REPO/pipeline/likeness/containment.py" clean "$STATS"; then
    echo "hero: treating $IN as a fan build (private output)" >&2
    FAN=1
  fi
fi
[[ -n "$FAN" ]] && ROOT="$PRIVATE/likeness/hero"
RUN="$ROOT/$(date -u +%Y%m%dT%H%M%SZ)-$LABEL"
[[ -n "${INTO:-}" ]] && RUN="$(cd "$INTO" && pwd -P)"   # add to an existing run (stage.json is merged); symlinks resolved
if [[ -n "$FAN" && "$(realpath -m "$RUN")" != "$PRIVATE"/* ]]; then echo "fan build: refusing to write outside $PRIVATE ($RUN)" >&2; exit 2; fi
# The input's own (real) directory is the source run: hero outputs never go in or under it.
SRC_RUN="$(dirname "$IN")"
RUN_REAL="$(realpath -m "$RUN")"
if [[ "$RUN_REAL" == "$SRC_RUN" || "$RUN_REAL" == "$SRC_RUN"/* ]]; then
  echo "hero: refusing to write into the source run $SRC_RUN (output $RUN_REAL)" >&2; exit 2
fi
mkdir -p "$RUN"
echo "== hero $LABEL quality=$QUALITY shots=$SHOTS set=$SET threads=$THREADS${FAN:+ fan(private)} loadavg=$(cut -d' ' -f1-3 /proc/loadavg)"
T0=$(date +%s)
"${BL[@]}" -t "$THREADS" --python "$REPO/blender/hero/stage.py" -- --in "$IN" --out "$RUN" \
  --quality "$QUALITY" --shots "$SHOTS" --set "$SET" --crop "$CROP" --hair-rim "$HAIR_RIM" "${PCT[@]}" "${TT[@]}" "${TTV[@]}" "${TTP[@]}" \
  ${PARITY:+--parity} \
  >> "$RUN/stage.log" 2>&1 || STAGE_FAIL=1
grep -E '^\[stage\]' "$RUN/stage.log" || true
# grade and draw whatever was rendered, even after a failure or a kill
[[ -f "$RUN/stage.json" ]] && grade_and_sheet "$RUN" "$PAINT"
if [[ -n "${STAGE_FAIL:-}" ]]; then echo "stage failed: $RUN/stage.log" >&2; tail -20 "$RUN/stage.log" >&2; exit 1; fi
ln -sfn "$(basename "$RUN")" "$ROOT/latest"
echo "-> $RUN ($(( $(date +%s) - T0 )) s)"

# Engine frames for the same build, in <this hero run>/engine/ (a fan build's run is private, and so
# is this dir), then engine_sheet.png and regression_strip.png there against this portrait. Nothing is
# written into the source run $SRC_RUN: engine/ gets symlinks to the source's input files only (glb,
# rig, stats, material params, shader balls, EEVEE views), each made to the resolved source path, and
# every file written lands under engine/ as a fresh regular file. Stale symlinks in engine/ (an earlier
# --into) are removed first so no output name can be a link back into any run.
if [[ "${ENGINE_SHOTS:-1}" == 1 && -s "$SRC_RUN/character.glb" && -f "$RUN/portrait.png" ]]; then
  ENG="$RUN/engine"
  [[ -L "$ENG" ]] && rm -f "$ENG"
  mkdir -p "$ENG"
  ENG="$(cd "$ENG" && pwd -P)"
  if [[ "$ENG" != "$(cd "$RUN" && pwd -P)/engine" || "$ENG" == "$SRC_RUN"/* ]]; then
    echo "hero: engine dir $ENG is not inside the hero run; refusing" >&2; exit 2
  fi
  [[ -n "$FAN" ]] && { python3 -I "$REPO/pipeline/likeness/containment.py" check "$ENG" || exit 2; }
  find "$ENG" -mindepth 1 -maxdepth 1 -type l -delete
  for f in "$SRC_RUN"/*; do
    [[ -f "$f" ]] || continue
    b="$(basename "$f")"
    [[ "$b" =~ ^(character\.(glb|ktx2\.glb|rig\.json|stats\.json)|material_params\.json|suit_detail\.json|suit_twill_detail\.png|shader_balls\.(glb|json)|skin_(head|hands)_(curvature|detail)\.png|skin_detail\.json|skin_detail_(pore|micro)\.png|cycles_balls\.png|(front|three_quarter|profile|closeup)\.png)$ ]] || continue
    ln -s "$(realpath "$f")" "$ENG/$b"
  done
  if "$REPO/bench/m1/engine_shots.sh" "$ENG"; then
    python3 -I "$REPO/bench/m1/lookdev_report.py" engine "$ENG" --cycles "$RUN" --build "$DATA/build" \
      || echo "warning: engine sheet failed" >&2
  else
    echo "warning: engine shots failed ($ENG/engine_shots.log)" >&2
  fi
fi
