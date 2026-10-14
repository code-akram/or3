"""Head sculpt layer: bony structure on top of the identity (m1 v4 T7, fable_review.md §4.1/§4.7).

head_shape and head_forms are smooth Gaussian fields; the identity layer (head_layer) is a
statistical face. None of them makes a plane break. This layer adds the skull under the skin as
landmark-anchored ridge fields with an asymmetric profile (a crisp edge on one side, a long falloff
on the other), and the eye block (globe size, lids, canthi). It runs in head.edit_base after the
identity layer, on either face (public identity or private fan delta), as one shape key
("head_sculpt"), so every proxy fitted afterwards follows it.

Anchors: the MediaPipe embedding of the base mesh (author_public.py embed, triangle +
barycentrics per landmark), evaluated on the current shape (after the identity), symmetrised
(left/right landmark pairs averaged across the face midline).

Ridge field: a polyline C (landmarks, or points derived from them), a push direction D, a "side"
reference S. A vertex's distance to C is measured in the plane perpendicular to D (so pushing
along D does not change it); the signed offset across the curve picks the profile width (pos_mm
on the S side, neg_mm on the other); the amplitude tapers at the curve's ends; vertices are
weighted by depth along D from the curve (depth_mm) and by facing (normal . D), so the far side
of the head never moves. Fields (head.sculpt.fields, mm; negative = recess):

  brow           supraorbital ridge along the lower brow line, forward, crisp underside
  socket         the orbit behind the rim: recess inside the rim ellipse, outside the lids
                 (lower_mm / lower_r_mm: the infraorbital part, deeper and wider)
  zygoma         malar eminence and zygomatic arch back to the ear, lateral, crisp lower edge
  submalar       the plane under the arch, recessed: the cheek plane break
  mandible       lower border of the mandible, chin to gonion, out-and-down, crisp underside
                 (drop_mm: how far below MediaPipe's frontal jaw contour the border runs at the corner)
  submandible    the recess under that border
  gonion         the jaw angle pushed out and back-down (squares it)
  ramus          posterior border of the ramus, gonion to the condyle in front of the tragus
  retromandible  the recess behind the ramus
  nasal          nasal bones: the dorsum and its side edges (sides recessed)
  chin           mental tubercles, a squarer chin; drop_mm lowers the menton
  temporal       temporal line, with the temple hollow behind it

  The vault (a cranial frame from the base mesh: porion from the ear fronts, vertex, the midline
  back; vault_frame):
  crown          the top flattened, down (the egg's dome), broad
  parietal       parietal eminences, out and a little up, behind and above the ear: with the flat
                 crown, the pentagonal skull outline seen from behind
  temporal_fossa the side under the superior temporal line (the arc from the temple over the ear to
                 the supramastoid crest), pushed in: a flat temporal plane with a crisp upper edge
  occiput        the occipital curve (opisthocranion) pushed back: a fuller back of the head
  nuchal         under the superior nuchal line (inion out to the mastoids), pushed in: the shelf
                 where the occiput turns into the neck, instead of the egg's smooth taper

Two-band application: the base mesh has ~4-5 mm vertex spacing, so edit_base applies each
profile widened by base_spacing_mm (soft band, same peak); head_refine then adds the difference
(sharp - soft) on the subdivided face (refine()), which carries the crisp edges into the GLB.

Eye block (head.sculpt.eyes): the eye helpers are scaled to globe_mm about a centre moved forward
so the cornea apex stays put; the lid skin is re-seated on the smaller globe (core/fade like
wrap.py's eye cores); the lids are then rotated (head_forms.lids) so the upper margin covers
upper_over_iris_mm of the iris top and the lower margin lower_over_iris_mm of its bottom (iris_mm is
the iris radius); the lateral canthus is moved to
canthal_tilt_deg. Parameters only; no person is the reference.
"""

import os

import numpy as np

from . import head_forms, head_layer, head_shape

MM = 0.001
LID_MM = 1.5       # socket globe guard: least skin-to-globe gap in front of the eye (t7b)

DEFAULTS = {
    "embedding": "$DATA/build/identity/base_embedding.npz",
    "base_spacing_mm": 3.5,
    "fields": {
        "brow": {"mm": -0.5, "neg_mm": 2.5, "pos_mm": 9.0, "depth_mm": 14.0},
        "socket": {"mm": -1.0, "lower_mm": -4.0, "lower_r_mm": 16.0, "edge_mm": 2.0},
        "zygoma": {"mm": 2.5, "neg_mm": 3.0, "pos_mm": 6.0, "depth_mm": 14.0},
        "submalar": {"mm": -1.8, "neg_mm": 6.0, "pos_mm": 4.0, "depth_mm": 16.0},
        "mandible": {"mm": 3.0, "neg_mm": 2.5, "pos_mm": 7.0, "depth_mm": 14.0, "drop_mm": 16.0},
        "submandible": {"mm": -1.2, "neg_mm": 4.0, "pos_mm": 2.5, "depth_mm": 14.0},
        "gonion": {"mm": 7.5, "r_mm": 12.0},
        "ramus": {"mm": 1.5, "neg_mm": 2.5, "pos_mm": 7.0, "depth_mm": 12.0},
        "retromandible": {"mm": -1.5, "neg_mm": 4.0, "pos_mm": 3.0, "depth_mm": 12.0},
        "nasal": {"mm": 0.5, "side_mm": -0.7},
        "chin": {"mm": 1.2, "r_mm": 6.0, "drop_mm": 0.0},
        "temporal": {"mm": 0.5, "hollow_mm": -1.2},
        # the vault (t7b): skull, not egg, from the back and in profile (vault_frame, vault)
        "crown": {"mm": -4.0, "r_mm": 32.0},
        "parietal": {"mm": 5.0, "r_mm": 28.0},
        "temporal_fossa": {"mm": -3.5, "neg_mm": 22.0, "pos_mm": 3.0, "depth_mm": 15.0},
        "occiput": {"mm": 4.5, "r_mm": 22.0},
        "nuchal": {"mm": -5.5, "neg_mm": 10.0, "pos_mm": 3.0, "depth_mm": 15.0},
    },
    # lids (t7b): a calm, slightly hooded adult-male eye, no sclera above or below the iris in a front
    # view: the upper margin 2 mm over the iris top (MRD1 ~3.9 mm), the lower 0.75 mm over the iris
    # bottom (MRD2 ~5.15 mm); fissure = 2 * iris - upper - lower = 9.05 mm
    "eyes": {"globe_mm": 12.0, "forward_mm": 0.6, "iris_mm": 5.9, "upper_over_iris_mm": 2.0, "lower_over_iris_mm": 0.75,
             "canthal_tilt_deg": 3.0, "core_mm": 1.5, "fade_mm": 6.0, "clearance_mm": 0.6,
             "lids_on_fan": False},   # the lid targets (aperture, tilt) apply to the public face only
}

# MediaPipe left/right landmark pairs (subject's right first) and midline points.
PAIRS = [(33, 263), (133, 362), (159, 386), (145, 374), (46, 276), (53, 283), (52, 282), (65, 295),
         (55, 285), (70, 300), (63, 293), (105, 334), (66, 296), (107, 336), (234, 454), (93, 323),
         (132, 361), (58, 288), (172, 397), (136, 365), (150, 379), (149, 378), (176, 400), (148, 377),
         (116, 345), (117, 346), (118, 347), (123, 352), (147, 376), (127, 356), (162, 389), (21, 251),
         (54, 284), (103, 332), (98, 327), (61, 291), (129, 358), (50, 280), (187, 411), (205, 425)]
MIDLINE = (152, 168, 6, 197, 195, 5, 4, 1, 2, 0, 17, 9, 151, 10, 8, 175, 199, 200)


def _cfg(cfg):
    out = {"embedding": DEFAULTS["embedding"], "base_spacing_mm": DEFAULTS["base_spacing_mm"]}
    out.update({k: v for k, v in (cfg or {}).items() if k not in ("fields", "eyes")})
    f = {k: dict(v) for k, v in DEFAULTS["fields"].items()}
    for k, v in ((cfg or {}).get("fields") or {}).items():
        if v is None:
            f.pop(k, None)
        else:
            f.setdefault(k, {}).update(v)
    out["fields"] = f
    e = (cfg or {}).get("eyes", DEFAULTS["eyes"])
    out["eyes"] = None if e is None else {**DEFAULTS["eyes"], **e}
    return out


def ss(e0, e1, x):
    return head_forms.smoothstep(e0, e1, x)


# --- anchors ---------------------------------------------------------------------------------

