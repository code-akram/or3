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
                src = r.get("inside_rt_visible", r.get(tag, {})) if tag == "inside_rt" else r.get(tag, {})
                for k, v in src.items():
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


def load_lod(run, garment, k):
    """The garment run's collapse-decimated LOD k (spike_<garment>_lod<k>), or None."""
    import bpy
    nm = f"spike_{garment}_lod{k}"
    with bpy.data.libraries.load(os.path.join(run, "spike.blend"), link=False) as (src, dst):
        dst.objects = [n for n in src.objects if n == nm]
    o = dst.objects[0] if dst.objects else None
    if o is not None:
        bpy.context.scene.collection.objects.link(o)
    return o


def lod_from(src, lod):
    """Skin the decimated `lod` from the skinned full-resolution `src` (one joined object): each LOD
    vertex goes to its nearest point on the source's rest surface (the LODs were cut before the
    layers were pressed under the jacket) and takes that point's barycentric weights and shape-key
    deltas."""
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    me = src.data
    me.calc_loop_triangles()
    nv = len(me.vertices)
    V = np.empty(nv * 3)
    me.vertices.foreach_get("co", V)
    V = V.reshape(-1, 3)
    T = np.empty(len(me.loop_triangles) * 3, np.int64)
    me.loop_triangles.foreach_get("vertices", T)
    T = T.reshape(-1, 3)
    bvh = BVHTree.FromPolygons([tuple(map(float, v)) for v in V], [tuple(map(int, t)) for t in T])
    gi = {g.index: g.name for g in src.vertex_groups}
    Wt = np.zeros((nv, len(gi)))
    for v in me.vertices:
        for ge in v.groups:
            Wt[v.index, ge.group] = ge.weight
    keys = []
    if me.shape_keys:
        for kb in me.shape_keys.key_blocks[1:]:
            d = np.empty(nv * 3)
            kb.data.foreach_get("co", d)
            keys.append((kb.name, d.reshape(-1, 3) - V))
    lm = lod.data
    P = np.empty(len(lm.vertices) * 3)
    lm.vertices.foreach_get("co", P)
    P = P.reshape(-1, 3)
    Q = np.zeros_like(P)
    WL = np.zeros((len(P), Wt.shape[1]))
    DL = [np.zeros_like(P) for _ in keys]
    for i, p in enumerate(P):
        loc, _, fi, _ = bvh.find_nearest(Vector(p))
        a, b_, c = V[T[fi]]
        q = np.array(loc)
        v0, v1, v2 = b_ - a, c - a, q - a
        d00, d01, d11 = v0 @ v0, v0 @ v1, v1 @ v1
        d20, d21 = v2 @ v0, v2 @ v1
        den = d00 * d11 - d01 * d01
        if abs(den) < 1e-18:
            bc = np.array([1.0, 0.0, 0.0])
        else:
            y = (d11 * d20 - d01 * d21) / den
            z = (d00 * d21 - d01 * d20) / den
            bc = np.clip(np.array([1 - y - z, y, z]), 0, 1)
            bc /= bc.sum()
        Q[i] = q
        WL[i] = bc @ Wt[T[fi]]
        for j, (_, D) in enumerate(keys):
            DL[j][i] = bc @ D[T[fi]]
    lm.vertices.foreach_set("co", Q.ravel())
    lm.update()
    lod.vertex_groups.clear()
    for j in range(Wt.shape[1]):
        g = lod.vertex_groups.new(name=gi[j])
        for i in np.nonzero(WL[:, j] > 1e-4)[0]:
            g.add([int(i)], float(WL[i, j]), "REPLACE")
    if lm.shape_keys:
        lod.shape_key_clear()
    if keys:
        lod.shape_key_add(name="Basis")
        for (nm, _), D in zip(keys, DL):
            kb = lod.shape_key_add(name=nm, from_mix=False)
            kb.data.foreach_set("co", (Q + D).astype(np.float32).ravel())
    return {"verts": len(P), "keys": len(keys)}


def swap(b, part_fmt, lofted, rec, arm, lods=None):
    """Replace the lofted garments (dict key -> object, 'buttons' a list) with the made ones from the
    cache record; lods {garment: k} skins each garment's LOD k from its full-resolution part instead
    (lod_from). Returns ({key: made object}, info)."""
    import bpy
    from . import suit_ops
    parts = load_parts(rec["runs"]["posed"])
    made = {}
    info = {}
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
        k = (lods or {}).get(g, 0)
        if k:
            lo = load_lod(rec["runs"][g], g, k)
            if lo is not None:
                info[g] = {"lod": k, **lod_from(ob, lo)}
                lo.parent = ob.parent
                lo.matrix_parent_inverse = ob.matrix_parent_inverse.copy()
                for c in ob.users_collection:
                    if lo.name not in c.objects:
                        c.objects.link(lo)
                for c in list(lo.users_collection):
                    if c not in ob.users_collection:
                        c.objects.unlink(lo)
                me0 = ob.data
                bpy.data.objects.remove(ob, do_unlink=True)
                bpy.data.meshes.remove(me0)
                ob = lo
                ob.name = ob.data.name = part_fmt.format(g) + "_made"
        info.setdefault(g, {"lod": 0})
        info[g]["tris"] = sum(len(p.vertices) - 2 for p in ob.data.polygons)
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
    copy_wrinkles(rec["runs"]["posed"], getattr(b, "out_dir", None))
    for a in stray:                     # appended along with the parts as a modifier target
        if a.name in bpy.data.objects and not a.users_collection:
            bpy.data.objects.remove(a, do_unlink=True)
    return made, info


def copy_wrinkles(posed_run, out_dir):
    """The rig run's wrinkle maps (suit_wrinkle.json and its layers) next to the GLB (cloth.ts)."""
    import shutil
    src = os.path.join(posed_run, "suit_wrinkle.json")
    if not out_dir or not os.path.exists(src):
        return []
    os.makedirs(out_dir, exist_ok=True)
    with open(src) as f:
        j = json.load(f)
    files = ["suit_wrinkle.json"] + [x for fs in j["materials"].values() for x in fs]
    for x in files:
        shutil.copyfile(os.path.join(posed_run, x), os.path.join(out_dir, x))
    return files


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
