"""Generated skin for the hero (m1): 4k head and 2k hands albedo, ORM and
tangent-space normal maps, synthesised in texture space from maps baked on
the game mesh itself (no painting, no photos; everything is parameters).

Pipeline (cfg["head"]["refine"]["skin"]):

  bake   Cycles emission bakes into the re-packed UVs (head_refine): object
         position, smooth normal, UV tangent, exact coverage, vertex-group
         masks (lips, nails, ears, scalp, region), three noise sets evaluated
         in 3D (Voronoi F1 for pores, value noise for mottling, grain,
         speckles, a stretched noise for creases), and ambient occlusion with
         only the body and eyes visible (hair and clothes must not shadow the
         skin). 3D evaluation makes everything seamless across UV islands.
  height a metres-valued height field per texel: pore pits, grain, and a
         set of wrinkle polylines placed in the face frame (forehead lines,
         glabella furrows, crow's feet, under-eye lines, nasolabial fold,
         lip creases, neck rings) and on the hands (knuckle creases, palm
         lines, nail cuticle). Each is a Gaussian groove with soft shoulders,
         weighted by region.
  normal the perturbed surface normal from the height gradient and the
         baked dP/du, dP/dv, expressed in the baked tangent frame (glTF +Y).
  albedo base tone (the look-dev skin tone as rendered, kept) x mottling
         x colour zones (warmer cheeks / nose / ears, cooler beard shadow,
         darker sockets, natural desaturated lips, nails) x sparse sun
         speckles x pore / groove darkening x a light "plane paint" (value
         by facing, the Sifu speed-painting read) x baked occlusion.
  ORM    R occlusion (AO x cavity), G roughness (T-zone shinier, beard zone
         and knuckles rougher, wet lid margin glossy, nails glossy), B 0.

Images are packed into the .blend and embedded in the GLB; PNG copies go to
the run directory when save_maps is set. Materials "skin_head" and
"skin_hands" are Principled with the glTF Material Output occlusion node, so
the exporter writes a standard PBR material (KTX2 later).
"""

import math
import os
import time

import bpy
import numpy as np

from . import head_refine

HEX = lambda h: np.array([int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)], dtype=np.float32)


def srgb_to_linear(c):
    c = np.asarray(c, dtype=np.float32)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4).astype(np.float32)


def linear_to_srgb(c):
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.0031308, 12.92 * c, 1.055 * np.power(c, 1 / 2.4) - 0.055).astype(np.float32)


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def gauss(x, w):
    return np.exp(-0.5 * (x / w) ** 2)


# --- baking ----------------------------------------------------------------------------------

class Baker:
    """Emission bakes of shader sockets into one image per material slot."""

    def __init__(self, body, slots, sizes, margin=16):
        self.body = body
        self.sizes = sizes
        self.margin = margin
        self.mats = []
        self.tex = []
        self.em = []
        for i in range(slots):
            m = bpy.data.materials.new(f"_bake_{i}")
            m.use_nodes = True
            nt = m.node_tree
            for n in list(nt.nodes):
                nt.nodes.remove(n)
            out = nt.nodes.new("ShaderNodeOutputMaterial")
            em = nt.nodes.new("ShaderNodeEmission")
            nt.links.new(em.outputs[0], out.inputs[0])
            tex = nt.nodes.new("ShaderNodeTexImage")
            nt.nodes.active = tex
            self.mats.append(m)
            self.tex.append(tex)
            self.em.append(em)
        self.saved_mats = [m for m in body.data.materials]
        self.mat_index = [p.material_index for p in body.data.polygons]
        body.data.materials.clear()          # resets material_index on every face
        for m in self.mats:
            body.data.materials.append(m)
        restore_indices(body.data, self.mat_index)
        self.scene = bpy.context.scene
        self.saved_engine = self.scene.render.engine
        self.scene.render.engine = "CYCLES"
        self.scene.cycles.device = "CPU"
        bpy.ops.object.select_all(action="DESELECT")
        body.select_set(True)
        bpy.context.view_layer.objects.active = body

    def source(self, build):
        """build(nt, i) -> output socket, per material slot i."""
        for i, (m, em) in enumerate(zip(self.mats, self.em)):
            nt = m.node_tree
            for l in list(em.inputs["Color"].links):
                nt.links.remove(l)
            nt.links.new(build(nt, i), em.inputs["Color"])

    def run(self, name, build, samples=1, bake_type="EMIT", margin=None, float_img=True, down=1):
        """down: bake at sizes / down and upsample (AO is smooth)."""
        imgs = []
        for i, tex in enumerate(self.tex):
            s = self.sizes[i] // down
            img = bpy.data.images.new(f"_bake_{name}_{i}", s, s, alpha=True, float_buffer=float_img, is_data=True)
            img.colorspace_settings.name = "Non-Color"
            tex.image = img
            imgs.append(img)
        if build is not None:
            self.source(build)
        self.scene.cycles.samples = samples
        t = time.perf_counter()
        bpy.ops.object.bake(type=bake_type, use_clear=True,
                            margin=self.margin if margin is None else margin, margin_type="ADJACENT_FACES")
        dt = time.perf_counter() - t
        out = []
        for img in imgs:
            s = img.size[0]
            px = np.empty(s * s * 4, dtype=np.float32)
            img.pixels.foreach_get(px)
            arr = px.reshape(s, s, 4)[..., :3].copy()
            if down > 1:
                arr = np.repeat(np.repeat(arr, down, axis=0), down, axis=1)
            out.append(arr)
            bpy.data.images.remove(img)
        print(f"[skin] bake {name}: {dt:.1f} s", flush=True)
        return out

    def finish(self):
        self.body.data.materials.clear()
        for m in self.saved_mats:
            self.body.data.materials.append(m)
        restore_indices(self.body.data, self.mat_index)
        for m in self.mats:
            bpy.data.materials.remove(m)
        self.scene.render.engine = self.saved_engine


