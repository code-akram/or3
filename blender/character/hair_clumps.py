"""Long swept-back hair as clump meshes, generated from scripted guide curves.

1. Roots: a Fibonacci spread of directions from the cranium centre, ray-cast
   onto the body's MPFB `scalp` faces (so they follow head edits).
2. Guides: each root is marched in 1 cm steps by deterministic rules: comb
   back from the hairline (away from an off-centre part), slide along the
   head, then fall under gravity once behind the crown or below the ears.
   Every step is pushed out of the colliders (body + clothes) by the clump's
   half-thickness plus a gap, so nothing clips the scalp or the collar.
   A strand stops at the variant's tip height (shoulder line or collar).
3. Clumps: each guide is resampled and swept into a tapered, flattened tube
   (hair_mesh.tube). A few front-fall clumps break the helmet silhouette on
   one side of the face.
4. A scalp cap shell (the scalp faces pushed out a few mm, edge tapered into
   the skin) stops see-through between clumps.

All of it is one mesh, `hair`, skinned 100 % to the head bone. UV0.v runs
root -> tip for the runtime Kajiya-Kay tangent; UV1 = (per-clump random,
side sign). Seeded RNG: the same config builds the same mesh.
"""

import math
import random

from mathutils import Vector
from mathutils.bvhtree import BVHTree

from . import hair_mesh

DOWN = Vector((0.0, 0.0, -1.0))


def smoothstep(e0, e1, x):
    t = min(max((x - e0) / (e1 - e0), 0.0), 1.0)
    return t * t * (3 - 2 * t)


def growth_region(frame, cfg):
    """Body vertex indices the hair grows from: MPFB's `scalp` group plus the
    band it leaves bare above and behind the ears (temples, sideburn roots,
    nape), all still bound to landmarks."""
    body = frame.body
    gi = {n: body.vertex_groups[n].index for n in ("scalp", "head", "ears")}
    mw = body.matrix_world
    ext = cfg["region"]
    keep = set()
    for v in body.data.vertices:
        w = {e.group: e.weight for e in v.groups}
        if w.get(gi["scalp"], 0) >= 0.5:
            keep.add(v.index)
            continue
        if w.get(gi["head"], 0) < 0.5 or w.get(gi["ears"], 0) > 0.05:
            continue
        p = mw @ v.co
        temple = (p.y > frame.ears_min.y - ext["temple_front_m"]
                  and p.z > frame.ear_z + ext["temple_above_ear_m"])
        nape = p.y > frame.ears_max.y and p.z > frame.neck_z + ext["nape_above_neck_m"]
        if temple or nape:
            keep.add(v.index)
    return keep


def region_bvh(frame, keep):
    body = frame.body
    mw = body.matrix_world
    verts = [mw @ v.co for v in body.data.vertices]
    polys = [list(p.vertices) for p in body.data.polygons
             if all(i in keep for i in p.vertices)]
    return BVHTree.FromPolygons(verts, polys, all_triangles=False)


def fib_dirs(n):
    golden = math.pi * (3 - math.sqrt(5))
    for i in range(n):
        z = 1 - 2 * (i + 0.5) / n
        r = math.sqrt(1 - z * z)
        yield Vector((math.cos(golden * i) * r, math.sin(golden * i) * r, z))


def cast_roots(frame, bvh, n_target):
    """About n_target roots evenly spread over the scalp."""
    hits = []
    n = n_target * 2
    for _ in range(4):
        hits = []
        for d in fib_dirs(n):
            loc, nrm, _, _ = bvh.ray_cast(frame.center, d, 0.3)
            if loc is not None:
                if nrm.dot(loc - frame.center) < 0:
                    nrm = -nrm
                hits.append((loc, nrm))
        if not hits:
            raise RuntimeError("hair: no rays hit the scalp faces")
        n = max(4, round(n * n_target / len(hits)))
        if abs(len(hits) - n_target) <= 1:
            break
    return hits


def tangent(v, nrm):
    t = v - nrm * v.dot(nrm)
    return t.normalized() if t.length > 1e-6 else v.normalized()


