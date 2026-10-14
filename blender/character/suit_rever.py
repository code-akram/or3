"""The modelled collar and lapel of the drafted jacket (m1 v4 T13; bench/m1/v4/suit-spike.md §5.1, §5.4).

Not simulated. The drape supplies one curve per side, the jacket's free edge after the lapel
and the collar are cut away:

    E(s)   centre back -> back neckline -> neck point -> front gorge -> roll-line crossing
           (s_R) -> down the roll edge of the front -> the break point (s_B)

s is the flat (pattern) arc length from the centre back, in cm, so the draft's dimensions
apply directly. The collar and the lapel are one turned-over sheet attached along E. Its
chart is (s, q): q is the sheet's own arc length away from E. Per s the sheet runs

    stand   q in [0, st(s)]            up from the neckline, leaning onto the neck, clear of
                                       the shirt collar (st = 0 on the roll edge: the lapel
                                       turns straight off the front's edge)
    roll    q in [st, st + pi r(s)]    a half turn of radius r about the roll line
    fall    q > st + pi r              laid back over the stand and the jacket at height
                                       h(q) above it: 2r at the roll, settling to h_lay

The fall's base point is found by walking the jacket surface inward from E (a column per s,
walked on the draped mesh), or on the stand above E. The outline in (s, q) is the draft's:
collar width (stand + roll + the fall's reach below the neckline), the collar end and the
notch at the gorge, and the lapel edge (the draft's lapel panel, measured off the roll line).
The sheet is meshed in the chart (constrained Delaunay), mapped to 3D, relaxed, pushed clear of
the jacket and the under-garments, then given thickness with a rounded edge.

Needs mathutils (BVHTree, delaunay_2d_cdt); no bpy data access.
"""

import math

import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import delaunay_2d_cdt

from . import suit_pattern as sp

DEFAULTS = {
    "h_cm": 0.6,                 # chart mesh spacing
    "ds_cm": 0.5,                # column spacing along E
    "dv_cm": 0.4,                # column walk step
    "edge_smooth_cm": 1.5,       # E(s) and its frames: Gaussian along s
    "corner_smooth_cm": 3.0,     # wider round the gorge corner (s_R)
    "stand_cm": 3.0,             # at the centre back
    "stand_np_frac": 0.85,       # the stand starts to fall off at this x the neck-point arc
    "fall_below_cm": 1.2,        # the collar fall reaches this far below the neckline at CB
    "end_width_cm": 4.0,         # collar end, perpendicular to the gorge
    "r_collar_cm": 0.3,
    "r_lapel_top_cm": 0.55,
    "r_break_cm": 0.22,
    "lean_deg": 10.0,            # the stand leans onto the neck by this much off the jacket surface
    "shirt_gap_cm": 0.25,        # stand clear of the shirt collar
    "h_lay_cm": 0.42,            # fall height over its base where it lies down
    "lay_len_collar_cm": 1.2,
    "lay_len_lapel_cm": 2.2,
    "corner_blend_cm": 0.8,      # the fall's normal turns over the stand/jacket corner within this
    "thick_cm": 0.26,
    "relax_iters": 12,
    "clear_cm": 0.15,            # final: every vertex this far outside the jacket and the under-garments
}


def _gauss(a, sig, ds, axis=0):
    """Gaussian smoothing of samples spaced ds along axis 0 (edge-clamped)."""
    if sig <= 0:
        return a
    k = int(math.ceil(3 * sig / ds))
    w = np.exp(-0.5 * (np.arange(-k, k + 1) * ds / sig) ** 2)
    w /= w.sum()
    pad = np.concatenate([np.repeat(a[:1], k, 0), a, np.repeat(a[-1:], k, 0)], 0)
    out = np.zeros_like(a, dtype=float)
    for i, wi in enumerate(w):
        out += wi * pad[i:i + len(a)]
    return out


def _norm(v):
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-12)


def vertex_normals(X, T):
    fn = np.cross(X[T[:, 1]] - X[T[:, 0]], X[T[:, 2]] - X[T[:, 0]])
    N = np.zeros_like(X)
    for k in range(3):
        np.add.at(N, T[:, k], fn)
    return _norm(N)


