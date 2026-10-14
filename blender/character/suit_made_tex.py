"""Surfaces of the made (pattern-drafted) jacket (m1 v4 T13 phase B item 2).

The made jacket (suit_detail.build, suit_rever.build) carries UVs from its pattern: every face
corner at its panel's flat coordinates in metres, the grain up the panel (v), the right-hand
copies mirrored so the twill has one handedness on the outside; the turned edges continue the
panel's UVs round the half round; the pockets are cut on the front's grain; the top collar has
its grain up the centre back and the lapel facings along the front edge. Each face has a panel
tag, one atlas rectangle per (object, tag). This module puts the UVs and tags on the Blender
objects and hands them to suit_textures (the lofted suit's atlas packing, height marks, normal,
albedo and ORM maps, materials), so both jackets share one surface pipeline:

    wool    outside, turned edges, facings and turn-ups, pockets, collar and lapels, the
            buttonhole cord (part 0 and 2): the baked atlas (marks, slubs, cavity, per-panel
            roughness) + the engine's tiled twill detail (suit_textures.detail_record)
    lining  the inside (part 1): plain, glossier
    button  part 3

Marks (suit_textures.draw_marks kinds, registered by the builders): pressed-open seams
(groove, no stitching), dart legs, pick stitching in from the fronts' and the rever's free
edges, the gorge seam, the purl round the buttonhole cord.
"""

import numpy as np

from . import suit_textures as st

DEFAULTS = {
    "px": 2048,                  # the wool atlas (suit.DEFAULTS textures.wool_px)
    "seed": 3,
    "slope": 1.0,
    # a viscose twill lining: black, smoother and glossier than the wool
    "lining": {"albedo": [0.010, 0.010, 0.012], "rough": 0.34, "sheen": 0.2, "sheen_rough": 0.3,
               "sheen_tint": [0.8, 0.85, 1.0], "spec": 0.45},
    # roughness offsets per (object key, tag label): the pressed lapel facings and top collar
    "panel_rough": {("rever", "lapel"): -0.10, ("rever", "lapel_r"): -0.10, ("rever", "collar"): -0.05},
}


def set_uv(ob, UV, tag):
    """UV layer from per-face corner UVs (aligned with the mesh's polygons, from_pydata order)
    and the "panel" face tag."""
    me = ob.data
    lay = me.uv_layers.get("UVMap") or me.uv_layers.new(name="UVMap")
    flat = np.concatenate([np.asarray(u, float).reshape(-1, 2) for u in UV])
    if len(flat) != len(me.loops):
        raise ValueError(f"{ob.name}: {len(flat)} UVs for {len(me.loops)} loops")
    lay.data.foreach_set("uv", flat.astype(np.float32).ravel())
    a = me.attributes.get("panel") or me.attributes.new("panel", "INT", "FACE")
    a.data.foreach_set("value", [int(t) for t in tag])


def uv_stats(ob, side=1.0):
    """Texel-density check: UV area (x side^2: metric) / 3D area per face (1 = the panel's own
    size), and the faces whose UVs wind clockwise (the insides, which carry the outside's UVs
    reversed)."""
    me = ob.data
    uv = np.zeros(len(me.loops) * 2, np.float32)
    me.uv_layers["UVMap"].data.foreach_get("uv", uv)
    uv = uv.reshape(-1, 2)
    co = np.zeros(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    a3, a2 = [], []
    for p in me.polygons:
        li = list(p.loop_indices)
        vi = list(p.vertices)
        for k in range(1, len(li) - 1):
            P = co[[vi[0], vi[k], vi[k + 1]]]
            U = uv[[li[0], li[k], li[k + 1]]]
            a3.append(0.5 * np.linalg.norm(np.cross(P[1] - P[0], P[2] - P[0])))
            e1, e2 = U[1] - U[0], U[2] - U[0]
            a2.append(0.5 * (e1[0] * e2[1] - e1[1] * e2[0]))
    a3, a2 = np.array(a3), np.array(a2)
    m = a3 > 1e-10
    r = np.abs(a2[m]) * side * side / a3[m]
    return {"area_ratio_p05": round(float(np.percentile(r, 5)), 3), "area_ratio_med": round(float(np.median(r)), 3),
            "area_ratio_p95": round(float(np.percentile(r, 95)), 3), "uv_cw_frac": round(float((a2 < 0).mean()), 4)}


def apply(objs, marks, tags, buttons, suit_o, opts=None):
    """objs: {key: object} with UVs and panel tags (set_uv); marks: {key: {tag: [marks]}} in each
    tag's UV metres; tags: {key: {tag: label}}; buttons: objects with only the button
    material; suit_o: suit.DEFAULTS (materials, surface). Materials by the face attribute
    "part" (0 wool, 1 lining, 2 edge (wool), 3 button). Returns stats."""
    o = dict(DEFAULTS, **(opts or {}))
    obs = list(objs.values())
    side, layout = st.pack_group(obs, o["px"])
    H = st.Height(o["px"], side, seed=o["seed"])
    H.weave(st.WEAVE["wool"])
    flat = {}
    for k, d in marks.items():
        if k in objs:
            for t, lst in d.items():
                flat[(objs[k].name, t)] = lst
    st.draw_marks(H, layout, flat, side)
    img = H.normal_image("t13_wool_normal", slope=o["slope"])
    spec = suit_o["materials"]["wool"]
    wool = st.material("t13_wool", **spec)
    st.attach_normal_map(wool, img, strength=1.0)
    wool["suit_atlas_side_m"] = side
    detail = st.detail_record(wool, side, st.WEAVE["wool"])
    S = dict(suit_o["surface"])
    S["panel_rough"] = {f"{objs[k].name}:{t}": v for (k, lab), v in o["panel_rough"].items() if k in objs
                        for t, l2 in tags.get(k, {}).items() if l2 == lab}
    ai, oi, surf = st.surface_maps(H, layout, side, spec, S, "t13_wool")
    st.attach_surface(wool, ai, oi)
    lining = st.material("t13_lining", **o["lining"])
    button = st.material("t13_button", **suit_o["materials"]["button"])
    _, gmax = st.twill_tile(slope=o["slope"])
    for ob in obs + list(buttons):
        me = ob.data
        me.materials.clear()
        for m in (wool, lining, wool, button):
            me.materials.append(m)
        a = me.attributes.get("part")
        vals = np.zeros(len(me.polygons), np.int32)
        if a is not None:
            a.data.foreach_get("value", vals)
        me.polygons.foreach_set("material_index", vals)
    return {"px": o["px"], "atlas_side_m": round(side, 4), "mm_per_px": round(1000 * side / o["px"], 3),
            "rects": len(layout), "marks": sum(len(v) for v in flat.values()), "surface": surf,
            "weave_detail": detail, "tile_max_slope": round(gmax, 4),
            "uv": {k: uv_stats(ob, side) for k, ob in objs.items()}}
