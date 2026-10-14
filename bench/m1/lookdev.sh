#!/usr/bin/env bash
# m1 look-dev loop: build the character, render the fixed views + silhouette
# masks, score them, draw a contact sheet. See bench/m1/README.md.
#
# Usage:
#   bench/m1/lookdev.sh [options] <label>        one run -> $DATA/build/lookdev/<UTC>-<label>/
#     --config FILE    JSON override for blender/character/config.py
#     --signoff        Cycles CPU 1024², 128 spp + OIDN instead of EEVEE 512², 16 samples
#     --target DIR     score masks against DIR/<view>_mask.png
#     --prev DIR|none  run to score against (default: the latest finished run)
#     --fan FILE       private fan build (passed to build_character.py as --fan; also
#                      taken from $FAN_CONFIG, which only this script reads)
#   bench/m1/lookdev.sh --compare A B             side-by-side sheet + metrics diff
#                                                 (A, B: run dirs, or names under lookdev/)
#
# Private runs: a run goes to <main>/private/likeness/lookdev/, never under data/
# (NOTES.md §14 rule 7, bench/m1/v3/BRIEF.md), when it has --fan / $FAN_CONFIG, a --config
# file carrying likeness content (a "fan" block or a private/likeness/ path) or any input
# (--config, --target, --prev) under private/. A compare goes there when either run is under
# private/ or its metrics.json carries likeness content or cannot be read (fails closed).
# build_character.py refuses a likeness build outside private/ on its own as well.
# Env: DATA (default: <main checkout>/data), THREADS (default 4; 16 for --signoff),
#      ENGINE_SHOTS=1 adds the engine frames (bench/m1/engine_shots.sh; minutes, off by default),
#      KEEP_BLEND=1 keeps the staged .blend of the build.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
MAIN_ROOT="$(dirname "$(git -C "$REPO" rev-parse --path-format=absolute --git-common-dir)")"
DATA="${DATA:-$MAIN_ROOT/data}"
ROOT="$DATA/build/lookdev"
PRIVATE="$(realpath -m "$MAIN_ROOT/private")"
PRIVATE_ROOT="$PRIVATE/likeness/lookdev"
REPORT=(python3 -I "$REPO/bench/m1/lookdev_report.py")
CONTAIN=(python3 -I "$REPO/pipeline/likeness/containment.py")
mkdir -p "$ROOT"

