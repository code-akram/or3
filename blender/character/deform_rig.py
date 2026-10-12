"""Helper and twist bones, weight remaps and garment weight smoothing (m1 v2
Track F; bench/m1/v2/deform.md). Runs on the staged export objects from
rig.post, after head_refine (final topology) and before budgets.

Bones added (UE-mannequin naming; every one a deform bone the runtime drives
with the rules in character.rig.json, see deform_runtime.py):

    upperarm_twist_01_{l,r}  child of upperarm, cancels the arm's twist near the
                             shoulder (factor -1), ramping to none at the elbow
    lowerarm_twist_01_{l,r}  child of lowerarm, takes half the hand's twist
                             (pronation) along the forearm: no candy wrapper
    thigh_twist_01_{l,r}     as upperarm_twist, for the hip
    deltoid_helper_{l,r}     child of clavicle at the shoulder joint, 50 % of
                             the arm's swing (direction.md §2 Track F)
    hip_helper_{l,r}         child of pelvis at the hip joint, 50 % of the thigh swing
    skirt_{front,side,back}_{l,r}  child of pelvis, pivot at the hip joint: the
                             jacket skirt panels follow the thigh with per-sector
                             gains instead of being skinned to it (no riding up)

Weight edits (generic: they work on any mesh from its existing weights and
vertex positions, so they survive a garment rebuild):

* half-joint remap at the shoulder and hip: where a vertex blends the trunk
  (clavicle/spine/pelvis) with the limb, the middle of the blend moves to the
  50 % helper, so linear blend skinning interpolates over half the angle
  (less collapse, no sleeve-head pinch);
* twist splits by position along the bone;
* 3-bone finger falloff: each finger's share is redistributed over hand,
  01, 02, 03 by position along the finger with a smooth band at each knuckle;
* garments: spatial (not topological) Gaussian smoothing of the weights, so
  separate islands that meet at a seam (sleeve and armhole, collar and
  lapel) carry the same weights and stay closed; then the same remaps; the
  skirt meshes get the skirt bones;
* every mesh: at most 4 influences, normalised.
"""

import json
import math
import os

import bpy
import numpy as np
from mathutils import Vector
from mathutils.kdtree import KDTree

from . import deform_runtime as drt

FINGERS = ("thumb", "index", "middle", "ring", "pinky")
SKIP = ("hair", "beard", "brows", "eyebrow", "eyelash", "eyes", "teeth", "tongue", "low-poly")

DEFAULTS = {
    "twist": {"upperarm": -1.0, "lowerarm": 0.5, "thigh": -1.0},
    "deltoid": {"factor": 0.5, "radius_m": 0.15},
    "hip": {"factor": 0.5, "radius_m": 0.20},
    "fingers": {"band": 0.28},
    # garments: name fragments -> Gaussian sigma (m) of the spatial weight smoothing
    "garments": {"suit_jacket": 0.025, "suit_shirt": 0.015, "suit_waistcoat": 0.015,
                 "suit_trousers": 0.02, "suit_tie": 0.01, "suit_buttons": 0.0},
    "skirt": {"meshes": ["suit_jacket"], "top_above_hip_m": 0.09, "ramp_m": 0.08,
              "front_band_m": 0.02,
              # per sector: gains for thigh flexion (+ forward, - back) and abduction
              "gains": {"front": {"flex+": 0.95, "flex-": 0.35, "abd+": 0.5, "abd-": 0.2},
                        "side": {"flex+": 0.45, "flex-": 0.45, "abd+": 0.85, "abd-": 0.2},
                        "back": {"flex+": 0.0, "flex-": 0.85, "abd+": 0.45, "abd-": 0.2}}},
    # torso garments whose chest/back core ignores the arms (fraction of the
    # shoulder joint's |x|: full trunk inside the first, none past the second)
    "arm_free": {"meshes": ["suit_jacket", "suit_waistcoat", "suit_shirt"], "x_ramp": [0.5, 0.85]},
    "max_influences": 4,
}


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


# ---------------------------------------------------------------- bones

def _sides(arm):
    return [s for s in ("l", "r") if f"upperarm_{s}" in arm.data.bones]


