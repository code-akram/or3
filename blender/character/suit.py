"""Suit: a black three-piece built parametrically on the body (bench/m1/suit.md).

add() fits the stock CC0 garments (the suits01 shell for its trousers, the
shoes placeholder) and keeps a copy of the unmasked body. post() works on the
staged export meshes, in rest pose:

    split the stock shell, drop it (its trousers only when trousers.build is false)
    jacket   suit_jacket: block, lapels, collar, vents, sleeves, pockets
    inner    suit_inner: waistcoat, shirt front + collar + cuffs, tie + knot
    buttons  low-poly discs (jacket front, cuffs, waistcoat)
    trousers suit_trousers: built on the body (flat front, slim straight leg,
             quarter break, creases); fallback: the stock shell tailored
    textures suit_textures: atlas UVs, baked-by-script normal maps, materials
    budgets, hide covered body polygons, measurements -> stats.json["suit"]

Options live in DEFAULTS and are overridden through the build config's
"suit" section, e.g. {"suit": {"jacket": {"vents": "centre"}}}.
"""

import os

import bmesh
import bpy
from mathutils import Vector

from . import budgets, config
from . import suit_build as sb
from . import (suit_drape, suit_folds, suit_hero, suit_inner, suit_jacket, suit_neck, suit_ops, suit_shoes,
               suit_textures, suit_trousers)

