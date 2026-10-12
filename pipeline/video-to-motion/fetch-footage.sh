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
  # Batch 2 (2026-10-12, bench/m1/footage-batch-2.md). Lionsgate Movies uploads no JW4 scene clips; its
  # JW2/JW3/Ballerina clips, trailers and training featurettes are below.
  "yt-qEVUtrk8_B4|https://www.youtube.com/watch?v=qEVUtrk8_B4|Lionsgate Movies (YouTube)|JW4 Official Trailer (Sacre-Coeur climb, Osaka, Arc de Triomphe shots)|full"
  "yt-Mioo2uqCSG0|https://www.youtube.com/watch?v=Mioo2uqCSG0|Lionsgate Movies (YouTube)|JW3 Official Clip 'Taxi' (NYC, injured run)|full"
  "yt-y7pLCd7BgZA|https://www.youtube.com/watch?v=y7pLCd7BgZA|Lionsgate Movies (YouTube)|JW2 Official Clip 'Suited Up' (suit fitting, suit adjust)|full"
  "yt-5O2SZVS26Dg|https://www.youtube.com/watch?v=5O2SZVS26Dg|Lionsgate Movies (YouTube)|Ballerina Official Clip 'Baba Yaga' (Wick clip)|full"
  "yt-4r5_5eOmxzA|https://www.youtube.com/watch?v=4r5_5eOmxzA|Lionsgate Movies (YouTube)|JW2 Official Featurette 'Training' (range, reloads)|full"
  "yt-MW0mu_TPua4|https://www.youtube.com/watch?v=MW0mu_TPua4|Lionsgate Movies (YouTube)|JW3 Official BTS 'Training for John Wick'|full"
  "yt-YO3cBrcDiT0|https://www.youtube.com/watch?v=YO3cBrcDiT0|Lionsgate Movies (YouTube)|JW3 Official BTS 'Art of Action'|full"
  # Movieclips (Fandango): the studio's licensed scene-clip channel, where the official JW4 scene clips
  # live. Treated as studio-supplied scene clips under the 2026-10-12 ruling; drop this block if the user
  # rules otherwise.
  "yt-hrq7sSV3dkA|https://www.youtube.com/watch?v=hrq7sSV3dkA|Movieclips (YouTube, licensed)|JW4 'Stairway Team-Up Fight Scene' (Sacre-Coeur stairs)|full"
  "yt-Xw70HfHVfWQ|https://www.youtube.com/watch?v=Xw70HfHVfWQ|Movieclips (YouTube, licensed)|JW4 'The Duel With Pistols Scene' (Paris duel walk)|full"
  "yt-oa7BjVtvA7w|https://www.youtube.com/watch?v=oa7BjVtvA7w|Movieclips (YouTube, licensed)|JW4 'Paris Street Fight Scene'|full"
  "yt-jUIZdspS32E|https://www.youtube.com/watch?v=jUIZdspS32E|Movieclips (YouTube, licensed)|JW4 'Paint It Black Fight Scene'|full"
  "yt-Lqii8YkcCDI|https://www.youtube.com/watch?v=Lqii8YkcCDI|Movieclips (YouTube, licensed)|JW4 'Paris Car Chase Scene' (Arc de Triomphe)|full"
  "yt-SyEU1pN1Uj0|https://www.youtube.com/watch?v=SyEU1pN1Uj0|Movieclips (YouTube, licensed)|JW4 'John Wick vs. Caine Scene'|full"
  "yt-Sw4pvbkQ-jk|https://www.youtube.com/watch?v=Sw4pvbkQ-jk|Movieclips (YouTube, licensed)|JW3 'Horse Stable Fight Scene' (2/12)|full"
  "yt-v00zKyXbfD4|https://www.youtube.com/watch?v=v00zKyXbfD4|Movieclips (YouTube, licensed)|JW3 'Throwing Knives Scene' (1/12)|full"
  "yt-L-zzxADqlu8|https://www.youtube.com/watch?v=L-zzxADqlu8|Movieclips (YouTube, licensed)|JW3 'Long Live the King Scene' (5/12)|full"
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
