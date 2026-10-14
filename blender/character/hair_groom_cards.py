"""Game hair cards baked from the strand groom (hair_groom), hair v4 step 4
(track T9, bench/m1/v4/t9-cards.md; fable_review §5.3-5.5).

The groom is the source of truth: the evaluated strands (48 points, after the
Geometry Nodes clump / noise / frizz / trim) give the card geometry, the
texture cells and the colour (per-strand melanin / redness / grey, the same
numbers the hero Principled Hair BSDF renders).

Layers (one mesh, two materials: `hair` the scalp cap, `hair_cards` the rest):

  cap       the scalp shell, its own unwrap (one UV island set, no seam or
            pole) and its own texture: the groom's strands projected onto it
            where they lie over the scalp, over a dark core whose alpha
            follows the groom's root density (soft hairline, no hard edge)
  under     the volume / core: wide cards per half level-1 lock, set in
            toward the skull, from 20 % of the lock on (dense cells)
  mid, top  one card per level-2 clump (inner half mid, outer half top)
  front     one lock card per front fall
  hairline  short cards along the hairline built from the edge strands'
            first few centimetres (forward-pointing single hairs)
  fly       thin strips along the groom's stray hairs

Atlas (`hair_cards`): `size` px, columns of `cell_w` px; lock and under cells
run the whole height (a 0.55 m lock at 4096 px is 0.13 mm/px along the strand),
the fly and hairline columns are split. Each cell rasterises one
representative clump of the groom in its card frame (hair_strand_raster):
per-strand colour, tip alpha gradient, flow, depth, ID, root-to-tip. Albedo
full res; aniso (flow, depth) and orm (AO, roughness, ID, root-to-tip) at half
res, written into the GLB by export.pack_hair_maps.

Card geometry: the clump's evaluated centreline (mean of its strands per
point), width from the strands' spread, 3 vertices wide with a rounded
profile; every card vertex is pushed out of the skin and suit after the
Geometry Nodes (the groom's push_out runs on the guides, before them).
COLOR_0 "lock": layer shade x per-card value. Smooth-proxy normals from a
volume blob of the groom; spring chains (hair_springs) from hang distance.

Defects of the v3 baker fixed here (fable_review §5.3): temple-bay streaks and
the empty cap texture (the cap is baked from the strands on its own unwrap),
the atan2 seam / crown pole (no cylindrical UV), the dead / empty cells (every
cell is used; stats record coverage and use per cell), push_out before GN
(card vertices pushed after), cap UV vs the smoothed boundary (the UV is the
smoothed, offset cap's own), ribbons vs THICK (hair_groom.render sets THICK on
the scene, checked in stats).
"""

import math

import bmesh
import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

from . import hair_clumps, hair_mesh, hair_springs
from . import hair_strand_raster as hsr

CARDS = {
    "atlas": {"size": [2048, 4096], "cell_w": 128, "ss": 2, "data_scale": 2,
              "lock_cells": 12, "under_cells": 2,
              # column 14: fly cells (fly_cells x 64 px wide), column 15: hairline cells
              # (hairline_cells x 1024 px tall)
              "fly_cells": 2, "hairline_cells": 4,
              "strand_px": 1.15, "strand_scale": 1.0,     # strand half-width in final px at the root
              "tip_px": 0.45, "tip_fade": 0.12, "tip_alpha": 0.15,
              "max_strands": 420, "under_max_strands": 700,
              "flow_jitter_deg": 6.0, "seed": 5},
    # Per-strand colour from the groom's melanin / redness (hair_strand_raster.chiang_color),
    # Random Color and the root-dark / tip-light gradient as the hero shader; `path` < 1
    # lightens the absorption, `gain` scales the result (both calibrated against the hero
    # strands with hair_test.py --parts parity).
    "albedo": {"radial_roughness": 0.5, "path": 0.68, "gain": 1.0, "random_color": 0.15,
               "root_dark": 0.08, "tip_light": 0.03, "value_sigma": 0.08},
    "roughness": {"base": 0.55, "jitter": 0.12},
    # baked occlusion (ORM R): density x depth only; the root darkening is the viewer's (ORM A, hair.rootAO)
    "ao": {"root": 0.0, "root_v": 0.15, "depth": 0.35},
    "segment_m": 0.024, "min_segments": 4, "max_segments": 16,
    "min_halfwidth_m": 0.0015, "width_pct": 90, "width_pad_m": 0.0015,
    "tip_width": 0.5, "curve": 0.3, "root_w": [0.3, 0.85], "root_w_m": [0.005, 0.025],
    "under": {"split": 2, "inset_m": 0.004, "width": 1.15, "max_halfwidth_m": 0.022, "start": 0.15,
              "max_segments": 14},
    "flyaways": {"count": 60, "start": 0.3, "halfwidth_m": 0.0012, "max_segments": 12},
    "front_lock": {"width_pct": 85, "pad_m": 0.0015, "inset_m": 0.0015, "max_halfwidth_m": 0.007},
    # Hairline cards: every `spacing_m` along the front hairline (and the temples), the
    # strands rooted within `radius_m` and `band_m` of the line, their first `length_m`.
    "hairline": {"spacing_m": 0.0055, "radius_m": 0.004, "band_m": 0.009, "length_m": 0.03,
                 "min_strands": 4, "segments": 4, "halfwidth_m": [0.0025, 0.0055], "lift_m": 0.0006,
                 "near_m": [0.006, 0.022], "root_dark": 0.05, "widen": 0.35},
    "ear_margin_m": 0.004, "ear_lateral_m": 0.035,
    "ear_test": "box",
    "gap_m": 0.0012,                 # card vertices kept this far off the skin / suit (after GN)
    "layer_shade": {"under": 0.7, "mid": 0.88, "top": 1.0, "front": 0.95, "fly": 0.95, "hairline": 1.0},
    "lock_sigma": 0.08,
    "top_lift": {"pct": 80, "max_m": 0.012},
    "material": {"roughness": 0.55, "specular": 0.25},
    "proxy": {"voxel_m": 0.004, "radius_m": 0.008, "every": 4},
    # Cap: unique texture on the cap's own unwrap.
    "cap": {"size": 1024, "ss": 2, "data_scale": 2, "strand_px": 0.9, "max_dist_m": 0.03,
            "strands": 24000, "core": [0.3, 0.75], "density_r_m": 0.004, "shade": 0.8,
            "skin_mm": 0.0},
}

smoothstep = hair_clumps.smoothstep


