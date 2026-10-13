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
from .suit_build import lerp, smoothstep

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
                    hem=None, uv0=0.0, clear=None, marks=False, round_edge=0.0):
        """Two mirrored front panels (left, right) from the centre/V edge out to
        half_at(z) in x, lofted over the torso slices at `offset`. The V edge
        is where half_at's inner bound starts: inner(z). round_edge (with a
        lip): the V edge is a pressed, rounded edge, a quarter round of radius lip/2,
        the front flat to round_edge from it. Returns the grids."""
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
                if lip and round_edge:
                    # the V edge rolls over in a quarter round (cloth
                    # thickness): a thin highlight line along the edge that
                    # reads in the lapels' shadow, where the flat front is
                    # black on the jacket's black. Not a half round turned
                    # under: its back faces looked backwards, and the deform
                    # rig's rest tuck read them as pierced through the lapel
                    # and sank them 3 cm forward (a spike beside the tie)
                    p0, p1 = pts[0], pts[1]
                    n = Vector((math.cos(a_in), math.sin(a_in), 0.0))
                    e = (p0 - p1) - n * (p0 - p1).dot(n)
                    e = e.normalized()
                    rr = 0.5 * lip
                    c = p0 - n * rr
                    ring = [c + n * (rr * math.cos(th)) + e * (rr * math.sin(th))
                            for th in (math.pi / 2, math.pi / 4)]
                    pts[1:1] = [p0 - e * round_edge]
                    uvs[1:1] = [(uvs[0][0] + 0.002 * s, uvs[0][1])]
                    pts[0:0] = ring
                    uvs[0:0] = [(uvs[0][0] - 0.0007 * s * (2 - k), uvs[0][1]) for k in range(2)]
                elif lip:
                    # an inner lip column at the V/centre edge (cloth thickness)
                    p0, p1 = pts[0], pts[1]
                    n = Vector((math.cos(a_in), math.sin(a_in), 0.0))
                    pts.insert(0, p0 - n * lip + (p0 - p1).normalized() * 0.0005)
                    uvs.insert(0, (uvs[0][0] - 0.002 * s, uvs[0][1]))
                g.add_row(pts, uvs)
            g.fill(G.uv, G.tag, tag, flip=not left)
            grids.append(g)
            if marks:
                c0 = (2 if round_edge else 1) if lip else 0
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
        nf = self.neck
        z1 = nf.zb(-math.pi / 2) + S["front_into_band_m"]   # up inside the collar band
        rows = [z0 + (z1 - z0) * k / 14 for k in range(15)]
        margin = S["front_margin_m"]

        def half(z):
            return (0.0, min(self.w_vest(z) + margin, 0.11))
        fronts = self.front_panel(G, "front", rows, half, off, 8, tag=1)
        self.m["shirt_front_raised_verts"] = self.front_to_neckline(fronts, z0, z1, off)
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
        # where the front and placket run up into the collar band, keep them
        # inside it (they would cross the band, which is the same 5 mm off the skin)
        inset = 0
        for v in G.bm.verts:
            a, z, r = nf.polar(v.co)
            if nf.zb(a) - 0.001 <= z <= nf.zt(a):
                lim = nf.band_r(a, z) - S["band_inset_m"]
                if r > lim:
                    v.co = nf.point(a, z, lim)
                    inset += 1
        self.m["shirt_front_inset_verts"] = inset
        self.build_shirt_collar(G)
        if S["yoke"]:
            self.build_yoke(G)
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

    def front_to_neckline(self, grids, z0, z1, off, gap=0.0015, x_full=0.045, x_none=0.065):
        """The front's top edge follows the collar band's bottom edge, which
        dips at the centre and rises round the neck, instead of a level line
        at the centre-front height: level, it stood proud of the band under the
        collar points as a white ledge. Each column is stretched up to just
        under the band (`gap`; running into it, the faces crossed the band) and
        re-lofted on the torso at its new height (faded out past the side of
        the neck, where the jacket collar covers the front). At the centre the
        front already runs up inside the band and stays."""
        nf = self.neck
        cache = {}
        moved = 0
        for g in grids:
            for row in g.rows:
                for v in row:
                    z = v.co.z
                    if z <= z0 + 1e-6:
                        continue
                    w = 1.0 - smoothstep((abs(v.co.x) - x_full) / (x_none - x_full))
                    if w <= 0.0:
                        continue
                    a = nf.polar(v.co)[0]
                    top = z1 + w * (nf.zb(a) - gap - z1)
                    if top <= z1 + 1e-4:
                        continue
                    z2 = z0 + (z - z0) * (top - z0) / (z1 - z0)
                    key = round(z2, 3)
                    if key not in cache:
                        cache[key] = self.slice(key)
                    cy, radii = cache[key]
                    aa = sb.angle_at_x(cy, radii, v.co.x, front=True, ease=lambda a: off)
                    r = sb.sample_ring(radii, aa) + off
                    v.co = Vector((r * math.cos(aa), cy + r * math.sin(aa), z2))
                    moved += 1
        return moved

    def build_shirt_collar(self, G):
        """Band, fold and fall with two points, plus the front closure
        (suit_neck.build_shirt_collar, in the neck frame shared with the
        jacket collar). The points stay under the jacket where they meet it."""
        from . import suit_neck
        info = suit_neck.build_shirt_collar(self.neck, G, self.o["shirt"]["collar"],
                                            NECK | {"spine_03", "clavicle_l", "clavicle_r"}, 3)
        G.bm.normal_update()
        jt = sb.bvh_of([self.jacket])
        g = info["grid"]
        # radial order check against the built jacket (the frame already keeps
        # them apart; this catches the block's straight strips near the gorge)
        nf = self.neck
        tucked = 0
        for v in [v for row in g.rows for v in row]:
            a, z, r = nf.polar(v.co)
            d = nf.radial(v.co)
            hit = jt.ray_cast(nf.point(a, z, 0.01), d, 0.4)
            if hit[0] is not None and hit[3] + 0.01 < r + 0.002:
                r_new = max(hit[3] + 0.01 - 0.002, nf.r_body(a, z) + 0.004)
                v.co = nf.point(a, z, r_new)
                tucked += 1
        # the root strips lie on the skin: keep them under the jacket along the
        # skin normal
        for rg in (info["root"] if self.o["shirt"]["collar"].get("ring_tuck", True) else []):
            for v in [v for row in rg.rows[2:] for v in row]:
                bh = nf.tree.find_nearest(v.co, 0.05)
                if bh[0] is None:
                    continue
                n = (v.co - bh[0])
                n = n.normalized() if n.length > 1e-6 else bh[1]
                hit = jt.ray_cast(bh[0], n, 0.03)
                if hit[0] is not None:
                    room = hit[3]
                    want = min((v.co - bh[0]).length, max(0.0012, room - 0.0025))
                    if want < (v.co - bh[0]).length - 1e-5:
                        v.co = bh[0] + n * want
                        tucked += 1
        self.m["shirt_collar_tucked_verts"] = tucked
        self.m["shirt_collar"] = {k: v for k, v in info.items() if k not in ("grid", "closure", "root")}
        self.collar_front_z = info["z_base_front"]
        return g

    def build_yoke(self, G):
        """Shoulder panels from the collar base out to the deltoids, draped on
        the body's top surface (vertical rays): what shows where the jacket
        collar, lapels and sleeve heads open (look-spec §4.3)."""
        S = self.o["shirt"]
        off = S["offset_m"] * 0.9
        tree = self.body.bvh()
        jk = self.jk
        cy, _ = self.slice(self.shirt_base_front + 0.02, self.body.verts(NECK), 0.012)
        z0 = jk.z_nb + 0.02
        from .suit_jacket import body_bideltoid
        x_in, x_out = 0.05, 0.5 * body_bideltoid(self.body) - 0.01
        ys = [cy + lerp(-0.085, 0.08, j / 10) for j in range(11)]
        down = Vector((0, 0, -1))
        missing = 0
        for left in (True, False):
            s = 1 if left else -1
            g = G.grid("yoke_l" if left else "yoke_r")
            for j, y in enumerate(ys):
                pts = []
                for i in range(11):
                    x = s * lerp(x_in, x_out, i / 10)
                    hit = tree.ray_cast(Vector((x, y, z0)), down, 0.3)
                    pts.append(hit[0] + hit[1] * off if hit[0] is not None and hit[1].z > 0.05 else None)
                valid = [i for i, p in enumerate(pts) if p is not None]
                if not valid:
                    continue
                for i, p in enumerate(pts):
                    if p is None:
                        missing += 1
                        pts[i] = pts[min(valid, key=lambda v: abs(v - i))].copy()
                g.add_row(pts, [(1.0 + 0.25 * i / 10, 0.02 * j) for i in range(11)])
            g.fill(G.uv, G.tag, 5, flip=not left)
            for row in g.rows:
                G.weight(row, sb.TORSO | {"neck_01"})
            # the yoke stays under the jacket wherever the jacket covers it
            G.bm.normal_update()
            tucked = sb.tuck_under([v for row in g.rows for v in row], sb.bvh_of([self.jacket]),
                                   gap=0.003, reach=0.05)
            self.m["shirt_yoke_tucked_verts"] = self.m.get("shirt_yoke_tucked_verts", 0) + tucked
        self.m["shirt_yoke_missing_rays"] = missing

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
            # cuff_segments round a smooth curve through the sleeve end (16
            # straight off it read as a polygon in the hand close-ups), and the
            # outer edge a quarter round of cuff_edge_r_m (it was a square corner)
            n = S.get("cuff_segments", 16)
            base = sb.ring_points_smooth(ring, n) if n != 16 else sb.ring_points_resample(ring, n)
            rv, e = S["cuff_reveal_m"], S.get("cuff_edge_r_m", 0.0)
            prof = [(0.80, 0.0, -S["cuff_inside_m"]), (0.88, 0.0, 0.0)]
            if e:
                h = math.sqrt(0.5)
                prof += [(0.88, 0.0, rv - e), (0.88, e * (1 - h), rv - e * (1 - h)), (0.88, e, rv)]
            else:
                prof += [(0.88, 0.0, rv)]
            prof += [(0.80, 0.0, rv - 0.002)]
            g = G.grid(f"cuff_{side}")
            for k, (scale, inset, along) in enumerate(prof):
                pts = [c + (p - c) * scale - (p - c).normalized() * inset + T * along for p in base]
                g.add_row(pts + [pts[0].copy()], [(0.3 * i / n, 0.02 * k) for i in range(n + 1)])
            g.fill(G.uv, G.tag, 4, flip=True)   # the sleeve end's column order on both sides: faces out
            # cuff_rigid: the cuff is stiff, interfaced cloth and rotates with
            # the forearm as one ring (all on lowerarm; Track F's twist split
            # moves it onto the forearm twist bone). Weighted from the nearest
            # skin, the reveal took up to 0.7 hand and 0.14 thumb, and the
            # ring sheared into a zigzag when the wrist bent (high_ready)
            for row in g.rows:
                if S.get("cuff_rigid"):
                    for v in row:
                        v[G.dl].clear()
                        v[G.dl][G.gidx[f"lowerarm_{side}"]] = 1.0
                else:
                    G.weight(row, sb.ARM[side])
            G.mark_row(4, g, 2, "edge", inside_sign=-1.0, stitch_in_m=0.004)

    # --- tie ----------------------------------------------------------------------------------

    def build_tie(self):
        from . import suit_neck
        T = self.o["tie"]
        G = sb.Garment(self.part.format("tie"), self.arm, self.body)
        body_tree = self.body.bvh()
        shirt_off = self.o["shirt"]["offset_m"]
        shirt_tree0 = sb.bvh_of([self.shirt])

        def front_y(z):
            ys = [h[0].y for x in (-0.012, 0.0, 0.012)
                  for h in [shirt_tree0.ray_cast(Vector((x, -1, z)), Vector((0, 1, 0)), 2.0)] if h[0] is not None]
            return min(ys) if ys else None
        g, z_kb = suit_neck.build_knot(self.neck, G, T, self.o["shirt"]["collar"], 1, front_y)
        for row in g.rows:
            G.weight(row, {"spine_03", "neck_01", "clavicle_l", "clavicle_r"})
        z_top = z_kb + T["knot_h_m"]
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
            # (none on the first row, which tucks up inside the knot)
            dimple = T["dimple_m"] * max(0.0, 1 - dd / 0.08) if k > 0 else 0.0
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
                lift -= dimple * max(0.0, 1 - (2.5 * s) ** 2) ** 2   # dimple under the knot (smooth: a V-shaped one lit as a crisp white diamond)
                # never closer than 2.5 mm to the shirt: at 1 mm the placket
                # ridge (and the decimated shirt) showed through the dimple
                # as a white diamond
                lift = max(lift, 0.0025)
                pts.append(Vector((x, base.y, z)) + n * lift)
                uvs.append((0.5 + 0.08 * (s + 0.5), 0.6 + T["knot_h_m"] + dd))
            # the first blade row starts inside the knot bottom, but stays in
            # front of the shirt (pushed 4 mm back it went behind it at the
            # dimple, and the shirt showed under the knot as a white dot)
            if k == 0:
                for p in pts:
                    p.z += 0.008
                    hit = shirt_tree.ray_cast(Vector((p.x, -1, p.z)), Vector((0, 1, 0)), 2.0)
                    y_max = hit[0].y - 0.0015 if hit[0] is not None else p.y + 0.004
                    p.y = min(p.y + 0.004, y_max)
            bg.add_row(pts, uvs)
        bg.fill(G.uv, G.tag, 2, flip=True)   # normals out (toward the viewer)
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
        # clear 4.5 mm, more than the 2.5 mm lip turned under at the V's edge
        # (at 3 mm the lip's edge sat up to 0.7 mm behind the shirt front)
        fronts = self.front_panel(G, "front", rows, half, off, W["columns"] // 2, lip=W.get("edge_m", 0.0025), tag=1,
                                  hem=self.vest_hem, clear=(inner_tree, 0.0045), marks=True,
                                  round_edge=W.get("edge_press_m", 0.0))
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
        self.vest = G.finish(self.b, self.like, self.mats.get("vest", self.mats["wool"]))
        self.marks[self.vest.name] = G.marks
        self.m["waistcoat"] = {"v_bottom_z": round(self.z_v, 4), "neck_point_z": round(self.z_vn, 4),
                               "side_hem_z": round(self.z_side, 4), "point_z": round(self.z_point, 4),
                               "bottom_below_waistband_m": round(self.waistband - self.z_side, 4),
                               "top_button_above_jacket_button_m": round(self.z_v - 0.012 - jk.z_b, 4)}
        return self.vest

    def tuck_under_vest(self, gap=0.0015, reach=0.03):
        """Shirt and tie faces in front of the waistcoat move back behind it.
        The vest clears the shirt at its own vertices only, and its edge lip
        turns under 2.5 mm, so where the V's edge crosses the steep base of
        the collar band a shirt face showed through as a white speck beside
        each lapel. Each face is sampled (corners, edge midpoints, centre)
        with front-on rays (the vest covers the front, so a face's own
        normal does not matter); its vertices move back by the largest
        shortfall. Two passes (a move can expose a neighbour)."""
        vt = sb.bvh_of([self.vest])
        fwd = Vector((0.0, 1.0, 0.0))
        moved = set()
        for _ in range(2):
            for ob in (self.shirt, self.tie):
                me = ob.data
                mw, mi = ob.matrix_world, ob.matrix_world.inverted()
                co = [mw @ v.co for v in me.vertices]
                need = {}
                for f in me.polygons:
                    pts = [co[i] for i in f.vertices]
                    c = sum(pts, Vector()) / len(pts)
                    if abs(c.x) > 0.16 or not (self.z_point - 0.01 < c.z < self.z_vn + 0.03):
                        continue
                    samples = pts + [(pts[k] + pts[(k + 1) % len(pts)]) * 0.5 for k in range(len(pts))] + [c]
                    short = 0.0
                    for q in samples:
                        hit = vt.ray_cast(Vector((q.x, q.y - reach, q.z)), fwd, 2 * reach)
                        if hit[0] is not None:
                            short = max(short, hit[0].y + gap - q.y)
                    if short > 1e-5:
                        for i in f.vertices:
                            need[i] = max(need.get(i, 0.0), short)
                for i, d in need.items():
                    p = co[i]
                    me.vertices[i].co = mi @ Vector((p.x, p.y + d, p.z))
                    moved.add((ob.name, i))
                me.update()
        self.m["tucked_under_vest"] = len(moved)
        return len(moved)

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


def build(b, body, o, arm, jk, jacket, like, waistband, mats, part, neck):
    inr = Inner(b, body, o, arm, jk, jacket, like, waistband, mats, part)
    inr.neck = neck
    shirt = inr.build_shirt()
    tie = inr.build_tie()
    vest = inr.build_vest()
    inr.tuck_under_vest()
    buttons = inr.build_buttons()
    return {"vest": vest, "shirt": shirt, "tie": tie, "buttons": buttons, "measure": inr.m,
            "marks": inr.marks}
