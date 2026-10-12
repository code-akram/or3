"""Suit: the suits01 toigo shell tailored into a black three-piece (bench/m1/suit.md).

add() fits the stock CC0 garments and keeps a copy of the unmasked body (the
staged body has its covered polygons deleted; the waistcoat is built from its
torso). post() works on the staged export meshes, in rest pose:

    split the shell -> jacket, trousers, shirt, tie, buttons
    jacket: longer hem, vents | tie: longer blade | trousers: break, creases
    waistcoat from the body torso | shirt cuffs | low-poly buttons
    look-dev materials | per-part budgets | hide covered body polygons
    measurements against bench/m1/look-spec.md §4 -> stats.json["suit"]

Options live in DEFAULTS below and are overridden through the build config's
"suit" section, e.g. {"suit": {"vents": "centre"}}.
"""

import math

import bmesh
import bpy
from mathutils import Vector

from . import budgets, config
from . import suit_ops as ops

DEFAULTS = {
    "tailor": True,             # False: stock shell, as in spike 1
    "hem_to_suprasternale": 0.50,
    "stretch_from_z": 1.00,     # jacket hem stretch acts below this height
    "open_front_to_m": 1.40,    # the jacket V is re-cut from here down to the button
    "open_front_strip_m": 0.05,
    "open_front_blend_m": 0.15,  # best of 6 candidates (bench/m1/suit.md)
    "vents": "double",          # double | centre | none (user ruling 2026-10-12: double)
    "vent_height_m": 0.24,
    "vent_x_frac": 0.55,        # double vents: fraction of the hem half-width
    "tie_tip_above_waistband_m": 0.02,
    "trouser_back_hem_m": 0.035,
    "trouser_break_from_z": 0.45,
    "crease_depth_m": 0.0025,
    "waistcoat": {
        "offset_m": 0.007,
        "top_button_above_jacket_button_m": 0.14,  # V bottom; top button sits 1.2 cm lower
        "neck_point_x_m": 0.075,
        "cover_waistband_m": 0.025,   # side hem below the trouser waistband top
        "point_drop_m": 0.05,         # points fall this far below the side hem
        "back_panel_m": 0.12,         # lower back panel height above the back hem
        "buttons": 5,
    },
    "sleeve_end_from_wrist_m": 0.005,  # along the forearm, past the hand joint
    "shirt_clearance_m": 0.012,  # min gap from the shirt out to the jacket (6 mm let it show)
    "cuff_reveal_m": 0.013,
    "cuff_inside_m": 0.02,
    "buttons": {"segments": 8, "jacket_height_m": 0.004, "vest_radius_m": 0.006,
                "vest_height_m": 0.003},
    "materials": {
        # linear albedo, roughness, sheen (look-dev only, no textures). glTF export
        # writes Sheen Tint as sheenColorFactor and ignores the weight, so the
        # sheen strength is the tint.
        "wool": [0.03, 0.72, 0.06],
        "shirt": [0.75, 0.6, 0.0],
        "silk": [0.02, 0.4, 0.12],
        "button": [0.015, 0.3, 0.0],
    },
    "budgets": {"jacket": 9000, "tie": 700, "waistcoat": 2000, "shirt": 1500,
                "trousers": 3500, "shoes": 3000},
    "hide_body": True,
    "hide_margin_m": 0.03,
    "hide_ray_m": 0.06,
}

PART = "suit_{}"  # set per build to "<human>.suit_<part>_export", the staged naming


def opts(b):
    return config.merge(DEFAULTS, b.cfg["suit"])


def add(b):
    for fname in b.cfg["suit"]["clothes"]:
        b.mpfb.add_mhclo(b.basemesh, "clothes", fname, "Clothes")
    if opts(b)["tailor"]:
        b.suit_src = capture_body(b.basemesh)