def add_bones(arm, skirt):
    """Create the helper bones (edit mode). Returns {name: parent}."""
    prev = bpy.context.view_layer.objects.active
    bpy.context.view_layer.objects.active = arm
    hidden = arm.hide_get()
    arm.hide_set(False)
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm.data.edit_bones
    made = {}

    def along(src, parent, name, t0, t1):
        b = eb[src]
        d = b.tail - b.head
        nb = eb.new(name)
        nb.head = b.head + d * t0
        nb.tail = b.head + d * t1
        nb.roll = b.roll
        nb.parent = eb[parent]
        nb.use_connect = False
        nb.use_deform = True
        made[name] = parent

    for s in _sides(arm):
        along(f"upperarm_{s}", f"upperarm_{s}", f"upperarm_twist_01_{s}", 0.0, 0.5)
        along(f"lowerarm_{s}", f"lowerarm_{s}", f"lowerarm_twist_01_{s}", 0.5, 1.0)
        along(f"thigh_{s}", f"thigh_{s}", f"thigh_twist_01_{s}", 0.0, 0.5)
        along(f"upperarm_{s}", f"clavicle_{s}", f"deltoid_helper_{s}", 0.0, 0.4)
        along(f"thigh_{s}", "pelvis", f"hip_helper_{s}", 0.0, 0.4)
        if skirt:
            h = eb[f"thigh_{s}"].head.copy()
            sx = 1.0 if h.x > 0 else -1.0
            for sector, off in (("front", (0.03, -0.12, -0.30)), ("side", (0.10, 0.0, -0.30)),
                                ("back", (0.03, 0.12, -0.30))):
                n = f"skirt_{sector}_{s}"
                nb = eb.new(n)
                nb.head = h
                nb.tail = h + Vector((off[0] * sx, off[1], off[2]))
                nb.parent = eb["pelvis"]
                nb.use_deform = True
                made[n] = "pelvis"
    bpy.ops.object.mode_set(mode="OBJECT")
    arm.hide_set(hidden)
    bpy.context.view_layer.objects.active = prev
    return made


def rules(arm, made, cfg):
    """character.rig.json (glTF model space; deform_runtime.py)."""
    B = arm.data.bones
    g = drt.bl_to_gl

    def bdir(n):
        b = B[n]
        return (b.tail_local - b.head_local).normalized()

    helpers = []
    for s in _sides(arm):
        sx = 1.0 if B[f"upperarm_{s}"].head_local.x > 0 else -1.0
        helpers += [
            {"type": "swing", "bone": f"deltoid_helper_{s}", "source": f"upperarm_{s}",
             "axis": g(bdir(f"upperarm_{s}")), "factor": cfg["deltoid"]["factor"], "frame": f"clavicle_{s}"},
            {"type": "swing", "bone": f"hip_helper_{s}", "source": f"thigh_{s}",
             "axis": g(bdir(f"thigh_{s}")), "factor": cfg["hip"]["factor"], "frame": "pelvis"},
            {"type": "twist", "bone": f"upperarm_twist_01_{s}", "source": f"upperarm_{s}",
             "axis": g(bdir(f"upperarm_{s}")), "factor": cfg["twist"]["upperarm"], "frame": f"upperarm_{s}"},
            {"type": "twist", "bone": f"lowerarm_twist_01_{s}", "source": f"hand_{s}",
             "axis": g(bdir(f"lowerarm_{s}")), "factor": cfg["twist"]["lowerarm"], "frame": f"lowerarm_{s}"},
            {"type": "twist", "bone": f"thigh_twist_01_{s}", "source": f"thigh_{s}",
             "axis": g(bdir(f"thigh_{s}")), "factor": cfg["twist"]["thigh"], "frame": f"thigh_{s}"},
        ]
        for sector in ("front", "side", "back"):
            n = f"skirt_{sector}_{s}"
            if n in made:
                helpers.append({"type": "follow", "bone": n, "source": f"thigh_{s}", "frame": "pelvis",
                                "rest_dir": g(bdir(f"thigh_{s}")), "flex_axis": g(Vector((-1, 0, 0))),
                                "abd_axis": g(Vector((0, -sx, 0))),
                                "gain": cfg["skirt"]["gains"][sector]})
    return [h for h in helpers if h["bone"] in B]


# ---------------------------------------------------------------- weights

def bone_names(arm):
    return [b.name for b in arm.data.bones if b.use_deform]


def read(o, names):
    idx = {n: i for i, n in enumerate(names)}
    gmap = {g.index: idx.get(g.name) for g in o.vertex_groups}
    W = np.zeros((len(o.data.vertices), len(names)), dtype=np.float64)
    for v in o.data.vertices:
        for ge in v.groups:
            j = gmap.get(ge.group)
            if j is not None:
                W[v.index, j] = ge.weight
    co = np.empty(len(o.data.vertices) * 3)
    o.data.vertices.foreach_get("co", co)
    return W, co.reshape(-1, 3)


