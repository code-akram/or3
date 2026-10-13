"""Hand skin detail (m1 v2 Track G): a texture-space layer on top of Track
A's hand synthesis (skin_synth.synth_hands), baked into the same maps, so the
game hand normal / albedo / ORM and the hero displacement all carry it.

Hook: skin_tex.build calls hand_detail.synth() in place of
skin_synth.synth_hands (one line). synth() runs A's synthesis with A's hand
crease and palm-line terms switched off (this layer draws them anatomically:
HANDOVER below) and adds:

  height (mm, both game normal and hero displacement)
    knuckle folds    dorsal skin folds over every finger joint: curved,
                     irregular, broken folds in an oval field (PIP strongest,
                     DIP finer, MCP loose and wide), the thumb's two joints;
    flexion creases  palm side of each finger joint (double at the PIP), the
                     digital creases at the finger roots, the wrist bracelets;
    palm lines       thenar, proximal and distal transverse creases placed
                     from the hand's own landmarks, plus faint minor lines;
    veins            the dorsal venous network: two wrist trunks, the arch over
                     the metacarpals, metacarpal veins to the finger webs;
                     raised, wandering, partly sunk;
    cuticle          the proximal nail fold as a slight roll of skin.
  albedo
    redder knuckles and fingertips (haemoglobin: G and B down, as Track A's
    chromatic albedo), bluish veins (subtle), a drier, slightly darker cuticle.
  roughness
    folds and creases rougher; knuckle skin a little drier.

All placement is in the hand frame from the rest skeleton
(head_refine.hand_frames); positions are the baked world positions (the rest
pose), so nothing depends on the UV layout.
"""

import numpy as np

from . import skin_synth as ss
from .skin_synth import MM, gauss, polyline, smoothstep

# A's synth_hands terms this layer replaces (set to 0 when calling it).
HANDOVER = {"knuckle_crease_mm": 0.0, "palm_crease_mm": 0.0, "palm_line_mm": 0.0}

DETAIL = {
    "fold_pip_mm": 0.34, "fold_dip_mm": 0.22, "fold_mcp_mm": 0.16, "fold_thumb_mm": 0.26,
    "fold_w_mm": 0.30,
    "flex_crease_mm": 0.30, "digital_crease_mm": 0.22, "wrist_crease_mm": 0.18,
    "palm_line_mm": 0.32, "minor_line_mm": 0.07,
    "vein_mm": 0.45, "vein_w_mm": 1.5, "vein_tint": 0.7,
    "cuticle_mm": 0.08,
    "red_knuckle": 0.85, "red_tip": 1.0, "red_palm": 0.35,
    "rough_fold": 0.06, "rough_knuckle": 0.04,
}


def _tint(alb, w, rgb):
    alb *= (1 + w[..., None] * (np.array(rgb, np.float32) - 1))


class HandFrame:
    """Per-texel coordinates in one hand's frame (rest pose)."""

    def __init__(self, m, f):
        self.f = f
        P, N = m.P, m.N
        self.W, self.F, self.A, self.B = f["wrist"], f["fingers"], f["across"], f["back"]
        d = P - self.W
        self.a = d @ self.F
        self.b = d @ self.A
        self.near = (np.linalg.norm(d, axis=-1) < 0.24) & m.valid
        nb = (N * self.B).sum(-1)
        self.back = np.clip(nb, 0, 1) ** 1.2 * self.near
        self.palm = np.clip(-nb, 0, 1) ** 1.2 * self.near
        # normalised palm coordinates: u along (wrist 0 -> middle MCP 1),
        # v across (index MCP 0 -> pinky MCP 1)
        mm = f["mcp"]
        self.L = float((mm["middle"] - self.W) @ self.F)
        bi = float((mm["index"] - self.W) @ self.A)
        bp = float((mm["pinky"] - self.W) @ self.A)
        self.u = self.a / self.L
        self.v = (self.b - bi) / (bp - bi)
        self.Wd = abs(bp - bi)

    def joint(self, P, j, axis):
        """(along, across, radial) of texels relative to joint j and the
        segment axis."""
        d = P - j
        al = d @ axis
        ac_dir = self.A - axis * float(self.A @ axis)
        ac_dir /= np.linalg.norm(ac_dir)
        ac = d @ ac_dir
        return al, ac


