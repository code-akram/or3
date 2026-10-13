"""Joint multi-view FLAME fit to MediaPipe landmarks: one shared identity shape, per-frame camera,
jaw and expression.

Every reference frame contributes its 2D MediaPipe landmarks (the points a MediaPipe landmark
embedding maps onto the FLAME surface; contour points are not in such an embedding). The model:

  shape beta (n_shape, shared, prior toward an initial code, e.g. a median regressor code),
  per frame: rotation (3), translation (3), jaw (3), expression psi (n_expr), log focal (1).

Perspective camera with the principal point at the frame centre; a log-normal focal prior
(35 mm equivalent across the frame width; a portrait frame narrower than tall is treated as a
centre crop of a 2.39:1 frame). Residuals are in units of each frame's interpupillary distance,
weighted per frame, with a Huber loss; scipy least_squares with a block-sparse Jacobian.

    python -I fit.py --flame generic_model.pkl --embedding mediapipe_landmark_embedding.npz \
        --ref REF_DIR --ids 8,9,12 --init codes.npz --out fit.npz [--obj neutral.obj]
    python -I fit.py --selftest          # synthetic recovery test, no model files needed

Run with OMP_NUM_THREADS=3.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares
from scipy.sparse import lil_matrix
from scipy.spatial.transform import Rotation

sys.path.insert(0, str(Path(__file__).resolve().parent))
import flame as fl  # noqa: E402

IRIS_R, IRIS_L = 468, 473
PER_FRAME_FIXED = 10          # rvec 3, tvec 3, jaw 3, log focal 1


class LandmarkModel:
    """FLAME restricted to the vertices under the landmark embedding: fast shaped + posed landmarks."""

    def __init__(self, m, face_idx, bary, n_shape, n_expr):
        self.n_shape, self.n_expr = n_shape, n_expr
        tri = m.faces[face_idx]                               # (L, 3)
        S, inv = np.unique(tri.reshape(-1), return_inverse=True)
        self.tri = inv.reshape(-1, 3)
        self.bary = bary
        cols = list(range(n_shape)) + list(range(m.n_shape, m.n_shape + n_expr))
        self.vt = m.v_template[S]
        self.sd = m.shapedirs[S][:, :, cols]                  # (s, 3, n_shape + n_expr)
        self.pd = m.posedirs.reshape(-1, 3, m.posedirs.shape[1])[S]
        self.w = m.weights[S]
        self.parents = m.parents
        self.J0 = m.J_regressor @ m.v_template
        self.JS = np.einsum("jv,vdk->jdk", m.J_regressor, m.shapedirs[:, :, cols])

    def points(self, beta, psi, pose):
        """Landmark positions (L, 3), model space; pose (J, 3) axis-angle."""
        c = np.concatenate([beta, psi])
        v = self.vt + self.sd @ c
        J = self.J0 + self.JS @ c
        R = fl.rodrigues(pose)
        feat = (R[1:] - np.eye(3)).reshape(-1)
        v = v + self.pd @ feat
        G = np.zeros((len(J), 4, 4))
        for j in range(len(J)):
            T = np.eye(4)
            T[:3, :3] = R[j]
            T[:3, 3] = J[j] - (J[self.parents[j]] if j > 0 else 0)
            G[j] = T if j == 0 else G[self.parents[j]] @ T
        G[:, :3, 3] -= np.einsum("jab,jb->ja", G[:, :3, :3], J)
        A = np.einsum("vj,jab->vab", self.w, G)
        v = np.einsum("vab,vb->va", A[:, :3, :3], v) + A[:, :3, 3]
        return np.einsum("lk,lkd->ld", self.bary, v[self.tri])


def project(P, rvec, tvec, f, cx, cy, R0=None):
    """OpenCV-convention pinhole projection of model points P (L, 3). The rotation is
    rodrigues(rvec) @ R0: a small update on a per-frame base rotation, so the parameters stay away
    from the 180-degree singularity of the axis-angle map (a face toward the camera is a half turn
    about x)."""
    R = fl.rodrigues(rvec)[0] if R0 is None else fl.rodrigues(rvec)[0] @ R0
    X = P @ R.T + tvec
    z = np.maximum(X[:, 2], 1e-6)
    return np.c_[f * X[:, 0] / z + cx, f * X[:, 1] / z + cy]


def prior_focal(wh, lens_mm):
    w, h = wh
    w_eff = w if w >= h else h * 2.39
    return lens_mm / 36.0 * w_eff


class Problem:
    def __init__(self, lmodel, frames, beta0, n_jaw_joint, shape_prior, expr_prior, jaw_prior, lens_mm,
                 lens_sigma, huber, cam_prior=0.01):
        self.lm, self.frames, self.beta0 = lmodel, frames, beta0
        self.jaw_joint = n_jaw_joint
        self.nb, self.ne = lmodel.n_shape, lmodel.n_expr
        self.npf = PER_FRAME_FIXED + self.ne
        self.shape_prior, self.expr_prior, self.jaw_prior = shape_prior, expr_prior, jaw_prior
        self.lens_mm, self.lens_sigma, self.huber, self.cam_prior = lens_mm, lens_sigma, huber, cam_prior
        self.nj = len(lmodel.parents)

    def unpack(self, x):
        beta = x[:self.nb]
        per = x[self.nb:].reshape(len(self.frames), self.npf)
        return beta, per

    def frame_points(self, beta, p):
        pose = np.zeros((self.nj, 3))
        pose[self.jaw_joint] = p[6:9]
        return self.lm.points(beta, p[PER_FRAME_FIXED:], pose)

    def frame_residuals(self, beta, fr, p):
        P = self.frame_points(beta, p)
        uv = project(P, p[0:3], p[3:6], np.exp(p[9]), fr["cx"], fr["cy"], fr["R0"])
        return (fr["weight"] / fr["ipd"]) * (uv - fr["uv"]).ravel()

    def frame_priors(self, fr, p):
        return np.concatenate([self.expr_prior * p[PER_FRAME_FIXED:], self.jaw_prior * p[6:9],
                               [self.cam_prior * (p[9] - np.log(prior_focal(fr["wh"], self.lens_mm))) / self.lens_sigma]])

    def residuals(self, x):
        beta, per = self.unpack(x)
        out = [self.frame_residuals(beta, fr, p) for fr, p in zip(self.frames, per)]
        out.append(self.shape_prior * (beta - self.beta0))
        out += [self.frame_priors(fr, p) for fr, p in zip(self.frames, per)]
        return np.concatenate(out)

    def solve_frame(self, beta, fr, p0, max_nfev=100):
        """One frame's camera, jaw and expression with the shape held."""
        def f(p):
            return np.concatenate([self.frame_residuals(beta, fr, p), self.frame_priors(fr, p)])
        return least_squares(f, p0, loss="huber", f_scale=self.huber, x_scale="jac", max_nfev=max_nfev).x

    def sparsity(self):
        L = len(self.lm.bary)
        n_lm = len(self.frames) * L * 2
        n_res = n_lm + self.nb + len(self.frames) * (self.ne + 3 + 1)
        S = lil_matrix((n_res, self.nb + len(self.frames) * self.npf), dtype=np.int8)
        S[:n_lm, :self.nb] = 1
        for i in range(len(self.frames)):
            c0 = self.nb + i * self.npf
            S[i * L * 2:(i + 1) * L * 2, c0:c0 + self.npf] = 1
        r = n_lm
        S[r:r + self.nb, :self.nb] = np.eye(self.nb, dtype=np.int8)
        r += self.nb
        for i in range(len(self.frames)):
            c0 = self.nb + i * self.npf
            for k in range(self.ne):
                S[r + k, c0 + PER_FRAME_FIXED + k] = 1
            r += self.ne
            for k in range(3):
                S[r + k, c0 + 6 + k] = 1
            r += 3
            S[r, c0 + 9] = 1
            r += 1
        return S

    def solve(self, x0, max_nfev=200, loss="huber"):
        return least_squares(self.residuals, x0, jac_sparsity=self.sparsity(), loss=loss, f_scale=self.huber,
                             x_scale="jac", max_nfev=max_nfev, verbose=0)


