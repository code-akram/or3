"""Suit pattern spike runner (m1 v4 step 5; report: bench/m1/v4/suit-spike.md).

    bench/m1/v4/suit_spike.sh [--base RUN] [--out DIR]     (wrapper: paths, nice, -t 3)

    blender -b -t 3 --factory-startup --python-exit-code 1 --python bench/m1/v4/suit_spike.py -- \
        --system-assets ... --suit-assets ... --config bench/m1/variants/direction.json \
        --base-blend RUN/character.blend --out-dir DIR [--measure-only] [--no-render]

1. body       a partial build (MPFB human, head edits, rig, suit capture) gives the
              full rest-pose body with skin weights (the kept build .blend has its
              enclosed faces deleted, so it cannot be the collider)
2. base       the shipped garments and the full rig are appended from a kept build
              .blend (the lofted jacket for the A/B; shirt, waistcoat, trousers as
              colliders)
3. measure    suit_pattern.BodyMeasure on the rest body
4. draft      suit_pattern.draft -> flat panels, seams, notches (pattern sheet PNG)
5. sew        panels meshed (constrained Delaunay), placed round the body in the
              drape pose P0, sewn with cloth sewing springs, pose ramped to the rest
              pose, settled; then (optional) ramped on to a bent-arm pose
6. keep       sewn seams welded, the settled cloth kept as geometry
7. render     EEVEE clay, lofted vs pattern, front / 3/4 / profile / back (+ bent arm)

Public build only (no fan input). Outputs under DIR (data/build/..., gitignored).
"""

import argparse
import json
import math
import os
import sys
import time

import bpy
import numpy as np
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "blender"))

from character import body as cbody  # noqa: E402
from character import config, head, rig, suit  # noqa: E402
from character import suit_pattern as sp  # noqa: E402
from character.context import Build, Mpfb  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--system-assets", required=True)
ap.add_argument("--suit-assets", required=True)
ap.add_argument("--config", required=True)
ap.add_argument("--base-blend", required=True)
ap.add_argument("--out-dir", required=True)
ap.add_argument("--measure-only", action="store_true")
ap.add_argument("--no-render", action="store_true")
ap.add_argument("--no-clay", action="store_true", help="spike 2: no clay renders (textures and spike.blend still made)")
ap.add_argument("--place-only", action="store_true", help="stop after placing the panels (render them)")
ap.add_argument("--opts", default="", help="JSON override for the spike options (or @file.json)")
ap.add_argument("--from-run", default="", help="spike 2: reuse this run's drape (drape2.npz); rever + renders only")
ap.add_argument("--v2", action="store_true", help="spike 2 (T13): two-stage weld, hull collider, modelled rever")
A = ap.parse_args(argv)
os.makedirs(A.out_dir, exist_ok=True)
T = {}
T0 = time.perf_counter()


def tick(name, t):
    T[name] = round(time.perf_counter() - t, 2)
    print(f"[spike] {name}: {T[name]} s", flush=True)


# --- 1. body ----------------------------------------------------------------------------------

def capture_body():
    cfg = config.load(A.config, {"assets": {"system": A.system_assets, "suit": A.suit_assets}})
    if cfg.get("fan"):
        raise SystemExit("suit_spike: public build only (config carries a fan block)")
    b = Build(cfg)
    b.mpfb = Mpfb(cfg["assets"]["system"], cfg["assets"]["suit"])
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    cbody.create(b)
    head.edit_base(b)
    rig.add(b)
    suit.add(b)
    src_me, names = b.suit_src
    # drop the live human; keep only the captured mesh (with its vertex groups)
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    ob = bpy.data.objects.new("spike_body", src_me)
    for n in names:
        ob.vertex_groups.new(name=n)
    bpy.context.scene.collection.objects.link(ob)
    return ob, names


def body_arrays(ob, arm):
    me = ob.data
    n = len(me.vertices)
    co = np.empty(n * 3)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    names = [g.name for g in ob.vertex_groups]
    bones = set(arm.data.bones.keys())
    dom = np.array([""] * n, dtype=object)
    for v in me.vertices:
        best, bw = "", 0.0
        for g in v.groups:
            nm = names[g.group]
            if nm in bones and g.weight > bw:
                best, bw = nm, g.weight
        dom[v.index] = best
    J = {bn.name: (tuple(arm.matrix_world @ bn.head_local), tuple(arm.matrix_world @ bn.tail_local))
         for bn in arm.data.bones}
    me.calc_loop_triangles()
    tris = np.empty(len(me.loop_triangles) * 3, int)
    me.loop_triangles.foreach_get("vertices", tris)
    return co, tris.reshape(-1, 3), dom.astype(str), J


# --- 2. base ------------------------------------------------------------------------------------

BASE_PARTS = ("suit_jacket", "suit_shirt", "suit_waistcoat", "suit_trousers", "suit_shoes", "suit_tie",
              "suit_buttons")


def append_base(path):
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        dst.objects = [n for n in src.objects if n.endswith("rig_export")
                       or any(p in n for p in BASE_PARTS)]
    coll = bpy.data.collections.new("base")
    bpy.context.scene.collection.children.link(coll)
    arm = None
    out = {}
    for o in dst.objects:
        if o is None:
            continue
        coll.objects.link(o)
        if o.type == "ARMATURE":
            arm = o
    for o in dst.objects:
        if o is None or o.type != "MESH":
            continue
        for m in o.modifiers:
            if m.type == "ARMATURE":
                m.object = arm
        key = next(p for p in BASE_PARTS if p in o.name)
        out[key.replace("suit_", "")] = o
    return arm, out


# --- 3. placement helpers (block cm -> world m) -----------------------------------------------

def _pip(pts, poly):
    """Points inside a closed polygon (even-odd)."""
    x, y = pts[:, 0][:, None], pts[:, 1][:, None]
    a, b = poly, np.roll(poly, -1, axis=0)
    c = ((a[:, 1] > y) != (b[:, 1] > y)) & (x < (b[:, 0] - a[:, 0]) * (y - a[:, 1])
                                            / np.where(b[:, 1] != a[:, 1], b[:, 1] - a[:, 1], 1e-12) + a[:, 0])
    return c.sum(1) % 2 == 1


def _dist_polyline(pts, poly, closed=False):
    a = poly if not closed else poly
    b = np.roll(poly, -1, axis=0) if closed else poly[1:]
    a = a if closed else poly[:-1]
    d = b - a
    L2 = np.maximum((d ** 2).sum(1), 1e-12)
    t = np.clip(((pts[:, None, :] - a[None]) * d[None]).sum(2) / L2[None], 0, 1)
    q = a[None] + t[..., None] * d[None]
    return np.linalg.norm(pts[:, None, :] - q, axis=2).min(1)


class Rings:
    """Eased hull rings of the body (torso above the waist, trunk below), from
    the centre back round the wearer's left to the centre front."""

    def __init__(self, BM, M, gap):
        self.BM, self.M, self.gap = BM, M, gap
        self.cache = {}

    def ring(self, z):
        k = round(z, 3)
        if k not in self.cache:
            fm = self.BM.f_torso if z > self.M["waist_z"] - 0.02 else self.BM.f_trunk
            d, _ = self.BM.ring_from_cb(z, fm, dense=300)
            t = np.gradient(d, axis=0)
            t /= np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-12)
            nrm = np.stack([-t[:, 1], t[:, 0]], 1)
            if nrm[len(nrm) // 2, 0] < 0:
                nrm = -nrm
            e = d + nrm * self.gap
            arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(e, axis=0), axis=1))])
            self.cache[k] = (e, arc / arc[-1], nrm)
        return self.cache[k]

    def at(self, s, z, extra=0.0):
        e, a, n = self.ring(z)
        flip = s > 1.0
        s = 2.0 - s if flip else s
        s = min(max(s, 0.0), 1.0)
        p = np.array([np.interp(s, a, e[:, 0]), np.interp(s, a, e[:, 1])])
        nn = np.array([np.interp(s, a, n[:, 0]), np.interp(s, a, n[:, 1])])
        p = p + nn * extra
        if flip:
            p[0] = -p[0]
        return np.array([p[0], p[1], z])


def tps_fit(src, dst, reg=0.05):
    src = np.asarray(src, float)
    n = len(src)
    r = np.linalg.norm(src[:, None] - src[None], axis=2)
    K = np.where(r > 0, r * r * np.log(np.maximum(r, 1e-12)), 0.0) + reg * np.eye(n)
    P = np.hstack([np.ones((n, 1)), src])
    A = np.zeros((n + 3, n + 3))
    A[:n, :n], A[:n, n:], A[n:, :n] = K, P, P.T
    B = np.zeros((n + 3, 3))
    B[:n] = dst
    return src, np.linalg.solve(A, B)


def tps_eval(model, q):
    src, W = model
    q = np.asarray(q, float)
    r = np.linalg.norm(q[:, None] - src[None], axis=2)
    K = np.where(r > 0, r * r * np.log(np.maximum(r, 1e-12)), 0.0)
    return K @ W[:len(src)] + np.hstack([np.ones((len(q), 1)), q]) @ W[len(src):]


class Placer:
    """Block (cm) -> world (m) for the left half's body panels: ring wrap below
    the chest line, a thin-plate spline through body landmarks above it."""

    def __init__(self, D, M, BM, opts):
        self.D, self.M, self.F = D, M, D.frame
        self.o = opts
        self.rings = Rings(BM, M, opts["gap_m"])
        self.models = {}
        F = self.F
        self.z_of = {"back": lambda y: F["Zc"] + (F["Yc"] - y) / F["kb"],
                     "front": lambda y: F["Zc"] + (F["Yc"] - y) / F["kf"],
                     "side": lambda y: F["Zc"] + (F["Yc"] - y)}
        for kind in ("back", "side", "front"):
            src, dst = self.anchors(kind)
            self.models[kind] = tps_fit(np.array(src), np.array(dst), reg=opts["tps_reg"])

    def lower(self, x, y, kind):
        F = self.F
        z = (F["Zc"] - (y - F["Yc"])) / 100.0 if y >= F["Yc"] else self.z_of[kind](y) / 100.0
        return self.rings.at(x / F["Gc"], z)

    def anchors(self, kind):
        F, M, D = self.F, self.M, self.D
        g = self.o["gap_m"]
        src, dst = [], []

        def ring_pts(xs, ys):
            for y in ys:
                for x in xs:
                    src.append((x, y))
                    dst.append(self.lower(x, y, kind))

        Yc = F["Yc"]
        np3 = np.array(F["np3"]) / 100.0
        sp3 = np.array(F["sp3"]) / 100.0
        xt = M["torso_side_x"]
        yf, yb = M["arm_root_y"]
        za = M["armpit_z"]
        z_of = self.z_of[kind]
        mid_np_sp = 0.5 * (np3 + sp3)
        if kind == "back":
            ring_pts(np.linspace(0, F["x_bs"], 6), [Yc, Yc + 4, Yc + 9])
            ring_pts([0.0, 6.0, 12.0], [Yc - 5, Yc - 10])
            nape = D.anchors["nape"][1]
            src.append(tuple(nape)); dst.append((0.0, M["nape"][1] + g, M["nape"][2]))
            P = D.anchors["np_b"][1]
            src.append(tuple(P)); dst.append(tuple(np3 + (0, 0.012, 0)))
            P = D.anchors["sp_b"][1]
            src.append(tuple(P)); dst.append(tuple(sp3 + (0, 0.012, 0.004)))
            P = 0.5 * (D.anchors["np_b"][1] + D.anchors["sp_b"][1])
            src.append(tuple(P)); dst.append(tuple(mid_np_sp + (0, 0.012, 0.012)))
            P = D.anchors["bpitch"][1]
            src.append(tuple(P)); dst.append((xt - 0.005, yb + g, z_of(P[1]) / 100.0))
            P = D.anchors["p_bs"][1]
            src.append(tuple(P)); dst.append((xt + 0.004, yb + 0.6 * g, z_of(P[1]) / 100.0))
        elif kind == "front":
            ring_pts(np.linspace(F["x_sf"], F["Gc"] + 2.0, 6), [Yc, Yc + 4, Yc + 9])
            ring_pts([F["Gc"] - 12.0, F["Gc"] - 6.0, F["Gc"], F["Gc"] + 2.0], [Yc - 5, Yc - 10])
            P = D.anchors["np_f"][1]
            src.append(tuple(P)); dst.append(tuple(np3 + (0, -0.012, 0)))
            P = D.anchors["sp_f"][1]
            src.append(tuple(P)); dst.append(tuple(sp3 + (0, -0.012, 0.004)))
            P = 0.5 * (D.anchors["np_f"][1] + D.anchors["sp_f"][1])
            src.append(tuple(P)); dst.append(tuple(mid_np_sp + (0, -0.012, 0.012)))
            P = D.anchors["fpitch"][1]
            src.append(tuple(P)); dst.append((xt - 0.005, yf - g, z_of(P[1]) / 100.0))
            P = D.anchors["p_fe"][1]
            src.append(tuple(P)); dst.append((xt + 0.004, yf - 0.6 * g, z_of(P[1]) / 100.0))
        else:
            ring_pts(np.linspace(F["x_bs"], F["x_sf"], 4), [Yc, Yc + 4, Yc + 9])
            P = D.anchors["p_bs"][1]
            src.append(tuple(P)); dst.append((xt + 0.004, yb + 0.6 * g, (F["Zc"] + (F["Yc"] - P[1]) / F["kb"]) / 100))
            ysc = F["ysc"]
            xm = 0.5 * (F["x_bp"] + F["x_fp"])
            src.append((xm, ysc)); dst.append((xt + g * 0.6, 0.5 * (yf + yb), za - 0.025))
        return src, dst

    def place(self, xy, kind):
        out = np.zeros((len(xy), 3))
        Yc = self.F["Yc"]
        lo = xy[:, 1] >= Yc + 3.0
        for i in np.nonzero(lo)[0]:
            out[i] = self.lower(xy[i, 0], xy[i, 1], kind)
        hi = ~lo
        if hi.any():
            t = tps_eval(self.models[kind], xy[hi])
            # blend into the ring wrap over the 3 cm above the switch
            w = np.clip((xy[hi, 1] - Yc) / 3.0, 0, 1)[:, None]
            ring = np.array([self.lower(x, y, kind) for x, y in xy[hi]])
            out[hi] = t * (1 - w) + ring * w
        return out


# --- 4. meshing --------------------------------------------------------------------------------

