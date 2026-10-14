# m1 v4 track T12: skin mid-frequency, hero hair colour, eye-band margin

_Track T12 report, 2026-10-14. Brief: `checkpoint-2.md` §1 (skin, hair and eyes rows), §4 row T12 and the housekeeping paragraph. Public build only (`bench/m1/variants/direction.json`); no fan overlay. ArcFace was run in private and printed one number per image._

**What I see in my own frames, viewed at 100 %.**
- In the Cycles portrait crop, the forehead now has fine horizontal lines and a broken sheen, and the eye sockets read darker and more recessed than in T9b. The cheeks and the nose are still smooth at that distance and depth of field, so the new mid band shows only where the key rakes: the forehead and under the eyes.
- In the engine closeup, the periorbital ring and the upper-lid crease are darker. The forehead highlight is broken into patches instead of one glassy sheet, and there is a faint crepey texture under the eyes. A slight warm-pink tint is left on the lower lid of the far eye.
- The hero hair is a little less ginger on the lengths beside the face, and the metric passes (r/g +7.5 % of main9). It still reads dark brown with a mauve rim, not the blue-black of main9. The game hair in the engine is still light brown, because the hair cards carry their own albedo constants (leftover 1).

**Final build:**
- `data/build/lookdev/20261014T184620Z-t12-b2`: on main after the T11 merge (`fce1aa8`).
- Cycles hero: `data/build/hero/20261014T185633Z-t12-b2`.
- `t12-b1` (`…/20261014T183044Z-t12-b1`, hero `…/20261014T184148Z-t12-b1`) is the same T12 code before the merge. Its metrics isolate T12's own effect.

**Before:**
- T9b final: `…/lookdev/20261014T155504Z-t9b-b1`, hero `…/hero/20261014T161745Z-t9b-b1`.
- main9 hair reference: `…/hero/20261013T081828Z-main9-final`.

## Gate

