"""Hair test renders and metrics for one look-dev run (hair v4, bench/m1/v4/t8-hair.md).

    blender -b -t 6 --factory-startup --python bench/m1/hair_test.py -- RUN_DIR \
        [--parts test,beard,clay] [--models current|CHIANG,HUANG] [--res 768] [--samples 64] \
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
    for model in MODELS:
        tag = "current" if model == "current" else model.lower()
        if model != "current":
            if "hair_shader" not in mat or "hair_roughness" not in nt.nodes:
                out[tag] = {"skipped": "material not built by hair v4 (no model A/B)"}
                continue
            bsdf.model = model
            lo, hi = mat["hair_shader"][model.lower() + "_roughness"]
            nt.nodes["hair_roughness"].inputs["To Min"].default_value = lo
            nt.nodes["hair_roughness"].inputs["To Max"].default_value = hi
        png = os.path.join(OUT, f"hairtest_{tag}.png")
        save(png)
        px = pixels(png)
        a = px[..., 3]
        y = luma(px[..., :3])[a >= 0.95]
        hist, _ = np.histogram(y, bins=64, range=(0.0, 1.0))
        md, _ = modes(hist.astype(float))
        out[tag] = {"model": bsdf.model, "png": png, "hair_px": int(len(y)),
                    "p10": round(float(np.percentile(y, 10)), 4), "p50": round(float(np.percentile(y, 50)), 4),
                    "p90": round(float(np.percentile(y, 90)), 4), "p99": round(float(np.percentile(y, 99)), 4),
                    "mean": round(float(y.mean()), 4), "modes": md, "mode_count": len(md),
                    "hist64": hist.tolist()}
        print(f"[hair_test] {tag}: p10 {out[tag]['p10']} p50 {out[tag]['p50']} modes {md}", flush=True)
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
    eev = os.path.join(OUT, "beard_eevee.exr")
    save(eev, exr=True)
    save(os.path.join(OUT, "beard_eevee.png"))
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
    save(cyc, exr=True)
    save(os.path.join(OUT, "beard_cycles.png"))
    yc = luma(pixels(cyc)[..., :3])
    ye = luma(pixels(eev)[..., :3])
    mc, me = float(yc[m].mean()), float(ye[m].mean())
    results["beard"] = {"mask_px": int(m.sum()), "cycles_mean_lin": round(mc, 5), "eevee_mean_lin": round(me, 5),
                        "ratio_eevee_over_cycles": round(me / mc, 3) if mc > 0 else None,
                        "within_25pct": bool(mc > 0 and abs(me / mc - 1) <= 0.25),
                        "cycles_p50_lin": round(float(np.median(yc[m])), 5),
                        "eevee_p50_lin": round(float(np.median(ye[m])), 5),
                        "res": res, "cycles_samples": SAMPLES}
    print(f"[hair_test] beard: cycles {mc:.5f} eevee {me:.5f} ratio {results['beard']['ratio_eevee_over_cycles']}",
          flush=True)


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
    for part, fn in (("test", hair_test), ("beard", beard_test), ("clay", clay_test)):
        if part in PARTS:
            fn(results)
            with open(jpath, "w") as f:
                json.dump(results, f, indent=1)
    print("hair_test ->", jpath)


main()
