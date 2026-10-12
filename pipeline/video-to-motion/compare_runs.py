"""Compare two motion exports (e.g. fp32 vs bf16) from motion_qc.py: per-joint position error.

    python -I compare_runs.py private/motion/RUN_A private/motion/RUN_B [--which raw|clean]

Reports MPJPE in world space, root-aligned MPJPE (pose only) and root trajectory difference, in mm.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--which", default="raw")
    a = ap.parse_args()
    ja = np.load(Path(a.a) / f"motion_{a.which}.npz")["joints"]
    jb = np.load(Path(a.b) / f"motion_{a.which}.npz")["joints"]
    n = min(len(ja), len(jb))
    ja, jb = ja[:n], jb[:n]
    world = np.linalg.norm(ja - jb, axis=-1) * 1000
    local = np.linalg.norm((ja - ja[:, :1]) - (jb - jb[:, :1]), axis=-1) * 1000
    root = np.linalg.norm(ja[:, 0] - jb[:, 0], axis=-1) * 1000
    print(json.dumps({
        "frames": n,
        "mpjpe_world_mm_mean": round(float(world.mean()), 2),
        "mpjpe_world_mm_max": round(float(world.max()), 2),
        "mpjpe_root_aligned_mm_mean": round(float(local.mean()), 2),
        "mpjpe_root_aligned_mm_p99": round(float(np.percentile(local, 99)), 2),
        "root_diff_mm_mean": round(float(root.mean()), 2),
        "root_diff_mm_final": round(float(root[-1]), 2),
    }, indent=1))


if __name__ == "__main__":
    main()
