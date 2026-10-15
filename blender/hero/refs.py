"""Cycles references for the engine's AA / post work (m1 v4 track T16, bench/m1/v4/checkpoint-3.md §2.5,
§2.6, §3.2): the hero portrait shot with its rig exactly as stage.render_shot builds it, plus

    chart   the grey-chart check: 18 / 50 / 90 % Lambertian patches and an 18 % ball at the focus
            distance in front of the face, under the portrait's hero rig, void set, parity settings
            (1 px filter, no haze / rain / beads / wet, no DoF), the character hidden. Writes
            exr/chart.exr, chart.png (grade.py --parity), chart.glb (the chart alone, for the
            engine) and chart.json (patch boxes in the 1920 x 1080 frame, Cycles means).
    bounce  the set bounce: the alley set as the portrait sees it (set turn, neon, rig, practicals and
            emitters; flagged rig lights light only the character, so here nothing), no character,
            the rig's own emitters invisible to camera; six 32 x 32 cube faces from the eyes'
            midpoint, resampled to a 128 x 64 equirect in three.js world axes -> set_bounce.json.
    dof     the bokeh reference: the parity portrait twice, DoF on (the hero camera: f/2, 7 blades,
            focus on the near cornea) and off, as a 100 % border crop around the head;
            dof.json with the thin-lens CoC predicted at the visible ear.
    lights  T25: the parity portrait's 100 % head crop (HEAD_CROP) with every rig light, then one light (and
            its twins) at a time, scene-linear, alpha = the character -> exr/lights_<tag>.exr, lights.json;
            bench/m1/face_light.py measures rim / key and the cheek's lit : shadow from them.

    blender -b -t 6 --factory-startup --python-exit-code 1 --python blender/hero/refs.py -- \\
        --in RUN/character.blend --out DIR --mode chart|bounce|dof|lights [--samples N] [--lights key,fill (chart, lights)]

(run Cycles inside `flock /tmp/or3-cycles.lock`). Never writes next to the input .blend.
"""

import argparse
import base64
import json
import math
import os
import sys
import time

import bpy
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.dirname(HERE) not in sys.path:
    sys.path.insert(0, os.path.dirname(HERE))

from hero import grade, poses, rig, sets, shots, stage, wet  # noqa: E402

SHOT = "portrait"
RES = (1920, 1080)


# ------------------------------------------------------------------ shared
def hide_character(ch):
    hidden = []
    for o in list(ch.objs) + [o for o in bpy.data.objects
                              if any(c.name == "hero_only" for c in o.users_collection)]:
        if not o.hide_render:
            o.hide_render = True
            hidden.append(o)
    return hidden


def setup_portrait(ch, set_kind, parity, dof, samples=None):
    """stage.render_shot up to the render (same calls, same order), for the portrait shot."""
    spec = shots.SHOTS[SHOT]
    stage.clear_transient()
    wet.restore(ch)
    if parity:
        spec = stage.parity_spec(spec)
    ch.pose_log = poses.apply(ch.arm, spec["pose"])
    rig.sync_props(ch)
    settings = rig.cycles("preview", spec["res"], samples=samples)
    sc = bpy.context.scene
    if parity:
        if hasattr(sc.cycles, "filter_width"):
            sc.cycles.filter_width = stage.PARITY_FILTER_PX
        if hasattr(sc.render, "filter_size"):
            sc.render.filter_size = stage.PARITY_FILTER_PX
    cam = rig.camera(ch, spec["cam"], dof=dof)
    eyes = wet.gaze(ch, cam["obj"].location, off_deg=spec["gaze"]) if spec.get("gaze") is not None else None
    cam["obj"].data.shift_x = spec.get("shift", 0.0)
    cam["obj"].data.shift_y = spec.get("shift_y", 0.0)
    if set_kind == "alley":
        sets.turn(cam["az"] + spec.get("set_yaw", 15.0))
        sets.neon(spec.get("neon", 1.0))
    lights = dict(spec.get("lights") or {})
    made = rig.hero_rig(ch, cam, lights=lights, twin=spec.get("twin"),
                        flag=spec.get("flag", ("key", "wrap", "fill", "eye")) if set_kind == "alley" else (),
                        practicals=rig.practical_lights() if set_kind == "alley" else (),
                        emitters=rig.practical_emitters() if set_kind == "alley" else ())
    if set_kind == "void":
        rig.world()
        rig.void_floor()
    sc.view_settings.exposure = 0.0
    sc.render.use_compositing = False
    bpy.context.view_layer.update()
    return spec, cam, settings, made, eyes


