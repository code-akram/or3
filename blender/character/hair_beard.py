"""Short full beard: a shell over the jaw, chin and upper lip plus short tufts
on the under-jaw for profile breakup.

The beard edge is defined by landmarks (MPFB `lips` and `ears` groups, the
chin) as lines in profile (y, z): a cheek line from the sideburn, dipping
under the cheekbone, to just above the mouth corner, and a neckline from
under the ear to about 2 cm above the Adam's apple. Each body vertex gets a
signed distance to that region; faces wholly inside become the shell, whose
boundary is then relaxed along the skin (so the edge is a smooth curve, not a
staircase of faces) and tapered into it. The shell keeps
the skin weights of the faces it covers, so it moves with the head and neck.
"""

import math
import random

from mathutils import Vector

from . import hair_mesh


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


def build(b, frame, cfg):
    rng = random.Random(cfg["seed"])
    body = frame.body
    groups = tuple(body.vertex_groups[n].index for n in ("lips", "ears", "head", "neck_01"))
    cheek, neck, back_y = landmarks(frame, cfg)
    mw = body.matrix_world
    dist = {}
    for v in body.data.vertices:
        dist[v.index] = inside_dist(mw @ v.co, {e.group: e.weight for e in v.groups},
                                    groups, cheek, neck, back_y)
    keep = set(i for i, d in dist.items() if d > 0)
    obj, bm = hair_mesh.shell_from_body(b, body, keep, "Human.beard_export")
    idx = bm.verts.layers.int.get("src")
    hair_mesh.smooth_boundary(bm, frame.skin_bvh, cfg["edge_smooth_iters"])
    chin_z = frame.lips_min.z

    def thickness(v):
        return cfg["thickness_m"] + (cfg["chin_extra_m"] if v.co.z < chin_z else 0.0)

    hair_mesh.offset_shell(bm, thickness, cfg["edge_taper"])
    shell_tris = sum(len(f.verts) - 2 for f in bm.faces)

    uv = bm.loops.layers.uv.verify()
    uv2 = bm.loops.layers.uv.new("strand")
    dl = bm.verts.layers.deform.verify()
    # Tufts on the under-jaw (normals facing down), well inside the edge:
    # short tapered spikes that break the jaw line in profile.
    cand = [v for v in bm.verts if v.normal.z < -0.35 and dist.get(v[idx], -1) > 0.008]
    cand.sort(key=lambda v: (math.atan2(v.co.x, -(v.co.y - frame.center.y)), v.co.z))
    rng.shuffle(cand)
    tris = 0
    for v in cand[:cfg["tufts"]]:
        n = v.normal.copy()
        direction = (n * 0.6 + Vector((0, -0.15, -0.6)) + Vector(
            (rng.uniform(-0.2, 0.2), rng.uniform(-0.2, 0.2), 0))).normalized()
        length = cfg["tuft_len_m"] * rng.uniform(0.6, 1.2)
        base = v.co - n * 0.002
        path = [base, base + direction * (length * 0.5), base + direction * length]
        weights = {g: w for g, w in v[dl].items()}
        tris += hair_mesh.tube(bm, uv, uv2, dl, weights, path, lambda k: n,
                               lambda t: cfg["tuft_radius_m"] * (1 - t) + 0.0004,
                               1.5, 3, (rng.random(), 0.0))
    hair_mesh.finish(b, obj, bm, hair_mesh.material("beard", cfg["color"], cfg["roughness"]))
    r = lambda pts: [[round(x, 4) for x in pt] for pt in pts]
    b.notes["beard"] = {"shell_tris": shell_tris, "tuft_tris": tris,
                        "cheek_line_yz": r(cheek), "neckline_yz": r(neck)}
    return obj