class Anchors:
    """Landmark points on the current shape, symmetrised about the face midline x0, plus the
    face axes (object space): lateral(side) for side +1/-1 (+1 = +x), up, fwd."""

    def __init__(self, co, emb, x0):
        pts = np.einsum("lk,lkd->ld", emb["bary"], co[emb["tri_verts"]])
        valid = emb["valid"].astype(bool)
        self.x0 = x0
        mirror = lambda p: np.array([2 * x0 - p[0], p[1], p[2]])  # noqa: E731
        P, ok = pts.copy(), valid.copy()
        for a, b in PAIRS:
            if valid[a] and valid[b]:
                P[a] = 0.5 * (pts[a] + mirror(pts[b]))
            elif valid[b]:
                P[a] = mirror(pts[b])
            elif not valid[a]:
                continue
            P[b] = mirror(P[a])
            ok[a] = ok[b] = True
        for m in MIDLINE:
            if valid[m]:
                P[m, 0] = x0
        self.P, self.ok = P, ok
        # which x side is the subject's right (MediaPipe "right" = 33)
        self.r_side = 1.0 if P[33, 0] > x0 else -1.0
        self.up = np.array([0.0, 0.0, 1.0])
        self.fwd = np.array([0.0, -1.0, 0.0])

    def lat(self, side):
        return np.array([side, 0.0, 0.0])

    def pts(self, idx, side):
        """Landmarks given on the subject's right, on the requested x side (+1 / -1)."""
        missing = [i for i in idx if not self.ok[i]]
        if missing:
            raise RuntimeError(f"head_sculpt: landmarks not embedded: {missing}")
        p = self.P[list(idx)].copy()
        if side != self.r_side:
            p[:, 0] = 2 * self.x0 - p[:, 0]
        return p


def unit(v):
    v = np.asarray(v, np.float64)
    return v / np.linalg.norm(v)


# --- ridge fields ----------------------------------------------------------------------------

def ridge(co, nrm, curve, D, S, amp, neg, pos, depth, widen=0.0, taper=0.15, end_mm=None):
    """Displacement (n, 3) of one ridge field (all lengths in metres). curve (k, 3), D push
    direction (unit), S side reference (pos side). widen: extra profile width (soft band)."""
    D = unit(D)
    a = unit(S - D * (S @ D))
    b = np.cross(D, a)
    P2 = np.c_[co @ a, co @ b]
    C2 = np.c_[curve @ a, curve @ b]
    seg = np.diff(C2, axis=0)
    L = np.linalg.norm(seg, axis=1)
    tot = L.sum()
    best = np.full(len(co), np.inf)
    t_best = np.zeros(len(co))
    s_best = np.zeros(len(co))
    e_best = np.zeros(len(co))
    q_best = np.zeros((len(co), 3))
    acc = 0.0
    for k in range(len(seg)):
        e = seg[k] / max(L[k], 1e-12)
        rel = P2 - C2[k]
        tl = rel @ e
        t = np.clip(tl / max(L[k], 1e-12), 0, 1)
        q = C2[k] + t[:, None] * seg[k]
        off = P2 - q
        d = np.linalg.norm(off, axis=1)
        better = d < best
        nrm2 = np.array([-e[1], e[0]])
        if nrm2 @ np.array([1.0, 0.0]) < 0:      # oriented toward S (= +a)
            nrm2 = -nrm2
        best = np.where(better, d, best)
        t_best = np.where(better, (acc + t * L[k]) / tot, t_best)
        s_best = np.where(better, off @ nrm2, s_best)
        over = np.where(tl < 0, -tl, np.where(tl > L[k], tl - L[k], 0.0))
        e_best = np.where(better, over * ((k == 0) & (tl < 0) | (k == len(seg) - 1) & (tl > L[k])), e_best)
        q3 = curve[k] + t[:, None] * (curve[k + 1] - curve[k])
        q_best = np.where(better[:, None], q3, q_best)
        acc += L[k]
    sig = np.where(s_best > 0, np.hypot(pos, widen), np.hypot(neg, widen))
    prof = np.exp(-0.5 * (s_best / sig) ** 2)
    along = ss(0.0, taper, t_best) * (1 - ss(1 - taper, 1.0, t_best)) if taper else 1.0
    end = np.exp(-0.5 * (e_best / (end_mm or np.hypot(neg, widen))) ** 2)
    dep = np.exp(-0.5 * (((co - q_best) @ D) / depth) ** 2)
    face = np.clip(nrm @ D, 0, 1) ** 0.5
    return (amp * prof * along * end * dep * face)[:, None] * D[None, :]


def blob(co, nrm, c, D, amp, r, widen=0.0):
    D = unit(D)
    rr = np.hypot(r, widen)
    w = np.exp(-0.5 * ((co - c) ** 2).sum(1) / rr ** 2) * np.clip(nrm @ D, 0, 1) ** 0.5
    return (amp * w)[:, None] * D[None, :]


def ear_front(co, ears, side):
    e = ears & ((co[:, 0] > 0) == (side > 0))
    p = co[e]
    return p[np.argmin(p[:, 1])], p[:, 2].mean(), p[:, 2].min()


def fields(an, co, nrm, eyes_c, ears, fcfg, widen, vf=None):
    """Sum of all ridge fields (n, 3), metres. vf: vault_frame() of the base mesh (the vault
    fields are skipped without it)."""
    out = np.zeros_like(co)
    if vf is not None:
        out += vault(co, nrm, an, vf, fcfg, widen)
    up, fwd = an.up, an.fwd
    m = lambda v: float(v) * MM  # noqa: E731
    for side in (1.0, -1.0):
        lat = an.lat(side)
        c_eye = eyes_c[side]
        f = fcfg.get("brow")
        if f:
            C = an.pts([55, 65, 52, 53, 46, 70], side)
            C[0] += -lat * 0.004                      # carry the ridge onto the glabella
            out += ridge(co, nrm, C, fwd, up, m(f["mm"]), m(f["neg_mm"]), m(f["pos_mm"]), m(f["depth_mm"]),
                         widen, taper=0.12)
        f = fcfg.get("zygoma")
        if f:
            ef, ez_mid, ez_low = ear_front(co, ears, side)
            back = np.array([ef[0] - lat[0] * 0.004, ef[1] - 0.008, ez_mid - 0.004])
            C = np.vstack([an.pts([116, 234], side), back])
            D = unit(0.6 * lat + 0.8 * fwd)     # cheekbone forward-lateral corner, not width
            out += ridge(co, nrm, C, D, up, m(f["mm"]), m(f["neg_mm"]), m(f["pos_mm"]), m(f["depth_mm"]),
                         widen, taper=0.1)
            g = fcfg.get("submalar")
            if g:
                C2 = C[:2] - up * 0.016 + lat * 0.002
                out += ridge(co, nrm, C2, D, up, m(g["mm"]), m(g["neg_mm"]), m(g["pos_mm"]),
                             m(g["depth_mm"]), widen, taper=0.25)
        f = fcfg.get("mandible")
        # MediaPipe's jaw contour is the frontal outline, above and ahead of the mandible's lower
        # border: the border runs drop_mm below it at the jaw corner (0 at the chin), and the
        # corner (gonion) sits 12 mm behind landmark 172
        drop = m(f.get("drop_mm", 0.0)) if f else 0.0
        G = an.pts([172], side)[0] - fwd * 0.012 - up * (0.004 + drop)
        if f:
            J = an.pts([148, 176, 149, 150, 136, 172], side)
            J = J - up * (drop * np.linspace(0.0, 1.0, len(J)) ** 1.5)[:, None]
            C = np.vstack([J, G])
            D = unit(lat - 0.7 * up)
            out += ridge(co, nrm, C, D, up, m(f["mm"]), m(f["neg_mm"]), m(f["pos_mm"]), m(f["depth_mm"]),
                         widen, taper=0.1)
            g = fcfg.get("submandible")
            if g:
                out += ridge(co, nrm, C - up * 0.007, D, up, m(g["mm"]), m(g["neg_mm"]), m(g["pos_mm"]),
                             m(g["depth_mm"]), widen, taper=0.15)
        f = fcfg.get("gonion")
        if f:
            out += blob(co, nrm, G, unit(0.2 * lat - 0.8 * up - 0.55 * fwd), m(f["mm"]), m(f["r_mm"]), widen)
        f = fcfg.get("ramus")
        if f:
            ef, ez_mid, ez_low = ear_front(co, ears, side)
            cd = np.array([ef[0] - lat[0] * 0.006, ef[1] - 0.006, ez_mid - 0.006])
            C = np.vstack([G, 0.5 * (G + cd), cd])
            back = -fwd
            out += ridge(co, nrm, C, lat, fwd, m(f["mm"]), m(f["neg_mm"]), m(f["pos_mm"]), m(f["depth_mm"]),
                         widen, taper=0.2)
            g = fcfg.get("retromandible")
            if g:
                out += ridge(co, nrm, C + back * 0.008, lat, fwd, m(g["mm"]), m(g["neg_mm"]), m(g["pos_mm"]),
                             m(g["depth_mm"]), widen, taper=0.25)
        f = fcfg.get("chin")
        if f:
            c = an.pts([152], side)[0] + lat * 0.011 + up * 0.006
            out += blob(co, nrm, c, unit(fwd + 0.3 * lat), m(f["mm"]), m(f["r_mm"]), widen)
            if f.get("drop_mm") and side > 0:
                c0 = an.pts([152], side)[0]
                w = np.exp(-0.5 * ((co - c0) ** 2).sum(1) / 0.012 ** 2)
                out[:, 2] -= m(f["drop_mm"]) * w
        f = fcfg.get("nasal")
        if f:
            C = an.pts([168, 6, 197], side)          # dorsum sides above the alae (alar width untouched)
            if f.get("side_mm"):
                out += ridge(co, nrm, C + lat * 0.0065, fwd, up, m(f["side_mm"]), 0.0025, 0.0025, 0.012, widen,
                             taper=0.2)
        f = fcfg.get("temporal")
        if f:
            C = an.pts([70, 54, 103], side)
            C[0] = C[0] + up * 0.004
            out += ridge(co, nrm, C, lat, fwd, m(f["mm"]), 0.0025, 0.008, 0.012, widen, taper=0.15)
            if f.get("hollow_mm"):
                h = C[0] + up * 0.012 - fwd * 0.014 + lat * 0.004
                out += blob(co, nrm, h, lat, m(f["hollow_mm"]), 0.010, widen)
        f = fcfg.get("socket")
        if f:
            out += socket(co, nrm, an, c_eye, side, m(f["mm"]), m(f.get("lower_mm", f["mm"])),
                          m(f.get("lower_r_mm", 13.0)), m(f["edge_mm"]), widen)
    f = fcfg.get("nasal")
    if f and f.get("mm"):
        C = an.pts([168, 6, 197, 195], 1.0)
        out += ridge(co, nrm, C, fwd, an.lat(1.0), m(f["mm"]), 0.003, 0.003, 0.012, widen, taper=0.2)
    return out