def focus_distance(ch, cam):
    """rig.camera's focal plane distance (the near eye's cornea), whether or not DoF is on."""
    loc = cam["obj"].location
    el, er = ch.eyes()
    c = el if (el - loc).length < (er - loc).length else er
    fp = c + (loc - c).normalized() * rig.EYE_FRONT
    return (fp - loc).length - rig._cam_opt(cam["spec"], "fo") / 1000.0


def cam_axes(cam_obj):
    m = cam_obj.matrix_world.to_3x3()
    return m.col[0].normalized(), m.col[1].normalized(), -m.col[2].normalized()   # right, up, forward


def to_px(pt, res=RES):
    """World point -> (x, y) px in the frame, top-left origin (lens shift included)."""
    from bpy_extras.object_utils import world_to_camera_view
    sc = bpy.context.scene
    v = world_to_camera_view(sc, sc.camera, Vector(pt))
    return [v.x * res[0], (1.0 - v.y) * res[1]]


def render_exr(path, res=None, border=None):
    """Full-float ZIP EXR (RGBA, single layer) of the current scene; border = (x0, x1, y0, y1)
    in 0..1 Blender (bottom-left) frame coordinates, cropped."""
    sc = bpy.context.scene
    r = sc.render
    if res:
        r.resolution_x, r.resolution_y = res
    r.resolution_percentage = 100
    s = r.image_settings
    s.media_type = "IMAGE"
    s.file_format = "OPEN_EXR"
    s.color_mode = "RGBA"
    s.color_depth = "32"
    s.exr_codec = "ZIP"
    r.filepath = path
    if border:
        r.use_border, r.use_crop_to_border = True, True
        r.border_min_x, r.border_max_x, r.border_min_y, r.border_max_y = border
    t = time.perf_counter()
    try:
        bpy.ops.render.render(write_still=True)
    finally:
        r.use_border = r.use_crop_to_border = False
    return round(time.perf_counter() - t, 1)


def grade_png(exr, png, ev, vignette=True):
    """grade.py --parity on one EXR (no bloom, halation, dispersion, grain or paint)."""
    g = dict(grade.GRADE, **grade.PARITY_OFF)
    if not vignette:
        g["vignette_ev"] = 0.0
    keep = bpy.context.window.scene if bpy.context.window else None
    secs = grade.grade(exr, png, 0.0, ev, g)
    if keep is not None:
        bpy.context.window.scene = keep
    return secs


def exr_rgb(path):
    import numpy as np
    return grade._oiio_read(path)[..., :3].astype(np.float64)


def png_rgb(path):
    import numpy as np
    return grade._oiio_read(path)[..., :3].astype(np.float64) * 255.0


def b64(a):
    import numpy as np
    return base64.b64encode(np.ascontiguousarray(a, dtype="<f4").tobytes()).decode("ascii")


# ------------------------------------------------------------------ chart
def _mesh_obj(col, name, verts, faces, mat):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], faces)
    me.update()
    ob = bpy.data.objects.new(name, me)
    col.objects.link(ob)
    me.materials.append(mat)
    return ob


