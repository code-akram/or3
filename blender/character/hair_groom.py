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

from . import export, hair_clumps, hair_frame, hair_mesh

ESSENTIALS = os.path.join(bpy.utils.system_resource("DATAFILES"), "assets", "nodes",
                          "procedural_hair_node_assets.blend")

DEFAULTS = {
    "enabled": True,
    "cards": "groom",          # game cards: "groom" (baked from this groom) or "clumps"
    "seed": 21,
    "guides": 520,
    # hair v4 (fable_review §5.5 steps 1-3). The v3 values: bench/m1/variants/hair_v3_groom.json.
    "strands": 70000,          # main strands (vellus, front falls and stray hairs extra)
    "points": 48,              # control points per strand (the cards resample from these)
    # Point spacing along the strand: s = L (g t + (1 - g) t^2); 1 = even. < 1 puts
    # more points near the root (the hairline's forward edge hairs need them).
    "point_grade": 0.55,
    # Strand radius root, tip (m), as a power ramp (v3: 0.045 -> 0.02 mm, t^1.5).
    # Cut hair is blunt: `tip_taper_from` > 0 keeps the root radius and drops
    # it to `tip_taper` x only past that fraction of the strand (flyaways and
    # vellus taper on their own).
    "radius_m": [0.00004, 0.00004],
    "tip_taper": 0.8, "tip_taper_from": 0.97,
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
    # "field": "back" turned by a direction field (`field`, hair_frame.FlowField):
    # a crown whorl, the occiput and nape combed down, and coherent angle
    # noise so neighbouring guides are not all combed the same way.
    "comb": {"mode": "field", "side": 0.8, "back": 0.35, "drop": 0.35, "forward": 0.25,
             "front_hold": 0.8, "fall_az_deg": [25.0, 50.0], "fall_above_ear_m": 0.06,
             "hug": 0.0, "hug_above_ear_m": 0.0,   # pull back onto the skull while above the ear
             "free_fall_m": None},   # gravity ramps to full over 4 cm from this length, everywhere
    # Direction field (comb.mode "field"). Whorl: on the crown at `el_deg` over
    # the cranium centre, `az_deg` round from the back (+ = the character's
    # left); the comb turns round the scalp normal by up to `turn_deg` there
    # (+ = counter-clockwise seen from outside), fading over `radius_m`. `down`:
    # behind and below the whorl the comb turns down by this much. `jitter_deg`
    # of coherent angle noise round the scalp normal at `jitter_scale_m`.
    "field": {"whorl": {"el_deg": 58.0, "az_deg": 14.0, "radius_m": 0.025, "turn_deg": 50.0},
              "down": 0.5, "jitter_deg": 12.0, "jitter_scale_m": 0.035, "seed": 5},
    # Share of roots per side that tuck behind the ear (the rest drape over
    # it, kept off by the ear collider). left = +x, the character's left.
    "tuck": {"left": 1.0, "right": 1.0},
    "part_jitter_m": 0.002,    # the part line wanders this much (soft part)
    "part_push": 0.25,         # comb push away from the part (hair_clumps uses clumps.part_push)
    "part_width_m": 0.02,
    "part_lift_m": 0.004,      # strands next to the part rise a little before they fall
    "part_lift_rise_m": None,  # rise length of that lift (None: the lift profile's rise_m)
    "part_density": 0.0,       # extra root density at the part line (x within part_width_m)
    "part_back_m": 0.03,       # ... from the front back to this far behind the head centre
    # Hairline: temples recede (two bays; `recess_side` per side: depth x and
    # azimuth shift in degrees, an asymmetric M), the density ramps over the
    # feather. `noise`: octaves [amplitude, scale] (m) of 3D noise added to the
    # distance field, so the line is irregular instead of a smooth offset of
    # the region boundary. `density_noise`: the feather density is modulated
    # (a non-monotone ramp; 0 = off). `edge` (null = off): strands rooted
    # within band_m of the line lean `kick_m` toward the face over the first
    # `over_m` (edge hairs point forward, then sweep back), are `radius` x
    # finer and `melanin` lighter; clump.edge_m keeps them unclumped.
    "hairline": {"recess_m": 0.011, "recess_az_deg": 44, "recess_sigma_deg": 13,
                 "recess_above_ear_m": 0.025,
                 "recess_side": {"left": [1.0, 0.0], "right": [1.3, 4.0]},
                 "feather_m": 0.011, "feather_min": 0.05, "ramp_pow": 1.2,
                 "nape_feather_m": 0.006,
                 "noise": [[0.002, 0.008], [0.0015, 0.005], [0.001, 0.003]], "noise_seed": 3,
                 "density_noise": {"amp": 0.6, "scale_m": 0.004},
                 "edge": {"band_m": 0.006, "kick_m": 0.0022, "over_m": 0.005, "radius": 0.75,
                          "melanin": -0.06}},
    # Volume lift (stand-off from the skull along the strand, Strand.lift):
    # front roots lift off the forehead, the crown lies flat, the occiput full.
    # v4: the sides at half of v3's 36 mm (the shell off the skull read as a helmet).
    "lift": {"front_m": 0.014, "front_band_m": 0.04, "crown_m": 0.008, "side_m": 0.018,
             "back_m": 0.022, "rise_m": 0.05, "hold_m": 0.07, "fall_m": 0.14, "keep": 0.75,
             "jitter": 0.4},
    # Clumping ramps in along the strand: `scalp` x the factor while it lies
    # on the skull (combed hair lies smooth), full `ramp_m` past the hang point.
    # `levels`: nested clumps, coarse to fine; each level's centres are spread
    # inside the previous level's clumps: `count` clumps (or `size` strands per
    # clump), and the Essentials Clump node's factor, shape, tip spread, clump
    # offset and distance falloff (m). Low factors so locks never fully converge
    # (fable_review §5.4). Levels 1 and 2 are the card baker's primary and
    # secondary clumps. The v3 keys (primary, primary_factor, primary_shape,
    # secondary, secondary_factor, secondary_shape, tip_spread) still override
    # levels 1 and 2; v3 is two levels at 0.85 / 0.8 with Preserve Length off.
    # No clumping within `edge_m` of the hairline.
    "clump": {"scalp": 0.2, "ramp_m": 0.06, "edge_m": 0.008, "preserve_length": True,
              "noise_after_clumps": True,
              "levels": [
                  {"count": 50, "factor": 0.4, "shape": 0.3, "tip_spread_m": 0.004,
                   "offset_m": 0.0, "falloff_m": 0.0},
                  {"count": 400, "factor": 0.5, "shape": 0.0, "tip_spread_m": 0.002,
                   "offset_m": 0.0, "falloff_m": 0.0},
                  {"count": 4000, "factor": 0.4, "shape": 0.0, "tip_spread_m": 0.0004,
                   "offset_m": 0.0, "falloff_m": 0.0},
                  {"size": 4, "factor": 0.25, "shape": 0.0, "tip_spread_m": 0.0001,
                   "offset_m": 0.0, "falloff_m": 0.0}],
              "stray": 0.10, "stray_nape": 0.25},
    # Coherent lock wave in the hanging part (per level-1 clump): 1-2 waves per strand.
    "wave": {"amp_m": [0.004, 0.010], "period_m": [0.14, 0.24], "jitter": 0.4},
    # GN order (v4): clumps, then noise, then frizz (v3: noise before the clumps,
    # so the clumping erased part of it).
    "noise": {"distance_m": 0.0015, "scale": 40.0, "shape": 0.3},
    "frizz": {"distance_m": 0.0005, "shape": 0.6},
    # Flyaways. mode "strays": `share` x strands extra stray hairs, each a copy
    # of a main strand that leaves the mass from `start` (a fraction of its
    # length, uniform in the range) by `lift_m` at its end (outward and
    # sideways), `length` x the source's length, not clumped, `radius` x the
    # strand radius tapering to `tip_radius` x; GN noise `distance_m` on them.
    # mode "noise" (v3): `share` of the main strands get `distance_m` noise.
    "flyaways": {"mode": "strays", "share": 0.02, "distance_m": 0.003, "scale": 20.0, "shape": 0.4,
                 "part_weight": 0.6, "start": [0.1, 0.75], "lift_m": [0.004, 0.03],
                 "length": [0.55, 1.0], "tip_radius": 0.3, "radius": 0.8},
    # Length variation: each strand loses up to `random` x its length at the tip.
    # `in_gn`: the Essentials Trim node does it (v3); it resamples every strand
    # evenly, which undoes point_grade, so v4 cuts in Python (hanging part only).
    "trim": {"random": 0.06, "in_gn": False},
    # Ragged ends (v3): hanging strands lose up to `clump` of their length per
    # secondary clump (locks end at different heights) plus up to `strand`
    # per strand (tapered lock tips), cut from the tip. 0 = off.
    "ends": {"clump": 0.0, "strand": 0.0, "min_hang_m": 0.04},
    # The cut (v4; null = off): the guides' perimeter line, then per strand a
    # layered taper. Each strand is cut back from its tip by `lock_m` per
    # level-2 clump (locks end at different heights), plus `taper_m` x u^pow
    # per strand (each lock's end tapers over 2-3 cm), plus `layer_m` x how far
    # up the skull it is rooted (the outer, top-rooted layer ends higher).
    # Never into the first `min_hang_m` of the hanging part. `taper_radial`
    # (0 = a random taper per strand: the lock end fades out) blends the taper
    # toward the root's distance from its level-2 lock centre: pointed lock ends.
    "cut": {"lock_m": [0.0, 0.07], "taper_m": 0.03, "taper_pow": 1.0, "taper_radial": 0.7,
            "layer_m": 0.05, "min_hang_m": 0.04},
    "vellus": {"count": 4000, "length_m": [0.003, 0.007], "band_m": [-0.002, 0.008],
               "radius_m": 0.000025, "lift": 0.35, "melanin": 0.7},
    # Front falls (hair_clumps.march with fall gravity). side -1 = the
    # character's right. Each takes the `strands` nearest strands, which blend
    # the fall's own `guides` sub-guides (rooted within `spread_deg`, each
    # combed `comb_jitter` and cut `len_jitter` differently) instead of all
    # copying one guide (v3: guides 1, a rigid slab). `clump_w` scales the
    # clump factors (v3: `factor` / the level-1 factor).
    "front_fall": [
        {"side": -1, "count": 3, "az0_deg": 30, "az_step_deg": 6.0, "el_deg": 24,
         "comb_side": 0.2, "comb_fwd": 0.3, "comb_down": 0.9, "fall_after_m": 0.025,
         "tip_above_lips_m": 0.045, "tip_jitter_m": 0.015, "hug": 0.06, "clear_m": 0.005,
         "flare_after_m": 0.1, "flare": 0.1, "max_len_m": 0.24, "strands": 360,
         "clump_w": 1.5, "wave_m": 0.005, "guides": 6, "spread_deg": 5.0, "comb_jitter": 0.25,
         "len_jitter": 0.12},
        {"side": 1, "count": 1, "az0_deg": 16, "az_step_deg": 0.0, "el_deg": 32,
         "comb_side": 0.9, "comb_fwd": 0.35, "comb_down": 0.5, "fall_after_m": 0.04, "gravity": 0.75,
         "tip_above_lips_m": 0.06, "tip_jitter_m": 0.0, "hug": 0.4, "clear_m": 0.007,
         "flare_after_m": 0.11, "flare": 0.08, "max_len_m": 0.13, "strands": 260,
         "clump_w": 1.5, "wave_m": 0.003, "guides": 5, "spread_deg": 5.0, "comb_jitter": 0.25,
         "len_jitter": 0.12}],
    # Principled Hair BSDF, melanin parametrisation. Melanin 0.82 (red light
    # keeps ~25 % through one hair, so TT / TRT survive: two highlights; v3's
    # 0.985 left only the white R lobe), Random Color 0.2; per point melanin
    # + `root_dark` at the root and - `tip_light` at the tip. Grey: `grey_share`
    # of the strands (weighted `grey_temple` x at the temples, a Gaussian at
    # +-`grey_temple_az_deg` above the ears) at melanin uniform in
    # `grey_melanin` (the top of the range is half-pigmented), redness
    # `grey_redness`. `model` CHIANG or HUANG (the hair test renders both);
    # `roughness` is Chiang's, `huang_roughness` Huang's (roughly its square).
    # `offset_deg`: cuticle tilt. v3: Huang, 0.985, 10 % light strands, no grey.
    # Chiang roughness 0.32 -> 0.40: at 0.24 -> 0.30 the hair test's shadow side
    # stayed as dark as v3's (p10 1.1x); at 0.32 -> 0.40 it is 2.2x (t8-hair.md).
    "shader": {"model": "CHIANG", "melanin": 0.82, "redness": 0.12,
               "roughness": [0.32, 0.40], "huang_roughness": [0.11, 0.16],
               "random_color": 0.2, "random_roughness": 0.1,
               "ior": 1.55, "aspect_ratio": 0.85, "offset_deg": 3.0,
               "light_share": 0.0, "light_melanin": 0.93,
               "lock_melanin_jitter": 0.012, "tint": None,
               "coat": 0.0, "radial_roughness": 0.3,     # Chiang only (coat: the wet look)
               "root_dark": 0.06, "tip_light": 0.04,
               "grey_share": 0.12, "grey_melanin": [0.0, 0.5], "grey_redness": 0.0,
               "grey_temple": 2.2, "grey_temple_az_deg": 70.0, "grey_temple_sigma_deg": 22.0,
               "fly_roughness": None, "fly_melanin": None},   # flyaway strands (curve attr `fly`) blend to this: dry strays on a wet groom
    # Hero scalp shell under the strands: dark, fading in from fade_m[0] inside
    # the hairline (v3: from 8 mm, so the first 8 mm read as bare skin).
    "scalp_tint": {"offset_m": 0.0004, "color": "#4a3a31", "fade_m": [0.0, 0.014], "alpha": 0.8},
    # Cycles settings saved with the kept .blend: hair as 3D curves (THICK, not
    # the default ribbons) and the glossy bounces dark hair needs (fable_review
    # §5.4). The hero rig (blender/hero/rig.py cycles()) still sets its own bounces.
    "render": {"curve_shape": "THICK", "curve_subdivisions": 2, "glossy_bounces": 16},
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
        az = self.azimuth(p)
        depth, shift = (h.get("recess_side") or {}).get("left" if az >= 0 else "right", (1.0, 0.0))
        gate = smoothstep(self.frame.ear_z, self.frame.ear_z + h["recess_above_ear_m"], p[2])
        return (h["recess_m"] * depth * gate
                * math.exp(-((abs(az) - h["recess_az_deg"] - shift) / h["recess_sigma_deg"]) ** 2))

    def d_eff(self, p):
        """Distance inside the hairline (m): boundary distance minus the
        temple recession, plus the hairline noise. < 0: bare skin."""
        _, _, d = self.kd.find(Vector(p))
        h = self.cfg["hairline"]
        if h.get("noise"):
            d += hair_frame.fbm(p, h["noise"], h.get("noise_seed", 0))
        return d - self.recess(p)

    def toward_line(self, p, nrm):
        """Unit tangent at p pointing to the nearest hairline boundary point
        (the way an edge hair points), or None."""
        co, _, _ = self.kd.find(Vector(p))
        n = Vector(nrm)
        v = co - Vector(p)
        v -= n * v.dot(n)
        return v.normalized() if v.length > 1e-6 else None

    def density(self, p):
        """Root density multiplier (non-monotone feather; 1 = off)."""
        dn = self.cfg["hairline"].get("density_noise")
        if not dn or not dn.get("amp"):
            return 1.0
        return max(0.0, 1.0 + dn["amp"] * 1.6 * hair_frame.fbm(p, [[1.0, dn["scale_m"]]], 11))

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


def grade_param(m, grade=1.0):
    """m curve parameters in [0, 1] for the point spacing s = g t + (1 - g) t^2."""
    t = np.linspace(0.0, 1.0, m)
    return grade * t + (1.0 - grade) * t * t


def resample_np(pts, m, grade=1.0):
    """Polyline (n, 3) -> m points by arc length (even, or graded: see grade_param)."""
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    acc = np.concatenate([[0.0], np.cumsum(seg)])
    s = grade_param(m, grade) * acc[-1]
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
    v = Vector((push + rng.uniform(-0.08, 0.08), 1.0, -drop))
    if cm.get("mode") == "field" and getattr(surf, "flow", None) is not None:
        v = surf.flow.turn(v, p, nrm)
    return v


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
    rise = L["rise_m"]
    if nrm[2] > 0.5 and p[1] < c.y + 0.02:
        near = math.exp(-abs(p[0] - surf.part_x) / 0.012)
        amp += surf.cfg["part_lift_m"] * near
        if surf.cfg.get("part_lift_rise_m") and near > 0.3:
            rise = surf.cfg["part_lift_rise_m"] + (rise - surf.cfg["part_lift_rise_m"]) * (1 - near)
    amp *= 1 - L["jitter"] * rng.random()
    return (amp, rise, L["hold_m"], L["fall_m"], L["keep"])


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
            if cm.get("free_fall_m") is not None:
                behind = max(behind, smoothstep(cm["free_fall_m"], cm["free_fall_m"] + 0.04, s))
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
        G.append(_march(frame, ccfg, s, m, gcfg.get("point_grade", 1.0)))
    for g in G:
        h, hp = hang_of(frame, ccfg, g)
        H.append(h)
        hang_pts.append(hp)
    return np.array(G), np.array(H), hang_pts


def _march(frame, ccfg, s, m, grade=1.0):
    pts = hair_clumps.march(frame, s, ccfg["step_m"], ccfg["turn"], ccfg["ear_margin_m"],
                            ccfg.get("cloth_gap_m", 0.0), ccfg.get("neck_tuck", 0.0),
                            frame.chin_z, ccfg.get("cling", 0.0), ccfg.get("hang_turn"))
    P = np.array([tuple(p) for p in pts])
    # Point 0 buried upstream, point 1 at the root, the rest even by length.
    return np.concatenate([P[:1], resample_np(P[1:], m - 1, grade)])


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
    the cranium centre, combed forward and down (hair_clumps.march). Each
    fall has `guides` sub-guides rooted within `spread_deg` of it, combed and
    cut a little differently; its strands blend them (build)."""
    c = frame.center
    grade = gcfg.get("point_grade", 1.0)
    out = []

    def root_at(az, el):
        d = Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)))
        # Walk back from the hairline until the root is inside it.
        for back in range(12):
            dd = (d + Vector((0, 0.03 * back, 0.02 * back))).normalized()
            hit, nrm, _, _ = surf.frame.skin_bvh.ray_cast(c, dd, 0.3)
            if hit is not None and surf.d_eff(tuple(hit)) > 0.004:
                if nrm.dot(hit - c) < 0:
                    nrm = -nrm
                return hit, nrm
        return None, None

    for ff in gcfg["front_fall"]:
        side = ff["side"]
        for i in range(ff["count"]):
            az0 = math.radians(side * (ff["az0_deg"] + ff["az_step_deg"] * i))
            el0 = math.radians(ff["el_deg"] + rng.uniform(-3, 3))
            loc, nrm = root_at(az0, el0)
            if loc is None:
                continue
            comb0 = Vector((side * (ff["comb_side"] + rng.uniform(-0.1, 0.1)), -ff["comb_fwd"],
                            -ff["comb_down"]))
            tip0 = frame.lips_max.z + ff["tip_above_lips_m"] + rng.uniform(-1, 1) * ff["tip_jitter_m"]
            len0 = ff["max_len_m"] * rng.uniform(0.9, 1.0)
            flare0 = ff["flare_after_m"] * rng.uniform(0.8, 1.2)

            def fall_gravity(p, s, ff=ff):
                return smoothstep(0.0, ff["fall_after_m"], s) * ff.get("gravity", 0.95)

            subs = []
            for k in range(max(1, ff.get("guides", 1))):
                if k == 0:
                    r, rn, comb, tip, ln, fl = loc, nrm, comb0, tip0, len0, flare0
                else:
                    sp = math.radians(ff.get("spread_deg", 2.5))
                    r, rn = root_at(az0 + rng.uniform(-sp, sp), el0 + rng.uniform(-sp, sp))
                    if r is None:
                        continue
                    cj, lj = ff.get("comb_jitter", 0.15), ff.get("len_jitter", 0.12)
                    comb = comb0 + Vector((rng.uniform(-cj, cj), rng.uniform(-cj, cj) * 0.5,
                                           rng.uniform(-cj, cj) * 0.5))
                    tip = tip0 + rng.uniform(-1, 1) * ff["tip_jitter_m"] * 0.5
                    ln = len0 * (1.0 - lj * rng.random())
                    fl = flare0 * rng.uniform(0.85, 1.15)
                s = hair_clumps.Strand(r, rn, comb, tip, ln, fall_gravity,
                                       gcfg["gap_m"] + ff["clear_m"] + 0.0015 * i, {}, side)
                s.hug = ff["hug"]
                s.flare = (fl, ff["flare"])
                s.lift = (0.0, 0.03, 0.03, 0.08, 0.5)
                g = _march(frame, ccfg, s, m, grade)
                h, hp = hang_of(frame, ccfg, g, front_fall=True)
                subs.append({"root": np.array(tuple(r)), "guide": g, "hang": h, "hang_pt": hp})
            s0 = subs[0]
            out.append({"guide": s0["guide"], "hang": s0["hang"], "hang_pt": s0["hang_pt"],
                        "side": side, "cfg": ff, "subs": subs})
    return out


# ---------------------------------------------------------------- strands

def sample_roots(surf, rng, n):
    """n roots with the hairline density ramp (feather band)."""
    h = surf.cfg["hairline"]
    pd = surf.cfg.get("part_density", 0.0)
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
            if d < 2 * f:
                # non-monotone: denser and sparser patches across the feather band
                prob = min(1.0, prob * surf.density(p))
            if pd > 0:
                # sample() is uniform: accept the rest at 1 / (1 + pd), the part line at 1.
                near = (Nn[i][2] > 0.5 and p[1] < surf.c.y + surf.cfg.get("part_back_m", 0.03)
                        and abs(p[0] - surf.part_x) < surf.cfg["part_width_m"])
                prob *= 1.0 if near else 1.0 / (1.0 + pd)
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
    levels = clump_levels(cc)
    v4 = cc.get("noise_after_clumps", True)

    def clump_factor(k):
        m = N.new("ShaderNodeMath")
        m.operation = "MULTIPLY"
        L.new(scaled("clump_w", k), m.inputs[0])
        L.new(attr("clump_ramp").outputs["Attribute"], m.inputs[1])
        return m.outputs[0]

    def noise_node():
        nn = group("Hair Curves Noise", Distance=nz["distance_m"], Scale=nz["scale"],
                   Shape=nz["shape"], Seed=seed)
        nn.inputs["Cumulative Offset"].default_value = False
        return nn

    chain = [gin]
    if not v4:
        chain.append(noise_node())   # v3 order: noise before the clumps
    for i, lv in enumerate(levels):
        c = group("Clump Hair Curves", Shape=lv["shape"], Seed=seed + 1 + i)
        c.label = f"Clump L{i + 1}"
        c.inputs["Tip Spread"].default_value = lv.get("tip_spread_m", 0.0)
        c.inputs["Clump Offset"].default_value = lv.get("offset_m", 0.0)
        c.inputs["Distance Falloff"].default_value = lv.get("falloff_m", 0.0)
        c.inputs["Preserve Length"].default_value = bool(cc.get("preserve_length", False))
        L.new(clump_factor(lv["factor"]), c.inputs["Factor"])
        if i > 0:
            L.new(attr(CLUMP_ATTRS[i], "INT").outputs["Attribute"], c.inputs["Guide Index"])
        chain.append(c)
    if v4:
        chain.append(noise_node())   # v4: noise and frizz after the clumps
    frizz = group("Frizz Hair Curves", Distance=fz["distance_m"], Shape=fz["shape"], Seed=seed + 3)
    fly = group("Hair Curves Noise", Distance=fw["distance_m"], Scale=fw["scale"],
                Shape=fw["shape"], Seed=seed + 4)
    L.new(attr("fly").outputs["Attribute"], fly.inputs["Factor"])
    chain += [frizz, fly]
    if gcfg["trim"].get("in_gn", True) and gcfg["trim"]["random"] > 0:
        trim = group("Trim Hair Curves", Seed=seed + 5)
        trim.inputs["Replace Length"].default_value = False
        trim.inputs["Length Factor"].default_value = 1.0
        trim.inputs["Random Offset"].default_value = gcfg["trim"]["random"]
        chain.append(trim)
    chain.append(gout)
    for a, c in zip(chain, chain[1:]):
        L.new(a.outputs[0], c.inputs[0])
    gout.location = (x[0] + 250, 0)
    return ng


# Curve attributes holding each clump level's guide (centre strand) index.
CLUMP_ATTRS = ["guide_curve_index", "sub_guide_index", "l3_guide_index", "l4_guide_index",
               "l5_guide_index"]


def clump_levels(cc):
    """The clump levels, coarse to fine; the v3 keys override levels 1-2."""
    levels = [dict(lv) for lv in cc.get("levels") or []]
    if not levels:
        levels = [{"count": 36, "factor": 0.85, "shape": 0.3}, {"count": 360, "factor": 0.8, "shape": 0.0}]
    for i, pre in enumerate(("primary", "secondary")):
        if i >= len(levels):
            break
        for key, lk in (("", "count"), ("_factor", "factor"), ("_shape", "shape")):
            if pre + key in cc:
                levels[i][lk] = cc[pre + key]
    if "tip_spread" in cc and levels:
        levels[0]["tip_spread_m"] = cc["tip_spread"]
    return levels[:len(CLUMP_ATTRS)]
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
    bsdf.name = "hair_bsdf"
    bsdf.model = sc["model"]
    bsdf.parametrization = "MELANIN"
    info = nt.nodes.new("ShaderNodeHairInfo")
    # Melanin per strand (curve attribute), per point darker at the root and
    # lighter at the tip (Hair Info intercept).
    mel = nt.nodes.new("ShaderNodeAttribute")
    mel.attribute_type = "GEOMETRY"
    mel.attribute_name = "melanin"
    rd, tl = sc.get("root_dark", 0.0), sc.get("tip_light", 0.0)
    if rd or tl:
        grad = nt.nodes.new("ShaderNodeMapRange")
        grad.name = "melanin_gradient"
        nt.links.new(info.outputs["Intercept"], grad.inputs["Value"])
        grad.inputs["To Min"].default_value = rd
        grad.inputs["To Max"].default_value = -tl
        add = nt.nodes.new("ShaderNodeMath")
        add.operation = "ADD"
        add.use_clamp = True
        nt.links.new(mel.outputs["Fac"], add.inputs[0])
        nt.links.new(grad.outputs["Result"], add.inputs[1])
        nt.links.new(add.outputs["Value"], bsdf.inputs["Melanin"])
    else:
        nt.links.new(mel.outputs["Fac"], bsdf.inputs["Melanin"])
    # Redness per strand (grey strands are neutral).
    red = nt.nodes.new("ShaderNodeAttribute")
    red.attribute_type = "GEOMETRY"
    red.attribute_name = "redness"
    nt.links.new(red.outputs["Fac"], bsdf.inputs["Melanin Redness"])
    for key, name in (("coat", "Coat"), ("radial_roughness", "Radial Roughness")):
        if sc.get(key) is not None and name in bsdf.inputs:
            bsdf.inputs[name].default_value = sc[key]
    if sc.get("offset_deg") is not None and "Offset" in bsdf.inputs:
        bsdf.inputs["Offset"].default_value = math.radians(sc["offset_deg"])
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
    rough.name = "hair_roughness"
    lo, hi = shader_roughness(sc, sc["model"])
    rough.inputs["To Min"].default_value = lo
    rough.inputs["To Max"].default_value = hi
    nt.links.new(info.outputs["Intercept"], rough.inputs["Value"])
    if sc.get("fly_roughness") is None:
        nt.links.new(rough.outputs["Result"], bsdf.inputs["Roughness"])
    else:
        fly = nt.nodes.new("ShaderNodeAttribute")
        fly.attribute_type = "GEOMETRY"
        fly.attribute_name = "fly"
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type = "FLOAT"
        nt.links.new(fly.outputs["Fac"], mix.inputs["Factor"])
        nt.links.new(rough.outputs["Result"], mix.inputs["A"])
        mix.inputs["B"].default_value = sc["fly_roughness"]
        nt.links.new(mix.outputs["Result"], bsdf.inputs["Roughness"])
    nt.links.new(info.outputs["Random"], bsdf.inputs["Random"])
    nt.links.new(bsdf.outputs[0], out.inputs["Surface"])
    mat["hair_shader"] = {"chiang_roughness": list(shader_roughness(sc, "CHIANG")),
                          "huang_roughness": list(shader_roughness(sc, "HUANG"))}
    return mat


def shader_roughness(sc, model):
    """(root, tip) roughness for a hair model: `roughness` is the configured
    model's; HUANG takes `huang_roughness` when the config model is CHIANG."""
    if model == "HUANG" and sc["model"] != "HUANG" and sc.get("huang_roughness"):
        return tuple(sc["huang_roughness"])
    if model == "CHIANG" and sc["model"] == "HUANG":
        return tuple(min(1.0, math.sqrt(r)) for r in sc["roughness"])
    return tuple(sc["roughness"])


def set_hair_model(mat, model):
    """Switch a hair_groom material between CHIANG and HUANG with the
    matching roughness (the hair test's A/B)."""
    nt = mat.node_tree
    bsdf = nt.nodes["hair_bsdf"]
    bsdf.model = model
    lo, hi = mat["hair_shader"][model.lower() + "_roughness"]
    nt.nodes["hair_roughness"].inputs["To Min"].default_value = lo
    nt.nodes["hair_roughness"].inputs["To Max"].default_value = hi


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

    def sub_rng(k):
        # Per-feature streams (v4 features): turning one on or off does not
        # reshuffle the draws of the others (fable_review §1.9).
        return np.random.default_rng([gcfg["seed"], k])

    m = gcfg["points"]
    grade = gcfg.get("point_grade", 1.0)
    upar = grade_param(m, grade)             # curve parameter of each point (~ arc fraction)
    c = frame.center
    part_x = c.x + ccfg["part_x_m"]
    keep = hair_clumps.growth_region(frame, ccfg)
    surf = Surface(frame, keep, gcfg, part_x)
    surf.flow = hair_frame.FlowField(frame, gcfg["field"]) if gcfg["comb"].get("mode") == "field" else None

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
    droot = np.array([surf.d_eff(p) for p in roots])

    # Front falls: each takes the strands nearest its root, which blend the
    # fall's sub-guides (v3: one guide copied rigidly, a slab).
    ffs = front_fall_guides(frame, ccfg, gcfg, surf, prng, m)
    kind = np.zeros(len(S), dtype=int)       # 0 main, 2 front fall
    ffid = np.full(len(S), -1)
    for fi, ff in enumerate(ffs):
        root = ff["guide"][1]
        free = np.where(kind == 0)[0]
        d = np.linalg.norm(roots[free] - root, axis=1)
        take = free[np.argsort(d, kind="stable")[:ff["cfg"]["strands"]]]
        kind[take] = 2
        ffid[take] = fi
        subs = ff["subs"]
        if len(subs) == 1:
            rel = ff["guide"] - ff["guide"][1]
            S[take] = roots[take][:, None, :] + rel[None]
            H[take] = ff["hang"][None]
            continue
        R = np.array([s_["root"] for s_ in subs])
        rel = np.array([s_["guide"] - s_["guide"][1] for s_ in subs])
        HH = np.array([s_["hang"] for s_ in subs])
        k = min(3, len(subs))
        for j in take:
            dd = np.linalg.norm(R - roots[j], axis=1)
            o = np.argsort(dd, kind="stable")[:k]
            w = 1.0 / (dd[o] + 0.002) ** 2
            w /= w.sum()
            S[j] = roots[j] + (rel[o] * w[:, None, None]).sum(0)
            H[j] = (HH[o] * w[:, None]).sum(0)

    # Clumps: strays; nested levels (level 1 = primary, 2 = secondary).
    cc = gcfg["clump"]
    levels = clump_levels(cc)
    n = len(S)
    # Strays (unclumped) fill between the locks; more of them low at the
    # back, so the gaps between clumps over the spine don't show the collar.
    nape_w = (np.clip((roots[:, 1] - c.y) / 0.04, 0, 1)
              * np.clip((frame.ears_max.z + 0.02 - roots[:, 2]) / 0.05, 0, 1))
    stray = (rng.random(n) < cc["stray"] + cc.get("stray_nape", 0.0) * nape_w) & (kind == 0)
    main = np.where((kind == 0) & ~stray)[0]
    lv = [np.arange(n) for _ in levels]
    sides = np.array([surf.part_side(p, q) for p, q in zip(roots, nrms)])
    pc = main[fps(roots[main], levels[0]["count"])]
    for j in main:
        d = np.linalg.norm(roots[pc] - roots[j], axis=1)
        ok = (sides[pc] * sides[j]) >= 0
        d[~ok] += 1.0
        lv[0][j] = pc[int(np.argmin(d))]
    ffm = np.where(kind == 2)[0]
    for fi in range(len(ffs)):
        members = np.where(ffid == fi)[0]
        if len(members) == 0:
            continue
        # the member nearest the fall's root (v3 took the lowest index)
        lv[0][members] = members[int(np.argmin(np.linalg.norm(roots[members] - ffs[fi]["guide"][1], axis=1)))]

    def subdivide(prev, members_all, k_of):
        """Next level inside each group of `prev`: k_of(group size) centres by
        farthest-point sampling, started at the group's own centre."""
        out = np.arange(n)
        if len(members_all) == 0:
            return out
        order = members_all[np.argsort(prev[members_all], kind="stable")]
        keys = prev[order]
        cuts = np.flatnonzero(np.diff(keys)) + 1
        for members in np.split(order, cuts):
            p0 = prev[members[0]]
            start = np.flatnonzero(members == p0)
            k = max(1, min(len(members), k_of(len(members))))
            sc_ = members[fps(roots[members], k, start=int(start[0]) if len(start) else 0)]
            if k == 1:
                out[members] = sc_[0]
                continue
            d = np.linalg.norm(roots[members][:, None, :] - roots[sc_][None], axis=2)
            out[members] = sc_[np.argmin(d, axis=1)]
        return out

    if len(levels) > 1:
        c2 = levels[1].get("count")
        lv[1] = subdivide(lv[0], main, lambda s: round(c2 * s / max(len(main), 1)) if c2
                          else round(s / levels[1]["size"]))
        lv[1][ffm] = subdivide(lv[0], ffm, lambda s: 3)[ffm]
    clumped = np.concatenate([main, ffm])
    for i in range(2, len(levels)):
        lvl = levels[i]
        size = lvl.get("size") or max(len(main), 1) / lvl["count"]
        lv[i] = subdivide(lv[i - 1], clumped, lambda s, size=size: round(s / size))
    prim, sub = lv[0], (lv[1] if len(levels) > 1 else lv[0])
    clump_w = np.where(stray, 0.0, 1.0)
    for fi, ff in enumerate(ffs):
        fc = ff["cfg"]
        clump_w[ffid == fi] = fc["clump_w"] if "clump_w" in fc else fc["factor"] / levels[0]["factor"]
    # Hairline: single hairs, no clumping right at the edge (not the front
    # falls: they root at the hairline and are locks by design).
    if cc.get("edge_m"):
        ed = (kind == 0) & (ffid < 0)
        clump_w[ed] *= np.array([smoothstep(0.0, cc["edge_m"], d) for d in droot[ed]])

    def recut(j, new_len):
        arc = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(S[j], axis=0), axis=1))])
        sn = np.concatenate([[0.0], arc[1] + (new_len - arc[1]) * grade_param(m - 1, grade)])
        H[j] = np.interp(sn, arc, H[j])
        S[j] = np.stack([np.interp(sn, arc, S[j][:, k]) for k in range(3)], axis=1)

    # The cut (v4): per lock, per strand (the tapered lock end), per layer.
    ct = gcfg.get("cut")
    tr = gcfg["trim"]
    py_trim = tr["random"] if not tr.get("in_gn", True) else 0.0
    cut_n = 0
    if ct or py_trim > 0:
        ct = ct or {"lock_m": [0.0, 0.0], "taper_m": 0.0, "taper_pow": 1.0, "layer_m": 0.0, "min_hang_m": 0.04}
        crng = sub_rng(101)
        lock = {int(q): crng.uniform(*ct["lock_m"]) for q in np.unique(sub)}
        top_w = np.clip((nrms[:, 2] - 0.3) / 0.6, 0, 1)
        u = crng.random(n)
        rad = ct.get("taper_radial", 0.0)
        if rad > 0:
            # Pointed lock ends: a strand's taper grows with its root's distance
            # from its level-2 lock centre (relative to the lock's extent), so the
            # outer strands of a lock end first and the clumped lock tapers to a point.
            dc = np.linalg.norm(roots[:n] - roots[sub], axis=1)
            dmax = np.zeros(n)
            np.maximum.at(dmax, sub, dc)
            u = (1 - rad) * u + rad * np.clip(dc / np.maximum(dmax[sub], 1e-6), 0, 1)
        cut = (np.array([lock[int(q)] for q in sub]) + ct["taper_m"] * u ** ct["taper_pow"]
               + ct["layer_m"] * top_w)
        trim_f = crng.uniform(0.0, py_trim, n)
        for j in np.where((kind == 0) & (H[:, -1] > ct["min_hang_m"]))[0]:
            arc_len = float(np.linalg.norm(np.diff(S[j], axis=0), axis=1).sum())
            new_len = max(arc_len - cut[j] - trim_f[j] * arc_len, arc_len - H[j, -1] + ct["min_hang_m"])
            if new_len < arc_len - 1e-4:
                recut(j, new_len)
                cut_n += 1

    # Ragged ends (v3): cut hanging strands back from the tip, per lock and per strand.
    en = gcfg["ends"]
    if en["clump"] > 0 or en["strand"] > 0:
        cut_l = {int(q): rng.uniform(0, en["clump"]) for q in np.unique(sub)}
        cut = np.array([cut_l[int(q)] for q in sub]) + rng.uniform(0, en["strand"], n)
        for j in np.where((kind == 0) & (H[:, -1] > en["min_hang_m"]))[0]:
            arc = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(S[j], axis=0), axis=1))])
            # never cut into the part on the skull (before the hang point)
            recut(j, max(arc[-1] * (1 - cut[j]), arc[-1] - H[j, -1] + en["min_hang_m"]))

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

    # Hairline edge hairs: lean toward the face over the first few mm, then
    # follow the comb (they point forward, then sweep back).
    hl = gcfg["hairline"]
    eg = hl.get("edge")
    w_edge = np.zeros(n)
    if eg:
        w_edge = np.where(kind == 0, 1.0 - np.clip(droot / eg["band_m"], 0.0, 1.0), 0.0) ** 1.5
        for j in np.flatnonzero(w_edge > 0.02):
            dv = surf.toward_line(roots[j], nrms[j])
            if dv is None:
                continue
            arc = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(S[j], axis=0), axis=1))])
            s_ = np.clip((arc - arc[1]) / eg["over_m"], 0.0, 1.0)
            S[j, 1:] += np.array(dv)[None] * (eg["kick_m"] * w_edge[j] * (s_ * s_ * (3 - 2 * s_)))[1:, None]
    pushed = push_out(frame, S, gcfg["gap_m"], ccfg.get("cloth_gap_m", 0.0))

    # Flyaways: mostly at the silhouette (sides, back) and the part.
    fw = gcfg["flyaways"]
    sil = np.abs(nrms[:, 0]) * 0.7 + np.clip(nrms[:, 1], 0, 1) * 0.5
    part_near = np.exp(-np.abs(roots[:, 0] - part_x) / 0.01) * (nrms[:, 2] > 0.5)
    wfly = (0.2 + sil + fw.get("part_weight", 1.5) * part_near) * (kind == 0)
    nfly = int(fw["share"] * n)
    fly = np.zeros(n)
    X = np.zeros((0, m, 3))
    src = np.zeros(0, dtype=int)
    if fw.get("mode", "noise") == "strays":
        # Separate stray hairs: copies of main strands that leave the mass.
        frng = sub_rng(202)
        src = frng.choice(n, nfly, replace=False, p=wfly / wfly.sum())
        X = S[src].copy()
        for k, j in enumerate(src):
            arc = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(X[k], axis=0), axis=1))])
            L = arc[-1]
            s0 = frng.uniform(*fw["start"]) * L
            Lk = max(L * frng.uniform(*fw["length"]), min(L, s0 + 0.03))
            sn = np.concatenate([[0.0], arc[1] + (Lk - arc[1]) * grade_param(m - 1, grade)])
            Xk = np.stack([np.interp(sn, arc, X[k][:, q]) for q in range(3)], axis=1)
            rad = Xk - np.array(c)
            rad[:, 2] = np.maximum(rad[:, 2], 0.0) * 0.5
            rad /= np.linalg.norm(rad, axis=1, keepdims=True) + 1e-9
            lat_ = np.stack([-rad[:, 1], rad[:, 0], np.zeros(m)], axis=1)
            mix = (frng.uniform(0.5, 1.0), frng.uniform(-1.0, 1.0), frng.uniform(-0.2, 0.5))
            dv = rad * mix[0] + lat_ * mix[1] + np.array([0.0, 0.0, 1.0]) * mix[2]
            dv /= np.linalg.norm(dv, axis=1, keepdims=True) + 1e-9
            t = np.clip((sn - s0) / max(Lk - s0, 1e-4), 0.0, 1.0)
            X[k] = Xk + dv * (frng.uniform(*fw["lift_m"]) * t ** 1.6)[:, None]
        if len(X):
            push_out(frame, X, gcfg["gap_m"], ccfg.get("cloth_gap_m", 0.0))
        fly[src] = 1.0     # the card baker draws its flyaway strips along these
    else:
        fly_idx = rng.choice(n, nfly, replace=False, p=wfly / wfly.sum())
        fly[fly_idx] = rng.uniform(0.5, 1.0, nfly)
        clump_w[fly_idx] *= 0.5
    nx = len(X)

    sh = gcfg["shader"]
    melanin = np.full(n, sh["melanin"])
    light = rng.random(n) < sh["light_share"]
    melanin[light] = sh["light_melanin"]
    if sh.get("fly_melanin") is not None and fw.get("mode", "noise") != "strays":
        melanin[fly > 0] = sh["fly_melanin"]   # thin backlit strays: no warm glow
    # Value per lock (secondary clump): some locks catch more light.
    lj = {int(q): rng.uniform(-1, 1) * sh.get("lock_melanin_jitter", 0.0) for q in np.unique(sub)}
    melanin = np.clip(melanin - np.abs(np.array([lj[int(q)] for q in sub])), 0.0, 1.0)
    redness = np.full(n, sh["redness"])
    # Hairline edge hairs a little lighter.
    if eg:
        melanin = np.clip(melanin + eg.get("melanin", 0.0) * w_edge, 0.0, 1.0)
    # Grey: weighted to the temples, neutral, some half-pigmented.
    grey = np.zeros(n, dtype=bool)
    if sh.get("grey_share"):
        grng = sub_rng(303)
        az = np.degrees(np.arctan2(roots[:, 0] - c.x, -(roots[:, 1] - c.y)))
        temple = (np.exp(-((np.abs(az) - sh["grey_temple_az_deg"]) / sh["grey_temple_sigma_deg"]) ** 2)
                  * np.clip((roots[:, 2] - frame.ear_z + 0.01) / 0.04, 0, 1))
        wg = 1.0 + (sh["grey_temple"] - 1.0) * temple
        grey = grng.random(n) < sh["grey_share"] * wg / wg.mean()
        melanin[grey] = grng.uniform(*sh["grey_melanin"], int(grey.sum()))
        redness[grey] = sh["grey_redness"]
    if nx:
        fly_x = np.ones(nx)
        mel_x, red_x = melanin[src], redness[src]
    else:
        fly_x, mel_x, red_x = np.zeros(0), np.zeros(0), np.zeros(0)

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

    # The Curves object: main strands | stray hairs | vellus.
    cv = bpy.data.hair_curves.new("hair_groom")
    cv.add_curves([m] * (n + nx) + [4] * nv)
    pos = np.concatenate([S.reshape(-1, 3), X.reshape(-1, 3), VS.reshape(-1, 3)]).astype(np.float32)
    cv.position_data.foreach_set("vector", pos.ravel())
    r0, r1 = gcfg["radius_m"]
    tf = gcfg.get("tip_taper_from", 0.0)
    if tf > 0:
        prof = r0 * (1.0 - (1.0 - gcfg.get("tip_taper", 1.0)) * np.clip((upar - tf) / max(1 - tf, 1e-6), 0, 1))
    else:
        prof = r0 + (r1 - r0) * upar ** 1.5
    rad = prof[None, :] * np.ones((n, 1))
    if eg:
        rad *= (1.0 - (1.0 - eg.get("radius", 1.0)) * w_edge)[:, None]
    xrad = (r0 * fw.get("radius", 1.0) * (1.0 - (1.0 - fw.get("tip_radius", 1.0)) * upar))[None, :] \
        * np.ones((nx, 1))
    vt = np.linspace(0, 1, 4)
    vrad = np.tile(vc["radius_m"] * (1 - 0.5 * vt), nv)
    radius = np.concatenate([rad.ravel(), xrad.ravel(), vrad]).astype(np.float32)
    ra = cv.attributes.get("radius") or cv.attributes.new("radius", "FLOAT", "POINT")
    ra.data.foreach_set("value", radius)
    # Clump ramp per point: low while on the skull, full past the hang point.
    ramp = cc["scalp"] + (1 - cc["scalp"]) * np.clip(H / cc["ramp_m"], 0, 1) ** 1.5
    ramp[kind == 2] = np.clip(H[kind == 2] / 0.03, 0, 1)
    cr = cv.attributes.new("clump_ramp", "FLOAT", "POINT")
    cr.data.foreach_set("value", np.concatenate([ramp.ravel(), np.zeros(nx * m + nv * 4)]).astype(np.float32))

    def curve_attr(name, dtype, values):
        a = cv.attributes.new(name, dtype, "CURVE")
        a.data.foreach_set("value", values)

    nall = n + nx + nv
    own = np.arange(nall)
    for i, idx in enumerate(lv):
        curve_attr(CLUMP_ATTRS[i], "INT", np.concatenate([idx, own[n:]]).astype(np.int32))
    curve_attr("clump_w", "FLOAT", np.concatenate([clump_w, np.zeros(nx + nv)]).astype(np.float32))
    curve_attr("fly", "FLOAT", np.concatenate([fly if not nx else np.zeros(n), fly_x,
                                               np.zeros(nv)]).astype(np.float32))
    curve_attr("melanin", "FLOAT", np.concatenate([melanin, mel_x, np.full(nv, vc["melanin"])]).astype(np.float32))
    curve_attr("redness", "FLOAT", np.concatenate([redness, red_x, np.full(nv, sh["redness"])]).astype(np.float32))
    curve_attr("kind", "INT", np.concatenate([kind, np.full(nx, 3), np.ones(nv)]).astype(np.int32))
    cv.materials.append(hair_material(gcfg))
    obj = bpy.data.objects.new("hair_groom", cv)
    export.hero_collection().objects.link(obj)
    mod = obj.modifiers.new("groom", "NODES")
    mod.node_group = groom_nodes(gcfg)

    tint = scalp_tint(b, frame, keep, surf, gcfg)
    render = render_settings(gcfg.get("render"))

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

    clumped_main = (kind == 0) & ~stray
    b.notes["hair_groom"] = {
        "guides": int(len(G)), "strands": int(n), "stray_hairs": int(nx), "vellus": int(nv),
        "strand_count_total": int(nall), "points_per_strand": int(m), "point_grade": grade,
        "front_fall_guides": len(ffs),
        "front_fall_sub_guides": int(sum(len(f["subs"]) for f in ffs)),
        "front_fall_strands": int((kind == 2).sum()),
        "primary_clumps": int(len(np.unique(prim[clumped_main]))),
        "secondary_clumps": int(len(np.unique(sub[clumped_main]))),
        "clump_levels": [{"clumps": int(len(np.unique(idx[clumped_main]))),
                          "strands_per_clump": round(float(clumped_main.sum()) / max(len(np.unique(idx[clumped_main])), 1), 1),
                          "factor": lvl["factor"], "shape": lvl.get("shape", 0.0),
                          "tip_spread_m": lvl.get("tip_spread_m", 0.0), "offset_m": lvl.get("offset_m", 0.0),
                          "falloff_m": lvl.get("falloff_m", 0.0)}
                         for idx, lvl in zip(lv, levels)],
        "clump_preserve_length": bool(cc.get("preserve_length", False)),
        "strays": int(stray.sum()), "flyaways": int(nfly), "flyaway_mode": fw.get("mode", "noise"),
        "cut_strands": int(cut_n), "edge_strands": int((w_edge > 0.02).sum()),
        "grey_share": round(float(grey.mean()), 4), "comb_mode": gcfg["comb"].get("mode"),
        "shader_model": sh["model"], "melanin": sh["melanin"], "radius_m": gcfg["radius_m"],
        "points_pushed": int(pushed),
        "points": int(len(pos)), "evaluated_points": int(len(ev["pos"])),
        "render": render,
        "essentials": ESSENTIALS + " (CC0 1.0, datafiles/assets/LICENSE)",
        "tint": tint.name,
    }
    return {"obj": obj, "surf": surf, "keep": keep,
            "kind": np.concatenate([kind, np.full(nx, 3), np.ones(nv, int)]),
            "prim": prim, "sub": sub, "stray": stray, "fly": fly, "hang": H, "roots": roots,
            "nrms": nrms, "n": n, "m": m, "eval": ev, "guides": G, "guide_hang": GH,
            "vellus_pt0": (n + nx) * m, "vellus_pt1": (n + nx) * m + nv * 4,
            "ff": ffs, "cfg": gcfg}


