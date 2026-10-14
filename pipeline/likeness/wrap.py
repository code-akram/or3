"""Wrap the character's base mesh onto a target head surface: a per-vertex offset field for the
build's optional face layer (blender/character/head_fan.py).

Inputs: the base mesh dumped by the build (head_fan dump_base: coords, polygons, vertex groups,
eye centres), a landmark embedding on that base mesh (clay_views.py embed: MediaPipe index ->
triangle + barycentrics), and a target mesh with its own embedding for the same landmark set
(for a FLAME fit: the fitted neutral mesh and a MediaPipe landmark embedding for FLAME).

Steps:
  1. similarity-align the target to the base on the shared landmarks (Umeyama; the base keeps
     its scale unless --metric);
  2. coarse: thin-plate RBF of the landmark offsets, with zero-offset anchors on the neck and
     shoulders, over the head region;
  3. fine: a few rounds of closest-point projection of the trusted face/scalp region onto the
     target surface, each displacement field Laplacian-smoothed over the base mesh before it is
     applied (non-rigid ICP); ears, lips' inner rows and the eye sockets follow by smoothing;
  4. helpers: eye, teeth and tongue helpers move rigidly with the field at their centroids (eyes
     stay spheres), and the skin around each eyeball (the lids) moves with it (eye cores); hair,
     eyelash helpers and joint cubes take the field per vertex (inverse-distance from the nearest
     skin vertices);
  5. optional left/right symmetrisation; a smooth fade to zero from the jaw to the neck.

    python -I wrap.py --base base.npz --base-embedding emb.npz --target fit.obj \
        --target-embedding mp_embedding.npz [--target-frame flame] [--target-mask masks.npz] \
        --out face_delta.npz
    python -I wrap.py --selftest --base base.npz   # recovers a known deformation of the base head
"""

import argparse
import sys
import time
from pathlib import Path

import numpy as np
from scipy.interpolate import RBFInterpolator
from scipy.sparse import coo_matrix, diags
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
import containment  # noqa: E402

RIGID_HELPERS = ("helper-l-eye", "helper-r-eye", "helper-upper-teeth", "helper-lower-teeth", "helper-tongue")
FIELD_HELPERS = ("helper-hair", "helper-l-eyelashes-1", "helper-l-eyelashes-2", "helper-r-eyelashes-1",
                 "helper-r-eyelashes-2", "JointCubes")


# ----------------------------------------------------------------------------------- base mesh
class Base:
    def __init__(self, path):
        d = np.load(path)
        self.co = np.asarray(d["co"], np.float64)
        self.names = [str(n) for n in d["group_names"]]
        self.W = d["group_weights"].astype(np.float32)
        lv, ls, lt = d["loop_verts"], d["poly_start"], d["poly_total"]
        self.polys = [lv[s:s + t] for s, t in zip(ls, lt)]
        self.eye_l, self.eye_r = np.asarray(d["eye_l"]), np.asarray(d["eye_r"])
        self.helper = self.group("HelperGeometry") > 0
        self.skin = ~self.helper
        # edges of the skin polygons, for the Laplacian
        e = []
        for p in self.polys:
            if self.helper[p].any():
                continue
            e += [(p[k], p[(k + 1) % len(p)]) for k in range(len(p))]
        e = np.array(e)
        n = len(self.co)
        A = coo_matrix((np.ones(len(e) * 2), (np.r_[e[:, 0], e[:, 1]], np.r_[e[:, 1], e[:, 0]])), shape=(n, n)).tocsr()
        A.data[:] = 1.0
        deg = np.asarray(A.sum(1)).ravel()
        self.avg = diags(1.0 / np.maximum(deg, 1)) @ A          # neighbour average
        self.has_nbr = deg > 0
        self.tris = np.array([(p[0], p[k], p[k + 1]) for p in self.polys if not self.helper[p].any()
                              for k in range(1, len(p) - 1)])

    def group(self, name):
        return self.W[:, self.names.index(name)] if name in self.names else np.zeros(len(self.co), np.float32)

    def normals(self, co):
        t = self.tris
        fn = np.cross(co[t[:, 1]] - co[t[:, 0]], co[t[:, 2]] - co[t[:, 0]])
        vn = np.zeros_like(co)
        for k in range(3):
            np.add.at(vn, t[:, k], fn)
        return vn / np.maximum(np.linalg.norm(vn, axis=1, keepdims=True), 1e-12)

    def smooth(self, f, iters, mask=None):
        """Laplacian smoothing of a per-vertex field over the skin graph (helpers untouched)."""
        g = f.copy()
        for _ in range(iters):
            s = self.avg @ g
            upd = self.has_nbr if mask is None else (self.has_nbr & mask)
            g[upd] = 0.5 * g[upd] + 0.5 * s[upd]
        return g


