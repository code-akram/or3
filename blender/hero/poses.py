"""Hero poses for the MPFB game_engine rig (UE-mannequin bone names).

Every operation works in armature (character) space, so the poses do not
depend on the bones' rolls: the character faces -Y, +X is its LEFT side, +Z is
up, metres, feet on z = 0. Poses are written for the left side and mirrored
with `s` (+1 left, -1 right).

Tools (class Poser):
  rot(bone, axis, deg)         rotate a bone (and its children) about an
                               armature-space axis through its posed head
  aim(bone, direction)         swing a bone to point along a direction
  ik2(upper, lower, target, pole, hinge)
                               analytic two-bone IK: the end of `lower`
                               reaches `target`, the joint bends toward `pole`,
                               and the upper bone is twisted so the joint stays
                               a pure hinge (no twist inside the elbow/knee)
  reach(side, wrist, pole) arm IK to a wrist position, elbow toward pole
  plant(side, ...)             leg IK to a foot placed on the floor (yaw,
                               heel lift), sole and toes kept flat
  hand(side, fingers, thumb)   orient the hand (finger direction + thumb-side
                               direction), choosing the forearm roll that keeps
                               the wrist untwisted
  curl(side, ...)              relaxed finger curl toward the palm

POSES maps a name to a function(Poser). The log lists what each pose did and
any bone it could not find; nothing here edits the mesh or the weights.
"""

import copy
import json
import math
import os

import bpy
from mathutils import Matrix, Quaternion, Vector

X, Y, Z = Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))
FINGERS = ("index", "middle", "ring", "pinky")


def _q(axis, deg):
    return Quaternion(Vector(axis).normalized(), math.radians(deg))


def _sfx(s):
    return "_l" if s > 0 else "_r"


