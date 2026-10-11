#!/usr/bin/env bash
# Spike 5, step 4: check the JGD2011 (EPSG:6697) -> EPSG:6677 projection.
#  a) our pure-Rust Krüger series (plateau-chunk project) vs the GSI's official
#     survey calculation web API (bl2xy, JGD2011, zone IX) for a few known points;
#  b) nusamai's glTF output vs our projection of the same GML vertices.
# Usage: bench/m0/spike5/verify-crs.sh
set -euo pipefail

ROOT=/home/akram/code/or3
REPO="$(cd "$(dirname "$0")/../../.." && pwd)"
BIN="$REPO/target/release/plateau-chunk"
cargo build --release -j3 -p plateau-chunk --manifest-path "$REPO/Cargo.toml" 2>/dev/null

# zone IX origin, Kabukicho (task reference point), Golden Gai, Shinjuku Station east exit
for p in "36.0 139.83333333333333" "35.6950 139.7030" "35.6941 139.7046" "35.6908 139.7006"; do
  set -- $p
  ours=$("$BIN" project "$1" "$2")
  gsi=$(curl -fsS "https://vldb.gsi.go.jp/sokuchi/surveycalc/surveycalc/bl2xy.pl?outputType=json&refFrame=2&zone=9&latitude=$1&longitude=$2" || echo '{}')
  jq -n --argjson o "$ours" --argjson g "$gsi" '{lat: $o.lat, lon: $o.lon,
     ours_E: $o.easting, ours_N: $o.northing,
     gsi_E: ($g.OutputData.publicY // null | tonumber? // null),
     gsi_N: ($g.OutputData.publicX // null | tonumber? // null)}
     | . + {dE_mm: (if .gsi_E then ((.ours_E - .gsi_E) * 1000 | round) else null end),
            dN_mm: (if .gsi_N then ((.ours_N - .gsi_N) * 1000 | round) else null end)}' -c
  sleep 1  # be polite to the GSI service
done

"$BIN" verify-crs \
  --gml "$ROOT/data/raw/plateau/13104-2025/extract/udx/bldg/53394536_bldg_6697_op.gml" \
  --glb "$ROOT/data/build/world/nusamai-53394536/bldg/bldg_Building.glb" --max 20000 2>/dev/null
