"""Eyelashes: a strand groom (hero) and two baked strips per eye (game),
replacing MPFB's eyelash proxy.

Roots: the lid margins are found on the final skin by casting rays along
+y across each eye (lid_margins): the highest and lowest rays that reach the
eyeball before the skin bound the opening, and the skin hit just past them
is the margin. The MPFB eyelash proxy (fitted by head.add_parts) only gives
the base lash direction per lid; snapping its roots to the skin put the
upper lashes behind the eyeball once the lids were reshaped. The proxy is
then dropped from the export (the config switch is `hair.lashes`; null keeps
the MPFB lashes).

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


def eye_mesh(b):
    ms = [o for o in b.meshes() if "eyes_hq" in o.name] or [o for o in b.meshes() if "low-poly" in o.name]
    return ms[0] if ms else None


def lid_margins(eye_obj, centres, skin_bvh, cfg):
    """The lid margins seen from the front: per column of rays along +y
    across each eye, the highest and lowest rays that reach the eyeball
    before the skin bound the opening; the skin hit just past each is the
    lid margin. Per (side, lid): roots (n, 3), inner corner first. Follows
    any reshaping of the lids, unlike the fitted proxy."""
    from .hair_frame import world_bvh
    ebvh = world_bvh([eye_obj])
    step = cfg["margin_step_m"]
    out = {}
    for side, c in centres.items():
        y0 = c[1] - 0.06
        cols = {"upper": [], "lower": []}
        xs = np.arange(-0.02, 0.02, step)
        zs = np.arange(-0.012, 0.012, step * 0.5)
        for dx in xs:
            vis = []
            for dz in zs:
                o = Vector((c[0] + dx, y0, c[2] + dz))
                he = ebvh.ray_cast(o, Vector((0, 1, 0)), 0.1)
                hs = skin_bvh.ray_cast(o, Vector((0, 1, 0)), 0.1)
                vis.append(he[0] is not None and (hs[0] is None or he[3] < hs[3]))
            vis = np.array(vis)
            if not vis.any():
                continue
            iz = np.flatnonzero(vis)
            if (iz[-1] - iz[0]) * step * 0.5 < cfg["margin_min_open_m"]:
                continue
            for lid, k in (("upper", min(iz[-1] + 1, len(zs) - 1)), ("lower", max(iz[0] - 1, 0))):
                o = Vector((c[0] + dx, y0, c[2] + zs[k]))
                hs = skin_bvh.ray_cast(o, Vector((0, 1, 0)), 0.1)
                if hs[0] is not None:
                    # a little into the margin, behind its front edge
                    cols[lid].append(np.array(hs[0][:]) + np.array([0, cfg["margin_in_m"], 0]))
        for lid, pts in cols.items():
            if len(pts) < 3:
                continue
            pts = np.array(pts)
            pts = pts[np.argsort(pts[:, 0] * side)]  # inner (nose side) first
            out[(side, lid)] = pts
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
    eo = eye_mesh(b)
    margins = lid_margins(eo, eyes, frame.skin_bvh, cfg) if eo is not None and cfg.get("margin_step_m") else {}
    for key, roots in margins.items():
        if key in lines:
            lines[key] = (roots,) + tuple(lines[key][1:])
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
    # T18: the upper lid's lashes in two rows (a front row and a shorter back row, row2_*), each
    # with its own game strip; atlas slots: one per strip
    rows2 = cfg.get("row2_frac", 0.0) > 0
    nslots = sum(2 if (lid == "upper" and rows2) else 1 for _, lid in strips)
    sh = H // nslots
    slot = 0
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
        # T18: the back row (upper lid): roots behind the front row on the margin, shorter, more curl
        row = np.zeros(n, int)
        if lid == "upper" and rows2:
            row = (rng.uniform(0, 1, n) < cfg["row2_frac"]).astype(int)
            r = r + np.array([0.0, cfg["row2_back_m"], 0.0]) * row[:, None]
            L = L * np.where(row == 1, cfg["row2_length"], 1.0)
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
        curl = math.radians(lc["curl_deg"]) * rng.uniform(0.7, 1.2, n) * np.where(row == 1, cfg.get("row2_curl", 1.0), 1.0)
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
        # kept out of the skin (a hooded upper lid would otherwise swallow the
        # upturned tips) before the strip is built along them
        beard_groom.collide(pts, frame.skin_bvh, np.concatenate([[0.0], np.full(k - 1, cfg["gap_m"])]))
        rad = (np.linspace(1.0, hero["tip_radius"], k)[None, :] * rng.uniform(*hero["radius_m"], n)[:, None]
               * lc.get("radius_scale", 1.0))
        mel = np.clip(cfg["melanin"] + rng.normal(0, 0.01, n), 0, 1)
        red = np.full(n, cfg["redness"])
        all_pts.append(pts)
        all_rad.append(rad)
        all_mel.append(mel)
        all_red.append(red)
        stats["lashes"][f"{'l' if side > 0 else 'r'}_{lid}"] = int(n)
        # --- game strip(s): columns along the lid, rows root / mid / tip; one per lash row (T18) ---
        all_n, all_u, all_pts_k, all_tang = n, u, pts, tang
        for rsel in ((0, 1) if (lid == "upper" and rows2) else (0,)):
            pick = row == rsel
            n, u, pts, tang = int(pick.sum()), all_u[pick], all_pts_k[pick], all_tang[pick]
            if n < 4:
                continue
            back = np.array([0.0, cfg.get("row2_back_m", 0.0) * rsel, 0.0])
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
                grid[0, ci] = line[ri0] + back
                # A ribbon along lashes that leave the lid forward is seen edge-on
                # from the front; card lashes are tilted toward the viewer (the
                # forward run is shortened), the standard cheat.
                for ri in range(1, rows):
                    off = grid[ri, ci] - grid[0, ci]
                    # not at the outer corner: there the lashes fan out of a
                    # recess under the hood, and a flattened strip sinks into it
                    s0 = lc.get("strip_forward_scale", 1.0)
                    off[1] *= s0 + (1 - s0) * min(max((cuv - 0.6) / 0.4, 0.0), 1.0)
                    q = Vector(grid[0, ci] + off)
                    loc, nrm, _, _ = frame.skin_bvh.find_nearest(q)
                    if loc is not None and (q - loc).dot(nrm) < cfg["strip_gap_m"]:
                        q = loc + nrm * cfg["strip_gap_m"]
                    grid[ri, ci] = q[:]
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
            y0 = slot * sh
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
            # T18b: per-lid stroke radius, root darkening, value and lash line (the lower lid's: thinner,
            # lighter, no line, so at 100 % its lashes read as fine lashes, not black specks at the roots)
            rr = np.maximum(lc.get("strip_radius_px", cfg["strip_radius_px"]) * (1 - 0.7 * tt),
                            lc.get("strip_min_px", 0.5))
            col = np.array(beard_bake.linear(hair_mesh.hex_rgb(cfg["color"]))) * lc.get("strip_value", 1.0)
            rd = lc.get("strip_root_dark", 0.4)
            cc = np.tile(col, (len(tt), 1)) * (1 - rd + rd * tt)[:, None]
            canvas.lines(a_, b_, rr, cc)
            # the dark lash line along the root edge (0.3 mm)
            line_px = lc.get("lash_line_px", cfg["lash_line_px"])
            if line_px > 0:
                lx = np.linspace(pad, W - pad, 200)
                ly = np.full(200, y0 + pad + 1.0)
                canvas.lines(np.stack([lx[:-1], ly[:-1]], 1), np.stack([lx[1:], ly[1:]], 1),
                             np.full(199, line_px), np.tile(col * 0.5, (199, 1)))
            slot += 1
        n, u, pts, tang = all_n, all_u, all_pts_k, all_tang
    # hero curves: all lashes in one object (collided above), clumped
    P = np.concatenate(all_pts)
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
    # The kept .blend renders the strands (hero stage); the baked game mesh
    # stays in the GLB (the exporter ignores render visibility). Left
    # visible, its alpha shells drew over the strands as dark speckle.
    obj.hide_render = True
    if cfg.get("drop_proxy", True):
        b.export_objs.remove(proxy)
        bpy.data.objects.remove(proxy, do_unlink=True)
    stats.update({"atlas": [W, H], "proxy_dropped": cfg.get("drop_proxy", True)})
    b.notes["lashes"] = stats
    return obj
