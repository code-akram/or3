#!/usr/bin/env bash
# Frame-accurate cut of one shot (inclusive frame range) into private/footage/clips/.
# Usage: cut-shot.sh SOURCE START_FRAME END_FRAME OUT_NAME
set -euo pipefail
src=$1 start=$2 end=$3 name=$4
out_dir="${MAIN_ROOT:-/home/akram/code/or3}/private/footage/clips"
mkdir -p "$out_dir"
ffmpeg -v error -y -i "$src" \
  -vf "select='between(n\,$start\,$end)',setpts=N/FRAME_RATE/TB" -an \
  -c:v libx264 -crf 14 -preset slow -pix_fmt yuv420p "$out_dir/$name.mp4"
ffprobe -v error -count_frames -select_streams v:0 \
  -show_entries stream=width,height,r_frame_rate,nb_read_frames -of csv=p=0 "$out_dir/$name.mp4"
