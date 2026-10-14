"""The public face: an original identity authored in a statistical shape space, wrapped onto the
MPFB base mesh as the build's `head.identity` layer (blender/character/head_layer.py).

Prior: ICT-FaceKit (USC ICT, MIT licence; fetch_ict.sh). FLAME 2023 Open (CC BY 4.0) was the
first choice but needs the MPI login; FLAME 2020 (the private fan fit) is academic-only and must
not shape a public mesh. The coefficients are hand-chosen in sigma units from the character brief
(bench/m1/variants/public_identity.json), with no photo or person as input: original by
construction. Every input here must be public; this script refuses any path under private/.

    python -I author_public.py features --ict ICT [--n 30]            # what each component does
    python -I author_public.py mesh --ict ICT --out mesh.npz [--coeffs J] [--obj out.obj]
    python -I author_public.py base-mesh --base base.npz --out mesh.npz
    python -I author_public.py embed --mesh mesh.npz --views DIR --landmarks DIR --out emb.npz
    python -I author_public.py wrap --ict ICT --coeffs J --base base.npz --base-embedding E \
        --ict-embedding E --out public_face.npz

The views come from mesh_views.py (Blender), the landmarks from refboard.py measure (MediaPipe,
written to a mode-700 temp dir). bench/m1/identity.sh runs the whole chain.

Output public_face.npz: delta (n, 3) per base vertex (metres), base (n, 3) the base it was made
against, coeffs, prior ("ICT-FaceKit <commit>"), and the wrap notes. head_layer.py reads it.
"""

import argparse
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import containment  # noqa: E402
import ict  # noqa: E402

N_LANDMARKS = 478
IRIS = range(468, 478)


def public(*paths):
    for p in paths:
        if p and containment.is_private(p):
            raise SystemExit(f"author_public.py: public inputs and outputs only (refusing {p})")


def load_coeffs(path):
    if not path:
        return np.zeros(ict.N_ID)
    spec = json.load(open(path))
    c = np.zeros(ict.N_ID)
    for k, v in (spec.get("coefficients") or {}).items():
        c[int(k)] = float(v)
    lim = float(spec.get("max_sigma", 2.5))
    if np.abs(c).max() > lim + 1e-9:
        raise SystemExit(f"coefficient beyond {lim} sigma: {np.abs(c).max():.2f}")
    return c


def ict_commit(root):
    p = Path(root) / "COMMIT"
    return p.read_text().strip() if p.exists() else "unknown"


