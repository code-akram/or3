"""Repo-wide policy for binary raster / mesh / array / audio / video files (stdlib only).

Shared by tools/hooks/check_staged.py (pre-commit) and provenance/audit.py --check-files (catches a
`--no-verify` bypass at the next audit). Renders, arrays, meshes and recordings live under data/ or
private/, never in git: reports link to them. A tracked file is refused unless its exact path is in
ALLOWED_BINARIES below.

Deliberate override: add the path to ALLOWED_BINARIES (or, for a whole directory of icons, a prefix to
ALLOWED_BINARY_DIRS) in the SAME commit that adds the file, so the exception is reviewable in the
diff. `git add -f` does not bypass this: a hook is not a .gitignore rule.
"""

import re

BINARY = re.compile(
    r"\.(png|jpe?g|webp|gif|bmp|tiff?|exr|hdr|ktx2?|psd|"            # raster
    r"npz|npy|pt|pth|pkl|safetensors|onnx|"                           # arrays / weights
    r"obj|ply|stl|glb|gltf|fbx|blend\d*|abc|usd[acz]?|"               # meshes / scenes (.gltf can embed buffers)
    r"wav|flac|opus|ogg|mp3|aiff?|"                                   # audio
    r"mp4|mov|mkv|webm)$",                                            # video
    re.I,
)

# Exact tracked paths that predate this policy: the m0 gate evidence images (public-safe scenes).
ALLOWED_BINARIES = frozenset({
    "bench/m0/img/chunk-kabukicho-alley.png",
    "bench/m0/img/chunk-kabukicho-overview.png",
    "bench/m0/renders/compare_closeup_crops.png",
    "bench/m0/renders/cycles128_oidn_closeup.png",
    "bench/m0/renders/cycles128_oidn_front.png",
    "bench/m0/renders/cycles128_oidn_profile.png",
    "bench/m0/renders/cycles128_oidn_three_quarter.png",
    "bench/m0/renders/pose_check.png",
})
# Directory prefixes (with trailing slash) whose files are allowed, e.g. "web/public/icons/".
ALLOWED_BINARY_DIRS = ()


def binary_problem(path):
    """Return a reason string if `path` (repo-relative, '/' separators) is a refused binary, else None."""
    if not BINARY.search(path):
        return None
    if path in ALLOWED_BINARIES or path.startswith(ALLOWED_BINARY_DIRS):
        return None
    return ("binary image / array / mesh / audio / video outside the allowlist "
            "(tools/hooks/binary_policy.py; keep it under data/ or private/)")