def init_frame(lmodel, beta0, fr, lens_mm, nj):
    """Camera init by PnP of the initial shape's landmarks."""
    import cv2
    P = lmodel.points(beta0, np.zeros(lmodel.n_expr), np.zeros((nj, 3)))
    f = prior_focal(fr["wh"], lens_mm)
    K = np.array([[f, 0, fr["cx"]], [0, f, fr["cy"]], [0, 0, 1]], np.float64)
    ok, rv, tv = cv2.solvePnP(P, fr["uv"].astype(np.float64), K, None, flags=cv2.SOLVEPNP_EPNP)
    _, rv, tv = cv2.solvePnP(P, fr["uv"].astype(np.float64), K, None, rv, tv, True, flags=cv2.SOLVEPNP_ITERATIVE)
    fr["R0"] = fl.rodrigues(rv.ravel())[0]
    return np.r_[np.zeros(3), tv.ravel(), np.zeros(3), np.log(f), np.zeros(lmodel.n_expr)]


def load_frames(ref, ids, mp_index, weight_flat):
    ref = Path(ref)
    idx = {f["id"]: f for f in json.load(open(ref / "index.json"))["frames"]}
    frames = []
    for i in ids:
        f = idx[i]
        lm = np.load(ref / f["landmarks"])
        if len(lm) < 478:
            raise ValueError(f"frame {i} has no MediaPipe landmarks")
        s, x0, y0 = f["frame_landmarks_affine"]
        uv_all = np.c_[lm[:, 0] / s + x0, lm[:, 1] / s + y0]
        w, h = f["frame_wh"]
        frames.append({"id": i, "uv": uv_all[mp_index], "wh": (w, h), "cx": w / 2.0, "cy": h / 2.0,
                       "ipd": float(np.linalg.norm(uv_all[IRIS_R] - uv_all[IRIS_L])),
                       "weight": 1.0 + weight_flat * float(np.clip(f["flat"], 0, 1)), "flat": f["flat"],
                       "yaw": f["yaw"]})
    return frames