def build_chart(ch, cam, depth):
    """Patches 18 / 50 / 90 % (5 cm, 1 cm gaps) in a row through the eyes' midpoint at the focal
    plane (perpendicular to the camera axis), an 18 % ball (8 cm) below; Lambertian, no specular."""
    col = rig.collection("chart")
    right, up, fwd = cam_axes(cam["obj"])
    loc = cam["obj"].location
    eyes = ch.aim("eyes")
    centre = loc + (eyes - loc) * (depth / (eyes - loc).dot(fwd))
    size, gap, ball_r = 0.05, 0.01, 0.04
    objs = []
    for i, alb in enumerate((0.18, 0.5, 0.9)):
        c = centre + right * ((i - 1) * (size + gap))
        h = size / 2
        vs = [c - right * h - up * h, c + right * h - up * h, c + right * h + up * h, c - right * h + up * h]
        m = rig._mat(f"chart_grey{round(alb * 100)}", (alb,) * 3, 1.0, 0.0)
        o = _mesh_obj(col, f"chart_grey{round(alb * 100)}", vs, [(0, 1, 2, 3)], m)
        objs.append((o, alb, "patch", c, h))
    bc = centre - up * (size / 2 + 0.015 + ball_r)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=96, ring_count=48, radius=ball_r, location=bc)
    b = bpy.context.active_object
    for cc in list(b.users_collection):
        cc.objects.unlink(b)
    col.objects.link(b)
    b.name = "chart_ball18"
    b.data.name = "chart_ball18"
    for p in b.data.polygons:
        p.use_smooth = True
    b.data.materials.append(rig._mat("chart_ball18", (0.18,) * 3, 1.0, 0.0))
    objs.append((b, 0.18, "ball", bc, ball_r))
    bpy.context.view_layer.update()
    return objs


def chart_records(objs, cam, key_obj):
    right, up, fwd = cam_axes(cam["obj"])
    out = []
    for o, alb, kind, c, h in objs:
        if kind == "patch":
            k = h * 0.6   # inset 20 % per side
            pts = [to_px(c + right * sx * k + up * sy * k) for sx in (-1, 1) for sy in (-1, 1)]
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            out.append({"name": o.name, "albedo": alb, "kind": kind,
                        "bbox_px": [round(min(xs)), round(min(ys)), round(max(xs)), round(max(ys))]})
        else:
            cp = to_px(c)
            rp = to_px(c + right * h)
            r_px = math.hypot(rp[0] - cp[0], rp[1] - cp[1])
            # sample points on the visible hemisphere: toward the key (lit), the centre, away (shadow),
            # and the key's terminator band, picked in the image plane from the key's direction
            L = (key_obj.matrix_world.translation - c).normalized()
            lx, ly = L.dot(right), L.dot(up)
            n = math.hypot(lx, ly) or 1.0
            dx, dy = lx / n, -ly / n          # image space (y down)
            pts = {"lit": [cp[0] + dx * 0.55 * r_px, cp[1] + dy * 0.55 * r_px],
                   "centre": list(cp),
                   "terminator": [cp[0] - dx * 0.25 * r_px, cp[1] - dy * 0.25 * r_px],
                   "shadow": [cp[0] - dx * 0.6 * r_px, cp[1] - dy * 0.6 * r_px]}
            out.append({"name": o.name, "albedo": alb, "kind": kind, "center_px": [round(v, 1) for v in cp],
                        "radius_px": round(r_px, 1), "samples_px": {k: [round(v, 1) for v in p] for k, p in pts.items()},
                        "sample_box_px": 7})
    return out


def measure_chart(recs, img):
    """Mean RGB inside each patch box / ball sample box of an (h, w, 3) image."""
    res = {}
    for r in recs:
        if r["kind"] == "patch":
            x0, y0, x1, y1 = r["bbox_px"]
            res[r["name"]] = [round(float(v), 5) for v in img[y0:y1, x0:x1].reshape(-1, 3).mean(0)]
        else:
            k = r["sample_box_px"] // 2
            for lab, (x, y) in r["samples_px"].items():
                x, y = int(round(x)), int(round(y))
                res[f"{r['name']}:{lab}"] = [round(float(v), 5) for v in img[y - k:y + k + 1, x - k:x + k + 1].reshape(-1, 3).mean(0)]
            cx, cy = r["center_px"]
            rr = r["radius_px"] * 0.85
            import numpy as np
            yy, xx = np.mgrid[0:img.shape[0], 0:img.shape[1]]
            m = (xx + 0.5 - cx) ** 2 + (yy + 0.5 - cy) ** 2 < rr * rr
            res[f"{r['name']}:disc"] = [round(float(v), 5) for v in img[m].mean(0)]
    return res


