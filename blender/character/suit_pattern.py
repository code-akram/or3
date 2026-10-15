"""Pattern-drafted jacket (m1 v4 step 5 spike; bench/m1/v4/suit-spike.md).

Draft only: body measurements -> flat 2D panels. No bpy here (numpy only), so
the draft can be checked and plotted outside Blender. The bench runner
(bench/m1/v4/suit_spike.py) meshes the panels, places them round the body,
sews them with Blender cloth sewing springs and keeps the settled cloth.

Two parts:

  measure(co, dom, joints)   tape measurements from the rest-pose MPFB body
                             (convex-hull girths = a tape over the hollows,
                             surface arcs, landmark heights)
  draft(M, opts)             an Aldrich-style men's lounge jacket block
                             (Metric Pattern Cutting for Menswear, "classic
                             tailored jacket"): back with a centre-back seam,
                             side body, front with a front dart, lapel and
                             roll line, an undercollar with its own roll line,
                             a two-piece sleeve (top and under sleeve) drafted
                             to the armhole with sleeve-head ease, and a
                             shoulder pad as a separate volume.

Units: the draft works in centimetres like the book; panel outlines are
returned in metres. Block frame: x across the body from the centre back
(x = 0) toward the centre front, y down from the nape (y = 0). Every panel is
the wearer's left half; the runner mirrors it for the right.

A panel is a closed outline made of named edges (each an open polyline, in
order, sharing end points) plus optional internal lines (the lapel and collar
roll lines, the dart centre) and notches. Seams pair two named edges
(panel, edge, reversed?) and carry an ease (the longer edge is gathered).

Where the book uses proportional formulas (chest/8, neck/5, ...) that stand in
for a measurement a tailor would take, this draft uses the measurement itself:
the body is available, so across back, across chest, shoulder heights and the
front and back lengths come from the body. The ease values are the book's
order of magnitude for a close-fitting lounge jacket worn over a waistcoat.
"""

import math

import numpy as np

TORSO = ("pelvis", "spine_01", "spine_02", "spine_03", "clavicle_l", "clavicle_r", "neck_01")
ARMS = ("upperarm_l", "upperarm_r", "lowerarm_l", "lowerarm_r", "hand_l", "hand_r")
LEGS = ("thigh_l", "thigh_r")

DEFAULTS = {
    # total girth ease over the body, cm
    "ease": {"chest": 12.0, "waist": 11.0, "seat": 7.0, "bicep": 9.0, "cuff": 13.0},
    "waist_min_frac": 0.85,       # jacket waist >= this x jacket chest (no jacket follows a 26 cm drop)
    "scye_ease_cm": 0.6,          # each side of the arm root, at the chest line
    "scye_below_armpit_cm": 2.5,  # armhole bottom below the body's armpit
    "scye_rise_cm": 5.0,          # lower armhole: its ends sit this far above its bottom
    "side_front_frac": 0.35,      # the front panel takes this share of the armhole bottom
    "back_scye_frac": 0.18,       # the back takes this share of it: the back/side seam meets the
                                  # armhole where it has turned, square to it (not tangent: a sliver)
    "shoulder_out_cm": 1.75,      # jacket shoulder point past the acromion (fable 3.5: 1.5-2)
    "shoulder_drop_deg": 3.0,     # extra shoulder slope against the body's (fable 3.5)
    "back_shoulder_ease_cm": 0.6,
    "back_neck_rise_cm": 0.5,
    "np_out_cm": 3.2,             # jacket neck point out from the neck base (clears the shirt collar)
    "neck_scale": 1.15,           # neckline length over the quarter ellipse: the placed neckline rides
                                  # out over the shirt collar (calibrated on spike sim2: placed/drafted 1.26)
    "pad_cm": 1.2,                # shoulder pad at the shoulder point (the runner builds the volume)
    "length_frac": 0.475,         # nape-to-hem = this x nape height (the classic rule is 0.5)
    "suppression": {"cb": 0.22, "back_side": 0.43, "side_front": 0.35, "front_dart": 0.0},   # shares of the waist suppression
    # the front dart (a fisheye, sewn): from below the chest to the hip pocket line, at this
    # share of the way from the side seam to the centre front
    "front_dart": {"x_frac": 0.5, "top_below_chest_cm": 4.0, "pocket_below_waist_cm": 8.0},
    "cb_seat_frac": 0.8,          # CB seam in at seat and hem, x its waist value
    "hem_flare_cm": 1.0,          # half hem wider than the half seat
    "button_ext_cm": 2.0,         # button extension past CF
    "button_below_waist_cm": 2.0, # the (one) button = the break point
    "front_hem_in_cm": 6.0,       # cutaway: front hem corner this far inside CF (it was 1.5: the
                                  # fronts ran straight down below the button)
    "cutaway": {"straight_cm": 6.0,   # below the button the edge runs straight this far, then rounds
                "hem_angle_deg": 50.0},  # ... meeting the hem at this angle (from the hem line)
    "lapel_width_cm": 8.0,        # perpendicular to the roll line at the lapel point
    "lapel_belly_cm": 0.6,
    "gorge_drop_cm": 7.5,         # gorge point below the front neck point
    "gorge_past_roll_cm": 3.0,    # gorge point this far on the lapel side of the roll line
    "roll_past_np_cm": 2.0,       # roll line crosses the shoulder line this far past the neck point
    "collar": {"stand_cm": 3.0, "fall_cm": 4.2, "end_width_cm": 4.0, "spread": 1.22},
    "sleeve": {"head_ease_cm": 3.0, "pitch_cm": 2.0, "bend_deg": 25.0, "bend_zone_cm": 5.0, "cuff_slant_cm": 1.2,
               "elbow_extra_cm": 1.0, "under_offset_cm": 3.0, "hind_offset_cm": 1.5, "end_above_wrist_cm": 1.0},
    "seam_allowance_cm": 1.0,     # drawn on the pattern sheet; the sim sews on the sew lines
    # pocket, button and buttonhole placement (marked on the pattern; the runner builds them on
    # the drape). Hip pockets: straight, the front dart ends in the pocket line, the front end
    # this far in front of the dart; breast welt on the wearer's left only, rising to the side;
    # the buttonhole's eye just past CF (the button sits on CF), the slit running to the side;
    # kissing cuff buttons beside the hind seam (the sleeve vent)
    "details": {
        "hip_pocket": {"front_past_dart_cm": 6.0, "width_cm": 16.0, "flap_cm": 5.5, "jet_cm": 0.5,
                       "side_clear_cm": 1.0},
        "breast_welt": {"width_cm": 10.0, "height_cm": 2.4, "rise_cm": 1.5, "front_past_dart_cm": 2.5,
                        "below_chest_cm": 2.0},
        "buttonhole": {"length_cm": 2.4, "eye_past_cf_cm": 0.3},
        "cuff_buttons": {"n": 4, "diam_cm": 1.5, "first_above_cuff_cm": 3.0, "from_seam_cm": 1.4},
    },
}


# --- measuring -------------------------------------------------------------------------------

def _hull(p):
    """Convex hull (Andrew's monotone chain) of 2D points, CCW."""
    p = np.unique(np.round(p, 6), axis=0)
    if len(p) < 3:
        return p
    p = p[np.lexsort((p[:, 1], p[:, 0]))]

    def half(pts):
        h = []
        for q in pts:
            while len(h) >= 2:
                a, b = h[-2], h[-1]
                if (b[0] - a[0]) * (q[1] - a[1]) - (b[1] - a[1]) * (q[0] - a[0]) <= 0:
                    h.pop()
                else:
                    break
            h.append(q)
        return h

    lo, hi = half(p), half(p[::-1])
    return np.array(lo[:-1] + hi[:-1])


def perimeter(poly, closed=True):
    d = np.diff(np.vstack([poly, poly[:1]]) if closed else poly, axis=0)
    return float(np.linalg.norm(d, axis=1).sum())




