"""Pattern-drafted trousers (m1 v4 T13 phase B item 3; bench/m1/v4/t13-suit-rebuild.md).

Draft only (numpy, no bpy), like suit_pattern for the jacket: body measurements -> flat
panels in cm, the wearer's left half; the runner (bench/m1/v4/suit_spike.py --trousers)
meshes, places, sews and drapes them.

  measure_legs(BM, M, shoe_pts, opts)   leg and rise measurements on the rest body
  draft(M, L, opts)                     a classic trouser block (Aldrich, Metric Pattern
                                        Cutting for Menswear, "classic trouser block"),
                                        flat front, natural-waist rise for a three-piece
                                        suit (worn on braces under the waistcoat)

Panels (each the left leg's; "<name>_r" mirrored by the runner):

  front   side seam, waist, centre front (the fly line) to the seat line, front crotch
          curve to the fork point, inseam, hem (up at the crease: the break)
  back    side seam, waist with one dart, the seat seam raised at the centre back and
          sloped (the seat angle), back crotch curve to the fork (dropped), inseam, hem
          (down at the crease, over the heel)
  band    the waistband: a strip from the centre front round the side to the centre back

Draft frame per panel: x across, from the side line (x = 0 at the seat line) toward the
centre (CF on the front, CB on the back); y down from the waist seam at the side. The crease
line is vertical (x = const) on both. Levels come from the body: the waist seam is the band's
bottom (the band's top at waist_to_stature x stature, as the shipped trousers), the seat line
at the seat's greatest projection, the crotch line below the body's crotch by crotch_drop_cm,
the hem from its height above the floor at the side, the front crease and the back crease.

Seams: the outseam (front/back side), the inseam, the front rise (the left front's fly line
and crotch curve to the right's), the seat seam (back to back_r), the waist to the band
(the dart closed), the band's centre back and centre front, the back dart. The fly is sewn
closed (the opening is a mark: the J-stitch on the left front).
"""

import math

import numpy as np

from .suit_pattern import Draft, Panel, _hull, arclen, at_params, bezier, join, merge, perimeter

LEFT_LEG = ("thigh_l", "calf_l", "foot_l", "ball_l")
TRUNK = ("pelvis", "spine_01", "spine_02", "spine_03", "thigh_l", "thigh_r")

DEFAULTS = {
    "waist_to_stature": 0.627,    # the band's top (suit.py trousers: natural rise, under the waistcoat)
    "band_cm": 4.0,
    "ease": {"waist": 2.0, "seat": 6.0},       # girth ease, cm (braces trousers sit easy at the waist)
    "crotch_drop_cm": 2.0,        # the trouser fork below the body's crotch
    "front_seat_less_cm": 2.0,    # the front's seat width is S/4 - half this, the back's S/4 + half
    "front_waist_less_cm": 2.0,   # the same split at the waist
    "fly_slope_cm": 1.0,          # the centre front comes in this much from the seat line to the waist
    "front_fork": 0.0625,         # front crotch extension, x seat (S/16)
    "front_fork_add_cm": 0.5,
    "back_fork": 0.125,           # back crotch extension, x seat (S/8)
    "back_fork_add_cm": 0.0,
    "back_fork_drop_cm": 0.8,     # the back fork below the crotch line
    "seat_angle_deg": 10.0,       # the seat seam's slope from vertical
    "back_rise_cm": 3.5,          # the centre back's waist above the side's (a braces back)
    "back_dart": {"w_cm": 1.5, "len_cm": 10.0},
    "crease_back_in_cm": 1.0,     # the back crease this far toward the side from the back's middle
    "back_crease_below_fork_cm": 8.0,   # the back crease runs from the hem up to here (it fades below the seat)
    "knee_cm": 42.0,              # trouser knee girth (front 2 cm under half, back 2 over)
    "hem_cm": 38.0,               # trouser bottom girth
    "knee_above_mid_cm": 5.0,     # the knee line above halfway from the crotch line to the hem
    # hem heights above the floor (cm): side, at the front crease (rests on the vamp: one soft
    # break) and at the back crease (over the heel counter)
    "hem_z_cm": {"side": 7.0, "front": 8.5, "back": 5.5},
    "fly": {"w_cm": 3.8, "end_above_crotch_cm": 5.0},
    "side_pocket": {"in_cm": 3.8, "drop_cm": 17.0},     # slant pocket: on the waist this far in, to the side seam this far down
    "back_pocket": {"below_cm": 7.0, "w_cm": 13.0},     # jetted, below the band, on the dart
    "seam_allowance_cm": 1.0,
}


