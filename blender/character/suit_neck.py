"""The collar zone (bench/m1/suit.md §2 "Collar zone"): shirt collar, tie knot
and jacket collar, built in one cylindrical frame around the neck so the
layers can never cross.

    NeckFrame   the body's neck as r(angle, z): rays from a vertical axis
                through the neck centre, low-passed round the neck; the shirt
                band (base, top, radii) and the shirt collar's outer surface
                as functions of the angle, shared by the jacket and the shirt
    shirt       band (stand) closed at the front, a fold, and a fall that
                covers the band and spreads into two points lying on the chest;
                a closure patch fills the band between the leading edges
    knot        a four-in-hand: tapered, the wearer's left side fuller, a
                diagonal wrap edge, the top rolling back under the collar
    jacket      stand from the neckline up to a fold that sits `reveal_m`
                under the shirt band's top, then a fall draped over the stand
                and the block (radial profile per column, monotone outward);
                the front columns blend into the collar end, which lies on the
                lapel's top edge (the gorge seam) to the notch and turns up to
                the collar point

Ordering by construction: body + gap < shirt band < shirt fall (+ t) <
jacket stand (+ clearance) < jacket fall. Angles: a = atan2(y - cy, x), the
front (-Y) is -pi/2, the wearer's left (+X) is 0, the back pi/2.
"""

import math

import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from . import suit_build as sb
from .suit_build import TAU, lerp, smoothstep

NECK = {"neck_01", "head"}
UP = Vector((0, 0, 1))
DEBUG = bool(__import__("os").environ.get("SUIT_NECK_DEBUG"))
DUMP = __import__("os").environ.get("SUIT_NECK_DUMP")   # diagnosis: the jacket collar's grid as JSON


def _dump(stage, cols, i_e):
    if not DUMP:
        return
    import json
    path = f"{DUMP}_{stage}.json"
    with open(path, "w") as f:
        json.dump({"i_e": i_e, "cols": [[[round(c, 5) for c in p] for p in col] for col in cols]}, f)


def lowpass(vals, harmonics):
    f = np.fft.rfft(np.asarray(vals, dtype=float))
    f[harmonics + 1:] = 0
    return list(np.fft.irfft(f, len(vals)))


def envelope(vals, harmonics, iters=6):
    """A smooth curve round the ring that stays on or above `vals`."""
    s = list(vals)
    for _ in range(iters):
        s = lowpass([max(a, b) for a, b in zip(s, vals)], harmonics)
    d = max(0.0, max(v - x for v, x in zip(vals, s)))
    return [x + d for x in s]


def wrap(a):
    """Angle into (-pi/2 - pi, -pi/2 + pi]: continuous across the back, cut at the front."""
    while a <= -math.pi / 2 - math.pi:
        a += TAU
    while a > -math.pi / 2 + math.pi:
        a -= TAU
    return a