def restore_indices(me, idx):
    me.polygons.foreach_set("material_index", np.asarray(idx, dtype=np.int32))
    me.update()


def _geom(nt, i, output):
    return nt.nodes.new("ShaderNodeNewGeometry").outputs[output]


def _const(nt, i, v=1.0):
    n = nt.nodes.new("ShaderNodeRGB")
    n.outputs[0].default_value = (v, v, v, 1.0)
    return n.outputs[0]


def _tangent(uv_name):
    def f(nt, i):
        n = nt.nodes.new("ShaderNodeTangent")
        n.direction_type = "UV_MAP"
        n.uv_map = uv_name
        return n.outputs[0]
    return f


def _attrs(names):
    def f(nt, i):
        comb = nt.nodes.new("ShaderNodeCombineColor")
        for k, name in enumerate(names):
            if name is None:
                continue
            a = nt.nodes.new("ShaderNodeAttribute")
            a.attribute_name = name
            nt.links.new(a.outputs["Fac"], comb.inputs[k])
        return comb.outputs[0]
    return f


def _noises(specs):
    """specs: three of ("noise", scale, detail) | ("voronoi", scale) |
    ("noise_aniso", scale, (sx, sy, sz))."""
    def f(nt, i):
        comb = nt.nodes.new("ShaderNodeCombineColor")
        pos = nt.nodes.new("ShaderNodeNewGeometry").outputs["Position"]
        for k, spec in enumerate(specs):
            kind = spec[0]
            vec = pos
            if kind == "noise_aniso":
                mp = nt.nodes.new("ShaderNodeMapping")
                mp.inputs["Scale"].default_value = spec[2]
                nt.links.new(pos, mp.inputs["Vector"])
                vec = mp.outputs[0]
            if kind.startswith("noise"):
                n = nt.nodes.new("ShaderNodeTexNoise")
                n.inputs["Scale"].default_value = spec[1]
                n.inputs["Detail"].default_value = spec[2] if kind == "noise" else 2.0
                n.inputs["Roughness"].default_value = 0.5
                nt.links.new(vec, n.inputs["Vector"])
                nt.links.new(n.outputs["Fac"], comb.inputs[k])
            else:
                n = nt.nodes.new("ShaderNodeTexVoronoi")
                n.feature = "F1"
                n.inputs["Scale"].default_value = spec[1]
                n.inputs["Randomness"].default_value = 1.0
                nt.links.new(vec, n.inputs["Vector"])
                nt.links.new(n.outputs["Distance"], comb.inputs[k])
        return comb.outputs[0]
    return f


def beard_depth(b, body):
    """Per-vertex beard coverage 0..1 from the beard track's own landmark rules
    (hair_beard.landmarks / inside_dist, the same lines the shells use), so
    the skin's stubble shadow follows the beard edge exactly. None when the
    beard is off or the API differs."""
    cfg = (b.cfg.get("hair") or {}).get("beard")
    if not cfg:
        return None
    try:
        from . import hair_beard
        from .hair_frame import HeadFrame
        frame = HeadFrame(b, [body])
        groups = tuple(body.vertex_groups[n].index for n in ("lips", "ears", "head", "neck_01"))
        cheek, neck, back_y = hair_beard.landmarks(frame, cfg)
        margins = (cfg["margin_m"], cfg["neck_margin_m"], cfg["back_margin_m"], cfg["moustache_margin_m"])
        moustache_top = frame.lips_max.z + cfg["moustache_height_m"]
        nose = (frame.lips_min.y - cfg["nose_clear_m"], frame.lips_max.z)
        mw = body.matrix_world
        out = np.zeros(len(body.data.vertices), np.float32)
        fade = cfg["fade_m"]
        for v in body.data.vertices:
            d, m = hair_beard.inside_dist(mw @ v.co, {e.group: e.weight for e in v.groups}, groups,
                                          cheek, neck, back_y, margins, moustache_top, nose)
            if d > -1.0:
                t = min(max((d + m) / (m + fade), 0.0), 1.0)
                out[v.index] = t * t * (3 - 2 * t)
        return out
    except (ImportError, KeyError, TypeError, AttributeError) as e:  # older beard API
        print(f"[skin] beard depth unavailable ({e!r}); using the frame heuristic", flush=True)
        return None


def set_attr(me, name, values):
    a = me.attributes.get(name) or me.attributes.new(name, "FLOAT", "POINT")
    a.data.foreach_set("value", np.ascontiguousarray(values, dtype=np.float32))
    return name


# --- synthesis -------------------------------------------------------------------------------