def embedded_points(co, tri, bary):
    return np.einsum("lk,lkd->ld", bary, co[tri])


# ----------------------------------------------------------------------------------- target mesh
def read_obj(path):
    v, f = [], []
    with open(path) as fh:
        for line in fh:
            if line.startswith("v "):
                v.append([float(x) for x in line.split()[1:4]])
            elif line.startswith("f "):
                idx = [int(t.split("/")[0]) - 1 for t in line.split()[1:]]
                f += [(idx[0], idx[k], idx[k + 1]) for k in range(1, len(idx) - 1)]
    return np.array(v, np.float64), np.array(f, np.int64)


FLAME_TO_BLENDER = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], np.float64)   # y-up/z-fwd -> z-up/-y-fwd


def umeyama(src, dst, scale=True):
    ms, md = src.mean(0), dst.mean(0)
    s0, d0 = src - ms, dst - md
    U, S, Vt = np.linalg.svd(d0.T @ s0 / len(src))
    D = np.diag([1, 1, np.sign(np.linalg.det(U @ Vt))])
    R = U @ D @ Vt
    s = np.trace(np.diag(S) @ D) / (s0 ** 2).sum(1).mean() if scale else 1.0
    return s, R, md - s * R @ ms


def closest_on_mesh(V, F, P, k=12):
    """Closest points on triangle mesh (V, F) to points P, via candidate triangles around the k
    nearest vertices. Returns points, distances, triangle ids."""
    used = np.unique(F)                                 # only vertices of F (F may be a subset of faces)
    tree = cKDTree(V[used])
    _, nn = tree.query(P, k=min(k, len(used)))
    vf = [[] for _ in range(len(V))]
    for fi, t in enumerate(F):
        for x in t:
            vf[x].append(fi)
    best_p = np.zeros_like(P)
    best_d = np.full(len(P), np.inf)
    best_f = np.zeros(len(P), np.int64)
    for i in range(len(P)):
        cand = np.unique(np.concatenate([np.asarray(vf[j], np.int64) for j in used[nn[i]]]))
        q, d = point_tri(P[i], V[F[cand]])
        j = int(np.argmin(d))
        best_p[i], best_d[i], best_f[i] = q[j], d[j], cand[j]
    return best_p, best_d, best_f


def rim_faces(F):
    """Faces of F touching a vertex on F's open boundary (an edge used by one face only)."""
    e = np.sort(np.r_[F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]], axis=1)
    uniq, cnt = np.unique(e, axis=0, return_counts=True)
    bv = np.zeros(F.max() + 1, bool)
    bv[uniq[cnt == 1].ravel()] = True
    return bv[F].any(1)


def point_tri(p, T):
    """Closest points on triangles T (m, 3, 3) to point p (vectorised Ericson)."""
    a, b, c = T[:, 0], T[:, 1], T[:, 2]
    ab, ac, ap = b - a, c - a, p - a
    d1, d2 = (ab * ap).sum(1), (ac * ap).sum(1)
    bp = p - b
    d3, d4 = (ab * bp).sum(1), (ac * bp).sum(1)
    cp = p - c
    d5, d6 = (ab * cp).sum(1), (ac * cp).sum(1)
    va = d3 * d6 - d5 * d4
    vb = d5 * d2 - d1 * d6
    vc = d1 * d4 - d3 * d2
    denom = np.where(np.abs(va + vb + vc) < 1e-20, 1e-20, va + vb + vc)
    v = vb / denom
    w = vc / denom
    q = a + ab * v[:, None] + ac * w[:, None]
    # regions
    m = (d1 <= 0) & (d2 <= 0)
    q[m] = a[m]
    m = (d3 >= 0) & (d4 <= d3)
    q[m] = b[m]
    m = (d6 >= 0) & (d5 <= d6)
    q[m] = c[m]
    m = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
    t = d1 / np.where(d1 - d3 == 0, 1e-20, d1 - d3)
    q[m] = (a + ab * t[:, None])[m]
    m = (vb <= 0) & (d2 >= 0) & (d6 <= 0)
    t = d2 / np.where(d2 - d6 == 0, 1e-20, d2 - d6)
    q[m] = (a + ac * t[:, None])[m]
    m = (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0)
    t = (d4 - d3) / np.where((d4 - d3) + (d5 - d6) == 0, 1e-20, (d4 - d3) + (d5 - d6))
    q[m] = (b + (c - b) * t[:, None])[m]
    return q, np.linalg.norm(q - p, axis=1)


