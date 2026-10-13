"""Hand pose finishing (m1 v2 Track G): finger shapes, contact and
interpenetration, run after a pose is applied (blender/hero/poses.apply calls
settle() after the pose and Track F's runtime).

What it does, per hand, driven by deform_poses.POSE_HANDS[pose]:

  shape    replace the pose's finger curl with a named hand shape
           (deform_poses.HAND_SHAPES: per-finger flex / spread / twist, a
           cascade from index to pinky and a relaxed thumb).
  clear    lift the hand out of foreign geometry it was posed into: the
           other arm's sleeve and cuff, the torso, the other hand. The hand
           moves along the line from the overlap to the hand centre (arm
           re-solved with a two-bone IK, the hand keeps its orientation),
           by the smallest distance that clears it, plus a gap.
  wrap     fingers that hold something curl to contact: each listed
           finger's whole curl (MCP, PIP, DIP together, so the falloff is
           kept) is scaled to the largest value that does not cut into
           foreign geometry.
  spread   adjacent fingers (and thumb / index) that intersect are fanned
           apart at the MCP, 1.5 deg at a time, up to 10 deg.

Overlap is exact triangle-triangle intersection (BVHTree.overlap) between
the posed (evaluated) skin of a hand or finger and foreign triangles; a
vertex is foreign to a hand when its dominant bone is not on that arm's chain,
so the hand's own cuff and sleeve never count.

pierce(arm) reports the remaining overlaps (evidence, bench/m1/hands_render.py).
"""

import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector
from mathutils.bvhtree import BVHTree

FINGERS = ("index", "middle", "ring", "pinky")
DIGITS = ("thumb",) + FINGERS
ARM_CHAIN = ("clavicle", "upperarm", "upperarm_twist_01", "lowerarm", "lowerarm_twist_01", "hand",
             "deltoid_helper") + tuple(f"{d}_0{k}" for d in DIGITS for k in (1, 2, 3))
GAP_M = 0.002          # clearance left after a hand is lifted out of an overlap
LIFT_MAX_M = 0.08
SEARCH = 7             # bisection steps


# ---------------------------------------------------------------- mesh facts
def _meshes(arm):
    return [o for o in bpy.data.objects if o.type == "MESH" and not o.hide_render and (
        o.parent == arm or any(m.type == "ARMATURE" and m.object == arm for m in o.modifiers))]


_DOM = {}


def _dominant(o):
    """Per-vertex dominant deform group name (cached per mesh)."""
    key = (o.name, len(o.data.vertices))
    if key not in _DOM:
        names = {g.index: g.name for g in o.vertex_groups}
        out = []
        for v in o.data.vertices:
            best, bw = "", 0.0
            for g in v.groups:
                n = names.get(g.group, "")
                if n.startswith(("helper", "joint", "Delete", "body", "Left", "Right", "Mid")) or n in (
                        "fingernails", "lips", "ears", "scalp", "nipple", "nippleTip", "genitals", "HelperGeometry",
                        "JointCubes"):
                    continue
                if g.weight > bw:
                    best, bw = n, g.weight
            out.append(best)
        _DOM[key] = np.array(out, dtype=object)
    return _DOM[key]


def _side_of(n):
    return n[-1] if n.endswith(("_l", "_r")) else ""


def _own_chain(dom, s):
    return np.array([bool(d) and _side_of(d) == s and d[:-2] in ARM_CHAIN for d in dom])


def _posed(o):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = o.evaluated_get(dg)
    me = ev.to_mesh()
    try:
        n = len(me.vertices)
        co = np.empty(n * 3, np.float64)
        me.vertices.foreach_get("co", co)
        co = co.reshape(n, 3)
    finally:
        ev.to_mesh_clear()
    if n != len(o.data.vertices):
        return None
    mw = np.array(o.matrix_world)
    return co @ mw[:3, :3].T + mw[:3, 3]


def _polys(o):
    key = ("polys", o.name, len(o.data.polygons))
    if key not in _DOM:
        _DOM[key] = [tuple(p.vertices) for p in o.data.polygons]
    return _DOM[key]


