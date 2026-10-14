"""Hand forms (m1 v2 Track G): anatomical mid-frequency forms sculpted on the
staged body's hands, after head_refine (which subdivides the hands once and
adds soft knuckle bumps, tendons and a raised nail patch) and before the skin
bake, so the baked maps, the normal map and the AO see them. Topology, UVs
and weights are untouched: vertices only move along their normals.

Forms (all in mm, config `hands.forms`, defaults FORMS):

  back of the hand
    knuckles     the metacarpal heads as defined bumps (sharper than
                 head_refine's soft Gaussian) with shallow valleys between
                 them on the knuckle line;
    tendons      the four extensor tendons as narrow ridges fanning from the
                 wrist to the knuckles, plus the two thumb extensors framing
                 the anatomical snuffbox;
    first web    the dorsal interosseous mound between thumb and index;
  palm
    thenar       the thumb's ball, hypothenar the little-finger border pad,
    hollow       the central palm hollow, cushions under the finger roots;
  fingers
    pads         palm-side pads on each phalanx and the fingertip pulp,
    joints       a little volume at the PIP / DIP joints (sides and back),
                 slimmer shafts between them.

The hand frame (finger, across and back directions, joint positions) comes
from the rest skeleton (head_refine.hand_frames), so the forms follow any
body the build makes.
"""

import numpy as np

from . import head_refine as hr

FORMS = {
    "knuckle_mm": 1.1, "knuckle_r": 0.0058, "valley_mm": 0.7,
    "tendon_mm": 0.75, "tendon_w": 0.0017, "thumb_tendon_mm": 0.6,
    "web_mm": 1.4,
    "thenar_mm": 2.6, "hypothenar_mm": 1.8, "hollow_mm": 1.6, "cushion_mm": 0.9,
    "pad_mm": 0.55, "pulp_mm": 0.7, "joint_mm": 0.45, "shaft_mm": 0.25,
}


def _gauss(x, w):
    return np.exp(-0.5 * (x / w) ** 2)


def _seg(p, a, b):
    ab = b - a
    t = np.clip(((p - a) @ ab) / max(ab.dot(ab), 1e-12), 0.0, 1.0)
    return np.linalg.norm(p - (a + t[:, None] * ab), axis=1), t


