SwiftShader only

_Every engine frame and timing in this report comes from WebGPU in headless Chromium running on the CPU (SwiftShader): port 8798, CPUs 12–15, `nice -n 10`, on a shared machine at load 45–57. **SwiftShader milliseconds say nothing about the Air.** The tables report them only as relative costs between variants on the same machine, alongside the work each variant adds (passes, draw calls, map texels, textures), which does carry over. The texture memory figures are exact either way: SwiftShader exposes ETC2 and ASTC, so the KTX2 transcode picks the same formats as on the Air. Track G1, m1 v4, 2026-10-15. Public build only; nothing under `private/` was opened or written._

# m1 v4 track G1: gameplay-tier grounding, texture LOD and the texture-count audit

Pictures are in `data/build/g1/gate/`:
- `g1_3m_side_by_side.png`: the gameplay framing (3 m, hero rig, 1024², KTX2, 100 %). The panels are the gameplay tier before, the gameplay tier after (capsule floor shadows plus texture LOD), and the hero tier.
- `g1_3m_feet_2x.png`: the shoes and floor from the same three frames, 2× point-sampled.
- `g1_3m_signed_hero_minus_after_x8.png`: signed luma difference, hero tier minus gameplay after, ×8 (green where the hero tier is brighter). The shadow streaks coincide; the floor is brighter overall in the hero tier (§1.5).
- `g1_candidates_feet.png`: the shoes and floor for every candidate, 1.5× point-sampled. The panels are before, `contact=1`, `shadows=key,rim`, capsules (chosen) and the hero tier.

## Gate

| gate | result |
|---|---|
| 3 m gameplay side-by-side (before, after, hero tier), shoe and floor grounding visible | **Pass.** See `g1_3m_side_by_side.png` and `g1_3m_feet_2x.png`.<br>• Before, the shoes sit on a flat floor with nothing under them.<br>• After, the rim (magenta) and kicker (cyan) cast leg and shoe shadows across their floor pools, and the floor darkens at each sole, as the hero tier's five PCSS maps do.<br>• No change above the floor (§1.4). |
| Texture memory per tier | **Done (§2.3).** On the Air's formats, sampled textures come to:<br>• hero tier: 115 MB;<br>• gameplay tier before: 115 MB;<br>• gameplay tier after: **51 MB**.<br>Measured live on SwiftShader: 122.9 MB hero, 121.6 MB gameplay before, 57.6 MB gameplay after. |
| Texture count per material per tier ≤ 16, eyes noted as T18b's | **Gameplay tier: pass, maximum 13** (`eyes_hq`, `skin_head`, `skin_hands`) in every view, portrait included.<br>**Hero tier: pass in the device-capture views (max 16); the live portrait is over** ({{HERO_PORTRAIT}}). That is the known T18b case, and the audit now flags it by name (§3). |
| Added cost per tier | **§4.**<br>• Hero tier: nothing added to the frame.<br>• Gameplay tier: capsules add 0 passes, 0 draw calls, 0 map texels and 0 textures. They add ALU in the floor's fragment shader only: {{FLOOR_COST}}. |
| Hero closeup mean diff < 0.5/255 | **Pass: 0.0000 (max 0), identical**, `heroB_closeup_hero.png` (before G1) against `heroA_closeup_hero.png` (G1 code). The hero tier's gameplay framing is identical too (mean 0, max 0). |
| 0 glTF errors | **Pass.** gltf-validator reports 0 errors on every GLB G1 wrote:<br>• `g1-a2/character.lod1.ktx2.glb`;<br>• `g1-a2/character.lod1.glb`;<br>• `g1-a1/character.lod1.ktx2.glb`;<br>• `g1-a1/character.ktx2.glb`. |
| air-session.md | **Updated.** Step 4b adds two automatic gameplay captures on the G1 asset (`lookdev/20261015T094709Z-g1-a2`), with and without `floorshadow`, both with `texcheck=1`. |
| `cd web && npm run build` | **Pass** (tsc and vite), after merging main at f9d9069. |
| `bash bench/m1/test_containment.sh` | **Pass: 75 passed, 0 failed.** |
| `python3 -I provenance/audit.py --data-root <main>/data --check-files --release` | **Pass: 178 records, 0 errors, 0 warnings.** |

## 1. Floor shadows

### 1.1 What was missing

The gameplay tier keeps one shadow map, the key's (1024², PCF; `tiers.ts`). In this rig the key is high and in front, so its shadow of the legs falls mostly behind the feet and out of frame. The shadows that ground the shoes in the hero tier come from the rim and kicker: long magenta and cyan streaks from each shoe across that light's floor pool. The gameplay tier lost them all, and T24 recorded this as open.

