_SwiftShader only: every engine frame and timing here is WebGPU in headless Chromium on the CPU (port 8796, CPUs 0-3, a shared machine at load 30-40). Cycles is Blender 5.2 at `-t 6` under `/tmp/or3-cycles.lock`. Track T25 (Cycles target retune + plate harness), m1 v4, 2026-10-15. Brief: `checkpoint-3.md` §3.2, §5.4 and the T25 row of §4. Public build only. The final numbers are on main 0092b1c (T17 merged) plus T25, on main's T17 asset `lookdev/20261015T045405Z-t17-a8`. ArcFace was not run (its tooling is under `private/`); the run dirs are listed at the end. No photographs were collected._

# m1 v4 track T25: the Cycles target, toward photographic

## The read (three sentences)

Yes, a little: with the rims at or below the key and the fill now the alley's warm bounce, the magenta no longer paints the camera-right temple, cheek and ear, and the teal no longer outlines the jaw and beard, so the head reads as lit by one warm key in a neon street rather than gelled. Most of the jump from this morning's frames to `final_triptych_head100.png` (forehead and brow texture, socket depth) is T17's skin, and on the same asset the face is still evenly, frontally lit and waxy at 100 %. The cheek target (lit:shadow ≤ 8:1) was already met before T25 (2.3–3.6), because key, wrap and eye light are all near-frontal; a more photographic face needs a darker, more sculpted shadow side, which means changing the key that skin-direction.md binds (the user's call).

## The pictures (`data/build/t25/gate/`)

