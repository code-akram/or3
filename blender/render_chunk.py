"""Render a quick oblique check image of a world chunk GLB (headless).

Usage:
  blender -b --factory-startup --python blender/render_chunk.py -- \
      <chunk.glb> <out.png> [--markers x,y,z;x,y,z] [--threads 3] [--samples 24]

The chunk is Y-up glTF (x east, y up, z = -north), which Blender's importer maps to
Z-up (x east, y north, z up). Buildings are coloured by PLATEAU usage code using the
per-building table in mesh extras ("features") and the _FEATURE_ID_0 vertex attribute.
Optional markers (glTF coordinates) are drawn as small spheres, e.g. a sound source
(red) and listener (blue).
"""

import sys
import math
import bpy

argv = sys.argv[sys.argv.index("--") + 1 :]
src, out = argv[0], argv[1]
opts = dict(zip(argv[2::2], argv[3::2]))
threads = int(opts.get("--threads", "3"))
samples = int(opts.get("--samples", "24"))
markers = []
if "--markers" in opts:
    for m in opts["--markers"].split(";"):
        x, y, z = (float(v) for v in m.split(","))
        markers.append((x, -z, y))  # glTF Y-up -> Blender Z-up

# usage code -> colour (muted; commercial 402 warm, residential cool)
USAGE_RGB = {
    "401": (0.55, 0.60, 0.70),  # office
    "402": (0.85, 0.62, 0.45),  # commercial
    "403": (0.80, 0.45, 0.60),  # hotel
    "411": (0.55, 0.75, 0.60),  # house
    "412": (0.50, 0.68, 0.80),  # apartment
    "413": (0.75, 0.75, 0.50),  # shop-house
}
DEFAULT_RGB = (0.72, 0.72, 0.72)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
scene = bpy.context.scene

objs = [o for o in scene.objects if o.type == "MESH"]
for o in objs:
    me = o.data
    if o.name.startswith("tran"):
        m = bpy.data.materials.new("road")
        m.use_nodes = True
        m.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.08, 0.08, 0.09, 1)
        me.materials.clear()
        me.materials.append(m)
        continue
    feats = None
    # importer puts glTF mesh extras on the mesh datablock as custom properties
    if "features" in me.keys():
        feats = me["features"]
    fid_attr = me.attributes.get("_FEATURE_ID_0") or me.attributes.get("_feature_id_0")
    if feats is not None and fid_attr is not None and fid_attr.domain == "POINT":
        col = me.color_attributes.new("usage", "FLOAT_COLOR", "POINT")
        for i, v in enumerate(fid_attr.data):
            f = int(round(v.value))
            u = str(feats[f].get("usage", "")) if f < len(feats) else ""
            r, g, b = USAGE_RGB.get(u, DEFAULT_RGB)
            col.data[i].color = (r, g, b, 1.0)
        mat = bpy.data.materials.new("usage")
        mat.use_nodes = True
        nt = mat.node_tree
        bsdf = nt.nodes["Principled BSDF"]
        attr = nt.nodes.new("ShaderNodeAttribute")
        attr.attribute_name = "usage"
        nt.links.new(attr.outputs["Color"], bsdf.inputs["Base Color"])
        bsdf.inputs["Roughness"].default_value = 0.9
        me.materials.clear()
        me.materials.append(mat)

# bounds
xs, ys, zs = [], [], []
for o in objs:
    for c in o.bound_box:
        w = o.matrix_world @ __import__("mathutils").Vector(c)
        xs.append(w.x), ys.append(w.y), zs.append(w.z)
cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
zmin, zmax = min(zs), max(zs)

# ground plane under everything
bpy.ops.mesh.primitive_plane_add(size=400, location=(cx, cy, zmin - 0.2))
ground = bpy.context.active_object
gm = bpy.data.materials.new("ground")
gm.use_nodes = True
gm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.2, 0.2, 0.22, 1)
ground.data.materials.append(gm)

marker_r = float(opts.get("--marker-radius", "1.5"))
for i, (x, y, z) in enumerate(markers):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=marker_r, location=(x, y, z))
    s = bpy.context.active_object
    mm = bpy.data.materials.new(f"marker{i}")
    mm.use_nodes = True
    bs = mm.node_tree.nodes["Principled BSDF"]
    rgb = (1, 0.05, 0.05, 1) if i == 0 else (0.1, 0.3, 1, 1)
    bs.inputs["Base Color"].default_value = rgb
    bs.inputs["Emission Color"].default_value = rgb
    bs.inputs["Emission Strength"].default_value = 3.0
    s.data.materials.append(mm)

# sun + sky-ish world
bpy.ops.object.light_add(type="SUN", rotation=(math.radians(50), 0, math.radians(35)))
bpy.context.active_object.data.energy = 3.5
world = bpy.data.worlds.new("w")
world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.55, 0.6, 0.7, 1)
world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.6
scene.world = world

# oblique camera from the south-south-west (or around --focus x,y,z in glTF coords)
bpy.ops.object.camera_add()
cam = bpy.context.active_object
dist = float(opts.get("--dist", "260"))
el = math.radians(float(opts.get("--elevation", "52")))
az = math.radians(float(opts.get("--azimuth", "-115")))  # -115 = from the south-west
if "--focus" in opts:
    fx, fy, fz = (float(v) for v in opts["--focus"].split(","))
    target = (fx, -fz, fy)
else:
    target = (cx, cy, zmin + 15)
cam.location = (
    target[0] + dist * math.cos(el) * math.cos(az),
    target[1] + dist * math.cos(el) * math.sin(az),
    target[2] + dist * math.sin(el),
)
d = __import__("mathutils").Vector(target) - cam.location
cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
cam.data.lens = 35
scene.camera = cam

scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = samples
scene.cycles.use_denoising = True
scene.render.threads_mode = "FIXED"
scene.render.threads = threads
scene.render.resolution_x = int(opts.get("--width", "1280"))
scene.render.resolution_y = int(opts.get("--height", "800"))
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGB"
scene.render.image_settings.compression = 100
scene.render.filepath = out
bpy.ops.render.render(write_still=True)
print(f"rendered {out}")
