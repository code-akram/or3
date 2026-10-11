"""Read/write provenance/audio.jsonl and map licence URLs to SPDX ids via provenance/licences.json."""

from __future__ import annotations

import json
from pathlib import Path

from .common import DATA_ROOT, repo_root

PROV_DIR = repo_root() / "provenance"
MANIFEST = PROV_DIR / "audio.jsonl"


def policy() -> dict:
    return json.loads((PROV_DIR / "licences.json").read_text())


class LicenceRejected(Exception):
    pass


def licence_from_url(url: str) -> tuple[str, str]:
    """Return (spdx_id, tier) where tier is 'allow' or 'note'. Raise LicenceRejected otherwise."""
    pol = policy()
    low = url.lower()
    for pat in pol["deny_patterns"]:
        if pat in low:
            raise LicenceRejected(f"{url} matches deny pattern '{pat}'")
    for tier in ("allow", "note"):
        for spdx, info in pol[tier].items():
            if any(p in low for p in info["url_patterns"]):
                return spdx, tier
    raise LicenceRejected(f"{url} is not a known allowed licence")


def load() -> dict[str, dict]:
    recs: dict[str, dict] = {}
    if MANIFEST.exists():
        for line in MANIFEST.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                recs[r["id"]] = r
    return recs


def save(recs: dict[str, dict]) -> None:
    # Sources first (in insertion order), then derived; stable and diff-friendly.
    ordered = [r for r in recs.values() if r["kind"] == "source"] + \
              [r for r in recs.values() if r["kind"] == "derived"]
    MANIFEST.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=False) + "\n" for r in ordered))


def upsert(rec: dict) -> None:
    recs = load()
    recs[rec["id"]] = rec
    save(recs)


def update(rid: str, **fields) -> None:
    recs = load()
    recs[rid].update(fields)
    save(recs)


def rel(path: Path) -> str:
    return str(Path(path).resolve().relative_to(DATA_ROOT.resolve()))
