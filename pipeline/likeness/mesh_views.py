"""Landmarker views of a bare head mesh (Blender, Workbench, CPU): the public identity prep of
author_public.py. Renders a triangle mesh with clay skin, off-white sclera and a dark iris from a
few fixed views, and writes the PNGs plus cameras.json (OpenCV K and world-to-camera per view,
the clay_views.py format), so 2D landmarks found on them (refboard.py measure) can be cast back
onto the mesh (author_public.py embed).

    blender -b -t 3 --factory-startup --python-exit-code 1 --python mesh_views.py -- \
        --mesh mesh.npz --out DIR [--res 768] [--views "front:0,4;l30:30,4;r30:-30,4"]

mesh.npz: V (n, 3) metres, z up, -y forward; F (m, 3) triangles; part (m,) 0 skin, 1 sclera,
2 iris, 3 hidden; centre (3,) the point the cameras aim at.

Inputs must be public (no private/ path): this tool exists for the public face only.
"""

import argparse
import json
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Vector

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import containment  # noqa: E402

COLOURS = {0: (0.60, 0.50, 0.45, 1), 1: (0.85, 0.83, 0.80, 1), 2: (0.06, 0.04, 0.03, 1)}


def parse_views(spec):
    out = []
    for part in spec.split(";"):
        if part.strip():
            name, vals = part.split(":")
            az, el = (float(x) for x in vals.split(","))
            out.append((name.strip(), az, el))
    return out


def opencv_camera(cam, res):
    cd = cam.data
    f = cd.lens / cd.sensor_height * res
    w2c = np.diag([1.0, -1.0, -1.0, 1.0]) @ np.array(cam.matrix_world.inverted())
    return {"K": [[f, 0.0, res / 2.0], [0.0, f, res / 2.0], [0.0, 0.0, 1.0]], "world_to_cam": w2c.tolist(),
            "res": [res, res], "lens_mm": cd.lens, "location": list(cam.location)}


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(prog="mesh_views.py")
    ap.add_argument("--mesh", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--res", type=int, default=768)
    ap.add_argument("--lens", type=float, default=85.0)
    ap.add_argument("--frame", type=float, default=0.26, help="frame height at the centre, metres")
    ap.add_argument("--views", default="front:0,4;l30:30,4;r30:-30,4")
    a = ap.parse_args(argv)
    if containment.is_private(a.mesh) or containment.is_private(a.out):
        raise SystemExit("mesh_views.py: public meshes only (refusing a private/ path)")
    d = np.load(a.mesh)
    V, F, part, centre = d["V"], d["F"], d["part"], Vector(d["centre"])
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    keep = part != 3
    me = bpy.data.meshes.new("head")
    me.from_pydata(V.tolist(), [], F[keep].tolist())
    mats = {}
    for k, c in COLOURS.items():
        m = bpy.data.materials.new(f"part{k}")
        m.diffuse_color = c
        me.materials.append(m)
        mats[k] = len(me.materials) - 1
    me.polygons.foreach_set("material_index", np.array([mats[int(p)] for p in part[keep]], np.int32))
    me.polygons.foreach_set("use_smooth", np.ones(int(keep.sum()), bool))
    me.update()
    ob = bpy.data.objects.new("head", me)
    sc = bpy.context.scene
    sc.collection.objects.link(ob)
    sc.render.engine = "BLENDER_WORKBENCH"
    sh = sc.display.shading
    sh.light = "STUDIO"
    sh.color_type = "MATERIAL"
    sh.show_shadows = False
    sh.show_cavity = False
    sc.view_settings.view_transform = "Standard"
    sc.render.resolution_x = sc.render.resolution_y = a.res
    sc.render.resolution_percentage = 100
    cd = bpy.data.cameras.new("cam")
    cd.lens = a.lens
    cd.sensor_fit = "VERTICAL"
    cam = bpy.data.objects.new("cam", cd)
    sc.collection.objects.link(cam)
    sc.camera = cam
    dist = a.frame / 2 / math.tan(math.atan(cd.sensor_height / 2 / cd.lens))
    os.makedirs(a.out, exist_ok=True)
    cams = {}
    for name, az, el in parse_views(a.views):
        th, ph = math.radians(az), math.radians(el)
        dv = Vector((math.sin(th) * math.cos(ph), -math.cos(th) * math.cos(ph), math.sin(ph)))
        cam.location = centre + dv * dist
        cam.rotation_euler = (-dv).to_track_quat("-Z", "Y").to_euler()
        bpy.context.view_layer.update()
        sc.render.filepath = os.path.join(a.out, f"{name}.png")
        bpy.ops.render.render(write_still=True)
        cams[name] = dict(opencv_camera(cam, a.res), az=az, el=el, file=f"{name}.png")
    with open(os.path.join(a.out, "cameras.json"), "w") as f:
        json.dump({"mesh": os.path.abspath(a.mesh), "views": cams}, f, indent=1)
    print(f"[mesh_views] {len(cams)} views -> {a.out}")


main()
