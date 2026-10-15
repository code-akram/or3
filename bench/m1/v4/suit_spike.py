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
ap.add_argument("--trousers", action="store_true", help="T13 item 3: the pattern-drafted trousers (main_trousers)")
ap.add_argument("--waistcoat", action="store_true", help="T13 item 4: the pattern-drafted waistcoat (main_waistcoat)")
ap.add_argument("--shirt", action="store_true", help="T13 item 5: the pattern-drafted shirt (main_shirt)")
ap.add_argument("--jacket-ref", default="", help="item 5: a jacket run whose sleeve end places the shirt's cuff")
ap.add_argument("--shirt-from", default="", help="item 5: a --shirt run whose made shirt replaces the lofted one")
ap.add_argument("--waistcoat-from", default="", help="item 5: a --waistcoat run whose made waistcoat replaces the "
                "lofted one (the jacket over the final layers)")
ap.add_argument("--trousers-from", default="", help="spike 2: a --trousers run whose made trousers replace the "
                "lofted ones (collider, hull, renders)")
ap.add_argument("--posed", default="", help="item 6: a --v2 jacket run (over the made layers) to rig and pose")
ap.add_argument("--poses", default="", help="item 6: the pose set (comma list; default POSED['poses'])")
ap.add_argument("--posed-cache", default="", help="item 6: a --posed run whose per-pose drapes (posed.npz) are "
                "reused (no simulation; the fits, checks and frames are redone)")
A = ap.parse_args(argv)
os.makedirs(A.out_dir, exist_ok=True)
T = {}
T0 = time.perf_counter()
CFG = {}


def tick(name, t):
    T[name] = round(time.perf_counter() - t, 2)
    print(f"[spike] {name}: {T[name]} s", flush=True)


# --- 1. body ----------------------------------------------------------------------------------

def capture_body():
    cfg = config.load(A.config, {"assets": {"system": A.system_assets, "suit": A.suit_assets}})
    CFG.update(cfg)
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
    # the body hash the build looks the made suit up by (suit_made, suit.post)
    from character import suit_made
    os.makedirs(A.out_dir, exist_ok=True)
    with open(os.path.join(A.out_dir, "body_hash.txt"), "w") as f:
        f.write(suit_made.mesh_hash(src_me, getattr(b, "suit_zmax", None)) + "\n")
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

def mesh_panel(D, name, pts_by_edge, h, lines=()):
    """Constrained Delaunay mesh of one panel (flat, cm). Returns verts (n, 2),
    tris (m, 3), {(edge, j): vertex}, roll-line vertex ids. lines: names of the panel's
    internal lines (P.lines) meshed as constrained edges too (a trouser crease), their
    vertices in where[("line:<name>", j)]."""
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
    lines_req = tuple(lines)
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
    for ln in lines_req:
        if ln not in P.lines:
            continue
        Lq = np.asarray(P.lines[ln], float)
        Lr = sp.at_params(Lq, np.linspace(0, 1, max(2, int(math.ceil(sp.arclen(Lq) / h))) + 1))
        ids = []
        for j, p in enumerate(Lr):
            if j in (0, len(Lr) - 1):
                k = int(np.argmin(np.linalg.norm(loop - p, axis=1)))
                if np.linalg.norm(loop[k] - p) > 0.6 * h:
                    k = len(verts)
                    verts.append(tuple(p))
            else:
                k = len(verts)
                verts.append(tuple(p))
            ids.append(k)
            where[("line:" + ln, j)] = k
        edges += [(a, b) for a, b in zip(ids, ids[1:]) if a != b]
        lines[ln] = np.array([verts[i] for i in ids])
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
        for ln in lines_req:
            if ln in lines:
                far &= _dist_polyline(grid, lines[ln]) > 0.45 * h
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


def sleeve_axis(D, O):
    """The left sleeve's axis polyline (shoulder point -> elbow fillet -> wrist), its
    cumulative length and a parallel-transported frame (N up, Fr forward)."""
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
    return axis, L, N, Fr


def place_sleeve(D, M, V, O):
    """Wrap a sleeve panel round the bent arm axis (rest pose): angle from u,
    distance down the axis from v; the crown on the jacket shoulder point. A sleeve cut longer
    than its axis (the shirt's, which blouses over the cuff: frame SL_axis) is placed
    compressed along it."""
    S = D.frame["sleeve"]
    axis, L, N, Fr = sleeve_axis(D, O)
    ks = S.get("SL_axis", S["SL"]) / S["SL"]
    out = np.zeros((len(V), 3))
    for i, (uu, vv) in enumerate(V):
        w = np.interp(vv, [0, S["hcap"], S["v_el"], S["SL"]], [S["Wb"], S["Wb"], S["We"], S["Wc"]])
        pitch = D.opts["sleeve"]["pitch_cm"] * sp.smoothstep((vv - S["hcap"]) / (S["SL"] - S["hcap"]))
        th = 2 * math.pi * (uu - pitch - S["uc"]) / w
        s = min(max(vv * ks / 100.0, 0.0), L[-1])
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

RENDER_SAMPLES = 0             # 0: Blender's default (main_posed sets its own)
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
    if RENDER_SAMPLES:
        # T13d: the soft shadow a raised arm casts on the chest read as a grainy stipple at the
        # default samples (c1 arm raise, abd90)
        sc.eevee.taa_render_samples = RENDER_SAMPLES
        for a_, v_ in (("shadow_ray_count", 4), ("shadow_step_count", 12)):
            if hasattr(sc.eevee, a_):
                setattr(sc.eevee, a_, v_)
    sc.render.film_transparent = False
    sc.render.image_settings.file_format = "PNG"
    sc.view_settings.view_transform = "Standard"
    for o in bpy.data.objects:
        if o.type == "MESH":
            o.hide_render = o.name not in show or o.name in COLLIDER_ONLY
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
    uc = bpy.data.materials.get("spike_clay_under")
    if uc is None:
        # a made under-garment loaded from another run: a cool clay, apart from the garment made here
        uc = bpy.data.materials.new("spike_clay_under")
        uc.use_nodes = True
        b = uc.node_tree.nodes["Principled BSDF"]
        b.inputs["Base Color"].default_value = (0.40, 0.45, 0.52, 1)
        b.inputs["Roughness"].default_value = 0.65
    for o in bpy.data.objects:
        if o.type == "MESH" and o.name in show:
            mat = jc if ("jacket" in o.name or o.name.startswith(("spike_trousers", "spike_waistcoat",
                                                                    "spike_shirt"))) else clay
            if o.name in MADE_SLOTS:
                mat = uc
            if "tie_shell" in o.name:
                # the modelled tie in its own darker clay (in the under clay it vanished on the shirt)
                tc = bpy.data.materials.get("spike_clay_tie")
                if tc is None:
                    tc = bpy.data.materials.new("spike_clay_tie")
                    tc.use_nodes = True
                    b_ = tc.node_tree.nodes["Principled BSDF"]
                    b_.inputs["Base Color"].default_value = (0.16, 0.17, 0.24, 1)
                    b_.inputs["Roughness"].default_value = 0.45
                mat = tc
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


def drape_xpbd(C, O, sdf, canvas, stats, neck=None, neck2=None):
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
    bps = list(C.get("buttons") or [C["button"]])
    bl, br = np.array([a for a, _ in bps]), np.array([b for _, b in bps])
    S.set_sew(list(C["sew"]) + bps, [0.0] * len(C["sew"]) + [P["button_gap_m"]] * len(bps))
    S.sdf = sdf
    # the left front laps over the right at the centre front
    lay = layer_sets(C)
    if lay is not None:
        S.layers = [(lay[0], lay[1], P["layer_gap_m"])]
    # the button pair: the left front's button point stays in front of the right's (a plain
    # distance constraint let the right front come through: run t13b-d2, 13.5 mm)
    S.layer_force = [(bl, br, P["button_gap_m"])]
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
        if C.get("hold_pos") is not None:
            # the runner's own targets per vertex (the shirt: the collar band's base, the cuffs)
            tgt = {}
            S.hold_pos = np.asarray(C["hold_pos"], float)[S.hold_idx]
        else:
            tgt = neck_targets(C, Xm, wm0, P["neck_fair_iters"])
            S.hold_pos = np.array([tgt.get(int(wm0[i]), Xm[wm0[i]]) for i in S.hold_idx])
        stats["_neck_tgt"] = tgt
        stats["neck_hold_moved_mm"] = round(float(np.abs(S.hold_pos - Xm[wm0[S.hold_idx]]).max()) * 1000, 1)
        S.hold_k = P["neck_hold_k"]
    # post-collision hooks: (factory(idx) -> fn(X, free), mask on the unwelded vertices)
    S.post = [fac(np.nonzero(m)[0]) for fac, m in C.get("post", [])]
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
    S2.set_sew([(int(wm[a]), int(wm[b])) for a, b in bps], [P["button_gap_m"]] * len(bps))
    S2.sdf = sdf
    if lay is not None:
        S2.layers = [(np.unique(wm[lay[0]]), np.unique(wm[lay[1]]), P["layer_gap_m"])]
    S2.layer_force = [(wm[bl], wm[br], P["button_gap_m"])]
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
        for i in np.nonzero(neck if neck2 is None else neck2)[0]:   # (neck2: a stage-2 hold of its own)
            hold[int(wm[i])] = tgt.get(int(wm0[i]), Xw[wm[i]])
        S2.hold_idx = np.array(sorted(hold), int)
        S2.hold_pos = np.array([hold[k] for k in S2.hold_idx])
        S2.hold_k = P["neck_hold_k2"]
    S2.post = [fac(np.unique(wm[np.nonzero(m)[0]])) for fac, m in C.get("post", [])]
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


def make_lods(obs, ratios, prefix="spike_jacket"):
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
        j.name = f"{prefix}_lod{k}"
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


COLLIDER_ONLY = set()       # objects the drape collides with that the renders never show
MADE_SLOTS = {}             # a loaded made garment's own material slots (the clay takes them)


def load_made(run, prefix):
    """Append a spike run's made garment (its objects named prefix*, not the LODs or a
    collider, with their materials) from RUN/spike.blend."""
    with bpy.data.libraries.load(os.path.join(run, "spike.blend"), link=False) as (src, dst):
        dst.objects = [n for n in src.objects if n.startswith(prefix) and "lod" not in n and "collider" not in n]
    out = []
    for o in dst.objects:
        if o is not None:
            bpy.context.scene.collection.objects.link(o)
            out.append(o)
            MADE_SLOTS[o.name] = list(o.data.materials)
            for m in o.data.materials:
                if m is not None:
                    m.use_fake_user = True      # the clay renders take the slots for a while
    return out


def restore_made():
    """The loaded made garments' own materials back after the clay renders."""
    for n, mats in MADE_SLOTS.items():
        o = bpy.data.objects.get(n)
        if o is not None and all(m is not None for m in mats):
            o.data.materials.clear()
            for m in mats:
                o.data.materials.append(m)


def press_under(obs, X, T, body_bvh, clear=0.0025, reach=0.03, radius=0.015):
    """A made under-garment pressed under the garment draped over it (X, T: its kept mid-surface).
    The drape sees the under-layers as rigid, but a shirt is soft: where the jacket's sleeve folds
    into the crook it lies on the shirt's own crook fold, and the shirt came through (t13c-q2).
    Each under vertex in front of the outer surface (within reach, and over a face, not beside its
    edge) is moved in to `clear` behind it, and its neighbours within `radius` by a falling share
    (so both faces of a made solid move together). Returns {object name: [pressed, max mm]}."""
    from mathutils.bvhtree import BVHTree
    from mathutils.kdtree import KDTree
    ob_bvh = BVHTree.FromPolygons([tuple(p) for p in X], [tuple(int(i) for i in t) for t in T])
    out = {}
    for o in obs:
        P = evaluated(o)
        disp = np.zeros_like(P)
        hits = []
        for i, p in enumerate(P):
            loc, nor, _, dist = ob_bvh.find_nearest(Vector(p))
            if loc is None or dist > reach:
                continue
            loc, n = np.array(loc), np.array(nor)
            bl = body_bvh.find_nearest(Vector(loc))[0]
            if bl is not None and np.dot(n, loc - np.array(bl)) < 0:
                n = -n
            d = p - loc
            s = float(np.dot(d, n))
            if s > -clear and (dist < 1e-6 or abs(s) > 0.9 * dist):
                hits.append((i, (s + clear), n))
        if hits:
            kd = KDTree(len(P))
            for i, p in enumerate(P):
                kd.insert(Vector(p), i)
            kd.balance()
            for i, a, n in hits:
                for _, j, r in kd.find_range(Vector(P[i]), radius):
                    v = a * (1.0 - r / radius) * (-n)
                    if np.dot(v, v) > np.dot(disp[j], disp[j]):
                        disp[j] = v
            Mi = np.array(o.matrix_world.inverted())
            Q = P + disp
            Q = Q @ Mi[:3, :3].T + Mi[:3, 3]
            o.data.vertices.foreach_set("co", Q.astype(np.float32).ravel())
            o.data.update()
        out[o.name] = [len(hits), round(float(np.linalg.norm(disp, axis=1).max()) * 1000, 2) if hits else 0.0]
    return out


def use_layers(base, body, skip=(), drop=None, cap=None):
    """The made under-garments (--trousers-from, --shirt-from, --waistcoat-from) in place of the
    lofted ones. base[key] becomes what the drape collides with: a join of the made parts but the
    buttons (the shirt's shell, collar and cuffs; the waistcoat's shell and welts; the trousers'
    shell and pockets), their outer faces only, that the renders never show (COLLIDER_ONLY).
    Outer only: the made parts are solids, and the distance field reads an open shell by its
    nearest face, so a point under the shirt but nearer its inner face (which looks at the body)
    read as outside. The waistcoat settled under the made shirt in four places (t13w-b1).
    drop: {key: panel-name fragments} left out of that collider.
    cap: {key: metres}: the collider's shell pressed toward the body where it stands further off
    than that (a quarter of the excess kept). The drape takes the under-layers as rigid, but a
    shirt is soft and the waistcoat presses it flat: over the shirt as draped, the close
    waistcoat (6 cm chest ease over the shirt's 11) stretched round its bulk under the arms
    until the armholes tore open to the waist (strain p99 50 %, t13w-b5, b6). The rendered
    shirt is then pressed under the draped waistcoat (press_under).
    Returns the made objects; render them and base's (a collider is skipped)."""
    from mathutils.bvhtree import BVHTree
    bv = evaluated(body)
    bvh = BVHTree.FromPolygons([tuple(p) for p in bv], [tuple(p.vertices) for p in body.data.polygons])
    made = []
    for key, run, prefix in (("trousers", A.trousers_from, "spike_trousers_"),
                             ("shirt", A.shirt_from, "spike_shirt_"),
                             ("waistcoat", A.waistcoat_from, "spike_waistcoat_")):
        if not run or key in skip:
            continue
        obs = load_made(run, prefix)
        if key in base:
            base[key].hide_render = True
            base[key].hide_viewport = True
        V, F, n_in = [], [], 0
        frag = (drop or {}).get(key, ())
        gone = set()
        if frag:
            nm_ = [str(n) for n in np.load(os.path.join(run, "drape2.npz"))["names"]]
            gone = {i + 1 for i, n in enumerate(nm_) if any(f in n for f in frag)}
        for o in obs:
            if o.name.endswith("buttons") or (frag and o.name.endswith("cuffs")):
                continue
            P = evaluated(o)
            if (cap or {}).get(key) and o.name.endswith("shell"):
                c_ = cap[key]
                for i_, p_ in enumerate(P):
                    loc_ = bvh.find_nearest(Vector(p_))[0]
                    if loc_ is None:
                        continue
                    dv = p_ - np.array(loc_)
                    dn = float(np.linalg.norm(dv))
                    if dn > c_:
                        P[i_] = np.array(loc_) + dv / dn * (c_ + 0.25 * (dn - c_))
            n0 = sum(len(v) for v in V)
            pa = o.data.attributes.get("panel")
            ptag = np.zeros(len(o.data.polygons), np.int32)
            if pa is not None and gone:
                pa.data.foreach_get("value", ptag)
            for p in o.data.polygons:
                if gone and int(ptag[p.index]) in gone:
                    continue
                ids = list(p.vertices)
                c = P[ids].mean(0)
                n = np.cross(P[ids[1]] - P[ids[0]], P[ids[2]] - P[ids[0]])
                loc = bvh.find_nearest(Vector(c))[0]
                if loc is not None and float(np.dot(n, c - np.array(loc))) <= 0:
                    n_in += 1
                    continue
                F.append(tuple(n0 + i for i in ids))
            V.append(P)
        col = mesh_object(f"{prefix}collider", np.vstack(V), F, smooth=False)
        col.hide_render = True
        COLLIDER_ONLY.add(col.name)
        print(f"[spike] {key} from {os.path.basename(run.rstrip('/'))}: collider {len(F)} faces "
              f"({n_in} inner dropped)", flush=True)
        base[key] = col
        made += obs
    return made


def main_v2(O):
    t = time.perf_counter()
    body, names = capture_body()
    tick("body_capture", t)
    arm, base = append_base(A.base_blend)
    # the made under-garments (--trousers-from, --shirt-from, --waistcoat-from) in place of the lofted
    made_tr = use_layers(base, body, skip=())
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
    for k_, r_ in (("trousers_from", A.trousers_from), ("shirt_from", A.shirt_from), ("waistcoat_from", A.waistcoat_from)):
        if r_:
            stats[k_] = os.path.basename(r_.rstrip("/"))
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
    if made_tr and O.get("press_under", True):
        # the made under-garments pressed in where they come through (the rendered ones; the
        # colliders as draped)
        stats["press_under"] = press_under([o_ for o_ in made_tr if o_.name not in COLLIDER_ONLY],
                                           X3, Tw, body_bvh, clear=O.get("press_clear_m", 0.0045))
        print(f"[spike] press_under: {stats['press_under']}", flush=True)
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
    import hashlib
    stats["hash"] = {k: hashlib.sha256(np.ascontiguousarray(v).tobytes()).hexdigest()[:8]
                     for k, v in (("X1", X1), ("X2", X2), ("X3", np.asarray(X3)), ("Vr", np.asarray(Vr)))}
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
    under += [o_.name for o_ in made_tr if o_.name not in {b_.name for b_ in base.values()}]
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
    restore_made()    # the made under-garments' own slots back after the clay
    stage_rig(bpy.context.scene)              # (--no-clay: the beauty frames need the camera and lights)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(A.out_dir, "spike.blend"), compress=True)
    with open(os.path.join(A.out_dir, "spike_stats.json"), "w") as f:
        stats["timings_s"] = T
        json.dump(stats, f, indent=1, default=float)


# --- T13 item 3: the pattern-drafted trousers ---------------------------------------------------

TROUSERS = {
    "h_cm": 1.4,                 # mesh spacing on the flat panels
    "gap_m": 0.008,              # placement: off the body
    "min_clear_m": 0.004,
    "colliders": ["shirt"],
    "shoe_hull": True,           # the shoes collide as convex solids (shoe_hulls); False: as shells
    # the hem is placed above the shoe (the lower leg compressed over span_m to end at shoe top
    # + z0; without span_m the last cm squashed by squash) and falls onto it
    "hem_place": {"z0_above_shoe_m": 0.03, "squash": 0.25, "span_m": 0.40},
    "draft": {},
    # trouser cloth: one layer of worsted (about 280 g/m2), the band canvassed
    "xpbd": {"density": 0.28, "kb": 1.5e-5, "kb_band": 2.0e-4, "self_r": 0.008, "self_excl": 0.025,
             "hold_k": 40.0, "drape_frames": 50},
    "push": {"clear_m": 0.0012, "smooth_iters": 3},
    "crease_deg": 20.0,
    "details": True,             # blender/character/suit_trouser_detail.py; a dict overrides
    "textures": True,
    "lods": [0.4, 0.15],
}


def shoe_hulls(base):
    """The shoes as closed convex solids (one per foot): the trouser hem rests on the shoe and
    cannot fall into its throat (between the topline and the instep), as cloth too wide for
    the opening cannot. [(verts (n, 3), faces)] in world space."""
    import bmesh
    out = []
    for P, _ in garment_shells(base, ["shoes"]):
        for sgn in (1.0, -1.0):
            Q = P[P[:, 0] * sgn > 0]
            if len(Q) < 4:
                continue
            bm = bmesh.new()
            for q in Q:
                bm.verts.new(tuple(q))
            bmesh.ops.convex_hull(bm, input=bm.verts[:])
            for v in [v for v in bm.verts if not v.link_faces]:
                bm.verts.remove(v)
            bm.verts.index_update()
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
            V = np.array([tuple(v.co) for v in bm.verts])
            F = [tuple(v.index for v in f.verts) for f in bm.faces]
            bm.free()
            out.append((V, F))
    return out


def _section_left(BM, z, fmask, clip_mid=True):
    """The left half of the body's section at z (2D points, metres) and the midplane crossings'
    y (front, back) or None."""
    s = BM.sec(2, z, fmask)
    if len(s) == 0:
        return None, None
    a, b = s[:, 0, :2], s[:, 1, :2]
    p = s.reshape(-1, 3)[:, :2]
    pts = p[p[:, 0] >= 0.0]
    cr = (a[:, 0] < 0) != (b[:, 0] < 0)
    mid = None
    if cr.any():
        t = a[cr, 0] / (a[cr, 0] - b[cr, 0])
        y = a[cr, 1] + (b[cr, 1] - a[cr, 1]) * t
        mid = (float(y.min()), float(y.max()))
        pts = np.vstack([pts, [[0.0, mid[0]], [0.0, mid[1]]]])
    return pts, mid


class TrouserRings:
    """The left half's rings round the body, for wrapping the panels: above the fork the
    trunk (hull of the section's left half and the midplane chord), below it the left leg
    (hull of its section, opened up to the panel row's width so the leg hangs straight).
    Each ring: dense (K, 2) closed polygon, the side point (max x) and two arcs from it,
    the front arc and the back arc, each (k, 2) with its arc length."""

    def __init__(self, BM, L, gap, shoe_pts=None):
        from character import suit_trouser_pattern as tp
        self.BM, self.L, self.gap = BM, L, gap
        fd = BM.dom[BM.tris]
        self.f_trunk = np.isin(fd, tp.TRUNK).all(1)
        self.f_leg = np.isin(fd, tp.LEFT_LEG + ("thigh_l",)).all(1)
        self.cache = {}

    def _dense(self, poly, n=360):
        P = np.vstack([poly, poly[:1]])
        s = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))]
        t = np.linspace(0, s[-1], n, endpoint=False)
        return np.stack([np.interp(t, s, P[:, 0]), np.interp(t, s, P[:, 1])], 1)

    def ring(self, z, trunk, width=None):
        key = (round(z, 3), trunk, None if width is None else round(width, 3))
        if key in self.cache:
            return self.cache[key]
        pts, mid = _section_left(self.BM, z, self.f_trunk if trunk else self.f_leg)
        if pts is None or len(pts) < 3:
            self.cache[key] = None
            return None
        if not trunk:
            pts = pts[pts[:, 0] > 0.0]
            mid = None
        h = sp._hull(pts)
        h = sp._offset(h, self.gap)
        D = self._dense(h)
        if width is not None and not trunk:
            per = float(np.linalg.norm(np.diff(np.vstack([D, D[:1]]), axis=0), axis=1).sum())
            if per < width:
                c = D.mean(0)
                D = c + (D - c) * (width / per)
        D[:, 0] = np.maximum(D[:, 0], 0.002)
        n = len(D)
        s_ = int(np.argmax(D[:, 0]))
        dr = 1 if D[(s_ + 3) % n, 1] < D[s_, 1] else -1          # toward the front first
        arcs = []
        for d in (dr, -dr):
            idx = [s_]
            for k in range(1, n):
                i = (s_ + d * k) % n
                idx.append(i)
                if trunk and mid is not None and D[i, 0] <= 0.0025:
                    break
                if not trunk and i == int(np.argmin(D[:, 0])):
                    break
            A = D[idx]
            arcs.append((A, np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(A, axis=0), axis=1))]))
        self.cache[key] = (D, arcs[0], arcs[1])
        return self.cache[key]

    @staticmethod
    def at(arc, f):
        A, s = arc
        t = np.clip(f, 0.0, 1.0) * s[-1]
        return np.array([np.interp(t, s, A[:, 0]), np.interp(t, s, A[:, 1])])


def sagittal_profile(BM, z_top, z_bot, gap, f_trunk):
    """The body's midplane outline from the front at z_top, down and under the crotch, up the
    back to z_top, offset by gap: (P (k, 2) of (y, z), arc s, the front part's index range)."""
    s = BM.sec(0, 0.0, f_trunk)
    za, zb = s[:, 0, 2], s[:, 1, 2]
    zc = float(min(za.min(), zb.min()))
    fr, bk = [], []
    for z in np.arange(z_top, zc + 0.004, -0.004):
        hit = (np.minimum(za, zb) <= z) & (np.maximum(za, zb) > z)
        if not hit.any():
            continue
        a, b = s[hit, 0], s[hit, 1]
        t = (z - a[:, 2]) / np.where(np.abs(b[:, 2] - a[:, 2]) > 1e-12, b[:, 2] - a[:, 2], 1.0)
        y = a[:, 1] + (b[:, 1] - a[:, 1]) * t
        fr.append((float(y.min()) - gap, z))
        bk.append((float(y.max()) + gap, z))
    fr, bk = np.array(fr), np.array(bk)
    under = np.stack([np.linspace(fr[-1, 0], bk[-1, 0], 8), np.full(8, zc - gap)], 1)
    P = np.vstack([fr, under, bk[::-1]])
    arc = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))]
    return P, arc, len(fr)


def _row_interval(outline, y):
    """[x_min, x_max] where the closed outline (cm) crosses the row y."""
    P = np.vstack([outline, outline[:1]])
    a, b = P[:-1], P[1:]
    m = (np.minimum(a[:, 1], b[:, 1]) <= y) & (np.maximum(a[:, 1], b[:, 1]) >= y) & (np.abs(b[:, 1] - a[:, 1]) > 1e-9)
    if not m.any():
        return None
    t = (y - a[m, 1]) / (b[m, 1] - a[m, 1])
    xs = a[m, 0] + (b[m, 0] - a[m, 0]) * t
    return float(xs.min()), float(xs.max())


def place_trousers(D, L, BM, O, shoe_top):
    """Block (cm) -> world (m) for the left leg's panels and band (TrouserRings, the sagittal
    profile for the crotch extensions). Returns {name: X (n, 3)} for V from mesh_panel."""
    F = D.frame
    R = TrouserRings(BM, L, O["gap_m"])
    zws = L["waist_seam_z"]
    P, arc, nf = sagittal_profile(BM, L["band_top_z"] + 0.03, L["crotch_z"], O["gap_m"], R.f_trunk)
    zf = P[:nf, 1]
    hp = O["hem_place"]
    z0 = shoe_top + hp["z0_above_shoe_m"]
    zc = L["crotch_z"]
    outl = {n: D.geom(n).outline() for n in ("front", "back")}

    def s_front(z):
        return float(np.interp(-z, -zf, arc[:nf]))

    def s_back(z):
        nb = len(P) - nf - 8
        zb = P[-nb:, 1]
        return float(np.interp(z, zb, arc[-nb:]))

    def prof(s):
        return np.array([np.interp(s, arc, P[:, 0]), np.interp(s, arc, P[:, 1])])

    # the lowest hem (the back's), pattern y -> world z
    zmin = zws - max(float(outl[k][:, 1].max()) for k in outl) / 100.0

    def z_place(z):
        if hp.get("span_m"):
            # spread over the lower leg (span above z0): the last cm squashed 4:1 buckled into a
            # fold at the back hem in stage 1 (run t13t-d4, left leg); ~15 % over the shin does not
            z1 = z0 + hp["span_m"]
            k = min(1.0, (z1 - z0) / max(z1 - zmin, 1e-6))
            return z if z >= z1 else z1 - (z1 - z) * k
        return z if z >= z0 else z0 - (z0 - z) * hp["squash"]

    fly = D.geom("front").edge("fly")
    cbp = D.geom("back").edge("cb")

    def centre_line(kind, y):
        if kind == "front":
            return float(np.interp(y, fly[:, 1], fly[:, 0])) if y <= F["y_s"] else F["x_cfs"]
        q = cbp if cbp[0, 1] < cbp[-1, 1] else cbp[::-1]
        return float(np.interp(y, q[:, 1], q[:, 0]))

    def place(kind, V):
        out = np.zeros((len(V), 3))
        for i, (x, y) in enumerate(V):
            z = zws - y / 100.0
            iv = _row_interval(outl[kind], y)
            if iv is None:
                iv = (x, x + 1e-3)
            xs, xi = iv
            arc_i = 1 if kind == "front" else 2
            if y < F["y_c"]:
                ring = R.ring(max(z, zc + 0.004), True)
                x_cl = min(centre_line(kind, y), xi)
                if x <= x_cl + 1e-6:
                    f = (x - xs) / max(x_cl - xs, 1e-6)
                    q = R.at(ring[arc_i], f)
                    out[i] = (q[0], q[1], z)
                else:
                    e = (x - x_cl) / 100.0
                    zr = max(z, zc + 0.004)
                    s = s_front(zr) + e if kind == "front" else s_back(zr) - e
                    yz = prof(s)
                    out[i] = (0.003, yz[0], yz[1])
            else:
                zp = z_place(z)
                iv_o = _row_interval(outl["back" if kind == "front" else "front"], y)
                width = ((xi - xs) + ((iv_o[1] - iv_o[0]) if iv_o else (xi - xs))) / 100.0
                ring = R.ring(zp, False, width)
                if ring is None:
                    ring = R.ring(max(zp, 0.02), False, width)
                f = (x - xs) / max(xi - xs, 1e-6)
                q = R.at(ring[arc_i], f)
                out[i] = (q[0], q[1], zp)
        return out

    def place_band(V):
        Lb, hb = F["band_len"], F["band_cm"]
        out = np.zeros((len(V), 3))
        for i, (x, y) in enumerate(V):
            z = L["band_top_z"] - y / 100.0
            ring = R.ring(z, True)
            fr, bk = ring[1], ring[2]
            Lf, Lk = fr[1][-1], bk[1][-1]
            s = x / Lb * (Lf + Lk)
            q = R.at(fr, 1.0 - s / Lf) if s <= Lf else R.at(bk, (s - Lf) / Lk)
            out[i] = (q[0], q[1], z)
        return out

    return place, place_band