DEFAULTS = {
    "tailor": True,             # False: stock shell, as in spike 1
    "button_stance": 0.615,     # fastening button z / stature (look-spec: 0.61 +- 0.01)
    "jacket": {
        # hem: "seat" = just covering the seat, hem_below_seat_m under the
        # gluteal fold (suit_jacket.seat_fold; on this figure that also matches
        # the knuckle rule); "supra" = hem_to_suprasternale x suprasternale z
        # (the half neck-to-floor rule, which reads as a coat on long legs)
        "hem_mode": "seat", "hem_below_seat_m": 0.025,
        "hem_to_suprasternale": 0.50,
        "button_gap_m": 0.11,
        "columns": 72,
        "row_skirt_m": 0.018, "row_body_m": 0.02, "row_top_m": 0.012,
        "slice_band_m": 0.012,
        "canvas_limit_m": 0.014,
        "uv_circ_m": 1.08,
        # radial allowances over the body (metres)
        "ease": {"chest": 0.024, "back": 0.014, "side": 0.020,
                 "waist_front": 0.016, "waist_back": 0.013, "waist_side": 0.014,
                 "hip": 0.018, "flare": 0.005},
        "shoulder": {"over_body_m": 0.012, "back_neck_m": -0.022, "neck_point_drop_m": 0.012,
                     "depth_top": 0.78, "clear_m": 0.007, "under_cap_m": 0.004, "yoke_rows": 4, "scye_pow": 1.0,
                     "neck_half_m": 0.072, "neck_ease_m": 0.016, "neck_curve_pow": 0.8,
                     "neck_clear_m": 0.005, "neck_band_lo_m": 0.0, "neck_band_hi_m": 0.006, "neck_lift_clear_m": 0.005, "neck_blend_frac": 0.12, "seam_below_band_m": 0.010, "gorge_cols": 6, "band_clear_m": 0.004,
                     "armpit_below_joint_m": 0.115, "bulge_pow": 0.7, "cap_below_joint_m": 0.02,
                     # natural shoulder: the point 1.2 cm past the shoulder's edge
                     # (where the top line turns down steeper than 40 deg), at
                     # the body's height there + clear_m, the line straight from
                     # the neck (lifted over the trapezius); the deltoid is the
                     # sleeve head's. "deltoid" put the point past the A-pose
                     # deltoids, 3.5 cm further out and square (football padding)
                     "point_from": "acromion", "acromion_deg": 40, "point_probe_m": [0.012, 0.006, 0.0],
                     "slope_ease": "linear", "clear_above_point_m": 0.02},
        "overlap_m": 0.02, "underlap_tuck_m": 0.003, "front_cut_m": 0.03,
        # front dart (suit_jacket.front_dart): the fronts bridge the body's
        # waist dip round the button (it creased across at the button) and
        # the dart line is marked from the flap pocket to under the chest
        "front_dart": {"enabled": True, "below_button_m": 0.04, "above_button_m": 0.10, "max_m": 0.008,
                       "smooth": 2, "mark": True, "x_m": 0.10, "mark_above_button_m": 0.15},
        "quarter_cut_m": 0.035, "quarter_height_m": 0.10,
        "skirt_leg_weight": {"front": 0.85, "side": 0.5, "back": 0.3},   # leg share at the hem, by side
        # lapel: gorge_below_neck_m places the top ring at the front, the
        # gorge seam sits gorge_drop_m lower on the chest (the collar's front
        # end lies on the roll line between them); roll 16 mm, a rounded edge
        # edge_m thick, the edge stitch stitch_in_m in from it. A dropped
        # gorge (0.045) stood the collar ends up beside the neck as straps;
        # with the natural shoulder the undropped gorge has no lapel wings
        # (the wings came from the old square shoulder line)
        "lapel": {"width_m": 0.080, "width_pow": 2.2, "swing_u": 0.10,
                  "gorge_below_neck_m": 0.032, "gorge_drop_m": 0.0, "stitch_in_m": 0.006,
                  "roll_m": 0.016, "edge_m": 0.0035,
                  "tip_rise_m": 0.010, "rise_h_m": 0.05, "tip_lift_m": 0.0, "min_row_m": 0.006},
        # collar (suit_neck): the fold sits reveal_* under the shirt band's top;
        # the front end lies on the lapel's top edge to the notch, then turns
        # up at notch_deg to the collar point; in front of the neck point
        # (drop_frac of the way round) the fold lowers by drop_m so the ends
        # lie down onto the lapel; end_relax smooths the ends' fall.
        # The outer edge: faired round the collar (edge_fair_passes), a
        # rounded edge 2 * edge_r_m thick, the collar point's edge too; the
        # fold faired (fold_fair_passes); the end path held as built
        # (hold_end); the fall at the side 3.5 cm (4.2 stood out at the side
        # of the neck as a wing)
        "collar": {"reveal_back_m": 0.014, "reveal_side_m": 0.014, "stand_min_m": 0.006,
                   "shirt_clear_m": 0.003, "body_clear_m": 0.012, "thickness_m": 0.004,
                   "fall_back_m": 0.040, "fall_side_m": 0.035, "seam_cover_m": 0.008,
                   "rest_m": 0.0035, "fall_rows": 6, "end_frac": 0.09, "drop_frac": 0.3, "drop_m": 0.025, "end_relax": 2,
                   "gorge_seam_m": 0.030, "point_m": 0.028, "notch_deg": 30, "end_lift_m": 0.0015,
                   "edge_fair_passes": 20, "edge_r_m": 0.00125, "under_m": 0.004, "hold_end": True,
                   "fold_fair_passes": 6},
        "vents": "double", "vent_height_m": 0.20, "vent_x_frac": 0.55,
        "vent_lift_m": 0.004, "vent_underlap_m": 0.035,
        # sleeve: tapers from the bicep (top_r, at the armpit) to the cuff,
        # never closer than ease_m to the arm (0.066 / 0.046 / 0.010 read as
        # thick tubes: 12 cm over a 30 cm bicep); rows 1.1 cm apart carry the
        # modelled crook folds (suit_folds, 5 cm wavelength; 1.6 cm aliased them)
        "sleeve": {"columns": 28, "row_m": 0.011, "band_m": 0.012, "ease_m": 0.008,
                   "top_r_m": 0.058, "cuff_r_m": 0.044, "past_wrist_m": 0.005,
                   "rope_m": 0.006, "head_rows": 7, "seam_out_m": 0.0025, "scye_half_w_m": 0.070,
                   "elbow_blend_m": 0.04, "uv_circ_m": 0.36},
        "pockets": {"flap_x0_m": 0.07, "flap_w_m": 0.16, "flap_h_m": 0.06,
                    "flap_below_button_m": 0.10,
                    "welt": {"from_roll_m": 0.095, "w_m": 0.105, "h_m": 0.024,
                             "above_button_m": 0.235, "slant": 0.22}},
    },
    "waistcoat": {
        "offset_m": 0.008,
        # the V's bottom: halfway up the jacket's V, so the closed front with
        # 2-3 buttons shows above the jacket's button and the edges inside
        # the lapels (0.13: a sliver, black on black)
        "top_button_above_jacket_button_m": 0.17,
        # the V's top half width: narrower than the jacket's opening (0.072),
        # so a band of waistcoat shows between the lapel and the shirt up to
        # the collar (0.075 hid both edges under the lapels)
        "neck_point_x_m": 0.05,
        "cover_waistband_m": 0.025,
        "point_drop_m": 0.05,
        "back_panel_m": 0.12,
        "buttons": 5,
        "margin_m": 0.05,       # front panel reaches this far outside the jacket's V
        "columns": 48, "row_m": 0.015,
        # the V's edge: a pressed, rounded edge edge_m thick (a half round),
        # the front flat to edge_press_m from it, so a thin highlight line
        # runs down the V in the lapels' shadow (the cloth is not brightened)
        "edge_m": 0.0025, "edge_press_m": 0.002,
    },
    "shirt": {"offset_m": 0.005, "front_margin_m": 0.03,
              # collar (suit_neck): a band closed at the front, a fall over it with
              # two points on the chest; lead_deg is each leading edge's angle
              # from vertical (a moderate spread), point_m its length
              "collar": {"base_above_supra_m": 0.015, "base_flare_m": 0.012, "base_win_m": 0.001, "base_rise_pow": 0.7, "gap_m": 0.005,
                         "stand_front_m": 0.034, "stand_m": 0.040, "columns": 64,
                         "lead_half_gap_m": 0.016, "lead_deg": 38, "point_m": 0.075,
                         "point_cols_frac": 0.13, "fall_rows": 6, "fall_off_m": 0.003,
                         "flare": 0.35, "body_clear_m": 0.008, "overhang_m": 0.0,
                         "closure_overlap_rad": 0.06, "ring_columns": 20, "ring_open_rad": 0.30, "ring_to_deg": 115, "ring_drop_m": 0.012,
                         "ring_steps_m": [0.004, 0.009, 0.016, 0.026, 0.040], "ring_off_m": 0.0045},
              "placket_w_m": 0.035, "cuff_reveal_m": 0.013, "cuff_inside_m": 0.02,
              "front_into_band_m": 0.003, "band_inset_m": 0.002, "yoke": False},
    # four-in-hand (suit_neck.build_knot): width at its widest, height top to
    # the blade, depth off the band; taper = how much narrower the bottom is
    "tie": {"knot_w_m": 0.036, "knot_h_m": 0.046, "knot_d_m": 0.015, "knot_skew_m": 0.003,
            "knot_top_above_band_m": 0.002, "knot_taper": 0.42, "knot_full": 0.10,
            "knot_wrap_m": 0.0015, "blade_top_w_m": 0.021,
            "blade_w_m": 0.078, "blade_full_at_m": 0.44, "dimple_m": 0.005},
    # trousers (suit_trousers): built on the body; build false = the stock
    # suits01 shell tailored (suit_ops.tailor_trousers: back_hem_m, the last four keys)
    "trousers": {"build": True,
                 "waist_to_stature": 0.627,   # waistband top (natural rise, under the waistcoat)
                 "waistband_m": 0.035, "crotch_drop_m": 0.02, "canvas_limit_m": 0.02,
                 # radial allowances over the body (metres)
                 "ease": {"waist": 0.004, "front": 0.004, "hip": 0.0045, "seat": 0.0065,
                          "thigh_front": 0.008, "thigh_back": 0.012},
                 # the cut: flat widths (half the leg's circumference); thigh_cut
                 # scales the eased thigh where the cut starts (the body governs there)
                 "knee_flat_m": 0.21, "opening_flat_m": 0.19, "thigh_cut": 0.9,
                 "inner_gap_m": 0.0015, "crotch_close": 0.5, "seat_last_above_m": 0.03,
                 # knee rows 1.2 cm: the modelled folds at the back of the knee (suit_folds)
                 "row_seat_m": 0.022, "row_knee_m": 0.012, "row_leg_m": 0.04, "row_break_m": 0.02,
                 "break_zone_m": 0.20, "bridge_iters": 1,
                 # quarter break: back hem at the heel counter, front on the vamp
                 "back_hem_m": 0.035, "hem_slant_m": 0.02, "hem_slant_max_m": 0.08, "hem_curve": 2.5,
                 "vamp_rest_m": 0.0015, "slant_fade_m": 0.15, "heel_clear_m": 0.004,
                 "break_m": 0.004, "break_h_m": 0.03, "shoe_clear_m": 0.003,
                 "crease_m": 0.0015, "back_crease_from_m": 0.80,
                 "tuck_gap_m": 0.003, "tuck_body_min_m": 0.004,
                 "fly_w_m": 0.035, "fly_end_above_crotch_m": 0.06,
                 "pocket_drop_m": 0.17, "pocket_in_m": 0.04,
                 "back_pocket_below_m": 0.06, "back_pocket_w_m": 0.13,
                 # the stock shell's tailoring (build: false)
                 "break_from_z": 0.45, "crease_depth_m": 0.0025,
                 "opening_half_m": 0.095, "taper_from_z": 0.50},
    "shoes": {
        # black calf cap-toe derbies on a parametric last (suit_shoes.py)
        "build": True,              # False: keep the stock shoes04 placeholder
        "rows": 27, "half_columns": 9,
        "leather_m": 0.003, "width_ease_m": 0.003, "top_ease_m": 0.004, "max_top_m": 0.12,
        "smooth_m": 0.012,          # the last is the foot envelope smoothed along the foot
        "heel_ease_m": 0.008, "toe_ease_m": 0.028, "heel_r_m": 0.042, "heel_p": 2.0,
        # toe outline: superellipse exponents (2 round, higher squarer), medial straighter
        "toe_p_lat": 1.8, "toe_p_med": 2.3, "toe_shift_m": 0.006,
        "section_p": 2.6, "section_taper": 0.22, "ridge_shift_m": 0.004,
        "toe_box_h_m": 0.030, "nose_p": 2.4, "toe_spring_m": 0.009,
        "vamp_soft_m": 0.015,       # the vamp line is the convex envelope of the foot, softened
        "seat_m": 0.014, "waist_start_m": 0.015, "heel_curve_m": 0.008,
        "cap_m": 0.072, "cap_step_m": 0.0007,       # cap seam from the toe tip; cap leather step
        "throat_m": 0.150, "open_m": 0.212,         # lacing throat / ankle opening front, from the toe tip
        "tongue_row_m": 0.004,      # a full row this far ahead of the opening rounds the tongue top
        # topline: just under the ridge at the opening's front (the tongue top), then above
        # the foot's sole under the ankle bones and at the back
        "topline": {"front_drop_m": 0.003, "side_lat_m": 0.050, "side_med_m": 0.055, "back_m": 0.070,
                    "dip_at": 0.45},
        "lip_m": 0.0025,
        "backstay_m": 0.009, "backstay_lift_m": 0.0006, "counter_m": 0.075,
        # flex creases behind the cap: distance from the cap seam (main ones first, then fine)
        "creases_m": [0.013, 0.022, 0.009, 0.017, 0.027], "creases_main": 2,
        "crease_span_m": 0.042, "crease_depth_m": 0.00045, "crease_w_m": 0.0014, "crease_tilt": 0.12,
        "welt_m": 0.0045, "welt_heel_m": 0.002, "welt_h_m": 0.0035, "sole_m": 0.0065,
        "heel_len_m": 0.078, "toplift_m": 0.005,
        "facing": {"rows": 7, "width_m": 0.026, "gap_bottom_m": 0.004, "gap_top_m": 0.008,
                   "lift_m": 0.0011, "edge_lift_m": 0.0003, "past_top_m": 0.012},
        "laces": {"count": 3, "first_m": 0.165, "pitch_m": 0.018, "edge_in_m": 0.0055,
                  "eyelet_r_m": 0.0024, "radius_m": 0.0011, "sides": 5,
                  "bow": {"behind_m": 0.007, "knot_r_m": 0.0022, "knot_w_m": 0.007, "loop_pts": 11,
                          "loop_len_m": 0.026, "loop_w_m": 0.013, "loop_fwd_m": 0.006,
                          "tail_pts": 4, "tail_side_m": 0.022, "tail_fwd_m": 0.016}},
        # leather surfaces (suit_leather.py): linear albedo, roughness, clear coat per region
        "surface": {"albedo": {"upper": 0.012, "cap": 0.011, "facing": 0.012, "lip": 0.010,
                               "lace": 0.008, "sole": 0.009, "sole_m": 0.009,
                               "bottom": 0.030, "heel": 0.009, "toplift": 0.016},
                    "rough": {"upper": 0.28, "cap": 0.18, "facing": 0.27, "lip": 0.45, "lace": 0.42,
                              "sole": 0.30, "sole_m": 0.30, "bottom": 0.72,
                              "heel": 0.34, "toplift": 0.7},
                    "coat": {"upper": 0.45, "cap": 0.9, "facing": 0.45, "lip": 0.1, "lace": 0.15},
                    "coat_rough": 0.08, "cap_polish": 0.05, "crease_rough": 0.08, "crease_albedo": 1.35,
                    "paint_r": 2, "paint_amp": 0.14, "seed": 5},
    },
    "buttons": {"segments": 16, "jacket_r_m": 0.011, "jacket_height_m": 0.004,   # rounded edge, rim, dish
                "cuff_r_m": 0.0075, "vest_r_m": 0.0065, "vest_height_m": 0.003},
    "materials": {
        # suit_textures.material(): albedo (linear, grey or rgb), rough, sheen
        # (strength; the glTF sheen colour is sheen x sheen_tint), sheen_rough,
        # spec (Specular IOR Level: 0.5 = F0 0.04), coat, coat_rough, aniso, sss.
        # Wool: blue-black (reads black, not brown, under the 3000 K key: at
        # direction's 0.025 grey the key lifted it to dark brown), low
        # specular so the broad lobe does not grey it, a cool fuzz lobe at
        # grazing angles (sheen 0.35, roughness 0.4, the tint pulls the amber
        # out of the rim); roughness and albedo also vary per pixel (surface).
        "wool": {"albedo": [0.013, 0.014, 0.019], "rough": 0.68, "sheen": 0.35, "sheen_rough": 0.4,
                 "sheen_tint": [0.72, 0.8, 1.0], "spec": 0.15},
        # waistcoat: a finer, harder-finished worsted than the jacket, so it
        # reads inside the jacket's V (black on black otherwise): smoother,
        # a tighter and brighter sheen, a little more specular
        "vest": {"albedo": [0.015, 0.016, 0.021], "rough": 0.52, "sheen": 0.55, "sheen_rough": 0.28,
                 "sheen_tint": [0.75, 0.82, 1.0], "spec": 0.3},
        "shirt": {"albedo": 0.72, "rough": 0.5, "sheen": 0.2, "sheen_rough": 0.5, "spec": 0.4},
        "silk": {"albedo": 0.015, "rough": 0.45, "sheen": 0.15, "sheen_rough": 0.35, "spec": 0.45,
                 "aniso": 0.3},
        "button": {"albedo": 0.012, "rough": 0.25, "spec": 0.5, "coat": 0.4, "coat_rough": 0.12},
        "leather": [0.012, 0.28, 0.0],   # polished black calf
        "sole": [0.012, 0.45, 0.0],     # (maps and coat: shoes.surface)
    },
    # per-pixel wool surface (suit_textures.surface_maps): fibre noise in
    # roughness and albedo, cavity and fold occlusion, Kuwahara r (painterly
    # albedo, direction.md §4), roughness offsets per "<part>:<panel tag>"
    # (rough_noise 0.06 read as stains on the lapel and gorge close-ups)
    "surface": {"seed": 5, "rough_noise": 0.03, "albedo_noise": 0.008, "cavity": 0.35,
                "fold_ao": 0.55, "ao_in_albedo": 0.35, "kuwahara": 1,
                "panel_rough": {"suit_jacket:2": -0.10, "suit_jacket:3": -0.05}},
    "textures": {"enabled": True, "wool_px": 2048, "vest_px": 1024, "shirt_px": 1024, "tie_px": 512,
                 "shoe_px": 1024, "seed": 3, "slope": 1.0},
    # jacket and trousers raised (14000 / 4000) for the denser sleeve and knee rows
    "budgets": {"jacket": 16000, "tie": 900, "waistcoat": 3000, "shirt": 2200,
                "trousers": 5000, "shoes": 5000},
    "hide_body": True,
    "hide_margin_m": 0.03,
    "hide_ray_m": 0.06,
    # the armpit patch that was kept (and poked 45 mm through the jacket in
    # arm_raise) goes: under the upper arm, clavicle and torso, which the
    # jacket closes round, a cone ray may cross the hollow under the arm
    # (8-15 cm) before it meets the jacket; and a ray that meets the body
    # itself before any garment (the inner arm facing the torso) counts as
    # blocked when, carried on through the body, it ends on a garment within
    # hide_self_m rather than leaving the suit
    "hide_enclosed": {"bones": ["upperarm", "clavicle", "spine"], "m": 0.20},
    "hide_self_m": 1.5,
}

