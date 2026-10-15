"""A small deterministic cloth solver for the drafted suit (m1 v4 T13; bench/m1/v4/suit-spike.md §6).

Why not Blender cloth: its rest shape key sets both the rest lengths and the rest bending
angles. A two-stage weld (sew unwelded, weld, drape with the sewn state as rest) therefore
bakes the sewing-phase crumple into the rest shape, and a sewing spring has no bending across
it, so a single-stage drape hinges at every seam. Here the rest lengths and the rest
curvature are separate: lengths from the flat pattern, curvature flat (the cloth is flat
before it is sewn), and bending runs across welded seams like anywhere else.

    XPBD, small steps (Macklin et al. 2019): many substeps, one Gauss-Seidel sweep each,
    the sweep vectorised per colour (no two constraints of one colour share a vertex)

    stretch   per edge, rest length from the flat pattern; compression softer than stretch
              (woven cloth buckles rather than compresses)
    bending   isometric bending (Bergou et al. 2006): per interior edge a 4-vertex stencil
              with cotangent weights from the rest triangles, rest curvature 0; a linear
              constraint per axis, so the XPBD update is exact
    sewing    zero-length constraints whose compliance ramps down (stage 1), then the sewn
              pairs are welded and the solver rebuilt on the welded mesh (stage 2)
    collision a signed distance callable sdf(P) -> (d, grad) (grids built in Blender);
              push-out to a thickness, Coulomb-like friction on the substep displacement
    layers    vertex sets that must stay outside other sets (the left front over the right)

numpy only, float64, fixed operation order: bit-identical reruns.
"""

import math

import numpy as np


def edges_of(T):
    E = np.vstack([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]])
    return np.unique(np.sort(E, 1), axis=0)


def colour(groups, n):
    """Greedy colouring of constraint vertex groups (k, m) so no two in a colour share a
    vertex. Returns a list of index arrays."""
    used = [0] * n          # per-vertex bitmask of colours taken
    col = np.zeros(len(groups), int)
    for k, g in enumerate(groups):
        m = 0
        for v in g:
            m |= used[v]
        c = 0
        while m >> c & 1:
            c += 1
        col[k] = c
        b = 1 << c
        for v in g:
            used[v] |= b
    return [np.nonzero(col == c)[0] for c in range(col.max() + 1)] if len(groups) else []


def _tri_cots(la, lb, lc):
    """Cotangents of the angles opposite edges a, b, c of triangles with those lengths."""
    def cot(opp, s1, s2):
        cos = (s1 * s1 + s2 * s2 - opp * opp) / (2 * s1 * s2)
        cos = np.clip(cos, -0.999, 0.999)
        return cos / np.sqrt(1 - cos * cos)
    return cot(la, lb, lc), cot(lb, la, lc), cot(lc, la, lb)


def stencils(T, rest_len):
    """Isometric bending stencils. rest_len(i, j) -> rest length of edge (i, j) (arrays).
    Returns idx (k, 4) [x0, x1 = the edge, x2, x3 = the opposite vertices], K (k, 4), and
    the scale s (k,) with energy 1/2 kb |s K x|^2."""
    adj = {}
    for fi, t in enumerate(T):
        for a, b, c in ((t[0], t[1], t[2]), (t[1], t[2], t[0]), (t[2], t[0], t[1])):
            adj.setdefault((min(a, b), max(a, b)), []).append(c)
    idx = []
    for (a, b), opp in adj.items():
        if len(opp) == 2:
            idx.append((a, b, opp[0], opp[1]))
    idx = np.array(idx, int).reshape(-1, 4)
    if not len(idx):
        return idx, np.zeros((0, 4)), np.zeros(0)
    x0, x1, x2, x3 = idx.T
    L01, L02, L12 = rest_len(x0, x1), rest_len(x0, x2), rest_len(x1, x2)
    L03, L13 = rest_len(x0, x3), rest_len(x1, x3)
    # triangle A = (x0, x1, x2): angle at x0 between e0 = x1-x0 and e1 = x2-x0 (opposite L12),
    # angle at x1 between -e0 and e3 = x2-x1 (opposite L02)
    c01 = _tri_cots(L12, L02, L01)[0]          # angle at x0 in A (opposite L12)
    c03 = _tri_cots(L02, L12, L01)[0]          # angle at x1 in A (opposite L02)
    c02 = _tri_cots(L13, L03, L01)[0]          # angle at x0 in B (opposite L13)
    c04 = _tri_cots(L03, L13, L01)[0]          # angle at x1 in B (opposite L03)
    K = np.stack([c03 + c04, c01 + c02, -c01 - c03, -c02 - c04], 1)

    def area(a, b, c):
        s = 0.5 * (a + b + c)
        return np.sqrt(np.maximum(s * (s - a) * (s - b) * (s - c), 1e-16))
    A = area(L01, L02, L12) + area(L01, L03, L13)
    return idx, K, np.sqrt(3.0 / A)