def _bvh(co, polys, keep_vert):
    """BVH over the polygons whose vertices all pass keep_vert."""
    sel = [p for p in polys if all(keep_vert[i] for i in p)]
    if not sel:
        return None
    used = sorted({i for p in sel for i in p})
    remap = {v: k for k, v in enumerate(used)}
    verts = [Vector(co[i]) for i in used]
    return BVHTree.FromPolygons(verts, [tuple(remap[i] for i in p) for p in sel], epsilon=0.0)


class Scene:
    """Posed geometry around one hand: its own skin (palm and per digit) and
    the foreign triangles nearby."""

    def __init__(self, arm, s, radius=0.16):
        self.arm, self.s, self.radius = arm, s, radius
        self.meshes = _meshes(arm)
        self.body = max((o for o in self.meshes if "body" in o.vertex_groups), key=lambda o: len(o.data.vertices),
                        default=None)

    def centre(self):
        pb = self.arm.pose.bones
        mw = self.arm.matrix_world
        return mw @ ((pb[f"hand_{self.s}"].head + pb[f"middle_01_{self.s}"].head) * 0.5)

    def build(self, parts, own_palm=None):
        """parts: names ('palm' or a digit) -> BVH of that part of the hand;
        plus 'foreign' (own_palm: a digit root, world space; this hand's palm
        away from that root counts as foreign too, for fingers closing on it).
        Returns dict (None where empty)."""
        s = self.s
        c = np.array(self.centre()[:])
        out = {}
        foreign = []
        for o in self.meshes:
            co = _posed(o)
            if co is None:
                continue
            near = np.linalg.norm(co - c, axis=1) < self.radius
            if not near.any():
                continue
            dom = _dominant(o)
            own = _own_chain(dom, s)
            polys = _polys(o)
            if o == self.body:
                for p in parts:
                    if p == "palm":     # the palm with the thenar (thumb metacarpal)
                        keep = near & ((dom == f"hand_{s}") | (dom == f"thumb_01_{s}"))
                    else:
                        keep = near & np.array([d.startswith(p + "_0") and _side_of(d) == s for d in dom])
                    out[p] = _bvh(co, polys, keep)
                if own_palm is not None:
                    # the palm away from this digit's root (it always touches its own root)
                    far = np.linalg.norm(co - np.array(own_palm[:]), axis=1) > 0.024
                    foreign.append(_bvh(co, polys, near & far & (dom == f"hand_{s}")))
            foreign.append(_bvh(co, polys, near & ~own))
        out["foreign"] = [f for f in foreign if f is not None]
        return out

    def hits(self, part_bvh, others):
        if part_bvh is None:
            return 0
        return sum(len(part_bvh.overlap(f)) for f in others)


# ---------------------------------------------------------------- bone ops
def _update():
    bpy.context.view_layer.update()


def _rotate(arm, n, R, pivot=None):
    pb = arm.pose.bones[n]
    M = pb.matrix.copy()
    h = M.translation.copy() if pivot is None else Vector(pivot)
    pb.matrix = Matrix.Translation(h) @ R.to_matrix().to_4x4() @ Matrix.Translation(-h) @ M
    _update()


def move_hand(arm, s, delta):
    """Translate hand s by delta (armature space), re-solving the two-bone
    arm in its current elbow plane; the hand keeps its orientation."""
    pb = arm.pose.bones
    ua, la, hd = f"upperarm_{s}", f"lowerarm_{s}", f"hand_{s}"
    keep = pb[hd].matrix.to_3x3().normalized().to_quaternion()
    S, E, W = pb[ua].head.copy(), pb[la].head.copy(), pb[hd].head.copy()
    T = W + Vector(delta)
    l1, l2 = (E - S).length, (W - E).length
    d = T - S
    dist = min(max(d.length, 1e-4), (l1 + l2) * 0.999)
    dn = d.normalized()
    pole = (E - S) - dn * (E - S).dot(dn)
    pole = pole.normalized() if pole.length > 1e-6 else Vector((0, 0, -1))
    ca = (l1 * l1 + dist * dist - l2 * l2) / (2 * l1 * dist)
    a = np.arccos(max(-1.0, min(1.0, ca)))
    E2 = S + (dn * np.cos(a) + pole * np.sin(a)) * l1
    _rotate(arm, ua, (E - S).normalized().rotation_difference((E2 - S).normalized()))
    E_now = pb[la].head.copy()
    W_now = pb[hd].head.copy()
    _rotate(arm, la, (W_now - E_now).normalized().rotation_difference((T - E_now).normalized()))
    M = pb[hd].matrix.copy()
    pb[hd].matrix = Matrix.Translation(M.translation) @ keep.to_matrix().to_4x4()
    _update()


