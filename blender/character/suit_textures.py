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
    ("pick", [(u, v), ...], kw)    hand pick stitching: a dimple every pitch_m
    ("ridge", [(u, v), ...], kw)   a raised line, kw height and width_m
    ("welt", [(u, v), ...])        a raised welt strip (pocket mouths)
    ("jet", [(u, v), (u, v)])      a jetted pocket: two narrow lips either side
                                   of a slit, bar-tacked at both ends

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
# normal-map slope scale). "detail": True keeps the periodic weave OUT of the
# baked atlas (it sat at ~2 px per period there and aliased into diagonal
# moire bands in the engine, checkpoint-1 §1.3 #3); the runtime adds it from a
# small tiled detail normal (suit_twill_detail.png, mipmapped, faded by
# fwidth) at the same period and amplitude. The noise (slubs) stays baked.
# The shirt's plain weave stays baked (mostly hidden; no second tile yet).
WEAVE = {
    "wool": {"period_m": 0.0019, "amp": 0.000025, "noise": 0.00003, "twill": True, "detail": True},   # faint: the hero adds the real 0.6 mm twill (suit_hero)
    "shirt": {"period_m": 0.0012, "amp": 0.00003, "noise": 0.000015, "twill": False},
    "silk": {"period_m": 0.0014, "amp": 0.00006, "noise": 0.00001, "twill": True, "angle": 0.6, "detail": True},
    "leather": {"period_m": 0.0, "amp": 0.0, "noise": 0.00004, "twill": False},
    "sole": {"period_m": 0.0, "amp": 0.0, "noise": 0.00008, "twill": False},
}


# --- materials -----------------------------------------------------------------------------

def material(name, albedo, rough, sheen=0.0, sheen_rough=0.5, sheen_tint=(1.0, 1.0, 1.0),
             spec=0.5, coat=0.0, coat_rough=0.03, aniso=0.0, aniso_rot=0.0, sss=0.0, **_):
    """A Principled material that survives the glTF round trip: albedo (grey
    or rgb), roughness, sheen (the exporter writes Sheen Tint as
    sheenColorFactor and ignores Sheen Weight, so strength x tint goes in the
    tint), Specular IOR Level (KHR_materials_specular: factor = 2 x level),
    coat (KHR_materials_clearcoat), anisotropy along the UV tangent
    (KHR_materials_anisotropy). sss is Cycles-only (subsurface, not exported)."""
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    rgb = tuple(albedo) if isinstance(albedo, (list, tuple)) else (albedo, albedo, albedo)
    bsdf.inputs["Base Color"].default_value = rgb[:3] + (1.0,)
    bsdf.inputs["Roughness"].default_value = rough
    if "Sheen Weight" in bsdf.inputs:
        bsdf.inputs["Sheen Weight"].default_value = 1.0 if sheen else 0.0
        bsdf.inputs["Sheen Tint"].default_value = tuple(sheen * c for c in sheen_tint) + (1.0,)
        bsdf.inputs["Sheen Roughness"].default_value = sheen_rough
    bsdf.inputs["Specular IOR Level"].default_value = spec
    if coat:
        bsdf.inputs["Coat Weight"].default_value = coat
        bsdf.inputs["Coat Roughness"].default_value = coat_rough
    if aniso:
        bsdf.inputs["Anisotropic"].default_value = aniso
        bsdf.inputs["Anisotropic Rotation"].default_value = aniso_rot
        tg = nt.nodes.new("ShaderNodeTangent")
        tg.direction_type = "UV_MAP"
        nt.links.new(tg.outputs["Tangent"], bsdf.inputs["Tangent"])
    if sss:
        bsdf.inputs["Subsurface Weight"].default_value = sss
        bsdf.inputs["Subsurface Radius"].default_value = (1.0, 0.9, 0.8)
        bsdf.inputs["Subsurface Scale"].default_value = 0.002
    mat.diffuse_color = rgb[:3] + (1.0,)
    return mat


def gltf_output_group():
    """The exporter's "glTF Material Output" group (its Occlusion input becomes
    the glTF occlusion texture)."""
    name = "glTF Material Output"
    g = bpy.data.node_groups.get(name)
    if g is None:
        g = bpy.data.node_groups.new(name, "ShaderNodeTree")
        g.interface.new_socket("Occlusion", in_out="INPUT", socket_type="NodeSocketFloat")
        g.nodes.new("NodeGroupInput")
    return g


