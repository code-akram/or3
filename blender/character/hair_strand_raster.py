"""Strand rasteriser and texture packing shared by the game hair and facial-hair
card bakers (hair_groom_cards, beard_bake). Track T9 (bench/m1/v4/t9-cards.md).

A card texture is a set of strands drawn in the card's own frame (u across the
card, v root -> tip), supersampled, painter-ordered by depth (front-most last)
and box-filtered down. Per texel it carries what the runtime hair shader reads:

  albedo  RGB  per-strand colour (from the strand's melanin / redness, the same
               numbers the hero Principled Hair BSDF renders), A coverage with
               an alpha gradient over each strand's tip
  aniso   RG   flow: the strand tangent in UV space (0.5 + 0.5 x), B 1 (the
               KHR_materials_anisotropy strength), A depth across the card
               (0 back .. 1 front)
  orm     R    occlusion (root darkening x depth), G roughness (base + per-strand
               jitter), B strand ID (metallicFactor 0 in the GLB, so standard
               viewers ignore it), A root-to-tip (0 root .. 1 tip)

The GLB carries albedo as baseColorTexture, aniso as the KHR_materials_anisotropy
texture and orm as occlusion + metallicRoughness (export.pack_hair_maps), so the
KTX2 copy compresses all of them and no sidecar is needed.
"""

import math
import struct
import zlib

import bpy
import numpy as np

# Cycles' Principled Hair (Chiang): melanin -> absorption, and the colour <-> absorption
# mapping of the "Direct Coloring" parametrisation (Chiang et al. 2016, eq. 9), inverted:
# the colour a fibre assembly of that absorption shows (its multiple-scattering albedo).
EUMELANIN = np.array([0.506, 0.841, 1.653])
PHEOMELANIN = np.array([0.343, 0.733, 1.924])


def chiang_color(melanin, redness, radial_roughness, path=1.0):
    """Linear RGB (n, 3) for per-strand melanin / redness. `path` scales the
    absorption (1 = Chiang's mapping; < 1 lighter)."""
    mel = np.clip(np.asarray(melanin, dtype=np.float64), 0.0, 0.9999)
    red = np.clip(np.asarray(redness, dtype=np.float64), 0.0, 1.0)
    q = -np.log(np.maximum(1.0 - mel, 1e-4))
    sigma = (q * (1 - red))[:, None] * EUMELANIN + (q * red)[:, None] * PHEOMELANIN
    x = radial_roughness
    fac = (((((0.245 * x) + 5.574) * x - 10.73) * x + 2.532) * x - 0.215) * x + 5.969
    return np.exp(-np.sqrt(sigma * path) * fac)


ATTRS = ("r", "g", "b", "fu", "fv", "depth", "sid", "v", "rough")


