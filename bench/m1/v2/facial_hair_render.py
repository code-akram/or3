"""Facial-hair evidence renders (m1 v2 track C), under the shared hero and
turntable rigs (blender/hero/rig.py), from a kept build .blend.

    blender -b -t 4 --factory-startup --python-exit-code 1 \
        --python bench/m1/v2/facial_hair_render.py -- --in RUN/character.blend --out DIR \
        [--light hero|turntable|both] [--mode hero|game|both] \
        [--views bust,profile,front,moustache,cheek,chin,jaw,brow,eye] \
        [--res PX] [--samples N] [--engine cycles|eevee]

mode hero: the strand grooms in `hero_only`, the game shells/cards hidden.
mode game: the GLB geometry (shells, cards), the strands hidden. Cameras
are placed off body landmarks (lips, chin, eyes, the beard's cheek line from
the build stats), so they follow the head. Close-ups are ~0.05-0.1 mm/px.
Writes DIR/<mode>_<light>_<view>.png and DIR/sheet_<mode>_<light>.png.
"""

import argparse
import json
import math
import os
import subprocess
import sys

import bpy
from mathutils import Vector

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(REPO, "blender"))
from hero import rig  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--in", dest="inp", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--light", default="hero", choices=["hero", "turntable", "both"])
ap.add_argument("--mode", default="hero", choices=["hero", "game", "both"])
ap.add_argument("--views", default="bust,profile,moustache,cheek,chin,brow,eye")
ap.add_argument("--res", type=int, default=768)
ap.add_argument("--samples", type=int, default=64)
ap.add_argument("--engine", default="cycles", choices=["cycles", "eevee"])
A = ap.parse_args(argv)

GAME_PARTS = ("beard_export", "brows_export", "eyelash")


def group_pts(obj, name, w=0.5):
    g = obj.vertex_groups.get(name)
    if g is None:
        return []
    mw = obj.matrix_world
    return [mw @ v.co for v in obj.data.vertices if any(e.group == g.index and e.weight >= w for e in v.groups)]


def bbox(pts):
    return (Vector([min(p[i] for p in pts) for i in range(3)]),
            Vector([max(p[i] for p in pts) for i in range(3)]))


def ray_to_skin(body, start, direction):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = body.evaluated_get(dg)
    mw = ev.matrix_world
    inv = mw.inverted()
    ok, loc, _, _ = ev.ray_cast(inv @ start, (inv.to_3x3() @ direction).normalized())
    return mw @ loc if ok else None


def landmarks(ch):
    body = next(o for o in ch.objs if o.type == "MESH" and o.vertex_groups.get("scalp"))
    lo, hi = bbox(group_pts(body, "lips", 0.3))
    el, er = ch.eyes()
    hp = group_pts(body, "head")
    front = [p for p in hp if abs(p.x) < 0.02 and p.y < hi.y + 0.03]
    chin = Vector((0, min(p.y for p in front if p.z < lo.z), min(p.z for p in front)))
    lm = {"body": body, "lips_top": Vector(((lo.x + hi.x) / 2, lo.y, hi.z)), "lips_lo": lo,
          "lips_hi": hi, "eye_l": el, "chin": chin, "eyes": (el + er) / 2}
    # the beard's cheek line (profile y, z) from the build stats
    stats = os.path.join(os.path.dirname(os.path.abspath(A.inp)), "character.stats.json")
    cl = None
    if os.path.isfile(stats):
        with open(stats) as f:
            cl = json.load(f).get("beard", {}).get("cheek_line_yz")
    if cl:
        y, z = cl[1]
    else:
        y, z = (lo.y + 0.05, (hi.z + el.z) / 2)
    hit = ray_to_skin(body, Vector((0.3, y, z)), Vector((-1, 0, 0)))
    lm["cheek"] = hit if hit is not None else Vector((0.06, y, z))
    return lm


