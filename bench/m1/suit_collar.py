"""Collar-zone guard (bench/m1/suit.md §6): the shirt collar, tie knot, jacket
collar, gorge, notch and lapel roll, judged from the harness close-up camera.

Two independent tests on a built GLB (hair, beard, brows and lashes hidden:
they hide defects, they do not fix them):

1. **Ray-cast ID images** from the exact harness close-up camera
   (lookdev_render.py: head bone midpoint - 3 cm, azimuth 25 deg, 85 mm,
   0.42 m frame) and three collar crops (front, 3/4 at 40 deg, profile).
   Every pixel is a ray against all meshes: which mesh, which side of the
   face. Counted in the collar zone (within 12 cm of the neck axis, from 8 cm
   under the suprasternale up to the collar tops):
     * skin_px: body pixels below the shirt band's top edge at that azimuth
       round the neck with no shirt straight out from the neck axis in front
       of them: bare skin showing through or between the collar pieces
       (gated);
     * neck_inside_px: the same but with the shirt band radially in front:
       the neck inside the band, seen down through the collar's opening
       (reported, not gated: a collar stands a few mm off the neck);
     * backface_px: garment pixels where the camera sees the back of a face
       (folded or flipped strips, the inside of a collar where it should not
       show).
   Writes id_<view>.png: body tan, bare skin green, neck inside the band
   teal, shirt white, jacket blue, tie red, waistcoat purple, backfaces
   magenta. skin_at / back_at in collar.json say where (azimuth round the
   neck, 0 = front, 90 = wearer's left; height over the suprasternale).
2. **Geometry** in the neck zone: triangle-triangle intersections of each
   garment with itself (excluding faces that share a vertex) and between
   layers (body/shirt, body/jacket, shirt/jacket, tie/jacket, tie/shirt), and
   a radial ordering test: rays from the neck axis outward must meet body,
   then shirt, then jacket, never a shirt after the jacket. The tie's own
   intersections are not gated (the blade's top is tucked into the knot by
   construction), nor body/shirt (reported). "where" histograms and, for a
   SUIT_DEBUG_TAGS build, per-panel pairs (self.jacket.mat) locate the rest.

Gates (regression limits, bench/m1/suit.md §6): bare skin 0 in every view;
backfaces <= --max-back per view (the inside of the band and the turned
collar edge show legitimately); gated intersections <= --max-isect; radial
order violations 0.

    blender -b --factory-startup --python bench/m1/suit_collar.py -- \
        --glb RUN/character.glb --out-dir DIR [--res 384] [--wire] [--beauty]
        [--beauty-res 640] [--show jacket,shirt] [--hair]

--beauty / --wire also render the harness close-up eye point zoomed onto the
collar (closeup_zoom, closeup_wide, closeup_far: the far side).

Writes DIR/collar.json, DIR/id_*.png (and wire_*.png / beauty_*.png); exit 1
when a gated count exceeds its limit (--max-skin, --max-back, --max-isect).
"""

import argparse
import json
import math
import os
import sys

import bmesh
import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--glb", required=True)
ap.add_argument("--out-dir", required=True)
ap.add_argument("--res", type=int, default=384)
ap.add_argument("--wire", action="store_true", help="also EEVEE renders with a wire overlay")
ap.add_argument("--beauty", action="store_true", help="also EEVEE beauty renders of the views")
ap.add_argument("--beauty-res", type=int, default=0, help="resolution of the EEVEE renders (default --res)")
ap.add_argument("--show", default="", help="comma list of kinds to keep in the EEVEE renders (body,shirt,jacket,tie)")
ap.add_argument("--hair", action="store_true", help="keep hair/beard visible in the renders")
ap.add_argument("--max-skin", type=int, default=0)
ap.add_argument("--skin-tol", type=float, default=0.004, help="skin this far under the collar top edge counts")
ap.add_argument("--max-back", type=int, default=350)
ap.add_argument("--max-isect", type=int, default=120)
A = ap.parse_args(argv)
os.makedirs(A.out_dir, exist_ok=True)

