"""The made shirt on the draped pattern shirt (m1 v4 T13 phase B item 5).

Like suit_waistcoat_detail: the drape (suit_shirt_pattern panels, sewn and draped) is one welded
sheet; this makes it a shirt. The collar and the cuffs are not simulated (a fused collar and a
fused cuff are stiff, shaped pieces): they are modelled, the collar on the suit_neck frame (the
band and fall the jacket's collar is fitted to), the cuffs round the wrist.

  shell     the body, yoke and sleeves with a cotton's thickness (thick_mm), half-round turned
            edges; the left front's placket stands proud by its two extra layers (placket
            lift), with a pressed fold on its inner edge
  collar    suit_neck.build_shirt_collar's band, fold and fall (the frame the jacket collar is
            fitted to), thickened (two layers and the fused interlining), its edges rounded;
            the band's closure under the knot
  cuffs     barrel cuffs: a fused band cuff_round round the wrist, h_cm deep, the outer end
            lapping over the inner one at the back of the wrist, resting on the top of the wrist
            (gravity) and open below; one button
  buttons   the front's buttons on the placket at the centre front, one per cuff
  marks     flat-felled seams (a groove and a row of stitching 6 mm off it), the yoke seam
            topstitched, the placket's fold and its two rows of stitching, the buttonholes
            (vertical, on the placket), the collar's and the cuffs' edge stitching

numpy + mathutils (via suit_detail). Parts: 0 shirting outside, 1 inside, 2 turned edge, 3 button.
"""

import math

import numpy as np

from . import suit_detail as sd
from . import suit_pattern as sp

OUT, INSIDE, EDGE, BUTTON = 0, 1, 2, 3

DEFAULTS = {
    "thick_mm": 0.45,
    "edge_rings": 3,
    "placket": {"lift_mm": 0.5, "soft_cm": 0.25, "stitch_in_cm": 0.3},
    "collar": {"thick_mm": 1.1, "rings": 4, "stitch_in_m": 0.005},
    "cuff": {"thick_mm": 1.4, "rings": 4, "overlap_cm": 2.2, "gap_mm": 1.5, "rows": 9, "seg": 120,
             "stitch_in_cm": 0.5, "theta0": -2.2, "lap_ramp_cm": 1.2},
    "button": {"diam_cm": 1.1, "thick_mm": 2.0},
    "felled_off_cm": 0.6,
    "hole": {"lip_mm": 0.4, "lip_w_mm": 1.0, "half_gap_cm": 0.08},
}


# --- the cuff frame (before the drape: the sleeve's end is held to it) ----------------------------

def _hull2(p):
    from .suit_pattern import _hull
    return _hull(p)


