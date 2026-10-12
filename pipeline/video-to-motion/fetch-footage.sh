#!/usr/bin/env bash
# Fetch official John Wick clips (studio-uploaded, or studio-supplied and press-hosted) into private/footage/<id>/ (gitignored).
# Footage never enters git (NOTES.md §8, §14). Only official sources are listed here.
#
# Usage: pipeline/video-to-motion/fetch-footage.sh [ID ...]
#   With no arguments, fetches every candidate below.
#
# Note (2026-10-12): this machine's IPs are Hetzner datacenter ranges, and YouTube answers every
# player client (IPv4 and IPv6, current nightly, with PO tokens) with "Sign in to confirm you're not
# a bot". The Lionsgate Movies YouTube entries therefore need browser cookies: use
# fetch-youtube.sh, which checks private/youtube-cookies.txt and calls this script.
# The Lionsgate UK TikTok entries download without auth.
# YTDLP overrides the yt-dlp binary. With --cookies in YTDLP_EXTRA no info.json is written
# (yt-dlp copies cookie values into the formats in it); a cookie-free meta.txt is written instead.
set -euo pipefail

# Worktrees share the main checkout's private/ directory.
main_root="${MAIN_ROOT:-/home/akram/code/or3}"
footage_dir="$main_root/private/footage"

# id|url|channel|title|section (yt-dlp --download-sections spec, or "full")
candidates=(
  # Lionsgate UK (official TikTok, @lionsgateuk). Vertical 1080x1920 re-frames of film shots.
  "tt-7348821439023156513|https://www.tiktok.com/@lionsgateuk/video/7348821439023156513|Lionsgate UK (TikTok @lionsgateuk)|like c'mon John, we haven't got all day (JW4 Montmartre stairs)|full"
  "tt-7340295395097988384|https://www.tiktok.com/@lionsgateuk/video/7340295395097988384|Lionsgate UK (TikTok @lionsgateuk)|can't fault his determination (JW4)|full"
  "tt-7243793326070058266|https://www.tiktok.com/@lionsgateuk/video/7243793326070058266|Lionsgate UK (TikTok @lionsgateuk)|you'd think John was doing couch to 5k (JW)|full"
  "tt-7463173066575711521|https://www.tiktok.com/@lionsgateuk/video/7463173066575711521|Lionsgate UK (TikTok @lionsgateuk)|this might be the best fall in cinematic history (JW4)|full"
  "tt-7408560151441067297|https://www.tiktok.com/@lionsgateuk/video/7408560151441067297|Lionsgate UK (TikTok @lionsgateuk)|sorry John, but you're a bit of a liability (JW4)|full"
  "tt-7208946590155836677|https://www.tiktok.com/@lionsgateuk/video/7208946590155836677|Lionsgate UK (TikTok @lionsgateuk)|John Wick x the black suit (JW4)|full"
  "tt-7211197898581708038|https://www.tiktok.com/@lionsgateuk/video/7211197898581708038|Lionsgate UK (TikTok @lionsgateuk)|holiday inspo from Mr WorldWick (JW4 'wintry stroll' walk, frames 199-273)|full"
  "tt-7242343029678329115|https://www.tiktok.com/@lionsgateuk/video/7242343029678329115|Lionsgate UK (TikTok @lionsgateuk)|the loop no one asked for (JW4 Sacre-Coeur stairs, wide from below)|full"
  # Lionsgate Movies (official YouTube, UCJ6nMHaJPZvsJ-HmUmj1SeA). Blocked without cookies here.
  "yt-ohieMx5bSM8|https://www.youtube.com/watch?v=ohieMx5bSM8|Lionsgate Movies (YouTube)|JW4 Special Feature 'Osaka Continental'|full"
  "yt-3oIxZLUKYtI|https://www.youtube.com/watch?v=3oIxZLUKYtI|Lionsgate Movies (YouTube)|JW4 Special Feature 'New Challenges'|full"
  "yt-r7a4g-65SzA|https://www.youtube.com/watch?v=r7a4g-65SzA|Lionsgate Movies (YouTube)|John Wick Falling Down the Stairs of Sacre Coeur for 10 Hours|*0-180"
  # Studio-supplied featurettes hosted by press outlets count as official (user ruling 2026-10-12).
  "yt-fdNkGq4kroQ|https://www.youtube.com/watch?v=fdNkGq4kroQ|IGN (YouTube, Lionsgate-supplied exclusive)|JW4 behind the scenes: Sacre-Coeur stairs|full"
)

want=("$@")
fmt='bv*[height<=1080][vcodec^=avc1]/bv*[height<=1080][vcodec^=h264]/bv*[height<=1080]/b'
read -r -a extra <<<"${YTDLP_EXTRA:-}"
ytdlp="${YTDLP:-yt-dlp}"

for entry in "${candidates[@]}"; do
  IFS='|' read -r id url channel title section <<<"$entry"
  if ((${#want[@]})) && [[ ! " ${want[*]} " == *" $id "* ]]; then continue; fi
  out="$footage_dir/$id"
  mkdir -p "$out"
  args=(--no-playlist -f "$fmt" -o "$out/source.%(ext)s" "${extra[@]}")
  if [[ " ${extra[*]} " == *" --cookies "* ]]; then
    args+=(--no-write-info-json --print-to-file \
      '%(id)s|%(channel)s|%(channel_id)s|%(upload_date)s|%(width)sx%(height)s|%(fps)s|%(webpage_url)s|%(title)s' "$out/meta.txt")
  else
    args+=(--write-info-json)
  fi
  [[ "$section" != full ]] && args+=(--download-sections "$section")
  echo "== $id  [$channel]  $title  ($section)"
  printf '%s\n%s\n%s\n' "$url" "$channel" "$title" >"$out/SOURCE.txt"
  "$ytdlp" -q "${args[@]}" "$url" || echo "!! $id failed"
done
