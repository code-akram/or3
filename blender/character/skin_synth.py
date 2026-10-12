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
             forehead lines, a glabellar frown line on the left only, crow's
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

    def __init__(self, m, cl, cr):
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
    r["tzone"] = np.clip(r["forehead"] * gauss(u, 0.028) + r["nose"] + 0.6 * r["chin"], 0, 1)
    return r


def synth_head(m, c, cl, cr):
    fr = Frame(m, cl, cr)
    R = regions(fr, m)
    u, h, x = fr.u, fr.h, fr.x
    lips = R["lips"]
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

    k = c["wrinkle_scale"]
    lines = np.zeros(h.shape, np.float32)
    # forehead: two broken lines, slightly tilted (asymmetry), arched, wavy;
    # breaks on the centimetre scale (low-frequency noise), depth varies
    for i, (hh, amp) in enumerate(((0.050, c["forehead_mm"]), (0.063, 0.8 * c["forehead_mm"]))):
        wav = 0.0011 * np.sin(x * 120.0 + 1.7 * i) + 0.00025 * np.sin(x * 410.0 + 0.6 * i)
        b_ = h - (hh + 0.004 * (1 - (u / 0.05) ** 2) + 0.0025 * x / 0.05 + wav)
        brk = smoothstep(0.30, 0.48, m.mot_low if i == 0 else 1 - m.mot_low) * (0.55 + 0.45 * smoothstep(0.3, 0.6, m.broad))
        prof = 0.55 * groove(np.abs(b_), None, amp * MM * k, 0.0012, fade=None) \
            + 0.45 * groove(np.abs(b_), None, amp * MM * k, 0.0004, fade=None)
        lines -= prof * smoothstep(0.050, 0.025, u) * R["forehead"] * brk
    # glabellar frown line: left only (character's left, +x)
    d, tt = polyline(x, h, [(0.0045, 0.006), (0.0060, 0.014)])
    lines -= groove(d, tt, c["frown_mm"] * MM * k, 0.0005)
    d, tt = polyline(x, h, [(-0.0045, 0.007), (-0.0055, 0.012)])
    lines -= groove(d, tt, 0.25 * c["frown_mm"] * MM * k, 0.0005)
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
    # lip creases: vertical stretched noise on the vermilion
    crease = smoothstep(0.58, 0.68, m.aniso_v) * smoothstep(0.3, 0.7, lips)
    lines -= crease * c["lip_crease_mm"] * MM
    # neck rings
    for hh, amp in ((-0.140, 0.18), (-0.155, 0.14)):
        b_ = h - (hh + 0.004 * (u / 0.04) ** 2)
        lines -= groove(np.abs(b_), None, amp * MM * k, 0.0009, fade=None) * smoothstep(-0.12, -0.13, h) \
            * smoothstep(-0.03, 0.0, fr.f) * smoothstep(0.05, 0.03, u)
    grain = (m.grain - 0.5) * c["grain_mm"] * MM * (1 - lips)
    hgt_hero = (lines + grain).astype(np.float32)          # pores come from the hero shader
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
    tint(R["forehead"] * z, (1.03, 1.02, 0.94))                  # yellower
    red = np.clip(R["nose_tip"] + R["alar"] + R["apple"] * 0.9 + 0.35 * R["nose"], 0, 1)
    tint(red * z, (1.10, 0.93, 0.91))                            # flush: nose, alar, apples
    tint(R["ears"] * z, (1.12, 0.92, 0.90))                      # ears reddened by cold
    tint(R["beard"] * c["beard_shadow"], (0.80, 0.84, 0.91))     # cool, darker beard zone
    tint(R["under_eye"] * c["under_eye"], (0.88, 0.85, 0.91))    # violet-brown circles
    tint(R["socket"] * c["socket_dark"], (0.89, 0.86, 0.89))
    tint(R["lid"] * c["lid_dark"], (0.92, 0.88, 0.91))           # thin upper-lid skin, a little darker
    tint(R["roof"] * c["socket_dark"], (0.88, 0.85, 0.88))       # under the brow shelf
    tint(R["temple"] * 0.6, (0.97, 0.97, 1.0))
    tint(R["scalp"] * 0.7, (0.94, 0.93, 0.95))
    tint(R["neck"] * 0.5, (0.98, 0.97, 0.97))
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
    lipc = srgb_to_linear(HEX(c["lip"]))
    lw = smoothstep(0.25, 0.85, lips) * c["lip_mix"]
    alb = alb * (1 - lw[..., None]) + lipc * lw[..., None]
    tint(crease, (0.90, 0.88, 0.88))                                     # dry creases darker
    border = gauss(lips - 0.25, 0.12) * (1 - lw) * smoothstep(-0.075, -0.068, h)
    tint(border * 0.6, (1.04, 1.03, 1.02))
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
    alb *= (1 + c["plane_paint"] * facing)[..., None]
    # mouth corners: the baked occlusion pools in the commissures and, with the
    # corners set low, reads as a pout from the front; lift it there (and a
    # touch of value), so the mouth reads as a firm line, not a frown
    corner = np.zeros(h.shape, np.float32)
    for q in c.get("corners") or ():
        corner = np.maximum(corner, gauss(np.linalg.norm(m.P - np.asarray(q, np.float32), axis=-1) / fr.s, c["corner_r"]))
    ao_c = ao + (1 - ao) * c["corner_ao_lift"] * corner
    alb *= (1 - c["ao_in_albedo"] * (1 - ao_c))[..., None]
    tint(corner * c["corner_lift"], (1.06, 1.05, 1.05))
    alb = np.clip(alb, 0, 1)

    # ------------------------------------------------------------- roughness
    rough = np.full(h.shape, c["rough"], np.float32)
    rough += (c["rough_tzone"] - c["rough"]) * R["tzone"]
    rough += (c["rough_beard"] - c["rough"]) * R["beard"]
    rough += (c["rough_ears"] - c["rough"]) * R["ears"]
    rough += 0.10 * R["under_eye"] + 0.02 * R["neck"]          # thin, dry under-eye skin
    rough += 0.08 * crepe                                       # crepe folds scatter the sheen
    rough += (m.mot_mid - 0.5) * 0.06 + pit * 0.10
    lip_r = c["rough_lips"] + 0.12 * smoothstep(0.55, 0.72, m.aniso_v)
    rough = rough * (1 - lw) + lip_r * lw
    # wet lid margin: the rim that touches the eye only, not the lid's front skin
    lid = gauss(fr.eye_d - c["lid_margin_r"], 0.0004) * (1 - smoothstep(0.0164, 0.0170, fr.eye_d))
    rough = rough * (1 - lid) + c["rough_lid"] * lid
    rough = np.clip(rough, 0.05, 1.0)

    # ------------------------------------------------------ hero detail masks
    mask_pores = np.stack([w_nose, w_cheek, w_fore], -1).astype(np.float32)
    oil = np.clip(R["tzone"] * 1.0 + 0.3 * R["cheek"], 0, 1) * (1 - lips) * (1 - np.clip(R["under_eye"] * 1.5, 0, 1))
    fuzz = np.clip(R["cheek"] + 0.7 * R["ears"] + 0.5 * R["forehead"] + 0.4 * R["neck"], 0, 1) * (1 - R["beard"]) * (1 - lips)
    lid_clear = smoothstep(0.0168, 0.0178, fr.eye_d)          # micro relief up to the lid margin
    micro = np.clip(0.6 + 0.4 * R["cheek"] - 0.3 * R["nose"] - 0.5 * R["scalp"], 0, 1) * (1 - lips) * lid_clear
    mask_hero = np.stack([oil, fuzz, micro], -1).astype(np.float32)
    return {"albedo": alb, "rough": rough, "hgt_game": hgt_game, "hgt_hero": hgt_hero, "occl": occl,
            "mask_pores": mask_pores, "mask_hero": mask_hero}


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
    "corner_r": 0.004, "corner_ao_lift": 0.6, "corner_lift": 1.0,
    "zones": 1.0, "beard_shadow": 1.0, "under_eye": 1.0, "socket_dark": 1.0, "lid_dark": 1.0,
    "veins": 0.6, "capillaries": 0.6, "stubble": 0.5,
    "freckle_thr": 0.80, "freckles": 0.22, "blemish": 0.5,
    "mottle_low": 0.10, "mottle_mid": 0.06,
    "pore_scale": 1.0, "grain_mm": 0.006,
    "wrinkle_scale": 1.0, "forehead_mm": 0.30, "frown_mm": 0.30, "crows_mm": 0.15, "nasolabial_mm": 0.25, "lip_crease_mm": 0.08,
    "crepe_mm": 0.02, "crepe_period": 0.0008,
    "cavity_scale": 0.0006, "cavity_albedo": 0.03,
    "plane_paint": 0.06, "ao_in_albedo": 0.22,
    "rough": 0.47, "rough_tzone": 0.40, "rough_beard": 0.58, "rough_ears": 0.48, "rough_lips": 0.45,
    "lid_margin_r": 0.0162, "rough_lid": 0.2,
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
