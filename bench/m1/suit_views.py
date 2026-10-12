"""Suit detail and hero renders (bench/m1/suit.md, bench/m1/v2/suit.md).

    blender -b --factory-startup --python bench/m1/suit_views.py -- \
        --glb RUN/character.glb --out-dir DIR [--rig suit|studio|neon] [--engine eevee|cycles] \
        [--exposure EV] [--res 600] [--views back,torso] [--wire] [--only suit_jacket] [--hide hair] [--lum]

Rigs:
  suit    the m1 suit-track rig (key/fill/rim/back area lights), -3 EV
  studio  the look-dev harness rig (lookdev_render.build_studio: key 900 W, fill 250 W,
          rim 700 W, near-black world, grey floor), AgX, -2.5 EV: the calibrated exposure
  neon    the art-direction base rig (bench/m1/v2/direction.md §5) placed relative to each
          camera: amber 3000 K key 0.8 x 0.8 m 1.5 m away, 40° camera-left, 25° up; magenta
          rim strip 0.3 x 1.5 m behind-right (0.7); teal kicker behind-left (0.4); cool
          fill (0.08); dark wet-ish floor. -2.5 EV

Views: orthographic detail frames (VIEWS) and perspective hero framings (PERSP: body
at 1024 px tall, bust, profile). --lum renders each view as scene-linear EXR plus an
ID pass and writes lum.json: median linear luminance of the shirt, the wool (jacket,
trousers, waistcoat) and their ratio (art direction: shirt : wool >= 20 : 1).

--wire overlays the mesh edges (a wireframe modifier on a copy, lit flat orange),
--only keeps just the named meshes (substring match), --hide drops meshes.
"""

import argparse
import json
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--glb", required=True)
ap.add_argument("--blend", action="store_true", help="--glb is a .blend (the kept staged scene)")
ap.add_argument("--out-dir", required=True)
ap.add_argument("--rig", choices=["suit", "studio", "neon"], default="suit")
ap.add_argument("--engine", choices=["eevee", "cycles"], default="eevee")
ap.add_argument("--exposure", type=float, default=None)
ap.add_argument("--res", type=int, default=600)
ap.add_argument("--views", default="")
ap.add_argument("--wire", action="store_true")
ap.add_argument("--only", default="")
ap.add_argument("--hide", default="")
ap.add_argument("--samples", type=int, default=None)
ap.add_argument("--lum", action="store_true", help="linear EXR + ID pass -> lum.json (shirt : wool)")
ap.add_argument("--suffix", default="", help="appended to every output file name")
ap.add_argument("--clay", action="store_true", help="every mesh in a flat grey clay (form only)")
ap.add_argument("--mat", default="", help='look-dev material override, JSON {"name part": {"BSDF input": value}}')
A = ap.parse_args(argv)

