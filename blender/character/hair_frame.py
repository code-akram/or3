"""Head landmarks and collision surfaces for the generated hair and beard.

Everything is measured on the staged (post-bake) meshes, from MPFB's
topology-bound vertex groups (scalp, lips, ears, head) and the rig, never
from fixed coordinates, so the hair follows the head track's face edits and
any change to the body macros. Rest pose, world space, character facing -Y.
"""

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree


def group_verts(obj, name, min_w=0.5):
    """World positions of obj's vertices with weight >= min_w in group name."""
    g = obj.vertex_groups.get(name)
    if g is None:
        return []
    mw = obj.matrix_world
    return [mw @ v.co for v in obj.data.vertices
            if any(e.group == g.index and e.weight >= min_w for e in v.groups)]


def bbox(pts):
    return (Vector([min(p[i] for p in pts) for i in range(3)]),
            Vector([max(p[i] for p in pts) for i in range(3)]))


def world_bvh(objs, skip=None):
    """One BVH over the evaluated (rest pose) world-space faces of objs.
    skip: {object name: vertex indices}; faces touching those are left out."""
    dg = bpy.context.evaluated_depsgraph_get()
    verts, polys = [], []
    for o in objs:
        ev = o.evaluated_get(dg)
        me = ev.to_mesh()
        base = len(verts)
        mw = o.matrix_world
        drop = (skip or {}).get(o.name, ())
        verts += [mw @ v.co for v in me.vertices]
        polys += [[base + i for i in p.vertices] for p in me.polygons
                  if not any(i in drop for i in p.vertices)]
        ev.to_mesh_clear()
    return BVHTree.FromPolygons(verts, polys, all_triangles=False)


class HeadFrame:
    """Landmarks the hair and beard generators place themselves against."""

    def __init__(self, b, colliders):
        self.body = next(o for o in b.meshes() if o.vertex_groups.get("scalp"))
        arm = b.armature()
        mw = arm.matrix_world
        self.bone = {n: mw @ arm.data.bones[n].head_local
                     for n in ("head", "neck_01", "upperarm_l", "upperarm_r")}
        self.bone["head_tail"] = mw @ arm.data.bones["head"].tail_local

        scalp = group_verts(self.body, "scalp")
        self.scalp_min, self.scalp_max = bbox(scalp)
        head = group_verts(self.body, "head")
        self.head_min, self.head_max = bbox(head)
        self.ears_min, self.ears_max = bbox(group_verts(self.body, "ears"))
        self.lips_min, self.lips_max = bbox(group_verts(self.body, "lips", 0.3))

        self.crown_z = self.head_max.z
        self.ear_z = (self.ears_min.z + self.ears_max.z) / 2
        # Cranium centre: midway front-back over the scalp, midway crown-ears.
        self.center = Vector(((self.scalp_min.x + self.scalp_max.x) / 2,
                              (self.scalp_min.y + self.scalp_max.y) / 2,
                              (self.crown_z + self.ear_z) / 2))
        # Chin: lowest head-weighted point in front of the mouth corners' depth.
        front = [p for p in head if p.y < self.lips_max.y + 0.03 and abs(p.x) < 0.03]
        self.chin_z = min(p.z for p in front)
        self.chin_y = min(p.y for p in front if p.z < self.lips_min.z)
        self.neck_z = self.bone["neck_01"].z
        self.shoulder_z = (self.bone["upperarm_l"].z + self.bone["upperarm_r"].z) / 2

        self.colliders = colliders
        # Hair passes over the ears (thin flaps whose two-sided normals would
        # kick strands outward), so they are not colliders; the cap and the
        # beard edge relax onto the full skin (skin_bvh).
        ears = self.body.vertex_groups["ears"].index
        ear_verts = set(v.index for v in self.body.data.vertices
                        if any(e.group == ears and e.weight > 0.05 for e in v.groups))
        self.bvh = world_bvh(colliders, {self.body.name: ear_verts})
        self.skin_bvh = world_bvh([self.body])

    def signed(self, p):
        """(nearest surface point, outward normal, signed distance) to the colliders."""
        loc, nrm, _, _ = self.bvh.find_nearest(p)
        if loc is None:
            return None, None, 1e9
        return loc, nrm, (p - loc).dot(nrm)

    def summary(self):
        r = lambda v: [round(x, 4) for x in v]
        return {"center": r(self.center), "crown_z": round(self.crown_z, 4),
                "ear_z": round(self.ear_z, 4), "chin_z": round(self.chin_z, 4),
                "neck_z": round(self.neck_z, 4), "shoulder_z": round(self.shoulder_z, 4),
                "lips_min": r(self.lips_min), "lips_max": r(self.lips_max),
                "ears_min": r(self.ears_min), "ears_max": r(self.ears_max)}