def capture_body(ob):
    """The body with the clothes' delete masks muted (helpers stay hidden), as a
    standalone mesh with the targets applied and the skin weights kept."""
    muted = [m for m in ob.modifiers if m.type == "MASK" and m.name.startswith("Delete.")
             and m.show_viewport]
    for m in muted:
        m.show_viewport = False
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg), preserve_all_data_layers=True,
                                         depsgraph=dg)
    me.use_fake_user = True
    for m in muted:
        m.show_viewport = True
    return me, [g.name for g in ob.vertex_groups]


def post(b):
    o = opts(b)
    if not o["tailor"]:
        return
    arm = b.armature()
    bone = lambda n: arm.matrix_world @ arm.data.bones[n].head_local  # noqa: E731
    shell_stem = b.cfg["suit"]["clothes"][0].rsplit(".", 1)[0]
    shell = next(x for x in b.meshes(shell_stem))
    global PART
    PART = shell.name.split(".", 1)[0] + ".suit_{}_export"
    shoes = next((x for x in b.meshes() if "shoes" in x.name), None)
    src_me, src_names = b.suit_src
    m = {"options": o}

    # Body references from the unmasked body.
    sb = bmesh.new()
    sb.from_mesh(src_me)
    sdl = sb.verts.layers.deform.verify()
    body_g = src_names.index("body")
    body_vs = [v for v in sb.verts if v[sdl].get(body_g, 0) > 0]
    stature = max(v.co.z for v in body_vs)
    supra = bone("clavicle_l").z
    m["stature_m"], m["suprasternale_z"] = r(stature), r(supra)
    bones = set(arm.data.bones.keys())
    m["body_bideltoid_m"] = r(bideltoid(body_vs, sdl, src_names, bones, arm))
    sb.free()

    parts = split_shell(b, shell)
    jacket, trousers, shirt, tie, knot = (parts[k] for k in
                                          ("jacket", "trousers", "shirt", "tie", "knot"))
    b.export_objs.remove(knot)
    ops.join_into(tie, knot)
    old_buttons = parts["buttons"]
    waistband = max(v.co.z for v in trousers.data.vertices)
    m["waistband_top_z"] = r(waistband)
    m["waistband_to_stature"] = r(waistband / stature)
    button_info = []
    for btn in old_buttons:
        vs = [v.co for v in btn.data.vertices]
        c = sum(vs, Vector()) / len(vs)
        rad = max((v - c).length for v in vs)
        button_info.append((c, rad))
        b.export_objs.remove(btn)
        bpy.data.objects.remove(btn, do_unlink=True)
    button_info.sort(key=lambda t: -t[0].z)
    zb = button_info[0][0].z  # fastening (top) button
    m["button_stance_to_stature"] = r(zb / stature)

    m["jacket"] = tailor_jacket(jacket, o, supra, arm, button_info[0][0].z)
    m["tie"] = lengthen_tie(tie, o, waistband)
    m["trousers"] = tailor_trousers(trousers, o)
    m["shirt_pulled_in_verts"] = clear_under(shirt, jacket, o["shirt_clearance_m"])
    cuffs = shirt_cuffs(shirt, jacket, arm, o)
    m["cuffs"] = cuffs

    vest, vm = build_waistcoat(b, o, arm, src_me, src_names, jacket, [shirt, tie], zb, waistband)
    m["waistcoat"] = vm
    m["tie"]["deleted_below_vest_faces"] = trim_tie(tie, vm["v_bottom_z"] - 0.03)
    bpy.data.meshes.remove(src_me)
    b.suit_src = None

    btn = make_buttons(b, o, arm, jacket, vest, button_info, vm)
    apply_materials(o, jacket, trousers, vest, shirt, tie, btn)

    m["decimated"] = {}
    for key, obj in (("jacket", jacket), ("tie", tie), ("waistcoat", vest),
                     ("shirt", shirt), ("trousers", trousers), ("shoes", shoes)):
        lim = o["budgets"].get(key)
        if obj is not None and lim:
            before, after = budgets.decimate(obj, lim)
            m["decimated"][obj.name] = {"before": before, "after": after}

    if o["hide_body"]:
        m["body_hide"] = hide_body(b, o, [jacket, trousers, shirt, tie, vest] +
                                   ([shoes] if shoes else []))
    m.update(measure(arm, jacket, trousers, tie, vest, m))
    m["tris"] = {x.name: budgets.tris(x) for x in b.meshes()}
    b.notes["suit"] = m