def write(o, W, names, thr=1e-4):
    V = W.shape[0]
    allv = list(range(V))
    for j, n in enumerate(names):
        col = W[:, j]
        vg = o.vertex_groups.get(n)
        nz = np.nonzero(col > thr)[0]
        if vg is None:
            if len(nz) == 0:
                continue
            vg = o.vertex_groups.new(name=n)
        else:
            vg.remove(allv)
        # group equal weights to cut the call count
        vals = np.round(col[nz], 5)
        order = np.argsort(vals)
        nz, vals = nz[order], vals[order]
        if len(nz) == 0:
            continue
        cuts = np.nonzero(np.diff(vals))[0] + 1
        for a, b in zip(np.r_[0, cuts], np.r_[cuts, len(nz)]):
            vg.add(nz[a:b].tolist(), float(vals[a]), "REPLACE")


def prune(W, k):
    if W.shape[1] > k:
        part = np.argpartition(-W, k, axis=1)[:, k:]
        np.put_along_axis(W, part, 0.0, axis=1)
    W[W < 0.005] = 0.0
    s = W.sum(1, keepdims=True)
    s[s == 0] = 1.0
    return W / s


class Geo:
    def __init__(self, arm, names):
        self.B = arm.data.bones
        self.j = {n: i for i, n in enumerate(names)}

    def head(self, n):
        return np.array(self.B[n].head_local)

    def tail(self, n):
        return np.array(self.B[n].tail_local)

    def t_along(self, co, n):
        h, t = self.head(n), self.tail(n)
        d = t - h
        L2 = d.dot(d)
        return (co - h) @ d / L2

    def col(self, n):
        return self.j.get(n)


def half_joint(W, co, G, prox, dist, helper, radius):
    """Move the middle of a trunk-limb blend onto a 50 % swing helper.

    b = limb share of (trunk + limb). The helper takes h = 1 - |2b - 1|; the
    residual stays on the trunk (b < 0.5) or the limb (b > 0.5), so the
    effective rotation is still b * theta but interpolated over theta/2.
    Faded out (blended back to the original weights) past `radius` from the
    joint."""
    jp = [G.col(n) for n in prox if G.col(n) is not None]
    jd, jh = G.col(dist), G.col(helper)
    if jd is None or jh is None or not jp:
        return 0
    c = W[:, jp].sum(1)
    u = W[:, jd]
    tot = c + u
    r = np.linalg.norm(co - G.head(dist), axis=1)
    fade = 1.0 - smoothstep(radius, radius * 1.4, r)
    sel = (c > 1e-4) & (u > 1e-4) & (fade > 0)
    if not sel.any():
        return 0
    b = u / np.maximum(tot, 1e-9)
    h = 1.0 - np.abs(2 * b - 1)
    rest = (1.0 - h) * tot
    newc = np.where(b < 0.5, rest, 0.0)
    newu = np.where(b >= 0.5, rest, 0.0)
    scale = newc / np.maximum(c, 1e-9)
    f = np.where(sel, fade, 0.0)
    for j in jp:
        W[:, j] = W[:, j] * (1 - f) + W[:, j] * scale * f
    W[:, jd] = W[:, jd] * (1 - f) + newu * f
    W[:, jh] = W[:, jh] + h * tot * f
    return int(sel.sum())


def twist_split(W, co, G, bone, twist, ramp):
    jb, jt = G.col(bone), G.col(twist)
    if jb is None or jt is None:
        return 0
    t = G.t_along(co, bone)
    share = ramp(t)
    moved = W[:, jb] * share
    W[:, jt] += moved
    W[:, jb] -= moved
    return int((moved > 1e-4).sum())


def finger_falloff(W, co, G, s, band):
    """Redistribute each finger's share over hand/01/02/03 by position along the finger."""
    jh = G.col(f"hand_{s}")
    if jh is None:
        return 0
    n = 0
    for f in FINGERS:
        names = [f"{f}_0{k}_{s}" for k in (1, 2, 3)]
        js = [G.col(x) for x in names]
        if any(j is None for j in js):
            continue
        share = W[:, js].sum(1)
        sel = share > 1e-4
        if not sel.any():
            continue
        pts = [G.head(x) for x in names] + [G.tail(names[2])]
        # param s along the polyline: segment k covers [k, k+1]
        P = co[sel]
        best = np.full(len(P), np.inf)
        sp = np.zeros(len(P))
        for k in range(3):
            a, b = pts[k], pts[k + 1]
            d = b - a
            t = np.clip((P - a) @ d / d.dot(d), -0.6 if k == 0 else 0.0, 1.0 if k < 2 else 1.5)
            q = a + t[:, None] * d
            dist = np.linalg.norm(P - q, axis=1)
            better = dist < best
            best = np.where(better, dist, best)
            sp = np.where(better, k + t, sp)
        S = [smoothstep(k - band, k + band, sp) for k in range(3)]
        wh = 1 - S[0]
        w1 = S[0] - S[1]
        w2 = S[1] - S[2]
        w3 = S[2]
        sh = share[sel]
        W[sel, jh] += sh * wh
        W[sel, js[0]] = sh * w1
        W[sel, js[1]] = sh * w2
        W[sel, js[2]] = sh * w3
        n += int(sel.sum())
    return n


