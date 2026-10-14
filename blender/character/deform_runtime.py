"""Runtime deformation rules: the reference implementation of what the game
runs every frame after the animation pose and before skinning, and the
Blender emulation the build and bench/m1/deform_test.py use.

The rules ship as `character.rig.json` next to the GLB (written by
deform_rig.py). All vectors are in **glTF model space** (Y up, +Z = the
character's front, +X = its left), in the bind pose. The math only needs each
joint's bind (rest) world matrix (= inverse of its inverse-bind matrix) and its
current world matrix, so it does not depend on bone roll or node frames.

Notation, per joint J: R_J = rot(W_J) * rot(W_J_bind)^-1 (model-space
rotation of J away from its bind pose). For a joint S with parent P:
D_S = R_P^-1 * R_S (S's own rotation, in bind model space).
swing_twist(q, a): q = swing * twist, twist about unit axis a.

Helper joints (set their world rotation, then local = parent^-1 * world;
translation stays the bind offset):

    twist   {bone T, source S, axis a, factor f, frame F}
            theta = twist angle of D_S about a;  R_T = R_F * rot(a, f*theta)
            (F = T's parent. f < 0 on the bone itself cancels its twist near
            the joint: upperarm_twist_01 / thigh_twist_01, f = -1.)
    swing   {bone H, source S, factor f, axis a, frame F}
            swing = swing part of D_S about a;  R_H = R_F * slerp(I, swing, f)
            (deltoid_helper: f = 0.5, F = clavicle)
    follow  {bone K, source S, frame F, rest_dir d0, flex_axis L, abd_axis N,
             gain {flex+, flex-, abd+, abd-}}
            v = rotation vector of the swing of D_S taking d0 to D_S*d0;
            flex = v.L, abd = v.N; R_K = R_F * rotvec(g(flex)*flex*L + g(abd)*abd*N)
            (skirt_<sector>_<side>: the jacket skirt panels follow the thigh)

Corrective morphs (morph target name = rule name; same weight on every mesh
that carries a target of that name):

    cone    {name, bone B, ref R, rest_dir d0, target_dir t, power p, start s (default 0)}
            d = (R_R^-1 * R_B) * d0;  u = 1 - angle(d, t) / angle(d0, t)
            w = clamp((u - s) / (1 - s), 0, 1) ^ p
            (s > 0: no weight over the first part of the way, e.g. corr_fist
            stays 0 in a relaxed or holding hand)
            inverse: true -> d = (R_R^-1 * R_B)^-1 * d0 (the ref's direction seen
            from the bone): a twist of B about its own axis before the swing
            then leaves d unchanged (corr_wrist_*: a pronated hand that flexes
            still reads as flexion)

three.js: compute these after mixer.update() and before render, in the order
listed (helpers, then morph weights); set the helper bones' .quaternion and
mesh.morphTargetInfluences[mesh.morphTargetDictionary[name]].
"""

import math

from mathutils import Matrix, Quaternion, Vector


def gl_to_bl(v):
    return Vector((v[0], -v[2], v[1]))


def bl_to_gl(v):
    return [round(v[0], 6), round(v[2], 6), round(-v[1], 6)]


def swing_twist(q, a):
    """q = swing @ twist, twist about unit axis a. Returns (swing, twist, angle)."""
    p = Vector((q.x, q.y, q.z)).dot(a)
    tw = Quaternion((q.w, a.x * p, a.y * p, a.z * p))
    if tw.magnitude < 1e-9:
        tw = Quaternion()
    else:
        tw.normalize()
    ang = 2.0 * math.atan2(p, q.w)
    if ang > math.pi:
        ang -= 2 * math.pi
    elif ang < -math.pi:
        ang += 2 * math.pi
    sw = q @ tw.inverted()
    return sw, tw, ang


def rotvec(v):
    a = v.length
    if a < 1e-9:
        return Quaternion()
    return Quaternion(v / a, a)


