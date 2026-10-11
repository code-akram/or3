#!/usr/bin/env bash
# Spike 2 bench: turntable renders (front, 3/4, profile, close-up) of the
# spike-1 GLB with Cycles CPU (OIDN on/off) and headless EEVEE (OpenGL/EGL on
# the iGPU via radeonsi, and forced llvmpipe). Each config writes
# <DATA>/build/renders/<config>/{*.png,timings.json}.
#
# Usage: bench/m0/bench_spike2_render.sh [THREADS] [RES] [CONFIGS...]
#   CONFIGS default: cycles128_oidn cycles128_raw cycles32_oidn eevee_radeonsi eevee_llvmpipe
# Env:   DATA=/path/to/main/checkout/data (default: <repo>/data)
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
DATA="${DATA:-$REPO/data}"
THREADS="${1:-3}"
RES="${2:-1024}"
shift $(( $# > 2 ? 2 : $# ))
CONFIGS=("$@")
[[ ${#CONFIGS[@]} -gt 0 ]] || CONFIGS=(cycles128_oidn cycles128_raw cycles32_oidn eevee_radeonsi eevee_llvmpipe)
GLB="$DATA/build/character/character.glb"
OUTROOT="$DATA/build/renders"
mkdir -p "$OUTROOT"

run() { # config, then extra args for render_turntable.py
  local cfg="$1"; shift
  echo "== $cfg threads=$THREADS res=$RES loadavg=$(cat /proc/loadavg)"
  blender -b ${BLENDER_EXTRA:-} -t "$THREADS" --factory-startup --python "$REPO/blender/render_turntable.py" -- \
    --glb "$GLB" --out-dir "$OUTROOT/$cfg" --res "$RES" "$@" > "$OUTROOT/$cfg.log" 2>&1 \
    || { echo "FAILED $cfg (see $OUTROOT/$cfg.log)"; return 0; }
  grep '^\[render\]' "$OUTROOT/$cfg.log"
}

for cfg in "${CONFIGS[@]}"; do
  case "$cfg" in
    cycles128_oidn) run "$cfg" --engine CYCLES --samples 128 --denoise 1 --warm-repeat 0 ;;
    cycles128_raw)  run "$cfg" --engine CYCLES --samples 128 --denoise 0 --warm-repeat 0 ;;
    cycles32_oidn)  run "$cfg" --engine CYCLES --samples 32  --denoise 1 --warm-repeat 0 ;;
    eevee_radeonsi) run "$cfg" --engine EEVEE  --samples 64 ;;
    eevee_llvmpipe) LIBGL_ALWAYS_SOFTWARE=1 LP_NUM_THREADS="$THREADS" \
                    run "$cfg" --engine EEVEE  --samples 64 ;;
    # Needs a Vulkan ICD (vulkan-radeon / vulkan-swrast); none installed at spike time.
    eevee_vulkan)   BLENDER_EXTRA="--gpu-backend vulkan" run "$cfg" --engine EEVEE --samples 64 ;;
    *) echo "unknown config $cfg" ;;
  esac
done
