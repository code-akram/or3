#!/usr/bin/env bash
# Fetch the SMPL and SMPL-X body models from the MPI download server and lay
# them out under private/body-models/ with the filenames GVHMR expects:
#   smpl/SMPL_{NEUTRAL,MALE,FEMALE}.pkl
#   smplx/SMPLX_{NEUTRAL,MALE,FEMALE}.npz
#
# Requires accounts on https://smpl.is.tue.mpg.de and https://smpl-x.is.tue.mpg.de
# (licence accepted at registration). Credentials are read from SMPL_USER /
# SMPL_PASS / SMPLX_USER / SMPLX_PASS if set, otherwise prompted for without echo.
# They are never written to disk. These files must never be committed (NOTES.md §14).
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
downloads="$root/private/downloads/body-models"
out="$root/private/body-models"
server='https://download.is.tue.mpg.de/download.php'

prompt_credentials() {
  if [[ -z "${SMPL_USER:-}" ]]; then read -rp 'SMPL email: ' SMPL_USER; fi
  if [[ -z "${SMPL_PASS:-}" ]]; then read -rsp 'SMPL password: ' SMPL_PASS; echo; fi
  if [[ -z "${SMPLX_USER:-}" ]]; then
    read -rp "SMPL-X email [$SMPL_USER]: " SMPLX_USER
    SMPLX_USER="${SMPLX_USER:-$SMPL_USER}"
  fi
  if [[ -z "${SMPLX_PASS:-}" ]]; then
    read -rsp 'SMPL-X password [same as SMPL]: ' SMPLX_PASS; echo
    SMPLX_PASS="${SMPLX_PASS:-$SMPL_PASS}"
  fi
}

# fetch <domain> <file> <user> <pass>
fetch() {
  local dest="$downloads/$2"
  if [[ -f "$dest.done" ]]; then echo "already have $2"; return; fi
  echo "downloading $2 ..."
  # The server logs in, sets a session cookie, then redirects to the file, so the
  # cookie engine must be on or the redirect lands back on the sign-in page.
  # Credentials go in through /dev/fd pipes (printf is a builtin), never as
  # arguments, so they don't show up in /proc/<pid>/cmdline or ps output.
  local cookies status
  cookies="$(mktemp)"
  status="$(curl --fail --location --continue-at - --progress-bar \
    --cookie "$cookies" --cookie-jar "$cookies" \
    --data-urlencode "username@"<(printf %s "$3") --data-urlencode "password@"<(printf %s "$4") \
    --write-out '%{http_code} after %{num_redirects} redirect(s)' \
    --output "$dest" "$server?domain=$1&sfile=$2&resume=1")" \
    || { rm -f "$cookies"; echo "failed: $2 (wrong credentials or account not activated?)" >&2; exit 1; }
  rm -f "$cookies"
  # A wrong session or an unaccepted licence comes back as an HTML page with HTTP 200.
  if [[ "$(head -c 2 "$dest")" != 'PK' ]]; then
    echo "failed: $2 is not a zip (HTTP $status); the server sent a web page instead." >&2
    echo "Log in on the $1 site in a browser, check the licence boxes, then rerun." >&2
    rm -f "$dest"
    exit 1
  fi
  touch "$dest.done"
}

prompt_credentials
mkdir -p "$downloads" "$out/smpl" "$out/smplx"

fetch smpl SMPL_python_v.1.1.0.zip "$SMPL_USER" "$SMPL_PASS"
fetch smplx models_smplx_v1_1.zip "$SMPLX_USER" "$SMPLX_PASS"

# Extract into fresh directories, then copy only the files we need.
stage="$(mktemp -d "$downloads/extract.XXXXXX")"
trap 'rm -rf "$stage"' EXIT
mkdir "$stage/smpl" "$stage/smplx"
bsdtar -xf "$downloads/SMPL_python_v.1.1.0.zip" -C "$stage/smpl"
bsdtar -xf "$downloads/models_smplx_v1_1.zip" -C "$stage/smplx"

for pair in neutral:NEUTRAL m:MALE f:FEMALE; do
  src="$(find "$stage/smpl" -name "basicmodel_${pair%%:*}_lbs_10_207_0_v1.1.0.pkl" | head -n1)"
  [[ -n "$src" ]] || { echo "missing SMPL ${pair#*:} in archive" >&2; exit 1; }
  cp "$src" "$out/smpl/SMPL_${pair#*:}.pkl"
done
for gender in NEUTRAL MALE FEMALE; do
  src="$(find "$stage/smplx" -name "SMPLX_${gender}.npz" | head -n1)"
  [[ -n "$src" ]] || { echo "missing SMPLX_${gender}.npz in archive" >&2; exit 1; }
  cp "$src" "$out/smplx/SMPLX_${gender}.npz"
done

echo "done:"
ls -l "$out/smpl" "$out/smplx"