def r(x, n=4):
    return round(x, n)


# --- split ---------------------------------------------------------------------------------

def split_shell(b, shell):
    bm = ops.to_bm(shell)
    comps = ops.components(bm)
    info = []
    for c in comps:
        ps = [bm.verts[i].co for i in c]
        xs, zs = [p.x for p in ps], [p.z for p in ps]
        info.append({"keep": c, "n": len(c), "zmin": min(zs), "zmax": max(zs),
                     "xspan": max(xs) - min(xs), "diag": (max(zs) - min(zs)) + max(xs) - min(xs)})
    bm.free()
    info.sort(key=lambda d: -d["n"])
    roles = {"jacket": info[0]}
    rest = info[1:]
    roles["trousers"] = min(rest, key=lambda d: d["zmin"])
    rest.remove(roles["trousers"])
    btns = [d for d in rest if d["diag"] < 0.08]
    rest = [d for d in rest if d not in btns]
    roles["shirt"] = max(rest, key=lambda d: d["xspan"])
    rest.remove(roles["shirt"])
    roles["tie"], roles["knot"] = sorted(rest, key=lambda d: d["zmin"])
    out = {}
    for role, d in roles.items():
        out[role] = ops.new_part(shell, d["keep"], PART.format(role))
    out["buttons"] = [ops.new_part(shell, d["keep"], PART.format(f"oldbutton{i}"))
                      for i, d in enumerate(btns)]
    b.export_objs.remove(shell)
    bpy.data.objects.remove(shell, do_unlink=True)
    b.export_objs += [out[k] for k in ("jacket", "trousers", "shirt", "tie", "knot")]
    b.export_objs += out["buttons"]
    return out


# --- jacket, tie, trousers -----------------------------------------------------------------

def torso_verts(bm, dl, names, xmax=0.30):
    return [v for v in bm.verts if abs(v.co.x) < xmax
            and ops.dominant(v, dl, names, ops.TORSO_BONES | {"thigh_l", "thigh_r"})]


def tailor_jacket(jacket, o, supra, arm, z_button):
    bm = ops.to_bm(jacket)
    dl = bm.verts.layers.deform.verify()
    names = [g.name for g in jacket.vertex_groups]
    hem0 = min(v.co.z for v in bm.verts)
    target = o["hem_to_suprasternale"] * supra
    body = torso_verts(bm, dl, names)
    ops.stretch_below(body, o["stretch_from_z"], hem0, target)
    hem = min(v.co.z for v in bm.verts)
    out = {"hem_before_z": r(hem0), "hem_z": r(hem), "hem_to_suprasternale": r(hem / supra)}
    out["front_opened_verts"] = ops.open_front(bm, z_button, o["open_front_to_m"],
                                               o["open_front_strip_m"], o["open_front_blend_m"])
    out["vents"] = cut_vents(bm, o, hem)
    out["sleeves"] = shorten_sleeves(bm, arm, o["sleeve_end_from_wrist_m"])
    ops.write_bm(bm, jacket)
    return out


def sleeve_end(bm, arm, side):
    sign = 1 if side == "l" else -1
    loops = ops.boundary_loops(bm, [v for v in bm.verts if v.co.x * sign > 0.35])
    if not loops:
        return None
    loop = max(loops, key=len)
    c = sum((v.co for v in loop), Vector()) / len(loop)
    h = arm.matrix_world @ arm.data.bones[f"hand_{side}"].head_local
    la = arm.matrix_world @ arm.data.bones[f"lowerarm_{side}"].head_local
    return loop, c, h, (h - la).normalized()


