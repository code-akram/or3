"""The hero's pistol (m1 v2, Track H): an original fictional competition
pistol, built procedurally (no external asset, no real marks).

A compensated, striker-fired full-size race / carry gun: flat-topped slide
with steep side chamfers, rear and front cocking serrations, an optic-ready
cut with a cover plate, a ramped rear sight and a recessed front sight with a
fibre insert; a separate two-port compensator; a bronze (TiN) barrel hood in
the ejection port; a polymer frame with an undercut squared trigger guard,
an accessory rail, a beavertail, a stippled grip with a palm swell, a flared
magwell and a flared magazine base pad. Every outline here is our own
(numbers below), no real gun's silhouette, marks or trade dress.

Units: millimetres in this file (MM converts), gun space X = muzzle
direction, Y = the gun's left, Z = up; the bore axis is z = 0, the slide's
rear face x = 0.

    blender -b -t 3 --factory-startup --python-exit-code 1 \\
        --python blender/props/pistol.py -- --out DIR [--size 2048] [--orm 1024] [--samples 16]

writes DIR/pistol.glb (the game asset: the "game" detail level, 9.6k tris,
one node per moving part - slide, barrel, frame, trigger (origin on its
hinge), magazine - under a root "pistol", a "grip_socket" empty where the
web of the hand sits; one material on a 2k base colour, 2k normal and 1k
ORM atlas baked from the hero materials), DIR/pistol.blend, DIR/pistol.json
(stats) and the maps as PNG. --blend-only --detail hero|game: just the
built parts.

From Python (the hero stage poses through hero/poses.py, which does this
for a pose that holds the gun: "ready", or any pose + "+pistol"):

    from props import pistol
    gun, log = pistol.hold(arm, "r", rerun)          # hero build on hand_r: socket, aim, seat
    hand_pose.settle(arm, (), rerun, spec={"r": pistol.hand_spec("r")})
    log += pistol.finish_hold(arm, gun, "r", "l", None, rerun)   # support hand, index, thumbs
    pistol.hide()                                    # a pose without it
"""

import json
import math
import os
import sys
import time

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

MM = 0.001
GRIP_DEG = 20.0                     # grip angle from vertical (bottom toward the rear)
_GS, _GC = math.sin(math.radians(GRIP_DEG)), math.cos(math.radians(GRIP_DEG))
GD = (-_GS, -_GC)                   # down the grip axis (XZ)
GN = (_GC, -_GS)                    # forward, normal to the grip axis (XZ)
GB0 = (0.0, -30.0)                  # backstrap line at t = 0 (under the beavertail)
GRIP_DEPTH = 51.0                   # backstrap to front strap, normal to the axis
SLIDE_X = (0.0, 186.0)
COMP_X = (186.6, 214.0)
# slide cross-section (y, z): vertical sides, a steep chamfer, a narrow flat top
SLIDE_YZ = [(-11.8, -12.0), (11.8, -12.0), (11.8, 8.5), (8.4, 15.2), (6.6, 17.0),
            (-6.6, 17.0), (-8.4, 15.2), (-11.8, 8.5)]
FRAME_W = 10.6                      # frame half-width at the dust cover

QUALITY = {
    # bevel segments, cylinder sides, polygon fillet segments, grip corner points
    "hero": {"segs": 3, "cyl": 48, "fil": 6, "corner": 8, "bevel": 1.0},
    "game": {"segs": 1, "cyl": 20, "fil": 3, "corner": 4, "bevel": 1.0},
}


# ================================================================ geometry
def _fillet(pts, seg):
    """Polygon (x, z, r) -> points with each corner rounded by radius r."""
    n = len(pts)
    out = []
    for i in range(n):
        x, z, r = pts[i]
        b = np.array((x, z), float)
        if r <= 0:
            out.append(tuple(b))
            continue
        a = np.array(pts[i - 1][:2], float)
        c = np.array(pts[(i + 1) % n][:2], float)
        u, v = a - b, c - b
        lu, lv = np.linalg.norm(u), np.linalg.norm(v)
        u, v = u / lu, v / lv
        ang = math.acos(max(-1.0, min(1.0, float(u @ v))))
        if ang < 1e-3 or ang > math.pi - 1e-3:
            out.append(tuple(b))
            continue
        t = r / math.tan(ang / 2)
        t = min(t, 0.48 * lu, 0.48 * lv)
        re = t * math.tan(ang / 2)
        p1, p2 = b + u * t, b + v * t
        bis = (u + v) / np.linalg.norm(u + v)
        cen = b + bis * re / math.sin(ang / 2)
        a1 = math.atan2(*(p1 - cen)[::-1])
        a2 = math.atan2(*(p2 - cen)[::-1])
        da = (a2 - a1 + math.pi) % (2 * math.pi) - math.pi
        for k in range(seg + 1):
            th = a1 + da * k / seg
            out.append((cen[0] + re * math.cos(th), cen[1] + re * math.sin(th)))
    return out


def _obj(name, bm, col):
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    col.objects.link(ob)
    return ob


def _prism(name, poly2, a0, a1, col, axis):
    """Extrude a closed 2D polygon. axis 'y': poly in (x, z), extruded y a0..a1;
    axis 'x': poly in (y, z), extruded x a0..a1. mm in, metres out."""
    bm = bmesh.new()

    def P(p, a):
        return (a * MM, p[0] * MM, p[1] * MM) if axis == "x" else (p[0] * MM, a * MM, p[1] * MM)
    v0 = [bm.verts.new(P(p, a0)) for p in poly2]
    v1 = [bm.verts.new(P(p, a1)) for p in poly2]
    n = len(poly2)
    bm.faces.new(v0)
    bm.faces.new(list(reversed(v1)))
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((v0[i], v0[j], v1[j], v1[i]))
    return _obj(name, bm, col)


def prism_xz(name, poly, y0, y1, col, seg=4):
    return _prism(name, _fillet(poly, seg), y0, y1, col, "y")


def prism_yz(name, poly, x0, x1, col, seg=4):
    if len(poly[0]) == 3:
        poly = _fillet(poly, seg)
    return _prism(name, poly, x0, x1, col, "x")