class Poser:
    def __init__(self, arm, reset=True):
        """reset=False keeps the current pose (e.g. a deform_poses pose) and
        works on top of it."""
        self.arm = arm
        self.pb = arm.pose.bones
        self.log = []
        mats = {p.name: p.matrix.copy() for p in self.pb}
        for p in self.pb:
            p.rotation_mode = "QUATERNION"
            if reset:
                p.rotation_quaternion = (1, 0, 0, 0)
                p.location = (0, 0, 0)
                p.scale = (1, 1, 1)
        self.update()
        if not reset:
            for p in self.pb:          # parents first: re-seat any converted rotation
                if p.matrix.to_quaternion().rotation_difference(mats[p.name].to_quaternion()).angle > 1e-4 or \
                        (p.matrix.translation - mats[p.name].translation).length > 1e-5:
                    p.matrix = mats[p.name]
                    self.update()
        self.rest = {p.name: p.bone.matrix_local.copy() for p in self.pb}

    # ---------------------------------------------------------------- basics
    def update(self):
        bpy.context.view_layer.update()

    def has(self, b):
        if b in self.pb:
            return True
        self.log.append(f"missing bone {b}")
        return False

    def head(self, b):
        return self.pb[b].head.copy()

    def tail(self, b):
        return self.pb[b].tail.copy()

    def dir(self, b):
        return (self.tail(b) - self.head(b)).normalized()

    def rotq(self, b):
        return self.pb[b].matrix.to_quaternion()

    def rotate(self, b, q, pivot=None):
        """Apply the armature-space rotation q to bone b about pivot (its head)."""
        if not self.has(b):
            return
        p = self.pb[b]
        m = p.matrix.copy()
        h = m.translation.copy() if pivot is None else Vector(pivot)
        p.matrix = Matrix.Translation(h) @ q.to_matrix().to_4x4() @ Matrix.Translation(-h) @ m
        self.update()

    def rot(self, b, axis, deg):
        self.rotate(b, _q(axis, deg))

    def aim(self, b, d):
        self.rotate(b, self.dir(b).rotation_difference(Vector(d).normalized()))

    def twist(self, b, deg):
        self.rotate(b, _q(self.dir(b), deg))

    def move(self, b, delta):
        if not self.has(b):
            return
        p = self.pb[b]
        p.matrix = Matrix.Translation(Vector(delta)) @ p.matrix
        self.update()

    def set_rot(self, b, q_target):
        """Give bone b the armature-space orientation q_target (pivot: head)."""
        self.rotate(b, q_target @ self.rotq(b).inverted())

    # ---------------------------------------------------------------- IK
    def _hinge_now(self, upper, hinge_rest):
        """Armature-space hinge axis of the joint at the end of `upper`, given
        its rest-pose armature-space direction (carried by the upper bone)."""
        q_rest = self.rest[upper].to_quaternion()
        return (self.rotq(upper) @ q_rest.inverted()) @ Vector(hinge_rest)

    def ik2(self, upper, lower, target, pole, hinge_rest):
        """Two-bone IK: the tail of `lower` reaches
        target; the joint bends toward `pole`. hinge_rest: the joint's hinge
        axis in the rest pose (armature space), oriented so that bending the
        joint is a positive rotation of `lower` about it."""
        if not (self.has(upper) and self.has(lower)):
            return
        H = self.head(upper)
        L1 = (self.tail(upper) - H).length
        L2 = (self.tail(lower) - self.head(lower)).length
        T = Vector(target)
        d = T - H
        dist = min(d.length, (L1 + L2) * 0.9995)
        dn = d.normalized()
        a = (L1 * L1 - L2 * L2 + dist * dist) / (2 * dist)
        h = math.sqrt(max(L1 * L1 - a * a, 0.0))
        p = Vector(pole) - dn * Vector(pole).dot(dn)
        p = p.normalized() if p.length > 1e-6 else Vector((0, 0, 1))
        K = H + dn * a + p * h
        self.aim(upper, K - H)
        # Twist the upper bone so its hinge is normal to the (H, K, T) plane.
        n = (K - H).cross(T - K)
        if n.length > 1e-6:
            n.normalize()
            hz = self._hinge_now(upper, hinge_rest)
            ax = self.dir(upper)
            hz_p = (hz - ax * hz.dot(ax)).normalized()
            ang = math.atan2(ax.dot(hz_p.cross(n)), hz_p.dot(n))
            self.rotate(upper, Quaternion(ax, ang))
        self.aim(lower, H + dn * dist - self.head(lower))

    # ---------------------------------------------------------------- legs
    def plant(self, s, ball_xy, yaw=0.0, heel=0.0, pole=None, pelvis_drop=0.0):
        """Place the foot of side s so the ball joint sits at ball_xy on the
        floor (rest height), toes pointing yaw deg outward from straight ahead,
        heel lifted by `heel` deg (pivot on the ball; negative = toes up, a
        heel strike). The knee bends toward `pole` (default: forward)."""
        x = _sfx(s)
        thigh, calf, foot, ball = "thigh" + x, "calf" + x, "foot" + x, "ball" + x
        if not all(self.has(b) for b in (thigh, calf, foot, ball)):
            return
        rq_foot = self.rest[foot].to_quaternion()
        rq_ball = self.rest[ball].to_quaternion()
        a_rest = self.rest[foot].translation.copy()
        b_rest = self.rest[ball].translation.copy()
        q_yaw = _q(Z, s * yaw)
        q_f = q_yaw @ _q(X, heel)
        ball_t = Vector((ball_xy[0], ball_xy[1], b_rest.z))
        if heel < 0:
            # heel strike: the foot pivots about the heel, toes up; place the
            # heel where the flat foot's heel would be
            heel_pt = Vector((a_rest.x, a_rest.y + 0.06, 0.0))
            heel_t = ball_t + q_yaw @ (heel_pt - b_rest)
            ankle_t = heel_t + q_f @ (a_rest - heel_pt)
        else:
            ankle_t = ball_t + q_f @ (a_rest - b_rest)
        pole = Vector(pole) if pole is not None else (q_yaw @ Vector((0, -1, 0)))
        self.ik2(thigh, calf, ankle_t, pole, X)
        self.set_rot(foot, q_f @ rq_foot)
        if heel > 0:
            self.set_rot(ball, q_yaw @ rq_ball)  # toes stay flat on the floor
        else:
            self.set_rot(ball, q_f @ rq_ball)

    # ---------------------------------------------------------------- arms
    def _hand_frame(self, s):
        """(finger direction, thumb-side direction) of the hand, armature space."""
        x = _sfx(s)
        h = self.head("hand" + x)
        f = (self.head("middle_01" + x) - h).normalized()
        t = self.head("index_01" + x) - self.head("pinky_01" + x)
        t = (t - f * t.dot(f)).normalized()
        return f, t

    def _palm(self, s):
        """Palm normal (pointing out of the palm), armature space."""
        f, t = self._hand_frame(s)
        n = f.cross(t)
        # The thumb sits on the palm side of the knuckle line.
        x = _sfx(s)
        th = self.tail("thumb_02" + x) - self.head("index_01" + x)
        return n if n.dot(th) > 0 else -n

    def reach(self, s, wrist, pole, clavicle=0.0, clav_fwd=0.0):
        """Arm IK: wrist (hand head) to `wrist`, elbow toward `pole`.
        clavicle: deg the shoulder drops (+) or shrugs (-); clav_fwd: deg the
        shoulder rolls forward."""
        x = _sfx(s)
        if clavicle:
            self.rot("clavicle" + x, Y, s * clavicle)
        if clav_fwd:
            self.rot("clavicle" + x, Z, -s * clav_fwd)
        ua, la = "upperarm" + x, "lowerarm" + x
        # Elbow hinge from the rest pose (the A-pose elbow is bent ~44 deg).
        hu = (self.rest[la].translation - self.rest[ua].translation).normalized()
        hl = (self.rest["hand" + x].translation - self.rest[la].translation).normalized()
        hinge = hu.cross(hl).normalized()
        self.ik2(ua, la, wrist, pole, hinge)

    def hand(self, s, fingers, thumb, wrist_share=0.35):
        """Orient the hand so its fingers point along `fingers` and its thumb
        side along `thumb` (both armature space, given for the left hand and
        mirrored in x for the right). The forearm takes the roll
        (pronation/supination) except `wrist_share` of it, so the wrist does
        not candy-wrap."""
        x = _sfx(s)
        la, hd = "lowerarm" + x, "hand" + x
        fd = Vector((s * fingers[0], fingers[1], fingers[2])).normalized()
        td = Vector((s * thumb[0], thumb[1], thumb[2]))
        td = (td - fd * td.dot(fd)).normalized()

        def target_q():
            f, t = self._hand_frame(s)
            b0 = Matrix((f, t, f.cross(t))).transposed()
            b1 = Matrix((fd, td, fd.cross(td))).transposed()
            return (b1 @ b0.inverted()).to_quaternion()

        # Roll the forearm about its own axis by the twist part of the needed
        # hand rotation (swing-twist about the forearm axis).
        q = target_q()
        ax = self.dir(la)
        v = Vector((q.x, q.y, q.z))
        proj = ax * v.dot(ax)
        tw = Quaternion((q.w, proj.x, proj.y, proj.z))
        if tw.magnitude > 1e-6:
            tw.normalize()
            ang = tw.angle if tw.axis.dot(ax) >= 0 else -tw.angle
            if ang > math.pi:
                ang -= 2 * math.pi
            self.rotate(la, Quaternion(ax, ang * (1.0 - wrist_share)))
        self.rotate(hd, target_q())

    def curl(self, s, base=(12, 18, 24, 30), seg=(1.0, 1.3, 0.8), spread=3.0,
             thumb=(10, 12, 8)):
        """Relaxed finger curl: finger k bends base[k] deg at the knuckle,
        scaled by seg along its three joints; pinky curls most. spread fans
        the fingers apart a little (deg). thumb: flexion of its three joints."""
        x = _sfx(s)
        palm = self._palm(s)
        for k, fname in enumerate(FINGERS):
            for j in range(3):
                b = f"{fname}_0{j + 1}{x}"
                if not self.has(b):
                    continue
                d = self.dir(b)
                axis = d.cross(palm).normalized()
                self.rot(b, axis, base[k] * seg[j])
                if j == 0 and spread:
                    self.rot(b, palm, s * spread * (k - 1.5) * (1 if fname != "index" else 1))
        for j, deg in enumerate(thumb):
            b = f"thumb_0{j + 1}{x}"
            if not self.has(b):
                continue
            d = self.dir(b)
            axis = d.cross(palm).normalized()
            self.rot(b, axis, deg)

    def look(self, yaw=0.0, pitch=0.0, tilt=0.0, neck_share=0.4):
        """Turn the head yaw deg to the character's left (+), nod pitch deg
        down (+), tilt deg toward its left shoulder (+); the neck takes
        neck_share of each."""
        for b, share in (("neck_01", neck_share), ("head", 1.0 - neck_share)):
            if yaw:
                self.rot(b, Z, yaw * share)
            if pitch:
                self.rot(b, X, -pitch * share)
            if tilt:
                self.rot(b, Y, tilt * share)


