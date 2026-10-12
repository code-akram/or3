"""Look-dev renders + metrics for one character GLB (m1 loop; bench/m1/lookdev.sh).

Imports the GLB (we render what ships), then per view:
  * a beauty frame: fixed neutral studio, perspective camera at a FIXED world
    position (body views) or tracking the head bone (close-up), so a change
    in proportions shows up as a change in the picture;
  * a silhouette mask: orthographic camera along the same axis, character
    only, 1 px = a fixed metric size, so IoU between runs is meaningful.
Then the 40 px read test (look-spec §2.2): a key-light-only ¾ render of the
head, box-downsampled until the head is 40 px tall, scoring the eye-socket
band against the cheek (and the beard against the skin, once a beard exists).
Writes render_metrics.json: triangles per part, bones, weights per vertex,
joint-based landmarks of the shipped GLB, read test, and mask IoU against a
target set and the previous run. The spec landmarks (nude body) come from the
build (character.stats.json) and are merged by bench/m1/lookdev_report.py.

    blender -b -t 4 --factory-startup --python blender/lookdev_render.py -- \
        --glb RUN/character.glb --out-dir RUN [--mode loop|signoff] \
        [--prev PREV_RUN] [--target TARGET_DIR]

Loop mode: EEVEE (iGPU via EGL) 512², 16 samples. Sign-off: Cycles CPU 1024²,
128 spp + OIDN HIGH. Masks are always EEVEE 512², 1 sample.
"""

import argparse
import json
import math
import os
import sys
import time

import bpy
import numpy as np
from mathutils import Vector

# name: (azimuth deg from the character's front, framing)
VIEWS = {
    "front": (0.0, "body"),
    "three_quarter": (40.0, "body"),
    "profile": (90.0, "body"),
    "closeup": (25.0, "head"),
}
# Mask-only face views: body + eyes only (hair, clothes and face cards
# hidden), so IoU sees head edits that the hair hides in "closeup".
FACE_MASK_VIEWS = {
    "face_front": (0.0, "head"),
    "face_profile": (90.0, "head"),
}
FACE_PARTS = ("body", "low-poly")
# Fixed framing for body views (metres, character feet at z = 0, facing -Y).
BODY_TARGET_Z = 0.98
BODY_FRAME_H = 2.15
HEAD_FRAME_H = 0.42
MASK_RES = 512
# 40 px read test: render the head READ_PX tall, then box-average by READ_K.
READ_HEAD_PX = 40
READ_K = 8
READ_RES = 384
READ_AZ = -40.0  # the key-light side (the key is front-right of the character)
# Face strip (hair hidden): azimuths (key-side ¾ is negative), rendered once
# with the full studio rig and once key-only, so plane breaks show as shadow.
STRIP_VIEWS = (("front", 0.0), ("q_key", -35.0), ("q_shadow", 35.0), ("profile", -90.0))
STRIP_PARTS = ("body", "low-poly", "eyebrow", "eyelash", "teeth", "tongue")
STRIP_RES = 320
STRIP_FRAME_H = 0.30
# Look-dev skin (--skin lookdev): the MPFB texture desaturated and darkened a
# little, with low-frequency value variation and a rougher, less waxy finish.
# Render-side only; the GLB ships the asset material unchanged.
# Studio exposure (EV), calibrated with --calibrate so an 18 % grey card at
# face height reads ~0.46 display (AgX), 3 % black wool reads dark and an
# 80 % white shirt doesn't clip (bench/m1/README.md, "Exposure").
STUDIO_EXPOSURE = float(os.environ.get("LOOKDEV_EXPOSURE", "-2.5"))
SKIN_SAT = 0.55
SKIN_VAL = 0.88
SKIN_ROUGHNESS = 0.62


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--glb", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--mode", choices=["loop", "signoff"], default="loop")
    ap.add_argument("--prev", help="previous run dir (masks + metrics) to score against")
    ap.add_argument("--target", help="dir with <view>_mask.png target silhouettes")
    ap.add_argument("--views", default=",".join(VIEWS))
    ap.add_argument("--skin", choices=["lookdev", "asset"], default="lookdev",
                    help="lookdev: neutral render-side skin; asset: the shipped MPFB material")
    ap.add_argument("--no-face-strip", action="store_true")
    ap.add_argument("--calibrate", action="store_true",
                    help="render grey cards under the studio rig, write calibration.json, exit")
    return ap.parse_args(argv)


ARGS = parse_args()
TIMINGS = {}


