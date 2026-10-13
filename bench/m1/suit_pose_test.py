"""Poke-through test for the layered suit (look-spec §4.3 [auto]).

Imports the GLB, drives the game_engine rig through a set of stress poses and
renders an ID pass (one flat emission colour per mesh, no lighting, no
anti-aliasing) from four cameras. For every pose and view it counts the
pixels of each mesh. Inner layers (waistcoat, shirt, tie, body) may only show
where they show in the rest pose, so their pixel count in a pose, minus the
rest count, is the poke-through estimate; the body's count also moves with
the head and hands, so the body figure is indicative only.

    blender -b -t 4 --factory-startup --python bench/m1/suit_pose_test.py -- \
        --glb RUN/character.glb --out-dir DIR [--res 512] [--poses rest,twist]

Writes DIR/pose_<pose>_<view>.png (ID pass), DIR/beauty_<pose>_<view>.png
(flat-lit, for the eye) and DIR/poke.json.
"""

import argparse
import json
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Euler, Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--glb", required=True)
ap.add_argument("--out-dir", required=True)
ap.add_argument("--res", type=int, default=512)
ap.add_argument("--poses", default="")
ap.add_argument("--no-beauty", action="store_true")
A = ap.parse_args(argv)

# local-axis rotations in degrees (bone space), game_engine names
POSES = {
    "rest": {},
    "stress": {  # blender/pose_check.py
        "upperarm_l": (0, 0, -60), "lowerarm_l": (0, 0, -70),
        "upperarm_r": (60, 0, 30), "lowerarm_r": (0, 0, 80),
        "thigh_l": (-50, 0, 0), "calf_l": (80, 0, 0),
        "spine_02": (0, 20, 0), "spine_03": (0, 15, 0),
        "neck_01": (0, 25, 0), "head": (10, 10, 0),
    },
    "twist": {"spine_01": (0, 15, 0), "spine_02": (0, 25, 0), "spine_03": (0, 20, 0),
              "neck_01": (0, -20, 0)},
    "twist_back": {"spine_01": (0, -15, 0), "spine_02": (0, -25, 0), "spine_03": (0, -20, 0)},
    "arms_up": {"upperarm_l": (0, 0, 95), "upperarm_r": (0, 0, -95)},
    "reach": {"upperarm_l": (70, 0, -20), "lowerarm_l": (0, 0, -90),
              "upperarm_r": (70, 0, 20), "lowerarm_r": (0, 0, 90)},
    "crouch": {"thigh_l": (-85, 0, 0), "calf_l": (110, 0, 0), "thigh_r": (-85, 0, 0),
               "calf_r": (110, 0, 0), "spine_01": (25, 0, 0), "spine_02": (15, 0, 0)},
    "lean": {"spine_01": (35, 0, 0), "spine_02": (15, 0, 0), "thigh_l": (-60, 0, 0),
             "calf_l": (40, 0, 0)},
    "kick": {"thigh_r": (-90, 0, 0), "spine_02": (-10, 0, 0)},
}

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=os.path.abspath(A.glb))
sc = bpy.context.scene
arm = next(o for o in sc.objects if o.type == "ARMATURE")
meshes = [o for o in sc.objects if o.type == "MESH"]
# hair and beard are not part of the test (alpha cards)
for o in meshes:
    if "hair" in o.name or "beard" in o.name or "eyebrow" in o.name or "eyelash" in o.name:
        o.hide_render = True
meshes = [o for o in meshes if not o.hide_render]

sc.render.engine = "BLENDER_EEVEE"
sc.eevee.taa_render_samples = 1
sc.render.filter_size = 0.0
sc.render.resolution_x = sc.render.resolution_y = A.res
sc.view_settings.view_transform = "Standard"
sc.view_settings.look = "None"
sc.render.image_settings.color_mode = "RGB"
sc.world = bpy.data.worlds.new("id")
sc.world.color = (0, 0, 0)

