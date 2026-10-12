#!/usr/bin/env bash
# Idle-machine throughput bench for the GVHMR pipeline (Phase 0 spike 3 follow-up).
#
# Runs the full per-stage bench on one clip at 16 and 8 threads (bf16 ViTs and fp32 as shipped),
# then concurrent schedules (1x8, 2x4, 2x8, 4x4), then HMR2 thread scaling.
# Waits until the 1-minute load average is below LOAD_MAX before each heavy step.
#
# Usage: idle-bench.sh [CLIP] [PREFIX]
#   default CLIP = private/footage/clips/jw4-osaka-shimazu-walk.mp4 (the first bench's clip)
# Results: private/work/runs/<PREFIX>-*/timings.json, log on stdout.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
main_root="${MAIN_ROOT:-/home/akram/code/or3}"
clip="${1:-$main_root/private/footage/clips/jw4-osaka-shimazu-walk.mp4}"
prefix="${2:-idle}"
load_max="${LOAD_MAX:-1.5}"

wait_idle() {
  while :; do
    l=$(cut -d' ' -f1 /proc/loadavg)
    awk -v l="$l" -v m="$load_max" 'BEGIN{exit !(l < m)}' && break
    echo "waiting: loadavg=$l (want < $load_max)"
    sleep 60
  done
}

run() { # THREADS NAME ARGS...
  local t=$1 n=$2
  shift 2
  wait_idle
  THREADS=$t "$here/run-bench.sh" "$clip" "$prefix-$n" --fresh --stitch "$@"
}

run 16 bf16-t16 --bf16 vitpose,hmr2
run 16 fp32-t16
run 8 bf16-t8 --bf16 vitpose,hmr2
run 8 fp32-t8

# Concurrent schedules (bf16): 1x8 as the baseline with model loads, then 2x4, 2x8 and 4x4.
# (Before the ultralytics thread fix in bench_gvhmr.py, YOLO ignored the cap and 4x4 oversubscribed.)
for nt in "1 8" "2 4" "2 8" "4 4"; do
  wait_idle
  "$here/concurrency-bench.sh" $nt "$clip"
done

wait_idle
"$here/thread-scaling.sh" "$main_root/private/work/runs/$prefix-bf16-t16" 1 2 4 8 16
