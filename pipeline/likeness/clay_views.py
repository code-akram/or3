"""Measurement renders of a built character, and a landmark embedding on its base mesh (Blender).

render mode: open a kept character.blend, hide what the caller names (hair, beard, brows...),
optionally swap to the clay material (eyes keep theirs, so a landmarker finds the irises), and
render views under the 5,600 K turntable light with exact pinhole cameras; writes the PNGs and
cameras.json (OpenCV K and world-to-camera per view).

    blender -b -t 3 --factory-startup --python-exit-code 1 --python clay_views.py -- \
        render --in RUN/character.blend --out DIR --views "front:0,6;tq:35,4;profile:80,2" \
        [--lens 85 --frame 0.32 --res 1024 --samples 48 --hide hair,beard,brows --clay]

embed mode: cast each view's 2D landmarks (refboard.py measure --out-dir) onto the head surface,
combine the views (most frontal hit, consistent hits averaged) and express every landmark on the
base mesh dumped by the build (head_fan dump_base) as a triangle + barycentric coordinates.

    blender -b ... --python clay_views.py -- embed --in RUN/character.blend --views-dir DIR \
        --landmarks LM_DIR --base base.npz --out embedding.npz

Azimuth follows blender/hero/rig.py: 0 is in front, positive shows the character's left side.
"""

import argparse
import json
import os
import sys

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import barycentric_transform, intersect_point_tri

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "blender", "hero"))
sys.path.insert(0, os.path.join(HERE, "..", "..", "blender"))
sys.path.append(HERE)
import containment  # noqa: E402
import rig  # noqa: E402


def parse_views(spec):
    out = []
    for part in spec.split(";"):
        if not part.strip():
            continue
        name, vals = part.split(":")
        az, el = (float(x) for x in vals.split(","))
        out.append((name.strip(), az, el))
    return out


def head_object():
    return max((o for o in bpy.context.scene.objects if o.type == "MESH" and o.name.startswith("Human")
                and "export" in o.name and "." not in o.name), key=lambda o: len(o.data.vertices))


def opencv_camera(cam_obj, res):
    """OpenCV intrinsics/extrinsics of the camera for the image actually written (the render
    resolution percentage applied)."""
    pct = bpy.context.scene.render.resolution_percentage / 100.0
    res = (round(res[0] * pct), round(res[1] * pct))
    cd = cam_obj.data
    f = cd.lens / cd.sensor_height * res[1]          # vertical sensor fit
    K = [[f, 0.0, res[0] / 2.0], [0.0, f, res[1] / 2.0], [0.0, 0.0, 1.0]]
    w2c = np.array(cam_obj.matrix_world.inverted())
    w2c = np.diag([1.0, -1.0, -1.0, 1.0]) @ w2c     # Blender camera (-Z forward, +Y up) -> OpenCV
    return {"K": K, "world_to_cam": w2c.tolist(), "res": list(res), "lens_mm": cd.lens,
            "location": list(cam_obj.location)}


def cmd_render(a):
    rig.PCT = 100                                    # the measurement image is the full resolution
    ch = rig.load_character(a.inp)
    rig.pose(ch, "rest")
    hide = [h for h in a.hide.split(",") if h]
    for o in list(ch.objs):
        if any(h in o.name.lower() for h in hide):
            o.hide_render = True
            ch.objs.remove(o)
    os.makedirs(a.out, exist_ok=True)
    cams = {}
    res = (a.res, a.res)
    for name, az, el in parse_views(a.views):
        for c in ("tt_rig", "hero_cams"):
            rig.collection(c)
        cam = rig.camera(ch, f"az={az:g},el={el:g},lens={a.lens:g},aim=eyes,frame={a.frame:g}", dof=False)
        rig.world((0.05, 0.05, 0.05), 1.0)
        rig.turntable_rig(ch, cam)
        rig.cycles("preview", res, a.samples)
        vs = bpy.context.scene.view_settings
        vs.exposure = rig.TT_EXPOSURE + a.exposure
        vs.look = "None"
        restore = None
        if a.clay:
            eye_keep = [(o, i, s.material) for o in ch.objs if "eye" in o.name.lower() and "lash" not in o.name.lower()
                        for i, s in enumerate(o.material_slots)]
            restore = rig.material_pass(ch, "clay")
            for o, i, m in eye_keep:
                o.material_slots[i].material = m
        path = os.path.join(a.out, f"{name}.png")
        secs = rig.render(path)
        if restore:
            restore()
        cams[name] = dict(opencv_camera(cam["obj"], res), az=az, el=el, seconds=secs, file=f"{name}.png")
        print(f"[clay] {name}: az {az:g} el {el:g} lens {a.lens:g} -> {path} ({secs} s)", flush=True)
    with open(os.path.join(a.out, "cameras.json"), "w") as f:
        json.dump({"in": os.path.abspath(a.inp), "hidden": hide, "clay": a.clay, "frame_h_m": a.frame,
                   "views": cams}, f, indent=1)