def export_glb(objs, path):
    bpy.ops.object.select_all(action="DESELECT")
    for o, *_ in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0][0]
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=True, export_yup=True,
                              export_cameras=False, export_lights=False, export_apply=True,
                              export_animations=False, export_skins=False, export_morph=False)
    # the exported materials: specular must be 0 (KHR_materials_specular), roughness 1, metallic 0
    import struct
    with open(path, "rb") as f:
        data = f.read()
    n = struct.unpack("<I", data[12:16])[0]
    j = json.loads(data[20:20 + n])
    return [{"name": m["name"], "pbr": m.get("pbrMetallicRoughness"), "ext": m.get("extensions")}
            for m in j.get("materials", [])]


def mode_chart(ch, out, samples, only=None):
    import shutil
    spec, cam, settings, made, _ = setup_portrait(ch, "void", parity=True, dof=False, samples=samples)
    if only:   # per-light chart (--lights key,fill): the other rig lights (and their twins) off
        for name, o in made.items():
            o.hide_render = name.split("_")[0] not in only
    depth = focus_distance(ch, cam)
    hide_character(ch)
    objs = build_chart(ch, cam, depth)
    recs = chart_records(objs, cam, made["key"])
    os.makedirs(os.path.join(out, "exr"), exist_ok=True)
    exr = os.path.join(out, "exr", "chart.exr")
    secs = render_exr(exr, RES)
    ev = rig.HERO_EXPOSURE + spec.get("ev", 0.0)
    png = os.path.join(out, "chart.png")
    gsecs = grade_png(exr, png, ev)
    lin = measure_chart(recs, exr_rgb(exr))
    disp = measure_chart(recs, png_rgb(png))
    mats = export_glb(objs, os.path.join(out, "chart.glb"))
    rec = {"version": 1, "res": list(RES), "shot": SHOT, "exposure": ev, "focus_m": round(depth, 6),
           "patches": recs, "glb_materials": mats,
           "cycles": {"exr": "exr/chart.exr", "png": "chart.png", "render_s": secs, "grade_s": gsecs,
                      "samples": bpy.context.scene.cycles.samples, "denoise": bpy.context.scene.cycles.use_denoising,
                      "linear_means": lin, "graded_means_255": disp},
           "rig": sorted(made.keys()),
           "note": "void set, parity settings (1 px filter, no haze/rain/beads/wet, DoF off), character hidden; "
                   "graded with grade.py --parity at the shot exposure"}
    with open(os.path.join(out, "chart.json"), "w") as f:
        json.dump(rec, f, indent=1)
    print(f"[refs] chart: {secs} s, grade {gsecs} s -> {out}", flush=True)
    return rec


# ------------------------------------------------------------------ bounce
FACES = {"px": (1, 0, 0), "nx": (-1, 0, 0), "py": (0, 1, 0), "ny": (0, -1, 0), "pz": (0, 0, 1), "nz": (0, 0, -1)}


def face_matrix(d):
    d = Vector(d).normalized()
    up = Vector((0, 0, 1)) if abs(d.z) < 0.9 else Vector((0, 1, 0))
    right = d.cross(up).normalized()
    up2 = right.cross(d).normalized()
    m = Matrix.Identity(3)
    m.col[0], m.col[1], m.col[2] = right, up2, -d
    return m


