"""Hair/beard inspection renders: the head of one look-dev run at 1024² from
five azimuths (front, close-up angle, side, back three-quarter, back), plus a
game-distance shot, in the same neutral studio as the look-dev loop. The loop's
512² close-up is too coarse to judge strand detail; this is for eyes only and
adds nothing to metrics.json.

    blender -b -t 4 --factory-startup --python bench/m1/hair_inspect.py -- \
        RUN_DIR [--out RUN_DIR/hair] [--res 1024]

Writes <out>/<view>.png and <out>/sheet.png (needs ffmpeg for the sheet).
"""

import math
import os
import subprocess
import sys

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
RUN = os.path.abspath(argv[0])
OUT = argv[argv.index("--out") + 1] if "--out" in argv else os.path.join(RUN, "hair")
RES = int(argv[argv.index("--res") + 1]) if "--res" in argv else 1024
# name: (azimuth deg from the character's front, frame height m, lens mm)
VIEWS = {"front": (0, 0.34, 85), "closeup": (25, 0.34, 85), "side": (90, 0.34, 85),
         "back34": (140, 0.40, 85), "back": (180, 0.46, 85), "game": (25, 1.0, 50)}


def look_at(ob, target):
    ob.rotation_euler = (target - ob.location).to_track_quat("-Z", "Y").to_euler()


def main():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    bpy.ops.import_scene.gltf(filepath=os.path.join(RUN, "character.glb"))
    arm = next(o for o in bpy.context.scene.objects if o.type == "ARMATURE")
    for o in bpy.context.scene.objects:
        if o.type == "MESH" and o.parent != arm:
            o.hide_render = True
    bone = arm.data.bones["head"]
    head = arm.matrix_world @ ((bone.head_local + bone.tail_local) * 0.5)
    scene = bpy.context.scene
    world = scene.world or bpy.data.worlds.new("studio")
    scene.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.045, 0.045, 0.05, 1)
    aim = Vector((0, 0, 1.1))
    for name, loc, energy, size, color in (
            ("key", (-2.2, -2.6, 2.8), 900, 1.5, (1.0, 0.96, 0.9)),
            ("fill", (2.6, -2.0, 1.4), 250, 2.0, (0.85, 0.9, 1.0)),
            ("rim", (0.8, 2.8, 2.6), 700, 1.0, (1, 1, 1))):
        ld = bpy.data.lights.new(name, "AREA")
        ld.energy, ld.size, ld.color = energy, size, color
        ob = bpy.data.objects.new(name, ld)
        scene.collection.objects.link(ob)
        ob.location = Vector(loc)
        look_at(ob, aim)
    # Same view transform and exposure as the look-dev loop (lookdev_render.py).
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = float(os.environ.get("LOOKDEV_EXPOSURE", "-2.5"))
    r = scene.render
    r.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = 32
    r.resolution_x = r.resolution_y = RES
    r.image_settings.file_format = "PNG"
    os.makedirs(OUT, exist_ok=True)
    for name, (az, frame_h, lens) in VIEWS.items():
        cd = bpy.data.cameras.new(name)
        cd.lens = lens
        cam = bpy.data.objects.new(name, cd)
        scene.collection.objects.link(cam)
        a = math.radians(az)
        target = head.copy()
        target.z -= 0.03 if frame_h < 0.5 else 0.25
        dist = (frame_h * 0.5) / math.tan(math.atan(cd.sensor_width * 0.5 / lens))
        cam.location = target + Vector((math.sin(a), -math.cos(a), 0.0)) * dist
        look_at(cam, target)
        scene.camera = cam
        r.filepath = os.path.join(OUT, name + ".png")
        bpy.ops.render.render(write_still=True)
    names = list(VIEWS)
    inputs = sum((["-i", os.path.join(OUT, n + ".png")] for n in names), [])
    half = RES // 2
    layout = "|".join(f"{(i % 3) * half}_{(i // 3) * half}" for i in range(len(names)))
    filt = "".join(f"[{i}:v]scale={half}:{half}[v{i}];" for i in range(len(names)))
    filt += "".join(f"[v{i}]" for i in range(len(names))) + f"xstack=inputs={len(names)}:layout={layout}"
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", filt,
                    os.path.join(OUT, "sheet.png")], check=True)
    print("hair_inspect ->", os.path.join(OUT, "sheet.png"))


main()