def cuff_frame(axis, L, Nf, Ff, s_top, s_bot, body_co, round_m, gap_m, phi_n=96):
    """The cuff round the arm axis polyline (axis (k, 3), cumulative length L, transported
    frame Nf, Ff; s in metres along it): the body's section between s_top and s_bot (convex
    hull, in the axis frame), offset evenly until its length is round_m (the cuff's inside),
    then dropped with gravity onto the top of the wrist (gap_m left there). Returns a dict
    with the ring (radii about its centre per angle phi) and a point(theta, s, dr) mapper."""
    def at(s):
        k = int(np.clip(np.searchsorted(L, s), 1, len(L) - 1))
        f = (s - L[k - 1]) / max(L[k] - L[k - 1], 1e-12)
        c = axis[k - 1] + (axis[k] - axis[k - 1]) * f
        n = Nf[k - 1] + (Nf[k] - Nf[k - 1]) * f
        fr = Ff[k - 1] + (Ff[k] - Ff[k - 1]) * f
        t = axis[k] - axis[k - 1]
        t = t / np.linalg.norm(t)
        n = n - np.dot(n, t) * t
        n /= np.linalg.norm(n)
        fr = np.cross(t, n) * np.sign(np.dot(np.cross(t, n), fr))
        return c, t, n, fr

    sm = 0.5 * (s_top + s_bot)
    c0, t0, n0, f0 = at(sm)
    rel = body_co - c0
    s_of = sm + rel @ t0
    q = rel - np.outer(rel @ t0, t0)
    near = (s_of > s_top - 0.01) & (s_of < s_bot + 0.004) & (np.linalg.norm(q, axis=1) < 0.07)
    P2 = np.stack([q[near] @ n0, q[near] @ f0], 1)
    H = _hull2(P2)
    cen = H.mean(0)
    phi = np.linspace(-math.pi, math.pi, phi_n, endpoint=False)
    # the hull's radius per angle about its centre (ray / polygon)
    r = np.zeros(phi_n)
    Hn = np.roll(H, -1, axis=0)
    for i, a in enumerate(phi):
        d = np.array([math.cos(a), math.sin(a)])
        best = 0.0
        for p, p2 in zip(H - cen, Hn - cen):
            e = p2 - p
            den = d[0] * (-e[1]) - d[1] * (-e[0])
            if abs(den) < 1e-12:
                continue
            tt = (p[0] * (-e[1]) - p[1] * (-e[0])) / den
            u = (d[0] * p[1] - d[1] * p[0]) / den
            if tt > 0 and -1e-9 <= u <= 1 + 1e-9:
                best = max(best, tt)
        r[i] = best
    # smooth round the ring (a fused cuff does not follow the wrist's corners), kept outside
    f = np.fft.rfft(r)
    f[5:] = 0
    rs = np.fft.irfft(f, phi_n)
    rs += max(0.0, float((r - rs).max()))
    # offset evenly to the cuff's round
    def perim(rr):
        x, y = rr * np.cos(phi), rr * np.sin(phi)
        return float(np.hypot(np.diff(np.r_[x, x[:1]]), np.diff(np.r_[y, y[:1]])).sum())
    lo, hi = 0.0, 0.05
    for _ in range(50):
        e = 0.5 * (lo + hi)
        if perim(rs + e) < round_m:
            lo = e
        else:
            hi = e
    e = 0.5 * (lo + hi)
    R = rs + e
    # gravity in the ring's plane: the cuff hangs, its top resting on the wrist
    g = np.array([0.0, 0.0, -1.0])
    g2 = np.array([g @ n0, g @ f0])
    shift = np.zeros(2)
    if np.linalg.norm(g2) > 1e-6:
        g2 /= np.linalg.norm(g2)
        shift = g2 * max(0.0, e - gap_m)
    C2 = cen + shift

    def Rof(theta):
        return np.interp(np.mod(np.asarray(theta, float) + math.pi, 2 * math.pi) - math.pi, phi, R,
                         period=2 * math.pi)

    def point(theta, s, dr=0.0):
        c, t, n, fr = at(s)
        theta = np.asarray(theta, float)
        rr = Rof(theta) + dr
        x2 = C2[0] + rr * np.cos(theta)
        y2 = C2[1] + rr * np.sin(theta)
        return c + np.multiply.outer(x2, n) + np.multiply.outer(y2, fr)

    return {"s_top": s_top, "s_bot": s_bot, "phi": phi, "R": R, "C2": C2, "offset_m": e, "point": point,
            "round_m": round_m, "axis_mid": c0, "t": t0, "n": n0, "fr": f0,
            "gap_top_mm": round(gap_m * 1000, 2), "gap_bottom_mm": round((2 * e - gap_m) * 1000, 2)}


def cuff_mesh(cf, o, mirror=False):
    """The cuff band (outer surface) as a quad grid, its UVs (m) and the button point. The band
    runs from theta0 once round plus the overlap; the end laps over the start (lifted by the
    cuff's thickness over lap_ramp)."""
    co = o["cuff"]
    t = co["thick_mm"] / 1000
    Lc = cf["round_m"]
    ov = co["overlap_cm"] / 100
    nu = co["seg"]
    nv = co["rows"]
    u = np.linspace(0.0, Lc + ov, nu + 1)
    th = co["theta0"] + 2 * math.pi * u / Lc
    ramp = co["lap_ramp_cm"] / 100
    lift = (t + 0.0003) * sp.smoothstep((u - (Lc - ramp)) / ramp)
    s = np.linspace(cf["s_top"], cf["s_bot"], nv + 1)
    P = np.zeros((nv + 1, nu + 1, 3))
    UV = np.zeros((nv + 1, nu + 1, 2))
    for j, sj in enumerate(s):
        P[j] = cf["point"](th, sj, t + lift)
        UV[j, :, 0] = u
        UV[j, :, 1] = sj - cf["s_top"]
    if mirror:
        P[..., 0] *= -1
    # the button: on the outer lap, half way along it, mid height
    ub = Lc + ov * 0.5
    thb = co["theta0"] + 2 * math.pi * ub / Lc
    sb_ = 0.5 * (cf["s_top"] + cf["s_bot"])
    pb = cf["point"](np.array([thb]), sb_, 2 * t + 0.0003)[0]
    pn = cf["point"](np.array([thb]), sb_, 2 * t + 0.0013)[0] - pb
    pn /= np.linalg.norm(pn)
    pu = cf["point"](np.array([thb + 0.05]), sb_, 2 * t + 0.0003)[0] - pb
    if mirror:
        pb[0] *= -1
        pn[0] *= -1
        pu[0] *= -1
    return P, UV, (pb, pn, pu / np.linalg.norm(pu)), {"Lc": Lc, "ov": ov, "ub": ub}


