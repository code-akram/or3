"""Beauty frames for a suit spike run (m1 v4 T13): Cycles, the lookdev materials.

Run on a spike run's spike.blend (bench/m1/v4/suit_beauty.sh does the locking):

  blender -b RUN/spike.blend --python suit_beauty.py -- --base BASE/character.blend --out RUN

The spike's clay renders strip the garments' materials, so they are appended again from the
lookdev base by name; the hero body (head, eyes, brows, lashes) is appended in place of the
spike's bare body. The pattern jacket gets wool on the outside and the turned edges, lining
inside, horn buttons (from its `part` face attribute: 0 wool, 1 lining, 2 edge, 3 button).
A run made with textures (T13 item 2, character/suit_made_tex.py) keeps its own materials
(t13_wool with the pattern-UV atlas, t13_lining, t13_button); both wools get the Cycles
weave (suit_textures.cycles_weave) and the pattern wool the hero twill (suit_hero), as the
lofted suit_wool has from the build. Older runs: plain black wool.
--grain renders the pattern jacket in a pinstripe (white lines along the grain every 1/2 in,
red cross lines every 5 cm), the check that the cloth runs straight down every panel.
Writes beauty_<lofted|pattern>_<view>.png, beauty_pattern_<close>.png, grain_<view>.png.
"""

import argparse
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--base", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--samples", type=int, default=96)
ap.add_argument("--res", type=int, default=800)
ap.add_argument("--views", default="front,three_quarter,profile,back")
ap.add_argument("--closes", default="close_pocket,close_button,close_lapel,close_collar_back,close_cuff_btn,close_34")
ap.add_argument("--grain", action="store_true", help="also the pinstripe grain check")
ap.add_argument("--only-grain", action="store_true")
ap.add_argument("--lods", default="", help="views of the textured LODs (e.g. front,three_quarter)")
A = ap.parse_args(argv)
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "blender"))

GARMENT_MATS = {"suit_shirt": ["suit_shirt"], "suit_waistcoat": ["suit_vest"], "suit_trousers": ["suit_wool_b"],
                "suit_shoes": ["suit_leather", "suit_sole"], "suit_tie": ["suit_silk"],
                "suit_jacket": ["suit_wool"], "suit_buttons": ["suit_button"]}
HERO = ("Human_export", "Human.eyes_hq_export", "Human.eyes_hero", "Human.brows_export",
        "Human.eyelash_cards_export", "Human.teeth_base_export", "eye_cornea_hero", "eye_caruncle_hero",
        "eye_meniscus_hero")

VIEWS = {"front": 0.0, "three_quarter": 35.0, "profile": 90.0, "back": 180.0}
CLOSES = {"close_pocket": (20.0, (0.12, -0.12, 1.02), 0.24, 0.15),
          "close_lapel": (20.0, (0.07, -0.12, 1.36), 0.20, 0.15),
          "close_button": (5.0, (0.0, -0.13, 1.125), 0.10, 0.15),
          "close_collar_back": (160.0, (0.0, 0.05, 1.57), 0.24, 0.05),
          "close_collar_side": (125.0, (0.0, 0.03, 1.55), 0.30, 0.05),
          "close_vent": (165.0, (0.10, 0.08, 0.98), 0.32, 0.0),
          "close_front_hem": (15.0, (0.03, -0.12, 0.98), 0.36, 0.1),
          "close_cuff_btn": (110.0, (0.47, -0.12, 1.12), 0.18, 0.15),
          "close_34": (35.0, (0.0, 0.0, 1.42), 0.62, 0.15)}


def append(path, objects=(), materials=()):
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        dst.objects = [n for n in src.objects if n in objects]
        dst.materials = [n for n in src.materials if n in materials]
    return dst.objects, {m.name: m for m in dst.materials if m is not None}


def principled(name, base, rough, sheen=0.0, coat=0.0, spec=0.5):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*base, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Sheen Weight"].default_value = sheen
    b.inputs["Sheen Roughness"].default_value = 0.35
    b.inputs["Coat Weight"].default_value = coat
    b.inputs["Specular IOR Level"].default_value = spec
    return m


def sk(socks, ident):
    return next(x for x in socks if x.identifier == ident)


