"""Hair test renders and metrics for one look-dev run (hair v4, bench/m1/v4/t8-hair.md).

    blender -b -t 6 --factory-startup --python bench/m1/hair_test.py -- RUN_DIR \
        [--parts test,beard,parity,clay] [--models current|CHIANG,HUANG] [--res 768] [--samples 64] \
        [--out DIR]

Needs RUN_DIR/character.blend (KEEP_BLEND=1) and, for `beard`, RUN_DIR/character.glb.
Writes into RUN_DIR/hair_test/ (or --out) and merges its numbers into hair_test.json there.

Parts:
  test   the neutral two-light hair test (fable_review §5.6): the scalp groom only (every
         other object a holdout: it occludes and shadows, renders transparent), Cycles,
         `--res`² at `--samples` spp, two white area lights (a key above the camera side,
         a back light opposite) and a dim grey world, fixed exposure. One frame per hair
         model (--models: `current` = as built, or a list; CHIANG / HUANG switch the
         Principled Hair BSDF and its roughness when the material was built by hair v4).
         Metric per frame: display luma (AgX, sRGB) of the hair pixels (alpha >= 0.95):
         histogram (64 bins), mode count (smoothed local maxima >= 8 % of the peak,
         >= 5 bins apart), p10 / p50 / p90.
  beard  beard tone parity: the look-dev closeup (lookdev_render.py: az 25, 85 mm, studio
         key / fill / rim, AgX -2.5 EV) rendered twice with the same camera and lights:
         Cycles on the kept .blend (hero strands) and EEVEE on the GLB (the game shells and
         cards, as lookdev renders them, 16 samples). Beard mask: the GLB beard mesh as an
         opaque emitter, everything else a holdout, eroded 2 px. Metric: the beard-region
         mean linear luminance of each and their ratio (EEVEE / Cycles).
  parity hair and beard tone parity, engine vs Cycles (track T9, bench/m1/v4/t9-cards.md): the
         look-dev closeup (as `beard`) in Cycles on the kept .blend (hero strands: scalp groom,
         beard, brows) and in EEVEE on the GLB; regions from the hero grooms themselves (the
         scalp groom and the beard curves as emitters, every mesh a holdout, closed and eroded
         2 px; brows blue, closed 2 / eroded 1 px, T9b), so the metric does not move with the
         game geometry. The engine frame is
         RUN_DIR/lin_closeup.png when present (engine_shots.mjs --views closeup --prefix lin_
         --query view_transform=standard: Standard view at the studio exposure, so it decodes
         back to scene-linear). Metric: region mean linear luminance, engine / Cycles and
         EEVEE / Cycles (gate: within +-20 %). T11: per region also a tone record (core of the
         region): p10 / p50 / p90, grey fraction (light, neutral pixels), chroma (median
         saturation, r/g, b/g) and the same by thirds of the region's height (low / mid / high),
         engine / Cycles for grey fraction and chroma (gate: within +-20 %).
  measure  the parity metrics again from the files, no rendering (a re-shot engine frame), with
         --cycles-ref DIR: the Cycles frame and region mask from another run's hair_test dir
         (valid while the hero grooms are unchanged, e.g. a game-bake-only change).
  views  T15 head views (bench/m1/v4/t15-hair-volume.md): head-framed three-quarter / profile (+ the
         closeup) viewer stage for engine_shots.mjs, Cycles hero frames, a hero hair mask by region
         and the game hair mask (GLB cards with the viewer's cut-out); bench/m1/hair_views.sh runs it.
  views_measure  silhouette IoU (hero vs game hair masks) and per-region (crown / side / back / front
         falls) hair luminance and r/g, engine / Cycles, from those files and the engine frames.
  clay   a clay turntable of the groom (strands and head one matte grey, Cycles 24 spp +
         OIDN, 512², six azimuths, head framing to the collar) and the back view in the
         neutral test light with the shipped hair material.
"""

import json
import math
import os
import subprocess
import sys

import bpy
import numpy as np
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def opt(name, default):
    return argv[argv.index(name) + 1] if name in argv else default


RUN = os.path.abspath(argv[0])
OUT = os.path.abspath(opt("--out", os.path.join(RUN, "hair_test")))
PARTS = opt("--parts", "test,beard,clay").split(",")
MODELS = opt("--models", "current").split(",")
# --variants FILE: extra test frames, a JSON list of {"tag", "model"?, "inputs"?: {BSDF input:
# value}, "roughness"?: [root, tip], "melanin_shift"?: added to every strand's melanin}
# (shader sensitivity on one build; each variant starts from the built material).
VARIANTS = json.load(open(opt("--variants", ""))) if "--variants" in argv else []
# --beard-albedo S (diagnostic): the EEVEE beard's base colour x S (0: what is left
# is skin through the shells and specular); writes beard_eevee_aS.* and results
# "beard_albedo_S", and reuses beard_cycles.exr when --out already holds one.
BEARD_ALBEDO = float(opt("--beard-albedo", "nan")) if "--beard-albedo" in argv else None
RES = int(opt("--res", "768"))
SAMPLES = int(opt("--samples", "64"))
TEST_EXPOSURE = -2.5     # as the look-dev studio: near-black hair reads near-black
STUDIO_EXPOSURE = -2.5   # lookdev_render.STUDIO_EXPOSURE


def look_at(ob, target):
    ob.rotation_euler = (target - ob.location).to_track_quat("-Z", "Y").to_euler()


def open_blend():
    bpy.ops.wm.open_mainfile(filepath=os.path.join(RUN, "character.blend"))
    sc = bpy.context.scene
    for o in list(sc.objects):
        if o.type in ("LIGHT", "CAMERA"):
            bpy.data.objects.remove(o, do_unlink=True)
    arm = next(o for o in sc.objects if o.type == "ARMATURE")
    # The rest pose, as the GLB imports (the kept .blend can carry a pose).
    arm.data.pose_position = "REST"
    bpy.context.view_layer.update()
    hero = bpy.data.collections.get("hero_only")
    for o in sc.objects:
        # the game hair cards give way to the groom; hero_only shows
        if o.type == "MESH" and "hair_export" in o.name:
            o.hide_render = True
    if hero is not None:
        for o in hero.objects:
            o.hide_render = False
    return arm


def head_mid(arm):
    b = arm.data.bones["head"]
    return arm.matrix_world @ ((b.head_local + b.tail_local) * 0.5)


def camera(name, target, az, el, frame_h, lens):
    sc = bpy.context.scene
    cd = bpy.data.cameras.new(name)
    cd.lens = lens
    cd.clip_start = 0.01
    cam = bpy.data.objects.new(name, cd)
    sc.collection.objects.link(cam)
    dist = (frame_h * 0.5) / math.tan(math.atan(cd.sensor_width * 0.5 / lens))
    a, e = math.radians(az), math.radians(el)
    cam.location = target + Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e))) * dist
    look_at(cam, target)
    bpy.context.view_layer.update()   # matrix_world is read back (beard_test)
    sc.camera = cam
    return cam