def timed(name):
    class _T:
        def __enter__(self):
            self.t = time.perf_counter()

        def __exit__(self, *exc):
            TIMINGS[name] = round(time.perf_counter() - self.t, 3)
            return False
    return _T()


# ---------------------------------------------------------------- scene

def import_character(path):
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    bpy.ops.import_scene.gltf(filepath=os.path.abspath(path))
    arm = next(o for o in bpy.context.scene.objects if o.type == "ARMATURE")
    # Only the skinned character meshes: the importer also adds a hidden
    # bone-shape Icosphere that is not part of the character.
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH" and o.parent == arm]
    for o in bpy.context.scene.objects:
        if o.type == "MESH" and o not in meshes:
            o.hide_render = True
    return arm, meshes


def part_name(o):
    """'Human.long01_export' -> 'long01'; the body 'Human_export' -> 'body'."""
    n = o.name.split("_export")[0]
    return n.split(".", 1)[1] if "." in n else "body"


def lookdev_skin(meshes):
    """Neutral look-dev skin on the body material (render-side only):
    texture -> HSV (desaturate, darken) x low-frequency value noise, rough."""
    body = next((o for o in meshes if part_name(o) == "body"), None)
    if body is None:
        return None
    done = []
    for m in body.data.materials:
        if not m or not m.node_tree:
            continue
        nt = m.node_tree
        p = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if p is None:
            continue
        bc = p.inputs["Base Color"]
        src = bc.links[0].from_socket if bc.is_linked else None
        hsv = nt.nodes.new("ShaderNodeHueSaturation")
        hsv.inputs["Saturation"].default_value = SKIN_SAT
        hsv.inputs["Value"].default_value = SKIN_VAL
        if src is not None:
            nt.links.new(src, hsv.inputs["Color"])
        else:
            hsv.inputs["Color"].default_value = bc.default_value
        tc = nt.nodes.new("ShaderNodeTexCoord")
        noise = nt.nodes.new("ShaderNodeTexNoise")
        noise.inputs["Scale"].default_value = 35.0
        noise.inputs["Detail"].default_value = 3.0
        nt.links.new(tc.outputs["Object"], noise.inputs["Vector"])
        ramp = nt.nodes.new("ShaderNodeMapRange")
        ramp.inputs["To Min"].default_value = 0.86
        ramp.inputs["To Max"].default_value = 1.06
        nt.links.new(noise.outputs["Fac"], ramp.inputs["Value"])
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.blend_type = "MULTIPLY"
        mix.inputs["Factor"].default_value = 1.0
        nt.links.new(hsv.outputs["Color"], mix.inputs["A"])
        nt.links.new(ramp.outputs["Result"], mix.inputs["B"])
        nt.links.new(mix.outputs["Result"], bc)
        p.inputs["Roughness"].default_value = SKIN_ROUGHNESS
        if "Specular IOR Level" in p.inputs:
            p.inputs["Specular IOR Level"].default_value = 0.35
        done.append(m.name)
    return {"materials": done, "saturation": SKIN_SAT, "value": SKIN_VAL,
            "roughness": SKIN_ROUGHNESS}


def look_at(ob, target):
    ob.rotation_euler = (target - ob.location).to_track_quat("-Z", "Y").to_euler()


def build_studio(floor_z):
    scene = bpy.context.scene
    world = scene.world or bpy.data.worlds.new("studio")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    bg.inputs[0].default_value = (0.045, 0.045, 0.05, 1.0)
    bg.inputs[1].default_value = 1.0
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = STUDIO_EXPOSURE

    bpy.ops.mesh.primitive_plane_add(size=60, location=(0, 0, floor_z))
    floor = bpy.context.active_object
    floor.name = "lookdev_floor"
    mat = bpy.data.materials.new("lookdev_floor")
    mat.use_nodes = True
    p = mat.node_tree.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = (0.08, 0.08, 0.085, 1)
    p.inputs["Roughness"].default_value = 0.8
    floor.data.materials.append(mat)

    aim = Vector((0, 0, floor_z + 1.1))

    def area(name, loc, energy, size, color=(1, 1, 1)):
        ld = bpy.data.lights.new(name, "AREA")
        ld.energy, ld.size, ld.color = energy, size, color
        ob = bpy.data.objects.new(name, ld)
        scene.collection.objects.link(ob)
        ob.location = Vector(loc) + Vector((0, 0, floor_z))
        look_at(ob, aim)
        return ob

    # Character faces -Y. Key front-left-high, fill front-right, rim behind
    # (same rig as spike 2, at fixed positions).
    lights = [area("key", (-2.2, -2.6, 2.8), 900, 1.5, (1.0, 0.96, 0.9)),
              area("fill", (2.6, -2.0, 1.4), 250, 2.0, (0.85, 0.9, 1.0)),
              area("rim", (0.8, 2.8, 2.6), 700, 1.0)]
    return floor, lights


