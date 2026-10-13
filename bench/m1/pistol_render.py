"""Pistol close-ups (m1 v2 Track H evidence): the gun alone, under the
shared hero rig (neon-noir, on black) and the studio turntable rig (5,600 K
three-point on an 18 % grey cove), from fixed gun-space views.

    blender -b -t 3 --factory-startup --python-exit-code 1 \\
        --python bench/m1/pistol_render.py -- --out DIR \\
        [--detail hero|game] [--glb pistol.glb] [--views q34l,right,top,muzzle,...] \\
        [--light hero|studio|both] [--quality draft|preview|final] [--samples N] \\
        [--res 1600x1000] [--passes beauty,clay]

--glb renders the exported game asset instead of the procedural hero build
(the baked textures, what the game gets). Writes DIR/<light>_<view>[_<pass>].png
and DIR/pistol_render.json.
"""

import argparse
import json
import math
import os
import sys
import time

import bpy
from mathutils import Matrix, Vector

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "blender"))

from hero import rig, sets  # noqa: E402
from props import pistol  # noqa: E402

MM = 0.001
CENTRE = Vector((98.0, 0.0, -52.0)) * MM
# view: (camera direction from the gun centre in gun space (x muzzle, y the
# gun's left, z up), frame height m, lens mm, aim offset mm)
VIEWS = {
    "q34l": ((0.55, 0.85, 0.32), 0.17, 100, (0, 0, 0)),          # 3/4 front-left
    "q34r": ((0.5, -0.85, 0.3), 0.17, 100, (0, 0, 0)),
    "left": ((0.0, 1.0, 0.05), 0.17, 100, (0, 0, 0)),
    "right": ((0.0, -1.0, 0.05), 0.17, 100, (0, 0, 0)),
    "top": ((0.0, -0.08, 1.0), 0.15, 100, (0, 0, 40)),
    "muzzle": ((1.0, -0.22, 0.12), 0.11, 100, (100, 0, 15)),
    "rear34": ((-0.6, -0.6, 0.5), 0.16, 100, (0, 0, 0)),
    "slide_cu": ((0.25, -0.85, 0.5), 0.07, 100, (-20, 0, 50)),      # port, hood, optic cut, serrations
    "comp_cu": ((0.6, 0.55, 0.6), 0.06, 100, (100, 0, 45)),         # compensator ports, crown, front sight
    "grip_cu": ((-0.2, -1.0, 0.0), 0.10, 100, (-75, 0, -35)),      # stippling, magwell, base pad
    "under": ((0.3, -0.5, -0.8), 0.17, 100, (0, 0, 0)),
}


class Stub:
    """Just enough of rig.Character for the light rigs."""

    def __init__(self, objs, centre):
        self.objs = objs
        self.centre = centre

    def aim(self, what):
        return self.centre

    def eyes(self):
        return self.centre, self.centre


def camera(view, root):
    d, frame_h, lens, off = VIEWS[view]
    d = Vector(d).normalized()
    target = root.matrix_world @ (CENTRE + Vector(off) * MM)
    dw = (root.matrix_world.to_3x3() @ d).normalized()
    dist = lens / 24.0 * frame_h
    cd = bpy.data.cameras.new("pcam_" + view)
    cd.lens = lens
    cd.sensor_fit = "VERTICAL"
    cd.sensor_width, cd.sensor_height = 36.0, 24.0
    cd.clip_start, cd.clip_end = 0.01, 100.0
    cam = bpy.data.objects.new(cd.name, cd)
    rig.collection("hero_cams", clear=False).objects.link(cam)
    cam.location = target + dw * dist
    q = (target - cam.location).to_track_quat("-Z", "Y")
    if abs(dw.z) >= 0.95:     # top view: camera up = the gun's left, so the muzzle points right
        z = dw
        y = (root.matrix_world.to_3x3() @ Vector((0, 1, 0))).normalized()
        x = y.cross(z).normalized()
        y = z.cross(x)
        q = Matrix((x, y, z)).transposed().to_quaternion()
    cam.rotation_euler = q.to_euler()
    bpy.context.scene.camera = cam
    return {"obj": cam, "spec": view, "lens": lens, "az": 0.0, "frame_h": frame_h, "fstop": None,
            "subject": target, "aim": target}


