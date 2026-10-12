"""Budget reductions on staged meshes (NOTES.md §7 budgets)."""

import bpy


def tris(o):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = o.evaluated_get(dg)
    me = ev.to_mesh()
    me.calc_loop_triangles()
    n = len(me.loop_triangles)
    ev.to_mesh_clear()
    return n


def decimate(o, max_tris):
    """Collapse-decimate o's own mesh to <= max_tris. Vertex groups (skin
    weights) and UVs are interpolated. Moved ahead of the armature modifier so
    the rest pose, not a deformed one, is reduced."""
    before = tris(o)
    if before <= max_tris:
        return before, before
    mod = o.modifiers.new("budget_decimate", "DECIMATE")
    mod.decimate_type = "COLLAPSE"
    mod.use_collapse_triangulate = True
    mod.ratio = max_tris / before
    with bpy.context.temp_override(object=o, active_object=o):
        bpy.ops.object.modifier_move_to_index(modifier=mod.name, index=0)
        bpy.ops.object.modifier_apply(modifier=mod.name)
    return before, tris(o)


def apply(b):
    done = {}
    for part, max_tris in b.cfg["budgets"]["decimate"].items():
        if not max_tris:  # null/0 in an override disables a default entry
            continue
        for o in b.meshes(part):
            before, after = decimate(o, max_tris)
            done[o.name] = {"before": before, "after": after}
    b.notes["decimated"] = done
