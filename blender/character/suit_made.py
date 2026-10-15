"""The made (pattern-drafted, sewn, draped, rigged) suit in the character build (T13 item 8).

The made suit is built offline by the suit spike chain (bench/m1/v4/suit_made.sh: trousers, shirt,
waistcoat, jacket, then the posed rig run), because a full drape and the pose set take most of an
hour. Its result is cached under data/build/suit_cache/<body hash>.json, keyed on the body the
garments were draped on (the captured, unmasked rest body the lofted suit is built on too). A build
with cfg["suit"]["made"]["enabled"] looks the record up in suit.post and, when every guard passes,
swaps the lofted jacket, shirt, waistcoat, trousers and buttons for the made ones:

* the made parts come from the posed run's spike.blend (rig_spike_<garment>_<part>: weights over the
  armature's deform bones and helpers, one corrective shape key per suit cone, the atlases);
* they are joined per garment and named as the lofted ones (suit.PART), so hide_body, budgets and
  export treat them as the suit; each carries ["made_suit"] = 1, which deform_rig (no second weight
  remap, no tuck) and deform_correctives (no delta-mush keys) skip;
* rig.post appends the suit's cone rules (suit_rules.json) to character.rig.json and sets the skirt
  bones' follow gains to the fitted ones (rules()).

Guards (guards()): the body hash, each drape's stage-1 seam gap p95 < 3 mm and strain p99 < 25 %,
0 vertices inside the layers under it at rest and in every pose of the set (simulated and runtime),
and the determinism twins' hashes equal. A failing guard keeps the lofted suit and says why
(b.notes["suit"]["made"]).
"""

import hashlib
import json
import os

import numpy as np

GARMENTS = {"jacket": ("body", "rever", "pockets", "buttons", "buttonhole"),
            "shirt": ("shell", "collar", "cuffs", "buttons"),
            "waistcoat": ("shell", "pockets", "buttons"),
            "trousers": ("shell", "pockets", "buttons")}
LIMITS = {"seam_gap_p95_mm": 3.0, "strain_p99": 0.25, "inside": 0}


def body_hash(co):
    """sha256 of the rest body's vertex positions (metres, rounded to 0.01 mm), first 12 hex."""
    a = np.round(np.asarray(co, np.float64).reshape(-1, 3), 5)
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()[:12]


def mesh_hash(me):
    co = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get("co", co)
    return body_hash(co)


def data_root():
    """<main checkout>/data (the worktrees share the main checkout's data and private trees)."""
    import subprocess
    here = os.path.dirname(os.path.abspath(__file__))
    out = subprocess.run(["git", "-C", here, "rev-parse", "--path-format=absolute", "--git-common-dir"],
                         check=True, capture_output=True, text=True).stdout.strip()
    return os.path.join(os.path.dirname(out), "data")


def cache_root(data_root):
    return os.path.join(data_root, "build", "suit_cache")


def lookup(root, h):
    p = os.path.join(root, f"{h}.json")
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)


def _stats(run):
    with open(os.path.join(run, "spike_stats.json")) as f:
        return json.load(f)


def guards(rec, h, limits=LIMITS):
    """(ok, report): the cache record's runs against the limits."""
    rep, bad = {}, []
    if rec.get("body_hash") != h:
        bad.append(f"body hash {rec.get('body_hash')} != build {h}")
    for key in ("trousers", "shirt", "waistcoat", "jacket"):
        run = rec["runs"].get(key)
        if not run or not os.path.exists(os.path.join(run, "spike_stats.json")):
            bad.append(f"{key}: no run")
            continue
        st = _stats(run)
        gap = st.get("stage1_gap_mm", {}).get("p95")
        strain = st.get("strain_vs_flat", {}).get("p99_abs")
        inside = st.get("inside_after_push")
        rep[key] = {"seam_gap_p95_mm": gap, "strain_p99": strain, "inside": inside}
        if gap is None or gap >= limits["seam_gap_p95_mm"]:
            bad.append(f"{key}: seam gap p95 {gap} mm")
        if strain is None or strain >= limits["strain_p99"]:
            bad.append(f"{key}: strain p99 {strain}")
        if inside is not None and inside > limits["inside"]:
            bad.append(f"{key}: {inside} vertices inside at rest")
        twin = rec.get("twins", {}).get(key)
        if twin:
            th = _stats(twin).get("hash")
            same = th is not None and th == st.get("hash")
            rep[key]["determinism"] = same
            if not same:
                bad.append(f"{key}: determinism twin differs or has no hash")
    posed = rec["runs"].get("posed")
    if posed:
        st = _stats(posed)
        worst = {}
        for p, r in st.get("poses", {}).items():
            for tag in ("inside_sim", "inside_rt"):
                for k, v in r.get(tag, {}).items():
                    worst[f"{tag}.{k}"] = max(worst.get(f"{tag}.{k}", 0), v)
        rep["posed"] = {"inside_max": worst}
        if any(v > limits["inside"] for v in worst.values()):
            bad.append(f"posed: inside {worst}")
        twin = rec.get("twins", {}).get("posed")
        if twin:
            th = _stats(twin).get("hash")
            same = th is not None and th == st.get("hash")
            rep["posed"]["determinism"] = same
            if not same:
                bad.append("posed: determinism twin differs")
    else:
        bad.append("no posed (rig) run")
    rep["failures"] = bad
    return not bad, rep


