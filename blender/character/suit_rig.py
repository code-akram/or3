"""Rigging the made suit (T13 item 6): skin weights from the body, linear blend skinning, a
Dem Bones fit of the jacket's own bones to the simulated pose set, and the per-pose correctives
left after it. numpy only (the caller gives BVH lookups as a function), so the fit can be
re-run from saved arrays outside Blender.

Pieces:

* transfer(): each garment vertex takes the body's weights at its nearest body point
  (barycentric over the nearest face), smoothed over the garment's own mesh (a garment
  bridges hollows the body has, so the raw transfer steps where the nearest face changes
  bone), then the top `k` kept and renormalised.
* skin(): linear blend skinning with per-bone 4x4 skinning matrices (pose @ rest^-1, world).
* fit_bones(): the jacket's bones (the bone plan's 8). Dem Bones (Le & Deng, SSDR) with the
  body's bones fixed: the extra bones start from k-means over the vertices the body's skinning
  misses most (the simulated pose set against LBS), then alternate
    - per bone and pose a rigid transform (weighted Kabsch on the vertices it holds), and
    - per vertex its weights over its body bones and its three nearest jacket bones
      (non-negative least squares over all poses, summing to one, at most `k` kept).
* drive(): each jacket bone's per-pose transform, relative to its parent body bone, as a
  ridge regression on its drivers' local rotations (axis-angle), so the engine can pose it
  from the skeleton (a helper rule, as deform_runtime's swing/twist).
* correctives(): what the fit leaves per pose, un-skinned to rest space (d = M_v^-1 (Y - X)),
  as deform_correctives stores its morphs.
"""

import numpy as np


# --- weights -----------------------------------------------------------------------------------

def transfer(X, T, body_W, nearest, smooth_iters=8, lam=0.5, k=4):
    """X (n, 3) garment, T its triangles; body_W (nb_verts, B) dense body weights; nearest(p)
    -> (face vertex ids (3,), barycentric (3,)). Returns (n, B) weights, top-k, rows sum 1."""
    n, B = len(X), body_W.shape[1]
    W = np.zeros((n, B))
    for i, p in enumerate(X):
        ids, bc = nearest(p)
        W[i] = bc @ body_W[ids]
    if smooth_iters:
        E = np.concatenate([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]])
        E = np.unique(np.sort(E, 1), axis=0)
        deg = np.bincount(E.ravel(), minlength=n).astype(float)
        for _ in range(smooth_iters):
            S = np.zeros_like(W)
            np.add.at(S, E[:, 0], W[E[:, 1]])
            np.add.at(S, E[:, 1], W[E[:, 0]])
            m = deg > 0
            W[m] = (1 - lam) * W[m] + lam * S[m] / deg[m, None]
    return top_k(W, k)


def top_k(W, k=4):
    W = np.clip(W, 0.0, None)
    if W.shape[1] > k:
        cut = np.partition(W, -k, axis=1)[:, -k][:, None]
        W = np.where(W >= cut, W, 0.0)
    s = W.sum(1, keepdims=True)
    return W / np.where(s > 0, s, 1.0)


# --- skinning ----------------------------------------------------------------------------------

def skin(X, W, M):
    """LBS: X (n, 3), W (n, B), M (B, 4, 4) skinning matrices. Returns (n, 3)."""
    Xh = np.concatenate([X, np.ones((len(X), 1))], 1)
    P = np.einsum("bij,nj->nbi", M[:, :3, :], Xh)        # (n, B, 3)
    return np.einsum("nb,nbi->ni", W, P)


def blended(W, M):
    """Each vertex's blended 4x4 matrix (n, 4, 4)."""
    return np.einsum("nb,bij->nij", W, M)


# --- Dem Bones ---------------------------------------------------------------------------------

