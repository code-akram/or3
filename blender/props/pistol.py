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

writes DIR/pistol.glb (the game asset: the "game" detail level, 10.3k tris,
one node per moving part - slide, barrel, frame, trigger (origin on its
hinge), magazine - under a root "pistol", a "grip_socket" empty where the
web of the hand sits; one material on a 2k base colour, 2k normal and 1k
ORM atlas baked from the hero materials), DIR/pistol.blend, DIR/pistol.json
(stats) and the maps as PNG. --blend-only --detail hero|game: just the
built parts.

From Python (the hero stage poses through hero/poses.py, which does this
for a pose that holds the gun: "ready", or any pose + "+pistol"):

    from props import pistol
    gun, log = pistol.hold(arm, "r", rerun)          # hero build on hand_r: socket, level, straighten, seat
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
SLIDE_YZ = [(-11.8, -12.0), (11.8, -12.0), (11.8, 7.2), (7.9, 15.4), (5.9, 17.0),
            (-5.9, 17.0), (-7.9, 15.4), (-11.8, 7.2)]
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
    axis 'x': poly in (y, z), extruded x a0..a1; axis 'z': poly in (x, y),
    extruded z a0..a1. mm in, metres out."""
    bm = bmesh.new()

    def P(p, a):
        if axis == "z":
            return (p[0] * MM, p[1] * MM, a * MM)
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
    return 10.72 + 3.78 * _smooth(-2.0, 16.0, t) + 0.3 * math.sin(math.pi * min(max((t - 10) / (GRIP_END - 18.0), 0), 1))


def grip_swell(t):
    """Palm swell: the backstrap bulges back (mm)."""
    return 1.8 * math.sin(math.pi * min(max((t - 4.0) / (GRIP_END - 9.0), 0.0), 1.0))


STIPPLE_T = (4.0, 69.0)                 # the stippled band (grip stations, mm)
GRIP_END = 76.0                         # the grip's last station: the magwell from here
# the receiver behind the trigger, under the slide: horizontal rings (z, back
# x, front x (hidden in the frame), back and front corner radii)
GRIP_TOP = [(-13.2, -1.0, 97.0, 5.0, 2.0), (-17.0, -1.2, 97.0, 6.0, 2.0), (-21.0, -1.4, 97.0, 7.0, 2.0),
            (-25.0, -1.6, 97.0, 8.0, 2.0), (-28.6, -1.5, 97.0, 9.0, 2.0), (-30.0, -1.4, 96.6, 9.0, 1.4)]
# then stations down the backstrap line: (t, how far the ring has turned from
# horizontal to normal-to-the-axis)
GRIP_T = [(2, 0.3), (5, 0.6), (8, 0.85), (11, 1), (14, 1), (17, 1), (21, 1), (25, 1), (29, 1), (33, 1), (37, 1),
          (41, 1), (45, 1), (49, 1), (53, 1), (57, 1), (61, 1), (65, 1), (69, 1), (72, 1), (74, 1), (76, 1)]


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
    """The grip loft (with the undercut behind the trigger guard). Face
    attribute 'stipple' = 1 marks the grip for the polymer shader, which
    draws the stippled band (STIPPLE_T) and its border from the position, so
    the panel edge is clean whatever the mesh."""
    ob = loft("grip", grip_rings(q), col)
    boolean(ob, [_undercut(col, q)])
    me = ob.data
    att = me.attributes.new("stipple", "FLOAT", "FACE")
    att.data.foreach_set("value", [1.0] * len(me.polygons))
    me.shade_smooth()
    return ob


def _beavertail_sections():
    """The beavertail tang: (x, top z, bottom z, half-width) sections. Full
    width under the slide's rear, then a rounded end (a circle in plan, the
    same in side view) the web of the hand sits in; thick to its tip."""
    out = []
    R, xc = 10.4, -7.4
    for x in (1.0, -2.0, -4.5, -7.4, -9.6, -11.7, -13.5, -15.0, -16.2, -17.0, -17.5, -17.75):
        k = (1.0 - x) / 18.75
        top0, bot0 = -12.6 - 0.9 * k, -33.0 + 8.0 * k
        r = 1.0 if x >= xc else math.sqrt(max(0.0, 1.0 - ((x - xc) / R) ** 2))
        r = max(r, 0.12)
        zc, hh = 0.5 * (top0 + bot0), 0.5 * (top0 - bot0)
        out.append((x, zc + hh * math.sqrt(r), zc - hh * math.sqrt(r), R * r))
    return out


def build_beavertail(col, q):
    rings = []
    for x, top, bot, w in _beavertail_sections():
        rb = min(w, (top - bot) / 2) * 0.95
        rings.append([(x, v, u) for u, v in _rrect(bot, top, w, rb, min(2.0, rb), q["corner"])])
    ob = loft("beavertail", rings, col)
    ob.data.shade_smooth()
    return ob


def build_magwell(col, q):
    """The flared magwell: a modest flare over the last 13 mm of the grip."""
    D = GRIP_DEPTH
    t0 = GRIP_END - 5.0
    w0 = grip_w(t0) + 0.25
    rings = []
    for t in (t0, t0 + 3.0, t0 + 6.0, t0 + 9.0, t0 + 11.5, t0 + 13.5):
        f = ((t - t0) / 13.5) ** 1.6
        rings.append(_ring(t, -0.6 - 0.9 * f, D + 0.9 + 2.8 * f, w0 + 1.1 * f, 11.5, 9.5, q["corner"]))
    u0, u1, w = -1.5, D + 3.7, w0 + 1.1
    te = t0 + 13.5
    rings.append(_ring(te, u0 + 1.4, u1 - 1.4, w - 1.4, 10.0, 8.0, q["corner"]))      # the mouth lip
    rings.append(_ring(te - 2.5, u0 + 2.8, u1 - 2.6, w - 3.0, 8.5, 6.5, q["corner"]))  # funnel in
    rings.append(_ring(te - 5.5, 1.2, D - 1.4, 11.6, 7.0, 5.5, q["corner"]))
    ob = loft("magwell", rings, col)
    ob.data.shade_smooth()
    return ob


def build_basepad(col, q):
    """The magazine's base pad: a 5.8 mm pad, flared a little past the magwell."""
    D = GRIP_DEPTH
    t0 = GRIP_END + 8.8
    rings = [
        _ring(t0, 1.0, D - 2.0, 11.4, 7.0, 5.5, q["corner"]),          # the magazine body, in the mouth
        _ring(t0 + 0.6, 1.0, D - 2.0, 11.4, 7.0, 5.5, q["corner"]),
        _ring(t0 + 0.8, -0.6, D + 1.8, 13.6, 10.0, 8.0, q["corner"]),
        _ring(t0 + 1.4, -1.2, D + 2.8, 14.3, 10.5, 8.5, q["corner"]),
        _ring(t0 + 4.2, -1.6, D + 3.8, 14.7, 11.0, 9.0, q["corner"]),
        _ring(t0 + 5.3, -1.6, D + 4.0, 14.6, 11.0, 9.0, q["corner"]),
        _ring(t0 + 5.8, -1.1, D + 3.4, 14.0, 10.5, 8.6, q["corner"]),
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
    cut = [_nose(col, 150.0, 186.0, 10.0, 3.6, s) for s in (1, -1)]
    cut += [_corner(col, SLIDE_X[1], 17.0, 2.6), _corner(col, SLIDE_X[0], 17.0, 1.4)]
    # rear cocking serrations (8, leaning forward) and front serrations (6)
    cut += _serrations(col, [12.0 + 4.6 * k for k in range(8)], 1.9, 1.15, -12.0)
    cut += _serrations(col, [128.0 + 4.6 * k for k in range(6)], 1.9, 1.15, -12.0)
    # ejection port: right side (-y), over the top to just past the centre line
    cut.append(box(col, 70.0, 111.0, -30.0, 3.4, 3.0, 30.0, name="port"))
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
    return finish(sl, 0.7, q)


COMP_YZ = [(-11.3, -11.6), (11.3, -11.6), (11.3, 7.2), (7.6, 15.0), (5.7, 16.6),
           (-5.7, 16.6), (-7.6, 15.0), (-11.3, 7.2)]


def _corner(col, x, z, leg, lean=45.0):
    """Cutter that chamfers the edge along y at (x, z) with legs `leg`."""
    a = leg * math.sqrt(2.0)
    return box(col, x - a / 2, x + a / 2, -30.0, 30.0, z - a / 2, z + a / 2, rot_y=lean, name="chamfer")


def _port(col, x0, x1, w, r, z0=2.0, z1=30.0, seg=4):
    """A top port: a rounded rectangle (x0..x1, |y| < w, corner radius r)
    cut down from the top to z0."""
    poly = _fillet([(x0, -w, r), (x1, -w, r), (x1, w, r), (x0, w, r)], seg)
    return _prism("port", poly, z0, z1, col, "z")


def build_comp(col, q):
    cp = prism_yz("comp", COMP_YZ, *COMP_X, col)
    cut = [_nose(col, 194.0, 214.0, 6.5, 2.6, s) for s in (1, -1)]
    cut.append(_corner(col, COMP_X[1], 16.6, 3.8))                     # top-front chamfer
    cut.append(_corner(col, COMP_X[1], -11.6, 2.2))                    # bottom-front chamfer
    cut.append(_corner(col, COMP_X[0], 16.6, 1.2))                     # the joint to the slide
    cut.append(cyl(col, 184.0, 191.0, 6.95, n=q["cyl"]))                 # barrel in
    cut.append(cyl(col, 190.4, 209.0, 7.4, n=q["cyl"]))                  # expansion chamber
    cut.append(cyl(col, 208.5, 216.0, 5.1, n=q["cyl"]))                  # exit
    cut.append(cyl(col, 211.4, 214.6, 5.1, n=q["cyl"], r1=7.6))          # recessed crown
    # three top ports, narrowing toward the muzzle
    cut += [_port(col, 189.0, 194.2, 4.4, 1.4, seg=q["fil"]), _port(col, 196.4, 201.2, 4.0, 1.3, seg=q["fil"]),
            _port(col, 203.4, 207.6, 3.5, 1.2, seg=q["fil"])]
    boolean(cp, cut)
    return finish(cp, 0.65, q)


def build_barrel(col, q):
    b = cyl(col, 64.0, 190.5, 6.75, n=q["cyl"], name="barrel")
    hood = box(col, 64.0, 112.0, -6.85, 6.85, -1.0, 16.35, name="hood")
    boolean(b, [hood], "UNION")
    cut = [cyl(col, 100.0, 192.0, 4.55, n=q["cyl"]),
           cyl(col, 189.4, 190.6, 4.55, n=q["cyl"], r1=5.7)]          # recessed crown chamfer
    boolean(b, cut)
    return finish(b, 0.45, q)


FRAME_XZ = [
    (0.5, -12.6, 0), (183.0, -12.6, 0), (184.6, -14.5, 1.0), (184.6, -23.8, 1.2), (182.0, -26.6, 0),
    (99.0, -26.6, 0), (97.5, -30.4, 1.5), (58.0, -30.4, 3.0),
    (52.0, -33.2, 0), (30.0, -34.0, 0), (2.0, -30.0, 0),                # inside the grip
]
GUARD_OUT = [(56.0, -27.5, 0), (100.0, -27.5, 0), (100.3, -30.5, 0), (103.6, -50.2, 3.0), (100.6, -56.4, 3.0),
             (60.0, -59.2, 6.0), (47.0, -58.6, 0), (44.0, -50.0, 0), (45.6, -40.0, 0)]
GUARD_IN = [(94.0, -31.0, 1.5), (95.6, -49.4, 3.4), (58.0, -51.6, 4.0), (46.0, -50.2, 0), (52.0, -31.0, 0)]
UNDERCUT = ((46.0, -56.0), 3.0)         # behind the guard: the high grip's notch (centre x, z; radius)
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


def _undercut(col, q):
    (x, z), r = UNDERCUT
    return cyl(col, -20.0, 20.0, r, axis="y", c=(x, z), n=q["cyl"], name="undercut")


def build_frame(col, q):
    fr = prism_xz("frame", FRAME_XZ, -FRAME_W, FRAME_W, col, q["fil"])
    finish(fr, 0.9, q)
    g = prism_xz("guard", GUARD_OUT, -6.0, 6.0, col, q["fil"])
    boolean(g, [prism_xz("hole", GUARD_IN, -8.0, 8.0, col, q["fil"]), _undercut(col, q)])
    finish(g, 2.0, q, segs=q["segs"] + 1)
    rail = prism_yz("rail", RAIL_YZ, 110.0, 182.0, col)
    boolean(rail, [box(col, c - 1.6, c + 1.6, -12.0, 12.0, -32.0, -29.0) for c in (122.0, 134.0, 146.0, 158.0, 170.0)])
    finish(rail, 0.5, q)
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
    finish(rs, 0.5, q)
    fs = prism_xz("front_sight", FRONT_SIGHT_XZ, -1.55, 1.55, col, q["fil"])
    boolean(fs, [box(col, 170.4, 179.6, -0.6, 0.6, 21.4, 30.0)])
    finish(fs, 0.4, q)
    fib = finish(cyl(col, 170.0, 180.0, 0.82, c=(0.0, 21.6), n=max(12, q["cyl"] // 3), name="fibre"), 0.0, q)
    plate = finish(prism_yz("optic_plate", PLATE_YZ, 18.6, 59.4, col), 0.45, q)
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
    grip = att.outputs["Fac"]
    # grip station t of the point (along the grip axis from the backstrap line)
    sep = nb.n("ShaderNodeSeparateXYZ")
    nb.set(sep.inputs[0], P)
    t = nb.math("ADD", nb.math("MULTIPLY", nb.math("SUBTRACT", sep.outputs[0], GB0[0]), GD[0]),
                nb.math("MULTIPLY", nb.math("SUBTRACT", sep.outputs[2], GB0[1]), GD[1]))
    t0, t1, bw = STIPPLE_T[0], STIPPLE_T[1], 1.6
    band = nb.math("MULTIPLY", nb.smooth(t0 + bw, t0 + bw + 0.3, t), nb.math("SUBTRACT", 1.0, nb.smooth(t1 - bw - 0.3, t1 - bw, t)))
    outer = nb.math("MULTIPLY", nb.smooth(t0 - 0.3, t0, t), nb.math("SUBTRACT", 1.0, nb.smooth(t1, t1 + 0.3, t)))
    mask = nb.math("MULTIPLY", band, grip)
    border = nb.math("MULTIPLY", nb.math("SUBTRACT", outer, band), grip)     # the raised smooth frame
    h = _stipple_height(nb, P)
    mould = _noise(nb, P, 1.6, detail=4.0)
    height = nb.math("ADD", nb.math("MULTIPLY", nb.math("SUBTRACT", h, 0.35), mask), nb.math("MULTIPLY", mould, 0.06))
    height = nb.math("ADD", height, nb.math("MULTIPLY", border, 0.9))
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
        "nitride": mat_metal("nitride", (0.035, 0.035, 0.037), (0.42, 0.42, 0.43), 0.40, 0.22, wear=1.0),
        "steel": mat_metal("steel", (0.045, 0.045, 0.047), (0.40, 0.40, 0.41), 0.44, 0.26, wear=0.7),
        "anodised": mat_metal("anodised", (0.04, 0.04, 0.044), (0.62, 0.62, 0.64), 0.38, 0.25, wear=0.8),
        "bronze": mat_metal("bronze", (0.52, 0.34, 0.15), (0.62, 0.45, 0.24), 0.24, 0.18, wear=0.25, streak=0.04),
        "polymer": mat_polymer(),
        "fibre": mat_fibre(),
    }


# ================================================================ in the hand
# The hold is authored from the hand (the hand is the constraint), in a
# roll-independent hand frame built from joint positions:
#   f     wrist (hand bone head) -> middle finger root (the metacarpal line)
#   t     across the knuckles, toward the index (orthogonal to f)
#   back  out of the back of the hand
# The bore is f turned `alpha` deg toward t: the gun nearly in line with the
# hand and forearm, the knuckle row (which leans ~15 deg off t) along the
# raked front strap. The knuckle row's middle (half way between the index and
# pinky roots, bone level) goes `knuckles` = (t, u) on the grip: half way down
# it, at the front strap, so the middle finger runs right under the trigger
# guard and the web sits under the beavertail. The gun's left (+Y) is the
# palm normal. Then:
#   orient()   turns the hand about the wrist so the gun is level (`pitch`)
#              and upright, pointing along the forearm;
#   straighten() moves the wrist (two-bone IK, the hand keeps its
#              orientation) so the forearm lines up with the hand (wrist
#              bend <= WRIST_MAX where the arm allows);
#   seat()     slides the gun along the palm normal until the palm skin sits
#              `squash_mm` into the grip and the thenar pad `thenar_mm` (soft
#              tissue; contact() squashes it onto the surface at the end).
SOCKET = {"alpha": 4.0, "cant": 10.0, "yaw": 0.0, "knuckles": (26.0, 46.0), "pitch": -2.0, "squash_mm": 2.0,
          "thenar_mm": 6.0}
# The support hand (thumbs-forward two-hand grip): the strong hand's frame
# mirrored through the gun's mid-plane, turned `turn` deg fingers-down about
# the gun's Y axis through grip_point(*pivot), then moved `offset` (gun-space
# mm): its heel on the bare left grip panel, its fingers over the strong
# fingers, its thumb forward under the strong thumb. `turn` is searched in
# `turns` for the straightest wrist; hand_pose's clear and wrap finish it.
SUPPORT = {"turns": (0.0, 10.0, 15.0, 20.0, 25.0), "yaws": (0.0, 15.0, 30.0, 45.0, 60.0),
           "swivels": (-45.0, -30.0, -15.0, 0.0, 15.0, 30.0, 45.0), "pivot": (40.0, 25.0),
           "offset": (20.0, 4.0, -30.0)}
WRIST_MAX = 15.0
WEB_GRIP = (3.0, 0.0)               # (t, u): where the web of the hand sits, under the tang (game socket)
HERO_NAME = "pistol_hero"
CONTACT = "pistol_contact"          # the soft-contact modifiers and vertex group
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


def knuckle_mid(arm, s):
    pb = arm.pose.bones
    return 0.5 * (pb[f"index_01_{s}"].head + pb[f"pinky_01_{s}"].head)


def socket_matrix(arm, s="r", sock=None):
    """Gun matrix in armature space for the posed hand s (before orient,
    straighten and seat)."""
    sock = sock or SOCKET
    w, f, t, back = hand_frame(arm, s)
    a = math.radians(sock["alpha"])
    X = f * math.cos(a) + t * math.sin(a)
    Z = -f * math.sin(a) + t * math.cos(a)
    Y = Z.cross(X)
    c = math.radians(sock.get("cant", 0.0))     # the hand rolled over the grip, thumb side to the gun's left
    Y, Z = Y * math.cos(c) + Z * math.sin(c), Z * math.cos(c) - Y * math.sin(c)
    y = math.radians(sock.get("yaw", 0.0))      # the wrist swung in behind the gun, the knuckles kept
    X, Y = X * math.cos(y) + Y * math.sin(y), Y * math.cos(y) - X * math.sin(y)
    R = Matrix((X, Y, Z)).transposed()
    tk, uk = sock["knuckles"]
    K = Vector(grip_point(tk, uk)) * MM
    return Matrix.Translation(knuckle_mid(arm, s) - R @ K) @ R.to_4x4()


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
    uncontact(arm)
    ob.hide_render = False
    ob.hide_viewport = False
    ob.parent = arm
    ob.parent_type = "BONE"
    ob.parent_bone = f"hand_{s}"
    bpy.context.view_layer.update()
    ob.matrix_world = arm.matrix_world @ socket_matrix(arm, s)
    bpy.context.view_layer.update()
    return ob


def bore(ob):
    return (ob.matrix_world.to_3x3() @ Vector((1, 0, 0))).normalized()


def wrist_bend(arm, s):
    """Wrist bend of hand s against its rest pose (deg; twist excluded)."""
    q = arm.pose.bones[f"hand_{s}"].matrix_basis.to_quaternion()
    y = q @ Vector((0.0, 1.0, 0.0))
    return math.degrees(math.acos(max(-1.0, min(1.0, y.y))))


def orient(arm, ob, s="r", pitch=None, along="target"):
    """Turn hand s about its wrist so the gun is level (`pitch` deg), upright
    (slide on top) and points (seen from above) at the target: the
    character's forward, armature -Y, the line the eyes are on in E's bladed
    ready (along="forearm": along the forearm; "bore": level it only)."""
    from character import hand_pose
    pitch = SOCKET["pitch"] if pitch is None else pitch
    mw = arm.matrix_world
    pb = arm.pose.bones
    if along == "forearm":
        fore = mw @ pb[f"hand_{s}"].head - mw @ pb[f"lowerarm_{s}"].head
    elif along == "bore":
        fore = bore(ob)
    else:
        fore = mw.to_3x3() @ Vector((0.0, -1.0, 0.0))
    h = Vector((fore.x, fore.y, 0.0)).normalized()
    p = math.radians(pitch)
    X = h * math.cos(p) + Vector((0.0, 0.0, math.sin(p)))
    Y = Vector((0.0, 0.0, 1.0)).cross(X).normalized()
    Z = X.cross(Y)
    RT = Matrix((X, Y, Z)).transposed()
    RS = ob.matrix_world.to_3x3().normalized()
    m3 = mw.to_3x3().normalized()
    D = m3.inverted() @ (RT @ RS.inverted()) @ m3
    hand_pose._rotate(arm, f"hand_{s}", D.to_quaternion())


def straighten(arm, s="r", reach_mm=90.0):
    """Move the wrist of hand s (two-bone IK, the hand keeps its world
    orientation) to the nearby spot where the wrist bends least: a coarse
    grid across the forearm, then a finer one. Returns (bend before, after,
    move mm)."""
    from character import hand_pose
    names = [f"upperarm_{s}", f"lowerarm_{s}", f"hand_{s}"]
    base = hand_pose._bases(arm, names)
    b0 = wrist_bend(arm, s)
    w, f, t, back = hand_frame(arm, s)

    def score(d):
        hand_pose._set_bases(arm, base)
        hand_pose.move_hand(arm, s, d)
        return wrist_bend(arm, s) + 0.04 * d.length / MM     # a little cost for moving the hand

    best = (score(Vector()), Vector())
    for step, n in ((reach_mm / 3.0, 3), (reach_mm / 12.0, 2)):
        centre = best[1].copy()
        for i in range(-n, n + 1):
            for j in range(-n, n + 1):
                for k in (-1, 0, 1):
                    d = centre + (t * i + back * j + f * k) * step * MM
                    sc = score(d)
                    if sc < best[0] - 1e-6:
                        best = (sc, d.copy())
    hand_pose._set_bases(arm, base)
    hand_pose.move_hand(arm, s, best[1])
    return b0, wrist_bend(arm, s), best[1].length / MM


def _local_bvh(ob):
    from mathutils.bvhtree import BVHTree
    me = ob.data
    co = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get("co", co)
    return BVHTree.FromPolygons([Vector(p) for p in co.reshape(-1, 3)], [tuple(p.vertices) for p in me.polygons],
                                epsilon=0.0)


def _depth(gun, pts_local):
    """Deepest point (mm) of pts (gun-local) inside the gun: >0 inside, <0
    the smallest gap outside (nearest surface, its normal decides)."""
    deep = -1e9
    for p in pts_local:
        loc, nrm, _, dist = gun.find_nearest(Vector(p), 0.015)
        if loc is None:                   # over 15 mm from the gun: outside (the sign test is
            continue                      # unreliable far off, where the nearest point is an edge)
        sgn = -1.0 if (Vector(p) - loc).dot(nrm) < 0 else 1.0
        deep = max(deep, -sgn * dist)
    return deep / MM


def seat(arm, ob, s="r", reach_mm=60.0):
    """Slide the gun along the palm normal (gun Y) until the palm skin's
    deepest point sits SOCKET['squash_mm'] inside the grip and the thenar
    pad's (the thumb root, which wraps the backstrap) SOCKET['thenar_mm']
    (bisection). Returns a log line."""
    from character import hand_pose
    gun = _local_bvh(ob)
    sc = hand_pose.Scene(arm, s)
    co = hand_pose._posed(sc.body)
    dom = hand_pose._dominant(sc.body)
    near = np.linalg.norm(co - np.array(sc.centre()[:]), axis=1) < sc.radius
    Mi = np.array(ob.matrix_world.inverted())
    parts = {}
    for key, bone, allow in (("palm", f"hand_{s}", SOCKET["squash_mm"]), ("thenar", f"thumb_01_{s}", SOCKET["thenar_mm"])):
        p = co[near & (dom == bone)]
        parts[key] = (p @ Mi[:3, :3].T + Mi[:3, 3], allow)
    M0 = ob.matrix_world.copy()
    R = M0.to_3x3()

    def excess(dy):           # the gun moved dy mm along its Y = the skin moved -dy
        sh = np.array((0.0, dy * MM, 0.0))
        return max(_depth(gun, p - sh) - allow for p, allow in parts.values())
    e0 = excess(0.0)
    lo, hi = -reach_mm, reach_mm          # the excess falls as dy grows (the gun leaves the palm)
    for _ in range(16):
        m = 0.5 * (lo + hi)
        if excess(m) > 0.0:
            lo = m
        else:
            hi = m
    dy = hi
    ob.matrix_world = Matrix.Translation(R @ Vector((0.0, dy * MM, 0.0))) @ M0
    bpy.context.view_layer.update()
    sh = np.array((0.0, dy * MM, 0.0))
    dd = {k: _depth(gun, p - sh) for k, (p, _) in parts.items()}
    return (f"seat: moved {dy:+.1f} mm along the palm normal (excess {e0:+.1f} mm at the socket); "
            f"palm {dd['palm']:+.1f} mm, thenar {dd['thenar']:+.1f} mm into the grip")


def support(arm, ob, s="l", strong="r", sup=None):
    """Put the support hand s on the gun: for each turn in SUPPORT['turns'],
    orient the hand (see SUPPORT) and move its wrist there (two-bone IK);
    keep the turn with the straightest wrist. Returns a log line."""
    from character import hand_pose
    from mathutils import Quaternion
    sup = sup or SUPPORT
    names = [f"upperarm_{s}", f"lowerarm_{s}", f"hand_{s}"]
    base = hand_pose._bases(arm, names)
    G = arm.matrix_world.inverted() @ ob.matrix_world          # gun -> armature space
    piv = Vector(grip_point(*sup["pivot"])) * MM
    w, f, t, back = hand_frame(arm, strong)
    best = None
    for turn, yaw in [(a, b) for a in sup["turns"] for b in sup["yaws"]]:
        hand_pose._set_bases(arm, base)
        Rq = (Quaternion(Vector((0, 0, 1)), math.radians(-yaw)).to_matrix().to_4x4()      # + = fingers to the gun's right
              @ Quaternion(Vector((0, 1, 0)), math.radians(turn)).to_matrix().to_4x4())   # + = fingers down
        local = (Matrix.Translation(Vector(sup["offset"]) * MM) @ Matrix.Translation(piv) @ Rq
                 @ Matrix.Translation(-piv) @ Matrix.Diagonal((1.0, -1.0, 1.0, 1.0)))
        T = G @ local @ G.inverted()
        T3 = T.to_3x3()
        tw, tf, tt, tb = T @ w, (T3 @ f).normalized(), (T3 @ t).normalized(), (T3 @ back).normalized()
        cw, cf, ct, cb = hand_frame(arm, s)
        Rd = Matrix((tf, tt, tb)).transposed() @ Matrix((cf, ct, cb)).transposed().inverted()
        pb = arm.pose.bones[f"hand_{s}"]
        h = pb.head.copy()
        pb.matrix = Matrix.Translation(h) @ Rd.to_4x4() @ Matrix.Translation(-h) @ pb.matrix
        bpy.context.view_layer.update()
        hand_pose.move_hand(arm, s, tw - pb.head)
        err = (pb.head - tw).length / MM
        placed = hand_pose._bases(arm, names)
        keep = pb.matrix.copy()
        for sw in sup.get("swivels", (0.0,)):
            hand_pose._set_bases(arm, placed)
            if sw:
                S = arm.pose.bones[names[0]].head
                hand_pose._rotate(arm, names[0], Quaternion((pb.head - S).normalized(), math.radians(sw)), pivot=S)
                pb.matrix = keep
                bpy.context.view_layer.update()
            bend = wrist_bend(arm, s)
            if best is None or bend + err < best[0]:
                best = (bend + err, (turn, yaw, sw), bend, err, hand_pose._bases(arm, names))
    hand_pose._set_bases(arm, best[4])
    return (f"support hand_{s}: turn {best[1][0]:.0f}, yaw {best[1][1]:.0f}, elbow swivel {best[1][2]:+.0f} deg, "
            f"wrist bend {best[2]:.1f} deg, IK error {best[3]:.1f} mm")


def hold(arm, s="r", rerun=None):
    """Spawn the gun on hand s's socket, level it, straighten the wrist and
    seat the palm (after the pose, before the hand settle). Returns (object,
    log lines)."""
    rerun = rerun or (lambda: None)
    ob = spawn(arm, s)
    b_auth = wrist_bend(arm, s)
    orient(arm, ob, s)                    # level, at the target
    b0, b1, mv = straighten(arm, s, SOCKET.get("reach_mm", 90.0))
    orient(arm, ob, s)                    # (move_hand keeps the hand's orientation: a no-op check)
    rerun()
    log = [f"pistol in hand_{s}: wrist bend {b_auth:.1f} deg authored, {b0:.1f} levelled, "
           f"{wrist_bend(arm, s):.1f} after moving the wrist {mv:.0f} mm",
           f"pistol in hand_{s}: " + seat(arm, ob, s)]
    return ob, log


def finish_hold(arm, ob, s="r", support_s=None, support_base=None, rerun=None):
    """After the strong hand's settle: the support hand onto the gun and
    settled on it (its own hand_pose pass, so it closes on the strong
    fingers as they are), the index and thumbs placed, then the soft contact
    (contact()). Returns log lines."""
    from character import hand_pose
    rerun = rerun or (lambda: None)
    log = []
    if support_s:
        log.append(support(arm, ob, support_s, s))
        rerun()
        log += hand_pose.settle(arm, (), rerun=rerun, spec={support_s: support_spec(support_base)})
    log += place_digits(arm, ob, s, support_s)
    rerun()
    log.append(contact(arm, ob))
    return log


# ---------------------------------------------------------------- soft contact
def _contact_meshes(arm):
    from character import hand_pose
    return [o for o in hand_pose._meshes(arm) if o.vertex_groups and "index_02_r" in o.vertex_groups]


def contact(arm, ob, offset_mm=0.2, near_mm=6.0):
    """Soft contact: hand skin (both hands, the nails) within `near_mm` of
    the gun that sits inside it (the palm's and thenar's squash, a finger
    pad) is pushed out onto its surface by a shrinkwrap (outside mode) right
    after the skin's armature. Skin further off is left out of the group:
    there the nearest-point inside test is unreliable. Returns a log line
    with the largest push."""
    from character import hand_pose
    uncontact(arm)
    gun = _local_bvh(ob)
    Mi = np.array(ob.matrix_world.inverted())
    hand_bones = ("hand",) + tuple(f"{d}_0{k}" for d in hand_pose.DIGITS for k in (1, 2, 3))
    worst, count = 0.0, 0
    for o in _contact_meshes(arm):
        before = hand_pose._posed(o)
        if before is None or len(before) != len(o.data.vertices):
            continue
        dom = hand_pose._dominant(o)
        loc = before @ Mi[:3, :3].T + Mi[:3, 3]
        idx = [i for i, d in enumerate(dom) if d and d[:-2] in hand_bones
               and gun.find_nearest(Vector(loc[i]), near_mm * MM)[0] is not None]
        if not idx:
            continue
        vg = o.vertex_groups.new(name=CONTACT)
        vg.add(idx, 1.0, "REPLACE")
        m = o.modifiers.new(CONTACT, "SHRINKWRAP")
        m.target = ob
        m.wrap_method = "NEAREST_SURFACEPOINT"
        m.wrap_mode = "OUTSIDE"
        m.offset = offset_mm * MM
        m.vertex_group = CONTACT
        arm_i = next((i for i, mm in enumerate(o.modifiers) if mm.type == "ARMATURE"), None)
        if arm_i is not None:
            o.modifiers.move(len(o.modifiers) - 1, arm_i + 1)
        bpy.context.view_layer.update()
        after = hand_pose._posed(o)
        moved = np.linalg.norm(after - before, axis=1)
        worst = max(worst, float(moved.max()) / MM)
        count += int((moved > 1e-5).sum())
    return f"contact: {count} hand skin vertices pushed out onto the gun, by up to {worst:.1f} mm"


def uncontact(arm=None):
    """Remove the soft-contact modifiers and groups (a pose without the gun)."""
    for o in bpy.data.objects:
        if o.type == "MESH":
            m = o.modifiers.get(CONTACT)
            if m is not None:
                o.modifiers.remove(m)
            g = o.vertex_groups.get(CONTACT)
            if g is not None:
                o.vertex_groups.remove(g)


def hide(name=HERO_NAME):
    ob = bpy.data.objects.get(name)
    if ob is not None:
        ob.hide_render = True
        ob.hide_viewport = True
    uncontact()


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
    "strong": ([((-4, 16, -28), (30, 20, -28), (62, 20, -26)), ((-8, 14, -30), (26, 20, -30), (58, 21, -28)),
                ((0, 18, -26), (34, 21, -26), (66, 21, -24)), ((-10, 10, -32), (22, 22, -32), (54, 23, -30))],
               (40, 21, -28), (8, 24, -29)),
    "support": ([((40, 34, -40), (70, 24, -38), (100, 21, -36)), ((36, 38, -44), (66, 26, -40), (96, 22, -38)),
                 ((44, 32, -36), (74, 24, -34), (104, 21, -32))], (126, 21, -37), (98, 22, -38)),
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
    """Triangles of digit d of hand s cutting into anything not of its own
    arm. The thumb counts from its MCP out (its root is the thenar pad,
    which may squash onto the backstrap, see seat / contact), plus its skin
    against the index's."""
    from character import hand_pose
    sc = hand_pose.Scene(arm, s)
    g = sc.build((d, "index") if d == "thumb" else (d,))
    if d != "thumb":
        return sc.hits(g[d], g["foreign"])
    co = hand_pose._posed(sc.body)
    dom = hand_pose._dominant(sc.body)
    th = hand_pose._bvh(co, hand_pose._polys(sc.body), np.isin(dom, [f"thumb_02_{s}", f"thumb_03_{s}"]))
    n = sc.hits(th, g["foreign"])
    if th is not None and g["index"] is not None:
        n += len(th.overlap(g["index"]))
    return n


def _thumb_fan(arm, ob, s, tip, radii=(10.0, 9.0, 8.0), n=24):
    """Seed chains from the thumb's own root (gun space mm): its MCP on a
    fan of points one metacarpal out, its IP on a fan one proximal phalanx
    beyond, the tip aimed at the mark; each bone sampled along its length
    must keep its skin radius (`radii`, mm) off the gun. Ranked by the tip's
    distance from the mark; returns up to n (MCP, IP, tip) chains."""
    from character import hand_pose
    names = hand_pose.digit_bones(s, "thumb")
    pb = arm.pose.bones
    Gi = (arm.matrix_world.inverted() @ ob.matrix_world).inverted()
    root = Gi @ pb[names[0]].head / MM
    L = [(pb[k].tail - pb[k].head).length / MM for k in names]
    gun = _local_bvh(ob)
    tipv = Vector(tip)

    def clear(a, b, r):
        for k in (0.35, 0.7, 1.0):
            q = a.lerp(b, k)
            if gun.find_nearest(q * MM, r * MM)[0] is not None:
                return False
        return True

    def fan(c, length, step):
        for el in range(-70, 71, step):
            for az in range(0, 360, step):
                e, a = math.radians(el), math.radians(az)
                yield c + Vector((math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e))) * length
    mcps = [m for m in fan(root, L[0], 10) if clear(root, m, radii[0])]
    mcps.sort(key=lambda m: (tipv - m).length)
    out = []
    for m in mcps[:40]:
        for ip in fan(m, L[1], 15):
            if not clear(m, ip, radii[1]):
                continue
            t = ip + (tipv - ip).normalized() * min(L[2], (tipv - ip).length)
            if not clear(ip, t, radii[2]):
                continue
            out.append(((t - tipv).length, (tuple(m), tuple(ip), tuple(t))))
    out.sort(key=lambda c: c[0])
    return [c for _, c in out[:n]]


def _solve_thumb(arm, ob, s, seeds, tip, ip=None, steps=(16.0, 8.0, 4.0, 2.0)):
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
    knuckle = None if ip is None else G @ (Vector(ip) * MM)
    pb = arm.pose.bones
    base = hand_pose._bases(arm, names)

    def cost():
        n = _digit_hits(arm, s, "thumb")
        d = (pb[names[2]].tail - goal).length / MM
        k = 0.0 if knuckle is None else 0.5 * (pb[names[2]].head - knuckle).length / MM
        return n * 1000.0 + d + k, n, d

    best = None
    fan = _thumb_fan(arm, ob, s, tip)
    for pts in list(seeds) + fan:
        hand_pose._set_bases(arm, base)
        _chain(arm, ob, s, "thumb", pts)
        c = cost()
        if best is None or c[0] < best[0][0]:
            best = (c, hand_pose._bases(arm, names))
    hand_pose._set_bases(arm, best[1])
    cur, evals = best[0], len(seeds) + len(fan)
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
    (WEB_GRIP, under the beavertail's tang), X along the bore, Z up the gun."""
    e = bpy.data.objects.new(name, None)
    e.empty_display_type = "ARROWS"
    e.empty_display_size = 0.03
    e.location = Vector(grip_point(*WEB_GRIP)) * MM
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