class Surface:
    """The draped jacket: nearest point with a smooth (vertex-interpolated) normal."""

    def __init__(self, X, T):
        self.X, self.T = np.asarray(X, float), np.asarray(T, int)
        self.N = vertex_normals(self.X, self.T)
        self.bvh = BVHTree.FromPolygons([tuple(p) for p in self.X], [tuple(t) for t in self.T])

    def nearest(self, p):
        loc, _, fi, _ = self.bvh.find_nearest(Vector(p))
        loc = np.array(loc)
        a, b, c = self.X[self.T[fi]]
        v0, v1, v2 = b - a, c - a, loc - a
        d00, d01, d11 = v0 @ v0, v0 @ v1, v1 @ v1
        d20, d21 = v2 @ v0, v2 @ v1
        den = max(d00 * d11 - d01 * d01, 1e-18)
        w1 = (d11 * d20 - d01 * d21) / den
        w2 = (d00 * d21 - d01 * d20) / den
        w = np.clip([1 - w1 - w2, w1, w2], 0, 1)
        n = _norm(w @ self.N[self.T[fi]])
        return loc, n

    def smooth_normal(self, P, r):
        """The surface normal averaged over the vertices within r (m) of each point (Gaussian
        weights): the frame at the free edge is not thrown by a pinch in one face."""
        P = np.atleast_2d(P)
        out = np.zeros_like(P)
        for i, p in enumerate(P):
            d2 = ((self.X - p) ** 2).sum(1)
            w = np.exp(-d2 / (2 * (0.5 * r) ** 2)) * (d2 < r * r)
            out[i] = (w[:, None] * self.N).sum(0)
        return _norm(out)


# --- the chart outline ---------------------------------------------------------------------------

def outline(G, o):
    """The rever's outline in (s, q), wearer's left (s >= 0), from CB round to the break:
    a list of (name, polyline) in order, plus the gorge seam line. G: chart geometry from
    chart_geometry()."""
    s_R, s_B, s_G, q_G = G["s_R"], G["s_B"], G["s_G"], G["q_G"]
    # the collar end: from the gorge point, perpendicular to the gorge seam, away from the lapel
    g = np.array([s_G - s_R, q_G])
    g /= np.linalg.norm(g)
    perp = np.array([-g[1], g[0]])
    if perp[1] < 0:
        perp = -perp
    CP = np.array([s_G, q_G]) + perp * o["end_width_cm"]
    q0 = 2 * o["stand_cm"] + math.pi * o["r_collar_cm"] + o["fall_below_cm"]
    ss = np.linspace(0, CP[0], 40)
    qc = q0 + (CP[1] - q0) * sp.smoothstep(ss / CP[0]) ** 1.5
    collar_outer = np.stack([ss, qc], 1)[::-1]                 # CP -> CB
    end = np.stack([np.linspace(s_G, CP[0], 8), np.linspace(q_G, CP[1], 8)], 1)   # G -> CP
    lapel = G["lapel_sq"]                                       # break -> lapel point (s, q)
    top = np.stack([np.linspace(lapel[-1, 0], s_G, 8), np.linspace(lapel[-1, 1], q_G, 8)], 1)
    edge = np.stack([np.linspace(s_B, 0.0, int(s_B / 0.5) + 1), np.zeros(int(s_B / 0.5) + 1)], 1)
    # order: CB outer -> ... must be one closed loop: E (CB -> break), lapel edge (break -> L),
    # lapel top (L -> G), collar end (G -> CP), collar outer (CP -> CB)
    loop = [("edge", edge[::-1]), ("lapel", lapel), ("lapel_top", top), ("end", end), ("outer", collar_outer)]
    gorge = np.stack([np.linspace(s_R, s_G, 10), np.linspace(0, q_G, 10)], 1)
    return loop, gorge, CP


