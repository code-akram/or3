"""Render-side wetness for the rain shots (direction §5): water beads on the
jacket shoulders, wet hair tips, and the eyes turned toward the camera.
Nothing here edits the build: beads are transient objects, the hair-tip
nodes are driven by one value (0 = dry), and the eye rotation is undone by
restore().

    from hero import wet
    wet.beads(ch, per_side=35)        # close-ups (portrait, bust, back, profile)
    wet.hair_tips(ch, 1.0)            # every rain shot; 0.0 turns it off
    wet.gaze(ch, cam_location, off_deg=5)
    wet.restore(ch)                   # before the next shot
"""

import math
import random

import bmesh
import bpy
from mathutils import Matrix, Quaternion, Vector

from hero import rig

HAIR_MATS = ("hair", "hair_cards", "hair_under", "hair_groom")
TIP = 0.3        # the outer 30 % of each strand (card UV0.v / strand intercept, root 0 -> tip 1) gets wet
_EYES = {}       # eye object name -> original vertex coordinates


# ------------------------------------------------------------------- beads
def _water():
    m = bpy.data.materials.get("hero_water")
    if m:
        return m
    m = bpy.data.materials.new("hero_water")
    m.use_nodes = True
    p = m.node_tree.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = (1, 1, 1, 1)
    p.inputs["Roughness"].default_value = 0.02
    p.inputs["IOR"].default_value = 1.33
    p.inputs["Transmission Weight"].default_value = 1.0
    return m


def beads(ch, per_side=35, radius=(0.00025, 0.00075), seed=11):
    """`per_side` water drops (0.5-1.5 mm across) on the top of each jacket
    shoulder, on the posed jacket surface: flattened spheres sitting on the
    cloth. Returns the count placed."""
    col = rig.collection("hero_wet")
    jacket = next((o for o in ch.objs if o.type == "MESH" and "jacket" in o.name.lower()), None)
    if jacket is None:
        return 0
    dg = bpy.context.evaluated_depsgraph_get()
    ev = jacket.evaluated_get(dg)
    me = ev.to_mesh()
    mw = ev.matrix_world
    rnd = random.Random(seed)
    bm = bmesh.new()
    n = 0
    for side in ("l", "r"):
        j = ch.bone_head("upperarm_" + side)
        c = ch.bone_head("clavicle_" + side)
        cands = []
        for poly in me.polygons:
            p = mw @ poly.center
            nrm = (mw.to_3x3() @ poly.normal).normalized()
            # the top of the shoulder: from the neck side of the clavicle out
            # to the arm joint, facing up
            t = (p - c).dot(j - c) / max((j - c).length_squared, 1e-6)
            if nrm.z < 0.55 or not (0.25 < t < 1.1) or p.z < j.z:
                continue
            if (p - c).cross((j - c).normalized()).length > 0.13:   # the pad sits ~8 cm over the joint line
                continue
            cands.append((poly.area, poly.index))
        if not cands:
            continue
        total = sum(a for a, _ in cands)
        for _ in range(per_side):
            x = rnd.uniform(0, total)
            for a, i in cands:
                x -= a
                if x <= 0:
                    break
            poly = me.polygons[i]
            vs = [mw @ me.vertices[v].co for v in poly.vertices]
            w = [rnd.random() for _ in vs]
            s = sum(w)
            p = sum((v * (k / s) for v, k in zip(vs, w)), Vector())
            nrm = (mw.to_3x3() @ poly.normal).normalized()
            r = rnd.uniform(*radius)
            q = Vector((0, 0, 1)).rotation_difference(nrm)
            M = (Matrix.Translation(p + nrm * r * 0.25) @ q.to_matrix().to_4x4()
                 @ Matrix.Diagonal((r, r, r * 0.55, 1)))
            bmesh.ops.create_icosphere(bm, subdivisions=2, radius=1.0, matrix=M)
            n += 1
    ev.to_mesh_clear()
    me_b = bpy.data.meshes.new("hero_beads")
    bm.to_mesh(me_b)
    bm.free()
    for poly in me_b.polygons:
        poly.use_smooth = True
    me_b.materials.append(_water())
    ob = bpy.data.objects.new("hero_beads", me_b)
    ob.pass_index = 1
    col.objects.link(ob)
    rig.receivers(ch).objects.link(ob)   # flagged lights reach the drops too
    return n


