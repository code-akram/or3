#!/usr/bin/env bash
# N concurrent bench processes x T threads each (bf16 ViTs) on one clip: aggregate throughput.
# Usage: concurrency-bench.sh N T [CLIP]   e.g. concurrency-bench.sh 2 4
# Prints wall seconds and aggregate s/frame (wall / (N x frames)). Run on an idle machine.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
main_root="${MAIN_ROOT:-/home/akram/code/or3}"
n=$1 t=$2
clip="${3:-$main_root/private/footage/clips/jw4-osaka-shimazu-walk.mp4}"
echo "N=$n T=$t loadavg_before=$(cut -d' ' -f1-3 /proc/loadavg)"
start=$(date +%s.%N)
for i in $(seq 1 "$n"); do
  THREADS=$t "$here/run-bench.sh" "$clip" "conc-${n}x${t}-$i" --fresh --stitch --bf16 vitpose,hmr2 \
    >"$main_root/private/work/conc-${n}x${t}-$i.log" 2>&1 &
done
wait
end=$(date +%s.%N)
frames=$(python3 -I -c "import json,sys;print(json.load(open(sys.argv[1]))['frames_30fps'])" \
  "$main_root/private/work/runs/conc-${n}x${t}-1/timings.json")
awk -v a="$start" -v b="$end" -v n="$n" -v f="$frames" \
  'BEGIN{w=b-a; printf "wall %.1f s for %d x %d frames: aggregate %.3f s/frame (incl. model loads)\n", w, n, f, w/(n*f)}'
for i in $(seq 1 "$n"); do tr '\r' '\n' <"$main_root/private/work/conc-${n}x${t}-$i.log" | grep -aE '^\[(yolo|vitpose|hmr2)'; done
