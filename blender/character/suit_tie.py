"""A modelled four-in-hand tie for the made suit (m1 v4 T13d, item 8; replaces the lofted tie of
suit_inner.build_tie).

What a tied four-in-hand is, and what this models:

  knot   the wide end wrapped twice round the narrow end and passed down through the front loop:
         a narrow, slightly lopsided trapezoid (about 3.8 cm across at the top, 1.9 cm at the
         bottom, 5 cm tall), standing 1.2-1.5 cm off the collar band, its top rolled back under the
         collar points. Its face is the last wrap: a smooth band whose lower edge runs diagonally
         across the front (the step where the wrap ends), with soft compression creases fanning
         toward the bottom, where the blade comes out.
  blade  the wide end: silk over an interlining, 3.5 mm thick with rolled (round) edges and a
         slightly convex face, widening from about 3 cm where it leaves the knot to 7.8 cm, ending
         in a 90 deg point at the waistband. Just under the knot the single centred dimple: the
         face folds back into a soft V for 6-7 cm and the edges curl forward.
  (the narrow end behind the blade and the band round the neck under the collar are never seen
  and are not modelled)

Geometry only (numpy): build() returns vertices, quads/triangles, UVs (a uniform density in
metres times `uv_per_m`, v along the tie) and a part tag per face (0 knot, 1 blade). The caller
gives the surface the tie lies on as front(x, z) -> y (the most forward of the shirt and the collar
band), and places / rigs it (suit_spike main_posed: the knot on the collar's rigid row, the blade
wrapped on the shirt's drape).
"""

import math

import numpy as np

DEFAULTS = {
    "knot_w_top_m": 0.038, "knot_w_bot_m": 0.019, "knot_h_m": 0.050, "knot_d_m": 0.013,
    "knot_top_above_band_m": 0.002, "knot_skew_m": 0.004, "knot_full": 0.12,
    "wrap_step_m": 0.0016, "crease_m": 0.0005, "creases": 3,
    "blade_w_exit_m": 0.030, "blade_w_m": 0.078, "blade_full_at_m": 0.40, "blade_t_m": 0.0035,
    "blade_convex_m": 0.0010, "dimple_m": 0.0045, "dimple_len_m": 0.065, "clear_m": 0.0012,
    "ceil_clear_m": 0.0015, "t_min_m": 0.0012,
    "rows_knot": 26, "cols_knot": 36, "row_m": 0.008, "front_pts": 14, "end_pts": 4,
}


def _ss(t):
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3 - 2 * t)


def knot(front, band_y, z_top, P):
    """The knot's front shell: rows top -> bottom, columns across the front half. Returns (V (r, c, 3),
    UV (r, c, 2)) in metres."""
    nr, nc = P["rows_knot"], P["cols_knot"]
    H, D = P["knot_h_m"], P["knot_d_m"]
    V = np.zeros((nr + 1, nc + 1, 3))
    for k in range(nr + 1):
        v = k / nr
        z = z_top - H * v
        w = P["knot_w_top_m"] + (P["knot_w_bot_m"] - P["knot_w_top_m"]) * v ** 1.15
        w *= 0.90 + 0.10 * _ss(v / 0.15)                     # the top rolls in under the collar
        d = D * (0.55 + 0.45 * _ss(v / 0.25)) * (1 - 0.40 * v ** 1.6)
        d *= 1 - 0.55 * _ss((v - 0.88) / 0.12)               # the bottom closes onto the blade
        cx = P["knot_skew_m"] * (v - 0.5)
        yb = band_y(z)
        for i in range(nc + 1):
            ph = -math.pi / 2 + math.pi * i / nc
            sx = math.sin(ph)
            full = 1 + P["knot_full"] * max(sx, 0.0) * (0.4 + 0.6 * v)   # the wearer's left fuller below
            x = cx + 0.5 * w * sx * full
            fr = math.cos(ph) ** 0.6
            # the last wrap's lower edge: a diagonal across the face, upper right to lower left
            # (seen from the front), the band above it proud by wrap_step
            xd = 0.5 * w * (0.65 - 1.6 * (v - 0.35))
            step = P["wrap_step_m"] * float(_ss((x - xd) / 0.005 + 0.5)) * fr * float(_ss((0.92 - v) / 0.1))
            # compression creases fanning to the bottom
            cr = P["crease_m"] * float(_ss((v - 0.45) / 0.35)) * math.sin(P["creases"] * math.pi * (sx + 1)) * fr
            y = min(yb, front(x, z) - 0.0008) - d * fr - step - cr
            V[k, i] = (x, y, z)
    UV = np.zeros((nr + 1, nc + 1, 2))
    for k in range(nr + 1):
        L = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(V[k], axis=0), axis=1))])
        UV[k, :, 0] = L - L[-1] / 2
        UV[k, :, 1] = -(z_top - V[k, 0, 2])
    return V, UV


