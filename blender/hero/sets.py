"""Hero sets: the neon-noir alley (wet asphalt, puddles, brick and concrete
walls, invented neon signs, cables, haze, rain). The neutral studio is the
turntable cove in rig.py.

Layout (metres; the character stands at the origin facing -Y, +X is its
left): an alley running along Y, brick wall at x = -2.6 (frame left from the
front), concrete wall at x = +3.2, a lit street at each end (y = +24 amber
sodium, y = -24 cool). Signs sit at both ends so back views have a
background too. Set lights (sign spill, street lamps) are fixed in the world;
the character rig (rig.hero_rig) is placed per camera on top of them.

Textures: Poly Haven CC0 (blender/hero/fetch_textures.py; records in
provenance/mesh.jsonl), looked up under VENDOR/polyhaven/<asset>/.
Everything here is render-only and never ships.
"""

import math
import os
import random

import bmesh
import bpy
from mathutils import Vector

from hero import rig

VENDOR = os.environ.get("HERO_VENDOR", "/home/akram/code/or3/data/vendor")
WALL_L, WALL_R = -2.6, 3.2
# Sign spill power per unit of tube emission strength (W): at ~3 m a sign
# lights the character at ~0.3-0.5 of the key (rig.HERO_E).
SPILL = 1.0
LENGTH = 48.0

NEON = {  # linear RGB, emission colour of the tubes
    "magenta": (1.0, 0.06, 0.42),
    "teal": (0.02, 0.85, 0.80),
    "amber": (1.0, 0.42, 0.06),
    "red": (1.0, 0.05, 0.03),
    "cold": (0.55, 0.75, 1.0),
}


# ------------------------------------------------------------- materials
def _tex(nt, path, colour=True):
    n = nt.nodes.new("ShaderNodeTexImage")
    n.image = bpy.data.images.load(path, check_existing=True)
    n.image.colorspace_settings.name = "sRGB" if colour else "Non-Color"
    return n


def _maps(asset):
    d = os.path.join(VENDOR, "polyhaven", asset)
    return {k: os.path.join(d, f"{asset}_{k}_2k.jpg") for k in ("diff", "nor_gl", "rough", "disp")}


def _mul(nt, a, b, fac=1.0):
    """Colour multiply (Mix node, RGBA): a * b blended by fac; returns the
    output socket. a, b: sockets or RGBA tuples; fac: socket or float."""
    n = nt.nodes.new("ShaderNodeMix")
    n.data_type = "RGBA"
    n.blend_type = "MULTIPLY"
    if isinstance(fac, bpy.types.NodeSocket):
        nt.links.new(fac, n.inputs[0])
    else:
        n.inputs[0].default_value = fac
    for sock, v in ((n.inputs[6], a), (n.inputs[7], b)):
        if isinstance(v, bpy.types.NodeSocket):
            nt.links.new(v, sock)
        else:
            sock.default_value = v
    return n.outputs[2]