def mode_bounce(ch, out, samples, face=32, W=128, H=64):
    import numpy as np
    spec, cam, settings, made, _ = setup_portrait(ch, "alley", parity=False, dof=False, samples=samples)
    hide_character(ch)
    for o in bpy.data.collections["hero_rig"].all_objects:
        o.visible_camera = False
    head = ch.aim("eyes")
    sc = bpy.context.scene
    cd = bpy.data.cameras.new("bounce_cam")
    cd.type = "PERSP"
    cd.sensor_fit = "AUTO"
    cd.angle = math.pi / 2
    cd.clip_start, cd.clip_end = 0.01, 500.0
    co = bpy.data.objects.new("bounce_cam", cd)
    rig.collection("hero_cams", clear=False).objects.link(co)
    co.location = head
    sc.camera = co
    c = sc.cycles
    c.use_adaptive_sampling = False
    c.use_denoising = False
    c.samples = samples or 1024
    sc.cycles.filter_width = 1.5
    os.makedirs(os.path.join(out, "faces"), exist_ok=True)
    faces, mats, secs = {}, {}, 0.0
    for name, d in FACES.items():
        m3 = face_matrix(d)
        co.matrix_world = Matrix.Translation(head) @ m3.to_4x4()
        bpy.context.view_layer.update()
        p = os.path.join(out, "faces", f"{name}.exr")
        secs += render_exr(p, (face, face))
        faces[name] = exr_rgb(p)                      # rows top-down
        mats[name] = co.matrix_world.to_3x3().copy()
    # resample: three equirect (row 0 = bottom, v = 0) -> three direction -> Blender direction -> face
    env = np.zeros((H, W, 3))
    ss = 4
    for j in range(H):
        for i in range(W):
            acc = np.zeros(3)
            for sj in range(ss):
                for si in range(ss):
                    u = (i + (si + 0.5) / ss) / W
                    v = (j + (sj + 0.5) / ss) / H
                    phi = (u - 0.5) * 2 * math.pi
                    lat = (v - 0.5) * math.pi
                    tx, ty, tz = math.cos(phi) * math.cos(lat), math.sin(lat), math.sin(phi) * math.cos(lat)
                    wb = Vector((tx, -tz, ty))                 # Blender world
                    best, bl = None, None
                    for name, m3 in mats.items():
                        loc_ = m3.transposed() @ wb
                        if best is None or -loc_.z > best:
                            best, bl = -loc_.z, (name, loc_)
                    name, loc_ = bl
                    fu = loc_.x / -loc_.z
                    fv = loc_.y / -loc_.z
                    img = faces[name]
                    x = (fu + 1) / 2 * face - 0.5
                    y = (1 - (fv + 1) / 2) * face - 0.5
                    x0, y0 = int(math.floor(x)), int(math.floor(y))
                    fx, fy = x - x0, y - y0
                    def px(xx, yy):
                        return img[min(max(yy, 0), face - 1), min(max(xx, 0), face - 1)]
                    acc += ((1 - fx) * (1 - fy) * px(x0, y0) + fx * (1 - fy) * px(x0 + 1, y0)
                            + (1 - fx) * fy * px(x0, y0 + 1) + fx * fy * px(x0 + 1, y0 + 1))
            env[j, i] = acc / (ss * ss)
    # irradiance: cosine-weighted over the hemisphere around n (three world)
    jj, ii = np.mgrid[0:H, 0:W]
    lat = ((jj + 0.5) / H - 0.5) * math.pi
    phi = ((ii + 0.5) / W - 0.5) * 2 * math.pi
    dirs = np.stack([np.cos(phi) * np.cos(lat), np.sin(lat), np.sin(phi) * np.cos(lat)], -1)
    dw = (2 * math.pi / W) * (math.pi / H) * np.cos(lat)
    lum = env @ np.array([0.2126, 0.7152, 0.0722])

    def irr(n):
        n = np.asarray(n, float) / np.linalg.norm(n)
        cosw = np.maximum(dirs @ n, 0) * dw
        return float((lum * cosw).sum()), [float((env[..., k] * cosw).sum()) for k in range(3)]
    b2t = lambda v: [v[0], v[2], -v[1]]                 # Blender -> three
    to_cam = (cam["obj"].location - head).normalized()
    e_cam, e_cam_rgb = irr(b2t(to_cam))
    axes = {k: irr(b2t(d))[0] for k, d in FACES.items()}
    key = rig.HERO_LIGHTS["key"]
    k_spec = dict(rig.HERO_LIGHTS, **dict(spec.get("lights") or {}))["key"]
    e_key = k_spec[1] * rig.HERO_E
    rec = {"version": 1, "width": W, "height": H, "row0": "bottom",
           "convention": "three equirect u=atan2(z,x)/2pi+0.5, v=asin(y)/pi+0.5 (three/glTF world: x=Bx, y=Bz, z=-By)",
           "units": "scene-linear radiance, Cycles (exposure 0)",
           "head_three": b2t(list(head)), "shot": SHOT, "set": "alley",
           "faces": {"size": face, "samples": c.samples, "render_s": round(secs, 1)},
           "data": b64(env),
           "irradiance": {"key_at_face": e_key,
                          "key_note": "rig._light_power: the key's on-axis irradiance at the subject = ratio * HERO_E "
                                      "(W/m^2 in Blender's area-light units; white-normalised colour)",
                          "env_facing_camera": round(e_cam, 6), "env_facing_camera_rgb": [round(v, 6) for v in e_cam_rgb],
                          "env_axes": {k: round(v, 6) for k, v in axes.items()},
                          "env_mean_radiance": round(float((lum * dw).sum() / (4 * math.pi)), 6),
                          "ratio_facing_camera": round(e_cam / e_key, 6)},
           "notes": "rig lights invisible to camera; flagged rig lights (key, wrap, fill, eye) light only the "
                    "character and so nothing here, as in the beauty render; no rain, haze or beads"}
    with open(os.path.join(out, "set_bounce.json"), "w") as f:
        json.dump(rec, f)
    # preview: upright (top = up), exposure-scaled sRGB
    p95 = float(np.percentile(lum, 95)) or 1.0
    pv = np.clip(env[::-1] * (0.8 / p95), 0, 1)
    pv = np.where(pv <= 0.0031308, pv * 12.92, 1.055 * pv ** (1 / 2.4) - 0.055)
    big = np.repeat(np.repeat(pv, 4, 0), 4, 1)
    grade._oiio_write(os.path.join(out, "set_bounce_preview.exr"), big.astype(np.float32))
    import OpenImageIO as oiio
    buf = oiio.ImageBuf(os.path.join(out, "set_bounce_preview.exr"))
    buf.write(os.path.join(out, "set_bounce_preview.png"), "uint8")
    os.remove(os.path.join(out, "set_bounce_preview.exr"))
    print(f"[refs] bounce: faces {round(secs, 1)} s; ratio facing camera {rec['irradiance']['ratio_facing_camera']}",
          flush=True)
    return rec