# ----------------------------------------------------------------------------------- features
def ict_features(m, v):
    """Coarse face measures on an ICT head (mm): widths at the cheekbone and jaw-angle heights,
    brow projection over the eye, chin projection, face height, nose length and projection,
    mouth width, forehead lean. Heights from the iBUG-68 landmark vertices of the kit."""
    L = v[m.ibug68]
    eye = 0.5 * (L[36:42].mean(0) + L[42:48].mean(0))
    nasion, tip, sub, chin = L[27], L[30], L[33], L[8]
    skin = m.verts_of("skin") & m.fitting
    S = v[skin]
    f = {}

    def width(z, front=-0.0):
        band = S[(np.abs(S[:, 2] - z) < 0.004) & (S[:, 1] < eye[1] + 0.06)]
        return (band[:, 0].max() - band[:, 0].min()) * 1000 if len(band) else np.nan
    f["bizygomatic"] = max(width(eye[2] - k) for k in (0.005, 0.012, 0.02))
    f["bigonial"] = width(chin[2] + 0.30 * (eye[2] - chin[2]))
    f["face_height"] = (nasion[2] - chin[2]) * 1000
    f["nose_length"] = (nasion[2] - sub[2]) * 1000
    f["nose_proj"] = (sub[1] - tip[1]) * 1000
    f["mouth_width"] = np.linalg.norm(L[54] - L[48]) * 1000
    f["lip_height"] = (L[51][2] - L[57][2]) * 1000
    pupil_x = L[42:48, 0].mean()
    line = S[np.abs(S[:, 0] - pupil_x) < 0.004]
    cornea = v[m.verts_of("iris") & (v[:, 0] > 0)][:, 1].min()
    brow = line[(line[:, 2] > eye[2] + 0.008) & (line[:, 2] < eye[2] + 0.03)]
    f["brow_over_cornea"] = (cornea - brow[:, 1].min()) * 1000
    fh = line[np.abs(line[:, 2] - (eye[2] + 0.055)) < 0.004]
    f["forehead_behind_brow"] = (fh[:, 1].min() - brow[:, 1].min()) * 1000
    f["chin_proj"] = (sub[1] - S[np.abs(S[:, 0]) < 0.004][(S[np.abs(S[:, 0]) < 0.004][:, 2] < L[57][2])][:, 1].min()) * 1000
    f["eye_width"] = np.linalg.norm(L[45] - L[42]) * 1000
    f["ipd"] = np.linalg.norm(L[42:48].mean(0) - L[36:42].mean(0)) * 1000
    f["zyg_ipd"] = f["bizygomatic"] / f["ipd"]
    f["jaw_cheek"] = f["bigonial"] / f["bizygomatic"]
    f["eye_menton_zyg"] = (eye[2] - chin[2]) * 1000 / f["bizygomatic"]
    # jaw corner: iBUG 3/13 (lower jaw contour near the gonion), sagittal projection
    go = 0.5 * (L[3] + L[13])
    f["gonion_drop"] = (eye[2] - go[2]) / (eye[2] - chin[2])
    f["mand_plane_deg"] = float(np.degrees(np.arctan2(go[2] - chin[2], go[1] - chin[1])))
    tr = 0.5 * (L[0] + L[16])
    a, b = (chin - go)[1:], (tr - go)[1:]
    f["gonial3_deg"] = float(np.degrees(np.arccos(a @ b / np.linalg.norm(a) / np.linalg.norm(b))))
    return f


def solve(m, targets, n, c0, reg=0.05, iters=4):
    """Suggest coefficients (first n components) that move the named features toward
    targets {feature: (value, weight)} with the least coefficient norm (Gauss-Newton with a
    ridge on c). A drafting aid for the hand-chosen set, not the set itself."""
    c = np.array(c0[:n], np.float64)
    keys = list(targets)
    for _ in range(iters):
        f0 = ict_features(m, m.shaped(c))
        J = np.zeros((len(keys), n))
        for k in range(n):
            e = c.copy()
            e[k] += 0.5
            f1 = ict_features(m, m.shaped(e))
            J[:, k] = [(f1[q] - f0[q]) / 0.5 for q in keys]
        w = np.array([targets[q][1] for q in keys])
        r = np.array([targets[q][0] - f0[q] for q in keys]) * w
        A = J * w[:, None]
        dc = np.linalg.solve(A.T @ A + reg * np.eye(n), A.T @ r - reg * c)
        c = np.clip(c + dc, -2.5, 2.5)
    return c


def cmd_features(a):
    m = ict.load(a.ict, a.n)
    f0 = ict_features(m, m.neutral)
    keys = list(f0)
    print("pc   " + " ".join(f"{k[:10]:>10s}" for k in keys))
    print("mean " + " ".join(f"{f0[k]:10.2f}" for k in keys))
    for k in range(a.n):
        c = np.zeros(a.n)
        c[k] = 1.0
        f1 = ict_features(m, m.shaped(c))
        print(f"{k:3d}  " + " ".join(f"{f1[q] - f0[q]:+10.2f}" for q in keys))
    if a.coeffs:
        c = load_coeffs(a.coeffs)
        f1 = ict_features(m, m.shaped(c[:a.n]))
        print("auth " + " ".join(f"{f1[q]:10.2f}" for q in keys))
        spec = json.load(open(a.coeffs)).get("solve_targets")
        if spec:
            s = solve(m, {k: tuple(v) for k, v in spec.items() if not k.startswith("$")}, a.n, c)
            f2 = ict_features(m, m.shaped(s))
            print("solv " + " ".join(f"{f2[q]:10.2f}" for q in keys))
            print("suggested: " + json.dumps({str(k): round(float(x), 1) for k, x in enumerate(s) if abs(x) >= 0.25}))


