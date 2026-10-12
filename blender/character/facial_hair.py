"""Shell-textured short hair (beard, stubble, brows): the standard short-fur
technique, built as plain glTF geometry.

A base patch of the skin (faces of the body, so it keeps the skin weights) is
duplicated N times. Shell i sits at t = i / N of the local hair length,
displaced along the skin normal and bent over along a per-vertex comb
direction, so a texel column across the shells is one hair growing out of
the skin and lying down. Every shell is alpha-tested (glTF MASK) against its
own tile of one generated atlas: tile i holds the cross-section of the hair
field at height t, so hairs taper, drift sideways and end at their own
length. Density and length maps rasterised from per-vertex fields shape the
edges (cheek line fading into stubble, neckline, feather at the lips) and
skin shows between the hairs wherever the density is below one.

At runtime the same look costs one tile plus a per-vertex shell height; the
per-shell atlas is what lets the look-dev GLB carry it with a stock material.

Fields per base vertex (dicts keyed by bmesh vert):
  density  0..1   share of hair positions that grow a hair
  length_m        hair length at full growth (the shell stack height)
  short    0..1   length factor (stubble < 1), per texel after rasterising
  comb     Vector tangent-ish comb direction (world), unit length
"""

import math

import bmesh
import bpy
import numpy as np
from mathutils import Vector

from . import hair_mesh


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


# --------------------------------------------------------------------------
# Atlas texture

def _rasterize(tri_px, tri_val, w, h, fill):
    """Per-vertex values interpolated over UV triangles (pixel space)."""
    out = np.full((h, w), fill, dtype=np.float32)
    for (p0, p1, p2), (a, b, c) in zip(tri_px, tri_val):
        x0 = max(int(math.floor(min(p0[0], p1[0], p2[0]))), 0)
        x1 = min(int(math.ceil(max(p0[0], p1[0], p2[0]))) + 1, w)
        y0 = max(int(math.floor(min(p0[1], p1[1], p2[1]))), 0)
        y1 = min(int(math.ceil(max(p0[1], p1[1], p2[1]))) + 1, h)
        if x1 <= x0 or y1 <= y0:
            continue
        xs = np.arange(x0, x1)[None, :] + 0.5
        ys = np.arange(y0, y1)[:, None] + 0.5
        det = (p1[0] - p0[0]) * (p2[1] - p0[1]) - (p2[0] - p0[0]) * (p1[1] - p0[1])
        if abs(det) < 1e-9:
            continue
        l1 = ((xs - p0[0]) * (p2[1] - p0[1]) - (p2[0] - p0[0]) * (ys - p0[1])) / det
        l2 = ((p1[0] - p0[0]) * (ys - p0[1]) - (xs - p0[0]) * (p1[1] - p0[1])) / det
        l0 = 1 - l1 - l2
        # a one-pixel bleed so bilinear sampling at the patch edge sees hair
        eps = -0.5 / max(x1 - x0, y1 - y0)
        m = (l0 >= eps) & (l1 >= eps) & (l2 >= eps)
        val = l0 * a + l1 * b + l2 * c
        sub = out[y0:y1, x0:x1]
        sub[m] = val[m]
    return out