# ------------------------------------------------------------------ dof
def ear_point(ch, cam):
    """The visible ear: on the evaluated (posed) head skin, the side facing the camera, the vertex
    farthest out sideways (head-bone x) in a band at eye height that lies behind the eyes (the helix
    rim). Returns the world point and how it was picked."""
    dg = bpy.context.evaluated_depsgraph_get()
    head = ch._deform("head")
    hi = head.inverted()
    el, er = ch.eyes()
    loc = cam["obj"].location
    # head-bone frame: rest axes (x lateral, -y forward, z up); camera side in that frame
    eyes_l = hi @ ((el + er) * 0.5)
    cam_l = hi @ loc
    side = 1.0 if (cam_l.x - eyes_l.x) > 0 else -1.0
    best = None
    names = []
    for o in ch.objs:
        if o.type != "MESH" or not any(s.material and s.material.name.startswith("skin_head")
                                       for s in o.material_slots):
            continue
        names.append(o.name)
        ev = o.evaluated_get(dg)
        me = ev.to_mesh()
        slots = {i for i, s in enumerate(o.material_slots) if s.material and s.material.name.startswith("skin_head")}
        vids = set()
        for p in me.polygons:
            if p.material_index in slots:
                vids.update(p.vertices)
        mw = ev.matrix_world
        for vi in vids:
            w = mw @ me.vertices[vi].co
            q = hi @ w
            dz = q.z - eyes_l.z
            dy = q.y - eyes_l.y                     # + = behind the eyes
            if -0.035 < dz < 0.02 and 0.05 < dy < 0.14:
                s = (q.x - eyes_l.x) * side
                if best is None or s > best[0]:
                    best = (s, w.copy())
        ev.to_mesh_clear()
    if best is None:
        raise RuntimeError("no ear vertex found")
    return best[1], {"meshes": names, "side": "+x (character left)" if side > 0 else "-x (character right)",
                     "rule": "posed skin_head vertex farthest out sideways on the camera side, 0.035 m below to "
                             "0.02 m above the eyes, 0.05-0.14 m behind them (head-bone frame): the helix rim",
                     "lateral_m": round(best[0], 4)}