# ----------------------------------------------------------------------------------- meshes
def paint_iris(V, F, part, iris_mm=5.9):
    """Re-label eyeball triangles (part 1 or 2) by direction: within the iris cone of each eye's
    sphere (forward = -y) iris (2), else sclera (1), so a landmarker sees an iris on any eye mesh."""
    part = part.copy()
    eye_t = np.nonzero((part == 1) | (part == 2))[0]
    for side in (1, -1):
        t = eye_t[V[F[eye_t]].mean(1)[:, 0] * side > 0]
        if not len(t):
            continue
        P = V[np.unique(F[t])]
        A = np.c_[2 * P, np.ones(len(P))]
        sol = np.linalg.lstsq(A, (P ** 2).sum(1), rcond=None)[0]
        c, r = sol[:3], float(np.sqrt(sol[3] + sol[:3] @ sol[:3]))
        u = V[F[t]].mean(1) - c
        cosang = -u[:, 1] / np.linalg.norm(u, axis=1)
        part[t] = np.where(cosang > np.cos(np.arcsin(min(iris_mm / 1000 / r, 0.9))), 2, 1)
    return part


def cmd_mesh(a):
    public(a.out, a.obj, a.coeffs)
    m = ict.load(a.ict)
    v = m.shaped(load_coeffs(a.coeffs))
    iris = m.verts_of("iris")
    centre = v[iris].mean(0) + np.array([0, 0, -0.035])
    np.savez(a.out, V=v, F=m.faces, part=paint_iris(v, m.faces, m.part), centre=centre)
    if a.obj:
        ict.write_obj(a.obj, v, m.faces)
    print(f"[mesh] ICT {len(v)} verts, {len(m.faces)} tris -> {a.out}")


def base_polys(d):
    lv, ls, lt = d["loop_verts"], d["poly_start"], d["poly_total"]
    return [lv[s:s + t] for s, t in zip(ls, lt)]


def cmd_base_mesh(a):
    """The dumped base mesh as a landmarker mesh: skin, the eye-helper spheres with a painted
    iris (paint_iris), the rest hidden."""
    public(a.base, a.out)
    d = np.load(a.base)
    co = d["co"]
    names = [str(n) for n in d["group_names"]]
    W = d["group_weights"]
    helper = W[:, names.index("HelperGeometry")] > 0
    if "JointCubes" in names:
        helper |= W[:, names.index("JointCubes")] > 0
    eye = (W[:, names.index("helper-l-eye")] > 0) | (W[:, names.index("helper-r-eye")] > 0)
    tris, part = [], []
    for p in base_polys(d):
        for k in range(1, len(p) - 1):
            t = (p[0], p[k], p[k + 1])
            tris.append(t)
            if not helper[list(t)].any():
                part.append(0)
            elif eye[list(t)].all():
                part.append(1)
            else:
                part.append(3)
    centre = 0.5 * (d["eye_l"] + d["eye_r"]) + np.array([0, 0, -0.035])
    F = np.array(tris, np.int64)
    np.savez(a.out, V=co, F=F, part=paint_iris(co, F, np.array(part, np.int8)), centre=centre)
    print(f"[base-mesh] {len(tris)} tris -> {a.out}")


# ----------------------------------------------------------------------------------- embed
def triangulate(O, D, iters=6, scale=0.002):
    """Point nearest a bundle of rays (Cauchy-reweighted); returns point and weighted rms."""
    w = np.ones(len(O))
    for _ in range(iters):
        A = np.zeros((3, 3))
        b = np.zeros(3)
        for o, d, wi in zip(O, D, w):
            P = np.eye(3) - np.outer(d, d)
            A += wi * P
            b += wi * P @ o
        p = np.linalg.solve(A, b)
        r = np.array([np.linalg.norm((np.eye(3) - np.outer(d, d)) @ (p - o)) for o, d in zip(O, D)])
        w = 1.0 / (1.0 + (r / scale) ** 2)
    return p, float(np.sqrt((w * r ** 2).sum() / w.sum()))