class Maps:
    """Everything the synthesis needs for one texture (head or hands)."""

    def __init__(self, size, P, N, T, cover, attrs1, attrs2, nA, nB, nC, ao):
        self.size = size
        self.P, self.N, self.T = P, N, T
        self.cover = cover[..., 0] > 0.5
        self.valid = (np.abs(P).sum(-1) > 1e-9)      # inside the baked margin
        self.lips, self.nails, self.ears = attrs1[..., 0], attrs1[..., 1], attrs1[..., 2]
        self.scalp, self.region, self.beard_in = attrs2[..., 0], attrs2[..., 1], attrs2[..., 2]
        self.pore_f, self.mot_mid, self.mot_low = nA[..., 0], nA[..., 1], nA[..., 2]
        self.pore_c, self.grain, self.speck = nB[..., 0], nB[..., 1], nB[..., 2]
        self.aniso, self.aniso_y, self.broad = nC[..., 0], nC[..., 1], nC[..., 2]
        self.ao = ao[..., 0]
        # derivatives of P along the image axes (metres per texel)
        self.Pu = np.zeros_like(P)
        self.Pv = np.zeros_like(P)
        self.Pu[:, 1:-1] = (P[:, 2:] - P[:, :-2]) * 0.5
        self.Pv[1:-1, :] = (P[2:, :] - P[:-2, :]) * 0.5
        self.tex_m = np.maximum(np.linalg.norm(self.Pu, axis=-1), 1e-6)   # metres per texel (u)

    def face_frame(self, cl, cr):
        o = (cl + cr) * 0.5
        s = float(np.linalg.norm(cl - cr)) / 0.0616
        d = self.P - o
        self.s = s
        self.u = np.abs(d[..., 0]) / s
        self.x = d[..., 0] / s
        self.h = d[..., 2] / s
        self.f = -d[..., 1] / s
        self.eye_d = np.minimum(np.linalg.norm(self.P - cl, axis=-1), np.linalg.norm(self.P - cr, axis=-1)) / s
        self.front = np.clip(-self.N[..., 1], 0.0, 1.0)   # facing forward

    def groove(self, pts2, amp, w, fade=None, pow_shoulder=0.3, mask=None, coord="uh"):
        """Add a groove along a polyline in a 2D frame coordinate pair
        ("uh": lateral/up, mirrored; "fh": forward/up for the temple;
        "xh": signed). amp in metres (positive = depth), w the half-width."""
        if coord == "uh":
            a, b = self.u, self.h
        elif coord == "fh":
            a, b = self.f, self.h
        else:
            a, b = self.x, self.h
        pts = np.asarray(pts2, dtype=np.float32)
        d = np.full(a.shape, np.inf, dtype=np.float32)
        tt = np.zeros(a.shape, dtype=np.float32)
        total = np.sum(np.linalg.norm(np.diff(pts, axis=0), axis=1))
        acc = 0.0
        for p0, p1 in zip(pts[:-1], pts[1:]):
            e = p1 - p0
            L2 = max(float(e @ e), 1e-12)
            t = np.clip(((a - p0[0]) * e[0] + (b - p0[1]) * e[1]) / L2, 0, 1)
            dd = np.hypot(a - (p0[0] + t * e[0]), b - (p0[1] + t * e[1]))
            closer = dd < d
            d = np.where(closer, dd, d)
            tt = np.where(closer, (acc + t * math.sqrt(L2)) / max(total, 1e-9), tt)
            acc += math.sqrt(L2)
        tt = np.clip(tt, 0.0, 1.0)
        prof = gauss(d, w) - pow_shoulder * gauss(d, 2.2 * w)
        if fade == "ends":
            prof = prof * np.sin(np.pi * tt) ** 0.5
        elif fade == "end":
            prof = prof * (1 - tt) ** 0.7
        elif fade == "start":
            prof = prof * tt ** 0.7
        if mask is not None:
            prof = prof * mask
        return amp * prof

    def normal_map(self, h):
        """Tangent-space normal (glTF, +Y up) from height h (metres)."""
        hu = np.zeros_like(h)
        hv = np.zeros_like(h)
        hu[:, 1:-1] = (h[:, 2:] - h[:, :-2]) * 0.5
        hv[1:-1, :] = (h[2:, :] - h[:-2, :]) * 0.5
        # Bump-mapping form (Blender's Bump node): perturb the smooth normal
        # by the surface gradient of h, using the dual basis of (Pu, Pv).
        # Using cross(Pu + hu N, Pv + hv N) instead would bake the flat
        # triangle normals (facets) into the map.
        N = self.N
        Rx = np.cross(self.Pv, N)
        Ry = np.cross(N, self.Pu)
        det = (np.cross(self.Pu, self.Pv) * N).sum(-1, keepdims=True)
        det = np.where(np.abs(det) < 1e-18, 1e-18, det)
        n = N - (hu[..., None] * Rx + hv[..., None] * Ry) / det
        n /= np.maximum(np.linalg.norm(n, axis=-1, keepdims=True), 1e-9)
        T = self.T - N * (self.T * N).sum(-1, keepdims=True)
        T /= np.maximum(np.linalg.norm(T, axis=-1, keepdims=True), 1e-9)
        B = np.cross(N, T)
        sign = np.sign((B * self.Pv).sum(-1, keepdims=True) + 1e-12)
        B *= sign
        ts = np.stack([(n * T).sum(-1), (n * B).sum(-1), (n * N).sum(-1)], axis=-1)
        bad = ~self.valid | (self.tex_m < 1e-6)
        ts[bad] = (0.0, 0.0, 1.0)
        return np.clip(ts * 0.5 + 0.5, 0.0, 1.0)

    def cavity(self, h):
        lap = np.zeros_like(h)
        lap[1:-1, 1:-1] = (h[1:-1, 2:] + h[1:-1, :-2] + h[2:, 1:-1] + h[:-2, 1:-1] - 4 * h[1:-1, 1:-1])
        lap /= self.tex_m ** 2       # curvature-ish, 1/m
        return lap


