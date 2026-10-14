#!/usr/bin/env bash
# Fetch the ICT-FaceKit identity model (USC ICT, MIT licence) into <main checkout>/data/raw/ict-facekit/:
# the generic neutral mesh, the 100 identity blendshapes, the vertex-range index and the licence,
# pinned to one commit. No login. The public face prior of author_public.py (bench/m1/v4/t7-head.md).
#
#   pipeline/likeness/fetch_ict.sh
#
# The files are data, not code: nothing from the download is executed; parse them with python -I.
# FLAME 2023 Open (CC BY 4.0) would be the other public prior, but its download needs the
# flame.is.tue.mpg.de login (checked 2026-10-14), so it is not fetched here.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
MAIN="$(dirname "$(git -C "$REPO" rev-parse --path-format=absolute --git-common-dir)")"
SHA=da5f95a607f5e6b37755b38d3385d7f2853732e5            # ICT-VGL/ICT-FaceKit master, 2020-12-01
URL="https://raw.githubusercontent.com/ICT-VGL/ICT-FaceKit/$SHA"
OUT="$MAIN/data/raw/ict-facekit"

mkdir -p "$OUT/FaceXModel"
get() {   # skip files already present; a partial download never takes the final name
  [[ -s "$OUT/$1" ]] && return 0
  curl -fsSL --retry 3 -o "$OUT/$1.part" "$URL/$1"
  mv "$OUT/$1.part" "$OUT/$1"
}
get LICENSE
get README.md
get FaceXModel/generic_neutral_mesh.obj
get FaceXModel/vertex_indices.json
for i in $(seq -f '%03g' 0 99); do get "FaceXModel/identity$i.obj"; done
grep -q '^MIT License' "$OUT/LICENSE" || { echo "unexpected licence text in $OUT/LICENSE" >&2; exit 1; }
echo "$SHA" > "$OUT/COMMIT"
(cd "$OUT" && sha256sum LICENSE README.md FaceXModel/*.obj FaceXModel/vertex_indices.json > SHA256SUMS)
echo "OK: $OUT ($(ls "$OUT"/FaceXModel/identity*.obj | wc -l) identity shapes, commit ${SHA:0:12})"
