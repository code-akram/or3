"""Suit surfaces: atlas packing of the metric panel UVs, height maps drawn by
script (weave, seams, topstitching, buttonholes, creases), their tangent-space
normal maps, and the glTF-friendly materials (bench/m1/suit.md).

Each built garment carries a per-face "panel" tag and metric UVs (u, v in
metres, one rectangle per panel), plus a list of marks the builder registered
in that panel's UV space:

    ("seam", [(u, v), ...])        a pressed seam: a shallow groove with a
                                   stitch line either side
    ("topstitch", [(u, v), ...])   one line of visible stitches, pick-stitch pitch
    ("edge", [(u, v), ...])        a finished edge: rolled lip + topstitch inside it
    ("crease", [(u, v), ...])      a pressed crease ridge
    ("buttonhole", (u, v), length) a keyhole bar-tack
    ("welt", [(u, v), ...])        a raised welt strip (pocket mouths)

apply() packs the panels of a material group into one atlas (uniform texel
density), rewrites the UVs, draws the height map with numpy, converts it to a
normal map and wires it into the material. Images are packed into the .blend
so the glTF exporter embeds them.
"""

import json
import math

import bmesh
import bpy
import numpy as np

from . import suit_leather

# weave period in metres and amplitude (height units are metres before the
# normal-map slope scale)
WEAVE = {
    # periods are a little over 2 px at the atlas density, below that the twill aliases
    "wool": {"period_m": 0.0019, "amp": 0.00006, "noise": 0.00003, "twill": True},
    "shirt": {"period_m": 0.0012, "amp": 0.00003, "noise": 0.000015, "twill": False},
    "silk": {"period_m": 0.0014, "amp": 0.00006, "noise": 0.00001, "twill": True, "angle": 0.6},
    "leather": {"period_m": 0.0, "amp": 0.0, "noise": 0.00004, "twill": False},
    "sole": {"period_m": 0.0, "amp": 0.0, "noise": 0.00008, "twill": False},
}


# --- materials -----------------------------------------------------------------------------

def material(name, albedo, rough, sheen):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = (albedo, albedo, albedo, 1.0)
    bsdf.inputs["Roughness"].default_value = rough
    if "Sheen Weight" in bsdf.inputs:
        bsdf.inputs["Sheen Weight"].default_value = 1.0 if sheen else 0.0
        bsdf.inputs["Sheen Tint"].default_value = (sheen, sheen, sheen, 1.0)
        bsdf.inputs["Sheen Roughness"].default_value = 0.5
    mat.diffuse_color = (albedo, albedo, albedo, 1.0)
    return mat


def attach_normal_map(mat, image, strength=1.0):
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = image
    tex.interpolation = "Linear"
    image.colorspace_settings.name = "Non-Color"
    nm = nt.nodes.new("ShaderNodeNormalMap")
    nm.space = "TANGENT"
    nm.inputs["Strength"].default_value = strength
    nt.links.new(tex.outputs["Color"], nm.inputs["Color"])
    nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])


# --- panels and packing --------------------------------------------------------------------

def panels_of(obj):
    """{(panel tag): (umin, vmin, umax, vmax)} from the object's UVs and its
    "panel" face attribute (0 for untagged faces)."""
    me = obj.data
    uv = me.uv_layers.active
    if uv is None:
        return {}
    tag = me.attributes.get("panel")
    out = {}
    for p in me.polygons:
        t = tag.data[p.index].value if tag else 0
        for li in p.loop_indices:
            u, v = uv.data[li].uv
            b = out.get(t)
            if b is None:
                out[t] = [u, v, u, v]
            else:
                b[0], b[1], b[2], b[3] = min(b[0], u), min(b[1], v), max(b[2], u), max(b[3], v)
    return out


def shelf_pack(rects, pad):
    """rects: {key: (w, h)} in metres. Returns (side, {key: (x, y)}): the
    smallest square side found that fits a shelf packing."""
    items = sorted(rects.items(), key=lambda kv: -kv[1][1])
    area = sum((w + pad) * (h + pad) for _, (w, h) in items)
    side = math.sqrt(area) * 1.05
    for _ in range(40):
        pos, x, y, shelf_h, ok = {}, pad, pad, 0.0, True
        for key, (w, h) in items:
            if x + w + pad > side:
                x, y, shelf_h = pad, y + shelf_h + pad, 0.0
            if y + h + pad > side or w + 2 * pad > side:
                ok = False
                break
            pos[key] = (x, y)
            x += w + pad
            shelf_h = max(shelf_h, h)
        if ok:
            return side, pos
        side *= 1.04
    raise RuntimeError("atlas packing failed")