def mode_dof(ch, out, samples):
    spec, cam, settings, made, _ = setup_portrait(ch, "void", parity=True, dof=True, samples=samples)
    sc = bpy.context.scene
    co = cam["obj"]
    cd = co.data
    S1 = cd.dof.focus_distance
    fstop = cd.dof.aperture_fstop
    f = cd.lens / 1000.0
    ear, how = ear_point(ch, cam)
    right, up, fwd = cam_axes(co)
    S2 = (ear - co.location).dot(fwd)
    sensor = cd.sensor_height / 1000.0
    r_pred = 0.5 * (f * f / fstop) * abs(S2 - S1) / (S2 * (S1 - f)) / sensor * RES[1]
    ear_px = to_px(ear)
    eyes_px = to_px(ch.aim("eyes"))
    # head box: centred between the eyes and the ear, 0.5 x 0.5 of the frame (960 x 540 at 100 %)
    cw, chh = 960, 540
    cx = min(max((ear_px[0] + eyes_px[0]) / 2, cw / 2), RES[0] - cw / 2)
    cy = min(max((ear_px[1] + eyes_px[1]) / 2 - 40, chh / 2), RES[1] - chh / 2)
    x0, y0 = int(round(cx - cw / 2)), int(round(cy - chh / 2))
    border = (x0 / RES[0], (x0 + cw) / RES[0], 1 - (y0 + chh) / RES[1], 1 - y0 / RES[1])
    sc.cycles.use_adaptive_sampling = False
    sc.cycles.use_denoising = False
    sc.cycles.samples = samples or 512
    os.makedirs(os.path.join(out, "exr"), exist_ok=True)
    ev = rig.HERO_EXPOSURE + spec.get("ev", 0.0)
    rec = {"version": 1, "shot": SHOT, "lens_mm": cd.lens, "sensor_mm": cd.sensor_height, "sensor_fit": cd.sensor_fit,
           "fstop": fstop, "blades": cd.dof.aperture_blades, "focus_m": round(S1, 6), "res": list(RES),
           "ear_world_blender": [round(v, 5) for v in ear], "ear_how": how, "ear_depth_m": round(S2, 5),
           "ear_px": [round(v, 1) for v in ear_px], "eyes_px": [round(v, 1) for v in eyes_px],
           "crop": {"offset_px": [x0, y0], "size_px": [cw, chh], "border_blender": [round(b, 6) for b in border]},
           "ear_px_in_crop": [round(ear_px[0] - x0, 1), round(ear_px[1] - y0, 1)],
           "coc_radius_px_predicted": round(r_pred, 3),
           "coc_formula": "r = 0.5 * (f^2/N) * |S2 - S1| / (S2 * (S1 - f)) / sensor_h * 1080",
           "samples": sc.cycles.samples, "denoise": False, "filter_px": stage.PARITY_FILTER_PX, "renders": {}}
    for tag, on in (("dof", True), ("sharp", False)):
        cd.dof.use_dof = on
        exr = os.path.join(out, "exr", f"portrait_{tag}_crop.exr")
        s = render_exr(exr, RES, border)
        png = os.path.join(out, f"portrait_{tag}_crop.png")
        grade_png(exr, png, ev, vignette=False)
        rec["renders"][tag] = {"exr": f"exr/portrait_{tag}_crop.exr", "png": f"portrait_{tag}_crop.png", "render_s": s}
        with open(os.path.join(out, "dof.json"), "w") as f_:
            json.dump(rec, f_, indent=1)
        print(f"[refs] dof {tag}: {s} s", flush=True)
    return rec


# ------------------------------------------------------------------ lights
HEAD_CROP = (766, 74, 540, 540)   # x, y, w, h in the 1920 x 1080 portrait: T19's 100 % head crop


