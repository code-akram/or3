_SwiftShader only: every engine frame and timing here is WebGPU in headless Chromium on the CPU (port 8796, CPUs 0-3, a shared machine at load 20-28). Track T19 (lighting), m1 v4, 2026-10-15. Brief: `checkpoint-3.md` §2.5, §3.1 item 4 and the T19 row of §4. Public build only. ArcFace was not run (its models are under `private/`); the run dirs are listed at the end._

# m1 v4 track T19: lighting

## The pictures (`data/build/t19/gate/`)

**`portrait_head_t16_t19_cycles.png`**: the hero portrait head at 100 % (540 × 540 at (766, 74) of the 1920 × 1080 frame). Panels: T16 engine (`t16/gate_b2/t16b_portrait.png`) | T19 engine (`t19/gate_b2/t19d_portrait.png`) | Cycles `--parity` (`hero/20261014T190712Z-t10-parity-b2`). Same asset (t12-b2) in both engine panels, so only the lighting differs.

**What I see in my own frame at 100 %** (three sentences):
1. The face has lost T16's orange cast: with the eye light now lighting the whole face and the fill no longer 24 % hot, the forehead and the shadow cheek take Cycles' neutral-pink values (shadow cheek 91, 59, 61 against Cycles 92, 57, 58 and T16's 86, 52, 51), and the cyan kicker now reads on the temple hair edge as in Cycles.
2. It is still not Cycles: the eye sockets and the under-eye bags stay much darker (under-eye 92 against 118; unchanged from T16, it is GTAO + the key's shadow in the socket, not the light model), the temple behind the hair is half Cycles' brightness, and the engine skin has no SSS bleed into the shadow side.
3. The contact shadows are a subtle, correct-looking darkening where the brief asked (collar on neck, lower lip on the chin, the upper lid on the globe, the nose side), but they show the half-resolution prepass as a stepped edge in single frames, which TRAA smooths in the stills and the turntable, and they leave a 1 px dark line on the lit forehead silhouette.

Other pictures:
- `closeup_hero_t16_t19.png`: the hero `closeup:hero` (1024², 100 %), T16 | T19.
- `contact_jaw_collar_off_on_diff_x2.png`, `contact_eyes_nose_off_on_diff_x3.png`: the T19 closeup with `?contact=0` (`c0off_`) | with contact (`t19c_`, the same build) | the difference ×8. The contact term is visible on the collar against the neck, the neck under the beard line, the lower lip on the chin, the lapel on the shirt, the upper lid on the far eye's globe, the lower-lid crease and the nose side.
- `chart_sheet.png`: the graded grey chart, Cycles | T19 | T16, with the numbers.

## Before → after

| Measure | Target | T16 (before) | **T19 (after)** |
|---|---|---|---|
| Grey chart after the grade, 18 / 50 / 90 % patches, max \|d\| | ±3/255 per channel | −0.7, **−4.4, −11.4** ✗ | **−1.14, −0.24, +0.12** (max 1.14/255) ✓ |
| Grey chart, 18 % ball samples (reported, not gated) | — | up to −10.3 (B) | max −2.84 (R, terminator) |
| Per-light chart, 18 % patch luminance, engine / Cycles: key / wrap / fill / eye | each 1 ± small | 1.00 / ≈1.16 / 1.24 / **0 (missing)** | **0.996 / 1.005 / 1.041 / 1.019** |
| Shader balls per light, ±10 % (direct-only Cycles, net of the world; see below) | ±10 % | not measured per light | key 4 of 6 within (hair 1.27, eye 1.19 out); fill 4 of 6 (hair 1.38, eye 1.19); **rim 2 of 6** ✗ |
| Hair / Cycles per light (T16 recipe): key / fill / rim | 0.8–1.2 | 0.991 / 1.166 / 0.984 | **0.986 / 1.077 / 0.961** ✓ |
| Portrait crown / back vs Cycles (3.281) | within 20 % | ×0.957 | ×0.967 ✓ |
| Shadow maps: hero rig / neutral rig | ≤ 5 | 10 / 6 | **5 / 3** ✓ |
| Turntable temporal noise (T16 recipe: TRAA 48 Hz, warm-up 24, `lut=0`, 640 px, 2 s) | ≤ 3.47 | 3.47 | **3.387** ✓ |
| Skin boxes on the portrait head, sRGB, engine vs Cycles: shadow cheek | (info) | 86, 52, 51 vs 92, 57, 58 | **91, 59, 61** |
| forehead | (info) | 175, 123, 94 vs 176, 125, 101 | **175, 127, 102** |
| lit cheek | (info) | 167, 109, 83 vs 170, 114, 91 | **163, 109, 87** |
| under-eye (lit side) | (info) | 94, 54, 40 vs 118, 66, 49 | 92, 55, 43 ✗ (not a light-model term) |
| Eye, sclera / iris luminance (far eye; my re-implementation of T18's measure on the T18-b2 asset, see §6) | Cycles 7.36 here (T18's script: 16.6) | 4.89 (T18 final, `t18-b2` engine; T18's script: 11.24) | **4.97** (×1.02, ≈11.4 on T18's scale) |
| Eye catchlight share of the iris disc | Cycles 0.0107 here (T18: 0.0125) | 0.0053 (T18: 0.0063) | **0.0053** (unchanged) |
| Per-pass GPU ms | recorded | — | see "Frame cost" |

## 1. The grey chart: root cause and fix

T16 left the chart at −4/255 in G and −11/255 in B and named two causes: the engine's eye light lit only the eyes, and the wrap and fill ran ~16 % and ~24 % hot. I split it one light at a time against T16's per-light Cycles charts (`t16/refs/chart_*`), scene-linear on the patches:

| Engine change (cumulative) | key | wrap | fill | eye |
|---|---|---|---|---|
| T16 | 1.00–1.02 | ≈1.16 | 1.24 | 0 |
| + eye light on every material (`light.eyeAll`) at full diffuse | | | | 1.02 |
| + hybrid LTC, rect diffuse from the vector form factor (T19 `rectAsPoint`) | 1.008 | 1.034 | 1.145 | 1.019 |
| + **exact horizon-clipped form factor** in three's LTC diffuse | **0.996** | **1.005** | **1.041** | 1.019 |

- **The eye light.** Cycles ignores the light's `diffuse_factor` 0.3; Blender's per-light diffuse / specular factors are EEVEE settings. The engine eye light at full diffuse is 1.02× Cycles' eye-only chart, and my analytic integral of the eye rect over the 18 % patch predicts Cycles to 2 %. So `light.eyeAll` gives the eye light to every material at full diffuse. On request from the orchestrator, the eye material's `eye.eyeLightDiffuse` is now 1 (the eye's diffuse goes through its `direct()` under the rects too, §6). `rig.py` notes that `EYE_DIFFUSE` is EEVEE-only.
- **The fill / wrap excess was three's LTC horizon-clip fit, not the export.** For the diffuse, three's `LTC_Evaluate` (identity matrix) turns the rect's vector form factor F into a horizon-clipped form factor with `(|F|² + F·n) / (|F| + 1)` (LTC.js, "a Journey", p.102). That equals F·n only for a light at the zenith. I integrated each light over the chart patch numerically (`/tmp/t19/ff.py`, the export's positions, quaternions, sizes, powers; L = P / (π w h)), and the fit over the exact value is 1.114 for the fill (2 m square at 2.5 m, 57° off the patch normal), 1.030 for the wrap and 1.012 for the key: exactly the measured residuals. `withSharedLighting` (lighting.ts) now rescales three's LTC diffuse by exact / fit, where exact is Snyder's clipped-sphere form factor (Frostbite's `illuminanceSphereOrDisk` / π; F·n whenever the equivalent cap is above the horizon). Tested against brute-force integration of rects from 0° to 95° (`/tmp/t19/fftest.py`): exact to 3 decimals above the horizon, within 2–5 % when clipped, where the fit is up to 2× off.
- **The world.** The engine's hemisphere world (0.003) gives the same 0.00054 on the 18 % patch as Cycles' world (the rim + kicker chart, which sees no rim), so it needed nothing.
- The remaining +4 % on the fill: my analytic integral puts Cycles' fill 5 % *under* the exact irradiance, and the engine at +1 % over it. I did not chase it (it is 0.2/255 on the graded chart).
- The skin and hair models take the rect as a point equivalent from the same F (`rectAsPoint`: direction F/|F|, intensity π L |F|). That is exact above the horizon but not horizon-clipped; making it clipped means changing the skin and hair class call sites (T17, T20), so I left it.

## 2. Shadows: hybrid LTC + PCSS, one map per light

- **Hybrid LTC.** Every studio / hero light, including the eye light and the hair twins, is a three `RectAreaLight` of its Blender size (`?area=all` is the default). The specular is the area-shaped LTC lobe (a strip highlight from the rims on the wet eyes and skin), the diffuse is the exact form factor (above). three's rect lights cast no shadow, so each rect carries the shadow of an invisible spot proxy at the same place, through `light.shadow.shadowNode`. `?ltc=0` keeps T10's shadowed spots.
- **One map per light.** A light's twins (`_hair`, `_props`, `_beard`, ...) read their parent's depth map through `LinkedShadowNode`: the same shadow camera and matrix, the parent's render target, no render of their own, and their own filter (T10's deep hair filter for the hair twins). The hero rig goes from 10 maps to **5** (key, wrap, rim, kicker, fill); the neutral rig from 6 to **3**. The proxy fits its frustum to a sphere around the frame (`fitShadow`), so a 2048 map spans ~1.2 m on the hero portrait (0.6 mm texels), as fine as T10's head-only twin maps.
- **PCSS** (`pcssFilter`) on every parent: a 12-tap blocker search over the region a blocker up to 15 cm above the receiver could shadow it from, the penumbra from the emitter's equal-area disc and the mean blocker distance, then a 16-tap PCF of that radius on the hardware comparison sampler. The Vogel taps rotate per pixel and per frame (IGN), so TRAA integrates them.
- **Receiver-plane bias and a grazing normal offset.** The rim on the shader balls showed the classic convex-terminator problem: a sphere's crescent lit by a grazing light reads its own bulk in the map through the PCSS kernel. The depth bias now grows with tan(N, L) over the filter radius (capped at 2 cm), and the lookup moves out along the normal by 2 texels × tan(N, L) (`grazingOffset`, not on the hair twins). The wool ball's rim went 0.46 → 0.67 of Cycles, which is the same as with the rim's shadow off (0.71).
- **A WGSL trap, for whoever writes the next filter.** All texture nodes of one texture share a binding, and the first node generated decides the sampler type. If a filter `textureLoad`s a depth map before it compares, the comparison sampler is missing and `textureSampleCompare` fails to compile. `depthLoad()` marks the load nodes as comparison-sampled. T10's deep hair filter uses it now.

## 3. Contact shadows (`contact.ts`)

A `'pre'` pass through `Output.addPass` (order 10, after GTAO). It runs on the GTAO prepass depth and normals at half resolution, with this frame's jittered camera. Each pixel marches 10 quadratically spaced steps over 2.5 cm toward a random point of the key's rect, using a new point every frame. A step is occluded when the depth buffer's surface is in front of it by more than a pixel footprint and less than 1.2 cm. The pixel footprint grows at grazing view, so the half-res silhouette does not shadow itself. The ray fades over its last 40 %. The key's shadow node multiplies by the result, so the term darkens the key's diffuse and specular on every material except the hair: the hair's key twin keeps the deep hair shadow.

## 4. Specular occlusion

Lagarde & de Rousiers' `saturate((N·V + ao)^exp2(−16 r − 1) − 1 + ao)` from the GTAO term. It multiplies each material's indirect specular (the set bounce). It also multiplies each light's direct specular, weighted like T10's direct-diffuse AO (the light's size over its distance). It applies on every model except the hair cards, which keep their strand occlusion. It wraps the lighting model the material builds (`withSharedLighting`), so no material class changed.

## 5. Shader balls per light

`lookdev_render.py --shader-balls --ball-lights key` (new) renders the balls under one studio light. `--ball-direct` (new) renders without diffuse and glossy bounces, which is the engine's model: Cycles' balls otherwise include the light off the floor, both as bounce and as reflection. I took every frame net of the world, subtracting a `--ball-lights none` frame. The ratio is the mean scene-linear luminance in 0.85 of the ball radius (rim: the whole disc), engine / Cycles, run dir `data/build/t19/balls`, engine prefix `e6_` (final build):

| Ball | key | fill | rim (whole disc) |
|---|---|---|---|
| skin_head | 0.944 | 0.920 | **0.40** |
| suit_wool | 1.019 | 1.037 | **0.67** |
| suit_silk | 1.058 | 1.091 | **2.20** |
| suit_leather | 1.036 | 1.043 | 0.946 |
| hair_cards | **1.268** | **1.375** | **0.32** |
| eyes_hq | **1.188** | **1.185** | 1.010 |

- **Key and fill.** Everything is within 10 % except the hair-cards ball (+27 %, +38 %) and the eye ball (+19 %). Against Cycles with bounces, skin drops to 0.89–0.91: the floor lights the underside of every ball in Cycles.
- **The eye ball.** It was 1.10 while the rect path shaded it with three's LTC Lambert (`e5_`). It is 1.19 since its diffuse goes through T18's own iris model (§6). That is T18's known gap, not the light's: on the head, T18's iris is 37 % brighter than Cycles' (§6). The eye's specular rim is 1.01.
- **The hair-cards ball.** It is the T20 hair model on a sphere with no hair twins and no strand occlusion. The hair on the head is what is gated, and it passes per light: 0.986 / 1.077 / 0.961.
- **The rim misses on the diffuse-like models.** It lands only on a thin crescent at the silhouette (Cycles' rim inside 0.85 r is 1 % of its key). There:
  - skin is 0.40: Cycles' random-walk SSS carries the crescent's light into the ball, and the engine's pre-integrated SSS has no such path (T17);
  - wool is 0.67 and silk 2.2: the cloth sheen / fuzz at grazing (T13's class);
  - hair is 0.32 (T20).
- **Shadows are no longer the rim's problem.** With the grazing offset, the rim's shadow costs under 10 % on any ball (`?noshadow=rim` A/B, `e4_` against `e5_`). I did not tune any material class to close the rim, since those classes belong to T17, T13 and T20.

## 6. The eye under the new lights

- **The bug.** With every light a rect (hybrid LTC), the eye material's rect path (`directRectArea` → three's LTC Lambert on the eyeball normal) would have bypassed T18's iris model, which lives in `direct()`: the refracted iris, the limbus, the sclera wrap. My first T19 portrait on the T18 asset had the far iris 60 % too bright (0.0205 against T18's 0.0129).
- **The fix.** `withSharedLighting` (`rectDiffuseAsPoint`, the eye role) takes the eye's diffuse under a rect from `direct()` at the rect's point equivalent, the same form-factor direction and intensity the skin uses. It keeps the rect's LTC specular and the cornea's LTC catchlight. No eye-shading code changed.
- **`eye.eyeLightDiffuse` is now 1** (the orchestrator's request; Cycles ignores the 0.3).
- **The measure.** T18's metric scripts were scratch, so I re-implemented them from T18's notes (`/tmp/t19/eyemetric.py`): crop to Cycles' `portrait_crop` window, iris annulus 0.6–0.92 × 15.5 px without the upper-lid sector and the brightest 8 %, sclera boxes beside the iris, catchlight ≥ 0.5 × peak and ≥ 2 × iris. On the far eye (the one whose ratios match T18's: engine/Cycles 0.66 here against T18's 0.68):

| Far eye | Cycles (`hero/…t18-b2/portrait_crop.png`) | T18 engine (`lookdev/…t18-b2/game_portrait.png`) | **T19 engine (`t19/eye_b2/game_portrait.png`)** |
|---|---|---|---|
| sclera / iris | 7.36 | 4.89 | **4.97** |
| iris / sclera luminance | 0.0094 / 0.0695 | 0.0129 / 0.0628 | 0.0129 / 0.0639 |
| catchlight share | 0.0107 | 0.0053 | **0.0053** |

- **The verdict: T19 leaves T18's eye as it was.** The eye light at full diffuse lifts the sclera by 2 %, and the catchlight is unchanged. T18's gaps stay open: the iris is 37 % too bright and the sclera 8 % too dark here.
- **Picture:** `gate/portrait_eyes_t18_t19_cycles_x3.png` (T18 | T19 | Cycles, eyes at 3× nearest).

## 7. Frame cost (SwiftShader) and the switches for T24's tiers

**GPU timestamps work on SwiftShader** (`timestamp-query` is exposed), so these are per-pass times from the GPU queries, labelled by render target. They are from `__viewer.profile('closeup', 'hero', 1024, 1024, 6, 2)`: the hero closeup, TRAA, every pass running every frame as in motion, the median of 6 frames, logs in `/tmp/t19/prof/`, JSON in `data/build/t19/gate_b2/profile_closeup_hero.json`. The "GPU" is the shared CPU at load 20–28, so the absolute numbers are SwiftShader's, not a GPU's. The split is the useful part:

| Pass (hero closeup 1024², all T19 features on) | ms (SwiftShader) | share |
|---|---|---|
| scene (MRT: colour, velocity, hair) | 20,497 | 84 % |
| shadow maps, 5 (key 322, wrap 428, rim 310, fill 310, kicker 181) | 1,550 | 6.4 % |
| output (grade + LUT into the readback target) | 911 | 3.7 % |
| GTAO prepass (normals, depth) | 626 | 2.6 % |
| TRAA resolve | 600 | 2.5 % |
| GTAO | 278 | 1.1 % |
| **contact shadows** | **114** | **0.5 %** |
| total | 24,300 | |

Per-feature A/B on the same view (one switch off each; total GPU ms): every feature on 24,300; `contact=0` 20,256; `pcss=0` 19,098; `specocc=0` 17,446; `sharemaps=0` 23,902 (10 maps, 3,528 ms of maps against 1,550); `ltc=0` 19,836; `eyeall=0` 20,661; `aa=msaa` 26,470. **The scene-pass time swings 13–21 s between runs with no change in the shaders**, because the machine is shared, so these totals do not rank the features. Read only the per-pass rows, which are:
- the maps: 5 cost 1.55 s and 10 cost 3.5 s;
- contact: 0.1 s;
- GTAO plus its prepass: 0.9 s.

The scene pass holds the PCSS (12 blocker + 16 PCF taps per shadowed light), the LTC and the specular occlusion, and its share must be measured on a real GPU (the Air) before T24 sets tiers. The per-light PCSS taps are the obvious first knob: `light.pcssTaps` and `light.pcssBlockerTaps`.

Every feature is a `light.*` parameter with a URL switch, read when the scene is built:

| Feature | URL | Param |
|---|---|---|
| hybrid LTC (rects + shadow proxies) | `?ltc=0` | `light.ltc` |
| PCSS (else T10's PCF radius) | `?pcss=0` | `light.pcss`, `pcssTaps` 16, `pcssBlockerTaps` 12 |
| key contact shadows | `?contact=0` | `light.contact`, `contactSteps` 10 |
| specular occlusion | `?specocc=0` | `light.specOcclusion` |
| twins share the parent map | `?sharemaps=0` | `light.shareMaps` |
| eye light on every material | `?eyeall=0` | `light.eyeAll` |
| map size | — | `light.mapSize` 2048 |
| A/B only | `?noshadow=rim,kicker` | — |

`?timestamps=1` turns on `trackTimestamp`, and `__viewer.profile(view, rig, w, h, frames, warmup)` returns per-pass times (`profile.ts`, labelled by render target: each light's shadow map, the GTAO prepass, contact, the scene MRT, the resolve).

## Files

- New:
  - `web/src/character/lighting.ts`: the shadow nodes and PCSS, the exact form factor, specular occlusion and `withSharedLighting`.
  - `contact.ts`.
  - `profile.ts`.
- `stage.ts`:
  - the proxies, shared maps, PCSS and contact hook-up;
  - the eye light on every material;
  - `shadowMapCount`;
  - `?noshadow`.
- `ao.ts`: exposes the prepass depth and projection.
- `hairshadow.ts`: `depthLoad`.
- `materials/index.ts`: shared functions only (`rectAsPoint` via `rectFormFactor`, plus the `withSharedLighting` wrap at material creation), and the eye-light comment.
- `materials/params.ts`: the `light` block, and `eye.eyeLightDiffuse` 1.
- `main.ts`: the switches, the contact pass, the profiler and `__viewer.profile`, plus `?lights` / `?noshadow` on the balls scene.
- `blender/lookdev_render.py`: `--ball-lights`, `--ball-direct`.
- `blender/hero/rig.py`: a comment on `EYE_DIFFUSE`.

## Run dirs

- `data/build/t19/gate_b2`:
  - `t19d_{closeup_hero,portrait,portrait_beauty}.png` (final), `t19c_` (the same before the eye fix, the contact A/B pair);
  - `c0off_` (contact off);
  - `ph19*` (hair parity);
  - `tt19_turntable` (noise);
  - `hp_ph19.json`.
  This is T16's gate_b2 asset (t12-b2) for a lighting-only before/after.
- `data/build/t19/eye_b2`: `game_{closeup_hero,portrait,portrait_beauty}.png` on the T18-b2 asset (current main's character), the eye re-measure. **This is the run dir for ArcFace.**
- `data/build/t19/chart`: `c2_all_chart.png` / `c2_report.json` (final graded chart), `m3_*` (per-light, MSAA).
- `data/build/t19/balls`: Cycles `cycles_balls[_L][_direct].png`, engine `e6_*` (final), `e6_ball_parity_net_direct_r0.85.json` (rim: `_r0.98`); `e4_` (rim unshadowed) and `e5_` (before the eye fix) for the A/Bs.

## Left / notes

- **Build order.** The final chart (`c2_`), hair parity (`ph19*`), turntable (`tt19_`) and profile runs were made one commit before the eye fix (81f2233), which changes only the eye material's rect path. The gate frames (`t19d_`, `eye_b2`) and the balls (`e6_`) are on the final build.

- **The rim shader-ball target is missed** (above): skin SSS, cloth sheen and hair at grazing are T17's, T13's and T20's.
- **The hair-cards ball is +27–38 % under key and fill.** On the head the hair passes per light.
- **`rectAsPoint` is not horizon-clipped.** Skin and hair under a light that straddles the horizon get F·n instead of the clipped form factor. The fix is a one-argument change at the skin and hair call sites (bend the point direction toward the normal by exact / F·n), which belong to T17 and T20.
- **The under-eye and socket are too dark** against Cycles (92 vs 118): GTAO + the key's shadow in the socket. That is not a light-model term; a candidate is a lower `ao.strength` on the skin in the socket, or SSS bleed (T17).
- **Contact shadows show the half-res prepass** as stepped edges in single MSAA frames, and they leave a 1 px line on the lit forehead silhouette. A full-res depth would fix both, at the cost of the pass.
- **The cloth fuzz is rescaled with the LTC diffuse** by the exact / fit factor: `withSharedLighting` cannot separate them in `ClothLightingModel`'s rect path. It is ≤ 1 % except under the fill (−10 %).
- **Frame cost is SwiftShader on a shared CPU.** The per-pass split is real, but the per-feature totals are not stable enough to rank the features. The Air needs measuring before T24 sets tiers.