def chart_geometry(D):
    """The rever chart's landmarks from the draft (split_lapel): arc lengths along E and the
    lapel outline measured off the roll line."""
    back, front, lap = D.panels["back"], D.panels["front"], D.panels["lapel"]
    s_np = sp.arclen(back.edge("neck"))
    s_R = s_np + sp.arclen(front.edge("gorge"))
    roll = front.edge("roll")                     # break -> Rg
    B, Rg = roll[0], roll[-1]
    L = np.linalg.norm(Rg - B)
    s_B = s_R + L
    t_r = (Rg - B) / L                            # up the roll line
    n_r = np.array([t_r[1], -t_r[0]])
    if n_r[0] < 0:                                # toward the lapel side (+x)
        n_r = -n_r

    def to_sq(P):
        P = np.atleast_2d(P)
        along = (P - B) @ t_r                     # from the break, up
        return np.stack([s_B - along, (P - B) @ n_r], 1)

    G = D.anchors["gorge"][1]
    sG, qG = to_sq(G)[0]
    lapel_sq = to_sq(lap.edge("lapel"))           # break -> lapel point
    return {"s_np": float(s_np), "s_R": float(s_R), "s_B": float(s_B), "s_G": float(sG), "q_G": float(qG),
            "lapel_sq": lapel_sq}


def _pip(pts, poly):
    x, y = pts[:, 0][:, None], pts[:, 1][:, None]
    a, b = poly, np.roll(poly, -1, axis=0)
    c = ((a[:, 1] > y) != (b[:, 1] > y)) & (x < (b[:, 0] - a[:, 0]) * (y - a[:, 1])
                                            / np.where(b[:, 1] != a[:, 1], b[:, 1] - a[:, 1], 1e-12) + a[:, 0])
    return c.sum(1) % 2 == 1


def _dist_polyline(pts, poly, closed=False):
    a = poly if closed else poly[:-1]
    b = np.roll(poly, -1, axis=0) if closed else poly[1:]
    d = b - a
    L2 = np.maximum((d ** 2).sum(1), 1e-12)
    t = np.clip(((pts[:, None, :] - a[None]) * d[None]).sum(2) / L2[None], 0, 1)
    q = a[None] + t[..., None] * d[None]
    return np.linalg.norm(pts[:, None, :] - q, axis=2).min(1)


def triangulate(loop, gorge, h):
    """Mesh the full (both halves) outline in the chart. Returns V (n, 2), T (m, 3),
    boundary vertex ids in loop order, gorge line vertex ids per side."""
    # resample each named span at ~h (the corners stay), the left half CB inner -> CB outer
    pieces = []
    for _, p in loop:
        n = max(1, int(round(sp.arclen(p) / h)))
        pieces.append(sp.at_params(p, np.linspace(0, 1, n + 1)))
    left = sp.join(*pieces)                        # CB inner (0, 0) ... CB outer (0, q0)
    right = (left * np.array([-1.0, 1.0]))[::-1]   # CB outer ... CB inner
    bnd = np.vstack([left, right[1:-1]])
    verts = [tuple(p) for p in bnd]
    nb = len(verts)
    edges = []
    gl = []
    for sign in (1.0, -1.0):
        g = gorge * np.array([sign, 1.0])
        g = sp.at_params(g, np.linspace(0, 1, max(2, int(round(sp.arclen(g) / h))) + 1))
        i0 = int(np.argmin(np.linalg.norm(bnd - g[0], axis=1)))
        i1 = int(np.argmin(np.linalg.norm(bnd - g[-1], axis=1)))
        ids = [i0]
        for p in g[1:-1]:
            ids.append(len(verts))
            verts.append(tuple(p))
        ids.append(i1)
        edges += [(a, b) for a, b in zip(ids, ids[1:])]
        gl.append(ids)
    lo, hi = bnd.min(0), bnd.max(0)
    dy = h * math.sqrt(3) / 2
    grid = []
    for k, y in enumerate(np.arange(lo[1] + dy / 2, hi[1], dy)):
        off = (h / 2) * (k % 2)
        for x in np.arange(lo[0] + off, hi[0], h):
            grid.append((x, y))
    grid = np.array(grid)
    grid = grid[_pip(grid, bnd)]
    far = _dist_polyline(grid, bnd, closed=True) > 0.55 * h
    for ids in gl:
        far &= _dist_polyline(grid, np.array([verts[i] for i in ids])) > 0.45 * h
    grid = grid[far]
    verts += [tuple(p) for p in grid]
    out = delaunay_2d_cdt([Vector(v) for v in verts], edges, [list(range(nb))], 1, 1e-6)
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
    T = np.array(T)
    bids = [remap[i] for i in range(nb)]
    gl = [[remap[i] for i in ids] for ids in gl]
    return V, T, bids, gl


