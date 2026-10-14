"""Face identity layer: one per-vertex offset field on the base mesh, public or private.

Two sources, one code path (head.edit_base, after head_shape and head_forms, before head_sculpt):

  public   head.identity: the original public face (pipeline/likeness/author_public.py), an
           ICT-FaceKit identity authored from the brief and wrapped onto this base mesh:

               "identity": {"delta": "$DATA/build/identity/public_face.npz",
                            "coeffs": "$REPO/bench/m1/variants/public_identity.json",
                            "base_embedding": "$DATA/build/identity/base_embedding.npz",
                            "ict_embedding": "$DATA/build/identity/ict_embedding.npz",
                            "ict": "$DATA/raw/ict-facekit", "weight": 1.0, "auto": true}

           With "auto", a missing delta, or one made against a base that has since moved more than
           "max_drift_mm" (the head targets, edits or forms changed), is rebuilt: the base is
           dumped next to the delta and author_public.py wrap runs in the likeness venv
           ("python", default <main>/private/venvs/likeness/bin/python; a tool, not data).
           $DATA is <main checkout>/data, $REPO this checkout.

  private  fan (build_character.py --fan FILE adds a "fan" block; such a build writes under
           <main checkout>/private/ only, see containment.py): the likeness tribute,

               {"face_delta": "/abs/path/face_delta.npz", "weight": 1.0,
                "dump_base": "/abs/path/base.npz"}

           A fan block REPLACES the public identity (the public delta is not applied); the same
           sculpt layer (head_sculpt) runs on top of either.

The delta is one shape key ("identity_face" or "fan_face") on the live human before any proxy is
fitted or the rig is added, so eyes, brows, lashes, teeth, hair, clothes and the skeleton follow it
and export.bake_targets bakes it with the other targets. Helper geometry moves with the field.

The .npz holds "delta" (n, 3) in object space (metres) and, as a guard, "base" (n, 3): the coords
it was computed against. A vertex-count mismatch is an error; drift is reported in the notes.
"""

import json
import os
import subprocess
import sys

import numpy as np

from . import head_shape

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


def _main_root():
    sys.path.append(os.path.join(REPO, "pipeline", "likeness"))
    import containment
    return str(containment.main_root())


def resolve(path):
    if not path:
        return path
    return path.replace("$DATA", os.path.join(_main_root(), "data")).replace("$REPO", REPO)


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


def dump_base(obj, co, path):
    lv, ls, lt = _faces(obj)
    names, W = _groups(obj)
    cl = co[head_shape._group_weights(obj, "helper-l-eye") > 0].mean(0)
    cr = co[head_shape._group_weights(obj, "helper-r-eye") > 0].mean(0)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    np.savez_compressed(path, co=co, loop_verts=lv, poly_start=ls, poly_total=lt,
                        group_names=np.array(names), group_weights=W, eye_l=cl, eye_r=cr)


def _drift(path, co):
    try:
        d = np.load(path)
    except (OSError, ValueError):
        return None
    if "base" not in d or d["base"].shape != co.shape:
        return None
    return float(np.linalg.norm(np.asarray(d["base"], np.float64) - co, axis=1).max())


def _coeffs_changed(path, coeffs_path):
    """True when the delta was authored from other coefficients than the file now holds."""
    try:
        spec = json.load(open(coeffs_path))
        c = np.zeros(len(np.load(path)["coeffs"]))
        for k, v in (spec.get("coefficients") or {}).items():
            c[int(k)] = float(v)
        return not np.allclose(c, np.load(path)["coeffs"])
    except (OSError, ValueError, KeyError):
        return True


def build_identity(ident, obj, co, path, notes):
    """Dump the base next to the delta and run author_public.py wrap (likeness venv)."""
    base = os.path.splitext(path)[0] + "_base.npz"
    dump_base(obj, co, base)
    py = resolve(ident.get("python") or "$DATA/../private/venvs/likeness/bin/python")
    py = os.path.normpath(py)
    cmd = [py, "-I", os.path.join(REPO, "pipeline", "likeness", "author_public.py"), "wrap",
           "--ict", resolve(ident.get("ict", "$DATA/raw/ict-facekit")),
           "--coeffs", resolve(ident["coeffs"]),
           "--base", base,
           "--base-embedding", resolve(ident["base_embedding"]),
           "--ict-embedding", resolve(ident["ict_embedding"]),
           "--out", path]
    print("[head_layer] building the public identity delta:", " ".join(os.path.basename(c) for c in cmd[2:4]), flush=True)
    env = dict(os.environ, OMP_NUM_THREADS="3", OPENBLAS_NUM_THREADS="3")
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    print(r.stdout[-2000:], r.stderr[-2000:], flush=True)
    if r.returncode != 0:
        raise RuntimeError(f"author_public.py wrap failed ({r.returncode})")
    notes["rebuilt"] = True


def apply(b):
    fan = b.cfg.get("fan")
    ident = b.cfg["head"].get("identity")
    obj = b.basemesh
    co = head_shape._mix_coords(obj)
    if fan:
        notes = b.notes.setdefault("fan", {})
        if fan.get("dump_base"):
            dump_base(obj, co, fan["dump_base"])
            notes["dumped_base_verts"] = len(co)
        path, weight, key_name = fan.get("face_delta"), float(fan.get("weight", 1.0)), "fan_face"
    elif ident:
        notes = b.notes.setdefault("head_layer", {"source": "identity"})
        path, weight, key_name = resolve(ident.get("delta")), float(ident.get("weight", 1.0)), "identity_face"
        if ident.get("dump_base"):
            dump_base(obj, co, resolve(ident["dump_base"]))
        if path and ident.get("auto", True) and ident.get("coeffs"):
            drift = _drift(path, co) if os.path.exists(path) else None
            if drift is None or drift * 1000 > float(ident.get("max_drift_mm", 0.5)) \
                    or _coeffs_changed(path, resolve(ident["coeffs"])):
                build_identity(ident, obj, co, path, notes)
        notes["coeffs"] = ident.get("coeffs")
    else:
        return None
    if not path:
        return None
    d = np.load(path)
    delta = np.asarray(d["delta"], np.float64)
    if delta.shape != co.shape:
        raise RuntimeError(f"{key_name} delta has {delta.shape[0]} vertices, base mesh has {co.shape[0]}")
    if "base" in d:
        drift = np.linalg.norm(np.asarray(d["base"], np.float64) - co, axis=1)
        notes["base_drift_max_mm"] = round(float(drift.max()) * 1000, 3)
        if drift.max() > 1e-4:
            print(f"[head_layer] warning: base mesh moved since the delta was made (max {drift.max() * 1000:.2f} mm)")
    if "prior" in d:
        notes["prior"] = str(d["prior"])
    if "notes" in d:
        try:
            w = json.loads(str(d["notes"]))
            notes["wrap"] = {k: w[k] for k in ("landmark_rms_final_mm", "max_move_mm", "shared_landmarks") if k in w}
        except ValueError:
            pass
    kb = obj.data.shape_keys.key_blocks
    basis = np.empty(len(co) * 3)
    kb[0].data.foreach_get("co", basis)
    key = obj.shape_key_add(name=key_name, from_mix=False)
    key.data.foreach_set("co", (basis.reshape(-1, 3) + delta).ravel())
    key.value = weight
    obj.data.update()
    moved = np.linalg.norm(delta, axis=1) * key.value
    notes.update({"weight": key.value, "max_move_mm": round(float(moved.max()) * 1000, 2),
                  "verts_moved_over_0.1mm": int((moved > 1e-4).sum())})
    return moved
