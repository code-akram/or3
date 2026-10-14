# m1 v4 track T9: hair and beard cards from the v4 groom (hair v4 steps 4 and 6)

_Track T9 report, 2026-10-14. Spec: `checkpoint-1.md` §3 T9, `fable_review.md` §5.3-5.5. Public build only (`bench/m1/variants/direction.json`), no fan overlay. Branch `worktree-agent-a964202d135e9ed01`, rebased onto main `9567bcc` (T7b), so the gate build includes T7b._

**Final build: `data/build/lookdev/20261014T145202Z-t9-c6`** (code = branch head before this report). **Cycles hero of the same build:** `data/build/hero/20261014T150639Z-t9-c6`. **Baseline:** main before T9, run `data/build/lookdev/20261014T131343Z-int1-main` (assets and parity copied to `data/build/t9/base`).

## Gate summary

| Metric | Before (main) | After (c6) | Target |
|---|---|---|---|
| Hair-region linear mean, engine / Cycles hero | **0.241** (0.061 / 0.252) | **0.978** (0.268 / 0.274) | 0.8-1.2 ✓ |
| Beard-region linear mean, engine / Cycles hero | **1.694** (0.312 / 0.184) | **1.147** (0.220 / 0.192) | 0.8-1.2 ✓ |
| Hair p50, engine vs Cycles | 0.025 vs 0.088 | 0.117 vs 0.109 | (info) |
| Beard p50, engine vs Cycles | 0.277 vs 0.146 | 0.142 vs 0.143 | (info) |
| EEVEE / Cycles, hair; beard | 0.513; 1.427 | 0.617; 0.940 | (info) |
| Hair + beard + brows tris | 29,554 (21,368 + 6,946 shells + 1,240) | **35,886** (22,942 + 11,952 + 992) | ≤ 40,000 ✓ |
| Model tris | 127,231 | 133,707 | |
| glTF validator | 0 errors, 16 warnings | **0 errors**, 16 warnings (same skinned-node warnings) | 0 errors ✓ |
| Facial gain hack | `facialHair.albedoGain` 0.45 + `linearFix` | removed (gain 1, no linearFix) | ✓ |
| Beard / brow shells in the GLB | yes | no (`shells.enabled: False`; code kept) | ✓ |
| Draw calls (viewer) | 129 | 117 (115 with the depth prepass off) | |

Parity method (`hair_test.py` parity part, T9 commit `1803851`): the closeup camera under the neutral rig. Cycles renders the hero strands (64 spp). The engine frame is `lin_closeup.png`, captured with `?view_transform=standard` and decoded to linear (÷ 2^-2.5 exposure). Regions are masks from the hero grooms: hair red, beard green (`hair_test/parity_regions.png`). Both runs are measured against their own build's Cycles strands.

## Pictures

- **Closeup, base | c6 | Cycles strands (neutral rig):** `data/build/t9/gate/closeup_base_c6_cycles.png`.
- **Linear closeup c6 | Cycles | regions:** `data/build/t9/gate/lin_closeup_c6_vs_cycles.png`.
- **Portrait, engine c6 | Cycles hero c6:** `data/build/t9/gate/portrait_c6_engine_vs_cycles.png`.
- Individual frames:
  - Engine: `…-t9-c6/{game_portrait,game_closeup,game_front,game_three_quarter,game_profile,lin_closeup}.png`.
  - Cycles: `hero/20261014T150639Z-t9-c6/{portrait,portrait_crop}.png` and `…-t9-c6/hair_test/parity_{cycles,eevee}.png`.
  - Baseline: `data/build/t9/base/{game_closeup,game_portrait,lin_closeup}.png`.
- Atlases (in the run dir): `hair_cards_{albedo,aniso,orm}.png`, `hair_cap_*.png`, `beard_cards_*.png`, `brows_cards_*.png`.

## What still reads wrong (candid)

1. **The front locks and temple cards are silver plates.** In the closeup and the portrait, the two front locks over the character's right temple, plus a few cards over the left ear, show as wide, flat, near-white ribbons. The highlight covers the whole card instead of a thin band. Causes:
   - The cards are wide and nearly planar to the key.
   - The KK tangent follows the card flow, so the whole plate sits at one highlight angle.
   - `layer_spec` 0.4 on the front locks only dims this.

   Likely fixes: narrower front-lock cards with more twist (2-3 crossing strips), or a per-pixel tangent jitter from the flow map's ID channel. This is the most visible defect.
2. **Colour distribution differs even though the mean matches.**
   - Cycles: the hair is mid-brown with a warm multiple-scattering sheen along the lengths.
   - Engine: a darker body plus bright white KK streaks. The means agree (0.98x) and so do the medians (0.117 vs 0.109), but the engine reaches them with more contrast.
   - KK has no multiple-scattering / TRT colour. A coloured second lobe (spec2 tinted by the albedo) is the next step, not more gain.
