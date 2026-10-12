# m1 suit track: black three-piece, parametric rebuild

The suit is now **built on the body by script** (`blender/character/suit_build.py` primitives, `suit_jacket.py`, `suit_inner.py`, `suit_shoes.py`, `suit_textures.py`, driven by `suit.py`). Only the trousers still come from the CC0 suits01 shell (`suit_ops.tailor_trousers`). Every size is a parameter in `suit.DEFAULTS` and lands in `character.stats.json["suit"]`. Nothing is traced from film stills: the target below is written in words from costume-designer interviews and tailoring breakdowns, then built from body landmarks and the rig.

Runs (main checkout, `data/build/lookdev/`): before `20261012T104705Z-suit2-baseline` (the m1 wave-2 suit on the direction config), after `20261012T121526Z-suit2-final` (loop) and `20261012T121551Z-suit2-final-signoff` (Cycles, same build), compare sheet `compare-20261012T104705Z-suit2-baseline--20261012T121526Z-suit2-final/`. The final run dir holds `suit_views/` and `pose_test/`.

## 1. Target look (John Wick character, Chapters 2–4), with sources

The character's costume is costume styling, which is fair game (NOTES decision log 2026-10-12); the face is not. Hard tailoring data exists mostly for Chapter 1 (BAMF Style) and the designers' intent for the later films; nobody publishes lapel widths or button stances, so those are our own, taken from the classic ranges the look-spec already cites. Where the sources disagree it says so.