class Cell:
    """One texture cell, W x H final px, supersampled ss x."""

    def __init__(self, W, H, ss):
        self.W, self.H, self.ss = W, H, ss
        self.Ws, self.Hs = W * ss, H * ss
        self.cov = np.zeros((self.Hs, self.Ws), dtype=np.float32)
        self.att = {k: np.zeros((self.Hs, self.Ws), dtype=np.float32) for k in ATTRS}
        self.strands = 0

    def draw(self, x, y, rad, alpha, v, depth, rgb, sid, rough, flow_jitter=0.0):
        """One strand: x, y (k,) final px (y along the cell: v), rad (k,) half-width in
        final px, alpha (k,), v (k,) root-to-tip, depth (k,) -1 .. 1 (+ front);
        rgb (3,), sid, rough scalars. Last drawn wins (call in depth order)."""
        ss = self.ss
        xs, ys = np.asarray(x) * ss, np.asarray(y) * ss
        seg = np.hypot(np.diff(xs), np.diff(ys))
        acc = np.concatenate([[0.0], np.cumsum(seg)])
        if acc[-1] < 1.0:
            return
        ns = max(int(acc[-1] / 0.7), 2)
        s = np.linspace(0, acc[-1], ns)
        xi, yi = np.interp(s, acc, xs), np.interp(s, acc, ys)
        ri = np.interp(s, acc, np.asarray(rad) * ss)
        ai = np.interp(s, acc, alpha)
        vi = np.interp(s, acc, v)
        di = np.interp(s, acc, depth)
        tx, ty = np.gradient(xi), np.gradient(yi)
        tl = np.hypot(tx, ty) + 1e-9
        tx, ty = tx / tl, ty / tl
        nx, ny = -ty, tx
        jit = flow_jitter * (2 * sid - 1)
        cj, sj = math.cos(jit), math.sin(jit)
        fu, fv = tx * cj - ty * sj, tx * sj + ty * cj
        rmax = float(ri.max())
        offs = np.arange(-math.ceil(rmax), math.ceil(rmax) + 1, 0.7)
        Xs, Ys, A, idx = [], [], [], []
        for o in offs:
            # coverage of this offset sample: full inside the radius, a 1 px ramp at the edge
            w = np.clip(ri + 0.5 - abs(o), 0.0, 1.0)
            ok = w > 0.02
            if not ok.any():
                continue
            Xs.append(np.round(xi[ok] + nx[ok] * o).astype(np.int64))
            Ys.append(np.round(yi[ok] + ny[ok] * o).astype(np.int64))
            A.append((ai[ok] * w[ok]).astype(np.float32))
            idx.append(np.flatnonzero(ok))
        if not Xs:
            return
        X, Y, A, I = np.concatenate(Xs), np.concatenate(Ys), np.concatenate(A), np.concatenate(idx)
        inb = (X >= 0) & (X < self.Ws) & (Y >= 0) & (Y < self.Hs)
        X, Y, A, I = X[inb], Y[inb], A[inb], I[inb]
        if len(X) == 0:
            return
        # within one strand keep the strongest sample per pixel (its own overlap is not more cover)
        flat = Y * self.Ws + X
        order = np.argsort(A, kind="stable")
        flat, A, I = flat[order], A[order], I[order]
        cv = self.cov.reshape(-1)
        # painter's order between strands: the new strand covers what is behind it
        old = cv[flat]
        cv[flat] = old + A * (1.0 - old)
        vals = {"r": rgb[0], "g": rgb[1], "b": rgb[2], "fu": fu[I], "fv": fv[I], "depth": di[I],
                "sid": sid, "v": vi[I], "rough": rough}
        for k, val in vals.items():
            a = self.att[k].reshape(-1)
            cur = a[flat]
            # blend toward the new strand by its own coverage (front-most dominates)
            a[flat] = cur + (np.asarray(val, dtype=np.float32) - cur) * np.where(old > 0, A, 1.0)
        self.strands += 1

    def resolve(self):
        """Final-res arrays: cov and the attributes (coverage-weighted means)."""
        H, W, ss = self.H, self.W, self.ss

        def down(a):
            return a.reshape(H, ss, W, ss).mean(axis=(1, 3))
        c = down(self.cov)
        out = {"cov": np.clip(c, 0, 1)}
        for k, a in self.att.items():
            out[k] = np.where(c > 1e-4, down(a * self.cov) / np.maximum(c, 1e-4), 0.0)
        return out


def blur(a, r):
    """Separable box blur, radius r px, 3 passes (~ Gaussian), edge-clamped."""
    if r <= 0:
        return a
    k = 2 * r + 1
    for _ in range(3):
        for ax in (0, 1):
            p = np.pad(a, [(r, r) if i == ax else (0, 0) for i in range(2)], mode="edge")
            cs = np.cumsum(p, axis=ax, dtype=np.float64)
            cs = np.concatenate([np.zeros_like(np.take(cs, [0], axis=ax)), cs], axis=ax)
            a = (np.take(cs, range(k, cs.shape[ax]), axis=ax) - np.take(cs, range(0, cs.shape[ax] - k), axis=ax)) / k
    return a.astype(np.float32)


