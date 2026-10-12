"""Base body: MPFB human from macros, detail targets, plus skin."""


def load_targets(b, targets):
    """Load MPFB detail targets ({target file stem: weight}) as shape keys on
    the live human, e.g. {"measure-shoulder-dist-incr": 0.3}. A weight of
    0 or null skips the entry. "lr-<stem>" loads the mirrored pair
    l-<stem> and r-<stem> at the same weight (the face stays symmetric)."""
    ts = b.mpfb.TargetService
    for key, weight in (targets or {}).items():
        if not weight:
            continue
        names = [s + key[2:] for s in ("l", "r")] if key.startswith("lr-") else [key]
        for name in names:
            path = ts.target_full_path(name)
            if path is None or not path.split("/")[-1].startswith(name + ".target"):
                raise RuntimeError(f"MPFB target {name!r} not found")
            ts.load_target(b.basemesh, path, weight=float(weight), name=name)


def create(b):
    c = b.cfg["body"]
    macro = b.mpfb.TargetService.get_default_macro_info_dict()
    macro.update(c["macros"])
    macro["race"] = dict(c["race"])
    b.basemesh = b.mpfb.HumanService.create_human(macro_detail_dict=macro)
    load_targets(b, c.get("targets"))
    b.mpfb.HumanService.set_character_skin(
        b.mpfb.find(c["skin"], "skins"), b.basemesh, skin_type="GAMEENGINE")
