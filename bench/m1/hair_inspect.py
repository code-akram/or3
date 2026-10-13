"""Hair inspection renders of one look-dev run: the head at 1024² from several
views, under the look-dev studio rig or the shared hero / turntable rigs
(blender/hero/rig.py, Track E), from the GLB (the game cards) or from the kept
.blend (the hero strand groom in `hero_only`, Cycles). For eyes only; adds
nothing to metrics.json.

    blender -b -t 4 --factory-startup --python bench/m1/hair_inspect.py -- \
        RUN_DIR [--out DIR] [--res 1024] [--source glb|blend] \
        [--rig studio|hero|turntable] [--engine eevee|cycles] [--samples N] \
        [--views a,b,c] [--tag NAME] [--hide-obj a,b] [--hide-mat NAME]

--source blend needs RUN_DIR/character.blend (KEEP_BLEND=1): the card hair is
hidden and the groom shown. Writes <out>/<tag><view>.png and
<out>/<tag>sheet.png (ffmpeg). Default: glb, studio, eevee, the 6 classic
views, out RUN_DIR/hair, tag "".

Views: front, closeup (25°), side, back34, back, game (body at 1 m frame),
bust (0.62 m), hairline (left temple and the part, 0.13 m), hairline_r
(right temple, the front falls), part (from above-front, 0.16 m), nape (the
ends over the collar, from behind, 0.2 m).
"""

import math
import os
import subprocess
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "blender"))

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def opt(name, default):
    return argv[argv.index(name) + 1] if name in argv else default


RUN = os.path.abspath(argv[0])
OUT = opt("--out", os.path.join(RUN, "hair"))
RES = int(opt("--res", "1024"))
SOURCE = opt("--source", "glb")
RIG = opt("--rig", "studio")
ENGINE = opt("--engine", "cycles" if SOURCE == "blend" else "eevee")
SAMPLES = int(opt("--samples", "128" if ENGINE == "cycles" else "32"))
TAG = opt("--tag", "")
HIDE_MAT = opt("--hide-mat", "")  # debug: a material name made fully transparent
HIDE_OBJ = [n for n in opt("--hide-obj", "").split(",") if n]  # objects hidden from the render
# name: (azimuth deg from the character's front, elevation deg, frame height m, lens mm, anchor)
ALL = {"front": (0, 0, 0.34, 85, "head"), "closeup": (25, 0, 0.34, 85, "head"),
       "side": (90, 0, 0.34, 85, "head"), "back34": (140, 0, 0.40, 85, "head"),
       "back": (180, 0, 0.46, 85, "head"), "game": (25, 0, 1.0, 50, "body"),
       "bust": (25, 3, 0.62, 85, "bust"), "hairline": (30, 12, 0.13, 100, "hairline_l"),
       "hairline_r": (-35, 8, 0.15, 100, "hairline_r"), "part": (10, 55, 0.18, 100, "part"),
       "nape": (165, 5, 0.22, 100, "nape")}
VIEWS = opt("--views", "front,closeup,side,back34,back,game").split(",")


def look_at(ob, target):
    ob.rotation_euler = (target - ob.location).to_track_quat("-Z", "Y").to_euler()


def load():
    if SOURCE == "blend":
        bpy.ops.wm.open_mainfile(filepath=os.path.join(RUN, "character.blend"))
        arm = next(o for o in bpy.context.scene.objects if o.type == "ARMATURE")
        for o in bpy.context.scene.objects:
            if o.type in ("LIGHT", "CAMERA"):
                o.hide_render = True
            # The game cards (and the old card hair) give way to the groom.
            if o.type == "MESH" and "hair_export" in o.name:
                o.hide_render = True
        hero = bpy.data.collections.get("hero_only")
        if hero is not None:
            for o in hero.objects:
                o.hide_render = False
        return arm
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    bpy.ops.import_scene.gltf(filepath=os.path.join(RUN, "character.glb"))
    arm = next(o for o in bpy.context.scene.objects if o.type == "ARMATURE")
    for o in bpy.context.scene.objects:
        if o.type == "MESH" and o.parent != arm:
            o.hide_render = True
    return arm


def world_verts(o):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = o.evaluated_get(dg)
    me = ev.to_mesh()
    mw = o.matrix_world
    out = ([mw @ v.co for v in me.vertices],
           [list(p.vertices) for p in me.polygons], [p.material_index for p in me.polygons])
    ev.to_mesh_clear()
    return out


def cap_points():
    """World points of the hairline cap (GLB: the hair mesh's `hair`
    material faces; blend: the hero scalp tint)."""
    for o in bpy.context.scene.objects:
        if o.type != "MESH":
            continue
        if SOURCE == "blend" and o.name.startswith("hair_groom_scalp"):
            return world_verts(o)[0]
        if SOURCE == "glb" and "hair" in o.name.lower() and "beard" not in o.name.lower():
            mats = [m.name if m else "" for m in o.data.materials]
            if "hair" not in mats:
                continue
            k = mats.index("hair")
            vs, polys, mi = world_verts(o)
            idx = set(i for p, m in zip(polys, mi) if m == k for i in p)
            return [vs[i] for i in idx]
    return []


