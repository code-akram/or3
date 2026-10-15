"""The waistcoat's draft (m1 v4 T13 phase B item 4): a three-piece suit's single-breasted
waistcoat, cut from the jacket's block (suit_pattern.draft with waistcoat ease, a lower
armhole, a shorter unpadded shoulder and a closer neck), so it is placed and sewn by the
jacket's runner (Placer, build_cloth, drape_xpbd).

  front   wool. The jacket block's front and side body as one panel (no side-front
          suppression, so the two meet on one line), a fisheye dart from the lower pocket to
          below the chest, the V opening from the neck point to the top button, five buttons on
          an extension past the centre front, the front edge cut away below the last button
          to a point, the hem rising from the point to the side seam
  back    lining (as on a real waistcoat), the block's back with a CB seam, cut level at the
          side seam's hem height

Notches on the front: the buttons (centre front), the buttonholes (left front), the lower
welt pockets and the breast welt. Units: cm on the pattern, block y down from the nape.
"""

import math

import numpy as np

from . import suit_pattern as sp

DEFAULTS = {
    # the jacket block (suit_pattern.draft options): close over the shirt, the armhole 7 cm
    # under the armpit (a jacket's 2.5; at 5 the made shirt's underarm caught its lower edge,
    # ragged in the frames: t13w-b2), the shoulder ending 2.5 cm inside the acromion
    # (no pad), the neck point 1.8 cm out (under the jacket's collar, over the shirt's)
    "block": {"ease": {"chest": 6.0, "waist": 5.0, "seat": 6.0}, "waist_min_frac": 0.75,
              "scye_below_armpit_cm": 7.0, "scye_rise_cm": 6.0,
              "shoulder_out_cm": -2.5, "pad_cm": 0.0, "shoulder_drop_deg": 0.0,
              "np_out_cm": 1.8, "neck_scale": 1.0, "back_neck_rise_cm": 0.0,
              "length_frac": 0.40, "hem_flare_cm": 0.0, "split_lapel": True,
              "suppression": {"cb": 0.28, "back_side": 0.50, "side_front": 0.0, "front_dart": 0.22},
              "front_dart": {"x_frac": 0.45, "top_below_chest_cm": 3.0}},
    "dart_below_side_hem_cm": 1.0,   # the dart runs through the welt to just above the hem
    "cover_band_cm": 3.0,          # side and back hem this far below the trousers' band top
    # the draft's hem is cut this much lower than the block's straight drop: the sewn waistcoat
    # hangs 2.3-2.5 cm higher than that (its seams run round the body, not straight down;
    # runs t13w-a3..a5, the hem at 1.153-1.160 m against 1.129 drafted)
    "hang_comp_cm": 2.5,
    # the back neck scooped this much at the CB (a waistcoat's back neck sits under the shirt
    # collar; level with the neck point, the CB rode 4.6 cm up the collar: run t13w-a7)
    "back_neck_drop_cm": 3.0,
    "point_drop_cm": 6.0,          # the points this far below the side hem
    "point_in_cm": 4.5,            # each point this far inside the button edge (the inverted V)
    "top_button_above_jacket_cm": 17.0,   # the V's bottom (the jacket's button: 2 cm below the waist)
    "buttons": 5,
    "bottom_button_above_point_cm": 6.5,
    "button_ext_cm": 1.5,          # button edge past the centre front
    "cut_below_button_cm": 1.5,    # the front edge leaves the extension this far below the last button
    "v_belly_cm": 0.4,             # the V's edge bows out this much
    "welt": {"w_cm": 11.0, "h_cm": 1.2, "above_hem_cm": 5.5, "slant_cm": 1.0, "x_frac": 0.5},
    "breast_welt": {"w_cm": 8.5, "h_cm": 1.0, "below_chest_cm": 3.0, "slant_cm": 0.8, "x_frac": 0.45},
    "buttonhole_cm": 1.6,
    "seam_allowance_cm": 1.0,
}