def synth_head(m, c, cl, cr):
    """Albedo (linear), roughness, height, cavity-darkening for the head map."""
    m.face_frame(cl, cr)
    mm = 0.001
    u, h, f = m.u, m.h, m.f
    front = m.front
    lips = np.clip(m.lips, 0, 1)

    # --- region weights (0..1) in the face frame
    cheek = gauss(u - 0.046, 0.022) * gauss(h + 0.038, 0.020) * smoothstep(-0.02, 0.01, f)
    nose = gauss(u, 0.014) * gauss(h + 0.030, 0.026) * smoothstep(0.02, 0.035, f)
    forehead = smoothstep(0.028, 0.05, h) * smoothstep(-0.02, 0.005, f)
    socket = gauss(m.eye_d - 0.013, 0.012) * (m.eye_d > 0.008) * smoothstep(-0.01, 0.01, f)
    # orbit roof: the band under the brow shelf (painted eye-band shadow, look-spec §2.2)
    roof = gauss(u - 0.032, 0.020) * gauss(h - 0.012, 0.007) * smoothstep(-0.01, 0.01, f)
    under_eye = gauss(u - 0.031, 0.018) * gauss(h + 0.016, 0.009) * smoothstep(0.0, 0.015, f)
    beard = smoothstep(-0.040, -0.058, h) * (1 - gauss(u, 0.016) * smoothstep(-0.075, -0.06, h)) \
        * smoothstep(0.045, 0.02, f * 0 + (f if True else 0)) * 0 + \
        smoothstep(-0.040, -0.060, h) * (1 - nose) * smoothstep(-0.03, 0.0, f) * (1 - lips)
    beard = np.clip(beard, 0, 1) * smoothstep(0.075, 0.055, u + 0 * h)      # not past the ear
    beard = np.maximum(beard, smoothstep(-0.05, -0.062, h) * gauss(u, 0.02) * (1 - lips) * smoothstep(0.0, 0.02, f))
    if np.any(m.beard_in >= 0):   # the beard track's own region (hair_beard landmarks)
        beard = np.clip(m.beard_in, 0, 1) * (1 - lips)
    # stubble: dark hair-root specks whose density follows the beard band
    stubble = smoothstep(0.78, 0.9, 1 - m.pore_c) * beard * (1 - lips)
    lid_margin = gauss(m.eye_d - c["lid_margin_r"], 0.0018) * smoothstep(-0.2, 0.3, (m.N * ((np.array([cl, cr])[None, None, 0] - m.P)
                                                                                           / np.maximum(np.linalg.norm(cl - m.P, axis=-1, keepdims=True), 1e-9))).sum(-1))
    temple = gauss(u - 0.062, 0.015) * gauss(h - 0.03, 0.025)
    neck = (m.region > 0.6) * (m.region < 0.85)
    ears = np.clip(m.ears, 0, 1)
    scalp = np.clip(m.scalp, 0, 1)

    # --- height (metres)
    pore_w = (0.35 + 0.9 * cheek + 1.2 * nose + 0.5 * forehead + 0.4 * temple) * (1 - 0.9 * lips) \
        * (1 - 0.8 * gauss(m.eye_d - 0.013, 0.004)) * (1 - 0.7 * scalp) * (1 - 0.5 * neck)
    pores = gauss(m.pore_f, 0.20) * c["pore_mm"] * mm * pore_w
    pores_c = gauss(m.pore_c, 0.16) * c["pore_coarse_mm"] * mm * (nose + 0.6 * cheek) * (1 - lips)
    grain = (m.grain - 0.5) * c["grain_mm"] * mm
    hgt = -(pores + pores_c) + grain

    k = c["wrinkle_scale"]
    wob = (m.broad - 0.5) * 0.004
    # forehead lines (3), arched, fading at the temples
    for i, (hh, amp) in enumerate(((0.040, 0.16), (0.052, 0.22), (0.065, 0.17))):
        pts = [(uu, hh + 0.005 * (1 - (uu / 0.05) ** 2) + (0.0015 * math.sin(uu * 400 + i)))
               for uu in np.linspace(0.0, 0.052, 9)]
        hgt -= m.groove(pts, k * amp * mm, 0.0011, fade="end", mask=forehead * smoothstep(0.03, 0.0, m.f * 0 + np.abs(wob)) + forehead * 0.0)
    # glabella furrows ("11s")
    hgt -= m.groove([(0.0055, 0.010), (0.0065, 0.030)], k * 0.24 * mm, 0.0013, fade="ends", mask=front)
    # crow's feet: 4 lines radiating back from the outer canthus (temple plane)
    canth = (0.012, -0.001)
    lat = smoothstep(0.040, 0.050, u)
    for ang in (-28, -10, 8, 26):
        a = math.radians(ang)
        tip = (canth[0] - 0.019 * math.cos(a), canth[1] + 0.019 * math.sin(a) - 0.004)
        hgt -= m.groove([canth, tip], k * 0.20 * mm, 0.0009, fade="end", mask=lat, coord="fh")
    # under-eye lines
    hgt -= m.groove([(0.016, -0.0095), (0.031, -0.0125), (0.047, -0.0085)], k * 0.14 * mm, 0.0011, fade="ends", mask=front)
    hgt -= m.groove([(0.020, -0.014), (0.033, -0.0165), (0.045, -0.013)], k * 0.09 * mm, 0.0012, fade="ends", mask=front)
    # nasolabial fold
    hgt -= m.groove([(0.016, -0.038), (0.024, -0.050), (0.029, -0.064), (0.031, -0.079)],
                    k * c["nasolabial_mm"] * mm, 0.0022, fade="ends", mask=front)
    # lip creases: vertical stretched noise on the lips
    hgt -= smoothstep(0.52, 0.7, m.aniso) * lips * c["lip_crease_mm"] * mm
    # neck rings
    for hh, amp in ((-0.138, 0.22), (-0.153, 0.18)):
        pts = [(uu, hh + 0.004 * (uu / 0.04) ** 2) for uu in np.linspace(0.0, 0.045, 6)]
        hgt -= m.groove(pts, k * amp * mm, 0.0014, fade="end", mask=np.maximum(neck, smoothstep(-0.12, -0.13, h)) * smoothstep(-0.03, 0.0, f))
    hgt = hgt.astype(np.float32)

    # --- cavity and occlusion
    cav = m.cavity(hgt)
    pit = np.clip(cav * c["cavity_scale"], 0, 1)           # positive laplacian = pit
    ao = np.clip(m.ao, 0, 1)
    occl = np.clip(ao * (1 - 0.55 * pit), 0, 1)

    # --- albedo (linear)
    base = srgb_to_linear(HEX(c["base"]))
    alb = np.ones(m.P.shape, dtype=np.float32) * base
    mot = 1 + (m.mot_low - 0.5) * c["mottle_low"] + (m.mot_mid - 0.5) * c["mottle_mid"] + (m.grain - 0.5) * 0.04
    alb *= mot[..., None]
    # hue mottling: low-frequency red/yellow drift
    alb[..., 0] *= 1 + (m.broad - 0.5) * 0.05
    alb[..., 2] *= 1 - (m.mot_low - 0.5) * 0.06

    def tint(w, rgb):
        nonlocal alb
        alb = alb * (1 + np.clip(w, 0, 1)[..., None] * (np.array(rgb, np.float32) - 1))
    tint(cheek * c["flush"], (1.07, 0.93, 0.90))
    tint(nose * c["flush"], (1.06, 0.93, 0.91))
    tint(ears * 0.8 * c["flush"], (1.08, 0.94, 0.92))
    tint(forehead * 0.6, (1.02, 1.0, 0.95))
    tint(socket * c["socket_dark"], (0.84, 0.81, 0.86))
    tint(roof * c["socket_dark"], (0.82, 0.80, 0.84))
    tint(under_eye * c["socket_dark"] * 0.7, (0.90, 0.86, 0.90))
    tint(beard * c["beard_shadow"], (0.80, 0.80, 0.86))      # beard shadow under the shells
    tint(stubble * c["stubble"], (0.45, 0.40, 0.38))          # hair roots at the skin
    tint(temple * 0.4, (0.96, 0.96, 0.98))
    tint(scalp * 0.7, (0.93, 0.92, 0.94))
    # lips: desaturated brick, darker at the vermilion edge, no pink
    lipc = srgb_to_linear(HEX(c["lip"]))
    lw = smoothstep(0.35, 0.95, lips) ** 1.5 * c["lip_mix"]   # the vermilion, not the lip skin
    alb = alb * (1 - lw[..., None]) + lipc * lw[..., None]
    tint(lid_margin, (1.05, 0.86, 0.86))
    # speckles (sun damage): sparse, forehead / cheekbones / nose, warm brown
    spk = smoothstep(c["speck_thr"], c["speck_thr"] + 0.03, m.speck) * (0.4 * forehead + cheek + 0.8 * nose + 0.3 * temple)
    tint(spk * c["speck"], (0.72, 0.62, 0.58))
    # pores and grooves darken a little
    alb *= (1 - 0.35 * pit)[..., None]
    # plane paint: value by facing (up/front planes lighter, under-planes darker)
    L = np.array([0.0, -0.45, 1.0], np.float32)
    L /= np.linalg.norm(L)
    facing = np.clip((m.N * L).sum(-1), -1, 1)
    alb *= (1 + c["plane_paint"] * facing)[..., None]
    alb *= (1 - c["ao_in_albedo"] * (1 - ao))[..., None]
    alb = np.clip(alb, 0, 1)

    # --- roughness
    rough = np.full(m.P.shape[:2], c["rough"], np.float32)
    rough += -0.09 * nose - 0.07 * forehead + 0.03 * cheek + 0.08 * beard + 0.05 * neck
    rough += (m.mot_mid - 0.5) * 0.08 + pit * 0.12
    rough = rough * (1 - lw) + c["lip_rough"] * lw
    rough = rough * (1 - lid_margin) + c["lid_rough"] * lid_margin
    rough = np.clip(rough, 0.05, 1.0)
    return alb, rough, hgt, occl


