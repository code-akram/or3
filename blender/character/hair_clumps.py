"""Collar-length swept-back hair as clump meshes, generated from scripted
guide curves.

1. Roots: a Fibonacci spread of directions from the cranium centre, ray-cast
   onto the body's MPFB `scalp` faces (so they follow head edits).
2. Guides: each root is marched in 1 cm steps by deterministic rules: comb
   back from the hairline (away from an off-centre part), slide along the
   head, pass *behind* the ears (ear ellipsoids), then fall under gravity
   once behind the skull. Every step is pushed out of the colliders (body +
   clothes) by the clump's half-thickness plus a gap, so nothing clips the
   scalp or the collar. A strand stops at the variant's tip height.
3. Layers, inside out:
   - a scalp cap shell (the scalp faces pushed out a few mm, edge tapered
     into the skin). Its UV v is the depth from the hairline, and it carries
     a feather texture: fine short hairs whose density ramps up over the
     first ~1.5 cm, so skin shows through gradually (no cap outline);
   - an under layer of few, wide, flattened opaque tubes (hair_mesh.tube):
     the mass, darker, mostly in shadow;
   - a top layer of many narrow, twisted, curved cards (hair_mesh.card) with
     an alpha-tested lock-atlas texture: the visible piecey locks;
   - hairline cards rooted one ring inside the cap's front edge, front-fall
     cards on both sides (asymmetric) that frame the face, and thin flyaway
     cards leaving top cards part-way down.

All of it is one mesh, `hair`, with two materials (opaque-cored tubes and
cap; alpha cards). Per-vertex colour `lock` (COLOR_0) carries per-lock value,
depth (under-layer darker) and root shading. UV0.v runs root -> tip for the
runtime Kajiya-Kay tangent; UV1 = (per-clump random, side sign). Skinning:
100 % head, then hair_springs rebinds the hanging part to spring chains.
Seeded RNG: the same config builds the same mesh.
"""

import math
import random

from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

from . import hair_mesh, hair_springs

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
    def __init__(self, root, nrm, comb, tip_z, max_len, gravity, off, layer, front_fall=0):
        self.root, self.nrm, self.comb = root, nrm, comb.normalized()
        self.tip_z, self.max_len, self.gravity, self.off = tip_z, max_len, gravity, off
        self.layer = layer  # {"radius_m", "aspect", "hang_widen", ...} of its layer
        self.front_fall = front_fall  # 0, or the side (+-1) of a front-fall card
        self.lay = 0.0  # extra lift within the layer (0 .. layer_jitter)
        self.wave = (0.0, 0.0, 0.1)  # (amplitude, phase, period_m) of the hanging wave
        self.hug = 0.0  # pull toward the skin when hanging clear of it (front falls)
        self.flare = (1e9, 0.0)  # (after_m, strength): front falls curl away from the cheek
        self.tuck = True  # steer behind the ear (False: drape over it, the ear collider only)
        self.hug_above_z = -1e9  # hug only applies above this height (main strands: the skull)
        # Volume: extra stand-off from the skull along the strand,
        # (amplitude_m, rise_m, hold_m, fall_m, keep): 0 at the root, full
        # after rise_m, held, then decaying to keep x amplitude over fall_m.
        self.lift = (0.0, 0.03, 0.03, 0.08, 0.5)

    def lift_at(self, length):
        a, rise, hold, fall, keep = self.lift
        if a <= 0.0:
            return 0.0
        up = smoothstep(0.0, rise, length)
        down = smoothstep(rise + hold, rise + hold + fall, length)
        return a * up * (1.0 - (1.0 - keep) * down)


