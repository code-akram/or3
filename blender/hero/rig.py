"""Shared hero light rigs, cameras and Cycles settings (m1 v2, Track E).

One script every track renders its evidence with, so all tracks judge under
the same light (bench/m1/v2/direction.md §5):

  hero       the base rig: amber 3,000 K key (0.8 m square, 1.5 m, 40 deg
             camera-left, 25 deg up) 1.0; magenta rim strip behind-right 0.7;
             teal kicker behind-left 0.4; cool fill 0.08; 10 cm eye light at
             the camera 0.12. Near-black world, dark floor, optional haze.
             The rig is placed relative to the camera (a cinematic cheat), so
             every view is lit the same way.
  turntable  the honesty light: 5,600 K three-point (key 1.0 at 45 deg
             camera-left / 30 deg up, fill 0.3, rim 0.5), an 18 % grey
             cyclorama, no haze, no grade, no depth of field.

Ratios are irradiance ratios at the subject (head or chest): each light's
power is ratio * E_key * pi * d^2, so moving a light keeps its ratio.

CLI (renders a kept character.blend, or a GLB, under one or both rigs):

    blender -b -t 4 --factory-startup --python-exit-code 1 \\
        --python blender/hero/rig.py -- --in RUN/character.blend --out DIR \\
        [--light hero|turntable|both] [--cam "portrait;bust;tt0;az=30,el=5,..."] \\
        [--pose rest|stand|walk|ready|...] [--quality preview|final|draft] \\
        [--passes beauty,clay,normal] [--haze] [--res WxH] [--samples N]

Cameras: the presets in CAMERAS (lens mm, azimuth deg, elevation deg or
camera height, aim point, frame height m), `tt<deg>` (turntable, 50 mm full
body at that azimuth; tt = all 8 at 45 deg steps), or a custom spec
`az=30,el=5,lens=85,aim=head,frame=0.45`. Azimuth 0 is in front of the
character; positive shows its LEFT side. Separate cameras with ';' (a comma
list of presets also works, but a list containing a custom spec must use ';';
a single custom spec is always one camera).

Poses: `stand` / `ready` / `ready_low` are Track F's canonical `hero` /
`high_ready` / `low_ready` (blender/character/deform_poses.py), every
deform_poses name works too (`f:<name>` for one shadowed by an E pose), and
E's solver versions are `stand_e` / `ready_e` / `ready_low_e` / `walk`. Every
pose runs F's deformation runtime afterwards (helper bones + correctives from
the armature's deform_rules or character.rig.json; poses.deform).

Writes DIR/<light>_<cam>[_<pass>].png and DIR/rig.json (settings, per-frame
render seconds, pose log). Import it from Python too:

    from hero import rig
    ch = rig.load_character(path); cam = rig.camera(ch, "portrait")
    rig.hero_rig(ch, cam); rig.cycles(quality="preview"); rig.render(path)
"""

import argparse
import json
import math
import os
import sys
import time

import bpy
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.dirname(HERE) not in sys.path:
    sys.path.insert(0, os.path.dirname(HERE))

from hero import poses  # noqa: E402

Z = Vector((0, 0, 1))

# --------------------------------------------------------------- constants
# Key irradiance at the subject (Blender W/m^2) and view exposure, calibrated
# with --calibrate so that an 18 % grey card at face height reads ~0.46
# display (AgX) under the turntable key + fill + rim, and skin (albedo ~0.35)
# reads ~0.55 on the lit side under the hero key.
HERO_E = 3.0
HERO_EXPOSURE = -0.6
HERO_LOOK = "AgX - Medium High Contrast"   # direction §5: contrast +15 %
TT_E = 4.0
TT_EXPOSURE = 0.0