def synth_hands(m, c, hf, arm_mw):
    """Albedo, roughness, height, occlusion for the hands map."""
    mm = 0.001
    P, N = m.P, m.N
    nails = np.clip(m.nails, 0, 1)
    back = np.zeros(P.shape[:2], np.float32)
    knuckle = np.zeros_like(back)
    hgt = np.zeros_like(back)
    for side, f in hf.items():
        near = np.linalg.norm(P - f["wrist"], axis=-1) < 0.25
        b = np.clip((N * f["back"]).sum(-1), -1, 1) * near
        back = np.where(b > back, b, back) if side == "l" else np.maximum(back, b)
        wb = np.clip(b, 0, 1) ** 1.3
        wp = np.clip(-b, 0, 1) ** 1.3
        for name in head_refine.FINGERS:
            for joint, r, n_lines in ((f["mcp"][name], 0.009, 3), (f["pip"][name], 0.0065, 3), (f["dip"][name], 0.005, 2)):
                along = (P - joint) @ f["fingers"]
                across = np.linalg.norm(P - joint - along[..., None] * f["fingers"], axis=-1)
                inr = gauss(across, r)
                knuckle += inr * wb * gauss(along, 0.006)
                for i in range(n_lines):
                    off = (i - (n_lines - 1) / 2) * 0.0017
                    hgt -= c["knuckle_crease_mm"] * mm * gauss(along - off, 0.0005) * inr * wb
                # palm-side flexion creases
                for off in (-0.001, 0.001):
                    hgt -= c["palm_crease_mm"] * mm * 0.6 * gauss(along - off - 0.002, 0.0006) * inr * wp
        # palm lines: three long creases in the hand plane
        wrist, fd, ad = f["wrist"], f["fingers"], f["across"]
        def pl(pts, amp, w, back=back, wrist=wrist, fd=fd, ad=ad, wp=wp):
            nonlocal hgt
            d = np.full(back.shape, np.inf, np.float32)
            a = (P - wrist) @ fd
            bb = (P - wrist) @ ad
            for p0, p1 in zip(pts[:-1], pts[1:]):
                e = np.array(p1) - np.array(p0)
                L2 = float(e @ e)
                t = np.clip(((a - p0[0]) * e[0] + (bb - p0[1]) * e[1]) / L2, 0, 1)
                d = np.minimum(d, np.hypot(a - (p0[0] + t * e[0]), bb - (p0[1] + t * e[1])))
            hgt -= amp * mm * (gauss(d, w) - 0.3 * gauss(d, 2.2 * w)) * wp
        s_ = 1.0   # the hand frame's across axis is already mirrored per side
        pl([(0.045, -0.035 * s_), (0.062, 0.0), (0.072, 0.03 * s_)], c["palm_line_mm"], 0.0012)      # heart line
        pl([(0.030, -0.035 * s_), (0.042, 0.0), (0.050, 0.025 * s_)], c["palm_line_mm"] * 0.9, 0.0012)  # head line
        pl([(0.075, -0.030 * s_), (0.040, -0.028 * s_), (0.012, -0.010 * s_)], c["palm_line_mm"], 0.0013)  # life line
    knuckle = np.clip(knuckle, 0, 1)
    # pores / grain: back of hand coarser
    pores = gauss(m.pore_f, 0.2) * c["pore_mm"] * mm * (0.5 + 0.6 * np.clip(back, 0, 1)) * (1 - nails)
    hgt -= pores
    hgt += (m.grain - 0.5) * c["grain_mm"] * mm
    # skin folds over the knuckles (stretched noise)
    hgt -= smoothstep(0.55, 0.72, m.aniso_y) * knuckle * 0.06 * mm
    # nails: cuticle groove at the nail edge, fine longitudinal ridges
    nail_edge = gauss(nails - 0.35, 0.12)
    hgt -= nail_edge * c["cuticle_mm"] * mm
    hgt += (m.aniso - 0.5) * 0.02 * mm * nails
    hgt = hgt.astype(np.float32)
    cav = m.cavity(hgt)
    pit = np.clip(cav * c["cavity_scale"], 0, 1)
    ao = np.clip(m.ao, 0, 1)
    occl = np.clip(ao * (1 - 0.5 * pit), 0, 1)

    base = srgb_to_linear(HEX(c["base"]))
    alb = np.ones(P.shape, np.float32) * base
    mot = 1 + (m.mot_low - 0.5) * c["mottle_low"] + (m.mot_mid - 0.5) * c["mottle_mid"] + (m.grain - 0.5) * 0.04
    alb *= mot[..., None]
    palm = np.clip(-back, 0, 1)
    alb *= (1 + palm[..., None] * (np.array((1.08, 1.0, 0.98), np.float32) - 1))
    alb *= (1 + (knuckle * 0.8)[..., None] * (np.array((1.05, 0.92, 0.90), np.float32) - 1))
    spk = smoothstep(c["speck_thr"], c["speck_thr"] + 0.03, m.speck) * np.clip(back, 0, 1)
    alb *= (1 + (spk * c["speck"])[..., None] * (np.array((0.72, 0.62, 0.58), np.float32) - 1))
    nailc = srgb_to_linear(HEX(c["nail"]))
    nw = smoothstep(0.3, 0.8, nails)
    alb = alb * (1 - nw[..., None]) + nailc * nw[..., None]
    alb *= (1 - 0.35 * pit)[..., None]
    L = np.array([0.0, -0.45, 1.0], np.float32)
    L /= np.linalg.norm(L)
    alb *= (1 + c["plane_paint"] * np.clip((N * L).sum(-1), -1, 1))[..., None]
    alb *= (1 - c["ao_in_albedo"] * (1 - ao))[..., None]
    alb = np.clip(alb, 0, 1)
    rough = np.full(P.shape[:2], c["rough"] + 0.05, np.float32)
    rough += 0.06 * knuckle - 0.04 * palm + (m.mot_mid - 0.5) * 0.08 + pit * 0.12
    rough = rough * (1 - nw) + 0.3 * nw
    return np.clip(rough, 0.05, 1.0), alb, hgt, occl