# ----------------------------------------------------------------------------------- wrap
def head_weight(base, co, neck_top, neck_bottom):
    """1 above neck_top (metres below the eye line), 0 below neck_bottom, smooth in between."""
    eye_z = 0.5 * (base.eye_l[2] + base.eye_r[2])
    h = co[:, 2] - eye_z
    t = np.clip((h + neck_bottom) / (neck_bottom - neck_top), 0, 1)
    w = t * t * (3 - 2 * t)
    # nothing far from the head axis (shoulders)
    centre = 0.5 * (base.eye_l + base.eye_r)
    r = np.linalg.norm(co[:, :2] - centre[:2], axis=1)
    w *= np.clip((0.16 - r) / 0.04, 0, 1)
    return w


def smoothstep(x, a, b):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def mirror_map(co, tol=1e-4):
    tree = cKDTree(co)
    d, j = tree.query(co * np.array([-1, 1, 1]))
    j[d > tol] = -1
    return j


def idw(src_pts, src_val, dst_pts, k=8):
    tree = cKDTree(src_pts)
    d, j = tree.query(dst_pts, k=k)
    w = 1.0 / np.maximum(d, 1e-5) ** 2
    return (src_val[j] * w[:, :, None]).sum(1) / w.sum(1, keepdims=True)


