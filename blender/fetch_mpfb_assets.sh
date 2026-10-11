#!/usr/bin/env bash
# Fetch the CC0 MakeHuman asset packs used by the character pipeline into
# data/raw/ (gitignored). Each pack gets its own fresh directory; archives are
# untrusted data and are only unzipped, never executed.
#
# Usage: blender/fetch_mpfb_assets.sh [DATA_ROOT]
#   DATA_ROOT defaults to <repo>/data (main checkout when run from a worktree
#   is fine too: pass /path/to/main/data explicitly).
set -euo pipefail

DATA_ROOT="${1:-$(cd "$(dirname "$0")/.." && pwd)/data}"
RAW="$DATA_ROOT/raw/makehuman"
mkdir -p "$RAW"

fetch() { # name url sha256-or-empty
  local name="$1" url="$2"
  local dir="$RAW/$name"
  local zip="$dir/$(basename "$url")"
  if [[ -f "$zip" ]]; then
    echo "have $zip"
  else
    mkdir -p "$dir"
    echo "fetch $url"
    curl -sSfL --retry 3 -o "$zip.part" "$url"
    mv "$zip.part" "$zip"
  fi
  sha256sum "$zip" | tee "$zip.sha256"
  if [[ ! -d "$dir/unpacked" ]]; then
    mkdir -p "$dir/unpacked"
    # bsdtar (libarchive) reads zip and, without -P, refuses absolute paths
    # and ../ entries. -k never overwrites. unzip is not installed here.
    bsdtar -x -k --no-same-owner -f "$zip" -C "$dir/unpacked"
  fi
}

# https://static.makehumancommunity.org/assets/assetpacks/makehuman_system_assets.html
fetch makehuman_system_assets \
  https://files2.makehumancommunity.org/asset_packs/makehuman_system_assets/makehuman_system_assets_cc0.zip
# https://static.makehumancommunity.org/assets/assetpacks/suits01.html
fetch suits01 \
  https://files2.makehumancommunity.org/asset_packs/suits01/suits01_cc0.zip
