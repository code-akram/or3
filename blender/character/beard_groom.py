"""Strand grooms for the short facial hair (beard, stubble, brows, lashes).

The groom is the source of truth. Each groom is a Blender hair-curves object:

  1. Roots are scattered over a skin patch (triangles of the staged body)
     with a per-vertex density map: candidates are Poisson-distributed by
     area and kept with the interpolated density, so a beard line is a
     density gradient, not a cut.
  2. Each strand grows from its root along a direction field: it leaves the
     skin at an elevation angle that relaxes toward the tip (hair lies down
     along the comb direction), with a per-strand yaw and curl, and its length
     comes from a length map. Points are kept a hair's width above the skin
     (the moustache rides over the lip instead of entering it).
  3. Geometry Nodes add clumping and frizz (Blender's bundled "Clump Hair
     Curves" and "Frizz Hair Curves" node groups, run as modifiers with a
     fixed seed and per-strand factors read from curve attributes), so the
     build is deterministic.

Hero render: the curves live in the `hero_only` collection (never exported),
bound to the head (or neck) bone and shaded with the Principled Hair BSDF;
per-strand melanin / redness attributes give the near-black brown with warm
brown and grey strands. Game version: `beard_bake` reads the evaluated
strands back (`strands`) and paints shells and cards from them.

Everything is numpy over (n, k, 3) point arrays; one rng per groom.
"""

import os

import bpy
import numpy as np
from mathutils import Matrix, Vector

from . import export

NODE_LIB = "assets/nodes/procedural_hair_node_assets.blend"


# --------------------------------------------------------------------------
# Patch -> roots

def patch_arrays(bm, fields):
    """Triangles of a bmesh patch and its per-vertex fields as arrays:
    (co (v,3), normal (v,3), tris (t,3), {field: (v,) or (v,3)})."""
    bm.verts.index_update()
    bm.normal_update()
    tris = np.array([[l.vert.index for l in t] for t in bm.calc_loop_triangles()], dtype=np.int64)
    verts = list(bm.verts)
    co = np.array([v.co[:] for v in verts])
    nrm = np.array([v.normal[:] for v in verts])
    out = {}
    for k, fld in fields.items():
        x = fld[verts[0]]
        if isinstance(x, Vector):
            out[k] = np.array([fld[v][:] for v in verts])
        else:
            out[k] = np.array([float(fld[v]) for v in verts])
    return co, nrm, tris, out


def sample_roots(co, nrm, tris, fields, per_m2, rng, density_key="density"):
    """Roots on the patch: Poisson candidates by area, kept with the
    interpolated density. Returns (pos, normal, {field: per-root values})."""
    a = co[tris[:, 1]] - co[tris[:, 0]]
    b = co[tris[:, 2]] - co[tris[:, 0]]
    area = 0.5 * np.linalg.norm(np.cross(a, b), axis=1)
    cnt = rng.poisson(area * per_m2)
    ti = np.repeat(np.arange(len(tris)), cnt)
    m = len(ti)
    r1, r2 = rng.random(m), rng.random(m)
    s = np.sqrt(r1)
    bary = np.stack([1 - s, s * (1 - r2), s * r2], axis=1)

    def interp(arr):
        v = arr[tris[ti]]
        return (v * bary[..., None]).sum(1) if v.ndim == 3 else (v * bary).sum(1)

    dens = interp(fields[density_key])
    keep = rng.random(m) < dens
    pos = interp(co)[keep]
    n = interp(nrm)[keep]
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
    out = {k: interp(v)[keep] for k, v in fields.items()}
    return pos, n, out


def tangent_frame(n, comb):
    """Comb projected onto the tangent plane (unit) and the binormal."""
    c = comb - n * (comb * n).sum(1, keepdims=True)
    ln = np.linalg.norm(c, axis=1, keepdims=True)
    fallback = np.cross(n, np.array([1.0, 0.0, 0.0]))
    c = np.where(ln > 1e-6, c / np.maximum(ln, 1e-9), fallback)
    c /= np.maximum(np.linalg.norm(c, axis=1, keepdims=True), 1e-9)
    return c, np.cross(n, c)


# --------------------------------------------------------------------------
# Growth

