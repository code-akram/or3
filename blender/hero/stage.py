"""Hero stage: render the shot list in the neon-noir alley and the honesty
turntable for one character build (bench/m1/hero.sh drives it).

    blender -b -t 16 --factory-startup --python-exit-code 1 --python blender/hero/stage.py -- \\
        --in RUN/character.blend --out DIR [--quality preview|final|draft] \\
        [--shots portrait,sign,...|all|none] [--turntable] [--set alley|void] [--crop close|LIST]

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
import resource
import sys
import time

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.dirname(HERE) not in sys.path:
    sys.path.insert(0, os.path.dirname(HERE))

from hero import poses, rig, sets, shots, wet  # noqa: E402

TRANSIENT = ("hero_rig", "tt_rig", "tt_cyc", "hero_ground", "hero_haze", "hero_cams", "set_rain", "cal_cards",
             "hero_wet")


def peak_mb():
    """The process's peak resident memory so far, MB (monotonic: a shot's
    value is the peak up to and including that shot)."""
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0)


def clear_transient():
    for name in TRANSIENT:
        rig.collection(name)


def render_crop(ch, name, spec, cam, out_dir, size=0.5):
    """Close-up evidence: the same shot at 100 % resolution, cropped to
    `size` of the frame around the near eye (head shots) or the camera's
    focus target, or the shot's `crop_at` (("hands", size): between the
    hands; ("eyes", size): the head of a full-body shot). Writes exr/<name>_crop.exr; returns its record."""
    from bpy_extras.object_utils import world_to_camera_view
    sc = bpy.context.scene
    r = sc.render
    aim = rig._parse_cam(spec["cam"])[3]
    if aim in ("eyes", "head"):
        pt = ch.aim("eyes")
    elif aim == "cuff_feet":
        pt = ch.bone_head("hand_l")
    else:
        pt = cam["aim"]
    if spec.get("crop_at"):
        at, size = spec["crop_at"]
        if at == "hands":
            pt = (ch.bone_head("middle_01_l") + ch.bone_head("middle_01_r")) * 0.5
        elif at == "eyes":
            pt = ch.aim("eyes")
    v = world_to_camera_view(sc, cam["obj"], pt)
    cx = min(max(v.x, size / 2), 1 - size / 2)
    cy = min(max(v.y, size / 2), 1 - size / 2)
    pct = r.resolution_percentage
    r.resolution_percentage = 100
    r.use_border, r.use_crop_to_border = True, True
    r.border_min_x, r.border_max_x = cx - size / 2, cx + size / 2
    r.border_min_y, r.border_max_y = cy - size / 2, cy + size / 2
    path = os.path.join(out_dir, "exr", name + "_crop.exr")
    r.filepath = path
    t = time.perf_counter()
    try:
        bpy.ops.render.render(write_still=True)
    finally:
        r.use_border = r.use_crop_to_border = False
        r.resolution_percentage = pct
    secs = round(time.perf_counter() - t, 1)
    w, h = round(r.resolution_x * size), round(r.resolution_y * size)
    mb = peak_mb()
    print(f"[stage] {name}_crop: {secs} s ({w}x{h} at 100 %), peak {mb} MB", flush=True)
    return {"shot": name + "_crop", "seconds": secs, "crop_of": name, "res": [w, h], "pct": 100,
            "samples": sc.cycles.samples, "peak_mb": mb}


# T17 (bench/m1/v4/checkpoint-3.md §2.2, fable_review §4.7 item 7): the film filter and the denoiser
# erased the skin detail T12 added. Every hero shot now uses a 1.0 px Blackman-Harris filter (Blender's
# default is 1.5 px) and, on the skin only, OIDN without its guide prefilter: 'Accurate' denoises the
# albedo and normal guides first, which takes the pore / furrow bump out of the normal guide and so out
# of the image. Cycles renders without its own denoiser but with the denoising data passes; the skin
# materials carry pass index SKIN_DENOISE["index"] (IndexMA); skin_denoise() then runs OIDN twice in the
# compositor (the scene's 'Accurate' everywhere, the skin prefilter on the skin mask, anti-aliased) and
# writes the result back into the EXR's Combined. Env HERO_SKIN_DENOISE=0 restores Cycles' own denoise,
# HERO_FILTER_PX overrides the filter (T17's A/B).
HERO_FILTER_PX = 1.0
SKIN_DENOISE = {"prefilter": "Accurate", "skin_prefilter": "None", "quality": "High", "index": 7}


def skin_denoise_on():
    return os.environ.get("HERO_SKIN_DENOISE", "1") != "0"


def mark_skin(ch):
    """Pass index SKIN_DENOISE['index'] on the skin materials (IndexMA); returns their names."""
    done = []
    for o in ch.objs:
        for sl in o.material_slots:
            m = sl.material
            if m and m.name.startswith("skin_") and m.name not in done:
                m.pass_index = SKIN_DENOISE["index"]
                done.append(m.name)
    return done


def skin_denoise(path, cfg=SKIN_DENOISE):
    """OIDN in the compositor on a Cycles EXR rendered without denoising (with its denoising data
    passes): cfg['prefilter'] everywhere, cfg['skin_prefilter'] on the skin (IndexMA == cfg['index']);
    Combined is replaced in place. Returns seconds, or None when the passes are missing."""
    import numpy as np
    import OpenImageIO as oiio
    from hero import grade
    t = time.perf_counter()
    img = bpy.data.images.load(path, check_existing=False)
    sc = bpy.data.scenes.get("skin_dn") or bpy.data.scenes.new("skin_dn")
    w, h = grade.exr_size(path)
    r = sc.render
    r.resolution_x, r.resolution_y, r.resolution_percentage = w, h, 100
    r.engine = "BLENDER_WORKBENCH"
    r.use_compositing = True
    r.use_sequencer = False
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.look = "None"
    sc.view_settings.exposure = 0.0
    nt = bpy.data.node_groups.new("skin_dn", "CompositorNodeTree")
    nt.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    sc.compositing_node_group = nt
    src = nt.nodes.new("CompositorNodeImage")
    src.image = img
    o = {x.name: x for x in src.outputs}
    need = ("Combined", "Denoising Albedo", "Denoising Normal", "IndexMA")
    if any(k not in o for k in need):
        print(f"[stage] skin denoise: {os.path.basename(path)} lacks {[k for k in need if k not in o]}", flush=True)
        bpy.data.node_groups.remove(nt)
        bpy.data.images.remove(img)
        return None

    def dn(pref):
        d = nt.nodes.new("CompositorNodeDenoise")
        nt.links.new(o["Combined"], d.inputs["Image"])
        nt.links.new(o["Denoising Albedo"], d.inputs["Albedo"])
        nt.links.new(o["Denoising Normal"], d.inputs["Normal"])
        d.inputs["Prefilter"].default_value = pref
        d.inputs["Quality"].default_value = cfg["quality"]
        return d.outputs[0]
    idm = nt.nodes.new("CompositorNodeIDMask")
    nt.links.new(o["IndexMA"], idm.inputs["ID value"])
    idm.inputs["Index"].default_value = cfg["index"]
    idm.inputs["Anti-Alias"].default_value = True
    mix = grade._mix(nt, "MIX", dn(cfg["prefilter"]), dn(cfg["skin_prefilter"]), idm.outputs[0])
    nt.links.new(mix, nt.nodes.new("NodeGroupOutput").inputs[0])
    st = sc.render.image_settings
    st.file_format = "OPEN_EXR"
    st.color_depth = "32"
    st.exr_codec = "ZIP"
    st.color_mode = "RGB"
    tmp = path[:-4] + ".skin_dn.exr"
    sc.render.filepath = tmp
    bpy.ops.render.render(write_still=True, scene=sc.name)
    sc.compositing_node_group = None
    bpy.data.node_groups.remove(nt)
    bpy.data.images.remove(img)
    den = grade._oiio_read(tmp)[..., :3]
    os.remove(tmp)
    inp = oiio.ImageInput.open(path)
    spec = inp.spec()
    names = list(spec.channelnames)
    a = np.asarray(inp.read_image(format="float"), dtype=np.float32).copy()
    inp.close()
    for k, ch in enumerate("RGB"):
        hit = [i for i, n in enumerate(names) if n.endswith("Combined." + ch)]
        for i in hit:
            a[..., i] = den[..., k]
    out = oiio.ImageSpec(spec.width, spec.height, spec.nchannels, "half")
    out.channelnames = tuple(names)
    out.attribute("compression", "zip")
    for att in spec.extra_attribs:
        if att.name.startswith("blender") or att.name in ("Note",):
            out.attribute(att.name, att.value)
    ok = oiio.ImageOutput.create(path)
    if not ok or not ok.open(path, out):
        raise RuntimeError(f"cannot rewrite {path}")
    ok.write_image(a)
    ok.close()
    secs = round(time.perf_counter() - t, 1)
    print(f"[stage] skin denoise {os.path.basename(path)}: {secs} s", flush=True)
    return secs


# Engine parity (bench/m1/v4/checkpoint-1.md §1.3 #5): what the web viewer renders, and nothing it
# does not: the bare hero rig on the void floor, no set, haze, rain, beads or wet hair, no DoF, a 1 px
# Blackman-Harris filter; eyes still turn (the viewer applies the exported gaze). grade.py --parity
# drops bloom, halation, dispersion and grain to match.
PARITY_FILTER_PX = 1.0


def parity_spec(spec):
    s = dict(spec)
    for k in ("haze", "rain", "beads"):
        s.pop(k, None)
    return s


def render_shot(ch, name, spec, quality, out_dir, set_kind, crop=False, parity=False):
    clear_transient()
    wet.restore(ch)
    if parity:
        spec, set_kind = parity_spec(spec), "void"
    ch.pose_log = poses.apply(ch.arm, spec["pose"])
    rig.sync_props(ch)
    res = spec["res"]
    settings = rig.cycles(quality, res)
    sc_ = bpy.context.scene
    fpx = float(os.environ.get("HERO_FILTER_PX", HERO_FILTER_PX))
    sc_.cycles.filter_width = fpx
    settings["filter_px"] = fpx
    skin_dn = skin_denoise_on()
    if skin_dn:
        sc_.cycles.use_denoising = False
        vl_ = bpy.context.view_layer
        vl_.cycles.denoising_store_passes = True
        vl_.use_pass_material_index = True
        settings["skin_denoise"] = dict(SKIN_DENOISE)
    if parity:
        sc_ = bpy.context.scene
        if hasattr(sc_.cycles, "filter_width"):
            sc_.cycles.filter_width = PARITY_FILTER_PX
        if hasattr(sc_.render, "filter_size"):
            sc_.render.filter_size = PARITY_FILTER_PX
        settings["parity"] = {"filter_px": PARITY_FILTER_PX, "dof": False, "set": "void",
                              "skipped": ["haze", "rain", "beads", "wet_hair", "dof"]}
    cam = rig.camera(ch, spec["cam"], dof=not parity)
    # wet look (render side): hair tips in every rain shot, beads on the
    # shoulders in the close-ups, eyes to camera (or `gaze` deg off it)
    wet_hair = wet.hair_tips(ch, 1.0 if spec.get("rain") else 0.0)
    n_beads = wet.beads(ch, per_side=spec["beads"]) if spec.get("beads") else 0
    eyes = wet.gaze(ch, cam["obj"].location, off_deg=spec["gaze"]) if spec.get("gaze") is not None else None
    cam["obj"].data.shift_x = spec.get("shift", 0.0)
    cam["obj"].data.shift_y = spec.get("shift_y", 0.0)
    if set_kind == "alley":
        sets.turn(cam["az"] + spec.get("set_yaw", 15.0))
        sets.neon(spec.get("neon", 1.0))
    lights = dict(spec.get("lights") or {})
    rig.hero_rig(ch, cam, lights=lights, twin=spec.get("twin"),
                 flag=spec.get("flag", ("key", "wrap", "fill", "eye")) if set_kind == "alley" else (),
                 practicals=rig.practical_lights() if set_kind == "alley" else (),
                 emitters=rig.practical_emitters() if set_kind == "alley" else ())
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
    mb = peak_mb()
    print(f"[stage] {name}: {secs} s ({settings['samples']} spp, {res[0]}x{res[1]} @ {settings['pct']} %), "
          f"peak {mb} MB", flush=True)
    if skin_dn:
        settings["skin_denoise"]["seconds"] = skin_denoise(path)
    extra = []
    if crop:
        c = render_crop(ch, name, spec, cam, out_dir)
        if skin_dn:
            c["skin_denoise_s"] = skin_denoise(os.path.join(out_dir, "exr", name + "_crop.exr"))
        c["exposure"] = rig.HERO_EXPOSURE + spec.get("ev", 0.0)
        extra.append(c)
    return [{"shot": name, "seconds": secs, "exposure": rig.HERO_EXPOSURE + spec.get("ev", 0.0),
            "cam": spec["cam"], "pose": spec["pose"], "pose_log": ch.pose_log, "rain": n_rain,
            "beads": n_beads, "wet_hair": bool(spec.get("rain")) and wet_hair, "eyes_turned_deg": eyes,
            "haze": spec.get("haze", 0.0), "peak_mb": mb, **settings}] + extra


def render_turntable(ch, quality, out_dir, views, poses_, passes, recs=None, save=None):
    tdir = os.path.join(out_dir, "turntable")
    os.makedirs(tdir, exist_ok=True)
    clear_transient()   # drops the last shot's rain and beads (transient collections)
    wet.restore(ch)
    wet.hair_tips(ch, 0.0)
    hidden = [(o, o.hide_render) for o in bpy.data.objects
              if any(c.name == "set_alley" for c in o.users_collection)]
    for o, _ in hidden:
        o.hide_render = True
    recs = [] if recs is None else recs
    for pose in poses_:
        ch.pose_log = poses.apply(ch.arm, pose)
        rig.sync_props(ch)
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
                             "seconds": secs, "samples": bpy.context.scene.cycles.samples, "pct": st["pct"],
                             "peak_mb": peak_mb()})
                print(f"[stage] turntable {tag}: {secs} s, peak {peak_mb()} MB", flush=True)
                if save:
                    save()
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
    ap.add_argument("--pct", type=int, default=0, help="resolution %% override (e.g. 100 at preview samples)")
    ap.add_argument("--crop", default="none",
                    help="shots that also get a 100 %% crop (half the frame each way) around the eye or "
                         "focus point: a list, 'close' (shots.CLOSE) or 'none'")
    ap.add_argument("--hair-rim", choices=["on", "off"], default="on",
                    help="split saturated hero lights: a desaturated twin lights the hair (rig.HAIR_RIM)")
    ap.add_argument("--parity", action="store_true",
                    help="engine-parity variant: void set, no haze/rain/beads/wet hair, DoF off, 1 px filter "
                         "(grade with grade.py --parity)")
    ap.add_argument("--skin-sss", choices=["auto", "off"], default="auto",
                    help="auto: fill in Cycles SSS when the build's skin has none (render-side)")
    a = ap.parse_args(argv)
    rig.PCT = a.pct or None
    rig.HAIR_RIM = a.hair_rim == "on"
    out = os.path.abspath(a.out)
    os.makedirs(os.path.join(out, "exr"), exist_ok=True)
    t0 = time.perf_counter()
    ch = rig.load_character(a.inp)
    from character import suit_textures
    # the suit twill as the engine's tiled detail (no longer baked, T6): from the .blend's material
    # records, or the suit_detail.json sidecar next to a GLB
    weave = (suit_textures.cycles_weave_sidecar(a.inp) if a.inp.endswith(".glb")
             else suit_textures.cycles_weave_blend(a.inp))
    for o in ch.objs:
        o.pass_index = 1
    if a.parity:
        a.set_kind = "void"
    rec = {"in": os.path.abspath(a.inp), "quality": a.quality, "set": a.set_kind, "parity": a.parity,
           "blender": bpy.app.version_string, "threads": bpy.context.scene.render.threads,
           "hero_only": [o.name for o in ch.objs if any(c.name == "hero_only" for c in o.users_collection)],
           "skin_sss_added": skin_sss(ch) if a.skin_sss == "auto" else [], "cycles_weave": weave,
           "skin_denoise_materials": mark_skin(ch) if skin_denoise_on() else [],
           "shots": [], "turntable": []}
    names = shots.ORDER if a.shots == "all" else ([] if a.shots == "none" else a.shots.split(","))
    # a second pass into an existing run dir (hero.sh --into, e.g. the
    # turntable at a different thread count): keep the earlier records that
    # this pass doesn't redo
    prior_path = os.path.join(out, "stage.json")
    prior = json.load(open(prior_path)) if os.path.exists(prior_path) else None
    if prior:
        rec["shots"] = [r for r in prior.get("shots", []) if r["shot"] not in names
                        and r.get("crop_of") not in names]
        rec["turntable"] = list(prior.get("turntable", []))
        rec["passes"] = prior.get("passes") or [{k: prior.get(k) for k in ("threads", "total_s", "peak_mb")}]
    if names and a.set_kind == "alley":
        t = time.perf_counter()
        sets.alley()
        rec["set_build_s"] = round(time.perf_counter() - t, 2)
    crops = shots.CLOSE if a.crop == "close" else ([] if a.crop == "none" else a.crop.split(","))
    for n in names:
        rec["shots"] += render_shot(ch, n, shots.SHOTS[n], a.quality, out, a.set_kind, crop=n in crops,
                                    parity=a.parity)
        with open(os.path.join(out, "stage.json"), "w") as f:
            json.dump(rec, f, indent=1)
    if a.turntable:
        def save():
            with open(os.path.join(out, "stage.json"), "w") as f:
                json.dump(rec, f, indent=1)
        render_turntable(ch, a.quality, out, a.tt_views.split(","), a.tt_poses.split(","),
                         a.tt_passes.split(","), recs=rec["turntable"], save=save)
    rec["total_s"] = round(time.perf_counter() - t0, 1)
    rec["peak_mb"] = peak_mb()
    if prior:
        seen, tt = set(), []
        for r in reversed(rec["turntable"]):      # a redone view replaces the earlier record
            if r["file"] not in seen:
                seen.add(r["file"])
                tt.append(r)
        rec["turntable"] = tt[::-1]
        rec["passes"].append({"threads": rec["threads"], "total_s": rec["total_s"], "peak_mb": rec["peak_mb"]})
        rec["total_s"] = round(sum(x.get("total_s") or 0 for x in rec["passes"]), 1)
        rec["peak_mb"] = max(x.get("peak_mb") or 0 for x in rec["passes"])
    with open(os.path.join(out, "stage.json"), "w") as f:
        json.dump(rec, f, indent=1)


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
