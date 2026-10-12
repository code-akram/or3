"""Single build config: defaults plus an optional JSON override (deep-merged).

Keys are grouped by the module that owns them, so a stage only reads its own
section. Override example (look-dev candidate):

    {"body": {"macros": {"muscle": 0.7}}, "hair": {"asset": "long02.mhclo"}}
"""

import copy
import json

DEFAULTS = {
    "assets": {
        # Data roots injected into MPFB's in-memory preferences (never saved).
        "system": None,  # makehuman_system_assets/unpacked
        "suit": None,    # suits01/unpacked
    },
    "body": {
        # height 0.607: stature 1.85 m (look-spec §1.2); was 0.6 in spike 1.
        "macros": {"gender": 1.0, "age": 0.55, "muscle": 0.6, "weight": 0.5,
                   "height": 0.607, "proportions": 0.6},
        "race": {"caucasian": 0.6, "asian": 0.3, "african": 0.1},
        "skin": "young_caucasian_male.mhmat",
        # MPFB detail targets {target file stem: weight} (body.load_targets).
        # Tuned to look-spec §1.2: bideltoid 0.545 -> 0.561 m, hip breadth
        # 0.386 -> 0.373 m, shoulder:hip 1.41 -> 1.50 (bench/m1/head.md).
        "targets": {"measure-shoulder-dist-incr": 0.12, "torso-vshape-incr": 0.15,
                    "hip-scale-horiz-decr": 0.18},
    },
    "head": {
        # (asset subdir, mhclo file, MPFB asset type)
        "parts": [["eyes", "low-poly.mhclo", "Eyes"],
                  ["eyebrows", "eyebrow001.mhclo", "Eyebrows"],
                  ["eyelashes", "eyelashes01.mhclo", "Eyelashes"],
                  ["teeth", "teeth_base.mhclo", "Teeth"],
                  ["tongue", "tongue01.mhclo", "Tongue"]],
        "cutouts": ["eyebrow", "eyelashes"],
        # MPFB face targets {target file stem: weight}, loaded before the edits.
        "targets": {},
        # Parametric controls in [-1, 1] (head_shape.CONTROLS; look-spec §2.3).
        "edits": {},
        # Planarisation blend 0..1 per plane group (head_shape.PLANES).
        "planes": {},
        # Post-staging refinement (head_refine.py, skin_tex.py, eyes_hq.py):
        # dense face + hands, re-fitted planes, sculpt forms, re-packed UVs,
        # generated 4k skin. null disables the whole stage.
        "refine": {
            "subdiv": {"face": 1, "hands": 1, "smooth": 0.6},
            "replanarise": 1.0, "plane_sharp": 3.0,
            "sculpt": {"knuckle_mm": 2.0, "tendon_mm": 0.9, "nail_mm": 0.35, "lid_margin_mm": 0.4},
            "uv": True, "uv_px": {"head_px": 4096, "hands_px": 2048},
            "skin": {"bake_px": 4096, "ao_samples": 16, "ao_down": 2, "margin_px": 16, "sss": 0.0,
                     "save_maps": True, "base": "#c4a996",
                     "head": {}, "hands": {}},
            # Generated eyeballs + iris texture (eyes_hq.py); null keeps the MPFB eyes.
            "eyes": {},
        },
    },
    "hair": {
        # MPFB card hair (spike-1 placeholder); null = generated hair only.
        "asset": None,
        # Generated clump hair (hair_clumps.py). Default variant: shoulder.
        # Hero budget (user, 2026-10-12): hair + beard up to ~35k tris.
        "clumps": {
            "seed": 7,
            # Top layer (the visible hair): many curved alpha-tested cards.
            "card": True,             # False: flattened tubes like the under layer
            "curve": 0.35,            # card centre lift, x half-width (rounded profile)
            "twist": 1.0,             # max card twist root -> tip (radians, per-card random)
            "clumps": 360,            # top-layer cards (roots spread over the scalp)
            "length": {"f": 0.85,     # tip height: neck_01 joint (0) -> shoulder joints (1)
                       "jitter_m": 0.025},
            "max_len_m": 0.55,
            "radius_m": 0.008,        # clump / card half-width at full size
            "radius_jitter": 0.35,
            "hang_widen": 0.05,       # extra half-width where a clump hangs free
            "taper_power": 1.3,       # half-width ~ 1 - t^k
            "aspect": 4.5,            # half-width / half-thickness at the root
            "aspect_tip": 1.8,        # x flatter at the tip (thin blade ends)
            "sides": 4,
            "lift_m": 0.003,          # sits this much over the under layer
            "tip_m": 0.0,             # tip height offset vs the variant's target
            "shade_top": 1.0,         # vertex-colour value of the top layer (x lock jitter)
            # Under layer (the mass): fewer, wide, flat, solid clumps hugging the scalp.
            "under": {"clumps": 44, "radius_m": 0.016, "aspect": 4.0, "aspect_tip": 1.5,
                      "hang_widen": 0.15, "sides": 6, "lift_m": 0.0, "tip_m": -0.015,
                      "shade": 0.7},
            # Per-vertex colour "lock" (COLOR_0): per-lock lognormal value,
            # depth (lifted cards lighter), dark roots.
            "shade": {"lock_sigma": 0.22, "depth": 0.35, "root": 0.8, "root_v": 0.3},
            "gap_m": 0.0015,          # clearance over the skin
            "cloth_gap_m": 0.004,     # extra clearance over the suit (collar, lapel): hovers, not painted on
            "neck_tuck": 0.5,         # below the jaw, side lengths slide back beside the neck (direction push)
            "ear_margin_m": 0.003,    # clearance round the ear ellipsoids
            "layer_jitter_m": 0.008,
            # Volume: stand-off from the skull along each strand (Strand.lift):
            # 0 at the root, full after rise_m, held hold_m, decaying to keep
            # x over fall_m (the back keeps half). top_m on the crown, side_m
            # on the sides and nape; cards lifted higher in the layer get
            # more (layer), jittered per strand; under tubes x under.
            "volume": {"top_m": 0.010, "side_m": 0.002, "rise_m": 0.06, "hold_m": 0.03,
                       "fall_m": 0.08, "keep": 0.4, "jitter": 0.4, "layer": 0.4,
                       "under": 0.6, "hairline": 0.3},
            "cling": 0.2,             # hanging strands lean in toward the head axis (no bell)
            "hang_turn": 0.85,        # direction blend per step once hanging (turn: on the skull)
            "tip_width": 0.3,         # card half-width at the tip, x the root's
            # Lateral wave of hanging strands (direction amplitude, metres per cycle).
            "wave": {"amp": 0.25, "period_m": 0.12},
            "part_x_m": 0.012,        # part, off-centre to the character's left
            "part_push": 0.5,
            "part_width_m": 0.03,    # the push decays over this distance from the part
            "comb_drop": 0.15,
            "side_drop": 0.15,        # extra drop for side roots (behind the ear)
            "gravity": 0.95,
            "step_m": 0.01,
            "turn": 0.6,
            "segment_m": 0.03,
            "min_segments": 5,
            "max_segments": 16,
            # Front falls: heavier strands at the temples that fall forward and
            # frame the face, asymmetric (longer on the character's right).
            "front_fall": [
                {"side": -1, "count": 2, "az0_deg": 34, "az_step_deg": 5.0,
                 "el_deg": 22, "comb_side": 0.15, "comb_fwd": 0.0, "comb_down": 0.9,
                 "fall_after_m": 0.02, "tip_above_lips_m": 0.035, "hug": 0.15,
                 "clear_m": 0.006,      # stand-off from the skin (casts a shadow, not painted on)
                 "flare_after_m": 0.09, "flare": 0.12,  # the end curls away from the cheek
                 "twist": 0.3, "wave": 0.0,
                 "radius_scale": 0.35, "aspect": 4.0, "max_len_m": 0.22, "segment_m": 0.015,
                 "curve": 0.5, "shade": 0.85},
                {"side": 1, "count": 0, "az0_deg": 34, "az_step_deg": 4.0,
                 "el_deg": 20, "comb_side": 0.25, "comb_fwd": 0.0, "comb_down": 0.9,
                 "fall_after_m": 0.02, "tip_above_lips_m": 0.08, "hug": 0.0,
                 "radius_scale": 0.45, "aspect": 4.0, "max_len_m": 0.15, "segment_m": 0.015,
                 "curve": 0.4, "shade": 0.8}],
            # Cards rooted `ring` rings inside the cap's front edge, behind the
            # feather band, for a soft hairline.
            "hairline": {"count": 64, "ring": 1, "root_w": 0.2, "twist_scale": 0.5, "behind_center_m": 0.0,
                         "above_ear_m": -0.01, "width_scale": 0.8},
            # Loose strands leaving top clumps part-way down (silhouette breakup).
            "flyaways": {"count": 70, "start": [0.25, 0.7], "length_m": 0.16,
                         "drift_m": 0.015, "wave_m": 0.008, "radius_m": 0.003,
                         "max_up": 0.6,  # skip starts whose normal points up (crown)
                         "shade": 0.85},
            "region": {"temple_front_m": 0.045, "temple_above_ear_m": 0.0,
                       "nape_above_neck_m": 0.04},
            # Scalp cap: UV v = depth from the hairline (0 .. v_span_m), u =
            # arc length round the head / u_span_m; carries the feather texture.
            "cap": {"offset_m": 0.0025, "edge_taper": [0.2, 0.5, 0.8], "edge_smooth_iters": 6,
                    "radius_m": 0.09, "u_span_m": 0.06, "v_span_m": 0.03,
                    "shade": 0.75},
            "u_span_m": 0.05,         # strand texture width in metres around an under tube
            # Spring chains (hair_springs.py): sector -> bone count, 12 total.
            "springs": {"chains": {"back_l": 2, "back_r": 2, "side_l": 3, "side_r": 3,
                                   "front_l": 2, "front_r": 2},
                        "hang_below_ear_m": 0.01,  # strands hang once below ear level + this
                        "front_hang_m": 0.02,      # front falls hang from this far past the root
                        "min_verts": 20, "min_len_m": 0.04},
            # Generated strand textures (hair_mesh.strand_image).
            # Cap + under tubes ("edge" kind): v = depth from the hairline.
            # Fine short hairs (0.12-0.26 mm wide, 5-13 mm long) whose density
            # ramps up over the feather band (edge_v x v_span_m ~ 1.3 cm),
            # then an opaque core: the hairline is a gradual density falloff.
            "texture_cap": {"seed": 3, "size": [512, 512], "strands": 1200,
                            "width_px": [1.0, 2.0], "wave_px": 1.5, "value_sigma": 0.3,
                            "base_value": 0.5, "band_amp": 0.15,
                            "len_px": [150, 400], "slant": 0.06,
                            "edge_share": 0.6, "edge_v": 0.3, "ramp_pow": 2.0, "stub": 0.35,
                            "solid_jitter_v": 0.06,
                            "v_band": [0.08, 0.92],  # pattern rows; the rest transparent (v wraps)
                            "color": "#1d1915"},
            # Under tubes ("tip" kind): opaque core, strand tips past core_v.
            "texture": {"seed": 3, "size": [256, 512], "strands": 260,
                        "width_px": [1.2, 2.6], "wave_px": 1.5, "value_sigma": 0.3,
                        "base_value": 0.42, "band_amp": 0.15,  # darker: the mass is in shadow
                        "tip_v": [0.78, 0.99],  # where each strand ends (v = 1 is the tip)
                        "core_v": 0.7,          # opaque below this (the mass covers the collar)
                        "v_band": [0.04, 0.92],  # pattern rows; the rest transparent (v wraps)
                        "color": "#1d1915"},
            # Card atlas: `variants` lock patterns side by side (u range per
            # card), each 1-3 sub-locks of strands with gaps between them.
            # ~0.125 mm/px across a 1.6 cm card: 2-4 px is 0.25-0.5 mm.
            "texture_card": {"seed": 4, "size": [512, 512], "strands": 22, "variants": 4,
                             "locks": [1, 3], "lock_spread_px": 14, "variant_sigma": 0.15,
                             "tip_sigma_v": 0.14, "tip_taper_v": 0.18,
                             "width_px": [2.5, 5.0], "wave_px": 3.0, "value_sigma": 0.35,
                             "base_value": 0.55, "band_amp": 0.1,
                             "edge_pow": 1.6,      # strand density falls off toward the edges
                             "edge_short": 0.5,    # and edge strands end sooner
                             "root_v": 0.12, "tip_v": [0.5, 0.95],  # staggered starts/ends
                             "color": "#1d1915"},
            "roughness": 0.68,
            "specular": 0.1,
            "anisotropy": 0.3,
        },
        # Short full beard: strand groom (hero, hair curves in hero_only) and
        # game shells + cards baked from it (hair_beard.py, beard_groom.py,
        # beard_bake.py). Lengths/densities: bench/m1/v2/direction.md §2 C.
        "beard": {
            "seed": 11,
            # Region (landmark lines in profile; see hair_beard.landmarks).
            "sideburn_back_m": -0.004,  # behind the front of the ear (- = in front)
            "sideburn_up_m": -0.004,   # cheek line start above ear centre
            "corner_back_m": 0.022,    # cheek line end: behind the lip front
            "moustache_m": 0.010,      # cheek line end above the upper lip
            "cheek_dip_m": 0.02,       # cheek line sag under the cheekbone
            "jaw_drop_m": 0.06,        # neckline start below ear centre
            "neck_back_m": 0.012,      # ... behind the ear front
            "throat_back_m": 0.045,    # neckline end behind the chin front
            "under_chin_m": 0.018,     # neckline end below the chin
            "moustache_height_m": 0.012,  # moustache top over the upper lip
            "nose_clear_m": 0.004,     # above the lips, skin this far in front of them is nose: bare
            "lips_w": 0.5,             # body vertices over this `lips` weight are vermilion: no roots
            "fade_m": 0.010,           # skin_tex.beard_depth: the skin's stubble shadow ramp past the margin
            "lip_band_m": 0.004,       # top band of the upper lip in the shell patch (no roots): moustache overhang
            "mouth_depth_m": 0.008,    # skin this far behind the lip front, inside the corners, facing back: mouth
            # Patch reaches this far past each line (cheek, neck, back,
            # moustache top): the stubble band.
            "margin_m": 0.014, "neck_margin_m": 0.03, "back_margin_m": 0.006,
            "moustache_margin_m": 0.003,
            # Density across the line: 1 at in_m inside, line_density at the
            # line, 0 at out_m outside; stubble from stubble_in_m inside to
            # the patch edge.
            "fade": {"in_m": 0.010, "out_m": 0.004, "neck_in_m": 0.014, "neck_out_m": 0.006,
                     "line_density": 0.15, "pow": 1.6, "line_length": 0.35,
                     "stubble_in_m": 0.004},
            "line_wobble_m": 0.004,
            "edge_smooth_iters": 6,
            # Hair length by zone (direction §2 C: cheeks 6-8, jaw 9-11,
            # chin 12-15, soul patch 10, moustache 8-10 over the lip by 2 mm).
            "length": {"cheek_m": 0.0075, "jaw_m": 0.0105, "chin_extra_m": 0.0055,
                       "chin_radius_m": 0.03, "soul_m": 0.010, "soul_radius_m": 0.010,
                       "moustache_m": 0.0095, "lip_overlap_m": 0.002, "neck_m": 0.009},
            "comb": {"cheek_back": 0.3, "chin_forward": 0.3, "soul_forward": 0.8, "under_jaw_back": 0.6,
                     "moustache_down": 1.0, "moustache_side": 0.6, "philtrum_x_m": 0.006,
                     "smooth_iters": 3},
            # Strand growth (beard_groom.grow): exit angle over the skin
            # relaxing to the tip angle, yaw / curl spread, curly share.
            "groom": {"per_cm2": 200, "points": 8, "root_sink_m": 0.0005,
                      "elev0": 38, "elev1": 4, "elev1_under": 0, "elev_sigma": 10,
                      "elev_chin": 12,  # extra exit angle at the chin (bulk, profile)
                      "elev_soul": 25,  # ... under the lower lip (the hairs fill the sulcus)
                      "elev0_moustache": 22, "elev1_moustache": -25,
                      "yaw_sigma": 25, "curl_sigma": 12, "curl_share": 0.25,
                      "curl_radius_m": [0.008, 0.015], "curl_lift": 0.15,
                      "len_min": 0.7, "bend_pow": 1.0,
                      "gap_m": [0.0002, 0.0004],  # clearance over the skin, root -> tip
                      "clump_base": 0.25, "clump_moustache": 0.35, "clump_chin": 0.25,
                      "frizz_base": 1.0},
            "stubble": {"per_cm2": 60, "points": 3, "length_m": [0.001, 0.002],
                        "elev0": 35, "elev1": 20, "frizz": 0.3, "radius_scale": 0.8},
            # Tone: melanin / redness per strand (hero), with the game
            # palette interpolated by melanin (swatches, sRGB).
            "tone": {"melanin": 0.98, "redness": 0.45, "sigma": 0.015,
                     "warm_share": 0.12, "warm": [0.9, 0.7],
                     "grey_share": 0.025, "grey_extra": 0.05, "grey": [0.2, 0.15],
                     "swatches": [[0.2, "#948e86"], [0.9, "#6a4a32"], [0.98, "#3e2e23"],
                                  [1.0, "#30241b"]],
                     "value_sigma": 0.3},
            "hero": {"radius_m": [0.00004, 0.00007], "tip_radius": 0.35,
                     "material": {"roughness": 0.32, "radial_roughness": 0.35, "coat": 0.1,
                                  "root_dark": 0.06},
                     "clump": {"shape": 0.4, "tip_spread": 0.0004, "guide_distance_m": 0.004},
                     "frizz": {"distance_m": 0.0007, "shape": 0.6}},
            # Game shells: the decimated patch stacked along the normal at
            # t_k x the local groom canopy; tile k is the groom slice.
            "shells": {"layers": 14, "t_pow": 1.3, "base_tris": 420, "lift_m": 0.0,
                       "atlas_cols": 2, "tile": [1024, 512], "px_per_m": 3000.0,
                       "radius_scale": 1.0, "min_radius_px": 0.45,
                       "canopy_radius_m": 0.005, "canopy_pct": 80, "canopy_floor_m": 0.0006,
                       "shade": {"root": 0.6, "full_at": 0.8},
                       "uv": {"max_angle_deg": 120, "pad": 0.02, "origin_back_m": 0.0,
                              "origin_up_m": 0.0},
                       "roughness": 0.6, "specular": 0.25},
            # Silhouette cards along groom clumps (beard_bake.build_cards).
            "cards": {"count": 180, "spacing_m": 0.0035, "clump_radius_m": 0.002,
                      "min_members": 4, "min_len_m": 0.005, "segments": 3,
                      "tip_extend": 0.08, "width_scale": 1.3, "taper": 0.5,
                      "min_halfwidth_m": 0.0008, "max_halfwidth_m": 0.0025,
                      "jaw_nz": [-0.85, 0.05], "moustache_edge_m": 0.006,
                      "roll_jaw_deg": 80, "roll_moustache_deg": 35, "roll_chin_deg": 50,
                      "roll_sigma_deg": 15,
                      "cell": [48, 128], "atlas_px": [2048, 1024], "px_per_m": 11000.0,
                      "radius_scale": 1.0, "min_radius_px": 0.6, "root_shade": 0.55,
                      "roughness": 0.6, "specular": 0.25},
        },
        # Eyebrows: strand groom (hero) + shells and edge cards baked from it
        # (brows.py). Direction §2 C: 500-700 strands per side, 6-9 mm,
        # lying at ~80 deg to the normal, 8 mm tall at the head, 4 at the tail.
        "brows": {
            "seed": 13,
            "proxy": "eyebrow",        # the fitted MPFB proxy used as the landmark, then dropped
            "bins": 10,                # spine samples along each brow
            "half_height_m": [0.004, 0.002],  # band half-height at the head .. tail
            "centre_up_m": 0.0005,     # band centre over the proxy's spine
            "margin_m": 0.002,         # feather past the band
            "select_m": 0.006,         # patch selection beyond the feather (density 0 there)
            "end_extend_m": 0.004,     # patch beyond the proxy's ends
            "depth_tol_m": 0.015,      # skin within this y of the proxy (the face front only)
            "core": 0.45,              # |dz|/hh below this is full density
            "tail_start": 0.55, "tail_thin": 0.85,  # the tail thins to 1 - tail_thin
            "head_feather": 0.1,       # the head starts at half density, full after this
            "length_m": [0.006, 0.008, 0.0085, 0.006],  # at along 0, 0.35, 0.7, 1
            # comb by thirds (x outward, z up), blended
            "thirds": {"inner_up": 1.4, "inner_out": 0.6, "mid_up": 0.12, "tail_up": -0.35},
            "edge_turn": 0.45,         # upper-edge hairs turn down, lower-edge up (x dz)
            "smooth_iters": 2,
            "groom": {"per_cm2": 230, "points": 6, "root_sink_m": 0.0003,
                      "elev0": 22, "elev1": 4, "elev_sigma": 6, "yaw_sigma": 10, "curl_sigma": 15,
                      "len_min": 0.65, "gap_m": [0.00015, 0.0003], "clump": 0.3, "frizz": 0.4},
            "tone": {"melanin": 0.97, "redness": 0.45, "sigma": 0.02,
                     "swatches": [[0.2, "#948e86"], [0.86, "#5a3e2a"], [0.97, "#2a1f18"],
                                  [1.0, "#1e1712"]],
                     "redness_ref": 0.45, "value_sigma": 0.25},
            "hero": {"radius_m": [0.00003, 0.00005], "tip_radius": 0.3,
                     "material": {"roughness": 0.3, "radial_roughness": 0.35, "coat": 0.1,
                                  "root_dark": 0.04},
                     "clump": {"shape": 0.3, "tip_spread": 0.0003, "guide_distance_m": 0.0018},
                     "frizz": {"distance_m": 0.0004, "shape": 0.6}},
            "base_tris": 0,            # (unused; shells.base_tris)
            "shells": {"layers": 12, "t_pow": 1.2, "base_tris": 90, "lift_m": 0.0,
                       "atlas_cols": 2, "tile": [512, 192], "px_per_m": 6000.0,
                       "radius_scale": 1.3, "min_radius_px": 0.5,
                       "canopy_radius_m": 0.003, "canopy_pct": 85, "canopy_floor_m": 0.0005,
                       "shade": {"root": 0.6, "full_at": 0.7},
                       "roughness": 0.6, "specular": 0.25},
            "cards": {"per_side": 20, "spacing_m": 0.0025, "clump_radius_m": 0.0015,
                      "min_members": 3, "min_len_m": 0.004, "segments": 2,
                      "edge_dz": 0.55, "tail_from": 0.75,
                      "tip_extend": 0.08, "width_scale": 1.3, "taper": 0.5,
                      "min_halfwidth_m": 0.0005, "max_halfwidth_m": 0.0015,
                      "roll_deg": 10, "roll_sigma_deg": 10,
                      "cell": [32, 96], "atlas_px": [1024, 256], "px_per_m": 12000.0,
                      "radius_scale": 1.2, "min_radius_px": 0.6, "root_shade": 0.6,
                      "roughness": 0.6, "specular": 0.25},
        },
        # Eyelashes: strand groom (hero) + two baked strips per eye (lashes.py);
        # the MPFB eyelash proxy is the landmark and is dropped (drop_proxy).
        # null keeps the MPFB lashes.
        "lashes": {
            "seed": 17, "proxy": "eyelashes", "drop_proxy": True, "bins": 14, "points": 7,
            "margin_step_m": 0.0005, "margin_min_open_m": 0.0015, "margin_in_m": 0.0003,
            "upper": {"count": 165, "length_m": [0.0045, 0.0075, 0.0095, 0.010, 0.0085, 0.006],
                      "curl_deg": 55, "forward": 0.8, "splay_deg": 6, "fan_deg": 25,
                      "row_jitter_m": 0.00025, "strip_cols": 8},
            "lower": {"count": 80, "length_m": [0.0018, 0.0032, 0.0045, 0.0042, 0.003],
                      "curl_deg": 25, "forward": 0.45, "splay_deg": 8, "fan_deg": 20,
                      "row_jitter_m": 0.0002, "strip_cols": 6},
            "melanin": 0.99, "redness": 0.3, "clump": 0.55, "gap_m": 0.00015,
            "hero": {"radius_m": [0.00004, 0.000055], "tip_radius": 0.25,
                     "material": {"roughness": 0.25, "radial_roughness": 0.3, "coat": 0.1,
                                  "root_dark": 0.0},
                     "clump": {"shape": 0.5, "tip_spread": 0.0001, "guide_distance_m": 0.0012}},
            "atlas": [512, 512], "strip_radius_px": 2.2, "lash_line_px": 1.5,
            "color": "#1a1410",
        },
    },
    "suit": {
        "clothes": ["toigo_male_suit_tie_and_jacket.mhclo", "shoes04.mhclo"],
    },
    "rig": {
        "builtin": "game_engine",
        "helpers": [],  # helper/twist bones (rig.post); empty = stock rig
    },
    "budgets": {
        # Decimate a staged mesh whose name contains the key down to max tris.
        # MPFB ships no teeth under 7.1k tris (all six shapes are 7,120);
        # look-spec §5.1 budget is <= 500.
        "decimate": {"teeth": 480},
    },
    "export": {
        "max_influences": 4,
    },
}


def merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load(path=None, overrides=None):
    cfg = DEFAULTS
    if path:
        with open(path) as f:
            cfg = merge(cfg, json.load(f))
    return merge(cfg, overrides)