def kabsch(A, B, w):
    """Rigid R, t minimising sum w |R a + t - b|^2. Returns a 4x4."""
    w = w / max(w.sum(), 1e-12)
    ca, cb = w @ A, w @ B
    H = ((A - ca) * w[:, None]).T @ (B - cb)
    U, _, Vt = np.linalg.svd(H)
    D = np.eye(3)
    D[2, 2] = np.sign(np.linalg.det(Vt.T @ U.T))
    R = Vt.T @ D @ U.T
    M = np.eye(4)
    M[:3, :3] = R
    M[:3, 3] = cb - R @ ca
    return M


def _kmeans(P, k, iters=30, seed=0):
    rng = np.random.default_rng(seed)
    C = P[rng.choice(len(P), k, replace=False)]
    for _ in range(iters):
        lab = np.argmin(((P[:, None] - C[None]) ** 2).sum(-1), 1)
        for j in range(k):
            if (lab == j).any():
                C[j] = P[lab == j].mean(0)
    return C, lab


def _nnls_sum1(A, y, iters=12):
    """min |A w - y|^2, w >= 0, sum w = 1 (a few active-set passes with a stiff sum row)."""
    m = A.shape[1]
    act = np.ones(m, bool)
    w = np.zeros(m)
    big = 1e3 * max(np.abs(A).max(), 1e-6)
    for _ in range(iters):
        Aa = np.vstack([A[:, act], big * np.ones((1, act.sum()))])
        ya = np.concatenate([y, [big]])
        sol = np.linalg.lstsq(Aa, ya, rcond=None)[0]
        if (sol >= -1e-9).all():
            w[:] = 0.0
            w[act] = np.clip(sol, 0.0, None)
            break
        idx = np.nonzero(act)[0]
        act[idx[np.argmin(sol)]] = False
        if not act.any():
            break
    s = w.sum()
    return w / s if s > 0 else w


def fit_bones(X0, Ys, W0, Ms, nj=8, iters=4, k=4, seed=0, init_frac=0.35, groups=None, allow=None):
    """X0 (n, 3) rest; Ys (K, n, 3) simulated poses; W0 (n, B) body weights; Ms (K, B, 4, 4)
    body skinning matrices. Returns dict: W (n, B + nj) weights, T (K, nj, 4, 4) jacket-bone
    transforms, centres (nj, 3) rest centres, err {lbs, fit} RMS mm per pose.
    groups: optional (n,) int labels (0..nj-1, -1 = none) to start from instead of k-means.
    allow: optional (n,) bool, the vertices that may take a jacket bone (the rest stay on the body's)."""
    K, n, B = len(Ys), len(X0), W0.shape[1]
    lbs = np.stack([skin(X0, W0, Ms[i]) for i in range(K)])
    res = np.linalg.norm(Ys - lbs, axis=2)                 # (K, n)
    rms = np.sqrt((res ** 2).mean(0))
    if groups is None:
        hot = rms >= np.quantile(rms, 1.0 - init_frac)
        C, lab_h = _kmeans(X0[hot], nj, seed=seed)
        lab = np.full(n, -1)
        lab[hot] = lab_h
    else:
        lab = np.asarray(groups)
        C = np.array([X0[lab == j].mean(0) if (lab == j).any() else X0.mean(0) for j in range(nj)])
    # start: the hot vertices fully on their cluster's bone
    V = np.zeros((n, nj))
    V[lab >= 0, lab[lab >= 0]] = 1.0
    W = np.concatenate([W0 * (1.0 - V.sum(1, keepdims=True)), V], 1)
    T = np.tile(np.eye(4), (K, nj, 1, 1))
    near = np.argsort(((X0[:, None] - C[None]) ** 2).sum(-1), 1)[:, :3]
    for _ in range(iters):
        # transforms: each jacket bone's rigid motion over the vertices it holds
        for j in range(nj):
            wj = W[:, B + j]
            m = wj > 0.05
            if m.sum() < 4:
                continue
            for i in range(K):
                T[i, j] = kabsch(X0[m], Ys[i][m], wj[m])
        # weights: per vertex over its body bones and its three nearest jacket bones
        Mall = np.concatenate([Ms, T], 1)                    # (K, B + nj, 4, 4)
        Xh = np.concatenate([X0, np.ones((n, 1))], 1)
        P = np.einsum("kbij,nj->knbi", Mall[:, :, :3, :], Xh)  # (K, n, B + nj, 3)
        Wn = np.zeros_like(W)
        for v in range(n):
            cand = np.nonzero(W0[v] > 0)[0]
            if allow is None or allow[v]:
                cand = np.concatenate([cand, B + near[v]])
            A = P[:, v, cand, :].transpose(0, 2, 1).reshape(-1, len(cand))
            y = Ys[:, v, :].reshape(-1)
            Wn[v, cand] = _nnls_sum1(A, y)
        W = top_k(Wn, k)
    fit = np.stack([skin(X0, W, np.concatenate([Ms[i], T[i]], 0)) for i in range(K)])
    err = {"lbs_rms_mm": [round(float(np.sqrt((np.linalg.norm(Ys[i] - lbs[i], axis=1) ** 2).mean())) * 1000, 2)
                          for i in range(K)],
           "fit_rms_mm": [round(float(np.sqrt((np.linalg.norm(Ys[i] - fit[i], axis=1) ** 2).mean())) * 1000, 2)
                          for i in range(K)],
           "lbs_p99_mm": [round(float(np.percentile(np.linalg.norm(Ys[i] - lbs[i], axis=1), 99)) * 1000, 1)
                          for i in range(K)],
           "fit_p99_mm": [round(float(np.percentile(np.linalg.norm(Ys[i] - fit[i], axis=1), 99)) * 1000, 1)
                          for i in range(K)]}
    return {"W": W, "T": T, "centres": C, "labels": lab, "err": err, "fit": fit, "lbs": lbs}


