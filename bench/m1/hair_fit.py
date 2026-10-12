"""Hair-to-skin fit check on a look-dev run's GLB: where does the scalp cap's
edge (the feather band) sit against the *refined* body surface, and how much
hair lies inside the skin or the suit?

    blender -b --factory-startup --python bench/m1/hair_fit.py -- RUN_DIR

Prints, per cap edge ring (0 = open boundary), the signed distance of the
ring's vertices to the body (mm; negative = under the skin), and for the
whole hair mesh the share of vertices inside the body or the clothes. The
hair is built before head_refine (hair_clumps samples the low-res body), so
this is the only place the alignment is visible.
"""
import os
import sys

import bmesh
import bpy
from mathutils.bvhtree import BVHTree

RUN = os.path.abspath(sys.argv[sys.argv.index("--") + 1])
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
bpy.ops.import_scene.gltf(filepath=os.path.join(RUN, "character.glb"))
objs = {o.name: o for o in bpy.context.scene.objects if o.type == "MESH"}
hair = next(o for n, o in objs.items() if n.startswith("Human.hair"))
body = objs["Human"] if "Human" in objs else next(o for n, o in objs.items() if n == "Human_export")
suit = [o for n, o in objs.items() if ".suit_" in n and "shoes" not in n]


def bvh(obs):
    verts, polys = [], []
    for o in obs:
        base = len(verts)
        mw = o.matrix_world
        verts += [mw @ v.co for v in o.data.vertices]
        polys += [[base + i for i in p.vertices] for p in o.data.polygons]
    return BVHTree.FromPolygons(verts, polys, all_triangles=False)


skin = bvh([body])
cloth = bvh(suit) if suit else None


def signed(tree, p):
    loc, nrm, _, _ = tree.find_nearest(p)
    return (p - loc).dot(nrm) if loc is not None else 1e9


mw = hair.matrix_world
bm = bmesh.new()
bm.from_mesh(hair.data)
cap_mat = next(i for i, m in enumerate(hair.data.materials) if m and m.name.split(".")[0] == "hair")
cap = bmesh.new()
cap_faces = [f for f in bm.faces if f.material_index == cap_mat]
vmap = {}
for f in cap_faces:
    vs = []
    for v in f.verts:
        if v.index not in vmap:
            vmap[v.index] = cap.verts.new(v.co)
        vs.append(vmap[v.index])
    try:
        cap.faces.new(vs)
    except ValueError:
        pass
cap.verts.ensure_lookup_table()
ring = {v: 9 for v in cap.verts}
front = [v for v in cap.verts if v.is_boundary]
for d in range(4):
    nxt = []
    for v in front:
        if ring[v] > d:
            ring[v] = d
            nxt += [e.other_vert(v) for e in v.link_edges]
    front = [v for v in nxt if ring[v] > d]
print(f"cap faces {len(cap_faces)}  verts {len(cap.verts)}")
for d in range(4):
    ds = sorted(signed(skin, mw @ v.co) * 1000 for v in cap.verts if ring[v] == d)
    if ds:
        q = lambda f: ds[int(f * (len(ds) - 1))]
        buried = sum(1 for x in ds if x < 0)
        print(f"ring {d}: n {len(ds):4d}  mm p10 {q(0.1):6.2f}  p50 {q(0.5):6.2f}  p90 {q(0.9):6.2f}"
              f"  min {ds[0]:6.2f}  under skin {buried} ({100 * buried / len(ds):.0f}%)")
# Whole hair: under the skin (the buried root rows are ~8 % by design), and
# in the collar zone (the lowest 8 cm) how much lies within 4 mm of the suit,
# measured by true distance (garment shells are double-sided, so a signed
# distance to them means nothing).
n = len(bm.verts)
ins = sum(1 for v in bm.verts if signed(skin, mw @ v.co) < -0.0005)
print(f"hair verts {n}: {ins} ({100 * ins / n:.1f}%) more than 0.5 mm under the skin")
if cloth is not None:
    zmin = min((mw @ v.co).z for v in bm.verts)
    low = [mw @ v.co for v in bm.verts if (mw @ v.co).z < zmin + 0.08]
    dist = lambda p: cloth.find_nearest(p)[3]
    near = sum(1 for p in low if dist(p) < 0.004)
    touch = sum(1 for p in low if dist(p) < 0.0015)
    print(f"  collar zone (lowest 8 cm): {len(low)} verts, {near} ({100 * near / max(len(low), 1):.0f}%) "
          f"within 4 mm of the suit, {touch} ({100 * touch / max(len(low), 1):.0f}%) within 1.5 mm")
