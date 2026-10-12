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
from mathutils import Vector

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
BROW_OVERHANG_MIN = 0.012  # metres, look-spec §1.2 (cal.)
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


def measure(arm, body, eyes):
    """Spec landmarks. arm: armature, body: MPFB base mesh (nude, full
    topology), eyes: the fitted eye proxy or None. Returns a flat dict."""
    bones = set(arm.data.bones.keys())
    co = _rest_coords(body)
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

        # Brow overhang (look-spec §1.2): on the mid-pupil vertical, the most
        # forward brow point minus the cornea front, along -Y. Mean of both sides.
        over = []
        for side in (1, -1):
            eye = [p for p in eye_co if p.x * side > 0]
            cx = sum(p.x for p in eye) / len(eye)
            cornea_y = min(p.y for p in eye)
            brow = [p for p in head_v if abs(p.x - cx) < 0.004 and ez + 0.008 < p.z < ez + 0.040]
            if brow:
                over.append(cornea_y - min(p.y for p in brow))
        if over:
            m["brow_overhang"] = sum(over) / len(over)
        m["interpupillary"] = (sum(p.x for p in eye_co if p.x > 0) / max(1, sum(1 for p in eye_co if p.x > 0))
                               - sum(p.x for p in eye_co if p.x < 0) / max(1, sum(1 for p in eye_co if p.x < 0)))

    return {k: round(v, 4) for k, v in m.items()}


def checks(m):
    """Pass/fail against the spec targets: {key: {value, target, tol, ok}}."""
    out = {}
    for k, (t, tol) in TARGETS.items():
        if k in m:
            out[k] = {"value": m[k], "target": t, "tol": tol, "ok": abs(m[k] - t) <= tol + 1e-9}
    if "brow_overhang" in m:
        out["brow_overhang"] = {"value": m["brow_overhang"], "target": BROW_OVERHANG_MIN,
                                "tol": None, "ok": m["brow_overhang"] >= BROW_OVERHANG_MIN}
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
    m = measure(arm, b.basemesh, eyes)
    b.notes["spec_landmarks"] = m
    b.notes["spec_checks"] = checks(m)
    return m
