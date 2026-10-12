# m1 v2 Track B: scalp hair (strand groom + game cards baked from it)

_2026-10-12. Brief: `bench/m1/v2/BRIEF.md`; art direction: `direction.md` §2 Track B. Builds on the frozen Track A head (main 8fa40c6)._

## What it is

The scalp hair is now a **strand groom** that is the source of truth for both versions:

| | Hero (Cycles, `hero_only`) | Game (GLB) |
|---|---|---|
| Module | `blender/character/hair_groom.py` | `blender/character/hair_groom_cards.py` |
| Geometry | Blender hair curves: 520 guides → 40,000 strands × 24 points + 1,400 vellus hairs (4 points), 965,600 control points | 541 cards (72 under, 208 mid, 209 top, 12 front-fall, 40 flyaway) + the scalp cap: **23,432 tris** |
| Detail | Geometry Nodes modifier `hair_groom` built from the bundled **CC0 Essentials** hair node groups: noise → primary clump → secondary clump → frizz → flyaway noise → trim | atlas 2048², 12 lock variants rasterised from the evaluated groom strands; cap texture rasterised from the groom's hairline strands |
| Shading | Principled Hair BSDF, **Huang**, melanin per strand (0.95; 3 % lighter strands at 0.85; vellus 0.7), redness 0.3, roughness 0.22 root → 0.30 tip (Hair Info intercept), random colour 0.08, random roughness 0.1, IOR 1.55 | Principled: albedo atlas × COLOR_0, alpha MASK, tangent-space normal atlas (strand cylinders), roughness 0.55, specular 0.25, no anisotropy |
| Binding | Curves object parented to the `head` bone; a hero-only scalp tint shell (skinned like the cap) | skinned; 14 spring bones (back 2+2, side 3+3, front_r 2, front_l 2) |

Licence check (asked in the prompt): `/usr/share/blender/5.2/datafiles/assets/LICENSE` is **CC0 1.0** for the whole bundled asset library, so the Essentials hair node groups (`procedural_hair_node_assets.blend`) are usable, also for baked output that ships. Recorded in `provenance/mesh.jsonl` (`blender:essentials/procedural_hair_node_assets`, sha256 of the file); audit 0 errors.

## Construction

### Groom (`hair_groom.py`, defaults in `hair_groom.DEFAULTS`, config `hair.groom`)

1. **Growth surface and hairline field.** The hair_clumps growth region (MPFB `scalp` + temple and nape bands) as triangles. `Surface.d_eff(p)` = distance to the region's open boundary minus a **temple recession** (two Gaussian bays at ±44° azimuth, 9 mm deep, σ 13°, gated above the ears). `d_eff < 0` is bare skin. Everything is sampled on this surface; nothing is a fixed coordinate, so the rebuild on Track A's frozen head needed no change.
2. **Guides.** 520 roots by farthest-point sampling over the surface, each marched by `hair_clumps.march` (comb back from the part, ear ellipsoids, tuck behind the ears, gravity, skin and suit colliders), with groom overrides: `cling` 0.05 (the lengths hang with some volume instead of clinging to the neck), ear margin 6 mm, a **soft part** 12 mm left (push 0.25 decaying over 2 cm, the part line wandering ±2 mm, a 4 mm lift next to it), a **volume profile per root**: 10 mm lift off the forehead rising over 5 cm, a flat crown (3 mm), 14 mm on the sides and 16 mm over the occiput. Resampled to 24 points (point 0 buried upstream, point 1 at the root).
3. **Strands.** 40,000 roots area-uniform with a **density ramp over the 10 mm feather** (8 % at the hairline → full). Each strand blends its 4 nearest guides (never across the part), translated to its root, then is pushed ≥ 1.2 mm off skin and suit. A **lock wave** (4–8 mm, 12–18 cm period, phase per primary clump) in the hanging part.
4. **Clumps** (curve attributes, read by GN): 10 % strays (no clumping); 36 primary centres (farthest-point, same side of the part) and ~420 secondary centres inside them. A per-point **clump ramp**: 0.2 while the strand lies on the skull, full 6 cm past its hang point, so the swept-back top stays combed and the lengths separate into locks.
5. **Front falls**: three on the character's right (180 strands each, clump 0.6, 4 mm wave) crossing the temple toward the cheekbone, ends 3 cm above the lips; one thin lock (80 strands) from the left of the part falling diagonally across the left temple toward the brow.
6. **Flyaways**: 4 % of strands, weighted to the silhouette (sides, back) and the part, 10 mm noise in GN, half clumping.
7. **Vellus**: 1,400 hairs, 3–6 mm, along the whole hairline (`d_eff` −2…6 mm), flat to the skin (lift 0.35), radius 0.018 mm, lighter.
8. **GN modifier** (`hair_groom` node group, every input editable in the .blend): Hair Curves Noise (1.5 mm, scale 40) → Clump (primary, factor 0.7 × clump_w × clump_ramp, `guide_curve_index`) → Clump (secondary, factor 0.6, `sub_guide_index`) → Frizz (0.5 mm) → Hair Curves Noise (flyaways, factor = `fly`) → Trim (random 5 %). Checked numerically: the clump stages pull members from 15.6 → 7.3 mm (primary) and 7.1 → 2.2 mm (secondary) of their guides in the hanging part.
9. Strand radius 0.045 mm at the root → 0.02 mm at the tip (direction values).

