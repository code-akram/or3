#!/usr/bin/env bash
# Install MPFB2 as a user-level Blender extension, headless, from
# extensions.blender.org. Idempotent.
set -euo pipefail
BLENDER="${BLENDER:-blender}"
"$BLENDER" -b --online-mode --command extension install -s -e mpfb 2>&1 | grep -v '^PROGRESS'
"$BLENDER" -b --command extension list 2>&1 | grep -E '^\s*mpfb' || true