def pack_group(objs, px, pad_m=0.012):
    """Pack every (object, panel) rectangle of `objs` into one square atlas and
    rewrite the UVs. Returns the layout: {(obj name, tag): dict(x0, y0, w, h,
    umin, vmin)} in metres plus the atlas side in metres."""
    rects, bounds = {}, {}
    for o in objs:
        for t, (u0, v0, u1, v1) in panels_of(o).items():
            rects[(o.name, t)] = (max(u1 - u0, 1e-4), max(v1 - v0, 1e-4))
            bounds[(o.name, t)] = (u0, v0)
    side, pos = shelf_pack(rects, pad_m)
    layout = {}
    for key, (x, y) in pos.items():
        w, h = rects[key]
        u0, v0 = bounds[key]
        layout[key] = {"x0": x, "y0": y, "w": w, "h": h, "umin": u0, "vmin": v0}
    for o in objs:
        me = o.data
        uv = me.uv_layers.active
        tag = me.attributes.get("panel")
        for p in me.polygons:
            t = tag.data[p.index].value if tag else 0
            L = layout[(o.name, t)]
            for li in p.loop_indices:
                u, v = uv.data[li].uv
                uv.data[li].uv = ((L["x0"] + u - L["umin"]) / side, (L["y0"] + v - L["vmin"]) / side)
    return side, layout


# --- height-map drawing --------------------------------------------------------------------

