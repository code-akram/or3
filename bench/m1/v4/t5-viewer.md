# T5: engine character viewer (m1 v4, step 2)

_2026-10-14. Track T5 of "m1 v4: engine first, structure first" (fable_review.md §3.5 step 2, §3.2 C1)._

From now on the m1 look gate is the **engine frame**. The Blender Cycles hero render is the target it is judged against. This track builds that frame:

- the shipped GLB in three.js WebGPU with a first TSL material set;
- the `character.rig.json` deformation runtime;
- the look-dev and hero stages, exported from Blender as data;
- a headless screenshot path that every look-dev run can use.

## Evidence (baseline build `20261013T081002Z-heroE-main9`)

All files are in `data/build/lookdev/20261013T081002Z-heroE-main9/`, which is gitignored.

| File | What |
|---|---|
| `engine_sheet.png` | **The contact sheet**, in four rows: (1) the EEVEE views, (2) the engine views with the same cameras, (3) the Cycles hero portrait (`data/build/hero/20261013T081828Z-main9-final/portrait.png`) next to the engine portrait, with the same camera, rig and pose by data, (4) the face at 100 % from both, using the same crop rectangle. |
| `game_front.png`, `game_three_quarter.png`, `game_profile.png`, `game_closeup.png` | Engine frames at 1024², neutral look-dev rig |
| `game_portrait.png` | Engine frame at 1920×1080, hero neon rig, hero `stand` pose |
| `game_shots.json` | Sidecar: backend, adapter, browser, load and render timings, draw calls, triangles, lights per shot, and the rig.json check |
| `engine_stage.json` | Cameras, lights and the hero pose, exported from Blender (`blender/hero/export_rig.py`) |
| `engine_pose_armsup_ab.png` | Correctives at work: the `arms_up` debug pose without (left) and with (right) `corr_arm_up_*`. The weights are 1.0 / 1.0. |

**Measured** (headless Chromium 156, this machine, pinned to 4 cores, under load average ~45):

| | |
|---|---|
| Backend | **WebGPU** on SwiftShader (`google / swiftshader`) for every image. The WebGL2 fallback (`?gl=1`) also works; it was checked on the portrait and closeup, and its readback rows are flipped. |
| GLB load | **1.07–1.21 s** for 72.7 MB, over loopback. This covers fetch, parse and PNG decode (GLTFLoader resolves after the images). Over the SSH tunnel to the Mac, the network sets the load time. |
| First frame | 1.7 s (SwiftShader, including pipeline compile) |
| Triangles | **126,862** in the model. Rendered per frame: 380,588 under the neutral rig (main pass and 2 shadow maps), 761,174 under the hero rig (main pass and 5 shadow maps). |
| Draw calls | **64** neutral, **127** hero, including shadow passes. The main pass is 21 character primitives plus the floor; each shadow map adds 21. |
| Textures | 35, an estimated **579 MB** as uncompressed RGBA8 with mips. KTX2 is needed before the Air run. |
| Capture time (SwiftShader) | 10–25 s per 1024² view; 20 s for the 1920×1080 portrait; about 95 s for the whole `engine_shots.sh`, Blender export included |
| rig.json runtime vs Blender | Corrective weights for the hero `stand` pose match `deform_runtime.py` with a maximum absolute difference **< 1e-5**. That covers all 14 rules: `corr_arm_down_l` 0.5758, `corr_arm_down_r` 0.7941, `corr_elbow_l` 0.3285, and so on, which are the Cycles final's pose-log values. The largest helper-bone world-rotation difference is **0.036°**. |

These are frame numbers from SwiftShader, not the M4 Air. The HUD shows frame time, draw calls, triangles and texture memory interactively (see "Run it" below).

## What reads wrong in the engine frame vs the Cycles target (ranked)

The ranking is by how much each item moves the read. Each one names the side it belongs to: the asset, which feeds the next steps, or the engine.

1. **Scalp hair (asset first, then engine).**
   - In the engine the cards are separate flat ribbons. You can see through them at the crown, the temples and the hairline. The scalp cap shows as a hard edge and stringy cards across the forehead. Flyaway cards read as straw. Under the hero rig, the tinted Kajiya-Kay lobes streak teal and blue.
   - Cycles shows one dense dark mass with a soft silhouette and a magenta rim along the top.
   - The shader is not the main cause. The cards and cap are, as in §5.3: the cap texture is nearly empty, the temple bays streak, there are 484 thin ribbons and no layered core. Hair v4 steps 1–4 come first; the engine shader (§5.5 step 5) is already wired with flow, ID, root/tip and depth, so it only needs tuning.
