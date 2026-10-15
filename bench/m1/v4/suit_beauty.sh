#!/usr/bin/env bash
# Beauty frames for a suit spike run (m1 v4 T13): bench/m1/v4/suit_beauty.py under the
# machine's Cycles lock, 6 threads, nice 10. The lookdev base is the one the run used
# (RUN/base.txt), or --base.
#
#   bench/m1/v4/suit_beauty.sh [--base RUN] <spike run dir> [-- extra suit_beauty.py args]
#
# Writes RUN/beauty_*.png and RUN/beauty_sheet.png (lofted | pattern, labelled).
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../../.." && pwd)"
MAIN_ROOT="$(dirname "$(git -C "$REPO" rev-parse --path-format=absolute --git-common-dir)")"
DATA="${DATA:-$MAIN_ROOT/data}"
PRIVATE="$(realpath -m "$MAIN_ROOT/private")"
BASE=""
if [[ "${1:-}" == "--base" ]]; then BASE="$2"; shift 2; fi
RUN="$(realpath "${1:?usage: $0 [--base RUN] <spike run dir> [-- args]}")"; shift
[[ "${1:-}" == "--" ]] && shift
if [[ -z "$BASE" ]]; then
  BASE="$(cat "$RUN/base.txt")"
elif [[ ! -d "$BASE" ]]; then
  BASE="$DATA/build/lookdev/$BASE"
fi
BASE="$(realpath "$BASE")"
for p in "$BASE" "$RUN"; do
  [[ "$p" == "$PRIVATE"/* ]] && { echo "refusing private input: $p" >&2; exit 2; }
done
[[ -s "$RUN/spike.blend" && -s "$BASE/character.blend" ]] || { echo "need RUN/spike.blend and BASE/character.blend" >&2; exit 2; }
echo "== suit beauty run=$(basename "$RUN") base=$(basename "$BASE")"
flock /tmp/or3-cycles.lock nice -n 10 blender -b -t 6 --factory-startup "$RUN/spike.blend" \
  --python-exit-code 1 --python "$REPO/bench/m1/v4/suit_beauty.py" -- --base "$BASE/character.blend" --out "$RUN" "$@" \
  > "$RUN/beauty.log" 2>&1 || { echo "beauty failed: $RUN/beauty.log" >&2; tail -30 "$RUN/beauty.log" >&2; exit 1; }
grep '^\[beauty\]' "$RUN/beauty.log" || true
if command -v magick >/dev/null && [[ -f "$RUN/beauty_pattern_front.png" ]]; then
  FONT=/usr/share/fonts/noto/NotoSans-Bold.ttf
  [[ -f "$FONT" ]] || FONT=""
  rows=()
  for v in front three_quarter profile back; do
    [[ -f "$RUN/beauty_lofted_$v.png" ]] || continue
    magick "$RUN/beauty_lofted_$v.png" ${FONT:+-font "$FONT"} -gravity NorthWest -fill white -pointsize 34 \
      -annotate +18+12 "lofted | $v" "$RUN/_bl_$v.png"
    magick "$RUN/beauty_pattern_$v.png" ${FONT:+-font "$FONT"} -gravity NorthWest -fill white -pointsize 34 \
      -annotate +18+12 "pattern | $v" "$RUN/_bp_$v.png"
    magick "$RUN/_bl_$v.png" "$RUN/_bp_$v.png" +append "$RUN/_b_$v.png"; rows+=("$RUN/_b_$v.png")
  done
  [[ ${#rows[@]} -gt 0 ]] && magick "${rows[@]}" -append -resize 50% "$RUN/beauty_sheet.png"
  rm -f "$RUN"/_bl_*.png "$RUN"/_bp_*.png "$RUN"/_b_*.png
fi
if command -v magick >/dev/null && [[ -f "$RUN/beauty_grain_front.png" ]]; then
  FONT=/usr/share/fonts/noto/NotoSans-Bold.ttf
  [[ -f "$FONT" ]] || FONT=""
  cols=()
  for v in front three_quarter back; do
    magick "$RUN/beauty_grain_$v.png" ${FONT:+-font "$FONT"} -gravity NorthWest -fill white -pointsize 34 \
      -annotate +18+12 "grain | $v" "$RUN/_g_$v.png"; cols+=("$RUN/_g_$v.png")
  done
  magick "${cols[@]}" +append -resize 50% "$RUN/grain_sheet.png"
  rm -f "$RUN"/_g_*.png
fi
echo "$RUN"
