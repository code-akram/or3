"""Parametric garment construction (suit track, bench/m1/suit.md).

Garments are lofted from cross-sections of the unmasked body: horizontal
slices for the torso and legs, slices perpendicular to the bone axis for arms.
Each slice is a polar profile (max radius per angular bin), smoothed and
"canvassed" (chord-filled, so the cloth bridges hollows instead of following
the anatomy), then eased outward by the tailoring allowance. Rows of rings
become quad grids with metric UVs (u along the ring, v along the loft) so the
texture pass can place seams by (column, row). Skin weights come from the
nearest body vertex of the garment's bone set, so layered garments built from
the same slices deform together.

World space = object space for every staged mesh (identity transforms, Z up,
front = -Y, the wearer's left = +X).
"""

import math

import bmesh
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

TAU = 2 * math.pi
TORSO = {"pelvis", "spine_01", "spine_02", "spine_03", "clavicle_l", "clavicle_r", "neck_01"}
ARM = {"l": {"upperarm_l", "lowerarm_l", "hand_l"}, "r": {"upperarm_r", "lowerarm_r", "hand_r"}}
LEG = {"l": {"thigh_l", "calf_l", "foot_l", "ball_l"}, "r": {"thigh_r", "calf_r", "foot_r", "ball_r"}}


def smoothstep(t):
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def lerp(a, b, t):
    return a + (b - a) * t


# --- body ----------------------------------------------------------------------------------

class Body:
    """The unmasked body in rest pose: skin vertices with their dominant bone,
    joints, and nearest-vertex weight lookups per bone set."""

    def __init__(self, src_me, names, arm):
        self.names = names
        self.arm = arm
        self.bm = bmesh.new()
        self.bm.from_mesh(src_me)
        self.bm.verts.ensure_lookup_table()
        self.dl = self.bm.verts.layers.deform.verify()
        self.bones = set(arm.data.bones.keys())
        body_g = names.index("body")
        self.dom = {}
        for v in self.bm.verts:
            if v[self.dl].get(body_g, 0) <= 0:
                continue
            best, bw = None, 0.0
            for g, w in v[self.dl].items():
                n = names[g]
                if n in self.bones and w > bw:
                    best, bw = n, w
            if best:
                self.dom[v.index] = best
        self._kd = {}
        self._bvh = None

    def free(self):
        self.bm.free()

    def joint(self, name):
        return self.arm.matrix_world @ self.arm.data.bones[name].head_local

    def tail(self, name):
        return self.arm.matrix_world @ self.arm.data.bones[name].tail_local

    def verts(self, bones):
        return [self.bm.verts[i] for i, d in self.dom.items() if d in bones]

    def kd(self, bones):
        key = frozenset(bones)
        if key not in self._kd:
            vs = self.verts(bones)
            kd = KDTree(len(vs))
            for i, v in enumerate(vs):
                kd.insert(v.co, i)
            kd.balance()
            self._kd[key] = (kd, vs)
        return self._kd[key]

    def weights(self, co, bones):
        kd, vs = self.kd(bones)
        _, i, _ = kd.find(co)
        v = vs[i]
        return {self.names[g]: w for g, w in v[self.dl].items()
                if self.names[g] in self.bones and w > 1e-4}

    def bvh(self):
        if self._bvh is None:
            self._bvh = BVHTree.FromBMesh(self.bm)
        return self._bvh

    def extent(self, bones, axis):
        cs = [v.co[axis] for v in self.verts(bones)]
        return min(cs), max(cs)


# --- polar profiles -------------------------------------------------------------------------