def run(m, emb, frames, beta0, a):
    lmodel = LandmarkModel(m, emb["face_idx"], emb["bary"], a.n_shape, a.n_expr)
    nj = len(m.parents)
    x0 = np.concatenate([beta0] + [init_frame(lmodel, beta0, fr, a.lens_mm, nj) for fr in frames])
    prob = Problem(lmodel, frames, beta0, a.jaw_joint, a.shape_prior, a.expr_prior, a.jaw_prior, a.lens_mm,
                   a.lens_sigma, a.huber, a.cam_prior)
    t0 = time.time()
    # stage 1: each frame's camera, jaw and expression with the shape held at the initial code
    per0 = x0[a.n_shape:].reshape(len(frames), -1)
    per1 = np.stack([prob.solve_frame(beta0, fr, p) for fr, p in zip(frames, per0)])
    # stage 2: everything jointly, plain least squares to converge, then Huber to discount the
    # landmarks that disagree (hair or beard over the contour, occlusion); a Huber loss from a far
    # start crawls, because most residuals begin in its linear regime.
    res = prob.solve(np.concatenate([beta0, per1.ravel()]), max_nfev=a.max_nfev, loss="linear")
    if a.huber > 0:
        res = prob.solve(res.x, max_nfev=a.max_nfev, loss="huber")
    beta, per = prob.unpack(res.x)
    rows = []
    for fr, p in zip(frames, per):
        P = prob.frame_points(beta, p)
        uv = project(P, p[0:3], p[3:6], np.exp(p[9]), fr["cx"], fr["cy"], fr["R0"])
        err = np.linalg.norm(uv - fr["uv"], axis=1) / fr["ipd"]
        rows.append({"id": fr["id"], "rms_ipd": float(np.sqrt((err ** 2).mean())), "max_ipd": float(err.max()),
                     "f35_mm": float(np.exp(p[9]) / (fr["wh"][0] if fr["wh"][0] >= fr["wh"][1]
                                                     else fr["wh"][1] * 2.39) * 36.0),
                     "dist_m": float(np.linalg.norm(p[3:6])), "jaw_rad": float(np.linalg.norm(p[6:9])),
                     "expr_norm": float(np.linalg.norm(p[PER_FRAME_FIXED:]))})
    return beta, per, rows, res, time.time() - t0


