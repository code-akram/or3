"""Eye parity metrics on the hero portrait (track T18b; was T18's / T19's scratch script).

    python3 -I bench/m1/eye_metrics.py measure IMG [--offset X,Y] [--json OUT] [--overlay OUT.png]
    python3 -I bench/m1/eye_metrics.py compare --engine IMG [--engine-offset X,Y] --cycles IMG
        [--cycles-offset X,Y] [--json OUT] [--overlay OUT.png] [--blur PX]
    python3 -I bench/m1/eye_metrics.py turntable DIR [--box X,Y,W,H] [--json OUT]
    python3 -I bench/m1/eye_metrics.py strip --panels A.png,B.png,C.png [--offsets ...] --window X,Y,W,H
        [--scale 3] --out OUT.png

Coordinates are those of the 1920 x 1080 hero portrait (blender/hero/shots.py `portrait`; the engine
`portrait` view uses the same camera and shot lights). An image's --offset is where its top-left pixel sits
in that frame, so the same code reads:
  - the engine's full frame (game_portrait.png, offset 0,0),
  - Cycles' `portrait_crop` (960 x 540, the 100 % crop at 556,98: offset 556,98, the default for 960x540),
  - an engine eye window (engine_shots.mjs --crop X,Y,W,H: offset X,Y).

Per eye (near = the key side, image left; far = image right), around the iris centre found in each frame
(the limbus edge of a disc of fixed radius R = IRIS_R, 13 px, in both renderers; T18 used 15.5 px):
  iris       median scene-linear luminance (sRGB decoded) over 0.6-0.92 x R, without the upper lid's
             sector (|angle from up| < 50 deg) and the brightest 8 % (catchlight, rim glints)
  sclera     median over two 8 x 7 boxes beside the iris (their inner edge 4 px past the limbus, 2 px below
             the centre); nasal and temporal also reported apart
  ratio      sclera / iris
  ratio2     the mean of the nasal and temporal box medians / iris (T18b: robust; see sclera2 in eye_measure)
  catchlight pixels of the iris disc at >= 0.5 x the disc's peak and >= 2 x the iris median, as a share of
             the disc's area; the peak (0..255 display luma) as well
  sat        median HSV saturation (display sRGB, 8 bit) over the iris annulus
  under      16 x 6 boxes on the iris column 20 px (bag) and 36 px (cheek top) below the iris centre: median
             display sRGB and linear luminance (T18b's under-eye; T19's 92 vs 118 box was not scripted)
--blur PX applies the same Gaussian (sigma PX, display values) to both frames before measuring: the
equal-filter catchlight comparison (Cycles' 1.5 px Blackman-Harris pixel filter + OIDN vs the engine's TRAA).

turntable: per frame of an engine turntable dir (frame_*.png), the catchlight peak (display luma max) and
its area (pixels >= 0.5 x peak within 4 px of the peak) in --box, the peak's frame-to-frame step and
coefficient of variation (the pulse), and the temporal noise there (mean |L(t-1) - 2 L(t) + L(t+1)|),
T18's TRAA table.

stdlib + numpy + ffmpeg (no imaging library), like lookdev_report.py.
"""

import argparse
import json
import math
import os
import subprocess
import sys

import numpy as np

FRAME = (1920, 1080)
CYCLES_CROP = (556, 98)        # portrait_crop's window in the full frame (960 x 540)
IRIS_R = 13.0                  # iris radius (px) in the portrait frame (fits of both renderers: 11.5-14)
RADIUS_RANGE = (IRIS_R, IRIS_R)  # (lo, hi): a fixed radius, the same annulus in both renderers
# search boxes for the iris centres (full-frame px): near (key side, image left), far
SEARCH = {"near": (930, 335, 60, 60), "far": (1080, 340, 60, 60)}
EYE_WINDOW = (896, 318, 280, 100)   # the eye strip of T18's triptychs (crop 340,220 of portrait_crop)


# ------------------------------------------------------------------------------------------- io

def read_rgb(path):
    """(h, w, 3) uint8 through ffmpeg."""
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height", "-of", "csv=p=0", path],
                           check=True, capture_output=True, text=True).stdout.strip().split(",")
    w, h = int(probe[0]), int(probe[1])
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", path, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(h, w, 3)


