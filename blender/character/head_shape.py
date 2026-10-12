"""Parametric face edits on the MPFB base mesh (bench/m1/look-spec.md §2.3).

Every control is a scalar in [-1, 1] that drives a smooth, mirrored
displacement field over a face region; then a planarisation pass pulls each
plane group (§2.1) toward its least-squares plane. The result is written as
one shape key ("head_edits", value 1) on the live human before any proxy is
fitted, so eyes, brows, lashes, hair and clothes follow the edited head and
export.bake_targets bakes it with the macro targets.

Regions are soft masks in a face frame built from the eye helper geometry
(stable across macros): origin = midpoint of the two eye-helper centroids,
u = |x| (lateral), h = up, f = forward (-Y), all scaled by the
interpupillary distance relative to the default build (61.6 mm). Masks are
anisotropic Gaussians (centre, radii in metres at the reference scale).
Mirroring is exact: fields use |x| and flip the x component by side.

The face is defined only by these parameters (look-spec §2.4 rule 3).
"""

import math

import bpy
import numpy as np

REF_IPD = 0.0616  # eye-helper centroid distance on the default build

# name: (u, h, f) centre and (ru, rh, rf) radii, metres at REF_IPD.
REGIONS = {
    "brow":       ((0.030, 0.020, 0.020), (0.022, 0.008, 0.020)),
    "socket":     ((0.031, 0.002, 0.010), (0.016, 0.011, 0.020)),
    "lid":        ((0.031, 0.010, 0.016), (0.012, 0.0035, 0.010)),
    "nose":       ((0.000, -0.030, 0.035), (0.012, 0.025, 0.030)),
    "bridge":     ((0.008, -0.015, 0.030), (0.008, 0.012, 0.020)),
    "malar":      ((0.048, -0.018, 0.000), (0.016, 0.012, 0.020)),
    "submalar":   ((0.045, -0.050, -0.005), (0.014, 0.013, 0.020)),
    "gonial":     ((0.056, -0.092, -0.042), (0.016, 0.022, 0.030)),
    "chin":       ((0.000, -0.112, 0.020), (0.020, 0.014, 0.020)),
    "forehead":   ((0.025, 0.070, 0.005), (0.035, 0.030, 0.030)),
}

# Plane groups for the planarisation pass: (centre, radii, midline?).
# Midline groups fit one plane symmetric about x = 0; lateral groups fit
# the left side and mirror it.
PLANES = {
    "forehead":    ((0.028, 0.065, 0.008), (0.026, 0.022, 0.025), False),
    "brow_front":  ((0.030, 0.022, 0.022), (0.020, 0.006, 0.012), False),
    "brow_under":  ((0.031, 0.014, 0.015), (0.015, 0.0045, 0.010), False),
    "nose_dorsum": ((0.000, -0.020, 0.035), (0.006, 0.020, 0.020), True),
    "nose_side":   ((0.012, -0.025, 0.025), (0.006, 0.015, 0.014), False),
    "malar":       ((0.050, -0.022, 0.000), (0.016, 0.012, 0.016), False),
    "submalar":    ((0.046, -0.052, -0.006), (0.015, 0.014, 0.016), False),
    "jaw_side":    ((0.055, -0.085, -0.035), (0.013, 0.020, 0.022), False),
    "chin_front":  ((0.000, -0.110, 0.022), (0.016, 0.011, 0.013), True),
}

CONTROLS = (
    "brow_depth", "brow_angle", "brow_flatten", "socket_depth", "lid_hood",
    "nose_length", "nose_bridge_width", "dorsum_crease", "cheek_height",
    "cheek_plane_break", "submalar_hollow", "jaw_width", "jaw_angle",
    "chin_width", "chin_projection", "lip_thickness", "forehead_slope",
)

# Full-scale amplitude per control (mm, or degrees for the two angle
# controls). Widened about 2x over look-spec §2.3 on 2026-10-12: at the spec
# ranges every variant stayed within ~7 mm of the stock head and the three
# variants were indistinguishable from it in the face strips (bench/m1/head.md
# "Bolder pass").
RANGES = {
    "brow_depth": 14.0, "brow_angle": 10.0, "socket_depth": 7.0, "lid_hood": 3.5,
    "nose_length": 8.0, "nose_bridge_width": 3.5, "cheek_height": 7.0,
    "submalar_hollow": 9.0, "jaw_width": 11.0, "jaw_angle": 10.0, "chin_width": 8.0,
    "chin_projection": 8.0, "lip_thickness": 3.0, "forehead_slope": 8.0,
}

# Controls that act through the planarisation pass: control -> plane groups.
PLANE_CONTROLS = {
    "brow_flatten": ("brow_front", "brow_under"),
    "dorsum_crease": ("nose_dorsum", "nose_side"),
    "cheek_plane_break": ("malar", "submalar"),
}


