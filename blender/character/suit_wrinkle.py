"""Per-pose wrinkle maps for the made suit (T13 item 7). numpy only.

The corrective shape keys (suit_rig.fit_shapes, item 6) carry each pose's drape as a smooth
least-squares blend over the suit's cones, so a fold that one pose makes and its neighbours do
not (the crook of a bent elbow, the drag lines under a raised arm, the skirt over a raised
thigh) is averaged away in the geometry. What the blend leaves is baked here as a tangent-space
normal delta and blended back by pose in the engine:

* per pose k and made vertex v: the simulated normal and the runtime normal (LBS + shapes), both
  taken back to rest space with the vertex's blended skinning rotation; their difference in the
  rest tangent frame (t along the atlas u, b along v) is dN_k(v), a 2-vector;
* the cones are pooled into a few wrinkle groups (GROUPS: arms raised, arms down / crook, hip,
  torso); a group's weight at a pose is the largest of its cones' weights on that side, and a
  vertex takes its own side's (the centre line blends over +-4 cm);
* per vertex: dN_k(v) ~ sum_j a_kj(v) G_j(v), least squares over the pose set (ridge), so each
  group's map holds the fold that group's poses share;
* the G_j are rasterised into the part's atlas (pad-dilated), two groups per RGBA texture
  (RG, BA), encoded 0.5 + dN / (2 * RANGE).

The engine (web/src/character/cloth.ts) adds sum_j w_j G_j to the tangent-space normal's XY
before the normal map's own detail, w_j from the same cone weights (DeformRuntime) and the
vertex's side.
"""

import numpy as np

# wrinkle groups: name -> cone name stems (suit_<stem>_<side> rules; the spine ones have no side)
GROUPS = {
    "arm_up": ["arm_abd90", "arm_abd90_h", "arm_abd135", "arm_flex90", "arm_flex90_h", "arm_flex135"],
    "arm_down": ["arm_down", "arm_back", "elbow90", "elbow90_h"],
    "hip": ["thigh_flex90", "thigh_flex90_h", "thigh_abd40", "thigh_ext30"],
    "torso": ["spine_flex40", "spine_ext20", "spine_tilt25_l", "spine_tilt25_r", "spine_turn40_l", "spine_turn40_r"],
}
RANGE = 0.5          # |dN| per channel at full code


def group_weights(cones, A):
    """A (K, C) cone weights per pose -> (K, G, 2) group weights per side (l, r); the spine groups
    have the same weight both sides."""
    names = [c["name"] for c in cones]
    out = np.zeros((A.shape[0], len(GROUPS), 2))
    for j, (g, stems) in enumerate(GROUPS.items()):
        for si, s in enumerate(("l", "r")):
            cols = [names.index(f"suit_{st}_{s}") for st in stems if f"suit_{st}_{s}" in names]
            cols += [names.index(f"suit_{st}") for st in stems if f"suit_{st}" in names]
            if cols:
                out[:, j, si] = A[:, cols].max(1)
    return out


def side_mix(x, sx=1.0, band=0.04):
    """Share of the left side's weight for rest x (sx = +1 when the character's left is +x)."""
    t = np.clip((x * sx + band) / (2 * band), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def tangent_frames(V, F, UV):
    """Per-vertex rest tangent frame (t, b, n) from positions, triangles and per-vertex UVs."""
    n = np.zeros_like(V)
    t = np.zeros_like(V)
    p0, p1, p2 = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    u0, u1, u2 = UV[F[:, 0]], UV[F[:, 1]], UV[F[:, 2]]
    e1, e2 = p1 - p0, p2 - p0
    d1, d2 = u1 - u0, u2 - u0
    fn = np.cross(e1, e2)
    r = d1[:, 0] * d2[:, 1] - d2[:, 0] * d1[:, 1]
    r = np.where(np.abs(r) > 1e-14, 1.0 / np.where(np.abs(r) > 1e-14, r, 1.0), 0.0)
    ft = (e1 * d2[:, 1:2] - e2 * d1[:, 1:2]) * r[:, None]
    for k in range(3):
        np.add.at(n, F[:, k], fn)
        np.add.at(t, F[:, k], ft)
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    t = t - n * np.sum(t * n, 1, keepdims=True)
    t /= np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-12)
    b = np.cross(n, t)
    return t, b, n