class Neighbours:
    """Gaussian neighbourhoods over a point set (rest positions), across mesh
    islands: smooth(F) averages any per-vertex field."""

    def __init__(self, co, sigma):
        self.sigma = sigma
        kd = KDTree(len(co))
        for i, p in enumerate(co):
            kd.insert(p, i)
        kd.balance()
        self.nb = []
        for p in co:
            hits = kd.find_range(p, 2.2 * sigma)
            idx = np.array([h[1] for h in hits], dtype=np.int64)
            d = np.array([h[2] for h in hits])
            k = np.exp(-0.5 * (d / sigma) ** 2)
            self.nb.append((idx, k / k.sum()))

    def smooth(self, F, iters=1):
        for _ in range(iters):
            out = np.empty_like(F)
            for i, (idx, k) in enumerate(self.nb):
                out[i] = k @ F[idx]
            F = out
        return F


def spatial_smooth(W, co, sigma, iters=2):
    if sigma <= 0:
        return W
    return Neighbours(co, sigma).smooth(W, iters)


def arm_free_core(W, co, G, sides, inner=0.5, outer=0.85):
    """Torso garments: no arm influence on the chest/back core (lapels,
    collar, front panels follow the trunk, not the arm). Arm weights inside
    |x| < inner * shoulder x go to the clavicle, ramped out to outer."""
    n = 0
    for s in sides:
        sh = G.head(f"upperarm_{s}")
        xs = abs(sh[0])
        sgn = 1.0 if sh[0] > 0 else -1.0
        arm = [G.col(c) for c in G.j if c.endswith(f"_{s}") and c.startswith(
            ("upperarm", "lowerarm", "hand", "deltoid"))]
        arm = [j for j in arm if j is not None]
        jc = G.col(f"clavicle_{s}")
        if jc is None or not arm:
            continue
        x = co[:, 0] * sgn
        f = 1.0 - smoothstep(inner * xs, outer * xs, x)
        f = np.where(x > -0.05, f, 1.0)
        f = np.where(co[:, 2] > sh[2] - 0.35, f, 0.0)
        moved = W[:, arm] * f[:, None]
        W[:, arm] -= moved
        W[:, jc] += moved.sum(1)
        n += int((moved.sum(1) > 1e-4).sum())
    return n


def skirt_weights(W, co, G, s_cfg, sides):
    """Jacket skirt below the hip line: leg weights -> skirt bones by azimuth."""
    legs = [n for n in G.j if n.startswith(("thigh", "calf", "foot", "ball", "hip_helper"))]
    arms = [n for n in G.j if n.startswith(("upperarm", "lowerarm", "hand", "deltoid"))
            or any(n.startswith(f) for f in FINGERS)]
    jl = [G.col(n) for n in legs]
    ja = [G.col(n) for n in arms]
    hip_z = float(np.mean([G.head(f"thigh_{s}")[2] for s in sides]))
    z_top = hip_z + s_cfg["top_above_hip_m"]
    z = co[:, 2]
    tot = W.sum(1)
    sel = (z < z_top) & (W[:, ja].sum(1) < 0.3 * np.maximum(tot, 1e-9)) & (tot > 0)
    r = smoothstep(z_top, z_top - s_cfg["ramp_m"], z)
    cx = 0.0
    cy = float(np.mean([G.head(f"thigh_{s}")[1] for s in sides]))
    az = np.degrees(np.arctan2(co[:, 0] - cx, -(co[:, 1] - cy)))  # 0 front, +90 left side
    left = co[:, 0] > 0 if G.head("thigh_l")[0] > 0 else co[:, 0] < 0
    a = np.abs(az)
    # sector weights on one side: front centre 25 deg, side 90, back 155
    wf = np.clip((90 - a) / 65, 0, 1)
    wb = np.clip((a - 90) / 65, 0, 1)
    ws = 1 - wf - wb
    # midline blend (front opening, back vent)
    band = s_cfg["front_band_m"]
    sidew = smoothstep(-band, band, co[:, 0] if G.head("thigh_l")[0] > 0 else -co[:, 0])
    n = 0
    for s, f in (("l", sidew), ("r", 1 - sidew)):
        for sector, w in (("front", wf), ("side", ws), ("back", wb)):
            j = G.col(f"skirt_{sector}_{s}")
            if j is None:
                continue
            add = np.where(sel, r * tot * w * f, 0.0)
            W[:, j] += add
    keep = np.where(sel, 1 - r, 1.0)
    # the remaining (1-r) share: trunk only (legs move to the pelvis)
    jp = G.col("pelvis")
    legw = W[:, jl].sum(1)
    for j in jl:
        W[:, j] = np.where(sel, 0.0, W[:, j])
    if jp is not None:
        W[:, jp] = np.where(sel, W[:, jp] + legw, W[:, jp])
    skirt_cols = [G.col(f"skirt_{a}_{s}") for a in ("front", "side", "back") for s in ("l", "r")]
    skirt_cols = [j for j in skirt_cols if j is not None]
    other = [j for j in range(W.shape[1]) if j not in skirt_cols]
    W[:, other] *= keep[:, None]
    n = int(sel.sum())
    _ = left
    return n


