"""Finalise a look-dev run, or compare two runs (stdlib + ffmpeg; no Blender).

    python3 -I bench/m1/lookdev_report.py finalize RUN --label L [--process-s S]
    python3 -I bench/m1/lookdev_report.py compare A B --out DIR
    python3 -I bench/m1/lookdev_report.py engine RUN [--cycles HERO_DIR] [--crop x,y,w,h]

When RUN has game_<view>.png (bench/m1/engine_shots.sh), sheet.png gets an
engine row under the EEVEE views; `engine` draws RUN/engine_sheet.png: EEVEE
views, engine views, and the hero portrait Cycles target vs engine.

finalize merges build stats (character.stats.json), glTF validation
(glbstats.json) and render metrics (render_metrics.json) into RUN/metrics.json
and draws RUN/sheet.png. compare writes DIR/compare.{json,md} (every numeric
metric: A, B, delta) and DIR/sheet.png: both sheets stacked plus per-view
mask overlays (white = both, red = only A, cyan = only B).
"""

import argparse
import json
import os
import subprocess
import sys

VIEWS = ["front", "three_quarter", "profile", "closeup"]
FACE_VIEWS = ["face_front", "face_profile"]  # mask-only (body + eyes), IoU only
TILE = 512


def font():
    try:
        return subprocess.run(["fc-match", "-f", "%{file}", "monospace"], check=True,
                              capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def ffmpeg(args):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *args], check=True)


def drawtext(textfile, size, x="12", y="12"):
    f = font()
    ff = f"fontfile='{f}':" if f else ""
    return (f"drawtext={ff}textfile='{textfile}':expansion=none:fontsize={size}:"
            f"fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=6:x={x}:y={y}")


def load(path):
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def fmt(v):
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.3f}"
    return str(v)


# ---------------------------------------------------------------- finalize

def finalize(a):
    run = os.path.abspath(a.run)
    build = load(os.path.join(run, "character.stats.json"))
    glb = load(os.path.join(run, "glbstats.json"))
    rm = load(os.path.join(run, "render_metrics.json"))
    if not rm:
        sys.exit(f"no render_metrics.json in {run}")
    val = glb.get("validation", {})
    glb_max_w = max((int(k) for m in glb.get("meshes", [])
                     for k, n in (m.get("weightsPerVertex") or {}).items() if n),
                    default=None)
    frames = rm["render"]["frames"]
    beauty = [f["seconds"] for f in frames if f["pass"] == "beauty"]
    metrics = {
        "label": a.label,
        "run": os.path.basename(run),
        "mode": rm["mode"],
        "tris": rm["tris"],
        "bones": rm["bones"],
        "max_weights_per_vertex": glb_max_w if glb_max_w is not None else rm["max_weights_per_vertex"],
        # Spec landmarks (look-spec §1.1, nude body, measured in the build) and
        # their pass/fail; joint-based landmarks of the shipped GLB as context.
        "landmarks": build.get("spec_landmarks") or {},
        "spec_checks": build.get("spec_checks") or {},
        "read40": rm.get("read40"),
        "landmarks_glb": rm.get("landmarks_glb", rm.get("landmarks")),
        "head_edits": build.get("head_edits"),
        # Face-C fidelity stage (head_refine / skin_tex / eyes_hq): subdivision,
        # re-planarisation, sculpt, UV re-pack, generated skin and eye stats.
        "refine": {k: build.get(k) for k in ("head_refine", "skin", "eyes") if build.get(k)} or None,
        "detail_strip": rm.get("detail_strip"),
        "silhouette": rm["silhouette"],
        "iou_target": rm["iou_target"],
        "iou_prev": rm["iou_prev"],
        "prev_run": os.path.basename(rm["prev_run"]) if rm.get("prev_run") else None,
        "gltf_validator": {"errors": val.get("errors"), "warnings": val.get("warnings")},
        "glb_bytes": build.get("glb_bytes"),
        "decimated": build.get("decimated"),
        "timings_s": {
            "build_stages": build.get("timings_s"),
            "build_in_blender": build.get("total_s"),
            "render_per_view": dict(zip([f["view"] for f in frames if f["pass"] == "beauty"], beauty)),
            "render_beauty_mean": round(sum(beauty) / len(beauty), 3) if beauty else None,
            "mask_total": round(sum(f["seconds"] for f in frames if f["pass"] == "mask"), 3),
            "render_import_metrics": rm.get("timings_s"),
            "process_total": a.process_s,
        },
        "render": {k: rm["render"][k] for k in ("engine", "res", "mask_res", "gpu") if k in rm["render"]},
        "config": build.get("config"),
    }
    with open(os.path.join(run, "metrics.json"), "w") as f:
        json.dump(metrics, f, indent=2)
    sheet(run, metrics)
    summary(metrics)


