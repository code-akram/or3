"""The jacket, built parametrically (suit_build.py primitives; bench/m1/suit.md).

    block    horizontal slices of the torso from the hem to the shoulder line,
             eased, canvassed, waist-suppressed, skirt hanging straight from
             the hips; front closure with a left-over-right overlap below the
             fastening button and the roll line (the V) above it; a non-planar
             neckline row on top (gorge at the front, collar seam at the back)
    lapels   a flap folded back along the roll line: fold bulge, roll height,
             edge lip; the width grows from the button to the gorge; the tip
             rises past the gorge to make the notch with the collar
    collar   stand + fold + fall around the neckline, resting on the shoulders,
             ends extended past the gorge (the notch's upper edge)
    vents    double side vents: split column, lifted outer flap, underlap
    sleeves  tubes along the arm bones, head sewn to the block (ray cast onto
             the armhole), roped sleeve head, slim taper, cuff lip
    pockets  flapped hip pockets and a slanted breast welt as thin panels

Every size is a parameter (suit.DEFAULTS["jacket"]); landmarks come from the
body and the rig, never from reference images.
"""

import math

import bmesh
from mathutils import Vector

from . import suit_build as sb
from .suit_build import TAU, lerp, smoothstep

TAG = {"block": 1, "lapel": 2, "collar": 3, "sleeve_l": 4, "sleeve_r": 5, "underlap": 6,
       "pocket": 7, "welt": 8}