### Game cards (`hair_groom_cards.py`, defaults in `CARDS`, overrides in `hair.groom.game`)

- **From the evaluated groom** (after GN; point counts verified unchanged): one card per secondary clump (mid = inner half by stand-off, top = outer half), two per primary clump (under, split across the width, pulled 3 mm toward the skull), one per front-fall sub-clump, 40 flyaway strips along the groom's flyaway strands (not round the ears). The card path is the clump's mean strand; the half-width is the 85th percentile of the strands' spread across the card (smoothed); taper to 45 %; roots narrow (25 %) near the hairline, 80 % further back; 3 vertices wide with a rounded profile.
- **Atlas** (12 cells, 6 × 2 of 329 × 1012 px usable): 8 secondary clumps (sparse to dense), 2 primary clumps, 1 flyaway cell, 1 hairline wisp. Each cell rasterises the clump's actual strands in its card frame (u = offset across / half-width, v = centreline arc + offset along the tangent, so roots stagger and trimmed tips end early; depth along the normal), 3× supersampled and z-buffered. Written as `hair_atlas_albedo` (RGB, A coverage), `hair_atlas_data` (R coverage, G root-to-tip, B strand ID: the threejs-hair-shader layout), `hair_atlas_flow` (RG flow with ±15° per-strand jitter, B depth, A AO), `hair_atlas_normal`; packed in the .blend and saved as PNGs next to the GLB. The GLB carries albedo + alpha + normal (glTF has no slot for the data / flow maps).
- **Cap**: the scalp shell (hair_clumps' construction) with its UV v measured from the groom's **recessed** hairline; its texture is rasterised from the groom's strands and vellus rooted in one 6 cm window of the front hairline (near-skin parts only), over a dark core that fills in as staggered streaks (an alpha ramp would cut a hard line under MASK).
- **COLOR_0**: layer AO (under 0.55, mid 0.78, top 1.0, front 0.9, flyaway 0.85) × per-lock lognormal value × **35 % root darkening** over the first 30 % of v.
- **Smooth-proxy normals**: the groom's points → Points to Volume (4 mm voxels, 8 mm radius) → Volume to Mesh → Laplacian smooth; Data Transfer (custom normals, nearest face interpolated) onto the card vertices, applied as the first modifier.
- **Springs**: hang distance and sector per card vertex from the clump's strands → `hair_springs.bind` (unchanged). Pose test `hair_springtest.py` passes (masses swing, no tearing).
- The card object is `hide_render` in the kept .blend (the hero stage renders the groom); the exporter ignores render visibility, so the GLB keeps it.

## Numbers (final run `20261012T203924Z-hairB-final`, direction.json with the head refine)

| | Baseline (m1 sign-off) | **v2** |
|---|---|---|
| Hair tris | 27,548 | **23,432** (cap 816, under 3,060, mid 9,536, top 8,620, front 248, fly 1,152) |
| LOD0 total | 124,614 | 124,095 |
| Bones / max weights / validator errors | 66 / 4 / 0 | **68 / 4 / 0** (15 warnings, the known non-root skin ones) |
| Groom | – | 40,000 strands + 1,400 vellus, 520 guides, 36 primary / 417 secondary clumps, 3,866 strays, 1,600 flyaways |
| Tip z p10 / p50 / p90 (cards) | 1.540 / 1.560 / 1.575 | 1.574 / 1.582 / 1.592 (collar top ≈ 1.58) |
| Width / skull at eye level (≤ 1.35) | 1.18 | **1.11** |
| Side break beyond the cap | – | **45 / 106 mm** at the widest band (z 1.67, the hanging mass behind the ears); **13 / 13 mm** at temple level |
| Cap edge over the refined skin (`hair_fit.py`) | 0.50 / 1.24 mm | 0.60 / 1.25 mm (ring 0 / 1 p50; 2 of 202 edge verts ≤ 0 mm) |
| Hair verts > 0.5 mm under the skin | 8.2 % | 10.6 % (the buried card root rows) |
| hair_post time | ~5 s | 29 s idle; 60–66 s at load 25 (groom ~10 s, cards + atlas + proxy ~20 s) |

`read40` eye band reads 0.65 (fail) on this full build; every full (refine-on) build of the other tracks today reads 0.60–0.67 (`A-skin*`, `deformF-full1`, `heroE-main2`), and the same hair on the no-refine builds reads 0.80, so it is the skin/refine stage, not the hair.

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
| `203924Z-hairB-final` | full build (refine on) | evidence below |

## Evidence

EVIDENCE_PLACEHOLDER

## Verdict per defect

VERDICT_PLACEHOLDER

## Deviations from direction §2 Track B (numbers are starting points; my eyes decided)

- **40,000 strands, not 18–24k.** At 24k × 0.045 mm the crown and the sides showed scalp and the mass read thin at 1k (g1); the prompt allowed 40–100k. Render cost is fine (~2 min per 560² view at 3 threads).
- **Melanin redness 0.3, not 0.55.** Blender's melanin split at 0.55 gives more pheomelanin than eumelanin: the white studio rim lit the hair ginger (g1). At 0.3 it holds near-black brown under both rigs.
- **Huang has no coat or radial roughness inputs** (those are Chiang parameters), so they are not set.
- **Clump factors 0.7 / 0.6, not 0.6 / 0.4**, but ramped along the strand (0.2 × on the skull): at the spec factors the locks did not separate; at full factor on the scalp the hairline went to comb teeth (g2).
- **Side break ≥ 30 mm**: met at the widest band (behind the ears) but only 13 mm at the temples, where the hair is swept back and lies close by design (look-spec: swept back, close at the crown). More would read as a 70s blow-dry.
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

- The cards' hairline at ECU is still a dark stroke edge, alpha-tested; the runtime needs alpha-to-coverage there (spec §3.3). The groom hairline is the reference.
- Card ends over the collar read as separate dark blades at 2×; the groom ends are soft.
- A small gap between the hair halves at the centre back shows the shirt collar at the 165° nape ECU (groom and cards).
- The groom is rigid with the head bone; with a large head turn the hanging lengths will cut the collar. Hair dynamics for the hero poses are out of scope.
- The cap texture tiles one 6 cm window of the front hairline round the whole head.