def nsmooth(e0, e1, x):
    t = np.clip((np.asarray(x, dtype=float) - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


# ---------------------------------------------------------------- strands

def evaluated_strands(g):
    """(n, m, 3) evaluated main strands (vellus excluded)."""
    ev, n, m = g["eval"], g["n"], g["m"]
    offs = ev["offs"]
    if not np.all(np.diff(offs[:n + 1]) == m):
        raise RuntimeError("hair_groom_cards: the groom modifier changed point counts")
    return ev["pos"][:n * m].reshape(n, m, 3).astype(np.float64)


def strand_tones(g, cfg):
    """Per-curve melanin / redness from the groom's curve attributes, and a per-strand
    linear colour (main | strays | vellus order)."""
    cv = g["obj"].data
    nall = len(cv.curves)

    def attr(name, default):
        a = cv.attributes.get(name)
        if a is None:
            return np.full(nall, default)
        out = np.empty(nall, dtype=np.float32)
        a.data.foreach_get("value", out)
        return out.astype(np.float64)
    sh = g["cfg"]["shader"]
    mel = attr("melanin", sh["melanin"])
    red = attr("redness", sh["redness"])
    return mel, red


def strand_colors(mel, red, ac, rng, v=None):
    """Linear RGB per strand (n, 3), or per strand and point when v (n, k) root-to-tip
    is given: Random Color, root-dark / tip-light, Chiang colour, value jitter, gain."""
    n = len(mel)
    m = mel * (1.0 + ac["random_color"] * rng.uniform(-1, 1, n))
    jit = rng.lognormal(0, ac["value_sigma"], n)
    if v is None:
        c = hsr.chiang_color(m, red, ac["radial_roughness"], ac["path"])
        return c * (ac["gain"] * jit)[:, None]
    k = v.shape[1]
    mm = np.clip(m[:, None] + ac["root_dark"] * (1 - v) - ac["tip_light"] * v, 0, 1)
    c = hsr.chiang_color(mm.ravel(), np.repeat(red, k), ac["radial_roughness"], ac["path"]).reshape(n, k, 3)
    return c * (ac["gain"] * jit)[:, None, None]


def frame_along(frame, C, cloth_gap, off):
    """Per point of centreline C: (tangent, outward normal, binormal, touching).
    The normal is the collider normal while the clump lies on the skull and
    the radial direction from the head axis once it hangs."""
    c = frame.center
    k = len(C)
    T = np.gradient(C, axis=0)
    T /= np.linalg.norm(T, axis=1, keepdims=True) + 1e-12
    Nn = np.zeros_like(C)
    touch = np.zeros(k)
    prev = None
    for i in range(k):
        p = Vector(C[i])
        loc, nrm, sd = frame.signed(p, cloth_gap)
        radial = Vector((p.x - c.x, p.y - c.y, max(p.z - c.z, 0.0))).normalized()
        t = nrm is not None and sd < off
        nv = nrm if t else radial
        nv = np.array(nv)
        nv -= T[i] * nv.dot(T[i])
        if np.linalg.norm(nv) < 1e-6:
            nv = prev if prev is not None else np.array([0, 0, 1.0])
        nv /= np.linalg.norm(nv)
        if prev is not None:
            nv = nv + prev * 0.6
            nv -= T[i] * nv.dot(T[i])
            nv /= np.linalg.norm(nv)
        Nn[i] = nv
        prev = nv
        touch[i] = 1.0 if t else 0.0
    B = np.cross(T, Nn)
    return T, Nn, B, touch


def clump_profile(frame, E, members, cloth_gap, pct, pad, hw_min, hw_max=None):
    """Centreline, frame and half-width per point for a clump's strands."""
    S = E[members]
    C = S.mean(0)
    T, Nn, B, touch = frame_along(frame, C, cloth_gap, 0.02)
    O = S - C[None]
    u = np.abs((O * B[None]).sum(2))
    hw = np.percentile(u, pct, axis=0) + pad
    hw = np.maximum(hw, hw_min)
    if hw_max is not None:
        hw = np.minimum(hw, hw_max)
    hw = np.convolve(np.pad(hw, 2, mode="edge"), np.ones(5) / 5, mode="valid")
    return {"C": C, "T": T, "N": Nn, "B": B, "touch": touch, "hw": hw, "S": S, "O": O}


# ---------------------------------------------------------------- cells

def raster_clump(prof, cols, rng, W, H, ss, acfg, max_strands=None, k_end=None, u_spread=1.0,
                 rough_cfg=None, sids=None):
    """Rasterise a clump's strands into one cell (hair_strand_raster.Cell), W x H final px.
    cols: (n, k, 3) per strand and point linear colour (n = the clump's strands)."""
    S, O, B, Nn, hw, C, T = prof["S"], prof["O"], prof["B"], prof["N"], prof["hw"], prof["C"], prof["T"]
    k = S.shape[1] if k_end is None else k_end
    idx = np.arange(len(S))
    if max_strands and len(idx) > max_strands:
        idx = rng.choice(idx, max_strands, replace=False)
    arc = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(C[:k], axis=0), axis=1))])
    vtot = max(arc[-1], 1e-6)
    dmax = np.abs((O[:, :k] * Nn[None, :k]).sum(2)).max() + 1e-6
    cell = hsr.Cell(W, H, ss)
    rc = rough_cfg or {"base": 0.55, "jitter": 0.1}
    # painter's order: back (depth -1) first
    dmean = np.array([(O[j, :k] * Nn[:k]).sum(1).mean() for j in idx])
    for j in idx[np.argsort(dmean, kind="stable")]:
        u = (O[j, :k] * B[:k]).sum(1) / hw[:k] * u_spread
        d = (O[j, :k] * Nn[:k]).sum(1) / dmax
        v = np.clip((arc + (O[j, :k] * T[:k]).sum(1)) / vtot, 0.0, 1.0)
        # the strand's own length in this cell: where it ends (cut ends sit above v = 1)
        x = (u * 0.5 + 0.5) * W
        y = v * H
        L = np.linalg.norm(np.diff(S[j, :k], axis=0), axis=1)
        s = np.concatenate([[0.0], np.cumsum(L)]) / max(L.sum(), 1e-9)
        tip = np.clip((s - (1 - acfg["tip_fade"])) / acfg["tip_fade"], 0, 1)
        rad = (acfg["strand_px"] + (acfg["tip_px"] - acfg["strand_px"]) * tip) * acfg["strand_scale"]
        alpha = 1.0 - (1.0 - acfg["tip_alpha"]) * tip
        sid = float(sids[j]) if sids is not None else float(rng.random())
        rough = rc["base"] + rc["jitter"] * (2 * sid - 1)
        col = cols[j, :k].mean(0)  # one colour per strand (the gradient is in the orm root AO)
        cell.draw(x, y, rad, alpha, v, d, col, sid, rough, math.radians(acfg["flow_jitter_deg"]))
    return cell.resolve(), cell.strands