def closest_point_tris(V, F, P):
    import wrap
    q, dist, fid = wrap.closest_on_mesh(V, F, P)
    T = V[F[fid]]
    # barycentrics of q in its triangle
    v0, v1, v2 = T[:, 1] - T[:, 0], T[:, 2] - T[:, 0], q - T[:, 0]
    d00, d01, d11 = (v0 * v0).sum(1), (v0 * v1).sum(1), (v1 * v1).sum(1)
    d20, d21 = (v2 * v0).sum(1), (v2 * v1).sum(1)
    den = d00 * d11 - d01 * d01
    b1 = (d11 * d20 - d01 * d21) / den
    b2 = (d00 * d21 - d01 * d20) / den
    bary = np.clip(np.stack([1 - b1 - b2, b1, b2], 1), 0, 1)
    return fid, bary / bary.sum(1, keepdims=True), dist


def cmd_embed(a):
    public(a.mesh, a.views, a.out)
    m = np.load(a.mesh)
    V, F, part = m["V"], m["F"], m["part"]
    cams = json.load(open(Path(a.views) / "cameras.json"))["views"]
    rays = {i: [] for i in range(N_LANDMARKS)}
    for name, c in cams.items():
        p = Path(a.landmarks) / f"{name}_lm.npy"
        if not p.exists():
            print(f"[embed] no landmarks for {name}")
            continue
        lm = np.load(p)
        if len(lm) < N_LANDMARKS:
            continue
        K = np.array(c["K"])
        c2w = np.linalg.inv(np.array(c["world_to_cam"]))
        o = c2w[:3, 3]
        for i, (u, v) in enumerate(lm[:, :2]):
            d = c2w[:3, :3] @ np.array([(u - K[0, 2]) / K[0, 0], (v - K[1, 2]) / K[1, 1], 1.0])
            rays[i].append((o, d / np.linalg.norm(d)))
    skin = F[part == 0]
    skin_ids = np.nonzero(part == 0)[0]
    pts, res = np.zeros((N_LANDMARKS, 3)), np.full(N_LANDMARKS, np.inf)
    for i, rr in rays.items():
        if len(rr) >= 2 and i not in IRIS:
            pts[i], res[i] = triangulate(np.array([r[0] for r in rr]), np.array([r[1] for r in rr]))
    ok = res < a.max_rms_mm / 1000.0
    fid, bary, dist = closest_point_tris(V, skin, pts[ok])
    ok_idx = np.nonzero(ok)[0]
    near = dist < a.max_off_mm / 1000.0
    valid = np.zeros(N_LANDMARKS, bool)
    valid[ok_idx[near]] = True
    tri_verts = np.zeros((N_LANDMARKS, 3), np.int64)
    bary_all = np.zeros((N_LANDMARKS, 3))
    face_all = np.zeros(N_LANDMARKS, np.int64)
    tri_verts[ok_idx] = skin[fid]
    bary_all[ok_idx] = bary
    face_all[ok_idx] = skin_ids[fid]
    v = np.nonzero(valid)[0]
    np.savez(a.out, mp_index=np.arange(N_LANDMARKS), tri_verts=tri_verts, bary=bary_all, valid=valid,
             triangulation_rms_m=res, landmark_indices=v, lmk_face_idx=face_all[v], lmk_b_coords=bary_all[v])
    print(f"[embed] {valid.sum()} of {N_LANDMARKS} landmarks; ray rms median "
          f"{np.median(res[ok]) * 1000:.2f} mm; mesh offset median {np.median(dist[near]) * 1000:.2f} mm")