def vault_frame(co, skin, ears, an):
    """Cranial frame on the (sculpted-face) base mesh, kept for the dense pass: porion height Pz
    (the ears' mid height) and depth Py (10 mm behind the ear's front edge), the vertex height Vz,
    and surface points for the vault fields, found at fractions of the auricular height
    H = Vz - Pz (porion to vertex). Positions are object space, metres."""
    x0 = an.x0
    efs = [ear_front(co, ears, s_) for s_ in (1.0, -1.0)]
    Pz = float(np.mean([e[1] for e in efs]))
    Py = float(np.mean([e[0][1] for e in efs])) + 0.010
    head = skin & ~ears & (co[:, 2] > Pz - 0.06)
    mid = head & (np.abs(co[:, 0] - x0) < 0.006)
    V = co[mid][np.argmax(co[mid][:, 2])]
    H = float(V[2] - Pz)

    def extreme(m_fn, key, w):
        """The skin point maximising key among those in the window m_fn(w), the window widened
        until it holds some (the base mesh is ~4-5 mm apart)."""
        for k in range(6):
            m_ = m_fn(w * 1.5 ** k)
            if m_.any():
                p = co[m_]
                return p[np.argmax(key(p))]
        raise RuntimeError("head_sculpt.vault_frame: no skin point found")

    def back_at(x, z, w=0.006):
        """The most posterior skin point near (x, z)."""
        return extreme(lambda w_: head & (np.abs(co[:, 0] - x) < w_) & (np.abs(co[:, 2] - z) < w_) & (co[:, 1] > Py),
                       lambda p: p[:, 1], w)

    def side_at(side, y, z, w=0.008):
        """The most lateral skin point near (y, z) on the x side `side`."""
        return extreme(lambda w_: head & (np.abs(co[:, 1] - y) < w_) & (np.abs(co[:, 2] - z) < w_)
                       & ((co[:, 0] - x0) * side > 0), lambda p: (p[:, 0] - x0) * side, w)

    zi = Pz + 0.08 * H                                   # inion
    nuchal = [back_at(x0, zi)]
    for side in (1.0, -1.0):
        pts = [back_at(x0 + side * 0.030, zi - 0.004), back_at(x0 + side * 0.052, zi - 0.013)]
        nuchal = (pts[::-1] + nuchal) if side < 0 else (nuchal + pts)
    out = {"Pz": Pz, "Py": Py, "H": H, "vertex": V, "opisthocranion": back_at(x0, Pz + 0.28 * H),
           "nuchal": np.array(nuchal)}
    for side in (1.0, -1.0):
        out[("parietal", side)] = side_at(side, Py + 0.045, Pz + 0.62 * H)
        out[("temporal", side)] = np.array([side_at(side, Py - 0.050, Pz + 0.45 * H),
                                            side_at(side, Py - 0.015, Pz + 0.55 * H),
                                            side_at(side, Py + 0.025, Pz + 0.56 * H),
                                            side_at(side, Py + 0.055, Pz + 0.45 * H),
                                            side_at(side, Py + 0.070, Pz + 0.28 * H)])
    return out


def vault(co, nrm, an, vf, fcfg, widen):
    """The vault fields (n, 3), metres (see the module docstring)."""
    out = np.zeros_like(co)
    up, back = an.up, -an.fwd
    m = lambda v: float(v) * MM  # noqa: E731
    f = fcfg.get("crown")
    if f:
        out += blob(co, nrm, vf["vertex"], up, m(f["mm"]), m(f["r_mm"]), widen)
    f = fcfg.get("occiput")
    if f:
        out += blob(co, nrm, vf["opisthocranion"], unit(back + 0.2 * up), m(f["mm"]), m(f["r_mm"]), widen)
    f = fcfg.get("nuchal")
    if f:
        out += ridge(co, nrm, vf["nuchal"], back, up, m(f["mm"]), m(f["neg_mm"]), m(f["pos_mm"]),
                     m(f["depth_mm"]), widen, taper=0.1)
    for side in (1.0, -1.0):
        lat = an.lat(side)
        f = fcfg.get("parietal")
        if f:
            out += blob(co, nrm, vf[("parietal", side)], unit(lat + 0.35 * up), m(f["mm"]), m(f["r_mm"]), widen)
        f = fcfg.get("temporal_fossa")
        if f:
            out += ridge(co, nrm, vf[("temporal", side)], lat, up, m(f["mm"]), m(f["neg_mm"]), m(f["pos_mm"]),
                         m(f["depth_mm"]), widen, taper=0.12)
    return out


def socket(co, nrm, an, eye, side, amp, amp_lo, r_lo, edge, widen):
    """Recess inside the orbital rim: an ellipse in the frontal plane around the eye (rim radii
    from the brow landmarks above, 13 mm below, 19 mm lateral, 13 mm medial), outside the lids
    (beyond 4 mm from the globe), pushed back with a soft edge of `edge`."""
    c, R = eye
    lat = an.lat(side)
    brow = an.pts([52], side)[0]
    r_up = max(brow[2] - c[2] - 0.002, 0.008)
    dx = (co - c) @ lat
    dz = co[:, 2] - c[2]
    rx = np.where(dx > 0, 0.019, 0.013)
    rz = np.where(dz > 0, r_up, r_lo)
    q = np.sqrt((dx / rx) ** 2 + (dz / rz) ** 2)          # 1 on the rim
    e = np.hypot(edge, widen) / 0.016
    inside = 1 - ss(1 - e, 1 + 0.3 * e, q)
    s = np.linalg.norm(co - c, axis=1) - R
    lids = np.maximum(ss(0.003, 0.007, s), ss(0.006, 0.008, -dz))  # below the lower lid: infraorbital
    front = ss(0.0, 0.006, (c[1] - co[:, 1]))
    w = inside * lids * front * np.clip(nrm @ an.fwd, 0, 1)
    a = np.where(dz > 0, amp, amp_lo + (amp - amp_lo) * ss(-0.004, 0.0, dz))
    back = -(a * w)                                     # metres pushed back (+ = into the orbit)
    # globe guard (t7b): the lid skin over the lower globe (6-10 mm below the eye centre) must stay
    # in front of the eyeball. Unguarded, the infraorbital push drove it into the globe: a fold
    # under the lower lid, sclera showing through the skin and back faces seen from the front.
    # The push is limited to what keeps the skin lid_mm in front of the globe, with a soft min.
    gap = float(LID_MM) * MM
    h = (R + gap) ** 2 - dx ** 2 - dz ** 2
    room = np.where(h > 0, (c[1] - np.sqrt(np.maximum(h, 0.0))) - co[:, 1], np.inf)
    room = np.where(co[:, 1] < c[1], np.maximum(room, 0.0), np.inf)
    k = 0.0005
    lim = np.where(np.isfinite(room), -k * np.logaddexp(-back / k, -room / k), back)
    back = np.where(back > 0, np.clip(lim, 0.0, back), back)
    return (-back)[:, None] * an.fwd[None, :]          # negative amp: back into the orbit