def section(co, tris, axis, h):
    """Plane-mesh intersection: segments (K, 2, 3) of the triangles crossing
    the plane co[:, axis] = h."""
    v = co[tris]                                   # (T, 3, 3)
    d = v[:, :, axis] - h
    cross = (d.min(1) < 0) & (d.max(1) > 0)
    v, d = v[cross], d[cross]
    segs = []
    for a, b in ((0, 1), (1, 2), (2, 0)):
        da, db = d[:, a], d[:, b]
        hit = (da < 0) != (db < 0)
        t = np.where(hit, da / np.where(hit, da - db, 1.0), 0.0)
        p = v[:, a] + (v[:, b] - v[:, a]) * t[:, None]
        segs.append((hit, p))
    out = []
    for k in range(len(v)):
        pts = [p[k] for hit, p in segs if hit[k]]
        if len(pts) == 2:
            out.append(pts)
    return np.array(out).reshape(-1, 2, 3)


class BodyMeasure:
    """Tape measurements on the rest-pose body, from plane sections of its
    triangles (a tape over a hollow is the convex hull of the section).

    co      (N, 3) vertex positions (Z up, front = -Y, wearer's left = +X)
    tris    (T, 3) triangle vertex indices
    dom     (N,) dominant bone name per vertex ('' if none)
    joints  {bone: (head xyz, tail xyz)}
    """

    def __init__(self, co, tris, dom, joints):
        self.co = np.asarray(co, float)
        self.tris = np.asarray(tris, int)
        dom = np.asarray(dom)
        self.dom = dom
        self.J = {k: (np.asarray(h, float), np.asarray(t, float)) for k, (h, t) in joints.items()}
        fd = dom[self.tris]
        self.f_torso = np.isin(fd, TORSO).all(1)
        self.f_neck = np.isin(fd, ("neck_01", "head")).all(1)
        self.f_trunk = np.isin(fd, TORSO + LEGS).all(1)
        self.f_noarm = ~np.isin(fd, ("lowerarm_l", "lowerarm_r", "hand_l", "hand_r")).any(1)

    def sec(self, axis, h, fmask=None):
        tris = self.tris if fmask is None else self.tris[fmask]
        return section(self.co, tris, axis, h)

    def ring(self, z, fmask):
        s = self.sec(2, z, fmask)
        if len(s) < 3:
            return None
        return _hull(s.reshape(-1, 3)[:, :2])

    def girth(self, z, fmask):
        h = self.ring(z, fmask)
        return perimeter(h) if h is not None and len(h) >= 3 else 0.0

    def _intervals(self, z):
        s = self.sec(2, z, self.f_noarm)
        s = s[(s[:, :, 0] > 0.0).all(1)]
        iv = sorted(zip(s[:, :, 0].min(1), s[:, :, 0].max(1)))
        out = []
        for a, b in iv:
            if out and a <= out[-1][1] + 0.003:
                out[-1][1] = max(out[-1][1], b)
            else:
                out.append([a, b])
        return out

    def armpit(self):
        """Highest z below the shoulder joint where the section shows air
        between the torso and the left arm; and the torso's side x there."""
        z0 = self.J["upperarm_l"][0][2]
        for z in np.arange(z0 - 0.01, z0 - 0.30, -0.002):
            iv = self._intervals(z)
            if len(iv) >= 2 and iv[0][0] < 0.02:
                return float(z), float(iv[0][1])
        raise RuntimeError("armpit not found")

    def profile(self, x, z0, z1, side, fmask=None, step=0.004):
        """The body's profile in the sagittal plane at x between heights z0 > z1:
        the back (side=+1, max y) or the front (side=-1, min y). (M, 2) of (y, z)."""
        s = self.sec(0, x, self.f_trunk if fmask is None else fmask)
        za, zb = s[:, 0, 2], s[:, 1, 2]
        out = []
        for z in np.arange(z0, z1 - 1e-9, -step):
            hit = (np.minimum(za, zb) <= z) & (np.maximum(za, zb) > z)
            if not hit.any():
                continue
            a, b = s[hit, 0], s[hit, 1]
            t = (z - a[:, 2]) / np.where(np.abs(b[:, 2] - a[:, 2]) > 1e-12, b[:, 2] - a[:, 2], 1.0)
            y = a[:, 1] + (b[:, 1] - a[:, 1]) * t
            out.append(((y.max() if side > 0 else y.min()), z))
        return np.array(out)

    def tape(self, x, z0, z1, side, fmask=None):
        p = self.profile(x, z0, z1, side, fmask)
        # a tape laid down the body: bridge hollows (hull on the outside)
        if len(p) < 3:
            return 0.0, p
        q = p.copy()
        for _ in range(3):
            q[1:-1, 0] = (np.maximum if side > 0 else np.minimum)(q[1:-1, 0], 0.5 * (q[:-2, 0] + q[2:, 0]))
        return perimeter(q, closed=False), q

    def ring_from_cb(self, z, fmask, dense=400):
        """The hull ring at z resampled densely, ordered from the centre back
        round the wearer's left (+x) to the centre front: (K, 2) and arc (K,)."""
        h = self.ring(z, fmask)
        pts = np.vstack([h, h[:1]])
        seg = np.diff(pts, axis=0)
        L = np.concatenate([[0], np.cumsum(np.linalg.norm(seg, axis=1))])
        t = np.linspace(0, L[-1], dense, endpoint=False)
        d = np.stack([np.interp(t, L, pts[:, 0]), np.interp(t, L, pts[:, 1])], 1)
        # the centre back: the back-most point near x = 0
        cy = 0.5 * (d[:, 1].max() + d[:, 1].min())
        i0 = int(np.argmin(np.where(d[:, 1] > cy, np.abs(d[:, 0]), 9)))
        d = np.roll(d, -i0, axis=0)
        if d[dense // 8, 0] < 0:     # go round the left (+x) side first
            d = np.vstack([d[:1], d[1:][::-1]])
        i1 = int(np.argmin(np.where(d[:, 1] < cy, np.abs(d[:, 0]), 9)))
        d = d[:i1 + 1]
        arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(d, axis=0), axis=1))])
        return d, arc

    def arc_to_y(self, z, fmask, y):
        """Arc from the centre back round the left side to the lateral point at
        height y (None: to the centre front)."""
        d, arc = self.ring_from_cb(z, fmask)
        if y is None:
            return float(arc[-1])
        lat = d[:, 0] > 0.6 * d[:, 0].max()
        i = np.nonzero(lat)[0]
        k = i[int(np.argmin(np.abs(d[i, 1] - y)))]
        return float(arc[k])

    def half_arc(self, z, fmask, side, xlim):
        """Arc length of the section hull on the back (side=+1) or front (-1)
        between x = -xlim and +xlim."""
        h = self.ring(z, fmask)
        if h is None:
            return 0.0
        # dense resample of the hull, keep the side and |x| <= xlim
        pts = np.vstack([h, h[:1]])
        seg = np.linspace(0, 1, 40)[:-1]
        dense = np.vstack([a + (b - a) * seg[:, None] for a, b in zip(pts[:-1], pts[1:])])
        cy = 0.5 * (h[:, 1].max() + h[:, 1].min())
        keep = ((dense[:, 1] - cy) * side > 0) & (np.abs(dense[:, 0]) <= xlim)
        nxt = np.roll(dense, -1, axis=0)
        both = keep & np.roll(keep, -1)
        return float(np.linalg.norm(nxt - dense, axis=1)[both].sum())

    def run(self):
        J = self.J
        M = {}
        pel = float(J["pelvis"][0][2])
        armpit, xt = self.armpit()
        M["armpit_z"], M["torso_side_x"] = armpit, xt
        # the arm root just above the armpit: its front and back (y), and where
        # those fall on the chest ring (arc from the centre back round the left side)
        sec = self.sec(2, armpit + 0.015, np.isin(self.dom[self.tris], ("upperarm_l",)).all(1)).reshape(-1, 3)
        sec = sec[sec[:, 0] > 0]
        M["arm_root_y"] = [float(sec[:, 1].min()), float(sec[:, 1].max())]
        M["scye_arc_back"] = self.arc_to_y(armpit, self.f_torso, M["arm_root_y"][1])
        M["scye_arc_front"] = self.arc_to_y(armpit, self.f_torso, M["arm_root_y"][0])
        M["chest_half_arc"] = self.arc_to_y(armpit, self.f_torso, None)
        # chest: max torso girth from the armpit down 8 cm
        zs = np.arange(armpit - 0.08, armpit + 1e-9, 0.005)
        g = [self.girth(z, self.f_torso) for z in zs]
        M["chest_z"], M["chest"] = float(zs[int(np.argmax(g))]), float(max(g))
        # waist: min torso girth between the chest and the pelvis
        zs = np.arange(pel + 0.03, armpit - 0.12, 0.005)
        g = [self.girth(z, self.f_torso) for z in zs]
        M["waist_z"], M["waist"] = float(zs[int(np.argmin(g))]), float(min(g))
        # seat: the level of the buttocks' greatest projection; girth over both
        p = self.profile(0.06, pel, pel - 0.22, +1)
        M["seat_z"] = float(p[int(np.argmax(p[:, 0])), 1])
        M["seat"] = self.girth(M["seat_z"], self.f_trunk)
        M["hip_back_y"] = float(p[:, 0].max())
        # neck base ring, nape, side and front neck points
        nk = J["neck_01"][0]
        nape_z = float(nk[2] - 0.006)
        ring = self.ring(nape_z + 0.012, self.f_neck)
        M["neck"] = perimeter(ring) * 1.02
        M["neck_arc_back"] = 0.5 * self.half_arc(nape_z + 0.012, self.f_neck, +1, 1.0)
        M["neck_arc_front"] = 0.5 * self.half_arc(nape_z + 0.012, self.f_neck, -1, 1.0)
        back = self.profile(0.002, nape_z + 0.004, nape_z - 0.004, +1, fmask=self.f_torso | self.f_neck)
        M["nape"] = [0.0, float(back[:, 0].max()), nape_z]
        np_x = float(ring[:, 0].max())
        s = self.sec(0, np_x, self.f_torso | self.f_neck).reshape(-1, 3)
        q = s[np.abs(s[:, 2] - nape_z) < 0.01]
        M["neck_point"] = [np_x, float(0.5 * (q[:, 1].min() + q[:, 1].max())) if len(q) else float(nk[1]),
                           nape_z - 0.004]
        fr = self.profile(0.002, J["clavicle_l"][0][2] + 0.004, J["clavicle_l"][0][2] - 0.004, -1,
                          fmask=self.f_torso)
        M["front_neck"] = [0.0, float(fr[:, 0].min()), float(J["clavicle_l"][0][2])]
        # shoulder point: top of the shoulder 1.5 cm outside the joint
        ua = J["upperarm_l"][0]
        s = self.sec(0, ua[0] + 0.015).reshape(-1, 3)
        s = s[np.abs(s[:, 1] - ua[1]) < 0.03]
        top = s[np.argmax(s[:, 2])]
        M["acromion"] = top.tolist()
        # lateral extent of the shoulder (deltoid) at the shoulder line - 4 cm
        s = self.sec(2, top[2] - 0.04).reshape(-1, 3)
        M["shoulder_lateral_x"] = float(s[:, 0].max())
        s = self.co[(self.co[:, 2] > armpit) & (self.co[:, 2] < top[2])]
        M["bideltoid"] = float(s[:, 0].max() - s[:, 0].min())
        # across back / chest at mid scye, between the arm creases
        zm = 0.5 * (armpit + top[2])
        M["across_z"] = float(zm)
        M["across_back"] = self.half_arc(zm, self.f_torso, +1, xt - 0.005)
        M["across_chest"] = self.half_arc(zm, self.f_torso, -1, xt - 0.02)
        # lengths
        M["nape_to_waist"], _ = self.tape(0.002, nape_z, M["waist_z"], +1)
        M["scye_depth"] = float(nape_z - armpit)
        M["nape_height"] = nape_z - float(self.co[:, 2].min())
        npz = M["neck_point"][2]
        M["front_np_to_chest"], _ = self.tape(np_x * 1.1, npz, M["chest_z"], -1, self.f_torso)
        M["back_np_to_chest"], _ = self.tape(np_x * 1.1, npz, M["chest_z"], +1, self.f_torso)
        M["front_np_to_waist"], _ = self.tape(np_x * 1.1, npz, M["waist_z"], -1, self.f_torso)
        M["back_np_to_waist"], _ = self.tape(np_x * 1.1, npz, M["waist_z"], +1, self.f_torso)
        # arm
        el, wr = J["lowerarm_l"][0], J["hand_l"][0]
        M["upperarm_len"] = float(np.linalg.norm(el - top))
        M["forearm_len"] = float(np.linalg.norm(wr - el))
        M["elbow_bend_deg"] = float(np.degrees(np.arccos(np.clip(np.dot(
            (el - ua) / np.linalg.norm(el - ua), (wr - el) / np.linalg.norm(wr - el)), -1, 1))))
        M["sleeve_length"] = M["upperarm_len"] + M["forearm_len"]
        u = (el - ua) / np.linalg.norm(el - ua)
        M["bicep"] = self._limb_girth(ua + (el - ua) * 0.35, u)
        f = (wr - el) / np.linalg.norm(wr - el)
        M["wrist"] = self._limb_girth(el + (wr - el) * 0.95, f)
        M["stature"] = float(self.co[:, 2].max() - self.co[:, 2].min())
        M["floor_z"] = float(self.co[:, 2].min())
        return M

    def _limb_girth(self, c, u):
        """Girth of the left arm in the plane through c normal to u."""
        p = self.co[self.tris] - c                 # (T, 3, 3)
        d = p @ u
        cross = (d.min(1) < 0) & (d.max(1) > 0) & (np.linalg.norm(p.mean(1), axis=1) < 0.12)
        pts = []
        for tri, dd in zip(p[cross], d[cross]):
            for a, b in ((0, 1), (1, 2), (2, 0)):
                if (dd[a] < 0) != (dd[b] < 0):
                    t = dd[a] / (dd[a] - dd[b])
                    pts.append(tri[a] + (tri[b] - tri[a]) * t)
        pts = np.array(pts)
        a = np.cross(u, [0, 0, 1.0])
        a /= np.linalg.norm(a)
        b = np.cross(u, a)
        q = np.stack([pts @ a, pts @ b], 1)
        return perimeter(_hull(q)) if len(q) >= 3 else 0.0


