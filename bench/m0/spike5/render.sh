#!/usr/bin/env bash
# Spike 5, step 6: render check images of the chunk with headless Blender (Cycles CPU).
# Draws the spike-6 source (red) and listener (blue) if alley-01.json exists.
# Output: bench/m0/img/chunk-kabukicho-overview.png and chunk-kabukicho-alley.png
# (8-bit palette PNGs, small enough to commit).
#
# Usage: bench/m0/spike5/render.sh [threads]   (default 3)
set -euo pipefail

THREADS="${1:-3}"
ROOT=/home/akram/code/or3
REPO="$(cd "$(dirname "$0")/../../.." && pwd)"
CHUNK="$ROOT/data/build/world/chunk_e-11800_n-34000_s200.raw.glb"
IR_JSON="$ROOT/data/build/audio/ir/alley-01.json"
IMG="$REPO/bench/m0/img"
TMP="$(mktemp -d)"
mkdir -p "$IMG"

MARKERS=()
FOCUS=()
if [ -f "$IR_JSON" ]; then
  m=$(jq -r '"\(.source_local|join(","));\(.listener_local|join(","))"' "$IR_JSON")
  c=$(jq -r '.alley.center_local|join(",")' "$IR_JSON")
  MARKERS=(--markers "$m")
  FOCUS=(--focus "$c")
fi

echo "threads=$THREADS loadavg=$(cat /proc/loadavg)"
t0=$(date +%s%N)
blender -b --factory-startup --python "$REPO/blender/render_chunk.py" -- "$CHUNK" "$TMP/overview.png" \
  --threads "$THREADS" --samples 24 --width 1200 --height 750 "${MARKERS[@]}" >"$TMP/overview.log" 2>&1
t1=$(date +%s%N)
blender -b --factory-startup --python "$REPO/blender/render_chunk.py" -- "$CHUNK" "$TMP/alley.png" \
  --threads "$THREADS" --samples 24 --width 1000 --height 625 "${MARKERS[@]}" "${FOCUS[@]}" \
  --dist 45 --elevation 60 --azimuth -100 --marker-radius 0.5 >"$TMP/alley.log" 2>&1
t2=$(date +%s%N)
echo "overview render: $(( (t1 - t0) / 1000000 )) ms, alley render: $(( (t2 - t1) / 1000000 )) ms"

for n in overview alley; do
  ffmpeg -v error -y -i "$TMP/$n.png" -vf "split[a][b];[a]palettegen=max_colors=192[p];[b][p]paletteuse=dither=sierra2_4a" \
    "$IMG/chunk-kabukicho-$n.png"
done
ls -l "$IMG"
rm -rf "$TMP"
echo "loadavg_end=$(cat /proc/loadavg)"
