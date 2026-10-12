"""Short, dense-but-scruffy full beard as shell-textured hair (facial_hair.py).

The beard region is defined by landmarks (MPFB `lips` and `ears` groups, the
chin) as two lines in profile (y, z): a cheek line from the sideburn, dipping
under the cheekbone, to just above the mouth corner, and a neckline from
under the ear to just under the chin. Each body vertex gets a signed depth
into that region (plus a low-frequency wobble, so the lines are irregular).
The base patch is every skin face deeper than -margin: the band outside the
lines is where the density map fades the beard into stubble and bare skin.
The vermilion (`lips` group) is left out of the patch; the moustache and the
hair under the lower lip grow from its very edge and lean over it, so there
is no bare ring around the mouth.

Fields on the patch drive the shells: hair length (short on the cheeks and
moustache, longer along the jaw, longest at the chin), density (one inside,
fading through the band), stubble length factor in the band, and a comb
direction (down the cheeks, down and forward at the chin, sideways from the
philtrum on the moustache, back toward the throat under the jaw). The patch
is decimated before the shells are stacked, so the N shells cost
N x base_tris. The shells keep the skin weights of the faces they came from
(head and neck_01), so the beard deforms with the face.
"""

import math
import random

from mathutils import Vector
from mathutils.kdtree import KDTree

from . import facial_hair, hair_mesh


def _line_dist(p, pts, below):
    """Signed distance (m) from p to a polyline in profile (y, z): positive on
    the 'below' side if below else on the 'above' side."""
    y, z = p.y, p.z
    if y <= pts[0][0]:
        seg = (pts[0], pts[1])
    elif y >= pts[-1][0]:
        seg = (pts[-2], pts[-1])
    else:
        seg = next((a, c) for a, c in zip(pts, pts[1:]) if a[0] <= y <= c[0])
    (y0, z0), (y1, z1) = seg
    # Normal of the segment pointing to -z (below).
    ny, nz = (z1 - z0), -(y1 - y0)
    if nz > 0:
        ny, nz = -ny, -nz
    n = math.hypot(ny, nz)
    d = ((y - y0) * ny + (z - z0) * nz) / n
    return d if below else -d


def landmarks(frame, cfg):
    ear_y = frame.ears_min.y
    lips_y = frame.lips_min.y
    corner = (lips_y + 0.022, frame.lips_max.z + cfg["moustache_m"])
    side = (ear_y + cfg["sideburn_back_m"], frame.ear_z + cfg["sideburn_up_m"])
    # Cheek line dips under the cheekbone between the sideburn and the mouth.
    mid = ((side[0] + corner[0]) / 2,
           (side[1] + corner[1]) / 2 - cfg["cheek_dip_m"])
    # Profile y decreases toward the face front, so list points by rising y.
    cheek = sorted([corner, mid, side])
    neck = sorted([(ear_y + 0.01, frame.ear_z - cfg["jaw_drop_m"]),
                   (frame.chin_y + cfg["throat_back_m"], frame.chin_z - cfg["under_chin_m"])])
    return cheek, neck, side[0]


def inside_dist(p, w, groups, cheek, neck, back_y, margins, moustache_top, nose):
    """(signed depth into the beard, the margin band width at this point).
    The lines are in profile, so in front of the mouth corners (the
    philtrum, the nose) the beard is capped at the moustache's top edge, and
    anything above the lips and in front of them (the nose) is out."""
    lips, ears, head, neck_g = groups
    if w.get(ears, 0) > 0.2 or w.get(head, 0) + w.get(neck_g, 0) < 0.5:
        return -1.0, margins[0]
    if p.z > nose[1] and p.y < nose[0]:
        return -1.0, margins[0]
    ds = [(_line_dist(p, cheek, True), margins[0]), (_line_dist(p, neck, False), margins[1]),
          (back_y - p.y, margins[2])]
    if p.y < cheek[0][0]:
        ds.append((moustache_top - p.z, margins[3]))
    return min(ds)


def smoothstep(e0, e1, x):
    t = min(max((x - e0) / (e1 - e0), 0.0), 1.0)
    return t * t * (3 - 2 * t)


