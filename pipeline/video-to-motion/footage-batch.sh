#!/usr/bin/env bash
# Footage batch driver: fetched clip -> shots -> YOLO tracks -> automatic protagonist ID -> GVHMR -> QC.
#
# Usage: footage-batch.sh STAGE BATCH CLIP_ID [CLIP_ID ...]
#   STAGE  shots | filter | cut | yolo | id | select | probe | gvhmr | summary | all
#   BATCH  work name: outputs in private/work/<BATCH>/, runs in private/work/runs/<BATCH>-<shot>
#
# MIN_LUMA (default 15) is shot_filter.py's median-luma floor; `filter` re-runs only the stage-1 filter (e.g.
# MIN_LUMA=6 for night-graded clips). Manual overrides of the automatic protagonist call go in
# private/work/<BATCH>/content.json ({clip: {label: [shot idx, …]}}, footage_run.py select --content).
# `probe` runs ViTPose on 16 frames of each candidate's chosen track; only shots whose mean body-joint
# confidence reaches MIN_PROBE (default 0.65; the yield bar after GVHMR is 0.7, and the probe matched the
# full-run mean within 0.01 on batch 2) go on to GVHMR.
#
# Everything derives from film frames and stays under private/ (NOTES.md §14). Stages are resumable:
# each skips shots whose output already exists. Heavy stages run JOBS (4) processes x THREADS (4) under
# nice, so interactive work (Blender look-dev) stays responsive. The protagonist gallery (GALLERY, default
# private/work/protagonist-id/gallery.npz) holds embeddings of hand-verified Wick tracks; build it with
# `protagonist_id.py gallery`.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
main_root="${MAIN_ROOT:-/home/akram/code/or3}"
py="${GVHMR_SRC:-$main_root/private/src/gvhmr-rudes}/.venv/bin/python"
jobs="${JOBS:-4}" threads="${THREADS:-4}" min_luma="${MIN_LUMA:-15}" min_probe="${MIN_PROBE:-0.65}"
gallery="${GALLERY:-$main_root/private/work/protagonist-id/gallery.npz}"
stage=$1 batch=$2
shift 2
clips=("$@")
work="$main_root/private/work/$batch"
runs="$main_root/private/work/runs"
mkdir -p "$work/logs"
export MAIN_ROOT="$main_root" OMP_NUM_THREADS=$threads MKL_NUM_THREADS=$threads GVHMR_CHECKPOINTS="$main_root/private/models/gvhmr"

shot_names() {  # stage-1 survivors of every clip, as <clip>-sNNN
  for c in "${clips[@]}"; do
    "$py" -I -c 'import json,sys; u=json.load(open(sys.argv[1])); print("\n".join(f"{sys.argv[2]}-s{i:03d}" for i in u["stage1_pass"]))' \
      "$main_root/private/work/shots/$c/union.json" "$c"
  done
}

run_shots() {
  for c in "${clips[@]}"; do
    d="$main_root/private/work/shots/$c"
    [[ -f "$d/union.json" ]] && continue
    nice -n 10 "$py" -I "$here/shots.py" "$main_root/private/footage/$c/source.mp4" "$d" --threads "$threads" \
      >"$work/logs/shots-$c.log" 2>&1
    run_filter_one "$c"
  done
}

run_filter_one() {
  nice -n 10 "$py" -I "$here/shot_filter.py" "$main_root/private/footage/$1/source.mp4" "$main_root/private/work/shots/$1" \
    --min-luma "$min_luma" | tee -a "$work/logs/shots-$1.log"
}

run_cut() {
  for c in "${clips[@]}"; do
    "$py" -I -c 'import json,sys; u=json.load(open(sys.argv[1])); [print(s["start"], s["end"], "%s-s%03d" % (sys.argv[2], s["idx"])) for s in u["shots"] if s["idx"] in u["stage1_pass"]]' \
      "$main_root/private/work/shots/$c/union.json" "$c" |
    while read -r s e name; do
      [[ -f "$main_root/private/footage/clips/$name.mp4" ]] || echo "$main_root/private/footage/$c/source.mp4 $s $e $name"
    done
  done | xargs -r -P "$jobs" -L 1 nice -n 10 "$here/cut-shot.sh" >"$work/logs/cut.log" 2>&1
}

