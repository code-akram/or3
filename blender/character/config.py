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
        "clumps": {
            "seed": 7,
            "clumps": 68,             # main clumps (roots spread over the scalp)
            "length": {"f": 0.85,     # tip height: neck_01 joint (0) -> shoulder joints (1)
                       "jitter_m": 0.02},
            "max_len_m": 0.55,
            "radius_m": 0.022,        # clump half-width at full size
            "radius_jitter": 0.2,
            "hang_widen": 0.5,        # extra half-width where a clump hangs free
            "taper_power": 1.6,       # half-width ~ 1 - t^k: holds width, tapers late
            "aspect": 3.6,            # half-width / half-thickness
            "gap_m": 0.0015,          # clearance over skin and clothes
            "layer_jitter_m": 0.002,
            "part_x_m": 0.012,        # part, off-centre to the character's left
            "part_push": 0.35,
            "comb_drop": 0.15,
            "side_drop": 0.3,         # extra drop for side roots (over the ear)
            "gravity": 0.95,
            "step_m": 0.01,
            "turn": 0.6,
            "segment_m": 0.035,
            "min_segments": 5,
            "max_segments": 12,
            "sides": 6,
            "front_fall": {"side": -1, "count": 2, "az0_deg": 35, "az_step_deg": 9,
                           "el_deg": 22, "comb_side": 0.5, "comb_fwd": 0.0, "comb_down": 0.9,
                           "fall_after_m": 0.02, "tip_above_lips_m": 0.035,
                           "radius_scale": 0.85,
                           "max_len_m": 0.22},
            "region": {"temple_front_m": 0.045, "temple_above_ear_m": 0.0,
                       "nape_above_neck_m": 0.04},
            "cap": {"offset_m": 0.0025, "edge_taper": [0.2, 0.5, 0.8], "edge_smooth_iters": 6},
            "color": "#1d1915",
            "roughness": 0.5,
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
            "thickness_m": 0.005,
            "chin_extra_m": 0.003,
            "edge_taper": [0.15, 0.45, 0.8],
            "edge_smooth_iters": 6,
            "tufts": 24,
            "tuft_len_m": 0.008,
            "tuft_radius_m": 0.0035,
            "color": "#201a15",
            "roughness": 0.6,
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
