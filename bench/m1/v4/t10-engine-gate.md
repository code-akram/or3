# m1 v4 track T10: engine gate completion

_Track T10 report, 2026-10-14. Every engine frame here is SwiftShader (headless Chromium, WebGPU on the CPU); nothing was captured on the Air, so the frame times are informational only. Spec: `checkpoint-2.md` §2 items 1–8, §4 row T10, §5 items 1, 3 and 5. Public build only (`bench/m1/variants/direction.json`), no fan overlay._

**What I see in my own frames at 100 %** (`gate_b2/game_portrait.png` head crop, `game_closeup_hero.png`):
- The hair mass behind the temple has lost the lilac-silver sheet. It is now dark brown-black with only a thin mauve rim on its back edge, and the back-lengths no longer glow. The crown is now the brightest part of the hair, which is the Cycles distribution. But it is warm mid-brown with pale streaks along the parting, where Cycles has a cool blue kicker sheen. The hairline front locks are still hard, stringy card edges.
- GTAO puts contact darkening where it was missing: in the eye sockets, under the nose, behind the ear and along the hairline. The face sits in its sockets more, but the skin is still more orange and more evenly lit than the Cycles skin.
- T11's beard on the hero closeup is charcoal with the salt on the chin, and the cheek line fades. Under the hero rig it is warm olive-brown and takes none of the cyan kicker rim that Cycles puts on its left edge. The moustache's lower edge is still a fringe of spikes.

**Branch:** `worktree-agent-a17e23dad5f61f565`. Main is merged twice: T11 at `9f3482d`, T12 at `e3f085f`.

**Gate build:** `data/build/lookdev/20261014T184620Z-t12-b2`. This is T12's final build, i.e. current main with T11 and T12. Its KTX2 copy is the gate asset, at `data/build/t10/gate_b2/character.ktx2.glb` (engine runs in `data/build/t10/gate_b2/`).

**Cycles references** for the same build:
- `data/build/hero/20261014T190712Z-t10-parity-b2`: the `--parity` portrait, 1920 × 1080 at 100 %, 64 spp, 80 s.
- `gate_b2/hair_test/parity_cycles{,_key,_fill,_rim}.exr`: the closeup and the per-light closeups (`hair_test.py --parts parity --parity-lights key,fill,rim`).

**Before.** Two baselines:
- **T9b flags.** The same b2 KTX2 asset with the T9b behaviour restored by flags and params: `?hairshadow=0&fillshadow=0&gtao=0` and the T9b hair lobes. This is the like-for-like before.
- **The real T9b b1 frames.** `…/lookdev/20261014T155504Z-t9b-b1/game_portrait.png` is the "before" panel of the triptych.

## Gate pictures (`data/build/t10/gate/`)

| File | What |
|---|---|
| **`portrait_head_before_after_cycles.png`** | Hero portrait head at 100 % (560 × 560 of the 1920 × 1080 frame), all AgX. Panels: T9b b1 engine \| T10 engine (b2, KTX2) \| Cycles `--parity` of b2. |
| `closeup_hero_before_after.png` | The real hero-rig closeup, `game_closeup_hero.png`: T9b flags \| T10. |
| `regression_strip.png` | The new fixed strip, main9 → int1 → latest (b2). Each row shows the Cycles face crop beside the engine portrait cut to the same rectangle. |

The 2 s turntable (24 fps, 640 px, 20°/s, hero rig) is in `gate_b2/game_turntable.mp4`. The T9b-flags turntable is `gate_b2/before_turntable.mp4`.

## Gate metrics (b2, KTX2, Standard view decoded to scene-linear; `lookdev_report.py hairparity`)