def area(name, loc, target, energy, size, color=(1, 1, 1)):
    ld = bpy.data.lights.new(name, "AREA")
    ld.energy, ld.size, ld.color = energy, size, color
    ob = bpy.data.objects.new(name, ld)
    bpy.context.scene.collection.objects.link(ob)
    ob.location = loc
    look_at(ob, target)
    return ob


def world(rgb, strength=1.0):
    sc = bpy.context.scene
    w = sc.world or bpy.data.worlds.new("w")
    sc.world = w
    w.use_nodes = True
    bg = w.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (*rgb, 1.0)
    bg.inputs[1].default_value = strength


def cycles(res, samples, transparent):
    sc = bpy.context.scene
    r = sc.render
    r.engine = "CYCLES"
    r.resolution_x = r.resolution_y = res
    r.resolution_percentage = 100
    r.film_transparent = transparent
    c = sc.cycles
    c.device = "CPU"
    c.samples = samples
    c.use_adaptive_sampling = False
    c.use_denoising = True
    c.denoiser = "OPENIMAGEDENOISE"
    if hasattr(c, "denoising_use_gpu"):
        c.denoising_use_gpu = False
    c.max_bounces = 32
    c.glossy_bounces = 16
    c.diffuse_bounces = 3
    c.transmission_bounces = 16
    c.transparent_max_bounces = 64
    c.seed = 0
    sc.cycles_curves.shape = "THICK"
    sc.cycles_curves.subdivisions = 2
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.look = "None"
    sc.display_settings.display_device = "sRGB"


def save(path, exr=False):
    sc = bpy.context.scene
    im = sc.render.image_settings
    im.file_format = "OPEN_EXR" if exr else "PNG"
    im.color_mode = "RGBA"
    if exr:
        im.color_depth = "32"
        im.exr_codec = "ZIP"
    else:
        im.color_depth = "8"
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)


def pixels(path):
    """float (h, w, 4) of an image file, bottom row first: linear for EXR,
    the stored (display) values for PNG."""
    img = bpy.data.images.load(path, check_existing=False)
    if not path.endswith(".exr"):
        img.colorspace_settings.name = "Non-Color"
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    bpy.data.images.remove(img)
    return px.reshape(h, w, 4)


def luma(rgb):
    return rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722


def modes(hist, rel=0.08, sep=5):
    """Local maxima of the smoothed histogram >= rel x the peak, >= sep bins apart."""
    k = np.exp(-0.5 * (np.arange(-4, 5) / 1.5) ** 2)
    hs = np.convolve(hist, k / k.sum(), mode="same")
    peak = hs.max() if hs.max() > 0 else 1.0
    cand = [i for i in range(1, len(hs) - 1) if hs[i] >= hs[i - 1] and hs[i] > hs[i + 1] and hs[i] >= rel * peak]
    cand.sort(key=lambda i: -hs[i])
    keep = []
    for i in cand:
        if all(abs(i - j) >= sep for j in keep):
            keep.append(i)
    # a second maximum only counts as a mode if the valley between is real
    out = []
    for i in sorted(keep):
        if out:
            j = out[-1]
            valley = hs[min(i, j):max(i, j) + 1].min()
            if valley > 0.85 * min(hs[i], hs[j]):
                if hs[i] > hs[j]:
                    out[-1] = i
                continue
        out.append(i)
    return [round((i + 0.5) / len(hs), 3) for i in out], hs


# ---------------------------------------------------------------- the hair test

def hair_test(results):
    arm = open_blend()
    sc = bpy.context.scene
    groom = bpy.data.objects.get("hair_groom")
    if groom is None:
        results["test"] = {"skipped": "no hair_groom in the .blend"}
        return
    for o in sc.objects:
        if o.type in ("MESH", "CURVES", "CURVE") and o is not groom:
            o.is_holdout = True
    h = head_mid(arm)
    target = h + Vector((0.0, 0.03, -0.07))
    cam_az, cam_el = 125.0, 8.0
    camera("hairtest", target, cam_az, cam_el, 0.48, 85)

    def at(az, el, dist):
        a, e = math.radians(az), math.radians(el)
        return h + Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e))) * dist

    # key: above the camera side; back: low behind, opposite the camera
    area("key", at(cam_az - 35.0, 42.0, 1.4), h, 150.0, 0.5)
    area("back", at(cam_az + 180.0 - 25.0, 18.0, 1.4), h, 200.0, 0.5)
    world((0.02, 0.02, 0.02))
    cycles(RES, SAMPLES, True)
    sc.view_settings.exposure = TEST_EXPOSURE
    mat = groom.data.materials[0]
    nt = mat.node_tree
    bsdf = nt.nodes.get("hair_bsdf") or next(n for n in nt.nodes if n.type == "BSDF_HAIR_PRINCIPLED")
    out = {}
    v4 = "hair_shader" in mat and "hair_roughness" in nt.nodes
    built = {"model": bsdf.model,
             # by index: a socket the current model hides is not found by name
             "inputs": {n: i.default_value for n, i in enumerate(bsdf.inputs)
                        if not i.is_linked and isinstance(i.default_value, float)},
             "roughness": [nt.nodes["hair_roughness"].inputs[k].default_value
                           for k in ("To Min", "To Max")] if v4 else None}
    grad = nt.nodes.get("melanin_gradient")
    built_grad = [grad.inputs[k].default_value for k in ("To Min", "To Max")] if grad else None
    def reset():
        bsdf.model = built["model"]
        for k, v in built["inputs"].items():
            bsdf.inputs[k].default_value = v
        if v4:
            for k, v in zip(("To Min", "To Max"), built["roughness"]):
                nt.nodes["hair_roughness"].inputs[k].default_value = v
        if grad:
            for k, v in zip(("To Min", "To Max"), built_grad):
                grad.inputs[k].default_value = v

    frames = [{"tag": "current" if m == "current" else m.lower(), "model": None if m == "current" else m}
              for m in MODELS] + VARIANTS
    for fr in frames:
        tag, model = fr["tag"], fr.get("model")
        if (model or fr.get("roughness") or fr.get("melanin_shift")) and not v4:
            out[tag] = {"skipped": "material not built by hair v4 (no model A/B)"}
            continue
        reset()   # to the built material, then apply the frame's changes
        if model:
            bsdf.model = model
            lo, hi = mat["hair_shader"][model.lower() + "_roughness"]
            nt.nodes["hair_roughness"].inputs["To Min"].default_value = lo
            nt.nodes["hair_roughness"].inputs["To Max"].default_value = hi
        for k, v in fr.get("inputs", {}).items():
            socks = sorted((i for i in bsdf.inputs if i.name == k), key=lambda i: not i.enabled)
            socks[0].default_value = v
        if fr.get("roughness"):
            nt.nodes["hair_roughness"].inputs["To Min"].default_value = fr["roughness"][0]
            nt.nodes["hair_roughness"].inputs["To Max"].default_value = fr["roughness"][1]
        if fr.get("melanin_shift"):
            if grad is None:
                out[tag] = {"skipped": "no melanin_gradient node"}
                continue
            for k, v in zip(("To Min", "To Max"), built_grad):
                grad.inputs[k].default_value = v + fr["melanin_shift"]
        png = os.path.join(OUT, f"hairtest_{tag}.png")
        save(png)
        px = pixels(png)
        a = px[..., 3]
        y = luma(px[..., :3])[a >= 0.95]
        hist, _ = np.histogram(y, bins=64, range=(0.0, 1.0))
        md, _ = modes(hist.astype(float))
        out[tag] = {"model": bsdf.model, "variant": {k: v for k, v in fr.items() if k != "tag"},
                    "png": png, "hair_px": int(len(y)),
                    "p10": round(float(np.percentile(y, 10)), 4), "p50": round(float(np.percentile(y, 50)), 4),
                    "p90": round(float(np.percentile(y, 90)), 4), "p99": round(float(np.percentile(y, 99)), 4),
                    "mean": round(float(y.mean()), 4), "modes": md, "mode_count": len(md),
                    "hist64": hist.tolist()}
        print(f"[hair_test] {tag}: p10 {out[tag]['p10']} p50 {out[tag]['p50']} modes {md}", flush=True)
    reset()   # leave the material as built
    results["test"] = {"camera": {"az": cam_az, "el": cam_el}, "res": RES, "samples": SAMPLES,
                       "exposure": TEST_EXPOSURE, "frames": out}


