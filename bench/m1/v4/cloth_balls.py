"""Shader balls per light for the suit cloth path (T13 item 7; web/src/character/cloth.ts).

T19 measured the balls per light, direct light only and net of the world, engine over Cycles:
wool 1.02 / 1.04 / 0.67 and silk 1.06 / 1.09 / 2.20 under key / fill / rim (the rim over 0.98 of
the ball's radius, key and fill over 0.85). This script reruns that measure on the current viewer
and fits each cloth kind's grazing response (sheen scale, fuzz strength) per light:

    python3 bench/m1/v4/cloth_balls.py prep  DIR            # DIR <- T19's Cycles balls and inputs (links)
    python3 bench/m1/v4/cloth_balls.py shots DIR PREFIX [JSON]   # engine balls under none/key/fill/rim
    python3 bench/m1/v4/cloth_balls.py ratios DIR PREFIX    # net ratios per ball and light -> JSON
    python3 bench/m1/v4/cloth_balls.py fit DIR              # component renders, least squares, params

The engine renders go through bench/m1/engine_shots.mjs on port 8795, one browser at a time, at
nice 10. Public build only (the ball scene has no face).
"""

import json
import os
import subprocess
import sys
import urllib.parse

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "bench", "m1"))
import lookdev_report as lr  # noqa: E402

LIGHTS = ("none", "key", "fill", "rim")
RADIUS = {"key": 0.85, "fill": 0.85, "rim": 0.98}
KINDS = {"suit_wool": "wool", "suit_silk": "silk"}
# the base specular's grazing falloff power per kind (cloth.ts graze()): the silk's excess under the
# rim reaches in to mid angles (at power 3 the full falloff left the rim at 1.17)
GPOW = {"wool": 3.0, "silk": 1.5}


def main_root():
    out = subprocess.run(["git", "-C", REPO, "rev-parse", "--path-format=absolute", "--git-common-dir"],
                         check=True, capture_output=True, text=True).stdout.strip()
    return os.path.dirname(out)


def prep(d):
    src = os.path.join(main_root(), "data", "build", "t19", "balls")
    os.makedirs(d, exist_ok=True)
    keep = [f for f in os.listdir(src) if f.startswith("cycles_balls") and f.endswith(".png")]
    keep += ["character.glb", "engine_stage.json", "shader_balls.glb", "shader_balls.json", "suit_detail.json",
             "suit_twill_detail.png", "skin_head_curvature.png", "skin_hands_curvature.png"]
    for f in keep:
        p = os.path.join(d, f)
        if not os.path.exists(p) and os.path.exists(os.path.join(src, f)):
            os.symlink(os.path.join(src, f), p)
    print(f"prep: {len(keep)} inputs linked into {d}")


def shots(d, prefix, params=None, lights=LIGHTS):
    for L in lights:
        q = [] if L == "all" else [f"lights={L}"]
        if params:
            q.append("params=" + urllib.parse.quote(json.dumps(params)))
        log = os.path.join(d, f"{prefix}{L}.log")
        with open(log, "w") as f:
            r = subprocess.run(["nice", "-n", "10", "node", os.path.join(REPO, "bench", "m1", "engine_shots.mjs"),
                                "--build", d, "--views", "", "--balls", "on", "--prefix", f"{prefix}{L}_",
                                "--query", "&".join(q), "--port", "8795"], stdout=f, stderr=subprocess.STDOUT)
        if r.returncode:
            raise SystemExit(f"engine shots failed: {log}")


def lum(p):
    return lr._lin_lum(lr._png_rgb(p))


