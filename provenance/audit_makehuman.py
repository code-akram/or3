"""Per-file licence audit of MakeHuman asset packs (NOTES.md §14 rule 5).

MakeHuman packs are labelled CC0 at pack level, but individual files can carry
AGPL or CC-BY headers. This scans every file under each given data root and
classifies it by the licence statements in its own text, then cross-checks the
pack JSON (packs/*.json) for each asset directory.

Run with an isolated interpreter (the inputs are untrusted downloads):
    uv run --no-project --python 3.12 python -I provenance/audit_makehuman.py \
        --out data/build/provenance/makehuman_audit.csv ROOT [ROOT ...]

Exit status is 1 if any file is flagged (non-CC0 licence text found).
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path

TEXT_EXT = {".mhclo", ".mhmat", ".obj", ".proxy", ".mhw", ".json", ".mhskel",
            ".mhpxy", ".mhm", ".target", ".bvh", ".txt", ".mhcfg"}
# Patterns that indicate something other than CC0.
FLAG = re.compile(r"\b(a?gpl|affero|gnu general|cc[- ]?by|attribution|"
                  r"creative\s*commons|non-?commercial|share-?alike)\b", re.I)
CC0_LINE = re.compile(r"^\s*#?\s*licen[cs]e\s+cc0\b", re.I | re.M)
CC0_RELEASE = re.compile(r"explicitly released as CC0", re.I)
LICENSE_LINE = re.compile(r"^\s*#?\s*licen[cs]e\s+(.+)$", re.I | re.M)
AUTHOR_LINE = re.compile(r"^\s*#?\s*author\s+(.+)$", re.I | re.M)
HEAD_BYTES = 8192


def pack_metadata(root: Path) -> dict:
    meta = {}
    for pj in sorted((root / "packs").glob("*.json")):
        try:
            data = json.loads(pj.read_text(encoding="utf-8", errors="replace"))
        except ValueError:
            continue
        for name, entry in data.items():
            if isinstance(entry, dict):
                meta[name] = entry
    return meta


def classify(path: Path) -> tuple[str, str, str]:
    """Return (class, licence_text, author_text) from the file's own header."""
    if path.suffix.lower() not in TEXT_EXT:
        return ("binary-no-header", "", "")
    head = path.read_bytes()[:HEAD_BYTES].decode("utf-8", errors="replace")
    # Only comment/header lines can carry licence text; skip geometry data.
    header = "\n".join(l for l in head.splitlines()
                       if l.lstrip().startswith(("#", "//", "\"", "{"))
                       or re.match(r"^\s*(licen[cs]e|author|copyright)\b", l, re.I))
    lic = "; ".join(m.strip() for m in LICENSE_LINE.findall(header))
    auth = "; ".join(m.strip() for m in AUTHOR_LINE.findall(header))
    if path.suffix.lower() == ".json":
        lics = set(re.findall(r'"license"\s*:\s*"([^"]*)"', head))
        lic = ",".join(sorted(lics))
        if lics and lics <= {"CC0"}:
            return ("cc0-json", lic, "")
    flag = FLAG.search(header)
    if flag:
        return (f"FLAG:{flag.group(0)}", lic, auth)
    if CC0_LINE.search(header):
        return ("cc0-line", lic, auth)
    if CC0_RELEASE.search(header):
        return ("cc0-release-header", "CC0 (MH 2020 release header)", auth)
    return ("text-no-licence", lic, auth)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("roots", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    rows, flagged = [], 0
    summary: dict[tuple[str, str], int] = {}
    for root in args.roots:
        meta = pack_metadata(root)
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            rel = path.relative_to(root)
            asset = rel.parts[1] if len(rel.parts) > 2 else ""
            cls, lic, auth = classify(path)
            m = meta.get(asset) or meta.get(Path(asset).stem) or {}
            pack_lic = m.get("license", "")
            if pack_lic and pack_lic != "CC0":
                cls = f"FLAG:pack-licence-{pack_lic}"
            if cls.startswith("FLAG"):
                flagged += 1
            summary[(root.name if root.name != "unpacked" else root.parent.name, cls)] = \
                summary.get((root.name if root.name != "unpacked" else root.parent.name, cls), 0) + 1
            rows.append({"root": str(root), "file": str(rel), "asset": asset,
                         "class": cls, "file_licence": lic, "file_author": auth,
                         "pack_licence": pack_lic, "pack_author": m.get("author", ""),
                         "pack_source": m.get("source", "")})

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    for (pack, cls), n in sorted(summary.items()):
        print(f"{pack:28s} {cls:28s} {n:5d}")
    print(f"files={len(rows)} flagged={flagged} -> {args.out}")
    return 1 if flagged else 0


if __name__ == "__main__":
    sys.exit(main())
