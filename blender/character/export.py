"""Staging and glTF export, with the two fixes MPFB's path needs (spike 1)."""

import os

import bpy


def stage(b):
    """Copy the human, bake clothes masks, strip helpers; drop the original so
    only what ships remains in the scene (and in the saved .blend)."""
    m = b.mpfb
    b.export_root = m.ExportService.create_character_copy(b.basemesh, name_suffix="_export")
    export_basemesh = m.ObjectService.find_object_of_type_amongst_nearest_relatives(
        b.export_root, "Basemesh")
    m.ExportService.bake_modifiers_remove_helpers(export_basemesh, bake_masks=True,
                                                  bake_subdiv=True, remove_helpers=True,
                                                  also_proxy=True)
    b.export_objs = [b.export_root] + list(m.ObjectService.get_list_of_children(b.export_root))
    keep = set(o.name for o in b.export_objs)
    for o in list(bpy.data.objects):
        if o.name not in keep:
            bpy.data.objects.remove(o, do_unlink=True)
    b.basemesh = None


def bake_targets(b):
    """MPFB keeps the macro targets as shape keys; with export_morph=False the
    exporter would write the un-morphed Basis (head at chest height). Bake."""
    for o in b.meshes():
        if o.data.shape_keys:
            b.mpfb.TargetService.bake_targets(o)


def _fix_material_alpha(mat, cutout):
    """GAMEENGINE materials wire texture alpha into every BSDF, which glTF
    exports as BLEND. Opaque: drop the link. Cut-out: route alpha through Math
    ROUND, which the exporter maps to MASK @ 0.5."""
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    link = next((l for l in nt.links if l.to_node == bsdf and l.to_socket.name == "Alpha"), None)
    if link is None:
        return "OPAQUE"
    src = link.from_socket
    nt.links.remove(link)
    bsdf.inputs["Alpha"].default_value = 1.0
    if not cutout:
        return "OPAQUE"
    rnd = nt.nodes.new("ShaderNodeMath")
    rnd.operation = "ROUND"
    nt.links.new(src, rnd.inputs[0])
    nt.links.new(rnd.outputs[0], bsdf.inputs["Alpha"])
    return "MASK"


def fix_alpha(b):
    modes = {}
    for o in b.meshes():
        for mat in o.data.materials:
            if mat and mat.node_tree and mat.name not in modes:
                modes[mat.name] = _fix_material_alpha(
                    mat, any(c in o.name for c in b.cutouts))
    b.notes["alpha_modes"] = modes


HERO_ONLY = "hero_only"


def hero_collection():
    """Collection for render-only hero geometry (e.g. strand grooms for the
    Cycles hero renders). It is saved in the .blend but never exported."""
    col = bpy.data.collections.get(HERO_ONLY)
    if col is None:
        col = bpy.data.collections.new(HERO_ONLY)
        bpy.context.scene.collection.children.link(col)
    return col


def _hero_only(o):
    return any(c.name == HERO_ONLY for c in o.users_collection)


def write_glb(b, out):
    os.makedirs(os.path.dirname(out), exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    for o in b.export_objs:
        if not _hero_only(o):
            o.select_set(True)
    bpy.context.view_layer.objects.active = b.export_root
    bpy.ops.export_scene.gltf(
        filepath=out, export_format="GLB", use_selection=True,
        export_skins=True, export_influence_nb=b.cfg["export"]["max_influences"],
        export_all_influences=False, export_animations=False,
        export_morph=False, export_yup=True, export_apply=False,
        export_tangents=True, export_image_format="AUTO")


def save_blend(b, path):
    bpy.ops.wm.save_as_mainfile(filepath=path, compress=True)
