"""Staging and glTF export, with the two fixes MPFB's path needs (spike 1),
the runtime sidecars next to the GLB (write_sidecars) and the optional KTX2
post-step (ktx2)."""

import json
import os
import struct
import zlib

import bpy
import numpy as np


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
    if mat.get("alpha_blend"):   # T18: a blended overlay by design (the eye lid shell, the tear meniscus)
        return "BLEND"
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


def unweighted_verts(b):
    """Exported skinned meshes' vertices with no weight on a deform bone (the
    glTF exporter would add a `neutral_bone` joint for them)."""
    out = {}
    for o in b.export_objs:
        mod = next((m for m in o.modifiers if m.type == "ARMATURE"), None) \
            if o.type == "MESH" and not _hero_only(o) else None
        if mod is None or mod.object is None:
            continue
        deform = {bn.name for bn in mod.object.data.bones if bn.use_deform}
        ok = {g.index for g in o.vertex_groups if g.name in deform}
        n = sum(1 for v in o.data.vertices
                if not any(e.group in ok and e.weight > 0 for e in v.groups))
        if n:
            out[o.name] = n
    return out


def write_glb(b, out):
    os.makedirs(os.path.dirname(out), exist_ok=True)
    bad = unweighted_verts(b)
    if bad:
        raise RuntimeError(f"unweighted vertices (would export neutral_bone): {bad}")
    bpy.ops.object.select_all(action="DESELECT")
    for o in b.export_objs:
        if not _hero_only(o):
            o.select_set(True)
    bpy.context.view_layer.objects.active = b.export_root
    # corrective morph targets (rig.post / deform_correctives) are the only
    # shape keys left after bake_targets
    morph = any(o.type == "MESH" and o.data.shape_keys for o in b.export_objs)
    bpy.ops.export_scene.gltf(
        filepath=out, export_format="GLB", use_selection=True,
        export_skins=True, export_influence_nb=b.cfg["export"]["max_influences"],
        export_all_influences=False, export_animations=False,
        export_morph=morph, export_morph_normal=morph, export_yup=True, export_apply=False,
        export_tangents=True, export_image_format="AUTO")
    pack_hair_maps(b, out)
    from . import skin_tex
    skin_tex.pack_orm(b, out)  # T17: the skin ORM's blue (specular cavity) back into the GLB
    write_sidecars(b, out)


def _read_glb(path):
    with open(path, "rb") as f:
        data = f.read()
    magic, version, length = struct.unpack_from("<4sII", data, 0)
    if magic != b"glTF":
        raise RuntimeError(f"{path}: not a GLB")
    jlen, jtype = struct.unpack_from("<II", data, 12)
    doc = json.loads(data[20:20 + jlen])
    off = 20 + jlen
    blen, btype = struct.unpack_from("<II", data, off)
    return doc, bytearray(data[off + 8:off + 8 + blen])


def _write_glb(path, doc, bin_):
    js = json.dumps(doc, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    bin_ = bytes(bin_) + b"\x00" * (-len(bin_) % 4)
    with open(path, "wb") as f:
        f.write(struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(js) + 8 + len(bin_)))
        f.write(struct.pack("<II", len(js), 0x4E4F534A) + js)
        f.write(struct.pack("<II", len(bin_), 0x004E4942) + bin_)


def pack_hair_maps(b, out):
    """The hair / facial-hair cards' data maps (hair_strand_raster) into the GLB, in the
    standard slots so the KTX2 copy compresses them and no sidecar is needed:
    aniso -> KHR_materials_anisotropy texture (RG flow in tangent space, B strength,
    A depth across the card), orm -> occlusionTexture (R) + metallicRoughnessTexture
    (G roughness; B strand ID and A root-to-tip ride along, metallicFactor 0 so a
    standard viewer reads no metal). Texture coordinates and sampler follow the
    material's baseColorTexture."""
    maps = getattr(b, "hair_maps", None) or {}
    if not maps:
        return None
    from . import hair_strand_raster as hsr
    doc, bin_ = _read_glb(out)
    buf = doc["buffers"][0]
    done, nbytes = {}, 0
    images = doc.setdefault("images", [])
    textures = doc.setdefault("textures", [])
    tex_of = {}

    def texture(img_name, sampler):
        key = (img_name, sampler)
        if key in tex_of:
            return tex_of[key]
        img = bpy.data.images.get(img_name)
        if img is None:
            raise RuntimeError(f"pack_hair_maps: image {img_name} missing")
        png = hsr.image_png_bytes(img)
        bin_.extend(b"\x00" * (-len(bin_) % 4))
        doc["bufferViews"].append({"buffer": 0, "byteOffset": len(bin_), "byteLength": len(png)})
        bin_.extend(png)
        images.append({"name": img_name, "mimeType": "image/png", "bufferView": len(doc["bufferViews"]) - 1})
        t = {"source": len(images) - 1}
        if sampler is not None:
            t["sampler"] = sampler
        textures.append(t)
        tex_of[key] = len(textures) - 1
        nonlocal nbytes
        nbytes += len(png)
        return tex_of[key]

    for mat in doc.get("materials", []):
        rec = maps.get(mat.get("name"))
        if rec is None:
            continue
        pbr = mat.setdefault("pbrMetallicRoughness", {})
        base = pbr.get("baseColorTexture")
        if base is None:
            raise RuntimeError(f"pack_hair_maps: {mat['name']} has no baseColorTexture")
        tc = base.get("texCoord", 0)
        sampler = textures[base["index"]].get("sampler")
        ta = texture(rec["anisotropy"], sampler)
        to = texture(rec["orm"], sampler)
        mat.setdefault("extensions", {})["KHR_materials_anisotropy"] = {
            "anisotropyStrength": 1.0, "anisotropyRotation": 0.0,
            "anisotropyTexture": {"index": ta, "texCoord": tc}}
        mat["occlusionTexture"] = {"index": to, "texCoord": tc, "strength": 1.0}
        pbr["metallicRoughnessTexture"] = {"index": to, "texCoord": tc}
        pbr["metallicFactor"] = 0.0
        pbr["roughnessFactor"] = 1.0
        done[mat["name"]] = {"anisotropy": ta, "orm": to}
    if done:
        used = doc.setdefault("extensionsUsed", [])
        if "KHR_materials_anisotropy" not in used:
            used.append("KHR_materials_anisotropy")
    bin_.extend(b"\x00" * (-len(bin_) % 4))
    buf["byteLength"] = len(bin_)
    _write_glb(out, doc, bin_)
    missing = sorted(set(maps) - set(done))
    b.notes["hair_maps"] = {"materials": done, "png_bytes": nbytes, "missing": missing}
    if missing:
        raise RuntimeError(f"pack_hair_maps: materials not in the GLB: {missing}")
    return b.notes["hair_maps"]


