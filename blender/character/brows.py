"""Eyebrows: a strand groom (hero) and shells + edge cards baked from it
(game), replacing MPFB's alpha-card eyebrow proxy.

The proxy is still fitted by MPFB (head.parts) because it is the best brow
landmark we have: it follows the head track's brow edits exactly. Its
vertices, snapped to the skin, give each brow a spine (centre height over x,
a linear fit per bin so the arch's slope is not counted as thickness). The
band around the spine is 8 mm tall at the head and 4 mm at the tail
(direction §2 C), straight along the brow shelf.

Groom: roots by a density map (full in the core, feathered to the band
edges, the tail thinning out), 6-9 mm hairs lying at ~80 deg to the normal.
Direction by thirds: up and out at the head, out in the middle, out and down
at the tail; hairs on the upper edge turn down and on the lower edge up, so
the two rows meet along the spine. Then GN clumping and frizz. The proxy is
dropped from the export.
"""

import math

import bpy
import numpy as np
from mathutils import Vector
from mathutils.kdtree import KDTree

from . import beard_bake, beard_groom, facial_hair, hair_beard, hair_mesh


def _spines(brow_obj, skin_bvh, center_x, bins):
    """Per side: (list of (x, y, z_centre) over x bins, x0, x1), the centre
    smoothed across neighbouring bins."""
    pts = []
    for v in brow_obj.data.vertices:
        p = brow_obj.matrix_world @ v.co
        loc, _, _, _ = skin_bvh.find_nearest(p)
        pts.append(loc if loc is not None else p)
    out = {}
    for side in (-1, 1):
        sp = [p for p in pts if (p.x - center_x) * side > 0]
        if not sp:
            continue
        x0, x1 = min(p.x for p in sp), max(p.x for p in sp)
        spine = []
        for i in range(bins):
            a, c = x0 + (x1 - x0) * i / bins, x0 + (x1 - x0) * (i + 1) / bins
            sel = [p for p in sp if a - 0.002 <= p.x <= c + 0.002]
            if len(sel) < 3:
                continue
            n = len(sel)
            mx, mz = sum(p.x for p in sel) / n, sum(p.z for p in sel) / n
            sxx = sum((p.x - mx) ** 2 for p in sel)
            k = sum((p.x - mx) * (p.z - mz) for p in sel) / sxx if sxx > 1e-12 else 0.0
            xc = (a + c) / 2
            spine.append((xc, sum(p.y for p in sel) / n, mz + k * (xc - mx)))
        sm = []
        for i, s in enumerate(spine):
            nb = spine[max(i - 1, 0):i + 2]
            sm.append((s[0], s[1], sum(q[2] for q in nb) / len(nb)))
        out[side] = (sm, x0, x1)
    return out


def _sample(spine, x):
    """(y, z_centre) at x, linear along the spine."""
    if x <= spine[0][0]:
        return spine[0][1:]
    if x >= spine[-1][0]:
        return spine[-1][1:]
    for a, c in zip(spine, spine[1:]):
        if a[0] <= x <= c[0]:
            t = (x - a[0]) / max(c[0] - a[0], 1e-6)
            return tuple(a[k] + (c[k] - a[k]) * t for k in (1, 2))
    return spine[-1][1:]


smoothstep = hair_beard.smoothstep


