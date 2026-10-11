"""Step 1: scripted, licence-filtered fetch with one provenance record per file.

    uv run python -I -m audiopipe.fetch            # everything in sources.toml
    uv run python -I -m audiopipe.fetch --dry-run  # metadata + licence check only

Every download lands in its own new directory under data/raw/audio/{freesound,archive}/.
Already-fetched files whose sha256 matches the manifest are skipped.
Freesound originals need the OAuth2 bearer token (read from .env, never printed).
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import tomllib
import urllib.parse
import urllib.request
from pathlib import Path

from . import provenance as prov
from .common import RAW, RateLimiter, USER_AGENT, ffprobe, file_sha256, freesound_token, http_json, log

API = "https://freesound.org/apiv2"
SOURCES = Path(__file__).resolve().parents[2] / "sources.toml"
fs_limit = RateLimiter(2.0)   # <= 30 req/min (limit is 60/min, 2000/day)
ia_limit = RateLimiter(1.0)


def safe_name(name: str) -> str:
    base = Path(name).name
    return re.sub(r"[^A-Za-z0-9._-]", "_", base)[:120] or "file"


def download(url: str, dest: Path, bearer: str | None, limiter: RateLimiter) -> tuple[int, str]:
    """Stream to dest. The bearer header is unredirected so it never follows a redirect off-host."""
    limiter.wait()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    if bearer:
        req.add_unredirected_header("Authorization", f"Bearer {bearer}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    n = 0
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
        final = r.geturl()
        while chunk := r.read(1 << 20):
            f.write(chunk)
            n += len(chunk)
    tmp.rename(dest)
    return n, final


def probe_format(path: Path) -> dict:
    info = ffprobe(path)
    st = next(s for s in info["streams"] if s["codec_type"] == "audio")
    bd = st.get("bits_per_raw_sample") or st.get("bits_per_sample") or 0
    try:
        bd = int(bd)
    except ValueError:
        pass
    if not bd:
        bd = st.get("sample_fmt", "")
    return {
        "container": info["format"]["format_name"],
        "codec": st["codec_name"],
        "sample_rate": int(st["sample_rate"]),
        "bit_depth": bd,
        "channels": int(st["channels"]),
        "duration_s": round(float(info["format"].get("duration") or st.get("duration") or 0), 3),
    }


def already_have(rid: str) -> bool:
    rec = prov.load().get(rid)
    if not rec or "path" not in rec:
        return False
    p = prov.DATA_ROOT / rec["path"]
    return p.exists() and file_sha256(p) == rec.get("sha256")


def fetch_freesound(entry: dict, dry: bool, today: str) -> None:
    sid = int(entry["id"])
    rid = f"freesound:{sid}"
    tok = freesound_token()
    hdr = {"Authorization": f"Bearer {tok}"}
    fields = "id,name,username,license,type,samplerate,bitdepth,channels,duration,filesize,url,geotag,tags,description,pack"
    meta = http_json(f"{API}/sounds/{sid}/?fields={fields}", hdr, fs_limit)
    try:
        spdx, tier = prov.licence_from_url(meta["license"])
    except prov.LicenceRejected as e:
        log(f"SKIP {rid}: {e}")
        return
    log(f"{rid}: {meta['name']!r} by {meta['username']} [{spdx}/{tier}] {meta['type']} "
        f"{meta['samplerate']}Hz {meta['duration']:.1f}s")
    if dry:
        return
    if already_have(rid):
        log("  have it (sha256 matches manifest)")
        return
    d = RAW / "freesound" / str(sid)
    d.mkdir(parents=True, exist_ok=True)
    dest = d / f"{sid}.{safe_name(meta['type'])}"
    dl_url = f"{API}/sounds/{sid}/download/"
    n, _ = download(dl_url, dest, tok, fs_limit)
    if meta.get("filesize") and n != meta["filesize"]:
        log(f"  WARNING size {n} != API filesize {meta['filesize']}")
    rec = {
        "id": rid, "kind": "source", "domain": "audio",
        "title": meta["name"],
        "licence": spdx, "licence_url": meta["license"],
        "author": meta["username"],
        "attribution": f"\"{meta['name']}\" by {meta['username']} ({meta['url']}), {spdx}",
        "source_url": meta["url"],
        "download_url": dl_url,
        "retrieved_or_built": today,
        "original_format": probe_format(dest),
        "path": prov.rel(dest), "bytes": n, "sha256": file_sha256(dest),
        "status": "pending",
        "transformations": [],
    }
    if tier == "note":
        rec["licence_note"] = entry.get("licence_note", "")
    prov.upsert(rec)
    log(f"  saved {n/1e6:.1f} MB -> {dest}")


def fetch_archive(entry: dict, dry: bool, today: str) -> None:
    ident, fname = entry["identifier"], entry["file"]
    rid = f"archive:{ident}/{fname}"
    meta = http_json(f"https://archive.org/metadata/{urllib.parse.quote(ident)}", limiter=ia_limit)
    m = meta["metadata"]
    lic_url = m.get("licenseurl", "")
    try:
        spdx, tier = prov.licence_from_url(lic_url)
    except prov.LicenceRejected as e:
        log(f"SKIP {rid}: {e}")
        return
    f = next((x for x in meta["files"] if x["name"] == fname), None)
    if f is None:
        log(f"SKIP {rid}: file not in item")
        return
    log(f"{rid}: {m.get('title')!r} by {m.get('creator')} [{spdx}/{tier}] {f.get('format')} source={f.get('source')}")
    if dry:
        return
    if already_have(rid):
        log("  have it (sha256 matches manifest)")
        return
    d = RAW / "archive" / safe_name(ident)
    d.mkdir(parents=True, exist_ok=True)
    dest = d / safe_name(fname)
    dl_url = f"https://archive.org/download/{urllib.parse.quote(ident)}/{urllib.parse.quote(fname)}"
    n, _ = download(dl_url, dest, None, ia_limit)
    creator = m.get("creator") or "unknown"
    if isinstance(creator, list):
        creator = ", ".join(creator)
    creator = re.sub(r"@\S+", "@…", creator)  # aporee sometimes exposes e-mail addresses
    page = f"https://archive.org/details/{ident}"
    rec = {
        "id": rid, "kind": "source", "domain": "audio",
        "title": str(m.get("title")),
        "licence": spdx, "licence_url": lic_url,
        "author": creator,
        "attribution": f"\"{m.get('title')}\" by {creator}, radio aporee ::: maps via Internet Archive ({page}), {spdx}",
        "source_url": page,
        "download_url": dl_url,
        "retrieved_or_built": today,
        "original_format": probe_format(dest),
        "path": prov.rel(dest), "bytes": n, "sha256": file_sha256(dest),
        "status": "pending",
        "transformations": [],
    }
    if tier == "note":
        rec["licence_note"] = entry.get("licence_note", "")
    if f.get("source") != "original":
        rec["transformations"].append(f"file is an Internet Archive '{f.get('source')}' of the uploaded original")
    prov.upsert(rec)
    log(f"  saved {n/1e6:.1f} MB -> {dest}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", help="comma-separated ids/identifiers")
    a = ap.parse_args()
    cfg = tomllib.loads(SOURCES.read_text())
    today = dt.date.today().isoformat()
    only = set(a.only.split(",")) if a.only else None
    for e in cfg.get("freesound", []):
        if only and str(e["id"]) not in only:
            continue
        fetch_freesound(e, a.dry_run, today)
    for e in cfg.get("archive", []):
        if only and e["identifier"] not in only:
            continue
        fetch_archive(e, a.dry_run, today)
    log(f"requests: freesound={fs_limit.count} archive={ia_limit.count}")


if __name__ == "__main__":
    main()