def spec_line(m):
    """Spec checks as 'name value(+/-)': + = within tolerance, ! = outside."""
    ch = m.get("spec_checks") or {}
    short = {"stature": "stat", "heads_tall": "heads", "bideltoid": "bidelt",
             "shoulder_to_hip": "sh:hip", "leg_ratio": "leg", "leg_to_torso": "leg:tor",
             "bizygomatic": "bizyg", "jaw_to_cheek": "jaw:chk", "lower_face_index": "lfi",
             "brow_overhang": "brow", "nose_hump_mm": "hump", "nose_proj_ratio": "nose"}
    parts = []
    for k, c in ch.items():
        v = c["value"] * 1000 if k == "brow_overhang" else c["value"]
        parts.append(f"{short.get(k, k)} {v:.3g}{'+' if c['ok'] else '!'}")
    fails = sum(1 for c in ch.values() if not c["ok"])
    return "spec  " + "  ".join(parts) + f"   ({fails} out)"


def read_line(m):
    r = m.get("read40") or {}
    if "eye_band_darker" not in r:
        return "read40 " + str(r.get("skipped", "-"))
    s = f"read40 eye band {100 * r['eye_band_darker']:.0f}% darker{'+' if r['eye_band_ok'] else '!'}"
    if "beard_contrast" in r:
        s += f"   beard {100 * r['beard_contrast']:.0f}%{'+' if r['beard_ok'] else '!'}"
    else:
        s += "   beard -"
    return s + f"   (head {r['head_px']} px)"


def header_text(m):
    iou_p = m["iou_prev"] or {}
    iou_t = m["iou_target"] or {}
    lines = [
        f"{m['label']}   {m['run']}   mode {m['mode']}   "
        f"tris {m['tris']['total']}   bones {m['bones']}   w/v {m['max_weights_per_vertex']}   "
        f"gltf errors {fmt(m['gltf_validator']['errors'])}",
        spec_line(m),
        read_line(m),
        "IoU prev  " + "  ".join(f"{v} {fmt(iou_p.get(v))}" for v in VIEWS + FACE_VIEWS)
        + ("   IoU target  " + "  ".join(f"{v} {fmt(iou_t.get(v))}" for v in VIEWS) if iou_t else ""),
    ]
    return "\n".join(lines)


def sheet(run, m):
    txt = os.path.join(run, "sheet_header.txt")
    with open(txt, "w") as f:
        f.write(header_text(m))
    inputs, chains = [], []
    for i, v in enumerate(VIEWS):
        inputs += ["-i", os.path.join(run, f"{v}.png")]
        vt = os.path.join(run, f"sheet_{v}.txt")
        with open(vt, "w") as f:
            f.write(v)
        chains.append(f"[{i}]scale={TILE}:{TILE},{drawtext(vt, 18)}[b{i}]")
    for i, v in enumerate(VIEWS):
        inputs += ["-i", os.path.join(run, f"{v}_mask.png")]
        chains.append(f"[{i + 4}]scale={TILE // 2}:{TILE // 2},pad={TILE}:{TILE // 2}:{TILE // 4}:0[m{i}]")
    # Engine row (T5): the game frames (bench/m1/engine_shots.sh) under the EEVEE views, when present.
    game = all(os.path.exists(os.path.join(run, f"game_{v}.png")) for v in VIEWS)
    if game:
        for i, v in enumerate(VIEWS):
            inputs += ["-i", os.path.join(run, f"game_{v}.png")]
            with open(os.path.join(run, f"sheet_game_{v}.txt"), "w") as f:
                f.write(f"engine {v}")
            chains.append(f"[{i + 8}]scale={TILE}:{TILE},{drawtext(os.path.join(run, f'sheet_game_{v}.txt'), 18)}[e{i}]")
    rows = "[top][eng][bot]vstack=3[g]" if game else "[top][bot]vstack[g]"
    fc = ";".join(chains) + (
        ";[b0][b1][b2][b3]hstack=4[top];[m0][m1][m2][m3]hstack=4[bot];"
        + ("[e0][e1][e2][e3]hstack=4[eng];" if game else "") + rows + ";"
        f"[g]pad=iw:ih+108:0:108,{drawtext(txt, 18, y='8')}")
    ffmpeg([*inputs, "-filter_complex", fc, os.path.join(run, "sheet.png")])
    for v in VIEWS:
        os.remove(os.path.join(run, f"sheet_{v}.txt"))
        if game:
            os.remove(os.path.join(run, f"sheet_game_{v}.txt"))


