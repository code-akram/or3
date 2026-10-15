"""The made waistcoat on the draped pattern waistcoat (m1 v4 T13 phase B item 4).

Like suit_trouser_detail: the drape is one welded sheet; this makes it a garment, each detail
placed by pattern coordinates (suit_waistcoat_pattern's notches):

  shell        the fronts with thickness (wool, canvas, lining: thick_mm), the back one layer of
               lining (back_thick_mm), half-round turned edges on every free edge
  welts        two lower welt pockets and a breast welt (the wearer's left), welts standing
               welt_lift_mm proud
  buttons      on the left front over each buttonhole (the bottom one undone: on the right front)
  marks        pressed-open seams (side, shoulder, CB, darts), pick stitching in from the front
               edge, the V and the hem, the buttonholes (a corded lip either side of the slit)

numpy + mathutils (via suit_detail). Parts: 0 wool outside, 1 lining (inside, and the back
outside), 2 turned edge, 3 button.
"""

import numpy as np

from . import suit_detail as sd
from . import suit_pattern as sp

WOOL, LINING, EDGE, BUTTON = 0, 1, 2, 3

DEFAULTS = {
    "thick_mm": 2.0,
    "back_thick_mm": 0.8,
    "edge_rings": 4,
    "welt": {"lift_mm": 0.4, "thick_mm": 1.6},
    "button": {"diam_cm": 1.5, "thick_mm": 3.0},
    "buttoned": 4,
    "pick": {"in_cm": 0.6, "pitch_cm": 0.6},
    "hole": {"lip_mm": 0.6, "lip_w_mm": 1.4, "half_gap_cm": 0.12},
}