# --- eyes ------------------------------------------------------------------------------------

def eye_block(obj, co, ecfg, notes):
    """Globe size, lid re-seating, aperture and canthal tilt. Returns new coords."""
    out = co.copy()
    W = {g: head_shape._group_weights(obj, g) > 0 for g in
         ("helper-l-eye", "helper-r-eye", "HelperGeometry", "helper-l-eyelashes-1", "helper-l-eyelashes-2",
          "helper-r-eyelashes-1", "helper-r-eyelashes-2")}
    skin = ~W["HelperGeometry"]
    fr = head_shape.Frame.from_helpers(obj, co)
    eye_c = {}
    rep = {}
    for key, g, side in (("l", "helper-l-eye", 1.0), ("r", "helper-r-eye", -1.0)):
        c, R = head_forms.fit_sphere(co[W[g]])
        Rn = float(ecfg["globe_mm"]) * MM
        fwd = np.array([0.0, -1.0, 0.0])
        cn = c + fwd * (R - Rn + float(ecfg.get("forward_mm", 0.0)) * MM)   # cornea apex kept, then moved forward
        out[W[g]] = cn + (co[W[g]] - c) * (Rn / R)
        lash = W[f"helper-{key}-eyelashes-1"] | W[f"helper-{key}-eyelashes-2"]
        movable = (skin | lash) & ((co[:, 0] > fr.origin[0]) == (side > 0))
        d = co - c
        r = np.linalg.norm(d, axis=1)
        s = r - R
        w = (1 - ss(ecfg["core_mm"] * MM, (ecfg["core_mm"] + ecfg["fade_mm"]) * MM, s)) * (s > -0.002)
        w *= ss(0.004, -0.004, d[:, 1]) * movable              # front of the centre
        dn = co - cn
        seated = cn + dn / np.maximum(np.linalg.norm(dn, axis=1, keepdims=True), 1e-9) * (Rn + np.maximum(s, 0))[:, None]
        out = out + w[:, None] * (seated - out) * movable[:, None]
        eye_c[key] = (cn, Rn)
        rep[key] = {"globe_mm": [round(R * 1000, 2), round(Rn * 1000, 2)]}
    # lids and canthi: measured the way head_measure does (front rays: globe before skin), then
    # the lids rotated toward the target margins and the lateral canthus moved to the tilt
    iris = float(ecfg["iris_mm"]) * MM
    up_t = iris - float(ecfg["upper_over_iris_mm"]) * MM
    lo_t = -iris + float(ecfg["lower_over_iris_mm"]) * MM
    tgt = np.radians(float(ecfg["canthal_tilt_deg"]))
    lash = W_lash(W)
    clear = float(ecfg.get("clearance_mm", 0.0)) * MM      # base-mesh clearance (off: head_refine's is on)
    side_of = co[:, 0] > fr.origin[0]
    npush_total = 0
    for it in range(4 if ecfg.get("lid_targets", True) else 0):
        if clear > 0:
            out, npush = clear_globes(obj, out, skin, lash, side_of, eye_c, clear)
            npush_total += npush
        ap = fissures(obj, out, W, eye_c)
        cfg, done = {}, True
        for key in ("l", "r"):
            if ap[key] is None:
                continue
            a_, med, lat_p, top, bot = ap[key]
            cfg[f"upper_{key}_mm"] = float(np.clip((up_t - top) / MM, -3, 3))
            cfg[f"lower_{key}_mm"] = float(np.clip((lo_t - bot) / MM, -3, 3))
            rep[key]["margins_mm"] = [round(top / MM, 2), round(bot / MM, 2)]
            tilt = np.arctan2(lat_p[1] - med[1], abs(lat_p[0] - med[0]))
            rep[key]["canthal_tilt_deg"] = round(float(np.degrees(tilt)), 2)
            dz = float(np.clip(np.tan(tgt) * abs(lat_p[0] - med[0]) - (lat_p[1] - med[1]), -0.0015, 0.0015))
            cn, Rn = eye_c[key]
            d = out - cn
            sxz = np.hypot(out[:, 0] - lat_p[0], out[:, 2] - lat_p[1])
            wgt = np.exp(-0.5 * (sxz / 0.0035) ** 2) * (d[:, 1] < 0.002) * \
                (np.linalg.norm(d, axis=1) - Rn < 0.006) * (skin | lash)
            out[:, 2] += dz * wgt
            if max(abs(cfg[f"upper_{key}_mm"]), abs(cfg[f"lower_{key}_mm"]), abs(dz) / MM) > 0.15:
                done = False
        if done or it == 3:
            break
        cfg = {k: cfg.get(k, 0.0) for k in ("upper_l_mm", "upper_r_mm", "lower_l_mm", "lower_r_mm")}
        lid_in = out.copy()
        out = head_forms.lids(obj, out, fr, cfg, eye_c)
        keep = ~(skin | lash)
        out[keep] = lid_in[keep]
    rep["clearance_pushed_verts"] = npush_total
    notes["eyes"] = rep
    return out


def clear_globes(obj, out, skin, lash, side_of, eye_c, clear):
    """Push outer lid/lash vertices that sit inside the (smaller, forward) globe out to its
    surface + clear, so the eyeball does not show through the lids where the lid rotation and the
    canthus move folded them inward. The lid's inner (conjunctival) face is left alone: pushed out,
    it would drape over the cornea. Returns (coords, count)."""
    nrm = head_forms.vertex_normals(obj, out)
    n = 0
    for key, side in (("l", 1.0), ("r", -1.0)):
        cn, Rn = eye_c[key]
        d = out - cn
        r = np.linalg.norm(d, axis=1)
        outer = (nrm * d).sum(1) / np.maximum(r, 1e-9) > 0.3
        m_ = (skin | lash) & (side_of == (side > 0)) & (r < Rn + clear) & (d[:, 1] < 0.004) & outer
        out = out.copy()
        out[m_] = cn + d[m_] / r[m_, None] * (Rn + clear)
        n += int(m_.sum())
    return out, n


def shipped_spheres(b, body, fitted):
    """The eyeballs eyes_hq generates, world space: fitted is [(centre, radius)] (+x eye first)
    from the fitted proxy; when the build ran the sculpt layer, its eye-helper spheres (the globes
    the lids, socket guard and clearances were shaped against) replace them where they agree
    within 4 mm. The proxy's back-half fit sits ~0.9 mm forward of the helper (t7b): eyes built on
    it poked through the upper lid that lies tangent on the helper globe."""
    st = getattr(b, "sculpt_state", None)
    if not st or "eye_c" not in st:
        return fitted, False
    mw = np.array(body.matrix_world)
    out, used = [], True
    for (c, r), side in zip(fitted, (1.0, -1.0)):
        ch, rh = st["eye_c"][side]
        cw = (mw @ np.append(ch, 1.0))[:3]
        if np.linalg.norm(cw - np.asarray(c)) < 0.004:
            out.append((cw, float(rh) * float(np.linalg.norm(mw[:3, 0]))))
        else:
            out.append((c, r))
            used = False
    return out, used


def W_lash(W):
    return W["helper-l-eyelashes-1"] | W["helper-l-eyelashes-2"] | W["helper-r-eyelashes-1"] | W["helper-r-eyelashes-2"]


def fissures(obj, co, W, eye_c):
    """Per eye ("l"/"r"): head_measure._aperture on the current coords, the globe as the analytic
    sphere (centre, radius) of the resized eye helper (the fitted proxy does not exist yet).
    Canthi as (x, z) world; margins relative to the eye centre."""
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    from . import head_measure
    skip = W["HelperGeometry"] | (head_shape._group_weights(obj, "JointCubes") > 0)
    V = [Vector(p) for p in co]
    skin_p = [list(p.vertices) for p in obj.data.polygons if not skip[list(p.vertices)].any()]
    skin_bvh = BVHTree.FromPolygons(V, skin_p)
    return {key: head_measure._aperture(skin_bvh, eye_c[key], side) for key, side in (("l", 1.0), ("r", -1.0))}