def pbr_material(name, asset, darken=1.0, rough_mul=1.0, rough_add=0.0, wet_low=0.0,
                 puddles=0.0, normal=1.0):
    """Principled material from a Poly Haven set, in UV space (meshes carry
    UVs in tiles). darken scales the albedo (wet surfaces read darker),
    rough_* remap roughness. wet_low: a wet band up the wall base (m).
    puddles: fraction of the ground under standing water (from the height map
    plus large-scale noise): albedo x0.4, roughness 0.04, flat normal."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    p = nt.nodes["Principled BSDF"]
    mp = _maps(asset)
    uv = nt.nodes.new("ShaderNodeTexCoord")
    diff = _tex(nt, mp["diff"])
    rough = _tex(nt, mp["rough"], False)
    nor = _tex(nt, mp["nor_gl"], False)
    disp = _tex(nt, mp["disp"], False)
    for t in (diff, rough, nor, disp):
        nt.links.new(uv.outputs["UV"], t.inputs["Vector"])
    # albedo
    dk = _mul(nt, diff.outputs["Color"], (darken, darken, darken, 1))
    # roughness
    rr = nt.nodes.new("ShaderNodeMapRange")
    rr.inputs["To Min"].default_value = rough_add
    rr.inputs["To Max"].default_value = rough_add + rough_mul
    rr.clamp = True
    nt.links.new(rough.outputs["Color"], rr.inputs["Value"])
    nm = nt.nodes.new("ShaderNodeNormalMap")
    nm.inputs["Strength"].default_value = normal
    nt.links.new(nor.outputs["Color"], nm.inputs["Color"])
    base_out, rough_out, nrm_out = dk, rr.outputs["Result"], nm.outputs["Normal"]

    def mix(a, b, fac, kind="RGBA"):
        n = nt.nodes.new("ShaderNodeMix")
        n.data_type = kind
        nt.links.new(fac, n.inputs["Factor"])
        if kind == "RGBA":
            ia, ib, o = n.inputs[6], n.inputs[7], n.outputs[2]
        elif kind == "FLOAT":
            ia, ib, o = n.inputs[2], n.inputs[3], n.outputs[0]
        else:
            ia, ib, o = n.inputs[4], n.inputs[5], n.outputs[1]
        for sock, v in ((ia, a), (ib, b)):
            if isinstance(v, bpy.types.NodeSocket):
                nt.links.new(v, sock)
            else:
                sock.default_value = v
        return o

    if wet_low:
        geo = nt.nodes.new("ShaderNodeNewGeometry")
        sep = nt.nodes.new("ShaderNodeSeparateXYZ")
        nt.links.new(geo.outputs["Position"], sep.inputs[0])
        w = nt.nodes.new("ShaderNodeMapRange")
        w.inputs["From Min"].default_value = wet_low
        w.inputs["From Max"].default_value = 0.0
        nt.links.new(sep.outputs["Z"], w.inputs["Value"])
        base_out = _mul(nt, base_out, (0.55, 0.55, 0.55, 1), w.outputs["Result"])
        rough_out = mix(rough_out, 0.18, w.outputs["Result"], "FLOAT")
    if puddles:
        geo = nt.nodes.new("ShaderNodeNewGeometry")
        nz = nt.nodes.new("ShaderNodeTexNoise")
        nz.inputs["Scale"].default_value = 0.35
        nz.inputs["Detail"].default_value = 4.0
        nz.inputs["Roughness"].default_value = 0.6
        nt.links.new(geo.outputs["Position"], nz.inputs["Vector"])
        add = nt.nodes.new("ShaderNodeMath")
        add.operation = "MULTIPLY_ADD"
        add.inputs[1].default_value = 0.9
        nt.links.new(nz.outputs["Fac"], add.inputs[0])
        nt.links.new(disp.outputs["Color"], add.inputs[2])
        # low height + low noise = water; threshold sets the wet fraction
        thr = 0.95 + 0.25 * (puddles - 0.3)
        pm = nt.nodes.new("ShaderNodeMapRange")
        pm.inputs["From Min"].default_value = thr + 0.03
        pm.inputs["From Max"].default_value = thr - 0.03
        pm.clamp = True
        nt.links.new(add.outputs["Value"], pm.inputs["Value"])
        pud = pm.outputs["Result"]
        base_out = _mul(nt, base_out, (0.35, 0.35, 0.37, 1), pud)
        rough_out = mix(rough_out, 0.035, pud, "FLOAT")
        # puddles: flat water with a faint rain-ripple bump
        rip = nt.nodes.new("ShaderNodeTexNoise")
        rip.inputs["Scale"].default_value = 60.0
        rip.inputs["Detail"].default_value = 2.0
        nt.links.new(geo.outputs["Position"], rip.inputs["Vector"])
        bump = nt.nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = 0.04
        bump.inputs["Distance"].default_value = 0.002
        nt.links.new(rip.outputs["Fac"], bump.inputs["Height"])
        nrm_out = mix(nrm_out, bump.outputs["Normal"], pud, "VECTOR")
        m["puddle_threshold"] = thr
    nt.links.new(base_out, p.inputs["Base Color"])
    nt.links.new(rough_out, p.inputs["Roughness"])
    nt.links.new(nrm_out, p.inputs["Normal"])
    p.inputs["Specular IOR Level"].default_value = 0.5
    return m


def plain(name, colour, rough=0.5, metallic=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    p = m.node_tree.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = (*colour, 1)
    p.inputs["Roughness"].default_value = rough
    p.inputs["Metallic"].default_value = metallic
    return m


def emissive(name, colour, strength, glass=True):
    """Neon tube / lightbox face: emission plus a thin glossy glass sheen."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    p = nt.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = (*[0.2 + 0.8 * c for c in colour], 1)
    p.inputs["Emission Color"].default_value = (*colour, 1)
    p.inputs["Emission Strength"].default_value = strength
    p.inputs["Roughness"].default_value = 0.15 if glass else 0.6
    return m


