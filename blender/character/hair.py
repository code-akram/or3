"""Hair and beard.

Default: a strand groom (hair_groom: Blender hair curves + Geometry Nodes,
render-only in the `hero_only` collection) and game cards baked from it
(hair_groom_cards), a beard shell with jaw tufts (hair_beard) and brows,
all built post-staging on the baked body so they follow the head track's
edits. {"hair": {"groom": null}} falls back to the hair_clumps cards; the
MPFB card hair is still available for comparison:
{"hair": {"asset": "long01.mhclo", "groom": null, "clumps": null, "beard": null}}.
Variants for the direction checkpoint: bench/m1/variants/hair-*.json.
"""

from . import brows, hair_beard, hair_clumps, lashes
from .hair_frame import HeadFrame


def add(b):
    asset = b.cfg["hair"].get("asset")
    if asset:
        b.mpfb.add_mhclo(b.basemesh, "hair", asset, "Hair")
        b.cutouts.append(asset.rsplit(".", 1)[0])


def post(b):
    cfg = b.cfg["hair"]
    groom = cfg.get("groom")
    if groom is not None and groom.get("enabled", True) is False:
        groom = None
    if not (cfg.get("clumps") or cfg.get("beard")):
        return
    # Clothes as staged: the stock garments, or the suit track's tailored
    # parts ("<human>.suit_<part>_export"), which exist once suit.post ran.
    clothes = [c.rsplit(".", 1)[0] for c in b.cfg["suit"]["clothes"]] + [".suit_"]
    body = next(o for o in b.meshes() if o.vertex_groups.get("scalp"))
    colliders = [body] + [o for o in b.meshes() if any(c in o.name for c in clothes)]
    b.notes["hair_colliders"] = sorted(o.name for o in colliders)
    frame = HeadFrame(b, colliders)
    b.notes["head_frame"] = frame.summary()
    if cfg.get("clumps"):
        if groom is not None:
            from . import hair_groom
            g = hair_groom.build(b, frame, cfg["clumps"], groom)
            if g["cfg"].get("cards", "groom") == "groom":
                from . import hair_groom_cards
                hair_groom_cards.build(b, frame, cfg["clumps"], g)
            else:
                hair_clumps.build(b, frame, cfg["clumps"])
        else:
            hair_clumps.build(b, frame, cfg["clumps"])
    if cfg.get("beard"):
        hair_beard.build(b, frame, cfg["beard"])
    if cfg.get("brows"):
        brows.build(b, frame, cfg["brows"])
    if cfg.get("lashes"):
        lashes.build(b, frame, cfg["lashes"])