def polar_profile(pts, nbins):
    """pts: (x, y) relative to the centre. Max radius per angular bin, with
    empty bins interpolated circularly. Bin k covers angle [k, k+1) * TAU/nbins."""
    r = [None] * nbins
    for x, y in pts:
        a = math.atan2(y, x) % TAU
        k = int(a / TAU * nbins) % nbins
        d = math.hypot(x, y)
        if r[k] is None or d > r[k]:
            r[k] = d
    known = [i for i in range(nbins) if r[i] is not None]
    if not known:
        raise ValueError("empty profile")
    if len(known) < nbins:
        out = list(r)
        for i in range(nbins):
            if r[i] is None:
                p = max([k for k in known if k < i], default=known[-1] - nbins)
                n = min([k for k in known if k > i], default=known[0] + nbins)
                t = (i - p) / (n - p)
                out[i] = r[p % nbins] * (1 - t) + r[n % nbins] * t
        r = out
    return r


def smooth_ring(r, iters=1):
    n = len(r)
    for _ in range(iters):
        r = [(r[i - 1] + 2 * r[i] + r[(i + 1) % n]) / 4 for i in range(n)]
    return r


def chord_fill(r, ks=(2, 4, 8, 12), iters=3, limit=None):
    """Bridge hollows: lift each radius to the chord between the bins k steps
    either side (the cloth spans the sternum, the small of the back). `limit`
    caps the lift in metres."""
    n = len(r)
    r0 = list(r)
    for _ in range(iters):
        for k in ks:
            c = math.cos(k * TAU / n)
            r = [max(r[i], 0.5 * (r[i - k] + r[(i + k) % n]) * c) for i in range(n)]
    if limit is not None:
        r = [min(r[i], r0[i] + limit) for i in range(n)]
    return r


def sample_ring(r, a):
    """Radius at angle a (radians) by circular linear interpolation."""
    n = len(r)
    x = (a % TAU) / TAU * n - 0.5
    i = math.floor(x)
    t = x - i
    return r[i % n] * (1 - t) + r[(i + 1) % n] * t


def slice_profile(verts, z, band, nbins=180, min_pts=40, max_band=0.05):
    """Horizontal slice of `verts` at height z: (cy, radii) with cy the centre
    (x = 0, y = mid-extent). The band widens until min_pts vertices are in it."""
    while True:
        pts = [v.co for v in verts if abs(v.co.z - z) < band]
        if len(pts) >= min_pts or band >= max_band:
            break
        band *= 1.5
    if len(pts) < 3:
        raise ValueError(f"no slice at z={z:.3f}")
    ys = [p.y for p in pts]
    cy = 0.5 * (min(ys) + max(ys))
    return cy, polar_profile([(p.x, p.y - cy) for p in pts], nbins)


# --- grids ----------------------------------------------------------------------------------

class Grid:
    """Rows of vertices (equal length) joined by quads, in one bmesh. Row 0 is
    the bottom; columns run the ring. UVs in metres: u along the row, v up."""

    def __init__(self, bm, name="grid"):
        self.bm = bm
        self.name = name
        self.rows = []     # [[BMVert]]
        self.uvs = []      # [[(u, v)]] per row vertex
        self.faces = []

    def add_row(self, points, uvs):
        row = [self.bm.verts.new(p) for p in points]
        self.rows.append(row)
        self.uvs.append(list(uvs))
        return row

    def add_shared_row(self, verts, uvs):
        """A row of existing vertices (a seam shared with another grid)."""
        self.rows.append(list(verts))
        self.uvs.append(list(uvs))
        return verts

    def fill(self, uv_layer, tag_layer=None, tag=0, skip=None, smooth=True, flip=False):
        """Quads between consecutive rows. Degenerate quads (two coincident
        vertices) become triangles, fully degenerate ones are skipped."""
        for k in range(len(self.rows) - 1):
            a, b = self.rows[k], self.rows[k + 1]
            ua, ub = self.uvs[k], self.uvs[k + 1]
            for i in range(len(a) - 1):
                if skip and skip(k, i):
                    continue
                quad = [(a[i], ua[i]), (a[i + 1], ua[i + 1]), (b[i + 1], ub[i + 1]), (b[i], ub[i])]
                if flip:
                    quad.reverse()
                uniq = []
                for v, uv in quad:
                    if not any(v is u[0] for u in uniq):
                        uniq.append((v, uv))
                if len(uniq) < 3:
                    continue
                try:
                    f = self.bm.faces.new([v for v, _ in uniq])
                except ValueError:
                    continue
                f.smooth = smooth
                for loop, (_, uv) in zip(f.loops, uniq):
                    loop[uv_layer].uv = uv
                if tag_layer is not None:
                    f[tag_layer] = tag
                self.faces.append(f)
        return self.faces

    def column(self, i):
        return [row[i] for row in self.rows]