# --- measurements ----------------------------------------------------------------------------

def _leg_section(BM, z, fmask):
    s = BM.sec(2, z, fmask)
    if len(s) == 0:
        return None
    p = s.reshape(-1, 3)[:, :2]
    p = p[p[:, 0] > 0.0]
    return p if len(p) >= 3 else None


def measure_legs(BM, M, shoe_pts=None, opts=None):
    """Rise, leg levels and girths (metres) on the rest body (BodyMeasure BM, its run() M).
    shoe_pts: (k, 3) world points of the shoes (the hem rests on them)."""
    o = merge(DEFAULTS, opts)
    fd = BM.dom[BM.tris]
    f_leg = np.isin(fd, LEFT_LEG).all(1)
    f_trunk = np.isin(fd, TRUNK).all(1)
    J = BM.J
    L = {}
    floor = M["floor_z"]
    L["band_top_z"] = floor + o["waist_to_stature"] * M["stature"]
    L["waist_seam_z"] = L["band_top_z"] - o["band_cm"] / 100.0
    # the crotch: the lowest point of the body's midplane section
    s = BM.sec(0, 0.0, f_trunk)
    L["crotch_z"] = float(s[:, :, 2].min())
    L["waist_girth"] = BM.girth(L["waist_seam_z"], f_trunk)
    L["band_top_girth"] = BM.girth(L["band_top_z"], f_trunk)
    L["seat"] = M["seat"]
    L["seat_z"] = M["seat_z"]
    # the left leg: girths and its centre line
    zk = float(J["calf_l"][0][2])
    za = float(J["foot_l"][0][2])
    L["knee_z"], L["ankle_z"] = zk, za
    p = _leg_section(BM, L["crotch_z"] - 0.03, f_leg | f_trunk)
    L["thigh"] = perimeter(_hull(p)) if p is not None else 0.0
    p = _leg_section(BM, zk, f_leg)
    L["knee"] = perimeter(_hull(p)) if p is not None else 0.0
    zs = np.arange(za + 0.05, zk - 0.03, 0.01)
    g = [perimeter(_hull(q)) if (q := _leg_section(BM, z, f_leg)) is not None else 0.0 for z in zs]
    L["calf"], L["calf_z"] = float(max(g)), float(zs[int(np.argmax(g))])
    # the sagittal profile (front and back of the trunk at x = 0, metres): for the rise seams
    L["floor_z"] = floor
    if shoe_pts is not None and len(shoe_pts):
        sp_ = np.asarray(shoe_pts)
        sp_ = sp_[sp_[:, 0] > 0]
        L["shoe_top_z"] = float(sp_[:, 2].max())
    return L


# --- the draft --------------------------------------------------------------------------------

def _poly_x_at(poly, y):
    """x where a y-monotone polyline (cm) passes height y (interpolated, clamped)."""
    p = np.asarray(poly)
    if p[0, 1] > p[-1, 1]:
        p = p[::-1]
    return float(np.interp(y, p[:, 1], p[:, 0]))


