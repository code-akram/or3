"""Head: parametric face edits and face parts (eyes, brows, lashes, teeth, tongue).

edit_base runs on the base mesh before any proxy is fitted, so fitted assets
follow the edited head: first the MPFB face targets (head.targets), then the
parametric controls and planarisation pass (head.edits, head.planes; see
head_shape.py and bench/m1/look-spec.md §2.3). add_parts fits the face parts
and then measures the spec landmarks on the still-nude human
(head_measure.py). post runs on the staged export meshes.
"""

from . import body, head_measure, head_refine, head_shape


def edit_base(b):
    body.load_targets(b, b.cfg["head"].get("targets"))
    head_shape.apply(b)


def add_parts(b):
    for subdir, fname, atype in b.cfg["head"]["parts"]:
        b.mpfb.add_mhclo(b.basemesh, subdir, fname, atype)
    b.cutouts += b.cfg["head"]["cutouts"]
    head_measure.measure_live(b)


def post(b):
    pass


def refine(b):
    """After suit_post (covered body polygons gone) and hair_post (hair and
    beard sampled the low-res surface): subdivide the face and hands,
    re-planarise, sculpt, re-pack UVs, then generate the skin and eyes
    (head_refine, skin_tex, eyes_hq)."""
    notes = head_refine.refine(b)
    if notes is None:
        return
    from . import eyes_hq, skin_tex
    skin_tex.build(b)
    eyes_hq.build(b)