2. **Beard and brows (asset).**
   - The fur shells render as noisy spatter: alpha-to-coverage dither of thin shells, a hard cheek edge, and see-through dots. The brows are dotted lines, not a soft bar.
   - Cycles shows a dense, near-black volume.
   - Once the §1.9 sRGB bug is corrected in the engine (`facialHair.linearFix`), the beard reads grey-brown, and under the neutral rig the chin grey shows. That is the intended grey, which EEVEE's bug had hidden. The `beard_bake` gains were tuned against the bug. Until they are retuned, the engine compensates with `facialHair.albedoGain` 0.45.
   - Shells cannot carry this read. It needs cards or strands (§5.5 step 6).
3. **Skin reads as tan vinyl (both sides).**
   - The engine shows a broad, continuous specular sheen on the forehead, nose and cheekbone. The terminator is hard, with no SSS softening. At 100 % the pore detail is a regular stipple. There is a blotch on the character's left cheek; it comes from the skin texture.
   - Cycles shows a matte, soft surface with a random-walk SSS terminator.
   - Engine side, this baseline uses only wrap-lit diffuse, a per-channel normal blur and a terminator tint. The next step is a pre-integrated SSS LUT driven by a curvature bake, and roughness variance; the ORM roughness σ is 0.035, so the surface is one sheen.
   - Asset side, see the next item.
4. **Head form (asset).** Both frames show the same egg skull, weak brow, soft cheek planes and short lower face. The engine's harder light makes the missing plane breaks more obvious. This confirms that the FLAME and sculpt step (§3.5 step 3) is next for the face.
5. **Suit (asset first, then engine).**
   - The engine jacket reads lighter and satin-like:
     - three's sheen plus a fuzz rim, even after tuning down;
     - residual diagonal twill aliasing on the lapel and sleeve, from the baked twill normal maps (8× anisotropic filtering helps, but does not remove it);
     - bright lapel-edge highlights.
   - Both frames show tubes with no folds.
   - Cycles shows near-black wool with a soft grazing sheen.
   - Pattern-sewn garments (§3.5 step 5) fix the form. In the material, the twill needs a detail-normal approach (a lower-frequency tile, faded by mip) rather than a 4k baked weave.
6. **Lighting stage gaps (engine).**
   - There is no ambient occlusion or contact shadow at the collar and neck, under the jaw, at the ears, or where the hair meets the scalp.
   - The rims are spot lights approximating strip area lights. They land harder and stronger on the cheek and have no strip-shaped highlight.
   - There is no depth of field, bokeh, set, haze, rain, bloom, halation or grain. Cycles has all of them. The engine frame therefore reads more "CG" than the material differences alone would.
   - Next: a GTAO pass, LTC rect-area lights for the rims and the wrap, and bloom and grain in the output pass.
7. **Eyes (closest to the target).**
   - The cornea lobe, limbal ring and iris parallax work.
   - There is no lid-contact shadow or wet line. Gaze is not turned to the camera: `wet.gaze` is skipped, so the eyes keep the rest gaze.
   - The eye light lights only the eyes. In Blender it is a 0.3-diffuse catchlight.