def build_trouser_cloth(D, L, BM, body_bvh, O, shoe_top):
    h = O["h_cm"]
    pts, pairs = D.sample(h)
    place, place_band = place_trousers(D, L, BM, O, shoe_top)
    info, gid = {}, {}
    base = 0
    layout_x = 0.0
    names = list(D.names)
    for name in names:
        P = D.geom(name)
        V, T, where, _ = mesh_panel(D, name, pts, h, lines=("crease",))
        mirror = name.endswith("_r") and name not in D.panels
        Xw = place_band(V) if P.kind == "band" else place(P.kind, V)
        Xw = _push_out(Xw, body_bvh, O["min_clear_m"])
        if mirror:
            Xw = Xw * np.array([-1.0, 1.0, 1.0])
        R_ = np.zeros((len(V), 3))
        R_[:, 0] = (-V[:, 0] if mirror else V[:, 0]) / 100.0 + layout_x
        R_[:, 1] = -V[:, 1] / 100.0
        layout_x += (V[:, 0].max() - V[:, 0].min()) / 100.0 + 0.1
        # one winding: faces point away from the body
        fn = np.cross(Xw[T[:, 1]] - Xw[T[:, 0]], Xw[T[:, 2]] - Xw[T[:, 0]])
        c = Xw[T].mean(1)
        st_ = max(1, len(c) // 60)
        if np.einsum("ij,ij->i", fn[::st_], _outward(c[::st_], body_bvh)).mean() < 0:
            T = T[:, ::-1].copy()
        info[name] = {"V": V, "T": T, "where": where, "base": base, "kind": P.kind, "mirror": mirror,
                      "Xw": Xw, "R": R_}
        for (e, j), i in where.items():
            gid[(name, e, j)] = base + i
        base += len(V)
    X = np.vstack([info[n]["Xw"] for n in names])
    R_ = np.vstack([info[n]["R"] for n in names])
    T = np.vstack([info[n]["T"] + info[n]["base"] for n in names])
    pid = np.concatenate([[i] * len(info[n]["V"]) for i, n in enumerate(names)])
    sew, seam_of = set(), {}
    for sname, pr in pairs:
        for A_, B_ in pr:
            if A_ not in gid or B_ not in gid:
                continue
            i, j = gid[A_], gid[B_]
            if i != j:
                sew.add((min(i, j), max(i, j)))
                seam_of[(min(i, j), max(i, j))] = sname
    return {"X": X, "R": R_, "T": T, "sew": sorted(sew), "pid": pid, "names": names, "info": info,
            "pairs": pairs, "gid": gid, "pts": pts, "seam_of": seam_of}


def drape_garment(C, P, sdf, kb, stats, hold=None):
    """Stage 1 (unwelded: sew, no gravity), weld, stage 2 (welded: gravity). hold: unwelded
    vertex ids held where placed (the band's top: braces). Returns X1, (Xw, Tw, wm, cnt), X2."""
    from character import suit_xpbd as xp
    n0 = len(C["X"])
    mass = xp.mass_from_flat(C["T"], C["R"], n0, np.full(n0, P["density"]))
    E0 = xp.edges_of(C["T"])
    L0 = np.linalg.norm(C["R"][E0[:, 0]] - C["R"][E0[:, 1]], axis=1)
    o = {k: P[k] for k in ("k_stretch", "k_comp", "damping", "friction", "thickness", "stretch_iters")}
    t = time.perf_counter()
    S = xp.Solver(C["X"], C["T"], L0, mass, kb, o)
    S.set_sew(list(C["sew"]))
    S.sdf = sdf
    wm0, nw0 = weld_map(n0, C["sew"])
    Xm = np.zeros((nw0, 3))
    np.add.at(Xm, wm0, C["X"])
    Xm /= np.bincount(wm0, minlength=nw0)[:, None]
    if P["self_r"] > 0:
        S.self_ref, S.self_r, S.self_excl = Xm[wm0], P["self_r"], P["self_excl"]
    if hold is not None and len(hold):
        S.hold_idx = np.asarray(hold, int)
        S.hold_pos = Xm[wm0[S.hold_idx]]
        S.hold_k = P["hold_k"]
    k0, k1 = P["sew_k"]
    nf = P["sew_frames"]
    S.run(nf, P["fps"], P["substeps"], g_of=lambda f: 0.0,
          ksew_of=lambda f: k0 * (k1 / k0) ** min(1.0, f / max(nf - 8, 1)))
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
    t = time.perf_counter()
    Xw, Tw, wm, cnt = weld(C, X1)
    nw = len(Xw)
    Lw = {}
    for (a, b), l in zip(E0, L0):
        e = (int(min(wm[a], wm[b])), int(max(wm[a], wm[b])))
        if e[0] != e[1]:
            Lw.setdefault(e, []).append(l)
    Lw = {e: float(np.mean(v)) for e, v in Lw.items()}
    for a, b in xp.edges_of(Tw):
        Lw.setdefault((int(a), int(b)), float(np.linalg.norm(Xw[a] - Xw[b])))
    mw = np.zeros(nw)
    np.add.at(mw, wm, mass)
    kbw = np.zeros(nw)
    np.maximum.at(kbw, wm, kb)
    S2 = xp.Solver(Xw, Tw, Lw, mw, kbw, o)
    S2.sdf = sdf
    if P["self_r"] > 0:
        S2.self_ref, S2.self_r, S2.self_excl = Xm, P["self_r"], P["self_excl"]
    if hold is not None and len(hold):
        hw = np.unique(wm[np.asarray(hold, int)])
        S2.hold_idx = hw
        S2.hold_pos = Xw[hw].copy()
        S2.hold_k = P["hold_k"]
    gr = P["gravity_ramp"]
    S2.run(P["drape_frames"], P["fps"], P["substeps"], g_of=lambda f: 9.81 * min(1.0, (f + 1) / gr))
    stats["xpbd_stage2_s"] = round(time.perf_counter() - t, 2)
    stats["xpbd"] = {"stencils": int(len(S2.S)), "opts": P}
    return X1, (Xw, Tw, wm, cnt), S2.X.copy()


TROUSER_CLOSE = {
    # the wearer's left hem and break (front, side), the knee, the seat and back pocket, the
    # fly and side pocket, the waistband at the side
    "close_hem": (15.0, (0.17, -0.05, 0.12), 0.34),
    "close_hem_side": (90.0, (0.17, -0.03, 0.12), 0.34),
    "close_knee": (20.0, (0.15, -0.05, 0.55), 0.40),
    "close_seat": (180.0, (0.0, 0.08, 1.02), 0.45),
    "close_fly": (10.0, (0.04, -0.10, 1.04), 0.30),
    "close_band": (30.0, (0.10, -0.08, 1.08), 0.26),
}


def main_trousers(O):
    """T13 item 3: draft, place, sew and drape the trousers; the made trousers (turned hem,
    band, pockets), their UVs and atlas; clay and gate frames."""
    from character import suit_trouser_pattern as tp
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
    shoe = garment_shells(base, ["shoes"])[0][0] if "shoes" in base else None
    L = tp.measure_legs(BM, M, shoe, O["draft"])
    tick("measure", t)
    with open(os.path.join(A.out_dir, "measure.json"), "w") as f:
        json.dump({"M": M, "legs": L}, f, indent=1)
    np.savez_compressed(os.path.join(A.out_dir, "body.npz"), co=co, tris=tris, dom=dom)
    with open(os.path.join(A.out_dir, "joints.json"), "w") as f:
        json.dump(J, f)
    D = tp.draft(M, L, O["draft"])
    D.svg(os.path.join(A.out_dir, "pattern.svg"))
    from mathutils.bvhtree import BVHTree
    body_bvh = BVHTree.FromPolygons([tuple(p) for p in co], [tuple(t_) for t_ in tris])
    t = time.perf_counter()
    shoe_top = L.get("shoe_top_z", 0.11)
    C = build_trouser_cloth(D, L, BM, body_bvh, O, shoe_top)
    n0 = len(C["X"])
    print(f"[spike] trouser cloth verts {n0} tris {len(C['T'])} sew edges {len(C['sew'])}", flush=True)
    tick("mesh_place", t)
    stats = {"legs": L, "draft": {"frame": {k: (round(v, 3) if isinstance(v, float) else v) for k, v in D.frame.items()},
                                  "seam_lengths_cm": D.seam_lengths()}}
    Ef = mesh_edges(C["T"])
    lf = np.linalg.norm(C["R"][Ef[:, 0]] - C["R"][Ef[:, 1]], axis=1)
    lp = np.linalg.norm(C["X"][Ef[:, 0]] - C["X"][Ef[:, 1]], axis=1)
    stats["placed_strain_vs_flat"] = round(float(np.abs(lp / lf - 1).mean()), 4)
    P = sp.merge(XPBD, O["xpbd"])
    kb = np.full(n0, P["kb"])
    band = np.zeros(n0, bool)
    hold = []
    for name in C["names"]:
        I = C["info"][name]
        if I["kind"] == "band":
            band[I["base"]:I["base"] + len(I["V"])] = True
    for (pn, e, j), g in C["gid"].items():
        if e == "top":
            hold.append(g)
    kb[band] = P["kb_band"]
    if A.place_only:
        ob = mesh_object("spike_trousers_placed", C["X"], C["T"])
        render_views(A.out_dir, "placed", [body.name, ob.name] + [base[k].name for k in ("shirt", "shoes") if k in base],
                     list(VIEWS), target=(0, 0, 0.6), scale=1.4)
        return
    t = time.perf_counter()
    lo = np.minimum(C["X"].min(0), co.min(0) * np.array([1, 1, 0])) - 0.08
    hi = C["X"].max(0) + 0.08
    shells = garment_shells(base, O["colliders"]) + (shoe_hulls(base) if O["shoe_hull"] else garment_shells(base, ["shoes"]))
    bgrid, nex = body_sdf(co, tris, lo, hi, P["sdf_h"], shells=shells)
    T["sdf"] = round(time.perf_counter() - t, 2)
    print(f"[spike] sdf: {T['sdf']} s ({nex} exact samples)", flush=True)
    if A.from_run:
        d = np.load(os.path.join(A.from_run, "drape2.npz"))
        X1, Xw, Tw, wm, X2 = (d[k] for k in ("X1", "Xw", "Tw", "wm", "X2"))
        stats["from_run"] = A.from_run
    else:
        X1, (Xw, Tw, wm, cnt), X2 = drape_garment(C, P, bgrid, kb, stats, hold)
        T["stage1_sim"], T["stage2_sim"] = stats["xpbd_stage1_s"], stats["xpbd_stage2_s"]
        print(f"[spike] xpbd: stage 1 {T['stage1_sim']} s, stage 2 {T['stage2_sim']} s", flush=True)
    sw = np.array(C["sew"])
    gap1 = np.linalg.norm(X1[sw[:, 0]] - X1[sw[:, 1]], axis=1)
    stats["stage1_gap_mm"] = {"mean": round(float(gap1.mean() * 1000), 2), "p95": round(float(np.percentile(gap1, 95) * 1000), 2),
                              "max": round(float(gap1.max() * 1000), 2)}
    np.savez_compressed(os.path.join(A.out_dir, "drape2.npz"), X0=C["X"], X1=X1, Xw=Xw, Tw=Tw, wm=wm, X2=X2,
                        sew=sw, T=C["T"], R=C["R"], pid=C["pid"], names=np.array(C["names"]))
    import hashlib
    stats["hash"] = {k: hashlib.sha256(np.ascontiguousarray(v).tobytes()).hexdigest()[:8]
                     for k, v in (("X1", X1), ("Xw", Xw), ("X2", X2))}
    t = time.perf_counter()
    real = Layers(co, tris, shells)
    stats["inside_before_push"] = inside_count(X2, real)
    X3, moved = push_out(X2, Tw, real, O["push"]["clear_m"], O["push"]["smooth_iters"])
    stats["pushed_verts"] = moved
    stats["inside_after_push"] = inside_count(X3, real)
    cov3 = [p for p in X3 if real.covered(p)]
    stats["inside_both"] = int(sum(1 for p in cov3 if real.signed(p)[0] < -0.0005))
    tick("push_out", t)
    sedges = seam_edges(C, wm, Tw)
    stats["crease_final"] = crease_stats(X3, Tw, sedges, O["crease_deg"])
    stats["crease_seam_hinges"] = int(sum(v.get("hinge_over_thr", 0) for k, v in stats["crease_final"].items()
                                          if not k.startswith("_")))
    okE = wm[Ef[:, 0]] != wm[Ef[:, 1]]
    l3 = np.linalg.norm(X3[wm[Ef[:, 0]]] - X3[wm[Ef[:, 1]]], axis=1)
    s3 = l3[okE] / np.maximum(lf[okE], 1e-9) - 1
    stats["strain_vs_flat"] = {"mean_abs": round(float(np.abs(s3).mean()), 4),
                               "p99_abs": round(float(np.percentile(np.abs(s3), 99)), 4)}
    # the hem over the shoe: its lowest point at the back and the front
    hem_ids = np.array(sorted({int(wm[g]) for (pn, e, j), g in C["gid"].items() if e == "hem"}))
    Hm = X3[hem_ids]
    stats["hem"] = {"z_min": round(float(Hm[:, 2].min()), 4), "z_max": round(float(Hm[:, 2].max()), 4)}
    np.savez_compressed(os.path.join(A.out_dir, "kept.npz"), X3=X3, Tw=Tw)
    from character import suit_made_tex
    obs, uv_obs, uv_marks, uv_tags = [], {}, {}, {}
    if O.get("details"):
        t = time.perf_counter()
        from character import suit_trouser_detail as td
        dst = {}
        det = td.build(C, D, wm, X3, Tw, O["details"] if isinstance(O["details"], dict) else None, dst)
        for k, v in det.items():
            if k.startswith("_") or v is None:
                continue
            ob_ = mesh_object(f"spike_trousers_{k}", v[0], v[1])
            set_parts(ob_, v[2])
            if v[3] is not None:
                suit_made_tex.set_uv(ob_, v[3], v[4])
                uv_obs[k] = ob_
            if v[5] is not None:
                suit_made_tex.crisp_normals(ob_, v[5])
            obs.append(ob_)
        uv_marks.update(det["_uv"]["marks"])
        uv_tags.update(det["_uv"]["tags"])
        stats["detail"] = dst
        parts_ = {k: v for k, v in det.items() if v is not None and not k.startswith("_")}
        np.savez_compressed(os.path.join(A.out_dir, "made.npz"),
                            **{f"{k}_V": v[0] for k, v in parts_.items()},
                            **{f"{k}_F": np.array([list(f) + [-1] * (4 - len(f)) for f in v[1]]) for k, v in parts_.items()},
                            **{f"{k}_part": v[2] for k, v in parts_.items()})
        tick("details", t)
    else:
        obs.append(mesh_object("spike_trousers_body", X3, Tw))
    stats["made_tris"] = sum(len(p.vertices) - 2 for ob_ in obs for p in ob_.data.polygons)
    stats["kept_tris"] = int(len(Tw))
    stats["lofted_tris"] = sum(len(p.vertices) - 2 for p in base["trousers"].data.polygons) if "trousers" in base else 0
    stats["timings_s"] = T
    stats["options"] = {k: v for k, v in O.items() if not k.startswith("_")}
    with open(os.path.join(A.out_dir, "spike_stats.json"), "w") as f:
        json.dump(stats, f, indent=1, default=float)
    print(json.dumps({k: stats[k] for k in ("stage1_gap_mm", "inside_after_push", "inside_both", "strain_vs_flat",
                                            "hem", "made_tris")}, indent=1, default=float), flush=True)
    for nm, v in stats["crease_final"].items():
        print(f"[spike] crease {nm}: {v}", flush=True)
    made_mats = None
    if O.get("textures") and uv_obs:
        t = time.perf_counter()
        to = dict(O["textures"]) if isinstance(O["textures"], dict) else {}
        to.setdefault("name", "t13t")
        made_mats, stats["textures"] = suit_made_tex.bake(uv_obs, uv_marks, uv_tags, suit.DEFAULTS, to)
        tick("textures", t)
    lods = {}
    if not A.no_render:
        t = time.perf_counter()
        for k in ("jacket", "waistcoat", "tie", "buttons"):
            if k in base:
                base[k].hide_render = True
        bpy.context.scene.frame_set(1)
        under = [body.name] + [base[k].name for k in ("shirt", "shoes") if k in base]
        mine = [o_.name for o_ in obs]
        if not A.no_clay:
            if "trousers" in base:
                render_views(A.out_dir, "lofted", under + [base["trousers"].name], list(VIEWS), target=(0, 0, 0.62), scale=1.35)
            render_views(A.out_dir, "pattern", under + mine, list(VIEWS), target=(0, 0, 0.62), scale=1.35)
            for v, (az, tgt, sc_, *dz) in TROUSER_CLOSE.items():
                render_views(A.out_dir, "pattern", under + mine, [v], target=tgt, scale=sc_, az_override=az,
                             cam_dz=dz[0] if dz else 0.0)
        if O.get("lods"):
            lods = make_lods(obs, O["lods"], prefix="spike_trousers")
            stats["lod_tris"] = {k: v[1] for k, v in lods.items()}
            if not A.no_clay:
                for k, (ob_, _) in lods.items():
                    render_views(A.out_dir, f"lod{k}", under + [ob_.name], ["front", "three_quarter"],
                                 target=(0, 0, 0.62), scale=1.35)
        tick("render", t)
    if made_mats is not None:
        lod_obs = [ob_ for k, (ob_, _) in sorted(lods.items())]
        suit_made_tex.assign(obs + lod_obs, made_mats)
        side_ = made_mats[0]["suit_atlas_side_m"]
        stats["textures"]["uv_lod"] = {ob_.name: suit_made_tex.uv_stats(ob_, side_) for ob_ in lod_obs}
    stage_rig(bpy.context.scene)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(A.out_dir, "spike.blend"), compress=True)
    with open(os.path.join(A.out_dir, "spike_stats.json"), "w") as f:
        stats["timings_s"] = T
        json.dump(stats, f, indent=1, default=float)


# --- T13 item 4: the waistcoat ---------------------------------------------------------------

WAISTCOAT = {
    "v2": True,
    "h_cm": 1.2,
    # placement: off the body hull, clear of the trousers' band (at 0.010 the hem was placed in the
    # band, the distance field pushed it up over the band's top edge in stage 1 and the back rode
    # up 2.5 cm: run t13w-a1)
    "gap_m": 0.016,
    "min_clear_m": 0.005,
    "overlap_m": 0.004,          # the left front laps the right
    "fold_lift_m": 0.006, "rest_fold_deg": 168.0, "tps_reg": 0.5,
    "colliders": ["shirt", "tie", "trousers"],
    "draft": {},
    # one layer of wool with a canvassed front and a lining; the back a lining
    # the neck and shoulders held where placed (without it stage 1 slid the whole waistcoat up
    # 5 cm at the back: run t13w-a2); lighter in stage 2, where it hangs from the shoulders
    "xpbd": {"density": 0.30, "kb": 2.5e-5, "self_r": 0.008, "self_excl": 0.025, "drape_frames": 45,
             "neck_hold_k": 30.0, "neck_hold_k2": 10.0, "neck_fair_iters": 0},
    "buttoned": 4,               # the top four of five (the bottom one is left undone)
    "hold_hem": True,
    # the back is lining seen from outside: a twill lining, not the jacket's satin (rough 0.34 read
    # as black chrome across the back: t13w-a8)
    "textures": {"lining": {"albedo": [0.010, 0.010, 0.012], "rough": 0.55, "sheen": 0.3, "sheen_rough": 0.4,
                            "sheen_tint": [0.8, 0.85, 1.0], "spec": 0.4}},
    # the back neck free (held where placed it rippled, 83 deg at the CB, run t13w-a6; held to the
    # faired line, 69 deg, t13w-a5): the shoulder seams hold it
    "hold_back_neck": False,
    # the upper back laid onto the shirt (it bridged from the blades to the collar and stood 2 cm
    # off the shirt collar behind the nape: t13w-a8): within dmax of the layer under it from the
    # back neck down full_below_m, fading out by free_below_m
    "cling": {"full_below_m": 0.04, "free_below_m": 0.12, "dmax_m": 0.003},
    "shirt_cap_m": 0.006,        # the made shirt pressed to this off the body (use_layers cap)
    "push": {"clear_m": 0.0012, "smooth_iters": 3},
    "crease_deg": 20.0,
    "details": True,
    "lods": [0.4, 0.15],
}

WAISTCOAT_CLOSE = {
    # the V and the buttons, the left point and welt, the breast welt, the back, the side
    "close_v": (8.0, (0.0, -0.12, 1.30), 0.30),
    "close_point": (15.0, (0.05, -0.12, 1.10), 0.24),
    "close_welt": (25.0, (0.10, -0.11, 1.20), 0.22),
    "close_breast": (20.0, (0.10, -0.10, 1.38), 0.22),
    "close_back": (180.0, (0.0, 0.08, 1.30), 0.50),
    "close_side": (90.0, (0.15, 0.0, 1.28), 0.45),
}


def main_waistcoat(O):
    """T13 item 4: draft (from the jacket block), place, sew and drape the waistcoat; the made
    waistcoat (welts, buttons, buttonholes, turned edges, lining back), UVs and atlas; frames."""
    from character import suit_waistcoat_pattern as wp
    from character import suit_trouser_pattern as tp
    t = time.perf_counter()
    body, names = capture_body()
    tick("body_capture", t)
    arm, base = append_base(A.base_blend)
    # the made under-garments (--trousers-from, --shirt-from, --waistcoat-from) in place of the lofted
    made_tr = use_layers(base, body, skip=("waistcoat",), cap={"shirt": O.get("shirt_cap_m")})
    am = body.modifiers.new("Armature", "ARMATURE")
    am.object = arm
    co, tris, dom, J = body_arrays(body, arm)
    t = time.perf_counter()
    BM = sp.BodyMeasure(co, tris, dom, J)
    M = BM.run()
    L = tp.measure_legs(BM, M, None, {})
    tick("measure", t)
    with open(os.path.join(A.out_dir, "measure.json"), "w") as f:
        json.dump(M, f, indent=1)
    np.savez_compressed(os.path.join(A.out_dir, "body.npz"), co=co, tris=tris, dom=dom)
    with open(os.path.join(A.out_dir, "joints.json"), "w") as f:
        json.dump(J, f)
    D = wp.draft(M, L["band_top_z"], O["draft"])
    D.svg(os.path.join(A.out_dir, "pattern.svg"))
    from mathutils.bvhtree import BVHTree
    body_bvh = BVHTree.FromPolygons([tuple(p) for p in co], [tuple(t_) for t_ in tris])
    t = time.perf_counter()
    C = build_cloth(D, M, BM, body_bvh, O)
    # the button pairs: each button point on the left front to the right front's
    fr = D.geom("front")
    bts = np.asarray(fr.notches["buttons"], float)[:O["buttoned"]]
    pairs = []
    for xy in bts:
        il = C["info"]["front"]["base"] + int(np.argmin(np.linalg.norm(C["info"]["front"]["V"] - xy, axis=1)))
        ir = C["info"]["front_r"]["base"] + int(np.argmin(np.linalg.norm(C["info"]["front_r"]["V"] - xy, axis=1)))
        pairs.append((il, ir))
    C["buttons"] = pairs
    n0 = len(C["X"])
    print(f"[spike] waistcoat cloth verts {n0} tris {len(C['T'])} sew edges {len(C['sew'])}", flush=True)
    tick("mesh_place", t)
    stats = {"band_top_z": L["band_top_z"], "trousers_from": os.path.basename(A.trousers_from.rstrip("/")) or None,
             "shirt_from": os.path.basename(A.shirt_from.rstrip("/")) or None,
             "draft": {"frame": {k: (round(v, 3) if isinstance(v, float) else v) for k, v in D.frame.items()
                                 if k != "sleeve"},
                       "seam_lengths_cm": D.seam_lengths()}}
    Ef = mesh_edges(C["T"])
    lf = np.linalg.norm(C["R"][Ef[:, 0]] - C["R"][Ef[:, 1]], axis=1)
    lp = np.linalg.norm(C["X"][Ef[:, 0]] - C["X"][Ef[:, 1]], axis=1)
    stats["placed_strain_vs_flat"] = round(float(np.abs(lp / lf - 1).mean()), 4)
    hide = [k for k in ("jacket", "waistcoat", "buttons") if k in base]
    for k in hide:
        base[k].hide_render = True
    if A.place_only:
        ob = mesh_object("spike_waistcoat_placed", C["X"], C["T"])
        render_views(A.out_dir, "placed", [body.name, ob.name] + [base[k].name for k in ("shirt", "tie", "trousers")
                                                                  if k in base], list(VIEWS))
        return
    t = time.perf_counter()
    lo = C["X"].min(0) - 0.08
    hi = C["X"].max(0) + 0.08
    shells = garment_shells(base, O["colliders"])
    bgrid, nex = body_sdf(co, tris, lo, hi, XPBD["sdf_h"], shells=shells)
    T["sdf"] = round(time.perf_counter() - t, 2)
    print(f"[spike] sdf: {T['sdf']} s ({nex} exact samples)", flush=True)
    post = []
    cl = O.get("cling")
    if cl:
        backs = np.isin(np.asarray(C["names"])[C["pid"]], ["back", "back_r"])
        bn = np.concatenate([np.atleast_1d(g) for (pn, e, j), g in C["gid"].items()
                             if e == "neck" and pn.startswith("back")])
        zb = float(C["X"][bn, 2].min())
        stats["cling_z"] = round(zb, 4)
        post.append((tuck_hook(bgrid, zb - cl["full_below_m"], zb - cl["free_below_m"], cl["dmax_m"]), backs))
    C["post"] = post
    if A.from_run:
        d = np.load(os.path.join(A.from_run, "drape2.npz"))
        X1, Xw, Tw, wm, X2 = (d[k] for k in ("X1", "Xw", "Tw", "wm", "X2"))
        stats["from_run"] = A.from_run
    else:
        # stage 1 holds the shoulders, the back neck and the hem where placed (the hem rode up
        # 5 cm over the trousers' band in stage 1 and caught on its top edge: runs t13w-a2..a4);
        # stage 2 hangs it from the shoulders and back neck only
        hold = np.zeros(n0, bool)
        hem = np.zeros(n0, bool)
        for (pn, e, j), g in C["gid"].items():
            if e == "shoulder" or (e == "neck" and pn.startswith("back") and O["hold_back_neck"]):
                hold[g] = True
            if e == "hem" and O["hold_hem"]:
                hem[g] = True
        X1, (Xw, Tw, wm, cnt), X2 = drape_xpbd(C, O, bgrid, np.zeros(n0), stats, hold | hem, hold)
        T["stage1_sim"], T["stage2_sim"] = stats["xpbd_stage1_s"], stats["xpbd_stage2_s"]
        print(f"[spike] xpbd: stage 1 {T['stage1_sim']} s, stage 2 {T['stage2_sim']} s", flush=True)
    sw = np.array(C["sew"])
    gap1 = np.linalg.norm(X1[sw[:, 0]] - X1[sw[:, 1]], axis=1)
    stats["stage1_gap_mm"] = {"mean": round(float(gap1.mean() * 1000), 2), "p95": round(float(np.percentile(gap1, 95) * 1000), 2),
                              "max": round(float(gap1.max() * 1000), 2)}
    np.savez_compressed(os.path.join(A.out_dir, "drape2.npz"), X0=C["X"], X1=X1, Xw=Xw, Tw=Tw, wm=wm, X2=X2,
                        sew=sw, T=C["T"], R=C["R"], pid=C["pid"], names=np.array(C["names"]))
    import hashlib
    stats["hash"] = {k: hashlib.sha256(np.ascontiguousarray(v).tobytes()).hexdigest()[:8]
                     for k, v in (("X1", X1), ("Xw", Xw), ("X2", X2))}
    t = time.perf_counter()
    real = Layers(co, tris, shells)
    stats["inside_before_push"] = inside_count(X2, real)
    X3, moved = push_out(X2, Tw, real, O["push"]["clear_m"], O["push"]["smooth_iters"])
    free_w = np.ones(len(X3), bool)
    for fac, m in post:                     # the back neck's cling once more on the kept shape
        fac(np.unique(wm[np.nonzero(m)[0]]))(X3, free_w)
    stats["pushed_verts"] = moved
    stats["inside_after_push"] = inside_count(X3, real)
    cov3 = [p for p in X3 if real.covered(p)]
    stats["inside_both"] = int(sum(1 for p in cov3 if real.signed(p)[0] < -0.0005))
    tick("push_out", t)
    sedges = seam_edges(C, wm, Tw)
    stats["crease_final"] = crease_stats(X3, Tw, sedges, O["crease_deg"])
    stats["crease_seam_hinges"] = int(sum(v.get("hinge_over_thr", 0) for k, v in stats["crease_final"].items()
                                          if not k.startswith("_")))
    okE = wm[Ef[:, 0]] != wm[Ef[:, 1]]
    l3 = np.linalg.norm(X3[wm[Ef[:, 0]]] - X3[wm[Ef[:, 1]]], axis=1)
    s3 = l3[okE] / np.maximum(lf[okE], 1e-9) - 1
    stats["strain_vs_flat"] = {"mean_abs": round(float(np.abs(s3).mean()), 4),
                               "p99_abs": round(float(np.percentile(np.abs(s3), 99)), 4)}
    # the fronts at the buttons: the left in front of the right (mm, + = in front)
    bl = np.array([int(wm[a]) for a, _ in C["buttons"]])
    br = np.array([int(wm[b]) for _, b in C["buttons"]])
    nr = _outward(X3[br], body_bvh)
    stats["button_lap_mm"] = [round(float(v) * 1000, 2) for v in np.einsum("ij,ij->i", X3[bl] - X3[br], nr)]
    hem_ids = np.array(sorted({int(wm[g]) for (pn, e, j), g in C["gid"].items() if e == "hem"}))
    stats["hem_z"] = {"min": round(float(X3[hem_ids, 2].min()), 4), "max": round(float(X3[hem_ids, 2].max()), 4)}
    np.savez_compressed(os.path.join(A.out_dir, "kept.npz"), X3=X3, Tw=Tw)
    from character import suit_made_tex
    obs, uv_obs, uv_marks, uv_tags = [], {}, {}, {}
    if O.get("details"):
        t = time.perf_counter()
        from character import suit_waistcoat_detail as wd
        dst = {}
        det = wd.build(C, D, wm, X3, Tw, O["details"] if isinstance(O["details"], dict) else None, dst)
        for k, v in det.items():
            if k.startswith("_") or v is None:
                continue
            ob_ = mesh_object(f"spike_waistcoat_{k}", v[0], v[1])
            set_parts(ob_, v[2])
            if v[3] is not None:
                suit_made_tex.set_uv(ob_, v[3], v[4])
                uv_obs[k] = ob_
            if v[5] is not None:
                suit_made_tex.crisp_normals(ob_, v[5])
            obs.append(ob_)
        uv_marks.update(det["_uv"]["marks"])
        uv_tags.update(det["_uv"]["tags"])
        stats["detail"] = dst
        stats["detail"]["clearance_mm"] = detail_clearance(X3, Tw, {k: v for k, v in det.items()
                                                                  if k in ("pockets", "buttons") and v is not None})
        parts_ = {k: v for k, v in det.items() if v is not None and not k.startswith("_")}
        np.savez_compressed(os.path.join(A.out_dir, "made.npz"),
                            **{f"{k}_V": v[0] for k, v in parts_.items()},
                            **{f"{k}_F": np.array([list(f) + [-1] * (4 - len(f)) for f in v[1]]) for k, v in parts_.items()},
                            **{f"{k}_part": v[2] for k, v in parts_.items()})
        tick("details", t)
    else:
        obs.append(mesh_object("spike_waistcoat_body", X3, Tw))
    if made_tr and O.get("press_under", True):
        # the rendered under-garments pressed in under the waistcoat (the shirt was draped over
        # as a pressed collider: use_layers cap)
        stats["press_under"] = press_under([o_ for o_ in made_tr if o_.name not in COLLIDER_ONLY],
                                           X3, Tw, body_bvh, clear=O.get("press_clear_m", 0.003))
        print(f"[spike] press_under: {stats['press_under']}", flush=True)
    stats["made_tris"] = sum(len(p.vertices) - 2 for ob_ in obs for p in ob_.data.polygons)
    stats["kept_tris"] = int(len(Tw))
    stats["lofted_tris"] = sum(len(p.vertices) - 2 for p in base["waistcoat"].data.polygons) if "waistcoat" in base else 0
    stats["timings_s"] = T
    stats["options"] = {k: v for k, v in O.items() if not k.startswith("_")}
    with open(os.path.join(A.out_dir, "spike_stats.json"), "w") as f:
        json.dump(stats, f, indent=1, default=float)
    print(json.dumps({k: stats[k] for k in ("stage1_gap_mm", "inside_after_push", "inside_both", "strain_vs_flat",
                                            "button_lap_mm", "hem_z", "made_tris")}, indent=1, default=float), flush=True)
    for nm, v in stats["crease_final"].items():
        print(f"[spike] crease {nm}: {v}", flush=True)
    made_mats = None
    if O.get("textures") and uv_obs:
        t = time.perf_counter()
        to = dict(O["textures"]) if isinstance(O["textures"], dict) else {}
        to.setdefault("name", "t13w")
        made_mats, stats["textures"] = suit_made_tex.bake(uv_obs, uv_marks, uv_tags, suit.DEFAULTS, to)
        tick("textures", t)
    lods = {}
    if not A.no_render:
        t = time.perf_counter()
        bpy.context.scene.frame_set(1)
        under = [body.name] + [base[k].name for k in ("shirt", "tie", "trousers", "shoes") if k in base]
        under += [o_.name for o_ in made_tr if o_.name not in {b_.name for b_ in base.values()}]
        mine = [o_.name for o_ in obs]
        if not A.no_clay:
            if "waistcoat" in base:
                render_views(A.out_dir, "lofted", under + [base["waistcoat"].name], list(VIEWS))
            render_views(A.out_dir, "pattern", under + mine, list(VIEWS))
            for v, (az, tgt, sc_, *dz) in WAISTCOAT_CLOSE.items():
                render_views(A.out_dir, "pattern", under + mine, [v], target=tgt, scale=sc_, az_override=az,
                             cam_dz=dz[0] if dz else 0.0)
        if O.get("lods"):
            lods = make_lods(obs, O["lods"], prefix="spike_waistcoat")
            stats["lod_tris"] = {k: v[1] for k, v in lods.items()}
            if not A.no_clay:
                for k, (ob_, _) in lods.items():
                    render_views(A.out_dir, f"lod{k}", under + [ob_.name], ["front", "three_quarter"])
        tick("render", t)
    if made_mats is not None:
        lod_obs = [ob_ for k, (ob_, _) in sorted(lods.items())]
        suit_made_tex.assign(obs + lod_obs, made_mats)
        side_ = made_mats[0]["suit_atlas_side_m"]
        stats["textures"]["uv_lod"] = {ob_.name: suit_made_tex.uv_stats(ob_, side_) for ob_ in lod_obs}
    restore_made()    # the made under-garments' own slots back after the clay
    stage_rig(bpy.context.scene)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(A.out_dir, "spike.blend"), compress=True)
    with open(os.path.join(A.out_dir, "spike_stats.json"), "w") as f:
        stats["timings_s"] = T
        json.dump(stats, f, indent=1, default=float)


