"""Shoes: black calf cap-toe derbies on a parametric last (suit_build primitives).

    last     a smooth last fitted to the foot: plan outline (lateral and medial
             half-widths measured from the foot, eased, closed on a superellipse
             toe and a round heel), a designed top line (instep from the foot,
             toe box and rounded nose; the vamp line is the foot's convex
             envelope, so it never dips), a feather line that rises through the
             waist to the heel seat, toe spring; superellipse cross-sections
    upper    rings along the last (V-split at the top so the ankle opening can be
             cut); the toe cap is a second leather layer (a step at the cap seam),
             a back-stay strip over the back seam, a rolled collar lip round the
             topline; the tongue is the upper between the facings, its top the
             round front of the opening. Dress shoes have no heel pull loop: the
             "heel pull" of the brief is read as the back-stay strip
    facings  the derby quarters' lacing flaps, lying on the tongue, with punched
             blind eyelets (in the maps); criss-cross round laces, a bow (two
             loops, two tails)
    sole     welt (with the welt stitch and wheeling in the normal map), sole edge
             with a bevel, a bottom that follows the toe spring and arches through
             the waist, a stacked heel block with a breast and a top lift
    marks    cap seam (double stitched), quarter and counter seams, back-stay
             edges, facing edges, vamp flex creases, welt stitch, heel lifts, in
             the leather maps (suit_textures + suit_leather)

Sizes are parameters (suit.DEFAULTS["shoes"]). Weights come from the foot bones
through the nearest body vertex. One UV layout is shared by both shoes (lateral
and medial sides map to the same texels on the left and the right shoe).
"""

import math
import random

import bmesh
from mathutils import Vector

from . import suit_build as sb
from .suit_build import TAU, lerp, smoothstep

TAG = {"upper": 1, "sole": 2, "lace": 3, "cap": 4, "facing": 5, "bottom": 7,
       "heel": 8, "toplift": 9, "lip": 10, "sole_m": 12}
SOLE_TAGS = {TAG["sole"], TAG["sole_m"], TAG["bottom"], TAG["heel"], TAG["toplift"]}
HALF = math.pi / 2


def _gauss_smooth(vals, sigma):
    n = len(vals)
    r = int(3 * sigma) + 1
    ws = [math.exp(-0.5 * (k / sigma) ** 2) for k in range(-r, r + 1)]
    out = []
    for i in range(n):
        s = w = 0.0
        for k, wk in zip(range(-r, r + 1), ws):
            j = min(n - 1, max(0, i + k))
            s += vals[j] * wk
            w += wk
        out.append(s / w)
    return out