def shorten_sleeves(bm, arm, target, length=0.08):
    """Pull each sleeve end back along the forearm so it sits `target` past the
    hand joint; the shift fades out over `length` up the sleeve."""
    out = {}
    for side in ("l", "r"):
        se = sleeve_end(bm, arm, side)
        if se is None:
            continue
        _, c, h, a = se
        delta = (c - h).dot(a) - target
        sign = 1 if side == "l" else -1
        if delta > 0:
            for v in bm.verts:
                if v.co.x * sign < 0.3:
                    continue
                t = ((v.co - c).dot(a) + length) / length
                if t > 0:
                    t = min(t, 1.0)
                    v.co -= a * delta * t * t * (3 - 2 * t)
        out[side] = {"shortened_m": r(max(delta, 0.0))}
    return out


def cut_vents(bm, o, hem):
    mode = o["vents"]
    if mode == "none":
        return {}
    bm.verts.ensure_lookup_table()
    back = [v for v in bm.verts if v.co.y > 0.02 and v.co.z < 1.2
            and any(e.is_boundary for e in v.link_edges)]
    z_back = min(v.co.z for v in back)
    ring = [v for v in back if v.co.z < z_back + 0.02]
    half = max(abs(v.co.x) for v in ring)
    xs = [0.0] if mode == "centre" else [o["vent_x_frac"] * half, -o["vent_x_frac"] * half]
    top = hem + o["vent_height_m"]
    out = {}
    for x in xs:
        start = min(ring, key=lambda v: abs(v.co.x - x))
        edges = ops.walk_up(start, top, start.co.x)
        n = ops.split_slit(bm, edges, outward=(mode == "double"), depth_top=top)
        out[f"x={x:+.3f}"] = {"edges": n, "top_z": r(max(max(e.verts[0].co.z, e.verts[1].co.z)
                                                         for e in edges) if edges else hem)}
        bm.verts.ensure_lookup_table()
    return out


def lengthen_tie(tie, o, waistband):
    bm = ops.to_bm(tie)
    tip0 = min(v.co.z for v in bm.verts)
    blade_top = 1.50 if tip0 < 1.4 else tip0 + 0.1
    target = waistband + o["tie_tip_above_waistband_m"]
    ops.stretch_below([v for v in bm.verts if abs(v.co.x) < 0.06], blade_top, tip0, target)
    tip = min(v.co.z for v in bm.verts)
    ops.write_bm(bm, tie)
    return {"tip_before_z": r(tip0), "tip_z": r(tip), "tip_above_waistband_m": r(tip - waistband)}


def trim_tie(tie, z_cut):
    """Delete the blade hidden under the waistcoat (look-spec §4.3)."""
    bm = ops.to_bm(tie)
    gone = [f for f in bm.faces if max(v.co.z for v in f.verts) < z_cut]
    bmesh.ops.delete(bm, geom=gone, context="FACES")
    ops.write_bm(bm, tie)
    return len(gone)


def tailor_trousers(tr, o):
    bm = ops.to_bm(tr)
    zmin = min(v.co.z for v in bm.verts)
    out = {"hem_before_z": r(zmin)}
    for sign in (1, -1):
        hem = [v for v in bm.verts if v.co.x * sign > 0 and v.co.z < zmin + 0.04]
        y0, y1 = min(v.co.y for v in hem), max(v.co.y for v in hem)
        leg = [v for v in bm.verts if v.co.x * sign > 0]
        # Quarter break: the back of the hem drops to the heel counter, the front stays.
        ops.stretch_below(leg, o["trouser_break_from_z"], zmin, o["trouser_back_hem_m"],
                          weight=lambda v: min(1.0, max(0.0, (v.co.y - y0) / (y1 - y0))))
    out["back_hem_z"] = r(min(v.co.z for v in bm.verts))
    zlo = min(v.co.z for v in bm.verts)
    out["crease_edges"] = {}
    for sign in (1, -1):
        for front, zhi in ((True, 0.98), (False, 0.80)):
            n = ops.crease(bm, list(bm.verts), sign, front, zlo, zhi, o["crease_depth_m"])
            out["crease_edges"][f"{'L' if sign > 0 else 'R'}-{'front' if front else 'back'}"] = n
    for f in bm.faces:
        f.smooth = True
    ops.write_bm(bm, tr)
    return out