def view_target(framing, floor_z, head):
    if framing == "body":
        return Vector((0.0, 0.0, floor_z + BODY_TARGET_Z)), BODY_FRAME_H
    t = head.copy()
    t.z -= 0.03
    return t, HEAD_FRAME_H


def make_cameras(view, floor_z, head):
    az, framing = VIEWS.get(view) or FACE_MASK_VIEWS[view]
    target, frame_h = view_target(framing, floor_z, head)
    a = math.radians(az)
    # Azimuth 0 = in front of the character (-Y); positive shows its left side.
    axis = Vector((math.sin(a), -math.cos(a), 0.0))
    scene = bpy.context.scene

    cd = bpy.data.cameras.new(view)
    cd.lens = 50.0 if framing == "body" else 85.0
    dist = (frame_h * 0.5) / math.tan(math.atan(cd.sensor_width * 0.5 / cd.lens))
    cam = bpy.data.objects.new(view, cd)
    scene.collection.objects.link(cam)
    cam.location = target + axis * dist
    look_at(cam, target)

    od = bpy.data.cameras.new(view + "_ortho")
    od.type = "ORTHO"
    od.ortho_scale = frame_h
    od.clip_end = 100.0
    ortho = bpy.data.objects.new(view + "_ortho", od)
    scene.collection.objects.link(ortho)
    ortho.location = target + axis * 10.0
    look_at(ortho, target)
    return cam, ortho


def set_beauty_engine():
    scene = bpy.context.scene
    r = scene.render
    r.film_transparent = False
    r.image_settings.color_mode = "RGB"
    r.resolution_percentage = 100
    r.image_settings.file_format = "PNG"
    if ARGS.mode == "signoff":
        r.resolution_x = r.resolution_y = 1024
        r.engine = "CYCLES"
        c = scene.cycles
        c.device = "CPU"
        c.samples = 128
        c.use_adaptive_sampling = True
        c.use_denoising = True
        c.denoiser = "OPENIMAGEDENOISE"
        c.denoising_quality = "HIGH"
        c.denoising_prefilter = "ACCURATE"
        if hasattr(c, "denoising_use_gpu"):
            c.denoising_use_gpu = False
        c.max_bounces = 8
        c.transparent_max_bounces = 16
    else:
        r.resolution_x = r.resolution_y = 512
        r.engine = "BLENDER_EEVEE"
        scene.eevee.taa_render_samples = 16


def set_mask_engine():
    scene = bpy.context.scene
    r = scene.render
    r.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = 1
    r.resolution_x = r.resolution_y = MASK_RES
    r.film_transparent = True
    r.image_settings.color_mode = "RGBA"


def render(path):
    bpy.context.scene.render.filepath = path
    t = time.perf_counter()
    bpy.ops.render.render(write_still=True)
    return round(time.perf_counter() - t, 3)


# ---------------------------------------------------------------- masks

def load_mask(path):
    """bool[h, w] from a mask PNG (white = character), or None."""
    if not path or not os.path.exists(path):
        return None
    img = bpy.data.images.load(path, check_existing=False)
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    bpy.data.images.remove(img)
    return px.reshape(h, w, 4)[..., 0] > 0.5


def alpha_to_mask(rgba_path, mask_path):
    img = bpy.data.images.load(rgba_path, check_existing=False)
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    bpy.data.images.remove(img)
    m = px.reshape(h, w, 4)[..., 3] > 0.5
    out = np.zeros((h, w, 4), dtype=np.float32)
    out[m] = 1.0
    out[..., 3] = 1.0
    mi = bpy.data.images.new("mask", w, h, alpha=False)
    mi.pixels.foreach_set(out.ravel())
    mi.filepath_raw = mask_path
    mi.file_format = "PNG"
    mi.save()
    bpy.data.images.remove(mi)
    os.remove(rgba_path)
    return m


def iou(a, b):
    if a is None or b is None or a.shape != b.shape:
        return None
    u = np.logical_or(a, b).sum()
    return round(float(np.logical_and(a, b).sum() / u), 4) if u else None


