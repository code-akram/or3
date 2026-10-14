"""Hull-smoothed torso collider for the drafted jacket (m1 v4 T13; bench/m1/v4/suit-spike.md §5.3).

A real jacket bridges the hollows of the back (the spine groove, between and below the
shoulder blades, the small of the back) with cloth, canvas and lining. Draped on the bare
body, cloth follows every hollow. This builds a closed tube round the torso that the jacket
collides with instead:

  horizontal   each level is the convex hull of the torso section and the under-garments
               (a tape round the body bridges every horizontal hollow)
  vertical     on the back, each column (fixed angle round the axis) is pulled toward its
               upper hull in (z, r): a straight edge from the blades to the seat bridges the
               small of the back. `alpha_back` is the share (1 = a sack back, 0 = none):
               a suppressed jacket still follows the lumbar curve a little.
  top          the hull effect fades out over the top rows so the tube meets the body
               without a ledge

numpy only (no bpy). Units: metres, Z up, front = -Y, wearer's left = +X.
"""

import math

import numpy as np

from .suit_pattern import _hull, section, smoothstep

DEFAULTS = {
    "dz_m": 0.01,
    "n_theta": 96,
    "alpha_back": 0.75,
    "back_w": (0.15, 0.65),     # sin(theta) range over which the vertical hull fades in (0 = side, 1 = CB)
    "top_fade_m": 0.05,
    "garment_slab_m": 0.006,
    "smooth_iters": 2,
}


def _ray_poly(c, ang, poly_segs):
    """Largest t >= 0 where the ray c + t (cos, sin) meets any segment (K, 2, 2)."""
    d = np.stack([np.cos(ang), np.sin(ang)], 1)              # (A, 2)
    a, b = poly_segs[:, 0] - c, poly_segs[:, 1] - c          # (K, 2)
    e = b - a
    den = d[:, None, 0] * e[None, :, 1] - d[:, None, 1] * e[None, :, 0]     # (A, K)
    ok = np.abs(den) > 1e-12
    den = np.where(ok, den, 1.0)
    t = (a[None, :, 0] * e[None, :, 1] - a[None, :, 1] * e[None, :, 0]) / den
    u = (a[None, :, 0] * d[:, None, 1] - a[None, :, 1] * d[:, None, 0]) / den
    hit = ok & (u >= 0) & (u <= 1) & (t > 0)
    return np.where(hit, t, 0.0).max(1)


def _upper_hull_1d(z, r):
    """The concave (upper) envelope of r(z), sampled at z."""
    idx = []
    for i in range(len(z)):
        while len(idx) >= 2:
            i0, i1 = idx[-2], idx[-1]
            # drop i1 if it lies on or below the chord i0 -> i
            cr = (z[i1] - z[i0]) * (r[i] - r[i0]) - (r[i1] - r[i0]) * (z[i] - z[i0])
            if cr >= 0:
                idx.pop()
            else:
                break
        idx.append(i)
    return np.interp(z, z[idx], r[idx])


