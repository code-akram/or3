"""Compositor grade for the hero shots (direction.md §5 grade, §4 painterly).

Runs on the scene-linear multilayer EXRs the stage writes (Combined +
IndexOB, the character has pass index 1), in a separate compositor-only
scene, so the grade can be re-tuned without re-rendering:

    blender -b --factory-startup --python-exit-code 1 --python blender/hero/grade.py -- \\
        --exr DIR/exr/portrait.exr [--exr ...] --out DIR [--ev 0.0] [--paint 0.6]

Chain (linear, before the view transform):
  painterly  anisotropic Kuwahara, mixed in on the set only (the character
             mask keeps skin, eyes and hair clean: the face is where realism
             lives); written as the _paint A/B variant
  bloom      Glare/Bloom on the highlights (neon cores, speculars)
  halation   a red-orange Fog Glow from the brightest sources, ~1.5 %
  lens       a touch of lateral chromatic dispersion
  grade      CDL: shadows toward teal, highlights toward amber, black point
             lifted so blacks sit at ~0.02 display
  vignette   -0.3 EV at the corners
  grain      ~2 % luminance-proportional, 1 px
then AgX with the "Medium High Contrast" look (contrast +15 %).
"""

import argparse
import json
import os
import sys
import time

import bpy

LOOK = "AgX - Base Contrast"   # skin-direction.md: contrast from CDL power, not the look
GRADE = {
    "bloom_threshold": 1.0, "bloom_strength": 0.35, "bloom_size": 0.55,
    "halation_threshold": 2.0, "halation_strength": 0.12, "halation_tint": (1.0, 0.32, 0.12),
    "dispersion": 0.008,
    "slope": (1.04, 1.0, 0.94), "offset": (-0.0008, 0.0004, 0.0016), "power": (1.08, 1.08, 1.08),
    "black_lift": 0.0011,
    "vignette_ev": -0.3,
    "grain": 0.02,
    "saturation": 0.97,
    # white point: the colour of a `wb_kelvin` blackbody is mapped to white
    # (None = the render's 6,500 K white). Shot-independent; see hero-stage.md.
    "wb_kelvin": 3900,
    "paint_size": 5, "paint_sharpness": 0.4, "paint_eccentricity": 1.2, "paint_uniformity": 3,
}


# grade.py --parity: the output-pass effects the engine frame is compared without
PARITY_OFF = {"bloom_strength": 0.0, "halation_strength": 0.0, "dispersion": 0.0, "grain": 0.0}


def _new(nt, t, **kw):
    n = nt.nodes.new(t)
    for k, v in kw.items():
        setattr(n, k, v)
    return n


def _set(n, name, v):
    s = n.inputs.get(name)
    if s is None:
        raise KeyError(f"{n.bl_idname} has no input {name!r}: {[i.name for i in n.inputs]}")
    s.default_value = v


def _menu(n, name, v):
    """Menu sockets (5.x node options moved to inputs) or legacy properties."""
    s = n.inputs.get(name)
    if s is not None:
        s.default_value = v
    else:
        setattr(n, name.lower().replace(" ", "_"), v)


def _mix(nt, blend, a, b, fac=1.0):
    m = nt.nodes.new("ShaderNodeMix")
    m.data_type = "RGBA"
    m.blend_type = blend
    m.clamp_result = False
    if isinstance(fac, bpy.types.NodeSocket):
        nt.links.new(fac, m.inputs[0])
    else:
        m.inputs[0].default_value = fac
    for sock, v in ((m.inputs[6], a), (m.inputs[7], b)):
        if isinstance(v, bpy.types.NodeSocket):
            nt.links.new(v, sock)
        else:
            sock.default_value = v
    return m.outputs[2]


def _math(nt, op, a, b=None, c=None):
    m = nt.nodes.new("ShaderNodeMath")
    m.operation = op
    for i, v in enumerate((a, b, c)):
        if v is None:
            continue
        if isinstance(v, bpy.types.NodeSocket):
            nt.links.new(v, m.inputs[i])
        else:
            m.inputs[i].default_value = v
    return m.outputs[0]


