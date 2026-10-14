"""Jacket details on the draped pattern jacket (m1 v4 T13 phase B item 1).

The drape is one welded sheet. This turns it into a made garment, all placed by pattern
coordinates (the draft's notches) so each detail sits where the cutter marked it and moves with
the cloth:

  shell        the cloth with thickness: the outside, the inside one cloth-thickness in, and a
               half-round turned edge on every free edge (hem, fronts, cuffs, neck). The inside
               is the lining, except the front facings and the hem and cuff turn-ups (wool)
  hip pockets  flap (rounded rim) under a jet, on both fronts; the front dart ends in the line
  breast welt  wearer's left, rising to the side
  vents        the back panel laps over the side panel from the hem up (both sides); the lap
               edge is a turned edge standing a cloth-thickness proud
  buttons      the front button (on CF, through the buttonhole) and four kissing buttons per
               cuff beside the hind seam; four holes each
  buttonhole   keyhole, on the left front, its eye under the button

numpy + mathutils (CDT). Units: metres in 3D, cm on the pattern. Faces carry a part tag:
0 wool outside, 1 lining, 2 turned edge / rim (wool), 3 button.
"""

import math

import numpy as np
from mathutils import Vector
from mathutils.geometry import delaunay_2d_cdt

from . import suit_pattern as sp

WOOL, LINING, EDGE, BUTTON = 0, 1, 2, 3

DEFAULTS = {
    "shell_thick_mm": 3.0,       # outside to lining at the edges (two cloths and the canvas)
    "edge_rings": 5,             # turned edge: segments in the half round (LOD0)
    "facing_cm": 7.0,            # wool facing inside the fronts
    "turnup_cm": 4.0,            # hem and cuff turn-ups (wool inside)
    "flap": {"thick_mm": 2.6, "lift_mm": 0.6, "corner_r_cm": 1.0, "h_cm": 0.5, "gap_cm": 0.08},
    "jet": {"thick_mm": 1.6, "lift_mm": 0.4},
    "welt": {"thick_mm": 2.8, "lift_mm": 0.5, "h_cm": 0.5},
    "vent": {"height_cm": 22.0, "sleeve_cm": 10.5, "step_mm": 2.5, "band_cm": 1.5, "fade_cm": 3.0},
    "button": {"front_diam_cm": 2.0, "front_thick_mm": 3.6, "cuff_thick_mm": 3.0, "stand_mm": 1.5,
               "seg": 32, "hole_r_frac": 0.05, "hole_at_frac": 0.12, "hole_depth_mm": 1.2},
    "buttonhole": {"cord_r_mm": 0.75, "eye_r_mm": 1.6, "gap_mm": 0.6},
}


# --- mesh helpers ------------------------------------------------------------------------------

def _norm(v):
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.maximum(n, 1e-12)


def vertex_normals(X, T):
    fn = np.cross(X[T[:, 1]] - X[T[:, 0]], X[T[:, 2]] - X[T[:, 0]])
    N = np.zeros_like(X)
    for k in range(3):
        np.add.at(N, T[:, k], fn)
    return _norm(N)


def boundary_loops(T):
    """Ordered boundary loops (vertex ids) of a triangle mesh, each in the faces' winding."""
    nxt = {}
    E = {}
    for t in T:
        for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            E[(int(a), int(b))] = E.get((int(a), int(b)), 0) + 1
    for (a, b) in E:
        if (b, a) not in E:
            nxt[a] = b
    loops, seen = [], set()
    for s in list(nxt):
        if s in seen:
            continue
        loop, v = [], s
        while v not in seen and v in nxt:
            seen.add(v)
            loop.append(v)
            v = nxt[v]
        if len(loop) > 2:
            loops.append(np.array(loop))
    return loops


