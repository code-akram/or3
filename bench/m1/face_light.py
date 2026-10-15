#!/usr/bin/env python3
"""Light balance on the hero portrait's face (track T25, bench/m1/v4/t25-cycles-target.md).

    python3 -I bench/m1/face_light.py lights DIR [--json OUT]
        DIR is a blender/hero/refs.py --mode lights run: the parity portrait's 100 % head crop
        (refs.HEAD_CROP, 540 x 540 at (766, 74) of 1920 x 1080) with every rig light (lights_all) and
        one light + its twins at a time (lights_<name>), scene-linear, alpha = the character.
    python3 -I bench/m1/face_light.py frame FILE [--kind exr|standard|display] [--exposure EV] [--json OUT]
        a whole portrait frame (any width; the boxes scale from 1920): a stage multilayer / plain EXR
        (scene-linear), an engine frame in the Standard view (sRGB of 2^EV x linear; EV = the shot's
        exposure, -0.6 for the portrait), or a graded display PNG (sRGB-decoded only: an AgX frame is
        not linear, so its ratio is only indicative).

Measures (scene-linear luminance, Rec.709 weights):
  * cheek lit : shadow: the mean of CHEEK["lit"] over the mean of CHEEK["shadow"] (boxes on the
    camera-left cheek, which the short key lights, and the camera-right cheek, which it does not);
    target <= 8 (checkpoint-3 T25 row).
  * per light (lights): the light's share of each cheek box, and its highlight on the head: p99 and
    the mean of the top 1 % of the character's pixels (alpha >= 0.99) in the head crop. rim / key is
    that highlight of the rim (or kicker) over the key's; target <= 1 per rim ("the rims must not
    dominate the key").
"""

import argparse
import json
import os
import sys

import numpy as np

CROP = (766, 74, 540, 540)          # x, y, w, h of the head crop in the 1920 x 1080 portrait
# boxes in the head crop (x0, y0, x1, y1): the T19 face boxes (t19-lighting.md "skin boxes")
CHEEK = {"lit": (150, 330, 210, 390), "shadow": (380, 320, 440, 380)}
OTHER = {"forehead": (200, 110, 320, 170), "under_eye_lit": (175, 300, 225, 325),
         "temple_shadow": (400, 200, 450, 260), "nose_side_shadow": (300, 330, 340, 370)}
Y = np.array([0.2126, 0.7152, 0.0722])


def read(path):
    """(h, w, 3) float64 and an alpha / character mask (or None) from an EXR (multilayer: Combined
    and IndexOB) or a PNG."""
    import OpenImageIO as oiio
    i = oiio.ImageInput.open(path)
    if not i:
        sys.exit(f"face_light: cannot read {path}")
    spec = i.spec()
    a = np.asarray(i.read_image(format="float"), dtype=np.float64)
    i.close()
    names = list(spec.channelnames)
    if a.ndim == 2:
        a = a[..., None]

    def ch(suffixes):
        for s in suffixes:
            for k, n in enumerate(names):
                if n == s or n.endswith("." + s):
                    return k
        return None
    r, g, b = ch(["Combined.R", "R"]), ch(["Combined.G", "G"]), ch(["Combined.B", "B"])
    if None in (r, g, b):
        r, g, b = 0, 1, 2
    rgb = a[..., [r, g, b]]
    m = ch(["IndexOB.X", "IndexOB.V", "IndexOB"])
    al = ch(["Combined.A", "A"])
    mask = (a[..., m] > 0.5) if m is not None else (a[..., al] >= 0.99) if al is not None else None
    return rgb, mask


def srgb_decode(x):
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def box_mean(lum, box, s=1.0, off=(0, 0)):
    x0, y0, x1, y1 = (int(round(v * s)) for v in box)
    return float(lum[y0 + off[1]:y1 + off[1], x0 + off[0]:x1 + off[0]].mean())