PART = "suit_{}"  # set per build to "<human>.suit_<part>_export", the staged naming


def opts(b):
    return config.merge(DEFAULTS, b.cfg["suit"])


def hero(b):
    """Hero-only material detail (suit_hero.py), after the GLB export: the
    saved .blend renders it in Cycles, the game asset never sees it."""
    o = opts(b)
    if not o.get("tailor", True):
        return
    H = config.merge(suit_hero.DEFAULTS, o.get("hero") or {})
    b.notes["suit_hero"] = suit_hero.apply(b, H)


def add(b):
    for fname in b.cfg["suit"]["clothes"]:
        b.mpfb.add_mhclo(b.basemesh, "clothes", fname, "Clothes")
    if opts(b)["tailor"]:
        b.suit_src = capture_body(b.basemesh)
        # the shell's delete mask was cut for the stock collar and cuffs (it
        # removed the neck up to the stock collar's top, a see-through sliver
        # above our shirt band from the side); the built garments decide what
        # the body hides (hide_body). The shoes' mask stays.
        b.suit_masks_dropped = []
        for m in list(b.basemesh.modifiers):
            if m.type == "MASK" and m.name.startswith("Delete.") and "shoe" not in m.name.lower():
                b.suit_masks_dropped.append(m.name)
                b.basemesh.modifiers.remove(m)


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
    T = o["trousers"]
    # the stock trousers stay as the placement reference (parent, collections)
    # until the built ones exist; renamed so the built ones get the part name
    trousers = stock = parts["trousers"]
    if T["build"]:
        stock.name = stock.data.name = PART.format("stocktrousers")
    for k in ("jacket", "shirt", "tie", "knot"):
        suit_ops.drop(b, parts[k])
    for x in parts["buttons"]:
        suit_ops.drop(b, x)
    if T["build"]:
        waistband = suit_trousers.waistband_z(stature, T)
    else:
        waistband = max(v.co.z for v in trousers.data.vertices)
    m["waistband_top_z"] = r(waistband)
    m["waistband_to_stature"] = r(waistband / stature)
    z_b = o["button_stance"] * stature
    m["button_stance_to_stature"] = r(z_b / stature)

    mats = {k: (suit_textures.material(f"suit_{k}", **v) if isinstance(v, dict)
                else suit_textures.material(f"suit_{k}", *v)) for k, v in o["materials"].items()}

    neck = suit_neck.NeckFrame(body, supra, o["shirt"]["collar"])
    G = sb.Garment(PART.format("jacket"), arm, body)
    jk, jm = suit_jacket.build(G, body, o["jacket"], stature, z_b, supra, neck)
    jacket = G.finish(b, trousers, mats["wool"])
    jm["finish"] = G.stats
    jm["shoulder_over_body_m"] = r(2 * jk.half_sh - m["body_bideltoid_m"])
    m["jacket"] = jm

    inner = suit_inner.build(b, body, o, arm, jk, jacket, trousers, waistband, mats, PART, neck)
    m.update(inner["measure"])
    vest, shirt, tie, buttons = inner["vest"], inner["shirt"], inner["tie"], inner["buttons"]

    if o["shoes"]["build"]:   # before the trousers: the hem rests on them
        if shoes is not None:
            suit_ops.drop(b, shoes)
        shoes, m["shoes"] = suit_shoes.build(b, body, o["shoes"], arm, stock, mats, PART)
    if T["build"]:
        outer = [(jacket, jk.z_h), (vest, min(v.co.z for v in vest.data.vertices))]
        trousers, m["trousers"], tmarks = suit_trousers.build(b, body, T, arm, stock, mats, PART,
                                                              stature, shoes=shoes, outer=outer)
        suit_ops.drop(b, stock)
    else:
        m["trousers"], tmarks = suit_ops.tailor_trousers(trousers, T)
        trousers.data.materials.clear()
        trousers.data.materials.append(mats["wool"])
    body.free()
    bpy.data.meshes.remove(src_me)
    b.suit_src = None

    # cloth-sim fold detail (suit_drape): jacket and trousers on the full body
    folds = {}
    D = config.merge(suit_drape.DEFAULTS, o.get("drape") or {})
    if D["enabled"] and o["textures"]["enabled"]:
        body_ob = max((x for x in b.meshes() if "body" in x.vertex_groups),
                      key=lambda x: len(x.data.vertices))
        garments = {"jacket": (jacket, jacket_pins(jk, arm)),
                    "trousers": (trousers, trouser_pins(arm))}
        cols = [shoes] if shoes is not None else []
        y_b = _front_y(jacket, jk.z_b)
        extra = {"button": [(Vector((0.0, y_b, jk.z_b)), Vector((0, -1, 0)))]}
        fobs, m["drape"] = suit_drape.run(b, D, garments, body_ob, cols, extra)
        folds = {f.garment.name: f for f in fobs.values()}

    # modelled folds in the geometry (suit_folds), after the drape so the sim
    # sees the clean surface: the elbow crook and the back of the knee
    Fo = config.merge(suit_folds.DEFAULTS, o.get("folds") or {})
    if Fo["enabled"]:
        import numpy as np
        TJ = suit_jacket.TAG
        body_f = max((x for x in b.meshes() if "body" in x.vertex_groups), key=lambda x: len(x.data.vertices))
        m["folds"] = suit_folds.apply(Fo, arm, body_f, [
            (jacket, "elbow", lambda co, tag: (np.isin(tag, [TJ["sleeve_l"], TJ["sleeve_r"]]) if tag is not None
                                               else np.zeros(len(co), bool))),
            (trousers, "knee_back", lambda co, tag: np.ones(len(co), bool))])

    debug_tags = None
    if os.environ.get("SUIT_DEBUG_TAGS"):   # diagnosis: colour the jacket's panels
        a = jacket.data.attributes.get("panel")
        debug_tags = [a.data[i].value for i in range(len(jacket.data.polygons))] if a else None
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
                                            mats, marks, folds)
    for f in folds.values():
        f.free()
    else:
        m.get("shoes", {}).pop("marks", None)
        suit_textures.strip_panel_attr([jacket, trousers, vest, shirt, tie, shoes])

    if debug_tags:
        cols = {2: (0.8, 0.1, 0.1), 3: (0.1, 0.7, 0.1), 1: (0.1, 0.2, 0.8)}
        slots = {}
        for t, c in cols.items():
            mt = suit_textures.material(f"debug_tag_{t}", c[0], 0.6, 0.0)
            next(n for n in mt.node_tree.nodes if n.type == "BSDF_PRINCIPLED").inputs[0].default_value = c + (1.0,)
            jacket.data.materials.append(mt)
            slots[t] = len(jacket.data.materials) - 1
        for p, t in zip(jacket.data.polygons, debug_tags):
            if t in slots:
                p.material_index = slots[t]
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
        m["body_hide"]["stock_masks_dropped"] = getattr(b, "suit_masks_dropped", [])
    m["tris"] = {x.name: budgets.tris(x) for x in b.meshes()}
    b.notes["suit"] = m