def solid(X, T, N, t, rings, loops=None, keep=None):
    """Solidify a sheet inward (against N) by t (scalar or per vertex, m) with a half-round rim
    of `rings` segments on each boundary loop. keep: per-vertex mask; a boundary edge with both
    ends outside it gets no rim. Returns V, F (list of tuples), part (per face: 0 outside,
    1 inside, 2 rim)."""
    X = np.asarray(X, float)
    n = len(X)
    t = np.broadcast_to(np.asarray(t, float), (n,)).copy()
    N = np.asarray(N, float).copy()
    loops = boundary_loops(T) if loops is None else loops
    for b in loops:                      # smooth the boundary normals along each loop
        for _ in range(3):
            Nb = N[b]
            N[b] = _norm(np.roll(Nb, 1, 0) + 2.0 * Nb + np.roll(Nb, -1, 0))
    Xi = X - N * t[:, None]
    V = [X, Xi]
    F = [tuple(int(i) for i in f) for f in T] + [tuple(int(i) + n for i in f[::-1]) for f in T]
    part = [0] * len(T) + [1] * len(T)
    base = 2 * n
    inward = np.zeros((n, 3))
    cen = X[T].mean(1)
    for k in range(3):
        np.add.at(inward, T[:, k], cen - X[T[:, k]])
    for b in loops:
        nb = len(b)
        tan = X[np.roll(b, -1)] - X[np.roll(b, 1)]
        o = _norm(np.cross(tan, N[b]))
        flip = np.einsum("ij,ij->i", o, inward[b]) > 0
        o[flip] = -o[flip]
        r = 0.5 * t[b][:, None]
        C = X[b] - N[b] * r
        rows = [b]
        for m in range(1, rings):
            ph = math.pi * m / rings
            V.append(C + r * (N[b] * math.cos(ph) + o * math.sin(ph)))
            rows.append(base + np.arange(nb))
            base += nb
        rows.append(b + n)
        for k in range(nb):
            k2 = (k + 1) % nb
            if keep is not None and not (keep[b[k]] or keep[b[k2]]):
                continue
            for ra, rb in zip(rows[:-1], rows[1:]):
                # the loop runs in the faces' winding: the rim continues the outside's orientation
                F.append((int(ra[k2]), int(ra[k]), int(rb[k]), int(rb[k2])))
                part.append(EDGE)
    return np.vstack(V), F, np.array(part, int)


def cdt_patch(outline, h, holes=()):
    """Triangulate a closed 2D outline (cm) with an interior grid at ~h. Returns V (n, 2),
    T (m, 3), the outline's vertex ids in order."""
    from .suit_rever import _pip, _dist_polyline
    outline = np.asarray(outline, float)
    # resample the outline at ~h (keeping its vertices)
    pts = [outline[0]]
    for a, b in zip(outline, np.roll(outline, -1, 0)):
        k = max(1, int(round(np.linalg.norm(b - a) / h)))
        for j in range(1, k + 1):
            pts.append(a + (b - a) * j / k)
    bnd = np.array(pts[:-1])
    verts = [tuple(p) for p in bnd]
    nb = len(verts)
    faces = [list(range(nb))]
    for hp in holes:
        hp = np.asarray(hp, float)
        faces.append(list(range(len(verts), len(verts) + len(hp))))
        verts += [tuple(p) for p in hp]
    lo, hi = bnd.min(0), bnd.max(0)
    dy = h * math.sqrt(3) / 2
    grid = []
    for k, y in enumerate(np.arange(lo[1] + dy / 2, hi[1], dy)):
        off = (h / 2) * (k % 2)
        for x in np.arange(lo[0] + off, hi[0], h):
            grid.append((x, y))
    if grid:
        grid = np.array(grid)
        far = _pip(grid, bnd) & (_dist_polyline(grid, bnd, closed=True) > 0.5 * h)
        for hp in holes:
            hp = np.asarray(hp, float)
            far &= ~_pip(grid, hp) & (_dist_polyline(grid, hp, closed=True) > 0.5 * h)
        verts += [tuple(p) for p in grid[far]]
    out = delaunay_2d_cdt([Vector(v) for v in verts], [], faces, 2 if holes else 1, 1e-7)
    ov, of, orig_v = out[0], out[2], out[3]
    remap = {}
    for k, origs in enumerate(orig_v):
        for o_ in origs:
            remap[o_] = k
    V = np.array([(v.x, v.y) for v in ov])
    T = []
    for f in of:
        for a in range(1, len(f) - 1):
            T.append((f[0], f[a], f[a + 1]))
    T = np.array(T, int)
    # orient CCW in 2D
    e1, e2 = V[T[:, 1]] - V[T[:, 0]], V[T[:, 2]] - V[T[:, 0]]
    a2 = e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]
    T[a2 < 0] = T[a2 < 0][:, ::-1]
    return V, T, np.array([remap[i] for i in range(nb)])