def mask_extent(m, metres_per_px):
    """Height and width of the silhouette bbox, in metres."""
    ys, xs = np.nonzero(m)
    if len(xs) == 0:
        return None
    return {"height_m": round((ys.max() - ys.min() + 1) * metres_per_px, 4),
            "width_m": round((xs.max() - xs.min() + 1) * metres_per_px, 4),
            "area_px": int(m.sum())}


# ---------------------------------------------------------------- metrics

def mesh_tris(o):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = o.evaluated_get(dg)
    me = ev.to_mesh()
    me.calc_loop_triangles()
    n = len(me.loop_triangles)
    ev.to_mesh_clear()
    return n


def landmarks(arm, meshes):
    """Proportion metrics from joint positions and the body mesh (rest pose)."""
    mw = arm.matrix_world
    j = {b.name: mw @ b.head_local for b in arm.data.bones}
    body = next(o for o in meshes if part_name(o) == "body")
    co = np.array([(body.matrix_world @ v.co)[:] for v in body.data.vertices])
    floor_z = min(float(np.array([(o.matrix_world @ Vector(c))[:] for c in o.bound_box])[:, 2].min())
                  for o in meshes)
    top_z = float(co[:, 2].max())
    stature = top_z - floor_z

    head_gi = body.vertex_groups["head"].index if "head" in body.vertex_groups else None
    hw = np.zeros(len(co))
    if head_gi is not None:
        for v in body.data.vertices:
            for g in v.groups:
                if g.group == head_gi:
                    hw[v.index] = g.weight
    head_co = co[hw >= 0.5]
    head_h = float(top_z - head_co[:, 2].min()) if len(head_co) else None
    head_w = float(np.ptp(head_co[:, 0])) if len(head_co) else None
    head_d = float(np.ptp(head_co[:, 1])) if len(head_co) else None

    def dist(a, b):
        return float((j[a] - j[b]).length) if a in j and b in j else None

    def r(x, y):
        return round(x / y, 4) if x and y else None

    shoulder_w = dist("upperarm_l", "upperarm_r")
    hip_w = dist("thigh_l", "thigh_r")
    hip_z = (j["thigh_l"].z + j["thigh_r"].z) * 0.5 if "thigh_l" in j else None
    leg = hip_z - floor_z if hip_z is not None else None
    torso = j["neck_01"].z - hip_z if "neck_01" in j and hip_z is not None else None
    arm_len = ((dist("upperarm_l", "lowerarm_l") or 0) + (dist("lowerarm_l", "hand_l") or 0)) or None
    raw = {"stature_m": stature, "head_height_m": head_h, "head_width_m": head_w,
           "head_depth_m": head_d, "shoulder_joint_width_m": shoulder_w,
           "hip_joint_width_m": hip_w, "leg_length_m": leg, "torso_length_m": torso,
           "arm_length_m": arm_len}
    out = {k: (round(v, 4) if v is not None else None) for k, v in raw.items()}
    out.update({
        "heads_tall": r(stature, head_h),
        "shoulder_to_hip": r(shoulder_w, hip_w),
        "leg_to_torso": r(leg, torso),
        "leg_to_stature": r(leg, stature),
        "arm_to_stature": r(arm_len, stature),
        "head_width_to_height": r(head_w, head_h),
        "head_width_to_shoulder": r(head_w, shoulder_w),
    })
    return out, floor_z, (mw @ ((arm.data.bones["head"].head_local + arm.data.bones["head"].tail_local) * 0.5)
                          if "head" in arm.data.bones else Vector((0, 0, top_z - 0.13)))


def weights_per_vertex(meshes, bone_names):
    worst = 0
    for o in meshes:
        idx = {g.index for g in o.vertex_groups if g.name in bone_names}
        for v in o.data.vertices:
            worst = max(worst, sum(1 for g in v.groups if g.group in idx and g.weight > 1e-4))
    return worst


# ---------------------------------------------------------------- read test