class Last:
    """The shoe's last for one foot. Lateral = +x on the left foot (sgn)."""

    def __init__(self, body, S, side):
        self.S = S
        self.side = side
        self.sgn = 1 if side == "l" else -1
        fv = body.verts({f"foot_{side}", f"ball_{side}"})
        self.z0 = min(v.co.z for v in fv)
        ys = [v.co.y for v in fv]
        self.y_heel, self.y_toe = max(ys), min(ys)
        self.y_hb = self.y_heel + S["heel_ease_m"]
        self.y_tip = self.y_toe - S["toe_ease_m"]
        self.y_ball = body.joint(f"ball_{side}").y
        self.y_breast = self.y_hb - S["heel_len_m"]
        self.y_cap = self.y_tip + S["cap_m"]
        ball = [v.co for v in fv if abs(v.co.y - self.y_ball) < 0.008 and v.co.z < self.z0 + 0.05]
        self.cx0 = 0.5 * (min(p.x for p in ball) + max(p.x for p in ball))
        # measured envelope every 4 mm, heel to toe
        step = 0.004
        self.ys = []
        lat, med, top = [], [], []
        y = self.y_heel
        while y > self.y_toe - 1e-6:
            pts = [v.co for v in fv if abs(v.co.y - y) < 0.006]
            low = [p for p in pts if p.z < self.z0 + 0.05] or pts
            self.ys.append(y)
            lat.append(max(self.sgn * (p.x - self.cx0) for p in low))
            med.append(max(-self.sgn * (p.x - self.cx0) for p in low))
            top.append(min(max(p.z for p in pts), self.z0 + S["max_top_m"]))
            y -= step
        sig = S["smooth_m"] / step
        self.m_lat = _gauss_smooth(lat, sig)
        self.m_med = _gauss_smooth(med, sig)
        self.m_top = _gauss_smooth(top, sig * 0.6)
        self.h_ball = self._meas(self.m_top, self.y_ball) + S["leather_m"] + S["top_ease_m"] - self.zf(self.y_ball)
        self.w_ball = (self._meas(self.m_lat, self.y_ball), self._meas(self.m_med, self.y_ball))
        R = S["heel_r_m"]
        self.w_heel = (self._meas(self.m_lat, self.y_hb - R), self._meas(self.m_med, self.y_hb - R))
        self.y_open = self.y_tip + S["open_m"]
        self.y_throat = self.y_tip + S["throat_m"]
        # the vamp line, cap seam to instep: the upper convex envelope of the raw top
        # (a last's vamp never dips the way the foot's dorsum does), softened
        n = 48
        y_end = self.y_open + 0.02
        ys = [lerp(self.y_cap, y_end, i / (n - 1)) for i in range(n)]
        zs = [self._top_raw(y) for y in ys]
        hull = []
        for i in range(n):
            while len(hull) >= 2:
                (y1, z1), (y2, z2) = (ys[hull[-2]], zs[hull[-2]]), (ys[hull[-1]], zs[hull[-1]])
                if (z2 - z1) * (ys[i] - y1) - (zs[i] - z1) * (y2 - y1) <= 0:
                    hull.pop()
                else:
                    break
            hull.append(i)
        env = []
        for y in ys:
            k = max(j for j in range(len(hull) - 1) if ys[hull[j]] <= y + 1e-12) if len(hull) > 1 else 0
            a, b = hull[k], hull[min(k + 1, len(hull) - 1)]
            t = 0.0 if b == a else (y - ys[a]) / (ys[b] - ys[a])
            env.append(lerp(zs[a], zs[b], t))
        env = _gauss_smooth(env, S["vamp_soft_m"] / (ys[1] - ys[0]))
        self.vamp = (ys, [max(z, e) for z, e in zip(zs, env)])
        # the opening starts just under the ridge, so it widens like a root (round tongue top)
        self.tl_front = self.top(self.y_open) - S["topline"]["front_drop_m"] - self.z0

    def _meas(self, arr, y):
        f = (self.y_heel - y) / 0.004
        if f <= 0:
            return arr[0]
        if f >= len(arr) - 1:
            return arr[-1]
        i = int(f)
        t = f - i
        return arr[i] * (1 - t) + arr[i + 1] * t

    # --- profile functions -------------------------------------------------------------------

    def spring(self, y):
        if y >= self.y_ball:
            return 0.0
        t = (self.y_ball - y) / (self.y_ball - self.y_tip)
        return self.S["toe_spring_m"] * t * t

    def zf(self, y):
        """Feather line (the upper's bottom edge): rises through the waist to the
        heel seat; lifted by the toe spring ahead of the ball."""
        y0 = self.y_ball + self.S["waist_start_m"]
        t = smoothstep((y - y0) / max(self.y_breast - y0, 1e-6))
        return self.z0 + self.S["seat_m"] * t + self.spring(y)

    def z_floor(self):
        S = self.S
        return self.z0 - S["welt_h_m"] - S["sole_m"]

    def widths(self, y):
        """(lateral, medial) half-widths at the feather line and the centre x."""
        S = self.S
        e = S["width_ease_m"] + S["leather_m"]
        R = S["heel_r_m"]
        cx = self.cx0
        if y < self.y_ball:
            t = min(1.0, (self.y_ball - y) / (self.y_ball - self.y_tip))
            pl, pm = S["toe_p_lat"], S["toe_p_med"]
            wl = (self.w_ball[0] + e) * max(0.0, 1 - t ** pl) ** (1 / pl)
            wm = (self.w_ball[1] + e) * max(0.0, 1 - t ** pm) ** (1 / pm)
            cx -= self.sgn * S["toe_shift_m"] * t * t
            return wl, wm, cx
        if y > self.y_hb - R:
            q = min(1.0, (y - (self.y_hb - R)) / R)
            k = math.sqrt(max(0.0, 1 - q ** S["heel_p"])) if q < 1 else 0.0
            return (self.w_heel[0] + e) * k, (self.w_heel[1] + e) * k, cx
        return self._meas(self.m_lat, y) + e, self._meas(self.m_med, y) + e, cx

    def top(self, y):
        """Top line of the upper (absolute z)."""
        ys, zs = self.vamp
        if ys[0] < y < ys[-1]:
            f = (y - ys[0]) / (ys[1] - ys[0])
            i = min(int(f), len(ys) - 2)
            return max(self._top_raw(y), lerp(zs[i], zs[i + 1], f - i))
        return self._top_raw(y)

    def _top_raw(self, y):
        S = self.S
        zf = self.zf(y)
        meas = self._meas(self.m_top, y) + S["leather_m"] + S["top_ease_m"]
        y_lead = self.y_ball + 0.01
        if y < y_lead:
            if y >= self.y_cap:
                s = (y_lead - y) / (y_lead - self.y_cap)
                h = lerp(self.h_ball, S["toe_box_h_m"], smoothstep(s))
            else:
                s = min(1.0, (self.y_cap - y) / (self.y_cap - self.y_tip))
                q = S["nose_p"]
                h = S["toe_box_h_m"] * max(0.0, 1 - s ** q) ** (1 / q)
            return zf + h
        return max(meas, zf + 0.02)

    def point(self, y, a):
        """a in [0, pi]: 0 = lateral feather, pi/2 = top, pi = medial feather."""
        S = self.S
        wl, wm, cx = self.widths(y)
        zf, T = self.zf(y), self.top(y)
        h = max(T - zf, 1e-5)
        lateral = a <= HALF
        c, s = abs(math.cos(a)), math.sin(a)
        p = S["section_p"]
        xr = c ** (2 / p) if c > 1e-12 else 0.0
        zr = s ** (2 / p) if s > 1e-12 else 0.0
        W = (wl if lateral else wm) * (1 - S["section_taper"] * zr ** 2)
        x = cx + (self.sgn if lateral else -self.sgn) * W * xr - self.sgn * S["ridge_shift_m"] * zr ** 2
        z = zf + h * zr
        # heel counter: the back curves forward toward the topline
        R = S["heel_r_m"]
        g = smoothstep((y - (self.y_hb - R)) / R)
        yy = y - S["heel_curve_m"] * g * max(0.0, zr - 0.25) ** 2 / 0.5625
        return Vector((x, yy, z))

    def normal(self, y, a):
        e = 1e-3
        pa = self.point(y, min(math.pi, a + e)) - self.point(y, max(0.0, a - e))
        py = self.point(y - e, a) - self.point(y + e, a)
        n = pa.cross(py) if a <= HALF else py.cross(pa)
        # outward: away from the section centre
        c = Vector((self.widths(y)[2], y, self.zf(y) + 0.3 * (self.top(y) - self.zf(y))))
        n.normalize()
        if n.dot(self.point(y, a) - c) < 0:
            n = -n
        return n

    def half_arc(self, y, lateral, a_end=HALF, n=48):
        """Dense samples (a, point, arc from the feather) of one half ring up to a_end."""
        out, acc, prev = [], 0.0, None
        for j in range(n + 1):
            a = a_end * j / n
            p = self.point(y, a if lateral else math.pi - a)
            if prev is not None:
                acc += (p - prev).length
            out.append((a, p, acc))
            prev = p
        return out

    def at_arc(self, y, s_top, lateral):
        """Angle a (in [0, pi]) at arc distance s_top from the top centre."""
        hs = self.half_arc(y, lateral)
        total = hs[-1][2]
        s = max(0.0, total - s_top)
        for (a0, _, s0), (a1, _, s1) in zip(hs, hs[1:]):
            if s1 >= s:
                t = (s - s0) / max(s1 - s0, 1e-9)
                a = a0 + (a1 - a0) * t
                return a if lateral else math.pi - a
        return HALF

    def a_cut(self, y, lateral):
        """Angle from the feather (0..pi/2) where the half ring meets the topline;
        pi/2 where the ring stays under it."""
        z_tl = self.z_topline(y, lateral)
        if self.top(y) <= z_tl:
            return HALF
        lo, hi = 0.0, HALF
        for _ in range(40):
            mid = 0.5 * (lo + hi)
            z = self.point(y, mid if lateral else math.pi - mid).z
            if z < z_tl:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)

    def z_topline(self, y, lateral):
        S = self.S["topline"]
        if y < self.y_open:
            return 1.0   # in front of the opening: never cut (vamp, tongue)
        t = min(1.0, (y - self.y_open) / max(self.y_hb - self.y_open, 1e-6))
        side = S["side_lat_m"] if lateral else S["side_med_m"]
        tm = S["dip_at"]
        if t < tm:
            # ease out: the topline drops linearly at the tongue, so the opening
            # widens like a root there (a round tongue top, not a V)
            q = t / tm
            z = lerp(self.tl_front, side, 1 - (1 - q) ** 2)
        else:
            z = lerp(side, S["back_m"], smoothstep((t - tm) / (1 - tm)))
        return self.z0 + z