def wrap(base, lm_base, lm_target, TV, TF, trusted_tv=None, a=None):
    t0 = time.time()
    co = base.co
    notes = {}
    # 1. similarity, then drop landmark pairs that disagree (embedding or fit outliers) and refit
    s, R, t = umeyama(lm_target, lm_base, scale=not a.metric)
    res = np.linalg.norm(lm_target @ (s * R).T + t - lm_base, axis=1)
    keep = res < max(3.0 * np.median(res), a.outlier_mm / 1000.0)
    lm_base, lm_target = lm_base[keep], lm_target[keep]
    a._lm_tb = (a._lm_tb[0][keep], a._lm_tb[1][keep])
    s, R, t = umeyama(lm_target, lm_base, scale=not a.metric)
    notes["landmarks_used"] = int(keep.sum())
    notes["landmarks_dropped"] = int((~keep).sum())
    TV = TV @ (s * R).T + t
    lt = lm_target @ (s * R).T + t
    notes["align_scale"] = float(s)
    notes["landmark_rms_before_mm"] = float(np.sqrt(((lt - lm_base) ** 2).sum(1).mean()) * 1000)
    w_head = head_weight(base, co, a.neck_top, a.neck_bottom)
    region = w_head > 0
    # 2. coarse RBF with anchors where the field must vanish: below the neck fade, and (unless
    # disabled) the scalp behind --hold-cranium-dy, so the face change decays into the base
    # cranium instead of extrapolating over it (the face landmarks say nothing about the skull)
    anchors = co[(w_head == 0) & base.skin & (np.linalg.norm(co[:, :2], axis=1) < 0.3)
                 & (co[:, 2] > 0.5 * (base.eye_l[2] + base.eye_r[2]) - a.neck_bottom - 0.08)]
    anchors = anchors[::max(1, len(anchors) // 300)]
    if a.hold_cranium_dy is not None:
        eye_y = 0.5 * (base.eye_l[1] + base.eye_r[1])
        cran = co[base.skin & (base.group("scalp") > 0.5) & (co[:, 1] - eye_y > a.hold_cranium_dy)]
        anchors = np.r_[anchors, cran[::max(1, len(cran) // 200)]]
        notes["cranium_anchors"] = len(cran[::max(1, len(cran) // 200)])
    X = np.r_[lm_base, anchors]
    Y = np.r_[lt - lm_base, np.zeros_like(anchors)]
    rbf = RBFInterpolator(X, Y, kernel="thin_plate_spline", smoothing=a.rbf_smoothing, degree=1)
    cur = co.copy()
    cur[region] = co[region] + w_head[region, None] * rbf(co[region])
    notes["landmark_rms_after_coarse_mm"] = float(np.sqrt(((embedded_points(cur, *a._lm_tb) - lt) ** 2).sum(1).mean()) * 1000)
    # 3. fine: projection rounds on the trusted skin region
    trust = base.skin & region & (base.group("ears") == 0)
    if trusted_tv is not None:
        tv_ok = trusted_tv
    else:
        tv_ok = np.ones(len(TV), bool)
    tf_ok = tv_ok[TF].all(1)
    TFt = TF[tf_ok]
    # a base vertex beyond the trusted target region finds its closest point on that region's rim;
    # such matches drag skin (neck, cranium) onto the rim, so matches on the rim ring are rejected
    rim = rim_faces(TFt)
    notes["rim_faces"] = int(rim.sum())
    for it in range(a.iters):
        idx = np.where(trust)[0]
        q, d, fid = closest_on_mesh(TV, TFt, cur[idx])
        nb = base.normals(cur)[idx]
        tn = np.cross(TV[TFt[fid, 1]] - TV[TFt[fid, 0]], TV[TFt[fid, 2]] - TV[TFt[fid, 0]])
        tn /= np.maximum(np.linalg.norm(tn, axis=1, keepdims=True), 1e-12)
        along = np.abs(((q - cur[idx]) * tn).sum(1))                  # offset along the target normal
        ok = (d < a.max_dist) & ((nb * tn).sum(1) > 0.5) & ~rim[fid] & ((d < 1e-3) | (along > 0.8 * d))
        disp = np.zeros_like(co)
        has = np.zeros(len(co), bool)
        disp[idx[ok]] = q[ok] - cur[idx[ok]]
        has[idx[ok]] = True
        # smooth the field: fill vertices without a match from their neighbours, then relax
        wsum = has.astype(np.float64)
        for _ in range(a.smooth):
            disp = np.where(has[:, None], disp, base.avg @ disp / np.maximum(base.avg @ wsum, 1e-9)[:, None]
                            * (base.avg @ wsum > 0)[:, None])
            wsum = np.maximum(wsum, (base.avg @ wsum > 0).astype(np.float64))
        disp = base.smooth(disp, a.smooth)
        step = a.step
        cur[region] = cur[region] + step * w_head[region, None] * disp[region]
        notes[f"iter{it}_matched"] = int(ok.sum())
        notes[f"iter{it}_median_dist_mm"] = float(np.median(d[ok]) * 1000) if ok.any() else None
    # 4. helpers. Rigid ones move with the field at their centroids. Then the eye cores: the target's
    # lid margins border its (distrusted) eyeballs, so matches there are rejected as rim matches and
    # the field at the base's lid margins is only extrapolated, which lifts the lids off the eye
    # (a gap under the lower lid, exposed sclera at the outer corner). Skin within --eye-core-mm of
    # an eyeball's surface takes that eyeball's rigid move, fading to the fitted field over
    # --eye-fade-mm, so the lids keep their fit on the eye (lid shape is a separate edit).
    delta = cur - co
    delta[~region] = 0
    skin_idx = np.where(base.skin & region)[0]
    rigid = {}
    for g in RIGID_HELPERS:
        m = (base.group(g) > 0) & base.helper
        if m.any():
            c = co[m].mean(0, keepdims=True)
            rigid[g] = (m, idw(co[skin_idx], delta[skin_idx], c, k=24)[0] * w_head[m].mean())
    if a.eye_core_mm is not None:
        for g in ("helper-l-eye", "helper-r-eye"):
            if g in rigid:
                m, mv = rigid[g]
                c = co[m].mean(0)
                s = np.linalg.norm(co - c, axis=1) - np.median(np.linalg.norm(co[m] - c, axis=1))
                w = 1 - smoothstep(s, a.eye_core_mm / 1000.0, (a.eye_core_mm + a.eye_fade_mm) / 1000.0)
                w *= base.skin & region
                delta += w[:, None] * (mv - delta)
                notes[f"eye_core_{g}_verts"] = int((w > 0).sum())
    for g in FIELD_HELPERS:
        m = (base.group(g) > 0) & base.helper
        if m.any():
            delta[m] = idw(co[skin_idx], delta[skin_idx], co[m]) * w_head[m, None]
    for m, mv in rigid.values():
        delta[m] = mv
    # 5. symmetrise
    if a.symmetrise:
        mm = mirror_map(co)
        ok = mm >= 0
        mirrored = np.zeros_like(delta)
        mirrored[ok] = delta[mm[ok]] * np.array([-1, 1, 1])
        delta[ok] = 0.5 * (delta[ok] + mirrored[ok])
        notes["symmetrised_verts"] = int(ok.sum())
    final = co + delta
    notes["landmark_rms_final_mm"] = float(np.sqrt(((embedded_points(final, *a._lm_tb) - lt) ** 2).sum(1).mean()) * 1000)
    notes["max_move_mm"] = float(np.linalg.norm(delta, axis=1).max() * 1000)
    notes["seconds"] = round(time.time() - t0, 1)
    return delta, notes, TV


def selftest(a):
    """Deform the base head by a known smooth field (wider mid-face, longer nose, squarer jaw),
    use it as the target with the same landmarks, and check the wrap recovers it."""
    base = Base(a.base)
    co = base.co
    rng = np.random.default_rng(0)
    eye = 0.5 * (base.eye_l + base.eye_r)
    rel = co - eye
    w = head_weight(base, co, a.neck_top, a.neck_bottom)
    field = np.zeros_like(co)
    g = np.exp(-((rel[:, 2] + 0.03) ** 2) / (2 * 0.03 ** 2))             # mid-face band
    field[:, 0] += 0.06 * rel[:, 0] * g                                   # 6 % wider
    nose = np.exp(-(rel[:, 0] ** 2 + (rel[:, 2] + 0.035) ** 2) / (2 * 0.012 ** 2)) * (rel[:, 1] < -0.015)
    field[:, 2] += -0.004 * nose                                          # nose tip 4 mm lower
    jaw = np.exp(-((rel[:, 2] + 0.10) ** 2) / (2 * 0.02 ** 2))
    field[:, 0] += 0.05 * rel[:, 0] * jaw
    field *= w[:, None]
    target = co + field
    skin_face = np.where(base.skin & (w > 0.99) & (rel[:, 1] < -0.005) & (np.abs(rel[:, 2]) < 0.09))[0]
    pick = rng.choice(skin_face, 105, replace=False)
    tri = np.stack([pick, pick, pick], 1)
    bary = np.tile([1.0, 0.0, 0.0], (105, 1))
    a._lm_tb = (tri, bary)
    TV = target[base.skin]
    remap = -np.ones(len(co), np.int64)
    remap[base.skin] = np.arange(base.skin.sum())
    TF = remap[base.tris]
    t_moved = rng.normal(size=3) * 0.01
    TVm = TV + t_moved                                                    # the target sits elsewhere
    lm_b, lm_t = embedded_points(co, tri, bary), embedded_points(target, tri, bary) + t_moved
    delta, notes, TVa = wrap(base, lm_b, lm_t, TVm, TF, None, a)
    # truth in the base frame: the target under the same similarity the wrap used (the base keeps
    # its own scale, so a wider mid-face also shrinks the aligned target a little overall)
    sc, R, t = umeyama(lm_t, lm_b)
    truth = (target + t_moved) @ (sc * R).T + t
    face = base.skin & (w > 0.99) & (rel[:, 1] < 0.0)
    body = base.skin & (w == 0)
    out = co + delta
    err = np.linalg.norm(out - truth, axis=1)
    none = np.linalg.norm(co - truth, axis=1)
    _, surf, _ = closest_on_mesh(TVa, TF, out[face])
    print(f"[selftest] {notes['seconds']} s; field max {np.linalg.norm(field, axis=1).max() * 1000:.2f} mm; "
          f"front face vs the aligned target: vertex error median {np.median(err[face]) * 1000:.3f} mm, "
          f"p95 {np.percentile(err[face], 95) * 1000:.3f} mm (unwrapped: {np.median(none[face]) * 1000:.3f} / "
          f"{np.percentile(none[face], 95) * 1000:.3f} mm); surface distance p95 {np.percentile(surf, 95) * 1000:.3f} mm; "
          f"body moved {np.abs(delta[body]).max() * 1000:.4f} mm; landmark rms {notes['landmark_rms_final_mm']:.3f} mm")
    eyes_ok = all(np.ptp(delta[(base.group(gn) > 0) & base.helper], axis=0).max() < 1e-9
                  for gn in ("helper-l-eye", "helper-r-eye"))
    print(f"[selftest] eye helpers rigid: {eyes_ok}")
    return 0 if (np.percentile(err[face], 95) < 0.3 * np.percentile(none[face], 95) and eyes_ok) else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", required=True)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--base-embedding")
    ap.add_argument("--target")
    ap.add_argument("--target-embedding")
    ap.add_argument("--target-frame", choices=["blender", "flame"], default="flame")
    ap.add_argument("--target-mask", default="", help=".npz with 'trusted' (bool per target vertex)")
    ap.add_argument("--flame-masks", default="", help="FLAME_masks.pkl: trusted = --trust regions minus --distrust")
    ap.add_argument("--trust", default="face,forehead,nose,lips,eye_region")
    ap.add_argument("--distrust", default="left_eyeball,right_eyeball,left_ear,right_ear,neck,boundary")
    ap.add_argument("--metric", action="store_true", help="keep the target's absolute scale")
    ap.add_argument("--neck-top", type=float, default=0.13, help="full weight above this depth below the eyes (m)")
    ap.add_argument("--neck-bottom", type=float, default=0.21, help="zero weight below this depth (m)")
    ap.add_argument("--rbf-smoothing", type=float, default=1e-5)
    ap.add_argument("--hold-cranium-dy", type=float, default=0.05,
                    help="scalp vertices this far behind the eye line (m) anchor the coarse field at zero")
    ap.add_argument("--no-hold-cranium", dest="hold_cranium_dy", action="store_const", const=None)
    ap.add_argument("--eye-core-mm", type=float, default=1.5,
                    help="skin this close to an eyeball's surface (mm) moves rigidly with the eyeball")
    ap.add_argument("--eye-fade-mm", type=float, default=8.0, help="fade from the eye core to the fitted field (mm)")
    ap.add_argument("--no-eye-core", dest="eye_core_mm", action="store_const", const=None)
    ap.add_argument("--iters", type=int, default=5)
    ap.add_argument("--smooth", type=int, default=6)
    ap.add_argument("--step", type=float, default=0.8)
    ap.add_argument("--max-dist", type=float, default=0.015)
    ap.add_argument("--symmetrise", action="store_true")
    ap.add_argument("--outlier-mm", type=float, default=4.0, help="landmark pairs off by more (after alignment) are dropped")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest(a)
    containment.assert_outputs(a, "out")
    base = Base(a.base)
    be = np.load(a.base_embedding)
    TV, TF = read_obj(a.target)
    te = np.load(a.target_embedding)
    t_idx = np.asarray(te["landmark_indices"]).reshape(-1)
    shared = [k for k, i in enumerate(t_idx) if be["valid"][i]]
    mp = t_idx[shared]
    lm_t = np.einsum("lk,lkd->ld", np.asarray(te["lmk_b_coords"])[shared], TV[TF[np.asarray(te["lmk_face_idx"])[shared]]])
    tri_b, bary_b = be["tri_verts"][mp], be["bary"][mp]
    if a.target_frame == "flame":
        TV = TV @ FLAME_TO_BLENDER.T
        lm_t = lm_t @ FLAME_TO_BLENDER.T
    a._lm_tb = (tri_b, bary_b)
    trusted = np.load(a.target_mask)["trusted"].astype(bool) if a.target_mask else None
    if a.flame_masks:
        import flame as fl
        masks = fl.load_pickle(a.flame_masks)
        trusted = np.zeros(len(TV), bool)
        for k in a.trust.split(","):
            trusted[np.asarray(masks[k], np.int64)] = True
        for k in a.distrust.split(","):
            trusted[np.asarray(masks[k], np.int64)] = False
    delta, notes, _ = wrap(base, embedded_points(base.co, tri_b, bary_b), lm_t, TV, TF, trusted, a)
    np.savez(a.out, delta=delta, base=base.co, mp_index=mp, notes=str(notes))
    print(f"[wrap] {len(mp)} shared landmarks; {notes}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
