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
            "curve": 0.25,            # card centre lift, x half-width (rounded profile)
            "clumps": 320,            # top-layer cards (roots spread over the scalp)
            "length": {"f": 0.85,     # tip height: neck_01 joint (0) -> shoulder joints (1)
                       "jitter_m": 0.025},
            "max_len_m": 0.55,
            "radius_m": 0.0095,       # clump / card half-width at full size
            "radius_jitter": 0.35,
            "hang_widen": 0.35,       # extra half-width where a clump hangs free
            "taper_power": 1.3,       # half-width ~ 1 - t^k
            "aspect": 4.5,            # half-width / half-thickness at the root
            "aspect_tip": 1.8,        # x flatter at the tip (thin blade ends)
            "sides": 4,
            "lift_m": 0.003,          # sits this much over the under layer
            "tip_m": 0.0,             # tip height offset vs the variant's target
            # Under layer (the mass): fewer, wide, flat, solid clumps hugging the scalp.
            "under": {"clumps": 36, "radius_m": 0.02, "aspect": 4.0, "aspect_tip": 1.5,
                      "hang_widen": 0.6, "sides": 6, "lift_m": 0.0, "tip_m": -0.015},
            "gap_m": 0.0015,          # clearance over skin and clothes
            "layer_jitter_m": 0.007,
            "part_x_m": 0.012,        # part, off-centre to the character's left
            "part_push": 0.35,
            "comb_drop": 0.15,
            "side_drop": 0.3,         # extra drop for side roots (over the ear)
            "gravity": 0.95,
            "step_m": 0.01,
            "turn": 0.6,
            "segment_m": 0.03,
            "min_segments": 5,
            "max_segments": 16,
            "front_fall": {"side": -1, "count": 7, "az0_deg": 31, "az_step_deg": 2.5,
                           "el_deg": 22, "comb_side": 0.5, "comb_fwd": 0.0, "comb_down": 0.9,
                           "fall_after_m": 0.02, "tip_above_lips_m": 0.035,
                           "radius_scale": 0.8, "aspect": 4.0,
                           "max_len_m": 0.22},
            # Cards rooted on the cap's front edge, for a soft hairline.
            "hairline": {"count": 60, "behind_center_m": 0.0, "above_ear_m": -0.01,
                         "width_scale": 0.8},
            # Loose strands leaving top clumps part-way down (silhouette breakup).
            "flyaways": {"count": 80, "start": [0.08, 0.7], "length_m": 0.16,
                         "drift_m": 0.025, "wave_m": 0.006, "radius_m": 0.003},
            "region": {"temple_front_m": 0.045, "temple_above_ear_m": 0.0,
                       "nape_above_neck_m": 0.04},
            "cap": {"offset_m": 0.0025, "edge_taper": [0.2, 0.5, 0.8], "edge_smooth_iters": 6,
                    "v": 0.3,                        # texture v inside (opaque core)
                    "edge_v": [0.7, 0.66, 0.62]},     # outer rings: slightly ragged hairline
            "u_span_m": 0.05,         # strand texture width in metres around a clump
            # Generated "tip" strand textures (hair_mesh.strand_image): the
            # under layer and cap use an opaque core; the top layer, front
            # strands and flyaways only the strands (alpha-tested).
            "texture": {"seed": 3, "size": [256, 512], "strands": 260,
                        "width_px": [1.2, 2.6], "wave_px": 1.5, "value_sigma": 0.3,
                        "base_value": 0.42, "band_amp": 0.15,  # darker: the mass is in shadow
                        "tip_v": [0.72, 0.99],  # where each strand ends (v = 1 is the tip)
                        "core_v": 0.62,         # opaque below this
                        "color": "#1d1915"},
            # Card strands: ~0.14 mm/px across a 1.8 cm card, so 2.5-5 px is
            # 0.35-0.7 mm (stylised locks that survive at game distance).
            "texture_card": {"seed": 4, "size": [128, 512], "strands": 75,
                             "width_px": [2.5, 5.0], "wave_px": 2.0, "value_sigma": 0.3,
                             "base_value": 0.6, "band_amp": 0.1,
                             "edge_pow": 1.6,      # strand density falls off toward the edges
                             "edge_short": 0.5,    # and edge strands end sooner
                             "root_v": 0.12, "tip_v": [0.6, 0.99],  # staggered starts
                             "color": "#1d1915"},
            "roughness": 0.8,
            "specular": 0.12,
        },
        # Beard shell + jaw tufts (hair_beard.py).
        "beard": {
            "seed": 11,
            "sideburn_back_m": 0.004,  # behind the front of the ear
            "sideburn_up_m": 0.0,      # cheek line start above ear centre
            "moustache_m": 0.009,      # cheek line end above the upper lip
            "jaw_drop_m": 0.055,       # neckline start below ear centre
            "cheek_dip_m": 0.02,       # cheek line sag under the cheekbone
            "throat_back_m": 0.05,     # neckline end behind the chin front
            "under_chin_m": 0.008,     # neckline end below the chin (clears the shirt collar)
            "margin_m": 0.02,          # shell reaches this far past the lines (stubble feather band)
            "line_wobble_m": 0.004,    # low-frequency irregularity of the beard lines
            # Lip line: depth <= (distance from the lips - gap) x scale, so the
            # moustache and lower-lip hair thin out toward the lips.
            "lip_feather": {"gap_m": 0.003, "scale": 2.5},
            "thickness": {"cheek_m": 0.003, "jaw_m": 0.0045,   # off the skin
                          "chin_extra_m": 0.003, "chin_radius_m": 0.035,
                          "fade_m": 0.012,                    # 0 at -margin -> full at +fade
                          "floor_m": 0.0004},
            "edge_smooth_iters": 6,
            "uv": {"u_span_m": 0.04, "v_span_m": 0.065, "radius_m": 0.09},
            # Generated "edge" strand texture (hair_mesh.strand_image).
            "texture": {"seed": 5, "size": [512, 512], "strands": 2600,
                        "width_px": [1.5, 3.0], "wave_px": 2.0, "value_sigma": 0.35,
                        "base_value": 0.55, "band_amp": 0.08,
                        "len_px": [50, 120],  # 0.127 mm/px in v: hairs 6-15 mm
                        "slant": 0.15,
                        "edge_share": 0.55,   # share of hairs that start in the feather band
                        "edge_v": 0.43,       # feather band: depth -margin .. +~0.8 cm
                        "ramp_pow": 1.0,      # band hair density ~ depth^k: sparse stubble outside
                        "stub": 0.3,          # outermost hairs are this x len_px (stubble)
                        "solid_jitter_v": 0.05,  # uneven start of the solid part
                        "color": "#17110d"},
            # Tufts over the whole beard (hero budget: dense).
            # Tufts are small alpha cards (hair_mesh.card), 4 tris each.
            "tuft": {"count": 520, "min_depth_m": 0.004, "moustache_min_depth_m": 0.006,
                     "lip_clear_m": 0.006,  # no tuft roots this close to a lip vertex
                     "under_jaw_nz": 0.4,   # no tufts where the shell faces down more than this
                     "cloth_clear_m": 0.003,  # no tuft point this close to the clothes
                     "len_m": 0.008, "halfwidth_m": 0.0018,
                     "lift": 0.22,          # how far tufts stand off the shell
                     "sink_m": 0.003,       # root buried in the shell
                     "chin_weight": 2.0,    # extra density near the chin
                     "chin_len": 0.15},     # extra length near the chin
            "texture_card": {"seed": 9, "size": [64, 128], "strands": 24,
                             "width_px": [3.0, 5.0], "wave_px": 1.0, "value_sigma": 0.3,
                             "base_value": 0.6, "band_amp": 0.05, "slant": 0.08,
                             "edge_pow": 1.4, "edge_short": 0.4,
                             "root_v": 0.35, "tip_v": [0.55, 1.0],
                             "color": "#17110d"},
            "roughness": 0.8,
            "specular": 0.25,
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