def _srgb_to_linear(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _luminance_img(path):
    """Relative luminance per pixel. EXR is scene-linear (independent of the
    view transform and exposure); 8-bit images are sRGB-decoded."""
    img = bpy.data.images.load(path, check_existing=False)
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    bpy.data.images.remove(img)
    rgb = px.reshape(h, w, 4)[..., :3].astype(np.float64)
    if not path.endswith(".exr"):
        rgb = _srgb_to_linear(rgb)
    return rgb @ np.array([0.2126, 0.7152, 0.0722]), w, h  # row 0 = bottom


def _box_px(cam, corners, w, h):
    """Pixel bbox (x0, x1, y0, y1; y from the bottom) of projected 3D corners."""
    from bpy_extras.object_utils import world_to_camera_view
    scene = bpy.context.scene
    pts = [world_to_camera_view(scene, cam, Vector(c)) for c in corners]
    xs = [p.x * w for p in pts]
    ys = [p.y * h for p in pts]
    return min(xs), max(xs), min(ys), max(ys)


def _mean_in(lum, box):
    x0, x1, y0, y1 = box
    h, w = lum.shape
    xs = np.arange(w) + 0.5
    ys = np.arange(h) + 0.5
    mx = (xs >= x0) & (xs <= x1)
    my = (ys >= y0) & (ys <= y1)
    if not mx.any():
        mx[min(w - 1, max(0, int((x0 + x1) / 2)))] = True
    if not my.any():
        my[min(h - 1, max(0, int((y0 + y1) / 2)))] = True
    return float(lum[np.ix_(my, mx)].mean()), int(mx.sum() * my.sum())


def read_test(out, meshes, lights, head_mid, spec):
    """look-spec §2.2: eye band >= 15 % darker than the cheek, beard >= 25 %
    different from the skin, at a 40 px tall head under the key light only."""
    eyes = next((o for o in meshes if "low-poly" in o.name), None)
    if eyes is None or not spec.get("menton_z"):
        return {"skipped": "no eye mesh or no spec landmarks (menton)"}
    body = next(o for o in meshes if part_name(o) == "body")
    bco = np.array([(body.matrix_world @ v.co)[:] for v in body.data.vertices])
    eco = np.array([(eyes.matrix_world @ v.co)[:] for v in eyes.data.vertices])
    side = -1.0 if READ_AZ < 0 else 1.0  # the eye nearest the camera
    eye = eco[eco[:, 0] * side > 0]
    ec = eye.mean(0)
    cornea_y = float(eye[:, 1].min())
    crown = float(bco[:, 2].max())
    head_h = crown - spec["menton_z"]

    scene = bpy.context.scene
    a = math.radians(READ_AZ)
    axis = Vector((math.sin(a), -math.cos(a), 0.0))
    cd = bpy.data.cameras.new("read40")
    cd.lens = 85.0
    frame_h = head_h * READ_RES / (READ_HEAD_PX * READ_K)
    dist = (frame_h * 0.5) / math.tan(math.atan(cd.sensor_width * 0.5 / cd.lens))
    cam = bpy.data.objects.new("read40", cd)
    scene.collection.objects.link(cam)
    target = Vector((0.0, float(ec[1]), (crown + spec["menton_z"]) * 0.5))
    cam.location = target + axis * dist
    look_at(cam, target)

    saved = [(l, l.hide_render) for l in lights]
    for l in lights:
        l.hide_render = l.name != "key"
    r = scene.render
    r.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = 16
    r.resolution_x = r.resolution_y = READ_RES
    r.film_transparent = False
    r.image_settings.file_format = "OPEN_EXR"
    r.image_settings.color_mode = "RGB"
    scene.camera = cam
    full = os.path.join(out, "read40_full.exr")
    secs = render(full)
    r.image_settings.file_format = "PNG"
    for l, hid in saved:
        l.hide_render = hid

    lum, w, h = _luminance_img(full)
    k = READ_K
    small = lum[:h - h % k, :w - w % k].reshape(h // k, k, w // k, k).mean(axis=(1, 3))
    sw, sh = w // k, h // k
    x = float(ec[0])
    eye_band = [(x - 0.014, cornea_y, ec[2] - 0.006), (x + 0.014, cornea_y, ec[2] + 0.012)]
    cheek = [(x - 0.004 * side, cornea_y + 0.006, ec[2] - 0.042),
             (x + 0.016 * side, cornea_y + 0.006, ec[2] - 0.024)]

    def corners(pair):
        (x0, y0, z0), (x1, y1, z1) = pair
        return [(xx, yy, zz) for xx in (x0, x1) for yy in (y0, y1) for zz in (z0, z1)]

    def box(pair):
        x0, x1, y0, y1 = _box_px(cam, corners(pair), w, h)
        return x0 / k, x1 / k, y0 / k, y1 / k

    head_px = _box_px(cam, [(0, ec[1], crown), (0, ec[1], spec["menton_z"])], w, h)
    boxes = {"eye_band": box(eye_band), "cheek": box(cheek)}
    le, ne = _mean_in(small, boxes["eye_band"])
    lc, nc = _mean_in(small, boxes["cheek"])
    res = {
        "camera_az_deg": READ_AZ, "lights": "key only", "render_s": secs,
        "head_px": round((head_px[3] - head_px[2]) / k, 1), "image_px": [sw, sh],
        "eye_band_lum": round(le, 5), "eye_band_px": ne,
        "cheek_lum": round(lc, 5), "cheek_px": nc,
        "eye_band_darker": round(1.0 - le / lc, 4) if lc > 0 else None,
    }
    res["eye_band_ok"] = res["eye_band_darker"] is not None and res["eye_band_darker"] >= 0.15
    beard = next((o for o in meshes if "beard" in o.name.lower()), None)
    if beard is None:
        res["beard"] = "skipped: no beard mesh"
    else:
        chin = [(-0.012, cornea_y + 0.02, spec["menton_z"] + 0.012),
                (0.012, cornea_y + 0.02, spec["menton_z"] + 0.030)]
        boxes["beard"] = box(chin)
        lb, nb = _mean_in(small, boxes["beard"])
        res.update({"beard_lum": round(lb, 5), "beard_px": nb,
                    "beard_contrast": round(abs(lb - lc) / lc, 4) if lc > 0 else None})
        res["beard_ok"] = res["beard_contrast"] is not None and res["beard_contrast"] >= 0.25
    res["boxes_px"] = {n: [round(c, 1) for c in b] for n, b in boxes.items()}
    # 40 px image for eyeballing (nearest-upscaled x4) with the sample boxes
    # outlined (eye band red, cheek cyan, beard yellow); drop the full render.
    up = np.repeat(np.repeat(small, 4, 0), 4, 1) * 2.0 ** STUDIO_EXPOSURE
    g = np.clip(np.where(up <= 0.0031308, up * 12.92, 1.055 * up ** (1 / 2.4) - 0.055), 0, 1)
    rgba = np.dstack([g, g, g, np.ones_like(g)]).astype(np.float32)
    colours = {"eye_band": (1, 0, 0), "cheek": (0, 1, 1), "beard": (1, 1, 0)}
    for n, (x0, x1, y0, y1) in boxes.items():
        X0, X1 = int(round(x0 * 4)), int(round(x1 * 4))
        Y0, Y1 = int(round(y0 * 4)), int(round(y1 * 4))
        X0, X1 = max(0, min(X0, up.shape[1] - 1)), max(0, min(X1, up.shape[1] - 1))
        Y0, Y1 = max(0, min(Y0, up.shape[0] - 1)), max(0, min(Y1, up.shape[0] - 1))
        for yy in (Y0, Y1):
            rgba[yy, X0:X1 + 1, :3] = colours[n]
        for xx in (X0, X1):
            rgba[Y0:Y1 + 1, xx, :3] = colours[n]
    im = bpy.data.images.new("read40", up.shape[1], up.shape[0], alpha=False)
    im.pixels.foreach_set(rgba.ravel())
    im.filepath_raw = os.path.join(out, "read40.png")
    im.file_format = "PNG"
    im.save()
    bpy.data.images.remove(im)
    os.remove(full)
    return res


CARDS = (("black_wool", 0.03), ("skin_mid", 0.30), ("grey18", 0.18), ("white_shirt", 0.80))


def calibrate(out, head, floor):
    """Exposure check: Lambertian cards of known albedo at face and chest
    height, facing the front camera, under the studio rig and under the key
    alone. Reports the display-referred value (0..1) at each card centre."""
    scene = bpy.context.scene
    floor.hide_render = True
    for o in scene.objects:
        if o.type == "MESH" and o.name != "lookdev_floor":
            o.hide_render = True
    lights = [o for o in scene.objects if o.type == "LIGHT"]
    res = {"view_transform": scene.view_settings.view_transform,
           "look": scene.view_settings.look, "exposure": scene.view_settings.exposure,
           "lights": {l.name: l.data.energy for l in lights}}
    for height, z in (("face", head.z), ("chest", head.z - 0.35)):
        cards = []
        for i, (name, alb) in enumerate(CARDS):
            bpy.ops.mesh.primitive_plane_add(size=0.12, location=(-0.21 + i * 0.14, -0.15, z),
                                             rotation=(math.pi / 2, 0, 0))
            c = bpy.context.active_object
            m = bpy.data.materials.new("card_" + name)
            m.use_nodes = True
            p = m.node_tree.nodes["Principled BSDF"]
            p.inputs["Base Color"].default_value = (alb, alb, alb, 1)
            p.inputs["Roughness"].default_value = 1.0
            if "Specular IOR Level" in p.inputs:
                p.inputs["Specular IOR Level"].default_value = 0.0
            c.data.materials.append(m)
            cards.append((name, c))
        cd = bpy.data.cameras.new("cal")
        cd.type = "ORTHO"
        cd.ortho_scale = 0.62
        cam = bpy.data.objects.new("cal", cd)
        scene.collection.objects.link(cam)
        cam.location = Vector((0, -3.0, z))
        look_at(cam, Vector((0, 0, z)))
        scene.camera = cam
        set_beauty_engine()
        out_h = {}
        for row in ("studio", "key"):
            for l in lights:
                l.hide_render = row == "key" and l.name != "key"
            path = os.path.join(out, f"calibrate_{height}_{row}.png")
            render(path)
            img = bpy.data.images.load(path)
            w, h = img.size
            px = np.array(img.pixels[:]).reshape(h, w, 4)
            vals = {}
            for name, c in cards:
                u = 0.5 + c.location.x / 0.62
                cx, cy = int(u * w), h // 2
                vals[name] = round(float(px[cy - 4:cy + 4, cx - 4:cx + 4, :3].mean()), 4)
            bpy.data.images.remove(img)
            out_h[row] = vals
        for l in lights:
            l.hide_render = False
        for _, c in cards:
            bpy.data.objects.remove(c, do_unlink=True)
        res[height] = out_h
    with open(os.path.join(out, "calibration.json"), "w") as f:
        json.dump(res, f, indent=2)
    print(json.dumps(res, indent=2))


def face_strip(out, meshes, lights, head, floor):
    """Hair-hidden face beauty strip: STRIP_VIEWS x (studio, key only), EEVEE
    STRIP_RES², head-tracking 85 mm cameras. Writes face_strip.png (row 1
    studio, row 2 key only) and the frames under face/."""
    import subprocess
    scene = bpy.context.scene
    fdir = os.path.join(out, "face")
    os.makedirs(fdir, exist_ok=True)
    keep = [o for o in meshes if part_name(o).startswith(STRIP_PARTS)]
    saved = [(o, o.hide_render) for o in meshes] + [(floor, floor.hide_render)]
    for o in meshes:
        o.hide_render = o not in keep
    floor.hide_render = True
    r = scene.render
    r.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = 16
    r.resolution_x = r.resolution_y = STRIP_RES
    r.film_transparent = False
    r.image_settings.color_mode = "RGB"
    target = head.copy()
    target.z -= 0.035
    secs, paths = 0.0, []
    lit = [(l, l.hide_render) for l in lights]
    for row in ("studio", "key"):
        for l in lights:
            l.hide_render = row == "key" and l.name != "key"
        for name, az in STRIP_VIEWS:
            a = math.radians(az)
            axis = Vector((math.sin(a), -math.cos(a), 0.0))
            cd = bpy.data.cameras.new("strip_" + name)
            cd.lens = 85.0
            dist = (STRIP_FRAME_H * 0.5) / math.tan(math.atan(cd.sensor_width * 0.5 / cd.lens))
            cam = bpy.data.objects.new("strip_" + name, cd)
            scene.collection.objects.link(cam)
            cam.location = target + axis * dist
            look_at(cam, target)
            scene.camera = cam
            p = os.path.join(fdir, f"{row}_{name}.png")
            secs += render(p)
            paths.append(p)
    for l, hid in lit:
        l.hide_render = hid
    for o, hid in saved:
        o.hide_render = hid
    n = len(STRIP_VIEWS)
    inputs = [x for p in paths for x in ("-i", p)]
    fc = (";".join(f"{''.join(f'[{r * n + i}]' for i in range(n))}hstack={n}[r{r}]" for r in range(2))
          + ";[r0][r1]vstack=2")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *inputs, "-filter_complex", fc,
                    os.path.join(out, "face_strip.png")], check=True)
    return {"render_s": round(secs, 3), "views": [v for v, _ in STRIP_VIEWS],
            "rows": ["studio", "key only"], "parts": sorted({part_name(o) for o in keep})}