# A run dir (symlinks resolved): a path, else a name under data's lookdev/, then private's.
resolve() {
  local d
  for d in "$1" "$ROOT/$1" "$PRIVATE_ROOT/$1"; do [[ -d "$d" ]] && { realpath "$d"; return; }; done
  echo "$ROOT/$1"
}
private_path() { [[ "$(realpath -m "$1")" == "$PRIVATE"/* ]]; }

if [[ "${1:-}" == "--compare" ]]; then
  [[ $# -eq 3 ]] || { echo "usage: $0 --compare A B" >&2; exit 2; }
  A="$(resolve "$2")"; B="$(resolve "$3")"
  if private_path "$A" || private_path "$B" || ! "${CONTAIN[@]}" clean "$A/metrics.json" "$B/metrics.json"; then
    ROOT="$PRIVATE_ROOT"; mkdir -p "$ROOT"   # likeness content on either side: never under data/
  fi
  OUT="$ROOT/compare-$(basename "$A")--$(basename "$B")"
  echo "== compare -> $OUT"
  "${REPORT[@]}" compare "$A" "$B" --out "$OUT"
  exit 0
fi

MODE=loop; CONFIG=(); TARGET=(); PREV=auto; FAN="${FAN_CONFIG:-}"
while [[ $# -gt 1 ]]; do
  case "$1" in
    --signoff) MODE=signoff; shift ;;
    --config)  CONFIG=(--config "$(realpath "$2")"); shift 2 ;;
    --target)  TARGET=(--target "$(realpath "$2")"); shift 2 ;;
    --prev)    PREV="$2"; shift 2 ;;
    --fan)     FAN="$2"; shift 2 ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
done
LABEL="${1:?usage: $0 [options] <label>}"
[[ "$LABEL" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "label: letters, digits, . _ - only" >&2; exit 2; }
THREADS="${THREADS:-$([[ $MODE == signoff ]] && echo 16 || echo 4)}"
FAN_ARG=(); PRIV=
[[ -n "$FAN" ]] && { FAN_ARG=(--fan "$(realpath "$FAN")"); PRIV=fan; }
[[ ${#CONFIG[@]} -gt 0 ]] && { private_path "${CONFIG[1]}" || ! "${CONTAIN[@]}" clean "${CONFIG[1]}"; } && PRIV="${PRIV:-config}"
[[ ${#TARGET[@]} -gt 0 ]] && private_path "${TARGET[1]}" && PRIV="${PRIV:-target}"
case "$PREV" in auto|none) ;; *) PREV="$(resolve "$PREV")"; private_path "$PREV" && PRIV="${PRIV:-prev}" ;; esac
if [[ -n "$PRIV" ]]; then
  ROOT="$PRIVATE_ROOT"   # private likeness content: never under data/
  mkdir -p "$ROOT"
fi

# Latest finished run (timestamped dir with metrics.json), before this one starts.
latest() { find "$ROOT" -mindepth 1 -maxdepth 1 -type d -name '2*Z-*' -exec test -f '{}/metrics.json' ';' -print | sort | tail -1; }
case "$PREV" in
  auto) P="$(latest)" ;;
  none) P="" ;;
  *)    P="$PREV" ;;
esac
PREV_ARG=(); [[ -n "$P" ]] && PREV_ARG=(--prev "$P")

RUN="$ROOT/$(date -u +%Y%m%dT%H%M%SZ)-$LABEL"
if [[ -n "$PRIV" ]] && ! private_path "$RUN"; then echo "private input ($PRIV): refusing to write outside $PRIVATE ($RUN)" >&2; exit 2; fi
mkdir -p "$RUN"
T0=$(date +%s.%N)
echo "== lookdev $LABEL mode=$MODE threads=$THREADS${PRIV:+ private($PRIV)} prev=${P:+$(basename "$P")} loadavg=$(cut -d' ' -f1-3 /proc/loadavg)"

blender -b -t "$THREADS" --factory-startup --python-exit-code 1 --python "$REPO/blender/build_character.py" -- \
  --system-assets "$DATA/raw/makehuman/makehuman_system_assets/unpacked" \
  --suit-assets "$DATA/raw/makehuman/suits01/unpacked" \
  --out "$RUN/character.glb" "${CONFIG[@]}" "${FAN_ARG[@]}" > "$RUN/build.log" 2>&1 \
  || { echo "build failed: $RUN/build.log" >&2; tail -20 "$RUN/build.log" >&2; exit 1; }
[[ -s "$RUN/character.glb" ]] || { echo "build wrote no character.glb: $RUN/build.log" >&2; tail -20 "$RUN/build.log" >&2; exit 1; }
[[ "${KEEP_BLEND:-0}" == 1 ]] || rm -f "$RUN/character.blend"

# glTF validation + per-mesh weights (Khronos validator; needs the glb-stats npm deps).
GS="$REPO/bench/m0/glb-stats"
[[ -d "$GS/node_modules" ]] || { [[ -d "$MAIN_ROOT/bench/m0/glb-stats/node_modules" ]] && GS="$MAIN_ROOT/bench/m0/glb-stats"; }
[[ -d "$GS/node_modules" ]] || npm install --prefix "$GS" --no-fund --no-audit >/dev/null
node "$GS/glb_stats.mjs" "$RUN/character.glb" --json "$RUN/glbstats.json" > /dev/null \
  || echo "warning: glTF validator reported errors (see $RUN/glbstats.json)" >&2

blender -b -t "$THREADS" --factory-startup --python-exit-code 1 --python "$REPO/blender/lookdev_render.py" -- \
  --glb "$RUN/character.glb" --out-dir "$RUN" --mode "$MODE" "${PREV_ARG[@]}" "${TARGET[@]}" \
  > "$RUN/render.log" 2>&1 \
  || { echo "render failed: $RUN/render.log" >&2; tail -20 "$RUN/render.log" >&2; exit 1; }
[[ -s "$RUN/render_metrics.json" ]] || { echo "render wrote no metrics: $RUN/render.log" >&2; tail -20 "$RUN/render.log" >&2; exit 1; }

# Engine frames (T5): game_<view>.png from the web viewer, written into $RUN only (private for --fan).
# Off by default: SwiftShader takes minutes per run on this machine. ENGINE_SHOTS=1 turns it on.
if [[ "${ENGINE_SHOTS:-0}" == 1 ]]; then
  "$REPO/bench/m1/engine_shots.sh" "$RUN" || echo "warning: engine shots failed ($RUN/engine_shots.log)" >&2
fi

T1=$(date +%s.%N)
"${REPORT[@]}" finalize "$RUN" --label "$LABEL" --process-s "$(python3 -I -c "print(round($T1-$T0,2))")"
ln -sfn "$(basename "$RUN")" "$ROOT/latest"
echo "-> $RUN/sheet.png"