def blade(front, z0, z_tip, P, ceil=None):
    """The blade as rings (a flattened stadium: front, right edge, back, left edge) from z0 down to
    the point. ceil(x, z) -> y of what lies over the blade (the waistcoat's inside), or None: under
    it the blade is pressed to the room there is (a tie under a buttoned waistcoat lies flat).
    Returns (rings (r, m, 3), UV (r, m, 2), tip point, tip uv)."""
    nf, ne = P["front_pts"], P["end_pts"]
    t = P["blade_t_m"]
    L = z0 - z_tip
    nrow = max(8, int(math.ceil(L / P["row_m"])))
    rings, uvs = [], []
    w1 = P["blade_w_m"]
    tip_len = 0.5 * w1                                       # a 90 deg point
    for k in range(nrow + 1):
        z = z0 - L * k / nrow
        dd = z0 - z
        w = P["blade_w_exit_m"] + (w1 - P["blade_w_exit_m"]) * (1 - math.exp(-3.0 * dd / P["blade_full_at_m"])) / (1 - math.exp(-3.0))
        w = min(w, w1)
        to_tip = z - z_tip
        if to_tip < tip_len:
            w = max(2 * to_tip, 2.2 * r_)
        xs = np.linspace(-0.5 * w, 0.5 * w, 7)
        fy = [front(float(x), z) for x in xs]
        t_ = t
        conv_k = 1.0
        dim_k = 1.0
        if ceil is not None:
            cy = [ceil(float(x), z) for x in xs]
            room = [f_ - c_ for f_, c_ in zip(fy, cy) if c_ is not None]
            if room:
                # under the waistcoat: thickness, crown and dimple pressed into the room there is
                avail = min(room) - P["clear_m"] - P["ceil_clear_m"]
                t_ = float(np.clip(avail, P["t_min_m"], t))
                conv_k = dim_k = t_ / t
        r_ = 0.5 * t_
        half = max(0.5 * w - r_, 0.0005)
        dim = (P["dimple_m"] * float(_ss(1 - dd / P["dimple_len_m"])) if dd > 0 else P["dimple_m"]) * dim_k
        # the lying surface: the most forward point of the shirt across the blade (an interlined blade
        # bridges the placket), then the blade's back clear of it
        yb = min(fy) - P["clear_m"] - r_
        pts, us = [], []
        # front: x from -half to +half
        for j in range(nf + 1):
            s = -1 + 2 * j / nf
            x = s * half
            conv = P["blade_convex_m"] * conv_k * (1 - s * s)
            dimple = dim * max(0.0, 1 - abs(s) * 1.25) ** 1.5 - 0.35 * dim * s * s   # the V back, the edges forward
            pts.append((x, yb - r_ - conv + dimple, z))
            us.append(x)
        # right edge: the half round from front to back
        for j in range(1, ne):
            a = -math.pi / 2 + math.pi * j / ne
            pts.append((half + r_ * math.cos(a), yb + r_ * math.sin(a), z))
            us.append(half + r_ * (1 + a / (math.pi / 2)) * 0.5 * math.pi / 2)
        # back: x from +half to -half
        for j in range(nf + 1):
            s = 1 - 2 * j / nf
            pts.append((s * half, yb + r_, z))
            us.append(half + math.pi * r_ + (1 - s) * half)
        # left edge: back to front
        for j in range(1, ne):
            a = math.pi / 2 + math.pi * j / ne
            pts.append((-half + r_ * math.cos(a), yb + r_ * math.sin(a), z))
            us.append(3 * half + math.pi * r_ + r_ * j / ne * math.pi)
        rings.append(pts)
        uvs.append([(u_ - 0.5 * w1, -dd) for u_ in us])
    rings = np.array(rings)
    tip = rings[-1].mean(0)
    return rings, np.array(uvs), tip


def build(front, band_y, z_top, z_tip, opts=None, uv_per_m=1.0, uv_origin=(0.5, 0.5), ceil=None):
    """front(x, z) -> y of the surface under the tie; band_y(z) -> y of the collar band's front at the
    centre (the knot's back). Returns V (n, 3), faces (list of index tuples), corner UVs (per face, per
    corner), face tags (0 knot, 1 blade)."""
    P = dict(DEFAULTS)
    P.update(opts or {})
    Kv, Kuv = knot(front, band_y, z_top, P)
    z_kb = z_top - P["knot_h_m"]
    # the blade starts inside the knot (its top hidden in it) and runs to the point
    Bv, Buv, tip = blade(front, z_kb + 0.012, z_tip, P, ceil)
    V, F, UVc, tags = [], [], [], []

    def add(p):
        V.append(tuple(map(float, p)))
        return len(V) - 1
    nr, nc = Kv.shape[0] - 1, Kv.shape[1] - 1
    Ki = np.array([[add(Kv[k, i]) for i in range(nc + 1)] for k in range(nr + 1)])
    for k in range(nr):
        for i in range(nc):
            a, b, c, d = Ki[k, i], Ki[k, i + 1], Ki[k + 1, i + 1], Ki[k + 1, i]
            F.append((a, d, c, b))           # normals out (toward -y, the viewer)
            UVc.append([Kuv[k, i], Kuv[k + 1, i], Kuv[k + 1, i + 1], Kuv[k, i + 1]])
            tags.append(0)
    nb, m = Bv.shape[0], Bv.shape[1]
    Bi = np.array([[add(Bv[k, j]) for j in range(m)] for k in range(nb)])
    for k in range(nb - 1):
        for j in range(m):
            j2 = (j + 1) % m
            a, b, c, d = Bi[k, j], Bi[k, j2], Bi[k + 1, j2], Bi[k + 1, j]
            F.append((a, d, c, b))           # outward (the ring runs counter-clockwise from above)
            u2 = Buv[k, j2] if j2 else Buv[k, j] + np.array([0.004, 0.0])
            u3 = Buv[k + 1, j2] if j2 else Buv[k + 1, j] + np.array([0.004, 0.0])
            UVc.append([Buv[k, j], Buv[k + 1, j], u3, u2])
            tags.append(1)
    ti = add(tip)
    for j in range(m):
        j2 = (j + 1) % m
        F.append((Bi[-1, j2], Bi[-1, j], ti))
        UVc.append([Buv[-1, j2], Buv[-1, j], Buv[-1].mean(0)])
        tags.append(1)
    V = np.array(V)
    UVc = [[(uv_origin[0] + uv_per_m * float(u[0]), uv_origin[1] + uv_per_m * float(u[1])) for u in f] for f in UVc]
    return V, F, UVc, np.array(tags)
