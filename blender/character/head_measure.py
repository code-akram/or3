"""Spec landmarks (bench/m1/look-spec.md §1.1) on a nude MPFB body, plus brow overhang.

Used in two places:
  * head.add_parts calls measure_live() on the live MPFB human after the face
    parts are fitted and before any clothes exist, so the harness always gets
    the nude-body numbers the spec defines (the staged clothed body has its
    covered polygons deleted);
  * bench/m1/look_spec_landmarks.py runs measure() on a saved nude .blend.

Coordinates: metres, world space, rest pose, Z up, front = -Y. A vertex
belongs to the bone with its largest deform weight; helper and joint-cube
vertices are excluded.
"""

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

HELPERS = {"HelperGeometry", "JointCubes"}
TARGETS = {
    # key: (target, tolerance) from look-spec.md §1.2
    "stature": (1.85, 0.02),
    "heads_tall": (7.8, 0.15),
    "bideltoid": (0.56, 0.015),
    "shoulder_to_hip": (1.50, 0.04),
    "leg_ratio": (0.49, 0.01),
    "leg_to_torso": (1.49, 0.05),
    "bizygomatic": (0.140, 0.006),
    "jaw_to_cheek": (0.87, 0.03),
    "lower_face_index": (0.88, 0.04),
}
BROW_OVERHANG_MIN = 0.008  # metres; T7 redefinition (supraorbital rim ahead of the cornea apex)
# Head structure (bench/m1/v4/checkpoint-1.md §3 T7): key -> (low, high), inclusive.
RANGES = {
    "gonial_angle_deg": (115.0, 120.0),
    "eye_aperture_mm": (9.5, 11.0),
    "canthal_tilt_deg": (2.0, 4.0),
    "orbit_recess_mm": (2.0, 3.0),
    "forehead_behind_brow_mm": (3.0, None),
    "jaw_to_cheek": (0.84, 0.88),
}
# Nose caricature guard (face C, bench/m1/head.md §8): dorsal hump <= 2.5 mm
# over the nasion-pronasale chord; projection/length 0.60 +- 0.10 (the
# stock MPFB head is 0.63; a hooked, drooping nose reads > 0.75).
NOSE_HUMP_MAX = 2.5
NOSE_PROJ_RATIO = (0.60, 0.10)


def _rest_coords(obj):
    """World coordinates of obj's own vertices (shape-key mix, rest pose),
    one per original vertex. Modifiers are bypassed: a MASK modifier would
    drop vertices and break the index mapping, and the armature is at rest."""
    saved = [(m, m.show_viewport) for m in obj.modifiers]
    for m, _ in saved:
        m.show_viewport = False
    try:
        dg = bpy.context.evaluated_depsgraph_get()
        dg.update()
        ev = obj.evaluated_get(dg)
        me = ev.to_mesh()
        mw = obj.matrix_world
        co = [mw @ v.co for v in me.vertices]
        ev.to_mesh_clear()
    finally:
        for m, show in saved:
            m.show_viewport = show
    return co


def _dominant_bones(obj, bones):
    groups = {g.index: g.name for g in obj.vertex_groups}
    out = []
    for v in obj.data.vertices:
        if any(groups.get(g.group) in HELPERS and g.weight > 0 for g in v.groups):
            out.append(None)
            continue
        best, bw = None, 0.0
        for g in v.groups:
            n = groups.get(g.group)
            if n in bones and g.weight > bw:
                best, bw = n, g.weight
        out.append(best or "")
    return out