class Strand:
    def __init__(self, root, nrm, comb, tip_z, max_len, gravity, off, front_fall=False):
        self.root, self.nrm, self.comb = root, nrm, comb.normalized()
        self.tip_z, self.max_len, self.gravity, self.off = tip_z, max_len, gravity, off
        self.front_fall = front_fall


def march(frame, s, step, turn):
    """Guide polyline for one strand (list of Vectors), root buried in the scalp."""
    d = tangent(s.comb, s.nrm)
    # Start under the skin a little upstream, so the open root ring lies
    # along the scalp instead of standing up like a fin.
    pts = [s.root - s.nrm * 0.003 - d * 0.012, s.root + s.nrm * s.off + d * 0.004]
    p = pts[-1]
    length = 0.0
    while length < s.max_len:
        w = s.gravity(p, length)
        des = (s.comb * (1 - w) + DOWN * w).normalized()
        loc, nrm, sd = frame.signed(p)
        if loc is not None and sd < s.off + 0.006 and des.dot(nrm) < 0:
            des = tangent(des, nrm)
        d = d.lerp(des, turn).normalized()
        q = p + d * step
        for _ in range(3):
            loc, nrm, sd = frame.signed(q)
            if loc is None or sd >= s.off:
                break
            q = q + nrm * (s.off - sd)
        q = p + (q - p).normalized() * step
        loc, nrm, sd = frame.signed(q)
        if loc is not None and sd < s.off:
            q = q + nrm * (s.off - sd)
        d = (q - p).normalized()
        length += (q - p).length
        pts.append(q)
        p = q
        if p.z <= s.tip_z and length > 0.05:
            break
    return pts