# Deviation from direction §5: rim 1.4 and kicker 0.8 (not 0.7 / 0.4); at the
# spec ratios the rims did not separate the hair edge from the black.
# name: (colour or temperature K, ratio, shape (w, h m), azimuth deg from the
# camera axis (+ = camera-left), elevation deg, distance m)
# Key warmth: direction §5 says amber 3,000 K, but under the render's 6,500 K
# white and AgX Medium High Contrast that put the skin at HSV saturation
# 0.66-0.78 (orange-tan) where the turntable reads 0.30-0.39. The skin sits in
# the toe of the AgX curve, where the channel ratios stretch, and the set
# lights are not the cause (the void set is as orange). 5,000 K plus the
# grade's 0.85 saturation gives 0.33-0.46: neutral-warm skin, while the neon
# rims and signs keep the colour (deviation, see hero-stage.md).
KEY_K = 5000
HERO_LIGHTS = {
    "key":     (KEY_K, 1.00, (0.8, 0.8), 40.0, 25.0, 1.5),
    "rim":     ((1.0, 0.18, 0.55), 1.40, (0.3, 1.5), -140.0, 25.0, 1.5),
    "kicker":  ((0.1, 0.8, 0.9), 0.80, (0.3, 1.2), 135.0, 15.0, 1.6),
    "fill":    ((0.55, 0.7, 1.0), 0.08, (2.0, 2.0), -55.0, -5.0, 2.5),
    "eye":     (6500, 0.12, (0.1, 0.1), 0.0, 0.0, None),   # at the camera
}
TT_LIGHTS = {
    "key":  (5600, 1.0, (1.2, 1.2), 45.0, 30.0, 2.5),
    "fill": (5600, 0.3, (2.0, 2.0), -60.0, 5.0, 3.0),
    "rim":  (5600, 0.5, (0.6, 1.8), 160.0, 35.0, 2.5),
}

# name: (lens mm, azimuth deg, elevation deg | ("h", camera height m),
#        aim ("head" | "eyes" | "chest" | "body" | "hands" | "feet"),
#        frame height m, f-stop or None)
CAMERAS = {
    "portrait": (85, 30, 2, "eyes", 0.42, 2.0),      # shot 1: rain portrait
    "eye":      (135, 8, 0, "eyes", 0.075, 16.0),    # shot 6: eye close-up, 0.4 m
    "bust":     (50, 35, 3, "chest", 0.80, 2.8),
    "full":     (50, 20, ("h", 1.1), "body", 2.25, 4.0),  # shot 2: under the sign
    "profile":  (100, 90, 0, "head", 0.55, 2.8),     # shot 3
    "draw":     (35, 35, ("h", 1.2), "body", 2.40, 5.6),  # shot 4
    "hands":    (100, 25, -5, "hands", 0.45, 4.0),   # shot 5
    "back":     (50, 150, 5, "chest", 1.05, 2.8),    # back 3/4: hair + suit back
}
TT_LENS, TT_FRAME = 50, 2.3
EYE_FRONT = 0.012   # eyeball centre to the cornea front, m (focus point)
QUALITY = {  # samples, adaptive threshold, resolution %
    "draft": (16, 0.1, 25),
    "preview": (64, 0.05, 50),
    "final": (768, 0.012, 100),
}


# --------------------------------------------------------------- character
class Character:
    """The loaded character: armature, meshes (and hero_only objects), and
    posed landmarks in world space."""

    def __init__(self, arm, objs):
        self.arm = arm
        self.objs = objs
        self.pose_log = []

    def bone_head(self, name):
        return self.arm.matrix_world @ self.arm.pose.bones[name].head

    def bone_mid(self, name):
        pb = self.arm.pose.bones[name]
        return self.arm.matrix_world @ ((pb.head + pb.tail) * 0.5)

    def _deform(self, bone):
        pb = self.arm.pose.bones[bone]
        return self.arm.matrix_world @ pb.matrix @ pb.bone.matrix_local.inverted()

    def eyes(self):
        """(left eye, right eye) world centres, following the head bone."""
        eo = next((o for o in self.objs if o.type == "MESH" and "eyes" in o.name.lower()), None)
        if eo is None:
            h = self.bone_mid("head")
            return h + Vector((0.032, -0.09, -0.01)), h + Vector((-0.032, -0.09, -0.01))
        co = [eo.matrix_world @ v.co for v in eo.data.vertices]
        left = [c for c in co if c.x > 0]
        right = [c for c in co if c.x <= 0]
        m = self._deform("head")
        return (m @ (sum(left, Vector()) / len(left)), m @ (sum(right, Vector()) / len(right)))

    def aim(self, what):
        el, er = self.eyes()
        if what == "eyes":
            return (el + er) * 0.5
        if what == "head":
            return (el + er) * 0.5 + Vector((0, 0.02, 0.0))
        if what == "chest":
            return self.bone_head("spine_03") + Vector((0, -0.05, 0.08))
        if what == "body":
            return Vector((0, 0, 0.98))
        if what in ("hand_l", "hand_r"):
            return self.bone_head(what) * 0.6 + self.bone_head("middle_01" + what[-2:]) * 0.4
        if what == "hands":
            return (self.bone_head("hand_l") + self.bone_head("hand_r")) * 0.5 + Vector((0, 0, -0.25))
        if what == "cuff_feet":    # between the hands and the floor under them
            h = (self.bone_head("hand_l") + self.bone_head("hand_r")) * 0.5
            return Vector((h.x * 0.6, h.y * 0.6 - 0.03, h.z * 0.5 + 0.06))
        if what == "feet":
            return Vector((0, -0.05, 0.25))
        raise ValueError(what)