def rounded_rect(x0, y0, x1, y1, r, top_r=0.0, n=6):
    """Axis-aligned rectangle outline (CCW in x right / y down... any), bottom corners (larger y)
    rounded r, top corners top_r."""
    pts = []

    def arc(cx, cy, rr, a0, a1):
        if rr <= 1e-6:
            return [(cx, cy)]
        return [(cx + rr * math.cos(a), cy + rr * math.sin(a)) for a in np.linspace(a0, a1, n)]
    pts += arc(x0 + top_r, y0 + top_r, top_r, math.pi, 1.5 * math.pi)
    pts += arc(x1 - top_r, y0 + top_r, top_r, 1.5 * math.pi, 2 * math.pi)
    pts += arc(x1 - r, y1 - r, r, 0.0, 0.5 * math.pi)
    pts += arc(x0 + r, y1 - r, r, 0.5 * math.pi, math.pi)
    return np.array(pts)


# --- pattern -> drape ----------------------------------------------------------------------------

class PanelMap:
    """A pattern point (panel, x, y cm) to the draped surface: the panel's flat triangle that
    holds it, the same barycentrics on the drape. Normals are the drape's vertex normals."""

    def __init__(self, C, wm, X, Tw, D=None):
        self.X = np.asarray(X, float)
        self.N = vertex_normals(self.X, np.asarray(Tw, int))
        self.panels = {}
        self.holes = {}
        for name, I in C["info"].items():
            ids = wm[I["base"] + np.arange(len(I["V"]))]
            self.panels[name] = (np.asarray(I["V"], float), np.asarray(I["T"], int), ids)
            if D is not None:
                self.holes[name] = D.geom(name).dart_holes()

    def close_darts(self, name, P2):
        """A point between a dart's legs is not on the cloth (it is sewn away): snap it to the
        nearer leg (both legs are one line on the drape)."""
        from .suit_rever import _pip
        P2 = np.array(P2, float)
        for hp in self.holes.get(name, []):
            m = _pip(P2, hp)
            if not m.any():
                continue
            a, b = hp, np.roll(hp, -1, axis=0)
            d = b - a
            L2 = np.maximum((d ** 2).sum(1), 1e-12)
            for i in np.nonzero(m)[0]:
                t = np.clip(((P2[i] - a) * d).sum(1) / L2, 0, 1)
                q = a + t[:, None] * d
                P2[i] = q[np.argmin(np.linalg.norm(q - P2[i], axis=1))]
        return P2

    def locate(self, name, P2):
        V, T, _ = self.panels[name]
        P2 = np.atleast_2d(np.asarray(P2, float))
        A, B, Cc = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
        v0, v1 = B - A, Cc - A
        d00, d01, d11 = (v0 * v0).sum(1), (v0 * v1).sum(1), (v1 * v1).sum(1)
        den = d00 * d11 - d01 * d01
        out_t, out_w = [], []
        for p in P2:
            v2 = p - A
            d20, d21 = (v2 * v0).sum(1), (v2 * v1).sum(1)
            b = (d11 * d20 - d01 * d21) / den
            c = (d00 * d21 - d01 * d20) / den
            a = 1 - b - c
            m = np.minimum(np.minimum(a, b), c)
            k = int(np.argmax(m))
            w = np.clip(np.array([a[k], b[k], c[k]]), 0, None)
            out_t.append(k)
            out_w.append(w / w.sum())
        return np.array(out_t), np.array(out_w)

    def frame(self, name, P2):
        """Points, unit normals, and the unit 3D directions of the pattern's +x and +y."""
        V, T, ids = self.panels[name]
        P2 = self.close_darts(name, np.atleast_2d(np.asarray(P2, float)))
        k, w = self.locate(name, P2)
        tri = ids[T[k]]
        Xp = np.einsum("ij,ijk->ik", w, self.X[tri])
        Np = _norm(np.einsum("ij,ijk->ik", w, self.N[tri]))
        # Jacobian of the flat -> draped map on each triangle
        P2t = V[T[k]]
        e1, e2 = P2t[:, 1] - P2t[:, 0], P2t[:, 2] - P2t[:, 0]
        E1, E2 = self.X[tri[:, 1]] - self.X[tri[:, 0]], self.X[tri[:, 2]] - self.X[tri[:, 0]]
        det = e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]
        # d/dx = (e2y E1 - e1y E2)/det ; d/dy = (-e2x E1 + e1x E2)/det
        dx = (e2[:, 1, None] * E1 - e1[:, 1, None] * E2) / det[:, None]
        dy = (-e2[:, 0, None] * E1 + e1[:, 0, None] * E2) / det[:, None]
        return Xp, Np, _norm(dx), _norm(dy)