# --- driving the jacket bones from the skeleton -------------------------------------------------

def rotvec(R):
    """Axis-angle 3-vector of a 3x3 rotation."""
    c = np.clip((np.trace(R) - 1) / 2, -1.0, 1.0)
    a = np.arccos(c)
    if a < 1e-8:
        return np.zeros(3)
    v = np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]])
    return v / (2 * np.sin(a)) * a


def drive(T, parent_M, feats, lam=1e-2, centre=None):
    """T (K, 4, 4) a jacket bone's world transforms; parent_M (K, 4, 4) its parent body bone's
    skinning matrices; feats (K, F) the drivers' local rotations. Fits the bone's transform
    relative to its parent (rotation vector and translation, 6 numbers) as ridge-regressed
    linear in feats. centre: the bone's rest centre; the transform is taken about it (about the
    world origin a 10 deg swing of a skirt bone 1 m up reads as 170 mm of translation).
    Returns (coef (F + 1, 6), rel (K, 6), pred (K, 6))."""
    Cm, Ci = np.eye(4), np.eye(4)
    if centre is not None:
        Cm[:3, 3], Ci[:3, 3] = centre, -np.asarray(centre)
    rel = []
    for i in range(len(T)):
        Rl = Ci @ np.linalg.inv(parent_M[i]) @ T[i] @ Cm
        rel.append(np.concatenate([rotvec(Rl[:3, :3]), Rl[:3, 3]]))
    rel = np.array(rel)
    F = np.concatenate([feats, np.ones((len(feats), 1))], 1)
    coef = np.linalg.solve(F.T @ F + lam * np.eye(F.shape[1]), F.T @ rel)
    return coef, rel, F @ coef


# --- correctives -------------------------------------------------------------------------------

def correctives(X0, Ys, W, Mall):
    """Per pose: the rest-space delta that takes the fitted skin to the simulation
    (d = M_v^-1 (Y - skin)). Mall (K, B', 4, 4). Returns (K, n, 3)."""
    out = []
    for i in range(len(Ys)):
        Mv = blended(W, Mall[i])
        Yh = skin(X0, W, Mall[i])
        R = Mv[:, :3, :3]
        out.append(np.einsum("nij,nj->ni", np.linalg.inv(R), Ys[i] - Yh))
    return np.stack(out)


# --- T13c: the made layers' weights as the shipped pipeline makes them ---------------------------

