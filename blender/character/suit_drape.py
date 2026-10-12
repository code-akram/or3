"""Cloth-sim fold detail for the built suit (bench/m1/v2/suit.md).

The lofted garments are clean, eased surfaces with no folds. Here each one is
draped with Blender cloth on the body and the wrinkles are transferred back to
the game mesh as a height field in its own UV space:

  1. sim mesh   a simple subdivision of the garment (same UVs and panel tags,
                skin weights interpolated), with an armature modifier on a copy
                of the rig and a cloth modifier after it; tailored zones are
                pinned to the skin (shoulders, chest canvas, collar, lapels,
                the buttoned front, the sleeve head, the waistband)
  2. motion     the rig moves from a "relaxed" pose P0 to the target pose P1
                over `ramp` frames and holds: P0 has the elbows opened and the
                arms raised a little, P1 is the rest pose (its 44° elbow bend
                and lowered arms fold the sleeve at the crook and the armpit);
                P1 also flexes the knees and hips a little (back of the knee,
                crotch). The body (and the shoes) collide.
  3. transfer   fold height h = (cloth - skinned) . n, per sim vertex at P1,
                measured in the skinned surface's frame, so the folds map onto
                the rest mesh through the shared UVs (no ray projection, no
                cage). A graph high-pass keeps wavelengths under `highpass_m`
                (the drape's sag and offsets go), then region masks keep only
                the folds a tailored suit has (elbow crook, armpit, lower
                back, crotch, back of the knee, the break, the button pull)
                at full gain, everything else at `base_gain`.
  4. gate       (the clothcode idea, MIT: measure the settled drape before
                using it) body penetration, edge strain, settle speed and the
                fold wavelength; a failed gate retries with stiffer bending,
                then gives up (no folds) rather than ship a crumpled drape.

suit_textures rasterises h into each group's atlas (height map -> normals,
cavity, occlusion). Results are cached on disk by a hash of the inputs.
"""

import hashlib
import json
import math
import os
import time

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector
from mathutils.bvhtree import BVHTree

DEFAULTS = {
    "enabled": True,
    "cache": True,
    # a cached drape is reused while no garment vertex has moved more than this
    # since it was simulated (the folds ride on the UVs, so small body or fit
    # changes keep them); topology, pins and options are part of the key
    "cache_tol_m": 0.015,
    "parts": ["jacket", "trousers"],
    "level": 2,                 # simple subdivision levels of the sim mesh
    "frames": 36, "ramp": 22,   # P0 -> P1 over `ramp` frames, then hold
    "quality": 5, "collision_quality": 2,
    "fabric": {"mass": 0.32, "tension": 40.0, "compression": 40.0, "shear": 30.0,
               "bending": 6.0, "bending_max": 20.0, "air": 1.5, "pin_stiffness": 1.0,
               "distance_m": 0.003, "body_outer_m": 0.004, "friction": 5.0},
    # P0 (sim start) relative to the rest pose, P1 (target) relative to the rest pose
    "pose": {"p0": {"arm_raise_deg": 12.0},
             "p1": {"elbow_open_deg": -18.0, "knee_deg": 14.0, "hip_deg": 8.0}},
    "button_shrink": 0.025,     # waist band shrink at the fastened button (X pull lines)
    "highpass_m": 0.05,         # keep fold wavelengths below this
    "clamp_m": 0.004,           # soft clamp of |h|
    "base_gain": 0.1,           # outside the fold regions (0.35 printed the sim grid as a windowpane check)
    "denoise_iters": 4,         # graph smoothing of the high-passed height (grid-aligned sim ripples)
    # (landmark, radius m, gain); landmarks in suit_drape.landmarks()
    "regions": {"elbow": [0.075, 1.0], "armpit": [0.08, 0.9], "lower_back": [0.11, 0.8],
                "crotch": [0.09, 1.0], "knee_back": [0.09, 1.0], "break": [0.08, 1.0],
                "button": [0.12, 0.8]},
    "gate": {"max_inside_frac": 0.02, "inside_tol_m": 0.002, "max_mean_strain": 0.05,
             "max_p99_strain": 0.25, "max_settle_mm": 0.8, "min_wavelength_m": 0.012,
             "max_fold_m": 0.012, "retries": 1},
}