**Final, on merged main and the T17 asset:**
- **`final_triptych_head100.png`**: the portrait head at 100 % (540 × 540 at (766, 98) of the 1920 × 1080 frame; the Cycles panel is the 100 % `portrait_crop` at (210, 0)). Panels: engine before (T17's own `game_portrait_beauty.png`, old rig) | engine T25 | Cycles T25.
- `final_head100_engine_before_after_cycles_before_after.png`: engine before | engine T25 | Cycles before (`hero/20261015T051208Z-t17-a8`) | Cycles T25. Within each renderer, the asset and code are the same, so only the rig differs.
- `final_cycles_portrait_before_after.png`, `final_cycles_portrait_crop_before_after.png`, `final_engine_portrait_before_after.png`, `final_closeup_hero_before_after.png`.

**Lighting-only A/B on the pre-T17 asset** (`lookdev/20261015T012639Z-t20-f2`, branch before the merge; every shot):
- `cycles_portrait_before_after.png`, `cycles_portrait_crop_before_after.png`, `cycles_head100_before_after.png`.
- `cycles_profile_before_after.png` and `cycles_sign_before_after.png`. The sign suit still reads near-black, not plum, with its cloth twin.
- `engine_portrait_before_after.png`, `engine_head100_before_after.png`, `closeup_hero_before_after.png`, `triptych_head100_engine_before_after_cycles_after.png`.

**Other:**
- `chart_sheet.png`: the graded grey chart, Cycles | T25 engine.
- The first blind sheets (harness test, placeholders): `data/build/t25/plates/sheet_01..06.png`.

## Before → after

"Before" is the rig at the branch point (5900412). "Final" is merged main (0092b1c) + T25 on the T17 asset, unless the row says otherwise.

| Measure | Target | Before | **T25 (final)** |
|---|---|---|---|
| Rim / key, configured, worst shot | ≤ 1 per rim | 8.33 (profile); portrait 2.2 / 1.2 | **≤ 1.0 on every shot** ✓ (`rim_key` in `engine_stage.json`) |
| Rim / key on the image, top-1 % head highlight vs the key's (Cycles parity head, t20-f2) | (info) | rim 0.47, kicker 0.54 | **rim 0.21, kicker 0.32** |
| Cheek lit:shadow, Cycles alley portrait (EXR) | ≤ 8:1 | 2.50 (T17-a8) | **2.34** ✓ (parity 3.18) |
| Cheek lit:shadow, engine portrait (parity view, display) | ≤ 8:1 | 3.58 (T17-a8) | **3.18** ✓ (beauty 2.84; Standard view 3.03) |
| Grey chart after the grade, 18 / 50 / 90 % patches, max \|d\| | ±3/255 | 1.14 (T19) | **0.95** ✓ (−0.35/+0.61/+0.52, −0.95/+0.16/+0.80, −0.21/+0.07/+0.70) |
| Grey chart, grade only (own linear → CPU LUT vs own graded frame), both renderers | ±3/255 | — | **Cycles 0.59, engine 0.11** ✓ |
| Grey chart, 18 % ball samples (reported, not gated) | — | −2.84 (T19) | **−2.35** (R, terminator) |
| Per-light chart, 18 % patch, engine / Cycles: key / wrap / fill / eye | (info) | 0.996 / 1.005 / 1.041 / 1.019 (T19) | **0.996 / 1.005 / 1.131 / 1.019** (fill ✗ at +13 %, see §3) |
| Shader balls per light, net of the world, direct-only Cycles: key | ±10 % | skin 0.944 (T19) | **skin 1.047**, wool 1.023, silk 1.051, leather 1.036 ✓; hair cards 0.241, eyes 1.196 ✗ (T20/T18 materials, as in T19) |
| … fill | ±10 % | skin 0.920 (T19) | **skin 1.040**, wool 1.037, silk 1.086, leather 1.043 ✓; hair cards 0.353, eyes 1.209 ✗ |
| Skin shader ball, full studio rig (T17's measure) | ±10 % | 0.896 (T17) | **0.896** ✗, unchanged and bit-identical (see §3) |
| Hair / Cycles per light (T16 recipe, studio closeup): key / fill / rim | 0.8–1.2 | 0.986 / 1.077 / 0.961 (T19, t12-b2 asset) | **0.853 / 0.940 / 0.880** ✓ |
| Portrait crown / back vs Cycles (T16 recipe) | within 20 % | ×0.967 (T19) | **×0.703** ✗ (engine 1.461, Cycles 2.079; see §3) |
| Turntable temporal noise (T16 recipe: TRAA 48 Hz, warm-up 24, `lut=0`, 640 px, 2 s) | ≤ 3.39 | 3.051 (T17-a8, old rig) | **3.077** ✓ (frame max 3.55) |
| Shadow maps, hero rig | ≤ 5, skin ≤ 16 textures | 5 | **5** (unchanged; skin renders) ✓ |
| Twins on the portrait | hair only | rim, kicker, fill × (props, hair) | **rim, kicker × hair** ✓ |

## 1. What changed in the rig, and why

**Rims at or below the key.** Before T25 the alley shots (portrait, sign, draw, eye, bust, back, walk) used `shots.RIMS` = magenta rim 2.2, teal kicker 1.2 against key 1.0, so they could beat the sign spill. The profile ran a teal rim 2.5 over a key of 0.3 (×8.3), and the hands a rim of 1.4 over a key of 0.8 (×1.75). The ratios are irradiance at the subject, normal to the light.

On the image the rims never actually out-shone the key's highlights on the head (`lights_before`: rim top-1 % 0.47, kicker 0.54 of the key's). But they did paint the face's edges:
- The magenta rim put 10 % of the shadow cheek's light and 65 % of the shadow temple's on skin.
- It tinted the whole camera-right edge of the face, jaw and ear.

Now:
- `rig.RIM_MAX = 1.0`, with `rig.rim_key_ratios(lights)` and `rim_key` per shot in `engine_stage.json` (`hero.rim_max`).
- `HERO_LIGHTS` rim 1.4 → 1.0, kicker 0.8 → 0.7.
- `shots.RIMS` rim 2.2 → 1.0, kicker 1.2 → 0.7.
- Profile: key 0.3 → 0.6, teal rim 2.5 → 0.6, magenta kicker 0.35 → 0.3, ev +0.4 → −0.4 to hold the exposure.
- Hands: the rim gets its own 0.8, equal to that shot's key.

| shot | rim / key before | after |
|---|---|---|
| portrait, bust, back, walk | 2.2, kicker 1.2 | **1.0, 0.7** |
| profile | **8.33**, kicker 1.17 | **1.0, 0.5** |
| hands | 1.75, kicker 1.0 | **1.0, 0.875** |
| draw, eye | 1.4, kicker 0.8 | **1.0, 0.7** (draw top 0.4) |
| sign | 0.69, 0.38 (unchanged; its key is the magenta sign) | 0.69, 0.38 |

**The fill is the set's bounce.** It was a cool `(0.55, 0.7, 1.0)` 0.08, 2 × 2 m at az −55, el −5. Now it is 4,800 K, 0.15, 3 × 2.5 m, at az −60 and el −20: wide, low and on the shadow side.
- The colour is the alley's own bounce. `refs.py --mode bounce` measures r:g:b 1.24 : 1 : 0.82 facing the camera, about a 4,800 K blackbody.
- As a Kelvin light it is never saturated, so it gets no twins.
- It now gives 20 % of the shadow cheek's light (was 11 %), replacing most of what the rim gave there.
- It is still flagged to the character in the alley.

**Same light colour on all materials.** `rig.twin_plan` no longer gives every saturated light a default props twin (the pistol slide). The `CLOTH_TWIN` on bust, back and walk is gone, and so is the profile's skin twin. Portrait twins go from rim/kicker/fill × (props, hair) to rim/kicker × hair.
- **Kept:** the hair twins (HAIR_RIM_SAT 0.4) and the profile's beard twins (T3's teal beard edge). Those are the brief's "twins only for hair".
- **The one non-hair twin left:** the sign shot's cloth twin (30 %, 0.75), on its magenta key, rim and kicker. T3 found the black suit read purple under the 1.3 magenta sign key, which is a key, not a rim. The sign before/after shows the suit still near-black.