def remap(W, co, arm, names, sigma=None, arm_free=True, skirt=False, body=False):
    """deform_rig.remap_mesh on arrays: W (n, len(names)) over the armature's deform bones
    (helpers included), co (n, 3) rest positions in armature space. A garment (sigma set) gets
    the spatial smoothing, the neck keep, the arm-free chest core and shoulder cap (the cap rides
    the clavicle: a point above the shoulder pivot skinned to the arm swings up through the outer
    layer when the arm comes down, the ridge of t13r-a2's arms-down LBS), the half-joint
    remaps onto the deltoid / hip helpers, the twist splits, and (the jacket) the skirt bones.
    body: the shoulder cap only, plus the finger falloff. Returns W, top 4, rows sum 1."""
    from . import deform_rig as drig
    cfg = drig.DEFAULTS
    W = np.array(W, float)
    G = drig.Geo(arm, names)
    sides = drig._sides(arm)
    if sigma:
        W0 = W.copy()
        W = drig.spatial_smooth(W, co, sigma)
        kz = cfg["keep_neck_m"]
        if G.col("neck_01") is not None and kz:
            r = drig._dist_to_segment(co, G.head("neck_01"), G.tail("neck_01"))
            f = drig.smoothstep(kz[0], kz[1], r)[:, None]
            W = W0 * (1 - f) + W * f
        if arm_free:
            drig.arm_free_core(W, co, G, sides, *cfg["arm_free"]["x_ramp"])
    if body:
        drig.arm_free_core(W, co, G, sides, *cfg["arm_free"]["x_ramp"], core=False)
    for s in sides:
        drig.half_joint(W, co, G, [f"clavicle_{s}", "spine_03", "spine_02"], f"upperarm_{s}",
                        f"deltoid_helper_{s}", cfg["deltoid"]["radius_m"])
        drig.half_joint(W, co, G, ["pelvis", "spine_01"], f"thigh_{s}", f"hip_helper_{s}", cfg["hip"]["radius_m"])
        drig.twist_split(W, co, G, f"upperarm_{s}", f"upperarm_twist_01_{s}",
                         lambda t: 1 - drig.smoothstep(0.1, 0.8, t))
        drig.twist_split(W, co, G, f"lowerarm_{s}", f"lowerarm_twist_01_{s}",
                         lambda t: drig.smoothstep(0.05, 0.65, t))
        drig.twist_split(W, co, G, f"thigh_{s}", f"thigh_twist_01_{s}",
                         lambda t: 1 - drig.smoothstep(0.1, 0.8, t))
        if body:
            drig.finger_falloff(W, co, G, s, cfg["fingers"]["band"])
    if skirt:
        drig.skirt_weights(W, co, G, cfg["skirt"], sides)
    return drig.prune(W, cfg["max_influences"])


def widen(W, cols, names):
    """(n, len(cols)) weights over bone names `cols` -> (n, len(names)) columns in `names` order."""
    out = np.zeros((len(W), len(names)))
    idx = {n: i for i, n in enumerate(names)}
    for j, c in enumerate(cols):
        if c in idx:
            out[:, idx[c]] += W[:, j]
    return out


# --- a made part riding on its drape (wrap deformer) -----------------------------------------------

def vertex_normals(X, T):
    fn = np.cross(X[T[:, 1]] - X[T[:, 0]], X[T[:, 2]] - X[T[:, 0]])
    N = np.zeros_like(X)
    for k in range(3):
        np.add.at(N, T[:, k], fn)
    return N / np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)


def _frames(X, T, fi, bc):
    """Per bound point: the drape point (barycentric), and an orthonormal frame (e1 along the
    face's first edge, e2, n the interpolated vertex normal)."""
    N = vertex_normals(X, T)
    tri = T[fi]
    base = np.einsum("nk,nki->ni", bc, X[tri])
    n = np.einsum("nk,nki->ni", bc, N[tri])
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    e = X[tri[:, 1]] - X[tri[:, 0]]
    e1 = e - n * np.sum(e * n, 1, keepdims=True)
    e1 /= np.maximum(np.linalg.norm(e1, axis=1, keepdims=True), 1e-12)
    e2 = np.cross(n, e1)
    return base, np.stack([e1, e2, n], 1)          # (m, 3), (m, 3 axes, 3)


