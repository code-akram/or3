"""Foot-contact detection and contact-aware leg IK for GVHMR output (Phase 0 spike 3 follow-up).

Replaces the first version's root-level lock, which cancelled the planted foot's slide by moving the
root: that removed 11-17 % of real travel and made skating worse. Here the root's horizontal path is
never touched. Each foot is pinned in world space during a contact and the legs reach it with analytic
two-bone IK (hip - knee - ankle on the SMPL-X chain), with smoothstep blend-in / blend-out windows. The
only root change is a minimal, smoothed vertical drop on frames where a pinned foot would be out of reach.

Pure numpy / scipy: works on the 22 SMPL-X body joints given rest joints (from betas), local axis-angle
rotations and root translation, with the same conventions as the SMPL-X layer (pelvis = rest[0] + transl).
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import gaussian_filter1d, maximum_filter1d
from scipy.spatial.transform import Rotation as R

FPS = 30.0
PARENTS = [-1, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 9, 9, 12, 13, 14, 16, 17, 18, 19]
LEGS = {"left": (1, 4, 7, 10), "right": (2, 5, 8, 11)}  # hip, knee, ankle, foot (ball/toe)
COCO_ANKLE = {"left": 15, "right": 16}
UP = 1  # y-up world (GVHMR's gravity-aligned frame)


# ------------------------------------------------------------------------------------------- FK
def aa_to_mat(aa: np.ndarray) -> np.ndarray:
    sh = aa.shape[:-1]
    return R.from_rotvec(aa.reshape(-1, 3)).as_matrix().reshape(*sh, 3, 3)


def mat_to_aa(m: np.ndarray) -> np.ndarray:
    sh = m.shape[:-2]
    return R.from_matrix(m.reshape(-1, 3, 3)).as_rotvec().reshape(*sh, 3)


def fk(rest: np.ndarray, rot: np.ndarray, transl: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """rest (L,22,3) rest joints, rot (L,22,3,3) local rotations, transl (L,3) -> world joints, world rots."""
    L, J = rot.shape[:2]
    G = np.empty_like(rot)
    P = np.empty((L, J, 3))
    G[:, 0] = rot[:, 0]
    P[:, 0] = rest[:, 0] + transl
    for i in range(1, J):
        p = PARENTS[i]
        G[:, i] = G[:, p] @ rot[:, i]
        P[:, i] = P[:, p] + np.einsum("lab,lb->la", G[:, p], rest[:, i] - rest[:, p])
    return P, G


# ------------------------------------------------------------------------------------ contacts
def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """[start, end) of each True run."""
    d = np.diff(np.concatenate([[0], mask.astype(np.int8), [0]]))
    return list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)))


def detect_contacts(
    j: np.ndarray,
    kp2d: np.ndarray | None = None,
    h_on: float = 0.05,
    h_off: float = 0.08,
    v_on: float = 0.30,
    v_off: float = 0.50,
    min_len: int = 5,
    max_gap: int = 2,
) -> dict[str, np.ndarray]:
    """Per-foot contact labels from foot height + speed, with hysteresis and a minimum duration.

    height: the foot's lowest point (ankle or ball) above the lower foot this frame, so stairs and slopes
            need no global floor.
    speed:  3D speed of the foot point (mean of ankle and ball), lightly smoothed.
    A contact starts when height < h_on and speed < v_on, and ends when height > h_off or speed > v_off.
    Gaps of <= max_gap frames are filled; contacts shorter than min_len frames are dropped.
    kp2d (COCO-17, with confidence): where ViTPose's ankle confidence is low the 3D foot is a guess, so the
    exit speed is relaxed (up to 2x at confidence 0) to keep contacts through occlusion noise.
    """
    L = len(j)
    low = {k: j[:, [a, b], UP].min(1) for k, (_, _, a, b) in LEGS.items()}
    lowest = np.minimum(low["left"], low["right"])
    out = {}
    for k, (_, _, a, b) in LEGS.items():
        p = gaussian_filter1d(j[:, [a, b]].mean(1), 1.0, axis=0, mode="nearest")
        v = np.linalg.norm(np.gradient(p, axis=0) * FPS, axis=-1)
        h = low[k] - lowest
        voff = np.full(L, v_off)
        if kp2d is not None:
            c = gaussian_filter1d(kp2d[:L, COCO_ANKLE[k], 2], 1.0, mode="nearest")
            voff = v_off * (1 + np.clip((0.5 - c) / 0.5, 0, 1))
        m = np.zeros(L, bool)
        on = False
        for t in range(L):
            if not on and h[t] < h_on and v[t] < v_on:
                on = True
            elif on and (h[t] > h_off or v[t] > voff[t]):
                on = False
            m[t] = on
        for s, e in _runs(~m):  # fill short gaps inside contacts
            if 0 < s and e < L and e - s <= max_gap:
                m[s:e] = True
        for s, e in _runs(m):
            if e - s < min_len:
                m[s:e] = False
        out[k] = m
    return out


# -------------------------------------------------------------------------------------- leg IK
def _norm(x, eps=1e-9):
    return x / np.maximum(np.linalg.norm(x, axis=-1, keepdims=True), eps)


def _angle(u, v):
    return np.arccos(np.clip((_norm(u) * _norm(v)).sum(-1), -1.0, 1.0))


def _axis_angle_mat(axis, ang):
    return R.from_rotvec(_norm(axis) * ang[:, None]).as_matrix()


def soft_reach(d: np.ndarray, r_max: np.ndarray, soft: float) -> np.ndarray:
    """Soft IK: distances above soft*r_max approach r_max exponentially instead of snapping the knee
    straight (the classic source of knee pops near full extension)."""
    rs = soft * r_max
    over = d > rs
    out = d.copy()
    span = r_max - rs
    out[over] = rs[over] + span[over] * (1 - np.exp(-(d[over] - rs[over]) / span[over]))
    return out


def two_bone_ik(rot, G, P, leg, target, idx, soft=0.98):
    """Analytic two-bone IK (hip-knee-ankle) on frames idx, in place on local rotations `rot`.

    Keeps the current knee plane (the pole is the current knee position), so the knee never swivels."""
    hip, knee, ank, _ = leg
    a, b, c, t = P[idx, hip], P[idx, knee], P[idx, ank], target[idx]
    lab = np.linalg.norm(b - a, axis=-1)
    lcb = np.linalg.norm(c - b, axis=-1)
    r_max = (lab + lcb) * 0.9995
    lat = soft_reach(np.linalg.norm(t - a, axis=-1), r_max, soft)
    lat = np.clip(lat, np.abs(lab - lcb) + 1e-4, r_max)
    ac_ab_0 = _angle(c - a, b - a)
    ba_bc_0 = _angle(a - b, c - b)
    ac_at_0 = _angle(c - a, t - a)
    ac_ab_1 = np.arccos(np.clip((lcb**2 - lab**2 - lat**2) / (-2 * lab * lat), -1, 1))
    ba_bc_1 = np.arccos(np.clip((lat**2 - lab**2 - lcb**2) / (-2 * lab * lcb), -1, 1))
    # bend axis: normal of the hip-knee-ankle plane; biased by the knee's hinge (-x in SMPL) so it stays
    # defined, and sign-stable, when the leg is nearly straight
    hinge = -G[idx, knee][:, :, 0]
    axis0 = _norm(np.cross(c - a, b - a) + 0.02 * (lab * lcb)[:, None] * hinge)
    axis1 = np.cross(c - a, t - a)
    ok1 = np.linalg.norm(axis1, axis=-1) > 1e-9
    axis1 = np.where(ok1[:, None], axis1, axis0)
    Gh_inv = np.swapaxes(G[idx, hip], -1, -2)
    Gk_inv = np.swapaxes(G[idx, knee], -1, -2)
    r0 = _axis_angle_mat(np.einsum("lab,lb->la", Gh_inv, axis0), ac_ab_1 - ac_ab_0)
    r1 = _axis_angle_mat(np.einsum("lab,lb->la", Gk_inv, axis0), ba_bc_1 - ba_bc_0)
    r2 = _axis_angle_mat(np.einsum("lab,lb->la", Gh_inv, axis1), ac_at_0)
    rot[idx, hip] = rot[idx, hip] @ r2 @ r0
    rot[idx, knee] = rot[idx, knee] @ r1


def _smoothstep(x):
    x = np.clip(x, 0, 1)
    return x * x * (3 - 2 * x)


def contact_targets(P, G, contacts, blend: int, heel_h: float = 0.015):
    """Per foot: weight w(t) in [0,1] (1 in contact, smoothstep ramps of `blend` frames on each side),
    the ankle target at full weight, and the foot's target world rotation (its own FK rotation: the foot
    keeps rolling heel-to-toe, only its position is pinned).

    Each contact has a heel phase (ankle within `heel_h` of its lowest height in the contact) where the
    ankle is pinned at its mean position, then a toe phase (heel-off) where the ball is pinned at the point
    it occupied at the switch, and the ankle target follows the foot's FK rotation about that ball. This
    keeps the natural heel rise instead of dragging the heel down to a mean height. A contact that starts
    on the toes (stairs, running) is toe phase throughout, pinned at the ball's mean position."""
    L = len(P)
    res = {}
    for k, (_, _, ank, ball) in LEGS.items():
        w = np.zeros(L)
        pos = P[:, ank].copy()
        rel = P[:, ball] - P[:, ank]  # FK ankle -> ball, world
        segs = _runs(contacts[k])
        for i, (s, e) in enumerate(segs):
            y = P[s:e, ank, UP]
            lo = int(np.argmin(y))
            above = np.flatnonzero(y[lo:] > y[lo] + heel_h)
            sw = s + lo + (above[0] if above.size else e - s - lo)  # first heel-off frame
            heel = y[: sw - s] <= y.min() + heel_h
            if heel.any():
                ank_anchor = P[s:sw, ank][heel].mean(0)
                ball_anchor = ank_anchor + rel[sw - 1]
            else:
                ank_anchor = None
                ball_anchor = P[s:e, ball].mean(0)
            # ramps never overlap the next contact's ramp (two anchors would fight mid-swing)
            b_in = blend if i == 0 else min(blend, (s - segs[i - 1][1]) // 2)
            b_out = blend if i == len(segs) - 1 else min(blend, (segs[i + 1][0] - e) // 2)
            for t in range(max(0, s - b_in), min(L, e + b_out)):
                if t < s:
                    wt = _smoothstep((t - (s - b_in - 1)) / (b_in + 1))
                elif t >= e:
                    wt = _smoothstep(((e + b_out) - t) / (b_out + 1))
                else:
                    wt = 1.0
                if wt > w[t]:
                    w[t] = wt
                    pos[t] = ank_anchor if (ank_anchor is not None and t < sw) else ball_anchor - rel[t]
        res[k] = (w, pos, G[:, ank].copy())
    return res


def lock_feet(rest, aa, transl, contacts, blend: int = 6, soft: float = 0.98, reach: float = 0.995,
              drop_sigma: float = 6.0, offset_sigma: float = 1.0, iters: int = 2):
    """Pin feet during contacts with two-bone leg IK. Returns (aa_new, transl_new, info).

    Root: horizontal untouched; vertical lowered only where a pinned ankle would be beyond `reach` x leg
    length (max-filtered, then Gaussian-smoothed with `drop_sigma` frames so the pelvis never bobs).
    Between soft and reach, soft IK leaves a millimetre-scale residual instead of locking the knee."""
    L = len(aa)
    rot = aa_to_mat(aa)
    P, G = fk(rest, rot, transl)
    tg = contact_targets(P, G, contacts, blend)
    # 1) minimal vertical root correction so every pinned ankle is reachable (hip drops by delta)
    need = np.zeros(L)
    for k, (hip, knee, ank, _) in LEGS.items():
        w, pos, _ = tg[k]
        tgt = P[:, ank] + w[:, None] * (pos - P[:, ank])
        d = tgt - P[:, hip]
        r = reach * (np.linalg.norm(rest[:, knee] - rest[:, hip], axis=-1)
                    + np.linalg.norm(rest[:, ank] - rest[:, knee], axis=-1))
        hz2 = (np.delete(d, UP, axis=-1) ** 2).sum(-1)
        dy = d[:, UP]
        delta = -np.sqrt(np.maximum(r**2 - hz2, 0)) - dy
        need = np.maximum(need, np.where(w > 0, np.maximum(delta, 0), 0))
    if need.any():
        w_max = 2 * int(np.ceil(2 * drop_sigma)) + 1
        drop = gaussian_filter1d(maximum_filter1d(need, size=w_max), drop_sigma, mode="nearest")
    else:
        drop = need
    transl = transl.copy()
    transl[:, UP] -= drop
    # 2) IK targets, fixed once from the (dropped) FK: offset = w * (pinned - FK), lightly smoothed in time
    #    (offset_sigma frames) so stance onsets and heel-off do not turn into velocity steps
    P, G = fk(rest, rot, transl)
    targets, active = {}, {}
    for k, (_, _, ank, _) in LEGS.items():
        w, pos, _ = tg[k]
        off = w[:, None] * (pos - P[:, ank])
        if offset_sigma > 0:
            off = gaussian_filter1d(off, offset_sigma, axis=0, mode="nearest")
        targets[k] = P[:, ank] + off
        active[k] = np.flatnonzero((w > 0) | (np.abs(off).max(-1) > 1e-5))
    # 3) IK, a couple of passes on the same targets (the hinge bias leaves a tiny residual on the first)
    for _ in range(iters):
        P, G = fk(rest, rot, transl)
        for k, leg in LEGS.items():
            if active[k].size:
                two_bone_ik(rot, G, P, leg, targets[k], active[k], soft)
    # 4) foot orientation: restore the foot's FK world rotation (the IK moved its parents), as local
    P, G = fk(rest, rot, transl)
    for k, (hip, knee, ank, _) in LEGS.items():
        _, _, prot = tg[k]
        for t in active[k]:
            rot[t, ank] = G[t, knee].T @ prot[t]
    P_new, _ = fk(rest, rot, transl)
    err = []
    for k, (_, _, ank, _) in LEGS.items():
        w, pos, _ = tg[k]
        m = w >= 1
        if m.any():
            err.append(np.linalg.norm(P_new[m, ank] - pos[m], axis=-1))
    err = np.concatenate(err) if err else np.zeros(1)
    info = {
        "contact_frac": {k: float(v.mean()) for k, v in contacts.items()},
        "n_contacts": {k: len(_runs(v)) for k, v in contacts.items()},
        "root_drop_max_cm": float(drop.max() * 100),
        "root_drop_mean_cm": float(drop.mean() * 100),
        "pin_err_mean_mm": float(err.mean() * 1000),
        "pin_err_max_mm": float(err.max() * 1000),
    }
    return mat_to_aa(rot), transl, info


# ------------------------------------------------------------------------------------- metrics
def slide_cm_s(j: np.ndarray, contacts: dict[str, np.ndarray], pivot: bool = False) -> float | None:
    """Mean horizontal speed on contact frames of the foot point (mean of ankle and ball), or with
    pivot=True of the slower of ankle and ball: the point the foot should be rolling over (a perfect
    heel-to-toe stance has a stationary pivot even though the mean point moves at heel-off)."""
    v = []
    for k, (_, _, a, b) in LEGS.items():
        hv = np.linalg.norm(np.gradient(np.delete(j[:, [a, b]], UP, axis=-1), axis=0) * FPS, axis=-1)  # (L, 2)
        hv = hv.min(1) if pivot else np.linalg.norm(
            np.gradient(np.delete(j[:, [a, b]].mean(1), UP, axis=-1), axis=0) * FPS, axis=-1)
        v.append(hv[contacts[k][: len(hv)]])
    v = np.concatenate(v)
    return float(v.mean() * 100) if v.size else None


def travel(j: np.ndarray) -> dict:
    """Root horizontal travel: net displacement, and path length of the 2 Hz low-passed root
    (so removing jitter does not count as losing travel)."""
    r = np.delete(j[:, 0], UP, axis=-1)
    lp = gaussian_filter1d(r, FPS / (2 * np.pi * 2.0), axis=0, mode="nearest")
    return {"net_m": float(np.linalg.norm(r[-1] - r[0])),
            "path_lp_m": float(np.linalg.norm(np.diff(lp, axis=0), axis=-1).sum())}


def knee_angles(j: np.ndarray) -> dict[str, np.ndarray]:
    """Interior knee flexion (deg, 0 = straight) per frame."""
    return {k: np.degrees(np.pi - _angle(j[:, hip] - j[:, knee], j[:, ank] - j[:, knee]))
            for k, (hip, knee, ank, _) in LEGS.items()}


def knee_pops(j_before: np.ndarray, j_after: np.ndarray, aa_before, aa_after, thresh: float = 500.0) -> dict:
    """Knee pops: frames where a knee's local rotation speed exceeds `thresh` deg/s.
    `new` counts frames that pop after the IK but did not before (same frame, same knee)."""
    def speed(aa):
        q = R.from_rotvec(aa[:, [4, 5]].reshape(-1, 3)).as_matrix().reshape(len(aa), 2, 3, 3)
        rel = np.einsum("ljab,ljac->ljbc", q[:-1], q[1:])
        return np.degrees(np.linalg.norm(mat_to_aa(rel), axis=-1)) * FPS  # (L-1, 2)

    sb, sa = speed(aa_before), speed(aa_after)
    kb, ka = knee_angles(j_before), knee_angles(j_after)
    flex_rate = {k: np.abs(np.diff(ka[k])) * FPS for k in ka}
    return {
        "knee_speed_p99_before_deg_s": float(np.percentile(sb, 99)),
        "knee_speed_p99_after_deg_s": float(np.percentile(sa, 99)),
        "knee_speed_max_after_deg_s": float(sa.max()),
        "pop_frames_before": int((sb > thresh).any(1).sum()),
        "pop_frames_after": int((sa > thresh).any(1).sum()),
        "new_pop_frames": int(((sa > thresh) & (sb <= thresh)).any(1).sum()),
        "knee_flex_rate_p99_after_deg_s": float(np.percentile(np.concatenate(list(flex_rate.values())), 99)),
        "knee_min_flex_after_deg": float(min(v.min() for v in ka.values())),
        "knee_min_flex_before_deg": float(min(v.min() for v in kb.values())),
    }