# ----------------------------------------------------------------------------------- embedding
def world_bvh(obj):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    mw = obj.matrix_world
    verts = [mw @ v.co for v in me.vertices]
    polys = [tuple(p.vertices) for p in me.polygons]
    ev.to_mesh_clear()
    return BVHTree.FromPolygons(verts, polys), verts


def base_mesh(path):
    d = np.load(path)
    co = d["co"]
    names = [str(n) for n in d["group_names"]]
    W = d["group_weights"].astype(np.float32)
    helper = W[:, names.index("HelperGeometry")] > 0
    lv, ls, lt = d["loop_verts"], d["poly_start"], d["poly_total"]
    polys = [tuple(int(x) for x in lv[s:s + t]) for s, t in zip(ls, lt)]
    polys = [p for p in polys if not helper[list(p)].any()]   # skin only
    return co, polys, BVHTree.FromPolygons([Vector(c) for c in co], polys)


def to_triangle(co, poly, p):
    """Triangle of polygon `poly` (fan) containing the point p, with barycentric coordinates."""
    best = None
    for k in range(1, len(poly) - 1):
        tri = (poly[0], poly[k], poly[k + 1])
        A, B, C = (Vector(co[i]) for i in tri)
        q = intersect_point_tri(p, A, B, C)
        q = q if q is not None else p
        w = np.array(barycentric_transform(q, A, B, C, Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))))
        err = (-np.minimum(w, 0)).sum()
        if best is None or err < best[2]:
            best = (tri, np.clip(w, 0, None) / max(np.clip(w, 0, None).sum(), 1e-9), err)
    return best[0], best[1]


def triangulate(rays, p0, iters=5):
    """Point nearest to a bundle of rays (origin, unit direction), iteratively reweighted
    (Cauchy) so a view whose landmark disagrees counts less. Returns the point and the weighted
    rms distance to the rays."""
    p = np.asarray(p0, np.float64)
    O = np.array([r[0] for r in rays])
    D = np.array([r[1] for r in rays])
    w = np.ones(len(rays))
    for _ in range(iters):
        A = np.zeros((3, 3))
        b = np.zeros(3)
        for o, d, wi in zip(O, D, w):
            Pm = np.eye(3) - np.outer(d, d)
            A += wi * Pm
            b += wi * Pm @ o
        p = np.linalg.solve(A, b)
        r = np.array([np.linalg.norm((np.eye(3) - np.outer(d, d)) @ (p - o)) for o, d in zip(O, D)])
        w = 1.0 / (1.0 + (r / 0.002) ** 2)
    return p, float(np.sqrt((w * r ** 2).sum() / w.sum()))


