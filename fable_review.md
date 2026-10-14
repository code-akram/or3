# or3 deep codebase review (Fable 5.1)

_Started 2026-10-14. Written incrementally as the review proceeds; sections are appended as areas are finished. Severity: **S1** blocks shipping or corrupts data / leaks; **S2** real bug or risk the next milestone will hit; **S3** quality, drift, maintainability; **S4** nit._

## 0. Scope and method

- Tracked tree: 256 files, ~64k lines. Areas: `core/` (Rust → WASM sim), `web/` (Vite + TS client), `tools/` (Rust CLIs: plateau-chunk, acoustic-bake), `blender/` (character, hero stage, props), `pipeline/` (audio, video-to-motion, likeness), `provenance/`, `bench/` (harness scripts, reports).
- Method: the runtime core, web client, build scripts, provenance and every script that touches credentials or `private/` are read line by line here. The large Blender and Python pipeline trees are reviewed in parallel by delegated reviewers; their findings are verified against the source before they land in this file.
- Out of scope: `data/`, `private/`, `target/`, generated lockfiles (except for dependency pinning notes).

## 1. Findings log (chronological, raw)

### 1.1 `core/` (Rust → WASM sim) — read line by line

Verdict: small, careful, correct. The triple-buffer protocol is sound; the maths in `pose.rs` checks out term by term (Rz·Rx column expansion, Ry yaw matrix, scalar `mul` fallback = A·col_j(B) in column-major). No S1/S2.

- **[S3] Worker death is silent after start.** `web/src/sim.ts:70-78` listens for `started`/`error` only inside the start-up promise; once resolved, `worker.onmessage` is never consulted again. `sim.worker.ts:110-115` does post `error` (panic=abort → wasm trap → JS RuntimeError caught) and `stopped`, but nobody receives them. Scenario: Rapier panics on tick 40 000 → worker exits, main thread keeps drawing the last published slot forever, HUD shows a frozen `sim ticks`. Fix: keep an `onmessage` handler that flips a `simDead` flag into `boot`/telemetry, and have `summarize.mjs` flag windows with `ticks == 0`.
- **[S3] `std::thread::sleep` sub-microsecond busy loop.** `core/src/lib.rs:247-252`: `Duration::from_micros((wait*1000.0) as u64)` truncates any wait under 1 µs to 0 and loops. Harmless in practice (next iteration `now >= next`), but the "never spin" comment is slightly overstated. Nit.
- **[S3] Unbounded catch-up window.** `lib.rs:253-259`: between 16.7 ms and 250 ms behind, the loop runs back-to-back ticks with no sleep. On a throttled Air that is up to 15 consecutive Rapier steps (~15 ms at the measured 0.9 ms p50) in one burst, which is exactly the thermal behaviour the fanless target punishes. Consider capping catch-up to 2–3 ticks and counting the rest as a resync.
- **[S4] `Rig::new` offset rule is hard to read.** `pose.rs:201`: `if from == 0 && a != 0 { 0.0 } else { r.len[from] }` relies on `r.len[0]` still being 0.0 when the spine chain runs (it is). Comment it or split into `attach_at_parent_tip: bool`.
- **[S4] Stale comment.** `Cargo.toml:17` says the wasm profile is "Built by `scripts/build-core.sh`"; the script is `core/build-web.sh` (which does pass `--profile wasm`, so the profile is live).
- **[S4] `[profile.release] debug = 1`** applies to every native tool build; fine for now, but it is why `target/` is large.
- **Good:** `acquire_pose` never blocks and never hands the reader a slot the writer owns; ordering (`AcqRel` swap, `Acquire` load) is right; `arena_layout()` consumes the RNG exactly as `Arena::new`, so pillars match; exact version pins on `wasm-bindgen` and `rapier3d`; `build_features()` exposes whether the build is really threaded, closing the "stable Rust silently single-threads" trap noted in NOTES.

### 1.2 `web/` (Vite + TS client) — read line by line

- **[S2] Pose view can alias a buffer the browser is no longer backing.** `main.ts:374`: `poseBuffer.array = new Float32Array(sim.memory.buffer, ptr, …)` is rebuilt only when the slot pointer changes. Shared `WebAssembly.Memory` growth returns a *new* `SharedArrayBuffer` object (the old one stays valid but stops at the old length). Today the sim never grows memory after start, so this is latent; the moment Rapier allocates past the initial pages mid-run, any view taken earlier reads the old, shorter buffer and the `stats()` view does too (`sim.ts:91` rebuilds each call, fine; `main.ts:154` does not). Fix: compare `sim.memory.buffer !== lastBuffer` as well as `ptr !== lastPtr`.
- **[S3] Telemetry POST path is unauthenticated and appends to disk by client-chosen filename.** `bench/server.mjs:301-305`: `SESSION_RE` constrains the name, so no traversal, and it binds to loopback only; fine for a bench tool, but `MAX_BODY` of 2 MiB × unlimited sessions is an unbounded disk write if the tunnel is ever shared. Add a per-session byte cap. Low priority given the loopback bind.
- **[S3] Duplicated `Stat` table.** `sim.ts:18-35` mirrors `lib.rs::stat` by hand (and `summarize.mjs:34` repeats `SIM_BINS`). A drift here mislabels every histogram silently. Export the offsets from Rust (`#[wasm_bindgen] pub fn stat_layout() -> Vec<u32>`) or generate the TS from the Rust constants in `build-web.sh`.
- **[S3] One tsconfig for window and worker code.** `tsconfig.json:144` pulls in `DOM` and `WebWorker.ImportScripts`, so `self.postMessage` in the worker typechecks as `Window.postMessage` (which accepts the same shape). Works, but the worker loses type safety for `self`. Split with a `tsconfig.worker.json` or `/// <reference lib="webworker" />` when the worker grows.
- **[S4] `headless-check.mjs:65`** waits for `phase ∈ {running, error}` but then treats `error` as a normal result; `result.ok` still ends false via `checks.running`, so the exit code is right. Fine.
- **[S4] `Poster.send` with `beacon=true`** counts `ok++` even though `sendBeacon` only queues. Reasonable, but the HUD `telemetry ok=` number is then optimistic on `pagehide`.
- **Good:** strict TS flags (`noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`), isolation headers kept in sync in three places with a cross-reference comment in each, no `any`, `assetsInlineLimit: 0` so the wasm is never base64'd, loopback-only dev server.

### 1.3 `provenance/` — read line by line

- **[S2] `audit.py` skips licence checks after an unknown licence `continue`.** `audit.py:127-129`: when `lic not in known` it appends an error and `continue`s, so the record's `synthetic_placeholder` and attribution checks are skipped. Harmless because the run already fails, but a `--release` run that only fixes the licence string could then fail a second time on a check it never saw. Minor; drop the `continue`.
- **[S2] Schema check accepts `null` in `"type": ["integer","string"]` for `bit_depth`?** No: `type_ok` maps names to Python types and `None` matches none, so nulls are rejected. But `check_schema` never recurses for `original_format` beyond one level and ignores `additionalProperties` on nested objects that have no `properties` key (`tool`). Consistent with the docstring ("the subset it uses"). OK.
- **[S3] Pattern anchored with `re.search`.** `audit.py:69` uses `re.search` with patterns that start with `^`, fine, but `sha256` pattern `^[0-9a-f]{64}$` would also accept a trailing newline before `$`; `json.loads` cannot produce one. OK.
- **[S3] `deny_patterns` is substring matching on `licence + licence_url`.** `licences.json:259` includes `"-nc"`: a licence URL containing e.g. `…/by/4.0/#section-nc…` or a `LicenseRef-Encode-NC-free` would false-positive, and `"pixabay"` as a deny pattern is policy embedded as a string match. Acceptable for now; note it in the `$comment`.
- **[S3] Derived records require `path`+`sha256`, source records do not.** `record.schema.json:235-236`. A `source` with `path` but no `sha256` is caught by `audit.py:115`, good, but a `source` with neither is allowed, so "re-fetchable from `download_url`" is the only link to the bytes. Intentional for rejected items; fine.
- **Good:** stdlib only, `-I` documented, share-alike propagation and rejected-input checks are the right invariants, and the 2 MiB `MAX_BODY` style of defensive limits appears across the bench tooling too.

### 1.4 Credential handling (all fetch/auth scripts, cross-checked by hand)

Verdict: the 2026-10-12 lesson stuck. No script passes a secret in argv.

- `pipeline/freesound-auth.sh:50-53` uses `--data-urlencode name@<(printf …)` for the secret and the grant value; `.env` is written via a 600 temp file and `mv`. `client_id` is on argv, which is public by design (it appears in the authorise URL).
- **[S3] `freesound-auth.sh:17` `env_get`** uses `sed -n "s/^$1=//p"` with the key interpolated into the pattern unquoted for regex; keys are literal constants, so fine, but values containing `/` are not an issue since `s/…/` only delimits the pattern side. OK. `env_save` drops *every* `FREESOUND_*` line including any the user added by hand (e.g. a comment), fine.
- **[S3] `freesound-auth.sh:60-62`** prints the tokens through `python3 … print(...)` → `$parsed` → `read`. They stay in shell variables, never argv, good. But `set -x` anywhere in the caller's environment (`BASH_XTRACEFD`, `SHELLOPTS`) would echo them; add `set +x` at the top as belt-and-braces.
- `pipeline/fetch-body-models.sh:42-46`: `--data-urlencode "username@"<(printf …)` form, cookies in `mktemp`, removed on both paths. **[S3]** `mktemp` cookie jar is created with default mode (600 under `mktemp`, good) but lives in `/tmp` on a host with a second local user; `TMPDIR` under `private/` would be stricter.
- `pipeline/likeness/fetch_flame.sh:92-95`: login goes `cat → python3 -I (urlencode) → curl --data-binary @-`; the `.login` file is 600 under a 700 dir and shredded after success. **[S3]** On a *failed* download (`:98-100`) the `.login` file is kept so the user can retry; intentional, but say so in the usage header, since the header claims "removed after success" only.
- `pipeline/video-to-motion/fetch-youtube.sh:20-62`: refuses cookie files with mode ≠ 600, validates the Netscape format with `python3 -I`, passes only the path, re-chmods after yt-dlp rewrites the jar, and documents why `--cookies` disables the `info.json` write (yt-dlp copies cookie values into it). Exemplary.
- `pipeline/audio/src/audiopipe/common.py:64-75`: token refresh suppresses the child's output on failure ("may contain secrets"). Good.

### 1.5 `tools/` (Rust CLIs: plateau-chunk, acoustic-bake) — delegated review, key claims re-checked here

`cargo check` clean on both crates; clippy 15 style warnings. The committed `phonon_sys.rs` was regenerated with the flags in `bench/m0/spike6/bindgen.sh` and is byte-identical, so there are no hand edits in the FFI layer. `tm.rs` was checked term by term against the GSI (Kawase 2011) formulation, including the zone IX origin: correct. GLB writer pads to 4, uses u32 indices, deterministic output. No S1.

