"""Generated skin for the hero: head and hands albedo, ORM and tangent-space
normal maps for the game (GLB), plus the Cycles-only hero skin, all
synthesised from maps baked on the game mesh itself (no painting, no photos;
everything is parameters).

Pipeline (cfg["head"]["refine"]["skin"]):

  bake   Cycles emission bakes into the re-packed UVs (head_refine): object
         position, smooth normal, UV tangent, exact coverage, vertex-group
         masks (lips, nails, ears, scalp, region, beard zone), four 3D noise
         sets (skin_synth.NOISE_SPECS: three Voronoi pore layers, mottling,
         stretched crease noise, grain, speckles, Voronoi edges), and ambient
         occlusion with only the body and eyes visible. 3D evaluation makes
         everything seamless across UV islands.
  synth  skin_synth.synth_head / synth_hands: albedo by colour zones, a
         roughness map, a height field (region pores, lines), hero masks.
  game   albedo (sRGB), ORM (occlusion / roughness / 0) and a normal map from
         the game height (lines + pores); one Principled per slot with the
         "glTF Material Output" occlusion group. Written to the GLB.
  hero   (hero(b), after the GLB export) a Cycles-only material per slot:
         Random Walk (Skin) subsurface, the roughness map, a thin oil coat,
         a vellus sheen, and true displacement (BOTH) of the hero height
         (lines, in mm) minus three procedural Voronoi pore layers evaluated
         on the bake-time rest position (attribute "hero_rest", so pores
         stay put in poses and match the game normal map), on an adaptive
         Subdivision modifier (1 px dicing).
"""

import json
import math
import os
import time

import bpy
import numpy as np

from . import hand_detail, head_refine, skin_synth
from .skin_synth import HEX, gauss, linear_to_srgb, smoothstep, srgb_to_linear  # noqa: F401 (eyes_hq uses them)

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
    """specs: three of ("noise", scale, detail) | ("voronoi", scale) (F1
    distance, cell units) | ("edge", scale) (Voronoi distance to edge) |
    ("noise_aniso", scale, (sx, sy, sz)) (Mapping-scaled position)."""
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
            if kind == "edge_aniso":                 # distorted, stretched Voronoi edge
                dn = nt.nodes.new("ShaderNodeTexNoise")
                dn.inputs["Scale"].default_value = spec[1]
                dn.inputs["Detail"].default_value = 2.0
                nt.links.new(pos, dn.inputs["Vector"])
                off = nt.nodes.new("ShaderNodeVectorMath")
                off.operation = "MULTIPLY_ADD"
                nt.links.new(dn.outputs["Color"], off.inputs[0])
                off.inputs[1].default_value = (spec[3] / spec[1],) * 3
                off.inputs[2].default_value = (-0.5 * spec[3] / spec[1],) * 3
                add = nt.nodes.new("ShaderNodeVectorMath")
                add.operation = "ADD"
                nt.links.new(pos, add.inputs[0])
                nt.links.new(off.outputs[0], add.inputs[1])
                mp = nt.nodes.new("ShaderNodeMapping")
                mp.inputs["Scale"].default_value = spec[2]
                nt.links.new(add.outputs[0], mp.inputs["Vector"])
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
                n.feature = "DISTANCE_TO_EDGE" if kind in ("edge", "edge_aniso") else "F1"
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
        margins = hair_beard.line_margins(cfg)
        # T21: the sideburn and the back line under the ear, as the beard build placed them
        extra = getattr(b, "beard_extra", None)
        moustache_top = frame.lips_max.z + cfg["moustache_height_m"]
        nose = (frame.lips_min.y - cfg["nose_clear_m"], frame.lips_max.z)
        mw = body.matrix_world
        out = np.zeros(len(body.data.vertices), np.float32)
        fade = cfg["fade_m"]
        for v in body.data.vertices:
            d, m = hair_beard.inside_dist(mw @ v.co, {e.group: e.weight for e in v.groups}, groups,
                                          cheek, neck, back_y, margins, moustache_top, nose, extra)
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


# --- synthesis inputs ------------------------------------------------------------------------

class Maps:
    """Everything the synthesis needs for one texture (head or hands)."""

    def __init__(self, size, P, N, T, cover, attrs1, attrs2, nA, nB, nC, nD, ao, nE=None, nF=None, nG=None, nH=None,
                 crisp=None):
        self.size = size
        self.P, self.N, self.T = P, N, T
        self.cover = cover[..., 0] > 0.5
        self.valid = (np.abs(P).sum(-1) > 1e-9)      # inside the baked margin
        self.lips, self.nails, self.ears = attrs1[..., 0], attrs1[..., 1], attrs1[..., 2]
        self.scalp, self.region, self.beard_in = attrs2[..., 0], attrs2[..., 1], attrs2[..., 2]
        self.pores = nA                                            # Voronoi F1 per pore layer
        self.mot_mid, self.mot_low, self.broad = nB[..., 0], nB[..., 1], nB[..., 2]
        self.aniso_v, self.aniso_h, self.grain = nC[..., 0], nC[..., 1], nC[..., 2]
        self.speck, self.edge, self.vein_var = nD[..., 0], nD[..., 1], nD[..., 2]
        nE = nE if nE is not None else np.full_like(nD, 0.5)
        nF = nF if nF is not None else np.full_like(nD, 0.5)
        self.hb, self.mel, self.lump = nE[..., 0], nE[..., 1], nE[..., 2]
        self.peel, self.nose_f1, self.lipbump = nF[..., 0], nF[..., 1], nF[..., 2]
        nG = nG if nG is not None else np.full_like(nD, 0.5)
        self.hb_f1, self.hb_f2 = nG[..., 0], nG[..., 1]
        nH = nH if nH is not None else np.full_like(nD, 0.5)
        self.mid_f, self.mid_ff, self.fine_h = nH[..., 0], nH[..., 1], nH[..., 2]
        # sub-mesh residual of the sculpt layer's crisp band (metres along the normal), 0 without one
        self.crisp = crisp if crisp is not None else np.zeros(P.shape[:2], np.float32)
        self.ao = ao[..., 0]
        # derivatives of P along the image axes (metres per texel)
        self.Pu = np.zeros_like(P)
        self.Pv = np.zeros_like(P)
        self.Pu[:, 1:-1] = (P[:, 2:] - P[:, :-2]) * 0.5
        self.Pv[1:-1, :] = (P[2:, :] - P[:-2, :]) * 0.5
        self.tex_m = np.maximum(np.linalg.norm(self.Pu, axis=-1), 1e-6)   # metres per texel (u)

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


# --- sculpt crisp band (T12) ------------------------------------------------------------------

# The sculpt layer's crisp band (head_sculpt.refine: sharp - soft of the bony fields) is applied
# per vertex on the dense face (~2-2.5 mm spacing); what the mesh cannot hold between its vertices
# is the analytic field at each texel minus the field interpolated from the vertices. That residual
# goes into the skin height (game normal map and hero displacement). The vertex values are baked
# through an attribute (offset-encoded, CRISP_ENC metres per unit) so the interpolation is exactly
# the rasteriser's.
CRISP_ENC = 0.02
CRISP_MAX = 0.0008


def _crisp_fields(st, co, nrm, ears_co):
    """(sharp - soft) . n of the sculpt fields at points co (object space), metres. The ear points
    are prepended so ear_front (zygoma, ramus) finds the same ear as on the mesh."""
    from . import head_sculpt as hs
    c = st["cfg"]
    w = c["base_spacing_mm"] * hs.MM
    P = np.concatenate([ears_co, co])
    Nn = np.concatenate([np.zeros_like(ears_co), nrm])
    E = np.zeros(len(P), bool)
    E[:len(ears_co)] = True
    d = hs.fields(st["anchors"], P, Nn, st["eye_c"], E, c["fields"], 0.0, st.get("vault")) \
        - hs.fields(st["anchors"], P, Nn, st["eye_c"], E, c["fields"], w, st.get("vault"))
    return (d[len(ears_co):] * nrm).sum(1)


def crisp_vertex(b, body, lab):
    """Per-vertex attribute values (encoded field, selection weight), or None without a sculpt
    state. Selection as head_sculpt.refine: face and head labels, no lips."""
    st = getattr(b, "sculpt_state", None)
    if not st or lab is None:
        return None
    co = head_refine.coords(body)
    nrm = head_refine.normals(body)
    ears = head_refine.group_weights(body, "ears") > 0
    sel = ((lab == "face") | (lab == "head")) & ~(head_refine.group_weights(body, "lips") > 0)
    s = _crisp_fields(st, co, nrm, co[ears]) * sel
    mw = np.array(body.matrix_world, np.float64)
    head_c = mw[:3, :3] @ co[sel].mean(0) + mw[:3, 3]
    b._crisp_ctx = {"st": st, "ears_co": co[ears], "mw_inv": np.array(body.matrix_world.inverted(), np.float64),
                    "head_c": head_c}
    return (0.5 + s / CRISP_ENC).astype(np.float32), sel.astype(np.float32)