def row_ys(L, S):
    """Rows from the heel back to the toe tip, denser at both ends, with one row
    exactly at the cap seam, one at the opening's front and a full one just ahead
    of it (the tongue top: a round front edge, not a V to the ridge)."""
    n = S["rows"]
    ys = []
    for k in range(n + 1):
        u = k / n
        f = 0.5 * u + 0.5 * (0.5 - 0.5 * math.cos(math.pi * u))
        ys.append(lerp(L.y_hb, L.y_tip, f))
    k_open = min(range(1, n), key=lambda k: abs(ys[k] - L.y_open))
    ys[k_open] = L.y_open + 0.0005
    ys.insert(k_open + 1, L.y_open - S["tongue_row_m"])
    n += 1
    k_cap = min(range(1, n), key=lambda k: abs(ys[k] - L.y_cap))
    ys[k_cap] = L.y_cap
    return ys, k_cap


def orient(faces, inside):
    """Flip a grid's faces when most of them face `inside(centre)` (a point
    inside the shape) rather than away from it."""
    vote = 0.0
    for f in faces:
        f.normal_update()
        c = f.calc_center_median()
        vote += f.normal.dot(c - inside(c)) * f.calc_area()
    if vote < 0:
        for f in faces:
            f.normal_flip()
    return vote < 0


def _resample_half(L, y, lateral, a_end, M):
    """M + 1 points evenly spaced by arc length from the feather to a_end, with
    each point's arc distance s from the feather and the full half-arc length."""
    hs = L.half_arc(y, lateral, a_end)
    full = L.half_arc(y, lateral)[-1][2]
    total = hs[-1][2]
    out = []
    for j in range(M + 1):
        s = total * j / M
        a = hs[-1][0]
        for (a0, _, s0), (a1, _, s1) in zip(hs, hs[1:]):
            if s1 >= s - 1e-12:
                a = a0 + (a1 - a0) * (s - s0) / max(s1 - s0, 1e-12)
                break
        out.append((a if lateral else math.pi - a, s))
    return out, full