# --- curves ----------------------------------------------------------------------------------

def merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def bezier(p0, p1, p2, p3, n=24):
    t = np.linspace(0, 1, n)[:, None]
    p0, p1, p2, p3 = (np.asarray(p, float) for p in (p0, p1, p2, p3))
    return (1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t ** 2 * p2 + t ** 3 * p3


def catmull(pts, n=16, alpha=0.5):
    """Centripetal Catmull-Rom spline through pts (open), n samples per span. Uniform
    Catmull-Rom (alpha 0) overshoots and loops where the spacing jumps (a short span at a
    seam end next to a long one); centripetal does not."""
    P = np.asarray(pts, float)
    P = np.vstack([2 * P[0] - P[1], P, 2 * P[-1] - P[-2]])
    out = []
    u = np.linspace(0, 1, n, endpoint=False)[:, None]
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        t0 = 0.0
        t1 = t0 + max(np.linalg.norm(p1 - p0), 1e-9) ** alpha
        t2 = t1 + max(np.linalg.norm(p2 - p1), 1e-9) ** alpha
        t3 = t2 + max(np.linalg.norm(p3 - p2), 1e-9) ** alpha
        t = t1 + (t2 - t1) * u
        a1 = (t1 - t) / (t1 - t0) * p0 + (t - t0) / (t1 - t0) * p1
        a2 = (t2 - t) / (t2 - t1) * p1 + (t - t1) / (t2 - t1) * p2
        a3 = (t3 - t) / (t3 - t2) * p2 + (t - t2) / (t3 - t2) * p3
        b1 = (t2 - t) / (t2 - t0) * a1 + (t - t0) / (t2 - t0) * a2
        b2 = (t3 - t) / (t3 - t1) * a2 + (t - t1) / (t3 - t1) * a3
        out.append((t2 - t) / (t2 - t1) * b1 + (t - t1) / (t2 - t1) * b2)
    out.append(P[-2][None])
    return np.vstack(out)


def cum_len(p):
    return np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(p, axis=0), axis=1))])


