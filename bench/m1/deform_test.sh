#!/usr/bin/env bash
# Deformation test: pose the character through the canonical poses, render the
# joint close-ups, count poke-through per layer, draw one contact sheet per pose.
# See bench/m1/deform_test.py and bench/m1/v2/deform.md.
#
#   bench/m1/deform_test.sh RUN_DIR [label] [-- extra deform_test.py args]
#     RUN_DIR   a lookdev run (character.glb, character.rig.json) or a GLB path
#   Out: RUN_DIR/deform-<label>/ (sheet_<pose>.png, poke.json, per-pose tiles)
# Env: THREADS (default 4).
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
SRC="${1:?usage: $0 RUN_DIR|GLB [label] [-- args]}"; shift
LABEL="default"
if [[ $# -gt 0 && "$1" != "--" ]]; then LABEL="$1"; shift; fi
[[ "${1:-}" == "--" ]] && shift
if [[ -d "$SRC" ]]; then GLB="$SRC/character.glb"; RUN="$SRC"; else GLB="$SRC"; RUN="$(dirname "$SRC")"; fi
OUT="$RUN/deform-$LABEL"
mkdir -p "$OUT"
blender -b -t "${THREADS:-4}" --factory-startup --python-exit-code 1 \
  --python "$REPO/bench/m1/deform_test.py" -- --glb "$GLB" --out-dir "$OUT" "$@" \
  > "$OUT/deform.log" 2>&1 || { tail -30 "$OUT/deform.log" >&2; exit 1; }
grep '^\[deform\]' "$OUT/deform.log"
[[ -s "$OUT/tiles.txt" ]] || exit 0
for pose in $(cut -f1 "$OUT/tiles.txt" | uniq); do
  args=()
  while IFS=$'\t' read -r p label path; do
    [[ "$p" == "$pose" ]] || continue
    args+=(-label "$label" "$path")
  done < "$OUT/tiles.txt"
  montage "${args[@]}" -tile 8x -geometry 384x384+2+2 -background '#111' -fill '#ddd' \
    -pointsize 14 -title "$pose ($LABEL)" "$OUT/sheet_$pose.png"
done
echo "-> $OUT"
