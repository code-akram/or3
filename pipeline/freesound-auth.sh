#!/usr/bin/env bash
# One-time Freesound OAuth2 authorisation (needed for original-quality downloads).
# Stores the client credentials and tokens in the repo's gitignored .env (mode 600).
#
#   pipeline/freesound-auth.sh            authorise: prints a URL, you approve in any
#                                         browser and paste back the code it shows
#   pipeline/freesound-auth.sh --refresh  swap the refresh token for a new access token
#
# Access tokens live 24 h; authorisation codes live 10 min and work once.
# Docs: https://freesound.org/docs/api/authentication.html
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="$root/.env"
token_url='https://freesound.org/apiv2/oauth2/access_token/'

env_get() { [[ -f "$env_file" ]] && sed -n "s/^$1=//p" "$env_file" | tail -n1 || true; }

# Rewrite .env keeping every non-Freesound line, then append the Freesound keys.
env_save() {
  local tmp
  tmp="$(mktemp "$root/.env.XXXXXX")"
  chmod 600 "$tmp"
  [[ -f "$env_file" ]] && grep -v '^FREESOUND_' "$env_file" >> "$tmp" || true
  printf '%s\n' "$@" >> "$tmp"
  mv "$tmp" "$env_file"
}

client_id="$(env_get FREESOUND_CLIENT_ID)"
client_secret="$(env_get FREESOUND_CLIENT_SECRET)"
if [[ -z "$client_id" ]]; then read -rp 'Freesound client id: ' client_id; fi
if [[ -z "$client_secret" ]]; then read -rsp 'Freesound client secret / API key: ' client_secret; echo; fi

if [[ "${1:-}" == '--refresh' ]]; then
  refresh_token="$(env_get FREESOUND_REFRESH_TOKEN)"
  [[ -n "$refresh_token" ]] || { echo 'no FREESOUND_REFRESH_TOKEN in .env; authorise first' >&2; exit 1; }
  grant_type=refresh_token grant_key=refresh_token grant_value="$refresh_token"
else
  state="$(od -An -N8 -tx1 /dev/urandom | tr -d ' \n')"
  echo
  echo 'Open this URL in any browser, log in, click Authorize, and copy the code shown:'
  echo "  https://freesound.org/apiv2/oauth2/authorize/?client_id=$client_id&response_type=code&state=$state"
  echo
  read -rp 'Authorisation code: ' code
  grant_type=authorization_code grant_key=code grant_value="$code"
fi

# Secrets reach curl through /dev/fd pipes (printf is a builtin), never as
# arguments, so they never show up in /proc/<pid>/cmdline.
response="$(curl -sS -X POST \
  --data-urlencode "client_id=$client_id" --data-urlencode "client_secret@"<(printf %s "$client_secret") \
  --data-urlencode "grant_type=$grant_type" --data-urlencode "$grant_key@"<(printf %s "$grant_value") \
  "$token_url")"

parsed="$(python3 -I -c '
import json, sys, time
d = json.loads(sys.stdin.read())
if "access_token" not in d:
    sys.exit("token request failed: " + json.dumps(d))
print(d["access_token"], d["refresh_token"], int(time.time()) + int(d["expires_in"]))
' <<< "$response")"
read -r access_token refresh_token expires_at <<< "$parsed"

env_save \
  "FREESOUND_CLIENT_ID=$client_id" \
  "FREESOUND_CLIENT_SECRET=$client_secret" \
  "FREESOUND_ACCESS_TOKEN=$access_token" \
  "FREESOUND_REFRESH_TOKEN=$refresh_token" \
  "FREESOUND_TOKEN_EXPIRES_AT=$expires_at"

echo "ok: tokens saved to .env (access token valid until $(date -d "@$expires_at"))"