class Solver:
    """X (n, 3) start positions, T (m, 3) triangles, L0 {edge (i, j) sorted: rest length} or
    an (k,) array aligned with edges_of(T), mass (n,), per-vertex bending stiffness kb (n,)
    (a stencil takes the mean of its edge's two vertices)."""

    def __init__(self, X, T, L0, mass, kb, opts):
        self.o = o = opts
        self.X = np.array(X, float)
        self.V = np.zeros_like(self.X)
        self.T = np.asarray(T, int)
        n = len(self.X)
        self.w = 1.0 / np.asarray(mass, float)
        self.E = edges_of(self.T)
        if isinstance(L0, dict):
            self.L0 = np.array([L0[(int(a), int(b))] for a, b in self.E])
        else:
            self.L0 = np.asarray(L0, float)
        lut = {(int(a), int(b)): l for (a, b), l in zip(self.E, self.L0)}

        def rest_len(i, j):
            return np.array([lut[(min(a, b), max(a, b))] for a, b in zip(i, j)])
        self.S, self.K, self.s = stencils(self.T, rest_len)
        kbv = np.asarray(kb, float)
        self.kb = 0.5 * (kbv[self.S[:, 0]] + kbv[self.S[:, 1]]) if len(self.S) else np.zeros(0)
        self.ecol = colour(self.E, n)
        self.scol = colour(self.S, n)
        self.sew = np.zeros((0, 2), int)
        self.sew_len = np.zeros(0)
        self.sew_col = []
        self.layers = []
        self.layer_force = []    # (A, B, gap) pairs held in order at any distance (a button pair)
        self.sdf = None
        self.pinned = np.zeros(n, bool)
        self.hold_idx = np.zeros(0, int)       # soft attachments to target positions
        self.hold_pos = np.zeros((0, 3))
        self.hold_k = 0.0
        self.kstretch = np.full(len(self.E), o["k_stretch"])
        self.kcomp = np.full(len(self.E), o["k_comp"])
        # self-contact: vertex-vertex repulsion at radius self_r between vertices that are
        # at least self_excl apart in the reference shape self_ref (the placed, unfolded
        # garment: neighbours on the cloth never repel); self_skip vertices take no part
        self.self_ref = None
        self.self_r = 0.0
        self.self_excl = 0.0
        self.self_skip = None

    def set_sew(self, pairs, rest=None):
        self.sew = np.asarray(pairs, int).reshape(-1, 2)
        self.sew_len = np.zeros(len(self.sew)) if rest is None else np.asarray(rest, float)
        self.sew_col = colour(self.sew, len(self.X))

    def step(self, h, g, k_sew=0.0):
        X, V, w = self.X, self.V, self.w
        free = ~self.pinned
        V[free, 2] -= g * h
        V *= math.exp(-self.o["damping"] * h)
        P0 = X.copy()
        X[free] += V[free] * h
        h2 = h * h
        wp = np.where(free, w, 0.0)
        # stretch (stretch_iters sweeps: inextensibility converges slowest)
        for c in self.ecol * self.o.get("stretch_iters", 1):
            i, j = self.E[c, 0], self.E[c, 1]
            d = X[i] - X[j]
            L = np.sqrt((d * d).sum(1))
            n = d / np.maximum(L, 1e-12)[:, None]
            C = L - self.L0[c]
            k = np.where(C > 0, self.kstretch[c], self.kcomp[c])
            dl = -C / (wp[i] + wp[j] + 1.0 / (k * h2))
            X[i] += (wp[i] * dl)[:, None] * n
            X[j] -= (wp[j] * dl)[:, None] * n
        # sewing
        if len(self.sew) and k_sew > 0:
            for c in self.sew_col:
                i, j = self.sew[c, 0], self.sew[c, 1]
                d = X[i] - X[j]
                L = np.sqrt((d * d).sum(1))
                n = d / np.maximum(L, 1e-12)[:, None]
                C = L - self.sew_len[c]
                dl = -C / (wp[i] + wp[j] + 1.0 / (k_sew * h2))
                X[i] += (wp[i] * dl)[:, None] * n
                X[j] -= (wp[j] * dl)[:, None] * n
        # bending
        for c in self.scol:
            S, K, s = self.S[c], self.K[c], self.s[c]
            x = X[S]                                           # (k, 4, 3)
            C = s[:, None] * np.einsum("kj,kjc->kc", K, x)     # (k, 3)
            ws = wp[S]
            den = s * s * (ws * K * K).sum(1) + 1.0 / (self.kb[c] * h2)
            dl = -C / den[:, None]
            X[S] += (ws * K * s[:, None])[:, :, None] * dl[:, None, :]
        # holds
        if len(self.hold_idx) and self.hold_k > 0:
            i = self.hold_idx
            dl = (wp[i] / (wp[i] + 1.0 / (self.hold_k * h2)))[:, None]
            X[i] -= dl * (X[i] - self.hold_pos)
        # layers: set A stays outside set B along B's outward normal by `gap`
        for A, B, gap in self.layers:
            self._layer(A, B, gap)
        for A, B, gap in self.layer_force:
            self._layer_pairs(A, B, gap)
        # self-contact
        if self.self_ref is not None and self.self_r > 0:
            self._self_contact(X, wp)
        # collisions
        if self.sdf is not None:
            d, gr = self.sdf(X)
            th = self.o["thickness"]
            pen = (d < th) & free
            if pen.any():
                X[pen] += (th - d[pen])[:, None] * gr[pen]
                dx = X[pen] - P0[pen]
                gn = gr[pen]
                tang = dx - (dx * gn).sum(1)[:, None] * gn
                X[pen] -= self.o["friction"] * tang
        self.V = (X - P0) / h
        self.V[~free] = 0.0
        self.X = X

    def _self_contact(self, X, wp):
        r = self.self_r
        idx = np.arange(len(X)) if self.self_skip is None else np.nonzero(~self.self_skip)[0]
        i, j = close_pairs(X[idx], r)
        if not len(i):
            return
        i, j = idx[i], idx[j]
        far = np.linalg.norm(self.self_ref[i] - self.self_ref[j], axis=1) > self.self_excl
        i, j = i[far], j[far]
        if not len(i):
            return
        d = X[i] - X[j]
        L = np.sqrt((d * d).sum(1))
        n = d / np.maximum(L, 1e-12)[:, None]
        ws = wp[i] + wp[j]
        ok = ws > 0
        i, j, n, L, ws = i[ok], j[ok], n[ok], L[ok], ws[ok]
        C = (r - L) / ws
        acc = np.zeros_like(X)
        cnt = np.zeros(len(X))
        np.add.at(acc, i, (wp[i] * C)[:, None] * n)
        np.add.at(acc, j, -(wp[j] * C)[:, None] * n)
        np.add.at(cnt, i, 1.0)
        np.add.at(cnt, j, 1.0)
        m = cnt > 0
        X[m] += acc[m] / cnt[m][:, None]

    def _layer_pairs(self, a, b, gap):
        """a[k] stays outside b[k] (along b's outward normal) by gap, however far through."""
        X = self.X
        if self.sdf is None:
            return
        _, nb = self.sdf(X[b])
        s = ((X[a] - X[b]) * nb).sum(1)
        bad = s < gap
        if bad.any():
            corr = (gap - s[bad])[:, None] * nb[bad]
            X[a[bad]] += 0.5 * corr
            X[b[bad]] -= 0.5 * corr

    def _layer(self, A, B, gap):
        X = self.X
        if self.sdf is None:
            return
        xa, xb = X[A], X[B]
        d2 = ((xa[:, None, :] - xb[None, :, :]) ** 2).sum(2)
        j = np.argmin(d2, 1)
        near = np.sqrt(d2[np.arange(len(A)), j]) < 3 * gap
        if not near.any():
            return
        a, b = A[near], B[j[near]]
        _, nb = self.sdf(X[b])
        s = ((X[a] - X[b]) * nb).sum(1)
        bad = s < gap
        if bad.any():
            a, b, nb, s = a[bad], b[bad], nb[bad], s[bad]
            corr = (gap - s)[:, None] * nb
            X[a] += 0.5 * corr
            X[b] -= 0.5 * corr

    def run(self, frames, fps, substeps, g_of=lambda f: 9.81, ksew_of=lambda f: 0.0, cb=None):
        h = 1.0 / fps / substeps
        for f in range(frames):
            g, ks = g_of(f), ksew_of(f)
            for _ in range(substeps):
                self.step(h, g, ks)
            if cb is not None:
                cb(f, self)