def build_shoe(G, body, S, side):
    L = Last(body, S, side)
    first = side == "l"          # marks once: both shoes share one UV layout
    bones = {f"foot_{side}", f"ball_{side}", f"calf_{side}"}
    M = S["half_columns"]
    ys, k_cap = row_ys(L, S)
    up = G.grid(f"upper_{side}")
    open_rows = []
    k_vamp_row = None
    for k, y in enumerate(ys):
        # at the cap seam two rows: the vamp's, then the cap's (a leather step)
        for lift in ((0.0,) if k != k_cap else (0.0, S["cap_step_m"])):
            cap_lift = S["cap_step_m"] if y < L.y_cap - 1e-6 else lift
            cut = (L.a_cut(y, True), L.a_cut(y, False))
            is_open = min(cut) < HALF - 1e-4
            pts, uvs = [], []
            for lateral, a_end in ((True, cut[0]), (False, cut[1])):
                col = []
                samples, full = _resample_half(L, y, lateral, a_end, M)
                for aa, s in samples:
                    p = L.point(y, aa)
                    if cap_lift:
                        p = p + L.normal(y, aa) * cap_lift
                    u = (s - full) if lateral else (full - s)
                    v = L.y_hb - y + (0.0015 if (k == k_cap and lift) else 0.0)
                    col.append((p, (u, v)))
                if not lateral:
                    col.reverse()
                pts += [c[0] for c in col]
                uvs += [c[1] for c in col]
            verts = [G.bm.verts.new(p) for p in pts]
            if not is_open:   # front rows: the two halves meet at the top (one vertex)
                G.bm.verts.remove(verts[M + 1])
                verts[M + 1] = verts[M]
            up.add_shared_row(verts, uvs)
            if is_open:
                open_rows.append(len(up.rows) - 1)
            if k == k_cap and not lift:
                k_vamp_row = len(up.rows) - 1
    # the toe tip: one vertex
    tip = up.rows[-1]
    v0 = tip[0]
    v0.co = sum((v.co for v in tip), Vector()) / len(tip)
    # dict.fromkeys, not set: removal order decides which freed slots later
    # verts.new() reuses, so a hash (address) order changes the vertex order
    # of everything built after it from run to run
    for v in dict.fromkeys(tip):
        if v is not v0:
            G.bm.verts.remove(v)
    up.rows[-1] = [v0] * len(tip)
    n_rows = len(up.rows)
    up.fill(G.uv, G.tag, TAG["upper"], skip=lambda k, i: i == M)
    for f in up.faces:
        if f.calc_center_median().y < L.y_cap + 1e-3:
            f[G.tag] = TAG["cap"]

    def inside_upper(c):
        y = min(max(c.y, L.y_tip + 0.005), L.y_hb - 0.005)
        zf = L.zf(y)
        return Vector((L.widths(y)[2], y, zf + 0.3 * (L.top(y) - zf)))
    orient(up.faces, inside_upper)
    for row in up.rows:
        G.weight(row, bones)
    # back-stay: the rows over the back seam stand proud of the counter
    for k in range(n_rows):
        d = up.uvs[k][0][1]          # distance from the heel back
        w = 1.0 - smoothstep((d - S["backstay_m"] * 0.55) / (S["backstay_m"] * 0.45))
        if w <= 0:
            continue
        for v in dict.fromkeys(up.rows[k]):
            n = Vector((0.25 * (v.co.x - L.cx0) / max(abs(v.co.x - L.cx0), 1e-6), 1.0, 0.0)).normalized()
            v.co += n * S["backstay_lift_m"] * w
    lat_feather = [up.rows[k][0] for k in range(n_rows)]
    med_feather = [up.rows[k][2 * M + 1] for k in range(n_rows)]

    if first:
        _upper_marks(G, L, S, up, k_vamp_row)

    # --- collar lip: the topline turned in (leather thickness), round the opening
    lip_n = 0
    if open_rows:
        K = open_rows[-1]
        front = up.rows[K + 1][M]
        loop = [up.rows[k][M] for k in open_rows] + [front] + [up.rows[k][M + 1] for k in reversed(open_rows)]
        c = sum((v.co for v in loop), Vector()) / len(loop)
        lg = G.grid(f"lip_{side}")
        acc = 0.0
        for i, v in enumerate(loop):
            if i:
                acc += (v.co - loop[i - 1].co).length
            d = Vector((c.x - v.co.x, c.y - v.co.y, 0.0))
            d = d.normalized() if d.length > 1e-6 else Vector((0, -1, 0))
            q = v.co + d * S["lip_m"] + Vector((0, 0, -S["lip_m"] * 1.2))
            lg.add_shared_row([v, G.bm.verts.new(q)], [(acc, 0.0), (acc, S["lip_m"] * 1.5)])
        lg.fill(G.uv, G.tag, TAG["lip"])
        # the lip faces up and in (toward the leg): away from a point below and outside it
        orient(lg.faces, lambda p: p + Vector((p.x - c.x, p.y - c.y, 0.0)) * 0.5 - Vector((0, 0, 0.01)))
        for row in lg.rows:
            G.weight([row[1]], bones)
        lip_n = len(loop)

    sole_info = build_sole(G, L, S, side, bones, lat_feather, med_feather, first)
    lace_info = build_lacing(G, L, S, side, bones, body, first)
    return {"y_heel": round(L.y_heel, 4), "y_toe": round(L.y_toe, 4), "length_m": round(L.y_hb - L.y_tip, 4),
            "ball_width_m": round(sum(L.widths(L.y_ball)[:2]), 4), "toe_box_h_m": S["toe_box_h_m"],
            "heel_height_m": round(L.zf(L.y_hb) - L.z_floor(), 4), "floor_z": round(L.z_floor(), 4),
            "upper_rows": n_rows, "open_rows": len(open_rows), "lip_verts": lip_n,
            "ridge_at_open_m": round(L.top(L.y_open) - L.z0, 4),
            "ridge_profile": [round(L.top(L.y_open + d) - L.z0, 4) for d in (0.0, 0.01, 0.02, 0.03, 0.04)],
            "topline_profile": [round(L.z_topline(L.y_open + d, True) - L.z0, 4) for d in (0.0, 0.01, 0.02, 0.03, 0.04)],
            **sole_info, **lace_info}