# name: (camera location, target, orthographic frame size in metres)
VIEWS = {
    "front": ((0, -3.2, 1.0), (0, 0, 0.95), 2.0),
    "back": ((0, 3.2, 1.0), (0, 0, 0.95), 2.0),
    "back_hem": ((0.3, 1.6, 0.9), (0, 0, 0.85), 0.7),
    "torso": ((0, -1.2, 1.35), (0, 0, 1.3), 0.55),
    "torso34": ((-0.7, -1.0, 1.35), (0, 0, 1.25), 0.6),
    "side": ((1.4, 0, 1.2), (0, 0, 1.15), 0.9),
    "side_full": ((3.0, 0, 1.0), (0, 0, 0.95), 2.0),
    "lapel": ((-0.25, -1.0, 1.42), (-0.03, -0.1, 1.40), 0.32),
    "knot": ((0.0, -1.0, 1.52), (0.0, -0.1, 1.50), 0.20),
    "gorge": ((-0.35, -1.0, 1.52), (-0.09, -0.1, 1.47), 0.22),
    "notch": ((-0.22, -1.0, 1.52), (-0.08, -0.14, 1.47), 0.12),     # the notch at the dropped gorge
    "notch_r": ((-0.25, -1.0, 1.56), (-0.08, -0.13, 1.50), 0.13),   # the notch at the v3 gorge, wearer's right
    "notch_l": ((0.25, -1.0, 1.56), (0.08, -0.13, 1.50), 0.13),     # and left
    "cpoint_r": ((-0.2, -1.0, 1.62), (-0.11, -0.08, 1.55), 0.10),   # the right collar point and wing, front
    "vest_top_r": ((-0.25, -1.0, 1.53), (-0.05, -0.13, 1.50), 0.05),  # the waistcoat's edge beside the right lapel
    "lapel_edge": ((-0.9, -0.6, 1.45), (-0.07, -0.11, 1.40), 0.14),   # lapel edge thickness, raking
    "closeup_h": ((-0.63, -1.36, 1.58), (0.0, 0.0, 1.50), 0.42),   # the harness close-up's azimuth (25°), collar framing
    "collar_back": ((0.25, 1.0, 1.75), (0.0, 0.0, 1.52), 0.3),
    "collar_side": ((1.0, 0.0, 1.56), (0.0, 0.0, 1.56), 0.22),
    "neck_front": ((0.0, -1.0, 1.52), (0.0, 0.0, 1.52), 0.36),         # the collar ends and the shoulder line
    "neck_top": ((0.0, -0.25, 2.4), (0.0, 0.0, 1.5), 0.45),            # from above: collar fall on the shoulders
    "armpit": ((-0.7, -0.8, 1.05), (-0.24, -0.02, 1.40), 0.32),       # the left scye from below the front
    "armpit_back": ((-0.7, 0.8, 1.05), (-0.24, 0.02, 1.40), 0.32),
    "armpit_back_l": ((0.45, 1.0, 1.35), (0.21, 0.04, 1.40), 0.2),     # the sliver under the left sleeve, from behind
    "pocket": ((-0.5, -1.0, 1.1), (-0.12, -0.1, 1.03), 0.3),
    "pocket_x": ((-0.45, -1.0, 1.06), (-0.12, -0.12, 1.0), 0.13),     # extreme close-up of the flap
    "vent_x": ((0.3, 1.1, 1.06), (0.11, 0.1, 1.03), 0.10),           # close-up of the left vent top, from behind
    "vent_xr": ((-0.3, 1.1, 1.06), (-0.11, 0.1, 1.03), 0.10),        # the right vent top
    "shoulder": ((-0.3, -1.0, 1.55), (-0.2, -0.05, 1.48), 0.35),
    "shoulder_front": ((-0.22, -1.2, 1.45), (-0.22, 0.0, 1.45), 0.3),      # the shoulder line and sleeve head, square on
    "shoulder_side": ((-1.2, 0.0, 1.42), (-0.25, 0.0, 1.42), 0.36),       # sleeve pitch, roped head in profile
    "shoulder_back": ((0.3, 1.0, 1.55), (0.2, 0.05, 1.48), 0.35),
    "v_bottom": ((-0.5, -0.9, 1.22), (0, -0.1, 1.2), 0.18),
    "waist_r": ((-0.35, -1.0, 1.16), (-0.13, -0.12, 1.14), 0.12),      # the right front at the button row, outboard
    "cuff": ((0.75, -0.75, 1.25), (0.52, -0.22, 1.14), 0.25),
    "cuff_x": ((0.86, -0.10, 1.20), (0.51, -0.15, 1.14), 0.12),       # extreme close-up of the cuff buttons
    "elbow": ((0.2, -1.0, 1.3), (0.42, -0.1, 1.24), 0.3),             # the inner elbow (left arm)
    "elbow_side": ((1.2, -0.3, 1.25), (0.42, -0.08, 1.22), 0.35),     # the left sleeve in profile
    "legs_back": ((0.3, 2.2, 0.62), (0.0, 0.0, 0.55), 0.9),           # both knees from behind
    "seat": ((0.0, 1.6, 0.95), (0.0, 0.0, 0.92), 0.6),
    "knee_back": ((0.2, 1.4, 0.55), (0.1, 0.0, 0.5), 0.5),
    "hem": ((0.6, -0.9, 0.25), (0.1, 0, 0.12), 0.45),
    "hem_back": ((0.5, 0.9, 0.2), (0.1, 0, 0.1), 0.45),
    "shoe": ((0.68, -0.9, 0.12), (0.195, -0.04, 0.06), 0.3),
    "shoe_x": ((0.52, -0.6, 0.18), (0.195, -0.1, 0.045), 0.14),       # extreme close-up: cap, vamp, laces
    "shoe_side": ((1.0, -0.04, 0.1), (0.195, -0.04, 0.06), 0.3),
    "shoe_top": ((0.195, -0.3, 1.2), (0.195, -0.04, 0.05), 0.35),
}

