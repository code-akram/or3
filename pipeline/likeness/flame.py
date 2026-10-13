"""FLAME-format head model: loading, shape/expression blend, LBS, surface landmarks. numpy only.

Loads the FLAME pickle format (generic_model.pkl and later releases) without chumpy: a
restricted unpickler admits only numpy, scipy.sparse and stand-ins for the chumpy array class,
so a model file cannot run code on load. Also accepts the same buffers from a state dict (a
checkpoint that embeds a FLAME generator), given as a dict of arrays.

    m = load("generic_model.pkl")                # or from_buffers({...})
    v = m.shaped(beta, psi)                      # (V, 3) neutral-pose surface
    v = m.posed(beta, psi, pose)                 # pose: (J, 3) axis-angle (global, neck, jaw, eye_l, eye_r)
    lm = surface_points(v, m.faces, face_idx, bary)

The shape/expression split follows the file: the first n_shape (default 300) columns of
shapedirs are identity, the rest expression.
"""

import copyreg
import io
import pickle

import numpy as np

N_SHAPE = 300


class _Stub:
    """Stand-in for chumpy objects: keeps the pickled state; .x holds the array."""

    def __setstate__(self, state):
        self.__dict__.update(state if isinstance(state, dict) else {"state": state})


def _array(obj):
    if isinstance(obj, _Stub):
        if "x" in obj.__dict__:
            return np.asarray(obj.__dict__["x"])
        raise ValueError("model holds a derived chumpy expression, not a plain array")
    if hasattr(obj, "toarray"):                       # scipy.sparse
        return obj.toarray()
    return np.asarray(obj)


class _Unpickler(pickle.Unpickler):
    def find_class(self, module, name):
        if module.startswith("chumpy"):
            return _Stub
        if module in ("copy_reg", "copyreg") and name == "_reconstructor":
            return copyreg._reconstructor
        if module in ("__builtin__", "builtins") and name in ("object", "set", "frozenset", "slice"):
            return {"object": object, "set": set, "frozenset": frozenset, "slice": slice}[name]
        if module.startswith("numpy"):
            if name == "_reconstruct":
                from numpy._core.multiarray import _reconstruct
                return _reconstruct
            if name in ("ndarray", "dtype"):
                return getattr(np, name)
            if name == "scalar":
                from numpy._core.multiarray import scalar
                return scalar
        if module.startswith("scipy.sparse"):
            import scipy.sparse as sp
            if name in ("csc_matrix", "csr_matrix", "coo_matrix"):
                return getattr(sp, name)
        raise pickle.UnpicklingError(f"refusing global {module}.{name}")


def load_pickle(path):
    with open(path, "rb") as f:
        data = f.read()
    return _Unpickler(io.BytesIO(data), encoding="latin1").load()


class Flame:
    def __init__(self, v_template, shapedirs, posedirs, J_regressor, weights, parents, faces, n_shape=N_SHAPE):
        self.v_template = np.asarray(v_template, np.float64)
        V = len(self.v_template)
        sd = np.asarray(shapedirs, np.float64)
        self.shapedirs = sd.reshape(V, 3, -1)
        self.n_shape = min(n_shape, self.shapedirs.shape[2])
        self.n_expr = self.shapedirs.shape[2] - self.n_shape
        pd = np.asarray(posedirs, np.float64)
        # stored either (V, 3, P) / (V*3, P) as in the pickle, or (P, V*3) as in torch ports
        self.posedirs = pd.reshape(V * 3, -1) if pd.shape[0] in (V, V * 3) else pd.T.reshape(V * 3, -1)
        self.J_regressor = np.asarray(J_regressor, np.float64)
        self.weights = np.asarray(weights, np.float64)
        self.parents = np.asarray(parents, np.int64).copy()
        self.parents[0] = -1
        self.faces = np.asarray(faces, np.int64)

    # -------------------------------------------------------------------------- blend shapes
    def shaped(self, beta=None, psi=None):
        v = self.v_template.copy()
        if beta is not None and len(beta):
            b = np.asarray(beta, np.float64)
            v += self.shapedirs[:, :, :len(b)] @ b
        if psi is not None and len(psi):
            p = np.asarray(psi, np.float64)
            v += self.shapedirs[:, :, self.n_shape:self.n_shape + len(p)] @ p
        return v

    # -------------------------------------------------------------------------- skinning
    def posed(self, beta=None, psi=None, pose=None):
        v = self.shaped(beta, psi)
        if pose is None:
            return v
        pose = np.asarray(pose, np.float64).reshape(-1, 3)
        J = self.J_regressor @ v
        R = rodrigues(pose)
        eye = np.eye(3)
        feat = (R[1:] - eye).reshape(-1)
        v = v + (self.posedirs @ feat).reshape(-1, 3)
        G = np.zeros((len(J), 4, 4))
        for j in range(len(J)):
            T = np.eye(4)
            T[:3, :3] = R[j]
            T[:3, 3] = J[j] - (J[self.parents[j]] if j > 0 else 0)
            G[j] = T if j == 0 else G[self.parents[j]] @ T
        Gr = G.copy()
        Gr[:, :3, 3] -= np.einsum("jab,jb->ja", G[:, :3, :3], J)
        A = np.einsum("vj,jab->vab", self.weights, Gr)
        return np.einsum("vab,vb->va", A[:, :3, :3], v) + A[:, :3, 3]