# --- T13 item 5: the pattern-drafted shirt ------------------------------------------------------

SHIRT = {
    "v2": True,
    "h_cm": 1.2,
    "gap_m": 0.006,              # placement: off the body hull
    "min_clear_m": 0.003,
    "sleeve_gap_m": 0.006, "elbow_fillet_m": 0.08,
    "overlap_m": 0.0015,         # the left front laps the right
    "fold_lift_m": 0.004, "rest_fold_deg": 168.0, "tps_reg": 0.5,
    "colliders": [],
    "draft": {},
    # shirting: a cotton poplin about 120 g/m2, soft; the collar and cuffs are modelled
    "xpbd": {"density": 0.12, "density_canvas": 0.12, "kb": 4.0e-6, "kb_canvas": 4.0e-6, "kb_sleeve": 4.0e-6,
             "k_stretch": 3000.0, "k_comp": 250.0, "thickness": 0.0022, "self_r": 0.010, "self_excl": 0.025,
             "drape_frames": 45, "neck_hold_k": 40.0, "neck_hold_k2": 40.0, "neck_fair_iters": 0,
             "button_gap_m": 0.0012, "layer_gap_m": 0.0012, "friction": 0.3},
    # the neckline is held inside the collar band, just above its base; the sleeve end inside
    # the cuff's top
    "band_hold": {"up_m": 0.004, "in_m": 0.0018, "lap_m": 0.0012},
    "cuff_hold": {"down_m": 0.007, "in_m": 0.0016},
    # tucked: below the trousers' band top the shirt lies within dmax of the body
    "tuck": {"full_below_m": 0.006, "free_above_m": 0.03, "dmax_m": 0.0025},
    # the sleeve round the elbow pressed onto the arm, as the jacket's sleeve presses it: draped
    # free, its crook fold stood as far off the arm as the jacket's own and came through the
    # jacket's crook (t13c-q2, q3)
    "elbow_press": {"r_full_m": 0.06, "r_free_m": 0.14, "dmax_m": 0.005},
    "tie_clear_m": 0.0012,
    "push": {"clear_m": 0.001, "smooth_iters": 3},
    "crease_deg": 20.0,
    "details": True,
    "textures": {"name": "t13s", "cloth": "shirt"},
    "lods": [0.4, 0.15],
}

SHIRT_CLOSE = {
    # the collar front (under the knot), side and back; the placket; the yoke; the sleeve head
    "close_collar_f": (8.0, (0.0, -0.06, 1.52), 0.22, 0.0),
    "close_collar_s": (80.0, (0.04, -0.01, 1.53), 0.22, 0.0),
    "close_collar_b": (170.0, (0.0, 0.03, 1.54), 0.22, 0.05),
    "close_placket": (10.0, (0.0, -0.10, 1.30), 0.26, 0.0),
    "close_yoke": (180.0, (0.0, 0.08, 1.45), 0.42, 0.0),
    "close_sleevehead": (70.0, (0.21, 0.0, 1.40), 0.32, 0.0),
}


def tie_heightfield(tie_ob, h=0.003, slope=0.6):
    """The tie's back face as y(x, z) on a grid (the shirt front stays behind it)."""
    from mathutils.bvhtree import BVHTree
    dg = bpy.context.evaluated_depsgraph_get()
    me = tie_ob.evaluated_get(dg).to_mesh()
    Mw = np.array(tie_ob.matrix_world)
    P = np.array([tuple(v.co) for v in me.vertices]) @ Mw[:3, :3].T + Mw[:3, 3]
    F = [tuple(p.vertices) for p in me.polygons]
    tie_ob.evaluated_get(dg).to_mesh_clear()
    bvh = BVHTree.FromPolygons([tuple(p) for p in P], F)
    x0, x1 = P[:, 0].min() - h, P[:, 0].max() + h
    z0, z1 = P[:, 2].min() - h, P[:, 2].max() + h
    xs = np.arange(x0, x1 + h, h)
    zs = np.arange(z0, z1 + h, h)
    Y = np.full((len(xs), len(zs)), np.nan)
    for i, x in enumerate(xs):
        for j, z in enumerate(zs):
            hit = bvh.ray_cast(Vector((x, 0.4, z)), Vector((0, -1, 0)), 1.0)
            if hit[0] is not None:
                Y[i, j] = hit[0].y
    # a soft edge: the limit falls back (slope) beside the tie, so the shirt eases out from
    # under it instead of stepping at its edge
    pad = int(round(0.015 / h))
    Yp = np.full((len(xs) + 2 * pad, len(zs) + 2 * pad), np.nan)
    Yp[pad:pad + len(xs), pad:pad + len(zs)] = Y
    Ys = np.full_like(Yp, -np.inf)
    for di in range(-pad, pad + 1):
        for dj in range(-pad, pad + 1):
            dist = math.hypot(di, dj) * h
            if dist > pad * h:
                continue
            sh = np.roll(np.roll(Yp, di, 0), dj, 1)
            Ys = np.fmax(Ys, sh - slope * dist)
    Ys[~np.isfinite(Ys)] = np.nan
    return {"x0": x0 - pad * h, "z0": z0 - pad * h, "h": h, "Y": Ys, "Y0": Y, "pad": pad}


def tie_hook(hf, clear):
    def fac(idx):
        def fn(X, free):
            P = X[idx]
            i = np.round((P[:, 0] - hf["x0"]) / hf["h"]).astype(int)
            j = np.round((P[:, 2] - hf["z0"]) / hf["h"]).astype(int)
            ok = (i >= 0) & (j >= 0) & (i < hf["Y"].shape[0]) & (j < hf["Y"].shape[1])
            yb = np.full(len(P), np.nan)
            yb[ok] = hf["Y"][i[ok], j[ok]]
            bad = ~np.isnan(yb) & (P[:, 1] < yb + clear) & free[idx]
            if bad.any():
                X[idx[bad], 1] = yb[bad] + clear
        return fn
    return fac


def tuck_hook(sdf, z_full, z_free, dmax):
    """Below the trousers' band the shirt is tucked in: within dmax of the body (fading out
    from z_full up to z_free)."""
    sgn = 1.0 if z_free >= z_full else -1.0     # (z_free below z_full: held above, as a cling)

    def fac(idx):
        def fn(X, free):
            z = X[idx, 2]
            w = np.clip(sgn * (z_free - z) / max(abs(z_free - z_full), 1e-6), 0.0, 1.0)
            m = (w > 0) & free[idx]
            if not m.any():
                return
            ii = idx[m]
            d, g = sdf(X[ii])
            lim = dmax / np.maximum(w[m], 1e-3)
            over = d - lim
            k = (over > 0) & (d < 0.5)
            if k.any():
                X[ii[k]] -= over[k][:, None] * g[k]
        return fn
    return fac


def zone_hook(sdf, centers, r_full, r_free, dmax):
    """Within dmax of the body near the centres (full within r_full, fading out by r_free)."""
    Cz = np.asarray(centers, float)

    def fac(idx):
        def fn(X, free):
            dist = np.min(np.linalg.norm(X[idx][:, None] - Cz[None], axis=2), 1)
            w = np.clip((r_free - dist) / max(r_free - r_full, 1e-6), 0.0, 1.0)
            m = (w > 0) & free[idx]
            if not m.any():
                return
            ii = idx[m]
            d, g = sdf(X[ii])
            over = d - dmax / np.maximum(w[m], 1e-3)
            k = (over > 0) & (d < 0.5)
            if k.any():
                X[ii[k]] -= over[k][:, None] * g[k]
        return fn
    return fac


def band_ring(nf, up, inward, a0, a1, n=400):
    """Points just inside the collar band above its base, from angle a0 to a1, and their arc length."""
    a = np.linspace(a0, a1, n)
    P = []
    for ai in a:
        z = nf.zb(ai) + up
        P.append(tuple(nf.point(ai, z, nf.band_r(ai, z) - inward)))
    P = np.array(P)
    s = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))]
    return a, P, s


def jacket_cuff_edge(run, J, sector_n=12):
    """The made jacket's left sleeve end (from a jacket run's kept drape): per angular sector
    round the forearm, the furthest point down the forearm; their median projection (m) on the
    forearm direction, and the direction."""
    d = np.load(os.path.join(run, "kept.npz"))
    X = d["X3"]
    j1, j2 = np.array(J["lowerarm_l"][0]), np.array(J["hand_l"][0])
    u = (j2 - j1) / np.linalg.norm(j2 - j1)
    rel = X - j2
    pr = rel @ u
    q = rel - np.outer(pr, u)
    m = (pr > -0.15) & (pr < 0.05) & (np.linalg.norm(q, axis=1) < 0.08) & (X[:, 0] > 0)
    e1 = np.cross(u, [0, 0, 1.0])
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(u, e1)
    ang = np.arctan2(q[m] @ e2, q[m] @ e1)
    sec = ((ang + math.pi) / (2 * math.pi) * sector_n).astype(int) % sector_n
    mx = [pr[m][sec == k].max() for k in range(sector_n) if (sec == k).any()]
    return float(np.median(mx)) + float(j2 @ u), u, mx


def neck_check(base_blend, nf, collar_inner):
    """T22's claim (the neck forms are zero under the collar) and the collar's seat on the hero
    body: the hero body's neck radius in the collar frame against the frame's own body (the
    spike body, pre-refine), under the band and above it; the made collar's inner face against
    the hero neck."""
    from mathutils.bvhtree import BVHTree
    with bpy.data.libraries.load(base_blend, link=False) as (src, dst):
        dst.objects = [n for n in src.objects if n == "Human_export"]
    ob = dst.objects[0]
    bpy.context.scene.collection.objects.link(ob)
    dg = bpy.context.evaluated_depsgraph_get()
    me = ob.evaluated_get(dg).to_mesh()
    Mw = np.array(ob.matrix_world)
    P = np.array([tuple(v.co) for v in me.vertices]) @ Mw[:3, :3].T + Mw[:3, 3]
    F = [tuple(p.vertices) for p in me.polygons]
    ob.evaluated_get(dg).to_mesh_clear()
    under, above = [], []
    for p in P:
        if abs(p[0]) > 0.09 or not (nf.z0 + 0.01 < p[2] < nf.z0 + nf.dz * (nf.nz - 2)):
            continue
        a, z, r = nf.polar(Vector(p))
        zb, zt = nf.zb(a), nf.zt(a)
        rb = nf.r_body(a, z)
        if r > rb + 0.02:
            continue
        if zb - 0.01 <= z <= zt + 0.003:
            under.append(r - rb)
        elif zt + 0.003 < z < zt + 0.03:
            above.append(r - rb)
    bvh = BVHTree.FromPolygons([tuple(p) for p in P], F)
    clr = []
    for p in collar_inner:
        loc, nor, _, dd = bvh.find_nearest(Vector(p))
        if loc is None:
            continue
        clr.append(float(np.dot(np.asarray(p) - np.array(loc), np.array(nor))))
    clr = np.array(clr) * 1000
    bpy.data.objects.remove(ob, do_unlink=True)

    def st(v):
        v = np.array(v) * 1000
        return {"n": int(len(v)), "abs_max_mm": round(float(np.abs(v).max()), 2) if len(v) else None,
                "p99_abs_mm": round(float(np.percentile(np.abs(v), 99)), 2) if len(v) else None}
    return {"hero_minus_frame_under_band": st(under), "hero_minus_frame_above_band": st(above),
            "collar_inner_to_hero_mm": {"min": round(float(clr.min()), 2), "p01": round(float(np.percentile(clr, 1)), 2),
                                        "median": round(float(np.median(clr)), 2), "inside": int((clr < 0).sum()),
                                        "n": int(len(clr))}}