### 1.2 Candidates (`g1_candidates_feet.png`)

| candidate | picture at 3 m | work added per frame |
|---|---|---|
| `shadows=key,rim` (a second map, 1024²) | One faint magenta streak behind the right shoe. The kicker's cyan streak and both contacts are still missing. A third map (kicker) would be needed to match. | +1 depth pass (the character's ~26 draws again), +1 M map texels (8.4 MB of targets: rgba8 + depth24), **+1 sampled texture in every receiving material** (eyes and skin 13 → 14) |
| `contact=1` (screen-space contact shadows, key only) | No visible change at the feet. It traces toward the key, whose shadow is already mapped. | +1 screen pass (`pre:contact`), +1 sampled texture in every material |
| Blob shadow at the feet | Not built. A blob gives contact but no direction. The hero tier's look is two coloured, directional streaks, which a blob can't make. | +1 draw, +1 texture in the floor only |
| **Analytic capsule shadows on the floor (chosen)** | Rim and kicker streaks plus contact darkening at each sole, in the same places as the hero tier's. Slightly darker than the hero tier right at the soles; plausible, and not tuned to match. | **0 passes, 0 draw calls, 0 map texels, 0 textures.** ALU in the floor's fragment shader only, and one CPU update of 14 capsules per frame |

The capsules win on both counts: they are the only candidate that gives back the hero tier's streaks, and they add no pass and no texture binding. A binding matters here: in the hero tier, five maps plus contact already push the eyes to the 16 limit.

### 1.3 How the capsules work (`web/src/character/capsules.ts`, `stage.ts` `linkGround()`)

- **Fit, once at load:**
  - Each skinned vertex goes to the group of its heaviest joint. There are 14 groups: torso, head, and per side the upper arm, lower arm, hand, thigh, calf and foot.
  - Hair, beard, brows, lashes, eyes and the mouth are skipped.
  - Each group gets a principal-axis capsule in its anchor bone's bind space. The radius is the 65th percentile of the distance to the axis; the segment runs from the 3rd to the 97th percentile along the axis, pulled in by r.
  - The fits are in `stats().ground.fits`.
- **Every frame:** the capsules move with `bone.matrixWorld`. They are written to two `uniformArray`s of 16 vec4, with a bounding sphere for an early-out.
- **Per floor fragment and per unshadowed light:**
  - The light is a rect (LTC). Each capsule is tested by the closest approach of the fragment→light-centre ray to the capsule's segment.
  - Coverage is the overlap of the capsule's angular interval with the rect's projected angular extent from that point, `(|ex·n| + |ey·n|)/dist`. Large lights therefore give soft shadows and long lights give long streaks.
  - Visibility is the product over capsules.
  - An equal-area disc penumbra was tried first and came out too soft: the long rim and kicker softened into blobs.
- **Wiring:**
  - The floor (`MeshStandardNodeMaterial`, no material of T21, T13d or H2) gets its own `lightsNode`.
  - Every light without a map is replaced there by a clone, `<name>_ground`, whose `shadow.shadowNode` is the capsule visibility node.
  - The key keeps its real map, and the character materials are untouched.
  - Lights: wrap, rim, kicker, fill, and the exported hair twins `rim_hair`, `kicker_hair` and `fill_hair` (§1.5).
- **Switch:** `floorshadow`, which is 1 in the gameplay tier and 0 in the hero tier; it can be given on the URL. Parameters: `ground.capsuleStrength`, `ground.capsuleRadiusScale` and `ground.capsuleSoftness` (all 1).

### 1.4 Only the floor changes

- Before against capsules, above the floor (rows < 640): mean 0.0165/255. That is TAAU history noise; the character is not touched.
- The texture LOD's change is separate (§2.4).

### 1.5 Finding: the floor is lit by the hair twins

The floor material has no `lightsNode` of its own in either tier, so it receives every light in the scene, the hair twins included:
- `rim_hair`, `kicker_hair` and `fill_hair` (exported) in both tiers;
- `key_hair` and `wrap_hair` (made by the viewer under `hairshadow=1`) in the hero tier.

This is why the hero tier's floor is brighter overall than the gameplay tier's (`g1_3m_signed_hero_minus_after_x8.png`: over the floor rows the hero tier is brighter by a mean of +3.9/255, and 71 % of the pixels by more than 2). It is also why the gameplay floor carries three `_ground` copies of twins: 3 of the 7 capsule lights shade the floor with light meant for the hair. It was not fixed here, because it changes the hero tier's floor (see *What's left*).

## 2. Gameplay texture LOD

### 2.1 Method (`web/tools/texlod.mjs`, run by the export)

