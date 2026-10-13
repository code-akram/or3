"""Strand groom for the scalp hair: the source of truth for the hero render
and for the game cards (hair_groom_cards bakes them from it).

Pipeline (deterministic, seeded; no fixed coordinates, everything is placed
on the body's MPFB `scalp` region and the HeadFrame landmarks, so a rebuild
on an edited head just works):

1. Growth surface: the hair_clumps growth region (scalp + temple and nape
   bands) as triangles. A hairline field: distance to the region's open
   boundary, minus a temple recession (two Gaussian bays at the temple
   corners), so d_eff < 0 is bare skin.
2. Guides: a farthest-point spread of roots over the surface, each marched
   by hair_clumps.march (comb back from the soft off-centre part, volume
   lift, tuck behind the ears, gravity, collision with skin and suit).
   Plus front-fall guides (right temple, one thin lock over the left brow).
3. Strands: roots sampled area-uniformly with a density ramp over the
   feather band at the hairline; each strand blends its nearest guides
   (same side of the part), translated to its root; a lock wave in the
   hanging part (phase per primary clump); pushed out of skin and suit.
   Two-level clump assignment (primary / secondary centres by farthest-point
   sampling), strays and flyaways are stored as curve attributes. Vellus
   hairs (3-6 mm) along the hairline.
4. Geometry Nodes (the bundled CC0 Essentials hair node groups, appended
   from Blender's datafiles): noise, primary clump, secondary clump, frizz,
   flyaway noise, trim (length variation). Everything after the base shape
   is a modifier, so it can be tuned in the .blend.
5. Principled Hair BSDF (Huang), melanin near-black brown, a few lighter
   strands, root-to-tip roughness.
6. The Curves object lives in the `hero_only` collection (never exported),
   parented to the `head` bone; plus a hero-only scalp tint shell.
"""

import math
import os
import random

import bpy
import numpy as np
from mathutils import Vector
from mathutils.kdtree import KDTree

from . import export, hair_clumps, hair_mesh

ESSENTIALS = os.path.join(bpy.utils.system_resource("DATAFILES"), "assets", "nodes",
                          "procedural_hair_node_assets.blend")

DEFAULTS = {
    "enabled": True,
    "cards": "groom",          # game cards: "groom" (baked from this groom) or "clumps"
    "seed": 21,
    "guides": 520,
    "strands": 40000,          # main strands (vellus and front falls extra)
    "points": 24,
    "radius_m": [0.000045, 0.00002],   # root, tip
    "gap_m": 0.0012,           # strand clearance over the skin
    "layer_jitter_m": 0.004,   # guide stand-off jitter (layers stack)
    "knn": 4,                  # guides blended per strand
    # Overrides of the hair_clumps march parameters for the groom guides.
    "march": {"cling": 0.0, "ear_margin_m": 0.008},
    # Comb: "back" sweeps every root back from the part (v2 look); "part"
    # lets the hair fall sideways off the part and down the sides (a hanging
    # centre-part style): `side` out from the part, `back`, `drop`; roots
    # facing forward comb `forward` and hold up (`front_hold`) until past
    # the temple, where gravity starts between `fall_az_deg` (|azimuth|).
    "comb": {"mode": "back", "side": 0.8, "back": 0.35, "drop": 0.35, "forward": 0.25,
             "front_hold": 0.8, "fall_az_deg": [25.0, 50.0], "fall_above_ear_m": 0.06,
             "hug": 0.0, "hug_above_ear_m": 0.0},   # pull back onto the skull while above the ear
    # Share of roots per side that tuck behind the ear (the rest drape over
    # it, kept off by the ear collider). left = +x, the character's left.
    "tuck": {"left": 1.0, "right": 1.0},
    "part_jitter_m": 0.002,    # the part line wanders this much (soft part)
    "part_push": 0.25,         # comb push away from the part (hair_clumps uses clumps.part_push)
    "part_width_m": 0.02,
    "part_lift_m": 0.004,      # strands next to the part rise a little before they fall
    # Hairline: temples recede (two bays), the density ramps over the feather.
    "hairline": {"recess_m": 0.009, "recess_az_deg": 44, "recess_sigma_deg": 13,
                 "recess_above_ear_m": 0.025,
                 "feather_m": 0.010, "feather_min": 0.08, "ramp_pow": 1.2,
                 "nape_feather_m": 0.006},
    # Volume lift (stand-off from the skull along the strand, Strand.lift):
    # front roots lift off the forehead, the crown lies flat, the occiput full.
    "lift": {"front_m": 0.014, "front_band_m": 0.04, "crown_m": 0.008, "side_m": 0.036,
             "back_m": 0.026, "rise_m": 0.05, "hold_m": 0.07, "fall_m": 0.14, "keep": 0.75,
             "jitter": 0.3},
    # Clumping ramps in along the strand: `scalp` x the factor while it lies
    # on the skull (combed hair lies smooth), full `ramp_m` past the hang point.
    "clump": {"scalp": 0.2, "ramp_m": 0.06, "primary": 36, "primary_factor": 0.85, "primary_shape": 0.3,
              "secondary": 360, "secondary_factor": 0.8, "secondary_shape": 0.0,
              "stray": 0.10, "stray_nape": 0.25, "tip_spread": 0.0},
    "wave": {"amp_m": [0.004, 0.008], "period_m": [0.12, 0.18], "jitter": 0.4},
    "noise": {"distance_m": 0.0015, "scale": 40.0, "shape": 0.3},
    "frizz": {"distance_m": 0.0005, "shape": 0.6},
    "flyaways": {"share": 0.04, "distance_m": 0.010, "scale": 20.0, "shape": 0.4, "part_weight": 0.6},
    "trim": {"random": 0.05},
    "vellus": {"count": 1400, "length_m": [0.003, 0.006], "band_m": [-0.002, 0.006],
               "radius_m": 0.000018, "lift": 0.35, "melanin": 0.9},
    # Front falls (hair_clumps.march with fall gravity). side -1 = the
    # character's right. Each takes the `strands` nearest strands.
    "front_fall": [
        {"side": -1, "count": 3, "az0_deg": 30, "az_step_deg": 6.0, "el_deg": 24,
         "comb_side": 0.2, "comb_fwd": 0.3, "comb_down": 0.9, "fall_after_m": 0.025,
         "tip_above_lips_m": 0.045, "tip_jitter_m": 0.015, "hug": 0.06, "clear_m": 0.005,
         "flare_after_m": 0.1, "flare": 0.1, "max_len_m": 0.24, "strands": 360,
         "factor": 0.75, "wave_m": 0.005},
        {"side": 1, "count": 1, "az0_deg": 16, "az_step_deg": 0.0, "el_deg": 32,
         "comb_side": 0.9, "comb_fwd": 0.5, "comb_down": 0.4, "fall_after_m": 0.04, "gravity": 0.55,
         "tip_above_lips_m": 0.06, "tip_jitter_m": 0.0, "hug": 0.08, "clear_m": 0.007,
         "flare_after_m": 0.07, "flare": 0.08, "max_len_m": 0.13, "strands": 260,
         "factor": 0.75, "wave_m": 0.003}],
    "shader": {"model": "HUANG", "melanin": 0.985, "redness": 0.12,
               "roughness": [0.22, 0.30], "random_color": 0.08, "random_roughness": 0.1,
               "ior": 1.55, "aspect_ratio": 0.85, "light_share": 0.10, "light_melanin": 0.93,
               "lock_melanin_jitter": 0.012, "tint": None,
               "coat": None, "radial_roughness": None},   # Chiang only (wet look: coat)
    "scalp_tint": {"offset_m": 0.0004, "color": "#4a3a31", "fade_m": [0.008, 0.03], "alpha": 0.85},
}

