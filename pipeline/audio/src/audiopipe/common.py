"""Shared paths, secrets handling, rate-limited HTTP and ffmpeg helpers.

Secrets are read from the repo's gitignored .env inside the process. They are
never printed, logged or passed on a command line.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

USER_AGENT = "audio-pipeline/0.1 (open-source game asset pipeline)"


def _checkout_root() -> Path:
    """Main checkout root, also when running from a git worktree."""
    here = Path(__file__).resolve().parent
    out = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=here, capture_output=True, text=True, check=True,
    ).stdout.strip()
    return Path(out).parent


def repo_root() -> Path:
    """Root of the working tree that holds this code (committed files live here)."""
    here = Path(__file__).resolve().parent
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], cwd=here,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return Path(out)


DATA_ROOT = Path(os.environ.get("AUDIO_DATA_ROOT") or (_checkout_root() / "data"))
RAW = DATA_ROOT / "raw" / "audio"
BUILD = DATA_ROOT / "build" / "audio"
ENV_FILE = Path(os.environ.get("AUDIO_ENV_FILE") or (_checkout_root() / ".env"))
REAL_IR = BUILD / "ir" / "alley-01.wav"


def log(*a: object) -> None:
    print(*a, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- secrets

def read_env() -> dict[str, str]:
    d: dict[str, str] = {}
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            d[k] = v
    return d


def freesound_token(min_valid_s: int = 1800) -> str:
    """Return the access token, refreshing it via freesound-auth.sh when close to expiry."""
    env = read_env()
    if int(env.get("FREESOUND_TOKEN_EXPIRES_AT", "0")) - time.time() < min_valid_s:
        script = _checkout_root() / "pipeline" / "freesound-auth.sh"
        res = subprocess.run([str(script), "--refresh"], capture_output=True, text=True)
        last = (res.stdout.strip().splitlines() or [""])[-1]
        if res.returncode != 0 or not last.startswith("ok"):
            raise SystemExit("token refresh failed (output suppressed: may contain secrets)")
        log("token refresh: ok")
        env = read_env()
    return env["FREESOUND_ACCESS_TOKEN"]


# --------------------------------------------------------------------------- http

class RateLimiter:
    """Simple spacing limiter: at most one request per `interval` seconds."""

    def __init__(self, interval: float) -> None:
        self.interval = interval
        self.last = 0.0
        self.count = 0

    def wait(self) -> None:
        dt = time.monotonic() - self.last
        if dt < self.interval:
            time.sleep(self.interval - dt)
        self.last = time.monotonic()
        self.count += 1


def http_get(url: str, headers: dict[str, str] | None = None, limiter: RateLimiter | None = None,
             timeout: float = 60) -> tuple[bytes, dict[str, str], str]:
    """GET returning (body, headers, final_url). Headers may carry secrets; never logged."""
    if limiter:
        limiter.wait()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read(), dict(r.headers.items()), r.geturl()
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(5 * (attempt + 1))
                continue
            raise
        except urllib.error.URLError:
            if attempt < 3:
                time.sleep(5 * (attempt + 1))
                continue
            raise
    raise RuntimeError("unreachable")


def http_json(url: str, headers: dict[str, str] | None = None, limiter: RateLimiter | None = None):
    body, _, _ = http_get(url, headers, limiter)
    return json.loads(body)


# --------------------------------------------------------------------------- ffmpeg

FFMPEG = os.environ.get("FFMPEG", "ffmpeg")
FFPROBE = os.environ.get("FFPROBE", "ffprobe")
THREADS = "3"  # shared machine: cap parallelism


def ffmpeg(*args: str, quiet: bool = True) -> subprocess.CompletedProcess:
    cmd = [FFMPEG, "-hide_banner", "-nostdin", "-y", "-threads", THREADS, "-filter_threads", "1", *args]
    if quiet:
        cmd[1:1] = ["-loglevel", "error"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {' '.join(args)[:400]}\n{res.stderr[-2000:]}")
    return res


def ffmpeg_stderr(*args: str) -> str:
    """Run ffmpeg with info logging and return stderr (for ebur128/astats parsing)."""
    cmd = [FFMPEG, "-hide_banner", "-nostdin", "-threads", THREADS, "-filter_threads", "1", *args]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {res.stderr[-2000:]}")
    return res.stderr


def ffprobe(path: Path) -> dict:
    res = subprocess.run(
        [FFPROBE, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    return json.loads(res.stdout)


def ffmpeg_version() -> str:
    out = subprocess.run([FFMPEG, "-version"], capture_output=True, text=True).stdout
    return out.splitlines()[0].split()[2]


def file_sha256(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
