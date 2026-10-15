SwiftShader

_Every engine frame and timing in this report is WebGPU in headless Chromium on the CPU: port 8797, CPUs 8–11, a shared machine at load 30–44. **SwiftShader frame times say nothing about the Air.** They are recorded for information only, to show that the switches change the work. Track T24 (code part), m1 v4, 2026-10-15. Brief: `checkpoint-3.md` §5.2–5.3 and the T24 row of §4. Public build only, and nothing under `private/` was opened._

# m1 v4 track T24: quality tiers, GPU timing, LOD1 and the Air runbook

Pictures (`data/build/t24/gate/`, from the run dir `data/build/lookdev/20261015T045719Z-t24-a1`):
- `tiers_3m_side_by_side.png`: the hero tier and the gameplay tier at the gameplay framing (3 m, hero rig, 1024², KTX2 assets).
- `tiers_3m_head_4x.png`: the head from the same two frames, 4× point-sampled.
- `tiers_3m_torso_2x.png` and `tiers_3m_feet_2x.png`: the torso, and the feet with the floor.
- `tiers_3m_absdiff_x4.png`: |hero − gameplay| × 4.
- `tiers_closeup_side_by_side.png`: the hero closeup, hero tier (LOD0, PNG asset) next to the gameplay tier (LOD1, KTX2), 75 %.

## Gate