**Not changed:**
- the key (3,000 K, 0.3 m, 55°/30°; skin-direction.md is binding), the wrap and the eye light;
- the film filter and denoise (T17's `HERO_FILTER_PX` and skin denoise in `stage.py`);
- the grade.

## 2. The cheek lit:shadow ratio was already ≤ 8:1

`bench/m1/face_light.py` measures the lit and shadow cheek boxes on the head crop:
- lit cheek (150, 330)–(210, 390);
- shadow cheek (380, 320)–(440, 380), in crop coordinates of the 540 × 540 head at (766, 74);
- scaled for other frame sizes.

It reads a stage EXR (scene-linear, the object-index mask from the multilayer's second part), or a graded PNG, sRGB-decoded only. `refs.py --mode lights` renders the parity portrait's head once per light (with its twins). `face_light.py lights` gives each light's share of each box and its highlight against the key's.

| frame | before | after |
|---|---|---|
| Cycles alley portrait, EXR (t20-f2 asset) | 2.46 | 2.35 |
| Cycles parity portrait, EXR (t20-f2) | 3.13 | 2.97 |
| Cycles per-light sum, parity head (t20-f2) | 3.15 | 2.99 |
| Cycles alley portrait, EXR (T17 asset) | 2.50 (`t17-a8`) | **2.34** |
| Cycles parity portrait, EXR (T17 asset) | — | **3.18** |
| Engine portrait (parity view), display (t20-f2) | 3.15 | 2.94 |
| Engine portrait beauty, display (t20-f2) | 2.86 | 2.68 |
| Engine portrait (parity view), display (T17 asset) | 3.58 (T17's frame) | **3.18** |
| Engine portrait beauty, display (T17 asset) | 3.15 (T17's frame) | **2.84** |

**Why it was already flat.** The shadow-cheek box is about 40 % key light even before T25: the key at 55° camera-left still reaches the far cheek across the nose. The wrap (0.25, 1.5 m square, 35°) and the eye light (at the camera, lighting the whole face since T19) add another 40 %. The face's darkest regions are the eye sockets and under the nose, not the cheek.

The 8:1 ceiling guards against a black shadow side. The hero's actual problem is the opposite, an evenly lit face. I did not darken it: the key and wrap are binding in skin-direction.md and outside the brief. It is listed under "Left".

## 3. Engine follows

All re-run on merged main (0092b1c + T25) with the T17 asset. The rig is re-exported by `export_rig.py` into `engine_stage.json`.
- **`web/src/character/stage.ts`**: one minimal edit, to the fallback `light_specs` used when an older `engine_stage.json` has none. Rim 1, kicker 0.7, fill 4,800 K as linear RGB `[1.241, 0.957, 0.719]`, 0.15, 3 × 2.5 m, az −60, el −20, matching `rig.HERO_LIGHTS`. Nothing else in T19's files changed.
- **Shadow maps / the skin's 16-texture budget.** The fill already cast a shadow map before T25: T19's `shadowRe` covers key, rim, kicker, fill and wrap, so there are 5 maps, and T17 counted its 16 skin textures with that rig. T25 adds no light and no map; the hero rig still reports 5 PCSS maps plus linked hair twins (`final/m_shots.json`). The merged engine renders the skin correctly (`final/m_portrait*.png`, `m_closeup_hero.png`); it is not black.

**The grey chart.** The Cycles chart refs (`refs.py --mode chart`, all lights and per light) and the engine charts were re-rendered on the T17 asset under the T25 rig. The patches hold at 0.95/255 (T19: 1.14) and the 18 % ball samples at −2.35 (T19: −2.84).

One trap is worth recording. My first engine chart used Cycles chart refs built from the t20-f2 blend with an engine export from the a8 asset. The chart ball sits at the eyes, which are 5 mm apart between those two assets: ~15 px at the portrait camera. The samples then hit the wrong part of the ball and read −8.5/255 at the terminator. I confirmed this by rendering the same engine build and export on T16's chart (key-only centre 0.0787, T19's exact value) and on the t20-f2 chart (0.0694). The engine itself had not changed: pre-merge build, merged build and `?contact=0` / `gtao=0` / `pcss=0` all gave bit-identical key-only frames. **The chart's blend and the engine export must come from the same asset.**

**The per-light chart.** The 18 % patch luminance, engine / Cycles, is key 0.996, wrap 1.005, eye 1.019 (T19: 0.996 / 1.005 / 1.019). The ball samples under the key are 0.98 / 0.96 / 0.91 (lit / centre / terminator).

The new fill is hot in the engine: **1.131 / 1.101 / 1.097** on the 18 / 50 / 90 % patches, and 1.09–1.16 on the ball. T19's 2 × 2 m fill at el −5 measured 1.041.

Its share of the 18 % patch is about 4 % of the total, so the full chart still holds at 0.95/255. The shader balls under the fill pass too (skin 1.040, silk 1.086). That is why I left it.

The likely cause is the hybrid LTC on a light this large and close: 3 × 2.5 m at 2.5 m subtends about 62° × 53°, and from 20° below the camera axis. The fix is in `lighting.ts` (T19's), or the fill could be scaled by 0.9 in the export. I did neither (see "Left"). Rim and kicker barely reach the camera-facing chart (0.0005 of the key), so their ratios there are noise.

**The shader balls are not lit by the hero rig.**
- `lookdev_render.py --shader-balls` and the engine's balls scene use the neutral look-dev studio. The engine ball frame on merged main + T25 is bit-identical to T17's `game_balls.png` (mean |d| 0.0).
- So the full-rig skin ball stays at **0.896**, and nothing in T25 can move it.
- Per light, net of the world, against direct-only Cycles on the T17 asset, the skin ball now passes: **key 1.047, fill 1.040** (T19: 0.944 / 0.920; the change is T17's skin).
- So the full-rig miss is not the key or fill. It sits in what the per-light runs leave out:
  - the world/indirect term: Cycles has bounces, the engine has none in the balls scene;
  - the rim: T19 measured the skin under the rim at 0.40.
- This is for T17/T19's owners (a rim-path or ambient term on the skin), not a light-rig change. I did not retune the skin gain.

**Hair.**
- **Per light:** the T16 recipe passes (key 0.853, fill 0.94, rim 0.88). It uses the studio closeup, so it checks the merged engine, not T25's rig.
- **The portrait crown / back fails at ×0.703.** This one is T25's, indirectly. Cycles' crown, relative to the forehead, falls from 0.079 to 0.044–0.050 with the rims at key level: the 2.2 magenta rim from behind and above was what lit the crown. The engine matched Cycles' crown under that rim (T19: ×0.967). Without it, the engine crown under the key and fill is 57 % of Cycles' (0.028 vs 0.050 of the forehead; the back is 81 %).
- That is an engine hair deficit under a frontal-high key (deep shadow / hair occlusion on the crown) that the old rim was hiding. It is T20's hair, and per light it is consistent with the key closeup's 0.853.

**Turntable:** 3.077, ≤ 3.39 ✓. T17's a8 turntable with the old rig was 3.051, so the rig's effect on temporal noise is within run-to-run noise.

## 4. The plate harness (`bench/m1/plates.py`)

A sheet is 6 tiles (540 px, 3 × 2, labelled A–F only):
- the engine hero head;
- the Cycles hero head;
- 3–4 plate slots.

Render tiles are cut at 100 % from the frame, never resampled. The defaults match the head crops above: engine `@766,98` of the 1920 × 1080 portrait, Cycles `portrait_crop.png@210,0`; both are the same window of the same camera. Plates are centre-cropped, or cut at a person-chosen square box in a `<plate>.crop.json` sidecar, then resampled to the tile.

The order is shuffled per sheet. The answer key goes to `key/answer_key.json` in a separate directory, with each letter's kind, source file and the seed. `answers_template.json` is for the judge.

`score --key --answers` passes when the engine tile is picked as a render no more often than the plates' rate, over ≥ 6 sheets. It refuses to score a harness test.

**Rules (enforced, not only written):**
- **Location.** Plates live in `bench/ref/plates/` of the main checkout. That directory is gitignored (`.gitignore`), and `tools/hooks/check_staged.py` refuses any staged path under it, sidecars included. Two new containment cases cover this; `test_containment.sh` is at 75/75.
- **Licence record.** A plate is used only if `provenance/plates.jsonl` holds an `accepted` record `plate:<file name>`. Its licence must be CC0-1.0 or LicenseRef-PDM-1.0 and its sha256 must match the file. Otherwise `sheet` skips it and `check` reports it.
- **Template.** `provenance/plates.template.json` is the record template, and `record FILE` prints a filled line (sha256, status pending). `provenance/audit.py` passes on both.
- **Use.** Plates are a lighting/material comparison only: never a face or form target, never an input to fitting or measuring. `plates.py` only crops, resamples and shuffles them, and no other script reads the directory.

**How plates get added.** This needs the user's yes first; checkpoint-3's orchestrator note says so.
1. Pick CC0 or public-domain photographs: an anonymous bearded man, hard key plus coloured rim, head and shoulders, 50–135 mm equivalent, sharp at a ~540 px head. Use different plates per sheet (≥ 3–4 per sheet, ≥ 6 sheets). Never the actor.
2. Save the original bytes into `bench/ref/plates/`.
3. Run `python3 -I bench/m1/plates.py record FILE --author … --source-url … --download-url …`. Check the licence on the source page, set `"status": "accepted"`, append the line to `provenance/plates.jsonl`, then run `python3 -I provenance/audit.py`.
4. Optionally add `<file>.crop.json` `{"box": [x, y, size]}`.
5. Run `plates.py check`, then `plates.py sheet --engine … --cycles … --sheets 6`.

**Tested without photographs:**
- `data/build/t25/plates/`: 6 sheets with placeholder slots (grey card; T17's Cycles crop; T17's engine head) around the final engine and Cycles heads. The key marks this as a harness test.
- `/tmp/t25/platepath_test.sh`: the record path, on five synthetic gradient stand-in files with a scratch manifest (`--manifest`). Results: audit 0 errors; `check` 4 ok and 1 pending skipped; sheets drew only the accepted files; one used its `crop.json` box.

## Files

- `blender/hero/rig.py`: `HERO_LIGHTS` (rim, kicker, fill), `RIM_MAX`, `RIM_NAMES`, `rim_key_ratios`, `twin_plan` (no default props twin), docstrings.
- `blender/hero/shots.py`: `RIMS`, no `CLOTH_TWIN`, profile and hands lights, the sign's cloth twin documented.
- `blender/hero/export_rig.py`: `rim_key` per shot, `hero.rim_max`.
- `blender/hero/refs.py`: `--mode lights` (`HEAD_CROP`, per-light head renders).
- `bench/m1/face_light.py` (new): cheek lit:shadow, per-light shares, rim/key highlights.
- `bench/m1/plates.py` (new), `provenance/plates.template.json`, `provenance/plates.jsonl` (empty), `.gitignore`, `tools/hooks/check_staged.py`, `bench/m1/test_containment.sh` (+2 cases).
- `web/src/character/stage.ts`: fallback `light_specs` only (T19's file; minimal, see §3).

## Run dirs

**Final: merged main + T25, asset `lookdev/20261015T045405Z-t17-a8`.**
- **Engine** `data/build/t25/final`:
  - `m_portrait.png`, `m_portrait_beauty.png`, `m_closeup_hero.png` (gate frames, **for ArcFace**), `m_shots.json`;
  - `mb_balls.png`, `ph_*closeup.png`, `hp_ph.json` (hair);
  - `tt_turntable/`, `tt_turntable.mp4`, `tt_shots.json`;
  - `s_portrait.png` (Standard view).
- **Cycles:**
  - `hero/20261015T071556Z-t25-final`: portrait, portrait_crop, sign and profile in the alley; `portrait_crop.png` is the Cycles head **for ArcFace**.
  - `hero/20261015T072517Z-t25-final-parity`: parity portrait.
- **Charts:** Cycles refs `data/build/t25/refs_final/chart*`; engine `data/build/t25/chart_final2` (`c_report.json`, `c_per_light.json`).
- **Balls:** `data/build/t25/final_balls`: direct-only Cycles `cycles_balls_{none,key,fill}_direct.png`, engine `e_*`, `e_ball_parity_net_direct.json`, `mb_balls_parity.json`.
- **Before (old rig, same asset):** T17's own runs, `lookdev/20261015T045405Z-t17-a8` (`game_*`) and `hero/20261015T051208Z-t17-a8`.

**Lighting-only A/B on the pre-T17 asset `lookdev/20261015T012639Z-t20-f2`, branch before the merge.**
- **Cycles:**
  - before `hero/20261015T050517Z-t25-before` (portrait, crop, sign, profile) and `hero/20261015T050647Z-t25-before-parity`;
  - after `hero/20261015T055520Z-t25-after` (all nine shots) and `hero/20261015T054944Z-t25-after-parity`.
- **Per-light heads:** `data/build/t25/lights_before`, `data/build/t25/lights_a1` (`face_light.json`).
- **Engine:** `data/build/t25/eng_before` (`b_`) and `data/build/t25/eng_after` (`a_`). The `eng_after` queue was stopped after its gate frames when main moved; its charts etc. were redone on the merged build.
- **Bounce / charts (t20-f2):** `data/build/t25/refs_after/{bounce,chart*}`. Do not pair these charts with an a8 export (§3).
- **Superseded:** `data/build/t25/chart_final` (the misregistered chart), plus its diagnostics `d_*` and `p_*`, `chart_t19stage`, `chart_t19glb`, `chart_t16glb`.

**Plates:** `data/build/t25/plates` (6 harness-test sheets, `key/answer_key.json`).

## Left / notes

- **The flat face is the bigger realism problem, and it is the key's.** Key 55°/30°, wrap 0.25 at 35°, and the eye light at the camera lighting all of the face give lit:shadow of about 2.3–3.6. A photographic low-key portrait in a night street runs about 4–8:1.
  - The next step would be to drop the wrap (or move it to the key side and shrink it), and to make the eye light a catchlight only. In the engine that means turning `light.eyeAll` back off for skin, and T19 turned it on to match Cycles.
  - Both cross skin-direction.md, which is binding, so this needs the user's call.
- **Crown / back ×0.703** (§3). The engine crown under the key is 57 % of Cycles'. That is T20's hair and was masked by the old 2.2 rim.
- **The full-rig skin ball 0.896** is unchanged by T25, and the rig cannot change it (§3). Per light, key and fill pass. The miss is the rim and world terms (T17/T19).
- **The per-light fill chart.** The engine runs +10–13 % hot on flat patches under the new 3 × 2.5 m fill. It is within budget on the full chart and on the balls, but it is a real model error for large, near, low area lights. The candidates are T19's hybrid LTC (the fit for a 60° source) or horizon clipping; the cheap workaround is `fill.ratio × 0.9` in the engine export only. Not done, because it would hide the model error.
- **Profile.** Its rim went from 8.3× to 1× the key. The silhouette shot keeps a teal edge on the nose, brow and beard, but it is much less of a neon silhouette now (`cycles_profile_before_after.png`). If the user wants the old look back, the rule should get a named exception like the sign's, not a quiet override.
- **The sign shot keeps its cloth twin.** That is the one non-hair twin.
- **The plate test** needs the user's yes and real plates. The harness, the hook and the licence path are done and tested on placeholders. Every sheet so far is a harness test, and `score` refuses those.
- **Not run:** ArcFace (`private/`); an Air capture (every engine number is SwiftShader).
- **Main moved during the track.** I merged main 0092b1c (T17, T24, T13b) before the final engine re-match; there were no conflicts. The pre-merge `a_` frames are the lighting-only A/B on the old asset.