# perspective framings: (azimuth deg, 0 = in front, + = the character's left; target;
# frame height in metres; lens mm; resolution (w, h))
PERSP = {
    "body": (40.0, (0.0, 0.0, 0.98), 2.15, 50.0, (768, 1024)),
    "body_front": (0.0, (0.0, 0.0, 0.98), 2.15, 50.0, (768, 1024)),
    "body_profile": (90.0, (0.0, 0.0, 0.98), 2.15, 50.0, (768, 1024)),
    "body_back": (180.0, (0.0, 0.0, 0.98), 2.15, 50.0, (768, 1024)),
    "bust": (30.0, (0.0, 0.0, 1.40), 0.80, 85.0, (900, 1024)),
    "bust_front": (0.0, (0.0, 0.0, 1.38), 0.80, 85.0, (900, 1024)),
    "waist": (25.0, (0.0, 0.0, 1.05), 0.75, 85.0, (900, 1024)),
    "legs": (30.0, (0.0, 0.0, 0.45), 1.0, 85.0, (800, 1024)),
}

if A.blend:
    bpy.ops.wm.open_mainfile(filepath=os.path.abspath(A.glb))
    for o in list(bpy.data.objects):
        if o.type in ("LIGHT", "CAMERA"):
            bpy.data.objects.remove(o, do_unlink=True)
else:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=os.path.abspath(A.glb))
sc = bpy.context.scene
sc.render.resolution_x = sc.render.resolution_y = A.res
sc.render.resolution_percentage = 100
if A.engine == "cycles":
    sc.render.engine = "CYCLES"
    c = sc.cycles
    c.device = "CPU"
    c.samples = A.samples or 64
    c.use_adaptive_sampling = True
    c.use_denoising = True
    c.denoiser = "OPENIMAGEDENOISE"
    c.max_bounces = 8
else:
    sc.render.engine = "BLENDER_EEVEE"
    sc.eevee.taa_render_samples = A.samples or 16
sc.view_settings.view_transform = "AgX"
sc.view_settings.look = "None"
sc.view_settings.exposure = A.exposure if A.exposure is not None else (-3.0 if A.rig == "suit" else -2.5)
sc.world = bpy.data.worlds.new("suit_views")
sc.world.use_nodes = True
bg = sc.world.node_tree.nodes.get("Background")
bg.inputs[0].default_value = {"suit": (0.02, 0.02, 0.025, 1), "studio": (0.045, 0.045, 0.05, 1),
                              "neon": (0.004, 0.005, 0.008, 1)}[A.rig]

if A.mat:
    for part, ins in json.loads(A.mat).items():
        for m in bpy.data.materials:
            if part in m.name and m.node_tree:
                p = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
                for k, v in ins.items():
                    if p is not None and k in p.inputs:
                        p.inputs[k].default_value = v if not isinstance(v, list) else tuple(v)

if A.clay:
    cm = bpy.data.materials.new("clay")
    cm.use_nodes = True
    cp = cm.node_tree.nodes["Principled BSDF"]
    cp.inputs["Base Color"].default_value = (0.4, 0.4, 0.42, 1)
    cp.inputs["Roughness"].default_value = 0.6
    for o in sc.objects:
        if o.type == "MESH":
            o.data.materials.clear()
            o.data.materials.append(cm)

only = [s for s in A.only.split(",") if s]
hide = [s for s in A.hide.split(",") if s]
MESHES = [o for o in sc.objects if o.type == "MESH" and not o.hide_render]
for o in MESHES:
    if (only and not any(s in o.name for s in only)) or any(s in o.name for s in hide):
        o.hide_render = True
