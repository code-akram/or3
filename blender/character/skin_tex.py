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


# --- synthesis inputs ------------------------------------------------------------------------

class Maps:
    """Everything the synthesis needs for one texture (head or hands)."""

    def __init__(self, size, P, N, T, cover, attrs1, attrs2, nA, nB, nC, nD, ao, nE=None, nF=None, nG=None):
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
        ao = bk.run("ao", None, samples=int(c.get("ao_samples", 16)), bake_type="AO", down=int(c.get("ao_down", 2)))
    finally:
        bk.finish()
        for o in hidden:
            o.hide_render = False
    for n in ("sk_lips", "sk_nails", "sk_ears", "sk_scalp", "sk_region"):
        me.attributes.remove(me.attributes[n])

    maps = [Maps(bake_px[i], P[i], N[i], T[i], cover[i], a1[i], a2[i], nA[i], nB[i], nC[i], nD[i], ao[i], nE[i], nF[i], nG[i]) for i in range(2)]
    cl, cr = head_refine.eye_centres(eyes) if eyes is not None else (np.array([0.03, -0.13, 1.72]), np.array([-0.03, -0.13, 1.72]))
    hc = dict(skin_synth.DEFAULT_HEAD)
    hc.update(c.get("head") or {})
    hc["base"] = c.get("base", hc["base"])
    hc.setdefault("corners", mouth_corners(body))
    head = skin_synth.synth_head(maps[0], hc, cl, cr)
    hh = dict(skin_synth.DEFAULT_HANDS)
    hh.update(c.get("hands") or {})
    hh["base"] = c.get("base", hh["base"])
    # Track G hook: A's hand synthesis plus the hand detail layer (hand_detail.py)
    hands = hand_detail.synth(maps[1], hh, head_refine.hand_frames(arm), head_refine.FINGERS,
                              ((b.cfg.get("hands") or {}).get("detail")))
    out_dir = b.out_dir if c.get("save_maps") else None
    imgs, hero_in = {}, {"body": body.name, "cfg": c}
    for key, m, syn in (("head", maps[0], head), ("hands", maps[1], hands)):
        z = np.zeros_like(syn["rough"])
        imgs[key] = {
            "albedo": make_image(f"skin_{key}_albedo", syn["albedo"], True, out_dir),
            "orm": make_image(f"skin_{key}_orm", np.stack([syn["occl"], syn["rough"], z], -1), False, out_dir),
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
    sss = float(c.get("sss", 0.0))
    idx = [p.material_index for p in me.polygons]
    me.materials.clear()
    for key in ("head", "hands"):
        me.materials.append(skin_material(f"skin_{key}", imgs[key]["albedo"], imgs[key]["orm"], imgs[key]["normal"], sss))
    restore_indices(me, idx)
    face = maps[0].cover & (np.abs(maps[0].region - 0.5) < 0.05) & (maps[0].lips < 0.3)
    stats = {"sizes": bake_px, "seconds": round(time.perf_counter() - t0, 2),
             "height_mm": {k: [round(float(v["hgt_game"].min()) * 1000, 3), round(float(v["hgt_game"].max()) * 1000, 3)]
                           for k, v in (("head", head), ("hands", hands))},
             "albedo_mean_srgb": _mean_srgb(head["albedo"], maps[0].cover),
             "albedo_face_mean_srgb": _mean_srgb(head["albedo"], face),
             "hero_albedo_face_mean_srgb": _mean_srgb(head["albedo_hero"], face),
             "roughness_mean": round(float(head["rough"][maps[0].cover].mean()), 3),
             "roughness_face_mean": round(float(head["rough"][face].mean()), 3) if face.any() else None,
             "hero_rest": rest is not None}
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


def hero_material(name, im, hc, layers):
    """One Principled (the hero rig's clay/normal passes swap the first one)."""
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
    me.materials.append(hero_material("skin_head_hero", data["head"], hc, head_layers))
    me.materials.append(hero_material("skin_hands_hero", data["hands"], dict(hc, micro_bump=1.0, dimple_depth=0.0),
                                      hands_layers))
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
