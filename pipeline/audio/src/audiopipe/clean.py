"""Step 3: clean accepted sources into 48 kHz / 24-bit FLAC working files.

    uv run python -I -m audiopipe.clean

Recipes are per source (decided from the step-2 measurements and spectrograms):
  * trim handling noise at the ends;
  * high-pass rumble (35 Hz ambience, 50 Hz footsteps);
  * de-click (adeclick) on ambience only: on footsteps it would eat the heel transient;
  * denoise (afftdn, noise tracking) on footsteps only: ambience noise *is* the content;
  * EQ (firequalizer, linear phase): ambience gets a 17 kHz low-pass to remove the steady
    19-21 kHz ultrasonic tones (pest repellers / electronics) seen in the takecha and sergeeo
    spectrograms; footsteps get per-source tone shaping;
  * resample to 48 kHz with soxr (precision 28).
Round 2 (human-free bed, NOTES §12) adds a mains retune: Shinjuku is on TEPCO's 50 Hz grid, but
the transformer, neon, vending and air-conditioner recordings carry 60 Hz hum (or 60 Hz induction-
motor speeds, 58-59 Hz). `retune: 60to50` plays them 5/6 as fast (asetrate), which moves the whole
recording down 3.16 semitones so the hum and motor lines land on the 50 Hz family; trims for these
recipes are input-side (-ss/-t before -i) because the output is 1.2x longer.
Outputs: data/build/audio/clean/<slug>.flac plus <slug>.json with the exact filter chain.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import provenance as prov
from .common import BUILD, DATA_ROOT, ffmpeg, log

OUT = BUILD / "clean"

LP17K = "firequalizer=gain_entry='entry(0,0);entry(16000,0);entry(17500,-24);entry(19000,-60);entry(24000,-80)':delay=0.02:accuracy=4"
RESAMPLE = "aresample=48000:resampler=soxr:precision=28"
AMB = f"highpass=f=35:poles=2,adeclick=window=55:overlap=75:threshold=4,{LP17K}"

RECIPES: dict[str, dict] = {
    # ambience: (trim_start_s, trim_end_s)
    "freesound:679335": {"trim": (1.0, 1.0), "chain": AMB},
    "freesound:679333": {"trim": (1.0, 1.0), "chain": AMB},
    "freesound:679334": {"trim": (1.0, 1.0), "chain": AMB},
    "freesound:380726": {"trim": (1.0, 1.0), "chain": AMB},
    "freesound:364865": {"trim": (1.0, 1.0), "chain": AMB},
    "archive:aporee_70134_81690/20251014GareShinjukuLigneJRJSDPA4060binauralDeityPR2.wav": {"trim": (1.0, 1.0), "chain": AMB},
    "freesound:569313": {"trim": (0.5, 0.5), "chain": "highpass=f=30:poles=2"},
    # footsteps: contact mics on the shoes (Yuval) give a boomy, very close thump; tame
    # 90-250 Hz and lift 2-5 kHz air so it sits closer to an airborne recording.
    "freesound:205748": {"trim": (0.0, 0.0), "chain":
        "highpass=f=50:poles=2,afftdn=nr=10:nf=-80:tn=1,"
        "firequalizer=gain_entry='entry(0,-12);entry(60,-6);entry(120,-5);entry(250,-3);entry(500,0);entry(2000,1);entry(4000,3);entry(8000,2);entry(16000,0)':accuracy=4"},
    # MKH-50 airborne recording, quiet (-42 LUFS), noise floor -71 dBFS: denoise a little more.
    "freesound:560478": {"trim": (0.0, 0.0), "chain":
        "highpass=f=50:poles=2,afftdn=nr=12:nf=-72:tn=1"},
    # Artninja: clean, hard ground; edited with digital-silence gaps, so noise tracking on.
    "freesound:742969": {"trim": (0.0, 0.0), "chain":
        "highpass=f=50:poles=2,afftdn=nr=10:nf=-70:tn=1"},
    # ---- round 2: human-free bed (measured mains family in the round-2 report) ----
    "freesound:786004": {"trim": (1.0, 1.0), "chain": "highpass=f=30:poles=2"},
    # wire wind: mic wind rumble below 80 Hz; the last 6 s carry equipment noise
    "freesound:664257": {"trim": (1.0, 6.0), "chain": "highpass=f=80:poles=2"},
    "freesound:454261": {"trim": (0.5, 0.5), "chain": "highpass=f=30:poles=2", "retune": "60to50"},
    "freesound:192240": {"trim": (0.5, 0.5), "chain": "highpass=f=30:poles=2", "retune": "60to50"},
    "freesound:453489": {"trim": (0.5, 0.5), "chain": "highpass=f=80:poles=2", "retune": "60to50"},
    "freesound:641208": {"trim": (0.5, 0.5), "chain": "highpass=f=40:poles=2", "retune": "60to50"},
    "freesound:730438": {"trim": (0.5, 0.5), "chain": "highpass=f=30:poles=2", "retune": "60to50"},
    "freesound:81731": {"trim": (0.5, 0.5), "chain": "highpass=f=40:poles=2"},
    "freesound:612817": {"trim": (0.5, 0.5), "chain": "highpass=f=40:poles=2"},
    "freesound:365257": {"trim": (0.5, 0.5), "chain": "highpass=f=150:poles=2"},
    "freesound:568820": {"trim": (0.0, 0.0), "chain": "highpass=f=300:poles=2"},
    "freesound:386768": {"trim": (0.0, 0.0), "chain": "highpass=f=100:poles=2"},
    "freesound:476139": {"trim": (0.0, 0.0), "chain": "highpass=f=100:poles=2"},
}


def slug_of(rid: str) -> str:
    import re
    return re.sub(r"[^A-Za-z0-9]+", "-", rid).strip("-")[:60]


def full_chain(rid: str, rec: dict) -> str:
    r = RECIPES[rid]
    if r.get("retune") == "60to50":
        sr = rec["original_format"]["sample_rate"]
        return f"asetrate={sr * 5 / 6:.4f},{r['chain']},{RESAMPLE}"
    return f"{r['chain']},{RESAMPLE}"


def clean_one(rid: str, rec: dict) -> Path:
    r = RECIPES[rid]
    src = DATA_ROOT / rec["path"]
    dur = rec["original_format"]["duration_s"]
    t0, t1 = r["trim"]
    chain = full_chain(rid, rec)
    out = OUT / f"{slug_of(rid)}.flac"
    trim = ["-ss", f"{t0}", "-t", f"{dur - t0 - t1:.3f}"]
    io = [*trim, "-i", str(src)] if r.get("retune") else ["-i", str(src), *trim]
    args = [*io, "-af", chain,
            "-ar", "48000", "-sample_fmt", "s32", "-bits_per_raw_sample", "24", "-c:a", "flac",
            "-compression_level", "8", str(out)]
    ffmpeg(*args)
    (OUT / f"{slug_of(rid)}.json").write_text(json.dumps(
        {"id": rid, "trim_s": [t0, t1], "filter_chain": chain, "retune": r.get("retune"),
         "output": str(out.relative_to(BUILD))}, indent=2))
    return out


def transformations(rid: str) -> list[str]:
    r = RECIPES[rid]
    rec = prov.load()[rid]
    out = [f"trim {r['trim'][0]} s head / {r['trim'][1]} s tail", f"ffmpeg -af {full_chain(rid, rec)}"]
    if r.get("retune"):
        out.insert(1, "mains retune 60 -> 50 Hz family: asetrate x5/6 (whole recording -3.16 semitones, 1.2x longer)")
    return out


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated source ids")
    a = ap.parse_args()
    only = set(a.only.split(",")) if a.only else None
    OUT.mkdir(parents=True, exist_ok=True)
    for rid, rec in prov.load().items():
        if rec["kind"] != "source" or rec.get("status") != "accepted" or rid not in RECIPES:
            continue
        if only and rid not in only:
            continue
        log(f"cleaning {rid}")
        clean_one(rid, rec)


if __name__ == "__main__":
    main()