# ---------------------------------------------------------------- cap

def cap_mesh(b, frame, ccfg, g):
    """The scalp cap: hair_clumps' shell (smoothed boundary, offset, tapered edge),
    unwrapped (angle based) as its own UV set, and the bmesh layers the cards write."""
    keep = g["keep"]
    obj, bm = hair_mesh.shell_from_body(b, frame.body, keep, "Human.hair_export")
    cap = ccfg["cap"]
    hair_mesh.smooth_boundary(bm, frame.skin_bvh, cap["edge_smooth_iters"])
    hair_mesh.offset_shell(bm, lambda v: cap["offset_m"], cap["edge_taper"])
    # unwrap the cap alone (its own object data), then carry on in bmesh
    src = bm.verts.layers.int.get("src")
    if src is not None:
        bm.verts.layers.int.remove(src)
    for f in bm.faces:
        f.material_index = 0
    for e in bm.edges:
        e.seam = False      # the body's UV seams: one island where the cap allows
    bm.to_mesh(obj.data)
    bm.free()
    me = obj.data
    if not me.uv_layers:
        me.uv_layers.new(name="UVMap")
    prev = bpy.context.view_layer.objects.active
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    with bpy.context.temp_override(active_object=obj, object=obj, selected_objects=[obj],
                                   selected_editable_objects=[obj]):
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.unwrap(method="ANGLE_BASED", margin=0.01)
        bpy.ops.object.mode_set(mode="OBJECT")
    obj.select_set(False)
    bpy.context.view_layer.objects.active = prev
    bm = bmesh.new()
    bm.from_mesh(me)
    uv = bm.loops.layers.uv.active or bm.loops.layers.uv.verify()
    uv2 = bm.loops.layers.uv.new("strand")
    col = bm.verts.layers.float_color.new("lock")
    hang_l = bm.verts.layers.float.new("hang_s")
    sector_l = bm.verts.layers.int.new("sector")
    for f in bm.faces:
        for loop in f.loops:
            loop[uv2].uv = (0.5, 0.0)
    dl = bm.verts.layers.deform.verify()
    weights = {obj.vertex_groups["head"].index: 1.0}
    return obj, bm, uv, uv2, col, hang_l, sector_l, dl, weights


def _tri_raster(W, H, uvs, vals):
    """Rasterise per-corner values (t, 3, c) over triangles with UVs (t, 3, 2) into (H, W, c)
    (barycentric, texel centres); returns (img, filled mask)."""
    c = vals.shape[2]
    out = np.zeros((H, W, c), dtype=np.float32)
    hit = np.zeros((H, W), dtype=bool)
    P = uvs * np.array([W, H])
    for t in range(len(P)):
        a, b_, c_ = P[t]
        x0, x1 = int(max(np.floor(min(a[0], b_[0], c_[0])), 0)), int(min(np.ceil(max(a[0], b_[0], c_[0])), W - 1))
        y0, y1 = int(max(np.floor(min(a[1], b_[1], c_[1])), 0)), int(min(np.ceil(max(a[1], b_[1], c_[1])), H - 1))
        if x1 < x0 or y1 < y0:
            continue
        xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        d = (b_[1] - c_[1]) * (a[0] - c_[0]) + (c_[0] - b_[0]) * (a[1] - c_[1])
        if abs(d) < 1e-12:
            continue
        l0 = ((b_[1] - c_[1]) * (xs - c_[0]) + (c_[0] - b_[0]) * (ys - c_[1])) / d
        l1 = ((c_[1] - a[1]) * (xs - c_[0]) + (a[0] - c_[0]) * (ys - c_[1])) / d
        l2 = 1 - l0 - l1
        ins = (l0 >= -1e-3) & (l1 >= -1e-3) & (l2 >= -1e-3)
        if not ins.any():
            continue
        yy, xx = (ys[ins] - 0.5).astype(int), (xs[ins] - 0.5).astype(int)
        out[yy, xx] = (l0[ins, None] * vals[t, 0] + l1[ins, None] * vals[t, 1] + l2[ins, None] * vals[t, 2])
        hit[yy, xx] = True
    return out, hit


def _dilate_fill(img, hit, iters):
    """Grow the filled texels outward (gutter fill for mips / filtering)."""
    img, hit = img.copy(), hit.copy()
    for _ in range(iters):
        acc = np.zeros_like(img)
        cnt = np.zeros(hit.shape, dtype=np.float32)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            h = np.roll(hit, (dy, dx), (0, 1))
            acc += np.roll(img, (dy, dx), (0, 1)) * h[..., None]
            cnt += h
        new = (~hit) & (cnt > 0)
        img[new] = acc[new] / cnt[new, None]
        hit = hit | new
    return img, hit


