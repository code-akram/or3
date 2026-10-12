"""Geometry helpers for the suit track (blender/character/suit.py).

World space = object space for every staged mesh (identity transforms, Z up,
front = -Y). Skin weights travel in each bmesh's deform layer; parts that were
split from one object share its vertex-group order, other meshes are mapped by
group name.
"""

import math

import bmesh
import bpy
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

TORSO_BONES = {"pelvis", "spine_01", "spine_02", "spine_03", "clavicle_l", "clavicle_r"}


# --- objects and bmesh ---------------------------------------------------------------------

def to_bm(o):
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bm.verts.ensure_lookup_table()
    return bm


def write_bm(bm, o):
    bm.to_mesh(o.data)
    o.data.update()
    bm.free()


def bvh(objs):
    """One BVH over several meshes (rest pose, world space)."""
    bm = bmesh.new()
    for o in objs:
        tmp = bmesh.new()
        tmp.from_mesh(o.data)
        tmp.transform(o.matrix_world)
        me = bpy.data.meshes.new("_tmp_bvh")
        tmp.to_mesh(me)
        tmp.free()
        bm.from_mesh(me)
        bpy.data.meshes.remove(me)
    tree = BVHTree.FromBMesh(bm)
    bm.free()
    return tree


def components(bm):
    """Vertex-index sets of the connected (loose) parts."""
    seen, out = set(), []
    for v in bm.verts:
        if v.index in seen:
            continue
        stack, comp = [v], set()
        seen.add(v.index)
        while stack:
            x = stack.pop()
            comp.add(x.index)
            for e in x.link_edges:
                y = e.other_vert(x)
                if y.index not in seen:
                    seen.add(y.index)
                    stack.append(y)
        out.append(comp)
    return out


def new_part(src, keep, name):
    """A new object holding only the vertices `keep` of src (same groups, parent,
    modifiers, materials)."""
    bm = to_bm(src)
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.index not in keep], context="VERTS")
    o = src.copy()
    o.data = bpy.data.meshes.new(name)
    for g in src.vertex_groups:  # group names live on the mesh (Blender >= 3.0)
        o.vertex_groups.new(name=g.name)
    for m in src.data.materials:
        o.data.materials.append(m)
    o.name = name
    for c in src.users_collection:
        c.objects.link(o)
    write_bm(bm, o)
    return o


def join_into(dst, src):
    """Append src's geometry into dst (groups mapped by name), then delete src."""
    names = [g.name for g in src.vertex_groups]
    for n in names:
        if n not in dst.vertex_groups:
            dst.vertex_groups.new(name=n)
    remap = {i: dst.vertex_groups[n].index for i, n in enumerate(names)}
    bm = to_bm(dst)
    dl = bm.verts.layers.deform.verify()
    sb = to_bm(src)
    sdl = sb.verts.layers.deform.verify()
    vmap = {}
    for v in sb.verts:
        nv = bm.verts.new(v.co)
        for g, w in v[sdl].items():
            nv[dl][remap[g]] = w
        vmap[v.index] = nv
    for f in sb.faces:
        nf = bm.faces.new([vmap[v.index] for v in f.verts])
        nf.smooth = f.smooth
    sb.free()
    write_bm(bm, dst)
    bpy.data.objects.remove(src, do_unlink=True)


def dominant(v, dl, names, allowed):
    best, bw = None, 0.0
    for g, w in v[dl].items():
        n = names[g]
        if n in allowed and w > bw:
            best, bw = n, w
    return best


# --- deformation-free edits ----------------------------------------------------------------

def stretch_below(verts, z_top, z_from, z_to, weight=None):
    """Remap z below z_top linearly so z_from lands on z_to (x, y unchanged).
    weight(v) in [0, 1] blends the stretch per vertex (1 = full)."""
    k = (z_top - z_to) / (z_top - z_from)
    for v in verts:
        if v.co.z < z_top:
            t = 1.0 if weight is None else weight(v)
            z = z_top - (z_top - v.co.z) * k
            v.co.z = v.co.z + (z - v.co.z) * t


