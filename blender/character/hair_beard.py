"""Short, full, slightly unkempt beard: a strand groom (the source of truth)
plus the game shells and cards baked from it.

Region. Landmarks only (MPFB `lips` and `ears` groups, the chin, the head
frame): a cheek line from the sideburn, dipping under the cheekbone, to
10 mm above the mouth corner, and a neckline from under the ear to the
throat, as two lines in profile (y, z). Every body vertex gets a signed depth
into that region (plus a low-frequency wobble, so the lines are irregular).
In front of the mouth corners the beard is capped at the moustache top, and
skin above the lips and in front of them is the nose (bare).

Fields on the skin patch (body faces, so they keep the skin weights):
  density   beard roots: 1 inside, falling to `line_density` at the line and
            to nothing a few mm outside it
  stubble   stubble roots (1-2 mm hairs): a band straddling the lines that
            carries the fade on to bare skin (cheek), and down the neck
  length    by zone: cheeks, jaw, chin, soul patch, moustache (which ends
            `lip_overlap_m` past the vermilion border), under the jaw
  comb      down and back on the cheeks, down and forward at the chin, back
            toward the throat under the jaw, down and out on the moustache
  grey      share of grey strands (higher at the chin and sideburns)

Groom (beard_groom): roots by density, grown along the comb with an exit
angle that relaxes toward the tip, a share of curly strands, clumping and
frizz in Geometry Nodes; hero-only Principled Hair curves bound to the head
and neck bones. Game (beard_bake): shells sliced from the groom, plus cards
on the jaw silhouette, chin and moustache edge.
"""

import math

import numpy as np
from mathutils import Vector
from mathutils.kdtree import KDTree

from . import beard_bake, beard_groom, facial_hair, hair_mesh


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
    corner = (lips_y + cfg["corner_back_m"], frame.lips_max.z + cfg["moustache_m"])
    side = (ear_y + cfg["sideburn_back_m"], frame.ear_z + cfg["sideburn_up_m"])
    # Cheek line dips under the cheekbone between the sideburn and the mouth.
    mid = ((side[0] + corner[0]) / 2,
           (side[1] + corner[1]) / 2 - cfg["cheek_dip_m"])
    # Profile y decreases toward the face front, so list points by rising y.
    cheek = sorted([corner, mid, side])
    neck = sorted([(ear_y + cfg["neck_back_m"], frame.ear_z - cfg["jaw_drop_m"]),
                   (frame.chin_y + cfg["throat_back_m"], frame.chin_z - cfg["under_chin_m"])])
    return cheek, neck, side[0]


def inside_dist(p, w, groups, cheek, neck, back_y, moustache_top, nose):
    """(signed depth into the beard, which line is nearest: 0 cheek, 1 neck,
    2 back, 3 moustache top). The lines are in profile, so in front of the
    mouth corners (the philtrum, the nose) the beard is capped at the
    moustache's top edge, and anything above the lips and in front of them
    (the nose) is out."""
    lips, ears, head, neck_g = groups
    if w.get(ears, 0) > 0.2 or w.get(head, 0) + w.get(neck_g, 0) < 0.5:
        return -1.0, 0
    if p.z > nose[1] and p.y < nose[0]:
        return -1.0, 0
    ds = [(_line_dist(p, cheek, True), 0), (_line_dist(p, neck, False), 1), (back_y - p.y, 2)]
    if p.y < cheek[0][0]:
        ds.append((moustache_top - p.z, 3))
    return min(ds)


def smoothstep(e0, e1, x):
    t = min(max((x - e0) / (e1 - e0), 0.0), 1.0)
    return t * t * (3 - 2 * t)


