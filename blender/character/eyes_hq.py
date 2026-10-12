"""Hero eyes (m1): our own eyeballs in place of the MPFB low-poly eyes.

The fitted MPFB eye gives each eye's centre and radius (sphere fit); the
rest is generated:
  mesh     two UV spheres (segments x rings) with a corneal bulge, front
           axis -Y, polar UVs per eye (u around the axis, half the map per
           eye; v = sqrt(theta / pi) so the iris gets most of the texels),
           skinned to the head bone like the MPFB eyes.
  texture  iris in polar coordinates: pupil, a dark pupillary ring, radial
           fibres (stretched value noise), a brighter collarette, crypts,
           a limbal ring; sclera off-white, warmer toward the corners, with
           fine radial veins and a soft red limbus halo ("slight redness").
  material Principled: albedo texture, roughness from an ORM texture (cornea
           and iris glossy, sclera satin), high specular, so the eye reads
           wet under the key and rim lights. glTF PBR only (no refraction).

Config: cfg["head"]["refine"]["eyes"] (null keeps the MPFB eyes).
"""

import math

import bmesh
import bpy
import numpy as np

from . import head_refine, skin_tex

DEFAULTS = {
    "segments": 48, "rings": 36, "tex_px": 1024,
    "cornea_bulge_mm": 2.2, "cornea_deg": 34.0,
    "pupil_deg": 9.0, "iris_deg": 30.0, "limbus_deg": 2.5,
    "iris": "#4a2e1a", "iris_inner": "#20120a", "iris_outer": "#2e1d10", "collarette": "#7a4e2a",
    "sclera": "#c3b6ae", "sclera_back": "#86675f", "vein": "#a2423a", "vein_amount": 0.5,
    "redness": 0.45,
    "rough_iris": 0.08, "rough_sclera": 0.32, "specular": 0.5,
    "seed": 5,
}


# --- small 2D value noise (periodic in x for the u wrap) --------------------------------------

def _hash(ix, iy, seed):
    h = (ix * 374761393 + iy * 668265263 + seed * 1442695041) & 0xFFFFFFFF
    h = (h ^ (h >> 13)) * 1274126177 & 0xFFFFFFFF
    h = h ^ (h >> 16)
    return (h & 0xFFFF).astype(np.float32) / 65535.0


def vnoise(x, y, period_x, seed):
    """Value noise on an integer lattice, periodic in x with period_x cells."""
    x0 = np.floor(x).astype(np.int64)
    y0 = np.floor(y).astype(np.int64)
    fx = (x - x0).astype(np.float32)
    fy = (y - y0).astype(np.float32)
    sx = fx * fx * (3 - 2 * fx)
    sy = fy * fy * (3 - 2 * fy)
    px = period_x

    def h(dx, dy):
        return _hash((x0 + dx) % px, y0 + dy, seed)
    a = h(0, 0) * (1 - sx) + h(1, 0) * sx
    b = h(0, 1) * (1 - sx) + h(1, 1) * sx
    return a * (1 - sy) + b * sy


def fbm(x, y, period_x, seed, octaves=4):
    out = np.zeros_like(x, dtype=np.float32)
    amp, tot = 1.0, 0.0
    for o in range(octaves):
        out += amp * vnoise(x * (2 ** o), y * (2 ** o), period_x * (2 ** o), seed + o)
        tot += amp
        amp *= 0.5
    return out / tot


# --- geometry ---------------------------------------------------------------------------------

def fit_sphere(pts):
    """Least-squares sphere (centre, radius) through pts (n, 3)."""
    A = np.hstack([2 * pts, np.ones((len(pts), 1))])
    bvec = (pts ** 2).sum(1)
    sol = np.linalg.lstsq(A, bvec, rcond=None)[0]
    c = sol[:3]
    r = math.sqrt(max(sol[3] + c @ c, 1e-12))
    return c, r


