#!/usr/bin/env python3
"""Provenance audit (NOTES.md §14). Standard library only, so CI can run it anywhere:

    python3 -I provenance/audit.py                  # schema + licence policy on provenance/*.jsonl
    python3 -I provenance/audit.py --check-files    # also verify sha256 of files under data/
                                                    # and refuse tracked binaries outside the allowlist
    python3 -I provenance/audit.py --release        # also fail on synthetic placeholders

Exit status 1 on any error. Checks:
  * every line parses and matches record.schema.json (the subset of JSON Schema it uses);
  * ids are unique across all manifests;
  * licence is in licences.json 'allow', or in 'note' with a non-empty licence_note;
    licence_url agrees with the licence; deny patterns (NC, ND, Sampling+, ...) never appear;
  * attribution text is present when the licence (or any input's licence) needs it;
  * derived records: every input exists and was not rejected; share-alike propagates
    (a derived file with an SA input must carry that SA licence, and two different SA
    licences cannot mix); otherwise derived assets ship as CC-BY-4.0 (project asset licence).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ASSET_LICENCE = "CC-BY-4.0"


def load_schema() -> dict:
    return json.loads((HERE / "record.schema.json").read_text())


def type_ok(value, t) -> bool:
    types = t if isinstance(t, list) else [t]
    m = {"string": str, "object": dict, "array": list, "boolean": bool, "number": (int, float), "integer": int}
    for name in types:
        py = m[name]
        if name in ("integer", "number") and isinstance(value, bool):
            continue
        if isinstance(value, py):
            return True
    return False


def check_schema(rec: dict, schema: dict) -> list[str]:
    errs = []
    props = schema["properties"]
    required = list(schema["required"])
    for cond in schema.get("allOf", []):
        const = cond["if"]["properties"]["kind"]["const"]
        if rec.get("kind") == const:
            required += cond["then"]["required"]
    for k in required:
        if k not in rec:
            errs.append(f"missing required field '{k}'")
    for k, v in rec.items():
        if k not in props:
            errs.append(f"unknown field '{k}'")
            continue
        p = props[k]
        if "enum" in p and v not in p["enum"]:
            errs.append(f"'{k}'={v!r} not in {p['enum']}")
        if "type" in p and not type_ok(v, p["type"]):
            errs.append(f"'{k}' has wrong type")
            continue
        if "pattern" in p and isinstance(v, str) and not re.search(p["pattern"], v):
            errs.append(f"'{k}'={v!r} does not match {p['pattern']}")
        if p.get("type") == "array" and "items" in p:
            if not all(type_ok(x, p["items"]["type"]) for x in v):
                errs.append(f"'{k}' items have wrong type")
        if p.get("type") == "object" and "properties" in p:
            for sk, sv in v.items():
                sp = p["properties"].get(sk)
                if sp is None:
                    errs.append(f"unknown field '{k}.{sk}'")
                elif not type_ok(sv, sp["type"]):
                    errs.append(f"'{k}.{sk}' has wrong type")
    return errs


def tracked_binary_errors() -> list[str]:
    """Repo-wide binary policy (tools/hooks/binary_policy.py) over `git ls-files`: catches a commit that
    got past the pre-commit hook with --no-verify. Silently skipped when git is missing or this file is
    not at the top of its own git checkout (e.g. an exported tarball)."""
    root = HERE.parent
    try:
        top = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                             capture_output=True, check=True).stdout.decode().strip()
        if Path(top).resolve() != root.resolve():
            return []
        listed = subprocess.run(["git", "-C", str(root), "ls-files", "-z"],
                                capture_output=True, check=True).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.CalledProcessError):
        return []
    sys.path.insert(0, str(root / "tools" / "hooks"))
    try:
        import binary_policy
    except ImportError:
        return []
    finally:
        sys.path.pop(0)
    return [f"git ls-files: {p}: {why}" for p in listed.split("\0")
            if p and (why := binary_policy.binary_problem(p))]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("manifests", nargs="*", type=Path, help="default: provenance/*.jsonl")
    ap.add_argument("--check-files", action="store_true")
    ap.add_argument("--data-root", type=Path, default=HERE.parent / "data")
    ap.add_argument("--release", action="store_true", help="fail on synthetic placeholders")
    a = ap.parse_args()

    schema = load_schema()
    policy = json.loads((HERE / "licences.json").read_text())
    allow, note, deny = policy["allow"], policy["note"], policy["deny_patterns"]
    known = {**allow, **note}

    files = a.manifests or sorted(HERE.glob("*.jsonl"))
    records: dict[str, dict] = {}
    errors: list[str] = []
    warnings: list[str] = []

    for mf in files:
        for n, line in enumerate(mf.read_text().splitlines(), 1):
            if not line.strip():
                continue
            where = f"{mf.name}:{n}"
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                errors.append(f"{where}: invalid JSON ({e})")
                continue
            rid = rec.get("id", "?")
            where = f"{where} [{rid}]"
            errors += [f"{where}: {e}" for e in check_schema(rec, schema)]
            if "path" in rec and "sha256" not in rec:
                errors.append(f"{where}: a record with a local path needs its sha256")
            if rid in records:
                errors.append(f"{where}: duplicate id")
            records[rid] = rec | {"_where": where}

            lic = rec.get("licence", "")
            lic_url = rec.get("licence_url", "")
            blob = f"{lic} {lic_url}".lower()
            for pat in deny:
                if pat in blob:
                    errors.append(f"{where}: disallowed licence ({lic or lic_url}; matches '{pat}')")
            if lic not in known:
                errors.append(f"{where}: licence '{lic}' is not in licences.json allow/note")
                continue
            if lic in note and not rec.get("licence_note", "").strip():
                errors.append(f"{where}: licence '{lic}' needs a licence_note (case-by-case)")
            pats = known[lic]["url_patterns"]
            if lic_url and pats and not any(p in lic_url for p in pats):
                errors.append(f"{where}: licence_url {lic_url} does not match licence {lic}")
            if known[lic]["attribution"] and rec["kind"] == "source" and not rec.get("attribution", "").strip():
                errors.append(f"{where}: licence {lic} needs an attribution line")
            if rec.get("synthetic_placeholder"):
                (errors if a.release else warnings).append(f"{where}: built with a synthetic placeholder")

    for rid, rec in records.items():
        if rec.get("kind") != "derived":
            continue
        where = rec["_where"]
        sa = set()
        needs_attr = False
        for iid in rec.get("inputs", []):
            src = records.get(iid)
            if src is None:
                errors.append(f"{where}: input '{iid}' has no provenance record")
                continue
            if src.get("status") == "rejected":
                errors.append(f"{where}: input '{iid}' was rejected by the quality gate")
            info = known.get(src.get("licence", ""))
            if info is None:
                continue
            if info["share_alike"]:
                sa.add(src["licence"])
            needs_attr |= info["attribution"] or src.get("licence") in note
        lic = rec.get("licence")
        if len(sa) > 1:
            errors.append(f"{where}: mixes incompatible share-alike licences {sorted(sa)}")
        elif sa and lic not in sa:
            errors.append(f"{where}: has share-alike input {sa.pop()} but is licensed {lic}")
        elif not sa and lic not in (PROJECT_ASSET_LICENCE,):
            errors.append(f"{where}: derived asset should be {PROJECT_ASSET_LICENCE}, got {lic}")
        if needs_attr and not rec.get("attribution", "").strip():
            errors.append(f"{where}: an input needs attribution but the record has none")

    if a.check_files:
        for rid, rec in records.items():
            if "path" not in rec or "sha256" not in rec:
                continue
            p = a.data_root / rec["path"]
            if not p.exists():
                warnings.append(f"{rec['_where']}: file not present locally ({p})")
                continue
            h = hashlib.sha256(p.read_bytes()).hexdigest()
            if h != rec["sha256"]:
                errors.append(f"{rec['_where']}: sha256 mismatch for {p}")

    if a.check_files:
        errors += tracked_binary_errors()

    for w in warnings:
        print(f"warning: {w}")
    for e in errors:
        print(f"ERROR: {e}")
    n_src = sum(r.get("kind") == "source" for r in records.values())
    print(f"audit: {len(records)} records ({n_src} source, {len(records) - n_src} derived) "
          f"in {len(files)} manifest(s): {len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