class Height:
    def __init__(self, px, side_m, seed=0):
        self.px, self.side = px, side_m
        self.ppm = px / side_m          # pixels per metre
        self.h = np.zeros((px, px), np.float32)
        self.rng = np.random.default_rng(seed)

    def to_px(self, u, v):
        return u * self.ppm, v * self.ppm

    def weave(self, w):
        px = self.px
        if w["amp"] and w["period_m"]:
            f = self.side / w["period_m"]         # periods across the atlas
            y, x = np.mgrid[0:px, 0:px].astype(np.float32) / px
            if w.get("twill"):
                a = w.get("angle", 0.0)
                xr = x * math.cos(a) - y * math.sin(a)
                yr = x * math.sin(a) + y * math.cos(a)
                # 2/1 twill: diagonal ribs from the warp floats
                ribs = np.sin(2 * np.pi * f * (xr + yr) / 1.4142)
                weft = np.sin(2 * np.pi * f * xr) * np.sin(2 * np.pi * f * yr)
                pat = 0.6 * ribs + 0.4 * weft
            else:
                pat = np.sin(2 * np.pi * f * x) * np.sin(2 * np.pi * f * y)   # plain weave
            self.h += (w["amp"] * pat).astype(np.float32)
        if w.get("noise"):
            # two octaves of smoothed grain (slubs and fibre), no blocky steps
            for cell, amp in ((3, 0.6), (8, 0.4)):
                n = self.rng.normal(0.0, 1.0, (px // cell + 2, px // cell + 2)).astype(np.float32)
                n = np.kron(n, np.ones((cell, cell), np.float32))[:px, :px]
                for _ in range(2):  # box blur
                    n = (n + np.roll(n, 1, 0) + np.roll(n, -1, 0) + np.roll(n, 1, 1) + np.roll(n, -1, 1)) / 5
                self.h += (w["noise"] * amp * n).astype(np.float32)

    def _window(self, pts, r):
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        x0, x1 = int(max(0, min(xs) - r)), int(min(self.px - 1, max(xs) + r)) + 1
        y0, y1 = int(max(0, min(ys) - r)), int(min(self.px - 1, max(ys) + r)) + 1
        if x1 <= x0 or y1 <= y0:
            return None
        Y, X = np.mgrid[y0:y1, x0:x1].astype(np.float32)
        return (x0, x1, y0, y1), X, Y

    def line(self, pts_m, profile, r_m, offset_m=0.0, dash=None):
        """Add profile(d, t) along a polyline (metres), where d is the signed
        distance across the line (px), t the arc parameter (px). dash =
        (pitch_m, duty) limits it to dashes."""
        pts = [self.to_px(u, v) for u, v in pts_m]
        r = r_m * self.ppm
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            L = math.hypot(bx - ax, by - ay)
            if L < 1e-6:
                continue
            tx, ty = (bx - ax) / L, (by - ay) / L
            nx, ny = -ty, tx
            ox, oy = nx * offset_m * self.ppm, ny * offset_m * self.ppm
            win = self._window([(ax + ox, ay + oy), (bx + ox, by + oy)], r + 2)
            if win is None:
                continue
            (x0, x1, y0, y1), X, Y = win
            dx, dy = X - (ax + ox), Y - (ay + oy)
            t = dx * tx + dy * ty
            d = dx * nx + dy * ny
            inside = (t >= 0) & (t <= L)
            # round caps are unnecessary: segments abut
            val = profile(d, t) * inside
            if dash:
                pitch = dash[0] * self.ppm
                val = val * (((t / pitch) % 1.0) < dash[1])
            self.h[y0:y1, x0:x1] += val.astype(np.float32)

    # profiles (heights in metres)
    def groove(self, depth, width_m):
        w = width_m * self.ppm
        return lambda d, t: -depth * np.exp(-(d / (0.5 * w)) ** 2)

    def ridge(self, height, width_m):
        w = width_m * self.ppm
        return lambda d, t: height * np.exp(-(d / (0.5 * w)) ** 2)

    def stitch(self, pts, pitch_m=0.0045, offset_m=0.0, thread_m=0.0007, height=0.00025):
        """A line of pick stitches: short raised dashes."""
        self.line(pts, self.ridge(height, thread_m * 2.2), thread_m * 1.5, offset_m,
                  dash=(pitch_m, 0.45))

    def seam(self, pts, depth=0.0004, width_m=0.0016, stitch=True):
        self.line(pts, self.groove(depth, width_m), width_m * 1.5)
        if stitch:
            self.stitch(pts, offset_m=0.0012)
            self.stitch(pts, offset_m=-0.0012)

    def edge(self, pts, inside_sign=1.0, lip_m=0.0012, height=0.0005, stitch_in_m=0.005):
        """A finished edge: the fabric rolls over (ridge at the edge) and a
        topstitch runs stitch_in_m inside it."""
        self.line(pts, self.ridge(height, lip_m * 2), lip_m * 2, offset_m=inside_sign * lip_m * 0.5)
        self.stitch(pts, pitch_m=0.006, offset_m=inside_sign * stitch_in_m, height=0.00035)

    def crease(self, pts, height=0.0009, width_m=0.004):
        self.line(pts, self.ridge(height, width_m), width_m * 1.5)

    def welt(self, pts, height=0.0009, width_m=0.012):
        self.line(pts, self.ridge(height, width_m), width_m)
        self.stitch(pts, offset_m=width_m * 0.5 + 0.001, height=0.0003)
        self.stitch(pts, offset_m=-width_m * 0.5 - 0.001, height=0.0003)

    def buttonhole(self, at, length_m, angle=0.0, width_m=0.0035):
        """A bar-tacked keyhole: dense stitches around a slit."""
        u, v = at
        c, s = math.cos(angle), math.sin(angle)
        a = (u - c * length_m / 2, v - s * length_m / 2)
        b = (u + c * length_m / 2, v + s * length_m / 2)
        self.line([a, b], self.groove(0.0006, 0.0012), 0.002)
        for sign in (1, -1):
            self.stitch([a, b], pitch_m=0.0012, offset_m=sign * width_m * 0.5, height=0.00045,
                        thread_m=0.0006)
        # keyhole eye at the edge end
        self.spot(a, 0.0016, -0.0005)

    def spot(self, at, r_m, height):
        x, y = self.to_px(*at)
        r = r_m * self.ppm
        win = self._window([(x, y)], r + 2)
        if win is None:
            return
        (x0, x1, y0, y1), X, Y = win
        d2 = (X - x) ** 2 + (Y - y) ** 2
        self.h[y0:y1, x0:x1] += (height * np.exp(-d2 / (0.5 * r) ** 2)).astype(np.float32)

    def normal_image(self, name, slope=1.0):
        """Tangent-space normal map from the height field. The height is in
        metres and the pixel pitch is 1/ppm, so dz/dx is dimensionless; slope
        scales it (fabric detail reads better slightly exaggerated)."""
        h = self.h
        dpx = 1.0 / self.ppm
        gx = (np.roll(h, -1, axis=1) - np.roll(h, 1, axis=1)) / (2 * dpx) * slope
        gy = (np.roll(h, -1, axis=0) - np.roll(h, 1, axis=0)) / (2 * dpx) * slope
        nz = np.ones_like(h)
        n = np.stack([-gx, -gy, nz], axis=-1)
        n /= np.linalg.norm(n, axis=-1, keepdims=True)
        rgba = np.empty((self.px, self.px, 4), np.float32)
        rgba[..., :3] = n * 0.5 + 0.5
        rgba[..., 3] = 1.0
        img = bpy.data.images.new(name, self.px, self.px, alpha=False, float_buffer=False)
        img.colorspace_settings.name = "Non-Color"
        img.pixels.foreach_set(rgba.ravel())
        img.pack()
        return img


# --- marks ---------------------------------------------------------------------------------

def draw_marks(H, layout, marks, side):
    """marks: {(obj name, tag): [(kind, data...)]} in panel-metric UVs."""
    for key, lst in marks.items():
        L = layout.get(key)
        if L is None:
            continue

        def T(uv):
            return (L["x0"] + uv[0] - L["umin"], L["y0"] + uv[1] - L["vmin"])

        for mark in lst:
            kind, data = mark[0], mark[1]
            if kind == "seam":
                H.seam([T(p) for p in data])
            elif kind == "topstitch":
                H.stitch([T(p) for p in data], **(mark[2] if len(mark) > 2 else {}))
            elif kind == "edge":
                H.edge([T(p) for p in data], **(mark[2] if len(mark) > 2 else {}))
            elif kind == "crease":
                H.crease([T(p) for p in data])
            elif kind == "welt":
                H.welt([T(p) for p in data])
            elif kind == "buttonhole":
                H.buttonhole(T(data), mark[2], mark[3] if len(mark) > 3 else 0.0)


def strip_panel_attr(objs):
    for o in objs:
        a = o.data.attributes.get("panel")
        if a:
            o.data.attributes.remove(a)


def apply(o, parts, mats, marks):
    """parts: {name: object}; marks: {object name: {tag: [marks]}}. Groups:
    wool_a (jacket), wool_b (waistcoat + trousers), shirt, silk (tie)."""
    T = o["textures"]
    groups = [("wool_a", [parts["jacket"]], T["wool_px"], "wool", mats["wool"]),
              ("wool_b", [parts["waistcoat"], parts["trousers"]], T["wool_px"], "wool", None),
              ("shirt", [parts["shirt"]], T["shirt_px"], "shirt", mats["shirt"]),
              ("silk", [parts["tie"]], T["tie_px"], "silk", mats["silk"]),
              ("leather", [parts.get("shoes")], T["shoe_px"], "leather", mats["leather"])]
    out = {}
    for gname, objs, px, weave, mat in groups:
        objs = [x for x in objs if x is not None]
        if not objs:
            continue
        side, layout = pack_group(objs, px)
        H = Height(px, side, seed=T["seed"] + len(out))
        H.weave(WEAVE[weave])
        flat = {}
        for ob in objs:
            for tag, lst in marks.get(ob.name, {}).items():
                flat[(ob.name, tag)] = lst
        leather = suit_leather.Surfaces(H, layout, flat, side, o) if gname == "leather" else None
        draw_marks(H, layout, flat, side)
        img = H.normal_image(f"suit_{gname}_normal", slope=T["slope"])
        if mat is None:
            base = mats["wool"]
            mat = base.copy()
            mat.name = f"suit_{gname}"
        attach_normal_map(mat, img, strength=1.0)
        for ob in objs:
            keep_second = len(ob.data.materials) > 1   # shoes: upper + sole
            second = ob.data.materials[1] if keep_second else None
            ob.data.materials[0] = mat
            if keep_second:
                attach_normal_map(second, img, strength=1.0)
            else:
                for p in ob.data.polygons:
                    p.material_index = 0
        if leather:   # shoes: albedo, roughness and clear-coat maps (suit_leather.py)
            out["leather_maps"] = leather.wire(mat, objs[0].data.materials[1])
        strip_panel_attr(objs)
        out[gname] = {"px": px, "atlas_side_m": round(side, 4), "panels": len(layout),
                      "mm_per_px": round(1000 * side / px, 3), "marks": sum(len(v) for v in flat.values())}
    return out
