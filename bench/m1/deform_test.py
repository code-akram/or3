"""Deformation test for the hero character (m1 v2 Track F; bench/m1/v2/deform.md).

Imports the shipped GLB (or a kept character.blend), poses the rig through the
canonical poses (blender/character/deform_poses.py), applies the runtime rules
the game will run (helper and twist bones, skirt followers, corrective morph
weights; blender/character/deform_runtime.py, read from character.rig.json)
and, per pose:

* renders a full-body frame in the shipped materials and one in clay (one
  flat colour per garment layer, so an inner layer showing through an outer
  one is obvious), plus clay close-ups of each listed joint, with the clothes
  on and with the skin only (garments hidden);
* counts poke-through geometrically per layer pair: a vertex of an inner
  layer that the outer layer covers in the rest pose (nearest outer point
  within --cover-m, on the inside) and that is outside the outer surface by
  more than --tol-m in the pose. Faces next to an open edge of the outer
  layer (cuff, hem, collar, vent) are not judged. Reported per pair with the
  max depth and the bones the poking vertices hang on.

    blender -b -t 4 --factory-startup --python bench/m1/deform_test.py -- \
        --glb RUN/character.glb --out-dir DIR [--poses a,b] [--rules none|PATH] \
        [--res 384] [--full-res 640] [--no-render] [--light studio|neon]

Writes DIR/<pose>/{full,full_clay,<joint>,<joint>_skin}.png, DIR/poke.json
and DIR/tiles.txt (the montage layout bench/m1/deform_test.sh uses).
"""

import argparse
import json
import math
import os
import sys
import time

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "blender"))
from character import deform_poses as dp  # noqa: E402
from character import deform_runtime as drt  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--glb")
ap.add_argument("--blend")
ap.add_argument("--out-dir", required=True)
ap.add_argument("--poses", default="")
ap.add_argument("--rules", default="auto", help="auto (next to the GLB), none, or a path")
ap.add_argument("--res", type=int, default=384)
ap.add_argument("--full-res", type=int, default=640)
ap.add_argument("--no-render", action="store_true")
ap.add_argument("--no-skin", action="store_true", help="skip the skin-only close-ups")
ap.add_argument("--light", choices=["studio", "neon"], default="studio")
ap.add_argument("--no-morphs", action="store_true", help="helpers only, corrective weights 0")
ap.add_argument("--cover-m", type=float, default=0.05)
ap.add_argument("--tol-m", type=float, default=0.0015)
A = ap.parse_args(argv)

# inner fragment, outer fragment
LAYER_PAIRS = [
    ("body", "shirt"), ("body", "waistcoat"), ("body", "jacket"), ("body", "trousers"),
    ("shirt", "waistcoat"), ("shirt", "jacket"), ("shirt", "trousers"),
    ("tie", "waistcoat"), ("tie", "jacket"),
    ("waistcoat", "jacket"), ("trousers", "jacket"),
]
CLAY = {"body": (0.80, 0.55, 0.45), "shirt": (0.92, 0.92, 0.90), "waistcoat": (0.20, 0.32, 0.55),
        "jacket": (0.42, 0.42, 0.44), "trousers": (0.45, 0.33, 0.22), "tie": (0.70, 0.10, 0.10),
        "shoes": (0.12, 0.12, 0.12), "buttons": (0.9, 0.8, 0.2)}
HIDE_ALWAYS = ("eyelash",)
HAIR = ("hair", "beard", "brows", "eyebrow")