def arclen(p):
    return float(cum_len(p)[-1])


def at_params(p, ts):
    """Points at normalised arc-length parameters ts along polyline p."""
    L = cum_len(p)
    s = np.asarray(ts) * L[-1]
    return np.stack([np.interp(s, L, p[:, k]) for k in range(p.shape[1])], 1)


def join(*parts):
    out = [np.asarray(parts[0], float)]
    for q in parts[1:]:
        q = np.asarray(q, float)
        out.append(q[1:] if np.linalg.norm(q[0] - out[-1][-1]) < 1e-6 else q)
    return np.vstack(out)


def split_at(p, t):
    """Split polyline p at normalised arc parameter t -> (head, tail)."""
    L = cum_len(p)
    s = t * L[-1]
    i = int(np.searchsorted(L, s))
    q = at_params(p, [t])[0]
    return np.vstack([p[:i], q]), np.vstack([q, p[i:]])


def seg_intersect(a, b, p):
    """First intersection of segment a-b (extended both ways) with polyline p:
    (point, parameter along p)."""
    d = b - a
    L = cum_len(p)
    for i in range(len(p) - 1):
        e = p[i + 1] - p[i]
        den = d[0] * e[1] - d[1] * e[0]
        if abs(den) < 1e-12:
            continue
        w = p[i] - a
        s = (w[0] * e[1] - w[1] * e[0]) / den
        u = (w[0] * d[1] - w[1] * d[0]) / den
        if 0 <= u <= 1:
            return a + d * s, (L[i] + u * (L[i + 1] - L[i])) / L[-1]
    return None, None


def smoothstep(t):
    t = np.clip(t, 0, 1)
    return t * t * (3 - 2 * t)


# --- panels and seams ------------------------------------------------------------------------

class Panel:
    """A closed outline of named edges (each an open polyline, cm, in order,
    end of one = start of the next), internal lines and notches."""

    def __init__(self, name, edges, lines=None, notches=None, mirror=True, kind=None, inner=None):
        self.name = name
        self.edges = [(n, np.asarray(p, float)) for n, p in edges]
        # inner edges: open polylines inside the panel that are sewn (a dart's two legs); the
        # mesher cuts out what lies between a dart's legs
        self.inner = {n: np.asarray(p, float) for n, p in (inner or {}).items()}
        self.lines = {k: np.asarray(v, float) for k, v in (lines or {}).items()}
        self.notches = {k: np.asarray(v, float) for k, v in (notches or {}).items()}
        self.mirror = mirror
        self.kind = kind or name
        for (n0, a), (n1, b) in zip(self.edges, self.edges[1:] + self.edges[:1]):
            if np.linalg.norm(a[-1] - b[0]) > 1e-4:
                raise ValueError(f"{name}: edge {n0} does not meet {n1} ({a[-1]} vs {b[0]})")

    def edge(self, n):
        if n in self.inner:
            return self.inner[n]
        return next(p for k, p in self.edges if k == n)

    def dart_holes(self):
        """Closed polygons between each dart's legs (<name>_b and <name>_f, bottom to top)."""
        out = []
        for n in self.inner:
            if n.endswith("_b") and n[:-2] + "_f" in self.inner:
                out.append(join(self.inner[n], self.inner[n[:-2] + "_f"][::-1]))
        return out

    def outline(self):
        return join(*[p for _, p in self.edges])[:-1]

    def area(self):
        p = self.outline()
        return 0.5 * abs(np.dot(p[:, 0], np.roll(p[:, 1], -1)) - np.dot(p[:, 1], np.roll(p[:, 0], -1)))


