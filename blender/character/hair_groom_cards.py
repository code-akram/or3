"""Game hair cards baked from the strand groom (hair_groom).

The groom is the source of truth: the evaluated strands (after the Geometry
Nodes clump / noise / frizz / trim) give both the card geometry and the card
texture atlas.

1. Atlas (2048², 12 lock variants in a 6 x 2 grid of 341 x 1024 cells):
   representative clumps of the groom are flattened into their card frame
   (u across the clump's own width, v root -> tip along its centreline,
   depth along the card normal) and rasterised strand by strand (3x
   supersampled, z-buffered): coverage (alpha), root-to-tip, strand ID,
   flow (the strand tangent in UV space, +-15 deg jitter per strand for the
   runtime), depth and an AO term from depth and local density. Packed as
     hair_atlas_albedo  RGB albedo (strand value variation x AO), A coverage
     hair_atlas_data    R coverage, G root-to-tip, B strand ID (the layout
                        of threejs-hair-shader's strand-data atlas, MIT)
     hair_atlas_flow    RG flow (0.5 + 0.5 x), B depth, A AO
     hair_atlas_normal  tangent-space normal (strand cylinders + depth slope)
   Cells: 8 secondary clumps (mid / top locks, sparse to dense), 2 primary
   clumps (under), 1 flyaway (few strands), 1 hairline wisp (short, fine).
2. Cards, one per clump, along the clump's evaluated centreline (the mean of
   its strands per point), width from the strands' spread across the card,
   tapered, 3 vertices wide with a rounded profile:
     cap       the scalp shell (hair_clumps' feather texture), opaque core,
               hairline feather following the groom's recessed hairline
     under     the primary clumps, pulled in toward the scalp, dense cells
     mid / top the secondary clumps (inner half mid, outer half top)
     flyaway   thin strips along the groom's flyaway strands
3. COLOR_0 "lock": layer AO (under 0.55, mid 0.78, top 1.0) x per-lock
   value x a 35 % root darkening.
4. Smooth-proxy normals: a hair-volume blob (the groom's points through
   Points to Volume / Volume to Mesh) transfers its normals to the cards
   (Data Transfer, custom normals), so the cards shade as one soft mass.
5. Spring chains: hang distance and sector per card vertex from the clump's
   strands (hair_springs.bind), as the hair_clumps cards did.
"""

import math

import bpy
import numpy as np
from mathutils import Vector
from mathutils.kdtree import KDTree

from . import hair_clumps, hair_mesh, hair_springs

CARDS = {
    "atlas": {"size": 2048, "cols": 6, "rows": 2, "ss": 3, "pad_px": 6,
              "strand_px": 2.2,      # strand width in atlas px (final res) at the root
              "flow_jitter_deg": 15.0, "value_sigma": 0.22, "light_share": 0.03,
              "ao": 0.55, "seed": 5},
    "segment_m": 0.022, "min_segments": 4, "max_segments": 14,
    "min_halfwidth_m": 0.0015, "width_pct": 85, "width_pad_m": 0.0008,
    "tip_width": 0.45, "curve": 0.3, "root_w": [0.25, 0.8], "root_w_m": [0.005, 0.025],
    "under": {"split": 2, "inset_m": 0.003, "width": 0.9, "max_halfwidth_m": 0.014},
    "flyaways": {"count": 40, "start": 0.35, "halfwidth_m": 0.0012},
    "layer_shade": {"under": 0.55, "mid": 0.78, "top": 1.0, "front": 0.9, "fly": 0.85},
    "root_dark": 0.35, "root_v": 0.3, "lock_sigma": 0.15,
    "material": {"roughness": 0.55, "specular": 0.25, "normal_strength": 0.8,
                 "color": "#1d1915"},
    "proxy": {"voxel_m": 0.004, "radius_m": 0.008, "every": 4},
    # Cap texture from the groom's hairline (bake_cap_texture).
    "cap": {"window_az_deg": -28.0, "strand_px": 0.7, "core_m": [0.012, 0.026], "seed": 9,
            "near_skin_m": 0.003, "max_len_m": 0.015, "shade": 0.85},
}

smoothstep = hair_clumps.smoothstep