def attach_surface(mat, albedo_img, orm_img):
    """Base colour from an sRGB albedo map; roughness (G), metallic (B) and
    occlusion (R) from one linear ORM map."""
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    if albedo_img is not None:
        ta = nt.nodes.new("ShaderNodeTexImage")
        ta.image = albedo_img
        nt.links.new(ta.outputs["Color"], bsdf.inputs["Base Color"])
    if orm_img is not None:
        to = nt.nodes.new("ShaderNodeTexImage")
        to.image = orm_img
        orm_img.colorspace_settings.name = "Non-Color"
        sep = nt.nodes.new("ShaderNodeSeparateColor")
        nt.links.new(to.outputs["Color"], sep.inputs[0])
        nt.links.new(sep.outputs["Green"], bsdf.inputs["Roughness"])
        nt.links.new(sep.outputs["Blue"], bsdf.inputs["Metallic"])
        grp = nt.nodes.new("ShaderNodeGroup")
        grp.node_tree = gltf_output_group()
        nt.links.new(sep.outputs["Red"], grp.inputs["Occlusion"])


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
        if w["amp"] and w["period_m"] and not w.get("detail"):
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

    def pick(self, pts, pitch_m=0.006, r_m=0.0011, depth=0.00022):
        """Pick stitching (hand, through the edge): a small dimple where each stitch pulls the
        cloth in, one every pitch_m along the line."""
        P = np.asarray(pts, float)
        if len(P) < 2:
            return
        s = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))]
        for t in np.arange(0.5 * pitch_m, s[-1], pitch_m):
            q = (np.interp(t, s, P[:, 0]), np.interp(t, s, P[:, 1]))
            self.spot(q, r_m, -depth)
            self.spot(q, 0.45 * r_m, 0.5 * depth)

    def crease(self, pts, height=0.0009, width_m=0.004):
        self.line(pts, self.ridge(height, width_m), width_m * 1.5)

    def jet(self, pts, lip_m=0.005, height=0.0007):
        """Jetted pocket: a slit (groove) between two narrow lips, bar tacks at the ends."""
        self.line(pts, self.groove(0.0008, 0.0012), 0.002)
        for sign in (1, -1):
            self.line(pts, self.ridge(height, lip_m), lip_m, offset_m=sign * 0.5 * lip_m)
        self.stitch(pts, offset_m=lip_m + 0.001, height=0.0003)
        self.stitch(pts, offset_m=-lip_m - 0.001, height=0.0003)
        for end in (pts[0], pts[-1]):
            self.spot(end, 0.0015, 0.0004)

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


# --- runtime weave detail ------------------------------------------------------------------

DETAIL_TILE = "suit_twill_detail"
DETAIL_PX = 256
DETAIL_PERIODS = 8          # rib periods across the tile (32 px each at 256)
DETAIL_REF_AMP = 0.000025   # the tile's baked amplitude (wool); other weaves scale the XY slope
DETAIL_REF_PERIOD = 0.0019  # the tile's metric period (wool)


def twill_tile(slope=1.0, px=DETAIL_PX, n=DETAIL_PERIODS):
    """Tileable 2/1 twill (Height.weave's twill at angle 0) as a tangent-space
    normal image. Height.weave's ribs, sin(2 pi f (x + y) / sqrt 2), repeat
    every sqrt(2) * period along x; here n of them span the tile, so the tile is
    n * sqrt(2) * period wide. The weft term is rounded to integer periods so
    the tile wraps."""
    y, x = np.mgrid[0:px, 0:px].astype(np.float64) / px
    ribs = np.sin(2 * np.pi * n * (x + y))
    k = round(n * math.sqrt(2))
    weft = np.sin(2 * np.pi * k * x) * np.sin(2 * np.pi * k * y)
    h = DETAIL_REF_AMP * (0.6 * ribs + 0.4 * weft)
    tile_m = n * math.sqrt(2) * DETAIL_REF_PERIOD
    dpx = tile_m / px
    gx = (np.roll(h, -1, axis=1) - np.roll(h, 1, axis=1)) / (2 * dpx) * slope
    gy = (np.roll(h, -1, axis=0) - np.roll(h, 1, axis=0)) / (2 * dpx) * slope
    n3 = np.stack([-gx, -gy, np.ones_like(h)], axis=-1)
    n3 /= np.linalg.norm(n3, axis=-1, keepdims=True)
    rgba = np.empty((px, px, 4), np.float32)
    rgba[..., :3] = n3 * 0.5 + 0.5
    rgba[..., 3] = 1.0
    img = bpy.data.images.get(DETAIL_TILE) or bpy.data.images.new(DETAIL_TILE, px, px, alpha=False)
    img.use_fake_user = True  # no node uses it in the build, and the hero .blend needs it (cycles_weave)
    img.colorspace_settings.name = "Non-Color"
    img.pixels.foreach_set(rgba.ravel())
    img.pack()
    return img, float(np.abs(gx).max())


