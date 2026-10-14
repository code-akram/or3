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


def inside_dist(p, w, groups, cheek, neck, back_y, margins, moustache_top, nose):
    """(signed depth into the beard, the margin band width at this point).
    Kept for skin_tex.beard_depth (the skin's stubble shadow follows the
    same lines); the groom uses inside_line."""
    d, k = inside_line(p, w, groups, cheek, neck, back_y, moustache_top, nose)
    return d, margins[k]


def inside_line(p, w, groups, cheek, neck, back_y, moustache_top, nose):
    """(signed depth into the beard, which line is nearest: 0 cheek, 1 neck,
    2 back, 3 moustache top). The lines are in profile, so in front of the
    mouth corners (the philtrum, the nose) the beard is capped at the
    moustache's top edge, and anything above the lips and in front of them
    (the nose) is out."""
    lips, ears, head, neck_g = groups
    if w.get(ears, 0) > 0.2 or w.get(head, 0) + w.get(neck_g, 0) < 0.5:
        return -1.0, 0
    # nose = (y, z[, z_sill]): skin in front of y and above z is nose. The
    # optional third value lifts the test to the nose sill, so the philtrum
    # under an overhanging nose (in front of the lips) keeps its roots.
    if p.z > (nose[2] if len(nose) > 2 else nose[1]) and p.y < nose[0]:
        return -1.0, 0
    ds = [(_line_dist(p, neck, False), 1), (back_y - p.y, 2)]
    if p.y < cheek[0][0]:
        # In front of the cheek line's front end (the mouth corner) the
        # moustache top bounds the beard. The cheek line extrapolated across
        # the philtrum sat a few mm over the lip and thinned the moustache to
        # stubble wherever the lips sit lower or further forward (a reshaped
        # face).
        ds.append((moustache_top - p.z, 3))
    else:
        ds.append((_line_dist(p, cheek, True), 0))
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
    nose = (frame.lips_min.y - cfg["nose_clear_m"], frame.lips_max.z,
            frame.lips_max.z + cfg.get("philtrum_free_m", 0.0))
    dist, which = {}, {}
    for v in body.data.vertices:
        p = mw @ v.co
        d, k = inside_line(p, {e.group: e.weight for e in v.groups}, groups, cheek, neck,
                           back_y, moustache_top, nose)
        # the mouth interior (skin behind the lips, facing back or up) is out
        nrm = (mw.to_3x3() @ v.normal)
        if (abs(p.x - frame.center.x) < frame.lips_max.x - frame.center.x
                and frame.lips_min.z - 0.006 < p.z < frame.lips_max.z
                and p.y > frame.lips_min.y + cfg["mouth_depth_m"] and nrm.y > -0.2):
            d = -1.0
        if d > -1:
            # the moustache top is a short line over a ~12 mm moustache: a
            # full-strength wobble there punches holes in it
            d += wob * (cfg.get("moustache_wobble", 1.0) if k == 3 else 1.0) * (math.sin(p.z * 160 + ph[0]) + math.sin(p.y * 110 + ph[1])
                        + math.sin((p.x + p.z) * 260 + ph[2]) + 0.6 * math.sin((p.y - p.x) * 530 + ph[0])) / 3.6
        dist[v.index] = d
        which[v.index] = k
    lips_i = groups[0]
    on_lips = set(v.index for v in body.data.vertices
                  if any(e.group == lips_i and e.weight > cfg["lips_w"] for e in v.groups))
    # The lower lip's bottom band of lip-group skin, under the lip's curl and
    # facing forward again, is skin outside the painted vermilion: it takes
    # roots, or a bare strip shows between the lip and the beard.
    r3 = mw.to_3x3()
    low_band = set(i for i in on_lips
                   if (mw @ body.data.vertices[i].co).z < frame.lips_min.z + cfg["lower_lip_root_m"]
                   and (r3 @ body.data.vertices[i].normal).normalized().y < cfg.get("lower_lip_ny", -0.3))
    on_lips -= low_band
    keep = set(i for i, d in dist.items() if d > -margins[which[i]] and i not in on_lips)
    # The top band of the upper lip joins the patch with no roots, so the
    # game shells can carry the moustache hairs that hang over the lip edge.
    lip_band = set(i for i in on_lips
                   if (mw @ body.data.vertices[i].co).z > frame.lips_max.z - cfg["lip_band_m"])
    for i in lip_band:
        dist[i], which[i] = 0.02, 3
    keep |= lip_band
    obj, bm = hair_mesh.shell_from_body(b, body, keep, "Human.beard_export")
    idx = bm.verts.layers.int.get("src")
    depth = {v: dist[v[idx]] for v in bm.verts}
    line = {v: which[v[idx]] for v in bm.verts}
    bare = {v: v[idx] in lip_band for v in bm.verts}
    hair_mesh.smooth_boundary(bm, frame.skin_bvh, cfg["edge_smooth_iters"])
    bm.normal_update()
    lips_pts = [mw @ body.data.vertices[i].co for i in on_lips]
    return obj, bm, depth, line, margins, lips_pts, (cheek, neck, back_y), bare


