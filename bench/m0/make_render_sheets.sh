#!/usr/bin/env bash
# Downscale spike-2 renders into small committed PNGs under bench/m0/renders/.
# Usage: bench/m0/make_render_sheets.sh   (env DATA as in the bench scripts)
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
DATA="${DATA:-$REPO/data}"
R="$DATA/build/renders"
OUT="$REPO/bench/m0/renders"
mkdir -p "$OUT"
ff() { ffmpeg -loglevel error -y "$@"; }

# Reference turntable: Cycles 128 spp + OIDN, 512 px each.
for v in front three_quarter profile closeup; do
  ff -i "$R/cycles128_oidn/$v.png" -vf scale=512:512 "$OUT/cycles128_oidn_$v.png"
done

# Same close-up across engines/configs (1:1 232 px crop of the 1024 frame around the eye,
# so noise and denoiser smearing stay visible): 2 rows x 3.
crop="crop=232:232:300:370"
ff -i "$R/cycles128_oidn/closeup.png" -i "$R/cycles128_raw/closeup.png" \
   -i "$R/cycles32_oidn/closeup.png" -i "$R/eevee_radeonsi/closeup.png" \
   -i "$R/eevee_llvmpipe/closeup.png" -i "$R/cycles32_oidn_fast/closeup.png" \
   -filter_complex "[0]$crop[a];[1]$crop[b];[2]$crop[c];\
[3]$crop[d];[4]$crop[e];[5]$crop[f];\
[a][b][c]hstack=inputs=3[top];[d][e][f]hstack=inputs=3[bot];[top][bot]vstack" \
   "$OUT/compare_closeup_crops.png"

# Skinning stress pose (EEVEE), cropped to the figure.
ff -i "$R/pose_check/pose_front.png" -i "$R/pose_check/pose_three_quarter.png" \
   -filter_complex "[0]crop=320:440:160:120[a];[1]crop=320:440:160:120[b];[a][b]hstack" \
   "$OUT/pose_check.png"
ls -l "$OUT"