# ---------------------------------------------------------------- beard parity

def studio_lights(floor_z):
    aim = Vector((0, 0, floor_z + 1.1))
    for name, loc, energy, size, color in (
            ("key", (-2.2, -2.6, 2.8), 900, 1.5, (1.0, 0.96, 0.9)),
            ("fill", (2.6, -2.0, 1.4), 250, 2.0, (0.85, 0.9, 1.0)),
            ("rim", (0.8, 2.8, 2.6), 700, 1.0, (1, 1, 1))):
        area(name, Vector(loc) + Vector((0, 0, floor_z)), aim, energy, size, color)
    world((0.045, 0.045, 0.05))
    bpy.ops.mesh.primitive_plane_add(size=60, location=(0, 0, floor_z))
    fl = bpy.context.active_object
    fl.name = "lookdev_floor"
    m = bpy.data.materials.new("lookdev_floor")
    m.use_nodes = True
    p = m.node_tree.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = (0.08, 0.08, 0.085, 1)
    p.inputs["Roughness"].default_value = 0.8
    fl.data.materials.append(m)
    sc = bpy.context.scene
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.look = "None"
    sc.view_settings.exposure = STUDIO_EXPOSURE


def closeup_camera(arm, floor_z):
    h = head_mid(arm)
    t = h.copy()
    t.z -= 0.03
    return camera("closeup", t, 25.0, 0.0, 0.42, 85)   # lookdev_render VIEWS["closeup"]


def floor_of(objs):
    return min(float(np.array([(o.matrix_world @ Vector(c))[:] for c in o.bound_box])[:, 2].min())
               for o in objs)


