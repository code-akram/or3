#!/usr/bin/env bash
# Self-test of likeness containment (NOTES.md §14 rule 7), no Blender: a fake `blender` that fails
# stands in for the build and the hero stage, so only the routing runs.
#
#   bench/m1/test_containment.sh
#
# Covers pipeline/likeness/containment.py (assert_private accept/refuse, symlink escapes, clean),
# bench/m1/character_provenance.py (refuses fan stats, mesh.jsonl untouched), lookdev.sh --compare
# and run routing (DATA= a temp dir; private runs under the real private/likeness/lookdev/ with a
# selftest-<pid> prefix), hero.sh failing closed on a missing stats file, and tools/hooks/pre-commit
# in a throwaway git repo (including the repo-wide binary policy), plus provenance/audit.py
# --check-files catching a --no-verify commit of binaries. Everything it creates is removed on exit. Exit 0 = all passed.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
MAIN_ROOT="$(dirname "$(git -C "$REPO" rev-parse --path-format=absolute --git-common-dir)")"
PRIVATE="$(realpath -m "$MAIN_ROOT/private")"
TAG="selftest-$$"
C=(python3 -I "$REPO/pipeline/likeness/containment.py")
T="$(mktemp -d)"   # mode 700
PRIV_TMP="$PRIVATE/likeness/$TAG"
cleanup() {
  rm -rf "$T" "$PRIV_TMP"
  find "$PRIVATE/likeness/lookdev" "$PRIVATE/likeness/hero" -mindepth 1 -maxdepth 1 -name "*$TAG*" \
    -exec rm -rf '{}' + 2>/dev/null
}
trap cleanup EXIT
mkdir -p "$PRIV_TMP" "$PRIVATE/likeness/lookdev"
PASS=0; FAIL=0
ok()  { echo "  ok   $1"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $1"; FAIL=$((FAIL + 1)); }
expect() {  # expect 0|nz NAME CMD...: exit status zero / non-zero with a containment message
  local want="$1" name="$2"; shift 2
  "$@" >"$T/last.log" 2>&1; local rc=$?
  if [[ $want == 0 && $rc == 0 ]] || { [[ $want == nz && $rc != 0 ]] && grep -qE 'refusing|containment:' "$T/last.log"; }; then
    ok "$name"; else bad "$name (exit $rc)"; sed 's/^/       /' "$T/last.log" | tail -5; fi
}

echo "== containment.py check (assert_private)"
mkdir -p "$T/closed"; chmod 700 "$T/closed"
mkdir -p "$T/open"; chmod 755 "$T/open"
ln -s "$MAIN_ROOT/data" "$T/closed/to-data"
ln -s "$MAIN_ROOT/data" "$PRIV_TMP/to-data"
ln -s "$PRIV_TMP" "$T/closed/to-private"
mkdir -p "$T/closed/clone" && git -C "$T/closed/clone" init -q
expect 0  "private/likeness/... accepted"              "${C[@]}" check "$PRIV_TMP/out.npz"
expect 0  "private, missing nested dirs accepted"      "${C[@]}" check "$PRIV_TMP/a/b/c/out.npz"
expect 0  "mode-700 temp dir accepted"                 "${C[@]}" check "$T/closed/out.npz"
expect 0  "mode-700 temp dir, missing subdir accepted" "${C[@]}" check "$T/closed/x/y/out.npz"
expect 0  "symlink into private accepted"              "${C[@]}" check "$T/closed/to-private/out.npz"
expect nz "data/ refused"                              "${C[@]}" check "$MAIN_ROOT/data/build/lookdev/out.npz"
expect nz "repo root refused"                          "${C[@]}" check "$MAIN_ROOT/out.npz"
expect nz "tracked dir in this checkout refused"       "${C[@]}" check "$REPO/bench/m1/out.png"
expect nz "relative path climbing out of private"      "${C[@]}" check "$PRIV_TMP/../../../bench/out.npz"
expect nz "bare /tmp refused"                          "${C[@]}" check "/tmp/$TAG.npz"
expect nz "mode-755 dir refused"                       "${C[@]}" check "$T/open/out.npz"
expect nz "symlink escape from a temp dir into data/"  "${C[@]}" check "$T/closed/to-data/build/out.npz"
expect nz "symlink escape from private/ into data/"    "${C[@]}" check "$PRIV_TMP/to-data/build/out.npz"
expect nz "another git work tree refused"              "${C[@]}" check "$T/closed/clone/out.npz"
expect nz "python assert_private raises"               python3 -I -c '
import sys; sys.path.append(sys.argv[1]); import containment
containment.assert_private(sys.argv[2])' "$REPO/pipeline/likeness" "$MAIN_ROOT/data/x.npz"

echo "== containment.py clean"
echo '{"config": {"head": {}, "fan": {"face_delta": "/x/face_delta.npz"}}}' > "$T/fan.json"
echo '{"config": {"head": {"skin": "private/likeness/skin.png"}}}' > "$T/marker.json"
echo '{"config": {"head": {}, "hands": {"fan_deg": 40}}}' > "$T/clean.json"
printf '{"id": 1}\n{"tool": {"config": {"fan": {}}}}\n' > "$T/fan.jsonl"
echo '{"config": ' > "$T/broken.json"
expect nz "fan block (nested) is likeness"        "${C[@]}" clean "$T/fan.json"
expect nz "private/likeness/ string is likeness"  "${C[@]}" clean "$T/marker.json"
expect 0  "fan_deg is not a fan block"            "${C[@]}" clean "$T/clean.json"
expect nz "fan key in JSON lines"                 "${C[@]}" clean "$T/fan.jsonl"
expect nz "missing file fails closed"             "${C[@]}" clean "$T/nope.json"
expect nz "malformed JSON fails closed"           "${C[@]}" clean "$T/broken.json"

echo "== character_provenance.py"
MANIFEST="$REPO/provenance/mesh.jsonl"
cp "$MANIFEST" "$T/mesh.jsonl.bak"
mkdir -p "$T/data/build/character"
printf 'glTF' > "$T/data/build/character/character.glb"
cp "$T/fan.json" "$T/data/build/character/character.stats.json"
expect nz "refuses stats with a fan config" python3 -I "$REPO/bench/m1/character_provenance.py" --data-root "$T/data"
if cmp -s "$MANIFEST" "$T/mesh.jsonl.bak"; then ok "mesh.jsonl untouched"; else bad "mesh.jsonl changed (restored)"; cp "$T/mesh.jsonl.bak" "$MANIFEST"; fi
mkdir -p "$T/data/build/character2"
printf '{"fan": {"dumped_base_verts": 1}, "config": {}}' > "$T/data/build/character2/character.stats.json"
printf 'glTF' > "$T/data/build/character2/character.glb"
expect nz "refuses stats with fan build notes" python3 -I "$REPO/bench/m1/character_provenance.py" --data-root "$T/data" --glb build/character2/character.glb
if cmp -s "$MANIFEST" "$T/mesh.jsonl.bak"; then ok "mesh.jsonl untouched"; else bad "mesh.jsonl changed (restored)"; cp "$T/mesh.jsonl.bak" "$MANIFEST"; fi

echo "== lookdev.sh --compare routing"
export DATA="$T/data"
LD="$DATA/build/lookdev"
run() {  # run DIR LABEL CONFIG-JSON: a finalised-looking run (metrics.json only)
  mkdir -p "$1"; printf '{"run": "%s", "label": "%s", "tris": 1, "config": %s}\n' "$(basename "$1")" "$2" "$3" > "$1/metrics.json"
}
run "$LD/$TAG-pubA" a '{"head": {}}'
run "$LD/$TAG-pubB" b '{"head": {}}'
run "$LD/$TAG-fanA" f '{"head": {}, "fan": {"face_delta": "x.npz"}}'
mkdir -p "$LD/$TAG-nometrics"
run "$PRIVATE/likeness/lookdev/$TAG-privA" p '{"head": {}}'
compare_to() {  # compare_to WANT(data|private) NAME A B
  local want="$1" name="$2" out
  "$REPO/bench/m1/lookdev.sh" --compare "$3" "$4" >"$T/last.log" 2>&1
  out="$(sed -n 's/^== compare -> //p' "$T/last.log")"
  case "$want:$out" in
    data:"$LD"/compare-*|private:"$PRIVATE"/likeness/lookdev/compare-*) ok "$name -> $want" ;;
    *) bad "$name: wanted $want, got '${out:-nothing}'"; tail -5 "$T/last.log" | sed 's/^/       /' ;;
  esac
}
compare_to data    "public vs public"            "$TAG-pubA" "$TAG-pubB"
compare_to private "public vs fan (both in data)" "$TAG-pubA" "$TAG-fanA"
compare_to private "fan vs public, by path"       "$LD/$TAG-fanA" "$LD/$TAG-pubA"
compare_to private "public vs private run (name)" "$TAG-pubA" "$TAG-privA"
compare_to private "missing metrics fails closed" "$TAG-pubA" "$TAG-nometrics"
if compgen -G "$LD/compare-*fanA*" >/dev/null || compgen -G "$LD/compare-*privA*" >/dev/null; then
  bad "a compare with likeness content landed under DATA"; else ok "no likeness compare under DATA"; fi