def displacement(co, nr, hand, hf, c):
    """Per-vertex displacement along the normal (metres) for the hand verts."""
    mm = 0.001
    disp = np.zeros(len(co))
    for side, f in hf.items():
        W, F, A, B = f["wrist"], f["fingers"], f["across"], f["back"]
        near = hand & (np.linalg.norm(co - W, axis=1) < 0.25)
        if not near.any():
            continue
        p = co[near]
        n = nr[near]
        back = np.clip(n @ B, 0.0, 1.0) ** 1.3
        palm = np.clip(-(n @ B), 0.0, 1.0) ** 1.3
        d = np.zeros(len(p))
        mcp = [f["mcp"][k] for k in hr.FINGERS]
        # ---- back of the hand
        for i, j in enumerate(mcp):
            head = j + B * 0.0055 - F * 0.002
            d += c["knuckle_mm"] * mm * np.exp(-0.5 * ((p - head) ** 2).sum(1) / c["knuckle_r"] ** 2) * back
            if i < 3:   # valley between this knuckle and the next, on the knuckle line
                v = 0.5 * (j + mcp[i + 1]) + B * 0.005 - F * 0.003
                dd = p - v
                along = dd @ F
                acr = np.linalg.norm(dd - np.outer(along, F), axis=1)
                d -= c["valley_mm"] * mm * _gauss(acr, 0.0035) * _gauss(along, 0.008) * back
            # extensor tendon: wrist (fanned in) to the knuckle
            a0 = W + F * 0.012 + B * 0.007 + (j - W - F * ((j - W) @ F)) * 0.35
            a1 = j + B * 0.005 - F * 0.010
            dist, t = _seg(p, a0, a1)
            fade = np.sin(np.pi * np.clip(t, 0, 1)) ** 0.5
            d += c["tendon_mm"] * mm * _gauss(dist, c["tendon_w"]) * fade * back
        # thumb extensors: from the radial wrist to the thumb MCP (long one
        # on the back, short one on the side: the snuffbox between them)
        th1, th2 = f["thumb"][1], f["thumb"][2]
        radial = -A
        for off, amp in ((B * 0.006 + radial * 0.004, 1.0), (radial * 0.010 - B * 0.002, 0.7)):
            a0 = W + F * 0.004 + off
            a1 = th1 + (th2 - th1) * 0.15 + off * 0.5
            dist, t = _seg(p, a0, a1)
            d += c["thumb_tendon_mm"] * amp * mm * _gauss(dist, c["tendon_w"] * 1.1) \
                * np.sin(np.pi * np.clip(t, 0, 1)) ** 0.5 * np.clip(n @ (B + radial * 0.6) / 1.17, 0, 1)
        # first dorsal interosseous: the mound between the thumb and index
        # metacarpals on the back
        web = 0.55 * f["mcp"]["index"] + 0.45 * th1 + B * 0.004
        d += c["web_mm"] * mm * np.exp(-0.5 * ((p - web) ** 2).sum(1) / 0.011 ** 2) * np.clip(n @ (B + radial) / 1.4, 0, 1)
        # ---- palm
        pal = -B
        thenar = 0.55 * th1 + 0.25 * W + 0.20 * f["mcp"]["index"] + pal * 0.008
        d += c["thenar_mm"] * mm * np.exp(-0.5 * ((p - thenar) ** 2).sum(1) / 0.014 ** 2) * palm
        hyp0 = W + F * 0.020 + A * 0.022
        hyp1 = f["mcp"]["pinky"] - F * 0.022 + A * 0.006
        dist, t = _seg(p, hyp0, hyp1)
        d += c["hypothenar_mm"] * mm * _gauss(dist, 0.010) * np.sin(np.pi * np.clip(t, 0, 1)) ** 0.7 * palm
        centre = W * 0.45 + f["mcp"]["middle"] * 0.4 + f["mcp"]["ring"] * 0.15
        d -= c["hollow_mm"] * mm * np.exp(-0.5 * ((p - centre) ** 2).sum(1) / 0.015 ** 2) * palm
        for k in hr.FINGERS:
            cu = f["mcp"][k] + F * 0.004
            d += c["cushion_mm"] * mm * np.exp(-0.5 * ((p - cu) ** 2).sum(1) / 0.008 ** 2) * palm
        # ---- fingers: pads, pulp, joint volume
        for k in hr.FINGERS:
            joints = [f["mcp"][k], f["pip"][k], f["dip"][k]]
            tip = joints[2] + (joints[2] - joints[1]) * 0.85
            segs = [(joints[0], joints[1]), (joints[1], joints[2]), (joints[2], tip)]
            for si, (a, b) in enumerate(segs):
                dist, t = _seg(p, a, b)
                onf = dist < 0.012
                mid = np.sin(np.pi * np.clip(t, 0, 1))
                amp = c["pulp_mm"] if si == 2 else c["pad_mm"]
                ctr = 0.55 if si == 2 else 0.5
                d += amp * mm * _gauss(t - ctr, 0.22) * palm * onf
                d -= c["shaft_mm"] * mm * mid ** 2 * (1 - palm) * onf * (1 if si < 2 else 0.4)
            for jt in joints[1:]:
                d += c["joint_mm"] * mm * np.exp(-0.5 * ((p - jt) ** 2).sum(1) / 0.0045 ** 2) * (1 - 0.6 * palm)
        disp[near] += d
    return disp


# Track G terms the T22 landmark fields (head_sculpt.hand_field) replace when hands.sculpt is on:
# the knuckles, valleys, tendons, thumb tendons and joint/shaft volumes are drawn there, crisper.
SUPERSEDED = ("knuckle_mm", "valley_mm", "tendon_mm", "thumb_tendon_mm", "joint_mm", "shaft_mm")