def march(frame, s, step, turn, ear_margin, cloth_gap=0.0, tuck=0.0, tuck_z=-1e9,
          cling=0.0, hang_turn=None):
    """Guide polyline for one strand (list of Vectors), root buried in the scalp."""
    d = tangent(s.comb, s.nrm)
    # Start under the skin a little upstream, so the open root ring lies
    # along the scalp instead of standing up like a fin. The upstream point
    # is snapped to the skin first: a straight segment under a concave
    # temple came out through it as a dark wedge in profile.
    up = s.root - d * 0.006
    loc, nrm, _, _ = frame.skin_bvh.find_nearest(up)
    up = (loc - nrm * 0.003) if loc is not None else (up - s.nrm * 0.003)
    # Emerge at skin level; the stand-off grows over the next steps through
    # the collision push. Jumping straight to `off` at the root left the first
    # quad bridging the hollow temple as a dark wedge in profile.
    pts = [up, s.root + s.nrm * min(s.off, 0.001) + d * 0.004]
    p = pts[-1]
    length = 0.0
    while length < s.max_len:
        off = s.off + s.lift_at(length)
        w = s.gravity(p, length)
        des = (s.comb * (1 - w) + DOWN * w).normalized()
        if w > 0.5 and cling > 0:
            # Hanging: lean in toward the head's axis, so the lengths drop
            # close along the neck instead of belling out on the momentum
            # they had leaving the skull (the colliders keep them off).
            radial = Vector((p.x - frame.center.x, p.y - frame.center.y, 0.0))
            if radial.length > 1e-6:
                des = (des - radial.normalized() * (cling * w)).normalized()
        ear = None if (s.front_fall or not s.tuck) else frame.near_ear(p)
        if ear is not None and p.y < ear[0].y + ear[1].y + 0.004:
            # Above an ear and not yet behind it: keep going back, so the
            # strand tucks behind the ear instead of draping over it.
            des = (des + Vector((0.0, 1.0, -0.15))).normalized()
        if w > 0.3 and s.wave[0] > 0:
            # Hanging: a slow lateral wave, so the lengths are not a curtain
            # of parallel verticals (period and phase per strand).
            amp, ph, per = s.wave
            radial = Vector((p.x - frame.center.x, p.y - frame.center.y, 0.0))
            if radial.length > 1e-6:
                side_v = DOWN.cross(radial.normalized())
                des = (des + side_v * (amp * w * math.sin(ph + 2 * math.pi * length / per))).normalized()
        if tuck > 0 and not s.front_fall and p.z < tuck_z and p.y < frame.center.y:
            # Below the jaw and in front of the ear line: slide back, so the
            # side lengths hang beside the neck and the collar's side instead
            # of lying forward over the shirt collar and the lapel.
            des = (des + Vector((0.0, tuck, 0.0))).normalized()
        loc, nrm, sd = frame.signed(p, cloth_gap)
        if loc is not None and sd < off + 0.006 and des.dot(nrm) < 0:
            des = tangent(des, nrm)
        elif loc is not None and length >= s.flare[0] and s.flare[1] > 0:
            # The end of a front fall curls away from the cheek.
            des = (des + nrm * s.flare[1]).normalized()
        elif loc is not None and s.hug > 0 and sd > off + 0.003 and p.z > s.hug_above_z:
            # Front falls drape against the temple and cheek rather than
            # hanging in the air in front of the face.
            des = (des - nrm * s.hug).normalized()
        d = d.lerp(des, hang_turn if (hang_turn and w > 0.5) else turn).normalized()
        q = p + d * step
        for _ in range(3):
            loc, nrm, sd = frame.signed(q, cloth_gap)
            if loc is None or sd >= off:
                break
            q = q + nrm * (off - sd)
        q = p + (q - p).normalized() * step
        loc, nrm, sd = frame.signed(q, cloth_gap)
        if loc is not None and sd < off:
            q = q + nrm * (off - sd)
        if not s.front_fall:
            q = frame.ear_push(q, s.off + ear_margin)
        d = (q - p).normalized()
        length += (q - p).length
        pts.append(q)
        p = q
        if p.z <= s.tip_z and length > 0.05:
            break
    return pts


def cap_uvs(bm, uv, uv2, c, cap, vband=(0.0, 0.998)):
    """Cap UVs: u = arc length round the head / u_span (wraps), v = depth
    from the cap's open boundary / v_span, mapped into vband (the rows of
    the "edge" texture that carry the pattern; the image wraps in v too, so
    the band keeps the opaque core away from the open edge). The texture
    puts a feather band of fine short hairs at low v and the opaque strand
    core at high v, so the hairline is a density ramp."""
    edge = [v for v in bm.verts if v.is_boundary]
    kd = KDTree(len(edge))
    for i, v in enumerate(edge):
        kd.insert(v.co, i)
    kd.balance()
    for f in bm.faces:
        for loop in f.loops:
            p = loop.vert.co
            u = math.atan2(p.x - c.x, -(p.y - c.y)) * cap["radius_m"] / cap["u_span_m"]
            _, _, d = kd.find(p)
            loop[uv].uv = (u, vband[0] + (vband[1] - vband[0]) * min(d / cap["v_span_m"], 1.0))
            loop[uv2].uv = (0.5, 0.0)
    return kd


