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
    # t7b: a calm, slightly hooded adult-male fissure, no sclera above or below the iris: upper lid
    # 1.5-2.5 mm and lower lid 0.5-1.0 mm over an 11.8 mm iris -> 8.3-9.8 mm; MRD1 3.4-4.4 and
    # MRD2 4.9-5.4 mm (normal adult MRD1 ~4-5, upper lid 1-2 mm over the limbus, the lower at or
    # just above it; heavy lids sit at the low end). Was 9.5-11, which allowed the stare.
    "eye_aperture_mm": (8.5, 9.5),
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


def measure(arm, body, eyes, emb=None, globes=None):
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

        m.update(head_structure(body, co, eyes, eye_co, chin, ez, lm, globes))
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


def eye_sphere(p):
    """Sphere (centre, radius) of one eye's points (n, 3): least squares through the back half
    (y behind the centroid), as eyes_hq.build fits the eye it ships (the MPFB eye's front carries
    a corneal bulge). Every globe test (this measure, head_sculpt's dense clearance) uses this one
    fit: the all-points fit sits ~0.45 mm higher on the low-poly proxy, and the dense clearance on
    it left the upper lid 0.5 mm inside the shipped left globe (t7b)."""
    p = np.asarray(p, np.float64)
    back = p[p[:, 1] > p[:, 1].mean()]
    q = back if len(back) > 12 else p
    A = np.c_[2 * q, np.ones(len(q))]
    sol = np.linalg.lstsq(A, (q ** 2).sum(1), rcond=None)[0]
    c = sol[:3]
    return c, float(np.sqrt(sol[3] + c @ c))


def _eye_spheres(eye_co):
    """Per side (1 = character's left, +x): sphere centre, radius (eye_sphere) and cornea apex
    (most forward)."""
    out = {}
    for side in (1, -1):
        p = np.array([q[:] for q in eye_co if q.x * side > 0])
        c, r = eye_sphere(p)
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


def _sphere_hit(o, c, r):
    """Distance along +Y from o to the sphere (c, r), or None."""
    dx, dz = o[0] - c[0], o[2] - c[2]
    h = r * r - dx * dx - dz * dz
    if h < 0:
        return None
    return (c[1] - np.sqrt(h)) - o[1]