def rodrigues(r):
    r = np.asarray(r, np.float64).reshape(-1, 3)
    th = np.linalg.norm(r, axis=1, keepdims=True)
    k = r / np.maximum(th, 1e-12)
    K = np.zeros((len(r), 3, 3))
    K[:, 0, 1], K[:, 0, 2], K[:, 1, 2] = -k[:, 2], k[:, 1], -k[:, 0]
    K[:, 1, 0], K[:, 2, 0], K[:, 2, 1] = k[:, 2], -k[:, 1], k[:, 0]
    s, c = np.sin(th)[:, :, None], np.cos(th)[:, :, None]
    return np.eye(3)[None] + s * K + (1 - c) * (K @ K)


def surface_points(v, faces, face_idx, bary):
    tri = v[faces[np.asarray(face_idx)]]                 # (L, 3, 3)
    return np.einsum("lk,lkd->ld", np.asarray(bary, np.float64), tri)


def from_pickle(obj, n_shape=N_SHAPE):
    d = obj if isinstance(obj, dict) else obj.__dict__
    return Flame(_array(d["v_template"]), _array(d["shapedirs"]), _array(d["posedirs"]),
                 _array(d["J_regressor"]), _array(d["weights"]), _array(d["kintree_table"])[0],
                 _array(d["f"]), n_shape)


def from_buffers(sd, prefix="", n_shape=N_SHAPE):
    """From a dict of arrays with torch-port names (v_template, shapedirs, posedirs, J_regressor,
    lbs_weights, parents, faces_tensor), optionally under a key prefix."""
    g = {k[len(prefix):]: (v.numpy() if hasattr(v, "numpy") else np.asarray(v))
         for k, v in sd.items() if k.startswith(prefix)}
    return Flame(g["v_template"], g["shapedirs"], g["posedirs"], g["J_regressor"], g["lbs_weights"],
                 g["parents"], g["faces_tensor"], n_shape)


def load(path, n_shape=N_SHAPE):
    return from_pickle(load_pickle(path), n_shape)


def load_embedding(path):
    """Landmark embedding .npz: lmk_face_idx (L,), lmk_b_coords (L, 3), and for a MediaPipe
    embedding landmark_indices (L,), the MediaPipe index of each row."""
    d = np.load(path, allow_pickle=False)
    out = {"face_idx": np.asarray(d["lmk_face_idx"], np.int64).reshape(-1),
           "bary": np.asarray(d["lmk_b_coords"], np.float64).reshape(-1, 3)}
    if "landmark_indices" in d:
        out["mp_index"] = np.asarray(d["landmark_indices"], np.int64).reshape(-1)
    return out


def write_obj(path, v, faces):
    with open(path, "w") as f:
        f.writelines(f"v {p[0]:.6f} {p[1]:.6f} {p[2]:.6f}\n" for p in v)
        f.writelines(f"f {t[0]} {t[1]} {t[2]}\n" for t in faces + 1)