def _character_from_scene():
    arm = next(o for o in bpy.context.scene.objects if o.type == "ARMATURE")
    objs = [o for o in bpy.context.scene.objects
            if o.type in ("MESH", "CURVES", "CURVE") and not o.hide_render
            and (o.parent == arm or any(c.name == "hero_only" for c in o.users_collection))]
    # The glTF importer adds a hidden bone-shape icosphere; keep it hidden.
    for o in bpy.context.scene.objects:
        if o.type == "MESH" and o not in objs:
            o.hide_render = True
    # hero_only geometry that nothing drives (no parent, no armature or
    # surface-deform modifier) would stay put when the rig is posed: pin it
    # to the head bone, keeping its world transform.
    head = arm.data.bones.get("head")
    for o in objs:
        if o.parent is None and head is not None and not any(
                m.type in ("ARMATURE", "SURFACE_DEFORM", "NODES") for m in o.modifiers):
            mw = o.matrix_world.copy()
            o.parent = arm
            o.parent_type = "BONE"
            o.parent_bone = "head"
            bpy.context.view_layer.update()
            o.matrix_world = mw
            print(f"[rig] pinned hero_only {o.name} to the head bone", flush=True)
    return Character(arm, objs)


def load_character(path):
    """Open a kept character.blend (with its hero_only collection) or import a
    GLB into an empty scene."""
    path = os.path.abspath(path)
    if path.endswith(".blend"):
        bpy.ops.wm.open_mainfile(filepath=path)
    else:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=path)
    sc = bpy.context.scene
    for o in list(sc.objects):
        if o.type in ("LIGHT", "CAMERA"):
            bpy.data.objects.remove(o, do_unlink=True)
    return _character_from_scene()


def pose(ch, name):
    ch.pose_log = poses.apply(ch.arm, name)
    return ch.pose_log


# --------------------------------------------------------------- helpers
def look_at(ob, target):
    ob.rotation_euler = (Vector(target) - ob.location).to_track_quat("-Z", "Y").to_euler()


def collection(name, clear=True):
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(col)
    elif clear:
        for o in list(col.objects):
            bpy.data.objects.remove(o, do_unlink=True)
    return col


def area_light(col, name, colour, power, size, loc, target):
    ld = bpy.data.lights.new(name, "AREA")
    if isinstance(colour, (int, float)):
        ld.use_temperature = True
        ld.temperature = float(colour)
        ld.color = (1, 1, 1)
    else:
        ld.color = colour
    ld.energy = power
    w, h = size
    ld.shape = "RECTANGLE" if abs(w - h) > 1e-6 else "SQUARE"
    ld.size = w
    ld.size_y = h
    ob = bpy.data.objects.new(name, ld)
    col.objects.link(ob)
    ob.visible_camera = False   # the emitter never shows directly (it still shows in reflections)
    ob.location = loc
    look_at(ob, target)
    return ob


def _light_power(ratio, e_key, d):
    """Area-light power giving irradiance ratio * e_key at distance d."""
    return ratio * e_key * math.pi * d * d


def _around(subject, cam_loc, az, el, dist):
    """Point at `dist` from subject, az deg from the subject->camera axis
    (+ = camera-left), el deg up."""
    c = Vector(cam_loc) - Vector(subject)
    c.z = 0
    c.normalize()
    # The camera looks along -c; its right vector is (-c) x Z. Rotating c
    # about +Z by -az moves the point to camera-left for az > 0.
    a, e = -math.radians(az), math.radians(el)
    d = Vector((c.x * math.cos(a) - c.y * math.sin(a), c.x * math.sin(a) + c.y * math.cos(a), 0))
    return Vector(subject) + (d * math.cos(e) + Z * math.sin(e)) * dist