def mesh_panel(D, name, pts_by_edge, h):
    """Constrained Delaunay mesh of one panel (flat, cm). Returns verts (n, 2),
    tris (m, 3), {(edge, j): vertex}, roll-line vertex ids."""
    from mathutils import Vector
    from mathutils.geometry import delaunay_2d_cdt
    P = D.geom(name)
    loop, where = [], {}
    for e, _ in P.edges:
        q = pts_by_edge[(name, e)]
        start = len(loop)
        for j in range(len(q)):
            where[(e, j)] = start + j
        loop.extend(q[:-1])
    nb = len(loop)
    for (e, j), i in list(where.items()):
        if i >= nb:
            where[(e, j)] = i % nb
    loop = np.array(loop)
    verts = [tuple(p) for p in loop]
    edges = []
    roll_ids = []
    lines = {}
    if "roll" in P.lines:
        L = P.lines["roll"]
        # snap the ends to the nearest boundary vertices
        i0 = int(np.argmin(np.linalg.norm(loop - L[0], axis=1)))
        i1 = int(np.argmin(np.linalg.norm(loop - L[-1], axis=1)))
        Lr = sp.at_params(L, np.linspace(0, 1, max(2, int(math.ceil(sp.arclen(L) / h))) + 1))
        ids = [i0]
        for p in Lr[1:-1]:
            ids.append(len(verts))
            verts.append(tuple(p))
        ids.append(i1)
        edges += [(a, b) for a, b in zip(ids, ids[1:])]
        roll_ids = ids
        lines["roll"] = np.array([verts[i] for i in ids])
    # inner edges (dart legs): constrained polylines; what lies between a dart's legs is cut out
    holes = P.dart_holes() if hasattr(P, "dart_holes") else []
    for e in getattr(P, "inner", {}):
        q = pts_by_edge[(name, e)]
        prev = None
        for j, pq in enumerate(q):
            hit = [k for k in range(nb, len(verts)) if abs(verts[k][0] - pq[0]) + abs(verts[k][1] - pq[1]) < 1e-7]
            if hit:
                k = hit[0]
            else:
                k = len(verts)
                verts.append(tuple(pq))
            where[(e, j)] = k
            if prev is not None and prev != k:
                edges.append((prev, k))
            prev = k
        lines[e] = np.array(q)
    # interior lattice
    lo, hi = loop.min(0), loop.max(0)
    dy = h * math.sqrt(3) / 2
    grid = []
    for k, y in enumerate(np.arange(lo[1] + dy / 2, hi[1], dy)):
        off = (h / 2) * (k % 2)
        for x in np.arange(lo[0] + off, hi[0], h):
            grid.append((x, y))
    grid = np.array(grid)
    if len(grid):
        inside = _pip(grid, loop)
        grid = grid[inside]
        far = _dist_polyline(grid, loop, closed=True) > 0.55 * h
        if "roll" in lines:
            far &= _dist_polyline(grid, lines["roll"]) > 0.45 * h
        for e in getattr(P, "inner", {}):
            far &= _dist_polyline(grid, lines[e]) > 0.45 * h
        for hp in holes:
            far &= ~_pip(grid, hp)
        grid = grid[far]
    verts += [tuple(p) for p in grid]
    vs = [Vector((x, y)) for x, y in verts]
    out = delaunay_2d_cdt(vs, edges, [list(range(nb))], 1, 1e-6)
    ov, of, orig_v = out[0], out[2], out[3]
    remap = {}
    for k, origs in enumerate(orig_v):
        for o in origs:
            remap[o] = k
    V = np.array([(v.x, v.y) for v in ov])
    T = np.array([f for f in of if len(f) == 3])
    quads = [f for f in of if len(f) != 3]
    for f in quads:   # fan anything that is not a triangle
        for a in range(1, len(f) - 1):
            T = np.vstack([T, [f[0], f[a], f[a + 1]]])
    for hp in holes:   # the dart's cut-out
        T = T[~_pip(V[T].mean(1), hp)]
    where = {k: remap[i] for k, i in where.items()}
    roll_ids = [remap[i] for i in roll_ids]
    return V, T, where, roll_ids


# --- 5. the cloth object ------------------------------------------------------------------------

def side_of_line(p, a, b):
    d = b - a
    return (p[:, 0] - a[0]) * d[1] - (p[:, 1] - a[1]) * d[0]


MODELLED = ("collar", "lapel")   # spike 2: built after the drape, not simulated