def beard_test(results):
    res = 512
    # EEVEE: the GLB, as lookdev_render imports and frames it (its camera is
    # kept and reused for the .blend: the importer's bone tails differ, so
    # the head-bone midpoint does too).
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=os.path.join(RUN, "character.glb"))
    sc = bpy.context.scene
    arm = next(o for o in sc.objects if o.type == "ARMATURE")
    meshes = [o for o in sc.objects if o.type == "MESH" and o.parent == arm]
    for o in sc.objects:
        if o.type == "MESH" and o not in meshes:
            o.hide_render = True
    floor_z = floor_of(meshes)
    studio_lights(floor_z)
    cam = closeup_camera(arm, floor_z)
    cam_mw = cam.matrix_world.copy()
    r = sc.render
    r.engine = "BLENDER_EEVEE"
    sc.eevee.taa_render_samples = 16
    r.resolution_x = r.resolution_y = res
    r.resolution_percentage = 100
    r.film_transparent = False
    sfx = ""
    if BEARD_ALBEDO is not None:
        sfx = f"_a{BEARD_ALBEDO:g}"
        for o in meshes:
            if "beard" not in o.name.lower():
                continue
            for mt in o.data.materials:
                bs = next((n for n in mt.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
                if bs is None or not bs.inputs["Base Color"].is_linked:
                    continue
                src = bs.inputs["Base Color"].links[0].from_socket
                sv = mt.node_tree.nodes.new("ShaderNodeVectorMath")
                sv.operation = "SCALE"
                sv.inputs["Scale"].default_value = BEARD_ALBEDO
                mt.node_tree.links.new(src, sv.inputs[0])
                mt.node_tree.links.new(sv.outputs[0], bs.inputs["Base Color"])
    eev = os.path.join(OUT, f"beard_eevee{sfx}.exr")
    save(eev, exr=True)
    save(os.path.join(OUT, f"beard_eevee{sfx}.png"))
    # Mask: the beard mesh as an opaque emitter, everything else a holdout.
    beard = [o for o in meshes if "beard" in o.name.lower()]
    em = bpy.data.materials.new("mask_white")
    em.use_nodes = True
    nt = em.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    e = nt.nodes.new("ShaderNodeEmission")
    o_ = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(e.outputs[0], o_.inputs[0])
    for o in meshes:
        if o in beard:
            for i in range(len(o.data.materials)):
                o.data.materials[i] = em
        else:
            o.is_holdout = True
    bpy.data.objects["lookdev_floor"].hide_render = True
    r.film_transparent = True
    sc.eevee.taa_render_samples = 1
    mpath = os.path.join(OUT, "beard_mask.png")
    save(mpath)
    m = pixels(mpath)[..., 3] > 0.5
    for _ in range(2):   # erode 2 px
        m = m & np.roll(m, 1, 0) & np.roll(m, -1, 0) & np.roll(m, 1, 1) & np.roll(m, -1, 1)
    # Cycles: the kept .blend, hero strands, the same camera, floor and lights.
    open_blend()
    sc = bpy.context.scene
    studio_lights(floor_z)
    cd = bpy.data.cameras.new("closeup")
    cd.lens = 85.0
    cd.clip_start = 0.01
    cam = bpy.data.objects.new("closeup", cd)
    sc.collection.objects.link(cam)
    cam.matrix_world = cam_mw
    sc.camera = cam
    cycles(res, SAMPLES, False)
    sc.view_settings.exposure = STUDIO_EXPOSURE
    cyc = os.path.join(OUT, "beard_cycles.exr")
    if BEARD_ALBEDO is None or not os.path.exists(cyc):
        save(cyc, exr=True)
        save(os.path.join(OUT, "beard_cycles.png"))
    yc = luma(pixels(cyc)[..., :3])
    ye = luma(pixels(eev)[..., :3])
    mc, me = float(yc[m].mean()), float(ye[m].mean())
    results["beard" if BEARD_ALBEDO is None else f"beard_albedo{sfx[2:]}"] = {"mask_px": int(m.sum()), "cycles_mean_lin": round(mc, 5), "eevee_mean_lin": round(me, 5),
                        "ratio_eevee_over_cycles": round(me / mc, 3) if mc > 0 else None,
                        "within_25pct": bool(mc > 0 and abs(me / mc - 1) <= 0.25),
                        "cycles_p50_lin": round(float(np.median(yc[m])), 5),
                        "eevee_p50_lin": round(float(np.median(ye[m])), 5),
                        "res": res, "cycles_samples": SAMPLES}
    print(f"[hair_test] beard{sfx}: cycles {mc:.5f} eevee {me:.5f} ratio {me / mc if mc > 0 else 0:.3f}",
          flush=True)


# ---------------------------------------------------------------- hair / beard parity (T9)

def _close(m, r):
    """Binary closing then nothing else: dilate r px, erode r px (np.roll, wraps; the masks sit
    well inside the frame)."""
    d = m.copy()
    for _ in range(r):
        d = d | np.roll(d, 1, 0) | np.roll(d, -1, 0) | np.roll(d, 1, 1) | np.roll(d, -1, 1)
    for _ in range(r):
        d = d & np.roll(d, 1, 0) & np.roll(d, -1, 0) & np.roll(d, 1, 1) & np.roll(d, -1, 1)
    return d


def _erode(m, r):
    for _ in range(r):
        m = m & np.roll(m, 1, 0) & np.roll(m, -1, 0) & np.roll(m, 1, 1) & np.roll(m, -1, 1)
    return m


def _srgb_decode(x):
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def parity_test(results):
    res = 512
    # EEVEE on the GLB: the camera (as lookdev_render frames it), floor and the game frame.
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=os.path.join(RUN, "character.glb"))
    sc = bpy.context.scene
    arm = next(o for o in sc.objects if o.type == "ARMATURE")
    meshes = [o for o in sc.objects if o.type == "MESH" and o.parent == arm]
    for o in sc.objects:
        if o.type == "MESH" and o not in meshes:
            o.hide_render = True
    floor_z = floor_of(meshes)
    studio_lights(floor_z)
    cam = closeup_camera(arm, floor_z)
    cam_mw = cam.matrix_world.copy()
    r = sc.render
    r.engine = "BLENDER_EEVEE"
    sc.eevee.taa_render_samples = 16
    r.resolution_x = r.resolution_y = res
    r.resolution_percentage = 100
    r.film_transparent = False
    eev = os.path.join(OUT, "parity_eevee.exr")
    save(eev, exr=True)
    save(os.path.join(OUT, "parity_eevee.png"))
    # Cycles on the kept .blend: hero strands, the same camera, floor and lights.
    open_blend()
    sc = bpy.context.scene
    studio_lights(floor_z)
    cd = bpy.data.cameras.new("closeup")
    cd.lens = 85.0
    cd.clip_start = 0.01
    cam = bpy.data.objects.new("closeup", cd)
    sc.collection.objects.link(cam)
    cam.matrix_world = cam_mw
    sc.camera = cam
    cycles(res, SAMPLES, False)
    sc.view_settings.exposure = STUDIO_EXPOSURE
    cyc = os.path.join(OUT, "parity_cycles.exr")
    save(cyc, exr=True)
    save(os.path.join(OUT, "parity_cycles.png"))
    # --parity-lights key,rim (T9b): one more Cycles frame per studio light, the others off
    # (parity_cycles_<light>.exr), to calibrate the engine's hair lobes light by light
    # (viewer ?lights=<name>)
    for ln in [x for x in opt("--parity-lights", "").split(",") if x]:
        keep = {o.name: o.hide_render for o in sc.objects if o.type == "LIGHT"}
        for o in sc.objects:
            if o.type == "LIGHT":
                o.hide_render = o.name != ln
        save(os.path.join(OUT, f"parity_cycles_{ln}.exr"), exr=True)
        for k, v in keep.items():
            sc.objects[k].hide_render = v
    # Region masks from the hero grooms: scalp groom red, beard green, every mesh a holdout.
    def emit(name, rgb):
        m_ = bpy.data.materials.new(name)
        m_.use_nodes = True
        nt = m_.node_tree
        for n in list(nt.nodes):
            nt.nodes.remove(n)
        e = nt.nodes.new("ShaderNodeEmission")
        e.inputs[0].default_value = (*rgb, 1)
        o_ = nt.nodes.new("ShaderNodeOutputMaterial")
        nt.links.new(e.outputs[0], o_.inputs[0])
        return m_
    red, green, black = emit("m_hair", (1, 0, 0)), emit("m_beard", (0, 1, 0)), emit("m_other", (0, 0, 0))
    blue = emit("m_brows", (0, 0, 1))
    for o in sc.objects:
        if o.type == "MESH":
            o.is_holdout = True
        elif o.type == "CURVES" and not o.hide_render:
            mt = (red if o.name.startswith("hair_groom") else green if o.name.startswith("beard_hero")
                  else blue if o.name.startswith("brows_hero") else black)
            o.data.materials.clear()
            o.data.materials.append(mt)
    fl = bpy.data.objects.get("lookdev_floor")
    if fl:
        fl.hide_render = True
    sc.render.film_transparent = True
    sc.cycles.samples = 8
    sc.cycles.use_denoising = False
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.exposure = 0.0
    mpath = os.path.join(OUT, "parity_mask.exr")
    save(mpath, exr=True)
    parity_measure(results, cyc, eev, mpath, res)


# Facial-hair grey / chroma (T11, bench/m1/v4/t11-facial-hair.md; checkpoint-2 §5.1: every parity
# gate carries a spatial term). In the region's core (eroded CORE_ERODE more px: the beard's edge
# band is skin through the cheek-line fade, judged by eye), a "grey" pixel is light and neutral:
# scene-linear luminance > GREY_LUM (about twice the Cycles beard median under the studio rig) and
# saturation (max - min) / max < GREY_SAT. Chroma: the core's median saturation and its r/g, b/g.
# Spatial: the core split into thirds of its height in the frame (low: chin / jaw, mid, high:
# moustache / cheeks for the beard), each with its mean and grey fraction.
GREY_LUM, GREY_SAT, BRIGHT_LUM, GREY_MIN = 0.3, 0.45, 0.4, 0.05
CORE_ERODE = {"hair": 2, "beard": 3, "brows": 1}


def _tone_stats(rgb, m):
    """Spatial and chroma terms of one frame's region m (rows bottom-up, as pixels() returns)."""
    y = luma(rgb)
    c = rgb[m]
    yy = y[m]
    sat = (c.max(1) - c.min(1)) / np.maximum(c.max(1), 1e-6)
    g = max(float(c[:, 1].sum()), 1e-9)
    rec = {"p10_p50_p90": [round(float(np.percentile(yy, q)), 4) for q in (10, 50, 90)],
           "grey_frac": round(float(((yy > GREY_LUM) & (sat < GREY_SAT)).mean()), 4),
           "bright_frac": round(float((yy > BRIGHT_LUM).mean()), 4),
           "chroma_p50": round(float(np.median(sat)), 4),
           "r_g": round(float(c[:, 0].sum()) / g, 3), "b_g": round(float(c[:, 2].sum()) / g, 3)}
    rows = np.nonzero(m.any(1))[0]
    cuts = np.linspace(int(rows.min()), int(rows.max()) + 1, 4).round().astype(int)
    thirds = {}
    for name, a, b in (("low", cuts[0], cuts[1]), ("mid", cuts[1], cuts[2]), ("high", cuts[2], cuts[3])):
        sel = m.copy()
        sel[:a] = False
        sel[b:] = False
        if not sel.any():
            continue
        cs, ys = rgb[sel], y[sel]
        ss = (cs.max(1) - cs.min(1)) / np.maximum(cs.max(1), 1e-6)
        thirds[name] = {"mean": round(float(ys.mean()), 4),
                        "grey_frac": round(float(((ys > GREY_LUM) & (ss < GREY_SAT)).mean()), 4)}
    rec["thirds"] = thirds
    return rec


def parity_measure(results, cyc, eev, mpath, res=512):
    """The parity metrics from the rendered files: Cycles (cyc), EEVEE (eev, optional), the hero-groom
    region mask (mpath) and the engine's RUN/lin_closeup.png."""
    mk = pixels(mpath)
    # brows (T9b): thin, so closed 2 px and eroded 1 px (the scalp / beard erosion of 2 px leaves
    # only the brow cores)
    regions = {"hair": _erode(_close(mk[..., 0] > 0.3, 3), 2),
               "beard": _erode(_close(mk[..., 1] > 0.3, 3), 2),
               "brows": _erode(_close(mk[..., 2] > 0.3, 2), 1)}
    rc = pixels(cyc)[..., :3]
    yc = luma(rc)
    ye = luma(pixels(eev)[..., :3]) if eev and os.path.exists(eev) else None
    eng = os.path.join(RUN, "lin_closeup.png")
    yg = lin = None
    if os.path.exists(eng):
        px = pixels(eng)[..., :3]           # stored values (Standard view: sRGB of exposed linear)
        if px.shape[0] != res:
            k = px.shape[0] // res
            lin = _srgb_decode(px).reshape(res, k, res, k, 3).mean(axis=(1, 3))
        else:
            lin = _srgb_decode(px)
        lin = lin / 2.0 ** STUDIO_EXPOSURE
        yg = luma(lin)
    out = {"res": res, "cycles_samples": SAMPLES, "engine_frame": os.path.basename(eng) if yg is not None else None,
           "tone_def": {"grey_lum": GREY_LUM, "grey_sat": GREY_SAT, "grey_min": GREY_MIN, "core_erode": CORE_ERODE}}
    vis = np.zeros((res, res, 3), dtype=np.float32)
    for name, m in regions.items():
        mc = float(yc[m].mean()) if m.any() else 0.0
        rec = {"mask_px": int(m.sum()), "cycles_mean_lin": round(mc, 5)}
        if ye is not None:
            me = float(ye[m].mean()) if m.any() else 0.0
            rec.update({"eevee_mean_lin": round(me, 5), "eevee_over_cycles": round(me / mc, 3) if mc > 0 else None})
        if yg is not None:
            mg = float(yg[m].mean())
            rec.update({"engine_mean_lin": round(mg, 5), "engine_over_cycles": round(mg / mc, 3) if mc > 0 else None,
                        "engine_within_20pct": bool(mc > 0 and abs(mg / mc - 1) <= 0.2),
                        "engine_p50_lin": round(float(np.median(yg[m])), 5)})
        rec["cycles_p50_lin"] = round(float(np.median(yc[m])), 5)
        core = _erode(m, CORE_ERODE[name])
        if core.sum() > 50:
            tone = {"core_px": int(core.sum()), "cycles": _tone_stats(rc, core)}
            if lin is not None:
                te, tc = _tone_stats(lin, core), tone["cycles"]
                tone["engine"] = te
                # a grey fraction under GREY_MIN in Cycles (the brows, ~2 %) is noise: chroma only there
                eoc = {k: (round(te[k] / tc[k], 3) if tc[k] > (GREY_MIN if k == "grey_frac" else 0) else None)
                       for k in ("grey_frac", "chroma_p50")}
                tone["engine_over_cycles"] = eoc
                tone["engine_within_20pct"] = all(abs(v - 1) <= 0.2 for v in eoc.values() if v is not None)
            rec["tone"] = tone
        out[name] = rec
        vis[m] += {"hair": (1, 0, 0), "beard": (0, 1, 0), "brows": (0, 0, 1)}[name]
        print(f"[hair_test] parity {name}: {rec}", flush=True)
    # region overlay for the record (Blender rows are bottom-up; the PNG writer flips them back)
    ov = bpy.data.images.new("parity_regions", res, res, alpha=True)
    ov.pixels.foreach_set(np.concatenate([vis, np.ones((res, res, 1), np.float32)], 2).ravel())
    ov.filepath_raw = os.path.join(OUT, "parity_regions.png")
    ov.file_format = "PNG"
    ov.save()
    results["parity"] = out


def parity_measure_part(results):
    """--parts measure: the parity metrics again from the files, no rendering: a new engine frame on
    the same build, or (--cycles-ref DIR) the Cycles frame and region mask of another run's hair_test
    dir, valid while the hero grooms are unchanged and only the game bake moved."""
    ref = os.path.abspath(opt("--cycles-ref", OUT))
    eev = os.path.join(OUT, "parity_eevee.exr")
    parity_measure(results, os.path.join(ref, "parity_cycles.exr"), eev if os.path.exists(eev) else None,
                   os.path.join(ref, "parity_mask.exr"))
    if ref != OUT:
        results["parity"]["cycles_ref"] = ref


# ---------------------------------------------------------------- head views: silhouette + regions (T15)
#
# Track T15 (bench/m1/v4/t15-hair-volume.md). Head-framed three-quarter and profile cameras (85 mm,
# HV_FRAME_H tall, the head-bone midpoint HV_DROP lower so the lengths over the shoulder are in
# frame), plus the look-dev closeup. `views` writes a viewer stage (HV_DIR/engine_stage.json: the run's
# stage with these cameras under the lookdev names three_quarter / profile, the asset files linked)
# for engine_shots.mjs, and renders per view in Cycles:
#   hv_<view>_cycles.{exr,png}  the hero strands under the studio rig (AgX png, scene-linear exr)
#   hv_<view>_hero.exr         hero hair mask: the scalp groom as an emitter coloured by region
#                              (curve attribute from each strand's root: crown, side, back, front
#                              falls), every mesh a holdout; alpha = coverage
#   hv_<view>_game.exr         game hair mask: the GLB's scalp-hair meshes (cap + cards) as an emitter
#                              with the viewer's cut-out (albedo alpha >= HV_ALPHA_TEST, coverage
#                              alpha), every other mesh a holdout
# `views_measure` (no rendering) reads those and the engine frames HV_DIR/lin_<view>.png (Standard
# view) and writes hair_test.json "views": silhouette IoU (hero vs game mask, alpha >= 0.5) per view,
# and per region the hair-only luminance and r/g, engine / Cycles, on pixels that are hair in both
# (the region's pure pixels, eroded 2 px, inside the eroded game mask), per view and pooled.
HV_DIR = "views"
HV_FRAME_H, HV_LENS, HV_DROP = 0.56, 85.0, 0.09
HV_VIEWS = {"three_quarter": 40.0, "profile": 90.0, "front": 0.0}
HV_ALPHA_TEST = 0.32            # web/src/character/materials/params.ts hair.alphaTest (read-only here)
HV_REGIONS = ("crown", "side", "back", "front")
HV_CODES = np.array([(1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 0)], dtype=np.float32)
HV_ASSETS = ("character.glb", "character.rig.json", "character.stats.json", "material_params.json",
             "suit_detail.json", "suit_twill_detail.png", "skin_head_curvature.png",
             "skin_hands_curvature.png")


def _gl(v):
    return [round(float(v[0]), 6), round(float(v[2]), 6), round(float(-v[1]), 6)]


def _bl(g):
    return Vector((g[0], -g[2], g[1]))


def hv_stage():
    """The viewer stage for the head views (HV_DIR/engine_stage.json) and the Blender cameras
    {view: (location, target)} in Blender space."""
    with open(os.path.join(RUN, "engine_stage.json")) as f:
        st = json.load(f)
    hm = _bl(st["landmarks"]["head_mid"])
    target = hm - Vector((0.0, 0.0, HV_DROP))
    cams = {}
    dist = (HV_FRAME_H * 0.5) / math.tan(math.atan(18.0 / HV_LENS))
    for view, az in HV_VIEWS.items():
        a = math.radians(az)
        loc = target + Vector((math.sin(a), -math.cos(a), 0.0)) * dist
        cams[view] = (loc, target.copy())
        st["lookdev"]["cameras"][view] = {
            "position": _gl(loc), "target": _gl(target), "up": [0, 1, 0], "lens_mm": HV_LENS,
            "sensor_fit": "AUTO", "sensor_mm": 36.0,
            "vfov_deg": round(math.degrees(2 * math.atan(18.0 / HV_LENS)), 6), "res": [1024, 1024],
            "shift": [0.0, 0.0], "azimuth_deg": az, "frame_h_m": HV_FRAME_H}
    c = st["lookdev"]["cameras"]["closeup"]
    cams["closeup"] = (_bl(c["position"]), _bl(c["target"]))
    st["t15_head_views"] = {"frame_h_m": HV_FRAME_H, "lens_mm": HV_LENS, "drop_m": HV_DROP,
                            "views": HV_VIEWS}
    d = os.path.join(OUT, HV_DIR)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "engine_stage.json"), "w") as f:
        json.dump(st, f, indent=1)
    for name in HV_ASSETS:
        src, dst = os.path.join(RUN, name), os.path.join(d, name)
        if os.path.exists(src) and not os.path.lexists(dst):
            os.symlink(src, dst)
    return cams