def _bases(arm, names):
    return {n: arm.pose.bones[n].matrix_basis.copy() for n in names if n in arm.pose.bones}


def _set_bases(arm, bases):
    for n, B in bases.items():
        arm.pose.bones[n].matrix_basis = B
    _update()


def _scaled(B, k):
    """Joint rotation in basis B scaled by k (slerp from the rest)."""
    q = B.to_quaternion()
    return Quaternion().slerp(q, k).to_matrix().to_4x4() if k <= 1.0 else \
        (q @ Quaternion().slerp(q, k - 1.0)).to_matrix().to_4x4()


def digit_bones(s, d):
    return [f"{d}_0{k}_{s}" for k in (1, 2, 3)]


def palm_normal(arm, s):
    """Unit vector out of the palm (armature space), and the finger direction."""
    pb = arm.pose.bones
    h = pb[f"hand_{s}"].head
    f = (pb[f"middle_01_{s}"].head - h).normalized()
    t = pb[f"index_01_{s}"].head - pb[f"pinky_01_{s}"].head
    t = (t - f * t.dot(f)).normalized()
    n = f.cross(t)
    th = pb[f"thumb_02_{s}"].head - h
    return (n if n.dot(th) > 0 else -n), f


def spread_digit(arm, s, d, deg):
    """Abduct digit d at its first joint about the palm normal (+ = toward
    the thumb side for index, away from the middle finger otherwise)."""
    n, _ = palm_normal(arm, s)
    b = f"{d}_01_{s}"
    pb = arm.pose.bones[b]
    # sign: rotate the digit away from the middle finger
    mid = arm.pose.bones[f"middle_01_{s}"]
    away = (pb.tail - pb.head).cross(n)
    to_mid = mid.head - pb.head
    sg = -1.0 if away.dot(to_mid) > 0 else 1.0
    _rotate(arm, b, Quaternion(n, np.radians(deg) * sg))


# ---------------------------------------------------------------- shapes
def apply_shape(arm, s, shape):
    """Set the finger bones of hand s from a HAND_SHAPES entry (deform_poses
    op lists per digit, relative to the hand)."""
    from . import deform_poses as dp
    rig = dp.Rig(arm)
    names = [b for d in DIGITS for b in digit_bones(s, d)]
    for n in names:
        if n in arm.pose.bones:
            arm.pose.bones[n].matrix_basis = Matrix.Identity(4)
    _update()
    bones = {k[:-2] + "_" + s if k.endswith("_l") else k: v for k, v in shape.items()}
    order = [n for n in dp._order(arm) if n in bones]
    for n in order:
        for op, val in bones[n]:
            pb = arm.pose.bones[n]
            ax = rig.axis(n, op)
            ax = (dp._rel(arm, rig, rig.ref(n, op)) @ ax).normalized()
            M = dp._rot_about(pb.matrix.copy(), pb.head.copy(), Matrix.Rotation(np.radians(val), 3, ax))
            dp._set(arm, n, M)


