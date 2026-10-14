# T6: engine look parity (m1 v4)

_2026-10-14. Track T6 of checkpoint-1.md §3 (items §1.3 must-fix and §2 items 1–8), branch `worktree-agent-a4bfe2bb1dab4230f`._

## Gate result

| Gate | Target | Before | After |
|---|---|---|---|
| Shader-ball mean luminance ratio, six materials | each within ±10 % | 3 of 5 measurable (the hair ball was black in Cycles) | **6 of 6** |
| Shader-ball highlight peak ratio | each within ±20 % | 3 of 5 | **6 of 6** |
| Portrait SSIM (luma, 512 px) vs the Cycles `--parity` portrait | ≥ 0.80 | **0.666** | **0.700**: **missed** |
| Row 3 captured on the Air | — | — | path built and self-tested; needs the user's Mac (steps below) |

**The portrait target is missed, and I don't expect any T6 knob to close it.** Per region, after T6 (512 px luma SSIM, Cycles mean luma vs engine mean luma):

| Region | Before | After |
|---|---|---|
| face | 0.56 (59 vs 73) | 0.62 (**59 vs 59**) |
| hair sides | 0.50 (34 vs 43) | 0.56 (34 vs 35) |
| suit | 0.67 | 0.72 |
| background | 0.69–0.78 | 0.68–0.78 |

Brightness now matches everywhere. What remains is structure, and it sits in the asset:

- **Hair.** Cycles renders long hero strands; the engine renders shorter cards with a different silhouette.
- **Beard.** Dark strands in Cycles, light-grey shells in the engine. T8 owns this (the beard tone and grey retune).
- **Noise.** Fine-scale differences in SwiftShader's MSAA.

On the metric, 0.80 is not reachable until hero and game hair agree in shape.

## Evidence

All under `data/build/`, which is gitignored. Nothing from it is committed.

| Path | What |
|---|---|
| `lookdev/20261014T103057Z-t6-after/engine_sheet.png` | **The gate sheet**, with the new last rows: Cycles shader balls next to engine shader balls, then the parity numbers (SSIM, plus per-ball mean and peak ratios) |
| `lookdev/20261014T103057Z-t6-after/t6_before_after.png` | Portrait strip: Cycles parity, baseline engine, T6 engine, T6 engine with beauty post |
| `lookdev/20261014T103057Z-t6-after/engine_parity.json` | Numbers behind the sheet |
| `lookdev/20261014T103057Z-t6-after/game_*.png`, `game_balls.png`, `game_shots.json` | Final engine frames (SwiftShader) |
| `lookdev/20261014T103057Z-t6-after/cycles_balls.png`, `shader_balls.{glb,json}` | Cycles balls (64 spp, Standard view) and the ball scene for the engine |
| `lookdev/20261014T101019Z-t6-base/base_portrait.png` | Baseline: main's viewer on the t6-base build (current main, rebuilt) |
| `hero/20261014T113615Z-t6-parity-after2/portrait.png` | Cycles `--parity` portrait of the T6 build, with the weave (125 s at `-t 6`) |
| `hero/20261014T102659Z-t6-parity-base/portrait.png` | Cycles `--parity` portrait of the baseline build (217 s) |
| `lookdev/20261014T103057Z-t6-after/ktx_portrait.png` | `?ktx2=1` frame, compared against `game_portrait.png` |

Shader balls, after (`area=all`, i.e. LTC rects; ratio = engine / Cycles):

| Material | Mean | Peak | Before (spot lights, uncalibrated, t6-base) |
|---|---|---|---|
| skin_head | 0.967 | 0.844 | 1.052 / 0.943 |
| suit_wool | 1.000 | 0.960 | 1.317 / 1.414 |
| suit_silk | 1.031 | 0.953 | 1.082 / 1.154 |
| suit_leather | 0.952 | 0.972 | **0.426** / 0.489 |
| hair_cards | 1.009 | 1.173 | invalid (Cycles ball black, see below) |
| eyes_hq | 1.068 | 1.142 | 0.963 / 0.814 |

## What changed

### Must-fix (§1.3) and the §2 list

