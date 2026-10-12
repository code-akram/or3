# m1 v2 Track B: scalp hair (strand groom + game cards baked from it)

_2026-10-12. Brief: `bench/m1/v2/BRIEF.md`; art direction: `direction.md` §2 Track B. Builds on the frozen Track A head (main 8fa40c6); rebased on main a5ea570 (Track F deform, Track D suit v2; a dev build on it, `20261012T220315Z-hairB-rebaseD`, gives the same hair numbers: 21,068 tris, temple break 35 / 36 mm, width 1.345, and the lengths sit over the new collar). Revised after the orchestrator review of `hairB-final` (round 2, below)._

## What it is

The scalp hair is now a **strand groom** that is the source of truth for both versions:

| | Hero (Cycles, `hero_only`) | Game (GLB) |
|---|---|---|
| Module | `blender/character/hair_groom.py` | `blender/character/hair_groom_cards.py` |
| Geometry | Blender hair curves: 520 guides → 40,000 strands × 24 points + 1,400 vellus hairs (4 points), 965,600 control points | 484 cards (72 under, 180 mid, 180 top, 12 front-fall, 40 flyaway) + the scalp cap: **21,088 tris** |
| Detail | Geometry Nodes modifier `hair_groom` built from the bundled **CC0 Essentials** hair node groups: noise → primary clump → secondary clump → frizz → flyaway noise → trim | atlas 2048², 12 lock variants rasterised from the evaluated groom strands; cap texture rasterised from the groom's hairline strands |
| Shading | Principled Hair BSDF, **Huang**, melanin per strand (0.95, minus up to 0.04 per lock; 10 % lighter strands at 0.8; vellus 0.7), redness 0.3, roughness 0.22 root → 0.30 tip (Hair Info intercept), random colour 0.08, random roughness 0.1, IOR 1.55 | Principled: albedo atlas × COLOR_0, alpha MASK, tangent-space normal atlas (strand cylinders), roughness 0.55, specular 0.25, no anisotropy |
| Binding | Curves object parented to the `head` bone; a hero-only scalp tint shell (skinned like the cap) | skinned; 14 spring bones (back 2+2, side 3+3, front_r 2, front_l 2) |

Licence check (asked in the prompt): `/usr/share/blender/5.2/datafiles/assets/LICENSE` is **CC0 1.0** for the whole bundled asset library, so the Essentials hair node groups (`procedural_hair_node_assets.blend`) are usable, also for baked output that ships. Recorded in `provenance/mesh.jsonl` (`blender:essentials/procedural_hair_node_assets`, sha256 of the file); audit 0 errors.

## Construction

### Groom (`hair_groom.py`, defaults in `hair_groom.DEFAULTS`, config `hair.groom`)

