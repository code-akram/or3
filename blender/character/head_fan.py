"""Optional private face layer: a per-vertex offset field on the base mesh.

Active only when the build has a fan config (build_character.py --fan FILE, or the FAN_CONFIG
environment variable), which adds a "fan" block to the build config:

    {"face_delta": "/abs/path/face_delta.npz",   # offsets for every base-mesh vertex
     "weight": 1.0,                              # shape-key value
     "dump_base": "/abs/path/base.npz"}          # optional: write the pre-delta base mesh here

The delta is applied in head.edit_base after the parametric edits and forms, as one shape key
("fan_face") on the live human before any proxy is fitted or the rig is added, so eyes, brows,
lashes, teeth, hair, clothes and the skeleton follow it and export.bake_targets bakes it with the
other targets. Helper geometry (eye, teeth, tongue, lash helpers, joint cubes) is offset with
the rest of the head by the same field.

With no fan config this module does nothing and the build is unchanged.

face_delta.npz holds "delta" (n, 3) in object space (metres) and, as a guard, "base" (n, 3): the
base-mesh coords it was computed against. A vertex-count mismatch is an error; a base that moved
(the public head changed since the delta was made) is reported in the build notes, with the
largest drift, and the delta is still applied.
"""

import numpy as np

from . import head_shape


def _faces(obj):
    me = obj.data
    n = len(me.polygons)
    ls = np.empty(n, np.int64)
    lt = np.empty(n, np.int64)
    me.polygons.foreach_get("loop_start", ls)
    me.polygons.foreach_get("loop_total", lt)
    lv = np.empty(len(me.loops), np.int64)
    me.loops.foreach_get("vertex_index", lv)
    return lv, ls, lt


def _groups(obj):
    """All vertex groups as a dense (n, G) float16 weight matrix plus names."""
    names = [g.name for g in obj.vertex_groups]
    W = np.zeros((len(obj.data.vertices), len(names)), np.float16)
    for v in obj.data.vertices:
        for vg in v.groups:
            W[v.index, vg.group] = vg.weight
    return names, W


def dump_base(b, obj, co, path):
    lv, ls, lt = _faces(obj)
    names, W = _groups(obj)
    cl = co[head_shape._group_weights(obj, "helper-l-eye") > 0].mean(0)
    cr = co[head_shape._group_weights(obj, "helper-r-eye") > 0].mean(0)
    np.savez_compressed(path, co=co, loop_verts=lv, poly_start=ls, poly_total=lt,
                        group_names=np.array(names), group_weights=W, eye_l=cl, eye_r=cr)
    b.notes.setdefault("fan", {})["dumped_base_verts"] = len(co)


def apply(b):
    fan = b.cfg.get("fan")
    if not fan:
        return None
    obj = b.basemesh
    co = head_shape._mix_coords(obj)
    notes = b.notes.setdefault("fan", {})
    if fan.get("dump_base"):
        dump_base(b, obj, co, fan["dump_base"])
    if not fan.get("face_delta"):
        return None
    d = np.load(fan["face_delta"])
    delta = np.asarray(d["delta"], np.float64)
    if delta.shape != co.shape:
        raise RuntimeError(f"fan face_delta has {delta.shape[0]} vertices, base mesh has {co.shape[0]}")
    if "base" in d:
        drift = np.linalg.norm(np.asarray(d["base"], np.float64) - co, axis=1)
        notes["base_drift_max_mm"] = round(float(drift.max()) * 1000, 3)
        if drift.max() > 1e-4:
            print(f"[fan] warning: base mesh moved since the delta was made (max {drift.max() * 1000:.2f} mm)")
    kb = obj.data.shape_keys.key_blocks
    basis = np.empty(len(co) * 3)
    kb[0].data.foreach_get("co", basis)
    key = obj.shape_key_add(name="fan_face", from_mix=False)
    key.data.foreach_set("co", (basis.reshape(-1, 3) + delta).ravel())
    key.value = float(fan.get("weight", 1.0))
    obj.data.update()
    moved = np.linalg.norm(delta, axis=1) * key.value
    notes.update({"weight": key.value, "max_move_mm": round(float(moved.max()) * 1000, 2),
                  "verts_moved_over_0.1mm": int((moved > 1e-4).sum())})
    return moved