# ---------------------------------------------------------------- settle
def settle(arm, keys, rerun=None):
    """Finish the hands for the first pose name in `keys` that has an entry in
    deform_poses.POSE_HANDS. rerun(): re-applies Track F's runtime (helper
    bones follow the moved arm). Returns log lines."""
    from . import deform_poses as dp
    spec = next((dp.POSE_HANDS[k] for k in keys if k and k in dp.POSE_HANDS), None)
    if spec is None:
        return []
    log = []
    wrapped = {}
    rerun = rerun or (lambda: None)
    for s in [k for k in spec if k in ("l", "r")]:    # in the spec's order: the hand that moves first
        hs = spec.get(s)
        if hs is None:
            continue
        if hs.get("shape"):
            apply_shape(arm, s, dp.HAND_SHAPES[hs["shape"]])
            log.append(f"hand_{s}: shape {hs['shape']}")
        wrap = hs.get("wrap") or ()
        # the authored curl of the wrapping digits; they open while the palm
        # is cleared (curled fingers would drag through what they hold)
        authored = {d: _bases(arm, digit_bones(s, d)) for d in wrap}
        if wrap and hs.get("clear"):
            _set_bases(arm, {n: Matrix.Identity(4) for d in wrap for n in authored[d]})
        if hs.get("clear"):
            log.append(f"hand_{s}: " + _clear(arm, s, rerun, hs.get("clear_parts", ("palm",) + DIGITS)))
        if wrap:
            log.append(f"hand_{s}: " + _wrap(arm, s, wrap, hs.get("wrap_max", 1.25), hs.get("own_palm", False),
                                              authored))
            wrapped[s] = (hs, authored)
        if hs.get("spread", True):
            r = _spread(arm, s)
            if r:
                log.append(f"hand_{s}: {r}")
    # a hand cleared later may have moved into fingers wrapped earlier: wrap
    # those again (from open, against the final geometry)
    rerun()
    for s, (hs, authored) in wrapped.items():
        sc = Scene(arm, s)
        g = sc.build(tuple(hs["wrap"]))
        if any(sc.hits(g[d], g["foreign"]) for d in hs["wrap"]):
            log.append(f"hand_{s}: re-" + _wrap(arm, s, hs["wrap"], hs.get("wrap_max", 1.25),
                                                hs.get("own_palm", False), authored))
    r = rerun()
    if log and r:
        log.append(f"after hands: {r}")      # Track F's correctives on the final pose
    return log


def _clear(arm, s, rerun, parts):
    """Lift hand s out of foreign geometry: try a few directions (away from
    the overlap, back off the palm, along the thumb side either way, back
    along the forearm, along the fingers, forward) and keep the one that
    clears with the smallest move."""
    sc = Scene(arm, s)
    g = sc.build(("palm",))
    n0 = sc.hits(g["palm"], g["foreign"])
    if not n0:
        return "clear: no palm overlap"
    c = sc.centre()
    pts = []
    for f in g["foreign"]:
        if g["palm"].overlap(f):
            pts.append(Vector(f.find_nearest(c)[0]))
    pn, fd = palm_normal(arm, s)
    pbs = arm.pose.bones
    mw3 = arm.matrix_world.to_3x3()
    pn_w, fd_w = (mw3 @ pn).normalized(), (mw3 @ fd).normalized()
    thumb_w = pn_w.cross(fd_w)
    fore = (arm.matrix_world @ pbs[f"hand_{s}"].head - arm.matrix_world @ pbs[f"lowerarm_{s}"].head).normalized()
    fwd = (mw3 @ Vector((0.0, -1.0, 0.0))).normalized()     # the character faces -Y
    cands = {"back": -pn_w, "thumb": thumb_w, "ulnar": -thumb_w, "pull": -fore, "reach": fd_w, "forward": fwd}
    if pts:
        v = c - sum(pts, Vector()) / len(pts)
        if v.length > 1e-6:
            cands["away"] = v.normalized()
    base = _bases(arm, [f"upperarm_{s}", f"lowerarm_{s}", f"hand_{s}"])
    inv = arm.matrix_world.inverted().to_3x3()

    def ok(dloc, t):
        _set_bases(arm, base)
        move_hand(arm, s, dloc * t)
        rerun()
        sc2 = Scene(arm, s)
        gg = sc2.build(("palm",))
        return sc2.hits(gg["palm"], gg["foreign"]) == 0

    best = None
    for name, dirn in cands.items():
        dloc = (inv @ dirn).normalized()
        if not ok(dloc, LIFT_MAX_M):
            continue
        lo, hi = 0.0, LIFT_MAX_M
        for _ in range(SEARCH):
            mid = 0.5 * (lo + hi)
            if ok(dloc, mid):
                hi = mid
            else:
                lo = mid
        if best is None or hi < best[0]:
            best = (hi, name, dloc, dirn)
    _set_bases(arm, base)
    if best is None:
        rerun()
        return f"clear: palm overlap {n0} tris, not cleared within {LIFT_MAX_M * 1000:.0f} mm"
    t = best[0] + GAP_M
    move_hand(arm, s, best[2] * t)
    rerun()
    return f"clear: palm overlap {n0} tris, moved {t * 1000:.1f} mm ({best[1]})"


