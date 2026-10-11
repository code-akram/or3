#!/usr/bin/env bash
# Audio pipeline driver (NOTES.md §12). Run from anywhere.
#
#   pipeline/audio/run.sh all       fetch -> analyse -> clean -> loop -> footsteps -> spatialise -> master -> page -> audit
#   pipeline/audio/run.sh spatial   rerun from the IR onwards (use this when data/build/audio/ir/alley-01.wav changes)
#   pipeline/audio/run.sh build     everything after fetch (no network)
#
# Data lives in the main checkout's data/ (raw/audio, build/audio); override with AUDIO_DATA_ROOT.
# Freesound tokens are read from the repo .env inside Python and never printed.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
data="${AUDIO_DATA_ROOT:-$(dirname "$(git -C "$here" rev-parse --path-format=absolute --git-common-dir)")/data}"
py() { uv run --project "$here" python -I -m "audiopipe.$1" "${@:2}"; }
stage="${1:-build}"

echo "loadavg before: $(cat /proc/loadavg)"
start=$(date +%s)
case "$stage" in
  all)     py fetch ;&
  build)   py analyse; py clean; py loop
           py footsteps
           py footsteps --source freesound-205748 --name dress-concrete-contactmic --profile contact ;&
  spatial) py spatialise; py master; py page ;;
  *) echo "usage: $0 all|build|spatial" >&2; exit 2 ;;
esac
python3 -I "$repo/provenance/audit.py" --data-root "$data" --check-files
echo "stage '$stage' done in $(( $(date +%s) - start )) s; loadavg after: $(cat /proc/loadavg)"