def build_cloth(D, M, BM, body_bvh, O):
    h = O["h_cm"]
    pts, pairs = D.sample(h)
    PL = Placer(D, M, BM, O)
    info = {}
    gid = {}
    base = 0
    v2 = bool(O.get("v2"))
    names = [n for n in D.names if not (v2 and D.geom(n).kind in MODELLED)]
    layout_x = 0.0
    for name in names:
        P = D.geom(name)
        V, T, where, roll = mesh_panel(D, name, pts, h)
        mirror = name.endswith("_r") and name not in D.panels
        kind = P.kind
        # world placement of the left copy, then mirror
        if kind in ("back", "side", "front"):
            Xw = PL.place(V, kind)
        else:
            Xw = np.zeros((len(V), 3))   # sleeves and collar placed below
        # flat rest (m), panels laid side by side; mirrored copies mirrored
        R = np.zeros((len(V), 3))
        R[:, 0] = (-V[:, 0] if mirror else V[:, 0]) / 100.0 + layout_x
        R[:, 1] = -V[:, 1] / 100.0
        layout_x += (V[:, 0].max() - V[:, 0].min()) / 100.0 + 0.1
        info[name] = {"V": V, "T": T, "where": where, "roll": roll, "base": base, "kind": kind,
                      "mirror": mirror, "Xw": Xw, "R": R}
        for (e, j), i in where.items():
            gid[(name, e, j)] = base + i
        base += len(V)
    # sleeves: wrap round the bent arm axis
    for name, I in info.items():
        if I["kind"] in ("top_sleeve", "under_sleeve"):
            I["Xw"] = place_sleeve(D, M, I["V"], O)
    # lapel: fold the lapel side of the roll line over the front (reflected
    # across the roll line in the block, placed there, lifted a layer off)
    for name, I in info.items():
        if I["kind"] != "front" or "roll" not in D.geom(name).lines:
            continue
        V = I["V"]
        L = D.geom(name).lines["roll"]
        a, b = L[0], L[-1]
        s = side_of_line(V, a, b)
        n = np.array([b[1] - a[1], -(b[0] - a[0])])
        n /= np.linalg.norm(n)
        lap_sign = np.sign(side_of_line(np.array([D.anchors["break"][1] + (5.0, -10.0)]), a, b))[0]
        tpar = ((V - a) @ (b - a)) / np.dot(b - a, b - a)
        lap = (np.sign(s) == lap_sign) & (np.abs(s) > 1e-6) & (tpar > -0.02)
        I["lapel"] = lap
        dist = np.abs(s) / np.linalg.norm(b - a)
        refl = V[lap] - 2 * np.outer(((V[lap] - a) @ n), n)
        Xr = _push_out(PL.place(refl, "front"), body_bvh, O["min_clear_m"])
        nrm = _outward(Xr, body_bvh)
        lift = O["fold_lift_m"] * sp.smoothstep(dist[lap] / 1.0)
        I["Xw"][lap] = Xr + nrm * lift[:, None]
    # push the body panels and sleeves off the body
    for name, I in info.items():
        if I["kind"] == "collar":
            continue
        keep = ~I.get("lapel", np.zeros(len(I["V"]), bool))
        I["Xw"][keep] = _push_out(I["Xw"][keep], body_bvh, O["min_clear_m"])
    # the left front laps over the right: lift its centre-front zone a layer
    I = info["front"]
    wgt = sp.smoothstep((I["V"][:, 0] / D.frame["Gc"] - 0.85) / 0.1)
    I["Xw"] = I["Xw"] + _outward(I["Xw"], body_bvh) * (O["overlap_m"] * wgt)[:, None]
    # mirror the right half
    for name, I in info.items():
        if I["mirror"]:
            I["Xw"] = I["Xw"] * np.array([-1.0, 1.0, 1.0])
    if not v2:
        # collar: on the placed neckline, stand up, fall folded down outside
        place_collar(D, info, gid, pairs, O, body_bvh)
        # rest folds (pressed lapel roll and collar roll), toward the outside
        for name, I in info.items():
            if I["kind"] == "front":
                _rest_fold(I, I["lapel"], D.geom(name).lines["roll"], O["rest_fold_deg"], body_bvh)
            if I["kind"] == "collar":
                _rest_fold_curve(I, I["w"] > I["stand"], O["rest_fold_deg"], body_bvh)
    else:
        # one winding for the whole garment: every panel's faces point away from the body
        for name, I in info.items():
            Xw, T = I["Xw"], I["T"]
            fn = np.cross(Xw[T[:, 1]] - Xw[T[:, 0]], Xw[T[:, 2]] - Xw[T[:, 0]])
            c = Xw[T].mean(1)
            out = _outward(c[:: max(1, len(c) // 60)], body_bvh)
            if np.einsum("ij,ij->i", fn[:: max(1, len(c) // 60)], out).mean() < 0:
                I["T"] = T[:, ::-1].copy()
    # assemble
    X = np.vstack([info[n]["Xw"] for n in names])
    R = np.vstack([info[n]["R"] for n in names])
    T = np.vstack([info[n]["T"] + info[n]["base"] for n in names])
    pid = np.concatenate([[i] * len(info[n]["V"]) for i, n in enumerate(names)])
    sew = set()
    seam_of = {}
    for sname, pr in pairs:
        for A, B in pr:
            if A not in gid or B not in gid:
                continue           # a modelled part's seam (collar, roll line)
            i, j = gid[A], gid[B]
            if i != j:
                sew.add((min(i, j), max(i, j)))
                seam_of[(min(i, j), max(i, j))] = sname
    # button: the left front's button point to the right front's
    bp = np.array(D.geom("front").notches["button"])
    il = info["front"]["base"] + int(np.argmin(np.linalg.norm(info["front"]["V"] - bp, axis=1)))
    ir = info["front_r"]["base"] + int(np.argmin(np.linalg.norm(info["front_r"]["V"] - bp, axis=1)))
    button = (il, ir)
    sew = sorted(sew)
    return {"X": X, "R": R, "T": T, "sew": sew, "button": button, "pid": pid, "names": names,
            "info": info, "pairs": pairs, "gid": gid, "pts": pts, "seam_of": seam_of}


def _outward(X, bvh):
    out = np.zeros_like(X)
    for i, p in enumerate(X):
        loc, nor, _, _ = bvh.find_nearest(Vector(p))
        d = np.array(p) - np.array(loc) if loc is not None else np.array([0, 0, 1.0])
        out[i] = d / max(np.linalg.norm(d), 1e-9)
    return out


def _push_out(X, bvh, clear):
    X = X.copy()
    for i, p in enumerate(X):
        loc, nor, _, dist = bvh.find_nearest(Vector(p))
        if loc is None:
            continue
        d = np.array(p) - np.array(loc)
        n = np.array(nor)
        inside = np.dot(d, n) < 0
        if inside or dist < clear:
            X[i] = np.array(loc) + n * clear
    return X


def _rest_fold(I, mask, L, deg, bvh):
    """Rotate the flat rest of `mask` about the 2D line L by deg, to the side
    the placed panel's outside maps to."""
    if not mask.any():
        return
    R = I["R"]
    a3, b3 = R[I["roll"][0]], R[I["roll"][-1]]
    s_out = _flat_outside_sign(I, bvh)
    ax = (b3 - a3) / np.linalg.norm(b3 - a3)
    p = R[mask] - a3
    along = p @ ax
    perp = p - np.outer(along, ax)
    d = np.linalg.norm(perp, axis=1)
    u = perp / np.maximum(d, 1e-12)[:, None]
    ang = math.radians(deg)
    z = np.array([0, 0, s_out])
    R[mask] = a3 + np.outer(along, ax) + (np.cos(ang) * u + np.sin(ang) * z) * d[:, None]


def _rest_fold_curve(I, mask, deg, bvh):
    """The collar fall: fold about the (curved) roll line, per vertex about the
    local roll-line point and tangent."""
    if not mask.any():
        return
    R = I["R"]
    s_out = _flat_outside_sign(I, bvh)
    roll = R[I["roll"]]
    ang = math.radians(deg)
    z = np.array([0, 0, s_out])
    for i in np.nonzero(mask)[0]:
        k = int(np.argmin(np.linalg.norm(roll - R[i], axis=1)))
        k0, k1 = max(k - 1, 0), min(k + 1, len(roll) - 1)
        ax = roll[k1] - roll[k0]
        ax /= np.linalg.norm(ax)
        p = R[i] - roll[k]
        along = p @ ax
        perp = p - along * ax
        d = np.linalg.norm(perp)
        if d < 1e-9:
            continue
        u = perp / d
        R[i] = roll[k] + along * ax + (np.cos(ang) * u + np.sin(ang) * z) * d


def _flat_outside_sign(I, bvh):
    """+1 if the flat panel's +z side maps to the placed panel's outside."""
    R, X, T = I["R"], I["Xw"], I["T"]
    votes = 0.0
    for t in T[:: max(1, len(T) // 40)]:
        fn = np.cross(R[t[1]] - R[t[0]], R[t[2]] - R[t[0]])[2]
        wn = np.cross(X[t[1]] - X[t[0]], X[t[2]] - X[t[0]])
        c = X[t].mean(0)
        loc, nor, _, _ = bvh.find_nearest(Vector(c))
        out = c - np.array(loc)
        votes += np.sign(fn) * np.sign(np.dot(wn, out))
    return 1.0 if votes >= 0 else -1.0


def place_sleeve(D, M, V, O):
    """Wrap a sleeve panel round the bent arm axis (rest pose): angle from u,
    distance down the axis from v; the crown on the jacket shoulder point."""
    S = D.frame["sleeve"]
    J = O["_joints"]
    j0, j1, j2 = (np.array(J[n][0]) for n in ("upperarm_l", "lowerarm_l", "hand_l"))
    sp3 = np.array(D.frame["sp3"]) / 100.0
    u = (j1 - j0) / np.linalg.norm(j1 - j0)
    n0 = np.array([0, 0, 1.0]) - u[2] * u
    n0 /= np.linalg.norm(n0)
    R0 = S["Wb"] / (2 * math.pi) / 100.0 + O["sleeve_gap_m"]
    q0 = sp3 - n0 * R0
    # axis polyline q0 -> elbow -> wrist with a fillet at the elbow
    axis = _fillet_polyline([q0, j1, j2], O["elbow_fillet_m"])
    L = sp.cum_len(axis)
    T = np.gradient(axis, axis=0)
    T /= np.linalg.norm(T, axis=1, keepdims=True)
    # parallel-transport frame
    N = [n0 - np.dot(n0, T[0]) * T[0]]
    N[0] /= np.linalg.norm(N[0])
    for k in range(1, len(axis)):
        n = N[-1] - np.dot(N[-1], T[k]) * T[k]
        N.append(n / np.linalg.norm(n))
    N = np.array(N)
    Fr = np.cross(T, N)
    if Fr[0, 1] > 0:      # + u toward the front (-y)
        Fr = -Fr
    out = np.zeros((len(V), 3))
    for i, (uu, vv) in enumerate(V):
        w = np.interp(vv, [0, S["hcap"], S["v_el"], S["SL"]], [S["Wb"], S["Wb"], S["We"], S["Wc"]])
        pitch = D.opts["sleeve"]["pitch_cm"] * sp.smoothstep((vv - S["hcap"]) / (S["SL"] - S["hcap"]))
        th = 2 * math.pi * (uu - pitch - S["uc"]) / w
        s = min(max(vv / 100.0, 0.0), L[-1])
        k = int(np.clip(np.searchsorted(L, s), 1, len(L) - 1))
        f = (s - L[k - 1]) / max(L[k] - L[k - 1], 1e-12)
        c = axis[k - 1] + (axis[k] - axis[k - 1]) * f
        n = N[k - 1] + (N[k] - N[k - 1]) * f
        fr = Fr[k - 1] + (Fr[k] - Fr[k - 1]) * f
        r = w / (2 * math.pi) / 100.0 + O["sleeve_gap_m"]
        out[i] = c + r * (math.cos(th) * n + math.sin(th) * fr)
    return out


def _fillet_polyline(P, rad, n=12):
    P = [np.asarray(p, float) for p in P]
    out = [P[0]]
    for k in range(1, len(P) - 1):
        a, b, c = P[k - 1], P[k], P[k + 1]
        d0 = (b - a) / np.linalg.norm(b - a)
        d1 = (c - b) / np.linalg.norm(c - b)
        th = math.acos(np.clip(np.dot(d0, d1), -1, 1))
        tl = rad * math.tan(th / 2)
        p0, p1 = b - d0 * tl, b + d1 * tl
        for t in np.linspace(0, 1, n):
            q = (1 - t) ** 2 * p0 + 2 * (1 - t) * t * b + t ** 2 * p1
            out.append(q)
    out.append(P[-1])
    # resample densely
    out = np.array(out)
    return sp.at_params(out, np.linspace(0, 1, 400))


def place_collar(D, info, gid, pairs, O, bvh):
    """The undercollar on the placed neckline: polar (s, w) of its flat
    annulus; the stand rises from the neckline, the fall turns down outside."""
    I = info["collar"]
    V = I["V"]
    Co = D.opts["collar"]
    w0 = Co["stand_cm"] + Co["fall_cm"]
    Rn = w0 / (Co["spread"] - 1.0)
    c = np.array([0.0, Rn])
    r = np.linalg.norm(V - c, axis=1)
    phi = np.arctan2(V[:, 0], c[1] - V[:, 1])
    s = phi * Rn
    I["w"] = np.maximum(r - Rn, 0.0)   # across the collar, from the neck edge
    # neckline: the placed bodice vertices sewn to the collar's neck edges
    pts = {}
    for sname, pr in pairs:
        if not sname.startswith("collar_"):
            continue
        for A, B in pr:
            ca = A if A[0] == "collar" else B
            ob = B if ca is A else A
            k = gid[ca] - I["base"]
            xb = info[ob[0]]["Xw"][gid[ob] - info[ob[0]]["base"]]
            pts[k] = xb
    ks = np.array(sorted(pts))
    sk = s[ks]
    order = np.argsort(sk)
    sk, Pk = sk[order], np.array([pts[k] for k in ks[order]])
    Ln_total = np.abs(sk).max()
    stand = Co["stand_cm"] + (D.opts["roll_past_np_cm"] - Co["stand_cm"]) * np.clip(np.abs(s) / Ln_total, 0, 1)
    I["stand"] = stand
    up = np.array([0, 0, 1.0])
    out = np.zeros((len(V), 3))
    for i in range(len(V)):
        si = np.clip(s[i], sk[0], sk[-1])
        p = np.array([np.interp(si, sk, Pk[:, k]) for k in range(3)])
        radial = np.array([p[0], p[1] - O["_neck_cy"], 0.0])
        radial /= max(np.linalg.norm(radial), 1e-9)
        wi, st = I["w"][i] / 100.0, stand[i] / 100.0
        if wi <= st:
            out[i] = p + up * wi + radial * 0.1 * wi
        else:
            top = p + up * st + radial * 0.15 * st
            out[i] = top + radial * O["fold_lift_m"] - up * (wi - st) * 0.93 + radial * (wi - st) * 0.35
    I["Xw"] = _push_out(out, bvh, O["min_clear_m"] * 0.4)
    D.frame["collar_Rn"] = Rn


def make_cloth_object(C, name):
    me = bpy.data.meshes.new(name)
    X, T, sew = C["X"], C["T"], C["sew"] + [C["button"]]
    me.from_pydata([tuple(p) for p in X], [tuple(e) for e in sew], [tuple(t) for t in T])
    me.update()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    ob.shape_key_add(name="Basis")
    rest = ob.shape_key_add(name="flat_rest")
    rest.data.foreach_set("co", C["R"].astype(np.float32).ravel())
    rest.value = 0.0      # only the cloth's rest lengths read it
    return ob


def under_tree(co, tris, garments):
    """BVH of the body and the rest-pose garments the jacket goes over."""
    from mathutils.bvhtree import BVHTree
    V, F = [tuple(p) for p in co], [tuple(t) for t in tris]
    dg = bpy.context.evaluated_depsgraph_get()
    for g in garments:
        me = g.evaluated_get(dg).to_mesh()
        n0 = len(V)
        Mw = g.matrix_world
        V += [tuple(Mw @ v.co) for v in me.vertices]
        F += [tuple(n0 + i for i in p.vertices) for p in me.polygons]
        g.evaluated_get(dg).to_mesh_clear()
    return BVHTree.FromPolygons(V, F)


# --- 6. colliders, shoulder pad, sim ------------------------------------------------------------

def make_pad(body, M, O):
    """The shoulder pad as a collider volume on the body: the shoulder-top skin
    within pad_r of the acromion, pushed out along its normals by a dome
    profile (pad_cm at the acromion, 0 at the rim), skinned with the body."""
    import bmesh
    D_ = O["pad_r_m"]
    t0 = O["pad_cm"] / 100.0
    pads = []
    for sgn in (1.0, -1.0):
        ac = np.array(M["acromion"]) * np.array([sgn, 1, 1])
        ob = body.copy()
        ob.data = body.data.copy()
        ob.name = f"spike_pad_{'l' if sgn > 0 else 'r'}"
        bpy.context.scene.collection.objects.link(ob)
        bm = bmesh.new()
        bm.from_mesh(ob.data)
        bm.normal_update()
        kill = [f for f in bm.faces
                if not all(np.linalg.norm(np.array(v.co) - ac) < D_ and v.co.z > M["armpit_z"] + 0.03
                           and v.co.x * sgn > M["neck_point"][0] + 0.03 for v in f.verts)]
        bmesh.ops.delete(bm, geom=kill, context="FACES")
        loose = [v for v in bm.verts if not v.link_faces]
        bmesh.ops.delete(bm, geom=loose, context="VERTS")
        for v in bm.verts:
            d = np.linalg.norm(np.array(v.co) - ac) / D_
            v.co += v.normal * (t0 * (1 - min(d, 1.0) ** 2) ** 2 + 0.002)
        bm.to_mesh(ob.data)
        bm.free()
        pads.append(ob)
    return pads


def add_collider(ob, O):
    m = ob.modifiers.new("Collision", "COLLISION")
    c = ob.collision
    c.thickness_outer = O["col_outer_m"]
    c.thickness_inner = 0.01
    c.cloth_friction = O["friction"]
    c.damping = 0.5
    return m


def simulate(ob, colliders, arm, O, frames):
    """Sew (no gravity), then drape (gravity on), then hold; optionally ramp
    the rig to the bent-arm pose. Returns {frame: coords} for frames asked."""
    sc = bpy.context.scene
    m = ob.modifiers.new("Cloth", "CLOTH")
    st = m.settings
    F = O["fabric"]
    st.quality = O["quality"]
    st.mass = F["mass"]
    st.tension_stiffness = F["tension"]
    st.compression_stiffness = F["compression"]
    st.shear_stiffness = F["shear"]
    st.bending_stiffness = F["bending"]
    st.air_damping = F["air"]
    st.use_sewing_springs = True
    st.sewing_force_max = F["sewing_max"]
    st.rest_shape_key = ob.data.shape_keys.key_blocks["flat_rest"]
    if "canvas" in ob.vertex_groups:
        st.vertex_group_bending = "canvas"
        st.bending_stiffness_max = F["bending_canvas"]
    cs = m.collision_settings
    cs.collision_quality = O["collision_quality"]
    cs.distance_min = O["cloth_dist_m"]
    cs.use_self_collision = O["self_collision"]
    cs.self_distance_min = O["self_dist_m"]
    cs.self_friction = 5.0
    ew = st.effector_weights
    f_sew, f_grav, f_end = O["sew_frames"], O["sew_frames"] + O["gravity_ramp"], frames[-1]
    ew.gravity = 0.0
    ew.keyframe_insert("gravity", frame=1)
    ew.keyframe_insert("gravity", frame=f_sew)
    ew.gravity = 1.0
    ew.keyframe_insert("gravity", frame=f_grav)
    m.point_cache.frame_start = 1
    m.point_cache.frame_end = f_end
    sc.frame_start, sc.frame_end = 1, f_end
    out, times = {}, {}
    t = time.perf_counter()
    for f in range(1, f_end + 1):
        sc.frame_set(f)
        if f in frames:
            out[f] = evaluated(ob)
            times[f] = round(time.perf_counter() - t, 2)
            print(f"[spike] sim frame {f}: {times[f]} s", flush=True)
    return out, times, m


def evaluated(ob):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    me = ev.to_mesh()
    n = len(me.vertices)
    co = np.empty(n * 3, np.float32)
    me.vertices.foreach_get("co", co)
    ev.to_mesh_clear()
    return co.reshape(-1, 3) @ np.array(ob.matrix_world)[:3, :3].T + np.array(ob.matrix_world)[:3, 3]


def key_bent(arm, frame0, frame1, flex_deg, elbow_deg):
    """Rest at frame0; at frame1 both arms flexed forward and the elbows bent
    further (a guard / reach pose)."""
    from mathutils import Quaternion
    from character.suit_drape import _rotate_bone
    for pb in arm.pose.bones:
        pb.rotation_mode = "QUATERNION"
        pb.rotation_quaternion = (1, 0, 0, 0)
        pb.keyframe_insert("rotation_quaternion", frame=frame0)
    bpy.context.view_layer.update()
    for s in ("l", "r"):
        _rotate_bone(arm, f"upperarm_{s}", Quaternion((1, 0, 0), -math.radians(flex_deg)))
        ua, la = arm.pose.bones[f"upperarm_{s}"], arm.pose.bones[f"lowerarm_{s}"]
        u = (ua.tail - ua.head).normalized()
        f = (la.tail - la.head).normalized()
        _rotate_bone(arm, f"lowerarm_{s}", Quaternion(u.cross(f).normalized(), math.radians(elbow_deg)))
    for pb in arm.pose.bones:
        pb.keyframe_insert("rotation_quaternion", frame=frame1)


# --- 7. measures on the drape -------------------------------------------------------------------

def drape_stats(C, X, body_bvh, colliders_bvh):
    T, R, sew = C["T"], C["R"], C["sew"]
    E = np.vstack([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]])
    E = np.unique(np.sort(E, 1), axis=0)
    lr = np.linalg.norm(R[E[:, 0]] - R[E[:, 1]], axis=1)
    lx = np.linalg.norm(X[E[:, 0]] - X[E[:, 1]], axis=1)
    strain = lx / np.maximum(lr, 1e-9) - 1
    sw = np.array(sew)
    gap = np.linalg.norm(X[sw[:, 0]] - X[sw[:, 1]], axis=1)
    inside = 0
    inside_any = 0
    for p in X:
        loc, nor, _, d = body_bvh.find_nearest(Vector(p))
        if loc is not None and np.dot(np.array(p) - np.array(loc), np.array(nor)) < -0.001:
            inside += 1
    for p in X:
        for b in colliders_bvh:
            loc, nor, _, d = b.find_nearest(Vector(p))
            if loc is not None and d < 0.03 and np.dot(np.array(p) - np.array(loc), np.array(nor)) < -0.001:
                inside_any += 1
                break
    return {"verts": int(len(X)), "tris": int(len(T)),
            "strain_mean": round(float(np.mean(np.abs(strain))), 4),
            "strain_p99": round(float(np.percentile(np.abs(strain), 99)), 4),
            "stretch_max": round(float(strain.max()), 4),
            "sew_gap_mean_mm": round(float(gap.mean() * 1000), 2),
            "sew_gap_p95_mm": round(float(np.percentile(gap, 95) * 1000), 2),
            "sew_gap_max_mm": round(float(gap.max() * 1000), 2),
            "inside_body_verts": inside, "inside_any_collider_verts": inside_any}


def keep_geometry(C, X, name, weld=True, smooth=0):
    """The settled cloth as a mesh, the sewn pairs welded."""
    import bmesh
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(p) for p in X], [], [tuple(t) for t in C["T"]])
    me.update()
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    if weld:
        # union-find over the sewn pairs, weld each group to its mean
        par = list(range(len(X)))

        def find(a):
            while par[a] != a:
                par[a] = par[par[a]]
                a = par[a]
            return a
        for a, b in C["sew"]:
            ra, rb = find(a), find(b)
            if ra != rb:
                par[max(ra, rb)] = min(ra, rb)
        groups = {}
        for i in range(len(X)):
            groups.setdefault(find(i), []).append(i)
        tmap = {}
        for r, g in groups.items():
            if len(g) > 1:
                c = np.mean(X[g], axis=0)
                bm.verts[r].co = Vector(c)
                for i in g:
                    if i != r:
                        tmap[bm.verts[i]] = bm.verts[r]
        bmesh.ops.weld_verts(bm, targetmap=tmap)
        # a sewn seam is a hinge in the sim (no bending across it) and settles
        # as a small ridge; relax the band either side of it
        if smooth:
            bm.verts.ensure_lookup_table()
            seam = {bm.verts[r] for r, g in groups.items() if len(g) > 1 and bm.verts[r].is_valid}
            band = set(seam)
            for _ in range(2):
                for v in list(band):
                    band.update(e.other_vert(v) for e in v.link_edges)
            band = [v for v in band if v.is_valid and not v.is_boundary]
            for _ in range(smooth):
                bmesh.ops.smooth_vert(bm, verts=band, factor=0.5, use_axis_x=True, use_axis_y=True,
                                      use_axis_z=True)
    for f in bm.faces:
        f.smooth = True
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


# --- 8. clay renders ---------------------------------------------------------------------------

VIEWS = {"front": (0.0, -1), "three_quarter": (35.0, -1), "profile": (90.0, -1), "back": (180.0, -1)}


def stage_rig(sc):
    """The render camera and the three area lights (az, el about the camera, energy, size)."""
    cam = bpy.data.objects.get("spike_cam")
    if cam is None:
        cam = bpy.data.objects.new("spike_cam", bpy.data.cameras.new("spike_cam"))
        sc.collection.objects.link(cam)
        for nm, (az, el, en, sz) in {"key": (-40, 35, 90, 1.2), "fill": (55, 10, 25, 2.0),
                                      "rim": (160, 30, 50, 1.0)}.items():
            L = bpy.data.objects.new(f"spike_{nm}", bpy.data.lights.new(f"spike_{nm}", "AREA"))
            L.data.energy, L.data.size = en, sz
            if hasattr(L.data, "shadow_maximum_resolution"):
                L.data.shadow_maximum_resolution = 0.0002   # finer shadow maps: the rim shadows alias
            sc.collection.objects.link(L)
            L["az"], L["el"] = az, el
    return cam


def render_views(out_dir, tag, show, views, res=800, target=(0, 0, 1.22), scale=1.15, az_override=None,
                 cam_dz=0.15):
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_EEVEE"
    sc.render.resolution_x = sc.render.resolution_y = res
    sc.render.film_transparent = False
    sc.render.image_settings.file_format = "PNG"
    sc.view_settings.view_transform = "Standard"
    for o in bpy.data.objects:
        if o.type == "MESH":
            o.hide_render = o.name not in show
    clay = bpy.data.materials.get("spike_clay")
    if clay is None:
        clay = bpy.data.materials.new("spike_clay")
        clay.use_nodes = True
        b = clay.node_tree.nodes["Principled BSDF"]
        b.inputs["Base Color"].default_value = (0.42, 0.42, 0.42, 1)
        b.inputs["Roughness"].default_value = 0.6
        jc = bpy.data.materials.new("spike_clay_jacket")
        jc.use_nodes = True
        b = jc.node_tree.nodes["Principled BSDF"]
        b.inputs["Base Color"].default_value = (0.55, 0.52, 0.47, 1)
        b.inputs["Roughness"].default_value = 0.65
    jc = bpy.data.materials["spike_clay_jacket"]
    for o in bpy.data.objects:
        if o.type == "MESH" and o.name in show:
            mat = jc if "jacket" in o.name else clay
            o.data.materials.clear()
            o.data.materials.append(mat)
    if sc.world is None:
        sc.world = bpy.data.worlds.new("w")
    sc.world.use_nodes = True
    sc.world.node_tree.nodes["Background"].inputs[0].default_value = (0.05, 0.05, 0.055, 1)
    sc.world.node_tree.nodes["Background"].inputs[1].default_value = 1.0
    cam = stage_rig(sc)
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = scale
    sc.camera = cam
    paths = []
    tgt = Vector(target)
    for v in views:
        az = math.radians(az_override if az_override is not None else VIEWS[v][0] if v in VIEWS else float(v))
        d = Vector((math.sin(az), -math.cos(az), 0.0))
        cam.location = tgt + d * 4.0 + Vector((0, 0, cam_dz))
        cam.rotation_euler = (tgt - cam.location).to_track_quat("-Z", "Y").to_euler()
        for o in bpy.data.objects:
            if o.name.startswith("spike_") and o.type == "LIGHT":
                a = az + math.radians(o["az"])
                el = math.radians(o["el"])
                o.location = tgt + Vector((math.sin(a) * math.cos(el), -math.cos(a) * math.cos(el),
                                           math.sin(el))) * 2.5
                o.rotation_euler = (tgt - o.location).to_track_quat("-Z", "Y").to_euler()
        p = os.path.join(out_dir, f"{tag}_{v}.png")
        sc.render.filepath = p
        bpy.ops.render.render(write_still=True)
        paths.append(p)
    return paths


# --- main ---------------------------------------------------------------------------------------

SPIKE = {
    "h_cm": 1.6,                 # mesh spacing on the flat panels
    "gap_m": 0.022,              # placement: off the body hull
    "min_clear_m": 0.012,
    "sleeve_gap_m": 0.002,
    "seam_smooth": 6,
    "elbow_fillet_m": 0.08,
    "overlap_m": 0.006,
    "fold_lift_m": 0.006,
    "rest_fold_deg": 168.0,
    "tps_reg": 0.5,
    "pad_r_m": 0.085, "pad_cm": 1.2,
    "col_outer_m": 0.004, "friction": 5.0,
    "quality": 8, "collision_quality": 3, "cloth_dist_m": 0.004,
    "self_collision": True, "self_dist_m": 0.003,
    "fabric": {"mass": 0.3, "tension": 40.0, "compression": 40.0, "shear": 30.0, "bending": 12.0,
               "bending_canvas": 60.0, "air": 2.0, "sewing_max": 0.0},
    "sew_frames": 30, "gravity_ramp": 10, "settle_frames": 30,
    "bent": {"frames": 30, "hold": 15, "flex_deg": 35.0, "elbow_deg": 30.0},
    "colliders": ["shirt", "waistcoat", "trousers"],
    "canvas": {"hem_drop": 0.6, "neck_band_cm": 5.0},
}


# --- spike 2 (T13): two-stage weld, hull back collider, modelled rever --------------------------

SPIKE2 = {
    "details": True,             # the made jacket (blender/character/suit_detail.py); a dict overrides
    "lods": [0.4, 0.15],         # LOD1, LOD2 decimate ratios of the made jacket
    "textures": True,            # UVs from the pattern + the wool atlas (character/suit_made_tex.py); a dict overrides
    "v2": True,
    "h_cm": 1.2,                      # finer than spike 1: a fold at the elbow crook needs it
    # the draft for the XPBD drape: the neckline at the neck's own length (spike 1's 1.15
    # made up for Blender's placed-shape rest), more waist, the sleeve 2 cm above the wrist
    # phase B review: hem at the crotch line (0.44 x nape height), a front dart and more side
    # suppression, the skirt straight below the hip (no flare), a 13.4 cm half cuff, a squarer
    # padded shoulder
    "draft": {"split_lapel": True, "neck_scale": 1.0, "waist_min_frac": 0.82, "length_frac": 0.44,
              "hem_flare_cm": 0.0, "pad_cm": 1.5, "shoulder_drop_deg": 1.0,
              "suppression": {"cb": 0.22, "back_side": 0.40, "side_front": 0.25, "front_dart": 0.13},
              "ease": {"cuff": 11.0},
              "sleeve": {"end_above_wrist_cm": 2.0, "elbow_extra_cm": 0.0}},
    "pad_cm": 1.5,
    # the hem and the cuffs are turned up 4 cm (two layers and the hem canvas): stiffer
    # (not the cuffs: flat-rest bending in a stiff band round a 4 cm tube opens it into a bell)
    "canvas_bands": {"hem_cm": 4.0, "cuff_cm": 0.0},
    "sew_frames": 30,                 # stage 1: unwelded, flat rest, sewing springs, no gravity
    "gravity_ramp": 10, "settle_frames": 35,      # stage 2: welded, sewn rest, gravity
    "rest_smooth": {"rings": 2, "iters": 6},      # stage-2 rest: the seam band relaxed
    "pin_neck": 0.0,                  # pin weight on the neckline in stage 2 (0 = off)
    "hull": {"alpha_back": 0.55, "z_lo_below_hem_m": 0.05, "z_hi_m": None},
    "push": {"clear_m": 0.0015, "smooth_iters": 3},
    "bent": None,
    "rever": {},
    "crease_deg": 20.0,
    "engine": "xpbd",
}


def make_tube(co, tris, BM, M, D, base, O):
    from character import suit_hull
    G = []
    dg = bpy.context.evaluated_depsgraph_get()
    for k in ("shirt", "waistcoat", "trousers"):
        if k in base:
            me = base[k].evaluated_get(dg).to_mesh()
            Mw = np.array(base[k].matrix_world)
            P = np.empty(len(me.vertices) * 3)
            me.vertices.foreach_get("co", P)
            P = P.reshape(-1, 3) @ Mw[:3, :3].T + Mw[:3, 3]
            G.append(P)
            base[k].evaluated_get(dg).to_mesh_clear()
    H = O["hull"]
    z_lo = D.frame["Zh"] / 100.0 - H["z_lo_below_hem_m"]
    z_hi = H["z_hi_m"] or (M["nape"][2] - 0.025)
    V, F, info, radial = suit_hull.build(co, tris, BM.f_trunk, z_lo, z_hi, np.vstack(G) if G else (),
                                 {"alpha_back": H["alpha_back"]})
    me = bpy.data.meshes.new("spike_hull")
    me.from_pydata([tuple(p) for p in V], [], [tuple(int(i) for i in f) for f in F])
    me.update()
    ob = bpy.data.objects.new("spike_hull", me)
    bpy.context.scene.collection.objects.link(ob)
    return ob, info, radial


def simulate_stage(ob, O, f_end, grav_keys, rest_key, pin=None):
    """One cloth run to f_end; grav_keys [(frame, value)]. Returns the coords at f_end and the
    frame time."""
    sc = bpy.context.scene
    m = ob.modifiers.new("Cloth", "CLOTH")
    st = m.settings
    F = O["fabric"]
    st.quality = O["quality"]
    st.mass = F["mass"]
    st.tension_stiffness = F["tension"]
    st.compression_stiffness = F["compression"]
    st.shear_stiffness = F["shear"]
    st.bending_stiffness = F["bending"]
    st.air_damping = F["air"]
    st.use_sewing_springs = True
    st.sewing_force_max = F["sewing_max"]
    st.rest_shape_key = ob.data.shape_keys.key_blocks[rest_key]
    if "canvas" in ob.vertex_groups:
        st.vertex_group_bending = "canvas"
        st.bending_stiffness_max = F["bending_canvas"]
    if pin is not None and "pin" in ob.vertex_groups:
        st.vertex_group_mass = "pin"
        st.pin_stiffness = pin
    cs = m.collision_settings
    cs.collision_quality = O["collision_quality"]
    cs.distance_min = O["cloth_dist_m"]
    cs.use_self_collision = O["self_collision"]
    cs.self_distance_min = O["self_dist_m"]
    cs.self_friction = 5.0
    ew = st.effector_weights
    for f, g in grav_keys:
        ew.gravity = g
        ew.keyframe_insert("gravity", frame=f)
    m.point_cache.frame_start = 1
    m.point_cache.frame_end = f_end
    sc.frame_start, sc.frame_end = 1, f_end
    t = time.perf_counter()
    for f in range(1, f_end + 1):
        sc.frame_set(f)
    X = evaluated(ob)
    dt = round(time.perf_counter() - t, 2)
    print(f"[spike] {ob.name}: {f_end} frames {dt} s", flush=True)
    return X.astype(float), dt


def weld_map(n, sew):
    par = list(range(n))

    def find(a):
        while par[a] != a:
            par[a] = par[par[a]]
            a = par[a]
        return a
    for a, b in sew:
        ra, rb = find(a), find(b)
        if ra != rb:
            par[max(ra, rb)] = min(ra, rb)
    roots = sorted({find(i) for i in range(n)})
    new = {r: k for k, r in enumerate(roots)}
    wm = np.array([new[find(i)] for i in range(n)])
    return wm, len(roots)


def weld(C, X):
    """Weld the sewn pairs: (Xw, Tw, wm). Seam groups at their mean."""
    wm, n = weld_map(len(X), C["sew"])
    cnt = np.bincount(wm, minlength=n).astype(float)
    Xw = np.zeros((n, 3))
    np.add.at(Xw, wm, X)
    Xw /= cnt[:, None]
    Tw = wm[C["T"]]
    ok = (Tw[:, 0] != Tw[:, 1]) & (Tw[:, 1] != Tw[:, 2]) & (Tw[:, 2] != Tw[:, 0])
    return Xw, Tw[ok], wm, cnt


def mesh_edges(T):
    E = np.vstack([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]])
    return np.unique(np.sort(E, 1), axis=0)


def ring_band(T, seed, rings, n):
    E = mesh_edges(T)
    band = np.zeros(n, bool)
    band[seed] = True
    for _ in range(rings):
        nb = band[E[:, 0]] | band[E[:, 1]]
        band[E[nb].ravel()] = True
    return band


def boundary_verts(T, n):
    E = np.vstack([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]])
    E = np.sort(E, 1)
    u, c = np.unique(E, axis=0, return_counts=True)
    b = np.zeros(n, bool)
    b[u[c == 1].ravel()] = True
    return b


def laplace(X, T, mask, iters, lam=0.5):
    E = mesh_edges(T)
    n = len(X)
    deg = np.bincount(E.ravel(), minlength=n).astype(float)
    X = X.copy()
    for _ in range(iters):
        acc = np.zeros_like(X)
        np.add.at(acc, E[:, 0], X[E[:, 1]])
        np.add.at(acc, E[:, 1], X[E[:, 0]])
        L = acc / np.maximum(deg, 1)[:, None] - X
        X[mask] += lam * L[mask]
    return X


def seam_edges(C, wm, Tw):
    """Edges of the welded mesh that lie on a sewn seam, with the seam's name."""
    T = C["T"]
    E = np.sort(np.vstack([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]]), 1)
    u, c = np.unique(E, axis=0, return_counts=True)
    bnd = u[c == 1]                              # panel boundary edges (unwelded)
    seam_v = {}
    for (a, b), nm in C["seam_of"].items():
        seam_v.setdefault(a, nm)
        seam_v.setdefault(b, nm)
    out = {}
    for a, b in bnd:
        if a in seam_v and b in seam_v:
            nm = seam_v[a] if seam_v[a] == seam_v[b] else seam_v[a]
            key = tuple(sorted((int(wm[a]), int(wm[b]))))
            if key[0] != key[1]:
                out[key] = nm.replace("_r", "")
    # keep only edges interior to the welded mesh (two faces)
    Ew = np.sort(np.vstack([Tw[:, [0, 1]], Tw[:, [1, 2]], Tw[:, [2, 0]]]), 1)
    uw, cw = np.unique(Ew, axis=0, return_counts=True)
    inner = {tuple(e) for e in uw[cw == 2]}
    return {k: v for k, v in out.items() if k in inner}


def dihedrals(X, T, edges):
    """Unsigned dihedral (deg) between the two faces at each edge (consistent winding)."""
    fn = np.cross(X[T[:, 1]] - X[T[:, 0]], X[T[:, 2]] - X[T[:, 0]])
    fn /= np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-12)
    adj = {}
    for fi, t in enumerate(T):
        for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            adj.setdefault((min(a, b), max(a, b)), []).append(fi)
    out = {}
    for e in edges:
        fs = adj.get(e, [])
        if len(fs) == 2:
            out[e] = float(np.degrees(np.arccos(np.clip(fn[fs[0]] @ fn[fs[1]], -1, 1))))
    return out


def crease_zones(X, T, sedges, J):
    """Per-vertex zone labels where a seam dihedral is the body's shape, not a hinge: the
    underarm corner (the armhole bottom, where sleeve and side meet at the arm's angle),
    the elbow (the rest-pose sleeve is bent there) and the seam ends at the free edge."""
    n = len(X)
    zone = np.full(n, "", dtype=object)
    near_free = ring_band(T, np.nonzero(boundary_verts(T, n))[0], 1, n)
    zone[near_free] = "free_edge"
    for side in ("l", "r"):
        el = np.array(J[f"lowerarm_{side}"][0])
        zone[np.linalg.norm(X - el, axis=1) < 0.07] = "elbow"
    arm = [e for e, nm in sedges.items() if nm == "armhole"]
    for sgn in (1.0, -1.0):
        vs = np.array(sorted({v for e in arm for v in e if X[v, 0] * sgn > 0}))
        if len(vs):
            bot = X[vs[np.argmin(X[vs, 2])]]
            zone[np.linalg.norm(X - bot, axis=1) < 0.04] = "underarm"
    return zone


def crease_stats(X, T, sedges, thr, ring_ref=True, zone=None):
    """Per seam: edge count, count over thr, max and mean dihedral, and the excess over the
    mean dihedral of the panel edges within 3 cm (a hinge is a crease the cloth either side
    does not have). With `zone` (crease_zones), over_thr_clean counts the edges outside
    the zones and zone_over the rest by zone."""
    d = dihedrals(X, T, list(sedges))
    allE = [tuple(e) for e in mesh_edges(T)]
    dall = dihedrals(X, T, allE)
    mid = {e: 0.5 * (X[e[0]] + X[e[1]]) for e in allE}
    keys = np.array(allE)
    mids = np.array([mid[e] for e in allE])
    dv = np.array([dall.get(e, 0.0) for e in allE])
    is_seam = np.array([e in sedges for e in allE])
    # the hinge measure: the bend across the seam against the cloth's own bend in the same
    # direction nearby (edges parallel to the seam edge, 1-4 cm off it), as curvature (the
    # dihedral over the span between the two faces' centroids), so a round sleeve (every
    # edge along it bent by the arm's radius) is not read as a crease
    fc = X[T].mean(1)
    adj = {}
    for fi, t in enumerate(T):
        for a_, b_ in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            adj.setdefault((min(a_, b_), max(a_, b_)), []).append(fi)
    keys_ok = np.array([len(adj.get(e, ())) == 2 for e in allE])
    span = np.array([np.linalg.norm(fc[adj[e][0]] - fc[adj[e][1]]) if ok else 1.0 for e, ok in zip(allE, keys_ok)])
    kap = np.radians(dv) / np.maximum(span, 1e-6)
    edir = X[keys[:, 1]] - X[keys[:, 0]]
    edir /= np.maximum(np.linalg.norm(edir, axis=1, keepdims=True), 1e-12)
    idx_of = {e: i for i, e in enumerate(allE)}
    per = {}
    for e, nm in sedges.items():
        if e not in d:
            continue
        dist = np.linalg.norm(mids - mid[e], axis=1)
        near = (dist < 0.03) & ~is_seam
        ref = float(dv[near].mean()) if near.any() else 0.0
        i = idx_of[e]
        par = (dist > 0.01) & (dist < 0.04) & ~is_seam & keys_ok & (np.abs(edir @ edir[i]) > 0.87)
        kref = float(np.median(kap[par])) if par.sum() >= 3 else 0.0
        hinge = d[e] - float(np.degrees(kref * span[i]))
        z = (zone[e[0]] or zone[e[1]]) if zone is not None else ""
        per.setdefault(nm, []).append((d[e], d[e] - ref, z, mid[e], hinge))
    out = {}
    for nm, v in sorted(per.items()):
        a = np.array([r[:2] for r in v])
        zs = [r[2] for r in v]
        out[nm] = {"edges": len(a), "over_thr": int((a[:, 0] > thr).sum()), "max_deg": round(float(a[:, 0].max()), 1),
                   "mean_deg": round(float(a[:, 0].mean()), 1), "excess_over_thr": int((a[:, 1] > thr).sum()),
                   "excess_max_deg": round(float(a[:, 1].max()), 1)}
        hg = np.array([r[4] for r in v])
        out[nm]["hinge_over_thr"] = int((hg > thr).sum())
        out[nm]["hinge_max_deg"] = round(float(hg.max()), 1)
        out[nm]["hinge_p95_deg"] = round(float(np.percentile(hg, 95)), 1)
        worst = sorted([(r[4], r[3]) for r in v if r[4] > thr], key=lambda t: -t[0])[:4]
        out[nm]["hinge_over_at"] = [[round(float(dd), 1)] + [round(float(c), 3) for c in m] for dd, m in worst]
        if zone is not None:
            clean = np.array([z == "" for z in zs])
            out[nm]["over_thr_clean"] = int((a[clean, 0] > thr).sum())
            out[nm]["max_deg_clean"] = round(float(a[clean, 0].max()), 1) if clean.any() else 0.0
            zo = {}
            for (dd, _), z in zip(a, zs):
                if z and dd > thr:
                    zo[z] = zo.get(z, 0) + 1
            out[nm]["zone_over"] = zo
            worst = sorted([(r[0], r[3]) for r in v if r[2] == "" and r[0] > thr], key=lambda t: -t[0])[:4]
            out[nm]["clean_over_at"] = [[round(float(dd), 1)] + [round(float(c), 3) for c in m] for dd, m in worst]
    panel = dv[~is_seam]
    out["_panel_edges"] = {"mean_deg": round(float(panel.mean()), 2), "p99_deg": round(float(np.percentile(panel, 99)), 1)}
    return out


def garment_covers(bvh, body_bvh, nbody, p, reach=0.05):
    """Is p under a garment: a ray from p away from the body hits a garment face (index >=
    nbody in bvh) within reach? The nearest-face sign misreads a point in front of a face that
    looks inward (a turned edge's inner rim, a lining at an opening): the waistcoat's front
    edge pushed the cut-away jacket front 2 cm forward in the drape, then push_out sent it
    back through the other front (t13c-k4)."""
    loc, nor, fi, d = body_bvh.find_nearest(Vector(p))
    u = np.asarray(p) - np.array(loc)
    if float(np.dot(u, np.array(nor))) < 0:
        return True
    u = u / max(np.linalg.norm(u), 1e-9)
    hit, _, hfi, hd = bvh.ray_cast(Vector(np.asarray(p) + u * 1e-4), Vector(u), reach)
    return hit is not None and hfi >= nbody


class Layers:
    """The body and the under-garments as one surface set, read the way the drape's distance
    field reads them: the nearest face decides. The body is closed (behind its face = inside);
    a garment is an open shell (inside only when behind its face, not beside its edge)."""

    def __init__(self, co, tris, shells=()):
        from mathutils.bvhtree import BVHTree
        V = [tuple(p) for p in co]
        F = [tuple(int(i) for i in t) for t in tris]
        self.nbody = len(F)
        for sv, sf in shells:
            n0 = len(V)
            V += [tuple(p) for p in sv]
            F += [tuple(n0 + int(i) for i in f) for f in sf]
        self.bvh = BVHTree.FromPolygons(V, F)
        self.body_bvh = BVHTree.FromPolygons(V[:len(co)], F[:self.nbody])

    def covered(self, p, reach=0.05):
        """A second reading of 'inside': is p under a garment (a ray from p away from the body
        hits a garment within reach) or inside the body? The nearest-face rule misreads a
        point beside a garment's folded edge (a shirt collar's fall); the ray does not."""
        loc, nor, fi, d = self.body_bvh.find_nearest(Vector(p))
        loc, nor = np.array(loc), np.array(nor)
        if float(np.dot(np.asarray(p) - loc, nor)) < 0:
            return True
        u = np.asarray(p) - loc
        u = u / max(np.linalg.norm(u), 1e-9)
        hit, _, hfi, hd = self.bvh.ray_cast(Vector(np.asarray(p) + u * 1e-4), Vector(u), reach)
        return hit is not None and hfi >= self.nbody

    def signed(self, p):
        """(signed distance, nearest point, normal): negative inside."""
        loc, nor, fi, d = self.bvh.find_nearest(Vector(p))
        loc, nor = np.array(loc), np.array(nor)
        s = float(np.dot(np.asarray(p) - loc, nor))
        inside = s < 0 if fi < self.nbody else (s < -0.5 * d and self.covered(p))
        return (-d if inside else d), loc, nor


def garment_shells(base, keys):
    dg = bpy.context.evaluated_depsgraph_get()
    shells = []
    for k in keys:
        if k in base:
            me = base[k].evaluated_get(dg).to_mesh()
            Mw = np.array(base[k].matrix_world)
            P = np.array([tuple(v.co) for v in me.vertices]) @ Mw[:3, :3].T + Mw[:3, 3]
            shells.append((P, [tuple(pl.vertices) for pl in me.polygons]))
            base[k].evaluated_get(dg).to_mesh_clear()
    return shells


def inside_count(X, L, tol=0.0005):
    """Vertices inside the body or behind an under-garment (Layers L)."""
    return int(sum(1 for p in X if L.signed(p)[0] < -tol))


def push_out(X, T, L, clear, iters):
    """Final layer order: every vertex `clear` outside the body and the under-garments
    (Layers L), then a light smooth of the moved vertices and their ring, and again."""
    X = X.copy()
    moved_any = np.zeros(len(X), bool)
    for it in range(iters + 1):
        moved = np.zeros(len(X), bool)
        for i, p in enumerate(X):
            d, loc, nor = L.signed(p)
            if d < clear:
                g = (p - loc) / max(abs(d), 1e-9) * (1 if d >= 0 else -1) if abs(d) > 1e-6 else nor
                X[i] = p + g * (clear - d)
                moved[i] = True
        moved_any |= moved
        if it == iters or not moved.any():
            break
        band = ring_band(T, np.nonzero(moved)[0], 1, len(X)) & ~boundary_verts(T, len(X))
        X = laplace(X, T, band, 2, 0.4)
    # a vertex in a crevice between two layers (the shirt going into the waistband) can be
    # pushed out of one into the other: march it out along the cloth's own normal instead
    Nv = np.zeros_like(X)
    fn = np.cross(X[T[:, 1]] - X[T[:, 0]], X[T[:, 2]] - X[T[:, 0]])
    for k in range(3):
        np.add.at(Nv, T[:, k], fn)
    Nv /= np.maximum(np.linalg.norm(Nv, axis=1, keepdims=True), 1e-12)
    for i, p in enumerate(X):
        if L.signed(p)[0] >= 0 or not L.covered(p):
            continue            # outside, or a misreading beside a garment's edge (no ray hit)
        p0 = p
        for _ in range(20):
            p = p + Nv[i] * 0.001
            if L.signed(p)[0] >= clear:
                break
        else:
            p = p0              # 2 cm out and still 'inside': not a crevice; leave it
        X[i] = p
        moved_any[i] = True
    return X, int(moved_any.sum())


def chains_for_rever(C, wm, D):
    """The jacket's free edge per side, welded ids and flat arc s (cm): back neck (CB -> NP),
    front gorge reversed (NP -> roll crossing), front roll edge reversed (-> break)."""
    out = {}
    for side, suf in (("l", ""), ("r", "_r")):
        ids, s = [], []
        acc = 0.0
        for pn, e, rev in (("back" + suf, "neck", False), ("front" + suf, "gorge", True),
                           ("front" + suf, "roll", True)):
            P = C["pts"][(pn, e)]
            js = list(range(len(P)))
            if rev:
                js = js[::-1]
            for k, j in enumerate(js):
                g = int(wm[C["gid"][(pn, e, j)]])
                if k > 0:
                    acc += float(np.linalg.norm(P[j] - P[js[k - 1]]))
                if ids and ids[-1] == g:
                    continue
                ids.append(g)
                s.append(acc)
        out[side] = (np.array(ids), np.array(s))
    return out


def mesh_object(name, V, F, smooth=True):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(p) for p in V], [], [tuple(int(i) for i in f) for f in F])
    me.update()
    for p in me.polygons:
        p.use_smooth = smooth
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def body_sdf(co, tris, lo, hi, h, band=0.03, shells=()):
    """Signed distance to the body and the under-garments on a grid (negative inside), exact
    within `band` of a surface, coarse elsewhere. One BVH over all of them: the nearest face
    decides. The body is closed: the sign is the nearest face's normal. A garment is an open
    shell: a point is inside only when it is behind the face (not beside its edge) and under the
    garment (garment_covers: not in front of a face that looks inward, as a turned edge's inner
    rim or a lining does).
    shells: [(verts (n, 3), faces)] in world space."""
    from mathutils.bvhtree import BVHTree
    from character.suit_xpbd import Grid
    V = [tuple(p) for p in co]
    F = [tuple(int(i) for i in t) for t in tris]
    nbody = len(F)
    for sv, sf in shells:
        n0 = len(V)
        V += [tuple(p) for p in sv]
        F += [tuple(n0 + int(i) for i in f) for f in sf]
    bvh = BVHTree.FromPolygons(V, F)
    body_bvh = BVHTree.FromPolygons(V[:len(co)], F[:nbody])

    def exact(P):
        out = np.empty(len(P))
        for k, p in enumerate(P):
            loc, nor, fi, d = bvh.find_nearest(Vector(p))
            s = np.dot(p - np.array(loc), np.array(nor))
            inside = s < 0 if fi < nbody else (s < -0.5 * d and garment_covers(bvh, body_bvh, nbody, p))
            out[k] = -d if inside else d
        return out
    H = 4 * h
    shc = np.ceil((hi - lo) / H).astype(int) + 1
    gc = np.stack(np.meshgrid(*[lo[k] + H * np.arange(shc[k]) for k in range(3)], indexing="ij"), -1)
    Dc = exact(gc.reshape(-1, 3)).reshape(shc)
    coarse = Grid(Dc, lo, H)
    shf = (shc - 1) * 4 + 1
    gf = np.stack(np.meshgrid(*[lo[k] + h * np.arange(shf[k]) for k in range(3)], indexing="ij"), -1).reshape(-1, 3)
    Df, _ = coarse(gf)
    m = np.abs(Df) < band + H
    Df[m] = exact(gf[m])
    return Grid(Df.reshape(shf), lo, h), int(m.sum())