def detail_record(mat, side_m, w):
    """Runtime weave detail for one material (the viewer reads it from
    suit_detail.json, which export.write_sidecars puts next to the GLB): tile
    repeats per atlas UV unit, rotation, slope gain vs the tile."""
    tile_m = DETAIL_PERIODS * math.sqrt(2) * w["period_m"]
    rec = {"tile": DETAIL_TILE + ".png", "atlas_side_m": round(side_m, 6), "period_m": w["period_m"],
           "tile_m": round(tile_m, 6), "repeat": round(side_m / tile_m, 4), "angle_rad": w.get("angle", 0.0),
           "strength": round(w["amp"] / DETAIL_REF_AMP * DETAIL_REF_PERIOD / w["period_m"], 4)}
    mat["suit_detail"] = json.dumps(rec)
    return rec


def cycles_weave(records=None, tile=None, gain=1.0):
    """Render-time weave for Cycles (lookdev_render, hero/stage): the twill left the baked atlas for the
    engine's tiled detail normal, so Blender needs the same detail or its renders lose the weave. Adds,
    per material with a detail record, the engine's arithmetic (web ClothMaterial) in front of the
    existing Normal Map node: uv_tile = rotate(gltf_uv * repeat, angle); d = tile * 2 - 1 rotated back;
    n = normalize(base.xy + d.xy * strength, base.z). Never call it before a glTF export (the exporter
    needs Image -> Normal Map). records: {material: suit_detail record}, default each material's
    "suit_detail" property; tile: the tile image (default the packed DETAIL_TILE). Returns the names done."""
    if records is None:
        records = {m.name: json.loads(m["suit_detail"]) for m in bpy.data.materials if "suit_detail" in m}
    tile = tile or bpy.data.images.get(DETAIL_TILE)
    if not records or tile is None:
        return []
    tile.colorspace_settings.name = "Non-Color"
    done = []
    for name, rec in sorted(records.items()):
        mat = bpy.data.materials.get(name)
        if mat is None or not mat.use_nodes or mat.get("cycles_weave"):
            continue
        nt = mat.node_tree
        bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
        lk = bsdf and bsdf.inputs["Normal"].links
        nm = lk[0].from_node if lk else None
        while nm is not None and nm.type == "BUMP":  # suit_hero's fine twill bumps over the normal map
            lk = nm.inputs["Normal"].links
            nm = lk[0].from_node if lk else None
        if nm is None or nm.type != "NORMAL_MAP" or not nm.inputs["Color"].links:
            continue
        base = nm.inputs["Color"].links[0].from_socket
        uv_src = base.node.inputs["Vector"].links[0].from_socket if (
            base.node.type == "TEX_IMAGE" and base.node.inputs["Vector"].links) else None

        def vm(op, a, b=None, c=None, scale=None):
            n = nt.nodes.new("ShaderNodeVectorMath")
            n.operation = op
            for i, x in enumerate((a, b, c)):
                if x is None:
                    continue
                if isinstance(x, (tuple, list)):
                    n.inputs[i].default_value = x
                else:
                    nt.links.new(x, n.inputs[i])
            if scale is not None:
                n.inputs["Scale"].default_value = scale
            return n.outputs[0]

        def rot(v, ang):
            n = nt.nodes.new("ShaderNodeVectorRotate")
            n.rotation_type = "Z_AXIS"
            n.inputs["Angle"].default_value = ang
            n.inputs["Center"].default_value = (0.0, 0.0, 0.0)
            nt.links.new(v, n.inputs["Vector"])
            return n.outputs[0]

        if uv_src is None:
            uvn = nt.nodes.new("ShaderNodeUVMap")
            uv_src = uvn.outputs["UV"]
        ang, k = float(rec.get("angle_rad", 0.0)), float(rec["strength"]) * gain
        uvg = vm("MULTIPLY_ADD", uv_src, (1.0, -1.0, 0.0), (0.0, 1.0, 0.0))        # Blender v -> glTF v
        uvt = rot(vm("SCALE", uvg, scale=float(rec["repeat"])), ang)
        st = vm("MULTIPLY_ADD", uvt, (1.0, -1.0, 0.0), (0.0, 1.0, 0.0))            # back to Blender v
        tx = nt.nodes.new("ShaderNodeTexImage")
        tx.image = tile
        tx.extension = "REPEAT"
        tx.interpolation = "Linear"
        nt.links.new(st, tx.inputs["Vector"])
        d = vm("MULTIPLY_ADD", tx.outputs["Color"], (2.0, 2.0, 2.0), (-1.0, -1.0, -1.0))
        dxy = vm("MULTIPLY", rot(d, -ang), (k, k, 0.0))
        b = vm("MULTIPLY_ADD", base, (2.0, 2.0, 2.0), (-1.0, -1.0, -1.0))
        n = vm("NORMALIZE", vm("ADD", b, dxy))
        nt.links.new(vm("MULTIPLY_ADD", n, (0.5, 0.5, 0.5), (0.5, 0.5, 0.5)), nm.inputs["Color"])
        mat["cycles_weave"] = 1
        done.append(name)
    return done