| Element | Target we build | Source |
|---|---|---|
| Cloth, colour | Near-black worsted wool, a soft sheen so it reads under neon (not a flat black). Mosca: the suits "may look black but are actually very dark grey"; the Rome suit in Chapter 2 is the true black exception. Delgado (Chapter 4) chose a Scabal cloth with a sheen, "a black that reflected light instead of absorbing light". We use linear albedo 0.028, roughness 0.70, a weak sheen, plus a fine twill in the normal map (Mosca describes a subtle "waffly" Kevlar-like texture on the Chapter 3 suit; we keep it to a fine twill so it stays a suit, not armour). | [Gentleman's Journal](https://www.thegentlemansjournal.com/article/story-behind-keanu-reeves-styling-john-wick-suit/), [Offscreen Central, Delgado](https://offscreencentral.com/2023/11/15/john-wick-chapter-4-interview-with-costume-designer-paco-delgado/), [SlashFilm, Mosca](https://www.slashfilm.com/566482/john-wick-3-costume-designer-interview/) |
| Design intent | "Very sleek, very clean lines and minimal color", "reduced to the essential", a Glock as the reference object; no pattern, no embellishment; "you see his silhouette coming from afar and you know that it's him". So: no pocket square, no tie bar, plain buttons, nothing shiny except the shoes. | [SlashFilm](https://www.slashfilm.com/566482/john-wick-3-costume-designer-interview/), [Highsnobiety](https://www.highsnobiety.com/p/john-wick-parabellum-luca-mosa-interview/) |
| Jacket cut | Single-breasted, **two buttons**, slim and close, high armholes, natural shoulders with **roped sleeve heads**, **slim notch lapels** with edge stitching, **double vents**, welted breast pocket, straight **flapped hip pockets**, four-button cuffs. (Chapter 1 facts; Mosca says each sequel "cleans" the same template.) Peak lapels appear only in retail replicas, not in the costume sources. | [BAMF Style, Chapter 1](https://bamfstyle.com/2015/03/27/john-wick-suit/), [Black Lapel](https://blacklapel.com/blogs/the-compass/master-the-john-wick-suit) (retail, low weight) |
| Numbers (ours) | Lapel 8.0 cm, gorge 3.2 cm below the neck point (medium-high), fastening button at 0.615 × stature (about an inch above the navel), second button 11 cm below, hem at 0.50 × suprasternale height, shoulder 1.2 cm past the deltoid each side, 24 cm vents at ±0.55 of the back half-width. | look-spec §4.1 conventions ([Bond Suits](https://www.bondsuits.com/the-suits-ideal-proportions/), [Westwood Hart](https://westwoodhart.com/blogs/westwood-hart/guide-suit-lapel-width-classic-wide-skinny)) |
| Waistcoat | Single-breasted, no lapels, **low-fastening**, welted lower pockets, small notched hem, satin back (fan sources). Chapter 1 had four buttons; the look-spec and the user's rulings keep **five, bottom undone**, points over the waistband. | [BAMF Style](https://bamfstyle.com/2015/03/27/john-wick-suit/) |
| Shirt | White, **moderately spread collar**, from Chapter 2 on a "very imposing high collar" that became the trademark; narrow placket, no pocket, French cuffs (we build barrel-style cuff rings; the cuff type is invisible at game distance). | [SlashFilm](https://www.slashfilm.com/566482/john-wick-3-costume-designer-interview/), [BAMF Style](https://bamfstyle.com/2015/03/27/john-wick-suit/) |
| Tie | Plain **black silk**, slim, **four-in-hand** knot (fan sources say half-Windsor; a small asymmetric knot reads better with a slim tie and the high collar). We tuck it under the waistcoat (user ruling). Blade 7.8 cm. | [BAMF Style](https://bamfstyle.com/2015/03/27/john-wick-suit/) |
| Trousers | **Flat front**, straight slim leg, plain hems with a short break (BAMF: "break high"), slanted side pockets, jetted rear pockets. Chapter 1 wore a belt; we keep side adjusters (house style, no belt under the waistcoat). | [BAMF Style](https://bamfstyle.com/2015/03/27/john-wick-suit/) |
| Shoes | **Black calf cap-toe derbies**, three eyelets, slightly squared toe, polished. (The look-spec said oxfords; the only sourced description is derbies, so the shoe is a derby: open lacing with facings over the vamp.) | [BAMF Style](https://bamfstyle.com/2015/03/27/john-wick-suit/) |
| Fit in motion | Hero suits fit trim; action copies add gussets under the arms and stretch panels at the sides and crotch, "Lycra becomes our biggest friend". For us that means the rest-pose cut can be close, and the deformation work (helpers, Dem Bones) carries the stretch. | [SlashFilm](https://www.slashfilm.com/566482/john-wick-3-costume-designer-interview/), [Gothamist (snippet)](https://gothamist.com/arts-entertainment/interview-ny-couture-costume-designer-luca-mosca-talks-suiting-up-john-wick) |

Not fetched in full (403/429 at research time, used via search snippets only): Film Independent parts [1](https://www.filmindependent.org/blog/costume-designer-luca-moscas-sartorial-lettera-damore-to-john-wick-part-one/) and [2](https://www.filmindependent.org/blog/detail-oriented-john-wick-costume-designer-luca-mosca-part-two/), [WWD on Delgado](https://wwd.com/menswear-news/mens-fashion/paco-delgado-john-wick-wardrobe-costume-designer-hard-rock-hotel-suitstakes-1235575235/), [Screen Rant on Delgado](https://screenrant.com/john-wick-4-costume-designer-suitstakes-interview/).

## 2. How it is built

All garments are **lofted from cross-sections of the unmasked body** (`suit_build.Body`, captured in `suit.add` with the delete masks muted). A slice is a polar profile (max radius per angular bin), smoothed, **canvassed** (chord-filled so the cloth bridges the sternum and the small of the back instead of following the anatomy) and eased outward by the tailoring allowance. Rows of rings become quad grids (`suit_build.Grid`) with **metric UVs** (metres along the ring and up the loft), one rectangle per panel, so the texture pass can place seams by (row, column). Skin weights come from the nearest body vertex of the garment's bone set, so the layers deform together.

**Jacket** (`suit_jacket.py`):
- *Block*: 44 rows from the hem to the shoulder ring, 72 columns from the left front edge round the back to the right front edge. Ease: chest 24 mm, back 18, sides 20, waist 16/13/14, hips 18, plus 10 mm of flare at the hem. Below the hips the slice is the running max of the slices above (the skirt hangs straight). Above the armpit the slice is widened in x only, to the shoulder point (body bideltoid + 2 × 12 mm), and the outer part of the top rows drops 30 mm (shoulder slope), so the shoulder line runs from the neck point down to a slightly roped sleeve head.
- *Front*: the left panel overlaps the right by 2 cm below the fastening button, the right is tucked 3 mm inside; the quarters cut away 2.5 cm toward the hem. Above the button each front edge is the roll line, a straight V from the button to the neck point (±7.2 cm).
- *Lapels*: a flap folded back along the roll line, one row per block row: fold bulge (12 mm roll height, strongest mid-way), width growing from 0 at the button to 8 cm at the gorge (power 2.2, so the roll is soft), a 3 mm edge lip, and a tip row that rises 28 mm past the gorge and leans outboard. That tip and the collar end make the **notch**.
- *Neckline and collar*: the top row runs on the neck circle (+16 mm ease) from the gorge points, rising 3.2 cm to the back. The collar is a stand (28/32 mm front/back, leaning 4 mm in), a fold, and a fall (48/44 mm) that rests on whatever is beneath it (ray-tested), plus 4 extra columns at each end running out along the lapel's top edge to the **collar point** (36 mm, angled 12° down), which closes the notch.
- *Vents*: two 24 cm slits at ±0.55 of the back hem half-width, the outer flap lifted 4 mm (tapering to 0 at the top), and a 3.5 cm **underlap** strip behind each.
- *Sleeves*: 28-column tubes along the arm bones (upper arm, elbow blend, forearm) to 5 mm past the hand joint; radius = arm profile + 10 mm ease, never thinner than a 66 → 46 mm taper; a 3.5 mm rope on the top of the head; the head ring is ray-cast onto the block (the armhole seam, 4 mm proud) and eased into the tube over 7 rows; a 4 mm cuff lip.
- *Pockets*: two flapped hip pockets (16 × 6 cm, 7.5 cm below the button) and a slanted breast welt (10.5 × 2.4 cm), as thin panels standing 0.5–3.5 mm off the block.

**Inner layers** (`suit_inner.py`), built only where they can show (look-spec §4.3):
- *Shirt*: front panels inside the waistcoat's V plus a 3 cm margin, a placket strip 1.2 mm proud with two buttons, a **collar band** (34/38 mm front/back) with a fold and leaves that are 7 cm **points** spread 28° at the front, nothing across the front gap (the tie), and short (16 mm) under the jacket collar; the leaves are tucked under the jacket wherever they would poke out (`suit_build.tuck_under`). Cuff rings 13 mm past the sleeve ends.
- *Tie*: a **four-in-hand** knot (40 × 46 × 24 mm, lofted half-ellipses, 3 mm skew) and a blade from 32 to 78 mm wide with a 5 mm dimple under the knot, lying 3 mm over the shirt placket, cut 3 cm under the waistcoat V.
- *Waistcoat*: front panels from the vest V (top button 11.8 cm above the jacket button) out to the jacket's V + 5 cm, 8 mm off the body and pushed 3 mm clear of the shirt and tie; hem 2.5 cm below the waistband at the sides, points 5 cm lower with a notch; a 2.5 mm edge lip; 5 buttons, buttonholes and two welt pockets in the normal map; a 12 cm lower back panel for the vents.
- *Buttons* (`suit_buttons`): 8-segment discs, 22 tris each: 2 front, 4 per cuff (kissing, on the hindarm side), 5 vest.

**Shoes** (`suit_shoes.py`): black calf **cap-toe derbies**. Rings across each foot at 26 slices (polar half-profiles of the foot, chord-filled into a stiff last, smoothed along the foot, 4 mm leather), a toe box that extends 2.6 cm past the toes on an elliptical taper, the rings opened above a 64 mm topline behind the throat. A **welt** lip (5 mm) and a sole slab (10 mm, 26 mm heel block), three eyelets a side with criss-cross lace tubes. Cap seam, quarter seams, heel counter seam and welt stitch go to the leather normal map.

**Trousers** (`suit_ops.tailor_trousers`, stock shell): quarter break (back hem 3.5 cm), **leg-opening taper** to 9.5 cm half-width from the knee, front and back crease ridges, cylindrical metric UVs per leg with the outseam, inseam, hem edge, jetted back pockets and crease lines in the normal map.

**Surfaces** (`suit_textures.py`): the metric panel rectangles of each material group are shelf-packed into one square atlas (uniform texel density) and the UVs rewritten. A float **height map** is drawn with numpy: a 2/1 twill weave (1.9 mm period, a little over 2 px) plus two octaves of fibre grain, then the marks the builders registered in panel space (pressed seams with pick stitches either side, topstitched finished edges, rolled edge lips, bar-tacked buttonholes with a keyhole, crease ridges, welts), and converted to a **tangent-space normal map**. Groups and sizes: jacket 2048² (0.71 mm/px), waistcoat + trousers 2048² (0.77 mm/px), shirt 1024² (0.53 mm/px), tie 512², shoes 1024² (0.44 mm/px). Images are packed into the .blend and embedded by the glTF exporter. Materials: `suit_wool` (albedo 0.028, roughness 0.70, sheen tint 0.08), `suit_wool_b`, `suit_shirt` (0.75, 0.55), `suit_silk` (0.02, 0.35, sheen 0.15), `suit_leather` (0.012, 0.28), `suit_sole`, `suit_button`. The glTF exporter writes Sheen *Tint* as `sheenColorFactor` and ignores Sheen Weight, so the strength goes in the tint.

Degenerate faces (zero vector area: seam wraps and collapsed lapel rows) are removed in `Garment.finish`; they exported zero tangents, which the Khronos validator flags as an error.

## 3. Measurements against look-spec §4.1

| Check | Spec | Before (wave 2) | After | |
|---|---|---|---|---|
| Jacket hem ÷ suprasternale z | 0.50 ± 0.015 | 0.500 | **0.500** (hem z 0.755) | ✅ |
| Fastening button z ÷ stature | 0.61 ± 0.01 | 0.619 | **0.615** | ✅ |
| Jacket shoulder width − body bideltoid | +2.0–3.5 cm | +3.3 cm | **+2.4 cm** | ✅ |
| Waist suppression (width at button ÷ chest) | ≤ 0.88 | 0.79 | **0.76** | ✅ |
| Lapel width | 8.5 ± 0.7 cm | stock, unmeasured | **8.0 cm** by construction | ✅ |
| Gorge | notch ≈ 5 cm below the neck point | stock | 3.2 cm (medium-high, the later-films "imposing" collar) | 🟡 house choice |
| Tie tip above waistband top | 0–4 cm | +2.0 cm | tucked: the blade ends 3 cm under the vest V (never visible) | ✅ |
| Waistband top ÷ stature | 0.59–0.63 | 0.623 | 0.623 (stock trousers) | ✅ |
| Trouser back hem z | 0.035 ± 0.01 m | 0.0355 | 0.0355 | ✅ |
| Leg opening | ~19 cm flat | stock | 19 cm (half 9.5) | ✅ |
| Vest bottom below the waistband top | > 2 cm | 2.5 / 7.5 cm | 2.5 cm sides, 7.5 cm points | ✅ |
| Vest top button above the jacket button | 12–14 cm | 12.8 cm | 11.8 cm | 🟡 (lowered 1 cm so the vest V clears the tie knot shadow) |
| Vents | double, 24 cm | double | double, 24 cm, with underlap | ✅ |
| Cuff reveal | 1–1.5 cm | 1.3 cm | 1.3 cm | ✅ |
| Shirt collar | semi-spread, 7 cm points, 1–1.5 cm above the jacket collar | stock | 7 cm points, 28° spread, 38 mm band | ✅ |
| Shoes | cap-toe, polished | shoes04 placeholder | built derbies, 3 eyelets, welt, heel | ✅ |
| Max weights per vertex / glTF errors | 4 / 0 | 4 / 0 | **4 / 0** (the usual `NODE_SKINNED_MESH_NON_ROOT` warnings) | ✅ |

### Triangles (direction config, hair on)

| Part | Wave 2 | Now | Budget (suit.DEFAULTS) |
|---|---|---|---|
| Jacket | 9,000 | 10,980 | 14,000 |
| Waistcoat | 1,516 | 2,999 | 3,000 |
| Shirt | 1,448 | 1,426 | 2,200 |
| Tie | 700 | 308 | 900 |
| Trousers | 2,188 | 2,188 | 4,000 |
| Buttons | 154 | 330 | – |
| Shoes | 3,000 (stock) | 3,536 | 5,000 |
| **Suit + shoes** | **18,006** | **21,767** | ~40k allowed |

Character total on the direction config: 61,909 → **65,512** (hair 21.0k, beard 5.9k, body 15.2k; the hair count moves a little with the collar it collides with). Build: `suit_post` ≈ 2.5 s of the ~10 s Blender build (textures ~0.9 s); a harness iteration is ~22 s.

## 4. Poke-through test (look-spec §4.3 [auto])

`bench/m1/suit_pose_test.py` imports the GLB, drives the rig through nine poses (rest, the spike-1 stress pose, twist both ways, arms up, reach, crouch, lean, kick), renders a flat **ID pass** (one emission value per mesh, no AA) from four cameras and counts pixels per mesh. Inner layers (waistcoat, shirt, tie) may only show where they show at rest, so the count over the rest count is the poke-through estimate. Output: `poke.json`, `pose_<pose>_<view>.png` (IDs), `beauty_<pose>_<view>.png`.

Result on the final run (`20261012T121526Z-suit2-final/pose_test/`, 512², the figure ~330 px tall; pixels over the rest count, worst of the four views):

| Pose | shirt | tie | waistcoat | reading |
|---|---|---|---|---|
| stress (spike-1 pose) | 323 | 210 | 215 | the torso turns 35° toward the ¾ camera, so the V faces it: legitimate visibility, not poke-through (checked in `beauty_stress_three_quarter.png`) |
| twist (spine +60°, neck −20°) | 475 | 477 | 271 | same: the profile camera now sees the front |
| twist_back | −5 | 0 | 31 | clean |
| arms_up (95°) | 110 | 17 | 0 | the shirt cuffs and placket show more as the sleeves pull; no white through the jacket body |
| reach | −5 | 0 | 4 | clean |
| crouch | 221 | 1 | 106 | the shirt front shows under the lapels as the spine bends forward (the jacket V opens); the waistcoat with it, no shirt through the waistcoat |
| lean | 235 | 1 | 119 | as crouch |
| kick | 2 | 1 | 6 | clean |

**Verdict:** no inner layer breaks through an outer one at rest or in the eight poses; the counts above the noise are the V opening or the figure turning toward a camera. The waistcoat is 3 mm clear of the shirt and tie and inside the jacket by its own ease difference (jacket 16–24 mm vs vest 8 mm off the body), compared with 4 mm in wave 2; the two share the body's torso weights by nearest vertex, so they twist together. The test's rest-subtraction over-counts whenever the whole torso turns; a per-pixel neighbourhood test (inner-layer pixels not adjacent to any inner-layer pixel at rest, in the rotated frame) is the next step if a locomotion clip shows real breakthrough. The body figure in `poke.json` is indicative only (head and hands move between poses).

Known deformation issues the test shows (not poke-through): the sleeve heads pinch at the shoulder when the arms go up 95° (no `deltoid_helper` yet), and the front skirt rides up the raised thigh in `stress` and `kick` (no `glute_helper`, no Dem Bones skirt bones).

## 5. Remaining weaknesses (honest)

- **Jacket skirt in leg raises** still lifts with the thigh (the skirt is weighted 50 % to the legs below the hips so it follows the walk; in a −50° thigh raise the front panel rides up and the inside shows). This is the `glute_helper` / Dem Bones job (look-spec §5.2), not fixable by rest-pose geometry.
- **Lapel notch** is built from two meeting flaps (lapel tip, collar point); it reads as a notch from the front and ¾ but the join is not a sewn seam, and from above there is a small open wedge between the collar end and the neckline.
- **Sleeve pitch**: the sleeves follow the bone axis, so in the A-pose they hang straight; a real sleeve is pitched forward about 10°. Add a pitch parameter once the rest pose is re-evaluated against the locomotion set.
- **Trousers** are still the stock shell: the rise, seat and fly are the stock mesh, and the UVs are cylindrical per leg (seams in the normal map only).
- **Shirt collar** sits a little low at the back under the jacket collar; the leaves are tucked by ray test, which can leave a hard crease where they meet the lapel.
- **Normal-map weave** is at the Nyquist edge of a 2k atlas (2.4 px per period); it mips to flat at distance, which is fine, but at the sign-off close-up it shows as fine diagonal hatching rather than cloth.
- **Shoes**: the upper's topline is a straight cut; no tongue, no heel pull; the throat/facing geometry is implied by the eyelets and laces. The sole bottom is a flat cap.
- Materials still have no base-colour textures (flat albedo + normal). Shoe leather would benefit from a roughness map (toe-cap polish).

## 6. Tools

- `bench/m1/suit_dev.py`: the suit loop (build without hair in one Blender process, render the detail views in another): `blender -b -t 4 --factory-startup --python bench/m1/suit_dev.py -- --out DIR [--override '{"suit": {...}}'] [--views …] [--wire] [--hair]`. 10–16 s per iteration.
- `bench/m1/suit_views.py`: detail views (front, back, back hem, torso, torso ¾, side, lapel, gorge, knot, shoulder, shoulder back, V bottom, pocket, cuff, hem, hem back, shoe, shoe side, shoe top) at −3 EV; `--wire` overlays the mesh, `--only`/`--hide` filter meshes.
- `bench/m1/suit_pose_test.py`: the poke-through test above.
- `bench/m1/lookdev.sh --config bench/m1/variants/direction.json --prev RUN <label>`: the harness; suit parts show as `tris.parts.suit_*`.