def _cut_y(P, yc):
    """The part of polyline P with y <= yc (above the line; block y runs down), cut exactly."""
    P = np.asarray(P, float)
    out = []
    for i in range(len(P)):
        a = P[i]
        if a[1] <= yc:
            out.append(a)
        if i + 1 < len(P):
            b = P[i + 1]
            if (a[1] - yc) * (b[1] - yc) < 0:
                t = (yc - a[1]) / (b[1] - a[1])
                out.append(a + t * (b - a))
    return np.array(out)


def _x_at_y(P, y):
    P = np.asarray(P, float)
    o = np.argsort(P[:, 1])
    return float(np.interp(y, P[o, 1], P[o, 0]))


def draft(M, band_top_z, opts=None):
    """The waistcoat from the body measurements M (BodyMeasure.run) and the trousers' band top
    (m). Returns a suit_pattern.Draft (front and back, the wearer's left; "_r" mirrored)."""
    o = sp.merge(DEFAULTS, opts or {})
    cm = 100.0
    Zw = M["waist_z"] * cm
    zb = band_top_z * cm
    z_side = zb - o["cover_band_cm"] - o["hang_comp_cm"]
    z_pt = z_side - o["point_drop_cm"]
    z_tb = Zw - 2.0 + o["top_button_above_jacket_cm"]
    z_bb = z_pt + o["bottom_button_above_point_cm"]
    wo = o["welt"]
    # the lower welts sit above the hem
    z_welt = z_side + wo["above_hem_cm"] - 2.0
    blk = sp.merge(o["block"], {"front_dart": {"pocket_below_waist_cm": Zw - (z_side - o["dart_below_side_hem_cm"])},
                                "button_ext_cm": o["button_ext_cm"]})
    B0 = sp.draft(M, blk)
    F = dict(B0.frame)
    Zc, Yc, Gc = F["Zc"], F["Yc"], F["Gc"]

    def y_of(z):
        return Yc + (Zc - z) if z <= Zc else Yc - (z - Zc) * F["kf"]

    y_hs, y_pt, y_tb, y_bb = y_of(z_side), y_of(z_pt), y_of(z_tb), y_of(z_bb)
    ext = o["button_ext_cm"]
    xe = Gc + ext

    # --- back (lining): the block's back cut level at the side hem
    bk = B0.geom("back")
    side_b = _cut_y(bk.edge("side"), y_hs)
    cb_full = bk.edge("cb")
    cb = _cut_y(cb_full[::-1], y_hs)[::-1]
    neck0 = bk.edge("neck")
    NPb = neck0[-1]
    y1 = neck0[0][1] + o["back_neck_drop_cm"]
    cb = -_cut_y(-cb, -y1)                      # cb runs hem -> up: keep it below y1
    top = cb[-1]
    neck_b = sp.bezier(top, top + (0.45 * NPb[0], 0.0), NPb + (-0.2 * NPb[0], 0.5 * (top[1] - NPb[1])), NPb, n=20)
    hem_b = np.array([side_b[-1], cb[0]])
    back = sp.Panel("back", [("neck", neck_b), ("shoulder", bk.edge("shoulder")),
                             ("armhole", bk.edge("armhole")), ("side", side_b), ("hem", hem_b), ("cb", cb)],
                    notches={"waist_cb": bk.notches["waist_cb"]})

    # --- front: the block's side body and front as one
    sd_ = B0.geom("side")
    fr = B0.geom("front")
    side_f = _cut_y(sd_.edge("back")[::-1], y_hs)          # P_b down to the hem
    S_h = side_f[-1]
    Pp = np.array([xe - o["point_in_cm"], y_pt])
    # hem: from the side seam down to the point, a slight hollow
    hem_f = sp.bezier(S_h, S_h + (Pp - S_h) * 0.35 + (0, 0.4), S_h + (Pp - S_h) * 0.7 + (0, 0.2), Pp, n=20)
    # front edge: point -> under the last button -> straight up the extension to the top button
    TB = np.array([xe, y_tb])
    C1 = np.array([xe, y_bb + o["cut_below_button_cm"]])
    cut = sp.bezier(Pp, Pp + (C1 - Pp) * 0.45 + (0.6, 0), C1 + (0, 1.2), C1, n=14)
    straight = np.stack([np.full(12, xe), np.linspace(C1[1], TB[1], 12)], 1)
    front_e = sp.join(cut, straight)
    # the V: top button -> neck point, bowed out
    NPf = np.asarray(B0.anchors["np_f"][1], float)
    d = NPf - TB
    nrm = np.array([d[1], -d[0]]) / np.linalg.norm(d)
    if nrm[0] < 0:
        nrm = -nrm
    vb = o["v_belly_cm"]
    neck_v = sp.bezier(TB, TB + d * 0.33 + nrm * vb, TB + d * 0.7 + nrm * vb, NPf, n=24)
    shoulder_f = fr.edge("shoulder")
    arm = sp.join(fr.edge("armhole_upper"), fr.edge("armhole_lower"), sd_.edge("scye")[::-1])
    inner = dict(fr.inner)

    # notches: buttons (centre front), buttonholes (the left front, from the eye toward the edge),
    # the lower welts (slanting up to the front), the breast welt (left)
    nb = int(o["buttons"])
    yb = np.linspace(y_tb, y_bb, nb)
    buttons = np.stack([np.full(nb, Gc), yb], 1)
    bh = o["buttonhole_cm"]
    holes = np.array([[[Gc - 0.2, y], [Gc - 0.2 + bh, y]] for y in yb])
    x_side_w = _x_at_y(side_f, y_of(z_welt))
    xw0 = x_side_w + wo["x_frac"] * (Gc - x_side_w) - wo["w_cm"] / 2
    yw_ = y_of(z_welt)
    welt = np.array([[xw0, yw_ + wo["slant_cm"] / 2], [xw0 + wo["w_cm"], yw_ - wo["slant_cm"] / 2]])
    bw = o["breast_welt"]
    yb_ = Yc + bw["below_chest_cm"]
    x_side_b = F["x_sf"]
    xb0 = x_side_b + bw["x_frac"] * (Gc - x_side_b) - bw["w_cm"] / 2
    bwelt = np.array([[xb0, yb_ + bw["slant_cm"] / 2], [xb0 + bw["w_cm"], yb_ - bw["slant_cm"] / 2]])
    notches = {"button": buttons[0], "buttons": buttons, "welt": welt, "breast_welt": bwelt,
               "point": Pp, "top_button": TB, "buttonholes": holes.reshape(-1, 2)}
    front = sp.Panel("front", [("side", side_f), ("hem", hem_f), ("front", front_e), ("neck", neck_v),
                               ("shoulder", shoulder_f), ("armhole", arm)],
                     notches=notches, inner=inner)
    seams = [
        {"name": "cb", "a": [("back", "cb", False)], "b": [("back_r", "cb", False)], "mirror": False},
        {"name": "shoulder", "a": [("back", "shoulder", False)], "b": [("front", "shoulder", False)]},
        {"name": "side", "a": [("back", "side", False)], "b": [("front", "side", False)]},
    ]
    if inner:
        seams.append({"name": "front_dart", "a": [("front", "dart_b", False)], "b": [("front", "dart_f", False)]})
    F.update({"y_hs": y_hs, "y_pt": y_pt, "y_tb": y_tb, "y_bb": y_bb, "z_side_hem": z_side / cm,
              "z_point": z_pt / cm, "z_top_button": z_tb / cm, "z_welt": z_welt / cm, "x_edge": xe})
    anchors = {k: v for k, v in B0.anchors.items() if k in ("nape", "np_b", "sp_b", "np_f", "sp_f", "bpitch",
                                                          "fpitch", "p_bs", "p_fe")}
    D = sp.Draft([back, front], seams, F, anchors, o)
    return D