def on_drape(pm, name, V2, lift):
    """Map flat 2D verts onto the drape, lifted along the normal by `lift` (m, scalar or per vertex)."""
    Xp, Np, _, _ = pm.frame(name, V2)
    lift = np.broadcast_to(np.asarray(lift, float), (len(V2),))
    return Xp + Np * lift[:, None], Np


def patch3d(pm, name, outline, h, lift_m, thick_m, rings):
    """A cloth patch (flap, jet, welt) on the drape: outline (cm, pattern), solid with a
    rounded rim. Returns V, F, part."""
    V2, T, bids = cdt_patch(outline, h)
    X, N = on_drape(pm, name, V2, lift_m + thick_m)
    # the flat triangles are CCW in pattern (x, y-down) coords; match the drape's outward side
    fn = np.cross(X[T[:, 1]] - X[T[:, 0]], X[T[:, 2]] - X[T[:, 0]])
    if np.einsum("ij,ij->i", fn, N[T].mean(1)).mean() < 0:
        T = T[:, ::-1]
    N = vertex_normals(X, T)
    return solid(X, T, N, thick_m, rings)


# --- buttons -------------------------------------------------------------------------------------

def _orient(V, F, want):
    """Flip each face so its normal agrees with want[i] (a direction per face)."""
    out = []
    for f, w in zip(F, want):
        q = V[list(f)]
        fn = np.cross(q[1] - q[0], q[2] - q[0])
        out.append(tuple(f) if np.dot(fn, w) >= 0 else tuple(f[::-1]))
    return out


