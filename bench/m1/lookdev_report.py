"""Finalise a look-dev run, or compare two runs (stdlib + ffmpeg; no Blender).

    python3 -I bench/m1/lookdev_report.py finalize RUN --label L [--process-s S]
    python3 -I bench/m1/lookdev_report.py compare A B --out DIR
    python3 -I bench/m1/lookdev_report.py engine RUN [--cycles HERO_DIR] [--crop x,y,w,h]
    python3 -I bench/m1/lookdev_report.py parity RUN [--cycles PARITY_HERO_DIR]

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
    parity_rows(a, run, out, W)
    print(f"-> {out}")


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


def parity_metrics(a, run):
    cyc_p = os.path.join(a.cycles, "portrait.png") if getattr(a, "cycles", None) else None
    balls = ball_metrics(run)
    ssim = portrait_ssim(cyc_p, os.path.join(run, "game_portrait.png"))
    stage = load(os.path.join(a.cycles, "stage.json")) if getattr(a, "cycles", None) else {}
    res = {"run": os.path.basename(run), "cycles": os.path.abspath(a.cycles) if getattr(a, "cycles", None) else None,
           "cycles_is_parity": bool(stage.get("parity")),
           "portrait_ssim_luma_512": ssim, "portrait_ssim_ok": ssim is not None and ssim >= PARITY_SSIM_MIN,
           "balls": balls,
           "balls_mean_ok": sum(1 for v in (balls or {}).values() if isinstance(v, dict) and v.get("mean_ok")),
           "balls_n": len([v for v in (balls or {}).values() if isinstance(v, dict) and "mean_ratio" in v]),
           "targets": {"mean": PARITY_MEAN_TOL, "peak": PARITY_PEAK_TOL, "ssim": PARITY_SSIM_MIN}}
    with open(os.path.join(run, "engine_parity.json"), "w") as f:
        json.dump(res, f, indent=1)
    return res


def parity_text(res):
    lines = [f"PARITY  portrait SSIM (luma, {PARITY_SSIM_W} px) {res['portrait_ssim_luma_512']} "
             f"(target >= {PARITY_SSIM_MIN}; cycles {'parity' if res['cycles_is_parity'] else 'BEAUTY (not parity)'})   "
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
    pa = sub.add_parser("parity", help="engine parity numbers (RUN/engine_parity.json)")
    pa.add_argument("run")
    pa.add_argument("--cycles", help="hero stage dir with the parity portrait.png (hero.sh --parity)")
    h = sub.add_parser("hairtest", help="hair test sheet (RUN/hair_test/, bench/m1/hair_test.py)")
    h.add_argument("run")
    h.add_argument("--base", help="run to show above it (before)")
    a = ap.parse_args()
    {"finalize": finalize, "compare": compare, "engine": engine_sheet, "parity": parity_cmd,
     "hairtest": hair_test_sheet}[a.cmd](a)


if __name__ == "__main__":
    main()