| gate | result |
|---|---|
| Both tiers render, 0 console errors | **Pass for the device capture and the engine stills; not on a 16-texture adapter in the live hero portrait** (§5).<br>• Fixed two errors that every run had. The one 404 of every engine run since T5 was `/favicon.ico`; `character.html` now declares a data-URL icon. Separately, every canvas frame after a capture at another size raised `Destroyed texture [contact shadows] used in a submit`, which T19's `contact.ts` started; the fix is in §5.<br>• Results: the hero-tier device capture (`air/t24-diag-cap`) has 0 errors, and the gameplay-tier live overlay (`air/t24-selftest-live`) has 0.<br>• Engine stills: `hero_shots.json`, `gameplay_shots.json` and `hero2_shots.json` each hold only the favicon 404, because they ran before the favicon fix.<br>• Open: the live hero portrait on SwiftShader. Its eye shader binds 18 textures against SwiftShader's limit of 16, which is WebGPU's default. |
| Perf JSON has per-pass entries | **Pass.** `data/build/air/t24-selftest-vite/{hero,gameplay}_perf.json` has `perf.passes[]` (the rAF loop) and `perf.synced.passes[]` (T19's measure). The hero synced passes are the scene (MRT), 5 shadow maps by light, the AO prepass, DoF ×5, the TRAA resolve, contact, the bright pass and the output. |
| LOD1 ≤ 65k tris | **Pass: 57,920**, from 166,370, in both `character.lod1.glb` and `character.lod1.ktx2.glb`. |
| 3 m: gameplay tier shows no visible regression against hero, side by side | **The figure passes, but the floor contact is lost.**<br>• Face, hair, beard, suit, hands and silhouette read the same at 3 m. In the 4× crops the gameplay tier is a little softer (TAAU 0.8), and the lapels lose some rim separation.<br>• What changes visibly is the floor. The hero rig's rim (magenta) and kicker (cyan) cast the feet's shadows across their floor pools. With one shadowed light (the brief's gameplay spec) those shadows go, and the shoes look set on the floor rather than in it (`tiers_3m_feet_2x.png`, `absdiff`).<br>• This portrait rig's key does not reach the floor near the feet.<br>• Not fixed here; see *What's left*. |
| `?capture=1&upload=1` round-trips the perf JSON locally | **Pass on both servers.**<br>• `engine_shots.mjs --serve --selftest` → `data/build/t24/rt_serve/`: 13 files, with `session.json` last.<br>• Vite dev server (the Air path) driven by `air_selftest.mjs` → `data/build/air/t24-selftest-vite/`: the hero → gameplay page chain, then `session.json`.<br>• `?perf=1` overlay **save** → `data/build/air/t24-selftest-live/live_perf.json`. |
| `cd web && npm run build` | **Pass** (tsc and vite). |
| `bash bench/m1/test_containment.sh` | **Pass: 73 passed, 0 failed.** |
| `python3 -I provenance/audit.py --data-root <main>/data --check-files --release` | **Pass: 178 records, 0 errors, 0 warnings.** |

## 1. Two quality tiers (`web/src/character/tiers.ts`)

`?tier=hero` (the default; every feature on, as T10–T20 built them) and `?tier=gameplay`. Both are presets over one set of per-feature switches, collected and documented in the header of `tiers.ts`. Any switch given on the URL wins over the tier, for example `?tier=gameplay&gtao=0`. Every switch is read at setup (materials, lights and the GLB are built once), so changing one means a reload.

| switch | what it drives | hero | gameplay |
|---|---|---|---|
| `aa` / `scale` | TRAA, TAAU, or the MSAA parity path, plus the TAAU render scale (T16) | traa / 1 | **taau / 0.8** |
| `dof` | thin-lens DoF on the beauty frames (T16) | 1 | **0** |
| `hairshadow` | deep hair shadow on the hair twins (T10) | 1 | **0** |
| `hairocc` | T20's baked 6-direction hair occlusion (`hair.dirOcclusion`) | 0 | **1** |
| `shadows` | the lights that cast at all: `all`, or a list, with every other light added to T19's `stage.noShadow` | all | **key** |
| `fillshadow` | fill and wrap shadows (T10) | 1 | 0 (moot with `shadows=key`) |
| `shadowmap` | `light.mapSize` (T19) | 2048 | **1024** |
| `pcss` | PCSS, or T10's 5-tap PCF (T19) | 1 | **0** |
| `contact` | key contact shadows (T19, `contact.ts`) | 1 | **0** |
| `specocc`, `ltc`, `eyeall`, `sharemaps` | T19's specular occlusion, hybrid LTC, eye light on every material, twins sharing the parent map | 1 | 1 |
| `gtao` / `aores` | GTAO on/off and its prepass + AO resolution (`SceneAO.resolution`, new) | 1 / 0.5 | 1 / **0.25** |
| `ssss` | T17's separable SSS (a pass named `ssss` or `skin.ssss`) | 1 | **0** |
| `detail` | T17's skin detail normals (`skin.detailNormal`) | 1 | 1 |
| `lod` | 1 loads `character.lod1[.ktx2].glb`, falling back to LOD0 with a warning | 0 | **1** |

- **`ssss` and `detail` are no-ops on this branch**, because T17 has not merged. `stats().tier.noop` lists them until a pass named `ssss` or the params `skin.ssss` / `skin.detailNormal` exist. Then they switch with no change here.
- **What is left on in gameplay.** LTC, specular occlusion and the eye light stay on: checkpoint 3 §5.2 does not cut them, and their cost is inside the scene pass, which only the Air can split.
- **The gameplay framing.** `?view=gameplay` adds a third-person framing, `gameplayCamera()` in `tiers.ts`, injected as one more look-dev camera:
  - 3 m from the hips by default; `&gpdist=2.5..4` changes it;
  - at the three-quarter azimuth, just above eye height;
  - a 46° vertical FOV, so the head is ~90 px of 956 at 3 m and 60–120 px over 2.5–4 m (checkpoint 3 §1.1).

  It has no f-stop, so no DoF. `gameplay:hero` puts it under the hero rig.
- **Changes in T19's files are minimal.**
  - `ao.ts`: a `resolution` field (default 0.5, so the same `w >> 1` as before).
  - `profile.ts`: additive. It adds a CPU per-pass fallback (encode time between the backend's `beginRender` and `finishRender`, exclusive of nested passes), p95 per label, and a live mode, `live()` / `collectGPU()`, for the overlay.
  - `contact.ts`: its target is allocated once at a fixed size, and each frame renders into a viewport of it. This fixes a destroyed-texture error (§5); the shader itself is unchanged.
  - `stage.ts` is untouched. The tiers use T19's `noShadow`, `light.mapSize` and `light.pcss`.
- **The device's texture limit.** `main.ts` asks the adapter for its per-stage texture and sampler limits (capped at 48). WebGPU's default is 16, and the live hero portrait's eyes need 18 (§5).

## 2. GPU timing (`perf.ts` on T19's `profile.ts`)

- **Live, `?perf=1`.** An overlay at bottom left shows:
  - the tier, AA, canvas, view, shadow-map count and LOD;
  - frame (rAF to rAF) p50 / p95;
  - the render call's CPU ms;
  - the GPU ms per frame (the sum of the frame's render-pass timestamps);
  - the top passes with GPU mean (p95), or with CPU encode ms when there is no `timestamp-query`.

  **save** POSTs the report as `live_perf.json` to `/upload/`, or downloads it if there is no sink.
- **The report** (`PerfReport`) holds:
  - `frame_ms`, `cpu_render_ms` and `gpu_ms` (each `{p50, p95, mean, n}`);
  - `passes[]`, each `{label, gpu_ms, cpu_ms, share}`. Labels come from T19's labeller: `shadow map: key`, `AO prepass normal`, `scene (MRT)`, the TRAA / TAAU resolve, contact, DoF, bright pass, the output quad, and so on;
  - `synced`: T19's `measure()`, in which every frame is waited for, with per-pass p50 / p95 and CPU encode ms.
- **Device capture** (`?capture=1&upload=1&tiers=hero,gameplay`). Each tier is its own page load. The page captures stills, then a 2 s turntable (T10's recipe: 20°/s, 24 fps, history at 48 Hz, 24 warm-up frames, temporal-noise number). It then runs a 600-frame rAF-paced perf loop at the canvas size and a 30-frame synced profile, and uploads `<tier>_perf.json` and `<tier>_shots.json`. Then it reloads itself for the next tier, keeping the session id. The last page posts `session.json`.
  - Frames go up as PNG where the browser can encode them, because the host is remote.
  - Without `tier`/`tiers` the old T6 names (`game_*.png`, `game_shots.json`) are kept, so `lookdev_report.py engine` still reads them.
- **Upload sink** (`web/upload-sink.mjs`). Two servers share it:
  - **the Vite dev server**, the Air path: `POST /upload/<name>?session=<id>` writes to `<data/build>/air/<id>/`. It is off when `CHARACTER_ASSET_ROOT` points at a private dir and `CHARACTER_UPLOAD_DIR` is not given;
  - **`engine_shots.mjs --serve`**, which writes into the run dir and exits after `session.json`.

  Both accept only whitelisted names and write only inside that one directory. The dev server also serves the KTX2 transcoder at `/basis/` now; before this, `?ktx2=1` did not work under `npm run dev`.
- **`bench/m1/air_selftest.mjs`** drives a device-capture URL (or, with `--live S`, the overlay's save) in headless SwiftShader through every tier's reload and reports any console errors. It stands in for the Mac.

## 3. LOD1 (`web/tools/lod1.mjs`, `export.lod1`, `build_character.py --lod1`)

meshoptimizer 1.1.1 (`simplifyWithAttributes`, MIT, already in the lockfile through `@types/three`, now a pinned devDependency) simplifies each primitive to its own triangle target. It collapses edges onto existing vertices, so positions, skin weights and the corrective morph targets of the kept vertices are exact, and only the index buffer changes. Unreferenced vertices are then compacted out of every attribute and morph target. Before simplifying, the scalp hair drops whole cards by atlas cell, read from the build's `hair.atlas.cells`:
- dropped: the fly-aways (`fly*`) and the one-strand cells (`flyone*`, which also carry the 90 baby hairs), 5,760 tris;
- kept: the core (under / lock / front / hairline) and T20's outer layer, shortened in segments instead.

Textures pass through, so `character.ktx2.glb` → `character.lod1.ktx2.glb` is the KTX2 gate asset. The suit targets stand in until T13b exports its own suit LODs; when it does, they replace these rows.

| primitive | tris before | LOD1 | error (mm) |
|---|---|---|---|
| skin_head | 27,618 | 10,500 | 0.35 |
| skin_hands | 32,400 | 7,500 | 0.53 |
| hair_cards | 45,156 | 15,500 (5,760 dropped: `fly0-1`, `flyone0-3`) | 6.52 |
| hair (cap) | 816 | 599 | 0.75 |
| beard | 12,000 | 5,000 | 1.59 |
| eyes_hq | 6,720 | 2,000 | 0.15 |
| nails | 1,736 | 600 | 0.61 |
| jacket | 18,000 | 5,999 | 1.54 |
| trousers | 4,688 | 2,000 | 1.61 |
| shirt / waistcoat | 3,580 / 2,999 | 1,399 / 1,200 | 1.14 / 0.93 |
| shoes leather / sole | 3,484 / 1,340 | 1,199 / 449 | 2.65 / 4.22 |
| buttons | 2,130 | 699 | 2.4 |
| teeth / tongue | 479 / 448 | 300 / 200 | 5.34 / 1.12 |
| brows, lashes, caruncle, lid shell, meniscus, tie | 2,776 | unchanged | — |
| **total** | **166,370** | **57,920** | |

- **Reading the errors.** The error is meshoptimizer's, scaled by each primitive's extent. For the hair cards, 6.5 mm is a card's length shortening, not a surface moving.
- **Teeth and sole** have the largest relative errors, but at 3 m both are under a pixel (a head is about 90 px).
- **The closeup** (`tiers_closeup_side_by_side.png`, which also changes the tier) shows where LOD1 is visible up close:
  - the fly-aways are gone;
  - the jaw and cheek silhouette is a little faceted;
  - the hair core holds.

  The gameplay tier never frames a closeup, so this is only a check.
- **File sizes.** `character.lod1.ktx2.glb` is 38 MB against 45 MB for LOD0 KTX2. The textures dominate and are shared; texture LOD is in *What's left*.

## 4. Air session runbook (`bench/m1/v4/air-session.md`)

One page, about 10 minutes:
- tunnel `ssh -N -L 5173:127.0.0.1:5173 archlinux` and `npm run dev`;
- one URL that captures both tiers by itself (stills, 2 s turntables, perf loops), 4–5 min;
- two live overlay URLs (hero portrait, gameplay framing), 30 s each, then **save**;
- Chrome's Task Manager for tab and GPU memory.

Everything lands in `data/build/air/air1/` (and `air1-live-*/`). The page lists every file and the fields to read.

## 5. SwiftShader smoke (information only)

**Not representative.** This is CPU rendering at load 30–44 on 4 pinned cores, and identical runs differ by up to 1.5×.

| frame (1024², 8 still subframes) | hero tier | gameplay tier |
|---|---|---|
| gameplay framing, 3 m, hero rig | 174.6 s | 86.3 s |
| closeup, hero rig | 273.7 s (PNG asset) | 130.2 s |
| triangles rendered (incl. hair twins) | 213,456 | 75,133 |
| draw calls | 27 | 27 |
| shadow maps | 5 @ 2048 PCSS | 1 @ 1024 PCF |

The synced per-pass profiles at 640×360 come from the Vite device capture (`air/t24-selftest-vite`), in GPU timestamp ms on SwiftShader. Each tier is at its own perf view, so the two are not the same frame:
- **hero** (`portrait:hero`): 12,550 in total. Scene MRT 5,285; shadow maps: kicker 1,431, key 1,033, fill 772, wrap 443, rim 248; AO prepass 321; DoF far blur 228.
- **gameplay** (`gameplay:hero`): 1,099 in total. Scene MRT 443; key shadow map 139; output 103; TAAU resolve 90; AO prepass 84; GTAO 14.

The ratio, about 10×, says only that the switches remove work. The Air's numbers come from `air-session.md`.

**What the smoke run and the round trips found:**
- **`Destroyed texture [contact shadows] used in a submit`, fixed.** It came on every canvas frame after a capture at another size: 7 errors per hero device capture.
  - Cause: T19's `contact.ts` resized its target with `rt.setSize()`, which destroys the GPU texture. three rebinds a render object's textures only on a full refresh, and the key light's shadow node is not a material property that its observer watches. Steady canvas frames kept the stale bind group.
  - Fix (T19's file; the edit is confined to the target): the target is allocated once at 2048² R8 (4 MB), and each frame renders into its top-left `w × h` through the viewport, sampled through a UV scale. Growing past 2048 swaps in a larger target and marks the materials for update.
  - Verified: 0 errors in the hero device capture, and the 256² hero frame is identical to the old code's (PSNR 120 dB).
- **The perf loop's `gpu_ms` counted timestamps from before the loop, fixed.** Passes rendered before it (the stills and the turntable) were counted under an `other` label, which on SwiftShader showed up as a p95 of 70 s. `collectGPU()` now keeps only the passes labelled while live.
- **The favicon 404, fixed** (see the gate).
- **The live hero portrait's eyes bind 18 sampled textures. Open.**
  - The 18 are 13 textures for the material, the LUTs and the AO, plus 5 PCSS depth maps (key, wrap, rim, kicker, fill).
  - WebGPU's default per-stage limit is 16. The viewer now requests the adapter's limit (capped at 48), records it, and warns on the HUD when the limit is 16 (`air-session.md` step 3).
  - SwiftShader offers 16, so the live hero portrait cannot compile its eye pipeline here: 288 console errors in 30 min, and the save never answered.
  - In the device capture the same eye pipeline binds 16 (3 depth maps), so the captures are clean.
  - See *What's left*.

## What's left

- **The Air session itself** (`air-session.md`). It is the only source of real numbers; nothing in this report measures the Air.
- **The live hero portrait on a 16-texture adapter.**
  - Symptom on SwiftShader: creating `renderPipeline_eyes_hq_58` fails with `The number of sampled textures (18) in the Fragment stage exceeds the maximum per-stage limit (16)`. After that, every frame raises invalid-pipeline errors. The page keeps running, but the eyes don't draw and the overlay's save never resolves its timestamps.
  - URL workaround: `&shadows=key,rim,kicker`.
  - On the Air: the viewer requests the adapter's limit, and `adapter.max_sampled_textures_per_stage` in the perf JSON records it.
  - The real fix belongs to the eye material (T18) and the lights (T19). For example, the eye could sample fewer shadow maps (wrap and fill are soft at the eye), or the maps could be packed.
- **Possibly fewer shadow maps on the eyes in the device captures.** The capture's eye pipeline binds 3 depth maps where the live one binds 5, though both use the hero rig's 5 casting lights.
  - The likely cause is that the pipeline was compiled at the capture's first 64² frame under the neutral rig (3 lights) and not rebuilt when the rig changed.
  - If so, the eyes in hero-rig captures miss the wrap and kicker shadows. That is negligible on the eyes, but it is a pipeline-cache question for T19.
  - Not verified, because of the cap on capture runs.
- **Gameplay grounding.** With one shadowed light, the feet lose the hero rig's rim and kicker floor shadows.
  - On the Air, `&tier=gameplay&shadows=key,rim` measures what a second 1024 map costs.
  - The alternatives are a cheap blob or contact shadow under the feet, or a gameplay rig whose key reaches the floor (T25 owns the rig).
  - Not rendered here, because of the cap on capture runs.
- **LOD switches by tier only, not by distance.** The gameplay tier loads only LOD1. A distance switch would need both GLBs resident, which costs memory against the 1.5 GB tab budget.
- **No texture LOD for the gameplay tier.** It still loads LOD0's 4k head maps (halved in KTX2), and `texture_mb_est` is about 300 MB uncompressed for both tiers. The next memory cut is mip-dropped textures in `lod1.ktx2.glb`.
- **T13b's suit LODs.** When they land, they replace this tool's suit rows (`lod1.mjs` TARGETS).
- **T17's `ssss` and `detail` switches** are no-ops until T17 merges (`stats().tier.noop`).
- **`hairocc=1` may read darker** than the deep shadow it replaces (T20's note on its baked occlusion). At 3 m it is not visible in the side-by-side.
- **The closeup pair mixes texture compression with the tier.** `hero_closeup_hero.png` used the PNG asset (it ran before the KTX2 query was added), while the gameplay-tier frames and `hero2_` used KTX2.
