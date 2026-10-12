"""Waistcoat, shirt and tie, built on the body slices inside the jacket
(suit_build primitives; bench/m1/suit.md).

    shirt      front panel inside the waistcoat's V (+ margin), placket strip,
               collar band around the neck with a fold and spread leaves,
               cuff rings inside the jacket sleeves, two placket buttons
    tie        four-in-hand knot (lofted ellipses, slightly asymmetric) and a
               blade with a dimple, over the placket, cut under the vest V
    waistcoat  front panel inside the jacket's V (+ margin): 5-button V, points,
               edge lip; lower back panel for the vents
    buttons    discs: jacket front, cuffs, waistcoat

Only regions that can show are built (look-spec §4.3).
"""

import math

from mathutils import Vector

from . import suit_build as sb
from .suit_build import TAU, lerp, smoothstep

NECK = {"neck_01", "head"}
UPPER = {"spine_03", "clavicle_l", "clavicle_r", "neck_01"}


class Inner:
    def __init__(self, b, body, o, arm, jk, jacket, like, waistband, mats, part):
        self.b, self.body, self.o, self.arm = b, body, o, arm
        self.jk, self.jacket, self.like, self.mats, self.part = jk, jacket, like, mats, part
        self.waistband = waistband
        self.torso = body.verts(sb.TORSO)
        self.m = {}
        self.marks = {}
        W = o["waistcoat"]
        self.z_v = jk.z_b + W["top_button_above_jacket_button_m"]   # vest V bottom
        self.z_vn = jk.supra + 0.02                                   # vest neck point
        self.x_vn = W["neck_point_x_m"]
        self.z_side = waistband - W["cover_waistband_m"]
        self.z_point = self.z_side - W["point_drop_m"]
        self.z_notch = self.z_side - 0.5 * W["point_drop_m"]
        self.shirt_base_front = jk.supra + o["shirt"]["collar"]["base_above_supra_m"]

    # --- shared slice helpers ---------------------------------------------------------------

    def slice(self, z, verts=None, band=0.012):
        cy, radii = sb.slice_profile(verts or self.torso, z, band, min_pts=50)
        return cy, sb.smooth_ring(sb.chord_fill(radii, limit=0.012), 2)

    def w_vest(self, z):
        if z <= self.z_v:
            return 0.0
        return self.x_vn * (z - self.z_v) / (self.z_vn - self.z_v)

    def vest_hem(self, x):
        ax = abs(x)
        if ax < 0.045:
            return self.z_notch + (self.z_point - self.z_notch) * ax / 0.045
        return self.z_point + (self.z_side - self.z_point) * min(1.0, (ax - 0.045) / 0.08)

    def front_panel(self, G, name, z_rows, half_at, offset, cols, lip=0.0, tag=1,
                    hem=None, uv0=0.0, clear=None, marks=False):
        """Two mirrored front panels (left, right) from the centre/V edge out to
        half_at(z) in x, lofted over the torso slices at `offset`. The V edge
        is where half_at's inner bound starts: inner(z). Returns the grids."""
        grids = []
        for left in (True, False):
            s = 1 if left else -1
            g = G.grid(name + ("_l" if left else "_r"))
            for k, z in enumerate(z_rows):
                cy, radii = self.slice(z)
                x_in, x_out = half_at(z)
                a_in = sb.angle_at_x(cy, radii, s * x_in, front=True, ease=lambda a: offset)
                a_out = sb.angle_at_x(cy, radii, s * x_out, front=True, ease=lambda a: offset)
                pts, uvs = [], []
                for i in range(cols + 1):
                    a = lerp(a_in, a_out, i / cols)
                    r = sb.sample_ring(radii, a) + offset
                    p = Vector((r * math.cos(a), cy + r * math.sin(a), z))
                    if hem is not None:
                        p.z = max(p.z, hem(p.x)) if k == 0 else p.z
                    if clear is not None:
                        n = Vector((math.cos(a), math.sin(a), 0.0))
                        p = sb.offset_from(clear[0], p, n, clear[1])
                    pts.append(p)
                    uvs.append((uv0 + (0.4 * i / cols if left else 0.4 * (1 - i / cols)) , z - z_rows[0]))
                if lip:
                    # an inner lip column at the V/centre edge (cloth thickness)
                    p0, p1 = pts[0], pts[1]
                    n = Vector((math.cos(a_in), math.sin(a_in), 0.0))
                    pts.insert(0, p0 - n * lip + (p0 - p1).normalized() * 0.0005)
                    uvs.insert(0, (uvs[0][0] - 0.002 * s, uvs[0][1]))
                g.add_row(pts, uvs)
            g.fill(G.uv, G.tag, tag, flip=not left)
            grids.append(g)
            if marks:
                c0 = 1 if lip else 0
                G.mark_column(tag, g, c0, "edge", inside_sign=1.0 if left else -1.0)
                G.mark_row(tag, g, 0, "edge", cols=range(c0, len(g.rows[0])), inside_sign=1.0)
        return grids

    # --- shirt -------------------------------------------------------------------------------

    def build_shirt(self):
        o, S = self.o, self.o["shirt"]
        G = sb.Garment(self.part.format("shirt"), self.arm, self.body)
        off = S["offset_m"]
        # front: inside the vest V plus margin, from under the V bottom to the collar base
        z0 = self.z_v - 0.04
        z1 = self.shirt_base_front + 0.012
        rows = [z0 + (z1 - z0) * k / 14 for k in range(15)]
        margin = S["front_margin_m"]

        def half(z):
            return (0.0, min(self.w_vest(z) + margin, 0.11))
        fronts = self.front_panel(G, "front", rows, half, off, 8, tag=1)
        for g in fronts:
            for row in g.rows:
                G.weight(row, sb.TORSO | {"neck_01"})
        # placket: a strip proud of the front, centre
        pw = S["placket_w_m"]
        g = G.grid("placket")
        for z in rows:
            cy, radii = self.slice(z)
            pts, uvs = [], []
            for i in range(5):
                x = -pw / 2 + pw * i / 4
                a = sb.angle_at_x(cy, radii, x, front=True, ease=lambda a: off)
                r = sb.sample_ring(radii, a) + off + (0.0012 if 0 < i < 4 else 0.0003)
                pts.append(Vector((r * math.cos(a), cy + r * math.sin(a), z)))
                uvs.append((0.45 + pw * i / 4, z - rows[0]))
            g.add_row(pts, uvs)
        g.fill(G.uv, G.tag, 2)
        for row in g.rows:
            G.weight(row, sb.TORSO | {"neck_01"})
        G.mark_column(2, g, 1, "topstitch", pitch_m=0.002, height=0.00015)
        G.mark_column(2, g, 3, "topstitch", pitch_m=0.002, height=0.00015)
        self.shirt_front_top = rows[-1]
        self.build_shirt_collar(G)
        self.build_cuffs(G)
        # placket buttons (tiny white discs)
        tree = sb.bvh_of_bm(G.bm)
        for z in (self.z_v + 0.01, self.z_v + 0.10):
            hit = tree.ray_cast(Vector((0, -1, z)), Vector((0, 1, 0)), 2.0)
            if hit[0] is not None:
                n = hit[1] if hit[1].y < 0 else -hit[1]
                sb.disc(G.bm, G.dl, hit[0], n, 0.0045, 0.0015,
                        {G.gidx[k]: w for k, w in self.body.weights(hit[0], sb.TORSO).items()},
                        8, G.uv, (0.9, 0.05))
        self.shirt = G.finish(self.b, self.like, self.mats["shirt"])
        self.marks[self.shirt.name] = G.marks
        return self.shirt

    def build_shirt_collar(self, G):
        """Band (stand) around the neck, fold, leaves spreading at the front."""
        C = self.o["shirt"]["collar"]
        body = self.body
        neck = body.verts(NECK)
        n_cols = C["columns"]
        g = G.grid("collar")
        z_fb, z_bb = self.shirt_base_front, self.shirt_base_front + C["back_rise_m"]
        cy0, base_r = self.slice(z_fb + 0.02, neck, 0.012)
        cy1, mid_r = self.slice(z_fb + 0.045, neck, 0.012)
        rows = [[] for _ in range(6)]
        uvs = [[] for _ in range(6)]
        under = sb.bvh_of_bm(G.bm)
        for i in range(n_cols + 1):
            c = i / n_cols
            # psi from the front centre (wearer's left side first) round the back
            a = -math.pi / 2 + TAU * c
            bk = 0.5 - 0.5 * math.cos(TAU * c)  # 0 front, 1 back
            z_base = lerp(z_fb, z_bb, bk ** 0.8)
            stand = lerp(C["stand_front_m"], C["stand_m"], bk ** 0.5)
            r0 = sb.sample_ring(base_r, a) + C["gap_m"]
            r1 = sb.sample_ring(mid_r, a) + C["gap_m"]
            out = Vector((math.cos(a), math.sin(a), 0.0))
            up = Vector((0, 0, 1))
            p0 = Vector((r0 * math.cos(a), cy0 + r0 * math.sin(a), z_base))
            p1 = Vector((r1 * math.cos(a), cy1 + r1 * math.sin(a), z_base + stand))
            p2 = p1 + up * 0.003 + out * 0.003
            # leaves: none across the front gap (the tie sits there), full length
            # at the points, then short where the jacket collar covers them
            cf = min(c, 1 - c)  # 0 at the front centre, 0.5 at the back
            gap, pt, hide = C["gap_frac"], C["point_frac"], C["hidden_from_frac"]
            if cf < gap:
                leaf = 0.0
            elif cf < pt:
                leaf = C["point_m"] * smoothstep((cf - gap) / (pt - gap))
            else:
                leaf = lerp(C["point_m"], C["leaf_m"], smoothstep((cf - pt) / (hide - pt)))
            frontness = 1 - smoothstep((cf - pt) / (hide - pt))
            lat = Vector((1.0 if math.cos(a) > 0 else -1.0, 0, 0))
            spread = math.sin(math.radians(C["spread_deg"])) * frontness
            # the points fold out over the chest; past them the leaves hang
            # nearly straight down inside the jacket collar
            d = (-up * (1 - spread * 0.6) + out * lerp(0.08, 0.3, frontness) + lat * spread).normalized()
            p3 = p2 + d * (leaf * 0.5) + out * 0.003
            p4 = p2 + d * leaf + out * 0.003
            for q in (p3, p4):
                hit = under.find_nearest(q, 0.08)
                if hit[0] is not None:
                    h = (q - hit[0]).dot(hit[1])
                    if h < 0.0025:
                        q += hit[1] * (0.0025 - h)
            p5 = p4 + (p3 - p4).normalized() * 0.003 - out * 0.002
            u = 0.5 * c
            for j, (p, v) in enumerate(((p0, 0.0), (p1, stand), (p2, stand + 0.008),
                                        (p3, stand + 0.008 + leaf * 0.5), (p4, stand + 0.008 + leaf),
                                        (p5, stand + 0.011 + leaf))):
                rows[j].append(g.bm.verts.new(p))
                uvs[j].append((u, v))
        for j in range(6):
            g.add_shared_row(rows[j], uvs[j])
        g.fill(G.uv, G.tag, 3, flip=True)
        for j in range(6):
            G.weight(rows[j], NECK | {"spine_03", "clavicle_l", "clavicle_r"})
        G.mark_row(3, g, 4, "edge", inside_sign=-1.0, stitch_in_m=0.004)
        G.mark_row(3, g, 1, "topstitch", pitch_m=0.002, height=0.00015)
        # the leaves stay under the jacket's lapels and collar where they overlap
        G.bm.normal_update()
        jt = sb.bvh_of([self.jacket])
        leaves = [v for j in (2, 3, 4, 5) for v in rows[j]]
        self.m["shirt_collar_tucked_verts"] = sb.tuck_under(leaves, jt, gap=0.0025)
        self.collar_front_z = z_fb
        self.collar_rows = rows
        return g

    def build_cuffs(self, G):
        """A cuff ring inside each jacket sleeve end, showing cuff_reveal_m."""
        S = self.o["shirt"]
        jk = self.jk
        for side in ("l", "r"):
            ring = getattr(jk, f"sleeve_end_{side}")  # last tube ring (before the lip)
            axis = getattr(jk, f"sleeve_axis_{side}")
            _, L = getattr(jk, f"sleeve_L_{side}")
            C, T, up, sd = axis(L)
            c = sum(ring, Vector()) / len(ring)
            n = 16
            pts16 = sb.ring_points_resample(ring, n)
            g = G.grid(f"cuff_{side}")
            for k, (scale, along) in enumerate(((0.80, -S["cuff_inside_m"]), (0.88, 0.0),
                                                (0.88, S["cuff_reveal_m"]),
                                                (0.80, S["cuff_reveal_m"] - 0.002))):
                pts = [c + (p - c) * scale + T * along for p in pts16]
                g.add_row(pts + [pts[0].copy()], [(0.3 * i / n, 0.02 * k) for i in range(n + 1)])
            g.fill(G.uv, G.tag, 4, flip=(side == "r"))
            for row in g.rows:
                G.weight(row, sb.ARM[side])
            G.mark_row(4, g, 2, "edge", inside_sign=-1.0, stitch_in_m=0.004)

    # --- tie ----------------------------------------------------------------------------------

    def build_tie(self):
        T = self.o["tie"]
        G = sb.Garment(self.part.format("tie"), self.arm, self.body)
        body_tree = self.body.bvh()
        shirt_off = self.o["shirt"]["offset_m"]
        # knot frame: at the collar front, in front of the collar band
        z_top = self.collar_front_z + T["knot_top_above_base_m"]
        hit = body_tree.ray_cast(Vector((0, -1, z_top - 0.01)), Vector((0, 1, 0)), 2.0)
        y_front = hit[0].y if hit[0] is not None else -0.1
        y_knot = y_front - shirt_off - 0.004
        g = G.grid("knot")
        segs = 14
        prof = [(0.0, 0.66, 0.5), (0.2, 0.9, 0.85), (0.45, 1.0, 1.0), (0.7, 0.96, 0.95),
                (0.88, 0.88, 0.8), (1.0, 0.8, 0.55)]
        for (v, kw, kd) in prof:
            w, d = T["knot_w_m"] * kw * 0.5, T["knot_d_m"] * kd
            cx = T["knot_skew_m"] * math.sin(math.pi * v)
            cz = z_top - T["knot_h_m"] * v
            cyk = y_knot + 0.004 - T["knot_d_m"] * 0.25 * v   # leans forward at the bottom
            pts, uvs = [], []
            for i in range(segs + 1):
                a = math.pi * (0.5 - i / segs) * 1.0  # front half-ellipse, left to right
                a = lerp(-math.pi * 0.95, math.pi * 0.95, i / segs)
                x = cx + w * math.sin(a)
                y = cyk - d * max(math.cos(a), -0.15)
                pts.append(Vector((x, y, cz)))
                uvs.append((0.5 + 0.12 * i / segs, 0.6 + T["knot_h_m"] * v))
            g.add_row(pts, uvs)
        g.fill(G.uv, G.tag, 1, flip=True)
        # cap the top
        top = g.rows[0]
        try:
            f = G.bm.faces.new(list(reversed(top[:-1])))
            f.smooth = True
            for loop in f.loops:  # planar UVs, so the tangent is defined
                loop[G.uv].uv = (0.5 + loop.vert.co.x, 0.6 - 0.03 - loop.vert.co.y * 0.5)
            import bmesh
            bmesh.ops.triangulate(G.bm, faces=[f])
        except ValueError:
            pass
        for row in g.rows:
            G.weight(row, {"spine_03", "neck_01", "clavicle_l", "clavicle_r"})
        # blade, over the shirt front
        shirt_tree = sb.bvh_of([self.shirt])
        z_kb = z_top - T["knot_h_m"]
        z_end = self.z_v - 0.03
        nrows = max(6, int((z_kb - z_end) / 0.02))
        bg = G.grid("blade")
        cols = 6
        for k in range(nrows + 1):
            t = k / nrows
            z = lerp(z_kb, z_end, t)
            dd = (z_kb - z)
            w = T["blade_top_w_m"] + (T["blade_w_m"] - T["blade_top_w_m"]) * min(1.0, dd / T["blade_full_at_m"])
            dimple = T["dimple_m"] * max(0.0, 1 - dd / 0.08)
            pts, uvs = [], []
            for i in range(cols + 1):
                s = i / cols - 0.5           # -0.5 .. 0.5 across
                x = s * w
                hit = shirt_tree.ray_cast(Vector((x, -1, z)), Vector((0, 1, 0)), 2.0)
                if hit[0] is None:
                    hit = body_tree.ray_cast(Vector((x, -1, z)), Vector((0, 1, 0)), 2.0)
                    base = hit[0] - Vector((0, shirt_off, 0))
                else:
                    base = hit[0]
                n = Vector((0, -1, 0))
                lift = 0.003 + 0.003 * (1 - (2 * s) ** 2)   # slightly convex blade
                lift -= dimple * max(0.0, 1 - abs(s) * 4)    # dimple under the knot
                pts.append(Vector((x, base.y, z)) + n * lift)
                uvs.append((0.5 + 0.08 * (s + 0.5), 0.6 + T["knot_h_m"] + dd))
            # the first blade row starts inside the knot bottom
            if k == 0:
                for p in pts:
                    p.z += 0.008
                    p.y += 0.004
            bg.add_row(pts, uvs)
        bg.fill(G.uv, G.tag, 2)
        for row in bg.rows:
            G.weight(row, sb.TORSO)
        self.tie = G.finish(self.b, self.like, self.mats["silk"])
        self.marks[self.tie.name] = G.marks
        return self.tie

    # --- waistcoat ---------------------------------------------------------------------------

    def build_vest(self):
        W = self.o["waistcoat"]
        G = sb.Garment(self.part.format("waistcoat"), self.arm, self.body)
        jk = self.jk
        off = W["offset_m"]
        inner_tree = sb.bvh_of([self.shirt, self.tie])
        z0 = self.z_point
        z1 = self.z_vn + 0.01
        n = max(10, int((z1 - z0) / W["row_m"]))
        rows = [z0] + [self.z_side + 0.004] + [self.z_side + 0.02 + (z1 - self.z_side - 0.02) * k / (n - 2)
                                               for k in range(n - 1)]
        rows = sorted(set(round(z, 5) for z in rows))
        margin = W["margin_m"]

        def half(z):
            return (self.w_vest(z), min(jk.w_v(z) + margin, 0.13))
        fronts = self.front_panel(G, "front", rows, half, off, W["columns"] // 2, lip=0.0025, tag=1,
                                  hem=self.vest_hem, clear=(inner_tree, 0.003), marks=True)
        for g in fronts:
            for row in g.rows:
                G.weight(row, sb.TORSO)
        # buttonholes down the left front edge, welt pockets on both fronts
        gl = fronts[0]
        nb = W["buttons"]
        z_top, z_bot = self.z_v - 0.012, self.z_notch + 0.02
        for i in range(nb):
            z = z_top + (z_bot - z_top) * i / max(nb - 1, 1)
            G.mark(1, "buttonhole", (gl.uvs[0][1][0] + 0.014, z - rows[0]), 0.018, 0.0)
        for g, left in ((fronts[0], True), (fronts[1], False)):
            z = self.z_v - 0.06
            u0 = g.uvs[0][1][0]
            s = 1 if left else -1
            G.mark(1, "welt", [(u0 + s * 0.05, z - rows[0]), (u0 + s * 0.12, z - rows[0] + 0.008)])
        # lower back panel (shows through the vents)
        bg = G.grid("back")
        zb0, zb1 = self.z_side, self.z_side + W["back_panel_m"]
        for k in range(7):
            z = lerp(zb0, zb1, k / 6)
            cy, radii = self.slice(z)
            pts, uvs = [], []
            for i in range(37):
                a = math.pi / 2 + math.radians(lerp(-75, 75, i / 36))
                r = sb.sample_ring(radii, a) + off
                pts.append(Vector((r * math.cos(a), cy + r * math.sin(a), z)))
                uvs.append((0.5 + 0.5 * i / 36, z - zb0))
            bg.add_row(pts, uvs)
        bg.fill(G.uv, G.tag, 2)
        for row in bg.rows:
            G.weight(row, sb.TORSO)
        self.vest = G.finish(self.b, self.like, self.mats["wool"])
        self.marks[self.vest.name] = G.marks
        self.m["waistcoat"] = {"v_bottom_z": round(self.z_v, 4), "neck_point_z": round(self.z_vn, 4),
                               "side_hem_z": round(self.z_side, 4), "point_z": round(self.z_point, 4),
                               "bottom_below_waistband_m": round(self.waistband - self.z_side, 4),
                               "top_button_above_jacket_button_m": round(self.z_v - 0.012 - jk.z_b, 4)}
        return self.vest

    # --- buttons -----------------------------------------------------------------------------

    def build_buttons(self):
        B = self.o["buttons"]
        G = sb.Garment(self.part.format("buttons"), self.arm, self.body)
        jk = self.jk
        jt = sb.bvh_of([self.jacket])

        def put(tree, origin, direction, radius, height, bones, uv_at, from_inside=False):
            hit = tree.ray_cast(origin, direction, 2.0)
            if hit[0] is None:
                return 0
            n = hit[1] if hit[1].dot(direction) < 0 else -hit[1]
            if from_inside:
                n = -n
            sb.disc(G.bm, G.dl, hit[0], n, radius, height,
                    {G.gidx[k]: w for k, w in self.body.weights(hit[0], bones).items()},
                    B["segments"], G.uv, uv_at, 20.0)
            return 1

        placed = {"jacket": 0, "cuffs": 0, "vest": 0}
        for z in (jk.z_b, jk.z_b - self.o["jacket"]["button_gap_m"]):
            placed["jacket"] += put(jt, Vector((0.0, -1.0, z)), Vector((0, 1, 0)), B["jacket_r_m"],
                                    B["jacket_height_m"], sb.TORSO, (0.1, 0.1))
        # cuff buttons: four kissing buttons along the back of each sleeve end
        for side in ("l", "r"):
            axis = getattr(jk, f"sleeve_axis_{side}")
            _, L = getattr(jk, f"sleeve_L_{side}")
            for k in range(4):
                t = L - 0.028 - k * 0.0135
                C, T, up, sd = axis(t)
                back = sd * (1 if side == "l" else -1)   # hindarm side of the sleeve
                d = (back - up * 0.25).normalized()
                placed["cuffs"] += put(jt, C, d, B["cuff_r_m"], 0.003, sb.ARM[side], (0.3, 0.1),
                                       from_inside=True)
        vt = sb.bvh_of([self.vest])
        nb = self.o["waistcoat"]["buttons"]
        z_top = self.z_v - 0.012
        z_bot = self.z_notch + 0.02
        for i in range(nb):
            z = z_top + (z_bot - z_top) * i / max(nb - 1, 1)
            placed["vest"] += put(vt, Vector((0.0, -1.0, z)), Vector((0, 1, 0)), B["vest_r_m"],
                                  B["vest_height_m"], sb.TORSO, (0.5, 0.1))
        self.m["buttons_placed"] = placed
        self.buttons = G.finish(self.b, self.like, self.mats["button"])
        return self.buttons


def build(b, body, o, arm, jk, jacket, like, waistband, mats, part):
    inr = Inner(b, body, o, arm, jk, jacket, like, waistband, mats, part)
    shirt = inr.build_shirt()
    tie = inr.build_tie()
    vest = inr.build_vest()
    buttons = inr.build_buttons()
    return {"vest": vest, "shirt": shirt, "tie": tie, "buttons": buttons, "measure": inr.m,
            "marks": inr.marks}
