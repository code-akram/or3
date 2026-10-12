"""Per-mesh and rig statistics of the staged character."""

import bpy


def mesh_stats(objs, bone_names):
    out = {}
    dg = bpy.context.evaluated_depsgraph_get()
    for o in objs:
        if o.type != "MESH":
            continue
        ev = o.evaluated_get(dg)
        me = ev.to_mesh()
        me.calc_loop_triangles()
        tris = len(me.loop_triangles)
        nverts = len(me.vertices)
        ev.to_mesh_clear()
        idx_is_bone = {g.index: (g.name in bone_names) for g in o.vertex_groups}
        hist = {}
        for v in o.data.vertices:
            n = sum(1 for g in v.groups if idx_is_bone.get(g.group) and g.weight > 1e-4)
            hist[n] = hist.get(n, 0) + 1
        out[o.name] = {"tris": tris, "verts": nverts,
                       "materials": [m.name for m in o.data.materials if m],
                       "source_influence_histogram": dict(sorted(hist.items()))}
    return out


def collect(b):
    arm = b.armature()
    bone_names = set(bn.name for bn in arm.data.bones)
    s = {"meshes": mesh_stats(b.export_objs, bone_names),
         "bones": len(arm.data.bones),
         "deform_bones": sum(1 for bn in arm.data.bones if bn.use_deform)}
    s["total_tris"] = sum(m["tris"] for m in s["meshes"].values())
    return s
