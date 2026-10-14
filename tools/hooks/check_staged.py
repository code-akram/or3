"""Check the staged changes for likeness leaks (stdlib only; run by tools/hooks/pre-commit).

Refuses, for every added, copied, modified or renamed path in the index:

  * a path naming "fan" or "likeness" (any case) outside the allowlist below: the generic likeness
    code and the track docs are tracked; fan configs, deltas, boards and renders never are;
  * a binary image, array, mesh or video under bench/ (reports link to private/ or data/ instead);
  * a .json / .jsonl blob carrying likeness content as pipeline/likeness/containment.py defines it:
    a "fan" key at any depth or a string naming private/likeness/ (e.g. a fan build's stats config
    copied into provenance/mesh.jsonl). Malformed JSON is checked for those markers as text.

Exits 1 with one line per refused path; NOTES.md §14 rule 7 has the rule.
"""

import re
import subprocess
import sys
from pathlib import Path


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, check=True).stdout


TOP = Path(git("rev-parse", "--show-toplevel").decode().strip())
sys.path.append(str(TOP / "pipeline" / "likeness"))
import containment  # noqa: E402

NAMED = re.compile(r"fan|likeness", re.I)
ALLOWED = [re.compile(p) for p in (
    r"^pipeline/likeness/[^/]+\.(py|sh)$",  # generic likeness code: every input and output is a private path
    r"^blender/character/head_fan\.py$",    # the fan layer's build stage (no data in it)
    r"^bench/m1/v\d+/[^/]+\.md$",           # track briefs and reports (text only)
)]
BENCH_BINARY = re.compile(r"^bench/.*\.(png|jpe?g|webp|gif|bmp|tiff?|exr|hdr|npz|npy|pt|pth|pkl|obj|ply|"
                          r"glb|gltf|fbx|blend|mp4|mov|mkv|webm)$", re.I)
TEXT_MARKERS = re.compile(r'"fan"\s*:|' + re.escape(containment.MARKER))


def problems(path):
    if NAMED.search(path) and not any(a.match(path) for a in ALLOWED):
        yield "likeness-named path outside the allowlist"
    if BENCH_BINARY.match(path):
        yield "binary image / array / mesh under bench/"
    if path.endswith((".json", ".jsonl")):
        text = git("cat-file", "blob", f":{path}").decode("utf-8", "replace")
        try:
            hits = containment.text_likeness(text)
        except ValueError:
            hits = [m.group(0) for m in TEXT_MARKERS.finditer(text)]
        if hits:
            yield f"JSON carries likeness content ({', '.join(hits[:3])})"


def main():
    staged = git("diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR").decode().split("\0")
    bad = [(p, why) for p in staged if p for why in problems(p)]
    for p, why in bad:
        print(f"pre-commit: refusing {p}: {why}", file=sys.stderr)
    if bad:
        print("pre-commit: likeness content stays in private/ (NOTES.md §14 rule 7; tools/hooks/check_staged.py)",
              file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
