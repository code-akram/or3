"""Write the made suit's cache record (blender/character/suit_made.py) from a posed (rig) run.

    python3 -I bench/m1/v4/suit_made_cache.py POSED_RUN [--twin KEY=RUN ...] [--hash H] [--check]

POSED_RUN is a suit_spike --posed run; its spike_stats.json names the jacket run, which names the
trousers, shirt and waistcoat runs. The body hash is read from body_hash.txt in any of the runs
(suit_spike writes it from the captured body) unless --hash gives it. --twin adds a determinism
twin per key (trousers, shirt, waistcoat, jacket, posed). The record goes to
<data>/build/suit_cache/<hash>.json; --check prints the guards' verdict without writing.
"""

import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "blender"))
from character import suit_made  # noqa: E402


def stats(run):
    with open(os.path.join(run, "spike_stats.json")) as f:
        return json.load(f)


def runs_of(posed):
    st = stats(posed)
    root = os.path.dirname(posed.rstrip("/"))
    out = {"posed": posed, "jacket": os.path.join(root, st["run"])}
    for k, v in st.get("runs", {}).items():
        out[k] = os.path.join(root, v)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("posed")
    ap.add_argument("--twin", action="append", default=[])
    ap.add_argument("--hash")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    runs = runs_of(os.path.abspath(a.posed))
    h = a.hash
    for r in runs.values():
        p = os.path.join(r, "body_hash.txt")
        if h is None and os.path.exists(p):
            h = open(p).read().strip()
    twins = dict(t.split("=", 1) for t in a.twin)
    for k, r in twins.items():
        p = os.path.join(r, "body_hash.txt")
        if h is None and os.path.exists(p):
            h = open(p).read().strip()
    if h is None:
        raise SystemExit("no body hash: pass --hash or rerun a spike that writes body_hash.txt")
    head = subprocess.run(["git", "-C", REPO, "rev-parse", "--short", "HEAD"], capture_output=True,
                          text=True).stdout.strip()
    rec = {"body_hash": h, "runs": runs, "twins": {k: os.path.abspath(v) for k, v in twins.items()},
           "commit": head}
    ok, rep = suit_made.guards(rec, h)
    rec["guards"] = rep
    print(json.dumps({"ok": ok, "failures": rep["failures"]}, indent=1))
    if not a.check:
        root = suit_made.cache_root(suit_made.data_root())
        os.makedirs(root, exist_ok=True)
        with open(os.path.join(root, f"{h}.json"), "w") as f:
            json.dump(rec, f, indent=1)
        print(os.path.join(root, f"{h}.json"))


if __name__ == "__main__":
    main()
