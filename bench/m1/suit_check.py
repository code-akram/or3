"""Suit integrity check (bench/m1/suit.md §6): holes and open seams.

Two independent tests on a built GLB:

1. **Silhouette holes.** Render film-transparent silhouettes of the whole
   character (hair hidden) from a ring of directions plus above and below,
   flood-fill the background from the image border and count every enclosed
   background component left inside the silhouette. A see-through gap in the
   layered suit (an open armhole, a split seam) shows up as such a component
   whatever mesh is behind it. Components under `--min-px` are ignored (AA
   slivers between hair cards and the head). Existing harness masks
   (`RUN/<view>_mask.png`) can be checked with `--masks RUN`.
2. **Boundary edges.** For every suit mesh, the boundary edge loops (edges
   with one face), with length, centroid and extent. Intended openings are
   the hem, cuffs, front/lapel/collar edges, vents, pocket panels. For the
   jacket, a boundary edge inside the armhole zone (within `--armhole-m` of
   the segment from each shoulder joint down the arm) fails unless it rests on
   the jacket's own surface within `--seam-m` (the sleeve head sits on the
   block): an open edge there is a gap under the shoulder.

Silhouettes are rendered with the hair hidden; with `--masks` the harness
masks (hair on) are judged too, failing the body views only on components of
`--mask-min-px` or more (hair-card slivers are a few px) and reporting the
close-up.

    blender -b -t 4 --factory-startup --python bench/m1/suit_check.py -- \
        --glb RUN/character.glb --out-dir DIR [--masks RUN] [--res 512] [--min-px 3]

Writes DIR/check.json and DIR/sil_<view>.png; exits 1 on failure.
"""

import argparse
import json
import math
import os
import sys
from collections import deque

import bmesh
import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--glb", required=True)
ap.add_argument("--out-dir", required=True)
ap.add_argument("--masks", default="", help="harness run dir with <view>_mask.png to check too")
ap.add_argument("--res", type=int, default=512)
ap.add_argument("--min-px", type=int, default=3)
ap.add_argument("--mask-min-px", type=int, default=32, help="harness masks (hair on): failing component size")
ap.add_argument("--armhole-m", type=float, default=0.05)
ap.add_argument("--seam-m", type=float, default=0.006, help="a boundary this close to the mesh rests on it")
ap.add_argument("--no-render", action="store_true")
A = ap.parse_args(argv)
os.makedirs(A.out_dir, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=os.path.abspath(A.glb))
sc = bpy.context.scene
arm = next((o for o in sc.objects if o.type == "ARMATURE"), None)
meshes = [o for o in sc.objects if o.type == "MESH"]
report = {"glb": os.path.abspath(A.glb), "boundary": {}, "holes": {}, "fail": []}


# --- boundary loops --------------------------------------------------------------------------

def boundary_loops(ob):
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.transform(ob.matrix_world)
    edges = [e for e in bm.edges if len(e.link_faces) == 1]
    seen, loops = set(), []
    adj = {}
    for e in edges:
        for v in e.verts:
            adj.setdefault(v.index, []).append(e)
    for e in edges:
        if e.index in seen:
            continue
        comp, stack = [], [e]
        seen.add(e.index)
        while stack:
            x = stack.pop()
            comp.append(x)
            for v in x.verts:
                for y in adj[v.index]:
                    if y.index not in seen:
                        seen.add(y.index)
                        stack.append(y)
        pts = [v.co for x in comp for v in x.verts]
        c = sum(pts, Vector()) / len(pts)
        loops.append({"edges": len(comp), "length_m": round(sum(x.calc_length() for x in comp), 4),
                      "centroid": [round(c.x, 3), round(c.y, 3), round(c.z, 3)],
                      "min": [round(min(p[i] for p in pts), 3) for i in range(3)],
                      "max": [round(max(p[i] for p in pts), 3) for i in range(3)],
                      "_edges": comp})
    return bm, loops


def seg_dist(p, a, b):
    ab = b - a
    t = max(0.0, min(1.0, (p - a).dot(ab) / max(ab.length_squared, 1e-9)))
    return (p - (a + ab * t)).length


armholes = []
if arm is not None:
    for side in ("l", "r"):
        bn = arm.data.bones.get(f"upperarm_{side}")
        if bn is not None:
            S = arm.matrix_world @ bn.head_local
            T = (arm.matrix_world @ bn.tail_local - S).normalized()
            armholes.append((S, S + T * 0.13))