def write_rgb(path, img):
    img = np.ascontiguousarray(np.clip(img, 0, 255).astype(np.uint8))
    h, w = img.shape[:2]
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
                    "-i", "-", path], input=img.tobytes(), check=True)


def default_offset(img):
    h, w = img.shape[:2]
    if (w, h) == FRAME:
        return (0, 0)
    if (w, h) == (960, 540):
        return CYCLES_CROP
    raise SystemExit(f"{w}x{h}: give --offset (where the image sits in the 1920x1080 portrait)")


def lin(c):
    c = np.asarray(c, np.float64) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def luma_lin(rgb):
    return lin(rgb) @ np.array([0.2126, 0.7152, 0.0722])


def luma_disp(rgb):
    return np.asarray(rgb, np.float64) @ np.array([0.2126, 0.7152, 0.0722])


def gauss_blur(img, sigma):
    if sigma <= 0:
        return np.asarray(img, np.float64)
    r = int(math.ceil(3 * sigma))
    x = np.arange(-r, r + 1)
    k = np.exp(-0.5 * (x / sigma) ** 2)
    k /= k.sum()
    a = np.asarray(img, np.float64)
    pad = [(r, r), (r, r)] + [(0, 0)] * (a.ndim - 2)
    p = np.pad(a, pad, mode="edge")
    tmp = sum(k[i] * p[:, i:i + a.shape[1]] for i in range(2 * r + 1))
    return sum(k[i] * tmp[i:i + a.shape[0]] for i in range(2 * r + 1))


# -------------------------------------------------------------------------------------- measure

class Frame:
    def __init__(self, path, offset=None, blur=0.0):
        self.path = path
        raw = read_rgb(path)
        self.off = tuple(offset) if offset else default_offset(raw)
        self.rgb = gauss_blur(raw, blur) if blur > 0 else raw.astype(np.float64)
        self.L = luma_lin(self.rgb)
        self.D = luma_disp(self.rgb)

    def local(self, x, y):
        return x - self.off[0], y - self.off[1]

    def grid(self):
        h, w = self.L.shape
        yy, xx = np.mgrid[0:h, 0:w]
        return xx + self.off[0] + 0.5, yy + self.off[1] + 0.5


def find_iris(fr, box):
    """Iris centre (full-frame px) and radius: the limbus as the strongest dark-to-light edge in the
    sectors within 40 deg of horizontal (the lids cover the rest), plus a dark pupil at the centre."""
    X, Y = fr.grid()
    bx, by, bw, bh = box
    lx0, ly0 = fr.local(bx - 22, by - 22)
    lx1, ly1 = fr.local(bx + bw + 22, by + bh + 22)
    lx0, ly0, lx1, ly1 = max(int(lx0), 0), max(int(ly0), 0), min(int(lx1), fr.L.shape[1]), min(int(ly1), fr.L.shape[0])
    sub = np.sqrt(fr.L[ly0:ly1, lx0:lx1])          # perceptual-ish, so the dark iris edge counts
    Xs, Ys = X[ly0:ly1, lx0:lx1], Y[ly0:ly1, lx0:lx1]
    def score(cx, cy, r):
        dx, dy = Xs - cx, Ys - cy
        d = np.hypot(dx, dy)
        horiz = np.abs(dy) < np.sin(np.radians(40)) * d
        out = horiz & (d > r + 0.5) & (d < r + 3.5)
        inn = horiz & (d > r - 3.5) & (d < r - 0.5)
        pup = d < 0.3 * r
        if out.sum() < 8 or inn.sum() < 8:
            return None
        return sub[out].mean() - sub[inn].mean() - 0.5 * sub[pup].mean()

    best = None
    # coarse (2 px, 1 px radius), then fine (0.5 px) around the best
    cands = [(cx, cy, r) for r in np.arange(RADIUS_RANGE[0], RADIUS_RANGE[1] + 0.01, 1.0)
             for cy in np.arange(by, by + bh, 2.0) for cx in np.arange(bx, bx + bw, 2.0)]
    for _ in range(2):
        for cx, cy, r in cands:
            v = score(cx, cy, r)
            if v is not None and (best is None or v > best[0]):
                best = (v, cx, cy, r)
        if best is None:
            break
        _, bx0, by0, br0 = best
        cands = [(bx0 + i, by0 + j, br0 + k) for i in np.arange(-2, 2.01, 0.5) for j in np.arange(-2, 2.01, 0.5)
                 for k in np.arange(-1, 1.01, 0.5) if RADIUS_RANGE[0] <= br0 + k <= RADIUS_RANGE[1]]
    if best is None:
        raise SystemExit(f"{fr.path}: no iris found in {box}")
    return (float(best[1]), float(best[2])), float(best[3])