def receivers(ch):
    """Collection (outside the scene) holding the character, for light
    linking: a flagged light only lights what is in it."""
    col = bpy.data.collections.get("hero_receivers") or bpy.data.collections.new("hero_receivers")
    for o in ch.objs:
        if o.name not in col.objects:
            col.objects.link(o)
    return col


def hero_rig(ch, cam, e_key=HERO_E, lights=None, subject=None, scale=1.0, flag=()):
    """Build the base hero rig around the camera's subject (the head for
    head shots, the chest otherwise). `lights` overrides entries of
    HERO_LIGHTS; scale multiplies every power. `flag`: names of lights that
    light only the character (Cycles light linking, the render version of a
    flag on a stand), so a camera-relative key does not wash the set."""
    col = collection("hero_rig")
    spec = dict(HERO_LIGHTS)
    spec.update(lights or {})
    subject = subject if subject is not None else cam["subject"]
    made = {}
    for name, val in spec.items():
        if val is None:
            continue
        colour, ratio, size, az, el, dist = val
        if ratio <= 0:
            continue
        if dist is None:  # eye light: just above the lens, aimed at the eyes
            d = (cam["obj"].location - subject).length
            loc = cam["obj"].location + Vector((0, 0, 0.08))
            aim = ch.aim("eyes")
        else:
            d = dist
            loc = _around(subject, cam["obj"].location, az, el, dist)
            aim = subject
        made[name] = area_light(col, "hero_" + name, colour,
                                _light_power(ratio, e_key, d) * scale, size, loc, aim)
        if name in ("rim", "kicker"):
            made[name].data.volume_factor = 0.35  # rims glow in the haze, not flood it
        if name == "eye":
            made[name].data.use_shadow = False
            made[name].data.diffuse_factor = 0.3  # mostly a catchlight
        if name in flag:
            made[name].light_linking.receiver_collection = receivers(ch)
    return made


def turntable_rig(ch, cam, e_key=TT_E):
    col = collection("tt_rig")
    subject = ch.aim("chest")
    made = {}
    for name, (colour, ratio, size, az, el, dist) in TT_LIGHTS.items():
        loc = _around(subject, cam["obj"].location, az, el, dist)
        made[name] = area_light(col, "tt_" + name, colour, _light_power(ratio, e_key, dist),
                                size, loc, subject)
    return made


def world(colour=(0.003, 0.003, 0.004), strength=1.0):
    sc = bpy.context.scene
    w = bpy.data.worlds.get("hero_world") or bpy.data.worlds.new("hero_world")
    sc.world = w
    w.use_nodes = True
    bg = w.node_tree.nodes.get("Background")
    bg.inputs[0].default_value = (*colour, 1.0)
    bg.inputs[1].default_value = strength
    return w


def _mat(name, colour, rough, spec=0.5):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    p = m.node_tree.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = (*colour, 1)
    p.inputs["Roughness"].default_value = rough
    p.inputs["Specular IOR Level"].default_value = spec
    return m


def void_floor(albedo=0.03, rough=0.45):
    """Hero-rig default ground: a dark, slightly glossy floor (no set)."""
    col = collection("hero_ground")
    bpy.ops.mesh.primitive_plane_add(size=40, location=(0, 0, 0))
    fl = bpy.context.active_object
    for c in fl.users_collection:
        c.objects.unlink(fl)
    col.objects.link(fl)
    fl.name = "hero_floor"
    fl.data.materials.append(_mat("hero_floor", (albedo,) * 3, rough))
    return fl


def cyclorama(cam_loc, subject, albedo=0.18, back=3.0, radius=1.5, height=5.0, width=14.0):
    """18 % grey infinity cove: floor toward the camera, curving up into a
    wall `back` m behind the subject (relative to the camera)."""
    col = collection("tt_cyc")
    c = Vector(subject) - Vector(cam_loc)
    c.z = 0
    c.normalize()
    side = c.cross(Z)
    prof = [(-12.0, 0.0)]
    flat_end = back - radius
    prof.append((flat_end, 0.0))
    for i in range(1, 13):
        t = math.radians(90 * i / 12)
        prof.append((flat_end + radius * math.sin(t), radius * (1 - math.cos(t))))
    prof.append((back, height))
    verts, faces = [], []
    for u, z in prof:
        for sgn in (-1, 1):
            p = Vector((subject.x, subject.y, 0)) + c * u + side * (sgn * width / 2)
            verts.append((p.x, p.y, z))
    for i in range(len(prof) - 1):
        a = i * 2
        faces.append((a, a + 1, a + 3, a + 2))
    me = bpy.data.meshes.new("tt_cyc")
    me.from_pydata(verts, [], faces)
    me.update()
    for poly in me.polygons:
        poly.use_smooth = True
    ob = bpy.data.objects.new("tt_cyc", me)
    col.objects.link(ob)
    me.materials.append(_mat("tt_grey18", (albedo,) * 3, 0.9, 0.2))
    return ob