class NeckFrame:
    def __init__(self, body, supra, C):
        self.body, self.supra, self.C = body, supra, C
        self.tree = body.bvh()
        nj = body.joint("neck_01")
        self.z_neck = nj.z
        # the axis: through the neck's front/back midpoints (the neck leans
        # forward), a straight line fitted over the neck's height
        zs, ys = [], []
        for k in range(8):
            z = lerp(supra + 0.02, nj.z + 0.005, k / 7)
            o = Vector((0.0, nj.y, z))
            f = self.tree.ray_cast(o, Vector((0, -1, 0)), 0.3)
            bk = self.tree.ray_cast(o, Vector((0, 1, 0)), 0.3)
            if f[0] is not None and bk[0] is not None:
                zs.append(z)
                ys.append(0.5 * (f[0].y + bk[0].y))
        if len(zs) >= 2:
            k_, y0_ = np.polyfit(zs, ys, 1)
        else:
            k_, y0_ = 0.0, nj.y
        self._ck, self._c0 = float(k_), float(y0_)
        self.na = 96
        self.z0, self.dz, self.nz = supra - 0.08, 0.004, 50
        R = []
        for k in range(self.nz):
            z = self.z0 + k * self.dz
            c = self.cyz(z)
            row = []
            for i in range(self.na):
                a = TAU * i / self.na
                d = Vector((math.cos(a), math.sin(a), 0.0))
                o = Vector((0.0, c, z))
                hit = self.tree.ray_cast(o, d, 0.5)
                # skip a surface right at the axis (under the chin)
                if hit[0] is not None and hit[3] < 0.012:
                    h0 = hit[3] + 1e-4
                    hit = self.tree.ray_cast(o + d * h0, d, 0.5)
                    row.append(h0 + hit[3] if hit[0] is not None else None)
                    continue
                row.append(hit[3] if hit[0] is not None else None)
            known = [i for i, r in enumerate(row) if r is not None]
            for i in range(self.na):
                if row[i] is None:
                    j = min(known, key=lambda j: min(abs(j - i), self.na - abs(j - i))) if known else None
                    row[i] = row[j] if j is not None else 0.3
            R.append(row)
        self.R = np.array(R)
        self._band()
        if DEBUG:
            print(f"[neck] axis y = {self._c0:.4f} + {self._ck:.3f} z  (y at supra {self.cyz(supra):.4f}, "
                  f"at neck {self.cyz(nj.z):.4f}) supra={supra:.4f} neck_z={nj.z:.4f}")
            for k in range(0, self.nz, 2):
                z = self.z0 + k * self.dz
                print(f"[neck] z={z:.3f} " + " ".join(f"{d:4d}:{self.r_body(math.radians(d), z):.3f}"
                                                     for d in (-90, -60, -30, 0, 30, 60, 90)))
            for d in range(-90, 91, 15):
                a = math.radians(d)
                print(f"[neck] band a={d:4d} zb={self.zb(a):.4f} zt={self.zt(a):.4f} rb={self.rb(a):.4f} "
                      f"rt={self.rt(a):.4f}")

    def cyz(self, z):
        return self._c0 + self._ck * z

    # --- the body --------------------------------------------------------------------------

    def r_body(self, a, z):
        x = (a % TAU) / TAU * self.na
        i = int(math.floor(x)) % self.na
        t = x - math.floor(x)
        k = (z - self.z0) / self.dz
        k0 = min(max(int(math.floor(k)), 0), self.nz - 2)
        u = min(max(k - k0, 0.0), 1.0)
        j = (i + 1) % self.na
        r0 = self.R[k0, i] * (1 - t) + self.R[k0, j] * t
        r1 = self.R[k0 + 1, i] * (1 - t) + self.R[k0 + 1, j] * t
        return float(r0 * (1 - u) + r1 * u)

    def r_body_max(self, a, z0, z1, n=6):
        return max(self.r_body(a, lerp(z0, z1, k / (n - 1))) for k in range(n))

    def point(self, a, z, r):
        return Vector((r * math.cos(a), self.cyz(z) + r * math.sin(a), z))

    def polar(self, p):
        """(a, z, r) of a point."""
        c = self.cyz(p.z)
        return math.atan2(p.y - c, p.x), p.z, math.hypot(p.x, p.y - c)

    def radial(self, p):
        """Horizontal unit vector from the axis through p."""
        a = self.polar(p)[0]
        return Vector((math.cos(a), math.sin(a), 0.0))

    # --- the shirt band ----------------------------------------------------------------------

    @staticmethod
    def back(a):
        return 0.5 + 0.5 * math.sin(a)   # 0 at the front centre, 1 at the back

    def _band(self):
        """Band base: where the neck meets the trapezius / chest (scanning down
        from the upper neck until the body flares by more than base_flare_m),
        smoothed round the neck and kept on or above that line; at least
        base_above_supra_m over the suprasternale at the front."""
        C = self.C
        n = self.na
        z_ref = self.z_neck - 0.004
        z_min = self.supra + C["base_above_supra_m"]
        raw = []
        for i in range(n):
            a = TAU * i / n
            r_ref = self.r_body(a, z_ref)
            z = z_ref
            while z > z_min and self.r_body(a, z - 0.001) <= r_ref + C["base_flare_m"]:
                z -= 0.001
            raw.append(z)
        # never lower toward the back than at the sides (the back of the neck
        # has no flare to find): a line rising from the front to the highest
        # side value, whichever is higher
        z_hi = max(raw)
        z_lo = raw[int(0.75 * n) % n]   # the front centre (a = -pi/2)
        raw = [max(z, lerp(z_lo, z_hi, self.back(TAU * i / n) ** C["base_rise_pow"])) for i, z in enumerate(raw)]
        zb = envelope(raw, 3)
        self.zb_i, self.zt_i, rb, rt = [], [], [], []
        for i in range(n):
            a = TAU * i / n
            bk = self.back(a)
            z_b = max(zb[i], z_min)
            z_t = z_b + lerp(C["stand_front_m"], C["stand_m"], bk ** 0.5)
            self.zb_i.append(z_b)
            self.zt_i.append(z_t)
            rt.append(self.r_body_max(a, z_t - 0.014, z_t + 0.002) + C["gap_m"])
            rb.append(self.r_body_max(a, z_b - C.get("base_win_m", 0.008), z_b + 0.006) + C["gap_m"])
        rt = envelope(rt, 5)
        # the band is a ruled strip base -> top: widen the base where the neck
        # between would come within the gap
        for i in range(n):
            a = TAU * i / n
            for t in (0.2, 0.4, 0.6, 0.8):
                need = self.r_body(a, lerp(self.zb_i[i], self.zt_i[i], t)) + C["gap_m"]
                rb[i] = max(rb[i], (need - rt[i] * t) / (1 - t))
            rb[i] = max(rb[i], rt[i] + 0.001)
        self.rb_i = envelope(rb, 5)
        self.rt_i = rt

    def _ring(self, vals, a):
        return sb.sample_ring(vals, a + math.pi / self.na)  # sample_ring bins are centred

    def zb(self, a):
        return self._ring(self.zb_i, a)

    def zt(self, a):
        return self._ring(self.zt_i, a)

    def rb(self, a):
        return self._ring(self.rb_i, a)

    def rt(self, a):
        return self._ring(self.rt_i, a)

    def band_r(self, a, z):
        zb, zt = self.zb(a), self.zt(a)
        t = min(max((z - zb) / max(zt - zb, 1e-6), 0.0), 1.0)
        return lerp(self.rb(a), self.rt(a), t)

    def fall_r(self, a, z):
        """The shirt collar's fall (its outer surface) at (a, z): over the band
        by fall_off_m, flaring out below the band's base, never closer to the
        body than shirt offset + lay."""
        C = self.C
        zb = self.zb(a)
        if z >= zb:
            r = self.band_r(a, z) + C["fall_off_m"]
        else:
            r = self.rb(a) + C["fall_off_m"] + C["flare"] * (zb - z)
        return max(r, self.r_body(a, z) + C["body_clear_m"])

    def shirt_outer(self, a, z0, z1):
        """Max radius of the shirt collar between heights z0 and z1 at angle a
        (the jacket collar's stand stays outside this)."""
        top = self.zt(a) + 0.004
        zs = [lerp(z0, z1, k / 5) for k in range(6)]
        rs = [self.fall_r(a, z) for z in zs if self.zb(a) - self.C["overhang_m"] - 0.002 <= z <= top]
        return max(rs) if rs else 0.0


# --- shirt collar ----------------------------------------------------------------------------

