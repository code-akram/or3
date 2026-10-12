"""Canonical poses for the hero character, as data, plus the engine that applies
them to a game_engine (UE-mannequin-named) armature.

The poses are written in anatomical terms, so they do not depend on the bone
roll the exporter or the glTF importer picks (all axes come from joint
positions):

    flex      hinge/flexion; + = forward bend (spine, neck, head), limb
              forward (upperarm, thigh), knee bend (calf), elbow bend
              (lowerarm), wrist flexion toward the palm (hand), curl (fingers),
              dorsiflexion (foot, ball), protraction (clavicle)
    abduct    + = away from the midline (upperarm, thigh), shrug (clavicle),
              radial deviation toward the thumb (hand)
    twist     about the bone's own axis; + = internal rotation (pronation for
              the hand / forearm). Mirrored per side.
    turn      about the up axis; + = toward the character's left (spine, neck, head)
    tilt      lateral bend; + = toward the character's left
    aim       point the bone along a direction in the reference bone's rest
              frame (x = the character's left for _l bones, mirrored for _r)
    ik        two-bone IK on upperarm/thigh: {"to": bone, "offset": [x,y,z],
              "pole": [x,y,z]}: the hand / foot goes to `to`'s posed head plus
              the offset (rotated with `to`), the elbow / knee toward pole.
              x is mirrored for _r.
    move      translate (pelvis): [x, y, z] metres, armature space
    side_l / side_r are written explicitly; `sym()` mirrors a left-side spec.

Every op is applied about the bone head, in order, in the current (parent-
posed) frame: "flex 90 then abduct 20" is not "abduct 20 then flex 90".
Axes for limbs are taken in the reference bone's posed frame (spine_03 for
the arms, pelvis for the legs, the parent otherwise), so a clavicle shrug
does not tilt the arm's abduction plane.

Use (Blender):

    from character import deform_poses as dp
    dp.apply_pose(arm_obj, "hero")          # or a spec dict
    dp.reset(arm_obj)

The runtime rules for the helper bones and corrective morphs are separate
(deform_runtime.py); call deform_runtime.apply() after apply_pose().
Angles in degrees, lengths in metres. Character faces -Y, +X is its left.
"""

import math

from mathutils import Matrix, Quaternion, Vector

X, Y, Z = Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))
FINGERS = ("thumb", "index", "middle", "ring", "pinky")


# ---------------------------------------------------------------- pose data

def sym(spec_l, extra=None):
    """Mirror a left-side bone spec onto the right (ops are anatomical, so
    the values carry over unchanged)."""
    out = {}
    for k, v in spec_l.items():
        out[k] = v
        if k.endswith("_l"):
            out[k[:-2] + "_r"] = v
    out.update(extra or {})
    return out


def hand(mcp, pip, dip, thumb=(10, 10, 10), spread=0.0, prefix_ops=None, index=None):
    """Finger curl for one hand: {finger: [[flex, deg]]} (left names).
    index: optional (mcp, pip, dip) for the index finger (trigger finger)."""
    out = {}
    for f in FINGERS[1:]:
        m, p, d = (index if (f == "index" and index) else (mcp, pip, dip))
        out[f"{f}_01_l"] = [["flex", m]]
        out[f"{f}_02_l"] = [["flex", p]]
        out[f"{f}_03_l"] = [["flex", d]]
    t1, t2, t3 = thumb
    out["thumb_01_l"] = [["flex", t1]]
    out["thumb_02_l"] = [["flex", t2]]
    out["thumb_03_l"] = [["flex", t3]]
    return out


def side(spec_l, s):
    """Rename a left spec to side s ('l' or 'r')."""
    return {(k[:-2] + "_" + s if k.endswith("_l") else k): v for k, v in spec_l.items()}


RELAXED_HAND = hand(18, 28, 12, thumb=(8, 10, 12))
HERO_RIGHT_HAND = hand(20, 35, 15, thumb=(10, 12, 15))  # direction.md §2 Track F
GRIP = hand(75, 85, 45, thumb=(25, 25, 25), index=(30, 25, 10))  # trigger finger along the frame
SUPPORT_GRIP = hand(60, 75, 40, thumb=(20, 20, 20))
FIST = hand(85, 95, 60, thumb=(35, 30, 30))