def region(b, frame, cfg, rng):
    """Signed depth per body vertex and the patch (an object + bmesh with
    skin weights) of everything within the outer margins."""
    body = frame.body
    groups = tuple(body.vertex_groups[n].index for n in ("lips", "ears", "head", "neck_01"))
    cheek, neck, back_y = landmarks(frame, cfg)
    mw = body.matrix_world
    wob, ph = cfg["line_wobble_m"], [rng.uniform(0, 6.3) for _ in range(3)]
    margins = (cfg["margin_m"], cfg["neck_margin_m"], cfg["back_margin_m"], cfg["moustache_margin_m"])
    moustache_top = frame.lips_max.z + cfg["moustache_height_m"]
    nose = (frame.lips_min.y - cfg["nose_clear_m"], frame.lips_max.z)
    dist, which = {}, {}
    for v in body.data.vertices:
        p = mw @ v.co
        d, k = inside_dist(p, {e.group: e.weight for e in v.groups}, groups, cheek, neck,
                           back_y, moustache_top, nose)
        if d > -1:
            d += wob * (math.sin(p.z * 160 + ph[0]) + math.sin(p.y * 110 + ph[1])
                        + math.sin((p.x + p.z) * 260 + ph[2])) / 3
        dist[v.index] = d
        which[v.index] = k
    lips_i = groups[0]
    on_lips = set(v.index for v in body.data.vertices
                  if any(e.group == lips_i and e.weight > 0.02 for e in v.groups))
    keep = set(i for i, d in dist.items() if d > -margins[which[i]] and i not in on_lips)
    obj, bm = hair_mesh.shell_from_body(b, body, keep, "Human.beard_export")
    idx = bm.verts.layers.int.get("src")
    depth = {v: dist[v[idx]] for v in bm.verts}
    line = {v: which[v[idx]] for v in bm.verts}
    hair_mesh.smooth_boundary(bm, frame.skin_bvh, cfg["edge_smooth_iters"])
    bm.normal_update()
    lips_pts = [mw @ body.data.vertices[i].co for i in on_lips]
    return obj, bm, depth, line, margins, lips_pts, (cheek, neck, back_y)