# --- the 3D map ----------------------------------------------------------------------------------

class Columns:
    """E(s) for both halves on one signed axis (s < 0: the wearer's right), with the frame at
    each column and the inward walk on the jacket."""

    def __init__(self, surf, chains, G, o):
        self.o = o
        ds = o["ds_cm"]
        s_B = G["s_B"]
        self.s = np.arange(-s_B, s_B + 1e-9, ds)
        # E: interpolate each side's chain over |s|, the right side on s < 0
        P = np.zeros((len(self.s), 3))
        for side, sign in (("l", 1.0), ("r", -1.0)):
            ids, sv = chains[side]
            X = surf.X[ids]
            m = (np.sign(self.s) == sign) | (self.s == 0)
            for k in range(3):
                P[m, k] = np.interp(np.abs(self.s[m]), sv, X[:, k])
        self.E = _gauss(P, o["edge_smooth_cm"], ds)
        self.E[0], self.E[-1] = P[0], P[-1]       # the break points stay
        Tn = _norm(np.gradient(self.E, axis=0))
        N = surf.smooth_normal(self.E, 0.02)
        # inward: across the edge into the jacket. A step inward stays on the surface; a
        # step outward leaves it (by about the step).
        D = _norm(np.cross(N, Tn))
        d_in = np.array([np.linalg.norm(surf.nearest(p + d * 0.01)[0] - (p + d * 0.01)) for p, d in zip(self.E, D)])
        d_out = np.array([np.linalg.norm(surf.nearest(p - d * 0.01)[0] - (p - d * 0.01)) for p, d in zip(self.E, D)])
        D[d_in > d_out] *= -1
        # smooth the frame (wider round the gorge corner), re-orthogonalise
        s_R = G["s_R"]
        w = sp.smoothstep(1 - np.abs(np.abs(self.s) - s_R) / (2 * o["corner_smooth_cm"]))
        Ds = _gauss(D, o["edge_smooth_cm"], ds)
        Dc = _gauss(D, o["corner_smooth_cm"], ds)
        D = Ds * (1 - w)[:, None] + Dc * w[:, None]
        N = _norm(_gauss(N, o["edge_smooth_cm"], ds))
        D = _norm(D - np.einsum("ij,ij->i", D, Tn)[:, None] * Tn)
        N = _norm(np.cross(Tn, D))
        if np.einsum("ij,ij->i", N, np.array([surf.nearest(p)[1] for p in self.E])).mean() < 0:
            N = -N
        self.T, self.D, self.N = Tn, D, N
        self.surf = surf
        self.walk_len = None
        self.lean = None

    def walk(self, max_cm):
        """Columns walked inward on the jacket: positions (S, K, 3), normals, at v = -k dv."""
        dv = self.o["dv_cm"] / 100.0
        K = int(math.ceil(max_cm / self.o["dv_cm"])) + 1
        W = np.zeros((len(self.s), K, 3))
        Wn = np.zeros((len(self.s), K, 3))
        for i, (p, d) in enumerate(zip(self.E, self.D)):
            q, n = self.surf.nearest(p)
            W[i, 0], Wn[i, 0] = p, n
            d = d.copy()
            for k in range(1, K):
                q, n = self.surf.nearest(W[i, k - 1] + d * dv)
                W[i, k], Wn[i, k] = q, n
                step = q - W[i, k - 1]
                d = d - (d @ n) * n
                if np.linalg.norm(step) > 1e-9:
                    d = 0.5 * d / np.linalg.norm(d) + 0.5 * step / np.linalg.norm(step)
                d = d / np.linalg.norm(d)
        # smooth across columns
        W = _gauss(W, self.o["edge_smooth_cm"], self.o["ds_cm"])
        Wn = _norm(_gauss(Wn, self.o["edge_smooth_cm"], self.o["ds_cm"]))
        self.W, self.Wn, self.K, self.dv = W, Wn, K, dv
        return W, Wn