def cycles_weave_blend(blend_path, gain=1.0):
    """cycles_weave for a kept character.blend: the material records, the tile from the .blend or (builds
    before the tile had a fake user, so the orphan image was not saved) the PNG sidecar beside it."""
    import os
    tile = bpy.data.images.get(DETAIL_TILE)
    png = os.path.join(os.path.dirname(os.path.abspath(blend_path)), DETAIL_TILE + ".png")
    if tile is None and os.path.exists(png):
        tile = bpy.data.images.load(png, check_existing=True)
    return cycles_weave(None, tile, gain)


def cycles_weave_sidecar(glb_path, gain=1.0):
    """cycles_weave for a GLB import: suit_detail.json and its tile next to the GLB (export.write_sidecars)."""
    import os
    d = os.path.dirname(os.path.abspath(glb_path))
    jp = os.path.join(d, "suit_detail.json")
    if not os.path.exists(jp):
        return []
    with open(jp) as f:
        recs = json.load(f).get("materials", {})
    tiles = {r["tile"] for r in recs.values()}
    if len(tiles) != 1 or not os.path.exists(os.path.join(d, next(iter(tiles)))):
        return []
    img = bpy.data.images.load(os.path.join(d, next(iter(tiles))), check_existing=True)
    return cycles_weave(recs, img, gain)


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
                H.seam([T(p) for p in data], **(mark[2] if len(mark) > 2 else {}))
            elif kind == "pick":
                H.pick([T(p) for p in data], **(mark[2] if len(mark) > 2 else {}))
            elif kind == "ridge":
                H.line([T(p) for p in data], H.ridge(**mark[2]), mark[2]["width_m"] * 1.5)
            elif kind == "topstitch":
                H.stitch([T(p) for p in data], **(mark[2] if len(mark) > 2 else {}))
            elif kind == "edge":
                H.edge([T(p) for p in data], **(mark[2] if len(mark) > 2 else {}))
            elif kind == "crease":
                H.crease([T(p) for p in data])
            elif kind == "jet":
                H.jet([T(p) for p in data])
            elif kind == "welt":
                H.welt([T(p) for p in data])
            elif kind == "buttonhole":
                H.buttonhole(T(data), mark[2], mark[3] if len(mark) > 3 else 0.0)


def strip_panel_attr(objs):
    for o in objs:
        a = o.data.attributes.get("panel")
        if a:
            o.data.attributes.remove(a)


def add_folds(H, objs, folds, layout, side, gain=1.0):
    """Rasterise each object's cloth-sim fold height (suit_drape.Fold) into the
    height map: half resolution (folds are 2-4 cm long), bilinear-upsampled."""
    from . import suit_drape
    out = {}
    px2 = H.px // 2
    acc = np.zeros((px2, px2), np.float64)
    for ob in objs:
        f = folds.get(ob.name) if folds else None
        if f is None:
            continue
        uv = suit_drape.fold_uvs(f, layout, side)
        img, cover = suit_drape.rasterise(f.ob.data, uv, f.h.astype(np.float64), px2)
        acc += img
        out[ob.name] = {"cover_px": int(cover.sum()), "max_mm": round(float(np.abs(img).max()) * 1000, 2)}
    if out:
        up = np.kron(acc, np.ones((2, 2)))
        # smooth the 2x blocks (a cheap bilinear)
        up = (up + np.roll(up, 1, 0) + np.roll(up, 1, 1) + np.roll(np.roll(up, 1, 0), 1, 1)) / 4.0
        H.h += (gain * up[:H.px, :H.px]).astype(np.float32)
        H.folds = up[:H.px, :H.px].astype(np.float32)
    return out