def nsmooth(e0, e1, x):
    t = np.clip((np.asarray(x, dtype=float) - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


# ---------------------------------------------------------------- strands

def evaluated_strands(g):
    """(n, m, 3) evaluated main strands (vellus excluded)."""
    ev, n, m = g["eval"], g["n"], g["m"]
    offs = ev["offs"]
    if not np.all(np.diff(offs[:n + 1]) == m):
        raise RuntimeError("hair_groom_cards: the groom modifier changed point counts")
    return ev["pos"][:n * m].reshape(n, m, 3).astype(np.float64)


def frame_along(frame, C, cloth_gap, off):
    """Per point of centreline C: (tangent, outward normal, binormal, touching).
    The normal is the collider normal while the clump lies on the skull and
    the radial direction from the head axis once it hangs."""
    c = frame.center
    k = len(C)
    T = np.gradient(C, axis=0)
    T /= np.linalg.norm(T, axis=1, keepdims=True) + 1e-12
    Nn = np.zeros_like(C)
    touch = np.zeros(k)
    prev = None
    for i in range(k):
        p = Vector(C[i])
        loc, nrm, sd = frame.signed(p, cloth_gap)
        radial = Vector((p.x - c.x, p.y - c.y, max(p.z - c.z, 0.0))).normalized()
        t = nrm is not None and sd < off
        nv = nrm if t else radial
        nv = np.array(nv)
        nv -= T[i] * nv.dot(T[i])
        if np.linalg.norm(nv) < 1e-6:
            nv = prev if prev is not None else np.array([0, 0, 1.0])
        nv /= np.linalg.norm(nv)
        if prev is not None:
            nv = nv + prev * 0.6
            nv -= T[i] * nv.dot(T[i])
            nv /= np.linalg.norm(nv)
        Nn[i] = nv
        prev = nv
        touch[i] = 1.0 if t else 0.0
    B = np.cross(T, Nn)
    return T, Nn, B, touch


def clump_profile(frame, E, members, cloth_gap, pct, pad, hw_min, hw_max=None):
    """Centreline, frame and half-width per point for a clump's strands."""
    S = E[members]
    C = S.mean(0)
    T, Nn, B, touch = frame_along(frame, C, cloth_gap, 0.02)
    O = S - C[None]
    u = np.abs((O * B[None]).sum(2))
    hw = np.percentile(u, pct, axis=0) + pad
    hw = np.maximum(hw, hw_min)
    if hw_max is not None:
        hw = np.minimum(hw, hw_max)
    # Smooth along the clump.
    hw = np.convolve(np.pad(hw, 2, mode="edge"), np.ones(5) / 5, mode="valid")
    return {"C": C, "T": T, "N": Nn, "B": B, "touch": touch, "hw": hw, "S": S, "O": O}


# ---------------------------------------------------------------- atlas

def raster_cell(prof, rng, W, H, ss, acfg, max_strands=None, v_scale=1.0):
    """Rasterise a clump's strands into one atlas cell, W x H final px.
    Returns float arrays (H, W): cov, v, sid, depth, flowu, flowv, across,
    value (coverage-weighted means)."""
    S, O, B, Nn, hw, C, T = prof["S"], prof["O"], prof["B"], prof["N"], prof["hw"], prof["C"], prof["T"]
    idx = np.arange(len(S))
    if max_strands and len(idx) > max_strands:
        idx = rng.choice(idx, max_strands, replace=False)
    arc = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(C, axis=0), axis=1))])
    vtot = arc[-1] * v_scale
    Ws, Hs = W * ss, H * ss
    cov = np.zeros((Hs, Ws), dtype=bool)
    att = {k: np.zeros((Hs, Ws), dtype=np.float32) for k in
           ("v", "sid", "depth", "fu", "fv", "across", "val")}
    dmax = np.abs((O * Nn[None]).sum(2)).max() + 1e-6
    xs_all, ys_all, cols = [], [], {k: [] for k in ("v", "sid", "depth", "fu", "fv", "across", "val")}
    vs = acfg["value_sigma"]
    for j in idx:
        u = (O[j] * B).sum(1) / hw            # -1 .. 1 across
        d = (O[j] * Nn).sum(1) / dmax         # -1 .. 1 depth (+ = outward)
        # v: the centreline arc at the same point index plus the offset
        # along the centreline tangent, so roots stagger (strands rooted
        # behind the clump's root join it later) and trimmed tips end early.
        v = (arc + (O[j] * T).sum(1)) / max(vtot, 1e-6)
        v = np.clip(v, 0.0, 1.0)
        x = (u * 0.5 + 0.5) * Ws
        y = v * Hs
        seg = np.hypot(np.diff(x), np.diff(y))
        acc = np.concatenate([[0.0], np.cumsum(seg)])
        ns = max(int(acc[-1] / 0.5), 2)
        s = np.linspace(0, acc[-1], ns)
        xi, yi = np.interp(s, acc, x), np.interp(s, acc, y)
        di, vi = np.interp(s, acc, d), np.interp(s, acc, v)
        tx, ty = np.gradient(xi), np.gradient(yi)
        tl = np.hypot(tx, ty) + 1e-9
        tx, ty = tx / tl, ty / tl
        sid = rng.random()
        val = rng.lognormal(0, vs) * (1.8 if rng.random() < acfg["light_share"] else 1.0)
        rpx = acfg["strand_px"] * ss * 0.5 * (1.0 - 0.5 * np.clip(vi, 0, 1) ** 2)
        span = rpx / np.maximum(np.abs(ty), 0.35)
        jit = math.radians(acfg["flow_jitter_deg"]) * rng.uniform(-1, 1)
        fu, fv = tx * math.cos(jit) - ty * math.sin(jit), tx * math.sin(jit) + ty * math.cos(jit)
        smax = int(np.ceil(span.max()))
        for o in range(-smax, smax + 1):
            ok = np.abs(o) <= span
            if not ok.any():
                continue
            xo = np.round(xi[ok] + o).astype(int)
            yo = np.round(yi[ok]).astype(int)
            inb = (xo >= 0) & (xo < Ws) & (yo >= 0) & (yo < Hs)
            xs_all.append(xo[inb])
            ys_all.append(yo[inb])
            a = (o / np.maximum(span[ok], 1e-6))[inb]
            cols["across"].append(a)
            cols["v"].append(vi[ok][inb])
            cols["depth"].append(di[ok][inb])
            cols["fu"].append(fu[ok][inb])
            cols["fv"].append(fv[ok][inb])
            cols["sid"].append(np.full(inb.sum(), sid))
            cols["val"].append(np.full(inb.sum(), val))
    xs = np.concatenate(xs_all)
    ys = np.concatenate(ys_all)
    order = np.argsort(np.concatenate(cols["depth"]), kind="stable")  # front-most last: wins
    xs, ys = xs[order], ys[order]
    cov[ys, xs] = True
    for k in att:
        att[k][ys, xs] = np.concatenate(cols[k])[order]
    # Downsample (box filter): coverage fraction, coverage-weighted means.
    def down(a):
        return a.reshape(H, ss, W, ss).mean(axis=(1, 3))
    c = down(cov.astype(np.float32))
    out = {"cov": c}
    for k, a in att.items():
        out[k] = np.where(c > 0, down(a * cov) / np.maximum(c, 1e-6), 0.0)
    return out


