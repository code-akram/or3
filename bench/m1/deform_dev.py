"""Fast inner loop for the deformation stage: open a kept character.blend
built WITHOUT the stage (`{"rig": {"deform": null}}`, or any build before
it existed), run rig.post on it and export the GLB, the rules and the .blend,
so bench/m1/deform_test.sh can test it without a 2-minute full build.

    blender -b -t 4 --factory-startup --python bench/m1/deform_dev.py -- \
        --blend BASE/character.blend --out DIR/character.glb [--config over.json]

The full build (bench/m1/lookdev.sh) runs the same code in its rig_post step.
"""

import argparse
import json
import os
import sys
import time

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "blender"))
from character import config, export, rig  # noqa: E402
from character.context import Build  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--blend", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--config")
ap.add_argument("--no-blend", action="store_true")
A = ap.parse_args(argv)

bpy.ops.wm.open_mainfile(filepath=os.path.abspath(A.blend))
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
if "deform_rules" in arm:
    raise SystemExit("this .blend already went through the deformation stage")
b = Build(config.load(A.config))
b.export_root = arm
b.export_objs = [arm] + [o for o in bpy.data.objects if o.parent == arm]
b.out_dir = os.path.dirname(os.path.abspath(A.out))
os.makedirs(b.out_dir, exist_ok=True)
t = time.perf_counter()
b.step("rig_post", rig.post)
b.step("export_glb", export.write_glb, os.path.abspath(A.out))
if not A.no_blend:
    b.step("save_blend", export.save_blend, os.path.abspath(A.out)[:-4] + ".blend")
with open(os.path.abspath(A.out)[:-4] + ".deform.json", "w") as f:
    json.dump({"notes": b.notes, "timings": b.timings}, f, indent=1, default=str)
print(f"[deform_dev] {time.perf_counter() - t:.1f} s; bones {len(arm.data.bones)}")