def _upper_marks(G, L, S, up, k_vamp_row):
    """Seams and creases in the upper's panel space (u = arc from the top centre,
    lateral negative; v = distance from the heel back)."""
    tu, tc = TAG["upper"], TAG["cap"]
    cap_uv = up.uvs[k_vamp_row + 1]
    cap_uv = [uv for i, uv in enumerate(cap_uv) if i == 0 or uv != cap_uv[i - 1]]
    # the cap's back edge: a rolled lip, double stitched
    G.mark(tc, "sedge", cap_uv, {"inside_sign": 1.0, "stitch_in_m": 0.0016})
    G.mark(tc, "topstitch", [(u, v + 0.0036) for u, v in cap_uv],
           {"pitch_m": 0.0022, "height": 0.00022, "thread_m": 0.0005})
    v_cap = L.y_hb - L.y_cap
    # flex creases on the vamp behind the cap: along the oblique ball line (the medial
    # side further forward), irregular, wavy, fading down the sides; fine ones between
    rnd = random.Random(S["surface"]["seed"])
    tilt = S["crease_tilt"]
    for j, dv in enumerate(S["creases_m"]):
        fine = j >= S["creases_main"]
        span = S["crease_span_m"] * (rnd.uniform(0.35, 0.6) if fine else (1 - 0.15 * j) * rnd.uniform(0.85, 1.0))
        c = rnd.uniform(-0.25, 0.25) * span
        ph = rnd.uniform(0, TAU)
        k = rnd.uniform(140, 220)
        bow = rnd.uniform(0.003, 0.007)
        us = [lerp(c - span, c + span, i / 24) for i in range(25)]
        pts = [(u, v_cap - dv + tilt * u + 0.0011 * math.sin(k * u + ph) + bow * ((u - c) / span) ** 2) for u in us]
        G.mark(tu, "flex", pts, S["crease_depth_m"] * (0.3 if fine else 1 - 0.25 * j),
               S["crease_w_m"] * (0.5 if fine else 1.0))
    # derby quarters lie on the vamp: their front edge runs from the throat down
    # and a little back to the feather line
    v_thr = L.y_hb - L.y_throat
    for sgn_u in (-1, 1):
        pts = [(sgn_u * lerp(0.010, 0.085, (i / 10) ** 0.9), v_thr - 0.022 * (i / 10) ** 1.6) for i in range(11)]
        G.mark(tu, "sedge", pts, {"inside_sign": -float(sgn_u), "stitch_in_m": 0.0018, "rows": 2})
        # heel counter seam
        pts = [(sgn_u * lerp(0.035, 0.09, i / 6), S["counter_m"] - 0.008 * (i / 6) ** 2) for i in range(7)]
        G.mark(tu, "sedge", pts, {"inside_sign": -float(sgn_u), "stitch_in_m": 0.0018})
        # back-stay edges
        G.mark(tu, "sedge", [(sgn_u * 0.09, S["backstay_m"]), (sgn_u * 0.0005, S["backstay_m"])],
               {"inside_sign": float(sgn_u), "stitch_in_m": 0.0016})


# --- sole ----------------------------------------------------------------------------------------

