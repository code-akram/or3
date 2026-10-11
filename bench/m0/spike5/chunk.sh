#!/usr/bin/env bash
# Spike 5, steps 4-5: cut one 200 m chunk (EPSG:6677 grid) out of the nusamai output,
# re-origin it to the chunk centre (Y-up), then meshopt-compress it with glTF-Transform.
#
# Chunk: E [-11800, -11600) x N [-34000, -33800) in EPSG:6677 (JGD2011 / JPR CS IX).
#        Covers central Kabukicho 1-chome incl. Golden Gai. Named by its SW corner.
# Usage: bench/m0/spike5/chunk.sh   (run convert.sh first)
set -euo pipefail

ROOT=/home/akram/code/or3
REPO="$(cd "$(dirname "$0")/../../.." && pwd)"
IN="$ROOT/data/build/world/nusamai-53394536"
OUT="$ROOT/data/build/world"
GML="$ROOT/data/raw/plateau/13104-2025/extract/udx/bldg/53394536_bldg_6697_op.gml"
NAME="chunk_e-11800_n-34000_s200"
GT_VERSION=4.5.1   # @gltf-transform/cli

echo "threads=1 (plateau-chunk is single-threaded) loadavg=$(cat /proc/loadavg)"
cargo build --release -j3 -p plateau-chunk --manifest-path "$REPO/Cargo.toml" 2>/dev/null

t0=$(date +%s%N)
"$REPO/target/release/plateau-chunk" chunk \
  --min-e -11800 --min-n -34000 --size 200 \
  --gml "$GML" \
  --layer "whole:bldg:$IN/bldg/bldg_Building.glb" \
  --layer "clip:tran:$IN/tran/tran_Road.glb" \
  --layer "clip:frn:$IN/frn/frn_CityFurniture.glb" \
  --out "$OUT/$NAME.raw.glb" --meta "$OUT/$NAME.meta.json" > "$OUT/$NAME.summary.json"
t1=$(date +%s%N)
echo "chunk cut: $(( (t1 - t0) / 1000000 )) ms"

# meshopt: quantise + EXT_meshopt_compression (filter + gzip-friendly). Keep extras.
npx -y "@gltf-transform/cli@$GT_VERSION" meshopt "$OUT/$NAME.raw.glb" "$OUT/$NAME.glb" --level medium >/dev/null
t2=$(date +%s%N)
echo "meshopt: $(( (t2 - t1) / 1000000 )) ms (includes npx start-up)"

ls -l "$OUT/$NAME.raw.glb" "$OUT/$NAME.glb"
gzip -9 -c "$OUT/$NAME.glb" | wc -c | xargs echo "meshopt+gzip bytes:"
gzip -9 -c "$OUT/$NAME.raw.glb" | wc -c | xargs echo "raw+gzip bytes:"
cat "$OUT/$NAME.summary.json"
echo "loadavg_end=$(cat /proc/loadavg)"