def measure(arm, body, eyes, emb=None):
    """Spec landmarks. arm: armature, body: MPFB base mesh (nude, full
    topology), eyes: the fitted eye proxy or None, emb: the MediaPipe landmark embedding on the
    base mesh (head_sculpt; tri_verts + bary) for the landmark-based measures. Returns a flat
    dict."""
    bones = set(arm.data.bones.keys())
    co = _rest_coords(body)
    lm = None
    if emb is not None:
        C = np.array([p[:] for p in co])
        lm = np.einsum("lk,lkd->ld", emb["bary"], C[emb["tri_verts"]])
    dom = _dominant_bones(body, bones)
    V = [(p, b) for p, b in zip(co, dom) if b is not None]
    mw = arm.matrix_world

    def bone_head(name):
        return mw @ arm.data.bones[name].head_local

    def along(p, bone):
        bn = arm.data.bones[bone]
        h, t = mw @ bn.head_local, mw @ bn.tail_local
        return (p - h).dot((t - h).normalized())

    zs = [p.z for p, _ in V]
    m = {}
    floor = min(min(zs), 0.0)
    m["stature"] = max(zs) - floor
    head_v = [p for p, b in V if b == "head"]
    head_y = bone_head("head").y

    eye_co = _rest_coords(eyes) if eyes is not None else []
    if eye_co:
        ez = sum(p.z for p in eye_co) / len(eye_co)
    else:
        ez = bone_head("head").z + 0.04
    mid = [p for p, b in V if abs(p.x) < 0.006 and p.y < head_y and p.z > ez - 0.25]
    pog = min((p for p in mid if ez - 0.15 < p.z < ez - 0.08), key=lambda p: p.y)
    chin = min((p for p in mid if p.y < pog.y + 0.025 and p.z <= pog.z), key=lambda p: p.z)
    m["menton_z"] = chin.z
    m["head_height"] = max(zs) - chin.z
    m["heads_tall"] = m["stature"] / m["head_height"]

    delt = [p for p, b in V if b in ("upperarm_l", "upperarm_r", "clavicle_l", "clavicle_r")
            and along(p, "upperarm_l" if p.x > 0 else "upperarm_r") < 0.06]
    m["bideltoid"] = max(p.x for p in delt) - min(p.x for p in delt)
    hip_z = bone_head("thigh_l").z
    hips = [p for p, b in V if b in ("pelvis", "thigh_l", "thigh_r", "spine_01")
            and hip_z - 0.10 < p.z < hip_z + 0.02]
    if not hips:
        raise RuntimeError("no hip vertices: measure a nude body (covered polygons deleted?)")
    m["hip_breadth"] = max(p.x for p in hips) - min(p.x for p in hips)
    m["shoulder_to_hip"] = m["bideltoid"] / m["hip_breadth"]
    m["biacromial_joints"] = bone_head("upperarm_l").x - bone_head("upperarm_r").x

    crotch = min((p for p, b in V if abs(p.x) < 0.006 and 0.5 < p.z < hip_z), key=lambda p: p.z)
    m["crotch_height"] = crotch.z
    m["leg_ratio"] = m["crotch_height"] / m["stature"]
    m["suprasternale_height"] = bone_head("clavicle_l").z
    m["torso_length"] = m["suprasternale_height"] - m["crotch_height"]
    m["leg_to_torso"] = m["crotch_height"] / m["torso_length"]

    if eye_co:
        m["eye_height"] = ez

        def width_at(frac, front_of, band=0.006):
            z = chin.z + frac * (ez - chin.z)
            pts = [p for p in head_v if abs(p.z - z) < band and p.y < head_y - front_of]
            return (max(p.x for p in pts) - min(p.x for p in pts)) if pts else float("nan")

        m["bizygomatic"] = max(width_at(f, 0.05) for f in (0.80, 0.85, 0.9))
        m["bigonial"] = width_at(0.30, 0.0)
        m["jaw_to_cheek"] = m["bigonial"] / m["bizygomatic"]
        m["eye_menton"] = ez - chin.z
        m["lower_face_index"] = m["eye_menton"] / m["bizygomatic"]

        # Nose profile (face-C caricature guard, bench/m1/head.md §8): nasion =
        # most recessed midline point from eye level to 25 mm above it;
        # pronasale = most forward midline point 10-60 mm below eye level;
        # hump = largest forward deviation of the dorsum from the nasion-
        # pronasale chord (y-z plane); projection and length from the same two.
        nas_c = [p for p in mid if ez - 0.005 < p.z < ez + 0.025]
        prn_c = [p for p in mid if ez - 0.060 < p.z < ez - 0.010]
        if nas_c and prn_c:
            nas = max(nas_c, key=lambda p: p.y)
            prn = min(prn_c, key=lambda p: p.y)
            chord = Vector((prn.y - nas.y, prn.z - nas.z))
            n2 = Vector((-chord.y, chord.x)).normalized()      # in-plane normal
            if n2.x > 0:                                       # pointing forward (-y) means n2.x < 0
                n2 = -n2
            hump = 0.0
            for p in mid:
                if prn.z < p.z < nas.z:
                    d = Vector((p.y - nas.y, p.z - nas.z)).dot(n2)
                    hump = max(hump, d)
            m["nose_hump_mm"] = hump * 1000
            m["nose_projection_mm"] = (nas.y - prn.y) * 1000
            m["nose_length_mm"] = (nas.z - prn.z) * 1000
            m["nose_proj_ratio"] = m["nose_projection_mm"] / max(m["nose_length_mm"], 1e-6)

        m.update(head_structure(body, co, eyes, eye_co, chin.z, ez, lm))
        m["interpupillary"] = (sum(p.x for p in eye_co if p.x > 0) / max(1, sum(1 for p in eye_co if p.x > 0))
                               - sum(p.x for p in eye_co if p.x < 0) / max(1, sum(1 for p in eye_co if p.x < 0)))

    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in m.items()}