class Atlas:
    """Three RGBA images (albedo full res, aniso and orm at 1/data_scale) filled cell by cell."""

    def __init__(self, W, H, data_scale=2):
        self.W, self.H, self.ds = W, H, data_scale
        self.alb = np.zeros((H, W, 4), dtype=np.float32)
        self.cov = np.zeros((H, W), dtype=np.float32)
        hd, wd = H // data_scale, W // data_scale
        self.aniso = np.zeros((hd, wd, 4), dtype=np.float32)
        self.aniso[..., :] = (0.5, 1.0, 1.0, 0.5)
        self.orm = np.zeros((hd, wd, 4), dtype=np.float32)
        self.orm[..., :] = (1.0, 0.6, 0.5, 0.0)
        self.rects = []

    def put(self, x0, y0, r, ao_cfg, rough_jitter=0.0):
        """Write a resolved cell r (Cell.resolve()) at pixel (x0, y0) (rows from the image
        bottom, Blender's convention). Returns its UV rect (u0, v0, u1, v1) at texel centres."""
        h, w = r["cov"].shape
        sl = (slice(y0, y0 + h), slice(x0, x0 + w))
        c = r["cov"]
        self.cov[sl] = c
        self.alb[sl + (slice(0, 3),)] = np.stack([r["r"], r["g"], r["b"]], -1)
        self.alb[sl + (3,)] = c
        ds = self.ds
        hd, wd = h // ds, w // ds

        def dn(a, wgt=None):
            a = a[:hd * ds, :wd * ds]
            if wgt is None:
                return a.reshape(hd, ds, wd, ds).mean(axis=(1, 3))
            ww = wgt[:hd * ds, :wd * ds]
            s = (a * ww).reshape(hd, ds, wd, ds).sum(axis=(1, 3))
            n = ww.reshape(hd, ds, wd, ds).sum(axis=(1, 3))
            return np.where(n > 1e-5, s / np.maximum(n, 1e-5), 0.0)
        fu, fv = dn(r["fu"], c), dn(r["fv"], c)
        fl = np.hypot(fu, fv)
        has = fl > 1e-3
        fu = np.where(has, fu / np.maximum(fl, 1e-6), 0.0)
        fv = np.where(has, fv / np.maximum(fl, 1e-6), 1.0)
        depth = dn(r["depth"], c)
        v = dn(r["v"], c)
        cd = dn(c)
        # occlusion: dark at the root (where the mass is thickest) and at the back of the card,
        # deeper where the cell is dense (local coverage)
        dens = blur(cd, 3)
        ao = (1.0 - ao_cfg["root"] * (1.0 - np.clip(v / ao_cfg["root_v"], 0, 1)) ** 2) \
            * (1.0 - ao_cfg["depth"] * np.clip(dens * 1.3, 0, 1) * (0.5 - 0.5 * depth))
        y0d, x0d = y0 // ds, x0 // ds
        dsl = (slice(y0d, y0d + hd), slice(x0d, x0d + wd))
        self.aniso[dsl + (0,)] = 0.5 + 0.5 * fu
        self.aniso[dsl + (1,)] = 0.5 + 0.5 * fv
        self.aniso[dsl + (2,)] = 1.0
        self.aniso[dsl + (3,)] = 0.5 + 0.5 * np.clip(depth, -1, 1)
        self.orm[dsl + (0,)] = np.clip(ao, 0.05, 1.0)
        self.orm[dsl + (1,)] = np.clip(dn(r["rough"], c), 0.05, 1.0)
        self.orm[dsl + (2,)] = dn(r["sid"], c)
        self.orm[dsl + (3,)] = np.clip(v, 0, 1)
        Wf, Hf = self.W, self.H
        rect = ((x0 + 0.5) / Wf, (y0 + 0.5) / Hf, (x0 + w - 0.5) / Wf, (y0 + h - 0.5) / Hf)
        self.rects.append(rect)
        return rect

    def bleed(self):
        """Colour under the transparent texels: the mean hair colour (mip-safe edges)."""
        m = self.cov > 0.02
        mean = self.alb[m][:, :3].mean(0) if m.any() else np.zeros(3)
        self.alb[..., :3] = np.where(m[..., None], self.alb[..., :3], mean[None, None, :])
        return mean

    def images(self, prefix):
        """Packed bpy images {albedo, aniso, orm} (albedo sRGB-encoded and tagged sRGB)."""
        from . import hair_mesh
        out = {}
        for key, arr, srgb in (("albedo", self.alb, True), ("aniso", self.aniso, False),
                               ("orm", self.orm, False)):
            out[key] = hair_mesh.rgba_image(f"{prefix}_{key}", arr, srgb)
        return out