def remap_mesh(o, arm, names, cfg, garment_sigma=None, skirt=False):
    W, co = read(o, names)
    G = Geo(arm, names)
    info = {"verts": len(co)}
    sides = _sides(arm)
    if garment_sigma:
        W = spatial_smooth(W, co, garment_sigma)
        info["smooth_sigma_m"] = garment_sigma
        if any(k in o.name for k in cfg["arm_free"]["meshes"]):
            info["arm_free"] = arm_free_core(W, co, G, sides, *cfg["arm_free"]["x_ramp"])
    for s in sides:
        info[f"deltoid_{s}"] = half_joint(W, co, G, [f"clavicle_{s}", "spine_03", "spine_02"],
                                          f"upperarm_{s}", f"deltoid_helper_{s}", cfg["deltoid"]["radius_m"])
        info[f"hip_{s}"] = half_joint(W, co, G, ["pelvis", "spine_01"], f"thigh_{s}",
                                      f"hip_helper_{s}", cfg["hip"]["radius_m"])
        info[f"uatwist_{s}"] = twist_split(W, co, G, f"upperarm_{s}", f"upperarm_twist_01_{s}",
                                           lambda t: 1 - smoothstep(0.1, 0.8, t))
        info[f"latwist_{s}"] = twist_split(W, co, G, f"lowerarm_{s}", f"lowerarm_twist_01_{s}",
                                           lambda t: smoothstep(0.05, 0.65, t))
        info[f"thtwist_{s}"] = twist_split(W, co, G, f"thigh_{s}", f"thigh_twist_01_{s}",
                                           lambda t: 1 - smoothstep(0.1, 0.8, t))
        if garment_sigma is None:
            info[f"fingers_{s}"] = finger_falloff(W, co, G, s, cfg["fingers"]["band"])
    if skirt:
        info["skirt_verts"] = skirt_weights(W, co, G, cfg["skirt"], sides)
    W = prune(W, cfg["max_influences"])
    write(o, W, names)
    info["max_infl"] = int((W > 0).sum(1).max())
    return info


def run(b, cfg):
    arm = b.armature()
    skirt_meshes = [o for o in b.meshes() if any(k in o.name for k in cfg["skirt"]["meshes"])]
    made = add_bones(arm, bool(skirt_meshes))
    names = bone_names(arm)
    out = {"bones_added": sorted(made), "bones_total": len(arm.data.bones), "meshes": {}}
    for o in b.meshes():
        if any(k in o.name.lower() for k in SKIP):
            continue
        if not o.vertex_groups:
            continue
        sigma = None
        if o.name != "Human_export":
            sigma = next((v for k, v in cfg["garments"].items() if k in o.name), None)
            if sigma is None:
                continue  # shoes and anything unknown keep their weights
        out["meshes"][o.name] = remap_mesh(o, arm, names, cfg, garment_sigma=sigma,
                                           skirt=o in skirt_meshes)
    R = {"version": 1, "doc": "blender/character/deform_runtime.py", "space": "glTF model, bind pose",
         "helpers": rules(arm, made, cfg), "morphs": []}
    return R, out


def write_rules(b, R):
    path = os.path.join(b.out_dir, "character.rig.json") if getattr(b, "out_dir", None) else None
    if path:
        with open(path, "w") as f:
            json.dump(R, f, indent=1)
    arm = b.armature()
    arm["deform_rules"] = json.dumps(R)
    return path


_ = math