def button(c, n, u, diam_m, thick_m, o, seg=None):
    """A four-hole sew-through button: a raised rim round a dished face, a half-round edge,
    four blind holes. c centre on the cloth, n outward normal, u in-plane direction (the
    holes' square)."""
    seg = seg or o["seg"]
    R = diam_m / 2
    th = thick_m
    n = n / np.linalg.norm(n)
    u = u - n * np.dot(u, n)
    u /= np.linalg.norm(u)
    v = np.cross(n, u)
    z0 = o["stand_mm"] / 1000.0                     # the thread shank: it stands off the cloth
    Rc = R - th / 2                                 # the top face ends where the half round starts
    hr = o["hole_r_frac"] * diam_m
    ha = o["hole_at_frac"] * diam_m
    ang = np.linspace(0, 2 * np.pi, seg, endpoint=False)
    outer = np.c_[np.cos(ang), np.sin(ang)] * Rc
    hs = 10
    hang = np.linspace(0, 2 * np.pi, hs, endpoint=False)
    hc = [np.array((sx * ha, sy * ha)) for sx, sy in ((1, 1), (-1, 1), (-1, -1), (1, -1))]
    holes = [c2 + hr * np.c_[np.cos(hang), np.sin(hang)] for c2 in hc]
    sc = 1000.0                                     # triangulate in mm
    V2, T, bids = cdt_patch(outer * sc, max(Rc * sc / 3, 0.4), [h_ * sc for h_ in holes])
    V2 = V2 / sc
    r = np.linalg.norm(V2, axis=1) / Rc
    rim_in = 0.7
    zt = np.where(r < rim_in, 0.62 * th + 0.18 * th * (r / rim_in) ** 2,
                  0.80 * th + 0.20 * th * np.sin(0.5 * np.pi * np.clip((r - rim_in) / (1 - rim_in), 0, 1)))
    P3 = lambda xy, z: c + n * (z0 + z)[:, None] + xy[:, :1] * u + xy[:, 1:] * v
    top = P3(V2, zt)
    Vs = [top]
    F = [tuple(int(i) for i in f) for f in T]
    want = [n] * len(F)
    base = len(top)
    prev = bids
    dirs = V2[bids] / np.linalg.norm(V2[bids], axis=1)[:, None]
    E = 6
    for m in range(1, E + 1):
        ph = math.pi * m / E
        rad = Rc + (th / 2) * math.sin(ph)
        z = th / 2 + (th / 2) * math.cos(ph)
        ring = P3(dirs * rad, np.full(len(bids), z))
        ids = base + np.arange(len(bids))
        Vs.append(ring)
        base += len(bids)
        nb = len(bids)
        for k in range(nb):
            k2 = (k + 1) % nb
            F.append((int(prev[k]), int(prev[k2]), int(ids[k2]), int(ids[k])))
            d = dirs[k] + dirs[k2]
            want.append(math.sin(ph - math.pi / E / 2) * (d[0] * u + d[1] * v)
                        + math.cos(ph - math.pi / E / 2) * n)
        prev = ids
    cb = base
    Vs.append((c + n * z0)[None])
    base += 1
    nb = len(prev)
    for k in range(nb):
        F.append((int(prev[(k + 1) % nb]), int(prev[k]), cb))
        want.append(-n)
    depth = o["hole_depth_mm"] / 1000.0
    for hp, c2 in zip(holes, hc):
        hidx = np.array([int(np.argmin(np.linalg.norm(V2 - q, axis=1))) for q in hp])
        low = top[hidx] - n * depth
        lid = base + np.arange(len(hidx))
        Vs.append(low)
        base += len(hidx)
        ax = c + n * z0 + c2[0] * u + c2[1] * v
        for k in range(len(hidx)):
            k2 = (k + 1) % len(hidx)
            F.append((int(hidx[k]), int(hidx[k2]), int(lid[k2]), int(lid[k])))
            mid = 0.5 * (top[hidx[k]] + top[hidx[k2]])
            w = ax - mid
            want.append(w - n * np.dot(w, n))
        Vs.append(low.mean(0)[None])
        for k in range(len(hidx)):
            F.append((int(lid[k]), int(lid[(k + 1) % len(hidx)]), base))
            want.append(n)
        base += 1
    V = np.vstack(Vs)
    return V, _orient(V, F, want)