def eyeball(bm, centre, radius, side, c, uv_layer, dl, head_gi):
    """Append one eyeball to bm. side: 0 (character's left, +x) or 1."""
    segs, rings = c["segments"], c["rings"]
    bulge = c["cornea_bulge_mm"] * 0.001
    cdeg = math.radians(c["cornea_deg"])
    axis = np.array([0.0, -1.0, 0.0])
    ex = np.array([1.0, 0.0, 0.0])
    ez = np.array([0.0, 0.0, 1.0])
    grid = []
    for i in range(rings + 1):
        th = math.pi * i / rings
        row = []
        r = radius
        if th < cdeg:
            t = 1 - (th / cdeg) ** 2
            r = radius + bulge * max(t, 0.0) ** 1.3
        for j in range(segs):
            ph = 2 * math.pi * j / segs
            d = axis * math.cos(th) + (ex * math.cos(ph) + ez * math.sin(ph)) * math.sin(th)
            v = bm.verts.new(centre + d * r)
            v[dl][head_gi] = 1.0
            row.append(v)
            if i in (0, rings):
                break
        grid.append(row)
    bm.verts.ensure_lookup_table()

    def uv(i, j):
        th = i / rings
        return (((j % segs) / segs) * 0.5 + 0.5 * side, math.sqrt(th))
    for i in range(rings):
        for j in range(segs):
            j1 = (j + 1) % segs
            if i == 0:
                vs = [grid[0][0], grid[1][j], grid[1][j1]]
                uvs = [((j + 0.5) / segs * 0.5 + 0.5 * side, 0.0), uv(1, j), uv(1, j + 1)]
            elif i == rings - 1:
                vs = [grid[i][j], grid[rings][0], grid[i][j1]]
                uvs = [uv(i, j), ((j + 0.5) / segs * 0.5 + 0.5 * side, 1.0), uv(i, j + 1)]
            else:
                vs = [grid[i][j], grid[i + 1][j], grid[i + 1][j1], grid[i][j1]]
                uvs = [uv(i, j), uv(i + 1, j), uv(i + 1, j + 1), uv(i, j + 1)]
            try:
                f = bm.faces.new(vs)
            except ValueError:
                continue
            f.smooth = True
            for l, t in zip(f.loops, uvs):
                l[uv_layer].uv = t
            # fix the u wrap on the seam column
            us = [l[uv_layer].uv.x for l in f.loops]
            if max(us) - min(us) > 0.25:
                for l in f.loops:
                    if l[uv_layer].uv.x < 0.25 + 0.5 * side:
                        l[uv_layer].uv.x += 0.5


# --- texture ----------------------------------------------------------------------------------