DOWN = Vector((0.0, 0.0, -1.0))
smoothstep = hair_clumps.smoothstep


def merged(cfg):
    """DEFAULTS deep-merged with the config's `hair.groom` section."""
    def merge(a, b):
        out = dict(a)
        for k, v in (b or {}).items():
            out[k] = merge(a[k], v) if isinstance(a.get(k), dict) and isinstance(v, dict) else v
        return out
    return merge(DEFAULTS, cfg)


# ---------------------------------------------------------------- surface

class Surface:
    """The growth region as triangles, with the hairline field."""

    def __init__(self, frame, keep, gcfg, part_x):
        body = frame.body
        mw = body.matrix_world
        nm = mw.to_3x3().inverted().transposed()
        V = np.array([tuple(mw @ v.co) for v in body.data.vertices])
        N = np.array([tuple((nm @ v.normal).normalized()) for v in body.data.vertices])
        tris, edges = [], {}
        for p in body.data.polygons:
            vs = list(p.vertices)
            if not all(i in keep for i in vs):
                continue
            for k in range(1, len(vs) - 1):
                tris.append((vs[0], vs[k], vs[k + 1]))
            for a, c in zip(vs, vs[1:] + vs[:1]):
                e = (min(a, c), max(a, c))
                edges[e] = edges.get(e, 0) + 1
        self.T = np.array(tris)
        self.V, self.N = V, N
        a, b_, c = V[self.T[:, 0]], V[self.T[:, 1]], V[self.T[:, 2]]
        self.area = 0.5 * np.linalg.norm(np.cross(b_ - a, c - a), axis=1)
        # Open boundary, densified every ~2 mm, in a KD tree.
        bpts = []
        for (i, j), n in edges.items():
            if n == 1:
                p, q = V[i], V[j]
                k = max(1, int(np.linalg.norm(q - p) / 0.002))
                bpts += [p + (q - p) * (s / k) for s in range(k)]
        self.kd = KDTree(len(bpts))
        for i, p in enumerate(bpts):
            self.kd.insert(Vector(p), i)
        self.kd.balance()
        self.frame, self.cfg, self.part_x = frame, gcfg, part_x
        self.c = frame.center

    def azimuth(self, p):
        """Degrees round the head from the front (+ = the character's left)."""
        return math.degrees(math.atan2(p[0] - self.c.x, -(p[1] - self.c.y)))

    def recess(self, p):
        h = self.cfg["hairline"]
        if p[1] > self.c.y:
            return 0.0
        az = abs(self.azimuth(p))
        gate = smoothstep(self.frame.ear_z, self.frame.ear_z + h["recess_above_ear_m"], p[2])
        return h["recess_m"] * math.exp(-((az - h["recess_az_deg"]) / h["recess_sigma_deg"]) ** 2) * gate

    def d_eff(self, p):
        """Distance inside the hairline (m): boundary distance minus the
        temple recession. < 0: bare skin."""
        _, _, d = self.kd.find(Vector(p))
        return d - self.recess(p)

    def feather(self, p):
        h = self.cfg["hairline"]
        return h["feather_m"] if p[1] < self.c.y else h["nape_feather_m"]

    def sample(self, rng, n):
        """n area-uniform points (positions, normals)."""
        cdf = np.cumsum(self.area)
        ti = np.searchsorted(cdf, rng.random(n) * cdf[-1])
        u, v = rng.random(n), rng.random(n)
        flip = u + v > 1
        u[flip], v[flip] = 1 - u[flip], 1 - v[flip]
        w = 1 - u - v
        t = self.T[ti]
        P = self.V[t[:, 0]] * w[:, None] + self.V[t[:, 1]] * u[:, None] + self.V[t[:, 2]] * v[:, None]
        Nn = self.N[t[:, 0]] * w[:, None] + self.N[t[:, 1]] * u[:, None] + self.N[t[:, 2]] * v[:, None]
        Nn /= np.linalg.norm(Nn, axis=1)[:, None]
        # Outward from the cranium centre.
        out = P - np.array(self.c)
        Nn[(Nn * out).sum(1) < 0] *= -1
        return P, Nn

    def part_side(self, p, nrm):
        """+1 / -1 on the two sides of the part for roots in the part zone
        (top front), 0 elsewhere. The part line wanders a little in y."""
        if not (nrm[2] > 0.45 and p[1] < self.c.y + 0.03):
            return 0
        j = self.cfg["part_jitter_m"]
        px = self.part_x + j * (math.sin(p[1] * 260.0) + 0.5 * math.sin(p[1] * 610.0 + 1.3))
        return 1 if p[0] >= px else -1