ARMS_DOWN = {"upperarm_l": [["abduct", -36], ["flex", 4], ["twist", 5]],
             "lowerarm_l": [["flex", -22]],
             "hand_l": [["flex", 5]]}

POSES = {
    "rest": {"bones": {}, "view": 25, "closeups": ["chest", "torso_front", "neck", "shoulder_l", "skirt_l", "hip_front_l"]},
    # 1. Relaxed stand, arms down, fingers soft.
    "relaxed": {
        "bones": sym({**ARMS_DOWN, **RELAXED_HAND}, {
            "spine_03": [["flex", -2]], "neck_01": [["flex", 3]]}),
        "view": 25,
        "closeups": ["shoulder_l", "armpit_l", "elbow_l", "wrist_l", "hand_l", "neck", "hip_l"],
    },
    # 2. 3/4 walk, mid-stride: left leg forward, right leg back, arms counter-swing.
    "walk": {
        "bones": {
            **sym(RELAXED_HAND),
            "pelvis": [["turn", 5]],
            "spine_02": [["turn", -4]], "spine_03": [["turn", -4]],
            "thigh_l": [["flex", 26], ["abduct", -2]], "calf_l": [["flex", 8]], "foot_l": [["flex", 12]],
            "thigh_r": [["flex", -14], ["abduct", -2]], "calf_r": [["flex", 38]], "foot_r": [["flex", -16]],
            "upperarm_l": [["abduct", -36], ["flex", -18], ["twist", 5]], "lowerarm_l": [["flex", -26]],
            "upperarm_r": [["abduct", -36], ["flex", 22], ["twist", 5]], "lowerarm_r": [["flex", -8]],
            "neck_01": [["turn", 2]],
        },
        "ground": True,
        "view": 40,
        "closeups": ["hip_front_l", "hip_back_r", "knee_r", "skirt_l", "shoulder_r", "elbow_r"],
    },
    # 3. Low ready: both arms forward, hands together low in front, pistol 45 deg down.
    "low_ready": {
        "bones": {
            **side(GRIP, "r"), **SUPPORT_GRIP,
            "spine_01": [["flex", 6]], "spine_03": [["flex", 6]], "neck_01": [["flex", 6]], "head": [["flex", 8]],
            "thigh_l": [["flex", 10]], "calf_l": [["flex", 16]], "foot_l": [["flex", 6]],
            "thigh_r": [["flex", 8]], "calf_r": [["flex", 14]], "foot_r": [["flex", 6]],
            "clavicle_l": [["flex", 8]], "clavicle_r": [["flex", 8]],
            "upperarm_r": [["ik", {"to": "spine_03", "offset": [-0.01, -0.42, -0.12], "pole": [-0.5, 0.3, -1]}]],
            "hand_r": [["flex", -10], ["twist", -60], ["abduct", 10]],
            "upperarm_l": [["ik", {"to": "spine_03", "offset": [-0.01, -0.40, -0.13], "pole": [0.5, 0.3, -1]}]],
            "hand_l": [["flex", 10], ["twist", -40]],
        },
        "ground": True,
        "view": 30,
        "closeups": ["chest", "torso_front", "shoulder_l", "shoulder_r", "elbow_r", "wrist_r", "hand_r", "armpit_r", "neck"],
    },
    # 4. Raised knee (the left), arms relaxed: the jacket-skirt test.
    "knee_up": {
        "bones": sym({**ARMS_DOWN, **RELAXED_HAND}, {
            "thigh_l": [["flex", 90]], "calf_l": [["flex", 90]], "foot_l": [["flex", 0]],
        }),
        "view": 35,
        "closeups": ["skirt_profile_l", "skirt_top_l", "skirt_l", "hip_front_l", "hip_back_l", "knee_l", "trouser_l"],
    },
    # 5. Arm raise: the left abducted to 95 deg with a natural clavicle shrug;
    #    the right flexed forward to 95 deg (shoulder flexion test).
    "arm_raise": {
        "bones": {
            **sym(RELAXED_HAND),
            "clavicle_l": [["abduct", 14]],
            "upperarm_l": [["aim", [1.0, 0.0, 0.087]], ["twist", -10]],
            "lowerarm_l": [["flex", -30]],
            "clavicle_r": [["abduct", 10], ["flex", 8]],
            "upperarm_r": [["aim", [0.12, -1.0, 0.087]]],
            "lowerarm_r": [["flex", -30]],
        },
        "view": 20,
        "closeups": ["shoulder_top_l", "armpit_l", "shoulder_back_l", "shoulder_r", "armpit_r", "elbow_l"],
    },
    # 6. Crouch: deep hip and knee flexion, feet planted, torso forward.
    "crouch": {
        "bones": {
            **sym({**RELAXED_HAND}),
            "pelvis": [["flex", 18]],
            "spine_01": [["flex", 10]], "spine_02": [["flex", 8]], "spine_03": [["flex", 2]],
            "neck_01": [["flex", -14]], "head": [["flex", -10]],
            "thigh_l": [["flex", 92], ["abduct", 10]], "calf_l": [["flex", 130]], "foot_l": [["flex", 20]],
            "thigh_r": [["flex", 92], ["abduct", 10]], "calf_r": [["flex", 130]], "foot_r": [["flex", 20]],
            "upperarm_l": [["abduct", -30], ["flex", 40]], "lowerarm_l": [["flex", 20]],
            "upperarm_r": [["abduct", -30], ["flex", 40]], "lowerarm_r": [["flex", 20]],
        },
        "ground": True,
        "view": 45,
        "closeups": ["torso_front", "skirt_profile_l", "hip_front_l", "hip_back_l", "knee_l", "skirt_l", "skirt_back", "trouser_l"],
    },
    # 7. Hero pose (direction.md §2 Track F): weight on the left leg, pelvis
    #    tilted 4 deg (free right hip drops), shoulders 5 deg back, head turned
    #    10 deg toward camera (camera on the character's left) and tilted 3 deg;
    #    right hand relaxed (MCP 20, PIP 35, DIP 15), left hand at the jacket button.
    "hero": {
        "bones": {
            **side(HERO_RIGHT_HAND, "r"),
            **hand(30, 50, 30, thumb=(25, 20, 15)),
            "pelvis": [["tilt", 4], ["turn", -4]],
            "spine_01": [["tilt", -2]], "spine_02": [["tilt", -2], ["turn", 3]],
            "spine_03": [["flex", -5], ["tilt", -1], ["turn", 3]],
            "clavicle_l": [["flex", -5]], "clavicle_r": [["flex", -5]],
            "neck_01": [["turn", 5], ["tilt", 1.5]], "head": [["turn", 5], ["tilt", 1.5], ["flex", 2]],
            "thigh_l": [["abduct", -2], ["flex", 0]], "calf_l": [["flex", 2]], "foot_l": [["abduct", 0]],
            "thigh_r": [["abduct", 3], ["flex", 10], ["twist", -8]], "calf_r": [["flex", 18]],
            "foot_r": [["flex", 2]],
            "upperarm_r": [["abduct", -38], ["flex", 3], ["twist", 8]], "lowerarm_r": [["flex", -20]],
            "hand_r": [["flex", 6]],
            "upperarm_l": [["ik", {"to": "pelvis", "offset": [0.025, -0.15, 0.16], "pole": [1.0, 0.6, -0.4]}]],
            "hand_l": [["flex", 20], ["twist", 20], ["abduct", -10]],
        },
        "ground": True,
        "view": 30,
        "closeups": ["torso_front", "shoulder_l", "elbow_l", "hand_l", "hand_r", "neck", "hip_l", "skirt_r"],
    },
    # 8. High-ready pistol stance, elbows in: gun close to the chest, muzzle forward.
    "high_ready": {
        "bones": {
            **side(GRIP, "r"), **SUPPORT_GRIP,
            "spine_01": [["flex", 4]], "spine_03": [["flex", 4], ["turn", 6]],
            "neck_01": [["flex", 2]], "head": [["flex", 4], ["turn", -4]],
            "thigh_l": [["flex", 12]], "calf_l": [["flex", 18]], "foot_l": [["flex", 6]],
            "thigh_r": [["flex", -4]], "calf_r": [["flex", 10]],
            "upperarm_r": [["ik", {"to": "spine_03", "offset": [-0.02, -0.36, 0.12], "pole": [-0.15, 0.2, -1]}]],
            "hand_r": [["flex", -20], ["twist", -70]],
            "upperarm_l": [["ik", {"to": "spine_03", "offset": [-0.015, -0.34, 0.105], "pole": [0.15, 0.2, -1]}]],
            "hand_l": [["flex", 10], ["twist", -50]],
        },
        "ground": True,
        "view": 35,
        "closeups": ["chest", "torso_front", "elbow_r", "elbow_l", "armpit_r", "wrist_r", "hand_r", "neck", "shoulder_l"],
    },
    # 9. Head turned 30 deg (collar test) and tilted, arms relaxed.
    "head_turn": {
        "bones": sym({**ARMS_DOWN, **RELAXED_HAND}, {
            "neck_01": [["turn", 15], ["tilt", 4]], "head": [["turn", 15], ["tilt", 4], ["flex", -6]]}),
        "view": 0,
        "closeups": ["neck", "neck_l", "neck_r", "neck_back"],
    },
    # 10. Twist stress: forearm pronation/supination, fist, wrist flexion.
    "twist": {
        "bones": {
            **FIST, **side(RELAXED_HAND, "r"),
            "upperarm_l": [["abduct", -10], ["flex", 30]], "lowerarm_l": [["flex", 60]],
            "hand_l": [["twist", 80], ["flex", 40]],
            "upperarm_r": [["abduct", -10], ["flex", 30]], "lowerarm_r": [["flex", 60]],
            "hand_r": [["twist", -70], ["flex", -40]],
        },
        "view": 20,
        "closeups": ["wrist_l", "wrist_r", "hand_l", "elbow_l", "forearm_l", "forearm_r"],
    },
}