def build_shirt_collar(nf, G, C, weight_bones, tag):
    """Band + fold + fall in one grid (columns round the neck from the wearer's
    left leading edge, round the back, to the right leading edge), and a
    closure patch across the front between the leading edges. Returns info."""
    a_front = -math.pi / 2
    r_front = nf.rt(a_front)
    a_g = math.asin(min(0.9, C["lead_half_gap_m"] / r_front))
    M = C["columns"]
    c_s = C["point_cols_frac"]

    # the collar point (tip) of each side, on the chest
    zt_f = nf.zt(a_front)
    al = math.radians(C["lead_deg"])
    tips = {}
    for s in (1, -1):
        x_tip = s * (C["lead_half_gap_m"] + C["point_m"] * math.sin(al))
        z_tip = zt_f - C["point_m"] * math.cos(al)
        lo, hi = (a_front, 0.0) if s > 0 else (-math.pi, a_front)
        for _ in range(40):   # bisection on x(a) = r(a) cos(a)
            mid = 0.5 * (lo + hi)
            x = nf.fall_r(mid, z_tip) * math.cos(mid)
            if (x < x_tip) == (s > 0):
                lo, hi = (mid, hi) if s > 0 else (lo, mid)
            else:
                lo, hi = (lo, mid) if s > 0 else (mid, hi)
        tips[s] = (0.5 * (lo + hi), z_tip)

    def a_fold(c):
        return a_front + a_g + (TAU - 2 * a_g) * c

    def edge_at(c):
        """(a, z) of the fall's outer edge for column c."""
        a = a_fold(c)
        cf = min(c, 1 - c)
        s = 1 if c < 0.5 else -1
        z_back = nf.zb(a) - C["overhang_m"]
        if cf >= c_s:
            return a, z_back
        t = smoothstep(cf / c_s) if cf > 0 else 0.0
        a_t, z_t = tips[s]
        a_t = a_t if s > 0 else a_t + TAU   # continuous with a_fold on the right side
        a_side = a_fold(c_s if s > 0 else 1 - c_s)
        return lerp(a_t, a_side, t), lerp(z_t, nf.zb(a_side) - C["overhang_m"], t ** 0.7)

    NF = C["fall_rows"]
    rows = [[] for _ in range(5 + NF)]
    uvs = [[] for _ in range(5 + NF)]
    t_f = C["fall_off_m"]
    for ci in range(M + 1):
        c = ci / M
        a = a_fold(c)
        zb, zt = nf.zb(a), nf.zt(a)
        rb, rt = nf.rb(a), nf.rt(a)
        col = [nf.point(a, zb, rb), nf.point(a, lerp(zb, zt, 0.5), lerp(rb, rt, 0.5)),
               nf.point(a, zt, rt), nf.point(a, zt + 0.0028, rt + 0.6 * t_f + 0.0006)]
        a_e, z_e = edge_at(c)
        z_top = zt - 0.0005
        fall = []
        for j in range(NF + 1):
            v = j / NF
            aa = lerp(a, a_e, v ** 1.3)
            zz = lerp(z_top, z_e, v)
            fall.append(nf.point(aa, zz, nf.fall_r(aa, zz)))
        col += fall
        u = c * TAU * r_front
        vv = 0.0
        prev = None
        for j, p in enumerate(col):
            if prev is not None:
                vv += (p - prev).length
            prev = p
            rows[j].append(p)
            uvs[j].append((u, vv))
    # smooth the fall rows across columns (the tips bend them), then re-impose
    # the radial order
    for _ in range(3):
        for j in range(5, 4 + NF + 1):
            co = [p.copy() for p in rows[j]]
            for i in range(1, M):
                rows[j][i] = (co[i - 1] + 2 * co[i] + co[i + 1]) / 4
        for j in range(5, 4 + NF + 1):
            for i in range(M + 1):
                a, z, r = nf.polar(rows[j][i])
                need = nf.fall_r(a, z)
                if r < need:
                    rows[j][i] = nf.point(a, z, need)
    # an edge lip (the fall's edge turned under by 2.5 mm)
    lip = []
    for i in range(M + 1):
        p, q = rows[-1][i], rows[-2][i]
        a, z, r = nf.polar(p)
        lip.append(p + (q - p).normalized() * 0.0025 - Vector((math.cos(a), math.sin(a), 0)) * 0.0012)
    rows.append(lip)
    uvs.append([(u, v + 0.003) for (u, v) in uvs[-1]])

    g = G.grid("collar")
    for j, row in enumerate(rows):
        g.add_row(row, uvs[j])
    g.fill(G.uv, G.tag, tag, flip=True)
    for row in g.rows:
        G.weight(row, weight_bones)
    G.mark_row(tag, g, len(g.rows) - 2, "edge", inside_sign=-1.0, stitch_in_m=0.004)
    G.mark_row(tag, g, 2, "topstitch", pitch_m=0.002, height=0.00015)

    # closure: the band across the front gap, a hair outside the band ends
    cl = G.grid("collar_front")
    span = a_g + C["closure_overlap_rad"]
    K = 8
    for j, t in enumerate((0.0, 0.5, 1.0)):
        pts, uv = [], []
        for i in range(K + 1):
            a = a_front - span + 2 * span * i / K
            zb, zt = nf.zb(a), nf.zt(a)
            z = lerp(zb, zt, t)
            pts.append(nf.point(a, z, nf.band_r(a, z) + 0.0004))
            uv.append((0.9 + 2 * span * r_front * i / K, 0.01 + (zt - zb) * t))
        cl.add_row(pts, uv)
    cl.fill(G.uv, G.tag, tag, flip=C.get("closure_flip", False))
    for row in cl.rows:
        G.weight(row, weight_bones)
    # the shirt's body round the collar's root: a strip from inside the band's
    # base outward over the trapezius and the upper chest (draped by vertical
    # rays, ring_off_m off the skin), so what shows between the shirt collar
    # and the jacket collar is shirt, not skin. Open across the front, where
    # the shirt front panel is.
    K = C["ring_columns"]
    a_open, a_back = C["ring_open_rad"], math.radians(C["ring_to_deg"])
    steps = C["ring_steps_m"]
    down = Vector((0, 0, -1))
    roots = []
    for s in (1, -1):
        rg = G.grid("collar_root_l" if s > 0 else "collar_root_r")
        ring_rows = [[] for _ in range(len(steps) + 2)]
        for i in range(K + 1):
            a = a_front + s * lerp(a_open, a_back, i / K)
            zb, rb = nf.zb(a), nf.rb(a)
            # inside the band, then out under its base edge (never through the band)
            ring_rows[0].append(nf.point(a, zb + 0.004, nf.band_r(a, zb + 0.004) - 0.0015))
            ring_rows[1].append(nf.point(a, zb - 0.002, max(rb - 0.001, nf.r_body(a, zb - 0.002) + 0.002)))
            prev = ring_rows[1][-1]
            for k, dz in enumerate(steps, start=1):
                if C.get("ring_follow", True):
                    # down the skin in the neck frame, ring_off_m off it
                    z = zb - 0.002 - dz
                    p = nf.point(a, z, nf.r_body(a, z) + C["ring_off_m"])
                else:
                    q = nf.point(a, zb, rb + dz)
                    hit = nf.tree.ray_cast(q + Vector((0, 0, 0.06)), down, 0.2)
                    if hit[0] is not None and hit[0].z > prev.z - C["ring_drop_m"]:
                        n = hit[1] if hit[1].z > 0 else -hit[1]
                        p = hit[0] + n * C["ring_off_m"]
                        p.z = min(p.z, prev.z, zb - 0.002)
                    else:
                        p = nf.point(a, prev.z - 0.002, nf.polar(prev)[2] + 0.004)
                ring_rows[k + 1].append(p)
                prev = p
        for j, row in enumerate(ring_rows):
            rg.add_row(row, [(1.2 + 0.4 * i / K, 0.01 * j) for i in range(K + 1)])
        rg.fill(G.uv, G.tag, tag, flip=(s > 0))
        for row in rg.rows:
            G.weight(row, weight_bones)
        roots.append(rg)
    return {"grid": g, "closure": cl, "root": roots, "z_top_front": zt_f, "z_base_front": nf.zb(a_front),

            "lead_half_angle_rad": round(a_g, 4),
            "tip_l": [round(x, 4) for x in tips[1]], "tip_r": [round(x, 4) for x in tips[-1]]}