def grid_tris(nr, nc, closed=False):
    T = []
    for j in range(nr - 1):
        for i in range(nc - 1 + (1 if closed else 0)):
            a, b = j * nc + i, j * nc + (i + 1) % nc
            c, d = (j + 1) * nc + (i + 1) % nc, (j + 1) * nc + i
            T += [(a, b, c), (a, c, d)]
    return np.array(T, int)


def _outward_tris(X, T, centre_fn):
    """Flip T so the faces look away from centre_fn(face centres)."""
    fn = np.cross(X[T[:, 1]] - X[T[:, 0]], X[T[:, 2]] - X[T[:, 0]])
    c = X[T].mean(1)
    if np.einsum("ij,ij->i", fn, c - centre_fn(c)).mean() < 0:
        T = T[:, ::-1].copy()
    return T


def collar_from_grid(rows, uvs, drop_last=1):
    """The suit_neck collar grid (rows of 3D points, per-row UVs) as arrays: X (r*c, 3), UV."""
    R = rows[:len(rows) - drop_last] if drop_last else rows
    U = uvs[:len(uvs) - drop_last] if drop_last else uvs
    X = np.array([[tuple(p) for p in row] for row in R], float)
    UV = np.array([[tuple(q) for q in row] for row in U], float)
    return X, UV