def tube(P, N, r, seg=6, closed=True):
    """A round cord of radius r along the polyline P (n, 3), N the surface normal per point."""
    P = np.asarray(P, float)
    nP = len(P)
    tg = _norm(np.roll(P, -1, 0) - np.roll(P, 1, 0)) if closed else _norm(np.gradient(P, axis=0))
    b = _norm(np.cross(tg, N))
    nn = _norm(np.cross(b, tg))
    V, F = [], []
    for i in range(nP):
        for s in range(seg):
            a = 2 * math.pi * s / seg
            V.append(P[i] + r * (math.cos(a) * nn[i] + math.sin(a) * b[i]))
    m = nP if closed else nP - 1
    want = []
    for i in range(m):
        i2 = (i + 1) % nP
        for s in range(seg):
            s2 = (s + 1) % seg
            F.append((i * seg + s, i * seg + s2, i2 * seg + s2, i2 * seg + s))
            a = 2 * math.pi * (s + 0.5) / seg
            want.append(math.cos(a) * nn[i] + math.sin(a) * b[i])
    V = np.array(V)
    return V, _orient(V, F, want)


# --- the made jacket -----------------------------------------------------------------------------

def _edge_ids(C, wm, panel_edges):
    out = set()
    for (pn, e, j), g in C["gid"].items():
        if (pn.removesuffix("_r"), e) in panel_edges:
            out.add(int(wm[g]))
    return np.array(sorted(out), int)


def _vents(X, T, C, wm, o, stats):
    """Open the vents: from the hem (cuff) up the given height, a seam is a lap instead. The
    lapping panel's vertices on that stretch are duplicated (it keeps the copies), so its edge
    and the other panel's extension are separate edges; a band either side then steps (the lap
    stands a cloth thickness proud, the extension under it sinks), fading out at the vent top
    where it is sewn across. Back vents: the back laps over the side body; sleeve vents: the
    top sleeve laps over the under sleeve. Returns X, T (new arrays)."""
    vo = o["vent"]
    specs = [("back", "side", "hem", vo["height_cm"]), ("top_sleeve", "hind", "cuff", vo["sleeve_cm"])]
    X = np.asarray(X, float).copy()
    T = np.asarray(T, int).copy()
    pans = {}
    for name, I in C["info"].items():
        for i in wm[I["base"] + np.arange(len(I["V"]))]:
            pans.setdefault(int(i), set()).add(name)
    N0 = vertex_normals(X, T)
    step = vo["step_mm"] / 1000.0
    band = vo["band_cm"] / 100.0
    fade = vo["fade_cm"]
    lift = np.zeros(len(X))
    info = []
    for pn0, e, hem_e, h_cm in specs:
        if h_cm <= 0:
            continue
        for suf in ("", "_r"):
            pn = pn0 + suf
            if (pn, e) not in C["pts"]:
                continue
            P2 = np.asarray(C["pts"][(pn, e)], float)
            H2 = np.asarray(C["pts"][(pn, hem_e)], float)
            d0 = np.min(np.linalg.norm(H2 - P2[0], axis=1))
            d1 = np.min(np.linalg.norm(H2 - P2[-1], axis=1))
            js = list(range(len(P2))) if d0 < d1 else list(range(len(P2)))[::-1]
            sj = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(P2[js], axis=0), axis=1))]
            seam, s_of = [], {}
            for j, sv in zip(js, sj):
                if sv > h_cm + 1e-6:
                    break
                g = int(wm[C["gid"][(pn, e, j)]])
                if g not in s_of:
                    seam.append(g)
                    s_of[g] = float(sv)
            if len(seam) < 2:
                continue
            other = None
            for g in seam:
                for q in pans.get(g, ()):
                    if q != pn:
                        other = q
            seam_set = set(seam)
            excl = lambda v: pans.get(v) == {pn}
            new_of = {}
            for g in seam:
                fs = np.nonzero((T == g).any(1))[0]
                side_f = []
                for f in fs:
                    others = [int(v) for v in T[f] if v != g]
                    if any(excl(v) or v in new_of.values() for v in others):
                        side_f.append(f)
                if not side_f:
                    continue
                j = len(X)
                X = np.vstack([X, X[g]])
                N0 = np.vstack([N0, N0[g]])
                lift = np.r_[lift, 0.0]
                pans[j] = {pn}
                new_of[g] = j
                for f in side_f:
                    T[f][T[f] == g] = j
            # the step: a band either side of the vent line, fading to nothing at its top
            S3 = X[seam]
            sv = np.array([s_of[g] for g in seam])
            lap = np.array([v for v in range(len(X)) if pans.get(v) == {pn}], int)
            ext = np.array([v for v in range(len(X)) if other is not None and pans.get(v) == {other}] + seam, int)
            for ids, amt in ((lap, 1.0), (ext, -0.4)):
                if not len(ids):
                    continue
                dd = np.linalg.norm(X[ids][:, None, :] - S3[None], axis=2)
                k = np.argmin(dd, axis=1)
                d = dd[np.arange(len(ids)), k]
                w = sp.smoothstep(1.0 - d / band) * sp.smoothstep((h_cm - sv[k]) / fade)
                m = d < band
                lift[ids[m]] = np.where(np.abs(amt * w[m]) > np.abs(lift[ids[m]]), amt * w[m], lift[ids[m]])
            info.append((pn, len(new_of)))
    X = X + N0 * (lift * step)[:, None]
    stats["vents"] = {pn: n for pn, n in info}
    return X, T