# --------------------------------------------------------------- hair tips
def _wet_nodes(m, curves=False):
    """Insert (once) a tip mask that darkens the base colour and lowers the
    roughness toward the strand tips; amount = the "hero_wet" value node."""
    nt = m.node_tree
    if "hero_wet" in nt.nodes:
        return nt.nodes["hero_wet"]
    p = rig._principled(m)
    hair = None
    if p is None:   # strands: Principled Hair BSDF (melanin)
        hair = next((n for n in nt.nodes if n.bl_idname == "ShaderNodeBsdfHairPrincipled"), None)
        if hair is None:
            return None
    N, L = nt.nodes, nt.links
    amt = N.new("ShaderNodeValue")
    amt.name = amt.label = "hero_wet"
    amt.outputs[0].default_value = 0.0
    rng = N.new("ShaderNodeMapRange")
    rng.inputs["From Min"].default_value = 1.0 - TIP
    rng.inputs["From Max"].default_value = 1.0
    if curves:      # strands: Hair Info intercept, root 0 -> tip 1
        hi = N.new("ShaderNodeHairInfo")
        L.new(hi.outputs["Intercept"], rng.inputs["Value"])
    else:           # cards: UV0.v root 0 -> tip 1
        uv = N.new("ShaderNodeUVMap")
        sep = N.new("ShaderNodeSeparateXYZ")
        L.new(uv.outputs["UV"], sep.inputs[0])
        L.new(sep.outputs["Y"], rng.inputs["Value"])
    w = N.new("ShaderNodeMath")
    w.operation = "MULTIPLY"
    L.new(rng.outputs["Result"], w.inputs[0])
    L.new(amt.outputs[0], w.inputs[1])

    def scale(sock, lo):
        """sock *= mix(1, lo, w) (colour or float)."""
        f = N.new("ShaderNodeMapRange")
        f.inputs["To Min"].default_value = 1.0
        f.inputs["To Max"].default_value = lo
        L.new(w.outputs[0], f.inputs["Value"])
        if sock.type == "RGBA":
            mul = N.new("ShaderNodeMix")
            mul.data_type = "RGBA"
            mul.blend_type = "MULTIPLY"
            mul.inputs[0].default_value = 1.0
            if sock.is_linked:
                L.new(sock.links[0].from_socket, mul.inputs[6])
            else:
                mul.inputs[6].default_value = sock.default_value
            comb = N.new("ShaderNodeCombineXYZ")
            for k in range(3):
                L.new(f.outputs["Result"], comb.inputs[k])
            L.new(comb.outputs[0], mul.inputs[7])
            L.new(mul.outputs[2], sock)
        else:
            mul = N.new("ShaderNodeMath")
            mul.operation = "MULTIPLY"
            if sock.is_linked:
                L.new(sock.links[0].from_socket, mul.inputs[0])
            else:
                mul.inputs[0].default_value = sock.default_value
            L.new(f.outputs["Result"], mul.inputs[1])
            L.new(mul.outputs[0], sock)

    if hair is not None:
        scale(hair.inputs["Roughness"], 0.55)   # strands: the water film smooths the cuticle
        return amt
    scale(p.inputs["Base Color"], 0.55)   # wet hair is darker ...
    scale(p.inputs["Roughness"], 0.45)    # ... and glossier
    return amt


def hair_tips(ch, amount=1.0):
    """Set the wet-tip amount on every hair material (0 = the build's look)."""
    done = []
    for o in ch.objs:
        for s in getattr(o, "material_slots", []):
            m = s.material
            if not m or m.name not in HAIR_MATS or m.name in done or not m.use_nodes:
                continue
            node = (_wet_nodes(m, curves=o.type == "CURVES") if amount > 0
                    else m.node_tree.nodes.get("hero_wet"))
            if node is not None:
                node.outputs[0].default_value = amount
                done.append(m.name)
    return done


# -------------------------------------------------------------------- gaze
def _eye_objs(ch):
    """The eyeball mesh first, then the shells that turn with it (the hero
    cornea); the tear meniscus and caruncle stay with the lids."""
    eyes = [o for o in ch.objs if o.type == "MESH" and "eyes" in o.name.lower()]
    shells = [o for o in ch.objs if o.type == "MESH" and "cornea" in o.name.lower()]
    return eyes[:1] + shells


def gaze(ch, target, off_deg=0.0, limit=28.0):
    """Turn both eyes (eyeball + cornea, skinned to the head bone) toward
    `target` (world), `off_deg` to the character's left of it. Rotates the
    rest vertices of each eye about the eyeball's centre; restore() undoes
    it. The lids don't follow, so the turn is limited to `limit` degrees."""
    objs = [o for o in _eye_objs(ch) if not o.data.shape_keys   # keys would override the edit
            and any(m.type == "ARMATURE" for m in o.modifiers)]
    if not objs:
        return None
    restore(ch)
    eo = objs[0]
    head = ch._deform("head")
    h3i = head.to_3x3().inverted()
    mw0 = eo.matrix_world
    out = []
    rots = {}
    for side in (1, -1):
        pts = [mw0 @ v.co for v in eo.data.vertices if (mw0 @ v.co).x * side > 0]
        c_rest = sum(pts, Vector()) / len(pts)
        d = (Vector(target) - head @ c_rest).normalized()
        if off_deg:
            d = Matrix.Rotation(math.radians(off_deg), 3, "Z") @ d
        q = Vector((0, -1, 0)).rotation_difference((h3i @ d).normalized())
        ang = math.degrees(q.angle)
        if ang > limit:
            q = Quaternion(q.axis, math.radians(limit))
        rots[side] = (c_rest, q.to_matrix())
        out.append(round(min(ang, limit), 1))
    for o in objs:
        _EYES[o.name] = [v.co.copy() for v in o.data.vertices]
        mw, mwi = o.matrix_world, o.matrix_world.inverted()
        for v in o.data.vertices:
            p = mw @ v.co
            c, R = rots[1 if p.x > 0 else -1]
            v.co = mwi @ (c + R @ (p - c))
        o.data.update()
    return {"deg": out, "objects": [o.name for o in objs]}


def restore(ch):
    for name, cos in list(_EYES.items()):
        o = bpy.data.objects.get(name)
        if o is not None:
            for v, co in zip(o.data.vertices, cos):
                v.co = co
            o.data.update()
        del _EYES[name]