def load(a):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    root = bpy.data.objects.new("gun_root", None)
    bpy.context.scene.collection.objects.link(root)
    if a.glb:
        bpy.ops.import_scene.gltf(filepath=a.glb)
        objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
        for o in bpy.context.scene.objects:
            if o.parent is None and o != root:
                o.parent = root
    else:
        parts = pistol.build(a.detail)
        objs = [o for g in parts.values() for o in g]
        for o in objs:
            o.parent = root
    # lift the gun off the floor and turn it a little toward the camera rig
    root.location = (0, 0, 1.2)
    bpy.context.view_layer.update()
    return root, objs


def main(argv):
    ap = argparse.ArgumentParser(prog="pistol_render.py")
    ap.add_argument("--out", required=True)
    ap.add_argument("--detail", default="hero", choices=sorted(pistol.QUALITY))
    ap.add_argument("--glb", default="")
    ap.add_argument("--views", default="q34l,right,top,muzzle")
    ap.add_argument("--light", choices=["hero", "studio", "both"], default="both")
    ap.add_argument("--quality", default="preview", choices=sorted(rig.QUALITY))
    ap.add_argument("--samples", type=int, default=0)
    ap.add_argument("--res", default="1600x1000")
    ap.add_argument("--passes", default="beauty")
    ap.add_argument("--set", dest="set_kind", choices=["void", "alley"], default="alley",
                    help="hero light: the hero stage's alley (neon to reflect) or black")
    a = ap.parse_args(argv)
    rig.PCT = 100
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    t0 = time.perf_counter()
    root, objs = load(a)
    ch = Stub(objs, root.matrix_world @ CENTRE)
    rec = {"detail": a.detail, "glb": a.glb, "tris": pistol.tris(objs), "frames": []}
    res = tuple(int(v) for v in a.res.split("x"))
    lights = ["hero", "studio"] if a.light == "both" else [a.light]
    alley = None
    if "hero" in lights and a.set_kind == "alley":
        alley = sets.alley()
    for view in [v for v in a.views.split(",") if v]:
        for light in lights:
            for name in ("hero_rig", "tt_rig", "tt_cyc", "hero_ground", "hero_haze", "hero_cams"):
                rig.collection(name)
            cam = camera(view, root)
            if alley is not None:
                for o in alley.all_objects:
                    o.hide_render = light == "studio"
            if light == "studio":
                rig.world((0.05, 0.05, 0.05), 1.0)
                rig.turntable_rig(ch, cam)
                # a small grey cove behind the gun (the body-sized one is too far for a 0.2 m frame)
                rig.cyclorama(cam["obj"].location, cam["aim"], back=0.6, radius=0.3, height=1.5, width=3.0)
            else:
                rig.world()
                if alley is not None:
                    c = cam["obj"].location - cam["aim"]
                    sets.turn(math.degrees(math.atan2(c.x, -c.y)) + 15.0)
                rig.hero_rig(ch, cam, subject=cam["aim"], lights={"eye": None},
                             flag=("key", "wrap", "fill") if alley is not None else ())
            for kind in [p for p in a.passes.split(",") if p]:
                settings = rig.cycles(a.quality, res, a.samples or None)
                vs = bpy.context.scene.view_settings
                tt = light == "studio"
                vs.exposure = rig.TT_EXPOSURE if tt else rig.HERO_EXPOSURE
                vs.look = "None" if tt else rig.HERO_LOOK
                if hasattr(vs, "use_white_balance"):
                    vs.use_white_balance = not tt
                    if not tt:
                        vs.white_balance_temperature = rig.HERO_WB
                restore = rig.material_pass(ch, kind) if kind in ("clay", "normal") else None
                if kind == "normal":
                    rig.set_pass_view(kind)
                tag = f"{light}_{view}" + ("" if kind == "beauty" else f"_{kind}")
                secs = rig.render(os.path.join(out, tag + ".png"))
                if restore:
                    restore()
                rec["frames"].append({"file": tag + ".png", "seconds": secs, **settings})
                print(f"[pistol_render] {tag}: {secs} s", flush=True)
    rec["total_s"] = round(time.perf_counter() - t0, 1)
    with open(os.path.join(out, "pistol_render.json"), "w") as f:
        json.dump(rec, f, indent=1)


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