def grow(pos, n, comb, length, elev0, elev1, yaw, curl, k, bend_pow=1.0):
    """Strand points (m, k, 3). The direction at arc fraction s leaves the
    skin at elevation elev0 (radians over the tangent plane) relaxing to
    elev1 at the tip (s^bend_pow), heading along the comb turned by yaw and
    curling by curl x s (radians). All per-strand arrays (m,)."""
    c, b = tangent_frame(n, comb)
    s = (np.arange(k - 1) + 0.5) / (k - 1)  # segment midpoints
    th = elev0[:, None] + (elev1 - elev0)[:, None] * s[None, :] ** bend_pow
    ps = yaw[:, None] + curl[:, None] * s[None, :]
    d = (np.cos(th)[..., None] * (np.cos(ps)[..., None] * c[:, None, :] + np.sin(ps)[..., None] * b[:, None, :])
         + np.sin(th)[..., None] * n[:, None, :])
    step = (length / (k - 1))[:, None, None]
    pts = np.concatenate([pos[:, None, :], pos[:, None, :] + np.cumsum(d * step, axis=1)], axis=1)
    return pts


def collide(pts, bvh, gap, skip_root=True):
    """Keep every point at least gap(i) (m, per point index) over the skin
    (the nearest surface's front side). A pushed point carries the rest of
    its strand with it, so segments keep their length roughly."""
    m, k, _ = pts.shape
    pushed = 0
    for j in range(m):
        carry = Vector((0, 0, 0))
        for i in range(1 if skip_root else 0, k):
            p = Vector(pts[j, i]) + carry
            loc, nrm, _, _ = bvh.find_nearest(p)
            if loc is not None:
                h = (p - loc).dot(nrm)
                g = gap[i]
                if h < g:
                    q = p + nrm * (g - h)
                    carry += q - p
                    p = q
                    pushed += 1
            pts[j, i] = p[:]
    return pushed


def heights(pts, bvh):
    """Signed height of every point over the skin (m, k)."""
    m, k, _ = pts.shape
    out = np.zeros((m, k))
    for j in range(m):
        for i in range(k):
            p = Vector(pts[j, i])
            loc, nrm, _, _ = bvh.find_nearest(p)
            out[j, i] = (p - loc).dot(nrm) if loc is not None else 0.0
    return out


# --------------------------------------------------------------------------
# Curves object, Geometry Nodes, material

def make_curves(name, pts, radius, curve_attrs=None, material=None):
    """Hair-curves object in the hero_only collection (identity transform;
    bind() parents it to a bone afterwards)."""
    m, k, _ = pts.shape
    cv = bpy.data.hair_curves.new(name)
    cv.add_curves([k] * m)
    cv.position_data.foreach_set("vector", pts.astype(np.float32).ravel())
    rad = cv.attributes.get("radius") or cv.attributes.new("radius", "FLOAT", "POINT")
    rad.data.foreach_set("value", np.broadcast_to(radius, (m, k)).astype(np.float32).ravel())
    for key, arr in (curve_attrs or {}).items():
        a = cv.attributes.new(key, "FLOAT", "CURVE")
        a.data.foreach_set("value", np.asarray(arr, dtype=np.float32))
    if material is not None:
        cv.materials.append(material)
    obj = bpy.data.objects.new(name, cv)
    export.hero_collection().objects.link(obj)
    return obj


def _node_group(name):
    ng = bpy.data.node_groups.get(name)
    if ng is not None:
        return ng
    path = os.path.join(bpy.utils.system_resource("DATAFILES"), NODE_LIB)
    if not os.path.isfile(path):
        raise RuntimeError(f"Blender's bundled hair node groups not found: {path}")
    with bpy.data.libraries.load(path) as (src, dst):
        dst.node_groups = [name]
    return bpy.data.node_groups[name]


def _socket_ids(ng):
    return {it.name: it.identifier for it in ng.interface.items_tree
            if it.item_type == "SOCKET" and it.in_out == "INPUT"}


def add_gn(obj, group, values, attrs=None):
    """A Geometry Nodes modifier running one of Blender's bundled hair node
    groups. values: {socket name: value}; attrs: {socket name: curve
    attribute name} for per-strand factors."""
    ng = _node_group(group)
    mod = obj.modifiers.new(group, "NODES")
    mod.node_group = ng
    ids = _socket_ids(ng)
    inputs = getattr(getattr(mod, "properties", None), "inputs", None)
    for k, v in values.items():
        if inputs is not None:  # Blender 5.x: typed modifier interface
            getattr(inputs, ids[k]).value = v
        else:
            mod[ids[k]] = v
    for k, a in (attrs or {}).items():
        if inputs is not None:
            sock = getattr(inputs, ids[k])
            sock.type = "ATTRIBUTE"
            sock.attribute_name = a
        else:
            mod[ids[k] + "_use_attribute"] = True
            mod[ids[k] + "_attribute_name"] = a
    return mod


