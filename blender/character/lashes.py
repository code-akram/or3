"""Eyelashes: a strand groom (hero) and two baked strips per eye (game),
replacing MPFB's eyelash proxy.

The MPFB eyelash proxy is still fitted by head.add_parts, because it follows
the lid edits exactly; here it is only a landmark. Each of its four islands
(upper and lower lid per eye) gives a root line, the island's vertices
nearest the eyeball centre per angular bin round the eye, snapped to the
skin, and a base direction toward its farthest vertices. The proxy is then
dropped from the export (the config switch is `hair.lashes`; null keeps the
MPFB lashes).

Groom: upper 150-180 lashes per eye, 8-10 mm, longest in the outer middle,
curving up; lower 70-90, 5-6 mm, curving down (direction §2 C). Roots in two
or three ragged rows along the margin; GN clumping pulls the tips into the
small clumps real lashes form. Darker at the root (melanin + root_dark).

Game: per lid one strip (root, middle, tip rows) whose rows follow the mean
lash path, textured with the lashes drawn in strip space, a 0.3 mm dark lash
line along the root edge. Upper 7 segments, lower 5: 48 tris per eye.
"""

import math

import bmesh
import bpy
import numpy as np
from mathutils import Vector
from mathutils.kdtree import KDTree

from . import beard_bake, beard_groom, hair_mesh


def _islands(me):
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    seen, out = set(), []
    for v in bm.verts:
        if v.index in seen:
            continue
        st, comp = [v], []
        while st:
            x = st.pop()
            if x.index in seen:
                continue
            seen.add(x.index)
            comp.append(x.index)
            st += [e.other_vert(x) for e in x.link_edges]
        out.append(comp)
    bm.free()
    return out


def eye_centres(b):
    eyes = next((o for o in b.meshes() if "low-poly" in o.name or "eyes_hq" in o.name), None)
    co = np.array([(eyes.matrix_world @ v.co)[:] for v in eyes.data.vertices])
    return {1: co[co[:, 0] > 0].mean(0), -1: co[co[:, 0] < 0].mean(0)}


def lid_lines(proxy, eyes, skin_bvh, bins):
    """Per (side, 'upper'|'lower'): (roots (bins, 3), base dir (bins, 3),
    proxy length (bins,)) ordered from the inner to the outer corner."""
    mw = proxy.matrix_world
    co = np.array([(mw @ v.co)[:] for v in proxy.data.vertices])
    out = {}
    isls = [co[i] for i in _islands(proxy.data)]
    for p in isls:
        side = 1 if p[:, 0].mean() > 0 else -1
        pair = [q for q in isls if (1 if q[:, 0].mean() > 0 else -1) == side]
        # upper / lower by the two islands of this eye, not the eye mesh
        lid = "upper" if p[:, 2].mean() >= max(q[:, 2].mean() for q in pair) else "lower"
        # the eyeball centre: between the lids, behind the lid margin
        allp = np.concatenate(pair)
        e = np.array([allp[:, 0].mean(), allp[:, 1].max() + 0.008, allp[:, 2].mean()])
        d = np.linalg.norm(p - e, axis=1)
        # angle round the eye seen from the front, inner corner first
        ang = np.arctan2(p[:, 2] - e[2], (p[:, 0] - e[0]) * side)
        if lid == "upper":
            ang = np.pi - ang  # inner (nose side) first
        lo, hi = np.percentile(ang, 1), np.percentile(ang, 99)
        roots, dirs, lens = [], [], []
        for i in range(bins):
            a0 = lo + (hi - lo) * i / bins
            a1 = lo + (hi - lo) * (i + 1) / bins
            sel = (ang >= a0) & (ang <= a1)
            if sel.sum() < 2:
                continue
            q, dq = p[sel], d[sel]
            r = q[np.argmin(dq)]
            t = q[np.argmax(dq)]
            loc, _, _, _ = skin_bvh.find_nearest(Vector(r))
            r = np.array(loc[:]) if loc is not None else r
            v = t - r
            roots.append(r)
            dirs.append(v / max(np.linalg.norm(v), 1e-9))
            lens.append(np.linalg.norm(v))
        out[(side, lid)] = (np.array(roots), np.array(dirs), np.array(lens))
    return out


def resample_line(pts, n):
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    s = np.concatenate([[0], np.cumsum(seg)])
    t = np.linspace(0, s[-1], n)
    return np.stack([np.interp(t, s, pts[:, k]) for k in range(pts.shape[1])], axis=1), s[-1]