def build(b, frame, cfg):
    rng = random.Random(cfg["seed"])
    c = frame.center
    length = cfg["length"]
    z0, z1 = frame.neck_z, frame.shoulder_z
    tip_base = z0 + (z1 - z0) * length["f"]
    r_c, aspect = cfg["radius_m"], cfg["aspect"]
    off = r_c / aspect + cfg["gap_m"]

    scalp_keep = growth_region(frame, cfg)
    bvh = region_bvh(frame, scalp_keep)
    part_x = c.x + cfg["part_x_m"]

    def main_gravity(p, s):
        behind = smoothstep(c.y - 0.01, c.y + 0.06, p.y)
        low = smoothstep(frame.ears_min.z, frame.ears_min.z - 0.05, p.z)
        return max(behind, low) * cfg["gravity"]

    strands = []
    for root, nrm in cast_roots(frame, bvh, cfg["clumps"]):
        dx = root.x - part_x
        on_top = nrm.z > 0.5 and root.y < c.y + 0.02
        push = math.copysign(cfg["part_push"], dx) * math.exp(-abs(dx) / 0.025) if on_top else 0.0
        # Side roots sweep back and down over the top of the ear.
        drop = cfg["comb_drop"] + cfg["side_drop"] * smoothstep(0.4, 0.8, abs(nrm.x))
        comb = Vector((push + rng.uniform(-0.08, 0.08), 1.0, -drop))
        tip = tip_base + rng.uniform(-1, 1) * length["jitter_m"]
        lay = rng.uniform(0, cfg["layer_jitter_m"])
        strands.append(Strand(root, nrm, comb, tip, cfg["max_len_m"], main_gravity, off + lay))

    ff = cfg.get("front_fall")
    if ff:
        side = ff["side"]
        tip = frame.lips_max.z + ff["tip_above_lips_m"]

        def fall_gravity(p, s):
            return smoothstep(0.0, ff["fall_after_m"], s) * 0.95

        for i in range(ff["count"]):
            az = math.radians(side * (ff["az0_deg"] + ff["az_step_deg"] * i))
            el = math.radians(ff["el_deg"])
            d = Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)))
            loc, nrm, _, _ = bvh.ray_cast(c, d, 0.3)
            if loc is None:
                continue
            if nrm.dot(loc - c) < 0:
                nrm = -nrm
            comb = Vector((side * ff["comb_side"], -ff["comb_fwd"], -ff["comb_down"]))
            strands.append(Strand(loc, nrm, comb, tip + rng.uniform(-0.01, 0.01),
                                  ff["max_len_m"], fall_gravity, off + 0.004, True))

    obj, bm = hair_mesh.shell_from_body(b, frame.body, scalp_keep, "Human.hair_export")
    cap = cfg["cap"]
    hair_mesh.smooth_boundary(bm, frame.skin_bvh, cap["edge_smooth_iters"])
    hair_mesh.offset_shell(bm, lambda v: cap["offset_m"], cap["edge_taper"])
    cap_tris = sum(len(f.verts) - 2 for f in bm.faces)
    uv = bm.loops.layers.uv.verify()
    uv2 = bm.loops.layers.uv.new("strand")
    for f in bm.faces:
        for loop in f.loops:
            loop[uv].uv = (0.5, 0.0)
    dl = bm.verts.layers.deform.verify()
    weights = {obj.vertex_groups["head"].index: 1.0}

    tris = 0
    lengths = []
    tips = []
    seg = cfg["segment_m"]
    for i, s in enumerate(strands):
        guide = march(frame, s, cfg["step_m"], cfg["turn"])
        nseg = min(max(round(sum((b_ - a).length for a, b_ in zip(guide, guide[1:])) / seg),
                       cfg["min_segments"]), cfg["max_segments"])
        path, total = hair_mesh.resample(guide, nseg)
        lengths.append(total)
        tips.append(path[-1].z)
        normals, free = [], []
        for p in path:
            # Lie flat on the surface while touching it; hanging free, face
            # out from the head's vertical axis so the ribbons stack in layers.
            loc, nrm, sd = frame.signed(p)
            radial = Vector((p.x - c.x, p.y - c.y, max(p.z - c.z, 0.0))).normalized()
            touching = nrm is not None and sd < 2.5 * off
            normals.append(nrm if touching else radial)
            free.append(0.0 if touching else 1.0)
        # Hanging free, clumps fan out a little so the mass reads as a sheet.
        for _ in range(2):
            free = [free[0]] + [(x + y + z) / 3 for x, y, z in zip(free, free[1:], free[2:])] + [free[-1]]
        rc = r_c * rng.uniform(1 - cfg["radius_jitter"], 1 + cfg["radius_jitter"])
        if s.front_fall:
            rc *= ff["radius_scale"]

        def radius(t, rc=rc, k=cfg["taper_power"], free=free, n=nseg):
            widen = 1 + cfg["hang_widen"] * free[round(t * n)]
            return rc * widen * (0.55 + 0.45 * smoothstep(0.0, 0.12, t)) * (1 - t ** k) + 0.0015

        side = 1.0 if s.root.x >= c.x else -1.0
        tris += hair_mesh.tube(bm, uv, uv2, dl, weights, path, lambda k: normals[k],
                               radius, aspect, cfg["sides"], (rng.random(), side))

    hair_mesh.finish(b, obj, bm, hair_mesh.material("hair", cfg["color"], cfg["roughness"]))
    tips.sort()
    # Silhouette width at eye level (spec: <= 1.35 x the skull's width there).
    eye_z = frame.ear_z + 0.02
    band = lambda pts: [p.x for p in pts if abs(p.z - eye_z) < 0.01]
    hx = band([obj.matrix_world @ v.co for v in obj.data.vertices])
    sx = band([frame.body.matrix_world @ frame.body.data.vertices[i].co for i in scalp_keep]
              + [frame.body.matrix_world @ v.co for v in frame.body.data.vertices
                 if abs(v.co.y - frame.center.y) < 0.05])
    width = (max(hx) - min(hx)) if hx else 0.0
    skull = (max(sx) - min(sx)) if sx else 0.0
    b.notes["hair"] = {
        "clumps": len(strands), "front_fall": sum(1 for s in strands if s.front_fall),
        "clump_tris": tris, "cap_tris": cap_tris,
        "tip_z_target": round(tip_base, 4),
        "tip_z_p10_p50_p90": [round(tips[int(q * (len(tips) - 1))], 4) for q in (0.1, 0.5, 0.9)],
        "length_m_min_max": [round(min(lengths), 3), round(max(lengths), 3)],
        "width_eye_level_m": round(width, 4),
        "width_to_skull": round(width / skull, 3) if skull else None,
    }
    return obj