def fps(points, k, start=0):
    """Farthest-point sampling: indices of k well-spread points."""
    n = len(points)
    k = min(k, n)
    sel = [start]
    d = np.linalg.norm(points - points[start], axis=1)
    for _ in range(k - 1):
        i = int(np.argmax(d))
        sel.append(i)
        d = np.minimum(d, np.linalg.norm(points - points[i], axis=1))
    return np.array(sel)


def resample_np(pts, m):
    """Polyline (n, 3) -> m points evenly by arc length."""
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    acc = np.concatenate([[0.0], np.cumsum(seg)])
    s = np.linspace(0.0, acc[-1], m)
    return np.stack([np.interp(s, acc, pts[:, k]) for k in range(3)], axis=1)


# ---------------------------------------------------------------- guides

def comb_dir(surf, ccfg, p, nrm, rng, side=None):
    c = surf.c
    dx = p[0] - surf.part_x
    cm = surf.cfg.get("comb", {})
    gc = surf.cfg
    if cm.get("mode") == "part":
        sg = side if side else (1.0 if dx >= 0 else -1.0)
        frontw = smoothstep(-0.2, -0.7, nrm[1])
        # Next to the part the hair leaves it gently (part_ramp of the side
        # comb at the part, full `part_width_m` away), so the part is a line.
        near = smoothstep(0.0, gc["part_width_m"], abs(dx)) if nrm[2] > 0.5 else 1.0
        ramp = cm.get("part_ramp", 1.0) + (1 - cm.get("part_ramp", 1.0)) * near
        x = sg * (cm["side"] * ramp * (1 - cm.get("front_side_cut", 0.0) * frontw)
                  + rng.uniform(-0.1, 0.1))
        y = cm["back"] * (1 - frontw) - cm["forward"] * frontw
        z = -cm["drop"] * (1 - cm["front_hold"] * frontw)
        return Vector((x, y, z))
    on_top = nrm[2] > 0.5 and p[1] < c.y + 0.02
    gc = surf.cfg
    push = (math.copysign(gc["part_push"], dx if side is None or side == 0 else side)
            * math.exp(-abs(dx) / gc["part_width_m"])) if on_top else 0.0
    drop = ccfg["comb_drop"] + ccfg["side_drop"] * smoothstep(0.4, 0.8, abs(nrm[0]))
    return Vector((push + rng.uniform(-0.08, 0.08), 1.0, -drop))


def lift_profile(surf, gcfg, p, nrm, rng):
    """(amplitude, rise, hold, fall, keep): a 10 mm lift off the forehead,
    a flat crown, a full occiput."""
    L = gcfg["lift"]
    c = surf.c
    d = surf.d_eff(p)
    front = (1 - smoothstep(0.0, L["front_band_m"], d)) * smoothstep(c.y - 0.02, c.y - 0.06, p[1])
    top = smoothstep(0.5, 0.85, nrm[2])
    back = smoothstep(c.y, c.y + 0.05, p[1]) * (1 - top)
    # Side lift only where the scalp faces sideways; forward-facing roots
    # (the front hairline, above the temples) get the front lift. With
    # side = 1 - max(top, back) the front hairline stood 36 mm off the
    # forehead and read as a pale tuft against the top light.
    rest = max(0.0, 1 - top - back)
    side = rest * smoothstep(0.3, 0.7, abs(nrm[0]))
    fwd = rest - side
    amp = max(L["front_m"] * front, L["crown_m"] * top + L["side_m"] * side + L["back_m"] * back
              + L["front_m"] * fwd)
    if nrm[2] > 0.5 and p[1] < c.y + 0.02:
        amp += surf.cfg["part_lift_m"] * math.exp(-abs(p[0] - surf.part_x) / 0.012)
    amp *= 1 - L["jitter"] * rng.random()
    return (amp, L["rise_m"], L["hold_m"], L["fall_m"], L["keep"])


