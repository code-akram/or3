#!/usr/bin/env bash
# Spike 6: fetch the Steam Audio C SDK 4.8.1 (Apache-2.0) into data/raw/steam-audio/.
# Source: https://github.com/ValveSoftware/steam-audio/releases/tag/v4.8.1
# The binary bundles third-party code (Intel IPP, Embree, FFTS, PFFFT, MySOFA, ...);
# see sdk/steamaudio/THIRDPARTY.md. Nothing from it is committed.
set -euo pipefail

DIR=/home/akram/code/or3/data/raw/steam-audio
URL=https://github.com/ValveSoftware/steam-audio/releases/download/v4.8.1/steamaudio_4.8.1.zip
SHA256=4a0aa5ec1176f38f0b0993a37c2259d9e86f27e22d5e24f83ec4c3cb9a1d5449  # 181,171,027 bytes

mkdir -p "$DIR/sdk"
cd "$DIR"
[ -f steamaudio_4.8.1.zip ] || curl -fsSL -o steamaudio_4.8.1.zip "$URL"
echo "$SHA256  steamaudio_4.8.1.zip" | sha256sum -c -
[ -f sdk/steamaudio/lib/linux-x64/libphonon.so ] || bsdtar -xf steamaudio_4.8.1.zip -C sdk
ls -l sdk/steamaudio/lib/linux-x64/libphonon.so
