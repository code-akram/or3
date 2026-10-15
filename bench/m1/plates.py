#!/usr/bin/env python3
"""Blind plate sheets: the realism row of the two-tier gate (bench/m1/v4/checkpoint-3.md §3.2, track T25).

A sheet is 6 tiles at identical crop and size in a 3 x 2 grid, labelled A-F only: the engine hero
closeup, the Cycles hero crop, and 3-4 lighting/material plates (photographs of anonymous bearded men
under a hard key plus a coloured rim, at a similar lens). The tile order is shuffled per sheet; the
answer key goes to a separate file in a separate directory, so the judge can open the sheets without
seeing it. The question for the judge (the user) is "which tiles are renders?"; `score` turns the
answers into the gate number: the engine tile must be picked as a render no more often than a plate,
across >= 6 sheets with different plates each time.

    python3 -I bench/m1/plates.py sheet --engine ENGINE.png[@x,y] --cycles CYCLES.png[@x,y] \\
        [--plates DIR] [--slots 4] [--sheets 6] [--tile 540] [--seed N] [--label NAME] \\
        [--placeholder grey | --placeholder FILE.png[@x,y] ...] [--out DIR]
    python3 -I bench/m1/plates.py check [--plates DIR]
    python3 -I bench/m1/plates.py record FILE --author A --source-url U --download-url U \\
        [--licence CC0-1.0] [--title T]          # prints a provenance line for FILE (sha256 filled in)
    python3 -I bench/m1/plates.py score --key KEY.json --answers ANSWERS.json

Tiles:
  * render tiles (--engine, --cycles, and Cycles placeholders) are cut at 100 %: a tile x tile window
    of the frame, never resampled. `@x,y` is the window's top-left in the frame; without it the window
    is centred. The T19/T25 head crop of the 1920 x 1080 portrait is `@766,74` with --tile 540.
  * plates are photographs at their own resolution: centre-cropped to a square, or to the box in an
    optional sidecar `<plate file>.crop.json` ({"box": [x, y, size]}, chosen by a person), then
    resampled to the tile size. That box is the only thing ever chosen on a plate; nothing measures it.

Plates (rules from checkpoint-3 §3.2; they hold for every use of this script):
  * live in bench/ref/plates/ of the main checkout (gitignored; tools/hooks/check_staged.py also
    refuses any staged path under it), never in git, never in data/ or a build;
  * are lighting/material comparisons only: never a face or form target, never an input of any
    fitting, measuring, calibration or training step. This script only crops, resamples and shuffles
    them; no other script in the repo may read bench/ref/plates/;
  * are never the actor and never a likeness reference (those stay in private/, offline);
  * need a licence record: one line per plate in provenance/plates.jsonl, id `plate:<file name>`,
    licence CC0-1.0 or LicenseRef-PDM-1.0 (public domain only), status "accepted", sha256 of the
    local file. provenance/plates.template.json is the template; `record` fills it for a file.
    provenance/audit.py checks the line like any other record. A plate file without an accepted
    record whose sha256 matches is skipped by `sheet` and reported by `check`.

How plates get added (only after the user approves collecting them; HANDOFF "Plate test"):
  1. The user, or an agent the user asked, picks CC0 / public-domain photographs: an anonymous man
     with a beard, hard key plus a coloured rim, head and shoulders, 50-135 mm equivalent, sharp at
     100 % over a ~540 px head. Different plates for each sheet (>= 3-4 per sheet, >= 6 sheets).
  2. Save each file under bench/ref/plates/ (original bytes, as downloaded).
  3. `plates.py record FILE --author ... --source-url ... --download-url ...` prints the provenance
     line; check the licence on the source page, set status "accepted", append it to
     provenance/plates.jsonl, and run `python3 -I provenance/audit.py`.
  4. Optional: `<file>.crop.json` with the square head box, if the centre crop is wrong.
  5. `plates.py check`, then `plates.py sheet ...`.

Without plates (or to test the harness) --placeholder fills the plate slots: `grey` (a flat 18 % grey
card with sensor-like noise) or a frame cut like a render tile (e.g. a Cycles variant). The key marks
them as placeholders; a sheet with placeholders is a harness test, not a gate result.

Outputs (default <main>/data/build/plates/<UTC>-<label>/, gitignored): sheet_NN.png (the blind
sheets), answers_template.json (for the judge), and key/answer_key.json (per sheet, tile letter ->
kind and source, plus the seed). Writes nowhere else.
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import random
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
PLATE_LICENCES = ("CC0-1.0", "LicenseRef-PDM-1.0")
PLATE_EXT = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp")
LETTERS = "ABCDEF"
GRID = (3, 2)   # columns, rows
GAP, BAR = 12, 40
BG = 0.08


def main_root():
    try:
        common = subprocess.run(["git", "-C", REPO, "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                capture_output=True, check=True, text=True).stdout.strip()
        return os.path.dirname(common)
    except (OSError, subprocess.CalledProcessError):
        return REPO


def default_plates():
    return os.path.join(main_root(), "bench", "ref", "plates")


def manifest_path():
    return os.path.join(REPO, "provenance", "plates.jsonl")


# ------------------------------------------------------------------ image io
def read_rgb(path):
    """(h, w, 3) float32 display-referred 0..1 (the file's own encoding: sRGB PNG / JPEG)."""
    import OpenImageIO as oiio
    i = oiio.ImageInput.open(path)
    if not i:
        sys.exit(f"plates: cannot read {path}: {oiio.geterror()}")
    a = np.asarray(i.read_image(format="float"), dtype=np.float32)
    i.close()
    if a.ndim == 2:
        a = a[..., None]
    if a.shape[-1] == 1:
        a = np.repeat(a, 3, -1)
    return a[..., :3]


def write_png(path, a):
    import OpenImageIO as oiio
    a = np.ascontiguousarray(np.clip(a, 0, 1), dtype=np.float32)
    h, w, c = a.shape
    o = oiio.ImageOutput.create(path)
    if not o or not o.open(path, oiio.ImageSpec(w, h, c, "uint8")):
        sys.exit(f"plates: cannot write {path}")
    o.write_image(a)
    o.close()


def resize(a, size):
    import OpenImageIO as oiio
    h, w, c = a.shape
    src = oiio.ImageBuf(oiio.ImageSpec(w, h, c, "float"))
    src.set_pixels(oiio.ROI(0, w, 0, h, 0, 1, 0, c), np.ascontiguousarray(a, dtype=np.float32))
    dst = oiio.ImageBuf(oiio.ImageSpec(size, size, c, "float"))
    oiio.ImageBufAlgo.resize(dst, src, filtername="lanczos3")
    return np.asarray(dst.get_pixels(oiio.FLOAT), dtype=np.float32).reshape(size, size, c)


# ------------------------------------------------------------------ tiles
def parse_at(spec):
    """'file.png@x,y' -> (file, (x, y)) or (file, None)."""
    if "@" in spec:
        f, at = spec.rsplit("@", 1)
        x, y = (int(v) for v in at.split(","))
        return f, (x, y)
    return spec, None


def render_tile(spec, tile):
    """A tile x tile window of a render at 100 % (never resampled)."""
    f, at = parse_at(spec)
    a = read_rgb(f)
    h, w, _ = a.shape
    if h < tile or w < tile:
        sys.exit(f"plates: {f} is {w}x{h}, smaller than the {tile} px tile (render tiles are never resampled)")
    x, y = at if at else ((w - tile) // 2, (h - tile) // 2)
    if not (0 <= x <= w - tile and 0 <= y <= h - tile):
        sys.exit(f"plates: window @{x},{y} + {tile} px is outside {f} ({w}x{h})")
    return a[y:y + tile, x:x + tile].copy(), {"file": os.path.abspath(f), "window": [x, y, tile, tile], "scale": 1.0}


def plate_tile(path, tile):
    """A plate: the square box from <file>.crop.json, else the centre square, resampled to the tile."""
    a = read_rgb(path)
    h, w, _ = a.shape
    side = path + ".crop.json"
    if os.path.exists(side):
        x, y, s = json.load(open(side))["box"]
    else:
        s = min(h, w)
        x, y = (w - s) // 2, (h - s) // 2
    x, y, s = int(x), int(y), int(s)
    if not (s > 0 and 0 <= x <= w - s and 0 <= y <= h - s):
        sys.exit(f"plates: crop box {x},{y},{s} is outside {path} ({w}x{h})")
    return resize(a[y:y + s, x:x + s], tile), {"file": os.path.basename(path), "box": [x, y, s],
                                               "scale": round(tile / s, 4)}


def grey_tile(tile, rng):
    """A placeholder plate: 18 % grey card (display 0.46) with mild luminance and chroma noise."""
    base = 0.461
    n = rng.normal(0, 0.012, (tile, tile, 1)) + rng.normal(0, 0.004, (tile, tile, 3))
    yy, xx = np.mgrid[0:tile, 0:tile] / tile - 0.5
    vig = 1.0 - 0.25 * (xx ** 2 + yy ** 2)
    return np.clip(base * vig[..., None] + n, 0, 1).astype(np.float32), {"file": "grey18", "scale": 1.0}


# ------------------------------------------------------------------ plates and records
def load_records(p=None):
    p = p or manifest_path()
    out = {}
    if not os.path.exists(p):
        return out
    for i, line in enumerate(open(p), 1):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        out[r["id"]] = dict(r, _line=i)
    return out


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def plate_status(plates_dir, manifest=None):
    """[(file, ok, reason)] for every image file in the plate dir."""
    recs = load_records(manifest)
    out = []
    if not os.path.isdir(plates_dir):
        return out
    for f in sorted(os.listdir(plates_dir)):
        if not f.lower().endswith(PLATE_EXT):
            continue
        p = os.path.join(plates_dir, f)
        r = recs.get(f"plate:{f}")
        if r is None:
            out.append((p, False, "no record plate:%s in provenance/plates.jsonl" % f))
        elif r.get("licence") not in PLATE_LICENCES:
            out.append((p, False, f"licence {r.get('licence')!r} is not public domain ({', '.join(PLATE_LICENCES)})"))
        elif r.get("status") != "accepted":
            out.append((p, False, f"record status {r.get('status')!r}, not 'accepted'"))
        elif r.get("sha256") != sha256(p):
            out.append((p, False, "sha256 differs from the record (re-downloaded or edited?)"))
        else:
            out.append((p, True, "ok"))
    return out


def cmd_check(a):
    st = plate_status(a.plates, a.manifest)
    if not st:
        print(f"plates: no plate files in {a.plates}")
        return 0
    for p, ok, why in st:
        print(f"{'ok  ' if ok else 'SKIP'} {os.path.basename(p)}: {why}")
    good = sum(ok for _, ok, _ in st)
    print(f"plates: {good} usable of {len(st)}")
    return 0 if good == len(st) else 1


def cmd_record(a):
    tpl = json.load(open(os.path.join(REPO, "provenance", "plates.template.json")))
    f = os.path.basename(a.file)
    lic = a.licence
    urls = {"CC0-1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
            "LicenseRef-PDM-1.0": "https://creativecommons.org/publicdomain/mark/1.0/"}
    if lic not in PLATE_LICENCES:
        sys.exit(f"plates: plates must be public domain ({', '.join(PLATE_LICENCES)}), not {lic}")
    rec = dict(tpl)
    rec.update({"id": f"plate:{f}", "title": a.title or f, "licence": lic, "licence_url": urls[lic],
                "author": a.author, "source_url": a.source_url, "download_url": a.download_url,
                "retrieved_or_built": dt.date.today().isoformat(), "bytes": os.path.getsize(a.file),
                "sha256": sha256(a.file), "status": "pending"})
    if lic == "LicenseRef-PDM-1.0":
        rec["licence_note"] = "Public Domain Mark: accepted by a person after checking the source page."
    else:
        rec.pop("licence_note", None)
    print(json.dumps(rec, ensure_ascii=False))
    print("plates: check the licence on the source page, set status to \"accepted\", append the line to "
          "provenance/plates.jsonl, then run python3 -I provenance/audit.py", file=sys.stderr)
    return 0


# ------------------------------------------------------------------ sheet
# 5 x 7 bitmap glyphs for the tile labels (no font dependency)
GLYPHS = {
    "A": ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    "B": ["11110", "10001", "10001", "11110", "10001", "10001", "11110"],
    "C": ["01111", "10000", "10000", "10000", "10000", "10000", "01111"],
    "D": ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
    "E": ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    "F": ["11111", "10000", "10000", "11110", "10000", "10000", "10000"],
}


def stamp(img, ch, x, y, px=4, val=0.9):
    for r, row in enumerate(GLYPHS[ch]):
        for c, bit in enumerate(row):
            if bit == "1":
                img[y + r * px:y + (r + 1) * px, x + c * px:x + (c + 1) * px] = val


def compose(tiles, tile):
    cols, rows = GRID
    W = cols * tile + (cols + 1) * GAP
    H = rows * (tile + BAR) + (rows + 1) * GAP
    sheet = np.full((H, W, 3), BG, np.float32)
    for i, t in enumerate(tiles):
        c, r = i % cols, i // cols
        x = GAP + c * (tile + GAP)
        y = GAP + r * (tile + BAR + GAP)
        sheet[y:y + tile, x:x + tile] = t
        stamp(sheet, LETTERS[i], x + tile // 2 - 10, y + tile + (BAR - 28) // 2)
    return sheet


def cmd_sheet(a):
    tile = a.tile
    seed = a.seed if a.seed is not None else random.SystemRandom().randrange(1 << 31)
    rng = np.random.default_rng(seed)
    pick = random.Random(seed)
    if a.slots not in (3, 4):
        sys.exit("plates: --slots is 3 or 4 (6 tiles: engine, Cycles, plates, and with 3 plates one more "
                 "placeholder or render variant)")
    st = plate_status(a.plates, a.manifest)
    usable = [p for p, ok, _ in st if ok]
    skipped = [(os.path.basename(p), why) for p, ok, why in st if not ok]
    for f, why in skipped:
        print(f"plates: skipping {f}: {why}", file=sys.stderr)
    placeholders = a.placeholder or []
    need = a.slots * a.sheets
    if len(usable) < a.slots and not placeholders:
        sys.exit(f"plates: {len(usable)} usable plates in {a.plates}, a sheet needs {a.slots}; add plates (see the "
                 "docstring) or pass --placeholder for a harness test")
    if usable and len(usable) < need:
        print(f"plates: {len(usable)} plates for {a.sheets} sheets x {a.slots} slots: plates repeat across sheets "
              f"(the gate wants different plates on each sheet)", file=sys.stderr)
    engine, eng_src = render_tile(a.engine, tile)
    cyc, cyc_src = render_tile(a.cycles, tile)
    label = a.label or "sheet"
    out = os.path.abspath(a.out or os.path.join(main_root(), "data", "build", "plates",
                                                dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + label))
    if os.path.realpath(out).startswith(os.path.realpath(REPO) + os.sep) and "/data/" not in out:
        sys.exit(f"plates: --out {out} is inside the checkout; sheets hold plates, which never go in git")
    os.makedirs(os.path.join(out, "key"), exist_ok=True)
    order = list(usable)
    pick.shuffle(order)
    key = {"version": 1, "seed": seed, "tile_px": tile, "grid": list(GRID), "slots": a.slots,
           "question": "Which tiles are renders?", "plates_dir": a.plates, "skipped_plates": skipped,
           "harness_test": not usable or len(usable) < a.slots, "sheets": []}
    for s in range(a.sheets):
        tiles = [("engine", engine, eng_src), ("cycles", cyc, cyc_src)]
        chosen = [order[(s * a.slots + k) % len(order)] for k in range(min(a.slots, len(order)))] if order else []
        for p in chosen:
            t, src = plate_tile(p, tile)
            tiles.append(("plate", t, src))
        k = 0
        while len(tiles) < 6:
            ph = placeholders[k % len(placeholders)] if placeholders else "grey"
            t, src = grey_tile(tile, rng) if ph == "grey" else render_tile(ph, tile)
            tiles.append(("placeholder", t, src))
            k += 1
        perm = list(range(6))
        pick.shuffle(perm)
        tiles = [tiles[i] for i in perm]
        name = f"sheet_{s + 1:02d}.png"
        write_png(os.path.join(out, name), compose([t for _, t, _ in tiles], tile))
        key["sheets"].append({"sheet": name, "tiles": {LETTERS[i]: {"kind": kind, **src}
                                                       for i, (kind, _, src) in enumerate(tiles)}})
        print(f"plates: {name}: " + " ".join(f"{LETTERS[i]}" for i in range(6)), flush=True)
    with open(os.path.join(out, "key", "answer_key.json"), "w") as f:
        json.dump(key, f, indent=1)
    with open(os.path.join(out, "answers_template.json"), "w") as f:
        json.dump({"judge": "", "date": "", "renders": {sh["sheet"]: [] for sh in key["sheets"]},
                   "note": "per sheet, the letters you think are renders; then plates.py score"}, f, indent=1)
    print(f"plates: {a.sheets} sheets -> {out} (answer key in {os.path.join(out, 'key')}; "
          f"{'HARNESS TEST: placeholder tiles' if key['harness_test'] else 'plates: ' + str(len(usable))})")
    return 0


def cmd_score(a):
    key = json.load(open(a.key))
    ans = json.load(open(a.answers))["renders"]
    picked = {"engine": [0, 0], "cycles": [0, 0], "plate": [0, 0], "placeholder": [0, 0]}
    for sh in key["sheets"]:
        said = set(x.upper() for x in ans.get(sh["sheet"], []))
        for letter, t in sh["tiles"].items():
            picked[t["kind"]][1] += 1
            picked[t["kind"]][0] += letter in said
    rate = {k: (round(v[0] / v[1], 3) if v[1] else None) for k, v in picked.items()}
    res = {"sheets": len(key["sheets"]), "picked_as_render": {k: v[0] for k, v in picked.items()},
           "shown": {k: v[1] for k, v in picked.items()}, "rate": rate,
           "pass": bool(rate["plate"] is not None and rate["engine"] is not None and rate["engine"] <= rate["plate"]
                        and len(key["sheets"]) >= 6 and not key.get("harness_test")),
           "rule": "engine picked as a render no more often than a plate, >= 6 sheets, real plates (checkpoint-3 §3.2)"}
    print(json.dumps(res, indent=1))
    return 0 if res["pass"] else 1


def main(argv=None):
    ap = argparse.ArgumentParser(prog="plates.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sheet", help="blind sheets + a separate answer key")
    s.add_argument("--engine", required=True, help="engine hero frame [@x,y] (tile cut at 100 %%)")
    s.add_argument("--cycles", required=True, help="Cycles hero frame [@x,y] (tile cut at 100 %%)")
    s.add_argument("--plates", default=default_plates())
    s.add_argument("--manifest", default=None, help="plate licence records (default provenance/plates.jsonl)")
    s.add_argument("--slots", type=int, default=4, help="plate slots per sheet (3 or 4)")
    s.add_argument("--sheets", type=int, default=6)
    s.add_argument("--tile", type=int, default=540)
    s.add_argument("--seed", type=int, default=None, help="shuffle seed (default random; written to the key)")
    s.add_argument("--placeholder", action="append",
                   help="fill empty slots: 'grey' or a frame[@x,y] cut like a render tile (repeatable)")
    s.add_argument("--label", default="")
    s.add_argument("--out", default=None)
    c = sub.add_parser("check", help="every plate file has an accepted public-domain record")
    c.add_argument("--plates", default=default_plates())
    c.add_argument("--manifest", default=None, help="plate licence records (default provenance/plates.jsonl)")
    r = sub.add_parser("record", help="print a provenance line for a plate file")
    r.add_argument("file")
    r.add_argument("--author", required=True)
    r.add_argument("--source-url", required=True)
    r.add_argument("--download-url", required=True)
    r.add_argument("--licence", default="CC0-1.0")
    r.add_argument("--title", default="")
    k = sub.add_parser("score", help="the gate number from a judge's answers")
    k.add_argument("--key", required=True)
    k.add_argument("--answers", required=True)
    a = ap.parse_args(argv)
    return {"sheet": cmd_sheet, "check": cmd_check, "record": cmd_record, "score": cmd_score}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