def bake_cap(frame, g, E, bm, uv, cfg, cols_main, rng, sids):
    """The cap's own texture set (hair_strand_raster.Atlas, one cell): the groom's strands
    projected onto the cap (nearest point, barycentric UV) wherever they lie over it
    (within max_dist_m, the offset along the face normal), over a dark core whose alpha
    follows the groom's root density (a soft hairline). Returns (images, stats)."""
    cc = cfg["cap"]
    size, ss = cc["size"], cc["ss"]
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    lt = bm.calc_loop_triangles()
    co = [v.co.copy() for v in bm.verts]
    tri_v = np.array([[l.vert.index for l in t] for t in lt])
    tri_uv = np.array([[tuple(l[uv].uv) for l in t] for t in lt], dtype=np.float64)
    tri_n = np.array([tuple(t[0].face.normal) for t in lt])
    bvh = BVHTree.FromPolygons(co, tri_v.tolist(), all_triangles=True)
    V = np.array([tuple(c) for c in co])

    def project(P):
        """(uv (k, 2), ok (k,)) for points P (k, 3): the run from P[0] while it lies over the cap."""
        out = np.zeros((len(P), 2))
        ok = np.zeros(len(P), dtype=bool)
        locs, idx = np.zeros((len(P), 3)), np.zeros(len(P), dtype=np.int64)
        for i, p in enumerate(P):
            loc, nrm, ti, dist = bvh.find_nearest(Vector(p), cc["max_dist_m"])
            if loc is None:
                break
            d = Vector(p) - loc
            if d.length > 1e-5 and abs(d.normalized().dot(nrm)) < 0.85:
                break  # beyond the cap's edge (oblique to the face): not over it
            locs[i], idx[i], ok[i] = tuple(loc), ti, True
        if ok.any():
            t = tri_v[idx[ok]]
            a, b_, c_ = V[t[:, 0]], V[t[:, 1]], V[t[:, 2]]
            q = locs[ok]
            v0, v1, v2 = b_ - a, c_ - a, q - a
            d00, d01, d11 = (v0 * v0).sum(1), (v0 * v1).sum(1), (v1 * v1).sum(1)
            d20, d21 = (v2 * v0).sum(1), (v2 * v1).sum(1)
            den = np.maximum(d00 * d11 - d01 * d01, 1e-18)
            w1 = (d11 * d20 - d01 * d21) / den
            w2 = (d00 * d21 - d01 * d20) / den
            w0 = 1 - w1 - w2
            T = tri_uv[idx[ok]]
            out[ok] = T[:, 0] * w0[:, None] + T[:, 1] * w1[:, None] + T[:, 2] * w2[:, None]
        return out, ok

    n, m = E.shape[:2]
    pick = rng.choice(n, min(cc["strands"], n), replace=False)
    cell = hsr.Cell(size, size, ss)
    drawn = 0
    rc = cfg["roughness"]
    for j in pick:
        P = E[j]
        uvp, ok = project(P)
        # the strand's run over the cap from its root, until it leaves it
        stop = int(np.argmin(ok)) if not ok.all() else m
        if stop < 2:
            continue
        x, y = uvp[:stop, 0] * size, uvp[:stop, 1] * size
        if np.any(np.hypot(np.diff(x), np.diff(y)) > size * 0.08):
            # a UV island seam between two points: draw up to it
            cut = int(np.argmax(np.hypot(np.diff(x), np.diff(y)) > size * 0.08)) + 1
            x, y = x[:cut], y[:cut]
            if len(x) < 2:
                continue
        k = len(x)
        v = np.linspace(0, 1, m)[:k]
        rad = np.full(k, cc["strand_px"])
        sid = float(sids[j])
        cell.draw(x, y, rad, np.ones(k), v, np.zeros(k), cols_main[j], sid,
                  rc["base"] + rc["jitter"] * (2 * sid - 1))
        drawn += 1
    r = cell.resolve()
    # root density per cap vertex -> per texel (low res, then up)
    roots = E[:, 0]
    kd = KDTree(len(roots))
    for i, p in enumerate(roots):
        kd.insert(Vector(p), i)
    kd.balance()
    rr = cc["density_r_m"]
    dens_v = np.array([len(kd.find_range(Vector(tuple(p)), rr)) for p in V], dtype=np.float64)
    ref = np.percentile(dens_v[dens_v > 0], 60) if (dens_v > 0).any() else 1.0
    dens_v = dens_v / max(ref, 1e-6)
    lo = size // 4
    dimg, hit = _tri_raster(lo, lo, tri_uv, dens_v[tri_v][..., None])
    dimg, hit = _dilate_fill(dimg, hit, 4)
    dimg = hsr.blur(dimg[..., 0], 1)
    # upsample (nearest x4 then a light blur)
    up = np.repeat(np.repeat(dimg, size // lo, 0), size // lo, 1)
    up = hsr.blur(up, 2)
    core = nsmooth(cc["core"][0], cc["core"][1], up)
    cov = np.clip(r["cov"] + core * (1 - r["cov"]), 0, 1)
    base = np.median(cols_main, axis=0) * cc["shade"]
    has = r["cov"] > 1e-3
    rgb = np.stack([r["r"], r["g"], r["b"]], -1)
    w = (r["cov"] / np.maximum(cov, 1e-6))[..., None]
    rgb = np.where(has[..., None], rgb * w + base[None, None] * (1 - w), base[None, None])
    res = dict(r, cov=cov, r=rgb[..., 0], g=rgb[..., 1], b=rgb[..., 2])
    # flow where only the core is: the flow of the nearest strands (dilated)
    flow = np.stack([r["fu"], r["fv"]], -1)
    fl, fhit = _dilate_fill(flow, has, 24)
    res["fu"], res["fv"] = fl[..., 0], fl[..., 1]
    res["v"] = np.where(has, r["v"], 0.0)
    res["sid"] = np.where(has, r["sid"], 0.5)
    res["rough"] = np.where(has, r["rough"], rc["base"])
    atl = hsr.Atlas(size, size, cc["data_scale"])
    atl.put(0, 0, res, dict(cfg["ao"], root=0.0, depth=0.0))
    atl.bleed()
    imgs = atl.images("hair_cap")
    return imgs, {"strands_drawn": drawn, "size": size, "core_px": int((core > 0.5).sum()),
                  "cov_mean": round(float(cov.mean()), 3)}


# ---------------------------------------------------------------- proxy normals

def proxy_blob(points, pcfg):
    """Smooth hair-volume mesh from groom points (Points to Volume ->
    Volume to Mesh), returned as a temporary object."""
    me = bpy.data.meshes.new("hair_proxy_pts")
    me.vertices.add(len(points))
    me.vertices.foreach_set("co", points.astype(np.float32).ravel())
    src = bpy.data.objects.new("hair_proxy_pts", me)
    bpy.context.scene.collection.objects.link(src)
    ng = bpy.data.node_groups.new("hair_proxy", "GeometryNodeTree")
    ng.is_modifier = True
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    N, L = ng.nodes, ng.links
    gi, go = N.new("NodeGroupInput"), N.new("NodeGroupOutput")
    m2p = N.new("GeometryNodeMeshToPoints")
    m2p.inputs["Radius"].default_value = pcfg["radius_m"]
    p2v = N.new("GeometryNodePointsToVolume")
    p2v.inputs["Radius"].default_value = pcfg["radius_m"]
    for k in ("Voxel Size",):
        if k in p2v.inputs:
            p2v.inputs[k].default_value = pcfg["voxel_m"]
    if hasattr(p2v, "resolution_mode"):
        p2v.resolution_mode = "VOXEL_SIZE"
    elif "Resolution Mode" in p2v.inputs:
        p2v.inputs["Resolution Mode"].default_value = "Size"
    v2m = N.new("GeometryNodeVolumeToMesh")
    smooth = N.new("GeometryNodeSetShadeSmooth")
    L.new(gi.outputs[0], m2p.inputs[0])
    L.new(m2p.outputs[0], p2v.inputs[0])
    L.new(p2v.outputs[0], v2m.inputs[0])
    L.new(v2m.outputs[0], smooth.inputs[0])
    L.new(smooth.outputs[0], go.inputs[0])
    mod = src.modifiers.new("proxy", "NODES")
    mod.node_group = ng
    dg = bpy.context.evaluated_depsgraph_get()
    blob_me = bpy.data.meshes.new_from_object(src.evaluated_get(dg))
    bpy.data.objects.remove(src, do_unlink=True)
    bpy.data.meshes.remove(me)
    bpy.data.node_groups.remove(ng)
    blob = bpy.data.objects.new("hair_proxy", blob_me)
    bpy.context.scene.collection.objects.link(blob)
    sm = blob.modifiers.new("smooth", "LAPLACIANSMOOTH")
    sm.iterations = 6
    sm.lambda_factor = 1.0
    dg = bpy.context.evaluated_depsgraph_get()
    sm_me = bpy.data.meshes.new_from_object(blob.evaluated_get(dg))
    blob.modifiers.clear()
    old = blob.data
    blob.data = sm_me
    bpy.data.meshes.remove(old)
    return blob


def transfer_normals(obj, blob, verts):
    """Data Transfer the blob's normals to obj's vertices `verts` (custom
    split normals), applied as the first modifier."""
    name = "_proxy_cards"
    vg = obj.vertex_groups.new(name=name)
    vg.add(list(verts), 1.0, "REPLACE")
    mod = obj.modifiers.new("proxy_normals", "DATA_TRANSFER")
    mod.object = blob
    mod.use_loop_data = True
    mod.data_types_loops = {"CUSTOM_NORMAL"}
    mod.loop_mapping = "POLYINTERP_NEAREST"
    mod.vertex_group = name
    obj.modifiers.move(obj.modifiers.find(mod.name), 0)
    with bpy.context.temp_override(object=obj, active_object=obj, selected_objects=[obj]):
        bpy.ops.object.modifier_apply(modifier=mod.name)
    # Look the group up by its name string: modifier_apply replaces the mesh
    # (which owns the vertex group list), so `vg` now dangles.
    obj.vertex_groups.remove(obj.vertex_groups[name])


# ---------------------------------------------------------------- build

def merged(gcfg):
    cfg = CARDS
    for k, v in (gcfg.get("game") or {}).items():
        cfg = dict(cfg, **{k: (dict(cfg[k], **v) if isinstance(cfg.get(k), dict) else v)})
    return cfg


def build(b, frame, ccfg, g):
    cfg = merged(g["cfg"])
    acfg = cfg["atlas"]
    rng = np.random.default_rng(acfg["seed"])
    E = evaluated_strands(g)
    n, m = E.shape[:2]
    prim, sub, kind, stray, H = g["prim"], g["sub"], g["kind"][:n], g["stray"], g["hang"]
    cloth_gap = ccfg.get("cloth_gap_m", 0.0)
    c = frame.center
    surf = g["surf"]

    # --- per-strand colour (the groom's melanin / redness), IDs
    mel, red = strand_tones(g, cfg)
    vgrid = np.linspace(0, 1, m)[None, :].repeat(n, 0)
    crng = np.random.default_rng(acfg["seed"] + 1)
    cols = strand_colors(mel[:n], red[:n], cfg["albedo"], crng, vgrid)      # (n, m, 3)
    sids = np.random.default_rng(acfg["seed"] + 2).random(n)
    grey = mel[:n] < 0.6

    # --- clumps -> profiles
    main = (kind != 1) & ~stray
    profs = []
    for s in np.unique(sub[main]):
        members = np.where((sub == s) & main)[0]
        if len(members) < 3:
            continue
        p = clump_profile(frame, E, members, cloth_gap, cfg["width_pct"], cfg["width_pad_m"],
                          cfg["min_halfwidth_m"])
        p.update(members=members, kind="front" if kind[s] == 2 else "sec", hang=H[members].mean(0))
        profs.append(p)
    for p in profs:
        mid = p["C"][len(p["C"]) // 3:]
        p["depth"] = float(np.mean([frame.signed(Vector(q), cloth_gap)[2] for q in mid[::3]]))
    dmed = np.median([p["depth"] for p in profs if p["kind"] == "sec"])
    for p in profs:
        p["layer"] = ("top" if p["depth"] >= dmed else "mid") if p["kind"] == "sec" else "front"
    uc = cfg["under"]
    unders = []
    for pc in np.unique(prim[main & (kind == 0)]):
        members = np.where((prim == pc) & main & (kind == 0))[0]
        if len(members) < 10:
            continue
        p0 = clump_profile(frame, E, members, cloth_gap, 50, 0.0, cfg["min_halfwidth_m"])
        side = ((E[members] - p0["C"][None]) * p0["B"][None]).sum(2).mean(1)
        for part in ([side < 0, side >= 0] if uc["split"] == 2 else [np.ones(len(members), bool)]):
            mm = members[part]
            if len(mm) < 10:
                continue
            p = clump_profile(frame, E, mm, cloth_gap, cfg["width_pct"], cfg["width_pad_m"],
                              cfg["min_halfwidth_m"], uc["max_halfwidth_m"])
            p["hw"] *= uc["width"]
            p["C"] = p["C"] - p["N"] * uc["inset_m"] * nsmooth(0.0, 0.2, np.linspace(0, 1, m))[:, None]
            p.update(members=mm, kind="under", layer="under", hang=H[mm].mean(0))
            unders.append(p)

    # --- atlas: lock cells, under cells, fly cells, hairline cells
    W, Hh = acfg["size"]
    cw, ss = acfg["cell_w"], acfg["ss"]
    atl = hsr.Atlas(W, Hh, acfg["data_scale"])
    cells = {}       # name -> (rect, stats)
    cell_stats = []

    def put(name, res, n_strands, x0, y0):
        rect = atl.put(x0, y0, res, cfg["ao"])
        cells[name] = rect
        cell_stats.append({"cell": name, "strands": int(n_strands), "cov_mean": round(float(res["cov"].mean()), 3),
                           "px": [int(res["cov"].shape[1]), int(res["cov"].shape[0])], "x0": x0, "y0": y0})

    hanging = [p for p in profs if p["layer"] in ("mid", "top") and p["hang"][-1] > 0.08]
    hanging.sort(key=lambda p: len(p["members"]))
    nl = acfg["lock_cells"]
    reps = [hanging[int(q * (len(hanging) - 1))] for q in np.linspace(0.1, 0.97, nl)]
    for i, p in enumerate(reps):
        res, ns = raster_clump(p, cols[p["members"]], rng, cw, Hh, ss, acfg, acfg["max_strands"],
                               rough_cfg=cfg["roughness"], sids=sids[p["members"]])
        put(f"lock{i}", res, ns, i * cw, 0)
        p["rep_len"] = len(p["members"])
    under_reps = sorted(unders, key=lambda p: -len(p["members"]))[:acfg["under_cells"]]
    for i, p in enumerate(under_reps):
        res, ns = raster_clump(p, cols[p["members"]], rng, cw, Hh, ss, acfg, acfg["under_max_strands"],
                               rough_cfg=cfg["roughness"], sids=sids[p["members"]])
        put(f"under{i}", res, ns, (nl + i) * cw, 0)
    col_fly = nl + acfg["under_cells"]
    # fly cells: a few loose strands of a hanging clump each, spread wide
    nf = acfg["fly_cells"]
    for i in range(nf):
        src = dict(reps[(3 + 4 * i) % nl])
        pick = rng.choice(len(src["S"]), min(3, len(src["S"])), replace=False)
        fl = dict(src, S=src["S"][pick], O=src["O"][pick] * 2.2)
        res, ns = raster_clump(fl, cols[src["members"][pick]], rng, cw // nf, Hh, ss,
                               dict(acfg, strand_px=acfg["strand_px"] * 0.85), rough_cfg=cfg["roughness"],
                               sids=sids[src["members"][pick]])
        put(f"fly{i}", res, ns, col_fly * cw + i * (cw // nf), 0)
    col_hl = col_fly + 1

    # --- hairline cards: groups of edge strands along the line
    hc = cfg["hairline"]
    droot = np.array([surf.d_eff(tuple(p)) for p in E[:, 0]])
    front_side = E[:, 0, 1] < c.y + 0.01            # front half and temples (not the nape)
    edge = (droot < hc["band_m"]) & (kind == 0) & front_side
    eidx = np.flatnonzero(edge)
    hl_groups = []
    if len(eidx):
        # centres: farthest-point spread over the edge roots at ~spacing_m
        R = E[eidx, 0]
        order = [int(np.argmin(droot[eidx]))]
        dmin = np.linalg.norm(R - R[order[0]], axis=1)
        while dmin.max() > hc["spacing_m"]:
            i = int(np.argmax(dmin))
            order.append(i)
            dmin = np.minimum(dmin, np.linalg.norm(R - R[i], axis=1))
        kdr = KDTree(len(R))
        for i, p in enumerate(R):
            kdr.insert(Vector(p), i)
        kdr.balance()
        for i in order:
            mem = [eidx[k] for _, k, _ in kdr.find_range(Vector(R[i]), hc["radius_m"])]
            if len(mem) >= hc["min_strands"]:
                hl_groups.append(np.array(mem))

    def k_of_len(S, L):
        """Point count covering the first L metres of the mean strand."""
        Cm = S.mean(0)
        arc = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(Cm, axis=0), axis=1))])
        return int(max(4, min(len(arc), np.searchsorted(arc, L) + 1)))

    nh = acfg["hairline_cells"]
    hl_reps = []
    if hl_groups:
        sizes = np.argsort([len(gm) for gm in hl_groups])
        for q in np.linspace(0.2, 0.95, nh):
            gm = hl_groups[sizes[int(q * (len(sizes) - 1))]]
            hl_reps.append(gm)
    for i, gm in enumerate(hl_reps):
        p = clump_profile(frame, E, gm, cloth_gap, 95, 0.0005, 0.0015)
        k3 = k_of_len(E[gm], hc["length_m"])
        res, ns = raster_clump(p, cols[gm], rng, cw, Hh // nh, ss,
                               dict(acfg, strand_px=acfg["strand_px"] * 0.8, tip_fade=0.3, tip_alpha=0.0),
                               k_end=k3, rough_cfg=cfg["roughness"], sids=sids[gm])
        put(f"hairline{i}", res, ns, col_hl * cw, i * (Hh // nh))
    fill = atl.bleed()
    imgs = atl.images("hair_cards")
    hsr.save_pngs(b, imgs, "hair_cards")

    # --- cap mesh + its texture
    obj, bm, uv, uv2, col, hang_l, sector_l, dl, weights = cap_mesh(b, frame, ccfg, g)
    cap_cols = cols.mean(1)
    cap_imgs, cap_stats = bake_cap(frame, g, E, bm, uv, cfg, cap_cols, np.random.default_rng(acfg["seed"] + 3), sids)
    hsr.save_pngs(b, cap_imgs, "hair_cap")
    shade = cfg["layer_shade"]
    for v in bm.verts:
        v[col] = (1.0, 1.0, 1.0, 1.0)

    use = {k: 0 for k in cells}

    def add_card(p, cell, layer, path_from=0, halfwidth_m=None, k_end=None, max_seg=None, flip=False):
        C = p["C"][path_from:k_end]
        arc = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(C, axis=0), axis=1))])
        total = arc[-1]
        if total < 0.006:
            return 0
        nseg = int(np.clip(round(total / cfg["segment_m"]), cfg["min_segments"], max_seg or cfg["max_segments"]))
        if layer == "hairline":
            nseg = hc["segments"]
        s = np.concatenate([[0.0], np.linspace(arc[1] if len(arc) > 1 else 0, total, nseg)])
        idx = np.interp(s, arc, np.arange(len(C)))

        def at(a, x):
            return np.stack([np.interp(x, np.arange(len(a)), a[:, k]) for k in range(a.shape[1])], 1) \
                if a.ndim == 2 else np.interp(x, np.arange(len(a)), a)
        P = at(C, idx)
        Nn = at(p["N"][path_from:k_end], idx)
        hw = at(p["hw"][path_from:k_end], idx) if halfwidth_m is None else np.full(len(idx), halfwidth_m)
        hs = at(p["hang"][path_from:k_end], idx)
        path = [Vector(q) for q in P]
        normals = [Vector(q) for q in Nn]
        nrow = len(path) - 1
        d_root = surf.d_eff(tuple(P[1]))
        hl = cfg["hairline"]
        near = 1 - smoothstep(hl["near_m"][0], hl["near_m"][1], d_root)
        widen = 0.12 + (hl["widen"] - 0.12) * near
        rw0, rw1 = cfg["root_w"]
        root_w = rw0 + (rw1 - rw0) * smoothstep(cfg["root_w_m"][0], cfg["root_w_m"][1], d_root)
        if layer == "hairline":
            root_w, widen = 0.6, 0.3
        tip_w = cfg["tip_width"]

        def halfwidth(t, hw=hw, nrow=nrow):
            i = min(int(round(t * nrow)), nrow)
            w0 = 0.15 + 0.85 * smoothstep(0.0, 0.6 / nrow, t)
            taper = 1 - (1 - tip_w) * t ** 1.3
            return hw[i] * (root_w + (1 - root_w) * smoothstep(0.0, widen, t)) * w0 * taper

        hang_pt = path[int(np.argmax(hs > 0))] if (hs > 0).any() else path[-1]
        sector = hair_springs.sector_id(frame, hang_pt, 1 if p.get("kind") == "front" else 0)
        x = float(np.clip(shade[layer] * rng.lognormal(0, cfg["lock_sigma"]), 0.2, 1.0))

        def on_vert(v, t, hs=hs, nrow=nrow, sector=sector, x=x):
            v[col] = (x, x, x, 1.0)
            v[hang_l] = float(hs[min(int(round(t * nrow)), nrow)])
            v[sector_l] = sector

        x0, y0, x1, y1 = cells[cell]
        if flip:
            x0, x1 = x1, x0
        use[cell] += 1
        return hair_mesh.card(bm, uv, uv2, dl, weights, path, lambda k: normals[k], halfwidth,
                              (float(rng.random()), 1.0 if path[0].x >= c.x else -1.0),
                              curve=cfg["curve"] if layer not in ("fly", "hairline") else 0.1, mat_index=1,
                              v_map=lambda t, y0=y0, y1=y1: y0 + (y1 - y0) * t,
                              u_range=(x0, x1), on_vert=on_vert)

    counts, tris = {}, {}

    def count(layer, t):
        counts[layer] = counts.get(layer, 0) + 1
        tris[layer] = tris.get(layer, 0) + t

    def through_ear(p, start=2):
        if cfg["ear_test"] is None:
            return False
        c0, hw0 = p["C"][start:], p["hw"][start:, None]
        C = np.concatenate([c0, c0 + p["B"][start:] * hw0, c0 - p["B"][start:] * hw0])
        mg = cfg["ear_margin_m"]
        for ec, er in frame.ears:
            ec, er = np.array(ec), np.array(er)
            inside = ((np.abs(C[:, 0] - ec[0]) < er[0] + cfg["ear_lateral_m"])
                      & (np.abs(C[:, 1] - ec[1]) < er[1] + mg)
                      & (C[:, 2] > ec[2] - er[2] - mg) & (C[:, 2] < ec[2] + er[2] - mg))
            if inside.any():
                return True
        return False

    ear_dropped = {}

    def drop_ear(p, layer, start=2):
        if through_ear(p, start):
            ear_dropped[layer] = ear_dropped.get(layer, 0) + 1
            return True
        return False

    lock_names = [f"lock{i}" for i in range(nl)]
    rep_sizes = np.array([r_["rep_len"] for r_ in reps])

    def lock_cell(p):
        # the variant nearest in strand count, +-1 at random
        k = int(np.argmin(np.abs(rep_sizes - len(p["members"]))))
        k = int(np.clip(k + rng.integers(-1, 2), 0, nl - 1))
        return lock_names[k]

    # under (core / volume)
    for p in unders:
        st = max(1, int(len(p["C"]) * uc["start"]))
        if drop_ear(p, "under", st):
            continue
        count("under", add_card(p, f"under{int(rng.integers(len(under_reps)))}", "under", path_from=st,
                                max_seg=uc["max_segments"], flip=bool(rng.random() < 0.5)))
    # front locks: all of a fall's strands
    flc = cfg["front_lock"]
    for pc in np.unique(prim[(kind == 2)]):
        members = np.where((prim == pc) & (kind == 2))[0]
        if len(members) < 10:
            continue
        p = clump_profile(frame, E, members, cloth_gap, flc["width_pct"], flc["pad_m"], cfg["min_halfwidth_m"],
                          flc["max_halfwidth_m"])
        p["C"] = p["C"] - p["N"] * flc["inset_m"]
        p.update(members=members, kind="front", layer="front", hang=H[members].mean(0))
        count("front_lock", add_card(p, lock_names[-1 - int(rng.integers(3))], "front"))
    # mid / top (and the front falls' own sub-clumps). The top cards ride on the clump's outer
    # strands (a percentile of their offset along the outward normal), not its mean: the strands'
    # outer envelope is the silhouette the hero renders.
    tl = cfg["top_lift"]
    lifted = []
    for p in profs:
        if p["layer"] != "top":
            continue
        dn = (p["O"] * p["N"][None]).sum(2)
        off = np.percentile(dn, tl["pct"], axis=0)
        off = np.convolve(np.pad(off, 2, mode="edge"), np.ones(5) / 5, mode="valid")
        off = np.clip(off, 0.0, tl["max_m"]) * nsmooth(0.0, 0.15, np.linspace(0, 1, len(off)))
        p["C"] = p["C"] + p["N"] * off[:, None]
        lifted.append(float(off.max()))
    for p in profs:
        if p["kind"] != "front" and drop_ear(p, p["layer"]):
            continue
        count(p["layer"], add_card(p, lock_cell(p), p["layer"], flip=bool(rng.random() < 0.5)))
    # hairline cards
    for gm in hl_groups:
        p = clump_profile(frame, E, gm, cloth_gap, 90, 0.0008, hc["halfwidth_m"][0], hc["halfwidth_m"][1])
        p["C"] = p["C"] + p["N"] * hc["lift_m"]
        p.update(members=gm, kind="hairline", hang=np.zeros(m))
        k3 = k_of_len(E[gm], hc["length_m"])
        cell = f"hairline{int(rng.integers(len(hl_reps)))}" if hl_reps else lock_names[0]
        count("hairline", add_card(p, cell, "hairline", k_end=k3, flip=bool(rng.random() < 0.5)))
    # flyaways along the stray hairs (kind 3)
    fc = cfg["flyaways"]
    nx = int((g["kind"] == 3).sum())
    if nx and nf:
        offs = g["eval"]["offs"]
        if not np.all(np.diff(offs[n:n + nx + 1]) == m):
            raise RuntimeError("hair_groom_cards: stray point counts changed")
        X = g["eval"]["pos"][n * m:(n + nx) * m].reshape(nx, m, 3).astype(np.float64)
        s0 = int(m * fc["start"])
        Ez = X[:, s0:]
        by_ear = ((Ez[..., 1] < frame.ears_max.y + 0.01) & (Ez[..., 2] > frame.ears_min.z - 0.01)
                  & (Ez[..., 2] < frame.ears_max.z + 0.02)).any(1)
        cand = np.flatnonzero(~by_ear)
        # the longest strays first (they break the silhouette)
        Ls = np.linalg.norm(np.diff(X[cand], axis=1), axis=2).sum(1)
        for j in cand[np.argsort(-Ls)][:fc["count"]]:
            T_, Nn, B, _ = frame_along(frame, X[j], cloth_gap, 0.02)
            p = {"C": X[j], "N": Nn, "B": B, "hw": np.full(m, fc["halfwidth_m"]), "hang": H[0] * 0 + 0.1,
                 "kind": "fly"}
            if drop_ear(p, "fly", s0):
                continue
            count("fly", add_card(p, f"fly{int(rng.integers(nf))}", "fly", path_from=s0,
                                  halfwidth_m=fc["halfwidth_m"], max_seg=fc["max_segments"]))

    # --- keep every card vertex off the skin / suit (after GN; the groom's push_out ran before)
    gap = cfg["gap_m"]
    pushed = 0
    card_v = set()
    for f in bm.faces:
        if f.material_index == 1:
            card_v.update(f.verts)
    for v in card_v:
        loc, nrm, sd = frame.signed(v.co, cloth_gap)
        if loc is not None and sd < gap and sd > -0.03:
            v.co = v.co + nrm * (gap - sd)
            pushed += 1

    springs = None
    if ccfg.get("springs"):
        springs = hair_springs.bind(b, obj, bm, dl, hang_l, sector_l, ccfg["springs"])
    bm.verts.layers.float.remove(hang_l)
    bm.verts.layers.int.remove(sector_l)
    cap_faces = sum(1 for f in bm.faces if f.material_index == 0)
    mcfg = cfg["material"]
    cap_mat = hsr.card_material("hair", cap_imgs, mcfg["roughness"], mcfg["specular"])
    card_mat = hsr.card_material("hair_cards", imgs, mcfg["roughness"], mcfg["specular"])
    hsr.register_maps(b, cap_mat, cap_imgs)
    hsr.register_maps(b, card_mat, imgs)
    hair_mesh.finish(b, obj, bm, [cap_mat, card_mat])
    b.cutouts.append("hair_export")

    # Smooth-proxy normals on the card vertices (not the cap).
    me = obj.data
    card_verts = set()
    for poly in me.polygons:
        if poly.material_index == 1:
            card_verts.update(poly.vertices)
    pts = E[::cfg["proxy"]["every"]].reshape(-1, 3)
    blob = proxy_blob(pts, cfg["proxy"])
    transfer_normals(obj, blob, card_verts)
    blob_info = {"verts": len(blob.data.vertices), "faces": len(blob.data.polygons)}
    bpy.data.objects.remove(blob, do_unlink=True)

    total = sum(len(p.vertices) - 2 for p in me.polygons)
    tips = sorted(float(p["C"][-1][2]) for p in profs)
    for st in cell_stats:
        st["cards"] = use.get(st["cell"], 0)
    sc = bpy.context.scene
    b.notes["hair"] = {
        "source": "groom", "baker": "v4 (T9)", "cards": counts, "card_tris": tris, "cap_faces": cap_faces,
        "tris": total, "ear_dropped": ear_dropped, "pushed_card_verts": pushed,
        "top_lift_mm_p50_max": [round(float(np.median(lifted)) * 1e3, 2), round(float(max(lifted)) * 1e3, 2)] if lifted else None,
        "atlas": {"size": [W, Hh], "cell_w": cw, "data_scale": acfg["data_scale"],
                  "mm_per_px_along_0.55m": round(0.55e3 / Hh, 3), "cells": cell_stats,
                  "fill_linear": [round(float(x), 5) for x in fill]},
        "cap": cap_stats, "hairline_groups": len(hl_groups),
        "albedo": {"median_linear": [round(float(x), 5) for x in np.median(cols.reshape(-1, 3), 0)],
                   "grey_share": round(float(grey.mean()), 4), "cfg": cfg["albedo"]},
        "proxy_blob": blob_info,
        "tip_z_p10_p50_p90": [round(tips[int(q * (len(tips) - 1))], 4) for q in (0.1, 0.5, 0.9)],
        "springs": springs,
        "scene_curve_shape": getattr(getattr(sc, "cycles_curves", None), "shape", None),
    }
    unused = [s["cell"] for s in cell_stats if s["cards"] == 0]
    empty = [s["cell"] for s in cell_stats if s["cov_mean"] < 0.01]
    if unused or empty:
        b.notes["hair"]["cell_warnings"] = {"unused": unused, "empty": empty}
    b.notes["hair"].update(silhouette(frame, obj, g))
    return obj


