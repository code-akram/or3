"""Skin synthesis in texture space (m1 v2 track A): albedo, roughness, height
and the hero-only detail masks, from the maps skin_tex bakes on the game mesh.

Targets (bench/m1/v2/direction.md §2 Track A, §3; numbers are starting points):

  albedo     mean sRGB ~ (0.70, 0.55, 0.46). Three zones: forehead a little
             yellow; mid-face red at the nose tip, alar, cheek apples and
             ears; lower face cool, the beard zone 15 % darker and blue-grey.
             Under-eye darker, violet-brown; faint temple veins; broken
             capillaries on the alar; faint freckles and small blemishes
             (no mole, no scar: user ruling). Lips wind-dried, vertical creases.
  roughness  a map: T-zone ~0.40, cheeks 0.50, beard zone 0.58, lips 0.45
             with crease breakup, ears 0.48; mean ~0.48.
  height     pores by region from three 3D Voronoi layers (nose 60/cm²,
             0.3-0.4 mm; cheeks 35/cm², 0.25-0.35 mm; forehead 20/cm²,
             0.15 mm), the hero shader evaluates the same layers on the rest
             position, so game and hero pores coincide; lines: two broken
             forehead lines, two soft glabellar frown furrows (left deeper), crow's
             feet (left set longer), under-eye lines, the nasolabial crease,
             lip creases, neck rings.

Outputs are linear float arrays; skin_tex turns them into images.
"""

import math

import numpy as np

HEX = lambda h: np.array([int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)], dtype=np.float32)  # noqa: E731
MM = 0.001

# Pore layers: (bake channel in noise A, Voronoi scale 1/m, pit radius in
# cell units, depth mm). The Voronoi is 3D (seamless across UV islands), so the
# skin is a 2D slice through a 3D point field: a feature point makes a pit only
# when it lies within r of the surface, and the pit's radius is the slice
# sqrt(r^2 - d^2) (a natural spread of sizes). Surface density is therefore
# scale^3 * 2 r_m, so the scale is set from the target density (direction.md
# §2 Track A): nose 60/cm2 at r_m 0.20 mm, cheek 35/cm2 at 0.17 mm, forehead
# 20/cm2 at 0.09 mm.
PORE_LAYERS = {
    "nose": (0, 1145.0, 0.229, 0.070),
    "cheek": (1, 1010.0, 0.172, 0.060),
    "forehead": (2, 1040.0, 0.094, 0.040),
}
NOISE_SPECS = {
    "noiseA": tuple(("voronoi", v[1]) for v in sorted(PORE_LAYERS.values())),
    "noiseB": (("noise", 350.0, 3.0), ("noise", 55.0, 2.0), ("noise", 22.0, 1.0)),
    "noiseC": (("noise_aniso", 900.0, (1.0, 1.0, 0.05)), ("noise_aniso", 900.0, (0.05, 1.0, 1.0)),
               ("noise", 3000.0, 2.0)),
    "noiseD": (("noise", 180.0, 4.0), ("edge", 300.0), ("noise", 40.0, 2.0)),
    # skin-direction.md: haemoglobin 90/m, melanin 30/m, subdermal lumps 120/m
    "noiseE": (("noise", 90.0, 2.0), ("noise", 30.0, 2.0), ("noise", 120.0, 1.0)),
    # orange peel (Voronoi edge 350/m, 1.5:1 along x, distortion 1.5), nose and
    # alar bumps (0.6 mm cells), 1.5 mm lip bumps
    "noiseF": (("edge_aniso", 350.0, (0.667, 1.0, 1.0), 1.5), ("voronoi", 1667.0), ("noise", 650.0, 1.0)),
    # fine-scale redness (capillary scale, 3-7 mm); the third channel is unused
    "noiseG": (("noise", 150.0, 2.0), ("noise", 300.0, 2.0), ("noise", 450.0, 2.0)),
    # T12 mid band (0.5-3 mm): a ~2 mm fBm (texture, pore clusters, sheen patches), Voronoi edges
    # (~1.7 mm skin plateaus) and a horizontally stretched noise (fine forehead lines ~3 mm apart)
    "noiseH": (("noise", 450.0, 3.0), ("edge", 600.0), ("noise_aniso", 330.0, (0.06, 1.0, 1.0))),
}


def srgb_to_linear(c):
    c = np.asarray(c, dtype=np.float32)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4).astype(np.float32)


def linear_to_srgb(c):
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.0031308, 12.92 * c, 1.055 * np.power(c, 1 / 2.4) - 0.055).astype(np.float32)


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def gauss(x, w):
    return np.exp(-0.5 * (x / w) ** 2)


def pits(f1, scale, r, texel_m, depth_mm):
    """Pore pit depth (metres, positive = deeper) from a Voronoi F1 distance
    (cell units). The pit is widened to at least ~0.7 texel and its depth
    scaled down to match, so sub-texel pores don't alias into grain."""
    texel_cells = texel_m * scale
    r_eff = np.sqrt(r * r + (0.7 * texel_cells) ** 2)
    k = (r / r_eff) ** 2
    return depth_mm * MM * k * (1 - smoothstep(0.0, r_eff, f1))


class Frame:
    """Face frame per texel (metres at the reference IPD)."""

    def __init__(self, m, cl, cr, spheres=None):
        o = (cl + cr) * 0.5
        s = float(np.linalg.norm(cl - cr)) / 0.0616
        d = m.P - o
        self.s = s
        self.x = d[..., 0] / s
        self.u = np.abs(self.x)
        self.left = (self.x > 0).astype(np.float32)
        self.h = d[..., 2] / s
        self.f = -d[..., 1] / s
        self.eye_d = np.minimum(np.linalg.norm(m.P - cl, axis=-1), np.linalg.norm(m.P - cr, axis=-1)) / s
        if spheres:
            # T12: distance from the shipped globe centres (the sculpt layer's 12 mm globes), mapped
            # so the visible lid skin starts where it started on the MPFB eye the eye-region rings
            # were tuned on (EYE_LID_REF). From the bake-time eye centroids the lid, socket and crepe
            # rings sat 3-6 mm outside the lids.
            d = np.min([np.linalg.norm(m.P - np.asarray(c_, np.float32), axis=-1) / (r_ + EYE_LID_GAP)
                        for c_, r_ in spheres], axis=0)
            self.eye_d = d * EYE_LID_REF / s
        self.front = np.clip(-m.N[..., 1], 0.0, 1.0)


def polyline(a, b, pts):
    pts = np.asarray(pts, dtype=np.float32)
    d = np.full(a.shape, np.inf, dtype=np.float32)
    tt = np.zeros(a.shape, dtype=np.float32)
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    total, acc = float(seg.sum()), 0.0
    for (p0, p1), L in zip(zip(pts[:-1], pts[1:]), seg):
        e = p1 - p0
        t = np.clip(((a - p0[0]) * e[0] + (b - p0[1]) * e[1]) / max(float(L * L), 1e-12), 0, 1)
        dd = np.hypot(a - (p0[0] + t * e[0]), b - (p0[1] + t * e[1]))
        closer = dd < d
        d = np.where(closer, dd, d)
        tt = np.where(closer, (acc + t * L) / max(total, 1e-9), tt)
        acc += float(L)
    return d, tt


def groove(d, tt, amp, w, fade="ends", shoulder=0.25):
    """Groove profile (metres): Gaussian with soft raised shoulders."""
    prof = gauss(d, w) - shoulder * gauss(d, 2.4 * w)
    if fade == "ends":
        prof = prof * np.sin(np.pi * np.clip(tt, 0, 1)) ** 0.6
    elif fade == "end":
        prof = prof * (1 - tt) ** 0.8
    return amp * prof


