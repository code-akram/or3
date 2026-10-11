"""Headless MPFB2 character build: human -> game_engine rig -> suit -> skinned GLB.

Spike 1 (NOTES.md §18). Run:

    blender -b -t 3 --factory-startup --python blender/build_character.py -- \
        --system-assets data/raw/makehuman/makehuman_system_assets/unpacked \
        --suit-assets   data/raw/makehuman/suits01/unpacked \
        --out           data/build/character/character.glb

--factory-startup keeps the user's saved scene/prefs out of the run; the MPFB
extension is enabled explicitly below. Asset roots are injected into MPFB's
in-memory preferences only (never saved), so nothing global is modified.

Writes <out>, <out minus .glb>.blend (the staged scene, for renders) and
<out minus .glb>.stats.json (per-step timings and mesh/rig statistics).
"""

import argparse
import importlib
import json
import os
import sys
import time

import addon_utils
import bpy


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--system-assets", required=True)
    ap.add_argument("--suit-assets", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--suit", default="toigo_male_suit_tie_and_jacket.mhclo")
    ap.add_argument("--shoes", default="shoes04.mhclo")  # black dress shoes
    ap.add_argument("--hair", default="long01.mhclo")
    ap.add_argument("--skin", default="young_caucasian_male.mhmat")
    ap.add_argument("--rig", default="game_engine")
    ap.add_argument("--max-influences", type=int, default=4)
    return ap.parse_args(argv)


ARGS = parse_args()
TIMINGS = {}
_T0 = time.perf_counter()


class step:
    """Context manager that records wall time of one pipeline step."""

    def __init__(self, name):
        self.name = name

    def __enter__(self):
        self.t = time.perf_counter()
        print(f"[build] {self.name} ...", flush=True)

    def __exit__(self, *exc):
        dt = time.perf_counter() - self.t
        TIMINGS[self.name] = round(dt, 3)
        print(f"[build] {self.name}: {dt:.2f} s", flush=True)
        return False


def mpfb_module_name():
    for mod in addon_utils.modules():
        if mod.__name__.endswith(".mpfb") or mod.__name__ == "mpfb":
            return mod.__name__
    raise RuntimeError("MPFB extension not installed; run blender/install_mpfb.sh")


def mpfb_import(pkg, sub, key):
    return getattr(importlib.import_module(f"{pkg}.{sub}"), key)


# --------------------------------------------------------------------------
with step("enable_mpfb"):
    PKG = mpfb_module_name()
    addon_utils.enable(PKG, default_set=True, persistent=False)
    prefs = bpy.context.preferences.addons[PKG].preferences
    # Two packs, two roots: second_root + mh_user_data are both plain data
    # roots in MPFB's asset search (AssetService.get_available_data_roots).
    prefs.mpfb_second_root = os.path.abspath(ARGS.system_assets)
    prefs.mh_user_data = os.path.abspath(ARGS.suit_assets)
    LocationService = mpfb_import(PKG, "services.locationservice", "LocationService")
    LocationService.update_second_root()
    LocationService.update_mh_data()
    HumanService = mpfb_import(PKG, "services.humanservice", "HumanService")
    AssetService = mpfb_import(PKG, "services.assetservice", "AssetService")
    ExportService = mpfb_import(PKG, "services.exportservice", "ExportService")
    ObjectService = mpfb_import(PKG, "services.objectservice", "ObjectService")
    TargetService = mpfb_import(PKG, "services.targetservice", "TargetService")

# Empty scene (factory startup has a cube, camera, light).
for _o in list(bpy.data.objects):
    bpy.data.objects.remove(_o, do_unlink=True)


def find(fname, subdir):
    path = AssetService.find_asset_absolute_path(fname, asset_subdir=subdir)
    if path is None:
        raise RuntimeError(f"asset {subdir}/{fname} not found in MPFB data roots")
    return path


# --------------------------------------------------------------------------
with step("create_human"):
    macro = TargetService.get_default_macro_info_dict()
    macro.update({"gender": 1.0, "age": 0.55, "muscle": 0.6, "weight": 0.5,
                  "height": 0.6, "proportions": 0.6})
    macro["race"] = {"caucasian": 0.6, "asian": 0.3, "african": 0.1}
    basemesh = HumanService.create_human(macro_detail_dict=macro)

with step("skin"):
    HumanService.set_character_skin(find(ARGS.skin, "skins"), basemesh,
                                    skin_type="GAMEENGINE")

with step("rig"):
    HumanService.add_builtin_rig(basemesh, ARGS.rig)

with step("bodyparts"):
    for subdir, fname, atype in [("eyes", "low-poly.mhclo", "Eyes"),
                                 ("eyebrows", "eyebrow001.mhclo", "Eyebrows"),
                                 ("eyelashes", "eyelashes01.mhclo", "Eyelashes"),
                                 ("teeth", "teeth_base.mhclo", "Teeth"),
                                 ("tongue", "tongue01.mhclo", "Tongue"),
                                 ("hair", ARGS.hair, "Hair")]:
        HumanService.add_mhclo_asset(find(fname, subdir), basemesh, asset_type=atype,
                                     subdiv_levels=0, material_type="GAMEENGINE")

with step("suit"):
    HumanService.add_mhclo_asset(find(ARGS.suit, "clothes"), basemesh, asset_type="Clothes",
                                 subdiv_levels=0, material_type="GAMEENGINE")
    HumanService.add_mhclo_asset(find(ARGS.shoes, "clothes"), basemesh, asset_type="Clothes",
                                 subdiv_levels=0, material_type="GAMEENGINE")

with step("stage_for_export"):
    export_root = ExportService.create_character_copy(basemesh, name_suffix="_export")
    export_basemesh = ObjectService.find_object_of_type_amongst_nearest_relatives(
        export_root, "Basemesh")
    ExportService.bake_modifiers_remove_helpers(export_basemesh, bake_masks=True,
                                                bake_subdiv=True, remove_helpers=True,
                                                also_proxy=True)
    export_objs = [export_root] + list(ObjectService.get_list_of_children(export_root))
    # Drop the un-staged original so the saved .blend holds only what ships.
    keep = set(o.name for o in export_objs)
    for o in list(bpy.data.objects):
        if o.name not in keep:
            bpy.data.objects.remove(o, do_unlink=True)

# Assets whose texture alpha is a cut-out; everything else ships opaque.
CUTOUT_ASSETS = ("eyebrow", "eyelashes", ARGS.hair.rsplit(".", 1)[0])


def fix_material_alpha(mat, cutout):
    """MPFB GAMEENGINE materials wire texture alpha into every BSDF, which the
    glTF exporter turns into alphaMode BLEND for all of them (sorting
    artefacts, no depth write). Opaque materials: drop the link. Cut-outs:
    route alpha through Math ROUND, which the exporter maps to MASK @ 0.5."""
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


with step("bake_targets_and_alpha"):
    # MPFB keeps the macro targets (gender, age, ...) as shape keys on the
    # basemesh; the glTF exporter would ship the un-morphed Basis, leaving the
    # body shorter than the rig and clothes. Bake them in.
    alpha_modes = {}
    for o in export_objs:
        if o.type == "MESH" and o.data.shape_keys:
            TargetService.bake_targets(o)
        if o.type == "MESH":
            for m in o.data.materials:
                if m and m.node_tree and m.name not in alpha_modes:
                    alpha_modes[m.name] = fix_material_alpha(
                        m, any(c in o.name for c in CUTOUT_ASSETS))


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


with step("stats"):
    arm = next(o for o in export_objs if o.type == "ARMATURE")
    bone_names = set(b.name for b in arm.data.bones)
    stats = {"meshes": mesh_stats(export_objs, bone_names), "alpha_modes": alpha_modes,
             "bones": len(arm.data.bones),
             "deform_bones": sum(1 for b in arm.data.bones if b.use_deform)}
    stats["total_tris"] = sum(m["tris"] for m in stats["meshes"].values())

out = os.path.abspath(ARGS.out)
os.makedirs(os.path.dirname(out), exist_ok=True)
stem = out[:-4] if out.endswith(".glb") else out

with step("export_glb"):
    bpy.ops.object.select_all(action="DESELECT")
    for o in export_objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = export_root
    bpy.ops.export_scene.gltf(
        filepath=out, export_format="GLB", use_selection=True,
        export_skins=True, export_influence_nb=ARGS.max_influences,
        export_all_influences=False, export_animations=False,
        export_morph=False, export_yup=True, export_apply=False,
        export_tangents=True,
        export_image_format="AUTO")

with step("save_blend"):
    bpy.ops.wm.save_as_mainfile(filepath=stem + ".blend", compress=True)

stats["timings_s"] = TIMINGS
stats["total_s"] = round(time.perf_counter() - _T0, 3)
stats["glb_bytes"] = os.path.getsize(out)
stats["blender"] = bpy.app.version_string
stats["threads"] = bpy.context.scene.render.threads
stats["args"] = vars(ARGS)
with open("/proc/loadavg") as f:
    stats["loadavg_end"] = f.read().strip()
with open(stem + ".stats.json", "w") as f:
    json.dump(stats, f, indent=2)
print(json.dumps({k: v for k, v in stats.items() if k != "meshes"}, indent=2))
for name, m in stats["meshes"].items():
    print(f"  {name:40s} tris={m['tris']:6d} verts={m['verts']:6d} "
          f"infl={m['source_influence_histogram']}")