def grain_material(side):
    """Pinstripe on the atlas UVs (x side = metres): white along v every 12.7 mm, red across
    every 50 mm."""
    m = bpy.data.materials.new("t13_grain")
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    b.inputs["Roughness"].default_value = 0.8
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["UV"], sep.inputs[0])

    def stripe(sock, period, width):
        a = nt.nodes.new("ShaderNodeMath")
        a.operation = "MULTIPLY"
        a.inputs[1].default_value = side / period
        nt.links.new(sock, a.inputs[0])
        f = nt.nodes.new("ShaderNodeMath")
        f.operation = "PINGPONG"
        f.inputs[1].default_value = 0.5
        nt.links.new(a.outputs[0], f.inputs[0])
        c = nt.nodes.new("ShaderNodeMath")
        c.operation = "LESS_THAN"
        c.inputs[1].default_value = width / period
        nt.links.new(f.outputs[0], c.inputs[0])
        return c.outputs[0]
    pin = stripe(sep.outputs["X"], 0.0127, 0.0009)
    cross = stripe(sep.outputs["Y"], 0.05, 0.0012)
    mix1 = nt.nodes.new("ShaderNodeMix")
    mix1.data_type = "RGBA"
    sk(mix1.inputs, "A_Color").default_value = (0.03, 0.03, 0.035, 1)
    sk(mix1.inputs, "B_Color").default_value = (0.75, 0.75, 0.75, 1)
    nt.links.new(pin, sk(mix1.inputs, "Factor_Float"))
    mix2 = nt.nodes.new("ShaderNodeMix")
    mix2.data_type = "RGBA"
    sk(mix2.inputs, "B_Color").default_value = (0.6, 0.05, 0.03, 1)
    nt.links.new(sk(mix1.outputs, "Result_Color"), sk(mix2.inputs, "A_Color"))
    nt.links.new(cross, sk(mix2.inputs, "Factor_Float"))
    nt.links.new(sk(mix2.outputs, "Result_Color"), b.inputs["Base Color"])
    return m