# --- stage -----------------------------------------------------------------------------------

def setup(b, obj, co):
    c = _cfg(b.cfg["head"].get("sculpt"))
    path = head_layer.resolve(c["embedding"])
    emb = np.load(path)
    fr = head_shape.Frame.from_helpers(obj, co)
    return c, Anchors(co, emb, float(fr.origin[0]))


def apply(b):
    """head.edit_base hook (after head_layer): the 'head_sculpt' shape key."""
    if b.cfg["head"].get("sculpt") is None:
        return None
    emb_path = head_layer.resolve(_cfg(b.cfg["head"]["sculpt"])["embedding"])
    if not os.path.exists(emb_path):
        print(f"[head_sculpt] warning: no landmark embedding at {emb_path} (bench/m1/identity.sh makes it); "
              "sculpt layer skipped", flush=True)
        b.notes["head_sculpt"] = {"skipped": "no embedding"}
        return None
    obj = b.basemesh
    co = head_shape._mix_coords(obj)
    c, an = setup(b, obj, co)
    notes = {}
    edited = co
    if c["eyes"]:
        ecfg = dict(c["eyes"])
        if b.cfg.get("fan") and not ecfg.get("lids_on_fan", False):
            ecfg["lid_targets"] = False      # the fan face keeps its own fissure: globe and re-seat only
        edited = eye_block(obj, co, ecfg, notes)
    helpers = head_shape._group_weights(obj, "HelperGeometry") > 0
    eyes = (head_shape._group_weights(obj, "helper-l-eye") > 0) | (head_shape._group_weights(obj, "helper-r-eye") > 0)
    ears = head_shape._group_weights(obj, "ears") > 0
    nrm = head_forms.vertex_normals(obj, edited)
    eye_c = {}
    for side, g in ((1.0, "helper-l-eye"), (-1.0, "helper-r-eye")):
        eye_c[side] = head_forms.fit_sphere(edited[head_shape._group_weights(obj, g) > 0])
    an_now = Anchors(edited, np.load(head_layer.resolve(c["embedding"])), an.x0)
    vf = vault_frame(edited, ~helpers, ears, an_now)
    disp = fields(an_now, edited, nrm, eye_c, ears, c["fields"], c["base_spacing_mm"] * MM, vf)
    disp[eyes | helpers] = 0.0       # helper cubes have no meaningful normal; the lids moved above
    edited = edited + disp
    emb = np.load(head_layer.resolve(c["embedding"]))
    b.sculpt_state = {"cfg": c, "anchors": an_now, "eye_c": eye_c, "vault": vf,
                      "emb": {"tri_verts": emb["tri_verts"], "bary": emb["bary"]},
                      "ears_front": {s: ear_front(edited, ears, s) for s in (1.0, -1.0)}}
    kb = obj.data.shape_keys.key_blocks
    basis = np.empty(len(co) * 3)
    kb[0].data.foreach_get("co", basis)
    key = obj.shape_key_add(name="head_sculpt", from_mix=False)
    key.data.foreach_set("co", (basis.reshape(-1, 3) + (edited - co)).ravel())
    key.value = 1.0
    obj.data.update()
    moved = np.linalg.norm(edited - co, axis=1)
    notes.update({"fields": {k: v.get("mm") for k, v in c["fields"].items()},
                  "max_move_mm": round(float(moved.max()) * 1000, 2),
                  "verts_moved_over_0.1mm": int((moved > 1e-4).sum())})
    b.notes["head_sculpt"] = notes
    return moved


def refine(b, body, lab, eyes_obj):
    """head_refine hook, after the dense re-planarisation: add (sharp - soft) of every field on
    the subdivided face, so the edges the base mesh could not hold reach the GLB."""
    st = getattr(b, "sculpt_state", None)
    if not st:
        return None
    from . import head_refine as hr
    co = hr.coords(body)
    nrm = hr.normals(body)
    if eyes_obj is not None:
        # sphere centres of the fitted eyes in the body's object space (a centroid sits forward of
        # the centre on a proxy with a cornea), against the helper spheres seen at edit_base
        to_body = body.matrix_world.inverted() @ eyes_obj.matrix_world
        E = np.array([(to_body @ v.co)[:] for v in eyes_obj.data.vertices])
        from . import head_measure
        cl, rl = head_measure.eye_sphere(E[E[:, 0] > 0])
        cr, rr = head_measure.eye_sphere(E[E[:, 0] < 0])
        gap = max(np.linalg.norm(cl - st["eye_c"][1.0][0]), np.linalg.norm(cr - st["eye_c"][-1.0][0]))
        if gap > 0.004:
            return {"skipped": f"eye centres moved {gap * 1000:.1f} mm since edit_base"}
        # the globes eyes_hq ships (shipped_spheres): the helper spheres the lids were shaped on
        (cl, rl), (cr, rr) = st["eye_c"][1.0], st["eye_c"][-1.0]
    sel = (lab == "face") | (lab == "head")
    ears = hr.group_weights(body, "ears") > 0
    c = st["cfg"]
    w = c["base_spacing_mm"] * MM
    sharp = fields(st["anchors"], co, nrm, st["eye_c"], ears, c["fields"], 0.0, st.get("vault"))
    soft = fields(st["anchors"], co, nrm, st["eye_c"], ears, c["fields"], w, st.get("vault"))
    d = (sharp - soft) * sel[:, None]
    d[hr.group_weights(body, "lips") > 0] = 0.0
    new = co + d
    # clearance on the dense face against the fitted eyes: subdivision shrinks the lids onto (and
    # into) a 12 mm globe; an outer-skin vertex inside the eye would show the eyeball through it
    npush = nline = 0
    if eyes_obj is not None:
        clear = float(c["eyes"].get("dense_clearance_mm", 0.3)) * MM if c["eyes"] else 0.0003
        for cen, R in ((cl, rl), (cr, rr)):
            v = new - cen
            r = np.linalg.norm(v, axis=1)
            outer = (nrm * v).sum(1) / np.maximum(r, 1e-9) > 0.3
            m_ = sel & outer & (r < R + clear) & (v[:, 1] < 0.004)
            new[m_] = cen + v[m_] / r[m_, None] * (R + clear)
            npush += int(m_.sum())
            # the lids' inner lining (normals toward the eye) onto the globe (t7b): subdivision
            # shrinks the convex outer lid onto the eye and swells the concave lining outward,
            # and under the lower lid the two crossed (the lining's back faces seen from the front)
            inner = (nrm * v).sum(1) / np.maximum(r, 1e-9) < -0.5
            m_ = sel & inner & (r > R + 0.0002) & (r < R + 0.0025) & (v[:, 1] < 0.004)
            new[m_] = cen + v[m_] / r[m_, None] * (R + 0.0002)
            nline += int(m_.sum())
    hr.set_coords(body, new)
    mag = np.linalg.norm(new - co, axis=1)
    return {"max_mm": round(float(mag.max()) * 1000, 2), "verts_over_0.1mm": int((mag > 1e-4).sum()),
            "eye_clearance_pushed": npush, "lid_lining_seated": nline}