# --- shirt cuffs ---------------------------------------------------------------------------

def clear_under(inner, outer, gap):
    """Pull inner-layer vertices in along their normal wherever the outer layer
    is closer than `gap` (the shirt poked through the lapel undersides once the
    stock jacket texture no longer painted a shirt there)."""
    tree = ops.bvh([outer])
    bm = ops.to_bm(inner)
    bm.normal_update()
    moved = 0
    for v in bm.verts:
        n = v.normal
        hit = tree.ray_cast(v.co - n * 0.002, n, gap + 0.002)
        if hit[0] is not None:
            v.co -= n * (gap + 0.002 - hit[3])
            moved += 1
    ops.write_bm(bm, inner)
    return moved


def shirt_cuffs(shirt, jacket, arm, o):
    """A white cuff ring inside each jacket sleeve end, showing cuff_reveal_m
    past it (the suits01 shirt has no sleeves)."""
    jb = ops.to_bm(jacket)
    jdl = jb.verts.layers.deform.verify()
    jnames = [g.name for g in jacket.vertex_groups]
    kd = ops.kd_of(jb)
    sb = ops.to_bm(shirt)
    sdl = sb.verts.layers.deform.verify()
    sidx = {g.name: g.index for g in shirt.vertex_groups}
    out = {}
    for side in ("l", "r"):
        sign = 1 if side == "l" else -1
        arm_vs = [v for v in jb.verts if v.co.x * sign > 0.35]
        loops = ops.boundary_loops(jb, arm_vs)
        if not loops:
            continue
        loop = max(loops, key=len)
        pts = [v.co.copy() for v in loop]
        c = sum(pts, Vector()) / len(pts)
        h = arm.matrix_world @ arm.data.bones[f"hand_{side}"].head_local
        la = arm.matrix_world @ arm.data.bones[f"lowerarm_{side}"].head_local
        a = (h - la).normalized()
        ring = ops.ring_resample(pts, 16)
        rings = []
        for scale, along in ((0.82, -o["cuff_inside_m"]), (0.9, 0.0), (0.9, o["cuff_reveal_m"]),
                             (0.82, o["cuff_reveal_m"] - 0.002)):
            vs = []
            for p in ring:
                q = c + (p - c) * scale + a * along
                nv = sb.verts.new(q)
                for g, w in ops.nearest_weights(kd, jb, jdl, jnames, sidx, p).items():
                    nv[sdl][g] = w
                vs.append(nv)
            rings.append(vs)
        for r0, r1 in zip(rings, rings[1:]):
            for i in range(16):
                j = (i + 1) % 16
                sb.faces.new([r0[i], r0[j], r1[j], r1[i]]).smooth = True
        out[side] = {"sleeve_end_from_wrist_m": r((c - h).dot(a)), "loop_verts": len(loop),
                     "sleeve_radius_m": r(sum((p - c).length for p in pts) / len(pts))}
    jb.free()
    ops.write_bm(sb, shirt)
    return out


# --- waistcoat -----------------------------------------------------------------------------