def r(x, n=4):
    return round(x, n)


# --- drape pins (suit_drape) ----------------------------------------------------------------

def _smooth(t):
    import numpy as np
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3 - 2 * t)


def _front_y(ob, z):
    hit = sb.bvh_of([ob]).ray_cast(Vector((0.0, -1.0, z)), Vector((0, 1, 0)), 2.0)
    return hit[0].y if hit[0] is not None else -0.15


def jacket_pins(jk, arm):
    """Pin weights for the jacket drape: the tailored, canvassed zones follow
    the skin (collar, lapels, pockets, the chest above the button, the back
    above the shoulder blades, the sleeve head, the buttoned front); the
    sleeves, the waist, the lower back and the skirt hang free. The cuff is
    lightly pinned so it stays at the wrist while the elbow moves. Shrink: a
    waist band at the fastened button (the X pull lines)."""
    import numpy as np
    T = suit_jacket.TAG
    J = lambda n: np.array(arm.matrix_world @ arm.data.bones[n].head_local)   # noqa: E731

    def fn(co, tag):
        z, y = co[:, 2], co[:, 1]
        front = _smooth((-y + 0.02) / 0.06)          # 1 on the front half
        chest = _smooth((z - (jk.z_b + 0.07)) / 0.10)
        # the back hangs from the shoulder blades: full pin above the pit, easing
        # to 0.35 at the waist and 0 at the seat (no shelf where the pin ends)
        back = np.clip(0.35 + 0.65 * _smooth((z - (jk.z_b + 0.02)) / (jk.z_pit - jk.z_b)), 0, 1) \
            * _smooth((z - jk.z_hip) / 0.08)
        pin = front * chest + (1 - front) * back
        # the buttoned front edges: both panels overlap at the button
        d_btn = np.hypot(co[:, 0], z - jk.z_b)
        pin = np.maximum(pin, np.exp(-(d_btn / 0.03) ** 2) * front)
        for t in (T["collar"], T["lapel"], T["pocket"], T["welt"]):
            pin[tag == t] = 1.0
        for s, t in (("l", T["sleeve_l"]), ("r", T["sleeve_r"])):
            sel = tag == t
            dS = np.linalg.norm(co - J(f"upperarm_{s}"), axis=1)
            dW = np.linalg.norm(co - J(f"hand_{s}"), axis=1)
            w = np.maximum(1.0 - _smooth((dS - 0.07) / 0.06), 0.5 * (1.0 - _smooth((dW - 0.05) / 0.04)))
            pin[sel] = w[sel]
        shrink = np.exp(-((z - jk.z_b) / 0.05) ** 2) * front * (tag == T["block"])
        # bending stiffness: canvassed chest, lapels, collar stiff; back medium; sleeves soft
        stiff = np.where(tag == T["block"], 0.4 + 0.6 * front * chest, 0.25)
        for t in (T["collar"], T["lapel"], T["pocket"], T["welt"]):
            stiff[tag == t] = 1.0
        return pin, shrink, stiff
    return fn


