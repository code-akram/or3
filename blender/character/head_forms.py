"""Soft-tissue forms, lid heights and intentional asymmetry on the MPFB base
mesh (m1 v2 track A; bench/m1/v2/direction.md §2 Track A and §3).

Runs in head.edit_base right after head_shape (the parametric controls and
plane groups), on the live human before any proxy is fitted. The result is a
second shape key, "head_forms" (value 1), so eyes, lashes, brows, hair, beard
and clothes all fit to the final surface, and export.bake_targets bakes it.

What it adds (all in head.forms; mm amplitudes; null or 0 disables a term):

  tissue   mirrored soft tissue along the surface normal: malar fat pad,
           tear trough, lower-lid bag, nasolabial fold (deep at the alar,
           fading to the mouth corner, with the cheek mass overhanging it),
           marionette crease, mentalis pad and labiomental fold, a temporal
           hollow and a soft zygomatic arch; a rounded brow shelf (the
           supraorbital roll brought forward) over a slight upper-orbit
           hollow, so a high key leaves the eye band in shadow (look-spec
           §0, the heavy brow) without v1's hard planar shelf.
  lids     upper and lower lids rotated about the eyeball centre (the eye-
           helper sphere), so the lid margin slides on the eye instead of
           cutting into it; the lash helpers follow. Signed mm at the margin:
           + raises the lid. Per side (l = character's left, +x).
  asym     intentional, seeded asymmetry: brow height, a nasal dorsum
           deviation at the bony bridge (an old break), mouth corners, ear
           height and a protruding helix. `seed` and `jitter` re-roll the
           amplitudes (jitter 0 = the exact values).

Regions use the face frame of head_shape (origin between the eye helpers,
u lateral, h up, f forward, scaled by the interpupillary distance). Helpers
are moved with the field (proxies fit to them) except the eyeballs, which
stay put. Nothing here is fitted to any person: parameters only (look-spec
§2.4).
"""

import math

import numpy as np

from . import head_shape
from .eyes_hq import fit_sphere

MM = 0.001

DEFAULTS = {
    "tissue": {
        "malar_pad_mm": 2.0, "tear_trough_mm": 1.2, "lid_bag_mm": 0.8,
        "nasolabial_mm": 1.5, "nasolabial_end_mm": 0.3, "nasolabial_overhang_mm": 0.8,
        "marionette_mm": 0.5, "mentalis_mm": 0.8, "labiomental_mm": 0.8,
        "temple_hollow_mm": 0.0, "zygomatic_arch_mm": 0.0,
        "brow_shelf_mm": 0.0, "orbit_hollow_mm": 0.0,
    },
    "lids": {"upper_l_mm": 0.0, "upper_r_mm": 0.0, "lower_l_mm": 0.0, "lower_r_mm": 0.0},
    "asym": {
        "seed": 0, "jitter": 0.0,
        "brow_l_up_mm": 0.0, "dorsum_dev_mm": 0.0, "mouth_corners_down_mm": 0.0,
        "mouth_l_down_mm": 0.0, "ear_l_down_mm": 0.0, "ear_top_out_mm": 0.0,
    },
}


def _cfg(cfg):
    out = {}
    for k, d in DEFAULTS.items():
        out[k] = dict(d)
        out[k].update((cfg or {}).get(k) or {})
    return out


def vertex_normals(obj, co):
    """Area-weighted vertex normals of the mesh at coordinates co (n, 3)."""
    me = obj.data
    nl = len(me.loops)
    lv = np.empty(nl, np.int64)
    me.loops.foreach_get("vertex_index", lv)
    np_ = len(me.polygons)
    ls = np.empty(np_, np.int64)
    lt = np.empty(np_, np.int64)
    me.polygons.foreach_get("loop_start", ls)
    me.polygons.foreach_get("loop_total", lt)
    poly_of = np.repeat(np.arange(np_), lt)
    k = np.arange(nl) - ls[poly_of]
    nxt = ls[poly_of] + (k + 1) % lt[poly_of]
    cr = np.cross(co[lv], co[lv[nxt]])
    fn = np.add.reduceat(cr, ls, axis=0)          # Newell normal x 2 area
    vn = np.zeros_like(co)
    np.add.at(vn, lv, fn[poly_of])
    vn /= np.maximum(np.linalg.norm(vn, axis=1, keepdims=True), 1e-12)
    return vn


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def gauss(x, w):
    return np.exp(-0.5 * (x / w) ** 2)