def boxes(lum, s=1.0, off=(0, 0)):
    out = {k: box_mean(lum, b, s, off) for k, b in CHEEK.items()}
    out.update({k: box_mean(lum, b, s, off) for k, b in OTHER.items()})
    return out


def highlight(lum, mask):
    v = lum[mask] if mask is not None and mask.any() else lum.ravel()
    p99 = float(np.percentile(v, 99))
    top = v[v >= p99]
    return {"p99": p99, "top1_mean": float(top.mean()) if top.size else p99, "px": int(v.size)}


def cmd_lights(a):
    rec = json.load(open(os.path.join(a.dir, "lights.json")))
    res = {"dir": os.path.abspath(a.dir), "crop": rec["crop"], "lights": {}}
    for tag, r in rec["lights"].items():
        rgb, mask = read(os.path.join(a.dir, r["exr"]))
        lum = rgb @ Y
        if tag == "all":
            allmask = mask
        res["lights"][tag] = {"boxes": boxes(lum), "highlight": highlight(lum, mask if tag == "all" else None)}
    am = allmask
    for tag in res["lights"]:          # highlights over the same pixels (the character in the all frame)
        rgb, _ = read(os.path.join(a.dir, rec["lights"][tag]["exr"]))
        res["lights"][tag]["highlight"] = highlight(rgb @ Y, am)
    al = res["lights"]["all"]["boxes"]
    res["cheek_lit_shadow"] = al["lit"] / max(al["shadow"], 1e-9)
    key = res["lights"].get("key", {}).get("highlight")
    res["vs_key"] = {}
    for tag, v in res["lights"].items():
        if tag in ("all", "key") or not key:
            continue
        res["vs_key"][tag] = {"p99": v["highlight"]["p99"] / max(key["p99"], 1e-9),
                              "top1_mean": v["highlight"]["top1_mean"] / max(key["top1_mean"], 1e-9)}
    res["cheek_share"] = {side: {tag: v["boxes"][side] / max(al[side], 1e-9) for tag, v in res["lights"].items()
                                 if tag != "all"} for side in CHEEK}
    out(res, a.json)
    print(f"cheek lit:shadow {res['cheek_lit_shadow']:.2f} (target <= 8)")
    for tag, v in res["vs_key"].items():
        print(f"{tag:8s} / key: p99 {v['p99']:.3f}  top1% {v['top1_mean']:.3f}")
    for side in CHEEK:
        print(f"cheek {side:6s} shares: " + "  ".join(f"{t} {s:.3f}" for t, s in sorted(res['cheek_share'][side].items())))
    return 0


def cmd_frame(a):
    rgb, _ = read(a.file)
    if a.kind == "standard":
        rgb = srgb_decode(rgb) / 2.0 ** a.exposure
    elif a.kind == "display":
        rgb = srgb_decode(rgb)
    lum = rgb @ Y
    s = lum.shape[1] / 1920.0
    off = (int(round(CROP[0] * s)), int(round(CROP[1] * s)))
    b = boxes(lum, s, off)
    res = {"file": os.path.abspath(a.file), "kind": a.kind, "scale": s, "boxes": b,
           "cheek_lit_shadow": b["lit"] / max(b["shadow"], 1e-9)}
    out(res, a.json)
    print(f"{os.path.basename(a.file)}: cheek lit:shadow {res['cheek_lit_shadow']:.2f} "
          f"(lit {b['lit']:.4f}, shadow {b['shadow']:.4f}; {a.kind})")
    return 0


def out(res, path):
    if path:
        with open(path, "w") as f:
            json.dump(res, f, indent=1)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="face_light.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("lights")
    p.add_argument("dir")
    p.add_argument("--json")
    f = sub.add_parser("frame")
    f.add_argument("file")
    f.add_argument("--kind", choices=["exr", "standard", "display"], default="exr")
    f.add_argument("--exposure", type=float, default=-0.6)
    f.add_argument("--json")
    a = ap.parse_args(argv)
    return {"lights": cmd_lights, "frame": cmd_frame}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