# --- poses -----------------------------------------------------------------------------------

def _dir(arm, name):
    b = arm.data.bones[name]
    return (b.tail_local - b.head_local).normalized()


def _rotate_bone(arm, name, q):
    """Rotate pose bone `name` by the armature-space rotation q about its head
    (its current posed matrix; parents must be up to date)."""
    pb = arm.pose.bones[name]
    M = pb.matrix.copy()
    h = M.translation.copy()
    R = q.to_matrix().to_4x4()
    pb.matrix = Matrix.Translation(h) @ R @ Matrix.Translation(-h) @ M
    bpy.context.view_layer.update()


def _toward(cur, axis, angle, want):
    """Quaternion about axis by +-angle, the sign chosen so want(rotated) is larger."""
    qa, qb = Quaternion(axis, angle), Quaternion(axis, -angle)
    return qa if want(qa @ cur) >= want(qb @ cur) else qb


def pose_rotations(arm, spec):
    """[(bone, Quaternion in armature space)] in hierarchy order for a pose spec."""
    out = []
    Z = Vector((0, 0, 1))
    for s in ("l", "r"):
        u = _dir(arm, f"upperarm_{s}")
        f = _dir(arm, f"lowerarm_{s}")
        if spec.get("arm_raise_deg"):
            ax = u.cross(Z).normalized()
            out.append((f"upperarm_{s}", _toward(u, ax, math.radians(spec["arm_raise_deg"]), lambda v: v.z)))
        if spec.get("elbow_open_deg"):
            ax = u.cross(f).normalized()
            q = Quaternion(ax, -math.radians(spec["elbow_open_deg"]))   # f toward u: opens the bend
            out.append((f"lowerarm_{s}", q))
        X = Vector((1, 0, 0))
        if spec.get("hip_deg"):
            t = _dir(arm, f"thigh_{s}")
            out.append((f"thigh_{s}", _toward(t, X, math.radians(spec["hip_deg"]), lambda v: -v.y)))
        if spec.get("knee_deg"):
            c = _dir(arm, f"calf_{s}")
            # flex the knee by twice the hip angle relative to the thigh: the shin
            # tilts back by knee - hip in world space
            out.append((f"calf_{s}", _toward(c, X, math.radians(spec["knee_deg"]), lambda v: v.y)))
    return out


def key_pose(arm, spec, frame):
    """Reset, apply the pose spec (hierarchy order), keyframe every touched bone."""
    for pb in arm.pose.bones:
        pb.rotation_mode = "QUATERNION"
        pb.rotation_quaternion = (1, 0, 0, 0)
        pb.location = (0, 0, 0)
    bpy.context.view_layer.update()
    order = {n: i for i, n in enumerate(["thigh_l", "thigh_r", "calf_l", "calf_r", "upperarm_l",
                                          "upperarm_r", "lowerarm_l", "lowerarm_r"])}
    rots = sorted(pose_rotations(arm, spec), key=lambda x: order.get(x[0], 99))
    for name, q in rots:
        _rotate_bone(arm, name, q)
    for pb in arm.pose.bones:
        pb.keyframe_insert("rotation_quaternion", frame=frame)
        pb.keyframe_insert("location", frame=frame)


# --- scene helpers ---------------------------------------------------------------------------

def _copy_rigged(src, arm, name, link_to):
    ob = src.copy()
    ob.data = src.data.copy()
    ob.name = name
    ob.parent = None
    ob.matrix_world = src.matrix_world.copy()
    for m in ob.modifiers:
        if m.type == "ARMATURE":
            m.object = arm
    link_to.objects.link(ob)
    return ob


