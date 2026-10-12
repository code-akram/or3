"""Hair and beard.

Default: generated clump-mesh hair (hair_clumps) and a beard shell with jaw
tufts (hair_beard), both built post-staging on the baked body so they follow
the head track's edits. The MPFB card hair is still available for
comparison: {"hair": {"asset": "long01.mhclo", "clumps": null, "beard": null}}.
Variants for the direction checkpoint: bench/m1/variants/hair-*.json.
"""

from . import hair_beard, hair_clumps
from .hair_frame import HeadFrame


def add(b):
    asset = b.cfg["hair"].get("asset")
    if asset:
        b.mpfb.add_mhclo(b.basemesh, "hair", asset, "Hair")
        b.cutouts.append(asset.rsplit(".", 1)[0])


def post(b):
    cfg = b.cfg["hair"]
    if not (cfg.get("clumps") or cfg.get("beard")):
        return
    clothes = [c.rsplit(".", 1)[0] for c in b.cfg["suit"]["clothes"]]
    body = next(o for o in b.meshes() if o.vertex_groups.get("scalp"))
    colliders = [body] + [o for o in b.meshes() if any(c in o.name for c in clothes)]
    frame = HeadFrame(b, colliders)
    b.notes["head_frame"] = frame.summary()
    if cfg.get("clumps"):
        hair_clumps.build(b, frame, cfg["clumps"])
    if cfg.get("beard"):
        hair_beard.build(b, frame, cfg["beard"])