def polyline_dist(a, b, pts):
    """Distance from (a, b) to the polyline pts [(a, b), ...] and the arc
    parameter 0..1 of the closest point."""
    pts = np.asarray(pts, dtype=np.float64)
    d = np.full(a.shape, np.inf)
    tt = np.zeros(a.shape)
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    total, acc = seg.sum(), 0.0
    for (p0, p1), L in zip(zip(pts[:-1], pts[1:]), seg):
        e = p1 - p0
        t = np.clip(((a - p0[0]) * e[0] + (b - p0[1]) * e[1]) / max(L * L, 1e-12), 0, 1)
        dd = np.hypot(a - (p0[0] + t * e[0]), b - (p0[1] + t * e[1]))
        closer = dd < d
        d = np.where(closer, dd, d)
        tt = np.where(closer, (acc + t * L) / total, tt)
        acc += L
    return d, tt


def tissue(fr, t):
    """Mirrored soft tissue: displacement along the normal (metres, + = out)."""
    u, h, f = fr.u, fr.h, fr.f
    out = np.zeros(len(u))
    front = smoothstep(-0.03, 0.0, f)
    # malar fat pad: the cheek mound under the zygion, above the hollow
    out += t["malar_pad_mm"] * MM * gauss(u - 0.040, 0.013) * gauss(h + 0.030, 0.011) * front
    # tear trough: inner canthus down and out along the infraorbital rim,
    # shallow past the mid-pupil line
    d, tt = polyline_dist(u, h, [(0.018, -0.012), (0.024, -0.019), (0.031, -0.023), (0.042, -0.022)])
    out -= t["tear_trough_mm"] * MM * gauss(d, 0.0028) * smoothstep(0.0, 0.2, tt) \
        * (1 - 0.7 * smoothstep(0.4, 1.0, tt)) * front
    # lower-lid bag: just above the trough
    out += t["lid_bag_mm"] * MM * gauss(u - 0.028, 0.008) * gauss(h + 0.0145, 0.0035) * front
    # nasolabial fold: groove from the alar crease to beside the mouth corner,
    # the cheek mass overhanging it on the lateral side
    pts = [(0.017, -0.036), (0.022, -0.048), (0.027, -0.060), (0.030, -0.072), (0.031, -0.080)]
    d, tt = polyline_dist(u, h, pts)
    depth = (t["nasolabial_mm"] + (t["nasolabial_end_mm"] - t["nasolabial_mm"]) * tt) * MM
    fade = smoothstep(0.0, 0.08, tt) * (1 - smoothstep(0.85, 1.0, tt))
    # lateral side: distance along +u from the line ~ (u - u_line)
    u_line = np.interp(-h, [-p[1] for p in pts], [p[0] for p in pts])
    lateral = u - u_line
    out -= depth * gauss(d, 0.0025) * fade * front
    out += t["nasolabial_overhang_mm"] * MM * gauss(lateral - 0.006, 0.005) * gauss(d, 0.009) * fade * front \
        * (1 - smoothstep(0.6, 1.0, tt))
    # marionette crease: from the mouth corner down and slightly out
    d, tt = polyline_dist(u, h, [(0.027, -0.078), (0.029, -0.090), (0.031, -0.100)])
    out -= t["marionette_mm"] * MM * gauss(d, 0.002) * np.sin(np.pi * tt) ** 0.5 * front
    # mentalis pad and the labiomental fold above it
    out += t["mentalis_mm"] * MM * gauss(u, 0.011) * gauss(h + 0.105, 0.008) * front
    out -= t["labiomental_mm"] * MM * gauss(u, 0.012) * gauss(h + 0.091, 0.0025) * front
    # temporal hollow and a soft zygomatic arch (mostly under the hair)
    out -= t["temple_hollow_mm"] * MM * gauss(u - 0.060, 0.008) * gauss(h - 0.015, 0.014) * gauss(f + 0.02, 0.02)
    out += t["zygomatic_arch_mm"] * MM * gauss(h + 0.012, 0.004) * smoothstep(0.050, 0.058, u) * gauss(f + 0.03, 0.02)
    # brow shelf: the supraorbital roll forward, a soft band fading at the
    # glabella and past the lateral orbital rim
    lat = smoothstep(0.004, 0.013, u) * (1 - smoothstep(0.044, 0.056, u))
    out += t.get("brow_shelf_mm", 0.0) * MM * gauss(h - 0.017, 0.0055) * lat * front
    # upper-orbit hollow: the sulcus between the lid fold and the shelf
    out -= t.get("orbit_hollow_mm", 0.0) * MM * gauss(u - 0.027, 0.010) * gauss(h - 0.0085, 0.0035) * front
    return out


