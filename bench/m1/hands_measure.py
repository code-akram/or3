"""Hand and neck measures of a kept build (m1 v4 T22): hand_width_ratio and dorsum relief
(blender/character/hand_forms.measure), on the staged rest mesh of a character.blend.

    blender -b -t 4 --factory-startup RUN/character.blend --python bench/m1/hands_measure.py -- [--json OUT]

Prints one JSON object (and writes it to --json).
"""

import json
import os
import sys

import bpy

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "blender"))
from character import hand_forms  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
body = bpy.data.objects["Human_export"]
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
# measure the rest shape: shape keys (correctives) at 0, no armature deformation
if body.data.shape_keys:
    for k in body.data.shape_keys.key_blocks[1:]:
        k.value = 0.0
res = hand_forms.measure(body, arm)
s = json.dumps(res, indent=1)
print("[hands_measure]", s)
if "--json" in argv:
    with open(argv[argv.index("--json") + 1], "w") as f:
        f.write(s)
