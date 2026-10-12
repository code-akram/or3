"""Hair (and later beard). Placeholder MPFB card hair until the clump meshes land."""


def add(b):
    asset = b.cfg["hair"]["asset"]
    b.mpfb.add_mhclo(b.basemesh, "hair", asset, "Hair")
    b.cutouts.append(asset.rsplit(".", 1)[0])


def post(b):
    pass