def ratios(d, prefix, quiet=False):
    bj = json.load(open(os.path.join(d, "shader_balls.json")))
    cn = lum(os.path.join(d, "cycles_balls_none_direct.png"))
    en = lum(os.path.join(d, f"{prefix}none_balls.png"))
    yy, xx = np.mgrid[0:cn.shape[0], 0:cn.shape[1]]
    out = {}
    for L in ("key", "fill", "rim"):
        c = lum(os.path.join(d, f"cycles_balls_{L}_direct.png"))
        e = lum(os.path.join(d, f"{prefix}{L}_balls.png"))
        out[L] = {}
        for b in bj["balls"]:
            if "circle_px" not in b:
                continue
            cx, cy, r = b["circle_px"]
            m = (xx + 0.5 - cx) ** 2 + (yy + 0.5 - cy) ** 2 <= (RADIUS[L] * r) ** 2
            mc, me = float((c - cn)[m].mean()), float((e - en)[m].mean())
            out[L][b["material"]] = {"cycles": mc, "engine": me, "ratio": round(me / mc, 3) if mc > 0 else None}
    with open(os.path.join(d, f"{prefix}cloth_ratios.json"), "w") as f:
        json.dump(out, f, indent=1)
    if not quiet:
        for m in KINDS:
            print(f"{prefix} {m:10s} " + "  ".join(f"{L} {out[L][m]['ratio']}" for L in ("key", "fill", "rim")))
    return out


def fit(d):
    """Engine net luminance per ball and light is linear in each kind's sheen scale s and fuzz strength f
    (the sheen node is sheenColor * s; the fuzz term is f x the rim): E = E0 + s Es + f Ef. Three renders
    (s = f = 0; s = 1; f = 1) give the components; each kind then gets the s, f >= 0 minimising the
    squared log ratio over key, fill and rim (the rim counted twice: it is what T6's key-only fit missed)."""
    zero = {k: {"sheenScale": 0.0, "fuzzStrength": 0.0} for k in ("wool", "silk")}
    comp = {}
    for tag, sv, fv, gv in (("c0_", 0.0, 0.0, 0.0), ("cs_", 1.0, 0.0, 0.0), ("cf_", 0.0, 1.0, 0.0),
                            ("cg_", 0.0, 0.0, 1.0)):
        p = {"suitCloth": {k: {"sheenScale": sv, "fuzzStrength": fv, "specGraze": gv, "specGrazePower": GPOW[k]}
                           for k in zero}}
        if not os.path.exists(os.path.join(d, f"{tag}rim_balls.png")):
            shots(d, tag, p)
        comp[tag] = ratios(d, tag, quiet=True)
    res = {}
    for mat, kind in KINDS.items():
        rows = []
        for L, wgt in (("key", 1.0), ("fill", 1.0), ("rim", 2.0)):
            C = comp["c0_"][L][mat]["cycles"]
            e0 = comp["c0_"][L][mat]["engine"]
            es = comp["cs_"][L][mat]["engine"] - e0
            ef = comp["cf_"][L][mat]["engine"] - e0
            eg = comp["cg_"][L][mat]["engine"] - e0
            rows.append((L, wgt, C, e0, es, ef, eg))
        S, F, G = np.meshgrid(np.linspace(0.0, 1.5, 151), np.linspace(0.0, 1.0, 101), np.linspace(0.0, 1.0, 51),
                              indexing="ij")
        err = sum(w * np.log(np.maximum(e0 + S * es + F * ef + G * eg, 1e-9) / C) ** 2
                  for _, w, C, e0, es, ef, eg in rows)
        i = np.unravel_index(np.argmin(err), err.shape)
        s, f, g = float(S[i]), float(F[i]), float(G[i])
        res[kind] = {"sheenScale": round(s, 3), "fuzzStrength": round(f, 3), "specGraze": round(g, 3),
                     "specGrazePower": GPOW[kind],
                     "predicted": {L: round(float((e0 + s * es + f * ef + g * eg) / C), 3)
                                   for L, _, C, e0, es, ef, eg in rows},
                     "components": {L: {"cycles": C, "base": e0, "sheen": es, "fuzz": ef, "graze": eg}
                                    for L, _, C, e0, es, ef, eg in rows}}
        print(kind, res[kind]["sheenScale"], res[kind]["fuzzStrength"], res[kind]["specGraze"], res[kind]["predicted"])
    with open(os.path.join(d, "cloth_fit.json"), "w") as fh:
        json.dump(res, fh, indent=1)
    return res


if __name__ == "__main__":
    cmd, d = sys.argv[1], sys.argv[2]
    if cmd == "prep":
        prep(d)
    elif cmd == "shots":
        shots(d, sys.argv[3], json.loads(sys.argv[4]) if len(sys.argv) > 4 else None)
    elif cmd == "ratios":
        ratios(d, sys.argv[3])
    elif cmd == "fit":
        fit(d)