class PadSDF:
    """The body field with the shoulder pads as an outward offset: a dome of pad_cm at the
    acromion falling to 0 at pad_r (top of the shoulder only)."""

    def __init__(self, body, M, O):
        self.body = body
        self.ac = np.array(M["acromion"])
        self.r, self.t = O["pad_r_m"], O["pad_cm"] / 100.0
        self.zmin = M["armpit_z"] + 0.03
        self.xmin = M["neck_point"][0] + 0.03

    def __call__(self, P):
        d, g = self.body(P)
        off = np.zeros(len(P))
        for sgn in (1.0, -1.0):
            ac = self.ac * np.array([sgn, 1, 1])
            q = np.linalg.norm(P - ac, axis=1) / self.r
            w = (P[:, 2] > self.zmin) & (P[:, 0] * sgn > self.xmin)
            off = np.maximum(off, np.where(w, self.t * np.clip(1 - q ** 2, 0, 1) ** 2, 0.0))
        return d - off, g


XPBD = {
    "fps": 24, "substeps": 30, "stretch_iters": 2,
    "density": 0.33, "density_canvas": 0.45,          # kg/m2: suiting + lining; the canvassed front
    "k_stretch": 4000.0, "k_comp": 400.0,             # N/m per edge
    "kb": 2.0e-5, "kb_canvas": 1.2e-4,                # N m
    "damping": 2.0, "friction": 0.3, "thickness": 0.004,
    "sew_frames": 30, "sew_k": (5.0, 5000.0),         # stage 1: sewing stiffness ramp (log)
    "drape_frames": 45, "gravity_ramp": 8,
    "button_gap_m": 0.004, "layer_gap_m": 0.003,
    "sew_close_m": 0.002, "sew_extra_max": 40,
    "neck_fair_iters": 60,                            # fair the neckline hold targets (0 = as placed)
    "neck_hold_k": 30.0,                              # N/m: the collar and the neck tape hold the neckline
    "neck_hold_k2": 30.0, "neck_hold2_fair": False,   # stage 2
    "sdf_h": 0.006,
    # self-contact (the elbow crook and the underarm fold onto themselves otherwise): vertices
    # closer than self_r repel unless within self_excl of each other on the placed garment
    # self_r 0.010 let the right sleeve's inner elbow fold through itself once the fronts were cut
    # away (run t13c-k1/k2: a 117-120 deg hinge on the fore seam); 0.012 holds it (t13c-k3)
    "self_r": 0.012, "self_excl": 0.025,
    "kb_sleeve": 6e-5,
}