for o in sc.objects:   # the importer's bone-shape icosphere
    if o.type == "MESH" and o.parent is None and "Icosphere" in o.name:
        o.hide_render = True

if A.wire:
    wm = bpy.data.materials.new("wire")
    wm.use_nodes = True
    em = wm.node_tree.nodes.new("ShaderNodeEmission")
    em.inputs[0].default_value = (1.0, 0.45, 0.05, 1.0)
    em.inputs[1].default_value = 4.0
    out = next(n for n in wm.node_tree.nodes if n.type == "OUTPUT_MATERIAL")
    wm.node_tree.links.new(em.outputs[0], out.inputs[0])
    for o in [o for o in sc.objects if o.type == "MESH" and not o.hide_render
              and ("suit" in o.name or "shoe" in o.name)]:
        w = o.copy()
        w.data = o.data.copy()
        w.data.materials.clear()
        w.data.materials.append(wm)
        for p in w.data.polygons:
            p.material_index = 0
        m = w.modifiers.new("wire", "WIREFRAME")
        m.thickness = 0.0006
        m.use_replace = True
        m.use_boundary = True
        sc.collection.objects.link(w)

floor_z = min((o.matrix_world @ Vector(c)).z for o in sc.objects
              if o.type == "MESH" and not o.hide_render for c in o.bound_box)
LIGHTS = []


