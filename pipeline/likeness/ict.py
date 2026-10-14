"""ICT-FaceKit identity model (USC ICT, MIT licence): loader and shape blend. numpy only.

The model (fetched by fetch_ict.sh into <main checkout>/data/raw/ict-facekit/) is a generic
neutral mesh plus 100 identity shapes stored as full meshes; identity k minus the neutral is the
k-th principal direction scaled to one standard deviation (the kit samples identities as
N(0, 1) weights), so a coefficient is in sigma units:

    m = load(ROOT)                       # neutral + identity deltas, Blender frame, metres
    v = m.shaped(coeffs)                 # (V, 3)
    m.faces, m.part                      # triangles (fan order of the OBJ faces), part per triangle

Frame: the kit is y-up, z-forward, centimetres; here it is converted to the build's frame
(z up, -y forward, metres). Triangles are the OBJ polygons fanned in file order, the same order
wrap.read_obj produces, so a written OBJ and these arrays index alike.

Parts (per triangle, from the OBJ materials): skin (M_Face, M_BackHead), sclera, iris, and
"other" (mouth interior, teeth, lacrimal fluid, eye blend/occlusion shells, lashes). `fitting`
marks the kit's own fitting region (idx_to_fitting_verts): the face proper.
"""

import json
from pathlib import Path

import numpy as np

ICT_TO_BLENDER = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], np.float64) * 0.01
PARTS = {"M_Face": "skin", "M_BackHead": "skin", "M_ScleraLeft": "sclera", "M_ScleraRight": "sclera",
         "M_IrisLeft": "iris", "M_IrisRight": "iris"}
PART_IDS = {"skin": 0, "sclera": 1, "iris": 2, "other": 3}
N_ID = 100


def read_obj(path, with_parts=False):
    v, f, part = [], [], []
    cur = "other"
    with open(path) as fh:
        for line in fh:
            if line.startswith("v "):
                v.append([float(x) for x in line.split()[1:4]])
            elif line.startswith("usemtl"):
                cur = PARTS.get(line.split()[1], "other")
            elif line.startswith("f ") and with_parts:
                idx = [int(t.split("/")[0]) - 1 for t in line.split()[1:]]
                for k in range(1, len(idx) - 1):
                    f.append((idx[0], idx[k], idx[k + 1]))
                    part.append(PART_IDS[cur])
    V = np.array(v, np.float64)
    if with_parts:
        return V, np.array(f, np.int64), np.array(part, np.int8)
    return V


class Ict:
    def __init__(self, root, n=N_ID):
        d = Path(root) / "FaceXModel"
        V0, F, part = read_obj(d / "generic_neutral_mesh.obj", with_parts=True)
        self.neutral = V0 @ ICT_TO_BLENDER.T
        self.faces, self.part = F, part
        self.deltas = np.stack([read_obj(d / f"identity{k:03d}.obj") @ ICT_TO_BLENDER.T - self.neutral
                                for k in range(n)])
        idx = json.load(open(d / "vertex_indices.json"))
        self.fitting = np.zeros(len(V0), bool)
        self.fitting[np.asarray(idx["idx_to_fitting_verts"], np.int64)] = True
        self.ibug68 = np.asarray(idx["idx_to_landmark_verts"], np.int64)

    def shaped(self, coeffs):
        c = np.zeros(len(self.deltas))
        c[:min(len(coeffs), len(c))] = np.asarray(coeffs, np.float64)[:len(c)]
        return self.neutral + np.tensordot(c, self.deltas, 1)

    def verts_of(self, part):
        m = np.zeros(len(self.neutral), bool)
        m[self.faces[self.part == PART_IDS[part]].ravel()] = True
        return m


def load(root, n=N_ID):
    return Ict(root, n)


def write_obj(path, v, faces):
    with open(path, "w") as f:
        f.writelines(f"v {p[0]:.6f} {p[1]:.6f} {p[2]:.6f}\n" for p in v)
        f.writelines(f"f {t[0]} {t[1]} {t[2]}\n" for t in faces + 1)