def main_shirt(O):
    """T13 item 5: draft, place, sew and drape the shirt (body, yoke, sleeves) on the body; the
    collar (band and fall) on the suit_neck frame and the cuffs modelled; the made shirt
    (placket, buttons, flat-felled seams, turned edges), UVs and its cotton atlas; frames."""
    from character import suit_build as sbld
    from character import suit_neck
    from character import suit_shirt_detail as sd_
    from character import suit_shirt_pattern as shp
    from character import suit_trouser_pattern as tp
    t = time.perf_counter()
    body, names = capture_body()
    tick("body_capture", t)
    arm, base = append_base(A.base_blend)
    # the made under-garments (--trousers-from, --shirt-from, --waistcoat-from) in place of the lofted
    made_tr = use_layers(base, body, skip=("shirt", "waistcoat"))
    am = body.modifiers.new("Armature", "ARMATURE")
    am.object = arm
    co, tris, dom, J = body_arrays(body, arm)
    t = time.perf_counter()
    BM = sp.BodyMeasure(co, tris, dom, J)
    M = BM.run()
    L = tp.measure_legs(BM, M, None, {})
    tick("measure", t)
    with open(os.path.join(A.out_dir, "measure.json"), "w") as f:
        json.dump(M, f, indent=1)
    np.savez_compressed(os.path.join(A.out_dir, "body.npz"), co=co, tris=tris, dom=dom)
    with open(os.path.join(A.out_dir, "joints.json"), "w") as f:
        json.dump(J, f)
    O["_joints"] = J
    # the collar frame (suit_neck): the same frame the lofted build fits the jacket collar to
    t = time.perf_counter()
    sbody = sbld.Body(body.data, names, arm)
    supra = sbody.joint("clavicle_l").z
    Ccol = config.merge(suit.DEFAULTS["shirt"]["collar"], ((CFG.get("suit") or {}).get("shirt") or {}).get("collar") or {})
    nf = suit_neck.NeckFrame(sbody, supra, Ccol)
    bh = O["band_hold"]
    a_r, P_r, s_r = band_ring(nf, bh["up_m"], bh["in_m"], math.pi / 2, -math.pi / 2)
    neck = {"z_cb": nf.zb(math.pi / 2), "z_cf": nf.zb(-math.pi / 2), "half_cm": float(s_r[-1] * 100)}
    tick("neck_frame", t)
    stats = {"band_top_z": L["band_top_z"], "trousers_from": os.path.basename(A.trousers_from.rstrip("/")) or None,
             "neck_frame": {"supra_z": round(supra, 4), "band_base_cb_z": round(neck["z_cb"], 4),
                            "band_base_cf_z": round(neck["z_cf"], 4), "band_base_half_cm": round(neck["half_cm"], 2),
                            "band_top_cb_z": round(nf.zt(math.pi / 2), 4)}}
    # the draft, then the cuff's place on the arm (shown show_cm past the jacket's sleeve), and
    # the draft again with the sleeve's length to it
    D = shp.draft(M, neck, O["draft"])
    axis, Lx, Nf, Ff = sleeve_axis(D, O)
    Cf = D.opts["cuff"]
    if A.jacket_ref:
        pj, u_f, mx = jacket_cuff_edge(A.jacket_ref, J)
        j2 = np.array(J["hand_l"][0])
        s_bot = float(Lx[-1] - (j2 @ u_f - (pj + Cf["show_cm"] / 100)))
        stats["jacket_ref"] = {"run": os.path.basename(A.jacket_ref.rstrip("/")),
                               "cuff_edge_above_wrist_cm": round((j2 @ u_f - pj) * 100, 2),
                               "sector_spread_cm": round((max(mx) - min(mx)) * 100, 2)}
    else:
        s_bot = float(Lx[-1] - D.frame["sleeve"]["cuff_bottom_above_wrist"] / 100)
    s_top = s_bot - Cf["h_cm"] / 100
    D = shp.draft(M, neck, sp.merge(O["draft"], {"cuff": {"top_s_cm": s_top * 100}}))
    axis, Lx, Nf, Ff = sleeve_axis(D, O)
    D.svg(os.path.join(A.out_dir, "pattern.svg"))
    cf = sd_.cuff_frame(axis, Lx, Nf, Ff, s_top, s_bot, co, D.frame["sleeve"]["cuff_round"] / 100,
                        sd_.DEFAULTS["cuff"]["gap_mm"] / 1000)
    stats["cuff_frame"] = {"s_top": round(s_top, 4), "s_bot": round(s_bot, 4), "axis_len": round(float(Lx[-1]), 4),
                           "offset_mm": round(cf["offset_m"] * 1000, 2), "gap_top_mm": cf["gap_top_mm"],
                           "gap_bottom_mm": cf["gap_bottom_mm"]}
    from mathutils.bvhtree import BVHTree
    body_bvh = BVHTree.FromPolygons([tuple(p) for p in co], [tuple(t_) for t_ in tris])
    t = time.perf_counter()
    C = build_cloth(D, M, BM, body_bvh, O)
    n0 = len(C["X"])
    # the buttons: each button point on the left front to the right front's
    fr = D.geom("front")
    pairs = []
    for xy in np.asarray(fr.notches["buttons"], float):
        il = C["info"]["front"]["base"] + int(np.argmin(np.linalg.norm(C["info"]["front"]["V"] - xy, axis=1)))
        ir = C["info"]["front_r"]["base"] + int(np.argmin(np.linalg.norm(C["info"]["front_r"]["V"] - xy, axis=1)))
        pairs.append((il, ir))
    C["buttons"] = pairs
    # holds: the neckline inside the band (arc length from the CB, the stand past the CF), the
    # sleeve end inside the cuff's top
    a_x, P_x, s_x = band_ring(nf, bh["up_m"], bh["in_m"], math.pi / 2, -math.pi / 2 - 0.6)
    s_cf = float(s_r[-1])
    hold = np.zeros(n0, bool)
    hold_pos = np.full((n0, 3), np.nan)
    Gc = D.frame["Gc"]
    for suf, sgn in (("", 1.0), ("_r", -1.0)):
        pts, seg = [], [0.0]
        for pn, e, rev in (("yoke" + suf, "neck", False), ("front" + suf, "neck", True)):
            Pp = C["pts"][(pn, e)]
            js = list(range(len(Pp)))[::-1] if rev else list(range(len(Pp)))
            for k, j in enumerate(js):
                if pts:
                    # pattern arc length along the chain (none across the shoulder seam's two ends)
                    seg.append(float(np.linalg.norm(Pp[j] - Pp[js[k - 1]])) if k > 0 else 0.0)
                pts.append((C["gid"][(pn, e, j)], Pp[j], pn.startswith("front")))
        sp_ = np.cumsum(seg)
        fx = np.array([p[1][0] for p in pts if p[2]])
        fs = np.array([sv for p, sv in zip(pts, sp_) if p[2]])
        L_cf = float(np.interp(Gc, fx, fs))
        lap = bh["lap_m"] if suf == "" else -0.4 * bh["lap_m"]
        for (g, xy, _f), sv in zip(pts, sp_):
            if sv <= L_cf:
                sr = sv / max(L_cf, 1e-9) * s_cf
                past = 0.0
            else:
                past = (sv - L_cf) / 100.0
                sr = s_cf + past
            p = np.array([np.interp(sr, s_x, P_x[:, k]) for k in range(3)])
            if past > 0:
                c_ = np.array([0.0, nf.cyz(p[2]), p[2]])
                rad = (p - c_) * np.array([1, 1, 0])
                p = p + rad / max(np.linalg.norm(rad), 1e-9) * lap * min(1.0, past / 0.005)
            if sgn < 0:
                p = p * np.array([-1.0, 1, 1])
            hold[g] = True
            hold_pos[g] = p
    nh_neck = int(hold.sum())
    S_ = D.frame["sleeve"]
    pitch_end = D.opts["sleeve"]["pitch_cm"]
    ch = O["cuff_hold"]
    for nm in ("sleeve", "sleeve_r"):
        Pp = C["pts"][(nm, "cuff")]
        for j, (uu, vv) in enumerate(Pp):
            g = C["gid"][(nm, "cuff", j)]
            th = 2 * math.pi * (uu - pitch_end - S_["uc"]) / S_["Wc"]
            p = cf["point"](np.array([th]), s_top + ch["down_m"], -ch["in_m"])[0]
            if nm.endswith("_r"):
                p = p * np.array([-1.0, 1, 1])
            hold[g] = True
            hold_pos[g] = p
    C["hold_pos"] = hold_pos
    stats["holds"] = {"neck": nh_neck, "cuff": int(hold.sum()) - nh_neck}
    Ef = mesh_edges(C["T"])
    lf = np.linalg.norm(C["R"][Ef[:, 0]] - C["R"][Ef[:, 1]], axis=1)
    lp = np.linalg.norm(C["X"][Ef[:, 0]] - C["X"][Ef[:, 1]], axis=1)
    stats["placed_strain_vs_flat"] = round(float(np.abs(lp / lf - 1).mean()), 4)
    hm = np.nonzero(hold)[0]
    stats["hold_placed_dist_mm"] = {"median": round(float(np.median(np.linalg.norm(C["X"][hm] - hold_pos[hm], axis=1))) * 1000, 1),
                                    "max": round(float(np.max(np.linalg.norm(C["X"][hm] - hold_pos[hm], axis=1))) * 1000, 1)}
    print(f"[spike] shirt cloth verts {n0} tris {len(C['T'])} sew edges {len(C['sew'])} holds {stats['holds']}",
          flush=True)
    short = lf < 1e-5
    if short.any():
        bad = np.unique(C["pid"][Ef[short].ravel()])
        print(f"[spike] zero-length flat edges: {int(short.sum())} in {[C['names'][b] for b in bad]}", flush=True)
        raise SystemExit("degenerate flat mesh")
    if np.isnan(hold_pos[hold]).any():
        raise SystemExit("NaN hold targets")
    used = np.zeros(n0, bool)
    used[C["T"].ravel()] = True
    if not used.all():
        bad = np.unique(C["pid"][~used])
        print(f"[spike] verts in no triangle: {int((~used).sum())} in {[C['names'][b] for b in bad]}", flush=True)
        raise SystemExit("isolated vertices")
    tick("mesh_place", t)
    stats["draft"] = {"frame": {k: (round(v, 3) if isinstance(v, float) else v) for k, v in D.frame.items()
                                if k != "sleeve"},
                      "sleeve": {k: round(v, 2) for k, v in D.frame["sleeve"].items()},
                      "seam_lengths_cm": D.seam_lengths()}
    for k in ("jacket", "waistcoat", "buttons", "shirt"):
        if k in base:
            base[k].hide_render = True
    if A.place_only:
        ob = mesh_object("spike_shirt_placed", C["X"], C["T"])
        render_views(A.out_dir, "placed", [body.name, ob.name] + [base[k].name for k in ("tie", "trousers") if k in base],
                     list(VIEWS))
        with open(os.path.join(A.out_dir, "spike_stats.json"), "w") as f:
            json.dump(stats, f, indent=1, default=float)
        return
    # the field: the body only (the shirt is the first layer)
    t = time.perf_counter()
    lo = C["X"].min(0) - 0.08
    hi = C["X"].max(0) + 0.08
    bgrid, nex = body_sdf(co, tris, lo, hi, XPBD["sdf_h"], shells=())
    T["sdf"] = round(time.perf_counter() - t, 2)
    torso = np.isin(np.asarray(C["names"])[C["pid"]], ["yoke", "yoke_r", "back", "back_r", "front", "front_r"])
    fronts = np.isin(np.asarray(C["names"])[C["pid"]], ["front", "front_r"])
    tk = O["tuck"]
    bt = L["band_top_z"]
    post = [(tuck_hook(bgrid, bt - tk["full_below_m"], bt + tk["free_above_m"], tk["dmax_m"]), torso)]
    hf = None
    if "tie" in base:
        hf = tie_heightfield(base["tie"])
        post.append((tie_hook(hf, O["tie_clear_m"]), fronts))
    ep = O.get("elbow_press")
    if ep:
        sleeves = np.isin(np.asarray(C["names"])[C["pid"]], ["sleeve", "sleeve_r"])
        elbows = [J[f"lowerarm_{s_}"][0] for s_ in ("l", "r")]
        post.append((zone_hook(bgrid, elbows, ep["r_full_m"], ep["r_free_m"], ep["dmax_m"]), sleeves))
    C["post"] = post
    if A.from_run:
        d = np.load(os.path.join(A.from_run, "drape2.npz"))
        X1, Xw, Tw, wm, X2 = (d[k] for k in ("X1", "Xw", "Tw", "wm", "X2"))
        stats["from_run"] = A.from_run
    else:
        X1, (Xw, Tw, wm, cnt), X2 = drape_xpbd(C, O, bgrid, np.zeros(n0), stats, hold)
        T["stage1_sim"], T["stage2_sim"] = stats["xpbd_stage1_s"], stats["xpbd_stage2_s"]
        print(f"[spike] xpbd: stage 1 {T['stage1_sim']} s, stage 2 {T['stage2_sim']} s", flush=True)
    sw = np.array(C["sew"])
    gap1 = np.linalg.norm(X1[sw[:, 0]] - X1[sw[:, 1]], axis=1)
    stats["stage1_gap_mm"] = {"mean": round(float(gap1.mean() * 1000), 2), "p95": round(float(np.percentile(gap1, 95) * 1000), 2),
                              "max": round(float(gap1.max() * 1000), 2)}
    np.savez_compressed(os.path.join(A.out_dir, "drape2.npz"), X0=C["X"], X1=X1, Xw=Xw, Tw=Tw, wm=wm, X2=X2,
                        sew=sw, T=C["T"], R=C["R"], pid=C["pid"], names=np.array(C["names"]))
    import hashlib
    stats["hash"] = {k: hashlib.sha256(np.ascontiguousarray(v).tobytes()).hexdigest()[:8]
                     for k, v in (("X1", X1), ("Xw", Xw), ("X2", X2))}
    t = time.perf_counter()
    real = Layers(co, tris, [])
    stats["inside_before_push"] = inside_count(X2, real)
    X3, moved = push_out(X2, Tw, real, O["push"]["clear_m"], O["push"]["smooth_iters"])
    # the tuck and the tie once more on the kept shape
    free_w = np.ones(len(X3), bool)
    for fac, m in post:
        fac(np.unique(wm[np.nonzero(m)[0]]))(X3, free_w)
    stats["pushed_verts"] = moved
    stats["inside_after_push"] = inside_count(X3, real)
    tick("push_out", t)
    sedges = seam_edges(C, wm, Tw)
    stats["crease_final"] = crease_stats(X3, Tw, sedges, O["crease_deg"])
    stats["crease_seam_hinges"] = int(sum(v.get("hinge_over_thr", 0) for k, v in stats["crease_final"].items()
                                          if not k.startswith("_")))
    okE = wm[Ef[:, 0]] != wm[Ef[:, 1]]
    l3 = np.linalg.norm(X3[wm[Ef[:, 0]]] - X3[wm[Ef[:, 1]]], axis=1)
    s3 = l3[okE] / np.maximum(lf[okE], 1e-9) - 1
    stats["strain_vs_flat"] = {"mean_abs": round(float(np.abs(s3).mean()), 4),
                               "p99_abs": round(float(np.percentile(np.abs(s3), 99)), 4)}
    # the layers over it: the tucked shirt inside the made trousers, the front behind the tie
    tw_ = np.unique(wm[np.nonzero(torso)[0]])
    if A.trousers_from:
        dk = np.load(os.path.join(A.trousers_from, "kept.npz"))
        tb = BVHTree.FromPolygons([tuple(p) for p in dk["X3"]], [tuple(int(i) for i in f) for f in dk["Tw"]])
        dd = []
        for i in tw_:
            if X3[i, 2] > bt - 0.003:
                continue
            loc, nor, _, dist = tb.find_nearest(Vector(X3[i]))
            if loc is None or dist > 0.03:
                continue
            dd.append(float(np.dot(X3[i] - np.array(loc), np.array(nor))))
        dd = np.array(dd) * 1000
        # the trousers' cloth is 1.2 mm (its drape is the outside): the shirt clears its inside
        stats["tuck_vs_trousers_mm"] = {"n": int(len(dd)), "max": round(float(dd.max()), 2),
                                        "through_inside": int((dd > -1.2).sum()), "outside_mid": int((dd > 0).sum())}
    if hf is not None:
        P = X3[np.unique(wm[np.nonzero(fronts)[0]])]
        i = np.round((P[:, 0] - hf["x0"]) / hf["h"]).astype(int)
        j = np.round((P[:, 2] - hf["z0"]) / hf["h"]).astype(int)
        ok = (i >= 0) & (j >= 0) & (i < hf["Y"].shape[0]) & (j < hf["Y"].shape[1])
        yb = np.full(len(P), np.nan)
        yb[ok] = hf["Y"][i[ok], j[ok]]
        stats["front_through_tie"] = int(np.sum(~np.isnan(yb) & (P[:, 1] < yb)))
    np.savez_compressed(os.path.join(A.out_dir, "kept.npz"), X3=X3, Tw=Tw)
    # --- the made shirt
    from character import suit_made_tex
    sbld_G = sbld.Garment("spike_shirt_tmp", arm, sbody)
    info = suit_neck.build_shirt_collar(nf, sbld_G, Ccol, {"neck_01", "head", "spine_03", "clavicle_l",
                                                           "clavicle_r"}, 3)
    g = info["grid"]
    Xg, UVg = sd_.collar_from_grid([[v.co for v in row] for row in g.rows], g.uvs, drop_last=1)
    clo = info["closure"]
    Xc, UVc = sd_.collar_from_grid([[v.co for v in row] for row in clo.rows], clo.uvs, drop_last=0)
    sbld_G.bm.free()

    def neck_axis(c_):
        return np.stack([np.zeros(len(c_)), nf.cyz(c_[:, 2]), c_[:, 2]], 1)
    collar = {"X": Xg, "UV": UVg, "closure": (Xc, UVc), "axis": neck_axis}
    obs, uv_obs, uv_marks, uv_tags = [], {}, {}, {}
    t = time.perf_counter()
    dst = {}
    det = sd_.build(C, D, wm, X3, Tw, collar, [(cf, False), (cf, True)],
                    O["details"] if isinstance(O["details"], dict) else None, dst)
    for k, v in det.items():
        if k.startswith("_") or v is None:
            continue
        ob_ = mesh_object(f"spike_shirt_{k}", v[0], v[1])
        set_parts(ob_, v[2])
        if v[3] is not None:
            suit_made_tex.set_uv(ob_, v[3], v[4])
            uv_obs[k] = ob_
        if v[5] is not None:
            suit_made_tex.crisp_normals(ob_, v[5])
        obs.append(ob_)
    uv_marks.update(det["_uv"]["marks"])
    uv_tags.update(det["_uv"]["tags"])
    stats["detail"] = dst
    if det.get("buttons") is not None:
        b0 = det["_front_button_v0"]
        stats["detail"]["clearance_mm"] = detail_clearance(X3, Tw, {"buttons": (det["buttons"][0][b0:],)})
    parts_ = {k: v for k, v in det.items() if v is not None and not k.startswith("_")}
    np.savez_compressed(os.path.join(A.out_dir, "made.npz"),
                        **{f"{k}_V": v[0] for k, v in parts_.items()},
                        **{f"{k}_F": np.array([list(f) + [-1] * (4 - len(f)) for f in v[1]]) for k, v in parts_.items()},
                        **{f"{k}_part": v[2] for k, v in parts_.items()})
    tick("details", t)
    # the collar's seat: T22's neck against the frame's body, the collar's inside against the hero neck
    try:
        Vc = det["collar"][0]
        kind = np.zeros(len(Vc), bool)
        for f_, p_ in zip(det["collar"][1], det["collar"][2]):
            if p_ == 1:
                kind[list(f_)] = True
        stats["neck_check"] = neck_check(A.base_blend, nf, Vc[kind][::3])
    except Exception as ex:      # informative only
        stats["neck_check"] = {"error": repr(ex)}
    # the cuff past the jacket's sleeve
    if A.jacket_ref:
        pj, u_f, _ = jacket_cuff_edge(A.jacket_ref, J)
        Vk = det["cuffs"][0]
        Vk = Vk[Vk[:, 0] > 0]
        stats["cuff_show_cm"] = round((float(np.median(np.sort(Vk @ u_f)[-60:])) - pj) * 100, 2)
    stats["made_tris"] = sum(len(p.vertices) - 2 for ob_ in obs for p in ob_.data.polygons)
    stats["kept_tris"] = int(len(Tw))
    stats["timings_s"] = T
    stats["options"] = {k: v for k, v in O.items() if not k.startswith("_")}
    with open(os.path.join(A.out_dir, "spike_stats.json"), "w") as f:
        json.dump(stats, f, indent=1, default=float)
    print(json.dumps({k: stats.get(k) for k in ("stage1_gap_mm", "inside_after_push", "strain_vs_flat",
                                                "tuck_vs_trousers_mm", "front_through_tie", "cuff_show_cm",
                                                "neck_check", "made_tris")}, indent=1, default=float), flush=True)
    for nm_, v in stats["crease_final"].items():
        print(f"[spike] crease {nm_}: {v}", flush=True)
    made_mats = None
    if O.get("textures") and uv_obs:
        t = time.perf_counter()
        to = dict(O["textures"]) if isinstance(O["textures"], dict) else {}
        made_mats, stats["textures"] = suit_made_tex.bake(uv_obs, uv_marks, uv_tags, suit.DEFAULTS, to)
        tick("textures", t)
    lods = {}
    if not A.no_render:
        t = time.perf_counter()
        bpy.context.scene.frame_set(1)
        under = [body.name] + [base[k].name for k in ("tie", "trousers", "shoes") if k in base]
        under += [o_.name for o_ in made_tr if o_.name not in {b_.name for b_ in base.values()}]
        mine = [o_.name for o_ in obs]
        if not A.no_clay:
            if "shirt" in base:
                render_views(A.out_dir, "lofted", under + [base["shirt"].name], list(VIEWS))
            render_views(A.out_dir, "pattern", under + mine, list(VIEWS))
            closes = dict(SHIRT_CLOSE)
            cc = cf["point"](np.array([0.0]), 0.5 * (s_top + s_bot))[0]
            closes["close_cuff"] = (60.0, tuple(cc), 0.20, 0.0)
            closes["close_cuff_b"] = (150.0, tuple(cc), 0.20, 0.0)
            for v, (az, tgt, sc_, *dz) in closes.items():
                render_views(A.out_dir, "pattern", under + mine, [v], target=tgt, scale=sc_, az_override=az,
                             cam_dz=dz[0] if dz else 0.0)
        if O.get("lods"):
            lods = make_lods(obs, O["lods"], prefix="spike_shirt")
            stats["lod_tris"] = {k: v[1] for k, v in lods.items()}
            if not A.no_clay:
                for k, (ob_, _) in lods.items():
                    render_views(A.out_dir, f"lod{k}", under + [ob_.name], ["front", "three_quarter"])
        tick("render", t)
    if made_mats is not None:
        lod_obs = [ob_ for k, (ob_, _) in sorted(lods.items())]
        suit_made_tex.assign(obs + lod_obs, made_mats)
        side_ = made_mats[0]["suit_atlas_side_m"]
        stats["textures"]["uv_lod"] = {ob_.name: suit_made_tex.uv_stats(ob_, side_) for ob_ in lod_obs}
    restore_made()    # the made under-garments' own slots back after the clay
    stage_rig(bpy.context.scene)
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


# --- T13 item 6: the made suit rigged (T13b: weights from the body, Dem Bones; T13c: the shipped
# weight pipeline, every layer simulated per pose, the skirt bones' follow gains and pose-space
# correctives fitted over a ~35-pose set) -----------------------------------------------------------

POSED = {
    # the simulated pose set: the deform_poses library, a fist, and ramps (posed_specs)
    "poses": ["rest", "relaxed", "arm_raise", "knee_up", "walk", "high_ready", "twist", "fist",
              "abd30", "abd60", "abd90", "abd120", "flex30", "flex60", "flex90", "flex120",
              "elbow45", "elbow90", "elbow120",
              "thigh30", "thigh60", "thigh90", "thighb30", "thighb60", "thighb90", "thighext",
              "turn20", "turn40", "turnr20", "turnr40", "bend20", "bend40", "back15", "tilt20", "tiltr20"],
    "frames": 40,                # settle frames per pose for the jacket (from the skinned rest drape)
    "frames_under": 30,          # the shirt and the waistcoat
    "rules": True,               # the lookdev rig's helper rules (twist, deltoid, hip, skirt) when posing
    "push": {"clear_m": 0.0015, "smooth_iters": 3},
    "push_under": {"clear_m": 0.001, "smooth_iters": 2},
    "self_contact": True,
    # the weight smoothing per layer (deform_rig.DEFAULTS["garments"])
    "sigma": {"jacket": 0.025, "shirt": 0.015, "waistcoat": 0.015, "trousers": 0.02},
    # holds per pose: the shirt's neckline inside the collar band and its sleeve ends inside the
    # cuffs (both modelled, skinned), the tuck below the trousers' band (pulled to its skinned
    # place a share per substep); the waistcoat's shoulder seams
    "hold": {"shirt_k": 40.0, "tuck_pull": 0.2, "waistcoat_k": 20.0, "jacket_neck_k": None},
    # ridge of the corrective fit: 1e-4 left the 34 cones over 35 poses overfitted (leave-one-out
    # p90 118 mm on the jacket, 798 mm for a cone only one pose drives); 0.03 keeps the training fit
    # under 14 mm and brings the leave-one-out p90 to 24 mm (scan over 1e-4..0.3, c1)
    "lam": 0.03,
    "cone_masks": False,         # the spatial masks cost the fit 7-10 mm (high ready 20 mm) for little
    # the layer order at runtime: each layer's fit misses by several mm, more than the gaps between
    # layers, so the under-layers' covered vertices (hidden under the next layer out at rest) sink
    # along their normal, feathered to nothing over margin_m from the visible ones (deform_rig.tuck)
    # T13d: off. The cull removes what the jacket hides in every pose; the sink pushed the shirt in the
    # closed armpit out through the jacket (a cover found along -n is the other side of the arm)
    "tuck": {"on": False, "reach_m": 0.05, "margin_m": 0.03, "depth_m": {"shirt": 0.012, "waistcoat": 0.007}},
    # T13d: the correctives refitted to keep the layer order and the jacket out of the body (constrain_fit)
    "constrain": {"on": True, "rounds": 8, "trigger_m": 0.0005, "margin_m": 0.0012, "body_margin_m": 0.0015,
                  "body_depth_max_m": 0.02, "weight": 100.0, "sink_r_m": 0.015, "sink_max_m": 0.012},
    "gain_fit": True,            # refit the skirt bones' follow gains to the simulated skirt
    "dem_bones_diag": True,      # T13b's eight free jacket bones: refit and leave-one-out on this set
    "jacket_bones": 8, "fit_iters": 4, "waist_z": 1.03, "drive_lam": 0.1,
    "render_res": 420,
    "render_samples": 256,
    "wrinkle": True,             # item 7: per-pose wrinkle maps (suit_wrinkle) from the sim vs the runtime
    "wrinkle_px": {"t13_wool": 1024, "default": 512},
    "wrinkle_lam": 0.02,
    "lbs_renders": ["relaxed", "arm_raise", "knee_up", "walk", "fist"],
    "hinge_deg": 150.0,
    # T13d: rigid cuffs and collar (drape vertices within r of the made cuff / collar, and the held
    # sleeve ends and neckline, pinned on one weight row each, feathered over margin_m on the drape);
    # the jacket's neckline on the collar's row
    "rigid": {"on": True, "cuff_r_m": 0.012, "collar_r_m": 0.012, "margin_m": 0.03, "jneck": True,
              "jneck_margin_m": 0.04, "part_r_m": 0.002, "button_r_m": 0.012},
    "anchors": {"on": True, "reach_m": 0.04, "gap_max_m": 0.003, "lat_m": 0.02},
    # the modelled four-in-hand (suit_tie; opts override suit_tie.DEFAULTS)
    "tie": {"on": True, "top_above_band_m": 0.002, "tip_above_band_m": 0.004, "blend_m": 0.08, "opts": {}},
    # gap: the rest gap itself (to 12 mm): the made fronts are shells with their own thickness, and a
    # posed gap under the rest one let the under-front through the over-front (i2 walk: a sawtooth)
    "overlap": {"on": True, "reach_m": 0.04, "gap_max_m": 0.012},
    # the fold limit per interior edge (suit_xpbd.Solver.set_fold): T13c's armpit seams folded flat
    "fold_deg": 140.0,
    "fold_fix_rounds": 3,
    # the under-layers on the jacket's runtime where they stay under it in every pose (bind_under). Off:
    # on i4 it doubled the layer crossings (its targets follow the jacket's fit error, 21-29 mm off the
    # sim, and cross their unbound neighbours); constrain_fit does the job
    "bind_under": {"on": False, "reach_m": 0.03, "lat_m": 0.015, "gap_min_m": 0.002, "gap_max_m": 0.025,
                   "margin_m": 0.015},
    # hidden-face culling (suit_cull): ray cone tilts (deg) and azimuths, the margin the visible set
    # grows by on the mesh, the cuff's (the 1.5 cm past the sleeve plus the turn), the jacket's inside
    # (vertices more than inner_off_m inside its drape: lining, facings, turn-ups)
    "cull": {"on": True, "view_zmin": -0.5, "tilts_narrow": [0.0, 35.0, 60.0], "tilts": [0.0, 45.0, 75.0], "k": 8, "eps_m": 0.0015, "reach_m": 0.6, "margin_m": 0.025,
             "cuff_margin_m": 0.012, "lining_m": 0.0025, "inner_off_m": 0.0015, "lods": {"1": 0.4, "2": 0.15}},
    # close-ups per pose: name -> (bone whose posed head is the target, offset (m), azimuth, scale)
    "close": {"cuff_l": ["hand_l", [0, 0, 0.03], 60.0, 0.30], "cuff_r": ["hand_r", [0, 0, 0.03], -60.0, 0.30],
              "uarm_l": ["lowerarm_l", [0, 0, 0], 150.0, 0.45], "front": ["pelvis", [0, -0.1, 0.12], 0.0, 0.45],
              "chest": ["spine_03", [0, -0.1, 0.0], 15.0, 0.45]},
}


from character import deform_poses as dp  # noqa: E402


def posed_specs():
    """name -> deform_poses spec. Ramps: the arms abducted / flexed 30..120 deg from hanging (the
    left one way, the right the other, so both sides are sampled in each), the elbows, the
    thighs (one flexed, the other abducted), the spine turned, bent, extended and tilted; the
    arms down (ARMS_DOWN) where they are not the subject."""
    out = {}
    AD = dp.sym({**dp.ARMS_DOWN, **dp.RELAXED_HAND})

    def aim_abd(a):
        r = math.radians(a)
        return [math.sin(r), 0.0, -math.cos(r)]

    def aim_flex(a):
        r = math.radians(a)
        return [0.12, -math.sin(r), -math.cos(r)]
    for a in (30, 60, 90, 120):
        cl = [["abduct", {30: 0, 60: 4, 90: 10, 120: 18}[a]]]
        out[f"abd{a}"] = {"bones": {**dp.sym(dp.RELAXED_HAND), "clavicle_l": cl, "clavicle_r": cl,
                                    "upperarm_l": [["aim", aim_abd(a)]], "upperarm_r": [["aim", aim_flex(a)]]}}
        out[f"flex{a}"] = {"bones": {**dp.sym(dp.RELAXED_HAND), "clavicle_l": cl, "clavicle_r": cl,
                                     "upperarm_l": [["aim", aim_flex(a)]], "upperarm_r": [["aim", aim_abd(a)]]}}
    for a in (45, 90, 120):
        b = dict(AD)
        b["upperarm_l"] = b["upperarm_r"] = [["abduct", -36], ["flex", 12], ["twist", 5]]
        b["lowerarm_l"] = b["lowerarm_r"] = [["flex", a - 22]]
        out[f"elbow{a}"] = {"bones": b}
    for a, ab in ((30, 10), (60, 20), (90, 30)):
        for tag, s1, s2 in (("thigh", "l", "r"), ("thighb", "r", "l")):
            b = dict(AD)
            b[f"thigh_{s1}"] = [["flex", a]]
            b[f"calf_{s1}"] = [["flex", a]]
            b[f"thigh_{s2}"] = [["abduct", ab]]
            out[f"{tag}{a}"] = {"bones": b}
    b = dict(AD)
    b["thigh_l"] = b["thigh_r"] = [["flex", -22]]
    b["calf_l"] = b["calf_r"] = [["flex", 25]]
    out["thighext"] = {"bones": b}
    for tag, op, vals in (("turn", "turn", (20, 40)), ("turnr", "turn", (-20, -40)), ("bend", "flex", (20, 40)),
                          ("back", "flex", (-15,)), ("tilt", "tilt", (20,)), ("tiltr", "tilt", (-20,))):
        for v in vals:
            b = dict(AD)
            for n_, k_ in (("spine_01", 0.3), ("spine_02", 0.35), ("spine_03", 0.35)):
                b[n_] = [[op, v * k_]]
            out[f"{tag}{abs(v)}"] = {"bones": b}
    out["fist"] = {"bones": dp.sym({**dp.ARMS_DOWN, **dp.FIST})}
    return out


def pose_spec(name):
    return posed_specs().get(name, name)


# the suit's corrective cones (deform_runtime 'cone' rules): (name, bone, ref, d0, target spec
# (left names; mirrored for _r), start, mask kind). d0 'dir' is the bone's rest direction; 'fwd' the
# character's front (a turn leaves the spine's direction where it is). A '_h' twin with start 0.5
# makes the response piecewise linear in angle (a knot half way to the target).
SUIT_CONES = [
    ("arm_down", "upperarm", "spine_03", "dir", {"upperarm_l": [["abduct", -36], ["flex", 4]]}, 0.0, "arm"),
    ("arm_abd90", "upperarm", "spine_03", "dir", {"upperarm_l": [["aim", [1.0, 0.0, 0.0]]]}, 0.0, "arm"),
    ("arm_abd90_h", "upperarm", "spine_03", "dir", {"upperarm_l": [["aim", [1.0, 0.0, 0.0]]]}, 0.5, "arm"),
    ("arm_abd135", "upperarm", "spine_03", "dir", {"upperarm_l": [["aim", [0.707, 0.0, 0.707]]]}, 0.0, "arm"),
    ("arm_flex90", "upperarm", "spine_03", "dir", {"upperarm_l": [["aim", [0.12, -1.0, 0.0]]]}, 0.0, "arm"),
    ("arm_flex90_h", "upperarm", "spine_03", "dir", {"upperarm_l": [["aim", [0.12, -1.0, 0.0]]]}, 0.5, "arm"),
    ("arm_flex135", "upperarm", "spine_03", "dir", {"upperarm_l": [["aim", [0.1, -0.707, 0.707]]]}, 0.0, "arm"),
    ("arm_back", "upperarm", "spine_03", "dir", {"upperarm_l": [["aim", [0.2, 0.55, -0.81]]]}, 0.0, "arm"),
    ("elbow90", "lowerarm", "upperarm", "dir", {"lowerarm_l": [["flex", 70]]}, 0.0, "elbow"),
    ("elbow90_h", "lowerarm", "upperarm", "dir", {"lowerarm_l": [["flex", 70]]}, 0.5, "elbow"),
    ("thigh_flex90", "thigh", "pelvis", "dir", {"thigh_l": [["flex", 90]]}, 0.0, "thigh"),
    ("thigh_flex90_h", "thigh", "pelvis", "dir", {"thigh_l": [["flex", 90]]}, 0.5, "thigh"),
    ("thigh_abd40", "thigh", "pelvis", "dir", {"thigh_l": [["abduct", 40]]}, 0.0, "thigh"),
    ("thigh_ext30", "thigh", "pelvis", "dir", {"thigh_l": [["flex", -30]]}, 0.0, "thigh"),
]
SUIT_SPINE_CONES = [
    ("spine_flex40", "dir", {"spine_01": [["flex", 12]], "spine_02": [["flex", 14]], "spine_03": [["flex", 14]]}),
    ("spine_ext20", "dir", {"spine_01": [["flex", -6]], "spine_02": [["flex", -7]], "spine_03": [["flex", -7]]}),
    ("spine_tilt25_l", "dir", {"spine_01": [["tilt", 8]], "spine_02": [["tilt", 8.5]], "spine_03": [["tilt", 8.5]]}),
    ("spine_tilt25_r", "dir", {"spine_01": [["tilt", -8]], "spine_02": [["tilt", -8.5]], "spine_03": [["tilt", -8.5]]}),
    ("spine_turn40_l", "fwd", {"spine_01": [["turn", 12]], "spine_02": [["turn", 14]], "spine_03": [["turn", 14]]}),
    ("spine_turn40_r", "fwd", {"spine_01": [["turn", -12]], "spine_02": [["turn", -14]], "spine_03": [["turn", -14]]}),
]


def suit_cones(arm, rig_):
    """The cone rules (glTF space, deform_runtime) with each one's mask kind and side: targets are
    read off the armature posed to each target spec."""
    from character import deform_runtime as drt
    rt0 = drt.Runtime(arm, [], {})
    B = arm.data.bones

    def bdir(n):
        return (B[n].tail_local - B[n].head_local).normalized()
    out = []
    jobs = []
    for nm, bone, ref, d0k, spec, start, kind in SUIT_CONES:
        for s in ("l", "r"):
            sp_ = dp.side(spec, s) if s == "r" else spec
            jobs.append((f"suit_{nm}_{s}", f"{bone}_{s}", ref if ref in ("spine_03", "pelvis") else f"{ref}_{s}",
                         d0k, sp_, start, kind, s))
    for nm, d0k, spec in SUIT_SPINE_CONES:
        jobs.append((f"suit_{nm}", "spine_03", "pelvis", d0k, spec, 0.0, "spine", ""))
    for name, bone, ref, d0k, spec, start, kind, s in jobs:
        d0 = bdir(bone) if d0k == "dir" else Vector((0.0, -1.0, 0.0))
        dp.apply_pose(arm, {"bones": spec}, rig_)
        q = rt0.R(ref).inverted() @ rt0.R(bone)
        t = q @ d0
        out.append({"name": name, "bone": bone, "ref": ref, "rest_dir": drt.bl_to_gl(d0), "target_dir": drt.bl_to_gl(t),
                    "power": 1.0, "start": start, "_kind": kind, "_side": s,
                    "_deg": round(math.degrees(d0.angle(t)), 1)})
    dp.reset(arm)
    return out


def cone_masks(cones, X0, arm):
    """(n, C) where each shape may act: an arm's on its own side of the body and a few cm over the
    centre line (an arm raised pulls the whole front up), an elbow's within ~30 cm of the joint, a
    thigh's on its side below the waist, the spine's everywhere."""
    from character.deform_rig import smoothstep as ss
    B = arm.data.bones
    hip_z = float(np.mean([B[f"thigh_{s}"].head_local.z for s in ("l", "r")]))
    m = np.zeros((len(X0), len(cones)))
    for j, c in enumerate(cones):
        s = c["_side"]
        sx = (1.0 if B["upperarm_l"].head_local.x > 0 else -1.0) * (1.0 if s == "l" else -1.0)
        x = X0[:, 0] * sx
        if c["_kind"] == "arm":
            m[:, j] = ss(-0.10, 0.04, x)
        elif c["_kind"] == "elbow":
            e = np.array(B[f"lowerarm_{s}"].head_local)
            m[:, j] = 1.0 - ss(0.22, 0.34, np.linalg.norm(X0 - e, axis=1))
        elif c["_kind"] == "thigh":
            m[:, j] = ss(-0.08, 0.03, x) * (1.0 - ss(hip_z + 0.20, hip_z + 0.32, X0[:, 2]))
        else:
            m[:, j] = 1.0
    return m


def bind_fn(X, T):
    """Nearest face and barycentrics on (X, T) for points P (the wrap binding)."""
    from mathutils.bvhtree import BVHTree
    bvh = BVHTree.FromPolygons([tuple(p) for p in X], [tuple(int(i) for i in t) for t in T])

    def f(P):
        fi = np.zeros(len(P), int)
        bc = np.zeros((len(P), 3))
        for k, p in enumerate(P):
            loc, _, fidx, _ = bvh.find_nearest(Vector(p))
            a, b, c = X[T[fidx]]
            v0, v1, v2 = b - a, c - a, np.array(loc) - a
            d00, d01, d11 = v0 @ v0, v0 @ v1, v1 @ v1
            d20, d21 = v2 @ v0, v2 @ v1
            den = max(d00 * d11 - d01 * d01, 1e-18)
            v = (d11 * d20 - d01 * d21) / den
            w = (d00 * d21 - d01 * d20) / den
            u = np.clip(np.array([1 - v - w, v, w]), 0, 1)
            fi[k], bc[k] = fidx, u / u.sum()
        return fi, bc
    return f