# ------------------------------------------------------------- geometry
def _link(col, ob):
    for c in ob.users_collection:
        c.objects.unlink(ob)
    col.objects.link(ob)
    return ob


def quad(col, name, corners, tile, mat):
    """A quad with UVs in tile units: corners (4 x Vector) in order; u along
    corner0->corner1, v along corner0->corner3."""
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(c) for c in corners], [], [(0, 1, 2, 3)])
    uv = me.uv_layers.new()
    lu = (corners[1] - corners[0]).length / tile
    lv = (corners[3] - corners[0]).length / tile
    for li, (u, v) in zip(range(4), ((0, 0), (lu, 0), (lu, lv), (0, lv))):
        uv.data[li].uv = (u, v)
    me.materials.append(mat)
    ob = bpy.data.objects.new(name, me)
    col.objects.link(ob)
    return ob


def box(col, name, size, loc, mat, rot_z=0.0):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    ob = _link(col, bpy.context.active_object)
    ob.name = name
    ob.scale = size
    ob.rotation_euler.z = rot_z
    ob.data.materials.append(mat)
    return ob


def tube(col, name, points, radius, mat, closed=False):
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = radius
    cu.bevel_resolution = 3
    sp = cu.splines.new("POLY")
    sp.points.add(len(points) - 1)
    for p, c in zip(sp.points, points):
        p.co = (*c, 1.0)
    sp.use_cyclic_u = closed
    cu.materials.append(mat)
    ob = bpy.data.objects.new(name, cu)
    col.objects.link(ob)
    return ob


def text(col, name, body, size, mat, loc, rot, extrude=0.01, bevel=0.004):
    cu = bpy.data.curves.new(name, "FONT")
    cu.body = body
    cu.size = size
    cu.align_x = "CENTER"
    cu.align_y = "CENTER"
    cu.extrude = extrude
    cu.bevel_depth = bevel
    cu.materials.append(mat)
    ob = bpy.data.objects.new(name, cu)
    col.objects.link(ob)
    ob.location = loc
    ob.rotation_euler = rot
    return ob


def spill(col, name, colour, power, size, loc, aim):
    ob = rig.area_light(col, name, colour, power, size, loc, aim)
    ob.data.volume_factor = 0.6
    return ob


# ------------------------------------------------------------- signs
def sign_blade(col, name, word, colour, wall_x, y, z, facing, strength=30.0, letter=0.34):
    """Vertical blade sign sticking out of a wall: a dark box with the word
    stacked letter by letter on both faces, framed by a neon tube."""
    n = len(word)
    h = n * letter * 1.12 + 0.25
    out = 0.55 * facing   # sign centre this far from the wall
    cx = wall_x + out
    box(col, name + "_box", (0.12, 0.62, h), (cx, y, z), plain(name + "_body", (0.02, 0.02, 0.022), 0.4))
    em = emissive(name + "_neon", NEON[colour], strength)
    for side in (-1, 1):
        x = cx + side * 0.07
        for i, ch in enumerate(word):
            zz = z + h / 2 - 0.2 - (i + 0.5) * letter * 1.12
            text(col, f"{name}_{side}_{i}", ch, letter, em, (x, y, zz),
                 (math.pi / 2, 0, side * math.pi / 2), extrude=0.008, bevel=0.003)
        fr = [(x, y - 0.27, z - h / 2 + 0.06), (x, y + 0.27, z - h / 2 + 0.06),
              (x, y + 0.27, z + h / 2 - 0.06), (x, y - 0.27, z + h / 2 - 0.06)]
        tube(col, f"{name}_frame{side}", fr, 0.011, em, closed=True)
    # bracket to the wall
    box(col, name + "_arm", (abs(out), 0.05, 0.05), (wall_x + out / 2, y, z + h / 2 - 0.1),
        plain(name + "_steel", (0.05, 0.05, 0.05), 0.35, 1.0))
    spill(col, name + "_spill", NEON[colour], strength * SPILL * 1.5, (0.8, h), (cx, y, z), (cx - facing * 3, y, 0.6))
    spill(col, name + "_spill2", NEON[colour], strength * SPILL * 0.6, (0.8, h), (cx, y, z), (cx, y - 3, 0.8))
    spill(col, name + "_spill3", NEON[colour], strength * SPILL * 0.6, (0.8, h), (cx, y, z), (cx, y + 3, 0.8))


