"""Track E's hero stage (blender/hero/rig.py) with the deformation runtime:
the helper bones and corrective shape keys follow the pose exactly as the
game runtime drives them (blender/character/deform_runtime.py), and the
canonical poses of blender/character/deform_poses.py (hero, high_ready, ...)
are available next to E's own.

    blender -b -t 3 --factory-startup --python-exit-code 1 \\
        --python bench/m1/deform_hero.py -- <rig.py args> [--pose hero|high_ready|...]

Without this wrapper a posed character.blend renders with the helper bones at
their bind pose: no twist split, no deltoid/hip helpers, no skirt follow and
no correctives (that is what an engine without the runtime would show).
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "blender"))
from character import deform_poses as dp, deform_runtime as drt  # noqa: E402
from hero import poses, rig  # noqa: E402


def _rules(ch):
    arm = ch.arm
    if "deform_rules" in arm:
        return json.loads(arm["deform_rules"])
    p = os.path.join(os.path.dirname(os.path.abspath(bpy_path())), "character.rig.json")
    return json.load(open(p)) if os.path.exists(p) else None


def bpy_path():
    import bpy
    return bpy.data.filepath or ARGS_IN


def _ours(name):
    def f(p):
        dp.apply_pose(p.arm, name)
    return f


for n in dp.POSES:
    if n not in poses.POSES:
        poses.POSES[n] = _ours(n)

_pose = rig.pose


def pose(ch, name):
    log = _pose(ch, name)
    R = _rules(ch)
    if R:
        meshes = [o for o in ch.arm.children if o.type == "MESH"]
        w = drt.Runtime(ch.arm, meshes, R).apply()
        log.append("deform runtime: " + ", ".join(f"{k} {v:.2f}" for k, v in sorted(w.items()) if v > 0.01))
    else:
        log.append("deform runtime: no rules (helpers at bind)")
    return log


rig.pose = pose
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ARGS_IN = argv[argv.index("--in") + 1] if "--in" in argv else ""
rig.main(argv)