def _png_rgb8(path, rgb):
    """8-bit RGB PNG from a (h, w, 3) float array in [0, 1], rows top-down."""
    h, w = rgb.shape[:2]
    a = np.clip(np.round(rgb * 255.0), 0, 255).astype(np.uint8)
    raw = b"".join(b"\x00" + a[y].tobytes() for y in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def _image_rgb(img):
    """Blender image pixels (bottom-up) -> top-down (h, w, 3), glTF's UV convention."""
    w, h = img.size
    px = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(px)
    return px.reshape(h, w, 4)[::-1, :, :3]


def write_sidecars(b, out):
    """Runtime-only inputs that glTF has no slot for, next to the GLB:
    suit_detail.json + its tiles (suit_textures: the weave as a tiled detail
    normal instead of baked into the atlas). Returns a stats record."""
    out_dir = os.path.dirname(os.path.abspath(out))
    mats, tiles = {}, set()
    for o in b.export_objs:
        if o.type != "MESH" or _hero_only(o):
            continue
        for m in o.data.materials:
            if m is not None and "suit_detail" in m and m.name not in mats:
                rec = json.loads(m["suit_detail"])
                mats[m.name] = rec
                tiles.add(rec["tile"])
    written = []
    for t in sorted(tiles):
        img = bpy.data.images.get(os.path.splitext(t)[0])
        if img is None:
            raise RuntimeError(f"weave detail tile {t} missing from the .blend")
        _png_rgb8(os.path.join(out_dir, t), _image_rgb(img))
        written.append(t)
    if mats:
        with open(os.path.join(out_dir, "suit_detail.json"), "w") as f:
            json.dump({"version": 1, "materials": mats,
                       "note": "tile = tangent-space normal (linear, glTF +Y), wrap REPEAT, mipmapped; "
                               "uv_tile = rotate(uv * repeat, angle_rad); XY slope x strength"}, f, indent=1)
        written.append("suit_detail.json")
    b.notes["sidecars"] = {"files": written, "materials": sorted(mats)}
    return b.notes["sidecars"]


def ktx2(b, out):
    """KTX2 copy of the GLB for the engine (web/tools/ktx2.mjs: UASTC q2 for normals and
    ORM, ETC1S q128 for albedo) as <stem>.ktx2.glb; the PNG GLB stays the source of
    truth (Blender cannot import KTX2). Needs the web/ node deps (npm ci --prefix web)."""
    import subprocess
    import time
    repo = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    dst = out[:-4] + ".ktx2.glb"
    t = time.perf_counter()
    r = subprocess.run(["node", os.path.join(repo, "web", "tools", "ktx2.mjs"), out, dst],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ktx2 failed: {r.stderr[-2000:]}")
    rec = json.loads(r.stdout.strip().splitlines()[-1])
    rec["bytes"] = os.path.getsize(dst)
    rec["seconds"] = round(time.perf_counter() - t, 1)
    b.notes["ktx2"] = rec
    return rec


def lod1(b, out):
    """LOD1 for the gameplay tier (T24, checkpoint-3 §5.2: ~60k tris, cap 65k): web/tools/lod1.mjs
    simplifies every primitive to its target with meshoptimizer and drops the scalp hair's fly-away
    cards (by atlas cell, from this build's hair stats) -> <stem>.lod1.glb, and from the KTX2 copy
    (when export.ktx2 ran first) <stem>.lod1.ktx2.glb, the gate asset. Needs the web/ node deps."""
    import subprocess
    import tempfile
    import time
    repo = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    tool = os.path.join(repo, "web", "tools", "lod1.mjs")
    stem = out[:-4]
    t = time.perf_counter()
    rec = {}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({"hair": b.notes.get("hair", {})}, f)
        stats = f.name
    try:
        for src, dst in ((out, stem + ".lod1.glb"), (stem + ".ktx2.glb", stem + ".lod1.ktx2.glb")):
            if not os.path.exists(src):
                continue
            r = subprocess.run(["node", tool, src, dst, "--stats", stats], capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError(f"lod1 failed ({os.path.basename(src)}): {(r.stdout + r.stderr)[-2000:]}")
            one = json.loads(r.stdout.strip().splitlines()[-1])
            rec[os.path.basename(dst)] = {"tris": one["tris"], "budget": one["budget"], "bytes": os.path.getsize(dst),
                                          "primitives": {f"{p['node']}/{p['material']}": [p["before"], p["after"]]
                                                         for p in one["primitives"]}}
    finally:
        os.unlink(stats)
    rec["seconds"] = round(time.perf_counter() - t, 1)
    b.notes["lod1"] = rec
    return rec


def save_blend(b, path):
    bpy.ops.wm.save_as_mainfile(filepath=path, compress=True)