def point_at_arc(points, s):
    """Point at arc length s along the polyline `points` (clamped)."""
    if s <= 0:
        return points[0].copy()
    acc = 0.0
    for a, b in zip(points, points[1:]):
        L = (b - a).length
        if acc + L >= s:
            return a.lerp(b, (s - acc) / L if L else 0.0)
        acc += L
    return points[-1].copy()


def arc_length(points, closed=False):
    pts = points + ([points[0]] if closed else [])
    return sum((b - a).length for a, b in zip(pts, pts[1:]))


def ring_points_resample(points, n):
    """n points evenly spaced by arc length along a closed polyline."""
    segs = [(points[i], points[(i + 1) % len(points)]) for i in range(len(points))]
    total = sum((b - a).length for a, b in segs)
    out, acc, k = [], 0.0, 0
    for i in range(n):
        target = total * i / n
        while k < len(segs) - 1 and acc + (segs[k][1] - segs[k][0]).length < target:
            acc += (segs[k][1] - segs[k][0]).length
            k += 1
        a, b = segs[k]
        L = (b - a).length
        out.append(a.lerp(b, (target - acc) / L if L else 0.0))
    return out


def ring_points(cy, radii, z, a0, a1, n, ease=None):
    """n + 1 points on the slice profile from angle a0 to a1 (a1 > a0, may
    exceed TAU), at height z. ease(angle) adds to the radius."""
    out = []
    for i in range(n + 1):
        a = a0 + (a1 - a0) * i / n
        r = sample_ring(radii, a) + (ease(a) if ease else 0.0)
        out.append(Vector((r * math.cos(a), cy + r * math.sin(a), z)))
    return out


def angle_at_x(cy, radii, x, front=True, ease=None):
    """Angle on the (eased) profile whose point has the given x, on the front
    (y < cy) or back half. Searched on a fine grid, then refined linearly."""
    lo, hi = (-math.pi, 0.0) if front else (0.0, math.pi)
    best, bd = None, 1e9
    steps = 720
    prev = None
    for i in range(steps + 1):
        a = lo + (hi - lo) * i / steps
        r = sample_ring(radii, a) + (ease(a) if ease else 0.0)
        px = r * math.cos(a)
        if prev is not None and (prev[1] - x) * (px - x) <= 0:
            a_prev, x_prev = prev
            t = (x - x_prev) / (px - x_prev) if px != x_prev else 0.0
            return a_prev + (a - a_prev) * t
        d = abs(px - x)
        if d < bd:
            best, bd = a, d
        prev = (a, px)
    return best


# --- objects ---------------------------------------------------------------------------------

def disc(bm, dl, centre, normal, radius, height, weights, segs=8, uv_layer=None, uv_at=(0, 0),
         uv_scale=1.0):
    """A button: a ring on the host surface, a ring lifted by `height`, a flat
    front cap (segs - 2 tris + 2 * segs side tris)."""
    n = normal.normalized()
    t = n.orthogonal().normalized()
    u = n.cross(t)
    back, front = [], []
    for i in range(segs):
        a = TAU * i / segs
        off = (t * math.cos(a) + u * math.sin(a)) * radius
        back.append(bm.verts.new(centre + off - n * 0.001))
        front.append(bm.verts.new(centre + off * 0.85 + n * height))
    for v in back + front:
        for g, w in weights.items():
            v[dl][g] = w
    faces = []
    for i in range(segs):
        j = (i + 1) % segs
        f = bm.faces.new([back[i], back[j], front[j], front[i]])
        f.smooth = True
        faces.append(f)
    cap = bm.faces.new(front)
    cap.smooth = False
    faces.append(cap)
    if uv_layer is not None:
        for f in faces:
            for loop in f.loops:
                p = loop.vert.co - centre
                loop[uv_layer].uv = (uv_at[0] + p.dot(t) * uv_scale, uv_at[1] + p.dot(u) * uv_scale)
    bmesh.ops.triangulate(bm, faces=[cap])