def mode_lights(ch, out, samples, only=None):
    """T25: the parity portrait's head crop (HEAD_CROP, 100 %) once with every rig light and once per
    light (each with its twins), scene-linear, film transparent so alpha is the character mask (the
    floor is out of the crop). bench/m1/face_light.py measures them (rim / key, cheek lit : shadow)."""
    spec, cam, settings, made, _ = setup_portrait(ch, "void", parity=True, dof=False, samples=samples)
    sc = bpy.context.scene
    sc.render.film_transparent = True
    x, y, w, h = HEAD_CROP
    border = (x / RES[0], (x + w) / RES[0], 1 - (y + h) / RES[1], 1 - y / RES[1])
    names = sorted({n.split("_")[0] for n in made})
    tags = ["all"] + [n for n in names if not only or n in only]
    os.makedirs(os.path.join(out, "exr"), exist_ok=True)
    rec = {"version": 1, "shot": SHOT, "crop": list(HEAD_CROP), "res": list(RES), "lights": {},
           "exposure": rig.HERO_EXPOSURE + spec.get("ev", 0.0), "samples": sc.cycles.samples,
           "rig": {n: {"power_w": round(o.data.energy, 4), "color": [round(c, 4) for c in o.data.color],
                       "use_temperature": bool(o.data.use_temperature),
                       "kelvin": o.data.temperature if o.data.use_temperature else None,
                       "size": [round(o.data.size, 3), round(o.data.size_y, 3)]} for n, o in made.items()},
           "note": "void set, parity settings (1 px filter, no haze/rain/beads/wet, DoF off); exr/lights_<tag>.exr "
                   "is the head crop with only that light and its twins (all: every light)"}
    for tag in tags:
        for n, o in made.items():
            o.hide_render = not (tag == "all" or n.split("_")[0] == tag)
        exr = os.path.join(out, "exr", f"lights_{tag}.exr")
        s = render_exr(exr, RES, border)
        rec["lights"][tag] = {"exr": f"exr/lights_{tag}.exr", "render_s": s,
                              "members": sorted(n for n in made if tag == "all" or n.split("_")[0] == tag)}
        with open(os.path.join(out, "lights.json"), "w") as f:
            json.dump(rec, f, indent=1)
        print(f"[refs] lights {tag}: {s} s", flush=True)
    return rec


def main(argv):
    ap = argparse.ArgumentParser(prog="refs.py")
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--mode", choices=["chart", "bounce", "dof", "lights", "probe"], required=True)
    ap.add_argument("--samples", type=int, default=0)
    ap.add_argument("--lights", help="chart / lights: only these rig lights, e.g. key,fill (per-light decomposition)")
    a = ap.parse_args(argv)
    out = os.path.abspath(a.out)
    if os.path.dirname(os.path.abspath(a.inp)) == out:
        sys.exit("refs.py: --out must not be the input's run dir")
    os.makedirs(out, exist_ok=True)
    rig.PCT = 100
    ch = rig.load_character(a.inp)
    for o in ch.objs:
        o.pass_index = 1
    stage.skin_sss(ch)
    from character import suit_textures   # the suit twill in Cycles, as stage.main does
    if a.inp.endswith(".glb"):
        suit_textures.cycles_weave_sidecar(a.inp)
    else:
        suit_textures.cycles_weave_blend(a.inp)
    t = time.perf_counter()
    if a.mode == "chart":
        mode_chart(ch, out, a.samples or 256, a.lights.split(",") if a.lights else None)
    elif a.mode == "bounce":
        sets.alley()
        mode_bounce(ch, out, a.samples or 1024)
    elif a.mode == "dof":
        mode_dof(ch, out, a.samples or 512)
    elif a.mode == "lights":
        mode_lights(ch, out, a.samples or 128, a.lights.split(",") if a.lights else None)
    else:
        spec, cam, settings, made, _ = setup_portrait(ch, "void", parity=True, dof=True)
        ear, how = ear_point(ch, cam)
        print("[refs] probe focus", cam["obj"].data.dof.focus_distance, focus_distance(ch, cam),
              "ear", tuple(ear), how, "ear_px", to_px(ear), "eyes_px", to_px(ch.aim("eyes")),
              "lights", sorted(made), flush=True)
    print(f"[refs] {a.mode}: {round(time.perf_counter() - t, 1)} s", flush=True)


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