1. **Growth surface and hairline field.** The hair_clumps growth region (MPFB `scalp` + temple and nape bands) as triangles. `Surface.d_eff(p)` = distance to the region's open boundary minus a **temple recession** (two Gaussian bays at ±44° azimuth, 9 mm deep, σ 13°, gated above the ears). `d_eff < 0` is bare skin. Everything is sampled on this surface; nothing is a fixed coordinate, so the rebuild on Track A's frozen head needed no change.
2. **Guides.** 520 roots by farthest-point sampling over the surface, each marched by `hair_clumps.march` (comb back from the part, ear ellipsoids, tuck behind the ears, gravity, skin and suit colliders), with groom overrides: `cling` 0 (the lengths hang with volume instead of leaning in to a rope behind the neck), ear margin 8 mm, a **soft part** 12 mm left (push 0.25 decaying over 2 cm, the part line wandering ±2 mm, a 4 mm lift next to it), a **volume profile per root** (stand-off from the skull rising over 5 cm, held 7 cm, decaying to 75 % over 14 cm, ×0.7–1.0 per guide): 14 mm off the forehead, a flatter crown (8 mm), **36 mm on the sides** and 26 mm over the occiput. A shorter rise (3.5 cm) left the first centimetres of the side strands leaving the skin at ~40°, which reads as a blow-dry in the groom and as louvres in the cards. Resampled to 24 points (point 0 buried upstream, point 1 at the root).
3. **Strands.** 40,000 roots area-uniform with a **density ramp over the 10 mm feather** (8 % at the hairline → full). Each strand blends its 4 nearest guides (never across the part), translated to its root, then is pushed ≥ 1.2 mm off skin and suit. A **lock wave** (4–8 mm, 12–18 cm period, phase per primary clump) in the hanging part.
4. **Clumps** (curve attributes, read by GN): 10 % strays (no clumping); 36 primary centres (farthest-point, same side of the part) and 360 secondary centres inside them. A per-point **clump ramp**: 0.2 while the strand lies on the skull, full 6 cm past its hang point, so the swept-back top stays combed and the lengths separate into locks.
5. **Front falls**: three on the character's right (360 strands each, clump 0.75, 5 mm wave, 5 mm clearance, low hug so they hang a little off the temple) crossing the temple, ends at the cheekbone (4.5 cm above the lips); one lock (260 strands, clump 0.75) from just left of the part, combed sideways and forward with reduced gravity (0.55), so it falls **diagonally** across the forehead to the outer left brow.
6. **Flyaways**: 4 % of strands, weighted to the silhouette (sides, back) and the part, 10 mm noise in GN, half clumping.
7. **Vellus**: 1,400 hairs, 3–6 mm, along the whole hairline (`d_eff` −2…6 mm), flat to the skin (lift 0.35), radius 0.018 mm, lighter.
8. **GN modifier** (`hair_groom` node group, every input editable in the .blend): Hair Curves Noise (1.5 mm, scale 40) → Clump (primary, factor 0.85 × clump_w × clump_ramp, `guide_curve_index`) → Clump (secondary, factor 0.8, `sub_guide_index`) → Frizz (0.5 mm) → Hair Curves Noise (flyaways, factor = `fly`) → Trim (random 5 %). Checked numerically: the clump stages pull members from 15.6 → 7.3 mm (primary) and 7.1 → 2.2 mm (secondary) of their guides in the hanging part.
9. Strand radius 0.045 mm at the root → 0.02 mm at the tip (direction values).

### Game cards (`hair_groom_cards.py`, defaults in `CARDS`, overrides in `hair.groom.game`)

