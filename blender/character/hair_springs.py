"""Spring-bone chains for the generated hair (look-spec §5 bone plan: 12 hair
bones; NOTES §7 secondary motion: VRM-style spring chains in Rust).

The hair mesh is built 100 % on `head`. For every clump vertex hair_clumps
records a sector (which mass it hangs with) and `hang_s`: metres past the
point where its strand stops lying on the skull and starts to hang. bind()
turns each configured sector into a chain of bones parented to `head`, whose
stations sit on the sector's mean hanging path, and reweights the hanging
vertices by hang_s:

    head      1 at the hang point -> 0 at station 1
    bone k    hat: 0 at station k, 1 at station k+1, 0 at station k+2
              (the last bone stays 1 past its tail)

so a vertex has at most two chain bones plus `head` (<= 4 weights/vertex
holds). Vertices still on the skull keep `head`. The chains are plain deform
bones named `hair_<sector>_<k>`, so the runtime finds them by name; the spring
parameters (stiffness, drag, gravity, colliders) are runtime data, see
bench/m1/hair.md.
"""

import bpy
from mathutils import Vector

SECTORS = ["back_l", "back_r", "side_l", "side_r", "front_l", "front_r"]


def sector_id(frame, p, front_fall=0):
    """Index into SECTORS for a strand whose hang point is p (world). l/r
    follow the rig (the side of upperarm_l), not the world x sign."""
    lx = frame.bone["upperarm_l"].x - frame.center.x
    side = "l" if (p.x - frame.center.x) * lx >= 0 else "r"
    if front_fall:
        kind = "front"
    elif p.y > frame.center.y + 0.02:
        kind = "back"
    else:
        kind = "side"
    return SECTORS.index(f"{kind}_{side}")


def chain_weights(s, knots):
    """Weights of the chain's bones (bone k spans knots[k] .. knots[k+1]) at
    hang distance s. The remainder (1 - sum) goes to `head`."""
    n = len(knots) - 1
    w = [0.0] * n
    if s >= knots[n]:
        w[n - 1] = 1.0
        return w
    for k in range(n):
        if knots[k] <= s < knots[k + 1]:
            u = (s - knots[k]) / (knots[k + 1] - knots[k])
            w[k] = u
            if k > 0:
                w[k - 1] = 1.0 - u
            return w
    return w


def bind(b, obj, bm, dl, hang_l, sector_l, cfg):
    """Create the chains on the staged armature and reweight bm's hanging
    vertices. Returns a summary for stats.json (None if nothing hangs)."""
    chains = cfg["chains"]
    per = {name: [] for name in chains}
    for v in bm.verts:
        s = v[hang_l]
        if s <= 0.0:
            continue
        name = SECTORS[v[sector_l]]
        if name in per:
            per[name].append((s, v.co.copy()))

    sector_verts = {}
    for v in bm.verts:
        if v[hang_l] > 0.0:
            n = SECTORS[v[sector_l]]
            sector_verts[n] = sector_verts.get(n, 0) + 1
    arm = b.armature()
    mi = arm.matrix_world.inverted()
    built = {}
    stations_all = {}
    for name, n in chains.items():
        pts = per[name]
        if len(pts) < cfg["min_verts"] or n < 1:
            continue
        ss = sorted(s for s, _ in pts)
        s_max = max(ss[int(0.9 * (len(ss) - 1))], cfg["min_len_m"])
        seg = s_max / n
        knots = [k * seg for k in range(n + 1)]
        stations = []
        for k, sk in enumerate(knots):
            lo, hi = (0.0, seg * 0.35) if k == 0 else (sk - seg * 0.35, sk + seg * 0.35)
            if k == n:
                hi = 1e9
            sel = [co for s, co in pts if lo < s <= hi]
            if not sel:  # fall back to the nearest vertices by hang distance
                sel = [co for s, co in sorted(pts, key=lambda e: abs(e[0] - sk))[:12]]
            stations.append(sum(sel, Vector()) / len(sel))
        # Stations must descend the chain; a degenerate one would make a
        # zero-length bone.
        for k in range(1, n + 1):
            if (stations[k] - stations[k - 1]).length < 0.005:
                stations[k] = stations[k - 1] + Vector((0, 0, -0.005))
        built[name] = (knots, stations, len(pts))
        stations_all[name] = stations
    if not built:
        return None

    # Bones: a chain per sector, parented to `head` (UE-mannequin naming).
    prev_active = bpy.context.view_layer.objects.active
    bpy.context.view_layer.objects.active = arm
    was_hidden = arm.hide_get()
    arm.hide_set(False)
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm.data.edit_bones
    names = {}
    for name, (knots, stations, _) in built.items():
        prev = eb["head"]
        names[name] = []
        for k in range(len(knots) - 1):
            bn = eb.new(f"hair_{name}_{k + 1:02d}")
            bn.head = mi @ stations[k]
            bn.tail = mi @ stations[k + 1]
            bn.parent = prev
            bn.use_connect = k > 0
            bn.use_deform = True
            prev = bn
            names[name].append(bn.name)
    bpy.ops.object.mode_set(mode="OBJECT")
    arm.hide_set(was_hidden)
    bpy.context.view_layer.objects.active = prev_active

    groups = {name: [obj.vertex_groups.new(name=bn).index for bn in bones]
              for name, bones in names.items()}
    head_g = obj.vertex_groups["head"].index
    rebound = 0
    for v in bm.verts:
        s = v[hang_l]
        if s <= 0.0:
            continue
        name = SECTORS[v[sector_l]]
        if name not in built:
            continue
        knots = built[name][0]
        w = chain_weights(s, knots)
        for g, wk in zip(groups[name], w):
            if wk > 1e-4:
                v[dl][g] = wk
        head_w = 1.0 - sum(w)
        if head_w > 1e-4:
            v[dl][head_g] = head_w
        elif head_g in v[dl]:
            del v[dl][head_g]
        rebound += 1
    r = lambda p: [round(x, 4) for x in p]
    return {"bones": sum(len(v) for v in names.values()),
            "rebound_verts": rebound, "sector_verts": sector_verts,
            "chains": {name: {"bones": names[name], "knots_m": [round(k, 3) for k in built[name][0]],
                              "stations": [r(p) for p in stations_all[name]],
                              "verts": built[name][2]} for name in built}}