class Garment:
    """A bmesh with deform, UV and panel-tag layers that becomes one staged,
    skinned object."""

    def __init__(self, name, arm, body):
        self.name = name
        self.arm = arm
        self.body = body
        self.bm = bmesh.new()
        self.dl = self.bm.verts.layers.deform.verify()
        self.uv = self.bm.loops.layers.uv.verify()
        self.tag = self.bm.faces.layers.int.new("panel")
        self.bone_names = list(arm.data.bones.keys())
        self.gidx = {n: i for i, n in enumerate(self.bone_names)}
        self.marks = {}     # tag -> [(kind, data, ...)] in panel-metric UVs (suit_textures)

    def grid(self, name):
        return Grid(self.bm, name)

    def mark(self, tag, kind, data, *extra):
        self.marks.setdefault(tag, []).append((kind, data) + extra)

    def mark_column(self, tag, grid, i, kind, rows=None, **kw):
        """A mark down column i of a grid (over `rows`, default all)."""
        ks = range(len(grid.rows)) if rows is None else rows
        pts = [grid.uvs[k][i] for k in ks]
        pts = [p for j, p in enumerate(pts) if j == 0 or p != pts[j - 1]]
        if len(pts) >= 2:
            self.mark(tag, kind, pts, kw) if kw else self.mark(tag, kind, pts)

    def mark_row(self, tag, grid, k, kind, cols=None, **kw):
        cs = range(len(grid.rows[k])) if cols is None else cols
        pts = [grid.uvs[k][i] for i in cs]
        pts = [p for j, p in enumerate(pts) if j == 0 or p != pts[j - 1]]
        if len(pts) >= 2:
            self.mark(tag, kind, pts, kw) if kw else self.mark(tag, kind, pts)

    def weight(self, verts, bones, mix=None):
        """Nearest-body-vertex weights for `verts` from the bone set. mix:
        (bone, factor) blends toward a single bone."""
        for v in verts:
            w = self.body.weights(v.co, bones)
            if mix:
                bone, f = mix
                w = {k: x * (1 - f) for k, x in w.items()}
                w[bone] = w.get(bone, 0.0) + f
            v[self.dl].clear()
            for k, x in w.items():
                v[self.dl][self.gidx[k]] = x

    def copy_weights(self, src, dst):
        dst[self.dl].clear()
        for g, w in src[self.dl].items():
            dst[self.dl][g] = w

    def finish(self, b, like, material=None):
        """Create the object next to `like` (same parent and collections),
        with an armature modifier, and register it for export."""
        bm = self.bm
        # degenerate faces (zero area: coincident vertices at a seam wrap or a
        # collapsed row) export zero tangents, a glTF validator error
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)

        def area(f):  # vector area, zero for collinear faces (calc_area is not)
            vs = [v.co for v in f.verts]
            s = Vector((0, 0, 0))
            for i in range(len(vs)):
                s += vs[i].cross(vs[(i + 1) % len(vs)])
            return 0.5 * s.length

        degenerate = [f for f in bm.faces if area(f) < 1e-9]
        if degenerate:
            bmesh.ops.delete(bm, geom=degenerate, context="FACES_ONLY")
        loose = [v for v in bm.verts if not v.link_faces]
        if loose:
            bmesh.ops.delete(bm, geom=loose, context="VERTS")
        # faces without UV area give zero tangents (glTF validator error): nudge
        flat = 0
        for f in bm.faces:
            uvs = [l[self.uv].uv for l in f.loops]
            area = 0.0
            for i in range(len(uvs)):
                p, q = uvs[i], uvs[(i + 1) % len(uvs)]
                area += p.x * q.y - q.x * p.y
            if abs(area) < 1e-12:
                for i, l in enumerate(f.loops):
                    l[self.uv].uv = (uvs[i].x + 0.0004 * math.cos(i * 2.1), uvs[i].y + 0.0004 * math.sin(i * 2.1))
                flat += 1
        self.stats = {"loose_verts_removed": len(loose), "flat_uv_faces_fixed": flat,
                      "degenerate_faces_removed": len(degenerate)}
        bm.normal_update()
        me = bpy.data.meshes.new(self.name)
        bm.to_mesh(me)
        bm.free()
        ob = bpy.data.objects.new(self.name, me)
        for n in self.bone_names:
            ob.vertex_groups.new(name=n)
        ob.parent = like.parent
        ob.matrix_parent_inverse = like.matrix_parent_inverse.copy()
        mod = ob.modifiers.new("Armature", "ARMATURE")
        mod.object = self.arm
        for c in like.users_collection:
            c.objects.link(ob)
        if material is not None:
            me.materials.append(material)
        b.export_objs.append(ob)
        return ob


