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
    with open(os.path.join(run, "stage.json")) as f:
        st = json.load(f)
    rows = []
    tmp = []
    shots = [s for s in st.get("shots", []) if os.path.exists(os.path.join(run, s["shot"] + ".png"))]
    land = [s for s in shots if s["res"][0] >= s["res"][1]]
    tall = [s for s in shots if s["res"][0] < s["res"][1]]
    for group, geom, tag in ((land, "800x450+4+4", "land"), (tall, "506x900+4+4", "tall")):
        if not group:
            continue
        files = [os.path.join(run, s["shot"] + ".png") for s in group]
        labels = [f"{s['shot']}  {s['seconds']:.0f} s  {s['samples']} spp" for s in group]
        p = os.path.join(run, f".sheet_{tag}.png")
        montage(files, labels, p, f"{min(len(files), 4)}x", geom)
        rows.append(p)
    paint = [os.path.join(run, s["shot"] + "_paint.png") for s in land]
    paint = [x for x in paint if os.path.exists(x)]
    if paint:
        p = os.path.join(run, ".sheet_paint.png")
        montage(paint, [os.path.basename(x)[:-4] for x in paint], p, f"{min(len(paint), 5)}x",
                "640x360+4+4")
        rows.append(p)
    tt = st.get("turntable", [])
    for pose in dict.fromkeys(r["pose"] for r in tt):
        for kind in dict.fromkeys(r["pass"] for r in tt):
            sel = [r for r in tt if r["pose"] == pose and r["pass"] == kind]
            p = os.path.join(run, f".sheet_tt_{pose}_{kind}.png")
            montage([os.path.join(run, r["file"]) for r in sel],
                    [f"{pose} {r['view']} {kind} {r['seconds']:.0f} s" for r in sel], p, f"{len(sel)}x",
                    "240x360+2+2")
            rows.append(p)
    tmp = list(rows)
    total = sum(s["seconds"] for s in st.get("shots", [])) + sum(r["seconds"] for r in tt)
    head = (f"hero stage  {os.path.basename(run)}   quality {st['quality']}   set {st['set']}   "
            f"render total {total / 60:.1f} min   blender {st['blender']}   "
            f"hero_only: {', '.join(st.get('hero_only') or []) or 'none'}   "
            f"render-side SSS: {', '.join(st.get('skin_sss_added') or []) or 'none'}")
    hp = os.path.join(run, ".sheet_head.png")
    subprocess.run(["magick", "-background", "#111", "-fill", "#eee", "-font", "DejaVu-Sans",
                    "-pointsize", "18", "-size", "3300x", f"caption:{head}", hp], check=True)
    subprocess.run(["magick", hp, *rows, "-background", "#111", "-gravity", "west", "-append",
                    os.path.join(run, "sheet.png")], check=True)
    for p in tmp + [hp]:
        os.remove(p)
    print(os.path.join(run, "sheet.png"))


if __name__ == "__main__":
    main(sys.argv[1])