def blur(a, r):
    """Separable box blur, radius r px (3 passes ~ Gaussian)."""
    for _ in range(3):
        for ax in (0, 1):
            k = np.ones(2 * r + 1) / (2 * r + 1)
            a = np.apply_along_axis(lambda x: np.convolve(np.pad(x, r, mode="edge"), k, "valid"), ax, a)
    return a


def bake_atlas(cells, acfg, base_hex):
    """Assemble the cells into the four atlas images; returns
    {name: bpy image}, plus the cells' UV rectangles."""
    size, cols, rows, pad = acfg["size"], acfg["cols"], acfg["rows"], acfg["pad_px"]
    cw, ch = size // cols, size // rows
    alb = np.zeros((size, size, 4), dtype=np.float32)
    data = np.zeros((size, size, 4), dtype=np.float32)
    flow = np.zeros((size, size, 4), dtype=np.float32)
    nrm = np.zeros((size, size, 4), dtype=np.float32)
    nrm[..., :] = (0.5, 0.5, 1.0, 1.0)
    flow[..., :] = (0.5, 1.0, 0.5, 1.0)
    data[..., 3] = 1.0
    base = np.array([hair_mesh.srgb_to_linear(c) for c in hair_mesh.hex_rgb(base_hex)])
    rects = []
    for i, cell in enumerate(cells):
        col, row = i % cols, i // cols
        x0, y0 = col * cw + pad, row * ch + pad
        w, h = cw - 2 * pad, ch - 2 * pad
        cov = cell["cov"]
        dens = blur(cov, 6)
        depth = cell["depth"]
        ao = np.clip(1.0 - acfg["ao"] * np.clip(dens * 1.4, 0, 1) * (0.5 - 0.5 * depth), 0.35, 1.0)
        val = np.where(cov > 0, cell["val"], 1.0)
        lin = base[None, None, :] * (val * ao)[..., None]
        # Store sRGB (the image is tagged sRGB).
        srgb = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.power(np.maximum(lin, 0), 1 / 2.4) - 0.055)
        sl = (slice(y0, y0 + h), slice(x0, x0 + w))
        alb[sl + (slice(0, 3),)] = srgb
        alb[sl + (3,)] = cov
        data[sl + (0,)] = cov
        data[sl + (1,)] = cell["v"]
        data[sl + (2,)] = cell["sid"]
        flow[sl + (0,)] = 0.5 + 0.5 * cell["fu"]
        flow[sl + (1,)] = 0.5 + 0.5 * cell["fv"]
        flow[sl + (2,)] = 0.5 + 0.5 * depth
        flow[sl + (3,)] = ao
        # Normal: tilt across the strand (cylinder), perpendicular to the flow.
        a = np.clip(cell["across"], -1, 1) * 0.75
        pu, pv = cell["fv"], -cell["fu"]
        nz = np.sqrt(np.clip(1 - a * a, 0, 1))
        nrm[sl + (0,)] = np.where(cov > 0, 0.5 + 0.5 * a * pu, 0.5)
        nrm[sl + (1,)] = np.where(cov > 0, 0.5 + 0.5 * a * pv, 0.5)
        nrm[sl + (2,)] = np.where(cov > 0, 0.5 + 0.5 * nz, 1.0)
        rects.append(((x0 + 0.5) / size, (y0 + 0.5) / size, (x0 + w - 0.5) / size, (y0 + h - 0.5) / size))
    # Bleed colour into the transparent texels (mip-safe edges).
    rgb = alb[..., :3]
    m = alb[..., 3] > 0.02
    mean = rgb[m].mean(0) if m.any() else np.zeros(3)
    alb[..., :3] = np.where(m[..., None], rgb, mean[None, None, :])
    imgs = {}
    for name, arr, cs in (("hair_atlas_albedo", alb, "sRGB"), ("hair_atlas_data", data, "Non-Color"),
                          ("hair_atlas_flow", flow, "Non-Color"), ("hair_atlas_normal", nrm, "Non-Color")):
        img = bpy.data.images.get(name) or bpy.data.images.new(name, size, size, alpha=True)
        img.colorspace_settings.name = cs
        img.alpha_mode = "STRAIGHT"
        img.pixels.foreach_set(np.ascontiguousarray(arr).ravel())
        img.pack()
        imgs[name] = img
    return imgs, rects


# ---------------------------------------------------------------- material

