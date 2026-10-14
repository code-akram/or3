"""Likeness containment (NOTES.md §14 rule 7): likeness and identity outputs stay in private/.

Stdlib only, so it imports under Blender's Python (blender/build_character.py,
pipeline/likeness/clay_views.py), the likeness and video-to-motion envs, and plain python3 -I
(bench/m1, the pre-commit hook in tools/hooks/); the shell wrappers run it as a CLI.

The rule for any writer of likeness or identity data (fan builds and their renders, fitted shapes,
face deltas, reference crops, landmarks, face/body embeddings, footage-derived motion):
the output path, with symlinks resolved, must be

  * under <main checkout>/private/, or
  * outside every git work tree, in a directory that is ours and closed to group and others
    (the directory the output lands in, or its nearest existing parent, is mode 700: a
    mkdtemp() scratch dir qualifies, a bare /tmp does not).

Everything else is refused: data/, any tracked directory, a worktree, another clone, a world- or
group-readable directory. Worktrees share the main checkout's private/, which is found through
git rev-parse --git-common-dir, so a worktree has no private/ of its own.

"Likeness content" in a JSON document (build stats, lookdev metrics, compare.json, a --config
file): a "fan" key at any depth (the fan layer, build_character.py --fan) or a string naming
private/likeness/.

    python3 -I containment.py check PATH...   exit 0 when every PATH is an allowed output
    python3 -I containment.py clean FILE...   exit 0 only when every FILE is readable JSON with no
                                              likeness content; a missing, unreadable or malformed
                                              file is not clean (callers fail closed on any non-zero)
"""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

MARKER = "private/likeness"
_ROOT = None


class ContainmentError(SystemExit):
    """A refused output path. A SystemExit, so a broad `except Exception` cannot swallow it; uncaught
    it prints the message and exits 1 (also under blender -b without --python-exit-code)."""


def main_root():
    """The main checkout (git common dir's parent): its private/ is the only private/."""
    global _ROOT
    if _ROOT is None:
        try:
            r = subprocess.run(["git", "-C", os.path.dirname(os.path.abspath(__file__)), "rev-parse",
                                "--path-format=absolute", "--git-common-dir"],
                               capture_output=True, text=True, check=True)
        except (OSError, subprocess.CalledProcessError) as e:
            raise ContainmentError(f"containment: cannot locate the main checkout ({e})") from None
        _ROOT = Path(os.path.realpath(os.path.dirname(r.stdout.strip())))
    return _ROOT


def private_root():
    return main_root() / "private"


def _under(p, root):
    return p == root or root in p.parents


def is_private(path):
    """True when path (symlinks resolved) is under <main checkout>/private/."""
    return _under(Path(os.path.realpath(path)), Path(os.path.realpath(private_root())))


def _in_work_tree(p):
    return any((d / ".git").exists() for d in (p, *p.parents))


def _nearest_dir(p):
    d = p if p.is_dir() else p.parent
    while not d.exists():
        d = d.parent
    return d


def why_not_private(path):
    """None when path is an allowed likeness output, else the reason it is refused."""
    p = Path(os.path.realpath(path))
    if _under(p, Path(os.path.realpath(private_root()))):
        return None
    if _under(p, main_root()):
        return f"{p} is inside the repo but not under {private_root()}/"
    if _in_work_tree(p):
        return f"{p} is inside a git work tree"
    d = _nearest_dir(p)
    st = d.stat()
    if st.st_uid != os.getuid() or st.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        return f"{p}: {d} is mode {stat.S_IMODE(st.st_mode):o} (owner uid {st.st_uid}); outside private/ " \
               f"a likeness output needs a directory of yours at mode 700"
    return None


def assert_private(path, what="likeness output"):
    """Refuse (ContainmentError) unless path is an allowed likeness output; returns the resolved path."""
    why = why_not_private(path)
    if why:
        raise ContainmentError(f"refusing {what}: {why} (NOTES.md §14 rule 7; see {__file__})")
    return Path(os.path.realpath(path))


def assert_outputs(args, *names):
    """assert_private() every non-empty argparse attribute among names (e.g. "out", "obj")."""
    for n in names:
        if getattr(args, n, None):
            assert_private(getattr(args, n), "--" + n.replace("_", "-"))


def likeness(obj, where="$"):
    """JSON paths in obj that carry likeness content: "fan" keys and strings naming private/likeness/."""
    hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "fan":
                hits.append(f"{where}.fan")
            hits += likeness(v, f"{where}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits += likeness(v, f"{where}[{i}]")
    elif isinstance(obj, str) and MARKER in obj:
        hits.append(where)
    return hits


def file_likeness(path):
    """likeness() of a JSON (or JSON-lines) file; raises OSError / ValueError when unreadable."""
    return text_likeness(Path(path).read_text())


def text_likeness(text):
    """likeness() of JSON or JSON-lines text; raises ValueError when it is neither."""
    try:
        return likeness(json.loads(text))
    except json.JSONDecodeError:
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if not lines:
            raise
        return [h for n, ln in enumerate(lines, 1) for h in likeness(json.loads(ln), f"line{n}")]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 2 or argv[0] not in ("check", "clean"):
        print(__doc__.split("\n\n")[-1], file=sys.stderr)
        return 2
    bad = 0
    for p in argv[1:]:
        if argv[0] == "check":
            why = why_not_private(p)
        else:
            try:
                hits = file_likeness(p)
                why = f"{p} carries likeness content at {', '.join(hits[:4])}" if hits else None
            except (OSError, ValueError) as e:
                why = f"{p} unreadable ({type(e).__name__}): treated as likeness content"
        if why:
            print(f"containment: {why}", file=sys.stderr)
            bad += 1
    return 3 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