_HASH = np.array([73856093, 19349663, 83492791], np.int64)
_OFFS = np.array([(a, b, c) for a in (-1, 0, 1) for b in (-1, 0, 1) for c in (-1, 0, 1)], np.int64)


def close_pairs(P, r):
    """All pairs (i < j) of points closer than r (uniform grid hash, cell r). Deterministic."""
    n = len(P)
    q = np.floor(P / r).astype(np.int64)
    key = np.bitwise_xor.reduce(q * _HASH, axis=1)
    order = np.argsort(key, kind="stable")
    ks = key[order]
    I, J = [], []
    for off in _OFFS:
        nk = np.bitwise_xor.reduce((q + off) * _HASH, axis=1)
        lo = np.searchsorted(ks, nk, "left")
        hi = np.searchsorted(ks, nk, "right")
        cnt = hi - lo
        tot = int(cnt.sum())
        if not tot:
            continue
        ii = np.repeat(np.arange(n), cnt)
        start = np.repeat(lo - (np.cumsum(cnt) - cnt), cnt)
        jj = order[start + np.arange(tot)]
        keep = ii < jj
        I.append(ii[keep])
        J.append(jj[keep])
    if not I:
        return np.zeros(0, int), np.zeros(0, int)
    I, J = np.concatenate(I), np.concatenate(J)
    d2 = ((P[I] - P[J]) ** 2).sum(1)
    near = d2 < r * r
    I, J = I[near], J[near]
    u = np.unique(I.astype(np.int64) * n + J)
    return (u // n).astype(int), (u % n).astype(int)


def mass_from_flat(Tflat, Rflat, n, density):
    """Per-vertex lumped mass (kg) from flat triangles (m) and a per-vertex density (kg/m2)."""
    a = 0.5 * np.linalg.norm(np.cross(Rflat[Tflat[:, 1]] - Rflat[Tflat[:, 0]],
                                      Rflat[Tflat[:, 2]] - Rflat[Tflat[:, 0]]), axis=1)
    rho = np.asarray(density, float)
    m = np.zeros(n)
    for k in range(3):
        np.add.at(m, Tflat[:, k], a * rho[Tflat].mean(1) / 3.0)
    return m


class Grid:
    """A sampled signed distance (and its gradient) on a regular grid; trilinear lookup.
    Outside the grid: +big."""

    def __init__(self, D, lo, h):
        self.D = np.asarray(D, float)
        self.lo = np.asarray(lo, float)
        self.h = float(h)
        G = np.gradient(self.D, self.h)
        self.G = np.stack(G, -1)

    def __call__(self, P):
        P = np.atleast_2d(P)
        u = (P - self.lo) / self.h
        sh = np.array(self.D.shape) - 1
        inside = np.all((u >= 0) & (u < sh), 1)
        u = np.clip(u, 0, sh - 1e-6)
        i = np.floor(u).astype(int)
        f = u - i
        d = np.zeros(len(P))
        g = np.zeros((len(P), 3))
        for dx in (0, 1):
            wx = f[:, 0] if dx else 1 - f[:, 0]
            for dy in (0, 1):
                wy = f[:, 1] if dy else 1 - f[:, 1]
                for dz in (0, 1):
                    wz = f[:, 2] if dz else 1 - f[:, 2]
                    ww = wx * wy * wz
                    ii, jj, kk = i[:, 0] + dx, i[:, 1] + dy, i[:, 2] + dz
                    d += ww * self.D[ii, jj, kk]
                    g += ww[:, None] * self.G[ii, jj, kk]
        d = np.where(inside, d, 1e3)
        g /= np.maximum(np.linalg.norm(g, axis=1, keepdims=True), 1e-12)
        return d, g


def union(*fields):
    """Pointwise minimum of several sdf callables (gradient of the minimum)."""
    def f(P):
        best_d, best_g = None, None
        for fn in fields:
            d, g = fn(P)
            if best_d is None:
                best_d, best_g = d, g
            else:
                m = d < best_d
                best_d = np.where(m, d, best_d)
                best_g = np.where(m[:, None], g, best_g)
        return best_d, best_g
    return f
