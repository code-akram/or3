"""Corrective morph targets baked from delta mush plus layer collision
(m1 v2 Track F; bench/m1/v2/deform.md).

For each corrective (one joint, one target pose, both sides):

1. pose the staged rig into the target pose (one joint moved, the helper
   rules applied: deform_runtime.Runtime);
2. per mesh, evaluate plain linear blend skinning (X) and the same with a
   Corrective Smooth (delta mush) modifier restricted to a soft region around
   the joint (Y). Delta mush keeps the rest-pose surface detail relative to a
   smoothed surface, so it removes the LBS collapse, pinch and candy wrapper
   without hand sculpting;
3. resolve the layers in that pose: an outer garment that an inner layer now
   pokes through is pushed out to a small clearance (shirt < tie < trousers <
   waistcoat < jacket); body skin that a garment covers in the rest pose and
   now pokes out is pushed in (it is hidden anyway). Small attached meshes
   (buttons) follow the nearest point of their garment;
4. un-skin the pose-space delta into rest space with the vertex's own blended
   bone matrix (d_rest = M_v^-1 (Y - X)), so with the morph applied before
   skinning (glTF order) the target pose reproduces Y exactly;
5. store it as shape key `<name>_<side>`, and a `cone` driver rule
   (deform_runtime.py): weight 1 at the target pose, 0 at rest and beyond.

The garments are found by name fragment, so a rebuilt suit gets fresh
correctives on the next build. Morph targets export with export_morph (the
exporter writes sparse accessors, so untouched vertices cost nothing).
"""

import math

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

from . import deform_poses as dp
from . import deform_rig as drig
from . import deform_runtime as drt

# name, bone, ops, driver ref, region (bone whose head is the centre, radius m)
SPECS = [
    {"name": "corr_arm_up", "bone": "upperarm", "ops": [["aim", [1.0, 0.0, 0.087]]],
     "ref": "clavicle", "region": ("upperarm", 0.22)},
    {"name": "corr_arm_fwd", "bone": "upperarm", "ops": [["aim", [0.12, -1.0, 0.087]]],
     "ref": "clavicle", "region": ("upperarm", 0.22)},
    {"name": "corr_arm_down", "bone": "upperarm", "ops": [["aim", [0.17, 0.02, -1.0]]],
     "ref": "clavicle", "region": ("upperarm", 0.20)},
    {"name": "corr_elbow", "bone": "lowerarm", "ops": [["flex", 86]],
     "ref": "upperarm", "region": ("lowerarm", 0.14)},
    {"name": "corr_hip_fwd", "bone": "thigh", "ops": [["flex", 95]],
     "ref": "pelvis", "region": ("thigh", 0.26)},
    {"name": "corr_knee", "bone": "calf", "ops": [["flex", 120]],
     "ref": "thigh", "region": ("calf", 0.16)},
]
# inner part -> outer parts, processed in this order (outer garments pushed out)
GARMENT_ORDER = ["shirt", "tie", "trousers", "waistcoat", "jacket"]
COVERS = {"tie": ["shirt"], "trousers": ["shirt"], "waistcoat": ["shirt", "tie", "trousers"],
          "jacket": ["shirt", "tie", "waistcoat", "trousers"]}
BODY_UNDER = ["shirt", "waistcoat", "jacket", "trousers"]
ATTACH = {"buttons": "jacket"}


def part(o):
    if o.name == "Human_export":
        return "body"
    for k in ("shirt", "waistcoat", "jacket", "trousers", "tie", "buttons"):
        if f"suit_{k}" in o.name:
            return k
    return None


def _eval_co(o, dg):
    ev = o.evaluated_get(dg)
    me = ev.to_mesh()
    co = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get("co", co)
    ev.to_mesh_clear()
    return co.reshape(-1, 3)


def _polys(o):
    return [tuple(p.vertices) for p in o.data.polygons]


def _boundary_faces(o):
    cnt = {}
    for p in o.data.polygons:
        for e in p.edge_keys:
            cnt[e] = cnt.get(e, 0) + 1
    bv = set()
    for e, c in cnt.items():
        if c == 1:
            bv.update(e)
    return {p.index for p in o.data.polygons if any(v in bv for v in p.vertices)}


def _adjacency(o):
    nb = [[] for _ in o.data.vertices]
    for e in o.data.edges:
        a, b = e.vertices
        nb[a].append(b)
        nb[b].append(a)
    return nb


def _smooth_field(D, nb, mask, iters=3):
    for _ in range(iters):
        out = D.copy()
        for i in np.nonzero(mask)[0]:
            n = nb[i]
            if n:
                out[i] = 0.5 * D[i] + 0.5 * D[n].mean(0)
        D = out
    return D


