"""Game facial hair baked from the strand groom (beard_groom.py).

Two kinds of geometry, both painted from the same evaluated strands as the
hero render, so the game version matches it in density, direction and tone:

Shells. The decimated skin patch (it keeps the skin weights) is stacked S
times along the normal. Shell k sits at t_k x canopy(v), where canopy is the
local height of the groom (a high percentile of the strand heights near v),
so the stack hugs the stubble where the hair is short and stands off the
chin where it is long. Tile k of one atlas is a volumetric slice of the
groom: every strand segment whose normalised height lies in shell k's band
is drawn at its foot point on the skin (projected into the tile), with the
strand's own colour and a root-to-tip shade. Low shells are the skin-hugging
base (roots, stubble: skin shows between them); the upper shells hold the
lying-down hair, drawn as strokes along the strand direction.

Cards. Tapered strips that follow groom clumps at the silhouette (jaw edge,
chin, moustache over the lip): each card's spine is the mean of the strands
rooted within a radius of its centre strand, its width the spread of those
strands, and its texture cell in the card atlas is those strands drawn in
the card's own frame. The card plane rolls between lying on the skin and
standing as a fin (containing the skin normal) so the profile silhouette is
broken where the beard edge is seen side-on.

Atlases are RGBA (straight alpha, exported as glTF MASK via export.fix_alpha);
the RGB under transparent texels is the mean hair colour, so filtering at the
alpha edge does not darken the hairs into a black outline.
"""

import math

import bmesh
import numpy as np
from mathutils import Vector
from mathutils.kdtree import KDTree

from . import facial_hair, hair_mesh
from . import hair_strand_raster as hsr


# --------------------------------------------------------------------------
# Line rasterising

class Canvas:
    """Coverage-weighted colour accumulation for anti-aliased lines."""

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.alpha = np.zeros(h * w, dtype=np.float32)
        self.csum = np.zeros((h * w, 3), dtype=np.float32)
        self.wsum = np.zeros(h * w, dtype=np.float32)

    def lines(self, a, b, radius, rgb, step=0.5):
        """Segments a -> b ((n, 2) px), radius (n,), rgb (n, 3)."""
        if len(a) == 0:
            return
        d = b - a
        ln = np.hypot(d[:, 0], d[:, 1])
        ns = np.maximum(np.ceil(ln / step).astype(int), 1)
        idx = np.repeat(np.arange(len(a)), ns + 1)
        off = np.concatenate([np.arange(n + 1) / n for n in ns])
        pts = a[idx] + d[idx] * off[:, None]
        rr = radius[idx]
        col = rgb[idx]
        rmax = int(math.ceil(float(rr.max()))) + 1
        oy, ox = np.mgrid[-rmax:rmax + 1, -rmax:rmax + 1]
        ox, oy = ox.ravel(), oy.ravel()
        # chunk to bound memory
        for s in range(0, len(pts), 200000):
            p, r, c = pts[s:s + 200000], rr[s:s + 200000], col[s:s + 200000]
            px = np.floor(p[:, 0])[:, None] + ox[None, :]
            py = np.floor(p[:, 1])[:, None] + oy[None, :]
            dd = np.hypot(px + 0.5 - p[:, 0:1], py + 0.5 - p[:, 1:2])
            cov = np.clip(r[:, None] + 0.5 - dd, 0.0, 1.0)
            m = (cov > 0.01) & (px >= 0) & (px < self.w) & (py >= 0) & (py < self.h)
            flat = (py[m] * self.w + px[m]).astype(np.int64)
            cv = cov[m].astype(np.float32)
            np.maximum.at(self.alpha, flat, cv)
            cc = np.repeat(c[:, None, :], len(ox), axis=1)[m]
            np.add.at(self.wsum, flat, cv)
            for ch in range(3):
                np.add.at(self.csum[:, ch], flat, cv * cc[:, ch])

    def rgba(self, fill_rgb):
        w = self.wsum[:, None]
        rgb = np.where(w > 1e-6, self.csum / np.maximum(w, 1e-6), fill_rgb[None, :])
        out = np.concatenate([rgb, self.alpha[:, None]], axis=1)
        return out.reshape(self.h, self.w, 4)


def make_image(name, rgba, srgb=True):
    """Colour atlas: rgba (H, W, 4) float, RGB linear, row 0 = image bottom
    (Blender convention); stored sRGB-encoded (hair_mesh.rgba_image). Before
    this the linear values went straight into the sRGB byte image, so the
    game facial hair read about 10x too dark and its dark tones banded."""
    return hair_mesh.rgba_image(name, rgba, srgb)


def linear(rgb):
    rgb = np.asarray(rgb, dtype=np.float64)
    return np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)


# --------------------------------------------------------------------------
# Groom geometry helpers

def strand_feet(pts, bvh):
    """Height over the skin and the foot point (nearest skin point) of every
    strand point: (h (m, k), feet (m, k, 3), normal at the root (m, 3))."""
    m, k, _ = pts.shape
    h = np.zeros((m, k))
    feet = np.zeros_like(pts)
    rn = np.zeros((m, 3))
    for j in range(m):
        for i in range(k):
            p = Vector(pts[j, i])
            loc, nrm, _, _ = bvh.find_nearest(p)
            if loc is None:
                feet[j, i] = pts[j, i]
                continue
            h[j, i] = (p - loc).dot(nrm)
            feet[j, i] = loc[:]
            if i == 0:
                rn[j] = nrm[:]
    return h, feet, rn