def panel_side(v, rings=3):
    """+1 / -1: which front panel v belongs to, from the mean x of its
    neighbourhood (the panels overlap across x = 0 near the front edge)."""
    seen, frontier = {v}, [v]
    for _ in range(rings):
        nxt = []
        for x in frontier:
            for e in x.link_edges:
                y = e.other_vert(x)
                if y not in seen:
                    seen.add(y)
                    nxt.append(y)
        frontier = nxt
    mx = sum(x.co.x for x in seen) / len(seen)
    return 1 if mx >= 0 else -1


def open_front(bm, z_button, z_ref, strip, blend=0.05, y_front=-0.05):
    """Open the jacket's V down to the fastening button: between z_button and
    z_ref, each panel's strip from its front edge to (half-width + strip) is
    compressed into [half-width, half-width + strip], where the half-width runs
    linearly from 0 at the button to the edge's own position at z_ref."""
    band = [v for v in bm.verts if v.co.y < y_front and z_button - 0.02 < v.co.z < z_ref + 0.02
            and abs(v.co.x) < 0.2]
    side = {v: panel_side(v) for v in band}

    edges = {}  # (side, cm bucket) -> front-edge position, from the unmoved mesh
    for v in band:
        k = (side[v], round(v.co.z * 100))
        edges[k] = min(edges.get(k, 9.0), side[v] * v.co.x)

    def edge_at(s, z):
        b = round(z * 100)
        xs = [edges[(s, k)] for k in (b - 1, b, b + 1) if (s, k) in edges]
        return min(xs) if xs else 0.0

    moved = 0
    for s in (1, -1):
        x_ref = edge_at(s, z_ref)
        for v in [v for v in band if side[v] == s]:
            z = v.co.z
            if not (z_button < z < z_ref):
                continue
            x0 = edge_at(s, z)
            ht = x_ref * (z - z_button) / (z_ref - z_button)
            if x0 >= ht:
                continue
            t = min(1.0, (z - z_button) / blend)  # ease in from the closed front
            xt = x0 + (ht - x0) * t * t * (3 - 2 * t)
            sx = s * v.co.x
            hi = xt + strip
            if sx >= hi:
                continue
            v.co.x = s * (xt + (sx - x0) * strip / max(hi - x0, 1e-6))
            moved += 1
    return moved


def walk_up(start, z_stop, x_target, max_dx=0.02):
    """Edge chain from start going up as vertically as possible, staying within
    max_dx of x_target. Returns the edges."""
    v, edges = start, []
    while v.co.z < z_stop:
        best, bs = None, -1.0
        for e in v.link_edges:
            o = e.other_vert(v)
            d = o.co - v.co
            if d.z <= 1e-6 or abs(o.co.x - x_target) > max_dx:
                continue
            s = d.z / d.length - 2.0 * abs(o.co.x - x_target)
            if s > bs:
                best, bs = e, s
        if best is None:
            break
        edges.append(best)
        v = best.other_vert(v)
    return edges


def split_slit(bm, edges, outward, depth_top):
    """Split a vertical edge chain into a vent: the two flaps get coincident
    copies; the flap on the `outward` side (+1: larger |x|, 0: centre vent, the
    +x flap) is lifted along its normal, tapering to 0 at depth_top."""
    path_x = sum(e.verts[0].co.x for e in edges) / len(edges)
    z_bot = min(min(e.verts[0].co.z, e.verts[1].co.z) for e in edges)
    res = bmesh.ops.split_edges(bm, edges=edges)
    bm.normal_update()
    lifted = set()
    for e in res["edges"]:
        for v in e.verts:
            if v in lifted or not v.link_faces:
                continue
            cx = sum(f.calc_center_median().x for f in v.link_faces) / len(v.link_faces)
            side = cx - path_x
            on_outer = (abs(cx) > abs(path_x)) if outward else (side > 0)
            if not on_outer:
                continue
            t = max(0.0, 1.0 - (v.co.z - z_bot) / max(depth_top - z_bot, 1e-6))
            v.co += v.normal * 0.004 * t
            lifted.add(v)
    return len(edges)