for ob in meshes:
    if "suit" not in ob.name:
        continue
    bm, loops = boundary_loops(ob)
    key = ob.name.split(".")[-1].replace("_export", "")
    bad, sewn = 0, 0
    if "jacket" in ob.name and armholes:
        # a boundary loop in the armhole zone is fine when it rests on the mesh's
        # own surface (the sleeve head sits on the block); open when it does not
        for L in loops:
            zone = [e for e in L["_edges"]
                    if any(seg_dist((e.verts[0].co + e.verts[1].co) / 2, a, b) < A.armhole_m
                           for a, b in armholes)]
            if not zone:
                continue
            lv = {v for e in L["_edges"] for v in e.verts}
            lf = {f for v in lv for f in v.link_faces}
            tmp = bmesh.new()
            vm = {}
            for f in bm.faces:
                if f in lf:
                    continue
                vs = []
                for v in f.verts:
                    if v not in vm:
                        vm[v] = tmp.verts.new(v.co)
                    vs.append(vm[v])
                tmp.faces.new(vs)
            tree = BVHTree.FromBMesh(tmp) if tmp.faces else None
            for e in zone:
                p = (e.verts[0].co + e.verts[1].co) / 2
                hit = tree.find_nearest(p, A.seam_m) if tree else None
                if hit and hit[0] is not None:
                    sewn += 1
                else:
                    bad += 1
                    far = tree.find_nearest(p, 0.1) if tree else None
                    report.setdefault("open_edges", []).append(
                        {"mesh": key, "at": [round(c, 3) for c in p],
                         "gap_mm": round(1000 * (p - far[0]).length, 1) if far and far[0] else None,
                         "loop_len_m": L["length_m"]})
            tmp.free()
    for L in loops:
        del L["_edges"]
    loops.sort(key=lambda d: -d["length_m"])
    report["boundary"][key] = {"loops": len(loops), "armhole_edges_open": bad,
                               "armhole_edges_resting": sewn, "detail": loops[:12]}
    if bad:
        report["fail"].append(f"{key}: {bad} open boundary edges in the armhole zone")
    bm.free()


# --- silhouette holes ------------------------------------------------------------------------

def enclosed_background(mask):
    """Connected background components not reachable from the image border:
    [(pixels, x0, y0, x1, y1)], largest first."""
    h, w = mask.shape
    bg = ~mask
    reach = np.zeros_like(mask)
    q = deque()
    for y in range(h):
        for x in (0, w - 1):
            if bg[y, x] and not reach[y, x]:
                reach[y, x] = True
                q.append((y, x))
    for x in range(w):
        for y in (0, h - 1):
            if bg[y, x] and not reach[y, x]:
                reach[y, x] = True
                q.append((y, x))
    while q:
        y, x = q.popleft()
        for yy, xx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
            if 0 <= yy < h and 0 <= xx < w and bg[yy, xx] and not reach[yy, xx]:
                reach[yy, xx] = True
                q.append((yy, xx))
    holes = bg & ~reach
    comps = []
    lab = np.zeros_like(mask)
    ys, xs = np.nonzero(holes)
    for y0, x0 in zip(ys, xs):
        if lab[y0, x0]:
            continue
        lab[y0, x0] = True
        q.append((y0, x0))
        n, bx0, by0, bx1, by1 = 0, x0, y0, x0, y0
        while q:
            y, x = q.popleft()
            n += 1
            bx0, by0, bx1, by1 = min(bx0, x), min(by0, y), max(bx1, x), max(by1, y)
            for yy, xx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                if 0 <= yy < h and 0 <= xx < w and holes[yy, xx] and not lab[yy, xx]:
                    lab[yy, xx] = True
                    q.append((yy, xx))
        comps.append((n, int(bx0), int(by0), int(bx1), int(by1)))
    comps.sort(reverse=True)
    return comps


def load_mask(path, channel):
    img = bpy.data.images.load(path, check_existing=False)
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    bpy.data.images.remove(img)
    return px.reshape(h, w, 4)[::-1, :, channel] > 0.5   # top row first


def judge(name, mask, z_of_row=None):
    """z_of_row(y) maps an image row to world z for eye-level views: components
    entirely above the suit (the ear's helix gap, hair) are not the suit's."""
    comps = [c for c in enclosed_background(mask) if c[0] >= A.min_px]
    # the shoe arch (between heel block and sole) is a real see-through at the
    # ground: ignore components in the lowest 2 % of the silhouette
    rows = np.nonzero(mask.any(axis=1))[0]
    ground = rows.max() - 0.02 * (rows.max() - rows.min()) if len(rows) else -1
    skipped = [c for c in comps if c[4] >= ground]
    comps = [c for c in comps if c[4] < ground]
    zs_b = []
    if z_of_row is not None:
        zs_b = [round(z_of_row(c[4]), 3) for c in comps]
        keep = [c for c in comps if z_of_row(c[4]) <= suit_top + 0.01]
        skipped += [c for c in comps if c not in keep]
        comps = keep
    report["holes"][name] = {"components": len(comps), "pixels": sum(c[0] for c in comps),
                             "bbox_px": [c[1:] for c in comps[:8]], "z_bottom": zs_b[:8],
                             "ignored": [c[1:] for c in skipped[:8]]}
    if comps:
        report["fail"].append(f"{name}: {len(comps)} enclosed background component(s), "
                              f"{sum(c[0] for c in comps)} px, largest at {comps[0][1:]}")


