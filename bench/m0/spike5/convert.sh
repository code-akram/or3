#!/usr/bin/env bash
# Spike 5, step 3: convert one PLATEAU 3rd-level mesh cell (1 km) with nusamai's glTF sink.
# Output CRS EPSG:6677 (JGD2011 / Japan Plane Rectangular CS IX), absolute coordinates
# (center_at_origin=false) so plateau-chunk can re-origin onto a fixed grid.
#
# Usage: bench/m0/spike5/convert.sh [threads]   (default 3)
# Needs: nusamai built at data/raw/nusamai/src/target/release/nusamai, the extracted cell at
#        data/raw/plateau/13104-2025/extract (see bench/m0/spike-5-plateau.md).
set -euo pipefail

THREADS="${1:-3}"
ROOT=/home/akram/code/or3
NUSAMAI="$ROOT/data/raw/nusamai/src/target/release/nusamai"
SRC="$ROOT/data/raw/plateau/13104-2025/extract/udx"
OUT="$ROOT/data/build/world/nusamai-53394536"
MESH=53394536

mkdir -p "$OUT"
echo "threads=$THREADS loadavg=$(cat /proc/loadavg)"
for layer in bldg tran frn veg; do
  gml="$SRC/$layer/${MESH}_${layer}_6697_op.gml"
  [ -f "$gml" ] || { echo "skip $layer (no file)"; continue; }
  start=$(date +%s%N)
  RAYON_NUM_THREADS="$THREADS" RUST_LOG=warn "$NUSAMAI" "$gml" \
    --sink gltf --output "$OUT/$layer" --epsg 6677 \
    -o center_at_origin=false -t use_lod=max_lod >"$OUT/$layer.log" 2>&1 || {
      echo "$layer FAILED, see $OUT/$layer.log"; continue; }
  end=$(date +%s%N)
  printf '%s  gml=%s  wall=%.1fs  out=%s\n' "$layer" "$(du -h "$gml" | cut -f1)" \
    "$(( (end - start) / 1000000 ))e-3" "$(du -ch "$OUT/$layer"/*.glb | tail -1 | cut -f1)"
  ls -la "$OUT/$layer"
done
echo "loadavg_end=$(cat /proc/loadavg)"