def engine_sheet(a):
    """RUN/engine_sheet.png: EEVEE views over engine views, then the hero portrait as Cycles target
    vs engine (same camera, rig and pose by data: blender/hero/export_rig.py), whole frame and a
    face crop at 100 %. Writes into RUN only."""
    run = os.path.abspath(a.run)
    gs = load(os.path.join(run, "game_shots.json"))
    if not gs.get("ok"):
        sys.exit(f"no successful game_shots.json in {run}")
    rows, inputs, chains = [], [], []

    def label(text, key):
        p = os.path.join(run, f"esheet_{key}.txt")
        with open(p, "w") as f:
            f.write(text)
        return p

    labels = []
    n = 0
    for src, tag in (("{v}.png", "eevee"), ("game_{v}.png", "engine")):
        names = []
        for v in VIEWS:
            path = os.path.join(run, src.format(v=v))
            if not os.path.exists(path):
                break
            inputs += ["-i", path]
            lp = label(f"{tag} {v}", f"{tag}_{v}")
            labels.append(lp)
            chains.append(f"[{n}]scale={TILE}:{TILE},{drawtext(lp, 18)}[t{n}]")
            names.append(f"[t{n}]")
            n += 1
        if len(names) == len(VIEWS):
            chains.append("".join(names) + f"hstack={len(VIEWS)}[r{len(rows)}]")
            rows.append(f"[r{len(rows)}]")
    W = TILE * len(VIEWS)
    cyc = os.path.join(a.cycles, "portrait.png") if a.cycles else None
    game_p = os.path.join(run, "game_portrait.png")
    if os.path.exists(game_p):
        pair = []
        x, y, w, h = (int(c) for c in a.crop.split(","))
        for path, tag in ((cyc, "cycles target"), (game_p, "engine")):
            if not path or not os.path.exists(path):
                continue
            inputs += ["-i", path]
            lp = label(f"{tag} portrait", f"p_{len(pair)}")
            lc = label(f"{tag} face 100 %", f"c_{len(pair)}")
            labels += [lp, lc]
            chains.append(f"[{n}]scale=1920:1080,split[s{n}a][s{n}b]")
            chains.append(f"[s{n}a]scale={W // 2}:-2,{drawtext(lp, 18)}[pf{n}]")
            chains.append(f"[s{n}b]crop={w}:{h}:{x}:{y},scale={W // 2}:-2,{drawtext(lc, 18)}[pc{n}]")
            pair.append(n)
            n += 1
        if len(pair) == 2:
            chains.append(f"[pf{pair[0]}][pf{pair[1]}]hstack[r{len(rows)}]")
            rows.append(f"[r{len(rows)}]")
            chains.append(f"[pc{pair[0]}][pc{pair[1]}]hstack[r{len(rows)}]")
            rows.append(f"[r{len(rows)}]")
        elif pair:
            chains.append(f"[pf{pair[0]}]pad={W}:ih[r{len(rows)}]")
            rows.append(f"[r{len(rows)}]")
    st = gs.get("stats", {})
    ver = gs.get("verify", {})
    head = (f"engine vs EEVEE vs Cycles   {os.path.basename(run)}   backend {gs.get('backend')} "
            f"({(gs.get('adapter') or {}).get('description') or '-'})   {gs.get('browser', '')}\n"
            f"load {gs.get('load', {}).get('load_ms')} ms ({gs.get('load', {}).get('glb_mb')} MB GLB)   "
            f"tris {st.get('tris_model')}   draws {[s.get('draw_calls') for s in gs.get('shots', [])]}   "
            f"textures {st.get('textures')} ~{st.get('texture_mb_est')} MB   "
            f"rig.json vs Blender: corrective max diff {ver.get('corrective_max_abs_diff')}, "
            f"helper max {ver.get('helper_max_angle_deg')} deg\n"
            f"cycles: {a.cycles or '-'}")
    ht = label(head, "header")
    labels.append(ht)
    fc = ";".join(chains) + ";" + "".join(rows) + f"vstack={len(rows)}[g];" \
        + f"[g]pad=iw:ih+84:0:84,{drawtext(ht, 18, y='8')}"
    if len(rows) == 1:
        fc = fc.replace(f"{rows[0]}vstack=1[g]", f"{rows[0]}null[g]")
    out = os.path.join(run, "engine_sheet.png")
    ffmpeg([*inputs, "-filter_complex", fc, out])
    for p in labels:
        os.remove(p)
    print(f"-> {out}")


