"""Suit detail renders (bench/m1/suit.md): back, back hem, torso, torso ¾, cuff,
trouser hem front and back. The harness (lookdev.sh) has no back view and its
studio rig runs hot for 0.03-albedo black wool, so these use the same light
layout at -3 EV by default.

    blender -b --factory-startup --python bench/m1/suit_views.py -- \
        --glb RUN/character.glb --out-dir DIR [--exposure -3] [--res 600] [--views back,torso]
"""

import argparse
import os
import sys

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--glb", required=True)
ap.add_argument("--out-dir", required=True)
ap.add_argument("--exposure", type=float, default=-3.0)
ap.add_argument("--res", type=int, default=600)
ap.add_argument("--views", default="")
A = ap.parse_args(argv)

# name: (camera location, target, orthographic frame size in metres)
VIEWS = {
    "back": ((0, 3.2, 1.0), (0, 0, 0.95), 2.0),
    "back_hem": ((0.3, 1.6, 0.9), (0, 0, 0.85), 0.7),
    "torso": ((0, -1.2, 1.35), (0, 0, 1.3), 0.55),
    "torso34": ((-0.7, -1.0, 1.35), (0, 0, 1.25), 0.6),
    "v_bottom": ((-0.5, -0.9, 1.22), (0, -0.1, 1.2), 0.18),
    "cuff": ((0.75, -0.75, 1.25), (0.52, -0.22, 1.14), 0.25),
    "hem": ((0.6, -0.9, 0.25), (0.1, 0, 0.12), 0.45),
    "hem_back": ((0.5, 0.9, 0.2), (0.1, 0, 0.1), 0.45),
}

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=os.path.abspath(A.glb))
sc = bpy.context.scene
sc.render.engine = "BLENDER_EEVEE"
sc.eevee.taa_render_samples = 16
sc.render.resolution_x = sc.render.resolution_y = A.res
sc.view_settings.exposure = A.exposure
sc.world = bpy.data.worlds.new("suit_views")
sc.world.color = (0.02, 0.02, 0.025)


def light(name, loc, energy, size):
    ld = bpy.data.lights.new(name, "AREA")
    ld.energy, ld.size = energy, size
    ob = bpy.data.objects.new(name, ld)
    sc.collection.objects.link(ob)
    ob.location = loc
    ob.rotation_euler = (Vector((0, 0, 1.1)) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()


light("key", (-1.5, -2.5, 2.5), 900, 2)
light("fill", (2, -2, 1.5), 250, 2)
light("rim", (0, 3, 2.5), 700, 2)
light("back", (0.5, 3, 1.0), 400, 2)
cd = bpy.data.cameras.new("suit_views")
cd.type = "ORTHO"
cam = bpy.data.objects.new("suit_views", cd)
sc.collection.objects.link(cam)
sc.camera = cam
os.makedirs(A.out_dir, exist_ok=True)
for name in [v for v in A.views.split(",") if v] or list(VIEWS):
    loc, tgt, size = VIEWS[name]
    cam.location = loc
    cam.rotation_euler = (Vector(tgt) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    cd.ortho_scale = size
    sc.render.filepath = os.path.join(A.out_dir, f"{name}.png")
    bpy.ops.render.render(write_still=True)
    print(f"[suit_views] {sc.render.filepath}", flush=True)