def hv_camera(name, loc, target):
    sc = bpy.context.scene
    cd = bpy.data.cameras.new(name)
    cd.lens = HV_LENS
    cd.sensor_width = 36.0
    cd.sensor_fit = "AUTO"
    cd.clip_start = 0.01
    cam = bpy.data.objects.new(name, cd)
    sc.collection.objects.link(cam)
    cam.location = loc
    look_at(cam, target)
    bpy.context.view_layer.update()
    sc.camera = cam
    return cam


def _emit_mat(name, color=None, attr=None):
    """An emitter: a constant colour, or the HV_CODES colour of the integer curve attribute `attr`."""
    m_ = bpy.data.materials.new(name)
    m_.use_nodes = True
    nt = m_.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    e = nt.nodes.new("ShaderNodeEmission")
    o_ = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(e.outputs[0], o_.inputs[0])
    if attr:
        at = nt.nodes.new("ShaderNodeAttribute")
        at.attribute_type = "GEOMETRY"
        at.attribute_name = attr
        ramp = nt.nodes.new("ShaderNodeValToRGB")
        cr = ramp.color_ramp
        cr.interpolation = "CONSTANT"
        n = len(HV_CODES)
        while len(cr.elements) < n:
            cr.elements.new(0.5)
        for i, el in enumerate(cr.elements):
            el.position = i / n
            el.color = (*HV_CODES[i], 1.0)
        div = nt.nodes.new("ShaderNodeMath")
        div.operation = "DIVIDE"
        div.inputs[1].default_value = float(n)
        add = nt.nodes.new("ShaderNodeMath")
        add.operation = "ADD"
        add.inputs[1].default_value = 0.5
        nt.links.new(at.outputs["Fac"], add.inputs[0])
        nt.links.new(add.outputs[0], div.inputs[0])
        nt.links.new(div.outputs[0], ramp.inputs[0])
        nt.links.new(ramp.outputs[0], e.inputs[0])
    else:
        e.inputs[0].default_value = (*(color or (1, 1, 1)), 1)
    return m_