def _evaluated_coords(ob):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    me = ev.to_mesh()
    n = len(me.vertices)
    co = np.empty(n * 3, np.float32)
    me.vertices.foreach_get("co", co)
    nor = np.empty(n * 3, np.float32)
    me.vertices.foreach_get("normal", nor)
    ev.to_mesh_clear()
    M = np.array(ob.matrix_world, np.float32)
    co = co.reshape(-1, 3) @ M[:3, :3].T + M[:3, 3]
    nor = nor.reshape(-1, 3) @ M[:3, :3].T
    nor /= np.maximum(np.linalg.norm(nor, axis=1, keepdims=True), 1e-9)
    return co, nor


def sim_mesh(garment, level, name, coll):
    """A simple subdivision of `garment` (UVs linear, vertex groups and face
    attributes interpolated), as a new object without modifiers."""
    tmp = garment.copy()
    tmp.data = garment.data.copy()
    tmp.modifiers.clear()
    coll.objects.link(tmp)
    if level:
        m = tmp.modifiers.new("sub", "SUBSURF")
        m.levels = m.render_levels = level
        m.subdivision_type = "SIMPLE"
        m.uv_smooth = "NONE"
        m.use_limit_surface = False
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(tmp.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
    me.name = name
    ob = bpy.data.objects.new(name, me)
    for g in garment.vertex_groups:
        ob.vertex_groups.new(name=g.name)
    ob.matrix_world = garment.matrix_world.copy()
    coll.objects.link(ob)
    old = tmp.data
    bpy.data.objects.remove(tmp, do_unlink=True)
    bpy.data.meshes.remove(old)
    return ob


def edges_of(me):
    e = np.empty(len(me.edges) * 2, np.int64)
    me.edges.foreach_get("vertices", e)
    return e.reshape(-1, 2)


def smooth_graph(vals, E, n, iters):
    """Uniform Laplacian smoothing of per-vertex values over the edge graph."""
    deg = np.bincount(E[:, 0], minlength=n) + np.bincount(E[:, 1], minlength=n)
    v = vals.astype(np.float64)
    for _ in range(iters):
        s = np.bincount(E[:, 0], weights=v[E[:, 1]], minlength=n) + \
            np.bincount(E[:, 1], weights=v[E[:, 0]], minlength=n)
        v = (v + s) / (1.0 + deg)
    return v


# --- landmarks and region masks --------------------------------------------------------------

def landmarks(arm, extra):
    """{region: [(point, direction or None)]} from the rig, plus builder extras
    (e.g. the fastened button) in `extra`."""
    J = lambda n: arm.matrix_world @ arm.data.bones[n].head_local   # noqa: E731
    T = lambda n: arm.matrix_world @ arm.data.bones[n].tail_local   # noqa: E731
    out = {}
    els = []
    for s in ("l", "r"):
        u = (T(f"upperarm_{s}") - J(f"upperarm_{s}")).normalized()
        f = (T(f"lowerarm_{s}") - J(f"lowerarm_{s}")).normalized()
        els.append((J(f"lowerarm_{s}"), (f - u).normalized()))   # the crook faces the bend
    out["elbow"] = els
    out["armpit"] = [(J(f"upperarm_{s}") + Vector((0, 0, -0.10)), None) for s in ("l", "r")]
    sp = J("spine_01")
    out["lower_back"] = [(Vector((0.0, sp.y + 0.10, sp.z - 0.03)), Vector((0, 1, 0)))]
    hl, hr = J("thigh_l"), J("thigh_r")
    out["crotch"] = [(Vector((0.0, hl.y - 0.05, hl.z - 0.10)), None)]
    out["knee_back"] = [(J(f"calf_{s}") + Vector((0, 0.04, 0.0)), Vector((0, 1, 0))) for s in ("l", "r")]
    out["break"] = [(J(f"foot_{s}") + Vector((0, -0.06, 0.05)), Vector((0, -1, 0))) for s in ("l", "r")]
    out.update(extra or {})
    return out


def region_mask(co, nor, lm, regions, base):
    """Per-vertex gain: max over regions of gain * gaussian(dist / r) * facing."""
    g = np.full(len(co), base, np.float64)
    names = {}
    for name, pts in lm.items():
        if name not in regions:
            continue
        r, gain = regions[name]
        acc = np.zeros(len(co))
        for p, d in pts:
            dist = np.linalg.norm(co - np.array(p, np.float64), axis=1)
            w = np.exp(-(dist / r) ** 2)
            if d is not None:
                w *= np.clip(0.5 + nor @ np.array(d, np.float64), 0.0, 1.0)
            acc = np.maximum(acc, w)
        names[name] = int((acc > 0.5).sum())
        g = np.maximum(g, base + (gain - base) * acc)
    return g, names


# --- the drape -------------------------------------------------------------------------------

class Fold:
    """Per sim-vertex fold height (metres) on a subdivided copy of a garment."""

    def __init__(self, garment, ob, h, stats):
        self.garment, self.ob, self.h, self.stats = garment, ob, h, stats

    def free(self):
        if self.ob is not None:
            me = self.ob.data
            bpy.data.objects.remove(self.ob, do_unlink=True)
            bpy.data.meshes.remove(me)
            self.ob = None


def _hash(*parts):
    h = hashlib.sha1()
    for p in parts:
        if isinstance(p, np.ndarray):
            h.update(np.ascontiguousarray(p).tobytes())
        else:
            h.update(json.dumps(p, sort_keys=True, default=str).encode())
    return h.hexdigest()[:20]


def _mesh_key(ob):
    me = ob.data
    co = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("co", co)
    pv = np.empty(len(me.loops), np.int32)
    me.loops.foreach_get("vertex_index", pv)
    return np.round(co, 5), pv


def cache_dir(b):
    root = os.environ.get("SUIT_DRAPE_CACHE")
    if not root:
        sysroot = b.cfg.get("assets", {}).get("system") or ""
        parts = os.path.abspath(sysroot).split(os.sep)
        if "data" in parts:
            root = os.sep.join(parts[:len(parts) - parts[::-1].index("data")] + ["cache", "suit_drape"])
        else:
            root = os.path.join(os.path.expanduser("~"), ".cache", "suit_drape")
    os.makedirs(root, exist_ok=True)
    return root


def run(b, D, garments, body, colliders=(), extra_landmarks=None):
    """garments: {key: (object, pin_fn(co[n,3], panel_per_vertex[n]) -> (pin[n], shrink[n]))}.
    Returns {key: Fold} (missing keys: gate failed or disabled) and stats."""
    t0 = time.perf_counter()
    stats = {"options": {k: D[k] for k in ("level", "frames", "ramp", "highpass_m", "base_gain")}}
    if not D["enabled"] or not garments:
        return {}, stats
    sc = bpy.context.scene
    coll = bpy.data.collections.new("_drape")
    sc.collection.children.link(coll)
    arm0 = b.armature()
    arm = arm0.copy()
    arm.data = arm0.data.copy()
    arm.name = "_drape_rig"
    arm.animation_data_clear()
    coll.objects.link(arm)
    lm = landmarks(arm0, extra_landmarks)

    # sim meshes and their cache keys
    sims = {}
    for key, (g, pin_fn) in garments.items():
        if key not in D["parts"]:
            continue
        ob = sim_mesh(g, D["level"], f"_drape_{key}", coll)
        me = ob.data
        n = len(me.vertices)
        co = np.empty(n * 3, np.float32)
        me.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)
        panel = np.zeros(n, np.int32)
        a = me.attributes.get("panel")
        if a is not None:
            fp = np.empty(len(me.polygons), np.int32)
            a.data.foreach_get("value", fp)
            for p in me.polygons:   # max tag over a vertex's faces
                for vi in p.vertices:
                    panel[vi] = max(panel[vi], fp[p.index])
        res = pin_fn(co, panel)
        pin, shrink = res[0], res[1]
        stiff = res[2] if len(res) > 2 else np.zeros(len(co))
        gco, topo = _mesh_key(g)
        k = _hash(key, topo, np.round(pin, 1).astype(np.float32), np.round(shrink, 1).astype(np.float32),
                  np.round(stiff, 1).astype(np.float32),
                  {k: D[k] for k in D if k not in ("enabled", "cache", "cache_tol_m")}, sorted(lm))
        sims[key] = {"g": g, "ob": ob, "pin": pin, "shrink": shrink, "stiff": stiff, "key": k,
                     "panel": panel, "gco": gco}
    root = cache_dir(b)

    def hit(s):
        path = os.path.join(root, s["key"] + ".npz")
        if not (D["cache"] and os.path.exists(path)):
            return False
        z = np.load(path, allow_pickle=False)
        if "gco" not in z or z["gco"].shape != s["gco"].shape:
            return False
        moved = float(np.abs(z["gco"] - s["gco"]).max())
        s["cache_moved_m"] = round(moved, 4)
        return moved <= D["cache_tol_m"]
    todo = [k for k, s in sims.items() if not hit(s)]
    stats["cache_dir"] = root
    stats["cached"] = sorted(set(sims) - set(todo))
    if todo:
        _simulate(b, D, {k: sims[k] for k in todo}, arm, body, colliders, coll, lm, stats)
    out = {}
    for key, s in sims.items():
        path = os.path.join(root, s["key"] + ".npz")
        if os.path.exists(path):
            z = np.load(path, allow_pickle=False)
            st = json.loads(str(z["stats"]))
            st["cache_moved_m"] = s.get("cache_moved_m", 0.0)
            stats[key] = st
            if st.get("gate_ok"):
                coll.objects.unlink(s["ob"])
                out[key] = Fold(s["g"], s["ob"], z["h"], st)
                continue
        me = s["ob"].data
        bpy.data.objects.remove(s["ob"], do_unlink=True)
        bpy.data.meshes.remove(me)
    # clean up the rig copy and colliders
    for ob in list(coll.objects):
        data = ob.data
        bpy.data.objects.remove(ob, do_unlink=True)
        if data is not None and data.users == 0:
            if isinstance(data, bpy.types.Mesh):
                bpy.data.meshes.remove(data)
            elif isinstance(data, bpy.types.Armature):
                bpy.data.armatures.remove(data)
    bpy.data.collections.remove(coll)
    stats["seconds"] = round(time.perf_counter() - t0, 2)
    return out, stats