# ---------------------------------------------------------------- main

def main():
    out = os.path.abspath(ARGS.out_dir)
    os.makedirs(out, exist_ok=True)
    with timed("import_glb"):
        arm, meshes = import_character(ARGS.glb)
    with timed("metrics"):
        lm, floor_z, head = landmarks(arm, meshes)
        parts = {}
        for o in meshes:
            parts[part_name(o)] = parts.get(part_name(o), 0) + mesh_tris(o)
        bone_names = {b.name for b in arm.data.bones}
        metrics = {
            "glb": os.path.abspath(ARGS.glb), "mode": ARGS.mode,
            "tris": {"total": sum(parts.values()), "parts": dict(sorted(parts.items()))},
            "bones": len(arm.data.bones),
            "max_weights_per_vertex": weights_per_vertex(meshes, bone_names),
            "landmarks_glb": lm,
        }
    floor, lights = build_studio(floor_z)
    if ARGS.calibrate:
        calibrate(os.path.abspath(ARGS.out_dir), head, floor)
        return
    metrics["skin"] = lookdev_skin(meshes) if ARGS.skin == "lookdev" else "asset"
    views = [v for v in ARGS.views.split(",") if v]
    face_views = list(FACE_MASK_VIEWS)
    cams = {v: make_cameras(v, floor_z, head) for v in views + face_views}
    scene = bpy.context.scene

    frames = []
    set_beauty_engine()
    for v in views:
        scene.camera = cams[v][0]
        frames.append({"view": v, "pass": "beauty",
                       "seconds": render(os.path.join(out, f"{v}.png"))})
        print(f"[lookdev] {ARGS.mode} {v}: {frames[-1]['seconds']:.2f} s", flush=True)

    floor.hide_render = True
    set_mask_engine()
    masks, sil = {}, {}
    for v in views:
        scene.camera = cams[v][1]
        tmp = os.path.join(out, f"{v}_alpha.png")
        frames.append({"view": v, "pass": "mask", "seconds": render(tmp)})
        masks[v] = alpha_to_mask(tmp, os.path.join(out, f"{v}_mask.png"))
        sil[v] = mask_extent(masks[v], cams[v][1].data.ortho_scale / MASK_RES)
    hidden = [(o, o.hide_render) for o in meshes if part_name(o) not in FACE_PARTS]
    for o, _ in hidden:
        o.hide_render = True
    for v in face_views:
        scene.camera = cams[v][1]
        tmp = os.path.join(out, f"{v}_alpha.png")
        frames.append({"view": v, "pass": "mask", "seconds": render(tmp)})
        masks[v] = alpha_to_mask(tmp, os.path.join(out, f"{v}_mask.png"))
        sil[v] = mask_extent(masks[v], cams[v][1].data.ortho_scale / MASK_RES)
    for o, hid in hidden:
        o.hide_render = hid
    floor.hide_render = False

    def score(d):
        if not d:
            return None
        return {v: iou(masks[v], load_mask(os.path.join(d, f"{v}_mask.png")))
                for v in views + face_views}

    spec = {}
    stats_path = os.path.join(os.path.dirname(os.path.abspath(ARGS.glb)), "character.stats.json")
    if os.path.exists(stats_path):
        with open(stats_path) as f:
            spec = json.load(f).get("spec_landmarks") or {}
    with timed("read40"):
        metrics["read40"] = read_test(out, meshes, lights, head, spec)
    if not ARGS.no_face_strip:
        with timed("face_strip"):
            metrics["face_strip"] = face_strip(out, meshes, lights, head, floor)
    metrics["silhouette"] = sil
    metrics["iou_target"] = score(ARGS.target)
    metrics["iou_prev"] = score(ARGS.prev)
    metrics["prev_run"] = os.path.abspath(ARGS.prev) if ARGS.prev else None
    metrics["render"] = {
        "engine": "CYCLES" if ARGS.mode == "signoff" else "BLENDER_EEVEE",
        "res": 1024 if ARGS.mode == "signoff" else 512, "mask_res": MASK_RES,
        "frames": frames}
    try:
        import gpu
        metrics["render"]["gpu"] = gpu.platform.renderer_get()
    except Exception:  # noqa: BLE001 - informational only
        pass
    metrics["timings_s"] = TIMINGS
    metrics["blender"] = bpy.app.version_string
    with open(os.path.join(out, "render_metrics.json"), "w") as f:
        json.dump(metrics, f, indent=2)
    print(json.dumps({k: metrics[k] for k in ("tris", "landmarks_glb", "read40", "iou_prev")}, indent=2))


main()