def sign_wall(col, name, word, colour, wall_x, y, z, facing, strength=25.0, size=0.42):
    """Flat neon word on a wall (tube letters on a dark back plate)."""
    w = len(word) * size * 0.75 + 0.4
    box(col, name + "_plate", (0.04, w, size + 0.3), (wall_x + facing * 0.03, y, z),
        plain(name + "_plate", (0.015, 0.015, 0.017), 0.5))
    em = emissive(name + "_neon", NEON[colour], strength)
    text(col, name + "_word", word, size, em, (wall_x + facing * 0.07, y, z),
         (math.pi / 2, 0, facing * math.pi / 2), extrude=0.012, bevel=0.005)
    spill(col, name + "_spill", NEON[colour], strength * SPILL, (w, 0.5),
          (wall_x + facing * 0.25, y, z), (wall_x + facing * 3, y, 0.4))


def sign_shape(col, name, kind, colour, wall_x, y, z, facing, strength=30.0, scale=1.0):
    """Abstract neon tube shapes: 'ring', 'arrow', 'zigzag', 'bars'."""
    em = emissive(name + "_neon", NEON[colour], strength)
    x = wall_x + facing * 0.08
    s = scale
    if kind == "ring":
        pts = [(x, y + 0.45 * s * math.cos(t), z + 0.45 * s * math.sin(t))
               for t in [i * 2 * math.pi / 40 for i in range(40)]]
        tube(col, name, pts, 0.014, em, closed=True)
        pts = [(x, y + 0.3 * s * math.cos(t), z + 0.3 * s * math.sin(t))
               for t in [i * 2 * math.pi / 32 for i in range(32)]]
        tube(col, name + "_in", pts, 0.012, em, closed=True)
    elif kind == "arrow":
        pts = [(x, y - 0.9 * s, z), (x, y + 0.5 * s, z), (x, y + 0.5 * s, z + 0.25 * s),
               (x, y + 0.95 * s, z - 0.05 * s), (x, y + 0.5 * s, z - 0.35 * s),
               (x, y + 0.5 * s, z - 0.12 * s), (x, y - 0.9 * s, z - 0.12 * s)]
        tube(col, name, pts, 0.013, em, closed=True)
    elif kind == "zigzag":
        pts = [(x, y + (i - 4) * 0.18 * s, z + (0.18 * s if i % 2 else -0.18 * s)) for i in range(9)]
        tube(col, name, pts, 0.013, em)
    elif kind == "bars":
        for i in range(4):
            zz = z + (i - 1.5) * 0.16 * s
            tube(col, f"{name}_{i}", [(x, y - 0.6 * s, zz), (x, y + 0.6 * s, zz)], 0.012, em)
    spill(col, name + "_spill", NEON[colour], strength * SPILL, (1.2 * s, 0.8 * s),
          (wall_x + facing * 0.3, y, z), (wall_x + facing * 3, y, 0.4))