# close-ups: name -> (bone, offset (char frame, x mirrored for _r), az, el, frame_h)
# az 0 = in front of the character, + = its left side.
JOINTS = {
    "shoulder_l": ("upperarm_l", (0.0, 0.0, 0.0), 65, 10, 0.36),
    "shoulder_top_l": ("upperarm_l", (-0.03, 0.0, 0.04), 40, 35, 0.36),
    "shoulder_back_l": ("upperarm_l", (0.0, 0.0, 0.0), 150, 15, 0.36),
    "armpit_l": ("upperarm_l", (0.0, 0.0, -0.08), 55, -25, 0.36),
    "elbow_l": ("lowerarm_l", (0.0, 0.0, 0.0), 55, 5, 0.30),
    "forearm_l": ("lowerarm_l", None, 55, 5, 0.34),
    "wrist_l": ("hand_l", (0.0, 0.0, 0.0), 55, 10, 0.22),
    "hand_l": ("hand_l", "middle_01_l", 50, 15, 0.24),
    "neck": ("neck_01", (0.0, 0.0, 0.04), 25, 5, 0.32),
    "neck_l": ("neck_01", (0.0, 0.0, 0.04), 80, 5, 0.32),
    "neck_back": ("neck_01", (0.0, 0.0, 0.04), 180, 5, 0.32),
    "hip_l": ("thigh_l", (0.0, 0.0, 0.0), 40, 5, 0.50),
    "hip_front_l": ("thigh_l", (0.0, 0.0, 0.0), 15, 10, 0.50),
    "hip_back_l": ("thigh_l", (0.0, 0.0, 0.0), 160, 5, 0.50),
    "knee_l": ("calf_l", (0.0, 0.0, 0.0), 60, 5, 0.36),
    "skirt_l": ("thigh_l", (0.0, 0.0, -0.12), 50, 5, 0.62),
    "skirt_back": ("pelvis", (0.0, 0.0, -0.18), 180, 5, 0.70),
    "skirt_profile_l": ("thigh_l", (0.0, -0.05, -0.05), 90, 0, 0.75),
    "skirt_top_l": ("thigh_l", (0.0, -0.10, 0.0), 25, 40, 0.6),
    "torso_front": ("spine_02", (0.0, -0.1, 0.0), 10, 5, 0.6),
    "chest": ("spine_03", (0.0, -0.12, 0.06), 15, 10, 0.40),
    "trouser_l": ("calf_l", (0.0, 0.0, 0.15), 70, 0, 0.70),
}


def joint_spec(name):
    if name in JOINTS:
        return JOINTS[name], 1.0
    if name.endswith("_r") and name[:-2] + "_l" in JOINTS:
        (bone, off, az, el, fh) = JOINTS[name[:-2] + "_l"]
        off = off[:-2] + "_r" if isinstance(off, str) else (None if off is None else
                                                            (-off[0], off[1], off[2]))
        return (bone[:-2] + "_r", off, -az, el, fh), -1.0
    if name == "neck_r":
        (bone, off, az, el, fh) = JOINTS["neck_l"]
        return (bone, off, -az, el, fh), 1.0
    raise KeyError(name)


def part(o):
    n = o.name.lower()
    if n.startswith("human_export") or n == "human_export":
        return "body"
    for k in ("shirt", "waistcoat", "jacket", "trousers", "tie", "shoes", "buttons"):
        if k in n:
            return k
    for k in HAIR + HIDE_ALWAYS:
        if k in n:
            return "hair"
    return "other"


# ---------------------------------------------------------------- scene

def load():
    if A.blend:
        bpy.ops.wm.open_mainfile(filepath=os.path.abspath(A.blend))
        for c in list(bpy.data.collections):
            if c.name == "hero_only":
                for o in c.objects:
                    o.hide_render = True
    else:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=os.path.abspath(A.glb))
    sc = bpy.context.scene
    arm = next(o for o in sc.objects if o.type == "ARMATURE")
    meshes = [o for o in sc.objects if o.type == "MESH" and o.parent == arm and not o.hide_render]
    for o in sc.objects:
        if o.type == "MESH" and o not in meshes:
            o.hide_render = True
    for o in sc.objects:
        if o.type in ("LIGHT", "CAMERA"):
            bpy.data.objects.remove(o, do_unlink=True)
    return sc, arm, meshes


def rules_path():
    if A.rules == "none":
        return None
    if A.rules != "auto":
        return A.rules
    src = A.glb or A.blend
    p = os.path.join(os.path.dirname(os.path.abspath(src)), "character.rig.json")
    return p if os.path.exists(p) else None