def atlas_image(name, cfg, layers, cols, tile, tri_px, density_v, short_v, comb_px, rng):
    """One RGBA atlas of `layers` tiles (grid cols x rows of tile w x h): tile
    i is the alpha-tested cross-section of the hair field at height
    t = (i + 1) / layers. Hairs are scattered on a jittered grid, kept with
    probability density, and each has a length (x the local length factor),
    a value, a radius that tapers with height, and a sideways drift so hairs
    don't all lie exactly along the comb.
    tri_px: (n, 3, 2) base-face triangles in tile pixel space; density_v,
    short_v: (n, 3) per-corner values; comb_px: (n, 3, 2) comb direction in
    tile pixel space (for the drift, which follows the comb loosely)."""
    tw, th = tile
    rows = math.ceil(layers / cols)
    W, H = tw * cols, th * rows
    dens = _rasterize(tri_px, density_v, tw, th, 0.0)
    short = _rasterize(tri_px, short_v, tw, th, 0.0)
    comb_u = _rasterize(tri_px, comb_px[..., 0], tw, th, 0.0)
    comb_w = _rasterize(tri_px, comb_px[..., 1], tw, th, 0.0)
    # Hair positions: jittered grid.
    sp = cfg["spacing_px"]
    gx, gy = np.meshgrid(np.arange(0, tw, sp), np.arange(0, th, sp))
    cx = (gx + rng.uniform(0, sp, gx.shape)).ravel()
    cy = (gy + rng.uniform(0, sp, gy.shape)).ravel()
    ix, iy = np.clip(cx.astype(int), 0, tw - 1), np.clip(cy.astype(int), 0, th - 1)
    keep = rng.uniform(0, 1, cx.shape) < dens[iy, ix] * cfg["density"]
    cx, cy, ix, iy = cx[keep], cy[keep], ix[keep], iy[keep]
    n = len(cx)
    length = short[iy, ix] * rng.uniform(cfg["len_min"], 1.0, n)
    length = np.clip(length, 0.03, 1.0)
    value = rng.lognormal(0, cfg["value_sigma"], n)
    radius = cfg["radius_px"] * rng.uniform(0.75, 1.25, n) * (cfg["short_thin"] + (1 - cfg["short_thin"]) * length)
    # Drift: a random sideways vector plus a share of the comb direction, in
    # px per unit height, so each hair bends its own way.
    ang = rng.uniform(0, 2 * np.pi, n)
    drift = cfg["drift_px"]
    dx = np.cos(ang) * drift * rng.uniform(0.3, 1, n) + comb_u[iy, ix] * cfg["comb_drift_px"]
    dy = np.sin(ang) * drift * rng.uniform(0.3, 1, n) + comb_w[iy, ix] * cfg["comb_drift_px"]
    base = hair_mesh.hex_rgb(cfg["color"])
    alpha = np.zeros((H, W), dtype=np.float32)
    val = np.full((H, W), cfg["base_value"], dtype=np.float32)
    # Each hair's cross-section is a dash elongated along its own bend
    # direction (where it moves between shells), so the dashes of successive
    # shells overlap into one strand instead of a row of dots.
    elong = cfg["elongate"]
    dn = np.hypot(dx, dy)
    ux = np.where(dn > 1e-6, dx / np.maximum(dn, 1e-6), 1.0)
    uy = np.where(dn > 1e-6, dy / np.maximum(dn, 1e-6), 0.0)
    rmax = int(math.ceil(cfg["radius_px"] * 1.25 * elong)) + 1
    oy, ox = np.mgrid[-rmax:rmax + 1, -rmax:rmax + 1]
    ox, oy = ox.ravel().astype(np.float32), oy.ravel().astype(np.float32)
    for i in range(layers):
        t = (i + 1) / layers
        vis = length >= t
        if not vis.any():
            continue
        hx = cx[vis] + dx[vis] * t
        hy = cy[vis] + dy[vis] * t
        hr = radius[vis] * (1 - cfg["taper"] * t / length[vis])
        hv = value[vis]
        shade = cfg["root_shade"] + (1 - cfg["root_shade"]) * t ** 0.7
        px = np.rint(hx)[:, None] + ox[None, :]
        py = np.rint(hy)[:, None] + oy[None, :]
        ex, ey = px - hx[:, None], py - hy[:, None]
        par = ex * ux[vis][:, None] + ey * uy[vis][:, None]
        perp = ex * uy[vis][:, None] - ey * ux[vis][:, None]
        d = np.hypot(par / elong, perp)
        cov = np.clip(hr[:, None] + 0.5 - d, 0, 1)
        m = cov > 0.02
        px, py = px[m].astype(int), py[m].astype(int)
        inside = (px >= 0) & (px < tw) & (py >= 0) & (py < th)
        px, py = px[inside], py[inside]
        c = cov[m][inside]
        vv = (hv * shade)[:, None].repeat(len(ox), 1)[m][inside]
        x0, y0 = (i % cols) * tw, (i // cols) * th
        flat = (py + y0) * W + (px + x0)
        a = alpha.ravel()
        np.maximum.at(a, flat, c)
        # colour: full-coverage pixels take the hair's value; partial ones blend
        vr = val.ravel()
        vr[flat] = np.where(c > 0.5, vv, vr[flat] * (1 - c) + vv * c)
    rgba = np.zeros((H, W, 4), dtype=np.float32)
    rgba[..., :3] = np.clip(base[None, None, :] * val[..., None], 0, 1)
    rgba[..., 3] = alpha
    img = bpy.data.images.get(name)
    if img:
        bpy.data.images.remove(img)
    img = bpy.data.images.new(name, W, H, alpha=True)
    img.pixels.foreach_set(rgba.ravel())
    img.pack()
    return img, n


# --------------------------------------------------------------------------
# Shells

def build_shells(b, obj, bm, fields, cfg, name, project, tile, rng, extra=None):
    """Turn the base patch (bm, with skin weights) into N shells, UV-mapped
    into one atlas, with a MASK material. project(p: Vector) -> (u, v) in
    0..1 across a tile. extra(bm, uv, uv2, dl) may add cards (material 1).
    Returns stats."""
    layers = cfg["layers"]
    welded, culled = clean_patch(bm, fields, project, cfg.get("weld_m", 2e-5),
                                 cfg.get("min_face_area_m2", 1e-10), cfg.get("min_uv_area", 1e-9))
    base_faces = list(bm.faces)
    base_verts = list(bm.verts)
    bm.normal_update()
    dl = bm.verts.layers.deform.verify()
    uv = bm.loops.layers.uv.verify()
    uv2 = bm.loops.layers.uv.new("strand")
    cols = cfg["atlas_cols"]
    rows = math.ceil(layers / cols)
    tw, th = tile
    W, H = tw * cols, th * rows
    puv = {v: project(v.co) for v in base_verts}
    # Shell geometry: hair path offset(t) = L (n (t - lean t²/2) + comb lean t²/2),
    # the integral of a direction that turns from the normal toward the comb.
    lean = cfg["lean"]
    normals = {v: v.normal.copy() for v in base_verts}
    shells_tris = 0
    for i in range(layers):
        t = (i + 1) / layers
        x0, y0 = (i % cols) * tw, (i // cols) * th
        new = {}
        for v in base_verts:
            L = fields["length_m"][v]
            off = normals[v] * (t - lean * t * t / 2) + fields["comb"][v] * (lean * t * t / 2)
            nv = bm.verts.new(v.co + off * L)
            for g, w in v[dl].items():
                nv[dl][g] = w
            new[v] = nv
        for f in base_faces:
            nf = bm.faces.new([new[v] for v in f.verts])
            nf.material_index = 0
            for loop, v in zip(nf.loops, f.verts):
                u_, v_ = puv[v]
                loop[uv].uv = ((x0 + u_ * tw) / W, (y0 + v_ * th) / H)
                loop[uv2].uv = (t, 0.0)
            shells_tris += len(f.verts) - 2
    # Texture inputs from the base faces (triangulated by fan).
    tri_px, dens, short, comb_px = [], [], [], []
    for f in base_faces:
        vs = f.verts
        for k in range(1, len(vs) - 1):
            tri = (vs[0], vs[k], vs[k + 1])
            tri_px.append([(puv[v][0] * tw, puv[v][1] * th) for v in tri])
            dens.append([fields["density"][v] for v in tri])
            short.append([fields["short"][v] for v in tri])
            # comb in tile px: project a point one unit along the comb
            cp = []
            for v in tri:
                u0, v0 = puv[v]
                u1, v1 = project(v.co + fields["comb"][v] * 0.01)
                d = Vector(((u1 - u0) * tw, (v1 - v0) * th))
                cp.append(tuple(d.normalized()) if d.length > 1e-6 else (0.0, 0.0))
            comb_px.append(cp)
    img, hairs = atlas_image(name + "_atlas", cfg["texture"], layers, cols, tile,
                             np.array(tri_px, dtype=np.float64), np.array(dens),
                             np.array(short), np.array(comb_px), rng)
    # The base patch itself is dropped: the skin is under it.
    bmesh.ops.delete(bm, geom=base_faces, context="FACES")
    card_tris = 0
    mats = [hair_mesh.material(name, cfg["texture"]["color"], cfg["roughness"], img,
                               cfg["specular"], wrap=False)]
    if extra is not None:
        card_tris, card_mat = extra(bm, uv, uv2, dl)
        mats.append(card_mat)
    hair_mesh.finish(b, obj, bm, mats)
    nudged, culled_tan = guard_tangents(obj, obj.data.uv_layers[0].name, cfg.get("tangent_nudge_m", 2e-4),
                                        cfg.get("tangent_passes", 2))
    return {"layers": layers, "shell_tris": shells_tris, "card_tris": card_tris,
            "hairs": int(hairs), "atlas": [W, H],
            "welded_verts": welded, "culled_degenerate_faces": culled,
            "tangent_nudged_loops": nudged, "tangent_culled_faces": culled_tan}