# ------------------------------------------------------------------- poses
# Rest (A-pose) facts for this rig (data/build/lookdev/*/character.blend):
# shoulder joint (0.203, -0.013, 1.482), arm 0.27 + 0.25 m, hip joint
# (0.114, 0.006, 0.99), ball joint (0.196, -0.137, 0.009), ankle z 0.075.

def pose_rest(p):
    p.log.append("rest: the build's A-pose")


def pose_stand(p, look=(12.0, 4.0, -2.0)):
    """Relaxed hero stand: weight on the right leg, left knee eased, pelvis
    tilted (left hip down), shoulders counter-tilted and settled, arms down at
    the sides with a soft elbow, hands relaxed, head turned a little to its
    left."""
    p.move("pelvis", (-0.025, 0.0, -0.012))
    p.rot("pelvis", Y, 3.5)       # left hip drops (free leg)
    p.rot("pelvis", Z, -4.0)      # left hip a little forward
    p.rot("spine_01", Y, -1.5)
    p.rot("spine_02", Y, -1.5)
    p.rot("spine_03", Y, -1.0)    # shoulders counter-tilt
    p.rot("spine_03", Z, 3.0)     # chest turns back toward the camera
    p.rot("spine_02", X, -2.0)    # slight chest lift
    p.plant(-1, (-0.13, -0.135), yaw=8)                 # weight leg, under the body
    p.plant(+1, (0.215, -0.20), yaw=16, pole=(0.25, -1, 0))  # free leg forward, out
    for s in (+1, -1):
        sh = p.head("upperarm" + _sfx(s))
        wrist = Vector((sh.x + s * 0.045, sh.y - 0.035, sh.z - 0.505))
        p.reach(s, wrist, pole=(s * 0.25, 1.0, -0.1), clavicle=4.0)
        p.hand(s, fingers=(-0.10, -0.12, -1.0), thumb=(0.0, -1.0, 0.0))
        p.curl(s, base=(14, 20, 26, 32), thumb=(6, 10, 10))
    p.look(yaw=look[0], pitch=look[1], tilt=look[2])