def build_sole(G, L, S, side, bones, lat, med, first):
    """Welt, sole edge, bottom and heel block under the feather line.
    lat / med: the upper's feather vertices, heel back -> toe tip."""
    n = len(lat)
    ring = lat + list(reversed(med[1:-1]))   # closed: lateral back -> tip, medial tip -> back
    m = len(ring)
    outs = []
    for i, v in enumerate(ring):
        a, b = ring[i - 1].co, ring[(i + 1) % m].co
        t = Vector((b.x - a.x, b.y - a.y, 0.0))
        t = t.normalized() if t.length > 1e-9 else Vector((0, 1, 0))
        nrm = Vector((t.y, -t.x, 0.0))
        c = Vector((L.widths(min(max(v.co.y, L.y_tip + 0.01), L.y_hb - 0.01))[2], v.co.y, 0.0))
        rel = Vector((v.co.x - c.x, v.co.y - c.y, 0.0))
        if rel.length < 1e-6 or i == 0 or i == n - 1:   # the ends: outward along y
            rel = Vector((0, 1 if v.co.y > 0.5 * (L.y_hb + L.y_tip) else -1, 0))
        if nrm.dot(rel) < 0:
            nrm = -nrm
        outs.append(nrm)
    zfl = L.z_floor()
    W, Wh, So = S["welt_m"], S["welt_h_m"], S["sole_m"]
    prof = []
    for v, o in zip(ring, outs):
        heel = smoothstep((v.co.y - L.y_breast + 0.01) / 0.03)
        w = lerp(W, S["welt_heel_m"], heel)
        P = v.co
        prof.append([
            P + o * w + Vector((0, 0, -0.0004)),                 # welt top, outer edge
            P + o * (w + 0.0004) + Vector((0, 0, -Wh * 0.6)),   # welt edge (rounded)
            P + o * (w + 0.0005) + Vector((0, 0, -Wh - So * 0.7)),  # sole edge, flush with the welt
            P + o * (w - 0.0012) + Vector((0, 0, -Wh - So)),     # bevel to the bottom
        ])
    arcs = [0.0]
    for i in range(1, m + 1):
        arcs.append(arcs[-1] + (ring[i % m].co - ring[i - 1].co).length)
    cols = [[ring[i]] + [G.bm.verts.new(p) for p in prof[i]] for i in range(m)]
    dv = [0.0, W, W + Wh * 0.6, W + Wh + So * 0.7, W + Wh + So + 0.002]
    walls = {}
    for tag, idx in ((TAG["sole"], list(range(0, n))), (TAG["sole_m"], list(range(n - 1, m)) + [m])):
        g = G.grid(f"solewall_{side}_{tag}")
        u0 = arcs[idx[0]]
        for j in range(len(dv)):
            g.add_shared_row([cols[i % m][j] for i in idx], [(arcs[i] - u0, dv[j]) for i in idx])
        g.fill(G.uv, G.tag, tag)
        walls[tag] = g

        def inside_wall(c):
            y = min(max(c.y, L.y_tip + 0.01), L.y_hb - 0.01)
            return Vector((L.widths(y)[2], c.y, c.z))
        orient(g.faces, inside_wall)
        if first:
            us = [uv[0] for uv in g.uvs[0]]
            line = lambda vv: [(u, vv) for u in us]   # noqa: E731
            G.mark(tag, "topstitch", line(W * 0.55), {"pitch_m": 0.0034, "height": 0.0003, "thread_m": 0.0009})
            G.mark(tag, "wheel", line(W * 0.55), 0.0016, W * 0.9)
            G.mark(tag, "groove", line(W + Wh))
    for col in cols:
        G.weight(col[1:], bones)
    # bottom: forepart and waist, ahead of the breast (3 columns)
    bot = [c[-1] for c in cols]
    k_br = min(range(n), key=lambda k: abs(lat[k].co.y - L.y_breast))
    bg = G.grid(f"bottom_{side}")
    for k in range(k_br, n):
        a = bot[k]
        b = bot[(m - k) % m] if 0 < k < n - 1 else a
        mid = (a.co + b.co) / 2
        vm = G.bm.verts.new(mid) if b is not a else a
        if vm is not a:
            G.weight([vm], bones)
        bg.add_shared_row([a, vm, b], [(a.co.x - L.cx0, -a.co.y), (mid.x - L.cx0, -mid.y),
                                       (b.co.x - L.cx0, -b.co.y)])
    bg.fill(G.uv, G.tag, TAG["bottom"])
    orient(bg.faces, lambda c: c + Vector((0, 0, 0.01)))
    # heel block: top ring on the sole's bottom edge from the breast round the back
    hb_top = [bot[k] for k in range(k_br, -1, -1)] + [bot[(m - k) % m] for k in range(1, k_br + 1)]
    hb_top.append(bg.rows[0][1])
    hm = len(hb_top)
    cxy = sum((v.co for v in hb_top), Vector()) / hm
    harc = [0.0]
    for i in range(1, hm + 1):
        harc.append(harc[-1] + (hb_top[i % hm].co - hb_top[i - 1].co).length)
    rings = [hb_top]
    for kind, inset in (("lift", 0.0008), ("bevel", 0.0016), ("bottom", 0.0026)):
        rv = []
        for v in hb_top:
            d = Vector((v.co.x - cxy.x, v.co.y - cxy.y, 0.0))
            d = d.normalized() if d.length > 1e-6 else Vector()
            z = {"lift": zfl + S["toplift_m"], "bevel": zfl + 0.0009,
                 "bottom": zfl}[kind]
            rv.append(G.bm.verts.new(Vector((v.co.x, v.co.y, z)) - d * inset))
        rings.append(rv)
        G.weight(rv, bones)
    hdv = [0.0]
    for j in range(1, len(rings)):
        hdv.append(hdv[-1] + abs(rings[j][0].co.z - rings[j - 1][0].co.z))
    hg = G.grid(f"heel_{side}")
    for j, rv in enumerate(rings):
        hg.add_shared_row(rv + [rv[0]], [(harc[i], hdv[j]) for i in range(hm + 1)])
    hg.fill(G.uv, G.tag, TAG["heel"])
    orient(hg.faces, lambda c: Vector((cxy.x, cxy.y, c.z)))
    f = G.bm.faces.new(rings[-1])
    f.smooth = False
    f[G.tag] = TAG["toplift"]
    for loop in f.loops:
        loop[G.uv].uv = (loop.vert.co.x - L.cx0, -loop.vert.co.y)
    res = bmesh.ops.triangulate(G.bm, faces=[f])
    for ff in res["faces"]:
        ff.normal_update()
        if ff.normal.z > 0:
            ff.normal_flip()
    if first:
        G.mark(TAG["heel"], "lifts", [(0.0, hdv[1]), (harc[-1], hdv[1])], 0.0, hdv[1])
    return {"sole_outline_pts": m, "heel_ring_pts": hm, "breast_y": round(L.y_breast, 4),
            "heel_block_m": round(hb_top[0].co.z - zfl, 4)}


# --- lacing ---------------------------------------------------------------------------------------