| Metric | Target | Before (T9b flags) | **After (T10)** |
|---|---|---|---|
| Hair / Cycles per light: key | 0.8–1.2 | 1.157 | **1.015** ✓ |
| fill | 0.8–1.2 | **1.453** ✗ | **1.149** ✓ |
| rim | 0.8–1.2 | 0.943 | **1.082** ✓ |
| Portrait crown-box / back-box luminance | within 20 % of Cycles (3.281) | 1.287 (×0.39) ✗ | **3.056 (×0.93)** ✓ |
| Portrait boxes / forehead, engine vs Cycles: crown | (info) | 0.132 / 0.084 | 0.076 / 0.084 |
| top-back | (info) | 0.063 / 0.087 | 0.040 / 0.087 |
| back (mass behind the temple) | (info) | 0.102 / 0.026 | 0.025 / 0.026 |
| front-side | (info) | 0.205 / 0.174 | 0.184 / 0.174 |
| lengths | (info) | 0.088 / 0.025 | 0.040 / 0.025 |
| Closeup region / Cycles: hair, beard, brows | 0.8–1.2 | 1.021, 0.954, 0.863 | 1.078, 0.906, **0.801** (edge) |
| Closeup hair p50 / p90 vs Cycles (closeup tuning frame) | (info) | — | 0.093 / 0.776 vs 0.109 / 0.806 |
| Closeup profile crown / back (neutral studio) | (info; Cycles 0.634) | 1.764 | 1.118 |
| Beard grey fraction, engine / Cycles (my definition, below) | (info) | 0.626 / 0.458 (×1.37) | 0.599 / 0.458 (×1.31) |
| Portrait SSIM, luma at 512 px, vs Cycles parity | (re-enabled; ≥ 0.80 is the old T6 target) | 0.701 (T9b b1 itself: 0.698) | **0.707** |
| Portrait head SSIM, luma at 100 % (560 × 560) | (new) | 0.517 (b1: 0.510) | **0.537** |
| KTX2 vs PNG GLB, engine portrait SSIM 512 / head | ≈ 1 | — | 0.999 / 0.978. The parity is unchanged (0.7063 PNG vs 0.7066 KTX2). |
| Turntable temporal noise (mean \|L(t−1) − 2L(t) + L(t+1)\|, 0–255) | lower | 6.37 | **6.08** (−5 %) |
| Shadow maps, hero rig | (info) | 5 | 10: key, rim and kicker, with fill and wrap shadowed plus hair twins |
| GTAO pass, half resolution | (info, SwiftShader) | — | 0.38–0.55 s |
| Portrait / hero closeup / turntable frame render | (info, SwiftShader, shared CPU) | 7.1 s / 10.9 s / 7.0 s | 15.7 s / 13.6 s / 10.4 s |
| GLB | (info) | 87.8 MB PNG | 41.5 MB KTX2. Images 78.9 → 32.6 MB, the three 4K head maps halved by `ktx2.mjs`. Load 589 ms. |

The beard grey fraction is the share of the beard's brighter half (≥ median luminance) whose HSV saturation is under 0.25. This is not the same definition as T11's tone record, so compare its ratios only with each other. The bright, neutral salt on the chin is what drives it. T10 does not make it worse.

**Brows at 0.80.** This is the only region near an edge. GTAO darkens the brow ridge, so brows go 0.863 → 0.801. The `brows` and `facialHair` parameter blocks are T11's, and I left them alone. A follow-up should raise `brows.albedoGain` about 10 %, or give the brows a higher `ao.lightWeightMin`.

## What changed

1. **Hair self-shadowing** (`web/src/character/hairshadow.ts`, `stage.ts`).
   - **Which lights get a twin.** Every shadowed light that reaches the hair gets a hair-only twin `<name>_hair`, and the parent light now excludes the hair group. The hero export already carried rim, kicker and fill twins. The viewer adds key and wrap, and the studio key, fill and rim.
   - **What the twin's shadow map holds.** The card geometry with its alpha test (card alpha ≥ 0.57 after the colour × map alpha product).
   - **The filter.** A custom one-layer deep-shadow `filterNode`: T = exp(−density · (depth behind the first occluder − bias)), 8 Vogel taps rotated by IGN, density 120 /m.
   - **Frustum and map size.** The frustum is focused on the head (`shadow.focus` from the angle to the head, near/far = distance ± 0.6 m), with 2048² maps.
   - **No baked fallback.** The baked per-card occlusion fallback was not needed and was not built.
   - Flags: `?hairshadow=0` gives the T9b binary shadow; `hair.deepShadow`, `shadowDensity`, `shadowBias`, `shadowRadius`, `shadowMapSize` and `shadowExtent` are in `params.ts`.
2. **Shadowed fill.** Fill and wrap now cast shadows (the `shadowFill` regex). Turn it off with `?fillshadow=0`.
3. **GTAO at half resolution** (`web/src/character/ao.ts`, `output.ts`, `materials/index.ts`).
   - **The pass.** three's `GTAONode` runs on a depth + view-normal prepass. In the prepass every character mesh swaps to a basic normal material; the cards keep their alpha at 0.5 and the hair depth-prepass twins are hidden.
   - **Where it is applied.** It multiplies the direct diffuse of skin, hair, eye, cloth and generic materials. The weight is per light, `min(1, size / distance)`, floored at `ao.lightWeightMin` 0.3, because a big soft light is what AO stands in for. A quarter of the baked AO stays in (`ao.bakedMix`).
   - **Flags.** `?gtao=0` restores the T6 0.5 direct-AO stand-in. `?aoview=1` / `?aoview=normal` show the AO and the normal buffer.