def area(name, loc, energy, size, color=(1, 1, 1), aim=(0, 0, 1.1), size_y=None):
    ld = bpy.data.lights.new(name, "AREA")
    ld.energy, ld.color = energy, color
    if size_y is not None:
        ld.shape = "RECTANGLE"
        ld.size, ld.size_y = size, size_y
    else:
        ld.size = size
    ob = bpy.data.objects.new(name, ld)
    sc.collection.objects.link(ob)
    ob.location = loc
    ob.rotation_euler = (Vector(aim) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    LIGHTS.append(ob)
    return ob


def floor(albedo, rough):
    me = bpy.data.meshes.new("floor")
    s = 30.0
    me.from_pydata([(-s, -s, floor_z), (s, -s, floor_z), (s, s, floor_z), (-s, s, floor_z)], [], [(0, 1, 2, 3)])
    ob = bpy.data.objects.new("suit_views_floor", me)
    sc.collection.objects.link(ob)
    mat = bpy.data.materials.new("suit_views_floor")
    mat.use_nodes = True
    p = mat.node_tree.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = (albedo, albedo, albedo * 1.06, 1)
    p.inputs["Roughness"].default_value = rough
    me.materials.append(mat)
    return ob


def clear_lights():
    for ob in LIGHTS:
        bpy.data.objects.remove(ob, do_unlink=True)
    LIGHTS.clear()


def rig_static():
    if A.rig == "suit":
        area("key", (-1.5, -2.5, 2.5), 900, 2)
        area("fill", (2, -2, 1.5), 250, 2)
        area("rim", (0, 3, 2.5), 700, 2)
        area("back", (0.5, 3, 1.0), 400, 2)
    elif A.rig == "studio":   # lookdev_render.build_studio, same positions relative to the floor
        aim = (0, 0, floor_z + 1.1)
        area("key", (-2.2, -2.6, floor_z + 2.8), 900, 1.5, (1.0, 0.96, 0.9), aim)
        area("fill", (2.6, -2.0, floor_z + 1.4), 250, 2.0, (0.85, 0.9, 1.0), aim)
        area("rim", (0.8, 2.8, floor_z + 2.6), 700, 1.0, (1, 1, 1), aim)


# 3000 K blackbody in linear Rec.709, normalised to max 1
AMBER = (1.0, 0.52, 0.21)


def rig_neon(cam_loc, target):
    """direction.md §5 base rig, relative to the camera. Key irradiance matches the
    studio key's at the subject (studio: 900 W at 3.8 m; here 1.5 m)."""
    t = Vector(target)
    d = Vector(cam_loc) - t
    d.z = 0.0
    d.normalize()
    up = Vector((0, 0, 1))
    right = d.cross(up).normalized() * -1   # camera's right, seen from the camera

    def at(az_deg, el_deg, dist, base=t):
        a = math.radians(az_deg)
        h = (d * math.cos(a) - right * math.sin(a)).normalized()   # + az = camera-left
        e = math.radians(el_deg)
        return base + (h * math.cos(e) + up * math.sin(e)) * dist

    key_w = 140.0
    area("key", at(40, 25, 1.5), key_w, 0.8, AMBER, t)
    rim_t = t + Vector((0, 0, -0.1))
    area("rim", at(180 + 40, 5, 1.6, rim_t), key_w * 0.7 * 2.2, 0.3, (1.0, 0.18, 0.55), rim_t, size_y=1.5)
    area("kicker", at(180 - 45, 10, 1.7, rim_t), key_w * 0.4 * 2.2, 0.4, (0.1, 0.8, 0.9), rim_t, size_y=1.2)
    area("fill", at(-20, 5, 2.5), key_w * 0.08 * 2.5, 2.0, (0.7, 0.8, 1.0), t)


if A.rig == "studio":
    floor(0.08, 0.8)
elif A.rig == "neon":
    floor(0.03, 0.35)
rig_static()

cd = bpy.data.cameras.new("suit_views")
cam = bpy.data.objects.new("suit_views", cd)
sc.collection.objects.link(cam)
sc.camera = cam
os.makedirs(A.out_dir, exist_ok=True)


# --- ID pass (--lum) -------------------------------------------------------------------------

CLASSES = {"shirt": ("suit_shirt",), "wool": ("suit_jacket", "suit_trousers", "suit_waistcoat"),
           "jacket": ("suit_jacket",), "tie": ("suit_tie",), "shoes": ("suit_shoes",)}


def id_value(o):
    for k, (name,) in (("shirt", ("suit_shirt",)), ("jacket", ("suit_jacket",)),
                       ("trousers", ("suit_trousers",)), ("vest", ("suit_waistcoat",)),
                       ("tie", ("suit_tie",)), ("shoes", ("suit_shoes",))):
        if name in o.name:
            return {"shirt": 1, "jacket": 2, "trousers": 3, "vest": 4, "tie": 5, "shoes": 6}[k]
    return 7


def load_exr(path):
    img = bpy.data.images.load(path, check_existing=False)
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    bpy.data.images.remove(img)
    return px.reshape(h, w, 4)


def id_pass(path):
    """Flat emission per garment class, no AA: returns int[h, w] (0 = background)."""
    saved = {}
    mats = {}
    for o in sc.objects:
        if o.type != "MESH" or o.hide_render:
            continue
        v = id_value(o)
        if v not in mats:
            m = bpy.data.materials.new(f"_id{v}")
            m.use_nodes = True
            nt = m.node_tree
            nt.nodes.clear()
            em = nt.nodes.new("ShaderNodeEmission")
            em.inputs[0].default_value = (v / 10.0, v / 10.0, v / 10.0, 1)
            out = nt.nodes.new("ShaderNodeOutputMaterial")
            nt.links.new(em.outputs[0], out.inputs[0])
            mats[v] = m
        saved[o.name] = [s.material for s in o.material_slots]
        for s in o.material_slots:
            s.material = mats[v]
    hidden = [ob for ob in LIGHTS] + [o for o in sc.objects if o.name.startswith("suit_views_floor")]
    for ob in hidden:
        ob.hide_render = True
    r = sc.render
    state = (r.engine, r.filter_size, sc.view_settings.view_transform, sc.view_settings.exposure,
             r.film_transparent, tuple(bg.inputs[0].default_value))
    r.engine = "BLENDER_EEVEE"
    sc.eevee.taa_render_samples = 1
    r.filter_size = 0.0
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.exposure = 0.0
    bg.inputs[0].default_value = (0, 0, 0, 1)
    r.image_settings.file_format = "OPEN_EXR"
    r.filepath = path
    bpy.ops.render.render(write_still=True)
    ids = np.rint(load_exr(path)[..., 0] * 10.0).astype(np.int32)
    r.engine, r.filter_size, sc.view_settings.view_transform, sc.view_settings.exposure, \
        r.film_transparent, bgc = state
    bg.inputs[0].default_value = bgc
    if A.engine == "eevee":
        sc.eevee.taa_render_samples = A.samples or 16
    for ob in hidden:
        ob.hide_render = False
    for o in sc.objects:
        if o.name in saved:
            for s, m in zip(o.material_slots, saved[o.name]):
                s.material = m
    os.remove(path)
    return ids


def lum_stats(exr, ids):
    L = 0.2126 * exr[..., 0] + 0.7152 * exr[..., 1] + 0.0722 * exr[..., 2]
    out = {}
    for name, v in (("shirt", [1]), ("wool", [2, 3, 4]), ("jacket", [2]), ("trousers", [3]),
                    ("tie", [5]), ("shoes", [6])):
        m = np.isin(ids, v)
        # erode one pixel (edge AA mixes the neighbours in)
        m = m & np.roll(m, 1, 0) & np.roll(m, -1, 0) & np.roll(m, 1, 1) & np.roll(m, -1, 1)
        if m.sum() < 20:
            continue
        vals = L[m]
        out[name] = {"px": int(m.sum()), "median": float(np.median(vals)), "mean": float(vals.mean()),
                     "p90": float(np.percentile(vals, 90))}
    if "shirt" in out and "wool" in out:
        out["shirt_to_wool_median"] = round(out["shirt"]["median"] / max(out["wool"]["median"], 1e-9), 2)
        out["shirt_to_wool_mean"] = round(out["shirt"]["mean"] / max(out["wool"]["mean"], 1e-9), 2)
    return out


# --- render loop -------------------------------------------------------------------------------

lum = {}
names = [v for v in A.views.split(",") if v] or list(VIEWS)
for name in names:
    if name in PERSP:
        az, tgt, frame_h, lens, (w, h) = PERSP[name]
        cd.type = "PERSP"
        cd.lens = lens
        cd.sensor_fit = "VERTICAL"
        cd.sensor_height = 24.0
        dist = (frame_h * 0.5) / math.tan(math.atan(cd.sensor_height * 0.5 / lens))
        a = math.radians(az)
        tgt = Vector(tgt) + Vector((0, 0, floor_z))
        loc = tgt + Vector((math.sin(a), -math.cos(a), 0.0)) * dist
        sc.render.resolution_x, sc.render.resolution_y = w, h
    else:
        loc, tgt, size = VIEWS[name]
        cd.type = "ORTHO"
        cd.ortho_scale = size
        sc.render.resolution_x = sc.render.resolution_y = A.res
        loc, tgt = Vector(loc), Vector(tgt)
    cam.location = loc
    cam.rotation_euler = (Vector(tgt) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    if A.rig == "neon":
        clear_lights()
        rig_neon(loc, tgt)
    png = os.path.join(A.out_dir, f"{name}{A.suffix}.png")
    if A.lum:
        exr_path = os.path.join(A.out_dir, f"{name}{A.suffix}.exr")
        sc.render.image_settings.file_format = "OPEN_EXR"
        sc.render.filepath = exr_path
        bpy.ops.render.render(write_still=True)
        img = bpy.data.images.load(exr_path, check_existing=False)
        img.save_render(png, scene=sc)   # display-referred PNG with the scene's view transform
        bpy.data.images.remove(img)
        exr = load_exr(exr_path)
        ids = id_pass(os.path.join(A.out_dir, f"_id_{name}.exr"))
        lum[name] = lum_stats(exr, ids)
        os.remove(exr_path)
        sc.render.image_settings.file_format = "PNG"
        print(f"[suit_views] {name}: {json.dumps({k: v for k, v in lum[name].items() if 'to' in k})}", flush=True)
    else:
        sc.render.image_settings.file_format = "PNG"
        sc.render.filepath = png
        bpy.ops.render.render(write_still=True)
    print(f"[suit_views] {png}", flush=True)
if A.lum:
    with open(os.path.join(A.out_dir, f"lum{A.suffix}.json"), "w") as f:
        json.dump({"rig": A.rig, "engine": A.engine, "exposure": sc.view_settings.exposure, "views": lum}, f, indent=1)
