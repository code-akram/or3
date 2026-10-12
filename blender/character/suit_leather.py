"""Leather surfaces for the shoes (suit_shoes.py), drawn into the leather atlas
that suit_textures packs:

    normal    a faint calf grain and a slow waviness (replacing the generic
              leather noise), vamp flex creases (soft folds, tapered ends), shoe
              edges with fine 2.2 mm stitching ("sedge"), punched blind eyelets,
              welt wheeling, the welt/sole junction, stacked heel lifts, the lace
              twist; seams and plain topstitches are drawn by suit_textures
    albedo    per-region linear albedo with a painterly mottle (value noise through
              a Kuwahara filter, r 1-2 px; art direction §4: albedo only), creases
              a little greyer (cracked polish), a dark welt/upper junction
    CRM       one data texture: R clear-coat weight (cap 0.9, quarters 0.45,
              creases halved), G roughness (polished cap 0.18 with a mirror spot,
              vamp and quarters 0.28, creases rougher, sole edge dressed, bottom
              rough), B metallic 0. Coat roughness 0.08 (KHR_materials_clearcoat);
              the coat has no normal map, so its highlight is smooth over the
              grain (wax fills it)

Surfaces(H, layout, marks, side, opts) runs before suit_textures draws the
generic marks; wire(material, sole_material) after the atlas UVs are written.
"""
import math
from math import tau as TAU

import bpy
import numpy as np

from . import suit_shoes

TAGNAME = {v: k for k, v in suit_shoes.TAG.items()}


def _srgb(x):
    x = np.clip(x, 0.0, 1.0)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - 0.055)