def lids(obj, co, fr, cfg, eye_c):
    """Rotate the lids about each eyeball centre (around the lateral axis)."""
    out = co.copy()
    eye_v = (head_shape._group_weights(obj, "helper-l-eye") > 0) | (head_shape._group_weights(obj, "helper-r-eye") > 0)
    for key, side in (("l", 1.0), ("r", -1.0)):
        up, lo = cfg[f"upper_{key}_mm"], cfg[f"lower_{key}_mm"]
        if not up and not lo:
            continue
        c, R = eye_c[key]
        d = co - c
        lat = d[:, 0] * side                  # + toward the temple
        r = np.linalg.norm(d, axis=1)
        s = fr.s
        w_lat = np.clip(1 - ((lat - 0.002 * s) / (0.0125 * s)) ** 2, 0, 1) ** 1.5
        w_r = 1 - smoothstep(R + 0.004 * s, R + 0.010 * s, r)
        w_front = smoothstep(0.003 * s, -0.003 * s, d[:, 1])     # in front of the centre
        z_mid = -0.0022 * s                                       # middle of the aperture
        dz = d[:, 2]
        w_up = smoothstep(z_mid, z_mid + 0.0015 * s, dz) * (1 - smoothstep(0.004 * s, 0.012 * s, dz))
        w_lo = smoothstep(z_mid, z_mid - 0.0015 * s, dz) * (1 - smoothstep(-0.009 * s, -0.016 * s, dz))
        base = w_lat * w_r * w_front * ~eye_v
        ang = (up * MM / R) * w_up * base + (lo * MM / R) * w_lo * base
        # rotation "up" about the x axis through c: a point in front (y < 0)
        # rises for a negative angle in the y-z plane
        a = -ang
        y, z = d[:, 1], d[:, 2]
        ny = y * np.cos(a) - z * np.sin(a)
        nz = y * np.sin(a) + z * np.cos(a)
        sel = ang != 0
        out[sel, 1] = c[1] + ny[sel]
        out[sel, 2] = c[2] + nz[sel]
    return out