# ----------------------------------------------------------------------------------- wrap
def wrap_args(**over):
    """wrap.py's CLI defaults (pipeline/likeness/wrap.py main), as a namespace."""
    a = dict(metric=False, neck_top=0.13, neck_bottom=0.21, rbf_smoothing=1e-5, hold_cranium_dy=0.05,
             eye_core_mm=1.5, eye_fade_mm=8.0, iters=5, smooth=6, step=0.8, max_dist=0.015,
             symmetrise=True, outlier_mm=4.0)
    a.update(over)
    return SimpleNamespace(**a)


NOSTRIL_LM = (64, 294, 129, 358, 98, 327, 48, 278)    # MediaPipe alar base / alar crease points


def clean_delta(base, delta, TV, TFt, notes, band_iters=12, relax_iters=40, spike_mm=1.0, emb=None):
    """Post-wrap clean-up of the public delta (the fan path keeps wrap.py as it is):
    1. seam: where the wrapped skin did not land on the trusted target surface (beyond 1 mm),
       the field is extrapolated, and its edge shows as a crease at the temple and jaw; blend
       toward a relaxed (Laplacian-smoothed) field over a band around that edge;
    2. ears: rigid, with the mean field of the skin ring around each ear (the ear shape is the
       base's; the wrap distrusts it);
    3. spikes: a vertex whose offset differs from its neighbours' mean by more than spike_mm
       takes the mean (mouth corners, lid folds);
    4. nostrils: around the alar base (emb: the base landmark embedding) the field is relaxed, so
       the outer skin and the nostril's inner wall move together (the snapped outer skin otherwise
       sinks behind the inner wall, which then shows through the cheek), and the cavity walls
       there follow the outer skin in front of them."""
    import wrap
    co = base.co
    skin = base.skin
    out = delta.copy()
    idx = np.nonzero(skin & (np.linalg.norm(delta, axis=1) > 0))[0]
    _, dist, _ = wrap.closest_on_mesh(TV, TFt, (co + delta)[idx])
    on = np.zeros(len(co))
    on[idx[dist < 0.001]] = 1.0
    w = base.smooth(on, band_iters)                       # 1 deep inside, 0 outside, ramp at the edge
    w = np.clip((w - 0.15) / 0.7, 0, 1)
    relaxed = base.smooth(delta, relax_iters)
    out = w[:, None] * delta + (1 - w[:, None]) * relaxed
    out[base.helper] = delta[base.helper]
    ears = base.group("ears") > 0
    for side in (1, -1):
        e = ears & (co[:, 0] * side > 0)
        if not e.any():
            continue
        c = co[e].mean(0)
        r = np.linalg.norm(co - c, axis=1)
        ring = skin & ~ears & (r < np.linalg.norm(co[e] - c, axis=1).max() + 0.012)
        out[e] = out[ring].mean(0)
    nspike = 0
    for _ in range(3):
        avg = base.avg @ out
        bad = skin & ~base.helper & base.has_nbr & (np.linalg.norm(out - avg, axis=1) > spike_mm / 1000.0)
        nspike += int(bad.sum())
        out[bad] = avg[bad]
    nrel = 0
    if emb is not None:
        ok = [i for i in NOSTRIL_LM if emb["valid"][i]]
        P = np.einsum("lk,lkd->ld", emb["bary"][ok], co[emb["tri_verts"][ok]])
        d = np.min(np.linalg.norm(co[:, None, :] - P[None, :, :], axis=2), axis=1)
        wn = (1 - np.clip((d - 0.008) / 0.010, 0, 1)) * (skin & ~base.helper)
        out = out + wn[:, None] * (base.smooth(out, 2 * relax_iters) - out)
        nrel = int((wn > 0).sum())
        # the nasal cavity walls behind the alar groove (base normals facing back) take the field
        # of the outer skin in front of them (t7b): relaxed or not, the snapped groove skin moved
        # back ~2 mm more than the cavity behind it, and the cavity wall poked through the cheek
        # beside each ala (back faces seen from the front: the engine's teal specks)
        nb = base.normals(co)
        near = (d < 0.025) & skin & ~base.helper
        inner = np.nonzero(near & (nb[:, 1] > 0.2))[0]
        outer = np.nonzero(near & (nb[:, 1] < -0.2))[0]
        if len(inner) and len(outer):
            dxz = co[inner][:, None, [0, 2]] - co[outer][None, :, [0, 2]]
            wgt = np.exp(-0.5 * (dxz ** 2).sum(2) / 0.002 ** 2) * (co[outer][None, :, 1] < co[inner][:, None, 1])
            tot = wgt.sum(1)
            ok_ = tot > 1e-3
            follow = (wgt @ out[outer]) / np.maximum(tot, 1e-12)[:, None]
            out[inner[ok_]] = follow[ok_]
            notes["cavity_follow_verts"] = int(ok_.sum())
    notes["clean"] = {"on_target_verts": int(on.sum()), "spikes_fixed": nspike, "nostril_relaxed_verts": nrel}
    return out