def fields(bm, frame, cfg, depth, line, margins, lips_pts):
    """Per patch vertex: beard density, stubble density, length, comb, grey
    share, neck weight."""
    kd = KDTree(len(lips_pts))
    for i, p in enumerate(lips_pts):
        kd.insert(p, i)
    kd.balance()
    mouth_z = frame.lips_min.z
    upper_lip_z = frame.lips_max.z
    corner_x = frame.lips_max.x
    c = frame.center
    chin = Vector((c.x, frame.chin_y, frame.chin_z))
    soul = Vector((c.x, frame.lips_min.y + 0.006, mouth_z - 0.012))
    ln, cb, fd = cfg["length"], cfg["comb"], cfg["fade"]
    dl = bm.verts.layers.deform.verify()
    head_g = frame.body.vertex_groups["head"].index
    neck_g = frame.body.vertex_groups["neck_01"].index
    out = {k: {} for k in ("density", "stubble", "length_m", "comb", "grey", "neckw",
                           "moustache", "under", "chin")}
    down = Vector((0, 0, -1))
    for v in bm.verts:
        d, which = depth[v], line[v]
        p = v.co
        # Beard density: 1 from fade_in inside the line, line_density at the
        # line, nothing beam_out outside it (the neckline fades wider).
        fin = fd["neck_in_m"] if which == 1 else fd["in_m"]
        fout = fd["neck_out_m"] if which == 1 else fd["out_m"]
        if d >= 0:
            x = smoothstep(0, fin, d)
            dens = fd["line_density"] + (1 - fd["line_density"]) * x ** fd["pow"]
            lenf = fd["line_length"] + (1 - fd["line_length"]) * x
        else:
            dens = fd["line_density"] * smoothstep(-fout, 0, d)
            lenf = fd["line_length"]
        out["density"][v] = dens
        # Stubble: a band from just inside the line to the patch edge.
        m = margins[which]
        st = smoothstep(-m, -m * 0.35, d) * (1 - smoothstep(fd["stubble_in_m"], fd["stubble_in_m"] * 2, d))
        out["stubble"][v] = st
        lip_d = kd.find(p)[2] if lips_pts else 1.0
        near_chin = math.exp(-((p - chin).length / ln["chin_radius_m"]) ** 2)
        near_soul = math.exp(-((p - soul).length / ln["soul_radius_m"]) ** 2)
        below = smoothstep(mouth_z + 0.004, mouth_z - 0.02, p.z)
        moustache = p.z > mouth_z - 0.002 and abs(p.x - c.x) < corner_x - c.x + 0.010
        under = v.normal.z < -0.35
        if moustache:
            L = ln["moustache_m"]
            if p.z > upper_lip_z - 0.002:
                # end lip_overlap past the vermilion border: the height of
                # the root over the lip plus the overlap, along a hair that
                # runs mostly down
                L = min(L, (p.z - upper_lip_z + ln["lip_overlap_m"]) / 0.8 + 0.002)
        else:
            L = ln["cheek_m"] + (ln["jaw_m"] - ln["cheek_m"]) * below
            L += ln["chin_extra_m"] * near_chin
            L = max(L, ln["soul_m"] * near_soul + L * (1 - near_soul))
            if under:
                L = min(L, ln["neck_m"] + ln["chin_extra_m"] * near_chin * 0.6)
        out["length_m"][v] = max(L * (1.0 if moustache else lenf), 0.002)
        side = math.copysign(1.0, p.x - c.x)
        if moustache:
            phil = min(abs(p.x - c.x) / cb["philtrum_x_m"], 1.0)
            g = Vector((side * phil * cb["moustache_side"], 0, 0)) + down * cb["moustache_down"]
        elif under:
            g = down + Vector((0, cb["under_jaw_back"], 0))
        elif p.z > mouth_z:
            g = down + Vector((0, cb["cheek_back"], 0))
        else:
            fwd = near_chin * cb["chin_forward"]
            g = down + Vector((0, -fwd, 0)) + Vector((side * 0.15 * (1 - near_chin), 0, 0))
        out["comb"][v] = facial_hair.tangent(v, g.normalized())
        side_burn = smoothstep(frame.lips_min.y + 0.05, frame.ears_min.y, p.y) * smoothstep(mouth_z, frame.ear_z, p.z)
        out["grey"][v] = cfg["tone"]["grey_share"] + cfg["tone"]["grey_extra"] * max(near_chin, side_burn)
        wh = v[dl].get(head_g, 0.0)
        wn = v[dl].get(neck_g, 0.0)
        out["neckw"][v] = wn / max(wh + wn, 1e-6)
        out["moustache"][v] = 1.0 if moustache else 0.0
        out["under"][v] = 1.0 if under else 0.0
        out["chin"][v] = near_chin
    facial_hair.smooth_field(bm, out["comb"], cb["smooth_iters"])
    for v in bm.verts:
        cm = out["comb"][v]
        out["comb"][v] = facial_hair.tangent(v, cm) if cm.length > 1e-6 else Vector((0, 0, -1))
    facial_hair.smooth_field(bm, out["length_m"], 1)
    return out


def grow_beard(roots, n, f, g, rng, frame):
    """Strand points for the beard roots: per-zone exit and tip angles, a
    share of curly strands, kept off the skin."""
    m = len(roots)
    deg = math.radians
    must = f["moustache"] > 0.5
    under = f["under"] > 0.5
    e0 = np.where(must, deg(g["elev0_moustache"]), deg(g["elev0"])) + rng.normal(0, deg(g["elev_sigma"]), m)
    e1 = np.where(must, deg(g["elev1_moustache"]), np.where(under, deg(g["elev1_under"]), deg(g["elev1"])))
    e1 = e1 + rng.normal(0, deg(g["elev_sigma"]), m)
    yaw = rng.normal(0, deg(g["yaw_sigma"]), m)
    L = f["length_m"] * rng.uniform(g["len_min"], 1.0, m)
    curly = rng.random(m) < g["curl_share"]
    R = rng.uniform(*g["curl_radius_m"], m)
    curl = np.where(curly, rng.choice([-1, 1], m) * L / R, rng.normal(0, deg(g["curl_sigma"]), m))
    pts = beard_groom.grow(roots, n, f["comb"], L, e0, e1, yaw, curl, g["points"], g["bend_pow"])
    # Curly strands also roll up off the comb plane (a loose helix).
    if curly.any():
        s = np.linspace(0, 1, g["points"])
        lift = (np.sin(s * np.pi * 1.5)[None, :] * (L * g["curl_lift"])[:, None])
        pts[curly] += n[curly, None, :] * lift[curly, :, None]
    return pts, L


