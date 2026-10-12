"""Head: parametric face edits and face parts (eyes, brows, lashes, teeth, tongue).

edit_base runs on the base mesh before any proxy is fitted, so fitted assets
follow the edited head. post runs on the staged export meshes.
"""


def edit_base(b):
    if b.cfg["head"]["edits"]:
        raise NotImplementedError("head edits: owned by the m1 head track")


def add_parts(b):
    for subdir, fname, atype in b.cfg["head"]["parts"]:
        b.mpfb.add_mhclo(b.basemesh, subdir, fname, atype)
    b.cutouts += b.cfg["head"]["cutouts"]


def post(b):
    pass