def _folds(m, hf, al, ac, back_w, n, spacing, amp, w, length, width, seed, curve=60.0):
    """Dorsal skin folds over a joint: n curved, broken grooves across the
    finger, in an oval field. Returns (height m, fold mask 0..1)."""
    rng = np.random.default_rng(seed)
    env = gauss(al, length) * gauss(ac, width) * back_w
    h = np.zeros(al.shape, np.float32)
    mask = np.zeros(al.shape, np.float32)
    wob = (m.mot_mid - 0.5) * 2.0
    brk = m.aniso_h
    first = -0.5 * (n - 1) * spacing
    for k in range(n):
        a0 = first + k * spacing * (1 + 0.25 * (rng.random() - 0.5))
        bend = curve * (1 + 0.5 * (rng.random() - 0.5)) * (1 if k % 3 else -0.6)
        tilt = 0.12 * (rng.random() - 0.5)
        line = al - (a0 + bend * ac ** 2 + tilt * ac + 0.00035 * wob)
        # broken: each fold fades in and out across the finger
        keep = smoothstep(0.30, 0.55, brk + 0.25 * np.sin(ac * (900 + 400 * rng.random()) + 6.3 * rng.random()))
        depth = amp * (0.6 + 0.8 * rng.random())
        g = gauss(line, w * (0.8 + 0.4 * rng.random()))
        h -= (depth * (g - 0.35 * gauss(line, 2.6 * w)) * keep * env).astype(np.float32)
        mask = np.maximum(mask, g * keep * env)
    return h, mask


def _chaikin(pts, n=2):
    """Corner-cut a polyline n times (round the joints of the vein paths)."""
    for _ in range(n):
        q = [pts[0]]
        for (a0, b0), (a1, b1) in zip(pts[:-1], pts[1:]):
            q += [(0.75 * a0 + 0.25 * a1, 0.75 * b0 + 0.25 * b1), (0.25 * a0 + 0.75 * a1, 0.25 * b0 + 0.75 * b1)]
        pts = q + [pts[-1]]
    return pts


def synth(m, c, hf, fingers, cfg=None):
    """Track A's hand synthesis (crease terms handed over) plus this layer."""
    d = dict(DETAIL)
    d.update(cfg or {})
    if not d.get("enabled", True):
        return ss.synth_hands(m, c, hf, fingers)
    ca = dict(c)
    ca.update(HANDOVER)
    out = ss.synth_hands(m, ca, hf, fingers)
    layer(m, out, hf, fingers, d)
    return out


