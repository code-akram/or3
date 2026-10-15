"""The made trousers on the draped pattern trousers (m1 v4 T13 phase B item 3).

Like suit_detail for the jacket: the drape is one welded sheet; this makes it a garment,
every detail placed by pattern coordinates (suit_trouser_pattern's notches and lines):

  shell        the cloth with thickness (one layer of worsted; the band canvassed and thicker)
               and a half-round turned edge on the free edges (the hems, the band's top)
  creases      front (waist to hem) and back (hem to below the seat): the crease line raised
               crease_mm with a narrow falloff, and a pressed ridge in the atlas
  back pockets jetted, both sides (two jets either side of the mouth), a button under each
  marks        pressed-open seams (outseam, inseam, rise, seat, band, dart), the fly's edge (a
               lip on the left front) and its J-stitch (pick stitching), the slant side pockets
               (a lip and pick stitching in from it), the crease (a pressed ridge)

numpy + mathutils (via suit_detail). Units: metres in 3D, cm on the pattern. Parts: 0 wool
outside, 1 inside (wool: unlined), 2 turned edge, 3 button.
"""

import numpy as np

from . import suit_detail as sd
from . import suit_pattern as sp

WOOL, INSIDE, EDGE, BUTTON = 0, 1, 2, 3

DEFAULTS = {
    "thick_mm": 1.2,             # one cloth (the hem turn-up and seams are inside it)
    "band_thick_mm": 3.0,        # the band: cloth, canvas, curtain
    "edge_rings": 4,
    "crease": {"mm": 1.2, "w_mm": 7.0, "ridge_mm": 0.25, "ridge_w_mm": 1.2},
    "jet": {"h_cm": 0.5, "gap_cm": 0.06, "thick_mm": 1.6, "lift_mm": 0.3},
    "button": {"diam_cm": 1.7, "thick_mm": 3.0, "below_cm": 1.4},
    "pick": {"in_cm": 0.6, "pitch_cm": 0.6},
    "lip": {"in_cm": 0.15, "mm": 0.7, "w_mm": 2.2},
}


def _crease_ids(C, wm):
    """Welded vertex ids of each panel copy's crease line, in order: {name: ids}."""
    out = {}
    for (pn, e, j), g in C["gid"].items():
        if e == "line:crease":
            out.setdefault(pn, {})[j] = int(wm[g])
    return {pn: np.array([d[k] for k in sorted(d)]) for pn, d in out.items()}


def _dist_to_polyline(P, Q):
    """Distance from each point P (n, 3) to the polyline Q (k, 3)."""
    a, b = Q[:-1], Q[1:]
    ab = b - a
    L2 = np.maximum((ab * ab).sum(1), 1e-12)
    out = np.full(len(P), np.inf)
    for s in range(0, len(P), 4096):
        p = P[s:s + 4096]
        t = np.clip(((p[:, None, :] - a[None]) * ab[None]).sum(2) / L2[None], 0, 1)
        q = a[None] + t[..., None] * ab[None]
        out[s:s + 4096] = np.linalg.norm(p[:, None, :] - q, axis=2).min(1)
    return out