def tube(G, pts, r, sides, tag, weights, close_end=False, uv_u0=0.0):
    """A round tube along a polyline (parallel-transported frames), faces out."""
    n = len(pts)
    T = [(pts[min(i + 1, n - 1)] - pts[max(i - 1, 0)]).normalized() for i in range(n)]
    ref = Vector((0, 0, 1)) if abs(T[0].z) < 0.9 else Vector((1, 0, 0))
    N = (ref - T[0] * ref.dot(T[0])).normalized()
    rings, faces = [], []
    acc = 0.0
    for i in range(n):
        if i:
            N = (N - T[i] * N.dot(T[i])).normalized()
            acc += (pts[i] - pts[i - 1]).length
        B = T[i].cross(N)
        ring = [G.bm.verts.new(pts[i] + (N * math.cos(TAU * j / sides) + B * math.sin(TAU * j / sides)) * r)
                for j in range(sides)]
        for v in ring:
            for k, x in weights.items():
                v[G.dl][k] = x
        rings.append((ring, acc))
    circ = TAU * r
    for (ra, va), (rb, vb) in zip(rings, rings[1:]):
        for j in range(sides):
            jj = (j + 1) % sides
            f = G.bm.faces.new([ra[j], rb[j], rb[jj], ra[jj]])   # outward for B = T x N
            f.smooth = True
            f[G.tag] = tag
            faces.append(f)
            for loop, uv in zip(f.loops, ((uv_u0 + circ * j / sides, va), (uv_u0 + circ * j / sides, vb),
                                          (uv_u0 + circ * (j + 1) / sides, vb), (uv_u0 + circ * (j + 1) / sides, va))):
                loop[G.uv].uv = uv
    if close_end:
        ring, v_end = rings[-1]
        c = G.bm.verts.new(pts[-1] + T[-1] * r * 0.6)
        for k, x in weights.items():
            c[G.dl][k] = x
        for j in range(sides):
            f = G.bm.faces.new([ring[j], ring[(j + 1) % sides], c])
            f.smooth = True
            f[G.tag] = tag
            faces.append(f)
            for loop, uv in zip(f.loops, ((uv_u0 + circ * j / sides, v_end), (uv_u0 + circ * (j + 1) / sides, v_end),
                                          (uv_u0 + circ * (j + 0.5) / sides, v_end + r))):
                loop[G.uv].uv = uv
    # outward check: faces point away from the nearest path point
    vote = 0.0
    for f in faces:
        f.normal_update()
        cc = f.calc_center_median()
        i = min(range(n), key=lambda q: (pts[q] - cc).length)
        vote += f.normal.dot(cc - pts[i])
    if vote < 0:
        for f in faces:
            f.normal_flip()
    return acc