def build(b, frame, cfg):
    rng_py = __import__("random").Random(cfg["seed"])
    rng = np.random.default_rng(cfg["seed"])
    beard_groom.refit_for(b, frame)
    obj, bm, depth, line, margins, lips_pts, lines = region(b, frame, cfg, rng_py)
    fl = fields(bm, frame, cfg, depth, line, margins, lips_pts)
    co, nrm, tris, F = beard_groom.patch_arrays(bm, fl)
    g = cfg["groom"]
    # Beard roots.
    pos, n, f = beard_groom.sample_roots(co, nrm, tris, F, g["per_cm2"] * 1e4, rng)
    # Roots sit a little inside the skin, so no strand starts in mid-air.
    pos = pos - n * g["root_sink_m"]
    pts, L = grow_beard(pos, n, f, g, rng, frame)
    k = g["points"]
    gap = np.concatenate([[0.0], np.linspace(g["gap_m"][0], g["gap_m"][1], k - 1)])
    beard_groom.collide(pts, frame.skin_bvh, gap)
    # Stubble roots.
    sg = cfg["stubble"]
    spos, sn, sf = beard_groom.sample_roots(co, nrm, tris, F, sg["per_cm2"] * 1e4, rng, density_key="stubble")
    sm = len(spos)
    spos = spos - sn * g["root_sink_m"]
    deg = math.radians
    sL = rng.uniform(*sg["length_m"], sm)
    spts = beard_groom.grow(spos, sn, sf["comb"], sL,
                            np.full(sm, deg(sg["elev0"])) + rng.normal(0, deg(10), sm),
                            np.full(sm, deg(sg["elev1"])) + rng.normal(0, deg(8), sm),
                            rng.normal(0, deg(25), sm), rng.normal(0, deg(30), sm), sg["points"])
    sgap = np.concatenate([[0.0], np.full(sg["points"] - 1, g["gap_m"][0])])
    beard_groom.collide(spts, frame.skin_bvh, sgap)

    # Tone: per-strand melanin / redness; grey share from the field.
    tone = cfg["tone"]
    mel, red, rgb = tones(len(pos), tone, rng, f["grey"])
    smel, sred, srgb = tones(sm, tone, rng, sf["grey"])

    # Hero curves: beard and stubble, split by bone (head / neck_01).
    hero = cfg["hero"]
    mat = beard_groom.hair_material("beard_hero", hero["material"])
    rad = np.linspace(1.0, hero["tip_radius"], k)[None, :] * rng.uniform(*hero["radius_m"], len(pos))[:, None]
    srad = np.linspace(1.0, hero["tip_radius"], sg["points"])[None, :] * \
        rng.uniform(*hero["radius_m"], sm)[:, None] * sg["radius_scale"]
    clump = np.clip(g["clump_base"] + g["clump_moustache"] * f["moustache"] + g["clump_chin"] * f["chin"], 0, 1)
    frizz = np.clip(g["frizz_base"] * (L / max(L.max(), 1e-6)) * (1 - 0.6 * f["moustache"]), 0, 1)
    objs = []
    for label, P, R, attrs, nw, gn in (
            ("beard", pts, rad, {"melanin": mel, "redness": red, "clump": clump, "frizz": frizz},
             f["neckw"], hero),
            ("stubble", spts, srad, {"melanin": smel, "redness": sred,
                                     "clump": np.zeros(sm), "frizz": np.full(sm, sg["frizz"])},
             sf["neckw"], None)):
        for bone, sel in (("head", nw < 0.5), ("neck_01", nw >= 0.5)):
            if not sel.any():
                continue
            o = beard_groom.make_curves(f"beard_hero_{label}_{bone}", P[sel], R[sel],
                                        {a: v[sel] for a, v in attrs.items()}, mat)
            if gn is not None:
                beard_groom.clump_frizz(o, gn, cfg["seed"])
            objs.append((o, bone, sel, label))
    # Read the evaluated (clumped, frizzed) strands back for the game bake.
    ev_beard = np.zeros_like(pts)
    ev_stub = np.zeros_like(spts)
    for o, bone, sel, label in objs:
        (ev_beard if label == "beard" else ev_stub)[sel] = beard_groom.strands(o)
    for o, bone, sel, label in objs:
        beard_groom.bind(b, o, bone)
        b.facial_refit.add("curves", o)

    # Game: shells from the groom, cards on the silhouette.
    bake_rgb = lambda mm, rr, gr: beard_bake.linear(tone_rgb(mm, rr, gr, tone))
    h, feet, rn = beard_bake.strand_feet(ev_beard, frame.skin_bvh)
    sh_, sfeet, srn = beard_bake.strand_feet(ev_stub, frame.skin_bvh)
    gb = {"pts": ev_beard, "h": h, "feet": feet, "root_n": n, "radius": rad[:, 0],
          "rgb": bake_rgb(mel, red, rng)}
    gs = {"pts": ev_stub, "h": sh_, "feet": sfeet, "root_n": sn, "radius": srad[:, 0],
          "rgb": bake_rgb(smel, sred, rng)}
    sh = cfg["shells"]
    base_before = sum(len(fc.verts) - 2 for fc in bm.faces)
    # canopy from both grooms (before decimation, the vertex keys change)
    roots_all = np.concatenate([ev_beard[:, 0], ev_stub[:, 0]])
    top_all = np.concatenate([h.max(1), sh_.max(1)])
    bm, kept = facial_hair.decimate_patch(obj, bm, {"density": fl["density"]}, sh["base_tris"], frame.skin_bvh)
    base_tris = sum(len(fc.verts) - 2 for fc in bm.faces)
    canopy = beard_bake.canopy_field(bm, roots_all, top_all, sh["canopy_radius_m"], sh["canopy_pct"],
                                     sh["canopy_floor_m"])
    ckd = KDTree(len(bm.verts))
    bm.verts.ensure_lookup_table()
    for i, v in enumerate(bm.verts):
        ckd.insert(v.co, i)
    ckd.balance()
    cvals = [canopy[v] for v in bm.verts]
    for gr in (gb, gs):
        gr["canopy"] = np.array([cvals[ckd.find(Vector(r))[1]] for r in gr["pts"][:, 0]])

    project = spherical_projection(bm, frame, sh["uv"])
    cd = cfg["cards"]
    dl_body = bm.verts.layers.deform.verify()
    # cards take the skin weights of the nearest base vertex (copied now:
    # build_shells deletes the base faces before the cards are made)
    wcache = {i: dict(v[dl_body].items()) for i, v in enumerate(bm.verts)}

    def weights_of(root):
        return wcache[ckd.find(Vector(root))[1]]

    def extra(bmx, uv, uv2, dl):
        cand, prio, roll = card_candidates(gb, f, frame, cd)
        centres = beard_bake.pick_centres(gb["pts"][:, 0], cand, prio, cd["spacing_m"], cd["count"], rng)
        rolls = [roll[j] + rng.normal(0, math.radians(cd["roll_sigma_deg"])) for j in centres]
        return beard_bake.build_cards(bmx, uv, uv2, dl, gb, centres, rolls, weights_of, cd, "beard", rng)


    stats = beard_bake.build_shells(b, obj, bm, canopy, project, [gb, gs], sh, "beard",
                                    extra=extra if cd.get("count") else None)
    b.facial_refit.add("mesh", obj)
    b.cutouts.append("beard_export")
    r = lambda pts_: [[round(x, 4) for x in pt] for pt in pts_]
    cheek, neck, back_y = lines
    allg = np.concatenate([mel, smel])
    stats.update({
        "base_tris": base_tris, "base_tris_before_decimate": base_before,
        "strands": int(len(pos)), "stubble_strands": int(sm),
        "grey_share": round(float((allg < 0.4).mean()), 4),
        "grey_share_beard": round(float((mel < 0.4).mean()), 4),
        "length_mm": {"p10": round(float(np.percentile(L, 10)) * 1e3, 1),
                      "p50": round(float(np.percentile(L, 50)) * 1e3, 1),
                      "p90": round(float(np.percentile(L, 90)) * 1e3, 1)},
        "cheek_line_yz": r(cheek), "neckline_yz": r(neck),
        "sideburn_top_z": round(max(p[1] for p in cheek), 4),
        "hero_objects": [o.name for o, *_ in objs]})
    b.notes["beard"] = stats
    return obj