def crisp_texels(b, m, a3, chunk=1_000_000):
    """Residual height (s, s) in metres: the analytic crisp band at each texel, weighted by the
    interpolated selection, minus the vertex interpolation."""
    ctx = getattr(b, "_crisp_ctx", None)
    out = np.zeros(m.P.shape[:2], np.float32)
    if ctx is None:
        return out, None
    t = time.perf_counter()
    s_v = (a3[..., 0] - 0.5) * CRISP_ENC
    w = np.clip(a3[..., 1], 0, 1)
    # only texels on the head itself (some atlas texels far from it carry a stray selection weight
    # with no field value: a 10 mm "residual" at the legs in the first bake)
    head_c = np.asarray(ctx["head_c"], np.float32)
    where = m.valid & (w > 1e-3) & (np.linalg.norm(m.P - head_c, axis=-1) < 0.17)
    mi = ctx["mw_inv"]
    P = m.P[where].astype(np.float64) @ mi[:3, :3].T + mi[:3, 3]
    N = m.N[where].astype(np.float64) @ mi[:3, :3].T
    N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-9)
    a = np.empty(len(P), np.float64)
    for i in range(0, len(P), chunk):
        a[i:i + chunk] = _crisp_fields(ctx["st"], P[i:i + chunk], N[i:i + chunk], ctx["ears_co"])
    # bounded like the hero displacement (max_vertex_displacement 1 mm)
    out[where] = np.clip(w[where] * a - s_v[where], -CRISP_MAX, CRISP_MAX).astype(np.float32)
    r = out[where]
    stats = {"texels": int(where.sum()), "seconds": round(time.perf_counter() - t, 1),
             "p1_mm": round(float(np.percentile(r, 1)) * 1000, 4), "p99_mm": round(float(np.percentile(r, 99)) * 1000, 4),
             "min_mm": round(float(r.min()) * 1000, 4), "max_mm": round(float(r.max()) * 1000, 4)}
    print(f"[skin] crisp band residual: {stats}", flush=True)
    return out, stats


# --- T22 hand and neck field residual ----------------------------------------------------------

# The hand fields (hand_forms.apply: head_sculpt.hand_field on the hands and wrists) and the neck
# fields (head_sculpt.neck, times the collar weight) are geometry at the vertices; what the mesh
# cannot hold goes into the skin height as the field's high-pass at each texel: the analytic field
# minus its texture-space blur at about the vertex spacing (T22_BLUR_M). The vertex-interpolation
# residual the crisp band uses was tried first (t22-a1): against smooth-shaded geometry it bakes
# the triangles' piecewise-linear error into the normal map, a zigzag along every vein and
# tendon. Hands: the hands map; neck: the head map. The attribute pair (encoded vertex field,
# weight) carries the collar weight to the texels; it is piecewise linear there, so it is blurred
# (T22_W_BLUR_M) before it scales the field, or the triangles show as facets (t22-a2, the neck).
# On the hands only the terms finer than the mesh go to the map (T22_HAND_MAP_TERMS: the veins
# and the palmar flexor cords); the high-pass of the broad terms (knuckles, tendons) sharpened
# geometry that already holds them into hard creases (t22-a2).
T22_MAX = 0.0010
T22_BLUR_M = {"hands": 0.003, "head": 0.004}
T22_MAP_K = {"hands": 0.6, "head": 1.0}   # the veins: half in the mesh already (t22-a3 read as beads at 1.0)
T22_W_BLUR_M = {"hands": 0.002, "head": 0.004}
T22_HAND_MAP_TERMS = ("vein_mm", "flexor_mm")
T22_HAND_AMPS = ("knuckle_mm", "valley_mm", "gutter_mm", "tendon_mm", "thumb_mm", "snuff_mm", "pip_mm", "dip_mm",
                 "joint_mm", "shaft_mm", "breadth_ulnar_mm", "breadth_radial_mm", "wrist_flat_mm", "wrist_side_mm",
                 "ulnar_mm", "radial_mm", "flexor_mm", "vein_mm")


def t22_vertex(b, body):
    """(encoded field, weight) per vertex, or None when neither T22 stage ran."""
    from . import hand_forms
    from . import head_sculpt as hs
    hs_state, nk = getattr(b, "t22_hands", None), getattr(b, "t22_neck", None)
    if hs_state is None and nk is None:
        return None
    co = head_refine.coords(body)
    nrm = head_refine.normals(body)
    s = np.zeros(len(co))
    w = np.zeros(len(co))
    if hs_state is not None:
        lab, dom = head_refine.classify(body, b.armature())
        sel = hand_forms.field_verts(lab, dom, co, hs_state["hf"])
        s[sel] = hs.hand_field(co[sel], nrm[sel], hs_state["hf"], hs_state["cfg"], hs_state["paths"])
        w[sel] = 1.0
    if nk is not None:
        v = nk["verts"]
        s[v] = hs.neck_field(co[v], nrm[v], nk["anchors"], nk["cfg"]) * nk["w"]
        w[v] = nk["w"]
    b._t22_ctx = {"mw_inv": np.array(body.matrix_world.inverted(), np.float64)}
    return (0.5 + s / CRISP_ENC).astype(np.float32), w.astype(np.float32)


def t22_texels(b, m, a4, key, chunk=500_000):
    """Residual height (metres) on one map: 'hands' (hand fields) or 'head' (neck fields)."""
    from . import head_sculpt as hs
    out = np.zeros(m.P.shape[:2], np.float32)
    ctx = getattr(b, "_t22_ctx", None)
    st = getattr(b, "t22_hands" if key == "hands" else "t22_neck", None)
    if ctx is None or st is None:
        return out, None
    t = time.perf_counter()
    s_v = (a4[..., 0] - 0.5) * CRISP_ENC
    w = np.clip(a4[..., 1], 0, 1)
    where = m.valid & (w > 1e-3)
    if key == "head":
        # the neck only (texels in the head map near a neck vertex's weight; the face is far)
        where &= m.P[..., 2] < max(st["anchors"][1.0]["lobe"][2], st["anchors"][-1.0]["lobe"][2]) + 0.01
    mi = ctx["mw_inv"]
    P = m.P[where].astype(np.float64) @ mi[:3, :3].T + mi[:3, 3]
    N = m.N[where].astype(np.float64) @ mi[:3, :3].T
    N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-9)
    a = np.empty(len(P), np.float64)
    hcfg = {k: (v if (k not in T22_HAND_AMPS or k in T22_HAND_MAP_TERMS) else 0.0) for k, v in st["cfg"].items()}
    for i in range(0, len(P), chunk):
        sl = slice(i, i + chunk)
        if key == "hands":
            a[sl] = hs.hand_field(P[sl], N[sl], st["hf"], hcfg, st["paths"])
        else:
            a[sl] = hs.neck_field(P[sl], N[sl], st["anchors"], st["cfg"])
    texel = float(np.median(m.tex_m[where])) if where.any() else 1e-3
    ws, _ = _masked_blur(np.where(m.valid, w, 0.0).astype(np.float64), m.valid, T22_W_BLUR_M[key] / max(texel, 1e-6))
    g = np.zeros(m.P.shape[:2], np.float64)
    g[where] = np.clip(ws[where], 0, 1) * a
    low, _ = _masked_blur(g, m.valid, T22_BLUR_M[key] / max(texel, 1e-6))
    r = (g - low)[where]
    out[where] = np.clip(r * T22_MAP_K[key], -T22_MAX, T22_MAX).astype(np.float32)
    rr = out[where]
    stats = {"texels": int(where.sum()), "seconds": round(time.perf_counter() - t, 1), "texel_mm": round(texel * 1000, 4),
             "vertex_rms_mm": round(float(np.sqrt(np.mean(s_v[where] ** 2))) * 1000, 4) if where.any() else 0.0,
             "p1_mm": round(float(np.percentile(rr, 1)) * 1000, 4) if len(rr) else 0.0,
             "p99_mm": round(float(np.percentile(rr, 99)) * 1000, 4) if len(rr) else 0.0}
    print(f"[skin] T22 {key} residual: {stats}", flush=True)
    return out, stats


def eye_spheres(b, body, eyes):
    """[(centre world, radius m)] of the globes the game ships: the sculpt layer's eye spheres
    (head_sculpt eye_c, which eyes_hq ships), else a back-half sphere fit of the eye mesh."""
    st = getattr(b, "sculpt_state", None)
    mw = np.array(body.matrix_world, np.float64)
    if st and st.get("eye_c"):
        return [([float(x) for x in mw[:3, :3] @ np.asarray(c_, np.float64) + mw[:3, 3]], float(r_))
                for c_, r_ in (st["eye_c"][1.0], st["eye_c"][-1.0])]
    if eyes is None:
        return None
    from . import head_measure
    E = np.array([(eyes.matrix_world @ v.co)[:] for v in eyes.data.vertices])
    return [([float(x) for x in c_], float(r_)) for c_, r_ in
            (head_measure.eye_sphere(E[E[:, 0] > 0]), head_measure.eye_sphere(E[E[:, 0] < 0]))]


def save_cache(path, m, extra):
    """Dev cache of the head bake inputs (env SKIN_BAKE_CACHE): skin_synth re-runs on it outside Blender."""
    def f16(*a):
        return np.stack(a, -1).astype(np.float16) if len(a) > 1 else np.asarray(a[0], np.float16)
    np.savez(path, P=m.P.astype(np.float32), N=m.N.astype(np.float32), T=m.T.astype(np.float32),
             cover=m.cover, valid=m.valid, attrs1=f16(m.lips, m.nails, m.ears),
             attrs2=np.stack([m.scalp, m.region, m.beard_in], -1).astype(np.float32),
             nA=f16(m.pores), nB=f16(m.mot_mid, m.mot_low, m.broad), nC=f16(m.aniso_v, m.aniso_h, m.grain),
             nD=f16(m.speck, m.edge, m.vein_var), nE=f16(m.hb, m.mel, m.lump), nF=f16(m.peel, m.nose_f1, m.lipbump),
             nG=f16(m.hb_f1, m.hb_f2, m.hb_f2), nH=f16(m.mid_f, m.mid_ff, m.fine_h), ao=f16(m.ao),
             crisp=m.crisp.astype(np.float32), extra=np.array(repr(extra)))
    print(f"[skin] bake cache -> {path}", flush=True)


