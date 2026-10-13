"""Hand close-ups (m1 v2 Track G evidence): one Blender process, several
poses and views, under the shared hero and / or turntable rig.

    blender -b -t 3 --factory-startup --python-exit-code 1 \\
        --python bench/m1/hands_render.py -- --in RUN/character.blend --out DIR \\
        [--shots cuff,rest_back_l,...] [--light hero|turntable|both] \\
        [--quality draft|preview|final] [--samples N] [--res 1080] [--pct 100] \\
        [--passes beauty,clay] [--pierce]

Cameras are placed in the posed hand's own frame (back of the hand, palm,
thumb side, ...), so a view shows the same anatomy in every pose. Depth of
field is off (evidence, not a hero frame). --pierce also reports garment
vertices inside each posed hand (hand_pose.pierce) to DIR/hands.json.
Writes DIR/<light>_<shot>[_<pass>].png and DIR/hands.json.
"""

import argparse
import json
import math
import os
import sys
import time

import bpy
from mathutils import Vector

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "blender"))

from hero import rig  # noqa: E402

# name: (pose, side ('l' | 'r' | 'shot'), view, frame height m, lens mm[, aim])
# view: (back, fingers, thumb) weights of the camera direction in the posed
# hand frame (back = out of the back of the hand, fingers = toward the
# fingertips, thumb = toward the thumb side), plus world up for 'both'.
SHOTS = {
    "rest_back_l":  ("rest", "l", (1.0, -0.15, 0.25), 0.20, 100),
    "rest_palm_l":  ("rest", "l", (-1.0, -0.1, 0.35), 0.20, 100),
    "rest_side_l":  ("rest", "l", (0.45, -0.1, 1.0), 0.20, 100),
    "rest_nails_l": ("rest", "l", (0.85, 0.45, 0.25), 0.09, 100, "tips"),
    "rest_knuckles_l": ("rest", "l", (0.75, 0.0, 0.66), 0.12, 100, "knuckles"),
    "hero_r":       ("stand", "r", (0.7, 0.0, 0.7), 0.22, 100),
    "hero_l":       ("stand", "l", (1.0, -0.2, 0.3), 0.22, 100),
    "cuff":         ("cuff", "shot", (28.0, -5.0), 0.20, 100),
    "cuff_top":     ("cuff", "shot", (-20.0, 10.0), 0.20, 100),
    "ready":        ("ready", "shot", (35.0, 5.0), 0.24, 100),
    "ready_side":   ("ready", "shot", (80.0, 0.0), 0.24, 100),
    # Track H (the pistol in the hands): from the muzzle, the strong-hand side, above
    "ready_front":  ("ready", "shot", (2.0, 4.0), 0.24, 100),
    "ready_r":      ("ready", "shot", (-75.0, 5.0), 0.24, 100),
    "ready_top":    ("ready", "shot", (20.0, 65.0), 0.24, 100),
    "fist_l":       ("f:twist", "l", (0.8, 0.4, 0.4), 0.18, 100),
}
DEFAULT = ["rest_back_l", "rest_palm_l", "hero_r", "cuff", "ready", "fist_l"]


def hand_frame(ch, s, aim=None):
    """Posed (centre, back, fingers, thumb) of hand s, world space. aim:
    None (mid-hand), 'tips' (the middle phalanges to the tips) or
    'knuckles' (the MCP row)."""
    def h(n):
        return ch.bone_head(f"{n}_{s}")
    wrist = h("hand")
    f = (h("middle_01") - wrist).normalized()
    t = h("index_01") - h("pinky_01")
    t = (t - f * t.dot(f)).normalized()
    back = f.cross(t)
    if (h("thumb_02") - wrist).dot(back) > 0:   # the thumb sits on the palm side
        back = -back
    centre = wrist * 0.45 + h("middle_01") * 0.35 + h("middle_02") * 0.2
    if aim == "tips":
        centre = (h("middle_03") + h("ring_03") + h("index_03")) / 3.0
    elif aim == "knuckles":
        centre = (h("middle_01") + h("ring_01")) * 0.5
    return centre, back, f, t