def build_lacing(G, L, S, side, bones, body, first):
    F = S["facing"]
    Lc = S["laces"]
    wts = {G.gidx[k]: w for k, w in body.weights(L.point(L.y_throat, HALF), bones).items()}
    y0 = L.y_throat - 0.004
    ys_e = [L.y_tip + Lc["first_m"] + j * Lc["pitch_m"] for j in range(Lc["count"])]
    y1 = ys_e[-1] + F["past_top_m"]
    nr = F["rows"]

    def gap(y):
        return lerp(F["gap_bottom_m"], F["gap_top_m"], min(1.0, max(0.0, (y - y0) / (y1 - y0))))

    def surf(y, s, lateral, lift):
        a = L.at_arc(y, s, lateral)
        return L.point(y, a) + L.normal(y, a) * lift

    eyelets = {True: [], False: []}
    # the facings: flaps lying on the tongue, their lacing edge 1 mm thick
    for lateral in (True, False):
        g = G.grid(f"facing_{side}_{int(lateral)}")
        for k in range(nr + 1):
            t = k / nr
            y = lerp(y0, y1, t)
            gp = gap(y)
            w = F["width_m"] * (0.5 + 0.5 * smoothstep(t / 0.3))
            lift_k = F["lift_m"] * (0.35 + 0.65 * smoothstep(t / 0.12))   # the throat end turns down
            spec = [(gp, 0.0002), (gp + 0.0004, lift_k), (gp + 0.3 * w, lift_k * 0.95),
                    (gp + 0.7 * w, lift_k * 0.6), (gp + w, F["edge_lift_m"])]
            pts, uvs = [], []
            for j, (s, lift) in enumerate(spec):
                pts.append(surf(y, s, lateral, lift))
                uu = s + (-0.0012 if j == 0 else 0.0)
                uvs.append((uu if lateral else -uu, L.y_hb - y))
            g.add_row(pts, uvs)
        g.fill(G.uv, G.tag, TAG["facing"])

        def inside_f(c, lateral=lateral):
            y = min(max(c.y, L.y_tip + 0.01), L.y_hb - 0.01)
            zf = L.zf(y)
            return Vector((L.widths(y)[2], y, zf + 0.2 * (L.top(y) - zf)))
        orient(g.faces, inside_f)
        for row in g.rows:
            for v in row:
                v[G.dl].clear()
                for kk, x in wts.items():
                    v[G.dl][kk] = x
        if first:
            G.mark(TAG["facing"], "sedge", [g.uvs[k][1] for k in range(1, nr + 1)],
                   {"inside_sign": 1.0 if lateral else -1.0, "stitch_in_m": 0.0018})
            G.mark(TAG["facing"], "sedge", [g.uvs[1][j] for j in range(1, 5)],
                   {"inside_sign": -1.0 if lateral else 1.0, "stitch_in_m": 0.0018})
        for y in ys_e:
            s = gap(y) + Lc["edge_in_m"]
            a = L.at_arc(y, s, lateral)
            lift = F["lift_m"]
            eyelets[lateral].append((L.point(y, a) + L.normal(y, a) * lift, L.normal(y, a), y))
            if first:   # blind eyelets: punched holes, drawn in the maps (suit_leather.py)
                G.mark(TAG["facing"], "eyelet", (s if lateral else -s, L.y_hb - y), Lc["eyelet_r_m"])
    r = Lc["radius_m"]
    sides = Lc["sides"]
    u0 = [0.0]

    def lay(pts, close=False):
        out = tube(G, pts, r, sides, TAG["lace"], wts, close_end=close, uv_u0=u0[0])
        u0[0] += 0.009
        return out

    def bezier(a, c, b, k=5):
        return [a * (1 - t) ** 2 + c * 2 * t * (1 - t) + b * t * t for t in [i / (k - 1) for i in range(k)]]

    lace_len = 0.0
    lift_top = F["lift_m"] + r * 1.05
    # the bottom bar, on top, eyelet to eyelet
    (pa, na, ya), (pb, nb, _) = eyelets[True][0], eyelets[False][0]
    mid = surf(ya, 0.0, True, lift_top + 0.0003)
    pts = bezier(pa - na * r * 0.5, mid, pb - nb * r * 0.5)
    pts[1] += na * r
    pts[-2] += nb * r
    lace_len += lay(pts)
    # diagonals: from under one facing's edge (j = 0) or from the eyelet on top, across
    # the gap, diving under the other facing's edge next to the eyelet above
    for j in range(len(ys_e) - 1):
        for lateral in (True, False):
            y_a, y_b = ys_e[j], ys_e[j + 1]
            over = 0.0006 if lateral else 0.0
            if j == 0:
                start = surf(y_a + 0.002, gap(y_a) + 0.0004, lateral, r * 0.9)
            else:
                p, nrm, _ = eyelets[lateral][j]
                start = p - nrm * r * 0.5
            end = surf(y_b - 0.002, gap(y_b) + 0.0006, not lateral, r * 0.9)
            ym = 0.5 * (y_a + y_b)
            mid = surf(ym, 0.0, True, r * 1.3 + over + (0.0006 if j else 0.0))
            pts = bezier(start, mid, end)
            if j:
                pts[1] += eyelets[lateral][j][1] * r
            lace_len += lay(pts)
    # the bow: the ends leave the top eyelets for a knot over the gap behind them
    B = Lc["bow"]
    yk = ys_e[-1] + B["behind_m"]
    lk = lift_top + r * 0.5
    K = surf(yk, 0.0, True, lk + B["knot_r_m"] * 0.5)
    for lateral in (True, False):
        p, nrm, _ = eyelets[lateral][-1]
        lace_len += lay([p - nrm * r * 0.5, p + nrm * r, (p + K) / 2 + nrm * r * 1.2, K])
    for lateral, asym in ((True, 1.0), (False, 0.86)):
        loop_pts = []
        for i in range(B["loop_pts"]):
            ang = math.pi * i / (B["loop_pts"] - 1)
            s_out = B["loop_len_m"] * asym * math.sin(ang) ** 0.7
            dy = B["loop_w_m"] * 0.5 * math.sin(2 * ang) + B["loop_fwd_m"] * math.sin(ang)
            loop_pts.append(surf(yk - dy, s_out + 0.0015, lateral, lk + r * 0.3 + 0.0012 * math.sin(ang)))
        lace_len += lay(loop_pts)
        tail = []
        for i in range(B["tail_pts"]):
            t = i / (B["tail_pts"] - 1)
            tail.append(surf(yk - B["tail_fwd_m"] * t * (1.15 if lateral else 0.9),
                             0.002 + B["tail_side_m"] * asym * t, lateral, lk - r * 0.2 * t))
        lace_len += lay(tail, close=True)
    kn = [surf(yk, B["knot_w_m"] / 2, True, lk), K, surf(yk, B["knot_w_m"] / 2, False, lk)]
    tube(G, kn, B["knot_r_m"], sides + 1, TAG["lace"], wts, close_end=True, uv_u0=u0[0])
    if first:
        G.mark(TAG["lace"], "twist", None)
    return {"eyelets": 2 * len(ys_e), "lace_m": round(lace_len, 3), "top_eyelet_y": round(ys_e[-1], 4)}


def build(ctx, body, S, arm, like, mats, part):
    G = sb.Garment(part.format("shoes"), arm, body)
    m = {}
    for side in ("l", "r"):
        m[side] = build_shoe(G, body, S, side)
    ob = G.finish(ctx, like, mats["leather"])
    ob.data.materials.append(mats["sole"])
    tag = ob.data.attributes.get("panel")
    if tag:
        names = {v: k for k, v in TAG.items()}
        tris = {}
        for p in ob.data.polygons:
            t = tag.data[p.index].value
            p.material_index = 1 if t in SOLE_TAGS else 0
            tris[names.get(t, t)] = tris.get(names.get(t, t), 0) + len(p.vertices) - 2
        m["tris"] = dict(sorted(tris.items(), key=lambda kv: -kv[1]))
        m["tris"]["total"] = sum(tris.values())
    m["marks"] = G.marks
    m.update(G.stats)
    return ob, m