# --- curvature (engine pre-integrated SSS, T6) -------------------------------------------------

# Encoded mean curvature: v = clamp(kappa / CURV_KMAX, 0, 1), kappa in 1/m (convex > 0), so
# v = 1 is a 1 cm radius and v = 0 flat or concave. The engine's SSS LUT (web/src/character/
# materials/sss.ts) is indexed by the same v.
CURV_KMAX = 100.0
CURV_BLUR_M = 0.004      # curvature at the scale the hero SSS radii act on (3.4 / 0.75 / 0.34 mm)
CURV_PX = {"head": 1024, "hands": 512}


def _masked_blur(a, valid, r):
    """Normalised separable box^3 blur of a over valid texels (radius r px)."""
    r = max(1, int(round(r)))
    w = valid.astype(np.float64)
    num, den = a * w, w
    for _ in range(3):
        for ax in (0, 1):
            num = _box1(num, r, ax)
            den = _box1(den, r, ax)
    return np.where(den > 1e-6, num / np.maximum(den, 1e-6), 0.0), den


def _box1(x, r, ax):
    pad = [(0, 0), (0, 0)]
    pad[ax] = (r + 1, r)
    c = np.cumsum(np.pad(x, pad, mode="edge"), axis=ax)
    if ax == 0:
        return (c[2 * r + 1:, :] - c[:-2 * r - 1, :]) / (2 * r + 1)
    return (c[:, 2 * r + 1:] - c[:, :-2 * r - 1]) / (2 * r + 1)