# --- images and materials --------------------------------------------------------------------

def make_image(name, rgb, srgb, out_dir=None):
    s = rgb.shape[0]
    img = bpy.data.images.new(name, s, s, alpha=False)
    img.colorspace_settings.name = "sRGB" if srgb else "Non-Color"
    px = np.empty((s, s, 4), np.float32)
    px[..., :3] = linear_to_srgb(rgb) if srgb else np.clip(rgb, 0, 1)
    px[..., 3] = 1.0
    img.pixels.foreach_set(px.ravel())
    if out_dir:
        img.filepath_raw = os.path.join(out_dir, name + ".png")
        img.file_format = "PNG"
        img.save()
    img.pack()
    return img


def gltf_output_group():
    name = "glTF Material Output"
    g = bpy.data.node_groups.get(name)
    if g is None:
        g = bpy.data.node_groups.new(name, "ShaderNodeTree")
        g.interface.new_socket("Occlusion", in_out="INPUT", socket_type="NodeSocketFloat")
        g.nodes.new("NodeGroupInput")
    return g


def skin_material(name, albedo, orm, normal, sss):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    p = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    ta = nt.nodes.new("ShaderNodeTexImage")
    ta.image = albedo
    nt.links.new(ta.outputs["Color"], p.inputs["Base Color"])
    to = nt.nodes.new("ShaderNodeTexImage")
    to.image = orm
    sep = nt.nodes.new("ShaderNodeSeparateColor")
    nt.links.new(to.outputs["Color"], sep.inputs[0])
    nt.links.new(sep.outputs["Green"], p.inputs["Roughness"])
    nt.links.new(sep.outputs["Blue"], p.inputs["Metallic"])
    grp = nt.nodes.new("ShaderNodeGroup")
    grp.node_tree = gltf_output_group()
    nt.links.new(sep.outputs["Red"], grp.inputs["Occlusion"])
    tn = nt.nodes.new("ShaderNodeTexImage")
    tn.image = normal
    nm = nt.nodes.new("ShaderNodeNormalMap")
    nm.inputs["Strength"].default_value = 1.0
    nt.links.new(tn.outputs["Color"], nm.inputs["Color"])
    nt.links.new(nm.outputs["Normal"], p.inputs["Normal"])
    p.inputs["Specular IOR Level"].default_value = 0.5   # default: no KHR_materials_specular in the GLB
    if sss and "Subsurface Weight" in p.inputs:   # render-side only; glTF ignores it
        p.inputs["Subsurface Weight"].default_value = sss
        p.inputs["Subsurface Radius"].default_value = (0.004, 0.0015, 0.0008)
        p.inputs["Subsurface Scale"].default_value = 0.6
    return m