def subdivide_dorsum(b, body, arm, hf):
    """One more grid subdivision on the back and sides of the hands, wrist to just past the
    knuckles (head_refine subdivided the hands once; the MPFB dorsum is still ~4 mm apart there,
    the fingers ~2 mm): ~2 mm, enough to carry tendons, veins and the knuckle planes as geometry.
    UVs and skin weights interpolate (head_refine.subdivide), so the re-packed islands hold."""
    lab, dom = hr.classify(body, arm)
    co = hr.coords(body)
    nr = hr.normals(body)
    thumb_tip = np.array([str(d).startswith(("thumb_02", "thumb_03")) for d in dom])
    sel = np.zeros(len(co), bool)
    for f in hf.values():
        W, F, B = f["wrist"], f["fingers"], f["back"]
        a = (co - W) @ F
        amcp = float(np.mean([(f["mcp"][k] - W) @ F for k in hr.FINGERS]))
        # the back only (n . B > 0.15), wrist to the knuckle line, not the thumb's phalanges
        sel |= (lab == "hand") & (np.linalg.norm(co - W, axis=1) < 0.2) & (a > -0.012) & (a < amcp + 0.004) \
            & (nr @ B > 0.15) & ~thumb_tip
    smooth = float(((b.cfg["head"].get("refine") or {}).get("subdiv") or {}).get("smooth", 0.5))
    before, after = hr.subdivide(body, sel, smooth)
    return {"verts_selected": int(sel.sum()), "faces_before": before, "faces_after": after}


def field_verts(lab, dom, co, hf):
    """The vertices the T22 hand fields act on: the hands and the forearm skin within 6 cm of
    each wrist (the wrist forms reach under the cuff)."""
    sel = lab == "hand"
    fore = np.array([str(d).startswith("lowerarm") for d in dom])
    for f in hf.values():
        sel |= fore & (np.linalg.norm(co - f["wrist"], axis=1) < 0.06)
    return sel


def apply(b):
    """Build stage (called from head.refine, after head_refine, before the
    skin bake). Config `hands` (null disables Track G) / `hands.forms`;
    `hands.sculpt` (T22, head_sculpt.hand_field; null: Track G's forms only)."""
    if "hands" in b.cfg and b.cfg["hands"] is None:
        return None
    hcfg = b.cfg.get("hands") or {}
    c = dict(FORMS)
    sculpt_on = hcfg.get("sculpt", {}) is not None
    if sculpt_on:
        c.update({k: 0.0 for k in SUPERSEDED})
    c.update(hcfg.get("forms") or {})
    if not c.get("enabled", True):
        return None
    body = hr.staged_body(b)
    arm = b.armature()
    hf = hr.hand_frames(arm)
    out = {}
    if sculpt_on and (hcfg.get("sculpt") or {}).get("subdiv_dorsum", 1):
        out["subdiv_dorsum"] = subdivide_dorsum(b, body, arm, hf)
    lab, dom = hr.classify(body, arm)
    b.refine_labels = lab
    hand = lab == "hand"
    co = hr.coords(body)
    nr = hr.normals(body)
    disp = displacement(co, nr, hand, hf, c)
    out.update({"verts_moved": int((np.abs(disp) > 1e-5).sum()),
                "max_out_mm": round(float(disp.max()) * 1000, 2), "max_in_mm": round(float(-disp.min()) * 1000, 2)})
    if sculpt_on:
        from . import head_sculpt as hs
        sc = hs.field_cfg(hs.HAND_FIELDS, hcfg.get("sculpt"))
        sel = field_verts(lab, dom, co, hf)
        paths = hs.vein_paths(hf)
        s = np.zeros(len(co))
        s[sel] = hs.hand_field(co[sel], nr[sel], hf, sc, paths)
        nails = hr.group_weights(body, "fingernails")
        s[hand] += hs.nail_folds(nails[hand], co[hand], hf, sc)
        disp = disp + s
        # what skin_tex needs for the residual bake (the analytic part only; the nail folds are
        # weight-based and stay geometry)
        b.t22_hands = {"cfg": sc, "hf": hf, "paths": paths, "verts": np.nonzero(sel)[0]}
        out["fields"] = {"verts": int(sel.sum()), "max_out_mm": round(float(s.max()) * 1000, 2),
                         "max_in_mm": round(float(-s.min()) * 1000, 2)}
    hr.set_coords(body, co + nr * disp[:, None])
    b.notes.setdefault("hands", {})["forms"] = out
    b.notes["hands"]["measure"] = measure(body, arm)
    return out