def eye_measure(fr, name, centre, r=IRIS_R):
    X, Y = fr.grid()
    cx, cy = centre
    dx, dy = X - cx, Y - cy
    d = np.hypot(dx, dy)
    ang = np.degrees(np.arctan2(dx, -dy))       # 0 = up (image y down)
    ann = (d >= 0.6 * r) & (d <= 0.92 * r) & (np.abs(ang) > 50)
    Li = fr.L[ann]
    keep = Li <= np.quantile(Li, 0.92)
    iris = float(np.median(Li[keep]))
    # sclera boxes: inner edge 4 px past the limbus, 8 x 7, centred 2 px below the centre
    boxes = {}
    for s, sgn in (("left", -1), ("right", 1)):
        x0 = cx + sgn * (r + 4) if sgn > 0 else cx - r - 4 - 8
        m = (X >= x0) & (X < x0 + 8) & (Y >= cy + 2 - 3.5) & (Y < cy + 2 + 3.5)
        boxes[s] = fr.L[m]
    # image left is temporal for the near eye (the subject's right eye, on image left) and nasal for the far
    nasal, temporal = (boxes["right"], boxes["left"]) if name == "near" else (boxes["left"], boxes["right"])
    sclera = float(np.median(np.concatenate([nasal, temporal])))
    # T18b: the mean of the two boxes' medians. One box is lit and one shaded (2-12x apart), so the median of
    # their union falls in the gap between the two populations and flips with a few pixels (bench/m1/v4/
    # t18b-eyes.md); this one does not
    sclera2 = 0.5 * (float(np.median(nasal)) + float(np.median(temporal)))
    disc = d <= r
    Ld = fr.L[disc]
    peak = Ld.max()
    cl = (Ld >= 0.5 * peak) & (Ld >= 2 * iris)
    rgb = fr.rgb[ann][keep]
    mx = rgb.max(-1)
    sat = np.where(mx > 0, (mx - rgb.min(-1)) / np.maximum(mx, 1e-9), 0)
    # under-eye (T18b): 16 x 6 boxes centred on the iris column, 20 px (the bag / lower-lid shadow) and
    # 36 px (the cheek top) below the iris centre; median display sRGB (0..255) and linear luminance
    under = {}
    for k, dy_ in (("bag", 20), ("cheek", 36)):
        m = (X >= cx - 8) & (X < cx + 8) & (Y >= cy + dy_ - 3) & (Y < cy + dy_ + 3)
        under[k] = {"srgb": [round(float(v), 1) for v in np.median(fr.rgb[m], 0)], "lum": round(float(np.median(fr.L[m])), 5)}
    return {
        "centre": [round(cx, 1), round(cy, 1)],
        "under": under,
        "iris": round(iris, 5), "sclera": round(sclera, 5),
        "sclera_nasal": round(float(np.median(nasal)), 5), "sclera_temporal": round(float(np.median(temporal)), 5),
        "ratio": round(sclera / max(iris, 1e-9), 3),
        "sclera2": round(sclera2, 5), "ratio2": round(sclera2 / max(iris, 1e-9), 3),
        "catchlight_share": round(float(cl.sum()) / (math.pi * r * r), 5),
        "catchlight_px": int(cl.sum()),
        "catchlight_peak_disp": round(float(fr.D[disc].max()), 1),
        "sat": round(float(np.median(sat)), 3),
        "iris_disp_rgb": [round(float(v), 1) for v in np.median(fr.rgb[ann][keep], 0)],
    }


def measure(path, offset=None, blur=0.0, overlay=None):
    fr = Frame(path, offset, blur)
    out = {"file": os.path.abspath(path), "offset": list(fr.off), "blur_sigma": blur}
    for name, box in SEARCH.items():
        centre, r = find_iris(fr, box)
        out[name] = eye_measure(fr, name, centre, r)
        out[name]["radius_px"] = r
    out["both"] = {k: round((out["near"][k] + out["far"][k]) / 2, 5) for k in ("ratio", "ratio2", "catchlight_share", "sat")}
    if overlay:
        draw_overlay(fr, out, overlay)
    return out