def build(b, frame, cfg):
    proxy = next((o for o in b.meshes() if cfg["proxy"] in o.name), None)
    if proxy is None:
        return None
    rng = np.random.default_rng(cfg["seed"])
    beard_groom.refit_for(b, frame)
    eyes = eye_centres(b)
    lines = lid_lines(proxy, eyes, frame.skin_bvh, cfg["bins"])
    hero = cfg["hero"]
    mat = beard_groom.hair_material("lashes_hero", hero["material"])
    body = frame.body
    bkd = KDTree(len(body.data.vertices))
    bmw = body.matrix_world
    for i, v in enumerate(body.data.vertices):
        bkd.insert(bmw @ v.co, i)
    bkd.balance()
    bones = set(bn.name for bn in b.armature().data.bones)
    gname = {g.index: g.name for g in body.vertex_groups}

    obj = bpy.data.objects.new("Human.eyelash_cards_export", bpy.data.meshes.new("eyelash_cards"))
    for c in body.users_collection:
        c.objects.link(obj)
    obj.matrix_world = body.matrix_world.copy()
    for g in body.vertex_groups:
        if g.name in bones:
            obj.vertex_groups.new(name=g.name)
    ogi = {g.name: g.index for g in obj.vertex_groups}
    bm = bmesh.new()
    dl = bm.verts.layers.deform.verify()
    uv = bm.loops.layers.uv.verify()
    W, H = cfg["atlas"]
    strips = sorted(lines)
    sh = H // len(strips)
    canvas = beard_bake.Canvas(W, H)
    vroots = []
    stats = {"lashes": {}, "strip_tris": 0}
    all_pts, all_rad, all_mel, all_red = [], [], [], []
    for si, key in enumerate(strips):
        side, lid = key
        lc = cfg[lid]
        roots, dirs, plen = lines[key]
        if len(roots) < 3:
            continue
        line, total = resample_line(roots, 64)
        dline, _ = resample_line(dirs, 64)
        dline /= np.linalg.norm(dline, axis=1, keepdims=True)
        n = lc["count"]
        u = np.sort(rng.uniform(0.02, 0.98, n))
        ui = u * 63
        i0 = np.floor(ui).astype(int).clip(0, 62)
        fr = (ui - i0)[:, None]
        r = line[i0] * (1 - fr) + line[i0 + 1] * fr
        d = dline[i0] * (1 - fr) + dline[i0 + 1] * fr
        d /= np.linalg.norm(d, axis=1, keepdims=True)
        tang = line[np.minimum(i0 + 1, 63)] - line[i0]
        tang /= np.maximum(np.linalg.norm(tang, axis=1, keepdims=True), 1e-9)
        # ragged rows: a little in/out of the margin along the base direction
        r = r + d * rng.normal(0, lc["row_jitter_m"], n)[:, None] + tang * rng.normal(0, 0.0002, n)[:, None]
        # length profile over the lid (inner .. outer), per-lash jitter
        L = np.interp(u, np.linspace(0, 1, len(lc["length_m"])), lc["length_m"]) * rng.uniform(0.8, 1.05, n)
        # curl: bend toward 'up' (upper lid: +z, lower: -z), in the plane of d and up
        up = np.array([0, 0, 1.0 if lid == "upper" else -1.0])
        # lashes leave the lid forward and slightly toward the curl side
        fwd = np.array([0, -1.0, 0])
        d0 = d * (1 - lc["forward"]) + fwd * lc["forward"]
        d0 /= np.linalg.norm(d0, axis=1, keepdims=True)
        bend_ax = up - d0 * (d0 @ up)[:, None]
        bend_ax /= np.maximum(np.linalg.norm(bend_ax, axis=1, keepdims=True), 1e-9)
        k = cfg["points"]
        s = np.linspace(0, 1, k)
        curl = math.radians(lc["curl_deg"]) * rng.uniform(0.7, 1.2, n)
        yaw = rng.normal(0, math.radians(lc["splay_deg"]), n)
        # lashes splay outward toward the outer corner
        yaw = yaw + (u - 0.3) * math.radians(lc["fan_deg"]) * side
        side_ax = np.cross(d0, bend_ax)
        pts = np.zeros((n, k, 3))
        pts[:, 0] = r
        for j in range(1, k):
            th = curl * ((j - 0.5) / (k - 1)) ** 1.5
            dirj = (d0 * np.cos(th)[:, None] + bend_ax * np.sin(th)[:, None])
            dirj = dirj * np.cos(yaw)[:, None] + side_ax * np.sin(yaw)[:, None] * side
            pts[:, j] = pts[:, j - 1] + dirj * (L / (k - 1))[:, None]
        rad = np.linspace(1.0, hero["tip_radius"], k)[None, :] * rng.uniform(*hero["radius_m"], n)[:, None]
        mel = np.clip(cfg["melanin"] + rng.normal(0, 0.01, n), 0, 1)
        red = np.full(n, cfg["redness"])
        all_pts.append(pts)
        all_rad.append(rad)
        all_mel.append(mel)
        all_red.append(red)
        stats["lashes"][f"{'l' if side > 0 else 'r'}_{lid}"] = int(n)
        # --- game strip: columns along the lid, rows root / mid / tip ---
        cols = lc["strip_cols"]
        rows = 3
        cu = np.linspace(0.0, 1.0, cols)
        grid = np.zeros((rows, cols, 3))
        for ci, cuv in enumerate(cu):
            near = np.argsort(np.abs(u - cuv))[:max(4, n // cols)]
            mean = pts[near].mean(0)
            for ri, f_ in enumerate((0.0, 0.5, 1.0)):
                grid[ri, ci] = mean[int(round(f_ * (k - 1)))]
            # the root row on the lid margin itself
            ri0 = int(np.clip(round(cuv * 63), 0, 63))
            grid[0, ci] = line[ri0]
        vs = [[None] * cols for _ in range(rows)]
        for ri in range(rows):
            for ci in range(cols):
                vv = bm.verts.new(Vector(grid[ri, ci]))
                _, bi, _ = bkd.find(Vector(line[int(np.clip(round(cu[ci] * 63), 0, 63))]))
                for e in body.data.vertices[bi].groups:
                    nm = gname.get(e.group)
                    if nm in ogi and e.weight > 0:
                        vv[dl][ogi[nm]] = e.weight
                vs[ri][ci] = vv
                vroots.append(Vector(line[int(np.clip(round(cu[ci] * 63), 0, 63))]))
        y0 = si * sh
        pad = 2
        for ri in range(rows - 1):
            for ci in range(cols - 1):
                f = bm.faces.new((vs[ri][ci], vs[ri][ci + 1], vs[ri + 1][ci + 1], vs[ri + 1][ci]))
                for loop, (a, c_) in zip(f.loops, ((ci, ri), (ci + 1, ri), (ci + 1, ri + 1), (ci, ri + 1))):
                    loop[uv].uv = ((pad + a / (cols - 1) * (W - 2 * pad)) / W,
                                   (y0 + pad + c_ / (rows - 1) * (sh - 2 * pad)) / H)
                stats["strip_tris"] += 2
        # texture: lash j's point i at (u_j + lateral drift, i / (k-1))
        lat = ((pts - pts[:, :1]) * tang[:, None, :]).sum(2) / max(total, 1e-6)
        U = (u[:, None] + lat).clip(0, 1)
        V = np.tile(s, (n, 1))
        px = pad + U * (W - 2 * pad)
        py = y0 + pad + V * (sh - 2 * pad)
        a_ = np.stack([px[:, :-1], py[:, :-1]], -1).reshape(-1, 2)
        b_ = np.stack([px[:, 1:], py[:, 1:]], -1).reshape(-1, 2)
        tt = np.tile((np.arange(k - 1) + 0.5) / (k - 1), n)
        rr = np.maximum(cfg["strip_radius_px"] * (1 - 0.7 * tt), 0.5)
        col = np.array(beard_bake.linear(hair_mesh.hex_rgb(cfg["color"])))
        cc = np.tile(col, (len(tt), 1)) * (0.6 + 0.4 * tt)[:, None]
        canvas.lines(a_, b_, rr, cc)
        # the dark lash line along the root edge (0.3 mm)
        lx = np.linspace(pad, W - pad, 200)
        ly = np.full(200, y0 + pad + 1.0)
        canvas.lines(np.stack([lx[:-1], ly[:-1]], 1), np.stack([lx[1:], ly[1:]], 1),
                     np.full(199, cfg["lash_line_px"]), np.tile(col * 0.5, (199, 1)))
    # hero curves: all lashes in one object, kept out of the skin (a hooded
    # upper lid would otherwise swallow the upturned tips), clumped
    P = np.concatenate(all_pts)
    k = cfg["points"]
    beard_groom.collide(P, frame.skin_bvh, np.concatenate([[0.0], np.full(k - 1, cfg["gap_m"])]))
    o = beard_groom.make_curves("lashes_hero", P, np.concatenate(all_rad),
                                {"melanin": np.concatenate(all_mel), "redness": np.concatenate(all_red),
                                 "clump": np.full(len(P), cfg["clump"]), "frizz": np.zeros(len(P))}, mat)
    beard_groom.clump_frizz(o, hero, cfg["seed"])
    beard_groom.bind(b, o, "head")
    b.facial_refit.add("curves", o)
    img = beard_bake.make_image("eyelash_cards_atlas", canvas.rgba(np.array(beard_bake.linear(
        hair_mesh.hex_rgb(cfg["color"])))))
    m = hair_mesh.material("eyelash_cards", "#ffffff", 0.5, img, 0.3, wrap=False)
    hair_mesh.finish(b, obj, bm, [m])
    me = obj.data
    att = me.attributes.new("fh_root", "FLOAT_VECTOR", "POINT")
    att.data.foreach_set("vector", [c for r in vroots for c in r])
    from . import facial_hair
    stats["tangent_guard"] = facial_hair.guard_tangents(obj, me.uv_layers[0].name, 2e-4, 2)
    b.facial_refit.add("mesh", obj)
    b.cutouts.append("eyelash_cards")
    if cfg.get("drop_proxy", True):
        b.export_objs.remove(proxy)
        bpy.data.objects.remove(proxy, do_unlink=True)
    stats.update({"atlas": [W, H], "proxy_dropped": cfg.get("drop_proxy", True)})
    b.notes["lashes"] = stats
    return obj