[[ -f "$PRIVATE/likeness/lookdev/compare-$TAG-pubA--$TAG-fanA/compare.json" ]] \
  && ok "fan compare.json written under private/" || bad "fan compare.json not under private/"

echo "== lookdev.sh run routing (fake blender fails the build)"
mkdir -p "$T/bin"; printf '#!/bin/sh\nexit 1\n' > "$T/bin/blender"; chmod +x "$T/bin/blender"
echo '{"fan": {"face_delta": "d.npz"}, "config": {}}' > "$T/fan-as-config.json"
echo '{"head": {}}' > "$T/public.json"
echo '{"head": {}}' > "$PRIV_TMP/private-clean.json"
run_to() {  # run_to WANT NAME LABEL ARGS...
  local want="$1" name="$2" label="$3"; shift 3
  PATH="$T/bin:$PATH" "$REPO/bench/m1/lookdev.sh" --prev none "$@" "$label" >"$T/last.log" 2>&1
  local dir; dir="$(sed -n 's/^build failed: \(.*\)\/build.log$/\1/p' "$T/last.log")"
  case "$want:$dir" in
    data:"$LD"/*-"$label"|private:"$PRIVATE"/likeness/lookdev/*-"$label") ok "$name -> $want" ;;
    *) bad "$name: wanted $want, got '${dir:-nothing}'"; tail -5 "$T/last.log" | sed 's/^/       /' ;;
  esac
}
run_to data    "public --config"                 "$TAG-pub"   --config "$T/public.json"
run_to private "--config carrying a fan block"   "$TAG-cfg"   --config "$T/fan-as-config.json"
run_to private "clean --config under private/"   "$TAG-pcfg"  --config "$PRIV_TMP/private-clean.json"
run_to private "--prev under private/"           "$TAG-prev"  --prev "$PRIVATE/likeness/lookdev/$TAG-privA"
FAN_CONFIG="$T/fan-as-config.json" run_to private "\$FAN_CONFIG" "$TAG-env"

echo "== hero.sh fan detection fails closed (fake blender fails the stage)"
mkdir -p "$T/build/nostats" "$T/build/clean" "$T/build/broken"
touch "$T/build/nostats/character.blend" "$T/build/clean/character.blend" "$T/build/broken/character.blend"
cp "$T/clean.json" "$T/build/clean/character.stats.json"
cp "$T/broken.json" "$T/build/broken/character.stats.json"
hero_to() {  # hero_to WANT NAME BLEND LABEL
  local want="$1" name="$2"
  PATH="$T/bin:$PATH" "$REPO/bench/m1/hero.sh" --draft --no-turntable "$3" "$4" >"$T/last.log" 2>&1
  local dir; dir="$(sed -n 's/^stage failed: \(.*\)\/stage.log$/\1/p' "$T/last.log")"
  case "$want:$dir" in
    data:"$DATA"/build/hero/*-"$4"|private:"$PRIVATE"/likeness/hero/*-"$4") ok "$name -> $want" ;;
    *) bad "$name: wanted $want, got '${dir:-nothing}'"; tail -5 "$T/last.log" | sed 's/^/       /' ;;
  esac
}
hero_to data    "stats without likeness"  "$T/build/clean/character.blend"   "$TAG-clean"
hero_to private "missing stats"           "$T/build/nostats/character.blend" "$TAG-nostats"
hero_to private "malformed stats"         "$T/build/broken/character.blend"  "$TAG-broken"
unset DATA

echo "== pre-commit hook (throwaway repo)"
G="$T/repo"
mkdir -p "$G/tools/hooks" "$G/pipeline/likeness" "$G/bench/m1/v3" "$G/provenance" "$G/web/public" "$G/docs" "$G/bench/m0/img"
cp "$REPO/tools/hooks/pre-commit" "$REPO/tools/hooks/check_staged.py" "$REPO/tools/hooks/binary_policy.py" "$G/tools/hooks/"
cp "$REPO/pipeline/likeness/containment.py" "$G/pipeline/likeness/"
git -C "$G" init -q
gc() { git -C "$G" -c user.name=selftest -c user.email=selftest@invalid -c commit.gpgsign=false \
         -c core.hooksPath=tools/hooks "$@"; }
gc add -A && gc commit -qm base >/dev/null 2>&1 && ok "base commit (hook + allowlisted likeness code)" || bad "base commit"
try_commit() {  # try_commit WANT(pass|refuse) NAME PATH CONTENT
  printf '%s\n' "$4" > "$G/$3"
  gc add -f "$3"
  if gc commit -qm "$2" >"$T/last.log" 2>&1; then r=pass
  else r=refuse; grep -q "pre-commit: refusing $3:" "$T/last.log" || r=error; gc reset -q; rm -f "$G/$3"; fi
  [[ $r == "$1" ]] && ok "$2: $1" || { bad "$2: wanted $1, got $r"; sed 's/^/       /' "$T/last.log" | tail -3; }
}
try_commit refuse "fan-named config"                    "fan_gate.json"           '{"head": {}}'
try_commit refuse "likeness-named dir outside allowlist" "bench/likeness-notes.txt" 'x'
try_commit refuse "image under bench/"                  "bench/m1/sheet.png"      'PNG'
try_commit refuse "array under bench/"                  "bench/m1/delta.npz"      'PK'
try_commit refuse "fan key in provenance jsonl"         "provenance/mesh.jsonl"   '{"tool": {"config": {"fan": {}}}}'
try_commit refuse "private/likeness path in JSON"       "bench/m1/variants.json"  '{"head": {"delta": "private/likeness/d.npz"}}'
try_commit refuse "fan key in malformed JSON"           "cfg.json"                '{"fan": '
try_commit pass   "clean JSON"                          "cfg.json"                '{"hands": {"fan_deg": 40}}'
try_commit pass   "track doc under bench/m1/v3"         "bench/m1/v3/likeness-review.md" 'notes'
try_commit pass   "likeness code"                       "pipeline/likeness/new_tool.py"  'print()'
# repo-wide binary policy (tools/hooks/binary_policy.py); try_commit stages with `git add -f`
try_commit refuse "image outside bench/ (web/public)"   "web/public/render.png"   'PNG'
try_commit refuse "renamed render, upper-case ext"      "docs/shot.PNG"           'PNG'
try_commit refuse "jpeg in repo root"                   "ref.jpeg"                'JFIF'
try_commit refuse "exr"                                 "docs/a.exr"              'x'
try_commit refuse "glb"                                 "web/public/head.glb"     'glTF'
try_commit refuse "gltf (can embed buffers)"            "web/public/head.gltf"    '{"buffers": []}'
try_commit refuse "npy"                                 "pipeline/codes.npy"      'x'
try_commit refuse "blend"                               "docs/scene.blend"        'BLENDER'
try_commit refuse "wav"                                 "docs/take.wav"           'RIFF'
try_commit refuse "flac"                                "docs/take.flac"          'fLaC'
try_commit refuse "opus"                                "docs/take.opus"          'OggS'
try_commit refuse "mp4"                                 "docs/clip.mp4"           'x'
try_commit pass   "svg is not a raster"                 "web/public/icon.svg"     '<svg/>'
try_commit pass   "allowlisted legacy m0 image"         "bench/m0/img/chunk-kabukicho-alley.png" 'PNG'

echo "== provenance/audit.py --check-files (repo-wide binary policy, catches --no-verify)"
A="$T/auditrepo"
mkdir -p "$A/provenance" "$A/tools/hooks"
cp "$REPO/provenance/audit.py" "$REPO/provenance/record.schema.json" "$REPO/provenance/licences.json" "$A/provenance/"
cp "$REPO/tools/hooks/binary_policy.py" "$A/tools/hooks/"
: > "$A/provenance/mesh.jsonl"
git -C "$A" init -q
ac() { git -C "$A" -c user.name=selftest -c user.email=selftest@invalid -c commit.gpgsign=false "$@"; }
audit() { python3 -I "$A/provenance/audit.py" --data-root "$T/data" "$@" >"$T/last.log" 2>&1; }
ac add -A && ac commit -qm base --no-verify >/dev/null 2>&1
if audit --check-files; then ok "clean checkout passes"; else bad "clean checkout fails"; sed 's/^/       /' "$T/last.log" | tail -3; fi
mkdir -p "$A/web/public"; printf 'PNG\n' > "$A/web/public/render.png"; printf 'RIFF\n' > "$A/web/public/take.wav"
ac add -f web/public/render.png web/public/take.wav && ac commit -qm bypass --no-verify >/dev/null 2>&1
if audit --check-files; then bad "--no-verify binaries not caught"
elif grep -q '^ERROR: git ls-files: web/public/render.png:' "$T/last.log" \
     && grep -q '^ERROR: git ls-files: web/public/take.wav:' "$T/last.log" \
     && grep -q '2 error(s)' "$T/last.log"; then ok "--no-verify binaries caught"
else bad "audit failed without the expected errors"; sed 's/^/       /' "$T/last.log" | tail -3; fi
if audit; then ok "without --check-files the repo scan is off"; else bad "repo scan ran without --check-files"; fi
NG="$T/nogit"; mkdir -p "$NG/provenance" "$NG/tools/hooks"
cp "$A/provenance/audit.py" "$A/provenance/record.schema.json" "$A/provenance/licences.json" "$A/provenance/mesh.jsonl" "$NG/provenance/"
cp "$A/tools/hooks/binary_policy.py" "$NG/tools/hooks/"; printf 'PNG\n' > "$NG/stray.png"
if python3 -I "$NG/provenance/audit.py" --data-root "$T/data" --check-files >"$T/last.log" 2>&1; then ok "outside a git checkout: skipped"
else bad "outside a git checkout: failed"; sed 's/^/       /' "$T/last.log" | tail -3; fi

echo "== $PASS passed, $FAIL failed"
[[ $FAIL == 0 ]]
