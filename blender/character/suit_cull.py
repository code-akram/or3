"""Hidden-face culling for the made suit's under-layers (m1 v4 T13d, item 8 budget and penetration).

The shirt and the waistcoat are almost all under the jacket (T13c: 7309 of the shirt's 7561 drape
vertices and 3312 of the waistcoat's 3577 covered at rest). What the jacket hides in every pose of the
rig's pose set never needs to be drawn, and what is not drawn cannot be pierced by the jacket's
runtime fit. A point counts as visible in a pose when one ray from it, in a cone about its outward
normal, leaves the character without hitting an occluder (the body, the layers over it) within reach;
a face is culled when every point it rides on is hidden in every pose, after the visible set is grown
by a margin on the mesh (the edges of an opening).

numpy + mathutils only (runs inside Blender, in the suit spike's posed run).
"""

import math

import numpy as np


def cone_dirs(tilts_deg=(0.0, 45.0, 75.0), k=8):
    """Unit directions in a local frame (z = the normal): the normal, then k azimuths per tilt."""
    out = []
    for t in tilts_deg:
        if t == 0:
            out.append((0.0, 0.0, 1.0))
            continue
        tr = math.radians(t)
        for j in range(k):
            a = 2 * math.pi * (j + 0.5 * (len(out) % 2)) / k
            out.append((math.sin(tr) * math.cos(a), math.sin(tr) * math.sin(a), math.cos(tr)))
    return np.array(out)


def frames(N):
    """An orthonormal (t, b, n) frame per unit normal."""
    a = np.where(np.abs(N[:, 2:3]) < 0.9, np.array([[0.0, 0.0, 1.0]]), np.array([[1.0, 0.0, 0.0]]))
    t = np.cross(a, N)
    t /= np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-12)
    b = np.cross(N, t)
    return t, b


def bvh_of(meshes):
    """One BVH over [(V (n, 3), F (polygons))]."""
    from mathutils.bvhtree import BVHTree
    V, F = [], []
    for v, f in meshes:
        n0 = len(V)
        V += [tuple(map(float, p)) for p in v]
        F += [tuple(n0 + int(i) for i in fc) for fc in f]
    return BVHTree.FromPolygons(V, F)


def visible(P, N, bvh, dirs, todo, eps=0.0015, reach=0.6, zmin=None):
    """For points P (n, 3) with unit outward normals N: True where some ray in the cone (dirs, local
    frame) misses every occluder in bvh within reach. Only points in `todo` are tested. zmin: no
    camera views from further below the horizontal than that (a ray's z under zmin is not tried:
    a look up the jacket's hem or a hanging sleeve)."""
    from mathutils import Vector
    t, b = frames(N)
    out = np.zeros(len(P), bool)
    for i in np.nonzero(todo)[0]:
        o = P[i] + N[i] * eps
        for d in dirs:
            w = t[i] * d[0] + b[i] * d[1] + N[i] * d[2]
            if zmin is not None and w[2] < zmin:
                continue
            if bvh.ray_cast(Vector(o), Vector(w), reach)[0] is None:
                out[i] = True
                break
    return out


def adjacency(F, n):
    """Vertex neighbours from polygons (lists of sets)."""
    nb = [set() for _ in range(n)]
    for f in F:
        f = [int(i) for i in f]
        for a, b in zip(f, f[1:] + f[:1]):
            nb[a].add(b)
            nb[b].add(a)
    return nb


def grow(mask, nb, rings):
    m = mask.copy()
    for _ in range(rings):
        new = m.copy()
        for i in np.nonzero(m)[0]:
            for j in nb[i]:
                new[j] = True
        m = new
    return m


def grow_dist(mask, X, nb, dist):
    """Grow a vertex set over the mesh edges until dist (m) from it (Dijkstra on edge lengths)."""
    import heapq
    d = np.full(len(X), np.inf)
    h = []
    for i in np.nonzero(mask)[0]:
        d[i] = 0.0
        h.append((0.0, int(i)))
    heapq.heapify(h)
    while h:
        di, i = heapq.heappop(h)
        if di > d[i] or di > dist:
            continue
        for j in nb[i]:
            dj = di + float(np.linalg.norm(X[i] - X[j]))
            if dj < d[j] and dj <= dist:
                d[j] = dj
                heapq.heappush(h, (dj, j))
    return d <= dist


def face_keep(F, vert_keep):
    """A polygon is kept when any of its vertices is kept."""
    return np.array([bool(vert_keep[list(f)].any()) for f in F])


def drop_faces(ob, keep):
    """Delete the polygons of `ob` not in keep, and the vertices left loose (shape keys and vertex
    groups follow, bmesh keeps them). Returns (faces before, faces after)."""
    import bmesh
    me = ob.data
    n0 = len(me.polygons)
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    gone = [bm.faces[i] for i in range(len(bm.faces)) if not keep[i]]
    bmesh.ops.delete(bm, geom=gone, context="FACES")
    loose = [v for v in bm.verts if not v.link_faces]
    bmesh.ops.delete(bm, geom=loose, context="VERTS")
    bm.to_mesh(me)
    bm.free()
    me.update()
    return n0, len(me.polygons)


def tri_count(F):
    return int(sum(len(f) - 2 for f in F))