def clay_materials(meshes):
    mats = {}
    for k, c in list(CLAY.items()) + [("other", (0.6, 0.6, 0.6)), ("hair", (0.1, 0.08, 0.07))]:
        m = bpy.data.materials.new("clay_" + k)
        m.use_nodes = True
        p = m.node_tree.nodes["Principled BSDF"]
        p.inputs["Base Color"].default_value = (*c, 1)
        p.inputs["Roughness"].default_value = 0.6
        mats[k] = m
    orig = {o.name: [s.material for s in o.material_slots] for o in meshes}
    return mats, orig


def set_materials(meshes, mode, mats, orig):
    for o in meshes:
        if mode == "clay":
            for s in o.material_slots:
                s.material = mats.get(part(o), mats["other"])
        else:
            for s, m in zip(o.material_slots, orig[o.name]):
                s.material = m


def setup_render(sc):
    sc.render.engine = "BLENDER_EEVEE"
    sc.eevee.taa_render_samples = 16
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGB"
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.look = "None"
    w = bpy.data.worlds.new("deform")
    w.use_nodes = True
    w.node_tree.nodes["Background"].inputs[0].default_value = (0.05, 0.05, 0.055, 1)
    w.node_tree.nodes["Background"].inputs[1].default_value = 1.0
    sc.world = w


def add_light(sc, name, energy, size, color):
    ld = bpy.data.lights.new(name, "AREA")
    ld.energy, ld.size, ld.color = energy, size, color
    ob = bpy.data.objects.new(name, ld)
    sc.collection.objects.link(ob)
    return ob


def look_at(ob, target):
    ob.rotation_euler = (target - ob.location).to_track_quat("-Z", "Y").to_euler()


class Stage:
    """Camera plus a camera-relative light rig (key upper-left of the camera,
    fill right, rim behind), so every close-up is lit the same way."""

    def __init__(self, sc, light):
        self.sc = sc
        cd = bpy.data.cameras.new("cam")
        self.cam = bpy.data.objects.new("cam", cd)
        sc.collection.objects.link(self.cam)
        sc.camera = self.cam
        self.light = light
        if light == "neon":
            self.lights = [(add_light(sc, "key", 1, 0.8, (1.0, 0.72, 0.45)), (-40, 25, 1.0), 1.0),
                           (add_light(sc, "rim_m", 1, 0.6, (1.0, 0.18, 0.55)), (150, 15, 0.7), 1.0),
                           (add_light(sc, "kick_t", 1, 0.6, (0.1, 0.8, 0.9)), (-150, 20, 0.4), 1.0),
                           (add_light(sc, "fill", 1, 2.0, (0.6, 0.7, 0.9)), (30, 0, 0.08), 1.0)]
            sc.view_settings.exposure = 0.0
        else:
            self.lights = [(add_light(sc, "key", 1, 1.2, (1.0, 0.97, 0.92)), (-35, 30, 1.0), 1.0),
                           (add_light(sc, "fill", 1, 2.0, (0.85, 0.9, 1.0)), (45, 5, 0.35), 1.0),
                           (add_light(sc, "rim", 1, 1.0, (1, 1, 1)), (160, 25, 0.8), 1.0)]

    def shoot(self, target, az, el, frame_h, res, path, exposure=0.0, base_energy=None):
        a, e = math.radians(az), math.radians(el)
        axis = Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)))
        cd = self.cam.data
        cd.lens = 50.0 if frame_h > 1.0 else 85.0
        dist = (frame_h * 0.5) / math.tan(math.atan(cd.sensor_width * 0.5 / cd.lens))
        cd.clip_start = 0.02
        self.cam.location = target + axis * dist
        look_at(self.cam, target)
        d = max(1.2, dist)
        for ob, (laz, lel, k), _ in self.lights:
            la, le = math.radians(az + laz), math.radians(el + lel)
            ob.location = target + Vector((math.sin(la) * math.cos(le), -math.cos(la) * math.cos(le),
                                           math.sin(le))) * d
            look_at(ob, target)
            ob.data.energy = (base_energy or 12.0) * k * d * d
        self.sc.view_settings.exposure = exposure
        self.sc.render.resolution_x = self.sc.render.resolution_y = res
        self.sc.render.filepath = path
        bpy.ops.render.render(write_still=True)


# ---------------------------------------------------------------- poke-through