class Draft:
    def __init__(self, panels, seams, frame, anchors, opts):
        self.panels = {p.name: p for p in panels}
        # the right half: "<name>_r" panels share the left's flat geometry (the
        # runner mirrors them in 3D); a seam not marked mirror=False is doubled
        self.names = []
        for p in panels:
            self.names += [p.name, p.name + "_r"] if p.mirror else [p.name]
        self.seams = []             # [{"name", "a": [(panel, edge, rev)], "b": [...]}]
        for s in seams:
            self.seams.append(s)
            if s.get("mirror", True):
                r = lambda ch: [(p + "_r", e, rev) for p, e, rev in ch]
                self.seams.append({"name": s["name"] + "_r", "a": r(s["a"]), "b": r(s["b"])})
        self.frame = frame
        self.anchors = anchors      # {name: (panel, xy cm)}
        self.opts = opts

    def geom(self, name):
        return self.panels[name[:-2] if name.endswith("_r") and name not in self.panels else name]

    def chain(self, ch):
        """Polylines of a chain in chain direction, and the corner params."""
        polys = [self.geom(p).edge(e)[::-1] if rev else self.geom(p).edge(e) for p, e, rev in ch]
        Ls = np.array([arclen(q) for q in polys])
        corners = np.concatenate([[0], np.cumsum(Ls)]) / Ls.sum()
        return polys, corners, float(Ls.sum())

    def seam_lengths(self):
        out = {}
        for s in self.seams:
            out[s["name"]] = (round(self.chain(s["a"])[2], 2), round(self.chain(s["b"])[2], 2))
        return out

    def sample(self, h):
        """Sample every edge at spacing ~h (cm). Edges in a seam are sampled at
        the same normalised parameters on both sides, corners of either side
        included, so their samples pair one to one.

        Returns (pts, pairs): pts {(panel, edge): (k, 2) cm, edge direction};
        pairs [(seam, [((panel, edge, i), (panel, edge, j)), ...])]."""
        pts, pairs = {}, []
        for s in self.seams:
            (pa, ca, La), (pb, cb, Lb) = self.chain(s["a"]), self.chain(s["b"])
            n = max(2, int(math.ceil(max(La, Lb) / h)))
            g = self.ease_map(s, La, Lb)          # t on a -> t on b
            cb_a = np.interp(cb, g[1], g[0])     # b's corners in a's parameter
            ts = list(np.linspace(0, 1, n + 1))
            for c in list(ca) + list(cb_a):
                ts.append(float(c))
            ts = np.array(sorted(ts))
            keep = [ts[0]]
            corner = set(np.round(np.concatenate([ca, cb_a]), 9))
            for t in ts[1:]:
                if t - keep[-1] < 0.35 / n:
                    if round(t, 9) in corner:
                        keep[-1] = t
                    continue
                keep.append(t)
            ts = np.array(keep)
            idx = {}
            tb = np.interp(ts, g[0], g[1])
            for c_ in cb:                        # b's corners land exactly
                j = int(np.argmin(np.abs(tb - c_)))
                if abs(tb[j] - c_) < 1e-6:
                    tb[j] = c_
            for side, (polys, corners, ch, tt) in (("a", (pa, ca, s["a"], ts)), ("b", (pb, cb, s["b"], tb))):
                for k, (poly, (p, e, rev)) in enumerate(zip(polys, ch)):
                    t0, t1 = corners[k], corners[k + 1]
                    sel = (tt >= t0 - 1e-9) & (tt <= t1 + 1e-9)
                    loc = np.clip((tt[sel] - t0) / max(t1 - t0, 1e-12), 0, 1)
                    q = at_params(poly, loc)
                    gi = np.nonzero(sel)[0]
                    if rev:
                        q, gi = q[::-1], gi[::-1]
                    pts[(p, e)] = q
                    for j, g in enumerate(gi):
                        idx.setdefault((side, int(g)), []).append((p, e, j))
            pr = []
            for g in range(len(ts)):
                for A in idx.get(("a", g), []):
                    for B in idx.get(("b", g), []):
                        pr.append((A, B))
            pairs.append((s["name"], pr))
        for name in self.names:
            for e, poly in self.geom(name).edges:
                if (name, e) not in pts:
                    n = max(1, int(math.ceil(arclen(poly) / h)))
                    pts[(name, e)] = at_params(poly, np.linspace(0, 1, n + 1))
        return pts, pairs

    @staticmethod
    def ease_map(s, La, Lb):
        """The seam's pairing: (t_a, t_b) knots, both 0..1. Even (t_b = t_a) unless the seam
        names an ease zone: s["ease_zero"] = (ta0, ta1) is sewn 1:1 (the sleeve's underarm, as
        a tailor sews it), and the rest of b's extra length goes in as a smooth bump that is
        largest at the chain's ends (the crown) and nothing at the zone's edges."""
        t = np.linspace(0, 1, 2001)
        if "ease_zero" not in s or Lb <= La:
            return t, t
        a0, a1 = s["ease_zero"]
        w = np.zeros_like(t)
        m0 = t < a0
        w[m0] = 1 - smoothstep(t[m0] / max(a0, 1e-9))
        m1 = t > a1
        w[m1] = smoothstep((t[m1] - a1) / max(1 - a1, 1e-9))
        W = np.concatenate([[0], np.cumsum(0.5 * (w[1:] + w[:-1]) * np.diff(t))])
        sb = t * La + (Lb - La) * W / max(W[-1], 1e-12)
        return t, sb / Lb

    def svg(self, path, h=None):
        """The pattern sheet: sew lines, seam allowance, roll lines, notches."""
        sa = self.opts["seam_allowance_cm"]
        items = []
        boxes = []
        for p in self.panels.values():
            o = p.outline()
            lo, hi = o.min(0), o.max(0)
            boxes.append((p, lo, hi))
        cur, rowh, y0 = 2.0, 0.0, 2.0
        place = {}
        for p, lo, hi in boxes:
            w, hh = hi - lo + 2 * sa + 3
            if cur + w > 200:
                cur, y0, rowh = 2.0, y0 + rowh, 0.0
            place[p.name] = (cur - lo[0] + sa + 1.5, y0 - lo[1] + sa + 1.5)
            cur += w
            rowh = max(rowh, hh)
        H = y0 + rowh + 2
        for p in self.panels.values():
            dx, dy = place[p.name]
            o = p.outline() + (dx, dy)
            items.append('<polygon points="%s" fill="#f4efe6" stroke="#222" stroke-width="0.15"/>'
                         % " ".join(f"{a:.2f},{b:.2f}" for a, b in o))
            off = _offset(p.outline(), sa) + (dx, dy)
            items.append('<polygon points="%s" fill="none" stroke="#888" stroke-width="0.08" '
                         'stroke-dasharray="0.6,0.4"/>' % " ".join(f"{a:.2f},{b:.2f}" for a, b in off))
            for k, l in p.lines.items():
                q = l + (dx, dy)
                items.append('<polyline points="%s" fill="none" stroke="#b33" stroke-width="0.12" '
                             'stroke-dasharray="1,0.5"/>' % " ".join(f"{a:.2f},{b:.2f}" for a, b in q))
            for k, v in p.notches.items():
                v = np.atleast_2d(v)
                if len(v) == 2 and k in ("hip_pocket", "breast_welt", "buttonhole"):
                    # a pocket mouth / buttonhole: the line itself
                    items.append('<polyline points="%s" fill="none" stroke="#36c" stroke-width="0.25"/>'
                                 % " ".join(f"{a_ + dx:.2f},{b_ + dy:.2f}" for a_, b_ in v))
                    continue
                for q in v:
                    items.append(f'<circle cx="{q[0] + dx:.2f}" cy="{q[1] + dy:.2f}" r="0.45" fill="#36c"/>')
            for k, l in p.inner.items():
                q = l + (dx, dy)
                items.append('<polyline points="%s" fill="none" stroke="#222" stroke-width="0.12"/>'
                             % " ".join(f"{a_:.2f},{b_:.2f}" for a_, b_ in q))
            c = p.outline().mean(0) + (dx, dy)
            items.append(f'<text x="{c[0]:.1f}" y="{c[1]:.1f}" font-size="2.2" text-anchor="middle" '
                         f'font-family="sans-serif">{p.name}</text>')
            items.append(f'<text x="{c[0]:.1f}" y="{c[1] + 2.6:.1f}" font-size="1.4" text-anchor="middle" '
                         f'font-family="sans-serif">{p.area() / 1e4:.3f} m2{" x2" if p.mirror else ""}</text>')
        with open(path, "w") as f:
            f.write(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 204 {H:.1f}" '
                    f'width="{204 * 6}" height="{H * 6:.0f}"><rect width="204" height="{H:.1f}" fill="#fff"/>'
                    + "".join(items) + "</svg>")


def _offset(poly, d):
    """Outward offset of a closed polygon by d (miter, clamped)."""
    p = np.asarray(poly, float)
    area = 0.5 * (np.dot(p[:, 0], np.roll(p[:, 1], -1)) - np.dot(p[:, 1], np.roll(p[:, 0], -1)))
    s = 1.0 if area > 0 else -1.0
    e0 = p - np.roll(p, 1, axis=0)
    e1 = np.roll(p, -1, axis=0) - p
    n0 = np.stack([e0[:, 1], -e0[:, 0]], 1) * s
    n1 = np.stack([e1[:, 1], -e1[:, 0]], 1) * s
    n0 /= np.maximum(np.linalg.norm(n0, axis=1, keepdims=True), 1e-9)
    n1 /= np.maximum(np.linalg.norm(n1, axis=1, keepdims=True), 1e-9)
    m = n0 + n1
    m /= np.maximum(np.linalg.norm(m, axis=1, keepdims=True), 1e-9)
    cosh = np.maximum(np.einsum("ij,ij->i", m, n1), 0.5)
    return p + m * (d / cosh)[:, None]


# --- the draft -------------------------------------------------------------------------------