HERO_POSES = ("hero", "high_ready")


# ---------------------------------------------------------------- engine

def _side(name):
    return name[-1] if name.endswith(("_l", "_r")) else ""


def _sgn(name):
    return -1.0 if name.endswith("_r") else 1.0


def _mirror(v, name):
    return Vector((v[0] * _sgn(name), v[1], v[2]))


class Rig:
    """Rest-pose anatomy of the armature (joint positions only)."""

    def __init__(self, arm):
        self.arm = arm
        self.bones = arm.data.bones
        self.head = {b.name: b.head_local.copy() for b in self.bones}
        self.tail = {b.name: b.tail_local.copy() for b in self.bones}

    def has(self, n):
        return n in self.head

    def child_head(self, n, child):
        return self.head[child] if self.has(child) else self.tail[n]

    def dir(self, n):
        """Rest direction of a bone from joint positions."""
        s = _side(n)
        nxt = {"upperarm": "lowerarm", "lowerarm": "hand", "thigh": "calf", "calf": "foot",
               "foot": "ball", "clavicle": "upperarm", "hand": "middle_01"}
        base = n[:-2] if s else n
        if base in nxt:
            c = f"{nxt[base]}_{s}"
            return (self.child_head(n, c) - self.head[n]).normalized()
        for f in FINGERS:
            for k, nk in (("01", "02"), ("02", "03")):
                if base == f"{f}_{k}":
                    return (self.child_head(n, f"{f}_{nk}_{s}") - self.head[n]).normalized()
            if base == f"{f}_03":
                p = f"{f}_02_{s}"
                return (self.head[n] - self.head[p]).normalized()
        return (self.tail[n] - self.head[n]).normalized()

    def palm(self, s):
        """(finger direction, thumb-side direction, palm normal) of a hand, rest."""
        h = self.head[f"hand_{s}"]
        f = (self.head[f"middle_01_{s}"] - h).normalized()
        t = self.head[f"index_01_{s}"] - self.head[f"pinky_01_{s}"]
        t = (t - f * t.dot(f)).normalized()
        n = f.cross(t)
        if s == "r":
            n = -n
        return f, t, n

    def ref(self, n, op=None):
        """Bone whose posed frame carries the op's rest axis: the thorax for
        the arm, the pelvis for the leg, the forearm for a hand twist, the
        bone itself (parent motion + its earlier ops) otherwise."""
        base = n[:-2] if _side(n) else n
        if base == "upperarm" and op != "twist":
            return "spine_03"
        if base == "thigh" and op != "twist":
            return "pelvis"
        if base == "hand" and op == "twist":
            return f"lowerarm_{_side(n)}"
        return n

    def axis(self, n, op):
        """Rest-space rotation axis for an anatomical op (sign included)."""
        s = _side(n)
        base = n[:-2] if s else n
        sg = _sgn(n)
        if op == "turn":
            return Z.copy()
        if op == "tilt":
            return Y.copy()
        if op == "twist":
            if base == "hand":
                return self.dir(f"lowerarm_{s}") * sg
            return self.dir(n) * sg
        if op == "flex":
            if base in ("pelvis", "spine_01", "spine_02", "spine_03", "neck_01", "head", "Root"):
                return X.copy()
            if base in ("thigh", "upperarm", "foot", "ball"):
                return -X
            if base == "calf":
                return X.copy()
            if base == "clavicle":
                return -Z * sg
            if base == "lowerarm":
                u = self.head[f"lowerarm_{s}"] - self.head[f"upperarm_{s}"]
                l = self.head[f"hand_{s}"] - self.head[f"lowerarm_{s}"]
                return u.cross(l).normalized()
            if base == "hand":
                f, t, nrm = self.palm(s)
                return f.cross(nrm).normalized()
            if base.startswith("thumb"):
                # the thumb flexes across the palm toward the little finger;
                # the metacarpal (01) opposes, more toward the palm
                f, t, nrm = self.palm(s)
                to = (nrm - t * 0.5) if base == "thumb_01" else (nrm * 0.4 - t)
                return self.dir(n).cross(to.normalized()).normalized()
            if any(base.startswith(f) for f in FINGERS):
                _, _, nrm = self.palm(s)
                return self.dir(n).cross(nrm).normalized()
        if op == "abduct":
            if base in ("upperarm", "thigh", "clavicle", "foot"):
                return -Y * sg
            if base == "hand":
                f, t, nrm = self.palm(s)
                return f.cross(t).normalized()
            if any(base.startswith(f) for f in FINGERS):
                f, t, nrm = self.palm(s)
                return nrm.copy()
        raise ValueError(f"no axis for {op} on {n}")