def anchors(arm):
    bone = arm.data.bones["head"]
    head = arm.matrix_world @ ((bone.head_local + bone.tail_local) * 0.5)
    a = {"head": head - Vector((0, 0, 0.03)), "body": head - Vector((0, 0, 0.25)),
         "bust": head - Vector((0, 0, 0.13))}
    cap = cap_points()
    if cap:
        cx = sum(p.x for p in cap) / len(cap)
        cy = sum(p.y for p in cap) / len(cap)

        def front_in(x0, x1):
            pts = [p for p in cap if x0 <= p.x - cx <= x1 and p.y < cy]
            return min(pts, key=lambda p: p.y) if pts else head

        # The cap's character-left is +x.
        a["hairline_l"] = front_in(0.015, 0.045) + Vector((0, 0, -0.01))
        a["hairline_r"] = front_in(-0.06, -0.035) + Vector((0, 0, -0.025))
        top = max(cap, key=lambda p: p.z)
        a["part"] = Vector((cx + 0.012, (front_in(-0.01, 0.01).y + top.y) / 2, top.z - 0.01))
        a["nape"] = Vector((cx, cy + 0.03, head.z - 0.11))
    else:
        for k in ("hairline_l", "hairline_r", "part", "nape"):
            a[k] = head
    return a


def studio(scene):
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


def main():
    arm = load()
    scene = bpy.context.scene
    a = anchors(arm)
    if HIDE_MAT and HIDE_MAT in bpy.data.materials:
        nt = bpy.data.materials[HIDE_MAT].node_tree
        p = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
        for l in list(p.inputs["Alpha"].links):
            nt.links.remove(l)
        p.inputs["Alpha"].default_value = 0.0
    for name in HIDE_OBJ:
        if name in bpy.data.objects:
            bpy.data.objects[name].hide_render = True
    rig = ch = None
    if RIG in ("hero", "turntable"):
        from hero import rig
        ch = rig._character_from_scene()
    else:
        studio(scene)
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = float(os.environ.get("LOOKDEV_EXPOSURE", "-2.5"))
    r = scene.render
    if rig is not None:
        rig.cycles("final", (RES, RES), SAMPLES)
        scene.cycles_curves.shape = "THICK"
        scene.cycles_curves.subdivisions = 2
    elif ENGINE == "cycles":
        r.engine = "CYCLES"
        scene.cycles.device = "CPU"
        scene.cycles.samples = SAMPLES
        scene.cycles.use_denoising = True
        scene.cycles.denoiser = "OPENIMAGEDENOISE"
        scene.cycles.max_bounces = 12
        scene.cycles.transparent_max_bounces = 64
        scene.cycles_curves.shape = "THICK"
        scene.cycles_curves.subdivisions = 2
        scene.cycles.seed = 0
    else:
        r.engine = "BLENDER_EEVEE"
        scene.eevee.taa_render_samples = SAMPLES
    r.resolution_x = r.resolution_y = RES
    r.resolution_percentage = 100
    r.film_transparent = False
    r.image_settings.file_format = "PNG"
    os.makedirs(OUT, exist_ok=True)
    for name in VIEWS:
        az, el, frame_h, lens, anchor = ALL[name]
        cd = bpy.data.cameras.new(name)
        cd.lens = lens
        cd.clip_start = 0.01
        cam = bpy.data.objects.new(name, cd)
        scene.collection.objects.link(cam)
        target = a[anchor].copy()
        dist = (frame_h * 0.5) / math.tan(math.atan(cd.sensor_width * 0.5 / lens))
        az_r, el_r = math.radians(az), math.radians(el)
        cam.location = target + Vector((math.sin(az_r) * math.cos(el_r), -math.cos(az_r) * math.cos(el_r),
                                        math.sin(el_r))) * dist
        look_at(cam, target)
        scene.camera = cam
        if rig is not None:
            for col in ("hero_rig", "tt_rig", "tt_cyc", "hero_ground"):
                rig.collection(col)
            camd = {"obj": cam, "subject": ch.aim("eyes")}
            vs = scene.view_settings
            if RIG == "hero":
                rig.world()
                rig.hero_rig(ch, camd)
                rig.void_floor()
                vs.exposure, vs.look = rig.HERO_EXPOSURE, rig.HERO_LOOK
            else:
                rig.world((0.05, 0.05, 0.05), 1.0)
                rig.turntable_rig(ch, camd)
                rig.cyclorama(cam.location, ch.aim("body"))
                vs.exposure, vs.look = rig.TT_EXPOSURE, "None"
        r.filepath = os.path.join(OUT, TAG + name + ".png")
        bpy.ops.render.render(write_still=True)
    names = VIEWS
    cols = 3 if len(names) > 4 else len(names)
    rows = (len(names) + cols - 1) // cols
    half = RES // 2
    inputs = sum((["-i", os.path.join(OUT, TAG + n + ".png")] for n in names), [])
    layout = "|".join(f"{(i % cols) * half}_{(i // cols) * half}" for i in range(len(names)))
    filt = "".join(f"[{i}:v]scale={half}:{half}[v{i}];" for i in range(len(names)))
    if len(names) > 1:
        filt += "".join(f"[v{i}]" for i in range(len(names))) + f"xstack=inputs={len(names)}:layout={layout}"
    else:
        filt = f"[0:v]scale={half}:{half}"
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", filt,
                    os.path.join(OUT, TAG + "sheet.png")], check=True)
    print("hair_inspect ->", os.path.join(OUT, TAG + "sheet.png"), f"({rows}x{cols})")


main()
