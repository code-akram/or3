#!/usr/bin/env bash
# Prepare the public face (m1 v4 T7, bench/m1/v4/t7-head.md): the MediaPipe landmark embeddings
# on the MPFB base mesh and on the ICT-FaceKit neutral, which head_layer (identity wrap) and
# head_sculpt (landmark-anchored fields) read. Once per base-mesh change; public data only.
#
#   bench/m1/identity.sh            # writes <main>/data/build/identity/{base,ict}_embedding.npz
#
# Needs: pipeline/likeness/fetch_ict.sh (ICT-FaceKit), the likeness venv (MediaPipe) and the
# face_landmarker.task model under data/vendor/mediapipe/. The landmarks are written to a mode-700
# temp dir and removed; only the embeddings (triangle + barycentric per landmark) are kept.
# After it, a build with bench/m1/variants/direction.json makes data/build/identity/public_face.npz
# itself (head.identity.auto).
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
MAIN="$(dirname "$(git -C "$REPO" rev-parse --path-format=absolute --git-common-dir)")"
DATA="$MAIN/data"
OUT="${IDENTITY_OUT:-$DATA/build/identity}"   # IDENTITY_OUT: a scratch dir for a dry run
PREP="$OUT/prep"
PY="$MAIN/private/venvs/likeness/bin/python"
MP="$DATA/vendor/mediapipe/face_landmarker.task"
ICT="$DATA/raw/ict-facekit"
AP="$REPO/pipeline/likeness/author_public.py"
export OMP_NUM_THREADS=3
mkdir -p "$PREP"
[[ -s "$ICT/COMMIT" ]] || "$REPO/pipeline/likeness/fetch_ict.sh"

# 1. the base mesh exactly as head_layer sees it (direction config, before the identity layer)
DUMP_CFG="$(mktemp --suffix=.json)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP" "$DUMP_CFG"' EXIT
printf '{"head": {"identity": {"dump_base": "%s", "delta": null}, "sculpt": null}}\n' "$PREP/base_dump.npz" > "$DUMP_CFG"
nice -n 10 blender -b -t 3 --factory-startup --python-exit-code 1 --python "$REPO/bench/m1/head_quick.py" -- \
  --system-assets "$DATA/raw/makehuman/makehuman_system_assets/unpacked" \
  --suit-assets "$DATA/raw/makehuman/suits01/unpacked" \
  --config "$REPO/bench/m1/variants/direction.json" --config "$DUMP_CFG" --out "$TMP/quick" > "$TMP/dump.log" 2>&1 \
  || { tail -20 "$TMP/dump.log" >&2; exit 1; }

# 2. landmarker meshes, views, landmarks, embeddings (base, then the ICT neutral)
embed() {   # name mesh.npz out_embedding.npz
  local views="$PREP/views_$1" lm
  lm="$(mktemp -d -p "$TMP")"
  chmod 700 "$lm"
  nice -n 10 blender -b -t 3 --factory-startup --python-exit-code 1 --python "$REPO/pipeline/likeness/mesh_views.py" -- \
    --mesh "$2" --out "$views" > "$TMP/views_$1.log" 2>&1 || { tail -20 "$TMP/views_$1.log" >&2; exit 1; }
  nice -n 10 "$PY" -I "$REPO/pipeline/likeness/refboard.py" measure --landmarker "$MP" --out-dir "$lm" "$views"/*.png > /dev/null
  nice -n 10 "$PY" -I "$AP" embed --mesh "$2" --views "$views" --landmarks "$lm" --out "$3"
}
nice -n 10 "$PY" -I "$AP" base-mesh --base "$PREP/base_dump.npz" --out "$PREP/base_mesh.npz"
embed base "$PREP/base_mesh.npz" "$OUT/base_embedding.npz"
nice -n 10 "$PY" -I "$AP" mesh --ict "$ICT" --out "$PREP/ict_neutral.npz"
embed ict_neutral "$PREP/ict_neutral.npz" "$OUT/ict_embedding.npz"
echo "OK: $OUT/base_embedding.npz $OUT/ict_embedding.npz"
