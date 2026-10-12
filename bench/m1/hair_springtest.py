"""Skinning sanity test: import a run's GLB, rotate the hair chains as a
spring sim would after a head turn (first bones swung back/sideways, second
bones further), render back and side at 768 next to the rest pose.

    blender -b --factory-startup --python bench/m1/hair_springtest.py -- RUN_DIR

Writes RUN_DIR/hair/spring_<view>_<deg>.png for back, side and closeup at 0 and 35 degrees.
"""
import math
import os
import sys

import bpy
from mathutils import Euler, Vector

RUN = os.path.abspath(sys.argv[sys.argv.index("--") + 1])
OUT = os.path.join(RUN, "hair")
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
bpy.ops.import_scene.gltf(filepath=os.path.join(RUN, "character.glb"))
arm = next(o for o in bpy.context.scene.objects if o.type == "ARMATURE")
for o in bpy.context.scene.objects:
    if o.type == "MESH" and o.parent != arm:
        o.hide_render = True
scene = bpy.context.scene
world = scene.world or bpy.data.worlds.new("w")
scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.045, 0.045, 0.05, 1)
ld = bpy.data.lights.new("key", "AREA")
ld.energy, ld.size = 900, 1.5
key = bpy.data.objects.new("key", ld)
scene.collection.objects.link(key)
key.location = (-2.2, -2.6, 2.8)
aim = Vector((0, 0, 1.1))
key.rotation_euler = (aim - key.location).to_track_quat("-Z", "Y").to_euler()
ld2 = bpy.data.lights.new("rim", "AREA")
ld2.energy, ld2.size = 700, 1.0
rim = bpy.data.objects.new("rim", ld2)
scene.collection.objects.link(rim)
rim.location = (0.8, 2.8, 2.6)
rim.rotation_euler = (aim - rim.location).to_track_quat("-Z", "Y").to_euler()
scene.view_settings.view_transform = "AgX"
scene.view_settings.exposure = -2.5
scene.render.engine = "BLENDER_EEVEE"
scene.eevee.taa_render_samples = 16
scene.render.resolution_x = scene.render.resolution_y = 768
bone = arm.data.bones["head"]
head = arm.matrix_world @ ((bone.head_local + bone.tail_local) * 0.5)


def pose(deg):
    for pb in arm.pose.bones:
        if pb.name.startswith("hair_"):
            k = int(pb.name[-2:])
            # swing about the bone's local X (perpendicular to its length)
            pb.rotation_mode = "XYZ"
            pb.rotation_euler = Euler((math.radians(deg * (1.0 if k == 1 else 0.7)), 0, 0))


for name, az in (("back", 180), ("side", 90), ("closeup", 25)):
    cd = bpy.data.cameras.new(name)
    cd.lens = 85
    cam = bpy.data.objects.new(name, cd)
    scene.collection.objects.link(cam)
    a = math.radians(az)
    target = head.copy()
    target.z -= 0.06
    dist = (0.42 * 0.5) / math.tan(math.atan(cd.sensor_width * 0.5 / 85))
    cam.location = target + Vector((math.sin(a), -math.cos(a), 0.0)) * dist
    cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam
    for deg in (0, 35):
        pose(deg)
        scene.render.filepath = os.path.join(OUT, f"spring_{name}_{deg}.png")
        bpy.ops.render.render(write_still=True)
print("ok")
