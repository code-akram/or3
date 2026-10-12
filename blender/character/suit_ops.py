"""Mesh helpers for the suit track: splitting the stock shell and tailoring the
stock trousers (blender/character/suit.py). The built garments live in
suit_build / suit_jacket / suit_inner.

World space = object space for every staged mesh (identity transforms, Z up,
front = -Y). Skin weights travel in each bmesh's deform layer.
"""

import bmesh
import bpy


def to_bm(o):
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bm.verts.ensure_lookup_table()
    return bm


def write_bm(bm, o):
    bm.to_mesh(o.data)
    o.data.update()
    bm.free()


def dominant(v, dl, names, allowed):
    best, bw = None, 0.0
    for g, w in v[dl].items():
        n = names[g]
        if n in allowed and w > bw:
            best, bw = n, w
    return best


def components(bm):
    """Vertex-index sets of the connected (loose) parts."""
    seen, out = set(), []
    for v in bm.verts:
        if v.index in seen:
            continue
        stack, comp = [v], set()
        seen.add(v.index)
        while stack:
            x = stack.pop()
            comp.add(x.index)
            for e in x.link_edges:
                y = e.other_vert(x)
                if y.index not in seen:
                    seen.add(y.index)
                    stack.append(y)
        out.append(comp)
    return out


def new_part(src, keep, name):
    """A new object holding only the vertices `keep` of src (same groups, parent,
    modifiers, materials)."""
    bm = to_bm(src)
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.index not in keep], context="VERTS")
    o = src.copy()
    o.data = bpy.data.meshes.new(name)
    for g in src.vertex_groups:
        o.vertex_groups.new(name=g.name)
    for m in src.data.materials:
        o.data.materials.append(m)
    o.name = name
    for c in src.users_collection:
        c.objects.link(o)
    write_bm(bm, o)
    return o


def drop(b, o):
    if o in b.export_objs:
        b.export_objs.remove(o)
    bpy.data.objects.remove(o, do_unlink=True)


def split_shell(b, shell, part):
    """The suits01 shell by loose part, classified by size and position:
    jacket, trousers, shirt, tie blade, knot, two buttons."""
    bm = to_bm(shell)
    comps = components(bm)
    info = []
    for c in comps:
        ps = [bm.verts[i].co for i in c]
        xs, zs = [p.x for p in ps], [p.z for p in ps]
        info.append({"keep": c, "n": len(c), "zmin": min(zs), "zmax": max(zs),
                     "xspan": max(xs) - min(xs), "diag": (max(zs) - min(zs)) + max(xs) - min(xs)})
    bm.free()
    info.sort(key=lambda d: -d["n"])
    roles = {"jacket": info[0]}
    rest = info[1:]
    roles["trousers"] = min(rest, key=lambda d: d["zmin"])
    rest.remove(roles["trousers"])
    btns = [d for d in rest if d["diag"] < 0.08]
    rest = [d for d in rest if d not in btns]
    roles["shirt"] = max(rest, key=lambda d: d["xspan"])
    rest.remove(roles["shirt"])
    roles["tie"], roles["knot"] = sorted(rest, key=lambda d: d["zmin"])
    out = {}
    for role, d in roles.items():
        out[role] = new_part(shell, d["keep"], part.format(role))
    out["buttons"] = [new_part(shell, d["keep"], part.format(f"oldbutton{i}"))
                      for i, d in enumerate(btns)]
    b.export_objs.remove(shell)
    bpy.data.objects.remove(shell, do_unlink=True)
    b.export_objs += [out[k] for k in ("jacket", "trousers", "shirt", "tie", "knot")]
    b.export_objs += out["buttons"]
    return out


# --- trousers (stock shell) ----------------------------------------------------------------

def stretch_below(verts, z_top, z_from, z_to, weight=None):
    """Remap z below z_top linearly so z_from lands on z_to (x, y unchanged).
    weight(v) in [0, 1] blends the stretch per vertex (1 = full)."""
    k = (z_top - z_to) / (z_top - z_from)
    for v in verts:
        if v.co.z < z_top:
            t = 1.0 if weight is None else weight(v)
            z = z_top - (z_top - v.co.z) * k
            v.co.z = v.co.z + (z - v.co.z) * t


def walk_up(start, z_stop, x_target, max_dx=0.02):
    """Edge chain from start going up as vertically as possible, staying within
    max_dx of x_target. Returns the edges."""
    v, edges = start, []
    while v.co.z < z_stop:
        best, bs = None, -1.0
        for e in v.link_edges:
            o = e.other_vert(v)
            d = o.co - v.co
            if d.z <= 1e-6 or abs(o.co.x - x_target) > max_dx:
                continue
            s = d.z / d.length - 2.0 * abs(o.co.x - x_target)
            if s > bs:
                best, bs = e, s
        if best is None:
            break
        edges.append(best)
        v = best.other_vert(v)
    return edges


def crease(bm, verts, side_sign, front, z_lo, z_hi, depth):
    """Trouser crease on one leg: from the hem vertex nearest the leg's front
    (front=True) or back centre, walk up and push the chain out by depth; the
    chain's edges are marked sharp. Returns the chain's vertices in order."""
    leg = [v for v in verts if v.co.x * side_sign > 0.005 and v.co.z < z_lo + 0.03]
    if not leg:
        return []
    start = (min if front else max)(leg, key=lambda v: v.co.y)
    edges = walk_up(start, z_hi, start.co.x, max_dx=0.03)
    chain, v = [start], start
    for e in edges:
        e.smooth = False
        v = e.other_vert(v)
        chain.append(v)
    for v in chain:
        v.co.y += -depth if front else depth
    return chain


