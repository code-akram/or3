#!/usr/bin/env bash
# Fetch the official YouTube footage with the user's browser cookies: the single user step.
#
# Why cookies: this machine's IPv4 and IPv6 both belong to Hetzner (AS24940, a hosting network).
# YouTube answers every player client from datacenter ranges with "Sign in to confirm you're not a
# bot". Measured 2026-10-12 with yt-dlp 2026.08.19 (pacman) and the 2026.10.10 nightly, over -4 and -6,
# with the player clients default, tv, web_safari, android_vr, mweb, ios, web_embedded, tv_simply and
# web_creator, and with the bgutil PO-token provider (tokens were generated, the wall stayed). The
# yt-dlp docs say a PO token does not lift IP-based sign-in walls, so cookies are the documented route.
#
# User step (once): export youtube.com cookies in Netscape format from a logged-in browser on the Mac
# to /home/akram/code/or3/private/youtube-cookies.txt (mode 600). See bench/m0/spike-3-gvhmr.md,
# "Follow-up (completion)", for the exact export + scp commands.
#
# Usage: pipeline/video-to-motion/fetch-youtube.sh [ID ...]   (IDs from fetch-footage.sh; default: all yt-*)
# The cookies file is never printed. Only its path is passed to yt-dlp (never its contents).
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
main_root="${MAIN_ROOT:-/home/akram/code/or3}"
cookies="${YT_COOKIES:-$main_root/private/youtube-cookies.txt}"
venv="$main_root/private/tools/yt-dlp"

# --- 1. check the cookies file without printing it
[[ -f "$cookies" ]] || { echo "missing: $cookies (see the export steps in bench/m0/spike-3-gvhmr.md)"; exit 2; }
mode=$(stat -c %a "$cookies")
if [[ "$mode" != 600 && "$mode" != 400 ]]; then
  echo "refusing: $cookies has mode $mode; run: chmod 600 '$cookies'"
  exit 2
fi
python3 -I - "$cookies" <<'EOF'
import sys
path = sys.argv[1]
with open(path, encoding="utf-8", errors="replace") as f:
    lines = f.read().splitlines()
head = lines[0].strip() if lines else ""
rows = [l for l in lines if l.strip() and (not l.startswith("#") or l.startswith("#HttpOnly_"))]
ok7 = [l for l in rows if len(l.split("\t")) == 7]
yt = [l for l in ok7 if "youtube.com" in l.split("\t")[0]]
names = {l.split("\t")[5] for l in yt}
auth = sorted(n for n in names if n in {"SID", "__Secure-1PSID", "__Secure-3PSID", "SAPISID", "LOGIN_INFO"})
print(f"cookies: header={'ok' if 'HTTP Cookie File' in head else 'MISSING'} rows={len(rows)} "
      f"tab7={len(ok7)} youtube={len(yt)} auth_cookie_names={len(auth)}")
if "HTTP Cookie File" not in head and len(ok7) != len(rows):
    sys.exit("not a Netscape cookies file (expected '# Netscape HTTP Cookie File' and 7 tab-separated fields)")
if not yt:
    sys.exit("no youtube.com cookies in the file: export from a browser tab logged in to youtube.com")
if not auth:
    print("warning: no login cookies (SID/SAPISID/LOGIN_INFO): the bot wall will likely remain")
EOF

# --- 2. current yt-dlp (nightly) in its own venv under private/ (no system changes)
if [[ ! -x "$venv/bin/yt-dlp" ]]; then
  uv venv -q --python 3.13 "$venv"
  uv pip install -q --python "$venv/bin/python" --prerelease=allow -U "yt-dlp[default]"
fi
echo "yt-dlp $("$venv/bin/yt-dlp" --version)"

# --- 3. fetch (fetch-footage.sh appends YTDLP_EXTRA to every yt-dlp call)
ids=("$@")
((${#ids[@]})) || ids=($(grep -oE '"yt-[A-Za-z0-9_-]+' "$here/fetch-footage.sh" | tr -d '"'))
YTDLP="$venv/bin/yt-dlp" YTDLP_EXTRA="--cookies $cookies" "$here/fetch-footage.sh" "${ids[@]}"
chmod 600 "$cookies"  # yt-dlp rewrites the jar on exit; keep it private
rc=0
for id in "${ids[@]}"; do
  f=$(ls "$main_root/private/footage/$id"/source.* 2>/dev/null | grep -v json | head -1 || true)
  if [[ -n "$f" ]]; then
    echo "$id: $(ffprobe -v error -select_streams v:0 -show_entries stream=width,height,r_frame_rate -of csv=p=0 "$f")"
  else
    echo "$id: not downloaded"
    rc=1
  fi
done
exit $rc
