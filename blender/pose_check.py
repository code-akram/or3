"""Skinning sanity check: import the GLB, pose the game_engine rig into a
stress pose (arms up/forward, elbows and knees bent, torso twist, head turn)
and render a front and three-quarter view with EEVEE.

    blender -b -t 3 --factory-startup --python blender/pose_check.py -- \
        --glb data/build/character/character.glb --out data/build/renders/pose_check.png
"""

import argparse
import math
import os
import sys

import bpy
from mathutils import Euler, Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--glb", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--res", type=int, default=768)
ARGS = ap.parse_args(argv)

for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
bpy.ops.import_scene.gltf(filepath=os.path.abspath(ARGS.glb))
arm = next(o for o in bpy.context.scene.objects if o.type == "ARMATURE")

# Local-axis rotations in degrees (bone space); chosen to stress shoulders,
# elbows, knees, the spine and the neck, where suit and body deform most.
POSE = {
    "upperarm_l": (0, 0, -60), "lowerarm_l": (0, 0, -70),
    "upperarm_r": (60, 0, 30), "lowerarm_r": (0, 0, 80),
    "thigh_l": (-50, 0, 0), "calf_l": (80, 0, 0),
    "spine_02": (0, 20, 0), "spine_03": (0, 15, 0),
    "neck_01": (0, 25, 0), "head": (10, 10, 0),
}
for name, deg in POSE.items():
    pb = arm.pose.bones.get(name)
    if pb is None:
        print("missing bone", name)
        continue
    pb.rotation_mode = "XYZ"
    pb.rotation_euler = Euler([math.radians(d) for d in deg], "XYZ")
bpy.context.view_layer.update()

scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE"
scene.eevee.taa_render_samples = 32
scene.render.resolution_x = scene.render.resolution_y = ARGS.res
w = bpy.data.worlds.new("w")
scene.world = w
w.use_nodes = True
w.node_tree.nodes["Background"].inputs[0].default_value = (0.3, 0.3, 0.32, 1)
for name, loc, e in [("key", (-2, -3, 3), 800), ("rim", (1, 3, 2.5), 500)]:
    ld = bpy.data.lights.new(name, "AREA")
    ld.energy, ld.size = e, 2
    ob = bpy.data.objects.new(name, ld)
    scene.collection.objects.link(ob)
    ob.location = loc
    ob.rotation_euler = (Vector((0, 0, 1)) - ob.location).to_track_quat("-Z", "Y").to_euler()

cd = bpy.data.cameras.new("cam")
cam = bpy.data.objects.new("cam", cd)
scene.collection.objects.link(cam)
scene.camera = cam
cd.lens = 40
target = Vector((0, 0, 1.0))
stem, ext = os.path.splitext(ARGS.out)
os.makedirs(os.path.dirname(os.path.abspath(ARGS.out)), exist_ok=True)
for tag, az in [("front", 0), ("three_quarter", 40)]:
    a = math.radians(az)
    cam.location = target + Vector((math.sin(a) * 3.6, -math.cos(a) * 3.6, 0.1))
    cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
    scene.render.filepath = f"{stem}_{tag}{ext}"
    bpy.ops.render.render(write_still=True)
    print("[pose_check] wrote", scene.render.filepath)