def build_waistcoat(b, o, arm, src_me, names, jacket, inner, zb, waistband):
    w = o["waistcoat"]
    bm = bmesh.new()
    bm.from_mesh(src_me)
    bm.verts.ensure_lookup_table()
    dl = bm.verts.layers.deform.verify()
    bones = set(arm.data.bones.keys())
    body_g = names.index("body")
    z_v = zb + w["top_button_above_jacket_button_m"]
    neck = arm.matrix_world @ arm.data.bones["clavicle_l"].head_local
    x_n, z_n = w["neck_point_x_m"], neck.z + 0.02
    z_side = waistband - w["cover_waistband_m"]
    z_point = z_side - w["point_drop_m"]
    z_notch = z_side - 0.5 * w["point_drop_m"]
    back_hem = z_side
    back_top = back_hem + w["back_panel_m"]

    def hem(x):
        ax = abs(x)
        if ax < 0.045:
            return z_notch + (z_point - z_notch) * ax / 0.045
        return z_point + (z_side - z_point) * min(1.0, (ax - 0.045) / 0.08)

    def vhalf(z):
        return x_n * (z - z_v) / (z_n - z_v)

    def torso(v):
        return v[dl].get(body_g, 0) > 0 and ops.dominant(v, dl, names, bones) in ops.TORSO_BONES

    keep = set()
    for f in bm.faces:
        if not all(torso(v) for v in f.verts):
            continue
        c = f.calc_center_median()
        if c.y < 0.0:
            if c.z > hem(c.x) and c.z < z_n + 0.06 and not (c.z > z_v and abs(c.x) < vhalf(c.z)):
                keep.add(f)
        elif back_hem < c.z < back_top:
            keep.add(f)
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f not in keep], context="FACES")
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    bm.verts.ensure_lookup_table()

    # Snap the cut edges to the hem, V and back-panel lines.
    for v in bm.verts:
        if not any(e.is_boundary for e in v.link_edges):
            continue
        p = v.co
        if p.y < 0.0:
            if p.z < z_v - 0.05 and p.z < hem(p.x) + 0.03:
                p.z = hem(p.x)
            elif z_v - 0.01 < p.z < z_n and abs(p.x) < vhalf(p.z) + 0.03:
                p.x = math.copysign(max(vhalf(p.z), 0.0), p.x if p.x else 1.0)
        else:
            if p.z < back_hem + 0.03:
                p.z = back_hem
            elif p.z > back_top - 0.03:
                p.z = back_top
    bm.normal_update()

    # Offset off the body: clear of the shirt and tie, inside the jacket.
    inner_t, outer_t = ops.bvh(inner), ops.bvh([jacket])
    d = {}
    for v in bm.verts:
        n = v.normal
        need = w["offset_m"]
        hit = inner_t.ray_cast(v.co - n * 0.002, n, 0.05)
        if hit[0] is not None:
            need = max(need, hit[3] - 0.002 + 0.003)
        d[v] = need
    for _ in range(3):
        d = {v: max(d[v], sum(d[e.other_vert(v)] for e in v.link_edges) / max(len(v.link_edges), 1))
             for v in bm.verts}
    clamped = 0
    for v in bm.verts:
        n = v.normal
        hit = outer_t.ray_cast(v.co + n * 0.001, n, 0.2)
        if hit[0] is not None and d[v] > hit[3] - 0.004:
            d[v] = max(0.002, hit[3] - 0.004)
            clamped += 1
    for v in bm.verts:
        v.co += v.normal * d[v]
    for f in bm.faces:
        f.smooth = True

    me = bpy.data.meshes.new(PART.format("waistcoat"))
    bm.to_mesh(me)
    bm.free()
    vest = bpy.data.objects.new(PART.format("waistcoat"), me)
    for n in names:
        vest.vertex_groups.new(name=n)
    for g in [g for g in vest.vertex_groups if g.name not in bones]:
        vest.vertex_groups.remove(g)
    vest.parent = jacket.parent
    vest.matrix_parent_inverse = jacket.matrix_parent_inverse.copy()
    mod = vest.modifiers.new("Armature", "ARMATURE")
    mod.object = arm
    for c in jacket.users_collection:
        c.objects.link(vest)
    b.export_objs.append(vest)
    zs = [v.co.z for v in me.vertices]
    front_bottom = [v.co for v in me.vertices if v.co.y < 0 and v.co.z < z_v - 0.05]
    out = {"v_bottom_z": r(z_v), "neck_point_z": r(z_n), "side_hem_z": r(z_side),
           "point_z": r(z_point), "bottom_min_z": r(min(zs)),
           "bottom_below_waistband_m": r(waistband - z_side),
           "front_bottom_max_z": r(max(p.z for p in front_bottom) if front_bottom else 0),
           "jacket_clamped_verts": clamped, "verts": len(me.vertices)}
    out["_z"] = {"z_v": z_v, "notch": z_notch}
    return vest, out


