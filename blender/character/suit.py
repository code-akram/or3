"""Suit: a black three-piece built parametrically on the body (bench/m1/suit.md).

add() fits the stock CC0 garments (the suits01 shell for its trousers, the
shoes placeholder) and keeps a copy of the unmasked body. post() works on the
staged export meshes, in rest pose:

    split the stock shell, keep the trousers, drop the rest
    jacket   suit_jacket: block, lapels, collar, vents, sleeves, pockets
    inner    suit_inner: waistcoat, shirt front + collar + cuffs, tie + knot
    buttons  low-poly discs (jacket front, cuffs, waistcoat)
    trousers stock shell tailored: break, taper, creases
    textures suit_textures: atlas UVs, baked-by-script normal maps, materials
    budgets, hide covered body polygons, measurements -> stats.json["suit"]

Options live in DEFAULTS and are overridden through the build config's
"suit" section, e.g. {"suit": {"jacket": {"vents": "centre"}}}.
"""

import bmesh
import bpy
from mathutils import Vector

from . import budgets, config
from . import suit_build as sb
from . import suit_inner, suit_jacket, suit_ops, suit_shoes, suit_textures

DEFAULTS = {
    "tailor": True,             # False: stock shell, as in spike 1
    "button_stance": 0.615,     # fastening button z / stature (look-spec: 0.61 +- 0.01)
    "jacket": {
        "hem_to_suprasternale": 0.50,
        "button_gap_m": 0.11,
        "columns": 72,
        "row_skirt_m": 0.025, "row_body_m": 0.02, "row_top_m": 0.012,
        "slice_band_m": 0.012,
        "canvas_limit_m": 0.02,
        "uv_circ_m": 1.08,
        # radial allowances over the body (metres)
        "ease": {"chest": 0.024, "back": 0.018, "side": 0.020,
                 "waist_front": 0.016, "waist_back": 0.013, "waist_side": 0.014,
                 "hip": 0.018, "flare": 0.010},
        "shoulder": {"over_body_m": 0.012, "back_neck_m": -0.036, "neck_point_drop_m": 0.012,
                     "slope_m": 0.030,
                     "neck_half_m": 0.072, "neck_ease_m": 0.016, "neck_curve_pow": 0.8,
                     "armpit_below_joint_m": 0.095, "bulge_pow": 0.7, "cap_below_joint_m": 0.02},
        "overlap_m": 0.02, "underlap_tuck_m": 0.003, "front_cut_m": 0.03,
        "quarter_cut_m": 0.025, "quarter_height_m": 0.12,
        "skirt_leg_weight": 0.5,
        "lapel": {"width_m": 0.080, "width_pow": 2.2, "swing_u": 0.10,
                  "gorge_below_neck_m": 0.032, "roll_m": 0.012, "edge_m": 0.003,
                  "tip_rise_m": 0.028},
        "collar": {"stand_front_m": 0.028, "stand_back_m": 0.032, "lean_in_m": 0.004,
                   "fall_front_m": 0.048, "fall_back_m": 0.044, "end_frac": 0.10,
                   "end_columns": 4, "gorge_seam_m": 0.034, "point_m": 0.036,
                   "point_angle_deg": -12},
        "vents": "double", "vent_height_m": 0.24, "vent_x_frac": 0.55,
        "vent_lift_m": 0.004, "vent_underlap_m": 0.035,
        "sleeve": {"columns": 28, "row_m": 0.016, "band_m": 0.012, "ease_m": 0.010,
                   "top_r_m": 0.066, "cuff_r_m": 0.046, "past_wrist_m": 0.005,
                   "rope_m": 0.0035, "head_rows": 7, "seam_out_m": 0.004, "elbow_blend_m": 0.04, "uv_circ_m": 0.36},
        "pockets": {"flap_x0_m": 0.07, "flap_w_m": 0.16, "flap_h_m": 0.06,
                    "flap_below_button_m": 0.075,
                    "welt": {"from_roll_m": 0.095, "w_m": 0.105, "h_m": 0.024,
                             "above_button_m": 0.235, "slant": 0.22}},
    },
    "waistcoat": {
        "offset_m": 0.008,
        "top_button_above_jacket_button_m": 0.13,
        "neck_point_x_m": 0.075,
        "cover_waistband_m": 0.025,
        "point_drop_m": 0.05,
        "back_panel_m": 0.12,
        "buttons": 5,
        "margin_m": 0.05,       # front panel reaches this far outside the jacket's V
        "columns": 48, "row_m": 0.015,
    },
    "shirt": {"offset_m": 0.005, "front_margin_m": 0.03,
              "collar": {"base_above_supra_m": 0.002, "back_rise_m": 0.038, "gap_m": 0.005,
                         "stand_front_m": 0.032, "stand_m": 0.038, "leaf_m": 0.016,
                         "point_m": 0.070, "spread_deg": 28, "columns": 64,
                         "gap_frac": 0.035, "point_frac": 0.085, "hidden_from_frac": 0.15},
              "placket_w_m": 0.035, "cuff_reveal_m": 0.013, "cuff_inside_m": 0.02},
    "tie": {"knot_w_m": 0.040, "knot_h_m": 0.046, "knot_d_m": 0.024, "knot_skew_m": 0.003,
            "knot_top_above_base_m": 0.030, "blade_top_w_m": 0.032,
            "blade_w_m": 0.078, "blade_full_at_m": 0.44, "dimple_m": 0.005},
    "trousers": {"back_hem_m": 0.035, "break_from_z": 0.45, "crease_depth_m": 0.0025,
                 "opening_half_m": 0.095, "taper_from_z": 0.50},
    "shoes": {
        "build": True,              # False: keep the stock shoes04 placeholder
        "rows": 26, "columns": 24, "band_m": 0.008, "leather_m": 0.004,
        "heel_ease_m": 0.010, "toe_ease_m": 0.026, "toe_box_m": 0.004,
        "topline_m": 0.064, "throat_y_m": 0.125,    # throat: this far from the toe tip
        "cap_m": 0.075, "quarter_m": 0.16,          # seam positions from the toe tip
        "welt_m": 0.005, "sole_m": 0.010, "heel_m": 0.026, "heel_len_m": 0.085,
        "laces": {"count": 3, "first_m": 0.165, "pitch_m": 0.018, "half_gap_cols": 1,
                  "eyelet_r_m": 0.0028, "radius_m": 0.0015},
    },
    "buttons": {"segments": 8, "jacket_r_m": 0.011, "jacket_height_m": 0.004,
                "cuff_r_m": 0.0075, "vest_r_m": 0.0065, "vest_height_m": 0.003},
    "materials": {
        # linear albedo, roughness, sheen (glTF: Sheen Tint is the sheen colour,
        # Sheen Weight is ignored, so the strength goes in the tint).
        "wool": [0.028, 0.70, 0.08],
        "shirt": [0.75, 0.55, 0.0],
        "silk": [0.02, 0.35, 0.15],
        "button": [0.015, 0.3, 0.0],
        "leather": [0.012, 0.28, 0.0],   # polished black calf
        "sole": [0.02, 0.65, 0.0],
    },
    "textures": {"enabled": True, "wool_px": 2048, "shirt_px": 1024, "tie_px": 512,
                 "shoe_px": 1024, "seed": 3, "slope": 1.0},
    "budgets": {"jacket": 14000, "tie": 900, "waistcoat": 3000, "shirt": 2200,
                "trousers": 4000, "shoes": 5000},
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
    shell_stem = b.cfg["suit"]["clothes"][0].rsplit(".", 1)[0]
    shell = next(x for x in b.meshes(shell_stem))
    global PART
    PART = shell.name.split(".", 1)[0] + ".suit_{}_export"
    shoes = next((x for x in b.meshes() if "shoes" in x.name), None)
    src_me, src_names = b.suit_src
    m = {"options": o}

    body = sb.Body(src_me, src_names, arm)
    stature = body.extent(body.bones, 2)[1]
    supra = body.joint("clavicle_l").z
    m["stature_m"], m["suprasternale_z"] = r(stature), r(supra)
    m["body_bideltoid_m"] = r(suit_jacket.body_bideltoid(body))

    parts = suit_ops.split_shell(b, shell, PART)
    trousers = parts["trousers"]
    for k in ("jacket", "shirt", "tie", "knot"):
        suit_ops.drop(b, parts[k])
    for x in parts["buttons"]:
        suit_ops.drop(b, x)
    waistband = max(v.co.z for v in trousers.data.vertices)
    m["waistband_top_z"] = r(waistband)
    m["waistband_to_stature"] = r(waistband / stature)
    z_b = o["button_stance"] * stature
    m["button_stance_to_stature"] = r(z_b / stature)

    mats = {k: suit_textures.material(f"suit_{k}", *v) for k, v in o["materials"].items()}

    G = sb.Garment(PART.format("jacket"), arm, body)
    jk, jm = suit_jacket.build(G, body, o["jacket"], stature, z_b, supra)
    jacket = G.finish(b, trousers, mats["wool"])
    jm["shoulder_over_body_m"] = r(2 * jk.half_sh - m["body_bideltoid_m"])
    m["jacket"] = jm

    inner = suit_inner.build(b, body, o, arm, jk, jacket, trousers, waistband, mats, PART)
    m.update(inner["measure"])
    vest, shirt, tie, buttons = inner["vest"], inner["shirt"], inner["tie"], inner["buttons"]

    m["trousers"], tmarks = suit_ops.tailor_trousers(trousers, o["trousers"])
    trousers.data.materials.clear()
    trousers.data.materials.append(mats["wool"])
    if o["shoes"]["build"]:
        if shoes is not None:
            suit_ops.drop(b, shoes)
        shoes, m["shoes"] = suit_shoes.build(b, body, o["shoes"], arm, trousers, mats, PART)
    body.free()
    bpy.data.meshes.remove(src_me)
    b.suit_src = None

    if o["textures"]["enabled"]:
        marks = dict(inner["marks"])
        marks[jacket.name] = G.marks
        marks[trousers.name] = tmarks
        if "shoes" in m:
            marks[shoes.name] = m["shoes"].pop("marks")
        m["textures"] = suit_textures.apply(o, {"jacket": jacket, "trousers": trousers,
                                                "waistcoat": vest, "shirt": shirt, "tie": tie,
                                                "buttons": buttons,
                                                "shoes": shoes if o["shoes"]["build"] else None},
                                            mats, marks)
    else:
        m.get("shoes", {}).pop("marks", None)
        suit_textures.strip_panel_attr([jacket, trousers, vest, shirt, tie, shoes])

    m["decimated"] = {}
    for key, obj in (("jacket", jacket), ("tie", tie), ("waistcoat", vest),
                     ("shirt", shirt), ("trousers", trousers), ("shoes", shoes)):
        lim = o["budgets"].get(key)
        if obj is not None and lim:
            before, after = budgets.decimate(obj, lim)
            m["decimated"][obj.name] = {"before": before, "after": after}

    garments = [x for x in (jacket, trousers, shirt, tie, vest, shoes) if x is not None]
    if o["hide_body"]:
        m["body_hide"] = hide_body(b, o, garments)
    m["tris"] = {x.name: budgets.tris(x) for x in b.meshes()}
    b.notes["suit"] = m


def r(x, n=4):
    return round(x, n)


# --- hidden-surface removal ----------------------------------------------------------------

def hide_body(b, o, occluders):
    """Delete body polygons no camera can see: a vertex is covered when every ray
    of a small cone around its normal hits a garment within hide_ray_m. Covered
    vertices within hide_margin_m of a visible one are kept (look-spec §4.3).
    The head is never touched (hair is not an occluder)."""
    import math
    body = max((x for x in b.meshes() if "body" in x.vertex_groups),
               key=lambda x: len(x.data.vertices))
    names = [g.name for g in body.vertex_groups]
    bones = set(b.armature().data.bones.keys())
    tree = sb.bvh_of(occluders)
    bm = suit_ops.to_bm(body)
    bm.normal_update()
    dl = bm.verts.layers.deform.verify()
    before = budgets.tris(body)
    visible = []
    covered = set()
    for v in bm.verts:
        if suit_ops.dominant(v, dl, names, bones) == "head":
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
    kd = sb.KDTree(len(visible))
    for i, v in enumerate(visible):
        kd.insert(v.co, i)
    kd.balance()
    drop = {v for v in covered if kd.find(v.co)[2] > o["hide_margin_m"]}
    gone = [f for f in bm.faces if all(v in drop for v in f.verts)]
    bmesh.ops.delete(bm, geom=gone, context="FACES")
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    suit_ops.write_bm(bm, body)
    return {"object": body.name, "tris_before": before, "tris_after": budgets.tris(body),
            "faces_deleted": len(gone)}
