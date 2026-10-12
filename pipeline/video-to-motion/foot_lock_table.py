"""Summarise the foot-lock A/B from motion_qc.py's qc.json files as a Markdown table.

    python -I foot_lock_table.py private/motion/walk-fp32 private/motion/osaka-bf16 ...

Per clip, it prints a row for each of raw / smoothed (One Euro) / root lock (first version) / IK lock (default):
slide on contact frames (same contact labels for every variant; foot point and pivot), travel kept vs raw (2 Hz low-passed root
path), net displacement vs raw, mean |jerk|, and, for the IK lock, knee-pop counts and the root drop.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    print("| clip | variant | slide in contact, foot / pivot (cm/s) | travel vs raw (path / net) | jitter (m/s³) | knees |")
    print("|---|---|---|---|---|---|")
    for d in sys.argv[1:]:
        q = json.loads((Path(d) / "qc.json").read_text())
        ab = q["foot_lock_ab"]
        k, info = ab["ik_knees"], ab["ik_info"]
        name = Path(d).name
        for v, label in (("raw", "raw GVHMR"), ("smoothed", "One Euro"), ("root_lock", "root lock (v1)"),
                         ("ik_lock", "**IK lock (v2)**")):
            if v not in ab:
                continue
            r = ab[v]
            knees = ""
            if v == "ik_lock":
                knees = (f"p99 {k['knee_speed_p99_before_deg_s']:.0f}→{k['knee_speed_p99_after_deg_s']:.0f} °/s; "
                         f">500 °/s frames {k['pop_frames_before']}→{k['pop_frames_after']} "
                         f"(new {k['new_pop_frames']}); root drop max {info['root_drop_max_cm']:.1f} cm")
            print(f"| {name} | {label} | {r['slide_cm_s']:.1f} / {r['pivot_slide_cm_s']:.1f} | {r['travel_vs_raw_pct']:.1f}% / {r['net_vs_raw_pct']:.1f}% "
                  f"| {r['jitter_mean_jerk_m_s3']:.0f} | {knees} |")
        print(f"| {name} | contacts | L {info['n_contacts']['left']} / R {info['n_contacts']['right']} segments, "
              f"{100 * info['contact_frac']['left']:.0f}% / {100 * info['contact_frac']['right']:.0f}% of frames; "
              f"pin error mean {info['pin_err_mean_mm']:.1f} mm, max {info['pin_err_max_mm']:.1f} mm | | | |")


if __name__ == "__main__":
    main()