def draw_overlay(fr, m, path, scale=3):
    """The eye window x scale with the iris annulus, the sclera boxes and the catchlight pixels marked."""
    x0, y0, w, h = EYE_WINDOW
    lx, ly = fr.local(x0, y0)
    lx, ly = int(lx), int(ly)
    img = np.zeros((h, w, 3))
    hh, ww = fr.rgb.shape[:2]
    ys, xs = slice(max(ly, 0), min(ly + h, hh)), slice(max(lx, 0), min(lx + w, ww))
    img[ys.start - ly:ys.stop - ly, xs.start - lx:xs.stop - lx] = fr.rgb[ys, xs]
    X, Y = np.meshgrid(np.arange(w) + x0 + 0.5, np.arange(h) + y0 + 0.5)
    for name in ("near", "far"):
        e = m[name]
        cx, cy = e["centre"]
        d = np.hypot(X - cx, Y - cy)
        r = e["radius_px"]
        ring = (np.abs(d - 0.6 * r) < 0.5) | (np.abs(d - 0.92 * r) < 0.5) | (np.abs(d - r) < 0.3)
        img[ring] = img[ring] * 0.4 + np.array([0, 255, 0]) * 0.6
        for sgn in (-1, 1):
            bx = cx + sgn * (r + 4) if sgn > 0 else cx - r - 12
            bm = (X >= bx) & (X < bx + 8) & (Y >= cy + 2 - 3.5) & (Y < cy + 2 + 3.5)
            img[bm] = img[bm] * 0.5 + np.array([255, 255, 0]) * 0.5
    big = np.repeat(np.repeat(img, scale, 0), scale, 1)
    write_rgb(path, big)


def compare(a):
    blur = a.blur
    e = measure(a.engine, parse_xy(a.engine_offset), blur, a.overlay and a.overlay.replace(".png", "_engine.png"))
    c = measure(a.cycles, parse_xy(a.cycles_offset), blur, a.overlay and a.overlay.replace(".png", "_cycles.png"))
    rel = {}
    for eye in ("near", "far"):
        rel[eye] = {k: round(e[eye][k] / max(c[eye][k], 1e-9), 3)
                    for k in ("ratio", "ratio2", "iris", "sclera", "sclera2", "sclera_nasal", "sclera_temporal", "catchlight_share", "sat")}
        for k in ("bag", "cheek"):
            rel[eye][f"under_{k}"] = round(e[eye]["under"][k]["lum"] / max(c[eye]["under"][k]["lum"], 1e-9), 3)
    rel["both"] = {k: round(e["both"][k] / max(c["both"][k], 1e-9), 3) for k in ("ratio", "ratio2", "catchlight_share", "sat")}
    out = {"engine": e, "cycles": c, "engine_over_cycles": rel}
    return out


# ------------------------------------------------------------------------------------- turntable

def box_mean(D, r):
    """Mean over the (2r+1)^2 window (edge-padded)."""
    P = np.pad(D, r, mode="edge")
    c = np.cumsum(np.cumsum(P, 0), 1)
    c = np.pad(c, ((1, 0), (1, 0)))
    k = 2 * r + 1
    h, w = D.shape
    return (c[k:k + h, k:k + w] - c[:h, k:k + w] - c[k:k + h, :w] + c[:h, :w]) / (k * k)