def pose_walk(p):
    """Mid-stride, left foot forward at heel contact, right foot pushing off;
    pelvis turned with the forward leg, chest counter-rotated, arms swinging
    opposite the legs, head forward."""
    p.move("pelvis", (0.0, -0.03, -0.03))
    p.rot("pelvis", Z, -7.0)
    p.rot("pelvis", Y, -2.0)
    p.rot("spine_01", Z, 3.0)
    p.rot("spine_02", Z, 4.0)
    p.rot("spine_03", Z, 4.0)
    p.rot("spine_01", X, 3.0)     # slight forward lean
    p.plant(+1, (0.11, -0.47), yaw=6, heel=-12, pole=(0.1, -1, 0))
    p.plant(-1, (-0.10, 0.20), yaw=6, heel=28, pole=(-0.1, -1, 0))
    # arms swing opposite the legs: right arm forward, left arm back (the
    # left leg leads); wrists a little out from the hips so the fingers
    # clear the jacket skirt and trousers
    for s, fwd in ((+1, -0.18), (-1, 0.16)):
        sh = p.head("upperarm" + _sfx(s))
        wrist = Vector((sh.x + s * 0.06, sh.y - fwd, sh.z - 0.49 + abs(fwd) * 0.1))
        p.reach(s, wrist, pole=(s * 0.2, 1.0, -0.2), clavicle=3.0)
        p.hand(s, fingers=(-0.05, -0.15 - fwd * 0.6, -1.0), thumb=(0.0, -1.0, 0.0))
        p.curl(s, base=(16, 22, 28, 34), thumb=(6, 10, 10))
    p.look(yaw=-6.0, pitch=2.0)