def build(C, D, wm, X, Tw, opts=None, stats=None):
    """The made waistcoat on the drape (X, Tw welded). Returns {name: (V, F, part, UV, tag,
    kind)} plus "_uv": {"marks": {name: {tag: marks}}, "tags": {name: {tag: label}}}."""
    o = sp.merge(DEFAULTS, opts or {})
    stats = {} if stats is None else stats
    rings = o["edge_rings"]
    X = np.asarray(X, float)
    Tw = np.asarray(Tw, int)
    pm = sd.PanelMap(C, wm, X, Tw, D)
    N = sd.vertex_normals(X, Tw)
    t = np.full(len(X), o["thick_mm"] / 1000.0)
    back_v = np.zeros(len(X), bool)
    for name, I in C["info"].items():
        if I["kind"] == "back":
            back_v[wm[I["base"] + np.arange(len(I["V"]))]] = True
    t[back_v] = o["back_thick_mm"] / 1000.0
    FU, ftag = sd.shell_uv(C, wm, Tw, pm, stats)
    V, F, part, U = sd.solid(X, Tw, N, t, rings, FU=FU)
    src = U["src"]
    tag = ftag[src]
    names = list(C["names"])
    is_back = np.array([names[g - 1].startswith("back") if g > 0 else False for g in tag])
    part = np.where(part == 1, LINING, part)
    part = np.where(is_back, LINING, part)           # the back is lining, both faces and its edges
    tags = {"shell": {k + 1: n for k, n in enumerate(names)}, "pockets": {}}
    marks = {"shell": shell_marks(C, D, pm, o), "pockets": {}}
    out = {"shell": (V, F, part, U["uv"], tag, U["kind"].copy())}
    stats["shell"] = {"verts": int(len(V)), "tris": int(sum(len(f) - 2 for f in F)),
                      "back_faces": int(is_back.sum())}
    # --- welts: lower both sides, the breast welt on the left
    wo = o["welt"]
    fr = D.geom("front")
    pv, pf, pp, pu, pt, pk = [], [], [], [], [], []

    def add(V_, F_, part_, U_, label):
        b = sum(len(v) for v in pv)
        pv.append(V_)
        pf.extend(tuple(int(i) + b for i in f) for f in F_)
        pp.extend(list(part_))
        pu.extend(U_["uv"])
        pk.extend(list(U_["kind"]))
        tg = len(tags["pockets"]) + 1
        tags["pockets"][tg] = label
        pt.extend([tg] * len(F_))

    warp = _dart_warp(fr)
    welts = [("welt", "front"), ("welt", "front_r"), ("breast_welt", "front")]
    h_of = {"welt": D.opts["welt"]["h_cm"], "breast_welt": D.opts["breast_welt"]["h_cm"]}
    for key, nm in welts:
        if key not in fr.notches:
            continue
        # the welt is set on the sewn front: lay it out with the dart closed, straight
        p0, p1 = warp(np.asarray(fr.notches[key], float), inverse=True)
        u = (p1 - p0) / np.linalg.norm(p1 - p0)
        n = np.array([-u[1], u[0]])
        if n[1] < 0:
            n = -n                                   # down the panel: the welt hangs below the mouth
        h = h_of[key]
        poly = np.array([p0, p1, p1 + n * h, p0 + n * h])
        add(*_patch_closed(pm, nm, poly, 0.25, wo["lift_mm"] / 1000, wo["thick_mm"] / 1000, max(2, rings // 2), warp),
            f"{key}_{nm}")
    out["pockets"] = (np.vstack(pv), pf, np.array(pp, int), pu, np.array(pt, int), np.array(pk, int)) if pv else None
    # --- buttons: on the left front over the holes. The bottom one is left undone; it sits on
    # the right front under the left front's lap, out of sight, and is not modelled
    bo = o["button"]
    bv, bf = [], []
    btn = np.asarray(fr.notches.get("buttons", []), float)[:o["buttoned"]]
    for i, xy in enumerate(btn):
        Xp, Np, ux, uy = pm.frame("front", [xy])
        b0 = sum(len(v) for v in bv)
        Vb, Fb = sd.button(Xp[0], Np[0], ux[0] + uy[0], bo["diam_cm"] / 100, bo["thick_mm"] / 1000,
                           sp.merge(sd.DEFAULTS["button"], {}))
        bv.append(Vb)
        bf.extend(tuple(int(j) + b0 for j in f) for f in Fb)
    out["buttons"] = (np.vstack(bv), bf, np.full(len(bf), BUTTON), None, None, None) if bv else None
    stats["details"] = {k: {"verts": int(len(v[0])), "tris": int(sum(len(f) - 2 for f in v[1]))}
                        for k, v in out.items() if v is not None}
    out["_uv"] = {"marks": marks, "tags": tags}
    return out


def _dart_warp(P):
    """Pattern (x, y) <-> the sewn front (the dart closed: what lies past the dart's back leg
    slides back by the dart's width at that height). warp(P2) maps sewn -> pattern;
    warp(P2, inverse=True) pattern -> sewn."""
    if "dart_b" not in P.inner:
        return lambda Q, inverse=False: np.asarray(Q, float)
    b, f = P.inner["dart_b"], P.inner["dart_f"]
    ys = np.linspace(min(b[:, 1].min(), f[:, 1].min()), max(b[:, 1].max(), f[:, 1].max()), 64)

    def at(poly, y):
        o_ = np.argsort(poly[:, 1])
        return np.interp(y, poly[o_, 1], poly[o_, 0])
    xb, w = at(b, ys), np.maximum(at(f, ys) - at(b, ys), 0.0)

    def warp(Q, inverse=False):
        Q = np.array(Q, float)
        inside = (Q[:, 1] >= ys[0]) & (Q[:, 1] <= ys[-1])
        x0 = np.interp(Q[:, 1], ys, xb)
        ww = np.where(inside, np.interp(Q[:, 1], ys, w), 0.0)
        if inverse:
            past = Q[:, 0] >= x0 + ww
            Q[past, 0] -= ww[past]
        else:
            past = Q[:, 0] >= x0
            Q[past, 0] += ww[past]
        return Q
    return warp


def _patch_closed(pm, name, outline, h, lift_m, thick_m, rings, warp):
    """sd.patch3d for a patch laid out on the sewn front (outline in dart-closed coordinates):
    meshed there, each vertex mapped to the pattern through the dart, UVs from the sewn layout."""
    V2, T, _ = sd.cdt_patch(outline, h)
    X, N = sd.on_drape(pm, name, warp(V2), lift_m + thick_m)
    fn = np.cross(X[T[:, 1]] - X[T[:, 0]], X[T[:, 2]] - X[T[:, 0]])
    if np.einsum("ij,ij->i", fn, N[T].mean(1)).mean() < 0:
        T = T[:, ::-1]
    N = sd.vertex_normals(X, T)
    return sd.solid(X, T, N, thick_m, rings, FU=pm.uv(name, V2)[T])


def shell_marks(C, D, pm, o):
    """Marks per panel tag (UV metres): pressed-open seams on the sewn edges and darts; on the
    fronts pick stitching in from the front edge, the V and the hem, and the buttonholes (the
    left front) as a corded lip either side of the slit."""
    sewn = set()
    for sm in D.seams:
        for ch in (sm["a"], sm["b"]):
            for pn, e, _ in ch:
                sewn.add((D.geom(pn).name, e))
    pk, ho = o["pick"], o["hole"]
    lipk = {"height": ho["lip_mm"] / 1000, "width_m": ho["lip_w_mm"] / 1000}
    out = {}
    for k, name in enumerate(C["names"]):
        P = D.geom(name)
        left = not name.endswith("_r")
        L = []
        for e, poly in P.edges:
            if (P.name, e) in sewn:
                L.append(("seam", [tuple(q) for q in pm.uv(name, poly)], {"stitch": False}))
            elif P.kind == "front" and e in ("front", "neck", "hem"):
                pin = sd._inset(poly, P.outline(), pk["in_cm"])
                L.append(("pick", [tuple(q) for q in pm.uv(name, pin)], {"pitch_m": pk["pitch_cm"] / 100}))
        for e, poly in P.inner.items():
            if (P.name, e) in sewn:
                L.append(("seam", [tuple(q) for q in pm.uv(name, poly)], {"stitch": False}))
        if P.kind == "front" and left and "buttonholes" in P.notches:
            H = np.asarray(P.notches["buttonholes"], float).reshape(-1, 2, 2)
            g = ho["half_gap_cm"]
            for a, b in H:
                for s in (-g, g):
                    L.append(("ridge", [tuple(q) for q in pm.uv(name, np.array([a + (0, s), b + (0, s)]))], lipk))
                L.append(("seam", [tuple(q) for q in pm.uv(name, np.array([a, b]))], {"stitch": False}))
        out[k + 1] = L
    return out