| Metric | Target | Before (T9b b1) | T12 b1 (pre-merge) | **T12 b2 (on main + T11)** |
|---|---|---|---|---|
| read40 eye band darker | ≥ 0.80 | 0.7547 (main after T11: 0.7679) | 0.8057 | **0.8163** ✓ |
| eye aperture | 8.5–9.5 mm | 9.0 | 9.0 | **9.0** ✓ |
| Hero hair r/g, portrait crop, graded PNG (main9 1.284) | within 10 % of main9 (≤ 1.412) | 1.452 (+13.1 %) | 1.380 | **1.380 (+7.5 %)** ✓ |
| The same, scene-linear EXR (main9 1.914) | (info) | 2.06 (+7.6 %) | 1.994 | **1.994 (+4.2 %)** |
| Hair test p10 (T8 base 0.0157) | ≥ 2× = 0.0314 | 0.0383 | 0.0367 | **0.0367 (2.34×)** ✓ |
| ArcFace cosine vs the private reference median, EEVEE closeup / engine | ≤ 0.25 | 0.103 / 0.062 | 0.076 / 0.052 | **0.034 / 0.029** ✓ |
| Head measures (`spec ... out`) | all in range | 0 out | 0 out | **0 out** ✓ |
| glTF validator | 0 errors | 0 errors, 16 warnings | 0 / 16 | **0 errors**, 16 warnings ✓ |
| Tris | unchanged | 133,799 | 133,799 | 133,683 ✓ (brows 992 → 876 is T11's; every T12 part is unchanged) |
| Textures | unchanged | 40 images | 40 | 40, same sizes ✓ |
| GLB bytes | (info) | 88.27 MB | 89.99 MB | 87.76 MB |
| Face roughness, mean / std | 10–20 % structure | 0.516 / — | 0.518 / 0.0617 (11.9 %) | **0.518 / 0.0617 (11.9 %)** ✓ |
| Crisp residual in `hgt` (5.6 M head texels), p1 / p99 | (info) | — | −0.19 / +0.60 mm | −0.19 / +0.60 mm (clamped ±0.8) |
| AO in albedo | none | 0 | 0 | 0 ✓ |

Head measures on b2:
- aperture 9.0 mm;
- canthal tilt 3.14°;
- orbit recess 2.38 mm;
- brow overhang 9.1 mm;
- forehead behind brow 6.85 mm;
- gonial 119.7°;
- bizygomatic 0.142 m;
- lower-face index 0.857;
- jaw / cheek 0.875.

### Notes on the gate

- **What the eye-band numbers measure.** b1 is T12 alone: +0.051 over T9b. T11's darker brow under-layer adds another ~0.01 on top (b2).
  - On the a2 GLB, the T12 rings alone gave 0.8038–0.8058, depending on `orbit_rgb`.
  - The margin over 0.80 is thin when T12 stands alone (see leftover 2).
- **Hair r/g.**
  - The primary number is the graded PNG, the picture the brief compares.
  - The EXR number is scene-linear before the grade; it is reported for completeness.
  - Boxes are fixed in the 960 × 540 crop: crown, the two side lengths and a forehead normaliser (scratch `/tmp/t12/hairrg.py`). They are the same boxes for every run.
- **Roughness std.**
  - Without the T12 structure terms (`rough_patch`, `rough_mid`, `rough_line` and `rough_orbit` at 0), the same bake gives std 0.054 (10.4 %).
  - The structure terms are zero-mean over the skin, so the face mean is unchanged: 0.516 → 0.518.
- **ArcFace** went down: the authored face moved further from the reference. It printed one scalar per image; no private file was viewed.

### T9b hair parity, re-checked

Method: engine `lin_closeup` against the Cycles hero strands, `hair_test.py --parts parity`, gate ±20 %.

| Region | T9b b1 | T12 b1 | T12 b2 |
|---|---|---|---|
| Hair, engine / Cycles | 0.936 | 1.012 | **1.012** ✓ |
| Beard | 1.090 | 1.084 | **0.965** ✓ (T11 beard) |
| Brows | 1.031 | 1.029 | **0.867** ✓ (T11 brows) |
| Hair r/g, closeup: Cycles / engine | 1.51 / 1.44 | — | 1.471 / 1.423 |

- **Why hair parity moved toward 1.0.** The hero strands lost the lighter tips, and the game cards take the groom's per-strand redness, so both sides moved.
- **Beard and brows.** Their b2 numbers are T11's work, unchanged by T12.

## Pictures (all public, in `data/build/t12/gate/`)

- `detail_strip_before_after.png`: `detail_strip.png`, T9b b1 (top) vs T12 b2 (bottom).
- `portrait_crop_before_after.png`: Cycles `portrait_crop.png`, T9b b1 | T12 b2, at 100 %.
- `portrait_crop_main9_t9b_t12.png`: the same crop stacked, main9 / T9b / T12, for the hair colour.
- `engine_closeup_before_after.png`: engine `game_closeup.png`, T9b | T12 b2.
- `engine_face_crop_before_after.png`: the same, the face at 100 %.
- `read40_before_after.png`: the read40 frames.

Individual frames:
- `…/lookdev/20261014T184620Z-t12-b2/{detail_strip,closeup,read40,game_closeup,lin_closeup}.png`;
- `…/hero/20261014T185633Z-t12-b2/portrait_crop.png`, with `exr/portrait_crop.exr`;
- `…-t12-b2/hair_test/parity_*`.

## (a) Skin relief at portrait distance

The hero material displaces `hgt_hero` (Cycles true displacement on adaptive subdivision). It does not read the game normal map. So every layer below goes into both heights: `hgt_game`, from which `skin_head_normal` is baked, and `hgt_hero`.

**Sculpt crisp band** (`skin_tex.py`: `crisp_vertex`, `crisp_texels`).
- **Source.** The sculpt layer's sharp − soft field, the "crisp band" `head_sculpt.fields`, is evaluated per vertex. The ear points are prepended so that `ear_front` resolves the same ear.
- **Baking.** It is encoded into a vertex attribute and baked to texels.
- **What is added.** The **residual** that the dense mesh does not already carry: the field minus the vertex-interpolated value.
- **Limits.**
  - It is limited to the head (texels within 0.17 m of the head centre) and clamped to ±0.8 mm.
  - It is excluded on the lids, where it fought the lid shading.
  - Without the head limit there were spikes of up to 10 mm at the legs, from a stray selection weight.

**Mid band, 0.5–3 mm** (`skin_synth.py`).
- **Noise.** A new noise set, `noiseH`: noise at 450 and edge at 600, plus an anisotropic 330.
- **Pore clusters.** The pore field is modulated by a cluster mask, `pore_cluster` 0.5, so pores come in patches instead of an even grain.
- **Fine lines.**
  - forehead: broken zero crossings of a low-frequency field, 0.08 mm;
  - crow's feet: 9 extra radiating lines per side, 0.08 mm;
  - nasolabial: 2 lateral lines, 0.05 mm.
- **Under-eye.** `crepe_mm` 0.02 → 0.03.
- **Mid texture.** A texture plus cell layer, 0.06 / 0.015 mm. It is weighted to the cheek, nose, forehead, chin, temple and neck, and reduced on the lids and under the beard.
- **Hero gain.** `hero_mid_gain` 1.5 scales the mid texture and the fine lines in `hgt_hero` only. The Cycles portrait's depth of field and distance swallowed them at 1.0.

**Roughness structure.**
- Three terms:
  - a patch term from the lump field;
  - a mid-texture term;
  - a fine-line term.
- They are made zero-mean over the skin, so the face mean stays at 0.518. Std is 0.0617, about 12 % of the mean.

**Lip seam and soft vermilion.** v3's lip seam (0.5, 0.7 mm) and soft vermilion edge (0.6 mm) are now on in `direction.json`. They help a little in the detail strip: the lip line is defined without a hard edge.

**No AO in the albedo.** `ao_in_albedo` is 0.0 in `direction.json`.

## (c) The eye band: a bug, then a periorbital ring

**The bug: the eye rings were drawn around the wrong centre.**
- In a1, the socket and lid tints changed nothing: read40 was identical to T9b.
- `Frame` placed the socket and lid rings using `head_refine.eye_centres`. That centre sits **5.7 mm in front of the shipped `eyes_hq` globe** (globe centre y −0.13874, z 1.73075, r 12.0 mm).
- The rings therefore landed outside the lids.

**The fix.**
- `skin_tex.eye_spheres` takes the shipped globe centres and radii: from the sculpt state, or else a back-half sphere fit of the eye mesh.
- `Frame` measures `eye_d` as the distance to the nearest globe surface (`EYE_LID_REF` 16.8 mm, `EYE_LID_GAP` 0.6 mm). With that, `socket_dark` 1.6 and `lid_dark` 1.3 land on the lids.

**A periorbital ring** (`R["orbit"]`, `orbit_dark` 1.0) at 17.5 ± 3.5 mm from the globe surface.
- **Colour.** It has a neutral, slightly cool `orbit_rgb` (0.68, 0.63, 0.64). The first colour, (0.86, 0.80, 0.84), read pink on the lids.
- **Darkening must come from the colour.** `tint()` clips its weight to [0, 1], so `orbit_dark` > 1 does nothing.

**What the band still measures.** At 48 px, the eye-band box is mostly sclera and brow, so the skin rings move it only so far: T12 alone gives 0.806.

## (b) Hero hair toward near-black

**The brief's lobes, tried.** Chiang roughness 0.30–0.36 with radial 0.4 fails the hair test:
- p10 is 0.0218, 1.39× the T8 base; the gate is 2×;
- it moves the portrait r/g by only about 4 % (1.452 → 1.399).

Narrowing the lobes darkens the highlight-free hair, which sets p10, but does not remove the warmth. **The ginger lengths came from the colour, not the lobes:**
- the lightened tips (`tip_light` 0.03 lowers the melanin toward the tip);
- the pheomelanin (`redness` 0.10).

**Variants** were tried on the a1 blend (`/tmp/t12/hairvar.py`), each with a Cycles hero render and the hair test:

| Variant | PNG r/g | p10 |
|---|---|---|
| a1: lobes 0.30–0.36, radial 0.4, redness 0.10, tips 0.03 | 1.399 | 0.0218 |
| redness ×0.4, radial 0.3 | 1.362 | 0.0213 |
| A: lobes 0.36–0.45, radial 0.5, tips 0, random 0.08 | 1.412 | 0.0328 |
| C: lobes 0.34–0.42, radial 0.5, redness ×0.4, tips 0, random 0.08 | 1.381 | 0.0322 |
| **D (shipped): T8 lobes, redness 0.04, tips 0, random 0.08** | **1.381** | **0.0367** |

**What shipped** (`config.py`, `hair.groom.shader`):
- `redness` 0.04;
- `tip_light` 0.0;
- `random_color` 0.08;
- melanin unchanged at 0.90;
- the T8 lobes kept.

**Effect.** The side lengths' luminance relative to the forehead went 0.124 → 0.112 (main9 0.082).

## (d) Housekeeping

- The v2 identity files are now at the default paths, `data/build/identity/{public_face,base_embedding,ict_embedding}.npz`. v1 is kept in `identity/v1/`, and `identity/v2/` is left in place.
- `direction.json` reads the default paths, and its `head.sculpt.embedding` v2 pointer is dropped.
- A fresh build finds the delta: a2, b1 and b2 all report `head_layer` source `identity` with base drift 0.0 mm.

## Leftovers and notes

1. **The game hair cards are still light brown in the engine.** The cards take the groom's per-strand redness (so 0.04 reached them), but they keep their own albedo constants in `hair_groom_cards.py` `CARDS.albedo`: `random_color` 0.15 and `tip_light` 0.03. T15 or the card owner should mirror the new shader there (`tip_light` 0, `random_color` 0.08) and recheck the engine's hair tone. That file was outside T12's scope.
2. **The eye-band margin is thin and dominated by the sclera and brows.** It is 0.806 for T12 alone and 0.816 with T11. Any brighter sclera or lighter brow will push read40 back under 0.80. Skin darkening alone has little left to give without the lids going grey or pink.
3. **The hero hair is "within 10 %" but not near-black.**
   - The remaining difference from main9 is mostly lightness on the side lengths and the mauve rim, not hue.
   - Going further means more melanin, which the brief kept fixed at 0.90, or a lighting change.
4. **The mid band is subtle in the Cycles portrait.** The portrait's depth of field and distance swallow most of it.
   - It shows on the forehead and under the eyes, and in the engine closeup and the detail strip.
   - The cheeks still read smooth at portrait distance.
   - A further step would be more `hero_mid_gain`, or detail in the albedo and specular rather than the height.
5. **Data.**
   - `data/build/identity/v1/` is a backup of the pre-promotion files.
   - `data/build/t12/bake_cache_a2.npz` (1.8 GB) is the cached head bake inputs for the offline synth preview (`SKIN_BAKE_CACHE`); it can be deleted.
   - The variant `.blend` files were deleted; their renders are kept.
6. **Leftover tint.** A faint warm tint on the far eye's lower lid in the engine closeup remains; a later lid pass could neutralise it.

## Code and tools

- `blender/character/skin_tex.py`: the crisp band (`crisp_vertex`, `crisp_texels`, `CRISP_ENC`, `CRISP_MAX`), `eye_spheres`, `noiseH` and `attr3` bakes, `roughness_face_std` and `crisp` stats, and the `SKIN_BAKE_CACHE` dump.
- `blender/character/skin_synth.py`:
  - globe-based `Frame`;
  - the `orbit` ring;
  - pore clusters;
  - fine lines;
  - the mid texture;
  - `hero_mid_gain`;
  - zero-mean roughness structure;
  - new `DEFAULT_HEAD` keys.
- `blender/character/config.py`: `hair.groom.shader` only.
- `bench/m1/variants/direction.json`: identity paths and `head.refine.skin.head`.
- Scratch tools (not committed) are in `/tmp/t12/`:
  - `preview.py` / `pv.sh`: offline synth from the cache;
  - `read40.py`: the read40 harness on a GLB with swapped maps;
  - `hairrg.py`;
  - `hairvar.py` / `hv.sh`.

## Commits (branch `worktree-agent-ae8d25b76a0841390`)

| Commit | What |
|---|---|
| `2634a20` | housekeeping: promoted identity paths |
| `ddcc6e1` | wip: crisp residual, mid band, sheen structure, lip seam and soft vermilion |
| `aa1aa5f` | wip: eye rings from the globe centres, periorbital ring, crisp clamp, zero-mean structure |
| `9a2a764` | hero hair colour by tips and pheomelanin, neutral orbit ring, hero mid gain |
| `4ce8374` | merge main (T11) |
| (this) | report |