def march_guides(b, frame, ccfg, gcfg, surf, rng, roots, nrms, m):
    """Marched, resampled guides: (G, m, 3) positions, (G, m) hang_s,
    per-guide hang point (for the spring sector)."""
    c = frame.center
    length = ccfg["length"]
    tip_base = frame.neck_z + (frame.shoulder_z - frame.neck_z) * length["f"]
    ear_back_y = frame.ears_max.y + 0.004

    cm = gcfg["comb"]
    part_mode = cm.get("mode") == "part"

    def gravity(p, s, tuck=True):
        behind = smoothstep(c.y - 0.01, c.y + 0.06, p.y)
        low = smoothstep(frame.ears_min.z, frame.ears_min.z - 0.05, p.z)
        if tuck and frame.near_ear(p) is not None and p.y < ear_back_y:
            behind = 0.0
        if part_mode:
            # Hanging style: off the upper skull and past the temple, fall.
            az = abs(surf.azimuth(tuple(p)))
            side = (smoothstep(cm["fall_az_deg"][0], cm["fall_az_deg"][1], az)
                    * smoothstep(frame.ears_max.z + cm["fall_above_ear_m"], frame.ears_max.z, p.z))
            behind = max(behind, side)
        return max(behind, low) * ccfg["gravity"]

    tk = gcfg["tuck"]

    wv = ccfg["wave"]
    G, H, hang_pts = [], [], []
    for p, n in zip(roots, nrms):
        side = surf.part_side(p, n)
        comb = comb_dir(surf, ccfg, p, n, rng, side)
        tip = tip_base + rng.uniform(-1, 1) * length["jitter_m"]
        lay = rng.uniform(0, gcfg["layer_jitter_m"])
        share = tk["left"] if p[0] >= c.x else tk["right"]
        tuck = True if share >= 1.0 else rng.random() < share   # no draw: v2 grooms unchanged
        s = hair_clumps.Strand(Vector(p), Vector(n), comb, tip, ccfg["max_len_m"],
                               lambda q, l, tuck=tuck: gravity(q, l, tuck), gcfg["gap_m"] + lay, {})
        s.tuck = tuck
        if part_mode and cm.get("hug", 0.0) > 0:
            s.hug = cm["hug"]
            s.hug_above_z = frame.ears_max.z + cm["hug_above_ear_m"]
        s.lift = lift_profile(surf, gcfg, p, n, rng)
        s.wave = (wv["amp"] * rng.uniform(0.3, 0.6), rng.uniform(0, 6.3),
                  wv["period_m"] * rng.uniform(0.8, 1.25))
        G.append(_march(frame, ccfg, s, m))
    for g in G:
        h, hp = hang_of(frame, ccfg, g)
        H.append(h)
        hang_pts.append(hp)
    return np.array(G), np.array(H), hang_pts


def _march(frame, ccfg, s, m):
    pts = hair_clumps.march(frame, s, ccfg["step_m"], ccfg["turn"], ccfg["ear_margin_m"],
                            ccfg.get("cloth_gap_m", 0.0), ccfg.get("neck_tuck", 0.0),
                            frame.chin_z, ccfg.get("cling", 0.0), ccfg.get("hang_turn"))
    P = np.array([tuple(p) for p in pts])
    # Point 0 buried upstream, point 1 at the root, the rest even by length.
    return np.concatenate([P[:1], resample_np(P[1:], m - 1)])


def hang_of(frame, ccfg, g, front_fall=False):
    """hang_s per point (m past the point where the strand starts to hang)
    and the hang point. As hair_clumps: clear of the colliders, or below
    ear level behind the head; front falls hang from 2 cm past the root."""
    sp = ccfg["springs"] or {"hang_below_ear_m": 0.01, "front_hang_m": 0.02}
    c = frame.center
    arc = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(g, axis=0), axis=1))])
    hi = len(g) - 1
    for i, p in enumerate(g):
        if i < 2:
            continue
        if front_fall:
            hang = arc[i] >= sp["front_hang_m"]
        else:
            _, _, sd = frame.signed(Vector(p), ccfg.get("cloth_gap_m", 0.0))
            hang = sd > 0.02 or (p[2] < frame.ear_z + sp["hang_below_ear_m"] and p[1] > c.y)
        if hang:
            hi = i
            break
    return np.maximum(arc - arc[hi], 0.0), Vector(g[hi])


def front_fall_guides(frame, ccfg, gcfg, surf, rng, m):
    """Front-fall guides: rooted on the hairline by azimuth / elevation from
    the cranium centre, combed forward and down (hair_clumps.march)."""
    c = frame.center
    out = []
    for ff in gcfg["front_fall"]:
        side = ff["side"]
        for i in range(ff["count"]):
            az = math.radians(side * (ff["az0_deg"] + ff["az_step_deg"] * i))
            el = math.radians(ff["el_deg"] + rng.uniform(-3, 3))
            d = Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)))
            loc = None
            # Walk back from the hairline until the root is inside it.
            for back in range(12):
                dd = (d + Vector((0, 0.03 * back, 0.02 * back))).normalized()
                hit, nrm, _, _ = surf.frame.skin_bvh.ray_cast(c, dd, 0.3)
                if hit is not None and surf.d_eff(tuple(hit)) > 0.004:
                    loc = hit
                    break
            if loc is None:
                continue
            if nrm.dot(loc - c) < 0:
                nrm = -nrm
            comb = Vector((side * (ff["comb_side"] + rng.uniform(-0.1, 0.1)), -ff["comb_fwd"],
                           -ff["comb_down"]))
            tip = frame.lips_max.z + ff["tip_above_lips_m"] + rng.uniform(-1, 1) * ff["tip_jitter_m"]

            def fall_gravity(p, s, ff=ff):
                return smoothstep(0.0, ff["fall_after_m"], s) * ff.get("gravity", 0.95)

            s = hair_clumps.Strand(loc, nrm, comb, tip, ff["max_len_m"] * rng.uniform(0.9, 1.0),
                                   fall_gravity, gcfg["gap_m"] + ff["clear_m"] + 0.0015 * i, {},
                                   side)
            s.hug = ff["hug"]
            s.flare = (ff["flare_after_m"] * rng.uniform(0.8, 1.2), ff["flare"])
            s.lift = (0.0, 0.03, 0.03, 0.08, 0.5)
            g = _march(frame, ccfg, s, m)
            h, hp = hang_of(frame, ccfg, g, front_fall=True)
            out.append({"guide": g, "hang": h, "hang_pt": hp, "side": side, "cfg": ff})
    return out


# ---------------------------------------------------------------- strands