def profile(G, o):
    """Stand height st(s), roll radius r(s) (cm) and the lay length, as functions of |s|."""
    s_np, s_R, s_B = G["s_np"], G["s_R"], G["s_B"]
    a = o["stand_np_frac"] * s_np

    def st(s):
        s = np.abs(s)
        return o["stand_cm"] * (1 - sp.smoothstep((s - a) / max(s_R - a, 1e-6)))

    def r(s):
        s = np.abs(s)
        top = o["r_collar_cm"] + (o["r_lapel_top_cm"] - o["r_collar_cm"]) * sp.smoothstep((s - s_np) / (s_R - s_np + 1.0))
        return np.where(s <= s_R, top,
                        o["r_lapel_top_cm"] + (o["r_break_cm"] - o["r_lapel_top_cm"]) * sp.smoothstep((s - s_R) / (s_B - s_R)))

    def lay(s):
        s = np.abs(s)
        return o["lay_len_collar_cm"] + (o["lay_len_lapel_cm"] - o["lay_len_collar_cm"]) * sp.smoothstep((s - s_np) / (s_R - s_np + 2.0))

    return st, r, lay


def map3d(Vc, C, G, o, under=None):
    """Chart (s, q) -> 3D (m). C: Columns (walked). Returns X (n, 3) and the base normal."""
    st_f, r_f, lay_f = profile(G, o)
    s, q = Vc[:, 0], Vc[:, 1]
    st, r, lay = st_f(s), r_f(s), lay_f(s)
    cm = 0.01
    # column interpolation
    x = np.clip((s - C.s[0]) / o["ds_cm"], 0, len(C.s) - 1.000001)
    i0 = np.floor(x).astype(int)
    f = (x - i0)[:, None]

    def col(A):
        return A[i0] * (1 - f) + A[i0 + 1] * f

    E, D, N, Tn = col(C.E), _norm(col(C.D)), _norm(col(C.N)), _norm(col(C.T))
    if C.lean is None:
        C.lean = stand_lean(C, st_f, o, under)
    lean = col(C.lean[:, None]) * sp.smoothstep(st / 1.0)[:, None]   # the lapel turns straight off
    U = _norm(-D * np.cos(lean) - N * np.sin(lean))
    Nst = _norm(np.cross(Tn, U))
    Nst = np.where((np.einsum("ij,ij->i", Nst, N) < 0)[:, None], -Nst, Nst)

    def body(v_cm):
        """Base point and normal on the jacket at v (cm) < 0 (inward)."""
        k = np.clip(-v_cm / o["dv_cm"], 0, C.K - 1.000001)
        k0 = np.floor(k).astype(int)
        g = (k - k0)[:, None]
        Wa = C.W[i0, k0] * (1 - f) + C.W[i0 + 1, k0] * f
        Wb = C.W[i0, k0 + 1] * (1 - f) + C.W[i0 + 1, k0 + 1] * f
        Na = C.Wn[i0, k0] * (1 - f) + C.Wn[i0 + 1, k0] * f
        Nb = C.Wn[i0, k0 + 1] * (1 - f) + C.Wn[i0 + 1, k0 + 1] * f
        return Wa * (1 - g) + Wb * g, _norm(Na * (1 - g) + Nb * g)

    X = np.zeros((len(Vc), 3))
    Nout = np.zeros((len(Vc), 3))
    stand = q <= st
    X[stand] = E[stand] + U[stand] * (q[stand] * cm)[:, None]
    Nout[stand] = Nst[stand]
    rollm = (~stand) & (q <= st + math.pi * r)
    phi = (q - st) / np.maximum(r, 1e-6)
    Ctr = E + U * (st * cm)[:, None] + Nst * (r * cm)[:, None]
    Pr = Ctr + (r * cm)[:, None] * (-np.cos(phi)[:, None] * Nst + np.sin(phi)[:, None] * U)
    X[rollm] = Pr[rollm]
    Nout[rollm] = _norm(Pr - Ctr)[rollm]
    fall = ~(stand | rollm)
    qq = q - st - math.pi * r                              # past the roll
    v = st - qq                                            # base coordinate: + on the stand, - on the jacket
    h = o["h_lay_cm"] + (2 * r - o["h_lay_cm"]) * np.exp(-qq / lay)
    Pb_st = E + U * (np.maximum(v, 0) * cm)[:, None]
    Pb_bd, Nb_bd = body(np.minimum(v, 0))
    b = o["corner_blend_cm"]
    w = sp.smoothstep((v + b) / (2 * b))[:, None]          # 1 on the stand, 0 on the jacket
    has_stand = (st > 1e-3)[:, None]
    w = np.where(has_stand, w, 0.0)
    Pb = np.where((v >= 0)[:, None], Pb_st, Pb_bd)
    Nb = _norm(Nst * w + Nb_bd * (1 - w))
    Xf = Pb + Nb * (h * cm)[:, None]
    X[fall] = Xf[fall]
    Nout[fall] = Nb[fall]
    return X, Nout