def leg_uvs(bm, tag_layer, uv_layer):
    """Cylindrical metric UVs per leg (u = arc around the leg's own axis, v = z);
    the wrap sits at the inseam. Faces are tagged 1 (left) / 2 (right).
    Returns per leg the circumference and the u of the outseam and inseam."""
    import math
    legs = {}
    for sign, tag in ((1, 1), (-1, 2)):
        vs = [v for v in bm.verts if v.co.x * sign > 0]
        xs = [v.co.x for v in vs if v.co.z < 0.6]
        ys = [v.co.y for v in vs if v.co.z < 0.6]
        cx, cy = 0.5 * (min(xs) + max(xs)), 0.5 * (min(ys) + max(ys))
        rad = sum(math.hypot(v.co.x - cx, v.co.y - cy) for v in vs if v.co.z < 0.6) / max(
            1, sum(1 for v in vs if v.co.z < 0.6))
        circ = 2 * math.pi * rad
        legs[tag] = {"c": (cx, cy), "circ": circ, "sign": sign}

    def u_of(v, L):
        cx, cy = L["c"]
        a = math.atan2(v.co.y - cy, (v.co.x - cx) * L["sign"])  # 0 = outseam, +-pi = inseam
        return (a + math.pi) / (2 * math.pi) * L["circ"]

    for f in bm.faces:
        cx = f.calc_center_median().x
        tag = 1 if cx > 0 else 2
        f[tag_layer] = tag
        L = legs[tag]
        us = [u_of(l.vert, L) for l in f.loops]
        if max(us) - min(us) > 0.5 * L["circ"]:  # across the wrap
            us = [u + L["circ"] if u < 0.5 * L["circ"] else u for u in us]
        for l, u in zip(f.loops, us):
            l[uv_layer].uv = (u, l.vert.co.z)
    return {t: {"circ": L["circ"], "outseam_u": 0.5 * L["circ"], "u_of": (lambda v, L=L: u_of(v, L))}
            for t, L in legs.items()}


def tailor_trousers(tr, T):
    """Quarter break, leg-opening taper, creases, on the stock trousers.
    Returns (measurements, marks) with marks per panel tag for suit_textures."""
    bm = to_bm(tr)
    zmin = min(v.co.z for v in bm.verts)
    out = {"hem_before_z": round(zmin, 4)}
    for sign in (1, -1):
        hem = [v for v in bm.verts if v.co.x * sign > 0 and v.co.z < zmin + 0.04]
        y0, y1 = min(v.co.y for v in hem), max(v.co.y for v in hem)
        leg = [v for v in bm.verts if v.co.x * sign > 0]
        stretch_below(leg, T["break_from_z"], zmin, T["back_hem_m"],
                      weight=lambda v: min(1.0, max(0.0, (v.co.y - y0) / (y1 - y0))))
        # taper: scale the leg about its own centre, 1 at taper_from_z -> opening at the hem
        lo = [v for v in leg if v.co.z < T["taper_from_z"]]
        hem = [v for v in lo if v.co.z < zmin + 0.06]
        cx = sum(v.co.x for v in hem) / len(hem)
        cy = sum(v.co.y for v in hem) / len(hem)
        half = max(abs(v.co.x - cx) for v in hem)
        k_hem = min(1.0, T["opening_half_m"] / max(half, 1e-6))
        for v in lo:
            t = (T["taper_from_z"] - v.co.z) / (T["taper_from_z"] - zmin)
            k = 1 + (k_hem - 1) * min(1.0, max(0.0, t))
            v.co.x = cx + (v.co.x - cx) * k
            v.co.y = cy + (v.co.y - cy) * k
    out["back_hem_z"] = round(min(v.co.z for v in bm.verts), 4)
    zlo = min(v.co.z for v in bm.verts)
    tag_layer = bm.faces.layers.int.get("panel") or bm.faces.layers.int.new("panel")
    uv_layer = bm.loops.layers.uv.verify()
    legs = leg_uvs(bm, tag_layer, uv_layer)
    marks = {}
    out["crease_edges"] = {}
    for sign, tag in ((1, 1), (-1, 2)):
        L = legs[tag]
        for front, zhi in ((True, 0.98), (False, 0.80)):
            chain = crease(bm, list(bm.verts), sign, front, zlo, zhi, T["crease_depth_m"])
            out["crease_edges"][f"{'L' if sign > 0 else 'R'}-{'front' if front else 'back'}"] = len(chain)
            if len(chain) >= 2:
                pts = [(L["u_of"](v), v.co.z) for v in chain]
                marks.setdefault(tag, []).append(("crease", pts))
        # outseam and inseam, hem edge, a jetted back pocket
        z_top = max(v.co.z for v in bm.verts if v.co.x * sign > 0)
        u_out = L["outseam_u"]
        marks[tag].append(("seam", [(u_out, zlo + 0.01), (u_out, z_top - 0.02)]))
        marks[tag].append(("seam", [(0.012, zlo + 0.01), (0.012, 0.62)]))
        marks[tag].append(("edge", [(0.0, zlo + 0.003), (L["circ"], zlo + 0.003)], {"inside_sign": 1.0}))
        u_back = u_out + 0.25 * L["circ"] * (1 if sign > 0 else -1)
        marks[tag].append(("welt", [(u_back - 0.06, 0.96), (u_back + 0.06, 0.96)]))
    for f in bm.faces:
        f.smooth = True
    write_bm(bm, tr)
    return out, marks