def evaluated(o, dg):
    ev = o.evaluated_get(dg)
    me = ev.to_mesh()
    mw = o.matrix_world
    co = np.empty(len(me.vertices) * 3, dtype=np.float64)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    M = np.array(mw)
    co = co @ M[:3, :3].T + M[:3, 3]
    nrm = np.empty(len(me.vertices) * 3, dtype=np.float64)
    me.vertex_normals.foreach_get("vector", nrm)
    nrm = nrm.reshape(-1, 3) @ M[:3, :3].T
    tris = [tuple(p.vertices) for p in me.polygons]
    ev.to_mesh_clear()
    return co, tris, nrm


def boundary_faces(o):
    me = o.data
    count = {}
    for p in me.polygons:
        for e in p.edge_keys:
            count[e] = count.get(e, 0) + 1
    bverts = set()
    for e, c in count.items():
        if c == 1:
            bverts.update(e)
    return {p.index for p in me.polygons if any(v in bverts for v in p.vertices)}


def dominant_bones(o, idx, k=3):
    names = {g.index: g.name for g in o.vertex_groups}
    tally = {}
    for i in idx:
        v = o.data.vertices[i]
        if v.groups:
            g = max(v.groups, key=lambda g: g.weight)
            tally[names[g.group]] = tally.get(names[g.group], 0) + 1
    return sorted(tally.items(), key=lambda kv: -kv[1])[:k]


def crossings(bvh, a, b):
    """Number of surface crossings on the segment a -> b, and the distance
    from the last one to b."""
    d = b - a
    L = d.length
    if L < 1e-6:
        return 0, 0.0
    d = d / L
    n, t, last = 0, 0.0, 0.0
    while t < L:
        hit = bvh.ray_cast(a + d * t, d, L - t)
        if hit[0] is None:
            break
        t += hit[3] + 1e-4
        n += 1
        last = t
    return n, L - last