4. **Hair lobes refitted** (`params.ts` `hair`).
   - **Measured on per-term basis frames.** I rendered each lobe alone, at each studio light on the closeup and with the hero rig on the portrait, plus one frame with every lobe off. Then I solved a non-negative least squares against the Cycles per-light closeups and the parity portrait's boxes (`/tmp`-only scripts; the method is recorded in the params comment).
   - **What it showed.**
     - The Kajiya R lobe lit the side mass behind the temple, where Cycles lights the top.
     - A broad TT (ttPow 2) lit everything the rim reached. TT alone cannot separate crown from back: ttPow 2 → 6 drops both boxes by the same ×0.07.
     - Only the diffuse and scatter body carry a crown-over-back ratio near Cycles (×7 per unit).
   - **New values (was → now).**

     | Parameter | T9b | T10 |
     |---|---|---|
     | albedoGain | 1.0 | 1.3 |
     | scatter | 0.004 | 0.008 |
     | spec1 (R) | 0.035 | 0.0175 |
     | spec2 (TRT) | 0.007 | 0 |
     | tt | 0.13 | 0.36 |
     | ttPow | 2 | 6 |

     The model's prediction (per light 0.98 / 1.12 / 0.99, crown/back 3.22) landed within 3 % on the first real frame.
   - **Tried and dropped.**
     - `surfaceDepth` (an optical depth over the visible fibres) took the crown down with the back.
     - A deep-shadow density of 300 cost the rim 25 % for a small gain.
     - Both are left at 0 and 120.
5. **The hero-rig closeup** is a new view, `closeup:hero` → `game_closeup_hero.png`. It is in the default views of `engine_shots.{sh,mjs}`, and `deviceCapture` writes it too. The b1 run's misleading `hero_closeup.png` / `hero_shots.json` (the neutral rig, byte-identical to `game_closeup.png`) are deleted.
6. **Framing mismatch: there is none in the camera.** I registered the eye landmarks of the Cycles and engine frames by NCC of high-passed log-luminance patches. The offsets are:
   - +2/−1 px and +2/0 px for the b1 beauty, at 1920 px;
   - +1/0 px for the parity render.

   The silhouette is what differs. The Cycles hair top is 10 px higher (row 48 vs 58), and the mass reaches 60–90 px further back (row 150: x 1321 vs 1310; row 300: 1420 vs 1358, with the flyaways). The "lower and larger" read comes from the strand volume and from the beauty render's f/2 depth of field. Nothing in the rig needed fixing. The groom's volume against the cards' is T15's ground.
7. **Parity metrics** (`lookdev_report.py`, appended).
   - `hairparity` adds four outputs:
     - the closeup hair profile in crown / front / side / back boxes, with p10 / p50 / p90 and chroma;
     - the beard grey fraction;
     - the same per light (`--lights`);
     - the portrait boxes against the parity EXR (`--portrait`, `--cycles-portrait`).
   - `parity` re-enables the portrait SSIM row and adds a head-at-100 % SSIM.
8. **KTX2 copy as the gate asset**: `node web/tools/ktx2.mjs` and `?ktx2=1`. SSIM against the PNG GLB is above.
9. **Turntable**: `engine_shots.mjs --turntable 2 [--tt-view closeup:hero --tt-fps 24 --tt-size 640]` writes `<prefix>turntable/`, `<prefix>turntable.mp4` and the temporal-noise figure in `shots.json`.
10. **`engine_shots.sh --port N`**. Any further options pass through to the `.mjs`.
11. **Regression strip**: `lookdev_report.py strip RUN --cycles HERO`. It is also drawn after `engine` whenever `--cycles` is given, which is how `hero.sh` calls it.
    - **Rows.** The rows are fixed: main9, then int1 (with the T8 v5 hero, because int1 had no Cycles hero), then RUN.
    - **Engine crop.** The engine crop is registered to the Cycles crop by NCC at quarter scale.
    - **main9 row.** The main9 engine portrait predates the rig-by-data camera, so that row's two crops differ in pose. That is genuine, not a strip bug.

## Left / notes

- **The crown's colour is wrong; its level is right.** The engine crown is warm (key diffuse), and Cycles' is the cyan kicker's sheen through the strands. The R lobe cannot place it: Kajiya's narrow R does not hit the crown under the kicker, and its R/TT longitudinal shapes differ from Chiang's. The real fix is a Marschner/Chiang-style lobe set for the cards, which is the next hair-shading item. On the closeup, the neutral studio profile crown/back is still 1.12 vs Cycles 0.63, and top-back is about half of Cycles on the portrait.
- **Beard under the rim / kicker.** The beard is 0.37 of Cycles under the rim alone. The parents' shadow maps occlude it, and the facial hair has no hair twins. This matches the missing cyan rim in the picture. Giving `beard` its own twin group is an `export_rig.py` and stage change. I left it for T11's successor, with the brows note above.
- **The AgX grey-chart check was not done.**
- **Frame times are SwiftShader on a shared CPU.** The deep shadow doubles the maps (5 → 10) and GTAO adds a pass, so the Air measurement matters before shipping. The hair twins' map size is a single parameter.
- **`hero.sh` writes its engine sheet into the source run** of the `.blend`, resolving symlinks. My b2 parity render therefore overwrote T12's `t12-b2/engine_sheet.png`. I regenerated it against T12's own hero (`lookdev_report.py engine … --cycles hero/20261014T185633Z-t12-b2`). The same run also left a `regression_strip.png` there.
- **One 404 per engine run** is the optional `material_params.json`. It predates T10.