def pose_ready(p):
    """Compressed high-ready (direction §5 shot 4; the brief's low-ready is
    `ready_low`): staggered feet (right foot back), knees soft, torso in,
    elbows down and in, both hands together in front of the sternum as if
    gripping a pistol (no weapon yet): right hand closed, left hand wrapped
    over it."""
    p.move("pelvis", (0.015, 0.03, -0.045))
    p.rot("pelvis", Z, 14.0)       # right side back (bladed stance)
    p.rot("spine_01", X, 6.0)
    p.rot("spine_02", X, 5.0)
    p.rot("spine_02", Z, -6.0)
    p.rot("spine_03", Z, -8.0)     # shoulders square to the front
    p.plant(+1, (0.14, -0.30), yaw=12)
    p.plant(-1, (-0.17, 0.17), yaw=35, heel=6)
    grip = Vector((-0.015, -0.36, 1.24))
    p.reach(-1, grip + Vector((-0.01, 0.0, 0.0)), pole=(-0.25, 0.3, -1.0), clavicle=-1.0, clav_fwd=6)
    p.reach(+1, grip + Vector((0.065, -0.012, -0.035)), pole=(0.3, 0.3, -1.0), clavicle=-1.0, clav_fwd=8)
    p.hand(-1, fingers=(-0.1, -1.0, 0.15), thumb=(0.15, -0.2, 1.0))
    p.curl(-1, base=(85, 88, 90, 92), seg=(1.0, 1.2, 0.6), spread=0.0, thumb=(5, 25, 20))
    p.hand(+1, fingers=(-0.7, -1.0, 0.05), thumb=(0.0, -0.4, 1.0))
    p.curl(+1, base=(45, 50, 55, 60), seg=(1.0, 1.1, 0.6), spread=0.0, thumb=(5, 15, 10))
    p.look(yaw=-8.0, pitch=-2.0)


def pose_ready_low(p):
    """Low-ready: as `ready`, hands lower and further out (arms ~45 deg down)."""
    p.move("pelvis", (0.015, 0.03, -0.04))
    p.rot("pelvis", Z, 14.0)
    p.rot("spine_01", X, 6.0)
    p.rot("spine_02", X, 4.0)
    p.rot("spine_02", Z, -6.0)
    p.rot("spine_03", Z, -8.0)
    p.plant(+1, (0.14, -0.30), yaw=12)
    p.plant(-1, (-0.17, 0.17), yaw=35, heel=6)
    grip = Vector((-0.02, -0.44, 1.02))
    p.reach(-1, grip + Vector((-0.01, 0.0, 0.0)), pole=(-0.4, 0.4, -1.0), clavicle=-1.0, clav_fwd=6)
    p.reach(+1, grip + Vector((0.07, 0.015, -0.01)), pole=(0.5, 0.4, -1.0), clavicle=-1.0, clav_fwd=8)
    p.hand(-1, fingers=(-0.1, -1.0, -0.6), thumb=(0.15, -0.3, 1.0))
    p.curl(-1, base=(70, 75, 78, 80), seg=(1.0, 1.2, 0.6), spread=0.0, thumb=(5, 20, 15))
    p.hand(+1, fingers=(-0.7, -1.0, -0.5), thumb=(0.0, -0.4, 1.0))
    p.curl(+1, base=(45, 50, 55, 60), seg=(1.0, 1.1, 0.6), spread=0.0, thumb=(5, 15, 10))
    p.look(yaw=-6.0, pitch=-4.0)