# --- stage -----------------------------------------------------------------------------------

def build(b):
    rcfg = b.cfg["head"].get("refine") or {}
    c = rcfg.get("skin")
    if not c or not c.get("enabled", True):
        return None
    t0 = time.perf_counter()
    body = head_refine.staged_body(b)
    arm = b.armature()
    eyes = head_refine.find_eyes(b)
    lab = getattr(b, "refine_labels", None)
    if lab is None:
        lab, _ = head_refine.classify(body, arm)
    me = body.data
    uv = me.uv_layers.active.name
    px = rcfg.get("uv_px") or {}
    sizes = [int(px.get("head_px", 4096)), int(px.get("hands_px", 2048))]
    bake_px = [min(s, int(c.get("bake_px", 4096))) for s in sizes]

    # vertex attributes to bake
    region = np.array([{"face": 0.5, "head": 0.25, "neck": 0.75, "hand": 1.0}.get(l, 0.0) for l in lab], np.float32)
    set_attr(me, "sk_lips", head_refine.group_weights(body, "lips"))
    set_attr(me, "sk_nails", head_refine.group_weights(body, "fingernails"))
    set_attr(me, "sk_ears", head_refine.group_weights(body, "ears"))
    set_attr(me, "sk_scalp", head_refine.group_weights(body, "scalp"))
    set_attr(me, "sk_region", region)
    bd = beard_depth(b, body)
    set_attr(me, "sk_beard", bd if bd is not None else np.full(len(me.vertices), -1.0, np.float32))
    # hide everything but body + eyes for the AO bake
    hidden = []
    for o in b.meshes():
        if o not in (body, eyes) and not o.hide_render:
            o.hide_render = True
            hidden.append(o)
    bk = Baker(body, 2, bake_px, margin=int(c.get("margin_px", 16)))
    try:
        P = bk.run("pos", lambda nt, i: _geom(nt, i, "Position"))
        N = bk.run("nrm", lambda nt, i: _geom(nt, i, "Normal"))
        T = bk.run("tan", _tangent(uv))
        cover = bk.run("cover", _const, margin=0)
        a1 = bk.run("attr1", _attrs(("sk_lips", "sk_nails", "sk_ears")))
        a2 = bk.run("attr2", _attrs(("sk_scalp", "sk_region", "sk_beard")))
        nz = c.get("noise") or {}
        nA = bk.run("noiseA", _noises((("voronoi", nz.get("pore_scale", 1700)), ("noise", 350, 3.0), ("noise", 55, 2.0))))
        nB = bk.run("noiseB", _noises((("voronoi", nz.get("pore_coarse_scale", 800)), ("noise", 3000, 2.0), ("noise", 180, 4.0))))
        nC = bk.run("noiseC", _noises((("noise_aniso", 900, (1.0, 1.0, 0.05)), ("noise_aniso", 900, (0.05, 1.0, 1.0)), ("noise", 22, 1.0))))
        ao = bk.run("ao", None, samples=int(c.get("ao_samples", 16)), bake_type="AO", down=int(c.get("ao_down", 2)))
    finally:
        bk.finish()
        for o in hidden:
            o.hide_render = False
    for n in ("sk_lips", "sk_nails", "sk_ears", "sk_scalp", "sk_region"):
        me.attributes.remove(me.attributes[n])

    maps = [Maps(bake_px[i], P[i], N[i], T[i], cover[i], a1[i], a2[i], nA[i], nB[i], nC[i], ao[i]) for i in range(2)]
    cl, cr = head_refine.eye_centres(eyes) if eyes is not None else (np.array([0.03, -0.13, 1.72]), np.array([-0.03, -0.13, 1.72]))
    hc = dict(DEFAULT_HEAD)
    hc.update(c.get("head") or {})
    hc["base"] = c.get("base", hc["base"])
    alb, rough, hgt, occl = synth_head(maps[0], hc, cl, cr)
    nrm = maps[0].normal_map(hgt)
    out_dir = b.out_dir if c.get("save_maps") else None
    imgs = {
        "skin_head_albedo": make_image("skin_head_albedo", alb, True, out_dir),
        "skin_head_orm": make_image("skin_head_orm", np.stack([occl, rough, np.zeros_like(rough)], -1), False, out_dir),
        "skin_head_normal": make_image("skin_head_normal", nrm, False, out_dir),
    }
    hh = dict(DEFAULT_HANDS)
    hh.update(c.get("hands") or {})
    hh["base"] = c.get("base", hh["base"])
    rough2, alb2, hgt2, occl2 = synth_hands(maps[1], hh, head_refine.hand_frames(arm), arm.matrix_world)
    nrm2 = maps[1].normal_map(hgt2)
    imgs.update({
        "skin_hands_albedo": make_image("skin_hands_albedo", alb2, True, out_dir),
        "skin_hands_orm": make_image("skin_hands_orm", np.stack([occl2, rough2, np.zeros_like(rough2)], -1), False, out_dir),
        "skin_hands_normal": make_image("skin_hands_normal", nrm2, False, out_dir),
    })
    sss = float(c.get("sss", 0.0))
    idx = [p.material_index for p in me.polygons]
    me.materials.clear()
    me.materials.append(skin_material("skin_head", imgs["skin_head_albedo"], imgs["skin_head_orm"], imgs["skin_head_normal"], sss))
    me.materials.append(skin_material("skin_hands", imgs["skin_hands_albedo"], imgs["skin_hands_orm"], imgs["skin_hands_normal"], sss))
    restore_indices(me, idx)
    stats = {"sizes": bake_px, "seconds": round(time.perf_counter() - t0, 2),
             "height_mm": {"head": [round(float(hgt.min()) * 1000, 3), round(float(hgt.max()) * 1000, 3)],
                           "hands": [round(float(hgt2.min()) * 1000, 3), round(float(hgt2.max()) * 1000, 3)]},
             "albedo_mean_srgb": [round(float(x), 3) for x in linear_to_srgb(alb[maps[0].cover].mean(0))],
             "roughness_mean": round(float(rough[maps[0].cover].mean()), 3)}
    b.notes["skin"] = stats
    print(f"[skin] done in {stats['seconds']} s", flush=True)
    return stats