# --- hands and neck (m1 v4 T22) --------------------------------------------------------------
#
# The same idea as the head fields, on the dense hands and the neck after head_refine: analytic
# fields of position and normal, anchored on the rest skeleton (head_refine.hand_frames, the neck
# and clavicle bones) and on the ears, so a texel evaluates exactly what a vertex got.
# hand_forms.apply displaces the hand vertices along their normals by hand_field(); neck() does the
# neck. skin_tex then bakes the residual the mesh cannot hold between its vertices (the field at
# each texel minus the field interpolated from the vertices, as for the crisp band), so tendon
# edges and vein walls stay sharp in the normal map and the hero displacement.
#
# Hand fields (hands.sculpt.fields, mm along the normal; negative = recess):
#   knuckle    the metacarpal heads (KNUCKLE_K per finger), crisp, on the knuckle line
#   valley     the dips between the heads, and the intermetacarpal gutters behind them (gutter):
#              with the heads, the knuckle planes (each head a facet, a groove between)
#   tendon     the four extensor tendons, fanning from the wrist to each head and on over the
#              proximal phalanx (the hood, hood_k of the amplitude)
#   thumb      the long thumb extensor (EPL) to the IP joint and the short one (EPB) on the radial
#              border; the anatomical snuffbox (snuff) between them at the wrist
#   pip / dip  the dorsal knuckle pad of each finger joint
#   joint      the joint wider at the sides than the shaft; shaft slims between the joints
#   breadth    the ulnar border (5th metacarpal) and the radial side of the index head out: a
#              broader, squarer palm (hand_width_ratio)
#   wrist      flatter (dorsal and palmar faces in, the sides out), the ulnar head and the radial
#              styloid, two palmar flexor cords (palmaris longus, flexor carpi radialis)
#   vein       the dorsal venous network (paths in palm coordinates; hand_detail tints the same
#              paths), vein_w_mm its Gaussian half-width, dipping under the skin along each path
#   nail_fold  (geometry only, from the fingernails weights: nail_folds) the proximal and lateral
#              nail folds raised round the plate, the bed a little sunk
#
# Neck fields (neck.fields, mm): scm (sternocleidomastoid, mastoid to the sternal head, a crisp
# anterior border), carotid / posterior (the triangles either side, recessed), larynx (thyroid
# prominence, midline). All fade to 0 on skin the shirt, jacket or tie (knot) covers and collar_gap_mm +
# collar_margin_mm above it (collar_weight), so the surface the collar sits on does not move. The
# clavicle heads are under the shirt, where the body is deleted: no field.

FINGERS = ("index", "middle", "ring", "pinky")
HAND_FIELDS = {
    "knuckle_mm": 1.8, "knuckle_r_mm": 3.8, "valley_mm": -1.0, "gutter_mm": -0.6,
    "tendon_mm": 1.8, "tendon_w_mm": 2.0, "hood_k": 0.45,
    "thumb_mm": 0.9, "snuff_mm": -1.0,
    "pip_mm": 0.6, "dip_mm": 0.4, "joint_mm": 0.5, "shaft_mm": -0.3,
    "breadth_ulnar_mm": 1.6, "breadth_radial_mm": 0.7,
    "wrist_flat_mm": -0.7, "wrist_side_mm": 0.35, "ulnar_mm": 1.4, "radial_mm": 0.7, "flexor_mm": 0.35,
    "vein_mm": 1.6, "vein_w_mm": 1.8,
    "nail_fold_mm": 0.3, "nail_bed_mm": -0.12,
}
KNUCKLE_K = {"index": 0.95, "middle": 1.0, "ring": 0.85, "pinky": 0.65}
TENDON_K = {"index": 1.0, "middle": 1.0, "ring": 0.8, "pinky": 0.55}
NECK_FIELDS = {
    "scm_mm": 3.0, "scm_front_mm": 5.5, "scm_back_mm": 8.0, "scm_depth_mm": 18.0,
    "carotid_mm": -1.2, "posterior_mm": -1.4, "larynx_mm": 2.5, "larynx_r_mm": 7.0,
    "collar_margin_mm": 12.0, "collar_gap_mm": 3.0, "subdiv": 1,
}


def field_cfg(defaults, cfg):
    c = dict(defaults)
    c.update((cfg or {}).get("fields") or {})
    return c


def _g(x, s):
    return np.exp(-0.5 * (x / s) ** 2)


def _segd(p, a, b):
    """Distance from points p (n, d) to the segment ab, and its parameter."""
    ab = b - a
    t = np.clip(((p - a) @ ab) / max(float(ab @ ab), 1e-12), 0.0, 1.0)
    return np.linalg.norm(p - (a + t[:, None] * ab), axis=1), t


def _chain(p, pts):
    """Distance from p to the polyline pts and the arc parameter (0..1) of the nearest point."""
    best = np.full(len(p), np.inf)
    tb = np.zeros(len(p))
    L = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    tot, acc = float(L.sum()), 0.0
    for k in range(len(pts) - 1):
        d, t = _segd(p, pts[k], pts[k + 1])
        better = d < best
        best = np.where(better, d, best)
        tb = np.where(better, (acc + t * L[k]) / max(tot, 1e-12), tb)
        acc += L[k]
    return best, tb


def _ortho(v, axis):
    v = v - axis * float(v @ axis)
    return v / max(float(np.linalg.norm(v)), 1e-12)


def _chaikin(pts, n=2):
    for _ in range(n):
        q = [pts[0]]
        for a, b in zip(pts[:-1], pts[1:]):
            q += [0.75 * a + 0.25 * b, 0.25 * a + 0.75 * b]
        pts = q + [pts[-1]]
    return pts


def vein_paths(hf):
    """Per side: [(points (k, 2) in palm coordinates (u along, v across), amplitude, phase)]: the
    dorsal network of hand_detail (Track G) with its per-side jitter, corner-rounded; deterministic."""
    out = {}
    for si, (side, _f) in enumerate(sorted(hf.items())):
        rng = np.random.default_rng(301 + si)
        jit = lambda p: [(a + 0.03 * (rng.random() - 0.5), b + 0.05 * (rng.random() - 0.5)) for a, b in p]  # noqa: E731
        trunks = [
            (jit([(-0.25, 1.05), (0.05, 0.95), (0.28, 0.80), (0.45, 0.62)]), 1.0),     # basilic side
            (jit([(-0.25, -0.20), (0.05, -0.10), (0.25, 0.05), (0.42, 0.25)]), 0.9),   # cephalic side
            (jit([(0.45, 0.62), (0.50, 0.42), (0.42, 0.25)]), 0.85),                   # arch
            (jit([(0.45, 0.62), (0.62, 0.70), (0.80, 0.78)]), 0.7),                    # to the ring/middle web
            (jit([(0.42, 0.25), (0.60, 0.30), (0.79, 0.35)]), 0.65),                   # to the middle/index web
            (jit([(0.28, 0.80), (0.52, 0.98), (0.76, 1.08)]), 0.6),                    # to the ring/pinky web
            (jit([(0.25, 0.05), (0.40, -0.18), (0.55, -0.35)]), 0.5),                  # toward the thumb web
        ]
        out[side] = [(np.array(_chaikin([np.array(q, float) for q in pts])), amp, 6.3 * rng.random())
                     for pts, amp in trunks]
    return out


class PalmCoords:
    """Palm coordinates of points p for one hand: a along the fingers from the wrist, b across
    (index -> pinky), h toward the back; u = a / L (L: wrist to the middle MCP), v = 0 at the index
    MCP and 1 at the pinky MCP (hand_detail.HandFrame's convention)."""

    def __init__(self, f, p):
        self.W, self.F, self.A, self.B = f["wrist"], f["fingers"], f["across"], f["back"]
        d = p - self.W
        self.a, self.b, self.h = d @ self.F, d @ self.A, d @ self.B
        mm = f["mcp"]
        self.L = float((mm["middle"] - self.W) @ self.F)
        self.bi = float((mm["index"] - self.W) @ self.A)
        self.bp = float((mm["pinky"] - self.W) @ self.A)
        self.u = self.a / self.L
        self.v = (self.b - self.bi) / (self.bp - self.bi)


def vein_profile(p, f, paths, w):
    """Vein mask (0..1) at points p of one hand: the max over the paths of a Gaussian of the
    distance in metres (half-width w), dipping under the skin along each path (a deterministic
    'sunk' term), faded at the path ends and toward the knuckles."""
    pc = PalmCoords(f, p)
    out = np.zeros(len(p))
    scale = abs(pc.bp - pc.bi)
    for pts, amp, ph in paths:
        seg = np.c_[np.diff(pts[:, 0]) * pc.L, np.diff(pts[:, 1]) * scale]
        Ls = np.linalg.norm(seg, axis=1)
        tot, acc = float(Ls.sum()), 0.0
        best = np.full(len(p), np.inf)
        tb = np.zeros(len(p))
        for k in range(len(seg)):
            rx = (pc.u - pts[k, 0]) * pc.L
            ry = (pc.v - pts[k, 1]) * scale
            t = np.clip((rx * seg[k, 0] + ry * seg[k, 1]) / max(Ls[k] ** 2, 1e-12), 0, 1)
            d = np.hypot(rx - t * seg[k, 0], ry - t * seg[k, 1])
            better = d < best
            best = np.where(better, d, best)
            tb = np.where(better, (acc + t * Ls[k]) / max(tot, 1e-12), tb)
            acc += Ls[k]
        sunk = 0.65 + 0.35 * head_forms.smoothstep(-0.5, 0.5, np.sin(2 * np.pi * 1.1 * tb + ph))
        ends = np.sin(np.pi * np.clip(0.08 + 0.84 * tb, 0, 1)) ** 0.3
        out = np.maximum(out, amp * _g(best, w) * sunk * ends)
    return out * head_forms.smoothstep(0.84, 0.70, pc.u)