def hv_regions(groom, arm):
    """Per-curve region of the scalp groom from its root (point 1; point 0 is buried) relative to the
    head-bone midpoint: front falls (kind 2) 3, crown (elevation >= 45 deg) 0, back (|azimuth| >= 120 deg
    from the face) 2, else side 1. Stored as the curve attribute t15_region (FLOAT)."""
    cv = groom.data
    nc = len(cv.curves)
    first = np.empty(nc, dtype=np.int32)
    cv.curves.foreach_get("first_point_index", first)
    pos = np.empty(len(cv.points) * 3, dtype=np.float32)
    cv.points.foreach_get("position", pos)
    pos = pos.reshape(-1, 3)
    size = np.empty(nc, dtype=np.int32)
    cv.curves.foreach_get("points_length", size)
    root = pos[first + np.minimum(1, size - 1)]
    mw = np.array(groom.matrix_world)
    root = root @ mw[:3, :3].T + mw[:3, 3]
    h = np.array(head_mid(arm))
    v = root - h
    el = np.degrees(np.arctan2(v[:, 2], np.hypot(v[:, 0], v[:, 1])))
    az = np.degrees(np.arctan2(v[:, 0], -v[:, 1]))
    reg = np.where(el >= 45.0, 0, np.where(np.abs(az) >= 120.0, 2, 1))
    ka = cv.attributes.get("kind")
    if ka is not None:
        kind = np.empty(nc, dtype=np.int32)
        ka.data.foreach_get("value", kind)
        reg = np.where(kind == 2, 3, reg)
    a = cv.attributes.get("t15_region") or cv.attributes.new("t15_region", "FLOAT", "CURVE")
    a.data.foreach_set("value", reg.astype(np.float32))
    cv.update_tag()
    return {HV_REGIONS[i]: int((reg == i).sum()) for i in range(len(HV_REGIONS))}