DEFAULT_HEAD = {
    "base": "#c4a996",          # look-dev skin tone as rendered (MPFB face mean, sat x0.55, val x0.88)
    "lip": "#93655b", "lip_mix": 0.55, "lip_rough": 0.5,
    "lid_margin_r": 0.0135, "lid_rough": 0.18,
    "flush": 0.8, "socket_dark": 1.0, "beard_shadow": 0.7, "stubble": 0.6,
    "mottle_low": 0.10, "mottle_mid": 0.07,
    "speck_thr": 0.74, "speck": 0.55,
    "pore_mm": 0.08, "pore_coarse_mm": 0.10, "grain_mm": 0.008,
    "wrinkle_scale": 1.8, "nasolabial_mm": 0.55, "lip_crease_mm": 0.06,
    "cavity_scale": 0.0006,
    "plane_paint": 0.06, "ao_in_albedo": 0.25,
    "rough": 0.56,
}

DEFAULT_HANDS = {
    "base": "#c4a996", "nail": "#c9a399",
    "mottle_low": 0.10, "mottle_mid": 0.07,
    "speck_thr": 0.72, "speck": 0.5,
    "pore_mm": 0.05, "grain_mm": 0.006,
    "knuckle_crease_mm": 0.45, "palm_crease_mm": 0.4, "palm_line_mm": 0.5, "cuticle_mm": 0.15,
    "cavity_scale": 0.0006,
    "plane_paint": 0.05, "ao_in_albedo": 0.25,
    "rough": 0.56,
}
