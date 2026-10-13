"""Head: parametric face edits and face parts (eyes, brows, lashes, teeth, tongue).

edit_base runs on the base mesh before any proxy is fitted, so fitted assets
follow the edited head: first the MPFB face targets (head.targets), then the
parametric controls and planarisation pass (head.edits, head.planes; see
head_shape.py and bench/m1/look-spec.md §2.3), then the soft-tissue forms,
lid heights and seeded asymmetry (head.forms; head_forms.py). add_parts fits
the face parts and then measures the spec landmarks on the still-nude human
(head_measure.py). post runs on the staged export meshes; refine adds the
dense face, skin and eyes; hero wires the Cycles-only materials after export.
"""

from . import body, head_forms, head_measure, head_refine, head_shape


def edit_base(b):
    body.load_targets(b, b.cfg["head"].get("targets"))
    head_shape.apply(b)
    head_forms.apply(b)


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
    from . import eyes_hq, hand_forms, skin_tex
    hand_forms.apply(b)  # Track G: hand forms on the dense hands, before the skin bake
    skin_tex.build(b)
    eyes_hq.build(b)


def hero(b):
    """After the GLB export, before the .blend is saved: the Cycles-only hero
    skin (subsurface, coat, sheen, displacement on an adaptive subdivision)
    and the hero eyes (refractive cornea, tear meniscus, caruncle) in the
    hero_only collection. The game materials stay in the GLB."""
    from . import eyes_hq, skin_tex, skin_vellus
    skin_tex.hero(b)
    skin_vellus.build(b)
    eyes_hq.hero(b)
    mouth_hero(b)


# Hero mouth parts: the MPFB teeth texture is near white and the materials are
# dry, so in a parted mouth the teeth glow. Render-only (the GLB keeps the
# asset materials): teeth value x0.78, satin, a little translucency; a wet
# tongue.
MOUTH_HERO = {"teeth": {"value": 0.78, "roughness": 0.3, "sss": 0.25},
              "tongue": {"value": 0.85, "roughness": 0.4, "sss": 0.5}}


def mouth_hero(b):
    import bpy
    done = {}
    for o in b.meshes():
        part = "teeth" if "teeth" in o.name else "tongue" if "tongue" in o.name else None
        if part is None:
            continue
        c = MOUTH_HERO[part]
        for m in o.data.materials:
            if m is None or m.name in done or not m.node_tree:
                continue
            nt = m.node_tree
            p = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
            if p is None:
                continue
            if p.inputs["Base Color"].is_linked:
                src = p.inputs["Base Color"].links[0].from_socket
                mul = nt.nodes.new("ShaderNodeMix")
                mul.data_type = "RGBA"
                mul.blend_type = "MULTIPLY"
                mul.inputs["Factor"].default_value = 1.0
                mul.inputs["B"].default_value = (c["value"],) * 3 + (1.0,)
                nt.links.new(src, mul.inputs["A"])
                nt.links.new(mul.outputs["Result"], p.inputs["Base Color"])
            p.inputs["Roughness"].default_value = c["roughness"]
            p.subsurface_method = "RANDOM_WALK"
            p.inputs["Subsurface Weight"].default_value = c["sss"]
            p.inputs["Subsurface Radius"].default_value = (1.0, 0.6, 0.4)
            p.inputs["Subsurface Scale"].default_value = 0.001
            done[m.name] = part
    b.notes["mouth_hero"] = done