def build(C, D, wm, X, Tw, collar=None, cuffs=None, opts=None, stats=None):
    """The made shirt on the drape (X, Tw welded). collar: {"X": (r, c, 3), "UV": (r, c, 2),
    "closure": (X, UV) or None, "axis": fn(points) -> nearest neck axis points}; cuffs: [cuff
    frame (left), mirrored?]. Returns {name: (V, F, part, UV, tag, kind)} plus "_uv"."""
    o = sp.merge(DEFAULTS, opts or {})
    stats = {} if stats is None else stats
    rings = o["edge_rings"]
    X = np.asarray(X, float).copy()
    Tw = np.asarray(Tw, int)
    pm = sd.PanelMap(C, wm, X, Tw, D)
    N = sd.vertex_normals(X, Tw)
    # the placket: the left front's band past the fold, three layers: proud by lift_mm
    pk = o["placket"]
    F = D.frame
    fold_x = F["x_edge"] - D.opts["placket_cm"]
    I = C["info"]["front"]
    ids = wm[I["base"] + np.arange(len(I["V"]))]
    w = sp.smoothstep((I["V"][:, 0] - fold_x) / pk["soft_cm"])
    lift = np.zeros(len(X))
    np.maximum.at(lift, ids, w * pk["lift_mm"] / 1000)
    X = X + N * lift[:, None]
    pm = sd.PanelMap(C, wm, X, Tw, D)
    N = sd.vertex_normals(X, Tw)
    t = np.full(len(X), o["thick_mm"] / 1000.0)
    FU, ftag = sd.shell_uv(C, wm, Tw, pm, stats)
    V, Fs, part, U = sd.solid(X, Tw, N, t, rings, FU=FU)
    tag = ftag[U["src"]]
    names = list(C["names"])
    tags = {"shell": {k + 1: n for k, n in enumerate(names)}, "collar": {}, "cuffs": {}}
    marks = {"shell": shell_marks(C, D, pm, o), "collar": {}, "cuffs": {}}
    out = {"shell": (V, Fs, part, U["uv"], tag, U["kind"].copy())}
    stats["shell"] = {"verts": int(len(V)), "tris": int(sum(len(f) - 2 for f in Fs)),
                      "placket_lift_verts": int((lift > 1e-5).sum())}
    # --- the collar
    if collar is not None:
        co = o["collar"]
        tc = co["thick_mm"] / 1000
        pv, pf, pp, pu, pt, pk_ = [], [], [], [], [], []
        pieces = [("collar", collar["X"], collar["UV"])]
        if collar.get("closure") is not None:
            pieces.append(("closure", collar["closure"][0], collar["closure"][1]))
        for k_, (label, Xg, UVg) in enumerate(pieces):
            nr, nc = Xg.shape[:2]
            Xc = Xg.reshape(-1, 3)
            Tc = _outward_tris(Xc, grid_tris(nr, nc), collar["axis"])
            Nc = sd.vertex_normals(Xc, Tc)
            FUc = UVg.reshape(-1, 2)[Tc]
            Vc, Fc, partc, Uc = sd.solid(Xc, Tc, Nc, tc, co["rings"], FU=FUc)
            b = sum(len(v) for v in pv)
            pv.append(Vc)
            pf.extend(tuple(int(i) + b for i in f) for f in Fc)
            pp.extend(list(partc))
            pu.extend(Uc["uv"])
            pk_.extend(list(Uc["kind"]))
            tg = k_ + 1
            tags["collar"][tg] = label
            pt.extend([tg] * len(Fc))
            if label == "collar":
                # stitching: the fall's edge (stitch_in from it), the band's top and its base
                ug = UVg
                ml = []
                vi = ug[-1, :, 1] - co["stitch_in_m"]
                ml.append(("topstitch", [(float(a), float(b_)) for a, b_ in zip(ug[-1, :, 0], vi)],
                           {"pitch_m": 0.0022, "height": 0.00012}))
                for rr, dv in ((2, -0.002), (0, 0.003)):
                    ml.append(("topstitch", [(float(a), float(b_ + dv)) for a, b_ in zip(ug[rr, :, 0], ug[rr, :, 1])],
                               {"pitch_m": 0.0022, "height": 0.00012}))
                marks["collar"][tg] = ml
            else:
                marks["collar"][tg] = []
        out["collar"] = (np.vstack(pv), pf, np.array(pp, int), pu, np.array(pt, int), np.array(pk_, int))
        stats["collar"] = {"tris": int(sum(len(f) - 2 for f in pf)), "rows": int(collar["X"].shape[0]),
                           "cols": int(collar["X"].shape[1])}
    # --- the cuffs
    bo = o["button"]
    bv, bf = [], []

    def add_button(c, n, u, diam, thick):
        b0 = sum(len(v) for v in bv)
        Vb, Fb = sd.button(c, n, u, diam, thick, sp.merge(sd.DEFAULTS["button"], {}))
        bv.append(Vb)
        bf.extend(tuple(int(j) + b0 for j in f) for f in Fb)

    if cuffs:
        cv, cfc, cpp, cpu, cpt, cpk = [], [], [], [], [], []
        cst = {}
        for k_, (cf, mirror) in enumerate(cuffs):
            P, UVg, (pb, pn, pu_), info = cuff_mesh(cf, o, mirror)
            nr, nc = P.shape[:2]
            Xc = P.reshape(-1, 3)
            ax_c = cf["axis_mid"] * (np.array([-1.0, 1, 1]) if mirror else 1.0)
            ax_t = cf["t"] * (np.array([-1.0, 1, 1]) if mirror else 1.0)

            def centre(c_, ax_c=ax_c, ax_t=ax_t):
                rel = c_ - ax_c
                return ax_c + np.outer(rel @ ax_t, ax_t)
            Tc = _outward_tris(Xc, grid_tris(nr, nc), centre)
            Nc = sd.vertex_normals(Xc, Tc)
            co = o["cuff"]
            Vc, Fc, partc, Uc = sd.solid(Xc, Tc, Nc, co["thick_mm"] / 1000, co["rings"], FU=UVg.reshape(-1, 2)[Tc])
            b = sum(len(v) for v in cv)
            cv.append(Vc)
            cfc.extend(tuple(int(i) + b for i in f) for f in Fc)
            cpp.extend(list(partc))
            cpu.extend(Uc["uv"])
            cpk.extend(list(Uc["kind"]))
            tg = k_ + 1
            tags["cuffs"][tg] = "cuff_r" if mirror else "cuff"
            cpt.extend([tg] * len(Fc))
            # stitching round the cuff's edges, the buttonhole on the outer lap
            si = co["stitch_in_cm"] / 100
            Lt = info["Lc"] + info["ov"]
            hgt = cf["s_bot"] - cf["s_top"]
            ml = [("topstitch", [(0.0 + si, si), (Lt - si, si)], {"pitch_m": 0.0022, "height": 0.00012}),
                  ("topstitch", [(0.0 + si, hgt - si), (Lt - si, hgt - si)], {"pitch_m": 0.0022, "height": 0.00012}),
                  ("topstitch", [(Lt - si, si), (Lt - si, hgt - si)], {"pitch_m": 0.0022, "height": 0.00012})]
            ho = o["hole"]
            lipk = {"height": ho["lip_mm"] / 1000, "width_m": ho["lip_w_mm"] / 1000}
            for dv in (-ho["half_gap_cm"] / 100, ho["half_gap_cm"] / 100):
                ml.append(("ridge", [(info["ub"] - 0.003, hgt / 2 + dv), (info["ub"] + 0.012, hgt / 2 + dv)], lipk))
            marks["cuffs"][tg] = ml
            add_button(pb, pn, pu_, bo["diam_cm"] / 100, bo["thick_mm"] / 1000)
            cst["cuff_r" if mirror else "cuff"] = {"round_cm": round(info["Lc"] * 100, 2),
                                                    "gap_top_mm": cf["gap_top_mm"], "gap_bottom_mm": cf["gap_bottom_mm"]}
        out["cuffs"] = (np.vstack(cv), cfc, np.array(cpp, int), cpu, np.array(cpt, int), np.array(cpk, int))
        stats["cuffs"] = cst
    # --- the front's buttons, on the placket at the centre front
    fr = D.geom("front")
    btn = np.asarray(fr.notches.get("buttons", []), float)
    out["_front_button_v0"] = sum(len(v) for v in bv)
    if len(btn):
        Xp, Np, ux, uy = pm.frame("front", btn)
        for i in range(len(btn)):
            add_button(Xp[i] + Np[i] * 0.0002, Np[i], ux[i] + uy[i], bo["diam_cm"] / 100, bo["thick_mm"] / 1000)
    out["buttons"] = (np.vstack(bv), bf, np.full(len(bf), BUTTON), None, None, None) if bv else None
    stats["details"] = {k: {"verts": int(len(v[0])), "tris": int(sum(len(f) - 2 for f in v[1]))}
                        for k, v in out.items() if v is not None and not k.startswith("_")}
    out["_uv"] = {"marks": marks, "tags": tags}
    return out