def _rot_about(M, pivot, R3):
    T = Matrix.Translation(pivot)
    return T @ R3.to_4x4() @ Matrix.Translation(-pivot) @ M


def _rel(arm, rig, n):
    """Current rotation of bone n relative to its rest (armature space)."""
    if n is None:
        return Matrix.Identity(3)
    pb = arm.pose.bones[n]
    return pb.matrix.to_3x3().normalized() @ rig.bones[n].matrix_local.to_3x3().normalized().inverted()


def _cur_dir(arm, rig, n):
    return (_rel(arm, rig, n) @ rig.dir(n)).normalized()


def _update():
    import bpy
    bpy.context.view_layer.update()


def reset(arm):
    for pb in arm.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)
    _update()


def _order(arm):
    out = []

    def walk(b):
        out.append(b.name)
        for c in b.children:
            walk(c)
    for b in arm.data.bones:
        if b.parent is None:
            walk(b)
    return out


def _set(arm, n, M):
    arm.pose.bones[n].matrix = M
    _update()


def _ik(arm, rig, n, a):
    """Analytic two-bone IK: n = upperarm_* / thigh_*."""
    s = _side(n)
    base = n[:-2]
    mid, end = ({"upperarm": ("lowerarm", "hand"), "thigh": ("calf", "foot")}[base])
    mid, end = f"{mid}_{s}", f"{end}_{s}"
    pbs = arm.pose.bones
    S = pbs[n].head.copy()
    to = a["to"]
    T = pbs[to].head + _rel(arm, rig, to) @ _mirror(Vector(a["offset"]), n)
    pole = (_rel(arm, rig, rig.ref(n)) @ _mirror(Vector(a["pole"]), n)).normalized()
    l1 = (rig.head[mid] - rig.head[n]).length
    l2 = (rig.head[end] - rig.head[mid]).length
    d = T - S
    dist = min(max(d.length, 1e-4), (l1 + l2) * 0.999)
    dn = d.normalized()
    # elbow position: law of cosines, in the plane of d and the pole
    cos_a = (l1 * l1 + dist * dist - l2 * l2) / (2 * l1 * dist)
    a_ang = math.acos(max(-1.0, min(1.0, cos_a)))
    pp = (pole - dn * pole.dot(dn)).normalized()
    E = S + (dn * math.cos(a_ang) + pp * math.sin(a_ang)) * l1
    # 1) aim the upper bone at E
    cur = _cur_dir(arm, rig, n)
    want = (E - S).normalized()
    M = pbs[n].matrix.copy()
    M = _rot_about(M, S, cur.rotation_difference(want).to_matrix())
    _set(arm, n, M)
    # 2) roll the upper bone so the hinge axis is normal to the (S, E, T) plane
    hinge_rest = rig.axis(mid, "flex") if base == "upperarm" else X.copy()
    hinge = (_rel(arm, rig, n) @ hinge_rest).normalized()
    plane_n = (E - S).cross(T - E)
    if plane_n.length > 1e-6:
        plane_n.normalize()
        h_p = (hinge - want * hinge.dot(want)).normalized()
        ang = h_p.angle(plane_n)
        if h_p.cross(plane_n).dot(want) < 0:
            ang = -ang
        M = _rot_about(pbs[n].matrix.copy(), S, Quaternion(want, ang).to_matrix())
        _set(arm, n, M)
    # 3) bend the lower bone about the hinge so it reaches T
    Ecur = pbs[mid].head.copy()
    cur = _cur_dir(arm, rig, mid)
    want = (T - Ecur).normalized()
    M = _rot_about(pbs[mid].matrix.copy(), Ecur, cur.rotation_difference(want).to_matrix())
    _set(arm, mid, M)