def stand_lean(C, st_f, o, under):
    """One lean angle per column (rad): from lean_deg (onto the neck) outward until the stand
    clears the under-garments, then a moving max and a Gaussian along s so the stand reads as
    one smooth band (per-vertex clearing ruffles it)."""
    lean0 = math.radians(o["lean_deg"])
    out = np.zeros(len(C.s))
    if under is None:
        out[:] = lean0
    else:
        gap = o["shirt_gap_cm"] / 100.0
        st = st_f(C.s)
        angles = lean0 - np.radians(np.arange(0.0, 50.0 + 1e-9, 2.5))
        for i in range(len(C.s)):
            if st[i] <= 1e-3:
                out[i] = lean0
                continue
            out[i] = angles[-1]
            for a in angles:
                u = _norm(-C.D[i] * math.cos(a) - C.N[i] * math.sin(a))
                bad = False
                for t in (0.33, 0.66, 1.0):
                    p = C.E[i] + u * st[i] * 0.01 * t
                    loc, nor, _, _d = under.find_nearest(Vector(p))
                    if loc is not None and np.dot(p - np.array(loc), np.array(nor)) < gap:
                        bad = True
                        break
                if not bad:
                    out[i] = a
                    break
    # a smaller lean is further out: a moving min of the angle, then smooth
    ds = o["ds_cm"]
    k = max(1, int(round(2.0 / ds)))
    pad = np.pad(out, k, mode="edge")
    m = np.array([pad[j:j + 2 * k + 1].min() for j in range(len(out))])
    return _gauss(m, 1.5, ds)


def _edges(T):
    E = np.vstack([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]])
    return np.unique(np.sort(E, 1), axis=0)


def relax(X, T, fixed, iters, lam=0.33, mu=-0.34):
    """Taubin smoothing (no shrinkage), fixed vertices held. The boundary is fixed by the
    caller: an umbrella step pulls an open sheet's edge inward."""
    E = _edges(T)
    n = len(X)
    deg = np.bincount(E.ravel(), minlength=n).astype(float)
    for it in range(2 * iters):
        acc = np.zeros_like(X)
        np.add.at(acc, E[:, 0], X[E[:, 1]])
        np.add.at(acc, E[:, 1], X[E[:, 0]])
        L = acc / np.maximum(deg, 1)[:, None] - X
        L[fixed] = 0
        X = X + (lam if it % 2 == 0 else mu) * L
    return X


