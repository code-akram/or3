# m1 v4 track T16: engine AA / post architecture

_SwiftShader only: every engine frame here comes from headless Chromium running WebGPU on the CPU (port 8796, CPUs 0-3, a shared machine). Frame times are informational. Spec: `checkpoint-3.md` §2.6, §3, the T16 row of §4 and §5. Public build only._

**The 100 % head crop** is `data/build/t16/gate/portrait_head_t10_t16_cycles.png`: 540 × 540 at (766, 74) of the 1920 × 1080 hero portrait. The panels are:
1. T10 engine beauty (MSAA, analytic grade).
2. T16 engine beauty (TRAA + hashed hair, thin-lens DoF, grade LUT, set bounce).
3. Cycles `refs.py --mode dof` (f/2, 7 blades, 512 spp, the same crop).

**What I see in my own frame (panel 2):**
1. T10's aliasing is gone (the stair-stepped crown cards, the pixel-crawl on the side locks, the blocky brows, which now read soft and dense like Cycles'), but TRAA alone is softer than 4× MSAA on the forehead's specular breakup and on the beard, and the ~1 px DoF on the cheeks softens them further.
2. The DoF itself reads like Cycles' (ear, far hair and far beard edge soft; eyes sharp), but the side locks still look like smeared cards rather than strands.
3. The LUT pulls the skin toward Cycles' tone (less orange, lower mid-tones), yet it stays warmer than Cycles' pale grey-pink with a darker shadow-side cheek (the engine's eye light lights only the eyes, §3) and hair without Cycles' blue kicker sheen.

Frames:
- `gate_b2/t16b_portrait_beauty.png`: TRAA, DoF, LUT and bounce.
- `t16b_portrait.png`: TRAA without DoF.
- `t16m_portrait_beauty.png`: MSAA + LUT, no DoF.
- `t16b_closeup_hero.png`: the hero closeup.

**Branch:** `worktree-agent-a3d8b0b2d87cd2bf6`. Main was merged in at `b2f4685` (hero.sh fix, T22, T13 phase A, T15).

**Gate asset:** T10's b2 KTX2 (`data/build/t10/gate_b2/character.ktx2.glb`, symlinked). The engine runs live in `data/build/t16/gate_b2/`. That is the same asset as T10's numbers, so every before/after below is like for like.

**Cycles references (new, `blender/hero/refs.py`):** all in `data/build/t16/refs/`.
- `chart/`: the grey chart under the hero rig.
- `chart_{key,wrap,fill,eye,rim_kicker}/`: the same chart one light at a time (`--lights`, new).
- `dof/`: the portrait crop around the ear, f/2 on and off.
- `bounce/`: the alley set without the character.
- `probe/`: the hair_test parity set.

## Gate

| Gate item | Target | Result |
|---|---|---|
| T10's 2 s turntable (hero closeup, 24 fps, 640 px, 20°/s): temporal noise, mean \|L(t−1) − 2L(t) + L(t+1)\| (0–255) | < 6.08 (T10), no shimmer on hair at 100 % | **3.47** with TRAA + hash (−43 %). The hair box drops 11.86 → 6.77. ✓ |
| Hair / Cycles per light, TRAA + hash | 0.8–1.2 | key **0.991**, fill **1.166**, rim **0.984** ✓ |
| Portrait crown-box / back-box, TRAA + hash | within 20 % of Cycles (3.281) | **3.139 (×0.96)** ✓ |
| Bokeh radius at the ear, engine vs Cycles (same disc fit, same ROI) | within 15 % | helix **3.04 vs 2.87 px (+6.0 %)**, whole ear **2.89 vs 2.71 px (+6.5 %)** ✓ |
| Grey chart after the grade, 18 / 50 / 90 % patches | ±3/255 per channel | **Grade: ✓.** Each renderer's own linear frame through the LUT matches its own graded frame to 0.11/255 (engine) and 0.53/255 (Cycles). **Full chart: ✗.** R is within 0.7/255, but G is −2.3 to −4.4 and B is −7.6 to −11.4. The cause is lighting, not the grade: the engine's eye light does not reach anything but the eyes (below). |

**Gate pictures** (`data/build/t16/gate/`):

| File | What it shows |
|---|---|
| `portrait_head_t10_t16_cycles.png` | The 100 % head triptych above. |
| `turntable_shimmer_msaa_traa0_traa1.png` | Turntable middle frame over its per-pixel temporal-noise map (×4): MSAA \| TRAA coverage 0 \| TRAA coverage 1. |
| `hair_closeup_msaa_hash0_hash1.png` | Parity closeup (Standard view, neutral studio): MSAA \| hash coverage 0 \| hash coverage 1. |
| `dof_ear_engine_vs_cycles.png` | Ear at 2×: engine sharp \| engine DoF \| Cycles sharp \| Cycles DoF. |
| `chart_sheet.png` | The chart row and its numbers, including the grade-only line. |

## 1. TRAA, hashed hair, velocity, TAAU

### How it works

**Output modes** (`web/src/character/output.ts`, `temporal.ts`):
- **`?aa=traa`** is the default. The temporal path renders the scene single-sample into an MRT target: `output` (half float), `velocity`, `hair`, plus any `addMRT()`, with a float depth texture.
- The camera gets a Halton(2,3) sub-pixel jitter as a view offset. It is applied on top of the stage's lens-shift view offset. The velocity node keeps the unjittered projection.
- **`?aa=msaa`** is the T10 path (4× MSAA, alpha-to-coverage cards), kept for parity stills.
- **`?aa=taau&scale=0.75`** renders at 0.75 of the output and resolves with three's TAAU (`SizedTAAU`).
- **Stills accumulate `aa.stillFrames` (24) frames.** Shadow maps and GTAO are frozen after the first frame of a still.

**The node frame.** three advances the node frame only from its own animation loop, so `Output.render` advances it itself, once per render. Without that, velocity, TRAA and shadows all saw "the same frame".

**HairTRAA** (subclass of r186 `TRAANode`):
- **Hair mask.** It reads a 3×3-dilated 'hair' attachment, which the hair materials write as 1 through `material.mrtNode`.
- **On hair pixels:**
  - no depth-disocclusion reset (hashed cards break the depth test);
  - a current-frame weight floor of `aa.hairMinWeight`;
  - a variance-clip gamma of `hairGamma` 1.25 when still, falling to `hairGammaMoving` 0.75 over `hairMotionPx` 1 px/frame of screen motion. This is the anti-ghosting clamp: a moving strand clips hard, a still one keeps its history.
- **Off hair:** the stock resolve (variance clip, flicker reduction, subpixel correction ×0.25).

**Velocity for skinned and morphed meshes:**
- **Skinning** keeps its previous bone matrices only when the MRT has 'velocity', which it does.
- **Morph targets** broke `positionPrevious`. `patchMorphVelocity()` copies the morphed position into it.
- **Stills read zero velocity** (checked with `?aaview=velocity`).

**Hashed alpha** (`HairMaterial.setupHashedAlpha`, the only hair change in `materials/index.ts`):
- **Coverage.** The card coverage is `mix(edge, a, aa.hairCoverage)`, where `edge` is three's A2C edge. Each pixel tests it against interleaved gradient noise rotated by the frame index.
- **Shadows unchanged.** The shadow pass keeps T10's binary alpha test (`maskShadowNode = true`).
- **A bug I hit.** three's A2C edge is `smoothstep(at, at + fwidth(a), a)`. Inside a card the map alpha is flat, so fwidth is 0 and that smoothstep is undefined. SwiftShader returned 0 there, so whole card interiors failed the hash in every frame. That showed as background-coloured holes down the crown, through the depth-prepass twins. The fix floors the width (`(a − at) / max(fwidth(a), 1e-4)`). The MSAA path still uses three's own A2C formula and did not show it.

**`aa.hairCoverage` = 1 (the map alpha) is the new default.** The A2C step (0) was the parity-preserving option. Both pass the gate; 1 is closer to Cycles everywhere it differs and shimmers less:

| | MSAA (T10 path, LUT grade) | TRAA, coverage 0 (A2C step) | **TRAA, coverage 1 (default)** | Cycles |
|---|---|---|---|---|
| Hair / Cycles: key / fill / rim | 1.015 / 1.149 / 1.082 | 0.992 / 1.133 / 1.034 | **0.991 / 1.166 / 0.984** | 1 |
| Portrait crown/back (×Cycles) | 3.169 (×0.97) | 3.137 (×0.96) | **3.139 (×0.96)** | 3.281 |
| Closeup region / Cycles: hair, beard, brows | 1.078, 0.906, 0.801 | 1.039, 0.895, **0.778** | **1.000, 0.940, 1.074** | 1 |
| Portrait boxes / forehead: crown, top-back, back, front-side, lengths | .075 .040 .024 .164 .037 | .073 .039 .023 .159 .032 | **.072 .038 .023 .166 .030** | .084 .087 .026 .174 .025 |
| Turntable temporal noise (frame / hair box) | 6.08 / 11.86 | 3.63 / 7.07 | **3.47 / 6.77** | — |

- **The MSAA column on this branch reproduces T10's closeup numbers to the third decimal** (1.015 / 1.149 / 1.082 and 1.078 / 0.906 / 0.801). Only the portrait crown/back moves (3.056 → 3.169), and that comes from the LUT grade.
- The turntables use `lut=0`, so they are like for like with T10's analytic-grade turntable. My rerun of that turntable reproduced T10's 6.0764 exactly.

**New baseline for hair tuning (T20 and anyone after).** Use the "TRAA, coverage 1" column: `?aa=traa` default, `view_transform=standard&post=0`, 24-frame stills.
- JSONs: `data/build/t16/gate_b2/hp_ph1.json`. The coverage-0 and MSAA columns are `hp_ph0.json` and `hp_pm.json`.
- Frames: `ph1_closeup.png`, `ph1_{key,fill,rim}_closeup.png`, `ph1p_portrait.png`.
- Recipe: `lookdev_report.py hairparity data/build/t16/gate_b2 --engine ph1_closeup.png --lights key,fill,rim --pattern 'ph1_{light}_closeup.png' --portrait ph1p_portrait.png --cycles-portrait data/build/hero/20261014T190712Z-t10-parity-b2/exr/portrait.exr`. `gate_b2/hair_test` links to T10's parity EXRs.
- **Brows: T10's 0.80 edge is gone (1.07).** Fractional coverage puts back the brow density that the A2C step cut. The brows are now T11's / T20's to tune, not an AA artefact.
- **Coverage 1 has one cost.** Where a prepass twin has written depth (map alpha > 0.85), the card is still discarded on up to 15 % of frames, and the scalp behind it is occluded. The dense core loses a little: crown box .0734 → .0722.

**TAAU** (`?aa=taau&scale=0.75`): runs, and the hero closeup at 512 is clean (`gate_b2/taau_closeup_hero.png`). It was not gated. Its render scale is `aa.scale`, or `?scale=` at load.

**Turntable pictures.**
- `gate/turntable_shimmer_msaa_traa0_traa1.png`: the middle frame over the per-pixel noise map (×4) for MSAA | TRAA cov 0 | TRAA cov 1.
- Videos: `gate_b2/base_turntable.mp4` (MSAA) and `gate_b2/tt1_turntable.mp4` (TRAA cov 1).
- **How the metric was rendered.** TRAA renders at 48 Hz with every second frame written, after a 24-frame warm-up (`engine_shots.mjs --tt-hz 48 --tt-warmup 24`). Because of that, the metric measures what a 48 Hz game would show at 24 fps capture.
- **What the map shows.** It is still dominated by the rotation itself: horizontal streaks on every edge. The hair-specific sparkle that MSAA shows on the crown and the side mass is what dropped.

## 2. Thin-lens DoF (`dof.ts`)

**How it works:**
- **CoC.** `ThinLensDoF` subclasses r186 `DepthOfFieldNode`. The CoC is the thin lens of the stage camera (`engine_stage.json` fstop, focus_m, lens_mm, sensor_mm, sensor_fit): `r = radiusScale · ½ (f²/N) |z − S| / (z (S − f)) / sensor_h · H`.
- **Far field.** A scatter-as-gather: a tap counts only if its own CoC reaches the pixel. The gather radius is the smallest far CoC in front of the pixel, so the 3 px ear does not take the void's 60 px radius.
- **Near field** is stock.
- **Composite** fades between CoC 0.5 and 1.5 px.
- **When it runs:** beauty only, on the resolved frame (the built-in 'resolved' pass). `?dof=0` turns it off. `?dof=only` turns on the DoF without bloom or grain, for the fit. `?dofview=coc_near|coc_far|near|far|input` shows the intermediates.

**A bug in my first version:** the DoF was rendered through `getTextureNode()`. That is a plain texture node, unlike TRAA's pass texture, so it never pulled the node's `updateBefore`, and the frame came out black. The trigger now renders the node itself.

**Bokeh fit** (`lookdev_report.py bokeh`, a disc fit on the sRGB-decoded ROI, the same tool and ROIs as the Cycles fit):

| ROI (full frame) | Cycles | Engine, radiusScale 1 | **Engine, 0.835 (default)** | Thin-lens prediction |
|---|---|---|---|---|
| Helix [1294, 364, 60, 120] | 2.865 px | 3.446 (+20.3 %) | **3.037 (+6.0 %)** | 3.387 |
| Whole ear [1244, 364, 110, 150] | 2.714 px | 3.244 (+19.5 %) | **2.891 (+6.5 %)** | — |

- **The engine follows the formula; Cycles comes in at ~0.85 of it.** The engine at scale 1 is within 2 % of the formula, while Cycles' f/2 7-blade blur measures 0.85 of the same formula.
- **Cause: probably the aperture shape, but unproven.** A 7-blade polygon has ~0.93 of the circle's radius at equal area, and the disc fit sees the polygon. I did not prove where the rest comes from.
- **So `dof.radiusScale` 0.835 is a match to Cycles' measurement, not to the formula.** The +6 % that remains is the half-res gather plus the composite fade (the radius does not scale linearly). One more step to ~0.79 would close it; 6 % is inside the gate.

**Picture:** `gate/dof_ear_engine_vs_cycles.png`. Panels: engine sharp | engine DoF | Cycles sharp | Cycles DoF, at 2× nearest.
- The Cycles DoF also dissolves the thin flyaways over the ear. The engine has no such strands.
- The engine keeps a ~1–2 px sharp band of void next to a blurred mid-ground edge. This is the documented cost of the scatter-as-gather; it is invisible on the black world.

## 3. Grade as data (`grade.py --lut`, `grade.ts`)

**The LUT export.**
- `blender/hero/grade.py --lut OUT.json` pushes a 33³ lattice through Blender's own compositor grade and view transform, and stores:
  - the grade: log2 shaper in, log2 out, range (−12, 5);
  - the view: AgX + "AgX - Base Contrast" + sRGB, display out, range (−13, 5);
  - the compositor vignette as a 96 × 54 gain map.
- `bench/m1/engine_shots.sh` now bakes it into every run (`RUN/grade_lut.json`).
- **Verified against Blender's own output** (`--lut-verify`, `data/build/t16/lut/grade_lut_verify.json`):

  | Input set | max | p99 | worst case |
  |---|---|---|---|
  | Grey ramp | 0.68/255 | — | — |
  | 18 / 50 / 90 % greys | 0.51/255 | — | — |
  | Random colours | — | 1.4/255 | 10/255, on hyper-saturated inputs only |

  The half-float copy the engine uploads changes nothing.

**In the viewer** (Lut3DNode):
- Order: bloom/halation → grade LUT → vignette map → grain → 2^EV → view LUT.
- `?lut=0` is the old analytic path (CDL + three's AgX).
- The engine applies the LUT to **0.11/255** of the same LUT on the CPU (the chart's grade-only check).

**Grey chart** (`refs.py --mode chart`): 18 / 50 / 90 % patches and an 18 % ball, under the portrait's hero rig, at the portrait camera.
- **Command:** `lookdev_report.py chart --chart … --engine lut_chart.png --engine2 ana_chart.png --lut grade_lut.json --engine-linear lut_chart_linear.npy`.
- **Outputs:** `data/build/t16/chart/chart_report.json` and `gate/chart_sheet.png`.
- **New grade-only row.** The new `--lut` / `--engine-linear` options add a "grade only" row: each renderer's own scene-linear chart through the LUT on the CPU, against its own graded frame. That separates the grade from the lighting.

| Patch (Cycles RGB) | Engine LUT − Cycles | Pre-LUT analytic − Cycles | Grade only: engine / Cycles frame − own LUT |
|---|---|---|---|
| 18 % (89.6, 74.9, 69.0) | −0.1, −2.3, −7.6 | +9.3, +9.7, −0.8 | ≤ 0.03 / ≤ 0.46 |
| 50 % (145.4, 128.3, 121.0) | −0.7, −4.4, −11.4 | +1.5, +3.3, −7.3 | ≤ 0.11 / ≤ 0.53 |
| 90 % (171.9, 157.5, 152.0) | −0.2, −4.1, −10.4 | −0.0, −0.1, −11.4 | ≤ 0.10 / ≤ 0.35 |

**Why the full chart misses: the per-light decomposition.** These are scene-linear means on the 18 % patch, engine vs the new per-light Cycles charts:

| Light | Engine | Cycles | Engine / Cycles |
|---|---|---|---|
| key | .1686 .0819 .0267 | .1680 .0805 .0262 | 1.00 / 1.02 / 1.02 |
| fill | .0046 .0057 .0081 | .0037 .0046 .0066 | 1.24 |
| wrap (+ rim, kicker) | ≈ .065 .031 .0094 (total − key − fill) | .0560 .0272 .0096 | ≈ 1.16 |
| **eye** | **0** | **.0149 .0141 .0149** | **missing** |

- **The eye light is the cause.** The engine links the eye light to the eye materials only (`stage.ts` `link()`: "the eye light is a catchlight"). In Cycles it lights everything, with `diffuse_factor` 0.3. On the character (alley set) it lights the whole character through the receivers collection.
- **The check.** Adding Cycles' eye term to the engine's linear chart brings every patch to **+2.2 … +4.1/255** of Cycles. What remains is the wrap and fill running ~20 % hot.
- **So this is a lighting gap, and it is not only on the chart.** The engine face is also missing a frontal neutral light at ~6 % of the key in diffuse. That is `stage.ts`, which is T19's file. I did not touch it.
- **The analytic path** (pre-LUT) is +9/255 on the 18 % patch in R and G. That is three's AgX against Blender's AgX + Base Contrast look. The LUT removes it.

## 4. Set bounce (`refs.py --mode bounce`, `bounce.ts`)

**The capture.** Cycles renders the alley set with the character hidden, from the head position: six 32² cube faces, resampled to a 128 × 64 equirect in three's axes (`set_bounce.json`, scene-linear radiance).

**In the viewer.** It is the `envMap` of the character's materials, at `bounce.gain` 1, in the hero beauty frame only. There, the world hemisphere light is switched off, because the cube already holds the world.

**Measured ratio.** Irradiance facing the camera is 0.127 against a key of 3.0, i.e. **0.042 of the key, about twice the spec's ~0.02**.
- I kept gain 1, because this is Cycles' own radiance for that set: the Cycles alley beauty includes it.
- Set `bounce.gain` 0.5 if the ~0.02 is meant as an art target rather than a guess.

**A fix during the run.** Setting it as `scene.environment` also lit the stage floor (roughness 0.45), which showed as a teal plane behind the head. It is per-material now.

## 5. The pass hook (for T17 and T19)

The header comment of `output.ts` is the contract. In short:

```ts
output.addPass({
  name: 'ssss',                       // unique; re-adding replaces
  stage: 'pre' | 'scene' | 'resolved',
  order?: number,                     // ascending within a stage, default 0
  enabled?: boolean,
  setup?(ctx: FrameContext): void,    // once, before the first render
  render(ctx: FrameContext): THREE.Texture | void,  // 'scene' / 'resolved': return a half-float RGBA
                                                    // texture to replace ctx.color; 'pre': ignored
  dispose?(): void,
});
output.removePass('ssss');
output.addMRT('skin', float(0));      // temporal modes: an extra attachment of the scene target;
                                      // a material writes it with material.mrtNode = mrt({ skin: float(1) })
output.passList;                      // readonly OutputPass[]
```

**`FrameContext`:**
- `renderer`, `scene`;
- `camera`: jittered during 'pre' and 'scene';
- `width` / `height` (render resolution) and `outWidth` / `outHeight`;
- `color`: scene-linear at this point of the frame;
- `depth`: a float `DepthTexture`, null in msaa;
- `velocity`: null in msaa;
- `mrt` (by name), `jitter` (render px), `frame`, `beauty`, `aa`, `still`, `lens` (the DoF lens uniforms).

**Rules for a pass:**
- It renders into its own targets.
- `Output` resets the render target and MRT after each pass.

**The stages:**

| Stage | When | Use |
|---|---|---|
| 'pre' | Before the scene, on the jittered camera | GTAO is the built-in example. T19's contact-shadow / PCSS prepasses go here. |
| 'scene' | Jittered scene-linear frame at render resolution, before the temporal resolve | T17's screen-space SSS goes here, so TRAA cleans its noise. |
| 'resolved' | Output resolution, after TRAA | DoF is the built-in example. |

**Self-test:** `?passcheck=1` (`passcheck.ts`, also the smallest worked example).
- It adds an MRT attachment `probe` (0.5) and a 'scene' pass that multiplies the frame by (1, 2 × probe, 0.5).
- Result: display blue ×0.62 and green ×0.97 against the same frame without it (`gate_b2/pc0_` vs `pc1_closeup_hero.png`). So the pass ran and the MRT attachment was written and read back.
- On the MSAA path, the pass runs and `addMRT` is a no-op, as documented.

## Changed files

- **`web/src/character/`**
  - **Mine:** `output.ts`, `main.ts`, and the new `temporal.ts`, `dof.ts`, `grade.ts`, `bounce.ts`, `passcheck.ts`, `addons.d.ts`.
  - **`materials/index.ts`:** the hair alpha paths only (`setupHashedAlpha`, the A2C/hash switch).
  - **`materials/params.ts`:** new `aa`, `dof` and `bounce` blocks.
- **`blender/hero/`**
  - `grade.py`: `--lut`, `--lut-verify`.
  - `refs.py`: new; the chart, bounce, dof and probe modes, plus chart `--lights`.
- **`bench/m1/`**
  - `lookdev_report.py`: the `chart` row (now with `--lut` / `--engine-linear`, the grade-only check) and `bokeh`.
  - `engine_shots.mjs`: `--chart`, the temporal turntable (`--tt-hz`, `--tt-warmup`), `grade_lut.json` and `set_bounce.json` served.
  - `engine_shots.sh`: bakes `grade_lut.json`; `ENGINE_BOUNCE` copies a bounce sidecar in.
- **Viewer flags:**

  | Flag | Effect |
  |---|---|
  | `?aa=traa\|taau\|msaa` | AA mode (default traa) |
  | `&scale=` | TAAU render scale |
  | `&dof=0\|only` | DoF off, or DoF without the other post |
  | `&dofview=` | Show a DoF intermediate |
  | `&lut=0` | Analytic grade instead of the LUT |
  | `&bounce=0` | No set bounce |
  | `&aaview=raw\|velocity\|hair` | Show a temporal buffer |
  | `&scene=chart` | Grey chart scene (with `lights=`, `fillshadow=`) |
  | `&passcheck=1` | Pass-hook self-test |

## Left / notes

- **The eye light is linked to the eyes only in the engine.** It is the chart's G/B miss, and probably part of the face's look against Cycles. `stage.ts` `link()` should give it every character material at diffuse 0.3 (and the chart). The wrap and fill run ~20 % hot on a camera-facing plane. Both are for T19.
- **TRAA softness.** TRAA stills are softer than 4× MSAA on skin specular breakup and beard texture (`t16m_portrait_beauty.png` vs `t16b_portrait.png`). The usual fix is a contrast-adaptive sharpen as a built-in 'resolved' pass. Not done.
- **DoF residual and soft cheeks.** The DoF is +6 % over Cycles at the ear; `radiusScale` ~0.79 would close it. The composite starts fading toward the half-res gather at a CoC of 0.5 px, so ~1 px CoCs (the cheeks) pick up the half-res resampling blur on top of their own. A full-res gather (`dof.fullRes` 1) or a later fade start would keep them crisper.
- **TAAU is not gated.** It was smoke-tested only; its quality and time belong to T24 (Air).
- **Frame cost.** Every frame time here is SwiftShader on a shared CPU, so nothing about the Air is known.
  - TRAA is cheaper per frame than 4× MSAA here, but a still needs 24 frames.
  - The 1024² closeup takes 142–198 s (24 frames) against 22 s (one MSAA frame).
  - Turntable capture calls average 8.2–11.3 s, against 13.7 s for MSAA.
- **Ghosting.** I checked it only by eye on turntable frames 24 and 47, against MSAA's. I saw no lag trails on the locks at 20°/s, but the moving locks are softer and their edges a little stepped. There is no lag metric.
- **Bounce gain.** It is 2× the spec's ~0.02 by design (above).