# --- head structure (T7) ------------------------------------------------------------------------

def _skin_bvh(body, co):
    """BVH of the skin polygons (helper and joint-cube polygons dropped), on rest coords co."""
    gidx = {g.index for g in body.vertex_groups if g.name in HELPERS}
    helper = np.zeros(len(co), bool)
    for v in body.data.vertices:
        if any(g.group in gidx and g.weight > 0 for g in v.groups):
            helper[v.index] = True
    polys = [tuple(p.vertices) for p in body.data.polygons if not helper[list(p.vertices)].any()]
    return BVHTree.FromPolygons(co, polys), helper, polys


def _eye_spheres(eye_co):
    """Per side (1 = character's left, +x): sphere centre, radius and cornea apex (most forward)."""
    out = {}
    for side in (1, -1):
        p = np.array([q[:] for q in eye_co if q.x * side > 0])
        A = np.c_[2 * p, np.ones(len(p))]
        sol = np.linalg.lstsq(A, (p ** 2).sum(1), rcond=None)[0]
        c = sol[:3]
        r = float(np.sqrt(sol[3] + c @ c))
        out[side] = (c, r, p[np.argmin(p[:, 1])])
    return out


def _profile(bvh, x, z0, z1, step=0.0005, y0=-1.0):
    """Skin profile on the vertical line x: first hit along +Y from the front, per height z.
    Returns (z, y) arrays (y nan where nothing was hit)."""
    zs = np.arange(z0, z1 + 1e-9, step)
    ys = np.full(len(zs), np.nan)
    for i, z in enumerate(zs):
        loc, _, _, _ = bvh.ray_cast(Vector((x, y0, z)), Vector((0, 1, 0)))
        if loc is not None:
            ys[i] = loc.y
    return zs, ys


def _aperture(skin, eye_bvh, c, side, step=0.00025):
    """Palpebral fissure seen from the front: the front rays that reach the eyeball before any
    skin, as the connected region around the pupil. Returns the vertical extent through the pupil
    (m), the canthi (medial, lateral) as (x, z): the extreme columns' mean heights, and the top
    and bottom of the pupil column relative to the eye centre (the lid margins)."""
    xs = np.arange(-0.020, 0.020 + 1e-9, step)
    zs = np.arange(-0.014, 0.014 + 1e-9, step)
    open_ = np.zeros((len(zs), len(xs)), bool)
    d = Vector((0, 1, 0))
    for j, dx in enumerate(xs):
        for i, dz in enumerate(zs):
            o = Vector((c[0] + dx, c[1] - 0.2, c[2] + dz))
            le, _, _, te = eye_bvh.ray_cast(o, d)
            if le is None:
                continue
            ls, _, _, ts = skin.ray_cast(o, d)
            open_[i, j] = ls is None or te < ts
    i0, j0 = int(np.argmin(np.abs(zs))), int(np.argmin(np.abs(xs)))
    if not open_[i0, j0]:
        return None
    reg = np.zeros_like(open_)
    stack = [(i0, j0)]
    while stack:
        i, j = stack.pop()
        if i < 0 or j < 0 or i >= len(zs) or j >= len(xs) or reg[i, j] or not open_[i, j]:
            continue
        reg[i, j] = True
        stack += [(i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)]
    k = np.nonzero(reg[:, j0])[0]
    aperture = (k.max() - k.min() + 1) * step
    top, bottom = zs[k.max()] + step / 2, zs[k.min()] - step / 2
    cols = np.nonzero(reg.any(0))[0]

    def canthus(jj):
        return c[0] + xs[jj], c[2] + float(zs[reg[:, jj]].mean())
    a, b = canthus(cols.min()), canthus(cols.max())
    lateral, medial = (b, a) if side > 0 else (a, b)
    return aperture, medial, lateral, top, bottom