def asym(obj, co, fr, a):
    """Non-mirrored displacement (metres, object space)."""
    rng = np.random.default_rng(int(a.get("seed", 0)))
    jit = float(a.get("jitter", 0.0))

    def amp(k):
        v = float(a.get(k, 0.0))
        return v * (1 + jit * rng.standard_normal()) * MM if v else 0.0
    d = np.zeros_like(co)
    u, h, f, x = fr.u, fr.h, fr.f, fr.x
    left = fr.side > 0
    # brow height, character's left
    v = amp("brow_l_up_mm")
    if v:
        w = gauss(u - 0.030, 0.016) * gauss(h - 0.020, 0.012) * smoothstep(-0.02, 0.0, f) * left
        d[:, 2] += v * w
    # dorsum deviation toward the character's right (-x), peaking at the
    # bony bridge, back to the midline at the tip and at the nasion
    v = amp("dorsum_dev_mm")
    if v:
        w = gauss(u, 0.014) * gauss(h + 0.019, 0.010) * smoothstep(0.012, 0.03, f)
        d[:, 0] -= v * w
    # mouth corners down (both), plus the left one further
    lips_w = head_shape._group_weights(obj, "lips")
    lp = co[lips_w > 0]
    if len(lp):
        corner_u = (np.abs(lp[:, 0] - fr.origin[0]).max()) / fr.s
        corner_h = ((lp[:, 2].min() + lp[:, 2].max()) * 0.5 - fr.origin[2]) / fr.s
        wc = gauss(u - corner_u, 0.007) * gauss(h - corner_h, 0.007) * smoothstep(-0.02, 0.0, f)
        v = amp("mouth_corners_down_mm")
        if v:
            d[:, 2] -= v * wc
        v = amp("mouth_l_down_mm")
        if v:
            d[:, 2] -= v * wc * left
    # ears: left lower; the helix tops protrude
    ears = head_shape._group_weights(obj, "ears")
    if ears.any():
        for side in (1.0, -1.0):
            sel = (ears > 0) & (fr.side == side)
            if not sel.any():
                continue
            ec = co[sel].mean(0)
            zr = co[sel, 2].max() - co[sel, 2].min()
            near = gauss(np.linalg.norm(co - ec, axis=1), 0.022 * fr.s) * (fr.side == side)
            if side > 0:
                v = amp("ear_l_down_mm")
                if v:
                    d[:, 2] -= v * near
            v = amp("ear_top_out_mm")
            if v:
                # 0 below the ear centre, 1 at the top of the helix; only the
                # free ear (away from the skull attachment, i.e. lateral)
                t = np.clip((co[:, 2] - ec[2]) / (0.5 * zr), 0, 1)
                lat = smoothstep(0.0, 0.006, (co[:, 0] - ec[0]) * side + 0.003)
                d[:, 0] += side * v * t * lat * (ears > 0) * (fr.side == side)
    return d * fr.s


def apply(b):
    """head.edit_base hook (after head_shape.apply): 'head_forms' shape key."""
    fcfg = b.cfg["head"].get("forms")
    if not fcfg:
        return None
    c = _cfg(fcfg)
    obj = b.basemesh
    co = head_shape._mix_coords(obj)
    fr = head_shape.Frame.from_helpers(obj, co)
    eye_c = {}
    for key, g in (("l", "helper-l-eye"), ("r", "helper-r-eye")):
        p = co[head_shape._group_weights(obj, g) > 0]
        eye_c[key] = fit_sphere(p)
    nrm = vertex_normals(obj, co)
    eyes = (head_shape._group_weights(obj, "helper-l-eye") > 0) | (head_shape._group_weights(obj, "helper-r-eye") > 0)
    helpers = head_shape._group_weights(obj, "HelperGeometry") > 0
    tis = tissue(fr, c["tissue"]) * fr.s
    tis[helpers] = 0.0      # helper cubes have no meaningful normal; skin only
    edited = co + nrm * tis[:, None]
    edited = lids(obj, edited, fr, c["lids"], eye_c)
    dv = asym(obj, edited, fr, c["asym"])
    dv[eyes] = 0.0
    edited = edited + dv

    kb = obj.data.shape_keys.key_blocks
    basis = np.empty(len(co) * 3)
    kb[0].data.foreach_get("co", basis)
    key = obj.shape_key_add(name="head_forms", from_mix=False)
    key.data.foreach_set("co", (basis.reshape(-1, 3) + (edited - co)).ravel())
    key.value = 1.0
    obj.data.update()
    moved = np.linalg.norm(edited - co, axis=1)
    b.notes["head_forms"] = {"config": c, "max_move_mm": round(float(moved.max()) * 1000, 2),
                             "verts_moved_over_0.1mm": int((moved > 1e-4).sum()),
                             "eye_spheres_mm": {k: [round(float(x) * 1000, 2) for x in v[0]] + [round(v[1] * 1000, 2)]
                                                for k, v in eye_c.items()}}
    return moved