def fields(bm, frame, cfg, depth, line, margins, lips_pts, bare):
    """Per patch vertex: beard density, stubble density, length, comb, grey
    share, neck weight."""
    mouth_z = frame.lips_min.z            # bottom of the lower lip
    slit_z = (frame.lips_min.z + frame.lips_max.z) / 2  # the mouth line
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
                           "moustache", "under", "chin", "soul", "edge", "depth", "line")}
    ct = cfg.get("cheek_thin")
    eb = cfg.get("edge", {}).get("band_m", 0.0)
    down = Vector((0, 0, -1))
    for v in bm.verts:
        d, which = depth[v], line[v]
        p = v.co
        # Beard density: 1 from fade_in inside the line, line_density at the
        # line, nothing beam_out outside it (the neckline fades wider).
        fin = fd["neck_in_m"] if which == 1 else fd["in_m"]
        if which == 3:  # the moustache is only ~12 mm tall: a shorter ramp fills it
            fin = fd.get("moustache_in_m", fin)
        fout = fd["neck_out_m"] if which == 1 else fd["out_m"]
        if which == 3:
            fout = fd.get("moustache_out_m", fout)
        if d >= 0:
            x = smoothstep(0, fin, d)
            dens = fd["line_density"] + (1 - fd["line_density"]) * x ** fd["pow"]
            lenf = fd["line_length"] + (1 - fd["line_length"]) * x
        else:
            dens = fd["line_density"] * smoothstep(-fout, 0, d)
            lenf = fd["line_length"]
        if ct and which == 0:
            # Upper cheeks: thinner and patchy for cheek_thin.full_m inside
            # the cheek line, so it grows in instead of ending in an edge.
            u = smoothstep(0, ct["full_m"], d)
            pn = 0.5 + 0.5 * (math.sin(p.x * 410 + 1.3) * math.sin(p.z * 370 + 0.4)
                              + 0.5 * math.sin((p.y + p.z) * 690 + 2.1)) / 1.5
            dens *= (ct["min"] + (1 - ct["min"]) * u) * (1 - ct["patch"] * (1 - u) * pn)
        out["density"][v] = 0.0 if bare[v] else dens
        out["depth"][v] = d
        out["line"][v] = float(which)
        # Edge band (moustache top, cheek line, neckline): 0 at the outer
        # fade, 1 band_m inside the line; the strands there are finer.
        ebv = cfg.get("edge", {}).get("moustache_band_m", eb) if which == 3 else eb
        out["edge"][v] = smoothstep(-fout, ebv, d) if ebv > 0 else 1.0
        # Stubble: a band from just inside the line to the patch edge.
        m = margins[which]
        st = smoothstep(-m, -m * 0.35, d) * (1 - smoothstep(fd["stubble_in_m"], fd["stubble_in_m"] * 2, d))
        out["stubble"][v] = 0.0 if bare[v] else st
        near_chin = math.exp(-((p - chin).length / ln["chin_radius_m"]) ** 2)
        near_soul = math.exp(-((p - soul).length / ln["soul_radius_m"]) ** 2)
        below = smoothstep(mouth_z + 0.004, mouth_z - 0.02, p.z)
        moustache = p.z > slit_z and abs(p.x - c.x) < corner_x - c.x + 0.010
        # under the jaw (not the underside of the lower lip, whose hairs
        # must grow down and out of the mentolabial fold, not back into it)
        under = v.normal.z < -0.35 and p.z < mouth_z - ln["under_below_mouth_m"]
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
        side = math.copysign(1.0, p.x - c.x)
        phil = min(abs(p.x - c.x) / cb["philtrum_x_m"], 1.0)
        if moustache:
            # shorter in the philtrum groove (the hairs there comb straight down)
            pl = ln.get("philtrum_scale", 1.0)
            L *= pl + (1 - pl) * phil
        out["length_m"][v] = max(L * (1.0 if moustache else lenf), 0.002)
        if moustache:
            g = Vector((side * phil * cb["moustache_side"], 0, 0)) + down * cb["moustache_down"]
        elif under:
            g = down + Vector((0, cb["under_jaw_back"], 0))
        elif p.z > mouth_z:
            g = down + Vector((0, cb["cheek_back"], 0))
        else:
            fwd = near_chin * cb["chin_forward"] + near_soul * cb["soul_forward"]
            g = down + Vector((0, -fwd, 0)) + Vector((side * 0.15 * (1 - near_chin), 0, 0))
        out["comb"][v] = facial_hair.tangent(v, g.normalized())
        side_burn = smoothstep(frame.lips_min.y + 0.05, frame.ears_min.y, p.y) * smoothstep(mouth_z, frame.ear_z, p.z)
        tn = cfg["tone"]
        if "grey_chin" in tn:
            # zoned: a base share (cheeks), more at the chin, at the mouth
            # corners (moustache ends) and the sideburns
            ccx = c.x + side * (corner_x - c.x)
            dc = math.hypot(p.x - ccx, p.z - (slit_z + tn["corner_up_m"]))
            # grey_pow > 2 flattens the bell, so the whole zone gets its share, not just the peak
            gp = tn.get("grey_pow", 2.0)
            near_corner = math.exp(-(dc / tn["corner_radius_m"]) ** gp) if p.y < frame.lips_min.y + 0.03 else 0.0
            nc = math.exp(-((p - chin).length / tn["chin_grey_radius_m"]) ** gp)
            base = tn["grey_share"]
            out["grey"][v] = max(base + (tn["grey_chin"] - base) * nc,
                                 base + (tn["grey_corner"] - base) * near_corner,
                                 base + (tn["grey_side"] - base) * side_burn)
        else:
            out["grey"][v] = tn["grey_share"] + tn["grey_extra"] * max(near_chin, side_burn)
        wh = v[dl].get(head_g, 0.0)
        wn = v[dl].get(neck_g, 0.0)
        out["neckw"][v] = wn / max(wh + wn, 1e-6)
        out["moustache"][v] = 1.0 if moustache else 0.0
        out["under"][v] = 1.0 if under else 0.0
        out["chin"][v] = near_chin
        out["soul"][v] = near_soul
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
    e0 = np.where(must, deg(g["elev0_moustache"]),
                  deg(g["elev0"]) + deg(g["elev_chin"]) * f["chin"] + deg(g["elev_soul"]) * f["soul"])
    e0 = e0 + rng.normal(0, deg(g["elev_sigma"]), m)
    e1 = np.where(must, deg(g["elev1_moustache"]), np.where(under, deg(g["elev1_under"]), deg(g["elev1"])))
    e1 = e1 + rng.normal(0, deg(g["elev_sigma"]), m)
    yaw = rng.normal(0, deg(g["yaw_sigma"]), m)
    # the moustache hangs: less sideways spread, so its hairs drop over the lip
    yaw = np.where(must, yaw * g.get("yaw_moustache", 1.0), yaw)
    L = f["length_m"] * rng.uniform(g["len_min"], 1.0, m)
    curly = rng.random(m) < np.where(must, g.get("curl_share_moustache", g["curl_share"]), g["curl_share"])
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
    obj, bm, depth, line, margins, lips_pts, lines, bare = region(b, frame, cfg, rng_py)
    fl = fields(bm, frame, cfg, depth, line, margins, lips_pts, bare)
    co, nrm, tris, F = beard_groom.patch_arrays(bm, fl)
    g = cfg["groom"]
    # Beard roots.
    pos, n, f = beard_groom.sample_roots(co, nrm, tris, F, g["per_cm2"] * 1e4, rng)
    # Roots sit a little inside the skin, so no strand starts in mid-air.
    pos = pos - n * g["root_sink_m"]
    ec = cfg.get("edge", {})
    if ec:
        f["length_m"] = f["length_m"] * (ec["length"] + (1 - ec["length"]) * np.clip(f["edge"], 0, 1))
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
    mel, red = tones(len(pos), tone, rng, f["grey"])
    smel, sred = tones(sm, tone, rng, sf["grey"])

    # Under-coat (hero only): short hairs lying close to the skin under the
    # main mass, so the skin shows through only at the edge bands. Own RNG,
    # so the main groom (and the game bake drawn from it) is unchanged.
    uc = cfg.get("undercoat")
    under = None
    if uc:
        urng = np.random.default_rng(cfg["seed"] + 201)
        # the under-coat stays well inside the cheek line and neckline (it
        # would turn a soft edge into a solid one); the moustache keeps it
        t_ = np.clip(F["depth"] / uc.get("in_m", 1e-6), 0, 1)
        F["udens"] = F["density"] * np.where(F["line"] > 2.5, 1.0, t_ * t_ * (3 - 2 * t_))
        upos, un, uf = beard_groom.sample_roots(co, nrm, tris, F, uc["per_cm2"] * 1e4, urng,
                                                density_key="udens")
        upos = upos - un * g["root_sink_m"]
        ue = np.clip(uf["edge"], 0, 1)
        uf["length_m"] = uf["length_m"] * urng.uniform(*uc["length"], len(upos)) * \
            ((ec["length"] + (1 - ec["length"]) * ue) if ec else 1.0)
        ug = dict(g, elev0=uc["elev0"], elev1=uc["elev1"], elev0_moustache=uc["elev0"],
                  elev1_moustache=uc["elev1"], elev_chin=0, elev_soul=0, curl_share=0.0)
        upts, _ = grow_beard(upos, un, uf, ug, urng, frame)
        beard_groom.collide(upts, frame.skin_bvh, gap)
        umel, ured = tones(len(upos), tone, urng, uf["grey"])
        urad = np.linspace(1.0, cfg["hero"]["tip_radius"], k)[None, :] * \
            urng.uniform(*cfg["hero"]["radius_m"], len(upos))[:, None] * uc["radius_scale"]
        if ec:
            urad *= (ec["radius"] + (1 - ec["radius"]) * ue)[:, None]
        under = ("under", upts, urad, {"melanin": umel, "redness": ured, "clump": np.zeros(len(upos)),
                                       "frizz": np.full(len(upos), uc["frizz"])}, uf["neckw"], None)

    # Hero curves: beard and stubble, split by bone (head / neck_01).
    hero = cfg["hero"]
    mat = beard_groom.hair_material("beard_hero", hero["material"])
    rad = np.linspace(1.0, hero["tip_radius"], k)[None, :] * rng.uniform(*hero["radius_m"], len(pos))[:, None]
    # Finer, shorter hairs in the edge band, so the line breaks up into a few
    # thin hairs instead of ending in full-weight ones.
    ec = cfg.get("edge", {})
    if ec:
        e = np.clip(f["edge"], 0, 1)
        rad *= (ec["radius"] + (1 - ec["radius"]) * e)[:, None]
    # grey hairs are coarser, so the salt-and-pepper survives distance and denoising
    rad *= np.where(mel < 0.4, tone.get("grey_radius", 1.0), 1.0)[:, None]
    srad = np.linspace(1.0, hero["tip_radius"], sg["points"])[None, :] * \
        rng.uniform(*hero["radius_m"], sm)[:, None] * sg["radius_scale"]
    clump = np.clip(g["clump_base"] + g["clump_moustache"] * f["moustache"] + g["clump_chin"] * f["chin"], 0, 1)
    if ec and "clump" in ec:
        # the edge hairs stand apart (less clumping), so the line breaks into strands
        clump = clump * (ec["clump"] + (1 - ec["clump"]) * np.clip(f["edge"], 0, 1))
    frizz = np.clip(g["frizz_base"] * (L / max(L.max(), 1e-6)) * (1 - 0.6 * f["moustache"]), 0, 1)
    objs = []
    for label, P, R, attrs, nw, gn in (
            ("beard", pts, rad, {"melanin": mel, "redness": red, "clump": clump, "frizz": frizz},
             f["neckw"], hero),
            ("stubble", spts, srad, {"melanin": smel, "redness": sred,
                                     "clump": np.zeros(sm), "frizz": np.full(sm, sg["frizz"])},
             sf["neckw"], None)) + ((under,) if under else ()):
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
        if label == "under":  # hero only, not baked
            continue
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
    gcards = cfg.get("game_cards")
    if gcards and not sh.get("enabled", True):
        # T9: cards only, over the whole groom; the skin under-layer is painted after
        # head_refine (paint_underlayer, from facial_hair_refit)
        stats = game_cards(b, frame, obj, bm, gcards, ev_beard, n, rad[:, 0], mel, red, f, rng)
        b.facial_refit.add("mesh", obj)
        b.cutouts.append("beard_export")
        obj.hide_render = True
        b.beard_underlayer = {"cfg": cfg.get("underlayer"), "beard_albedo": stats.pop("_albedo_median")}
        allg = np.concatenate([mel, smel])
        stats.update({"strands": int(len(pos)), "stubble_strands": int(sm),
                      "undercoat_strands": int(len(under[1])) if under else 0,
                      "grey_share": round(float((allg < 0.4).mean()), 4),
                      "grey_share_beard": round(float((mel < 0.4).mean()), 4),
                      "length_mm": {"p10": round(float(np.percentile(L, 10)) * 1e3, 1),
                                    "p50": round(float(np.percentile(L, 50)) * 1e3, 1),
                                    "p90": round(float(np.percentile(L, 90)) * 1e3, 1)},
                      "hero_objects": [o.name for o, *_ in objs]})
        b.notes["beard"] = stats
        return obj
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


    # The baked stubble: a texel is several times a stubble hair's width, so
    # every hair drawn would read as a bold dark speck; keep a share of them.
    keep_s = np.random.default_rng(cfg["seed"] + 101).random(len(gs["pts"])) < sh["stubble_keep"]
    gs_bake = {key: val[keep_s] for key, val in gs.items()}
    # Likewise the beard: a drawn hair is about 3x a real one's width at the
    # atlas resolution, so all of them together read as a solid dark mass.
    keep_b = np.random.default_rng(cfg["seed"] + 102).random(len(gb["pts"])) < sh["beard_keep"]
    gb_bake = {key: val[keep_b] for key, val in gb.items()}
    stats = beard_bake.build_shells(b, obj, bm, canopy, project, [gb_bake, gs_bake], sh, "beard",
                                    extra=extra if cd.get("count") else None)
    b.facial_refit.add("mesh", obj)
    b.cutouts.append("beard_export")
    # The kept .blend renders the strands (hero stage); the baked game mesh
    # stays in the GLB (the exporter ignores render visibility). Left
    # visible, its alpha shells drew over the strands as dark speckle.
    obj.hide_render = True
    r = lambda pts_: [[round(x, 4) for x in pt] for pt in pts_]
    cheek, neck, back_y = lines
    allg = np.concatenate([mel, smel])
    stats.update({
        "base_tris": base_tris, "base_tris_before_decimate": base_before,
        "strands": int(len(pos)), "stubble_strands": int(sm),
        "undercoat_strands": int(len(under[1])) if under else 0,
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


def game_cards(b, frame, obj, bm, gc, ev, rn, rad0, mel, red, f, rng):
    """The game beard as cards over the whole groom (beard_bake.build_groom_cards):
    blue-noise centres over every strand longer than min_len_m (the silhouette zones
    first: jaw fins, the moustache's lip edge, the chin), lying cards elsewhere."""
    crng = np.random.default_rng(gc["seed"])
    # T11: the bake's grey is the hero's *visible* grey, not its strand share. In the hero beard
    # a grey strand sits inside a dense dark mass that shadows and covers it; drawn on a card it
    # is a full-width light stroke (the T9 bake read as 55+, "steel wool"). So only a share of
    # the hero's grey strands stay grey in the bake: most at the chin, few on the moustache and
    # the sides (NOTES §7: greying concentrated at the chin, dark moustache and sides); the rest
    # take the dark base tone. Those left are dimmer (gain), more neutral (desat) and finer (px).
    # Own RNG, so the card centres and the rest of the bake keep their streams.
    gy = gc.get("grey")
    bmel, bred = mel.copy(), red.copy()
    grey0 = mel < 0.4
    if gy:
        grng = np.random.default_rng(gc["seed"] + 7)
        keep = gy["keep"] + (gy["keep_chin"] - gy["keep"]) * np.clip(f["chin"], 0, 1)
        keep = np.where(f["moustache"] > 0.5, gy["keep_moustache"], keep)
        drop = grey0 & (grng.random(len(mel)) >= keep)
        bmel[drop] = np.clip(gy["dark_melanin"] + grng.normal(0, 0.015, int(drop.sum())), 0, 1)
        bred[drop] = gy["dark_redness"]
    grey = bmel < 0.4
    rgb = beard_bake.strand_rgb(bmel, bred, gc["albedo"], crng)
    if gy and grey.any():
        lum = (rgb[grey] @ np.array([0.2126, 0.7152, 0.0722]))[:, None]
        rgb[grey] = (lum + (rgb[grey] - lum) * (1.0 - gy["desat"])) * gy["gain"]
    if gy and gy.get("body"):
        # the dark strands' body: Chiang at melanin 0.99 is linear ~(1e-3, 1e-4, 0), so with the grey
        # thinned the cards render near-black where the hero's dense beard reads charcoal (its multiple
        # scattering and under-coat; the engine's facial hair has no scatter lobe). A small neutral
        # floor on every strand (sRGB hex) stands in for it.
        rgb = rgb + beard_bake.linear(hair_mesh.hex_rgb(gy["body"]))[None, :]
    gb = {"pts": ev, "root_n": rn, "rgb": rgb, "radius": rad0}
    px = np.where(grey, gy["px"], 1.0) if gy else np.ones(len(mel))
    # T11: cheek-line fade: each strand's alpha in its card ramps with the groom's root density
    # (the hero thins over fade.in_m; the cards drew the thin edge strands at full alpha: a hard
    # arc), and the strand narrows with it (px_min at no density)
    ef = gc.get("edge_fade")
    if ef:
        d0, d1 = ef["density"]
        a = np.clip((f["density"] - d0) / (d1 - d0), 0, 1) ** ef["pow"]
        gb["alpha"] = ef["min"] + (1 - ef["min"]) * a
        px = px * (ef.get("px_min", 1.0) + (1 - ef.get("px_min", 1.0)) * a)
    gb["px"] = px
    L = np.linalg.norm(np.diff(ev, axis=1), axis=2).sum(1)
    zone, zprio, zroll = card_candidates(gb, f, frame, gc)
    ok = L > gc["min_len_m"]
    prio = np.where(zone, 1.0 + zprio, 0.0) + crng.random(len(L)) * 0.3
    centres = beard_bake.pick_centres(ev[:, 0], ok, prio, gc["spacing_m"], gc["count"], crng)
    sig = math.radians(gc["roll_sigma_deg"])
    rolls = [(zroll[j] if zone[j] else math.radians(gc["roll_lying_deg"])) + crng.normal(0, sig) for j in centres]
    dl = bm.verts.layers.deform.verify()
    bm.verts.ensure_lookup_table()
    kd = KDTree(len(bm.verts))
    for i, v in enumerate(bm.verts):
        kd.insert(v.co, i)
    kd.balance()
    wcache = {i: dict(v[dl].items()) for i, v in enumerate(bm.verts)}
    # T11: lip clearance: the moustache's lip-edge cards stand lip_gap_m off the skin past the root
    # row (at the 0.3 mm gap the overhang lay on the vermilion: a ragged bar along the lip)
    lip_edge = (f["moustache"] > 0.5) & (ev[:, 0, 2] < frame.lips_max.z + gc["moustache_edge_m"])
    gaps = [gc.get("lip_gap_m", gc["gap_m"]) if lip_edge[j] else gc["gap_m"] for j in centres]
    stats = beard_bake.build_groom_cards(b, obj, bm, gb, centres, rolls, lambda r: wcache[kd.find(Vector(r))[1]],
                                         gc, "beard", frame.skin_bvh, crng, gaps=gaps)
    stats["zone_cards"] = int(sum(1 for j in centres if zone[j]))
    stats["lip_edge_cards"] = int(sum(1 for j in centres if lip_edge[j]))
    stats["albedo_median_linear"] = [round(float(x), 5) for x in np.median(rgb, 0)]
    chin = f["chin"] > 0.5
    must = f["moustache"] > 0.5
    rest = ~chin & ~must

    def share(g, sel):
        return round(float(g[sel].mean()), 4) if sel.any() else None
    stats["grey_share_chin"] = share(grey0, chin)
    # T11: grey share by zone, the hero strands' and the bake's
    stats["bake_grey"] = {z: {"hero": share(grey0, sel), "bake": share(grey, sel)}
                          for z, sel in (("all", np.ones(len(mel), bool)), ("chin", chin),
                                         ("moustache", must), ("sides", rest))}
    if "alpha" in gb:
        stats["edge_fade_alpha_p10_p50"] = [round(float(np.percentile(gb["alpha"], q)), 3) for q in (10, 50)]
    # the under-layer colour: the dark strands' median (as before; the grey strands are a minority)
    stats["_albedo_median"] = np.median(rgb[~grey] if (~grey).any() else rgb, 0).tolist()
    return stats


def paint_underlayer(b, key="beard"):
    """After head_refine (facial_hair_refit): the darker under-layer of the beard (or, T9b,
    `key` "brows": the brows) painted into the game skin albedo (skin_head_albedo; the hero
    albedo is untouched, Cycles has the strands). Per head texel: the beard + stubble (brow)
    root density of the hero grooms (refitted), blurred, as a cover fraction; the albedo is
    pulled toward the beard (brow) colour by strength x cover, so the skin between and under
    the cards reads dark and the edge fades as the groom's density does."""
    ul = getattr(b, f"{key}_underlayer", None)
    if not ul or not ul.get("cfg"):
        return None
    cfg = ul["cfg"]
    import bpy
    from . import hair_groom_cards as hgc
    img = bpy.data.images.get("skin_head_albedo")
    body = next((o for o in b.meshes() if o.vertex_groups.get("scalp")), None)
    if img is None or body is None:
        return {"skipped": "no skin_head_albedo / body"}
    roots, wts = [], []
    for o in bpy.data.objects:
        if o.type != "CURVES":
            continue
        if key == "brows":
            if o.name != "brows_hero":
                continue
        elif not o.name.startswith("beard_hero_") or "_under_" in o.name:
            continue
        r = beard_groom.base_points(o)[:, 0]
        roots.append(r)
        wts.append(np.full(len(r), cfg["stubble_weight"] if "_stubble_" in o.name else 1.0))
    if not roots:
        return {"skipped": f"no {key} grooms"}
    R = np.concatenate(roots)
    Wr = np.concatenate(wts)
    kd = KDTree(len(R))
    for i, p in enumerate(R):
        kd.insert(Vector(p), i)
    kd.balance()
    me = body.data
    mw = body.matrix_world
    mat_i = next((i for i, m_ in enumerate(me.materials) if m_ and m_.name == "skin_head"), None)
    if mat_i is None:
        return {"skipped": "no skin_head material"}
    uvl = me.uv_layers.active
    rr = cfg["radius_m"]
    me.calc_loop_triangles()
    vdens = {}
    tri_uv, tri_val = [], []
    lo_corner = np.array([R[:, 0].min(), R[:, 1].min(), R[:, 2].min()]) - 2 * rr
    hi_corner = np.array([R[:, 0].max(), R[:, 1].max(), R[:, 2].max()]) + 2 * rr
    for lt in me.loop_triangles:
        if lt.material_index != mat_i:
            continue
        ps = [mw @ me.vertices[vi].co for vi in lt.vertices]
        if not any(np.all(np.array(p[:]) > lo_corner) and np.all(np.array(p[:]) < hi_corner) for p in ps):
            continue
        vals = []
        for vi, p in zip(lt.vertices, ps):
            if vi not in vdens:
                vdens[vi] = sum(Wr[i] for _, i, _ in kd.find_range(p, rr))
            vals.append(vdens[vi])
        if max(vals) <= 0:
            continue
        tri_uv.append([tuple(uvl.data[li].uv) for li in lt.loops])
        tri_val.append(vals)
    if not tri_uv:
        return {"skipped": f"no {key} texels"}
    w, h = img.size
    area = math.pi * rr * rr * 1e4          # cm^2
    full = cfg["full_per_cm2"] * area       # weighted roots in the disc for full cover
    tv = np.clip(np.array(tri_val) / full, 0, 1)[..., None]
    cov, hit = hgc._tri_raster(w, h, np.array(tri_uv), tv)
    cov = hsr_blur(cov[..., 0], cfg["blur_px"])
    a = cfg["strength"] * np.clip(cov, 0, 1) ** cfg["gamma"]
    px = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(px)
    px = px.reshape(h, w, 4)
    lin = beard_bake.linear(px[..., :3])
    col = np.array(ul["beard_albedo"] if key == "beard" else ul["albedo"]) * cfg["colour_gain"]
    if cfg.get("colour"):
        # T11: an explicit colour (sRGB hex). The strands' median is a near-black red (Chiang at
        # melanin ~0.99: linear ~(1e-3, 1e-4, 0)); a strong brow band in it reads ginger under
        # the hero rig's warm key
        col = beard_bake.linear(np.array([hair_mesh.hex_rgb(cfg["colour"])]))[0] * cfg["colour_gain"]
    out = lin * (1 - a[..., None]) + col[None, None] * a[..., None]
    px[..., :3] = hair_mesh.linear_to_srgb(out)
    img.pixels.foreach_set(px.ravel())
    img.pack()
    st = {"texels": int((a > 0.01).sum()), "max_cover": round(float(a.max()), 3), "tris": len(tri_uv),
          "roots": int(len(R)), "image": [w, h]}
    b.notes.setdefault(key, {})["underlayer"] = st
    return st


def hsr_blur(a, r):
    from . import hair_strand_raster
    return hair_strand_raster.blur(a, r)


def tones(m, tone, rng, grey_share):
    """Per-strand melanin and redness: the base near-black brown, a share of
    warm brown strands, and grey strands with probability grey_share (per
    strand, from the grey field)."""
    mel = np.clip(tone["melanin"] + rng.normal(0, tone["sigma"], m), 0, 1)
    red = np.clip(tone["redness"] + rng.normal(0, tone["sigma"] * 0.5, m), 0, 1)
    warm = rng.random(m) < tone["warm_share"]
    mel[warm] = np.clip(tone["warm"][0] + rng.normal(0, tone["sigma"], warm.sum()), 0, 1)
    red[warm] = tone["warm"][1]
    grey = rng.random(m) < grey_share
    mel[grey] = np.clip(tone["grey"][0] + rng.normal(0, 0.05, grey.sum()), 0, 1)
    red[grey] = tone["grey"][1]
    return mel, red


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