- **Density per texture:** sqrt(UV area × W × H / world area) per triangle, area-weighted 90th percentile, over every primitive that samples the texture.
- **Target:** the gameplay camera at its nearest, 2.5 m with a 46° vertical field of view, puts 956 px of a 1080-line frame on 2.1 m, so 450 px/m. With a margin of 2 that is 900 texels/m, kept so that mip selection still has a level above the pixel rate.
- **Levels dropped** = floor(log2(density / target)), at most 4, never below 256 px.
- **Card materials** (`hair_cards`, `beard_cards`, `brows_cards`, `eyelash_cards`) keep 2 more levels, because `hair.idLodBias` samples them 2 levels sharper.
- **Filter:** a box filter in linear light for colour slots, renormalised for normal maps, plain for data.
- **Export:** `blender/character/export.py` `lod1()` now runs `lod1.mjs` on the PNG GLB, then `texlod.mjs`, then `ktx2.mjs` (when the hero KTX2 exists). The result, `character.lod1.ktx2.glb`, is the gameplay asset. Per-texture rows (density, from, to) go into `texlod.json`.

### 2.2 What it cut

| texture | density (texels/m) | hero tier | gameplay tier |
|---|---|---|---|
| `skin_head_{albedo,normal,orm}` | 8,358 | 4096² | 512² |
| `skin_hands_*` | 3,585 | 2048² | 1024² |
| `hair_cards_albedo` | 17,535 | 2048×4096 | 512×1024 |
| `beard_cards_albedo` | 11,790 | 2048×4096 | 1024×2048 |
| `eyes_{albedo,normal,orm}` | 20,401 | 1024² | 256² |
| `teeth` | 10,368 | 2048² | 256² |
| `suit_vest_normal` | 4,122 | 1024² | 256² |
| `suit_leather_*` (shoes) | 2,448 | 1024² | 512² |
| `suit_wool_{a,b}_normal`, wool albedo and ORM, shirt normal | 744–1,623 | as exported | **unchanged** (already at the target) |

The full list is in `g1-a2/texlod.json`; 41 textures were considered. The beard and hair aniso and ORM textures are already at density, so they are not cut. On RGBA8 with mips the textures drop from 632 MB to 147.5 MB, as a PNG decode would have them.

### 2.3 Texture memory per tier

Offline, from `web/tools/texmem.mjs`, which reads the KTX2 headers and DFD. It counts UASTC as ASTC 4×4 (1 B/texel) and ETC1S as ETC2 (0.5 B/texel, 1 with alpha), which is what KTX2Loader picks on the Air. Mips are included.

| asset | GLB textures (Air MB) | sidecars (skin/suit detail, curvature; Air MB) | total (Air MB) | RGBA8 + mips (MB) |
|---|---|---|---|---|
| hero tier, `character.ktx2.glb` | 98.2 | 17.1 | **115.4** | 430.7 |
| gameplay before, `character.lod1.ktx2.glb` (same textures) | 98.2 | 17.1 | **115.4** | 430.7 |
| gameplay after, texture-LOD `character.lod1.ktx2.glb` | 34.3 | 17.1 | **51.4** | 147.5 |

By group (Air MB, hero/before → after):

| group | MB |
|---|---|
| hair, beard, brow and lash cards | 37.1 → 11.4 |
| skin | 28.0 → 4.4 |
| suit | 22.9 → 18.3 |
| eyes, mouth, nails | 10.7 → 0.6 |
| sidecars | 16.8 → 16.8 |

Live, measured by the viewer (`TextureMemory`: every GPU texture's real format, mips and layers from the backend's `GPUTexture`; `stats().texture_memory`, in the HUD as `GPU MB`). SwiftShader picks the same formats as the Air.

| tier | sampled textures (MB) | of which LUTs and data (rgba32f/rgba8) | render targets and depth (MB) |
|---|---|---|---|
| hero tier (`heroA`, closeup) | 122.9 | 13.9 rgba32f + 10.2 rgba8 | 260 (incl. 5 shadow maps at 2048²) |
| gameplay before (`gpC2`) | 121.6 | 5.6 + 17.2 | 58.9 |
| gameplay after (`gpT`) | **57.6** | 5.6 + 17.2 | 58.9 |
| gameplay + `shadows=key,rim` (`gpM`) | 121.6 | | 67.3 (+8.4) |

