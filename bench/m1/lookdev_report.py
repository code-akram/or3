"""Finalise a look-dev run, or compare two runs (stdlib + ffmpeg; no Blender).

    python3 -I bench/m1/lookdev_report.py finalize RUN --label L [--process-s S]
    python3 -I bench/m1/lookdev_report.py compare A B --out DIR
    python3 -I bench/m1/lookdev_report.py engine RUN [--cycles HERO_DIR] [--crop x,y,w,h]
    python3 -I bench/m1/lookdev_report.py parity RUN [--cycles PARITY_HERO_DIR]
    python3 -I bench/m1/lookdev_report.py hairparity RUN [--engine F] [--lights key,fill,rim]
        [--portrait F --cycles-portrait EXR]
    python3 -I bench/m1/lookdev_report.py strip RUN [--cycles HERO_DIR] [--out PNG]
    python3 -I bench/m1/lookdev_report.py chart --chart CHART.json --engine PNG [--engine2 PNG] --out J [--sheet PNG]
    python3 -I bench/m1/lookdev_report.py bokeh --sharp A --dof B --roi x,y,w,h [--out J]

`parity` (T6) measures the engine against Cycles: shader-ball luminance ratios
(RUN/cycles_balls.png vs RUN/game_balls.png, blender/lookdev_render.py
--shader-balls) and the portrait SSIM (luma, 512 px wide) of RUN/game_portrait.png
against the parity Cycles portrait (bench/m1/hero.sh --parity), into
RUN/engine_parity.json; `engine` appends the ball row and the numbers to
engine_sheet.png when those inputs exist.

When RUN has game_<view>.png (bench/m1/engine_shots.sh), sheet.png gets an
engine row under the EEVEE views; `engine` draws RUN/engine_sheet.png: EEVEE
views, engine views, and the hero portrait Cycles target vs engine.

finalize merges build stats (character.stats.json), glTF validation
(glbstats.json) and render metrics (render_metrics.json) into RUN/metrics.json
and draws RUN/sheet.png. compare writes DIR/compare.{json,md} (every numeric
metric: A, B, delta) and DIR/sheet.png: both sheets stacked plus per-view
mask overlays (white = both, red = only A, cyan = only B).

Both refuse to write likeness content outside <main checkout>/private/: a run or a compare whose
inputs are private or carry a fan block (pipeline/likeness/containment.py, NOTES.md §14 rule 7).
"""

import argparse
import json
import os
import subprocess
import sys

sys.path.append(os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "pipeline", "likeness")))
import containment  # noqa: E402

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
    if containment.likeness(build):
        containment.assert_private(run, "lookdev run of a likeness build")
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
    face crop at 100 %. Writes into RUN only (hero.sh gives it its own staging dir, never the source
    look-dev run). `--build` is the data/build root of the regression strip's fixed stages."""
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
    parity_rows(a, run, out, W)
    print(f"-> {out}")
    if a.cycles:
        regression_strip(run, a.cycles, build=getattr(a, "build", None))


# ---------------------------------------------------------------- engine parity (T6)
# checkpoint-1 §2 item 3 and the T6 gate: per-material mean luminance ratio within
# +-10 %, highlight peak within +-20 %; portrait SSIM (luma, 512 px) >= 0.80.
PARITY_MEAN_TOL = 0.10
PARITY_PEAK_TOL = 0.20
PARITY_SSIM_MIN = 0.80
PARITY_SSIM_W = 512


def _png_rgb(path):
    """(h, w, 3) uint8 via ffmpeg (no imaging library in the stdlib)."""
    import numpy as np
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height", "-of", "csv=p=0", path],
                           check=True, capture_output=True, text=True).stdout.strip().split(",")
    w, h = int(probe[0]), int(probe[1])
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", path, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(h, w, 3)


def _lin_lum(rgb):
    import numpy as np
    c = rgb.astype(np.float64) / 255.0
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return lin @ np.array([0.2126, 0.7152, 0.0722])


def ball_metrics(run, engine_png="game_balls.png"):
    """Per ball: mean and 99.5th-percentile scene-linear luminance (Standard view,
    exposure-scaled) inside 0.85 of its projected radius, Cycles vs engine."""
    import numpy as np
    bj = load(os.path.join(run, "shader_balls.json"))
    cyc, eng = os.path.join(run, "cycles_balls.png"), os.path.join(run, engine_png)
    if not bj or not os.path.exists(cyc) or not os.path.exists(eng):
        return None
    lc, le = _lin_lum(_png_rgb(cyc)), _lin_lum(_png_rgb(eng))
    if lc.shape != le.shape:
        return {"error": f"size mismatch {lc.shape} vs {le.shape}"}
    yy, xx = np.mgrid[0:lc.shape[0], 0:lc.shape[1]]
    out = {}
    for b in bj.get("balls", []):
        if "circle_px" not in b:
            continue
        cx, cy, r = b["circle_px"]
        m = (xx + 0.5 - cx) ** 2 + (yy + 0.5 - cy) ** 2 <= (0.85 * r) ** 2
        mc, me = float(lc[m].mean()), float(le[m].mean())
        pc, pe = float(np.percentile(lc[m], 99.5)), float(np.percentile(le[m], 99.5))
        rm = me / mc if mc > 0 else None
        rp = pe / pc if pc > 0 else None
        out[b["material"]] = {
            "cycles_mean": round(mc, 5), "engine_mean": round(me, 5), "mean_ratio": round(rm, 3) if rm else None,
            "cycles_peak": round(pc, 5), "engine_peak": round(pe, 5), "peak_ratio": round(rp, 3) if rp else None,
            "mean_ok": rm is not None and abs(rm - 1) <= PARITY_MEAN_TOL,
            "peak_ok": rp is not None and abs(rp - 1) <= PARITY_PEAK_TOL}
    return out


def _luma_scaled(path, width):
    """Rec.709 luma of the display-encoded (sRGB) frame, area-scaled to `width` px wide, 0..255."""
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", path, "-vf", f"scale={width}:-2:flags=area",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], check=True, capture_output=True).stdout
    rgb = np.frombuffer(raw, np.uint8).reshape(-1, width, 3).astype(np.float64)
    return rgb @ np.array([0.2126, 0.7152, 0.0722])


def ssim(a, b, sigma=1.5):
    """Mean SSIM (Wang et al. 2004: 11x11 Gaussian window, sigma 1.5, K1 0.01, K2 0.03, L 255).
    (ffmpeg's ssim filter read ~0.40 where this reads ~0.68 on the same pair, so the gate uses this.)"""
    import numpy as np
    r = int(3.5 * sigma + 0.5)
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()

    def blur(x):
        x = np.pad(x, r, mode="reflect")
        x = np.apply_along_axis(lambda m: np.convolve(m, k, mode="valid"), 0, x)
        return np.apply_along_axis(lambda m: np.convolve(m, k, mode="valid"), 1, x)
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    ma, mb = blur(a), blur(b)
    va, vb, cv = blur(a * a) - ma * ma, blur(b * b) - mb * mb, blur(a * b) - ma * mb
    s = ((2 * ma * mb + c1) * (2 * cv + c2)) / ((ma * ma + mb * mb + c1) * (va + vb + c2))
    return float(s.mean())