def sample_roots(surf, rng, n):
    """n roots with the hairline density ramp (feather band)."""
    h = surf.cfg["hairline"]
    P_all, N_all = [], []
    got = 0
    while got < n:
        P, Nn = surf.sample(rng, n * 2)
        keep = []
        r = rng.random(len(P))
        for i, p in enumerate(P):
            d = surf.d_eff(p)
            if d <= 0:
                continue
            f = surf.feather(p)
            prob = h["feather_min"] + (1 - h["feather_min"]) * smoothstep(0.0, f, d) ** h["ramp_pow"]
            if r[i] < prob:
                keep.append(i)
        P_all.append(P[keep])
        N_all.append(Nn[keep])
        got += len(keep)
    return np.concatenate(P_all)[:n], np.concatenate(N_all)[:n]


def interpolate(surf, G, groots, gside, roots, nrms, knn):
    """Each strand blends its nearest guides (not across the part),
    translated to its own root. Returns (S, w_idx, w) for re-use."""
    kd = KDTree(len(groots))
    for i, p in enumerate(groots):
        kd.insert(Vector(p), i)
    kd.balance()
    S = np.empty((len(roots), G.shape[1], 3))
    idx = np.zeros((len(roots), knn), dtype=int)
    wts = np.zeros((len(roots), knn))
    for j, (p, n) in enumerate(zip(roots, nrms)):
        side = surf.part_side(p, n)
        cand = kd.find_n(Vector(p), knn * 3)
        sel = [(i, d) for _, i, d in cand if side == 0 or gside[i] == 0 or gside[i] == side][:knn]
        if not sel:
            sel = [(i, d) for _, i, d in cand[:knn]]
        ii = np.array([i for i, _ in sel])
        dd = np.array([d for _, d in sel])
        w = 1.0 / (dd + 0.002) ** 2
        w /= w.sum()
        idx[j, :len(ii)] = ii
        wts[j, :len(ii)] = w
        rel = G[ii] - G[ii, 1:2]          # guide shapes relative to their roots
        S[j] = p + (rel * w[:, None, None]).sum(0)
    return S, idx, wts


def push_out(frame, S, gap, cloth_gap, start=2):
    """Push every point (from index start) at least gap off skin / suit."""
    moved = 0
    for j in range(len(S)):
        for k in range(start, S.shape[1]):
            q = Vector(S[j, k])
            loc, nrm, sd = frame.signed(q, cloth_gap)
            if loc is not None and sd < gap:
                S[j, k] = tuple(q + nrm * (gap - sd))
                moved += 1
    return moved


def side_vectors(frame, S):
    """Horizontal unit vectors perpendicular to the radial direction from
    the head axis, per point (the lateral direction of a hanging strand)."""
    c = np.array(frame.center)
    rad = S[..., :2] - c[:2]
    rad /= np.linalg.norm(rad, axis=-1, keepdims=True) + 1e-9
    side = np.zeros_like(S)
    side[..., 0] = -rad[..., 1]
    side[..., 1] = rad[..., 0]
    return side


# ---------------------------------------------------------------- geometry nodes

def essentials(names):
    """Append the CC0 Essentials hair node groups (Blender's bundled asset
    library, datafiles/assets/LICENSE: CC0 1.0)."""
    have = {n: bpy.data.node_groups.get(n) for n in names}
    need = [n for n, g in have.items() if g is None]
    if need:
        with bpy.data.libraries.load(ESSENTIALS, link=False) as (src, dst):
            dst.node_groups = [n for n in src.node_groups if n in need]
        for g in dst.node_groups:
            have[g.name] = g
    return have


def groom_nodes(gcfg):
    """The groom modifier: noise -> clump (primary) -> clump (secondary) ->
    frizz -> flyaway noise -> trim. Curve attributes drive the per-strand
    factors (clump_w: 0 for strays, vellus; fly: flyaways)."""
    eg = essentials(["Hair Curves Noise", "Clump Hair Curves", "Frizz Hair Curves",
                     "Trim Hair Curves"])
    ng = bpy.data.node_groups.new("hair_groom", "GeometryNodeTree")
    ng.is_modifier = True
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    N = ng.nodes
    L = ng.links
    gin = N.new("NodeGroupInput")
    gout = N.new("NodeGroupOutput")
    x = [0]

    def group(name, **inputs):
        node = N.new("GeometryNodeGroup")
        node.node_tree = eg[name]
        node.label = name
        x[0] += 250
        node.location = (x[0], 0)
        for k, v in inputs.items():
            node.inputs[k].default_value = v
        return node

    def attr(name, dtype="FLOAT"):
        a = N.new("GeometryNodeInputNamedAttribute")
        a.data_type = dtype
        a.inputs["Name"].default_value = name
        return a

    def scaled(name, k):
        a = attr(name)
        m = N.new("ShaderNodeMath")
        m.operation = "MULTIPLY"
        L.new(a.outputs["Attribute"], m.inputs[0])
        m.inputs[1].default_value = k
        return m.outputs[0]

    cc, nz, fz, fw = gcfg["clump"], gcfg["noise"], gcfg["frizz"], gcfg["flyaways"]
    seed = gcfg["seed"]
    noise = group("Hair Curves Noise", Distance=nz["distance_m"], Scale=nz["scale"],
                  Shape=nz["shape"], Seed=seed)
    noise.inputs["Cumulative Offset"].default_value = False
    c1 = group("Clump Hair Curves", Shape=cc["primary_shape"], Seed=seed + 1)
    c1.inputs["Tip Spread"].default_value = cc["tip_spread"]
    def clump_factor(k):
        m = N.new("ShaderNodeMath")
        m.operation = "MULTIPLY"
        L.new(scaled("clump_w", k), m.inputs[0])
        L.new(attr("clump_ramp").outputs["Attribute"], m.inputs[1])
        return m.outputs[0]

    L.new(clump_factor(cc["primary_factor"]), c1.inputs["Factor"])
    c2 = group("Clump Hair Curves", Shape=cc["secondary_shape"], Seed=seed + 2)
    L.new(clump_factor(cc["secondary_factor"]), c2.inputs["Factor"])
    L.new(attr("sub_guide_index", "INT").outputs["Attribute"], c2.inputs["Guide Index"])
    frizz = group("Frizz Hair Curves", Distance=fz["distance_m"], Shape=fz["shape"], Seed=seed + 3)
    fly = group("Hair Curves Noise", Distance=fw["distance_m"], Scale=fw["scale"],
                Shape=fw["shape"], Seed=seed + 4)
    L.new(attr("fly").outputs["Attribute"], fly.inputs["Factor"])
    trim = group("Trim Hair Curves", Seed=seed + 5)
    trim.inputs["Replace Length"].default_value = False
    trim.inputs["Length Factor"].default_value = 1.0
    trim.inputs["Random Offset"].default_value = gcfg["trim"]["random"]
    chain = [gin, noise, c1, c2, frizz, fly, trim, gout]
    for a, c in zip(chain, chain[1:]):
        L.new(a.outputs[0], c.inputs[0])
    gout.location = (x[0] + 250, 0)
    return ng