HIDE = ("hair", "beard", "brows", "eyelash")
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=os.path.abspath(A.glb))
sc = bpy.context.scene
arm = next(o for o in sc.objects if o.type == "ARMATURE")
meshes = [o for o in sc.objects if o.type == "MESH" and o.parent == arm]
for o in sc.objects:
    if o.type == "MESH" and o not in meshes:
        o.hide_render = True


def kind(o):
    n = o.name
    if n.startswith("Human_export"):
        return "body"
    for k in ("jacket", "shirt", "tie", "waistcoat", "buttons", "trousers", "shoes"):
        if f"suit_{k}" in n:
            return k
    for k in HIDE:
        if k in n:
            return "hair"
    return "other"


mw = arm.matrix_world
bones = arm.data.bones
head = mw @ ((bones["head"].head_local + bones["head"].tail_local) * 0.5)
neck = mw @ bones["neck_01"].head_local
neck_top = mw @ bones["neck_01"].tail_local
supra = (mw @ bones["clavicle_l"].head_local).z
report = {"glb": os.path.abspath(A.glb), "fail": []}


def world_bm(o, weld=True):
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bm.transform(o.matrix_world)
    if weld:
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    return bm


def axis_xy(z):
    """The neck axis (neck_01 head -> tail, extended) at height z."""
    d = neck_top - neck
    t = (z - neck.z) / d.z if abs(d.z) > 1e-6 else 0.0
    return neck + d * t


def in_zone(p, r=0.12):
    if not (supra - 0.08 <= p.z <= supra + 0.13):
        return False
    c = axis_xy(p.z)
    return math.hypot(p.x - c.x, p.y - c.y) < r


kinds = {o.name: kind(o) for o in meshes}
BMS = {o.name: world_bm(o) for o in meshes if kinds[o.name] not in ("hair", "other")
       or (A.hair and kinds[o.name] == "hair")}

# --- the shirt band's top edge per azimuth round the neck -----------------------------------
shirt = next(o for o in meshes if kinds[o.name] == "shirt")
NB = 180
band_top = np.full(NB, -1.0)
for v in BMS[shirt.name].verts:
    p = v.co
    if not in_zone(p, 0.11) or p.z < supra - 0.02:
        continue
    c = axis_xy(p.z)
    b = int(((math.atan2(p.y - c.y, p.x - c.x) + math.pi) / (2 * math.pi)) * NB) % NB
    band_top[b] = max(band_top[b], p.z)
for b in range(NB):   # fill gaps (the open front) from the neighbours
    if band_top[b] < 0:
        nb = [band_top[(b + k) % NB] for k in (-3, -2, -1, 1, 2, 3) if band_top[(b + k) % NB] > 0]
        band_top[b] = max(nb) if nb else supra + 0.05
report["band_top_z"] = {"min": round(float(band_top.min()), 4), "max": round(float(band_top.max()), 4)}


def band_top_at(p):
    """The shirt collar's top edge height at p's azimuth (interpolated bins)."""
    c = axis_xy(p.z)
    x = ((math.atan2(p.y - c.y, p.x - c.x) + math.pi) / (2 * math.pi)) * NB - 0.5
    b = int(math.floor(x))
    t = x - b
    return band_top[b % NB] * (1 - t) + band_top[(b + 1) % NB] * t


# --- ray-cast ID images ----------------------------------------------------------------------
names = list(BMS)
verts_all, polys_all, owner = [], [], []
for mi, n in enumerate(names):
    bm = BMS[n]
    base = len(verts_all)
    verts_all += [v.co.copy() for v in bm.verts]
    for f in bm.faces:
        polys_all.append([base + v.index for v in f.verts])
        owner.append(mi)
