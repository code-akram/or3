#!/usr/bin/env bash
# Download FLAME 2020 into private/body-models/flame/ with your flame.is.tue.mpg.de login.
# Run it in your own terminal: credentials are read silently and sent on stdin, never in argv.
set -euo pipefail
dest="$(cd "$(dirname "$0")/../.." && pwd)/private/body-models/flame"
mkdir -p "$dest"; chmod 700 "$dest"
zip="$dest/FLAME2020.zip"

read -rp "FLAME username (email): " user
read -rsp "FLAME password: " pass; echo

# url-encode both fields; printf is a builtin, so nothing shows up in the process list
printf '%s\n%s\n' "$user" "$pass" \
  | python3 -I -c 'import sys,urllib.parse as u;a=sys.stdin.read().split("\n");print(u.urlencode({"username":a[0],"password":a[1]}),end="")' \
  | curl -fL --data-binary @- -o "$zip" \
      'https://download.is.tue.mpg.de/download.php?domain=flame&sfile=FLAME2020.zip&resume=1'
unset user pass

# a wrong login returns an HTML page, not a zip
if ! python3 -I -c 'import sys,zipfile;sys.exit(not zipfile.is_zipfile(sys.argv[1]))' "$zip"; then
  rm -f "$zip"; echo "Download failed: check the login and that the FLAME licence is accepted." >&2; exit 1
fi
python3 -I -c 'import sys,zipfile
z=zipfile.ZipFile(sys.argv[1])
m=[n for n in z.namelist() if n.endswith("generic_model.pkl")][0]
open(sys.argv[2],"wb").write(z.read(m))' "$zip" "$dest/generic_model.pkl"
chmod 600 "$dest"/*
echo "OK: $dest/generic_model.pkl"