def body_weights(body, arm):
    """Dense (n_verts, B) skin weights of the body over the armature's deforming bones it uses."""
    names = [g.name for g in body.vertex_groups]
    bones = [b.name for b in arm.data.bones if b.use_deform]
    used = sorted({names[g.group] for v in body.data.vertices for g in v.groups
                   if names[g.group] in bones and g.weight > 0})
    col = {n: i for i, n in enumerate(used)}
    W = np.zeros((len(body.data.vertices), len(used)))
    for v in body.data.vertices:
        for g in v.groups:
            j = col.get(names[g.group])
            if j is not None:
                W[v.index, j] = g.weight
    s = W.sum(1, keepdims=True)
    return W / np.where(s > 0, s, 1.0), used


def skin_mats(arm, bones):
    """World skinning matrices (pose @ rest^-1) of `bones` as (B, 4, 4)."""
    Mw = arm.matrix_world
    out = []
    for n in bones:
        pb = arm.pose.bones[n]
        out.append(np.array(Mw @ pb.matrix @ arm.data.bones[n].matrix_local.inverted() @ Mw.inverted()))
    return np.array(out)


def local_rot(arm, n):
    """A bone's pose rotation relative to its rest (rotation vector, in its parent's frame)."""
    from character import suit_rig as sr
    return sr.rotvec(np.array(arm.pose.bones[n].matrix_basis.to_3x3()))


def nearest_fn(co, tris):
    from mathutils.bvhtree import BVHTree
    bvh = BVHTree.FromPolygons([tuple(p) for p in co], [tuple(int(i) for i in t) for t in tris])

    def f(p):
        loc, _, fi, _ = bvh.find_nearest(Vector(p))
        ids = tris[fi]
        a, b, c = co[ids]
        v0, v1, v2 = b - a, c - a, np.array(loc) - a
        d00, d01, d11 = v0 @ v0, v0 @ v1, v1 @ v1
        d20, d21 = v2 @ v0, v2 @ v1
        den = max(d00 * d11 - d01 * d01, 1e-18)
        v = (d11 * d20 - d01 * d21) / den
        w = (d00 * d21 - d01 * d20) / den
        return ids, np.clip(np.array([1 - v - w, v, w]), 0, 1)
    return f


def panel_bind_fn(Gx, glob):
    """T13d: the wrap binding by panel. Where two panels of one garment overlap (the fronts below the
    button, a placket) a made vertex 2-3 mm out from its own drape can be nearer the other panel's
    drape (i3: 16 of the jacket's over-front vertices bound to the under-front; when the fronts part
    they tore away from their neighbours, a sawtooth down the edge). A made vertex whose faces are all
    on one panel (the face attribute 'panel', 1-based into the drape's panel names) binds to the drape
    faces touching that panel; a seam vertex and a part without the attribute bind as before (glob)."""
    from mathutils.bvhtree import BVHTree
    X, T = Gx["X0"], Gx["Tw"]
    names = list(Gx.get("pnames") or [])
    trees = {}

    def tree(pn):
        if pn not in trees:
            fs = np.nonzero(np.array([any(pn in Gx["panels"][v] for v in t) for t in T]))[0]
            trees[pn] = (BVHTree.FromPolygons([tuple(map(float, p)) for p in X],
                                              [tuple(int(i) for i in T[f]) for f in fs]), fs) if len(fs) else None
        return trees[pn]

    def f(V, ob):
        fi, bc = glob(V)
        pa = ob.data.attributes.get("panel") if ob is not None else None
        if pa is None or pa.domain != "FACE" or not names:
            return fi, bc, {"panel_bound": 0}
        pv = np.empty(len(pa.data), np.int64)
        pa.data.foreach_get("value", pv)
        vp = [set() for _ in range(len(V))]
        for pl in ob.data.polygons:
            for v in pl.vertices:
                vp[v].add(int(pv[pl.index]))
        # the attribute must index this drape's panels: most single-panel vertices already lie nearest
        # a face touching their panel (i4: the pockets' and the rever's own panel numbers do not, and
        # rebinding them by it threw them across the coat)
        single = [k for k, ps in enumerate(vp) if len(ps) == 1 and 0 <= next(iter(ps)) - 1 < len(names)]
        if not single:
            return fi, bc, {"panel_bound": 0}

        def touches(k, pn):
            return any(pn in Gx["panels"][v] for v in T[fi[k]])
        agree = np.mean([touches(k, names[next(iter(vp[k])) - 1]) for k in single])
        if agree < 0.9:
            return fi, bc, {"panel_bound": 0, "agree": round(float(agree), 3)}
        moved = 0
        for k in single:
            pn = names[next(iter(vp[k])) - 1]
            if touches(k, pn):
                continue
            tr = tree(pn)
            if tr is None:
                continue
            d_glob = float(np.linalg.norm(np.einsum("k,ki->i", bc[k], X[T[fi[k]]]) - V[k]))
            loc, _, li, d_pan = tr[0].find_nearest(Vector(V[k]))
            if loc is None or d_pan > min(0.012, d_glob + 0.006):
                continue
            fidx = int(tr[1][li])
            a, b, c = X[T[fidx]]
            v0, v1, v2 = b - a, c - a, np.array(loc) - a
            d00, d01, d11 = v0 @ v0, v0 @ v1, v1 @ v1
            d20, d21 = v2 @ v0, v2 @ v1
            den = max(d00 * d11 - d01 * d01, 1e-18)
            v_ = (d11 * d20 - d01 * d21) / den
            w_ = (d00 * d21 - d01 * d20) / den
            u = np.clip(np.array([1 - v_ - w_, v_, w_]), 0, 1)
            fi[k], bc[k] = fidx, u / u.sum()
            moved += 1
        return fi, bc, {"panel_bound": moved, "agree": round(float(agree), 3)}
    return f


def tris_of(F):
    """Triangles of polygons (fan)."""
    return np.array([(f[0], f[i], f[i + 1]) for f in F for i in range(1, len(f) - 1)], int)


def garment_drape(run, key, X0=None):
    """A layer's drape for the per-pose solver: rest positions (kept X3), welded triangles, rest
    lengths from the flat pattern, mass, bending, the panel of each welded vertex, the solver opts."""
    from character import suit_xpbd as xp
    st = json.load(open(os.path.join(run, "spike_stats.json")))
    d = np.load(os.path.join(run, "drape2.npz"))
    k = np.load(os.path.join(run, "kept.npz"))
    X3, Tw, wm = (k["X3"] if X0 is None else X0), k["Tw"], d["wm"]
    T0_, R0, pid, pnames = d["T"], d["R"], d["pid"], [str(n) for n in d["names"]]
    P_ = dict(XPBD)
    P_.update(st["xpbd"]["opts"])
    nw, n0 = len(X3), len(R0)
    pk = np.asarray(pnames)[pid]
    front = np.isin(pk, ["front", "front_r"])
    sleeve = np.isin(pk, ["top_sleeve", "top_sleeve_r", "under_sleeve", "under_sleeve_r", "sleeve", "sleeve_r"])
    rho = np.where(front, P_.get("density_canvas", P_["density"]), P_["density"])
    mass = xp.mass_from_flat(T0_, R0, n0, rho)
    kb = np.where(front, P_.get("kb_canvas", P_["kb"]), P_["kb"])
    kb = np.where(sleeve, np.maximum(kb, P_.get("kb_sleeve", P_["kb"])), kb)
    E0 = xp.edges_of(T0_)
    L0 = np.linalg.norm(R0[E0[:, 0]] - R0[E0[:, 1]], axis=1)
    Lw = {}
    for (a, b), l in zip(E0, L0):
        e = (int(min(wm[a], wm[b])), int(max(wm[a], wm[b])))
        if e[0] != e[1]:
            Lw.setdefault(e, []).append(l)
    Lw = {e: float(np.mean(v)) for e, v in Lw.items()}
    for a, b in xp.edges_of(Tw):
        Lw.setdefault((int(a), int(b)), float(np.linalg.norm(X3[a] - X3[b])))
    mw = np.zeros(nw)
    np.add.at(mw, wm, mass)
    kbw = np.zeros(nw)
    np.maximum.at(kbw, wm, kb)
    kind_w = np.full(nw, "", dtype=object)
    kind_w[wm] = pk
    panels = [set() for _ in range(nw)]
    for i, p in zip(wm, pk):
        panels[i].add(str(p))
    return {"key": key, "run": run, "X0": X3, "Tw": Tw, "wm": wm, "Lw": Lw, "mw": mw, "kbw": kbw, "P": P_,
            "kind": kind_w, "panels": panels, "st": st, "pnames": pnames}


def seam_report(G, Y, thr):
    """Seam hinges over thr deg at Y: count, and per panel pair the count and z range."""
    from character import suit_xpbd as xp
    Ew = xp.edges_of(G["Tw"])
    seam_v = np.array([len(p) > 1 for p in G["panels"]])
    sm = seam_v[Ew[:, 0]] & seam_v[Ew[:, 1]]
    Es = Ew[sm]
    dd_ = dihedrals(Y, G["Tw"], [(int(min(a, b)), int(max(a, b))) for a, b in Es])
    dih = np.array([dd_.get((int(min(a, b)), int(max(a, b))), 0.0) for a, b in Es])
    out = {"over_20": int((dih > 20).sum()), "p99_deg": round(float(np.percentile(dih, 99)), 1) if len(dih) else 0.0,
           "max_deg": round(float(dih.max()), 1) if len(dih) else 0.0, "folds": {}}
    for (a, b), v in zip(Es, dih):
        if v <= thr:
            continue
        pp = sorted(G["panels"][a] & G["panels"][b]) or sorted(G["panels"][a] | G["panels"][b])
        lab = "/".join(pp)
        r = out["folds"].setdefault(lab, {"n": 0, "max_deg": 0.0, "z": [9.0, -9.0], "x": [9.0, -9.0]})
        r["n"] += 1
        r["max_deg"] = round(max(r["max_deg"], float(v)), 1)
        p = 0.5 * (Y[a] + Y[b])
        r["z"] = [round(min(r["z"][0], float(p[2])), 3), round(max(r["z"][1], float(p[2])), 3)]
        r["x"] = [round(min(r["x"][0], float(p[0])), 3), round(max(r["x"][1], float(p[0])), 3)]
    return out, dih


def pose_solve(G, Y0, sdf, frames, holds=(), pull=None, pairs=(), self_contact=True, pinned=None, hooks=(),
               fold_deg=None):
    """The layer's drape from its skinned rest state Y0 in the posed field: rest lengths from the
    flat pattern, holds (idx, pos, k) as soft attachments (the strongest k wins), pull (idx,
    pos, share) a share of the way per substep; pinned vertices stay at Y0 (the rigid cuff and
    collar zones); hooks fn(X, free) run after the collisions (the layer anchors, the overlap)."""
    from character import suit_xpbd as xp
    P_ = G["P"]
    o = {kk: P_[kk] for kk in ("k_stretch", "k_comp", "damping", "friction", "thickness", "stretch_iters")}
    S = xp.Solver(G["X0"], G["Tw"], G["Lw"], G["mw"], G["kbw"], o)
    S.X = Y0.copy()
    S.sdf = sdf
    if self_contact and P_.get("self_r", 0) > 0:
        S.self_ref, S.self_r, S.self_excl = G["X0"], P_["self_r"], P_["self_excl"]
    if pairs:
        S.set_sew([p for p, _ in pairs], [g for _, g in pairs])
        S.layer_force = [(np.array([p[0] for p, _ in pairs]), np.array([p[1] for p, _ in pairs]),
                          float(np.mean([g for _, g in pairs])))]
    if holds:
        idx = np.concatenate([h[0] for h in holds])
        pos = np.concatenate([h[1] for h in holds])
        S.hold_idx, S.hold_pos, S.hold_k = idx, pos, max(h[2] for h in holds)
    if pinned is not None:
        S.pinned = np.asarray(pinned, bool).copy()
    if fold_deg:
        S.set_fold(fold_deg)
    if pull is not None:
        pi_, pp_, sh_ = pull

        def fac(X, free, pi_=pi_, pp_=pp_, sh_=sh_):
            X[pi_] += sh_ * (pp_ - X[pi_]) * free[pi_][:, None]
        S.post = [fac]
    S.post = list(S.post) + list(hooks)
    S.run(frames, P_["fps"], P_["substeps"], g_of=lambda f: 9.81, ksew_of=lambda f: 5000.0)
    if fold_deg:
        _FOLD[id(G)] = S
    return S.X.copy()


_FOLD = {}          # the last solver per garment (its stencils and colours, for fold_fix)


def fold_fix(G, X, free, real, pu, hooks, rounds):
    """T13d: the fold limit after the final push-out: the push-out and the layer hooks act after the
    solver's last substep and can fold an armpit edge back over (i2: 175-179 deg). Rounds of the
    limiter's projection (several sweeps), the push-out of what it moved, the hooks. Returns the
    stencils turned in all rounds."""
    S = _FOLD.get(id(G))
    if S is None:
        return 0
    n = 0
    for _ in range(rounds):
        m = S.unfold(X, free, sweeps=4)
        n += m
        if not m:
            break
        X0 = X.copy()
        X[:], _ = push_out(X, G["Tw"], real, pu["clear_m"], 0)
        X[~free] = X0[~free]
        for _ in range(2):
            for h_ in hooks:
                h_(X, free)
    for _ in range(10):                 # and the limit last, alone
        m = S.unfold(X, free, sweeps=4)
        n += m
        if not m:
            break
    return n


def made_parts(prefix):
    """The loaded made garment's parts (objects named prefix*, not the collider): name -> (V, F)."""
    out = {}
    for o in bpy.data.objects:
        if o.type == "MESH" and o.name.startswith(prefix) and "lod" not in o.name:
            out[o.name] = (evaluated(o), [tuple(p.vertices) for p in o.data.polygons])
    return out


def rig_copy(nm):
    """A copy of the loaded made part `nm` (its UVs, material slots, normals and part tags kept) as
    rig_<nm>, without vertex groups or shape keys; its materials restored from MADE_SLOTS."""
    src = bpy.data.objects[nm]
    o = src.copy()
    o.data = src.data.copy()
    o.name = o.data.name = f"rig_{nm}"
    o.vertex_groups.clear()
    if o.data.shape_keys:
        o.shape_key_clear()
    mats = MADE_SLOTS.get(nm)
    if mats and all(m is not None for m in mats):
        o.data.materials.clear()
        for m in mats:
            o.data.materials.append(m)
    bpy.context.scene.collection.objects.link(o)
    return o


def tuck_layers(G, T):
    """Sink each under-layer's covered vertices (deform_rig.tuck on the drapes): covered = a ray along
    the vertex normal, either way, meets a layer further out within reach_m. The sink is depth_m
    along the side the cover is on, feathered to 0 over margin_m from the nearest visible vertex.
    Changes G[key]["X0"] in place; returns ({key: feather f}, stats)."""
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    from mathutils.kdtree import KDTree
    from character import suit_wrinkle as swk
    outers = {"shirt": ("waistcoat", "jacket"), "waistcoat": ("jacket",)}
    F, st = {}, {}
    for key, outs in outers.items():
        X = G[key]["X0"]
        V = np.concatenate([G[o]["X0"] for o in outs])
        off = np.cumsum([0] + [len(G[o]["X0"]) for o in outs])
        Tt = np.concatenate([G[o]["Tw"] + off[i] for i, o in enumerate(outs)])
        bvh = BVHTree.FromPolygons([tuple(map(float, v)) for v in V], [tuple(map(int, t)) for t in Tt])
        N = swk.vertex_normals(X, G[key]["Tw"])
        cov = np.zeros(len(X), bool)
        sgn = np.zeros(len(X))
        for i, (p, n) in enumerate(zip(X, N)):
            for sg in (1.0, -1.0):
                d = Vector(n * sg)
                if bvh.ray_cast(Vector(p) + d * 1e-4, d, T["reach_m"])[0] is not None:
                    cov[i], sgn[i] = True, sg
                    break
        vis = np.nonzero(~cov)[0]
        f = np.zeros(len(X))
        if len(vis) and cov.any():
            kd = KDTree(len(vis))
            for j, i in enumerate(vis):
                kd.insert(X[i], j)
            kd.balance()
            dv = np.array([kd.find(X[i])[2] if cov[i] else 0.0 for i in range(len(X))])
            t = np.clip((dv - 0.4 * T["margin_m"]) / (0.6 * T["margin_m"]), 0, 1)
            f = t * t * (3 - 2 * t) * cov
        X -= (N * sgn[:, None]) * (f * T["depth_m"][key])[:, None]
        F[key] = f
        st[key] = {"covered": int(cov.sum()), "sunk_full": int((f > 0.99).sum()), "verts": len(X),
                   "depth_mm": T["depth_m"][key] * 1000}
    return F, st


# --- T13d: the posed sim's faults fixed at the source ------------------------------------------------
# c1 showed: the jacket sleeve starting (skinned) inside the shirt sleeve and staying there (a shell
# field cannot push a point out that is already behind it), the fronts passing through each other
# below the button (the overlap is within self_excl at rest, so no self-contact acts there), the
# made cuffs and collar riding on the drape's last faces 6 cm out (a long lever: every turn of the
# end faces swung the cuff into spikes), the jacket's neck riding up the shirt collar.

def zone_weight(W, idx):
    """One weight row for a rigid part: the mean of W over idx, the top 4 kept."""
    from character import deform_rig as drig
    return drig.prune(W[idx].mean(0, keepdims=True).copy(), 4)[0]


def feather_rows(W, X, idx, w_row, margin):
    """W with the rows of idx set to w_row and blended back to their own over margin (m) around them
    (a smoothstep in the distance to the nearest idx vertex). Returns (W, f)."""
    from mathutils.kdtree import KDTree
    from character import deform_rig as drig
    kd = KDTree(len(idx))
    for j, i in enumerate(idx):
        kd.insert(X[i], j)
    kd.balance()
    d = np.array([kd.find(p)[2] for p in X])
    t = np.clip(1.0 - d / max(margin, 1e-9), 0.0, 1.0)
    f = t * t * (3 - 2 * t)
    f[idx] = 1.0
    W = W * (1 - f)[:, None] + f[:, None] * w_row[None]
    return drig.prune(W, 4), f


def tri_normals(V, T):
    n = np.cross(V[T[:, 1]] - V[T[:, 0]], V[T[:, 2]] - V[T[:, 0]])
    return n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)


def surf_bind(P, V, T, reach):
    """Each point's nearest point on (V, T): (face, barycentrics, height along the interpolated vertex
    normal, distance). Points farther than reach get face -1."""
    from mathutils.bvhtree import BVHTree
    from character import suit_rig as sr
    bvh = BVHTree.FromPolygons([tuple(map(float, v)) for v in V], [tuple(map(int, t)) for t in T])
    N = sr.vertex_normals(V, T)
    fi = np.full(len(P), -1)
    bc = np.zeros((len(P), 3))
    h = np.zeros(len(P))
    dist = np.full(len(P), 9.0)
    for k, p in enumerate(P):
        loc, _, f, d = bvh.find_nearest(Vector(p), reach)
        if loc is None:
            continue
        a, b, c = V[T[f]]
        v0, v1, v2 = b - a, c - a, np.array(loc) - a
        d00, d01, d11, d20, d21 = v0 @ v0, v0 @ v1, v1 @ v1, v2 @ v0, v2 @ v1
        den = max(d00 * d11 - d01 * d01, 1e-18)
        v = (d11 * d20 - d01 * d21) / den
        w = (d00 * d21 - d01 * d20) / den
        u = np.clip(np.array([1 - v - w, v, w]), 0, 1)
        u /= u.sum()
        n = u @ N[T[f]]
        n /= max(np.linalg.norm(n), 1e-12)
        fi[k], bc[k], h[k], dist[k] = f, u, float((p - np.array(loc)) @ n), d
    return fi, bc, h, dist


class Anchors:
    """Rest-referenced layer order: each outer-layer vertex over an under-layer surface at rest keeps
    above the same surface point (face + barycentrics, followed as the under-layer moves) along its
    normal by gap. Unlike a distance field this does not depend on which face is nearest in the
    pose, so a vertex that starts through the under-layer is put back on the right side."""

    def __init__(self, X, V, T, reach=0.04, gap_max=0.003, gap_min=0.0008, sign=None, lat_max=0.02):
        self.lat_max = lat_max
        fi, bc, h, dist = surf_bind(X, V, T, reach)
        if sign is None:            # the under-layer's faces may wind either way: most points are above
            sign = 1.0 if np.median(h[fi >= 0]) >= 0 else -1.0
        h = h * sign
        ok = (fi >= 0) & (h > 0.0) & (h > 0.8 * dist)
        self.idx = np.nonzero(ok)[0]
        self.fi, self.bc, self.T, self.sign = fi[ok], bc[ok], np.asarray(T), sign
        self.h0 = h[ok]
        self.gap = np.clip(self.h0 - 0.001, gap_min, gap_max)

    def frame(self, Vp):
        from character import suit_rig as sr
        N = sr.vertex_normals(Vp, self.T) * self.sign
        tri = self.T[self.fi]
        P = np.einsum("nk,nki->ni", self.bc, Vp[tri])
        n = np.einsum("nk,nki->ni", self.bc, N[tri])
        return P, n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)

    def hook(self, Vp):
        """A post-collision hook against the posed under-layer Vp (static during the solve)."""
        P, n = self.frame(Vp)
        idx, gap, lat = self.idx, self.gap, self.lat_max

        def f(X, free, P=P, n=n, idx=idx, gap=gap):
            d = X[idx] - P
            s = (d * n).sum(1)
            bad = (s < gap) & free[idx]
            if lat:
                bad &= np.linalg.norm(d - s[:, None] * n, axis=1) < lat
            if bad.any():
                X[idx[bad]] += (gap[bad] - s[bad])[:, None] * n[bad]
        return f

    def repair(self, X, Vp, lift_max=0.012):
        """The start state: vertices below their surface point go back to their rest height (capped)."""
        P, n = self.frame(Vp)
        s = ((X[self.idx] - P) * n).sum(1)
        bad = s < self.gap
        tgt = np.minimum(np.maximum(self.h0, self.gap), lift_max)
        X[self.idx[bad]] += (tgt[bad] - s[bad])[:, None] * n[bad]
        return int(bad.sum())

    def count(self, X, Vp, tol=0.0):
        P, n = self.frame(Vp)
        d = X[self.idx] - P
        s = (d * n).sum(1)
        bad = s < -tol
        if self.lat_max:
            bad &= np.linalg.norm(d - s[:, None] * n, axis=1) < self.lat_max
        return int(bad.sum())


class Overlap:
    """One part of a garment over another of the same garment (the left front over the right below
    the break): each over-vertex keeps above its rest point on the under-part (faces of the under
    panel, followed as both move) by gap; the correction is shared between the two sides."""

    def __init__(self, X, T, over, under_faces, reach=0.03, gap_max=0.004):
        fi, bc, h, dist = surf_bind(X[over], X, T[under_faces], reach)
        sign = 1.0 if np.median(h[fi >= 0]) > 0 else -1.0
        h *= sign
        ok = (fi >= 0) & (h > 0.0) & (h > 0.7 * dist)
        self.a = np.asarray(over)[ok]
        self.tri = T[under_faces][fi[ok]]
        self.bc, self.sign = bc[ok], sign
        self.gap = np.clip(h[ok], 0.001, gap_max)

    def ease_near(self, X0, pts, r0=0.03, r1=0.06):
        """Near the button pairs the pair's own rest gap governs: over-vertices within r0 of a pair
        vertex drop out, the gap eases from 1 mm at r0 to the rest gap at r1 (T13d i3: the rest
        gap held against the button's pull crumpled the fronts round the button in the walk)."""
        if not len(pts):
            return
        d = np.min(np.linalg.norm(X0[self.a][:, None, :] - X0[np.asarray(pts)][None, :, :], axis=2), 1)
        keep = d >= r0
        t = np.clip((d - r0) / (r1 - r0), 0, 1)
        g = np.maximum(0.001, self.gap * t * t * (3 - 2 * t))
        self.a, self.tri, self.bc, self.gap = self.a[keep], self.tri[keep], self.bc[keep], g[keep]

    def __call__(self, X, free):
        A, B = X[self.tri[:, 1]] - X[self.tri[:, 0]], X[self.tri[:, 2]] - X[self.tri[:, 0]]
        n = np.cross(A, B) * self.sign
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
        P = np.einsum("nk,nki->ni", self.bc, X[self.tri])
        s = ((X[self.a] - P) * n).sum(1)
        bad = s < self.gap
        if not bad.any():
            return
        c = (self.gap[bad] - s[bad])[:, None] * n[bad]
        fa = free[self.a[bad]][:, None]
        X[self.a[bad]] += 0.5 * c * fa
        for k in range(3):
            v = self.tri[bad, k]
            np.add.at(X, v, -0.5 * c * self.bc[bad, k][:, None] * free[v][:, None])

    def count(self, X):
        A, B = X[self.tri[:, 1]] - X[self.tri[:, 0]], X[self.tri[:, 2]] - X[self.tri[:, 0]]
        n = np.cross(A, B) * self.sign
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
        P = np.einsum("nk,nki->ni", self.bc, X[self.tri])
        return int((((X[self.a] - P) * n).sum(1) < 0).sum())