def hand_field(p, n, hf, c, paths=None):
    """Scalar displacement along the normal (metres) of the hand fields at points p (unit normals
    n), both hands. Positions and normals only (no vertex groups), so texels can evaluate it;
    the nail folds are nail_folds()."""
    mm = 0.001
    ss_ = head_forms.smoothstep
    out = np.zeros(len(p))
    paths = paths if paths is not None else vein_paths(hf)
    for side, f in hf.items():
        W = f["wrist"]
        near = np.linalg.norm(p - W, axis=1) < 0.24
        if not near.any():
            continue
        q, nn = p[near], n[near]
        pc = PalmCoords(f, q)
        F, A, B = pc.F, pc.A, pc.B
        ab = np.c_[pc.a, pc.b]
        back = np.clip(nn @ B, 0, 1) ** 1.5
        palm = np.clip(-(nn @ B), 0, 1) ** 1.5
        d = np.zeros(len(q))
        ak = {k: float((f["mcp"][k] - W) @ F) for k in FINGERS}
        bk = {k: float((f["mcp"][k] - W) @ A) for k in FINGERS}
        cen = 0.5 * (bk[FINGERS[0]] + bk[FINGERS[3]])
        # metacarpal heads and the knuckle planes
        r = c["knuckle_r_mm"] * mm
        for i, k in enumerate(FINGERS):
            d += c["knuckle_mm"] * mm * KNUCKLE_K[k] * _g(pc.a - (ak[k] - 0.0015), r) * _g(pc.b - bk[k], r * 1.1) * back
            if i < 3:
                k2 = FINGERS[i + 1]
                am, bm = 0.5 * (ak[k] + ak[k2]), 0.5 * (bk[k] + bk[k2])
                d += c["valley_mm"] * mm * _g(pc.a - (am - 0.002), 0.0045) * _g(pc.b - bm, 0.0026) * back
                # gutter: from the valley toward the wrist, converging as the metacarpals do
                g0 = np.array([am - 0.006, bm])
                g1 = np.array([0.30 * pc.L, cen + (bm - cen) * 0.55])
                dist, t = _segd(ab, g0, g1)
                d += c["gutter_mm"] * mm * _g(dist, 0.0028) * np.sin(np.pi * np.clip(0.15 + 0.85 * t, 0, 1)) ** 0.6 * back
        # extensor tendons: wrist (fanned in) -> head, then over the proximal phalanx (the hood)
        tw = c["tendon_w_mm"] * mm
        for k in FINGERS:
            dist, t = _segd(ab, np.array([0.012, cen + (bk[k] - cen) * 0.35]), np.array([ak[k] - 0.003, bk[k]]))
            fade = ss_(0.0, 0.25, t) * (1 - 0.35 * ss_(0.85, 1.0, t))
            d += c["tendon_mm"] * mm * TENDON_K[k] * _g(dist, tw) * fade * back
            j0, j1 = f["mcp"][k], f["pip"][k]
            ln = float(np.linalg.norm(j1 - j0))
            ax = (j1 - j0) / ln
            Bs = _ortho(B, ax)
            rel = q - j0
            al = rel @ ax
            hood = ss_(-0.007, -0.002, al) * ss_(ln * 1.05, ln * 0.7, al)
            d += c["tendon_mm"] * c["hood_k"] * mm * TENDON_K[k] * _g(rel @ _ortho(A, ax), tw * 1.2) * hood \
                * np.clip(nn @ Bs, 0, 1) ** 1.5 * (1 - ss_(0.013, 0.018, np.abs(rel @ Bs)))
        # thumb: EPL (long, over the back) and EPB (radial border), the snuffbox between them
        t1, t2, t3 = f["thumb"]
        radial = -A
        face = np.clip(nn @ unit(B + radial * 0.8), 0, 1) ** 1.2
        for pts, amp, w_ in (([W + F * 0.006 + B * 0.009 + radial * 0.002, t1 + (t2 - t1) * 0.2 + B * 0.004, t2, t3], 1.0, 1.1),
                             ([W + F * 0.002 + radial * 0.013, t1 + radial * 0.006, t1 + (t2 - t1) * 0.5], 0.75, 1.2)):
            dist, t = _chain(q, np.array(pts))
            # the curve runs at the bone, the cord on the skin ~7.5 mm out
            d += c["thumb_mm"] * amp * mm * _g(dist - 0.0075, tw * w_) * np.sin(np.pi * np.clip(0.1 + 0.85 * t, 0, 1)) ** 0.5 * face
        sb = W + F * 0.010 + radial * 0.013 + B * 0.004
        d += c["snuff_mm"] * mm * np.exp(-0.5 * ((q - sb) ** 2).sum(1) / 0.0045 ** 2) * np.clip(nn @ unit(B + radial), 0, 1)
        # finger joints: the dorsal knuckle pad, the sides wider than the shaft
        for k in FINGERS:
            J = [f["mcp"][k], f["pip"][k], f["dip"][k]]
            chain = J + [J[2] + (J[2] - J[1]) * 0.85]
            dist, _ = _chain(q, np.array(chain))
            onf = 1 - ss_(0.009, 0.013, dist)
            for ji, amp in ((1, c["pip_mm"]), (2, c["dip_mm"])):
                ax = unit(chain[ji + 1] - chain[ji - 1])
                al = (q - J[ji]) @ ax
                d += amp * mm * _g(al - 0.0005, 0.0032) * np.clip(nn @ _ortho(B, ax), 0, 1) ** 1.5 * onf
                d += c["joint_mm"] * (1.0 if ji == 1 else 0.7) * mm * _g(al, 0.0034) * np.abs(nn @ _ortho(A, ax)) ** 1.5 * onf
            for a_, b_ in ((J[0], J[1]), (J[1], J[2])):
                ln = float(np.linalg.norm(b_ - a_))
                ax = (b_ - a_) / ln
                al = (q - a_) @ ax
                t = np.clip(al / ln, 0, 1)
                d += c["shaft_mm"] * mm * np.sin(np.pi * t) ** 2 * (1 - np.clip(-(nn @ _ortho(B, ax)), 0, 1)) * onf \
                    * ((al > 0) & (al < ln))
        # a broader palm: the ulnar border and the radial side of the index head out
        d += c["breadth_ulnar_mm"] * mm * np.clip(nn @ A, 0, 1) ** 2 * _g(pc.a - 0.65 * pc.L, 0.32 * pc.L) * ss_(cen - 0.006, cen + 0.006, pc.b) \
            * (1 - ss_(ak["pinky"] + 0.004, ak["pinky"] + 0.014, pc.a))
        d += c["breadth_radial_mm"] * mm * np.clip(-(nn @ A), 0, 1) ** 2 * _g(pc.a - (ak["index"] - 0.006), 0.012) * ss_(cen + 0.006, cen - 0.006, pc.b)
        # wrist: flatter, the ulnar head and the radial styloid, the palmar flexor cords
        band = _g(pc.a + 0.012, 0.016)
        d += c["wrist_flat_mm"] * mm * band * np.abs(nn @ B) ** 2
        d += c["wrist_side_mm"] * mm * band * np.abs(nn @ A) ** 2
        uh = W + A * (pc.bp * 0.95) + B * 0.009 - F * 0.014
        d += c["ulnar_mm"] * mm * np.exp(-0.5 * ((q - uh) ** 2).sum(1) / 0.005 ** 2) * np.clip(nn @ unit(B + A), 0, 1)
        rs = W + A * (pc.bi * 0.9) - B * 0.001 - F * 0.006
        d += c["radial_mm"] * mm * np.exp(-0.5 * ((q - rs) ** 2).sum(1) / 0.0055 ** 2) * np.clip(nn @ unit(-A + 0.3 * B), 0, 1)
        for bo in (0.42, 0.62):
            bb = pc.bi + (pc.bp - pc.bi) * (1 - bo) - 0.004
            dist, t = _segd(ab, np.array([-0.045, bb]), np.array([0.004, bb + 0.002]))
            d += c["flexor_mm"] * mm * _g(dist, 0.0016) * np.sin(np.pi * t) ** 0.5 * palm
        # dorsal veins
        d += c["vein_mm"] * mm * vein_profile(q, f, paths[side], c["vein_w_mm"] * mm) * back
        out[near] += d
    return out


