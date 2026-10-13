"""Fingernails as geometry (m1 v2 Track G).

The MPFB body only marks the nails with a vertex group ("fingernails"): a
flat patch of skin. This stage builds a separate nail-plate mesh on top of
it, in the GLB (game) and the hero renders alike:

  plate      the body's nail faces (weight > 0.5), one island per digit,
             lifted along the normal: `plate_mm` in the middle, easing to
             `edge_mm` at the proximal and lateral borders, so the plate
             rises out of the cuticle and the lateral folds instead of
             floating on them;
  free edge  the distal border carried on over the skin to the fingertip
             (`reach`, still nail bed) and then `overhang_mm` past it with a
             slight downward curve,
             a thickness (`thick_mm`) and an underside, so the nail has a
             real edge and silhouette;
  UVs        one layout for every nail (u across, v proximal -> free edge;
             thumbs use the right half of the texture), so all ten share a
             small generated texture: nail bed pink, a lunula (larger on the
             thumbs), the onychodermal band, an off-white free edge, fine
             longitudinal ridges in the normal map; roughness lower than the
             skin (0.22 on the plate);
  weights    copied from the body vertex each plate vertex came from, after
             rig.post (so they match the body's final finger weights);
             <= 4 influences like the body.

hero(): a Cycles-only variant of the material (a thin glossy coat and a
little subsurface: the plate is translucent), swapped in after the GLB export.

Build stages (blender/build_character.py): `hand_nails` after rig_post,
`hand_nails_hero` after export_glb. Config `hands.nails` (null disables).
"""

import bmesh
import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from . import head_refine as hr

NAILS = {
    "plate_mm": 0.40, "edge_mm": 0.06,
    "reach_min_mm": 0.4, "reach_max_mm": 2.5, "overhang_mm": 0.55, "overhang_thumb_mm": 0.75,
    "thick_mm": 0.45, "curl_mm": 0.2, "tex_px": 512,
    "bed": "#c79a8c", "lunula": "#d8bcb0", "free": "#dccbbb", "band": "#b07e70",
    "lunula_finger": 0.35, "lunula_thumb": 0.65, "ridges": 0.010, "ridge_normal": 0.012,
    "rough": 0.22, "rough_free": 0.34,
}
NAME = "hand_nails"
DIGITS = ("thumb", "index", "middle", "ring", "pinky")


def _islands(faces, polys):
    """Connected components (sharing vertices) of the given face indices."""
    parent = {f: f for f in faces}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    by_v = {}
    for f in faces:
        for v in polys[f]:
            by_v.setdefault(v, []).append(f)
    for fs in by_v.values():
        for f in fs[1:]:
            ra, rb = find(fs[0]), find(f)
            if ra != rb:
                parent[rb] = ra
    out = {}
    for f in faces:
        out.setdefault(find(f), []).append(f)
    return list(out.values())


def _digit_of(c, arm):
    """(digit, side) of the distal phalanx nearest to point c (rest, world)."""
    mw = arm.matrix_world
    best = None
    for s in ("l", "r"):
        for d in DIGITS:
            b = arm.data.bones.get(f"{d}_03_{s}")
            if b is None:
                continue
            h, t = mw @ b.head_local, mw @ b.tail_local
            ab = t - h
            k = max(0.0, min(1.0, (Vector(c) - h).dot(ab) / max(ab.length_squared, 1e-12)))
            dist = (Vector(c) - (h + ab * k)).length
            if best is None or dist < best[0]:
                best = (dist, d, s, h, t)
    return best[1], best[2], np.array(best[3][:]), np.array(best[4][:])