TREE = BVHTree.FromPolygons(verts_all, polys_all, all_triangles=True)
owner = np.array(owner)
COL = {"body": (0.80, 0.62, 0.50), "shirt": (0.95, 0.95, 0.95), "jacket": (0.15, 0.30, 0.85),
       "tie": (0.85, 0.12, 0.10), "waistcoat": (0.45, 0.20, 0.60), "buttons": (0.3, 0.3, 0.3),
       "trousers": (0.2, 0.2, 0.5), "shoes": (0.1, 0.1, 0.1), "hair": (0.25, 0.18, 0.1),
       "other": (0.5, 0.5, 0.2)}


def camera_rays(loc, tgt, lens, frame_h, res):
    fwd = (tgt - loc).normalized()
    right = fwd.cross(Vector((0, 0, 1))).normalized()
    up = right.cross(fwd)
    dist = (tgt - loc).length
    half = frame_h * 0.5
    return fwd, right, up, dist, half


def view_cam(az, tgt, frame_h, lens=85.0):
    a = math.radians(az)
    axis = Vector((math.sin(a), -math.cos(a), 0.0))
    sensor = 36.0
    dist = (frame_h * 0.5) / math.tan(math.atan(sensor * 0.5 / lens))
    return tgt + axis * dist, tgt


def covered(p, reach=0.03):
    """Skin with the shirt collar straight out from the neck axis in front of
    it: the neck inside the band (seen over its edge), not bare skin between
    the garments."""
    c = axis_xy(p.z)
    d = Vector((p.x - c.x, p.y - c.y, 0.0))
    if d.length < 1e-6:
        return False
    d.normalize()
    o = p + d * 1e-4
    h = TREE.ray_cast(o, d, reach)
    return h[0] is not None and kinds[names[owner[h[2]]]] == "shirt"


def raycast_view(name, loc, tgt, frame_h, res, rows=(0.0, 1.0)):
    fwd, right, up, dist, half = camera_rays(loc, tgt, 85.0, frame_h, res)
    img = np.zeros((res, res, 3), dtype=np.float32)
    img[:] = (0.05, 0.05, 0.06)
    skin = back = garment = inside = 0
    skin_at, skin_xy, back_at = {}, {}, {}
    y0, y1 = int(rows[0] * res), int(rows[1] * res)
    for y in range(y0, y1):
        vy = half * (1 - 2 * (y + 0.5) / res)
        for x in range(res):
            vx = half * (2 * (x + 0.5) / res - 1)
            d = (fwd * dist + right * vx + up * vy).normalized()
            hit = TREE.ray_cast(loc, d, 10.0)
            if hit[0] is None:
                continue
            k = kinds[names[owner[hit[2]]]]
            c = COL.get(k, COL["other"])
            p = hit[0]
            zone = in_zone(p)
            if k == "body" and zone and p.z < band_top_at(p) - A.skin_tol and covered(p):
                # neck inside the band, seen down through the collar's opening
                inside += 1
                c = (0.1, 0.55, 0.55)
            elif k == "body" and zone and p.z < band_top_at(p) - A.skin_tol:
                skin += 1
                c = (0.1, 0.9, 0.2)
                ax = axis_xy(p.z)
                az = (math.degrees(math.atan2(p.y - ax.y, p.x - ax.x)) + 90) % 360
                b = f"az{int(az // 15) * 15:03d} dz{round(1000 * (p.z - band_top_at(p))) // 5 * 5:+d}mm"
                skin_at[b] = skin_at.get(b, 0) + 1
                skin_xy.setdefault(b, [x, y, [round(c, 3) for c in p]])
            elif k not in ("body", "hair") and zone:
                garment += 1
                if hit[1].dot(d) > 0:
                    back += 1
                    ax = axis_xy(p.z)
                    az = (math.degrees(math.atan2(p.y - ax.y, p.x - ax.x)) + 90) % 360
                    b = f"{k} az{int(az // 30) * 30:03d} z{round(100 * (p.z - supra)):+d}"
                    back_at[b] = back_at.get(b, 0) + 1
                    c = (1.0, 0.0, 1.0)
            if k not in ("hair",):
                shade = 0.55 + 0.45 * abs(hit[1].dot(d))
                c = tuple(ch * shade for ch in c)
            img[y, x] = c
    save_png(img, os.path.join(A.out_dir, f"id_{name}.png"))
    top = dict(sorted(skin_at.items(), key=lambda kv: -kv[1])[:8])
    return {"skin_px": skin, "neck_inside_px": inside, "backface_px": back, "garment_px": garment, "skin_at": top,
            "skin_px_xy": {k: skin_xy[k] for k in top},
            "back_at": dict(sorted(back_at.items(), key=lambda kv: -kv[1])[:10])}