def haze(cam=None, density=0.012, anisotropy=0.6, size=(16, 16, 6)):
    """Cheap haze: one box of homogeneous volume scatter. With a camera, the
    box starts 0.6 m behind the subject (seen from the camera), so the haze
    reads behind the face, not in front of it (direction §6)."""
    centre = Vector((0, 0, size[2] / 2))
    rot = 0.0
    if cam is not None:
        c = cam["subject"] - cam["obj"].location
        c.z = 0
        c.normalize()
        centre = cam["subject"] + c * (0.6 + size[1] / 2)
        centre.z = size[2] / 2
        rot = math.atan2(c.y, c.x) - math.pi / 2
    col = collection("hero_haze")
    bpy.ops.mesh.primitive_cube_add(size=1, location=centre)
    ob = bpy.context.active_object
    ob.rotation_euler.z = rot
    for c in ob.users_collection:
        c.objects.unlink(ob)
    col.objects.link(ob)
    ob.name = "hero_haze"
    ob.scale = size
    m = bpy.data.materials.get("hero_haze") or bpy.data.materials.new("hero_haze")
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    vol = nt.nodes.new("ShaderNodeVolumeScatter")
    vol.inputs["Density"].default_value = density
    vol.inputs["Anisotropy"].default_value = anisotropy
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(vol.outputs[0], out.inputs["Volume"])
    ob.data.materials.append(m)
    ob.visible_shadow = False
    return ob


# --------------------------------------------------------------- cameras
def _parse_cam(spec):
    if spec in CAMERAS:
        return CAMERAS[spec]
    if spec.startswith("tt"):
        az = float(spec[2:] or 0)
        return (TT_LENS, az, ("h", 1.0), "body", TT_FRAME, None)
    kv = dict(p.split("=") for p in spec.split(","))
    el = ("h", float(kv["h"])) if "h" in kv else float(kv.get("el", 0))
    return (float(kv.get("lens", 50)), float(kv.get("az", 0)), el, kv.get("aim", "head"),
            float(kv.get("frame", 0.5)), float(kv["f"]) if "f" in kv else None)


def camera(ch, spec, dof=True, focus="near_eye"):
    """Camera for a preset name, `tt<deg>` or a custom spec. Frame height is
    measured at the aim point (vertical sensor fit, 24 mm full frame)."""
    lens, az, el, aim, frame_h, fstop = _parse_cam(spec)
    target = ch.aim(aim)
    dist = lens / 24.0 * frame_h
    a = math.radians(az)
    axis = Vector((math.sin(a), -math.cos(a), 0.0))
    if isinstance(el, tuple):
        h = el[1]
        flat = math.sqrt(max(dist * dist - (h - target.z) ** 2, 0.01))
        loc = Vector((target.x, target.y, 0)) + axis * flat
        loc.z = h
    else:
        e = math.radians(el)
        loc = target + (axis * math.cos(e) + Z * math.sin(e)) * dist
    cd = bpy.data.cameras.new("hero_cam_" + spec.replace(",", "_").replace("=", ""))
    cd.lens = lens
    cd.sensor_fit = "VERTICAL"
    cd.sensor_width, cd.sensor_height = 36.0, 24.0
    cd.clip_start, cd.clip_end = 0.05, 200.0
    cam = bpy.data.objects.new(cd.name, cd)
    collection("hero_cams", clear=False).objects.link(cam)
    cam.location = loc
    look_at(cam, target)
    bpy.context.scene.camera = cam
    focus_pt = target
    if aim in ("eyes", "head") and focus == "near_eye":
        # the near eye's cornea, not the eyeball centre (12 mm behind it):
        # at 135 mm the depth of field is a few mm
        el_, er_ = ch.eyes()
        c = el_ if (el_ - loc).length < (er_ - loc).length else er_
        focus_pt = c + (loc - c).normalized() * EYE_FRONT
    elif aim == "cuff_feet":
        focus_pt = ch.bone_head("hand_l")           # the cuff, not the empty air below it
    elif aim == "hands":
        focus_pt = (ch.bone_head("hand_l") + ch.bone_head("hand_r")) * 0.5
    if dof and fstop:
        cd.dof.use_dof = True
        cd.dof.focus_distance = (focus_pt - loc).length
        cd.dof.aperture_fstop = fstop
        cd.dof.aperture_blades = 7
        cd.dof.aperture_ratio = 1.0
    subject = ch.aim("eyes") if aim in ("eyes", "head") else ch.aim("chest")
    return {"obj": cam, "spec": spec, "lens": lens, "az": az, "frame_h": frame_h,
            "fstop": fstop if dof else None, "subject": subject, "aim": target}


