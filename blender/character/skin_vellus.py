"""Hero-only vellus hair (peach fuzz) on the face (skin-direction.md, Track A 5).

About 20k short, fine, light strands, 0.8-2 mm long and 0.008 mm in radius,
with melanin 0.1. Roots follow the skin's fuzz mask (cheeks, forehead, ears and
neck; none in the beard, lips, eyes or scalp), and each root sits on the hero
displacement so the fuzz rides the lumps instead of sinking into them. The
strands lie down toward the jaw and out, and catch the rims at the silhouette.

Cycles only: hair curves in the `hero_only` collection, bound to the head
bone, shaded with the shared Principled Hair BSDF (beard_groom). Nothing
reaches the GLB.
"""

import math

import bpy
import numpy as np

from . import beard_groom

DEFAULTS = {
    "count": 20000,
    "length_mm": (0.8, 2.0),
    "radius_mm": 0.008, "tip_radius": 0.5,
    "points": 4,
    "elev_deg": (25.0, 8.0), "elev_sigma_deg": 6.0, "yaw_sigma_deg": 25.0, "curl_sigma_deg": 15.0,
    "lift_mm": 0.03,
    "melanin": 0.10, "melanin_sigma": 0.03, "redness": 0.30,
    "material": {"roughness": 0.35, "radial_roughness": 0.3, "coat": 0.0, "root_dark": 0.0},
    "seed": 23,
}


def _pixels(img, channel):
    w, h = img.size
    px = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(px)
    return px.reshape(h, w, 4)[..., channel].copy()


def _sample(arr, uv):
    h, w = arr.shape
    x = np.clip((uv[:, 0] % 1.0) * w, 0, w - 1).astype(np.int64)
    y = np.clip((uv[:, 1] % 1.0) * h, 0, h - 1).astype(np.int64)
    return arr[y, x]


def build(b, cfg=None):
    c = dict(DEFAULTS)
    c.update(cfg or {})
    data = getattr(b, "skin_hero", None)
    if not data or c["count"] <= 0:
        return None
    body = bpy.data.objects.get(data["body"])
    head = data.get("head") or {}
    if body is None or "mask_hero" not in head:
        return None
    me = body.data
    uv_layer = me.uv_layers.active
    nv = len(me.vertices)
    # per-vertex fuzz and hero height (mm) from the head maps (head slot only)
    fuzz_img = _pixels(head["mask_hero"], 1)
    hgt_img = _pixels(head["height_mm"], 0) if "height_mm" in head else None
    loop_v = np.empty(len(me.loops), np.int64)
    me.loops.foreach_get("vertex_index", loop_v)
    luv = np.empty(len(me.loops) * 2, np.float32)
    uv_layer.data.foreach_get("uv", luv)
    luv = luv.reshape(-1, 2)
    mat_idx = np.empty(len(me.polygons), np.int64)
    me.polygons.foreach_get("material_index", mat_idx)
    loop_start = np.empty(len(me.polygons), np.int64)
    me.polygons.foreach_get("loop_start", loop_start)
    loop_total = np.empty(len(me.polygons), np.int64)
    me.polygons.foreach_get("loop_total", loop_total)
    loop_poly = np.repeat(np.arange(len(me.polygons)), loop_total)
    head_loop = mat_idx[loop_poly] == 0
    fz = np.zeros(nv, np.float32)
    np.maximum.at(fz, loop_v[head_loop], _sample(fuzz_img, luv[head_loop]))
    hg = np.zeros(nv, np.float32)
    if hgt_img is not None:
        cnt = np.zeros(nv, np.float32)
        np.add.at(hg, loop_v[head_loop], _sample(hgt_img, luv[head_loop]))
        np.add.at(cnt, loop_v[head_loop], 1.0)
        hg = hg / np.maximum(cnt, 1.0)
    del fuzz_img, hgt_img
    # rest-pose world positions and normals
    rest = me.attributes.get("hero_rest")
    co = np.empty(nv * 3, np.float32)
    if rest is not None:
        rest.data.foreach_get("vector", co)
        co = co.reshape(-1, 3).astype(np.float64)
    else:
        me.vertices.foreach_get("co", co)
        mw = np.array(body.matrix_world)
        co = co.reshape(-1, 3) @ mw[:3, :3].T + mw[:3, 3]
    me.calc_loop_triangles()
    tv = np.empty(len(me.loop_triangles) * 3, np.int64)
    me.loop_triangles.foreach_get("vertices", tv)
    tv = tv.reshape(-1, 3)
    # normals of the rest surface itself (area-weighted), so roots match hero_rest
    fn = np.cross(co[tv[:, 1]] - co[tv[:, 0]], co[tv[:, 2]] - co[tv[:, 0]])
    nrm = np.zeros((nv, 3))
    for j in range(3):
        np.add.at(nrm, tv[:, j], fn)
    nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12)
    # patch: head-slot triangles that carry fuzz
    tp = np.empty(len(me.loop_triangles), np.int64)
    me.loop_triangles.foreach_get("polygon_index", tp)
    keep = (mat_idx[tp] == 0) & (fz[tv].max(1) > 0.02)
    tris = tv[keep]
    a = co[tris[:, 1]] - co[tris[:, 0]]
    bb = co[tris[:, 2]] - co[tris[:, 0]]
    area = 0.5 * np.linalg.norm(np.cross(a, bb), axis=1)
    per_m2 = c["count"] / max(float((area * fz[tris].mean(1)).sum()), 1e-9)
    rng = np.random.default_rng(c["seed"])
    pos, n, fields = beard_groom.sample_roots(co, nrm, tris, {"density": np.clip(fz, 0, 1), "hgt": hg},
                                              per_m2, rng)
    m = len(pos)
    if m == 0:
        return None
    # sit on the displaced skin (+ a hair's clearance)
    pos = pos + n * ((fields["hgt"] + c["lift_mm"]) * 0.001)[:, None]
    # lie down toward the jaw and outward
    cx = float(np.median(co[:, 0]))
    comb = np.stack([np.sign(pos[:, 0] - cx) * 0.5, np.zeros(m), -np.ones(m)], 1)
    deg = math.radians
    L = rng.uniform(*c["length_mm"], m) * 0.001
    e0 = deg(c["elev_deg"][0]) + rng.normal(0, deg(c["elev_sigma_deg"]), m)
    e1 = deg(c["elev_deg"][1]) + rng.normal(0, deg(c["elev_sigma_deg"]) * 0.5, m)
    yaw = rng.normal(0, deg(c["yaw_sigma_deg"]), m)
    curl = rng.normal(0, deg(c["curl_sigma_deg"]), m)
    k = int(c["points"])
    pts = beard_groom.grow(pos, n, comb, L, e0, e1, yaw, curl, k)
    rad = np.linspace(1.0, c["tip_radius"], k)[None, :] * np.full((m, 1), c["radius_mm"] * 0.001)
    mel = np.clip(c["melanin"] + rng.normal(0, c["melanin_sigma"], m), 0, 1)
    red = np.full(m, c["redness"])
    mat = beard_groom.hair_material("vellus_hero", c["material"])
    obj = beard_groom.make_curves("skin_vellus_hero", pts, rad, {"melanin": mel, "redness": red}, mat)
    beard_groom.bind(b, obj, "head")
    note = {"strands": int(m), "per_cm2_peak": round(per_m2 / 1e4, 1),
            "length_mm": list(c["length_mm"]), "radius_mm": c["radius_mm"]}
    b.notes["skin_vellus"] = note
    print(f"[vellus] {m} strands", flush=True)
    return note