def crease(bm, verts, side_sign, front, z_lo, z_hi, depth):
    """Trouser crease on one leg: from the hem vertex nearest the leg's front
    (front=True) or back centre, walk up and push the chain out by depth; the
    chain's edges are marked sharp."""
    leg = [v for v in verts if v.co.x * side_sign > 0.005 and v.co.z < z_lo + 0.03]
    if not leg:
        return 0
    start = (min if front else max)(leg, key=lambda v: v.co.y)
    edges = walk_up(start, z_hi, start.co.x, max_dx=0.03)
    done = set()
    for e in edges:
        e.smooth = False
        for v in e.verts:
            if v not in done:
                v.co.y += -depth if front else depth
                done.add(v)
    return len(edges)


# --- garments built by script --------------------------------------------------------------

def disc(bm, dl, centre, normal, radius, height, weights, segs=8):
    """A button: a ring on the host surface, a ring lifted by `height`, a flat
    front cap (segs - 2 tris + 2 * segs side tris)."""
    n = normal.normalized()
    t = n.orthogonal().normalized()
    u = n.cross(t)
    back, front = [], []
    for i in range(segs):
        a = 2 * math.pi * i / segs
        off = (t * math.cos(a) + u * math.sin(a)) * radius
        back.append(bm.verts.new(centre + off - n * 0.001))
        front.append(bm.verts.new(centre + off * 0.85 + n * height))
    for v in back + front:
        for g, w in weights.items():
            v[dl][g] = w
    for i in range(segs):
        j = (i + 1) % segs
        f = bm.faces.new([back[i], back[j], front[j], front[i]])
        f.smooth = True
    cap = bm.faces.new(front)
    cap.smooth = False
    bmesh.ops.triangulate(bm, faces=[cap])


def ring_resample(points, n):
    """n points evenly spaced by arc length along a closed polyline."""
    segs = [(points[i], points[(i + 1) % len(points)]) for i in range(len(points))]
    total = sum((b - a).length for a, b in segs)
    out, acc, k = [], 0.0, 0
    for i in range(n):
        target = total * i / n
        while acc + (segs[k][1] - segs[k][0]).length < target:
            acc += (segs[k][1] - segs[k][0]).length
            k += 1
        a, b = segs[k]
        L = (b - a).length
        out.append(a.lerp(b, (target - acc) / L if L else 0.0))
    return out


def boundary_loops(bm, verts):
    """Ordered boundary loops among `verts` (bmesh verts)."""
    vs = set(verts)
    edges = {e for v in vs for e in v.link_edges if e.is_boundary and all(x in vs for x in e.verts)}
    loops = []
    while edges:
        e = edges.pop()
        loop = [e.verts[0], e.verts[1]]
        while True:
            nxt = next((x for x in loop[-1].link_edges if x in edges), None)
            if nxt is None:
                break
            edges.discard(nxt)
            o = nxt.other_vert(loop[-1])
            if o is loop[0]:
                break
            loop.append(o)
        loops.append(loop)
    return loops


def nearest_weights(tree_kd, host_bm, host_dl, host_names, dst_index, co):
    _, i, _ = tree_kd.find(co)
    v = host_bm.verts[i]
    return {dst_index[host_names[g]]: w for g, w in v[host_dl].items() if host_names[g] in dst_index}


def kd_of(bm):
    kd = KDTree(len(bm.verts))
    for v in bm.verts:
        kd.insert(v.co, v.index)
    kd.balance()
    return kd