- **From the evaluated groom** (after GN; point counts verified unchanged): one card per secondary clump (mid = inner half by stand-off, top = outer half), two per primary clump (under, split across the width, starting 20 % along the clump so their dense dark roots never show at the temple), one per front-fall sub-clump, 40 flyaway strips along the groom's flyaway strands (not round the ears). The card path is the clump's mean strand; the half-width is the 92nd percentile of the strands' spread across the card + 1.8 mm (smoothed), so neighbours overlap; taper to 45 %; roots narrow (25 %) near the hairline, 80 % further back; cards rooted within ~2 cm of the hairline take a sparse cell, widen slowly and get only 8 % root darkening; 3 vertices wide with a rounded profile.
- **Atlas** (12 cells, 6 × 2 of 329 × 1012 px usable): 8 secondary clumps (sparse to dense), 2 primary clumps, 1 flyaway cell, 1 hairline wisp. Each cell rasterises the clump's actual strands in its card frame (u = offset across / half-width, v = centreline arc + offset along the tangent, so roots stagger and trimmed tips end early; depth along the normal), 3× supersampled and z-buffered. Written as `hair_atlas_albedo` (RGB, A coverage), `hair_atlas_data` (R coverage, G root-to-tip, B strand ID: the threejs-hair-shader layout), `hair_atlas_flow` (RG flow with ±15° per-strand jitter, B depth, A AO), `hair_atlas_normal`; packed in the .blend and saved as PNGs next to the GLB. The GLB carries albedo + alpha + normal (glTF has no slot for the data / flow maps).
- **Cap**: the scalp shell (hair_clumps' construction) with its UV v measured from the groom's **recessed** hairline; its texture is rasterised from the groom's strands and vellus rooted in one 6 cm window of the front hairline (near-skin parts only), over a dark core that fills in as staggered streaks (an alpha ramp would cut a hard line under MASK).
- **COLOR_0**: layer AO (under 0.8, mid 0.82, top 1.0, front 0.9, flyaway 0.85) × per-lock lognormal value × **35 % root darkening** over the first 30 % of v (8 % near the hairline, none on under cards).
- **Smooth-proxy normals**: the groom's points → Points to Volume (4 mm voxels, 8 mm radius) → Volume to Mesh → Laplacian smooth; Data Transfer (custom normals, nearest face interpolated) onto the card vertices, applied as the first modifier.
- **Springs**: hang distance and sector per card vertex from the clump's strands → `hair_springs.bind` (unchanged). Pose test `hair_springtest.py` passes (masses swing, no tearing).
- The card object is `hide_render` in the kept .blend (the hero stage renders the groom); the exporter ignores render visibility, so the GLB keeps it.

## Numbers (final run `data/build/lookdev/20261012T213651Z-hairB-final2`, `bench/m1/variants/direction.json` with the head refine)

| | Baseline (m1 sign-off) | first v2 (`hairB-final`) | **v2 after review (`hairB-final2`)** |
|---|---|---|---|
| Hair tris | 27,548 | 23,432 | **21,088** (under 2,668, mid 7,900, top 8,200, front 232, fly 1,272, cap 816) |
| Cards | – | 541 | **484** (72 under, 180 mid, 180 top, 12 front, 40 fly) |
| LOD0 total | 124,614 | 124,095 | 121,751 |
| Bones / max weights / validator errors | 66 / 4 / 0 | 68 / 4 / 0 | **83 / 4 / 0** (Track F's helper bones from main; 15 warnings, the known non-root skin ones) |
| Groom | – | 36 / 417 clumps | 40,000 strands + 1,400 vellus, 520 guides, 1,340 front-fall strands, 36 primary / 360 secondary clumps, 3,792 strays, 1,600 flyaways |
| Tip z p10 / p50 / p90 (cards) | 1.540 / 1.560 / 1.575 | 1.574 / 1.582 / 1.592 | 1.574 / 1.583 / 1.594 (collar top ≈ 1.58) |
| Width / skull at eye level (≤ 1.35) | 1.18 | 1.11 | **1.344** |
| Side break beyond the cap (≥ 30 mm) | – | 45 / 106 mm widest band; 13 / 13 mm at the temples | **70 / 73 mm** widest band (z 1.68); **35 / 36 mm at temple level** |
| Cap edge over the refined skin (`hair_fit.py`, ring 0 / 1 p50) | 0.50 / 1.24 mm | 0.60 / 1.25 mm | 0.55 / 1.25 mm (2 of 202 edge verts ≤ 0 mm) |
| Hair verts > 0.5 mm under the skin | 8.2 % | 10.6 % | 8.3 % |
| Collar zone within 1.5 mm of the suit | – | – | 30 of 2,191 verts (1 %) |
| hair_post time | ~5 s | 29 s | 36 s at load ~12 |
| Spring test (`hair_springtest.py`) | ok | ok | ok (masses swing at 35°, no tearing) |

`read40` eye band reads 0.67 (fail) on this full build (0.65 on the first); every full (refine-on) build of the other tracks today reads 0.60–0.67 (`A-skin*`, `deformF-full1`, `heroE-main2`), and the same hair on the no-refine builds reads 0.80, so it is the skin/refine stage, not the hair.

## Iteration log

Runs under `data/build/lookdev/` (main checkout). Hero = Track E rig (`blender/hero/rig.py`, used through `hair_inspect.py --rig hero|turntable`). Dev builds use direction.json with `head.refine: null` (hair identical, 25 s instead of 3.5 min).

| Run | Change | Verdict (from the pixels) |
|---|---|---|
| `185712Z-hairB-base-fast` | baseline cards | streaky glassy straps (the defect) |
| `190558Z-hairB-g1` | first groom: 24k strands, Huang, redness 0.55, Essentials GN | Already reads as hair. But the rim lit it ginger-orange (redness 0.55), the hairline was a blurry dark band (scalp tint too dark and too near the edge), the part a bald stripe, the back a fine silky sheet. |
| `191518Z-hairB-g2` | 40k strands, redness 0.3, part push 0.25 + lift, tint lighter and later | Colour right. Hairline and part turned into **comb teeth with bald wedges**: the clumping acted on the strands lying on the skull. Front falls a few strings. |
| `192354Z-hairB-g3` | per-point clump ramp (0.2 on the skull), front lift rises over 5 cm, front falls 180 strands | Hairline a soft density ramp, top combed, part reads. Silhouette tight (a slicked pony). |
| `193204Z-hairB-g4` | rebased on Track A forms; side 9 → 14 mm, back 16 mm lift | 900² turntable nape: real-looking wavy locks separating toward the ends. Clump check: the GN clumping works; trim/noise only confound the metric. |
| `195430Z-hairB-c1` | first cards from the groom | Mass matches the groom. Glossy (specular 0.35), hairline a hard dark edge (every atlas strand started at v = 0), black blocks at the temple (cap core), comb of blunt ends (strands clipped at v = 1). |
| `195901Z-hairB-c2` | cap texture from the groom | Worse: the cap's smooth core ramp cut a hard line under MASK; strands too thick and dense. |
| `200502Z-hairB-c3` | v by projection on the centreline (staggered roots, early trimmed tips), wide roots away from the hairline, thin cap strands | Hairline soft, ends taper. Still a dark band above the ear. |
| `200808Z-hairB-g5` | groom `cling` 0.05, ear margin 6 mm | Side volume behind the ears; the front view no longer a pony. |
| `202144Z-hairB-c4` | cap core as staggered streaks; normal strength 0.8, roughness 0.55; wider under cards; fuller tips | The temple band gone; ends denser; highlights broken up. |
| `202844Z-hairB-c5` | rebased on forms v2; brow lock; temple side-break metric | Spring test and hair_fit OK. Hero ECU: front falls stiff strings, brow lock a rat-tail, a stray flyaway card across the ear. |
| `203718Z-hairB-c6` | front falls clump 0.6 + 4 mm wave, comb forward; brow lock diagonal and shorter; flyaway cards clear of the ears | Front falls cross the temple; accepted. |
| `203924Z-hairB-final` | full build (refine on) | Orchestrator review (round 2): a wet-look helmet glued to the skull, no side break at the temples; front falls and brow lock not visible in the portrait; one dark sheet (needs ≥ 3 values and lock gaps); the collar lengths and the tucked mass not visible at ¾; hard-edged card strips at the card hairline. |

**Round 2** (after the review). Renders: hero portrait 700² and the turntable at az −40 / +40 / 150 (head framing), groom and cards, `.scratch/iter.sh`; card close-ups with `hair_inspect.py --rig hero`.

| Run | Change | Verdict (from the pixels) |
|---|---|---|
| `205820Z-hairB-v1` | lift side 14 → 30 mm, back 26, front 18, crown 8, keep 0.75; `cling` 0; clumps 0.85 / 0.8, 300 secondaries; 10 % light strands, per-lock melanin; front falls 360 strands, low hug; brow lock 260 strands | The hair stands off the skull; ¾ views show the mass behind the ear and the lengths reaching the collar in separate locks with highlights. Brow lock visible but a vertical string down the middle of the forehead; front falls hang to the jaw; a pale tuft at the right front crown. Temple break 33 / 34 mm, width 1.21. |
| `210357Z-hairB-v2` | brow lock combed sideways with gravity 0.55; falls end at the cheekbone; front lift 14 mm; 360 secondaries (card count) | Brow lock diagonal to the outer left brow; accepted. **Cards**: shelves of dark horizontal strips above the ear, hard dark root wedges at the forehead. |
| `211036Z-hairB-v3` | cards: 92nd percentile + 1.8 mm width, wider under layer, hairline cards with sparse cells, slow widening, little root darkening | Forehead roots softer; side shelves unchanged, so not a width problem. |
| `211415Z-hairB-v4` | lift rise 3.5 → 6 cm; front-fall clearance back to 5 mm | The louvres were the steep lift ramp (30 mm over 3.5 cm): gone in the card side view. Temple break dropped to 26 / 29 mm. |
| `211907Z-hairB-v5` | side 36 mm over 5 cm; flyaway cards tested along their whole length against the ear | Temple 35 / 36 mm, width 1.344. A dark slab still above the ear in the card portrait; hiding the cap material (`--hide-mat hair`) left it, so it is cards. |
| `212436Z-hairB-v6` | lift jitter 0.6 (inner strands fill the depth) | No change to the slab; temple break 28 mm. Reverted. |
| `213223Z-hairB-v7` | under cards start 20 % along the clump, no root darkening, shade 0.8 | The slab gone: the dense under cells' near-black roots were showing through the gaps at the temple. Accepted. |
| `213651Z-hairB-final2` | full build (refine on) | evidence below |

## Evidence

All under `data/build/lookdev/20261012T213651Z-hairB-final2/evidence/` (Cycles, hero rig = Track E `blender/hero/rig.py`). **Before**: `data/build/m1-signoff/closeup.png` (m1 cards) and `data/build/lookdev/20261012T203924Z-hairB-final/evidence/{groom,cards}/hero_portrait.png` (first v2, the one reviewed).

| Shot | Groom (hero, Cycles) | Cards (GLB) |
|---|---|---|
| Hero portrait 1000², hero light | `groom/hero_portrait.png` | `cards/hero_portrait.png` |
| Turntable ¾ right (az −40), head | `groom/turntable_az-40_el2_lens85_aimhead_frame0.5.png` | `cards/turntable_az-40_…png` |
| Turntable ¾ left (az +40), head | `groom/turntable_az40_el2_lens85_aimhead_frame0.5.png` | `cards/turntable_az40_…png` |
| Turntable back ¾ (az 150) | `groom/turntable_az150_el5_lens85_aimhead_frame0.6.png` | `cards/turntable_az150_…png` |
| ECU hairline left / right / nape, hero light | `ecu/blend_sheet.png` | `ecu/glb_sheet.png` |

Spring test: `data/build/lookdev/20261012T213651Z-hairB-final2/hair/spring_*.png`.

## Verdict per defect

Brief defects (streaky glassy card hair) and the round-2 review points, judged on the final2 renders under both rigs:

| Defect | Verdict |
|---|---|
| Streaky, glassy card hair (m1) | **Fixed** in the groom: individual strands, soft roots, melanin colour, no plastic sheen. **Mostly fixed** in the cards: clump-shaped locks from the groom with a strand atlas, matte. Ends still read as separate dark blades at 2× and the GLB is darker and more uniform than the groom. |
| Wet-look helmet, no volume off the skull (review 1) | **Fixed.** The sides stand off the skull and the mass hangs with volume behind the ears. Side break 35 / 36 mm at temple level and 70 / 73 mm at the widest band (≥ 30 mm), width 1.34 × skull (≤ 1.35, at the limit). The crown is still flat by design (look-spec), with a highlight band. |
| Front falls / left brow lock not visible (review 2) | **Fixed in the groom**: three right falls cross the temple to the cheekbone as separate wavy locks (ECU right, turntable −40) and show in the portrait silhouette at the far temple; the brow lock crosses the forehead diagonally to the left brow (portrait). **Partial in the cards**: present, but each is 2–3 thin strips rather than a lock. |
| One dark sheet, no separation (review 3) | **Fixed in the groom**: visible lock gaps in the lengths, lighter catching strands, and a highlight band on the top. The mass has three values under the turntable and hero rigs. **Partial in the cards**: highlights and lock shapes, but darker overall. |
| Collar lengths and the mass behind the ear at ¾ (review 4) | **Fixed**: both ¾ turntable views show the mass behind the ear and the lengths over the collar (tips p50 1.583 m). |
| Hard-edged card strips at the card hairline (review) | **Improved, not solved.** The near-black strips at the temple were the under cards; they are gone. Hairline cards are finer and lighter at the root. At ECU the card hairline is still alpha-tested strokes over the cap texture; it needs the runtime's alpha-to-coverage (spec §3.3). |
| Hairline: recession, feather, vellus | **Fixed** (groom): temples recede, density ramps over the feather, vellus visible at ECU. |
| Part | **Fixed**: soft, off-centre, no bald stripe. |
| Turntable vs hero light | Both read; the groom is browner under the turntable, near-black under the hero rig. |

## Deviations from direction §2 Track B (numbers are starting points; my eyes decided)

- **40,000 strands, not 18–24k.** At 24k × 0.045 mm the crown and the sides showed scalp and the mass read thin at 1k (g1); the prompt allowed 40–100k. Render cost is fine (~2 min per 560² view at 3 threads).
- **Melanin redness 0.3, not 0.55.** Blender's melanin split at 0.55 gives more pheomelanin than eumelanin: the white studio rim lit the hair ginger (g1). At 0.3 it holds near-black brown under both rigs.
- **Huang has no coat or radial roughness inputs** (those are Chiang parameters), so they are not set.
- **Clump factors 0.85 / 0.8, not 0.6 / 0.4**, but ramped along the strand (0.2 × on the skull): at the spec factors the locks did not separate (the review's "one dark sheet"); at full factor on the scalp the hairline went to comb teeth (g2).
- **Light strands 10 %** (melanin 0.8) instead of 3 %, plus up to −0.04 melanin per lock, for the third value the review asked for.
- **Width / skull 1.344**: the side lift that gives the 30 mm temple break puts the eye-level width at the 1.35 limit; there is no headroom for more volume.
- Game albedo is realistic (strand value × AO), not "lock blocks with a 2-tone ramp" (§4): the painterly treatment belongs to the runtime shader, and the atlas keeps the data it needs.

## Shared-file edits

- `blender/character/config.py`: one additive key, `hair.groom: {}` (defaults live in `hair_groom.DEFAULTS`).
- `provenance/mesh.jsonl`: one record (the Essentials node groups).
- `hair_mesh.py`: untouched. `blender/hero/rig.py`: imported by `hair_inspect.py`, not edited.

## Tools

- `bench/m1/hair_inspect.py RUN --source glb|blend --rig studio|hero|turntable [--engine eevee|cycles] [--views ...]`: head views at 1024² (front, closeup, side, back34, back, game, bust, hairline, hairline_r, part, nape), groom (from the kept .blend) or cards (GLB), under the look-dev studio or Track E's rigs. `--hide-mat NAME` for debugging.
- `hair_fit.py`, `hair_springtest.py`: unchanged, work on the new mesh.
- Opt out: `{"hair": {"groom": null}}` (the hair_clumps cards); `{"hair": {"groom": {"cards": "clumps"}}}` keeps the groom with the old cards.

## Known limits / next

- The cards' hairline at ECU is still alpha-tested strokes; the runtime needs alpha-to-coverage there (spec §3.3). The groom hairline is the reference.
- In the cards, the front falls and the brow lock are thin strips, and one thin card still crosses the top of the right ear at ECU.
- A pale fuzzy tuft at the front crown (flyaways weighted to the part) catches the turntable's top light.
- Card ends over the collar read as separate dark blades at 2×; the groom ends are soft.
- A small gap between the hair halves at the centre back shows the shirt collar at the 165° nape ECU (groom and cards).
- The groom is rigid with the head bone; with a large head turn the hanging lengths will cut the collar. Hair dynamics for the hero poses are out of scope.
- The cap texture tiles one 6 cm window of the front hairline round the whole head.