1. **linearFix (§1.3 #1).** `resolveFacialAtlas` reads the build:
   - a `character.stats.json` with `beard.atlas_fill_linear` (T2 or later) decodes the atlas as tagged sRGB at gain 1;
   - older builds get the linear read at 0.45.
   - The sheet records the choice (`facial_atlas`).
2. **Direct AO (§1.3 #2).** The AO map multiplies direct diffuse at 0.5 (`skin.directAO`, `cloth.directAO`). It stands in until GTAO lands.
3. **Twill moiré (§1.3 #3).** The weave is out of the baked wool and silk maps (seams, folds and hems stay in). The shirt keeps its baked weave.
   - New sidecars: `suit_twill_detail.png` (256², 8 rib periods) and `suit_detail.json` (repeat, angle and strength per material).
   - The engine tiles the detail with mips and an `fwidth` fade. The moiré is gone from the portrait.
   - **Cycles had lost the weave with it.** `suit_textures.cycles_weave` adds the same arithmetic in nodes at render time only, in `lookdev_render.py` (from the GLB sidecar) and `hero/stage.py` (from the .blend). The silk ball's cross-hatch now matches pattern for pattern.
4. **Parity render (§1.3 #5).** `hero.sh --parity`:
   - void set, no DoF, filter 1.0 px, 64 spp + OIDN;
   - `grade.py --parity` drops bloom, halation, dispersion and grain.
5. **ENGINE_SHOTS (§1.3 #6).** Default on for `lookdev.sh --signoff` and `hero.sh`. `hero.sh` writes the engine sheet against its own render.
6. **Gaze (§1.3 #8).** `export_rig.py` exports the shot's eye rotations, and the viewer applies them to the eye meshes for the portrait (`?gaze=0` turns it off).
7. **Shader balls (§2 #3).** `lookdev_render.py --shader-balls` puts a sphere per material, carrying a UV patch of that material's atlas, under the neutral rig. `engine_shots --balls` renders the same GLB and camera in the viewer. `lookdev_report.py` appends the row and the numbers. Bugs found on the way:
   - the camera's AUTO sensor fit was applied to the wrong axis (balls at half size);
   - the hair-card material multiplies a per-lock tint layer that the ball lacked: black in Cycles, white in three. Balls now carry the source mean.
8. **LTC rect lights (§2 #5).** `?area=none|rims|all`: Blender-sized `RectAreaLight`s with I = P/(π w h).
   - three's stock rect path has no sheen and none of our custom terms. The skin, cloth, hair and eye models now have `directRectArea`:
     - **skin:** LTC specular plus the SSS diffuse;
     - **cloth:** LTC plus sheen and fuzz;
     - **hair:** Kajiya-Kay;
     - **eye:** cornea as LTC GGX.
   - The non-LTC terms see a point equivalent of the rect (I = L·A·cosθ).
   - **Default is still shadowed spots for the portrait.** three's rect lights cast no shadow, and the rims leak onto the collar and under the jaw. Portrait SSIM: spots 0.700, rims 0.691; all scored lower against the baseline parity render (0.670).
   - The balls use `area=all`: no occluders, so the rects are the faithful model there.
9. **Pre-integrated SSS (§2 #6).**
   - A curvature map is baked per skin part: `skin_tex.curvature`, 1k head and 512 hands, κ/100 m⁻¹, a 4 mm masked blur, checked at κ = 20 /m on a 5 cm sphere.
   - A 128² Penner LUT (two-Gaussian profile at 3.4 / 0.748 / 0.34 mm) is built at load. Each colour channel samples it with its own blurred N·L.
10. **Output pass (§2 #7).** Bloom and halation from a half-res mip chain, then grain. The grade order is fixed to match `grade.py`: WB, CDL, black lift, saturation, vignette, grain, exposure, AgX.
    - The portrait is captured twice: `game_portrait.png` (no post; the parity frame) and `game_portrait_beauty.png`.
    - **No DoF.**
11. **KTX2 (§2 #8).** `build_character.py --ktx2` (or `node web/tools/ktx2.mjs IN OUT`) writes `character.ktx2.glb`; the viewer loads it with `?ktx2=1`.
    - Encoding: UASTC q2 + Zstd for normals and ORM (tagged linear), ETC1S q128 for colour.
    - The encoder is ktx2-encoder (Basis WASM; no toktx on this machine). It caps a texture at about 12 Mpix, so the three 4k head maps are halved to 2k.
    - **GLB 69.3 → 31.8 MB, images 61.5 → 24.0 MB.** GPU memory is roughly 283 MB as RGBA8 (the HUD estimate; it was 579), or about 70 MB once transcoded to ASTC/BC7 at 1 B/texel. That is arithmetic, not a measurement.
    - Portrait vs the PNG GLB: **SSIM 0.998**.
    - Two bugs fixed on the way:
      - the encoder's defaults tag every file sRGB, which gave wet skin;
      - gltf-transform interleaves vertex buffers, which scrambled the gaze-rotated eyeballs. EyeGaze is now layout-agnostic and the tool writes separate streams.
12. **Air capture (§1.3 #4, §2 #2).** `?capture=1&upload=1` renders every view on the device's GPU. It POSTs raw RGBA to `engine_shots.mjs --serve`:
    - the server binds 127.0.0.1 only, accepts only whitelisted `game_*` names, writes PNGs into the run dir, and exits after `game_shots.json`;
    - a perf loop records rAF frame times and WebGPU timestamp queries.
    - **Self-test passed** in headless Chromium (`--serve --selftest`): six frames and the summary landed in the run dir. SwiftShader's 6.8 s per frame at 640×360 says nothing about the Air.

### Calibration (on the balls, not by eye)

| Param | Was | Now | Evidence |
|---|---|---|---|
| `cloth.sheenScale` | 0.6 | **0.15** | wool 1.35 at 0.6, 0.88 at 0, linear in between; the same result under spots (0.997) and rects (1.000) |
| `hair.spec1` / `spec2` | 0.07 / 0.08 | **0.0175 / 0.02** | hair card 3.0× Cycles; diffuse alone 0.35× |
| `eye.corneaStrength` | 1.0 | **0.7** | area catchlight peak 1.35× (Cycles coat f0 is about 0.025, ours 0.04) |

BRDF structure is unchanged; these are gains only. `facialHair` (T8) and the beard and brow atlases were not touched.

## Run it on the Air

1. On this machine: `node bench/m1/engine_shots.mjs --build data/build/lookdev/<RUN> --serve`. Use `--port 8792` if 8791 is taken; the server now says so instead of hanging.
2. On the Mac: `ssh -N -L 8791:127.0.0.1:8791 <this host>`.
3. Open the printed URL in Chrome or Safari with WebGPU: `http://127.0.0.1:8791/character.html?asset=.&capture=1&upload=1&ui=0&dpr=1`. Add `&ktx2=1` for the KTX2 copy (needs `build_character.py --ktx2`), and `&perf=300` for a longer timing loop.
4. Leave the tab in front until the page says done; the server exits by itself.
5. Then run `python3 bench/m1/lookdev_report.py engine data/build/lookdev/<RUN> --cycles data/build/hero/<parity run>`. Row 3 is now Air pixels.

GPU timestamps need `timestamp-query`. Safari may not expose it, in which case `gpu_ms` is null and only rAF frame times are recorded.

## What's left

- **Portrait SSIM 0.70 < 0.80.** Hair silhouette (cards vs strands) and beard tone are the bulk of it, and both belong to T8. Re-measure after T8 merges; the sheet does it on every run.
- **DoF** (portrait only) is not done. Neither is **GTAO**, so the 0.5 direct-AO stand-in stays. The **AgX grey-chart check** (§1.3, minor) was not run.
- **LTC rects cast no shadow.** The fix is a shadowed-spot diffuse with an LTC-only specular per light (a hybrid), or contact shadows.
- **Shirt weave** is still baked; it showed no moiré at the portrait scale.
- **Air row 3** needs the user's Mac session (above). The device page does not capture the balls yet: they are a separate page (`?scene=balls`).
- **Older .blends:** for builds before this branch, the twill tile was not saved in the .blend (no users). `cycles_weave_blend` falls back to the PNG sidecar; new builds give the tile a fake user.
- **Skin peak is 0.844 under rects.** It passes, but the LTC lobe uses the material's single specular, not the dual lobe.
- **Metric note.** ffmpeg's `ssim` filter reads about 0.40 on these pairs, where a standard SSIM (11×11 Gaussian, σ 1.5) reads about 0.68. `lookdev_report.py` uses the standard one in numpy.