def main():
    sc = bpy.context.scene
    mats = {}
    allm = sorted({m for v in GARMENT_MATS.values() for m in v} | {"skin_head_hero", "skin_hands_hero", "eyes_hq",
                                                                     "eyes_hero", "brows_cards", "eyelash_cards",
                                                                     "Human.teeth_base", "eye_cornea_hero",
                                                                     "eye_caruncle_hero", "eye_meniscus_hero"})
    hero, mats = append(A.base, HERO, allm)
    coll = bpy.data.collections.new("beauty_hero")
    sc.collection.children.link(coll)
    rig = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
    for o in hero:
        if o is None:
            continue
        coll.objects.link(o)
        for m in o.modifiers:
            if m.type == "ARMATURE":
                m.object = rig
    # the garments' own materials (stripped by the clay pass)
    under = []
    for o in bpy.data.objects:
        if o.type != "MESH":
            continue
        key = next((k for k in GARMENT_MATS if k in o.name), None)
        if key is None:
            continue
        o.data.materials.clear()
        for mn in GARMENT_MATS[key]:
            o.data.materials.append(mats.get(mn) or bpy.data.materials.get(mn))
        if key not in ("suit_jacket", "suit_buttons"):
            under.append(o.name)
    # the pattern jacket
    # the lofted jacket's wool (its weave falls back to the material's own coordinates without
    # UVs); a plain black wool if the base has none
    own = bpy.data.materials.get("t13_wool")
    if own is not None:
        # the run's own pattern-UV materials (T13 item 2)
        from character import suit_hero, suit_textures
        suit_hero.twill(own, suit_hero.DEFAULTS["twill"])
        print("[beauty] cycles weave:", suit_textures.cycles_weave(), flush=True)
        wool, lining, btn = own, bpy.data.materials["t13_lining"], bpy.data.materials["t13_button"]
        for nm in ("t13_wool_normal", "suit_t13_wool_albedo", "suit_t13_wool_orm"):
            im = bpy.data.images.get(nm)
            if im is not None:      # the atlas, for the gate sheet
                w_, h_ = im.size
                buf = np.empty(w_ * h_ * 4, np.float32)
                im.pixels.foreach_get(buf)
                im2 = bpy.data.images.new(nm + "_out", w_, h_, alpha=False)
                im2.colorspace_settings.name = im.colorspace_settings.name
                im2.pixels.foreach_set(buf)
                im2.filepath_raw = os.path.join(A.out, f"atlas_{nm.replace('suit_', '')}.png")
                im2.file_format = "PNG"
                im2.save()
    else:
        wool = mats.get("suit_wool") or principled("t13_wool", (0.011, 0.011, 0.012), 0.78, sheen=0.25)
        lining = principled("t13_lining", (0.018, 0.017, 0.02), 0.32, sheen=0.3)
        btn = mats.get("suit_button") or principled("t13_horn", (0.015, 0.012, 0.01), 0.25, coat=0.6)
    grain = grain_material(own["suit_atlas_side_m"]) if (own is not None and (A.grain or A.only_grain)) else None
    pattern = []
    for o in bpy.data.objects:
        if o.type == "MESH" and o.name.startswith("spike_jacket_") and "lod" not in o.name:
            o.data.materials.clear()
            for m in (wool, lining, wool, btn):
                o.data.materials.append(m)
            a = o.data.attributes.get("part")
            if a is not None:
                vals = [0] * len(o.data.polygons)
                a.data.foreach_get("value", vals)
                o.data.polygons.foreach_set("material_index", vals)
            else:
                for p in o.data.polygons:
                    p.material_index = 0
            pattern.append(o.name)
    lofted = [o.name for o in bpy.data.objects if o.type == "MESH" and ("suit_jacket" in o.name or "suit_buttons" in o.name)]
    hero_names = [o.name for o in hero if o is not None and o.type == "MESH"]
    # render setup
    sc.render.engine = "CYCLES"
    sc.cycles.samples = A.samples
    sc.cycles.use_denoising = True
    sc.render.threads_mode = "FIXED"
    sc.render.threads = 6
    sc.render.resolution_x = sc.render.resolution_y = A.res
    sc.render.film_transparent = False
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.look = "AgX - Medium High Contrast"
    sc.frame_set(1)
    w = sc.world or bpy.data.worlds.new("w")
    sc.world = w
    w.use_nodes = True
    w.node_tree.nodes["Background"].inputs[0].default_value = (0.20, 0.205, 0.21, 1)
    w.node_tree.nodes["Background"].inputs[1].default_value = 0.35
    cam = bpy.data.objects.get("spike_cam")
    lights = [o for o in bpy.data.objects if o.type == "LIGHT" and o.name.startswith("spike_")]
    energy = {"spike_key": 260.0, "spike_fill": 70.0, "spike_rim": 220.0}
    for L in lights:
        L.data.energy = energy.get(L.name, L.data.energy)

    def shoot(tag, show, az_deg, tgt, scale, dz):
        for o in bpy.data.objects:
            if o.type == "MESH":
                o.hide_render = o.name not in show
        cam.data.type = "ORTHO"
        cam.data.ortho_scale = scale
        sc.camera = cam
        az = math.radians(az_deg)
        tv = Vector(tgt)
        cam.location = tv + Vector((math.sin(az), -math.cos(az), 0.0)) * 4.0 + Vector((0, 0, dz))
        cam.rotation_euler = (tv - cam.location).to_track_quat("-Z", "Y").to_euler()
        for o in lights:
            a = az + math.radians(o["az"])
            el = math.radians(o["el"])
            o.location = tv + Vector((math.sin(a) * math.cos(el), -math.cos(a) * math.cos(el), math.sin(el))) * 2.5
            o.rotation_euler = (tv - o.location).to_track_quat("-Z", "Y").to_euler()
        sc.render.filepath = os.path.join(A.out, f"beauty_{tag}.png")
        bpy.ops.render.render(write_still=True)
        print(f"[beauty] {tag}", flush=True)

    base_show = hero_names + under
    if grain is not None:
        keep = {}
        for n in pattern:
            me = bpy.data.objects[n].data
            if me.uv_layers:
                keep[n] = me.materials[0]
                me.materials[0] = grain
                me.materials[2] = grain
        for v in ("front", "three_quarter", "back"):
            shoot(f"grain_{v}", base_show + pattern, VIEWS[v], (0, 0, 1.22), 1.15, 0.15)
        shoot("grain_close_34", base_show + pattern, *CLOSES["close_34"])
        shoot("grain_close_cuff_btn", base_show + pattern, *CLOSES["close_cuff_btn"])
        for n, m in keep.items():
            bpy.data.objects[n].data.materials[0] = m
            bpy.data.objects[n].data.materials[2] = m
        if A.only_grain:
            return
    for v in [x for x in A.views.split(",") if x]:
        shoot(f"lofted_{v}", base_show + lofted, VIEWS[v], (0, 0, 1.22), 1.15, 0.15)
        shoot(f"pattern_{v}", base_show + pattern, VIEWS[v], (0, 0, 1.22), 1.15, 0.15)
    for c in [x for x in A.closes.split(",") if x]:
        az, tgt, scale, dz = CLOSES[c]
        shoot(f"pattern_{c}", base_show + pattern, az, tgt, scale, dz)
    for ob in sorted((o for o in bpy.data.objects if o.name.startswith("spike_jacket_lod")), key=lambda o: o.name):
        for v in [x for x in A.lods.split(",") if x]:
            shoot(f"{ob.name.removeprefix('spike_jacket_')}_{v}", base_show + [ob.name], VIEWS[v], (0, 0, 1.22), 1.15, 0.15)


main()