def cuff_arms(p):
    """Adjusting the cuff (direction §5 shot 5), on top of F's hero legs,
    torso and head: the left forearm across the front of the waist, back of
    the hand to the camera; the right hand pinches the left shirt cuff."""
    # upper arm down by the side, elbow ~90 deg, forearm level across the front
    p.reach(+1, Vector((0.06, -0.255, 1.15)), pole=(0.6, 0.3, -1.0))
    p.hand(+1, fingers=(-1.0, -0.25, -0.12), thumb=(0.0, 0.1, 1.0))
    p.curl(+1, base=(18, 24, 30, 36), thumb=(6, 10, 10))
    wl = p.head("hand_l")
    f = (wl - p.head("lowerarm_l")).normalized()
    cuff = wl - f * 0.035
    # right hand in front of the left wrist, fingers across and wrapping the
    # cuff from the front, thumb on top
    fr = Vector((0.85, 0.2, -0.3)).normalized()
    p.reach(-1, cuff - fr * 0.07 + Vector((0.0, -0.045, 0.0)), pole=(-0.7, 0.4, -1.0))
    p.hand(-1, fingers=(-fr.x, fr.y, fr.z), thumb=(0.0, 0.15, 1.0))
    p.curl(-1, base=(55, 62, 70, 75), seg=(1.0, 1.2, 0.7), spread=0.0, thumb=(10, 25, 20))
    p.log.append(f"cuff: left wrist {tuple(round(v, 3) for v in wl)}, right wrist "
                 f"{tuple(round(v, 3) for v in p.head('hand_r'))}")


def pose_stand_profile(p):
    """The hero stand, head straight ahead and chin 3 deg down (profile shot)."""
    pose_stand(p, look=(0.0, 3.0, 0.0))


# Track F's canonical poses (blender/character/deform_poses.py) drive the
# hero stand and the ready stances; E's own solver versions stay available as
# `*_e` (and for the walk, which F only has as a deformation test pose).
F_POSES = {"stand": "hero", "ready": "high_ready", "ready_low": "low_ready"}
# F's pose for the body, E's solver on top for the arms
HYBRID = {"cuff": ("hero", "cuff_arms")}

POSES = {"rest": pose_rest, "stand_e": pose_stand, "stand_profile_e": pose_stand_profile,
         "walk": pose_walk, "ready_e": pose_ready, "ready_low_e": pose_ready_low}


def _dp():
    try:
        from character import deform_poses
        return deform_poses
    except ImportError:
        return None


# Bladed high-ready (hero `ready`): F/G's high_ready grip and hands, with the
# torso turned BLADE_DEG to its right (gun-side shoulder back, support
# shoulder forward), the support foot forward and the knees soft, and the head
# turned back so the eyes stay on the target (-Y). The arms' IK targets,
# poles and hand orientations (chest-frame values) are turned back by the
# same angle about the chest, so the two-hand grip keeps G's geometry (the
# support-hand wrap) and the gun stays on the eye-target line.
BLADE = {"pelvis": -18.0, "spine_01": -4.0, "spine_02": -4.0, "spine_03": -6.0}
BLADE_DEG = sum(BLADE.values())     # -32: the chest's turn


def _rot_z(v, deg):
    c, s_ = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return [v[0] * c - v[1] * s_, v[0] * s_ + v[1] * c, v[2]]


def bladed(spec):
    """high_ready -> bladed high-ready (a deep copy; see BLADE)."""
    spec = copy.deepcopy(spec)
    b = spec["bones"]

    def turn(bone, deg, keep=("flex", "tilt", "abduct")):
        ops = [op for op in b.get(bone, []) if op[0] in keep]
        b[bone] = ops + ([["turn", deg]] if deg else [])

    for bone, deg in BLADE.items():
        turn(bone, deg)
    # eyes back on the target: neck and head take the chest's turn back
    turn("neck_01", -0.45 * BLADE_DEG)
    turn("head", -0.55 * BLADE_DEG - 4.0)
    # stagger: support (left) foot forward, gun-side foot back, knees soft
    b["thigh_l"] = [["flex", 16]]
    b["calf_l"] = [["flex", 20]]
    b["foot_l"] = [["flex", 6]]
    b["thigh_r"] = [["flex", -10]]
    b["calf_r"] = [["flex", 12]]
    b["foot_r"] = [["flex", 4]]
    # arms and hands: chest-frame values turned back by the chest's turn
    # (values are written for the left side; the x mirror flips the sense)
    for bone in ("upperarm_l", "upperarm_r", "hand_l", "hand_r"):
        deg = (-1.0 if bone.endswith("_l") else 1.0) * BLADE_DEG
        for op in b.get(bone, []):
            v = op[1] if len(op) > 1 and isinstance(op[1], dict) else None
            if v is None:
                continue
            if op[0] == "orient" and v.get("frame", "spine_03") == "spine_03":
                v["fingers"], v["thumb"] = _rot_z(v["fingers"], deg), _rot_z(v["thumb"], deg)
            elif op[0] == "ik" and v.get("to") == "spine_03":
                v["offset"], v["pole"] = _rot_z(v["offset"], deg), _rot_z(v["pole"], deg)
    return spec


