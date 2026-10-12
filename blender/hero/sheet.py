#!/usr/bin/env python3
"""Contact sheet for a hero-stage run (plain Python + ImageMagick).

    python3 -I blender/hero/sheet.py RUN

Reads RUN/stage.json and RUN/grade.json; writes RUN/sheet.png: a header,
the graded shots (label: shot, render seconds), the painterly A/B row, and
the turntable rows (beauty, clay, normal per pose).
"""

import json
import os
import subprocess
import sys


def montage(files, labels, out, tile, geom):
    args = ["montage", "-background", "#111", "-fill", "#ddd", "-font", "DejaVu-Sans", "-pointsize", "14"]
    for f, lab in zip(files, labels):
        args += ["-label", lab, f]
    args += ["-tile", tile, "-geometry", geom, "-type", "TrueColor", "-depth", "8", out]
    subprocess.run(args, check=True)


def main(run):
    run = os.path.abspath(run)
    with open(os.path.join(run, "stage.json")) as f:
        st = json.load(f)
    rows = []
    tmp = []
    shots = [s for s in st.get("shots", []) if os.path.exists(os.path.join(run, s["shot"] + ".png"))]
    land = [s for s in shots if s["res"][0] >= s["res"][1]]
    tall = [s for s in shots if s["res"][0] < s["res"][1]]
    block = []
    for group, geom, tag in ((land, "800x450+4+4", "land"), (tall, "540x960+4+4", "tall")):
        if not group:
            continue
        files = [os.path.join(run, s["shot"] + ".png") for s in group]
        labels = [f"{s['shot']}  {s['seconds']:.0f} s  {s['samples']} spp" for s in group]
        p = os.path.join(run, f".sheet_{tag}.png")
        montage(files, labels, p, f"{min(len(files), 3)}x" if tag == "land" else f"{len(files)}x", geom)
        block.append(p)
    if block:
        # landscape grid with the poster(s) to its right, both at the grid height
        p = os.path.join(run, ".sheet_block.png")
        h = subprocess.run(["magick", "identify", "-format", "%h", block[0]], capture_output=True,
                           text=True, check=True).stdout.strip()
        subprocess.run(["magick", block[0], *(["(", block[1], "-resize", f"x{h}", ")"] if len(block) > 1 else []),
                        "-background", "#111", "+append", p], check=True)
        rows.append(p)
        tmp += block
    paint = [os.path.join(run, s["shot"] + "_paint.png") for s in land]
    paint = [x for x in paint if os.path.exists(x)]
    if paint:
        p = os.path.join(run, ".sheet_paint.png")
        montage(paint, [os.path.basename(x)[:-4] for x in paint], p, f"{min(len(paint), 5)}x",
                "640x360+4+4")
        rows.append(p)
    tt = st.get("turntable", [])
    tdir = os.path.join(run, "turntable")
    if not tt and os.path.isdir(tdir):  # an interrupted run: list what is on disk
        for f in sorted(os.listdir(tdir)):
            parts = f[:-4].split("_")
            if f.endswith(".png") and len(parts) >= 2:
                tt.append({"file": "turntable/" + f, "pose": parts[0], "view": parts[1],
                           "pass": parts[2] if len(parts) > 2 else "beauty", "seconds": 0.0})
        order = {f"tt{a}": i for i, a in enumerate(range(0, 360, 45))}
        tt.sort(key=lambda r: (r["pose"], r["pass"], order.get(r["view"], 99)))
    for pose in dict.fromkeys(r["pose"] for r in tt):
        for kind in dict.fromkeys(r["pass"] for r in tt):
            sel = [r for r in tt if r["pose"] == pose and r["pass"] == kind]
            p = os.path.join(run, f".sheet_tt_{pose}_{kind}.png")
            montage([os.path.join(run, r["file"]) for r in sel],
                    [f"{pose} {r['view']} {kind} {r['seconds']:.0f} s" for r in sel], p, f"{len(sel)}x",
                    "240x360+2+2")
            rows.append(p)
    tmp += rows
    total = sum(s["seconds"] for s in st.get("shots", [])) + sum(r["seconds"] for r in tt)
    head = (f"hero stage  {os.path.basename(run)}   quality {st['quality']}   set {st['set']}   "
            f"render total {total / 60:.1f} min   blender {st['blender']}   "
            f"hero_only: {', '.join(st.get('hero_only') or []) or 'none'}   "
            f"render-side SSS: {', '.join(st.get('skin_sss_added') or []) or 'none'}")
    hp = os.path.join(run, ".sheet_head.png")
    subprocess.run(["magick", "-background", "#111", "-fill", "#eee", "-font", "DejaVu-Sans",
                    "-pointsize", "18", "-size", "3300x", f"caption:{head}", hp], check=True)
    subprocess.run(["magick", hp, *rows, "-background", "#111", "-gravity", "west", "-append", "+repage", "-depth", "8",
                    os.path.join(run, "sheet.png")], check=True)
    for p in tmp + [hp]:
        os.remove(p)
    print(os.path.join(run, "sheet.png"))


if __name__ == "__main__":
    main(sys.argv[1])