def apply_pose(arm, pose, rig=None):
    """Pose `arm` from a POSES name or a spec dict ({"bones": {...}, "ground": bool})."""
    spec = POSES[pose] if isinstance(pose, str) else pose
    rig = rig or Rig(arm)
    reset(arm)
    bones = spec.get("bones", {})
    for n in _order(arm):
        ops = bones.get(n)
        if not ops or not rig.has(n):
            continue
        for op, val in ops:
            pb = arm.pose.bones[n]
            if op == "ik":
                _ik(arm, rig, n, val)
                continue
            M = pb.matrix.copy()
            if op == "move":
                M = Matrix.Translation(Vector(val)) @ M
            elif op == "aim":
                cur = _cur_dir(arm, rig, n)
                want = (_rel(arm, rig, rig.ref(n)) @ _mirror(Vector(val), n)).normalized()
                M = _rot_about(M, pb.head.copy(), cur.rotation_difference(want).to_matrix())
            else:
                ax = rig.axis(n, op)
                ax = (_rel(arm, rig, rig.ref(n, op)) @ ax).normalized()
                M = _rot_about(M, pb.head.copy(), Matrix.Rotation(math.radians(val), 3, ax))
            _set(arm, n, M)
    if spec.get("ground"):
        ground(arm, rig)
    return rig


def ground(arm, rig):
    """Lower the pelvis so the lower ankle sits at its rest height."""
    pbs = arm.pose.bones
    feet = [n for n in ("foot_l", "foot_r") if rig.has(n)]
    if not feet or not rig.has("pelvis"):
        return
    dz = min(pbs[n].head.z - rig.head[n].z for n in feet)
    if abs(dz) < 1e-5:
        return
    root = "pelvis"
    M = Matrix.Translation(Vector((0, 0, -dz))) @ pbs[root].matrix
    _set(arm, root, M)


def joint_angle(arm, rig, n):
    """Bend at bone n's head: angle between its posed direction and its
    parent's (deg), for reporting."""
    p = rig.bones[n].parent
    if p is None:
        return 0.0
    return math.degrees(_cur_dir(arm, rig, n).angle(_cur_dir(arm, rig, p.name)))