def bvh_of(objs):
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


def bvh_of_bm(bm):
    return BVHTree.FromBMesh(bm)


def tuck_under(verts, outer_tree, gap=0.002, reach=0.03):
    """Inner-layer vertices that poke out of the surface in `outer_tree` are
    moved back inside it (gap below the surface). A vertex with the outer
    surface in front of it (along its normal) is already covered."""
    moved = 0
    for v in verts:
        n = v.normal
        if outer_tree.ray_cast(v.co + n * 0.0005, n, reach)[0] is not None:
            continue
        hit = outer_tree.ray_cast(v.co, -n, reach)
        if hit[0] is not None and hit[1].dot(n) > 0:
            v.co = hit[0] - n * gap
            moved += 1
    return moved


def clear_of_body(tree, pts, clear, reach=0.08):
    """Push every point of `pts` (Vectors or BMVerts, moved in place) out
    along the nearest body normal until it is `clear` metres off the skin.
    Returns the number moved."""
    moved = 0
    for p in pts:
        co = p.co if hasattr(p, "co") else p
        hit = tree.find_nearest(co, reach)
        if hit[0] is None:
            continue
        d = (co - hit[0]).dot(hit[1])
        if d < clear:
            co = co + hit[1] * (clear - d)
            if hasattr(p, "co"):
                p.co = co
            else:
                p[:] = co
            moved += 1
    return moved


def lift_onto_body(tree, pts, clear, above=0.08, min_nz=0.3):
    """Points under the body's top surface (the trapezius, the deltoid cap)
    are raised to `clear` above it: a ray from `above` metres over the point
    straight down finds the skin between. Only up-facing skin counts (a ray
    that starts inside the body and leaves through its underside is ignored).
    Moved in place; returns the count."""
    moved = 0
    down = Vector((0, 0, -1))
    for p in pts:
        co = p.co if hasattr(p, "co") else p
        hit = tree.ray_cast(co + Vector((0, 0, above)), down, above)
        if hit[0] is None or hit[1].z < min_nz:
            continue
        z = hit[0].z + clear
        if z > co.z:
            co = Vector((co.x, co.y, z))
            if hasattr(p, "co"):
                p.co = co
            else:
                p[:] = co
            moved += 1
    return moved


def offset_from(tree, p, n, gap, back=0.01, reach=0.06):
    """Move p out along n until it is `gap` clear of the surface in `tree`
    (ray from behind p). Returns the new point."""
    hit = tree.ray_cast(p - n * back, n, reach + back)
    if hit[0] is None:
        return p
    d = hit[3] - back  # surface distance along n from p (negative: p is already outside)
    if d + gap > 0:
        return p + n * (d + gap)
    return p