def cull_hidden(C, poses, Ms, rt_Y, G, parts, tparts, place, arm, rig_, rt, body, tris, stats, res, anc=None,
                col0=None):
    """Per pose (the runtime: what ships), the under-layers' points that some ray in a cone about the
    outward normal sees out of (suit_cull.visible): the shirt and waistcoat drapes, the jacket's inside
    (its lining and facings, looking in), the shirt's cuffs and the trousers' shell. The visible sets
    are grown by a margin over each mesh; a made part's face is kept when any of its vertices rides on
    a kept point. Then each pose's jacket is checked against the kept under-layers (and the body).
    Returns {part name: face keep mask}."""
    from mathutils.kdtree import KDTree
    from character import suit_cull as sc
    from character import suit_rig as sr
    t0 = time.perf_counter()
    dirs = sc.cone_dirs(tuple(C["tilts"]), C["k"])
    # the body and the cuffs: no grazing rays past 60 deg (at 75 deg a ray slides down the gap between
    # the arm (or the cuff) and the sleeve and leaves by the cuff: a view along the forearm's axis)
    dirs_n = sc.cone_dirs(tuple(C.get("tilts_narrow", C["tilts"])), C["k"])
    K = len(poses)
    Gs, Gw, Gj = G["shirt"], G["waistcoat"], G["jacket"]
    jparts = [nm for nm, p in parts.items() if p["key"] == "jacket" and not nm.endswith("collider")]
    wparts = [nm for nm, p in parts.items() if p["key"] == "waistcoat" and not nm.endswith("collider")]
    sparts = [nm for nm, p in parts.items() if p["key"] == "shirt" and not nm.endswith("collider")]
    tnm = [nm for nm in tparts if not nm.endswith("collider")]
    tshell = next((nm for nm in tnm if nm.endswith("shell")), None)
    cuff = "spike_shirt_cuffs" if "spike_shirt_cuffs" in parts else None
    tie = "spike_tie_shell" if "spike_tie_shell" in parts else None
    # outward normals: the drapes' winding is taken against the rest body
    from mathutils.bvhtree import BVHTree
    bb = BVHTree.FromPolygons([tuple(map(float, v)) for v in body_rest_co(body)], [tuple(map(int, t)) for t in tris])

    def sign_of(X, N):
        s_ = [float((np.asarray(x) - np.array(bb.find_nearest(Vector(x))[0])) @ n) for x, n in zip(X[::7], N[::7])]
        return 1.0 if np.median(s_) >= 0 else -1.0
    sg = {k: sign_of(G[k]["X0"], sr.vertex_normals(G[k]["X0"], G[k]["Tw"])) for k in ("shirt", "waistcoat", "jacket")}
    vis = {"shirt": np.zeros(len(Gs["X0"]), bool), "waistcoat": np.zeros(len(Gw["X0"]), bool),
           "jacket_in": np.zeros(len(Gj["X0"]), bool)}
    if cuff:
        vis["cuffs"] = np.zeros(len(parts[cuff]["V0"]), bool)
    if tshell:
        vis["trousers"] = np.zeros(len(tparts[tshell]["V0"]), bool)
    if tie:
        vis["tie"] = np.zeros(len(parts[tie]["V0"]), bool)
    body_vis = None
    if cuff:
        cuff_first = np.full(len(parts[cuff]["V0"]), -1)
        cuff_esc = np.zeros((len(parts[cuff]["V0"]), 3))
        cuff_pos = np.zeros((len(parts[cuff]["V0"]), 3))
    per_pose = []
    for k, pname in enumerate(poses):
        dp.apply_pose(arm, pose_spec(pname), rig_)
        if rt is not None:
            rt.apply(rig_, morphs=False)
        bpy.context.view_layer.update()
        cop = evaluated(body)
        Bm = [(cop, tris)]
        Jm = [(place(nm, rt_Y["jacket"][k], Ms[k]), tris_of(parts[nm]["F"])) for nm in jparts]
        Wm_ = [(place(nm, rt_Y["waistcoat"][k], Ms[k]), tris_of(parts[nm]["F"])) for nm in wparts]
        Sm_ = [(place(nm, rt_Y["shirt"][k], Ms[k]), tris_of(parts[nm]["F"])) for nm in sparts]
        Tm = [(sr.skin(tparts[nm]["V0"], tparts[nm]["W"], Ms[k]), tris_of(tparts[nm]["F"])) for nm in tnm]
        # the welded drapes close the made panels' seam gaps (stage-1 p95 up to 3 mm): through them a
        # cone ray from a cuff 6 cm up the sleeve, or the shirt in a closed armpit, got out (i4c)
        Jd = [(rt_Y["jacket"][k], Gj["Tw"])]
        Wd = [(rt_Y["waistcoat"][k], Gw["Tw"])]
        Sd = [(rt_Y["shirt"][k], Gs["Tw"])]
        Jm = Jm + Jd
        Wm_ = Wm_ + Wd
        occ_s = sc.bvh_of(Bm + Jm + Wm_ + Tm)
        Tie_ = [(place(tie, rt_Y["shirt"][k], Ms[k]), tris_of(parts[tie]["F"]))] if tie else []
        occ_st = sc.bvh_of(Bm + Jm + Wm_ + Tm + Tie_) if tie else occ_s
        occ_w = sc.bvh_of(Bm + Jm + Tm)
        occ_j = sc.bvh_of(Bm + Sm_ + Sd + Wm_ + Tm + Jm)
        n0 = {kk: int(v.sum()) for kk, v in vis.items()}
        for key, occ in (("shirt", occ_st), ("waistcoat", occ_w)):
            P_ = rt_Y[key][k]
            N_ = sr.vertex_normals(P_, G[key]["Tw"]) * sg[key]
            vis[key] |= sc.visible(P_, N_, occ, dirs, ~vis[key], eps=C["eps_m"], reach=C["reach_m"], zmin=C.get("view_zmin"))
        P_ = rt_Y["jacket"][k]
        N_ = -sr.vertex_normals(P_, Gj["Tw"]) * sg["jacket"]
        vis["jacket_in"] |= sc.visible(P_ + N_ * C["lining_m"], N_, occ_j, dirs, ~vis["jacket_in"], eps=C["eps_m"],
                                       reach=C["reach_m"], zmin=C.get("view_zmin"))
        if cuff:
            P_ = place(cuff, rt_Y["shirt"][k], Ms[k])
            N_ = sr.vertex_normals(P_, tris_of(parts[cuff]["F"]))
            esc_ = np.zeros((len(P_), 3))
            new_ = sc.visible(P_, N_, occ_s, dirs_n, ~vis["cuffs"], eps=C["eps_m"], reach=C["reach_m"], zmin=C.get("view_zmin"), esc=esc_)
            cuff_first[new_ & (cuff_first < 0)] = k
            cuff_esc[new_] = esc_[new_]
            cuff_pos[new_] = P_[new_]
            vis["cuffs"] |= new_
        if tie:
            P_ = Tie_[0][0]
            N_ = sr.vertex_normals(P_, tris_of(parts[tie]["F"]))
            vis["tie"] |= sc.visible(P_, N_, occ_s, dirs, ~vis["tie"], eps=C["eps_m"], reach=C["reach_m"], zmin=C.get("view_zmin"))
        if tshell:
            P_ = sr.skin(tparts[tshell]["V0"], tparts[tshell]["W"], Ms[k])
            N_ = sr.vertex_normals(P_, tris_of(tparts[tshell]["F"]))
            vis["trousers"] |= sc.visible(P_, N_, occ_s, dirs, ~vis["trousers"], eps=C["eps_m"], reach=C["reach_m"], zmin=C.get("view_zmin"))
        # the body where it shows past the whole outfit (the build's hide_body deletes the rest)
        Pb = np.array(cop)
        if body_vis is None:
            body_vis = np.zeros(len(Pb), bool)
        Nb = sr.vertex_normals(Pb, np.asarray(tris))
        occ_b = sc.bvh_of(Bm + Sm_ + Sd + Wm_ + Tm + Jm + Tie_)
        body_vis |= sc.visible(Pb, Nb, occ_b, dirs_n, ~body_vis, eps=C["eps_m"], reach=C["reach_m"], zmin=C.get("view_zmin"))
        per_pose.append({kk: int(v.sum()) - n0[kk] for kk, v in vis.items()})
        print(f"[cull] {pname}: newly visible {per_pose[-1]}", flush=True)
    # grow over each mesh, then the faces
    grown = {}
    for key in ("shirt", "waistcoat"):
        nb = sc.adjacency(G[key]["Tw"], len(G[key]["X0"]))
        grown[key] = sc.grow_dist(vis[key], G[key]["X0"], nb, C["margin_m"])
    nbj = sc.adjacency(Gj["Tw"], len(Gj["X0"]))
    grown["jacket_in"] = sc.grow_dist(vis["jacket_in"], Gj["X0"], nbj, C["margin_m"])
    if cuff:
        V_ = parts[cuff]["V0"]
        grown["cuffs"] = sc.grow_dist(vis["cuffs"], V_, sc.adjacency(parts[cuff]["F"], len(V_)), C["cuff_margin_m"])
    if tie:
        V_ = parts[tie]["V0"]
        grown["tie"] = sc.grow_dist(vis["tie"], V_, sc.adjacency(parts[tie]["F"], len(V_)), C["margin_m"])
    if tshell:
        V_ = tparts[tshell]["V0"]
        grown["trousers"] = sc.grow_dist(vis["trousers"], V_, sc.adjacency(tparts[tshell]["F"], len(V_)),
                                         C["margin_m"])
    keep = {}
    kd_c = None
    if cuff:
        Vc = parts[cuff]["V0"]
        kd_c = KDTree(len(Vc))
        for i, v in enumerate(Vc):
            kd_c.insert(v, i)
        kd_c.balance()
    for nm, p in parts.items():
        if nm.endswith("collider"):
            continue
        key = p["key"]
        F_ = p["F"]
        T_ = G[key]["Tw"]
        on_drape = np.zeros(len(p["V0"]), bool)
        if nm == tie:
            keep[nm] = sc.face_keep(F_, grown["tie"])
        elif key in ("shirt", "waistcoat"):
            on_drape = grown[key][T_[p["bind"]["fi"]]].any(1)
            rg = p.get("rigid")
            if rg is not None:
                if nm == "spike_shirt_collar":
                    on_drape[rg[0]] = True
                elif nm == cuff:
                    on_drape = grown["cuffs"].copy()
                else:
                    for i in np.nonzero(rg[0])[0]:
                        v = p["V0"][i]
                        _, j, d = kd_c.find(v) if kd_c is not None else (None, None, 9.0)
                        on_drape[i] = bool(grown["cuffs"][j]) if (j is not None and d < 0.02) else True
            keep[nm] = sc.face_keep(F_, on_drape)
        elif key == "jacket":
            inner = p["bind"]["off"][:, 2] * sg["jacket"] < -C["inner_off_m"]
            seen = grown["jacket_in"][T_[p["bind"]["fi"]]].any(1)
            vk = ~inner | seen
            keep[nm] = sc.face_keep(F_, vk)
    if tshell:
        keep[tshell] = sc.face_keep(tparts[tshell]["F"], grown["trousers"])
    st = {"s": round(time.perf_counter() - t0, 1), "dirs": len(dirs), "per_pose_new": dict(zip(poses, per_pose)),
          "visible_points": {kk: [int(v.sum()), int(len(v))] for kk, v in vis.items()},
          "grown_points": {kk: [int(v.sum()), int(len(v))] for kk, v in grown.items()}, "parts": {}}
    for nm, m in keep.items():
        F_ = parts[nm]["F"] if nm in parts else tparts[nm]["F"]
        st["parts"][nm] = {"tris_before": sc.tri_count(F_), "tris_after": sc.tri_count([f for f, k_ in zip(F_, m) if k_])}
    from mathutils.kdtree import KDTree as _KD
    tri_a = np.asarray(tris)
    shown_v = sc.grow_dist(body_vis, body_rest_co(body), sc.adjacency(tri_a, len(body_vis)), C.get("body_margin_m", 0.03))
    st["body_shown"] = [int(shown_v.sum()), int(len(shown_v))]
    # the runtime penetration against what is kept: jacket drape vertices inside the body or behind a
    # kept under-layer face; and the kept under-layer faces' vertices outside the jacket where it
    # covered them at rest (shown through)
    for k, pname in enumerate(poses):
        dp.apply_pose(arm, pose_spec(pname), rig_)
        if rt is not None:
            rt.apply(rig_, morphs=False)
        bpy.context.view_layer.update()
        cop = evaluated(body)
        shells = []
        for nm in sparts + wparts:
            m = keep.get(nm)
            key = parts[nm]["key"]
            F_ = [f for f, k_ in zip(parts[nm]["F"], m) if k_] if m is not None else parts[nm]["F"]
            if F_:
                shells.append((place(nm, rt_Y[key][k], Ms[k]), tris_of(F_)))
        for nm in tnm:
            m = keep.get(nm)
            F_ = [f for f, k_ in zip(tparts[nm]["F"], m) if k_] if m is not None else tparts[nm]["F"]
            if F_:
                shells.append((sr.skin(tparts[nm]["V0"], tparts[nm]["W"], Ms[k]), tris_of(F_)))
        L_all = Layers(cop, tris, shells)
        L_body = Layers(cop, tris, [])
        Yj = rt_Y["jacket"][k]
        ins = [i for i, p_ in enumerate(Yj) if L_all.signed(p_)[0] < -0.0005]
        dep = {i: L_body.signed(Yj[i]) for i in ins}
        inb_ = [i for i in ins if dep[i][0] < -0.0005]
        inb = len(inb_)
        # where it shows: the body's nearest point on a face with a shown vertex (else the build deleted it)
        Pb_ = np.array(cop)
        kd_b = _KD(len(Pb_))
        for i_, v_ in enumerate(Pb_):
            kd_b.insert(v_, i_)
        kd_b.balance()
        ins_shown = [i for i in inb_ if shown_v[kd_b.find(dep[i][1])[1]]]
        res[pname]["inside_rt_culled"] = {"jacket": len(ins), "jacket_body": inb, "jacket_layers": len(ins) - inb,
                                          "jacket_body_shown": len(ins_shown),
                                          "body_depth_mm_max": round(-min([dep[i][0] for i in inb_], default=0.0) * 1000, 1)}
        res[pname]["inside_rt_culled_idx"] = ins[:400]
        # --- the gate's count (T13d): what shows. (1) the body: every jacket vertex inside the closed
        # body (its own sign, not read through a nearer shell) where the body is shown; (2) the layers:
        # each jacket vertex against the kept under-layer point it lay over at rest (the sim's own
        # anchors, rest-referenced: no nearest-face misreading at a culled shell's edge or in a crevice)
        bd = {i: L_body.signed(p_) for i, p_ in enumerate(Yj)}
        body_in = [i for i, v_ in bd.items() if v_[0] < -0.0005]
        body_sh = {i for i in body_in if shown_v[kd_b.find(bd[i][1])[1]]}
        ord_bad = {}
        for (outer, u), an in (anc or {}).items():
            if outer != "jacket" or u not in (col0 or {}):
                continue
            if u == "trousers":
                tn = col0["trousers"][2]
                Vp = sr.skin(tparts[tn]["V0"], tparts[tn]["W"], Ms[k])
                kept_f = np.ones(len(an.idx), bool)
            elif u == "tie":
                tnm_ = "spike_tie_shell"
                Vp = place(tnm_, rt_Y["shirt"][k], Ms[k])
                F_t = parts[tnm_]["F"]
                tri_poly = np.repeat(np.arange(len(F_t)), [len(f) - 2 for f in F_t])
                kept_f = keep[tnm_][tri_poly[an.fi]] if tnm_ in keep else np.ones(len(an.idx), bool)
            else:
                cn = f"spike_{u}_collider"
                Vp = place(cn, rt_Y[u][k], Ms[k])
                kv = grown[u][G[u]["Tw"][parts[cn]["bind"]["fi"]]].any(1)
                kept_f = kv[an.T[an.fi]].any(1)
            P_, n_ = an.frame(Vp)
            d_ = Yj[an.idx] - P_
            s_ = (d_ * n_).sum(1)
            lat_ = np.linalg.norm(d_ - s_[:, None] * n_, axis=1)
            bad_ = (s_ < -0.0005) & (lat_ < (an.lat_max or 9.0)) & kept_f
            for i in an.idx[bad_]:
                ord_bad.setdefault(int(i), u)
        gate = set(ord_bad) | body_sh
        res[pname]["pen_rt"] = {"gate": len(gate), "layers": len(ord_bad), "body_shown": len(body_sh),
                                "body_all": len(body_in),
                                "by_layer": {u: sum(1 for v_ in ord_bad.values() if v_ == u) for u in set(ord_bad.values())},
                                "body_depth_mm_max": round(-min([bd[i][0] for i in body_in], default=0.0) * 1000, 1)}
        res[pname]["pen_rt_idx"] = sorted(gate)[:400]
        print(f"[cull] {pname}: jacket inside (runtime, culled layers) {res[pname]['inside_rt_culled']} "
              f"gate {res[pname]['pen_rt']}", flush=True)
    st["s_total"] = round(time.perf_counter() - t0, 1)
    stats["cull"] = st
    np.savez_compressed(os.path.join(A.out_dir, "cull_vis.npz"), **{f"vis_{k_}": v_ for k_, v_ in vis.items()},
                        **{f"grown_{k_}": v_ for k_, v_ in grown.items()}, body_vis=body_vis, body_shown=shown_v,
                        **({"cuff_first": cuff_first, "cuff_esc": cuff_esc, "cuff_pos": cuff_pos} if cuff else {}))
    print(f"[cull] parts {st['parts']} in {st['s_total']} s", flush=True)
    return keep


def culled_lods(ratios):
    """Per garment, the exported (culled) rig parts joined and collapse-decimated: cull_spike_<g>_lod<k>
    (no weights or keys; suit_made.lod_from skins them from the full part at build time)."""
    from character import suit_made as smd
    out = {}
    for g in ("jacket", "shirt", "waistcoat", "trousers", "tie"):
        src = [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(f"rig_spike_{g}_")
               and "collider" not in o.name]
        if not src:
            continue
        for k_, ratio in sorted(ratios.items()):
            cps = []
            for o in src:
                c = o.copy()
                c.data = o.data.copy()
                bpy.context.scene.collection.objects.link(c)
                if c.data.shape_keys:
                    c.shape_key_clear()
                c.vertex_groups.clear()
                for md in list(c.modifiers):
                    c.modifiers.remove(md)
                cps.append(c)
            ob = smd.join(cps, f"cull_spike_{g}_lod{k_}")
            if ob.data.shape_keys:
                ob.shape_key_clear()
            dec = ob.modifiers.new("dec", "DECIMATE")
            dec.ratio = float(ratio)
            dg = bpy.context.evaluated_depsgraph_get()
            me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg))
            old = ob.data
            ob.modifiers.remove(dec)
            ob.data = me
            bpy.data.meshes.remove(old)
            me.name = ob.name
            ob.hide_render = True
            out[f"{g}_lod{k_}"] = sum(len(p.vertices) - 2 for p in me.polygons)
    return out


def make_tie(T, parts, Gs, base, sr, collar_row, stats):
    """Build the four-in-hand (suit_tie) on the shirt's rest collider and collar; add it to parts as
    spike_tie_shell (key shirt: wrapped on the shirt drape, the knot on the collar's row). Its UV
    density is the lofted tie's (the silk weave's repeat), its material the lofted tie's."""
    from mathutils.bvhtree import BVHTree
    from character import suit_tie as stie
    from character import deform_rig as drig  # noqa: F401
    Vc, Fc = parts["spike_shirt_collider"]["V0"], parts["spike_shirt_collider"]["F"]
    bvh = BVHTree.FromPolygons([tuple(map(float, v)) for v in Vc], [tuple(int(i) for i in f) for f in Fc])

    def front(x, z):
        # the front half only: above the band's front edge at the CF the ray passes through the
        # collar's gap and meets the back of the band (i3: the knot's top row 13 cm back); step down
        for dz in np.arange(0.0, 0.0301, 0.002):
            h = bvh.ray_cast(Vector((x, -1.0, z - dz)), Vector((0.0, 1.0, 0.0)), 2.0)
            if h[0] is not None and h[0].y < -0.03:
                return float(h[0].y)
        return -0.10
    Vk = parts["spike_shirt_collar"]["V0"]
    cf = (np.abs(Vk[:, 0]) < 0.004) & (Vk[:, 1] < 0)
    z_top = float(Vk[cf, 2].max()) + T["top_above_band_m"]
    z_tip = float(Gs["st"].get("band_top_z") or 1.15) + T["tip_above_band_m"]
    # the lofted tie's UV density (UV units per metre)
    lt = base["tie"]
    me = lt.data
    Mw = np.array(lt.matrix_world)
    X = np.array([v.co for v in me.vertices]) @ Mw[:3, :3].T + Mw[:3, 3]
    uv = np.empty(len(me.loops) * 2)
    me.uv_layers.active.data.foreach_get("uv", uv)
    uv = uv.reshape(-1, 2)
    dens = []
    for pl in me.polygons:
        li = list(pl.loop_indices)
        for a, b in zip(li, li[1:] + li[:1]):
            va, vb = me.loops[a].vertex_index, me.loops[b].vertex_index
            dx = np.linalg.norm(X[va] - X[vb])
            if dx > 1e-4:
                dens.append(np.linalg.norm(uv[a] - uv[b]) / dx)
    dens = float(np.median(dens)) if dens else 1.0
    # the waistcoat's inside over the blade (its made shell at rest: the first hit forward of the shirt)
    ceil = None
    if "spike_waistcoat_shell" in parts:
        Vw, Fw = parts["spike_waistcoat_shell"]["V0"], parts["spike_waistcoat_shell"]["F"]
        bvh_w = BVHTree.FromPolygons([tuple(map(float, v)) for v in Vw], [tuple(int(i) for i in f) for f in Fw])

        def ceil(x, z):
            y0 = front(x, z)
            h = bvh_w.ray_cast(Vector((x, y0 - 0.0002, z)), Vector((0.0, -1.0, 0.0)), 0.03)
            return float(h[0].y) if h[0] is not None else None
    V, F, UVc, tags = stie.build(front, lambda z: front(0.0, z), z_top, z_tip, T.get("opts"), uv_per_m=dens,
                                 uv_origin=tuple(uv.mean(0)), ceil=ceil)
    nm = "spike_tie_shell"
    me2 = bpy.data.meshes.new(nm)
    me2.from_pydata([tuple(p) for p in V], [], [tuple(int(i) for i in f) for f in F])
    me2.update()
    lay = me2.uv_layers.new(name="UVMap")
    k = 0
    for pl, cs in zip(me2.polygons, UVc):
        for li, c in zip(pl.loop_indices, cs):
            lay.data[li].uv = c
        pl.use_smooth = True
        k += 1
    for m in lt.data.materials:
        me2.materials.append(m)
    ob = bpy.data.objects.new(nm, me2)
    bpy.context.scene.collection.objects.link(ob)
    MADE_SLOTS[nm] = list(lt.data.materials)
    lt.hide_render = True
    fi, bc = bind_fn(Gs["X0"], Gs["Tw"])(V)
    z_kb = z_top - stie.DEFAULTS["knot_h_m"]
    f = np.where(V[:, 2] > z_kb, 1.0, np.clip(1 - (z_kb - V[:, 2]) / T["blend_m"], 0, 1))
    f = f * f * (3 - 2 * f)
    parts[nm] = {"key": "shirt", "F": [tuple(int(i) for i in fc) for fc in F], "V0": V,
                 "bind": sr.wrap_bind(Gs["X0"], Gs["Tw"], V, fi, bc), "blend": (f, collar_row), "tags": tags}
    stats["tie"] = {"tris": int(sum(len(fc) - 2 for fc in F)), "z_top": round(z_top, 4), "z_tip": round(z_tip, 4),
                    "uv_per_m": round(dens, 3), "knot_tris": int(sum(len(fc) - 2 for fc, t in zip(F, tags) if t == 0))}
    print(f"[spike] tie: {stats['tie']}", flush=True)
    return nm


def bind_under(G, Y, rtj, K, B, pinned):
    """T13d: the under-layers ride on the jacket's runtime where they lie under it in every pose. Each
    layer's corrective fit misses by its own error (up to ~14 mm over the 35 poses), more than the
    2-7 mm between the layers, so independently fitted layers cross. A waistcoat or shirt drape vertex
    is bound when it lies under a jacket face at rest (along the face's normal, not beside its edge,
    within reach_m) and in every simulated pose stays under that face point (lateral < lat_m, gap
    < gap_max_m); not a pinned (rigid cuff / collar) vertex. Its fit target becomes the jacket's
    runtime point there less the sim's own gap (at least gap_min_m), its weights the jacket's
    there; eased in over margin_m inside the bound region. Returns {key: (targets (K, n, 3), W, f)}
    and stats."""
    from mathutils.kdtree import KDTree
    from character import deform_rig as drig
    from character import suit_rig as sr
    Gj = G["jacket"]
    Xj, Tj = Gj["X0"], Gj["Tw"]
    out, st = {}, {}
    for key in ("waistcoat", "shirt"):
        Gx = G[key]
        X = Gx["X0"]
        fi, bc, h, dist = surf_bind(X, Xj, Tj, B["reach_m"])
        ok = fi >= 0
        if not ok.any():
            continue
        sg = -1.0 if np.median(h[ok]) > 0 else 1.0          # sg * h < 0: under the jacket
        hs = h * sg
        el = ok & (hs < -0.0005) & (np.abs(hs) > 0.7 * dist) & ~pinned[key]
        tri = Tj[np.maximum(fi, 0)]
        gaps = np.zeros((K, len(X)))
        cover = B.get("cover_m")
        if cover:
            # covered in every pose: the layer slides under the jacket (a shirt sleeve 2-4 cm along the
            # jacket's as the arm lifts), so not the same face point but a ray out along its normal
            # meets the jacket's sim within cover_m. Bound on the rest point at the rest gap: hidden.
            from mathutils.bvhtree import BVHTree as _BVH
            Nu0 = sr.vertex_normals(X, Gx["Tw"])
            Pj0 = np.einsum("nk,nki->ni", bc, Xj[tri])
            su = 1.0 if np.median(((Pj0 - X) * Nu0).sum(1)[el]) >= 0 else -1.0     # the under-layer's outward
            cand = np.nonzero(el)[0]
            for k in range(K):
                bvh = _BVH.FromPolygons([tuple(map(float, v)) for v in Y["jacket"][k]], [tuple(map(int, t)) for t in Tj])
                Nu = sr.vertex_normals(Y[key][k], Gx["Tw"]) * su
                keep_ = np.zeros(len(cand), bool)
                for j, v in enumerate(cand):
                    o_ = Y[key][k][v]
                    keep_[j] = bvh.ray_cast(Vector(o_ - Nu[v] * 0.002), Vector(Nu[v]), cover + 0.002)[0] is not None
                el[cand[~keep_]] = False
                cand = cand[keep_]
            gaps[:] = np.clip(-hs, B["gap_min_m"], B["gap_max_m"])[None]
        for k in range(K if not cover else 0):
            N = sr.vertex_normals(Y["jacket"][k], Tj) * sg
            P_ = np.einsum("nk,nki->ni", bc, Y["jacket"][k][tri])
            n_ = np.einsum("nk,nki->ni", bc, N[tri])
            n_ /= np.maximum(np.linalg.norm(n_, axis=1, keepdims=True), 1e-12)
            d_ = Y[key][k] - P_
            sk = (d_ * n_).sum(1)
            lat = np.linalg.norm(d_ - sk[:, None] * n_, axis=1)
            el &= (sk < B["gap_max_m"]) & (-sk < B["gap_max_m"]) & (lat < B["lat_m"])
            gaps[k] = np.clip(-sk, B["gap_min_m"], B["gap_max_m"])
        f = np.zeros(len(X))
        if el.any() and (~el).any():
            ne = np.nonzero(~el)[0]
            kd = KDTree(len(ne))
            for j, i in enumerate(ne):
                kd.insert(X[i], j)
            kd.balance()
            d0 = np.array([kd.find(X[i])[2] if el[i] else 0.0 for i in range(len(X))])
            t = np.clip(d0 / B["margin_m"], 0, 1)
            f = t * t * (3 - 2 * t) * el
        elif el.all():
            f = np.ones(len(X))
        Wj_b = np.einsum("nk,nkb->nb", bc, Gj["W"][tri])
        W = drig.prune(Gx["W"] * (1 - f)[:, None] + Wj_b * f[:, None], 4)
        T_ = np.zeros((K, len(X), 3))
        dev = []
        for k in range(K):
            N = sr.vertex_normals(rtj[k], Tj) * sg
            P_ = np.einsum("nk,nki->ni", bc, rtj[k][tri])
            n_ = np.einsum("nk,nki->ni", bc, N[tri])
            n_ /= np.maximum(np.linalg.norm(n_, axis=1, keepdims=True), 1e-12)
            tgt = P_ - n_ * gaps[k][:, None]
            T_[k] = Y[key][k] + f[:, None] * (tgt - Y[key][k])
            if (f > 0).any():
                dev.append(float(np.linalg.norm(T_[k] - Y[key][k], axis=1)[f > 0].max()))
        out[key] = (T_, W, f)
        st[key] = {"bound": int((f > 0.99).sum()), "eased": int(((f > 0) & (f <= 0.99)).sum()), "verts": len(X),
                   "under_at_rest": int((ok & (hs < -0.0005)).sum()),
                   "target_dev_from_sim_mm_max": round(max(dev, default=0.0) * 1000, 1)}
    return out, st