def render_settings(rc):
    """Cycles curve shape and bounces saved with the kept .blend."""
    if not rc:
        return None
    sc = bpy.context.scene
    out = {}
    try:
        if rc.get("curve_shape"):
            sc.cycles_curves.shape = rc["curve_shape"]
            sc.cycles_curves.subdivisions = rc.get("curve_subdivisions", 2)
            out["curve_shape"] = rc["curve_shape"]
        if rc.get("glossy_bounces"):
            sc.cycles.glossy_bounces = rc["glossy_bounces"]
            sc.cycles.max_bounces = max(sc.cycles.max_bounces, 2 * rc["glossy_bounces"])
            out["glossy_bounces"] = rc["glossy_bounces"]
    except AttributeError as e:   # Cycles not registered
        out["error"] = str(e)
    return out


def evaluated(obj):
    """Evaluated groom: positions (P, 3) and curve offsets (C + 1)."""
    dg = bpy.context.evaluated_depsgraph_get()
    cd = obj.evaluated_get(dg).data
    pos = np.empty(len(cd.points) * 3, dtype=np.float32)
    cd.attributes["position"].data.foreach_get("vector", pos)
    offs = np.empty(len(cd.curves) + 1, dtype=np.int32)
    cd.curve_offset_data.foreach_get("value", offs)
    return {"pos": pos.reshape(-1, 3), "offs": offs}