# --------------------------------------------------------------- render
def cycles(quality="preview", res=(1920, 1080), samples=None, threads=0):
    sc = bpy.context.scene
    n, thr, pct = QUALITY[quality]
    r = sc.render
    r.engine = "CYCLES"
    r.resolution_x, r.resolution_y = res
    r.resolution_percentage = pct
    r.film_transparent = False
    r.use_persistent_data = True
    if threads:
        r.threads_mode = "FIXED"
        r.threads = threads
    c = sc.cycles
    c.device = "CPU"
    c.samples = samples or n
    c.use_adaptive_sampling = True
    c.adaptive_threshold = thr
    c.adaptive_min_samples = min(32, c.samples)
    c.use_denoising = True
    c.denoiser = "OPENIMAGEDENOISE"
    c.denoising_quality = "HIGH"
    c.denoising_prefilter = "ACCURATE"
    c.denoising_input_passes = "RGB_ALBEDO_NORMAL"
    if hasattr(c, "denoising_use_gpu"):
        c.denoising_use_gpu = False
    c.max_bounces = 12
    c.diffuse_bounces = 3
    c.glossy_bounces = 4
    c.transmission_bounces = 8
    c.volume_bounces = 1
    c.transparent_max_bounces = 48   # stacked hair cards and shells
    c.sample_clamp_indirect = 8.0
    c.caustics_reflective = False
    c.caustics_refractive = False
    c.blur_glossy = 0.5
    c.volume_step_rate = 4.0
    c.use_light_tree = True
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.look = "None"
    sc.display_settings.display_device = "sRGB"
    r.image_settings.media_type = "IMAGE"
    r.image_settings.file_format = "PNG"
    r.image_settings.color_mode = "RGB"
    r.image_settings.color_depth = "8"
    return {"samples": c.samples, "adaptive_threshold": thr, "res": list(res), "pct": pct}


def render(path, fmt="PNG"):
    sc = bpy.context.scene
    r = sc.render
    r.image_settings.media_type = "IMAGE"
    if fmt == "EXR":
        r.image_settings.file_format = "OPEN_EXR"
        r.image_settings.color_mode = "RGBA"
        r.image_settings.color_depth = "16"
        r.image_settings.exr_codec = "DWAA"
    else:
        r.image_settings.file_format = "PNG"
        r.image_settings.color_mode = "RGB"
        r.image_settings.color_depth = "8"
    r.filepath = path
    t = time.perf_counter()
    bpy.ops.render.render(write_still=True)
    return round(time.perf_counter() - t, 2)


# --------------------------------------------------------------- passes
def _principled(m):
    if not m or not m.node_tree:
        return None
    return next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)


