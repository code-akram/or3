#!/usr/bin/env bash
# Spike 6: bake the alley impulse response from the spike-5 chunk with Steam Audio 4.8.1.
#
# Usage: bench/m0/spike6/bake.sh [threads] [repeats]   (defaults: 3, 3)
# Needs: the SDK at data/raw/steam-audio/sdk (bench/m0/spike6/fetch-sdk.sh) and the chunk
#        from bench/m0/spike5/chunk.sh. Writes data/build/audio/ir/alley-01*.wav + .json.
set -euo pipefail

THREADS="${1:-3}"
REPEATS="${2:-3}"
ROOT=/home/akram/code/or3
REPO="$(cd "$(dirname "$0")/../../.." && pwd)"
CHUNK="$ROOT/data/build/world/chunk_e-11800_n-34000_s200.raw.glb"
OUT="$ROOT/data/build/audio/ir"
mkdir -p "$OUT"

cargo build --release -j3 -p acoustic-bake --manifest-path "$REPO/Cargo.toml" 2>/dev/null
echo "threads=$THREADS loadavg=$(cat /proc/loadavg)"

# The shipped bake (alley found automatically; 262144 rays, 64 bounces, 2 s, order 1).
"$REPO/target/release/acoustic-bake" --chunk "$CHUNK" --threads "$THREADS" \
  --out "$OUT/alley-01.wav" --report "$OUT/alley-01.json" >/dev/null 2>"$OUT/alley-01.log"
jq -c '{alley: .alley, drr_db, cal_db: .calibration.gain_applied_to_reflections_db,
        full: (.measure_full_mono | del(.early_profile_2ms_db)), trimmed_seconds,
        t20_bands: (.octave_bands_full_mono | map_values(.t20_s)), timings, loadavg}' "$OUT/alley-01.json"

# Repeatability: the ray tracer is stochastic, so re-run the same bake N times.
for i in $(seq 1 "$REPEATS"); do
  "$REPO/target/release/acoustic-bake" --chunk "$CHUNK" --threads "$THREADS" \
    --out "/tmp/alley-repeat-$i.wav" --report "/tmp/alley-repeat-$i.json" >/dev/null 2>&1
  jq -c '{run: .timings.full_scene.run_reflections_s, total: .timings.total_s, drr_db,
          edt: .measure_full_mono.edt_s, t20: .measure_full_mono.t20_s, t30: .measure_full_mono.t30_s,
          len: .trimmed_seconds}' "/tmp/alley-repeat-$i.json"
done
rm -f /tmp/alley-repeat-*.wav
echo "loadavg_end=$(cat /proc/loadavg)"
ls -l "$OUT"