class Jacket:
    def __init__(self, G, body, J, stature, z_button, supra):
        self.G, self.body, self.J = G, body, J
        self.stature = stature
        self.z_b = z_button
        self.supra = supra
        self.N = J["columns"]
        self.m = {}
        sh = J["shoulder"]
        self.z_h = J["hem_to_suprasternale"] * supra
        neck = body.joint("neck_01").z
        self.z_nb = neck + sh["back_neck_m"]          # back collar seam
        self.z_np = self.z_nb - sh["neck_point_drop_m"]  # neck point (shoulder seam at the neck)
        self.z_g = self.z_np - J["lapel"]["gorge_below_neck_m"]  # gorge / shoulder ring
        self.z_sh = self.z_g
        self.x_n = sh["neck_half_m"]
        js = body.joint("upperarm_l")
        self.z_pit = js.z - sh["armpit_below_joint_m"]
        self.z_hip = body.joint("pelvis").z
        self.half_sh = 0.5 * body_bideltoid(body) + sh["over_body_m"]
        self.ease = J["ease"]
        self.rings = []   # per planar row: dict(z, cy, radii, a0, a1, pts)

    # --- the V (roll line) and front ends -------------------------------------------------

    def w_v(self, z):
        """Half-width of the V at z (0 at the button, x_n at the neck point)."""
        if z <= self.z_b:
            return 0.0
        return self.x_n * (z - self.z_b) / (self.z_np - self.z_b)

    def end_x(self, z, left):
        """x of the panel's front edge at z. Left panel: overlaps to -overlap
        below the button, cut away toward the hem; above the button the edge
        is the roll line. Right panel mirrored, tucked under."""
        J = self.J
        ov = J["overlap_m"]
        if z > self.z_b:
            x = self.w_v(z)
            lift = smoothstep((z - self.z_b) / J["front_cut_m"])
            x = lerp(-ov if left else ov * 0.75, x, lift) if left else lerp(-ov * 0.75, -x, lift)
            return x
        cut = J["quarter_cut_m"] * smoothstep((self.z_h + J["quarter_height_m"] - z) / J["quarter_height_m"])
        return (-ov + cut) if left else (ov * 0.75 - cut)

    # --- slices -------------------------------------------------------------------------------

    def ease_fn(self, z):
        e = self.ease
        zb = self.z_b

        def zone(front, waist, hip):
            # chest above zb + 0.09, waist around zb, hip below zb - 0.08
            if z > zb + 0.02:
                t = smoothstep((z - zb - 0.02) / 0.08)
                return lerp(waist, front, t)
            t = smoothstep((zb - 0.02 - z) / 0.07)
            return lerp(waist, hip, t)

        ef = zone(e["chest"], e["waist_front"], e["hip"])
        eb = zone(e["back"], e["waist_back"], e["hip"])
        es = zone(e["side"], e["waist_side"], e["hip"])
        # over the deltoids the side ease closes to the shoulder-point allowance
        sh = self.J["shoulder"]
        es = lerp(es, sh["over_body_m"], smoothstep((z - self.z_pit) / max(self.z_sh - self.z_pit, 1e-6)))

        def f(a):
            s, c = math.sin(a), math.cos(a)
            wf = max(0.0, -s) ** 2
            wb = max(0.0, s) ** 2
            ws = c * c
            return wf * ef + wb * eb + ws * es
        return f

    def levels(self):
        J = self.J
        zs = []
        z = self.z_h
        while z < self.z_hip - 1e-6:
            zs.append(z)
            z += J["row_skirt_m"]
        z = self.z_hip
        while z < self.z_pit - 1e-6:
            zs.append(z)
            z += J["row_body_m"]
        z = self.z_pit
        while z < self.z_sh - 1e-6:
            zs.append(z)
            z += J["row_top_m"]
        zs.append(self.z_sh)
        # make sure a row sits at the button and one just above it (the lapel start)
        zs = sorted(set(round(x, 5) for x in zs + [self.z_b, self.z_b + 0.012]))
        return zs

    def build_rings(self):
        body = self.body
        torso = body.verts(sb.TORSO)
        J = self.J
        sh = J["shoulder"]
        js = body.joint("upperarm_l")
        z_cap = js.z - sh["cap_below_joint_m"]
        cap = [v for v in body.verts({"upperarm_l", "upperarm_r"}) if v.co.z > js.z - 0.06]
        # the shoulder point's height: the body's top over the deltoid (rays
        # down at the shoulder line's x) + the pad clearance. No horizontal row
        # lies above it (a horizontal slice of the sloping shoulder folds): the
        # yoke sheet spans from the last row below it up to the ring
        tree = body.bvh()
        down = Vector((0, 0, -1))
        cy_s = 0.5 * (body.joint("upperarm_l").y + body.joint("clavicle_l").y)
        tops = []
        for x in (self.half_sh - 0.04, self.half_sh - 0.025, self.half_sh - 0.01):
            for y in (cy_s - 0.03, cy_s, cy_s + 0.03):
                for sx in (1, -1):
                    hit = tree.ray_cast(Vector((sx * x, y, 1.9)), down, 0.6)
                    if hit[0] is not None and hit[1].z > 0.2:
                        tops.append(hit[0].z)
        self.z_sp = (max(tops) if tops else js.z) + sh["clear_m"]
        self.m["shoulder_point_body_top_z"] = round(self.z_sp - sh["clear_m"], 4)
        # the deltoid ring: the widest slice of torso + shoulder caps; the top
        # ring has its shape, narrowed in x to the shoulder line and shallower
        # (the trapezius slice stretched in x gave a thin wedge)
        deltoid = None
        for dz in (-0.035, -0.025, -0.015, -0.005, 0.005):
            cy_c, rad = sb.slice_profile(torso + cap, js.z + dz, J["slice_band_m"], min_pts=60)
            nb = len(rad)
            xe = max(rad[i] * abs(math.cos(TAU * (i + 0.5) / nb)) for i in range(nb))
            if deltoid is None or xe > deltoid[0]:
                deltoid = (xe, cy_c, rad)
        self.x_cap, cy_cap, cap_radii = deltoid
        cap_radii = sb.chord_fill(sb.smooth_ring(cap_radii, 2), limit=J["canvas_limit_m"])
        self.z_cap = z_cap
        run_max = None
        rows = []
        # between the armpit and the shoulder point the block encloses the
        # deltoid out to the armhole: the scye runs from the pit (at the torso's
        # side) up to the shoulder point, and the body inboard of it is the
        # block's, outboard of it the sleeve's
        cap_all = [v for v in body.verts({"upperarm_l", "upperarm_r"}) if v.co.z > self.z_pit - 0.03]
        _, pit_r = sb.slice_profile(torso, self.z_pit, J["slice_band_m"], min_pts=60)
        nb = len(pit_r)
        self.x_pit_body = max(pit_r[i] * abs(math.cos(TAU * (i + 0.5) / nb)) for i in range(nb))
        for z in reversed(self.levels()):
            if z >= self.z_sh - 1e-6:
                rows.append({"z": z, "cy": cy_cap, "raw": list(cap_radii), "cap": True})
                continue
            if z > self.z_sp - sh["under_cap_m"]:
                continue
            try:
                vs = torso
                if z > self.z_pit:
                    u = (z - self.z_pit) / max(self.z_sp - self.z_pit, 1e-6)
                    x_lim = lerp(self.x_pit_body, self.half_sh, u ** sh["scye_pow"]) + 0.005
                    vs = torso + [v for v in cap_all if abs(v.co.x) <= x_lim]
                cy, radii = sb.slice_profile(vs, z, J["slice_band_m"], min_pts=60)
                radii = sb.smooth_ring(radii, 2)
                radii = sb.chord_fill(radii, limit=J["canvas_limit_m"])
            except ValueError:  # below the seat: no torso vertices, the skirt hangs
                cy, radii = rows[-1]["cy"], rows[-1]["raw"]
            rows.append({"z": z, "cy": cy, "raw": radii})
        rows.reverse()
        # skirt: hangs straight from the widest point at or above each level
        rows.reverse()
        for r in rows:
            if r["z"] <= self.z_hip + 1e-6:
                if run_max is None:
                    run_max = list(r["raw"])
                else:
                    run_max = [max(a, b) for a, b in zip(run_max, r["raw"])]
                r["raw"] = list(run_max)
        rows.reverse()
        N = self.N
        for r in rows:
            z = r["z"]
            ease = self.ease_fn(z)
            radii = r["raw"]
            # flare toward the hem
            if z < self.z_hip:
                fl = J["ease"]["flare"] * (self.z_hip - z) / (self.z_hip - self.z_h)
                radii = [x + fl for x in radii]
            # shoulder zone: the slice is widened in x only, so the sides reach the
            # shoulder point while the chest and back keep the body's depth
            if z >= self.z_pit - 1e-6:
                t = smoothstep((z - self.z_pit) / max(self.z_sh - self.z_pit, 1e-6)) ** sh["bulge_pow"]
                nb = len(radii)
                x_prof = max(radii[i] * abs(math.cos(TAU * (i + 0.5) / nb)) for i in range(nb))
                x_pit = self._x_pit if hasattr(self, "_x_pit") else x_prof
                if not hasattr(self, "_x_pit"):
                    self._x_pit = x_prof
                x_want = lerp(x_pit, self.half_sh - ease(0.0), t)
                if r.get("cap"):
                    k, g = x_want / max(x_prof, 1e-6), sh["depth_top"]
                else:
                    k, g = max(1.0, x_want / max(x_prof, 1e-6)), 1.0
                pts = [(radii[i] * math.cos(TAU * (i + 0.5) / nb) * k,
                        radii[i] * math.sin(TAU * (i + 0.5) / nb) * g) for i in range(nb)]
                radii = sb.smooth_ring(sb.polar_profile(pts, nb), 1)
            r["radii"] = radii
            r["ease"] = ease
            xl, xr = self.end_x(z, True), self.end_x(z, False)
            a0 = sb.angle_at_x(r["cy"], radii, xl, front=True, ease=ease)
            a1 = sb.angle_at_x(r["cy"], radii, xr, front=True, ease=ease) + TAU
            pts = sb.ring_points(r["cy"], radii, z, a0, a1, N, ease)
            if z <= self.z_b:
                # the right front edge tucks under the left: pull its last columns in
                for i in range(N - 2, N + 1):
                    k = (i - (N - 3)) / 3.0
                    p = pts[i]
                    c = Vector((0.0, r["cy"], z))
                    d = (p - c)
                    pts[i] = c + d * (1 - J["underlap_tuck_m"] * k / max(d.length, 1e-6))
            r.update({"a0": a0, "a1": a1, "pts": pts})
        # shoulder slope: the ring runs from the neck point down to the shoulder
        # point (the body's top over the deltoid + the pad), never below the
        # trapezius + clearance, smoothed along the line away from the neck
        top = rows[-1]["pts"]
        for p in top:
            t = smoothstep((abs(p.x) - self.x_n) / max(self.half_sh - self.x_n, 1e-6))
            p.z = lerp(self.z_sh, min(self.z_sp, self.z_sh), t)
        clear = sh["clear_m"]
        lifted = 0
        for _ in range(2):
            lifted += sb.lift_onto_body(tree, top, clear, above=0.15)
            for _ in range(2):
                zs = [p.z for p in top]
                for i in range(1, N):
                    if abs(top[i].x) > self.x_n + 0.02:
                        top[i].z = 0.25 * zs[i - 1] + 0.5 * zs[i] + 0.25 * zs[i + 1]
        self.m["shoulder_verts_lifted"] = lifted
        self.m["shoulder_point_z"] = round(max(top, key=lambda p: p.x).z, 4)
        self.m["shoulder_drop_m"] = round(self.z_sh - max(top, key=lambda p: p.x).z, 4)
        # the yoke sheet between the last deltoid-level row and the ring: rows
        # interpolated by column (not horizontal slices), each lifted over the
        # trapezius and the deltoid cap, so the sheet drapes over them
        base, ring = rows[-2], rows[-1]
        K = sh["yoke_rows"]
        mid = []
        for k in range(1, K):
            t = k / K
            pts = [a.lerp(b, t) for a, b in zip(base["pts"], ring["pts"])]
            sb.lift_onto_body(tree, pts, clear, above=0.15)
            for _ in range(2):
                zs = [p.z for p in pts]
                for i in range(1, N):
                    pts[i].z = 0.25 * zs[i - 1] + 0.5 * zs[i] + 0.25 * zs[i + 1]
            mid.append({"z": lerp(base["z"], ring["z"], t), "cy": lerp(base["cy"], ring["cy"], t),
                        "raw": ring["raw"], "radii": ring["radii"], "ease": ring["ease"],
                        "a0": ring["a0"], "a1": ring["a1"], "pts": pts, "yoke": True})
        rows = rows[:-1] + mid + [ring]
        self.rings = rows
        return rows

    def neckline(self):
        """Top row: the collar seam, gorge points at the front rising to the back."""
        J = self.J
        N = self.N
        top = self.rings[-1]
        body = self.body
        neck = body.verts({"neck_01", "head"})
        cy, radii = sb.slice_profile(neck, self.z_np + 0.01, 0.012, min_pts=30)
        radii = sb.smooth_ring(sb.chord_fill(radii), 2)
        pts = []
        ease = J["shoulder"]["neck_ease_m"]
        x_g = abs(top["pts"][0].x)
        # the neckline runs from the gorge, on the neck circle, round the back
        a0 = sb.angle_at_x(cy, radii, min(x_g, max(radii) + ease - 0.005), front=True,
                           ease=lambda a: ease)
        a1 = sb.angle_at_x(cy, radii, -min(x_g, max(radii) + ease - 0.005), front=True,
                           ease=lambda a: ease) + TAU
        for i in range(N + 1):
            c = i / N
            b = math.sin(math.pi * c)  # 0 at the gorge ends, 1 at the back
            a = a0 + (a1 - a0) * c
            z = lerp(self.z_g, self.z_nb, b ** J["shoulder"]["neck_curve_pow"])
            r = sb.sample_ring(radii, a) + ease
            p = Vector((r * math.cos(a), cy + r * math.sin(a), z))
            if i == 0 or i == N:  # the gorge points are the top row's ends
                p = top["pts"][i].copy()
            pts.append(p)
        # the collar seam rides over the trapezius where it rises above the neck circle
        self.m["neckline_verts_lifted"] = sb.lift_onto_body(body.bvh(), pts[1:-1],
                                                            J["shoulder"]["clear_m"], above=0.15)
        self.neck_pts = pts
        self.neck_cy = cy
        return pts

    # --- block grid -------------------------------------------------------------------------

    def build_block(self):
        G = self.G
        N = self.N
        g = G.grid("block")
        C = self.J["uv_circ_m"]
        for r in self.rings:
            v = r["z"] - self.z_h
            g.add_row(r["pts"], [(C * i / N, v) for i in range(N + 1)])
        self.neckline()
        g.add_row(self.neck_pts, [(C * i / N, self.neck_pts[i].z - self.z_h) for i in range(N + 1)])
        g.fill(G.uv, G.tag, TAG["block"])
        self.block = g
        # marks: side seams, centre back seam, front edges + buttonholes, hem edge
        k_pit = max(k for k, r in enumerate(self.rings) if r["z"] <= self.z_pit)
        ring = self.rings[k_pit]["pts"]
        i_l = max(range(N + 1), key=lambda i: ring[i].x)
        i_r = min(range(N + 1), key=lambda i: ring[i].x)
        i_cb = max(range(N + 1), key=lambda i: ring[i].y)
        tag = TAG["block"]
        for i in (i_l, i_r):
            G.mark_column(tag, g, i, "seam")
        k_vent = max(k for k, r in enumerate(self.rings) if r["z"] <= self.z_h + self.J["vent_height_m"])
        G.mark_column(tag, g, i_cb, "seam", rows=range(k_vent, len(g.rows)))
        k_b = max(k for k, r in enumerate(self.rings) if r["z"] <= self.z_b)
        G.mark_column(tag, g, 0, "edge", rows=range(0, k_b + 1), inside_sign=1.0)
        G.mark_column(tag, g, N, "edge", rows=range(0, k_b + 1), inside_sign=-1.0)
        G.mark_row(tag, g, 0, "edge", inside_sign=1.0)
        for z in (self.z_b, self.z_b - self.J["button_gap_m"]):
            G.mark(tag, "buttonhole", (0.02 + 0.012, z - self.z_h), 0.024, 0.0)
        # vents: the top of each slit gets a bar tack, the flap edges a topstitch
        self.i_cb = i_cb
        # weights: torso, blending toward the legs down the skirt
        for k, row in enumerate(g.rows):
            z = row[0].co.z if k < len(self.rings) else self.z_nb
            if z < self.z_hip:
                f = self.J["skirt_leg_weight"] * smoothstep((self.z_hip - z) / (self.z_hip - self.z_h))
                for v in row:
                    wt = self.body.weights(v.co, sb.TORSO)
                    wl = self.body.weights(v.co, sb.LEG["l"] | sb.LEG["r"] | {"pelvis"})
                    v[G.dl].clear()
                    for kk, x in wt.items():
                        v[G.dl][G.gidx[kk]] = x * (1 - f)
                    for kk, x in wl.items():
                        v[G.dl][G.gidx[kk]] = v[G.dl].get(G.gidx[kk], 0.0) + x * f
            else:
                G.weight(row, sb.TORSO)
        return g

    def surface(self, row_k, s, left=True):
        """Point and outward normal on row row_k at arc distance s from the
        left (s >= 0 from column 0) or right end (from column N, going back)."""
        pts = self.block.rows[row_k]
        ring = [v.co for v in pts] if left else [v.co for v in reversed(pts)]
        if s < 0:
            t = (ring[1] - ring[0]).normalized()
            n = t.cross(Vector((0, 0, 1))).normalized() * (1 if left else -1)
            return ring[0] + t * s, n, t
        p = sb.point_at_arc(ring, s)
        # tangent at s
        acc = 0.0
        t = (ring[1] - ring[0]).normalized()
        for a, b in zip(ring, ring[1:]):
            L = (b - a).length
            if acc + L >= s:
                t = (b - a).normalized()
                break
            acc += L
        n = t.cross(Vector((0, 0, 1))).normalized() * (1 if left else -1)
        return p, n, t

    # --- lapels ------------------------------------------------------------------------------

    def build_lapels(self):
        G, J = self.G, self.J["lapel"]
        N = self.N
        rows_k = [k for k, r in enumerate(self.rings) if self.z_b - 1e-6 <= r["z"] <= self.z_g + 1e-6]
        for left in (True, False):
            g = G.grid("lapel_l" if left else "lapel_r")
            col = 0 if left else N
            for k in rows_k:
                z = self.rings[k]["z"]
                u = (z - self.z_b) / (self.z_g - self.z_b)
                w = J["width_m"] * (1 - (1 - u) ** J["width_pow"])
                s_e = lerp(-self.J["overlap_m"] * 0.8, w, smoothstep(u / J["swing_u"]))
                h = J["roll_m"] * (0.3 + 0.7 * math.sin(math.pi * u) ** 0.7)
                h *= min(1.0, max(0.0, s_e / 0.03))
                e = J["edge_m"]
                # the top edge (gorge line) tilts up toward the lapel point over
                # the last rows, so the point sits above the gorge without a wall
                rise = J["tip_rise_m"] * smoothstep((u - (1 - J["rise_frac"])) / J["rise_frac"])
                self.lapel_row(g, k, col, left, s_e, h, e, u, rise=rise, tip=(k == rows_k[-1]))
            g.fill(G.uv, G.tag, TAG["lapel"], flip=not left)
            for row in g.rows[1:]:
                for v in row[1:]:
                    G.copy_weights(row[0], v)
            setattr(self, "lapel_l" if left else "lapel_r", g)
            # edge stitch along the lapel edge (column 5) and its top edge; the
            # left lapel carries the buttonhole
            full = [k for k, row in enumerate(g.rows) if len(set(id(v) for v in row)) > 1]
            G.mark_column(TAG["lapel"], g, 5, "edge", rows=full, inside_sign=-1.0)
            G.mark_row(TAG["lapel"], g, len(g.rows) - 1, "edge", cols=range(1, 6), inside_sign=-1.0)
            if left:
                k = full[int(len(full) * 0.8)]
                s_e = g.uvs[k][5][0] - 0.01
                G.mark(TAG["lapel"], "buttonhole", (0.01 + s_e * 0.55, g.uvs[k][5][1]), 0.025, 0.15)

    def lapel_row(self, g, k, col, left, s_e, h, e, u, rise=0.0, tip=False):
        root = self.block.rows[k][col]
        if s_e <= 0.004:
            # collapsed row at the start: everything on the roll line
            pts = [root] * 7
            g.add_shared_row(pts, [(0.0, u * 0.4)] * 7)
            return
        spec = [(-0.5 * h, 0.6 * h), (0.25 * h, h), (0.35 * s_e, 0.45 * h + e),
                (0.7 * s_e, 0.15 * h + e), (s_e, e), (s_e - 0.003, 0.0005)]
        verts = [root]
        uvs = [(0.0, u * 0.4)]
        for s, hh in spec:
            p, n, t = self.surface(k, s, left)
            q = p + n * hh
            if rise:
                q.z += rise * max(0.0, s) / max(s_e, 1e-6)
            if tip and s > 0:
                q += n * (self.J["lapel"]["tip_lift_m"] * s / s_e)  # the point stands off the chest
            verts.append(g.bm.verts.new(q))
            uvs.append((max(s, 0.0) + 0.01, u * 0.4 + rise))
        g.add_shared_row(verts, uvs)

    # --- collar ------------------------------------------------------------------------------

    def build_collar(self):
        """Stand, fold and fall along the neckline. At each front end the seam
        runs E more columns along the lapel's top edge (the gorge seam) to the
        notch, where the fall edge turns up into the collar point: the notch
        opens between that leading edge and the lapel's top edge."""
        G, J = self.G, self.J["collar"]
        N = self.N
        top = self.block.rows[-1]
        under = sb.bvh_of_bm(G.bm)
        g = G.grid("collar")
        cy = self.neck_cy
        E = J["end_columns"]
        seam_m = J["gorge_seam_m"]
        up = Vector((0, 0, 1))

        def lapel_top(left):
            grid = self.lapel_l if left else self.lapel_r
            return [v.co.copy() for v in grid.rows[-1]]   # root (gorge point) outward, lip last

        # seam: lapel top edge (left, from the seam end in), neckline, lapel top edge (right)
        seam = []  # (point, shared vert or None, e in [0, 1] along the gorge seam, left)
        lt = {True: lapel_top(True), False: lapel_top(False)}
        for k in range(E, 0, -1):  # column 0 of the neckline is the wearer's left end
            seam.append((sb.point_at_arc(lt[True], seam_m * k / E), None, k / E, True))
        for i in range(N + 1):
            seam.append((top[i].co.copy(), top[i], 0.0, i < N // 2))
        for k in range(1, E + 1):
            seam.append((sb.point_at_arc(lt[False], seam_m * k / E), None, k / E, False))
        M = len(seam)
        # the collar point: from the gorge seam end, up at notch_deg to the lapel's
        # top edge; the fall edge comes round from point_back_m behind it
        cp, f0, nrm = {}, {}, {}
        ang = math.radians(J["notch_deg"])
        G.bm.normal_update()
        for left in (True, False):
            pts = lt[left]
            e_pt = sb.point_at_arc(pts, seam_m)
            # the collar end lies in the lapel's plane: its leading edge turns up
            # from the gorge seam end by notch_deg within that plane
            hit = under.find_nearest(e_pt, 0.05)
            n = hit[1] if hit[0] is not None else Vector((e_pt.x, e_pt.y - cy, 0.0)).normalized()
            nrm[left] = n
            edge = pts[-2] - pts[0]
            edge = (edge - n * edge.dot(n)).normalized()
            upl = (up - n * up.dot(n)).normalized()
            d = (edge * math.cos(ang) + upl * math.sin(ang)).normalized()
            cp[left] = e_pt + d * J["point_m"] + n * 0.003
            end = top[0].co if left else top[N].co
            nxt = top[1].co if left else top[N - 1].co
            f0[left] = cp[left] + (nxt - end).normalized() * J["point_back_m"]
        rows = [[] for _ in range(6)]
        uvs = [[] for _ in range(6)]
        rested = 0
        for i, (p0, shared, e, left) in enumerate(seam):
            c = min(max((i - E) / N, 0.0), 1.0)  # 0..1 along the neckline
            bk = math.sin(math.pi * c)
            out = Vector((p0.x, p0.y - cy, 0.0)).normalized()
            if e == 0:
                w = smoothstep(max(0.0, 1 - min(c, 1 - c) / J["end_frac"]))
                # the fold comes down to the lapel's roll height at the gorge point
                stand = lerp(lerp(J["stand_front_m"], J["stand_back_m"], bk), J["stand_end_m"], w)
                p1 = p0 + up * stand - out * J["lean_in_m"] * (1 - w)
                p2 = p1 + up * 0.004 + out * 0.003
                d_back = (-up * 0.85 + out * 0.5).normalized()
                L_back = lerp(J["fall_front_m"], J["fall_back_m"], bk)
                v_front = f0[left] - p2
                d = (d_back * (1 - w) + v_front.normalized() * w).normalized()
                L = lerp(L_back, v_front.length, w)
                p3 = p2 + d * (L * 0.5)
                p4 = p2 + d * L
                if w < 0.5:
                    # rest the fall on what is beneath it (the yoke, the back)
                    for q in (p3, p4):
                        hit = under.find_nearest(q, 0.08)
                        if hit[0] is not None:
                            h = (q - hit[0]).dot(hit[1])
                            if h < 0.003:
                                q += hit[1] * (0.003 - h)
                                rested += 1
            else:
                # along the gorge seam the collar lies on the lapel: the fold fades
                # out and the fall edge is the collar's end, running to the point
                n = nrm[left]
                upl = (up - n * up.dot(n)).normalized()
                stand = J["stand_end_m"] * (1 - e)
                p1 = p0 + upl * stand + n * 0.002
                p2 = p1 + upl * 0.001 + n * 0.001
                p4 = f0[left].lerp(cp[left], e)
                p3 = p2.lerp(p4, 0.5) + n * 0.002
                L = (p4 - p2).length
            p5 = p4 + (p3 - p4).normalized() * 0.004 - out * 0.0025
            u = (i / M) * self.J["uv_circ_m"] * 0.55
            for j, (p, v) in enumerate(((p0, 0.0), (p1, stand), (p2, stand + 0.01),
                                        (p3, stand + 0.01 + L * 0.5), (p4, stand + 0.01 + L),
                                        (p5, stand + 0.014 + L))):
                if j == 0:
                    rows[j].append(shared if shared is not None else g.bm.verts.new(p + out * 0.001))
                else:
                    rows[j].append(g.bm.verts.new(p))
                uvs[j].append((u, v))
        # smooth the fall rows along the neck columns (resting introduces steps)
        lo, hi = E + 2, M - E - 3
        for j in (3, 4, 5):
            co = [v.co.copy() for v in rows[j]]
            for _ in range(2):
                co = [co[i] if not (lo <= i <= hi) else (co[i - 1] + 2 * co[i] + co[i + 1]) / 4
                      for i in range(len(co))]
            for v, p in zip(rows[j], co):
                v.co = p
        for j in range(6):
            g.add_shared_row(rows[j], uvs[j])
        g.fill(G.uv, G.tag, TAG["collar"], flip=True)
        for i in range(M):
            src = rows[0][i]
            if seam[i][1] is None:
                G.weight([src], sb.TORSO)
            for j in range(1, 6):
                G.copy_weights(src, rows[j][i])
        self.collar = g
        self.m["collar_rested_verts"] = rested
        G.mark_row(TAG["collar"], g, 4, "edge", inside_sign=-1.0)

    # --- vents -------------------------------------------------------------------------------

    def build_vents(self):
        G, J = self.G, self.J
        mode = J["vents"]
        if mode == "none":
            return {}
        N = self.N
        g = self.block
        hem = g.rows[0]
        half = max(abs(v.co.x) for v in hem)
        xs = [0.0] if mode == "centre" else [J["vent_x_frac"] * half, -J["vent_x_frac"] * half]
        k_top = max(k for k, r in enumerate(self.rings) if r["z"] <= self.z_h + J["vent_height_m"])
        out = {}
        for x in xs:
            # nearest back-half column at the hem
            cands = [(abs(hem[i].co.x - x), i) for i in range(N // 4, 3 * N // 4 + 1)]
            ci = min(cands)[1]
            edges = []
            for k in range(k_top):
                a, b = g.rows[k][ci], g.rows[k + 1][ci]
                e = G.bm.edges.get([a, b])
                if e:
                    edges.append(e)
            if not edges:
                continue
            res = bmesh.ops.split_edges(G.bm, edges=edges)
            G.bm.normal_update()
            z_top = self.rings[k_top]["z"]
            path_x = x
            new_col = {}
            for e in res["edges"]:
                for v in e.verts:
                    if not v.link_faces:
                        continue
                    cx = sum(f.calc_center_median().x for f in v.link_faces) / len(v.link_faces)
                    outer = abs(cx) > abs(path_x) + 1e-6 if mode == "double" else cx > 0
                    t = max(0.0, 1.0 - (v.co.z - self.z_h) / max(z_top - self.z_h, 1e-6))
                    if outer:
                        v.co += v.normal * J["vent_lift_m"] * t
                    else:
                        new_col.setdefault(round(v.co.z, 5), v)
            # underlap: a strip on the back panel's edge, under the outer flap
            inner_col = [new_col[z] for z in sorted(new_col)]
            if len(inner_col) >= 2 and J["vent_underlap_m"] > 0:
                side = 1 if x > 0 else -1
                ug = G.grid("underlap")
                for k, v in enumerate(inner_col):
                    nb = g.rows[k][min(max(ci + side, 0), N)]
                    d = (nb.co - v.co)
                    d.z = 0
                    d = d.normalized() * J["vent_underlap_m"]
                    n = v.normal
                    p = v.co + d - n * 0.0035
                    ug.add_shared_row([v, ug.bm.verts.new(p)], [(0.0, k * 0.02), (0.035, k * 0.02)])
                ug.fill(G.uv, G.tag, TAG["underlap"], flip=(x < 0))
                for row in ug.rows:
                    G.copy_weights(row[0], row[1])
            out[f"x={x:+.3f}"] = {"edges": len(edges), "top_z": round(z_top, 4)}
        return out

    # --- sleeves -----------------------------------------------------------------------------

    def build_sleeves(self):
        for side in ("l", "r"):
            self.build_sleeve(side)

    def build_sleeve(self, side):
        G, J, body = self.G, self.J["sleeve"], self.body
        sign = 1 if side == "l" else -1
        S, E, W = body.joint(f"upperarm_{side}"), body.joint(f"lowerarm_{side}"), body.joint(f"hand_{side}")
        T1, T2 = (E - S).normalized(), (W - E).normalized()
        L1, L2 = (E - S).length, (W - E).length
        L = L1 + L2 + J["past_wrist_m"]
        # shoulder point: the block's shoulder row, at the side
        top_row = self.block.rows[len(self.rings) - 1]
        SP = max(top_row, key=lambda v: v.co.x * sign).co.copy()
        t_top = (SP - S).dot(T1)
        up0 = (SP - (S + T1 * t_top)).normalized()
        z_pit = S.z - self.J["shoulder"]["armpit_below_joint_m"]
        t_pit = (S.z - z_pit) / max(-T1.z, 1e-6)

        def axis(t):
            if t < L1:
                C, T = S + T1 * t, T1
            else:
                C, T = E + T2 * (t - L1), T2
            bl = J["elbow_blend_m"]
            if abs(t - L1) < bl:
                k = (t - L1 + bl) / (2 * bl)
                T = (T1 * (1 - k) + T2 * k).normalized()
            up = (up0 - T * up0.dot(T)).normalized()
            return C, T, up, T.cross(up).normalized() * -1  # (centre, axis, up, side)

        arm = [v for v in body.verts(sb.ARM[side] - {f"hand_{side}"})]
        # project arm vertices onto the axis polyline once
        proj = []
        for v in arm:
            p = v.co
            t1 = min(max((p - S).dot(T1), 0.0), L1)
            t2 = min(max((p - E).dot(T2), 0.0), L2)
            d1 = (p - (S + T1 * t1)).length
            d2 = (p - (E + T2 * t2)).length
            t = t1 if d1 <= d2 else L1 + t2
            proj.append((t, p))
        block_tree = sb.bvh_of_bm(G.bm)
        n_cols = J["columns"]
        K = max(8, int(round((L - t_top) / J["row_m"])))
        g = G.grid(f"sleeve_{side}")
        taper0, taper1 = J["top_r_m"], J["cuff_r_m"]
        rope = J["rope_m"]
        H = J["head_rows"]

        def arm_radius(t, C, up, sd, phi):
            band = J["band_m"]
            while True:
                near = [p for (tv, p) in proj if abs(tv - t) < band]
                if len(near) >= 24 or band > 0.05:
                    break
                band *= 1.5
            if not near:
                return 0.0
            prof = sb.polar_profile([((p - C).dot(up), (p - C).dot(sd)) for p in near], 90)
            prof = sb.smooth_ring(sb.chord_fill(prof, ks=(2, 4, 8), iters=2), 2)
            return sb.sample_ring(prof, phi)

        # the scye (armhole seam): a loop on the block's surface from the shoulder
        # point down the front and the back to the armpit depth, found with
        # horizontal rays from inside the block, so the sleeve head is sewn to the
        # block all round (no open wedge under the shoulder)
        sd_y = 1.0 if axis(t_pit)[3].y > 0 else -1.0
        b_scye = J["scye_half_w_m"]
        ring0, t0, misses = [], [], 0
        for i in range(n_cols + 1):
            phi = TAU * i / n_cols
            s = (1 - math.cos(phi)) / 2
            z = lerp(SP.z, z_pit, s)
            ring = min(self.rings, key=lambda rr: abs(rr["z"] - z))
            cy = ring["cy"]
            x_ring = max(abs(p.x) for p in ring["pts"])
            yc = S.y + (T1.y / T1.z) * (z - S.z) if abs(T1.z) > 1e-3 else S.y
            y = yc + b_scye * math.sin(phi) * sd_y * (0.85 + 0.15 * (1 - s))
            o = Vector((0.0, cy, z))
            d = Vector((sign * x_ring, y - cy, 0.0)).normalized()
            hit = block_tree.ray_cast(o, d, 1.0)
            if hit[0] is None:
                C, T, up, sd = axis(t_pit)
                dd = up * math.cos(phi) + sd * math.sin(phi)
                p = C + dd * (arm_radius(t_pit, C, up, sd, phi) + J["ease_m"])
                misses += 1
            else:
                p = hit[0] + hit[1] * J["seam_out_m"]
            ring0.append(p)
            t0.append((p - S).dot(T1))
        self.m[f"scye_misses_{side}"] = misses
        g.add_row(ring0, [(J["uv_circ_m"] * i / n_cols, t0[i]) for i in range(n_cols + 1)])
        cleared = 0
        body_tree = body.bvh()

        def body_exit(C, d, reach=0.14):
            """Distance along d from C to the last skin exit (normal along d)
            within reach, or None."""
            o, acc, best = C, 0.0, None
            for _ in range(4):
                hit = body_tree.ray_cast(o, d, reach - acc)
                if hit[0] is None:
                    break
                acc += hit[3] + 1e-4
                if hit[1].dot(d) > 0:
                    best = acc
                o = hit[0] + d * 1e-4
            return best
        for k in range(1, K + 1):
            uk = k / K
            pts, uvs = [], []
            s_head = smoothstep(k / H) if k < H else 1.0
            for i in range(n_cols + 1):
                phi = TAU * i / n_cols  # 0 at the top of the arm
                t_tube = lerp(t_pit, L, uk)
                t = lerp(t0[i], t_tube, k / H) if k < H else t_tube
                C, T, up, sd = axis(t)
                d = up * math.cos(phi) + sd * math.sin(phi)
                r_arm = arm_radius(t, C, up, sd, phi)
                r = max(r_arm + J["ease_m"], lerp(taper0, taper1, (t - t_pit) / max(L - t_pit, 1e-6)))
                if k <= 3:
                    r += rope * max(0.0, math.cos(phi)) ** 2 * (0.7, 1.0, 0.5)[k - 1]
                off = d * r
                if k < H:
                    # the cross-section morphs from the scye's shape into the tube
                    # while it slides along the arm: the cap follows the deltoid
                    C0 = axis(t0[i])[0]
                    off = (ring0[i] - C0).lerp(off, s_head)
                # never inside the body: a ray from the arm axis along the point's
                # direction leaves the skin (the deltoid, the back of the shoulder,
                # the lat) at r_body; the cloth stays ease outside it
                dn = off.normalized()
                r_body = body_exit(C, dn)
                ease = J["ease_m"] * (1.6 - 0.6 * s_head)   # extra over the deltoid's bulge
                if r_body is not None and off.length < r_body + ease:
                    off = dn * (r_body + ease)
                    cleared += 1
                pts.append(C + off)
                uvs.append((J["uv_circ_m"] * i / n_cols, t))
            if k < H:
                # ridges between the rays (the axillary folds) are caught by the
                # nearest-surface push
                cleared += sb.clear_of_body(body_tree, pts, J["ease_m"] * 0.8, reach=0.03)
            g.add_row(pts, uvs)
        self.m[f"sleeve_head_cleared_{side}"] = cleared
        # cuff lip: a ring stepping back inside the sleeve end
        last = g.rows[-1]
        C, T, up, sd = axis(L)
        lip = [v.co + (C - v.co).normalized() * 0.004 - T * 0.003 for v in last]
        g.add_row(lip, [(uv[0], uv[1] + 0.005) for uv in g.uvs[-1]])
        g.fill(G.uv, G.tag, TAG[f"sleeve_{side}"], flip=(side == "r"))
        bones = sb.ARM[side] | {f"clavicle_{side}", "spine_03"}
        for row in g.rows:
            G.weight(row, bones)
        tag = TAG[f"sleeve_{side}"]
        mid = g.rows[len(g.rows) // 2]
        i_hind = max(range(n_cols), key=lambda i: mid[i].co.y)
        i_in = n_cols // 2
        G.mark_column(tag, g, i_in, "seam", rows=range(1, len(g.rows) - 1))
        G.mark_column(tag, g, i_hind, "seam", rows=range(1, len(g.rows) - 1))
        G.mark_row(tag, g, 0, "seam")
        G.mark_row(tag, g, len(g.rows) - 2, "edge", inside_sign=-1.0)
        u_h = g.uvs[0][i_hind][0]
        for k in range(4):
            G.mark(tag, "buttonhole", (u_h - 0.016 * (1 if side == "l" else -1), L - 0.028 - k * 0.0135),
                   0.015, math.pi / 2)
        setattr(self, f"sleeve_{side}", g)
        setattr(self, f"sleeve_end_{side}", [v.co.copy() for v in last[:-1]])
        setattr(self, f"sleeve_axis_{side}", axis)
        setattr(self, f"sleeve_L_{side}", (t_pit, L))

    # --- pockets -----------------------------------------------------------------------------

    def block_point(self, z, s, left=True):
        """Point and outward normal on the block at height z, arc distance s
        from the panel's front edge (interpolated between rows)."""
        rows = self.rings
        k = max(0, min(len(rows) - 2, max(i for i, r in enumerate(rows) if r["z"] <= z)))
        z0, z1 = rows[k]["z"], rows[k + 1]["z"]
        t = (z - z0) / max(z1 - z0, 1e-6)
        pa, na, _ = self.surface(k, s, left)
        pb, nb, _ = self.surface(k + 1, s, left)
        return pa.lerp(pb, t), (na.lerp(nb, t)).normalized()

    def build_pockets(self):
        G, P = self.G, self.J["pockets"]
        ov = self.J["overlap_m"]
        for left in (True, False):
            s0 = ov + P["flap_x0_m"]
            z_t = self.z_b - P["flap_below_button_m"]
            g = G.grid("pocket")
            cols = 6
            for j, (dz, h) in enumerate(((0.0, 0.0005), (-P["flap_h_m"] * 0.6, 0.0025),
                                         (-P["flap_h_m"], 0.0035), (-P["flap_h_m"] + 0.003, 0.0005))):
                pts, uvs = [], []
                for i in range(cols + 1):
                    s = s0 + P["flap_w_m"] * i / cols
                    p, n = self.block_point(z_t + dz, s, left)
                    pts.append(p + n * h)
                    uvs.append((s - s0, -dz + (0.004 if j == 3 else 0.0)))
                g.add_row(pts, uvs)
            g.fill(G.uv, G.tag, TAG["pocket"], flip=not left)
            for row in g.rows:
                G.weight(row, sb.TORSO)
            G.mark_row(TAG["pocket"], g, 2, "edge", inside_sign=-1.0)
            G.mark_column(TAG["pocket"], g, 0, "edge", rows=range(0, 3), inside_sign=1.0)
            G.mark_column(TAG["pocket"], g, cols, "edge", rows=range(0, 3), inside_sign=-1.0)
        # breast welt, left chest, slanted up toward the shoulder
        W = P["welt"]
        g = G.grid("welt")
        z0 = self.z_b + W["above_button_m"]
        s0 = self.w_v(z0) + W["from_roll_m"]
        for j, (dz, h) in enumerate(((0.0, 0.0035), (W["h_m"], 0.0035), (W["h_m"] - 0.002, 0.0005))):
            pts, uvs = [], []
            for i in range(4):
                s = s0 + W["w_m"] * i / 3
                z = z0 + W["slant"] * (s - s0) + dz
                p, n = self.block_point(z, s, True)
                pts.append(p + n * h)
                uvs.append((s - s0, dz))
            g.add_row(pts, uvs)
        g.fill(G.uv, G.tag, TAG["welt"])
        for row in g.rows:
            G.weight(row, sb.TORSO)
        G.mark_row(TAG["welt"], g, 1, "edge", inside_sign=-1.0)
        G.mark_row(TAG["welt"], g, 0, "edge", inside_sign=1.0)

    # --- measurements ------------------------------------------------------------------------

    def measure(self):
        m = dict(self.m)
        m["hem_z"] = round(self.z_h, 4)
        m["hem_to_suprasternale"] = round(self.z_h / self.supra, 4)
        m["button_stance_to_stature"] = round(self.z_b / self.stature, 4)
        m["gorge_z"] = round(self.z_g, 4)
        m["neck_point_z"] = round(self.z_np, 4)
        m["back_neck_z"] = round(self.z_nb, 4)
        m["shoulder_half_m"] = round(self.half_sh, 4)
        m["lapel_width_m"] = self.J["lapel"]["width_m"]

        def width(z):
            r = min(self.rings, key=lambda r: abs(r["z"] - z))
            xs = [p.x for p in r["pts"]]
            return max(xs) - min(xs)
        chest = max(width(z) for z in (1.30, 1.33, 1.36, 1.39))
        m["jacket_chest_width_m"] = round(chest, 4)
        m["jacket_width_at_button_m"] = round(width(self.z_b), 4)
        m["waist_suppression"] = round(width(self.z_b) / chest, 4)
        m["rows"] = len(self.rings)
        return m


def body_bideltoid(body):
    shoulder = {"upperarm_l", "upperarm_r", "clavicle_l", "clavicle_r"}
    xs = []
    for v in body.verts(shoulder):
        bone = "upperarm_l" if v.co.x > 0 else "upperarm_r"
        bb = body.arm.data.bones[bone]
        h = body.arm.matrix_world @ bb.head_local
        t = body.arm.matrix_world @ bb.tail_local
        if (v.co - h).dot((t - h).normalized()) < 0.06:
            xs.append(v.co.x)
    return max(xs) - min(xs)


def build(G, body, J, stature, z_button, supra):
    jk = Jacket(G, body, J, stature, z_button, supra)
    jk.build_rings()
    jk.build_block()
    jk.build_lapels()
    jk.build_collar()
    vents = jk.build_vents()
    jk.build_sleeves()
    jk.build_pockets()
    m = jk.measure()
    m["vents"] = vents
    return jk, m
