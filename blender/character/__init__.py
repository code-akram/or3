"""Modular headless character build (m1).

blender/build_character.py drives the stages in this package. Each stage is a
plain function taking the shared Build context; stages that own a part of the
character (suit, head, hair, rig) live in their own module so they can be
worked on independently.

Stage order (see build_character.py):

    pre-staging, on the live MPFB human:
        body.create        base mesh + macros + skin
        head.edit_base     parametric head edits on the base mesh (before fitting)
        rig.add            builtin rig + weights
        head.add_parts     eyes, brows, lashes, teeth, tongue
        hair.add           scalp hair (beard later)
        suit.add           clothes and shoes
    export.stage           copy + bake masks + strip helpers (only what ships remains)
    export.bake_targets    macro shape keys -> mesh (glTF would ship the Basis)
    post-staging, on the staged export objects:
        head.post, hair.post, suit.post, rig.post, budgets.apply
    export.fix_alpha, stats, export.write
"""