def _value_noise(rng, px, cell):
    n = rng.normal(0.0, 1.0, (px // cell + 2, px // cell + 2)).astype(np.float32)
    n = np.kron(n, np.ones((cell, cell), np.float32))[:px, :px]
    for _ in range(max(1, cell // 2)):
        n = (n + np.roll(n, 1, 0) + np.roll(n, -1, 0) + np.roll(n, 1, 1) + np.roll(n, -1, 1)) / 5
    return (n - n.mean()) / (n.std() + 1e-9)


def kuwahara(img, r):
    """Kuwahara filter (4 quadrants of (r+1)^2 px, the mean of the least varied):
    flattens the mottle into painted value blocks with crisp edges."""
    if r <= 0:
        return img
    p = np.pad(img, r + 1, mode="wrap").astype(np.float64)
    S = p.cumsum(0).cumsum(1)
    S2 = (p * p).cumsum(0).cumsum(1)
    h, w = img.shape
    k = r + 1

    def box(T, dy, dx):
        y0, x0 = r + 1 + dy - 1, r + 1 + dx - 1
        a = T[y0 + k:y0 + k + h, x0 + k:x0 + k + w]
        b = T[y0:y0 + h, x0 + k:x0 + k + w]
        c = T[y0 + k:y0 + k + h, x0:x0 + w]
        d = T[y0:y0 + h, x0:x0 + w]
        return (a - b - c + d) / (k * k)
    best_m = best_v = None
    for dy, dx in ((-r, -r), (-r, 0), (0, -r), (0, 0)):
        m = box(S, dy, dx)
        v = box(S2, dy, dx) - m * m
        if best_m is None:
            best_m, best_v = m, v
        else:
            sel = v < best_v
            best_m = np.where(sel, m, best_m)
            best_v = np.where(sel, v, best_v)
    return best_m.astype(np.float32)


class Surfaces:
    def __init__(self, H, layout, marks, side, opts):
        self.S = opts["shoes"]["surface"]
        self.H, self.layout, self.side = H, layout, side
        self.px, self.ppm = H.px, H.ppm
        self.rng = np.random.default_rng(self.S["seed"])
        px = self.px
        # the calf grain: polished calf is nearly smooth; anything at pixel scale
        # glitters under the sharp highlights once minified (the generic leather
        # noise read as hammered metal under the clear coat)
        H.h[:] = 0.0
        H.h += (0.0000025 * _value_noise(self.rng, px, 3)).astype(np.float32)
        H.h += (0.0000080 * _value_noise(self.rng, px, 24)).astype(np.float32)   # a soft waviness
        self.crease = np.zeros((px, px), np.float32)
        self.holes = []
        self.regions = {}
        for (obj, tag), L in layout.items():
            self.regions.setdefault(TAGNAME.get(tag, "upper"), []).append(self._rect(L))
        for key, lst in marks.items():
            L = layout.get(key)
            if L is None:
                continue
            for mark in lst:
                kind = mark[0]
                if kind == "flex":
                    self.flex(L, mark[1], mark[2], mark[3])
                elif kind == "sedge":
                    self.sedge([self._T(L, p) for p in mark[1]], **mark[2])
                elif kind == "wheel":
                    self.wheel(L, mark[1], mark[2], mark[3])
                elif kind == "groove":
                    pts = [self._T(L, p) for p in mark[1]]
                    H.line(pts, H.groove(0.00022, 0.0009), 0.0014)
                elif kind == "lifts":
                    self.lifts(L, mark[1], mark[2], mark[3])
                elif kind == "eyelet":
                    self.holes.append((self._T(L, mark[1]), mark[2]))
                    H.spot(self.holes[-1][0], mark[2] * 0.7, -0.0006)
                    self._ring(self.holes[-1][0], mark[2] * 0.9, H.ridge(0.00012, 0.0006))
                elif kind == "twist":
                    self.twist(L)

    # --- helpers ---------------------------------------------------------------------------

    def _T(self, L, uv):
        return (L["x0"] + uv[0] - L["umin"], L["y0"] + uv[1] - L["vmin"])

    def _rect(self, L):
        p = self.ppm
        x0, y0 = int(L["x0"] * p), int(L["y0"] * p)
        x1, y1 = int(math.ceil((L["x0"] + L["w"]) * p)) + 1, int(math.ceil((L["y0"] + L["h"]) * p)) + 1
        # a margin of a few pixels: bilinear filtering and mips read past the panel edge
        m = 3
        return (max(0, x0 - m), max(0, y0 - m), min(self.px, x1 + m), min(self.px, y1 + m), L)

    def _polyline(self, arr, pts_m, prof, r_m):
        """arr += prof(d, s) along a polyline (metres in atlas space), d the signed
        distance across (m), s the global arc fraction 0..1."""
        pts = [(u * self.ppm, v * self.ppm) for u, v in pts_m]
        segs = list(zip(pts, pts[1:]))
        lens = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in segs]
        total = sum(lens) or 1.0
        acc = 0.0
        r = r_m * self.ppm
        for (a, b), Lg in zip(segs, lens):
            if Lg < 1e-6:
                continue
            tx, ty = (b[0] - a[0]) / Lg, (b[1] - a[1]) / Lg
            x0, x1 = int(max(0, min(a[0], b[0]) - r - 2)), int(min(self.px - 1, max(a[0], b[0]) + r + 2)) + 1
            y0, y1 = int(max(0, min(a[1], b[1]) - r - 2)), int(min(self.px - 1, max(a[1], b[1]) + r + 2)) + 1
            if x1 <= x0 or y1 <= y0:
                acc += Lg
                continue
            Y, X = np.mgrid[y0:y1, x0:x1].astype(np.float32)
            dx, dy = X - a[0], Y - a[1]
            t = dx * tx + dy * ty
            d = (dx * -ty + dy * tx) / self.ppm
            inside = (t >= 0) & (t <= Lg)
            s = (acc + np.clip(t, 0, Lg)) / total
            arr[y0:y1, x0:x1] += (prof(d, s) * inside).astype(np.float32)
            acc += Lg

    # --- marks -----------------------------------------------------------------------------

    def flex(self, L, pts, depth, w):
        """A vamp flex crease: a soft fold (groove between two low puffs), wavy in
        depth along its length, tapered ends."""
        pts_m = [self._T(L, p) for p in pts]
        ph = float(self.rng.uniform(0, 6.28))

        def taper(s):
            return np.clip(np.minimum(s, 1 - s) / 0.3, 0, 1) ** 1.6 * (0.75 + 0.25 * np.sin(9 * s + ph))

        def prof(d, s):
            g = -np.exp(-(d / w) ** 2) + 0.45 * np.exp(-((np.abs(d) - 1.8 * w) / (1.2 * w)) ** 2)
            return depth * taper(s) * g

        def mask(d, s):
            return taper(s) * np.exp(-(d / (1.5 * w)) ** 2)
        self._polyline(self.H.h, pts_m, prof, 4.5 * w)
        self._polyline(self.crease, pts_m, mask, 4.5 * w)

    def sedge(self, pts, inside_sign=1.0, lip_m=0.0008, height=0.00025, stitch_in_m=0.0018, rows=1):
        """A shoe edge: a skived, turned edge (a low rounded ridge) with fine
        stitching, 2.2 mm pitch, one or two rows."""
        H = self.H
        H.line(pts, H.ridge(height, lip_m * 2), lip_m * 2, offset_m=inside_sign * lip_m * 0.5)
        H.line(pts, H.groove(height * 0.6, lip_m), lip_m * 1.5, offset_m=-inside_sign * lip_m * 0.6)
        for r in range(rows):
            H.stitch(pts, pitch_m=0.0022, offset_m=inside_sign * (stitch_in_m + r * 0.0018),
                     thread_m=0.0005, height=0.0002)

    def wheel(self, L, pts, pitch, width):
        """Welt wheeling: short transverse notches along the welt top."""
        H = self.H
        u0, u1 = pts[0][0], pts[-1][0]
        v = pts[0][1]
        n = int(abs(u1 - u0) / pitch)
        prof = H.groove(0.00012, 0.0005)
        for i in range(n):
            u = u0 + (u1 - u0) * (i + 0.5) / n
            H.line([self._T(L, (u, v - width * 0.5)), self._T(L, (u + 0.0004, v + width * 0.5))], prof, 0.0008)

    def lifts(self, L, pts, v_a, v_b):
        """Stacked heel lifts: thin grooves between the sole and the top lift."""
        H = self.H
        u0, u1 = pts[0][0], pts[-1][0]
        prof = H.groove(0.00015, 0.0006)
        v = v_a + 0.0035
        while v < v_b - 0.001:
            H.line([self._T(L, (u0, v)), self._T(L, (u1, v))], prof, 0.001)
            v += 0.0035
        H.line([self._T(L, (u0, pts[0][1])), self._T(L, (u1, pts[0][1]))], H.groove(0.0003, 0.0008), 0.0012)

    def _ring(self, at, r_m, prof, n=12):
        pts = [(at[0] + r_m * math.cos(TAU * i / n), at[1] + r_m * math.sin(TAU * i / n)) for i in range(n + 1)]
        self.H.line(pts, prof, 0.0008)

    def twist(self, L):
        """Round waxed lace: diagonal twist ridges over the lace panel."""
        x0, y0, x1, y1, _ = self._rect(L)
        Y, X = np.mgrid[y0:y1, x0:x1].astype(np.float32) / self.ppm
        per = 0.0012
        self.H.h[y0:y1, x0:x1] += (0.00008 * np.sin(2 * np.pi * (X + Y) / per)).astype(np.float32)

    # --- maps ------------------------------------------------------------------------------

    def _fill(self, base_of):
        out = np.zeros((self.px, self.px), np.float32)
        default = base_of("upper")
        out[:] = default
        for name, rects in self.regions.items():
            val = base_of(name)
            for (x0, y0, x1, y1, _) in rects:
                out[y0:y1, x0:x1] = val
        return out

    def maps(self):
        S = self.S
        px = self.px
        alb = self._fill(lambda n: S["albedo"].get(n, S["albedo"]["upper"]))
        rough = self._fill(lambda n: S["rough"].get(n, S["rough"]["upper"]))
        coat = self._fill(lambda n: S["coat"].get(n, 0.0))
        crease = np.clip(self.crease, 0, 1)
        # painterly mottle on the albedo: two scales, through the Kuwahara filter
        mott = 0.65 * _value_noise(self.rng, px, 6) + 0.35 * _value_noise(self.rng, px, 24)
        mott = kuwahara(mott, int(S["paint_r"]))
        alb = alb * (1.0 + S["paint_amp"] * np.clip(mott, -2.5, 2.5) * 0.5)
        alb = alb * (1.0 + (S["crease_albedo"] - 1.0) * crease)
        # gloss varies slowly over a polished upper (wax worked in by hand), no pixel noise
        rough = rough + S["crease_rough"] * crease + 0.02 * _value_noise(self.rng, px, 32)
        coat = coat * (1.0 - 0.5 * crease)
        # the polished cap: a mirror spot over the top of the cap
        for (x0, y0, x1, y1, L) in self.regions.get("cap", []):
            Y, X = np.mgrid[y0:y1, x0:x1].astype(np.float32) / self.ppm
            u = X - L["x0"] + L["umin"]
            v = Y - L["y0"] + L["vmin"]
            vc = L["vmin"] + 0.4 * L["h"]
            g = np.exp(-(u / 0.028) ** 2 - ((v - vc) / 0.03) ** 2)
            rough[y0:y1, x0:x1] -= S["cap_polish"] * g
            coat[y0:y1, x0:x1] = np.minimum(1.0, coat[y0:y1, x0:x1] + 0.1 * g)
        # the welt meets the upper: a dark line in the corner; welt top a little rougher
        for name in ("sole", "sole_m"):
            for (x0, y0, x1, y1, L) in self.regions.get(name, []):
                Y = np.mgrid[y0:y1, x0:x1][0].astype(np.float32) / self.ppm
                v = Y - L["y0"] + L["vmin"]
                alb[y0:y1, x0:x1] *= (1.0 - 0.45 * np.exp(-(v / 0.0007) ** 2))
                rough[y0:y1, x0:x1] += 0.08 * ((v > 0.0005) & (v < 0.0045))
        # the punched eyelet holes: dark, matt, no coat
        for (u, v), r in self.holes:
            x, y, rp = u * self.ppm, v * self.ppm, r * self.ppm
            x0, x1 = int(max(0, x - 2 * rp)), int(min(px, x + 2 * rp + 1))
            y0, y1 = int(max(0, y - 2 * rp)), int(min(px, y + 2 * rp + 1))
            Y, X = np.mgrid[y0:y1, x0:x1].astype(np.float32)
            g = np.clip(1.5 - np.hypot(X - x, Y - y) / (0.5 * rp), 0, 1)
            alb[y0:y1, x0:x1] = alb[y0:y1, x0:x1] * (1 - g) + 0.002 * g
            rough[y0:y1, x0:x1] = rough[y0:y1, x0:x1] * (1 - g) + 0.7 * g
            coat[y0:y1, x0:x1] *= 1 - g
        rough = np.clip(rough, 0.05, 1.0)
        coat = np.clip(coat, 0.0, 1.0)
        return alb, rough, coat

    def wire(self, mat, sole_mat, name="suit_leather"):
        alb, rough, coat = self.maps()
        px = self.px
        a_img = _image(f"{name}_albedo", np.repeat(_srgb(alb)[..., None], 3, axis=2), "sRGB")
        # one data texture: R clear-coat weight (no occlusion map uses it), G roughness,
        # B metallic 0
        crm = np.stack([coat, rough, np.zeros_like(rough)], axis=-1)
        r_img = _image(f"{name}_crm", crm, "Non-Color")
        for m, with_coat in ((mat, True), (sole_mat, False)):
            if m is None:
                continue
            _wire(m, a_img, r_img, with_coat, self.S["coat_rough"])
        return {"albedo_mean_cap": round(float(_mean_in(alb, self.regions.get("cap"))), 4),
                "rough_cap": round(float(_mean_in(rough, self.regions.get("cap"))), 3),
                "rough_upper": round(float(_mean_in(rough, self.regions.get("upper"))), 3),
                "coat_cap": round(float(_mean_in(coat, self.regions.get("cap"))), 3),
                "coat_upper": round(float(_mean_in(coat, self.regions.get("upper"))), 3),
                "crease_px": int((self.crease > 0.3).sum()), "px": px}


def _mean_in(arr, rects):
    if not rects:
        return float("nan")
    vals = [arr[y0:y1, x0:x1].ravel() for (x0, y0, x1, y1, _) in rects]
    return np.concatenate(vals).mean()


def _image(name, rgb, colorspace):
    px = rgb.shape[0]
    img = bpy.data.images.new(name, px, px, alpha=False, float_buffer=False)
    img.colorspace_settings.name = colorspace
    rgba = np.ones((px, px, 4), np.float32)
    rgba[..., :3] = rgb
    img.pixels.foreach_set(rgba.ravel())
    img.pack()
    return img


def _wire(mat, a_img, r_img, coat, coat_rough):
    """glTF-exportable wiring: base colour texture; metallicRoughness (G, B) and the
    clear-coat weight (R, KHR_materials_clearcoat) from one texture through one
    Separate Color node; a constant coat roughness."""
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")

    def tex(img):
        t = nt.nodes.new("ShaderNodeTexImage")
        t.image = img
        t.interpolation = "Linear"
        return t
    ta = tex(a_img)
    nt.links.new(ta.outputs["Color"], bsdf.inputs["Base Color"])
    tr = tex(r_img)
    sep = nt.nodes.new("ShaderNodeSeparateColor")
    nt.links.new(tr.outputs["Color"], sep.inputs["Color"])
    nt.links.new(sep.outputs["Green"], bsdf.inputs["Roughness"])
    nt.links.new(sep.outputs["Blue"], bsdf.inputs["Metallic"])
    if coat and "Coat Weight" in bsdf.inputs:
        nt.links.new(sep.outputs["Red"], bsdf.inputs["Coat Weight"])
        bsdf.inputs["Coat Roughness"].default_value = coat_rough
        bsdf.inputs["Coat IOR"].default_value = 1.5