def png_rgba8(rgba_top_down):
    """8-bit RGBA PNG bytes from a (h, w, 4) uint8 array, rows top-down."""
    a = np.ascontiguousarray(rgba_top_down, dtype=np.uint8)
    h, w = a.shape[:2]
    raw = b"".join(b"\x00" + a[y].tobytes() for y in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def image_png_bytes(img):
    """PNG bytes of a bpy image's stored values (bottom-up pixels -> top-down rows)."""
    w, h = img.size
    px = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(px)
    a = np.clip(np.round(px.reshape(h, w, 4)[::-1] * 255.0), 0, 255).astype(np.uint8)
    return png_rgba8(a)


def register_maps(b, material, images):
    """Remember the data maps of a hair material for export.pack_hair_maps."""
    if not hasattr(b, "hair_maps"):
        b.hair_maps = {}
    b.hair_maps[material.name] = {"anisotropy": images["aniso"].name, "orm": images["orm"].name}
    material["hair_maps"] = str(b.hair_maps[material.name])


def save_pngs(b, images, stem):
    """Review copies next to the GLB (<stem>_<key>.png); the GLB carries the real maps."""
    import os
    out = getattr(b, "out_dir", None)
    if not out:
        return
    for key, img in images.items():
        with open(os.path.join(out, f"{stem}_{key}.png"), "wb") as f:
            f.write(image_png_bytes(img))


def card_material(name, images, roughness=0.6, specular=0.25, vertex_color="lock", vertex_alpha=False):
    """Look-dev / EEVEE material for cards: albedo x COLOR_0 `vertex_color` (None: the
    albedo alone), alpha from the albedo (export.fix_alpha routes it to glTF MASK). The
    data maps reach the GLB through export.pack_hair_maps, not through this node tree.
    vertex_alpha (H2): the alpha is the albedo's x the colour attribute's, so the glTF
    exporter writes COLOR_0 as VEC4 (the viewer's hair.vertexAlpha reads it)."""
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(bsdf.outputs[0], out.inputs["Surface"])
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = images["albedo"]
    tex.extension = "EXTEND"
    if vertex_color:
        vc = nt.nodes.new("ShaderNodeVertexColor")
        vc.layer_name = vertex_color
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.blend_type = "MULTIPLY"
        mix.inputs["Factor"].default_value = 1.0
        nt.links.new(tex.outputs["Color"], mix.inputs[6])
        nt.links.new(vc.outputs["Color"], mix.inputs[7])
        nt.links.new(mix.outputs[2], bsdf.inputs["Base Color"])
    else:
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    if vertex_color and vertex_alpha:
        am = nt.nodes.new("ShaderNodeMath")
        am.operation = "MULTIPLY"
        nt.links.new(tex.outputs["Alpha"], am.inputs[0])
        nt.links.new(vc.outputs["Alpha"], am.inputs[1])
        nt.links.new(am.outputs[0], bsdf.inputs["Alpha"])
    else:
        nt.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Specular IOR Level"].default_value = specular
    for key in ("aniso", "orm"):
        t = nt.nodes.new("ShaderNodeTexImage")
        t.image = images[key]
        t.label = f"{name}_{key} (GLB: export.pack_hair_maps)"
    mat.use_backface_culling = False
    return mat
