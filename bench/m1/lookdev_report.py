"""Finalise a look-dev run, or compare two runs (stdlib + ffmpeg; no Blender).

    python3 -I bench/m1/lookdev_report.py finalize RUN --label L [--process-s S]
    python3 -I bench/m1/lookdev_report.py compare A B --out DIR

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
        "landmarks": rm["landmarks"],
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


def header_text(m):
    lm = m["landmarks"]
    iou_p = m["iou_prev"] or {}
    iou_t = m["iou_target"] or {}
    lines = [
        f"{m['label']}   {m['run']}   mode {m['mode']}   "
        f"tris {m['tris']['total']}   bones {m['bones']}   w/v {m['max_weights_per_vertex']}   "
        f"gltf errors {fmt(m['gltf_validator']['errors'])}",
        f"heads {fmt(lm.get('heads_tall'))}   stature {fmt(lm.get('stature_m'))} m   "
        f"shoulder:hip {fmt(lm.get('shoulder_to_hip'))}   leg:torso {fmt(lm.get('leg_to_torso'))}   "
        f"head w:h {fmt(lm.get('head_width_to_height'))}",
        "IoU prev  " + "  ".join(f"{v} {fmt(iou_p.get(v))}" for v in VIEWS)
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
    fc = ";".join(chains) + (
        ";[b0][b1][b2][b3]hstack=4[top];[m0][m1][m2][m3]hstack=4[bot];[top][bot]vstack[g];"
        f"[g]pad=iw:ih+84:0:84,{drawtext(txt, 18, y='8')}")
    ffmpeg([*inputs, "-filter_complex", fc, os.path.join(run, "sheet.png")])
    for v in VIEWS:
        os.remove(os.path.join(run, f"sheet_{v}.txt"))


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
    a = ap.parse_args()
    finalize(a) if a.cmd == "finalize" else compare(a)


if __name__ == "__main__":
    main()