def draft(M, opts=None):
    """Aldrich-style lounge jacket block from the measurements M (metres, from
    BodyMeasure.run). Returns a Draft (panels in cm, the wearer's left half;
    the collar whole)."""
    o = merge(DEFAULTS, opts)
    E = o["ease"]
    cm = 100.0
    C, W, S = M["chest"] * cm, M["waist"] * cm, M["seat"] * cm
    Zn, Zc, Zw, Zs = M["nape"][2] * cm, M["chest_z"] * cm, M["waist_z"] * cm, M["seat_z"] * cm
    Znp = M["neck_point"][2] * cm
    Zh = Zn - o["length_frac"] * M["nape_height"] * cm
    Gc = C / 2 + E["chest"] / 2
    Gw = max(W + E["waist"], o["waist_min_frac"] * (C + E["chest"])) / 2
    Gs = max(S + E["seat"], 2 * Gw) / 2
    Gh = Gs + o["hem_flare_cm"]
    sig = Gc / (M["chest_half_arc"] * cm)

    # levels: below the chest line block y is the vertical drop; above it the
    # back and the front are stretched by their tape/drop ratio (the chest and
    # the blades are curved), so a panel is long enough to go over them
    Yc = Zn - Zc
    kb = M["back_np_to_chest"] * cm / (Znp - Zc)
    kf = M["front_np_to_chest"] * cm / (Znp - Zc)

    def y_low(z):
        return Yc + (Zc - z)

    def y_back(z):
        return Yc - (z - Zc) * kb

    def y_front(z):
        return Yc - (z - Zc) * kf

    ysc = Yc + o["scye_below_armpit_cm"]
    yw, ys, yh = y_low(Zw), y_low(Zs), y_low(Zh)

    # chest line: armhole from the arm root's back and front on the chest ring
    x_bp = sig * M["scye_arc_back"] * cm - o["scye_ease_cm"]
    x_fp = sig * M["scye_arc_front"] * cm + o["scye_ease_cm"]
    xm, hw, e = 0.5 * (x_bp + x_fp), 0.5 * (x_fp - x_bp), o["scye_rise_cm"]

    def lower_scye(t0, t1, n=24):
        t = np.linspace(t0, t1, n)
        return np.stack([xm - hw * np.cos(t), ysc - e * (1 - np.sin(t))], 1)

    x_bs = x_bp - 1.0
    x_sf = x_fp - o["side_front_frac"] * (x_fp - x_bp)
    t_sf = math.acos(np.clip((xm - x_sf) / hw, -1, 1))
    P_bs = np.array([x_bp, ysc - e])
    x_b = x_bp + o["back_scye_frac"] * (x_fp - x_bp)
    t_bs = math.acos(np.clip((xm - x_b) / hw, -1, 1))
    P_b = lower_scye(t_bs, t_bs, 1)[0]          # the back/side seam on the armhole
    tb = np.array([hw * math.sin(t_bs), e * math.cos(t_bs)])
    tb /= np.linalg.norm(tb)
    P_b2 = P_b + np.array([-tb[1], tb[0]]) * 2.0   # the seam leaves square to the armhole
    P_sf = lower_scye(t_sf, t_sf, 1)[0]
    P_fe = np.array([x_fp, ysc - e])

    # suppression (each seam: d total, half off each side)
    sup = o["suppression"]
    tw = Gc - Gw
    cbw, bsw, sfw = sup["cb"] * tw, sup["back_side"] * tw, sup["side_front"] * tw
    cbs = o["cb_seat_frac"] * cbw
    share = sup["back_side"] / (sup["back_side"] + sup["side_front"])
    ts_, th_ = Gc - Gs - cbs, Gc - Gh - cbs
    bss, sfs, bsh, sfh = share * ts_, (1 - share) * ts_, share * th_, (1 - share) * th_

    # neck and shoulder (3D: the jacket neck point rides rise above the nape;
    # the shoulder point is out past the acromion, up on the pad, down by the drop)
    rb = o["back_neck_rise_cm"]
    Znpj = Zn + rb
    ac = np.array(M["acromion"]) * cm
    npt = np.array(M["neck_point"]) * cm
    npt[0] += o["np_out_cm"]                 # the jacket's neck point, outside the shirt collar
    sp3 = ac + np.array([o["shoulder_out_cm"], 0, 0])
    sh_len3 = math.hypot(sp3[0] - npt[0], sp3[1] - npt[1])
    sp3[2] += o["pad_cm"] - math.tan(math.radians(o["shoulder_drop_deg"])) * sh_len3
    np3 = np.array([npt[0], npt[1], Znpj])
    Ls = 1.02 * float(np.linalg.norm(sp3 - np3))
    Lsb = Ls + o["back_shoulder_ease_cm"]

    # the jacket neckline round the eased neck: a quarter ellipse each side,
    # lateral semi-axis to the jacket neck point, back/front semi-axes to the
    # nape and the front neck (Ramanujan's perimeter)
    cy = 0.5 * (M["nape"][1] + M["front_neck"][1]) * cm

    def quarter(a, b):
        h = ((a - b) / (a + b)) ** 2
        return 0.25 * math.pi * (a + b) * (1 + 3 * h / (10 + math.sqrt(4 - 3 * h)))

    nb = o["neck_scale"] * quarter(npt[0], M["nape"][1] * cm - cy + 0.8)
    nf = o["neck_scale"] * quarter(npt[0], cy - M["front_neck"][1] * cm + 0.8)
    NPb = np.array([nb, y_back(Znpj)])
    nape = np.array([0.0, y_back(Zn)])
    y_spb = y_back(sp3[2])
    SPb = np.array([nb + math.sqrt(max(Lsb ** 2 - (y_spb - NPb[1]) ** 2, 1.0)), y_spb])
    x_npf = Gc - 0.8 * nf
    NPf = np.array([x_npf, y_front(Znpj)])
    y_spf = y_front(sp3[2])
    SPf = np.array([x_npf - math.sqrt(max(Ls ** 2 - (y_spf - NPf[1]) ** 2, 1.0)), y_spf])

    # --- back
    neck_b = bezier(nape, nape + (nb * 0.45, 0), NPb + (-nb * 0.1, (nape[1] - NPb[1]) * 0.7), NPb)
    shoulder_b = np.stack([np.linspace(NPb[0], SPb[0], 12), np.linspace(NPb[1], SPb[1], 12)], 1)
    arm_b = bezier(SPb, SPb + (-0.6, 0.35 * (P_bs[1] - SPb[1])), (x_bp, P_bs[1] - 4.0), P_bs)
    arm_b = join(arm_b, lower_scye(0.0, t_bs)) if t_bs > 1e-6 else arm_b
    side_b = catmull([P_b, P_b2, (x_bs, ysc + 2.0), (x_bs - bsw / 2, yw), (x_bs - bss / 2, ys), (x_bs - bsh / 2, yh)])
    hem_b = np.array([[x_bs - bsh / 2, yh], [cbs, yh]])
    cb = catmull([(cbs, yh), (cbs, ys), (cbw, yw), (0.35 * cbw, Yc), (0.0, (Yc + nape[1]) / 2), nape])
    back = Panel("back", [("neck", neck_b), ("shoulder", shoulder_b), ("armhole", arm_b), ("side", side_b),
                          ("hem", hem_b), ("cb", cb)],
                 notches={"waist_cb": (cbw, yw), "back_pitch": (x_bp, P_bs[1] - 4.0)})

    # --- side body
    scye_s = lower_scye(t_bs, t_sf)
    front_s = catmull([P_sf, (x_sf, ysc + 1.0), (x_sf - sfw / 2, yw), (x_sf - sfs / 2, ys), (x_sf - sfh / 2, yh)])
    hem_s = np.array([[x_sf - sfh / 2, yh], [x_bs + bsh / 2, yh]])
    back_s = catmull([(x_bs + bsh / 2, yh), (x_bs + bss / 2, ys), (x_bs + bsw / 2, yw), (x_bs, ysc + 2.0), P_b2, P_b])
    side = Panel("side", [("scye", scye_s), ("front", front_s), ("hem", hem_s), ("back", back_s)],
                 notches={"waist": (x_sf - sfw / 2, yw)})

    # --- front
    ext = o["button_ext_cm"]
    y_btn = yw + o["button_below_waist_cm"]
    B = np.array([Gc + ext, y_btn])
    Hf = np.array([Gc - o["front_hem_in_cm"], yh])
    side_f = catmull([P_sf, (x_sf, ysc + 1.0), (x_sf + sfw / 2, yw), (x_sf + sfs / 2, ys), (x_sf + sfh / 2, yh)])
    hem_f = np.array([[x_sf + sfh / 2, yh], Hf])
    # the front quarters: straight down from the button, then a rounded cutaway to the hem
    cu = o["cutaway"]
    a_h = math.radians(cu["hem_angle_deg"])
    L1 = 0.4 * float(np.linalg.norm(B - Hf))
    front_e = bezier(Hf, Hf + L1 * np.array([math.cos(a_h), -math.sin(a_h)]), (Gc + ext, y_btn + cu["straight_cm"]), B)
    sh_dir = (NPf - SPf) / np.linalg.norm(NPf - SPf)
    R0 = NPf + sh_dir * o["roll_past_np_cm"]
    t_r = (R0 - B) / np.linalg.norm(R0 - B)                     # up the roll line
    n_r = np.array([t_r[1], -t_r[0]])                           # its normal ...
    if n_r[0] < 0:                                              # ... toward the lapel side (+x)
        n_r = -n_r
    y_G = NPf[1] + o["gorge_drop_cm"]
    s_G = (y_G - B[1]) / t_r[1]
    G = B + t_r * s_G + n_r * o["gorge_past_roll_cm"]
    L_pt = B + t_r * (s_G - 1.5) + n_r * o["lapel_width_cm"]
    bel = o["lapel_belly_cm"]
    lapel = bezier(B, B + (L_pt - B) * 0.33 + n_r * bel, B + (L_pt - B) * 0.7 + n_r * bel, L_pt)
    lapel_top = np.stack([np.linspace(L_pt[0], G[0], 6), np.linspace(L_pt[1], G[1], 6)], 1)
    gorge = np.stack([np.linspace(G[0], NPf[0], 10), np.linspace(G[1], NPf[1], 10)], 1)
    shoulder_f = np.stack([np.linspace(NPf[0], SPf[0], 12), np.linspace(NPf[1], SPf[1], 12)], 1)
    arm_fu = bezier(SPf, SPf + (0.8, 0.35 * (P_fe[1] - SPf[1])), (x_fp, P_fe[1] - 4.0), P_fe)
    arm_fl = lower_scye(math.pi, t_sf)
    arm_f = join(arm_fu, arm_fl)
    t_fp = arclen(arm_fu) * 0.62 / arclen(arm_f)
    arm_fu, arm_fl = split_at(arm_f, t_fp)
    Rg, t_rg = seg_intersect(B, R0, gorge)
    # front dart: a fisheye from below the chest to the hip pocket line
    fd = o["front_dart"]
    w_d = sup.get("front_dart", 0.0) * tw
    inner_f = {}
    if w_d > 1e-3:
        x_d = x_sf + fd["x_frac"] * (Gc - x_sf)
        y_t, y_b = Yc + fd["top_below_chest_cm"], yw + fd["pocket_below_waist_cm"]
        yy = np.linspace(y_b, y_t, 33)
        hwd = np.where(yy >= yw, np.sin(0.5 * np.pi * np.clip((y_b - yy) / (y_b - yw), 0, 1)),
                       np.sin(0.5 * np.pi * np.clip((yy - y_t) / (yw - y_t), 0, 1))) * w_d / 2
        inner_f = {"dart_b": np.stack([x_d - hwd, yy], 1), "dart_f": np.stack([x_d + hwd, yy], 1)}
    # pockets and the buttonhole (pattern marks: the runner builds them on the drape)
    dt = o["details"]
    x_dl = x_sf + fd["x_frac"] * (Gc - x_sf)
    y_p = yw + fd["pocket_below_waist_cm"]
    hp = dt["hip_pocket"]
    x_pf = x_dl + hp["front_past_dart_cm"]
    x_side = float(np.interp(y_p, side_f[:, 1], side_f[:, 0]))
    x_pb = max(x_pf - hp["width_cm"], x_side + hp["side_clear_cm"])
    bw = dt["breast_welt"]
    x_wf = x_dl + bw["front_past_dart_cm"]
    x_wb = x_wf - bw["width_cm"]
    y_wf = Yc + bw["below_chest_cm"]
    bh = dt["buttonhole"]
    x_eye = Gc + bh["eye_past_cf_cm"]
    marks = {"hip_pocket": [(x_pb, y_p), (x_pf, y_p)],
             "breast_welt": [(x_wb, y_wf - bw["rise_cm"]), (x_wf, y_wf)],
             "buttonhole": [(x_eye, y_btn), (x_eye - bh["length_cm"], y_btn)]}
    lapel_panels = []
    if o.get("split_lapel"):
        # spike 2: the lapel is not simulated. The front ends at the roll line (break -> where
        # the roll line crosses the gorge); the lapel is its own panel on the other side, and
        # the modelled rever (collar + lapel) is built on the draped front's roll edge.
        g_lap, g_body = split_at(gorge, t_rg)
        roll_e = np.stack([np.linspace(B[0], Rg[0], 16), np.linspace(B[1], Rg[1], 16)], 1)
        front = Panel("front", [("side", side_f), ("hem", hem_f), ("front", front_e), ("roll", roll_e),
                                ("gorge", g_body), ("shoulder", shoulder_f),
                                ("armhole_upper", arm_fu), ("armhole_lower", arm_fl)],
                      notches={"button": (Gc, y_btn), "break": B, "front_pitch": arm_fu[-1], **marks},
                      inner=inner_f)
        lapel_panels = [Panel("lapel", [("roll", roll_e[::-1]), ("lapel", lapel), ("lapel_top", lapel_top),
                                        ("gorge", g_lap)])]
    else:
        front = Panel("front", [("side", side_f), ("hem", hem_f), ("front", front_e), ("lapel", lapel),
                                ("lapel_top", lapel_top), ("gorge", gorge), ("shoulder", shoulder_f),
                                ("armhole_upper", arm_fu), ("armhole_lower", arm_fl)],
                      lines={"roll": np.array([B, Rg])},
                      notches={"button": (Gc, y_btn), "break": B, "front_pitch": arm_fu[-1]})

    # --- undercollar (whole; CB at u = 0)
    Co = o["collar"]
    Ln = arclen(neck_b) + arclen(gorge)
    w0 = Co["stand_cm"] + Co["fall_cm"]
    Rn = w0 / (Co["spread"] - 1.0)

    def collar_pts(s, off):
        phi = s / Rn
        c = np.array([0.0, Rn])
        p = np.stack([Rn * np.sin(phi), Rn - Rn * np.cos(phi)], -1)
        out = (p - c) / Rn
        return p + out * off[..., None] if np.ndim(off) else p + out * off

    s = np.linspace(0, Ln, 24)
    width = w0 + (Co["end_width_cm"] - w0) * smoothstep(s / Ln)
    stand = Co["stand_cm"] + (o["roll_past_np_cm"] - Co["stand_cm"]) * (s / Ln)
    neck_l = collar_pts(s, np.zeros_like(s))
    outer_l = collar_pts(s, width)
    roll_l = collar_pts(s, stand)
    mir = np.array([-1.0, 1.0])
    np_c = collar_pts(np.array([arclen(neck_b)]), np.zeros(1))[0]
    collar = Panel("collar", [("neck_l", neck_l), ("end_l", np.array([neck_l[-1], outer_l[-1]])),
                              ("outer_l", outer_l[::-1]), ("outer_r", outer_l * mir),
                              ("end_r", np.array([outer_l[-1], neck_l[-1]]) * mir),
                              ("neck_r", (neck_l * mir)[::-1])],
                   lines={"roll": join((roll_l * mir)[::-1], roll_l)}, mirror=False,
                   notches={"np_l": np_c, "np_r": np_c * mir})

    # --- two-piece sleeve (u round the arm, 0 = top, + forward; v down from the crown)
    Sv = o["sleeve"]
    AH = arclen(arm_b) + arclen(scye_s) + arclen(arm_f)
    Wb = M["bicep"] * cm + E["bicep"]
    Wc = M["wrist"] * cm + E["cuff"]
    We = 0.5 * (Wb + Wc) + Sv.get("elbow_extra_cm", 1.0)
    up = M["upperarm_len"] * cm + o["shoulder_out_cm"]
    SL = up + M["forearm_len"] * cm - Sv["end_above_wrist_cm"]
    uc = 1.0

    def cap_v(u, hcap):
        tau = np.where(u >= uc, (u - uc) / (Wb / 2 - uc), (uc - u) / (Wb / 2 + uc))
        return hcap * 0.5 * (1 - np.cos(np.pi * np.clip(tau, 0, 1)))

    uu = np.linspace(-Wb / 2, Wb / 2, 200)
    lo_, hi_ = 5.0, 30.0
    for _ in range(50):
        hc = 0.5 * (lo_ + hi_)
        Lc = arclen(np.stack([uu, cap_v(uu, hc)], 1))
        if Lc < AH + Sv["head_ease_cm"]:
            lo_ = hc
        else:
            hi_ = hc
    hcap = hc
    v_el = up + 1.0

    def width(v):
        return np.interp(v, [0, hcap, v_el, SL], [Wb, Wb, We, Wc])

    def pitch(v):
        return Sv["pitch_cm"] * smoothstep((v - hcap) / (SL - hcap))

    uf0, uh0 = Wb / 4 + Sv["under_offset_cm"], -Wb / 4 - Sv["hind_offset_cm"]

    def seam_u(u0, v):
        return u0 * width(v) / Wb + pitch(v)

    def cuff_v(u0):
        # one smooth slanted cut round the arm (a sinusoid in the arm's angle): shorter at the
        # front, longer at the back, and no kink where it crosses a seam
        return SL - Sv["cuff_slant_cm"] * np.sin(2 * np.pi * np.asarray(u0, float) / Wb)

    def cuff_line(u0a, u0b, n=40):
        u0 = np.linspace(u0a, u0b, n)
        v = cuff_v(u0)
        return np.stack([u0 * width(v) / Wb + pitch(v), v], 1)

    def bend(P):
        """The sleeve cut for a bent arm: below the elbow every line round the arm is
        shortened by r th cos(angle from the crook): the crook (front, u0 = Wb/4) loses
        r th, the elbow point (back) gains it, the sides keep their length. The same map on
        both panels, so the seams still match."""
        P = np.array(P, float)
        u, v = P[:, 0], P[:, 1]
        u0 = (u - pitch(v)) * Wb / width(v)
        r = We / (2 * np.pi)
        dl = r * math.radians(Sv["bend_deg"]) * np.cos(2 * np.pi * (u0 - Wb / 4) / Wb)
        bz = Sv["bend_zone_cm"]
        P[:, 1] = v - dl * smoothstep((v - (v_el - bz)) / (2 * bz))
        return P

    vf = np.linspace(hcap, float(cuff_v(uf0)), 48)      # each seam ends on the cuff line
    vh = np.linspace(hcap, float(cuff_v(uh0)), 48)
    Hs = np.array([uh0, cap_v(np.array(uh0), hcap)])
    Fs = np.array([uf0, cap_v(np.array(uf0), hcap)])
    crown = np.array([uc, 0.0])
    ub = np.linspace(uh0, uc, 30)
    cap_back = np.stack([ub, cap_v(ub, hcap)], 1)
    uf = np.linspace(uc, uf0, 30)
    cap_front = np.stack([uf, cap_v(uf, hcap)], 1)
    fore_top = join(np.array([Fs]), np.stack([seam_u(uf0, vf), vf], 1))
    fore_top[-1, 1] = cuff_v(uf0)
    hind_top = join(np.array([Hs]), np.stack([seam_u(uh0, vh), vh], 1))
    hind_top[-1, 1] = cuff_v(uh0)
    cuff_top = cuff_line(uf0, uh0)
    fore_top, hind_top, cuff_top = bend(fore_top), bend(hind_top), bend(cuff_top)
    cbo = o["details"]["cuff_buttons"]
    hs = hind_top[::-1]                      # cuff end first
    sh = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(hs, axis=0), axis=1))]
    cuff_btn = []
    for k in range(int(cbo["n"])):
        d = cbo["first_above_cuff_cm"] + k * cbo["diam_cm"]
        q = np.array([np.interp(d, sh, hs[:, 0]), np.interp(d, sh, hs[:, 1])])
        tg = np.array([np.interp(d + 0.5, sh, hs[:, 0]), np.interp(d + 0.5, sh, hs[:, 1])]) - q
        tg /= np.linalg.norm(tg)
        nrm = np.array([tg[1], -tg[0]])
        if nrm[0] < 0:                       # into the top sleeve (+u, toward the fore seam)
            nrm = -nrm
        cuff_btn.append(q + nrm * cbo["from_seam_cm"])
    top = Panel("top_sleeve", [("cap_back", cap_back), ("cap_front", cap_front), ("fore", fore_top),
                               ("cuff", cuff_top), ("hind", hind_top[::-1])],
                notches={"crown": crown, "elbow": (seam_u(uh0, v_el), v_el), "cuff_buttons": cuff_btn})
    # under sleeve in its own u' (u for the front part, u + width for the back part)
    ua = np.linspace(uf0, Wb / 2, 16)
    ubk = np.linspace(-Wb / 2, uh0, 16)
    cap_u = join(np.stack([ua, cap_v(ua, hcap)], 1), np.stack([ubk + Wb, cap_v(ubk, hcap)], 1))
    hind_u = np.stack([seam_u(uh0, vh) + width(vh), vh], 1)
    hind_u = join(np.array([cap_u[-1]]), hind_u)
    hind_u[-1, 1] = cuff_v(uh0)
    fore_u = np.stack([seam_u(uf0, vf), vf], 1)
    fore_u = join(np.array([cap_u[0]]), fore_u)
    fore_u[-1, 1] = cuff_v(uf0)
    cuff_u = cuff_line(uh0 + Wb, uf0)
    hind_u, cuff_u, fore_u = bend(hind_u), bend(cuff_u), bend(fore_u)
    under = Panel("under_sleeve", [("cap", cap_u), ("hind", hind_u), ("cuff", cuff_u), ("fore", fore_u[::-1])])

    panels = [back, side, front, collar, top, under] + lapel_panels
    gorge_l = [("front", "gorge", True)] + ([("lapel", "gorge", True)] if lapel_panels else [])
    gorge_r = [(p + "_r", e, rev) for p, e, rev in gorge_l]
    seams = [
        {"name": "cb", "a": [("back", "cb", False)], "b": [("back_r", "cb", False)], "mirror": False},
        {"name": "shoulder", "a": [("back", "shoulder", False)], "b": [("front", "shoulder", False)]},
        {"name": "back_side", "a": [("back", "side", False)], "b": [("side", "back", True)]},
        {"name": "side_front", "a": [("side", "front", False)], "b": [("front", "side", False)]},
        {"name": "collar_l", "a": [("collar", "neck_l", False)],
         "b": [("back", "neck", False)] + gorge_l, "mirror": False},
        {"name": "collar_r", "a": [("collar", "neck_r", True)],
         "b": [("back_r", "neck", False)] + gorge_r, "mirror": False},
        # the sleeve head round the whole armhole, crown on the shoulder point,
        # the head ease spread evenly
        {"name": "armhole", "a": [("back", "armhole", False), ("side", "scye", False),
                                  ("front", "armhole_lower", True), ("front", "armhole_upper", True)],
         "b": [("top_sleeve", "cap_back", True), ("under_sleeve", "cap", True),
               ("top_sleeve", "cap_front", True)]},
        {"name": "sleeve_fore", "a": [("top_sleeve", "fore", False)], "b": [("under_sleeve", "fore", True)]},
        {"name": "sleeve_hind", "a": [("top_sleeve", "hind", True)], "b": [("under_sleeve", "hind", False)]},
    ]
    if lapel_panels:
        seams.append({"name": "roll", "a": [("front", "roll", False)], "b": [("lapel", "roll", True)]})
    if inner_f:
        seams.append({"name": "front_dart", "a": [("front", "dart_b", False)], "b": [("front", "dart_f", False)]})
    frame = {"Gc": Gc, "Gw": Gw, "Gs": Gs, "Gh": Gh, "Yc": Yc, "Zc": Zc, "Zn": Zn, "Znpj": Znpj, "Zh": Zh,
             "kb": kb, "kf": kf, "ysc": ysc, "yw": yw, "ys": ys, "yh": yh, "y_btn": y_btn, "sigma": sig,
             "x_bp": x_bp, "x_fp": x_fp, "x_bs": x_bs, "x_sf": x_sf, "sp3": sp3.tolist(), "np3": np3.tolist(),
             "neck_back_cm": nb, "neck_front_cm": nf,
             "shoulder_len": Ls, "armhole_len": AH, "sleeve": {"Wb": Wb, "We": We, "Wc": Wc, "hcap": hcap,
                                                               "v_el": v_el, "SL": SL, "uc": uc,
                                                               "uf0": uf0, "uh0": uh0, "up": up}}
    anchors = {"nape": ("back", nape), "np_b": ("back", NPb), "sp_b": ("back", SPb), "np_f": ("front", NPf),
               "sp_f": ("front", SPf), "bpitch": ("back", np.array([x_bp, P_bs[1] - 4.0])),
               "fpitch": ("front", arm_fu[-1]), "p_bs": ("back", P_bs), "p_fe": ("front", P_fe),
               "break": ("front", B), "gorge": ("front", G), "roll_gorge": ("front", Rg),
               "lapel_point": ("front", L_pt), "roll_top": ("front", R0)}
    D = Draft(panels, seams, frame, anchors, o)
    # the sleeve head's ease goes over the crown; the underarm (back pitch -> front pitch)
    # is sewn without ease
    for sm in D.seams:
        if sm["name"].startswith("armhole"):
            polys, corners, La = D.chain(sm["a"])
            P = join(*polys)
            s_ = cum_len(P) / La

            def t_at(q):
                return float(s_[int(np.argmin(np.linalg.norm(P - q, axis=1)))])

            sm["ease_zero"] = (t_at(P_bs), t_at(arm_fu[-1]))
    return D