def neck_targets(C, Xm, wm0, iters=60):
    """Fair hold targets for the neckline, by weld group: per side, the chain CB -> NP (back
    neck) -> roll crossing (front gorge, reversed), Taubin-smoothed with its ends fixed, then
    re-spaced along the smoothed line in proportion to the pattern's arc length."""
    out = {}
    if iters <= 0:
        return out
    for suf in ("", "_r"):
        ids, s = [], []
        acc = 0.0
        for pn, e, rev in (("back" + suf, "neck", False), ("front" + suf, "gorge", True)):
            if (pn, e) not in C["pts"]:
                continue
            Pp = C["pts"][(pn, e)]
            js = list(range(len(Pp)))[::-1] if rev else list(range(len(Pp)))
            for k, j in enumerate(js):
                g = int(wm0[C["gid"][(pn, e, j)]])
                if k > 0:
                    acc += float(np.linalg.norm(Pp[j] - Pp[js[k - 1]]))
                if ids and ids[-1] == g:
                    continue
                ids.append(g)
                s.append(acc)
        if len(ids) < 4:
            continue
        Q = Xm[ids].copy()
        for it in range(2 * iters):
            lam = 0.5 if it % 2 == 0 else -0.53
            Q[1:-1] += lam * (0.5 * (Q[:-2] + Q[2:]) - Q[1:-1])
        # re-space by the pattern's arc length
        seg = np.linalg.norm(np.diff(Q, axis=0), axis=1)
        cq = np.r_[0.0, np.cumsum(seg)]
        f = np.array(s) / max(s[-1], 1e-9) * cq[-1]
        R = np.c_[[np.interp(f, cq, Q[:, k]) for k in range(3)]].T
        for g, r in zip(ids, R):
            out[g] = r
    return out