# --- tie knot --------------------------------------------------------------------------------

def build_knot(nf, G, T, C, tag, front_y=None):
    """Four-in-hand knot in front of the band at the centre front. Rows from
    the top (rolled back under the collar fold) to the bottom (where the blade
    comes out). Returns (grid, z_bottom, y_front_bottom)."""
    a_front = -math.pi / 2
    zt = nf.zt(a_front)
    W, H, D = T["knot_w_m"], T["knot_h_m"], T["knot_d_m"]
    segs = 16
    nrows = 9
    g = G.grid("knot")
    for k in range(nrows + 1):
        v = k / nrows
        z = zt + T["knot_top_above_band_m"] - H * v
        # band surface behind this row (the band leans back toward the base)
        rb = nf.band_r(a_front, min(z, zt))
        yb = nf.cyz(z) - rb - 0.0008
        if front_y is not None:   # never behind the shirt front (the chest bulges under the band)
            fy = front_y(z)
            if fy is not None:
                yb = min(yb, fy - 0.0015)
        w = W * (1 - T["knot_taper"] * v ** 1.1) * (0.88 + 0.12 * smoothstep(v / 0.18))
        d = D * (0.55 + 0.45 * smoothstep(v / 0.22)) * (1 - 0.35 * v ** 1.5)
        cx = T["knot_skew_m"] * (v - 0.5)
        pts, uv = [], []
        for i in range(segs + 1):
            ph = lerp(-math.pi * 0.5, math.pi * 0.5, i / segs)
            sx = math.sin(ph)
            full = 1 + T["knot_full"] * max(sx, 0.0)            # the wearer's left fuller
            x = cx + 0.5 * w * sx * full
            front = math.cos(ph) ** 0.55
            # the wrap edge: a diagonal step across the front, upper left to
            # lower right (the four-in-hand's last turn)
            xd = 0.5 * w * (0.55 - 1.3 * v)
            step = T["knot_wrap_m"] * smoothstep((x - xd) / 0.004 + 0.5) * front
            y = yb - d * front - step
            pts.append(Vector((x, y, z)))
            uv.append((0.5 + 0.12 * i / segs, 0.6 + H * v))
        g.add_row(pts, uv)
    g.fill(G.uv, G.tag, tag, flip=True)
    z_bot = zt + T["knot_top_above_band_m"] - H
    return g, z_bot


# --- jacket collar ---------------------------------------------------------------------------