def _aperture(skin, sphere, side, step=0.00025, band=0.00075, tol=0.0005):
    """Palpebral fissure seen from the front: the front rays that reach the eyeball before any
    skin, as the connected region around the pupil. Returns the vertical extent through the pupil
    (m), the canthi (medial, lateral) as (x, z): the extreme columns' mean heights, and the top
    and bottom of the pupil column relative to the eye centre (the lid margins).

    Robustness (t7b; the left eye's aperture swung 8-12 mm over small edits):
      * the eyeball is the analytic sphere (c, r) fitted to the eye: the low-poly proxy and the
        eye helper are 48-vertex polyhedra whose facets lie up to ~1 mm inside the sphere, about
        the lid's clearance, so testing the lid against them flipped margin rows in or out with
        the facet under each ray;
      * the upper lid lies on the globe nearly tangentially over the last 1-2 mm above the
        margin, within 0.0-0.3 mm of it, and the fitted proxy (r 12.21 mm) and the helper the
        sculpt loop drives (12.0 mm, centre 0.26 mm lower and further forward) disagree by about
        that much: lid skin less than tol inside the sphere still counts as lid (the dense pass
        pushes such skin out in front of the shipped eye anyway, head_sculpt.refine);
      * per column only the contiguous open run that overlaps the pupil row's run counts (a slit
        under the lower lid that shows the globe is a separate run, not part of the fissure);
      * the aperture and margins are the median over the columns within +-band of the pupil."""
    c, r = np.asarray(sphere[0], np.float64), float(sphere[1])
    xs = np.arange(-0.020, 0.020 + 1e-9, step)
    zs = np.arange(-0.014, 0.014 + 1e-9, step)
    open_ = np.zeros((len(zs), len(xs)), bool)
    d = Vector((0, 1, 0))
    for j, dx in enumerate(xs):
        for i, dz in enumerate(zs):
            o = (c[0] + dx, c[1] - 0.2, c[2] + dz)
            te = _sphere_hit(o, c, r)
            if te is None:
                continue
            ls, _, _, ts = skin.ray_cast(Vector(o), d)
            open_[i, j] = ls is None or te < ts - tol
    i0, j0 = int(np.argmin(np.abs(zs))), int(np.argmin(np.abs(xs)))
    if not open_[i0, j0]:
        return None

    def run(col, i):
        """The contiguous open run of column col containing row i, as (lo, hi) row indices."""
        lo = hi = i
        while lo > 0 and open_[lo - 1, col]:
            lo -= 1
        while hi < len(zs) - 1 and open_[hi + 1, col]:
            hi += 1
        return lo, hi

    # the fissure: walk out from the pupil column, keeping per column the run that overlaps the
    # neighbouring column's run (stops where the lids meet)
    runs = {j0: run(j0, i0)}
    for step_j in (1, -1):
        j, prev = j0 + step_j, runs[j0]
        while 0 <= j < len(xs):
            cand = [i for i in range(prev[0], prev[1] + 1) if open_[i, j]]
            if not cand:
                break
            mid = cand[len(cand) // 2]
            prev = runs[j] = run(j, mid)
            j += step_j
    near = [j for j in runs if abs(xs[j]) <= band + 1e-9]
    tops = np.array([zs[runs[j][1]] + step / 2 for j in near])
    bots = np.array([zs[runs[j][0]] - step / 2 for j in near])
    top, bottom = float(np.median(tops)), float(np.median(bots))
    aperture = top - bottom
    cols = sorted(runs)

    def canthus(jj):
        lo, hi = runs[jj]
        return c[0] + xs[jj], c[2] + float(zs[lo:hi + 1].mean())
    a, b = canthus(cols[0]), canthus(cols[-1])
    lateral, medial = (b, a) if side > 0 else (a, b)
    return aperture, medial, lateral, top, bottom


def _occluding_edge(skin, side, ray, scan, pivots, span=0.045, step=0.0005, jump=0.004, z_min=-np.inf):
    """Occluding-contour points of the skin seen along `ray` (unit): for each pivot, a line of
    parallel rays offset along `scan` (unit, perpendicular to ray); the edge is the last hit
    before the first depth jump (or miss) when scanning toward +scan (the first overhang below
    the cheek), among edges above z_min."""
    out = []
    r = Vector(ray)
    for p0 in pivots:
        hits = []
        for u in np.arange(-span, span + 1e-9, step):
            o = Vector(p0 + u * scan - 0.25 * ray)
            loc, _, _, d = skin.ray_cast(o, r)
            hits.append((d if loc is not None else np.inf, loc))
        t = np.array([h[0] for h in hits])
        k = None
        for i in range(len(t) - 1):
            if np.isfinite(t[i]) and hits[i][1].z > z_min and t[i + 1] - t[i] > jump:
                k = i
                break
        if k is not None:
            out.append(np.array(hits[k][1][:]))
    return np.array(out).reshape(-1, 3)


def jaw_border(skin, side, M, C, x_jaw):
    """The mandible's lower border on the skin as an occluding contour: seen from above-lateral at
    45 deg, the line where the surface normal turns from lateral to down (the jaw overhangs the
    neck there). One point per 2 mm of depth from 20 mm behind the menton M to the condyle point C
    (object coords); x_jaw is the jaw's lateral half-width (where the scan lines pivot)."""
    s = float(side)
    r1 = np.array([-s, 0.0, -1.0]) / np.sqrt(2)
    u1 = np.array([s, 0.0, -1.0]) / np.sqrt(2)
    ys = np.arange(M[1] + 0.02, C[1] + 0.002, 0.002)
    return _occluding_edge(skin, side, r1, u1, [np.array([s * x_jaw, y, M[2] + 0.02]) for y in ys],
                           z_min=M[2] - 0.005)


def gonial_from_border(lower, M, C, ear_gap=0.008):
    """Soft-tissue gonial angle in the sagittal (y, z) projection. Gonion: the lower-border point
    farthest behind-below the menton-condyle chord (the jaw corner), among points at least
    `ear_gap` in front of the condyle point. Mandibular line: from the menton, tangent to the
    lower border (the flattest line through M with the border on or above it). Ramus line: gonion
    to the condyle point (the tragus proxy). Returns (degrees, gonion, mandibular-line degrees
    above horizontal) or None."""
    lo = lower[((lower[:, 1] - M[1]) > 0.025) & (lower[:, 1] < C[1] - ear_gap)] if len(lower) else lower
    if len(lo) < 3:
        return None
    ch = (C - M)[1:] / np.linalg.norm((C - M)[1:])
    nrm = np.array([ch[1], -ch[0]])                       # behind-below the chord
    g = lo[np.argmax((lo[:, 1:] - M[1:]) @ nrm)]
    phi = np.arctan2(lo[:, 2] - M[2], lo[:, 1] - M[1]).min()
    to_m = -np.array([np.cos(phi), np.sin(phi)])
    to_c = (C - g)[1:] / np.linalg.norm((C - g)[1:])
    return float(np.degrees(np.arccos(np.clip(to_m @ to_c, -1, 1)))), g, float(np.degrees(phi))


def group_mask(body, name):
    out = np.zeros(len(body.data.vertices), bool)
    g = body.vertex_groups.get(name)
    if g is not None:
        for v in body.data.vertices:
            if any(x.group == g.index and x.weight > 0 for x in v.groups):
                out[v.index] = True
    return out


def head_structure(body, co, eyes, eye_co, chin, ez, lm=None, globes=None):
    """T7 head-structure measures, mean of both sides (per side in *_lr):

    brow_overhang            supraorbital rim (most forward skin 6-25 mm above the eye centre on
                             the mid-pupil line) ahead of the cornea apex, along -Y (metres)
    forehead_behind_brow_mm  the profile 25 mm above that rim point, behind it (+ = behind)
    orbit_recess_mm          cornea apex behind the rim line (supraorbital rim to infraorbital rim,
                             the most forward skin 10-16 mm below the eye centre, below the lower
                             lid of a 12 mm globe), at apex height
    eye_aperture_mm          palpebral fissure height through the pupil, seen from the front
    canthal_tilt_deg         lateral canthus above the medial one (+ = up-tilted)
    gonial_angle_deg         soft-tissue jaw angle (gonial_from_border on the jaw_border contour)
    globe_radius_mm          sphere fit of the fitted eye
    infraorbital_*_mm        diagnostics: the infraorbital rim point ahead of the apex / below the eye centre
    """
    m = {}
    skin, helper, polys = _skin_bvh(body, co)
    rows = {k: [] for k in ("brow_overhang", "forehead_behind_brow_mm", "orbit_recess_mm",
                            "eye_aperture_mm", "canthal_tilt_deg", "globe_radius_mm",
                            "infraorbital_ahead_mm", "infraorbital_below_mm")}
    sph = _eye_spheres(eye_co)
    if globes:   # the globes that ship (head_sculpt.shipped_spheres), world; the proxy's apex moved with them
        sph = {s_: (np.asarray(globes[s_][0]), float(globes[s_][1]),
                    sph[s_][2] + (np.asarray(globes[s_][0]) - sph[s_][0])) for s_ in sph}
    for side, (c, r, apex) in sph.items():
        rows["globe_radius_mm"].append(r * 1000)
        zs, ys = _profile(skin, float(c[0]), c[2] - 0.03, c[2] + 0.065)
        up = (zs > c[2] + 0.006) & (zs < c[2] + 0.025) & np.isfinite(ys)
        lo = (zs > c[2] - 0.016) & (zs < c[2] - 0.010) & np.isfinite(ys)
        if up.any() and lo.any():
            iS = np.nonzero(up)[0][np.argmin(ys[up])]
            iI = np.nonzero(lo)[0][np.argmin(ys[lo])]
            yS, zS, yI, zI = ys[iS], zs[iS], ys[iI], zs[iI]
            rows["brow_overhang"].append(apex[1] - yS)
            f = np.isfinite(ys) & (np.abs(zs - (zS + 0.025)) < 0.002)
            if f.any():
                rows["forehead_behind_brow_mm"].append((ys[f].mean() - yS) * 1000)
            t = (apex[2] - zS) / (zI - zS)
            rows["infraorbital_ahead_mm"].append((apex[1] - yI) * 1000)
            rows["infraorbital_below_mm"].append((c[2] - zI) * 1000)
            rows["orbit_recess_mm"].append((apex[1] - (yS + t * (yI - yS))) * 1000)
        ap = _aperture(skin, (c, r), side)
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
    M = np.array(chin[:])
    ang, gon, mp = [], [], []
    for side in (1, -1):
        e = ears & (C[:, 0] * side > 0)
        if not e.any():
            continue
        E = C[e]
        cond = np.array([side * np.abs(E[:, 0]).min(), E[:, 1].min(), E[:, 2].mean()])
        x_jaw = 0.5 * m.get("bigonial", 0.12)
        r = gonial_from_border(jaw_border(skin, side, M, cond, x_jaw), M, cond)
        if r:
            ang.append(r[0])
            gon.append(r[1])
            mp.append(r[2])
    if ang:
        m["gonial_angle_deg"] = float(np.mean(ang))
        m["gonial_angle_deg_lr"] = [round(x, 1) for x in ang]
        m["gonion_y_mm"] = [round(float(g[1]) * 1000, 1) for g in gon]
        m["gonion_below_eye_mm"] = [round(float(ez - g[2]) * 1000, 1) for g in gon]
        m["mandibular_plane_deg"] = [round(x, 1) for x in mp]
        m["menton_y_mm"] = round(float(M[1]) * 1000, 1)
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
    globes = None
    if st and st.get("eye_c") and eyes is not None:
        from . import head_sculpt
        eco = np.array([p[:] for p in _rest_coords(eyes)])
        fitted = [eye_sphere(eco[eco[:, 0] > 0]), eye_sphere(eco[eco[:, 0] < 0])]
        g, used = head_sculpt.shipped_spheres(b, b.basemesh, fitted)
        globes = {1: g[0], -1: g[1]} if used else None
    m = measure(arm, b.basemesh, eyes, emb, globes)
    b.notes["spec_landmarks"] = m
    b.notes["spec_checks"] = checks(m)
    return m