8. **Neutral views vs EEVEE.**
   - Framing is identical, because the cameras come from the same math.
   - The floor shadows are harder in the engine (PCF radius vs EEVEE's soft shadows).
   - The jacket is a little lighter.
   - The beard is lighter and greyer (item 2).

## Built

### Files

| Path | Role |
|---|---|
| `web/character.html`, `web/src/character/main.ts` | Second Vite entry: boot, panel (view, rig, pose preset and amount slider, turntable, camera reset), HUD, capture API (`window.__viewer`, `window.__viewerState`) |
| `web/src/character/deform.ts` | TS port of `deform_runtime.py` (twist, swing and follow helpers; cone correctives). Same semantics and order, glTF model space, bind pose from the inverse-bind matrices (`skeleton.pose()`). |
| `web/src/character/poses.ts` | Bind pose; the exported hero pose (per-bone deform matrices `D = W_posed · W_bind⁻¹`, independent of the importer's bone orientation); debug presets that drive each cone rule toward its own target (`arms_up`, `arms_fwd`, `arms_down`, `elbows`, `hips_fwd`, `knees`, `fists`, `twist`) |
| `web/src/character/materials/` | TSL materials, `params.ts` (the JSON parameter block; every leaf is a live uniform) and `style.ts` (the stylisation hook) |
| `web/src/character/stage.ts` | Look-dev studio and hero rig from `engine_stage.json`, light linking, cameras including Blender shift |
| `web/src/character/output.ts` | HDR MSAA scene target → one pass (exposure, hero grade, AgX, sRGB) → canvas or RGBA8 readback |
| `web/src/character/hud.ts` | Perf telemetry stub |
| `web/character-assets.mjs` | Dev-server `/asset/` middleware. One root only; loopback. |
| `blender/hero/export_rig.py` | Dumps cameras, lights, the hero pose and Blender's own corrective weights to `engine_stage.json` (GLB import, `-t 3`, about 11 s) |
| `bench/m1/engine_shots.mjs`, `bench/m1/engine_shots.sh` | Headless capture into the run dir |
| `bench/m1/lookdev.sh` | `ENGINE_SHOTS=1` hook |
| `bench/m1/lookdev_report.py` | Engine row in `sheet.png`; new `engine` subcommand → `engine_sheet.png` |

### Materials

The glTF materials are replaced by name and role. Each is a `MeshPhysicalNodeMaterial` with a small custom `PhysicalLightingModel`, so indirect light and shadows stay three's own.

| Role (glTF material) | Shading |
|---|---|
| **skin** (`skin_head`, `skin_hands`) | Wrap-lit diffuse with per-channel wrap (R 0.30, G 0.12, B 0.08), scaled by screen-space curvature. A per-channel normal blur toward the geometric normal as a cheap pre-integrated SSS stand-in, plus a red terminator tint. Dual-lobe GGX specular (roughness × 0.85 and × 1.45, 20 % mix, F0 0.028). ORM roughness and AO. |
| **hair** (`hair_cards`, `hair` cap) | Dual-lobe Kajiya-Kay: a white primary shifted toward the root and an albedo-tinted secondary toward the tip, with shifts jittered by the strand ID. The fibre tangent comes from the **flow sidecar** through the exported TANGENT frame (bitangent by default). Root AO from the data atlas root→tip channel, depth AO from the flow B and A channels, `COLOR_0` lock values. **Alpha-to-coverage with 4× MSAA**, and hashed alpha when there is no MSAA; never sorted MASK. Cards are shaded on the GLB's smooth proxy normal. |
| **facial** (`beard`, `brows`, `*_cards`, `eyelash_cards`) | The same hair model, tangent = UV bitangent. The atlases are read as linear (the §1.9 S2 fix; `facialHair.linearFix`). |
| **eye** (`eyes_hq`) | Physical iris and sclera. A sharp GGX cornea lobe on the geometric eyeball normal. Limbal darkening at the limbus row (the eye UV is polar: limbus v = 0.645, pupil v = 0.79). Iris parallax in tangent space. |
| **cloth** (`suit_wool`, `suit_wool_b`, `suit_vest`, `suit_silk`; `suit_shirt` with less fuzz) | glTF sheen (× 0.6) plus a `(1 − N·V)^3` fuzz rim, the baked twill normal, and a procedural micro-twill (strength 0.12) that fades out where a ridge is under about 3 px. Without the fade it caused moiré in A/B. |
| **generic** (leather, sole, buttons, teeth, tongue, nails) | glTF PBR as exported |

- **Stylisation (C2 is still open).** All three lighting models send their diffuse term through `style.diffuseRamp`. `params.style.banded = 1` switches on a 3-band ramp with a soft terminator (`bands`, `softness`). Painted albedo goes in at `style.albedo`, and ink lines will be a pass in `output.ts`. None of this needs the BRDFs rewritten.
- **Parameters** can be set in three ways, all without recompiling:
  - `?params=<URL-encoded JSON>`;
  - a `material_params.json` next to the GLB;
  - `__viewer.setParam('skin.wrap', [0.4, 0.15, 0.1])`.

### Lighting and units

- **Data, not hand.** `export_rig.py` replays `lookdev_render.build_studio` and `make_cameras` (the math is copied; the module parses argv at import). For the hero stage it runs `hero.poses.apply('stand')`, `rig.camera` and `rig.hero_rig` for the portrait and records:
  - every light's world position, aim, colour, power, size and light-linking receivers;
  - the camera, including `shift_x` / `shift_y`, f-stop and focus;
  - the per-bone deform matrices;
  - Blender's own corrective weights and helper rotations, which the viewer checks itself against on every load.
- **Conversion.**
  - A Blender area light of power P at distance d gives an on-axis irradiance E = P / (π d²); this is `rig._light_power`'s convention, and a Lambert surface then renders albedo · E / π.
  - A three.js SpotLight of intensity I gives E = I / d² and the same albedo · E / π, so **I = P / π, with no other factor**. Examples: the hero key is 21.2 W → 6.75, and the look-dev key is 900 W → 286.5.
  - The area emitter's cosine falloff is approximated by an 80° cone with full penumbra, and its size by the PCF shadow radius.
  - A uniform world of radiance Lw becomes a hemisphere light of intensity π·|Lw|.
  - Kelvin colours use a Planck × CIE 1931 blackbody normalised to luminance 1. This approximates Blender's: 3000 K → (1.755, 0.849, 0.271).
- **Shadows.** The key, rim and kicker cast shadows, including the hair twins of the rim and kicker; that is 5 maps under the hero rig. The twins could share their parent's map, which saves 2 passes.
- **Light linking.** `rig.py`'s twins are per-material `lightsNode` sets. The rim and kicker exclude the hair; `rim_hair` and `kicker_hair` (desaturated) light only the hair.
- **Grade.**
  - Neutral: exposure −2.5 EV, AgX.
  - Hero: exposure −0.6 EV, then white balance (divide by the 3900 K blackbody), then CDL slope / offset / power, saturation 0.97 and a −0.3 EV vignette, then AgX (three's), then sRGB.
  - Not ported: bloom, halation, dispersion and grain.
  - three's AgX is close to Blender's "AgX – Base Contrast", but not identical.

### Containment

- The dev server and the capture server bind 127.0.0.1 only.
- **Dev server.** `/asset/` serves exactly one root: `<main>/data/build` by default, or `CHARACTER_ASSET_ROOT=<dir>`, which replaces it. Symlinks are resolved and re-checked against the root, and only `.glb`, `.json`, `.png` and `.ktx2` are served.
- **Capture server.** `engine_shots.mjs` serves `web/dist-viewer` plus a whitelist of six files from the one run dir it was given, and writes only into that dir.
- **Fan runs.** `lookdev.sh --fan` passes the private run dir, so stage export, frames and the sidecar all stay in `private/likeness/lookdev/<run>/`. The routing was made correct but has **not been run on a fan build**; I did not load or view any fan asset.
- **The lookdev.sh change** is one separated block before `finalize`, plus one usage line.

## Run it

- **Interactive** (WebGPU on the Mac's Chrome; the HUD shows frame p50/p95, draws, triangles, texture memory, load time and live corrective weights):
  ```
  cd web && npm run dev            # http://127.0.0.1:5173/ (loopback only)
  ssh -N -L 5173:127.0.0.1:5173 archlinux                    # on the Mac
  http://127.0.0.1:5173/character.html?asset=lookdev/20261013T081002Z-heroE-main9&view=portrait&rig=hero
  ```
  - `view`: `front`, `three_quarter`, `profile`, `closeup` or `portrait`.
  - `rig`: `neutral` or `hero`. Under `hero` with a non-portrait view, the camera-relative rig is re-placed with `rig._around`.
  - `turntable=1`; `pose=stand|arms_up|…&amount=0.7`; `gl=1` for WebGL2; `correctives=0` for an A/B; `ui=0`.
  - The default asset is `lookdev/latest`.
  - For a private run: `CHARACTER_ASSET_ROOT=/abs/private/run npm run dev`, then `asset=.`.
- **Headless frames for a run:** `bench/m1/engine_shots.sh RUN_DIR`, about 95 s. It also runs inside a look-dev run with `ENGINE_SHOTS=1 bench/m1/lookdev.sh <label>`. It is **off by default**, because SwiftShader adds minutes to a 5–7 s loop.
  - Env: `ENGINE_CPUS` (default `0-3`), `ENGINE_BACKEND` (`auto`, `webgpu` or `webgl2`), `ENGINE_SIZE`, `ENGINE_PORTRAIT`, `ENGINE_VIEWS`.
- **Contact sheet:** `python3 -I bench/m1/lookdev_report.py engine RUN --cycles data/build/hero/<final>`
- **Builds:** `npm run build` builds both pages into `web/dist`. `npm run build:viewer` builds only the viewer into `web/dist-viewer`, which needs no WASM core. `npm run typecheck` passes.

## Left / next

- **The Air run.** Measure the viewer on the M4 Air (real WebGPU on Metal). Before that, convert textures to **KTX2** (579 MB estimated uncompressed now), add GPU timestamps to the HUD and drop the twin shadow maps.
- **Engine look.**
  - A pre-integrated SSS LUT plus a curvature bake;
  - GTAO;
  - LTC rect-area lights for the rims and the wrap;
  - bloom and grain in the output pass;
  - eye gaze toward the camera (the hero shots turn the eyes);
  - DOF for the portrait.
- **Hair shader.** The sign of the shift (`hair.tangentSign`, root→tip) has not been checked against a strand render. Do this once the hair v4 cards exist; the current cards make it unreadable.
- **Assets.** The beard sRGB fix belongs in `beard_bake.py`; retune its gains, then remove the engine's `facialHair.albedoGain` compensation. After that, steps 3–5 of the programme (head sculpt, hair v4, suit), judged on `engine_sheet.png`.
- **C2 is still open.** The banded-ramp switch exists; the painted albedo bake and ink pass wait on the decision.
- **The GLB-imported hand settle differs slightly from the .blend final.** `export_rig.py` adds an empty `body` marker group so `hand_pose` runs on a GLB import. The right hand settles to "39 tris, 3.3 mm" where the final had "25 tris, 3.9 mm". Corrective weights are unaffected.