def build(C, D, wm, X, Tw, opts=None, stats=None):
    """The made trousers on the drape (X, Tw welded). Returns {name: (V, F, part, UV, tag,
    kind)} plus "_uv": {"marks": {name: {tag: marks}}, "tags": {name: {tag: label}}}."""
    o = sp.merge(DEFAULTS, opts or {})
    stats = {} if stats is None else stats
    rings = o["edge_rings"]
    X = np.asarray(X, float).copy()
    Tw = np.asarray(Tw, int)
    pm = sd.PanelMap(C, wm, X, Tw, D)
    # --- the creases: raise the line, falling off over w either side
    co = o["crease"]
    N0 = sd.vertex_normals(X, Tw)
    cids = _crease_ids(C, wm)
    lift = np.zeros(len(X))
    for pn, ids in cids.items():
        if len(ids) < 2:
            continue
        d = _dist_to_polyline(X, X[ids])
        w = np.clip(1.0 - d / (co["w_mm"] / 1000.0), 0.0, 1.0) ** 2
        lift = np.maximum(lift, w)
    X = X + N0 * (lift * co["mm"] / 1000.0)[:, None]
    pm = sd.PanelMap(C, wm, X, Tw, D)
    # --- the shell
    N = sd.vertex_normals(X, Tw)
    t = np.full(len(X), o["thick_mm"] / 1000.0)
    band_v = np.zeros(len(X), bool)
    for name, I in C["info"].items():
        if I["kind"] == "band":
            band_v[wm[I["base"] + np.arange(len(I["V"]))]] = True
    t[band_v] = o["band_thick_mm"] / 1000.0
    FU, ftag = sd.shell_uv(C, wm, Tw, pm, stats)
    V, F, part, U = sd.solid(X, Tw, N, t, rings, FU=FU)
    part = np.where(part == 1, INSIDE, part)
    kind = U["kind"].copy()
    # (a separate smooth group for the crease's far side shaded the whole strip between the
    # crease and the centre front a tone off in EEVEE, run t13t-d3: the crease is geometry and
    # the atlas ridge instead)
    src = U["src"]
    tags = {"shell": {k + 1: n for k, n in enumerate(C["names"])}, "pockets": {}}
    marks = {"shell": shell_marks(C, D, pm, o), "pockets": {}}
    out = {"shell": (V, F, part, U["uv"], ftag[src], kind)}
    stats["shell"] = {"verts": int(len(V)), "tris": int(sum(len(f) - 2 for f in F)),
                      "crease_lines": len(cids)}
    # --- back pockets: two jets either side of the mouth, a button under
    jo, bo = o["jet"], o["button"]
    pv, pf, pp, pu, pt, pk_ = [], [], [], [], [], []

    def add(V_, F_, part_, U_, label):
        b = sum(len(v) for v in pv)
        pv.append(V_)
        pf.extend(tuple(int(i) + b for i in f) for f in F_)
        pp.extend(list(part_))
        pu.extend(U_["uv"])
        pk_.extend(list(U_["kind"]))
        tg = len(tags["pockets"]) + 1
        tags["pockets"][tg] = label
        pt.extend([tg] * len(F_))
    bv, bf = [], []
    back = D.geom("back")
    if "back_pocket" in back.notches:
        p0, p1 = np.asarray(back.notches["back_pocket"], float)
        u = (p1 - p0) / np.linalg.norm(p1 - p0)
        n = np.array([-u[1], u[0]])
        if n[1] < 0:
            n = -n                                  # down the panel
        g, hj = jo["gap_cm"], jo["h_cm"]
        for nm in ("back", "back_r"):
            for lo, hi, lab in ((-hj, -g, "jet_top"), (g, hj, "jet_bot")):
                poly = np.array([p0 + n * lo, p1 + n * lo, p1 + n * hi, p0 + n * hi])
                add(*sd.patch3d(pm, nm, poly, 0.25, jo["lift_mm"] / 1000, jo["thick_mm"] / 1000, max(2, rings // 2)),
                    f"{lab}_{nm}")
            c = 0.5 * (p0 + p1) + n * (hj + bo["below_cm"])
            Xp, Np, ux, uy = pm.frame(nm, [c])
            b0 = sum(len(v) for v in bv)
            Vb, Fb = sd.button(Xp[0], Np[0], ux[0] + uy[0], bo["diam_cm"] / 100, bo["thick_mm"] / 1000,
                               sp.merge(sd.DEFAULTS["button"], {}))
            bv.append(Vb)
            bf.extend(tuple(int(i) + b0 for i in f) for f in Fb)
    out["pockets"] = (np.vstack(pv), pf, np.array(pp, int), pu, np.array(pt, int), np.array(pk_, int)) if pv else None
    out["buttons"] = (np.vstack(bv), bf, np.full(len(bf), BUTTON), None, None, None) if bv else None
    stats["details"] = {k: {"verts": int(len(v[0])), "tris": int(sum(len(f) - 2 for f in v[1]))}
                        for k, v in out.items() if v is not None}
    out["_uv"] = {"marks": marks, "tags": tags}
    return out


def shell_marks(C, D, pm, o):
    """Marks per panel tag (UV metres): pressed-open seams on every sewn edge, the left front's
    fly edge a lip (the right's fly under it a groove), the J-stitch and the slant pockets
    pick-stitched, the slant pocket's mouth a lip, the creases a pressed ridge."""
    sewn = set()
    for sm in D.seams:
        for ch in (sm["a"], sm["b"]):
            for pn, e, _ in ch:
                sewn.add((D.geom(pn).name, e))
    pk, lp, co = o["pick"], o["lip"], o["crease"]
    lipk = {"height": lp["mm"] / 1000, "width_m": lp["w_mm"] / 1000}
    out = {}
    for k, name in enumerate(C["names"]):
        P = D.geom(name)
        left = not name.endswith("_r")
        L = []
        for e, poly in P.edges:
            if (P.name, e) not in sewn:
                continue
            if P.kind == "front" and e == "fly" and left:
                L.append(("ridge", [tuple(q) for q in pm.uv(name, sd._inset(poly, P.outline(), lp["in_cm"]))], lipk))
                continue
            L.append(("seam", [tuple(q) for q in pm.uv(name, poly)], {"stitch": False}))
        if "crease" in P.lines:
            L.append(("ridge", [tuple(q) for q in pm.uv(name, P.lines["crease"])],
                      {"height": co["ridge_mm"] / 1000, "width_m": co["ridge_w_mm"] / 1000}))
        if P.kind == "front":
            if left and "fly_j" in P.notches:
                L.append(("pick", [tuple(q) for q in pm.uv(name, P.notches["fly_j"])], {"pitch_m": pk["pitch_cm"] / 100}))
            if "side_pocket" in P.notches:
                m0 = np.asarray(P.notches["side_pocket"], float)
                mouth = sp.at_params(m0, np.linspace(0, 1, 12))
                L.append(("ridge", [tuple(q) for q in pm.uv(name, mouth)], lipk))
                pin = sd._inset(mouth, P.outline(), pk["in_cm"])
                # in toward the centre front (the pocket's facing side)
                if pin[:, 0].mean() < mouth[:, 0].mean():
                    pin = mouth + (mouth - pin)
                L.append(("pick", [tuple(q) for q in pm.uv(name, pin)], {"pitch_m": pk["pitch_cm"] / 100}))
        out[k + 1] = L
    return out