def vertex_normals(V, F):
    fn = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    n = np.zeros_like(V)
    for k in range(3):
        np.add.at(n, F[:, k], fn)
    return n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)


def rest_normals(R, N):
    """Normals N (n, 3) taken back to rest space by the blended rotations R (n, 3, 3)."""
    m = np.einsum("nji,nj->ni", R, N)          # R^T N (R nearly orthonormal)
    return m / np.maximum(np.linalg.norm(m, axis=1, keepdims=True), 1e-12)


def deltas(Nsim, Nrt, frame):
    """2D tangent-space delta between rest-space normals (sim minus runtime)."""
    t, b, _ = frame
    d = Nsim - Nrt
    return np.stack([np.sum(d * t, 1), np.sum(d * b, 1)], 1)


def fit_groups(dN, Gw, mixl, lam=0.02):
    """dN (K, n, 2) per pose; Gw (K, G, 2) group weights per side; mixl (n,) left share.
    Returns (G, n, 2) group maps minimising sum_k |sum_j a_kj(v) G_j(v) - dN_k(v)|^2 + lam |G|^2."""
    a = Gw[:, None, :, 0] * mixl[None, :, None] + Gw[:, None, :, 1] * (1 - mixl[None, :, None])   # (K, n, G)
    M = np.einsum("knj,kni->nji", a, a) + lam * np.eye(a.shape[2])[None]
    R = np.einsum("knj,knc->njc", a, dN)
    return np.linalg.solve(M, R).transpose(1, 0, 2)


def raster(UVc, Fc, vals, px, pad=4):
    """Rasterise per-corner values into a px x px atlas. UVc (m, 3, 2) per-triangle corner UVs in
    [0, 1], vals (m, 3, c). Returns (px, px, c) and the coverage mask. The islands are dilated by
    pad px (the nearest covered texel's value) so mip levels and filtering do not pull in zero."""
    c = vals.shape[2]
    img = np.zeros((px, px, c), np.float32)
    cov = np.zeros((px, px), bool)
    P = UVc * px - 0.5
    for tri, v in zip(P, vals):
        lo = np.floor(tri.min(0)).astype(int)
        hi = np.ceil(tri.max(0)).astype(int)
        lo = np.clip(lo, 0, px - 1)
        hi = np.clip(hi, 0, px - 1)
        if (hi < lo).any():
            continue
        xs, ys = np.meshgrid(np.arange(lo[0], hi[0] + 1), np.arange(lo[1], hi[1] + 1))
        q = np.stack([xs.ravel(), ys.ravel()], 1).astype(float)
        a, b, cc = tri
        v0, v1 = b - a, cc - a
        den = v0[0] * v1[1] - v1[0] * v0[1]
        if abs(den) < 1e-12:
            continue
        w = q - a
        l1 = (w[:, 0] * v1[1] - v1[0] * w[:, 1]) / den
        l2 = (v0[0] * w[:, 1] - w[:, 0] * v0[1]) / den
        l0 = 1 - l1 - l2
        ins = (l0 >= -1e-3) & (l1 >= -1e-3) & (l2 >= -1e-3)
        if not ins.any():
            continue
        L = np.stack([l0, l1, l2], 1)[ins]
        val = L @ v
        yy, xx = q[ins, 1].astype(int), q[ins, 0].astype(int)
        img[yy, xx] = val
        cov[yy, xx] = True
    # dilate
    grown = cov.copy()
    for _ in range(pad):
        nb = np.zeros_like(img)
        cnt = np.zeros((px, px))
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            sh = np.roll(np.roll(img * grown[..., None], dy, 0), dx, 1)
            sc = np.roll(np.roll(grown, dy, 0), dx, 1)
            nb += sh
            cnt += sc
        new = (~grown) & (cnt > 0)
        img[new] = nb[new] / cnt[new][:, None]
        grown |= new
    return img, cov


def encode(G2):
    """(px, px, 2) deltas -> uint8 RG codes."""
    return np.clip(np.round((0.5 + G2 / (2 * RANGE)) * 255), 0, 255).astype(np.uint8)