def texture(c):
    n = c["tex_px"]
    seed = int(c["seed"])
    H = skin_tex.HEX
    lin = skin_tex.srgb_to_linear
    out = np.zeros((n, n, 3), np.float32)
    rough = np.zeros((n, n), np.float32)
    v = (np.arange(n, dtype=np.float32) + 0.5) / n           # rows: v
    for side in (0, 1):
        cols = slice(side * n // 2, (side + 1) * n // 2)
        u = (np.arange(n // 2, dtype=np.float32) + 0.5) / (n // 2)   # 0..1 around the axis
        U, V = np.meshgrid(u, v)
        theta = np.degrees(V * V * math.pi)                           # angle from the axis
        pd, idg, ld = c["pupil_deg"], c["iris_deg"], c["limbus_deg"]
        # radial coordinate inside the iris 0 (pupil edge) .. 1 (limbus)
        ri = np.clip((theta - pd) / (idg - pd), 0, 1)
        fib = fbm(U * 140, ri * 6 + side * 7, 140, seed + 11, 3)           # radial fibres
        fib2 = fbm(U * 60, ri * 3, 60, seed + 23, 2)
        crypt = fbm(U * 90, ri * 14, 90, seed + 31, 3)
        iris = lin(H(c["iris"]))[None, None] * (0.75 + 0.6 * fib + 0.2 * fib2)[..., None]
        inner = lin(H(c["iris_inner"]))
        outer = lin(H(c["iris_outer"]))
        coll = lin(H(c["collarette"]))
        w_in = skin_tex.gauss(ri, 0.10)
        iris = iris * (1 - w_in[..., None]) + inner[None, None] * w_in[..., None]
        cw = skin_tex.gauss(ri - (0.36 + 0.06 * (fib2 - 0.5)), 0.045) * (0.5 + fib)
        iris = iris * (1 - 0.6 * cw[..., None]) + coll[None, None] * (0.6 * cw)[..., None]
        cr = skin_tex.smoothstep(0.62, 0.72, crypt) * skin_tex.smoothstep(0.35, 0.6, ri)
        iris *= (1 - 0.55 * cr)[..., None]
        w_out = skin_tex.smoothstep(0.55, 1.0, ri) ** 1.5
        iris = iris * (1 - w_out[..., None]) + outer[None, None] * w_out[..., None]
        limb = skin_tex.smoothstep(idg - ld, idg + 0.3, theta)
        iris *= (1 - 0.85 * limb)[..., None]
        # sclera
        back = skin_tex.smoothstep(55.0, 120.0, theta)
        scl = lin(H(c["sclera"]))[None, None] * (1 - back[..., None]) + lin(H(c["sclera_back"]))[None, None] * back[..., None]
        scl *= (0.96 + 0.08 * fbm(U * 12, V * 6, 12, seed + 41, 2))[..., None]
        veins = fbm(U * 90, V * 4 + 0.5, 90, seed + 53, 3)
        veins2 = fbm(U * 30, V * 10, 30, seed + 61, 2)
        vein = skin_tex.smoothstep(0.66, 0.74, veins * 0.75 + veins2 * 0.25) \
            * skin_tex.smoothstep(idg + 4, idg + 20, theta) * skin_tex.smoothstep(130, 75, theta)
        vc = lin(H(c["vein"]))
        scl = scl * (1 - (vein * c["vein_amount"])[..., None]) + vc[None, None] * (vein * c["vein_amount"])[..., None]
        halo = skin_tex.gauss(theta - idg - 3, 4.0) * c["redness"] * (0.6 + 0.4 * veins2)
        scl *= (1 + halo[..., None] * (np.array((1.08, 0.78, 0.76), np.float32) - 1))
        scl *= (1 + (back * 0.0)[..., None])
        # compose
        in_iris = skin_tex.smoothstep(idg + 0.4, idg - 0.4, theta)
        col = iris * in_iris[..., None] + scl * (1 - in_iris)[..., None]
        pupil = skin_tex.smoothstep(pd + 0.8, pd - 0.6, theta)
        col *= (1 - pupil)[..., None]
        col += pupil[..., None] * np.array((0.004, 0.003, 0.003), np.float32)
        out[:, cols] = col
        rough[:, cols] = c["rough_iris"] * skin_tex.smoothstep(c["cornea_deg"] + 2, c["cornea_deg"] - 2, theta) \
            + c["rough_sclera"] * skin_tex.smoothstep(c["cornea_deg"] - 2, c["cornea_deg"] + 2, theta)
    return np.clip(out, 0, 1), np.clip(rough, 0.02, 1)


# --- stage ------------------------------------------------------------------------------------

def build(b):
    rcfg = b.cfg["head"].get("refine") or {}
    c = rcfg.get("eyes")
    if c is None:
        return None
    cfg = dict(DEFAULTS)
    cfg.update(c)
    old = head_refine.find_eyes(b)
    if old is None:
        return None
    co = np.array([(old.matrix_world @ v.co)[:] for v in old.data.vertices])
    arm = b.armature()
    new = bpy.data.objects.new("Human.eyes_hq_export", bpy.data.meshes.new("Human.eyes_hq_export"))
    for col in old.users_collection:
        col.objects.link(new)
    new.parent = old.parent
    new.matrix_parent_inverse = old.matrix_parent_inverse.copy()
    new.matrix_world = old.matrix_world.copy()
    for g in old.vertex_groups:
        new.vertex_groups.new(name=g.name)
    bm = bmesh.new()
    uvl = bm.loops.layers.uv.new("UVMap")
    dl = bm.verts.layers.deform.verify()
    head_gi = new.vertex_groups["head"].index
    fit = {}
    inv = np.array(new.matrix_world.inverted())
    for side, sel in ((0, co[:, 0] > 0), (1, co[:, 0] < 0)):
        pts = co[sel]
        # sphere from the back half (the MPFB eye has a corneal bulge)
        cen0 = pts.mean(0)
        backp = pts[pts[:, 1] > cen0[1]]
        centre, radius = fit_sphere(backp if len(backp) > 12 else pts)
        fit[("left", "right")[side]] = {"centre": [round(float(x), 4) for x in centre], "radius_mm": round(radius * 1000, 2)}
        local = (inv @ np.append(centre, 1.0))[:3]
        eyeball(bm, local, radius, side, cfg, uvl, dl, head_gi)
    bm.to_mesh(new.data)
    bm.free()
    new.data.update()
    for m in old.modifiers:
        if m.type == "ARMATURE":
            mod = new.modifiers.new("Armature", "ARMATURE")
            mod.object = m.object
    # texture + material
    alb, rough = texture(cfg)
    out_dir = b.out_dir if (rcfg.get("skin") or {}).get("save_maps") else None
    ia = skin_tex.make_image("eyes_albedo", alb, True, out_dir)
    io = skin_tex.make_image("eyes_orm", np.stack([np.ones_like(rough), rough, np.zeros_like(rough)], -1), False, out_dir)
    mat = bpy.data.materials.new("eyes_hq")
    mat.use_nodes = True
    nt = mat.node_tree
    p = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    ta = nt.nodes.new("ShaderNodeTexImage")
    ta.image = ia
    nt.links.new(ta.outputs["Color"], p.inputs["Base Color"])
    to = nt.nodes.new("ShaderNodeTexImage")
    to.image = io
    sep = nt.nodes.new("ShaderNodeSeparateColor")
    nt.links.new(to.outputs["Color"], sep.inputs[0])
    nt.links.new(sep.outputs["Green"], p.inputs["Roughness"])
    p.inputs["Specular IOR Level"].default_value = cfg["specular"]
    if "Coat Weight" in p.inputs:
        p.inputs["Coat Weight"].default_value = 0.5   # render-side gloss; glTF clearcoat extension
        p.inputs["Coat Roughness"].default_value = 0.03
    new.data.materials.append(mat)
    # swap
    b.export_objs = [o for o in b.export_objs if o is not old] + [new]
    bpy.data.objects.remove(old, do_unlink=True)
    b.notes["eyes"] = {"fit": fit, "tris": len(new.data.polygons) * 2, "tex_px": cfg["tex_px"]}
    return b.notes["eyes"]