def gonial_angle(lm, side_x, ear_c):
    """Soft-tissue gonial angle (photo-anthropometric) at the gonion landmark, in the sagittal
    (y, z) projection: between the line to the menton (the mandibular border) and the line to the
    condyle point (front of the ear at its mid height, the tragus proxy). lm: MediaPipe landmark
    points on the measured mesh (head_sculpt embedding); gonion = 172 / 397 on the side whose x
    sign matches side_x, averaged with its mirrored partner (the embedding is not symmetric)."""
    x0 = lm[152][0]
    a_, b_ = (lm[172], lm[397]) if np.sign(lm[172][0] - x0) == side_x else (lm[397], lm[172])
    g = 0.5 * (a_ + np.array([2 * x0 - b_[0], b_[1], b_[2]]))
    a = (lm[152] - g)[1:]
    b = (ear_c - g)[1:]
    return float(np.degrees(np.arccos(np.clip(a @ b / np.linalg.norm(a) / np.linalg.norm(b), -1, 1))))


def group_mask(body, name):
    out = np.zeros(len(body.data.vertices), bool)
    g = body.vertex_groups.get(name)
    if g is not None:
        for v in body.data.vertices:
            if any(x.group == g.index and x.weight > 0 for x in v.groups):
                out[v.index] = True
    return out


def head_structure(body, co, eyes, eye_co, chin_z, ez, lm=None):
    """T7 head-structure measures, mean of both sides (per side in *_lr):

    brow_overhang            supraorbital rim (most forward skin 6-25 mm above the eye centre on
                             the mid-pupil line) ahead of the cornea apex, along -Y (metres)
    forehead_behind_brow_mm  the profile 25 mm above that rim point, behind it (+ = behind)
    orbit_recess_mm          cornea apex behind the rim line (supraorbital rim to infraorbital rim,
                             the most forward skin 8-14 mm below the eye centre), at apex height
    eye_aperture_mm          palpebral fissure height through the pupil, seen from the front
    canthal_tilt_deg         lateral canthus above the medial one (+ = up-tilted)
    gonial_angle_deg         soft-tissue jaw angle (gonial_angle; needs the landmark embedding)
    globe_radius_mm          sphere fit of the fitted eye
    """
    m = {}
    skin, helper, polys = _skin_bvh(body, co)
    E = [Vector(p) for p in eye_co]
    eye_bvh = BVHTree.FromPolygons(E, [tuple(p.vertices) for p in eyes.data.polygons])
    rows = {k: [] for k in ("brow_overhang", "forehead_behind_brow_mm", "orbit_recess_mm",
                            "eye_aperture_mm", "canthal_tilt_deg", "globe_radius_mm")}
    for side, (c, r, apex) in _eye_spheres(eye_co).items():
        rows["globe_radius_mm"].append(r * 1000)
        zs, ys = _profile(skin, float(c[0]), c[2] - 0.03, c[2] + 0.065)
        up = (zs > c[2] + 0.006) & (zs < c[2] + 0.025) & np.isfinite(ys)
        lo = (zs > c[2] - 0.014) & (zs < c[2] - 0.008) & np.isfinite(ys)
        if up.any() and lo.any():
            iS = np.nonzero(up)[0][np.argmin(ys[up])]
            iI = np.nonzero(lo)[0][np.argmin(ys[lo])]
            yS, zS, yI, zI = ys[iS], zs[iS], ys[iI], zs[iI]
            rows["brow_overhang"].append(apex[1] - yS)
            f = np.isfinite(ys) & (np.abs(zs - (zS + 0.025)) < 0.002)
            if f.any():
                rows["forehead_behind_brow_mm"].append((ys[f].mean() - yS) * 1000)
            t = (apex[2] - zS) / (zI - zS)
            rows["orbit_recess_mm"].append((apex[1] - (yS + t * (yI - yS))) * 1000)
        ap = _aperture(skin, eye_bvh, c, side)
        if ap:
            a, (mx, mz), (lx, lz) = ap[:3]
            rows["eye_aperture_mm"].append(a * 1000)
            rows["canthal_tilt_deg"].append(float(np.degrees(np.arctan2(lz - mz, abs(lx - mx)))))
    for k, v in rows.items():
        if v:
            m[k] = float(np.mean(v))
            if k != "brow_overhang" and len(v) == 2:
                m[k + "_lr"] = [round(float(x), 2) for x in v]
    C = np.array([p[:] for p in co])
    ears = group_mask(body, "ears")
    ang = []
    if lm is not None:
        for side in (1, -1):
            e = ears & (C[:, 0] * side > 0)
            if e.any():
                E = C[e]
                ang.append(gonial_angle(lm, side, np.array([0.0, E[:, 1].min(), E[:, 2].mean()])))
    if ang:
        m["gonial_angle_deg"] = float(np.mean(ang))
        m["gonial_angle_deg_lr"] = [round(x, 1) for x in ang]
    return m