# ------------------------------------------------------------------------------------ selftest
def synthetic_model(rng, n_shape=40, n_expr=10):
    """A FLAME-shaped toy: a deformed ellipsoid grid, smooth random blend shapes, 5-joint chain."""
    nu, nv = 40, 30
    u = np.linspace(-np.pi * 0.9, np.pi * 0.9, nu)
    v = np.linspace(-np.pi / 2 * 0.9, np.pi / 2 * 0.9, nv)
    U, Vv = np.meshgrid(u, v)
    X = np.c_[0.075 * np.sin(U).ravel() * np.cos(Vv).ravel(), 0.11 * np.sin(Vv).ravel(),
              0.09 * np.cos(U).ravel() * np.cos(Vv).ravel()]
    faces = []
    for i in range(nv - 1):
        for j in range(nu - 1):
            a, b, c, d = i * nu + j, i * nu + j + 1, (i + 1) * nu + j, (i + 1) * nu + j + 1
            faces += [[a, b, d], [a, d, c]]
    faces = np.array(faces)
    K = n_shape + n_expr
    basis = []
    for k in range(K):
        fx, fy, fz = rng.normal(size=3) * 12
        ph = rng.uniform(0, 2 * np.pi, 3)
        amp = 0.004 / np.sqrt(1 + k * 0.2)
        basis.append(amp * np.c_[np.sin(fx * X[:, 1] + ph[0]), np.sin(fy * X[:, 0] + ph[1]), np.sin(fz * X[:, 1] + ph[2])])
    sd = np.stack(basis, -1)
    V = len(X)
    Jr = np.zeros((5, V))
    Jr[0, :] = 1.0 / V
    low = X[:, 1] < -0.05
    Jr[1, :] = 1.0 / V
    Jr[2, low] = 1.0 / low.sum()
    Jr[3, 0] = Jr[4, 1] = 1.0
    W = np.zeros((V, 5))
    W[:, 0] = 1.0
    W[low, 0], W[low, 2] = 0.3, 0.7
    m = fl.Flame(X, sd, np.zeros((V * 3, 36)), Jr, W, [-1, 0, 1, 1, 1], faces, n_shape=n_shape)
    front = np.where(X[:, 2] > 0.03)[0]
    pick = rng.choice(front, 105, replace=False)
    face_idx = np.array([np.where((faces == p).any(1))[0][0] for p in pick])
    bary = np.array([(faces[fi] == p).astype(float) for fi, p in zip(face_idx, pick)])
    return m, {"face_idx": face_idx, "bary": bary}


def selftest():
    rng = np.random.default_rng(3)
    m, emb = synthetic_model(rng)
    nb, ne = 40, 10
    beta_true = rng.normal(size=nb)
    lmodel = LandmarkModel(m, emb["face_idx"], emb["bary"], nb, ne)
    frames = []
    for i in range(10):
        yaw, pitch = rng.uniform(-30, 30), rng.uniform(-10, 10)
        # model y up / z toward the viewer -> camera y down / z away: flip y and z, then yaw / pitch
        R = fl.rodrigues(np.deg2rad([pitch, yaw, 0]))[0] @ np.diag([1, -1, -1])
        rv = Rotation.from_matrix(R).as_rotvec()
        f = rng.uniform(2500, 5000)
        dist = f * 0.12 / rng.uniform(250, 500)
        tv = np.array([rng.normal() * 0.02, rng.normal() * 0.02, dist])
        psi = rng.normal(size=ne) * 0.1          # near-neutral frames, as selected for the real fit
        jaw = np.r_[rng.uniform(0, 0.05), 0, 0]
        pose = np.zeros((5, 3))
        pose[2] = jaw
        P = lmodel.points(beta_true, psi, pose)
        uv = project(P, rv, tv, f, 960, 540) + rng.normal(size=(105, 2)) * 0.5
        ipd = f * 0.063 / dist
        frames.append({"id": i, "uv": uv, "wh": (1920, 1080), "cx": 960.0, "cy": 540.0, "ipd": ipd,
                       "weight": 1.0, "flat": 0.5, "yaw": yaw})
    beta0 = beta_true + rng.normal(size=nb) * 0.8
    a = argparse.Namespace(n_shape=nb, n_expr=ne, jaw_joint=2, shape_prior=0.002, expr_prior=0.02, jaw_prior=0.01,
                           lens_mm=75.0, lens_sigma=1.0, huber=0.03, cam_prior=0.01, max_nfev=300)
    beta, _, rows, res, dt = run(m, emb, frames, beta0, a)
    front = m.v_template[:, 2] > 0.03                  # the landmarked side; scale is free (distance)
    v_true, v0, v_fit = m.shaped(beta_true)[front], m.shaped(beta0)[front], m.shaped(beta)[front]
    e0, e1 = procrustes_rms(v0, v_true) * 1000, procrustes_rms(v_fit, v_true) * 1000
    print(f"[selftest] {dt:.1f} s, nfev {res.nfev}, status {res.status}; front-surface rms vs truth after a "
          f"similarity fit: init {e0:.2f} mm -> fit {e1:.2f} mm; landmark rms "
          f"{np.mean([r['rms_ipd'] for r in rows]) * 100:.2f} % IPD (noise 0.5 px)")
    return 0 if e1 < 0.3 * e0 else 1


