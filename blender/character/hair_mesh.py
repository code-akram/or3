"""Mesh plumbing shared by the hair and beard generators: body-derived shells,
tapered clump tubes, curved alpha cards, generated strand textures, skinning
to the staged rig, and the look-dev materials."""

import math

import bmesh
import bpy
import numpy as np
from mathutils import Vector


def srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hex_rgb(hex_srgb):
    return np.array([int(hex_srgb[i:i + 2], 16) / 255 for i in (1, 3, 5)])


def strand_image(name, cfg, kind):
    """Generated strand texture (our own synthesis, packed into the GLB).

    Strands run along v (image rows). Each has its own value (lighter and
    darker strands), width and a slight wave, over a darker base, so a clump
    reads as many hairs rather than one smooth surface.
      kind "tip":  v = root (0) -> tip (1). Opaque core up to core_v; above
                   it only the strands, each ending at its own length, so
                   alpha-tested tips feather into separate hairs.
      kind "edge": v = depth into the beard from its outer edge (0). Short
                   slanted strands (beard hairs, len_px long) at random
                   depths; those starting in the edge band (sparser and
                   shorter toward the outer edge: stubble) feather the
                   boundary, the rest give the interior its grain. Each
                   strand's outer end is pointed.
    u wraps (REPEAT); v is clamped by the UVs. sRGB values are written
    directly (byte image)."""
    w, h = cfg["size"]
    rng = np.random.default_rng(cfg["seed"])
    ys = np.arange(h)[:, None]
    xs = np.arange(w)[None, :]
    base = hex_rgb(cfg["color"])
    alpha = np.zeros((h, w))
    val = np.full((h, w), cfg["base_value"])
    # Low-frequency value bands across u, so clumps (which see different u
    # ranges) differ a little in value.
    val *= 1 + cfg["band_amp"] * np.sin(2 * np.pi * (xs / w) + rng.uniform(0, 6.3))
    # Card atlas: `variants` lock patterns side by side across u, each with
    # its own value level and its own 1-3 sub-locks (strands cluster round
    # the lock centres, leaving see-through gaps), so a card reads as a few
    # thin piecey locks and neighbouring cards differ. The caller picks a
    # variant by u range (card(..., u_range)).
    variants = cfg.get("variants", 1) if kind == "card" else 1
    wv = w / variants
    lock_specs = []
    if kind == "card" and "locks" in cfg:
        for k in range(variants):
            n_locks = int(rng.integers(cfg["locks"][0], cfg["locks"][1] + 1))
            level = rng.lognormal(0, cfg.get("variant_sigma", 0.0))
            val[:, int(k * wv):int((k + 1) * wv)] *= level
            locks = []
            for j in range(n_locks):
                cx = (k + 0.15 + 0.7 * (j + rng.uniform(0.3, 0.7)) / n_locks) * wv
                locks.append((cx, rng.uniform(*cfg["tip_v"]), rng.uniform(0, cfg["root_v"])))
            lock_specs.append(locks)
    # With locks, `strands` is per lock (so a 3-lock variant has 3 x as many).
    n_strands = (sum(len(locks) for locks in lock_specs) * cfg["strands"] if lock_specs
                 else cfg["strands"] * variants)
    for i in range(n_strands):
        cx = rng.uniform(0, w)
        hw = rng.uniform(*cfg["width_px"]) / 2
        v = rng.lognormal(0, cfg["value_sigma"])
        amp, per, ph = rng.uniform(0, cfg["wave_px"]), rng.uniform(0.3, 1.0) * h, rng.uniform(0, 6.3)
        slope = 0.0
        if kind == "card":
            k = i % variants
            if lock_specs:
                lcx, ltip, lroot = lock_specs[k][rng.integers(len(lock_specs[k]))]
                cx = lcx + rng.normal(0, cfg["lock_spread_px"])
                cx = min(max(cx, k * wv + 1), (k + 1) * wv - 2)
                y0 = int(h * (lroot + rng.uniform(0, 0.08)))
                # Feathered lock end: the longest strands reach the lock's tip.
                y1 = int(h * min(1.0, ltip - abs(rng.normal(0, cfg["tip_sigma_v"]))))
            else:
                y0 = int(h * rng.uniform(0, cfg["root_v"]))
                y1 = int(h * rng.uniform(*cfg["tip_v"]))
            # Fewer and shorter strands toward the card's edges: no outline.
            e = abs(2 * (cx - k * wv) / wv - 1)
            if rng.random() < e ** cfg["edge_pow"]:
                continue
            y1 = int(y1 * (1 - cfg["edge_short"] * e * e))
            slope = rng.normal(0, cfg.get("slant", 0.0))
        elif kind == "tip":
            y0, y1 = 0, int(h * rng.uniform(*cfg["tip_v"]))
        else:
            if rng.random() < cfg["edge_share"]:
                # Feather band: density ramps up ~ depth^ramp_pow and hairs
                # grow from stubble (stub x length) to full length, so the
                # beard thins out into the skin instead of ending in a line.
                f = rng.uniform(0, 1) ** (1 / (cfg["ramp_pow"] + 1))
                y0 = int(h * cfg["edge_v"] * f)
                n_len = rng.uniform(*cfg["len_px"]) * (cfg["stub"] + (1 - cfg["stub"]) * f * f)
            else:
                y0 = int(rng.uniform(cfg["edge_v"] * 0.7, 1.0) * h)
                n_len = rng.uniform(*cfg["len_px"])
            y1 = min(h, y0 + int(n_len))
            slope = rng.normal(0, cfg["slant"])
        if y1 - y0 < 3:
            continue
        yy = ys[y0:y1]
        x = cx + amp * np.sin(2 * np.pi * yy / per + ph) + slope * (yy - y0)
        if kind == "card":
            d = np.abs(xs - x)  # cards do not wrap across u
        else:
            d = np.abs((xs - x + w / 2) % w - w / 2)
        cov = np.clip(hw + 0.5 - d, 0, 1)
        # Point the free end: the tip (v = 1 side) of a clump strand, the
        # outer (v = 0 side) end of a beard hair.
        n = y1 - y0
        if kind in ("tip", "card"):
            cov *= np.clip((y1 - yy) / (cfg.get("tip_taper_v", 0.06) * h), 0.25, 1)
        else:
            cov *= np.clip((yy - y0) / (0.35 * n), 0.2, 1)
        sl = (slice(y0, y1), slice(None))
        val[sl] = val[sl] * (1 - cov) + v * cov
        alpha[sl] = np.maximum(alpha[sl], cov)
    if kind == "tip":
        core = int(h * cfg["core_v"])
        alpha[:core] = 1
    elif kind == "edge":
        # Opaque below an uneven line (a few wrapping sines across u), so the
        # solid part of the beard has no edge parallel to the beard line.
        x = 2 * np.pi * np.arange(w) / w
        wob = sum(rng.uniform(0.3, 1) * np.sin(k * x + rng.uniform(0, 6.3)) for k in (3, 7, 13, 29))
        top = (h * (cfg["edge_v"] + cfg["solid_jitter_v"] * wob / 2.5)).astype(int)
        alpha[ys >= np.clip(top, 0, h - 1)[None, :]] = 1
    rgba = np.zeros((h, w, 4), dtype=np.float32)
    rgba[..., :3] = np.clip(base[None, None, :] * val[..., None], 0, 1)
    rgba[..., 3] = alpha
    img = bpy.data.images.get(name)
    if img:
        bpy.data.images.remove(img)
    img = bpy.data.images.new(name, w, h, alpha=True)
    img.pixels.foreach_set(rgba.ravel())
    img.pack()
    return img


