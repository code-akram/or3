#!/usr/bin/env bash
# Suit pattern spike (m1 v4 step 5): bench/m1/v4/suit_spike.py with the data paths filled in.
#
#   bench/m1/v4/suit_spike.sh [--base RUN] [--config FILE] <label> [-- extra suit_spike.py args]
#
# RUN: a lookdev run dir (or a name under data/build/lookdev/) with a kept character.blend
# (KEEP_BLEND=1 bench/m1/lookdev.sh ...); default: the newest public one that has it.
# Output: data/build/suit_spike/<UTC>-<label>/. Public build only: --fan is not accepted, and a
# config or base under private/ is refused.
# Env: THREADS (default 3). Runs at nice 10.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../../.." && pwd)"
MAIN_ROOT="$(dirname "$(git -C "$REPO" rev-parse --path-format=absolute --git-common-dir)")"
DATA="${DATA:-$MAIN_ROOT/data}"
PRIVATE="$(realpath -m "$MAIN_ROOT/private")"
CONFIG="$REPO/bench/m1/variants/direction.json"
BASE=""
while [[ $# -gt 0 && "$1" == --* && "$1" != "--" ]]; do
  case "$1" in
    --base)   BASE="$2"; shift 2 ;;
    --config) CONFIG="$(realpath "$2")"; shift 2 ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
done
LABEL="${1:?usage: $0 [--base RUN] [--config FILE] <label> [-- args]}"; shift
[[ "$LABEL" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "label: letters, digits, . _ - only" >&2; exit 2; }
[[ "${1:-}" == "--" ]] && shift
if [[ -z "$BASE" ]]; then
  BASE="$(find "$DATA/build/lookdev" -mindepth 2 -maxdepth 2 -path '*/2*Z-*/character.blend' -printf '%h\n' | sort | tail -1)"
elif [[ ! -d "$BASE" ]]; then
  BASE="$DATA/build/lookdev/$BASE"
fi
BASE="$(realpath "$BASE")"
for p in "$BASE" "$CONFIG"; do
  [[ "$p" == "$PRIVATE"/* ]] && { echo "refusing private input: $p" >&2; exit 2; }
done
[[ -s "$BASE/character.blend" ]] || { echo "no character.blend in $BASE" >&2; exit 2; }
OUT="$DATA/build/suit_spike/$(date -u +%Y%m%dT%H%M%SZ)-$LABEL"
mkdir -p "$OUT"
echo "== suit spike $LABEL base=$(basename "$BASE") out=$OUT loadavg=$(cut -d' ' -f1-3 /proc/loadavg)"
nice -n 10 blender -b -t "${THREADS:-3}" --factory-startup --python-exit-code 1 \
  --python "$REPO/bench/m1/v4/suit_spike.py" -- \
  --system-assets "$DATA/raw/makehuman/makehuman_system_assets/unpacked" \
  --suit-assets "$DATA/raw/makehuman/suits01/unpacked" \
  --config "$CONFIG" --base-blend "$BASE/character.blend" --out-dir "$OUT" "$@" \
  > "$OUT/spike.log" 2>&1 || { echo "spike failed: $OUT/spike.log" >&2; grep -v '^\[INFO\|^\[DEBUG' "$OUT/spike.log" | tail -30 >&2; exit 1; }
grep '^\[spike\]' "$OUT/spike.log" || true
# A/B sheets: lofted (left) vs pattern (right), one row per view
if command -v magick >/dev/null && [[ -f "$OUT/pattern_front.png" ]]; then
  rows=()
  for v in front three_quarter profile back; do
    magick "$OUT/lofted_$v.png" "$OUT/pattern_$v.png" +append "$OUT/_ab_$v.png"; rows+=("$OUT/_ab_$v.png")
  done
  magick "${rows[@]}" -append -resize 50% "$OUT/ab_sheet.png"
  if [[ -f "$OUT/pattern_bent_front.png" ]]; then
    rows=()
    for v in front three_quarter profile; do
      magick "$OUT/lofted_bent_$v.png" "$OUT/pattern_bent_$v.png" +append "$OUT/_abb_$v.png"; rows+=("$OUT/_abb_$v.png")
    done
    magick "${rows[@]}" -append -resize 50% "$OUT/ab_bent_sheet.png"
  fi
  rm -f "$OUT"/_ab_*.png "$OUT"/_abb_*.png
  rsvg-convert -w 1400 -b white "$OUT/pattern.svg" -o "$OUT/pattern.png" 2>/dev/null || true
fi
echo "$OUT"
