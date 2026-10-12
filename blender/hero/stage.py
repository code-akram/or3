"""Hero stage: render the shot list in the neon-noir alley and the honesty
turntable for one character build (bench/m1/hero.sh drives it).

    blender -b -t 16 --factory-startup --python-exit-code 1 --python blender/hero/stage.py -- \\
        --in RUN/character.blend --out DIR [--quality preview|final|draft] \\
        [--shots portrait,sign,...|all|none] [--turntable] [--set alley|void]

Per hero shot: pose, camera, hero rig (+ shot overrides), haze behind the
subject, rain in the view volume; renders a scene-linear multilayer EXR
(Combined + IndexOB, character = index 1) to DIR/exr/<shot>.exr. grade.py
turns those into DIR/<shot>.png and DIR/<shot>_paint.png. The turntable
renders straight to DIR/turntable/<pose>_<view>[_<pass>].png (no grade).
Writes DIR/stage.json (per-shot render seconds, samples, pose logs).
"""

import argparse
import json
import os
import sys
import time

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.dirname(HERE) not in sys.path:
    sys.path.insert(0, os.path.dirname(HERE))

from hero import poses, rig, sets, shots  # noqa: E402

TRANSIENT = ("hero_rig", "tt_rig", "tt_cyc", "hero_ground", "hero_haze", "hero_cams", "set_rain", "cal_cards")


def clear_transient():
    for name in TRANSIENT:
        rig.collection(name)


def render_shot(ch, name, spec, quality, out_dir, set_kind):
    clear_transient()
    ch.pose_log = poses.apply(ch.arm, spec["pose"])
    res = spec["res"]
    settings = rig.cycles(quality, res)
    cam = rig.camera(ch, spec["cam"])
    cam["obj"].data.shift_x = spec.get("shift", 0.0)
    cam["obj"].data.shift_y = spec.get("shift_y", 0.0)
    if set_kind == "alley":
        sets.turn(cam["az"] + spec.get("set_yaw", 15.0))
    lights = dict(spec.get("lights") or {})
    rig.hero_rig(ch, cam, lights=lights)
    if set_kind == "void":
        rig.world()
        rig.void_floor()
    if spec.get("haze"):
        rig.haze(cam, density=spec["haze"])
    n_rain = 0
    if spec.get("rain") and set_kind == "alley":
        el, er = ch.eyes()
        n_rain = sets.rain(cam, count=spec["rain"], avoid=((el + er) * 0.5, 0.35))
    vl = bpy.context.view_layer
    vl.use_pass_object_index = True
    sc = bpy.context.scene
    sc.view_settings.exposure = 0.0
    sc.render.image_settings.media_type = "MULTI_LAYER_IMAGE"
    sc.render.image_settings.file_format = "OPEN_EXR_MULTILAYER"
    sc.render.image_settings.color_depth = "16"
    sc.render.image_settings.exr_codec = "DWAA"
    sc.render.use_compositing = False
    path = os.path.join(out_dir, "exr", name + ".exr")
    sc.render.filepath = path
    t = time.perf_counter()
    bpy.ops.render.render(write_still=True)
    secs = round(time.perf_counter() - t, 1)
    print(f"[stage] {name}: {secs} s ({settings['samples']} spp, {res[0]}x{res[1]} @ {settings['pct']} %)",
          flush=True)
    return {"shot": name, "seconds": secs, "exposure": rig.HERO_EXPOSURE + spec.get("ev", 0.0),
            "cam": spec["cam"], "pose": spec["pose"], "pose_log": ch.pose_log, "rain": n_rain,
            "haze": spec.get("haze", 0.0), **settings}