def silhouette(frame, obj, g):
    """Width at eye level (spec: <= 1.35 x the skull there) and how far the
    hair breaks beyond the cap at the sides (direction: >= 30 mm): per 1 cm
    band over the cap's height, the hair's x extent past the cap's (both
    sides), maximum over the bands (the smaller side of the best band)."""
    mw = obj.matrix_world
    H = np.array([tuple(mw @ v.co) for v in obj.data.vertices])
    capv = set()
    for poly in obj.data.polygons:
        if poly.material_index == 0:
            capv.update(poly.vertices)
    Cv = H[sorted(capv)]
    body = frame.body
    Bv = np.array([tuple(body.matrix_world @ v.co) for v in body.data.vertices])
    Bv = Bv[np.abs(Bv[:, 1] - frame.center.y) < 0.08]
    out = {}
    eye_z = frame.ear_z + 0.02

    def ext(P, z):
        sel = P[np.abs(P[:, 2] - z) < 0.005]
        return (sel[:, 0].min(), sel[:, 0].max()) if len(sel) else None

    he, be = ext(H, eye_z), ext(Bv, eye_z)
    if he and be:
        out["width_eye_level_m"] = round(float(he[1] - he[0]), 4)
        out["width_to_skull"] = round(float((he[1] - he[0]) / (be[1] - be[0])), 3)
    best = (0.0, 0.0, None)
    for z in np.arange(Cv[:, 2].min() + 0.005, Cv[:, 2].max(), 0.01):
        he, be = ext(H, z), ext(Cv, z)
        if not (he and be):
            continue
        l, r = be[0] - he[0], he[1] - be[1]
        if min(l, r) > min(best[0], best[1]):
            best = (l, r, z)
    out["side_break_m"] = [round(float(best[0]), 4), round(float(best[1]), 4)]
    zt = frame.ears_max.z + 0.01
    he, ce = ext(H, zt), ext(Cv, zt)
    if he and ce:
        out["side_break_temple_m"] = [round(float(ce[0] - he[0]), 4), round(float(he[1] - ce[1]), 4)]
    out["side_break_z"] = round(float(best[2]), 3) if best[2] is not None else None
    return out