# ------------------------------------------------------------- the alley
def alley(haze_density=0.0):
    """Build the alley set. Returns its collection."""
    col = rig.collection("set_alley")
    L = LENGTH
    ground = pbr_material("set_asphalt", "road_damaged", darken=0.5, rough_mul=0.55,
                          rough_add=0.08, puddles=0.35, normal=0.8)
    brick = pbr_material("set_brick", "red_brick_03", darken=0.55, rough_mul=0.8,
                         rough_add=0.1, wet_low=1.2)
    conc = pbr_material("set_concrete", "concrete_wall_008", darken=0.22, rough_mul=0.8,
                        rough_add=0.1, wet_low=1.5)
    V = Vector
    quad(col, "set_ground", [V((-8, -L / 2, 0)), V((8, -L / 2, 0)), V((8, L / 2, 0)), V((-8, L / 2, 0))],
         2.6, ground)
    quad(col, "set_wall_l", [V((WALL_L, -L / 2, 0)), V((WALL_L, L / 2, 0)),
                             V((WALL_L, L / 2, 9)), V((WALL_L, -L / 2, 9))], 2.2, brick)
    quad(col, "set_wall_r", [V((WALL_R, L / 2, 0)), V((WALL_R, -L / 2, 0)),
                             V((WALL_R, -L / 2, 9)), V((WALL_R, L / 2, 9))], 3.0, conc)
    # kerb strips along the wall bases
    kerb = plain("set_kerb", (0.05, 0.05, 0.05), 0.3)
    box(col, "set_kerb_l", (0.35, L, 0.12), (WALL_L + 0.175, 0, 0.06), kerb)
    box(col, "set_kerb_r", (0.35, L, 0.12), (WALL_R - 0.175, 0, 0.06), kerb)

    # signs: (+Y = behind the character from the front cameras)
    sign_blade(col, "sg_hotel", "HOTEL", "magenta", WALL_L, 3.2, 3.6, +1, strength=40)
    sign_shape(col, "sg_ring", "ring", "teal", WALL_R, 5.5, 2.9, -1, strength=35)
    sign_wall(col, "sg_bar", "BAR", "amber", WALL_L, 9.5, 2.6, +1, strength=30)
    sign_shape(col, "sg_arrow", "arrow", "magenta", WALL_R, 12.0, 3.4, -1, strength=30)
    sign_blade(col, "sg_noodle", "RAMEN", "teal", WALL_R, 16.0, 4.0, -1, strength=35, letter=0.3)
    sign_shape(col, "sg_bars", "bars", "amber", WALL_L, 18.5, 3.0, +1, strength=25)
    # behind the front cameras (for back and profile views)
    sign_blade(col, "sg_open", "OPEN", "teal", WALL_L, -6.0, 3.2, +1, strength=35)
    sign_shape(col, "sg_zig", "zigzag", "magenta", WALL_R, -9.0, 3.0, -1, strength=35)
    sign_wall(col, "sg_kissa", "KISSA", "amber", WALL_R, -3.5, 2.7, -1, strength=30)
    sign_shape(col, "sg_ring2", "ring", "red", WALL_L, -13.0, 3.6, +1, strength=25, scale=0.8)

    # a doorway in the concrete wall, with a warm bulkhead lamp over it
    dark = plain("set_door", (0.012, 0.012, 0.014), 0.35, 0.6)
    box(col, "set_door", (0.08, 1.0, 2.1), (WALL_R - 0.02, 1.4, 1.05), dark)
    lamp = emissive("set_bulkhead", (1.0, 0.55, 0.22), 12.0)
    box(col, "set_bulkhead", (0.12, 0.25, 0.12), (WALL_R - 0.08, 1.4, 2.4), lamp)
    spill(col, "set_bulkhead_l", 2400, 15.0, (0.3, 0.3), (WALL_R - 0.25, 1.4, 2.3), (1.5, 1.4, 0.0))

    # pipes, AC units, a dumpster, overhead cables
    metal = plain("set_metal", (0.06, 0.06, 0.065), 0.35, 1.0)
    for y in (-4.0, 7.5, 14.0):
        bpy.ops.mesh.primitive_cylinder_add(radius=0.05, depth=9, location=(WALL_L + 0.12, y, 4.5))
        _link(col, bpy.context.active_object).data.materials.append(metal)
    unit = plain("set_ac", (0.12, 0.12, 0.11), 0.6)
    for y, z in ((3.0, 3.8), (8.5, 4.6), (-7.0, 4.2), (14.5, 3.5)):
        box(col, f"set_ac_{y}", (0.55, 0.8, 0.6), (WALL_R - 0.28, y, z), unit)
    box(col, "set_dumpster", (1.1, 1.9, 1.15), (WALL_L + 0.75, 6.8, 0.6),
        plain("set_dumpster", (0.025, 0.06, 0.04), 0.45, 0.3))
    cable = plain("set_cable", (0.01, 0.01, 0.01), 0.5)
    rnd = random.Random(7)
    for i, y in enumerate((-8.0, -2.5, 2.2, 4.8, 8.8, 13.5, 19.0)):
        z0 = 5.0 + rnd.uniform(-0.6, 0.8)
        sag = rnd.uniform(0.4, 0.9)
        pts = [(WALL_L + (WALL_R - WALL_L) * t, y + rnd.uniform(-0.3, 0.3) * t,
                z0 - sag * 4 * t * (1 - t)) for t in [k / 16 for k in range(17)]]
        tube(col, f"set_cable_{i}", pts, 0.008, cable)

    # street light at each end, through the haze
    for name, y, temp, power in (("far", 21.0, 1900, 250.0), ("near", -21.0, 4500, 250.0)):
        ld = bpy.data.lights.new("set_street_" + name, "SPOT")
        ld.use_temperature = True
        ld.temperature = temp
        ld.energy = power
        ld.spot_size = math.radians(80)
        ld.spot_blend = 0.6
        ld.shadow_soft_size = 0.15
        ob = bpy.data.objects.new(ld.name, ld)
        col.objects.link(ob)
        ob.location = (0.4, y, 6.0)
        rig.look_at(ob, Vector((0.2, y - math.copysign(4.0, y), 0)))
        glow = emissive("set_street_" + name, (1.0, 0.55, 0.2) if temp < 3000 else (0.7, 0.85, 1.0), 0.03, False)
        quad(col, "set_street_" + name + "_bg",
             [V((-8, math.copysign(L / 2 - 0.01, y), 0)), V((8, math.copysign(L / 2 - 0.01, y), 0)),
              V((8, math.copysign(L / 2 - 0.01, y), 9)), V((-8, math.copysign(L / 2 - 0.01, y), 9))],
             4.0, glow)
    rig.world((0.005, 0.009, 0.016), 1.0)   # cool night-sky ambient for the shadows
    # one root for the whole set, so a shot can turn the alley to its camera
    root = bpy.data.objects.new("set_root", None)
    col.objects.link(root)
    for o in col.objects:
        if o is not root and o.parent is None:
            o.parent = root
    return col