class Poke:
    def __init__(self, meshes, arm=None):
        self.arm = arm
        self.by = {}
        for o in meshes:
            p = part(o)
            if p in ("body", "shirt", "waistcoat", "jacket", "trousers", "tie"):
                self.by.setdefault(p, o)
        self.pairs = [(i, o) for i, o in LAYER_PAIRS if i in self.by and o in self.by]
        self.bfaces = {k: boundary_faces(o) for k, o in self.by.items()}
        self.cover = {}

    def _side(self, inner_co, outer_co, outer_tris, bfaces, inner_nrm=None, key=None):
        """Per inner vertex: 1 outside the outer surface by > tol, -1 inside,
        0 not judged (nothing within cover_m, or an open-edge face).

        Rest pass (inner_nrm given): "inside" also needs the ray along the
        inner normal to hit the outer layer within cover_m (it is really
        under it); the covering face is remembered. Pose pass (key given): a
        hit only counts on the same part of the outer layer, i.e. a face whose
        rest centroid is within 4 cm of the remembered one, so a sleeve that
        comes close to the chest is not read as the chest poking through it."""
        bvh = BVHTree.FromPolygons([tuple(v) for v in outer_co], outer_tris, all_triangles=False)
        out = np.zeros(len(inner_co), dtype=np.int8)
        depth = np.zeros(len(inner_co))
        face = np.full(len(inner_co), -1, dtype=np.int64)
        if key is not None:
            rf = self.face[key]
            cen = self.centroids[key.split(">")[1]]
        for i, p in enumerate(inner_co):
            if key is not None and rf[i] < 0:
                continue
            pv = Vector(p)
            hit = bvh.find_nearest(pv, A.cover_m)
            if hit[0] is None or hit[2] in bfaces:
                continue
            if key is not None and np.linalg.norm(cen[hit[2]] - cen[rf[i]]) > 0.04:
                continue
            s = (pv - hit[0]).dot(hit[1])
            if s > A.tol_m:
                out[i], depth[i] = 1, s
            elif s < 0:
                if inner_nrm is not None:
                    n = Vector(inner_nrm[i])
                    if bvh.ray_cast(pv + n * 0.0005, n, A.cover_m)[0] is None:
                        continue
                out[i] = -1
                face[i] = hit[2]
        return out, depth, face

    def _anchor_setup(self, inner, co):
        """Per inner vertex: its dominant bone and the rest point on that
        bone's axis nearest to it (an interior anchor that moves with it)."""
        o = self.by[inner]
        B = self.arm.data.bones
        names = {g.index: g.name for g in o.vertex_groups}
        bone, pt = [], np.zeros((len(co), 3))
        for v in o.data.vertices:
            g = max((g for g in v.groups if names[g.group] in B), key=lambda g: g.weight, default=None)
            n = names[g.group] if g else None
            bone.append(n)
            if n:
                h, t = np.array(B[n].head_local), np.array(B[n].tail_local)
                d = t - h
                u = np.clip((co[v.index] - h) @ d / d.dot(d), 0, 1)
                pt[v.index] = h + u * d
        return bone, pt

    def _anchors(self, inner):
        bone, pt = self.anch[inner]
        out = np.zeros_like(pt)
        mats = {}
        for i, n in enumerate(bone):
            if n is None:
                continue
            if n not in mats:
                mats[n] = np.array(self.arm.pose.bones[n].matrix @ self.arm.data.bones[n].matrix_local.inverted())
            M = mats[n]
            out[i] = M[:3, :3] @ pt[i] + M[:3, 3]
        return out

    def measure(self, dg, rest=False):
        cos = {k: evaluated(o, dg) for k, o in self.by.items()}
        if rest:
            self.face = {}
            self.centroids = {k: np.array([cos[k][0][list(t)].mean(0) for t in cos[k][1]]) for k in cos}
            self.anch = {k: self._anchor_setup(k, cos[k][0]) for k in {i for i, _ in self.pairs}}
        res = {}
        bvhs = {k: BVHTree.FromPolygons([tuple(v) for v in cos[k][0]], cos[k][1], all_triangles=False)
                for k in {o for _, o in self.pairs}}
        anchors = {k: self._anchors(k) for k in {i for i, _ in self.pairs}}
        for inner, outer in self.pairs:
            key = f"{inner}>{outer}"
            side, depth, face = self._side(cos[inner][0], cos[outer][0], cos[outer][1], self.bfaces[outer],
                                           cos[inner][2] if rest else None, None if rest else key)
            # crossing test: the segment from the interior anchor to the vertex
            # crosses the outer layer (inner vertex pushed through it)
            cand = np.nonzero(self.cover[key] if not rest else side == -1)[0]
            cross = np.zeros(len(side), dtype=np.int16)
            cdep = np.zeros(len(side))
            for i in cand:
                n, dd = crossings(bvhs[outer], Vector(anchors[inner][i]), Vector(cos[inner][0][i]))
                cross[i], cdep[i] = n, dd
            if rest:
                self.cover[key] = (side == -1) & (cross == 0)
                self.face[key] = np.where(self.cover[key], face, -1)
                res[key] = {"covered": int(self.cover[key].sum()), "outside_at_rest": int((side == 1).sum())}
                continue
            through = (cross % 2 == 1) & (cdep > A.tol_m)
            depth = np.where(through & (cdep > depth), cdep, depth)
            mask = self.cover[key] & ((side == 1) | through)
            idx = np.nonzero(mask)[0]
            res[key] = {"poke": int(len(idx)),
                        "max_mm": round(float(depth[idx].max() * 1000), 1) if len(idx) else 0.0,
                        "bones": dominant_bones(self.by[inner], idx[:4000]) if len(idx) else [],
                        "at": [round(float(x), 3) for x in cos[inner][0][idx].mean(0)] if len(idx) else []}
        return res


# ---------------------------------------------------------------- main

def joint_target(arm, spec, sgn):
    bone, off, az, el, fh = spec
    pbs = arm.pose.bones
    if bone not in pbs:
        return None
    h = arm.matrix_world @ pbs[bone].head
    if isinstance(off, str):
        return (h + arm.matrix_world @ pbs[off].head) * 0.5
    if off is None:
        return (h + arm.matrix_world @ pbs[bone].tail) * 0.5 if bone.startswith("lowerarm") else h
    return h + Vector(off)


