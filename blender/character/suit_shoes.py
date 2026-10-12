"""Shoes: black cap-toe derbies built on the body's feet (suit_build primitives).

    upper   rings across the foot (sole edge, over the instep, sole edge) at
            slices along the foot, offset by the leather thickness; the toe
            box extends past the toes and closes on an elliptical taper; the
            topline cuts the rings behind the throat (the ankle opening)
    sole    welt lip at the sole edge, sole slab with a heel block and breast
    laces   three eyelets a side on the facings, criss-cross lace tubes
    marks   cap-toe seam, quarter seams, heel counter seam, welt stitch, in
            the leather normal map (suit_textures)

Sizes are parameters (suit.DEFAULTS["shoes"]). Weights come from the foot
bones through the nearest body vertex.
"""

import math

import bmesh
from mathutils import Vector

from . import suit_build as sb
from .suit_build import TAU, lerp, smoothstep

TAG = {"upper": 1, "sole": 2, "lace": 3}


def build_shoe(G, body, S, side):
    foot = f"foot_{side}"
    bones = {foot, f"ball_{side}", f"calf_{side}"}
    fv = [v for v in body.verts({foot, f"ball_{side}"})]
    ys = [v.co.y for v in fv]
    y_heel, y_toe = max(ys), min(ys)
    cx = sum(v.co.x for v in fv) / len(fv)
    # slices along the foot (rows), from behind the heel to past the toes
    y0, y1 = y_heel + S["heel_ease_m"], y_toe - S["toe_ease_m"]
    n_rows = S["rows"]
    N = S["columns"]
    off = S["leather_m"]
    z_top = S["topline_m"]
    g = G.grid(f"upper_{side}")
    sole_edge = []  # (left, right) sole-edge points per row
    rows_y = []
    profs, scales = [], []
    last_prof = None
    for k in range(n_rows + 1):
        t = k / n_rows
        # denser rows at the toe, where curvature is
        y = lerp(y0, y1, t ** 0.85)
        rows_y.append(y)
        band = S["band_m"]
        pts = [v.co for v in fv if abs(v.co.y - y) < band]
        while len(pts) < 24 and band < 0.03:
            band *= 1.5
            pts = [v.co for v in fv if abs(v.co.y - y) < band]
        scale = 1.0
        if y < y_toe + 0.004 or len(pts) < 8:
            # past the toes: the last foot profile, tapered on an ellipse
            prof = last_prof
            u = (y_toe + 0.004 - y) / (y_toe + 0.004 - y1)
            scale = math.sqrt(max(0.0, 1 - u * u)) * 0.92 + 0.08
        else:
            # upper half-profile about (cx, 0) in the (x, z) plane; the
            # points are mirrored below the sole so the polar bins are filled.
            # The last (a stiff, lasted shoe) bridges the toes and the arch.
            prof = sb.polar_profile([(p.x - cx, p.z) for p in pts] + [(p.x - cx, -p.z) for p in pts],
                                    120)
            prof = sb.smooth_ring(sb.chord_fill(prof, ks=(2, 4, 8, 16), iters=3), 3)
            last_prof = prof
        profs.append(prof)
        scales.append(scale)
    # smooth the profiles along the foot (no lumps between slices)
    for _ in range(2):
        profs = [profs[k] if k in (0, len(profs) - 1) or scales[k] < 1.0 else
                 [(profs[k - 1][i] + 2 * profs[k][i] + profs[k + 1][i]) / 4 for i in range(len(profs[k]))]
                 for k in range(len(profs))]
    for k, y in enumerate(rows_y):
        prof, scale = profs[k], scales[k]
        # the toe box is deeper than the foot
        toe_box = S["toe_box_m"] * smoothstep((y_toe + 0.07 - y) / 0.09)
        ring, uvs = [], []
        for i in range(N + 1):
            a = math.pi * i / N  # 0: the +x sole edge, pi/2: the top, pi: the -x sole edge
            r = sb.sample_ring(prof, a) * scale + off + toe_box * math.sin(a)
            x = cx + r * math.cos(a)
            z = max(0.0, r * math.sin(a))
            p = Vector((x, y, z))
            ring.append(p)
            uvs.append((r * a, y - y_heel))  # arc length along the ring, y along the foot
        # topline: behind the throat the rings open (the ankle); the points
        # above the topline are clamped to it and the quads there skipped
        if y > S["throat_y_m"] + y_toe:
            for p in ring:
                p.z = min(p.z, z_top)
        g.add_row(ring, uvs)
        sole_edge.append((ring[0].copy(), ring[N].copy()))

    def skip(k, i):
        z_a, z_b = g.rows[k][i].co.z, g.rows[k + 1][i].co.z
        za1, zb1 = g.rows[k][i + 1].co.z, g.rows[k + 1][i + 1].co.z
        return all(z >= z_top - 1e-6 for z in (z_a, z_b, za1, zb1))

    g.fill(G.uv, G.tag, TAG["upper"], skip=skip, flip=(side == "r"))
    # close the toe: the last ring collapses to its centre line
    for row in g.rows:
        G.weight(row, bones)
    upper = g
    # marks: cap-toe seam, quarter seams, heel counter, topline
    y_cap = y_toe + S["cap_m"]
    k_cap = min(range(len(rows_y)), key=lambda k: abs(rows_y[k] - y_cap))
    G.mark_row(TAG["upper"], g, k_cap, "seam")
    y_q = y_toe + S["quarter_m"]
    k_q = min(range(len(rows_y)), key=lambda k: abs(rows_y[k] - y_q))
    G.mark_row(TAG["upper"], g, k_q, "seam", cols=range(0, N // 3))
    G.mark_row(TAG["upper"], g, k_q, "seam", cols=range(2 * N // 3, N + 1))
    k_heel = [k for k, y in enumerate(rows_y) if y > y_heel - 0.07]
    G.mark_column(TAG["upper"], g, N // 2, "seam", rows=k_heel)

    # welt and sole
    sg = G.grid(f"sole_{side}")
    outline = []  # closed outline of the sole top, from the +x heel round the toe and back
    left = [e[0] for e in sole_edge]
    right = [e[1] for e in sole_edge]
    outline = left + list(reversed(right))
    # widen by the welt
    c_line = [(l + r) / 2 for l, r in zip(left, right)]
    def widen(p, k, w):
        c = c_line[min(k, len(c_line) - 1)]
        d = p - c
        d.z = 0
        if d.length < 1e-6:
            return p.copy()
        return p + d.normalized() * w
    n = len(outline)
    rows = []
    heel_len = S["heel_len_m"]
    arc = [0.0]
    for p, q in zip(outline, outline[1:] + outline[:1]):
        arc.append(arc[-1] + (q - p).length)
    for j, (dz, w) in enumerate(((0.004, 0.0), (0.004, S["welt_m"]), (0.0, S["welt_m"] + 0.001),
                                 (None, S["welt_m"] + 0.001), (None, S["welt_m"] - 0.002))):
        pts, uvs = [], []
        for idx, p in enumerate(outline):
            k = idx if idx < len(left) else n - 1 - idx
            q = widen(p, k, w)
            if dz is None:
                heel = smoothstep((p.y - (y_heel - heel_len)) / 0.01)
                q.z = -(S["sole_m"] + (S["heel_m"] - S["sole_m"]) * heel)
            else:
                q.z = dz
            pts.append(q)
            uvs.append((arc[idx], q.z + 0.05 + 0.004 * j))  # the sole wall unrolled
        pts.append(pts[0].copy())
        uvs.append((arc[-1], uvs[0][1]))
        rows.append(pts)
        sg.add_row(pts, uvs)
    sg.fill(G.uv, G.tag, TAG["sole"], flip=(side == "l"))
    # bottom cap
    bottom = sg.rows[-1][:-1]
    try:
        f = G.bm.faces.new(bottom if side == "r" else list(reversed(bottom)))
        f.smooth = False
        for loop in f.loops:
            loop[G.uv].uv = (loop.vert.co.x - cx + 0.6, loop.vert.co.y - y_toe)
        f[G.tag] = TAG["sole"]
        bmesh.ops.triangulate(G.bm, faces=[f])
    except ValueError:
        pass
    # the welt lip joins the upper: the upper's sole-edge columns sit on row 0
    for row in sg.rows:
        G.weight(row, bones)
    G.mark_row(TAG["sole"], sg, 1, "topstitch", pitch_m=0.004, height=0.0004)

    # laces: eyelets and criss-cross tubes over the facings
    L = S["laces"]
    top_k = N // 2
    eyelets = {"l": [], "r": []}
    for j in range(L["count"]):
        y = y_toe + L["first_m"] + j * L["pitch_m"]
        k = min(range(len(rows_y)), key=lambda kk: abs(rows_y[kk] - y))
        for sgn, key in ((1, "l"), (-1, "r")):
            i = top_k + sgn * L["half_gap_cols"]
            p = upper.rows[k][i].co.copy()
            eyelets[key].append(p)
            sb.disc(G.bm, G.dl, p, Vector((0, 0, 1)), L["eyelet_r_m"], 0.0008,
                    {G.gidx[kk]: w for kk, w in body.weights(p, bones).items()}, 6, G.uv,
                    (0.05, 0.05 + 0.02 * j), 10.0)
    tube_segments = []
    for j in range(L["count"] - 1):
        tube_segments.append((eyelets["l"][j], eyelets["r"][j + 1]))
        tube_segments.append((eyelets["r"][j], eyelets["l"][j + 1]))
    # the top pair ties straight across
    tube_segments.append((eyelets["l"][-1], eyelets["r"][-1]))
    for a, b in tube_segments:
        lace_tube(G, a, b, L["radius_m"], body, bones)
    return {"rows": n_rows, "y_heel": round(y_heel, 4), "y_toe": round(y_toe, 4),
            "length_m": round(y0 - y1, 4), "topline_m": z_top}


def lace_tube(G, pa, pb, r, body, bones, sides=5):
    d = (pb - pa)
    L = d.length
    d.normalize()
    up = Vector((0, 0, 1))
    t = d.cross(up).normalized()
    u = t.cross(d)
    ring_a, ring_b = [], []
    for i in range(sides):
        ang = TAU * i / sides
        off = (t * math.cos(ang) + u * math.sin(ang)) * r
        # the lace arches above the facings
        ring_a.append(pa + off + up * (r + 0.0015))
        ring_b.append(pb + off + up * (r + 0.0015))
    mid = [(qa + qb) / 2 + up * 0.002 for qa, qb in zip(ring_a, ring_b)]
    va = [G.bm.verts.new(p) for p in ring_a]
    vm = [G.bm.verts.new(p) for p in mid]
    vb = [G.bm.verts.new(p) for p in ring_b]
    w = {G.gidx[k]: x for k, x in body.weights((pa + pb) / 2, bones).items()}
    for v in va + vm + vb:
        for k, x in w.items():
            v[G.dl][k] = x
    for r0, r1, v0 in ((va, vm, 0.0), (vm, vb, L / 2)):
        for i in range(sides):
            j = (i + 1) % sides
            f = G.bm.faces.new([r0[i], r0[j], r1[j], r1[i]])
            f.smooth = True
            f[G.tag] = TAG["lace"]
            for loop, uv in zip(f.loops, ((0.3 + i * 0.002, v0), (0.3 + j * 0.002, v0),
                                          (0.3 + j * 0.002, v0 + L / 2), (0.3 + i * 0.002, v0 + L / 2))):
                loop[G.uv].uv = uv


def build(ctx, body, S, arm, like, mats, part):
    G = sb.Garment(part.format("shoes"), arm, body)
    m = {}
    for side in ("l", "r"):
        m[side] = build_shoe(G, body, S, side)
    ob = G.finish(ctx, like, mats["leather"])
    ob.data.materials.append(mats["sole"])
    tag = ob.data.attributes.get("panel")
    if tag:
        for p in ob.data.polygons:
            p.material_index = 1 if tag.data[p.index].value == TAG["sole"] else 0
    m["marks"] = G.marks
    m.update(G.stats)
    return ob, m