def tones(m, tone, rng, grey_share):
    mel = np.clip(tone["melanin"] + rng.normal(0, tone["sigma"], m), 0, 1)
    red = np.clip(tone["redness"] + rng.normal(0, tone["sigma"] * 0.5, m), 0, 1)
    warm = rng.random(m) < tone["warm_share"]
    mel[warm] = np.clip(tone["warm"][0] + rng.normal(0, tone["sigma"], warm.sum()), 0, 1)
    red[warm] = tone["warm"][1]
    grey = rng.random(m) < grey_share
    mel[grey] = np.clip(tone["grey"][0] + rng.normal(0, 0.05, grey.sum()), 0, 1)
    red[grey] = tone["grey"][1]
    return mel, red, None


def tone_rgb(mel, red, rng, tone):
    """sRGB display colour of a strand for the baked textures: interpolated
    between the palette's swatches by melanin, plus the per-strand value
    jitter (lognormal), so the game tones follow the hero strands."""
    sw = tone["swatches"]  # [[melanin, "#rrggbb"], ...] ascending melanin
    ms = np.array([s[0] for s in sw])
    cs = np.array([hair_mesh.hex_rgb(s[1]) for s in sw])
    out = np.stack([np.interp(mel, ms, cs[:, ch]) for ch in range(3)], axis=1)
    warm = red[:, None] - tone["redness"]
    out = out * (1 + warm * np.array([0.25, 0.0, -0.25]))
    out *= rng.lognormal(0, tone["value_sigma"], len(mel))[:, None]
    return np.clip(out, 0, 1)