def _simulate(b, D, sims, arm, body, colliders, coll, lm, stats):
    sc = bpy.context.scene
    F = D["fabric"]
    # rig motion P0 -> P1
    frame0, frame1, frame_end = 1, 1 + D["ramp"], D["frames"]
    key_pose(arm, D["pose"]["p0"], frame0)
    key_pose(arm, D["pose"]["p1"], frame1)
    # colliders follow the rig copy
    cols = []
    for src in [body] + list(colliders):
        c = _copy_rigged(src, arm, f"_drape_col_{src.name}", coll)
        cm = c.modifiers.new("Collision", "COLLISION")
        c.collision.thickness_outer = F["body_outer_m"]
        c.collision.thickness_inner = 0.02
        c.collision.cloth_friction = F["friction"]
        c.collision.damping = 0.5
        cols.append(c)
    attempts = {}
    for key, s in sims.items():
        attempts[key] = 0
    pending = dict(sims)
    while pending:
        cloths = {}
        for key, s in pending.items():
            ob = s["ob"]
            # fresh state each attempt: drop the old modifiers
            ob.modifiers.clear()
            for name, w in (("drape_pin", s["pin"]), ("drape_shrink", s["shrink"]),
                            ("drape_stiff", s["stiff"])):
                vg = ob.vertex_groups.get(name) or ob.vertex_groups.new(name=name)
                for val in np.unique(np.round(w, 2)):
                    idx = np.nonzero(np.round(w, 2) == val)[0].tolist()
                    if val > 0:
                        vg.add(idx, float(val), "REPLACE")
            am = ob.modifiers.new("Armature", "ARMATURE")
            am.object = arm
            m = ob.modifiers.new("Cloth", "CLOTH")
            st = m.settings
            bend = F["bending"] * (2.5 ** attempts[key])
            st.quality = D["quality"]
            st.mass = F["mass"]
            st.tension_stiffness = F["tension"]
            st.compression_stiffness = F["compression"]
            st.shear_stiffness = F["shear"]
            st.bending_stiffness = bend
            if s["stiff"].any():   # canvassed zones bend stiffer (weight 1 -> bending_max)
                st.vertex_group_bending = "drape_stiff"
                st.bending_stiffness_max = F["bending_max"] * (2.5 ** attempts[key])
            st.air_damping = F["air"]
            st.vertex_group_mass = "drape_pin"
            st.pin_stiffness = F["pin_stiffness"]
            if D["button_shrink"] and s["shrink"].any():
                st.vertex_group_shrink = "drape_shrink"
                st.shrink_min = 0.0
                st.shrink_max = D["button_shrink"]
            cs = m.collision_settings
            cs.collision_quality = D["collision_quality"]
            cs.distance_min = F["distance_m"]
            cs.use_self_collision = False
            m.point_cache.frame_start = frame0
            m.point_cache.frame_end = frame_end
            cloths[key] = (ob, m, bend)
        sc.frame_start, sc.frame_end = frame0, frame_end
        t = time.perf_counter()
        prev = {}
        for f in range(frame0, frame_end + 1):
            sc.frame_set(f)
            if f == frame_end - 1:
                for key, (ob, m, _) in cloths.items():
                    prev[key] = _evaluated_coords(ob)[0]
            if f == frame0:
                rest = {key: _evaluated_coords(ob)[0] for key, (ob, m, _) in cloths.items()}
        sim_s = time.perf_counter() - t
        sc.frame_set(frame_end)
        retry = {}
        for key, (ob, m, bend) in cloths.items():
            s = pending[key]
            cloth_co, _ = _evaluated_coords(ob)
            m.show_viewport = False
            skin_co, skin_n = _evaluated_coords(ob)
            m.show_viewport = True
            st = _measure(D, s, ob, rest[key], prev[key], cloth_co, skin_co, skin_n, cols[0], lm)
            st.update({"attempt": attempts[key], "bending": bend, "sim_s": round(sim_s, 2),
                       "verts": len(cloth_co), "frames": frame_end})
            stats.setdefault("attempts", []).append({key: {k: v for k, v in st.items() if k not in ("h", "hp_raw")}})
            h = st.pop("h")
            hp_raw = st.pop("hp_raw")
            dbg = os.environ.get("SUIT_DRAPE_DEBUG")
            if dbg:   # the raw drape, for bench/m1/suit_drape_view.py
                os.makedirs(dbg, exist_ok=True)
                np.savez_compressed(os.path.join(dbg, f"{key}_a{attempts[key]}.npz"), cloth=cloth_co,
                                    skin=skin_co, rest=rest[key], h=h, pin=s["pin"], hp=hp_raw)
            if st["gate_ok"] or attempts[key] >= D["gate"]["retries"]:
                path = os.path.join(cache_dir(b), s["key"] + ".npz")
                np.savez_compressed(path, h=h.astype(np.float32), gco=s["gco"], stats=json.dumps(st))
            else:
                attempts[key] += 1
                retry[key] = s
            ob.modifiers.clear()
        pending = retry
    sc.frame_set(1)
    for c in cols:
        pass   # removed with the collection by run()