# --- buttons -------------------------------------------------------------------------------

def make_buttons(b, o, arm, jacket, vest, jacket_buttons, vm):
    bo = o["buttons"]
    me = bpy.data.meshes.new(PART.format("buttons"))
    btn = bpy.data.objects.new(PART.format("buttons"), me)
    bone_names = list(arm.data.bones.keys())
    for n in bone_names:
        btn.vertex_groups.new(name=n)
    idx = {n: i for i, n in enumerate(bone_names)}
    bm = bmesh.new()
    dl = bm.verts.layers.deform.verify()

    def host_weights(host, co):
        hb = ops.to_bm(host)
        hdl = hb.verts.layers.deform.verify()
        w = ops.nearest_weights(ops.kd_of(hb), hb, hdl, [g.name for g in host.vertex_groups],
                                idx, co)
        hb.free()
        return w

    jt = ops.bvh([jacket])
    for c, rad in jacket_buttons:
        hit = jt.find_nearest(c)
        n = hit[1] if hit[0] is not None else Vector((0, -1, 0))
        if n.y > 0:
            n = -n
        ops.disc(bm, dl, hit[0] if hit[0] is not None else c, n, rad, bo["jacket_height_m"],
                 host_weights(jacket, c), bo["segments"])
    vt = ops.bvh([vest])
    z_top = vm["_z"]["z_v"] - 0.012
    z_bot = vm["_z"]["notch"] + 0.02
    nb = o["waistcoat"]["buttons"]
    placed = 0
    for i in range(nb):
        z = z_top + (z_bot - z_top) * i / max(nb - 1, 1)
        hit = vt.ray_cast(Vector((0.0, -1.0, z)), Vector((0.0, 1.0, 0.0)), 2.0)
        if hit[0] is None:
            continue
        n = hit[1] if hit[1].y < 0 else -hit[1]
        ops.disc(bm, dl, hit[0], n, bo["vest_radius_m"], bo["vest_height_m"],
                 host_weights(vest, hit[0]), bo["segments"])
        placed += 1
    bm.to_mesh(me)
    bm.free()
    btn.parent = jacket.parent
    btn.matrix_parent_inverse = jacket.matrix_parent_inverse.copy()
    mod = btn.modifiers.new("Armature", "ARMATURE")
    mod.object = arm
    for c in jacket.users_collection:
        c.objects.link(btn)
    b.export_objs.append(btn)
    vm["buttons_placed"] = placed
    vm.pop("_z", None)
    return btn


# --- materials -----------------------------------------------------------------------------

def material(name, albedo, rough, sheen):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = (albedo, albedo, albedo, 1.0)
    bsdf.inputs["Roughness"].default_value = rough
    if "Sheen Weight" in bsdf.inputs:
        bsdf.inputs["Sheen Weight"].default_value = 1.0 if sheen else 0.0
        bsdf.inputs["Sheen Tint"].default_value = (sheen, sheen, sheen, 1.0)
        bsdf.inputs["Sheen Roughness"].default_value = 0.5
    mat.diffuse_color = (albedo, albedo, albedo, 1.0)
    return mat


def apply_materials(o, jacket, trousers, vest, shirt, tie, btn):
    mats = {k: material(f"suit_{k}", *v) for k, v in o["materials"].items()}
    for obj, key in ((jacket, "wool"), (trousers, "wool"), (vest, "wool"), (shirt, "shirt"),
                     (tie, "silk"), (btn, "button")):
        obj.data.materials.clear()
        obj.data.materials.append(mats[key])
        for p in obj.data.polygons:
            p.material_index = 0


# --- hidden-surface removal ----------------------------------------------------------------

