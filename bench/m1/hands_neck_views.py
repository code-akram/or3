"""Hand and neck close-ups of a shipped GLB (m1 v4 T22 evidence): EEVEE, the rest (bind) pose,
a raking key, in the shipped materials ("beauty") and in grey clay (form only).

    blender -b -t 4 --factory-startup --python bench/m1/hands_neck_views.py -- \\
        --glb RUN/character.glb --out DIR [--res 768] [--passes beauty,clay] [--shots a,b] \\
        [--side l|r] [--pose NAME]

--side picks the hand the hand shots frame. --pose applies deform_poses.POSES[NAME] and, when
RUN/character.rig.json exists, its helper and corrective rules (deform_runtime, the engine's
rules), printing the corrective weights; the frames follow the posed bones.

Shots (camera in the hand's own frame, so every build shows the same anatomy):
  hand_back   back of the left hand, square on, 0.12 m frame
  knuckles    the knuckle row from the fingertip side and above, raking
  hand_side   the radial side (thumb, snuffbox, index), 0.12 m
  wrist       the wrist from the ulnar-dorsal side, 0.10 m
  neck_profile / neck_34 / neck_34r   the neck from the character's left, its left 3/4 and
              right 3/4 (hair hidden in clay), 0.20 m
Writes DIR/<pass>_<shot>.png.
"""

import argparse
import math
import os
import sys

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--glb", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--res", type=int, default=768)
ap.add_argument("--passes", default="beauty,clay")
ap.add_argument("--shots", default="hand_back,knuckles,hand_side,wrist,neck_profile,neck_34,neck_34r")
ap.add_argument("--side", default="l", choices=["l", "r"], help="the hand the hand shots frame")
ap.add_argument("--pose", default="", help="a deform_poses.POSES name; the rig.json rules next to the GLB run")
A = ap.parse_args(argv)
os.makedirs(A.out, exist_ok=True)

for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
bpy.ops.import_scene.gltf(filepath=A.glb)
sc = bpy.context.scene
arm = next(o for o in sc.objects if o.type == "ARMATURE")
meshes = [o for o in sc.objects if o.type == "MESH"]
if A.pose:
    import json
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "blender"))
    from character import deform_poses as dp  # noqa: E402
    from character import deform_runtime as drt  # noqa: E402
    rig = dp.Rig(arm)
    dp.apply_pose(arm, dp.POSES[A.pose], rig)
    rp = os.path.join(os.path.dirname(os.path.abspath(A.glb)), "character.rig.json")
    if os.path.exists(rp):
        drv = drt.Runtime(arm, meshes, json.load(open(rp))).apply(rig, morphs=True)
        print("[views] drivers", {k: round(v, 3) for k, v in drv.items() if v}, flush=True)
    bpy.context.view_layer.update()


def head(n):
    return arm.matrix_world @ arm.pose.bones[n].head


def frame(s):
    w = head(f"hand_{s}")
    f = (head(f"middle_01_{s}") - w).normalized()
    t = head(f"index_01_{s}") - head(f"pinky_01_{s}")
    t = (t - f * t.dot(f)).normalized()
    back = f.cross(t)
    if (head(f"thumb_02_{s}") - w).dot(back) > 0:
        back = -back
    return w, f, t, back


S = A.side
W, F, T, B = frame(S)
neck_c = (head("neck_01") + head("head")) * 0.5 + Vector((0.0, -0.01, 0.02))
UP = Vector((0, 0, 1))
# name: (target, camera direction, frame height m, key offset (az deg about the view, el deg))
SHOTS = {
    "hand_back": (W * 0.45 + head(f"middle_01_{S}") * 0.55, (B + T * 0.15).normalized(), 0.12, (55, 35)),
    "knuckles": ((head(f"middle_01_{S}") + head(f"ring_01_{S}")) * 0.5, (B * 0.8 + F * 0.55 + T * 0.1).normalized(), 0.09, (70, 25)),
    "hand_side": (W * 0.5 + head(f"index_01_{S}") * 0.5, (T + B * 0.35).normalized(), 0.12, (60, 30)),
    "wrist": (W + F * 0.02, (B - T * 0.8 - F * 0.3).normalized(), 0.10, (55, 30)),
    "neck_profile": (neck_c, Vector((1.0, 0.0, 0.0)), 0.20, (40, 30)),
    "neck_34": (neck_c, Vector((0.7, -0.7, 0.05)).normalized(), 0.20, (45, 30)),
    "neck_34r": (neck_c, Vector((-0.7, -0.7, 0.05)).normalized(), 0.20, (-45, 30)),
}

sc.render.engine = "BLENDER_EEVEE"
sc.eevee.taa_render_samples = 32
sc.render.resolution_x = sc.render.resolution_y = A.res
sc.render.image_settings.file_format = "PNG"
sc.render.image_settings.color_mode = "RGB"
sc.view_settings.view_transform = "AgX"
sc.view_settings.exposure = 0.0
w = bpy.data.worlds.new("t22")
w.use_nodes = True
w.node_tree.nodes["Background"].inputs[0].default_value = (0.04, 0.04, 0.045, 1)
sc.world = w
cd = bpy.data.cameras.new("t22_cam")
cd.lens = 85.0
cam = bpy.data.objects.new("t22_cam", cd)
sc.collection.objects.link(cam)
sc.camera = cam
key = bpy.data.objects.new("t22_key", bpy.data.lights.new("t22_key", "AREA"))
key.data.size = 0.25
fill = bpy.data.objects.new("t22_fill", bpy.data.lights.new("t22_fill", "AREA"))
fill.data.size = 1.0
for l in (key, fill):
    sc.collection.objects.link(l)

clay = bpy.data.materials.new("t22_clay")
clay.use_nodes = True
p = clay.node_tree.nodes["Principled BSDF"]
p.inputs["Base Color"].default_value = (0.42, 0.38, 0.36, 1)
p.inputs["Roughness"].default_value = 0.55
orig = {o: [s.material for s in o.material_slots] for o in meshes}


def aim(ob, target):
    ob.rotation_euler = (target - ob.location).to_track_quat("-Z", "Y").to_euler()


def rot(v, axis, deg):
    from mathutils import Matrix
    return Matrix.Rotation(math.radians(deg), 3, axis) @ v


def place(name):
    tgt, d, fh, (kaz, kel) = SHOTS[name]
    dist = (fh * 0.5) / math.tan(math.atan(cd.sensor_width * 0.5 / cd.lens))
    cam.location = tgt + d * dist
    aim(cam, tgt)
    side = d.cross(UP)
    if side.length < 1e-3:
        side = Vector((1, 0, 0))
    side.normalize()
    kd = rot(rot(d, UP, kaz), side, kel).normalized()
    key.location = tgt + kd * 0.6
    aim(key, tgt)
    key.data.energy = 7.0
    fd = rot(d, UP, -kaz * 0.8).normalized()
    fill.location = tgt + fd * 1.2
    aim(fill, tgt)
    fill.data.energy = 2.0


for pas in A.passes.split(","):
    for o in meshes:
        n = o.name.lower()
        hair = any(k in n for k in ("hair", "beard", "brows", "eyelash"))
        o.hide_render = pas == "clay" and hair
        for i, s in enumerate(o.material_slots):
            s.material = clay if pas == "clay" else orig[o][i]
    for name in A.shots.split(","):
        place(name)
        sc.render.filepath = os.path.join(A.out, f"{pas}_{name}.png")
        bpy.ops.render.render(write_still=True)
        print(f"[views] {pas}_{name}", flush=True)