def curvature(m, out_px):
    """Mean curvature of the baked surface (1/m, convex > 0) from the position
    and smooth-normal bakes: k = 0.5 (dN/du . dP/du / |dP/du|^2 + same in v),
    1 / r on a sphere of radius r. Blurred over CURV_BLUR_M, filled into the UV
    margin, box-downsampled to out_px. Returns (encoded v in [0, 1], stats)."""
    P, N = m.P.astype(np.float32), m.N.astype(np.float32)
    ok = m.valid & m.cover
    f0 = max(1, P.shape[0] // 2048)       # 4 mm curvature needs no 4k grid (and 4k float64 is GBs)
    if f0 > 1:
        s0 = P.shape[0] // f0
        P = P[:s0 * f0, :s0 * f0].reshape(s0, f0, s0, f0, 3).mean(axis=(1, 3))
        N = N[:s0 * f0, :s0 * f0].reshape(s0, f0, s0, f0, 3).mean(axis=(1, 3))
        ok = ok[:s0 * f0, :s0 * f0].reshape(s0, f0, s0, f0).all(axis=(1, 3))
    ok3 = ok.copy()
    ok3[1:-1, :] &= ok[2:, :] & ok[:-2, :]
    ok3[:, 1:-1] &= ok[:, 2:] & ok[:, :-2]
    Pu = np.zeros_like(P)
    Pv = np.zeros_like(P)
    Nu = np.zeros_like(N)
    Nv = np.zeros_like(N)
    Pu[:, 1:-1] = (P[:, 2:] - P[:, :-2]) * 0.5
    Pv[1:-1, :] = (P[2:, :] - P[:-2, :]) * 0.5
    Nu[:, 1:-1] = (N[:, 2:] - N[:, :-2]) * 0.5
    Nv[1:-1, :] = (N[2:, :] - N[:-2, :]) * 0.5
    pu2 = (Pu * Pu).sum(-1)
    pv2 = (Pv * Pv).sum(-1)
    ok3 &= (pu2 > 1e-14) & (pv2 > 1e-14)
    k = 0.5 * ((Nu * Pu).sum(-1) / np.maximum(pu2, 1e-14) + (Nv * Pv).sum(-1) / np.maximum(pv2, 1e-14))
    k = np.clip(np.where(ok3, k, 0.0), -500.0, 500.0)
    texel_m = float(np.median(np.sqrt(pu2[ok3]))) if ok3.any() else 1e-3
    kb, den = _masked_blur(k, ok3, CURV_BLUR_M / max(texel_m, 1e-6))
    # fill the margin outward (the runtime samples bilinear + mips across island edges)
    filled, _ = _masked_blur(kb, den > 1e-3, 8)
    kb = np.where(den > 1e-3, kb, filled)
    f = kb.shape[0] // out_px
    if f > 1:
        kb = kb[:out_px * f, :out_px * f].reshape(out_px, f, out_px, f).mean(axis=(1, 3))
    v = np.clip(kb / CURV_KMAX, 0.0, 1.0)
    face = kb[kb != 0]
    stats = {"px": int(v.shape[0]), "texel_mm": round(texel_m * 1000, 3), "blur_mm": CURV_BLUR_M * 1000,
             "kmax_per_m": CURV_KMAX, "v_mean": round(float(v.mean()), 4),
             "k_p50_per_m": round(float(np.percentile(face, 50)), 2) if face.size else None,
             "k_p95_per_m": round(float(np.percentile(face, 95)), 2) if face.size else None}
    return v, stats


def write_curvature(out_dir, key, v):
    """skin_<key>_curvature.png next to the GLB (grey, linear data, glTF row order)."""
    from .export import _png_rgb8
    name = f"skin_{key}_curvature.png"
    _png_rgb8(os.path.join(out_dir, name), np.repeat(v[::-1, :, None], 3, axis=2))
    return name


# --- T17 detail tiles, cavity, thickness (bench/m1/v4/checkpoint-3.md §2.2) --------------------

# Two tiled 512^2 tangent-space normal tiles the engine repeats over the skin UVs (the 4k maps are
# 0.13-0.25 mm/texel, so pores are 1-2 texels there and the mip chain erases them; checkpoint-3 §2.2):
#   pore   pits at a ~1.5 mm spacing (a jittered 16 x 16 grid over 24 mm, 15 % of the sites empty),
#          radius 0.12-0.28 mm log-uniform, slightly elliptic, each in a shallow funnel
#   micro  the skin's surface relief: furrows round ~0.3 x 0.23 mm plateaus (Voronoi edges on a
#          20 x 26 jittered grid over 6 mm), broken by a periodic low noise, plus a fine grain
# RGB = normal XY (glTF +Y = +v) and the openness (B: 1 inside a pore pit / a furrow), so the engine
# can occlude the specular and roughen the pits with the same texel. Rows are Blender's (row 0 = v 0);
# the PNG sidecar is written top-down, as every glTF image. The hero (Cycles) displaces by the same
# pore tile (hero_material), so both renderers carry the same pore field.
MM_ = 0.001
DETAIL = {
    "px": 512,
    "pore_tile_mm": 24.0, "pore_cells": 16, "pore_empty": 0.15, "pore_jitter": 0.42,
    "pore_r_mm": (0.12, 0.28), "pore_depth_mm": 0.05, "pore_aspect": (1.0, 1.45),
    "pore_funnel": 3.2, "pore_funnel_depth": 0.45,
    "pore_undulation_mm": 0.006, "pore_undulation_px": 7.0,   # soft ~1 mm domes between the pores
    "micro_tile_mm": 6.0, "micro_cells": (20, 26), "micro_jitter": 0.45,
    "micro_depth_mm": 0.012, "micro_w_mm": 0.022, "micro_break": 0.6, "micro_grain_mm": 0.003,
    "normal_gain": 1.0, "seed": 1717,
    # per-region pore-tile weight from the synth's pore mask (nose, cheek, forehead)
    "pore_region_gain": (1.0, 0.85, 0.6),
    # thickness: inside-AO distance (mm): t = D sqrt(AO) for a slab thinner than D
    "thick_dist_mm": 10.0, "thick_samples": 24,
    "lid_mm": (5.0, 9.0),      # skin within 5 (fully) to 9 mm of an eye sphere: no transmission (the eyeball)
    "detail_px": {"head": 1024, "hands": 512},
    # T21 stubble tile (layer 2 of the engine's tile array; its weight is the detail map's alpha, written by
    # hair_beard.paint_underlayer from the beard + stubble roots): ~100 stubs / cm^2 on a jittered grid, each
    # a cut shaft lying out of its follicle (a capsule len x w, raised h, aimed down the UV v +- dir_sigma),
    # 10 % of the sites empty; B = the shaft's coverage (dark in the albedo), RG its normal
    "stubble_tile_mm": 10.0, "stubble_cells": 10, "stubble_jitter": 0.45, "stubble_empty": 0.1,
    "stubble_len_mm": (0.35, 0.9), "stubble_w_mm": (0.07, 0.11), "stubble_h_mm": 0.035,
    "stubble_dir_sigma_deg": 35.0, "stubble_follicle_mm": 0.07,
}


def _periodic_noise(rng, n, sigma_px):
    """Tileable smooth noise (n x n), zero mean, unit std: white noise low-passed in the FFT domain."""
    w = rng.standard_normal((n, n))
    f = np.fft.fftfreq(n)
    k2 = f[:, None] ** 2 + f[None, :] ** 2
    a = np.real(np.fft.ifft2(np.fft.fft2(w) * np.exp(-2 * (np.pi * sigma_px) ** 2 * k2)))
    return (a - a.mean()) / max(a.std(), 1e-9)


def _cells(rng, n, nx, ny, jitter):
    """Per pixel of an n x n tile: the 9 neighbouring jittered grid sites (toroidal), as
    (dx, dy) in tile units from the pixel and the site index (iy * nx + ix)."""
    ox = 0.5 + rng.uniform(-jitter, jitter, (ny, nx))
    oy = 0.5 + rng.uniform(-jitter, jitter, (ny, nx))
    t = (np.arange(n) + 0.5) / n
    X, Y = np.meshgrid(t, t, indexing="xy")          # X along columns (u), Y along rows (v)
    cx = np.floor(X * nx).astype(np.int64)
    cy = np.floor(Y * ny).astype(np.int64)
    out = []
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            ix, iy = (cx + dx) % nx, (cy + dy) % ny
            sx = (cx + dx + ox[iy, ix]) / nx - X
            sy = (cy + dy + oy[iy, ix]) / ny - Y
            out.append((sx, sy, iy * nx + ix))
    return out


def _normals(h_mm, texel_mm, gain=1.0):
    """Tangent-space normal (+X = +u along columns, +Y = +v along rows) of a periodic height."""
    du = (np.roll(h_mm, -1, 1) - np.roll(h_mm, 1, 1)) / (2 * texel_mm)
    dv = (np.roll(h_mm, -1, 0) - np.roll(h_mm, 1, 0)) / (2 * texel_mm)
    n = np.stack([-du * gain, -dv * gain, np.ones_like(h_mm)], -1)
    return n / np.linalg.norm(n, axis=-1, keepdims=True)


def detail_tiles(d=DETAIL):
    """{'pore': (h_mm, rgb), 'micro': (h_mm, rgb)}: the two tiles, deterministic (d['seed'])."""
    rng = np.random.default_rng(d["seed"])
    n = d["px"]
    # ---- pore tile
    T = d["pore_tile_mm"]
    nc = d["pore_cells"]
    m = nc * nc
    lr = np.log(d["pore_r_mm"])
    rad = np.exp(rng.uniform(lr[0], lr[1], m))
    depth = d["pore_depth_mm"] * (rad / d["pore_r_mm"][1]) ** 0.7 * rng.uniform(0.6, 1.2, m)
    depth[rng.uniform(0, 1, m) < d["pore_empty"]] = 0.0
    ang = rng.uniform(0, np.pi, m)
    asp = rng.uniform(*d["pore_aspect"], m)
    h = np.zeros((n, n))
    open_ = np.zeros((n, n))
    for sx, sy, idx in _cells(rng, n, nc, nc, d["pore_jitter"]):
        x, y = sx * T, sy * T
        ca, sa = np.cos(ang[idx]), np.sin(ang[idx])
        a_ = (x * ca + y * sa) / asp[idx]
        b_ = -x * sa + y * ca
        dist = np.hypot(a_, b_)
        r = rad[idx]
        pit = 1 - smoothstep(0.0, r, dist)
        fun = 1 - smoothstep(0.0, r * d["pore_funnel"], dist)
        hi = -depth[idx] * ((1 - d["pore_funnel_depth"]) * pit ** 1.5 + d["pore_funnel_depth"] * fun ** 2)
        h = np.minimum(h, hi)
        open_ = np.maximum(open_, pit * (depth[idx] > 0))
    h = h + d["pore_undulation_mm"] * _periodic_noise(rng, n, d["pore_undulation_px"])
    pore_n = _normals(h, T / n, d["normal_gain"])
    pore = np.concatenate([pore_n[..., :2] * 0.5 + 0.5, open_[..., None]], -1).astype(np.float32)
    # ---- micro tile
    Tm = d["micro_tile_mm"]
    mx, my = d["micro_cells"]
    f1 = np.full((n, n), np.inf)
    f2 = np.full((n, n), np.inf)
    for sx, sy, _ in _cells(rng, n, mx, my, d["micro_jitter"]):
        dist = np.hypot(sx * Tm, sy * Tm)
        f2 = np.where(dist < f1, f1, np.minimum(f2, dist))
        f1 = np.minimum(f1, dist)
    edge = 0.5 * (f2 - f1)                                   # mm to the nearest cell border
    brk = 1 - d["micro_break"] * (1 - smoothstep(-0.6, 0.6, _periodic_noise(rng, n, n / 10)))
    fur = (1 - smoothstep(0.0, d["micro_w_mm"], edge)) * brk
    hm = -d["micro_depth_mm"] * fur + d["micro_grain_mm"] * _periodic_noise(rng, n, 1.2)
    micro_n = _normals(hm, Tm / n, d["normal_gain"])
    micro = np.concatenate([micro_n[..., :2] * 0.5 + 0.5, fur[..., None]], -1).astype(np.float32)
    out = {"pore": (h.astype(np.float32), pore), "micro": (hm.astype(np.float32), micro)}
    out["stubble"] = stubble_tile(rng, d)
    return out


def stubble_tile(rng, d=DETAIL):
    """T21: the stubble tile (h_mm, rgb): RG normal, B shaft coverage (see DETAIL stubble_*)."""
    n = d["px"]
    T = d["stubble_tile_mm"]
    nc = d["stubble_cells"]
    m = nc * nc
    L = rng.uniform(*d["stubble_len_mm"], m)
    w = rng.uniform(*d["stubble_w_mm"], m)
    ang = -np.pi / 2 + np.radians(d["stubble_dir_sigma_deg"]) * rng.standard_normal(m)
    live = rng.uniform(0, 1, m) >= d["stubble_empty"]
    texel = T / n
    h = np.zeros((n, n))
    cov = np.zeros((n, n))
    for sx, sy, idx in _cells(rng, n, nc, nc, d["stubble_jitter"]):
        x, y = -sx * T, -sy * T                    # pixel relative to the follicle (mm)
        ca, sa = np.cos(ang[idx]), np.sin(ang[idx])
        along = np.clip(x * ca + y * sa, 0.0, L[idx])
        dist = np.hypot(x - along * ca, y - along * sa)
        r = 0.5 * w[idx]
        inside = np.clip(1 - (dist / r) ** 2, 0, 1)
        # the shaft rises out of the follicle and lies on the skin toward its cut end
        lift = 1 - 0.5 * along / L[idx]
        hi = d["stubble_h_mm"] * np.sqrt(inside) * lift * live[idx]
        h = np.maximum(h, hi)
        c = np.clip((r - dist) / texel + 0.5, 0, 1) * live[idx]
        fol = np.clip((d["stubble_follicle_mm"] - np.hypot(x, y)) / texel + 0.5, 0, 1) * live[idx]
        cov = np.maximum(cov, np.maximum(c, fol))
    nrm = _normals(h, texel, d["normal_gain"])
    rgb = np.concatenate([nrm[..., :2] * 0.5 + 0.5, cov[..., None]], -1).astype(np.float32)
    return h.astype(np.float32), rgb


def write_png(path, rgb):
    """8-bit RGB PNG of a Blender-convention (row 0 = v 0) array, written top-down (glTF rows)."""
    from .export import _png_rgb8
    _png_rgb8(path, rgb[::-1])
    return os.path.basename(path)


def cavity_map(m, hgt, k_fine, k_broad, blur_m=0.0015):
    """Specular cavity (1 = open, 0 = deep): the Laplacian of the game height at the texel (pores,
    fine lines) and over ~blur_m (creases), clipped. Rides in ORM blue (pack_orm)."""
    lap = np.clip(m.cavity(hgt), 0, None)
    texel = float(np.median(m.tex_m[m.valid])) if m.valid.any() else 1e-3
    hb, _ = _masked_blur(hgt.astype(np.float64), m.valid, blur_m / max(texel, 1e-6))
    lapb = np.clip(m.cavity(hb.astype(np.float32)), 0, None)
    return np.clip(1 - np.clip(lap * k_fine, 0, 1) - np.clip(lapb * k_broad, 0, 1), 0, 1).astype(np.float32)


def _ao_inside(dist_m):
    """Bake source: the Ambient Occlusion node's 'inside' mode on this object only, D = dist_m: the
    fraction of cosine-weighted rays into the body that travel D without leaving it. A slab of
    thickness t < D gives AO = (t / D)^2, so t = D sqrt(AO) (thin: ears, alae, lids)."""
    def f(nt, i):
        ao = nt.nodes.new("ShaderNodeAmbientOcclusion")
        ao.inside = True
        ao.only_local = True
        ao.samples = 16
        ao.inputs["Distance"].default_value = dist_m
        comb = nt.nodes.new("ShaderNodeCombineColor")
        for k in range(3):
            nt.links.new(ao.outputs["AO"], comb.inputs[k])
        return comb.outputs[0]
    return f


def detail_map(syn, thick_ao, key, px, d=DETAIL):
    """Engine detail map (px^2): R pore-tile weight, G micro-tile weight, B thickness AO (t = D sqrt)."""
    mp = syn["mask_pores"]
    g = np.asarray(d["pore_region_gain"], np.float32)
    pore_w = np.clip((mp * g).sum(-1), 0, 1) if key == "head" else np.clip(mp[..., 1], 0, 1)
    micro_w = np.clip(syn["mask_hero"][..., 2], 0, 1)
    rgb = np.stack([pore_w, micro_w, np.clip(thick_ao, 0, 1)], -1)
    f = rgb.shape[0] // px
    if f > 1:
        rgb = rgb[:px * f, :px * f].reshape(px, f, px, f, 3).mean(axis=(1, 3))
    return rgb.astype(np.float32)


def uv_mm(m):
    """Millimetres per UV unit over the covered texels (median; MPFB islands vary about +-30 %)."""
    ok = m.valid & m.cover
    return float(np.median(m.tex_m[ok])) * m.size * 1000.0 if ok.any() else None


def pack_orm(b, out):
    """The skin ORM images (R occlusion, G roughness, B cavity) into the GLB as written: the glTF
    exporter re-composes a metallicRoughness image from the sockets it can trace and fills B
    (metallic, unlinked in skin_material) with white, so the cavity is lost. The image keeps its
    name; its bytes are replaced in place and every later bufferView shifts. metallicFactor stays 0."""
    names = getattr(b, "skin_orm", None)
    if not names:
        return None
    from . import export, hair_strand_raster as hsr
    doc, bin_ = export._read_glb(out)
    done = []
    for im in doc.get("images", []):
        if im.get("name") not in names or "bufferView" not in im:
            continue
        img = bpy.data.images.get(im["name"])
        if img is None:
            continue
        png = hsr.image_png_bytes(img)
        bv = doc["bufferViews"][im["bufferView"]]
        o0, n0 = bv.get("byteOffset", 0), bv["byteLength"]
        pad = (-len(png)) % 4
        new = png + b"\x00" * pad
        old_span = n0 + ((-n0) % 4)
        bin_ = bytearray(bytes(bin_[:o0]) + new + bytes(bin_[o0 + old_span:]))
        delta = len(new) - old_span
        for v in doc["bufferViews"]:
            if v is not bv and v.get("byteOffset", 0) > o0:
                v["byteOffset"] = v.get("byteOffset", 0) + delta
        bv["byteLength"] = len(png)
        done.append(im["name"])
    for mat in doc.get("materials", []):
        if mat.get("name", "").startswith("skin_"):
            mat.setdefault("pbrMetallicRoughness", {})["metallicFactor"] = 0.0
    doc["buffers"][0]["byteLength"] = len(bin_)
    export._write_glb(out, doc, bin_)
    b.notes.setdefault("skin", {})["orm_cavity"] = done
    return done


def write_detail_sidecars(b, out_dir, tiles, details, uvmm, stats):
    """skin_detail.json + the tiles + per-part detail maps next to the GLB (engine runtime inputs)."""
    keys = [k for k in ("pore", "micro", "stubble") if k in tiles]
    files = {k: write_png(os.path.join(out_dir, f"skin_detail_{k}.png"), tiles[k][1]) for k in keys}
    parts = {}
    for key, rgb in details.items():
        fn = write_png(os.path.join(out_dir, f"skin_{key}_detail.png"), rgb)
        mm = uvmm.get(key)
        parts[f"skin_{key}"] = {"detail": fn, "uv_mm": round(mm, 2) if mm else None,
                                "pore_repeat": round(mm / DETAIL["pore_tile_mm"], 4) if mm else None,
                                "micro_repeat": round(mm / DETAIL["micro_tile_mm"], 4) if mm else None,
                                "stubble_repeat": round(mm / DETAIL["stubble_tile_mm"], 4) if mm and "stubble" in tiles else None}
    # T21: hair_beard.paint_underlayer rewrites the detail maps with the stubble density in alpha
    b.skin_detail_maps = {"dir": out_dir, "rgb": dict(details), "files": {k: parts[f"skin_{k}"]["detail"] for k in details}}
    # mean |n_xy|^2 of each tile: the slope variance the engine moves into roughness where it fades a tile
    var = {k: round(float(np.mean(np.sum((tiles[k][1][..., :2] * 2.0 - 1.0) ** 2, axis=-1))), 5) for k in ("pore", "micro")}
    rec = {"version": 1, "tiles": files, "materials": parts, "tile_slope_var": var,
           "pore_tile_mm": DETAIL["pore_tile_mm"], "pore_cells": DETAIL["pore_cells"],
           "micro_tile_mm": DETAIL["micro_tile_mm"], "micro_cells": list(DETAIL["micro_cells"]),
           "thick_dist_mm": DETAIL["thick_dist_mm"], "cavity_in_orm_b": True, "stats": stats,
           "stubble": ({"cells": DETAIL["stubble_cells"], "tile_mm": DETAIL["stubble_tile_mm"],
                        "mean_cov": round(float(tiles["stubble"][1][..., 2].mean()), 5),
                        "slope_var": round(float(np.mean(np.sum((tiles["stubble"][1][..., :2] * 2.0 - 1.0) ** 2, axis=-1))), 5)}
                       if "stubble" in tiles else None),
           "note": "tiles: RG = tangent-space normal XY (glTF +Y), B = pit / furrow openness; wrap REPEAT, "
                   "mipmapped; uv_tile = uv * repeat. detail map (part UV): R pore-tile weight, G micro-tile "
                   "weight, B inside-AO, thickness t = thick_dist_mm * sqrt(B). ORM blue = specular cavity."}
    with open(os.path.join(out_dir, "skin_detail.json"), "w") as f:
        json.dump(rec, f, indent=1)
    return ["skin_detail.json"] + list(files.values()) + [p["detail"] for p in parts.values()]


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


def make_float_image(name, values):
    """Packed float (EXR) data image; values (s, s) or (s, s, 3), unclamped."""
    s = values.shape[0]
    img = bpy.data.images.new(name, s, s, alpha=False, float_buffer=True, is_data=True)
    img.colorspace_settings.name = "Non-Color"
    px = np.zeros((s, s, 4), np.float32)
    if values.ndim == 2:
        px[..., :3] = values[..., None]
    else:
        px[..., :3] = values
    px[..., 3] = 1.0
    img.pixels.foreach_set(px.ravel())
    img.file_format = "OPEN_EXR"
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


def skin_material(name, albedo, orm, normal, sss, cavity=False):
    """glTF-side skin material. cavity: ORM blue is the T17 specular cavity, not metal: Metallic is
    left unlinked (0) and pack_orm restores the blue channel the exporter drops."""
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
    if not cavity:
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

def _eval_world_coords(obj):
    """World-space vertex positions of the evaluated mesh (what a bake sees)."""
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    try:
        n = len(me.vertices)
        co = np.empty(n * 3, np.float32)
        me.vertices.foreach_get("co", co)
        co = co.reshape(n, 3)
    finally:
        ev.to_mesh_clear()
    if n != len(obj.data.vertices):
        return None
    mw = np.array(obj.matrix_world, np.float32)
    return co @ mw[:3, :3].T + mw[:3, 3]


def mouth_corners(body):
    """World positions of the two commissures: the extreme lips-group vertices in x."""
    w = head_refine.group_weights(body, "lips")
    co = _eval_world_coords(body)
    if co is None or not (w > 0.5).any():
        return []
    lp = co[w > 0.5]
    out = []
    for sgn in (1.0, -1.0):
        k = np.argsort(-sgn * lp[:, 0])[:4]
        out.append([float(x) for x in lp[k].mean(0)])
    return out


def _mean_srgb(alb, mask):
    if not mask.any():
        return None
    return [round(float(x), 3) for x in linear_to_srgb(alb[mask]).mean(0)]


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
    cv = crisp_vertex(b, body, lab) if c.get("crisp", True) else None
    if cv is not None:
        set_attr(me, "sk_crisp", cv[0])
        set_attr(me, "sk_crisp_w", cv[1])
    tv = t22_vertex(b, body) if c.get("t22", True) else None
    if tv is not None:
        set_attr(me, "sk_t22", tv[0])
        set_attr(me, "sk_t22_w", tv[1])
    # The rest position the bakes see: the hero shader evaluates the same
    # procedural pores on it (pose-stable, and aligned with the game normal map).
    rest = _eval_world_coords(body)
    if rest is not None:
        a = me.attributes.get("hero_rest") or me.attributes.new("hero_rest", "FLOAT_VECTOR", "POINT")
        a.data.foreach_set("vector", np.ascontiguousarray(rest, np.float32).ravel())
    # hide everything but body + eyes for the AO bake
    hidden = []
    for o in b.meshes():
        if o not in (body, eyes) and not o.hide_render:
            o.hide_render = True
            hidden.append(o)
    bk = Baker(body, 2, bake_px, margin=int(c.get("margin_px", 16)))
    ns = skin_synth.NOISE_SPECS
    try:
        P = bk.run("pos", lambda nt, i: _geom(nt, i, "Position"))
        N = bk.run("nrm", lambda nt, i: _geom(nt, i, "Normal"))
        T = bk.run("tan", _tangent(uv))
        cover = bk.run("cover", _const, margin=0)
        a1 = bk.run("attr1", _attrs(("sk_lips", "sk_nails", "sk_ears")))
        a2 = bk.run("attr2", _attrs(("sk_scalp", "sk_region", "sk_beard")))
        nA = bk.run("noiseA", _noises(ns["noiseA"]))
        nB = bk.run("noiseB", _noises(ns["noiseB"]))
        nC = bk.run("noiseC", _noises(ns["noiseC"]))
        nD = bk.run("noiseD", _noises(ns["noiseD"]))
        nE = bk.run("noiseE", _noises(ns["noiseE"]))
        nF = bk.run("noiseF", _noises(ns["noiseF"]))
        nG = bk.run("noiseG", _noises(ns["noiseG"]))
        nH = bk.run("noiseH", _noises(ns["noiseH"]))
        a3 = bk.run("attr3", _attrs(("sk_crisp", "sk_crisp_w", None))) if cv is not None else None
        a4 = bk.run("attr4", _attrs(("sk_t22", "sk_t22_w", None))) if tv is not None else None
        ao = bk.run("ao", None, samples=int(c.get("ao_samples", 16)), bake_type="AO", down=int(c.get("ao_down", 2)))
        # T17: thickness for the engine's transmission (ears, alae, lids): inside AO at 1/4 size
        thick = bk.run("thick", _ao_inside(DETAIL["thick_dist_mm"] * MM_), samples=DETAIL["thick_samples"],
                       down=4) if c.get("detail", True) else None
    finally:
        bk.finish()
        for o in hidden:
            o.hide_render = False
    for n in ("sk_lips", "sk_nails", "sk_ears", "sk_scalp", "sk_region", "sk_crisp", "sk_crisp_w", "sk_t22", "sk_t22_w"):
        if me.attributes.get(n) is not None:
            me.attributes.remove(me.attributes[n])

    maps = [Maps(bake_px[i], P[i], N[i], T[i], cover[i], a1[i], a2[i], nA[i], nB[i], nC[i], nD[i], ao[i], nE[i], nF[i], nG[i],
                 nH[i]) for i in range(2)]
    crisp_stats = None
    if a3 is not None:
        maps[0].crisp, crisp_stats = crisp_texels(b, maps[0], a3[0])
    cl, cr = head_refine.eye_centres(eyes) if eyes is not None else (np.array([0.03, -0.13, 1.72]), np.array([-0.03, -0.13, 1.72]))
    hc = dict(skin_synth.DEFAULT_HEAD)
    hc.update(c.get("head") or {})
    hc["base"] = c.get("base", hc["base"])
    hc.setdefault("corners", mouth_corners(body))
    if "eye_spheres" not in hc:
        hc["eye_spheres"] = eye_spheres(b, body, eyes)
    if os.environ.get("SKIN_BAKE_CACHE"):
        save_cache(os.environ["SKIN_BAKE_CACHE"], maps[0],
                   {"cl": [float(x) for x in cl], "cr": [float(x) for x in cr], "hc": hc})
    head = skin_synth.synth_head(maps[0], hc, cl, cr)
    hh = dict(skin_synth.DEFAULT_HANDS)
    hh.update(c.get("hands") or {})
    hh["base"] = c.get("base", hh["base"])
    # Track G hook: A's hand synthesis plus the hand detail layer (hand_detail.py)
    hands = hand_detail.synth(maps[1], hh, head_refine.hand_frames(arm), head_refine.FINGERS,
                              ((b.cfg.get("hands") or {}).get("detail")), getattr(b, "t22_hands", None))
    t22_stats = {}
    if a4 is not None:
        # T22: the hand and neck fields' sub-vertex residual into both heights
        for key, i, syn in (("head", 0, head), ("hands", 1, hands)):
            r, t22_stats[key] = t22_texels(b, maps[i], a4[i], key)
            syn["hgt_game"] = (syn["hgt_game"] + r).astype(np.float32)
            syn["hgt_hero"] = (syn["hgt_hero"] + r).astype(np.float32)
    out_dir = b.out_dir if c.get("save_maps") else None
    imgs, hero_in = {}, {"body": body.name, "cfg": c}
    use_detail = c.get("detail", True)
    cav_stats = {}
    for key, m, syn, cc in (("head", maps[0], head, hc), ("hands", maps[1], hands, hh)):
        # T17: ORM blue = the specular cavity (pack_orm keeps it in the GLB; the engine reads it when
        # skin_detail.json says so); before T17 it was 0 and linked to Metallic
        cav = cavity_map(m, syn["hgt_game"], cc.get("cavity_fine", 0.0003), cc.get("cavity_broad", 0.0015)) \
            if use_detail else np.zeros_like(syn["rough"])
        if use_detail:
            sk = m.valid & m.cover
            cav_stats[key] = {"mean": round(float(cav[sk].mean()), 4), "p5": round(float(np.percentile(cav[sk], 5)), 4)}
        imgs[key] = {
            "albedo": make_image(f"skin_{key}_albedo", syn["albedo"], True, out_dir),
            "orm": make_image(f"skin_{key}_orm", np.stack([syn["occl"], syn["rough"], cav], -1), False, out_dir),
            "normal": make_image(f"skin_{key}_normal", m.normal_map(syn["hgt_game"]), False, out_dir),
        }
        # hero-only inputs: height in mm (lines; pores come from the shader), masks
        hero_in[key] = dict(imgs[key])
        if "albedo_hero" in syn:            # no plane paint in the hero albedo
            hero_in[key]["albedo"] = make_image(f"skin_{key}_hero_albedo", syn["albedo_hero"], True, out_dir)
        hero_in[key]["height_mm"] = make_float_image(f"skin_{key}_hero_height", syn["hgt_hero"] * 1000.0)
        hero_in[key]["mask_pores"] = make_image(f"skin_{key}_hero_pores", syn["mask_pores"], False, out_dir)
        hero_in[key]["mask_hero"] = make_image(f"skin_{key}_hero_masks", syn["mask_hero"], False, out_dir)
    b.skin_hero = hero_in
    curv = {}
    if getattr(b, "out_dir", None):
        for key, m in (("head", maps[0]), ("hands", maps[1])):
            v, st = curvature(m, CURV_PX[key])
            st["file"] = write_curvature(b.out_dir, key, v)
            curv[key] = st
    # T17 detail layer: the two tiles, the per-part detail maps (pore / micro weights, thickness), the
    # sidecar for the engine; the hero displaces by the same pore tile (hero_material)
    detail_stats = None
    if use_detail:
        tiles = detail_tiles()
        uvmm = {"head": uv_mm(maps[0]), "hands": uv_mm(maps[1])}
        details, thick_st = {}, {}
        for key, i, syn in (("head", 0, head), ("hands", 1, hands)):
            m = maps[i]
            ta = thick[i][..., 0] if thick is not None else np.ones(m.P.shape[:2], np.float32)
            texel = float(np.median(m.tex_m[m.valid])) if m.valid.any() else 1e-3
            ta, _ = _masked_blur(np.where(m.valid, ta, 1.0).astype(np.float64), m.valid, 0.0015 / max(texel, 1e-6))
            ta = np.where(m.valid, ta, 1.0).astype(np.float32)
            if key == "head":
                # the lids lie on the eyeball (another object, so not in the inside AO): no light reaches
                # them from behind; within lid_mm of an eye sphere the part counts as thick
                for c_, r_ in hc.get("eye_spheres") or ():
                    dd = np.linalg.norm(m.P - np.asarray(c_, np.float32), axis=-1) - float(r_)
                    lid = np.clip((DETAIL["lid_mm"][1] * MM_ - dd) / ((DETAIL["lid_mm"][1] - DETAIL["lid_mm"][0]) * MM_), 0, 1)
                    ta = (ta + (1.0 - ta) * lid).astype(np.float32)
            details[key] = detail_map(syn, ta, key, DETAIL["detail_px"][key])
            tmm = DETAIL["thick_dist_mm"] * np.sqrt(np.clip(ta[m.valid & m.cover], 0, 1))
            thick_st[key] = {"p5_mm": round(float(np.percentile(tmm, 5)), 2),
                             "p50_mm": round(float(np.percentile(tmm, 50)), 2),
                             "thin_lt4mm_pct": round(float(100 * (tmm < 4).mean()), 2)}
        detail_stats = {"uv_mm": {k: round(v, 2) if v else None for k, v in uvmm.items()}, "thickness": thick_st,
                        "cavity": cav_stats}
        if getattr(b, "out_dir", None):
            detail_stats["files"] = write_detail_sidecars(b, b.out_dir, tiles, details, uvmm, detail_stats)
        tile_img = make_float_image("skin_detail_pore_height", tiles["pore"][0])
        tile_img.use_fake_user = True
        hero_in["tile"] = {"image": tile_img,
                           "repeat": {k: (v / DETAIL["pore_tile_mm"] if v else None) for k, v in uvmm.items()},
                           "gain": tuple(DETAIL["pore_region_gain"])}
    sss = float(c.get("sss", 0.0))
    idx = [p.material_index for p in me.polygons]
    me.materials.clear()
    for key in ("head", "hands"):
        me.materials.append(skin_material(f"skin_{key}", imgs[key]["albedo"], imgs[key]["orm"], imgs[key]["normal"], sss,
                                          cavity=use_detail))
    restore_indices(me, idx)
    if use_detail:
        b.skin_orm = [imgs[k]["orm"].name for k in ("head", "hands")]
    face = maps[0].cover & (np.abs(maps[0].region - 0.5) < 0.05) & (maps[0].lips < 0.3)
    stats = {"sizes": bake_px, "seconds": round(time.perf_counter() - t0, 2),
             "height_mm": {k: [round(float(v["hgt_game"].min()) * 1000, 3), round(float(v["hgt_game"].max()) * 1000, 3)]
                           for k, v in (("head", head), ("hands", hands))},
             "albedo_mean_srgb": _mean_srgb(head["albedo"], maps[0].cover),
             "albedo_face_mean_srgb": _mean_srgb(head["albedo"], face),
             "hero_albedo_face_mean_srgb": _mean_srgb(head["albedo_hero"], face),
             "roughness_mean": round(float(head["rough"][maps[0].cover].mean()), 3),
             "roughness_face_mean": round(float(head["rough"][face].mean()), 3) if face.any() else None,
             "roughness_face_std": round(float(head["rough"][face].std()), 4) if face.any() else None,
             "roughness_face_std_rel": (round(float(head["rough"][face].std() / head["rough"][face].mean()), 4)
                                        if face.any() else None),
             "crisp": crisp_stats, "t22": t22_stats, "hero_rest": rest is not None, "curvature": curv,
             "detail": detail_stats}
    b.notes["skin"] = stats
    print(f"[skin] done in {stats['seconds']} s", flush=True)
    return stats


# --- hero (Cycles only; wired after the GLB export) --------------------------------------------

HERO = {
    "sss_radius": (1.0, 0.22, 0.10), "sss_scale": 0.0034, "sss_ior": 1.4, "sss_anisotropy": 0.8,
    "specular": 0.5, "ior": 1.4,
    "coat": 0.02, "coat_oil": 0.10, "coat_roughness": 0.28,
    "sheen": 0.1, "sheen_roughness": 0.4, "sheen_tint": (1.0, 0.93, 0.88),
    "pore_scale": 1.6, "pore_dark": 0.02, "pore_rough": 0.16,
    # pores and micro relief go to a shading-normal bump (x micro_bump over the
    # physical depth); each pore sits in a shallow funnel (dimple_r x its
    # radius, dimple_depth x its depth). Head only: the hands keep 1.0 and no funnel.
    "micro_bump": 1.5, "dimple_r": 2.6, "dimple_depth": 0.6,
    # cross-hatched tension furrows: line angle from horizontal (deg) and weight.
    # 0.5 mm spacing (the primary lines; the 0.15-0.3 mm secondary net is below
    # a pixel even in the 135 mm close-up, so the fine grain stands in for it)
    "micro_mm": 0.025, "micro_period_mm": 0.5, "micro_dirs": ((38.0, 1.0), (-42.0, 0.9), (85.0, 0.5)),
    "micro_width": 0.3, "micro_distort": 5.0, "micro_distort_scale": 0.5, "micro_break": 0.5,
    "micro_patch_scale": 700.0,
    "fine_mm": 0.004, "fine_scale": 20000.0,
    "rough_plateau": -0.03, "rough_furrow": 0.10,
    "dicing_px": 1.0, "max_subdivisions": 10,
    "displacement": True,
    # T17: the engine's pore tile (skin_tex.DETAIL) as micro-displacement in the hero height, x
    "tile_gain": 1.0,
}


def _node(nt, kind, x, y, **props):
    n = nt.nodes.new(kind)
    n.location = (x, y)
    for k, v in props.items():
        setattr(n, k, v)
    return n


def _math(nt, op, a, b, x, y):
    n = _node(nt, "ShaderNodeMath", x, y, operation=op)
    for i, v in enumerate((a, b)):
        if isinstance(v, (int, float)):
            n.inputs[i].default_value = v
        else:
            nt.links.new(v, n.inputs[i])
    return n.outputs[0]


def hero_material(name, im, hc, layers, tile=None):
    """One Principled (the hero rig's clay/normal passes swap the first one). tile: T17's pore tile
    (image of the tile height in mm, UV repeat, per-channel weights of the pore mask), added to the
    displaced height: micro-displacement at the pore scale, shared with the engine's detail normal."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    m.displacement_method = "BOTH" if hc["displacement"] else "BUMP"
    nt = m.node_tree
    p = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
    p.location, out.location = (400, 300), (800, 300)

    def tex(img, y):
        return _node(nt, "ShaderNodeTexImage", -900, y, image=img)
    ta = tex(im["albedo"], 600)
    sep = _node(nt, "ShaderNodeSeparateColor", -600, 300)
    nt.links.new(tex(im["orm"], 300).outputs["Color"], sep.inputs[0])
    mh = _node(nt, "ShaderNodeSeparateColor", -600, 0)
    nt.links.new(tex(im["mask_hero"], 0).outputs["Color"], mh.inputs[0])
    oil, fuzz, micro_w = mh.outputs["Red"], mh.outputs["Green"], mh.outputs["Blue"]

    p.subsurface_method = "RANDOM_WALK_SKIN"
    p.inputs["Subsurface Weight"].default_value = 1.0
    p.inputs["Subsurface Radius"].default_value = hc["sss_radius"]
    p.inputs["Subsurface Scale"].default_value = hc["sss_scale"]
    p.inputs["Subsurface IOR"].default_value = hc["sss_ior"]
    p.inputs["Subsurface Anisotropy"].default_value = hc["sss_anisotropy"]
    p.inputs["Specular IOR Level"].default_value = hc["specular"]
    p.inputs["IOR"].default_value = hc["ior"]
    coat = _node(nt, "ShaderNodeMath", -300, -100, operation="MULTIPLY_ADD")
    nt.links.new(oil, coat.inputs[0])
    coat.inputs[1].default_value = hc["coat_oil"]
    coat.inputs[2].default_value = hc["coat"]
    nt.links.new(coat.outputs[0], p.inputs["Coat Weight"])
    p.inputs["Coat Roughness"].default_value = hc["coat_roughness"]
    p.inputs["Coat IOR"].default_value = hc["ior"]
    nt.links.new(_math(nt, "MULTIPLY", fuzz, hc["sheen"], -300, -250), p.inputs["Sheen Weight"])
    p.inputs["Sheen Roughness"].default_value = hc["sheen_roughness"]
    p.inputs["Sheen Tint"].default_value = (*hc["sheen_tint"], 1.0)

    # displacement (mm): hero height - pores (Voronoi on the rest position) - micro relief
    rest = _node(nt, "ShaderNodeAttribute", -1500, -400, attribute_name="hero_rest", attribute_type="GEOMETRY")
    hgt = _node(nt, "ShaderNodeSeparateColor", -600, -400)
    nt.links.new(tex(im["height_mm"], -400).outputs["Color"], hgt.inputs[0])
    macro = hgt.outputs["Red"]
    total = None                                     # micro height (mm): pores, cross-hatch, grain
    mp = _node(nt, "ShaderNodeSeparateColor", -600, -700)
    nt.links.new(tex(im["mask_pores"], -700).outputs["Color"], mp.inputs[0])
    y = -1000
    opening = None                                   # 0..1 inside a pore, weighted by the region
    for ch, (scale, r, depth_mm) in zip(("Red", "Green", "Blue"), layers):
        if depth_mm <= 0:
            continue
        vo = _node(nt, "ShaderNodeTexVoronoi", -1200, y, feature="F1")
        vo.inputs["Scale"].default_value = scale
        vo.inputs["Randomness"].default_value = 1.0
        nt.links.new(rest.outputs["Vector"], vo.inputs["Vector"])
        mr = _node(nt, "ShaderNodeMapRange", -900, y, interpolation_type="SMOOTHSTEP")
        mr.inputs["From Min"].default_value = 0.0
        mr.inputs["From Max"].default_value = r
        mr.inputs["To Min"].default_value = depth_mm * hc["pore_scale"]
        mr.inputs["To Max"].default_value = 0.0
        nt.links.new(vo.outputs["Distance"], mr.inputs["Value"])
        pit = _math(nt, "MULTIPLY", mr.outputs["Result"], mp.outputs[ch], -600, y)
        total = _math(nt, "MULTIPLY", pit, -1.0, -300, y) if total is None else _math(nt, "SUBTRACT", total, pit, -300, y)
        op = _node(nt, "ShaderNodeMapRange", -900, y - 120, interpolation_type="SMOOTHSTEP")
        op.inputs["From Min"].default_value = 0.0
        op.inputs["From Max"].default_value = r * 0.85
        op.inputs["To Min"].default_value = 1.0
        op.inputs["To Max"].default_value = 0.0
        nt.links.new(vo.outputs["Distance"], op.inputs["Value"])
        o = _math(nt, "MULTIPLY", op.outputs["Result"], mp.outputs[ch], -600, y - 120)
        opening = o if opening is None else _math(nt, "MAXIMUM", opening, o, -450, y - 120)
        # the funnel round the opening: a wider, shallow dimple, so a pore reads
        # in a highlight at a distance where the opening itself is sub-pixel
        if hc["dimple_depth"] > 0:
            dm = _node(nt, "ShaderNodeMapRange", -900, y - 60, interpolation_type="SMOOTHSTEP")
            dm.inputs["From Min"].default_value = 0.0
            dm.inputs["From Max"].default_value = min(r * hc["dimple_r"], 0.5)
            dm.inputs["To Min"].default_value = depth_mm * hc["pore_scale"] * hc["dimple_depth"]
            dm.inputs["To Max"].default_value = 0.0
            nt.links.new(vo.outputs["Distance"], dm.inputs["Value"])
            total = _math(nt, "SUBTRACT", total, _math(nt, "MULTIPLY", dm.outputs["Result"], mp.outputs[ch], -600, y - 60),
                          -300, y - 60)
        y -= 250
    # micro relief: the skin-tension cross-hatch (two distorted wave fields at
    # +-angle to the horizontal, narrow valleys at the wave minima), broken in
    # patches, plus a fine grain; the pores sit in it. Relief, not colour.
    furrow = None
    if hc["micro_mm"] > 0:
        scale = 2 * math.pi / (20.0 * hc["micro_period_mm"] * 0.001)
        for k, (ang, wgt) in enumerate(hc["micro_dirs"]):
            mpn = _node(nt, "ShaderNodeMapping", -1350, y, vector_type="POINT")
            mpn.inputs["Rotation"].default_value = (0.0, math.radians(90.0 - ang), 0.0)
            nt.links.new(rest.outputs["Vector"], mpn.inputs["Vector"])
            wv = _node(nt, "ShaderNodeTexWave", -1200, y, wave_type="BANDS", bands_direction="X",
                       wave_profile="SIN")
            wv.inputs["Scale"].default_value = scale
            wv.inputs["Distortion"].default_value = hc["micro_distort"]
            wv.inputs["Detail"].default_value = 2.0
            wv.inputs["Detail Scale"].default_value = hc["micro_distort_scale"]
            wv.inputs["Phase Offset"].default_value = 1.3 * k
            nt.links.new(mpn.outputs["Vector"], wv.inputs["Vector"])
            vr = _node(nt, "ShaderNodeMapRange", -900, y, interpolation_type="SMOOTHSTEP")
            vr.inputs["From Min"].default_value = 0.0
            vr.inputs["From Max"].default_value = hc["micro_width"]
            vr.inputs["To Min"].default_value = wgt
            vr.inputs["To Max"].default_value = 0.0
            nt.links.new(wv.outputs["Fac"], vr.inputs["Value"])
            furrow = vr.outputs["Result"] if furrow is None else _math(nt, "MAXIMUM", furrow, vr.outputs["Result"], -600, y)
            y -= 250
        # patches: a ~2.5 mm noise weakens the network here and there
        nz = _node(nt, "ShaderNodeTexNoise", -1200, y)
        nz.inputs["Scale"].default_value = hc["micro_patch_scale"]
        nz.inputs["Detail"].default_value = 2.0
        nt.links.new(rest.outputs["Vector"], nz.inputs["Vector"])
        br = _node(nt, "ShaderNodeMapRange", -900, y, interpolation_type="SMOOTHSTEP")
        br.inputs["From Min"].default_value = 0.38
        br.inputs["From Max"].default_value = 0.62
        br.inputs["To Min"].default_value = 1.0 - hc["micro_break"]
        br.inputs["To Max"].default_value = 1.0
        nt.links.new(nz.outputs["Fac"], br.inputs["Value"])
        furrow = _math(nt, "MULTIPLY", _math(nt, "MULTIPLY", furrow, br.outputs["Result"], -600, y), micro_w, -450, y)
        fz = _math(nt, "MULTIPLY", furrow, hc["micro_mm"], -300, y)
        total = _math(nt, "MULTIPLY", fz, -1.0, -150, y) if total is None else _math(nt, "SUBTRACT", total, fz, -150, y)
        y -= 250
    if hc["fine_mm"] > 0:
        fn = _node(nt, "ShaderNodeTexNoise", -1200, y)
        fn.inputs["Scale"].default_value = hc["fine_scale"]
        fn.inputs["Detail"].default_value = 1.0
        nt.links.new(rest.outputs["Vector"], fn.inputs["Vector"])
        g = _math(nt, "MULTIPLY", _math(nt, "SUBTRACT", fn.outputs["Fac"], 0.5, -900, y), 2.0 * hc["fine_mm"], -750, y)
        gz = _math(nt, "MULTIPLY", g, micro_w, -600, y)
        total = _math(nt, "MULTIPLY", gz, -1.0, -300, y) if total is None else _math(nt, "SUBTRACT", total, gz, -300, y)
        y -= 250
    # colour: pore openings at most a couple of percent darker
    if opening is not None and hc["pore_dark"] > 0:
        dk = _node(nt, "ShaderNodeMix", 100, 600, data_type="RGBA", blend_type="MULTIPLY")
        nt.links.new(_math(nt, "MULTIPLY", opening, hc["pore_dark"], -100, 650), dk.inputs["Factor"])
        nt.links.new(ta.outputs["Color"], dk.inputs["A"])
        dk.inputs["B"].default_value = (0.55, 0.42, 0.40, 1.0)
        nt.links.new(dk.outputs["Result"], p.inputs["Base Color"])
    else:
        nt.links.new(ta.outputs["Color"], p.inputs["Base Color"])
    # roughness at micro scale: pores and furrow valleys rougher, plateaus a
    # little glossier, so a highlight breaks into a stipple
    rough = _math(nt, "ADD", sep.outputs["Green"], hc["rough_plateau"], -250, 420)
    if opening is not None and hc["pore_rough"] > 0:
        rough = _math(nt, "ADD", rough, _math(nt, "MULTIPLY", opening, hc["pore_rough"], -250, 380), -100, 380)
    if furrow is not None and hc["rough_furrow"] > 0:
        rough = _math(nt, "ADD", rough, _math(nt, "MULTIPLY", furrow, hc["rough_furrow"], -250, 340), -100, 340)
    nt.links.new(rough, p.inputs["Roughness"])
    # micro relief as a shading-normal bump, evaluated per shading point on
    # the rest position (not texel-limited, not dicing-limited); the coat
    # follows it, so pores and furrows break the highlights
    if total is not None and hc["micro_bump"] > 0:
        bump = _node(nt, "ShaderNodeBump", 100, -250)
        bump.inputs["Strength"].default_value = 1.0
        bump.inputs["Distance"].default_value = 0.001 * hc["micro_bump"]
        nt.links.new(total, bump.inputs["Height"])
        nt.links.new(bump.outputs["Normal"], p.inputs["Normal"])
        nt.links.new(bump.outputs["Normal"], p.inputs["Coat Normal"])
    if tile is not None and tile.get("repeat") and hc.get("tile_gain", 0) > 0:
        tc = _node(nt, "ShaderNodeTexCoord", -1700, -1600)
        mpt = _node(nt, "ShaderNodeMapping", -1500, -1600, vector_type="POINT")
        mpt.inputs["Scale"].default_value = (tile["repeat"], tile["repeat"], 1.0)
        nt.links.new(tc.outputs["UV"], mpt.inputs["Vector"])
        ti = _node(nt, "ShaderNodeTexImage", -1300, -1600, image=tile["image"], extension="REPEAT",
                   interpolation="Cubic")
        nt.links.new(mpt.outputs["Vector"], ti.inputs["Vector"])
        th = _node(nt, "ShaderNodeSeparateColor", -1000, -1600)
        nt.links.new(ti.outputs["Color"], th.inputs[0])
        gw = tile["weights"]
        ws = _math(nt, "ADD", _math(nt, "MULTIPLY", mp.outputs["Red"], gw[0], -800, -1700),
                   _math(nt, "MULTIPLY", mp.outputs["Green"], gw[1], -800, -1750), -650, -1700)
        ws = _math(nt, "ADD", ws, _math(nt, "MULTIPLY", mp.outputs["Blue"], gw[2], -800, -1800), -500, -1700)
        w = _node(nt, "ShaderNodeClamp", -350, -1700)
        nt.links.new(ws, w.inputs["Value"])
        macro = _math(nt, "ADD", macro, _math(nt, "MULTIPLY", _math(nt, "MULTIPLY", th.outputs["Red"], w.outputs[0],
                                                                         -200, -1600), hc["tile_gain"], -50, -1600),
                      100, -1500)
    disp = _node(nt, "ShaderNodeDisplacement", 400, -400, space="WORLD")
    disp.inputs["Midlevel"].default_value = 0.0
    disp.inputs["Scale"].default_value = 0.001
    nt.links.new(macro, disp.inputs["Height"])
    nt.links.new(disp.outputs["Displacement"], out.inputs["Displacement"])
    m.max_vertex_displacement = 0.001
    return m


def hero(b):
    """Swap the body's skin slots for the Cycles hero materials and add an
    adaptive Subdivision modifier (last in the stack). Runs after the GLB
    export, so the game keeps the glTF materials."""
    data = getattr(b, "skin_hero", None)
    if not data:
        return None
    body = bpy.data.objects.get(data["body"])
    if body is None:
        return None
    c = data["cfg"]
    hc = dict(HERO)
    hc.update(c.get("hero") or {})
    if not hc.get("enabled", True):
        return None
    by_ch = {ch: (scale, r, depth) for ch, scale, r, depth in skin_synth.PORE_LAYERS.values()}
    head_layers = [by_ch[i] for i in range(3)]
    hands_layers = [(1.0, 0.1, 0.0), (by_ch[1][0], 0.07, skin_synth.DEFAULT_HANDS["pore_mm"]), (1.0, 0.1, 0.0)]
    me = body.data
    idx = [p.material_index for p in me.polygons]
    me.materials.clear()
    tile = data.get("tile")

    def tile_of(key, weights):
        if not tile or not tile["repeat"].get(key):
            return None
        return {"image": tile["image"], "repeat": tile["repeat"][key], "weights": weights}
    me.materials.append(hero_material("skin_head_hero", data["head"], hc, head_layers,
                                      tile_of("head", tile["gain"] if tile else None)))
    me.materials.append(hero_material("skin_hands_hero", data["hands"], dict(hc, micro_bump=1.0, dimple_depth=0.0),
                                      hands_layers, tile_of("hands", (0.0, 1.0, 0.0))))
    restore_indices(me, idx)
    if hc["displacement"]:
        mod = body.modifiers.new("hero_dice", "SUBSURF")
        mod.levels = 0
        mod.render_levels = 1
        mod.use_adaptive_subdivision = True
        mod.adaptive_space = "PIXEL"
        mod.adaptive_pixel_size = float(hc["dicing_px"])
        sc = bpy.context.scene.cycles
        sc.dicing_rate = float(hc["dicing_px"])
        sc.max_subdivisions = int(hc["max_subdivisions"])
    notes = {"materials": [m.name for m in me.materials], "displacement": bool(hc["displacement"]),
             "dicing_px": hc["dicing_px"]}
    b.notes.setdefault("skin", {})["hero"] = notes
    return notes