def material(name, hex_srgb, roughness, image=None, specular=0.5, wrap=True,
             vertex_color=None, anisotropy=0.0):
    """Look-dev material. The runtime hair shader (banded Kajiya-Kay) is a
    TSL concern; this only has to read in the loop renders and carry the
    strand texture (base colour + alpha, exported as MASK) into the GLB.
    vertex_color: name of a colour attribute multiplied into the base colour
    (per-lock value variation; exported as COLOR_0). anisotropy > 0 stretches
    the highlight across the fibres: the tangent is the UV map's u axis, so
    a quarter-turn rotation puts the lobe along v (root -> tip); exported as
    KHR_materials_anisotropy constants, which the runtime shader ignores."""
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    rgb = [srgb_to_linear(c) for c in hex_rgb(hex_srgb)]
    bsdf.inputs["Base Color"].default_value = (*rgb, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Specular IOR Level"].default_value = specular
    color_out = None
    if image is not None:
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = image
        tex.extension = "REPEAT" if wrap else "EXTEND"
        color_out = tex.outputs["Color"]
        # export.fix_alpha routes this through ROUND -> glTF alphaMode MASK.
        nt.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
    if vertex_color:
        attr = nt.nodes.new("ShaderNodeVertexColor")
        attr.layer_name = vertex_color
        if color_out is not None:
            mix = nt.nodes.new("ShaderNodeMix")
            mix.data_type = "RGBA"
            mix.blend_type = "MULTIPLY"
            mix.inputs["Factor"].default_value = 1.0
            nt.links.new(color_out, mix.inputs[6])
            nt.links.new(attr.outputs["Color"], mix.inputs[7])
            color_out = mix.outputs[2]
        else:
            color_out = attr.outputs["Color"]
    if color_out is not None:
        nt.links.new(color_out, bsdf.inputs["Base Color"])
    if anisotropy > 0:
        bsdf.inputs["Anisotropic"].default_value = anisotropy
        bsdf.inputs["Anisotropic Rotation"].default_value = 0.25
        tan = nt.nodes.new("ShaderNodeTangent")
        tan.direction_type = "UV_MAP"
        tan.uv_map = "UVMap"
        nt.links.new(tan.outputs["Tangent"], bsdf.inputs["Tangent"])
    return mat


def shell_from_body(b, body, keep, name):
    """New object holding the faces of body whose vertices are all in keep
    (a set of vertex indices). Keeps the body's skin weights, so a shell
    deforms exactly like the skin under it. Returns (obj, bm); the int
    vertex layer "src" holds each vertex's body index. Write back with
    finish()."""
    me = body.data.copy()
    me.name = name
    obj = bpy.data.objects.new(name, me)
    for c in body.users_collection:
        c.objects.link(obj)
    obj.parent = body.parent
    obj.matrix_parent_inverse = body.matrix_parent_inverse.copy()
    obj.matrix_world = body.matrix_world.copy()
    for g in body.vertex_groups:
        obj.vertex_groups.new(name=g.name)
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    src = bm.verts.layers.int.new("src")  # body vertex index; finish() drops it
    for v in bm.verts:
        v[src] = v.index
    drop = [f for f in bm.faces if not all(v.index in keep for v in f.verts)]
    bmesh.ops.delete(bm, geom=drop, context="FACES_ONLY")
    loose = [v for v in bm.verts if not v.link_faces]
    bmesh.ops.delete(bm, geom=loose, context="VERTS")
    return obj, bm


def edge_rings(bm, n):
    """Distance in edge rings from the open boundary, capped at n."""
    ring = {v: n for v in bm.verts}
    front = [v for v in bm.verts if v.is_boundary]
    for d in range(n):
        nxt = []
        for v in front:
            if ring[v] > d:
                ring[v] = d
                nxt += [e.other_vert(v) for e in v.link_edges]
        front = [v for v in nxt if ring[v] > d]
    return ring


def smooth_boundary(bm, bvh, iterations):
    """Relax the open boundary of a face-selected shell along the surface, so
    its edge (a hairline, a beard line) is a smooth curve rather than the
    staircase of whole faces it was cut from. Boundary vertices move toward
    their boundary neighbours and are snapped back onto the surface."""
    edge = [v for v in bm.verts if v.is_boundary]
    nbrs = {v: [e.other_vert(v) for e in v.link_edges if e.is_boundary] for v in edge}
    for _ in range(iterations):
        new = {}
        for v in edge:
            n = nbrs[v]
            if len(n) != 2:
                continue
            target = v.co * 0.5 + (n[0].co + n[1].co) * 0.25
            loc, _, _, _ = bvh.find_nearest(target)
            new[v] = loc if loc is not None else target
        for v, co in new.items():
            v.co = co


def offset_shell(bm, thickness, taper):
    """Push every vertex out along its normal: thickness(v) in the interior,
    scaled by taper[ring] within len(taper) rings of the boundary, so the
    shell's edge melts into the skin instead of ending in a step."""
    bm.normal_update()
    ring = edge_rings(bm, len(taper))
    moves = []
    for v in bm.verts:
        k = taper[ring[v]] if ring[v] < len(taper) else 1.0
        moves.append((v, v.normal.copy() * thickness(v) * k))
    for v, d in moves:
        v.co += d


def finish(b, obj, bm, mats):
    """Write bm back, set the material(s) (one, or a list indexed by the
    faces' material_index), skin to the staged armature, and register the
    object for export."""
    src = bm.verts.layers.int.get("src")
    if src is not None:
        bm.verts.layers.int.remove(src)
    if not isinstance(mats, (list, tuple)):
        mats = [mats]
        for f in bm.faces:
            f.material_index = 0
    idx = [f.material_index for f in bm.faces]
    bm.to_mesh(obj.data)
    bm.free()
    me = obj.data
    # materials.clear() resets every polygon's material_index to 0 (the hair
    # shipped with all faces on slot 0, the cap's feather texture, until this
    # was restored), so the bmesh indices are written back afterwards.
    me.materials.clear()
    for m in mats:
        me.materials.append(m)
    me.polygons.foreach_set("material_index", idx)
    me.update()
    for p in me.polygons:
        p.use_smooth = True
    arm = b.armature()
    bones = set(bn.name for bn in arm.data.bones)
    for g in list(obj.vertex_groups):
        if g.name not in bones:
            obj.vertex_groups.remove(g)
    obj.parent = arm
    obj.matrix_parent_inverse = arm.matrix_world.inverted()
    mod = next((m for m in obj.modifiers if m.type == "ARMATURE"), None) \
        or obj.modifiers.new("Armature", "ARMATURE")
    mod.object = arm
    b.export_objs.append(obj)
    return obj


def card(bm, uv, uv2, dl, weights, path, outward, halfwidth, tag, curve=0.3,
         v_map=None, mat_index=0, twist=None, u_range=(0.0, 1.0), on_vert=None):
    """Hair card along path: a strip three vertices wide (left, centre lifted
    by curve x half-width along the outward normal, right), so it has a soft
    rounded profile rather than a flat plank. Rendered double-sided with the
    alpha-tested "card" strand texture, whose strands thin out toward both
    edges and end at different lengths, so the card reads as a lock of hair
    with no hard outline. UV0: u across u_range (one atlas variant), v root
    -> tip (v_map(t) overrides). UV1: tag. twist(t): rotation of the card
    about its own axis (radians), so locks turn and catch light differently.
    on_vert(vert, t) runs for every new vertex (per-vertex attributes).
    Returns the number of triangles added."""
    vmap = v_map or (lambda t: t)
    n = len(path) - 1
    rows, prev_nrm = [], None
    for i, p in enumerate(path):
        t = i / n
        tan = (path[min(i + 1, n)] - path[max(i - 1, 0)]).normalized()
        nrm = outward(i)
        nrm = nrm - tan * tan.dot(nrm)
        if nrm.length < 1e-6:
            nrm = prev_nrm or Vector((0, 0, 1))
        nrm.normalize()
        if prev_nrm is not None:
            nrm = (nrm + prev_nrm * 0.6)
            nrm = (nrm - tan * tan.dot(nrm)).normalized()
        prev_nrm = nrm
        bi = tan.cross(nrm)
        if twist is not None:
            a = twist(t)
            ca, sa = math.cos(a), math.sin(a)
            nrm, bi = nrm * ca + bi * sa, bi * ca - nrm * sa
        hw = halfwidth(t)
        row = [bm.verts.new(p - bi * hw), bm.verts.new(p + nrm * (hw * curve)),
               bm.verts.new(p + bi * hw)]
        for v in row:
            for g, w in weights.items():
                v[dl][g] = w
            if on_vert:
                on_vert(v, t)
        rows.append((row, vmap(t)))
    tris = 0
    ua0, ua1 = u_range
    um = (ua0 + ua1) / 2
    for (r0, v0), (r1, v1) in zip(rows, rows[1:]):
        for a, c, ua, uc in ((0, 1, ua0, um), (1, 2, um, ua1)):
            # (left, right) then along: face normal = +outward.
            f = bm.faces.new((r0[a], r0[c], r1[c], r1[a]))
            f.material_index = mat_index
            for loop, co in zip(f.loops, ((ua, v0), (uc, v0), (uc, v1), (ua, v1))):
                loop[uv].uv = co
                loop[uv2].uv = tag
            tris += 2
    return tris


def resample(pts, n):
    """n + 1 points evenly spaced by arc length along the polyline pts."""
    acc = [0.0]
    for a, c in zip(pts, pts[1:]):
        acc.append(acc[-1] + (c - a).length)
    total = acc[-1]
    out, j = [], 0
    for i in range(n + 1):
        s = total * i / n
        while j < len(acc) - 2 and acc[j + 1] < s:
            j += 1
        seg = acc[j + 1] - acc[j]
        t = 0.0 if seg <= 0 else (s - acc[j]) / seg
        out.append(pts[j].lerp(pts[j + 1], min(max(t, 0.0), 1.0)))
    return out, total


def tube(bm, uv, uv2, dl, weights, path, outward, radius, aspect, sides, tag,
         u0=0.0, u_span=1.0, v_map=None, mat_index=0, on_vert=None):
    """Tapered, flattened tube along path (closed to a point at the tip,
    open at the root, which is buried in the cap). outward(i) gives the
    surface normal the tube's flat side lies against; radius(t) the
    half-width; aspect (a number, or a function of t) = half-width /
    half-thickness. UV0: u around (u0 .. u0 + u_span, so each clump samples
    its own part of the strand texture), v root -> tip (the Kajiya-Kay
    tangent direction; v_map(t) overrides it). UV1: tag (per-clump random,
    side sign). Returns the number of triangles added."""
    asp = aspect if callable(aspect) else (lambda t: aspect)
    vmap = v_map or (lambda t: t)
    n = len(path) - 1
    rings = []
    prev_nrm = None
    for i, p in enumerate(path):
        t = i / n
        tan = (path[min(i + 1, n)] - path[max(i - 1, 0)]).normalized()
        nrm = outward(i)
        nrm = (nrm - tan * tan.dot(nrm))
        if nrm.length < 1e-6:
            nrm = prev_nrm or Vector((0, 0, 1))
        nrm.normalize()
        if prev_nrm is not None:
            nrm = (nrm + prev_nrm * 0.6)
            nrm = (nrm - tan * tan.dot(nrm)).normalized()
        prev_nrm = nrm
        bi = tan.cross(nrm)
        if i == n:
            rings.append([bm.verts.new(p)])
        else:
            hw = radius(t)
            ht = hw / asp(t)
            ring = []
            for k in range(sides):
                a = 2 * math.pi * k / sides
                ring.append(bm.verts.new(p + bi * (math.cos(a) * hw) + nrm * (math.sin(a) * ht)))
            rings.append(ring)
        for v in rings[-1]:
            for g, w in weights.items():
                v[dl][g] = w
            if on_vert:
                on_vert(v, t)
    tris = 0
    for i in range(n):
        r0, r1 = rings[i], rings[i + 1]
        v0, v1 = vmap(i / n), vmap((i + 1) / n)
        for k in range(sides):
            k1 = (k + 1) % sides
            ua, ub = u0 + u_span * k / sides, u0 + u_span * (k + 1) / sides
            # Winding: (around) x (along) points inward, so go along first.
            if len(r1) == 1:
                f = bm.faces.new((r0[k], r1[0], r0[k1]))
                uvs = ((ua, v0), ((ua + ub) / 2, v1), (ub, v0))
                tris += 1
            else:
                f = bm.faces.new((r0[k], r1[k], r1[k1], r0[k1]))
                uvs = ((ua, v0), (ua, v1), (ub, v1), (ub, v0))
                tris += 2
            f.material_index = mat_index
            for loop, c in zip(f.loops, uvs):
                loop[uv].uv = c
                loop[uv2].uv = tag
    return tris