def portrait_ssim(cyc, eng, width=PARITY_SSIM_W):
    """SSIM on luma, both frames scaled to `width` px wide."""
    if not cyc or not os.path.exists(cyc) or not os.path.exists(eng):
        return None
    a, b = _luma_scaled(cyc, width), _luma_scaled(eng, width)
    if a.shape != b.shape:
        return None
    return round(ssim(a, b), 4)


# T10: the head at 100 % as well (the whole-frame SSIM is mostly background and suit): the hero
# camera's head box in the 1920x1080 portrait, w,h,x,y.
PARITY_HEAD_CROP = "560,560,800,20"


def portrait_head_ssim(cyc, eng, crop=PARITY_HEAD_CROP):
    """SSIM on luma of the head box at 100 % (both frames scaled to 1920x1080 first)."""
    import numpy as np
    if not cyc or not os.path.exists(cyc) or not os.path.exists(eng):
        return None
    w, h, x, y = (int(c) for c in crop.split(","))

    def luma(path):
        raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", path, "-vf", f"scale=1920:1080,crop={w}:{h}:{x}:{y}",
                              "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], check=True, capture_output=True).stdout
        return np.frombuffer(raw, np.uint8).reshape(h, w, 3).astype(np.float64) @ np.array([0.2126, 0.7152, 0.0722])
    return round(ssim(luma(cyc), luma(eng)), 4)


def parity_metrics(a, run):
    cyc_p = os.path.join(a.cycles, "portrait.png") if getattr(a, "cycles", None) else None
    balls = ball_metrics(run)
    ssim = portrait_ssim(cyc_p, os.path.join(run, "game_portrait.png"))
    stage = load(os.path.join(a.cycles, "stage.json")) if getattr(a, "cycles", None) else {}
    res = {"run": os.path.basename(run), "cycles": os.path.abspath(a.cycles) if getattr(a, "cycles", None) else None,
           "cycles_is_parity": bool(stage.get("parity")),
           "portrait_ssim_luma_512": ssim, "portrait_ssim_ok": ssim is not None and ssim >= PARITY_SSIM_MIN,
           "portrait_head_ssim_luma_100pct": portrait_head_ssim(cyc_p, os.path.join(run, "game_portrait.png")),
           "head_crop": PARITY_HEAD_CROP,
           "balls": balls,
           "balls_mean_ok": sum(1 for v in (balls or {}).values() if isinstance(v, dict) and v.get("mean_ok")),
           "balls_n": len([v for v in (balls or {}).values() if isinstance(v, dict) and "mean_ratio" in v]),
           "targets": {"mean": PARITY_MEAN_TOL, "peak": PARITY_PEAK_TOL, "ssim": PARITY_SSIM_MIN}}
    with open(os.path.join(run, "engine_parity.json"), "w") as f:
        json.dump(res, f, indent=1)
    return res


def parity_text(res):
    lines = [f"PARITY  portrait SSIM (luma, {PARITY_SSIM_W} px) {res['portrait_ssim_luma_512']} "
             f"(target >= {PARITY_SSIM_MIN}; cycles {'parity' if res['cycles_is_parity'] else 'BEAUTY (not parity)'}; "
             f"head at 100 % {res.get('portrait_head_ssim_luma_100pct')})   "
             f"balls within +-{int(PARITY_MEAN_TOL * 100)} %: {res['balls_mean_ok']}/{res['balls_n']}"]
    for k, v in (res.get("balls") or {}).items():
        if isinstance(v, dict) and "mean_ratio" in v:
            lines.append(f"  {k:13s} mean {v['mean_ratio']:.3f} {'ok' if v['mean_ok'] else 'MISS'}   "
                         f"peak {v['peak_ratio']:.3f} {'ok' if v['peak_ok'] else 'MISS'}   "
                         f"(cycles {v['cycles_mean']:.4f} / engine {v['engine_mean']:.4f})")
    return "\n".join(lines)


def parity_rows(a, run, sheet, W):
    """Append the shader-ball row (Cycles | engine) and the parity numbers to the engine sheet."""
    res = parity_metrics(a, run)
    cyc, eng = os.path.join(run, "cycles_balls.png"), os.path.join(run, "game_balls.png")
    tp = os.path.join(run, "esheet_parity.txt")
    with open(tp, "w") as f:
        f.write(parity_text(res))
    labels = [tp]
    inputs = ["-i", sheet]
    chains = []
    rows = "[0]"
    if os.path.exists(cyc) and os.path.exists(eng):
        for i, (path, tag) in enumerate(((cyc, "cycles balls (Standard view, 64 spp)"), (eng, "engine balls"))):
            lp = os.path.join(run, f"esheet_balls_{i}.txt")
            with open(lp, "w") as f:
                f.write(tag)
            labels.append(lp)
            inputs += ["-i", path]
            chains.append(f"[{i + 1}]scale={W // 2}:-2,{drawtext(lp, 18)}[b{i}]")
        chains.append("[b0][b1]hstack[balls]")
        rows += "[balls]"
    n = 2 if len(chains) else 1
    fc = ";".join(chains + [f"{rows}vstack={n}[g]" if n > 1 else f"{rows}null[g]",
                            f"[g]pad=iw:ih+{22 * (len(parity_text(res).splitlines()) + 1)}:0:0,"
                            f"{drawtext(tp, 18, y=f'H-{22 * (len(parity_text(res).splitlines()) + 1) - 4}')}"])
    tmp = sheet[:-4] + ".tmp.png"
    ffmpeg([*inputs, "-filter_complex", fc, tmp])
    os.replace(tmp, sheet)
    for p in labels:
        os.remove(p)
    print(parity_text(res))


def parity_cmd(a):
    run = os.path.abspath(a.run)
    print(parity_text(parity_metrics(a, run)))
    print(f"-> {run}/engine_parity.json")


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
    if containment.is_private(A) or containment.is_private(B) or containment.likeness([ma, mb]):
        containment.assert_private(a.out, "compare of a private or likeness run")
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


# ---------------------------------------------------------------- hair test (T8)