one_yolo() {  # $1 = shot name
  [[ -f "$runs/$batch-$1/timings.json" ]] && return 0
  nice -n 10 env THREADS="$threads" "$here/run-bench.sh" "$main_root/private/footage/clips/$1.mp4" "$batch-$1" \
    --fresh --stitch --stop-after yolo >"$work/logs/yolo-$1.log" 2>&1 || echo "no track: $1"
  [[ -f "$runs/$batch-$1/timings.json" ]] && cp "$runs/$batch-$1/timings.json" "$runs/$batch-$1/timings-yolo.json"
  return 0
}

one_probe() {  # $1 = shot name: ViTPose on 16 frames of the auto-ID track
  [[ -f "$runs/$batch-$1/vitpose-probe.json" ]] && return 0
  nice -n 10 env THREADS="$threads" "$here/run-bench.sh" "$main_root/private/footage/clips/$1.mp4" "$batch-$1" \
    --stitch --auto-id --bf16 vitpose --reuse yolo --vitpose-probe 16 >"$work/logs/probe-$1.log" 2>&1 || echo "FAIL probe $1"
}

one_gvhmr() {  # $1 = shot name
  [[ -f "$main_root/private/motion/$batch-$1/qc.json" ]] && return 0
  nice -n 10 env THREADS="$threads" "$here/run-bench.sh" "$main_root/private/footage/clips/$1.mp4" "$batch-$1" \
    --stitch --auto-id --bf16 vitpose,hmr2 --reuse yolo >"$work/logs/gvhmr-$1.log" 2>&1 || { echo "FAIL gvhmr $1"; return 0; }
  nice -n 10 "$py" -I "$here/motion_qc.py" "$runs/$batch-$1" --motion-out "$main_root/private/motion/$batch-$1" \
    --vis-out "$main_root/private/work/vis/$batch-$1" >>"$work/logs/gvhmr-$1.log" 2>&1 || echo "FAIL qc $1"
}
export -f one_yolo one_probe one_gvhmr
export here main_root py threads runs batch work

{  # braces: bash parses the whole dispatch before running it, so editing this file mid-run is safe
case $stage in
  shots) run_shots ;;
  filter) for c in "${clips[@]}"; do run_filter_one "$c"; done ;;
  cut) run_cut ;;
  yolo) shot_names | xargs -r -P "$jobs" -I{} bash -c 'one_yolo "$1"' _ {} ;;
  id)
    shot_names | while read -r n; do if [[ -f "$runs/$batch-$n/timings.json" ]]; then echo "$runs/$batch-$n"; fi; done >"$work/runs.txt"
    nice -n 10 "$py" -I "$here/protagonist_id.py" embed --threads "$((jobs * threads))" --runs-file "$work/runs.txt"
    "$py" -I "$here/protagonist_id.py" score --gallery "$gallery" --runs-file "$work/runs.txt" | tee "$work/logs/id.log"
    ;;
  select)  # coverage, subject size, automatic presence -> probe candidates
    over=()
    [[ -f "$work/content.json" ]] && over=(--content "$work/content.json")
    "$py" -I "$here/footage_run.py" select --clips "${clips[@]}" --prefix "$batch-" --auto-id "${over[@]}" \
      --out "$work/sel-pre.json" >"$work/probe-list.txt"
    wc -l <"$work/probe-list.txt"
    ;;
  probe)  # ViTPose probe on the candidates, then the GVHMR list and a contact sheet of its chosen tracks
    xargs -r -P "$jobs" -I{} bash -c 'one_probe "$1"' _ {} <"$work/probe-list.txt"
    over=()
    [[ -f "$work/content.json" ]] && over=(--content "$work/content.json")
    "$py" -I "$here/footage_run.py" select --clips "${clips[@]}" --prefix "$batch-" --auto-id "${over[@]}" \
      --min-probe "$min_probe" --out "$work/sel.json" >"$work/gvhmr-list.txt"
    wc -l <"$work/gvhmr-list.txt"
    sed "s|^|$runs/$batch-|" "$work/gvhmr-list.txt" >"$work/gvhmr-runs.txt"
    mkdir -p "$work/sheets"
    "$py" -I "$here/protagonist_id.py" sheet --runs-file "$work/gvhmr-runs.txt" --out "$work/sheets/check.jpg"
    ;;
  gvhmr) xargs -r -P "$jobs" -I{} bash -c 'one_gvhmr "$1"' _ {} <"$work/gvhmr-list.txt" ;;
  summary) "$py" -I "$here/footage_run.py" summary --sel "$work/sel.json" --out "$work/yield.json" ;;
  all)
    for s in shots cut yolo id select probe gvhmr summary; do "$0" "$s" "$batch" "${clips[@]}"; done
    ;;
  *) echo "unknown stage: $stage"; exit 2 ;;
esac
exit
}