def constrain_fit(G, S, Dres, masks, Acone, Ms, lam, rt_Y, anc, col0, parts, tparts, place, cops, tris, C,
                  tie_nm=None):
    """T13d: the runtime made to keep the layer order. The corrective fit misses the sim by 5-14 mm
    RMS over the 35 poses (a ridge over shared cones), more than the 1-7 mm between the layers, so
    the fitted layers cross wherever the error points inward. Per round every rest-referenced anchor
    (an outer layer's vertex over the under-layer point it lay over at rest) and every jacket vertex
    against the posed body is read on the runtime; a pair under the trigger is resolved:
    - an under-layer (the shirt, the waistcoat under the jacket) sinks at rest along its inward
      normal by the shortfall (the most any pose asks), feathered over sink_r_m: pose-independent,
      so it cannot leak into the other poses as a cone shape does, and it is hidden there;
    - the outer layer goes out (against the skinned trousers, the body, and a rigid cuff or collar
      row the drape cannot move): its active vertices refitted with the pairs as weighted rows (a
      vertex's cone shapes are its own unknowns: min |A S - D|^2 + lam |S|^2 + w |n.Y - b|^2); a
      pair once active stays, pinned where it is while it holds.
    Changes S, G[key]["X0"] (the sunk rest) and rt_Y in place; returns (stats, {key: sink (n,)})."""
    from mathutils.kdtree import KDTree
    from character import suit_rig as sr
    K = len(Ms)
    trig, mg, mgb = C["trigger_m"], C["margin_m"], C["body_margin_m"]
    w = np.sqrt(C["weight"])
    act, act_ix = {}, {}
    hist = []
    Lb = [Layers(cops[k], tris, []) for k in range(K)]
    Cn = Acone.shape[1]
    X0b = {k_: G[k_]["X0"].copy() for k_ in G}
    sink = {k_: np.zeros((len(G[k_]["X0"]), 3)) for k_ in G}
    kd_cache = {}
    Rinv = {}                   # (key, k) -> per-vertex inverse blended rotations (lazy)

    def rinv(key, k):
        if (key, k) not in Rinv:
            Rinv[(key, k)] = np.linalg.inv(sr.blended(G[key]["W"], Ms[k])[:, :3, :3])
        return Rinv[(key, k)]

    def under_pts(u, k):
        if u == "trousers":
            tn = col0["trousers"][2]
            return sr.skin(tparts[tn]["V0"], tparts[tn]["W"], Ms[k]), None, None
        nm = tie_nm if u == "tie" else f"spike_{u}_collider"
        p_ = parts[nm]
        key = p_["key"]
        sup = G[key]["Tw"][p_["bind"]["fi"]]               # each collider vertex's drape face
        free = np.ones(len(sup), bool)
        if p_.get("rigid") is not None:
            free[p_["rigid"][0]] = False
        if p_.get("blend") is not None:
            free &= p_["blend"][0] < 0.5
        return place(nm, rt_Y[key][k], Ms[k]), (key, sup), free

    def read():
        out = {}
        for (outer, u), an in anc.items():
            if u not in col0 or (u == "tie" and not tie_nm):
                continue
            src = (outer, u)
            lm = an.lat_max or 9.0
            for k in range(K):
                Vp, sup, free = under_pts(u, k)
                P_, n_ = an.frame(Vp)
                d_ = rt_Y[outer][k][an.idx] - P_
                s_ = (d_ * n_).sum(1)
                lat_ = np.linalg.norm(d_ - s_[:, None] * n_, axis=1)
                sel = set(np.nonzero((s_ < trig) & (lat_ < lm))[0].tolist()) | act_ix.get((src, k), set())
                for a in sel:
                    if lat_[a] < lm:
                        out[(src, k, int(a))] = (outer, u, an, int(a), n_[a], max(0.0, mg - float(s_[a])), sup, free)
        src = ("body", "jacket")
        for k in range(K):
            Yj = rt_Y["jacket"][k]
            ax = act_ix.get((src, k), set())
            for i in range(len(Yj)):
                loc, nor, fi, d = Lb[k].body_bvh.find_nearest(Vector(Yj[i]))
                if loc is None:
                    continue
                nor = np.array(nor)
                s = float((Yj[i] - np.array(loc)) @ nor)
                if (trig > s > -C["body_depth_max_m"]) or i in ax:
                    out[(src, k, i)] = ("jacket", "body", None, i, nor, max(0.0, mgb - s), None, None)
        return out

    for r in range(C["rounds"] + 1):
        pairs = read()
        short, gate = {}, {}
        for (src, k, a), v in pairs.items():
            m_ = mgb if src[0] == "body" else mg
            nm_ = f"{src[0]}>{src[1]}"
            if v[5] > m_ - trig + 1e-9:
                short[nm_] = short.get(nm_, 0) + 1
            if v[5] > m_ + 0.0005 + 1e-9:
                gate[nm_] = gate.get(nm_, 0) + 1
        hist.append({"round": r, "below_trigger": short, "below_-0.5mm": gate, "active": len(act),
                     "sink_mm_max": {k_: round(float(np.linalg.norm(v_, axis=1).max()) * 1000, 1) for k_, v_ in sink.items()},
                     "sunk": {k_: int((np.linalg.norm(v_, axis=1) > 1e-4).sum()) for k_, v_ in sink.items()}})
        print(f"[constrain] round {r}: {hist[-1]}", flush=True)
        if r == C["rounds"] or not short:
            break
        rows = {k_: {} for k_ in G}          # outer layers: {vertex: [(k, n, b)]}, n . Y_v(k) >= b
        need = {k_: {} for k_ in G}          # under layers: {vertex: rest-space inward sink wanted}
        for key_, (outer, u, an, a, n, defi, sup, free) in pairs.items():
            if u == "body" or sup is None:
                if defi > 1e-9 or key_ in act:
                    act[key_] = act.get(key_, 0) + 1
                    act_ix.setdefault((key_[0], key_[1]), set()).add(key_[2])
                    i = a if u == "body" else int(an.idx[a])
                    rows[outer].setdefault(i, []).append((key_[1], n, float(n @ rt_Y[outer][key_[1]][i]) + defi))
                continue
            if defi <= 1e-9:
                continue
            k = key_[1]
            key_u, sup_f = sup
            dv = sorted({int(x) for j in an.T[an.fi[a]] if free[j] for x in sup_f[j]})
            if not dv:                       # a rigid row: the outer goes out
                act[key_] = act.get(key_, 0) + 1
                act_ix.setdefault((key_[0], key_[1]), set()).add(key_[2])
                i = int(an.idx[a])
                rows[outer].setdefault(i, []).append((k, n, float(n @ rt_Y[outer][k][i]) + defi))
                continue
            Ri = rinv(key_u, k)[dv]
            dr = np.einsum("nij,j->ni", Ri, -n)                 # the push, in rest space
            for j, d in enumerate(dv):
                need[key_u].setdefault(d, []).append((dr[j], defi))
        # the under layers: each wanting vertex's push (rest space, the largest asked), feathered to
        # its neighbours over sink_r_m (each takes the largest falloff-scaled push near it), added
        # to the sink so far (a drape's faces wind either way per panel: no normal is trusted)
        for key, nd in need.items():
            if not nd:
                continue
            add = np.zeros((len(sink[key]), 3))
            for v, lst in nd.items():
                for dr_, defi in lst:
                    u_ = dr_ / max(np.linalg.norm(dr_), 1e-12) * defi
                    if np.linalg.norm(u_) > np.linalg.norm(add[v]):
                        add[v] = u_
            src_v = np.array(sorted(nd))
            rr = C["sink_r_m"]
            sm = add.copy()
            mag = np.linalg.norm(sm, axis=1)
            if key not in kd_cache:
                kd_ = KDTree(len(X0b[key]))
                for v_, p_ in enumerate(X0b[key]):
                    kd_.insert(p_, v_)
                kd_.balance()
                kd_cache[key] = kd_
            for v in src_v:
                for (co_, u_, dd) in kd_cache[key].find_range(X0b[key][v], rr):
                    t_ = 1.0 - dd / rr
                    f_ = t_ * t_ * (3 - 2 * t_)
                    m_ = np.linalg.norm(add[v]) * f_
                    if m_ > mag[u_]:
                        sm[u_] = add[v] * f_
                        mag[u_] = m_
            sink[key] = sink[key] + sm
            nrm = np.linalg.norm(sink[key], axis=1)
            sink[key] *= np.minimum(1.0, C["sink_max_m"] / np.maximum(nrm, 1e-12))[:, None]
            G[key]["X0"][:] = X0b[key] + sink[key]
            W = G[key]["W"]
            rt_Y[key][:] = np.stack([sr.skin(G[key]["X0"] + sr.apply_shapes(S[key], Acone[k]), W, Ms[k]) for k in range(K)])
        # the outer layers: refit the active vertices with their rows
        for key, rv in rows.items():
            if not rv:
                continue
            Gx = G[key]
            X0, W = Gx["X0"], Gx["W"]
            idx = np.array(sorted(rv))
            Mv = np.stack([sr.blended(W[idx], Ms[k]) for k in range(K)], 1)      # (m, K, 4, 4)
            Ar = np.sqrt(lam) * np.eye(Cn * 3)
            br = np.zeros(Cn * 3)
            for j, v in enumerate(idx):
                m = masks[key][v]
                Am = Acone * m[None]
                Ad = np.zeros((K * 3, Cn * 3))
                for i3 in range(3):
                    Ad[i3::3, i3::3] = Am
                bd = Dres[key][:, v].reshape(-1)
                cr, cb = [], []
                for (k, n, b) in rv[v]:
                    R_, t_ = Mv[j, k, :3, :3], Mv[j, k, :3, 3]
                    nr = n @ R_
                    row = np.zeros(Cn * 3)
                    for i3 in range(3):
                        row[i3::3] = nr[i3] * Am[k]
                    cr.append(w * row)
                    cb.append(w * (b - float(n @ (R_ @ X0[v] + t_))))
                sol = np.linalg.lstsq(np.vstack([Ad, Ar, np.array(cr)]), np.concatenate([bd, br, np.array(cb)]),
                                      rcond=None)[0].reshape(Cn, 3)
                S[key][:, v] = sol * m[:, None]
            for k in range(K):
                rt_Y[key][k][idx] = sr.skin(X0[idx] + sr.apply_shapes(S[key][:, idx], Acone[k]), W[idx], Ms[k])
    st = {"rounds": hist, "active": len(act),
          "sink": {k_: {"verts": int((np.linalg.norm(v_, axis=1) > 1e-4).sum()),
                        "max_mm": round(float(np.linalg.norm(v_, axis=1).max()) * 1000, 1)} for k_, v_ in sink.items()}}
    return st, {k_: np.linalg.norm(v_, axis=1) for k_, v_ in sink.items() if v_.any()}


def body_rest_co(body):
    co = np.empty(len(body.data.vertices) * 3)
    body.data.vertices.foreach_get("co", co)
    return co.reshape(-1, 3)