def card_material(imgs, mcfg):
    mat = bpy.data.materials.get("hair_cards") or bpy.data.materials.new("hair_cards")
    if mat.node_tree is None:
        mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(bsdf.outputs[0], out.inputs["Surface"])
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = imgs["hair_atlas_albedo"]
    tex.extension = "EXTEND"
    vc = nt.nodes.new("ShaderNodeVertexColor")
    vc.layer_name = "lock"
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.blend_type = "MULTIPLY"
    mix.inputs["Factor"].default_value = 1.0
    nt.links.new(tex.outputs["Color"], mix.inputs[6])
    nt.links.new(vc.outputs["Color"], mix.inputs[7])
    nt.links.new(mix.outputs[2], bsdf.inputs["Base Color"])
    nt.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
    ntex = nt.nodes.new("ShaderNodeTexImage")
    ntex.image = imgs["hair_atlas_normal"]
    ntex.extension = "EXTEND"
    nmap = nt.nodes.new("ShaderNodeNormalMap")
    nmap.inputs["Strength"].default_value = mcfg["normal_strength"]
    nmap.uv_map = "UVMap"
    nt.links.new(ntex.outputs["Color"], nmap.inputs["Color"])
    nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    bsdf.inputs["Roughness"].default_value = mcfg["roughness"]
    bsdf.inputs["Specular IOR Level"].default_value = mcfg["specular"]
    # The data / flow atlases ride along in the .blend (and as PNGs next to
    # the GLB) for the runtime shader; not wired (glTF has no slot for them).
    for name in ("hair_atlas_data", "hair_atlas_flow"):
        t = nt.nodes.new("ShaderNodeTexImage")
        t.image = imgs[name]
        t.label = name
    mat.use_backface_culling = False
    return mat


# ---------------------------------------------------------------- proxy normals

def proxy_blob(points, pcfg):
    """Smooth hair-volume mesh from groom points (Points to Volume ->
    Volume to Mesh), returned as a temporary object."""
    me = bpy.data.meshes.new("hair_proxy_pts")
    me.vertices.add(len(points))
    me.vertices.foreach_set("co", points.astype(np.float32).ravel())
    src = bpy.data.objects.new("hair_proxy_pts", me)
    bpy.context.scene.collection.objects.link(src)
    ng = bpy.data.node_groups.new("hair_proxy", "GeometryNodeTree")
    ng.is_modifier = True
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    N, L = ng.nodes, ng.links
    gi, go = N.new("NodeGroupInput"), N.new("NodeGroupOutput")
    m2p = N.new("GeometryNodeMeshToPoints")
    m2p.inputs["Radius"].default_value = pcfg["radius_m"]
    p2v = N.new("GeometryNodePointsToVolume")
    p2v.inputs["Radius"].default_value = pcfg["radius_m"]
    for k in ("Voxel Size",):
        if k in p2v.inputs:
            p2v.inputs[k].default_value = pcfg["voxel_m"]
    if hasattr(p2v, "resolution_mode"):
        p2v.resolution_mode = "VOXEL_SIZE"
    elif "Resolution Mode" in p2v.inputs:
        p2v.inputs["Resolution Mode"].default_value = "Size"
    v2m = N.new("GeometryNodeVolumeToMesh")
    smooth = N.new("GeometryNodeSetShadeSmooth")
    L.new(gi.outputs[0], m2p.inputs[0])
    L.new(m2p.outputs[0], p2v.inputs[0])
    L.new(p2v.outputs[0], v2m.inputs[0])
    L.new(v2m.outputs[0], smooth.inputs[0])
    L.new(smooth.outputs[0], go.inputs[0])
    mod = src.modifiers.new("proxy", "NODES")
    mod.node_group = ng
    dg = bpy.context.evaluated_depsgraph_get()
    blob_me = bpy.data.meshes.new_from_object(src.evaluated_get(dg))
    bpy.data.objects.remove(src, do_unlink=True)
    bpy.data.meshes.remove(me)
    bpy.data.node_groups.remove(ng)
    blob = bpy.data.objects.new("hair_proxy", blob_me)
    bpy.context.scene.collection.objects.link(blob)
    sm = blob.modifiers.new("smooth", "LAPLACIANSMOOTH")
    sm.iterations = 6
    sm.lambda_factor = 1.0
    dg = bpy.context.evaluated_depsgraph_get()
    sm_me = bpy.data.meshes.new_from_object(blob.evaluated_get(dg))
    blob.modifiers.clear()
    old = blob.data
    blob.data = sm_me
    bpy.data.meshes.remove(old)
    return blob


def transfer_normals(obj, blob, verts):
    """Data Transfer the blob's normals to obj's vertices `verts` (custom
    split normals), applied as the first modifier."""
    vg = obj.vertex_groups.new(name="_proxy_cards")
    vg.add(list(verts), 1.0, "REPLACE")
    mod = obj.modifiers.new("proxy_normals", "DATA_TRANSFER")
    mod.object = blob
    mod.use_loop_data = True
    mod.data_types_loops = {"CUSTOM_NORMAL"}
    mod.loop_mapping = "POLYINTERP_NEAREST"
    mod.vertex_group = vg.name
    obj.modifiers.move(obj.modifiers.find(mod.name), 0)
    with bpy.context.temp_override(object=obj, active_object=obj, selected_objects=[obj]):
        bpy.ops.object.modifier_apply(modifier=mod.name)
    obj.vertex_groups.remove(obj.vertex_groups[vg.name])


# ---------------------------------------------------------------- build