def render_turntable(ch, quality, out_dir, views, poses_, passes):
    tdir = os.path.join(out_dir, "turntable")
    os.makedirs(tdir, exist_ok=True)
    hidden = [(o, o.hide_render) for o in bpy.data.objects
              if any(c.name.startswith("set_") for c in o.users_collection)]
    for o, _ in hidden:
        o.hide_render = True
    recs = []
    for pose in poses_:
        ch.pose_log = poses.apply(ch.arm, pose)
        for view in views:
            clear_transient()
            cam = rig.camera(ch, view, dof=False)
            rig.world((0.05, 0.05, 0.05), 1.0)
            rig.turntable_rig(ch, cam)
            rig.cyclorama(cam["obj"].location, ch.aim("body"))
            for kind in passes:
                st = rig.cycles(quality, shots.TT_RES)
                vs = bpy.context.scene.view_settings
                vs.exposure = rig.TT_EXPOSURE
                vs.look = "None"
                restore = None
                if kind != "beauty":
                    restore = rig.material_pass(ch, kind)
                    rig.set_pass_view(kind)
                    if kind == "normal":
                        bpy.context.scene.cycles.samples = 16
                        bpy.context.scene.cycles.use_denoising = False
                tag = f"{pose}_{view}" + ("" if kind == "beauty" else "_" + kind)
                secs = rig.render(os.path.join(tdir, tag + ".png"))
                if restore:
                    restore()
                recs.append({"file": "turntable/" + tag + ".png", "pose": pose, "view": view, "pass": kind,
                             "seconds": secs, "samples": bpy.context.scene.cycles.samples, "pct": st["pct"]})
                print(f"[stage] turntable {tag}: {secs} s", flush=True)
    for o, hid in hidden:
        o.hide_render = hid
    return recs


def skin_sss(ch, weight=1.0, radius=(1.0, 0.25, 0.12), scale=0.0025):
    """Render-side only: if the build's skin has no subsurface (weight 0),
    give it direction §2 Track A's Cycles values so the stage shows what the
    light does to skin. Reported in stage.json; Track A owns the real value."""
    done = []
    for o in ch.objs:
        for s in o.material_slots:
            m = s.material
            if not m or not m.name.startswith("skin_") or m.name in done:
                continue
            p = rig._principled(m)
            if p is None or p.inputs["Subsurface Weight"].default_value > 0:
                continue
            p.subsurface_method = "RANDOM_WALK_SKIN"
            p.inputs["Subsurface Weight"].default_value = weight
            p.inputs["Subsurface Radius"].default_value = radius
            p.inputs["Subsurface Scale"].default_value = scale
            if "Subsurface Anisotropy" in p.inputs:
                p.inputs["Subsurface Anisotropy"].default_value = 0.8
            done.append(m.name)
    return done


def main(argv):
    ap = argparse.ArgumentParser(prog="stage.py")
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--quality", choices=sorted(rig.QUALITY), default="preview")
    ap.add_argument("--shots", default="all")
    ap.add_argument("--turntable", action="store_true")
    ap.add_argument("--tt-views", default=",".join(shots.TT_VIEWS))
    ap.add_argument("--tt-poses", default=",".join(shots.TT_POSES))
    ap.add_argument("--tt-passes", default=",".join(shots.TT_PASSES))
    ap.add_argument("--set", dest="set_kind", choices=["alley", "void"], default="alley")
    ap.add_argument("--skin-sss", choices=["auto", "off"], default="auto",
                    help="auto: fill in Cycles SSS when the build's skin has none (render-side)")
    a = ap.parse_args(argv)
    out = os.path.abspath(a.out)
    os.makedirs(os.path.join(out, "exr"), exist_ok=True)
    t0 = time.perf_counter()
    ch = rig.load_character(a.inp)
    for o in ch.objs:
        o.pass_index = 1
    rec = {"in": os.path.abspath(a.inp), "quality": a.quality, "set": a.set_kind,
           "blender": bpy.app.version_string, "threads": bpy.context.scene.render.threads,
           "hero_only": [o.name for o in ch.objs if any(c.name == "hero_only" for c in o.users_collection)],
           "skin_sss_added": skin_sss(ch) if a.skin_sss == "auto" else [],
           "shots": [], "turntable": []}
    names = shots.ORDER if a.shots == "all" else ([] if a.shots == "none" else a.shots.split(","))
    if names and a.set_kind == "alley":
        t = time.perf_counter()
        sets.alley()
        rec["set_build_s"] = round(time.perf_counter() - t, 2)
    for n in names:
        rec["shots"].append(render_shot(ch, n, shots.SHOTS[n], a.quality, out, a.set_kind))
        with open(os.path.join(out, "stage.json"), "w") as f:
            json.dump(rec, f, indent=1)
    if a.turntable:
        rec["turntable"] = render_turntable(ch, a.quality, out, a.tt_views.split(","),
                                            a.tt_poses.split(","), a.tt_passes.split(","))
    rec["total_s"] = round(time.perf_counter() - t0, 1)
    with open(os.path.join(out, "stage.json"), "w") as f:
        json.dump(rec, f, indent=1)


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