def build(co, tris, f_mask, z_lo, z_hi, garment_pts=(), opts=None):
    """The tube as (verts (n, 3), quads (m, 4), info). f_mask: the torso/trunk faces of the
    body (BodyMeasure.f_trunk); garment_pts: (k, 3) world points of the under-garments."""
    o = dict(DEFAULTS, **(opts or {}))
    zs = np.arange(z_lo, z_hi + 1e-9, o["dz_m"])
    na = o["n_theta"]
    th = 2 * math.pi * np.arange(na) / na
    G = np.asarray(garment_pts, float).reshape(-1, 3)
    body_tris = np.asarray(tris)[f_mask]
    secs, hulls, C = [], [], []
    for z in zs:
        s = section(co, body_tris, 2, z)
        p2 = s.reshape(-1, 3)[:, :2]
        xlim = np.abs(p2[:, 0]).max() + 0.005
        g = G[(np.abs(G[:, 2] - z) < o["garment_slab_m"]) & (np.abs(G[:, 0]) < xlim)][:, :2]
        h = _hull(np.vstack([p2, g]) if len(g) else p2)
        secs.append(s[:, :, :2])
        hulls.append(np.stack([h, np.roll(h, -1, axis=0)], 1))
        C.append(0.5 * (h[:, 1].max() + h[:, 1].min()))
    # the axis: a straight line through the ring centres (no kinks in the tube)
    k, y0 = np.polyfit(zs, np.array(C), 1)
    Cf = y0 + k * zs
    R = np.array([_ray_poly(np.array([0.0, c]), th, hs) for c, hs in zip(Cf, hulls)])
    Rb = np.array([_ray_poly(np.array([0.0, c]), th, s) for c, s in zip(Cf, secs)])
    # vertical hull on the back
    Rv = np.stack([_upper_hull_1d(zs, R[:, j]) for j in range(na)], 1)
    a0, a1 = o["back_w"]
    w = smoothstep((np.sin(th) - a0) / (a1 - a0)) * o["alpha_back"]
    Rt = R + (Rv - R) * w[None, :]
    # smooth (round the ring and up the column), never inside the horizontal hull
    for _ in range(o["smooth_iters"]):
        Rs = Rt.copy()
        Rs[1:-1] = 0.25 * Rt[:-2] + 0.5 * Rt[1:-1] + 0.25 * Rt[2:]
        Rs = 0.25 * np.roll(Rs, 1, 1) + 0.5 * Rs + 0.25 * np.roll(Rs, -1, 1)
        Rt = np.maximum(Rs, R)
    # the vertical hull fades out over the top rows (the tube ends as the plain horizontal
    # hull, which bridges the spine groove up to the neck base)
    f = smoothstep((z_hi - zs) / o["top_fade_m"])[:, None]
    Rt = R + (Rt - R) * f
    V = np.zeros((len(zs), na, 3))
    V[..., 0] = Rt * np.cos(th)[None]
    V[..., 1] = Cf[:, None] + Rt * np.sin(th)[None]
    V[..., 2] = zs[:, None]
    nz = len(zs)
    F = []
    for i in range(nz - 1):
        for j in range(na):
            j1 = (j + 1) % na
            F.append((i * na + j, i * na + j1, (i + 1) * na + j1, (i + 1) * na + j))
    lift = Rt - Rb
    info = {"levels": int(nz), "n_theta": na, "lift_back_max_mm": round(float(lift[:, np.sin(th) > 0.5].max() * 1000), 1),
            "lift_back_mean_mm": round(float(lift[:, np.sin(th) > 0.5].mean() * 1000), 1),
            "lift_front_mean_mm": round(float(lift[:, np.sin(th) < -0.5].mean() * 1000), 1)}
    radial = {"zs": zs, "theta": th, "R": Rt, "axis": (float(k), float(y0))}
    return V.reshape(-1, 3), np.array(F), info, radial


class TubeSDF:
    """Signed radial distance to the tube (negative inside), for z in its range; +big above
    the top and below the bottom. The gradient is the horizontal radial direction."""

    def __init__(self, radial, top_fade_m=0.0):
        self.zs, self.th, self.R = radial["zs"], radial["theta"], radial["R"]
        self.k, self.y0 = radial["axis"]
        self.fade = top_fade_m

    def __call__(self, P):
        P = np.atleast_2d(P)
        cy = self.y0 + self.k * P[:, 2]
        dx, dy = P[:, 0], P[:, 1] - cy
        rho = np.hypot(dx, dy)
        a = np.mod(np.arctan2(dy, dx), 2 * math.pi)
        na = len(self.th)
        u = a / (2 * math.pi) * na
        i0 = np.floor(u).astype(int) % na
        fu = u - np.floor(u)
        i1 = (i0 + 1) % na
        zz = np.clip((P[:, 2] - self.zs[0]) / (self.zs[1] - self.zs[0]), 0, len(self.zs) - 1.000001)
        k0 = np.floor(zz).astype(int)
        fz = zz - k0
        R = ((self.R[k0, i0] * (1 - fu) + self.R[k0, i1] * fu) * (1 - fz)
             + (self.R[k0 + 1, i0] * (1 - fu) + self.R[k0 + 1, i1] * fu) * fz)
        d = rho - R
        out = (P[:, 2] < self.zs[0]) | (P[:, 2] > self.zs[-1])
        d = np.where(out, 1e3, d)
        g = np.stack([dx, dy, np.zeros_like(dx)], 1) / np.maximum(rho, 1e-9)[:, None]
        return d, g