def wrap_bind(X, T, P, fi, bc):
    """Bind points P to the drape (X, T): fi, bc their nearest face and barycentrics there.
    The offset from the drape point is kept in the face's frame, so a shell's outside, a rim, a
    rever or a button keeps its height and lean as the cloth turns."""
    base, F = _frames(X, T, fi, bc)
    off = np.einsum("nai,ni->na", F, P - base)
    return {"fi": np.asarray(fi), "bc": np.asarray(bc), "off": off}


def wrap_apply(bind, Y, T):
    base, F = _frames(Y, T, bind["fi"], bind["bc"])
    return base + np.einsum("nai,na->ni", F, bind["off"])


def wrap_weights(bind, W, T):
    """A bound part's weights: its face's barycentric mix of the drape's."""
    return np.einsum("nk,nkb->nb", bind["bc"], W[T[bind["fi"]]])


# --- correctives over cone activations (pose-space, least squares) ---------------------------------

def fit_shapes(D, A, mask, lam=1e-4, chunk=4000):
    """D (K, n, 3) rest-space residuals per pose; A (K, C) the cone weights per pose; mask (n, C)
    in [0, 1] (a shape acts only near its joint). Per vertex: min sum_k |sum_c A_kc m_vc S_vc -
    D_kv|^2 + lam |S_v|^2. Returns S (C, n, 3), the shapes as stored (masks folded in)."""
    K, n, _ = D.shape
    C = A.shape[1]
    G0 = A.T @ A                                            # (C, C)
    S = np.zeros((n, C, 3))
    for a in range(0, n, chunk):
        b = min(n, a + chunk)
        m = mask[a:b]                                       # (c, C)
        G = G0[None] * m[:, :, None] * m[:, None, :] + lam * np.eye(C)[None]
        R = np.einsum("kc,kvi->vci", A, D[:, a:b]) * m[:, :, None]
        S[a:b] = np.linalg.solve(G, R) * m[:, :, None]
    return S.transpose(1, 0, 2)


def apply_shapes(S, a):
    """Sum of shapes S (C, n, 3) at activations a (C,)."""
    return np.einsum("c,cni->ni", a, S)


def unskin(W, M, Y, X0):
    """Rest-space delta d with skin(X0 + d, W, M) = Y (the blended 3x3 inverted)."""
    Mv = blended(W, M)
    return np.einsum("nij,nj->ni", np.linalg.inv(Mv[:, :3, :3]), Y - skin(X0, W, M))


# --- the skirt bones' follow rule (deform_runtime 'follow') in numpy ------------------------------

def rotvec_mat(v):
    a = np.linalg.norm(v)
    if a < 1e-12:
        return np.eye(3)
    k = v / a
    Kx = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + np.sin(a) * Kx + (1 - np.cos(a)) * Kx @ Kx


def follow_mat(gain, fl, ab, L, N, Rp, Mp, head):
    """Skinning matrix of a follow bone whose parent and frame are the pelvis: R_K = R_pelvis *
    rotvec(g(fl) fl L + g(ab) ab N), about the bone's head carried by the pelvis. fl, ab: the
    thigh's swing components (deform_runtime.Runtime.helper_rotation); Rp the pelvis's world
    delta rotation (3x3), Mp its skinning matrix (4x4); head the bone's rest head."""
    gf = gain["flex+"] if fl >= 0 else gain["flex-"]
    ga = gain["abd+"] if ab >= 0 else gain["abd-"]
    R = Rp @ rotvec_mat(L * (gf * fl) + N * (ga * ab))
    hp = Mp[:3, :3] @ head + Mp[:3, 3]
    M = np.eye(4)
    M[:3, :3] = R
    M[:3, 3] = hp - R @ head
    return M