def summary(m):
    t = m["timings_s"]
    print(header_text(m))
    print(f"build {fmt(t['build_in_blender'])} s in Blender; beauty "
          f"{' '.join(fmt(x) for x in t['render_per_view'].values())} s/view "
          f"(mean {fmt(t['render_beauty_mean'])}); masks {fmt(t['mask_total'])} s; "
          f"process total {fmt(t['process_total'])} s")


# ---------------------------------------------------------------- compare

def flatten(d, prefix=""):
    out = {}
    for k, v in (d or {}).items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(flatten(v, key + "."))
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            out[key] = v
    return out


SKIP = ("timings_s.", "config.", "glb_bytes")


def compare(a):
    A, B = os.path.abspath(a.a), os.path.abspath(a.b)
    ma, mb = load(os.path.join(A, "metrics.json")), load(os.path.join(B, "metrics.json"))
    if not ma or not mb:
        sys.exit("both runs need metrics.json (finalised runs)")
    fa, fb = flatten(ma), flatten(mb)
    rows = []
    for k in sorted(set(fa) | set(fb)):
        if k.startswith(SKIP):
            continue
        va, vb = fa.get(k), fb.get(k)
        d = round(vb - va, 4) if va is not None and vb is not None else None
        rows.append({"metric": k, "a": va, "b": vb, "delta": d})
    os.makedirs(a.out, exist_ok=True)
    res = {"a": ma["run"], "b": mb["run"], "rows": rows,
           "config_a": ma.get("config"), "config_b": mb.get("config")}
    with open(os.path.join(a.out, "compare.json"), "w") as f:
        json.dump(res, f, indent=2)
    md = [f"# {ma['label']} ({ma['run']}) vs {mb['label']} ({mb['run']})", "",
          "| metric | A | B | delta |", "|---|---|---|---|"]
    md += [f"| {r['metric']} | {fmt(r['a'])} | {fmt(r['b'])} | {fmt(r['delta'])} |"
           for r in rows if r["delta"] not in (0, 0.0)]
    md += ["", f"{sum(1 for r in rows if r['delta'] in (0, 0.0))} unchanged metrics omitted."]
    with open(os.path.join(a.out, "compare.md"), "w") as f:
        f.write("\n".join(md) + "\n")

    inputs, chains = ["-i", os.path.join(A, "sheet.png"), "-i", os.path.join(B, "sheet.png")], []
    for i, v in enumerate(VIEWS):
        inputs += ["-i", os.path.join(A, f"{v}_mask.png"), "-i", os.path.join(B, f"{v}_mask.png")]
        ia, ib = 2 + 2 * i, 3 + 2 * i
        # gbrp planes: G and B from B's mask, R from A's -> A only red, B only cyan.
        chains.append(f"[{ia}]format=gray[a{i}];[{ib}]format=gray,split[b{i}x][b{i}y];"
                      f"[b{i}x][b{i}y][a{i}]mergeplanes=0x001020:gbrp,"
                      f"scale={TILE}:{TILE}[o{i}]")
    fc = ";".join(chains) + ";[o0][o1][o2][o3]hstack=4[ov];[0][1][ov]vstack=3"
    ffmpeg([*inputs, "-filter_complex", fc, os.path.join(a.out, "sheet.png")])
    print("\n".join(md))
    print(f"-> {a.out}/sheet.png")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("finalize")
    f.add_argument("run")
    f.add_argument("--label", required=True)
    f.add_argument("--process-s", type=float)
    c = sub.add_parser("compare")
    c.add_argument("a")
    c.add_argument("b")
    c.add_argument("--out", required=True)
    e = sub.add_parser("engine", help="engine vs EEVEE vs Cycles sheet (RUN/engine_sheet.png)")
    e.add_argument("run")
    e.add_argument("--cycles", help="hero stage dir with portrait.png (the Cycles target)")
    e.add_argument("--crop", default="720,90,600,600",
                   help="face crop x,y,w,h in the 1920x1080 portrait (same camera in both)")
    a = ap.parse_args()
    {"finalize": finalize, "compare": compare, "engine": engine_sheet}[a.cmd](a)


if __name__ == "__main__":
    main()