def hide_body(b, o, occluders):
    """Delete body polygons no camera can see: a vertex is covered when every ray
    of a small cone around its normal hits a garment within hide_ray_m. Covered
    vertices within hide_margin_m of a visible one are kept (look-spec §4.3).
    The head is never touched (hair is not an occluder)."""
    body = max((x for x in b.meshes() if "body" in x.vertex_groups),
               key=lambda x: len(x.data.vertices))
    names = [g.name for g in body.vertex_groups]
    bones = set(b.armature().data.bones.keys())
    tree = ops.bvh(occluders)
    bm = ops.to_bm(body)
    bm.normal_update()
    dl = bm.verts.layers.deform.verify()
    head = {"head"}
    before = budgets.tris(body)
    visible = []
    covered = set()
    for v in bm.verts:
        if ops.dominant(v, dl, names, bones) in head:
            visible.append(v)
            continue
        n = v.normal
        t = n.orthogonal().normalized()
        u = n.cross(t)
        dirs = [n] + [(n * math.cos(0.6) + (t * math.cos(a) + u * math.sin(a)) * math.sin(0.6))
                      for a in (0, math.pi / 2, math.pi, 3 * math.pi / 2)]
        if all(tree.ray_cast(v.co + n * 0.001, dd, o["hide_ray_m"])[0] is not None for dd in dirs):
            covered.add(v)
        else:
            visible.append(v)
    kd = ops.KDTree(len(visible))
    for i, v in enumerate(visible):
        kd.insert(v.co, i)
    kd.balance()
    drop = {v for v in covered if kd.find(v.co)[2] > o["hide_margin_m"]}
    gone = [f for f in bm.faces if all(v in drop for v in f.verts)]
    bmesh.ops.delete(bm, geom=gone, context="FACES")
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    ops.write_bm(bm, body)
    return {"object": body.name, "tris_before": before, "tris_after": budgets.tris(body),
            "faces_deleted": len(gone)}


# --- measurements (look-spec §4.1) ---------------------------------------------------------

def along(arm, p, bone):
    bb = arm.data.bones[bone]
    h, t = arm.matrix_world @ bb.head_local, arm.matrix_world @ bb.tail_local
    return (p - h).dot((t - h).normalized())


def bideltoid(verts, dl, names, bones, arm):
    shoulder = {"upperarm_l", "upperarm_r", "clavicle_l", "clavicle_r"}
    xs = [v.co.x for v in verts if ops.dominant(v, dl, names, bones) in shoulder
          and along(arm, v.co, "upperarm_l" if v.co.x > 0 else "upperarm_r") < 0.06]
    return max(xs) - min(xs)


def measure(arm, jacket, trousers, tie, vest, m):
    jb = ops.to_bm(jacket)
    jdl = jb.verts.layers.deform.verify()
    names = [g.name for g in jacket.vertex_groups]
    bones = set(arm.data.bones.keys())
    out = {}
    out["jacket_shoulder_width_m"] = r(bideltoid(list(jb.verts), jdl, names, bones, arm))
    out["shoulder_over_body_m"] = r(out["jacket_shoulder_width_m"] - m["body_bideltoid_m"])
    torso = torso_verts(jb, jdl, names, xmax=0.32)
    zb = m["button_stance_to_stature"] * m["stature_m"]

    def width(z0, z1):
        xs = [v.co.x for v in torso if z0 < v.co.z < z1]
        return max(xs) - min(xs) if xs else float("nan")

    spine = [v for v in jb.verts if abs(v.co.x) < 0.3
             and ops.dominant(v, jdl, names, bones) in ("spine_02", "spine_03")]
    zs = [1.26 + 0.02 * i for i in range(8)]
    chest = max(max(v.co.x for v in spine if z < v.co.z < z + 0.02)
                - min(v.co.x for v in spine if z < v.co.z < z + 0.02) for z in zs
                if any(z < v.co.z < z + 0.02 for v in spine))
    out["jacket_chest_width_m"] = r(chest)
    out["jacket_width_at_button_m"] = r(width(zb - 0.01, zb + 0.01))
    out["waist_suppression"] = r(out["jacket_width_at_button_m"] / chest)
    jb.free()
    return out