def nail_folds(nails, p, hf, c):
    """Geometry-only nail folds (metres along the normal) from the fingernails weights (0..1 per
    vertex): a raised band just outside the plate on its proximal and lateral sides (none at the
    free edge), the bed a little sunk."""
    ss_ = head_forms.smoothstep
    fold = _g(nails - 0.18, 0.11) * (nails < 0.5)
    distal = np.zeros(len(p))
    for f in hf.values():
        tips = [(f["dip"][k], f["dip"][k] + (f["dip"][k] - f["pip"][k]) * 0.85) for k in FINGERS]
        tips.append((f["thumb"][2], f["thumb"][2] + (f["thumb"][2] - f["thumb"][1]) * 0.9))
        for a_, b_ in tips:
            ln = float(np.linalg.norm(b_ - a_))
            al = (p - a_) @ ((b_ - a_) / ln)
            close = np.linalg.norm(p - (a_ + b_) * 0.5, axis=1) < 0.022
            distal = np.maximum(distal, close * ss_(0.55, 0.8, al / ln))
    return (c["nail_fold_mm"] * fold * (1 - distal) + c["nail_bed_mm"] * ss_(0.5, 0.9, nails)) * MM


def neck_anchors(co, ears, arm, skin):
    """Mastoid (behind, medial of and a little below the ear lobe) and the SCM's sternal head
    (above the clavicle head, on the front of the neck) per x side, and the larynx point (midline
    front surface 10 mm below the neck joint). World space (the staged body is unparented)."""
    out = {}
    mw = arm.matrix_world
    for side in (1.0, -1.0):
        e = ears & ((co[:, 0] > 0) == (side > 0))
        lobe = co[e][np.argmin(co[e][:, 2])]
        lat = np.array([side, 0.0, 0.0])
        mast = lobe + np.array([0.0, 0.013, -0.004]) - lat * 0.010
        cl = np.array((mw @ arm.data.bones["clavicle_" + ("l" if side > 0 else "r")].head_local)[:])
        z = cl[2] + 0.034
        m_ = skin & (np.abs(co[:, 2] - z) < 0.006) & (np.abs(co[:, 0] - side * 0.016) < 0.008)
        y = co[m_][:, 1].min() if m_.any() else cl[1] - 0.06
        out[side] = {"mastoid": mast, "sternal": np.array([side * 0.016, y + 0.004, z]), "lobe": lobe}
    nk = np.array((mw @ arm.data.bones["neck_01"].head_local)[:])
    z = nk[2] - 0.010
    m_ = skin & (np.abs(co[:, 0]) < 0.006) & (np.abs(co[:, 2] - z) < 0.006)
    y = co[m_][:, 1].min() if m_.any() else nk[1] - 0.08
    out["larynx"] = np.array([0.0, y, z])
    return out


def neck_field(p, n, an, c):
    """Scalar displacement along the normal (metres) of the neck fields at points p."""
    fwd = np.array([0.0, -1.0, 0.0])
    out = np.zeros(len(p))
    m = lambda v: float(v) * MM  # noqa: E731
    for side in (1.0, -1.0):
        a = an[side]
        lat = np.array([side, 0.0, 0.0])
        M, S = a["mastoid"], a["sternal"]
        C = np.array([M, 0.5 * (M + S) + lat * 0.010 + fwd * 0.004, S])
        D = unit(0.85 * lat + 0.5 * fwd)
        sel = head_forms.smoothstep(0.0, 0.008, p[:, 0] * side)
        for curve, amp, front, back_ in ((C, c["scm_mm"], c["scm_front_mm"], c["scm_back_mm"]),
                                         (C + fwd * 0.016, c["carotid_mm"], 5.0, 5.0),
                                         (C - fwd * 0.022 + lat * 0.004, c["posterior_mm"], 6.0, 6.0)):
            v = ridge(p, n, curve, D, fwd, m(amp), m(back_), m(front), m(c["scm_depth_mm"]), taper=0.12)
            out += (v @ D) * sel
    L = an["larynx"]
    r = m(c["larynx_r_mm"])
    w = np.exp(-0.5 * ((p[:, 1:] - L[1:]) ** 2).sum(1) / r ** 2)
    # a V seen from the front: narrower below the prominence
    w *= _g(p[:, 0] / (1.0 + 0.5 * np.clip((p[:, 2] - L[2]) / 0.008, -1, 1)), r * 0.8)
    return out + m(c["larynx_mm"]) * w * np.clip(n @ fwd, 0, 1)


def collar_weight(co, nrm, garments, c):
    """Per vertex: 0 on skin a garment covers (a ray along the skin normal meets it within 4 cm,
    deform_test's rule) and up to collar_gap_mm from it, rising to 1 over collar_margin_mm. The
    surface the collar is fitted to stays put. Returns (weight, covered)."""
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    from mathutils.kdtree import KDTree
    cov = np.zeros(len(co), bool)
    for g in garments:
        mwg = np.array(g.matrix_world)
        gco = np.array([v.co[:] for v in g.data.vertices]) @ mwg[:3, :3].T + mwg[:3, 3]
        bvh = BVHTree.FromPolygons([tuple(x) for x in gco], [tuple(pl.vertices) for pl in g.data.polygons])
        for i in np.nonzero(~cov)[0]:
            dv = Vector(nrm[i])
            if bvh.ray_cast(Vector(co[i]) + dv * 0.0003, dv, 0.04)[0] is not None:
                cov[i] = True
    if not cov.any():
        return np.ones(len(co)), cov
    kd = KDTree(int(cov.sum()))
    for j, x in enumerate(co[cov]):
        kd.insert(x, j)
    kd.balance()
    dist = np.array([kd.find(x)[2] for x in co])
    gap, mar = m_(c["collar_gap_mm"]), m_(c["collar_margin_mm"])
    return head_forms.smoothstep(gap, gap + mar, dist) * ~cov, cov


def m_(v):
    return float(v) * MM


def neck(b):
    """head.refine hook, after the hand forms and before the skin bake: the neck fields on the
    (subdivided) neck, faded out under the collar. Stores what skin_tex needs for the residual."""
    if "neck" in b.cfg and b.cfg["neck"] is None:
        return None
    from . import head_refine as hr
    c = field_cfg(NECK_FIELDS, b.cfg.get("neck"))
    body = hr.staged_body(b)
    arm = b.armature()
    garments = [o for o in b.meshes() if any(k in o.name for k in ("suit_shirt", "suit_jacket", "suit_tie"))]
    out = {}

    def region():
        lab_, _ = hr.classify(body, arm)
        co_ = hr.coords(body)
        ears_ = hr.group_weights(body, "ears") > 0
        an_ = neck_anchors(co_, ears_, arm, ~(hr.group_weights(body, "HelperGeometry") > 0))
        lobe_z = max(an_[1.0]["lobe"][2], an_[-1.0]["lobe"][2])
        box_ = (co_[:, 2] < lobe_z + 0.006) & (co_[:, 2] > an_[1.0]["sternal"][2] - 0.03) & (np.abs(co_[:, 0]) < 0.10) \
            & np.isin(lab_, ["neck", "face", "head"]) & ~ears_ & ~(hr.group_weights(body, "lips") > 0)
        return lab_, co_, hr.normals(body), an_, box_

    lab, co, nrm, an, box = region()
    if c.get("subdiv", 1):
        # the MPFB neck is ~12 mm apart: one grid subdivision where the neck shows (not under the
        # collar; the face is dense already). UVs and weights interpolate.
        w0, cov0 = collar_weight(co[box], nrm[box], garments, c)
        sel = np.zeros(len(co), bool)
        sel[np.nonzero(box)[0][~cov0]] = True
        sel &= np.isin(lab, ["neck", "head"])
        before, after = hr.subdivide(body, sel, 0.5)
        out["subdiv"] = {"verts_selected": int(sel.sum()), "faces_before": before, "faces_after": after}
        lab, co, nrm, an, box = region()
    b.refine_labels = lab
    w, cov = collar_weight(co[box], nrm[box], garments, c)
    s = np.zeros(len(co))
    s[box] = neck_field(co[box], nrm[box], an, c) * w
    hr.set_coords(body, co + nrm * s[:, None])
    b.t22_neck = {"anchors": an, "cfg": c, "verts": np.nonzero(box)[0], "w": w}
    out.update({"verts_moved": int((np.abs(s) > 1e-5).sum()), "max_out_mm": round(float(s.max()) * 1000, 2),
                "max_in_mm": round(float(-s.min()) * 1000, 2), "covered_verts": int(cov.sum()),
                "larynx_weight": round(float(w[np.argmin(np.linalg.norm(co[box] - an["larynx"], axis=1))]), 3)})
    b.notes["neck"] = out
    return out