def build(b, frame, cfg):
    rng = random.Random(cfg["seed"])
    body = frame.body
    groups = tuple(body.vertex_groups[n].index for n in ("lips", "ears", "head", "neck_01"))
    cheek, neck, back_y = landmarks(frame, cfg)
    mw = body.matrix_world
    dist = {}
    # A low-frequency wobble on the distance, so the beard lines (and the
    # stubble band along them) are irregular rather than straight.
    wob, ph = cfg["line_wobble_m"], [rng.uniform(0, 6.3) for _ in range(3)]
    margins = (cfg["margin_m"], cfg["neck_margin_m"], cfg["back_margin_m"], cfg["moustache_margin_m"])
    moustache_top = frame.lips_max.z + cfg["moustache_height_m"]
    nose = (frame.lips_min.y - cfg["nose_clear_m"], frame.lips_max.z)
    margin_of = {}
    for v in body.data.vertices:
        p = mw @ v.co
        d, m = inside_dist(p, {e.group: e.weight for e in v.groups}, groups, cheek, neck,
                           back_y, margins, moustache_top, nose)
        if d > -1:
            d += wob * (math.sin(p.z * 160 + ph[0]) + math.sin(p.y * 110 + ph[1])
                        + math.sin((p.x + p.z) * 260 + ph[2])) / 3
        dist[v.index] = d
        margin_of[v.index] = m
    lips_i = groups[0]
    on_lips = set(v.index for v in body.data.vertices
                  if any(e.group == lips_i and e.weight > 0.02 for e in v.groups))
    kd = KDTree(len(on_lips))
    for i in on_lips:
        kd.insert(mw @ body.data.vertices[i].co, i)
    kd.balance()
    fade = cfg["fade_m"]
    keep = set(i for i, d in dist.items() if d > -margin_of[i] and i not in on_lips)
    obj, bm = hair_mesh.shell_from_body(b, body, keep, "Human.beard_export")
    idx = bm.verts.layers.int.get("src")
    depth = {v: dist[v[idx]] for v in bm.verts}
    vmargin = {v: margin_of[v[idx]] for v in bm.verts}
    hair_mesh.smooth_boundary(bm, frame.skin_bvh, cfg["edge_smooth_iters"])
    bm.normal_update()

    mouth_z = frame.lips_min.z
    corner_x = frame.lips_max.x
    c = frame.center
    chin = Vector((c.x, frame.chin_y, frame.chin_z))
    ln, cb = cfg["length"], cfg["comb"]
    density, short, length, comb = {}, {}, {}, {}
    down = Vector((0, 0, -1))
    for v in bm.verts:
        d, margin = depth[v], vmargin[v]
        p = v.co
        # Density: one inside the lines, fading through the band to nothing.
        x = min(max((d + margin) / (margin + fade), 0.0), 1.0)
        density[v] = x ** cfg["density_pow"]
        short[v] = cfg["stubble_short"] + (1 - cfg["stubble_short"]) * smoothstep(0, 1, x)
        lip_d = kd.find(p)[2]
        near_chin = math.exp(-((p - chin).length / ln["chin_radius_m"]) ** 2)
        below = smoothstep(mouth_z + 0.004, mouth_z - 0.02, p.z)
        moustache = p.z > mouth_z - 0.004 and abs(p.x - c.x) < corner_x - c.x + 0.012
        if moustache:
            L = ln["moustache_m"]
        else:
            L = ln["cheek_m"] + (ln["jaw_m"] - ln["cheek_m"]) * below
            L += ln["chin_extra_m"] * near_chin
            if v.normal.z < -0.35:  # under the jaw and chin
                L = min(L, ln["neck_m"] + ln["chin_extra_m"] * near_chin * 0.5)
        if lip_d is not None and lip_d < ln["lip_near_m"]:
            L *= ln["lip_scale"] + (1 - ln["lip_scale"]) * lip_d / ln["lip_near_m"]
        length[v] = L
        # Comb direction.
        side = math.copysign(1.0, p.x - c.x)
        if moustache:
            phil = min(abs(p.x - c.x) / cb["philtrum_x_m"], 1.0)
            g = Vector((side * phil * cb["moustache_side"], 0, 0)) + down * (cb["moustache_down"] + (1 - phil) * 0.8)
            # the lower edge of the moustache turns down over the lip
            if lip_d is not None and lip_d < 0.006:
                g = g + down * 1.0
        elif v.normal.z < -0.35:
            g = down + Vector((0, cb["under_jaw_back"], 0))
        elif p.z > mouth_z:
            g = down + Vector((0, cb["cheek_back"], 0))  # cheeks: down and back
        else:
            fwd = near_chin * cb["chin_forward"]
            g = down + Vector((0, -fwd, 0)) + Vector((side * 0.15 * (1 - near_chin), 0, 0))
        comb[v] = facial_hair.tangent(v, g.normalized())
    facial_hair.smooth_field(bm, comb, cb["smooth_iters"])
    for v in bm.verts:
        comb[v] = facial_hair.tangent(v, comb[v]) if comb[v].length > 1e-6 else Vector((0, 0, -1))
    facial_hair.smooth_field(bm, length, 1)

    fields = {"density": density, "short": short, "length_m": length, "comb": comb}
    base_tris_before = sum(len(f.verts) - 2 for f in bm.faces)
    bm, fields = facial_hair.decimate_patch(obj, bm, fields, cfg["base_tris"], frame.skin_bvh)
    base_tris = sum(len(f.verts) - 2 for f in bm.faces)

    # Cylindrical projection around the head's vertical axis into the tile:
    # u = angle from the front, v = height over the patch.
    zs = [v.co.z for v in bm.verts]
    z0, z1 = min(zs) - 0.01, max(zs) + 0.015
    pad = cfg["uv"]["pad"]
    amax = math.radians(cfg["uv"]["max_angle_deg"])

    def project(p):
        a = math.atan2(p.x - c.x, -(p.y - c.y))
        u = 0.5 + (a / amax) * (0.5 - pad)
        w = pad + (p.z - z0) / (z1 - z0) * (1 - 2 * pad)
        return (min(max(u, 0.0), 1.0), min(max(w, 0.0), 1.0))

    sh = cfg["shells"]
    nprng = __import__("numpy").random.default_rng(cfg["seed"])
    stats = facial_hair.build_shells(b, obj, bm, fields, sh, "beard", project, sh["tile"], nprng)
    b.cutouts.append("beard_export")
    r = lambda pts: [[round(x, 4) for x in pt] for pt in pts]
    stats.update({"base_tris": base_tris, "base_tris_before_decimate": base_tris_before,
                  "cheek_line_yz": r(cheek), "neckline_yz": r(neck)})
    b.notes["beard"] = stats
    return obj