def build(b, frame, cfg):
    proxy = next((o for o in b.meshes() if cfg["proxy"] in o.name), None)
    if proxy is None:
        return None
    rng = np.random.default_rng(cfg["seed"])
    beard_groom.refit_for(b, frame)
    body = frame.body
    cx = frame.center.x
    spines = _spines(proxy, frame.skin_bvh, cx, cfg["bins"])
    mw = body.matrix_world
    head_i = body.vertex_groups["head"].index
    margin = cfg["margin_m"]
    info = {}  # body vertex index -> (side, dz_norm, along, hh)
    for v in body.data.vertices:
        if not any(e.group == head_i and e.weight > 0.5 for e in v.groups):
            continue
        p = mw @ v.co
        side = -1 if p.x < cx else 1
        if side not in spines:
            continue
        spine, x0, x1 = spines[side]
        ext = cfg["end_extend_m"]
        if not (x0 - ext <= p.x <= x1 + ext):
            continue
        y, zc = _sample(spine, p.x)
        inner, outer = (x1, x0) if side < 0 else (x0, x1)
        along = min(max((p.x - inner) / (outer - inner), 0.0), 1.0)
        hh = cfg["half_height_m"][0] + (cfg["half_height_m"][1] - cfg["half_height_m"][0]) * along
        zc = zc + cfg["centre_up_m"]
        # the patch reaches select_m past the feather (the body is coarse
        # here: whole faces must be inside); the density map shapes the band
        if abs(p.y - y) > cfg["depth_tol_m"] or abs(p.z - zc) > hh + margin + cfg["select_m"]:
            continue
        info[v.index] = (side, (p.z - zc) / hh, along, hh)
    obj, bm = hair_mesh.shell_from_body(b, body, set(info), "Human.brows_export")
    idx = bm.verts.layers.int.get("src")
    hair_mesh.smooth_boundary(bm, frame.skin_bvh, 3)
    bm.normal_update()
    fl = {k: {} for k in ("density", "length_m", "comb", "along", "dz", "side")}
    d3 = cfg["thirds"]
    for v in bm.verts:
        side, dz, along, hh = info[v[idx]]
        edge = 1 - smoothstep(cfg["core"], 1 + margin / hh, abs(dz))
        tail = 1 - smoothstep(cfg["tail_start"], 1.0, along) * cfg["tail_thin"]
        head = 0.45 + 0.55 * smoothstep(0.0, cfg["head_feather"], along)
        fl["density"][v] = max(min(edge * tail * head, 1.0), 0.0)
        fl["length_m"][v] = float(np.interp(along, [0, 0.35, 0.7, 1.0], cfg["length_m"]))
        # Direction by thirds, blended: up+out, out, out+down.
        w_in = 1 - smoothstep(0.2, 0.45, along)
        w_tail = smoothstep(0.55, 0.85, along)
        up = d3["inner_up"] * w_in + d3["mid_up"] * (1 - w_in) * (1 - w_tail) + d3["tail_up"] * w_tail
        out_ = d3["inner_out"] * w_in + 1.0 * (1 - w_in)
        up -= dz * cfg["edge_turn"] * (1 - 0.6 * w_in)
        fl["comb"][v] = facial_hair.tangent(v, Vector((side * out_, 0, up)).normalized())
        fl["along"][v] = along
        fl["dz"][v] = dz
        fl["side"][v] = float(side)
    facial_hair.smooth_field(bm, fl["comb"], cfg["smooth_iters"])
    for v in bm.verts:
        c = fl["comb"][v]
        fl["comb"][v] = facial_hair.tangent(v, c) if c.length > 1e-6 else Vector((fl["side"][v], 0, 0))

    # Groom.
    g = cfg["groom"]
    co, nrm, tris, F = beard_groom.patch_arrays(bm, fl)
    pos, n, f = beard_groom.sample_roots(co, nrm, tris, F, g["per_cm2"] * 1e4, rng)
    pos = pos - n * g["root_sink_m"]
    m = len(pos)
    deg = math.radians
    L = f["length_m"] * rng.uniform(g["len_min"], 1.0, m)
    e0 = np.full(m, deg(g["elev0"])) + rng.normal(0, deg(g["elev_sigma"]), m)
    e1 = np.full(m, deg(g["elev1"])) + rng.normal(0, deg(g["elev_sigma"]) * 0.5, m)
    yaw = rng.normal(0, deg(g["yaw_sigma"]), m)
    curl = rng.normal(0, deg(g["curl_sigma"]), m)
    k = g["points"]
    pts = beard_groom.grow(pos, n, f["comb"], L, e0, e1, yaw, curl, k)
    gap = np.concatenate([[0.0], np.linspace(g["gap_m"][0], g["gap_m"][1], k - 1)])
    beard_groom.collide(pts, frame.skin_bvh, gap)
    tone = cfg["tone"]
    mel = np.clip(tone["melanin"] + rng.normal(0, tone["sigma"], m), 0, 1)
    red = np.clip(tone["redness"] + rng.normal(0, tone["sigma"] * 0.5, m), 0, 1)
    hero = cfg["hero"]
    rad = np.linspace(1.0, hero["tip_radius"], k)[None, :] * rng.uniform(*hero["radius_m"], m)[:, None]
    mat = beard_groom.hair_material("brows_hero", hero["material"])
    o = beard_groom.make_curves("brows_hero", pts, rad,
                                {"melanin": mel, "redness": red,
                                 "clump": np.full(m, g["clump"]), "frizz": np.full(m, g["frizz"])}, mat)
    beard_groom.clump_frizz(o, hero, cfg["seed"])
    ev = beard_groom.strands(o)
    beard_groom.bind(b, o, "head")
    b.facial_refit.add("curves", o)

    # Game: shells (planar projection) + edge cards.
    h, feet, rn = beard_bake.strand_feet(ev, frame.skin_bvh)
    rgb = beard_bake.linear(hair_beard.tone_rgb(mel, red, rng, tone))
    gr = {"pts": ev, "h": h, "feet": feet, "root_n": n, "radius": rad[:, 0], "rgb": rgb}
    sh = cfg["shells"]
    base_before = sum(len(fc.verts) - 2 for fc in bm.faces)
    bm, _ = facial_hair.decimate_patch(obj, bm, {"density": fl["density"]}, sh["base_tris"], frame.skin_bvh)
    base_tris = sum(len(fc.verts) - 2 for fc in bm.faces)
    canopy = beard_bake.canopy_field(bm, ev[:, 0], h.max(1), sh["canopy_radius_m"], sh["canopy_pct"],
                                     sh["canopy_floor_m"])
    bm.verts.ensure_lookup_table()
    ckd = KDTree(len(bm.verts))
    for i, v in enumerate(bm.verts):
        ckd.insert(v.co, i)
    ckd.balance()
    cvals = [canopy[v] for v in bm.verts]
    gr["canopy"] = np.array([cvals[ckd.find(Vector(r))[1]] for r in ev[:, 0]])
    dl_body = bm.verts.layers.deform.verify()
    wcache = {i: dict(v[dl_body].items()) for i, v in enumerate(bm.verts)}
    xs = [v.co.x for v in bm.verts]
    zs = [v.co.z for v in bm.verts]
    pad = 0.03
    x0, x1, z0, z1 = min(xs) - 0.006, max(xs) + 0.006, min(zs) - 0.006, max(zs) + 0.008

    def project(p):
        u = pad + (p.x - x0) / (x1 - x0) * (1 - 2 * pad)
        w = pad + (p.z - z0) / (z1 - z0) * (1 - 2 * pad)
        return (min(max(u, 0.0), 1.0), min(max(w, 0.0), 1.0))

    cd = cfg["cards"]

    def extra(bmx, uv, uv2, dl):
        along, dz = f["along"], f["dz"]
        long_ = np.linalg.norm(np.diff(ev, axis=1), axis=2).sum(1) > cd["min_len_m"]
        cand = long_ & ((np.abs(dz) > cd["edge_dz"]) | (along > cd["tail_from"])) & (f["density"] > 0.3)
        prio = np.abs(dz) + along * 0.5
        centres = []
        for s in (-1.0, 1.0):
            centres += beard_bake.pick_centres(ev[:, 0], cand & (f["side"] * s > 0), prio,
                                               cd["spacing_m"], cd["per_side"], rng)
        rolls = [math.radians(cd["roll_deg"]) + rng.normal(0, math.radians(cd["roll_sigma_deg"]))
                 for _ in centres]
        return beard_bake.build_cards(bmx, uv, uv2, dl, gr, centres, rolls,
                                      lambda r: wcache[ckd.find(Vector(r))[1]], cd, "brows", rng)

    stats = beard_bake.build_shells(b, obj, bm, canopy, project, [gr], sh, "brows", extra=extra)
    b.facial_refit.add("mesh", obj)
    b.cutouts.append("brows_export")
    # Drop the MPFB proxy: the groom and its bake replace it.
    b.export_objs.remove(proxy)
    bpy.data.objects.remove(proxy, do_unlink=True)
    stats.update({"base_tris": base_tris, "base_tris_before_decimate": base_before,
                  "proxy_dropped": cfg["proxy"], "strands": int(m),
                  "strands_per_side": {str(int(s)): int((f["side"] * s > 0).sum()) for s in (-1, 1)},
                  "length_mm_p50": round(float(np.median(L)) * 1e3, 1),
                  "spine_bins": {str(s): len(sp[0]) for s, sp in spines.items()}})
    b.notes["brows"] = stats
    return obj