def draft(M, L, opts=None):
    """The trouser block from the jacket measurements M and the leg measurements L (metres).
    Returns a suit_pattern.Draft (cm)."""
    o = merge(DEFAULTS, opts)
    cm = 100.0
    E = o["ease"]
    S = L["seat"] * cm + E["seat"]
    W = L["waist_girth"] * cm + E["waist"]
    zws = L["waist_seam_z"] * cm

    def y_of(z_cm):
        return zws - z_cm

    y_s = y_of(L["seat_z"] * cm)
    y_c = y_of(L["crotch_z"] * cm) + o["crotch_drop_cm"]
    hz = o["hem_z_cm"]
    fl = L["floor_z"] * cm
    y_h = y_of(fl + hz["side"])
    y_hf = y_of(fl + hz["front"])
    y_hb = y_of(fl + hz["back"])
    y_k = y_c + 0.5 * (y_h - y_c) - o["knee_above_mid_cm"]
    K, H = o["knee_cm"], o["hem_cm"]

    # ---- front
    x_cfs = S / 4 - o["front_seat_less_cm"] / 2
    x_fk = x_cfs + o["front_fork"] * S + o["front_fork_add_cm"]
    x_cr = 0.5 * x_fk
    x_cfw = x_cfs - o["fly_slope_cm"]
    wf = W / 4 - o["front_waist_less_cm"] / 2
    x_sw = x_cfw - wf
    kf, hf = K / 2 - 2.0, H / 2 - 2.0
    fly = np.array([[x_cfw, 0.0], [x_cfs, y_s]])
    fly = at_params(fly, np.linspace(0, 1, 12))
    # the front crotch curve: down the fly line, round to the fork (level there)
    crotch_f = bezier(np.array([x_cfs, y_s]), np.array([x_cfs, y_s + 0.75 * (y_c - y_s)]),
                      np.array([x_cfs + 0.35 * (x_fk - x_cfs), y_c]), np.array([x_fk, y_c]), 20)
    in_k = np.array([x_cr + kf / 2, y_k])
    in_h = np.array([x_cr + hf / 2, y_h])
    # inseam: hollow from the fork to the knee, straight to the hem
    inseam_f = join(bezier(np.array([x_fk, y_c]), np.array([x_fk - 0.25 * (x_fk - in_k[0]), y_c + 0.35 * (y_k - y_c)]),
                           in_k + np.array([0.0, -0.35 * (y_k - y_c)]), in_k, 20),
                    at_params(np.array([in_k, in_h]), np.linspace(0, 1, 12))[1:])
    out_k = np.array([x_cr - kf / 2, y_k])
    out_h = np.array([x_cr - hf / 2, y_h])
    # hem: up at the crease (the front rests on the vamp)
    xs_h = np.linspace(in_h[0], out_h[0], 17)
    hem_f = np.stack([xs_h, y_h - (y_h - y_hf) * np.cos(np.pi * (xs_h - x_cr) / (hf * 1.0)) ** 2], 1)
    hem_f[0], hem_f[-1] = in_h, out_h
    # side seam: hem -> knee -> seat line (x = 0) -> the hip curve to the waist
    side_low = at_params(np.array([out_h, out_k]), np.linspace(0, 1, 12))
    side_mid = bezier(out_k, out_k + np.array([0.0, -0.4 * (y_k - y_s)]), np.array([0.0, y_s + 0.35 * (y_k - y_s)]),
                      np.array([0.0, y_s]), 20)
    hip_f = bezier(np.array([0.0, y_s]), np.array([0.0, 0.5 * y_s]), np.array([x_sw - 0.25 * x_sw, 0.15 * y_s]),
                   np.array([x_sw, 0.0]), 16)
    side_f = join(side_low, side_mid[1:], hip_f[1:])
    waist_f = at_params(np.array([[x_sw, 0.0], [x_cfw, 0.0]]), np.linspace(0, 1, 16))
    front = Panel("front", [("waist", waist_f), ("fly", fly), ("crotch", crotch_f), ("inseam", inseam_f),
                            ("hem", hem_f), ("side", side_f)],
                  lines={"crease": np.array([[x_cr, 0.0], [x_cr, y_hf]])})

    # fly J-stitch (a mark): fly_w in from the CF line, down to the fly end, round to the CF
    fo = o["fly"]
    y_fe = y_c - fo["end_above_crotch_cm"] - 2.0
    jx = lambda y: _poly_x_at(fly, min(y, y_s)) if y <= y_s else x_cfs
    j_top = np.array([jx(0.0) - fo["w_cm"], 0.0])
    j_low = np.array([jx(y_fe - fo["w_cm"]) - fo["w_cm"], y_fe - fo["w_cm"]])
    j_end = np.array([jx(y_fe), y_fe])
    jst = join(at_params(np.array([j_top, j_low]), np.linspace(0, 1, 12)),
               bezier(j_low, j_low + np.array([0.0, 0.55 * fo["w_cm"]]), j_end + np.array([-0.55 * fo["w_cm"], 0.0]),
                      j_end, 10)[1:])
    sp_ = o["side_pocket"]
    p_top = np.array([x_sw + sp_["in_cm"], 0.0])
    p_bot = np.array([_poly_x_at(hip_f, sp_["drop_cm"]) if sp_["drop_cm"] < y_s else 0.0, sp_["drop_cm"]])
    front.notches.update({"fly_j": jst, "side_pocket": np.array([p_top, p_bot]), "fly_end": j_end})

    # ---- back (same frame: x from the side line toward the centre back)
    x_cbs = S / 4 + o["front_seat_less_cm"] / 2
    a = math.radians(o["seat_angle_deg"])
    rb = o["back_rise_cm"]
    # the seat seam: through (x_cbs, y_s), sloped; the centre back waist rb above the side's
    x_cbw = x_cbs - math.tan(a) * (y_s + rb)
    y_cbw = -rb
    x_bfk = x_cbs + o["back_fork"] * S + o["back_fork_add_cm"]
    y_bfk = y_c + o["back_fork_drop_cm"]
    # below the seat line the seam keeps its slope a little way, then curves to the fork
    y_bend = y_s + 0.45 * (y_c - y_s)
    x_bend = x_cbs + math.tan(a) * (y_bend - y_s)
    cb = at_params(np.array([[x_cbw, y_cbw], [x_cbs, y_s], [x_bend, y_bend]]), np.linspace(0, 1, 18))
    crotch_b = bezier(np.array([x_bend, y_bend]), np.array([x_bend + math.tan(a) * 0.5 * (y_bfk - y_bend), y_bend + 0.5 * (y_bfk - y_bend)]),
                      np.array([x_bend + 0.45 * (x_bfk - x_bend), y_bfk]), np.array([x_bfk, y_bfk]), 20)
    x_crb = 0.5 * x_bfk - o["crease_back_in_cm"]
    kb, hb = K / 2 + 2.0, H / 2 + 2.0
    bin_k = np.array([x_crb + kb / 2, y_k])
    bin_h = np.array([x_crb + hb / 2, y_h])
    inseam_b = join(bezier(np.array([x_bfk, y_bfk]), np.array([x_bfk - 0.3 * (x_bfk - bin_k[0]), y_bfk + 0.35 * (y_k - y_bfk)]),
                           bin_k + np.array([0.0, -0.35 * (y_k - y_bfk)]), bin_k, 20),
                    at_params(np.array([bin_k, bin_h]), np.linspace(0, 1, 12))[1:])
    bout_k = np.array([x_crb - kb / 2, y_k])
    bout_h = np.array([x_crb - hb / 2, y_h])
    xs_b = np.linspace(bin_h[0], bout_h[0], 17)
    hem_b = np.stack([xs_b, y_h + (y_hb - y_h) * np.cos(np.pi * (xs_b - x_crb) / (hb * 1.0)) ** 2], 1)
    hem_b[0], hem_b[-1] = bin_h, bout_h
    # the back waist: from the centre back down to the side at y = 0, W/4 + split + the dart
    wb = W / 4 + o["front_waist_less_cm"] / 2
    dw, dl = o["back_dart"]["w_cm"], o["back_dart"]["len_cm"]
    Lw = wb + dw
    x_swb = x_cbw - math.sqrt(max(Lw ** 2 - rb ** 2, 1.0))
    P_cb, P_sd = np.array([x_cbw, y_cbw]), np.array([x_swb, 0.0])
    u = (P_cb - P_sd) / np.linalg.norm(P_cb - P_sd)
    nrm = np.array([-u[1], u[0]])
    if nrm[1] < 0:
        nrm = -nrm                                   # down the panel
    mid = P_sd + u * (0.5 * (Lw - dw) + 0.5 * dw)    # the dart's centre on the waist
    d_s, d_c = mid - u * dw / 2, mid + u * dw / 2
    tip = mid + nrm * dl
    # the dart legs, raised at the waist so they are equal and the sewn waist runs on smoothly
    waist_s = at_params(np.array([P_sd, d_s]), np.linspace(0, 1, 8))
    dart_s = at_params(np.array([d_s, tip]), np.linspace(0, 1, 10))
    dart_c = at_params(np.array([tip, d_c]), np.linspace(0, 1, 10))
    waist_c = at_params(np.array([d_c, P_cb]), np.linspace(0, 1, 8))
    bside_low = at_params(np.array([bout_h, bout_k]), np.linspace(0, 1, 12))
    bside_mid = bezier(bout_k, bout_k + np.array([0.0, -0.4 * (y_k - y_s)]), np.array([0.0, y_s + 0.35 * (y_k - y_s)]),
                       np.array([0.0, y_s]), 20)
    hip_b = bezier(np.array([0.0, y_s]), np.array([0.0, 0.5 * y_s]), np.array([x_swb - 0.25 * x_swb, 0.15 * y_s]),
                   P_sd, 16)
    side_b = join(bside_low, bside_mid[1:], hip_b[1:])
    back = Panel("back", [("waist_s", waist_s), ("dart_s", dart_s), ("dart_c", dart_c), ("waist_c", waist_c),
                          ("cb", cb), ("crotch", crotch_b), ("inseam", inseam_b), ("hem", hem_b), ("side", side_b)],
                 lines={"crease": np.array([[x_crb, y_c + o["back_crease_below_fork_cm"]], [x_crb, y_hb]])})
    bp = o["back_pocket"]
    pc = mid + nrm * bp["below_cm"]
    back.notches.update({"back_pocket": np.array([pc - u * bp["w_cm"] / 2, pc + u * bp["w_cm"] / 2]),
                         "dart_tip": tip})

    # ---- waistband: centre front (x = 0) round to the centre back, y down from its top

    Lb = arclen(waist_f) + arclen(waist_s) + arclen(waist_c)
    hb_ = o["band_cm"]
    band = Panel("band", [("bottom", at_params(np.array([[0.0, hb_], [Lb, hb_]]), np.linspace(0, 1, 40))),
                          ("cb", at_params(np.array([[Lb, hb_], [Lb, 0.0]]), np.linspace(0, 1, 4))),
                          ("top", at_params(np.array([[Lb, 0.0], [0.0, 0.0]]), np.linspace(0, 1, 40))),
                          ("cf", at_params(np.array([[0.0, 0.0], [0.0, hb_]]), np.linspace(0, 1, 4)))],
                 notches={"side": np.array([arclen(waist_f), hb_ / 2])})

    panels = [front, back, band]
    seams = [
        {"name": "outseam", "a": [("front", "side", False)], "b": [("back", "side", False)]},
        {"name": "inseam", "a": [("front", "inseam", False)], "b": [("back", "inseam", False)]},
        {"name": "rise_front", "a": [("front", "fly", False), ("front", "crotch", False)],
         "b": [("front_r", "fly", False), ("front_r", "crotch", False)], "mirror": False},
        {"name": "seat", "a": [("back", "cb", False), ("back", "crotch", False)],
         "b": [("back_r", "cb", False), ("back_r", "crotch", False)], "mirror": False},
        {"name": "band", "a": [("band", "bottom", False)],
         "b": [("front", "waist", True), ("back", "waist_s", False), ("back", "waist_c", False)]},
        {"name": "band_cb", "a": [("band", "cb", False)], "b": [("band_r", "cb", False)], "mirror": False},
        {"name": "band_cf", "a": [("band", "cf", False)], "b": [("band_r", "cf", False)], "mirror": False},
        {"name": "back_dart", "a": [("back", "dart_s", False)], "b": [("back", "dart_c", True)]},
    ]
    frame = {"S": S, "W": W, "zws": zws, "y_s": y_s, "y_c": y_c, "y_k": y_k, "y_h": y_h, "y_hf": y_hf, "y_hb": y_hb,
             "x_cfs": x_cfs, "x_cfw": x_cfw, "x_fk": x_fk, "x_cr": x_cr, "x_sw": x_sw,
             "x_cbs": x_cbs, "x_cbw": x_cbw, "y_cbw": y_cbw, "x_bfk": x_bfk, "y_bfk": y_bfk, "x_crb": x_crb,
             "x_swb": x_swb, "band_len": Lb, "band_cm": hb_, "seat_angle_deg": o["seat_angle_deg"],
             "knee_f": kf, "knee_b": kb, "hem_f": hf, "hem_b": hb}
    anchors = {"fork_f": ("front", np.array([x_fk, y_c])), "fork_b": ("back", np.array([x_bfk, y_bfk]))}
    return Draft(panels, seams, frame, anchors, o)