def turn(yaw_deg):
    """Turn the alley about the character (z axis) so a camera at azimuth
    yaw_deg looks straight down it (a set cheat, like moving a flat)."""
    root = bpy.data.objects.get("set_root")
    if root is not None:
        root.rotation_euler.z = math.radians(yaw_deg)
        bpy.context.view_layer.update()


# ------------------------------------------------------------- rain
def rain(cam, count=2500, near=1.3, far=16.0, length=(0.18, 0.45), radius=0.0011, wind=(0.06, 0.02),
         seed=3, avoid=None):
    """Rain streaks in the camera's view volume between `near` and `far` m:
    thin tilted cylinders with a transparent-glossy shader that catches the
    neon. `avoid` (centre, radius): no streaks inside that sphere (keeps them
    off the face)."""
    col = rig.collection("set_rain")
    co = cam["obj"]
    m = co.matrix_world
    cd = co.data
    vfov = 2 * math.atan(cd.sensor_height / (2 * cd.lens))
    sc = bpy.context.scene
    aspect = sc.render.resolution_x / sc.render.resolution_y
    rnd = random.Random(seed)
    bm = bmesh.new()
    w = Vector(wind)
    made = 0
    tries = 0
    while made < count and tries < count * 4:
        tries += 1
        # uniform in volume of the frustum slice
        u = rnd.random()
        d = (near ** 3 + u * (far ** 3 - near ** 3)) ** (1 / 3)
        hy = math.tan(vfov / 2) * d * 1.1
        hx = hy * aspect
        local = Vector((rnd.uniform(-hx, hx), rnd.uniform(-hy, hy), -d))
        p = m @ local
        if p.z < 0.05:
            continue
        if avoid and (p - avoid[0]).length < avoid[1]:
            continue
        ln = rnd.uniform(*length)
        dirv = Vector((w.x, w.y, -1.0)).normalized()
        a, b = p - dirv * ln / 2, p + dirv * ln / 2
        r = radius * rnd.uniform(0.7, 1.3)
        side = dirv.cross(Vector((1, 0, 0))).normalized()
        side2 = dirv.cross(side).normalized()
        ring_a, ring_b = [], []
        for k in range(3):
            t = 2 * math.pi * k / 3
            off = (side * math.cos(t) + side2 * math.sin(t)) * r
            ring_a.append(bm.verts.new(a + off))
            ring_b.append(bm.verts.new(b + off))
        for k in range(3):
            bm.faces.new((ring_a[k], ring_a[(k + 1) % 3], ring_b[(k + 1) % 3], ring_b[k]))
        made += 1
    me = bpy.data.meshes.new("set_rain")
    bm.to_mesh(me)
    bm.free()
    mat = bpy.data.materials.get("set_rain")
    if mat is None:
        mat = bpy.data.materials.new("set_rain")
        mat.use_nodes = True
        nt = mat.node_tree
        for n in list(nt.nodes):
            nt.nodes.remove(n)
        tr = nt.nodes.new("ShaderNodeBsdfTransparent")
        gl = nt.nodes.new("ShaderNodeBsdfGlossy")
        gl.inputs["Roughness"].default_value = 0.12
        mix = nt.nodes.new("ShaderNodeMixShader")
        mix.inputs[0].default_value = 0.22
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        nt.links.new(tr.outputs[0], mix.inputs[1])
        nt.links.new(gl.outputs[0], mix.inputs[2])
        nt.links.new(mix.outputs[0], out.inputs["Surface"])
    me.materials.append(mat)
    ob = bpy.data.objects.new("set_rain", me)
    col.objects.link(ob)
    ob.visible_shadow = False
    return made
