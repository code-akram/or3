"""The shirt's draft (m1 v4 T13 phase B item 5): a men's dress shirt cut from the jacket's block
(suit_pattern.draft with shirt ease, a deeper armhole, the shoulder at the acromion, no pad and
a neck point at the neck's base), so it is placed and sewn by the jacket's runner (Placer,
build_cloth, drape_xpbd), like the waistcoat.

  yoke     the block's back above a yoke seam (across the back, a little lower at the
           armhole), a CB fold (sewn in the drape, no seam mark)
  back     the block's back below the yoke, a CB fold, no suppression at the CB; the side seam
           takes the waist shaping
  front    the block's side body and front as one panel (no side-front suppression, so they
           meet on one line); the neck curve from the neck point to the centre front at the
           collar band's base, a button stand (placket) past the centre front; the shirt tail
           runs on under the trousers
  sleeve   one piece, a shirt's low cap with little ease, gathered into the cuff (the sleeve end
           is wider than the cuff by the pleats); it is cut long by blouse_cm so it blouses over
           the cuff; the cuff and the collar (band and fall) are not simulated: the runner
           models them (suit_shirt_detail) on the suit_neck frame and round the wrist

Notches on the front: the buttons and buttonholes (centre front), the placket's fold. The
collar band's base length and heights come from the runner (suit_neck.NeckFrame), so the
neckline is drafted to the band it is sewn to. Units: cm on the pattern, block y down from the
nape.
"""

import math

import numpy as np

from . import suit_pattern as sp

DEFAULTS = {
    # the jacket block: a slim dress shirt (chest 12 cm over the body, the waist shaped at the
    # side seams), the armhole 3.5 cm under the armpit, the shoulder seam at the acromion, the
    # neck point at the neck's base (the band sits on it)
    "block": {"ease": {"chest": 11.0, "waist": 16.0, "seat": 10.0}, "waist_min_frac": 0.70,
              "scye_below_armpit_cm": 3.5, "scye_rise_cm": 6.0, "scye_ease_cm": 0.8,
              "shoulder_out_cm": 0.5, "pad_cm": 0.0, "shoulder_drop_deg": 0.0,
              "np_out_cm": 0.4, "neck_scale": 1.0, "back_neck_rise_cm": 0.0, "back_shoulder_ease_cm": 0.3,
              "length_frac": 0.40, "hem_flare_cm": 0.0, "split_lapel": True, "cb_seat_frac": 0.0,
              "suppression": {"cb": 0.0, "back_side": 0.78, "side_front": 0.0, "front_dart": 0.0}},
    # a fisheye dart in each back panel (a fitted shirt), this share of the waist suppression,
    # from below the blades to below the waist, x_frac of the way from the CB to the side seam
    "back_dart": {"share": 0.22, "x_frac": 0.45, "top_below_chest_cm": 2.0, "below_waist_cm": 12.0},
    "yoke": {"cb_cm": 9.0, "arm_drop_cm": 1.0},   # the yoke seam: this far below the nape at the CB, lower at the armhole
    "stand_cm": 1.7,               # the button stand (placket) past the centre front
    "placket_cm": 3.4,             # the left front's placket, folded (3 layers)
    "buttons": {"first_below_band_cm": 8.0, "pitch_cm": 9.5, "n": 6},
    "buttonhole_cm": 1.3,
    # the sleeve: the cap's ease over the armhole, the bicep ease, the cuff and its gathers
    # a fitted sleeve: it goes under the jacket's. At 10 cm bicep ease, 2 cm at the elbow and a
    # 3 cm blouse it stood as far off the arm as the jacket's sleeve (p90 38 mm at the elbow
    # against 32) and came through the jacket's under sleeve (run t13c-q1)
    "sleeve": {"head_ease_cm": 1.0, "bicep_ease_cm": 7.0, "pitch_cm": 1.0, "uc_cm": 0.8,
               "pleats": 2, "pleat_cm": 1.5, "blouse_cm": 2.0, "elbow_extra_cm": 0.0,
               # part of the A-pose's 45 deg elbow taken out of the crook in the cut (as the
               # jacket's sleeve, suit_pattern bend): cut straight, the crook's 4 cm of spare
               # length folded into a flap (run t13s-s2)
               "bend_deg": 30.0, "bend_zone_cm": 5.0},
    "cuff": {"h_cm": 6.5, "ease_cm": 8.0, "show_cm": 1.3, "jacket_end_above_wrist_cm": 2.0},
    "seam_allowance_cm": 1.0,
}