def _mix_coords(obj):
    """Object-space coords of the current shape-key mix, one per vertex."""
    kb = obj.data.shape_keys.key_blocks if obj.data.shape_keys else None
    n = len(obj.data.vertices)
    out = np.empty(n * 3, dtype=np.float64)
    if not kb:
        obj.data.vertices.foreach_get("co", out)
        return out.reshape(n, 3)
    basis = np.empty(n * 3, dtype=np.float64)
    kb[0].data.foreach_get("co", basis)
    out[:] = basis
    tmp = np.empty(n * 3, dtype=np.float64)
    for k in list(kb)[1:]:
        if k.mute or k.value == 0.0:
            continue
        k.data.foreach_get("co", tmp)
        out += k.value * (tmp - basis)
    return out.reshape(n, 3)


def _group_weights(obj, name):
    w = np.zeros(len(obj.data.vertices))
    g = obj.vertex_groups.get(name)
    if g is None:
        return w
    gi = g.index
    for v in obj.data.vertices:
        for vg in v.groups:
            if vg.group == gi:
                w[v.index] = vg.weight
    return w


class Frame:
    """Face frame from the two eye centres; local coords for every point.

    Frame(co, cl, cr): co (n, 3) points, cl / cr the left / right eye centres
    (same space). Frame.from_helpers(obj, co) reads the centres from the MPFB
    eye-helper groups on the live base mesh; after staging (helpers gone) use
    the fitted eye mesh centroids instead (head_refine)."""

    def __init__(self, co, cl, cr):
        cl, cr = np.asarray(cl, dtype=np.float64), np.asarray(cr, dtype=np.float64)
        self.origin = (cl + cr) * 0.5
        self.ipd = float(np.linalg.norm(cl - cr))
        self.s = self.ipd / REF_IPD
        d = co - self.origin
        self.side = np.where(d[:, 0] >= 0, 1.0, -1.0)
        self.u = np.abs(d[:, 0]) / self.s
        self.h = d[:, 2] / self.s
        self.f = -d[:, 1] / self.s
        self.x = d[:, 0] / self.s

    @classmethod
    def from_helpers(cls, obj, co):
        le = _group_weights(obj, "helper-l-eye") > 0
        re = _group_weights(obj, "helper-r-eye") > 0
        return cls(co, co[le].mean(0), co[re].mean(0))

    def mask(self, centre, radii, flat=False, sharp=2.0):
        """Anisotropic Gaussian; flat=True gives a plateau with a quick edge
        (exp(-q^sharp/2), q the squared normalised radius; sharp 2 = exp(-r^4/2)),
        so a plane group moves as one facet. Higher sharp = crisper edge."""
        (cu, ch, cf), (ru, rh, rf) = centre, radii
        q = ((self.u - cu) / ru) ** 2 + ((self.h - ch) / rh) ** 2 + ((self.f - cf) / rf) ** 2
        return np.exp(-0.5 * q ** sharp) if flat else np.exp(-0.5 * q)

    def region(self, name):
        return self.mask(*REGIONS[name])


def displacement(fr, ctl, lips_w):
    """Sum of the control fields, in metres (object space, before scaling by s)."""
    n = len(fr.u)
    d = np.zeros((n, 3))
    X, Y, Z = 0, 1, 2
    mm = 0.001
    v = lambda k: float(ctl.get(k, 0.0))  # noqa: E731
    sx = np.tanh(fr.x / 0.004)  # signed, smooth through the midline

    # The shelf ends at the temple: fade the projection out past the orbit's
    # outer rim, or the brow end sticks out of the ¾ silhouette.
    w = fr.region("brow") * np.clip((0.058 - fr.u) / 0.016, 0.0, 1.0)
    d[:, Y] -= v("brow_depth") * RANGES["brow_depth"] * mm * w                       # forward = -Y
    d[:, Z] += v("brow_angle") * math.tan(math.radians(RANGES["brow_angle"])) * (fr.u - 0.025) * w
    w = fr.region("socket")
    d[:, Y] += v("socket_depth") * RANGES["socket_depth"] * mm * w                     # recess = +Y
    w = fr.region("lid")
    d[:, Z] -= v("lid_hood") * RANGES["lid_hood"] * mm * w
    w = fr.region("nose")
    t = np.clip(-fr.h / 0.045, 0.0, 1.0)
    d[:, Z] -= v("nose_length") * RANGES["nose_length"] * mm * w * t
    w = fr.region("bridge")
    d[:, X] += v("nose_bridge_width") * RANGES["nose_bridge_width"] * mm * w * sx
    w = fr.region("malar")
    d[:, Z] += v("cheek_height") * RANGES["cheek_height"] * mm * w
    w = fr.region("submalar")
    k = v("submalar_hollow") * RANGES["submalar_hollow"] * mm * w
    d[:, X] -= k * 0.45 * fr.side
    d[:, Y] += k * 0.89
    w = fr.region("gonial")
    d[:, X] += v("jaw_width") * RANGES["jaw_width"] * mm * w * fr.side
    k = v("jaw_angle") * RANGES["jaw_angle"] * mm * w
    d[:, Y] += k * 0.707
    d[:, Z] += k * 0.707
    w = fr.region("chin")
    d[:, X] += v("chin_width") * RANGES["chin_width"] * mm * w * np.tanh(fr.x / 0.006)
    d[:, Y] -= v("chin_projection") * RANGES["chin_projection"] * mm * w
    d[:, Y] -= v("lip_thickness") * RANGES["lip_thickness"] * mm * lips_w
    w = fr.region("forehead") * (fr.h > 0.03)
    d[:, Y] += v("forehead_slope") * math.tan(math.radians(RANGES["forehead_slope"])) * np.clip(fr.h - 0.035, 0, None) * w
    return d * fr.s