def drape_xpbd(C, O, sdf, canvas, stats, neck=None):
    """Stage 1 (unwelded, sew), weld, stage 2 (welded, gravity). Returns X1 (unwelded, sewn),
    (Xw, Tw, wm) the weld, X2 the drape."""
    from character import suit_xpbd as xp
    P = sp.merge(XPBD, O.get("xpbd"))
    n0 = len(C["X"])
    rho = P["density"] + (P["density_canvas"] - P["density"]) * canvas
    mass = xp.mass_from_flat(C["T"], C["R"], n0, rho)
    kb = P["kb"] + (P["kb_canvas"] - P["kb"]) * canvas
    # the sleeves are wool and lining together (the body's lining is loose; a sleeve's is not)
    sleeve = np.isin(np.asarray(C["names"])[C["pid"]], ["top_sleeve", "top_sleeve_r", "under_sleeve", "under_sleeve_r"])
    kb = np.where(sleeve, np.maximum(kb, P["kb_sleeve"]), kb)
    E0 = xp.edges_of(C["T"])
    L0 = np.linalg.norm(C["R"][E0[:, 0]] - C["R"][E0[:, 1]], axis=1)
    o = {"k_stretch": P["k_stretch"], "k_comp": P["k_comp"], "damping": P["damping"],
         "friction": P["friction"], "thickness": P["thickness"], "stretch_iters": P["stretch_iters"]}
    t = time.perf_counter()
    S = xp.Solver(C["X"], C["T"], L0, mass, kb, o)
    bl, br = C["button"]
    S.set_sew(list(C["sew"]) + [(bl, br)], [0.0] * len(C["sew"]) + [P["button_gap_m"]])
    S.sdf = sdf
    # the left front laps over the right at the centre front
    lay = layer_sets(C)
    if lay is not None:
        S.layers = [(lay[0], lay[1], P["layer_gap_m"])]
    # the button pair: the left front's button point stays in front of the right's (a plain
    # distance constraint let the right front come through: run t13b-d2, 13.5 mm)
    S.layer_force = [(np.array([bl]), np.array([br]), P["button_gap_m"])]
    # the placed garment, each sewn group at its mean (the reference for holds and self-contact)
    wm0, nw0 = weld_map(n0, C["sew"])
    Xm = np.zeros((nw0, 3))
    np.add.at(Xm, wm0, C["X"])
    Xm /= np.bincount(wm0, minlength=nw0)[:, None]
    skip0 = np.zeros(n0, bool)
    if lay is not None:
        skip0[lay[0]] = skip0[lay[1]] = True      # the lap has its own layer constraint
    if P["self_r"] > 0:
        S.self_ref, S.self_r, S.self_excl, S.self_skip = Xm[wm0], P["self_r"], P["self_excl"], skip0
    if neck is not None and P["neck_hold_k"] > 0:
        # hold the neckline where it was placed (a sewn corner at its pair's mean, so the
        # hold and the seam agree): the collar and the neck tape hold it in a real jacket.
        # The placement can step where the back wraps into the shoulder: the targets are the
        # placed line smoothed and spaced as on the pattern (a taped neckline is a fair curve)
        S.hold_idx = np.nonzero(neck)[0]
        tgt = neck_targets(C, Xm, wm0, P["neck_fair_iters"])
        stats["_neck_tgt"] = tgt
        S.hold_pos = np.array([tgt.get(int(wm0[i]), Xm[wm0[i]]) for i in S.hold_idx])
        stats["neck_hold_moved_mm"] = round(float(np.abs(S.hold_pos - Xm[wm0[S.hold_idx]]).max()) * 1000, 1)
        S.hold_k = P["neck_hold_k"]
    k0, k1 = P["sew_k"]
    nf = P["sew_frames"]
    S.run(nf, P["fps"], P["substeps"], g_of=lambda f: 0.0,
          ksew_of=lambda f: k0 * (k1 / k0) ** min(1.0, f / max(nf - 8, 1)))
    # keep sewing until every seam is closed (the weld moves each pair to its mean)
    sw_ = np.array(C["sew"])
    extra = 0
    while extra < P["sew_extra_max"]:
        gap = np.linalg.norm(S.X[sw_[:, 0]] - S.X[sw_[:, 1]], axis=1).max()
        if gap < P["sew_close_m"]:
            break
        S.run(4, P["fps"], P["substeps"], g_of=lambda f: 0.0, ksew_of=lambda f: k1)
        extra += 4
    stats["xpbd_sew_extra_frames"] = extra
    X1 = S.X.copy()
    stats["xpbd_stage1_s"] = round(time.perf_counter() - t, 2)
    # weld
    t = time.perf_counter()
    Xw, Tw, wm, cnt = weld(C, X1)
    nw = len(Xw)
    Lw = {}
    for (a, b), l in zip(E0, L0):
        e = (int(min(wm[a], wm[b])), int(max(wm[a], wm[b])))
        if e[0] != e[1]:
            Lw.setdefault(e, []).append(l)
    Lw = {e: float(np.mean(v)) for e, v in Lw.items()}
    Ew = xp.edges_of(Tw)
    for a, b in Ew:     # an edge the weld creates across a seam corner (rare): its sewn length
        Lw.setdefault((int(a), int(b)), float(np.linalg.norm(Xw[a] - Xw[b])))
    mw = np.zeros(nw)
    np.add.at(mw, wm, mass)
    kbw = np.zeros(nw)
    np.maximum.at(kbw, wm, kb)
    S2 = xp.Solver(Xw, Tw, Lw, mw, kbw, o)
    S2.set_sew([(int(wm[bl]), int(wm[br]))], [P["button_gap_m"]])
    S2.sdf = sdf
    if lay is not None:
        S2.layers = [(np.unique(wm[lay[0]]), np.unique(wm[lay[1]]), P["layer_gap_m"])]
    S2.layer_force = [(np.array([int(wm[bl])]), np.array([int(wm[br])]), P["button_gap_m"])]
    if P["self_r"] > 0:
        skip2 = np.zeros(nw, bool)
        skip2[wm[skip0]] = True
        S2.self_ref, S2.self_r, S2.self_excl, S2.self_skip = Xm, P["self_r"], P["self_excl"], skip2
    if neck is not None and P["neck_hold_k"] > 0:
        # where stage 1 left it (holding stage 2 to the fair line instead, firmer, crumples the
        # collar ends: run t13b-j4); neck_hold2_fair switches that back on
        tgt = stats.pop("_neck_tgt", {})
        tgt = tgt if P["neck_hold2_fair"] else {}
        hold = {}
        for i in np.nonzero(neck)[0]:
            hold[int(wm[i])] = tgt.get(int(wm0[i]), Xw[wm[i]])
        S2.hold_idx = np.array(sorted(hold), int)
        S2.hold_pos = np.array([hold[k] for k in S2.hold_idx])
        S2.hold_k = P["neck_hold_k2"]
    gr = P["gravity_ramp"]
    S2.run(P["drape_frames"], P["fps"], P["substeps"], g_of=lambda f: 9.81 * min(1.0, (f + 1) / gr),
           ksew_of=lambda f: k1)
    stats["xpbd_stage2_s"] = round(time.perf_counter() - t, 2)
    stats["xpbd"] = {"stencils": int(len(S2.S)), "edge_colours": len(S2.ecol), "stencil_colours": len(S2.scol),
                     "opts": P}
    return X1, (Xw, Tw, wm, cnt), S2.X.copy()


def layer_sets(C):
    """Centre-front zones of the two fronts (the left laps over the right)."""
    out = []
    for nm in ("front", "front_r"):
        I = C["info"].get(nm)
        if I is None:
            return None
        Gc = None
        V = I["V"]
        x = V[:, 0]
        sel = x > x.max() - 6.0
        out.append(I["base"] + np.nonzero(sel)[0])
    return out[0], out[1]


CLOSE = {"close_34": (35.0, (0.0, 0.0, 1.42), 0.62), "close_back": (180.0, (0.0, 0.0, 1.30), 0.85),
         "close_profile": (90.0, (0.0, 0.0, 1.38), 0.75),
         # the wearer's left underarm (the armhole/side/sleeve junction), front and back
         "close_underarm_f": (15.0, (0.22, 0.0, 1.33), 0.30), "close_underarm_b": (165.0, (0.22, 0.0, 1.33), 0.30),
         # looking up into the left armpit from the front, below
         "close_armpit": (25.0, (0.22, 0.0, 1.36), 0.22, -2.4),
         # the left cuff and forearm from behind (the hind seam)
         "close_cuff": (120.0, (0.47, -0.12, 1.14), 0.30),
         # the wearer's left lapel edge, from the front
         "close_lapel": (10.0, (0.07, -0.12, 1.42), 0.16),
         # the back of the collar (stand, fall, the centre back)
         "close_collar_back": (160.0, (0.0, 0.05, 1.57), 0.24, 0.05)}


DETAIL_CLOSE = {
    # the wearer's left hip pocket, breast welt, front button and buttonhole, cuff buttons, vent
    "close_pocket": (20.0, (0.12, -0.12, 1.02), 0.24),
    "close_welt": (15.0, (0.10, -0.12, 1.36), 0.20),
    "close_button": (5.0, (0.0, -0.13, 1.125), 0.10),
    "close_cuff_btn": (110.0, (0.47, -0.12, 1.12), 0.18),
    "close_vent": (165.0, (0.10, 0.08, 0.98), 0.32),
    "close_hem_edge": (35.0, (0.06, -0.10, 0.95), 0.18, -0.25),
}


def render_detail_close(out_dir, tag, show):
    for v, (az, tgt, sc_, *dz) in DETAIL_CLOSE.items():
        render_views(out_dir, tag, show, [v], target=tgt, scale=sc_, az_override=az,
                     cam_dz=dz[0] if dz else 0.15)


def set_parts(ob, part):
    """Store the made jacket's part tag (0 wool, 1 lining, 2 edge, 3 button) as a face
    attribute (materials come later: T13 item 2)."""
    a = ob.data.attributes.new("part", "INT", "FACE")
    a.data.foreach_set("value", [int(x) for x in part])


def detail_clearance(X, T, det):
    """How far each detail stands off the drape (mm): min, p01 of the signed distance of the
    pockets' and buttons' vertices to the draped outside (negative = sunk in)."""
    from mathutils.bvhtree import BVHTree
    bvh = BVHTree.FromPolygons([tuple(p) for p in X], [tuple(int(i) for i in t) for t in T])
    out = {}
    for k in ("pockets", "buttons", "buttonhole"):
        if det.get(k) is None:
            continue
        d = []
        for p in det[k][0]:
            loc, nor, _, dd = bvh.find_nearest(Vector(p))
            if loc is None or dd > 0.03:
                continue
            d.append(float(np.dot(np.asarray(p) - np.array(loc), np.array(nor))))
        d = np.array(d) * 1000
        out[k] = {"min": round(float(d.min()), 2), "p01": round(float(np.percentile(d, 1)), 2),
                  "below_0": int((d < 0).sum()), "n": int(len(d))}
    return out


def make_lods(obs, ratios):
    """LOD1/LOD2: the made jacket joined and collapse-decimated. Returns {k: (object, tris)}."""
    out = {}
    for k, r in enumerate(ratios, start=1):
        cps = []
        for ob in obs:
            if k >= 2 and ob.name.endswith(("buttonhole",)):
                continue                       # LOD2 drops the buttonhole cord
            c = ob.copy()
            c.data = ob.data.copy()
            bpy.context.scene.collection.objects.link(c)
            cps.append(c)
        with bpy.context.temp_override(active_object=cps[0], selected_editable_objects=cps,
                                       selected_objects=cps):
            bpy.ops.object.join()
        j = cps[0]
        j.name = f"spike_jacket_lod{k}"
        m = j.modifiers.new("dec", "DECIMATE")
        m.ratio = float(r)
        dg = bpy.context.evaluated_depsgraph_get()
        me2 = bpy.data.meshes.new_from_object(j.evaluated_get(dg))
        j.modifiers.clear()
        j.data = me2
        out[k] = (j, int(sum(len(p.vertices) - 2 for p in me2.polygons)))
    return out


