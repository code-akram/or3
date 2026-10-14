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
  lids     rays from the eyeball outward against the body give, per eye
           direction, whether a lid covers it and how far the nearest lid
           edge is: the lid occlusion (upper 0.6 over 1.5 mm, lower 0.3 over
           0.8 mm) is baked into the albedo and the ORM occlusion.
  material Principled: albedo texture, roughness from an ORM texture (cornea
           and iris glossy, sclera satin), high specular, so the eye reads
           wet under the key and rim lights. glTF PBR only (no refraction).
  hero     (hero(b), after the GLB export; hero_only collection) a denser
           eyeball with the iris recessed 0.5 mm below the limbus, a
           separate refractive cornea + tear-film shell (IOR 1.376,
           transparent to shadow rays), a tear meniscus along the lower lid
           and a caruncle at the inner canthus, all skinned to the head bone;
           the game eye is hidden in renders.

Config: cfg["head"]["refine"]["eyes"] (null keeps the MPFB eyes).
"""

import math

import bmesh
import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from . import export, head_refine, skin_tex

DEFAULTS = {
    "segments": 48, "rings": 36, "tex_px": 1024,
    "cornea_bulge_mm": 2.2, "cornea_deg": 34.0,
    # Real-size iris and pupil (mm) on the fitted sphere: they override the
    # *_deg values; the cornea edge sits cornea_margin_deg past the limbus.
    # The MPFB eye sphere is ~15 mm in radius, so iris_deg 30 gave a 15 mm iris.
    "iris_mm": 11.7, "pupil_mm": 4.0, "cornea_margin_deg": 1.5,
    # Eyes converge on a point this far ahead of the eye midpoint (m); 0 = parallel.
    "converge_m": 1.2,
    "pupil_deg": 9.0, "iris_deg": 30.0, "limbus_deg": 2.5,
    "iris": "#4a2e1a", "iris_inner": "#20120a", "iris_outer": "#2e1d10", "collarette": "#8e5e33",
    "outer_mix": 0.6, "limbus_frac": 0.12, "limbal_dark": 0.55,
    "sclera": "#bdab9d", "sclera_back": "#86675f", "vein": "#a2423a", "vein_amount": 0.8,
    "redness": 0.45, "sclera_corner": 0.30,
    # Lid occlusion baked into the eye (the game's eye-occlusion shell): darker
    # within *_mm of the upper / lower lid, from rays cast against the body.
    "lid_occlusion": True, "lid_probe_mm": 4.0,
    "lid_occl_upper": 0.6, "lid_occl_upper_mm": 1.5, "lid_occl_lower": 0.3, "lid_occl_lower_mm": 0.8,
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


def eye_frame(axis):
    """(axis, ex, ez): ex horizontal (+X for a -Y gaze), ez up; matches eyeball()."""
    axis = np.asarray(axis, dtype=np.float64)
    axis = axis / np.linalg.norm(axis)
    ez = np.array([0.0, 0.0, 1.0])
    ex = np.cross(ez, axis)
    ex /= np.linalg.norm(ex)
    ez = np.cross(axis, ex)
    return axis, ex, ez


def bulge_profile(radius, bulge_m, cornea_deg, offset_m=0.0):
    cdeg = math.radians(cornea_deg)

    def f(th):
        r = radius + offset_m
        if th < cdeg:
            r += bulge_m * max(1 - (th / cdeg) ** 2, 0.0) ** 1.3
        return r * math.cos(th), r * math.sin(th)
    return f


def eyeball(bm, centre, radius, side, c, uv_layer, dl, head_gi, axis=None, profile=None,
            rings=None, segs=None, v_uniform=False, theta_max=math.pi):
    """Append one eyeball to bm. side: 0 (character's left, +x) or 1.
    axis: gaze direction (unit, local space); default -Y. profile(theta) ->
    (axial, lateral) distances from the centre (default: sphere + corneal
    bulge). v_uniform spaces the rings uniformly in v = sqrt(theta / pi)
    (dense at the front). theta_max < pi leaves an open shell."""
    segs = segs or c["segments"]
    rings = rings or c["rings"]
    if profile is None:
        profile = bulge_profile(radius, c["cornea_bulge_mm"] * 0.001, c["cornea_deg"])
    axis, ex, ez = eye_frame(np.array([0.0, -1.0, 0.0]) if axis is None else axis)
    vmax = math.sqrt(theta_max / math.pi)
    closed = theta_max >= math.pi - 1e-6

    def theta(i):
        t = i / rings
        return math.pi * (t * vmax) ** 2 if v_uniform else theta_max * t
    grid = []
    for i in range(rings + 1):
        th = theta(i)
        a, l = profile(th)
        row = []
        for j in range(segs):
            ph = 2 * math.pi * j / segs
            v = bm.verts.new(centre + axis * a + (ex * math.cos(ph) + ez * math.sin(ph)) * l)
            v[dl][head_gi] = 1.0
            row.append(v)
            if i == 0 or (i == rings and closed):
                break
        grid.append(row)
    bm.verts.ensure_lookup_table()

    def uv(i, j):
        return (((j % segs) / segs) * 0.5 + 0.5 * side, math.sqrt(theta(i) / math.pi))
    for i in range(rings):
        for j in range(segs):
            j1 = (j + 1) % segs
            if i == 0:
                vs = [grid[0][0], grid[1][j], grid[1][j1]]
                uvs = [((j + 0.5) / segs * 0.5 + 0.5 * side, 0.0), uv(1, j), uv(1, j + 1)]
            elif i == rings - 1 and closed:
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


def outward(bm, centres):
    """Flip faces whose normal points toward their eye centre (refraction needs it)."""
    bm.normal_update()
    flip = []
    for f in bm.faces:
        cen = f.calc_center_median()
        c = min(centres, key=lambda q: (Vector(q) - cen).length)
        if f.normal.dot(cen - Vector(c)) < 0:
            flip.append(f)
    if flip:
        bmesh.ops.reverse_faces(bm, faces=flip)


# --- lids: which eye directions the body covers -----------------------------------------------

class LidMap:
    """Per eye, on a (theta, phi) grid in the eye's own frame: covered[i, j]
    when a ray from just under the eyeball surface outward along that
    direction hits the body within probe_mm (the lids and the canthi), plus
    the distance (mm, on the sphere) from each direction to the nearest
    covered direction of the upper and of the lower lid."""

    def __init__(self, bvh, centre, radius, axis, cfg, n_th=200, n_ph=180, th_max_deg=80.0):
        self.centre, self.radius = np.asarray(centre), radius
        self.axis, self.ex, self.ez = eye_frame(axis)
        self.th = np.radians(np.linspace(0.0, th_max_deg, n_th))
        self.ph = np.linspace(0.0, 2 * math.pi, n_ph, endpoint=False)
        self.dth = self.th[1] - self.th[0]
        probe = cfg["lid_probe_mm"] * 0.001
        cov = np.zeros((n_th, n_ph), bool)
        T, PH = np.meshgrid(self.th, self.ph, indexing="ij")
        D = (self.axis[None, None] * np.cos(T)[..., None]
             + (self.ex[None, None] * np.cos(PH)[..., None] + self.ez[None, None] * np.sin(PH)[..., None]) * np.sin(T)[..., None])
        self.D = D
        start = radius - 0.0002
        for i in range(n_th):
            for j in range(n_ph):
                d = Vector(D[i, j])
                hit = bvh.ray_cast(Vector(self.centre) + d * start, d, probe + 0.0002)
                cov[i, j] = hit[0] is not None
        cov[-1, :] = True
        self.cov = cov
        up = np.sin(PH) > 0
        vis = ~cov
        edge = cov & (np.roll(vis, 1, 0) | np.roll(vis, -1, 0) | np.roll(vis, 1, 1) | np.roll(vis, -1, 1))
        edge[0, :] = edge[-1, :] = False
        self.dist = {}
        for name, sel in (("upper", up), ("lower", ~up)):
            pts = D[edge & sel]
            d = np.full(T.shape, 1e3, np.float32)
            if len(pts):
                flat = D.reshape(-1, 3)
                out = np.empty(len(flat), np.float32)
                for k in range(0, len(flat), 4096):
                    ch = flat[k:k + 4096]
                    out[k:k + 4096] = np.sqrt(((ch[:, None, :] - pts[None]) ** 2).sum(-1)).min(1) * radius * 1000
                d = out.reshape(T.shape)
                d[cov & sel] = 0.0
            self.dist[name] = d
        # first covered theta along each phi (the aperture boundary)
        first = np.argmax(cov, axis=0)
        self.boundary = self.th[first]
        # the aperture: open cells connected to the gaze axis (flood fill)
        n_th, n_ph = cov.shape
        ap = np.zeros_like(cov)
        stack = [(0, j) for j in range(n_ph) if not cov[0, j]]
        for i, j in stack:
            ap[i, j] = True
        while stack:
            i, j = stack.pop()
            for a, b in ((i + 1, j), (i - 1, j), (i, (j + 1) % n_ph), (i, (j - 1) % n_ph)):
                if 0 <= a < n_th and not cov[a, b] and not ap[a, b]:
                    ap[a, b] = True
                    stack.append((a, b))
        self.aperture = ap

    def canthus(self, nasal):
        """(theta, phi) of the aperture cell furthest toward `nasal` (unit, eye-local)."""
        score = np.where(self.aperture, self.D @ np.asarray(nasal, dtype=np.float64), -np.inf)
        i, j = np.unravel_index(np.argmax(score), score.shape)
        return float(self.th[i]), float(self.ph[j])

    def occlusion(self, cfg, k=1.0):
        """1 = open, lower = shadowed by the lids (upper strongest)."""
        ss = skin_tex.smoothstep
        o = 1.0 - k * cfg["lid_occl_upper"] * (1 - ss(0.0, cfg["lid_occl_upper_mm"], self.dist["upper"])) \
            - k * cfg["lid_occl_lower"] * (1 - ss(0.0, cfg["lid_occl_lower_mm"], self.dist["lower"]))
        return np.clip(o, 0.0, 1.0)

    def sample(self, grid, theta, phi):
        """Bilinear sample of a (n_th, n_ph) grid at theta (rad), phi (rad)."""
        n_th, n_ph = grid.shape
        fi = np.clip(theta / self.dth, 0, n_th - 1.001)
        fj = (phi % (2 * math.pi)) / (2 * math.pi) * n_ph
        i0 = np.floor(fi).astype(int)
        j0 = np.floor(fj).astype(int) % n_ph
        j1 = (j0 + 1) % n_ph
        ti = fi - i0
        tj = fj - np.floor(fj)
        a = grid[i0, j0] * (1 - tj) + grid[i0, j1] * tj
        b = grid[i0 + 1, j0] * (1 - tj) + grid[i0 + 1, j1] * tj
        return a * (1 - ti) + b * ti

    def direction(self, theta, phi):
        return self.axis * math.cos(theta) + (self.ex * math.cos(phi) + self.ez * math.sin(phi)) * math.sin(theta)


def lid_maps(b, body, eye_obj, spheres_local, axes_local, cfg):
    """LidMaps for both eyes, in the eye object's local space."""
    co = skin_tex._eval_world_coords(body)
    if co is None:
        co = np.array([(body.matrix_world @ v.co)[:] for v in body.data.vertices])
    inv = np.array(eye_obj.matrix_world.inverted())
    co = co @ inv[:3, :3].T + inv[:3, 3]
    bvh = BVHTree.FromPolygons([Vector(p) for p in co], [list(p.vertices) for p in body.data.polygons])
    return [LidMap(bvh, c, r, a, cfg) for (c, r), a in zip(spheres_local, axes_local)]


# --- texture ----------------------------------------------------------------------------------

def texture(c, lids=None):
    """Albedo (linear, without lid occlusion), roughness, and the lid
    occlusion factor per texel (1 = open)."""
    n = c["tex_px"]
    seed = int(c["seed"])
    H = skin_tex.HEX
    lin = skin_tex.srgb_to_linear
    ss = skin_tex.smoothstep
    out = np.zeros((n, n, 3), np.float32)
    rough = np.zeros((n, n), np.float32)
    occl = np.ones((n, n), np.float32)
    v = (np.arange(n, dtype=np.float32) + 0.5) / n           # rows: v
    for side in (0, 1):
        cols = slice(side * n // 2, (side + 1) * n // 2)
        u = (np.arange(n // 2, dtype=np.float32) + 0.5) / (n // 2)   # 0..1 around the axis
        U, V = np.meshgrid(u, v)
        theta = np.degrees(V * V * math.pi)                           # angle from the axis
        phi = U * 2 * math.pi
        pd, idg, ld = c["pupil_deg"], c["iris_deg"], c["limbus_deg"]
        # radial coordinate inside the iris 0 (pupil edge) .. 1 (limbus)
        ri = np.clip((theta - pd) / (idg - pd), 0, 1)
        fib = fbm(U * 140, ri * 6 + side * 7, 140, seed + 11, 3)           # radial fibres
        fib2 = fbm(U * 60, ri * 3, 60, seed + 23, 2)
        crypt = fbm(U * 90, ri * 14, 90, seed + 31, 3)
        iris = lin(H(c["iris"]))[None, None] * (0.55 + 0.95 * fib + 0.25 * fib2)[..., None]
        inner = lin(H(c["iris_inner"]))
        outer = lin(H(c["iris_outer"]))
        coll = lin(H(c["collarette"]))
        w_in = skin_tex.gauss(ri, 0.10)
        iris = iris * (1 - w_in[..., None]) + inner[None, None] * w_in[..., None]
        cw = skin_tex.gauss(ri - (0.36 + 0.06 * (fib2 - 0.5)), 0.045) * (0.5 + fib)
        cw = np.clip(cw, 0, 1)
        iris = iris * (1 - 0.8 * cw[..., None]) + coll[None, None] * (0.8 * cw)[..., None]
        cr = ss(0.62, 0.72, crypt) * ss(0.35, 0.6, ri)
        iris *= (1 - 0.55 * cr)[..., None]
        w_out = ss(0.55, 1.0, ri) ** 1.5 * c["outer_mix"]
        iris = iris * (1 - w_out[..., None]) + outer[None, None] * w_out[..., None]
        # limbal ring: darker over the outer limbus_frac of the iris radius
        limb = ss(1.0 - c["limbus_frac"], 1.0, ri) * ss(idg + 0.6, idg - 0.2, theta)
        iris *= (1 - c["limbal_dark"] * limb)[..., None]
        # sclera
        back = ss(55.0, 120.0, theta)
        scl = lin(H(c["sclera"]))[None, None] * (1 - back[..., None]) + lin(H(c["sclera_back"]))[None, None] * back[..., None]
        scl *= (0.96 + 0.08 * fbm(U * 12, V * 6, 12, seed + 41, 2))[..., None]
        # conjunctival vessels: thin meandering lines (iso-lines of a warped,
        # meridionally stretched noise), a finer branch set, both fading
        # toward the limbus and denser at the nasal and temporal corners
        veins2 = fbm(U * 30, V * 10, 30, seed + 61, 2)
        wu = U + 0.012 * (fbm(U * 24, V * 9, 24, seed + 71, 2) - 0.5)
        ridge = 1 - np.abs(2 * fbm(wu * 48, V * 5 + 0.5, 48, seed + 53, 3) - 1)
        ridge2 = 1 - np.abs(2 * fbm(wu * 120, V * 14, 120, seed + 59, 2) - 1)
        side_w = 0.35 + 0.65 * np.abs(np.cos(phi)) ** 2
        patch = ss(0.40, 0.62, fbm(U * 10, V * 3, 10, seed + 67, 2))     # vessels come in sectors
        vein = ss(0.945, 0.99, ridge) * (0.35 + 0.65 * patch) + 0.6 * ss(0.96, 0.995, ridge2) * patch
        vein = np.clip(vein, 0, 1) * side_w * ss(idg + 3, idg + 14, theta) * ss(120, 70, theta)
        vc = lin(H(c["vein"]))
        scl = scl * (1 - (vein * c["vein_amount"])[..., None]) + vc[None, None] * (vein * c["vein_amount"])[..., None]
        halo = skin_tex.gauss(theta - idg - 3, 4.0) * c["redness"] * (0.6 + 0.4 * veins2)
        scl *= (1 + halo[..., None] * (np.array((1.08, 0.78, 0.76), np.float32) - 1))
        # corners (nasal and temporal) darker and warmer
        corner = np.abs(np.cos(phi)) ** 3 * ss(idg + 6, idg + 22, theta)
        scl *= (1 + (corner * c["sclera_corner"])[..., None] * (np.array((0.97, 0.84, 0.81), np.float32) - 1))
        # compose
        in_iris = ss(idg + 0.4, idg - 0.4, theta)
        col = iris * in_iris[..., None] + scl * (1 - in_iris)[..., None]
        pupil = ss(pd + 0.8, pd - 0.6, theta)
        col *= (1 - pupil)[..., None]
        col += pupil[..., None] * np.array((0.004, 0.003, 0.003), np.float32)
        out[:, cols] = col
        rough[:, cols] = c["rough_iris"] * ss(c["cornea_deg"] + 2, c["cornea_deg"] - 2, theta) \
            + c["rough_sclera"] * ss(c["cornea_deg"] - 2, c["cornea_deg"] + 2, theta)
        if lids is not None:
            lm = lids[side]
            occl[:, cols] = lm.sample(lm.occlusion(c), np.radians(theta), phi)
    return np.clip(out, 0, 1), np.clip(rough, 0.02, 1), occl


# --- stage ------------------------------------------------------------------------------------

def _skin_to_head(new, old):
    for col in old.users_collection:
        col.objects.link(new)
    new.parent = old.parent
    new.matrix_parent_inverse = old.matrix_parent_inverse.copy()
    new.matrix_world = old.matrix_world.copy()
    new.vertex_groups.new(name="head")
    for m in old.modifiers:
        if m.type == "ARMATURE":
            mod = new.modifiers.new("Armature", "ARMATURE")
            mod.object = m.object


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
    spheres = []
    for side, sel in ((0, co[:, 0] > 0), (1, co[:, 0] < 0)):
        pts = co[sel]
        # sphere from the back half (the MPFB eye has a corneal bulge)
        cen0 = pts.mean(0)
        backp = pts[pts[:, 1] > cen0[1]]
        spheres.append(fit_sphere(backp if len(backp) > 12 else pts))
    from . import head_sculpt
    spheres, fit["sculpt_globes"] = head_sculpt.shipped_spheres(b, head_refine.staged_body(b), spheres)
    radius_m = float(np.mean([r for _, r in spheres]))
    if cfg.get("iris_mm"):
        cfg["iris_deg"] = math.degrees(math.asin(min(cfg["iris_mm"] * 0.0005 / radius_m, 0.95)))
        cfg["cornea_deg"] = cfg["iris_deg"] + cfg["cornea_margin_deg"]
    if cfg.get("pupil_mm"):
        cfg["pupil_deg"] = math.degrees(math.asin(min(cfg["pupil_mm"] * 0.0005 / radius_m, 0.9)))
    mid = (spheres[0][0] + spheres[1][0]) * 0.5
    rot = np.array(new.matrix_world.to_3x3().inverted())
    local_spheres, local_axes = [], []
    for side, (centre, radius) in enumerate(spheres):
        axis = np.array([0.0, -1.0, 0.0])
        if cfg.get("converge_m"):
            target = mid + np.array([0.0, -float(cfg["converge_m"]), 0.0])
            axis = (target - centre) / np.linalg.norm(target - centre)
        fit[("left", "right")[side]] = {"centre": [round(float(x), 4) for x in centre], "radius_mm": round(radius * 1000, 2),
                                         "axis": [round(float(x), 4) for x in axis]}
        local = (inv @ np.append(centre, 1.0))[:3]
        la = rot @ axis
        la = la / np.linalg.norm(la)
        local_spheres.append((local, radius))
        local_axes.append(la)
        eyeball(bm, local, radius, side, cfg, uvl, dl, head_gi, axis=la)
    bm.to_mesh(new.data)
    bm.free()
    new.data.update()
    for m in old.modifiers:
        if m.type == "ARMATURE":
            mod = new.modifiers.new("Armature", "ARMATURE")
            mod.object = m.object
    # lids: what the body covers, for the baked lid occlusion and the hero parts
    lids = None
    body = head_refine.staged_body(b)
    if cfg.get("lid_occlusion", True) and body is not None:
        lids = lid_maps(b, body, new, local_spheres, local_axes, cfg)
    # texture + material
    alb, rough, occl = texture(cfg, lids)
    out_dir = b.out_dir if (rcfg.get("skin") or {}).get("save_maps") else None
    ia = skin_tex.make_image("eyes_albedo", alb * occl[..., None], True, out_dir)
    io = skin_tex.make_image("eyes_orm", np.stack([occl, rough, np.zeros_like(rough)], -1), False, out_dir)
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
    notes = {"fit": fit, "tris": len(new.data.polygons) * 2, "tex_px": cfg["tex_px"],
             "iris_deg": round(cfg["iris_deg"], 2), "pupil_deg": round(cfg["pupil_deg"], 2),
             "cornea_deg": round(cfg["cornea_deg"], 2)}
    if lids is not None:
        r = radius_m * 1000
        ap = {}
        for side, lm in zip(("left", "right"), lids):
            up = lm.boundary[np.argmin(np.abs(lm.ph - math.pi / 2))]
            lo = lm.boundary[np.argmin(np.abs(lm.ph - 3 * math.pi / 2))]
            ap[side] = {"upper_mm": round(r * math.sin(up), 2), "lower_mm": round(-r * math.sin(lo), 2),
                        "iris_r_mm": round(cfg["iris_mm"] / 2, 2)}
        notes["aperture"] = ap
    b.notes["eyes"] = notes
    b.eye_hero = {"obj": new.name, "spheres": local_spheres, "axes": local_axes, "lids": lids,
                  "cfg": cfg, "albedo": alb, "occl": occl, "rough": rough}
    return notes


# --- hero (Cycles only; hero_only collection, after the GLB export) ----------------------------

HERO = {
    "rings": 120, "segments": 96,
    "recess_mm": 0.5,          # iris plane below the limbus plane
    "iris_cone_mm": 0.15,      # the pupil margin sits a little forward of the iris root
    "cornea_bulge_mm": 1.3,    # apex over the sphere (~3 mm over the iris plane)
    "film_mm": 0.02,           # shell offset over the eyeball at the limbus
    "cornea_skirt_deg": 1.5,   # the shell ends this far past the limbus
    "cornea_ior": 1.376, "cornea_rough": 0.02, "film_rough": 0.04,
    "occl_mix": 0.5,           # share of the baked lid occlusion kept on the hero eyeball
    "iris_rough": 0.6, "sclera_rough": 0.14, "sclera_specular": 0.5, "eyeball_sss": 0.3,
    "meniscus_mm": 0.15, "meniscus_rough": 0.05, "meniscus_ior": 1.336,
    "caruncle": "#a57a72", "caruncle_mm": (1.8, 1.1, 0.5), "caruncle_deg": 5.0,
}


def _shadow_transparent(nt, p):
    """Alpha 0 for shadow rays: light reaches the iris through refractive parts."""
    lp = nt.nodes.new("ShaderNodeLightPath")
    inv = nt.nodes.new("ShaderNodeMath")
    inv.operation = "SUBTRACT"
    inv.inputs[0].default_value = 1.0
    nt.links.new(lp.outputs["Is Shadow Ray"], inv.inputs[1])
    nt.links.new(inv.outputs[0], p.inputs["Alpha"])


def _principled(name):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    return m, m.node_tree, next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")


def _hero_mesh(name, old, build_fn):
    obj = bpy.data.objects.new(name, bpy.data.meshes.new(name))
    _skin_to_head(obj, old)
    bm = bmesh.new()
    uvl = bm.loops.layers.uv.new("UVMap")
    dl = bm.verts.layers.deform.verify()
    build_fn(bm, uvl, dl, obj.vertex_groups["head"].index)
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    return obj


def _tube(bm, pts, radius, sides, dl, gi):
    """A closed-ended tube along pts (n, 3)."""
    pts = np.asarray(pts)
    rings = []
    for k, p in enumerate(pts):
        t = pts[min(k + 1, len(pts) - 1)] - pts[max(k - 1, 0)]
        t /= np.linalg.norm(t)
        a = np.cross(t, [0.0, 0.0, 1.0])
        if np.linalg.norm(a) < 1e-6:
            a = np.cross(t, [1.0, 0.0, 0.0])
        a /= np.linalg.norm(a)
        bvec = np.cross(t, a)
        s = math.sin(math.pi * min(k, len(pts) - 1 - k) / max(len(pts) - 1, 1) * 2) if len(pts) > 2 else 1.0
        r = radius * (0.35 + 0.65 * min(max(s, 0.0) * 3, 1.0))      # tapered ends
        ring = []
        for q in range(sides):
            an = 2 * math.pi * q / sides
            v = bm.verts.new(p + (a * math.cos(an) + bvec * math.sin(an)) * r)
            v[dl][gi] = 1.0
            ring.append(v)
        rings.append(ring)
    for r0, r1 in zip(rings[:-1], rings[1:]):
        for q in range(sides):
            f = bm.faces.new([r0[q], r1[q], r1[(q + 1) % sides], r0[(q + 1) % sides]])
            f.smooth = True
    bm.faces.new(list(reversed(rings[0])))
    bm.faces.new(rings[-1])


def hero(b):
    data = getattr(b, "eye_hero", None)
    if not data:
        return None
    old = bpy.data.objects.get(data["obj"])
    if old is None:
        return None
    cfg = data["cfg"]
    hc = dict(HERO)
    hc.update(cfg.get("hero") or {})
    if not hc.get("enabled", True):
        return None
    col = export.hero_collection()
    spheres, axes, lids = data["spheres"], data["axes"], data["lids"]
    rad = [r for _, r in spheres]

    # eyeball: recessed, slightly conical iris; same polar UVs as the game eye
    def iris_profile(radius):
        ti = math.radians(cfg["iris_deg"])
        plane = radius * math.cos(ti) - hc["recess_mm"] * 0.001

        def f(th):
            if th <= ti:
                cone = hc["iris_cone_mm"] * 0.001 * (1 - th / ti)
                return plane + cone, radius * math.sin(th)
            return radius * math.cos(th), radius * math.sin(th)
        return f

    def build_ball(bm, uvl, dl, gi):
        for side, ((c, r), a) in enumerate(zip(spheres, axes)):
            eyeball(bm, c, r, side, cfg, uvl, dl, gi, axis=a, profile=iris_profile(r),
                    rings=hc["rings"], segs=hc["segments"], v_uniform=True)
    ball = _hero_mesh("Human.eyes_hero", old, build_ball)

    def build_cornea(bm, uvl, dl, gi):
        for side, ((c, r), a) in enumerate(zip(spheres, axes)):
            eyeball(bm, c, r, side, cfg, uvl, dl, gi, axis=a,
                    profile=bulge_profile(r, hc["cornea_bulge_mm"] * 0.001, cfg["cornea_deg"], hc["film_mm"] * 0.001),
                    rings=hc["rings"] // 3, segs=hc["segments"], v_uniform=True,
                    theta_max=math.radians(cfg["cornea_deg"] + hc["cornea_skirt_deg"]))
        outward(bm, [c for c, _ in spheres])
    cornea = _hero_mesh("eye_cornea_hero", old, build_cornea)
    parts = [ball, cornea]

    if lids is not None:
        def outer_r(r, th):
            a, l = bulge_profile(r, hc["cornea_bulge_mm"] * 0.001, cfg["cornea_deg"], hc["film_mm"] * 0.001)(th)
            return math.hypot(a, l)

        def build_meniscus(bm, uvl, dl, gi):
            for (c, r), lm in zip(spheres, lids):
                pts = []
                for j, ph in enumerate(lm.ph):
                    if math.sin(ph) > -0.25:
                        continue
                    k = np.arange(j - 2, j + 3) % len(lm.ph)
                    th = float(np.mean(lm.boundary[k])) - 0.00015 / r
                    pts.append((ph, lm.direction(th, ph) * (outer_r(r, th) + 0.00008)))
                pts.sort(key=lambda t: t[0])
                if len(pts) > 3:
                    _tube(bm, [np.asarray(c) + p for _, p in pts], hc["meniscus_mm"] * 0.001, 8, dl, gi)
        meniscus = _hero_mesh("eye_meniscus_hero", old, build_meniscus)
        parts.append(meniscus)

        def build_caruncle(bm, uvl, dl, gi):
            for side, ((c, r), lm) in enumerate(zip(spheres, lids)):
                c = np.asarray(c)
                # nasal: toward the midline (local x of the eye pair); the inner
                # canthus is the aperture cell furthest that way
                nasal_x = -np.sign(c[0]) if abs(c[0]) > 1e-6 else (-1.0 if side == 0 else 1.0)
                th, ph = lm.canthus((nasal_x, 0.0, 0.0))
                th += math.radians(hc["caruncle_deg"])
                d = lm.direction(th, ph)
                pos = c + d * (r + hc["caruncle_mm"][2] * 0.0005)
                tang_h = np.cross(lm.ez, d)
                tang_h /= np.linalg.norm(tang_h)
                tang_v = np.cross(d, tang_h)
                res = bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=10, radius=1.0)
                M = np.stack([tang_h * hc["caruncle_mm"][0] * 0.001, tang_v * hc["caruncle_mm"][1] * 0.001,
                              d * hc["caruncle_mm"][2] * 0.001], 1)
                for v in res["verts"]:
                    v.co = Vector(pos + M @ np.array(v.co))
                    v[dl][gi] = 1.0
                for f in {f for v in res["verts"] for f in v.link_faces}:
                    f.smooth = True
        caruncle = _hero_mesh("eye_caruncle_hero", old, build_caruncle)
        parts.append(caruncle)

    # materials
    k = hc["occl_mix"]
    alb = data["albedo"] * (1 - k * (1 - data["occl"]))[..., None]
    ia = skin_tex.make_image("eyes_hero_albedo", alb, True)
    m, nt, p = _principled("eyes_hero")
    t = nt.nodes.new("ShaderNodeTexImage")
    t.image = ia
    nt.links.new(t.outputs["Color"], p.inputs["Base Color"])
    # under the cornea (v < limbus) a matte iris with no specular of its own;
    # outside, the wet sclera
    uvn = nt.nodes.new("ShaderNodeUVMap")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(uvn.outputs["UV"], sep.inputs[0])
    vl = math.sqrt(math.radians(cfg["cornea_deg"]) / math.pi)
    for inp, (v_in, v_out) in (("Roughness", (hc["iris_rough"], hc["sclera_rough"])),
                               ("Specular IOR Level", (0.0, hc["sclera_specular"]))):
        mr = nt.nodes.new("ShaderNodeMapRange")
        mr.inputs["From Min"].default_value = vl - 0.004
        mr.inputs["From Max"].default_value = vl + 0.004
        mr.inputs["To Min"].default_value = v_in
        mr.inputs["To Max"].default_value = v_out
        nt.links.new(sep.outputs["Y"], mr.inputs["Value"])
        nt.links.new(mr.outputs["Result"], p.inputs[inp])
    p.subsurface_method = "RANDOM_WALK"
    p.inputs["Subsurface Weight"].default_value = hc["eyeball_sss"]
    p.inputs["Subsurface Radius"].default_value = (1.0, 0.45, 0.3)
    p.inputs["Subsurface Scale"].default_value = 0.0015
    ball.data.materials.append(m)

    m, nt, p = _principled("eye_cornea_hero")
    p.inputs["Base Color"].default_value = (1, 1, 1, 1)
    p.inputs["Transmission Weight"].default_value = 1.0
    p.inputs["IOR"].default_value = hc["cornea_ior"]
    uvn = nt.nodes.new("ShaderNodeUVMap")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(uvn.outputs["UV"], sep.inputs[0])
    mr = nt.nodes.new("ShaderNodeMapRange")
    vc = math.sqrt(math.radians(cfg["cornea_deg"]) / math.pi)
    mr.inputs["From Min"].default_value = vc - 0.01
    mr.inputs["From Max"].default_value = vc + 0.01
    mr.inputs["To Min"].default_value = hc["cornea_rough"]
    mr.inputs["To Max"].default_value = hc["film_rough"]
    nt.links.new(sep.outputs["Y"], mr.inputs["Value"])
    nt.links.new(mr.outputs["Result"], p.inputs["Roughness"])
    _shadow_transparent(nt, p)
    cornea.data.materials.append(m)

    if lids is not None:
        m, nt, p = _principled("eye_meniscus_hero")
        p.inputs["Base Color"].default_value = (1, 1, 1, 1)
        p.inputs["Transmission Weight"].default_value = 1.0
        p.inputs["IOR"].default_value = hc["meniscus_ior"]
        p.inputs["Roughness"].default_value = hc["meniscus_rough"]
        _shadow_transparent(nt, p)
        meniscus.data.materials.append(m)

        m, nt, p = _principled("eye_caruncle_hero")
        p.inputs["Base Color"].default_value = (*skin_tex.srgb_to_linear(skin_tex.HEX(hc["caruncle"])), 1.0)
        p.inputs["Roughness"].default_value = 0.2
        p.subsurface_method = "RANDOM_WALK_SKIN"
        p.inputs["Subsurface Weight"].default_value = 0.6
        p.inputs["Subsurface Radius"].default_value = (1.0, 0.35, 0.25)
        p.inputs["Subsurface Scale"].default_value = 0.0015
        p.inputs["Coat Weight"].default_value = 0.4
        p.inputs["Coat Roughness"].default_value = 0.05
        caruncle.data.materials.append(m)

    for o in parts:
        for cl in list(o.users_collection):
            cl.objects.unlink(o)
        col.objects.link(o)
    old.hide_render = True          # the game eye stays in the .blend (and the GLB), hidden in renders
    notes = {"objects": [o.name for o in parts], "tris": sum(len(o.data.polygons) for o in parts) * 2,
             "cornea_over_iris_mm": round(hc["cornea_bulge_mm"] + (rad[0] * (1 - math.cos(math.radians(cfg["iris_deg"])))) * 1000
                                          + hc["recess_mm"] + hc["film_mm"], 2)}
    b.notes.setdefault("eyes", {})["hero"] = notes
    return notes