3. **Volume and silhouette.** The engine hair is flatter and more "wet-combed" than the Cycles groom. `top_lift` puts the top cards on the outer strands (p50 2.5 mm, max 9.2 mm), but the hero's width at the temples and its loose lengths over the shoulder are not reached. The flyaway cards (60) are too few and too thin at game resolution to read.
4. **Brows are too heavy.** The brow cards read darker, thicker and spikier than the soft Cycles brows. Brows have no parity region, so their tone is uncalibrated (albedo gain 1, strand_px 0.5, cell coverage p50 0.35). They need a brow mask in the parity part and a lighter, thinner bake.
5. **Beard: close, but:**
   - The jaw silhouette is a little spiky (fin cards under the jaw).
   - The cheek fade is a soft gradient in Cycles but a slightly ragged edge in the engine.
   - The beard is 15 % brighter than Cycles (within the gate).
   - Grey at the chin reads (grey share at the chin 0.44).
   - The moustache overhangs the lip.
6. **Hero portrait rig:** the engine hair takes the blue / magenta rims much more strongly than the Cycles hair (portrait sheet). The neutral-rig parity does not cover the coloured rims. Probably the same over-wide highlight as item 1.
7. **Hairline:** soft (cap core alpha follows root density, plus 139 hairline cards), but it is still the regular arc from the T8 groom.
8. **Hero strands still penetrate the skin after the Geometry Nodes:** 84 strand points per 20k are inside. This is now a stat (`strand_points_inside_after_gn_per_20k`). It is a Cycles / groom issue; the card vertices are pushed out after GN (3,490 hair, 5,381 beard, 677 brow vertices moved).

## 1. What was built

### Scalp cards (`blender/character/hair_groom_cards.py`, new raster `hair_strand_raster.py`)

The cards come from the evaluated groom: 48-point strands after GN clump / noise / frizz / trim.

| Layer | Cards | Tris | Source |
|---|---|---|---|
| cap (scalp shell) | 417 faces | | own angle-based unwrap; 23,857 groom strands projected onto it; core alpha from root density |
| under (volume / core) | 91 | 2,824 | half level-1 locks, set in toward the skull |
| mid | 197 | 7,672 | inner level-2 clumps |
| top | 195 | 6,636 | outer level-2 clumps, lifted onto the clump's outer strands |
| front + front_lock | 12 + 4 | 368 | front falls, on cells baked from the front falls' own strands |
| hairline / baby hair | 139 | 2,224 | hairline edge strands, farthest-point spaced groups |
| fly | 60 | 2,384 | the groom's stray hairs |
| **total** | | **22,942** | |

**Atlas `hair_cards`:** 2048 × 4096, cells 128 px wide.
- 10 lock cells, 2 front, 2 under, 2 fly and 4 hairline.
- **0.134 mm/px along a 0.55 m lock** (≥ 0.15 mm/px required).
- Each cell rasterises one representative clump in its card frame. Cell use and coverage are in the stats, and no cell is empty.

**Per-strand albedo:**
- Chiang colour from each strand's melanin / redness, path 0.68, so grey strands come out grey.
- Hair grey share 0.12.
- Tip alpha gradient, random colour 0.15, root dark 0.08, tip light 0.03.

**Maps** (GLB, `export.pack_hair_maps`):

| Map | Resolution | Channels | GLB slot |
|---|---|---|---|
| albedo | full | RGBA | |
| aniso | half | RG flow, A depth | `KHR_materials_anisotropy` texture |
| ORM | half | R AO, G roughness, B strand ID, A root-to-tip | occlusion + metallicRoughness texture (metallicFactor 0, roughnessFactor 1) |

- The hair, hair_cards, beard_cards and brows_cards materials all carry them.
- The old flow / data PNG sidecars are gone.
- KTX2 (`web/tools/ktx2.mjs`) compresses aniso / ORM as UASTC linear and albedo as ETC1S.

**Per-layer specular scale** (`layer_spec`): in UV1 u, because COLOR_0 alpha exported as VEC3. Front locks 0.4, under 0.7, others 1. The viewer reads it only when the strand maps are present.

### §5.3 defects