def render_close(out_dir, tag, show):
    for v, (az, tgt, sc_, *dz) in CLOSE.items():
        render_views(out_dir, tag, show, [v], target=tgt, scale=sc_, az_override=az,
                     cam_dz=dz[0] if dz else 0.15)


def main_v2(O):
    t = time.perf_counter()
    body, names = capture_body()
    tick("body_capture", t)
    arm, base = append_base(A.base_blend)
    am = body.modifiers.new("Armature", "ARMATURE")
    am.object = arm
    co, tris, dom, J = body_arrays(body, arm)
    t = time.perf_counter()
    BM = sp.BodyMeasure(co, tris, dom, J)
    M = BM.run()
    tick("measure", t)
    with open(os.path.join(A.out_dir, "measure.json"), "w") as f:
        json.dump(M, f, indent=1)
    np.savez_compressed(os.path.join(A.out_dir, "body.npz"), co=co, tris=tris, dom=dom)
    D = sp.draft(M, O.get("draft"))
    D.svg(os.path.join(A.out_dir, "pattern.svg"))
    from mathutils.bvhtree import BVHTree
    body_bvh = BVHTree.FromPolygons([tuple(p) for p in co], [tuple(t) for t in tris])
    under_bvh = under_tree(co, tris, [base[k] for k in O["colliders"] if k in base])
    O["_joints"] = J
    O["_neck_cy"] = 0.5 * (M["nape"][1] + M["front_neck"][1])
    t = time.perf_counter()
    C = build_cloth(D, M, BM, under_bvh, O)
    n0 = len(C["X"])
    print(f"[spike] cloth verts {n0} tris {len(C['T'])} sew edges {len(C['sew'])}", flush=True)
    # canvas: the front, full, feathered toward the hem
    v2 = True
    y0, y1 = D.frame["yw"] - 6.0, D.frame["yh"]
    canvas = np.zeros(n0)
    for n in C["names"]:
        I = C["info"][n]
        if I["kind"] == "front":
            canvas[I["base"]:I["base"] + len(I["V"])] = 1.0 - O["canvas"]["hem_drop"] * sp.smoothstep(
                (I["V"][:, 1] - y0) / (y1 - y0))
        if v2 and I["kind"] in ("back", "front"):
            # the neckline is interfaced and taped: a stiff band that fades over neck_band_cm
            nk = D.geom(n).edge("neck" if I["kind"] == "back" else "gorge")
            dn = _dist_polyline(I["V"], nk)
            sl = slice(I["base"], I["base"] + len(I["V"]))
            canvas[sl] = np.maximum(canvas[sl], 1.0 - sp.smoothstep(dn / O["canvas"]["neck_band_cm"]))
        bands = O.get("canvas_bands")
        if v2 and bands:
            e = {"back": "hem", "side": "hem", "front": "hem", "top_sleeve": "cuff", "under_sleeve": "cuff"}.get(I["kind"])
            if e is not None:
                w_cm = bands["cuff_cm" if e == "cuff" else "hem_cm"]
                dh = _dist_polyline(I["V"], D.geom(n).edge(e))
                sl = slice(I["base"], I["base"] + len(I["V"]))
                canvas[sl] = np.maximum(canvas[sl], 1.0 - sp.smoothstep((dh - w_cm) / 1.5 + 1.0))
    # the neckline (for the optional stage-2 pin)
    neck = np.zeros(n0, bool)
    for (pn, e, j), g in C["gid"].items():
        if e == "neck" or (e == "gorge" and pn.startswith("front")):
            neck[g] = True
    tick("mesh_place", t)
    # colliders: the hull tube, the body, the shoulder pads, the under-garments
    t = time.perf_counter()
    tube, tube_info, tube_radial = make_tube(co, tris, BM, M, D, base, O)
    pads = make_pad(body, M, O)
    cols = [tube, body] + pads + [base[k] for k in O["colliders"] if k in base]
    for c in cols:
        add_collider(c, O)
    for k in ("jacket", "tie", "buttons"):
        if k in base:
            base[k].hide_viewport = True
    tick("colliders", t)
    sw = np.array(C["sew"])
    stats = {"hull": tube_info, "engine": O["engine"]}
    Ef = mesh_edges(C["T"])
    lf = np.linalg.norm(C["R"][Ef[:, 0]] - C["R"][Ef[:, 1]], axis=1)
    lp = np.linalg.norm(C["X"][Ef[:, 0]] - C["X"][Ef[:, 1]], axis=1)
    stats["placed_strain_vs_flat"] = round(float(np.abs(lp / lf - 1).mean()), 4)
    if A.from_run:
        # reuse a previous run's drape (iterate on the rever / renders without re-simulating)
        d = np.load(os.path.join(A.from_run, "drape2.npz"))
        X1, Xw, Tw, wm, X2 = (d[k] for k in ("X1", "Xw", "Tw", "wm", "X2"))
        R2 = Xw
        O["engine"] = "loaded"
        stats["from_run"] = A.from_run
    if O["engine"] == "xpbd":
        t = time.perf_counter()
        lo = C["X"].min(0) - 0.08
        hi = C["X"].max(0) + 0.08
        bgrid, nex = body_sdf(co, tris, lo, hi, sp.merge(XPBD, O.get("xpbd"))["sdf_h"],
                              shells=garment_shells(base, O["colliders"]))
        from character.suit_hull import TubeSDF
        from character.suit_xpbd import union
        sdf = union(PadSDF(bgrid, M, O), TubeSDF(tube_radial))
        T["sdf"] = round(time.perf_counter() - t, 2)
        print(f"[spike] sdf: {T['sdf']} s ({nex} exact samples)", flush=True)
        X1, (Xw, Tw, wm, cnt), X2 = drape_xpbd(C, O, sdf, canvas, stats, neck)
        T["stage1_sim"], T["stage2_sim"] = stats["xpbd_stage1_s"], stats["xpbd_stage2_s"]
        print(f"[spike] xpbd: stage 1 {T['stage1_sim']} s, stage 2 {T['stage2_sim']} s", flush=True)
        R2 = Xw
    elif O["engine"] == "blender":
        ob1 = make_cloth_object(C, "spike_stage1")
        vg = ob1.vertex_groups.new(name="canvas")
        for i in np.nonzero(canvas > 0)[0]:
            vg.add([int(i)], float(canvas[i]), "REPLACE")
        X1, t1 = simulate_stage(ob1, O, O["sew_frames"], [(1, 0.0)], "flat_rest")
        T["stage1_sim"] = t1
        ob1.hide_viewport = True
        ob1.hide_render = True
        Xw, Tw, wm, cnt = weld(C, X1)
    gap1 = np.linalg.norm(X1[sw[:, 0]] - X1[sw[:, 1]], axis=1)
    by_seam = {}
    for (a, b), g in zip(C["sew"], gap1):
        by_seam.setdefault(C["seam_of"][(a, b)].replace("_r", ""), []).append(g)
    stats["stage1_gap_mm"] = {"mean": round(float(gap1.mean() * 1000), 2),
                              "p95": round(float(np.percentile(gap1, 95) * 1000), 2),
                              "max": round(float(gap1.max() * 1000), 2),
                              "per_seam_mean": {k: round(float(np.mean(v) * 1000), 2) for k, v in by_seam.items()},
                              "per_seam_p95": {k: round(float(np.percentile(v, 95) * 1000), 2) for k, v in by_seam.items()}}
    nw = len(Xw)
    sedges = seam_edges(C, wm, Tw)
    np.savez_compressed(os.path.join(A.out_dir, "seams.npz"), edges=np.array(list(sedges.keys()), int).reshape(-1, 2),
                        names=np.array(list(sedges.values())))
    okE = wm[Ef[:, 0]] != wm[Ef[:, 1]]
    stats["crease_stage1_welded"] = crease_stats(Xw, Tw, sedges, O["crease_deg"])
    if O["engine"] == "blender":
        # the stage-2 rest is the sewn state with the seam band relaxed
        t = time.perf_counter()
        seam_v = np.zeros(nw, bool)
        seam_v[np.array(list({v for e in sedges for v in e}))] = True
        RS = O["rest_smooth"]
        band = ring_band(Tw, np.nonzero(seam_v)[0], RS["rings"], nw) & ~boundary_verts(Tw, nw)
        R2 = laplace(Xw, Tw, band, RS["iters"], 0.5)
        l2 = np.linalg.norm(R2[wm[Ef[:, 0]]] - R2[wm[Ef[:, 1]]], axis=1)
        rs = l2[okE] / np.maximum(lf[okE], 1e-9) - 1
        stats["stage2_rest_strain"] = {"mean_abs": round(float(np.abs(rs).mean()), 4),
                                       "p95_abs": round(float(np.percentile(np.abs(rs), 95)), 4)}
        bl, br = C["button"]
        me = bpy.data.meshes.new("spike_stage2")
        me.from_pydata([tuple(p) for p in Xw], [(int(wm[bl]), int(wm[br]))], [tuple(int(i) for i in t_) for t_ in Tw])
        me.update()
        ob2 = bpy.data.objects.new("spike_stage2", me)
        bpy.context.scene.collection.objects.link(ob2)
        ob2.shape_key_add(name="Basis")
        k = ob2.shape_key_add(name="sewn_rest")
        k.data.foreach_set("co", R2.astype(np.float32).ravel())
        k.value = 0.0
        cw = np.zeros(nw)
        np.maximum.at(cw, wm, canvas)
        vg = ob2.vertex_groups.new(name="canvas")
        for i in np.nonzero(cw > 0)[0]:
            vg.add([int(i)], float(cw[i]), "REPLACE")
        pin = None
        if O["pin_neck"] > 0:
            nk = np.zeros(nw, bool)
            nk[wm[neck]] = True
            vg = ob2.vertex_groups.new(name="pin")
            for i in np.nonzero(nk)[0]:
                vg.add([int(i)], float(O["pin_neck"]), "REPLACE")
            pin = 1.0
        tick("weld", t)
        g0, g1 = 1, 1 + O["gravity_ramp"]
        f2 = g1 + O["settle_frames"]
        X2, t2 = simulate_stage(ob2, O, f2, [(g0, 0.0), (g1, 1.0)], "sewn_rest", pin)
        T["stage2_sim"] = t2
        ob2.hide_viewport = True
        ob2.hide_render = True
    np.savez_compressed(os.path.join(A.out_dir, "drape2.npz"), X0=C["X"], X1=X1, Xw=Xw, Tw=Tw, wm=wm, R2=R2, X2=X2,
                        sew=sw, T=C["T"], R=C["R"], pid=C["pid"], names=np.array(C["names"]))
    # --- layer order: out of the body and the under-garments (real surfaces, not the tube)
    t = time.perf_counter()
    for c in cols:
        for mm in list(c.modifiers):
            if mm.type == "COLLISION":
                c.modifiers.remove(mm)
    real = Layers(co, tris, garment_shells(base, O["colliders"]))
    stats["inside_before_push"] = inside_count(X2, real)
    X3, moved = push_out(X2, Tw, real, O["push"]["clear_m"], O["push"]["smooth_iters"])
    stats["pushed_verts"] = moved
    stats["inside_after_push"] = inside_count(X3, real)
    if stats["inside_after_push"]:
        stats["inside_after_push_at"] = [[round(float(c), 3) for c in p] + [round(float(real.signed(p)[0]) * 1000, 1)]
                                         for p in X3 if real.signed(p)[0] < -0.0005][:10]
    tick("push_out", t)
    zone = crease_zones(X3, Tw, sedges, J)
    stats["crease_zone_refs"] = {k: [round(float(c), 3) for c in J[k][0]] for k in ("lowerarm_l", "lowerarm_r")}
    stats["crease_final"] = crease_stats(X3, Tw, sedges, O["crease_deg"], zone=zone)
    stats["crease_seam_over_clean"] = int(sum(v.get("over_thr_clean", 0) for k, v in stats["crease_final"].items()
                                              if not k.startswith("_")))
    stats["crease_seam_hinges"] = int(sum(v.get("hinge_over_thr", 0) for k, v in stats["crease_final"].items()
                                          if not k.startswith("_")))
    # strain against the flat pattern
    l3 = np.linalg.norm(X3[wm[Ef[:, 0]]] - X3[wm[Ef[:, 1]]], axis=1)
    s3 = l3[okE] / np.maximum(lf[okE], 1e-9) - 1
    stats["strain_vs_flat"] = {"mean_abs": round(float(np.abs(s3).mean()), 4),
                               "p99_abs": round(float(np.percentile(np.abs(s3), 99)), 4)}
    # --- the rever (collar + lapel), modelled on the draped edge
    t = time.perf_counter()
    from character import suit_rever
    chains = chains_for_rever(C, wm, D)
    np.savez_compressed(os.path.join(A.out_dir, "chains.npz"), **{f"{k}_ids": v[0] for k, v in chains.items()},
                        **{f"{k}_s": v[1] for k, v in chains.items()})
    shirt_body = under_tree(co, tris, [base[k] for k in ("shirt",) if k in base])
    rs_stats = {}
    Vr, Fr, rinfo = suit_rever.build(X3, Tw, chains, D, [shirt_body], O["rever"], rs_stats)
    stats["rever"] = rs_stats
    stats["rever"]["inside_under"] = inside_count(Vr[:len(rinfo["sheet_X"])], real)
    if "shirt" in base:
        # the shirt collar above the jacket collar at the back neck (a tailor wants 1-1.5 cm)
        sc_ = evaluated(base["shirt"])
        ms, mr = (np.abs(sc_[:, 0]) < 0.01) & (sc_[:, 1] > 0.0), (np.abs(Vr[:, 0]) < 0.01) & (Vr[:, 1] > 0.0)
        if ms.any() and mr.any():
            stats["rever"]["shirt_shows_cb_mm"] = round(float(sc_[ms, 2].max() - Vr[mr, 2].max()) * 1000, 1)
            stats["rever"]["collar_top_cb_z"] = round(float(Vr[mr, 2].max()), 4)
    if stats["rever"]["inside_under"]:
        cv = rinfo["chart_V"]
        bad = [i for i, p in enumerate(Vr[:len(rinfo["sheet_X"])]) if real.signed(p)[0] < -0.0005]
        stats["rever"]["inside_under_at"] = [[round(float(cv[i, 0]), 1), round(float(cv[i, 1]), 1),
                                              round(float(real.signed(Vr[i])[0]) * 1000, 1)] for i in bad[:12]]
        stats["rever"]["inside_under_max_mm"] = round(-min(float(real.signed(Vr[i])[0]) for i in bad) * 1000, 1)
        cov = [i for i in bad if real.covered(Vr[i])]
        stats["rever"]["inside_under_ray"] = len(cov)
        stats["rever"]["inside_under_ray_at"] = [[round(float(cv[i, 0]), 1), round(float(cv[i, 1]), 1)] for i in cov[:12]]
    cov3 = [p for p in X3 if real.covered(p)]
    # inside by both rules (the nearest face says inside and a ray says covered)
    stats["inside_both"] = int(sum(1 for p in cov3 if real.signed(p)[0] < -0.0005))
    stats["inside_after_push_ray"] = len(cov3)
    stats["inside_after_push_ray_at"] = [[round(float(c), 3) for c in p] for p in cov3[:12]]
    if O.get("debug_rever"):
        np.savez_compressed(os.path.join(A.out_dir, "rever_dbg.npz"), chart_V=rinfo["chart_V"], chart_T=rinfo["chart_T"],
                            sheet_X=rinfo["sheet_X"], **rinfo["debug"])
    tick("rever", t)
    rv = mesh_object("spike_jacket_rever", Vr, Fr)
    from character import suit_made_tex
    suit_made_tex.set_uv(rv, rinfo["uv"], rinfo["tag"])
    suit_made_tex.crisp_normals(rv, rinfo["kind"])
    set_parts(rv, np.zeros(len(Fr), int))
    det_obs = []
    uv_obs, uv_marks, uv_tags = {"rever": rv}, {"rever": rinfo["marks"]}, {"rever": rinfo["tags"]}
    if O.get("details"):
        # the made jacket: shell with turned edges and lining, pockets, vents, buttons
        t = time.perf_counter()
        from character import suit_detail
        dst = {}
        det = suit_detail.build(C, D, wm, X3, Tw, O["details"] if isinstance(O["details"], dict) else None, dst)
        Vs_, Fs_, ps_, us_, ts_, ks_ = det["shell"]
        jk = mesh_object("spike_jacket_body", Vs_, Fs_)
        set_parts(jk, ps_)
        suit_made_tex.set_uv(jk, us_, ts_)
        suit_made_tex.crisp_normals(jk, ks_)
        uv_obs["shell"] = jk
        for k in ("pockets", "buttons", "buttonhole"):
            if det.get(k) is not None:
                ob_ = mesh_object(f"spike_jacket_{k}", det[k][0], det[k][1])
                set_parts(ob_, det[k][2])
                if det[k][3] is not None:
                    suit_made_tex.set_uv(ob_, det[k][3], det[k][4])
                    uv_obs[k] = ob_
                if det[k][5] is not None:
                    suit_made_tex.crisp_normals(ob_, det[k][5])
                det_obs.append(ob_)
        uv_marks.update(det["_uv"]["marks"])
        uv_tags.update(det["_uv"]["tags"])
        dst["clearance_mm"] = detail_clearance(X3, Tw, det)
        stats["detail"] = dst
        parts_ = {k: v for k, v in det.items() if v is not None and not k.startswith("_")}
        np.savez_compressed(os.path.join(A.out_dir, "made.npz"),
                            **{f"{k}_V": v[0] for k, v in parts_.items()},
                            **{f"{k}_F": np.array([list(f) + [-1] * (4 - len(f)) for f in v[1]]) for k, v in parts_.items()},
                            **{f"{k}_part": v[2] for k, v in parts_.items()},
                            **{f"{k}_uv": np.array([list(np.ravel(u)) + [0.0] * (8 - np.size(u)) for u in v[3]])
                               for k, v in parts_.items() if v[3] is not None},
                            **{f"{k}_tag": v[4] for k, v in parts_.items() if v[4] is not None})
        tick("details", t)
    else:
        jk = mesh_object("spike_jacket_body", X3, Tw)
    stats["made_tris"] = sum(len(p.vertices) - 2 for ob_ in [jk, rv] + det_obs for p in ob_.data.polygons)
    stats["kept_tris"] = int(len(Tw)) + sum(len(f) - 2 for f in Fr)
    stats["body_tris"] = int(len(Tw))
    stats["rever_tris"] = sum(len(f) - 2 for f in Fr)
    stats["lofted_tris"] = sum(len(p.vertices) - 2 for p in base["jacket"].data.polygons)
    stats["timings_s"] = T
    stats["draft"] = {"frame": {k: (round(v, 3) if isinstance(v, float) else v) for k, v in D.frame.items()},
                      "seam_lengths_cm": D.seam_lengths()}
    stats["options"] = {k: v for k, v in O.items() if not k.startswith("_")}
    np.savez_compressed(os.path.join(A.out_dir, "kept.npz"), X3=X3, Tw=Tw, Vr=Vr,
                        Fr=np.array([list(f) + [-1] * (4 - len(f)) for f in Fr]))
    with open(os.path.join(A.out_dir, "spike_stats.json"), "w") as f:
        json.dump(stats, f, indent=1, default=float)
    print(json.dumps({k: stats[k] for k in ("stage1_gap_mm", "inside_after_push", "kept_tris")}, indent=1), flush=True)
    for nm, v in stats["crease_final"].items():
        print(f"[spike] crease {nm}: {v}", flush=True)
    made_mats = None
    if O.get("textures"):
        # the wool atlas and the materials: before the LODs (their copies carry the atlas UVs);
        # assigned after the clay renders, which take the slots
        t = time.perf_counter()
        made_mats, stats["textures"] = suit_made_tex.bake(uv_obs, uv_marks, uv_tags, suit.DEFAULTS,
                                                          O["textures"] if isinstance(O["textures"], dict) else None)
        tick("textures", t)
    if A.no_render:
        return
    t = time.perf_counter()
    tube.hide_render = True
    for p in pads:
        p.hide_render = True
    under = [body.name] + [base[k].name for k in ("shirt", "waistcoat", "trousers", "shoes", "tie") if k in base]
    base["jacket"].hide_viewport = False
    bpy.context.scene.frame_set(1)
    pat = [jk.name, rv.name] + [o_.name for o_ in det_obs]
    if not A.no_clay:
        render_views(A.out_dir, "lofted", under + [base["jacket"].name], list(VIEWS))
        render_views(A.out_dir, "pattern", under + pat, list(VIEWS))
        render_close(A.out_dir, "lofted", under + [base["jacket"].name])
        render_close(A.out_dir, "pattern", under + pat)
        if det_obs:
            render_detail_close(A.out_dir, "pattern", under + pat)
    if O.get("lods"):
        lods = make_lods([jk, rv] + det_obs, O["lods"])
        stats["lod_tris"] = {k: v[1] for k, v in lods.items()}
        for k, (ob_, _) in lods.items():
            if not A.no_clay:
                render_views(A.out_dir, f"lod{k}", under + [ob_.name], ["front", "three_quarter"])
    if O.get("debug_rever"):
        render_close(A.out_dir, "rever", [body.name, rv.name])
        render_close(A.out_dir, "jbody", [body.name, jk.name])
        render_views(A.out_dir, "rever", [body.name, rv.name], ["front", "back"], target=(0, 0, 1.4), scale=0.7)
    tick("render", t)
    if made_mats is not None:
        # kept in spike.blend for the beauty frames (suit_beauty.py), the LODs too
        lod_obs = [ob_ for k, (ob_, _) in sorted(lods.items())] if O.get("lods") else []
        suit_made_tex.assign([jk, rv] + det_obs + lod_obs, made_mats)
        side_ = made_mats[0]["suit_atlas_side_m"]
        stats["textures"]["uv_lod"] = {ob_.name: suit_made_tex.uv_stats(ob_, side_) for ob_ in lod_obs}
    stage_rig(bpy.context.scene)              # (--no-clay: the beauty frames need the camera and lights)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(A.out_dir, "spike.blend"), compress=True)
    with open(os.path.join(A.out_dir, "spike_stats.json"), "w") as f:
        stats["timings_s"] = T
        json.dump(stats, f, indent=1, default=float)