def regions(fr, m):
    u, h, f = fr.u, fr.h, fr.f
    lips = np.clip(m.lips, 0, 1)
    r = {}
    fwd = smoothstep(-0.02, 0.01, f)
    r["lips"] = lips
    r["forehead"] = smoothstep(0.028, 0.045, h) * fwd * (1 - smoothstep(0.055, 0.07, u))
    r["nose"] = gauss(u, 0.013) * smoothstep(0.012, -0.005, h) * smoothstep(-0.058, -0.045, h) * smoothstep(0.015, 0.03, f)
    r["nose_tip"] = gauss(u, 0.010) * gauss(h + 0.044, 0.008) * smoothstep(0.03, 0.045, f)
    r["alar"] = gauss(u - 0.016, 0.006) * gauss(h + 0.043, 0.006) * smoothstep(0.015, 0.03, f)
    r["cheek"] = gauss(u - 0.042, 0.016) * gauss(h + 0.032, 0.016) * fwd
    r["apple"] = gauss(u - 0.036, 0.011) * gauss(h + 0.030, 0.010) * fwd
    r["under_eye"] = gauss(u - 0.030, 0.012) * gauss(h + 0.014, 0.006) * smoothstep(-0.005, 0.01, f) * (fr.eye_d > 0.009)
    # eye_d is in frame units from the eye centres (the MPFB eye radius is ~16 of them);
    # outside_eye drops the lid surfaces tucked behind the eyeball
    outside_eye = smoothstep(0.0158, 0.0168, fr.eye_d)
    r["socket"] = gauss(fr.eye_d - 0.019, 0.0055) * outside_eye * smoothstep(-0.01, 0.01, f)
    r["lid"] = gauss(fr.eye_d - 0.0175, 0.0022) * outside_eye * smoothstep(-0.003, 0.002, h)
    # T12: both lids and the skin just round them (periorbital pigment, thin skin: the darker ring
    # that keeps the eye band reading at a distance), the lower lid included
    # (down to the lid margin, which sits within EYE_LID_GAP of the globe, inside outside_eye's edge)
    r["orbit"] = gauss(fr.eye_d - 0.0175, 0.0035) * smoothstep(0.0150, 0.0158, fr.eye_d)
    r["roof"] = gauss(u - 0.031, 0.016) * gauss(h - 0.010, 0.0055) * smoothstep(-0.01, 0.01, f)
    r["temple"] = gauss(u - 0.060, 0.012) * gauss(h - 0.022, 0.018)
    r["chin"] = gauss(u, 0.016) * gauss(h + 0.108, 0.014) * fwd
    r["ears"] = np.clip(m.ears, 0, 1)
    r["scalp"] = np.clip(m.scalp, 0, 1)
    r["neck"] = ((m.region > 0.6) & (m.region < 0.85)).astype(np.float32)
    # beard: the beard track's own region (hair_beard rules) when available
    if np.any(m.beard_in >= 0):
        beard = np.clip(m.beard_in, 0, 1)
    else:
        beard = smoothstep(-0.040, -0.060, h) * (1 - r["nose"]) * smoothstep(-0.03, 0.0, f) \
            * smoothstep(0.075, 0.055, u)
    r["beard"] = beard * (1 - lips)
    # T17: the inner eye corners (caruncle side, ~14 mm medial of the globe centre), a soft warm zone
    r["canthus"] = gauss(u - 0.016, 0.005) * gauss(h + 0.002, 0.005) * outside_eye * smoothstep(-0.01, 0.01, f)
    r["tzone"] = np.clip(r["forehead"] * gauss(u, 0.028) + r["nose"] + 0.6 * r["chin"], 0, 1)
    return r