def save_png(img, path):
    h, w, _ = img.shape
    im = bpy.data.images.new(os.path.basename(path), w, h, alpha=True)
    px = np.ones((h, w, 4), dtype=np.float32)
    px[..., :3] = img[::-1]
    im.pixels.foreach_set(px.ravel())
    im.filepath_raw = path
    im.file_format = "PNG"
    im.save()
    bpy.data.images.remove(im)


collar_tgt = Vector((0.0, axis_xy(supra + 0.03).y - 0.02, supra + 0.035))
VIEWS = {
    # the harness close-up exactly; only the lower part of the frame holds the collar
    "closeup": (view_cam(25.0, head + Vector((0, 0, -0.03)), 0.42), 0.42, (0.55, 1.0)),
    "collar_front": (view_cam(0.0, collar_tgt, 0.26), 0.26, (0.0, 1.0)),
    "collar_q": (view_cam(40.0, collar_tgt, 0.26), 0.26, (0.0, 1.0)),
    "collar_p": (view_cam(90.0, collar_tgt, 0.26), 0.26, (0.0, 1.0)),
}
report["views"] = {}
for name, ((loc, tgt), fh, rows) in VIEWS.items():
    res = A.res if name == "closeup" else A.res // 2 + A.res // 4
    report["views"][name] = raycast_view(name, loc, tgt, fh, res, rows)

# --- geometry: intersections in the neck zone -------------------------------------------------


def zone_tree(n):
    bm = BMS[n]
    keep = [f for f in bm.faces if any(in_zone(v.co, 0.16) for v in f.verts)]
    verts = [v.co.copy() for v in bm.verts]
    polys = [[v.index for v in f.verts] for f in keep]
    if not polys:
        return None, [], verts
    return BVHTree.FromPolygons(verts, polys, all_triangles=True), polys, verts


ZT = {}
for n in names:
    k = kinds[n]
    if k in ("body", "shirt", "jacket", "tie"):
        ZT[k] = zone_tree(n)
WHERE = {}
SAMPLES = {}


def where(key, k, idx):
    """Histogram of intersection sites: (azimuth round the neck axis in 30 deg
    bins, from the front; height over the suprasternale in cm)."""
    t, polys, verts = ZT[k]
    h = WHERE.setdefault(key, {})
    for i in idx:
        c = sum((verts[j] for j in polys[i]), Vector()) / len(polys[i])
        ax = axis_xy(c.z)
        az = (math.degrees(math.atan2(c.y - ax.y, c.x - ax.x)) + 90) % 360   # 0 = front, 90 = wearer's left
        b = f"az{int(az // 30) * 30:03d} z{round(100 * (c.z - supra)):+d}"
        h[b] = h.get(b, 0) + 1


