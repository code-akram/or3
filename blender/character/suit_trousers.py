"""Trousers, built parametrically on the body (suit_build primitives;
bench/m1/suit.md §1, look-spec §4.1, bench/m1/v2/direction.md Track D).

Flat front, natural-waist rise (waistband top at waist_to_stature x stature,
under the waistcoat), slim straight leg, quarter break, pressed creases.

Construction, per leg (the right leg is the exact mirror of the left, so the
centre seams weld):

    rows     horizontal rings from the waistband top down to the hem: the
             waistband, the seat (one blob round the pelvis, cut at the
             midplane), the crotch row, then the leg (round the leg's bone
             axis); the last rows tilt into the slanted hem
    columns  24 per leg, anchored at the inseam, centre front (CF), front
             crease, outseam, back crease, centre back (CB). Above the crotch
             the inseam side has no cloth (both legs are one blob): those
             columns lie on the midplane chord CB -> CF and their faces are
             skipped. At the crotch row the chord is real: the crotch seam
             under the body, shared by both legs. Below it each leg is a tube.
    shape    seat: the body slice (ray-cast from the centre), canvassed and
             eased (front / side / back allowances), the back convex across
             the cleft; thigh -> knee: the eased body against the cut (the
             body's second-moment ellipse scaled to a flat width tapering
             thigh -> knee_flat_m), whichever is larger, bridged vertically;
             knee -> hem: a straight tube (polar blend of the knee ellipse and
             the hem), hung over the calf (outer envelope per column)
    hem      the hull of the heel counter and the ankle (clear of both), grown
             until the hem lies opening_flat_m flat; back at back_hem_m (it
             rides up the counter only if the opening cannot wrap it there),
             level round the sides, rising to rest on the instep / vamp; one
             soft break fold above the front
    tuck     inside the jacket and the waistcoat above their hems (a smooth
             displacement field, never closer to the body than its ease)
    crease   a 1.5 mm ridge down the front (waistband -> hem) and the back
             (below the seat), sharp edges + a crease mark in the normal map

Panels (face tags, metric UVs, one atlas rectangle each): front and back per
leg, a waistband half per side. Marks for suit_textures: seams (outseam,
inseam, centre back, waistband), the fly J-stitch, slanted side pockets,
jetted back pockets, side adjusters, the hem edge, the creases.

World space = object space (Z up, front = -Y, the wearer's left = +X).
"""

import math

from mathutils import Vector

from . import suit_build as sb
from .suit_build import TAU, lerp, smoothstep

TAG = {"front_l": 1, "back_l": 2, "front_r": 3, "back_r": 4, "band_l": 5, "band_r": 6}

# columns per segment, inseam -> CF -> front crease -> outseam -> back crease -> CB -> inseam
SEGMENTS = (2, 4, 6, 6, 4, 2)
C_CF, C_FRONT, C_SIDE, C_BACK, C_CB = 2, 6, 12, 18, 22
NCOL = sum(SEGMENTS)      # 24; column NCOL is column 0 again (closed ring)
MID_EPS = 1e-6


def waistband_z(stature, T):
    return T["waist_to_stature"] * stature


# --- ring helpers ---------------------------------------------------------------------------

def ray_ring(tree, c, z, n=120, reach=0.4, prev=None):
    """Body cross-section at height z seen from the centre c (x, y): the first
    skin hit along each horizontal ray. Misses are filled from neighbours."""
    r = [None] * n
    for i in range(n):
        a = TAU * i / n
        d = Vector((math.cos(a), math.sin(a), 0.0))
        hit = tree.ray_cast(Vector((c[0], c[1], z)), d, reach)
        if hit[0] is not None:
            r[i] = hit[3]
    known = [i for i in range(n) if r[i] is not None]
    if not known:
        return prev
    for i in range(n):
        if r[i] is None:
            p = max([k for k in known if k < i], default=known[-1] - n)
            q = min([k for k in known if k > i], default=known[0] + n)
            t = (i - p) / (q - p)
            r[i] = r[p % n] * (1 - t) + r[q % n] * t
    return r


def polyline_from_polar(c, radii, z, a0, n_dense=240):
    """Closed dense polyline round c starting at angle a0 (radians), counter-
    clockwise seen from above."""
    out = []
    for j in range(n_dense):
        a = a0 + TAU * j / n_dense
        r = sb.sample_ring(radii, a)
        out.append(Vector((c[0] + r * math.cos(a), c[1] + r * math.sin(a), z)))
    return out


def arc_params(pts):
    s = [0.0]
    for a, b in zip(pts, pts[1:]):
        s.append(s[-1] + (b - a).length)
    return s


def resample(pts, i0, i1, n):
    """n + 1 points from pts[i0] to pts[i1] (indices into an open polyline,
    i1 > i0) evenly by arc length."""
    seg = pts[i0:i1 + 1]
    if len(seg) < 2:
        return [seg[0].copy() for _ in range(n + 1)]
    s = arc_params(seg)
    L = s[-1]
    out = []
    k = 0
    for j in range(n + 1):
        t = L * j / n
        while k < len(seg) - 2 and s[k + 1] < t:
            k += 1
        dl = s[k + 1] - s[k]
        u = (t - s[k]) / dl if dl > 1e-12 else 0.0
        out.append(seg[k].lerp(seg[k + 1], min(1.0, max(0.0, u))))
    return out


# --- ellipses -------------------------------------------------------------------------------
# An ellipse is (centre (x, y), M = (m00, m01, m11)): the points X with
# (X - e)^T M^-1 (X - e) = 1; M's eigenvalues are the squared semi-axes.

def ellipse_moments(pts):
    """The second-moment ellipse of a closed polygon: the solid ellipse with the
    same centroid and covariance (variance p^2 / 4 along a semi-axis p)."""
    n = len(pts)
    A = cx = cy = sxx = syy = sxy = 0.0
    for i in range(n):
        x0, y0 = pts[i].x, pts[i].y
        x1, y1 = pts[(i + 1) % n].x, pts[(i + 1) % n].y
        cr = x0 * y1 - x1 * y0
        A += cr
        cx += (x0 + x1) * cr
        cy += (y0 + y1) * cr
        sxx += (x0 * x0 + x0 * x1 + x1 * x1) * cr
        syy += (y0 * y0 + y0 * y1 + y1 * y1) * cr
        sxy += (x0 * y1 + 2 * x0 * y0 + 2 * x1 * y1 + x1 * y0) * cr
    A *= 0.5
    cx, cy = cx / (6 * A), cy / (6 * A)
    sxx = sxx / (12 * A) - cx * cx
    syy = syy / (12 * A) - cy * cy
    sxy = sxy / (24 * A) - cx * cy
    return (cx, cy), (4 * sxx, 4 * sxy, 4 * syy)


def ellipse_axes(M):
    m00, m01, m11 = M
    h = 0.5 * (m00 + m11)
    d = math.sqrt(max(0.0, 0.25 * (m00 - m11) ** 2 + m01 * m01))
    return math.sqrt(max(h + d, 1e-12)), math.sqrt(max(h - d, 1e-12))