def draft(M, neck, opts=None):
    """The shirt from the body measurements M (BodyMeasure.run) and the collar band's base
    (neck: {"z_cb", "z_cf"} metres: the band base at the centre back and front). Returns a
    suit_pattern.Draft (yoke, back, front, sleeve; the wearer's left, "_r" mirrored)."""
    o = sp.merge(DEFAULTS, opts or {})
    cm = 100.0
    blk = sp.merge(o["block"], {"button_ext_cm": o["stand_cm"]})
    B0 = sp.draft(M, blk)
    F = dict(B0.frame)
    Zc, Yc, Gc = F["Zc"], F["Yc"], F["Gc"]

    def y_front(z):
        return Yc - (z - Zc) * F["kf"] if z > Zc else Yc + (Zc - z)

    def y_back(z):
        return Yc - (z - Zc) * F["kb"] if z > Zc else Yc + (Zc - z)

    # --- back: the block's back, the yoke cut off
    bk = B0.geom("back")
    neck_b0 = bk.edge("neck")
    y_cb_top = max(neck_b0[0][1], y_back(neck["z_cb"] * cm))
    top, NPb = np.array([0.0, y_cb_top]), neck_b0[-1]
    neck_b = sp.bezier(top, top + (0.45 * NPb[0], 0.0), NPb + (-0.1 * NPb[0], 0.7 * (top[1] - NPb[1])), NPb, n=20)
    yo = o["yoke"]
    y_y = neck_b0[0][1] + yo["cb_cm"]
    arm_b = bk.edge("armhole")
    # where the yoke seam meets the armhole
    y_ya = y_y + yo["arm_drop_cm"]
    k = int(np.argmin(np.abs(arm_b[:, 1] - y_ya)))
    k = min(max(k, 2), len(arm_b) - 3)
    arm_yoke, arm_back = arm_b[:k + 1], arm_b[k:]
    Q = arm_b[k]
    yoke_seam = sp.bezier(Q, Q + (-0.3 * Q[0], 0.0), (0.3 * Q[0], y_y), (0.0, y_y), n=20)  # armhole -> CB
    cb_full = bk.edge("cb")                     # hem -> nape
    cb_low = cb_full[cb_full[:, 1] >= y_y]
    cb_low = np.vstack([cb_low, [[0.0, y_y]]])
    cb_top = np.array([[0.0, y_y], [0.0, y_cb_top]])
    yoke = sp.Panel("yoke", [("neck", neck_b), ("shoulder", bk.edge("shoulder")), ("armhole", arm_yoke),
                             ("yoke", yoke_seam), ("cb", cb_top)], kind="back")
    bd = o["back_dart"]
    inner_b = {}
    w_d = bd["share"] * (Gc - F["Gw"])
    if w_d > 1e-3:
        yw = F["yw"]
        side_b = bk.edge("side")
        x_sw = float(np.interp(yw, side_b[:, 1], side_b[:, 0]))
        x_d = bd["x_frac"] * x_sw
        y_t, y_b = Yc + bd["top_below_chest_cm"], yw + bd["below_waist_cm"]
        yy = np.linspace(y_b, y_t, 33)
        hwd = np.where(yy >= yw, np.sin(0.5 * np.pi * np.clip((y_b - yy) / (y_b - yw), 0, 1)),
                       np.sin(0.5 * np.pi * np.clip((yy - y_t) / (yw - y_t), 0, 1))) * w_d / 2
        inner_b = {"dart_b": np.stack([x_d - hwd, yy], 1), "dart_f": np.stack([x_d + hwd, yy], 1)}
    back = sp.Panel("back", [("yoke", yoke_seam[::-1]), ("armhole", arm_back), ("side", bk.edge("side")),
                             ("hem", bk.edge("hem")), ("cb", cb_low)], inner=inner_b)

    # --- front: the block's side body and front as one, the stand past the CF, a shirt neck
    sd_ = B0.geom("side")
    fr = B0.geom("front")
    side_f = sd_.edge("back")[::-1]             # P_b -> hem
    yh = F["yh"]
    xe = Gc + o["stand_cm"]
    hem_f = np.array([side_f[-1], [xe, yh]])
    NPf = np.asarray(B0.anchors["np_f"][1], float)
    dx = Gc - NPf[0]

    def front_curve(y_fn):
        return sp.bezier(np.array([Gc, y_fn]), np.array([Gc - 0.55 * dx, y_fn]),
                         np.array([NPf[0] + 0.04 * dx, NPf[1] + 0.5 * (y_fn - NPf[1])]), NPf, n=24)
    y_fn = y_front(neck["z_cf"] * cm)
    if neck.get("half_cm"):
        # the neck depth that makes the neckline (CB -> CF) as long as the band's base it is sewn to
        lo_, hi_ = NPf[1] + 1.0, NPf[1] + 16.0
        for _ in range(40):
            mid = 0.5 * (lo_ + hi_)
            if sp.arclen(neck_b) + sp.arclen(front_curve(mid)) < neck["half_cm"]:
                lo_ = mid
            else:
                hi_ = mid
        y_fn = 0.5 * (lo_ + hi_)
    curve = front_curve(y_fn)
    front_e = np.stack([np.full(24, xe), np.linspace(yh, y_fn, 24)], 1)
    neck_f = sp.join(np.array([[xe, y_fn], [Gc + 0.5 * o["stand_cm"], y_fn]]), curve)
    shoulder_f = fr.edge("shoulder")
    arm = sp.join(fr.edge("armhole_upper"), fr.edge("armhole_lower"), sd_.edge("scye")[::-1])
    bo = o["buttons"]
    yb = y_fn + bo["first_below_band_cm"] + bo["pitch_cm"] * np.arange(bo["n"])
    yb = yb[yb < yh - 4.0]
    buttons = np.stack([np.full(len(yb), Gc), yb], 1)
    bh = o["buttonhole_cm"]
    holes = np.array([[[Gc, y - 0.2], [Gc, y - 0.2 + bh]] for y in yb])
    pk = o["placket_cm"]
    notches = {"button": buttons[0], "buttons": buttons, "buttonholes": holes.reshape(-1, 2),
               "placket_fold": np.array([[xe - pk, yh], [xe - pk, y_fn]])}
    front = sp.Panel("front", [("side", side_f), ("hem", hem_f), ("front", front_e), ("neck", neck_f),
                               ("shoulder", shoulder_f), ("armhole", arm)], notches=notches)

    # --- the sleeve: one piece, a low cap (u round the arm, 0 = top, + forward; v down)
    Sv = o["sleeve"]
    Cf = o["cuff"]
    AH = sp.arclen(arm_yoke) + sp.arclen(arm_back) + sp.arclen(arm)
    Wb = M["bicep"] * cm + Sv["bicep_ease_cm"]
    cuff_round = M["wrist"] * cm + Cf["ease_cm"]
    Wc = cuff_round + Sv["pleats"] * Sv["pleat_cm"]
    We = 0.5 * (Wb + Wc) + Sv["elbow_extra_cm"]
    up = M["upperarm_len"] * cm + blk["shoulder_out_cm"]
    cuff_bottom_above_wrist = Cf["jacket_end_above_wrist_cm"] - Cf["show_cm"]
    SL_axis = up + M["forearm_len"] * cm - cuff_bottom_above_wrist - Cf["h_cm"]
    if Cf.get("top_s_cm"):
        SL_axis = float(Cf["top_s_cm"])     # the runner's: the cuff's top on the arm's axis
    SL = SL_axis + Sv["blouse_cm"]
    uc = Sv["uc_cm"]

    def cap_v(u, hcap):
        tau = np.where(u >= uc, (u - uc) / (Wb / 2 - uc), (uc - u) / (Wb / 2 + uc))
        return hcap * 0.5 * (1 - np.cos(np.pi * np.clip(tau, 0, 1)))

    uu = np.linspace(-Wb / 2, Wb / 2, 200)
    lo_, hi_ = 3.0, 30.0
    for _ in range(50):
        hc = 0.5 * (lo_ + hi_)
        if sp.arclen(np.stack([uu, cap_v(uu, hc)], 1)) < AH + Sv["head_ease_cm"]:
            lo_ = hc
        else:
            hi_ = hc
    hcap = hc
    v_el = up + 1.0

    def width(v):
        return np.interp(v, [0, hcap, v_el, SL], [Wb, Wb, We, Wc])

    def pitch(v):
        return Sv["pitch_cm"] * sp.smoothstep((v - hcap) / (SL - hcap))

    def bend(P):
        P = np.array(P, float)
        u, v = P[:, 0], P[:, 1]
        u0 = (u - pitch(v)) * Wb / width(v)
        r = We / (2 * np.pi)
        dl = r * math.radians(Sv["bend_deg"]) * np.cos(2 * np.pi * (u0 - Wb / 4) / Wb)
        bz = Sv["bend_zone_cm"]
        P[:, 1] = v - dl * sp.smoothstep((v - (v_el - bz)) / (2 * bz))
        return P

    ub = np.linspace(-Wb / 2, uc, 32)
    uf = np.linspace(uc, Wb / 2, 32)
    cap_back = np.stack([ub, cap_v(ub, hcap)], 1)
    cap_front = np.stack([uf, cap_v(uf, hcap)], 1)
    vv = np.linspace(hcap, SL, 48)
    under_f = np.stack([width(vv) / 2 + pitch(vv), vv], 1)
    under_b = np.stack([-width(vv) / 2 + pitch(vv), vv], 1)[::-1]
    cuff_e = np.stack([np.linspace(under_f[-1, 0], under_b[0, 0], 24), np.full(24, SL)], 1)
    under_f, under_b, cuff_e = bend(under_f), bend(under_b), bend(cuff_e)
    sleeve = sp.Panel("sleeve", [("cap_back", cap_back), ("cap_front", cap_front), ("under_f", under_f),
                                 ("cuff", cuff_e), ("under_b", under_b)], kind="top_sleeve",
                      notches={"crown": (uc, 0.0), "placket": np.array([[-Wc / 4 + pitch(SL), SL],
                                                                        [-Wc / 4 + pitch(SL), SL - 12.0]])})

    seams = [
        {"name": "cb_yoke", "a": [("yoke", "cb", False)], "b": [("yoke_r", "cb", False)], "mirror": False},
        {"name": "cb", "a": [("back", "cb", False)], "b": [("back_r", "cb", False)], "mirror": False},
        {"name": "yoke", "a": [("yoke", "yoke", False)], "b": [("back", "yoke", True)]},
        {"name": "shoulder", "a": [("yoke", "shoulder", False)], "b": [("front", "shoulder", False)]},
        {"name": "side", "a": [("back", "side", False)], "b": [("front", "side", False)]},
        # the sleeve head round the armhole, the crown on the shoulder point
        {"name": "armhole", "a": [("yoke", "armhole", False), ("back", "armhole", False), ("front", "armhole", True)],
         "b": [("sleeve", "cap_back", True), ("sleeve", "cap_front", True)]},
        {"name": "underarm", "a": [("sleeve", "under_f", False)], "b": [("sleeve", "under_b", True)]},
    ]
    if inner_b:
        seams.append({"name": "back_dart", "a": [("back", "dart_b", False)], "b": [("back", "dart_f", False)]})
    D = sp.Draft([yoke, back, front, sleeve], seams, F, {}, o)
    # the cap's ease over the crown; the underarm sewn without ease (as the jacket's)
    for sm in D.seams:
        if sm["name"].startswith("armhole"):
            polys, corners, La = D.chain(sm["a"])
            P = sp.join(*polys)
            s_ = sp.cum_len(P) / La
            pb = np.asarray(B0.anchors["p_bs"][1], float)
            pf = np.asarray(B0.anchors["p_fe"][1], float)

            def t_at(q):
                return float(s_[int(np.argmin(np.linalg.norm(P - q, axis=1)))])
            sm["ease_zero"] = (t_at(pb), t_at(pf))
    F.update({"y_yoke": y_y, "y_fn": y_fn, "x_edge": xe, "neck_cb_y": y_cb_top,
              "sleeve": {"Wb": Wb, "We": We, "Wc": Wc, "hcap": hcap, "v_el": v_el, "SL": SL, "SL_axis": SL_axis,
                         "uc": uc, "up": up, "cuff_round": cuff_round, "cuff_h": Cf["h_cm"],
                         "cuff_bottom_above_wrist": cuff_bottom_above_wrist},
              "neck_len_cm": {"back": round(sp.arclen(neck_b), 2), "front": round(sp.arclen(neck_f), 2)},
              "armhole_len": AH})
    D.anchors = {k: v for k, v in B0.anchors.items() if k in ("nape", "np_b", "sp_b", "np_f", "sp_f", "bpitch",
                                                            "fpitch", "p_bs", "p_fe")}
    D.frame = F
    return D