def checks(m):
    """Pass/fail against the spec targets: {key: {value, target, tol, ok}}."""
    out = {}
    for k, (t, tol) in TARGETS.items():
        if k in m and k not in RANGES:
            out[k] = {"value": m[k], "target": t, "tol": tol, "ok": abs(m[k] - t) <= tol + 1e-9}
    if "brow_overhang" in m:
        out["brow_overhang"] = {"value": m["brow_overhang"], "target": BROW_OVERHANG_MIN,
                                "tol": None, "ok": m["brow_overhang"] >= BROW_OVERHANG_MIN}
    for k, (lo, hi) in RANGES.items():
        if k in m:
            ok = (lo is None or m[k] >= lo - 1e-9) and (hi is None or m[k] <= hi + 1e-9)
            out[k] = {"value": m[k], "target": [lo, hi], "tol": None, "ok": ok}
    if "nose_hump_mm" in m:   # caricature guard: rugged, not hooked
        out["nose_hump_mm"] = {"value": m["nose_hump_mm"], "target": NOSE_HUMP_MAX,
                               "tol": None, "ok": m["nose_hump_mm"] <= NOSE_HUMP_MAX}
        out["nose_proj_ratio"] = {"value": m["nose_proj_ratio"], "target": NOSE_PROJ_RATIO[0],
                                  "tol": NOSE_PROJ_RATIO[1],
                                  "ok": abs(m["nose_proj_ratio"] - NOSE_PROJ_RATIO[0]) <= NOSE_PROJ_RATIO[1]}
    return out


def find_eyes(objs):
    return next((o for o in objs if o.type == "MESH" and "low-poly" in o.name), None)


def measure_live(b):
    """On the live MPFB human (nude: no clothes fitted yet)."""
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    eyes = find_eyes(bpy.data.objects)
    st = getattr(b, "sculpt_state", None)
    emb = st and st.get("emb")
    if emb is None:   # no sculpt layer: the default embedding, when it exists, still gives the jaw angle
        import os
        from . import head_layer
        path = head_layer.resolve("$DATA/build/identity/base_embedding.npz")
        emb = np.load(path) if os.path.exists(path) else None
    m = measure(arm, b.basemesh, eyes, emb)
    b.notes["spec_landmarks"] = m
    b.notes["spec_checks"] = checks(m)
    return m