def views_test(results):
    cams = hv_stage()
    res = int(opt("--views-res", "1024"))
    samples = int(opt("--views-samples", "48"))
    # Game mask: the GLB, scalp hair meshes only (cap + cards), with the viewer's cut-out.
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=os.path.join(RUN, "character.glb"))
    sc = bpy.context.scene
    arm = next(o for o in sc.objects if o.type == "ARMATURE")
    meshes = [o for o in sc.objects if o.type == "MESH" and o.parent == arm]
    for o in sc.objects:
        if o.type == "MESH" and o not in meshes:
            o.hide_render = True
    floor_z = floor_of(meshes)
    hair = [o for o in meshes if "hair_export" in o.name]
    for o in meshes:
        if o not in hair:
            o.is_holdout = True
            continue
        for i, mt in enumerate(o.data.materials):
            img = None
            for n in (mt.node_tree.nodes if mt and mt.node_tree else []):
                if n.type == "TEX_IMAGE" and n.image is not None and (
                        "albedo" in n.image.name or n.outputs["Alpha"].is_linked):
                    img = n.image
                    if "albedo" in n.image.name:
                        break
            m_ = bpy.data.materials.new(f"hv_cut_{i}")
            m_.use_nodes = True
            nt = m_.node_tree
            for n in list(nt.nodes):
                nt.nodes.remove(n)
            out = nt.nodes.new("ShaderNodeOutputMaterial")
            em = nt.nodes.new("ShaderNodeEmission")
            tr = nt.nodes.new("ShaderNodeBsdfTransparent")
            mix = nt.nodes.new("ShaderNodeMixShader")
            nt.links.new(tr.outputs[0], mix.inputs[1])
            nt.links.new(em.outputs[0], mix.inputs[2])
            nt.links.new(mix.outputs[0], out.inputs[0])
            if img is not None:
                tx = nt.nodes.new("ShaderNodeTexImage")
                tx.image = img
                tx.extension = "EXTEND"
                gt = nt.nodes.new("ShaderNodeMath")
                gt.operation = "GREATER_THAN"
                gt.inputs[1].default_value = HV_ALPHA_TEST
                mul = nt.nodes.new("ShaderNodeMath")
                mul.operation = "MULTIPLY"
                nt.links.new(tx.outputs["Alpha"], gt.inputs[0])
                nt.links.new(tx.outputs["Alpha"], mul.inputs[0])
                nt.links.new(gt.outputs[0], mul.inputs[1])
                nt.links.new(mul.outputs[0], mix.inputs[0])
            else:
                mix.inputs[0].default_value = 1.0
            o.data.materials[i] = m_
    cycles(res, 16, True)
    sc.cycles.use_denoising = False
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.exposure = 0.0
    for view, (loc, tgt) in cams.items():
        hv_camera(f"hv_{view}", loc, tgt)
        save(os.path.join(OUT, f"hv_{view}_game.exr"), exr=True)
    # Hero: the kept .blend, studio rig, same cameras.
    arm = open_blend()
    sc = bpy.context.scene
    studio_lights(floor_z)
    groom = bpy.data.objects.get("hair_groom")
    counts = hv_regions(groom, arm)
    cycles(res, samples, False)
    sc.view_settings.exposure = STUDIO_EXPOSURE
    for view, (loc, tgt) in cams.items():
        hv_camera(f"hv_{view}", loc, tgt)
        save(os.path.join(OUT, f"hv_{view}_cycles.exr"), exr=True)
        save(os.path.join(OUT, f"hv_{view}_cycles.png"))
    # Hero hair mask by region: the scalp groom an emitter, every mesh and other curve a holdout.
    reg_mat = _emit_mat("hv_region", attr="t15_region")
    for o in sc.objects:
        if o.type == "MESH":
            o.is_holdout = True
        elif o.type == "CURVES" and not o.hide_render:
            if o is groom:
                o.data.materials.clear()
                o.data.materials.append(reg_mat)
            else:
                o.is_holdout = True
    fl = bpy.data.objects.get("lookdev_floor")
    if fl:
        fl.hide_render = True
    sc.render.film_transparent = True
    sc.cycles.samples = 16
    sc.cycles.use_denoising = False
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.exposure = 0.0
    for view in cams:
        sc.camera = bpy.data.objects[f"hv_{view}"]
        save(os.path.join(OUT, f"hv_{view}_hero.exr"), exr=True)
    results["views"] = {"render": {"res": res, "cycles_samples": samples, "frame_h_m": HV_FRAME_H,
                                   "lens_mm": HV_LENS, "drop_m": HV_DROP, "views": HV_VIEWS,
                                   "region_strands": counts}}
    print(f"[hair_test] views rendered: {list(cams)} regions {counts}", flush=True)


def _png_write(path, rgb):
    """(h, w, 3) float 0..1, rows bottom-up (Blender order) -> PNG."""
    h, w = rgb.shape[:2]
    im = bpy.data.images.new(os.path.basename(path), w, h, alpha=True)
    im.pixels.foreach_set(np.concatenate([np.clip(rgb, 0, 1), np.ones((h, w, 1))], 2)
                          .astype(np.float32).ravel())
    im.filepath_raw = path
    im.file_format = "PNG"
    im.save()
    bpy.data.images.remove(im)