def perimeter(p, q):
    """Ramanujan's ellipse perimeter."""
    return math.pi * (3 * (p + q) - math.sqrt((3 * p + q) * (p + 3 * q)))


def ray_ellipse(c, a, e, M):
    """Distance from c (inside the ellipse) along the direction a (radians) to it."""
    m00, m01, m11 = M
    det = m00 * m11 - m01 * m01
    q00, q01, q11 = m11 / det, -m01 / det, m00 / det
    dx, dy = math.cos(a), math.sin(a)
    wx, wy = c[0] - e[0], c[1] - e[1]
    A = q00 * dx * dx + 2 * q01 * dx * dy + q11 * dy * dy
    B = q00 * dx * wx + q01 * (dx * wy + dy * wx) + q11 * dy * wy
    C = q00 * wx * wx + 2 * q01 * wx * wy + q11 * wy * wy - 1.0
    disc = B * B - A * C
    if disc < 0:
        return 0.0
    return max(0.0, (-B + math.sqrt(disc)) / A)


def spread_ring(d, width):
    """Spread non-negative values round a closed ring: each becomes the max of
    its neighbours' values under a Gaussian falloff (width in samples)."""
    n = len(d)
    out = list(d)
    reach = int(math.ceil(2.5 * width))
    for i, x in enumerate(d):
        if x <= 0:
            continue
        for k in range(-reach, reach + 1):
            j = (i + k) % n
            out[j] = max(out[j], x * math.exp(-(k / width) ** 2))
    return out


def minkowski_hull(poly, d, n=12):
    """The convex polygon grown by d (the hull of a disc round each vertex)."""
    if d <= 0:
        return poly
    pts = [(x + d * math.cos(TAU * j / n), y + d * math.sin(TAU * j / n)) for x, y in poly for j in range(n)]
    return convex_hull(pts)


def polygon_centroid(poly):
    A = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        cr = x0 * y1 - x1 * y0
        A += cr
        cx += (x0 + x1) * cr
        cy += (y0 + y1) * cr
    return cx / (3 * A), cy / (3 * A)


def ray_polygon(c, a, poly):
    """Distance from c (inside the convex polygon) along the direction a to its edge."""
    dx, dy = math.cos(a), math.sin(a)
    best = 0.0
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        ex, ey = x1 - x0, y1 - y0
        den = dx * ey - dy * ex
        if abs(den) < 1e-12:
            continue
        wx, wy = x0 - c[0], y0 - c[1]
        t = (wx * ey - wy * ex) / den
        u = (wx * dy - wy * dx) / den
        if t > 0 and -1e-9 <= u <= 1 + 1e-9:
            best = max(best, t)
    return best


def slanted_perimeter(poly, dz, curve=1.0):
    """Perimeter of the polygon lifted as the hem is: z rises by dz from its
    back (max y) to its front (min y), as fr ** curve (fr 0 -> 1 back -> front)."""
    y0, y1 = max(y for _, y in poly), min(y for _, y in poly)
    pts = []
    for (xa, ya), (xb, yb) in zip(poly, poly[1:] + poly[:1]):
        for j in range(4):          # subdivide: the lift is curved
            x, y = xa + (xb - xa) * j / 4, ya + (yb - ya) * j / 4
            pts.append(Vector((x, y, dz * ((y0 - y) / max(y0 - y1, 1e-9)) ** curve)))
    return sb.arc_length(pts, closed=True)


def columns_from_anchors(pts, anchors):
    """pts: open dense polyline; anchors: indices for inseam, CF, front, side,
    back, CB, inseam (increasing). Returns NCOL + 1 column points."""
    cols = []
    for (a, b), n in zip(zip(anchors, anchors[1:]), SEGMENTS):
        seg = resample(pts, a, b, n)
        cols.extend(seg[:-1])
    cols.append(pts[anchors[-1]].copy())
    return cols


# --- the build ------------------------------------------------------------------------------