ids = {}
mats_beauty = {}
# ids spread over the 8-bit range: with the hand nails a 14th mesh came in,
# and adjacent ids (1/255 apart) were confused in the dark sRGB range (the
# background sphere counted as the body)
STEP = max(1, 250 // (len(meshes) + 1))
for i, o in enumerate(meshes):
    ids[o.name] = i + 1
    m = bpy.data.materials.new(f"id_{i}")
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    em = nt.nodes.new("ShaderNodeEmission")
    v = (i + 1) * STEP / 255.0
    em.inputs[0].default_value = (v, v, v, 1.0)
    em.inputs[1].default_value = 1.0
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(em.outputs[0], out.inputs[0])
    mats_beauty[o.name] = [s.material for s in o.material_slots]
    for s in o.material_slots:
        s.material = m
    if not o.material_slots:
        o.data.materials.append(m)

cd = bpy.data.cameras.new("cam")
cam = bpy.data.objects.new("cam", cd)
sc.collection.objects.link(cam)
sc.camera = cam
cd.lens = 55
target = Vector((0, 0, 1.0))
VIEWS = [("front", 0), ("three_quarter", 40), ("profile", 90), ("back", 180)]
os.makedirs(A.out_dir, exist_ok=True)


def set_pose(pose):
    for pb in arm.pose.bones:
        pb.rotation_mode = "XYZ"
        pb.rotation_euler = Euler((0, 0, 0))
    for name, deg in pose.items():
        pb = arm.pose.bones.get(name)
        if pb is not None:
            pb.rotation_euler = Euler([math.radians(d) for d in deg], "XYZ")
    bpy.context.view_layer.update()


def render(path):
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(path)
    w, h = img.size
    px = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)
    bpy.data.images.remove(img)
    return px


def count_ids(px):
    # sRGB-encoded by the Standard transform: decode back to linear
    c = px[..., 0]
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    idx = np.rint(lin * 255 / STEP).astype(int)
    out = {}
    for name, i in ids.items():
        out[name] = int((idx == i).sum())
    return out


results = {}
poses = [p for p in A.poses.split(",") if p] or list(POSES)
for pname in poses:
    set_pose(POSES[pname])
    results[pname] = {}
    for tag, az in VIEWS:
        a = math.radians(az)
        cam.location = target + Vector((math.sin(a) * 3.6, -math.cos(a) * 3.6, 0.1))
        cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
        px = render(os.path.join(A.out_dir, f"pose_{pname}_{tag}.png"))
        results[pname][tag] = count_ids(px)

# beauty pass for the eye (flat grey materials, two lights)
if not A.no_beauty:
    sc.view_settings.view_transform = "AgX" if "AgX" in [i.identifier for i in
                                                        sc.view_settings.bl_rna.properties["view_transform"].enum_items] else "Standard"
    sc.eevee.taa_render_samples = 16
    sc.render.filter_size = 1.5
    sc.world.color = (0.25, 0.25, 0.27)
    for name, loc, e in [("key", (-2, -3, 3), 800), ("rim", (1, 3, 2.5), 500)]:
        ld = bpy.data.lights.new(name, "AREA")
        ld.energy, ld.size = e, 2
        ob = bpy.data.objects.new(name, ld)
        sc.collection.objects.link(ob)
        ob.location = loc
        ob.rotation_euler = (Vector((0, 0, 1)) - ob.location).to_track_quat("-Z", "Y").to_euler()
    for o in meshes:
        for s, m in zip(o.material_slots, mats_beauty[o.name]):
            if m is not None:
                s.material = m
    for pname in poses:
        set_pose(POSES[pname])
        for tag, az in VIEWS[:3]:
            a = math.radians(az)
            cam.location = target + Vector((math.sin(a) * 3.6, -math.cos(a) * 3.6, 0.1))
            cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
            sc.render.filepath = os.path.join(A.out_dir, f"beauty_{pname}_{tag}.png")
            bpy.ops.render.render(write_still=True)

# summary: inner layers' pixels over their rest-pose count
inner = [n for n in ids if any(k in n for k in ("waistcoat", "shirt", "tie", "Human_export"))]
summary = {}
for pname in poses:
    if pname == "rest" or "rest" not in results:
        continue
    s = {}
    for tag, _ in VIEWS:
        for n in inner:
            d = results[pname][tag][n] - results["rest"][tag][n]
            key = n.split(".")[-1].replace("_export", "")
            s[f"{tag}.{key}"] = d
    summary[pname] = {"max_over_rest": max(s.values()), "detail": s}
json.dump({"ids": ids, "pixels": results, "poke_over_rest": summary},
          open(os.path.join(A.out_dir, "poke.json"), "w"), indent=1)
for pname, s in summary.items():
    worst = sorted(s["detail"].items(), key=lambda kv: -kv[1])[:3]
    print(f"[pose_test] {pname:12s} max over rest {s['max_over_rest']:6d} px  {worst}")
