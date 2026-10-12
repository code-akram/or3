"""Eyebrows as shell-textured hair (facial_hair.py), replacing MPFB's
alpha-card eyebrow proxy.

The stopgap proxy is still fitted by MPFB (head.parts), because it is the
best landmark we have: it follows the head track's brow edits exactly. Its
vertices, snapped to the skin, give each brow a spine (a polyline of centre
height over x) and a half-thickness per x. The brow patch is the skin faces
within that band plus a margin; density is one along the spine and fades
toward the band's edges, the inner head is heavier and the tail thins out.
Hairs lie flat (high lean), growing up and outward near the nose and
outward then slightly down along the tail, with a per-hair drift for the
slightly unruly look. The proxy is then dropped from the export.
"""

import math

import bpy
from mathutils import Vector

from . import facial_hair, hair_mesh


def _spines(brow_obj, skin_bvh, center_x, bins, hh_range):
    """Per side: list of (x, y, z_centre, half_thickness) over x bins, the
    centre and thickness smoothed across neighbouring bins and the thickness
    clamped to hh_range (m)."""
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
            # Fit z = z0 + k x over the bin, so the arch's slope doesn't count
            # as thickness; the residual spread is the brow's half-height.
            n = len(sel)
            mx, mz = sum(p.x for p in sel) / n, sum(p.z for p in sel) / n
            sxx = sum((p.x - mx) ** 2 for p in sel)
            k = sum((p.x - mx) * (p.z - mz) for p in sel) / sxx if sxx > 1e-12 else 0.0
            res = [p.z - (mz + k * (p.x - mx)) for p in sel]
            xc = (a + c) / 2
            spine.append((xc, sum(p.y for p in sel) / n, mz + k * (xc - mx),
                          (max(res) - min(res)) / 2))
        sm = []
        for i, s in enumerate(spine):
            nb = spine[max(i - 1, 0):i + 2]
            zc = sum(q[2] for q in nb) / len(nb)
            hh = min(max(sum(q[3] for q in nb) / len(nb), hh_range[0]), hh_range[1])
            sm.append((s[0], s[1], zc, hh))
        out[side] = (sm, x0, x1)
    return out


def _sample(spine, x):
    """(y, z_centre, half_thickness) at x, linear along the spine."""
    if x <= spine[0][0]:
        return spine[0][1:]
    if x >= spine[-1][0]:
        return spine[-1][1:]
    for a, c in zip(spine, spine[1:]):
        if a[0] <= x <= c[0]:
            t = (x - a[0]) / max(c[0] - a[0], 1e-6)
            return tuple(a[k] + (c[k] - a[k]) * t for k in (1, 2, 3))
    return spine[-1][1:]


def smoothstep(e0, e1, x):
    t = min(max((x - e0) / (e1 - e0), 0.0), 1.0)
    return t * t * (3 - 2 * t)


def build(b, frame, cfg):
    proxy = next((o for o in b.meshes() if cfg["proxy"] in o.name), None)
    if proxy is None:
        return None
    body = frame.body
    cx = frame.center.x
    spines = _spines(proxy, frame.skin_bvh, cx, cfg["bins"], cfg["thickness_range_m"])
    mw = body.matrix_world
    head_i = body.vertex_groups["head"].index
    margin, hh_scale = cfg["margin_m"], cfg["thickness_scale"]
    info = {}  # body vertex index -> (side, dz_norm, along)
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
        y, zc, hh = _sample(spine, p.x)
        hh = hh * hh_scale + cfg["thickness_add_m"]
        if abs(p.y - y) > cfg["depth_tol_m"] or abs(p.z - zc) > hh + margin:
            continue
        # along: 0 at the inner end (nose), 1 at the tail
        inner, outer = (x1, x0) if side < 0 else (x0, x1)
        along = (p.x - inner) / (outer - inner)
        info[v.index] = (side, (p.z - zc) / hh, along, hh)
    obj, bm = hair_mesh.shell_from_body(b, body, set(info), "Human.brows_export")
    idx = bm.verts.layers.int.get("src")
    bm.normal_update()
    density, short, length, comb = {}, {}, {}, {}
    for v in bm.verts:
        side, dz, along, hh = info[v[idx]]
        # dense in the core of the band, feathered to the edges; the tail thins
        edge = 1 - smoothstep(cfg["core"], 1 + margin / hh, abs(dz))
        tail = 1 - smoothstep(cfg["tail_start"], 1.0, along) * cfg["tail_thin"]
        head = 1 + cfg["head_boost"] * (1 - smoothstep(0, 0.35, along))
        density[v] = min(edge * tail * head, 1.0)
        short[v] = 0.5 + 0.5 * edge
        length[v] = cfg["length_m"] * (1 - cfg["tail_shorter"] * along)
        # Comb: outward (away from the nose), up near the inner end, a little
        # down at the tail; the upper edge hairs lean down, the lower ones up.
        up = cfg["up_inner"] * (1 - smoothstep(0, 0.5, along)) - cfg["down_tail"] * smoothstep(0.5, 1, along)
        up -= dz * cfg["edge_turn"]
        comb[v] = facial_hair.tangent(v, Vector((side * 1.0, 0, up)).normalized())
    facial_hair.smooth_field(bm, comb, cfg["smooth_iters"])
    for v in bm.verts:
        comb[v] = facial_hair.tangent(v, comb[v]) if comb[v].length > 1e-6 else Vector((1, 0, 0))
    fields = {"density": density, "short": short, "length_m": length, "comb": comb}
    base_before = sum(len(f.verts) - 2 for f in bm.faces)
    bm, fields = facial_hair.decimate_patch(obj, bm, fields, cfg["base_tris"], frame.skin_bvh)
    base_tris = sum(len(f.verts) - 2 for f in bm.faces)
    xs = [v.co.x for v in bm.verts]
    zs = [v.co.z for v in bm.verts]
    pad = 0.04
    x0, x1, z0, z1 = min(xs) - 0.005, max(xs) + 0.005, min(zs) - 0.004, max(zs) + 0.006

    def project(p):
        u = pad + (p.x - x0) / (x1 - x0) * (1 - 2 * pad)
        w = pad + (p.z - z0) / (z1 - z0) * (1 - 2 * pad)
        return (min(max(u, 0.0), 1.0), min(max(w, 0.0), 1.0))

    sh = cfg["shells"]
    nprng = __import__("numpy").random.default_rng(cfg["seed"])
    stats = facial_hair.build_shells(b, obj, bm, fields, sh, "brows", project, sh["tile"], nprng)
    b.cutouts.append("brows_export")
    # Drop the MPFB proxy: the shells replace it.
    b.export_objs.remove(proxy)
    bpy.data.objects.remove(proxy, do_unlink=True)
    stats.update({"base_tris": base_tris, "base_tris_before_decimate": base_before,
                  "proxy_dropped": cfg["proxy"],
                  "spine_bins": {str(s): len(sp[0]) for s, sp in spines.items()}})
    b.notes["brows"] = stats
    return obj