def spherical_projection(bm, frame, ucfg):
    """(u, v) in a tile: azimuth and elevation seen from a point inside the
    head at ear height, so the cheeks, chin, moustache and the underside of
    the jaw all get texels (a cylinder squashes the under-jaw)."""
    c = frame.center
    o = Vector((c.x, c.y + ucfg["origin_back_m"], frame.ear_z + ucfg["origin_up_m"]))
    amax = math.radians(ucfg["max_angle_deg"])
    els = []
    for v in bm.verts:
        d = v.co - o
        els.append(math.atan2(d.z, math.hypot(d.x, d.y)))
    e0, e1 = min(els) - 0.02, max(els) + 0.02
    pad = ucfg["pad"]

    def project(p):
        d = p - o
        a = math.atan2(d.x, -d.y)
        e = math.atan2(d.z, math.hypot(d.x, d.y))
        u = 0.5 + (a / amax) * (0.5 - pad)
        w = pad + (e - e0) / (e1 - e0) * (1 - 2 * pad)
        return (min(max(u, 0.0), 1.0), min(max(w, 0.0), 1.0))
    return project


def card_candidates(gb, f, frame, cd):
    """Strands that may carry a card, a priority for each, and the card roll
    (0 lying on the skin .. pi/2 fin). Silhouette zones: the jaw edge and
    chin underside (fins, they make the profile), the moustache's lower edge
    over the lip (half rolled), the chin front."""
    pts = gb["pts"]
    L = np.linalg.norm(np.diff(pts, axis=1), axis=2).sum(1)
    rn = gb["root_n"]
    must = f["moustache"] > 0.5
    chin = f["chin"]
    # jaw edge: the normal turns from sideways to down
    jaw = (rn[:, 2] < cd["jaw_nz"][1]) & (rn[:, 2] > cd["jaw_nz"][0])
    lip_edge = must & (pts[:, 0, 2] < frame.lips_max.z + cd["moustache_edge_m"])
    long_ = L > cd["min_len_m"] * 1.2
    cand = long_ & (f["density"] > 0.6) & (jaw | lip_edge | (chin > 0.3))
    prio = np.where(lip_edge, 1.0, 0.0) + jaw * 0.8 + chin * 0.6
    roll = np.where(jaw, math.radians(cd["roll_jaw_deg"]),
                    np.where(lip_edge, math.radians(cd["roll_moustache_deg"]), math.radians(cd["roll_chin_deg"])))
    return cand, prio, roll