def turntable(a):
    files = sorted(f for f in os.listdir(a.dir) if f.startswith("frame_") and f.endswith(".png"))
    Ls, peaks, areas = [], [], []
    for f in files:
        img = read_rgb(os.path.join(a.dir, f))
        if a.box:
            x, y, w, h = parse_box(a.box)
            img = img[y:y + h, x:x + w]
        D = luma_disp(img)
        Ls.append(D)
        # the catchlight: the pixel standing highest over its 9 x 9 mean (a skin sheen in the box is broad)
        iy, ix = np.unravel_index(int((D - box_mean(D, 4)).argmax()), D.shape)
        p = D[iy, ix]
        peaks.append(round(float(p), 1))
        # its area: pixels >= half its peak within 4 px
        win = D[max(iy - 4, 0):iy + 5, max(ix - 4, 0):ix + 5]
        areas.append(int((win >= 0.5 * p).sum()))
    noise = [float(np.abs(Ls[i - 1] - 2 * Ls[i] + Ls[i + 1]).mean()) for i in range(1, len(Ls) - 1)]
    dp = [abs(peaks[i] - peaks[i - 1]) for i in range(1, len(peaks))]
    return {"dir": os.path.abspath(a.dir), "box": a.box, "frames": len(files), "peak": peaks, "area_px": areas,
            "peak_mean": round(float(np.mean(peaks)), 1), "peak_step_mean": round(float(np.mean(dp)), 2) if dp else 0,
            "peak_cv": round(float(np.std(peaks) / max(np.mean(peaks), 1e-9)), 4),
            "area_mean": round(float(np.mean(areas)), 2),
            "noise_mean": round(float(np.mean(noise)), 3) if noise else 0}


# ----------------------------------------------------------------------------------------- strip

def strip(a):
    """Panels side by side, each cut to --window (full-frame coordinates) and scaled (nearest)."""
    paths = a.panels.split(",")
    offs = [parse_xy(o) if o else None for o in (a.offsets.split(";") if a.offsets else [""] * len(paths))]
    x0, y0, w, h = parse_box(a.window)
    tiles = []
    for p, o in zip(paths, offs):
        raw = read_rgb(p)
        off = o or default_offset(raw)
        lx, ly = x0 - off[0], y0 - off[1]
        t = np.zeros((h, w, 3), np.uint8)
        hh, ww = raw.shape[:2]
        ys, xs = slice(max(ly, 0), min(ly + h, hh)), slice(max(lx, 0), min(lx + w, ww))
        if ys.stop > ys.start and xs.stop > xs.start:
            t[ys.start - ly:ys.stop - ly, xs.start - lx:xs.stop - lx] = raw[ys, xs]
        t = np.repeat(np.repeat(t, a.scale, 0), a.scale, 1)
        tiles.append(t)
        tiles.append(np.full((t.shape[0], 4, 3), 255, np.uint8))
    out = np.concatenate(tiles[:-1], 1) if not a.vertical else np.concatenate(
        [np.concatenate([t, np.full((4, t.shape[1], 3), 255, np.uint8)], 0) for t in tiles[::2]], 0)
    write_rgb(a.out, out)
    return {"out": a.out, "panels": paths, "window": [x0, y0, w, h], "scale": a.scale}


def parse_xy(s):
    return tuple(int(float(v)) for v in s.split(",")) if s else None


def parse_box(s):
    return tuple(int(float(v)) for v in s.split(","))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("measure")
    m.add_argument("img")
    m.add_argument("--offset")
    m.add_argument("--blur", type=float, default=0.0)
    m.add_argument("--json")
    m.add_argument("--overlay")
    c = sub.add_parser("compare")
    c.add_argument("--engine", required=True)
    c.add_argument("--engine-offset")
    c.add_argument("--cycles", required=True)
    c.add_argument("--cycles-offset")
    c.add_argument("--blur", type=float, default=0.0)
    c.add_argument("--json")
    c.add_argument("--overlay")
    t = sub.add_parser("turntable")
    t.add_argument("dir")
    t.add_argument("--box")
    t.add_argument("--json")
    s = sub.add_parser("strip")
    s.add_argument("--panels", required=True)
    s.add_argument("--offsets", help="';'-separated X,Y per panel (empty = default)")
    s.add_argument("--window", default=",".join(map(str, EYE_WINDOW)))
    s.add_argument("--scale", type=int, default=1)
    s.add_argument("--vertical", action="store_true")
    s.add_argument("--out", required=True)
    a = ap.parse_args()
    if a.cmd == "measure":
        r = measure(a.img, parse_xy(a.offset), a.blur, a.overlay)
    elif a.cmd == "compare":
        r = compare(a)
    elif a.cmd == "turntable":
        r = turntable(a)
    else:
        r = strip(a)
    txt = json.dumps(r, indent=1)
    if getattr(a, "json", None):
        with open(a.json, "w") as f:
            f.write(txt + "\n")
    print(txt)


if __name__ == "__main__":
    sys.exit(main())