def build(C, D, wm, X, Tw, opts=None, stats=None, rings=None, under=None):
    """The made jacket on the drape (X, Tw welded). Returns {name: (V, F, part)} plus info."""
    o = sp.merge(DEFAULTS, opts or {})
    stats = {} if stats is None else stats
    rings = rings or o["edge_rings"]
    X = np.asarray(X, float)
    Tw = np.asarray(Tw, int)
    pm = PanelMap(C, wm, X, Tw, D)
    dt = D.opts["details"] if hasattr(D, "opts") and "details" in D.opts else sp.DEFAULTS["details"]
    out = {}
    # --- the shell (vents opened first)
    Xs, Ts = _vents(X, Tw, C, wm, o, stats)
    N = vertex_normals(Xs, Ts)
    t = np.full(len(Xs), o["shell_thick_mm"] / 1000.0)
    V, F, part = solid(Xs, Ts, N, t, rings)
    # inside: lining, except the facings and the turn-ups
    n = len(Xs)
    wool_in = np.zeros(n, bool)
    for edges, w_cm in (({("front", "front")}, o["facing_cm"]), ({("front", "hem"), ("side", "hem"), ("back", "hem")}, o["turnup_cm"]),
                        ({("top_sleeve", "cuff"), ("under_sleeve", "cuff")}, o["turnup_cm"])):
        ids = _edge_ids(C, wm, edges)
        if len(ids):
            P = X[ids]
            for k in range(0, n, 2048):
                d = np.min(np.linalg.norm(Xs[k:k + 2048, None, :] - P[None], axis=2), axis=1)
                wool_in[k:k + 2048] |= d < w_cm / 100.0
    for i in np.nonzero(part == LINING)[0]:
        f = F[i]
        if wool_in[np.array(f) - n].mean() > 0.5:
            part[i] = WOOL
    out["shell"] = (V, F, part)
    stats["shell"] = {"verts": int(len(V)), "tris": int(sum(len(f) - 2 for f in F)),
                      "lining_faces": int((part == LINING).sum())}
    # --- pockets
    fl, jt, wl = o["flap"], o["jet"], o["welt"]
    pv, pf, pp = [], [], []

    def add(V_, F_, part_):
        b = sum(len(v) for v in pv)
        pv.append(V_)
        pf.extend(tuple(int(i) + b for i in f) for f in F_)
        pp.extend(list(part_))
    front = D.geom("front")
    if "hip_pocket" in front.notches:
        (xa, yp), (xb, _) = front.notches["hip_pocket"]
        hp = dt["hip_pocket"]
        g = fl["gap_cm"]
        flap = rounded_rect(xa, yp + g, xb, yp + hp["flap_cm"], fl["corner_r_cm"])
        jet = rounded_rect(xa, yp - hp["jet_cm"], xb, yp - g, 0.0)
        for nm in ("front", "front_r"):
            add(*patch3d(pm, nm, flap, fl["h_cm"], fl["lift_mm"] / 1000, fl["thick_mm"] / 1000, rings))
            add(*patch3d(pm, nm, jet, 0.25, jt["lift_mm"] / 1000, jt["thick_mm"] / 1000, max(2, rings // 2)))
    if "breast_welt" in front.notches:
        (x0, y0), (x1, y1) = front.notches["breast_welt"]
        bw = dt["breast_welt"]
        hgt = bw["height_cm"]
        welt = np.array([(x0, y0), (x1, y1), (x1, y1 - hgt), (x0, y0 - hgt)])
        add(*patch3d(pm, "front", welt, wl["h_cm"], wl["lift_mm"] / 1000, wl["thick_mm"] / 1000, rings))
    out["pockets"] = (np.vstack(pv), pf, np.array(pp, int)) if pv else None
    # --- buttons
    bo = o["button"]
    bv, bf = [], []

    def addb(V_, F_):
        b = sum(len(v) for v in bv)
        bv.append(V_)
        bf.extend(tuple(int(i) + b for i in f) for f in F_)
    shell_lift = 0.0
    if "button" in front.notches:
        xy = front.notches["button"]
        Xp, Np, ux, uy = pm.frame("front", [xy])
        addb(*button(Xp[0] + Np[0] * shell_lift, Np[0], ux[0] + uy[0], bo["front_diam_cm"] / 100,
                     bo["front_thick_mm"] / 1000, bo))
    top = D.geom("top_sleeve")
    cb = dt["cuff_buttons"]
    if "cuff_buttons" in top.notches:
        for nm in ("top_sleeve", "top_sleeve_r"):
            for xy in top.notches["cuff_buttons"]:
                Xp, Np, ux, uy = pm.frame(nm, [xy])
                addb(*button(Xp[0], Np[0], ux[0] + uy[0], cb["diam_cm"] / 100 * 0.97,
                             bo["cuff_thick_mm"] / 1000, bo))
    out["buttons"] = (np.vstack(bv), bf, np.full(len(bf), BUTTON)) if bv else None
    # --- the keyhole buttonhole (left front): a corded lip round the slit and the eye
    if "buttonhole" in front.notches:
        bo2 = o["buttonhole"]
        (xe, ye), (xs, _) = front.notches["buttonhole"]
        er = bo2["eye_r_mm"] / 10.0
        gp = bo2["gap_mm"] / 10.0
        cr = bo2["cord_r_mm"] / 1000.0
        a = np.linspace(-0.75 * np.pi, 0.75 * np.pi, 15)
        eye = np.c_[xe - er + er * np.cos(a), ye + er * np.sin(a)]
        cord_r = (cr * 100) + gp / 2
        upper = np.c_[np.linspace(eye[-1, 0], xs, 10), np.full(10, ye + cord_r)]
        lower = np.c_[np.linspace(xs, eye[0, 0], 10), np.full(10, ye - cord_r)]
        loop2 = np.vstack([eye, upper[1:], lower[1:-1]])
        Xp, Np, _, _ = pm.frame("front", loop2)
        V_, F_ = tube(Xp + Np * cr, Np, cr, seg=6)
        out["buttonhole"] = (V_, F_, np.full(len(F_), EDGE))
    stats["details"] = {k: {"verts": int(len(v[0])), "tris": int(sum(len(f) - 2 for f in v[1]))}
                        for k, v in out.items() if v is not None}
    return out
