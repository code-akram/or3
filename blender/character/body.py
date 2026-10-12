"""Base body: MPFB human from macros, plus skin."""


def create(b):
    c = b.cfg["body"]
    macro = b.mpfb.TargetService.get_default_macro_info_dict()
    macro.update(c["macros"])
    macro["race"] = dict(c["race"])
    b.basemesh = b.mpfb.HumanService.create_human(macro_detail_dict=macro)
    b.mpfb.HumanService.set_character_skin(
        b.mpfb.find(c["skin"], "skins"), b.basemesh, skin_type="GAMEENGINE")