def hair_test_sheet(a):
    """RUN/hair_test/hair_test_sheet.png from bench/m1/hair_test.py's frames: the neutral
    two-light hair test per model, the back view and the beard parity pair (Cycles strands,
    EEVEE game shells); with --base RUN0 a row of RUN0's frames above, and the metric ratios
    (p10, mode count, beard ratio) in the header. Merges the numbers into RUN/metrics.json
    under "hair_test" when that file exists. Writes into RUN only."""
    run = os.path.abspath(a.run)
    if containment.is_private(run) or containment.likeness(load(os.path.join(run, "character.stats.json"))):
        containment.assert_private(run, "hair test of a likeness build")
    ht = load(os.path.join(run, "hair_test", "hair_test.json"))
    if not ht:
        sys.exit(f"no hair_test/hair_test.json in {run} (bench/m1/hair_test.py)")
    base = load(os.path.join(os.path.abspath(a.base), "hair_test", "hair_test.json")) if a.base else {}
    T = 384
    inputs, chains, rows, labels = [], [], [], []
    n = [0]

    def tile(path, text):
        if not path or not os.path.exists(path):
            return None
        lp = os.path.join(run, "hair_test", f"hsheet_{n[0]}.txt")
        with open(lp, "w") as f:
            f.write(text)
        labels.append(lp)
        inputs.extend(["-i", path])
        chains.append(f"[{n[0]}]scale={T}:{T},{drawtext(lp, 14)}[h{n[0]}]")
        n[0] += 1
        return f"[h{n[0] - 1}]"

    def row(res, root, tag):
        out = []
        for k, fr in sorted((res.get("test") or {}).get("frames", {}).items()):
            if "png" in fr:
                out.append(tile(os.path.join(root, "hair_test", os.path.basename(fr["png"])),
                                f"{tag} {k}: p10 {fr['p10']:.3f} modes {fr['mode_count']}"))
        out.append(tile(os.path.join(root, "hair_test", "back.png"), f"{tag} back"))
        bd = res.get("beard") or {}
        out.append(tile(os.path.join(root, "hair_test", "beard_cycles.png"),
                        f"{tag} beard Cycles {bd.get('cycles_mean_lin', '-')}"))
        out.append(tile(os.path.join(root, "hair_test", "beard_eevee.png"),
                        f"{tag} beard EEVEE {bd.get('eevee_mean_lin', '-')} x{bd.get('ratio_eevee_over_cycles', '-')}"))
        return [t for t in out if t]

    width = 0
    for res, root, tag in ((base, os.path.abspath(a.base) if a.base else None, "before"), (ht, run, "after")):
        if not res:
            continue
        ts = row(res, root, tag)
        if ts:
            chains.append("".join(ts) + (f"hstack={len(ts)}" if len(ts) > 1 else "null") + f"[r{len(rows)}]")
            rows.append((f"[r{len(rows)}]", len(ts)))
            width = max(width, len(ts))
    if not rows:
        sys.exit("no hair test frames to draw")
    padded = []
    for name, k in rows:
        chains.append(f"{name}pad={width * T}:{T}[p{name[2:-1]}]")
        padded.append(f"[p{name[2:-1]}]")

    def p10(res):
        fr = (res.get("test") or {}).get("frames", {})
        return {k: v.get("p10") for k, v in fr.items() if "p10" in v}

    head = [f"hair test   {os.path.basename(run)}" + (f"   vs {os.path.basename(a.base)}" if a.base else "")]
    for k, v in p10(ht).items():
        b0 = max(p10(base).values(), default=None) if base else None
        fr = ht["test"]["frames"][k]
        head.append(f"{k}: p10 {v:.3f}" + (f" ({v / b0:.1f}x before)" if b0 else "")
                    + f"   modes {fr['mode_count']} at {fr['modes']}   p50 {fr['p50']:.3f}  p90 {fr['p90']:.3f}")
    bd = ht.get("beard") or {}
    if bd:
        head.append(f"beard mean linear: Cycles {bd['cycles_mean_lin']}  EEVEE {bd['eevee_mean_lin']}  "
                    f"ratio {bd['ratio_eevee_over_cycles']} ({'within' if bd['within_25pct'] else 'outside'} +-25 %)")
    hp = os.path.join(run, "hair_test", "hsheet_header.txt")
    with open(hp, "w") as f:
        f.write("\n".join(head))
    labels.append(hp)
    hh = 24 * len(head) + 16
    fc = ";".join(chains) + ";" + "".join(padded) + (f"vstack={len(padded)}" if len(padded) > 1 else "null") \
        + f"[g];[g]pad=iw:ih+{hh}:0:{hh},{drawtext(hp, 16, y='8')}"
    out = os.path.join(run, "hair_test", "hair_test_sheet.png")
    ffmpeg([*inputs, "-filter_complex", fc, out])
    for p in labels:
        os.remove(p)
    mp = os.path.join(run, "metrics.json")
    if os.path.exists(mp):
        m = load(mp)
        m["hair_test"] = {"test": {k: {kk: v.get(kk) for kk in ("p10", "p50", "p90", "mode_count", "modes")}
                                   for k, v in ((ht.get("test") or {}).get("frames") or {}).items()},
                          "beard": bd or None}
        with open(mp, "w") as f:
            json.dump(m, f, indent=2)
    print(f"-> {out}")


# ---------------------------------------------------------------- hair parity, spatial (T10)
# checkpoint-2 §5 item 1: a mean-ratio gate passed twice while the picture was wrong (T9's silver
# plates at 0.98x, T9b's uniform warm crown at 0.94x). Every hair / beard parity number therefore
# comes with a spatial term: per region p10 / p50 / p90, a four-box hair profile (crown / front /
# side / back) on the closeup, and the beard's grey fraction; and on the hero portrait the crown-box
# vs back-box luminance ratio, engine vs Cycles. Needs OpenImageIO's Python module for the EXRs.
HP_EXPOSURE = -2.5          # look-dev studio exposure (hair_test.STUDIO_EXPOSURE)
HP_GREY_SAT = 0.25          # a beard pixel is grey when (max - min) / max < this ...
HP_GREY_LUM_PCT = 50        # ... and it is at least as bright as the region's median (lit strands, not shadow)
# Portrait boxes as fractions of the frame (x0, x1, y0, y1); the engine and Cycles hero portraits
# register within 2 px at 1920 x 1080 (t10-engine-gate.md §5), so one set serves both.
HP_PORTRAIT_BOXES = {
    "crown": (1000 / 1920, 1150 / 1920, 70 / 1080, 130 / 1080),      # top of the head above the forehead
    "top_back": (1160 / 1920, 1240 / 1920, 60 / 1080, 130 / 1080),   # top of the head behind the parting
    "back": (1240 / 1920, 1300 / 1920, 180 / 1080, 340 / 1080),      # the mass behind the temple (rim side)
    "front_side": (870 / 1920, 900 / 1920, 240 / 1080, 420 / 1080),  # the lengths on the far cheek
    "lengths": (1320 / 1920, 1370 / 1920, 440 / 1080, 620 / 1080),   # the lengths behind the jaw
    "forehead": (980 / 1920, 1100 / 1920, 180 / 1080, 240 / 1080),   # skin, the normaliser
}
HP_LUM = (0.2126, 0.7152, 0.0722)


def _hp_read(path):
    import numpy as np
    try:
        import OpenImageIO as oiio
    except ImportError:
        sys.exit("hairparity needs the OpenImageIO Python module (pacman -S openimageio)")
    i = oiio.ImageInput.open(path)
    if not i:
        sys.exit(f"cannot read {path}")
    a = np.asarray(i.read_image(format="float"))
    i.close()
    if a.ndim == 2:
        a = a[..., None]
    return a[..., :3] if a.shape[-1] >= 3 else np.repeat(a[..., :1], 3, -1)


def _hp_srgb_decode(x):
    import numpy as np
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def _hp_engine_linear(path, res=None, exposure=HP_EXPOSURE):
    """Scene-linear RGB of a Standard-view engine frame (sRGB of the exposed linear), box-downsampled
    to `res` px square when given."""
    lin = _hp_srgb_decode(_hp_read(path)) / 2.0 ** exposure
    if res and lin.shape[0] != res:
        k = lin.shape[0] // res
        lin = lin.reshape(res, k, res, k, 3).mean(axis=(1, 3))
    return lin


def _hp_morph(m, r, close=False):
    import numpy as np
    d = m.copy()
    if close:
        for _ in range(r):
            d = d | np.roll(d, 1, 0) | np.roll(d, -1, 0) | np.roll(d, 1, 1) | np.roll(d, -1, 1)
    for _ in range(r):
        d = d & np.roll(d, 1, 0) & np.roll(d, -1, 0) & np.roll(d, 1, 1) & np.roll(d, -1, 1)
    return d