def procrustes_rms(A, B):
    """RMS distance between point sets after the best similarity transform of A onto B."""
    ma, mb = A.mean(0), B.mean(0)
    A0, B0 = A - ma, B - mb
    U, S, Vt = np.linalg.svd(B0.T @ A0)
    D = np.diag([1, 1, np.sign(np.linalg.det(U @ Vt))])
    R = U @ D @ Vt
    s = np.trace(np.diag(S) @ D) / (A0 ** 2).sum()
    return float(np.sqrt(((s * A0 @ R.T - B0) ** 2).sum(1).mean()))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--flame", help="FLAME pickle (generic_model.pkl format)")
    ap.add_argument("--embedding", help="MediaPipe landmark embedding .npz for that model")
    ap.add_argument("--ref", help="reference dir from refboard.py board")
    ap.add_argument("--ids", default="", help="comma-separated frame ids")
    ap.add_argument("--init", default="", help="codes.npz from identity_codes.py (its 'median'); else zeros")
    ap.add_argument("--n-shape", type=int, default=100)
    ap.add_argument("--n-expr", type=int, default=20)
    ap.add_argument("--jaw-joint", type=int, default=2)
    ap.add_argument("--shape-prior", type=float, default=0.002, help="residual weight on (beta - init)")
    ap.add_argument("--expr-prior", type=float, default=0.003)
    ap.add_argument("--jaw-prior", type=float, default=0.02)
    ap.add_argument("--lens-mm", type=float, default=75.0)
    ap.add_argument("--lens-sigma", type=float, default=0.7, help="log-space focal prior width")
    ap.add_argument("--huber", type=float, default=0.03, help="Huber scale, IPD units (0: plain least squares)")
    ap.add_argument("--cam-prior", type=float, default=0.01, help="residual weight of the focal prior")
    ap.add_argument("--weight-flat", type=float, default=2.0)
    ap.add_argument("--max-nfev", type=int, default=150)
    ap.add_argument("--out", help="output .npz")
    ap.add_argument("--obj", default="", help="write the fitted neutral mesh (metres) here")
    ap.add_argument("--obj-init", default="", help="write the initial-code neutral mesh here (for comparison)")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    m = fl.load(a.flame)
    emb = fl.load_embedding(a.embedding)
    ids = [int(x) for x in a.ids.split(",") if x.strip()]
    frames = load_frames(a.ref, ids, emb["mp_index"], a.weight_flat)
    beta0 = np.zeros(a.n_shape)
    if a.init:
        med = np.load(a.init)["median"]
        beta0[:min(a.n_shape, len(med))] = med[:a.n_shape]
    beta, per, rows, res, dt = run(m, emb, frames, beta0, a)
    np.savez(a.out, beta=beta, beta0=beta0, per_frame=per, ids=np.array(ids), rows=json.dumps(rows),
             cost=res.cost, args=json.dumps(vars(a)))
    if a.obj:
        fl.write_obj(a.obj, m.shaped(beta), m.faces)
    if a.obj_init:
        fl.write_obj(a.obj_init, m.shaped(beta0), m.faces)
    print(f"[fit] {len(frames)} frames, {a.n_shape} shape / {a.n_expr} expr, {dt:.1f} s, nfev {res.nfev}; "
          f"|beta - init| {np.linalg.norm(beta - beta0):.2f}")
    for r in rows:
        print(f"  {r['id']:3d} rms {r['rms_ipd'] * 100:5.2f} % IPD  max {r['max_ipd'] * 100:5.1f} %  "
              f"f35 {r['f35_mm']:6.1f} mm  dist {r['dist_m']:.2f} m  jaw {r['jaw_rad']:.3f}  |psi| {r['expr_norm']:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