def build(b, frame, ccfg, g):
    cfg = CARDS
    gcfg = g["cfg"]
    over = gcfg.get("game") or {}
    for k, v in over.items():
        cfg = dict(cfg, **{k: (dict(cfg[k], **v) if isinstance(cfg.get(k), dict) else v)})
    rng = np.random.default_rng(cfg["atlas"]["seed"])
    E = evaluated_strands(g)
    n, m = E.shape[:2]
    prim, sub, kind, stray, fly, H = g["prim"], g["sub"], g["kind"][:n], g["stray"], g["fly"], g["hang"]
    cloth_gap = ccfg.get("cloth_gap_m", 0.0)
    c = frame.center

    # --- clumps -> profiles
    main = (kind != 1) & ~stray
    subs = np.unique(sub[main])
    profs = []
    for s in subs:
        members = np.where((sub == s) & main)[0]
        if len(members) < 3:
            continue
        p = clump_profile(frame, E, members, cloth_gap, cfg["width_pct"], cfg["width_pad_m"],
                          cfg["min_halfwidth_m"])
        p.update(members=members, kind="front" if kind[s] == 2 else "sec",
                 hang=H[members].mean(0))
        profs.append(p)
    # Inner / outer: the clump's mean distance from the skull past the root.
    for p in profs:
        mid = p["C"][len(p["C"]) // 3:]
        p["depth"] = float(np.mean([frame.signed(Vector(q), cloth_gap)[2] for q in mid[::3]]))
    dmed = np.median([p["depth"] for p in profs if p["kind"] == "sec"])
    for p in profs:
        if p["kind"] == "sec":
            p["layer"] = "top" if p["depth"] >= dmed else "mid"
        else:
            p["layer"] = "front"
    uc = cfg["under"]
    unders = []
    for pc in np.unique(prim[main & (kind == 0)]):
        members = np.where((prim == pc) & main & (kind == 0))[0]
        if len(members) < 10:
            continue
        # Split the primary clump in halves across its width.
        p0 = clump_profile(frame, E, members, cloth_gap, 50, 0.0, cfg["min_halfwidth_m"])
        side = ((E[members] - p0["C"][None]) * p0["B"][None]).sum(2).mean(1)
        for part in ([side < 0, side >= 0] if uc["split"] == 2 else [np.ones(len(members), bool)]):
            mm = members[part]
            if len(mm) < 10:
                continue
            p = clump_profile(frame, E, mm, cloth_gap, cfg["width_pct"], cfg["width_pad_m"],
                              cfg["min_halfwidth_m"], uc["max_halfwidth_m"])
            p["hw"] *= uc["width"]
            # Pull the under card in toward the skull.
            p["C"] = p["C"] - p["N"] * uc["inset_m"] * nsmooth(0.0, 0.2, np.linspace(0, 1, m))[:, None]
            p.update(members=mm, kind="under", layer="under", hang=H[mm].mean(0))
            unders.append(p)

    # --- atlas cells from representative clumps
    acfg = cfg["atlas"]
    cw = acfg["size"] // acfg["cols"] - 2 * acfg["pad_px"]
    chh = acfg["size"] // acfg["rows"] - 2 * acfg["pad_px"]
    ss = acfg["ss"]
    hanging = [p for p in profs if p["layer"] in ("mid", "top") and p["hang"][-1] > 0.08]
    hanging.sort(key=lambda p: len(p["members"]))
    reps = [hanging[int(q * (len(hanging) - 1))] for q in np.linspace(0.15, 0.95, 8)]
    under_reps = sorted(unders, key=lambda p: -len(p["members"]))[:2]
    cells = [raster_cell(p, rng, cw, chh, ss, acfg) for p in reps]
    cells += [raster_cell(p, rng, cw, chh, ss, acfg, max_strands=450) for p in under_reps]
    # Flyaway cell: a few loose strands of a hanging clump, spread wide.
    fl = dict(reps[2])
    pick = rng.choice(len(fl["S"]), min(6, len(fl["S"])), replace=False)
    fl = dict(fl, S=fl["S"][pick], O=fl["O"][pick] * 2.5)
    cells.append(raster_cell(fl, rng, cw, chh, ss, acfg))
    # Hairline wisp: a front clump's first third, fine and sparse.
    front = [p for p in profs if p["kind"] == "sec" and p["touch"][:m // 3].mean() > 0.8]
    wisp = front[len(front) // 2] if front else reps[0]
    k3 = max(4, m // 3)
    wp = dict(wisp, S=wisp["S"][:, :k3], O=wisp["O"][:, :k3], C=wisp["C"][:k3], N=wisp["N"][:k3],
              B=wisp["B"][:k3], T=wisp["T"][:k3], hw=wisp["hw"][:k3])
    cells.append(raster_cell(wp, rng, cw, chh, ss, dict(acfg, strand_px=acfg["strand_px"] * 0.7)))
    imgs, rects = bake_atlas(cells, acfg, cfg["material"]["color"])
    save_atlas(b, imgs)

    # --- mesh: cap first (hair_clumps' shell and feather texture)
    obj, bm, uv, uv2, col, hang_l, sector_l, dl, weights = cap_mesh(b, frame, ccfg, g, cfg["cap"]["shade"])
    shade = cfg["layer_shade"]

    def add_card(p, cell, layer, path_from=0, halfwidth_m=None, two_wide=False):
        C = p["C"][path_from:]
        arc = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(C, axis=0), axis=1))])
        total = arc[-1]
        if total < 0.01:
            return 0
        nseg = int(np.clip(round(total / cfg["segment_m"]), cfg["min_segments"], cfg["max_segments"]))
        # Point 0 stays (buried root), the rest even by length.
        s = np.concatenate([[0.0], np.linspace(arc[1] if len(arc) > 1 else 0, total, nseg)])
        idx = np.interp(s, arc, np.arange(len(C)))
        def at(a, x):
            return np.stack([np.interp(x, np.arange(len(a)), a[:, k]) for k in range(a.shape[1])], 1) \
                if a.ndim == 2 else np.interp(x, np.arange(len(a)), a)
        P = at(C, idx)
        Nn = at(p["N"][path_from:], idx)
        hw = at(p["hw"][path_from:], idx) if halfwidth_m is None else np.full(len(idx), halfwidth_m)
        hs = at(p["hang"][path_from:], idx)
        path = [Vector(q) for q in P]
        normals = [Vector(q) for q in Nn]
        nrow = len(path) - 1
        d_root = g["surf"].d_eff(P[1])
        rw0, rw1 = cfg["root_w"]
        root_w = rw0 + (rw1 - rw0) * smoothstep(cfg["root_w_m"][0], cfg["root_w_m"][1], d_root)
        tip_w = cfg["tip_width"]

        def halfwidth(t, hw=hw, nrow=nrow):
            i = min(int(round(t * nrow)), nrow)
            w0 = 0.15 + 0.85 * smoothstep(0.0, 0.6 / nrow, t)
            taper = 1 - (1 - tip_w) * t ** 1.3
            return hw[i] * (root_w + (1 - root_w) * smoothstep(0.0, 0.12, t)) * w0 * taper

        hang_pt = path[int(np.argmax(hs > 0))] if (hs > 0).any() else path[-1]
        sector = hair_springs.sector_id(frame, hang_pt, 1 if p.get("kind") == "front" else 0)
        lockv = float(rng.lognormal(0, cfg["lock_sigma"]))
        base = shade[layer] * lockv

        def on_vert(v, t, hs=hs, nrow=nrow, sector=sector, base=base):
            r = 1 - cfg["root_dark"] * (1 - smoothstep(0.0, cfg["root_v"], t))
            x = min(max(base * r, 0.15), 1.0)
            v[col] = (x, x, x, 1.0)
            v[hang_l] = float(hs[min(int(round(t * nrow)), nrow)])
            v[sector_l] = sector

        x0, y0, x1, y1 = rects[cell]
        return hair_mesh.card(bm, uv, uv2, dl, weights, path, lambda k: normals[k], halfwidth,
                              (float(rng.random()), 1.0 if path[0].x >= c.x else -1.0),
                              curve=cfg["curve"] if not two_wide else 0.0, mat_index=1,
                              v_map=lambda t, y0=y0, y1=y1: y0 + (y1 - y0) * t,
                              u_range=(x0, x1), on_vert=on_vert)

    counts, tris = {}, {}

    def count(layer, t):
        counts[layer] = counts.get(layer, 0) + 1
        tris[layer] = tris.get(layer, 0) + t

    for p in unders:
        count("under", add_card(p, 8 + int(rng.integers(2)), "under"))
    # Mid / top: a cell by density rank (sparse clumps sparse cells).
    ranks = np.argsort(np.argsort([len(p["members"]) for p in profs]))
    for p, r in zip(profs, ranks):
        cell = int(np.clip(r / max(len(profs) - 1, 1) * 8 + rng.integers(-1, 2), 0, 7))
        count(p["layer"], add_card(p, cell, p["layer"]))
    # Flyaways along the groom's flyaway strands.
    fc = cfg["flyaways"]
    s0 = int(m * fc["start"])
    # Not round the ear (a loose strip across the ear reads as a stray card).
    ok = (fly > 0) & ((E[:, s0, 1] > frame.ears_max.y) | (E[:, s0, 2] > frame.ears_max.z + 0.02))
    fidx = np.argsort(-(fly * ok))[:fc["count"]]
    for j in fidx:
        if not ok[j]:
            continue
        S = E[j:j + 1]
        p = {"C": E[j], "hang": H[j], "kind": "fly"}
        T, Nn, B, touch = frame_along(frame, E[j], cloth_gap, 0.02)
        p.update(N=Nn, hw=np.full(m, fc["halfwidth_m"]))
        count("fly", add_card(p, 10, "fly", path_from=s0, halfwidth_m=fc["halfwidth_m"]))

    springs = None
    if ccfg.get("springs"):
        springs = hair_springs.bind(b, obj, bm, dl, hang_l, sector_l, ccfg["springs"])
    bm.verts.layers.float.remove(hang_l)
    bm.verts.layers.int.remove(sector_l)
    cap_faces = sum(1 for f in bm.faces if f.material_index == 0)
    tc = ccfg["texture_cap"]
    cap_img, cap_strands = bake_cap_texture(frame, g, E, ccfg, cfg["cap"])
    mats = [hair_mesh.material("hair", tc["color"], cfg["material"]["roughness"], cap_img,
                               cfg["material"]["specular"], vertex_color="lock", anisotropy=0.0),
            card_material(imgs, cfg["material"])]
    hair_mesh.finish(b, obj, bm, mats)
    b.cutouts.append("hair_export")

    # Smooth-proxy normals on the card vertices (not the cap).
    me = obj.data
    card_verts = set()
    for poly in me.polygons:
        if poly.material_index == 1:
            card_verts.update(poly.vertices)
    pts = E[::cfg["proxy"]["every"]].reshape(-1, 3)
    blob = proxy_blob(pts, cfg["proxy"])
    transfer_normals(obj, blob, card_verts)
    blob_info = {"verts": len(blob.data.vertices), "faces": len(blob.data.polygons)}
    bpy.data.objects.remove(blob, do_unlink=True)

    total = sum(len(p.vertices) - 2 for p in me.polygons)
    tips = sorted(float(p["C"][-1][2]) for p in profs)
    b.notes["hair"] = {
        "source": "groom", "cards": counts, "cap_texture_strands": cap_strands, "card_tris": tris, "cap_faces": cap_faces,
        "tris": total, "atlas": {"size": acfg["size"], "cells": len(cells)},
        "proxy_blob": blob_info,
        "tip_z_p10_p50_p90": [round(tips[int(q * (len(tips) - 1))], 4) for q in (0.1, 0.5, 0.9)],
        "springs": springs,
    }
    b.notes["hair"].update(silhouette(frame, obj, g))
    return obj


def silhouette(frame, obj, g):
    """Width at eye level (spec: <= 1.35 x the skull there) and how far the
    hair breaks beyond the cap at the sides (direction: >= 30 mm): per 1 cm
    band over the cap's height, the hair's x extent past the cap's (both
    sides), maximum over the bands (the smaller side of the best band)."""
    mw = obj.matrix_world
    H = np.array([tuple(mw @ v.co) for v in obj.data.vertices])
    capv = set()
    for poly in obj.data.polygons:
        if poly.material_index == 0:
            capv.update(poly.vertices)
    Cv = H[sorted(capv)]
    body = frame.body
    Bv = np.array([tuple(body.matrix_world @ v.co) for v in body.data.vertices])
    Bv = Bv[np.abs(Bv[:, 1] - frame.center.y) < 0.08]
    out = {}
    eye_z = frame.ear_z + 0.02

    def ext(P, z):
        sel = P[np.abs(P[:, 2] - z) < 0.005]
        return (sel[:, 0].min(), sel[:, 0].max()) if len(sel) else None

    he, be = ext(H, eye_z), ext(Bv, eye_z)
    if he and be:
        out["width_eye_level_m"] = round(float(he[1] - he[0]), 4)
        out["width_to_skull"] = round(float((he[1] - he[0]) / (be[1] - be[0])), 3)
    best = (0.0, 0.0, None)
    for z in np.arange(Cv[:, 2].min() + 0.005, Cv[:, 2].max(), 0.01):
        he, be = ext(H, z), ext(Cv, z)
        if not (he and be):
            continue
        l, r = be[0] - he[0], he[1] - be[1]
        if min(l, r) > min(best[0], best[1]):
            best = (l, r, z)
    out["side_break_m"] = [round(float(best[0]), 4), round(float(best[1]), 4)]
    zt = frame.ears_max.z + 0.01
    he, ce = ext(H, zt), ext(Cv, zt)
    if he and ce:
        out["side_break_temple_m"] = [round(float(ce[0] - he[0]), 4), round(float(he[1] - ce[1]), 4)]
    out["side_break_z"] = round(float(best[2]), 3) if best[2] is not None else None
    return out


def save_atlas(b, imgs):
    """The atlas PNGs next to the GLB (for the runtime shader and review)."""
    import os
    out = getattr(b, "out_dir", None)
    if not out:
        return
    for name, img in imgs.items():
        path = os.path.join(out, name + ".png")
        img2 = img.copy()
        img2.filepath_raw = path
        img2.file_format = "PNG"
        img2.save()
        bpy.data.images.remove(img2)


def bake_cap_texture(frame, g, E, ccfg, ccap):
    """The cap's hairline texture, rasterised from the groom: the strands
    (and vellus) rooted in a window of the front hairline, mapped into the
    cap's UV space (u = arc round the head / u_span, wrapping; v = depth
    behind the recessed hairline / v_span, in the texture's v band), over an
    opaque dark core from `core_m` on. So the game hairline has the groom's
    density ramp and strand directions."""
    surf = g["surf"]
    tc = ccfg["texture_cap"]
    cap = ccfg["cap"]
    w, h = tc["size"]
    ss = 3
    W, Hh = w * ss, h * ss
    lo, hi = (tc["v_band"][0] + 0.02, tc["v_band"][1] - 0.04) if tc.get("v_band") else (0.0, 0.998)
    span_deg = math.degrees(cap["u_span_m"] / cap["radius_m"])
    az0 = ccap["window_az_deg"]
    rng = np.random.default_rng(ccap["seed"])
    ev = g["eval"]
    n, m = g["n"], g["m"]
    strands = [E[j] for j in range(n) if abs(surf.azimuth(E[j][1]) - az0) < span_deg * 0.5
               and surf.d_eff(E[j][1]) < cap["v_span_m"]]
    vel = ev["pos"][n * m:].reshape(-1, 4, 3)
    strands += [q for q in vel if abs(surf.azimuth(q[0]) - az0) < span_deg * 0.5]
    cov = np.zeros((Hh, W), dtype=bool)
    val = np.ones((Hh, W), dtype=np.float32)
    for q in strands:
        uu, vv = [], []
        run = 0.0
        for i, p in enumerate(q[1:]):
            if i:
                run += float(np.linalg.norm(p - q[i]))
            d = surf.d_eff(p)
            sd = frame.signed(Vector(p))[2]
            if d > cap["v_span_m"] * 1.05 or run > ccap["max_len_m"] or sd > ccap["near_skin_m"]:
                break
            uu.append((surf.azimuth(p) - az0) / span_deg + 0.5)
            vv.append(lo + (hi - lo) * max(d, 0.0) / cap["v_span_m"])
        if len(uu) < 2:
            continue
        x, y = np.array(uu) * W, np.array(vv) * Hh
        seg = np.hypot(np.diff(x), np.diff(y))
        acc = np.concatenate([[0.0], np.cumsum(seg)])
        ns = max(int(acc[-1] / 0.5), 2)
        sp = np.linspace(0, acc[-1], ns)
        xi, yi = np.interp(sp, acc, x), np.interp(sp, acc, y)
        r = ccap["strand_px"] * ss * 0.5 * (1.15 - 0.3 * np.linspace(0, 1, ns))
        v_ = rng.lognormal(0, 0.25)
        for o in range(-int(np.ceil(r.max())), int(np.ceil(r.max())) + 1):
            ok = np.abs(o) <= r
            xo = (np.round(xi[ok] + o).astype(int)) % W
            yo = np.round(yi[ok]).astype(int)
            inb = (yo >= 0) & (yo < Hh)
            cov[yo[inb], xo[inb]] = True
            val[yo[inb], xo[inb]] = v_
    c = cov.reshape(h, ss, w, ss).mean(axis=(1, 3))
    vals = val.reshape(h, ss, w, ss).mean(axis=(1, 3))
    rows = (np.arange(h) + 0.5) / h
    d = (rows - lo) / (hi - lo) * cap["v_span_m"]
    core = nsmooth(ccap["core_m"][0], ccap["core_m"][1], d)
    core[(rows < lo) | (rows > hi)] = 0.0
    # The core fills in as streaks (alpha-tested, so a smooth ramp would cut
    # a hard line at 0.5): a per-column threshold, blurred across 1 px and
    # wavering a little along v, so strands start at staggered depths.
    thr = rng.random(w)
    thr = np.convolve(np.pad(thr, 1, mode="wrap"), np.ones(3) / 3, "valid")
    thr = (thr - thr.min()) / (thr.max() - thr.min() + 1e-9)
    wob = 0.08 * np.sin(rows[:, None] * 40.0 + rng.random(w)[None] * 6.3)
    core = np.clip((core[:, None] - (thr[None] * 0.9 + 0.05 + wob)) * 8.0 + 0.5, 0, 1)
    alpha = np.clip(c + core, 0, 1)
    alpha[(rows < lo - 0.01) | (rows > hi + 0.03)] = 0.0
    base = np.array([hair_mesh.srgb_to_linear(x) for x in hair_mesh.hex_rgb(tc["color"])])
    lin = base[None, None] * np.where(c > 0, vals, 1.0)[..., None]
    srgb = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.power(np.maximum(lin, 0), 1 / 2.4) - 0.055)
    rgba = np.concatenate([srgb, alpha[..., None]], axis=2).astype(np.float32)
    img = bpy.data.images.get("hair_cap") or bpy.data.images.new("hair_cap", w, h, alpha=True)
    img.pixels.foreach_set(rgba.ravel())
    img.pack()
    return img, len(strands)


