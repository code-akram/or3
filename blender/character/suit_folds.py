"""Modelled folds in the garment geometry: the elbow crook and the back of the knee.

The cloth sim (suit_drape) carries the fine folds in the normal map. At bust
and full distance only geometry reads, and the sim's broad component there is
a single dent at the crook. Here a few soft crescent folds are modelled where a
tailored suit has them at rest: across the inside of the elbow (the sleeve
follows the arm's rest flex) and across the back of the knee (the trouser leg
gathers there when standing). Each fold set is a damped sine along the limb
through the joint, bent into a crescent toward the sides and faded round the
limb away from the fold side:

    h = A sin(2 pi (s - s0 - k (1 - cos th)) / lam + phase) exp(-((s - s0) / sigma)^2) max(0, cos th)^p

s runs along the limb (the bisector of the two bones) from the joint, th
round it from the fold side (the crook: the inside of the bend; the knee: the
back). phase -pi/2 puts a valley at the joint with a ridge either side.
Vertices move along their normals (merged over split seams); inward moves stop
clear_m short of the body. The game mesh carries these: the sleeve rows are
1.1 cm apart and the knee rows 1.2 cm (suit.DEFAULTS), four or more per
wavelength. Options: suit.folds (DEFAULTS).
"""

import math

import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

DEFAULTS = {
    "enabled": True,
    "clear_m": 0.003,
    "elbow": {"amp_m": 0.005, "wavelength_m": 0.05, "sigma_m": 0.05, "crescent_m": 0.012,
              "power": 1.5, "phase": -math.pi / 2, "offset_m": 0.0},
    "knee_back": {"amp_m": 0.004, "wavelength_m": 0.045, "sigma_m": 0.045, "crescent_m": 0.010,
                  "power": 1.5, "phase": -math.pi / 2, "offset_m": 0.0},
}


def _joint(arm, name):
    return arm.matrix_world @ arm.data.bones[name].head_local


def frames(arm):
    """[(region, side, joint, bisector b, fold-side direction c)] from the rig at rest."""
    out = []
    for s, sx in (("l", 1.0), ("r", -1.0)):
        U, E, W = _joint(arm, f"upperarm_{s}"), _joint(arm, f"lowerarm_{s}"), _joint(arm, f"hand_{s}")
        u, f = (E - U).normalized(), (W - E).normalized()
        b = (u + f).normalized()
        c = f - u
        if c.length < 1e-3:   # a straight arm: the crook faces forward
            c = Vector((0.0, -1.0, 0.0))
        c = (c - b * c.dot(b)).normalized()
        out.append(("elbow", sx, E, b, c))
        T, K, F = _joint(arm, f"thigh_{s}"), _joint(arm, f"calf_{s}"), _joint(arm, f"foot_{s}")
        b = ((K - T).normalized() + (F - K).normalized()).normalized()
        c = Vector((0.0, 1.0, 0.0))
        c = (c - b * c.dot(b)).normalized()
        out.append(("knee_back", sx, K, b, c))
    return out


def field(co, joint, b, c, F):
    """Fold height per vertex (co: n x 3) for one joint frame."""
    j, b, c = np.array(joint), np.array(b), np.array(c)
    d = co - j
    s = d @ b - F["offset_m"]
    r = d - np.outer(d @ b + 0.0, b)
    rn = np.linalg.norm(r, axis=1)
    cos_t = np.where(rn > 1e-6, (r @ c) / np.maximum(rn, 1e-6), 0.0)
    face = np.clip(cos_t, 0.0, 1.0) ** F["power"]
    arg = 2 * math.pi * (s - F["crescent_m"] * (1.0 - cos_t)) / F["wavelength_m"] + F["phase"]
    return F["amp_m"] * np.sin(arg) * np.exp(-(s / F["sigma_m"]) ** 2) * face


def _merged_normals(co, nor):
    keys = [tuple(k) for k in np.round(co, 5)]
    acc = {}
    for k, n in zip(keys, nor):
        acc[k] = acc.get(k, 0.0) + n
    out = np.array([acc[k] for k in keys])
    ln = np.linalg.norm(out, axis=1)
    return out / np.maximum(ln, 1e-9)[:, None]


def vertex_tags(ob):
    """Max face tag ("panel" face attribute) per vertex, or None."""
    me = ob.data
    a = me.attributes.get("panel")
    if a is None:
        return None
    fp = np.empty(len(me.polygons), np.int32)
    a.data.foreach_get("value", fp)
    tag = np.zeros(len(me.vertices), np.int32)
    for p in me.polygons:
        for vi in p.vertices:
            tag[vi] = max(tag[vi], fp[p.index])
    return tag


def apply(o, arm, body, garments):
    """garments: [(object, region, vertex mask fn(co, tag) -> bool[n])].
    Moves the vertices; returns stats per object."""
    import bpy
    F = o
    stats = {}
    if not F.get("enabled", True):
        return stats
    fr = frames(arm)
    dg = bpy.context.evaluated_depsgraph_get()
    tree = BVHTree.FromObject(body, dg)
    for ob, region, mask_fn in garments:
        if ob is None or region not in F:
            continue
        me = ob.data
        n = len(me.vertices)
        co = np.empty(n * 3, np.float64)
        me.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)
        nor = np.empty(n * 3, np.float64)
        me.vertices.foreach_get("normal", nor)
        nor = _merged_normals(co, nor.reshape(-1, 3))
        sel = mask_fn(co, vertex_tags(ob))
        h = np.zeros(n)
        for reg, sx, joint, b, c in fr:
            if reg != region:
                continue
            side = (co[:, 0] * sx) > 0
            h += np.where(sel & side, field(co, joint, b, c, F[region]), 0.0)
        moved = clipped = 0
        for i in np.nonzero(np.abs(h) > 1e-5)[0]:
            p, nn, hi = Vector(co[i]), Vector(nor[i]), float(h[i])
            if hi < 0:
                hit = tree.ray_cast(p, -nn, 0.05)
                if hit[0] is not None:
                    room = max(0.0, (hit[0] - p).length - F["clear_m"])
                    if -hi > room:
                        hi = -room
                        clipped += 1
            me.vertices[i].co = p + nn * hi
            moved += 1
        me.update()
        stats[ob.name] = {"region": region, "moved": moved, "clipped": clipped,
                          "max_mm": round(float(np.abs(h).max() * 1000), 2) if n else 0.0}
    return stats
