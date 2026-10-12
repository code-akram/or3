"""Look at a suit drape (blender/character/suit_drape.py) as geometry.

Build with SUIT_DRAPE_DEBUG=DIR (and --save-blend), then:

    blender -b -t 4 --factory-startup --python bench/m1/suit_drape_view.py -- \
        --blend RUN/character.blend --npz DIR/jacket_a0.npz --part suit_jacket --out OUT \
        [--level 2] [--views elbow,back] [--exaggerate 3]

Renders clay views of (a) the simulated cloth at the end of the drape (posed),
(b) the skinned garment at the same pose (no cloth), and (c) the rest garment
displaced by the transferred fold height x exaggerate: what the normal map
encodes. OUT/<view>_{cloth,skin,fold}.png.
"""

import argparse
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--blend", required=True)
ap.add_argument("--npz", required=True)
ap.add_argument("--part", default="suit_jacket")
ap.add_argument("--out", required=True)
ap.add_argument("--level", type=int, default=2)
ap.add_argument("--views", default="elbow,armpit,back,torso34")
ap.add_argument("--exaggerate", type=float, default=3.0)
ap.add_argument("--res", type=int, default=600)
ap.add_argument("--field", default="h", help="h (gated, what ships) or hp (raw high-pass)")
A = ap.parse_args(argv)

VIEWS = {
    "elbow": ((0.2, -1.0, 1.3), (0.42, -0.1, 1.24), 0.3),
    "elbow_side": ((1.2, -0.3, 1.25), (0.42, -0.08, 1.22), 0.35),
    "armpit": ((-0.7, -0.8, 1.05), (-0.24, -0.02, 1.38), 0.35),
    "back": ((0.0, 1.6, 1.2), (0.0, 0.0, 1.15), 0.8),
    "torso34": ((-0.7, -1.0, 1.25), (0, 0, 1.2), 0.75),
    "front": ((0.0, -1.6, 1.2), (0.0, 0.0, 1.15), 0.8),
    "legs": ((0.4, -1.6, 0.5), (0.0, 0.0, 0.5), 1.1),
    "knee_back": ((0.2, 1.4, 0.55), (0.1, 0.0, 0.5), 0.5),
    "crotch": ((0.0, -1.2, 0.85), (0.0, 0.0, 0.85), 0.4),
    "hem": ((0.5, -0.9, 0.2), (0.12, 0.0, 0.12), 0.4),
}

bpy.ops.wm.open_mainfile(filepath=os.path.abspath(A.blend))
sc = bpy.context.scene
src = next(o for o in sc.objects if o.type == "MESH" and A.part in o.name)
z = np.load(A.npz)
for o in list(sc.objects):
    if o.type in ("LIGHT", "CAMERA"):
        bpy.data.objects.remove(o, do_unlink=True)
    elif o.type == "MESH":
        o.hide_render = True

tmp = src.copy()
tmp.data = src.data.copy()
tmp.modifiers.clear()
sc.collection.objects.link(tmp)
m = tmp.modifiers.new("sub", "SUBSURF")
m.levels = m.render_levels = A.level
m.subdivision_type = "SIMPLE"
m.uv_smooth = "NONE"
dg = bpy.context.evaluated_depsgraph_get()
me = bpy.data.meshes.new_from_object(tmp.evaluated_get(dg), depsgraph=dg)
tmp.hide_render = True
n = len(me.vertices)
assert n == len(z["cloth"]), (n, len(z["cloth"]))

clay = bpy.data.materials.new("clay")
clay.use_nodes = True
p = clay.node_tree.nodes["Principled BSDF"]
p.inputs["Base Color"].default_value = (0.45, 0.45, 0.47, 1)
p.inputs["Roughness"].default_value = 0.6


def make(name, co):
    mm = me.copy()
    mm.vertices.foreach_set("co", co.astype(np.float32).ravel())
    mm.update()
    mm.materials.clear()
    mm.materials.append(clay)
    for poly in mm.polygons:
        poly.use_smooth = True
    ob = bpy.data.objects.new(name, mm)
    sc.collection.objects.link(ob)
    return ob


rest = np.empty(n * 3, np.float32)
me.vertices.foreach_get("co", rest)
rest = rest.reshape(-1, 3)
nor = np.empty(n * 3, np.float32)
me.vertices.foreach_get("normal", nor)
nor = nor.reshape(-1, 3)
objs = {"cloth": make("cloth", z["cloth"]), "skin": make("skin", z["skin"]),
        "fold": make("fold", rest + nor * (z[A.field][:, None] * A.exaggerate))}

sc.render.engine = "BLENDER_EEVEE"
sc.eevee.taa_render_samples = 16
sc.render.resolution_x = sc.render.resolution_y = A.res
sc.view_settings.view_transform = "AgX"
sc.world = bpy.data.worlds.new("w")
sc.world.color = (0.05, 0.05, 0.06)
for name, loc, e in (("key", (-1.5, -2.5, 2.5), 600), ("fill", (2, -2, 1.5), 150), ("rim", (0.5, 3, 2.5), 400)):
    ld = bpy.data.lights.new(name, "AREA")
    ld.energy, ld.size = e, 1.5
    ob = bpy.data.objects.new(name, ld)
    sc.collection.objects.link(ob)
    ob.location = loc
    ob.rotation_euler = (Vector((0, 0, 1.1)) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
cd = bpy.data.cameras.new("c")
cd.type = "ORTHO"
cam = bpy.data.objects.new("c", cd)
sc.collection.objects.link(cam)
sc.camera = cam
os.makedirs(A.out, exist_ok=True)
for v in A.views.split(","):
    loc, tgt, size = VIEWS[v]
    cam.location = loc
    cam.rotation_euler = (Vector(tgt) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    cd.ortho_scale = size
    for k, ob in objs.items():
        for o2 in objs.values():
            o2.hide_render = o2 is not ob
        sc.render.filepath = os.path.join(A.out, f"{v}_{k}.png")
        bpy.ops.render.render(write_still=True)
print("[drape_view] done", A.out)