def canopy_field(bm, roots, top, radius_m, pct, floor_m):
    """Per base vertex: the pct-th percentile of the strand heights (top,
    per strand) rooted within radius_m."""
    kd = KDTree(len(roots))
    for i, r in enumerate(roots):
        kd.insert(Vector(r), i)
    kd.balance()
    out = {}
    for v in bm.verts:
        near = [i for _, i, _ in kd.find_range(v.co, radius_m)]
        out[v] = max(float(np.percentile(top[near], pct)), floor_m) if near else floor_m
    facial_hair.smooth_field(bm, out, 2)
    return out


# --------------------------------------------------------------------------
# Shells

def build_shells(b, obj, bm, canopy, project, grooms, cfg, name, extra=None):
    """Shell stack over the decimated patch bm (skin weights in its deform
    layer), textured from the grooms: a list of dicts with pts (m,k,3),
    h (m,k), feet (m,k,3), rgb (m,3) linear, radius (m,) metres, canopy (m,)
    per strand. project(Vector) -> (u, v) in 0..1 across a tile. extra(bm, uv,
    dl) -> (tris, material) adds cards. Returns stats."""
    S = cfg["layers"]
    ts = np.array([((k + 1) / S) ** cfg["t_pow"] for k in range(S)])
    cols = cfg["atlas_cols"]
    rows = math.ceil(S / cols)
    tw, th = cfg["tile"]
    W, H = tw * cols, th * rows
    welded, culled = facial_hair.clean_patch(bm, {"canopy": canopy}, project, cfg.get("weld_m", 2e-5),
                                             cfg.get("min_face_area_m2", 1e-10), cfg.get("min_uv_area", 1e-9))
    base_faces = list(bm.faces)
    base_verts = list(bm.verts)
    bm.normal_update()
    dl = bm.verts.layers.deform.verify()
    uv = bm.loops.layers.uv.verify()
    uv2 = bm.loops.layers.uv.new("strand")
    puv = {v: project(v.co) for v in base_verts}
    normals = {v: v.normal.copy() for v in base_verts}
    root_att = []  # per new vertex: the base vertex's skin point (for the refit)
    tris = 0
    for k in range(S):
        x0, y0 = (k % cols) * tw, (k // cols) * th
        new = {}
        for v in base_verts:
            nv = bm.verts.new(v.co + normals[v] * (ts[k] * canopy[v] + cfg.get("lift_m", 0.0)))
            for g, w in v[dl].items():
                nv[dl][g] = w
            new[v] = nv
            root_att.append(v.co.copy())
        for f in base_faces:
            nf = bm.faces.new([new[v] for v in f.verts])
            nf.material_index = 0
            for loop, v in zip(nf.loops, f.verts):
                u_, w_ = puv[v]
                loop[uv].uv = ((x0 + u_ * tw) / W, (y0 + w_ * th) / H)
                loop[uv2].uv = (ts[k], 0.0)
            tris += len(f.verts) - 2
    # Atlas: tile k is the slice of the groom between the band edges.
    edges = np.concatenate([[-1e9], (ts[:-1] + ts[1:]) / 2, [1e9]])
    px_per_m = cfg["px_per_m"]
    shade_cfg = cfg["shade"]
    canvas = Canvas(W, H)
    for gr in grooms:
        pts, h, feet, rgb = gr["pts"], gr["h"], gr["feet"], gr["rgb"]
        m, kk, _ = pts.shape
        t = h / np.maximum(gr["canopy"][:, None], 1e-4)
        uvp = np.array([project(Vector(p)) for p in feet.reshape(-1, 3)]).reshape(m, kk, 2)
        uvp[..., 0] *= tw
        uvp[..., 1] *= th
        rad_px = np.maximum(gr["radius"] * px_per_m * cfg["radius_scale"], cfg["min_radius_px"])
        for k in range(S):
            lo, hi = edges[k], edges[k + 1]
            x0, y0 = (k % cols) * tw, (k // cols) * th
            a_all, b_all, r_all, c_all = [], [], [], []
            for i in range(kk - 1):
                t0, t1 = t[:, i], t[:, i + 1]
                tmin, tmax = np.minimum(t0, t1), np.maximum(t0, t1)
                sel = (tmax >= lo) & (tmin <= hi)
                if not sel.any():
                    continue
                dt = t1[sel] - t0[sel]
                safe = np.where(np.abs(dt) > 1e-9, dt, 1e-9)
                f0 = np.clip((lo - t0[sel]) / safe, 0, 1)
                f1 = np.clip((hi - t0[sel]) / safe, 0, 1)
                fa, fb = np.minimum(f0, f1), np.maximum(f0, f1)
                flat = np.abs(dt) <= 1e-9
                fa[flat], fb[flat] = 0.0, 1.0
                pa, pb = uvp[sel, i], uvp[sel, i + 1]
                a_all.append(pa + (pb - pa) * fa[:, None])
                b_all.append(pa + (pb - pa) * fb[:, None])
                # strands taper: thinner toward the tip
                r_all.append(rad_px[sel] * (1 - 0.5 * (i + 0.5) / (kk - 1)))
                c_all.append(rgb[sel])
            if not a_all:
                continue
            a = np.concatenate(a_all) + [x0, y0]
            bb = np.concatenate(b_all) + [x0, y0]
            tk = ts[k]
            shade = shade_cfg["root"] + (1 - shade_cfg["root"]) * min(tk / shade_cfg["full_at"], 1.0) ** 0.7
            base = np.concatenate(c_all)
            gain = np.full((len(base), 1), cfg.get("albedo_gain", 1.0))
            if "grey_gain" in cfg:
                # light (grey) strands get their own, lower lift: the dark
                # strands' gain turns them into white flecks
                lb = base @ np.array([0.2126, 0.7152, 0.0722])
                lo, hi = cfg.get("grey_lum", [0.12, 0.25])
                w = np.clip((lb - lo) / (hi - lo), 0, 1)[:, None]
                gain = gain + (cfg["grey_gain"] - gain) * w
            col = base * shade * gain
            # lifted warm strands go orange: pull the colour toward its value
            lum = (col @ np.array([0.2126, 0.7152, 0.0722]))[:, None]
            col = lum + (col - lum) * cfg.get("saturation", 1.0)
            canvas.lines(a, bb, np.concatenate(r_all), col)
    rgb = np.concatenate([gr["rgb"] for gr in grooms])
    fill = (rgb.mean(0) * shade_cfg["root"]).astype(np.float32)
    img = make_image(name + "_atlas", canvas.rgba(fill))
    bmesh.ops.delete(bm, geom=base_faces, context="FACES")
    left = [v for v in base_verts if v.is_valid]  # base verts on wire edges
    if left:
        bmesh.ops.delete(bm, geom=left, context="VERTS")
    mats = [hair_mesh.material(name, "#ffffff", cfg["roughness"], img, cfg["specular"], wrap=False)]
    card_stats = {}
    if extra is not None:
        card_stats, card_mat = extra(bm, uv, uv2, dl)
        mats.append(card_mat)
    hair_mesh.finish(b, obj, bm, mats)
    # Stacked alpha layers self-shadow into a near-black mass in a path
    # tracer; a real-time engine's shadow map can't resolve that either.
    obj.visible_shadow = cfg.get("cast_shadow", True)
    # skin point under every shell vertex (cards: their root), for the refit
    me = obj.data
    att = me.attributes.new("fh_root", "FLOAT_VECTOR", "POINT")
    roots = root_att + card_stats.pop("_roots", [])
    if len(roots) != len(me.vertices):
        raise RuntimeError(f"fh_root: {len(roots)} roots for {len(me.vertices)} vertices "
                           f"(shells {len(root_att)})")
    att.data.foreach_set("vector", [c for r in roots for c in r])
    nudged, culled_tan = facial_hair.guard_tangents(obj, me.uv_layers[0].name, cfg.get("tangent_nudge_m", 2e-4),
                                                    cfg.get("tangent_passes", 2))
    stats = {"layers": S, "shell_tris": tris, "atlas": [W, H], "t": [round(x, 3) for x in ts],
             "welded_verts": welded, "culled_degenerate_faces": culled,
             "tangent_nudged_loops": nudged, "tangent_culled_faces": culled_tan,
             # linear RGB under the transparent texels (stored sRGB-encoded):
             # a read-back check of the atlas encoding
             "atlas_fill_linear": [round(float(x), 6) for x in fill]}
    stats.update(card_stats)
    return stats


# --------------------------------------------------------------------------
# Cards

def pick_centres(roots, cand, prio, spacing, limit, rng):
    """Greedy blue-noise pick among candidate strands (indices), in order of
    priority (+ jitter); no two centres closer than spacing."""
    idx = np.flatnonzero(cand)
    order = idx[np.argsort(-(prio[idx] + rng.random(len(idx)) * 0.3))]
    chosen = []
    pos = np.zeros((0, 3))
    for j in order:
        if len(chosen) >= limit:
            break
        if len(pos) and np.min(np.sum((pos - roots[j]) ** 2, axis=1)) < spacing ** 2:
            continue
        chosen.append(j)
        pos = np.vstack([pos, roots[j]])
    return chosen


def build_cards(bm, uv, uv2, dl, groom, centres, roll, weights_of, cfg, name, rng):
    """Cards along groom clumps. centres: strand indices; roll: per centre
    angle (0 = lying on the skin, pi/2 = fin). weights_of(root) -> {group
    index: weight}. Returns (stats incl. '_roots', material)."""
    pts, rgb, rn = groom["pts"], groom["rgb"], groom["root_n"]
    m, k, _ = pts.shape
    roots = pts[:, 0]
    kd = KDTree(m)
    for i, r in enumerate(roots):
        kd.insert(Vector(r), i)
    kd.balance()
    cw, ch = cfg["cell"]
    ncols = cfg["atlas_px"][0] // cw
    nrows = math.ceil(len(centres) / ncols)
    W, H = ncols * cw, max(nrows, 1) * ch
    canvas = Canvas(W, H)
    rows_n = cfg["segments"] + 1
    tris = 0
    vroots = []
    for ci, j in enumerate(centres):
        members = [i for _, i, _ in kd.find_range(Vector(roots[j]), cfg["clump_radius_m"])]
        if len(members) < cfg["min_members"]:
            continue
        mp = pts[members]
        spine = mp.mean(0)
        # resample spine and member strands to rows_n by index fraction
        si = np.linspace(0, k - 1, rows_n)
        i0 = np.floor(si).astype(int).clip(0, k - 2)
        fr = (si - i0)[:, None]
        sp = spine[i0] * (1 - fr) + spine[i0 + 1] * fr
        seg = np.linalg.norm(np.diff(sp, axis=0), axis=1)
        if seg.sum() < cfg["min_len_m"]:
            continue
        # extend a little past the tip so the strand ends sit inside the card
        tip_dir = (sp[-1] - sp[-2]) / max(seg[-1], 1e-9)
        sp[-1] = sp[-1] + tip_dir * seg.sum() * cfg["tip_extend"]
        tan = np.gradient(sp, axis=0)
        tan /= np.maximum(np.linalg.norm(tan, axis=1, keepdims=True), 1e-9)
        n0 = rn[j]
        nrm = n0[None, :] - tan * (tan @ n0)[:, None]
        nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-9)
        bi = np.cross(tan, nrm)
        a = roll[ci]
        wdir = bi * math.cos(a) + nrm * math.sin(a)
        # width: spread of the members across the card, tapering to the tip
        allp = mp[:, i0] * (1 - fr[None]) + mp[:, i0 + 1] * fr[None]  # (n, rows, 3)
        off = ((allp - sp[None]) * wdir[None]).sum(2)
        spread = np.percentile(np.abs(off), 85, axis=0)
        s = np.linspace(0, 1, rows_n)
        hw = np.clip(spread * cfg["width_scale"], cfg["min_halfwidth_m"], cfg["max_halfwidth_m"])
        hw = np.maximum(hw, cfg["min_halfwidth_m"]) * (1 - cfg["taper"] * s)
        # card vertices sit a fraction of a mm off their foot to avoid z-fight
        cell = ci
        cx0, cy0 = (cell % ncols) * cw, (cell // ncols) * ch
        wts = weights_of(roots[j])
        rowv = []
        for r in range(rows_n):
            vl = bm.verts.new(Vector(sp[r] - wdir[r] * hw[r]))
            vr = bm.verts.new(Vector(sp[r] + wdir[r] * hw[r]))
            for v in (vl, vr):
                for g, w in wts.items():
                    v[dl][g] = w
                vroots.append(Vector(roots[j]))
            rowv.append((vl, vr))
        pad = 0.5
        for r in range(rows_n - 1):
            f = bm.faces.new((rowv[r][0], rowv[r][1], rowv[r + 1][1], rowv[r + 1][0]))
            f.material_index = 1
            for loop, (uu, vv) in zip(f.loops, ((0, r), (1, r), (1, r + 1), (0, r + 1))):
                u_px = cx0 + pad + uu * (cw - 2 * pad)
                v_px = cy0 + pad + vv / (rows_n - 1) * (ch - 2 * pad)
                loop[uv].uv = (u_px / W, v_px / H)
                loop[uv2].uv = (vv / (rows_n - 1), 1.0)
            tris += 2
        # texture: members in the card frame
        su = lambda P, r: 0.5 + ((P - sp[r]) * wdir[r]).sum(-1) / (2 * hw[r])
        U = np.stack([su(allp[:, r], r) for r in range(rows_n)], axis=1)  # (n, rows)
        Vv = np.tile(np.linspace(0, 1, rows_n), (len(members), 1))
        # strands shorter than the card end early
        mlen = np.linalg.norm(np.diff(mp, axis=1), axis=2).sum(1)
        Vv = Vv * (mlen / max(seg.sum() * (1 + cfg["tip_extend"]), 1e-6))[:, None]
        px = cx0 + pad + U * (cw - 2 * pad)
        py = cy0 + pad + Vv * (ch - 2 * pad)
        inside = (U > -0.2) & (U < 1.2)
        a_ = np.stack([px[:, :-1], py[:, :-1]], -1).reshape(-1, 2)
        b_ = np.stack([px[:, 1:], py[:, 1:]], -1).reshape(-1, 2)
        keep = (inside[:, :-1] & inside[:, 1:]).ravel()
        tt = np.tile((np.arange(rows_n - 1) + 0.5) / (rows_n - 1), len(members))
        shade = cfg["root_shade"] + (1 - cfg["root_shade"]) * tt ** 0.6
        rad = np.repeat(groom["radius"][members] * cfg["px_per_m"] * cfg["radius_scale"], rows_n - 1)
        rad = np.maximum(rad * (1 - 0.5 * tt), cfg["min_radius_px"])
        cols = np.repeat(rgb[members], rows_n - 1, axis=0) * shade[:, None]
        canvas.lines(np.clip(a_[keep], [cx0, cy0], [cx0 + cw - 1, cy0 + ch - 1]),
                     np.clip(b_[keep], [cx0, cy0], [cx0 + cw - 1, cy0 + ch - 1]),
                     rad[keep], cols[keep])
    fill = (rgb.mean(0) * cfg["root_shade"]).astype(np.float32)
    img = make_image(name + "_cards", canvas.rgba(fill))
    mat = hair_mesh.material(name + "_cards", "#ffffff", cfg["roughness"], img, cfg["specular"], wrap=False)
    return {"cards": len(centres), "card_tris": tris, "card_atlas": [W, H],
            "card_fill_linear": [round(float(x), 6) for x in fill], "_roots": vroots}, mat


# --------------------------------------------------------------------------
# Cards over the whole groom (T9: the shipped path; the shells above stay
# behind shells.enabled)

def strand_rgb(mel, red, acfg, rng):
    """Linear colour per strand from its melanin / redness: the scalp's mapping
    (hair_strand_raster.chiang_color, the hero Principled Hair's melanin model),
    with the per-strand value jitter and one calibrated gain."""
    m = mel * (1.0 + acfg.get("random_color", 0.0) * rng.uniform(-1, 1, len(mel)))
    c = hsr.chiang_color(m, red, acfg["radial_roughness"], acfg["path"])
    return c * (acfg["gain"] * rng.lognormal(0, acfg["value_sigma"], len(mel)))[:, None]


def build_groom_cards(b, obj, bm, groom, centres, rolls, weights_of, cfg, name, skin_bvh, rng, gaps=None,
                      tip_fades=None, clips=None, ribbons=None):
    """The game facial hair as cards only (T9): the skin patch bm (it carried the skin
    weights) is replaced by one tapered strip per centre strand, following the mean of
    the strands rooted within clump_radius_m (their growth direction), with its own atlas
    cell: those strands drawn in the card's frame (hair_strand_raster: per-strand colour,
    tip alpha, flow, depth, ID, root-to-tip). rolls: per centre, 0 = lying on the skin,
    pi/2 = a fin standing off it. groom: pts (m, k, 3), root_n (m, 3), rgb (m, 3) linear,
    radius (m,) at the root; optional (T11) alpha (m,) per-strand alpha scale (the cheek-line
    fade: root density) and px (m,) per-strand width scale (grey strands finer). gaps: per
    centre skin clearance in m past the root row (default cfg gap_m; T11: the moustache's
    lip edge); tip_fades: per centre tip_fade (T11: the lip edge fades longer). T21: clips: per centre None or a z (m) where
    the card ends (the moustache's lip-edge cards stop at the vermilion border, where the lip
    ribbon takes over); cfg root_fade {len, jitter}: each strand fades in from a staggered start
    (a card's root row drew a hard comb line: the moustache top, the cheek line); ribbons: lip
    ribbon cards (lip_ribbon_cards) drawn into the same atlas after the clump cards. Writes obj
    (finish) and its fh_root attribute; returns stats."""
    bmesh.ops.delete(bm, geom=list(bm.faces), context="FACES")
    left = [v for v in bm.verts if v.is_valid]
    if left:
        bmesh.ops.delete(bm, geom=left, context="VERTS")
    dl = bm.verts.layers.deform.verify()
    uv = bm.loops.layers.uv.verify()
    uv2 = bm.loops.layers.uv.get("strand") or bm.loops.layers.uv.new("strand")
    pts, rn, rgb = groom["pts"], groom["root_n"], groom["rgb"]
    m, k, _ = pts.shape
    roots = pts[:, 0]
    kd = KDTree(m)
    for i, r in enumerate(roots):
        kd.insert(Vector(r), i)
    kd.balance()
    slen = np.linalg.norm(np.diff(pts, axis=1), axis=2).sum(1)
    sid_all = rng.random(m)
    rad_ref = float(np.median(groom["radius"]))
    cw, ch = cfg["cell"]
    W, H = cfg["atlas_px"]
    ncols, nrows = W // cw, H // ch
    atl = hsr.Atlas(W, H, cfg["data_scale"])
    ss = cfg["ss"]
    rows_n = cfg["segments"] + 1
    rc = cfg["roughness"]
    jit = math.radians(cfg.get("flow_jitter_deg", 6.0))
    tris, made, skipped, pushed = 0, 0, 0, 0
    vroots, covs, members_n, lens = [], [], [], []
    gap = cfg["gap_m"]
    s_alpha = groom.get("alpha")
    s_px = groom.get("px")
    rf = cfg.get("root_fade")
    # T21: the staggered root start per strand (own stream: the card picks and IDs are unchanged)
    r0_all = np.random.default_rng(cfg.get("seed", 0) + 31).uniform(0, rf["jitter"], m) if rf else None
    clipped = 0
    for ci, j in enumerate(centres):
        if made >= ncols * nrows:
            skipped += 1
            continue
        mem = np.array([i for _, i, _ in kd.find_range(Vector(roots[j]), cfg["clump_radius_m"])])
        if len(mem) < cfg["min_members"]:
            skipped += 1
            continue
        S = pts[mem]
        spine = S.mean(0)
        seg = np.linalg.norm(np.diff(spine, axis=0), axis=1)
        total = seg.sum()
        if total < cfg["min_len_m"]:
            skipped += 1
            continue
        # extend past the mean tip so the longer members' ends sit inside the card
        target = max(float(np.percentile(slen[mem], 85)), total) * (1 + cfg["tip_extend"])
        tip_dir = (spine[-1] - spine[-2]) / max(seg[-1], 1e-9)
        C = np.vstack([spine, spine[-1] + tip_dir * (target - total)])
        arcC = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(C, axis=0), axis=1))])
        clip_end = None
        if clips is not None and clips[ci] is not None:
            # T21: end the card where its spine drops below the clip height (k points are kept: the
            # spine is resampled along its own arc to the clip, so the frame below stays k long)
            below = np.flatnonzero(C[:, 2] < clips[ci])
            if len(below) and below[0] > 0:
                q = below[0]
                za, zb = C[q - 1, 2], C[q, 2]
                f_ = (za - clips[ci]) / max(za - zb, 1e-9)
                a_end = arcC[q - 1] + f_ * (arcC[q] - arcC[q - 1])
                if a_end >= cfg["min_len_m"]:
                    clip_end = a_end
        if clip_end is not None:
            sk = np.linspace(0, clip_end, len(C))
            C = np.stack([np.interp(sk, arcC, C[:, q]) for q in range(3)], 1)
            arcC = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(C, axis=0), axis=1))])
            clipped += 1
        vtot = arcC[-1]
        lens.append(vtot)
        T = np.gradient(C, axis=0)
        T /= np.maximum(np.linalg.norm(T, axis=1, keepdims=True), 1e-9)
        n0 = rn[j]
        Nn = n0[None, :] - T * (T @ n0)[:, None]
        Nn /= np.maximum(np.linalg.norm(Nn, axis=1, keepdims=True), 1e-9)
        Bi = np.cross(T, Nn)
        a = rolls[ci]
        wdir = Bi * math.cos(a) + Nn * math.sin(a)
        cn = np.cross(T, wdir)
        O = S - C[None, :k]
        across = np.abs((O * wdir[None, :k]).sum(2))
        hwk = np.percentile(across, 90, axis=0) * cfg["width_scale"]
        hwk = np.concatenate([hwk, hwk[-1:]])
        s01 = arcC / vtot
        hwk = np.clip(hwk, cfg["min_halfwidth_m"], cfg["max_halfwidth_m"]) * (1 - cfg["taper"] * s01)
        # --- cell: the members in the card frame, back to front
        cell = hsr.Cell(cw, ch, ss)
        dep = (O * cn[None, :k]).sum(2)
        dmax = np.abs(dep).max() + 1e-6
        for i in np.argsort(dep.mean(1), kind="stable"):
            u = (O[i] * wdir[:k]).sum(1) / hwk[:k]
            v_raw = (arcC[:k] + (O[i] * T[:k]).sum(1)) / vtot
            v = np.clip(v_raw, 0, 1)
            sl = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(S[i], axis=0), axis=1))])
            s_ = sl / max(sl[-1], 1e-9)
            tf = cfg["tip_fade"] if tip_fades is None else tip_fades[ci]
            tip = np.clip((s_ - (1 - tf)) / tf, 0, 1)
            w = cfg["strand_px"] * float(np.clip(groom["radius"][mem[i]] / rad_ref, 0.5, 1.6))
            if s_px is not None:
                w *= float(s_px[mem[i]])
            rad = w + (cfg["tip_px"] - w) * tip
            alpha = 1.0 - (1.0 - cfg["tip_alpha"]) * tip
            if s_alpha is not None:
                alpha = alpha * float(s_alpha[mem[i]])
            if rf:
                r0 = r0_all[mem[i]]
                alpha = alpha * np.clip((s_ - r0) / rf["len"], 0, 1) ** 1.5
            if clip_end is not None:
                # the members' lengths past the clipped card end are the ribbon's: faded out, not piled at v = 1
                alpha = alpha * (1.0 - np.clip((v_raw - 0.8) / 0.2, 0, 1))
            sid = float(sid_all[mem[i]])
            cell.draw((0.5 + 0.5 * u) * cw, v * ch, rad, alpha, v, dep[i] / dmax, rgb[mem[i]], sid,
                      rc["base"] + rc["jitter"] * (2 * sid - 1), jit)
        r = cell.resolve()
        x0, y0 = (made % ncols) * cw, (made // ncols) * ch
        u0, v0, u1, v1 = atl.put(x0, y0, r, cfg["ao"])
        covs.append(float(r["cov"].mean()))
        members_n.append(len(mem))
        # --- strip (2 vertices wide), rows even by length, kept gap_m off the skin
        sr = np.linspace(0, vtot, rows_n)

        def at(a_, x):
            if a_.ndim == 2:
                return np.stack([np.interp(x, arcC, a_[:, q]) for q in range(a_.shape[1])], 1)
            return np.interp(x, arcC, a_)
        P, Wd, hw = at(C, sr), at(wdir, sr), at(hwk, sr)
        Wd /= np.maximum(np.linalg.norm(Wd, axis=1, keepdims=True), 1e-9)
        wts = weights_of(roots[j])
        rowv = []
        for q in range(rows_n):
            pair = []
            gq = gap if (gaps is None or q == 0) else max(gap, gaps[ci])
            for sgn in (-1.0, 1.0):
                p = Vector(P[q] + sgn * Wd[q] * hw[q])
                loc, nrm, _, _ = skin_bvh.find_nearest(p)
                if loc is not None:
                    h = (p - loc).dot(nrm)
                    if h < gq:
                        p = p + nrm * (gq - h)
                        pushed += 1
                vv = bm.verts.new(p)
                for g_, w_ in wts.items():
                    vv[dl][g_] = w_
                vroots.append(Vector(roots[j]))
                pair.append(vv)
            rowv.append(pair)
        for q in range(rows_n - 1):
            f = bm.faces.new((rowv[q][0], rowv[q][1], rowv[q + 1][1], rowv[q + 1][0]))
            f.material_index = 0
            ta, tb = sr[q] / vtot, sr[q + 1] / vtot
            for loop, (uu, tt) in zip(f.loops, ((u0, ta), (u1, ta), (u1, tb), (u0, tb))):
                loop[uv].uv = (uu, v0 + (v1 - v0) * tt)
                loop[uv2].uv = (tt, 1.0)
            tris += 2
        made += 1
    rib_stats = None
    if ribbons:
        rib_stats = lip_ribbon_cards(bm, uv, uv2, dl, atl, made, ncols, nrows, cw, ch, groom, sid_all, ribbons,
                                     weights_of, cfg, skin_bvh, vroots)
        made += rib_stats["cards"]
        tris += rib_stats["tris"]
    fill = atl.bleed()
    imgs = atl.images(name + "_cards")
    hsr.save_pngs(b, imgs, name + "_cards")
    mc = cfg["material"]
    mat = hsr.card_material(name + "_cards", imgs, mc["roughness"], mc["specular"], vertex_color=None)
    hsr.register_maps(b, mat, imgs)
    hair_mesh.finish(b, obj, bm, [mat])
    obj.visible_shadow = cfg.get("cast_shadow", True)
    me = obj.data
    att = me.attributes.new("fh_root", "FLOAT_VECTOR", "POINT")
    if len(vroots) != len(me.vertices):
        raise RuntimeError(f"fh_root: {len(vroots)} roots for {len(me.vertices)} vertices")
    att.data.foreach_set("vector", [c for r_ in vroots for c in r_])
    nudged, culled_tan = facial_hair.guard_tangents(obj, me.uv_layers[0].name, cfg.get("tangent_nudge_m", 2e-4),
                                                    cfg.get("tangent_passes", 2))
    covs = np.array(covs) if covs else np.zeros(1)
    return {"path": "cards (T9)", "cards": made, "card_tris": tris, "centres": len(centres),
            "skipped": skipped, "atlas": [W, H], "cell": [cw, ch], "pushed_verts": pushed,
            "card_len_mm_p50": round(float(np.median(lens)) * 1e3, 1) if lens else None,
            "mm_per_px_along_p50": round(float(np.median(lens)) * 1e3 / ch, 3) if lens else None,
            "members_p10_p50_p90": [int(np.percentile(members_n, q)) for q in (10, 50, 90)] if members_n else None,
            "cell_cov_p10_p50": [round(float(np.percentile(covs, q)), 3) for q in (10, 50)],
            "empty_cells": int((covs < 0.01).sum()),
            "tangent_nudged_loops": nudged, "tangent_culled_faces": culled_tan,
            "atlas_fill_linear": [round(float(x), 6) for x in fill],
            "clipped_cards": clipped, "ribbons": rib_stats}


def lip_ribbon_cards(bm, uv, uv2, dl, atl, made, ncols, nrows, cw, ch, groom, sid_all, rib, weights_of, cfg,
                     skin_bvh, vroots):
    """T21 (checkpoint-3 T21 item 1): the moustache's overhang as cards laid ALONG the upper lip, not one card
    per clump hanging over it (T11's 280 lip-edge cards read as a fringe of dark spikes). rib (hair_beard.
    lip_ribbon): per x column along the lip (x, the vermilion top z_b, the overhang, the ribbon's surface y per
    row) and the lip-edge strands to draw. Each card spans `seg_cols` columns; its cell holds the strands that
    cross it, drawn across the card (the cell's u: top -> lip edge, v: along the lip), so its alpha runs across
    the card: a fade-in under the clump cards above and a cross-card fade toward the lip, where only the
    strand tips are left. Two layers, the second offset half a card and a little further out."""
    pts, rgb = groom["pts"], groom["rgb"]
    s_alpha, s_px = groom.get("alpha"), groom.get("px")
    rad_ref = float(np.median(groom["radius"]))
    X, ZT, H, Y = rib["x"], rib["z_top"], rib["height"], rib["y"]     # (nx,), (nx,), (nx,), (nx, nv)
    nv = Y.shape[1]
    tv = np.linspace(0, 1, nv)
    sel = rib["strands"]
    seg = rib["seg_cols"]
    a_in, a_out0, a_out1 = rib["alpha_in"], rib["alpha_out"][0], rib["alpha_out"][1]
    ss, jit, rc = cfg["ss"], math.radians(cfg.get("flow_jitter_deg", 6.0)), cfg["roughness"]
    # strand points: their t across the ribbon at their own x, their s along it
    P = pts[sel]
    sl = np.concatenate([np.zeros((len(sel), 1)), np.cumsum(np.linalg.norm(np.diff(P, axis=1), axis=2), 1)], 1)
    s_all = sl / np.maximum(sl[:, -1:], 1e-9)
    zt = np.interp(P[..., 0], X, ZT)
    hh = np.interp(P[..., 0], X, H)
    T_all = (zt - P[..., 2]) / np.maximum(hh, 1e-6)
    cards = tris = 0
    starts = []
    for layer in range(rib["layers"]):
        off = (seg // 2) * layer
        i0 = -off if layer else 0
        while i0 < len(X) - 1:
            a, b_ = max(i0, 0), min(i0 + seg, len(X) - 1)
            if b_ - a >= 2:
                starts.append((layer, a, b_))
            i0 += seg - rib["overlap_cols"]
    for layer, a, b_ in starts:
        if made + cards >= ncols * nrows:
            break
        x0, x1 = X[a], X[b_]
        cell = hsr.Cell(cw, ch, ss)
        inx = ((P[..., 0] >= x0 - 0.001) & (P[..., 0] <= x1 + 0.001)).any(1) & ((T_all > -0.1) & (T_all < 1.1)).any(1)
        idx = np.flatnonzero(inx)
        # back to front: the strands further from the skin (lower y = in front) last
        order = idx[np.argsort(-P[idx][:, :, 1].mean(1), kind="stable")]
        for i in order:
            gi = sel[i]
            sx = (P[i, :, 0] - x0) / (x1 - x0)
            t = T_all[i]
            s_ = s_all[i]
            tip = np.clip((s_ - (1 - rib["tip_fade"])) / rib["tip_fade"], 0, 1)
            w = cfg["strand_px"] * float(np.clip(groom["radius"][gi] / rad_ref, 0.5, 1.6))
            if s_px is not None:
                w *= float(s_px[gi])
            rad = w + (cfg["tip_px"] - w) * tip
            alpha = (1.0 - (1.0 - cfg["tip_alpha"]) * tip) * float(s_alpha[gi] if s_alpha is not None else 1.0)
            # the cross-card alpha: in under the clump cards, out toward the lip edge
            alpha = alpha * np.clip(t / a_in, 0, 1) * (1.0 - (1.0 - rib["alpha_floor"]) * np.clip((t - a_out0) / (a_out1 - a_out0), 0, 1))
            sid = float(sid_all[gi])
            cell.draw(t * cw, sx * ch, rad, alpha, s_, np.zeros_like(t), rgb[gi], sid,
                      rc["base"] + rc["jitter"] * (2 * sid - 1), jit)
        r = cell.resolve()
        slot = made + cards
        u0, v0, u1, v1 = atl.put((slot % ncols) * cw, (slot // ncols) * ch, r, cfg["ao"])
        # the grid: columns a..b_ along the lip, nv rows across (top -> lip edge)
        push = rib["layer_push_m"] * layer
        grid = []
        cx = 0.5 * (x0 + x1)
        wts = weights_of(np.array([cx, float(np.interp(cx, X, Y[:, 0])), float(np.interp(cx, X, ZT))]))
        for ci in range(a, b_ + 1):
            row = []
            for q in range(nv):
                p = Vector((X[ci], Y[ci, q] - push, ZT[ci] - tv[q] * H[ci]))
                vv = bm.verts.new(p)
                for g_, w_ in wts.items():
                    vv[dl][g_] = w_
                vroots.append(Vector((X[ci], Y[ci, 0], ZT[ci])))
                row.append(vv)
            grid.append(row)
        ncol = b_ - a
        for ci in range(ncol):
            for q in range(nv - 1):
                quad = (grid[ci][q], grid[ci + 1][q], grid[ci + 1][q + 1], grid[ci][q + 1])
                f = bm.faces.new(quad)
                f.material_index = 0
                for loop, (cc, qq) in zip(f.loops, ((ci, q), (ci + 1, q), (ci + 1, q + 1), (ci, q + 1))):
                    sx, tq = cc / ncol, tv[qq]
                    loop[uv].uv = (u0 + (u1 - u0) * tq, v0 + (v1 - v0) * sx)
                    loop[uv2].uv = (tq, 1.0)
                tris += 2
        cards += 1
    return {"cards": cards, "tris": tris, "columns": int(len(X)), "strands": int(len(sel)),
            "x_span_mm": round(float(X[-1] - X[0]) * 1e3, 1) if len(X) else 0,
            "height_mm_p50": round(float(np.median(H)) * 1e3, 1) if len(H) else 0}