def views(lm):
    """name: (azimuth deg, elevation deg, lens, frame height m, aim)."""
    eyes = lm["eyes"]
    return {
        "bust": (25, 3, 85, 0.40, eyes + Vector((0, 0.02, -0.07))),
        "front": (0, 0, 85, 0.28, eyes + Vector((0, 0.02, -0.06))),
        "profile": (90, 0, 100, 0.30, eyes + Vector((0, 0.03, -0.06))),
        "moustache": (18, 2, 100, 0.055, lm["lips_top"] + Vector((0, 0.0, -0.002))),
        "cheek": (65, 5, 100, 0.07, lm["cheek"]),
        "chin": (90, -5, 100, 0.08, lm["chin"] + Vector((0, 0.025, -0.005))),
        "jaw": (45, -15, 100, 0.10, lm["chin"] + Vector((0.03, 0.035, 0.01))),
        "brow": (12, 3, 100, 0.07, lm["eye_l"] + Vector((-0.01, 0, 0.016))),
        "eye": (15, 2, 135, 0.045, lm["eye_l"] + Vector((0, 0, 0.003))),
    }


def camera(ch, name, spec):
    az, el, lens, frame_h, aim = spec
    a, e = math.radians(az), math.radians(el)
    dist = lens / 24.0 * frame_h
    loc = aim + (Vector((math.sin(a), -math.cos(a), 0)) * math.cos(e) + Vector((0, 0, 1)) * math.sin(e)) * dist
    cd = bpy.data.cameras.new("fh_cam_" + name)
    cd.lens = lens
    cd.sensor_fit = "VERTICAL"
    cd.sensor_width, cd.sensor_height = 36.0, 24.0
    cd.clip_start, cd.clip_end = 0.01, 200.0
    cam = bpy.data.objects.new(cd.name, cd)
    rig.collection("hero_cams", clear=False).objects.link(cam)
    cam.location = loc
    rig.look_at(cam, aim)
    bpy.context.scene.camera = cam
    return {"obj": cam, "subject": ch.aim("eyes"), "aim": aim}


def set_mode(mode):
    hero = bpy.data.collections.get("hero_only")
    if hero is not None:
        hero.hide_render = mode != "hero"
    for o in bpy.data.objects:
        if o.type == "MESH" and any(p in o.name for p in GAME_PARTS):
            o.hide_render = mode == "hero"


def sheet(files, out):
    n = len(files)
    cols = min(n, 4)
    half = A.res // 2
    inputs = sum((["-i", f] for f in files), [])
    filt = "".join(f"[{i}:v]scale={half}:{half}[v{i}];" for i in range(n))
    layout = "|".join(f"{(i % cols) * half}_{(i // cols) * half}" for i in range(n))
    filt += "".join(f"[v{i}]" for i in range(n)) + f"xstack=inputs={n}:layout={layout}:fill=black"
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", filt, out], check=True)


def main():
    os.makedirs(A.out, exist_ok=True)
    ch = rig.load_character(A.inp)
    lm = landmarks(ch)
    vs = views(lm)
    names = [v for v in A.views.split(",") if v in vs]
    modes = ["hero", "game"] if A.mode == "both" else [A.mode]
    lights = ["hero", "turntable"] if A.light == "both" else [A.light]
    for mode in modes:
        set_mode(mode)
        for light in lights:
            files = []
            for v in names:
                for c in ("hero_rig", "tt_rig", "tt_cyc", "hero_ground", "hero_cams"):
                    rig.collection(c)
                cam = camera(ch, v, vs[v])
                if light == "hero":
                    rig.world()
                    rig.hero_rig(ch, cam)
                    rig.void_floor()
                    exposure, look = rig.HERO_EXPOSURE, rig.HERO_LOOK
                else:
                    rig.world((0.05, 0.05, 0.05), 1.0)
                    rig.turntable_rig(ch, cam)
                    rig.cyclorama(cam["obj"].location, ch.aim("body"))
                    exposure, look = rig.TT_EXPOSURE, "None"
                rig.cycles("final", (A.res, A.res), A.samples)
                sc = bpy.context.scene
                sc.cycles.adaptive_threshold = 0.03
                sc.cycles_curves.shape = "THICK"
                sc.cycles_curves.subdivisions = 3
                if A.engine == "eevee":
                    sc.render.engine = "BLENDER_EEVEE"
                    sc.eevee.taa_render_samples = max(A.samples, 32)
                sc.view_settings.exposure = exposure
                sc.view_settings.look = look
                path = os.path.join(A.out, f"{mode}_{light}_{v}.png")
                secs = rig.render(path)
                files.append(path)
                print(f"fh_render {path} {vs[v][3] / A.res * 1000:.3f} mm/px {secs:.1f} s", flush=True)
            if len(files) > 1:
                sheet(files, os.path.join(A.out, f"sheet_{mode}_{light}.png"))


main()