def self_isect(k):
    t, polys, _ = ZT.get(k, (None, [], None))
    if t is None:
        return 0
    hits = [(a, b) for a, b in t.overlap(t) if a < b and not (set(polys[a]) & set(polys[b]))]
    where(f"self.{k}", k, [a for a, _ in hits])
    verts = ZT[k][2]
    cen = lambda i: [round(c, 3) for c in sum((verts[j] for j in polys[i]), Vector()) / len(polys[i])]
    SAMPLES[f"self.{k}"] = [[cen(a), cen(b)] for a, b in hits[:: max(1, len(hits) // 6)][:6]]
    # by material pair (a SUIT_DEBUG_TAGS build gives the jacket one material per panel)
    n = next(nn for nn in names if kinds[nn] == k)
    bm = BMS[n]
    bm.faces.ensure_lookup_table()
    fidx = [f.index for f in bm.faces if any(in_zone(v.co, 0.16) for v in f.verts)]
    mats = {}
    for a, b in hits:
        ma, mb = sorted((bm.faces[fidx[a]].material_index, bm.faces[fidx[b]].material_index))
        mats[f"m{ma}/m{mb}"] = mats.get(f"m{ma}/m{mb}", 0) + 1
    if len(mats) > 1:
        WHERE[f"self.{k}.mat"] = mats
    return len(hits)


def pair_isect(ka, kb):
    ta = ZT.get(ka, (None,))[0]
    tb = ZT.get(kb, (None,))[0]
    if ta is None or tb is None:
        return 0
    hits = ta.overlap(tb)
    where(f"{ka}/{kb}", ka, [a for a, _ in hits])
    return len(hits)

geo = {"self": {k: self_isect(k) for k in ("shirt", "jacket", "tie")},
       "pairs": {f"{a}/{b}": pair_isect(a, b) for a, b in (("body", "shirt"), ("body", "jacket"),
                                                           ("shirt", "jacket"), ("tie", "jacket"),
                                                           ("tie", "shirt"), ("body", "tie"))}}

# radial ordering: from the neck axis outward, body < shirt < jacket
per_kind_tree = {}
for k in ("body", "shirt", "jacket"):
    t = ZT.get(k, (None,))[0]
    per_kind_tree[k] = t
order_bad = []
for zi in range(12):
    z = supra - 0.01 + 0.006 * zi
    c = axis_xy(z)
    for ai in range(72):
        a = 2 * math.pi * ai / 72
        d = Vector((math.cos(a), math.sin(a), 0.0))
        o = Vector((c.x, c.y, z))
        hits = []
        for k, t in per_kind_tree.items():
            if t is None:
                continue
            start, travelled = o.copy(), 0.0
            while travelled < 0.2:
                h = t.ray_cast(start, d, 0.2 - travelled)
                if h[0] is None:
                    break
                r = (h[0] - o).length
                hits.append((r, k))
                travelled = r + 1e-4
                start = o + d * travelled
        hits.sort()
        seq = [k for _, k in hits]
        if "jacket" in seq and "shirt" in seq[seq.index("jacket"):]:
            last_j = max(i for i, s in enumerate(seq) if s == "jacket")
            # a shirt hit after the jacket's outer surface: the shirt is outside
            if "shirt" in seq[last_j:]:
                order_bad.append([round(z, 3), round(math.degrees(a)), "shirt_outside_jacket"])
geo["order_violations"] = len(order_bad)
geo["order_samples"] = order_bad[:12]
geo["samples"] = SAMPLES
geo["where"] = {k: dict(sorted(v.items(), key=lambda kv: -kv[1])[:8]) for k, v in WHERE.items() if v}
report["geometry"] = geo

# --- optional EEVEE renders (beauty / wire) of the same cameras ------------------------------
if A.wire or A.beauty:
    for o in meshes:
        if kinds[o.name] in ("hair", "other") and not (A.hair and kinds[o.name] == "hair"):
            o.hide_render = True
        if A.show and kinds[o.name] not in A.show.split(","):
            o.hide_render = True
    sc.render.engine = "BLENDER_EEVEE"
    sc.eevee.taa_render_samples = 16
    sc.render.resolution_x = sc.render.resolution_y = A.beauty_res or A.res
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.exposure = -2.5
    sc.world = bpy.data.worlds.new("collar")
    sc.world.color = (0.03, 0.03, 0.035)

    def light(nm, loc, energy, size):
        ld = bpy.data.lights.new(nm, "AREA")
        ld.energy, ld.size = energy, size
        ob = bpy.data.objects.new(nm, ld)
        sc.collection.objects.link(ob)
        ob.location = loc
        ob.rotation_euler = (Vector((0, 0, 1.1)) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    light("key", (-2.2, -2.6, 2.8), 900, 1.5)
    light("fill", (2.6, -2.0, 1.4), 250, 2.0)
    light("rim", (0.8, 2.8, 2.6), 700, 1.0)
    cd = bpy.data.cameras.new("collar")
    cd.lens = 85.0
    cam = bpy.data.objects.new("collar", cd)
    sc.collection.objects.link(cam)
    sc.camera = cam
    wires = []

    def set_wire(on):
        if on and not wires:
            wm = bpy.data.materials.new("wire")
            wm.use_nodes = True
            em = wm.node_tree.nodes.new("ShaderNodeEmission")
            em.inputs[0].default_value = (1.0, 0.45, 0.05, 1.0)
            em.inputs[1].default_value = 3.0
            out = next(n for n in wm.node_tree.nodes if n.type == "OUTPUT_MATERIAL")
            wm.node_tree.links.new(em.outputs[0], out.inputs[0])
            for o in meshes:
                if kinds[o.name] not in ("jacket", "shirt", "tie") or (A.show and kinds[o.name] not in A.show.split(",")):
                    continue
                w = o.copy()
                w.data = o.data.copy()
                w.data.materials.clear()
                w.data.materials.append(wm)
                for p in w.data.polygons:
                    p.material_index = 0
                m = w.modifiers.new("wire", "WIREFRAME")
                m.thickness = 0.0004
                m.use_replace = True
                sc.collection.objects.link(w)
                wires.append(w)
        for w in wires:
            w.hide_render = not on

    for mode in (["beauty"] if A.beauty else []) + (["wire"] if A.wire else []):
        set_wire(mode == "wire")
        # plus the harness close-up camera zoomed onto the collar (same eye point)
        cl_loc = VIEWS["closeup"][0][0]
        zoom = {"closeup_zoom": ((cl_loc, collar_tgt), 0.14, None),
                "closeup_wide": ((cl_loc, collar_tgt + Vector((0, 0, 0.02))), 0.24, None),
                "closeup_far": ((cl_loc, collar_tgt + Vector((-0.07, 0, 0.0))), 0.12, None)}
        for name, ((loc, tgt), fh, rows) in list(VIEWS.items()) + list(zoom.items()):
            cam.location = loc
            cam.rotation_euler = (tgt - loc).to_track_quat("-Z", "Y").to_euler()
            cd.sensor_width = 36.0
            cd.lens = 85.0 * (VIEWS["closeup"][1] / fh) if name.startswith("closeup_") else 85.0
            sc.render.filepath = os.path.join(A.out_dir, f"{mode}_{name}.png")
            bpy.ops.render.render(write_still=True)

# --- verdict -----------------------------------------------------------------------------------
for name, v in report["views"].items():
    if v["skin_px"] > A.max_skin:
        report["fail"].append(f"{name}: {v['skin_px']} skin px inside the collar")
    if v["backface_px"] > A.max_back:
        report["fail"].append(f"{name}: {v['backface_px']} backface px in the collar zone")
n_is = (sum(v for k, v in geo["self"].items() if k != "tie")
        + sum(v for k, v in geo["pairs"].items() if k != "body/shirt"))
report["isect_gated"] = n_is
if n_is > A.max_isect:
    report["fail"].append(f"{n_is} triangle intersections in the neck zone (self + layers)")
if geo["order_violations"]:
    report["fail"].append(f"{geo['order_violations']} radial rays meet the shirt outside the jacket")
report["ok"] = not report["fail"]
with open(os.path.join(A.out_dir, "collar.json"), "w") as f:
    json.dump(report, f, indent=1)
for name, v in report["views"].items():
    print(f"[suit_collar] {name:13s} skin {v['skin_px']:5d}  (neck in band {v['neck_inside_px']:4d})  backface {v['backface_px']:5d}  "
          f"garment {v['garment_px']:6d}")
print(f"[suit_collar] self-isect {geo['self']}  pairs {geo['pairs']}  order {geo['order_violations']}")
print("[suit_collar] " + ("PASS" if report["ok"] else "FAIL: " + "; ".join(report["fail"])))
sys.exit(0 if report["ok"] else 1)