def box(col, x0, x1, y0, y1, z0, z1, rot_y=0.0, name="cut"):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    c = Vector(((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)) * MM
    M = (Matrix.Translation(c) @ Matrix.Rotation(math.radians(rot_y), 4, "Y")
         @ Matrix.Diagonal(((x1 - x0) * MM, (y1 - y0) * MM, (z1 - z0) * MM, 1.0)))
    bmesh.ops.transform(bm, matrix=M, verts=bm.verts)
    return _obj(name, bm, col)


def cyl(col, a0, a1, r, axis="x", c=(0.0, 0.0), n=32, r1=None, name="cyl"):
    """Cylinder (or cone r -> r1) along axis x (centre (y, z)), y (centre (x, z)) or z (centre (x, y))."""
    bm = bmesh.new()
    r1 = r if r1 is None else r1
    ring0, ring1 = [], []
    for k in range(n):
        th = 2 * math.pi * k / n
        cs, sn = math.cos(th), math.sin(th)
        if axis == "x":
            ring0.append(bm.verts.new((a0 * MM, (c[0] + r * cs) * MM, (c[1] + r * sn) * MM)))
            ring1.append(bm.verts.new((a1 * MM, (c[0] + r1 * cs) * MM, (c[1] + r1 * sn) * MM)))
        elif axis == "y":
            ring0.append(bm.verts.new(((c[0] + r * cs) * MM, a0 * MM, (c[1] + r * sn) * MM)))
            ring1.append(bm.verts.new(((c[0] + r1 * cs) * MM, a1 * MM, (c[1] + r1 * sn) * MM)))
        else:
            ring0.append(bm.verts.new(((c[0] + r * cs) * MM, (c[1] + r * sn) * MM, a0 * MM)))
            ring1.append(bm.verts.new(((c[0] + r1 * cs) * MM, (c[1] + r1 * sn) * MM, a1 * MM)))
    bm.faces.new(ring0)
    bm.faces.new(list(reversed(ring1)))
    for k in range(n):
        j = (k + 1) % n
        bm.faces.new((ring0[k], ring0[j], ring1[j], ring1[k]))
    return _obj(name, bm, col)


def hull(col, pts, name="hull"):
    bm = bmesh.new()
    vs = [bm.verts.new(Vector(p) * MM) for p in pts]
    bmesh.ops.convex_hull(bm, input=vs)
    return _obj(name, bm, col)


def loft(name, rings, col, cap0=True, cap1=True):
    """Rings (lists of mm points, same count) -> a closed tube."""
    bm = bmesh.new()
    vr = [[bm.verts.new(Vector(p) * MM) for p in ring] for ring in rings]
    n = len(rings[0])
    for a, b in zip(vr[:-1], vr[1:]):
        for k in range(n):
            j = (k + 1) % n
            bm.faces.new((a[k], a[j], b[j], b[k]))
    if cap0:
        bm.faces.new(list(reversed(vr[0])))
    if cap1:
        bm.faces.new(vr[-1])
    return _obj(name, bm, col)


def _apply(ob):
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
    old = ob.data
    ob.modifiers.clear()
    ob.data = me
    me.name = ob.name
    bpy.data.meshes.remove(old)


def boolean(ob, cutters, op="DIFFERENCE"):
    if not cutters:
        return ob
    col = bpy.data.collections.new("_cutters")
    bpy.context.scene.collection.children.link(col)
    for c in cutters:
        for uc in list(c.users_collection):
            uc.objects.unlink(c)
        col.objects.link(c)
        c.hide_render = True
    m = ob.modifiers.new("cut", "BOOLEAN")
    m.operation = op
    m.operand_type = "COLLECTION"
    m.collection = col
    m.solver = "EXACT"
    _apply(ob)
    for c in cutters:
        me = c.data
        bpy.data.objects.remove(c, do_unlink=True)
        bpy.data.meshes.remove(me)
    bpy.data.collections.remove(col)
    return ob


def finish(ob, width, q, angle=30.0, segs=None, smooth=True):
    """Clean up, bevel the hard edges (width mm), harden + weight the normals."""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bmesh.ops.dissolve_limit(bm, angle_limit=math.radians(0.2), verts=bm.verts, edges=bm.edges)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    bm.to_mesh(ob.data)
    bm.free()
    if smooth:
        ob.data.shade_smooth()
    if width > 0:
        b = ob.modifiers.new("bevel", "BEVEL")
        b.width = width * MM * q["bevel"]
        b.segments = segs or q["segs"]
        b.limit_method = "ANGLE"
        b.angle_limit = math.radians(angle)
        b.harden_normals = True
        b.miter_outer = "MITER_ARC"
        b.use_clamp_overlap = True
        b.profile = 0.5
    w = ob.modifiers.new("wn", "WEIGHTED_NORMAL")
    w.keep_sharp = True
    w.mode = "FACE_AREA"
    w.weight = 50
    _apply(ob)
    return ob


def _mat(ob, mat):
    ob.data.materials.clear()
    ob.data.materials.append(mat)
    return ob


# ---------------------------------------------------------------- the grip
def _rrect(u0, u1, w, rb, rf, nc):
    """Rounded rectangle in (u forward, v left): back radius rb, front rf;
    a fixed point count (4 corners x (nc + 1) + 4 straight runs x 2)."""
    rb = min(rb, w * 0.999, (u1 - u0) * 0.49)
    rf = min(rf, w * 0.999, (u1 - u0) * 0.49)
    out = []

    def arc(cu, cv, r, a0, a1):
        for k in range(nc + 1):
            th = math.radians(a0 + (a1 - a0) * k / nc)
            out.append((cu + r * math.cos(th), cv + r * math.sin(th)))

    def run(p, q_):
        for k in (1, 2):
            f = k / 3
            out.append((p[0] + (q_[0] - p[0]) * f, p[1] + (q_[1] - p[1]) * f))
    arc(u0 + rb, w - rb, rb, 180, 90)
    run((u0 + rb, w), (u1 - rf, w))
    arc(u1 - rf, w - rf, rf, 90, 0)
    run((u1, w - rf), (u1, -(w - rf)))
    arc(u1 - rf, -(w - rf), rf, 0, -90)
    run((u1 - rf, -w), (u0 + rb, -w))
    arc(u0 + rb, -(w - rb), rb, -90, -180)
    run((u0, -(w - rb)), (u0, w - rb))
    return out


def grip_point(t, u, v=0.0):
    """Gun-space mm point at grip station t (along the axis, down), u forward
    of the backstrap line, v to the left."""
    return (GB0[0] + t * GD[0] + u * GN[0], v, GB0[1] + t * GD[1] + u * GN[1])


def _ring(t, u0, u1, w, rb, rf, nc):
    return [grip_point(t, u, v) for u, v in _rrect(u0, u1, w, rb, rf, nc)]


def _smooth(e0, e1, x):
    x = min(max((x - e0) / (e1 - e0), 0.0), 1.0)
    return x * x * (3 - 2 * x)


def grip_w(t):
    """Grip half-width: a hair over the frame's width at the top (so the
    grip surface covers the frame side flush), flaring to the hand."""
    return 10.72 + 4.78 * _smooth(-2.0, 16.0, t) + 0.35 * math.sin(math.pi * min(max((t - 10) / 44, 0), 1))


def grip_swell(t):
    """Palm swell: the backstrap bulges back (mm)."""
    return 1.8 * math.sin(math.pi * min(max((t - 4.0) / 52.0, 0.0), 1.0))


STIPPLE_T = (3.0, 55.0)
# the receiver behind the trigger, under the slide: horizontal rings (z, back
# x, front x (hidden in the frame), back and front corner radii)
GRIP_TOP = [(-13.2, -1.0, 97.0, 5.0, 2.0), (-17.0, -1.2, 97.0, 6.0, 2.0), (-21.0, -1.4, 97.0, 7.0, 2.0),
            (-25.0, -1.6, 97.0, 8.0, 2.0), (-28.6, -1.5, 97.0, 9.0, 2.0), (-30.0, -1.4, 96.6, 9.0, 1.4)]
# then stations down the backstrap line: (t, how far the ring has turned from
# horizontal to normal-to-the-axis)
GRIP_T = [(2, 0.3), (5, 0.6), (8, 0.85), (11, 1), (14, 1), (17, 1), (21, 1), (25, 1), (29, 1), (33, 1), (37, 1),
          (41, 1), (45, 1), (49, 1), (53, 1), (56, 1), (59, 1), (61, 1)]


def _front_strap(b, u):
    """Distance along u from point b (XZ) to the front strap line."""
    f0 = np.array(GB0) + GRIP_DEPTH * np.array(GN)
    A = np.array([[u[0], -GD[0]], [u[1], -GD[1]]])
    s, _ = np.linalg.solve(A, f0 - np.array(b))
    return float(s)


def grip_rings(q):
    nc = q["corner"]
    rings = []
    for z, xb, xf, rb, rf in GRIP_TOP:
        rings.append([(xb + u, v, z) for u, v in _rrect(0.0, xf - xb, grip_w(-15.0), rb, rf, nc)])
    for t, f in GRIP_T:
        u = np.array((1.0, 0.0)) * (1 - f) + np.array(GN) * f
        u /= np.linalg.norm(u)
        b = np.array(GB0) + t * np.array(GD)
        D = _front_strap(b, u)
        k = min(1.0, max(0.0, (t - 2.0) / 9.0))
        rb, rf = 9.0 + 3.0 * k, 5.0 + 4.5 * k
        pts = _rrect(-grip_swell(t), D, grip_w(t), rb, rf, nc)
        rings.append([(b[0] + a * u[0], v, b[1] + a * u[1]) for a, v in pts])
    return rings


def build_grip(col, q):
    ob = loft("grip", grip_rings(q), col)
    # stipple panel: the faces between the stations inside STIPPLE_T, all round
    me = ob.data
    att = me.attributes.new("stipple", "FLOAT", "FACE")
    vals = []
    co = np.array([v.co for v in me.vertices]) / MM
    for p in me.polygons:
        c = co[list(p.vertices)].mean(0)
        t = (c[0] - GB0[0]) * GD[0] + (c[2] - GB0[1]) * GD[1]
        vals.append(1.0 if STIPPLE_T[0] <= t <= STIPPLE_T[1] and len(p.vertices) == 4 else 0.0)
    att.data.foreach_set("value", vals)
    me.shade_smooth()
    return ob


# beavertail: (x, top z, bottom z, half-width) sections, a rounded tongue over the web
BEAVERTAIL = [(1.0, -12.6, -33.0, 10.45), (-2.0, -12.6, -30.6, 10.4), (-4.5, -12.75, -28.8, 10.3),
              (-7.0, -13.1, -27.2, 10.15), (-9.5, -13.7, -25.9, 9.95), (-11.6, -14.5, -24.8, 9.7),
              (-13.2, -15.4, -23.8, 9.35), (-14.3, -16.3, -22.9, 8.9), (-14.9, -17.2, -22.0, 8.2),
              (-15.2, -18.0, -21.1, 7.0)]


def build_beavertail(col, q):
    rings = []
    for x, top, bot, w in BEAVERTAIL:
        rb = min(w, (top - bot) / 2) * 0.95
        rings.append([(x, v, u) for u, v in _rrect(bot, top, w, rb, min(2.0, rb), q["corner"])])
    ob = loft("beavertail", rings, col)
    ob.data.shade_smooth()
    return ob


def build_magwell(col, q):
    D = GRIP_DEPTH
    rings = []
    for t in (56.0, 59.0, 62.0, 65.0, 67.5, 69.5):
        f = ((t - 56.0) / 13.5) ** 1.6
        rings.append(_ring(t, -0.6 - 1.8 * f, D + 0.9 + 5.2 * f, 15.75 + 2.2 * f, 11.5, 9.5, q["corner"]))
    f = 1.0
    u0, u1, w = -0.6 - 1.8 * f, D + 0.9 + 5.2 * f, 15.75 + 2.2 * f
    rings.append(_ring(69.5, u0 + 1.6, u1 - 1.6, w - 1.6, 10.0, 8.0, q["corner"]))     # the mouth lip
    rings.append(_ring(67.0, u0 + 3.2, u1 - 3.0, w - 3.4, 8.5, 6.5, q["corner"]))      # funnel in
    rings.append(_ring(64.0, 1.2, D - 1.4, 12.2, 7.0, 5.5, q["corner"]))
    ob = loft("magwell", rings, col)
    ob.data.shade_smooth()
    return ob


def build_basepad(col, q):
    D = GRIP_DEPTH
    rings = [
        _ring(69.8, 1.0, D - 2.0, 12.0, 7.0, 5.5, q["corner"]),        # the magazine body, in the mouth
        _ring(70.4, 1.0, D - 2.0, 12.0, 7.0, 5.5, q["corner"]),
        _ring(70.6, -0.4, D + 2.6, 14.6, 10.0, 8.0, q["corner"]),
        _ring(71.2, -1.0, D + 3.4, 15.3, 10.5, 8.5, q["corner"]),
        _ring(74.5, -1.7, D + 6.0, 16.0, 11.0, 9.0, q["corner"]),
        _ring(76.9, -2.1, D + 7.4, 16.4, 11.2, 9.5, q["corner"]),
        _ring(77.6, -1.5, D + 6.6, 15.7, 10.5, 8.8, q["corner"]),
    ]
    ob = loft("basepad", rings, col)
    ob.data.shade_smooth()
    return ob


# ---------------------------------------------------------------- parts
def _nose(col, x0, x1, dz, dy, side):
    """Wedge cutter that tapers the lower front corner of a slide-section part."""
    s = 1.0 if side > 0 else -1.0
    p1 = (x0, 11.8 * s, -12.0)
    p2 = (x1, 11.8 * s, -12.0 + dz)
    p3 = (x1, (11.8 - dy) * s, -12.0)
    o = (0.0, 6.0 * s, -6.0)
    ext = [(p[0] + 4.0, p[1], p[2]) for p in (p2, p3)]
    pts = [p1, p2, p3] + ext + [tuple(a + b for a, b in zip(p, o)) for p in [p1, p2, p3] + ext]
    pts += [(x0 - 0.5, 11.8 * s + o[1], -12.0 + o[2])]
    return hull(col, pts, "nose")


def _serrations(col, xs, width, depth, lean, z0=-9.0, z1=16.0):
    out = []
    for x in xs:
        for s in (1, -1):
            y0, y1 = (11.8 - depth, 20.0) if s > 0 else (-20.0, -11.8 + depth)
            out.append(box(col, x - width / 2, x + width / 2, y0, y1, z0, z1, rot_y=lean, name="serr"))
    return out


def build_slide(col, q):
    sl = prism_yz("slide", SLIDE_YZ, *SLIDE_X, col)
    cut = [_nose(col, 156.0, 186.0, 8.0, 3.0, s) for s in (1, -1)]
    cut += [_corner(col, SLIDE_X[1], 17.0, 1.6), _corner(col, SLIDE_X[0], 17.0, 1.2)]
    # rear cocking serrations (8, leaning forward) and front serrations (6)
    cut += _serrations(col, [12.0 + 4.6 * k for k in range(8)], 1.9, 1.15, -12.0)
    cut += _serrations(col, [128.0 + 4.6 * k for k in range(6)], 1.9, 1.15, -12.0)
    # ejection port: right side (-y), over the top to just past the centre line
    cut.append(box(col, 70.0, 111.0, -30.0, 1.0, 3.0, 30.0, name="port"))
    # optic cut: a flat pocket across the top, 3.4 mm down
    cut.append(box(col, 18.0, 60.0, -30.0, 30.0, 13.6, 30.0, name="optic"))
    # front sight trench (the blade sits in it, below the side walls)
    cut.append(box(col, 165.5, 184.0, -3.3, 3.3, 15.0, 30.0, name="trench"))
    # barrel exit in the slide nose
    cut.append(cyl(col, 175.0, 190.0, 6.95, n=q["cyl"]))
    # striker cover plate recess (rear face) and extractor channel (right side)
    cut.append(box(col, -2.0, 0.3, -7.3, 7.3, -9.6, 9.6, name="plate_recess"))
    cut.append(box(col, 49.6, 66.4, -14.0, -11.45, 2.8, 7.2, name="extractor_slot"))
    boolean(sl, cut)
    return finish(sl, 0.45, q)


COMP_YZ = [(-11.3, -11.6), (11.3, -11.6), (11.3, 8.4), (8.1, 15.0), (6.4, 16.6),
           (-6.4, 16.6), (-8.1, 15.0), (-11.3, 8.4)]


def _corner(col, x, z, leg, lean=45.0):
    """Cutter that chamfers the edge along y at (x, z) with legs `leg`."""
    a = leg * math.sqrt(2.0)
    return box(col, x - a / 2, x + a / 2, -30.0, 30.0, z - a / 2, z + a / 2, rot_y=lean, name="chamfer")


def build_comp(col, q):
    cp = prism_yz("comp", COMP_YZ, *COMP_X, col)
    cut = [_nose(col, 196.0, 214.0, 5.5, 2.2, s) for s in (1, -1)]
    cut.append(_corner(col, COMP_X[1], 16.6, 3.6))                     # top-front chamfer
    for s in (1, -1):                                                   # machined side slots
        y0, y1 = (10.2, 20.0) if s > 0 else (-20.0, -10.2)
        cut.append(prism_xz("slot", [(190.8, -5.6, 3.2), (207.0, -5.6, 3.2), (207.0, 1.6, 3.2), (190.8, 3.6, 3.2)],
                            y0, y1, col, q["fil"]))
    cut.append(cyl(col, 184.0, 191.0, 6.95, n=q["cyl"]))                 # barrel in
    cut.append(cyl(col, 190.4, 207.5, 7.4, n=q["cyl"]))                  # expansion chamber
    cut.append(cyl(col, 207.0, 216.0, 5.1, n=q["cyl"]))                  # exit
    cut.append(cyl(col, 212.6, 214.6, 5.1, n=q["cyl"], r1=6.2))          # exit chamfer
    cut.append(box(col, 188.8, 195.6, -4.5, 4.5, 2.0, 30.0, name="port1"))
    cut.append(box(col, 199.6, 205.4, -3.9, 3.9, 2.0, 30.0, name="port2"))
    boolean(cp, cut)
    return finish(cp, 0.45, q)


def build_barrel(col, q):
    b = cyl(col, 64.0, 190.5, 6.75, n=q["cyl"], name="barrel")
    hood = box(col, 64.0, 112.0, -6.85, 6.85, -1.0, 16.35, name="hood")
    boolean(b, [hood], "UNION")
    cut = [cyl(col, 100.0, 192.0, 4.55, n=q["cyl"]),
           cyl(col, 189.4, 190.6, 4.55, n=q["cyl"], r1=5.7)]          # recessed crown chamfer
    boolean(b, cut)
    return finish(b, 0.3, q)


FRAME_XZ = [
    (0.5, -12.6, 0), (183.0, -12.6, 0), (184.6, -14.5, 1.0), (184.6, -23.8, 1.2), (182.0, -26.6, 0),
    (99.0, -26.6, 0), (97.5, -30.4, 1.5), (58.0, -30.4, 3.0),
    (52.0, -33.2, 0), (30.0, -34.0, 0), (2.0, -30.0, 0),                # inside the grip
]
GUARD_OUT = [(56.0, -27.5, 0), (99.5, -27.5, 0), (99.8, -30.5, 0), (102.0, -50.8, 5.0), (98.5, -56.6, 4.0),
             (52.0, -56.6, 5.0), (44.0, -52.0, 0), (45.6, -40.0, 0)]
GUARD_IN = [(94.2, -30.1, 1.5), (95.6, -50.0, 3.4), (56.5, -51.4, 4.0), (44.0, -49.6, 0), (52.0, -30.1, 0)]
RAIL_YZ = [(-8.2, -26.0), (8.2, -26.0), (8.2, -27.4), (9.7, -28.5), (9.7, -29.5), (8.0, -31.3),
           (-8.0, -31.3), (-9.7, -29.5), (-9.7, -28.5), (-8.2, -27.4)]
TRIGGER_XZ = [(61.0, -29.8, 0), (65.8, -29.8, 0), (67.8, -38.0, 8.0), (67.4, -46.5, 2.5), (65.6, -49.8, 1.2),
              (62.8, -49.4, 1.0), (61.8, -44.0, 5.0), (60.6, -36.0, 0)]
SAFETY_XZ = [(66.2, -39.4, 0), (68.5, -40.8, 0.6), (68.2, -46.6, 0.6), (66.2, -47.8, 0)]
SLIDESTOP_XZ = [(64.0, -14.6, 1.2), (96.0, -14.6, 0), (100.6, -18.5, 2.5), (96.0, -22.0, 0),
                (80.0, -20.0, 0), (70.0, -20.6, 1.0), (64.0, -18.6, 1.2)]
REAR_SIGHT_XZ = [(3.0, 16.0, 0), (3.0, 23.5, 0.4), (11.0, 23.5, 1.5), (16.8, 16.0, 0)]
FRONT_SIGHT_XZ = [(167.5, 14.6, 0), (169.2, 23.0, 0.4), (180.8, 23.0, 0.6), (182.6, 14.6, 0)]
PLATE_YZ = [(-9.0, 13.6), (9.0, 13.6), (8.25, 15.3), (7.15, 16.2), (-7.15, 16.2), (-8.25, 15.3)]


def build_frame(col, q):
    fr = prism_xz("frame", FRAME_XZ, -FRAME_W, FRAME_W, col, q["fil"])
    finish(fr, 0.8, q)
    g = prism_xz("guard", GUARD_OUT, -5.4, 5.4, col, q["fil"])
    boolean(g, [prism_xz("hole", GUARD_IN, -8.0, 8.0, col, q["fil"])])
    finish(g, 1.9, q, segs=q["segs"] + 1)
    rail = prism_yz("rail", RAIL_YZ, 110.0, 182.0, col)
    boolean(rail, [box(col, c - 1.6, c + 1.6, -12.0, 12.0, -32.0, -29.0) for c in (122.0, 134.0, 146.0, 158.0, 170.0)])
    finish(rail, 0.35, q)
    inner = box(col, -1.0, 181.0, -8.6, 8.6, -12.9, -8.0, name="frame_rails")
    return [fr, g, rail, inner]


def build_controls(col, q):
    tr = prism_xz("trigger", TRIGGER_XZ, -3.4, 3.4, col, q["fil"])
    boolean(tr, [box(col, 65.8, 70.0, -0.95, 0.95, -48.4, -38.8)])
    finish(tr, 0.5, q)
    sf = finish(prism_xz("safety", SAFETY_XZ, -0.75, 0.75, col, q["fil"]), 0.25, q)
    ss = finish(prism_xz("slide_stop", SLIDESTOP_XZ, 9.8, 12.1, col, q["fil"]), 0.5, q)
    td = finish(box(col, 85.0, 93.0, -11.3, 11.3, -25.8, -23.2, name="takedown"), 0.5, q)
    mr = finish(box(col, 43.6, 51.4, 6.0, 12.0, -40.8, -34.6, name="mag_release"), 1.0, q)
    pins = [finish(cyl(col, -11.05, 11.05, 1.55, axis="y", c=c, n=max(12, q["cyl"] // 3), name="pin"), 0.2, q)
            for c in ((58.0, -22.5), (76.0, -24.2))]
    return [tr, sf, ss, td, mr] + pins


def build_slide_parts(col, q):
    rs = prism_xz("rear_sight", REAR_SIGHT_XZ, -7.6, 7.6, col, q["fil"])
    cut = [box(col, 0.0, 20.0, -1.75, 1.75, 21.2, 30.0)]
    cut += [box(col, 2.0, 3.45, -10.0, 10.0, z - 0.25, z + 0.25) for z in (17.6, 18.7, 19.8, 20.9)]
    boolean(rs, cut)
    finish(rs, 0.35, q)
    fs = prism_xz("front_sight", FRONT_SIGHT_XZ, -1.55, 1.55, col, q["fil"])
    boolean(fs, [box(col, 170.4, 179.6, -0.6, 0.6, 21.4, 30.0)])
    finish(fs, 0.3, q)
    fib = finish(cyl(col, 170.0, 180.0, 0.82, c=(0.0, 21.6), n=max(12, q["cyl"] // 3), name="fibre"), 0.0, q)
    plate = finish(prism_yz("optic_plate", PLATE_YZ, 18.6, 59.4, col), 0.3, q)
    screws = []
    for x in (25.0, 53.0):
        s = cyl(col, 15.4, 16.45, 1.75, axis="z", c=(x, 0.0), n=max(16, q["cyl"] // 2), name="screw")
        hx = cyl(col, 15.75, 17.0, 0.75, axis="z", c=(x, 0.0), n=6)
        boolean(s, [hx])
        screws.append(finish(s, 0.15, q))
    ex = finish(box(col, 50.0, 66.0, -12.1, -11.0, 3.2, 6.8, name="extractor"), 0.3, q)
    pl = finish(box(col, 0.05, 1.0, -6.95, 6.95, -9.25, 9.25, name="striker_plate"), 0.2, q)
    return {"rear_sight": rs, "front_sight": fs, "fibre": fib, "optic_plate": plate, "screws": screws,
            "extractor": ex, "striker_plate": pl}


def build(detail="hero", col=None, mats=None):
    """Build every part (modifiers applied). Returns {group: [objects]}:
    slide (moves), barrel (barrel + compensator), frame, trigger, magazine."""
    q = QUALITY[detail]
    col = col or bpy.data.collections.new(f"pistol_{detail}")
    if col.name not in bpy.context.scene.collection.children:
        bpy.context.scene.collection.children.link(col)
    mats = mats or materials()
    sp = build_slide_parts(col, q)
    slide = [_mat(build_slide(col, q), mats["nitride"]), _mat(sp["rear_sight"], mats["steel"]),
             _mat(sp["front_sight"], mats["steel"]), _mat(sp["fibre"], mats["fibre"]),
             _mat(sp["optic_plate"], mats["nitride"]), _mat(sp["extractor"], mats["steel"]),
             _mat(sp["striker_plate"], mats["steel"])] + [_mat(s, mats["steel"]) for s in sp["screws"]]
    barrel = [_mat(build_barrel(col, q), mats["bronze"]), _mat(build_comp(col, q), mats["nitride"])]
    fr = build_frame(col, q)
    frame = [_mat(o, mats["polymer"]) for o in fr]
    grip = _mat(build_grip(col, q), mats["polymer"])
    ctl = build_controls(col, q)
    frame += [grip, _mat(build_beavertail(col, q), mats["polymer"]), _mat(build_magwell(col, q), mats["anodised"])] + [_mat(o, mats["steel"]) for o in ctl[2:]]
    trigger = [_mat(ctl[0], mats["steel"]), _mat(ctl[1], mats["steel"])]
    magazine = [_mat(build_basepad(col, q), mats["anodised"])]
    for o in col.objects:
        if "stipple" not in o.data.attributes:
            o.data.attributes.new("stipple", "FLOAT", "FACE")
    return {"slide": slide, "barrel": barrel, "frame": frame, "trigger": trigger, "magazine": magazine}


def join(objs, name):
    objs = [o for o in objs]
    with bpy.context.temp_override(active_object=objs[0], selected_editable_objects=objs,
                                   selected_objects=objs):
        bpy.ops.object.join()
    ob = objs[0]
    ob.name = name
    ob.data.name = name
    return ob


def tris(objs):
    return sum(sum(len(p.vertices) - 2 for p in o.data.polygons) for o in objs)


# ================================================================ materials
class _NB:
    """Tiny node-tree builder."""

    def __init__(self, mat):
        mat.use_nodes = True
        self.nt = mat.node_tree
        self.nt.nodes.clear()
        self.x = 0

    def n(self, kind, **inputs):
        node = self.nt.nodes.new(kind)
        node.location = (self.x, 0)
        self.x += 160
        for k, v in inputs.items():
            if hasattr(node, k) and k not in node.inputs:
                setattr(node, k, v)
            else:
                self.set(node.inputs[k], v)
        return node

    def set(self, sock, v):
        if hasattr(v, "is_output") or hasattr(v, "links"):
            self.nt.links.new(v, sock)
        else:
            sock.default_value = v

    def math(self, op, a, b=None, c=None, clamp=False):
        m = self.n("ShaderNodeMath", operation=op, use_clamp=clamp)
        self.set(m.inputs[0], a)
        if b is not None:
            self.set(m.inputs[1], b)
        if c is not None:
            self.set(m.inputs[2], c)
        return m.outputs[0]

    def smooth(self, e0, e1, x):
        m = self.n("ShaderNodeMapRange", interpolation_type="SMOOTHSTEP")
        self.set(m.inputs["Value"], x)
        m.inputs["From Min"].default_value = e0
        m.inputs["From Max"].default_value = e1
        return m.outputs["Result"]

    def mix(self, f, a, b, kind="FLOAT"):
        m = self.n("ShaderNodeMix", data_type=kind)
        if kind == "RGBA":
            self.set(m.inputs[0], f)
            self.set(m.inputs[6], a)
            self.set(m.inputs[7], b)
            return m.outputs[2]
        self.set(m.inputs[0], f)
        self.set(m.inputs[2], a)
        self.set(m.inputs[3], b)
        return m.outputs[0]

    def vec(self, op, a, b=None, scale=None):
        m = self.n("ShaderNodeVectorMath", operation=op)
        self.set(m.inputs[0], a)
        if b is not None:
            self.set(m.inputs[1], b)
        if scale is not None:
            m.inputs["Scale"].default_value = scale
        return m.outputs[1] if op in ("DOT_PRODUCT", "LENGTH", "DISTANCE") else m.outputs[0]


def _coords(nb):
    """Gun-space position in mm (object coordinates)."""
    tc = nb.n("ShaderNodeTexCoord")
    return nb.vec("SCALE", tc.outputs["Object"], scale=1000.0)


def _noise(nb, P, scale, detail=4.0, rough=0.6, stretch=None):
    if stretch is not None:
        P = nb.vec("MULTIPLY", P, stretch)
    t = nb.n("ShaderNodeTexNoise", Scale=scale, Detail=detail, Roughness=rough)
    nb.set(t.inputs["Vector"], P)
    return t.outputs["Fac"]


def _edge_wear(nb, P, radius_mm=0.7, amount=1.0, grain=0.35):
    """Convex-edge mask: the bevel shader's rounded normal against the true
    normal (edges), times local AO (concave corners and grooves excluded),
    broken up by noise."""
    bev = nb.n("ShaderNodeBevel", samples=8, Radius=radius_mm * MM)
    geo = nb.n("ShaderNodeNewGeometry")
    d = nb.vec("DOT_PRODUCT", bev.outputs[0], geo.outputs["Normal"])
    edge = nb.smooth(0.995, 0.93, d)
    ao = nb.n("ShaderNodeAmbientOcclusion", samples=8, only_local=True, Distance=0.004)
    convex = nb.smooth(0.82, 0.97, ao.outputs["AO"])
    nz = _noise(nb, P, 0.9, detail=8.0, rough=0.7)
    brk = nb.smooth(0.42 - grain * 0.3, 0.58, nz)
    w = nb.math("MULTIPLY", nb.math("MULTIPLY", edge, convex), brk)
    return nb.math("MULTIPLY", w, amount, clamp=True), convex


def _principled(nb, **kw):
    p = nb.n("ShaderNodeBsdfPrincipled")
    for k, v in kw.items():
        nb.set(p.inputs[k], v)
    out = nb.n("ShaderNodeOutputMaterial")
    nb.nt.links.new(p.outputs[0], out.inputs["Surface"])
    return p


def _rgb(nb, c):
    n = nb.n("ShaderNodeRGB")
    n.outputs[0].default_value = (*c, 1.0)
    return n.outputs[0]


def mat_metal(name, base, worn, rough, worn_rough, wear=1.0, streak=0.05, bump=0.0):
    """Black nitride / oxide / anodised metal: satin, machining streaks along
    the bore axis in the roughness, bright worn steel on the convex edges."""
    m = bpy.data.materials.new(name)
    nb = _NB(m)
    P = _coords(nb)
    w, convex = _edge_wear(nb, P, amount=wear)
    st = _noise(nb, P, 0.35, detail=6.0, rough=0.55, stretch=(0.04, 1.0, 1.0))
    fine = _noise(nb, P, 2.2, detail=3.0)
    r0 = nb.math("ADD", rough - streak, nb.math("MULTIPLY", nb.math("ADD", st, nb.math("MULTIPLY", fine, 0.5)), streak * 1.4))
    # cavities collect a little grime: rougher, a touch lighter
    cav = nb.math("SUBTRACT", 1.0, convex)
    r0 = nb.math("ADD", r0, nb.math("MULTIPLY", cav, 0.12))
    col = nb.mix(w, _rgb(nb, base), _rgb(nb, worn), "RGBA")
    kw = dict(**{"Base Color": col, "Metallic": 1.0, "Roughness": nb.mix(w, r0, worn_rough)})
    p = _principled(nb, **kw)
    if bump:
        b = nb.n("ShaderNodeBump", Strength=0.25, Distance=bump * MM)
        nb.set(b.inputs["Height"], fine)
        nb.set(p.inputs["Normal"], b.outputs["Normal"])
    return m


def _stipple_height(nb, P):
    """Hand stippling: overlapping round pits ~1.1 mm with raised rims, a
    second finer octave, a little noise."""
    v1 = nb.n("ShaderNodeTexVoronoi", feature="F1", distance="EUCLIDEAN")
    v1.inputs["Scale"].default_value = 0.95
    v1.inputs["Randomness"].default_value = 1.0
    nb.set(v1.inputs["Vector"], P)
    v2 = nb.n("ShaderNodeTexVoronoi", feature="F1", distance="EUCLIDEAN")
    v2.inputs["Scale"].default_value = 2.1
    v2.inputs["Randomness"].default_value = 1.0
    nb.set(v2.inputs["Vector"], nb.vec("ADD", P, (3.7, 1.3, 5.1)))
    h1 = nb.smooth(0.05, 0.62, v1.outputs["Distance"])
    rim = nb.math("MULTIPLY", nb.smooth(0.45, 0.7, v1.outputs["Distance"]), -0.35)
    h2 = nb.math("MULTIPLY", nb.smooth(0.05, 0.6, v2.outputs["Distance"]), 0.45)
    nz = nb.math("MULTIPLY", _noise(nb, P, 3.0, detail=2.0), 0.25)
    return nb.math("ADD", nb.math("ADD", h1, rim), nb.math("ADD", h2, nz))


def mat_polymer(name="polymer"):
    """Glass-filled polymer frame: near-black, satin-matte moulded texture;
    stippled grip panels (face attribute 'stipple') much rougher
    with a pit-and-rim normal; worn edges a touch lighter and smoother."""
    m = bpy.data.materials.new(name)
    nb = _NB(m)
    P = _coords(nb)
    w, convex = _edge_wear(nb, P, radius_mm=0.9, amount=0.55, grain=0.2)
    att = nb.n("ShaderNodeAttribute", attribute_name="stipple", attribute_type="GEOMETRY")
    mask = att.outputs["Fac"]
    h = _stipple_height(nb, P)
    mould = _noise(nb, P, 1.6, detail=4.0)
    height = nb.math("ADD", nb.math("MULTIPLY", h, mask), nb.math("MULTIPLY", mould, 0.06))
    b = nb.n("ShaderNodeBump", Strength=1.0, Distance=0.32 * MM)
    nb.set(b.inputs["Height"], height)
    base = nb.mix(w, _rgb(nb, (0.022, 0.022, 0.024)), _rgb(nb, (0.05, 0.05, 0.053)), "RGBA")
    base = nb.mix(nb.math("MULTIPLY", mask, nb.smooth(0.2, 0.9, h)), base, _rgb(nb, (0.034, 0.034, 0.036)), "RGBA")
    r = nb.math("ADD", 0.48, nb.math("MULTIPLY", mould, 0.1))
    r = nb.mix(mask, r, 0.74)
    r = nb.mix(w, r, 0.4)
    _principled(nb, **{"Base Color": base, "Roughness": r, "Specular IOR Level": 0.5, "Normal": b.outputs["Normal"]})
    return m


def mat_fibre():
    m = bpy.data.materials.new("fibre")
    nb = _NB(m)
    _principled(nb, **{"Base Color": (1.0, 0.16, 0.03, 1.0), "Roughness": 0.18, "Coat Weight": 0.6,
                       "Emission Color": (1.0, 0.16, 0.03, 1.0), "Emission Strength": 0.6})
    return m


def materials():
    """The hero (Cycles) materials, procedural in gun-space millimetres."""
    return {
        "nitride": mat_metal("nitride", (0.10, 0.10, 0.105), (0.42, 0.42, 0.43), 0.40, 0.22, wear=1.0),
        "steel": mat_metal("steel", (0.075, 0.075, 0.078), (0.40, 0.40, 0.41), 0.44, 0.26, wear=0.7),
        "anodised": mat_metal("anodised", (0.06, 0.06, 0.066), (0.62, 0.62, 0.64), 0.38, 0.25, wear=0.8),
        "bronze": mat_metal("bronze", (0.52, 0.34, 0.15), (0.62, 0.45, 0.24), 0.24, 0.18, wear=0.25, streak=0.04),
        "polymer": mat_polymer(),
        "fibre": mat_fibre(),
    }


# ================================================================ in the hand
# Grip socket: where the gun sits in the posed hand, in a roll-independent
# hand frame built from joint positions (as hand_pose / hands_render do):
#   f     wrist (hand bone head) -> middle finger root
#   t     across the knuckles, toward the index (orthogonal to f)
#   back  out of the back of the hand
# The bore is f turned `alpha` toward t (in the palm plane): the fingers run
# a little below the bore, the wrist straight behind the gun. The gun's left
# (+Y) is the palm normal. The web crotch (bone level: half way between the
# thumb's MCP and the middle of the index metacarpal) goes `web_grip` =
# (t, u) on the grip: just under the beavertail, behind the backstrap
# surface by the web's flesh. Then:
#   aim()   turns the wrist (the hand bone about the palm normal) so the bore
#           sits at `pitch` deg in the world (G/E's high-ready hand is
#           authored for an empty grip, so it points the muzzle ~20 deg down)
#   seat()  moves the gun the least distance that takes it out of the palm
#           (hand and thumb-root skin), then closes it along the palm normal
#           to first contact: the palm on the grip panel, no overlap.
SOCKET = {"alpha": 12.0, "web_grip": (4.0, -6.0), "pitch": -2.0, "up": 4.0}
# The support hand (thumbs-forward two-hand grip): the strong hand's frame
# mirrored through the gun's mid-plane, turned `turn` deg fingers-down about
# the gun's Y axis through grip_point(*pivot), then moved `offset` (gun-space
# mm): its palm on the bare left grip panel, its fingers over the strong
# fingers, its thumb forward under the strong thumb. hand_pose's clear and
# wrap finish it.
SUPPORT = {"turn": 38.0, "pivot": (40.0, 25.0), "offset": (10.0, 8.0, -14.0)}
HERO_NAME = "pistol_hero"
GAP_M = 0.0004


def hand_frame(arm, s):
    """Posed hand frame of hand s (armature space): wrist, f, t, back."""
    pb = arm.pose.bones
    w = pb[f"hand_{s}"].head.copy()
    f = (pb[f"middle_01_{s}"].head - w).normalized()
    t = pb[f"index_01_{s}"].head - pb[f"pinky_01_{s}"].head
    t = (t - f * t.dot(f)).normalized()
    back = f.cross(t)
    if (pb[f"thumb_02_{s}"].head - w).dot(back) > 0:     # the thumb is on the palm side
        back = -back
    return w, f, t, back          # (f, t, back) is right-handed for a right hand, left-handed for a left


def web_crotch(arm, s):
    pb = arm.pose.bones
    return 0.5 * pb[f"thumb_02_{s}"].head + 0.25 * (pb[f"hand_{s}"].head + pb[f"index_01_{s}"].head)


def socket_matrix(arm, s="r", sock=None):
    """Gun matrix in armature space for the posed hand s, before aim and seat."""
    sock = sock or SOCKET
    w, f, t, back = hand_frame(arm, s)
    a = math.radians(sock["alpha"])
    X = f * math.cos(a) + t * math.sin(a)
    Z = -f * math.sin(a) + t * math.cos(a)
    Y = Z.cross(X)
    y = math.radians(sock.get("yaw", 0.0))      # the muzzle swung toward the palm side
    X, Y = X * math.cos(y) + Y * math.sin(y), Y * math.cos(y) - X * math.sin(y)
    R = Matrix((X, Y, Z)).transposed()
    W = Vector(grip_point(*sock["web_grip"])) * MM
    return Matrix.Translation(web_crotch(arm, s) - R @ W) @ R.to_4x4()


def build_hero(name=HERO_NAME):
    """The hero gun as one mesh (all parts joined, procedural materials)."""
    col = bpy.data.collections.new("pistol_parts")
    bpy.context.scene.collection.children.link(col)
    parts = build("hero", col)
    ob = join([o for g in parts.values() for o in g], name)
    bpy.context.scene.collection.objects.link(ob)
    col.objects.unlink(ob)
    bpy.data.collections.remove(col)
    ob["hero_prop"] = "pistol"
    return ob


def spawn(arm, s="r", name=HERO_NAME):
    """The hero gun in hand s: built on first use (reused after), parented to
    the hand bone on the grip socket of the current pose. Returns it."""
    ob = bpy.data.objects.get(name)
    if ob is None:
        ob = build_hero(name)
    ob.hide_render = False
    ob.hide_viewport = False
    ob.parent = arm
    ob.parent_type = "BONE"
    ob.parent_bone = f"hand_{s}"
    place(arm, ob, s)
    return ob


def place(arm, ob, s, sock=None):
    bpy.context.view_layer.update()
    ob.matrix_world = arm.matrix_world @ socket_matrix(arm, s, sock)
    bpy.context.view_layer.update()


def bore(ob):
    return (ob.matrix_world.to_3x3() @ Vector((1, 0, 0))).normalized()


def aim(arm, ob, s="r", pitch=None):
    """Turn the wrist (the hand bone about the palm normal, through the
    wrist) so the bore sits at `pitch` deg in the world (secant steps).
    Returns the turn in deg."""
    from mathutils import Quaternion
    pitch = SOCKET["pitch"] if pitch is None else pitch
    pb = arm.pose.bones[f"hand_{s}"]
    M0 = pb.matrix.copy()
    h = M0.translation.copy()
    _, _, _, back = hand_frame(arm, s)
    n = -back

    def turn(deg):
        pb.matrix = (Matrix.Translation(h) @ Quaternion(n, math.radians(deg)).to_matrix().to_4x4()
                     @ Matrix.Translation(-h) @ M0)
        bpy.context.view_layer.update()
        return math.degrees(math.asin(max(-1.0, min(1.0, bore(ob).z))))
    a0, p0 = 0.0, turn(0.0)
    a1, p1 = 5.0, turn(5.0)
    for _ in range(8):
        if abs(p1 - pitch) < 0.1 or abs(p1 - p0) < 1e-6:
            break
        a0, p0, a1 = a1, p1, a1 + (pitch - p1) * (a1 - a0) / (p1 - p0)
        a1 = max(-45.0, min(45.0, a1))
        p1 = turn(a1)
    return a1


def _palm(arm, s):
    """Posed palm skin of hand s (world coords, polygons): the skin of the
    hand bone and the thumb root near the hand."""
    from character import hand_pose
    sc = hand_pose.Scene(arm, s)
    body = sc.body
    co = hand_pose._posed(body)
    dom = hand_pose._dominant(body)
    near = np.linalg.norm(co - np.array(sc.centre()[:]), axis=1) < sc.radius
    keep = near & ((dom == f"hand_{s}") | (dom == f"thumb_01_{s}"))
    polys = [p for p in hand_pose._polys(body) if all(keep[i] for i in p)]
    used = sorted({i for p in polys for i in p})
    remap = {v: k for k, v in enumerate(used)}
    return co[used], [tuple(remap[i] for i in p) for p in polys]


def _local_bvh(ob):
    from mathutils.bvhtree import BVHTree
    me = ob.data
    co = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get("co", co)
    return BVHTree.FromPolygons([Vector(p) for p in co.reshape(-1, 3)], [tuple(p.vertices) for p in me.polygons],
                                epsilon=0.0)


def seat(arm, ob, s="r", reach_mm=40.0, rounds=2):
    """Seat the gun in the palm for a high, snug grip, by rigid moves of the
    gun (gun-space directions), each to first contact with the palm skin
    (the hand bone and thumb root) and backed off to a 0.4 mm gap:
      1. out of the palm along its normal if the socket starts inside it;
      2. `rounds` times: onto the palm along its normal, up into the hand
         along the grip axis (a high grip: the beavertail onto the web),
         and back into the web (the backstrap into the crotch).
    Returns a log line."""
    from mathutils.bvhtree import BVHTree
    gun = _local_bvh(ob)
    pco, ppolys = _palm(arm, s)
    M0 = ob.matrix_world.copy()
    R = M0.to_3x3()

    def hits(off):
        """Palm overlap with the gun moved by off (gun-space mm)."""
        M = Matrix.Translation(R @ (Vector(off) * MM)) @ M0
        Mi = np.array(M.inverted())
        loc = pco @ Mi[:3, :3].T + Mi[:3, 3]
        return len(gun.overlap(BVHTree.FromPolygons([Vector(p) for p in loc], ppolys, epsilon=0.0)))

    def move(off, d, until_contact, reach=reach_mm, step=1.0):
        """Slide from off along d: to the first clear point (until_contact
        False) or to just before the first contact (True). Returns (new
        offset, distance); the whole reach if that never happens."""
        prev = 0.0
        t = 0.0
        while t < reach:
            t = min(reach, t + step)
            h = hits(off + d * t)
            if bool(h) == until_contact:
                a, b = prev, t           # a: still in the old state, b: the new state
                for _ in range(7):
                    m = 0.5 * (a + b)
                    if bool(hits(off + d * m)) == until_contact:
                        b = m
                    else:
                        a = m
                if until_contact:
                    back = max(0.0, a - GAP_M / MM)
                    return off + d * back, back
                return off + d * (b + GAP_M / MM), b
            prev = t
        return off + d * reach, reach          # no contact (or never clear) within reach: the whole reach
    Y = Vector((0, 1, 0))
    up = Vector((GD[0], 0, GD[1]))         # gun down its grip axis = the hand higher on the grip
    web = -Vector((GN[0], 0, GN[1]))       # gun back = the backstrap into the web
    off = Vector((0, 0, 0))
    h0 = hits(off)
    steps = []
    if h0:
        off, d = move(off, Y, False)
        steps.append(f"out {d:.1f}")
        if hits(off):
            return f"seat: palm overlap {h0} tris, not cleared within {reach_mm:.0f} mm"
    for _ in range(rounds):
        for name, d, reach in (("onto palm", -Y, reach_mm), ("up", up, SOCKET.get("up", 25.0)), ("web", web, 15.0)):
            off, dist = move(off, d, True, reach)
            steps.append(f"{name} {dist:.1f}" if dist is not None else f"{name} -")
    ob.matrix_world = Matrix.Translation(R @ (off * MM)) @ M0
    bpy.context.view_layer.update()
    return (f"seat: palm overlap at the socket {h0} tris; " + ", ".join(steps)
            + f" mm; net move {tuple(round(v, 1) for v in off)} mm (gun space)")


def support(arm, ob, s="l", strong="r", sup=None):
    """Put the support hand s on the gun (orientation, then a two-bone IK
    move of the wrist; see SUPPORT). Returns a log line."""
    from character import hand_pose
    from mathutils import Quaternion
    sup = sup or SUPPORT
    G = arm.matrix_world.inverted() @ ob.matrix_world          # gun -> armature space
    piv = Vector(grip_point(*sup["pivot"])) * MM
    turn = Quaternion(Vector((0, 1, 0)), math.radians(sup["turn"])).to_matrix().to_4x4()      # + = fingers down
    local = (Matrix.Translation(Vector(sup["offset"]) * MM) @ Matrix.Translation(piv) @ turn
             @ Matrix.Translation(-piv) @ Matrix.Diagonal((1.0, -1.0, 1.0, 1.0)))
    T = G @ local @ G.inverted()
    T3 = T.to_3x3()
    w, f, t, back = hand_frame(arm, strong)
    tw, tf, tt, tb = T @ w, (T3 @ f).normalized(), (T3 @ t).normalized(), (T3 @ back).normalized()
    cw, cf, ct, cb = hand_frame(arm, s)
    Rd = Matrix((tf, tt, tb)).transposed() @ Matrix((cf, ct, cb)).transposed().inverted()
    pb = arm.pose.bones[f"hand_{s}"]
    h = pb.head.copy()
    pb.matrix = Matrix.Translation(h) @ Rd.to_4x4() @ Matrix.Translation(-h) @ pb.matrix
    bpy.context.view_layer.update()
    d = tw - pb.head
    hand_pose.move_hand(arm, s, d)
    err = (pb.head - tw).length * 1000
    return f"support hand_{s}: wrist moved {d.length * 1000:.0f} mm onto the gun (IK error {err:.1f} mm)"


def hold(arm, s="r", rerun=None):
    """Spawn, aim and seat the gun in hand s (after the pose, before the
    hand settle). Returns (object, log lines)."""
    ob = spawn(arm, s)
    turn = aim(arm, ob, s)
    if rerun:
        rerun()
    log = [f"pistol in hand_{s}: wrist turned {turn:+.1f} deg (bore pitch {SOCKET['pitch']:+.0f})",
           f"pistol in hand_{s}: " + seat(arm, ob, s)]
    return ob, log


def finish_hold(arm, ob, s="r", support_s=None, support_base=None, rerun=None):
    """After the strong hand's settle: the support hand onto the gun and
    settled on it (its own hand_pose pass, so it closes on the strong
    fingers as they are), then the index and thumbs placed. Returns log
    lines."""
    from character import hand_pose
    rerun = rerun or (lambda: None)
    log = []
    if support_s:
        log.append(support(arm, ob, support_s, s))
        rerun()
        log += hand_pose.settle(arm, (), rerun=rerun, spec={support_s: support_spec(support_base)})
    log += place_digits(arm, ob, s, support_s)
    return log


def hide(name=HERO_NAME):
    ob = bpy.data.objects.get(name)
    if ob is not None:
        ob.hide_render = True
        ob.hide_viewport = True


def hand_spec(s="r"):
    """hand_pose.settle spec for the hand holding the gun: the grip shape,
    then the middle, ring and pinky curl round the front strap to first
    contact. The index (straight, along the frame above the trigger guard,
    never on the trigger) and the thumb are placed by place_digits()."""
    from character import deform_poses as dp
    shape = dp.hand(80, 92, 50, thumb=(8, 10, 8), cascade=0.1)
    shape["index_01_l"] = [["flex", 4.0]]
    shape["index_02_l"] = [["flex", 7.0]]
    shape["index_03_l"] = [["flex", 4.0]]
    return {"shape": shape, "shape_name": "pistol_grip", "wrap": ("middle", "ring", "pinky"), "wrap_max": 1.6}


def support_spec(base):
    """The support hand's settle spec (G's high_ready entry, if any): clear
    and wrap, but its thumb is placed by place_digits()."""
    hs = dict(base or {"clear": True, "wrap": ("index", "middle", "ring", "pinky"), "wrap_max": 1.3})
    hs["wrap"] = tuple(d for d in hs.get("wrap", ()) if d != "thumb")
    return hs


# Digits placed on the gun after the settle (gun-space mm, bone level: a
# finger's bone runs ~8 mm inside its skin). The strong index straight along
# the frame side above the trigger guard, its tip aimed at a point (backed
# off `out` mm by mm if it cuts in). The thumbs: seed chains (MCP, IP, tip
# points) and a mark for the tip, then a small search (_solve_thumb) that
# keeps them out of everything. This hand's thumb root sits ~40 mm right of
# the bore plane with a 34 mm metacarpal, so the strong thumb cannot reach
# high on the left of the frame: its MCP goes behind the backstrap under the
# beavertail and the thumb runs forward low on the left of the frame (a
# wrapped thumb). The support thumb lies forward along the frame above the
# trigger guard, pointing at the target.
DIGITS = {"strong": {"index": ((120.0, -19.0, -19.0), (0, -1, 0))}, "support": {}}
THUMBS = {
    "strong": ([((-28, -10, -38), (-2, 28, -32), (30, 30, -28)), ((-32, -13, -30), (-8, 24, -32), (22, 30, -30)),
                ((-30, -6, -34), (2, 28, -28), (34, 28, -24))], (32, 28, -26)),
    "support": ([((38, 40, -22), (66, 30, -24), (96, 26, -24)), ((36, 44, -30), (64, 34, -32), (94, 28, -30)),
                 ((40, 38, -16), (70, 28, -18), (100, 24, -18))], (98, 24, -26)),
}


def _aim_digit(arm, ob, s, d, target_mm, out, step_mm=1.0, reach_mm=14.0):
    """Swing digit d of hand s about its root so its tip points at the
    gun-space target; if it then cuts into anything (hand_pose overlap), move
    the target `out` mm by mm. Returns a log fragment."""
    from character import hand_pose
    names = hand_pose.digit_bones(s, d)
    G = arm.matrix_world.inverted() @ ob.matrix_world
    o = (G.to_3x3() @ Vector(out)).normalized()
    pb = arm.pose.bones
    base = pb[names[0]].matrix_basis.copy()
    n = 0
    for k in range(int(reach_mm / step_mm) + 1):
        pb[names[0]].matrix_basis = base
        bpy.context.view_layer.update()
        tgt = G @ (Vector(target_mm) * MM) + o * (k * step_mm * MM)
        for _ in range(2):
            v1 = pb[names[2]].tail - pb[names[0]].head
            v2 = tgt - pb[names[0]].head
            hand_pose._rotate(arm, names[0], v1.rotation_difference(v2))
        n = _digit_hits(arm, s, d)
        if not n:
            return f"{d} on target" + (f" (+{k * step_mm:.0f} mm out)" if k else "")
    return f"{d} {n} tris still touching after {reach_mm:.0f} mm out"


def _chain(arm, ob, s, d, pts):
    """Aim the bones of digit d of hand s in turn at gun-space points (mm):
    pts[0] for the second joint, pts[1] for the third, pts[2] for the tip
    (None: keep that bone). Each bone keeps its length; a point it cannot
    reach sets only its direction."""
    from character import hand_pose
    names = hand_pose.digit_bones(s, d)
    G = arm.matrix_world.inverted() @ ob.matrix_world
    pb = arm.pose.bones
    for k, p in enumerate(pts):
        if p is None:
            continue
        tgt = G @ (Vector(p) * MM)
        b = pb[names[k]]
        for _ in range(2):
            hand_pose._rotate(arm, names[k], (b.tail - b.head).rotation_difference(tgt - b.head))


def _digit_hits(arm, s, d):
    from character import hand_pose
    sc = hand_pose.Scene(arm, s)
    g = sc.build((d, "index") if d == "thumb" else (d,))
    n = sc.hits(g[d], g["foreign"])
    if d == "thumb" and g["thumb"] is not None and g["index"] is not None:
        n += len(g["thumb"].overlap(g["index"]))      # the thumb's crotch against the index
    return n


def _solve_thumb(arm, ob, s, seeds, tip, steps=(16.0, 8.0, 4.0, 2.0)):
    """Pose the thumb of hand s on the gun: start from the best of the seed
    chains (MCP, IP, tip points in gun space mm, see _chain), then a greedy
    search turning each thumb bone (children follow) a step either way about
    the two axes across it, keeping a turn when it lowers the cost:
    1000 x the triangles the thumb cuts (into anything not this arm, and the
    index's skin) + the tip's distance (mm) from `tip`. Returns a log
    fragment."""
    from character import hand_pose
    from mathutils import Quaternion
    names = hand_pose.digit_bones(s, "thumb")
    G = arm.matrix_world.inverted() @ ob.matrix_world
    goal = G @ (Vector(tip) * MM)
    pb = arm.pose.bones
    base = hand_pose._bases(arm, names)

    def cost():
        n = _digit_hits(arm, s, "thumb")
        d = (pb[names[2]].tail - goal).length / MM
        return n * 1000.0 + d, n, d

    best = None
    for pts in seeds:
        hand_pose._set_bases(arm, base)
        _chain(arm, ob, s, "thumb", pts)
        c = cost()
        if best is None or c[0] < best[0][0]:
            best = (c, hand_pose._bases(arm, names))
    hand_pose._set_bases(arm, best[1])
    cur, evals = best[0], len(seeds)
    for st in steps:
        improved = True
        while improved and evals < 400:
            improved = False
            for n in names:
                b = pb[n]
                ax0 = (b.tail - b.head).normalized()
                a1 = ax0.orthogonal().normalized()
                a2 = ax0.cross(a1).normalized()
                for ax in (a1, a2):
                    for sg in (1.0, -1.0):
                        keep = hand_pose._bases(arm, names)
                        hand_pose._rotate(arm, n, Quaternion(ax, math.radians(st * sg)))
                        c = cost()
                        evals += 1
                        if c[0] < cur[0] - 1e-3:
                            cur, improved = c, True
                        else:
                            hand_pose._set_bases(arm, keep)
    return (f"thumb {'clear' if not cur[1] else f'{cur[1]} tris still touching'}, tip {cur[2]:.0f} mm "
            f"from its mark ({evals} tries)")


def place_digits(arm, ob, s="r", support_s="l"):
    """After the hand settle: the strong index and both thumbs onto their
    places on the gun (DIGITS, THUMBS). Returns log lines."""
    out = []
    for role, side in (("strong", s), ("support", support_s)):
        if side is None:
            continue
        parts = [_aim_digit(arm, ob, side, d, tgt, o) for d, (tgt, o) in DIGITS[role].items()]
        if THUMBS[role]:
            parts.append(_solve_thumb(arm, ob, side, *THUMBS[role]))
        out.append(f"pistol {role} hand_{side}: " + ", ".join(parts))
    return out


# ================================================================ game asset
# The game pistol: the "game" detail level, one node per moving part, one UV
# atlas, the hero materials baked into it (Cycles), one glTF material.
GAME_GROUPS = ("slide", "barrel", "frame", "trigger", "magazine")
TRIGGER_PIVOT = (63.2, 0.0, -29.8)          # mm: the trigger bow's top, its hinge


def _select(objs, active=None):
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = active or objs[0]


def atlas(objs, margin=0.004):
    """One UV atlas over all the objects: smart projection (islands keep their
    3D scale relative to each other), then one packing pass."""
    _select(objs)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(58.0), island_margin=margin, area_weight=0.0,
                             correct_aspect=True, scale_to_bounds=False)
    bpy.ops.uv.pack_islands(rotate=True, margin=margin)
    bpy.ops.object.mode_set(mode="OBJECT")


def _image(name, size, data=False):
    im = bpy.data.images.new(name, size, size, alpha=False, float_buffer=False)
    im.colorspace_settings.name = "Non-Color" if data else "sRGB"
    return im


def _principled_of(m):
    return next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")


def _output_of(m):
    return next(n for n in m.node_tree.nodes if n.type == "OUTPUT_MATERIAL")


def _bake_pass(objs, mats, img, kind, socket=None, samples=16):
    """Bake one pass of every material into img. kind: a Cycles bake type
    (NORMAL, AO) or EMIT with `socket` (a Principled input baked as
    emission: Base Color, Roughness, Metallic)."""
    sc = bpy.context.scene
    sc.cycles.samples = samples
    undo = []
    for m in mats:
        nt = m.node_tree
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = img
        nt.nodes.active = tex
        undo.append((nt, [tex], None))
        if kind == "EMIT":
            p, out = _principled_of(m), _output_of(m)
            em = nt.nodes.new("ShaderNodeEmission")
            inp = p.inputs[socket]
            if inp.is_linked:
                nt.links.new(inp.links[0].from_socket, em.inputs["Color"])
            else:
                v = inp.default_value
                em.inputs["Color"].default_value = (v, v, v, 1.0) if isinstance(v, float) else tuple(v)
            old = out.inputs["Surface"].links[0].from_socket
            nt.links.new(em.outputs[0], out.inputs["Surface"])
            undo[-1] = (nt, [tex, em], (old, out))
    _select(objs)
    bpy.ops.object.bake(type=kind, margin=8, use_clear=True, normal_space="TANGENT")
    for nt, nodes, relink in undo:
        if relink:
            nt.links.new(relink[0], relink[1].inputs["Surface"])
        for n in nodes:
            nt.nodes.remove(n)


def bake(objs, size=2048, orm_size=1024, samples=16):
    """Bake the procedural hero materials of objs into base colour, normal
    and ORM (R occlusion, G roughness, B metallic) maps. Returns images."""
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.render.bake.margin = 8
    mats = sorted({s.material for o in objs for s in o.material_slots if s.material}, key=lambda m: m.name)
    base = _image("pistol_basecolor", size)
    nrm = _image("pistol_normal", size, data=True)
    _bake_pass(objs, mats, base, "EMIT", "Base Color", samples)
    _bake_pass(objs, mats, nrm, "NORMAL", samples=samples)
    ch = {}
    for name, kind, sock in (("ao", "AO", None), ("rough", "EMIT", "Roughness"), ("metal", "EMIT", "Metallic")):
        im = _image(f"pistol_{name}", orm_size, data=True)
        _bake_pass(objs, mats, im, kind, sock, samples * 2 if kind == "AO" else samples)
        ch[name] = np.array(im.pixels[:]).reshape(-1, 4)
        bpy.data.images.remove(im)
    orm = _image("pistol_orm", orm_size, data=True)
    px = np.ones((orm_size * orm_size, 4))
    px[:, 0] = np.clip(0.35 + 0.65 * ch["ao"][:, 0], 0.0, 1.0)     # baked AO, softened (it is static)
    px[:, 1] = ch["rough"][:, 0]
    px[:, 2] = ch["metal"][:, 0]
    orm.pixels[:] = px.ravel()
    return {"basecolor": base, "normal": nrm, "orm": orm}


def gltf_material(imgs, name="pistol"):
    """One glTF-ready material on the baked maps (occlusion through the
    exporter's "glTF Material Output" group)."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    p = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(p.outputs[0], out.inputs["Surface"])
    tb = nt.nodes.new("ShaderNodeTexImage")
    tb.image = imgs["basecolor"]
    nt.links.new(tb.outputs["Color"], p.inputs["Base Color"])
    to = nt.nodes.new("ShaderNodeTexImage")
    to.image = imgs["orm"]
    sep = nt.nodes.new("ShaderNodeSeparateColor")
    nt.links.new(to.outputs["Color"], sep.inputs["Color"])
    nt.links.new(sep.outputs["Green"], p.inputs["Roughness"])
    nt.links.new(sep.outputs["Blue"], p.inputs["Metallic"])
    tn = nt.nodes.new("ShaderNodeTexImage")
    tn.image = imgs["normal"]
    nm = nt.nodes.new("ShaderNodeNormalMap")
    nt.links.new(tn.outputs["Color"], nm.inputs["Color"])
    nt.links.new(nm.outputs["Normal"], p.inputs["Normal"])
    g = bpy.data.node_groups.get("glTF Material Output")
    if g is None:
        g = bpy.data.node_groups.new("glTF Material Output", "ShaderNodeTree")
        g.interface.new_socket("Occlusion", in_out="INPUT", socket_type="NodeSocketFloat")
    gn = nt.nodes.new("ShaderNodeGroup")
    gn.node_tree = g
    nt.links.new(sep.outputs["Red"], gn.inputs["Occlusion"])
    return m


def socket_empty(name="grip_socket", parent=None):
    """The grip socket: on the backstrap where the web of the hand sits
    (SOCKET web_grip), X along the bore, Z up the gun."""
    e = bpy.data.objects.new(name, None)
    e.empty_display_type = "ARROWS"
    e.empty_display_size = 0.03
    e.location = Vector(grip_point(*SOCKET["web_grip"])) * MM
    e.parent = parent
    bpy.context.scene.collection.objects.link(e)
    return e


def export_game(out, size=2048, orm_size=1024, samples=16):
    """Build, atlas, bake and export the game pistol: out/pistol.glb (+
    .blend, .json, the maps as PNG). Returns the record."""
    t0 = time.perf_counter()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    col = bpy.data.collections.new("pistol_game")
    bpy.context.scene.collection.children.link(col)
    mats = materials()
    parts = build("game", col, mats)
    nodes = {g: join(parts[g], f"pistol_{g}") for g in GAME_GROUPS}
    objs = list(nodes.values())
    atlas(objs)
    t1 = time.perf_counter()
    imgs = bake(objs, size, orm_size, samples)
    t2 = time.perf_counter()
    gm = gltf_material(imgs)
    for o in objs:
        o.data.materials.clear()
        o.data.materials.append(gm)
        if "stipple" in o.data.attributes:
            o.data.attributes.remove(o.data.attributes["stipple"])
        # triangles on export (applied by the exporter), so an engine's MikkTSpace tangents
        # match the bake's (exported tangents would carry two zero vectors from sliver UV faces)
        tm = o.modifiers.new("triangulate", "TRIANGULATE")
        tm.keep_custom_normals = True
        tm.quad_method, tm.ngon_method = "BEAUTY", "BEAUTY"
    # the trigger hinges at its pivot
    tr = nodes["trigger"]
    piv = Vector(TRIGGER_PIVOT) * MM
    tr.data.transform(Matrix.Translation(-piv))
    tr.location = piv
    root = bpy.data.objects.new("pistol", None)
    bpy.context.scene.collection.objects.link(root)
    for o in objs:
        o.parent = root
    sock = socket_empty(parent=root)
    for o in objs:
        for c in list(o.users_collection):
            c.objects.unlink(o)
        bpy.context.scene.collection.objects.link(o)
    bpy.data.collections.remove(col)
    for k, im in imgs.items():
        im.filepath_raw = os.path.join(out, f"pistol_{k}.png")
        im.file_format = "PNG"
        im.save()
        im.pack()
    glb = os.path.join(out, "pistol.glb")
    bpy.ops.export_scene.gltf(filepath=glb, export_format="GLB", export_yup=True, export_apply=True,
                              export_texcoords=True, export_normals=True, export_tangents=False, export_materials="EXPORT",
                              export_image_format="AUTO", export_extras=True, use_selection=False)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out, "pistol.blend"))
    co = np.array([v for o in objs for v in (o.matrix_world @ Vector(x.co) for x in o.data.vertices)])
    lo, hi = co.min(0) / MM, co.max(0) / MM
    rec = {
        "glb": "pistol.glb", "detail": "game", "tris": {g: tris([o]) for g, o in nodes.items()},
        "tris_total": tris(objs), "maps": {k: list(im.size) for k, im in imgs.items()},
        "bake_samples": samples, "size_mm": {"length": round(float(hi[0] - lo[0]), 1), "width": round(float(hi[1] - lo[1]), 1),
                                            "height": round(float(hi[2] - lo[2]), 1)},
        "socket": {"name": sock.name, "location_mm": [round(v / MM, 2) for v in sock.location],
                   "note": "the web of the strong hand on the backstrap; Blender X = bore, Z = up (glTF: X = bore, Y = up)"},
        "nodes": {g: {"name": o.name, "origin_mm": [round(v / MM, 2) for v in o.location]} for g, o in nodes.items()},
        "seconds": {"build_atlas": round(t1 - t0, 1), "bake": round(t2 - t1, 1),
                    "total": round(time.perf_counter() - t0, 1)},
    }
    with open(os.path.join(out, "pistol.json"), "w") as f:
        json.dump(rec, f, indent=1)
    return rec


# ================================================================ CLI
def main(argv):
    """Game asset (default): OUT/pistol.glb, .blend, .json and the baked maps.
    --detail hero|game --blend-only: just the built parts in a .blend."""
    import argparse
    ap = argparse.ArgumentParser(prog="pistol.py")
    ap.add_argument("--out", required=True)
    ap.add_argument("--detail", default="game", choices=sorted(QUALITY))
    ap.add_argument("--blend-only", action="store_true")
    ap.add_argument("--size", type=int, default=2048, help="base colour and normal map size")
    ap.add_argument("--orm", type=int, default=1024, help="occlusion / roughness / metallic map size")
    ap.add_argument("--samples", type=int, default=16)
    a = ap.parse_args(argv)
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    if not a.blend_only:
        rec = export_game(out, a.size, a.orm, a.samples)
        print(f"[pistol] game: {rec['tris_total']} tris {rec['tris']}, size {rec['size_mm']} mm, "
              f"{rec['seconds']} s -> {os.path.join(out, 'pistol.glb')}")
        return
    bpy.ops.wm.read_factory_settings(use_empty=True)
    t = time.perf_counter()
    parts = build(a.detail)
    allp = [o for g in parts.values() for o in g]
    print(f"[pistol] {a.detail}: {len(allp)} parts, {tris(allp)} tris, {time.perf_counter() - t:.1f} s")
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out, f"pistol_{a.detail}.blend"))


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
