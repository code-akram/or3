"""Patch plumbing shared by the facial-hair modules (beard, brows, lashes).

The facial hair is a strand groom (beard_groom.py) with game shells and cards
baked from it (beard_bake.py). The shells stand on a patch of the skin
(faces of the staged body, so they keep its skin weights); this module holds
what that patch needs: per-vertex field smoothing, projection of a direction
onto the skin, collapse decimation that carries the fields through, the
weld/degenerate-face cleanup that keeps the stacked shells valid for the
glTF exporter, and the mikktspace tangent guard (0 validator errors).

Fields per base vertex are dicts keyed by bmesh vert (floats or Vectors).
"""

import bmesh
import bpy
from mathutils import Vector


# --------------------------------------------------------------------------
# Base patch helpers

def smooth_field(bm, field, iterations, weight=0.5):
    """Laplacian smoothing of a per-vertex field (floats or Vectors)."""
    for _ in range(iterations):
        new = {}
        for v in bm.verts:
            nb = [e.other_vert(v) for e in v.link_edges]
            if not nb:
                continue
            avg = sum((field[n] for n in nb[1:]), field[nb[0]]) / len(nb)
            new[v] = field[v] * (1 - weight) + avg * weight
        field.update(new)


def tangent(v, direction):
    """direction projected onto v's tangent plane, unit length (or zero)."""
    n = v.normal
    d = direction - n * direction.dot(n)
    return d.normalized() if d.length > 1e-6 else Vector((0, 0, 0))


def decimate_patch(obj, bm, fields, max_tris, skin_bvh):
    """Collapse-decimate the base patch to max_tris, carrying the skin weights
    and the per-vertex fields through as attributes, then snap the result back
    onto the skin. Returns (bm, fields) for the reduced patch."""
    me = obj.data
    bm.verts.index_update()
    n = len(bm.verts)
    stored = {}
    for key, fld in fields.items():
        by_index = {v.index: x for v, x in fld.items()}
        if isinstance(by_index[0], Vector):
            stored[key] = ("FLOAT_VECTOR", [c for i in range(n) for c in by_index[i]])
        else:
            stored[key] = ("FLOAT", [float(by_index[i]) for i in range(n)])
    src = bm.verts.layers.int.get("src")
    if src is not None:
        bm.verts.layers.int.remove(src)
    bm.to_mesh(me)
    bm.free()
    for key, (kind, data) in stored.items():
        att = me.attributes.new("fh_" + key, kind, "POINT")
        att.data.foreach_set("vector" if kind == "FLOAT_VECTOR" else "value", data)
    tris = sum(len(p.vertices) - 2 for p in me.polygons)
    if tris > max_tris:
        mod = obj.modifiers.new("fh_decimate", "DECIMATE")
        mod.decimate_type = "COLLAPSE"
        mod.use_collapse_triangulate = True
        mod.ratio = max_tris / tris
        with bpy.context.temp_override(object=obj, active_object=obj):
            bpy.ops.object.modifier_apply(modifier=mod.name)
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    out = {}
    for key, (kind, _) in stored.items():
        att = me.attributes["fh_" + key]
        if kind == "FLOAT_VECTOR":
            out[key] = {bm.verts[i]: Vector(d.vector) for i, d in enumerate(att.data)}
        else:
            out[key] = {bm.verts[i]: d.value for i, d in enumerate(att.data)}
        me.attributes.remove(att)
    for v in bm.verts:
        loc, _, _, _ = skin_bvh.find_nearest(v.co)
        if loc is not None:
            v.co = loc
    bm.normal_update()
    return bm, out


def clean_patch(bm, fields, project, weld_m, min_area_m2, min_uv_area):
    """Make the base patch safe to stack: weld coincident vertices, then drop
    faces that are degenerate in 3D or in the tile projection. Either kind
    gives the glTF exporter's mikktspace a zero tangent (validator error
    ACCESSOR_VECTOR3_NON_UNIT), and both happen at the patch boundary on some
    head shapes (decimation collapse plus the snap back onto the skin, or two
    skin points at one projected (u, v) on the nose-wing crease). Fields are
    re-keyed to the surviving vertices. Returns (welded, culled)."""
    bm.verts.index_update()
    by_idx = {k: {v.index: x for v, x in fld.items()} for k, fld in fields.items()}
    n0 = len(bm.verts)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=weld_m)
    # survivors keep their old index until the next index_update
    for k in fields:
        fields[k] = {v: by_idx[k][v.index] for v in bm.verts}
    welded = n0 - len(bm.verts)
    puv = {v: project(v.co) for v in bm.verts}
    bad = []
    for f in bm.faces:
        vs = f.verts
        if len(vs) < 3 or f.calc_area() < min_area_m2:
            bad.append(f)
            continue
        for k in range(1, len(vs) - 1):
            (u0, v0), (u1, v1), (u2, v2) = puv[vs[0]], puv[vs[k]], puv[vs[k + 1]]
            if abs((u1 - u0) * (v2 - v0) - (u2 - u0) * (v1 - v0)) < min_uv_area:
                bad.append(f)
                break
    if bad:
        bmesh.ops.delete(bm, geom=bad, context="FACES")
    loose = [v for v in bm.verts if not v.link_faces]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context="VERTS")
    for k in fields:
        fields[k] = {v: fields[k][v] for v in bm.verts}
    bm.normal_update()
    return welded, len(bad)


def guard_tangents(obj, uv_name, nudge_m, passes):
    """The glTF exporter computes mikktspace tangents from UV0; a loop whose
    tangent comes back zero fails validation (ACCESSOR_VECTOR3_NON_UNIT).
    That happens where a shell folds over a crease (the lip-edge hairs turn
    down harder than their neighbours and a face ends up edge-on and
    UV-mirrored). Run the same tangent pass here: nudge the vertices of any
    zero-tangent loop off the fold (along the normal), re-check, and after
    `passes` nudges delete the faces still failing (one shell face, invisible).
    Returns (nudged, culled_faces)."""
    me = obj.data
    nudged = culled = 0
    for p in range(passes + 1):
        me.calc_tangents(uvmap=uv_name)
        bad = [l for l in me.loops if l.tangent.length < 0.5]
        me.free_tangents()
        if not bad:
            break
        if p < passes:
            for l in bad:
                v = me.vertices[l.vertex_index]
                v.co += v.normal * nudge_m * (p + 1)
            nudged += len(bad)
            continue
        loop_poly = {}
        for poly in me.polygons:
            for li in range(poly.loop_start, poly.loop_start + poly.loop_total):
                loop_poly[li] = poly.index
        faces = set(loop_poly[l.index] for l in bad)
        bm = bmesh.new()
        bm.from_mesh(me)
        bm.faces.ensure_lookup_table()
        bmesh.ops.delete(bm, geom=[bm.faces[i] for i in faces], context="FACES")
        bm.to_mesh(me)
        bm.free()
        culled = len(faces)
    return nudged, culled