def _side_test(pts, co, polys, bfaces, cover):
    """Signed distance of pts to the surface (co, polys) along its normal;
    nan where nothing within `cover` or on a boundary face."""
    bvh = BVHTree.FromPolygons([tuple(v) for v in co], polys, all_triangles=False)
    s = np.full(len(pts), np.nan)
    nrm = np.zeros((len(pts), 3))
    hitp = np.zeros((len(pts), 3))
    for i, p in enumerate(pts):
        loc, n, fi, d = bvh.find_nearest(Vector(p), cover)
        if loc is None or fi in bfaces:
            continue
        s[i] = (Vector(p) - loc).dot(n)
        nrm[i] = n
        hitp[i] = loc
    return s, nrm, hitp


class Baker:
    def __init__(self, b, cfg, rules):
        self.b = b
        self.cfg = cfg
        self.arm = b.armature()
        self.names = drig.bone_names(self.arm)
        self.parts = {}
        for o in b.meshes():
            p = part(o)
            if p and p not in self.parts:
                self.parts[p] = o
        self.rt = drt.Runtime(self.arm, list(self.parts.values()), rules)
        self.rig = dp.Rig(self.arm)
        self.bfaces = {k: _boundary_faces(o) for k, o in self.parts.items()}
        self.polys = {k: _polys(o) for k, o in self.parts.items()}
        self.nb = {k: _adjacency(o) for k, o in self.parts.items()}
        self.rest = {k: self._rest_co(o) for k, o in self.parts.items()}
        self.W = {k: drig.read(o, self.names)[0] for k, o in self.parts.items()}
        self.cover = self._rest_cover()
        # garments: the corrective is smoothed spatially across islands, so a
        # collar, lapel or sleeve island moves with the panel it touches
        self.nbh = {k: drig.Neighbours(self.rest[k], cfg["delta_sigma_m"])
                    for k in self.parts if k != "body" and k not in ATTACH}
        self.attach = self._attach_map()

    def _rest_co(self, o):
        co = np.empty(len(o.data.vertices) * 3)
        o.data.vertices.foreach_get("co", co)
        return co.reshape(-1, 3)

    def _rest_cover(self):
        c = self.cfg["collide"]
        cov = {}
        for outer, inners in COVERS.items():
            if outer not in self.parts:
                continue
            for inner in inners:
                if inner not in self.parts:
                    continue
                s, _, _ = _side_test(self.rest[outer], self.rest[inner], self.polys[inner],
                                     self.bfaces[inner], c["cover_m"])
                cov[(inner, outer)] = s > 0  # outer vertex outside inner at rest
        if "body" in self.parts:
            for outer in BODY_UNDER:
                if outer not in self.parts:
                    continue
                s, _, _ = _side_test(self.rest["body"], self.rest[outer], self.polys[outer],
                                     self.bfaces[outer], c["cover_m"])
                cov[("body", outer)] = s < 0  # body vertex inside the garment at rest
        return cov

    def _attach_map(self):
        out = {}
        for small, host in ATTACH.items():
            if small in self.parts and host in self.parts:
                kd = KDTree(len(self.rest[host]))
                for i, p in enumerate(self.rest[host]):
                    kd.insert(p, i)
                kd.balance()
                out[small] = (host, np.array([kd.find(p)[1] for p in self.rest[small]]))
        return out

    def region_group(self, o, centre, radius):
        vg = o.vertex_groups.get("deform_region") or o.vertex_groups.new(name="deform_region")
        co = self.rest[part(o)]
        r = np.linalg.norm(co - np.array(centre), axis=1)
        w = 1.0 - drig.smoothstep(radius * 0.55, radius, r)
        vg.remove(list(range(len(co))))
        for i in np.nonzero(w > 1e-3)[0]:
            vg.add([int(i)], float(w[i]), "REPLACE")
        return w

    def skin_mats(self):
        A = self.arm
        S = np.zeros((len(self.names), 4, 4))
        for j, n in enumerate(self.names):
            S[j] = np.array(A.pose.bones[n].matrix @ A.data.bones[n].matrix_local.inverted())
        return S

    def bake(self, spec, s):
        c = self.cfg
        bone = f"{spec['bone']}_{s}"
        dp.apply_pose(self.arm, {"bones": {bone: spec["ops"]}}, self.rig)
        self.rt.apply(morphs=False)
        centre = self.arm.data.bones[f"{spec['region'][0]}_{s}"].head_local
        radius = spec["region"][1]
        dg = bpy.context.evaluated_depsgraph_get()
        X, Y, reg = {}, {}, {}
        for k, o in self.parts.items():
            if k in ATTACH:
                continue
            reg[k] = self.region_group(o, centre, radius)
            m = o.modifiers.new("deform_cs", "CORRECTIVE_SMOOTH")
            m.rest_source = "ORCO"
            m.smooth_type = "LENGTH_WEIGHTED"
            m.iterations = c["cs_iters"]["body" if k == "body" else "garment"]
            m.factor = 0.5
            m.scale = 1.0
            m.use_pin_boundary = True
            m.vertex_group = "deform_region"
            m.show_viewport = False
            dg.update()
            X[k] = _eval_co(o, bpy.context.evaluated_depsgraph_get())
            m.show_viewport = True
            dg = bpy.context.evaluated_depsgraph_get()
            dg.update()
            Y[k] = _eval_co(o, dg)
            o.modifiers.remove(m)
            if k in self.nbh:
                Y[k] = X[k] + self.nbh[k].smooth(Y[k] - X[k])
        pushed = self.collide(Y, reg)
        for small, (host, idx) in self.attach.items():
            o = self.parts[small]
            dg = bpy.context.evaluated_depsgraph_get()
            X[small] = _eval_co(o, dg)
            Y[small] = X[small] + (Y[host] - X[host])[idx]
        S = self.skin_mats()
        name = f"{spec['name']}_{s}"
        stats = {"pushed": pushed}
        for k, o in self.parts.items():
            d = Y[k] - X[k]
            mag = np.linalg.norm(d, axis=1)
            if mag.max() < c["min_delta_m"]:
                continue
            W = self.W[k]
            M = np.einsum("vb,bij->vij", W, S[:, :3, :3])
            dr = np.linalg.solve(M, d[:, :, None])[:, :, 0]
            dr[mag < c["min_delta_m"]] = 0.0
            self.add_key(o, name, dr)
            stats[k] = {"verts": int((mag >= c["min_delta_m"]).sum()), "max_mm": round(float(mag.max() * 1000), 1)}
        # driver: target direction = the bone's direction in the ref frame at this pose
        ref = f"{spec['ref']}_{s}" if spec["ref"] not in ("pelvis", "spine_03") else spec["ref"]
        d0 = self.rig.dir(bone)
        q = self.rt.R(ref).inverted() @ self.rt.R(bone)
        t = (q @ d0).normalized()
        dp.reset(self.arm)
        self.rt.apply(morphs=False)
        rule = {"type": "cone", "name": name, "bone": bone, "ref": ref,
                "rest_dir": drt.bl_to_gl(d0), "target_dir": drt.bl_to_gl(t), "power": 1.0,
                "meshes": [self.parts[k].name for k in stats if k in self.parts],
                "angle_deg": round(math.degrees(d0.angle(t)), 1)}
        return rule, stats

    def add_key(self, o, name, dr):
        if o.data.shape_keys is None:
            o.shape_key_add(name="Basis", from_mix=False)
        kb = o.shape_key_add(name=name, from_mix=False)
        base = self.rest[part(o)]
        kb.data.foreach_set("co", (base + dr).astype(np.float32).ravel())
        kb.value = 0.0

    def collide(self, Y, reg):
        c = self.cfg["collide"]
        clear = c["clear_m"]
        n_out = {}
        # garments: outer pushed out over the inner layers it covers
        for outer in GARMENT_ORDER:
            if outer not in Y:
                continue
            D = np.zeros_like(Y[outer])
            for inner in COVERS.get(outer, []):
                key = (inner, outer)
                if inner not in Y or key not in self.cover:
                    continue
                q = Y[outer] + D
                s, nrm, _ = _side_test(q, Y[inner], self.polys[inner], self.bfaces[inner], c["cover_m"])
                bad = self.cover[key] & ~np.isnan(s) & (s < clear) & (reg[outer] > 0)
                D[bad] += nrm[bad] * (clear - s[bad])[:, None]
                n_out[f"{inner}>{outer}"] = int(bad.sum())
            if np.abs(D).max() > 0:
                D = _smooth_field(D, self.nb[outer], reg[outer] > 0, c["smooth_iters"])
                Y[outer] = Y[outer] + D
        # body pushed in under the garments that cover it at rest
        if "body" in Y:
            D = np.zeros_like(Y["body"])
            for outer in BODY_UNDER:
                key = ("body", outer)
                if outer not in Y or key not in self.cover:
                    continue
                q = Y["body"] + D
                s, nrm, _ = _side_test(q, Y[outer], self.polys[outer], self.bfaces[outer], c["cover_m"])
                bad = self.cover[key] & ~np.isnan(s) & (s > -clear) & (reg["body"] > 0)
                D[bad] -= nrm[bad] * (s[bad] + clear)[:, None]
                n_out[f"body>{outer}"] = int(bad.sum())
            if np.abs(D).max() > 0:
                D = _smooth_field(D, self.nb["body"], reg["body"] > 0, c["smooth_iters"])
                Y["body"] = Y["body"] + D
        return n_out


DEFAULTS = {
    "specs": [s["name"] for s in SPECS],
    "cs_iters": {"body": 12, "garment": 8},
    "min_delta_m": 0.0002,
    "delta_sigma_m": 0.015,
    "collide": {"cover_m": 0.04, "clear_m": 0.002, "smooth_iters": 2},
}


def run(b, cfg, rules):
    bk = Baker(b, cfg, rules)
    out = {}
    for spec in SPECS:
        if spec["name"] not in cfg["specs"]:
            continue
        for s in ("l", "r"):
            if f"{spec['bone']}_{s}" not in bk.arm.data.bones:
                continue
            rule, stats = bk.bake(spec, s)
            rules["morphs"].append(rule)
            out[rule["name"]] = stats
    for o in bk.parts.values():
        vg = o.vertex_groups.get("deform_region")
        if vg:
            o.vertex_groups.remove(vg)
    dp.reset(bk.arm)
    return out