def cone_weight(d, d0, t, p=1.0, start=0.0):
    span = d0.angle(t)
    if span < 1e-6:
        return 0.0
    w = 1.0 - d.angle(t) / span
    if start > 0.0:
        w = (w - start) / (1.0 - start)
    w = max(0.0, min(1.0, w))
    return w ** p


class Runtime:
    """Blender emulation of the rules on an armature (staged or GLB import)."""

    def __init__(self, arm, meshes, rules):
        self.arm = arm
        self.meshes = meshes
        self.rules = rules or {}
        self.rest = {b.name: b.matrix_local.to_quaternion() for b in arm.data.bones}

    def R(self, n):
        if n is None or n not in self.rest:
            return Quaternion()
        return self.arm.pose.bones[n].matrix.to_quaternion() @ self.rest[n].inverted()

    def D(self, s, frame=None):
        p = frame if frame is not None else (self.arm.data.bones[s].parent.name
                                             if self.arm.data.bones[s].parent else None)
        return self.R(p).inverted() @ self.R(s)

    def _set_world_rot(self, n, Rw):
        pb = self.arm.pose.bones[n]
        b = self.arm.data.bones[n]
        rot = (Rw @ self.rest[n]).to_matrix().to_4x4()
        # translation: the bind offset carried by the parent
        if b.parent:
            P = self.arm.pose.bones[b.parent.name].matrix
            off = b.parent.matrix_local.inverted() @ b.matrix_local
            head = (P @ off).translation
        else:
            head = b.matrix_local.translation
        pb.matrix = Matrix.Translation(head) @ rot

    def helper_rotation(self, h):
        """World-delta rotation R_H for one helper rule."""
        t = h["type"]
        F = h.get("frame")
        if t == "twist":
            a = gl_to_bl(h["axis"]).normalized()
            _, _, ang = swing_twist(self.D(h["source"], h.get("source_frame")), a)
            return self.R(F) @ Quaternion(a, h["factor"] * ang)
        if t == "swing":
            a = gl_to_bl(h["axis"]).normalized()
            sw, _, _ = swing_twist(self.D(h["source"], h.get("source_frame")), a)
            return self.R(F) @ Quaternion().slerp(sw, h["factor"])
        if t == "follow":
            q = self.D(h["source"], h.get("source_frame"))
            d0 = gl_to_bl(h["rest_dir"]).normalized()
            d = q @ d0
            sw = d0.rotation_difference(d)
            ax, ang = sw.to_axis_angle()
            v = ax * ang
            L = gl_to_bl(h["flex_axis"]).normalized()
            N = gl_to_bl(h["abd_axis"]).normalized()
            g = h["gain"]
            fl, ab = v.dot(L), v.dot(N)
            gf = g["flex+"] if fl >= 0 else g["flex-"]
            ga = g["abd+"] if ab >= 0 else g["abd-"]
            return self.R(F) @ rotvec(L * (gf * fl) + N * (ga * ab))
        raise ValueError(t)

    def morph_weights(self):
        out = {}
        for m in self.rules.get("morphs", []):
            d0 = gl_to_bl(m["rest_dir"]).normalized()
            t = gl_to_bl(m["target_dir"]).normalized()
            q = self.R(m["ref"]).inverted() @ self.R(m["bone"])
            if m.get("inverse"):
                q = q.inverted()
            out[m["name"]] = cone_weight(q @ d0, d0, t, m.get("power", 1.0), m.get("start", 0.0))
        return out

    def apply(self, rig=None, morphs=True):
        import bpy
        for h in self.rules.get("helpers", []):
            if h["bone"] not in self.rest:
                continue
            self._set_world_rot(h["bone"], self.helper_rotation(h))
            bpy.context.view_layer.update()
        w = self.morph_weights() if morphs else {}
        for o in self.meshes:
            ks = o.data.shape_keys
            if not ks:
                continue
            for kb in ks.key_blocks[1:]:
                kb.slider_min = 0.0
                kb.value = w.get(kb.name, 0.0)
        bpy.context.view_layer.update()
        return w