def _variant(m, kind):
    """Copy of material m for a pass: 'clay' (grey 0.5, roughness 0.55, no
    normal map: pure geometry) or 'normal' (camera-space shading normal,
    normal maps included, as colour). Alpha cut-outs are kept."""
    v = m.copy()
    v.name = f"{m.name}__{kind}"
    nt = v.node_tree
    p = _principled(v)
    alpha_src = None
    normal_src = None
    if p is not None:
        if p.inputs["Alpha"].is_linked:
            alpha_src = p.inputs["Alpha"].links[0].from_socket
        if p.inputs["Normal"].is_linked:
            normal_src = p.inputs["Normal"].links[0].from_socket
    out = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL" and n.is_active_output), None)
    if out is None:
        out = nt.nodes.new("ShaderNodeOutputMaterial")
    if kind == "clay":
        sh = nt.nodes.new("ShaderNodeBsdfPrincipled")
        sh.inputs["Base Color"].default_value = (0.5, 0.5, 0.5, 1)
        sh.inputs["Roughness"].default_value = 0.55
        sh.inputs["Specular IOR Level"].default_value = 0.3
    else:
        geo = nt.nodes.new("ShaderNodeNewGeometry")
        vt = nt.nodes.new("ShaderNodeVectorTransform")
        vt.vector_type = "NORMAL"
        vt.convert_from, vt.convert_to = "WORLD", "CAMERA"
        nt.links.new(normal_src or geo.outputs["Normal"], vt.inputs[0])
        mp = nt.nodes.new("ShaderNodeVectorMath")
        mp.operation = "MULTIPLY_ADD"
        mp.inputs[1].default_value = (0.5, 0.5, -0.5)  # shader camera space looks down +Z: facing = blue
        mp.inputs[2].default_value = (0.5, 0.5, 0.5)
        nt.links.new(vt.outputs[0], mp.inputs[0])
        sh = nt.nodes.new("ShaderNodeEmission")
        nt.links.new(mp.outputs[0], sh.inputs["Color"])
    if alpha_src is not None:
        tr = nt.nodes.new("ShaderNodeBsdfTransparent")
        mix = nt.nodes.new("ShaderNodeMixShader")
        nt.links.new(alpha_src, mix.inputs[0])
        nt.links.new(tr.outputs[0], mix.inputs[1])
        nt.links.new(sh.outputs[0], mix.inputs[2])
        sh = mix
    for l in list(out.inputs["Surface"].links):
        nt.links.remove(l)
    for l in list(out.inputs["Displacement"].links):
        nt.links.remove(l)
    nt.links.new(sh.outputs[0], out.inputs["Surface"])
    return v


def material_pass(ch, kind):
    """Swap every character material for its `kind` variant; returns a
    restore function. Curves (strand hair) get a plain grey/normal shader."""
    saved, cache = [], {}
    for o in ch.objs:
        for i, s in enumerate(o.material_slots):
            if s.material is None:
                continue
            m = s.material
            if m.name not in cache:
                cache[m.name] = _variant(m, kind)
            saved.append((o, i, m))
            s.material = cache[m.name]

    def restore():
        for o, i, m in saved:
            o.material_slots[i].material = m
        for v in cache.values():
            bpy.data.materials.remove(v)
    return restore


def set_pass_view(kind):
    vs = bpy.context.scene.view_settings
    if kind == "normal":
        vs.view_transform = "Standard"
        vs.look = "None"
        vs.exposure = 0.0


# --------------------------------------------------------------- calibrate
def grey_cards(ch, cam):
    """Lambertian 18 % and 35 % (skin-mid) cards facing the camera at the
    subject, for exposure calibration. Returns the card objects."""
    col = collection("cal_cards")
    cards = []
    to_cam = (cam["obj"].location - cam["subject"]).normalized()
    side = to_cam.cross(Z).normalized()
    for i, alb in enumerate((0.18, 0.35)):
        loc = cam["subject"] + to_cam * 0.25 + side * (0.05 * (1 if i else -1))
        bpy.ops.mesh.primitive_plane_add(size=0.06, location=loc)
        c = bpy.context.active_object
        for cc in c.users_collection:
            cc.objects.unlink(c)
        col.objects.link(c)
        c.rotation_euler = to_cam.to_track_quat("Z", "Y").to_euler()
        m = _mat(f"card_{alb}", (alb,) * 3, 1.0, 0.0)
        c.data.materials.append(m)
        cards.append((alb, c))
    return cards