def views_measure(results):
    d = os.path.join(OUT, HV_DIR)
    out = results.get("views", {})
    per_view, pool = {}, {r: {"n": 0, "ye": 0.0, "yc": 0.0, "e": np.zeros(3), "c": np.zeros(3)}
                          for r in HV_REGIONS}
    for view in list(HV_VIEWS) + ["closeup"]:
        fh, fg = os.path.join(OUT, f"hv_{view}_hero.exr"), os.path.join(OUT, f"hv_{view}_game.exr")
        if not (os.path.exists(fh) and os.path.exists(fg)):
            continue
        hm, gm = pixels(fh), pixels(fg)
        H, G = hm[..., 3] >= 0.5, gm[..., 3] >= 0.5
        inter, union = int((H & G).sum()), int((H | G).sum())
        rec = {"iou": round(inter / max(union, 1), 4), "hero_px": int(H.sum()), "game_px": int(G.sum()),
               "game_over_hero_px": round(int(G.sum()) / max(int(H.sum()), 1), 3)}
        # where they differ, by height thirds of the hero mask (top / mid / low: lengths over the shoulder)
        rows = np.nonzero(H.any(1))[0]
        if len(rows):
            cuts = np.linspace(int(rows.min()), int(rows.max()) + 1, 4).round().astype(int)
            th = {}
            for name, a, b in (("low", cuts[0], cuts[1]), ("mid", cuts[1], cuts[2]), ("top", cuts[2], cuts[3])):
                hh, gg = H[a:b], G[a:b]
                th[name] = {"iou": round(int((hh & gg).sum()) / max(int((hh | gg).sum()), 1), 4),
                            "game_only": int((gg & ~hh).sum()), "hero_only": int((hh & ~gg).sum())}
            rec["thirds"] = th
        # overlay: hero only red, game only green, both grey
        ov = np.zeros(H.shape + (3,), np.float32)
        ov[H & G] = 0.55
        ov[H & ~G] = (0.9, 0.1, 0.1)
        ov[G & ~H] = (0.1, 0.85, 0.2)
        _png_write(os.path.join(OUT, f"hv_{view}_iou.png"), ov)
        # regions: pure pixels of each code (colour / alpha within 0.25 of the code), eroded 2 px
        a = np.maximum(hm[..., 3:4], 1e-6)
        cn = hm[..., :3] / a
        dist = np.linalg.norm(cn[..., None, :] - HV_CODES[None, None], axis=-1)
        lab = np.argmin(dist, -1)
        pure = (dist.min(-1) < 0.25) & (hm[..., 3] >= 0.9)
        lin = None
        eng = os.path.join(d, f"lin_{view}.png")
        if os.path.exists(eng):
            px = pixels(eng)[..., :3]
            k = px.shape[0] // hm.shape[0]
            lin = _srgb_decode(px)
            if k > 1:
                n_ = hm.shape[0]
                lin = lin.reshape(n_, k, n_, k, 3).mean(axis=(1, 3))
            lin = lin / 2.0 ** STUDIO_EXPOSURE
        cyc = pixels(os.path.join(OUT, f"hv_{view}_cycles.exr"))[..., :3]
        G2 = _erode(G, 2)
        regs = {}
        for i, rname in enumerate(HV_REGIONS):
            m = _erode(pure & (lab == i), 2) & G2
            if m.sum() < 30:
                continue
            c = cyc[m].sum(0)
            r_ = {"px": int(m.sum()), "cycles_mean_lin": round(float(luma(cyc[m]).mean()), 5),
                  "cycles_r_g": round(float(c[0] / max(c[1], 1e-9)), 3)}
            if lin is not None:
                e = lin[m].sum(0)
                ye = float(luma(lin[m]).mean())
                r_.update({"engine_mean_lin": round(ye, 5), "engine_r_g": round(float(e[0] / max(e[1], 1e-9)), 3),
                           "lum_engine_over_cycles": round(ye / max(r_["cycles_mean_lin"], 1e-9), 3),
                           "rg_engine_over_cycles": round(float(e[0] / max(e[1], 1e-9)) / max(r_["cycles_r_g"], 1e-9), 3)})
                p = pool[rname]
                p["n"] += int(m.sum())
                p["ye"] += float(luma(lin[m]).sum())
                p["yc"] += float(luma(cyc[m]).sum())
                p["e"] += e
                p["c"] += c
            regs[rname] = r_
        rec["regions"] = regs
        per_view[view] = rec
        print(f"[hair_test] views {view}: iou {rec['iou']} regions {regs}", flush=True)
    pooled = {}
    for rname, p in pool.items():
        if p["n"] == 0:
            continue
        lum = (p["ye"] / p["n"]) / max(p["yc"] / p["n"], 1e-9)
        rg = (p["e"][0] / max(p["e"][1], 1e-9)) / max(p["c"][0] / max(p["c"][1], 1e-9), 1e-9)
        pooled[rname] = {"px": p["n"], "lum_engine_over_cycles": round(float(lum), 3),
                         "rg_engine_over_cycles": round(float(rg), 3),
                         "engine_r_g": round(float(p["e"][0] / max(p["e"][1], 1e-9)), 3),
                         "cycles_r_g": round(float(p["c"][0] / max(p["c"][1], 1e-9)), 3),
                         "within_15pct": bool(abs(lum - 1) <= 0.15 and abs(rg - 1) <= 0.15)}
    out.update({"per_view": per_view, "regions_pooled": pooled,
                "iou_three_quarter": per_view.get("three_quarter", {}).get("iou"),
                "iou_profile": per_view.get("profile", {}).get("iou"),
                "method": "hero mask: scalp groom strands as emitters (Cycles, meshes holdout); game mask: GLB "
                          "scalp-hair meshes, albedo alpha >= hair.alphaTest; both alpha >= 0.5. Tone: pure "
                          "region pixels eroded 2 px inside the eroded game mask; engine lin_<view>.png "
                          "(Standard) / 2^exposure vs the Cycles scene-linear EXR."})
    results["views"] = out


# ---------------------------------------------------------------- clay turntable

def clay_test(results):
    arm = open_blend()
    sc = bpy.context.scene
    groom = bpy.data.objects.get("hair_groom")
    h = head_mid(arm)
    target = h + Vector((0.0, 0.0, -0.09))
    # Back view in the neutral test light, shipped hair material.
    camera("back", target, 180.0, 4.0, 0.56, 85)
    area("key", h + Vector((-0.6, 1.0, 1.0)), h, 150.0, 0.6)
    area("back", h + Vector((0.8, -1.0, 0.4)), h, 120.0, 0.6)
    world((0.05, 0.05, 0.05))
    cycles(512, 32, False)
    sc.view_settings.exposure = TEST_EXPOSURE
    save(os.path.join(OUT, "back.png"))
    # Clay: everything visible one matte grey.
    clay = bpy.data.materials.new("clay")
    clay.use_nodes = True
    p = clay.node_tree.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = (0.42, 0.42, 0.42, 1)
    p.inputs["Roughness"].default_value = 0.7
    for o in sc.objects:
        if o.type in ("MESH", "CURVES") and not o.hide_render:
            if o.name.startswith("hair_groom_scalp"):
                o.hide_render = True
                continue
            if o.data.materials:
                for i in range(len(o.data.materials)):
                    o.data.materials[i] = clay
            else:
                o.data.materials.append(clay)
    for ob in [o for o in sc.objects if o.type == "LIGHT"]:
        bpy.data.objects.remove(ob, do_unlink=True)
    area("key", h + Vector((-1.0, -1.2, 1.2)), h, 320.0, 1.0)
    area("fill", h + Vector((1.2, -0.6, 0.2)), h, 90.0, 1.5)
    area("top", h + Vector((0.0, 0.6, 1.4)), h, 160.0, 1.0)
    world((0.06, 0.06, 0.06))
    cycles(512, 24, False)
    sc.view_settings.exposure = TEST_EXPOSURE
    names = []
    for az in (0, 60, 120, 180, 240, 300):
        camera(f"clay{az}", target, float(az), 4.0, 0.56, 85)
        pth = os.path.join(OUT, f"clay_az{az:03d}.png")
        save(pth)
        names.append(pth)
    sheet = os.path.join(OUT, "clay_turntable.png")
    inputs = sum((["-i", n] for n in names), [])
    filt = "".join(f"[{i}:v]scale=384:384[v{i}];" for i in range(6)) + \
        "".join(f"[v{i}]" for i in range(6)) + "xstack=inputs=6:layout=0_0|384_0|768_0|0_384|384_384|768_384"
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", filt, sheet], check=True)
    results["clay"] = {"sheet": sheet, "back": os.path.join(OUT, "back.png")}


def main():
    os.makedirs(OUT, exist_ok=True)
    jpath = os.path.join(OUT, "hair_test.json")
    results = {}
    if os.path.exists(jpath):
        with open(jpath) as f:
            results = json.load(f)
    results["run"] = os.path.basename(RUN)
    for part, fn in (("test", hair_test), ("beard", beard_test), ("parity", parity_test),
                     ("measure", parity_measure_part), ("views", views_test),
                     ("views_measure", views_measure), ("clay", clay_test)):
        if part in PARTS:
            fn(results)
            with open(jpath, "w") as f:
                json.dump(results, f, indent=1)
    print("hair_test ->", jpath)


main()