| # | Defect (v3 baker) | Fix | Check |
|---|---|---|---|
| 1 | Temple-bay streaks | cap baked from the strands on its own unwrap; no planar projection | closeup: no streaks |
| 2 | Near-empty cap texture | 23,857 strands drawn into the cap at 1024² over a density-alpha core | `hair.cap.strands_drawn` |
| 3 | atan2 seam / crown pole | angle-based unwrap with the seams cleared (one island set, no cylindrical UV) | no seam at the back / crown |
| 4 | Dead wisp cell, empty cell 4 | every cell has a role; stats list cards per cell and coverage | `hair.atlas.cells`, `empty_cells: 0` |
| 5 | `push_out` ran before GN | card vertices pushed off skin and suit after GN | `pushed_card_verts` 3,490; hero strands: stat 84 / 20k (not fixed, see item 8 above) |
| 6 | Cap UV vs the smoothed boundary | UV made on the final smoothed, offset cap | |
| 7 | Ribbons vs THICK | the scene curve shape is THICK (T8's render settings); recorded | `scene_curve_shape: THICK` |
| (8) | sRGB-swatch colour | per-strand Chiang colour, linear, same numbers as the hero BSDF | |

### Beard, moustache, brows (`beard_bake.build_groom_cards`, `hair_beard.game_cards`, `brows.py`)

**Beard: 1,992 cards / 11,952 tris** (2,048 centres, 2.6 mm spacing, 3 segments, 2-wide strips). Each card has its own 32 × 128 cell in a 2048 × 4096 atlas, rasterised from its own clump of groom strands.

| Stat | Value |
|---|---|
| Members per card (p10 / p50 / p90) | 14 / 48 / 62 |
| Card length p50 | 11.8 mm |
| mm/px along the strand, p50 | 0.092 |
| Cell coverage p10 / p50 | 0.31 / 0.61 |

**Growth:**
- Zone priority: 859 jaw / moustache / chin cards.
- Fins only under the jaw (normal z in [-0.95, -0.45]).
- Lying roll (12°) elsewhere; moustache roll 35°, so it overhangs the lip.

**Grey:** from the groom (beard grey share 0.21, chin 0.44).

**Under-layer** (`hair_beard.paint_underlayer`, also run in `beard_groom.refit`):
- Root density of beard + stubble (70,549 roots), rasterised into `skin_head_albedo` (4096²) and pulled toward the beard colour.
- Strength 0.85, gamma 0.7, blur 3 px.
- Gives the soft cheek fade and hides skin between the cards.

**Brows:** 248 cards / 992 tris, cells 32 × 64, 0.12 mm/px.

**Shells and lashes:**
- Beard and brow shells are off in the shipped GLB (`hair.beard.shells.enabled`, `hair.brows.shells.enabled` = False; the shell code is unchanged behind the flag).
- Lashes are unchanged (96 tris).

### Viewer (`web/src/character/materials/index.ts`, `params.ts`, `main.ts`)

**`HairMaterial`:**
- Reads the strand maps from the GLB slots (flow → tangent, ORM → baked AO / roughness / ID / root-to-tip, depth → depth AO).
- Lobe exponents scale with `(roughRef / roughness)²`.
- Per-card spec scale from UV1 u.
- `addHairDepthPrepass` adds depth-only twins of the alpha-tested hair (prepass alpha 0.85) to reduce sorting noise. It costs 2 draws.

**Removed:**
- The sidecar loader (`HairSidecars`, hair_atlas flow / data PNGs).
- The `linearFix` block.
- The `facialHair.albedoGain` 0.45 hack (now 1).

**`engine_shots`:**
- Reports `hair_maps` and `hair_prepass`.
- Default port is **8796** (outside 8790-8793).
- `ENGINE_PORT` env override.

## 2. Budget: why ≤ 40k and this split

Hair + beard + brows = **35,886 tris** (+96 lashes). The gate's ceiling is 40k; this leaves about 4k of headroom, for example for the front-lock rework in item 1.

- **Hair 22.9k (+1.6k vs v3):**
  - The layered build needs under / mid / top over the whole head to hide the cap at three-quarter angles.
  - mid + top (14.3k) carry the silhouette.
  - Hairline (2.2k) and fly (2.4k) are the cheap layers that break the edge.
  - The wide front-lock cards (only 368 tris) are exactly where it still reads as plates, so any savings should not come from widening cards.
- **Beard 12k (+5k vs the shells):**
  - At 1,024 cards (c2) skin showed through, and the region measured 0.81x Cycles with the albedo at black.
  - 2,048 cards at 2.6 mm spacing is the density at which the under-layer plus cards cover the skin at closeup distance.
  - The shells they replace were 6.9k and did not follow growth.
- **Brows 1k:** 256 short cards, about the old shell cost.

## 3. Calibration (parity path)

All values were calibrated in the engine against the Cycles strands with the parity metric (sweeps via `?params=`), not by eye.

- **Beard albedo gain 0.35** (`hair.beard.game_cards.albedo.gain`, in the bake, not the viewer):
  - Cards have no strand-volume self-shadowing; the hero beard is about 50 strands deep.
  - At gain 1 the beard measured 2.3x Cycles.
  - This is a physical compensation for the missing volume, applied to the baked colour. It is documented in config and replaces the viewer-side gain hack.
- **Facial-hair lobes:** spec1 0.01, spec2 0.012. The beard's short cards facing the camera otherwise catch a broad highlight Cycles does not show.
- **Scalp-hair lobes:**
  - Exponents 60 / 12, spec1 0.19, spec2 0.07, roughRef 0.55.
  - Root AO 0.45 (ORM A), baked AO 1, depth AO 0.2.
  - Narrow lobes reproduce the highlight tail of the Cycles mean.
  - Spec was set after the per-layer spec scale (it dropped hair to 0.73x; 0.19 / 0.07 restores 0.98x).
- **Atlas albedo path 0.68** (Chiang colour at a 0.68 path length) for hair, beard and brows. This is a single-scatter approximation of the hero BSDF's colour; the shortfall against the hero's warm multiple scattering is item 2 above.

## 4. Texture memory (hair + facial groups)

GPU estimate: PNG = RGBA8 + mips; KTX2 = 1 B/texel + mips (BC7 / ASTC 4×4 targets). Tool: `texmem.py` over each GLB.

| | Before (main) | After (c6) |
|---|---|---|
| PNG GLB, hair | 46.1 MB + flow / data sidecars (2048², separate PNGs) 44.7 MB | 75.5 MB (6 textures, maps included) |
| PNG GLB, facial | 53.4 MB | 71.3 MB (6 textures) |
| **PNG, hair + facial** | **≈ 144 MB** | **≈ 147 MB** |
| KTX2, hair | 11.5 MB + the PNG sidecars 44.7 MB (the sidecars were not in the GLB, so not compressed) | 18.9 MB |
| KTX2, facial | 13.3 MB | 17.8 MB |
| **KTX2, hair + facial** | **≈ 69.5 MB** | **≈ 36.7 MB** |
| GLB file size, PNG | 69.5 MB (images 61.6 MB) | 88.3 MB (images 79.4 MB) |
| GLB file size, KTX2 | 32.4 MB (images 24.5 MB) | 41.4 MB (images 32.5 MB) |

- The maps are now in the GLB and compress with it. On the KTX2 path, hair + facial GPU memory roughly halves.
- The download grows by 9 MB: the new beard atlas is 2048 × 4096 with unique cells, where the shells were 2048 × 3584.
- KTX2 hair file bytes 6.1 MB; facial 7.7 MB.

## 5. Engine frame time (informational)

These are headless SwiftShader numbers (`engine_shots.mjs --serve --selftest`, `perf=12`, closeup, 640 × 360, CPUs 0-3, shared machine). They are CPU-rasterised and noisy, so only the order of magnitude and the draw / tri counts mean anything. A GPU measurement is still owed.

| Build | Frame p50 / p95 ms | Draw calls | Triangles rendered |
|---|---|---|---|
| base | 2,235 / 2,982 | 129 | 784,756 |
| c6 | 1,787 / 1,857 | 117 | 825,186 |
| c6, depth prepass off | 1,653 / 1,670 | 115 | 802,244 |

The prepass costs about 8 % here (2 draws, about 23k tris). Draw calls drop by 12 because the shell layers are gone. That c6 is faster than base on more triangles is most likely the shells' overdraw going away, but SwiftShader numbers are not reliable enough to claim it.

## Runs

| Run | Use |
|---|---|
| `lookdev/20261014T131343Z-int1-main` (= `data/build/t9/base`) | before |
| `lookdev/20261014T134750Z-t9-c1` … `20261014T143618Z-t9-c5` | iterations: first v4 cards, beard density, fins, under-layer, beard gain, top lift, front cells |
| `lookdev/20261014T145202Z-t9-c6` | **final**, rebased on T7b |
| `hero/20261014T150639Z-t9-c6` | Cycles hero portrait of the final build |
| `t9/ktx/{base,c4,c6}.ktx2.glb` | KTX2 copies for texture memory |
| `t9/perf/{base,c6,c6np}` | perf copies (the selftest writes into its build dir) |
| `t9/gate/*.png` | comparison sheets |

## Commits

| Commit | What |
|---|---|
| `1803851` | parity part (engine vs Cycles strands by groom region), engine `view_transform=standard`, `ENGINE_PORT` |
| `ff1cc9f` | v4 cards from the groom, strand maps in the GLB, facial hair as cards |
| `7b747bd` | top lift, denser beard, jaw-only fins, darker under-layer, engine_shots port 8796 |
| `5c9b4f9` | beard gain 0.35, facial lobes |
| `fa9d986` | front-lock cells from the front falls; post-GN penetration stat |
| `161dda4` | per-layer spec scale (UV1 u) |
| `8ead47c` | hair lobes 0.19 / 0.07 |
| (this commit) | report, docstring |