def card_values(path, cards):
    """Display value (0..1, mean of RGB over a small box) at each card centre
    in a rendered PNG."""
    import numpy as np
    from bpy_extras.object_utils import world_to_camera_view
    sc = bpy.context.scene
    img = bpy.data.images.load(path, check_existing=False)
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    bpy.data.images.remove(img)
    px = px.reshape(h, w, 4)
    out = {}
    for alb, c in cards:
        p = world_to_camera_view(sc, sc.camera, c.matrix_world.translation)
        x, y = int(p.x * w), int(p.y * h)
        r = max(1, w // 300)
        out[str(alb)] = [round(float(v), 3) for v in px[y - r:y + r + 1, x - r:x + r + 1, :3].mean((0, 1))]
    return out


# --------------------------------------------------------------- CLI
def parse_args(argv):
    ap = argparse.ArgumentParser(prog="rig.py")
    ap.add_argument("--in", dest="inp", required=True, help="character.blend or .glb")
    ap.add_argument("--out", required=True)
    ap.add_argument("--light", choices=["hero", "turntable", "both"], default="both")
    ap.add_argument("--cam", default="", help="cameras separated by ';' (or a comma list of presets); "
                    "default portrait;bust (hero), tt (turntable)")
    ap.add_argument("--pose", choices=poses.names(), default="rest")
    ap.add_argument("--quality", choices=sorted(QUALITY), default="preview")
    ap.add_argument("--samples", type=int, default=0)
    ap.add_argument("--res", default="", help="WxH (default 1920x1080; turntable 1080x1620)")
    ap.add_argument("--passes", default="beauty", help="beauty,clay,normal")
    ap.add_argument("--haze", action="store_true", help="hero rig: 0.03/m haze box")
    ap.add_argument("--no-dof", action="store_true")
    ap.add_argument("--exposure", type=float, default=None)
    ap.add_argument("--calibrate", action="store_true", help="add grey cards at the subject")
    return ap.parse_args(argv)


def _cams(arg, light):
    if arg:
        out = []
        # ';' separates cameras. Without one, a spec with '=' is ONE custom
        # camera (its fields are comma-separated); otherwise a comma list of presets.
        parts = arg.split(";") if ";" in arg else ([arg] if "=" in arg else arg.split(","))
        for c in (c.strip() for c in parts if c.strip()):
            out += [f"tt{a}" for a in range(0, 360, 45)] if c == "tt" else [c]
        return out
    return ["portrait", "bust"] if light == "hero" else [f"tt{a}" for a in range(0, 360, 45)]


def main(argv):
    a = parse_args(argv)
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    t0 = time.perf_counter()
    ch = load_character(a.inp)
    pose(ch, a.pose)
    rec = {"in": os.path.abspath(a.inp), "pose": a.pose, "pose_log": ch.pose_log,
           "quality": a.quality, "frames": [], "blender": bpy.app.version_string}
    lights = ["hero", "turntable"] if a.light == "both" else [a.light]
    passes = [p for p in a.passes.split(",") if p]
    for light in lights:
        res = tuple(int(v) for v in a.res.split("x")) if a.res else (
            (1920, 1080) if light == "hero" else (1080, 1620))
        for spec in _cams(a.cam if a.light != "both" or light == "hero" or not a.cam else "", light):
            for name in ("hero_rig", "tt_rig", "tt_cyc", "hero_ground", "hero_haze", "hero_cams", "cal_cards"):
                collection(name)
            tt = light == "turntable"
            cam = camera(ch, spec, dof=not (a.no_dof or tt))
            if tt:
                world((0.05, 0.05, 0.05), 1.0)
                turntable_rig(ch, cam)
                cyclorama(cam["obj"].location, ch.aim("body"))
                exposure = TT_EXPOSURE
            else:
                world()
                hero_rig(ch, cam)
                void_floor()
                if a.haze:
                    haze(cam)
                exposure = HERO_EXPOSURE
            cards = grey_cards(ch, cam) if a.calibrate else None
            settings = cycles(a.quality, res, a.samples or None)
            for kind in passes:
                cycles(a.quality, res, a.samples or None)
                vs = bpy.context.scene.view_settings
                vs.exposure = a.exposure if a.exposure is not None else exposure
                vs.look = HERO_LOOK if not tt else "None"
                restore = None
                if kind in ("clay", "normal"):
                    restore = material_pass(ch, kind)
                    set_pass_view(kind)
                    if kind == "normal":
                        bpy.context.scene.cycles.samples = 16
                        bpy.context.scene.cycles.use_denoising = False
                tag = f"{light}_{spec}" + ("" if kind == "beauty" else f"_{kind}")
                tag = tag.replace(",", "_").replace("=", "")
                secs = render(os.path.join(out, tag + ".png"))
                if restore:
                    restore()
                rec["frames"].append({"file": tag + ".png", "light": light, "cam": spec, "pass": kind,
                                      "seconds": secs, **settings})
                if cards and kind == "beauty":
                    rec["frames"][-1]["cards"] = card_values(os.path.join(out, tag + ".png"), cards)
                    print(f"[rig] cards {tag}: {rec['frames'][-1]['cards']}", flush=True)
                print(f"[rig] {tag}: {secs:.1f} s", flush=True)
    rec["total_s"] = round(time.perf_counter() - t0, 1)
    with open(os.path.join(out, "rig.json"), "w") as f:
        json.dump(rec, f, indent=1)


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