def shell_marks(C, D, pm, o):
    """Marks per panel tag (UV metres): the flat-felled seams (a groove and a row of stitching
    felled_off_cm off it), the yoke seam topstitched on the yoke, the left placket's fold and its
    two rows of stitching, vertical buttonholes, the hem's stitching, the sleeve placket."""
    sewn = {}
    for sm in D.seams:
        for ch in (sm["a"], sm["b"]):
            for pn, e, _ in ch:
                sewn[(D.geom(pn).name, e)] = sm["name"].replace("_r", "")
    off = o["felled_off_cm"]
    st_ = {"pitch_m": 0.0022, "height": 0.00012}
    ho = o["hole"]
    lipk = {"height": ho["lip_mm"] / 1000, "width_m": ho["lip_w_mm"] / 1000}
    out = {}
    for k, name in enumerate(C["names"]):
        P = D.geom(name)
        left = not name.endswith("_r")
        L = []
        outl = P.outline()
        for e, poly in P.edges:
            sname = sewn.get((P.name, e))
            if sname is None:
                if e == "hem":
                    L.append(("topstitch", [tuple(q) for q in pm.uv(name, sd._inset(poly, outl, 0.6))], st_))
                continue
            if sname.startswith("cb"):
                continue                      # a fold: no seam
            L.append(("seam", [tuple(q) for q in pm.uv(name, poly)], {"stitch": False}))
            # felled: the stitching on one side of the seam (the yoke's and the sleeve's side)
            if (P.name, sname) in (("yoke", "yoke"), ("yoke", "shoulder"), ("sleeve", "armhole"),
                                   ("back", "side"), ("sleeve", "underarm")) and e != "under_b":
                L.append(("topstitch", [tuple(q) for q in pm.uv(name, sd._inset(poly, outl, off))], st_))
        if P.kind == "front" and left:
            xe = D.frame["x_edge"]
            pkw = D.opts["placket_cm"]
            fold = np.asarray(P.notches["placket_fold"], float)
            L.append(("ridge", [tuple(q) for q in pm.uv(name, fold + (0.05, 0.0))], {"height": 0.00025, "width_m": 0.0012}))
            si = o["placket"]["stitch_in_cm"]
            for x in (xe - si, xe - pkw + si):
                L.append(("topstitch", [tuple(q) for q in pm.uv(name, np.array([[x, fold[0, 1]], [x, fold[1, 1]]]))], st_))
            H = np.asarray(P.notches["buttonholes"], float).reshape(-1, 2, 2)
            g = ho["half_gap_cm"]
            for a, b in H:
                for s in (-g, g):
                    L.append(("ridge", [tuple(q) for q in pm.uv(name, np.array([a + (s, 0), b + (s, 0)]))], lipk))
        if P.kind == "top_sleeve" and "placket" in P.notches:
            pl = np.asarray(P.notches["placket"], float)
            L.append(("ridge", [tuple(q) for q in pm.uv(name, pl)], {"height": 0.0003, "width_m": 0.0015}))
            L.append(("topstitch", [tuple(q) for q in pm.uv(name, pl + (0.6, 0.0))], st_))
        out[k + 1] = L
    return out