def _wrap(arm, s, digits, kmax, own_palm=False, authored=None, step=0.1):
    """Curl each digit (its whole curl scaled by k from the open hand) up to
    its first contact with foreign geometry: the first k (scanned in `step`s
    up to kmax, then bisected) that touches, minus a hair. A digit that never
    touches keeps its authored curl (k = 1). An open thumb that already cuts
    in is first swung round the palm normal to the nearest clear angle; then
    only its two outer joints curl."""
    out = []
    for d in digits:
        names = digit_bones(s, d)
        base = (authored or {}).get(d) or _bases(arm, names)
        fixed = {}            # bones held at a set basis (the swung thumb root)

        def setk(k):
            _set_bases(arm, {n: fixed.get(n) or _scaled(B, k) for n, B in base.items()})

        def hits(k):
            setk(k)
            sc = Scene(arm, s)
            rt = arm.matrix_world @ arm.pose.bones[names[0]].head if own_palm else None
            g = sc.build((d,), own_palm=rt)
            return sc.hits(g[d], g["foreign"])
        note = ""
        if hits(0.0) and d == "thumb":
            open_b = _bases(arm, names)
            tries = sorted(((sw, lf) for sw in (0, 8, -8, 16, -16, 24, -24, 32, -32)
                            for lf in (0, -12, 12, -24, 24, -36, 36)), key=lambda t: abs(t[0]) + abs(t[1]))
            for sw, lf in tries[1:]:
                _set_bases(arm, open_b)
                spread_digit(arm, s, "thumb", sw)
                if lf:
                    pn, _ = palm_normal(arm, s)
                    pb0 = arm.pose.bones[names[0]]
                    ax = (pb0.tail - pb0.head).normalized().cross(pn).normalized()
                    _rotate(arm, names[0], Quaternion(ax, np.radians(lf)))
                fixed = {names[0]: arm.pose.bones[names[0]].matrix_basis.copy()}
                if not hits(0.0):
                    note = f" (root swung {sw:+d}, lifted {lf:+d} deg)"
                    break
                fixed = {}
        if hits(0.0):
            _set_bases(arm, base)
            out.append(f"{d} blocked open (authored curl kept)")
            continue
        lo, hi = 0.0, None
        k = step
        while k <= kmax + 1e-6:
            if hits(k):
                hi = k
                break
            lo = k
            k += step
        if hi is None:
            if fixed:
                setk(1.0)
            else:
                _set_bases(arm, base)
            out.append(f"{d} x1 (no contact){note}")
            continue
        for _ in range(SEARCH - 2):
            mid = 0.5 * (lo + hi)
            if hits(mid):
                hi = mid
            else:
                lo = mid
        setk(lo)
        out.append(f"{d} x{lo:.2f}{note}")
    return "wrap " + ", ".join(out)


PAIRS = (("thumb", "index"), ("index", "middle"), ("middle", "ring"), ("ring", "pinky"))
MOVER = {("thumb", "index"): "thumb", ("index", "middle"): "index", ("middle", "ring"): "ring",
         ("ring", "pinky"): "pinky"}   # the digit fanned away from the middle finger


def _spread(arm, s, step=1.5, max_deg=10.0):
    fixed = []
    for a, b in PAIRS:
        moved = 0.0
        while moved < max_deg:
            sc = Scene(arm, s, radius=0.14)
            g = sc.build((a, b))
            if g[a] is None or g[b] is None or not g[a].overlap(g[b]):
                break
            spread_digit(arm, s, MOVER[(a, b)], step)
            moved += step
        if moved:
            fixed.append(f"{a}/{b} +{moved:.1f} deg")
    return ("spread " + ", ".join(fixed)) if fixed else ""


# ---------------------------------------------------------------- report
def pierce(arm):
    """Triangle overlaps per hand and digit with foreign geometry, and between
    adjacent digits, in the current pose."""
    out = {}
    for s in ("l", "r"):
        sc = Scene(arm, s)
        g = sc.build(("palm",) + DIGITS)
        r = {p: sc.hits(g[p], g["foreign"]) for p in ("palm",) + DIGITS}
        for a, b in PAIRS:
            r[f"{a}/{b}"] = len(g[a].overlap(g[b])) if g[a] is not None and g[b] is not None else 0
        out[s] = {k: v for k, v in r.items() if v}
    return out
