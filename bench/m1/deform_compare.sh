#!/usr/bin/env bash
# Before/after strip from two deform_test.sh outputs: for each POSE/TILE, the
# tile from A above the tile from B.
#   bench/m1/deform_compare.sh A_DIR B_DIR OUT.png pose/tile [pose/tile ...]
#   (tile = a PNG stem in A_DIR/<pose>/, e.g. arm_raise/armpit_l or knee_up/full_clay)
set -euo pipefail
A="$1"; B="$2"; OUT="$3"; shift 3
top=(); bot=()
for t in "$@"; do
  top+=(-label "before $t" "$A/$t.png")
  bot+=(-label "after $t" "$B/$t.png")
done
montage "${top[@]}" "${bot[@]}" -tile "$#x2" -geometry 384x384+2+2 -background '#111' -fill '#ddd' \
  -pointsize 13 "$OUT"
echo "$OUT"