def cap_mesh(b, frame, ccfg, g, shade):
    """The scalp cap (hair_clumps' construction), with its UV v measured
    from the groom's recessed hairline (Surface.d_eff), and the bmesh layers
    the cards write."""
    surf = g["surf"]
    keep = g["keep"]
    obj, bm = hair_mesh.shell_from_body(b, frame.body, keep, "Human.hair_export")
    cap = ccfg["cap"]
    hair_mesh.smooth_boundary(bm, frame.skin_bvh, cap["edge_smooth_iters"])
    hair_mesh.offset_shell(bm, lambda v: cap["offset_m"], cap["edge_taper"])
    uv = bm.loops.layers.uv.verify()
    uv2 = bm.loops.layers.uv.new("strand")
    col = bm.verts.layers.float_color.new("lock")
    hang_l = bm.verts.layers.float.new("hang_s")
    sector_l = bm.verts.layers.int.new("sector")
    tc = ccfg["texture_cap"]
    lo, hi = (tc["v_band"][0] + 0.02, tc["v_band"][1] - 0.04) if tc.get("v_band") else (0.0, 0.998)
    c = frame.center
    for f in bm.faces:
        f.material_index = 0
        for loop in f.loops:
            p = loop.vert.co
            u = math.atan2(p.x - c.x, -(p.y - c.y)) * cap["radius_m"] / cap["u_span_m"]
            d = max(surf.d_eff(tuple(p)), 0.0)
            loop[uv].uv = (u, lo + (hi - lo) * min(d / cap["v_span_m"], 1.0))
            loop[uv2].uv = (0.5, 0.0)
    for v in bm.verts:
        v[col] = (shade, shade, shade, 1.0)
    dl = bm.verts.layers.deform.verify()
    weights = {obj.vertex_groups["head"].index: 1.0}
    return obj, bm, uv, uv2, col, hang_l, sector_l, dl, weights