class Trousers:
    def __init__(self, G, body, T, stature, z_wt, shoe_tree):
        self.G, self.body, self.T = G, body, T
        self.stature = stature
        self.z_wt = z_wt
        self.z_wb = z_wt - T["waistband_m"]
        self.tree = body.bvh()
        self.shoe_tree = shoe_tree
        self.m = {}
        # landmarks: crotch (the lowest midline point of the torso/thighs), knee
        mid = [v for v in body.verts(sb.TORSO | {"thigh_l", "thigh_r"})
               if abs(v.co.x) < 0.012 and 0.6 < v.co.z < z_wt]
        self.z_crotch_body = min(v.co.z for v in mid)
        self.z_cr = self.z_crotch_body - T["crotch_drop_m"]
        self.z_knee = body.joint("calf_l").z
        self.hip = body.joint("thigh_l")
        self.knee = body.joint("calf_l")
        self.ankle = body.tail("calf_l")
        self.m["crotch_body_z"] = round(self.z_crotch_body, 4)
        self.m["crotch_z"] = round(self.z_cr, 4)

    # leg axis (left leg): hip joint -> knee -> ankle, by z
    def leg_centre(self, z):
        if z >= self.knee.z:
            t = (self.hip.z - z) / (self.hip.z - self.knee.z)
            p = self.hip.lerp(self.knee, t)
        else:
            t = (self.knee.z - z) / (self.knee.z - self.ankle.z)
            p = self.knee.lerp(self.ankle, t)
        return (p.x, p.y)

    def seat_ease(self, z, a):
        """Radial allowance round the pelvis: front / side / back, the waistband
        snug, the seat allowance from the hip down."""
        T = self.T
        E = T["ease"]
        s, c = math.sin(a), math.cos(a)
        wf, wb, ws = max(0.0, -s) ** 2, max(0.0, s) ** 2, c * c
        seat = wf * E["front"] + wb * E["seat"] + ws * E["hip"]
        t = smoothstep((self.z_wb - z) / max(self.z_wb - (self.hip.z + 0.02), 1e-6))
        return lerp(E["waist"], seat, t)

    def leg_ease(self, z, a):
        E = self.T["ease"]
        s = math.sin(a)
        return lerp(E["thigh_front"], E["thigh_back"], 0.5 + 0.5 * s)

    def cut_half_width(self, z):
        """Flat width / 2 of the pattern's leg at z above the knee (thigh -> knee)."""
        T = self.T
        t = (z - self.z_knee) / max(self.z_cr - self.z_knee, 1e-6)
        return 0.5 * lerp(T["knee_flat_m"], self.thigh_flat * T["thigh_cut"], smoothstep(t))

    def eased_ring(self, c, z):
        body = ray_ring(self.tree, c, z, reach=0.25)
        n = len(body)
        body = sb.smooth_ring(sb.chord_fill(sb.smooth_ring(body, 1), ks=(2, 4, 8, 12), iters=2), 1)
        return [body[i] + self.leg_ease(z, TAU * (i + 0.5) / n) for i in range(n)]

    def fitted_cut(self, c, eased, z):
        """The cut above the knee: the second-moment ellipse of the eased body
        ring, scaled to the pattern's flat width (it fills the hollows of the
        thigh the way the cloth bridges them)."""
        e, M = ellipse_moments(polyline_from_polar(c, eased, z, 0.0, n_dense=120))
        s = 4 * self.cut_half_width(z) / perimeter(*ellipse_axes(M))
        return e, tuple(m * s * s for m in M)

    def top_at(self, x, y, z0):
        """The surface the cloth would rest on under (x, y), looking down from
        z0 (the shoe or the foot): (z, normal); (z0, None) when z0 is inside a
        surface already; (None, None) when nothing is below."""
        best = (None, None)
        down = Vector((0, 0, -1))
        for tr in (self.shoe_tree, self.tree):
            if tr is None:
                continue
            h = tr.ray_cast(Vector((x, y, z0)), down, z0 + 0.1)
            if h[0] is None:
                continue
            if h[1].dot(down) > 0:          # leaving a volume: z0 is inside it
                return z0, None
            if best[0] is None or h[0].z > best[0]:
                best = (h[0].z, h[1])
        return best

    def prepare_cuts(self, heel):
        """The knee ellipse (fitted, knee_flat_m) and the hem: the convex hull of
        the heel counter and the ankle above the instep (clear by heel_clear_m),
        grown evenly until the hem, rising from back_hem_m at the back (level
        round the sides, hem_curve) to the instep / vamp at the front, lies
        opening_flat_m flat. If even the bare hull is wider than that, the back
        rides up the counter until it is not. Below the knee the leg is the
        straight tube between the two (polar blend round a centre moving
        knee -> hem)."""
        T = self.T
        c = self.leg_centre(self.z_knee)
        self.knee_c = c
        self.knee_cut = self.fitted_cut(c, self.eased_ring(c, self.z_knee), self.z_knee)
        # the ankle above the instep (the hem rests on the instep, round the ankle)
        z0 = self.ankle.z + 0.03
        leg = [v.co for v in self.body.verts(sb.LEG["l"]) if v.co.x > 0]
        ankle = [(p.x, p.y) for p in leg if z0 <= p.z <= z0 + 0.06]
        y_heel = max(p.y for p in heel) if heel else max(p.y for p in leg)

        def base_at(z_b):
            # what the hem wraps at the back: the heel counter above z_b (the
            # heel of the foot once z_b is over the counter)
            back = [(p.x, p.y) for p in heel + leg
                    if p.y > y_heel - 0.07 and z_b - 0.005 <= p.z <= z_b + 0.04]
            return minkowski_hull(convex_hull(back + ankle), T["heel_clear_m"])

        # the back of the hem at back_hem_m, unless the opening cannot wrap the
        # counter there: then it rides up the counter until it can
        z_front = z_b = T["back_hem_m"]
        for _ in range(17):
            base = base_at(z_b)
            ch = polygon_centroid(base)
            t, _ = self.top_at(ch[0], ch[1] - ray_polygon(ch, -math.pi / 2, base), self.ankle.z + 0.05)
            z_front = max(z_b + T["hem_slant_m"], (t or 0.0) + T["vamp_rest_m"])
            if 0.5 * slanted_perimeter(base, z_front - z_b, T["hem_curve"]) <= T["opening_flat_m"]:
                break
            z_b += 0.0025
        self.z_back = z_b
        grown = 0.0
        for _ in range(4):
            dz = z_front - z_b

            def flat(d):
                return 0.5 * slanted_perimeter(minkowski_hull(base, d), dz, T["hem_curve"])
            lo, hi = 0.0, 0.05
            if flat(0.0) < T["opening_flat_m"]:
                for _ in range(30):
                    mid = 0.5 * (lo + hi)
                    if flat(mid) < T["opening_flat_m"]:
                        lo = mid
                    else:
                        hi = mid
            grown = lo
            poly = minkowski_hull(base, lo)
            ch = polygon_centroid(poly)
            y_f = ch[1] - ray_polygon(ch, -math.pi / 2, poly)
            t, _ = self.top_at(ch[0], y_f, self.ankle.z + 0.05)
            z_front = (t if t is not None else 0.0) + T["vamp_rest_m"]
            z_front = min(max(z_front, z_b + T["hem_slant_m"]), z_b + T["hem_slant_max_m"])
        self.hem_poly, self.hem_c = poly, ch
        self.z_front = z_front
        self.m["back_hem_raised_m"] = round(z_b - T["back_hem_m"], 4)
        xs, ys = [x for x, _ in poly], [y for _, y in poly]
        self.m["vamp_z_at_front"] = round(t, 4) if t is not None else None
        self.m["front_hem_z"] = round(z_front, 4)
        self.m["hem_cut_w_d_m"] = [round(max(xs) - min(xs), 4), round(max(ys) - min(ys), 4)]
        self.m["hem_grown_m"] = round(grown, 4)
        self.m["hem_cut_flat_m"] = round(0.5 * slanted_perimeter(poly, z_front - z_b, T["hem_curve"]), 4)

    def leg_ring_dense(self, z, clamp_gap):
        """The left leg's ring at z as a dense polyline from the inseam direction
        (angle pi round the leg centre) counter-clockwise: front, outseam, back.
        The eased body against the cut, whichever is larger; the foot is
        ignored (the hem is cut round the shoe)."""
        if z >= self.z_knee:
            c = self.leg_centre(z)
            eased = self.eased_ring(c, z)
            e, M = self.fitted_cut(c, eased, z)
        else:
            t = min(1.0, (self.z_knee - z) / max(self.z_knee - self.z_back, 1e-6))
            ck, ch = self.knee_c, self.hem_c
            c = (lerp(ck[0], ch[0], t), lerp(ck[1], ch[1], t))
            eased = self.eased_ring(c, z) if z > self.ankle.z + 0.05 else None
        n = 120
        radii = []
        for i in range(n):
            a = TAU * (i + 0.5) / n
            if z >= self.z_knee:
                r = ray_ellipse(c, a, e, M)
            else:
                r = lerp(ray_ellipse(ck, a, *self.knee_cut), ray_polygon(ch, a, self.hem_poly), t)
            radii.append(max(r, eased[i]) if eased is not None else r)
        radii = sb.smooth_ring(radii, 2)
        pts = polyline_from_polar(c, radii, z, math.pi)
        if clamp_gap is not None:
            for p in pts:
                if p.x < clamp_gap:
                    p.x = clamp_gap
        return pts, c

    def leg_columns(self, z):
        """Column points for a leg row below the crotch: the ring clamped to a
        small gap at the midplane (the legs touch, never cross)."""
        gap = self.T["inner_gap_m"]
        pts, c = self.leg_ring_dense(z, gap)
        n = len(pts)
        # angles: index j <-> pi + TAU j / n; front (3pi/2) at n/4, side at n/2, back at 3n/4
        j_front, j_side, j_back = n // 4, n // 2, 3 * n // 4
        flat = [abs(p.x - gap) < 1e-7 for p in pts]
        # CF: the front end of the flat span, at least 45 deg round from the inseam
        j = 0
        while j < j_front and flat[j]:
            j += 1
        j_cf = max(n // 8, j - 1)
        j = n - 1
        while j > j_back and flat[j]:
            j -= 1
        j_cb = min(7 * n // 8, j + 1)
        # open polyline from the inseam point (half way from CB to CF round the
        # inner side), through CF, front, side, back, CB, back to it
        inner = pts[j_cb:] + pts[:j_cf + 1]
        s = arc_params(inner)
        half = s[-1] * 0.5
        k = max(1, next(i for i in range(len(s)) if s[i] >= half))
        mid_pt = inner[k - 1].lerp(inner[k], (half - s[k - 1]) / max(s[k] - s[k - 1], 1e-12))
        tail_in = inner[k:]                    # inseam -> CF (inclusive)
        head_in = inner[:k]                    # CB -> just before the inseam
        seq = [mid_pt] + tail_in[:-1] + pts[j_cf:j_cb + 1] + head_in[1:] + [mid_pt.copy()]
        a_cf = len(tail_in)                    # where pts[j_cf] lands in seq
        anchors = (0, a_cf, a_cf + (j_front - j_cf), a_cf + (j_side - j_cf),
                   a_cf + (j_back - j_cf), a_cf + (j_cb - j_cf), len(seq) - 1)
        return columns_from_anchors(seq, anchors), c

    def crotch_columns(self, z, cf_s, cb_s, x_crease):
        """The crotch row: the convex hull of the left thigh's ring (clamped to
        the midplane) and the two rise points, CF and CB, moved toward each
        other under the crotch. The hull's edge on the midplane is the chord
        (the crotch seam, shared with the other leg)."""
        T = self.T
        pts, c = self.leg_ring_dense(z, 0.0)
        inner = min(pts, key=lambda p: p.x)
        y_mid = inner.y
        y_f = lerp(cf_s.y, y_mid, T["crotch_close"])
        y_b = lerp(cb_s.y, y_mid, T["crotch_close"])
        cloud = [(p.x, p.y) for p in pts] + [(0.0, y_f), (0.0, y_b)]
        hull = convex_hull(cloud)              # counter-clockwise
        # rotate so it starts at CF (0, y_f) and runs CCW (front, side, back) to CB
        i_f = min(range(len(hull)), key=lambda i: hull[i][0] ** 2 + (hull[i][1] - y_f) ** 2)
        hull = hull[i_f:] + hull[:i_f]
        i_b = min(range(len(hull)), key=lambda i: hull[i][0] ** 2 + (hull[i][1] - y_b) ** 2)
        path = [Vector((x, y, z)) for x, y in hull[:i_b + 1]]
        path[0].x = path[-1].x = 0.0
        half = resample(path, 0, len(path) - 1, 200)
        return self.half_to_columns(half, x_crease), c

    def half_to_columns(self, half, x_crease):
        """Columns from a half ring CF (x = 0, front) -> side -> CB (x = 0, back);
        the inseam-side columns lie on the midplane chord CB -> CF."""
        nd = len(half) - 1
        j_side = max(range(nd + 1), key=lambda j: half[j].x)
        j_front = min(range(1, j_side), key=lambda j: abs(half[j].x - x_crease))
        j_back = min(range(j_side + 1, nd), key=lambda j: abs(half[j].x - x_crease))
        outer = columns_from_anchors_seg(half, (0, j_front, j_side, j_back, nd), SEGMENTS[1:5])
        cf, cb = outer[0], outer[-1]
        mid = cb.lerp(cf, 0.5)
        n0, n5 = SEGMENTS[0], SEGMENTS[5]
        cols = [mid.lerp(cf, i / n0) for i in range(n0)] + outer + \
               [cb.lerp(mid, i / n5) for i in range(1, n5 + 1)]
        for i in list(range(0, C_CF + 1)) + list(range(C_CB, NCOL + 1)):
            cols[i].x = 0.0
        return cols

    def seat_columns(self, z, x_crease):
        """Column points for a seat row: the left half of the pelvis ring from CF
        (x = 0, front) round the side to CB (x = 0, back); the inseam-side
        columns on the midplane chord CB -> CF (no faces there)."""
        c = (0.0, self.cy_seat(z))
        body = ray_ring(self.tree, c, z, reach=0.4)
        n = len(body)
        body = sb.smooth_ring(sb.chord_fill(sb.smooth_ring(body, 1), ks=(2, 4, 8, 12), iters=3,
                                            limit=self.T["canvas_limit_m"]), 1)
        radii = [body[i] + self.seat_ease(z, TAU * (i + 0.5) / n) for i in range(n)]
        # dense half ring: angle -pi/2 (front) -> 0 (side) -> pi/2 (back)
        nd = 180
        half = []
        for j in range(nd + 1):
            a = -math.pi / 2 + math.pi * j / nd
            r = sb.sample_ring(radii, a)
            half.append(Vector((c[0] + r * math.cos(a), c[1] + r * math.sin(a), z)))
        # the back spans the cleft: the cloth runs buttock to buttock (convex
        # across the midplane), faded in from the side seam
        both = [(q.x, q.y) for q in half] + [(-q.x, q.y) for q in half]
        hull = convex_hull(both)
        for j in range(nd + 1):
            a = -math.pi / 2 + math.pi * j / nd
            if a <= 0:
                continue
            q = half[j]
            r = math.hypot(q.x - c[0], q.y - c[1])
            r_h = ray_polygon(c, a, hull)
            if r_h > r:
                r += (r_h - r) * smoothstep(a / (math.pi / 4))
                half[j] = Vector((c[0] + r * math.cos(a), c[1] + r * math.sin(a), z))
        half[0].x = 0.0
        half[-1].x = 0.0
        return self.half_to_columns(half, x_crease), c

    def cy_seat(self, z):
        """Centre y of the pelvis ring: the midline's front/back mid-extent."""
        pts = [v.co for v in self.body.verts(sb.TORSO | {"thigh_l", "thigh_r"})
               if abs(v.co.z - z) < 0.015]
        if not pts:
            return 0.0
        ys = [p.y for p in pts]
        return 0.5 * (min(ys) + max(ys))

    # --- rows ----------------------------------------------------------------------------------

    def row_levels(self):
        T = self.T
        rows = [("band", self.z_wt), ("band", self.z_wt - 0.5 * T["waistband_m"])]
        z = self.z_wb
        z_seat_end = self.z_cr + T["seat_last_above_m"]
        n = max(4, int(round((self.z_wb - z_seat_end) / T["row_seat_m"])))
        for k in range(n + 1):
            rows.append(("seat", lerp(self.z_wb, z_seat_end, k / n)))
        rows.append(("crotch", self.z_cr))
        z = self.z_cr
        zs = []
        while True:
            if z < T["break_zone_m"]:
                dz = T["row_break_m"]
            elif self.z_knee - 0.08 < z < self.z_knee + 0.08 or z > self.z_cr - 0.08:
                dz = T["row_knee_m"]
            else:
                dz = T["row_leg_m"]
            z -= dz
            if z <= self.z_back + 0.5 * T["row_break_m"]:
                break
            zs.append(z)
        zs.append(self.z_back)
        rows += [("leg", z) for z in zs]
        return rows

    def build_points(self):
        levels = self.row_levels()
        x_crease = self.leg_centre(self.z_cr)[0]
        P, kinds, centres = [], [], []
        for kind, z in levels:
            if kind in ("band", "seat"):
                cols, c = self.seat_columns(z, x_crease)
            elif kind == "crotch":
                cols, c = self.crotch_columns(z, P[-1][C_CF], P[-1][C_CB], x_crease)
            else:
                cols, c = self.leg_columns(z)
            P.append(cols)
            kinds.append(kind)
            centres.append(c)
        self.levels = levels
        self.P, self.kinds, self.centres = P, kinds, centres
        self.k_cr = kinds.index("crotch")
        return P

    # --- shaping passes ------------------------------------------------------------------------

    def outward(self, k, i):
        """Horizontal outward normal of column i on row k (from the ring tangent)."""
        row = self.P[k]
        a = row[(i - 1) % NCOL] if i > 0 else row[NCOL - 1]
        b = row[(i + 1) % NCOL]
        t = b - a
        t.z = 0.0
        n = Vector((t.y, -t.x, 0.0))   # rings run counter-clockwise seen from above
        return n.normalized() if n.length > 1e-9 else Vector((1, 0, 0))

    def bridge_columns(self):
        """Vertical bridging per column: a point lying inside the chord of its
        neighbours above and below (a concavity: the gluteal fold, the
        inguinal crease) moves out to it. The waistband, the crotch rows, the
        inseam-side columns and the leg below the knee (already a straight
        tube) are fixed."""
        T = self.T
        K = len(self.P)
        lo = 2
        moved = 0
        for _ in range(T["bridge_iters"]):
            for d in (1, 2):
                for k in range(lo + d, K - d):
                    if abs(k - self.k_cr) <= 1 or self.levels[k][1] < self.z_knee + 0.05:
                        continue
                    for i in range(C_CF + 1, C_CB):
                        p = self.P[k][i]
                        m = (self.P[k - d][i] + self.P[k + d][i]) * 0.5
                        n = self.outward(k, i)
                        dd = (m - p).dot(n)
                        if dd > 1e-5:
                            p += n * dd
                            moved += 1
        self.m["bridged"] = moved

    def hang_below_knee(self):
        """Below the knee the cloth hangs: per column, the profile (distance out
        from the row's centre against height) is replaced by its outer concave
        envelope, so the leg runs in straight lines knee -> calf -> hem and
        does not follow the calf back in. Moves are outward only, capped."""
        K = len(self.P)
        k0 = min(range(self.k_cr + 1, K), key=lambda k: abs(self.levels[k][1] - self.z_knee))
        moved, most = 0, 0.0
        for i in range(NCOL):
            prof = []
            for k in range(k0, K):
                c, p = self.centres[k], self.P[k][i]
                u = Vector((p.x - c[0], p.y - c[1], 0.0))
                prof.append((self.levels[k][1], u.length, u.normalized()))
            # upper hull of (z, w), walking down in z
            hull = []
            for z, w, _ in prof:
                while len(hull) >= 2:
                    (z1, w1), (z2, w2) = hull[-2], hull[-1]
                    # drop the middle point when it lies inside the chord
                    if (w2 - w1) * (z - z1) - (w - w1) * (z2 - z1) >= 0:
                        hull.pop()
                    else:
                        break
                hull.append((z, w))
            for j, (z, w, u) in enumerate(prof):
                for (za, wa), (zb, wb) in zip(hull, hull[1:]):
                    if zb <= z <= za:
                        env = wa + (wb - wa) * (za - z) / max(za - zb, 1e-9)
                        break
                else:
                    continue
                d = min(env - w, 0.015)
                if d > 1e-5:
                    self.P[k0 + j][i] += u * d
                    moved += 1
                    most = max(most, d)
        for k in range(k0, K):
            self.P[k][NCOL] = self.P[k][0].copy()
        self.m["hang_moved"] = moved
        self.m["hang_max_m"] = round(most, 4)

    def smooth_columns(self):
        K = len(self.P)
        for _ in range(2):
            for k in range(3, K - 1):
                if abs(k - self.k_cr) <= 1:
                    continue
                for i in range(C_CF + 1, C_CB):
                    a, p, b = self.P[k - 1][i], self.P[k][i], self.P[k + 1][i]
                    q = (a + b) * 0.5
                    p.x = 0.5 * p.x + 0.5 * q.x
                    p.y = 0.5 * p.y + 0.5 * q.y

    def hem_and_break(self):
        """Slant the hem (back at back_hem_m, front resting on the vamp), push
        the bottom rows clear of the shoe and the foot, add the break fold."""
        T = self.T
        K = len(self.P)
        z_front = self.z_front
        zone = T["slant_fade_m"]
        z_back = self.z_back
        for k in range(K):
            zn = self.levels[k][1]
            w = max(0.0, 1.0 - (zn - z_back) / zone)
            if w <= 0:
                continue
            # level round the back and the sides (over the shoe's collar), rising
            # to the front
            y0 = max(p.y for p in self.P[k])
            y1 = min(p.y for p in self.P[k])
            for i in range(NCOL + 1):
                p = self.P[k][i]
                fr = (y0 - p.y) / max(y0 - y1, 1e-6)     # 1 at the front, 0 at the back
                p.z = zn + (z_front - z_back) * fr ** T["hem_curve"] * w
        # clear of the shoe and the foot: a point over a top (the vamp, the
        # instep) at the front lifts onto it; one against a wall (the heel
        # counter, the ankle) moves out from the leg's axis. The lifts and the
        # pushes are then spread along the row (max with a falloff), so the
        # hem stays a smooth line
        moved = 0
        z_zone = self.ankle.z + 0.08
        for k in range(K):
            c = self.centres[k]
            if min(p.z for p in self.P[k]) > z_zone:
                continue
            lift, push = [0.0] * NCOL, [0.0] * NCOL
            for i in range(NCOL):
                p = self.P[k][i].copy()
                r = Vector((p.x - c[0], p.y - c[1], 0.0)).normalized()
                for _ in range(20):
                    t, n = self.top_at(p.x, p.y, p.z + 0.02)
                    if t is None or p.z >= t + T["shoe_clear_m"]:
                        break
                    if n is not None and n.z > 0.5 and p.y < c[1]:
                        lift[i] = t + T["vamp_rest_m"] - self.P[k][i].z
                        break
                    p += r * 0.002
                    push[i] += 0.002
                moved += lift[i] > 0 or push[i] > 0
            lift, push = spread_ring(lift, 1.5), spread_ring(push, 1.5)
            for i in range(NCOL):
                p = self.P[k][i]
                r = Vector((p.x - c[0], p.y - c[1], 0.0)).normalized()
                p += r * push[i]
                p.z += lift[i]
            self.P[k][NCOL] = self.P[k][0].copy()
        # the front of the hem settles onto the instep / vamp below it (blurred
        # along the hem: it may hover a little rather than kink)
        hem, c = self.P[K - 1], self.centres[K - 1]
        drop = [0.0] * NCOL
        for i in range(NCOL):
            p = hem[i]
            if p.y >= c[1]:
                continue
            t, n = self.top_at(p.x, p.y, p.z + 0.005)
            if t is None or n is None or n.z < 0.5:
                continue
            d = p.z - (t + T["vamp_rest_m"])
            drop[i] = d if 0 < d < 0.015 else 0.0
        for _ in range(2):
            drop = [0.25 * (drop[i - 1] + 2 * drop[i] + drop[(i + 1) % NCOL]) for i in range(NCOL)]
        for i in range(NCOL):
            for j, f in enumerate((1.0, 0.5, 0.25)):
                self.P[K - 1 - j][i].z -= drop[i] * f
        for j in range(3):
            self.P[K - 1 - j][NCOL] = self.P[K - 1 - j][0].copy()
        self.m["hem_settled_max_m"] = round(max(drop), 4)
        # rows stay ordered up each column
        for k in range(K - 2, -1, -1):
            for i in range(NCOL + 1):
                lo_ = self.P[k + 1][i].z + 0.006
                if self.P[k][i].z < lo_:
                    self.P[k][i].z = lo_
        self.m["hem_pushed"] = moved
        # the break: one soft fold across the front above the vamp (a ridge with
        # a shallow valley above it), front-weighted
        A, h1, h2, wd = T["break_m"], T["break_h_m"], T["break_h_m"] + 0.035, 0.016
        for k in range(K):
            c = self.centres[k]
            for i in range(NCOL + 1):
                p = self.P[k][i]
                a = math.atan2(p.y - c[1], p.x - c[0])
                fr = max(0.0, -math.sin(a)) ** 1.5
                if fr <= 0:
                    continue
                h = p.z - z_front
                bump = math.exp(-((h - h1) / wd) ** 2) - 0.35 * math.exp(-((h - h2) / wd) ** 2)
                if abs(bump) < 1e-3:
                    continue
                n = Vector((p.x - c[0], p.y - c[1], 0.0)).normalized()
                p += n * (A * fr * bump)

    def creases(self):
        """1.5 mm ridges: the front crease from the waistband, the back crease
        below the seat."""
        T = self.T
        h = T["crease_m"]
        for k in range(len(self.P)):
            z = self.levels[k][1]
            for i, z_from in ((C_FRONT, self.z_wb), (C_BACK, T["back_crease_from_m"])):
                if z > z_from or k < 2:
                    continue
                p = self.P[k][i]
                n = self.outward(k, i)
                ramp = smoothstep((z_from - z) / 0.06)
                p += n * (h * ramp)

    def tuck(self, outer_trees, z_limits):
        """Points outside an outer garment (jacket, waistcoat) above its hem, or
        closer than the gap under it, move in along the outward normal. The
        displacement is a field spread over the neighbours (max with a falloff,
        then blurred along the rows), so a point the rays miss moves with the
        rest: no spikes, no flaps. Midplane points stay on the midplane."""
        gap = self.T["tuck_gap_m"]
        K = len(self.P)
        cols = range(C_CF, C_CB + 1)
        N = {(k, i): self.outward(k, i) for k in range(K) for i in cols}
        D = [[0.0] * (NCOL + 1) for _ in range(K)]
        for tree, z_hem in zip(outer_trees, z_limits):
            if tree is None:
                continue
            for k in range(K):
                for i in cols:
                    p = self.P[k][i]
                    if p.z < z_hem - 0.01:
                        continue
                    n = N[k, i]
                    out = tree.ray_cast(p + n * 0.0005, n, 0.08)
                    if out[0] is not None:
                        if out[1].dot(n) <= 0:
                            continue
                        d = gap - (out[0] - p).dot(n)       # inside, too close
                    else:
                        hit = tree.ray_cast(p, -n, 0.08)
                        if hit[0] is None or hit[1].dot(n) <= 0:
                            continue
                        d = (p - hit[0]).dot(n) + gap        # outside
                    D[k][i] = max(D[k][i], d)
        S = [[0.0] * (NCOL + 1) for _ in range(K)]
        for k in range(K):
            for i in cols:
                if D[k][i] <= 0:
                    continue
                for dk in range(-2, 3):
                    for di in range(-3, 4):
                        kk, ii = k + dk, i + di
                        if 0 <= kk < K and C_CF <= ii <= C_CB:
                            f = math.exp(-(di / 2.0) ** 2 - (dk / 1.5) ** 2)
                            S[kk][ii] = max(S[kk][ii], D[k][i] * f)
        for _ in range(2):
            for k in range(K):
                row = S[k][:]
                for i in range(C_CF + 1, C_CB):
                    S[k][i] = max(D[k][i], 0.25 * (row[i - 1] + 2 * row[i] + row[i + 1]))
        # never into the body: where an outer garment cuts into the body (the
        # jacket's skirt over the thigh) the trousers keep their minimum ease
        # and that garment has to clear them
        moved = floored = 0
        for k in range(K):
            for i in cols:
                if S[k][i] <= 1e-6:
                    continue
                p = self.P[k][i]
                hit = self.tree.ray_cast(p, -N[k, i], 0.1)
                if hit[0] is not None and hit[1].dot(N[k, i]) > 0:
                    room = max(0.0, hit[3] - self.T["tuck_body_min_m"])
                    if S[k][i] > room:
                        S[k][i] = room
                        floored += 1
                q = p - N[k, i] * S[k][i]
                p.y = q.y
                if abs(p.x) >= MID_EPS:
                    p.x = q.x
                moved += 1
            if self.kinds[k] != "leg" and (S[k][C_CF] > 0 or S[k][C_CB] > 0):
                self.rechord(k)
        self.m["tucked"] = moved
        self.m["tuck_floored"] = floored
        self.m["tuck_max_m"] = round(max(max(r) for r in S), 4)

    def rechord(self, k):
        """Re-lay the inseam-side columns of a seat / crotch row on the chord CB -> CF."""
        row = self.P[k]
        cf, cb = row[C_CF], row[C_CB]
        mid = cb.lerp(cf, 0.5)
        n0, n5 = SEGMENTS[0], SEGMENTS[5]
        for i in range(n0):
            row[i] = mid.lerp(cf, i / n0)
        for i in range(1, n5 + 1):
            row[C_CB + i] = cb.lerp(mid, i / n5)
        for i in list(range(0, C_CF + 1)) + list(range(C_CB, NCOL + 1)):
            row[i].x = 0.0

    # --- mesh ----------------------------------------------------------------------------------

    def build_mesh(self):
        """Verts for both legs (right = mirror), the grids, UVs, tags, weights, marks."""
        G = self.G
        bm = G.bm
        K = len(self.P)
        self.grids = {}
        for side in ("l", "r"):
            s = 1.0 if side == "l" else -1.0
            V = []
            for k in range(K):
                row = []
                for i in range(NCOL):
                    p = self.P[k][i]
                    row.append(bm.verts.new(Vector((s * p.x, p.y, p.z))))
                row.append(row[0])
                V.append(row)
            self.weight_rows(V, side)
            # arc lengths along each row (for the metric u)
            arcs = []
            for k in range(K):
                pts = [v.co for v in V[k]]
                arcs.append(arc_params(pts))
            # u sign: the right side is mirrored, keep the UV winding positive
            us = 1.0 if side == "l" else -1.0
            b0 = 2  # the waistband seam row (shared by the band and the panels)
            # front panel: columns 0..C_SIDE, u from the front crease
            fg = G.grid(f"front_{side}")
            for k in range(b0, K):
                cols = V[k][0:C_SIDE + 1]
                u0 = arcs[k][C_FRONT]
                fg.add_shared_row(cols, [(us * (arcs[k][i] - u0), V[k][i].co.z) for i in range(0, C_SIDE + 1)])
            bg = G.grid(f"back_{side}")
            for k in range(b0, K):
                cols = V[k][C_SIDE:NCOL + 1]
                u0 = arcs[k][C_BACK]
                bg.add_shared_row(cols, [(us * (arcs[k][i] - u0), V[k][i].co.z) for i in range(C_SIDE, NCOL + 1)])
            # waistband: rows 0..b0-1, CF -> CB
            wg = G.grid(f"band_{side}")
            for k in range(0, b0 + 1):
                cols = V[k][C_CF:C_CB + 1]
                u0 = arcs[k][C_CF]
                wg.add_shared_row(cols, [(us * (arcs[k][i] - u0), V[k][i].co.z) for i in range(C_CF, C_CB + 1)])
            flip = (side == "r")

            for g, tag, c0 in ((fg, TAG[f"front_{side}"], 0), (bg, TAG[f"back_{side}"], C_SIDE),
                               (wg, TAG[f"band_{side}"], C_CF)):
                def skip(kk, i, g=g):
                    a, b = g.rows[kk][i], g.rows[kk][i + 1]
                    c, d = g.rows[kk + 1][i], g.rows[kk + 1][i + 1]
                    return all(abs(v.co.x) < MID_EPS for v in (a, b, c, d))
                g.fill(G.uv, G.tag, tag, skip=skip, flip=flip)
            self.grids[side] = (fg, bg, wg, V)
        self.mark_crease_edges()

    def weight_rows(self, V, side):
        """k-nearest inverse-distance weights from the body. The leg follows its
        own thigh/calf (and the pelvis near the crotch); the seat and the
        waistband the pelvis and spine_01. Midline points get symmetric weights."""
        G = self.G
        body = self.body
        o = "r" if side == "l" else "l"
        seat = {"pelvis", "spine_01", "thigh_l", "thigh_r"}

        def knn(co, bones, k=4):
            kd, vs = body.kd(bones)
            out = {}
            tot = 0.0
            for (_, idx, d) in kd.find_n(co, k):
                w = 1.0 / max(d, 0.004) ** 2
                tot += w
                for g, x in vs[idx][body.dl].items():
                    n = body.names[g]
                    if n in body.bones and x > 1e-4:
                        out[n] = out.get(n, 0.0) + w * x
            return {n: x / tot for n, x in out.items()}

        def swap(w):
            out = {}
            for n, x in w.items():
                if n.endswith(f"_{side}"):
                    n = n[:-2] + f"_{o}"
                elif n.endswith(f"_{o}"):
                    n = n[:-2] + f"_{side}"
                out[n] = out.get(n, 0.0) + x
            return out

        for k, row in enumerate(V):
            for i, v in enumerate(row[:-1]):
                # weights are computed on the left leg's (unmirrored) point
                p = self.P[k][i]
                kind = self.kinds[k]
                if kind in ("band", "seat") or (kind == "crotch"):
                    w = knn(p, seat)
                    if abs(p.x) < MID_EPS:
                        w = {n: 0.5 * x for n, x in w.items()}
                        for n, x in swap(w).items():
                            w[n] = w.get(n, 0.0) + x
                else:
                    # the leg follows the thigh and the calf (never the foot)
                    w = knn(p, {"pelvis", "thigh_l", "calf_l"})
                if side == "r":
                    w = swap(w) if abs(p.x) >= MID_EPS else w
                # keep the 4 largest, normalise
                items = sorted(w.items(), key=lambda kv: -kv[1])[:4]
                tot = sum(x for _, x in items) or 1.0
                v[G.dl].clear()
                for n, x in items:
                    v[G.dl][G.gidx[n]] = x / tot
        return V

    def mark_crease_edges(self):
        for side in ("l", "r"):
            fg, bg, wg, V = self.grids[side]
            K = len(V)
            for k in range(2, K - 1):
                for i, z_from in ((C_FRONT, self.z_wb), (C_BACK, self.T["back_crease_from_m"])):
                    if V[k + 1][i].co.z > z_from:
                        continue
                    e = self.G.bm.edges.get([V[k][i], V[k + 1][i]])
                    if e is not None:
                        e.smooth = False

    def marks(self):
        G, T = self.G, self.T
        out = {}
        for side in ("l", "r"):
            fg, bg, wg, V = self.grids[side]
            tf, tb, tw = TAG[f"front_{side}"], TAG[f"back_{side}"], TAG[f"band_{side}"]
            n = len(fg.rows)
            k_cr = self.k_cr - 2     # panel grid rows start at the waistband seam (row 2)
            below = range(k_cr, n)
            # creases
            G.mark_column(tf, fg, C_FRONT, "crease", rows=range(0, n))
            kb = [k for k in range(n) if fg.rows[k][0].co.z <= T["back_crease_from_m"]]
            G.mark_column(tb, bg, C_BACK - C_SIDE, "crease", rows=kb)
            # seams: outseam (both panel edges), inseam, centre back, waistband seam, hem
            G.mark_column(tf, fg, C_SIDE, "seam")
            G.mark_column(tb, bg, 0, "seam")
            G.mark_column(tf, fg, 0, "seam", rows=below)
            G.mark_column(tb, bg, NCOL - C_SIDE, "seam", rows=below)
            G.mark_column(tb, bg, C_CB - C_SIDE, "seam", rows=range(0, k_cr + 1))
            G.mark_row(tf, fg, 0, "seam")
            G.mark_row(tb, bg, 0, "seam")
            G.mark_row(tf, fg, n - 1, "edge", inside_sign=1.0)
            G.mark_row(tb, bg, n - 1, "edge", inside_sign=1.0)
            G.mark_row(tw, wg, 0, "edge", inside_sign=-1.0)
            # fly J-stitch, left front: 3.5 cm from CF down to 6 cm above the
            # crotch, curving into CF
            if side == "l":
                pts = []
                for k in range(0, k_cr + 1):
                    u_cf, v = fg.uvs[k][C_CF]
                    z = v
                    if z < self.z_cr + T["fly_end_above_crotch_m"]:
                        continue
                    pts.append((u_cf + T["fly_w_m"], v))
                if pts:
                    u_cf, v_last = pts[-1][0] - T["fly_w_m"], pts[-1][1]
                    for j in range(1, 5):
                        t = j / 4
                        pts.append((u_cf + T["fly_w_m"] * math.cos(t * math.pi / 2),
                                    v_last - 0.03 * math.sin(t * math.pi / 2)))
                    G.mark(tf, "topstitch", pts, {"pitch_m": 0.003, "height": 0.0003})
            # slanted side pocket: from the waistband seam 4 cm in front of the
            # outseam, down to the outseam 17 cm lower
            u_side = fg.uvs[0][C_SIDE][0]
            k_end = min(range(n), key=lambda k: abs(fg.rows[k][C_SIDE].co.z - (self.z_wb - T["pocket_drop_m"])))
            u_side_end, v_end = fg.uvs[k_end][C_SIDE]
            us = 1.0 if side == "l" else -1.0
            G.mark(tf, "edge", [(u_side - us * T["pocket_in_m"], fg.uvs[0][C_SIDE][1]),
                                (u_side_end - us * 0.006, v_end)], {"inside_sign": us})
            # jetted back pocket, centred on the back crease line
            z_p = self.z_wb - T["back_pocket_below_m"]
            u0 = 0.0
            G.mark(tb, "jet", [(u0 - us * 0.5 * T["back_pocket_w_m"], z_p),
                               (u0 + us * 0.5 * T["back_pocket_w_m"], z_p)])
            # side adjuster on the waistband (a tab at the side)
            u_s, v0 = wg.uvs[0][C_SIDE - C_CF]
            v_top = wg.uvs[-1][C_SIDE - C_CF][1]
            vm = 0.5 * (v0 + v_top)
            G.mark(tw, "edge", [(u_s - us * 0.07, vm - 0.008), (u_s - us * 0.02, vm - 0.008),
                                (u_s - us * 0.02, vm + 0.008), (u_s - us * 0.07, vm + 0.008),
                                (u_s - us * 0.07, vm - 0.008)], {"inside_sign": 1.0, "stitch_in_m": 0.002})
        return out

    # --- measurements --------------------------------------------------------------------------

    def measure(self):
        m = dict(self.m)
        m["waistband_top_z"] = round(self.z_wt, 4)
        m["waistband_to_stature"] = round(self.z_wt / self.stature, 4)
        m["back_hem_z"] = round(min(p.z for p in self.P[-1]), 4)

        def flat(k):
            pts = self.P[k][:NCOL] + [self.P[k][0]]
            return round(0.5 * sum((b - a).length for a, b in zip(pts, pts[1:])), 4)
        m["leg_opening_flat_m"] = flat(len(self.P) - 1)
        k_knee = min(range(self.k_cr + 1, len(self.P)), key=lambda k: abs(self.levels[k][1] - self.z_knee))
        m["knee_flat_m"] = flat(k_knee)
        m["knee_z"] = round(self.levels[k_knee][1], 4)
        k_th = min(range(self.k_cr + 1, len(self.P)), key=lambda k: abs(self.levels[k][1] - (self.z_cr - 0.03)))
        m["thigh_flat_m"] = flat(k_th)

        # seat: the girth as a tape takes it (convex, both halves) at the
        # body's fullest seat row, the body's and the trousers'
        def girth(pts):
            hull = convex_hull([(x, y) for x, y in pts])
            return sb.arc_length([Vector((x, y, 0)) for x, y in hull], closed=True)

        best = None
        for k in range(len(self.P)):
            if self.kinds[k] != "seat":
                continue
            z = self.levels[k][1]
            c = (0.0, self.cy_seat(z))
            ring = ray_ring(self.tree, c, z, reach=0.4)
            n = len(ring)
            g = girth([(c[0] + r * math.cos(TAU * i / n), c[1] + r * math.sin(TAU * i / n))
                       for i, r in enumerate(ring)])
            if best is None or g > best[0]:
                best = (g, k)
        g_body, k_s = best
        half = self.P[k_s][C_CF:C_CB + 1]
        g_tr = girth([(q.x, q.y) for q in half] + [(-q.x, q.y) for q in half])
        m["seat_z"] = round(self.levels[k_s][1], 4)
        m["seat_body_girth_m"] = round(g_body, 4)
        m["seat_girth_m"] = round(g_tr, 4)
        m["seat_ease_m"] = round(g_tr - g_body, 4)
        m["rows"] = len(self.P)
        m["columns_per_leg"] = NCOL
        return m


def convex_hull(pts):
    """2D convex hull (monotone chain), counter-clockwise, no repeated point."""
    pts = sorted(set(pts))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def columns_from_anchors_seg(pts, anchors, segments):
    cols = []
    for (a, b), n in zip(zip(anchors, anchors[1:]), segments):
        seg = resample(pts, a, b, n)
        cols.extend(seg[:-1])
    cols.append(pts[anchors[-1]].copy())
    return cols


def build(b, body, T, arm, like, mats, part, stature, shoes=None, outer=()):
    """Build the trousers. outer: [(object, hem z)] garments they must stay
    inside (the jacket, the waistcoat). Returns (object, measurements, marks)."""
    G = sb.Garment(part.format("trousers"), arm, body)
    z_wt = waistband_z(stature, T)
    shoe_tree = sb.bvh_of([shoes]) if shoes is not None else None
    tr = Trousers(G, body, T, stature, z_wt, shoe_tree)
    # thigh flat width of the eased body just below the crotch (the cut starts there)
    probe, _ = _eased_thigh(tr, tr.z_cr - 0.03)
    tr.thigh_flat = 0.5 * sb.arc_length(probe, closed=True)
    tr.m["thigh_body_eased_flat_m"] = round(tr.thigh_flat, 4)
    tr.prepare_cuts(heel_of(shoes))
    tr.build_points()
    tr.bridge_columns()
    tr.smooth_columns()
    tr.hang_below_knee()
    if outer and T.get("tuck", True):
        trees = [sb.bvh_of([o]) for o, _ in outer]
        tr.tuck(trees, [z for _, z in outer])
    tr.creases()
    tr.hem_and_break()
    tr.build_mesh()
    tr.marks()
    ob = G.finish(b, like, mats["wool"])
    m = tr.measure()
    m["finish"] = G.stats
    return ob, m, G.marks


def heel_of(shoes):
    """The left shoe's points (world space), [] when there are no shoes."""
    if shoes is None:
        return []
    mw = shoes.matrix_world
    return [p for p in (mw @ v.co for v in shoes.data.vertices) if p.x > 0]


def _eased_thigh(tr, z):
    """The eased body ring of the left thigh at z (no cut), for the pattern's thigh width."""
    c = tr.leg_centre(z)
    body = ray_ring(tr.tree, c, z, reach=0.25)
    n = len(body)
    body = sb.smooth_ring(sb.chord_fill(sb.smooth_ring(body, 1), ks=(2, 4, 8, 12), iters=2), 1)
    eased = [body[i] + tr.leg_ease(z, TAU * (i + 0.5) / n) for i in range(n)]
    pts = polyline_from_polar(c, eased, z, math.pi)
    for p in pts:
        p.x = max(p.x, tr.T["inner_gap_m"])
    return pts, c
