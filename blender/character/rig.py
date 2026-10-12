"""Rig: MPFB builtin skeleton, then helper/twist bones on the staged armature."""


def add(b):
    b.mpfb.HumanService.add_builtin_rig(b.basemesh, b.cfg["rig"]["builtin"])


def post(b):
    if b.cfg["rig"]["helpers"]:
        raise NotImplementedError("helper/twist bones: owned by the m1 deformation track")
