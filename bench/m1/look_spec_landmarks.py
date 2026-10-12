"""Measure the look-spec §1.1 landmarks on a saved nude character .blend.

The definitions live in blender/character/head_measure.py, which the build
also runs on every look-dev iteration (the harness reports them as
metrics.json `landmarks` + `spec_checks`). This wrapper is for one-off
measurement of an arbitrary .blend:

    blender -b nude.blend --factory-startup \
        --python bench/m1/look_spec_landmarks.py -- [--json out.json]

The body must be unclothed (a staged clothed build has its covered polygons
deleted); the MPFB base mesh is the largest mesh with a "body" vertex group.
"""
import json
import os
import sys

import bpy

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "blender"))
from character import head_measure  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
out_json = argv[argv.index("--json") + 1] if "--json" in argv else None

arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
body = max((o for o in bpy.data.objects if o.type == "MESH" and "body" in o.vertex_groups),
           key=lambda o: len(o.data.vertices))
m = head_measure.measure(arm, body, head_measure.find_eyes(bpy.data.objects))
for k, v in m.items():
    print(f"LANDMARK {k:22s} {v}")
for k, c in head_measure.checks(m).items():
    print(f"CHECK {k:22s} {c['value']} target {c['target']} tol {c['tol']} {'ok' if c['ok'] else 'OUT'}")
if out_json:
    with open(out_json, "w") as f:
        json.dump(m, f, indent=1)