- **[S2] Empty chunk writes an invalid glTF.** `tools/plateau-chunk/src/glb.rs:313-324` emits `scene.nodes: []`, empty `meshes`/`accessors`/`bufferViews` and `buffers[0].byteLength: 0` for a chunk with no geometry (water, park, data edge). The schema forbids all four; gltf-transform/meshopt and the validator reject it. City streaming will hit this on the first empty tile. Fix: skip the file (and record "empty" in the sidecar) or emit a single empty node.
- **[S2] Chunks spanning two 1 km source cells lose data silently.** Two `--layer whole:bldg:…` args produce two meshes both named `bldg` with feature ids restarting at 0. The meta sidecar is keyed by layer name (`main.rs:524`, second overwrites first), `--gml` takes one file (`main.rs:373`, last wins) so the second cell gets no attributes, and `acoustic-bake` (`geom.rs:62-67`) keeps the last building table but resolves features from both meshes against it, so ground heights and glass materials come from the wrong buildings. Fix: key tables by (layer, source) or offset feature ids per source.
- **[S3] Metadata decoder hardcodes nusamai's current types.** `glb.rs:182-193` reads enums as 4 bytes and scalars as 8 bytes. True of today's files; a nusamai upgrade changing to 32-bit scalars yields garbage then a panic.
- **[S3] GLB reader panics on malformed input.** `glb.rs:36,64,92,106-110`: unchecked slices. Acceptable for our own files, but `load_source` is also fed nusamai output.
- **[S3] `load_source` reads only `meshes[0]` and ignores node transforms.** `main.rs:106`, `geom.rs:54`.
- **[S3] Audio buffer aliasing.** `acoustic-bake/src/main.rs:89-105` caches raw channel pointers then writes the same memory through `&mut`. Formally UB under the aliasing rules, not exploitable today since the pointers go straight to C. Rebuild pointers inside `ipl()`.
- **[S3] Rust enums on FFI return values.** `bindgen.sh:13` `--default-enum-style rust` makes `IPLerror`, `IPLAudioEffectState`, `IPLLogLevel` Rust enums; an out-of-range value from another SDK build is UB. Also the SDK version is a literal `(4<<16)|(8<<8)|1` at `main.rs:472`.
- **[S3] Calibration can divide by zero.** `main.rs:501-506`: `cal_gain = sqrt(e_th / e_meas)`; a ground-only run with zero energy gives `inf`, and the WAVs are written as garbage with exit 0.
- **[S3] WAV writer.** `analysis.rs:120,139`: no explicit flush (a full disk truncates silently); mono files with odd sample counts lack the RIFF pad byte.
- **[S3] Hardcoded chunk geometry.** `main.rs:354` half-size 100 m assumes a 200 m chunk; `geom.rs:258` ground probe starts at 400 m absolute.
- **[S3] `build.rs` defaults to `/home/akram/...` and never checks the SDK exists.** `build.rs:2-3`. Any workspace `cargo build`/`cargo test` on another machine fails with a bare `-lphonon` link error; `cargo check` hides it. Fail with a clear message if the dir is missing, or make the crate `required-features`/optional in the workspace.
- **[S3] Spike scripts hide compiler errors.** `bench/m0/spike5/chunk.sh:19`, `verify-crs.sh:12`, `bench/m0/spike6/bake.sh:17` send `cargo build` stderr to `/dev/null`.
- **[S3] "clip" mode assigns triangles by centroid, it does not clip.** `main.rs:440-444`. In the spike chunk 69 of 2095 road triangles extend past the 200 m square, up to 55 m. Streaming shows overhangs and holes where the owner chunk isn't loaded. The spike-5 report says "clipped per triangle"; one of them is wrong.
- **[S3] 436-line `main` with a 264-line `unsafe` block** (`main.rs:307-743`); early `?` returns inside it leak IPL objects. Wrap handles in RAII guards.
- **[S4]** `glb.rs:311 let _ = mi;`, `main.rs:564 let _ = k;` refactor leftovers; `vec![Vec::with_capacity(n); k]` loses capacity on the clones (`main.rs:270,606`).

### 1.6 `pipeline/audio/` + `freesound-auth.sh` — delegated review, key claims re-checked here

Credentials clean (see 1.4). DSP core (BS.1770 loudness, loop construction, Opus loop-wrap fix, seeding) correct. `audit.py` passes with 0 errors. One S2.

- **[S2] The 18 kHz bandwidth floor never fires.** `analyse.py:143` smooths the dB spectrum with `np.convolve(..., mode="same")`, which zero-pads *in dB* (0 dB ≫ the −100 dB floor) and lifts the bins at Nyquist, so the "content edge" (`:147`) is always Nyquist. All 26 sources in `summary.json` show it; this is the root cause of the "useless spectral metric" note in spike-7. Recomputed with edge-safe smoothing (`mode="valid"` or reflect padding), three *accepted* sources fall below 18 kHz: rain-light 612817 at 17.5 kHz, vending 730438 at 16.4 kHz, footsteps 205748 at 13.2 kHz. The last one is the main footstep pool candidate the listening gate asks the user to pick. Flag before the listening session.
- **[S3] Wet footsteps are 10 ms late.** `footsteps.py:219` trims `z[:len(y)]` but the ffmpeg EQ adds ~480 samples of group delay that is never removed; the shipped wet/dry pairs show a 481-sample onset offset and the wet-vs-dry speaker metrics inherit the skew. Compensate with an impulse measurement of the filter once, or use a zero-phase scipy filter.
- **[S3] Bearer token forwarded on redirects.** `common.py:101` passes the token as a plain request header; `urllib` re-sends headers to redirect targets, cross-host included. `download()` already handles this correctly; `http_get` should too. Medium confidence on 3.14 behaviour.
- **[S3] Stale files survive reruns.** `master.py:160,238,272`: `premaster/events` is never cleared, so a rerun with fewer takes crashes with `IndexError`, and records for files no longer built stay in `audio.jsonl`.
- **[S3] Human-presence checks don't gate.** `run.sh:25` and `vad.py:154-179`, `tagger.py:358-388`, `bed.py:424` always exit 0; NOTES §12's human-free rule is a report, not a check.
- **[S3] Seam metric mislabels tonal layers.** `loop.py:258-269`: the loop point is snapped to a zero crossing, which the percentile metric then ranks as unusual; the page (`page.py:111`) shows a 99.6th-percentile "seam" on neon although the wrap is sample-exact.
- **[S3] Model integrity.** `vad.py:42` declares `MODEL_SHA256` and never checks it; `tools/export_panns_onnx.py` unpickles downloaded weights unverified and its "parity check" saves references without comparing.
- **[S3] Event takes end at their peak.** `bed.py:229-232` grows `lo` first and `hi` second under one shared length cap, so long events (all 4 insect takes, 4 of 6 crow takes hit `max_s`) are cut at their loudest point.
- **[S4]** empty event pools crash (`bed.py:361`); token refresh inherits stdin and can hang on a hidden prompt, and ignores `AUDIO_ENV_FILE` (`common.py:69`); `freesound-auth.sh:50` curl has no `--max-time`/`--fail`, and the OAuth `state` is generated and never checked; `run.sh:15` `uv run` without `--locked`; `loudness.py:11-14` K-weighting is 48 kHz-only but the API takes `sr`; lossy-codec list misses mp2/wma/ac3/eac3/amr/gsm (`analyse.py:45`); IA `licenseurl` can be a list (`fetch.py:131`); wet-08 decodes at −1.39 dBTP vs the −1.5 ceiling and spike-7 says −1.57; `provenance.py:307` manifest write is not atomic.
- **Gate note:** the HANDOFF "8.6 dB calibration" question applies only to the alley footstep takes; the ambience bed renormalises the IR itself, so the calibration has no effect there. Reword the listening gate.

### 1.7 `blender/` build driver, head, hands, deform, rig, export — delegated review, key claims re-checked here

Config deep-merge is correct; likeness is off by default (`head_fan` is inert without a `fan` block); MPFB macro bake and GAMEENGINE alpha fix are in place; all RNGs seeded; no bare `except:`; no `or3` identifiers.

