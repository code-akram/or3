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
        "macros": {"gender": 1.0, "age": 0.55, "muscle": 0.6, "weight": 0.5,
                   "height": 0.6, "proportions": 0.6},
        "race": {"caucasian": 0.6, "asian": 0.3, "african": 0.1},
        "skin": "young_caucasian_male.mhmat",
    },
    "head": {
        # (asset subdir, mhclo file, MPFB asset type)
        "parts": [["eyes", "low-poly.mhclo", "Eyes"],
                  ["eyebrows", "eyebrow001.mhclo", "Eyebrows"],
                  ["eyelashes", "eyelashes01.mhclo", "Eyelashes"],
                  ["teeth", "teeth_base.mhclo", "Teeth"],
                  ["tongue", "tongue01.mhclo", "Tongue"]],
        "cutouts": ["eyebrow", "eyelashes"],
        "edits": {},  # parametric head edits (head.edit_base); empty = stock head
    },
    "hair": {
        "asset": "long01.mhclo",
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
        # MPFB ships no teeth under 7.1k tris (all six shapes are 7,120).
        "decimate": {"teeth": 900},
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