def exr_size(path):
    """(width, height) from an OpenEXR header's dataWindow (Blender does not
    report the size of a multilayer EXR before it is composited)."""
    import struct
    with open(path, "rb") as f:
        head = f.read(1 << 16)
    i = head.index(b"dataWindow\0box2i\0") + len(b"dataWindow\0box2i\0") + 4
    x0, y0, x1, y1 = struct.unpack("<4i", head[i:i + 16])
    return x1 - x0 + 1, y1 - y0 + 1


def build(exr_path, paint, g=GRADE):
    """Compositor tree for one EXR; returns the scene."""
    img = bpy.data.images.load(exr_path, check_existing=False)
    sc = bpy.data.scenes.get("grade") or bpy.data.scenes.new("grade")
    w, h = exr_size(exr_path)
    r = sc.render
    r.resolution_x, r.resolution_y, r.resolution_percentage = w, h, 100
    r.engine = "BLENDER_WORKBENCH"
    r.use_compositing = True
    r.use_sequencer = False
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.look = LOOK
    nt = bpy.data.node_groups.new("grade", "CompositorNodeTree")
    nt.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    sc.compositing_node_group = nt
    src = _new(nt, "CompositorNodeImage")
    src.image = img
    out = _new(nt, "NodeGroupOutput")
    names = [o.name for o in src.outputs]
    rgb = src.outputs["Combined"] if "Combined" in names else src.outputs["Image"]
    mask = src.outputs["IndexOB"] if "IndexOB" in names else None

    x = rgb
    if paint > 0:
        k = _new(nt, "CompositorNodeKuwahara")
        _menu(k, "Type", "Anisotropic")
        size = max(2, round(g["paint_size"] * w / 1920))
        _set(k, "Size", size)
        _set(k, "Uniformity", g["paint_uniformity"])
        _set(k, "Sharpness", g["paint_sharpness"])
        _set(k, "Eccentricity", g["paint_eccentricity"])
        nt.links.new(x, k.inputs["Image"])
        fac = paint
        if mask is not None:
            # character = index 1 -> no paint; soften the mask edge
            ch = _math(nt, "COMPARE", mask, 1.0, 0.5)
            bl = _new(nt, "CompositorNodeBlur")
            _set(bl, "Size", (max(2, w // 400), max(2, w // 400)))
            nt.links.new(ch, bl.inputs["Image"])
            sep = _new(nt, "CompositorNodeSeparateColor")
            nt.links.new(bl.outputs[0], sep.inputs[0])
            fac = _math(nt, "MULTIPLY", _math(nt, "SUBTRACT", 1.0, sep.outputs["Red"]), paint)
        x = _mix(nt, "MIX", x, k.outputs["Image"], fac)

    if g["bloom_strength"]:
        bloom = _new(nt, "CompositorNodeGlare")
        _menu(bloom, "Type", "Bloom")
        _menu(bloom, "Quality", "High")
        _set(bloom, "Threshold", g["bloom_threshold"])
        _set(bloom, "Strength", g["bloom_strength"])
        _set(bloom, "Size", g["bloom_size"])
        nt.links.new(x, bloom.inputs["Image"])
        x = bloom.outputs["Image"]

    if g["halation_strength"]:
        hal = _new(nt, "CompositorNodeGlare")
        _menu(hal, "Type", "Fog Glow")
        _menu(hal, "Quality", "Medium")
        _set(hal, "Threshold", g["halation_threshold"])
        _set(hal, "Strength", g["halation_strength"])
        _set(hal, "Size", 0.35)
        _set(hal, "Tint", (*g["halation_tint"], 1.0))
        nt.links.new(x, hal.inputs["Image"])
        x = hal.outputs["Image"]

    if g["dispersion"]:
        ld = _new(nt, "CompositorNodeLensdist")
        _set(ld, "Dispersion", g["dispersion"])
        _set(ld, "Distortion", 0.0)
        nt.links.new(x, ld.inputs["Image"])
        x = ld.outputs["Image"]

    if g.get("wb_kelvin"):
        wb = _new(nt, "CompositorNodeColorBalance")
        _menu(wb, "Type", "White Point")
        _set(wb, "Factor", 1.0)
        temps = [i for i in wb.inputs if "Temperature" in i.name]
        temps[0].default_value = g["wb_kelvin"]          # input white
        if len(temps) > 1:
            temps[1].default_value = 6500.0              # output white
        nt.links.new(x, wb.inputs["Image"])
        x = wb.outputs["Image"]

    cb = _new(nt, "CompositorNodeColorBalance")
    _menu(cb, "Type", "Offset/Power/Slope (ASC-CDL)")
    _set(cb, "Factor", 1.0)
    # 5.x: Offset/Power/Slope are colour inputs; the second socket of each
    # name pair is the CDL one.
    for name, val in (("Offset", g["offset"]), ("Power", g["power"]), ("Slope", g["slope"])):
        socks = [i for i in cb.inputs if i.name == name]
        for s in socks:
            if s.type == "RGBA":
                s.default_value = (*val, 1.0)
            elif s.type == "VALUE":
                s.default_value = 0.0 if name == "Offset" else 1.0
    nt.links.new(x, cb.inputs["Image"])
    x = _mix(nt, "ADD", cb.outputs["Image"], (g["black_lift"],) * 3 + (1.0,), 1.0)

    hs = _new(nt, "CompositorNodeHueSat")
    _set(hs, "Saturation", g["saturation"])
    nt.links.new(x, hs.inputs["Image"])
    x = hs.outputs["Image"]

    # vignette: ellipse -> blur -> map to a gain between 2^ev (edge) and 1
    em = _new(nt, "CompositorNodeEllipseMask")
    _set(em, "Size", (0.95, 0.95 * 1.0))
    vb = _new(nt, "CompositorNodeBlur")
    _set(vb, "Size", (w // 3, h // 3))
    _menu(vb, "Type", "Gaussian")
    nt.links.new(em.outputs["Mask"], vb.inputs["Image"])
    vs = _new(nt, "CompositorNodeSeparateColor")
    nt.links.new(vb.outputs[0], vs.inputs[0])
    edge = 2.0 ** g["vignette_ev"]
    gain = _math(nt, "MULTIPLY_ADD", vs.outputs["Red"], 1.0 - edge, edge)
    mul = nt.nodes.new("ShaderNodeMix")
    mul.data_type = "RGBA"
    mul.blend_type = "MULTIPLY"
    mul.clamp_result = False
    mul.inputs[0].default_value = 1.0
    nt.links.new(x, mul.inputs[6])
    comb = _new(nt, "CompositorNodeCombineColor")
    for ch in ("Red", "Green", "Blue"):
        nt.links.new(gain, comb.inputs[ch])
    nt.links.new(comb.outputs[0], mul.inputs[7])
    x = mul.outputs[2]

    if not g["grain"]:
        nt.links.new(x, out.inputs[0])
        return sc
    # grain: white noise on pixel coordinates, luminance-proportional
    co = _new(nt, "CompositorNodeImageCoordinates")
    nt.links.new(rgb, co.inputs["Image"])
    wn = _new(nt, "ShaderNodeTexWhiteNoise")
    wn.noise_dimensions = "2D"
    nt.links.new(co.outputs["Pixel"], wn.inputs["Vector"])
    gsc = _math(nt, "MULTIPLY_ADD", wn.outputs["Value"], 2 * g["grain"], 1.0 - g["grain"])
    gc = _new(nt, "CompositorNodeCombineColor")
    for ch in ("Red", "Green", "Blue"):
        nt.links.new(gsc, gc.inputs[ch])
    x = _mix(nt, "MULTIPLY", x, gc.outputs[0], 1.0)

    nt.links.new(x, out.inputs[0])
    return sc


def grade(exr_path, out_png, paint=0.0, ev=0.0, g=GRADE):
    sc = build(exr_path, paint, g)
    sc.view_settings.exposure = ev
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGB"
    sc.render.filepath = out_png
    t = time.perf_counter()
    bpy.ops.render.render(write_still=True, scene=sc.name)
    secs = round(time.perf_counter() - t, 2)
    nt = sc.compositing_node_group
    sc.compositing_node_group = None
    bpy.data.node_groups.remove(nt)
    for im in list(bpy.data.images):
        if im.filepath and os.path.abspath(bpy.path.abspath(im.filepath)) == os.path.abspath(exr_path):
            bpy.data.images.remove(im)
    return secs


# ------------------------------------------------------------------ grade as data (T16)
# The engine applies the hero grade from a sidecar baked HERE, through Blender itself, so the
# engine grade is Blender's by construction (bench/m1/v4/checkpoint-3.md §2.6):
#   grade     33^3 LUT of the colour-only compositor chain (build() with PARITY_OFF, no paint,
#             vignette gain 1): white point -> CDL -> black lift -> Hue/Sat. Input: scene-linear
#             through a log2 shaper t = (log2(max(x, 2^lo)) - lo) / (hi - lo); output log2(y).
#   view      33^3 LUT of the view transform grade() writes PNGs through: view exposure 0, AgX, the
#             LOOK, sRGB display. Input: the exposed scene-linear value through the same kind of
#             shaper; output display-encoded 0..1.
#   vignette  the compositor's vignette gain (ellipse -> Gaussian -> 2^ev..1) at 1920x1080, 96x54.
# The engine: x -> LUT_G -> exp2 -> x vignette -> (grain) -> x 2^EV -> LUT_V -> display.
# Lattice order ((b * N + g) * N + r) * 3 + c (r fastest: a three.js Data3DTexture as is).
LUT_SIZE = 33
LUT_G_RANGE = (-12.0, 5.0)   # tuned on the grey ramp (grade_lut_verify.json)
LUT_V_RANGE = (-13.0, 5.0)
LUT_OUT_FLOOR = -24.0


def _oiio_write(path, arr):
    import numpy as np
    import OpenImageIO as oiio
    a = np.ascontiguousarray(arr, dtype=np.float32)
    h, w, c = a.shape
    spec = oiio.ImageSpec(w, h, c, "float")
    spec.attribute("compression", "zip")
    o = oiio.ImageOutput.create(path)
    if not o or not o.open(path, spec):
        raise RuntimeError(f"cannot write {path}")
    o.write_image(a)
    o.close()


def _oiio_read(path):
    import numpy as np
    import OpenImageIO as oiio
    i = oiio.ImageInput.open(path)
    if not i:
        raise RuntimeError(f"cannot read {path}")
    a = np.asarray(i.read_image(format="float"), dtype=np.float64)
    i.close()
    return a


def _through_blender(rgb, tmp, tag, g, out="exr", ev=0.0):
    """Push an (h, w, 3) scene-linear array through build(g) and the scene's output path:
    out='exr' -> the composited scene-linear values; out='png' -> the 16-bit display PNG with the
    hero view (AgX + LOOK, exposure ev), exactly grade()'s transform but 16-bit and undithered."""
    import numpy as np
    h, w, _ = rgb.shape
    src = os.path.join(tmp, f"{tag}_in.exr")
    _oiio_write(src, np.concatenate([rgb, np.ones((h, w, 1))], axis=-1))
    sc = build(src, 0.0, g) if g is not None else _passthrough(src)
    sc.view_settings.exposure = ev
    sc.render.dither_intensity = 0.0
    if hasattr(sc.render, "compositor_precision"):
        sc.render.compositor_precision = "FULL"
    s = sc.render.image_settings
    if out == "exr":
        s.file_format = "OPEN_EXR"
        s.color_depth = "32"
        s.exr_codec = "ZIP"
        s.color_mode = "RGB"
        dst = os.path.join(tmp, f"{tag}_out.exr")
    else:
        s.file_format = "PNG"
        s.color_mode = "RGB"
        s.color_depth = "16"
        dst = os.path.join(tmp, f"{tag}_out.png")
    sc.render.filepath = dst
    bpy.ops.render.render(write_still=True, scene=sc.name)
    nt = sc.compositing_node_group
    sc.compositing_node_group = None
    bpy.data.node_groups.remove(nt)
    for im in list(bpy.data.images):
        if im.filepath and os.path.abspath(bpy.path.abspath(im.filepath)) == os.path.abspath(src):
            bpy.data.images.remove(im)
    return _oiio_read(dst)[..., :3]


def _passthrough(exr_path):
    """build()'s scene and output path with no grade nodes: Image -> Output (the view LUT bake: a
    neutral build() would still round-trip Hue/Sat's HSV, which loses ~1e-5 on extreme colours)."""
    img = bpy.data.images.load(exr_path, check_existing=False)
    sc = bpy.data.scenes.get("grade") or bpy.data.scenes.new("grade")
    w, h = exr_size(exr_path)
    r = sc.render
    r.resolution_x, r.resolution_y, r.resolution_percentage = w, h, 100
    r.engine = "BLENDER_WORKBENCH"
    r.use_compositing = True
    r.use_sequencer = False
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.look = LOOK
    nt = bpy.data.node_groups.new("grade", "CompositorNodeTree")
    nt.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    sc.compositing_node_group = nt
    src = _new(nt, "CompositorNodeImage")
    src.image = img
    out = _new(nt, "NodeGroupOutput")
    nt.links.new(src.outputs["Image"], out.inputs[0])
    return sc


def _lattice(lo, hi, n=LUT_SIZE):
    """(n, n*n, 3) image of the lattice: row b, column r + n*g; values decoded from the shaper."""
    import numpy as np
    v = 2.0 ** (lo + (hi - lo) * np.arange(n) / (n - 1))
    b, g, r = np.meshgrid(v, v, v, indexing="ij")          # [b, g, r]
    img = np.stack([r, g, b], axis=-1).reshape(n, n * n, 3)   # row b; column g*n + r
    return img


def _unlattice(img, n=LUT_SIZE):
    return img.reshape(n, n, n, 3)                            # [b, g, r, c]


def _b64(a):
    import base64
    import numpy as np
    return base64.b64encode(np.ascontiguousarray(a, dtype="<f4").tobytes()).decode("ascii")


def _neutral_grade():
    """build() parameters that leave colour alone (only the vignette left)."""
    return dict(GRADE, **PARITY_OFF, wb_kelvin=None, slope=(1.0, 1.0, 1.0), offset=(0.0, 0.0, 0.0),
                power=(1.0, 1.0, 1.0), black_lift=0.0, saturation=1.0)


def bake_lut(out_json, tmp, g_range=LUT_G_RANGE, v_range=LUT_V_RANGE, n=LUT_SIZE):
    import numpy as np
    t = time.perf_counter()
    colour = dict(GRADE, **PARITY_OFF, vignette_ev=0.0)
    lg = _through_blender(_lattice(*g_range, n), tmp, "lut_grade", colour, out="exr")
    lut_g = np.log2(np.maximum(_unlattice(lg, n), 2.0 ** LUT_OUT_FLOOR))
    # the view LUT: a pass-through compositor (neutral grade, no vignette) and the hero view
    lv = _through_blender(_lattice(*v_range, n), tmp, "lut_view", None, out="png", ev=0.0)
    lut_v = _unlattice(lv, n)
    # the vignette gain at 1920 x 1080 (a constant 1 through the vignette alone), 20 x 20 box -> 96 x 54
    vg = _through_blender(np.ones((1080, 1920, 3)), tmp, "vignette", _neutral_grade(), out="exr")
    vmap = vg[..., 0].reshape(54, 20, 96, 20).mean(axis=(1, 3))
    rec = {
        "version": 1, "size": n, "blender": bpy.app.version_string, "look": LOOK,
        "view_transform": "AgX", "display": "sRGB",
        "grade_params": {k: GRADE[k] for k in ("wb_kelvin", "slope", "offset", "power", "black_lift",
                                               "saturation", "vignette_ev")},
        "chain": "x -> grade LUT (log2 shaper) -> exp2 -> x vignette -> (grain) -> x 2^EV -> view LUT -> display",
        "layout": "((b*size + g)*size + r)*3 + c, float32 LE, base64",
        "grade": {"min": g_range[0], "max": g_range[1], "out": "log2", "data": _b64(lut_g)},
        "view": {"min": v_range[0], "max": v_range[1], "out": "display", "data": _b64(lut_v)},
        "vignette": {"w": 96, "h": 54, "row0": "top", "ev": GRADE["vignette_ev"], "res": [1920, 1080],
                     "data": _b64(vmap)},
        "bake_s": round(time.perf_counter() - t, 2),
    }
    with open(out_json, "w") as f:
        json.dump(rec, f)
    print(f"[grade] LUT {n}^3 -> {out_json} ({rec['bake_s']} s)", flush=True)
    return rec


def _lut_apply(lut, x, lo, hi):
    """Trilinear lookup of an (n, n, n, 3) [b, g, r] LUT at the shaper of x (the engine's sampler)."""
    import numpy as np
    n = lut.shape[0]
    t = np.clip((np.log2(np.maximum(x, 2.0 ** lo)) - lo) / (hi - lo), 0.0, 1.0) * (n - 1)
    i0 = np.minimum(np.floor(t).astype(int), n - 2)
    f = t - i0
    out = np.zeros_like(x)
    for db in (0, 1):
        for dg in (0, 1):
            for dr in (0, 1):
                w = ((f[:, 2] if db else 1 - f[:, 2]) * (f[:, 1] if dg else 1 - f[:, 1])
                     * (f[:, 0] if dr else 1 - f[:, 0]))
                out += w[:, None] * lut[i0[:, 2] + db, i0[:, 1] + dg, i0[:, 0] + dr]
    return out


def verify_lut(rec, tmp, ev=-0.6, out_json=None, half=False):
    """Engine emulation (shaper -> trilinear LUT_G -> exp2 -> x 2^ev -> shaper -> trilinear LUT_V)
    against grade.py's real path (build(PARITY_OFF, vignette 0) -> AgX + LOOK, 16-bit PNG, no dither)."""
    import base64
    import numpy as np
    n = rec["size"]

    def dec(k):
        a = np.frombuffer(base64.b64decode(rec[k]["data"]), "<f4").reshape(n, n, n, 3).astype(np.float64)
        return a.astype(np.float16).astype(np.float64) if half else a
    lut_g, lut_v = dec("grade"), dec("view")
    rng = np.random.default_rng(16)
    ramp = np.geomspace(1e-4, 20.0, 400)
    sets = {
        "grey_ramp": np.repeat(ramp[:, None], 3, 1),
        "random": 10.0 ** rng.uniform(-4, np.log10(20.0), (500, 3)),
        "chart": np.array([[0.18] * 3, [0.5] * 3, [0.9] * 3]),
    }
    allx = np.concatenate(list(sets.values()))
    w = 64
    pad = (-len(allx)) % w
    img = np.concatenate([allx, np.ones((pad, 3)) * 0.18]).reshape(-1, w, 3)
    truth = _through_blender(img, tmp, "verify", dict(GRADE, **PARITY_OFF, vignette_ev=0.0), out="png",
                             ev=ev).reshape(-1, 3)[:len(allx)]
    g = 2.0 ** _lut_apply(lut_g, allx, rec["grade"]["min"], rec["grade"]["max"])
    eng = _lut_apply(lut_v, g * 2.0 ** ev, rec["view"]["min"], rec["view"]["max"])
    err = np.abs(eng - truth) * 255.0
    res, k = {}, 0
    for name, x in sets.items():
        e = err[k:k + len(x)]
        res[name] = {"max_255": round(float(e.max()), 3), "mean_255": round(float(e.mean()), 4),
                     "p99_255": round(float(np.percentile(e, 99)), 3)}
        if name == "chart":
            res[name]["values"] = {str(v): {"truth_255": [round(float(c), 2) for c in truth[k + i] * 255],
                                            "lut_255": [round(float(c), 2) for c in eng[k + i] * 255]}
                                   for i, v in enumerate((0.18, 0.5, 0.9))}
        if name == "grey_ramp":
            worst = int(np.argmax(e.max(axis=1)))
            res[name]["worst_at_linear"] = float(x[worst, 0])
        k += len(x)
    out = {"ev": ev, "half_float_lut": half, "size": n, "grade_range": [rec["grade"]["min"], rec["grade"]["max"]],
           "view_range": [rec["view"]["min"], rec["view"]["max"]], "error": res}
    if out_json:
        with open(out_json, "w") as f:
            json.dump(out, f, indent=1)
    print("[grade] LUT verify", json.dumps(res), flush=True)
    return out


def lut_main(a):
    import tempfile
    tmp = tempfile.mkdtemp(prefix="gradelut_")
    try:
        rec = bake_lut(a.lut, tmp, tuple(a.lut_grade_range), tuple(a.lut_view_range), a.lut_size)
        if a.lut_verify:
            v = verify_lut(rec, tmp, a.lut_verify_ev, a.lut_verify)
            v["half"] = verify_lut(rec, tmp, a.lut_verify_ev, None, half=True)["error"]
            with open(a.lut_verify, "w") as f:
                json.dump(v, f, indent=1)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv):
    ap = argparse.ArgumentParser(prog="grade.py")
    ap.add_argument("--exr", action="append")
    ap.add_argument("--out")
    ap.add_argument("--lut", help="T16: bake the grade as data (grade_lut.json; no --exr needed)")
    ap.add_argument("--lut-size", type=int, default=LUT_SIZE)
    ap.add_argument("--lut-grade-range", type=float, nargs=2, default=LUT_G_RANGE)
    ap.add_argument("--lut-view-range", type=float, nargs=2, default=LUT_V_RANGE)
    ap.add_argument("--lut-verify", help="also check the LUT path against Blender's, into this JSON")
    ap.add_argument("--lut-verify-ev", type=float, default=-0.6)
    ap.add_argument("--ev", type=float, action="append", default=None,
                    help="exposure per EXR (or one value for all); default from stage.json")
    ap.add_argument("--paint", type=float, default=0.6)
    ap.add_argument("--wb", type=float, default=None, help="white point in K (overrides GRADE wb_kelvin; 0 = off)")
    ap.add_argument("--suffix", default="", help="appended to the output names (grade A/Bs)")
    ap.add_argument("--parity", action="store_true",
                    help="engine-parity grade: no bloom, halation, dispersion or grain, no paint A/B "
                         "(exposure, white balance, CDL, saturation, vignette and AgX stay)")
    a = ap.parse_args(argv)
    if a.wb is not None:
        GRADE["wb_kelvin"] = a.wb or None
    if a.lut:
        return lut_main(a)
    if not a.exr or not a.out:
        ap.error("--exr and --out are required (or --lut)")
    if a.parity:
        GRADE.update(PARITY_OFF)
        a.paint = 0.0
    os.makedirs(a.out, exist_ok=True)
    meta = {}
    sj = os.path.join(a.out, "stage.json")
    if os.path.exists(sj):
        with open(sj) as f:
            meta = {s["shot"]: s for s in json.load(f).get("shots", [])}
    res = []
    for i, exr in enumerate(a.exr):
        name = os.path.splitext(os.path.basename(exr))[0]
        ev = (a.ev[i] if a.ev and len(a.ev) > 1 else a.ev[0]) if a.ev else meta.get(name, {}).get("exposure", 0.0)
        crop = name.endswith("_crop")        # a 100 % crop: no vignette, no paint A/B
        g = dict(GRADE, vignette_ev=0.0) if crop else GRADE
        s1 = grade(exr, os.path.join(a.out, f"{name}{a.suffix}.png"), 0.0, ev, g)
        s2 = (grade(exr, os.path.join(a.out, f"{name}{a.suffix}_paint.png"), a.paint, ev, g)
              if a.paint and not crop else None)
        res.append({"shot": name, "exposure": ev, "grade_s": s1, "paint_s": s2})
        print(f"[grade] {name}: {s1} s, paint {s2} s", flush=True)
    with open(os.path.join(a.out, "grade.json"), "w") as f:
        json.dump({"grade": GRADE, "look": LOOK, "paint": a.paint, "parity": a.parity, "shots": res}, f, indent=1)


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