# ---------------------------------------------------------------- shading

def hair_material(gcfg):
    sc = gcfg["shader"]
    mat = bpy.data.materials.new("hair_groom")
    nt = mat.node_tree if mat.node_tree else None
    if nt is None:
        mat.use_nodes = True
        nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfHairPrincipled")
    bsdf.model = sc["model"]
    bsdf.parametrization = "MELANIN"
    info = nt.nodes.new("ShaderNodeHairInfo")
    # Melanin per strand (a few lighter strands; vellus lighter).
    mel = nt.nodes.new("ShaderNodeAttribute")
    mel.attribute_type = "GEOMETRY"
    mel.attribute_name = "melanin"
    nt.links.new(mel.outputs["Fac"], bsdf.inputs["Melanin"])
    bsdf.inputs["Melanin Redness"].default_value = sc["redness"]
    for key, name in (("coat", "Coat"), ("radial_roughness", "Radial Roughness")):
        if sc.get(key) is not None and name in bsdf.inputs:
            bsdf.inputs[name].default_value = sc[key]
    if sc.get("tint") and "Tint" in bsdf.inputs:
        h = sc["tint"].lstrip("#")
        bsdf.inputs["Tint"].default_value = tuple(
            (int(h[i:i + 2], 16) / 255) ** 2.2 for i in (0, 2, 4)) + (1.0,)
    bsdf.inputs["Random Color"].default_value = sc["random_color"]
    bsdf.inputs["Random Roughness"].default_value = sc["random_roughness"]
    bsdf.inputs["IOR"].default_value = sc["ior"]
    if "Aspect Ratio" in bsdf.inputs:
        bsdf.inputs["Aspect Ratio"].default_value = sc["aspect_ratio"]
    rough = nt.nodes.new("ShaderNodeMapRange")
    rough.inputs["To Min"].default_value = sc["roughness"][0]
    rough.inputs["To Max"].default_value = sc["roughness"][1]
    nt.links.new(info.outputs["Intercept"], rough.inputs["Value"])
    nt.links.new(rough.outputs["Result"], bsdf.inputs["Roughness"])
    nt.links.new(info.outputs["Random"], bsdf.inputs["Random"])
    nt.links.new(bsdf.outputs[0], out.inputs["Surface"])
    return mat