def clear(X, bvhs, dist, skip=None, log=None):
    """Push every vertex at least `dist` outside each BVH surface (along its normal).

    bvhs run outermost first (the jacket, then the under-garments). A test counts only
    when the vertex is over the face (the offset mostly along the normal): beside an open
    edge (the stand above the jacket's neck edge) the nearest point says nothing about
    inside or out. A vertex over an outer surface is done once it is outside it: the
    outer layer already clears the inner ones."""
    X = X.copy()
    moved = 0
    for i, p in enumerate(X):
        if skip is not None and skip[i]:
            continue
        for bi, b in enumerate(bvhs):
            loc, nor, _, d = b.find_nearest(Vector(p))
            if loc is None or d > 0.05:
                continue
            loc, nor = np.array(loc), np.array(nor)
            s = np.dot(p - loc, nor)
            if abs(s) < 0.5 * d:
                continue        # beside an open edge, not over the face
            if s < dist:
                if log is not None:
                    log.append((i, bi, s, d))
                p = loc + nor * dist
                moved += 1
            break               # now outside this layer: the inner ones are behind it
        X[i] = p
    return X, moved


def thicken(X, T, Nout, bids, attach, t_cm, taper_q, Vc):
    """Solidify toward the base by t (tapered to 0 near the attachment edge), with a rounded
    rim on the free boundary. Returns (V, F)."""
    n = len(X)
    t = (t_cm / 100.0) * sp.smoothstep(Vc[:, 1] / taper_q)
    # the sheet's visible side: Nout (away from its base)
    Xi = X - Nout * t[:, None]
    V = np.vstack([X, Xi])
    F = [tuple(f) for f in T] + [tuple(f[::-1] + n) for f in T]
    # rim: the boundary loop, skipping the attachment edge
    b = list(bids)
    for k in range(len(b)):
        i, j = b[k], b[(k + 1) % len(b)]
        if attach[i] and attach[j]:
            continue
        F.append((j, i, i + n, j + n))
    return V, F


def build(X, T, chains, D, under_bvhs=(), opts=None, stats=None):
    """The rever mesh (verts (n, 3) m, faces) on the draped jacket (X, T), welded chain
    ids per side `chains` = {"l": (ids, s_cm), "r": (ids, s_cm)}."""
    o = dict(DEFAULTS, **(opts or {}))
    G = chart_geometry(D)
    loop, gorge, CP = outline(G, o)
    Vc, Tc, bids, gl = triangulate(loop, gorge, o["h_cm"])
    surf = Surface(X, T)
    C = Columns(surf, chains, G, o)
    q_max = float(Vc[:, 1].max())
    C.walk(q_max + 2.0)
    under = under_bvhs[0] if under_bvhs else None
    Xr, Nout = map3d(Vc, C, G, o, under)
    X_map = Xr.copy()
    attach = Vc[:, 1] < 1e-6
    # relax the map (kinks at the gorge corner and the stand/jacket corner), then clear
    bnd = np.zeros(len(Vc), bool)
    bnd[bids] = True
    Xr = relax(Xr, Tc, attach | bnd, o["relax_iters"])
    X_relax = Xr.copy()
    clog = []
    Xr, moved = clear(Xr, [surf.bvh] + list(under_bvhs), o["clear_cm"] / 100.0 + o["thick_cm"] / 100.0,
                      skip=Vc[:, 1] < 1.5, log=clog)
    # outward normals of the sheet (consistent with Nout)
    Nm = vertex_normals(Xr, Tc)
    if np.einsum("ij,ij->i", Nm, Nout).mean() < 0:
        Nm = -Nm
        Tc = Tc[:, ::-1]
    V, F = thicken(Xr, Tc, Nm, bids, attach, o["thick_cm"], 0.6, Vc)
    if stats is not None:
        stats.update({"chart": {k: round(v, 2) for k, v in G.items() if isinstance(v, float)},
                      "collar_point_sq": [round(float(c), 2) for c in CP],
                      "verts": int(len(V)), "faces": int(len(F)), "pushed_out": int(moved)})
    dbg = {"col_s": C.s, "col_E": C.E, "col_D": C.D, "col_N": C.N, "col_T": C.T, "col_lean": C.lean,
           "col_W": C.W, "X_map": X_map, "clear_log": np.array(clog, float).reshape(-1, 4), "X_relax": X_relax}
    return V, F, {"chart_V": Vc, "chart_T": Tc, "sheet_X": Xr, "gorge_ids": gl, "attach": attach, "debug": dbg}
