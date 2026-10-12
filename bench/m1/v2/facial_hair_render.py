"""Facial-hair evidence renders (m1 v2 track C) from a kept build .blend.

    blender -b RUN/character.blend -t 4 --python bench/m1/v2/facial_hair_render.py -- \
        --out DIR [--engine cycles|eevee] [--samples N] [--res PX] \
        [--views bust,profile,moustache,cheek,chin,brow,eye] [--rig studio|neon|both] \
        [--mode hero|game|both]

hero: the strand grooms in the `hero_only` collection, game shells/cards
hidden. game: the GLB geometry (shells, cards), strands hidden. Cameras are
placed off body landmarks (lips, chin, brows, eyes), so they follow the head.
The studio rig matches the look-dev loop (key/fill/rim, AgX, -2.5 EV); the
neon rig is the direction §5 base rig (amber key camera-left, magenta rim
behind-right, teal kicker behind-left, cool fill, eye light).
Writes DIR/<mode>_<rig>_<view>.png and DIR/sheet_<mode>_<rig>.png (ffmpeg).
"""

import argparse
import math
import os
import subprocess
import sys

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--engine", default="cycles", choices=["cycles", "eevee"])
ap.add_argument("--samples", type=int, default=64)
ap.add_argument("--res", type=int, default=768)
ap.add_argument("--views", default="bust,profile,moustache,cheek,chin,brow,eye")
ap.add_argument("--rig", default="studio", choices=["studio", "neon", "both"])
ap.add_argument("--mode", default="hero", choices=["hero", "game", "both"])
ap.add_argument("--exposure", type=float, default=float(os.environ.get("LOOKDEV_EXPOSURE", "-2.5")))
A = ap.parse_args(argv)

GAME_PARTS = ("beard_export", "brows_export", "eyelash")


def look_at(ob, target):
    ob.rotation_euler = (target - ob.location).to_track_quat("-Z", "Y").to_euler()


def group_pts(obj, name, w=0.5):
    g = obj.vertex_groups.get(name)
    if g is None:
        return []
    mw = obj.matrix_world
    return [mw @ v.co for v in obj.data.vertices if any(e.group == g.index and e.weight >= w for e in v.groups)]


def bbox(pts):
    return (Vector([min(p[i] for p in pts) for i in range(3)]),
            Vector([max(p[i] for p in pts) for i in range(3)]))


def surface_point(body, origin_xy_dir, z, x_side):
    """Point on the skin hit by a ray from outside at height z, coming in
    horizontally along -dir (dir: unit vector pointing out of the face)."""
    dg = bpy.context.evaluated_depsgraph_get()
    ev = body.evaluated_get(dg)
    mw = ev.matrix_world
    inv = mw.inverted()
    start = Vector((x_side, 0, z)) + origin_xy_dir * 0.5
    ok, loc, _, _ = ev.ray_cast(inv @ start, (inv.to_3x3() @ -origin_xy_dir).normalized())
    return mw @ loc if ok else start - origin_xy_dir * 0.5


def landmarks():
    body = next(o for o in bpy.data.objects if o.type == "MESH" and o.vertex_groups.get("scalp")
                and not o.hide_render)
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    hb = arm.data.bones["head"]
    head = arm.matrix_world @ ((hb.head_local + hb.tail_local) * 0.5)
    lips_lo, lips_hi = bbox(group_pts(body, "lips", 0.3))
    eyes = next((o for o in bpy.data.objects if o.type == "MESH" and ("eyes_hq" in o.name or "low-poly" in o.name)), None)
    lm = {"head": head, "lips_top": Vector(((lips_lo.x + lips_hi.x) / 2, lips_lo.y, lips_hi.z)),
          "lips_lo": lips_lo, "lips_hi": lips_hi}
    if eyes is not None:
        ep = [eyes.matrix_world @ v.co for v in eyes.data.vertices]
        left = [p for p in ep if p.x > 0]
        lm["eye_l"] = sum(left, Vector()) / len(left)
    hp = group_pts(body, "head")
    front = [p for p in hp if abs(p.x) < 0.02 and p.y < lips_hi.y + 0.03]
    chin_z = min(p.z for p in front)
    lm["chin"] = Vector((0, min(p.y for p in front if p.z < lips_lo.z), chin_z))
    lm["body"] = body
    return lm


def setup_render():
    scene = bpy.context.scene
    r = scene.render
    r.resolution_x = r.resolution_y = A.res
    r.resolution_percentage = 100
    r.image_settings.file_format = "PNG"
    r.film_transparent = False
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = A.exposure
    if A.engine == "cycles":
        r.engine = "CYCLES"
        c = scene.cycles
        c.device = "CPU"
        c.samples = A.samples
        c.use_adaptive_sampling = True
        c.use_denoising = True
        c.denoiser = "OPENIMAGEDENOISE"
        c.max_bounces = 8
        c.transparent_max_bounces = 32
        scene.cycles_curves.shape = "THICK"
        scene.cycles_curves.subdivisions = 2
    else:
        r.engine = "BLENDER_EEVEE"
        scene.eevee.taa_render_samples = max(A.samples, 32)
    world = scene.world or bpy.data.worlds.new("w")
    scene.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.045, 0.045, 0.05, 1)


def clear_lights():
    for o in list(bpy.data.objects):
        if o.type in ("LIGHT", "CAMERA") or o.name.startswith("fh_"):
            bpy.data.objects.remove(o, do_unlink=True)


