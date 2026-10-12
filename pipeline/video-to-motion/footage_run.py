"""Shot yield bookkeeping for a footage batch: the expensive NOTES.md §8 filters, then the yield table.

Stages (shot_filter.py has already applied duration / luma / blur and cut the stage-1 survivors to
``private/footage/clips/<clip>-sNNN.mp4``; each clip then ran ``run-bench.sh … --stitch --stop-after yolo``
into ``private/work/runs/<prefix><clip>-sNNN``):

* ``select``: per shot, protagonist track coverage (stitched chain) and subject size (median box height of
  the selected track, source px), plus the manual content review (``--content``: protagonist ID by contact
  sheet, standing in for the face/body-embedding step). Prints the GVHMR list: shots passing coverage,
  subject size and showing Wick.
* ``summary``: after GVHMR + motion_qc.py, adds ViTPose mean confidence and the QC verdict and prints the
  per-clip yield table (markdown) plus a JSON dump.

Everything read here derives from film frames; outputs go under private/.

    python -I footage_run.py select  --clips ID [ID …] --content content.json --out sel.json
    python -I footage_run.py summary --sel sel.json --out yield.json
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np

ROOT = Path(os.environ.get("MAIN_ROOT", "/home/akram/code/or3"))
WICK = ("wick_loco", "wick_action")


def run_dir(prefix: str, name: str) -> Path:
    return ROOT / "private/work/runs" / f"{prefix}{name}"


def subject_px(rd: Path, name: str) -> float | None:
    import torch

    p = rd / name / "preprocess/bbx.pt"
    if not p.exists():
        return None
    xyxy = torch.load(p, weights_only=False)["bbx_xyxy"].numpy()
    return float(np.median(xyxy[:, 3] - xyxy[:, 1]))


def select(a) -> None:
    content = json.loads(Path(a.content).read_text())
    shots = []
    for clip in a.clips:
        u = json.loads((ROOT / f"private/work/shots/{clip}/union.json").read_text())
        label = {i: k for k, v in content[clip].items() for i in v}
        for s in u["shots"]:
            rec = {"clip": clip, "idx": s["idx"], "dur_s": s["dur_s"], "median_luma": s["median_luma"],
                   "median_lapvar": s["median_lapvar"], "fail": list(s["stage1_fail"]), "content": None}
            if not rec["fail"]:
                name = f"{clip}-s{s['idx']:03d}"
                rd = run_dir(a.prefix, name)
                rec |= {"name": name, "content": label.get(s["idx"])}
                t = rd / "timings-yolo.json"  # copy of the YOLO-stage timings (the GVHMR run rewrites timings.json)
                t = t if t.exists() else rd / "timings.json"
                if not t.exists():
                    rec["fail"].append("no_track")
                else:
                    y = json.loads(t.read_text())["stages"].get("yolo_track", {})
                    rec["coverage"] = y.get("selected_frame_coverage")
                    rec["n_tracks"] = y.get("n_tracks")
                    rec["subject_px"] = subject_px(rd, name)
                    if rec["coverage"] is None or rec["coverage"] < a.min_coverage:
                        rec["fail"].append("coverage")
                    if rec["subject_px"] is None or rec["subject_px"] < a.min_subject:
                        rec["fail"].append("subject")
                if rec["content"] not in WICK:
                    rec["fail"].append("content")
            shots.append(rec)
    gv = [s["name"] for s in shots if not s["fail"]]
    params = {"min_coverage": a.min_coverage, "min_subject_px": a.min_subject, "prefix": a.prefix}
    Path(a.out).write_text(json.dumps({"params": params, "shots": shots, "gvhmr": gv}, indent=1))
    print("\n".join(gv))


def summary(a) -> None:
    sel = json.loads(Path(a.sel).read_text())
    prefix = sel["params"]["prefix"]
    for s in sel["shots"]:
        if s.get("name") not in sel["gvhmr"]:
            continue
        rd = run_dir(prefix, s["name"])
        npz = rd / "smplx_params.npz"
        if not npz.exists():
            s["fail"].append("gvhmr_error")
            continue
        conf = np.load(npz)["kp2d"][:, 5:, 2]  # body joints (COCO 5-16), as motion_qc.py
        s["vitpose_conf"] = round(float(conf.mean()), 3)
        if s["vitpose_conf"] < a.min_conf:
            s["fail"].append("vitpose_conf")
        q = ROOT / "private/motion" / f"{prefix}{s['name']}" / "qc.json"
        if not q.exists():
            s["fail"].append("qc_error")
            continue
        qc = json.loads(q.read_text())
        raw, clean = qc["raw"], qc["clean"]
        s["qc"] = {
            "reproj_median_px": raw.get("reproj_median_px"),
            "reproj_rel": None if not raw.get("reproj_median_px") else round(raw["reproj_median_px"] / s["subject_px"], 3),
            "jerk_clean": round(clean["jitter_mean_jerk_m_s3"], 1),
            "spike_frames_raw": raw.get("frames_with_joint_over_1000deg_s"),
            "slide_ik_cm_s": qc["foot_lock_ab"]["ik_lock"]["slide_cm_s"],
        }
        bad = []
        if s["qc"]["reproj_rel"] is None or s["qc"]["reproj_rel"] > a.max_reproj_rel:
            bad.append("reproj")
        if s["qc"]["jerk_clean"] > a.max_jerk:
            bad.append("jitter")
        if (s["qc"]["spike_frames_raw"] or 0) > a.max_spike_frac * s["dur_s"] * 30:
            bad.append("spikes")
        if bad:
            s["fail"].append("qc:" + "+".join(bad))
    sel["summary_params"] = {"min_conf": a.min_conf, "max_reproj_rel": a.max_reproj_rel, "max_jerk": a.max_jerk,
                             "max_spike_frac": a.max_spike_frac}
    Path(a.out).write_text(json.dumps(sel, indent=1))

    print("| clip | shots | ≥1 s | luma | blur | Wick content | coverage ≥ 90 % | subject ≥ 256 px | GVHMR'd | ViTPose ≥ 0.7 | QC-clean | clean s |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for clip in dict.fromkeys(s["clip"] for s in sel["shots"]):
        ss = [s for s in sel["shots"] if s["clip"] == clip]
        alive = ss
        cols = []
        for stage in ("dur", "luma", "blur"):
            alive = [s for s in alive if stage not in s["fail"]]
            cols.append(len(alive))
        alive = [s for s in alive if s["content"] in WICK]
        cols.append(len(alive))
        for stage in ("coverage", "subject"):
            alive = [s for s in alive if stage not in s["fail"] and "no_track" not in s["fail"]]
            cols.append(len(alive))
        cols.append(sum(1 for s in alive if "vitpose_conf" in s))
        alive = [s for s in alive if "vitpose_conf" in s and "vitpose_conf" not in s["fail"]]
        cols.append(len(alive))
        clean = [s for s in alive if not s["fail"]]
        cols.append(len(clean))
        cols.append(round(sum(s["dur_s"] for s in clean), 1))
        print(f"| {clip} | {len(ss)} | " + " | ".join(map(str, cols)) + " |")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("select")
    p.add_argument("--clips", nargs="+", required=True)
    p.add_argument("--content", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--prefix", default="fr-")
    p.add_argument("--min-coverage", type=float, default=0.9)
    p.add_argument("--min-subject", type=float, default=256)
    p = sub.add_parser("summary")
    p.add_argument("--sel", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--min-conf", type=float, default=0.7)
    p.add_argument("--max-reproj-rel", type=float, default=0.05, help="median reprojection error / subject height")
    p.add_argument("--max-jerk", type=float, default=150.0, help="mean |jerk| after cleanup (m/s^3)")
    p.add_argument("--max-spike-frac", type=float, default=0.02, help="share of frames with a joint > 1000 deg/s")
    a = ap.parse_args()
    select(a) if a.cmd == "select" else summary(a)


if __name__ == "__main__":
    main()