def cmd_wrap(a):
    public(a.ict, a.coeffs, a.base, a.base_embedding, a.ict_embedding, a.out)
    import wrap
    t0 = time.time()
    m = ict.load(a.ict)
    c = load_coeffs(a.coeffs)
    TV = m.shaped(c)
    base = wrap.Base(a.base)
    be = np.load(a.base_embedding)
    te = np.load(a.ict_embedding)
    t_idx = np.asarray(te["landmark_indices"])
    shared = [k for k, i in enumerate(t_idx) if be["valid"][i]]
    mp = t_idx[shared]
    lm_t = np.einsum("lk,lkd->ld", te["lmk_b_coords"][shared], TV[m.faces[te["lmk_face_idx"][shared]]])
    tri_b, bary_b = be["tri_verts"][mp], be["bary"][mp]
    wa = wrap_args(iters=a.iters)
    wa._lm_tb = (tri_b, bary_b)
    # trusted target: the kit's face fitting region, skin only
    trusted = m.fitting & m.verts_of("skin")
    TF = m.faces[m.part == 0]
    delta, notes, TVa = wrap.wrap(base, wrap.embedded_points(base.co, tri_b, bary_b), lm_t, TV, TF, trusted, wa)
    delta = clean_delta(base, delta, TVa, TF[trusted[TF].all(1)], notes, emb=be)
    notes["shared_landmarks"] = len(mp)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, delta=delta.astype(np.float32), base=base.co.astype(np.float32), coeffs=c,
                        prior=f"ICT-FaceKit {ict_commit(a.ict)} (MIT)", notes=json.dumps(notes))
    print(f"[wrap] {len(mp)} shared landmarks, {time.time() - t0:.0f} s; landmark rms "
          f"{notes['landmark_rms_before_mm']:.2f} -> {notes['landmark_rms_final_mm']:.2f} mm; "
          f"max move {notes['max_move_mm']:.1f} mm -> {out}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="author_public.py", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("features")
    s.add_argument("--ict", required=True)
    s.add_argument("--n", type=int, default=30)
    s.add_argument("--coeffs", default="")
    s = sub.add_parser("mesh")
    s.add_argument("--ict", required=True)
    s.add_argument("--coeffs", default="")
    s.add_argument("--out", required=True)
    s.add_argument("--obj", default="")
    s = sub.add_parser("base-mesh")
    s.add_argument("--base", required=True)
    s.add_argument("--out", required=True)
    s = sub.add_parser("embed")
    s.add_argument("--mesh", required=True)
    s.add_argument("--views", required=True)
    s.add_argument("--landmarks", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--max-rms-mm", type=float, default=3.0)
    s.add_argument("--max-off-mm", type=float, default=4.0)
    s = sub.add_parser("wrap")
    s.add_argument("--ict", required=True)
    s.add_argument("--coeffs", required=True)
    s.add_argument("--base", required=True)
    s.add_argument("--base-embedding", required=True)
    s.add_argument("--ict-embedding", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--iters", type=int, default=5)
    a = ap.parse_args(argv)
    {"features": cmd_features, "mesh": cmd_mesh, "base-mesh": cmd_base_mesh, "embed": cmd_embed,
     "wrap": cmd_wrap}[a.cmd](a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
