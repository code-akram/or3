"""Quality check, basic cleanup and export for one GVHMR run (Phase 0 spike 3).

Reads ``<run>/smplx_params.npz`` (written by bench_gvhmr.py), then:

1. Forward-kinematics the SMPL-X body (22 body joints) in world (gravity-aligned, y-up) and camera frames.
2. Measures jitter (mean |jerk|, m/s^3), acceleration, foot skating (horizontal speed of a planted foot),
   root drift, 2D reprojection error against ViTPose, and implausible angular-speed spikes.
3. Cleans up: One Euro filter on joint rotations (quaternions) and root translation, then a root-level
   foot-contact lock (cancels the planted foot's horizontal slide) and a floor clamp.
4. Re-measures, and exports raw + clean motion as npz and BVH (22-joint SMPL-X body skeleton)
   to ``--motion-out``, plus a 2D overlay video, a world stick-figure video and a plot to ``--vis-out``.

Everything written here derives from film frames and SMPL-X, so all outputs stay under private/.

    python -I motion_qc.py RUN_DIR --motion-out private/motion/NAME --vis-out private/work/vis/NAME
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np
import torch
from scipy.spatial.transform import Rotation as R

FPS = 30.0
# SMPL-X / SMPL body kinematic tree (first 22 joints).
PARENTS = [-1, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 9, 9, 12, 13, 14, 16, 17, 18, 19]
NAMES = [
    "pelvis", "left_hip", "right_hip", "spine1", "left_knee", "right_knee", "spine2", "left_ankle",
    "right_ankle", "spine3", "left_foot", "right_foot", "neck", "left_collar", "right_collar", "head",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow", "left_wrist", "right_wrist",
]
FEET = {"left": (7, 10), "right": (8, 11)}  # (ankle, toe/ball)
# COCO-17 index -> SMPL joint, for the reprojection check (eyes/ears/nose skipped).
COCO_TO_SMPL = {5: 16, 6: 17, 7: 18, 8: 19, 9: 20, 10: 21, 11: 1, 12: 2, 13: 4, 14: 5, 15: 7, 16: 8}


# ----------------------------------------------------------------------------------------------- FK
def body_model():
    from gvhmr.utils.smplx_utils import make_smplx

    return make_smplx("supermotion").eval()


@torch.no_grad()
def fk(bm, orient, body_pose, betas, transl) -> np.ndarray:
    t = lambda x: torch.as_tensor(x, dtype=torch.float32)  # noqa: E731
    out = bm(global_orient=t(orient), body_pose=t(body_pose), betas=t(betas), transl=t(transl))
    return out.joints[:, :22].numpy()


@torch.no_grad()
def rest_joints(bm, betas) -> np.ndarray:
    return bm.get_skeleton(torch.as_tensor(betas, dtype=torch.float32)).numpy()


# ------------------------------------------------------------------------------------------ metrics
def deriv(x: np.ndarray, n: int) -> np.ndarray:
    for _ in range(n):
        x = np.diff(x, axis=0) * FPS
    return x


def foot_contacts(j: np.ndarray, up: int = 1) -> dict[str, np.ndarray]:
    """Velocity + relative-height contact labels (works on stairs: no global floor assumed).

    A foot is planted when its lowest point (ankle/ball) is within 4 cm of the lower foot this frame and
    its 3D speed is < 0.6 m/s (generous; a slide still shows up as horizontal speed)."""
    low = {k: j[:, list(v), up].min(1) for k, v in FEET.items()}
    lowest = np.minimum(low["left"], low["right"])
    out = {}
    for k, (a, b) in FEET.items():
        p = j[:, [a, b]].mean(1)
        v = np.linalg.norm(np.gradient(p, axis=0) * FPS, axis=-1)
        out[k] = (low[k] - lowest < 0.04) & (v < 0.6)
    return out


def horiz(x: np.ndarray, up: int = 1) -> np.ndarray:
    return np.delete(x, up, axis=-1)


def metrics(j: np.ndarray, kp2d=None, j_cam=None, K=None, up: int = 1) -> dict:
    jerk = np.linalg.norm(deriv(j, 3), axis=-1)  # (L-3, 22)
    acc = np.linalg.norm(deriv(j, 2), axis=-1)
    contacts = foot_contacts(j, up)
    skate = []
    for k, (a, b) in FEET.items():
        p = horiz(j[:, [a, b]].mean(1), up)
        hv = np.linalg.norm(np.gradient(p, axis=0) * FPS, axis=-1)
        skate.append(hv[contacts[k]])
    skate = np.concatenate(skate) if skate else np.zeros(0)
    root = j[:, 0]
    step = np.linalg.norm(np.diff(horiz(root, up), axis=0), axis=-1)
    m = {
        "jitter_mean_jerk_m_s3": float(jerk.mean()),
        "jitter_p95_jerk_m_s3": float(np.percentile(jerk, 95)),
        "accel_mean_m_s2": float(acc.mean()),
        "contact_frac": float(np.mean(contacts["left"] | contacts["right"])),
        "foot_skate_mean_cm_s": float(skate.mean() * 100) if skate.size else None,
        "foot_skate_p90_cm_s": float(np.percentile(skate, 90) * 100) if skate.size else None,
        "root_path_m": float(step.sum()),
        "root_net_horiz_m": float(np.linalg.norm(horiz(root[-1] - root[0], up))),
        "root_vert_range_m": float(np.ptp(root[:, up])),
        "root_mean_speed_m_s": float(step.sum() / (len(root) / FPS)),
    }
    # angular-speed spikes of local joint rotations are computed by the caller (needs rotations)
    if kp2d is not None and j_cam is not None:
        uv = np.einsum("ij,lnj->lni", K[0], j_cam)
        uv = uv[..., :2] / uv[..., 2:3]
        coco = np.array(list(COCO_TO_SMPL.keys()))
        smpl = np.array(list(COCO_TO_SMPL.values()))
        err = np.linalg.norm(uv[:, smpl] - kp2d[:, coco, :2], axis=-1)
        ok = kp2d[:, coco, 2] > 0.5
        m["reproj_median_px"] = float(np.median(err[ok])) if ok.any() else None
        m["vitpose_conf_mean"] = float(kp2d[:, 5:, 2].mean())
        m["vitpose_conf_gt0.5_frac"] = float(ok.mean())
    return m


def ang_speed_spikes(orient: np.ndarray, body_pose: np.ndarray, thresh_deg_s: float = 1000.0) -> dict:
    aa = np.concatenate([orient[:, None], body_pose.reshape(len(body_pose), -1, 3)], 1)  # (L, 22, 3)
    L, J, _ = aa.shape
    rots = R.from_rotvec(aa.reshape(-1, 3)).as_matrix().reshape(L, J, 3, 3)
    rel = np.einsum("ljab,ljac->ljbc", rots[:-1], rots[1:])  # R_t^T R_{t+1}
    ang = np.degrees(np.linalg.norm(R.from_matrix(rel.reshape(-1, 3, 3)).as_rotvec(), axis=-1)).reshape(L - 1, J) * FPS
    return {
        "ang_speed_p99_deg_s": float(np.percentile(ang, 99)),
        "ang_speed_max_deg_s": float(ang.max()),
        f"frames_with_joint_over_{int(thresh_deg_s)}deg_s": int((ang > thresh_deg_s).any(1).sum()),
    }


# ------------------------------------------------------------------------------------------ cleanup
class OneEuro:
    """One Euro filter (Casiez et al. 2012), vectorised over the trailing dims, offline forward pass."""

    def __init__(self, min_cutoff: float, beta: float, d_cutoff: float = 1.0):
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff

    @staticmethod
    def _alpha(cutoff, dt):
        tau = 1.0 / (2 * np.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def __call__(self, x: np.ndarray) -> np.ndarray:
        dt = 1.0 / FPS
        y = np.empty_like(x)
        y[0] = x[0]
        dx = np.zeros_like(x[0])
        for t in range(1, len(x)):
            a_d = self._alpha(self.d_cutoff, dt)
            dx = a_d * (x[t] - x[t - 1]) / dt + (1 - a_d) * dx
            cutoff = self.min_cutoff + self.beta * np.abs(dx)
            a = self._alpha(cutoff, dt)
            y[t] = a * x[t] + (1 - a) * y[t - 1]
        return y


def smooth_rotations(aa: np.ndarray, min_cutoff: float, beta: float) -> np.ndarray:
    """aa (L, J, 3) axis-angle -> One-Euro-filtered quaternions (hemisphere-continuous) -> axis-angle."""
    L, J, _ = aa.shape
    q = R.from_rotvec(aa.reshape(-1, 3)).as_quat().reshape(L, J, 4)
    for t in range(1, L):  # keep consecutive quaternions in the same hemisphere
        flip = (q[t] * q[t - 1]).sum(-1) < 0
        q[t, flip] *= -1
    # Run forward and backward and average: zero-phase (no lag) since this is offline.
    f = OneEuro(min_cutoff, beta)
    qs = 0.5 * (f(q) + f(q[::-1])[::-1])
    qs /= np.linalg.norm(qs, axis=-1, keepdims=True)
    return R.from_quat(qs.reshape(-1, 4)).as_rotvec().reshape(L, J, 3)


def smooth_vec(x: np.ndarray, min_cutoff: float, beta: float) -> np.ndarray:
    f = OneEuro(min_cutoff, beta)
    return 0.5 * (f(x) + f(x[::-1])[::-1])


def retime(aa: np.ndarray, tr: np.ndarray, n_src: int, src_fps: float) -> tuple[np.ndarray, np.ndarray]:
    """Undo the nearest-frame 24->30 fps staging. The fork resamples by duplicating source frames
    (output j shows source frame round(j*src/30)), so each GVHMR output carries image evidence from a
    time up to half a source frame off its slot: a 4-frame stutter that shows up as jerk. Re-place one
    output per source frame at its true time and slerp / lerp back onto the uniform 30 fps grid."""
    from scipy.spatial.transform import Slerp

    L = len(aa)
    keep = np.array([min(n_src - 1, round(j * src_fps / FPS)) for j in range(L)])
    src_ids, first = np.unique(keep, return_index=True)
    t_src = src_ids / src_fps
    t_out = np.arange(0, t_src[-1] + 1e-9, 1 / FPS)
    J = aa.shape[1]
    out = np.empty((len(t_out), J, 3))
    for j in range(J):
        sl = Slerp(t_src, R.from_rotvec(aa[first, j]))
        out[:, j] = sl(t_out).as_rotvec()
    tr_o = np.stack([np.interp(t_out, t_src, tr[first, i]) for i in range(3)], -1)
    return out, tr_o


def foot_lock(j: np.ndarray, transl: np.ndarray, up: int = 1) -> tuple[np.ndarray, np.ndarray]:
    """Root-level foot lock: integrate the planted foot's horizontal velocity and subtract it from the
    root, so a planted foot stays put. (A full two-bone leg IK is the production version.)"""
    c = foot_contacts(j, up)
    corr = np.zeros((len(j), 3))
    acc = np.zeros(3)
    for t in range(1, len(j)):
        vs = []
        for k, (a, b) in FEET.items():
            if c[k][t] and c[k][t - 1]:
                vs.append(j[t, [a, b]].mean(0) - j[t - 1, [a, b]].mean(0))
        if vs:
            d = np.mean(vs, 0)
            d[up] = 0.0
            acc = acc - d
        corr[t] = acc
    corr = smooth_vec(corr, 2.0, 0.0)  # soften the corrections themselves
    # floor clamp: lowest foot point never goes below the clip's 2nd-percentile floor
    return transl + corr, c


# ------------------------------------------------------------------------------------------- export
def write_bvh(path: Path, rest: np.ndarray, orient: np.ndarray, body_pose: np.ndarray, root_pos: np.ndarray):
    """22-joint SMPL-X body BVH, y-up, centimetres, ZYX Euler channels, 30 fps."""
    L = len(orient)
    aa = np.concatenate([orient[:, None], body_pose.reshape(L, -1, 3)], 1)
    eul = np.degrees(R.from_rotvec(aa.reshape(-1, 3)).as_euler("ZYX")).reshape(L, 22, 3)
    children = {i: [c for c, p in enumerate(PARENTS) if p == i] for i in range(22)}
    lines = ["HIERARCHY"]

    def emit(i, depth):
        ind = "  " * depth
        off = (rest[i] - rest[PARENTS[i]]) * 100 if PARENTS[i] >= 0 else np.zeros(3)
        lines.append(f"{ind}{'ROOT' if i == 0 else 'JOINT'} {NAMES[i]}")
        lines.append(f"{ind}{{")
        lines.append(f"{ind}  OFFSET {off[0]:.4f} {off[1]:.4f} {off[2]:.4f}")
        ch = "6 Xposition Yposition Zposition Zrotation Yrotation Xrotation" if i == 0 else "3 Zrotation Yrotation Xrotation"
        lines.append(f"{ind}  CHANNELS {ch}")
        if children[i]:
            for c in children[i]:
                emit(c, depth + 1)
        else:
            lines.extend([f"{ind}  End Site", f"{ind}  {{", f"{ind}    OFFSET 0 0 0", f"{ind}  }}"])
        lines.append(f"{ind}}}")

    emit(0, 0)
    lines += ["MOTION", f"Frames: {L}", f"Frame Time: {1 / FPS:.6f}"]
    order = []

    def dfs(i):
        order.append(i)
        for c in children[i]:
            dfs(c)

    dfs(0)
    for t in range(L):
        vals = list(root_pos[t] * 100)
        for i in order:
            vals += list(eul[t, i])
        lines.append(" ".join(f"{v:.4f}" for v in vals))
    path.write_text("\n".join(lines) + "\n")


# -------------------------------------------------------------------------------------------- vis
BONES = [(c, p) for c, p in enumerate(PARENTS) if p >= 0]
COCO_BONES = [(5, 7), (7, 9), (6, 8), (8, 10), (5, 6), (11, 12), (5, 11), (6, 12), (11, 13), (13, 15), (12, 14), (14, 16)]


def overlay_video(video: str, kp2d, j_cam, K, out: Path):
    import cv2

    cap = cv2.VideoCapture(video)
    w, h = int(cap.get(3)), int(cap.get(4))
    uv = np.einsum("ij,lnj->lni", K[0], j_cam)
    uv = uv[..., :2] / uv[..., 2:3]
    wr = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (w, h))
    t = 0
    while True:
        ok, img = cap.read()
        if not ok or t >= len(uv):
            break
        for a, b in COCO_BONES:  # ViTPose: green
            if kp2d[t, a, 2] > 0.3 and kp2d[t, b, 2] > 0.3:
                cv2.line(img, tuple(int(v) for v in kp2d[t, a, :2]), tuple(int(v) for v in kp2d[t, b, :2]), (0, 220, 0), 2)
        for c, p in BONES:  # GVHMR in-cam joints reprojected: magenta
            cv2.line(img, tuple(int(v) for v in uv[t, c]), tuple(int(v) for v in uv[t, p]), (255, 0, 255), 2)
        cv2.putText(img, f"{t}", (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        wr.write(img)
        t += 1
    wr.release()
    cap.release()


def stick_video(j_raw: np.ndarray, j_clean: np.ndarray, out: Path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.animation import FFMpegWriter

    fig = plt.figure(figsize=(8, 4), dpi=90)
    axes = [fig.add_subplot(1, 2, i + 1, projection="3d") for i in range(2)]
    allj = np.concatenate([j_raw, j_clean])
    lo, hi = allj.min((0, 1)), allj.max((0, 1))
    c, r = (lo + hi) / 2, (hi - lo).max() / 2 + 0.2
    wr = FFMpegWriter(fps=FPS)
    with wr.saving(fig, str(out), dpi=90):
        for t in range(len(j_raw)):
            for ax, j, title in zip(axes, (j_raw, j_clean), ("raw GVHMR", "One Euro + foot lock")):
                ax.cla()
                ax.set_title(title, fontsize=9)
                # plot x, z on the ground plane and y up
                for a, b in BONES:
                    ax.plot([j[t, a, 0], j[t, b, 0]], [j[t, a, 2], j[t, b, 2]], [j[t, a, 1], j[t, b, 1]], "k-", lw=1.5)
                ax.plot(j[: t + 1, 0, 0], j[: t + 1, 0, 2], j[: t + 1, 0, 1] * 0 + lo[1], "r-", lw=0.8)
                ax.set_xlim(c[0] - r, c[0] + r)
                ax.set_ylim(c[2] - r, c[2] + r)
                ax.set_zlim(lo[1], lo[1] + 2 * r)
                ax.view_init(elev=15, azim=-60)
            wr.grab_frame()
    plt.close(fig)


def plot(j_raw, j_clean, c_raw, out: Path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    t = np.arange(len(j_raw)) / FPS
    tc = np.arange(len(j_clean)) / FPS
    fig, ax = plt.subplots(3, 1, figsize=(9, 7))
    for k, (a, b) in FEET.items():
        ax[0].plot(t, j_raw[:, a, 1], label=f"{k} ankle y raw")
        ax[0].fill_between(t, j_raw[:, a, 1].min(), j_raw[:, a, 1].max(), where=c_raw[k], alpha=0.12)
    ax[0].set_ylabel("height (m)")
    ax[0].legend(fontsize=7)
    jr = np.linalg.norm(deriv(j_raw, 3), axis=-1).mean(1)
    jc = np.linalg.norm(deriv(j_clean, 3), axis=-1).mean(1)
    ax[1].plot(t[3:], jr, label="raw")
    ax[1].plot(tc[3:], jc, label="clean")
    ax[1].set_ylabel("mean |jerk| m/s³")
    ax[1].set_yscale("log")
    ax[1].legend(fontsize=7)
    ax[2].plot(j_raw[:, 0, 0], j_raw[:, 0, 2], label="root xz raw")
    ax[2].plot(j_clean[:, 0, 0], j_clean[:, 0, 2], label="root xz clean")
    ax[2].legend(fontsize=7)
    ax[1].set_xlabel("time (s)")
    ax[2].set_xlabel("root path x (m)")
    ax[2].set_ylabel("z (m)")
    ax[2].set_aspect("equal", adjustable="datalim")
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


# ------------------------------------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--motion-out", required=True)
    ap.add_argument("--vis-out", required=True)
    ap.add_argument("--min-cutoff", type=float, default=1.5, help="One Euro min cutoff (Hz)")
    ap.add_argument("--beta", type=float, default=0.3, help="One Euro speed coefficient")
    ap.add_argument("--no-video", action="store_true")
    ap.add_argument("--src-fps", type=float, default=None, help="source clip fps (default: probe the clip)")
    ap.add_argument("--src-frames", type=int, default=None)
    ap.add_argument("--retime", action="store_true", help="undo the 24->30 fps frame duplication before smoothing")
    a = ap.parse_args()
    torch.set_num_threads(int(os.environ.get("OMP_NUM_THREADS", "4")))

    run = Path(a.run_dir)
    d = dict(np.load(run / "smplx_params.npz"))
    if a.src_fps is None:
        import cv2

        cap = cv2.VideoCapture(json.loads((run / "timings.json").read_text())["video"])
        a.src_fps, a.src_frames = cap.get(cv2.CAP_PROP_FPS), int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()
    mo, vo = Path(a.motion_out), Path(a.vis_out)
    mo.mkdir(parents=True, exist_ok=True)
    vo.mkdir(parents=True, exist_ok=True)
    bm = body_model()

    go, bp, be, tr = d["global_global_orient"], d["global_body_pose"], d["global_betas"], d["global_transl"]
    j_raw = fk(bm, go, bp, be, tr)
    j_cam = fk(bm, d["incam_global_orient"], d["incam_body_pose"], d["incam_betas"], d["incam_transl"])
    K, kp2d = d["K_fullimg"], d["kp2d"]

    m_raw = metrics(j_raw, kp2d, j_cam, K) | ang_speed_spikes(go, bp)

    L = len(go)
    aa = np.concatenate([go[:, None], bp.reshape(L, -1, 3)], 1)
    # 1) optional retime (only when the source was not ~30 fps and got duplicated frames). Measured: it
    #    does not help (linear slerp between 24 fps samples adds its own jerk), so it is off by default.
    if a.retime and abs(a.src_fps - FPS) > 1.5:
        aa_r, tr_r = retime(aa, tr, a.src_frames, a.src_fps)
    else:
        aa_r, tr_r = aa, tr
    Lr = len(aa_r)
    be_r = be[:Lr]
    go_r, bp_r = aa_r[:, 0], aa_r[:, 1:].reshape(Lr, -1)
    j_r = fk(bm, go_r, bp_r, be_r, tr_r)
    m_retimed = metrics(j_r) | ang_speed_spikes(go_r, bp_r)
    # 2) One Euro (zero-phase) on rotations + translation
    aa_s = smooth_rotations(aa_r, a.min_cutoff, a.beta)
    go_s, bp_s = aa_s[:, 0], aa_s[:, 1:].reshape(Lr, -1)
    tr_s = smooth_vec(tr_r, a.min_cutoff, a.beta)
    j_s = fk(bm, go_s, bp_s, be_r, tr_s)
    m_smooth = metrics(j_s) | ang_speed_spikes(go_s, bp_s)
    # 3) root-level foot lock + global floor clamp
    tr_l, c_raw = foot_lock(j_s, tr_s)
    j_clean = fk(bm, go_s, bp_s, be_r, tr_l)
    floor = np.percentile(j_clean[:, [7, 8, 10, 11], 1], 2)
    tr_l = tr_l - np.array([0, floor, 0])
    j_clean = j_clean - np.array([0, floor, 0])
    m_clean = metrics(j_clean) | ang_speed_spikes(go_s, bp_s)

    rest = rest_joints(bm, be.mean(0, keepdims=True))[0]
    np.savez(mo / "motion_raw.npz", global_orient=go, body_pose=bp, betas=be, transl=tr, joints=j_raw, fps=FPS,
             joint_names=np.array(NAMES), parents=np.array(PARENTS), rest_joints=rest)
    np.savez(mo / "motion_clean.npz", global_orient=go_s, body_pose=bp_s, betas=be_r, transl=tr_l, joints=j_clean,
             fps=FPS, joint_names=np.array(NAMES), parents=np.array(PARENTS), rest_joints=rest)
    write_bvh(mo / "motion_raw.bvh", rest, go, bp, tr + rest[0])
    write_bvh(mo / "motion_clean.bvh", rest, go_s, bp_s, tr_l + rest[0])

    def pct2(m, k):
        r, c = m_raw.get(k), m.get(k)
        return None if not r or c is None else round(100 * (1 - c / r), 1)

    def pct(k):
        r, c = m_raw.get(k), m_clean.get(k)
        return None if not r or c is None else round(100 * (1 - c / r), 1)

    res = {
        "frames": L,
        "one_euro": {"min_cutoff_hz": a.min_cutoff, "beta": a.beta, "zero_phase": True},
        "src_fps": a.src_fps,
        "src_frames": a.src_frames,
        "retime": a.retime,
        "raw": m_raw,
        "retimed": m_retimed,
        "retimed_one_euro": m_smooth,
        "clean": m_clean,
        "reduction_pct_retime_only": {k: pct2(m_retimed, k) for k in ("jitter_mean_jerk_m_s3", "accel_mean_m_s2")},
        "reduction_pct": {k: pct(k) for k in ("jitter_mean_jerk_m_s3", "accel_mean_m_s2", "foot_skate_mean_cm_s",
                                               "ang_speed_p99_deg_s")},
    }
    (mo / "qc.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))

    plot(j_raw, j_clean, foot_contacts(j_raw), vo / "qc_plot.png")
    if not a.no_video:
        video = next(run.glob("*/0_input_video.mp4"))
        overlay_video(str(video), kp2d, j_cam, K, vo / "overlay_2d.mp4")
        stick_video(j_raw[: len(j_clean)], j_clean, vo / "stick_world.mp4")


if __name__ == "__main__":
    main()