def _smooth01(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


def build_mesh(body, arm, c):
    """Returns (verts, faces, uvs per face-corner, source body vertex per
    vertex, info)."""
    me = body.data
    co = hr.coords(body)
    nr = hr.normals(body)
    w = hr.group_weights(body, "fingernails")
    polys = [tuple(p.vertices) for p in me.polygons]
    sel = [i for i, p in enumerate(polys) if all(w[v] > 0.5 for v in p)]
    islands = [isl for isl in _islands(sel, polys) if len(isl) >= 4]
    bvh = BVHTree.FromPolygons([Vector(p) for p in co], polys)
    mm = 0.001
    V, F, UV, SRC, HINT = [], [], [], [], []   # HINT: the outward direction of each face
    info = []
    # skin of each distal phalanx: to find the fingertip
    dom = hr.dominant_bones(body, set(arm.data.bones.keys()))
    for isl in islands:
        vids = sorted({v for f in isl for v in polys[f]})
        P = co[vids]
        cen = P.mean(0)
        digit, side, bh, bt = _digit_of(cen, arm)
        u_ax = (bt - bh) / np.linalg.norm(bt - bh)
        n_ax = nr[vids].mean(0)
        n_ax -= u_ax * n_ax.dot(u_ax)
        n_ax /= np.linalg.norm(n_ax)
        w_ax = np.cross(n_ax, u_ax)
        s = (P - cen) @ u_ax
        t = (P - cen) @ w_ax
        s0, s1 = s.min(), s.max()
        tmax = np.abs(t).max()
        S = (s - s0) / max(s1 - s0, 1e-9)
        T = t / max(tmax, 1e-9)
        # boundary vertices of the island
        edge_count = {}
        for f in isl:
            p = polys[f]
            for a, b in zip(p, p[1:] + p[:1]):
                k = (a, b) if a < b else (b, a)
                edge_count[k] = edge_count.get(k, 0) + 1
        bnd = {v for e, n in edge_count.items() if n == 1 for v in e}
        local = {v: i for i, v in enumerate(vids)}
        is_b = np.array([v in bnd for v in vids])
        distal = is_b & (S > 0.6) & (np.abs(T) < 0.85)
        # plate lift: plate_mm inside, edge_mm on the proximal / lateral border
        inner = np.ones(len(vids))
        inner[is_b & ~distal] = 0.0
        lift = c["edge_mm"] + (c["plate_mm"] - c["edge_mm"]) * inner
        # second ring in from the border: halfway, so the rise is a bevel
        ring = set()
        for f in isl:
            p = polys[f]
            if any(v in bnd and not distal[local[v]] for v in p):
                ring.update(v for v in p if v not in bnd)
        for v in ring:
            lift[local[v]] = c["edge_mm"] + (c["plate_mm"] - c["edge_mm"]) * 0.7
        top = P + nr[vids] * (lift * mm)[:, None]
        base = len(V)
        V.extend(top.tolist())
        SRC.extend(vids)
        # fingertip: the furthest skin point of this phalanx along the axis
        tipmask = dom == f"{digit}_03_{side}"
        tip_s = float(((co[tipmask] - cen) @ u_ax).max()) if tipmask.any() else s1
        # the plate runs on over the skin to the fingertip (reach, still nail
        # bed: pink) and then overhangs it (the free edge, off-white)
        thumb = digit == "thumb"
        reach = float(np.clip(tip_s - s1, c["reach_min_mm"] * mm, c["reach_max_mm"] * mm))
        free = reach + c["overhang_thumb_mm" if thumb else "overhang_mm"] * mm
        uoff = 0.5 if thumb else 0.0
        vmax_bed = 0.80
        sc = (s1 - s0) / (s1 - s0 + reach)

        def uv_of(Si, Ti, ext=0.0):
            if ext <= 0.0:
                v = vmax_bed * Si * sc
            elif ext <= 0.5:
                v = vmax_bed * (sc + (1 - sc) * ext / 0.5)
            else:
                v = vmax_bed + (1 - vmax_bed) * (ext - 0.5) / 0.5
            return (uoff + 0.5 * (0.04 + 0.92 * (Ti + 1) * 0.5), v)
        for f in isl:
            idx = [base + local[v] for v in polys[f]]
            F.append(idx)
            UV.append([uv_of(S[local[v]], T[local[v]]) for v in polys[f]])
            HINT.append(nr[list(polys[f])].mean(0))
        # free edge: rows off the distal border, ordered along T
        dv = [vids[i] for i in np.where(distal)[0]]
        dv.sort(key=lambda v: T[local[v]])
        if len(dv) >= 2:
            rows = []
            for k, frac in enumerate((reach / free, 1.0)):
                row = []
                for v in dv:
                    i = local[v]
                    nv = nr[v]
                    ut = u_ax - nv * u_ax.dot(nv)
                    ut /= np.linalg.norm(ut)
                    p = top[i] + ut * free * frac - nv * c["curl_mm"] * mm * frac ** 2
                    # keep clear of the fingertip skin
                    hit = bvh.find_nearest(Vector(p))
                    if hit[0] is not None:
                        q = np.array(hit[0][:])
                        gap = (p - q) @ np.array(hit[1][:])
                        if gap < 0.25 * mm:
                            p = p + np.array(hit[1][:]) * (0.25 * mm - gap)
                    row.append(len(V))
                    V.append(p.tolist())
                    SRC.append(v)
                rows.append(row)
            first = [base + local[v] for v in dv]
            allrows = [first] + rows
            for r0, r1, e0, e1 in zip(allrows[:-1], allrows[1:], (0.0, 0.5), (0.5, 1.0)):
                for j in range(len(dv) - 1):
                    Ta, Tb = T[local[dv[j]]], T[local[dv[j + 1]]]
                    F.append([r0[j], r0[j + 1], r1[j + 1], r1[j]])
                    UV.append([uv_of(1.0, Ta, e0), uv_of(1.0, Tb, e0), uv_of(1.0, Tb, e1), uv_of(1.0, Ta, e1)])
                    HINT.append(nr[[dv[j], dv[j + 1]]].mean(0))
            # underside (thickness), reversed winding, and the rim
            under = []
            for r in allrows:
                ur = []
                for vi in r:
                    src = SRC[vi]
                    p = np.array(V[vi]) - nr[src] * c["thick_mm"] * mm
                    ur.append(len(V))
                    V.append(p.tolist())
                    SRC.append(src)
                under.append(ur)
            for r0, r1, e0, e1 in zip(under[:-1], under[1:], (0.0, 0.5), (0.5, 1.0)):
                for j in range(len(dv) - 1):
                    Ta, Tb = T[local[dv[j]]], T[local[dv[j + 1]]]
                    F.append([r0[j], r1[j], r1[j + 1], r0[j + 1]])
                    UV.append([uv_of(1.0, Ta, e0), uv_of(1.0, Ta, e1), uv_of(1.0, Tb, e1), uv_of(1.0, Tb, e0)])
                    HINT.append(-nr[[dv[j], dv[j + 1]]].mean(0))
            r_top, r_bot = allrows[-1], under[-1]
            for j in range(len(dv) - 1):
                Ta, Tb = T[local[dv[j]]], T[local[dv[j + 1]]]
                F.append([r_top[j], r_bot[j], r_bot[j + 1], r_top[j + 1]])
                UV.append([uv_of(1.0, Ta, 1.0)] * 2 + [uv_of(1.0, Tb, 1.0)] * 2)
                HINT.append(u_ax)
            # lateral ends of the free edge: close them (top row -> underside)
            for j in (0, len(dv) - 1):
                tj = T[local[dv[j]]]
                for r0, r1, u0, u1 in zip(allrows[:-1], allrows[1:], under[:-1], under[1:]):
                    quad = [r0[j], r1[j], u1[j], u0[j]] if j == 0 else [r0[j], u0[j], u1[j], r1[j]]
                    F.append(quad)
                    UV.append([uv_of(1.0, tj, 0.5)] * 4)
                    HINT.append(w_ax if j else -w_ax)
        info.append({"digit": f"{digit}_{side}", "faces": len(isl), "free_mm": round(free * 1000, 2),
                     "len_mm": round((s1 - s0) * 1000, 1), "width_mm": round(2 * tmax * 1000, 1)})
    return V, F, UV, SRC, HINT, info


def textures(c):
    """Shared nail texture (albedo sRGB-linear, roughness, normal), square.
    Left half: fingers; right half: thumbs (larger lunula)."""
    from .skin_synth import HEX, srgb_to_linear, gauss, smoothstep
    n = int(c["tex_px"])
    y, x = np.mgrid[0:n, 0:n].astype(np.float32) / (n - 1)
    v = y                   # image rows run bottom-up in Blender: v = 0 at the proximal edge
    thumb = x >= 0.5
    u = np.where(thumb, (x - 0.5) * 2, x * 2)        # 0..1 across the nail
    acr = (u - 0.5) * 2                               # -1..1
    bed, lun, free, band = (srgb_to_linear(HEX(c[k])) for k in ("bed", "lunula", "free", "band"))
    rng = np.random.default_rng(5)
    stripes = np.zeros_like(u)
    for k in range(9):
        stripes += np.sin(2 * np.pi * (u * (11 + 7 * rng.random()) + rng.random())) * (0.5 + rng.random()) / 9
    alb = np.ones((n, n, 3), np.float32) * bed
    alb *= (1 + c["ridges"] * stripes)[..., None]
    # lateral shadow (the plate thickens and dives into the lateral folds) and
    # a slightly darker proximal band where the cuticle overlaps
    alb *= (1 - 0.18 * smoothstep(0.55, 1.0, np.abs(acr)))[..., None]
    alb *= (1 - 0.15 * smoothstep(0.06, 0.0, v))[..., None]
    # lunula: a crescent at the proximal edge
    rx = np.where(thumb, 0.62, 0.48)
    ry = np.where(thumb, 0.30, 0.17)
    lun_d = np.sqrt((acr / rx) ** 2 + (v / ry) ** 2)
    lw = smoothstep(1.05, 0.9, lun_d) * smoothstep(0.0, 0.03, v)
    lw = lw * np.where(thumb, c["lunula_thumb"], c["lunula_finger"])
    alb = alb * (1 - lw[..., None]) + lun * lw[..., None]
    # onychodermal band and the free edge (v > 0.8 is past the bed)
    fe = smoothstep(0.785, 0.815, v)
    bw = gauss(v - 0.79, 0.008) * (1 - 0.4 * np.abs(acr))
    alb = alb * (1 - bw[..., None] * 0.5) + band * (bw[..., None] * 0.5)
    alb = alb * (1 - fe[..., None]) + free * (1 + 0.02 * stripes)[..., None] * fe[..., None]
    alb = np.clip(alb, 0, 1)
    rough = (c["rough"] + 0.04 * smoothstep(0.06, 0.0, v) + (c["rough_free"] - c["rough"]) * fe
             + 0.02 * stripes).astype(np.float32)
    occl = (1 - 0.25 * smoothstep(0.08, 0.0, v) - 0.2 * smoothstep(0.7, 1.0, np.abs(acr))).astype(np.float32)
    # longitudinal ridges in tangent space (ridges run along v)
    nx = -c["ridge_normal"] * np.gradient(stripes, axis=1) * n / 20.0
    nrm = np.stack([nx, np.zeros_like(nx), np.ones_like(nx)], -1)
    nrm /= np.linalg.norm(nrm, axis=-1, keepdims=True)
    return alb, rough, occl, nrm * 0.5 + 0.5


def build(b):
    """Build stage, after rig_post."""
    hc = b.cfg.get("hands", {}) if "hands" in b.cfg else {}
    if hc is None:
        return None
    c = dict(NAILS)
    if "nails" in (hc or {}) and hc["nails"] is None:
        return None
    c.update((hc or {}).get("nails") or {})
    body = hr.staged_body(b)
    arm = b.armature()
    V, F, UV, SRC, HINT, info = build_mesh(body, arm, c)
    if not F:
        b.notes.setdefault("hands", {})["nails"] = {"nails": 0}
        return None
    me = bpy.data.meshes.new(NAME)
    me.from_pydata([tuple(p) for p in V], [], [tuple(f) for f in F])
    me.update()
    uvl = me.uv_layers.new(name="UVMap")
    k = 0
    for p, uvs in zip(me.polygons, UV):
        for li, uv in zip(p.loop_indices, uvs):
            uvl.data[li].uv = uv
        k += 1
    for p in me.polygons:
        p.use_smooth = True
    # every face faces its outward hint (plate up, underside down, rim forward)
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.normal_update()
    bm.faces.ensure_lookup_table()
    flip = [bm.faces[i] for i, hnt in enumerate(HINT) if bm.faces[i].normal.dot(Vector(hnt)) < 0]
    if flip:
        bmesh.ops.reverse_faces(bm, faces=flip)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(f"Human.{NAME}_export", me)
    for col in body.users_collection:
        col.objects.link(ob)
    ob.parent = body.parent
    ob.matrix_parent_inverse = body.matrix_parent_inverse.copy()
    ob.matrix_world = body.matrix_world.copy()
    # weights: the body's (final, after rig.post) per source vertex
    names = {g.index: g.name for g in body.vertex_groups}
    bones = set(arm.data.bones.keys())
    groups = {}
    bw = [[(names[g.group], g.weight) for g in v.groups if names.get(g.group) in bones and g.weight > 1e-4]
          for v in body.data.vertices]
    for i, src in enumerate(SRC):
        for gname, wt in bw[src]:
            if gname not in groups:
                groups[gname] = ob.vertex_groups.new(name=gname)
            groups[gname].add([i], wt, "REPLACE")
    mod = ob.modifiers.new("Armature", "ARMATURE")
    mod.object = arm
    b.export_objs.append(ob)
    # material: the shared generated texture
    from . import skin_tex
    alb, rough, occl, nrm = textures(c)
    out_dir = b.out_dir if ((b.cfg["head"].get("refine") or {}).get("skin") or {}).get("save_maps") else None
    z = np.zeros_like(rough)
    imgs = {"albedo": skin_tex.make_image("nails_albedo", alb, True, out_dir),
            "orm": skin_tex.make_image("nails_orm", np.stack([occl, rough, z], -1), False, out_dir),
            "normal": skin_tex.make_image("nails_normal", nrm, False, out_dir)}
    m = skin_tex.skin_material("nails", imgs["albedo"], imgs["orm"], imgs["normal"], 0.0)
    me.materials.append(m)
    b.nails_hero = {"obj": ob.name, "imgs": imgs}
    note = {"nails": len(info), "tris": sum(len(f) - 2 for f in F), "verts": len(V), "per_nail": info}
    b.notes.setdefault("hands", {})["nails"] = note
    return note


HERO = {"coat": 0.35, "coat_roughness": 0.08, "sss": 0.25, "sss_radius": (1.0, 0.45, 0.3), "sss_scale": 0.0006}


def hero(b):
    """Cycles-only nail material (after the GLB export): a thin glossy coat
    over the plate and a little subsurface (the plate is translucent)."""
    data = getattr(b, "nails_hero", None)
    if not data:
        return None
    ob = bpy.data.objects.get(data["obj"])
    if ob is None:
        return None
    h = dict(HERO)
    m = ob.data.materials[0].copy()
    m.name = "nails_hero"
    p = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    p.inputs["Coat Weight"].default_value = h["coat"]
    p.inputs["Coat Roughness"].default_value = h["coat_roughness"]
    p.subsurface_method = "RANDOM_WALK"
    p.inputs["Subsurface Weight"].default_value = h["sss"]
    p.inputs["Subsurface Radius"].default_value = h["sss_radius"]
    p.inputs["Subsurface Scale"].default_value = h["sss_scale"]
    ob.data.materials[0] = m
    return {"material": m.name}