The 17.2 MB of rgba8 is the skin and suit detail sidecars, two 1024² with mips plus arrays. They are the largest gameplay items left (*What's left*).

### 2.4 Picture and bandwidth

- **Picture:** at 3 m, full textures (`gpC2`) against reduced (`gpT`), same code:
  - full frame: mean 0.0148/255, 0.41 % of pixels > 1;
  - head crop: mean 0.233/255, max 28.
  - The head is slightly softer in skin micro-variation at 4×, and the same at 100 %.
- **Bandwidth, honestly:** at 2.5–8 m the GPU already samples mip levels at or below the new top level. Cutting the top levels therefore saves memory (64 MB of GPU memory on the gameplay tier, and 23 MB instead of 38 MB of download for the LOD1 GLB), but changes per-frame texture bandwidth very little by construction. The win is residency and load time, not frame time.

## 3. Texture-count audit (`web/src/character/texaudit.ts`)

- **How it counts:** `installTextureAudit` wraps three's node manager (`renderer._nodes.getForRender`). Every pipeline state the renderer builds is counted once from its generated WGSL: `: texture_*` declarations, excluding storage textures, per fragment and vertex stage. The texture names come from the state's bindings. This catches everything the shader really binds: the material's maps, the LUTs, every shadow map of every light the mesh receives, the screen textures (GTAO, contact) and array textures (one binding each).
- **Dev assertion, always on:** a pipeline over 16 raises `console.error` and a viewer warning naming the material, the object, the pass and the count, once per material and pass.
- **`?texcheck=1`:**
  - the HUD lists every material at 12 or more;
  - `stats().texture_audit` holds the full table (per material and pass, its maximum pipeline, the textures by name, the WGSL size and loop count), so a capture's `<prefix>shots.json` carries it;
  - `__viewer.textureAudit()` returns it at any time.

Sampled textures per material in the fragment stage, maximum over all its pipelines and views (front, hero closeup, portrait 480×270 and the gameplay framing; `auH_` and `auG_` with `texcheck=1`):

{{COUNT_TABLE}}

- **Eyes are T18b's.** G1 did not edit `eyes*`.
- **A lead for T18b:** `RectAreaLightTexturesLib.init()` runs in both `stage.ts` and the materials' `ltcTextures`. This gives two sets of LTC LUT `Texture` objects. The audit names unnamed textures by type and uuid, which shows the eyes binding 6 × 64² float LUTs. Deduplicating them might save bindings.

## 4. Added cost per tier

{{COST_TABLE}}

## Honest read

The gameplay tier now stands on its floor: analytic capsules give back the rim and kicker leg streaks and the sole contact that only the hero tier's five maps had. They add no pass, no texture binding and no map memory, and cost ALU on the floor alone. Texture LOD halves the gameplay tier's live texture memory (121.6 → 57.6 MB on the Air's formats) with no visible change at 3 m; it barely touches per-frame bandwidth, and the shadows' cost on the Air is still unmeasured because every millisecond here is SwiftShader. The audit shows the gameplay tier at most 13 textures per material, while the hero tier sits at 16 in its device-capture views and is over the limit only in the live portrait, the eyes being T18b's.

## What's left

- **Air numbers:** `air-session.md` step 4b, the floorshadow A/B and live texture memory on the device.
- **Floor and hair twins (§1.5):** give the floor a light list without `*_hair` twins in both tiers. That fixes the hero floor's double lighting and cuts the capsule ALU by 3/7, but it changes the hero tier's floor, so it needs a look-dev call.
- **Capsules under animation:** the fit is checked in the bind and hero poses only. A fast-motion turntable (and props, which are not in the fit) is m2 work. Feet near the floor could use a contact term on the capsule ends (`capsuleSoftness`).
- **Sidecars:** 17 MB of skin and suit detail and curvature are the same in both tiers. A gameplay-sized set (512²) would save about 12 MB.
- **Suit wool normals:** 2048², at density, so texlod keeps them. If T13d's tiling allows, a 1024² gameplay version would save 8 MB.
- **LTC LUT duplication (§3):** for T18b.

## Run dirs

- `data/build/lookdev/20261015T094709Z-g1-a1`:
  - symlinks to `20261015T045405Z-t17-a8`;
  - its own `character.ktx2.glb` (KTX2 encode, 418 s) and full-texture `character.lod1{,.ktx2}.glb`;
  - renders: `gpB_` (before), `gpC_` (disc penumbra, rejected), `gpC2_` (capsules, full textures), `gpM_` (`shadows=key,rim`), `heroB_`/`heroA_` (hero tier before and after G1) and `auH_` (hero audit).
- `data/build/lookdev/20261015T094709Z-g1-a2`:
  - the texture-LOD `character.lod1.glb` and `character.lod1.ktx2.glb`, `texlod.json` and `ktx2_lod1.log`;
  - renders: `gpT_` (after: capsules plus texture LOD), `gpK_` (`contact=1`) and `auG_` (gameplay audit).
- `data/build/g1/perf/P0..P3`: device captures (`gameplay_perf.json`): `floorshadow=0`, `floorshadow=1`, `shadows=key,rim`, `contact=1`.
- `data/build/g1/gate/`: the pictures.
