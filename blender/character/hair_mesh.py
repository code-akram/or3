"""Mesh plumbing shared by the hair and beard generators: body-derived shells,
tapered clump tubes, skinning to the staged rig, and the look-dev material."""

import math

import bmesh
import bpy
from mathutils import Vector


def srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def material(name, hex_srgb, roughness):
    """Flat dark look-dev material. The runtime hair shader (banded
    Kajiya-Kay) is a TSL concern; this only has to read in the loop renders."""
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    rgb = [srgb_to_linear(int(hex_srgb[i:i + 2], 16) / 255) for i in (1, 3, 5)]
    bsdf.inputs["Base Color"].default_value = (*rgb, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    return mat


def shell_from_body(b, body, keep, name):
    """New object holding the faces of body whose vertices are all in keep
    (a set of vertex indices). Keeps the body's skin weights, so a shell
    deforms exactly like the skin under it. Returns (obj, bm); the int
    vertex layer "src" holds each vertex's body index. Write back with
    finish()."""
    me = body.data.copy()
    me.name = name
    obj = bpy.data.objects.new(name, me)
    for c in body.users_collection:
        c.objects.link(obj)
    obj.parent = body.parent
    obj.matrix_parent_inverse = body.matrix_parent_inverse.copy()
    obj.matrix_world = body.matrix_world.copy()
    for g in body.vertex_groups:
        obj.vertex_groups.new(name=g.name)
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    src = bm.verts.layers.int.new("src")  # body vertex index; finish() drops it
    for v in bm.verts:
        v[src] = v.index
    drop = [f for f in bm.faces if not all(v.index in keep for v in f.verts)]
    bmesh.ops.delete(bm, geom=drop, context="FACES_ONLY")
    loose = [v for v in bm.verts if not v.link_faces]
    bmesh.ops.delete(bm, geom=loose, context="VERTS")
    return obj, bm


def edge_rings(bm, n):
    """Distance in edge rings from the open boundary, capped at n."""
    ring = {v: n for v in bm.verts}
    front = [v for v in bm.verts if v.is_boundary]
    for d in range(n):
        nxt = []
        for v in front:
            if ring[v] > d:
                ring[v] = d
                nxt += [e.other_vert(v) for e in v.link_edges]
        front = [v for v in nxt if ring[v] > d]
    return ring


def smooth_boundary(bm, bvh, iterations):
    """Relax the open boundary of a face-selected shell along the surface, so
    its edge (a hairline, a beard line) is a smooth curve rather than the
    staircase of whole faces it was cut from. Boundary vertices move toward
    their boundary neighbours and are snapped back onto the surface."""
    edge = [v for v in bm.verts if v.is_boundary]
    nbrs = {v: [e.other_vert(v) for e in v.link_edges if e.is_boundary] for v in edge}
    for _ in range(iterations):
        new = {}
        for v in edge:
            n = nbrs[v]
            if len(n) != 2:
                continue
            target = v.co * 0.5 + (n[0].co + n[1].co) * 0.25
            loc, _, _, _ = bvh.find_nearest(target)
            new[v] = loc if loc is not None else target
        for v, co in new.items():
            v.co = co


def offset_shell(bm, thickness, taper):
    """Push every vertex out along its normal: thickness(v) in the interior,
    scaled by taper[ring] within len(taper) rings of the boundary, so the
    shell's edge melts into the skin instead of ending in a step."""
    bm.normal_update()
    ring = edge_rings(bm, len(taper))
    moves = []
    for v in bm.verts:
        k = taper[ring[v]] if ring[v] < len(taper) else 1.0
        moves.append((v, v.normal.copy() * thickness(v) * k))
    for v, d in moves:
        v.co += d


def finish(b, obj, bm, mat):
    """Write bm back, set the material, skin to the staged armature, and
    register the object for export."""
    src = bm.verts.layers.int.get("src")
    if src is not None:
        bm.verts.layers.int.remove(src)
    bm.to_mesh(obj.data)
    bm.free()
    me = obj.data
    me.materials.clear()
    me.materials.append(mat)
    for p in me.polygons:
        p.material_index = 0
        p.use_smooth = True
    arm = b.armature()
    bones = set(bn.name for bn in arm.data.bones)
    for g in list(obj.vertex_groups):
        if g.name not in bones:
            obj.vertex_groups.remove(g)
    obj.parent = arm
    obj.matrix_parent_inverse = arm.matrix_world.inverted()
    mod = next((m for m in obj.modifiers if m.type == "ARMATURE"), None) \
        or obj.modifiers.new("Armature", "ARMATURE")
    mod.object = arm
    b.export_objs.append(obj)
    return obj


def resample(pts, n):
    """n + 1 points evenly spaced by arc length along the polyline pts."""
    acc = [0.0]
    for a, c in zip(pts, pts[1:]):
        acc.append(acc[-1] + (c - a).length)
    total = acc[-1]
    out, j = [], 0
    for i in range(n + 1):
        s = total * i / n
        while j < len(acc) - 2 and acc[j + 1] < s:
            j += 1
        seg = acc[j + 1] - acc[j]
        t = 0.0 if seg <= 0 else (s - acc[j]) / seg
        out.append(pts[j].lerp(pts[j + 1], min(max(t, 0.0), 1.0)))
    return out, total


def tube(bm, uv, uv2, dl, weights, path, outward, radius, aspect, sides, tag):
    """Tapered, flattened tube along path (closed to a point at the tip,
    open at the root, which is buried in the cap). outward(i) gives the
    surface normal the tube's flat side lies against; radius(t) the
    half-width (half-thickness = half-width / aspect). UV0: u around, v root
    -> tip (the Kajiya-Kay tangent direction). UV1: tag (per-clump random,
    side sign). Returns the number of triangles added."""
    n = len(path) - 1
    rings = []
    prev_nrm = None
    for i, p in enumerate(path):
        t = i / n
        tan = (path[min(i + 1, n)] - path[max(i - 1, 0)]).normalized()
        nrm = outward(i)
        nrm = (nrm - tan * tan.dot(nrm))
        if nrm.length < 1e-6:
            nrm = prev_nrm or Vector((0, 0, 1))
        nrm.normalize()
        if prev_nrm is not None:
            nrm = (nrm + prev_nrm * 0.6)
            nrm = (nrm - tan * tan.dot(nrm)).normalized()
        prev_nrm = nrm
        bi = tan.cross(nrm)
        if i == n:
            rings.append([bm.verts.new(p)])
            continue
        hw = radius(t)
        ht = hw / aspect
        ring = []
        for k in range(sides):
            a = 2 * math.pi * k / sides
            ring.append(bm.verts.new(p + bi * (math.cos(a) * hw) + nrm * (math.sin(a) * ht)))
        rings.append(ring)
    for ring in rings:
        for v in ring:
            for g, w in weights.items():
                v[dl][g] = w
    tris = 0
    for i in range(n):
        r0, r1 = rings[i], rings[i + 1]
        v0, v1 = i / n, (i + 1) / n
        for k in range(sides):
            k1 = (k + 1) % sides
            u0, u1 = k / sides, (k + 1) / sides
            # Winding: (around) x (along) points inward, so go along first.
            if len(r1) == 1:
                f = bm.faces.new((r0[k], r1[0], r0[k1]))
                uvs = ((u0, v0), ((u0 + u1) / 2, v1), (u1, v0))
                tris += 1
            else:
                f = bm.faces.new((r0[k], r1[k], r1[k1], r0[k1]))
                uvs = ((u0, v0), (u0, v1), (u1, v1), (u1, v0))
                tris += 2
            for loop, c in zip(f.loops, uvs):
                loop[uv].uv = c
                loop[uv2].uv = tag
    return tris