def _f_spec(name):
    """The deform_poses spec behind a stage pose name, or None."""
    dp = _dp()
    if dp is None:
        return None
    if name == "ready" and "high_ready" in dp.POSES:
        return bladed(dp.POSES["high_ready"])
    if name == "stand_profile":
        # the hero pose, head straight ahead and chin a little down (profile shot)
        spec = copy.deepcopy(dp.POSES["hero"])
        spec["bones"]["neck_01"] = [["flex", 1.5]]
        spec["bones"]["head"] = [["flex", 2.0]]
        return spec
    if name in F_POSES:
        return dp.POSES[F_POSES[name]]
    if name.startswith("f:") and name[2:] in dp.POSES:
        return dp.POSES[name[2:]]
    if name not in POSES and name in dp.POSES:
        return dp.POSES[name]
    return None


def names():
    dp = _dp()
    out = list(POSES) + [n for n in list(F_POSES) + list(HYBRID) + ["stand_profile"] if n not in POSES]
    out += ["ready+none", "ready+pistol1", "walk+pistol", "stand+pistol"]
    if dp is not None:
        out += [n for n in dp.POSES if n not in out] + ["f:" + n for n in dp.POSES]
    return out


def _rules(arm):
    if "deform_rules" in arm:
        return json.loads(arm["deform_rules"])
    if bpy.data.filepath:
        p = os.path.join(os.path.dirname(bpy.data.filepath), "character.rig.json")
        if os.path.exists(p):
            with open(p) as f:
                return json.load(f)
    return None


def _meshes(arm):
    return [o for o in bpy.data.objects if o.type == "MESH" and (
        o.parent == arm or any(m.type == "ARMATURE" and m.object == arm for m in o.modifiers))]


def deform(arm):
    """Track F's runtime after the pose: helper bones (twist split, deltoid and
    hip helpers, skirt follow) and corrective shape keys, exactly as the game
    drives them. Shape keys that are not correctives keep their values (the
    reference runtime zeroes every key it does not drive)."""
    R = _rules(arm)
    if not R:
        return "deform runtime: no rules in this build (helpers at bind)"
    from character import deform_runtime as drt
    meshes = _meshes(arm)
    keep = {(o.name, kb.name): kb.value for o in meshes if o.data.shape_keys
            for kb in o.data.shape_keys.key_blocks[1:]}
    w = drt.Runtime(arm, meshes, R).apply()
    for o in meshes:
        if o.data.shape_keys:
            for kb in o.data.shape_keys.key_blocks[1:]:
                if kb.name not in w and (o.name, kb.name) in keep:
                    kb.value = keep[(o.name, kb.name)]
    bpy.context.view_layer.update()
    on = ", ".join(f"{k} {v:.2f}" for k, v in sorted(w.items()) if v > 0.01)
    return f"deform runtime: {len(R.get('helpers', []))} helpers, correctives: {on or 'none active'}"