def main_posed(O):
    """T13 item 6: the made suit (the jacket run A.posed and the layers it was draped over) rigged:
    the shipped weight pipeline on every layer; per pose, the shirt, the waistcoat and the jacket
    simulated in turn over the posed body and the layers under them; the skirt bones' follow
    gains fitted; Dem Bones for T13b's free jacket bones (a diagnostic); pose-space correctives
    over the suit's cones fitted per layer, with leave-one-out; the runtime (LBS + skirt bones +
    correctives) checked per pose for fit, penetration, the collar, the shoulder line and the seam
    hinges; frames (sim | runtime, front and 3/4, every pose)."""
    from character import deform_runtime as drt
    from character import suit_rig as sr
    global RENDER_SAMPLES
    RENDER_SAMPLES = int(O.get("render_samples", 0))
    run = A.posed
    st0 = json.load(open(os.path.join(run, "spike_stats.json")))
    runs = {"jacket": run}
    for k_ in ("trousers_from", "shirt_from", "waistcoat_from"):
        if st0.get(k_):
            runs[k_.split("_")[0]] = os.path.join(os.path.dirname(run.rstrip("/")), st0[k_])
    # the drapes: the shirt's and the waistcoat's own runs (the waistcoat run names the shirt's)
    stw = json.load(open(os.path.join(runs["waistcoat"], "spike_stats.json")))
    if stw.get("shirt_from"):
        runs["shirt"] = os.path.join(os.path.dirname(run.rstrip("/")), stw["shirt_from"])
    stats = {"run": os.path.basename(run.rstrip("/")), "runs": {k: os.path.basename(v.rstrip("/")) for k, v in runs.items()}}
    body, names = capture_body()
    arm, base = append_base(A.base_blend)
    assert np.allclose(np.array(arm.matrix_world), np.eye(4)), "armature must sit at the origin"
    # the made layers as the jacket left them (pressed under it): all from the jacket run's blend
    made = []
    for pre in ("spike_trousers_", "spike_shirt_", "spike_waistcoat_", "spike_jacket_"):
        made += load_made(run, pre)
    # the layers' colliders (outer faces of the made parts, as the drapes saw them)
    with bpy.data.libraries.load(os.path.join(run, "spike.blend"), link=False) as (src, dst):
        dst.objects = [n for n in src.objects if n.startswith("spike_") and n.endswith("_collider")]
    for o in dst.objects:
        if o is not None:
            bpy.context.scene.collection.objects.link(o)
            made.append(o)
    for key in ("trousers", "shirt", "waistcoat", "jacket", "buttons"):
        if key in base:
            base[key].hide_render = True
            base[key].hide_viewport = True
    for o in made:
        if o.name.endswith("collider"):
            COLLIDER_ONLY.add(o.name)
    am = body.modifiers.new("Armature", "ARMATURE")
    am.object = arm
    co, tris, dom, J = body_arrays(body, arm)
    names_all = [b.name for b in arm.data.bones if b.use_deform]
    Wb0, used = body_weights(body, arm)
    t = time.perf_counter()
    # the body as the shipped build skins it (shoulder cap, half joints onto the helpers, twist
    # splits); the garments take the raw body weights and get the garment remap themselves
    Wraw = sr.widen(Wb0, used, names_all)
    Wb = sr.remap(Wraw, co, arm, names_all, body=True)
    from character import deform_rig as drig
    drig.write(body, Wb, names_all)
    nearest = nearest_fn(co, tris)

    def garment_w(P, T, key, skirt=False):
        Wt = sr.transfer(P, T, Wraw, nearest, smooth_iters=0, k=len(names_all))
        return sr.remap(Wt, P, arm, names_all, sigma=O["sigma"][key], skirt=skirt,
                        arm_free=key != "trousers")
    G = {}
    for key in ("shirt", "waistcoat", "jacket"):
        G[key] = garment_drape(runs[key], key)
        G[key]["W"] = garment_w(G[key]["X0"], G[key]["Tw"], key, skirt=key == "jacket")
    # the made parts ride on their drape (wrap); the trousers are skinned (not simulated per pose)
    parts = {}
    for key, pre in (("shirt", "spike_shirt_"), ("waistcoat", "spike_waistcoat_"), ("jacket", "spike_jacket_")):
        bf = bind_fn(G[key]["X0"], G[key]["Tw"])
        pbf = panel_bind_fn(G[key], bf)
        for nm, (V, F) in made_parts(pre).items():
            fi, bc, pst = pbf(V, bpy.data.objects.get(nm)) if O.get("panel_bind", True) else (*bf(V), {})
            if pst:
                stats.setdefault("panel_bound", {})[nm] = pst
            parts[nm] = {"key": key, "F": F, "V0": V, "bind": sr.wrap_bind(G[key]["X0"], G[key]["Tw"], V, fi, bc)}
    tparts = {}
    for nm, (V, F) in made_parts("spike_trousers_").items():
        tparts[nm] = {"F": F, "V0": V, "W": garment_w(V, tris_of(F), "trousers")}
    rig_ = dp.Rig(arm)
    rt = None
    rp = os.path.join(os.path.dirname(A.base_blend), "character.rig.json")
    rules0 = json.load(open(rp)) if os.path.exists(rp) else {"helpers": [], "morphs": []}
    if O["rules"]:
        rt = drt.Runtime(arm, [], rules0)
    cones = suit_cones(arm, rig_)
    stats["cones"] = [{k: v for k, v in c.items() if k in ("name", "bone", "ref", "start", "_deg")} for c in cones]
    rtc = drt.Runtime(arm, [], {"morphs": cones})
    poses = [p for p in (A.poses.split(",") if A.poses else O["poses"]) if p]
    K = len(poses)
    # holds and pairs per layer
    Gs, Gw, Gj = G["shirt"], G["waistcoat"], G["jacket"]
    bt = float(Gs["st"].get("band_top_z") or 1.15)
    nb = np.array(arm.data.bones["neck_01"].head_local)
    bnd_s = boundary_verts(Gs["Tw"], len(Gs["X0"]))
    hands = [np.array(arm.data.bones[f"hand_{s}"].head_local) for s in ("l", "r")]
    s_neck = np.nonzero(bnd_s & (np.linalg.norm(Gs["X0"] - nb, axis=1) < 0.12) & (Gs["X0"][:, 2] > 1.35))[0]
    s_cuff = np.nonzero(bnd_s & (np.min([np.linalg.norm(Gs["X0"] - h, axis=1) for h in hands], 0) < 0.12))[0]
    s_tuck = np.nonzero(Gs["X0"][:, 2] < bt - 0.01)[0]
    w_sh = np.nonzero(np.array([bool({"front", "front_r"} & p) and bool({"back", "back_r"} & p) for p in Gw["panels"]])
                      & (Gw["X0"][:, 2] > 1.35))[0]

    def lr_pairs(Gx, zlo, zhi, step):
        fl = np.nonzero(np.array(["front" in p for p in Gx["panels"]]) & (np.abs(Gx["X0"][:, 0]) < 0.012)
                        & (Gx["X0"][:, 2] > zlo) & (Gx["X0"][:, 2] < zhi) & (Gx["X0"][:, 1] < 0))[0]
        fr = np.nonzero(np.array(["front_r" in p for p in Gx["panels"]]))[0]
        out, last = [], -9.0
        for i in fl[np.argsort(Gx["X0"][fl, 2])]:
            d_ = np.linalg.norm(Gx["X0"][fr] - Gx["X0"][i], axis=1)
            j = int(np.argmin(d_))
            if d_[j] < 0.008 and Gx["X0"][i, 2] - last > step:
                out.append(((int(i), int(fr[j])), float(max(d_[j], 0.001))))
                last = Gx["X0"][i, 2]
        return out
    w_pairs = lr_pairs(Gw, 1.05, 1.36, 0.03)
    j_pairs = lr_pairs(Gj, 0.95, 1.15, 0.5)[:1]
    ch = np.load(os.path.join(run, "chains.npz"))
    j_neck = np.unique(np.concatenate([ch["l_ids"], ch["r_ids"]]))
    j_neck = j_neck[Gj["X0"][j_neck, 2] > Gj["X0"][j_neck, 2].max() - 0.06]
    # --- T13d: the cuffs and the collar rigid (one weight row each: a fused cuff and collar do not
    # bend with the drape), the shirt drape under them pinned to them, the jacket's neckline on the
    # collar's row; the made parts' vertices there skinned with that row instead of wrapped
    from mathutils.kdtree import KDTree
    RG = O["rigid"]
    pinned = {k: np.zeros(len(G[k]["X0"]), bool) for k in G}
    zstats = {}
    fj_neck = None
    if RG["on"] and "spike_shirt_cuffs" in parts and "spike_shirt_collar" in parts:
        sx = 1.0 if arm.data.bones["hand_l"].head_local.x > 0 else -1.0
        Xs = Gs["X0"]

        def kd_of(P_):
            kd = KDTree(len(P_))
            for i, p_ in enumerate(P_):
                kd.insert(p_, i)
            kd.balance()
            return kd
        Vc, Vk = parts["spike_shirt_cuffs"]["V0"], parts["spike_shirt_collar"]["V0"]
        kdc, kdk = kd_of(Vc), kd_of(Vk)
        dc = np.array([kdc.find(x)[2] for x in Xs])
        dk = np.array([kdk.find(x)[2] for x in Xs])
        in_cuff = np.isin(np.arange(len(Xs)), s_cuff)
        in_neck = np.isin(np.arange(len(Xs)), s_neck)
        rows = {}
        zone_idx = {}
        for s_, sg in (("l", 1.0), ("r", -1.0)):
            m_ = ((dc < RG["cuff_r_m"]) | in_cuff) & (Xs[:, 0] * sx * sg > 0)
            zone_idx[f"cuff_{s_}"] = np.nonzero(m_)[0]
        zone_idx["collar"] = np.nonzero((dk < RG["collar_r_m"]) | in_neck)[0]
        Wsh = Gs["W"]
        for zn, idx in zone_idx.items():
            rows[zn] = zone_weight(Wsh, idx)
        for zn, idx in zone_idx.items():
            Wsh, _ = feather_rows(Wsh, Xs, idx, rows[zn], RG["margin_m"])
            pinned["shirt"][idx] = True
            zstats[zn] = {"drape_verts": int(len(idx)),
                          "row": {names_all[j]: round(float(w_), 3) for j, w_ in enumerate(rows[zn]) if w_ > 0}}
        Gs["W"] = Wsh
        # the jacket's neckline rides with the collar (it rode up past the shirt collar with the arms
        # forward in c1: high ready -12 mm, twist -13 mm)
        if RG["jneck"]:
            Gj["W"], fj_neck = feather_rows(Gj["W"], Gj["X0"], j_neck, rows["collar"], RG["jneck_margin_m"])
            pinned["jacket"][j_neck] = True
        # the made parts: a vertex on (or on a button sewn to) a cuff or the collar takes its row
        for nm, p in parts.items():
            if p["key"] != "shirt":
                continue
            V_ = p["V0"]
            if nm == "spike_shirt_cuffs":
                m_ = np.ones(len(V_), bool)
                Wr_ = np.array([rows["cuff_l" if x * sx > 0 else "cuff_r"] for x in V_[:, 0]])
            elif nm == "spike_shirt_collar":
                m_ = np.ones(len(V_), bool)
                Wr_ = np.tile(rows["collar"], (len(V_), 1))
            else:
                r_ = RG["button_r_m"] if "buttons" in nm else RG["part_r_m"]
                d1 = np.array([kdc.find(v)[2] for v in V_])
                d2 = np.array([kdk.find(v)[2] for v in V_])
                m_ = (d1 < r_) | (d2 < r_)
                Wr_ = np.array([rows["collar"] if b < a else rows["cuff_l" if v[0] * sx > 0 else "cuff_r"]
                                for v, a, b in zip(V_[m_], d1[m_], d2[m_])]).reshape(-1, len(names_all))
            if m_.any():
                p["rigid"] = (m_, Wr_)
                zstats[f"part_{nm}"] = int(m_.sum())
    stats["rigid"] = zstats
    print(f"[spike] rigid zones: {zstats}", flush=True)
    # the rever: its own weights, the drape's under it smoothed along the roll (it followed its
    # nearest drape vertex in t13r-a2, and its roll edge read ragged)
    rv = parts.get("spike_jacket_rever")
    if rv is not None:
        Wr = sr.wrap_weights(rv["bind"], G["jacket"]["W"], G["jacket"]["Tw"])
        rv["W"] = drig.prune(drig.spatial_smooth(Wr, rv["V0"], 0.03, iters=3), 4)
        if fj_neck is not None:
            # the collar (stand and fall, 3-4 cm above the neckline it is bound to) rides the collar's
            # row, blended into the wrap down the gorge: on the wrap alone it swung on the neckline
            # faces like the cuffs (i1: the collar band 3.6-6.2 mm with the arms out)
            fr_ = (rv["bind"]["bc"] * fj_neck[G["jacket"]["Tw"][rv["bind"]["fi"]]]).sum(1)
            fr_ = np.clip((fr_ - 0.15) / 0.7, 0, 1)
            fr_ = fr_ * fr_ * (3 - 2 * fr_)
            rv["blend"] = (fr_, rows["collar"])
            rv["W"] = drig.prune(rv["W"] * (1 - fr_)[:, None] + fr_[:, None] * rows["collar"][None], 4)
            zstats["rever_rigid"] = {"full": int((fr_ > 0.99).sum()), "blend": int(((fr_ > 0.01) & (fr_ <= 0.99)).sum()),
                                     "verts": int(len(fr_))}

    def place(nm, Yd, M_):
        """A made part on its posed drape: wrapped, its rigid vertices skinned with their row."""
        p_ = parts[nm]
        P_ = sr.wrap_apply(p_["bind"], Yd, G[p_["key"]]["Tw"])
        rg_ = p_.get("rigid")
        if rg_ is not None:
            P_[rg_[0]] = sr.skin(p_["V0"][rg_[0]], rg_[1], M_)
        bl_ = p_.get("blend")
        if bl_ is not None:
            f_, row_ = bl_
            m_ = f_ > 0
            P_[m_] += f_[m_, None] * (sr.skin(p_["V0"][m_], np.tile(row_, (int(m_.sum()), 1)), M_) - P_[m_])
        return P_
    # --- T13d: the modelled four-in-hand (suit_tie) in place of the lofted tie: the knot on the
    # collar's row, the blade wrapped on the shirt's drape (blended into the collar's row over the
    # first 8 cm below the knot)
    tie_nm = None
    if O["tie"]["on"] and "spike_shirt_collar" in parts and "tie" in base and fj_neck is not None:
        tie_nm = make_tie(O["tie"], parts, Gs, base, sr, rows["collar"], stats)
    # the layer anchors (rest-referenced order against each under-layer's collider) and the fronts'
    # overlap (the left front over the right, below the break)
    anc = {}
    col0 = {}
    for key in ("shirt", "waistcoat"):
        nm = f"spike_{key}_collider"
        if nm in parts:
            col0[key] = (parts[nm]["V0"], tris_of(parts[nm]["F"]))
    if tie_nm:
        col0["tie"] = (parts[tie_nm]["V0"], tris_of(parts[tie_nm]["F"]))
    for nm, p in tparts.items():
        if nm.endswith("collider"):
            col0["trousers"] = (p["V0"], tris_of(p["F"]), nm)
    if O["anchors"]["on"]:
        for outer, unders in (("waistcoat", ("shirt", "tie", "trousers")), ("jacket", ("shirt", "waistcoat", "trousers"))):
            for u in unders:
                if u in col0:
                    anc[(outer, u)] = Anchors(G[outer]["X0"], col0[u][0], col0[u][1], reach=O["anchors"]["reach_m"],
                                              gap_max=O["anchors"]["gap_max_m"], lat_max=O["anchors"].get("lat_m", 0.0))
    ovl = {}
    if O["overlap"]["on"]:
        for key in ("waistcoat", "jacket"):
            Gx = G[key]
            pn = Gx["panels"]
            isl = np.array([("front" in p) and ("front_r" not in p) for p in pn])
            isr = np.array([("front_r" in p) and ("front" not in p) for p in pn])
            lf = np.nonzero(isl[Gx["Tw"]].all(1))[0]
            rf = np.nonzero(isr[Gx["Tw"]].all(1))[0]
            ovl[key] = [Overlap(Gx["X0"], Gx["Tw"], np.nonzero(isl)[0], rf, reach=O["overlap"]["reach_m"],
                                gap_max=O["overlap"]["gap_max_m"]),
                        Overlap(Gx["X0"], Gx["Tw"], np.nonzero(isr)[0], lf, reach=O["overlap"]["reach_m"],
                                gap_max=O["overlap"]["gap_max_m"])]
            prs = w_pairs if key == "waistcoat" else j_pairs
            pv = sorted({int(v) for pr, _ in prs for v in pr})
            for o_ in ovl[key]:
                o_.ease_near(Gx["X0"], pv, O["overlap"].get("pair_r0_m", 0.03), O["overlap"].get("pair_r1_m", 0.06))
    stats["anchors"] = {f"{a}/{b}": int(len(v.idx)) for (a, b), v in anc.items()}
    stats["overlap"] = {k: [{"verts": int(len(o.a)), "sign": o.sign} for o in v] for k, v in ovl.items()}
    print(f"[spike] anchors {stats['anchors']} overlap {stats['overlap']}", flush=True)
    stats["weights_s"] = round(time.perf_counter() - t, 1)
    print(f"[spike] weights: {stats['weights_s']} s", flush=True)
    stats["holds"] = {"shirt_neck": len(s_neck), "shirt_cuff": len(s_cuff), "shirt_tuck": len(s_tuck),
                      "waistcoat_shoulder": len(w_sh), "waistcoat_pairs": len(w_pairs), "jacket_pairs": len(j_pairs),
                      "jacket_neck": len(j_neck)}
    cache = None
    if A.posed_cache:
        cache = np.load(os.path.join(A.posed_cache, "posed.npz"))
        assert [str(p) for p in cache["poses"]] == poses, "posed cache: another pose set"
    Y = {k: [] for k in G}
    Ms, Acone, foll, per = [], [], [], {}
    hsk = [h for h in rules0.get("helpers", []) if h["type"] == "follow"]
    for ip, pname in enumerate(poses):
        t = time.perf_counter()
        dp.apply_pose(arm, pose_spec(pname), rig_)
        if rt is not None:
            rt.apply(rig_, morphs=False)
        bpy.context.view_layer.update()
        cop = evaluated(body)
        M = skin_mats(arm, names_all)
        Ms.append(M)
        Acone.append([rtc.morph_weights()[c["name"]] for c in cones])
        # the follow rules' inputs (the thigh's swing about the pelvis) for the gain fit
        fr_ = {}
        for h in hsk:
            q = rt.D(h["source"], h.get("source_frame")) if rt else None
            if q is None:
                continue
            d0 = drt.gl_to_bl(h["rest_dir"]).normalized()
            sw = d0.rotation_difference(q @ d0)
            ax, ang = sw.to_axis_angle()
            v = ax * ang
            L_ = drt.gl_to_bl(h["flex_axis"]).normalized()
            N_ = drt.gl_to_bl(h["abd_axis"]).normalized()
            fr_[h["bone"]] = (float(v.dot(L_)), float(v.dot(N_)), np.array(L_), np.array(N_))
        foll.append(fr_)
        Mt = {nm: sr.skin(p["V0"], p["W"], M) for nm, p in tparts.items()}
        tcol = [(Mt[nm], tris_of(p["F"])) for nm, p in tparts.items() if nm.endswith("collider")]
        rec = {}

        def collider_of(key, Yd):
            o_ = bpy.data.objects.get(f"spike_{key}_collider")
            if o_ is None:
                return None
            p_ = parts.get(o_.name)
            return (place(o_.name, Yd, M), tris_of(p_["F"]))

        def hooks_of(key, ip_):
            """The anchors against the posed under-layers (and their posed colliders)."""
            hk = []
            for (outer, u), an in anc.items():
                if outer != key:
                    continue
                if u == "trousers":
                    Vp = Mt[col0["trousers"][2]]
                elif u == "tie":
                    Vp = place(tie_nm, Y["shirt"][ip_], M)
                else:
                    Vp = place(f"spike_{u}_collider", Y[u][ip_], M)
                hk.append((an, Vp))
            return hk
        for key in ("shirt", "waistcoat", "jacket"):
            Gx = G[key]
            Y0 = sr.skin(Gx["X0"], Gx["W"], M)
            if cache is not None:
                Yk = cache[f"Y_{key}"][ip]
            elif pname == "rest":
                Yk = Gx["X0"].copy()
            else:
                shells = list(tcol)
                if key in ("waistcoat", "jacket"):
                    shells.append(collider_of("shirt", Y["shirt"][ip]))
                    if tie_nm and key == "waistcoat":
                        shells.append((place(tie_nm, Y["shirt"][ip], M), tris_of(parts[tie_nm]["F"])))
                if key == "jacket":
                    shells.append(collider_of("waistcoat", Y["waistcoat"][ip]))
                shells = [s_ for s_ in shells if s_ is not None]
                if key == "shirt":
                    shells = []                     # the shirt is the first layer (tucked inside the trousers)
                g_, _ = body_sdf(cop, tris, Y0.min(0) - 0.08, Y0.max(0) + 0.08, XPBD["sdf_h"], shells=shells)
                hk = hooks_of(key, ip)
                hooks = [an.hook(Vp) for an, Vp in hk] + list(ovl.get(key, []))
                rep_ = 0
                for an, Vp in hk:
                    rep_ += an.repair(Y0, Vp)
                if hk:
                    rec[f"{key}_repaired"] = rep_
                if key == "shirt":
                    Yk = pose_solve(Gx, Y0, g_, O["frames_under"],
                                    holds=[(s_neck, Y0[s_neck], O["hold"]["shirt_k"]), (s_cuff, Y0[s_cuff], O["hold"]["shirt_k"])],
                                    pull=(s_tuck, Y0[s_tuck], O["hold"]["tuck_pull"]), self_contact=O["self_contact"],
                                    pinned=pinned["shirt"], fold_deg=O["fold_deg"])
                elif key == "waistcoat":
                    Yk = pose_solve(Gx, Y0, g_, O["frames_under"], holds=[(w_sh, Y0[w_sh], O["hold"]["waistcoat_k"])],
                                    pairs=w_pairs, self_contact=O["self_contact"], pinned=pinned["waistcoat"], hooks=hooks,
                                    fold_deg=O["fold_deg"])
                else:
                    Yk = pose_solve(Gx, Y0, g_, O["frames"], holds=[(j_neck, Y0[j_neck], Gx["P"]["neck_hold_k2"])],
                                    pairs=[(p, Gx["P"]["button_gap_m"]) for p, _ in j_pairs], self_contact=O["self_contact"],
                                    pinned=pinned["jacket"], hooks=hooks, fold_deg=O["fold_deg"])
                real = Layers(cop, tris, shells)
                pu = O["push"] if key == "jacket" else O["push_under"]
                Yk, moved = push_out(Yk, Gx["Tw"], real, pu["clear_m"], pu["smooth_iters"])
                Yk[pinned[key]] = Y0[pinned[key]]
                free_ = ~pinned[key]
                for _ in range(3):
                    for h_ in hooks:
                        h_(Yk, free_)
                rec[f"{key}_inside_hooked"] = inside_count(Yk, real)
                if O.get("final_push", True):
                    Y1_ = Yk.copy()
                    Yk, _ = push_out(Yk, Gx["Tw"], real, pu["clear_m"], 0)
                    Yk[pinned[key]] = Y1_[pinned[key]]
                if O["fold_deg"] and O.get("fold_fix_rounds", 0):
                    # last: the fold limit (the push-out in the armpit's crevice folds an edge back over;
                    # i3 offline: the limit alone moves 35-50 vertices <= 9 mm, into body the build deletes)
                    rec[f"{key}_unfolded"] = fold_fix(Gx, Yk, free_, real, pu, hooks, O["fold_fix_rounds"])
                rec[f"{key}_pushed"] = moved
                rec[f"{key}_inside"] = inside_count(Yk, real)
                rec[f"{key}_inside_body"] = inside_count(Yk, Layers(cop, tris, []))
                if hk:
                    rec[f"{key}_below_anchor"] = int(sum(an.count(Yk, Vp, 0.0005) for an, Vp in hk))
                if key in ovl:
                    rec[f"{key}_overlap_through"] = sum(o.count(Yk) for o in ovl[key])
            Y[key].append(Yk)
        rec["s"] = round(time.perf_counter() - t, 1)
        per[pname] = rec
        print(f"[posed] {pname}: {rec}", flush=True)
    Ms, Acone = np.array(Ms), np.array(Acone)
    for k_ in Y:
        Y[k_] = np.array(Y[k_])
    stats["sim_s"] = round(sum(r["s"] for r in per.values()), 1)
    if cache is None:
        np.savez_compressed(os.path.join(A.out_dir, "posed.npz"), poses=np.array(poses),
                            **{f"Y_{k}": v.astype(np.float64) for k, v in Y.items()})
    import hashlib
    stats["hash"] = {k: hashlib.sha256(np.ascontiguousarray(v).tobytes()).hexdigest()[:8] for k, v in Y.items()}

    # --- the skirt bones' follow gains, fitted to the simulated skirt
    jn = names_all
    skirt_b = [h["bone"] for h in hsk if h["bone"] in jn]
    gains = {h["bone"]: dict(h["gain"]) for h in hsk}
    Bd = arm.data.bones

    def skirt_M(Mk, k, gn):
        Mk = Mk.copy()
        Mp = Mk[jn.index("pelvis")]
        Rp = Mp[:3, :3]
        for b in skirt_b:
            fl, ab, L_, N_ = foll[k][b]
            Mk[jn.index(b)] = sr.follow_mat(gn[b], fl, ab, L_, N_, Rp, Mp, np.array(Bd[b].head_local))
        return Mk
    Wj = Gj["W"]
    sk_cols = [jn.index(b) for b in skirt_b]
    sv = np.nonzero(Wj[:, sk_cols].sum(1) > 0.05)[0]
    if O["gain_fit"] and skirt_b:
        Xs = Gj["X0"][sv]
        Wns = Wj[sv].copy()
        Wns[:, sk_cols] = 0.0
        base_k = [sr.skin(Xs, Wns, Ms[k]) - Y["jacket"][k][sv] for k in range(K)]
        Xsh = np.concatenate([Xs, np.ones((len(Xs), 1))], 1)

        def err(gn):
            e = 0.0
            for k in range(K):
                Mk = skirt_M(Ms[k], k, gn)
                r_ = base_k[k].copy()
                for b, c in zip(skirt_b, sk_cols):
                    r_ += Wj[sv, c][:, None] * (Xsh @ Mk[c][:3, :].T)
                e += float((r_ ** 2).sum())
            return e
        e0 = err(gains)
        grid = np.linspace(-0.2, 1.6, 19)
        for sweep in range(3):
            for b in skirt_b:
                for key_g in ("flex+", "flex-", "abd+", "abd-"):
                    best = (err(gains), gains[b][key_g])
                    for v in grid:
                        gains[b][key_g] = float(v)
                        e = err(gains)
                        if e < best[0]:
                            best = (e, float(v))
                    gains[b][key_g] = best[1]
            grid = np.linspace(-0.2, 1.6, 37)
        stats["skirt_gain_fit"] = {"rms_mm_before": round(float(np.sqrt(e0 / (K * max(len(sv), 1)))) * 1000, 2),
                                   "rms_mm_after": round(float(np.sqrt(err(gains) / (K * max(len(sv), 1)))) * 1000, 2),
                                   "verts": int(len(sv)), "gains": gains,
                                   "lofted": {h["bone"]: h["gain"] for h in hsk}}
        for k in range(K):
            Ms[k] = skirt_M(Ms[k], k, gains)

    # --- T13b's free jacket bones (Dem Bones), refit on this set: are they drivable?
    if O["dem_bones_diag"]:
        t = time.perf_counter()
        X0j = Gj["X0"]
        kind_w = Gj["kind"]
        zw = float(O["waist_z"])
        lab = np.full(len(X0j), -1)
        xl = X0j[:, 0] >= 0
        isf = np.isin(kind_w, ["front", "front_r"])
        iss = np.isin(kind_w, ["side", "side_r"])
        isb = np.isin(kind_w, ["back", "back_r"])
        low = X0j[:, 2] < zw
        for j, m in enumerate([low & (isf | (iss & (X0j[:, 1] < 0))) & xl, low & (isf | (iss & (X0j[:, 1] < 0))) & ~xl,
                               low & (isb | (iss & (X0j[:, 1] >= 0))) & xl, low & (isb | (iss & (X0j[:, 1] >= 0))) & ~xl,
                               ~low & isf & xl, ~low & isf & ~xl, ~low & iss & xl, ~low & iss & ~xl]):
            lab[m] = j
        jnames = ["skirt_front_l", "skirt_front_r", "skirt_back_l", "skirt_back_r", "front_l", "front_r", "side_l", "side_r"]
        allow = ~np.isin(kind_w, ["top_sleeve", "top_sleeve_r", "under_sleeve", "under_sleeve_r"])
        fit = sr.fit_bones(X0j, Y["jacket"], Wj, Ms, nj=O["jacket_bones"], iters=O["fit_iters"], groups=lab, allow=allow)
        drivers = ["pelvis", "spine_01", "spine_02", "spine_03", "thigh_l", "thigh_r", "upperarm_l", "upperarm_r",
                   "clavicle_l", "clavicle_r"]
        feats = []
        for pname in poses:
            dp.apply_pose(arm, pose_spec(pname), rig_)
            feats.append(np.concatenate([local_rot(arm, n_) for n_ in drivers]))
        feats = np.array(feats)
        dcols = {n_: [3 * i_ + c for c in range(3)] for i_, n_ in enumerate(drivers)}
        drv = {}
        for j, jn_ in enumerate(jnames):
            sd = jn_[-1]
            par = "pelvis" if jn_.startswith("skirt") else "spine_03"
            src = {"skirt": [f"thigh_{sd}", "pelvis"], "front": [f"upperarm_{sd}", f"clavicle_{sd}", "spine_03"],
                   "side": [f"upperarm_{sd}", f"clavicle_{sd}"]}[jn_.split("_")[0]]
            fc = feats[:, sum((dcols[n_] for n_ in src), [])]
            pi = jn.index(par)
            cj = fit["centres"][j]
            coef, rel, pred = sr.drive(fit["T"][:, j], Ms[:, pi], fc, lam=O["drive_lam"], centre=cj)
            loo = []
            for i in range(K):
                m = np.arange(K) != i
                c_, _, _ = sr.drive(fit["T"][m, j], Ms[m, pi], fc[m], lam=O["drive_lam"], centre=cj)
                loo.append(np.concatenate([fc[i], [1.0]]) @ c_ - rel[i])
            loo = np.abs(np.array(loo))
            drv[jn_] = {"loo_rot_deg_p90": round(float(np.degrees(np.percentile(loo[:, :3].max(1), 90))), 1),
                        "loo_move_mm_p90": round(float(np.percentile(loo[:, 3:].max(1), 90)) * 1000, 1),
                        "range_rot_deg_p90": round(float(np.degrees(np.percentile(np.abs(rel[:, :3]).max(1), 90))), 1),
                        "range_move_mm_p90": round(float(np.percentile(np.abs(rel[:, 3:]).max(1), 90)) * 1000, 1)}
            drv[jn_]["drivable"] = bool(drv[jn_]["loo_rot_deg_p90"] < 0.5 * max(drv[jn_]["range_rot_deg_p90"], 1e-6))
        stats["dem_bones_diag"] = {"err": fit["err"], "drive": drv, "s": round(time.perf_counter() - t, 1)}
        dp.reset(arm)
    # --- pose-space correctives per layer, over the suit's cones
    t = time.perf_counter()
    S, Dres, rt_Y, loo_rms, masks = {}, {}, {}, {}, {}
    Yfit = {k_: Y[k_] for k_ in Y}     # the fit's targets: the sim, the bound under-layers on the jacket
    BU = O.get("bind_under") or {}
    for key in ("jacket", "waistcoat", "shirt"):
        Gx = G[key]
        X0 = Gx["X0"]
        if key == "waistcoat":
            W_pre = {k_: G[k_]["W"].copy() for k_ in G}
        if key == "waistcoat" and BU.get("on"):
            bu, stats["bind_under"] = bind_under(G, Y, rt_Y["jacket"], K, BU, pinned)
            for k_, (T_, W_, f_) in bu.items():
                Yfit[k_] = list(T_)
                G[k_]["W"] = W_
                G[k_]["bind_f"] = f_
            print(f"[spike] bind under: {stats['bind_under']}", flush=True)
        D = np.stack([sr.unskin(Gx["W"], Ms[k], Yfit[key][k], X0) for k in range(K)])
        mask = cone_masks(cones, X0, arm) if O["cone_masks"] else np.ones((len(X0), len(cones)))
        S[key] = sr.fit_shapes(D, Acone, mask, lam=O["lam"])
        Dres[key] = D
        masks[key] = mask
        rt_Y[key] = np.stack([sr.skin(X0 + sr.apply_shapes(S[key], Acone[k]), Gx["W"], Ms[k]) for k in range(K)])
        # leave-one-out: each pose predicted from the shapes fitted without it
        lo_ = []
        for k in range(K):
            if poses[k] == "rest":
                lo_.append(0.0)
                continue
            m = np.arange(K) != k
            Sk = sr.fit_shapes(D[m], Acone[m], mask, lam=O["lam"])
            Yl = sr.skin(X0 + sr.apply_shapes(Sk, Acone[k]), Gx["W"], Ms[k])
            lo_.append(float(np.sqrt((np.linalg.norm(Yl - Yfit[key][k], axis=1) ** 2).mean())) * 1000)
        loo_rms[key] = lo_
    stats["correctives_s"] = round(time.perf_counter() - t, 1)
    print(f"[spike] correctives: {stats['correctives_s']} s", flush=True)
    CF = O.get("constrain") or {}
    if CF.get("on"):
        t = time.perf_counter()
        cops = []
        for k, pname in enumerate(poses):
            dp.apply_pose(arm, pose_spec(pname), rig_)
            if rt is not None:
                rt.apply(rig_, morphs=False)
            bpy.context.view_layer.update()
            cops.append(np.array(evaluated(body)))
        if CF.get("dump"):
            import pickle
            pk = {"G": {k_: {"X0": G[k_]["X0"], "W": G[k_]["W"], "Tw": G[k_]["Tw"]} for k_ in G},
                  "S": S, "Dres": Dres, "masks": masks, "Acone": Acone, "Ms": Ms, "lam": O["lam"],
                  "rt_Y": rt_Y, "Y": Y, "cops": cops, "pinned": pinned, "BU": BU, "W_pre": W_pre, "poses": poses, "tris": tris, "tie_nm": tie_nm, "CF": CF,
                  "anc": {k_: {"idx": a_.idx, "fi": a_.fi, "bc": a_.bc, "T": a_.T, "sign": a_.sign,
                               "lat_max": a_.lat_max, "h0": a_.h0, "gap": a_.gap} for k_, a_ in anc.items()},
                  "col0": col0,
                  "parts": {n_: {k2: v2 for k2, v2 in p_.items() if k2 in ("V0", "F", "W", "bind", "rigid", "blend", "key")}
                            for n_, p_ in parts.items()},
                  "tparts": {n_: {k2: v2 for k2, v2 in p_.items() if k2 in ("V0", "F", "W")} for n_, p_ in tparts.items()}}
            with open(os.path.join(A.out_dir, "constrain_in.pkl"), "wb") as f_:
                pickle.dump(pk, f_)
        stats["constrain"], sunk = constrain_fit(G, S, Dres, masks, Acone, Ms, O["lam"], rt_Y, anc, col0, parts,
                                                 tparts, place, cops, tris, CF, tie_nm=tie_nm)
        stats["constrain"]["s"] = round(time.perf_counter() - t, 1)
    fit_Y = {k_: v_ for k_, v_ in rt_Y.items()}      # the fit as fitted (before the tuck)
    tuckf = dict(sunk) if CF.get("on") else {}        # a sunk layer's export base is its sunk rest drape
    if O["tuck"]["on"]:
        tuckf, stats["tuck"] = tuck_layers(G, O["tuck"])
        for key in tuckf:
            Gx = G[key]
            rt_Y[key] = np.stack([sr.skin(Gx["X0"] + sr.apply_shapes(S[key], Acone[k]), Gx["W"], Ms[k]) for k in range(K)])
        print(f"[spike] tuck: {stats['tuck']}", flush=True)
    # --- the runtime per pose: fit, penetration, collar, shoulder line, hinges
    Bn = arm.data.bones
    shoulders = [np.array(Bn[f"upperarm_{s}"].head_local) for s in ("l", "r")]
    sh_zone = np.min([np.linalg.norm(Gj["X0"] - s_, axis=1) for s_ in shoulders], 0) < 0.12
    sh_zone &= Gj["X0"][:, 2] > np.mean([s_[2] for s_ in shoulders]) - 0.02
    tri_j = Gj["Tw"]
    res = {}
    for k, pname in enumerate(poses):
        dp.apply_pose(arm, pose_spec(pname), rig_)
        if rt is not None:
            rt.apply(rig_, morphs=False)
        bpy.context.view_layer.update()
        cop = evaluated(body)
        Mt = {nm: sr.skin(p["V0"], p["W"], Ms[k]) for nm, p in tparts.items()}
        tcol = [(Mt[nm], tris_of(p["F"])) for nm, p in tparts.items() if nm.endswith("collider")]
        r = {}
        for key in ("shirt", "waistcoat", "jacket"):
            e = np.linalg.norm(fit_Y[key][k] - Y[key][k], axis=1)
            lbs = np.linalg.norm(sr.skin(G[key]["X0"], G[key]["W"], Ms[k]) - Y[key][k], axis=1)
            r[key] = {"lbs_rms_mm": round(float(np.sqrt((lbs ** 2).mean())) * 1000, 1),
                      "fit_rms_mm": round(float(np.sqrt((e ** 2).mean())) * 1000, 1),
                      "fit_p99_mm": round(float(np.percentile(e, 99)) * 1000, 1),
                      "loo_rms_mm": round(loo_rms[key][k], 1)}
            if Yfit[key] is not Y[key]:
                et = np.linalg.norm(fit_Y[key][k] - Yfit[key][k], axis=1)
                r[key]["fit_rms_target_mm"] = round(float(np.sqrt((et ** 2).mean())) * 1000, 1)

        def coll(key, Yd):
            p_ = parts.get(f"spike_{key}_collider")
            return (place(f"spike_{key}_collider", Yd, Ms[k]), tris_of(p_["F"]))
        for tag, src in (("sim", Y), ("rt", rt_Y)):
            sh_c, wc_c = coll("shirt", src["shirt"][k]), coll("waistcoat", src["waistcoat"][k])
            Lj = Layers(cop, tris, tcol + [sh_c, wc_c])
            Lw_ = Layers(cop, tris, tcol + [sh_c])
            r[f"inside_{tag}"] = {"jacket": inside_count(src["jacket"][k], Lj),
                                  "waistcoat": inside_count(src["waistcoat"][k], Lw_)}
            if tag == "rt" and "waistcoat" in tuckf:
                # the waistcoat where it shows (not sunk): its covered part goes under the shirt and
                # the body on purpose, hidden under the jacket (and the body there hidden by hide_body)
                vis = tuckf["waistcoat"] < 0.5
                r["inside_rt_visible"] = {"jacket": r["inside_rt"]["jacket"],
                                          "waistcoat": inside_count(src["waistcoat"][k][vis], Lw_)}
            # the collar: the shirt collar's top above the rever's at the CB, in the neck's frame
            Mn = np.linalg.inv(Ms[k][jn.index("neck_01")])
            pc = parts.get("spike_shirt_collar")
            prv = parts.get("spike_jacket_rever")
            if pc is not None and prv is not None:
                Pc = place("spike_shirt_collar", src["shirt"][k], Ms[k]) @ Mn[:3, :3].T + Mn[:3, 3]
                Pr = place("spike_jacket_rever", src["jacket"][k], Ms[k]) @ Mn[:3, :3].T + Mn[:3, 3]
                ms = (np.abs(Pc[:, 0]) < 0.01) & (Pc[:, 1] > 0.0)
                mr = (np.abs(Pr[:, 0]) < 0.01) & (Pr[:, 1] > 0.0)
                if ms.any() and mr.any():
                    r[f"collar_mm_{tag}"] = round(float(Pc[ms, 2].max() - Pr[mr, 2].max()) * 1000, 1)
            # the shoulder line: how far the jacket's shoulder stands above the simulated one
            dz = (src["jacket"][k][sh_zone] - Y["jacket"][k][sh_zone]) @ np.array([0, 0, 1.0])
            r[f"shoulder_rise_mm_{tag}"] = round(float(dz.max()) * 1000, 1)
        lb = sr.skin(Gj["X0"], Wj, Ms[k])
        r["shoulder_rise_mm_lbs"] = round(float(((lb[sh_zone] - Y["jacket"][k][sh_zone])[:, 2]).max()) * 1000, 1)
        hs, _ = seam_report(Gj, Y["jacket"][k], O["hinge_deg"])
        hr, _ = seam_report(Gj, rt_Y["jacket"][k], O["hinge_deg"])
        r["hinges_sim"], r["hinges_rt"] = hs, {kk: hr[kk] for kk in ("over_20", "p99_deg", "max_deg")}
        r["sim"] = per[pname]
        res[pname] = r
        print(f"[posed-rt] {pname}: fit {r['jacket']['fit_rms_mm']} loo {r['jacket']['loo_rms_mm']} "
              f"inside_rt {r['inside_rt']} collar {r.get('collar_mm_rt')} shoulder {r['shoulder_rise_mm_rt']} "
              f"(lbs {r['shoulder_rise_mm_lbs']}) folds {list(hs['folds'])}", flush=True)
    stats["poses"] = res
    # --- T13d: the faces the layers over them hide in every pose are culled (budget; what is not
    # drawn cannot be pierced), then the runtime penetration is counted against what is kept
    keep_faces = {}
    if O["cull"]["on"]:
        keep_faces = cull_hidden(O["cull"], poses, Ms, rt_Y, G, parts, tparts, place, arm, rig_, rt, body, tris,
                                 stats, res, anc=anc, col0=col0)
    np.savez_compressed(os.path.join(A.out_dir, "rig.npz"), poses=np.array(poses), names=np.array(names_all),
                        Ms=Ms, A=Acone, **{f"W_{k}": G[k]["W"] for k in G}, **{f"S_{k}": S[k].astype(np.float32) for k in G},
                        **{f"X0_{k}": G[k]["X0"] for k in G}, **{f"T_{k}": G[k]["Tw"] for k in G})
    with open(os.path.join(A.out_dir, "suit_rules.json"), "w") as f:
        json.dump({"morphs": [{k: v for k, v in c.items() if not k.startswith("_")} for c in cones],
                   "follow_gains": gains}, f, indent=1)
    # --- export: each made part as a skinned mesh with its corrective shape keys (one per cone,
    # named as the rule), fitted on the part itself (its wrap of each pose's drape), so the engine's
    # LBS + morphs reproduce the drape-level runtime; the trousers skinned only
    t = time.perf_counter()
    exp = {}
    M_id = np.tile(np.eye(4), (len(names_all), 1, 1))
    from character import suit_wrinkle as swk
    Gw = swk.group_weights(cones, Acone)
    wr_acc = {}                       # material -> ([UVc], [vals]) over every part using it
    wr_stats = {}
    for nm, p in parts.items():
        if nm.endswith("collider"):
            continue
        key = p["key"]
        Gx = G[key]
        Wm = p["W"] if "W" in p else drig.prune(sr.wrap_weights(p["bind"], Gx["W"], Gx["Tw"]), 4)
        if p.get("rigid") is not None:
            Wm = Wm.copy()
            Wm[p["rigid"][0]] = p["rigid"][1]
        V0 = p["V0"]
        Ysrc = rt_Y if CF.get("on") else Yfit
        # the base: the part on its (tucked / sunk) rest drape. With the constraint the shapes are fitted
        # on the runtime from that base; the tuck's shapes were fitted on the untucked part
        Vb = place(nm, Gx["X0"], M_id) if key in tuckf else V0
        D = np.stack([sr.unskin(Wm, Ms[k], place(nm, Ysrc[key][k], Ms[k]), Vb if CF.get("on") else V0)
                      for k in range(K)])
        Sm = sr.fit_shapes(D, Acone, cone_masks(cones, V0, arm) if O["cone_masks"] else np.ones((len(V0), len(cones))),
                           lam=O["lam"])
        dev = [float(np.linalg.norm(sr.skin(Vb + sr.apply_shapes(Sm, Acone[k]), Wm, Ms[k])
                                    - place(nm, rt_Y[key][k], Ms[k]), axis=1).max()) for k in range(K)]
        o_ = rig_copy(nm)
        drig.write(o_, Wm, names_all)
        o_.data.vertices.foreach_set("co", Vb.astype(np.float32).ravel())
        o_.shape_key_add(name="Basis")
        kept_ = 0
        for c, Sc in zip(cones, Sm):
            mx = float(np.linalg.norm(Sc, axis=1).max())
            if mx < 2e-4:
                continue
            kb = o_.shape_key_add(name=c["name"], from_mix=False)
            kb.data.foreach_set("co", (Vb + Sc).astype(np.float32).ravel())
            kept_ += 1
        o_.hide_render = True
        exp[nm] = {"verts": len(V0), "shape_keys": kept_, "max_dev_vs_drape_runtime_mm": round(max(dev) * 1000, 2)}
        if O["wrinkle"] and o_.data.uv_layers.active is not None:
            # the fold the shapes average away: sim normal minus runtime normal, in rest space
            me_ = o_.data
            me_.calc_loop_triangles()
            nt_ = len(me_.loop_triangles)
            lt_ = np.empty(nt_ * 3, np.int64)
            vt_ = np.empty(nt_ * 3, np.int64)
            mi_ = np.empty(nt_, np.int64)
            me_.loop_triangles.foreach_get("loops", lt_)
            me_.loop_triangles.foreach_get("vertices", vt_)
            me_.loop_triangles.foreach_get("material_index", mi_)
            uv_ = np.empty(len(me_.loops) * 2)
            me_.uv_layers.active.data.foreach_get("uv", uv_)
            UVc_ = uv_.reshape(-1, 2)[lt_].reshape(-1, 3, 2)
            Ft_ = vt_.reshape(-1, 3)
            Ysim_ = [place(nm, Y[key][k], Ms[k]) for k in range(K)]
            Yrt_ = [sr.skin(V0 + sr.apply_shapes(Sm, Acone[k]), Wm, Ms[k]) for k in range(K)]
            dN_ = swk.part_deltas(V0, Ft_, Wm, [Ms[k] for k in range(K)], Ysim_, Yrt_)
            G3_ = swk.fit_groups(dN_, Gw, swk.side_mix(V0[:, 0]), O["wrinkle_lam"])
            vals_ = swk.corner_values(G3_, V0, Ft_, UVc_)
            mag_ = np.linalg.norm(dN_, axis=2)
            wr_stats[nm] = {"dN_p95": round(float(np.percentile(mag_, 95)), 3),
                            "dN_p99": round(float(np.percentile(mag_, 99)), 3),
                            "G_p99": round(float(np.percentile(np.abs(vals_), 99)), 3),
                            "clipped_frac": round(float((np.abs(vals_) > swk.RANGE).mean()), 4)}
            for j_ in np.unique(mi_):
                mt_ = me_.materials[int(j_)] if j_ < len(me_.materials) else None
                if mt_ is None:
                    continue
                acc_ = wr_acc.setdefault(mt_.name, ([], []))
                acc_[0].append(UVc_[mi_ == j_])
                acc_[1].append(vals_[mi_ == j_])
        if nm in keep_faces:
            from character import suit_cull as sc_
            exp[nm]["faces"] = sc_.drop_faces(o_, keep_faces[nm])
    for nm, p in tparts.items():
        if nm.endswith("collider"):
            continue
        o_ = rig_copy(nm)
        drig.write(o_, p["W"], names_all)
        o_.hide_render = True
        exp[nm] = {"verts": len(p["V0"]), "shape_keys": 0}
        if nm in keep_faces:
            from character import suit_cull as sc_
            exp[nm]["faces"] = sc_.drop_faces(o_, keep_faces[nm])
    if keep_faces and O["cull"].get("lods"):
        exp["lods"] = culled_lods(O["cull"]["lods"])
        print(f"[spike] culled lods: {exp['lods']}", flush=True)
    if wr_acc:
        side_ = {"range": swk.RANGE, "groups": list(swk.GROUPS), "materials": {}, "poses": list(poses)}
        for mt, (uvs_, vs_) in sorted(wr_acc.items()):
            px_ = O["wrinkle_px"].get(mt, O["wrinkle_px"]["default"])
            layers_, cov_ = swk.bake_material(np.concatenate(uvs_), np.concatenate(vs_), px_)
            files_ = []
            for i_, L_ in enumerate(layers_):
                fn_ = f"suit_wrinkle_{mt}_{i_}.png"
                swk.write_png(os.path.join(A.out_dir, fn_), L_)
                files_.append(fn_)
            side_["materials"][mt] = files_
            wr_stats[mt] = {"px": px_, "coverage": round(cov_, 3)}
        with open(os.path.join(A.out_dir, "suit_wrinkle.json"), "w") as f:
            json.dump(side_, f, indent=1)
        stats["wrinkle"] = wr_stats
        print(f"[spike] wrinkle: {wr_stats}", flush=True)
    stats["export"] = {"parts": exp, "s": round(time.perf_counter() - t, 1)}
    print(f"[spike] export: {stats['export']}", flush=True)
    with open(os.path.join(A.out_dir, "spike_stats.json"), "w") as f:
        json.dump(stats, f, indent=1, default=float)
    stage_rig(bpy.context.scene)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(A.out_dir, "spike.blend"), compress=True)
    with open(os.path.join(A.out_dir, "spike_stats.json"), "w") as f:
        json.dump(stats, f, indent=1, default=float)
    if A.no_render:
        return
    # --- frames: per pose the simulated suit and the runtime (made parts wrapped on the drapes)
    t = time.perf_counter()
    for nm in list(parts) + list(tparts):
        o_ = bpy.data.objects.get(nm)
        if o_ is not None:
            o_.hide_render = True
    lbs_set = set(O["lbs_renders"])
    for k, pname in enumerate(poses):
        dp.apply_pose(arm, pose_spec(pname), rig_)
        if rt is not None:
            rt.apply(rig_, morphs=False)
        bpy.context.view_layer.update()
        cop = evaluated(body)
        bo = mesh_object(f"p_{pname}_body", cop, tris)
        tos = [mesh_object(f"p_{pname}_{nm}", sr.skin(p["V0"], p["W"], Ms[k]), p["F"]) for nm, p in tparts.items()
               if not nm.endswith("collider")]
        extra = [base[x].name for x in ("shoes", "tie") if x in base and not (x == "tie" and tie_nm)]
        tags = [("sim", Y), ("rt", rt_Y)]
        if pname in lbs_set:
            tags.append(("lbs", {key: {k: sr.skin(G[key]["X0"], G[key]["W"], Ms[k])} for key in G}))
        for tag, src in tags:
            obs_ = []
            for nm, p in parts.items():
                if nm.endswith("collider"):
                    continue
                obs_.append(mesh_object(f"p_{pname}_{tag}_{nm}", place(nm, src[p["key"]][k], Ms[k]),
                                        p["F"]))
            for o_ in obs_ + tos:
                if "jacket" not in o_.name:
                    MADE_SLOTS[o_.name] = []
            show = [bo.name] + [o_.name for o_ in obs_ + tos] + extra
            render_views(A.out_dir, f"{pname}_{tag}", show, ["front", "three_quarter"], res=O["render_res"])
            if tag == "sim":
                for cn, (bn, off, az_c, sc_c) in O["close"].items():
                    hd = arm.matrix_world @ arm.pose.bones[bn].head
                    render_views(A.out_dir, f"{pname}_{tag}_{cn}", show, ["c"], res=O["render_res"],
                                 target=tuple(np.array(hd) + np.array(off)), scale=sc_c, az_override=az_c, cam_dz=0.0)
            for o_ in obs_:
                bpy.data.objects.remove(o_, do_unlink=True)
        for o_ in [bo] + tos:
            bpy.data.objects.remove(o_, do_unlink=True)
    stats["render_s"] = round(time.perf_counter() - t, 1)
    with open(os.path.join(A.out_dir, "spike_stats.json"), "w") as f:
        json.dump(stats, f, indent=1, default=float)


def main():
    if A.posed:
        return main_posed(sp.merge(POSED, _cli_opts()))
    if A.trousers:
        return main_trousers(sp.merge(TROUSERS, _cli_opts()))
    if A.waistcoat:
        return main_waistcoat(sp.merge(WAISTCOAT, _cli_opts()))
    if A.shirt:
        return main_shirt(sp.merge(SHIRT, _cli_opts()))
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