def make_camera(ch, shot):
    pose, side, view, frame_h, lens = SHOTS[shot][:5]
    aim = SHOTS[shot][5] if len(SHOTS[shot]) > 5 else None
    dist = lens / 24.0 * frame_h
    if side == "shot":
        az, el = view
        c = (ch.bone_head("hand_l") + ch.bone_head("hand_r") + ch.bone_head("middle_01_l")
             + ch.bone_head("middle_01_r")) * 0.25
        a, e = math.radians(az), math.radians(el)
        d = Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)))
    else:
        c, back, f, t = hand_frame(ch, side, aim)
        d = (back * view[0] + f * view[1] + t * view[2]).normalized()
    cd = bpy.data.cameras.new("hands_cam_" + shot)
    cd.lens = lens
    cd.sensor_fit = "VERTICAL"
    cd.sensor_width, cd.sensor_height = 36.0, 24.0
    cd.clip_start, cd.clip_end = 0.02, 100.0
    cam = bpy.data.objects.new(cd.name, cd)
    rig.collection("hero_cams", clear=False).objects.link(cam)
    cam.location = c + d * dist
    up = Vector((0, 0, 1))
    if abs(d.dot(up)) > 0.95:
        up = Vector((0, 1, 0))
    cam.rotation_euler = (c - cam.location).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = cam
    return {"obj": cam, "spec": shot, "lens": lens, "az": 0.0, "frame_h": frame_h,
            "fstop": None, "subject": c, "aim": c}


def parse(argv):
    ap = argparse.ArgumentParser(prog="hands_render.py")
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--shots", default=",".join(DEFAULT))
    ap.add_argument("--light", choices=["hero", "turntable", "both"], default="hero")
    ap.add_argument("--quality", default="draft", choices=sorted(rig.QUALITY))
    ap.add_argument("--samples", type=int, default=0)
    ap.add_argument("--res", type=int, default=1080)
    ap.add_argument("--pct", type=int, default=100)
    ap.add_argument("--passes", default="beauty")
    ap.add_argument("--pierce", action="store_true")
    ap.add_argument("--pose", default="", help="pose for every shot instead of its own (e.g. ready+pistol1)")
    return ap.parse_args(argv)


def main(argv):
    a = parse(argv)
    rig.PCT = a.pct
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    ch = rig.load_character(a.inp)
    shots = [s for s in a.shots.split(",") if s]
    lights = ["hero", "turntable"] if a.light == "both" else [a.light]
    rec = {"in": os.path.abspath(a.inp), "frames": [], "poses": {}}
    cur = None
    for shot in shots:
        pose = a.pose or SHOTS[shot][0]
        if pose != cur:
            rec["poses"][pose] = rig.pose(ch, pose)
            cur = pose
            if a.pierce:
                try:
                    from character import hand_pose
                    rec.setdefault("pierce", {})[pose] = hand_pose.pierce(ch.arm)
                    print(f"[hands] pierce {pose}: {rec['pierce'][pose]}", flush=True)
                except ImportError:
                    pass
        for light in lights:
            for name in ("hero_rig", "tt_rig", "tt_cyc", "hero_ground", "hero_haze", "hero_cams", "cal_cards"):
                rig.collection(name)
            cam = make_camera(ch, shot)
            tt = light == "turntable"
            if tt:
                rig.world((0.05, 0.05, 0.05), 1.0)
                rig.turntable_rig(ch, cam)
                rig.cyclorama(cam["obj"].location, cam["subject"])
            else:
                rig.world()
                rig.hero_rig(ch, cam, subject=cam["subject"])
                rig.void_floor()
            res = (a.res, a.res)
            for kind in [p for p in a.passes.split(",") if p]:
                settings = rig.cycles(a.quality, res, a.samples or None)
                vs = bpy.context.scene.view_settings
                vs.exposure = rig.TT_EXPOSURE if tt else rig.HERO_EXPOSURE
                vs.look = "None" if tt else rig.HERO_LOOK
                if hasattr(vs, "use_white_balance"):
                    vs.use_white_balance = not tt
                    if not tt:
                        vs.white_balance_temperature = rig.HERO_WB
                restore = rig.material_pass(ch, kind) if kind in ("clay", "normal") else None
                if kind == "normal":
                    rig.set_pass_view(kind)
                tag = f"{light}_{shot}" + ("" if kind == "beauty" else f"_{kind}")
                t = time.perf_counter()
                rig.render(os.path.join(out, tag + ".png"))
                secs = round(time.perf_counter() - t, 1)
                if restore:
                    restore()
                rec["frames"].append({"file": tag + ".png", "pose": pose, "seconds": secs, **settings})
                print(f"[hands] {tag}: {secs} s", flush=True)
    with open(os.path.join(out, "hands.json"), "w") as f:
        json.dump(rec, f, indent=1)


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
