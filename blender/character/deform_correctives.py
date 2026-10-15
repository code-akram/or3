"""Corrective morph targets baked from delta mush plus layer collision
(m1 v2 Track F; bench/m1/v2/deform.md).

For each corrective (one joint, one target pose, both sides):

1. pose the staged rig into the target pose (one joint moved, the helper
   rules applied: deform_runtime.Runtime);
2. per mesh, evaluate plain linear blend skinning (X) and the same with a
   Corrective Smooth (delta mush) modifier restricted to a soft region around
   the joint (Y). Delta mush keeps the rest-pose surface detail relative to a
   smoothed surface, so it removes the LBS collapse, pinch and candy wrapper
   without hand sculpting. On the body the region is also limited to skin
   the pose actually moves (weight on a bone whose skinning matrix changed,
   dilated a few rings), so the smoothing cannot drag still skin such as the
   throat in an arm raise;
3. resolve the layers in that pose: an outer garment that an inner layer now
   pokes through is pushed out to a small clearance (shirt < tie < trousers <
   waistcoat < jacket); body skin that a garment covers in the rest pose and
   now pokes out is pushed in (it is hidden anyway). Skin counts as covered
   with the rule bench/m1/deform_test.py uses: the garment's nearest surface
   is outside it AND a ray along the skin normal meets the garment within
   collide.cover_ray_m, so a garment that is merely near (the jacket collar
   7 cm from the throat) does not cover it. Small attached meshes (buttons)
   follow the nearest point of their garment. Specs with self_collide
   (the fist) also resolve skin against skin: each digit against the palm
   and its neighbours, both sides giving way by half (pads compress);
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
    # tight fist: the whole hand pose (deform_poses.<pose>, left names), skin
    # only; driven by the middle finger's middle phalanx in the hand frame
    # (MCP + PIP curl), full weight at the authored FIST (drive_pose), so
    # hand_pose.settle, which curls to contact under the authored pose's
    # weight, never ends with more compression than it tested. The pads,
    # the palm and the palmar crease give way, so the fingers close further.
    {"name": "corr_fist", "bone": "middle_02", "pose": "FIST_TIGHT", "ref": "hand",
     "region": ("middle_01", 0.085), "meshes": ["body"], "self_collide": True, "power": 1.0,
     "start": 0.45, "drive_pose": "FIST", "knuckles": True},
    # T22: the wrist in flexion and extension (skin only: the cuffs are T13's), delta mush
    # keeps the tendons, the ulnar head and the flat wrist (head_sculpt.hand_field) instead of
    # LBS's collapsed tube.
    # inverse: the hand bone carries pronation (twist) too; the forearm's direction seen from
    # the hand ignores it, so a pronated wrist that flexes still drives these
    {"name": "corr_wrist_flex", "bone": "hand", "ops": [["flex", 60]], "ref": "lowerarm",
     "region": ("hand", 0.075), "meshes": ["body"], "inverse": True},
    {"name": "corr_wrist_ext", "bone": "hand", "ops": [["flex", -55]], "ref": "lowerarm",
     "region": ("hand", 0.075), "meshes": ["body"], "inverse": True},
    # No clavicle (shrug) corrective: t22-a1..a3 baked one (clavicle abduct 16, all meshes); the
    # neck forms held under LBS anyway (the exposed neck is above the clavicle's reach) and it
    # moved the jacket (415 verts, 5 mm) and the shirt collar into a jagged edge in arm_raise.
]
# corr_fist's knuckle term (T22): in a fist LBS rounds the outer corner of each flexed joint
# off; the skin is pushed back out to the bone head (the rest skin height over the joint) plus
# extra_mm, in the bisector of the two bones, and the dips between the metacarpal heads deepen.
# Baked at FIST_TIGHT and shown at FIST, about half of the push survives (t22-a1: max 2.0 mm
# restored MCP 4.6 -> 5.6 mm of a 6.3-7.2 mm rest height), hence the extra and the caps.
FIST_KNUCKLES = {"mcp": {"extra_mm": 1.0, "sigma_mm": 4.5, "max_mm": 3.5},
                 "pip": {"extra_mm": 0.6, "sigma_mm": 3.5, "max_mm": 3.0},
                 "valley_mm": -0.5}
# skin parts of a hand for self_collide: part -> bone prefixes (side added)
HAND_PARTS = {"palm": ("hand", "thumb_01"), "thumb": ("thumb_02", "thumb_03"),
              "index": ("index_01", "index_02", "index_03"), "middle": ("middle_01", "middle_02", "middle_03"),
              "ring": ("ring_01", "ring_02", "ring_03"), "pinky": ("pinky_01", "pinky_02", "pinky_03")}
HAND_PAIRS = [("index", "palm"), ("middle", "palm"), ("ring", "palm"), ("pinky", "palm"),
              ("thumb", "index"), ("thumb", "middle"), ("thumb", "palm"),
              ("index", "middle"), ("middle", "ring"), ("ring", "pinky")]
# inner part -> outer parts, processed in this order (outer garments pushed out)
GARMENT_ORDER = ["shirt", "tie", "trousers", "waistcoat", "jacket"]
COVERS = {"tie": ["shirt"], "trousers": ["shirt"], "waistcoat": ["shirt", "tie", "trousers"],
          "jacket": ["shirt", "tie", "waistcoat", "trousers"]}
BODY_UNDER = ["shirt", "waistcoat", "jacket", "trousers"]
ATTACH = {"buttons": "jacket"}


def part(o):
    if o.name == "Human_export":
        return "body"
    if o.get("made_suit"):
        return None  # the made suit carries its own pose-space correctives (suit_made)
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


def _patch_edge(sel):
    """Indices (in sel) of the faces on the open edge of a face patch."""
    cnt = {}
    for q in sel:
        for e in zip(q, q[1:] + q[:1]):
            e = tuple(sorted(e))
            cnt[e] = cnt.get(e, 0) + 1
    bv = {v for e, c in cnt.items() if c == 1 for v in e}
    return {j for j, q in enumerate(sel) if any(v in bv for v in q)}


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


def _ray_hits(pts, dirs, co, polys, dist):
    """Per point: does a ray along dirs meet the surface (co, polys) within dist."""
    bvh = BVHTree.FromPolygons([tuple(v) for v in co], polys, all_triangles=False)
    out = np.zeros(len(pts), dtype=bool)
    for i, (p, d) in enumerate(zip(pts, dirs)):
        dv = Vector(d)
        if dv.length < 1e-9:
            continue
        dv.normalize()
        out[i] = bvh.ray_cast(Vector(p) + dv * 0.0005, dv, dist)[0] is not None
    return out


class HandSkin:
    """The skin parts of one hand (HAND_PARTS, by dominant bone) and a
    skin-against-skin contact test between them (HAND_PAIRS).

    A vertex of part x is inside part y when its nearest point on y's posed
    surface (within reach_m) is a perpendicular foot on an inner face of y's
    patch (not at the patch edge, |p - foot| ~ |signed distance|) and it lies
    behind that face (signed distance < clear_m). Skin within root_m of a
    pair's digit roots is not judged (a digit always touches its own root),
    except that a digit is judged whole against the palm away from its root
    (hand_pose.settle's own_palm test).
    bench/m1 uses it too (the fist check)."""

    def __init__(self, arm, names, W, rest, polys, s, c):
        self.c = c
        dom = np.array(names)[W.argmax(1)]
        self.sets = {pn: np.isin(dom, [f"{b}_{s}" for b in pre]) for pn, pre in HAND_PARTS.items()}
        self.live = np.logical_or.reduce(list(self.sets.values()))
        self.polys = polys
        B = arm.data.bones
        roots = {pn: np.array(B[f"{pre[0]}_{s}"].head_local) for pn, pre in HAND_PARTS.items() if pn != "palm"}
        self.pairs = []
        for a, b in HAND_PAIRS:
            r = [roots[q] for q in (a, b) if q in roots]
            dr = np.min([np.linalg.norm(rest - q, axis=1) for q in r], axis=0)
            ok = dr > c["root_m"]
            for x, y in ((a, b), (b, a)):
                # against the palm the digit is judged whole (its crease too)
                # and the palm away from the root, as hand_pose.settle does;
                # the palm patch reaches root_pad_m closer, so a contact at
                # settle's cut is not lost on the patch edge
                okx = np.ones(len(rest), dtype=bool) if y == "palm" else ok
                oky = (dr > c["root_m"] - c["root_pad_m"]) if y == "palm" else ok
                sel = [q for q in polys if all(self.sets[y][i] and oky[i] for i in q)]
                selx = [q for q in polys if all(self.sets[x][i] and okx[i] for i in q)]
                if sel and selx:
                    self.pairs.append((x, y, np.nonzero(self.sets[x] & okx)[0], sel, _patch_edge(sel), selx))

    def contacts(self, Y):
        """[(vertex, push vector, pair)] for every vertex inside another part.

        Two tests: the vertex's nearest point on the other part is a
        perpendicular foot behind which it lies (deep overlaps), and the
        vertices of x's faces that cut through a face of y (triangle
        overlap, hand_pose.settle's own test: shallow folds such as the
        palmar crease) that lie behind that face's plane."""
        c = self.c
        out = []
        verts = [tuple(v) for v in Y]
        for x, y, idx, sel, edge, selx in self.pairs:
            bvh = BVHTree.FromPolygons(verts, sel, all_triangles=False)
            push = {}
            for i in idx:
                p = Vector(Y[i])
                loc, nrm, fi, dist = bvh.find_nearest(p, c["reach_m"])
                if loc is None or fi in edge:
                    continue
                sd = (p - loc).dot(nrm)
                if sd >= c["clear_m"] or dist > abs(sd) * 1.15 + 0.0005:
                    continue
                push[i] = np.array(nrm) * (c["clear_m"] - sd)
            bx = BVHTree.FromPolygons(verts, selx, all_triangles=False)
            okv = set(idx.tolist())
            for fx, fy in bx.overlap(bvh):
                q = sel[fy]
                P = Y[list(q)]
                n = np.cross(P[1] - P[0], P[2] - P[0])
                ln = np.linalg.norm(n)
                if ln < 1e-12:
                    continue
                n /= ln
                cen = P.mean(0)
                for v in selx[fx]:
                    if v not in okv:
                        continue
                    sd = float((Y[v] - cen) @ n)
                    if sd < c["clear_m"] and -sd < c["fold_m"]:
                        d = n * (c["clear_m"] - sd)
                        if v not in push or np.linalg.norm(d) > np.linalg.norm(push[v]):
                            push[v] = d
            out += [(i, v, f"{x}>{y}") for i, v in push.items()]
        return out

    def report(self, Y):
        """{pair: (vertices, max depth mm)}"""
        out = {}
        for i, v, pr in self.contacts(Y):
            n, d = out.get(pr, (0, 0.0))
            out[pr] = (n + 1, max(d, round(float(np.linalg.norm(v)) * 1000 - self.c["clear_m"] * 1000, 1)))
        return out


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
        self.rnrm = {k: self._rest_nrm(o) for k, o in self.parts.items()}
        self.W = {k: drig.read(o, self.names)[0] for k, o in self.parts.items()}
        self.cover = self._rest_cover()
        # garments: the corrective is smoothed spatially across islands, so a
        # collar, lapel or sleeve island moves with the panel it touches
        self.nbh = {k: drig.Neighbours(self.rest[k], cfg["delta_sigma_m"])
                    for k in self.parts if k != "body" and k not in ATTACH}
        self.attach = self._attach_map()

    def _rest_nrm(self, o):
        n = np.empty(len(o.data.vertices) * 3)
        o.data.vertex_normals.foreach_get("vector", n)
        return n.reshape(-1, 3)

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
                # outer vertex outside the inner layer (garment over garment:
                # the layers are built in order, and a loose skirt or flap
                # stands well off what it covers, so no ray rule here)
                cov[(inner, outer)] = s > 0
        if "body" in self.parts:
            for outer in BODY_UNDER:
                if outer not in self.parts:
                    continue
                s, _, _ = _side_test(self.rest["body"], self.rest[outer], self.polys[outer],
                                     self.bfaces[outer], c["body_cover_m"])
                # body vertex inside the garment, and the garment really over
                # it (a ray along the skin normal meets it): deform_test's rule
                ray = _ray_hits(self.rest["body"], self.rnrm["body"], self.rest[outer], self.polys[outer],
                                c["cover_ray_m"])
                cov[("body", outer)] = (s < 0) & ray
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

    def _moved_mask(self, k, moved, spec, s):
        """1 on skin weighted to a bone the pose moves, falling to 0 a few
        rings out (topological dilation); the fist also keeps the fingertip
        backs (the nails sit there) out of the smoothing."""
        W = self.W[k]
        if spec.get("self_collide"):
            # the whole hand (the dorsum puffs under the curl) except the
            # fingertips (the nails sit on them) and the thumb, which the
            # bake pose leaves open and the poses curl against the index
            still = [j for j, n in enumerate(self.names)
                     if n.endswith(f"_03_{s}") or (n.startswith("thumb_0") and n.endswith(f"_{s}"))]
            return 1.0 - drig.smoothstep(0.3, 0.7, W[:, still].sum(1))
        if spec.get("cs_mask") == "dorsal":
            # the back of the hand and the proximal phalanges: rest normal
            # away from the palm (the palm side is corr_fist's)
            B = self.arm.data.bones
            hd = Vector(B[f"hand_{s}"].head_local)
            f = (Vector(B[f"middle_01_{s}"].head_local) - hd).normalized()
            t = Vector(B[f"index_01_{s}"].head_local) - Vector(B[f"pinky_01_{s}"].head_local)
            t = (t - f * t.dot(f)).normalized()
            pn = f.cross(t)
            if pn.dot(Vector(B[f"thumb_02_{s}"].head_local) - hd) < 0:
                pn = -pn
            cols = [j for j, n in enumerate(self.names)
                    if n == f"hand_{s}" or (n.endswith(f"_01_{s}") and not n.startswith("thumb"))
                    or (n.endswith(f"_02_{s}") and not n.startswith("thumb"))]
            dors = drig.smoothstep(0.1, 0.5, -(self.rnrm[k] @ np.array(pn[:])))
            return dors * drig.smoothstep(0.3, 0.7, W[:, cols].sum(1))
        m = W[:, moved].sum(1) if moved.any() else np.zeros(len(W))
        nb = self.nb[k]
        for _ in range(self.cfg["moved_rings"]):
            out = m.copy()
            for i in np.nonzero(m < 1.0)[0]:
                n = nb[i]
                if n:
                    out[i] = max(m[i], 0.85 * float(m[n].max()))
            m = out
        return drig.smoothstep(0.0, 0.25, m)

    def self_collide(self, Y, reg, s):
        """Skin against skin in the hand (hand_contacts): every vertex inside
        another part moves out along that part's surface normal by half its
        depth per pass (both sides give way: the pads compress), the field
        lightly smoothed, until nothing is inside or the passes run out.
        Returns {pair: vertices inside} before and after."""
        c = self.cfg["self_collide"]
        k = "body"
        H = HandSkin(self.arm, self.names, self.W[k], self.rest[k], self.polys[k], s, c)
        nb = self.nb[k]
        first = None
        Y0 = Y[k].copy()
        cap = c["max_push_m"]
        for it in range(c["iters"]):
            hits = H.contacts(Y[k])
            if first is None:
                first = H.report(Y[k])
            if not hits:
                break
            D = np.zeros_like(Y[k])
            for i, push, _ in hits:
                D[i] += push * 0.5
            D = _smooth_field(D, nb, H.live, 1)
            Y[k] = Y[k] + D
            # no skin gives way by more than max_push_m in all (a deeper
            # overlap is a pose problem, not a corrective one)
            T = Y[k] - Y0
            m = np.linalg.norm(T, axis=1)
            over = m > cap
            Y[k][over] = Y0[over] + T[over] * (cap / m[over])[:, None]
        return {"before": first or {}, "after": H.report(Y[k]), "passes": it + 1}

    def knuckles(self, Y, s):
        """FIST_KNUCKLES on the posed body (Y['body'], object space): per flexed MCP and PIP, the
        outer corner direction c = unit(d_in - d_out) (the two bones' posed directions); the rest
        skin height r over the joint (along the rest back-of-hand direction); the posed skin is
        pushed along c by max(0, r - h_peak) + extra (h_peak: the highest posed skin along c near
        the corner ray), with a Gaussian falloff round the corner point."""
        from . import head_refine as hr
        kc = FIST_KNUCKLES
        A = self.arm
        mwa = np.array(A.matrix_world)
        to_obj = np.array(self.parts["body"].matrix_world.inverted()) @ mwa
        P = lambda n: (to_obj @ np.append(np.array(A.pose.bones[n].head[:]), 1.0))[:3]  # noqa: E731
        R = lambda n: (to_obj @ np.append(np.array(A.data.bones[n].head_local[:]), 1.0))[:3]  # noqa: E731
        rest, Yb = self.rest["body"], Y["body"]
        hand = self.W["body"][:, [j for j, n in enumerate(self.names)
                                  if n == f"hand_{s}" or (n.endswith(f"_{s}") and n.split("_")[0] in hr.FINGERS)]].sum(1) > 0.3
        f = hr.hand_frames(A)[s]
        Brest = f["back"]
        D = np.zeros_like(Yb)
        stats = {}
        corners = {}
        for k in hr.FINGERS:
            chain = [f"hand_{s}", f"{k}_01_{s}", f"{k}_02_{s}", f"{k}_03_{s}"]
            for ji, (kind, a_, j_, b_) in enumerate((("mcp", chain[0], chain[1], chain[2]),
                                                      ("pip", chain[1], chain[2], chain[3]))):
                c = kc[kind]
                d_in = P(j_) - P(a_) if ji else P(chain[1]) - P(chain[0])
                d_out = P(b_) - P(j_)
                d_in /= np.linalg.norm(d_in)
                d_out /= np.linalg.norm(d_out)
                cd = d_in - d_out
                if np.linalg.norm(cd) < 0.3:        # under ~17 deg of flexion: nothing to restore
                    continue
                cd /= np.linalg.norm(cd)
                # rest skin height over the joint along the rest back direction
                jr = R(j_)
                rel = rest - jr
                lat = np.linalg.norm(rel - np.outer(rel @ Brest, Brest), axis=1)
                ring = hand & (lat < 0.004) & (rel @ Brest > 0)
                if not ring.any():
                    continue
                r = float((rel[ring] @ Brest).max())
                jp = P(j_)
                relp = Yb - jp
                latp = np.linalg.norm(relp - np.outer(relp @ cd, cd), axis=1)
                ringp = hand & (latp < 0.004) & (relp @ cd > 0)
                if not ringp.any():
                    continue
                h = float((relp[ringp] @ cd).max())
                amp = min(max(0.0, r - h) + c["extra_mm"] * 0.001, c["max_mm"] * 0.001)
                K = jp + cd * r
                w = np.exp(-0.5 * ((Yb - K) ** 2).sum(1) / (c["sigma_mm"] * 0.001) ** 2) * hand * (relp @ cd > 0)
                D += (amp * w)[:, None] * cd[None, :]
                corners[(kind, k)] = K
                stats[f"{kind}_{k}"] = round(amp * 1000, 2)
        mcp = [corners.get(("mcp", k)) for k in hr.FINGERS]
        for a_, b_ in zip(mcp[:-1], mcp[1:]):
            if a_ is None or b_ is None:
                continue
            K = 0.5 * (a_ + b_)
            cd = K - P(f"hand_{s}")
            cd /= np.linalg.norm(cd)
            w = np.exp(-0.5 * ((Yb - K) ** 2).sum(1) / 0.0035 ** 2) * hand
            D += (kc["valley_mm"] * 0.001 * w)[:, None] * cd[None, :]
        Y["body"] = Yb + D
        return stats

    def region_group(self, o, centre, radius, mask=None):
        vg = o.vertex_groups.get("deform_region") or o.vertex_groups.new(name="deform_region")
        co = self.rest[part(o)]
        r = np.linalg.norm(co - np.array(centre), axis=1)
        w = 1.0 - drig.smoothstep(radius * 0.55, radius, r)
        if mask is not None:
            w = w * mask
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
        if spec.get("pose"):
            bones = dp.side(getattr(dp, spec["pose"]), s)
        else:
            bones = {bone: spec["ops"]}
        dp.apply_pose(self.arm, {"bones": bones}, self.rig)
        self.rt.apply(morphs=False)
        S0 = self.skin_mats()
        moved = np.abs(S0 - np.eye(4)[None]).reshape(len(S0), -1).max(1) > 1e-5
        parts = {k: o for k, o in self.parts.items()
                 if not spec.get("meshes") or k in spec["meshes"]}
        centre = self.arm.data.bones[f"{spec['region'][0]}_{s}"].head_local
        radius = spec["region"][1]
        dg = bpy.context.evaluated_depsgraph_get()
        X, Y, reg = {}, {}, {}
        for k, o in parts.items():
            if k in ATTACH:
                continue
            mask = None
            if k == "body":
                mask = self._moved_mask(k, moved, spec, s)
            reg[k] = self.region_group(o, centre, radius, mask)
            if not spec.get("cs", True):   # contact only: no delta mush
                X[k] = _eval_co(o, bpy.context.evaluated_depsgraph_get())
                Y[k] = X[k].copy()
                continue
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
        pushed = self.collide(Y, reg) if not spec.get("self_collide") else {}
        if spec.get("self_collide") and "body" in Y:
            pushed["skin"] = self.self_collide(Y, reg, s)
        if spec.get("knuckles") and "body" in Y:
            pushed["knuckles"] = self.knuckles(Y, s)
        for small, (host, idx) in self.attach.items():
            if small not in parts or host not in Y:
                continue
            o = self.parts[small]
            dg = bpy.context.evaluated_depsgraph_get()
            X[small] = _eval_co(o, dg)
            Y[small] = X[small] + (Y[host] - X[host])[idx]
        S = self.skin_mats()
        name = f"{spec['name']}_{s}"
        stats = {"pushed": pushed}
        for k, o in parts.items():
            if k not in Y:
                continue
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
        if spec.get("drive_pose"):   # full weight at another pose (past the bake pose)
            dp.apply_pose(self.arm, {"bones": dp.side(getattr(dp, spec["drive_pose"]), s)}, self.rig)
            self.rt.apply(morphs=False)
        q = self.rt.R(ref).inverted() @ self.rt.R(bone)
        if spec.get("inverse"):
            q = q.inverted()
        t = (q @ d0).normalized()
        dp.reset(self.arm)
        self.rt.apply(morphs=False)
        rule = {"type": "cone", "name": name, "bone": bone, "ref": ref,
                "rest_dir": drt.bl_to_gl(d0), "target_dir": drt.bl_to_gl(t), "power": spec.get("power", 1.0),
                "start": spec.get("start", 0.0), **({"inverse": True} if spec.get("inverse") else {}),
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
    "collide": {"cover_m": 0.07, "body_cover_m": 0.05, "cover_ray_m": 0.04, "clear_m": 0.006, "smooth_iters": 2},
    "moved_rings": 4,
    "self_collide": {"iters": 12, "clear_m": 0.0008, "reach_m": 0.02, "root_m": 0.024, "root_pad_m": 0.008, "max_push_m": 0.008,
                     "fold_m": 0.02},
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
            if spec.get("meshes") and not any(m in bk.parts for m in spec["meshes"]):
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