# --- measures (T22) ----------------------------------------------------------------------------

def measure(body, arm, relief_r=0.010):
    """hand_width_ratio and dorsum relief on the rest mesh, per side, then the mean.

    hand_width_ratio: hand breadth at the metacarpals (ISO 7250: across the knuckle line, the
    thumb excluded; skin within 2 mm of the mean MCP line) over hand length (the wrist joint, the
    hand bone's head, to the middle fingertip). Also the breadth including the thumb, at the thumb
    MCP's level, over the same length.

    dorsum relief: on the back of the hand (wrist to the knuckles, facing back > 0.5), each
    vertex's height above a quadric fitted to the skin within relief_r (Gaussian weights, sigma
    relief_r / 2) in its tangent frame: the forms smaller than ~1 cm with the hand's own curvature
    taken out. p50 / p95 / p99 of |relief| in mm."""
    from mathutils.kdtree import KDTree
    lab, dom = hr.classify(body, arm)
    co = hr.coords(body)
    nr = hr.normals(body)
    hf = hr.hand_frames(arm)
    thumb = np.array([str(d).startswith("thumb") for d in dom])
    middle = np.array([str(d).startswith("middle") for d in dom])
    out = {}
    for s, f in hf.items():
        W, F, A, B = f["wrist"], f["fingers"], f["across"], f["back"]
        near = (lab == "hand") & (np.linalg.norm(co - W, axis=1) < 0.24)
        a = (co - W) @ F
        b_ = (co - W) @ A
        amcp = float(np.mean([(f["mcp"][k] - W) @ F for k in hr.FINGERS]))
        band = near & ~thumb & (np.abs(a - amcp) < 0.002)
        breadth = float(b_[band].max() - b_[band].min())
        length = float(a[near & middle].max())
        at = float((f["thumb"][1] - W) @ F)
        tb = near & (np.abs(a - at) < 0.002)
        breadth_t = float(b_[tb].max() - b_[tb].min())
        # dorsum relief
        L = float((f["mcp"]["middle"] - W) @ F)
        dors = near & (a > 0.15 * L) & (a < amcp) & (nr @ B > 0.5) & ~thumb
        pool = np.nonzero(near & (nr @ B > 0.2))[0]
        kd = KDTree(len(pool))
        for j, i in enumerate(pool):
            kd.insert(co[i], j)
        kd.balance()
        rel = []
        sig = relief_r * 0.5
        for i in np.nonzero(dors)[0]:
            nb = np.array([pool[j] for _, j, _ in kd.find_range(co[i], relief_r)])
            if len(nb) < 10:
                continue
            n0 = nr[i]
            t1 = np.cross(n0, A)
            t1 /= np.linalg.norm(t1)
            t2 = np.cross(n0, t1)
            d = co[nb] - co[i]
            x, y, h = d @ t1, d @ t2, d @ n0
            w = np.exp(-0.5 * (x * x + y * y) / sig ** 2)
            M = np.c_[np.ones_like(x), x, y, x * x, x * y, y * y] * np.sqrt(w)[:, None]
            coef = np.linalg.lstsq(M, h * np.sqrt(w), rcond=None)[0]
            rel.append(-coef[0])
        rel = np.abs(np.array(rel)) * 1000
        out[s] = {"breadth_mm": round(breadth * 1000, 1), "length_mm": round(length * 1000, 1),
                  "hand_width_ratio": round(breadth / length, 3),
                  "breadth_thumb_mm": round(breadth_t * 1000, 1), "width_ratio_thumb": round(breadth_t / length, 3),
                  "dorsum_verts": int(len(rel)),
                  "relief_mm": {q: round(float(np.percentile(rel, int(q[1:]))), 3) for q in ("p50", "p95", "p99")}}
    sides = list(out.values())
    out["hand_width_ratio"] = round(float(np.mean([v["hand_width_ratio"] for v in sides])), 3)
    out["dorsum_relief_p99_mm"] = round(float(np.mean([v["relief_mm"]["p99"] for v in sides])), 3)
    return out