def clump_frizz(obj, cfg, seed):
    """Clumping (guides picked by distance, per-strand factor from the
    'clump' attribute) then frizz (per-strand amplitude from 'frizz')."""
    if cfg.get("clump"):
        c = cfg["clump"]
        add_gn(obj, "Clump Hair Curves",
               {"Factor": 1.0, "Shape": c["shape"], "Tip Spread": c["tip_spread"],
                "Clump Offset": c.get("offset", 0.0), "Distance Falloff": c.get("falloff", 0.0),
                "Distance Threshold": c.get("threshold", 0.0), "Seed": seed,
                "Preserve Length": True, "Guide Distance": c["guide_distance_m"],
                "Existing Guide Map": False},
               {"Factor": "clump"})
    if cfg.get("frizz"):
        f = cfg["frizz"]
        add_gn(obj, "Frizz Hair Curves",
               {"Factor": 1.0, "Distance": f["distance_m"], "Shape": f["shape"],
                "Seed": seed + 1, "Preserve Length": True},
               {"Factor": "frizz"})


def strands(obj):
    """Evaluated strand points (m, k, 3) in world space."""
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    cv = ev.data
    n = len(cv.points)
    pos = np.empty(n * 3, dtype=np.float32)
    cv.attributes["position"].data.foreach_get("vector", pos)
    m = len(cv.curves)
    pts = pos.reshape(m, n // m, 3).astype(np.float64)
    mw = np.array(ev.matrix_world)
    return pts @ mw[:3, :3].T + mw[:3, 3]


def set_base_points(obj, pts):
    """Write (m, k, 3) world points back as the original (pre-modifier)
    positions."""
    inv = np.array(obj.matrix_world.inverted())
    loc = pts @ inv[:3, :3].T + inv[:3, 3]
    obj.data.position_data.foreach_set("vector", loc.astype(np.float32).ravel())
    obj.data.update_tag()


def base_points(obj):
    cv = obj.data
    n = len(cv.points)
    pos = np.empty(n * 3, dtype=np.float32)
    cv.position_data.foreach_get("vector", pos)
    m = len(cv.curves)
    mw = np.array(obj.matrix_world)
    return pos.reshape(m, n // m, 3).astype(np.float64) @ mw[:3, :3].T + mw[:3, 3]


def bind(b, obj, bone):
    """Parent to an armature bone, keeping the world transform, so the
    strands follow the head (or neck) when the rig is posed."""
    arm = b.armature()
    mw = obj.matrix_world.copy()
    obj.parent = arm
    obj.parent_type = "BONE"
    obj.parent_bone = bone
    bpy.context.view_layer.update()
    obj.matrix_world = mw
    obj.matrix_parent_inverse = Matrix.Identity(4)
    bpy.context.view_layer.update()
    obj.matrix_world = mw


def hair_material(name, cfg):
    """Principled Hair BSDF (Chiang), melanin from the per-strand 'melanin'
    and 'redness' attributes, a little darker at the root."""
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    for nd in list(nt.nodes):
        nt.nodes.remove(nd)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    hb = nt.nodes.new("ShaderNodeBsdfHairPrincipled")
    hb.parametrization = "MELANIN"
    hb.model = "CHIANG"
    hb.inputs["Roughness"].default_value = cfg["roughness"]
    hb.inputs["Radial Roughness"].default_value = cfg["radial_roughness"]
    hb.inputs["Coat"].default_value = cfg.get("coat", 0.0)
    hb.inputs["Random Roughness"].default_value = 0.2
    hb.inputs["Random Color"].default_value = 0.0
    mel = nt.nodes.new("ShaderNodeAttribute")
    mel.attribute_type = "GEOMETRY"
    mel.attribute_name = "melanin"
    red = nt.nodes.new("ShaderNodeAttribute")
    red.attribute_type = "GEOMETRY"
    red.attribute_name = "redness"
    # root darkening: melanin + root_dark x (1 - intercept)^2, clamped
    info = nt.nodes.new("ShaderNodeHairInfo")
    inv = nt.nodes.new("ShaderNodeMath")
    inv.operation = "SUBTRACT"
    inv.inputs[0].default_value = 1.0
    nt.links.new(info.outputs["Intercept"], inv.inputs[1])
    sq = nt.nodes.new("ShaderNodeMath")
    sq.operation = "POWER"
    sq.inputs[1].default_value = 3.0
    nt.links.new(inv.outputs[0], sq.inputs[0])
    mul = nt.nodes.new("ShaderNodeMath")
    mul.operation = "MULTIPLY"
    mul.inputs[1].default_value = cfg.get("root_dark", 0.1)
    nt.links.new(sq.outputs[0], mul.inputs[0])
    add = nt.nodes.new("ShaderNodeMath")
    add.operation = "ADD"
    add.use_clamp = True
    nt.links.new(mel.outputs["Fac"], add.inputs[0])
    nt.links.new(mul.outputs[0], add.inputs[1])
    nt.links.new(add.outputs[0], hb.inputs["Melanin"])
    nt.links.new(red.outputs["Fac"], hb.inputs["Melanin Redness"])
    if cfg.get("tip_alpha", 1.0) < 1.0:
        # Fade the strand toward its tip (opacity 1 up to tip_fade_from along
        # the strand, tip_alpha at the end), so the ends taper in alpha as
        # well as width instead of ending in a hard dot.
        fade = nt.nodes.new("ShaderNodeMapRange")
        fade.interpolation_type = "SMOOTHSTEP"
        fade.inputs["From Min"].default_value = cfg.get("tip_fade_from", 0.5)
        fade.inputs["From Max"].default_value = 1.0
        fade.inputs["To Min"].default_value = 1.0
        fade.inputs["To Max"].default_value = cfg["tip_alpha"]
        nt.links.new(info.outputs["Intercept"], fade.inputs["Value"])
        tr = nt.nodes.new("ShaderNodeBsdfTransparent")
        mix = nt.nodes.new("ShaderNodeMixShader")
        nt.links.new(fade.outputs["Result"], mix.inputs["Fac"])
        nt.links.new(tr.outputs[0], mix.inputs[1])
        nt.links.new(hb.outputs[0], mix.inputs[2])
        nt.links.new(mix.outputs[0], out.inputs["Surface"])
    else:
        nt.links.new(hb.outputs[0], out.inputs["Surface"])
    return mat


# --------------------------------------------------------------------------
# Refit after the face refinement

class SkinRefit:
    """head_refine subdivides and re-planarises the face after the hair is
    built, so the skin under the facial hair moves by up to a few mm.
    Records the pre-refine skin; apply() moves every registered point by the
    displacement of its nearest skin point (old nearest -> new nearest)."""

    # After the move, strand points are kept this far over the new skin: a
    # face-shape change bigger than the refine's few mm (e.g. a face delta
    # applied after the grooms) would otherwise leave skin poking through.
    GAP_M = 0.0001

    def __init__(self, old_bvh):
        self.old = old_bvh
        self.items = []   # (kind, obj)
        self.pushed = 0   # strand points pushed back out of the new skin

    def add(self, kind, obj):
        self.items.append((kind, obj))

    def _delta(self, p, new):
        loc, _, _, _ = self.old.find_nearest(p)
        if loc is None:
            return Vector((0, 0, 0))
        nl, _, _, _ = new.find_nearest(loc)
        return (nl - loc) if nl is not None else Vector((0, 0, 0))

    def apply(self, new_bvh):
        moved = 0.0
        for kind, obj in self.items:
            if kind == "curves":
                pts = base_points(obj)
                m, k, _ = pts.shape
                for j in range(m):
                    d = self._delta(Vector(pts[j, 0]), new_bvh)
                    pts[j] += np.array(d[:])
                    moved = max(moved, d.length)
                self.pushed += collide(pts, new_bvh, np.full(k, self.GAP_M))
                set_base_points(obj, pts)
            else:
                mw = obj.matrix_world
                inv = mw.inverted()
                # per vertex: the delta of the skin point under its root
                # (stored as the 'fh_root' attribute if present, else itself)
                me = obj.data
                root = me.attributes.get("fh_root")
                for i, v in enumerate(me.vertices):
                    p = mw @ v.co
                    q = Vector(root.data[i].vector) if root is not None else p
                    d = self._delta(q, new_bvh)
                    v.co = inv @ (p + d)
                    moved = max(moved, d.length)
                if root is not None:
                    me.attributes.remove(root)
                me.update()
        return round(moved * 1000, 3)


def refit_for(b, frame):
    """The build's SkinRefit (created on first use, from the pre-refine
    skin)."""
    if getattr(b, "facial_refit", None) is None:
        b.facial_refit = SkinRefit(frame.skin_bvh)
    return b.facial_refit


def refit(b):
    """Build stage after head_refine: follow the refined skin."""
    fr = getattr(b, "facial_refit", None)
    if fr is None:
        return
    from . import facial_hair
    from .hair_frame import world_bvh
    body = next(o for o in b.meshes() if o.vertex_groups.get("scalp"))
    moved_mm = fr.apply(world_bvh([body]))
    guard = {}
    for kind, obj in fr.items:
        if kind == "mesh":
            guard[obj.name] = facial_hair.guard_tangents(obj, obj.data.uv_layers[0].name, 2e-4, 2)
    b.notes["facial_hair_refit"] = {"max_move_mm": moved_mm, "strand_points_pushed": fr.pushed,
                                    "tangent_guard": guard}