def _cli_opts():
    """--opts: inline JSON, or @path to a JSON file."""
    if not A.opts:
        return {}
    if A.opts.startswith("@"):
        with open(A.opts[1:]) as f:
            return json.load(f)
    return json.loads(A.opts)


def main():
    O = sp.merge(SPIKE, _cli_opts())
    if O.get("v2") or A.v2:
        return main_v2(sp.merge(sp.merge(SPIKE, SPIKE2), _cli_opts()))
    t = time.perf_counter()
    body, names = capture_body()
    tick("body_capture", t)
    t = time.perf_counter()
    arm, base = append_base(A.base_blend)
    tick("append_base", t)
    am = body.modifiers.new("Armature", "ARMATURE")
    am.object = arm
    co, tris, dom, J = body_arrays(body, arm)
    np.savez_compressed(os.path.join(A.out_dir, "body.npz"), co=co, tris=tris, dom=dom)
    with open(os.path.join(A.out_dir, "joints.json"), "w") as f:
        json.dump(J, f)
    t = time.perf_counter()
    BM = sp.BodyMeasure(co, tris, dom, J)
    M = BM.run()
    tick("measure", t)
    with open(os.path.join(A.out_dir, "measure.json"), "w") as f:
        json.dump(M, f, indent=1)
    if A.measure_only:
        return
    t = time.perf_counter()
    D = sp.draft(M, O.get("draft"))
    D.svg(os.path.join(A.out_dir, "pattern.svg"))
    tick("draft", t)
    from mathutils.bvhtree import BVHTree
    body_bvh = BVHTree.FromPolygons([tuple(p) for p in co], [tuple(t) for t in tris])
    under_bvh = under_tree(co, tris, [base[k] for k in O["colliders"] if k in base])
    O["_joints"] = J
    O["_neck_cy"] = 0.5 * (M["nape"][1] + M["front_neck"][1])
    t = time.perf_counter()
    C = build_cloth(D, M, BM, under_bvh, O)
    ob = make_cloth_object(C, "spike_cloth")
    # canvassed zones bend stiffer: the whole front (full canvas, feathered
    # from the chest to the hem so the stiffness step does not hinge) and the collar
    vg = ob.vertex_groups.new(name="canvas")
    y0, y1 = D.frame["yw"] - 6.0, D.frame["yh"]
    for n in C["names"]:
        I = C["info"][n]
        if I["kind"] == "front":
            wv = 1.0 - O["canvas"]["hem_drop"] * sp.smoothstep((I["V"][:, 1] - y0) / (y1 - y0))
        elif I["kind"] == "collar":
            wv = np.ones(len(I["V"]))
        else:
            continue
        for i, wi in enumerate(wv):
            vg.add([int(i + I["base"])], float(wi), "REPLACE")
    tick("mesh_place", t)
    print(f"[spike] cloth verts {len(C['X'])} tris {len(C['T'])} sew edges {len(C['sew'])}", flush=True)
    np.savez_compressed(os.path.join(A.out_dir, "placed.npz"), X=C["X"], R=C["R"], T=C["T"],
                        sew=np.array(C["sew"]), pid=C["pid"])
    if A.place_only:
        for o in list(base.values()):
            o.hide_render = True
        render_views(A.out_dir, "placed", [body.name, ob.name], ["front", "three_quarter", "profile", "back"])
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(A.out_dir, "placed.blend"), compress=True)
        return
    # colliders
    t = time.perf_counter()
    pads = make_pad(body, M, O)
    cols = [body] + pads + [base[k] for k in O["colliders"] if k in base]
    for c in cols:
        add_collider(c, O)
    for k in ("jacket", "tie", "buttons"):
        if k in base:
            base[k].hide_viewport = True   # not in the sim's depsgraph as colliders
    tick("colliders", t)
    f_rest = O["sew_frames"] + O["gravity_ramp"] + O["settle_frames"]
    frames = [1, O["sew_frames"], f_rest]
    B = O.get("bent")
    if B:
        f_b0, f_b1 = f_rest, f_rest + B["frames"]
        f_bent = f_b1 + B["hold"]
        key_bent(arm, f_b0, f_b1, B["flex_deg"], B["elbow_deg"])
        frames.append(f_bent)
    t = time.perf_counter()
    res, times, cm_ = simulate(ob, cols, arm, O, frames)
    tick("simulate", t)
    np.savez_compressed(os.path.join(A.out_dir, "drape.npz"), **{f"f{k}": v for k, v in res.items()})
    cols_bvh = []
    bpy.context.scene.frame_set(f_rest)
    dg = bpy.context.evaluated_depsgraph_get()
    for c in cols[1:]:
        cols_bvh.append(BVHTree.FromObject(c, dg))
    stats = {"sew": drape_stats(C, res[O["sew_frames"]], body_bvh, cols_bvh),
             "rest": drape_stats(C, res[f_rest], body_bvh, cols_bvh)}
    # keep geometry
    ob.hide_render = True
    ob.hide_viewport = True
    jk = keep_geometry(C, res[f_rest], "spike_jacket_rest", smooth=O["seam_smooth"])
    stats["kept_tris"] = sum(len(p.vertices) - 2 for p in jk.data.polygons)
    stats["kept_verts"] = len(jk.data.vertices)
    stats["lofted_tris"] = sum(len(p.vertices) - 2 for p in base["jacket"].data.polygons)
    stats["timings_s"] = T
    stats["sim_frame_times_s"] = times
    stats["draft"] = {"frame": {k: (round(v, 3) if isinstance(v, float) else v) for k, v in D.frame.items()},
                      "seam_lengths_cm": D.seam_lengths(),
                      "panel_area_m2": {n: round(p.area() / 1e4, 4) for n, p in D.panels.items()}}
    stats["measure"] = M
    stats["options"] = {k: v for k, v in O.items() if not k.startswith("_")}
    with open(os.path.join(A.out_dir, "spike_stats.json"), "w") as f:
        json.dump(stats, f, indent=1, default=float)
    print(json.dumps({k: stats[k] for k in ("sew", "rest", "kept_tris", "lofted_tris")}, indent=1))
    if A.no_render:
        return
    # renders at rest: lofted vs pattern, with the same body, shirt, waistcoat, trousers, shoes
    bpy.context.scene.frame_set(f_rest)
    for c in cols:
        for mm in list(c.modifiers):
            if mm.type == "COLLISION":
                c.modifiers.remove(mm)
    for p in pads:
        p.hide_render = True
    t = time.perf_counter()
    under = [body.name] + [base[k].name for k in ("shirt", "waistcoat", "trousers", "shoes", "tie") if k in base]
    base["jacket"].hide_viewport = False
    bpy.context.scene.frame_set(1)          # rig at rest
    render_views(A.out_dir, "lofted", under + [base["jacket"].name], list(VIEWS))
    render_views(A.out_dir, "pattern", under + [jk.name], list(VIEWS))
    if B:
        jb = keep_geometry(C, res[f_bent], "spike_jacket_bent", smooth=O["seam_smooth"])
        bpy.context.scene.frame_set(f_bent)
        render_views(A.out_dir, "lofted_bent", under + [base["jacket"].name], ["front", "three_quarter", "profile"])
        render_views(A.out_dir, "pattern_bent", under + [jb.name], ["front", "three_quarter", "profile"])
    tick("render", t)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(A.out_dir, "spike.blend"), compress=True)
    with open(os.path.join(A.out_dir, "spike_stats.json"), "w") as f:
        stats["timings_s"] = T
        json.dump(stats, f, indent=1, default=float)


main()