def scalp_tint(b, frame, keep, surf, gcfg):
    """Hero-only scalp shell under the strands: dark brown, fading out over
    the feather band, so the skin between strands at the part and the
    hairline reads as shadowed scalp, not as a bald patch."""
    st = gcfg["scalp_tint"]
    obj, bm = hair_mesh.shell_from_body(b, frame.body, keep, "hair_groom_scalp")
    hair_mesh.offset_shell(bm, lambda v: st["offset_m"], [0.5, 0.8])
    fade = bm.verts.layers.float_color.new("fade")
    for v in bm.verts:
        d = surf.d_eff(tuple(v.co))
        a = st["alpha"] * smoothstep(st["fade_m"][0], st["fade_m"][1], d)
        v[fade] = (a, a, a, 1.0)
    mat = bpy.data.materials.new("hair_groom_scalp")
    nt = mat.node_tree
    if nt is None:
        mat.use_nodes = True
        nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    rgb = [hair_mesh.srgb_to_linear(c) for c in hair_mesh.hex_rgb(st["color"])]
    bsdf.inputs["Base Color"].default_value = (*rgb, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.55
    ca = nt.nodes.new("ShaderNodeVertexColor")
    ca.layer_name = "fade"
    sep = nt.nodes.new("ShaderNodeSeparateColor")
    nt.links.new(ca.outputs["Color"], sep.inputs[0])
    nt.links.new(sep.outputs[0], bsdf.inputs["Alpha"])
    hair_mesh.finish(b, obj, bm, mat)
    b.export_objs.remove(obj)  # render-only
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    export.hero_collection().objects.link(obj)
    return obj


# ---------------------------------------------------------------- build

def build(b, frame, ccfg, gcfg_in):
    """Build the groom; returns a dict the card baker reads."""
    gcfg = merged(gcfg_in)
    rng = np.random.default_rng(gcfg["seed"])
    prng = random.Random(gcfg["seed"])
    m = gcfg["points"]
    c = frame.center
    part_x = c.x + ccfg["part_x_m"]
    keep = hair_clumps.growth_region(frame, ccfg)
    surf = Surface(frame, keep, gcfg, part_x)

    # Guides: a farthest-point spread over the surface inside the hairline.
    P, Nn = surf.sample(rng, 20000)
    inside = np.array([surf.d_eff(p) > 0.002 for p in P])
    P, Nn = P[inside], Nn[inside]
    gi = fps(P, gcfg["guides"])
    groots, gnrms = P[gi], Nn[gi]
    gside = np.array([surf.part_side(p, n) for p, n in zip(groots, gnrms)])
    ccfg = dict(ccfg, **gcfg["march"])
    G, GH, ghang = march_guides(b, frame, ccfg, gcfg, surf, prng, groots, gnrms, m)

    # Strands.
    roots, nrms = sample_roots(surf, rng, gcfg["strands"])
    S, kidx, kw = interpolate(surf, G, groots, gside, roots, nrms, gcfg["knn"])
    H = (GH[kidx] * kw[..., None]).sum(1)

    # Front falls: each guide takes the strands nearest its root.
    ffs = front_fall_guides(frame, ccfg, gcfg, surf, prng, m)
    kind = np.zeros(len(S), dtype=int)       # 0 main, 2 front fall
    ffid = np.full(len(S), -1)
    for fi, ff in enumerate(ffs):
        root = ff["guide"][1]
        free = np.where(kind == 0)[0]
        d = np.linalg.norm(roots[free] - root, axis=1)
        take = free[np.argsort(d)[:ff["cfg"]["strands"]]]
        kind[take] = 2
        ffid[take] = fi
        rel = ff["guide"] - ff["guide"][1]
        S[take] = roots[take][:, None, :] + rel[None]
        H[take] = ff["hang"][None]

    # Clumps: strays; primary centres; secondary centres within a primary.
    cc = gcfg["clump"]
    n = len(S)
    # Strays (unclumped) fill between the locks; more of them low at the
    # back, so the gaps between clumps over the spine don't show the collar.
    nape_w = (np.clip((roots[:, 1] - c.y) / 0.04, 0, 1)
              * np.clip((frame.ears_max.z + 0.02 - roots[:, 2]) / 0.05, 0, 1))
    stray = (rng.random(n) < cc["stray"] + cc.get("stray_nape", 0.0) * nape_w) & (kind == 0)
    prim = np.arange(n)
    sub = np.arange(n)
    main = np.where((kind == 0) & ~stray)[0]
    sides = np.array([surf.part_side(p, q) for p, q in zip(roots, nrms)])
    pc = main[fps(roots[main], cc["primary"])]
    for j in main:
        d = np.linalg.norm(roots[pc] - roots[j], axis=1)
        ok = (sides[pc] * sides[j]) >= 0
        d[~ok] += 1.0
        prim[j] = pc[int(np.argmin(d))]
    for p0 in pc:
        members = main[prim[main] == p0]
        k = max(1, round(cc["secondary"] * len(members) / max(len(main), 1)))
        sc = members[fps(roots[members], k, start=int(np.where(members == p0)[0][0]))]
        for j in members:
            sub[j] = sc[int(np.argmin(np.linalg.norm(roots[sc] - roots[j], axis=1)))]
    for fi in range(len(ffs)):
        members = np.where(ffid == fi)[0]
        if len(members) == 0:
            continue
        centre = members[0]  # nearest to the guide root
        prim[members] = centre
        sc = members[fps(roots[members], 3)]
        for j in members:
            sub[j] = sc[int(np.argmin(np.linalg.norm(roots[sc] - roots[j], axis=1)))]
    clump_w = np.where(stray, 0.0, 1.0)
    for fi, ff in enumerate(ffs):
        clump_w[ffid == fi] = ff["cfg"]["factor"] / cc["primary_factor"]

    # Lock wave in the hanging part, phase per primary clump.
    wv = gcfg["wave"]
    uniq = {int(p): (rng.uniform(*wv["amp_m"]), rng.uniform(*wv["period_m"]), rng.uniform(0, 6.3))
            for p in np.unique(prim)}
    amp = np.array([uniq[int(p)][0] for p in prim])
    per = np.array([uniq[int(p)][1] for p in prim])
    ph = np.array([uniq[int(p)][2] for p in prim]) + rng.normal(0, wv["jitter"], n)
    ramp = np.clip(H / 0.04, 0, 1) ** 2
    lat = (amp[:, None] * np.sin(2 * np.pi * H / per[:, None] + ph[:, None]) * ramp)
    for fi, ff in enumerate(ffs):
        sel = ffid == fi
        lat[sel] *= ff["cfg"].get("wave_m", 0.0) / max(amp[sel].mean(), 1e-6) if sel.any() else 0.0
    S += side_vectors(frame, S) * lat[..., None]
    pushed = push_out(frame, S, gcfg["gap_m"], ccfg.get("cloth_gap_m", 0.0))

    # Flyaways: mostly at the silhouette (sides, back) and the part.
    fw = gcfg["flyaways"]
    sil = np.abs(nrms[:, 0]) * 0.7 + np.clip(nrms[:, 1], 0, 1) * 0.5
    part_near = np.exp(-np.abs(roots[:, 0] - part_x) / 0.01) * (nrms[:, 2] > 0.5)
    wfly = (0.2 + sil + fw.get("part_weight", 1.5) * part_near) * (kind == 0)
    nfly = int(fw["share"] * n)
    fly_idx = rng.choice(n, nfly, replace=False, p=wfly / wfly.sum())
    fly = np.zeros(n)
    fly[fly_idx] = rng.uniform(0.5, 1.0, nfly)
    clump_w[fly_idx] *= 0.5

    sh = gcfg["shader"]
    melanin = np.full(n, sh["melanin"])
    light = rng.random(n) < sh["light_share"]
    melanin[light] = sh["light_melanin"]
    # Value per lock (secondary clump): some locks catch more light.
    lj = {int(q): rng.uniform(-1, 1) * sh.get("lock_melanin_jitter", 0.0) for q in np.unique(sub)}
    melanin = np.clip(melanin - np.abs(np.array([lj[int(q)] for q in sub])), 0.0, 1.0)

    # Vellus: short fine hairs along the whole hairline.
    vc = gcfg["vellus"]
    VP, VN = surf.sample(rng, vc["count"] * 30)
    lo, hi = vc["band_m"]
    vsel = [i for i, p in enumerate(VP) if lo < surf.d_eff(p) < hi][:vc["count"]]
    VS = []
    for i in vsel:
        p, q = Vector(VP[i]), Vector(VN[i])
        comb = hair_clumps.tangent(comb_dir(surf, ccfg, VP[i], VN[i], prng), q)
        d = (comb + q * vc["lift"]).normalized()
        ln = rng.uniform(*vc["length_m"])
        bend = (comb - q * 0.3).normalized()
        pts = [p - q * 0.0005, p + d * ln * 0.35, p + d * ln * 0.65 + bend * ln * 0.05,
               p + d * ln * 0.9 + bend * ln * 0.15]
        VS.append([tuple(x) for x in pts])
    VS = np.array(VS) if VS else np.zeros((0, 4, 3))
    nv = len(VS)

    # The Curves object.
    cv = bpy.data.hair_curves.new("hair_groom")
    cv.add_curves([m] * n + [4] * nv)
    pos = np.concatenate([S.reshape(-1, 3), VS.reshape(-1, 3)]).astype(np.float32)
    cv.position_data.foreach_set("vector", pos.ravel())
    r0, r1 = gcfg["radius_m"]
    t = np.linspace(0, 1, m)
    rad = np.tile(r0 + (r1 - r0) * t ** 1.5, n)
    vt = np.linspace(0, 1, 4)
    vrad = np.tile(vc["radius_m"] * (1 - 0.5 * vt), nv)
    radius = np.concatenate([rad, vrad]).astype(np.float32)
    ra = cv.attributes.get("radius") or cv.attributes.new("radius", "FLOAT", "POINT")
    ra.data.foreach_set("value", radius)
    # Clump ramp per point: low while on the skull, full past the hang point.
    ramp = cc["scalp"] + (1 - cc["scalp"]) * np.clip(H / cc["ramp_m"], 0, 1) ** 1.5
    ramp[kind == 2] = np.clip(H[kind == 2] / 0.03, 0, 1)
    cr = cv.attributes.new("clump_ramp", "FLOAT", "POINT")
    cr.data.foreach_set("value", np.concatenate([ramp.ravel(), np.zeros(nv * 4)]).astype(np.float32))

    def curve_attr(name, dtype, values):
        a = cv.attributes.new(name, dtype, "CURVE")
        a.data.foreach_set("value", values)

    nall = n + nv
    own = np.arange(nall)
    curve_attr("guide_curve_index", "INT", np.concatenate([prim, own[n:]]).astype(np.int32))
    curve_attr("sub_guide_index", "INT", np.concatenate([sub, own[n:]]).astype(np.int32))
    curve_attr("clump_w", "FLOAT", np.concatenate([clump_w, np.zeros(nv)]).astype(np.float32))
    curve_attr("fly", "FLOAT", np.concatenate([fly, np.zeros(nv)]).astype(np.float32))
    curve_attr("melanin", "FLOAT", np.concatenate([melanin, np.full(nv, vc["melanin"])]).astype(np.float32))
    curve_attr("kind", "INT", np.concatenate([kind, np.ones(nv)]).astype(np.int32))
    cv.materials.append(hair_material(gcfg))
    obj = bpy.data.objects.new("hair_groom", cv)
    export.hero_collection().objects.link(obj)
    mod = obj.modifiers.new("groom", "NODES")
    mod.node_group = groom_nodes(gcfg)

    tint = scalp_tint(b, frame, keep, surf, gcfg)

    # Evaluated strands (for the card bake), before parenting (world space).
    bpy.context.view_layer.update()
    ev = evaluated(obj)

    # Bind to the head bone (rigid with the head, like the cap).
    arm = b.armature()
    mw = obj.matrix_world.copy()
    obj.parent = arm
    obj.parent_type = "BONE"
    obj.parent_bone = "head"
    bpy.context.view_layer.update()
    obj.matrix_world = mw

    b.notes["hair_groom"] = {
        "guides": int(len(G)), "strands": int(n), "vellus": int(nv),
        "front_fall_guides": len(ffs), "front_fall_strands": int((kind == 2).sum()),
        "primary_clumps": int(len(np.unique(prim[main]))),
        "secondary_clumps": int(len(np.unique(sub[main]))),
        "strays": int(stray.sum()), "flyaways": int(nfly), "points_pushed": int(pushed),
        "points": int(len(pos)), "evaluated_points": int(len(ev["pos"])),
        "essentials": ESSENTIALS + " (CC0 1.0, datafiles/assets/LICENSE)",
        "tint": tint.name,
    }
    return {"obj": obj, "surf": surf, "keep": keep, "kind": np.concatenate([kind, np.ones(nv, int)]),
            "prim": prim, "sub": sub, "stray": stray, "fly": fly, "hang": H, "roots": roots,
            "nrms": nrms, "n": n, "m": m, "eval": ev, "guides": G, "guide_hang": GH,
            "ff": ffs, "cfg": gcfg}


def evaluated(obj):
    """Evaluated groom: positions (P, 3) and curve offsets (C + 1)."""
    dg = bpy.context.evaluated_depsgraph_get()
    cd = obj.evaluated_get(dg).data
    pos = np.empty(len(cd.points) * 3, dtype=np.float32)
    cd.attributes["position"].data.foreach_get("vector", pos)
    offs = np.empty(len(cd.curves) + 1, dtype=np.int32)
    cd.curve_offset_data.foreach_get("value", offs)
    return {"pos": pos.reshape(-1, 3), "offs": offs}