def _measure(D, s, ob, rest, prev, cloth, skin, skin_n, body_col, lm):
    """Fold height, region gating and the drape gate."""
    G = D["gate"]
    me = ob.data
    E = edges_of(me)
    n = len(cloth)
    d = (cloth - skin).astype(np.float64)
    h = np.einsum("ij,ij->i", d, skin_n.astype(np.float64))
    el = np.linalg.norm(rest[E[:, 0]] - rest[E[:, 1]], axis=1)
    e_mean = float(el.mean())
    iters = int(max(4, min(400, (D["highpass_m"] / max(e_mean, 1e-4)) ** 2)))
    low = smooth_graph(h, E, n, iters)
    hp = h - low
    # light de-noise: the shortest wavelengths are sim noise, not folds
    hp = smooth_graph(hp, E, n, D["denoise_iters"])
    # regions are places on the garment: rest positions against the rest-pose
    # landmarks (the posed knee and foot move several cm away from them)
    gain, region_px = region_mask(np.asarray(rest, np.float64), skin_n.astype(np.float64), lm,
                                  D["regions"], D["base_gain"])
    c = D["clamp_m"]
    out = c * np.tanh(hp * gain / c)
    out *= (1.0 - np.clip(s["pin"], 0, 1) * 0.6)     # pinned canvas zones fold less
    # --- gate
    st = {}
    # penetration: cloth vertices inside the body (nearest skin point behind them)
    dg = bpy.context.evaluated_depsgraph_get()
    tree = BVHTree.FromObject(body_col, dg)
    inside = 0
    step = max(1, n // 6000)
    sample = range(0, n, step)
    for i in sample:
        p = Vector(cloth[i])
        hit = tree.find_nearest(p, 0.05)
        if hit[0] is not None and (p - hit[0]).dot(hit[1]) < -G["inside_tol_m"]:
            inside += 1
    st["inside_frac"] = round(inside / max(1, len(sample)), 4)
    lc = np.linalg.norm(cloth[E[:, 0]] - cloth[E[:, 1]], axis=1)
    strain = np.abs(lc / np.maximum(el, 1e-6) - 1.0)
    st["mean_strain"] = round(float(strain.mean()), 4)
    st["p99_strain"] = round(float(np.percentile(strain, 99)), 4)
    st["settle_mm"] = round(float(np.linalg.norm(cloth - prev, axis=1).mean() * 1000), 3)
    # fold wavelength ~ 2 pi rms(h) / rms(dh/ds) over the gated vertices
    w = gain > 0.5
    if w.sum() > 50:
        dh = (out[E[:, 0]] - out[E[:, 1]]) / np.maximum(el, 1e-6)
        we = w[E[:, 0]] & w[E[:, 1]]
        rms_h = float(np.sqrt((out[w] ** 2).mean()))
        rms_g = float(np.sqrt((dh[we] ** 2).mean())) if we.any() else 0.0
        st["fold_rms_mm"] = round(rms_h * 1000, 3)
        st["fold_wavelength_m"] = round(2 * math.pi * rms_h / max(rms_g, 1e-9), 4)
    else:
        st["fold_rms_mm"], st["fold_wavelength_m"] = 0.0, 0.0
    st["fold_max_mm"] = round(float(np.abs(out).max() * 1000), 3)
    st["raw_rms_mm"] = round(float(np.sqrt((hp ** 2).mean()) * 1000), 3)
    st["highpass_iters"] = iters
    st["edge_mean_m"] = round(e_mean, 4)
    st["region_verts"] = region_px
    fails = []
    if st["inside_frac"] > G["max_inside_frac"]:
        fails.append("penetration")
    if st["mean_strain"] > G["max_mean_strain"] or st["p99_strain"] > G["max_p99_strain"]:
        fails.append("strain")
    if st["settle_mm"] > G["max_settle_mm"]:
        fails.append("settle")
    if st["fold_wavelength_m"] and st["fold_wavelength_m"] < G["min_wavelength_m"]:
        fails.append("crumpled")
    if st["fold_max_mm"] > G["max_fold_m"] * 1000:
        fails.append("amplitude")
    st["gate_fails"] = fails
    st["gate_ok"] = not fails
    st["h"] = out
    st["hp_raw"] = hp
    return st


# --- rasterising into an atlas ---------------------------------------------------------------

def fold_uvs(fold, layout, side):
    """Per-loop atlas UVs of the sim mesh: its metric panel UVs mapped with the
    garment's packing layout (suit_textures.pack_group)."""
    me = fold.ob.data
    uv = me.uv_layers.active
    n = len(me.loops)
    a = np.empty(n * 2, np.float32)
    uv.data.foreach_get("uv", a)
    a = a.reshape(-1, 2).copy()
    tag = me.attributes.get("panel")
    fp = np.zeros(len(me.polygons), np.int32)
    if tag is not None:
        tag.data.foreach_get("value", fp)
    ls = np.empty(len(me.polygons), np.int32)
    me.polygons.foreach_get("loop_start", ls)
    lt = np.empty(len(me.polygons), np.int32)
    me.polygons.foreach_get("loop_total", lt)
    loop_tag = np.repeat(fp, lt)
    gname = fold.garment.name
    for t in np.unique(loop_tag):
        L = layout.get((gname, int(t)))
        if L is None:
            continue
        sel = loop_tag == t
        a[sel, 0] = (L["x0"] + a[sel, 0] - L["umin"]) / side
        a[sel, 1] = (L["y0"] + a[sel, 1] - L["vmin"]) / side
    return a


def rasterise(me, loop_uv, vert_vals, px, samples=5):
    """Splat per-vertex values over each triangle (barycentric grid) into a
    px x px image (normalised by coverage, gaps filled). Returns (img, cover)."""
    me.calc_loop_triangles()
    nt = len(me.loop_triangles)
    tl = np.empty(nt * 3, np.int64)
    me.loop_triangles.foreach_get("loops", tl)
    tl = tl.reshape(-1, 3)
    tv = np.empty(nt * 3, np.int64)
    me.loop_triangles.foreach_get("vertices", tv)
    tv = tv.reshape(-1, 3)
    uv = loop_uv[tl]                     # (T, 3, 2)
    vv = vert_vals[tv]                   # (T, 3)
    # adapt the barycentric grid to the triangle's pixel size
    span = np.max(np.abs(uv - uv[:, :1]), axis=(1, 2)) * px
    k = int(max(samples, min(16, np.percentile(span, 95) * 1.5 + 2)))
    bs = [(i / k, j / k) for i in range(k + 1) for j in range(k + 1 - i)]
    acc = np.zeros(px * px, np.float64)
    cnt = np.zeros(px * px, np.float64)
    for a, bb in bs:
        c = 1.0 - a - bb
        p = uv[:, 0] * c + uv[:, 1] * a + uv[:, 2] * bb
        v = vv[:, 0] * c + vv[:, 1] * a + vv[:, 2] * bb
        x = np.clip((p[:, 0] * px).astype(np.int64), 0, px - 1)
        y = np.clip((p[:, 1] * px).astype(np.int64), 0, px - 1)
        idx = y * px + x
        acc += np.bincount(idx, weights=v, minlength=px * px)
        cnt += np.bincount(idx, minlength=px * px)
    acc = acc.reshape(px, px)
    cnt = cnt.reshape(px, px)
    cover = cnt > 0
    img = np.where(cover, acc / np.maximum(cnt, 1), 0.0)
    # fill gaps (normalised convolution, a few rings) so the bilinear lookup at
    # island edges never reads zeros
    w = cover.astype(np.float64)
    vimg = img * w
    for _ in range(4):
        vimg = _box(vimg)
        w = _box(w)
        img = np.where(cover, img, np.where(w > 1e-6, vimg / np.maximum(w, 1e-9), 0.0))
    return img, cover


def _box(a):
    return (a + np.roll(a, 1, 0) + np.roll(a, -1, 0) + np.roll(a, 1, 1) + np.roll(a, -1, 1)) / 5.0
