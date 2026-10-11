#!/usr/bin/env bash
# Build the Rust core for the browser: wasm32 + SIMD + threads (shared memory).
#
# Requirements (measured in Phase 0 spike 4, see bench/m0/spike-4-browser-skeleton.md):
#   * nightly Rust with rust-src: shared memory needs std rebuilt with atomics (-Z build-std);
#     stable's prebuilt std makes rust-lld refuse --shared-memory.
#   * wasm-bindgen CLI matching the crate version exactly (0.2.129).
#   * binaryen wasm-opt (optional; skipped with WASM_OPT=none).
#
# Size experiments: CARGO_PROFILE_WASM_OPT_LEVEL=z WASM_OPT_LEVEL=-Oz core/build-web.sh
#
# Output: web/src/core-wasm/ (gitignored): game_core.js, game_core_bg.wasm, .d.ts files.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/.." && pwd)"
out="$root/web/src/core-wasm"

toolchain="${CORE_TOOLCHAIN:-nightly}"
jobs="${CORE_JOBS:-3}"
wasm_bindgen="${WASM_BINDGEN:-$(command -v wasm-bindgen || echo "$HOME/opt/wasm-bindgen-0.2.129-x86_64-unknown-linux-musl/wasm-bindgen")}"
wasm_opt="${WASM_OPT:-$(command -v wasm-opt || echo "$HOME/opt/binaryen-version_133/bin/wasm-opt")}"
# Shared memory needs a declared maximum. 256 MiB keeps wasm32 address space modest (NOTES §13).
max_memory="${CORE_MAX_MEMORY:-268435456}"

export RUSTFLAGS="-C target-feature=+atomics,+bulk-memory,+simd128 -C link-arg=--shared-memory -C link-arg=--max-memory=${max_memory} -C link-arg=--import-memory -C link-arg=--export=__wasm_init_tls -C link-arg=--export=__tls_size -C link-arg=--export=__tls_align -C link-arg=--export=__tls_base"

cd "$root"
cargo "+${toolchain}" build -j"$jobs" -p game-core \
  --target wasm32-unknown-unknown --profile wasm \
  -Z build-std=std,panic_abort

raw="$root/target/wasm32-unknown-unknown/wasm/game_core.wasm"
rm -rf "$out"
"$wasm_bindgen" --target web --out-dir "$out" --out-name game_core "$raw"

wasm="$out/game_core_bg.wasm"
if [[ "$wasm_opt" != "none" && -x "$wasm_opt" ]]; then
  "$wasm_opt" ${WASM_OPT_LEVEL:--O3} \
    --enable-threads --enable-simd --enable-bulk-memory --enable-mutable-globals \
    --enable-sign-ext --enable-nontrapping-float-to-int --enable-reference-types --enable-multivalue \
    "$wasm" -o "$wasm.opt"
  mv "$wasm.opt" "$wasm"
else
  echo "wasm-opt skipped" >&2
fi

printf 'core wasm: %s bytes raw, %s bytes gzip -9\n' "$(stat -c %s "$wasm")" "$(gzip -9c "$wasm" | wc -c)"