def planarise(fr, co, blends, exclude, sharp=2.0):
    """Pull each plane group toward its weighted least-squares plane.
    blends: {group: 0..1}. exclude: bool mask of vertices never moved.
    sharp: plateau edge sharpness of the group masks (Frame.mask)."""
    out = co.copy()
    for name, blend in blends.items():
        if not blend:
            continue
        centre, radii, midline = PLANES[name]
        w = fr.mask(centre, radii, flat=True, sharp=sharp)
        w[exclude] = 0.0
        sides = (1.0,) if midline else (1.0, -1.0)
        for side in sides:
            sel = (w > 0.05) & ((fr.side == side) | midline)
            if sel.sum() < 6:
                continue
            p, ww = co[sel], w[sel]
            if midline:  # symmetric fit: add the mirror image
                pm = p.copy()
                pm[:, 0] = 2 * fr.origin[0] - pm[:, 0]
                p, ww = np.vstack([p, pm]), np.concatenate([ww, ww])
            c = (p * ww[:, None]).sum(0) / ww.sum()
            q = (p - c) * np.sqrt(ww)[:, None]
            nrm = np.linalg.svd(q, full_matrices=False)[2][-1]
            idx = np.nonzero(sel)[0]
            dist = (co[idx] - c) @ nrm
            out[idx] -= (blend * w[idx] * dist)[:, None] * nrm[None, :]
    return out


def apply(b):
    """head.edit_base hook: build the 'head_edits' shape key on b.basemesh."""
    cfg = b.cfg["head"]
    ctl = dict(cfg.get("edits") or {})
    unknown = sorted(set(ctl) - set(CONTROLS))
    if unknown:
        raise ValueError(f"unknown head edit controls: {unknown}")
    planes = dict(cfg.get("planes") or {})
    for c, groups in PLANE_CONTROLS.items():
        if ctl.get(c):
            for g in groups:
                planes[g] = max(planes.get(g, 0.0), float(ctl[c]))
    unknown = sorted(set(planes) - set(PLANES))
    if unknown:
        raise ValueError(f"unknown plane groups: {unknown}")
    if not any(ctl.values()) and not any(planes.values()):
        return None

    obj = b.basemesh
    co = _mix_coords(obj)
    fr = Frame.from_helpers(obj, co)
    disp = displacement(fr, ctl, _group_weights(obj, "lips"))
    edited = co + disp
    # Never planarise helpers (proxies fit to them) or the eyelids.
    helpers = _group_weights(obj, "HelperGeometry") > 0
    eye_c = [co[_group_weights(obj, g) > 0].mean(0) for g in ("helper-l-eye", "helper-r-eye")]
    near_eye = np.minimum(*(np.linalg.norm(co - c, axis=1) for c in eye_c)) < 0.020 * fr.s
    edited = planarise(fr, edited, planes, helpers | near_eye)

    kb = obj.data.shape_keys.key_blocks
    basis = np.empty(len(co) * 3)
    kb[0].data.foreach_get("co", basis)
    key = obj.shape_key_add(name="head_edits", from_mix=False)
    key.data.foreach_set("co", (basis.reshape(-1, 3) + (edited - co)).ravel())
    key.value = 1.0
    obj.data.update()
    moved = np.linalg.norm(edited - co, axis=1)
    b.notes["head_edits"] = {"controls": ctl, "planes": planes, "ipd_m": round(fr.ipd, 4),
                             "max_move_mm": round(float(moved.max()) * 1000, 2),
                             "verts_moved_over_0.1mm": int((moved > 1e-4).sum())}
    return moved
