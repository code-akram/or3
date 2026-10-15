"""Rig: MPFB builtin skeleton, then the deformation stage on the staged armature.

rig.post (after head_refine, before budgets) runs, on the staged export objects:

1. deform_rig: helper and twist bones, half-joint / twist / finger / skirt
   weight remaps, garment weight smoothing, <= 4 influences;
2. deform_correctives: corrective morph targets baked from delta mush plus
   layer collision, with their cone drivers;
3. writes the runtime rules (character.rig.json next to the GLB, and the
   armature's "deform_rules" property in the .blend).

Config: cfg["rig"]["deform"] deep-merges over DEFAULTS below; null disables
the stage (stock MPFB rig and weights); {"correctives": null} skips the morphs.
See bench/m1/v2/deform.md and blender/character/deform_runtime.py.
"""

from . import config
from . import deform_correctives as dcor
from . import deform_rig as drig

DEFAULTS = {"weights": drig.DEFAULTS, "correctives": dcor.DEFAULTS}


def add(b):
    b.mpfb.HumanService.add_builtin_rig(b.basemesh, b.cfg["rig"]["builtin"])


def post(b):
    over = b.cfg["rig"].get("deform", {})
    if over is None:
        return
    cfg = config.merge(DEFAULTS, over)
    rules, info = drig.run(b, cfg["weights"])
    note = {"weights": info}
    if cfg["correctives"] is not None:
        note["correctives"] = dcor.run(b, cfg["correctives"], rules)
    run = b.armature().get("made_suit_run")
    if run:   # the made suit's cones and fitted skirt gains (T13, suit_made)
        from . import suit_made
        note["made_suit"] = suit_made.apply_rules(rules, run)
    note["rules_path"] = drig.write_rules(b, rules)
    note["morphs"] = [m["name"] for m in rules["morphs"]]
    b.notes["deform"] = note