def build_jacket_collar(jk, nf, J, tag):
    """Stand + fold + fall on the jacket's neckline (block top row, shared
    vertices), front ends blended into the collar end over the lapel's top
    edge. See the module docstring."""
    G = jk.G
    N = jk.N
    top = jk.block.rows[-1]
    G.bm.normal_update()
    under = sb.bvh_of_bm(G.bm)   # block + lapels
    end_frac = J["end_frac"]
    NF = J["fall_rows"]

    def lapel_top(left):
        row = getattr(jk, "lapel_top_l" if left else "lapel_top_r", None)
        if row is None:
            row = (jk.lapel_l if left else jk.lapel_r).rows[-1]
        return [v.co.copy() for v in row]

    def outward(p):
        hit = under.find_nearest(p, 0.05)
        n = hit[1] if hit[0] is not None else nf.radial(p).normalized()
        return n if n.dot(nf.radial(p)) >= 0 else -n

    def roll_line(left, z0, z1):
        """The block's front edge (the roll line) between the lapel's top
        (z0) and the gorge point (z1), top-down, a little proud of the block."""
        col = 0 if left else N
        pts = [row[col].co.copy() for row in jk.block.rows[:-1] if z0 + 0.004 < row[col].co.z < z1 - 0.004]
        pts.sort(key=lambda p: -p.z)
        return [p + outward(p) * (J["end_lift_m"] + 0.001) for p in pts]

    # the collar end paths (front columns): gorge point -> along the lapel's
    # top edge to the notch -> up to the collar point
    ends, notch, cpoint, roll = {}, {}, {}, {}
    ang = math.radians(J["notch_deg"])
    for left in (True, False):
        lt = lapel_top(left)
        R = (top[0] if left else top[N]).co.copy()
        S = sb.point_at_arc(lt, J["gorge_seam_m"])
        hit = under.find_nearest(S, 0.05)
        n = hit[1] if hit[0] is not None else nf.radial(S).normalized()
        if n.dot(nf.radial(S)) < 0:
            n = -n
        edge = lt[-2] - lt[0]
        edge = (edge - n * edge.dot(n)).normalized()
        upl = (UP - n * UP.dot(n)).normalized()
        d = (edge * math.cos(ang) + upl * math.sin(ang)).normalized()
        Cp = S + d * J["point_m"] + n * 0.0025
        # the seam part lies on the lapel's top edge, a little proud of it
        # (skipping the lapel's fold bulge at the roll line, which the end would cross)
        seam = [p + n * J["end_lift_m"] for k, p in enumerate(lt)
                if k >= 3 and (p - lt[0]).length <= (S - lt[0]).length]
        roll[left] = []
        if R.z - lt[0].z > 0.01:
            # a dropped gorge: the collar's fold continues the lapel's roll
            # line down from the gorge point to the lapel's top (the fold curve
            # of the end patch, below); the end path starts on the roll's crest
            crest = lt[2] + outward(lt[2]) * J["end_lift_m"]
            roll[left] = [crest] + list(reversed(roll_line(left, lt[0].z, R.z)))
            seam = [crest] + seam
        else:
            seam = [R] + seam
        path = seam + [S + n * J["end_lift_m"], Cp]
        notch[left], cpoint[left] = S, Cp
        ends[left] = path

    def resample(path, n):
        L = sb.arc_length(path)
        return [sb.point_at_arc(path, L * j / n) for j in range(n + 1)]

    def resample_corner(path, k_corner, n):
        """n + 1 points along path with the vertex path[k_corner] on a row."""
        a, b = path[:k_corner + 1], path[k_corner:]
        La, Lb = sb.arc_length(a), sb.arc_length(b)
        ja = min(max(1, round(n * La / max(La + Lb, 1e-9))), n - 1)
        return resample(a, ja)[:-1] + resample(b, n - ja)

    th = J["thickness_m"]
    cols = []
    fold_z = []
    for i in range(N + 1):
        c = i / N
        p0 = top[i].co.copy()
        a, z_s, r_s = nf.polar(p0)
        cf = min(c, 1 - c)
        w = smoothstep(1 - cf / end_frac) if cf < end_frac else 0.0
        reveal = lerp(J["reveal_side_m"], J["reveal_back_m"], nf.back(a))
        z_f = max(nf.zt(a) - reveal, z_s + J["stand_min_m"])
        # in front of the neck point the fold line runs down toward the gorge,
        # continuing the lapel's roll line (the stand lowers), instead of
        # standing at full height to the end
        df = J.get("drop_frac", 0.0)
        if df > end_frac and cf < df:
            wd = smoothstep((df - cf) / (df - end_frac))
            z_f = lerp(z_f, max(z_s + J["stand_min_m"], z_f - J.get("drop_m", 0.0)), wd)
        z_f = lerp(z_f, z_s + 0.0015, w)
        # the fold hugs the shirt collar at its own height; the stand (a straight
        # line from the seam) stays outside the shirt and the body all the way
        r_f = nf.shirt_outer(a, z_f - 0.015, z_f) + J["shirt_clear_m"]
        r_f = max(r_f, nf.r_body_max(a, z_f - 0.01, z_f) + J["body_clear_m"])
        for t in (0.2, 0.4, 0.6, 0.8):
            z_t = lerp(z_s, z_f, t)
            need = max(nf.shirt_outer(a, z_t - 0.002, z_t + 0.002) + J["shirt_clear_m"],
                       nf.r_body(a, z_t) + J["body_clear_m"])
            r_f = max(r_f, (need - r_s * (1 - t)) / t)
        r_f = lerp(r_f, r_s, w)
        if DEBUG and i % 6 == 0:
            print(f"[neck] i={i:2d} a={math.degrees(a):6.1f} seam z={z_s:.4f} r={r_s:.4f}  fold z={z_f:.4f} "
                  f"r={r_f:.4f}  shirt zb={nf.zb(a):.4f} zt={nf.zt(a):.4f} rb={nf.rb(a):.4f} rt={nf.rt(a):.4f} "
                  f"body@seam={nf.r_body(a, z_s):.4f} w={w:.2f}")
        p1 = nf.point(a, z_f, r_f)
        p2 = nf.point(a, z_f + 0.6 * th * (1 - w), r_f + 0.5 * th * (1 - w))
        p3 = nf.point(a, z_f - 0.0005 * (1 - w), r_f + th * (1 - w))
        fold_z.append(z_f)
        # natural fall: a radial profile at angle a, draped over the stand and
        # the block, monotone outward, cut at the fall width
        width = max(lerp(J["fall_side_m"], J["fall_back_m"], nf.back(a)), (p1 - p0).length + J["seam_cover_m"])
        prof = [(r_f + th, z_f - 0.0005)]
        L = 0.0
        z = z_f - 0.0005
        r_prev = r_f + th
        while L < width and z > z_f - 0.12:
            z -= 0.0008
            u = r_prev
            if z >= z_s:
                t = (z - z_s) / max(z_f - z_s, 1e-6)
                u = max(u, lerp(r_s, r_f, t) + th)
            hit = under.ray_cast(nf.point(a, z, max(r_s - 0.02, 0.01)), Vector((math.cos(a), math.sin(a), 0)), 0.25)
            if hit[0] is not None:
                u = max(u, nf.polar(hit[0])[2] + J["rest_m"])
            L += math.hypot(u - prof[-1][0], z - prof[-1][1])
            prof.append((u, z))
            r_prev = u
        fall = resample([nf.point(a, zz, rr) for rr, zz in prof], NF)
        fall[0] = p3
        cols.append([p0, p0.lerp(p1, 0.5), p1, p2] + fall)

    i_e = max(2, math.ceil(end_frac * N))
    # fair the stand and the fold along the collar (outside the end columns):
    # each column's fold is the highest of its clearance needs, so single
    # columns spiked out by up to 3 mm and the fold read as a sawtooth where
    # the collar turns round the side of the neck. Height and radius 1-2-1
    # at each column's own angle, the radius never below the column's own
    # (the clearance), the stand's middle row back on its line
    for _ in range(J.get("fold_fair_passes", 0)):
        for j in (2, 3, 4):
            pol = [nf.polar(cols[i][j]) for i in range(N + 1)]
            for i in range(i_e - 1, N - i_e + 2):
                z = (pol[i - 1][1] + 2 * pol[i][1] + pol[i + 1][1]) * 0.25
                r = max(pol[i][2], (pol[i - 1][2] + 2 * pol[i][2] + pol[i + 1][2]) * 0.25)
                cols[i][j] = nf.point(pol[i][0], z, r)
        for i in range(i_e - 1, N - i_e + 2):
            cols[i][1] = cols[i][0].lerp(cols[i][2], 0.5)

    # smooth the natural fall across columns (outside the end regions)
    for _ in range(3):
        for j in range(5, 4 + NF + 1):
            co = [cols[i][j].copy() for i in range(N + 1)]
            for i in range(i_e, N - i_e + 1):
                cols[i][j] = (co[i - 1] + 2 * co[i] + co[i + 1]) / 4

    # the front ends: a Coons patch between the end path (gorge point -> notch
    # -> collar point), the fold curve, the natural column at i_b and an outer
    # edge curve from the collar point to that column's edge. i_b reaches past
    # the side of the neck (patch_frac), so the outer edge is one curve from
    # the collar point over the shoulder: a patch ending at i_e left the edge
    # rising straight up from the point and turning out at a corner (a tab)
    i_b = max(i_e, math.ceil(J.get("patch_frac", end_frac) * N))
    for left in (True, False):
        idx = list(range(0, i_b + 1)) if left else list(range(N, N - i_b - 1, -1))
        path = ends[left]
        Lc = resample_corner(path, len(path) - 2, NF)        # rows 4 .. 4 + NF
        Rc = [cols[idx[-1]][4 + j] for j in range(NF + 1)]
        T = [cols[i][4] for i in idx]
        if roll[left]:
            # the fold: up the roll line from the lapel's crest to the gorge
            # point, then the neckline back to column i_b, by arc length; the
            # stand rows of the end columns run from their seam point to it
            T = resample(roll[left] + T, i_b)
            for k, i in enumerate(idx[:-1]):
                p0 = cols[i][0]
                cols[i][1] = p0.lerp(T[k], 0.4)
                cols[i][2] = p0.lerp(T[k], 0.8)
                cols[i][3] = p0.lerp(T[k], 0.95)
        T[0] = Lc[0]
        Cp, E = Lc[-1], Rc[-1]
        Ep = cols[idx[-2]][4 + NF]
        m1 = (E - Ep) * i_b * 0.6
        m0 = (E - Cp)
        B = []
        for k in range(i_b + 1):
            t = k / i_b
            h00, h10 = 2 * t ** 3 - 3 * t ** 2 + 1, t ** 3 - 2 * t ** 2 + t
            h01, h11 = -2 * t ** 3 + 3 * t ** 2, t ** 3 - t ** 2
            B.append(Cp * h00 + m0 * h10 + E * h01 + m1 * h11)
        P00, P10, P01, P11 = Lc[0], Rc[0], Lc[-1], Rc[-1]
        if DEBUG and left:
            f = lambda p: f"({p.x:.3f},{p.y:.3f},{p.z:.3f})"
            print("[neck] end L: " + " ".join(f(p) for p in Lc))
            print(f"[neck] end R(i_b={i_b}): " + " ".join(f(p) for p in Rc))
            print("[neck] end T: " + " ".join(f(p) for p in T))
            print("[neck] end B: " + " ".join(f(p) for p in B))
        for k, i in enumerate(idx[:-1]):
            u = k / i_b
            for j in range(NF + 1):
                v = j / NF
                p = (Lc[j] * (1 - u) + Rc[j] * u + T[k] * (1 - v) + B[k] * v
                     - (P00 * ((1 - u) * (1 - v)) + P10 * (u * (1 - v)) + P01 * ((1 - u) * v) + P11 * (u * v)))
                cols[i][4 + j] = p
        notch[left] = path[-2]
    _dump("coons", cols, i_b)

    # rest the fall on what is beneath it (block, lapels): outside by rest_m
    rested = 0
    for i in range(N + 1):
        # hold_end: the end path (notch -> collar point) stays as built, a
        # little proud of the lapel; snapped to the nearest surface, the
        # collar point jumped 7 mm up off the lapel's rounded top edge and
        # kinked the point
        if J.get("hold_end") and i in (0, N):
            continue
        for j in range(5, 4 + NF + 1):
            p = cols[i][j]
            hit = under.find_nearest(p, 0.03)
            if hit[0] is None:
                continue
            # the outer side of the block is the one away from the body
            bh = nf.tree.find_nearest(hit[0], 0.2)
            out = (hit[0] - bh[0]) if bh[0] is not None else nf.radial(hit[0])
            n = hit[1] if hit[1].dot(out) >= 0 else -hit[1]
            h = (p - hit[0]).dot(n)
            # the front ends (a Coons patch) float where the chest falls away:
            # lay them on what is beneath, fading out into the natural columns
            k = min(i, N - i)
            snap = (1 - k / i_e) * min(1.0, (j - 4) / 2) if k < i_e else 0.0
            if h < J["rest_m"] and (k >= i_e or J.get("end_rest", True)):
                cols[i][j] = p + n * (J["rest_m"] - h)
                rested += 1
            elif snap > 0 and h < J.get("snap_max_m", 0.03):
                cols[i][j] = p - n * ((h - J["rest_m"]) * snap)
                rested += 1
    def outside(p, trees=None):
        """p, moved out along the ray from the neck axis to rest_m outside
        every layer beneath (block, lapels; `trees`); (point, moved)."""
        a, z, r = nf.polar(p)
        d = Vector((math.cos(a), math.sin(a), 0.0))
        o = nf.point(a, z, 0.01)
        r_hit = None
        for tree in trees or (under,):
            travelled = 0.0
            while travelled < r + 0.012:
                h = tree.ray_cast(o + d * travelled, d, r + 0.012 - travelled)
                if h[0] is None:
                    break
                travelled = (h[0] - o).length + 1e-4
                r_hit = max(r_hit or 0.0, nf.polar(h[0])[2])
        if r_hit is not None and r < r_hit + J["rest_m"]:
            return nf.point(a, z, r_hit + J["rest_m"]), True
        return p, False

    pushed = 0
    # and outside every layer beneath along the ray from the neck axis (the
    # nearest-point rest can pick the wrong layer where block and lapel cross)
    for i in range(N + 1):
        for j in range(5, 4 + NF + 1):
            cols[i][j], moved = outside(cols[i][j])
            pushed += moved
    # the front ends' fall: the rest and the push move single points (teeth
    # along the notch and the outer edge); relax them over their neighbours,
    # then put them back outside the layers beneath
    for _ in range(J.get("end_relax", 0)):
        ends_i = [i for i in range(1, N) if min(i, N - i) <= i_e + 1]
        new = {}
        for i in ends_i:
            for j in range(5, 4 + NF + 1):
                nb = [cols[i - 1][j], cols[i + 1][j]]
                if j < 4 + NF:
                    nb += [cols[i][j - 1], cols[i][j + 1]]
                new[(i, j)] = cols[i][j] * 0.5 + sum(nb, Vector()) * (0.5 / len(nb))
        for (i, j), p in new.items():
            cols[i][j] = outside(p)[0]
    # fair the outer edge: one smooth curve from the collar point round the
    # back. The per-column fall profiles and the end patch left it rising
    # straight up from the collar point and turning out at a corner at the
    # side of the neck (a tab), with single-column teeth. The edge row is
    # smoothed (1-2-1) as angle, height and radius in the neck frame (no
    # shrinking round the neck), the collar points held; the fall rows
    # follow it in proportion to their distance from the fold, then go back
    # outside the layers beneath
    passes = J.get("edge_fair_passes", 0)
    if passes:
        je = 4 + NF
        pol = [list(nf.polar(cols[i][je])) for i in range(N + 1)]
        for i in range(1, N + 1):   # unwrap the angle along the edge
            while pol[i][0] - pol[i - 1][0] > math.pi:
                pol[i][0] -= TAU
            while pol[i][0] - pol[i - 1][0] < -math.pi:
                pol[i][0] += TAU
        for _ in range(passes):
            pol = [pol[0]] + [[(pol[i - 1][k] + 2 * pol[i][k] + pol[i + 1][k]) * 0.25 for k in range(3)]
                              for i in range(1, N)] + [pol[N]]
        # the stand (seam to fold) is beneath the fall too: the fall rows
        # near the fold must not cross it where the edge moves
        sv = [cols[i][j] for j in range(5) for i in range(N + 1)]
        sp = [[j * (N + 1) + i, j * (N + 1) + i + 1, (j + 1) * (N + 1) + i + 1, (j + 1) * (N + 1) + i]
              for j in range(4) for i in range(N)]
        stand = BVHTree.FromPolygons(sv, sp)
        def rest_on(q):
            """rest_m off the nearest surface beneath, along its normal (the
            radial push measures across a sloping shoulder, not off it)"""
            hit = under.find_nearest(q, 0.03)
            if hit[0] is None:
                return q
            bh = nf.tree.find_nearest(hit[0], 0.2)
            out = (hit[0] - bh[0]) if bh[0] is not None else nf.radial(hit[0])
            n = hit[1] if hit[1].dot(out) >= 0 else -hit[1]
            h = (q - hit[0]).dot(n)
            return q + n * (J["rest_m"] - h) if h < J["rest_m"] else q

        for i in range(1, N):
            d = nf.point(*pol[i]) - cols[i][je]
            for j in range(5, je + 1):
                cols[i][j] = rest_on(outside(cols[i][j] + d * ((j - 4) / NF), (under, stand))[0])
        # the pushes above lift single points back over the lapels and the
        # stand (bumps up to 1.2 mm across the edge at the sides of the
        # neck): settle the edge over them, height 1-2-1, radius outward
        # only, resting each pass, so it lies over the bumps as one curve
        for _ in range(J.get("edge_settle_passes", 0)):
            pol = [nf.polar(cols[i][je]) for i in range(N + 1)]
            for i in range(1, N):
                z = (pol[i - 1][1] + 2 * pol[i][1] + pol[i + 1][1]) * 0.25
                r = max(pol[i][2], (pol[i - 1][2] + 2 * pol[i][2] + pol[i + 1][2]) * 0.25)
                d = nf.point(pol[i][0], z, r) - cols[i][je]
                for j in range(5, je + 1):
                    cols[i][j] = rest_on(cols[i][j] + d * ((j - 4) / NF))
    _dump("final", cols, i_b)
    rows = [[cols[i][j] for i in range(N + 1)] for j in range(5 + NF)]
    if DEBUG:
        for i in (0, 2, 4, 6, 9, 12):
            print(f"[neck] col {i:2d}: " + " ".join(f"({p.x:.3f},{p.y:.3f},{p.z:.3f})" for p in cols[i]))

    je = 4 + NF
    surf = [list(r) for r in rows]   # the collar's surface rows (seam .. outer edge)

    def grid_n(i, j):
        """The surface normal of the collar grid at (column i, row j), from
        its own tangents: one orientation over the whole grid (a normal
        taken toward the nearest body point flipped at single columns, and
        the edge rolled up over the fall there instead of under it)"""
        di = surf[j][min(i + 1, N)] - surf[j][max(i - 1, 0)]
        dj = surf[min(j + 1, je)][i] - surf[max(j - 1, 0)][i]
        n = di.cross(dj)
        return n.normalized() if n.length > 1e-12 else nf.radial(surf[j][i]).normalized()

    votes = 0
    for i in range(N + 1):
        p = surf[je][i]
        bh = nf.tree.find_nearest(p, 0.3)
        out = (p - bh[0]) if bh[0] is not None else nf.radial(p)
        votes += 1 if grid_n(i, je).dot(out) >= 0 else -1
    gsign = 1.0 if votes >= 0 else -1.0

    re = J.get("edge_r_m", 0.0)
    corner = {}
    if re:
        # the outer edge is a rounded, pressed edge 2 * edge_r_m thick: the
        # fall rolls over at the edge (a half round) into the under collar,
        # which runs back under the fall (the single sheet's raw edge and a
        # 1 mm lip read as a ragged paper edge in every portrait)
        b90, b180, lip = [], [], []
        for i in range(N + 1):
            p = rows[-1][i]
            n = grid_n(i, je) * gsign
            # across the edge, outward, in the surface: square to the edge's
            # own tangent (the last fall row can fold back past the edge near
            # the collar point, which rolled the edge up into a flap)
            di = (surf[je][min(i + 1, N)] - surf[je][max(i - 1, 0)]).normalized()
            t = (n.cross(di) * gsign).normalized()
            if i in (0, N):
                # the collar point: the edge rounds the corner on the
                # diagonal, shared with the point's own edge (below)
                dj = (surf[je][i] - surf[je - 1][i]).normalized()
                sd = dj.cross(n) * gsign * (-1.0 if i == 0 else 1.0)
                t = (t + sd.normalized()).normalized()
                corner[i == 0] = (n, t)
            c = p - n * re
            b90.append(c + t * re)
            b180.append(c - n * re)
            lip.append(c - n * re - t * J.get("under_m", 0.004))
        rows += [b90, b180, lip]
    else:
        # the edge turned under: a lip row
        lip = []
        for i in range(N + 1):
            p, q = rows[-1][i], rows[-2][i]
            a = nf.polar(p)[0]
            lip.append(p + (q - p).normalized() * 0.003 - Vector((math.cos(a), math.sin(a), 0)) * 0.001)
        rows.append(lip)

    g = G.grid("collar")
    uvs = []
    acc = [0.0] * (N + 1)
    for j, row in enumerate(rows):
        if j:
            for i in range(N + 1):
                acc[i] += (row[i] - rows[j - 1][i]).length
        u0 = 0.0
        uv = []
        for i in range(N + 1):
            if i:
                u0 += (rows[2][i] - rows[2][i - 1]).length
            uv.append((u0, acc[i]))
        uvs.append(uv)
    verts = [[top[i] for i in range(N + 1)]] + [[G.bm.verts.new(p) for p in row] for row in rows[1:]]
    for j, row in enumerate(verts):
        g.add_shared_row(row, uvs[j])
    g.fill(G.uv, G.tag, tag, flip=True)
    for i in range(N + 1):
        for j in range(1, len(verts)):
            G.copy_weights(top[i], verts[j][i])
    # the collar point's edge (notch -> collar point) rounded the same way
    end_strips = 0
    if re:
        je = 4 + NF
        for left in (True, False):
            c0 = 0 if left else N
            j_s = min(range(4, je + 1), key=lambda j: (verts[j][c0].co - notch[left]).length)
            js = list(range(j_s, je + 1))
            if len(js) < 2:
                continue
            band = [[], [], []]
            for j in js:
                v = verts[j][c0].co
                n = grid_n(c0, j) * gsign
                dj = (surf[min(j + 1, je)][c0] - surf[max(j - 1, 0)][c0]).normalized()
                s = (dj.cross(n) * gsign * (-1.0 if left else 1.0)).normalized()
                if j == je:   # the corner, as the outer edge rounds it
                    n, s = corner[left]
                c = v - n * re
                band[0].append(c + s * re)
                band[1].append(c - n * re)
                band[2].append(c - n * re - s * J.get("under_m", 0.004))
            ge = G.grid("collar_end_" + ("l" if left else "r"))
            u_of = [uvs[j][c0] for j in js]
            sgn = -1.0 if left else 1.0
            ge.add_shared_row([verts[j][c0] for j in js], u_of)
            for k, row in enumerate(band):
                ge.add_row(row, [(u + sgn * 0.002 * (k + 1), v) for u, v in u_of])
            # faces out: the first band's normal along (side + normal)
            a0, a1, b0 = ge.rows[0][0].co, ge.rows[0][1].co, ge.rows[1][0].co
            n0 = grid_n(c0, js[0]) * gsign
            flip = (a1 - a0).cross(b0 - a0).dot((b0 - a0) + n0 * (2 * re)) < 0
            ge.fill(G.uv, G.tag, tag, flip=flip)
            for row in ge.rows[1:]:
                for k, vv in enumerate(row):
                    G.copy_weights(verts[js[k]][c0], vv)
            end_strips += len(ge.faces)
    # the block / lapel beneath the fall: where it pokes through the fall
    # between the fall's vertices, press it under (it is hidden there)
    own = {v for row in verts for v in row}
    cverts = [v.co.copy() for row in verts[4:] for v in row]
    W = len(verts[0])
    cpolys = []
    for j in range(len(verts) - 5):
        for i in range(W - 1):
            b0 = j * W
            cpolys.append([b0 + i, b0 + i + 1, b0 + W + i + 1, b0 + W + i])
    ctree = BVHTree.FromPolygons(cverts, cpolys)
    lo = min(p.z for p in cverts) - 0.01
    pressed = 0
    gap = J.get("under_gap_m", 0.002)
    for v in G.bm.verts:
        if v in own or v.co.z < lo:
            continue
        hit = ctree.find_nearest(v.co, 0.012)
        if hit[0] is None:
            continue
        bh = nf.tree.find_nearest(hit[0], 0.2)
        out = (hit[0] - bh[0]) if bh[0] is not None else nf.radial(hit[0])
        n = hit[1] if hit[1].dot(out) >= 0 else -hit[1]
        h = (v.co - hit[0]).dot(n)
        lateral = ((v.co - hit[0]) - n * h).length
        if -gap < h < 0.008 and lateral < 0.001:
            v.co = v.co - n * (h + gap)
            pressed += 1
    G.mark_row(tag, g, 4 + NF, "edge", inside_sign=-1.0)
    return g, {"collar_rested_verts": rested, "collar_pushed_verts": pushed, "block_pressed_verts": pressed,
               "collar_end_strip_faces": end_strips,
               "fold_z_back": round(max(fold_z), 4),
               "notch_l": [round(x, 4) for x in notch[True]],
               "collar_point_l": [round(x, 4) for x in cpoint[True]]}