def build(b, frame, cfg):
    rng = random.Random(cfg["seed"])
    c = frame.center
    length = cfg["length"]
    z0, z1 = frame.neck_z, frame.shoulder_z
    tip_base = z0 + (z1 - z0) * length["f"]
    gap = cfg["gap_m"]

    scalp_keep = growth_region(frame, cfg)
    bvh = region_bvh(frame, scalp_keep)
    part_x = c.x + cfg["part_x_m"]
    ear_back_y = frame.ears_max.y + 0.004
    wv = cfg["wave"]

    def main_gravity(p, s):
        behind = smoothstep(c.y - 0.01, c.y + 0.06, p.y)
        low = smoothstep(frame.ears_min.z, frame.ears_min.z - 0.05, p.z)
        ear = frame.near_ear(p)
        if ear is not None and p.y < ear_back_y:
            behind = 0.0  # hold the sweep until the strand is behind the ear
        return max(behind, low) * cfg["gravity"]

    # Two layers from interleaved root spreads: a few wide, flat clumps that
    # hug the scalp (the mass, so no skin shows between clumps) and many
    # thinner clumps over them (the visible texture). Each layer has its own
    # width, flatness and lift off the skin.
    top = {k: cfg[k] for k in ("clumps", "radius_m", "aspect", "aspect_tip", "hang_widen",
                               "sides", "lift_m", "tip_m", "card", "curve")}
    top["shade"] = cfg["shade_top"]
    layers = [dict(cfg["under"], name="under"), dict(top, name="top")]
    vol = cfg.get("volume") or {}

    def lift_for(nrm, lay, scale=1.0):
        """Volume stand-off profile for a strand rooted with normal nrm:
        top_m on the crown, side_m on the sides and nape, more for cards
        lifted higher in the layer (so the layers stack), jittered."""
        if not vol:
            return (0.0, 0.03, 0.03, 0.08, 0.5)
        topness = smoothstep(0.3, 0.8, nrm.z)
        amp = vol["side_m"] + (vol["top_m"] - vol["side_m"]) * topness
        amp *= (1 - vol["jitter"] * rng.random()) * (1 - 0.5 * vol["layer"] + vol["layer"] * lay) * scale
        return (amp, vol["rise_m"], vol["hold_m"], vol["fall_m"], vol["keep"])

    strands = []
    for layer in layers:
        thick = 0.0 if layer.get("card") else layer["radius_m"] / layer["aspect"]
        off = thick + gap + layer["lift_m"]
        for root, nrm in cast_roots(frame, bvh, layer["clumps"]):
            dx = root.x - part_x
            on_top = nrm.z > 0.5 and root.y < c.y + 0.02
            push = math.copysign(cfg["part_push"], dx) * math.exp(-abs(dx) / cfg["part_width_m"]) if on_top else 0.0
            # Side roots sweep back and a little down over the top of the ear.
            drop = cfg["comb_drop"] + cfg["side_drop"] * smoothstep(0.4, 0.8, abs(nrm.x))
            comb = Vector((push + rng.uniform(-0.08, 0.08), 1.0, -drop))
            tip = tip_base + layer["tip_m"] + rng.uniform(-1, 1) * length["jitter_m"]
            lay = rng.uniform(0, cfg["layer_jitter_m"]) * (1.0 if layer.get("card") else 0.5)
            s = Strand(root, nrm, comb, tip, cfg["max_len_m"], main_gravity, off + lay, layer)
            s.lay = lay / max(cfg["layer_jitter_m"], 1e-6)
            s.lift = lift_for(nrm, s.lay, 1.0 if layer.get("card") else vol.get("under", 0.6))
            s.wave = (wv["amp"] * rng.uniform(0.5, 1.0), rng.uniform(0, 6.3),
                      wv["period_m"] * rng.uniform(0.8, 1.25))
            strands.append(s)

    ffs = cfg.get("front_fall") or []
    if isinstance(ffs, dict):
        ffs = [ffs]
    for ff in ffs:
        side = ff["side"]
        tip = frame.lips_max.z + ff["tip_above_lips_m"]
        fl = dict(top, name="front", radius_m=top["radius_m"] * ff["radius_scale"],
                  aspect=ff["aspect"], hang_widen=0.0, curve=ff["curve"], shade=ff["shade"],
                  segment_m=ff["segment_m"], twist=ff.get("twist", 0.0))
        off = (0.0 if fl.get("card") else fl["radius_m"] / fl["aspect"]) + gap + ff.get("clear_m", top["lift_m"] * 0.5)

        def fall_gravity(p, s, ff=ff):
            return smoothstep(0.0, ff["fall_after_m"], s) * 0.95

        for i in range(ff["count"]):
            az = math.radians(side * (ff["az0_deg"] + ff["az_step_deg"] * i))
            el = math.radians(ff["el_deg"] + rng.uniform(-3, 3))
            d = Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)))
            loc, nrm, _, _ = bvh.ray_cast(c, d, 0.3)
            if loc is None:
                continue
            if nrm.dot(loc - c) < 0:
                nrm = -nrm
            comb = Vector((side * (ff["comb_side"] + rng.uniform(-0.15, 0.15)), -ff["comb_fwd"],
                           -ff["comb_down"]))
            s = Strand(loc, nrm, comb, tip + rng.uniform(-0.015, 0.015),
                       ff["max_len_m"] * rng.uniform(0.85, 1.0), fall_gravity,
                       off + 0.0015 * i, fl, side)
            s.lay = 0.6
            s.hug = ff["hug"]
            s.flare = (ff.get("flare_after_m", 1e9) * rng.uniform(0.8, 1.2), ff.get("flare", 0.0))
            s.wave = (wv["amp"] * ff.get("wave", 0.0), rng.uniform(0, 6.3), wv["period_m"])
            strands.append(s)

    obj, bm = hair_mesh.shell_from_body(b, frame.body, scalp_keep, "Human.hair_export")
    cap = cfg["cap"]
    hair_mesh.smooth_boundary(bm, frame.skin_bvh, cap["edge_smooth_iters"])
    hair_mesh.offset_shell(bm, lambda v: cap["offset_m"], cap["edge_taper"])
    cap_tris = sum(len(f.verts) - 2 for f in bm.faces)
    uv = bm.loops.layers.uv.verify()
    uv2 = bm.loops.layers.uv.new("strand")
    col = bm.verts.layers.float_color.new("lock")
    hang_l = bm.verts.layers.float.new("hang_s")   # metres past the hang-start point
    sector_l = bm.verts.layers.int.new("sector")   # hair_springs sector id
    u_span = cfg["u_span_m"]
    def uv_band(tex):
        lo, hi = tex.get("v_band") or (0.0, 1.0)
        return (lo + 0.02, hi - 0.04) if tex.get("v_band") else (0.0, 0.998)

    edge_kd = cap_uvs(bm, uv, uv2, c, cap, uv_band(cfg["texture_cap"]))
    tube_band = uv_band(cfg["texture"])
    for f in bm.faces:
        f.material_index = 0
    for v in bm.verts:
        v[col] = (cap["shade"], cap["shade"], cap["shade"], 1.0)

    # Hairline cards: rooted a ring or two inside the cap's front boundary
    # (forehead and temples), so the cap's feather band of fine hairs lies in
    # front of them, and combed back with the rest. Their roots start narrow,
    # so the hairline is a density ramp instead of a row of card roots.
    hl = cfg.get("hairline")
    if hl:
        bm.normal_update()
        ring = hair_mesh.edge_rings(bm, hl["ring"] + 1)
        edge = [v for v in bm.verts if ring[v] == hl["ring"] and v.co.y < c.y - hl["behind_center_m"]
                and v.co.z > frame.ear_z + hl["above_ear_m"]]
        edge.sort(key=lambda v: math.atan2(v.co.x - c.x, -(v.co.y - c.y)))
        hlay = dict(top, name="hairline", radius_m=top["radius_m"] * hl["width_scale"],
                    hang_widen=0.2)
        step_n = max(1, len(edge) // max(1, hl["count"]))
        for v in edge[::step_n]:
            nrm = v.normal.copy()
            dx = v.co.x - part_x
            drop = cfg["comb_drop"] + cfg["side_drop"] * smoothstep(0.4, 0.8, abs(nrm.x))
            comb = Vector((math.copysign(cfg["part_push"], dx) * math.exp(-abs(dx) / cfg["part_width_m"])
                           + rng.uniform(-0.06, 0.06), 1.0, -drop))
            tip = tip_base + top["tip_m"] + rng.uniform(-1, 1) * length["jitter_m"]
            s = Strand(v.co.copy(), nrm, comb, tip, cfg["max_len_m"], main_gravity,
                       gap + top["lift_m"] * 0.5, hlay)
            s.lay = 0.5
            s.lift = lift_for(nrm, s.lay, vol.get("hairline", 1.0))
            s.wave = (wv["amp"] * rng.uniform(0.5, 1.0), rng.uniform(0, 6.3),
                      wv["period_m"] * rng.uniform(0.8, 1.25))
            strands.append(s)

    dl = bm.verts.layers.deform.verify()
    weights = {obj.vertex_groups["head"].index: 1.0}
    shade_cfg = cfg["shade"]
    tex_variants = cfg["texture_card"].get("variants", 1)

    def shader(layer, lay, nseg):
        """Per-vertex colour writer for one clump: per-lock value (lognormal),
        depth (lifted cards lighter, buried darker) and a dark root."""
        base = (layer["shade"] * rng.lognormvariate(0, shade_cfg["lock_sigma"])
                * (1 - shade_cfg["depth"] + shade_cfg["depth"] * lay))

        def on_vert(v, t):
            s = base * (shade_cfg["root"] + (1 - shade_cfg["root"]) * smoothstep(0.0, shade_cfg["root_v"], t))
            s = min(max(s, 0.2), 1.0)
            v[col] = (s, s, s, 1.0)
        return on_vert

    tris = 0
    lengths = []
    tips = []
    seg = cfg["segment_m"]
    counts = {}
    guides = []
    ear_margin = cfg["ear_margin_m"]
    cloth_gap = cfg.get("cloth_gap_m", 0.0)
    tuck = cfg.get("neck_tuck", 0.0)
    for s in strands:
        L = s.layer
        counts[L["name"]] = counts.get(L["name"], 0) + 1
        guide = march(frame, s, cfg["step_m"], cfg["turn"], ear_margin, cloth_gap, tuck, frame.chin_z,
                      cfg.get("cling", 0.0), cfg.get("hang_turn"))
        seg_m = L.get("segment_m", seg)
        nseg = min(max(round(sum((b_ - a).length for a, b_ in zip(guide, guide[1:])) / seg_m),
                       cfg["min_segments"]), cfg["max_segments"])
        # The first row stays at the buried start and the second at the root,
        # so the card leaves the skin within a centimetre; one 3 cm quad from
        # under the skin to the lifted root cut through the air at the hollow
        # temple of face C (a dark wedge in profile).
        path, total = hair_mesh.resample(guide[1:], max(nseg - 1, 2))
        path = [guide[0]] + path
        nseg = len(path) - 1
        total += (guide[1] - guide[0]).length
        lengths.append(total)
        tips.append(path[-1].z)
        arc = [0.0]
        for a, b_ in zip(path, path[1:]):
            arc.append(arc[-1] + (b_ - a).length)
        normals, free = [], []
        for p, a in zip(path, arc):
            # Lie flat on the surface while touching it (at its stand-off,
            # which includes the volume lift); hanging free, face out from the
            # head's vertical axis so the ribbons stack in layers.
            loc, nrm, sd = frame.signed(p, cloth_gap)
            radial = Vector((p.x - c.x, p.y - c.y, max(p.z - c.z, 0.0))).normalized()
            touching = nrm is not None and sd < s.off + s.lift_at(a) + 0.008
            normals.append(nrm if touching else radial)
            free.append(0.0 if touching else 1.0)
        # Where the strand starts to hang: clear of the colliders, or past
        # the skull (below ear level, behind the head). From there on it
        # belongs to a spring chain (hair_springs); before, to the head.
        hang_i = nseg
        sp = cfg["springs"] or {"hang_below_ear_m": 0.01, "front_hang_m": 0.02}
        for i, p in enumerate(path):
            if s.front_fall:
                hang = arc[i] >= sp["front_hang_m"]
            else:
                hang = free[i] > 0.5 or (p.z < frame.ear_z + sp["hang_below_ear_m"] and p.y > c.y)
            if hang:
                hang_i = i
                break
        hang_s = [max(arc[i] - arc[hang_i], 0.0) for i in range(nseg + 1)]
        sector = hair_springs.sector_id(frame, path[hang_i], s.front_fall)
        # Hanging free, clumps fan out a little so the mass reads as a sheet.
        for _ in range(2):
            free = [free[0]] + [(x + y + z) / 3 for x, y, z in zip(free, free[1:], free[2:])] + [free[-1]]
        rc = L["radius_m"] * rng.uniform(1 - cfg["radius_jitter"], 1 + cfg["radius_jitter"])

        def radius(t, rc=rc, k=cfg["taper_power"], free=free, n=nseg, hwid=L["hang_widen"]):
            widen = 1 + hwid * free[round(t * n)]
            # First ring (buried) near a point: a wide ring 3 mm under a
            # concave temple poked out as a solid wedge in profile.
            w0 = 0.1 + 0.9 * smoothstep(0.0, 0.5 / n, t)
            return rc * widen * (0.55 * w0 + 0.45 * smoothstep(0.0, 0.12, t)) * (1 - t ** k) + 0.001 * w0

        # Flatter toward the tip, so ends are thin blades, not rope ends.
        aspect = (lambda t, a=L["aspect"], m=L["aspect_tip"]: a * (1 + (m - 1) * t * t))
        side = 1.0 if s.root.x >= c.x else -1.0
        circ = 2 * math.pi * math.sqrt((rc ** 2 + (rc / L["aspect"]) ** 2) / 2)
        shade = shader(L, s.lay, nseg)

        def on_vert(v, t, shade=shade, hang_s=hang_s, n=nseg, sector=sector):
            shade(v, t)
            v[hang_l] = hang_s[round(t * n)]
            v[sector_l] = sector

        # The under layer is solid (opaque-core texture); everything above it
        # uses the sparse strand texture, so each clump is a bundle of
        # separate hairs with the darker mass showing between them.
        if L.get("card"):
            # Cards start narrow near the hairline (hairline cards, and top
            # cards rooted within reach of the cap's edge), so their roots
            # don't show as dark notches in the feather band.
            d_edge = edge_kd.find(s.root)[2]
            hl_w = (hl or {}).get("root_w", 0.2)
            root_w = hl_w + (0.6 - hl_w) * smoothstep(0.004, 0.025, d_edge)
            if L["name"] == "hairline":
                root_w = hl_w
            if s.front_fall:
                tw_max = L.get("twist", 0.0)
            else:
                tw_max = cfg["twist"] * (hl.get("twist_scale", 1.0) if L["name"] == "hairline" else 1.0)
            tw = rng.uniform(-1, 1) * tw_max

            def halfwidth(t, rc=rc, k=cfg["taper_power"], free=free, n=nseg, hwid=L["hang_widen"],
                          root_w=root_w, tip_w=cfg.get("tip_width", 0.3)):
                widen = 1 + hwid * free[round(t * n)]
                ss = smoothstep(0.0, 0.12, t)
                # The first row (buried) is a near-point, so the card's exit
                # from the skin is a sliver, not a wedge.
                w0 = 0.1 + 0.9 * smoothstep(0.0, 0.5 / n, t)
                return (rc * widen * (root_w * w0 + (1 - root_w) * ss)
                        * (1 - (1 - tip_w) * t ** k) + 0.0008 * (0.15 + 0.85 * ss))

            k = rng.randrange(tex_variants)
            tris += hair_mesh.card(bm, uv, uv2, dl, weights, path, lambda k: normals[k],
                                   halfwidth, (rng.random(), side), curve=L["curve"],
                                   mat_index=1,
                                   # peak twist mid-length, flat again at the
                                   # tip: twisted ends read as dark slivers
                                   # (shards) over the collar
                                   twist=lambda t, tw=tw: tw * math.sin(math.pi * t),
                                   u_range=(k / tex_variants, (k + 1) / tex_variants),
                                   on_vert=on_vert)
        else:
            # Under tubes: material 2, the "tip" texture (opaque core, strand
            # tips past core_v), so their ends feather instead of ending flat.
            tris += hair_mesh.tube(bm, uv, uv2, dl, weights, path, lambda k: normals[k],
                                   radius, aspect, L["sides"], (rng.random(), side),
                                   u0=rng.random(), u_span=circ / u_span, mat_index=2,
                                   v_map=lambda t, b=tube_band: b[0] + (b[1] - b[0]) * t,
                                   on_vert=on_vert)
        if L["name"] in ("top", "hairline"):
            guides.append((path, normals, hang_s, sector, s.lay))

    # Flyaways: thin loose strands that leave a top clump part-way down and
    # drift off the mass, so the silhouette is not a clean shell.
    fw = cfg.get("flyaways")
    fly_tris = 0
    for _ in range(fw["count"] if fw else 0):
        path, normals, hang_s, sector, lay = guides[rng.randrange(len(guides))]
        n = len(path) - 1
        i0 = rng.randint(max(1, int(n * fw["start"][0])), max(1, int(n * fw["start"][1])))
        p0 = path[i0]
        out = normals[i0].normalized()
        if out.z > fw["max_up"]:
            continue  # on the crown it would stand straight up
        drift = fw["drift_m"] * rng.uniform(0.4, 1.0)
        L = fw["length_m"] * rng.uniform(0.5, 1.0)
        pts, hs, acc, ph = [p0 - out * 0.001], [hang_s[i0]], 0.0, rng.uniform(0, 6.3)
        j = i0
        while acc < L and j < n:
            d = path[j + 1] - path[j]
            acc += d.length
            j += 1
            k = acc / L
            wave = math.sin(ph + k * 5.0) * fw["wave_m"]
            side_v = d.cross(out).normalized() if d.length > 1e-6 else Vector((1, 0, 0))
            pts.append(path[j] + out * (drift * k * k) + side_v * wave * k)
            hs.append(hang_s[j])
        if len(pts) < 3:
            continue
        nf = min(max(len(pts) - 1, 3), 8)
        fpath, _ = hair_mesh.resample(pts, nf)
        r0 = fw["radius_m"] * rng.uniform(0.7, 1.2)
        shade = shader(dict(shade=fw["shade"]), 1.0, nf)

        def on_fly(v, t, shade=shade, hs=hs, sector=sector):
            shade(v, t)
            v[hang_l] = hs[min(int(t * (len(hs) - 1) + 0.5), len(hs) - 1)]
            v[sector_l] = sector

        k = rng.randrange(tex_variants)
        fly_tris += hair_mesh.card(bm, uv, uv2, dl, weights, fpath, lambda k, o=out: o,
                                   lambda t, r0=r0: r0 * (1 - 0.5 * t), (rng.random(), 0.0),
                                   curve=0.15, v_map=lambda t: 0.3 + 0.7 * t, mat_index=1,
                                   u_range=(k / tex_variants, (k + 1) / tex_variants),
                                   on_vert=on_fly)

    springs = None
    if cfg.get("springs"):
        springs = hair_springs.bind(b, obj, bm, dl, hang_l, sector_l, cfg["springs"])
    bm.verts.layers.float.remove(hang_l)
    bm.verts.layers.int.remove(sector_l)

    mats = [hair_mesh.material("hair", cfg["texture"]["color"], cfg["roughness"],
                               hair_mesh.strand_image("hair_mass", cfg["texture_cap"], "edge"),
                               cfg["specular"], vertex_color="lock", anisotropy=cfg["anisotropy"]),
            hair_mesh.material("hair_cards", cfg["texture_card"]["color"], cfg["roughness"],
                               hair_mesh.strand_image("hair_cards", cfg["texture_card"], "card"),
                               cfg["specular"], wrap=False, vertex_color="lock",
                               anisotropy=cfg["anisotropy"]),
            hair_mesh.material("hair_under", cfg["texture"]["color"], cfg["roughness"],
                               hair_mesh.strand_image("hair_under", cfg["texture"], "tip"),
                               cfg["specular"], vertex_color="lock", anisotropy=cfg["anisotropy"])]
    hair_mesh.finish(b, obj, bm, mats)
    b.cutouts.append("hair_export")
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
        "clumps": len(strands), "per_layer": counts,
        "front_fall": sum(1 for s in strands if s.front_fall),
        "clump_tris": tris, "cap_tris": cap_tris, "flyaway_tris": fly_tris,
        "tip_z_target": round(tip_base, 4),
        "tip_z_p10_p50_p90": [round(tips[int(q * (len(tips) - 1))], 4) for q in (0.1, 0.5, 0.9)],
        "length_m_min_max": [round(min(lengths), 3), round(max(lengths), 3)],
        "width_eye_level_m": round(width, 4),
        "width_to_skull": round(width / skull, 3) if skull else None,
        "springs": springs,
    }
    return obj