def main():
    t0 = time.perf_counter()
    sc, arm, meshes = load()
    rp = rules_path()
    rules = json.load(open(rp)) if rp else None
    rig = dp.Rig(arm)
    rt = drt.Runtime(arm, meshes, rules) if rules else None
    os.makedirs(A.out_dir, exist_ok=True)
    poses = [p for p in A.poses.split(",") if p] or [p for p in dp.POSES]
    poke = Poke(meshes, arm)
    dp.reset(arm)
    if rt:
        rt.apply(rig, morphs=not A.no_morphs)
    dg = bpy.context.evaluated_depsgraph_get()
    rest = poke.measure(dg, rest=True)
    report = {"glb": A.glb, "blend": A.blend, "rules": rp, "rest": rest, "poses": {}}
    stage = None
    if not A.no_render:
        setup_render(sc)
        stage = Stage(sc, A.light)
        mats, orig = clay_materials(meshes)
    tiles = []
    for pname in poses:
        spec = dp.POSES[pname]
        dp.apply_pose(arm, spec, rig)
        drv = rt.apply(rig, morphs=not A.no_morphs) if rt else {}
        dg = bpy.context.evaluated_depsgraph_get()
        dg.update()
        pk = poke.measure(dg) if pname != "rest" else {}
        report["poses"][pname] = {"poke": pk, "drivers": {k: round(v, 3) for k, v in drv.items() if v}}
        tot = sum(v["poke"] for v in pk.values())
        worst = sorted(((k, v["poke"], v["max_mm"]) for k, v in pk.items() if v["poke"]),
                       key=lambda t: -t[1])[:4]
        print(f"[deform] {pname:11s} poke {tot:5d}  {worst}", flush=True)
        if A.no_render:
            continue
        d = os.path.join(A.out_dir, pname)
        os.makedirs(d, exist_ok=True)
        az = spec.get("view", 25)
        body_t = Vector((0, 0, 0.95))
        row = []
        for o in meshes:
            o.hide_render = any(k in o.name.lower() for k in HIDE_ALWAYS)
        set_materials(meshes, "asset", mats, orig)
        stage.shoot(body_t, az, 5, 2.15, A.full_res, os.path.join(d, "full.png"),
                    exposure=0.5 if A.light == "studio" else 0.0)
        row.append(("full", os.path.join(d, "full.png")))
        set_materials(meshes, "clay", mats, orig)
        for o in meshes:
            if part(o) == "hair":
                o.hide_render = True
        stage.shoot(body_t, az, 5, 2.15, A.full_res, os.path.join(d, "full_clay.png"), exposure=-1.0)
        row.append(("full clay", os.path.join(d, "full_clay.png")))
        for j in spec.get("closeups", []):
            js, sgn = joint_spec(j)
            t = joint_target(arm, js, sgn)
            if t is None:
                continue
            p = os.path.join(d, f"{j}.png")
            stage.shoot(t, js[2], js[3], js[4], A.res, p, exposure=-1.0)
            row.append((j, p))
        if not A.no_skin:
            for o in meshes:
                if part(o) in ("shirt", "waistcoat", "jacket", "trousers", "tie", "buttons"):
                    o.hide_render = True
            for j in spec.get("closeups", []):
                if j.startswith(("skirt", "trouser")):
                    continue
                js, sgn = joint_spec(j)
                t = joint_target(arm, js, sgn)
                if t is None:
                    continue
                p = os.path.join(d, f"{j}_skin.png")
                stage.shoot(t, js[2], js[3], js[4], A.res, p, exposure=-1.0)
                row.append((j + " skin", p))
            for o in meshes:
                o.hide_render = part(o) == "hair" or any(k in o.name.lower() for k in HIDE_ALWAYS)
        tiles.append((pname, row))
    dp.reset(arm)
    report["seconds"] = round(time.perf_counter() - t0, 1)
    json.dump(report, open(os.path.join(A.out_dir, "poke.json"), "w"), indent=1)
    with open(os.path.join(A.out_dir, "tiles.txt"), "w") as f:
        for pname, row in tiles:
            for label, p in row:
                f.write(f"{pname}\t{label}\t{p}\n")
    print(f"[deform] done in {report['seconds']} s -> {A.out_dir}")


main()