def _blur(a, r):
    """Approximate gaussian: three box passes of radius r (px), wrap-around."""
    r = max(1, int(round(r)))
    for _ in range(3):
        c = np.cumsum(np.pad(a, ((0, 0), (r + 1, r)), mode="wrap"), axis=1)
        a = (c[:, 2 * r + 1:] - c[:, :-2 * r - 1]) / (2 * r + 1)
        c = np.cumsum(np.pad(a, ((r + 1, r), (0, 0)), mode="wrap"), axis=0)
        a = (c[2 * r + 1:, :] - c[:-2 * r - 1, :]) / (2 * r + 1)
    return a


def _down2(a):
    return 0.25 * (a[0::2, 0::2] + a[1::2, 0::2] + a[0::2, 1::2] + a[1::2, 1::2])


def _value_noise(rng, px, cell):
    n = rng.normal(0.0, 1.0, (px // cell + 3, px // cell + 3)).astype(np.float32)
    n = np.kron(n, np.ones((cell, cell), np.float32))[:px, :px]
    n = _blur(n, max(1, cell // 2))
    return n / max(float(n.std()), 1e-6)


def kuwahara(img, r=1):
    """Kuwahara filter (painterly flattening, art direction §4: suit albedo r 1-2):
    each pixel takes the mean of the least-variant of its four (r+1)^2 quadrants."""
    pad = np.pad(img, ((r, r), (r, r), (0, 0)), mode="edge")
    lum = pad.mean(-1)
    h, w = img.shape[:2]
    best_v = np.full((h, w), np.inf, np.float32)
    out = np.zeros_like(img)
    for oy in (0, r):
        for ox in (0, r):
            acc = np.zeros((h, w, img.shape[2]), np.float32)
            acc2 = np.zeros((h, w), np.float32)
            accl = np.zeros((h, w), np.float32)
            for dy in range(r + 1):
                for dx in range(r + 1):
                    sl = (slice(oy + dy, oy + dy + h), slice(ox + dx, ox + dx + w))
                    acc += pad[sl]
                    accl += lum[sl]
                    acc2 += lum[sl] ** 2
            k = (r + 1) ** 2
            var = acc2 / k - (accl / k) ** 2
            sel = var < best_v
            best_v = np.where(sel, var, best_v)
            out = np.where(sel[..., None], acc / k, out)
    return out


def linear_to_srgb(c):
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.0031308, 12.92 * c, 1.055 * np.power(c, 1 / 2.4) - 0.055)


def surface_maps(H, layout, side, spec, S, name):
    """Albedo (sRGB) and ORM (occlusion, roughness, metallic) for a wool group,
    at half the normal map's resolution, from the finished height field:
    cavity in the seams, stitches and fold valleys darkens the albedo; the
    fold valleys (cloth sim) carry the occlusion; roughness = base + fibre
    noise, per panel offsets (the pressed lapel facing is smoother)."""
    px = H.px // 2
    h = _down2(H.h.astype(np.float64))
    mpp = side / px                                    # metres per pixel
    cav = np.clip((_blur(h, 0.0012 / mpp) - h) / 0.00025, 0.0, 1.0)
    f = getattr(H, "folds", None)
    if f is not None:
        f = _down2(f.astype(np.float64))
        valley = np.clip((_blur(f, 0.012 / mpp) - f) / 0.0025, 0.0, 1.0)
    else:
        valley = np.zeros_like(h)
    ao = 1.0 - S["fold_ao"] * valley
    rng = np.random.default_rng(S["seed"])
    n1 = _value_noise(rng, px, max(2, int(0.003 / mpp)))
    n2 = _value_noise(rng, px, max(3, int(0.012 / mpp)))
    rough = spec["rough"] + S["rough_noise"] * (0.6 * n1 + 0.4 * n2)
    # per-panel roughness offsets
    for (oname, tag), L in layout.items():
        off = S["panel_rough"].get(f"{oname.split('.')[-1].split('_export')[0]}:{tag}")
        if off:
            x0, y0 = int(L["x0"] / side * px), int(L["y0"] / side * px)
            x1, y1 = int((L["x0"] + L["w"]) / side * px) + 1, int((L["y0"] + L["h"]) / side * px) + 1
            rough[y0:y1, x0:x1] += off
    rough = np.clip(rough, 0.05, 1.0)
    base = np.array(spec["albedo"] if isinstance(spec["albedo"], (list, tuple)) else [spec["albedo"]] * 3,
                    np.float64)[:3]
    var = 1.0 + S["albedo_noise"] * (0.8 * n1 + 0.2 * n2)
    shade = var * (1.0 - S["cavity"] * cav) * (1.0 - S["ao_in_albedo"] * (1.0 - ao))
    alb = base[None, None, :] * shade[..., None]
    if S["kuwahara"]:
        alb = kuwahara(alb.astype(np.float32), S["kuwahara"])
    rgba = np.empty((px, px, 4), np.float32)
    rgba[..., :3] = linear_to_srgb(alb)
    rgba[..., 3] = 1.0
    ai = bpy.data.images.new(f"suit_{name}_albedo", px, px, alpha=False)
    ai.colorspace_settings.name = "sRGB"
    ai.pixels.foreach_set(rgba.ravel())
    ai.pack()
    orm = np.empty((px, px, 4), np.float32)
    orm[..., 0] = np.clip(ao, 0, 1)
    orm[..., 1] = rough
    orm[..., 2] = 0.0
    orm[..., 3] = 1.0
    oi = bpy.data.images.new(f"suit_{name}_orm", px, px, alpha=False)
    oi.colorspace_settings.name = "Non-Color"
    oi.pixels.foreach_set(orm.ravel())
    oi.pack()
    return ai, oi, {"px": px, "rough_mean": round(float(rough.mean()), 3),
                    "ao_min": round(float(ao.min()), 3), "cavity_mean": round(float(cav.mean()), 4)}


def apply(o, parts, mats, marks, folds=None):
    """parts: {name: object}; marks: {object name: {tag: [marks]}}; folds:
    {object name: suit_drape.Fold}. Groups: wool_a (jacket), wool_b
    (waistcoat + trousers), shirt, silk (tie)."""
    T = o["textures"]
    vest = mats.get("vest")
    groups = [("wool_a", [parts["jacket"]], T["wool_px"], "wool", mats["wool"]),
              ("wool_b", [parts["trousers"]] + ([] if vest else [parts["waistcoat"]]), T["wool_px"], "wool", None),
              ("shirt", [parts["shirt"]], T["shirt_px"], "shirt", mats["shirt"]),
              ("silk", [parts["tie"]], T["tie_px"], "silk", mats["silk"]),
              ("leather", [parts.get("shoes")], T["shoe_px"], "leather", mats["leather"])]
    if vest:   # the waistcoat's own cloth (suit.DEFAULTS materials.vest)
        groups.insert(2, ("vest", [parts["waistcoat"]], T.get("vest_px", T["wool_px"]), "wool", vest))
    # Groups without their own material start from an unwired copy of the
    # wool: copied after wool_a is wired, they would carry the jacket's maps,
    # and its glTF Material Output (occlusion = the jacket's ORM) stays linked
    # beside the new one, so the exporter packed the jacket's AO into the
    # trousers' ORM.
    wool_bare = mats["wool"].copy()
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
        fold_info = add_folds(H, objs, folds, layout, side)
        img = H.normal_image(f"suit_{gname}_normal", slope=T["slope"])
        if mat is None:
            mat = wool_bare.copy()
            mat.name = f"suit_{gname}"
        attach_normal_map(mat, img, strength=1.0)
        mat["suit_atlas_side_m"] = side   # suit_hero: metric UVs for the hero-only detail
        detail = detail_record(mat, side, WEAVE[weave]) if WEAVE[weave].get("detail") else None
        surf = None
        if weave == "wool" and o.get("surface"):
            spec = o["materials"]["vest" if gname == "vest" else "wool"]
            ai, oi, surf = surface_maps(H, layout, side, spec, o["surface"], gname)
            attach_surface(mat, ai, oi)
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
                      "mm_per_px": round(1000 * side / px, 3), "marks": sum(len(v) for v in flat.values()),
                      "folds": fold_info, "surface": surf, "weave_detail": detail}
    if any(r.get("weave_detail") for r in out.values() if isinstance(r, dict)):
        _, gmax = twill_tile(slope=T["slope"])
        out["weave_detail_tile"] = {"name": DETAIL_TILE, "px": DETAIL_PX, "periods": DETAIL_PERIODS,
                                    "max_slope": round(gmax, 4)}
    bpy.data.materials.remove(wool_bare)
    return out
