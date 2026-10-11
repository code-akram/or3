#!/usr/bin/env bash
# Spike 5, step 1: fetch PLATEAU Shinjuku-ku (13104) FY2025 CityGML + index map, verify,
# and extract the Kabukicho cell (3rd-level mesh 53394536) plus codelists/metadata.
# Also counts LOD1/LOD2 buildings per cell for the starting-district meshes.
#
# Usage: bench/m0/spike5/fetch.sh
# Source: https://www.geospatial.jp/ckan/dataset/plateau-13104-shinjuku-ku-2025
# Licence: PLATEAU Site Policy §3 (CC BY 4.0 compatible). Credit: 出典：国土交通省 PLATEAU
set -euo pipefail

ROOT=/home/akram/code/or3
DIR="$ROOT/data/raw/plateau/13104-2025"
ZIP_URL=https://assets.cms.plateau.reearth.io/assets/db/2866b9-e3c2-4bc4-83d3-b7b42e9b85a1/13104_shinjuku-ku_pref_2025_citygml_1_op.zip
PDF_URL=https://assets.cms.plateau.reearth.io/assets/78/53ad93-07eb-438e-b822-51ecf507c969/13104_indexmap_op.pdf
ZIP_SHA256=3a936966bae01051787fd2039319237cedc8d7a0ae838c10d30c222f586a7282  # 772,888,884 bytes, fetched 2026-10-12
MESH=53394536

mkdir -p "$DIR"
cd "$DIR"
t0=$(date +%s)
[ -f "${ZIP_URL##*/}" ] || curl -fsSL -o "${ZIP_URL##*/}" "$ZIP_URL"
[ -f "${PDF_URL##*/}" ] || curl -fsSL -o "${PDF_URL##*/}" "$PDF_URL"
echo "$ZIP_SHA256  ${ZIP_URL##*/}" | sha256sum -c -
t1=$(date +%s)
echo "download+verify: $((t1 - t0)) s"

mkdir -p extract
bsdtar -xf "${ZIP_URL##*/}" -C extract 'codelists/*' 'metadata/*' README.md 'specification/*' \
  "udx/bldg/${MESH}_bldg_6697_op.gml" "udx/tran/${MESH}_tran_6697_op.gml" \
  "udx/frn/${MESH}_frn_6697_op.gml" "udx/veg/${MESH}_veg_6697_op.gml"
t2=$(date +%s)
echo "extract: $((t2 - t1)) s"

# LOD coverage per cell of the starting district (Kabukicho, Golden Gai, Omoide Yokocho,
# station east side), streamed straight out of the zip.
printf '%-10s %8s %8s %6s\n' mesh bldgs lod2 share
for m in 53394525 53394526 53394535 53394536; do
  counts=$(bsdtar -xOf "${ZIP_URL##*/}" "udx/bldg/${m}_bldg_6697_op.gml" |
    grep -cE '<bldg:Building gml:id=|<bldg:lod2Solid>' || true)
  b=$(bsdtar -xOf "${ZIP_URL##*/}" "udx/bldg/${m}_bldg_6697_op.gml" | grep -c '<bldg:Building gml:id=' || true)
  l2=$((counts - b))
  printf '%-10s %8d %8d %5d%%\n' "$m" "$b" "$l2" $((100 * l2 / (b > 0 ? b : 1)))
done