if A.masks:
    # harness masks include the hair: slivers between hair cards (a few px at
    # the head) are not the suit's, so only components >= --mask-min-px fail
    # the body views; the close-up frames the head and is reported only
    for v in ("front", "three_quarter", "profile", "closeup"):
        p = os.path.join(A.masks, f"{v}_mask.png")
        if not os.path.exists(p):
            continue
        comps = [c for c in enclosed_background(load_mask(p, 0)) if c[0] >= A.min_px]
        big = [c for c in comps if c[0] >= A.mask_min_px]
        report["holes"][f"mask.{v}"] = {"components": len(comps), "pixels": sum(c[0] for c in comps),
                                        "bbox_px": [c[1:] for c in comps[:8]],
                                        "failing": len(big) if v != "closeup" else 0}
        if big and v != "closeup":
            report["fail"].append(f"mask.{v}: {len(big)} enclosed background component(s) >= "
                                  f"{A.mask_min_px} px, largest at {big[0][1:]}")

if not A.no_render:
    for o in meshes:
        if any(k in o.name for k in ("hair", "beard", "brows", "eyelash")):
            o.hide_render = True
    sc.render.engine = "BLENDER_EEVEE"
    sc.eevee.taa_render_samples = 1
    sc.render.resolution_x = sc.render.resolution_y = A.res
    sc.render.film_transparent = True
    sc.render.image_settings.color_mode = "RGBA"
    cd = bpy.data.cameras.new("sil")
    cd.type = "ORTHO"
    cam = bpy.data.objects.new("sil", cd)
    sc.collection.objects.link(cam)
    sc.camera = cam
    zs = [(o.matrix_world @ v.co).z for o in meshes if not o.hide_render
          and ("suit" in o.name or o.name.startswith("Human_export")) for v in o.data.vertices]
    z_mid = 0.5 * (min(zs) + max(zs))
    frame = (max(zs) - min(zs)) * 1.05
    suit_top = max((o.matrix_world @ v.co).z for o in meshes if "suit" in o.name for v in o.data.vertices)
    report["suit_top_z"] = round(suit_top, 3)
    # (name, azimuth deg, elevation deg, target z, ortho size)
    views = [("front", 0, 0, z_mid, frame), ("back", 180, 0, z_mid, frame),
             ("left", 90, 0, z_mid, frame), ("right", -90, 0, z_mid, frame),
             ("q_fl", 40, 0, z_mid, frame), ("q_fr", -40, 0, z_mid, frame),
             ("q_bl", 140, 0, z_mid, frame), ("q_br", -140, 0, z_mid, frame),
             ("above_front", 0, 45, z_mid, frame), ("above_back", 180, 45, z_mid, frame),
             ("below_front", 0, -30, z_mid, frame), ("below_back", 180, -30, z_mid, frame),
             ("torso_front", 0, 0, max(zs) - 0.35, 0.8), ("torso_back", 180, 0, max(zs) - 0.35, 0.8),
             ("torso_above", 0, 60, max(zs) - 0.25, 0.8)]
    for name, az, el, tz, size in views:
        a, e = math.radians(az), math.radians(el)
        tgt = Vector((0, 0, tz))
        cam.location = tgt + Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e))) * 4.0
        cam.rotation_euler = (tgt - cam.location).to_track_quat("-Z", "Y").to_euler()
        cd.ortho_scale = size
        path = os.path.join(A.out_dir, f"sil_{name}.png")
        sc.render.filepath = path
        bpy.ops.render.render(write_still=True)
        z_of_row = (lambda y, tz=tz, size=size: tz + (0.5 - y / A.res) * size) if el == 0 else None
        judge(f"sil.{name}", load_mask(path, 3), z_of_row)

report["ok"] = not report["fail"]
with open(os.path.join(A.out_dir, "check.json"), "w") as f:
    json.dump(report, f, indent=1)
for k, v in report["boundary"].items():
    print(f"[suit_check] {k:10s} boundary loops {v['loops']:3d}  armhole edges open {v['armhole_edges_open']}"
          f" resting {v['armhole_edges_resting']}")
for k, v in report["holes"].items():
    n = v.get("failing", v["components"])
    flag = "HOLE" if n else ("hair" if v["components"] else "ok  ")
    print(f"[suit_check] {flag} {k:18s} components {v['components']:2d} px {v['pixels']:5d} {v['bbox_px'][:3]}")
print("[suit_check] " + ("PASS" if report["ok"] else "FAIL: " + "; ".join(report["fail"])))
sys.exit(0 if report["ok"] else 1)