def load_parts(posed_run):
    """Append the rig_* parts of the posed run's spike.blend. Returns {garment: [objects]}."""
    import bpy
    want = {f"rig_spike_{g}_{p}": g for g, ps in GARMENTS.items() for p in ps}
    with bpy.data.libraries.load(os.path.join(posed_run, "spike.blend"), link=False) as (src, dst):
        dst.objects = [n for n in src.objects if n in want]
    out = {}
    for o in dst.objects:
        if o is not None:
            out.setdefault(want[o.name], []).append(o)
    return out


def join(objs, name):
    """Join objects (shape keys and vertex groups merge by name) into one named `name`."""
    import bpy
    sc = bpy.context.scene.collection
    for o in objs:
        if o.name not in sc.objects:
            sc.objects.link(o)
    keys = sorted({kb.name for o in objs if o.data.shape_keys for kb in o.data.shape_keys.key_blocks[1:]})
    for o in objs:                      # every part gets every key (a zero key where it has none)
        if not o.data.shape_keys:
            o.shape_key_add(name="Basis")
        have = {kb.name for kb in o.data.shape_keys.key_blocks}
        for k in keys:
            if k not in have:
                o.shape_key_add(name=k, from_mix=False)
    with bpy.context.temp_override(active_object=objs[0], selected_editable_objects=objs, object=objs[0]):
        bpy.ops.object.join()
    ob = objs[0]
    ob.name = ob.data.name = name
    return ob


def swap(b, part_fmt, lofted, rec, arm):
    """Replace the lofted garments (dict key -> object, 'buttons' a list) with the made ones from the
    cache record. Returns {key: made object}."""
    import bpy
    from . import suit_ops
    parts = load_parts(rec["runs"]["posed"])
    made = {}
    stray = set()
    for g, objs in parts.items():
        for o in objs:                  # the rig run's armature modifiers (its own armature) go
            for md in list(o.modifiers):
                if md.type == "ARMATURE":
                    if md.object is not None and md.object != arm:
                        stray.add(md.object)
                    o.modifiers.remove(md)
            o.parent = None
        like = lofted.get(g)
        ob = join(objs, part_fmt.format(g) + "_made")
        if like is not None:
            ob.parent = like.parent
            ob.matrix_parent_inverse = like.matrix_parent_inverse.copy()
            for c in like.users_collection:
                if ob.name not in c.objects:
                    c.objects.link(ob)
            if ob.name in bpy.context.scene.collection.objects and bpy.context.scene.collection not in like.users_collection:
                bpy.context.scene.collection.objects.unlink(ob)
        mod = ob.modifiers.new("Armature", "ARMATURE")
        mod.object = arm
        ob["made_suit"] = 1
        made[g] = ob
    for g, o in lofted.items():
        if g in made or g == "buttons":
            for x in (o if isinstance(o, list) else [o]):
                if x is not None:
                    me = x.data
                    suit_ops.drop(b, x)
                    if me is not None and me.users == 0:
                        bpy.data.meshes.remove(me)
    for g, ob in made.items():
        ob.name = ob.data.name = part_fmt.format(g)
        if hasattr(b, "export_objs"):
            b.export_objs.append(ob)
    for a in stray:                     # appended along with the parts as a modifier target
        if a.name in bpy.data.objects and not a.users_collection:
            bpy.data.objects.remove(a, do_unlink=True)
    return made


def rules(posed_run):
    """The suit's cone rules and the skirt bones' fitted follow gains."""
    with open(os.path.join(posed_run, "suit_rules.json")) as f:
        return json.load(f)


def apply_rules(R, posed_run):
    """Append the suit cones to R["morphs"] and set the skirt follow gains (character.rig.json)."""
    sr = rules(posed_run)
    names = {m["name"] for m in R.get("morphs", [])}
    R.setdefault("morphs", []).extend(m for m in sr["morphs"] if m["name"] not in names)
    for h in R.get("helpers", []):
        if h["type"] == "follow" and h["bone"] in sr.get("follow_gains", {}):
            h["gain"] = sr["follow_gains"][h["bone"]]
    return {"cones": len(sr["morphs"]), "follow_gains": sorted(sr.get("follow_gains", {}))}