def trouser_pins(arm):
    """Trousers hang from the waistband and the top of the seat; the legs
    follow the skinned shape softly (a free leg swung by the knee and hip
    bend stretched against the shoe), the hem firmly (it rests on the shoe
    and moves with the foot: fully pinned over the modelled break, which
    lies within the collision distance of the shoe; soft there, the shoe
    pushes it into a crumpled ring and fails the strain gate); the knee back
    and the crotch stay soft."""
    import numpy as np
    z_hip = (arm.matrix_world @ arm.data.bones["pelvis"].head_local).z

    def fn(co, tag):
        pin = _smooth((co[:, 2] - (z_hip - 0.10)) / 0.08)
        leg = 0.12
        hem = _smooth((0.20 - co[:, 2]) / 0.08)
        pin = np.maximum(pin, np.maximum(leg, hem))
        stiff = np.full(len(co), 0.6)
        return pin, np.zeros(len(co)), stiff
    return fn


# --- hidden-surface removal ----------------------------------------------------------------

def hide_body(b, o, occluders):
    """Delete body polygons no camera can see: a vertex is covered when every ray
    of a small cone around its normal hits a garment within hide_ray_m. Covered
    vertices within hide_margin_m of a visible one are kept (look-spec §4.3).
    The head is never touched (hair is not an occluder).

    Two refinements for the armpit, where the patch that was kept poked 45 mm
    through the jacket in arm_raise: (1) under the bones in hide_enclosed (the
    upper arm, clavicle and torso, which the jacket closes round: the only
    ways out are the collar, cuffs and hem) a ray may travel hide_enclosed.m
    through the hollow under the arm before it meets the jacket; (2) with
    hide_self_m a ray that meets the body before any garment (the inner arm
    facing the torso) is blocked when, carried on through the body, it still
    ends on a garment: the line of sight ends inside the suit."""
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
    self_m = o.get("hide_self_m") or 0.0
    self_tree = sb.bvh_of_bm(bm) if self_m else None
    enc = o.get("hide_enclosed") or {}
    enc_pre = tuple(enc.get("bones", ()))
    stats = {"self_blocked_rays": 0, "enclosed_far_rays": 0}

    def blocked(p, dd, reach):
        hg = tree.ray_cast(p, dd, max(reach, self_m))
        if hg[0] is not None and hg[3] <= reach:
            stats["enclosed_far_rays"] += hg[3] > o["hide_ray_m"]
            return True
        if self_tree is None:
            return False
        hb = self_tree.ray_cast(p, dd, self_m)
        if hb[0] is None or (hg[0] is not None and hg[3] < hb[3]):
            return False
        on = tree.ray_cast(hb[0] + dd * 0.001, dd, self_m)[0] is not None
        stats["self_blocked_rays"] += on
        return on

    visible = []
    covered = set()
    for v in bm.verts:
        # the head is never touched; neither is the neck, where the layered
        # collars make the cover test fragile (a hollow neck shows as a sliver
        # of background between the shirt band and the jacket collar)
        dom = suit_ops.dominant(v, dl, names, bones)
        if dom in ("head", "neck_01"):
            visible.append(v)
            continue
        reach = enc.get("m", 0.0) if enc_pre and dom and dom.startswith(enc_pre) else 0.0
        reach = max(reach, o["hide_ray_m"])
        n = v.normal
        t = n.orthogonal().normalized()
        u = n.cross(t)
        dirs = [n] + [(n * math.cos(0.6) + (t * math.cos(a) + u * math.sin(a)) * math.sin(0.6))
                      for a in (0, math.pi / 2, math.pi, 3 * math.pi / 2)]
        if all(blocked(v.co + n * 0.001, dd, reach) for dd in dirs):
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
            "faces_deleted": len(gone), **stats}