def area(name, loc, energy, size, color, aim, size_y=None):
    ld = bpy.data.lights.new(name, "AREA")
    ld.energy, ld.color = energy, color
    if size_y is None:
        ld.size = size
    else:
        ld.shape = "RECTANGLE"
        ld.size, ld.size_y = size, size_y
    ob = bpy.data.objects.new(name, ld)
    bpy.context.scene.collection.objects.link(ob)
    ob.location = loc
    look_at(ob, aim)
    return ob


def studio(lm):
    floor = 0.0
    aim = Vector((0, 0, floor + 1.1))
    area("fh_key", Vector((-2.2, -2.6, 2.8)), 900, 1.5, (1.0, 0.96, 0.9), aim)
    area("fh_fill", Vector((2.6, -2.0, 1.4)), 250, 2.0, (0.85, 0.9, 1.0), aim)
    area("fh_rim", Vector((0.8, 2.8, 2.6)), 700, 1.0, (1, 1, 1), aim)


def neon(lm, cam_dir):
    """direction §5 base rig, positioned relative to the camera azimuth."""
    h = lm["head"]
    az = math.atan2(cam_dir.x, -cam_dir.y)

    def at(az_off_deg, elev_deg, dist):
        a = az + math.radians(az_off_deg)
        e = math.radians(elev_deg)
        return h + Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e))) * dist
    k = 120.0  # key energy (W) at 1.5 m
    area("fh_key", at(-40, 25, 1.5), k, 0.8, (1.0, 0.72, 0.42), h)
    area("fh_rim_magenta", at(150, 10, 1.4), k * 0.7 * 2.5, 0.3, (1.0, 0.18, 0.55), h, size_y=1.5)
    area("fh_kick_teal", at(-145, 15, 1.4), k * 0.4 * 2.5, 0.4, (0.1, 0.8, 0.9), h, size_y=1.0)
    area("fh_fill", at(60, -10, 2.0), k * 0.08 * 2.0, 2.0, (0.6, 0.7, 1.0), h)
    area("fh_eye", at(0, 0, 1.2), k * 0.12, 0.1, (1, 1, 1), h)


def view_specs(lm):
    h = lm["head"]
    lt = lm["lips_top"]
    chin = lm["chin"]
    # name: (azimuth deg, frame height m, target)
    eye = lm.get("eye_l", h)
    specs = {
        "bust": (25, 0.42, h + Vector((0, 0, -0.06))),
        "front": (0, 0.30, h + Vector((0, 0, -0.05))),
        "profile": (90, 0.30, h + Vector((0, 0, -0.05))),
        "moustache": (20, 0.055, lt + Vector((0, 0.0, -0.002))),
        "chin": (90, 0.08, chin + Vector((0, 0.02, 0.01))),
        "brow": (15, 0.07, eye + Vector((0, 0, 0.018))),
        "eye": (20, 0.05, eye + Vector((0, 0, 0.004))),
    }
    # cheek line: the skin on the character's left side between the mouth
    # corner and the ear, at cheekbone-low height
    z = (lm["lips_hi"].z + eye.z) / 2 - 0.005
    d = Vector((math.sin(math.radians(60)), -math.cos(math.radians(60)), 0))
    cp = surface_point(lm["body"], d, z, 0.0)
    specs["cheek"] = (60, 0.08, cp)
    return specs


def set_mode(mode):
    hero = bpy.data.collections.get("hero_only")
    if hero is not None:
        hero.hide_render = mode != "hero"
    for o in bpy.data.objects:
        if o.type == "MESH" and any(p in o.name for p in GAME_PARTS):
            o.hide_render = mode == "hero"
    # MPFB lashes / brows proxies are always game geometry
    return hero is not None


def main():
    os.makedirs(A.out, exist_ok=True)
    setup_render()
    lm = landmarks()
    specs = view_specs(lm)
    views = [v for v in A.views.split(",") if v in specs]
    modes = ["hero", "game"] if A.mode == "both" else [A.mode]
    rigs = ["studio", "neon"] if A.rig == "both" else [A.rig]
    scene = bpy.context.scene
    for mode in modes:
        set_mode(mode)
        for rig in rigs:
            files = []
            for v in views:
                clear_lights()
                az, fh, target = specs[v]
                a = math.radians(az)
                axis = Vector((math.sin(a), -math.cos(a), 0.0))
                cd = bpy.data.cameras.new("fh_cam")
                cd.lens = 85.0 if fh > 0.2 else 100.0
                cd.clip_start = 0.01
                dist = (fh * 0.5) / math.tan(math.atan(cd.sensor_width * 0.5 / cd.lens))
                cam = bpy.data.objects.new("fh_cam", cd)
                scene.collection.objects.link(cam)
                cam.location = target + axis * dist
                look_at(cam, target)
                scene.camera = cam
                if rig == "studio":
                    studio(lm)
                else:
                    neon(lm, axis)
                path = os.path.join(A.out, f"{mode}_{rig}_{v}.png")
                scene.render.filepath = path
                bpy.ops.render.render(write_still=True)
                files.append(path)
                print("fh_render", path, f"{fh / A.res * 1000:.3f} mm/px", flush=True)
            if len(files) > 1:
                n = len(files)
                cols = min(n, 4)
                half = A.res // 2
                inputs = sum((["-i", f] for f in files), [])
                filt = "".join(f"[{i}:v]scale={half}:{half}[v{i}];" for i in range(n))
                layout = "|".join(f"{(i % cols) * half}_{(i // cols) * half}" for i in range(n))
                filt += "".join(f"[v{i}]" for i in range(n)) + f"xstack=inputs={n}:layout={layout}:fill=black"
                subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", filt,
                                os.path.join(A.out, f"sheet_{mode}_{rig}.png")], check=True)


main()