def apply(arm, name):
    """Pose the armature (F's canonical spec or E's solver), then run F's
    deformation runtime; returns the log (source, missing bones, notes).
    `name` may carry a held prop (Track H): "walk+pistol"; "ready" holds the
    pistol by default ("ready+none": empty hands)."""
    name, hold = _hold(name)
    if name in HYBRID and _dp() is not None:
        base, arms = HYBRID[name]
        _dp().apply_pose(arm, base)
        bpy.context.view_layer.update()
        p = Poser(arm, reset=False)
        globals()[arms](p)
        p.log.insert(0, f"pose {name}: deform_poses {base} + hero/poses.py {arms}")
        log = p.log
        log.append(deform(arm))
        return log + _hands(arm, name, hold)
    spec = _f_spec(name)
    if spec is not None:
        _dp().apply_pose(arm, spec)
        bpy.context.view_layer.update()
        src = ("hero, head straight" if name == "stand_profile" else "high_ready, bladed" if name == "ready"
               else (F_POSES.get(name) or name.removeprefix("f:")))
        log = [f"pose {name}: deform_poses {src}"]
    else:
        if name not in POSES:
            raise KeyError(f"unknown pose {name!r}; known: {', '.join(names())}")
        dp = _dp()
        if dp is not None:
            dp.reset(arm)
        p = Poser(arm)
        POSES[name](p)
        p.log.append(f"pose {name}: ok (hero/poses.py)")
        log = p.log
    log.append(deform(arm))
    return log + _hands(arm, name, hold)


# poses with no POSE_HANDS entry of their own: settle with this entry's
# rules ("hero" = lift both hands out of foreign geometry)
HAND_FALLBACK = {"walk": "hero", "stand_profile": "hero",
                 "stand_e": "hero", "ready_low_e": "hero", "stand_profile_e": "hero"}


def _hands(arm, name, hold=None):
    """Track G hand finishing (character/hand_pose.py): finger shapes, hands
    lifted out of sleeves they were posed into, fingers curled to contact.
    Track H: a held prop is put on its grip socket first (and the support
    hand on it, two-handed), the hands close on it (the prop's own settle
    spec), then the prop places the digits it needs (pistol: the index along
    the frame, the thumbs forward)."""
    try:
        from character import hand_pose
    except ImportError:
        return []
    keys = (name, F_POSES.get(name), name.removeprefix("f:"), HAND_FALLBACK.get(name))
    log, spec, after = _props(arm, name, hold or {}, keys)
    log += hand_pose.settle(arm, keys, rerun=lambda: deform(arm), spec=spec)
    for f in after:
        log += f()
    if after:
        r = deform(arm)
        log.append(f"after props: {r}")
    return log


# Track H (blender/props): props held by default in a stage pose, {side: prop}.
# Any pose takes one with a suffix ("walk+pistol": a one-hand low carry);
# "+none" drops it; "+pistol1" holds it one-handed in a TWO_HAND pose.
# TWO_HAND: poses where the other hand supports it.
HOLD = {"ready": {"r": "pistol"}}
TWO_HAND = ("ready",)


def _hold(name):
    base, _, prop = name.partition("+")
    if not prop:
        return base, dict(HOLD.get(base, {}))
    return base, ({} if prop == "none" else {"r": prop})


def _props(arm, name, hold, keys):
    """Show / hide the props, put the held ones on the hand's grip socket and
    seat them on the palm (before the hand settle). Returns (log, settle spec
    or None, callables to run after the settle)."""
    try:
        from props import pistol
    except ImportError:
        return ([f"props: not importable, {hold} not held"] if hold else []), None, []
    mods = {"pistol": pistol}
    log = []
    for prop, mod in mods.items():
        if prop not in (v.rstrip("1") for v in hold.values()):
            mod.hide()
    if not hold:
        return log, None, []
    dp = _dp()
    base = next((dp.POSE_HANDS[k] for k in keys if k and k in dp.POSE_HANDS), None) if dp else None
    spec = {k: v for k, v in (base or {}).items()}
    after = []
    for s, prop in hold.items():
        mod = mods[prop.rstrip("1")]
        other = "l" if s == "r" else "r"
        two = name in TWO_HAND and not prop.endswith("1")
        ob, lines = mod.hold(arm, s, rerun=lambda: deform(arm))
        log += lines
        # the holding hand settles first; a supporting hand is put on the
        # prop after that, and settles in the prop's own pass
        sup = spec.pop(other, None) if two else None
        spec = {s: mod.hand_spec(s), **{k: v for k, v in spec.items() if k != s}}
        after.append(lambda mod=mod, ob=ob, s=s, other=other, two=two, sup=sup:
                     mod.finish_hold(arm, ob, s, other if two else None, sup, rerun=lambda: deform(arm)))
    return log, spec, after
