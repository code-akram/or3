"""Short full beard: a textured shell over the jaw, chin and upper lip, plus
hundreds of small alpha-card tufts over it (denser and longer at the chin)
for depth and a broken silhouette.

The beard edge is defined by landmarks (MPFB `lips` and `ears` groups, the
chin) as lines in profile (y, z): a cheek line from the sideburn, dipping
under the cheekbone, to just above the mouth corner, and a neckline from
under the ear to about 2 cm above the Adam's apple. Each body vertex gets a
signed distance to that region. The shell is every face inside the lines plus
a margin band outside them; its boundary is relaxed along the skin. A
generated strand texture (UV0 v = depth into the beard) is alpha-tested, so
in the margin band the beard ends in ragged strands of different lengths
instead of an outline. Thickness grows from the cheeks to the chin. The
shell keeps the skin weights of the faces it covers, so it moves with the
head and neck.
"""

import math
import random

from mathutils import Vector
from mathutils.kdtree import KDTree

from . import hair_mesh
from .hair_frame import world_bvh


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


def inside_dist(p, w, groups, cheek, neck, back_y):
    lips, ears, head, neck_g = groups
    if w.get(ears, 0) > 0.2 or w.get(head, 0) + w.get(neck_g, 0) < 0.5:
        return -1.0
    d = min(_line_dist(p, cheek, True), _line_dist(p, neck, False), back_y - p.y)
    if w.get(lips, 0) > 0.05:
        d = min(d, -0.002 - 0.01 * w[lips])
    return d


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
    # feather band along them) are irregular rather than straight.
    wob, ph = cfg["line_wobble_m"], [rng.uniform(0, 6.3) for _ in range(3)]
    for v in body.data.vertices:
        p = mw @ v.co
        d = inside_dist(p, {e.group: e.weight for e in v.groups}, groups, cheek, neck, back_y)
        if d > -1:
            d += wob * (math.sin(p.z * 160 + ph[0]) + math.sin(p.y * 110 + ph[1])
                        + math.sin((p.x + p.z) * 260 + ph[2])) / 3
        dist[v.index] = d
    lips_i = body.vertex_groups["lips"].index
    on_lips = set(v.index for v in body.data.vertices
                  if any(e.group == lips_i and e.weight > 0.02 for e in v.groups))
    kd = KDTree(len(on_lips))
    for i in on_lips:
        kd.insert(mw @ body.data.vertices[i].co, i)
    kd.balance()
    # The lip line feathers like the beard lines, over a narrower band: depth
    # is also capped by the (scaled) distance from the lips, so the moustache
    # and the hair under the lower lip thin out toward the lip instead of
    # ending at the cut-out.
    lf = cfg["lip_feather"]
    for v in body.data.vertices:
        if v.index not in on_lips and dist[v.index] > -1:
            lip_d = kd.find(mw @ v.co)[2]
            dist[v.index] = min(dist[v.index], (lip_d - lf["gap_m"]) * lf["scale"])
    # The shell reaches margin_m past the beard lines; that outer band is
    # where the strand texture's sparse stubble feathers the edge.
    margin = cfg["margin_m"]
    keep = set(i for i, d in dist.items() if d > -margin and i not in on_lips)
    obj, bm = hair_mesh.shell_from_body(b, body, keep, "Human.beard_export")
    idx = bm.verts.layers.int.get("src")
    depth = {v: dist[v[idx]] for v in bm.verts}
    hair_mesh.smooth_boundary(bm, frame.skin_bvh, cfg["edge_smooth_iters"])
    mouth_z = frame.lips_min.z
    chin = Vector((frame.center.x, frame.chin_y, frame.chin_z))
    th = cfg["thickness"]

    # Volume: thin on the cheeks and moustache, fuller on the jaw, fullest at
    # the chin; fading to nothing across the edge band.
    def thickness(v):
        below = smoothstep(mouth_z + 0.005, mouth_z - 0.025, v.co.z)
        t = th["cheek_m"] + (th["jaw_m"] - th["cheek_m"]) * below
        t += th["chin_extra_m"] * math.exp(-((v.co - chin).length / th["chin_radius_m"]) ** 2)
        # (a floor, so the stubble band never z-fights the skin)
        return max(t * smoothstep(-margin, th["fade_m"], depth[v]), th["floor_m"])

    hair_mesh.offset_shell(bm, thickness, [1.0])
    shell_tris = sum(len(f.verts) - 2 for f in bm.faces)
    for f in bm.faces:
        f.material_index = 0

    uv = bm.loops.layers.uv.verify()
    uv2 = bm.loops.layers.uv.new("strand")
    # UV0 for the "edge" strand texture: u = arc length around the head's
    # vertical axis (strands run up and down the face), v = depth into the
    # beard from the shell's outer edge.
    c = frame.center
    u_span, v_span, r_ref = (cfg["uv"][k] for k in ("u_span_m", "v_span_m", "radius_m"))
    for f in bm.faces:
        for loop in f.loops:
            p = loop.vert.co
            u = math.atan2(p.x - c.x, -(p.y - c.y)) * r_ref / u_span
            loop[uv].uv = (u, min(max((depth[loop.vert] + margin) / v_span, 0.0), 1.0))
            loop[uv2].uv = (0.0, 0.0)
    dl = bm.verts.layers.deform.verify()
    bm.normal_update()
    # Tufts over the whole beard, inside the edge: short curved spikes that
    # grow down and out of the shell, longer and denser at the chin, giving
    # the beard depth and a broken silhouette. Their UVs run from the opaque
    # part of the texture out into the ragged band, so their tips feather.
    tc = cfg["tuft"]
    # Keep tufts off the lips: none may root within lip_clear_m of a lip
    # vertex, and above the mouth (moustache) they need more depth into the
    # beard, so none root on the lip line and cross it.
    def clear_of_lips(p):
        hit = kd.find(p)
        return hit[0] is None or hit[2] > tc["lip_clear_m"]

    # Nor into the clothes: a tuft at the neckline must not cross or touch the
    # shirt collar (unsigned tests: the collar is a thin open shell).
    cloth = [o for o in frame.colliders if o is not body]
    cloth_bvh = world_bvh(cloth)
    clear = tc["cloth_clear_m"]

    def clear_of_clothes(pts):
        if any(cloth_bvh.find_nearest(p, clear)[0] is not None for p in pts):
            return False
        return not any(cloth_bvh.ray_cast(a, q - a, (q - a).length)[0] is not None
                       for a, q in zip(pts, pts[1:]))

    cand = [v for v in bm.verts if depth[v] > (tc["moustache_min_depth_m"]
                                               if v.co.z > mouth_z - 0.004 else tc["min_depth_m"])
            and clear_of_lips(v.co)
            # none under the jaw and chin: they hung down in a fringe and made
            # a short beard long; the shell's texture carries it there
            and v.normal.z > -tc["under_jaw_nz"]]
    cand.sort(key=lambda v: (round(v.co.x, 4), round(v.co.y, 4), round(v.co.z, 4)))
    weights_c = [1.0 + tc["chin_weight"] * math.exp(-((v.co - chin).length / th["chin_radius_m"]) ** 2)
                 for v in cand]
    picks = rng.choices(cand, weights=weights_c, k=tc["count"]) if cand else []
    tris = skipped = 0
    down = Vector((0, 0, -1))
    for v in picks:
        n = v.normal.copy()
        near_chin = math.exp(-((v.co - chin).length / th["chin_radius_m"]) ** 2)
        # Growth: down along the skin, out of it a little, plus jitter; on the
        # moustache, also away from the philtrum.
        g = down - n * down.dot(n)
        g = g.normalized() if g.length > 1e-3 else Vector((0, -0.4, -1)).normalized()
        lift = tc["lift"]
        if v.co.z > mouth_z:
            g = (g + Vector((math.copysign(0.6, v.co.x - c.x), 0, 0))).normalized()
            lift *= 0.5  # the moustache lies flat over the lip
        direction = (g * 0.85 + n * lift + Vector(
            (rng.gauss(0, 0.2), rng.gauss(0, 0.2), rng.gauss(0, 0.1)))).normalized()
        length = tc["len_m"] * rng.uniform(0.6, 1.2) * (1 + tc["chin_len"] * near_chin)
        # Root sunk into the shell, so a card never shows a straight root edge.
        base = v.co - n * tc["sink_m"] + Vector((rng.gauss(0, 0.002), rng.gauss(0, 0.002),
                                                 rng.gauss(0, 0.002)))
        bend = (direction + down * 0.5).normalized()
        path = [base, base + direction * (length * 0.5), base + direction * (length * 0.5) + bend * (length * 0.5)]
        if not clear_of_clothes(path + [v.co]):
            skipped += 1
            continue
        weights = {g_: w for g_, w in v[dl].items()}
        hw = tc["halfwidth_m"] * rng.uniform(0.7, 1.3)
        tris += hair_mesh.card(bm, uv, uv2, dl, weights, path, lambda k, n=n: n,
                               lambda t, hw=hw: hw * (1 - 0.3 * t), (rng.random(), 0.0),
                               curve=0.25, mat_index=1)
    mats = [hair_mesh.material("beard", cfg["texture"]["color"], cfg["roughness"],
                               hair_mesh.strand_image("beard_strands", cfg["texture"], "edge"),
                               cfg["specular"]),
            hair_mesh.material("beard_cards", cfg["texture_card"]["color"], cfg["roughness"],
                               hair_mesh.strand_image("beard_cards", cfg["texture_card"], "card"),
                               cfg["specular"], wrap=False)]
    hair_mesh.finish(b, obj, bm, mats)
    b.cutouts.append("beard_export")
    r = lambda pts: [[round(x, 4) for x in pt] for pt in pts]
    b.notes["beard"] = {"shell_tris": shell_tris, "tuft_tris": tris,
                        "tufts_skipped_clothes": skipped,
                        "cheek_line_yz": r(cheek), "neckline_yz": r(neck)}
    return obj
