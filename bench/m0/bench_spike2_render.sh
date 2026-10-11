#!/usr/bin/env bash
# Spike 2 bench: turntable renders (front, 3/4, profile, close-up) of the
# spike-1 GLB with Cycles CPU (OIDN on/off) and headless EEVEE (OpenGL/EGL on
# the iGPU via radeonsi, and forced llvmpipe). Each config writes
# <DATA>/build/renders/<config>/{*.png,timings.json}.
#
# Usage: bench/m0/bench_spike2_render.sh [THREADS] [RES] [CONFIGS...]
#   CONFIGS default: cycles128_oidn cycles128_raw cycles32_oidn eevee_radeonsi eevee_llvmpipe
#   also: cycles1_oidn cycles1_raw (OIDN cost), eevee_vulkan (needs a Vulkan ICD)
# Env:   DATA=/path/to/main/checkout/data (default: <repo>/data)
#        SUFFIX=_512 appends to output dir names (e.g. for a second resolution)
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
    --glb "$GLB" --out-dir "$OUTROOT/$cfg${SUFFIX:-}" --res "$RES" "$@" > "$OUTROOT/$cfg${SUFFIX:-}.log" 2>&1 \
    || { echo "FAILED $cfg (see $OUTROOT/$cfg${SUFFIX:-}.log)"; return 0; }
  grep '^\[render\]' "$OUTROOT/$cfg${SUFFIX:-}.log"
}

for cfg in "${CONFIGS[@]}"; do
  case "$cfg" in
    cycles128_oidn) run "$cfg" --engine CYCLES --samples 128 --denoise 1 --warm-repeat 0 ;;
    cycles128_raw)  run "$cfg" --engine CYCLES --samples 128 --denoise 0 --warm-repeat 0 ;;
    cycles32_oidn)  run "$cfg" --engine CYCLES --samples 32  --denoise 1 --warm-repeat 0 ;;
    # 1 spp, front only: isolates the OIDN pass cost (on minus off).
    cycles1_oidn)   run "$cfg" --engine CYCLES --samples 1 --denoise 1 --adaptive 0 --views front --warm-repeat 0 ;;
    cycles1_oidn_balanced) run "$cfg" --engine CYCLES --samples 1 --denoise 1 --adaptive 0 --views front --warm-repeat 0 --oidn-quality BALANCED ;;
    cycles1_oidn_fast)     run "$cfg" --engine CYCLES --samples 1 --denoise 1 --adaptive 0 --views front --warm-repeat 0 --oidn-quality FAST --oidn-prefilter FAST ;;
    cycles32_oidn_fast)    run "$cfg" --engine CYCLES --samples 32 --denoise 1 --warm-repeat 0 --oidn-quality FAST --oidn-prefilter FAST ;;
    cycles1_raw)    run "$cfg" --engine CYCLES --samples 1 --denoise 0 --adaptive 0 --views front --warm-repeat 0 ;;
    # Fast look-dev settings (16 TAA samples); pair with RES=512 for the loop.
    eevee16_radeonsi) run "$cfg" --engine EEVEE --samples 16 ;;
    eevee16_llvmpipe) LIBGL_ALWAYS_SOFTWARE=1 LP_NUM_THREADS="$THREADS" \
                      run "$cfg" --engine EEVEE --samples 16 ;;
    eevee_radeonsi) run "$cfg" --engine EEVEE  --samples 64 ;;
    eevee_llvmpipe) LIBGL_ALWAYS_SOFTWARE=1 LP_NUM_THREADS="$THREADS" \
                    run "$cfg" --engine EEVEE  --samples 64 ;;
    # Needs a Vulkan ICD (vulkan-radeon / vulkan-swrast); none installed at spike time.
    eevee_vulkan)   BLENDER_EXTRA="--gpu-backend vulkan" run "$cfg" --engine EEVEE --samples 64 ;;
    *) echo "unknown config $cfg" ;;
  esac
done
