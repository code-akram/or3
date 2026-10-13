#!/usr/bin/env bash
# Download FLAME 2020 into private/body-models/flame/ with your flame.is.tue.mpg.de login.
#   fetch_flame.sh --login   (your terminal) saves the login to a 600 file under private/, nothing else
#   fetch_flame.sh           downloads with the saved login, or asks for it; the saved login is removed after success
# Credentials are read silently and sent on stdin, never in argv.
set -euo pipefail
dest="$(cd "$(dirname "$0")/../.." && pwd)/private/body-models/flame"
mkdir -p "$dest"; chmod 700 "$dest"
zip="$dest/FLAME2020.zip"
login="$dest/.login"

if [[ ${1:-} == --login || ! -f $login ]]; then
  read -rp "FLAME username (email): " user
  read -rsp "FLAME password: " pass; echo
  (umask 077; printf '%s\n%s\n' "$user" "$pass" > "$login")
  unset user pass
  if [[ ${1:-} == --login ]]; then echo "Saved. The download can now run without you."; exit 0; fi
fi

# the download host refuses curl's default user agent; url-encode both fields; the login only travels through files and pipes, never argv
cat "$login" \
  | python3 -I -c 'import sys,urllib.parse as u;a=sys.stdin.read().split("\n");print(u.urlencode({"username":a[0],"password":a[1]}),end="")' \
  | curl -fL -A "Mozilla/5.0 (X11; Linux x86_64)" --data-binary @- -o "$zip" \
      'https://download.is.tue.mpg.de/download.php?domain=flame&sfile=FLAME2020.zip&resume=1'

# a wrong login returns an HTML page, not a zip
if ! python3 -I -c 'import sys,zipfile;sys.exit(not zipfile.is_zipfile(sys.argv[1]))' "$zip"; then
  rm -f "$zip"; echo "Download failed: check the login and that the FLAME licence is accepted." >&2; exit 1
fi
python3 -I -c 'import sys,zipfile
z=zipfile.ZipFile(sys.argv[1])
m=[n for n in z.namelist() if n.endswith("generic_model.pkl")][0]
open(sys.argv[2],"wb").write(z.read(m))' "$zip" "$dest/generic_model.pkl"
chmod 600 "$dest"/*
shred -u "$login" 2>/dev/null || rm -f "$login"
echo "OK: $dest/generic_model.pkl"