def _hp_regions(mask_rgb):
    """hair_test.parity_test's regions: scalp groom red, beard green (closed 3, eroded 2), brows blue."""
    mk = mask_rgb
    return {"hair": _hp_morph(_hp_morph(mk[..., 0] > 0.3, 3, close=True), 2),
            "beard": _hp_morph(_hp_morph(mk[..., 1] > 0.3, 3, close=True), 2),
            "brows": _hp_morph(_hp_morph(mk[..., 2] > 0.3, 2, close=True), 1)}


def _hp_stats(lin, m):
    import numpy as np
    y = lin @ np.array(HP_LUM)
    v = y[m]
    if v.size == 0:
        return None
    rgb = lin[m].mean(0)
    return {"mean": round(float(v.mean()), 5), "p10": round(float(np.percentile(v, 10)), 5),
            "p50": round(float(np.median(v)), 5), "p90": round(float(np.percentile(v, 90)), 5),
            "r_g": round(float(rgb[0] / max(rgb[1], 1e-9)), 3), "b_g": round(float(rgb[2] / max(rgb[1], 1e-9)), 3),
            "px": int(m.sum())}


def _hp_hair_boxes(hair, beard):
    """Four boxes over the hair mask (closeup): crown = the top 25 % of its rows; the rest split into
    thirds across x, named from the face side (the beard's centroid) as front / side / back."""
    import numpy as np
    ys, xs = np.nonzero(hair)
    y0, y1 = ys.min(), ys.max() + 1
    x0, x1 = xs.min(), xs.max() + 1
    yc = y0 + (y1 - y0) // 4
    bx = np.nonzero(beard)[1].mean() if beard.any() else (x0 + x1) / 2
    face_left = bx < (x0 + x1) / 2
    cuts = [x0, x0 + (x1 - x0) // 3, x0 + 2 * (x1 - x0) // 3, x1]
    names = ["front", "side", "back"] if face_left else ["back", "side", "front"]
    out = {}
    rows = np.zeros_like(hair)
    rows[y0:yc] = True
    out["crown"] = hair & rows
    for n, (a, b) in zip(names, zip(cuts[:-1], cuts[1:])):
        sel = np.zeros_like(hair)
        sel[yc:y1, a:b] = True
        out[n] = hair & sel
    return out


def _hp_grey(lin, m):
    """Beard grey fraction: of the region's pixels at or above its median luminance, the share with
    HSV saturation (max - min) / max under HP_GREY_SAT."""
    import numpy as np
    y = lin @ np.array(HP_LUM)
    v = y[m]
    if v.size == 0:
        return None
    lit = m & (y >= np.percentile(v, HP_GREY_LUM_PCT))
    px = lin[lit]
    mx = px.max(1)
    sat = (mx - px.min(1)) / np.maximum(mx, 1e-9)
    return {"grey_fraction": round(float((sat < HP_GREY_SAT).mean()), 4), "sat_p50": round(float(np.median(sat)), 4),
            "px_lit": int(lit.sum())}


def _hp_closeup(ht, engine, cyc_name):
    import numpy as np
    mk = _hp_read(os.path.join(ht, "parity_mask.exr"))
    res = mk.shape[0]
    reg = _hp_regions(mk)
    cyc = _hp_read(os.path.join(ht, cyc_name))
    eng = _hp_engine_linear(engine, res)
    out = {"engine": os.path.basename(engine), "cycles": cyc_name, "regions": {}}
    for n, m in reg.items():
        e, c = _hp_stats(eng, m), _hp_stats(cyc, m)
        if not e or not c:
            continue
        out["regions"][n] = {"engine": e, "cycles": c, "ratio": round(e["mean"] / max(c["mean"], 1e-9), 3)}
    boxes = _hp_hair_boxes(reg["hair"], reg["beard"])
    prof = {}
    he = out["regions"]["hair"]["engine"]["mean"]
    hc = out["regions"]["hair"]["cycles"]["mean"]
    for n, m in boxes.items():
        e, c = _hp_stats(eng, m), _hp_stats(cyc, m)
        if not e or not c:
            continue
        # rel: the box over the whole hair region (the profile shape); ratio: engine over Cycles
        prof[n] = {"engine": e, "cycles": c, "ratio": round(e["mean"] / max(c["mean"], 1e-9), 3),
                   "rel_engine": round(e["mean"] / max(he, 1e-9), 3), "rel_cycles": round(c["mean"] / max(hc, 1e-9), 3)}
    out["hair_profile"] = prof
    if "crown" in prof and "back" in prof:
        ce = prof["crown"]["engine"]["mean"] / max(prof["back"]["engine"]["mean"], 1e-9)
        cc = prof["crown"]["cycles"]["mean"] / max(prof["back"]["cycles"]["mean"], 1e-9)
        out["crown_over_back"] = {"engine": round(ce, 3), "cycles": round(cc, 3), "ratio": round(ce / max(cc, 1e-9), 3)}
    ge, gc = _hp_grey(eng, reg["beard"]), _hp_grey(cyc, reg["beard"])
    if ge and gc:
        out["beard_grey"] = {"engine": ge, "cycles": gc,
                             "ratio": round(ge["grey_fraction"] / max(gc["grey_fraction"], 1e-9), 3)}
    return out, boxes, reg


def _hp_portrait(engine, cycles_exr):
    """Crown / back / side boxes on the hero portrait, engine (Standard view, post off: the graded,
    exposed linear) vs the Cycles parity EXR (scene-linear); each box relative to the forehead box
    (cancels exposure and white balance) and crown / back."""
    import numpy as np
    out = {}
    for tag, path, is_png in (("engine", engine, True), ("cycles", cycles_exr, False)):
        a = _hp_read(path)
        lin = _hp_srgb_decode(a) if is_png else a
        h, w = lin.shape[:2]
        y = lin @ np.array(HP_LUM)
        rec = {}
        for n, (x0, x1, y0, y1) in HP_PORTRAIT_BOXES.items():
            v = y[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
            rec[n] = {"mean": float(v.mean()), "p10": float(np.percentile(v, 10)), "p50": float(np.median(v)),
                      "p90": float(np.percentile(v, 90))}
        fh = rec["forehead"]["mean"]
        for n in rec:
            r = rec[n]
            rec[n] = {k: round(v / fh, 4) for k, v in r.items()}  # relative to the forehead mean
        rec["crown_over_back"] = round(rec["crown"]["mean"] / max(rec["back"]["mean"], 1e-9), 3)
        out[tag] = rec
    out["crown_over_back_ratio"] = round(out["engine"]["crown_over_back"] / max(out["cycles"]["crown_over_back"], 1e-9), 3)
    out["boxes_frac"] = HP_PORTRAIT_BOXES
    return out


def hair_parity(a):
    """RUN/hair_parity.json (or --out): closeup regions (mean, p10 / p50 / p90, chroma) engine vs
    Cycles, the four-box hair profile, the beard grey fraction, per light when --lights is given
    (engine frames --pattern with {light}, Cycles hair_test/parity_cycles_<light>.exr), and the hero
    portrait boxes when --portrait and --cycles-portrait are given. Writes into RUN only."""
    run = os.path.abspath(a.run)
    if containment.is_private(run) or containment.likeness(load(os.path.join(run, "character.stats.json"))):
        containment.assert_private(run, "hair parity of a likeness build")
    ht = os.path.join(run, "hair_test")
    res = {"run": os.path.basename(run), "targets": {"region_ratio": [0.8, 1.2], "per_light_ratio": [0.8, 1.2],
                                                       "crown_over_back_within": 0.2}}
    lines = []
    eng = os.path.join(run, a.engine)
    if os.path.exists(eng):
        res["closeup"], boxes, reg = _hp_closeup(ht, eng, "parity_cycles.exr")
        c = res["closeup"]
        lines.append(f"closeup {a.engine}: " + "  ".join(f"{n} {v['ratio']}" for n, v in c["regions"].items()))
        lines.append("  hair profile (engine / Cycles, rel to the hair mean): " + "  ".join(
            f"{n} {v['ratio']} ({v['rel_engine']} vs {v['rel_cycles']})" for n, v in c["hair_profile"].items()))
        if "crown_over_back" in c:
            lines.append(f"  crown / back: engine {c['crown_over_back']['engine']}  Cycles {c['crown_over_back']['cycles']}")
        if "beard_grey" in c:
            g = c["beard_grey"]
            lines.append(f"  beard grey fraction: engine {g['engine']['grey_fraction']}  Cycles {g['cycles']['grey_fraction']}  (x{g['ratio']})")
    if a.lights:
        res["per_light"] = {}
        for ln in a.lights.split(","):
            ef = os.path.join(run, a.pattern.format(light=ln))
            cf = f"parity_cycles_{ln}.exr"
            if not (os.path.exists(ef) and os.path.exists(os.path.join(ht, cf))):
                continue
            r, _, _ = _hp_closeup(ht, ef, cf)
            res["per_light"][ln] = r
            lines.append(f"light {ln}: " + "  ".join(f"{n} {v['ratio']}" for n, v in r["regions"].items())
                         + "   profile " + " ".join(f"{n} {v['ratio']}" for n, v in r["hair_profile"].items()))
    if a.portrait and a.cycles_portrait:
        p = _hp_portrait(os.path.join(run, a.portrait), a.cycles_portrait)
        res["portrait"] = p
        lines.append(f"portrait crown / back: engine {p['engine']['crown_over_back']}  Cycles {p['cycles']['crown_over_back']}"
                     f"  (x{p['crown_over_back_ratio']}; target within +-20 %)")
        lines.append("  boxes rel. forehead (engine / Cycles): " + "  ".join(
            f"{n} {p['engine'][n]['mean']}/{p['cycles'][n]['mean']}" for n in HP_PORTRAIT_BOXES if n != "forehead"))
    out = a.out or os.path.join(run, "hair_parity.json")
    if not os.path.abspath(out).startswith(run + os.sep):
        sys.exit("--out must be inside RUN")
    with open(out, "w") as f:
        json.dump(res, f, indent=1)
    print("\n".join(lines))
    print(f"-> {out}")


# ---------------------------------------------------------------- regression strip (T10)
# checkpoint-2 §5 item 5: a fixed strip main9 -> int1 -> latest, each the Cycles face crop at
# 100 % (hero portrait_crop.png) beside the engine portrait cut to the same rectangle, so a colour
# drift (like the T9 hair warming) shows the day it happens. int1 has no Cycles hero of its own;
# t8-v5 is the hero of the T8 build int1 merged. Paths relative to data/build.
STRIP_FIXED = [
    ("main9", "lookdev/20261013T081002Z-heroE-main9", "hero/20261013T081828Z-main9-final"),
    ("int1", "lookdev/20261014T131343Z-int1-main", "hero/20261014T130129Z-t8-v5"),
]
# hero portrait_crop.png (blender/hero/stage.py render_crop: half the frame around the near eye)
# sits at this rectangle of the 1920x1080 portrait for the hero camera (registered on t9b-b1).
STRIP_CROP = "960,540,556,98"
STRIP_W = 640


def _strip_register(cyc, eng, w, h, x, y, reach=128):
    """Where the Cycles crop sits in the engine portrait: normalised cross-correlation of log
    luminance at quarter scale, within `reach` px of (x, y). The crop follows the near eye, which
    moved between builds."""
    import numpy as np

    def lum(path, size):
        raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", path, "-vf", f"scale={size[0]}:{size[1]}:flags=area",
                              "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], check=True, capture_output=True).stdout
        return np.log(_lin_lum(np.frombuffer(raw, np.uint8).reshape(size[1], size[0], 3)) + 1e-3)
    c, e = lum(cyc, (w // 4, h // 4)), lum(eng, (480, 270))
    c = (c - c.mean()) / (c.std() + 1e-9)
    best = (-2.0, x, y)
    r = reach // 4
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            x0, y0 = x // 4 + dx, y // 4 + dy
            if x0 < 0 or y0 < 0 or x0 + c.shape[1] > e.shape[1] or y0 + c.shape[0] > e.shape[0]:
                continue
            p = e[y0:y0 + c.shape[0], x0:x0 + c.shape[1]]
            v = float(((p - p.mean()) / (p.std() + 1e-9) * c).mean())
            if v > best[0]:
                best = (v, x0 * 4, y0 * 4)
    return best[1], best[2]


def regression_strip(run, cycles, out=None, crop=STRIP_CROP, build=None):
    """RUN/regression_strip.png (or `out`): main9, int1 and RUN (with the Cycles hero `cycles`),
    one row each: Cycles crop | engine crop. Rows whose inputs are missing are skipped.
    `build` is the data/build root holding the fixed stages (default: two levels above RUN)."""
    build = build or os.path.dirname(os.path.dirname(os.path.abspath(run)))
    stages = [(n, os.path.join(build, l), os.path.join(build, h)) for n, l, h in STRIP_FIXED]
    stages.append(("latest " + os.path.basename(os.path.abspath(run)), os.path.abspath(run),
                   os.path.abspath(cycles) if cycles else ""))
    for _, l, h in stages:
        if containment.is_private(l) or containment.is_private(h) or \
                containment.likeness(load(os.path.join(l, "character.stats.json"))):
            containment.assert_private(out or run, "regression strip with a private or likeness run")
    w, h, x, y = (int(c) for c in crop.split(","))
    inputs, chains, rows, labels = [], [], [], []
    n = 0
    for name, lk, hero in stages:
        cyc, eng = os.path.join(hero, "portrait_crop.png"), os.path.join(lk, "game_portrait.png")
        if not (os.path.exists(cyc) and os.path.exists(eng)):
            print(f"strip: skip {name} (missing {cyc if not os.path.exists(cyc) else eng})")
            continue
        tags = []
        rx, ry = _strip_register(cyc, eng, w, h, x, y)
        for path, tag, vf in ((cyc, f"{name}  Cycles {os.path.basename(hero)}", f"scale={w}:{h}"),
                              (eng, f"{name}  engine (crop at {rx},{ry})", f"scale=1920:1080,crop={w}:{h}:{rx}:{ry}")):
            lp = os.path.join(os.path.dirname(out) if out else run, f"strip_{n}.txt")
            with open(lp, "w") as f:
                f.write(tag)
            labels.append(lp)
            inputs += ["-i", path]
            chains.append(f"[{n}]{vf},scale={STRIP_W}:-2,{drawtext(lp, 16)}[s{n}]")
            tags.append(f"[s{n}]")
            n += 1
        chains.append("".join(tags) + f"hstack[r{len(rows)}]")
        rows.append(f"[r{len(rows)}]")
    if not rows:
        print("strip: nothing to draw")
        return None
    out = out or os.path.join(run, "regression_strip.png")
    fc = ";".join(chains) + ";" + ("".join(rows) + f"vstack={len(rows)}" if len(rows) > 1 else rows[0] + "null")
    ffmpeg([*inputs, "-filter_complex", fc, out])
    for p in labels:
        os.remove(p)
    print(f"-> {out}")
    return out


def strip_cmd(a):
    regression_strip(os.path.abspath(a.run), a.cycles, a.out, a.crop, getattr(a, "build", None))


# ---------------------------------------------------------------- grey chart (T16)
# checkpoint-3 §3.2: 18 / 50 / 90 % patches and an 18 % ball under the hero rig in both renderers
# (blender/hero/refs.py --mode chart writes chart.json, the Cycles frame and chart.glb for the engine),
# compared after the grade, per channel, to +-3/255.
CHART_TOL = 3.0


def _read_rgb(path):
    """(h, w, 3) float: 0..255 display values for 8/16-bit images, scene-linear for EXR."""
    import numpy as np
    if path.lower().endswith(".exr"):
        return _hp_read(path).astype(np.float64)
    try:
        import OpenImageIO as oiio
        i = oiio.ImageInput.open(path)
        a = np.asarray(i.read_image(format="float"), dtype=np.float64)
        i.close()
        a = a[..., None] if a.ndim == 2 else a
        a = a[..., :3] if a.shape[-1] >= 3 else np.repeat(a[..., :1], 3, -1)
        return a * 255.0
    except ImportError:
        return _png_rgb(path).astype(np.float64)


def chart_measure(chart, img):
    """{sample: [R, G, B]} means over chart.json's patch boxes and ball sample boxes / disc."""
    import numpy as np
    out = {}
    for r in chart["patches"]:
        if r["kind"] == "patch":
            x0, y0, x1, y1 = r["bbox_px"]
            out[r["name"]] = img[y0:y1, x0:x1].reshape(-1, 3).mean(0)
            continue
        k = r.get("sample_box_px", 7) // 2
        for lab, (x, y) in r["samples_px"].items():
            x, y = int(round(x)), int(round(y))
            out[f"{r['name']}:{lab}"] = img[y - k:y + k + 1, x - k:x + k + 1].reshape(-1, 3).mean(0)
        cx, cy = r["center_px"]
        rr = r["radius_px"] * 0.85
        yy, xx = np.mgrid[0:img.shape[0], 0:img.shape[1]]
        out[f"{r['name']}:disc"] = img[(xx + 0.5 - cx) ** 2 + (yy + 0.5 - cy) ** 2 < rr * rr].mean(0)
    return out


def chart_rows(chart, ref_png, frames, tol=CHART_TOL):
    """The chart row: per sample, the reference (Cycles) mean and each engine frame's mean and
    difference (0..255 per channel and luma), pass at |d| <= tol on every channel. `frames` is
    [(label, png)]. Returns {"rows": [...], "pass": {label: bool (patches)}, ...}."""
    import numpy as np
    lw = np.array([0.2126, 0.7152, 0.0722])
    ref = chart_measure(chart, _read_rgb(ref_png))
    meas = {lab: chart_measure(chart, _read_rgb(p)) for lab, p in frames}
    rows = []
    ok = {lab: True for lab, _ in frames}
    for name, rv in ref.items():
        row = {"sample": name, "cycles": [round(float(v), 2) for v in rv], "cycles_luma": round(float(rv @ lw), 2)}
        patch = ":" not in name
        for lab, _ in frames:
            ev = meas[lab][name]
            d = ev - rv
            p = bool(np.all(np.abs(d) <= tol))
            row[lab] = {"mean": [round(float(v), 2) for v in ev], "diff": [round(float(v), 2) for v in d],
                        "diff_luma": round(float((ev - rv) @ lw), 2), "max_abs": round(float(np.abs(d).max()), 2),
                        "pass": p}
            if patch:
                ok[lab] = ok[lab] and p
        rows.append(row)
    return {"tolerance_255": tol, "reference": ref_png, "frames": dict(frames), "rows": rows,
            "pass_patches": ok,
            "note": "pass = every patch within +-tol/255 on R, G and B; ball samples are reported, not gated"}


def chart_sheet(chart, res, ref_png, frames, out_png, pad=40):
    """Side-by-side crops of the chart region (Cycles | engine ...) with the numbers under them."""
    xs, ys = [], []
    for r in chart["patches"]:
        if r["kind"] == "patch":
            xs += [r["bbox_px"][0], r["bbox_px"][2]]
            ys += [r["bbox_px"][1], r["bbox_px"][3]]
        else:
            cx, cy, rr = r["center_px"][0], r["center_px"][1], r["radius_px"]
            xs += [cx - rr, cx + rr]
            ys += [cy - rr, cy + rr]
    x0, y0 = max(0, int(min(xs)) - 2 * pad), max(0, int(min(ys)) - 2 * pad)
    x1, y1 = int(max(xs)) + 2 * pad, int(max(ys)) + 2 * pad
    w, h = x1 - x0, y1 - y0
    tiles = [("Cycles (grade.py --parity)", ref_png)] + list(frames)
    tmp = os.path.dirname(os.path.abspath(out_png))
    inputs, chains, labels = [], [], []
    for n, (lab, path) in enumerate(tiles):
        lp = os.path.join(tmp, f".chart_lab{n}.txt")
        with open(lp, "w") as f:
            f.write(lab)
        labels.append(lp)
        inputs += ["-i", path]
        box = ",".join(f"drawbox=x={r['bbox_px'][0] - x0}:y={r['bbox_px'][1] - y0}:w={r['bbox_px'][2] - r['bbox_px'][0]}:"
                       f"h={r['bbox_px'][3] - r['bbox_px'][1]}:color=yellow@0.6" for r in chart["patches"] if r["kind"] == "patch")
        chains.append(f"[{n}]crop={w}:{h}:{x0}:{y0},{box},{drawtext(lp, 18)}[t{n}]")
    lines = ["sample            cycles RGB (0-255)    " + "   ".join(f"{lab[:22]:>22} diff R,G,B" for lab, _ in frames)]
    for row in res["rows"]:
        s = f"{row['sample'][6:]:<17} {'%6.1f %6.1f %6.1f' % tuple(row['cycles'])}   "
        for lab, _ in frames:
            d = row[lab]["diff"]
            s += f"   {'%+6.1f %+6.1f %+6.1f' % tuple(d)} {'ok' if row[lab]['pass'] else ('FAIL' if ':' not in row['sample'] else '  ')}"
        lines.append(s)
    lines.append(f"patches within +-{res['tolerance_255']}/255: " + ", ".join(f"{k} {'PASS' if v else 'FAIL'}" for k, v in res["pass_patches"].items()))
    go = res.get("grade_only")
    if go:
        lines.append("grade only (own linear -> grade_lut.json on the CPU vs own graded frame): max |d| "
                     + ", ".join(f"{k} {v:.2f}/255 {'PASS' if go['pass_patches'][k] else 'FAIL'}" for k, v in go["max_abs"].items()))
    tp = os.path.join(tmp, ".chart_table.txt")
    with open(tp, "w") as f:
        f.write("\n".join(lines))
    labels.append(tp)
    th = 26 * (len(lines) + 1)
    fc = ";".join(chains) + ";" + "".join(f"[t{n}]" for n in range(len(tiles))) + \
        (f"hstack={len(tiles)}" if len(tiles) > 1 else "null") + f",pad=iw:ih+{th}:0:0:black,{drawtext(tp, 18, '12', f'h-{th}+8')}"
    ffmpeg([*inputs, "-filter_complex", fc, out_png])
    for p in labels:
        os.remove(p)
    return out_png


def _lut_pipeline(lut, lin, uv, ev):
    """grade_lut.json applied on the CPU as the engine does (web/src/character/grade.ts, output.ts):
    log2 shaper -> 33^3 grade LUT (log2 out) -> vignette map at uv -> x 2^ev -> view LUT (display).
    lin (k, 3) scene-linear -> (k, 3) display 0..255."""
    import base64
    import numpy as np
    n = lut["size"]

    def dec(d, shape):
        return np.frombuffer(base64.b64decode(d), np.float32).reshape(shape)

    def tri(t, x):
        p = np.clip(x, 0, 1) * (n - 1)
        i0 = np.minimum(np.floor(p).astype(int), n - 2)
        f = p - i0
        out = np.zeros_like(x)
        for db in (0, 1):
            for dg in (0, 1):
                for dr in (0, 1):
                    w = (f[:, 0] if dr else 1 - f[:, 0]) * (f[:, 1] if dg else 1 - f[:, 1]) * (f[:, 2] if db else 1 - f[:, 2])
                    out += w[:, None] * t[i0[:, 2] + db, i0[:, 1] + dg, i0[:, 0] + dr]
        return out

    def shaper(c, lo, hi):
        return np.clip((np.log2(np.maximum(c, 2.0 ** lo)) - lo) / (hi - lo), 0, 1)

    G = dec(lut["grade"]["data"], (n, n, n, 3))
    V = dec(lut["view"]["data"], (n, n, n, 3))
    g = 2.0 ** tri(G, shaper(lin, lut["grade"]["min"], lut["grade"]["max"]))
    vg = lut.get("vignette")
    if vg:
        m = dec(vg["data"], (vg["h"], vg["w"]))
        g = g * m[min(int(uv[1] * vg["h"]), vg["h"] - 1), min(int(uv[0] * vg["w"]), vg["w"] - 1)]
    return tri(V, shaper(g * 2.0 ** ev, lut["view"]["min"], lut["view"]["max"])) * 255.0


def chart_grade_only(chart, lut_path, ref_png, ref_exr, eng_png, eng_npy, tol=CHART_TOL):
    """The grade alone, in each renderer: its own scene-linear chart through the CPU LUT pipeline
    against its own graded frame (Cycles: grade.py's PNG of the EXR; engine: the viewer's GPU LUT
    path). Separates the grade from the lighting, which the full chart row mixes."""
    import numpy as np
    lut = load(lut_path)
    res = chart["res"]
    centres = {}
    for r in chart["patches"]:
        if r["kind"] == "patch":
            x0, y0, x1, y1 = r["bbox_px"]
            centres[r["name"]] = ((x0 + x1) / 2, (y0 + y1) / 2)
        else:
            for lab, xy in r["samples_px"].items():
                centres[f"{r['name']}:{lab}"] = tuple(xy)
            centres[f"{r['name']}:disc"] = tuple(r["center_px"])
    sides = {"cycles": (chart_measure(chart, _read_rgb(ref_exr)), chart_measure(chart, _read_rgb(ref_png)))}
    if eng_npy:
        e = np.load(eng_npy)[..., :3].astype(np.float64)
        sides["engine"] = (chart_measure(chart, e), chart_measure(chart, _read_rgb(eng_png)))
    rows, ok = [], {k: True for k in sides}
    for name, xy in centres.items():
        row = {"sample": name}
        for k, (lin, disp) in sides.items():
            cpu = _lut_pipeline(lut, lin[name][None], (xy[0] / res[0], xy[1] / res[1]), chart["exposure"])[0]
            d = disp[name] - cpu
            p = bool(np.all(np.abs(d) <= tol))
            row[k] = {"linear": [round(float(v), 5) for v in lin[name]], "frame_minus_lut": [round(float(v), 2) for v in d], "pass": p}
            if ":" not in name:
                ok[k] = ok[k] and p
        rows.append(row)
    return {"lut": lut_path, "rows": rows, "pass_patches": ok,
            "max_abs": {k: round(max(float(np.abs(r[k]["frame_minus_lut"]).max()) for r in rows
                                     if not r["sample"].endswith(":disc")), 2) for k in sides},
            "note": "max_abs and pass leave out the ball disc (a mean of display values against the LUT of a mean "
                    "of linear values over a gradient)"}


def chart_cmd(a):
    chart = load(a.chart)
    ref = a.cycles or chart.get("cycles", {}).get("png")
    if not ref:
        sys.exit("chart: no Cycles frame (--cycles or chart.json cycles.png)")
    if not os.path.isabs(ref):
        ref = os.path.join(os.path.dirname(os.path.abspath(a.chart)), ref)
    frames = [(a.engine_label, a.engine)] + ([(a.engine2_label, a.engine2)] if a.engine2 else [])
    for p in [a.chart, ref] + [p for _, p in frames]:
        if containment.is_private(p):
            containment.assert_private(a.out, "chart row with private inputs")
    res = chart_rows(chart, ref, frames, a.tol)
    if a.lut:
        exr = chart.get("cycles", {}).get("exr")
        if exr and not os.path.isabs(exr):
            exr = os.path.join(os.path.dirname(os.path.abspath(a.chart)), exr)
        if not exr or not os.path.exists(exr):
            exr = os.path.join(os.path.dirname(ref), "exr", "chart.exr")
        res["grade_only"] = chart_grade_only(chart, a.lut, ref, exr, a.engine, a.engine_linear, a.tol)
    with open(a.out, "w") as f:
        json.dump(res, f, indent=1)
    if a.sheet:
        chart_sheet(chart, res, ref, frames, a.sheet)
        print(f"-> {a.sheet}")
    for row in res["rows"]:
        print(f"{row['sample']:<26} cycles {row['cycles']}  " + "  ".join(
            f"{lab}: {row[lab]['diff']}{'' if row[lab]['pass'] else ' !'}" for lab, _ in frames))
    print(f"-> {a.out}; patches within +-{a.tol}/255: {res['pass_patches']}")
    if "grade_only" in res:
        go = res["grade_only"]
        print(f"grade only (own linear -> CPU LUT vs own graded frame): max |d| {go['max_abs']}, patches pass {go['pass_patches']}")


# ---------------------------------------------------------------- bokeh radius (T16)
def _disc_kernel(r, ss=16):
    """Anti-aliased disc of radius r px (area-sampled ss x ss per px), normalised; r < 0.05 = delta."""
    import numpy as np
    if r < 0.05:
        return np.ones((1, 1))
    n = int(np.ceil(r + 0.5))
    o = (np.arange((2 * n + 1) * ss) + 0.5) / ss - (n + 0.5)
    yy, xx = np.meshgrid(o, o, indexing="ij")
    k = (xx * xx + yy * yy <= r * r).astype(np.float64)
    k = k.reshape(2 * n + 1, ss, 2 * n + 1, ss).mean(axis=(1, 3))
    if k.sum() <= 0:
        return np.ones((1, 1))
    return k / k.sum()


def _conv_same(img, k):
    """2-D 'same' convolution of (h, w, c) by a small kernel (edge-padded), via FFT."""
    import numpy as np
    kh, kw = k.shape
    ph, pw = kh // 2, kw // 2
    p = np.pad(img, ((ph, ph), (pw, pw), (0, 0)), mode="edge")
    H, W = p.shape[:2]
    K = np.fft.rfft2(k, s=(H, W))
    out = np.fft.irfft2(np.fft.rfft2(p, axes=(0, 1)) * K[..., None], s=(H, W), axes=(0, 1))
    return out[kh - 1:kh - 1 + img.shape[0], kw - 1:kw - 1 + img.shape[1]]


def bokeh_fit(sharp, dof, roi, linear=False, rmax=12.0, step=0.05):
    """Fit the disc radius r (px) minimising |disc_r * sharp - dof|^2 inside roi = (x, y, w, h).
    PNGs are decoded from sRGB to linear unless `linear`; EXRs are linear. Returns a dict."""
    import numpy as np
    x, y, w, h = roi
    m = int(np.ceil(rmax)) + 2

    def get(path):
        a = _read_rgb(path)
        if not path.lower().endswith(".exr"):
            a = a / 255.0
            if not linear:
                a = _hp_srgb_decode(a)
        return a
    A, B = get(sharp), get(dof)
    if A.shape != B.shape:
        sys.exit(f"bokeh: {sharp} {A.shape[:2]} and {dof} {B.shape[:2]} differ")
    ya, yb, xa, xb = max(0, y - m), min(A.shape[0], y + h + m), max(0, x - m), min(A.shape[1], x + w + m)
    sa = A[ya:yb, xa:xb]
    tgt = B[y:y + h, x:x + w]
    oy, ox = y - ya, x - xa
    radii = np.round(np.arange(0.0, rmax + 1e-9, step), 4)
    errs = []
    for r in radii:
        c = _conv_same(sa, _disc_kernel(float(r)))[oy:oy + h, ox:ox + w]
        errs.append(float(((c - tgt) ** 2).mean()))
    errs = np.array(errs)
    i = int(np.argmin(errs))
    # parabolic refinement around the minimum
    r_best = float(radii[i])
    if 0 < i < len(radii) - 1:
        e0, e1, e2 = errs[i - 1], errs[i], errs[i + 1]
        den = e0 - 2 * e1 + e2
        if den > 0:
            r_best += 0.5 * step * (e0 - e2) / den
    base = float(((sa[oy:oy + h, ox:ox + w] - tgt) ** 2).mean())
    return {"radius_px": round(r_best, 3), "residual_rms": round(float(np.sqrt(errs[i])), 6),
            "unblurred_rms": round(float(np.sqrt(base)), 6), "roi": [x, y, w, h],
            "png_srgb_decoded": not linear,
            "curve": [[float(r), round(float(np.sqrt(e)), 6)] for r, e in zip(radii[::4], errs[::4])],
            "sharp": sharp, "dof": dof}


def bokeh_cmd(a):
    roi = [int(v) for v in a.roi.split(",")]
    res = bokeh_fit(a.sharp, a.dof, roi, a.linear, a.rmax)
    if a.out:
        with open(a.out, "w") as f:
            json.dump(res, f, indent=1)
    print(json.dumps({k: v for k, v in res.items() if k != "curve"}))


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
    e.add_argument("--build", help="data/build root for the regression strip's fixed stages (default: two levels above RUN)")
    e.add_argument("--crop", default="720,90,600,600",
                   help="face crop x,y,w,h in the 1920x1080 portrait (same camera in both)")
    pa = sub.add_parser("parity", help="engine parity numbers (RUN/engine_parity.json)")
    pa.add_argument("run")
    pa.add_argument("--cycles", help="hero stage dir with the parity portrait.png (hero.sh --parity)")
    h = sub.add_parser("hairtest", help="hair test sheet (RUN/hair_test/, bench/m1/hair_test.py)")
    h.add_argument("run")
    h.add_argument("--base", help="run to show above it (before)")
    hp = sub.add_parser("hairparity", help="spatial hair / beard parity, engine vs Cycles (RUN/hair_parity.json, T10)")
    hp.add_argument("run")
    hp.add_argument("--engine", default="lin_closeup.png", help="Standard-view engine closeup in RUN")
    hp.add_argument("--lights", help="per-light frames too, e.g. key,fill,rim")
    hp.add_argument("--pattern", default="lin_{light}_closeup.png", help="engine per-light frame name in RUN")
    hp.add_argument("--portrait", help="Standard-view, post-off engine hero portrait in RUN")
    hp.add_argument("--cycles-portrait", help="Cycles parity portrait EXR (hero.sh --parity: exr/portrait.exr)")
    hp.add_argument("--out", help="output JSON (inside RUN)")
    rs = sub.add_parser("strip", help="regression strip main9 -> int1 -> RUN, Cycles crop | engine (T10)")
    rs.add_argument("run")
    rs.add_argument("--cycles", help="hero stage dir of RUN (portrait_crop.png)")
    rs.add_argument("--crop", default=STRIP_CROP, help="w,h,x,y of the Cycles crop in the 1920x1080 portrait")
    rs.add_argument("--build", help="data/build root of the fixed stages (default: two levels above RUN)")
    rs.add_argument("--out", help="output PNG (default RUN/regression_strip.png)")
    ch = sub.add_parser("chart", help="grey-chart row: engine vs Cycles after the grade, +-3/255 (T16)")
    ch.add_argument("--chart", required=True, help="chart.json (blender/hero/refs.py --mode chart)")
    ch.add_argument("--engine", required=True, help="engine frame (graded, same 1920x1080 camera)")
    ch.add_argument("--engine-label", default="engine")
    ch.add_argument("--engine2", help="a second engine frame (e.g. the pre-LUT grade)")
    ch.add_argument("--engine2-label", default="engine2")
    ch.add_argument("--cycles", help="Cycles graded frame (default: chart.json cycles.png)")
    ch.add_argument("--tol", type=float, default=CHART_TOL)
    ch.add_argument("--lut", help="grade_lut.json: add the grade-only check (each renderer's linear through the LUT)")
    ch.add_argument("--engine-linear", help="the engine's scene-linear chart (engine_shots --chart: <prefix>chart_linear.npy)")
    ch.add_argument("--out", required=True, help="output JSON")
    ch.add_argument("--sheet", help="output PNG: chart crops side by side with the numbers")
    bk = sub.add_parser("bokeh", help="fit the DoF disc radius (px) between a sharp and a DoF frame (T16)")
    bk.add_argument("--sharp", required=True)
    bk.add_argument("--dof", required=True)
    bk.add_argument("--roi", required=True, help="x,y,w,h in the frames' pixels (top-left origin)")
    bk.add_argument("--linear", action="store_true", help="PNG values are used as they are (no sRGB decode)")
    bk.add_argument("--rmax", type=float, default=12.0)
    bk.add_argument("--out", help="output JSON")
    a = ap.parse_args()
    {"finalize": finalize, "compare": compare, "engine": engine_sheet, "parity": parity_cmd,
     "hairtest": hair_test_sheet, "hairparity": hair_parity, "strip": strip_cmd,
     "chart": chart_cmd, "bokeh": bokeh_cmd}[a.cmd](a)


if __name__ == "__main__":
    main()