def cmd_embed(a):
    bpy.ops.wm.open_mainfile(filepath=os.path.abspath(a.inp))
    arm = next((o for o in bpy.context.scene.objects if o.type == "ARMATURE"), None)
    if arm is not None:
        for pb in arm.pose.bones:
            pb.matrix_basis.identity()
    bpy.context.view_layer.update()
    head = head_object()
    bvh, _ = world_bvh(head)
    cams = json.load(open(os.path.join(a.views_dir, "cameras.json")))["views"]
    hits = {}                                         # mp index -> [(point, frontality, view)]
    rays = {}                                         # mp index -> [(origin, direction)]
    for name, c in cams.items():
        lp = os.path.join(a.landmarks, f"{name}_lm.npy")
        if not os.path.exists(lp):
            print(f"[embed] no landmarks for {name}", flush=True)
            continue
        lm = np.load(lp)
        K = np.array(c["K"])
        w2c = np.array(c["world_to_cam"])
        c2w = np.linalg.inv(w2c)
        origin = Vector(c2w[:3, 3])
        for i, (u, v) in enumerate(lm[:, :2]):
            d_cam = np.array([(u - K[0, 2]) / K[0, 0], (v - K[1, 2]) / K[1, 1], 1.0])
            d = Vector(c2w[:3, :3] @ d_cam).normalized()
            rays.setdefault(i, []).append((np.array(origin), np.array(d)))
            loc, nrm, _, dist = bvh.ray_cast(origin, d)
            if loc is None:
                continue
            fr = -nrm.dot(d)
            if fr > 0.2:
                hits.setdefault(i, []).append((np.array(loc), fr, name))
    co, polys, bbvh = base_mesh(a.base)
    # are the built head and the base mesh in the same space? (refine offsets are ~1 mm)
    head_ids = np.where(co[:, 2] > co[:, 2].max() - 0.25)[0][::7]
    gaps = [bvh.find_nearest(Vector(co[i]))[3] for i in head_ids]
    gaps = np.array([g for g in gaps if g is not None])
    n = 478
    tri = np.zeros((n, 3), np.int64)
    bary = np.zeros((n, 3))
    valid = np.zeros(n, bool)
    front = np.zeros(n)
    nviews = np.zeros(n, np.int64)
    off = np.full(n, np.nan)
    tri_res = np.full(n, np.nan)
    for i, hs in hits.items():
        best = max(hs, key=lambda h: h[1])
        near = [h for h in hs if np.linalg.norm(h[0] - best[0]) < a.consistent_mm / 1000.0]
        w = np.array([h[1] ** 2 for h in near])
        p = (np.stack([h[0] for h in near]) * w[:, None]).sum(0) / w.sum()
        if len(rays.get(i, ())) >= 3:
            # triangulate the landmark from every view's ray (robust to grazing rays at lid and lip
            # lines, where a surface hit can land inside the socket or the mouth), start at the hit
            q, rr = triangulate(rays[i], p)
            if rr < a.tri_max_mm / 1000.0:
                p, tri_res[i] = q, rr
        loc, _, fidx, dist = bbvh.find_nearest(Vector(p))
        if loc is None:
            continue
        t, b = to_triangle(co, polys[fidx], loc)
        # trusted: triangulated, or a surface hit that several views agree on
        tri[i], bary[i], valid[i] = t, b, bool(np.isfinite(tri_res[i]) or len(near) >= 3)
        front[i], nviews[i], off[i] = best[1], len(near), dist
    np.savez(a.out, mp_index=np.arange(n), tri_verts=tri, bary=bary, valid=valid, frontality=front,
             n_views=nviews, offset_m=off, triangulation_rms_m=tri_res)
    print(f"[embed] {valid.sum()} of {n} landmarks embedded; built-head vs base median gap "
          f"{np.median(gaps) * 1000:.2f} mm (p95 {np.percentile(gaps, 95) * 1000:.2f}); landmark-to-base offset "
          f"median {np.nanmedian(off) * 1000:.2f} mm, max {np.nanmax(off) * 1000:.2f} mm; triangulated "
          f"{int(np.isfinite(tri_res).sum())} (ray rms median {np.nanmedian(tri_res) * 1000:.2f} mm)", flush=True)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(prog="clay_views.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render")
    r.add_argument("--in", dest="inp", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--views", default="front:0,6;tq:35,4;profile:80,2", help="name:azimuth,elevation;...")
    r.add_argument("--lens", type=float, default=85.0)
    r.add_argument("--frame", type=float, default=0.32, help="frame height at the eyes, metres")
    r.add_argument("--res", type=int, default=1024)
    r.add_argument("--samples", type=int, default=48)
    r.add_argument("--exposure", type=float, default=0.0)
    r.add_argument("--hide", default="hair,beard", help="comma-separated name substrings to hide")
    r.add_argument("--clay", action="store_true")
    e = sub.add_parser("embed")
    e.add_argument("--in", dest="inp", required=True)
    e.add_argument("--views-dir", required=True)
    e.add_argument("--landmarks", required=True)
    e.add_argument("--base", required=True)
    e.add_argument("--out", required=True)
    e.add_argument("--consistent-mm", type=float, default=4.0)
    e.add_argument("--tri-max-mm", type=float, default=3.0, help="use the triangulated point when its ray rms is below")
    a = ap.parse_args(argv)
    containment.assert_outputs(a, "out")
    {"render": cmd_render, "embed": cmd_embed}[a.cmd](a)


main()