- **[S1 (latent)] Likeness isolation rests on two shell wrappers.** `blender/build_character.py:46` reads `FAN_CONFIG` from the environment as the default for `--fan`, and `--out` is unrestricted. Only `bench/m1/lookdev.sh:51-53` and `hero.sh` route fan output to `private/`. With `FAN_CONFIG` exported in a shell (which `lookdev.sh:11-12` documents as supported), `bench/m0/bench_spike1_build.sh:22` or the docstring command writes a likeness GLB, `.blend` and stats to `data/build/character/`. Then `bench/m1/character_provenance.py:67` copies `stats["config"]` (which contains the fan file's merged `config` block: skin, lip colours, likeness parameters) into the **tracked** `provenance/mesh.jsonl` and marks it "All inputs CC0 … accepted". Verified: `mesh.jsonl` has no `fan` key today, so nothing has leaked yet. Fix (all three): refuse a fan build whose `--out` is not under `<repo>/private/`; drop the env-var default; make `character_provenance.py` reject any stats containing `fan`.
- **[S2] Documented build command exits 0 on failure.** `build_character.py:7` docstring and `bench_spike1_build.sh:22` omit `--python-exit-code 1` (the m1 harness has it). A failing stage leaves the previous GLB in place and the bench records a success.
- **[S2] UV repack splits islands by first face, material per face.** `head_refine.py:371,404-413`. An island crossing the wrist boundary samples the wrong atlas in a band. Medium-low confidence (depends on MPFB's wrist seams); worth a one-off check with a UV-island/material mismatch assert.
- **[S3] `null` disables a default** (NOTES §5) only sometimes: `hands.forms`, `hands.detail`, `head.forms.tissue` null → defaults silently applied (`hand_forms.py:136`, `hand_detail.py:282`, `head_forms.py:65`); `budgets.decimate`, `head.parts`, `rig.deform.weights.skirt`, `export.max_influences` null → crash. Normalise in `config.load`.
- **[S3] Dead config key `rig.helpers`** (`config.py:411`), comment contradicts the default build.
- **[S3] `lookdev_render --facet` leaves the body flat-shaded** for the detail close-ups rendered afterwards (`lookdev_render.py:688-694,850-854`).
- **[S3] `character.rig.json` written before the GLB, fixed name** (`deform_rig.py:660`, `lookdev_render.py:844`): a failed export leaves new rules next to an old GLB.
- **[S3] Identity-transform assumption unchecked.** `deform_rig.py:277-286,101-130`, `deform_correctives.py:434-439,98-104` mix armature-space and mesh-local coordinates; correct only while every staged object sits at the origin.
- **[S3] Body located by exact name `Human_export`** in deform code (`deform_rig.py:549,646`, `deform_correctives.py:90`) but by vertex group elsewhere; a rename silently skips correctives.
- **[S3] Budgets measured, never enforced** (`budgets.py:273-298`), and the stage runs after corrective morphs exist (`build_character.py:113-115`), so a decimate entry for a morph-carrying mesh fails.
- **[S3] Comments contradicting code** (`head_shape.py:41-43` "fit left, mirror" vs independent per-side fit at `:208-213`; others listed in the delegated report). **Palm frame computed in five places with three sign conventions.**
- **[S4]** dead locals in `deform_rig.py:469-502,669`; fan weight clamp without warning (`head_fan.py:184`); asymmetry jitter re-rolls all amplitudes when one changes (`head_forms.py:202-204`); `--suit/--shoes` discard the `--config` clothes list (`build_character.py:60-64`); `export.py:39` `next()` without default; hard-coded `/home/akram/code/or3/data/vendor` in `blender/hero/sets.py:27` and `fetch_textures.py:5`.

### 1.8 `blender/character/suit_*` — delegated review, key claims re-checked here

Narrow `ValueError` catches only, no codename hits. Two claims were checked against the latest build's GLB and stats by the reviewer.

- **[S2] Root cause of the HANDOFF "shoes vertex order not build-stable".** `suit_shoes.py:383`: `for v in set(tip): G.bm.verts.remove(v)` deletes toe-tip vertices in address order, which differs per run; every vertex created after it (sole, laces, second shoe) can shift slot. It is the only hash-ordered delete in the suit code, which matches only the shoes being affected. Fix: `for v in dict.fromkeys(tip)`.
- **[S2] Trousers ship the jacket's ambient occlusion (confirmed in the GLB).** `suit_textures.py:570-573` copies the finished jacket material (with its AO already wired at `:114-116`) to make the trousers material; the exporter packs the stale link, so the trousers ORM texture in the GLB is `suit_wool_a_orm-suit_wool_b_orm`. Invisible in Cycles, visible in the game.
- **[S2] Lapel collapsed row wipes a jacket vertex's weights.** `suit_jacket.py:754-756,772-776` + `suit_build.py:419-422`: a repeated vertex makes `copy_weights(root, root)` clear and copy nothing. Hidden today by Track F's weight smoothing; a build with `rig.deform: null` ships it.
- **[S2] Drape fold masks measured in the arms-up P0 pose, not rest** (`suit_drape.py:477-478,527-530`): the elbow mask sits ~6 cm from the crook, gain ~0.54 instead of 1.0.
- **[S3] Drape cache key omits landmark positions, body geometry and code version** and tolerates garments moved up to 15 mm (`suit_drape.py:356-372`). The GLB depends on the on-disk cache; drape fixes are ignored until it is cleared.
- **[S3] Vent lift applied once per incident split edge** (`suit_jacket.py:849-857`), kink at the vent corner (75 % confidence).
- **[S3] `Jacket.end_x` unreachable branch** (`suit_jacket.py:88-91` vs `:97`): the right front jumps ~2.5 cm across centre above the button.
- **[S3] `suit.post` `for … else` misbinding** (`suit.py:451-466`): crashes when shoes are not built and the clothes list has no stock shoes.
- **[S3] Buttons never decimated**: 2,130 tris vs the look-spec ≤ 200 (`suit.py:282-283,480-481`).
- **[S3] Config drift**: ~22 code fallbacks contradict `DEFAULTS`, ~20 knobs exist only in code, and `material(**_)` swallows misspelled keys.
- **[S3] Drifted duplicates**: two `kuwahara` (`suit_textures.py:453` vs `suit_leather.py:46`), two `_value_noise`.

### 1.9 `blender/character/` hair, beard, brows, lashes, skin, eyes — delegated review, key claims re-checked here

Determinism solid (all RNGs seeded); float32 lip-distance fix correct and no similar precision trap found; tri counts inside the 35k hair+beard budget (hair 21.5k, beard 6.9k).

- **[S2] Facial-hair atlases store linear RGB in sRGB byte images.** `beard_bake.py:91-100` `make_image` writes `rgba` straight into `bpy.data.images.new(...)` (default colourspace sRGB) with no `linear_to_srgb`, unlike `skin_tex.make_image` (`skin_tex.py:318-323`) and `hair_groom_cards.bake_atlas`. Consumers: `hair_beard.py:439-445`, `brows.py:212`, `lashes.py:313,329`. Result: game beard shells/cards, brow shells/cards and the lash strip are ~10× too dark (swatch `#3e2e23` × 1.6 gain should be 0.077 linear, reads back 0.0068) and dark tones band into 5–20 byte levels. This is the probable cause of the "game beard renders near-black" open item in `bench/m1/v2/facial-hair.md`, currently attributed to Cycles self-shadowing. `albedo_gain` 1.6/1.8 and `grey_gain` were tuned against the bug and need retuning after the fix.
- **[S3] Cap UV wraps at the back midline** (`hair_clumps.py:236`, duplicated at `hair_groom_cards.py:847`): one face column squeezes ~9.4 texture periods, and the period does not close around the head.
- **[S3] Skin beard shadow does not follow the beard edge "exactly"** (`skin_tex.py:226-236` vs `hair_beard.py:124-141,145-162`): skips the ±8 mm wobble, philtrum rule, and lip/mouth exclusions.
- **[S3] Beard-shadow fallback can never run** (`skin_synth.py:159`, `skin_tex.py:241,458`): the check passes on unbaked zero texels, and a broad `except` in `beard_depth` hides config bugs (already happened once: `KeyError('fade_m')`).
- **[S3] `hair.post` drops brows and lashes** when `clumps` and `beard` are both null (`hair.py:29-30`), although both are on by default.
- **[S3] Front-fall guide picks lowest-index strand**, not the nearest to the guide root (`hair_groom.py:759-764`).
- **[S3] Groom RNG coupling**: enabling `ends` consumes from the shared stream and reshuffles every later wave/flyaway/melanin draw (`hair_groom.py:774-819`). Use per-feature sub-RNGs.
- **[S3] Card cell assignment uses an unstable `argsort` with many ties** (`hair_groom_cards.py:622`); can differ by CPU. Medium confidence.
- **[S3] Textures exceed the NOTES §7 hair budget (1024)**: hair 2048² (`hair_groom_cards.py:47`), beard shells 2048×3584, beard cards 2016×640, brows 1024×1152 (`config.py:297-319`). ~100 MB uncompressed, still within the tab budget, but the spec and the code disagree.
- **[S3] Dead atlas cell**: hairline wisp (cell 11) baked, never referenced (`hair_groom_cards.py:493-499`).
- **[S4]** `beard.edge: null` crashes; springs comment says 12 bones, code builds 14; hero hand pores ignore the config override; eye tri count overstated (6912 vs 6720) and the eye occlusion channel never reaches the GLB; nine functions over 150 lines (`hair_clumps.build` ≈ 375).

### 1.10 `blender/hero/`, `blender/props/pistol.py`, `bench/m1/` harness — delegated review, key claims re-checked here

No stage-only geometry (light twins, hero meshes, hero pistol) reaches any GLB; preview and final differ only in samples, adaptive threshold and resolution; light-linking API use is correct for 5.x.

- **[S1] `lookdev.sh --compare` writes fan output under `data/`.** `bench/m1/lookdev.sh:28-33` handles `--compare` and exits *before* `--fan`/`FAN_CONFIG` are parsed (`:36-53`), so `ROOT` is still `data/build/lookdev` and `OUT="$ROOT/compare-…"`. Comparing two fan runs writes a `sheet.png` with both fan faces and a `compare.json` containing the full fan config (private `face_delta` path, likeness skin and lip colours) into `data/`. Verified by reading the script. `data/build/` is gitignored, so this is a policy breach (NOTES §14 rule 7: likeness output never under `data/`), not a git leak, but the review server directories and the `worktree-attic` archive are built from `data/build/`.
- **[S1 (latent), duplicate of 1.7]** `character_provenance.py:55-75` has no fan guard.
- **[S2] A fan file passed as `--config` builds into `data/`.** `lookdev.sh:40,50-55` routes on `--fan`/`FAN_CONFIG` only; `config.py:435-440` still applies a `fan` block found in `--config`. `hero.sh` refuses inputs under `private/`; `lookdev.sh` has no equivalent check.
- **[S2] The HANDOFF fix for the purple suit in the sign shot cannot work.** `blender/hero/rig.py:470-478`: per-shot `twin` is only consulted for lights named `rim` and `kicker`; a cloth twin on the magenta `key` is silently ignored, and that key also reaches the hair at full saturation. The docstring (`:439-441`) and `hero-stage.md` "Twins generalised" claim otherwise.
- **[S3] `hero.sh` fan detection fails open** (`hero.sh:190-193`): a missing or unreadable stats file routes output to `data/`.
- **[S3] Rain streaks ignore the camera shift** (`stage.py:115-116,131`, `sets.py:475-490`): ~11 % rain-free band on shifted shots.
- **[S3] `Poser.look()` pitch sign inverted** (`poses.py:296`): "+ = nod down" lifts the chin; affects `walk`.
- **[S3] White balance differs between evidence scripts** sharing the hero rig: `hair_inspect.py:233`, `facial_hair_render.py:187,201-202`, `head_closeups.py:168-189` skip the 3,900 K balance that `rig.py:946-950`, `hands_render.py:164-168`, `pistol_render.py:349-353` apply.
- **[S3] `deform_hero.py` runs the deform runtime twice** (`:173-189`), zeroing non-corrective shape keys such as `fan_face`: renders the stock face.
- **[S3] `suit_views.py --lum` writes EXR bytes under a `.png` name** (`:435-439`); **`head_closeups.py` un-hides game hair cards** over the groom (`:265-266,288-289`); **`suit_dev.py` imports from `/tmp` and swallows child exit codes** (`:107-131`); **`lookdev.sh` passes when the glTF validator crashes**.
- **[S3] Run dirs collide between agents and `--prev auto` crosses tracks** (`lookdev.sh:58,66-67`, `hero.sh:195,198`). **Thread defaults exceed the machine rules** (`hero.sh:185`, `lookdev.sh:49`, `suit_dev.py:100,113,121`) and nothing enforces "finals alone".
- **[S4]** `PROP_SAT` unreachable for magenta; `sets.py:27` hard-coded path; grade docstring names the wrong look; `sheet.py` misparses pose names containing `_`; hand-frame maths in four copies; `pistol.py` depends on `hand_pose`'s private API. Pistol tri count (10,266) not re-verified without Blender; code, docstring and `pistol.md` agree.

### 1.11 `pipeline/video-to-motion/`, `pipeline/likeness/`, `fetch-body-models.sh` — delegated review, key claims re-checked here

No credential on argv or in logs; every *default* output path is under `private/`; nothing likeness- or footage-derived is tracked. GVHMR env is pinned (3.11 fork, fixed commit, `uv sync --frozen`). Likeness model loads are hardened; fit and wrap ship self-tests.

- **[S2] `identity_codes.py:239` stores a face-recognition template of a real person, and no CLI checks where it writes.** The `.npz` holds per-frame 512-d ArcFace embeddings (identifying on their own) plus 300-d FLAME shape codes (rebuild the head). NOTES §14 rule 7 forbids committing fitted shapes. `--out`/`--save-aligned` here, and the output flags of `fit`, `wrap`, `tune`, `refboard`, `review_board`, `clay_views`, `protagonist_id` and `motion_qc`, accept any path; `.gitignore` does not cover `*.npz`, `*.npy`, `*.jpg`, `*.obj`. A mistyped `--out` plus `git add -A` publishes it. Fix: a shared `assert_private(path)` helper refusing repo paths outside `private/`; add the gitignore patterns; stop persisting the per-frame embeddings (only the median is read).
- **[S2] Foot contacts fail on stairs.** `foot_lock.py:79-85` (and `motion_qc.py:79-85`): `h = low[k] - lowest` measures each foot against the *other* foot, so a foot one step up (15–17 cm) exceeds the 5/8 cm thresholds and never plants; descending, the planted foot is unpinned at the end of each step. Docstring and spike-3 claim stairs need no floor; the code does not support it. The Sacré-Cœur stair shots are a named footage target. Fix: per-foot floor estimate over ~1 s.
- **[S2] "Toe phase throughout" branch unreachable** (`foot_lock.py:188-197,210`): forefoot landings pin the ankle at the later heel-down position → heel slap at touchdown.
- **[S3] SMPL passwords accepted from env vars** (`fetch-body-models.sh:8-9,19-27`): invites `SMPL_PASS=… ./script` into shell history and inheritance by every child. Prefer prompt-only or a 600 file like `fetch_flame.sh`.
- **[S3] Unsafe model loads**: `protagonist_id.py:88` `weights_only=False` on third-party OSNet weights; GVHMR checkpoints from a mirror with no hash check.
- **[S3] Batch thread defaults = all 16 hardware threads** (`footage-batch.sh:24,98`), against the HANDOFF machine rules on a box shared with or4.
- **[S3] Failures mislabelled**: `footage-batch.sh:68-69` `|| echo "no track"` turns OOM/import errors into content verdicts; `fetch-footage.sh` always exits 0 and a `.part` counts as downloaded.
- **[S3] `--auto-id` silently ignored** when `track_history.pt` is missing (`bench_gvhmr.py:207,219-220`). **`run-bench.sh clip "" --fresh` rmtree's every cached run** (`bench_gvhmr.py:154-155`, `run-bench.sh:12,23`).
- **[S3] Two foot-skate definitions in `qc.json`** (`motion_qc.py:74-86` vs `foot_lock.py:58-105`).
- **[S3] `tune.py` `stretch` has no lateral/neck bound** (`:94-101`); **`fit.py` never checks convergence or solvePnP's flag** (`:174-175,212-215,365`); **likeness env unpinned** (needs NumPy 2 via `numpy._core.multiarray` imports); **no cap on `lock_feet` pelvis drop** (`foot_lock.py:236`).
- **[S4] `private/` is world-readable**: `private` and `private/likeness` are 755, 153 subdirectories are `o+r`, likeness files 644. A second local user exists on this host (`or2-test`, per the secrets memory). `chmod -R o-rwx private` is a one-liner. Also: the cookie temp file in `fetch-body-models.sh` survives Ctrl-C (no `trap`); both login POSTs let curl resend credentials on a cross-host redirect (add `--proto-redir` / `--location-trusted` is *not* set, good, but pin the host); `fetch-youtube.sh:61` word-splits the cookie path.

### 1.12 Repo hygiene (own greps)

- **[S3] 24 hard-coded `/home/akram/code/or3` paths** outside docs: all `bench/m0/spike5/*.sh`, `spike6/*.sh`, `tools/acoustic-bake/build.rs`, `blender/hero/sets.py`, `blender/hero/fetch_textures.py`, and 11 `pipeline/video-to-motion` scripts (those at least honour `MAIN_ROOT`). The m1 harness derives the root from git (`lookdev.sh:20`), which is the right pattern; apply it everywhere, or a fresh clone cannot run the spikes.
- **Codename rule**: no `or3` identifier anywhere in code (the only hits are the paths above and the `IPLVector3` false positive).
- **No bare `except:`** in the tree. Two `TODO/FIXME` markers total.
- **No tracked image under `bench/m1`**; `bench/m1/v3/` holds only `BRIEF.md` and `hair.md`. Good: no fan render has been committed.
- **`.gitignore`** lacks `*.npz`, `*.npy`, `*.obj`, `*.jpg`, `*.exr` (see 1.11); add them, and consider a pre-commit hook that rejects any path containing `fan` or `likeness` outside `private/`.

## 2. Synthesis

### 2.1 Ranked: what to fix first

| # | Sev | Finding | Where | Why first |
|---|---|---|---|---|
| 1 | S1 | `lookdev.sh --compare` writes fan sheets and the fan config under `data/` | `bench/m1/lookdev.sh:28-33` | Real today, one normal command |
| 2 | S1 | Likeness isolation rests on wrappers: `FAN_CONFIG` env default + unrestricted `--out` + no fan guard in `character_provenance.py` | `build_character.py:46`, `character_provenance.py:67` | A tracked-file leak path with no code check on it |
| 3 | S2 | Facial-hair atlases bake linear RGB into sRGB images (beard/brows/lashes ~10× too dark in-game) | `beard_bake.py:91-100` | Explains an open m1 defect; gains were tuned against the bug |
| 4 | S2 | Trousers ship the jacket's AO in the GLB | `suit_textures.py:570-573` | Shipped asset is wrong, invisible in Cycles review |
| 5 | S2 | Shoes vertex order non-deterministic (`set()` delete) | `suit_shoes.py:383` | Known HANDOFF defect; one-line fix |
| 6 | S2 | 18 kHz bandwidth gate never fires; 3 accepted sources fail it, incl. the main footstep pool candidate | `analyse.py:143` | Listening gate is open now |
| 7 | S2 | Per-shot light twins ignore `key`; HANDOFF's purple-suit fix cannot work | `hero/rig.py:470-478` | Round 4 would waste a 95-min render |
| 8 | S2 | Stairs break foot contacts; toe-phase branch unreachable | `foot_lock.py:79-85,188-197` | Stair shots are a named footage target |
| 9 | S2 | `identity_codes.py` persists ArcFace embeddings; no output-path guard; gitignore gaps | `identity_codes.py:239`, `.gitignore` | Highest-stakes artefact in the repo |
| 10 | S2 | Empty chunk → invalid glTF; two-cell chunks overwrite tables | `plateau-chunk/glb.rs:313`, `main.rs:524` | First city milestone hits both |
| 11 | S2 | Documented build command and spike-1 bench exit 0 on failure | `build_character.py:7`, `bench_spike1_build.sh:22` | Stale GLB passes as success |
| 12 | S2 | Pose view not rebuilt on shared-memory growth | `web/src/main.ts:374` | Latent; bites as soon as the sim allocates |

### 2.2 Themes

1. **Likeness containment is procedural, not structural.** NOTES §14 rule 7 is enforced by two shell wrappers and good habits. Four independent paths around them were found (compare branch, env var default, `--config` carrying a fan block, provenance copier) plus a world-readable `private/`. One `assert_private(path)` helper used by every writer, a gitignore sweep, and a pre-commit hook would make the rule mechanical.
2. **Checks that report but never gate.** Budgets (tris, bones, textures), human-presence VAD/tagger, glTF validator crashes, cargo build errors in spike scripts, batch failures labelled "no track", `--python-exit-code` missing. The project's benchmark ambition depends on these being hard failures.
3. **Colour-space and copy-of-material drift.** The two most visible asset bugs (dark beard, wrong AO) both come from one module not following a convention the sibling module follows. A shared `make_image(..., srgb=)` and "never `.copy()` a material after its textures are wired" would close the class.
4. **Hidden state in caches and run order.** Drape cache key, `premaster/events` never cleared, `--prev auto` across agents, `rig.json` written before the GLB, random-stream coupling in the groom. Reproducibility claims in NOTES ("IoU 1.000 against itself") hold only on a warm cache.
5. **Duplicated helpers that have drifted.** Palm frame ×5 (three sign conventions), hand frame ×4, `kuwahara` ×2, `_value_noise` ×2, cap UV ×2, `Stat` table mirrored by hand in TS. Each pair is a latent inconsistency.
6. **Machine rules are documentation.** Thread defaults in `hero.sh`, `lookdev.sh`, `suit_dev.py`, `footage-batch.sh` exceed the HANDOFF limits; nothing checks loadavg or running Blender jobs before a final.
7. **Portability.** 24 hard-coded checkout paths, a `build.rs` that fails workspace builds on any other machine, an unpinned likeness env. For a repo whose stated purpose is to be re-run by future models, a fresh clone should at least `cargo test` and run the m1 harness.

### 2.3 What is good

The runtime core is small and correct, with a sound lock-free hand-off and exact pins. Credential handling learned its lesson everywhere it matters. The projection maths, glTF writer, loudness measurement, loop construction, config deep-merge, MPFB target bake, left/right pose mirroring and the FLAME fit/wrap self-tests were all checked and hold. Every RNG in the tree is seeded. Provenance is a real system with a schema, a policy file and an audit that runs in CI mode with no dependencies. The documentation (NOTES, HANDOFF, per-track reports) is unusually honest about open defects, which is why several findings here could be tied to items already on the list.

### 2.4 Suggested order of work

1. **Today, before any further fan run:** fix 1 and 2 (compare routing, drop the env default, `assert_private`, provenance guard, `chmod -R o-rwx private`, gitignore patterns). Half a day.
2. **Before the user's listening and look gates:** 6 (bandwidth metric, re-run `analyse` and flag the three sources), 3 and 4 (beard sRGB, trousers AO) with a rebuild, 7 (generalise twins before round 4 renders), 5 (shoes).
3. **Before m2 motion work:** 8, 9, the `--auto-id` fallback and the `--fresh` guard.
4. **Before city work:** 10, the clip-vs-assign contract, `build.rs` hardening.
5. **Ongoing:** turn the reporting checks into gates; collapse the duplicated helpers; replace hard-coded paths with the git-derived root.

_Full delegated reports (one per area) are in `/tmp/or3-review/*.md` for this session; everything above was cross-checked against the source before being written here. Nothing in the repo was modified by this review except this file._

---

## 3. Second pass: the character model, design and detail (strategy)

_2026-10-14. A design review, not a bug review. I looked at the pixels of the public build's final set (`data/build/hero/20261013T081828Z-main9-final/`: portrait, portrait crop, eye crop, profile crop, bust, draw, hands crop, the paint variant, the clay and normal turntables), the game-material EEVEE close-up and the 40 px read image (`data/build/lookdev/20261013T081002Z-heroE-main9/`), the shipped GLB (meshes, materials, textures, morph targets), the look-spec, both briefs, the direction and skin-direction consults, every track report's verdict table, NOTES §7/§10/§15 and `config.py`. The fan build was not viewed; everything below applies to the pipeline, so it carries over to it._

### 3.1 Honest read of the final renders

The character is a clean, well-engineered **mannequin**. At the bust and portrait it reads as a vinyl figure under good film lighting, not as a person, and the turntable confirms it is not a lighting trick. Per area, what the pixels say and which part of the pipeline causes it:

| Area | What reads as CG at 1080p | Root cause in the pipeline |
|---|---|---|
| **Head form** | Egg-shaped skull with a tall, domed forehead; a weak brow ridge; soft, undefined zygomatic arch; small, close-set, level eyes; a long upper face and short lower face; no plane breaks anywhere. The look-spec §2.1 "brow shelf ≥ 12 mm overhang, high cheek planes, crisp dorsum/side edge" is not in the render. The clay turntable is the proof: the head is a smooth ovoid. | `head_shape` pushes Gaussian fields on an MPFB default; `head_forms` adds mm-scale soft tissue. Neither can create *bony* structure (supraorbital ridge, zygomatic arch, mandibular angle, nasal bones) because they are smooth, low-frequency displacement on a mesh whose topology was never sculpted for them. `replanarise` was dropped to 0.35–0.6 to avoid facets, which also removed the planes. |
| **Skin** | Smooth vinyl at portrait distance: one highlight sheen, no pores visible until the eye crop, no mid-frequency relief, the SSS reads as uniform pink bloom. The eye crop shows pores as an even, regular stipple (texture-space noise), not skin. | Fully procedural noise in UV space on a 4k map. `head.md` §4 already documents that pores "stay sub-pixel" under the hero key and that the cross-hatch "reads as woven". The team has spent ~20 iterations (skin13–skin25) on procedural micro-detail that physically cannot carry the read at 85 mm. |
| **Eyes** | Flat amber discs, small aperture, no lid wrap, no wet line, lashes read as a dark smudge. Gaze is slightly divergent in the portrait. | Hero eyes exist (cornea, meniscus, caruncle) but the *socket* is not sculpted around them, so there is no lid-on-eyeball contact shadow mass. Iris albedo too bright for the grade. |
| **Beard and brows** | A black fur patch with a hard cheek edge and a lighter skin "halo" inside the moustache; the moustache barely exists; brows are a dense black bar. In the EEVEE game-material close-up the beard is **black spatter dots** (shells). | Cycles strands are decent but ship nowhere; the game gets 14 fur shells baked from them, plus the sRGB bug (§1.9). Fur shells are a 2005-era technique that fails exactly at the distance this project cares about. |
| **Scalp hair** | A dark helmet with painted strand lines, a hard cap edge at the temple, one broad highlight on the crown, the back one clump. The clay turntable shows the hair as a solid blob. | 20k-tri cards baked from the groom. The groom (`hair.md`) is good; the *cards* flatten it. There is no strand rendering in the game plan. |
| **Suit** | Boxy block shoulders, straight-tube sleeves with no elbow fold, a bell-shaped skirt, rubbery/neoprene surface, flat lapels, a plastic-sheen tie. The clay turntable has **no cloth folds at all**: sleeve, trouser and skirt are extruded tubes. | Garments are *lofted parametric tubes* (`suit_jacket.py` "block = horizontal slices of the torso"). Cloth behaviour is a baked normal map from a 20-frame settle (`suit_drape.py`), which cannot make a sleeve bend or a trouser break. Wool is a sheen factor on a flat loft. |
| **Hands** | Doughy sausage fingers, no knuckle definition at the hands shot, wrist a smooth cylinder into the cuff. | `hand_forms` adds mm bumps on the MPFB hand; MPFB hand topology is low and undefined. `hands.md` already notes "puffy dorsum". |
| **The painterly layer** | The `_paint` variant is indistinguishable from the beauty. | `grade.py` masks the character out of the Kuwahara and applies it to the set at 5 px. "Painted Neon-Noir" is not on the character at all. |
| **Game distance** | The 40 px read works (eye band, beard, hair silhouette). This is the one target met. | — |

Summary: the pipeline is excellent at producing *parameters* and *guards* and weak at producing *form*. Every track report says "improved" for its area, and each is right locally, but the sum is a figure that no senior character artist would pass. The measurable gates (IoU, landmark ratios, luminance ratios) all pass because they measure the spec, not the read.

### 3.2 Five structural ceilings (what tuning cannot fix)

**C1. The target renderer does not exist, so the shipped character has never been seen.** Every judgement is made in Cycles with hero-only geometry: strand grooms, random-walk SSS, adaptive displacement, refractive cornea, vellus hair, a 256-spp grade. None of that ships. The GLB carries cards, fur shells, a 4k normal and glTF PBR (`KHR_materials_sheen/clearcoat/specular/anisotropy` only). `web/src/` has no glTF loader, no skin, hair, eye or cloth shader, no TSL stylisation node, nothing. The EEVEE game-material close-up (`closeup.png`) is the nearest thing to what the player will see, and it is far below the hero render. NOTES §10 says "Blender is the look-dev oracle"; that is right for the *target* and wrong as the *only judge*. The character look is a renderer feature as much as an asset feature.

**C2. The direction is incoherent, and the result sits in the uncanny valley between its two halves.** The look-spec (§0, §2.1) asks for Sifu: simplified volumes, sharp planes, painted value inside planes, banded Kajiya-Kay, ink lines. The v2 brief asks for "believable AAA realism in a Cycles close-up" with paint *around* the face. The decision log records both. The build followed v2: realism in the face, paint masked off it, planarisation turned down. The outcome is soft realism that fails as realism (C3–C5) and has no stylisation to hide behind. Sifu, Arcane and Dishonored all work because the stylisation *is* the detail: painted texture, stepped lighting, exaggerated planes. A stylised character is also cheaper on the Air, holds at 40 px, and is original by construction.

**C3. The head has no sculpt layer.** The face pipeline is: MPFB macros → 28 MPFB targets → 15 Gaussian "controls" → mm soft-tissue forms → subdivide → re-planarise → procedural 4k skin. There is no stage where bony structure is built. The spec's brow shelf, zygomatic plane break and gonial angle need a **sculpt** (multi-resolution displacement authored against anatomical landmarks), not a lattice. The team has the tool already: `pipeline/likeness/wrap.py` wraps a FLAME fit onto the MPFB head with the eye cores preserved, and FLAME 2023 is CC-BY-4.0. That path is currently used only for the private fan build; nothing stops the *public* face from being a FLAME identity authored in shape-coefficient space (strong supraorbital, wide zygomatic, square mandible, age 45) and wrapped the same way, with the §2.3 controls on top. That alone would replace the egg with a skull.

**C4. Hair and beard ship as cards and fur shells, and the groom that looks right never leaves Blender.** The Cycles groom is 18–24k strands; the game gets 20k card triangles and 14 shells. Strand rendering is not exotic any more: on an Apple M4 in WebGPU, 25k strands × 16 segments as camera-facing ribbons (two triangles per segment, ~800k tris, one draw, no skinning per strand: strands follow the scalp cap's skinning via a root transform buffer) renders in well under 1 ms. The project already instanced 12,800 boxes at 3.1 ms GPU on the Air in spike 4. A short beard (30k strands × 6 segments) is the same technique. This is the single largest visible jump available for the shipped asset, and it removes two entire subsystems (`hair_groom_cards`, `beard_bake` shells) plus their bugs.

**C5. The suit is a loft, not a garment.** A tailored jacket's look is *all* structure: the roll of a canvassed lapel, a sleeve pitched forward and bent at the elbow, the drape of the skirt off the hip, the break of the trouser on the shoe. A lofted tube with a baked wrinkle map cannot produce any of these because the fold geometry is never created. Blender's cloth simulator has *sewing springs*: flat pattern panels sewn along seams and draped on the body produce exactly those folds, deterministically, headless. Pattern drafting for a men's lounge jacket, trousers, waistcoat and shirt is formulaic (Aldrich-style blocks from body measurements: chest, waist, seat, nape-to-waist, scye depth, sleeve length) and can be implemented from the body landmarks the pipeline already measures. That is a one-time module, and it makes every later improvement (per-pose wrinkle maps, Dem Bones from a sim, LOD retopo) possible.

### 3.3 Detail inventory against the stated bar

"Believable AAA hero" is a measurable bar. The table lists where the shipped asset sits against a current AAA third-person hero (TLOU2 / Dishonored 2 / Sifu class), and what closes each gap.

| Component | Shipped now | AAA reference | Gap closer |
|---|---|---|---|
| Head mesh | MPFB head, 1 subdiv on the face, ~26k tris head+hands+neck in two primitives | 20–40k tris head, topology sculpted for the face, 50–150 blendshapes | FLAME-based identity wrapped onto a sculpted-for-face topology (C3); ICT-FaceKit (MIT) expression basis later |
| Skin maps | 4k albedo/normal/ORM, fully procedural, no cavity, no micro-normal tile, no SSS in game | 4k + detail-normal tile at 0.1 mm, cavity/curvature, pre-integrated or screen-space SSS, dual-lobe spec, wrinkle maps | Keep procedural but add: curvature+cavity bakes into albedo and roughness, a tiled micro-normal (procedural pore tile at 2 mm period, 512², sampled at 50×), pre-integrated SSS LUT in TSL, pose-driven wrinkle normals |
| Eyes | Separate 6.7k-tri eyeball, PBR, clearcoat, occlusion baked into albedo (and the export drops the AO channel) | Parallax-corrected iris, caustic, refraction, lid AO mesh, wetness meniscus, tear line | TSL eye shader: parallax iris with depth, limbal darkening, cornea spec lobe, an AO lid shell with alpha gradient, meniscus strip; socket sculpt around the eyeball |
| Scalp hair | 20k-tri cards + cap, MASK alpha, Kajiya-Kay planned | Strands or 40–60k-tri card hair with flow/ID/depth, dual-lobe Marschner, OIT | Strand ribbons from the groom (C4); keep a 6k-tri card LOD1 for distance |
| Beard, brows, lashes | 14 fur shells + 180 cards, 12 brow shells, 2 lash strips | Strands or dense cards with proper alpha, painted base in skin albedo | Strands (C4); lashes as 2 cards per lid with a baked strand alpha (fine as is after the sRGB fix) |
| Suit geometry | Lofted tubes, 17.7k jacket, 4.7k trousers, 10 morph correctives | Pattern-sewn cloth, 30–60k tris jacket, pose-space wrinkle maps, cloth sim or SSDR bones | Pattern draft + sewing-spring drape (C5); Dem Bones from the drape (already planned) |
| Suit shading | glTF sheen 0.25 + twill normal, roughness map | Dual-layer wool (sheen + fuzz Fresnel), micro-twill, fibre-level anisotropy, dust/AO cavity | TSL cloth node: sheen + `1−N·V` fuzz rim + twill tile; cavity from the drape |
| Hands | MPFB hand + mm sculpt, 1.7k nail mesh | Sculpted hand with knuckle planes, tendons, 4–6 correctives | Hand sculpt via the same displacement layer as the head; a `corr_fist` fix is already open |
| Stylisation | None on the character; Kuwahara on the set in the compositor only | Sifu: painted albedo, stepped light, ink; Arcane: painted albedo + realistic light | Decide (C2). If painterly: bake stroke-space albedo (curvature-guided strokes, not Kuwahara), 3-band toon ramp with soft terminator in TSL, ink on silhouette and creases |
| Deformation | 83 bones, 16 helpers, 14 correctives, rules JSON | 100–200 bones, SSDR cloth bones, 50+ correctives, DQ or hybrid skinning | On track; DQ skinning in TSL for the body, LBS for cloth bones |
| Textures | ~65 MB of PNG in a 72 MB GLB, no KTX2 | KTX2/ASTC with mips, ~25 MB | glTF-Transform `etc1s`/`uastc` in `export.py`; already in NOTES |

### 3.4 Specific design corrections (public face)

These are judgments from the renders, expressed in the spec's own units so they can go straight into controls or the FLAME authoring layer:

- **Brow**: the supraorbital ridge needs 6–8 mm more forward projection at the mid-pupil line and a sharper underside; `brow overhang ≥ 12 mm` is a spec target that was never measured ("not yet measured" in look-spec §1.2). Measure it now; the render suggests it is ~5 mm.
- **Forehead**: 8–10 mm too tall from brow to hairline relative to the nose length (the face reads as upper-third heavy). Lower the hairline or lengthen the midface; the fan likeness work will have found the same.
- **Eyes**: aperture is small and the palpebral fissure too level; the lids barely wrap the globe. Add a 2–3 mm socket recess around the eyeball (sculpt layer), lower the upper lid 1.5 mm over the iris (the direction asked for this; the render shows the full iris top), tilt the lateral canthus 1–2° up, and converge 2° to 1.2 m (the portrait gaze diverges slightly).
- **Cheekbones**: the zygomatic arch needs a real bony ridge 4–5 mm proud of the sub-malar plane, running back to the ear, not a fat pad. This is the Sifu plane break and the single most identity-defining form in the spec.
- **Jaw**: the gonial angle reads ~125°; the spec says 115–120°. Under a beard the angle still shows in the silhouette and the profile crop.
- **Nose**: the dorsum is one soft curve; the spec's "crisp edge where dorsum meets side" is absent. A 1.5 mm hump is in the config; it is invisible in profile.
- **Mouth**: the lips are "slightly inflated" (head.md's own verdict) and the moustache does not overhang the vermilion. Thin the upper lip 1 mm, and let the moustache cover 2 mm of it.
- **Neck and shoulders**: the bust shot shows a head that is small for the shoulders (bideltoid 0.56 m plus a 3 cm jacket margin plus box padding). Either pull the jacket shoulder to body + 1.5 cm with a 3° drop, or accept a 7.5-heads figure for the game camera; the current combination reads as a boy in his father's jacket.
- **Hands**: large and square is the spec; the shipped hands are narrow with tapered fingers. Width at the MCP line should be ~0.55 × hand length; check the measurement.

### 3.5 Proposed programme: "m1 v4, structure first"

Ordered so each step changes what the next is judged on. Every step has a gate that is a picture, not a metric, plus one metric so regressions are caught.

1. **Decide C2 (user gate, one answer).** Recommendation: *painterly stylised realism on the character*. Realistic proportion and anatomy, painted (stroke-space) albedo, 3-band lighting with a soft terminator, ink on the silhouette and major creases, realistic specular on eyes and wet surfaces. Reasons: it is the stated art direction; it is achievable at 60 fps on the Air; it makes micro-detail a non-goal (the biggest current time sink); it holds at 40 px; the public face is original by style. If the user instead confirms realism, steps 2–5 still apply and step 6 becomes a photoreal TSL stack with a much higher GPU bill.
2. **Build the web character viewer before any more Blender iteration** (1–2 days). `web/src/character/`: glTF loader, skinning, the `character.rig.json` rules, a first TSL skin/hair/eye/cloth material set, the neon test rig as three.js lights, a turntable, and a headless Playwright screenshot path into `lookdev.sh` so every run also produces `game_*.png`. Gate: the EEVEE `closeup.png` is replaced by the engine's own frame in the contact sheet. This is the oracle fix (C1).
3. **Head: FLAME-authored public identity + sculpt layer** (3–4 days). Author the face in FLAME shape space from the §3.4 corrections, wrap with `wrap.py`, then add a headless "sculpt" stage: a multires-2 displacement authored as landmark-anchored fields for bony forms (ridge, arch, angle, nasal bones, orbit rim), baked to a mid-frequency normal and kept as morph-free geometry on the game mesh. Gate: clay turntable with visible brow shelf, zygomatic plane and gonial angle; `brow_overhang ≥ 12 mm` measured. Retire `replanarise`.
4. **Hair and beard as strands in the engine** (3–4 days). Export the groom as a compact strand buffer (root UV on the cap, N points per strand, 16-bit positions in head space, ~2 MB for 25k strands), render as ribbons in TSL with a Marschner-lite (two shifted lobes + tint), per-strand root AO, and a depth-sorted or alpha-to-coverage pass. Beard the same at 6 points. Keep the card build as LOD1 only. Gate: the engine portrait at 1080p beside the Cycles portrait; the hair silhouette and value structure must match. This deletes the fur-shell path.
5. **Suit from patterns** (5–7 days, the largest item). A `suit_pattern.py` block drafter from body landmarks (chest, waist, seat, scye, nape-to-waist, sleeve) producing 2D panels with seam allowances; sewing-spring cloth drape in Blender per garment with pinning at the collar and shoulder; quad remesh of the settled cloth to the budget; UVs from the panels (which also gives correct twill direction per panel for free); re-run `suit_drape` per pose for pose-space wrinkle maps, blended by the existing corrective rules. Gate: clay turntable with a bent sleeve, a lapel roll, a skirt that hangs off the seat, a trouser break. Shoulder: body + 1.5 cm, 3° drop.
6. **TSL look pass** (2–3 days, after 1): stroke-space albedo bake (curvature-guided strokes in Blender, baked to the same 4k; not Kuwahara), 3-band ramp with a 0.08 soft width, rim from the three neon lights, ink lines in a depth/normal edge pass at 1.2 px. Gate: the engine portrait reads as the art direction; a Sifu-side-by-side at 40 px and at bust.
7. **Eyes and hands** (2 days): socket sculpt around the eyeball, TSL parallax iris with the lid-AO shell, meniscus strip; hand sculpt via the step-3 displacement layer. Gate: the eye crop and the hands crop.
8. **Deformation** as already planned (Dem Bones from the step-5 drape, DQ skinning for the body in TSL).

Compute: every step above runs on this machine. The strand export and the viewer cost no render time; the pattern drape is minutes per garment; the only overnight job is re-baking the skin after the head changes.

### 3.6 What to stop doing

- **Stop tuning procedural micro-detail at 4k.** Twenty skin iterations moved the portrait from "waxy" to "smooth vinyl". Mid and macro form is the problem; pores are the last 2 %.
- **Stop judging in Cycles alone.** The hero render is a *target*; the gate is the engine frame.
- **Stop measuring Kuwahara on the set as "painterly".** If the character is not painted, the art direction is not met.
- **Stop raising spp.** 256 spp at 95 min per set buys nothing a 64-spp OIDN render does not show; spend the machine on the steps above.
- **Do not add more guards before the form is right.** The guards are good; they currently guard a mannequin.

### 3.7 Reuse that is already in the repo

Things to build on rather than rewrite: `wrap.py` (FLAME → MPFB topology with eye-core preservation), `hair_groom.py` (the groom is the strand source; it only needs an exporter), `suit_drape.py`'s transfer/gate logic (works unchanged on pattern-sewn garments), `deform_runtime.py`'s rules JSON (the pose-space wrinkle blend can ride on `cone` rules), `head_measure.py` (add `brow_overhang`, `eye_aperture`, `gonial_angle`, `hand_width_ratio`), `lookdev.sh` (add the engine screenshot as a view), and the hero stage (`blender/hero/`) as the reference the engine is compared against.

---

## 4. Why the character is not realistic: causal audit (read-only pass, 2026-10-14)

_Method: six read-only sub-audits (head geometry, skin, eyes/hair/beard, suit, render/export, body/rig) over the code, the hero config `bench/m1/variants/direction.json`, `character.stats.json` and `metrics.json` of the shipped build, plus my own inspection of the baked 4k maps at 1:1, the bald game-material face strip, the clay/normal turntables and the EEVEE close-up. No file in the repo was modified and no render was run. "inf" marks inference; everything else is from code or build output._

### 4.0 Root cause in one sentence

The pipeline authors form at two scales only, wide Gaussian pushes on a 4–5 mm base mesh and sub-pixel procedural pores, and the 0.5–20 mm band where a real face, hand and garment actually live is empty, so every stage produces a smooth parametrised approximation that the renderer then reports faithfully.

### 4.1 Head geometry

- Base: MakeHuman/MPFB head, 2,950 face verts, 1,126 scalp, 243 neck, about 4–5 mm spacing (inf). All shaping happens at this resolution; `head_refine` subdivides once afterwards and the hero adds adaptive dicing, neither of which adds form.
- Order: 28 MPFB targets → `head_shape` (Gaussian displacement fields) → soft planarise → `head_forms` (normal-direction tissue) → subdivide.
- Every "bony" feature is a wide bump: `brow_depth` 0.9 × 14 = 12.6 mm forward on σ 22/8/20 mm (`head_shape.py:29,165`), `brow_shelf` 1.5 mm, `cheek_height` 2.8 mm on σ 16/12/20, `jaw_width` 6.6 mm and `jaw_angle` 6 mm as translated blobs (`:183-187`). `zygomatic_arch_mm` and `temple_hollow_mm` are 0 (`head_forms.py:49`, not set in the config). No orbital rim, no nasal-bone region exists. Max move of the whole `head_shape` stage is 8.6 mm; `head_forms` max 2.76 mm over 2,475 verts.
- Mid-frequency band (2–15 mm) is empty or aliased: tissue Gaussians have σ 2.5–3.5 mm evaluated at ~one vertex per σ, so the nasolabial fold renders as a one-vertex-wide hard diagonal crease (visible in `face_strip.png`).
- Planes: `planarise` is a soft least-squares pull at blends 0.35–0.6 and excludes everything within 20 mm of an eye centre, which removes most of the brow-under group; dense `replanarise` is **0.0** in the hero config (`direction.json:94`). The 17 controls are all Gaussian fields; only three act through planes.
- Eye socket: `socket_depth` moves skin and eye helpers together, so there is no recess under a rim. Globe radius 15.0 mm (real ≈ 12), iris radius 5.85, aperture upper +2.0 / lower −5.4 mm (covers ~3.9 mm of iris top, sleepy fissure ≈ 7.4 mm). Lid-margin thickness is a 0.4 mm push.
- Mouth: thirteen stacked MPFB mouth targets at high weight (`mouth-scale-horiz-decr 0.85`, `upperlip-volume-decr 1.0`, `upperlip-height-decr 0.8`, `eversion 0.5`, `cupidsbow-incr 0.5`, `philtrum-volume-incr 0.5`, `compression 0.25`, …, `direction.json:25-37`) give the pinched, pursed, prosthetic mouth that the bald front strip shows. Under the beard this is the main uncanny feature.
- Asymmetry: 0.8–1.5 mm seeded offsets plus mirrored targets; no skull, jaw or orbit asymmetry.
- Metric: `brow_overhang` = 19.2 mm (floor 12), but it takes the most forward vertex anywhere 8–40 mm above the eye on the mid-pupil line (`head_measure.py:169-180`). `forehead_slope 0.9` pushes the forehead itself forward, so a bulge satisfies a test meant for a shelf. Gonial angle, orbit depth, eye aperture, canthal tilt, profile angles and symmetry are not measured. **§3.4's "never measured, ~5 mm" is wrong; the problem is the metric, not the value.**
- Bald front silhouette (face strip, ~0.96 mm/px): cranium ~155 mm wide above the ears, bizygomatic 135 mm, bigonial 117 mm; the lightbulb read comes from the forehead bulge, hollow temples (`forehead-temple-decr 0.5`), concave sub-malar and a tapering chin, not from skull width.

### 4.2 Skin

- Optics: portrait 85 mm, 0.42 m frame, 1.49 m distance → 0.39 mm/px, 2.6 px/mm. 4k map = 0.13–0.25 mm/texel, so texture resolution is not the limit.
- Relief is sub-pixel: whole game height field −0.316…+0.160 mm; pores 0.04–0.07 mm deep, 0.18–0.46 mm wide (0.5–1.2 px); cross-hatch 0.5 mm spacing (Nyquist) at 0.025 mm; orange peel 0.05 mm; lumps 0.10–0.25 mm over 6–15 mm (2–3° slopes). Wrinkles: forehead 0.30/0.24 mm, frown 0.10, crow's feet 0.15, nasolabial 0.25, under-eye 0.03–0.04 mm (`skin_synth.py:277,606`); line colour in albedo is 0.0. Hero displacement bounded to 1 mm.
- Albedo (1:1 crop of `skin_head_albedo.png`): flat colour with sparse dots. Mottle ±5 %/±3 % Perlin (effective σ ≈ 1 %, inf); fine redness ±2–3 %; freckles weight 0.22; "no mole, no scar" by ruling; skin20's capillary network was deliberately removed as "red lace". Measured Lab a* σ 0.86 vs ≥1.5 target. AO 0.10 + cavity 3 % baked into albedo.
- Roughness: ORM green over the whole head 0.357–0.718, mean 0.465, **σ 0.035**. Single Principled lobe, IOR 1.4, coat 0.02 + 0.10 × oil; dual lobe and sebum removed in skin25. `skin-direction.md:9` itself names "one continuous sheen" as the top CG tell.
- SSS: hero random-walk radius 3.4/0.75/0.34 mm; terminator hue shift 5.2° vs ≥6° target. Game `sss: 0.0` and glTF carries none.
- Cues absent or sub-pixel: vellus (20k, radius 0.008 mm, "unverified visually"), lip wetness (oil mask 0 on lips), eyelid wet band removed, ear translucency.
- History: 25 skin iterations; skin8–25 are almost entirely pore/cross-hatch/funnel/under-eye work; two of the later ones removed variation.

### 4.3 Eyes, hair, beard, brows, lashes

- Iris: painted albedo only, 3-octave value noise × colour, no normal, depth or scatter; limbal ring 0.55; hero iris matte. Sclera `#bdab9d` with noise veins, reads porcelain (`head.md:190`). Wet film only on the cornea skirt, meniscus 0.15 mm on the lower lid only, no waterline. Lid occlusion baked in albedo and kept at 50 % in the hero. Caruncle a 1.8×1.1×0.5 mm bead. Lashes 240/60 per eye, roots uniform random (real: 2–3 rows). Game eye: flat sphere, no parallax or refraction.
- Scalp hair (public): 520 guides, 40k strands × 24 pts, radius 0.045→0.02 mm, clumps 36/360 at 0.85/0.8 (~110 strands per secondary clump), noise 1.5 mm, frizz 0.5 mm, 4 % flyaway. Huang BSDF melanin 0.985 (10 % at 0.93), redness 0.12, roughness 0.22–0.30. Hairline: scalp vgroup distance field, 9 mm temple bays, 8 %→100 % over 10 mm, no per-hair irregularity; baby hair 1,400 vellus at 3–6 mm, sub-pixel. Scalp albedo only 4 % darker; hero dark shell fades in 8–30 mm past the hairline so the first 8 mm is bare skin. Rope-like clumps + near-black specular-only shading + smooth hairline = painted helmet.
- Game hair: 484 cards / 21k tris, 2048² atlas, strands drawn 2.2 px, MASK 0.5 via ROUND (`export.py:34-52`), plain Principled (roughness 0.55, specular 0.25, no anisotropy); flow/ID/depth maps not wired. Cap: one 512² window of the front hairline wrapped around the head; in the temple bays v is clamped at `lo`, so the edge row never fades and any opaque texel streaks to the mesh edge (`hair_groom_cards.py:837-849`).
- Beard: 360 roots/cm² + 240 undercoat, Chiang melanin 0.99, cheek fade 15/12 mm, uniform density → solid blob with crisp edge. Moustache: 12 mm tall band, philtrum free 6 mm, hair length capped to ~7–11 mm, combed flat down, no roots on lip vertices, `beard_lip_dark` 0 → reads as absent. Brows ~1,500–2,000 strands at 22° elevation, uniform → dark bar. Game: 14/12 shells, each MASK 0.5, 33–37 % of strands, 3× strand width, plus the sRGB bug (§1.9).

### 4.4 Suit

- Construction (`suit_build.py:111-156`): each ring = body slice max radius per angle, chord-filled, + radial ease (jacket chest 24, back 14, side 20, waist 13–16, hip 18 mm). Sleeves are straight tubes along the bone with 8 mm ease, 58→44 mm radius; elbow is a 4 cm direction blend. Trousers straight below the knee. No side body, back seam, pitch, pad geometry; `deform.md` says "bent tube".
- Shoulder: jacket half-width 25.7 cm, **4.6 cm narrower than the body bideltoid**; the spec asked for +2–3.5 cm. §3.4's "too wide / boy in his father's jacket" is wrong; the small-head read comes from the body (bideltoid 0.56 m, +4 % vs ANSUR-scaled; bizygomatic 0.135, −10 %).
- Folds: sim only on jacket and trousers, P0→P1 nearly rest pose, pinned at chest/back/collar/lapels/sleeve ends/hem, 5 cm high-pass, `base_gain` 0.1 outside seven regions, tanh clamp at 4 mm, baked to normals only. Fold RMS 1.44 mm (jacket) / 0.96 mm (trousers). Only `suit_folds.py` adds geometry: ≤5 mm at elbow crook and knee back. No crotch, seat, hip, sleeve-hang or button-pull folds.
- Material: weave 25 µm at 1.9 mm period (slope ~0.08), hero twill 0.6 mm period (sub-texel); roughness 0.68 ± 0.03, sheen 0.35, albedo 0.013–0.019 ± 0.008; no fuzz geometry, no thickness. Hems, seams, pick-stitching, buttonholes are 0.4–0.9 mm height-map features; single-sheet garments.
- Budget: jacket 17,747 (spec ≤9,000), trousers 4,688 (≤3,500), shirt 3,580 (≤1,500), waistcoat 2,999 (≤2,000), buttons 2,130 (≤200), shoes 4,824 (≤3,000); suit ≈36.4k vs ≈20k. Density sits on a uniform grid, not on folds.

### 4.5 Body, pose, hands, deformation

- LBS only (glTF cannot carry DQ, none in TSL yet). 17,781 of 26,089 body verts single-influence. 14 correctives (arm up/forward/down, elbow, hip, knee, fist); none at neck, wrist, spine, clavicle.
- Neck: 243 verts, one bone, no SCM/trachea/larynx/trapezius form, and `neck-scale-horiz-decr 0.35` thins it against the spec's "thick, short-looking".
- Hands: MPFB hand subdivided once, `hand_forms` normal-only offsets ≤1.43 mm out / 0.68 in; taper from stock mesh; creases and veins texture only. `hands.md`: "puffy dorsum"; HANDOFF: "doughy fingers".
- Pose: pelvis 4°, spine −5° total, shoulders 5° back, head 10°/3°; no S-curve, no scapular motion; rest is an A-pose at 42°.

### 4.6 Render stage and export

- Smoothing chain: OIDN HIGH with albedo+normal, `blur_glossy` 0.5, default ~1.5 px film filter, 2 % grain. With detail already sub-pixel, the chain removes what is left. (Lighting form is fine: key 0.3 m at 1.5 m, 55° off-axis, 30° up; wrap 0.25, fill 0.08.)
- World near-black (0.003–0.016), no HDRI, character lights flagged to the character only, so no bounce fill; lit:shadow ≈ 15:1 (inf). Rims (magenta 2.2, teal 1.2) exceed the key (1.0); hair and cloth get desaturated light-linked twins, so skin, hair and cloth are lit by different colours.
- Grade is benign (AgX base contrast, −0.6 EV, small CDL, sat 0.97). Kuwahara only in the `_paint` A/B and masked off the character.
- GLB drops: SSS, displacement, strands, vellus, refractive cornea, meniscus, caruncle, coat/sheen on skin, hair flow/ID/depth, and the AO channel is ignored by the importer. `export.py` only sets alpha.
- Gates: silhouette IoU, spec landmark ratios, read40 (calibrated on our own variants), numeric skin crops, a human "3 s" look. No step compares against a photograph; v2 forbade reference photos.

### 4.7 What the evidence says would move the needle

1. A sculpt layer at 1–2 mm spacing for brow ridge, orbital rim, zygomatic arch, mandible border, nasal bones, neck and hands; then re-enable dense planes.
2. Halve the mouth target stack; recess the eye under a rim; 12 mm globe; 1–2 mm lid thickness.
3. Skin authored at 0.5–3 mm relief and 1–20 mm albedo structure (melanin/haemoglobin/capillary layers, a few moles), two-lobe specular, roughness map with 10–20 % structure, no AO in albedo.
4. Moustache length and under-lip darkening, beard density variation, weaker hair clumping, irregular hairline with visible baby hair.
5. Garments from patterns with an unpinned drape kept as geometry; shoulder to body + 2 cm with a pad.
6. Metrics for what the look-spec actually asks (gonial angle, orbit depth, aperture, canthal tilt, profile angles) and a photo-reference comparison in the gate.
7. Render: film filter 0.8–1.0 px, lighter denoise on a skin mask, a dim wide set fill, rims ≤ key, same light colour on all materials.

---

## 5. Hair: deep review and research (2026-10-14)

_Read-only. Sources: my inspection of the hero portrait/profile/back/turntable hair, the EEVEE close-up and the card atlas; a line-by-line audit of `hair_groom.py`, `hair_groom_cards.py`, `hair_frame.py`, `export.py`, `hero/rig.py` and the v2/v3 hair reports; and two web-research passes (real-time hair in WebGPU, professional groom practice in Blender hair curves). Numbers marked [est] are extrapolations, not measurements. The fan build was not viewed._

### 5.1 What the pixels say

- **Hero portrait:** a dark mass with a few painted parallel strand lines, one broad magenta sheen band, no flyaways, a solid slab in front of the ear, a temple blob with a hard edge against the forehead, and a soft smudge for a hairline.
- **Back and turntable:** a wet-mop silhouette flat to the skull at the crown, rope-like clumps, and a blunt equal-length end all round that reads as a wig line. The hair is jet black; the "10 % lighter strands" are invisible, so a 45-year-old with a greying beard has no grey hair.
- **Card atlas (`hair_atlas_albedo.png`):** every cell is a flat near-black silhouette with sparse jagged polyline strokes of uniform width, no tip gradient, no colour variation and almost no interior alpha. Cell 4 is nearly empty yet used by mid-rank cards. This atlas cannot render as hair whatever shader is put on it.
- **EEVEE close-up:** painted strips with hard MASK edges and streaks at the temples.

### 5.2 Why: the groom

Construction (all `blender/character/hair_groom.py`):

| Stage | What the code does | Why it reads wrong |
|---|---|---|
| Roots | 20k area-uniform samples on scalp + temple/nape bands, farthest-point to 520 guides (L706). Root prob = 0.08 + 0.92·smoothstep(0,10 mm,d)^1.2; d ≤ 0 rejected (L449) | Hard cut at 8 % density; constant-width feather; no noise, no asymmetry, no single-hair units |
| Guide marching | 10 mm steps, one **global** comb vector (±part push, +Y, −drop) (L252); part = centre + 12 mm with ±2 mm sine wobble, only on top-front | No direction field, no whorl, every edge hair combed the same way → "painted helmet" |
| Stand-off | `lift_profile` front 14 / crown 8 / side 36 / back 26 mm + 0–4 mm jitter (L277, L339) | Sides float 36 mm off the skull as a shell; crown is flat |
| Hang | gravity blend behind the ears, skin/suit collision 4 mm, ear ellipsoids 8 mm | OK |
| Length | **height cut** at z = neck + 0.85·(shoulder − neck) ± 25 mm (L338) | Equal-length blunt ends: the wig line |
| Resample | 24 points per 0.45–0.55 m strand = 20–24 mm spacing (L365) | Visible polyline kinks in strands and atlas |
| Front falls | 4 rigid guide copies overwrite 260–360 nearest strands each (L390, L720) | Solid slabs over the brow and ear |
| Interpolation | 4 nearest guides, same side of part, 1/(d+2 mm)² | OK |
| Wave | one sine per primary clump, 4–8 mm, 12–18 cm period, hanging part only (L785) | No curl, no per-strand variation |
| Clumps | 36 primary / 360 secondary at **0.85 / 0.8**, ramp 0.2→1 over 6 cm (L853); Preserve Length off | ~110 strands collapse per secondary clump → ropes; clumping shortens strands |
| Noise / frizz | 1.5 mm / 0.5 mm | Fine, but applied before clump so partly erased |
| Flyaways | 4 % of strands get 10 mm noise (L800) | Displaced strands, not stray hairs |
| Radius | 0.045 → 0.020 mm, t^1.5 (L846) | Root thick, tips too thin for *cut* hair (cut ends are blunt) |
| Vellus | 1,400 at 3–6 mm, r 0.018 mm | ~20 per cm of hairline, sub-pixel at the portrait |
| Scalp | tint shell α = 0.85·smoothstep(8,30 mm,d) (L668) | First 8 mm inside the hairline is bare pale skin |

Shading (`hair_material`, L605–655; `hero/rig.py` L311–430, L692–710):

- Huang BSDF, melanin **0.985**, redness 0.12, random colour 0.08, roughness 0.22→0.30, IOR 1.55, aspect 0.85. Melanin 0.985 → absorption quantity 4.2; red transmission through one hair ≈ 1.7 %, blue ≈ 0 [computed]. TT and TRT lobes vanish, only the white R lobe survives: one highlight on a black blob. The 10 % "light" strands at 0.93 are still black.
- Huang roughness is roughly the square of Chiang's; 0.22–0.30 is probably too rough for a sharp primary highlight (Blender issue #123451).
- No grey, no root-to-tip gradient, no per-lock colour.
- Hair shape is never set, so the hero renders the 5.2 default **ribbons**; `hair_inspect.py` uses THICK, so review renders and hero renders differ.
- Light-linked twins desaturate rims to 0.4× for hair only; hair still casts shadows from the originals.

### 5.3 Why: the cards

`hair_groom_cards.py`:

- One ribbon card per secondary clump (361) + 2 under-cards per primary + 4 front-lock + 12 front-fall + 40 flyaway strips = 484 cards, 20.8k tris. Width = 92nd-percentile spread + 1.8 mm; 3 verts wide, centre lifted 0.3 × half-width. No LOD.
- Atlas: 2048², 6 × 2 cells (~329 × 1012 px each, ≈0.09 mm/px across but ≈0.4 mm/px along). Each cell rasterises one clump's 24-point polylines as 2.2 px lines, z-buffered; alpha = box-filtered coverage. **Eight cells feed ~45 cards each.**
- GLB material: albedo × COLOR_0, normal from a smoothed volume proxy, roughness 0.55, specular 0.25, no anisotropy; flow/ID/depth PNGs written beside the GLB but not wired (L327–334). `export.py:34-52` routes alpha through ROUND → MASK 0.5; mipmapped coverage under MASK makes thin cards vanish with distance.
- Cap: 2.5 mm shell; texture is one 38° front-right window tiled ~9.4× around the head.

Defects found (fix regardless of strategy):

1. **Temple-bay streaks** (L848–849, L774–781): `d = max(d_eff, 0)` then `v = lo + …`, so every vertex inside a 9 mm bay gets v = lo exactly and samples the strand-root row; roots are also piled onto that row in `bake_cap_texture`.
2. **Cap texture is nearly empty** (L778–782, inferred from arithmetic): the bake breaks strands at 15 mm but main-strand spacing is 20–24 mm, so most strands reduce to one point and are skipped; the cap shows vellus plus a synthetic core.
3. `atan2` seam at back-centre and pole at the crown smear the cap texture (L847).
4. Wisp cell 11 is baked but never referenced; cell 4 near-empty but used.
5. `push_out` (L490) checks control points before GN; clump/noise/frizz can push strands into skin or suit (18,140 points pushed at build time).
6. Cap UV uses raw `d_eff` while the cap mesh is boundary-smoothed 6 iterations (L833): millimetre misregistration.
7. Ribbons vs THICK (above).
8. §1.9 sRGB bug in `beard_bake.py` (beard/brows, same family).

### 5.4 Research: what good looks like

Groom practice (XGen/Ornatrix/Blender Studio; see sources in the agent report):

- Real scalp ≈ 100k+ terminal hairs at 140–280 /cm²; hero grooms run 50–150k. 40k is the floor; 60–80k with 0.035–0.04 mm radius is the comfortable range.
- Clump hierarchy, 3–4 nested levels with **varying** sizes and **low** factors: L1 30–40 mm (40–60 clumps, 0.25–0.4), L2 8–12 mm (~400, 0.3–0.5), L3 2–3 mm (3–5k of 8–15 strands, 0.3–0.4), L4 micro ~0.5 mm (0.15–0.25). Use Tip Spread, Clump Offset and Distance Falloff so clumps never fully converge; Preserve Length on.
- Layer order: clump → coherent wave (3–8 mm, 1–2 waves per strand) → noise 1–2 mm → frizz 0.3–0.8 mm → Straighten (root-weighted) → Shrinkwrap → Smooth (2–3 it, lock tips) → Trim (random offset 5–8 %) → profile with Factor Min 1 (cut hair is blunt; taper only flyaways/vellus).
- Hairline: a ~1 cm transition of mostly single hairs, irregular and asymmetric; edge hairs point **forward** then sweep back a few mm later; no clumping at the edge; at 45, M-shaped temple recession with finer, shorter, lighter hairs at the edge. Perturb the distance field with 2–3 octaves of 1–2 mm noise at 3–8 mm scale, and make the density ramp non-monotone.
- Colour for near-black with grey: melanin **0.75–0.88** (transmission 16–30 % red), redness 0.05–0.15, Random Color 0.15–0.25, root darker than tip; 8–15 % grey strands overall, 20–30 % at the temples, grey = melanin 0–0.5 with neutral tint and some half-pigmented strands.
- Shader: Chiang gives controllable R/TRT and coat (the "two shifted highlights"); Huang is far-field, flat close-up and renders dark. A/B Chiang (roughness 0.2–0.3, radial 0.3, coat 0.1–0.3, offset 2–3°) vs Huang at 0.08–0.16. Render curves as **3D Curves** for the hero; glossy bounces ≥16, total ≥32.
- Lighting: dark hair is mostly specular; it needs a back/rim light and a second light from the opposite side for the two highlights, and a fill so the shadow side keeps detail.

Real-time hair (Frostbite 2019/2020, Capcom RE4, Unity Enemies, UE5 Groom, Lipp 2026, Scthe's WebGPU port):

- Shipped strand systems cost 4–9 ms on PS4/PS5-class hardware for 10–25k strands with custom compute rasterisers and visibility buffers; Lipp 2026 does 127k strands in 3.1 ms on an RTX 5080 only with a 64-bit-atomic visibility buffer. WGSL has 32-bit atomics only (64-bit min/max is a draft proposal). The one WebGPU strand renderer found (Scthe/frostbitten-hair-webgpu) is Chrome-only, ~3.3 ms for the fine pass on an RTX 3060, no TAA, flickers, drops long segments.
- No three.js or Babylon strand library exists. three.js WebGPU supports 1× or 4× MSAA and `alphaToCoverage`.
- AAA hair cards: 15–30k tris for photoreal hero hair (UE5 heroes up to ~50k), in **layers** (cap/core, volume, mid clump, flyaway, hairline/baby-hair cards), textures of alpha + flow + depth + ID + root-tip, shaded with dual-lobe Kajiya-Kay (or Karis's three-lobe) using the flow map, alpha via A2C + 4× MSAA + hashed alpha and TAA, never sorted MASK.
- **Revision of §3.2 C4 / §3.5 step 4:** strand ribbons are not the first move for this engine. Estimated M4 Air cost for a close-up strand pass is 4–8 ms [est] with high implementation risk (WebGPU raster, Retina memory, thermals, flicker). Cards done properly are 1–2.5 ms [est], one to two weeks, and are where most of the current "looks bad" actually lives. Strands become a later cinematic mode (20–30k strands × 12 segments, 1–1.5 px ribbons, A2C + hashed alpha, LOD by screen footprint).

### 5.5 Programme: "hair v4"

Ordered; each step has a picture gate. Steps 1–3 are Blender-only and change what the cards are baked from, so they come first.

1. **Groom rebuild (3–4 days).** 60–80k strands, radius 0.04 mm blunt; 4-level clumps at the factors above with Preserve Length; length as a *cut* (trim with 5–8 % random offset, plus a 2–3 cm layered taper at the ends) rather than a height cut; a direction field (forward at the hairline, back on top, down behind the ears, whorl at the crown) replacing the global comb; stand-off profile halved at the sides; the four rigid front-fall copies replaced by guides with their own interpolation; flyaways as separate 1–3 % stray hairs. Gate: clay turntable and back view show layered ends and no helmet.
2. **Hairline and scalp (1–2 days).** Noise-perturbed, asymmetric hairline with M recession; single forward-pointing edge hairs; vellus 2–3× denser and r 0.025 mm so it reaches a pixel; scalp albedo darkened toward the roots with baked hair AO; the tint shell starting at 0 mm not 8 mm. Gate: `portrait_crop` hairline reads as skin-to-hair, not blob-to-skin.
3. **Shading (1 day).** Melanin 0.82 ± Random Color 0.2, 12 % grey weighted to the temples, root-dark/tip-light; Chiang vs Huang A/B under the hero rig; 3D Curves; glossy bounces 16. Gate: two distinct highlights visible in the portrait, hair no longer black under the magenta rim.
4. **Cards rebuilt from the new groom (3–5 days).** Layered cards (cap/core, volume, mid, flyaway, hairline), 30–40k tris; per-card atlas cells at ≥0.15 mm/px along the strand with 48-point resampled strands, alpha gradient at the tips, albedo with per-strand variation; bake alpha + flow + depth + ID + root-tip into the GLB (ORM-style packing); fix the seven defects in §5.3; cap UV from the smoothed boundary with a proper fade. Gate: EEVEE close-up next to the Cycles portrait at 512 px.
5. **Engine shader (2 days, needs §3.5 step 2's viewer).** TSL dual-lobe Kajiya-Kay (shifted primary white lobe + tinted secondary, shifts jittered by the ID map, flow-map tangents), A2C with 4× MSAA plus hashed alpha, root AO from the root-tip channel, depth prepass for the solid core. Gate: engine portrait vs Cycles portrait, hair value structure and silhouette match.
6. **Beard and brows** follow the same path (groom density variation, moustache length and under-lip darkening, cards instead of shells, sRGB fix) once the scalp path works.
7. **Optional later:** strand ribbons as a cinematic mode, only if 4–5 fail review.

### 5.6 Stop doing

- Raising strand count without lowering clump factors; it makes thicker ropes.
- Judging the hair under the magenta/teal rims only; put a neutral two-light hair test in the contact sheet.
- Baking cards from 24-point polylines.
- Treating melanin 0.985 as "dark hair"; it is "no transmission".
