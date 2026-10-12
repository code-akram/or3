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

LOOK = "AgX - Medium High Contrast"
GRADE = {
    "bloom_threshold": 1.0, "bloom_strength": 0.35, "bloom_size": 0.55,
    "halation_threshold": 2.0, "halation_strength": 0.12, "halation_tint": (1.0, 0.32, 0.12),
    "dispersion": 0.008,
    "slope": (1.03, 1.0, 0.95), "offset": (-0.0004, 0.0003, 0.0009), "power": (1.0, 1.0, 1.0),
    "black_lift": 0.0011,
    "vignette_ev": -0.3,
    "grain": 0.02,
    "saturation": 1.04,
    "paint_size": 5, "paint_sharpness": 0.4, "paint_eccentricity": 1.2, "paint_uniformity": 3,
}


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

    bloom = _new(nt, "CompositorNodeGlare")
    _menu(bloom, "Type", "Bloom")
    _menu(bloom, "Quality", "High")
    _set(bloom, "Threshold", g["bloom_threshold"])
    _set(bloom, "Strength", g["bloom_strength"])
    _set(bloom, "Size", g["bloom_size"])
    nt.links.new(x, bloom.inputs["Image"])
    x = bloom.outputs["Image"]

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


def grade(exr_path, out_png, paint=0.0, ev=0.0):
    sc = build(exr_path, paint)
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


def main(argv):
    ap = argparse.ArgumentParser(prog="grade.py")
    ap.add_argument("--exr", action="append", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ev", type=float, action="append", default=None,
                    help="exposure per EXR (or one value for all); default from stage.json")
    ap.add_argument("--paint", type=float, default=0.6)
    a = ap.parse_args(argv)
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
        s1 = grade(exr, os.path.join(a.out, f"{name}.png"), 0.0, ev)
        s2 = grade(exr, os.path.join(a.out, f"{name}_paint.png"), a.paint, ev) if a.paint else None
        res.append({"shot": name, "exposure": ev, "grade_s": s1, "paint_s": s2})
        print(f"[grade] {name}: {s1} s, paint {s2} s", flush=True)
    with open(os.path.join(a.out, "grade.json"), "w") as f:
        json.dump({"grade": GRADE, "look": LOOK, "paint": a.paint, "shots": res}, f, indent=1)


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