def dist_to(P, seeds, where, n_seed=3000, chunk=4096):
    """3D distance (m) from the texels in `where` to the nearest texel in
    `seeds` (subsampled to ~n_seed); inf elsewhere, and everywhere when there
    are fewer than 16 seeds."""
    out = np.full(where.shape, np.inf, np.float32)
    if seeds.sum() < 16 or not where.any():
        return out
    # about the seeds' centre: |p|^2 + |q|^2 - 2 p.q in float32 at ~1.7 m from
    # the origin loses ~0.6 mm, the scale of the lip edge itself
    o = P[seeds].mean(0)
    Q = (P[seeds] - o).astype(np.float32)
    Q = Q[::max(1, len(Q) // n_seed)]
    q2 = (Q * Q).sum(-1)
    Pw = (P[where] - o).astype(np.float32)
    d2 = np.empty(len(Pw), np.float32)
    for i in range(0, len(Pw), chunk):
        p = Pw[i:i + chunk]
        d2[i:i + chunk] = ((p * p).sum(-1)[:, None] + q2[None] - 2 * p @ Q.T).min(1)
    out[where] = np.sqrt(np.maximum(d2, 0))
    return out


def soft(a, valid, sigma_px):
    """Gaussian blur (FFT, periodic) of a over the valid texels only, renormalised by the blurred mask."""
    n0, n1 = a.shape
    f0, f1 = np.fft.fftfreq(n0)[:, None], np.fft.rfftfreq(n1)[None, :]
    k = np.exp(-2.0 * (np.pi * sigma_px) ** 2 * (f0 ** 2 + f1 ** 2))
    w = valid.astype(np.float32)
    num = np.fft.irfft2(np.fft.rfft2(a * w) * k, s=a.shape)
    den = np.fft.irfft2(np.fft.rfft2(w) * k, s=a.shape)
    return np.where(valid, num / np.maximum(den, 1e-3), a).astype(np.float32)


def lip_seam(m, lips, ao, width_m):
    """Closeness (0..1, a gauss of width_m) of each lip texel to where the lips
    meet. The inner lips pressed together bake to zero occlusion inside the lips
    group; the distance is 3D (the seam crosses UV islands and the inner lips
    fold away from the visible vermilion in UV)."""
    d = dist_to(m.P, m.valid & (lips > 0.6) & (ao < 0.05), m.valid & (lips > 0.05))
    return gauss(d, width_m).astype(np.float32)


def beard_lip_fill(m, lips, beard, band_m):
    """0..1 over the skin between the beard and the vermilion where that gap is
    narrower than band_m (3D: distance to the lips' 0.55 contour plus distance
    to the beard's 0.5 contour), so the beard zone reaches the lip. Beard hairs
    rooted at the gap comb away from it, and from the front the bare strip reads
    as a pale rim around the lip; under a dense beard that skin is in shadow."""
    out = np.zeros(lips.shape, np.float32)
    ring = m.valid & (lips > 0.05)
    if band_m <= 0 or not ring.any():
        return out
    lo, hi = m.P[ring].min(0) - 2 * band_m, m.P[ring].max(0) + 2 * band_m
    box = m.valid & np.all((m.P > lo) & (m.P < hi), axis=-1)
    # the lip side counts as distance 0 to the lips, so the skin under a soft
    # vermilion border (lip_soft_mm) is shadowed too and no light ring is left
    # between the lip colour and the strip; the beard side by its 0.5 contour
    # (dense seeds: a smooth edge where the beard is patchy)
    d_lip = np.where(lips >= 0.55, 0.0, dist_to(m.P, box & (np.abs(lips - 0.55) < 0.1), box))
    edge = box & (np.abs(beard - 0.5) < 0.15)
    d_beard = dist_to(m.P, edge if edge.sum() >= 256 else box & (beard >= 0.5), box, n_seed=8000)
    s = d_lip + np.where(beard >= 0.5, 0.0, d_beard)
    out[box] = smoothstep(1.5 * band_m, band_m, s[box])
    return out


def lip_weight(m, lips, soft_m):
    """Lip colour weight 0..1. soft_m 0: from the lips group weight (its falloff
    is one edge ring, so the vermilion border is as hard as the mesh). soft_m > 0:
    a smoothstep +-soft_m across the group's 0.55 contour by 3D distance, a soft
    border at any mesh density."""
    hard = smoothstep(0.25, 0.85, lips)
    if soft_m <= 0:
        return hard
    ring = m.valid & (lips > 0.05)
    if not ring.any():
        return hard
    lo, hi = m.P[ring].min(0) - 3 * soft_m, m.P[ring].max(0) + 3 * soft_m
    where = m.valid & np.all((m.P > lo) & (m.P < hi), axis=-1)
    d = dist_to(m.P, m.valid & (np.abs(lips - 0.55) < 0.1), where)
    out = hard.copy()
    s = np.where(lips > 0.55, d, -d)[where]
    out[where] = smoothstep(-soft_m, soft_m, s)
    return out


EYE_LID_REF = 0.0168     # eye_d where the visible lid skin starts on the v2 MPFB eye (outside_eye)
EYE_LID_GAP = 0.0006     # the lid skin's stand-off over the shipped globe (head_sculpt clearance)


def synth_head(m, c, cl, cr):
    fr = Frame(m, cl, cr, c.get("eye_spheres"))
    R = regions(fr, m)
    u, h, x = fr.u, fr.h, fr.x
    lips = R["lips"]
    lip_fill = beard_lip_fill(m, lips, R["beard"], c["beard_to_lip_mm"] * MM)
    R["beard"] = np.maximum(R["beard"], lip_fill)
    eyes_clear = smoothstep(0.012, 0.018, fr.eye_d)

    # ---------------------------------------------------------------- height
    texel = m.tex_m
    w_nose = np.clip(R["nose"] * 1.2, 0, 1)
    face = (np.abs(m.region - 0.5) < 0.05).astype(np.float32)
    broad_cheek = gauss(u - 0.040, 0.024) * gauss(h + 0.035, 0.024) * smoothstep(-0.02, 0.01, fr.f)
    w_cheek = np.clip(np.maximum(broad_cheek * 1.4 + 0.8 * R["chin"] + 0.35 * R["neck"] + 0.4 * R["temple"], 0.6 * face),
                      0, 1) * (1 - w_nose)
    w_fore = np.clip(R["forehead"] + 0.25, 0, 1) * (1 - w_nose) * (1 - 0.6 * w_cheek)
    kill = (1 - lips) * eyes_clear * (1 - 0.8 * R["scalp"]) * (1 - 0.7 * R["ears"])
    w_nose, w_cheek, w_fore = w_nose * kill, w_cheek * kill, w_fore * kill
    pore_w = {"nose": w_nose, "cheek": w_cheek, "forehead": w_fore}
    pores = np.zeros(h.shape, np.float32)
    for name, (ch, scale, r, depth) in PORE_LAYERS.items():
        pores += pore_w[name] * pits(m.pores[..., ch], scale, r, texel, depth * c["pore_scale"])
    # T12: pores gather in clusters (~2 mm fBm), sparser between them, so the pore field reads as
    # a texture at portrait distance instead of an even grain (game pits and the hero pore mask)
    cluster = 1 - c["pore_cluster"] * (1 - smoothstep(0.38, 0.62, m.mid_f))
    pores *= cluster

    k = c["wrinkle_scale"]
    lines = np.zeros(h.shape, np.float32)
    shoulders = np.zeros(h.shape, np.float32)       # hero: rolled skin beside the lines

    def shoulder(d):
        """+1 on a ~1.5 mm band each side of a line (d = distance from it)."""
        return gauss(d - 0.0013, 0.0006)
    # forehead: two broken lines, slightly tilted (asymmetry), arched, wavy;
    # breaks on the centimetre scale (low-frequency noise), depth varies
    for i, (hh, amp) in enumerate(((0.050, c["forehead_mm"]), (0.063, 0.8 * c["forehead_mm"]))):
        wav = 0.0011 * np.sin(x * 120.0 + 1.7 * i) + 0.00025 * np.sin(x * 410.0 + 0.6 * i)
        b_ = h - (hh + 0.004 * (1 - (u / 0.05) ** 2) + 0.0025 * x / 0.05 + wav)
        brk = smoothstep(0.30, 0.48, m.mot_low if i == 0 else 1 - m.mot_low) * (0.55 + 0.45 * smoothstep(0.3, 0.6, m.broad))
        prof = 0.55 * groove(np.abs(b_), None, amp * MM * k, 0.0012, fade=None) \
            + 0.45 * groove(np.abs(b_), None, amp * MM * k, 0.0004, fade=None)
        lmask = smoothstep(0.050, 0.025, u) * R["forehead"] * brk
        lines -= prof * lmask
        shoulders += shoulder(np.abs(b_)) * lmask
    # glabellar frown furrows: soft, shallow and wide (no cut, no shoulders),
    # the left one a little deeper; they blend out at both ends
    d, tt = polyline(x, h, [(0.0045, 0.005), (0.0060, 0.015)])
    lines -= groove(d, tt, c["frown_mm"] * MM * k, c["frown_w"], shoulder=0.0)
    d, tt = polyline(x, h, [(-0.0045, 0.006), (-0.0055, 0.013)])
    lines -= groove(d, tt, 0.5 * c["frown_mm"] * MM * k, c["frown_w"], shoulder=0.0)
    # crow's feet: radiating back from the outer canthus on the temple plane
    lat = smoothstep(0.044, 0.052, u)
    for side, longer in ((1.0, 1.3), (0.0, 1.0)):
        sm = fr.left if side else 1 - fr.left
        for j, ang in enumerate((-30, -12, 6, 24)):
            a_ = math.radians(ang)
            L = 0.016 * longer * (1.0 if j in (1, 2) else 0.8)
            p0 = (0.010, -0.0015)
            p1 = (p0[0] - L * math.cos(a_), p0[1] + L * math.sin(a_) - 0.002)
            d, tt = polyline(fr.f, h, [p0, p1])
            lines -= groove(d, tt, c["crows_mm"] * MM * k, 0.0004, fade="end") * lat * sm
            shoulders += 0.6 * shoulder(d) * (1 - np.clip(tt, 0, 1)) ** 0.8 * lat * sm
    # under-eye lines (fine, the lid-cheek junction)
    # (no raised shoulders: under the hero key a shouldered groove here caught
    # a bright rim along the lid-cheek junction)
    for pts, amp in (([(0.017, -0.0095), (0.030, -0.0125), (0.046, -0.0085)], 0.04),
                     ([(0.021, -0.0155), (0.033, -0.0175), (0.044, -0.0145)], 0.03)):
        d, tt = polyline(u, h, pts)
        lines -= groove(d, tt, amp * MM * k, 0.0006, shoulder=0.0)
    # lid and under-eye crepe: fine, broken creases roughly concentric with the
    # eye (thin skin folds this way), warped by the mid noise and broken by the
    # horizontally stretched noise, so the under-eye sheen breaks up instead of
    # reading as one smooth wet patch
    ed = fr.eye_d + 0.0008 * (m.mot_mid - 0.5) * 2 + 0.0004 * (m.broad - 0.5) * 2 + 0.00015 * (m.grain - 0.5) * 2
    band = smoothstep(0.0168, 0.0182, fr.eye_d) * (1 - smoothstep(0.023, 0.029, fr.eye_d)) \
        * smoothstep(-0.006, 0.010, fr.f + 0.01) * (1 - lips)
    band = band * (smoothstep(0.004, -0.004, h) + 0.45 * smoothstep(-0.004, 0.004, h))
    ripple = 0.5 + 0.5 * np.cos(2 * np.pi * ed / c["crepe_period"])
    brk = smoothstep(0.46, 0.66, m.aniso_h) * (0.4 + 0.6 * smoothstep(0.35, 0.6, m.mot_low))
    crepe = smoothstep(0.55, 1.0, ripple) * brk * band
    lines -= crepe * c["crepe_mm"] * MM * k
    # nasolabial crease along the fold (the form carries the fold)
    d, tt = polyline(u, h, [(0.017, -0.036), (0.022, -0.048), (0.027, -0.060), (0.030, -0.072)])
    lines -= groove(d, tt, c["nasolabial_mm"] * MM * k, 0.0007) * (1 - 0.6 * smoothstep(0.5, 1.0, tt))
    shoulders += shoulder(d) * np.sin(np.pi * np.clip(tt, 0, 1)) ** 0.6
    # lip creases: vertical stretched noise on the vermilion
    # lip ridges: vertical furrows ~0.8 mm apart, wandering, with ~1.5 mm
    # lateral bumps between them
    per = c["lip_ridge_spacing_mm"] * MM / fr.s
    ridge = 0.5 + 0.5 * np.cos(2 * np.pi * x / per + 3.0 * (m.aniso_v - 0.5) * 2 * np.pi)
    lipin = smoothstep(0.3, 0.7, lips)
    crease = smoothstep(0.35, 0.0, ridge) * (0.55 + 0.9 * np.clip(m.lipbump - 0.3, 0, 0.5)) * lipin
    lines -= crease * c["lip_crease_mm"] * MM
    lines += (m.lipbump - 0.5) * 2 * c["lip_bump_mm"] * MM * lipin
    # neck rings
    for hh, amp in ((-0.140, 0.18), (-0.155, 0.14)):
        b_ = h - (hh + 0.004 * (u / 0.04) ** 2)
        lines -= groove(np.abs(b_), None, amp * MM * k, 0.0009, fade=None) * smoothstep(-0.12, -0.13, h) \
            * smoothstep(-0.03, 0.0, fr.f) * smoothstep(0.05, 0.03, u)
    # ---- T12 fine expression lines (portrait distance): many shallow, broken lines beside the
    # major ones. Forehead: thin lines at the zero crossings of a horizontally stretched noise,
    # broken by the low mottle; crow's feet: a fan of finer, shorter radiating lines; nasolabial:
    # two shallow lines lateral to the crease; under the eye the crepe (crepe_mm).
    fine = np.zeros(h.shape, np.float32)
    if c["forehead_fine_mm"] > 0:
        fl = 1 - smoothstep(0.0, c["fine_line_w"], np.abs(m.fine_h - 0.5))
        brk = smoothstep(0.38, 0.62, m.mot_low) * (0.5 + 0.5 * smoothstep(0.3, 0.7, m.mot_mid))
        fine -= c["forehead_fine_mm"] * MM * k * fl * brk * R["forehead"] * smoothstep(0.060, 0.030, u)
    if c["crows_fine_mm"] > 0:
        for side, longer in ((1.0, 1.3), (0.0, 1.0)):
            sm = fr.left if side else 1 - fr.left
            for j, ang in enumerate(np.linspace(-46.0, 38.0, 9)):
                a_ = math.radians(float(ang) + 3.0 * math.sin(2.3 * j + side))
                L = (0.009 + 0.004 * ((j * 7) % 3) / 2) * longer
                p0 = (0.0105 + 0.0006 * (j % 2), -0.0015 + 0.0004 * ((j * 5) % 3 - 1))
                p1 = (p0[0] - L * math.cos(a_), p0[1] + L * math.sin(a_) - 0.0015)
                d, tt = polyline(fr.f, h, [p0, p1])
                brk = 0.4 + 0.6 * smoothstep(0.4, 0.6, m.aniso_h if j % 2 else m.aniso_v)
                fine -= groove(d, tt, c["crows_fine_mm"] * MM * k, 0.00028, fade="end", shoulder=0.0) * lat * sm * brk
    if c["nasolabial_fine_mm"] > 0:
        for off, a_ in ((0.0035, 1.0), (0.0065, 0.6)):
            d, tt = polyline(u, h, [(0.017 + off, -0.040), (0.022 + off, -0.050), (0.026 + off, -0.061)])
            fine -= groove(d, tt, a_ * c["nasolabial_fine_mm"] * MM * k, 0.0004, shoulder=0.0) \
                * (0.5 + 0.5 * smoothstep(0.35, 0.65, m.mot_mid))
    fine *= (1 - lips) * eyes_clear
    lines += fine
    grain = (m.grain - 0.5) * c["grain_mm"] * MM * (1 - lips)
    # ---- mid band (skin-direction.md, Track A 2): what makes the skin read
    # at portrait distance. Lumps (6-15 mm), orange peel (2-4 mm cells along
    # x), rolled line shoulders, nose and alar bumps, and a soft under-eye
    # edge. Displaced in the hero, and in the game normal.
    skin = (1 - lips) * eyes_clear * (1 - 0.8 * R["scalp"])
    w_lump = np.clip(c["lump_cheek_mm"] * R["cheek"] + c["lump_forehead_mm"] * R["forehead"]
                     + c["lump_undereye_mm"] * R["under_eye"], 0, None)
    w_lump = np.maximum(w_lump, c["lump_face_mm"] * face)
    mid = (m.lump - 0.5) * 2.5 * w_lump * MM * skin
    w_peel = np.clip(R["cheek"] + R["nose"] + 0.8 * R["forehead"] + 0.8 * R["chin"] + 0.6 * face + 0.4 * R["neck"], 0, 1)
    mid += (smoothstep(0.0, 0.5, m.peel) - 0.6) * c["peel_mm"] * MM * w_peel * skin   # soft round domes
    mid += shoulders * c["shoulder_mm"] * MM * skin * k
    nb = np.clip(1 - m.nose_f1 / 0.45, 0, 1) ** 2
    mid += nb * c["nose_bump_mm"] * MM * np.clip(R["nose_tip"] + R["alar"] + 0.3 * R["nose"], 0, 1) * skin
    edge = gauss(h - c["undereye_edge_h"], 0.0025) * gauss(u - 0.029, 0.009) * smoothstep(-0.03, 0.0, fr.f)
    mid -= c["undereye_edge_mm"] * MM * edge * (1 - lips)
    # ---- T12 mid-frequency texture (0.5-3 mm, fable_review §4.2): a ~2 mm fBm and ~1.7 mm
    # plateaus (Voronoi edges as shallow furrows), strongest on the cheeks and nose, weaker on the
    # lids and under the beard; plus the sculpt layer's crisp band residual (skin_tex.crisp_texels)
    w_mid = np.clip(R["cheek"] + 0.9 * R["nose"] + 0.8 * R["forehead"] + 0.7 * R["chin"] + 0.5 * face
                    + 0.5 * R["temple"] + 0.4 * R["neck"], 0, 1) * skin \
        * (1 - 0.6 * np.clip(R["lid"] * 1.5, 0, 1)) * (1 - 0.6 * smoothstep(0.2, 0.6, R["beard"]))
    tex = (m.mid_f - 0.5) * 2
    cells = smoothstep(0.0, c["mid_cell_w"], m.mid_ff) - 1
    mid_tex = (c["mid_tex_mm"] * tex + c["mid_cell_mm"] * cells) * MM * w_mid
    mid += mid_tex
    # (not on the lids: the socket field's globe guard is steep there and the residual reads as a
    # groove under the lower lid)
    mid += c["crisp"] * m.crisp * smoothstep(0.0175, 0.0205, fr.eye_d)
    hgt_hero = (lines + grain + mid).astype(np.float32)    # pores come from the hero shader
    # the hero preview denoiser (OIDN at 64 spp) flattens the mid band: the hero displaces it harder
    hgt_hero_out = (hgt_hero + (c["hero_mid_gain"] - 1.0) * (mid_tex + fine)).astype(np.float32)
    hgt_game = (hgt_hero - pores).astype(np.float32)

    cav = m.cavity(hgt_game)
    pit = np.clip(cav * c["cavity_scale"], 0, 1)
    ao = np.clip(m.ao, 0, 1)
    occl = np.clip(ao * (1 - 0.5 * pit), 0, 1)

    # ---------------------------------------------------------------- albedo
    base = srgb_to_linear(HEX(c["base"]))
    alb = np.ones(m.P.shape, np.float32) * base
    mot = 1 + (m.mot_low - 0.5) * c["mottle_low"] + (m.mot_mid - 0.5) * c["mottle_mid"] + (m.grain - 0.5) * 0.03
    alb *= mot[..., None]
    alb[..., 0] *= 1 + (m.broad - 0.5) * 0.06                 # red drift
    alb[..., 2] *= 1 - (m.mot_low - 0.5) * 0.05

    def tint(w, rgb):
        nonlocal alb
        alb = alb * (1 + np.clip(w, 0, 1)[..., None] * (np.array(rgb, np.float32) - 1))
    z = c["zones"]
    tint(R["forehead"] * z, c["forehead_tint"])                   # yellower
    # flush: the nose tip and alar a deeper red, the apples a softer warm red
    # (two hues, so nose and cheek read apart)
    tint(np.clip(R["nose_tip"] + R["alar"] + 0.35 * R["nose"], 0, 1) * z, c["flush_nose"])
    tint(R["apple"] * 0.9 * z, c["flush_apple"])
    # smooth zone gradients: a broad cheek flush and a little warmth around the eyes
    tint(R["cheek"] * z * c["flush_cheek_w"], c["flush_apple"])
    tint(R["lid"] * z * 0.5, (1.04, 0.97, 0.97))
    tint(R["canthus"] * z * c["canthus"], c["canthus_rgb"])      # warmer, redder inner eye corners
    tint(R["ears"] * z, (1.12, 0.92, 0.90))                      # ears reddened by cold
    tint(R["beard"] * c["beard_shadow"], (0.80, 0.84, 0.91))     # cool, darker beard zone
    tint(R["under_eye"] * c["under_eye"], (0.88, 0.85, 0.91))    # violet-brown circles
    tint(R["socket"] * c["socket_dark"], (0.89, 0.86, 0.89))
    tint(R["lid"] * c["lid_dark"], (0.92, 0.88, 0.91))           # thin upper-lid skin, a little darker
    tint(R["orbit"] * c["orbit_dark"], c["orbit_rgb"])
    tint(R["roof"] * c["socket_dark"], (0.88, 0.85, 0.88))       # under the brow shelf
    tint(R["temple"] * 0.6, (0.97, 0.97, 1.0))
    tint(R["scalp"] * 0.7, (0.94, 0.93, 0.95))
    # hair v4: the scalp under the hair darker and cooler toward the interior
    # (follicles and the hair's occlusion), none at the region edge
    tint(smoothstep(c["scalp_dark_from"], 1.0, R["scalp"]) * c["scalp_dark"], c["scalp_dark_rgb"])
    tint(R["neck"] * 0.5, (0.98, 0.97, 0.97))
    # haemoglobin blotching (5-15 mm): acts on G and B only; strong on the
    # cheeks, nose, centre forehead and neck, faint elsewhere
    hb_w = np.clip(R["cheek"] + R["nose"] + R["apple"] + R["forehead"] * gauss(u, 0.025) + R["neck"], 0, 1)
    hb_w = c["hb_strong"] * hb_w + c["hb_weak"] * (1 - hb_w)
    # a soft threshold, zero mean over the skin (the face keeps its mean
    # colour); G and B absorb, R lifted by hb_r so a blotch reads as red, not dirt
    hbf = smoothstep(c["hb_thr"] - c["hb_soft"], c["hb_thr"] + c["hb_soft"], m.hb)
    sk = m.valid & (lips < 0.5) & (R["scalp"] < 0.5)
    hb = (hbf - (float(hbf[sk].mean()) if sk.any() else 0.5)) * hb_w * (1 - lips)
    alb *= 1 + hb[..., None] * np.array((c["hb_r"], -0.10 / 0.12, -1.0), np.float32)
    # fine-scale redness (3-7 mm, capillary scale): most of the hue variation
    # lives here, not in the broad blotches. Normalised to unit std over the
    # skin, then a nearly luminance-neutral red/green swing (R up, G and B
    # down), so it reads as uneven colour, not as dirt or a rash.
    def zscore(a):
        return (a - float(a[sk].mean())) / max(float(a[sk].std()), 1e-4) if sk.any() else a * 0
    # continuous and low-contrast: smooth gradient noise (3-7 mm), symmetric,
    # no threshold or one-sided curve, so it mottles and never forms flecks
    fine = np.clip(zscore(0.6 * m.hb_f1 + 0.4 * m.hb_f2), -2.5, 2.5)
    fw = np.clip(R["cheek"] + R["apple"] + R["nose"] + R["nose_tip"] + R["alar"] + R["ears"] + 0.6 * R["chin"]
                 + 0.5 * R["neck"], 0, 1)
    fw = (c["hb_fine_strong"] * fw + c["hb_fine_weak"] * (1 - fw)) * (1 - lips) \
        * (1 - np.clip(1.5 * R["under_eye"], 0, 1)) * (1 - R["beard"])   # under-eye less saturated; none in the beard
    alb *= 1 + (fine * fw)[..., None] * np.array(c["hb_fine_rgb"], np.float32)
    # ---- T17 haemoglobin and melanin layers at 1-20 mm (checkpoint-3 §2.2: Lab a* sigma in the
    # 8-30 px portrait band was 0.86, the bar >= 1.5). Smooth gradient noise only (no threshold, no
    # one-sided curve: v2 skin18 showed that flecks read as a rash), unit std over the skin, swung
    # along the haemoglobin absorption axis (R up a little, G and B down: redder and slightly darker,
    # hb_patch_rgb) and, apart, along melanin's (all down, blue most: browner, mel_patch_rgb). The
    # haemoglobin field is ~5-12 mm (the 150 / 90 / 120 per m noises), the melanin ~3-20 mm.
    # Off in the shipped config since T17 a7: at the strength the a* gate asked for, the 5-12 mm
    # patches read as a rash at 100 % (t17-skin.md); the colour now lives in the broad zones above.
    if c["hb_patch"] > 0 or c["mel_patch"] > 0:
        under = np.clip(1.5 * R["under_eye"] + R["orbit"], 0, 1)
        pw = np.clip(R["cheek"] + R["apple"] + R["nose"] + R["nose_tip"] + R["alar"] + 0.8 * R["chin"]
                     + c["hb_forehead"] * R["forehead"] + 0.6 * R["temple"] + 0.6 * R["neck"] + R["ears"], 0, 1)
        skin_w = (1 - lips) * (1 - 0.7 * under) * (1 - 0.8 * smoothstep(0.3, 0.8, R["beard"])) \
            * (1 - 0.8 * R["scalp"])
        if c["hb_patch"] > 0:
            zh = zscore(0.45 * m.hb_f1 + 0.30 * m.hb + 0.25 * m.lump)
            if c["hb_soft_mm"] > 0:
                # blotches, not speckle: the noise's ~2 mm octaves read as flecks (a rash, v2 skin18);
                # soften below hb_soft_mm, then back to unit std (the 5-12 mm patches keep their swing)
                zh = zscore(soft(zh, sk, c["hb_soft_mm"] * MM / max(float(np.median(m.tex_m[sk])), 1e-6)))
            zh = np.clip(zh, -2.5, 2.5)
            # the forehead reads less chroma through the view transform (brighter): its own boost
            wh = (c["hb_patch"] * pw + c["hb_patch_weak"] * (1 - pw)) * skin_w * (1 + c["hb_forehead_boost"] * R["forehead"])
            # one-sided in colour: above the mean along the absorption axis (redder), below it paler
            # (G and B up, R barely: blood-poor skin reads lighter and a little yellower, not green)
            up = (np.maximum(zh, 0) * wh)[..., None] * np.array(c["hb_patch_rgb"], np.float32)
            dn = (np.maximum(-zh, 0) * wh * c["hb_pale"])[..., None] * np.array(c["hb_pale_rgb"], np.float32)
            alb *= np.clip(1 + up + dn, 0.5, 1.5)
        if c["mel_patch"] > 0:
            zm = np.clip(zscore(0.5 * m.mot_low + 0.3 * m.mel + 0.2 * m.hb_f2), -2.5, 2.5)
            wm = c["mel_patch"] * (0.6 + 0.4 * pw) * skin_w
            alb *= np.clip(1 + (zm * wm)[..., None] * np.array(c["mel_patch_rgb"], np.float32), 0.5, 1.5)
    # melanin drift (20-50 mm): +-6 % value, darker patches a touch yellower
    mel = np.clip((m.mel - 0.5) * 2.5, -1, 1) * (1 - lips)
    alb *= (1 - c["melanin"] * mel)[..., None]
    tint(np.clip(mel, 0, 1), (1.02, 1.00, 0.95))
    # temple veins: faint blue wavy lines (~3 %)
    vein = smoothstep(0.06, 0.0, np.abs(m.aniso_h - 0.5)) * R["temple"] * smoothstep(0.4, 0.6, m.vein_var)
    tint(vein * c["veins"], (0.95, 0.97, 1.04))
    # broken capillaries on the alar and nose tip: a fine red network
    cap = smoothstep(0.035, 0.0, m.edge) * smoothstep(0.45, 0.65, m.mot_mid) * np.clip(R["alar"] * 1.5 + 0.5 * R["nose_tip"], 0, 1)
    tint(cap * c["capillaries"], (1.18, 0.82, 0.84))
    # stubble roots at the beard edge (under the shells the hair covers it)
    stub = smoothstep(0.80, 0.92, 1 - m.pores[..., 1]) * smoothstep(0.0, 0.25, R["beard"]) * (1 - lips)
    tint(stub * c["stubble"], (0.55, 0.52, 0.52))
    # lips: wind-dried, desaturated brick; vermilion border a touch lighter;
    # parting line dark, straighter at the corners (no pout)
    tint(lip_fill * c["beard_lip_dark"], c["beard_lip_rgb"])               # shadowed skin under the beard, at the lip
    lipc = srgb_to_linear(HEX(c["lip"]))
    lw = lip_weight(m, lips, c["lip_soft_mm"] * MM) * c["lip_mix"]
    alb = alb * (1 - lw[..., None]) + lipc * lw[..., None]
    tint(crease, (0.90, 0.88, 0.88))                                     # dry creases darker
    border = gauss(lips - 0.25, 0.12) * (1 - lw) * smoothstep(-0.075, -0.068, h)
    tint(border * c["lip_border"], (1.04, 1.03, 1.02))
    # expression lines in the colour too (forehead, frown, crow's feet,
    # nasolabial): under even light the relief alone vanishes and the forehead
    # reads as a blank slab; the groove floor is a touch darker and warmer
    if c["line_albedo"] > 0:
        groove_d = np.clip(-lines / (c["line_albedo_ref_mm"] * MM), 0, 1) * (1 - lips) * eyes_clear
        tint(groove_d * c["line_albedo"], (0.80, 0.74, 0.72))
    # freckles and small blemishes: faint, sparse (no single eye-catching mark)
    frk = smoothstep(c["freckle_thr"], c["freckle_thr"] + 0.03, m.speck) * (0.5 * R["forehead"] + R["cheek"] + 0.8 * R["nose"] + 0.3 * R["temple"])
    tint(frk * c["freckles"], (0.88, 0.80, 0.76))
    blem = smoothstep(0.76, 0.80, m.vein_var) * smoothstep(0.7, 0.8, m.speck) * (R["cheek"] + 0.5 * R["forehead"] + 0.6 * R["chin"])
    tint(blem * c["blemish"], (1.06, 0.88, 0.86))
    # pores and creases darken slightly
    alb *= (1 - c["cavity_albedo"] * pit)[..., None]          # pores and lines are relief, not colour
    # plane paint (look-spec §0, capped at 0.06 by direction §4) and AO
    L = np.array([0.0, -0.45, 1.0], np.float32)
    L /= np.linalg.norm(L)
    facing = np.clip((m.N * L).sum(-1), -1, 1)
    plane = (1 + c["plane_paint"] * facing)[..., None]          # game only; hero plane_paint 0
    # mouth corners: the baked occlusion pools in the commissures and, with the
    # corners set low, reads as a pout from the front; lift it there (and a
    # touch of value), so the mouth reads as a firm line, not a frown
    corner = np.zeros(h.shape, np.float32)
    for q in c.get("corners") or ():
        corner = np.maximum(corner, gauss(np.linalg.norm(m.P - np.asarray(q, np.float32), axis=-1) / fr.s, c["corner_r"]))
    ao_c = ao + (1 - ao) * c["corner_ao_lift"] * corner
    alb *= (1 - c["ao_in_albedo"] * (1 - ao_c))[..., None]
    tint(corner * c["corner_lift"], (1.06, 1.05, 1.05))
    # lip seam: a darker line where the lips meet, so a closed mouth reads as
    # closed (not a pale open oval); softer into the corners (no frown)
    if c["lip_seam"] > 0:
        seam = lip_seam(m, lips, ao, c["lip_seam_mm"] * MM) * smoothstep(0.25, 0.85, lips) * (1 - 0.6 * corner)
        tint(seam * c["lip_seam"], (0.62, 0.58, 0.60))
    alb_hero = np.clip(alb * (1 + c["hero_plane_paint"] * facing)[..., None], 0, 1)
    alb = np.clip(alb * plane, 0, 1)

    # ------------------------------------------------------------- roughness
    rough = np.full(h.shape, c["rough"], np.float32)
    rough += (c["rough_tzone"] - c["rough"]) * R["tzone"]
    rough += (c["rough_beard"] - c["rough"]) * R["beard"]
    rough += (c["rough_ears"] - c["rough"]) * R["ears"]
    rough += 0.10 * R["under_eye"] + 0.02 * R["neck"]          # thin, dry under-eye skin
    rough += 0.08 * crepe                                       # crepe folds scatter the sheen
    rough += c["rough_orbit"] * R["orbit"]                      # T12: dry, matte lid skin (no lid glint)
    rough += (m.mot_mid - 0.5) * 0.06 + pit * 0.10
    # T12: sheen structure (skin-direction.md: "one continuous sheen" is the top CG tell): oil and
    # dryness in ~8 mm patches and the ~2 mm texture (its hollows rougher, its domes glossier),
    # fine lines rougher; zero mean, so the regional means stay
    struct = c["rough_patch"] * np.clip((m.lump - 0.5) * 3.0, -1, 1) * (1 - lips) - c["rough_mid"] * tex * w_mid \
        + c["rough_line"] * np.clip(-fine / (0.04 * MM), 0, 1)
    skin_px = m.valid & (lips < 0.5) & (R["scalp"] < 0.5)
    rough += struct - (float(struct[skin_px].mean()) if skin_px.any() else 0.0)
    # oiliness varies smoothly (the T-zone a little shinier, rough_tzone); any
    # highlight breakup comes from the pores and micro relief, not from a mask
    # T17: roughness structure 12 -> ~22 % of the face mean, correlated with the pores: denser pore
    # clusters (the pore weights x the ~2 mm cluster field) rougher, the plateaus between them glossier,
    # the pits themselves rougher (rough_pore), and larger oil / dry patches (rough_patch2, ~3-8 mm).
    # Zero mean over the skin again, so the regional means stay.
    pore_dens = (w_nose + 0.85 * w_cheek + 0.6 * w_fore) * cluster
    pore_d = np.clip(pores / (0.04 * MM), 0, 1)      # pits() is positive into the skin
    struct2 = c["rough_density"] * np.clip(zscore(pore_dens), -2.5, 2.5) * smoothstep(0.05, 0.3, pore_dens + 0.5 * face) \
        + c["rough_pore"] * pore_d \
        + c["rough_patch2"] * np.clip(zscore(0.6 * m.hb_f2 + 0.4 * m.mot_mid), -2.5, 2.5) * (1 - lips)
    struct2 *= (1 - lips) * (1 - 0.5 * np.clip(R["lid"] * 1.5, 0, 1))
    rough += struct2 - (float(struct2[skin_px].mean()) if skin_px.any() else 0.0)
    lip_r = c["rough_lips"] + 0.12 * smoothstep(0.55, 0.72, m.aniso_v)
    # T17 lip wetness (both renderers): glossier toward where the lips meet (a ~lip_wet_mm band from
    # the seam), the dry vertical creases stay rough
    if c["lip_wet"] > 0:
        wet = lip_seam(m, lips, ao, c["lip_wet_mm"] * MM) * (1 - 0.7 * smoothstep(0.2, 0.8, crease))
        lip_r = lip_r - c["lip_wet"] * (lip_r - c["lip_wet_rough"]) * wet
    rough = rough * (1 - lw) + lip_r * lw
    # no wet band on the skin: the lid and under-eye skin lie within a
    # millimetre of the eyeball radius over several millimetres, so any radial
    # band spread gloss onto them (a wet crescent under the eye); the tear line
    # against the eyeball is the hero meniscus (eyes_hq), the skin stays matte
    rough = np.clip(rough, 0.05, 1.0)

    # ------------------------------------------------------ hero detail masks
    # hero micro-detail masks: strong on the nose, cheeks and forehead, weak on
    # the lids and lips, off under the beard
    no_beard = 1 - 0.85 * smoothstep(0.2, 0.6, R["beard"])
    mask_pores = (np.stack([w_nose, w_cheek, w_fore], -1) * (no_beard * cluster)[..., None]).astype(np.float32)
    oil = np.clip(R["tzone"] * 1.0 + 0.3 * R["cheek"], 0, 1) * (1 - lips) * (1 - np.clip(R["under_eye"] * 1.5, 0, 1))
    oil = oil * (0.8 + 0.4 * m.mot_low)                       # ~2 cm, smooth: no edges inside a highlight
    oil = np.maximum(oil, c["lip_wet_coat"] * lw)             # T17: the hero coat on the (wet) lips
    fuzz = np.clip(R["cheek"] + 0.7 * R["ears"] + 0.5 * R["forehead"] + 0.4 * R["neck"], 0, 1) * (1 - R["beard"]) * (1 - lips)
    lid_clear = smoothstep(0.0168, 0.0178, fr.eye_d)          # micro relief up to the lid margin
    micro = np.clip(0.6 + 0.4 * R["cheek"] - 0.3 * R["nose"] - 0.5 * R["scalp"], 0, 1) * (1 - lips) * lid_clear \
        * no_beard * (1 - 0.5 * np.clip(R["lid"] * 1.5, 0, 1))
    mask_hero = np.stack([oil, fuzz, micro], -1).astype(np.float32)
    return {"albedo": alb, "albedo_hero": alb_hero, "rough": rough, "hgt_game": hgt_game, "hgt_hero": hgt_hero_out,
            "occl": occl, "mask_pores": mask_pores, "mask_hero": mask_hero}


def synth_hands(m, c, hf, fingers):
    """Albedo, roughness, heights, occlusion for the hands map."""
    P, N = m.P, m.N
    nails = np.clip(m.nails, 0, 1)
    back = np.zeros(P.shape[:2], np.float32)
    knuckle = np.zeros_like(back)
    hgt = np.zeros_like(back)
    for side, f in hf.items():
        near = np.linalg.norm(P - f["wrist"], axis=-1) < 0.25
        b = np.clip((N * f["back"]).sum(-1), -1, 1) * near
        back = np.maximum(back, b) if side != "l" else np.where(b > back, b, back)
        wb = np.clip(b, 0, 1) ** 1.3
        wp = np.clip(-b, 0, 1) ** 1.3
        for name in fingers:
            for joint, r, n_lines in ((f["mcp"][name], 0.009, 3), (f["pip"][name], 0.0065, 3), (f["dip"][name], 0.005, 2)):
                along = (P - joint) @ f["fingers"]
                across = np.linalg.norm(P - joint - along[..., None] * f["fingers"], axis=-1)
                inr = gauss(across, r)
                knuckle += inr * wb * gauss(along, 0.006)
                for i in range(n_lines):
                    off = (i - (n_lines - 1) / 2) * 0.0017
                    hgt -= c["knuckle_crease_mm"] * MM * gauss(along - off, 0.0005) * inr * wb
                for off in (-0.001, 0.001):
                    hgt -= c["palm_crease_mm"] * MM * 0.6 * gauss(along - off - 0.002, 0.0006) * inr * wp
        wrist, fd, ad = f["wrist"], f["fingers"], f["across"]

        def pl(pts, amp, w, wrist=wrist, fd=fd, ad=ad, wp=wp):
            nonlocal hgt
            a = (P - wrist) @ fd
            bb = (P - wrist) @ ad
            d, _ = polyline(a, bb, pts)
            hgt -= amp * MM * (gauss(d, w) - 0.3 * gauss(d, 2.2 * w)) * wp
        pl([(0.045, -0.035), (0.062, 0.0), (0.072, 0.03)], c["palm_line_mm"], 0.0012)
        pl([(0.030, -0.035), (0.042, 0.0), (0.050, 0.025)], c["palm_line_mm"] * 0.9, 0.0012)
        pl([(0.075, -0.030), (0.040, -0.028), (0.012, -0.010)], c["palm_line_mm"], 0.0013)
    knuckle = np.clip(knuckle, 0, 1)
    backw = np.clip(back, 0, 1)
    pores = pits(m.pores[..., 1], PORE_LAYERS["cheek"][1], 0.07, m.tex_m, c["pore_mm"]) * (0.4 + 0.6 * backw) * (1 - nails)
    hgt += (m.grain - 0.5) * c["grain_mm"] * MM
    hgt -= smoothstep(0.55, 0.72, m.aniso_h) * knuckle * 0.06 * MM
    nail_edge = gauss(nails - 0.35, 0.12)
    hgt -= nail_edge * c["cuticle_mm"] * MM
    hgt += (m.aniso_v - 0.5) * 0.02 * MM * nails
    hgt_hero = hgt.astype(np.float32)
    hgt_game = (hgt - pores).astype(np.float32)
    cav = m.cavity(hgt_game)
    pit = np.clip(cav * c["cavity_scale"], 0, 1)
    ao = np.clip(m.ao, 0, 1)
    occl = np.clip(ao * (1 - 0.5 * pit), 0, 1)

    base = srgb_to_linear(HEX(c["base"]))
    alb = np.ones(P.shape, np.float32) * base
    mot = 1 + (m.mot_low - 0.5) * c["mottle_low"] + (m.mot_mid - 0.5) * c["mottle_mid"] + (m.grain - 0.5) * 0.04
    alb *= mot[..., None]
    palm = np.clip(-back, 0, 1)
    alb *= (1 + palm[..., None] * (np.array((1.07, 1.0, 0.97), np.float32) - 1))
    alb *= (1 + (knuckle * 0.9)[..., None] * (np.array((1.10, 0.92, 0.90), np.float32) - 1))
    vein = smoothstep(0.05, 0.0, np.abs(m.aniso_v - 0.5)) * backw * smoothstep(0.45, 0.6, m.vein_var)
    alb *= (1 + (vein * 0.06)[..., None] * (np.array((0.95, 0.98, 1.05), np.float32) - 1))
    spk = smoothstep(c["freckle_thr"], c["freckle_thr"] + 0.03, m.speck) * backw
    alb *= (1 + (spk * c["freckles"])[..., None] * (np.array((0.86, 0.78, 0.74), np.float32) - 1))
    nailc = srgb_to_linear(HEX(c["nail"]))
    nw = smoothstep(0.3, 0.8, nails)
    alb = alb * (1 - nw[..., None]) + nailc * nw[..., None]
    alb *= (1 - c["cavity_albedo"] * pit)[..., None]
    L = np.array([0.0, -0.45, 1.0], np.float32)
    L /= np.linalg.norm(L)
    alb *= (1 + c["plane_paint"] * np.clip((N * L).sum(-1), -1, 1))[..., None]
    alb *= (1 - c["ao_in_albedo"] * (1 - ao))[..., None]
    alb = np.clip(alb, 0, 1)
    rough = np.full(P.shape[:2], c["rough"], np.float32)
    rough += 0.06 * knuckle - 0.05 * palm + (m.mot_mid - 0.5) * 0.06 + pit * 0.10
    rough = rough * (1 - nw) + 0.3 * nw
    rough = np.clip(rough, 0.05, 1.0)
    w = np.clip(0.5 + 0.5 * backw, 0, 1) * (1 - nails)
    mask_pores = np.stack([np.zeros_like(w), w, np.zeros_like(w)], -1).astype(np.float32)
    mask_hero = np.stack([0.2 * palm, 0.3 * backw, w], -1).astype(np.float32)
    return {"albedo": alb, "rough": rough, "hgt_game": hgt_game, "hgt_hero": hgt_hero, "occl": occl,
            "mask_pores": mask_pores, "mask_hero": mask_hero}


DEFAULT_HEAD = {
    "base": "#b8927b",          # sRGB; the zones move the mean to ~(0.70, 0.55, 0.46)
    "lip": "#8e5f56", "lip_mix": 0.8,
    "lip_seam": 0.0, "lip_seam_mm": 0.7,     # darker line where the lips meet (amount, width); 0 = off
    "lip_soft_mm": 0.0,                      # vermilion border softness (3D, +-mm); 0 = the group falloff
    "lip_border": 0.6,                       # lighter skin rim just outside the vermilion
    "beard_to_lip_mm": 0.0,                  # beard zone fills skin gaps to the vermilion narrower than this; 0 = off
    "beard_lip_dark": 0.0,                   # extra shadow on that filled strip (amount) ...
    "beard_lip_rgb": (0.62, 0.58, 0.58),     # ... and its full-strength multiplier (linear)
    "corner_r": 0.004, "corner_ao_lift": 0.6, "corner_lift": 1.0,
    "zones": 1.0, "beard_shadow": 1.0, "under_eye": 1.0, "socket_dark": 1.0, "lid_dark": 1.0,
    "orbit_dark": 0.0, "orbit_rgb": (0.86, 0.80, 0.84),      # T12 periorbital ring (both lids), 0 = off
    "canthus": 0.0, "canthus_rgb": (1.10, 0.93, 0.94),       # T17 inner eye corners, 0 = off
    "rough_orbit": 0.0,
    "scalp_dark": 1.0, "scalp_dark_from": 0.6, "scalp_dark_rgb": (0.78, 0.77, 0.82),  # 0 = off (v3)
    "veins": 0.6, "capillaries": 0.6, "stubble": 0.5,
    "freckle_thr": 0.80, "freckles": 0.22, "blemish": 0.5,
    "mottle_low": 0.10, "mottle_mid": 0.06,
    "pore_scale": 1.0, "grain_mm": 0.006,
    "wrinkle_scale": 1.0, "forehead_mm": 0.30, "frown_mm": 0.10, "frown_w": 0.0016, "crows_mm": 0.15, "nasolabial_mm": 0.25,
    "lip_crease_mm": 0.12, "lip_ridge_spacing_mm": 0.8, "lip_bump_mm": 0.03,
    # mid band (skin-direction.md Track A 2, 4)
    "lump_cheek_mm": 0.25, "lump_forehead_mm": 0.22, "lump_undereye_mm": 0.15, "lump_face_mm": 0.10,
    "peel_mm": 0.05, "shoulder_mm": 0.08, "nose_bump_mm": 0.06,
    "undereye_edge_mm": 0.0, "undereye_edge_h": -0.0175,
    # chromatic albedo (skin-direction.md Track A 1)
    "hb_strong": 0.18, "hb_weak": 0.045, "hb_thr": 0.55, "hb_soft": 0.20, "hb_r": 0.7,
    "hb_fine_strong": 0.020, "hb_fine_weak": 0.010, "flush_cheek_w": 0.6, "hb_fine_rgb": (1.6, -1.0, -1.1),
    "melanin": 0.06, "hero_plane_paint": 0.0,
    "flush_nose": (1.20, 0.89, 0.92), "flush_apple": (1.06, 0.95, 0.92),
    "forehead_tint": (1.03, 1.02, 0.91),
    "crepe_mm": 0.03, "crepe_period": 0.0008,
    "cavity_scale": 0.0006, "cavity_albedo": 0.03,
    "line_albedo": 0.0, "line_albedo_ref_mm": 0.3,   # expression lines darken the albedo (amount at ref depth); 0 = off
    "plane_paint": 0.06, "ao_in_albedo": 0.10,
    # T12 mid band (0.5-3 mm) and sheen structure (0 turns each off)
    "crisp": 1.0,                               # sculpt crisp band residual (skin_tex.crisp_texels), x
    "pore_cluster": 0.5,                        # pore depth between the ~2 mm clusters, 1 - x
    "mid_tex_mm": 0.06, "mid_cell_mm": 0.015, "mid_cell_w": 0.12,
    "forehead_fine_mm": 0.08, "fine_line_w": 0.05, "crows_fine_mm": 0.08, "nasolabial_fine_mm": 0.05,
    "rough_patch": 0.05, "rough_mid": 0.04, "rough_line": 0.05,
    "hero_mid_gain": 1.5,                      # hero displacement of the mid band and fine lines, x
    "rough": 0.47, "rough_tzone": 0.37, "rough_beard": 0.58, "rough_ears": 0.48, "rough_lips": 0.45,
    # T17 (checkpoint-3 §2.2): haemoglobin / melanin layers (amount at the strong regions, weak elsewhere;
    # the RGB swing per unit std), roughness structure, lip wetness, the specular cavity (ORM blue)
    "hb_patch": 0.0, "hb_patch_weak": 0.0, "hb_patch_rgb": (0.25, -0.45, -0.40),
    "hb_pale": 1.0, "hb_pale_rgb": (-0.25, 0.45, 0.40), "hb_soft_mm": 0.0, "hb_forehead": 0.7, "hb_forehead_boost": 0.0,
    "mel_patch": 0.0, "mel_patch_rgb": (-0.45, -0.60, -0.95),
    "rough_density": 0.0, "rough_pore": 0.0, "rough_patch2": 0.0,
    "lip_wet": 0.0, "lip_wet_mm": 1.6, "lip_wet_rough": 0.22, "lip_wet_coat": 0.0,
    "cavity_fine": 0.0003, "cavity_broad": 0.0015,
}

DEFAULT_HANDS = {
    "base": "#b48f79", "nail": "#c2a096",
    "mottle_low": 0.10, "mottle_mid": 0.06,
    "freckle_thr": 0.74, "freckles": 0.4,
    "pore_mm": 0.035, "grain_mm": 0.006,
    "knuckle_crease_mm": 0.45, "palm_crease_mm": 0.4, "palm_line_mm": 0.5, "cuticle_mm": 0.15,
    "cavity_scale": 0.0006, "cavity_albedo": 0.05,
    "plane_paint": 0.05, "ao_in_albedo": 0.22,
    "rough": 0.52,
}