def layer(m, out, hf, fingers, d):
    P = m.P
    nails = np.clip(m.nails, 0, 1)
    skin = 1 - smoothstep(0.25, 0.6, nails)
    h = np.zeros(P.shape[:2], np.float32)
    fold_mask = np.zeros_like(h)
    red = np.zeros_like(h)
    vein = np.zeros_like(h)
    cut = np.zeros_like(h)
    w = d["fold_w_mm"] * MM
    for si, (side, f) in enumerate(sorted(hf.items())):
        H = HandFrame(m, f)
        if not H.near.any():
            continue
        seed = 11 + 101 * si
        for fi, name in enumerate(fingers):
            j = [f["mcp"][name], f["pip"][name], f["dip"][name]]
            tip = j[2] + (j[2] - j[1]) * 0.9
            axes = [(j[1] - j[0]), (j[2] - j[1]), (tip - j[2])]
            axes = [x / np.linalg.norm(x) for x in axes]
            # dorsal folds: (joint, distal axis, n, spacing, amp, length, width)
            for ji, (jt, ax, n, sp, amp, ln, wd) in enumerate((
                    (j[0] + H.F * 0.006, axes[0], 3, 0.0024, d["fold_mcp_mm"], 0.0045, 0.0055),
                    (j[1] + axes[1] * 0.0005, axes[1], 5, 0.0016, d["fold_pip_mm"], 0.0042, 0.0042),
                    (j[2] + axes[2] * 0.0003, axes[2], 3, 0.0013, d["fold_dip_mm"], 0.0028, 0.0035))):
                al, ac = H.joint(P, jt, ax)
                bw = np.clip((m.N * (H.B - ax * float(H.B @ ax))).sum(-1) / max(np.linalg.norm(H.B - ax * float(H.B @ ax)), 1e-6), 0, 1) ** 1.5
                close = np.linalg.norm(P - jt, axis=-1) < 0.016      # this finger only
                bw = bw * H.near * close
                hh, mk = _folds(m, hf, al, ac, bw, n, sp, amp * MM, w, ln, wd, seed + 7 * fi + ji)
                h += hh
                fold_mask = np.maximum(fold_mask, mk)
                red += [0.5, 1.0, 0.7][ji] * gauss(al, ln * 1.3) * gauss(ac, wd * 1.2) * bw
                # palm-side flexion creases (double at the PIP, single at the DIP)
                if ji > 0:
                    pw = np.clip(-(m.N * (H.B - ax * float(H.B @ ax))).sum(-1)
                                 / max(np.linalg.norm(H.B - ax * float(H.B @ ax)), 1e-6), 0, 1) ** 1.2 * H.near * close
                    offs = (-0.0012, 0.0006) if ji == 1 else (-0.0010,)
                    for o in offs:
                        line = al - o - 0.00025 * (m.mot_mid - 0.5)
                        h -= (d["flex_crease_mm"] * MM * (gauss(line, 0.00038) - 0.3 * gauss(line, 0.001))
                              * gauss(ac, 0.0062) * pw * (np.abs(al) < 0.01)).astype(np.float32)
            # digital creases at the finger root (palm side), ~40 % up the proximal phalanx
            root = j[0] + (j[1] - j[0]) * 0.42
            al, ac = H.joint(P, root, axes[0])
            pw = H.palm * (np.linalg.norm(P - root, axis=-1) < 0.016)
            for o in (-0.0011, 0.0009):
                line = al - o - 0.0003 * (m.mot_mid - 0.5)
                h -= (d["digital_crease_mm"] * MM * (gauss(line, 0.0004) - 0.3 * gauss(line, 0.0011))
                      * gauss(ac, 0.0075) * pw).astype(np.float32)
            # fingertip redness (pulp and around the nail)
            red += d["red_tip"] / d["red_knuckle"] * np.exp(-0.5 * ((P - tip) ** 2).sum(-1) / 0.009 ** 2) * H.near
            # cuticle: the proximal nail fold, just proximal of the nail plate
            al, ac = H.joint(P, j[2] + axes[2] * 0.004, axes[2])
            band = gauss(nails - 0.22, 0.12) * (al < 0.0) * H.near
            cut = np.maximum(cut, band)
        # thumb: folds over the MCP and IP joints (on the back of the thumb)
        t1, t2, t3 = f["thumb"]
        ttip = t3 + (t3 - t2) * 0.9
        for ji, (jt, nxt) in enumerate(((t2, t3), (t3, ttip))):
            ax = (nxt - jt) / np.linalg.norm(nxt - jt)
            al, ac = H.joint(P, jt, ax)
            # the thumb nail faces away from its pad: use the side opposite the palm-ish pad
            tb = H.B - H.A * 0.6
            tb = tb - ax * float(tb @ ax)
            tb /= np.linalg.norm(tb)
            close = np.linalg.norm(P - jt, axis=-1) < 0.018
            bw = np.clip((m.N * tb).sum(-1), 0, 1) ** 1.5 * H.near * close
            hh, mk = _folds(m, hf, al, ac, bw, 4, 0.0018, d["fold_thumb_mm"] * MM, w, 0.0045, 0.0050, seed + 77 + ji)
            h += hh
            fold_mask = np.maximum(fold_mask, mk)
            red += 0.7 * gauss(al, 0.006) * gauss(ac, 0.006) * bw
            pw = np.clip(-(m.N * tb).sum(-1), 0, 1) ** 1.2 * H.near * close
            line = al + 0.0008 - 0.0003 * (m.mot_mid - 0.5)
            h -= (d["flex_crease_mm"] * MM * gauss(line, 0.0004) * gauss(ac, 0.007) * pw).astype(np.float32)
        red += d["red_tip"] / d["red_knuckle"] * np.exp(-0.5 * ((P - ttip) ** 2).sum(-1) / 0.010 ** 2) * H.near
        al, ac = H.joint(P, t3 + (ttip - t3) * 0.45, (ttip - t3) / np.linalg.norm(ttip - t3))
        cut = np.maximum(cut, gauss(nails - 0.22, 0.12) * (al < 0.0) * H.near)

        # palm lines in normalised palm coordinates (u along, v across)
        u, v = H.u, H.v
        wob = 0.012 * (m.mot_low - 0.5)
        pl = d["palm_line_mm"] * MM
        for pts, amp, wd in (
                ([(0.80, 1.30), (0.83, 0.95), (0.88, 0.55), (0.96, 0.20)], 1.0, 0.0011),   # distal transverse
                ([(0.73, -0.30), (0.71, 0.10), (0.67, 0.55), (0.60, 0.95)], 0.95, 0.0011),  # proximal transverse
                ([(0.72, -0.28), (0.56, -0.02), (0.38, 0.08), (0.20, 0.10), (0.06, 0.05)], 1.0, 0.0012)):  # thenar
            dist, tt = polyline(u + wob, v, pts)
            dm = dist * H.L
            fade = np.sin(np.pi * np.clip(tt, 0, 1)) ** 0.35
            h -= (amp * pl * (gauss(dm, wd * 0.45) - 0.3 * gauss(dm, wd * 1.4)) * fade * H.palm).astype(np.float32)
            fold_mask = np.maximum(fold_mask, gauss(dm, wd * 0.5) * fade * H.palm)
        # minor lines: short broken creases between the main ones
        minor = smoothstep(0.035, 0.0, np.abs(m.aniso_v - 0.5)) * smoothstep(0.45, 0.7, m.broad)
        inpalm = smoothstep(0.05, 0.2, u) * smoothstep(1.0, 0.85, u) * smoothstep(-0.35, -0.1, v) * smoothstep(1.4, 1.15, v)
        h -= (d["minor_line_mm"] * MM * minor * inpalm * H.palm).astype(np.float32)
        # wrist bracelets (palm side)
        for uo, amp in ((-0.03, 1.0), (-0.09, 0.7)):
            line = (u - uo) * H.L + 0.0006 * (m.mot_mid - 0.5)
            h -= (d["wrist_crease_mm"] * amp * MM * gauss(line, 0.0005) * smoothstep(-0.5, -0.2, v)
                  * smoothstep(1.5, 1.2, v) * H.palm).astype(np.float32)
        red += d["red_palm"] / d["red_knuckle"] * H.palm * smoothstep(0.1, 0.4, u) \
            * smoothstep(0.45, 0.65, m.mot_mid)

        # dorsal veins in palm coordinates (mirrored by the across axis);
        # per side jitter so the hands differ
        rng = np.random.default_rng(301 + si)
        jit = lambda p: [(a + 0.03 * (rng.random() - 0.5), b + 0.05 * (rng.random() - 0.5)) for a, b in p]  # noqa: E731
        trunks = [
            (jit([(-0.25, 1.05), (0.05, 0.95), (0.28, 0.80), (0.45, 0.62)]), 1.0),        # basilic side
            (jit([(-0.25, -0.20), (0.05, -0.10), (0.25, 0.05), (0.42, 0.25)]), 0.9),      # cephalic side
            (jit([(0.45, 0.62), (0.50, 0.42), (0.42, 0.25)]), 0.85),                      # arch
            (jit([(0.45, 0.62), (0.62, 0.70), (0.80, 0.78)]), 0.7),                       # to the ring/middle web
            (jit([(0.42, 0.25), (0.60, 0.30), (0.79, 0.35)]), 0.65),                      # to the middle/index web
            (jit([(0.28, 0.80), (0.52, 0.98), (0.76, 1.08)]), 0.6),                       # to the ring/pinky web
            (jit([(0.25, 0.05), (0.40, -0.18), (0.55, -0.35)]), 0.5),                      # toward the thumb web
        ]
        vw = d["vein_w_mm"] * MM
        sunk = smoothstep(0.35, 0.6, m.vein_var)          # where a vein dives under
        for pts, amp in trunks:
            dist, tt = polyline(H.u + 0.010 * (m.mot_low - 0.5), H.v + 0.02 * (m.broad - 0.5), _chaikin(pts))
            dm = dist * H.L
            prof = gauss(dm, vw) * (0.45 + 0.55 * sunk) * np.sin(np.pi * np.clip(0.08 + 0.84 * tt, 0, 1)) ** 0.3
            vein = np.maximum(vein, amp * prof * H.back * smoothstep(0.84, 0.70, H.u))
    vein *= skin
    h += (d["vein_mm"] * MM * vein).astype(np.float32)
    h += (d["cuticle_mm"] * MM * cut * skin).astype(np.float32)
    h *= (0.3 + 0.7 * skin)

    out["hgt_hero"] = (out["hgt_hero"] + h).astype(np.float32)
    out["hgt_game"] = (out["hgt_game"] + h).astype(np.float32)
    alb = out["albedo"]
    hb = np.clip(red * d["red_knuckle"], 0, 1.4) * skin
    # haemoglobin (Track A's chromatic model: G and B drop, R nearly holds)
    alb *= (1 - (0.8 * hb)[..., None] * np.array((0.02, 0.10, 0.12), np.float32))
    _tint(alb, np.clip(vein * d["vein_tint"], 0, 1), (0.93, 0.96, 1.03))
    _tint(alb, cut * skin * 0.6, (0.92, 0.88, 0.87))
    out["albedo"] = np.clip(alb, 0, 1)
    out["rough"] = np.clip(out["rough"] + d["rough_fold"] * fold_mask * skin + d["rough_knuckle"] * np.clip(red, 0, 1) * 0.5
                           + 0.05 * cut, 0.05, 1.0)
    return out
