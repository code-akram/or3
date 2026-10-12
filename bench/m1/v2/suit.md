# m1 v2 Track D: the suit

Goal (BRIEF, direction.md defect 7): turn the grey, boxy costume into a sharp, close-cut near-black three-piece that reads as black wool under the neon-noir hero light and the turntable. Everything is still built on the body by script; the GLB stays game-ready and the Cycles-only detail goes into the kept `.blend` after the export.

## 1. What changed

### Jacket cut (`suit_jacket.py`, `suit_neck.py`, `suit_build.py`, `suit.py` DEFAULTS)

- **Length and skirt.** The hem comes from the seat fold (`seat_fold`), so the jacket just covers the seat: hem z 0.8675 = 0.573 × suprasternale height (hem 2.5 cm under the gluteal fold; the look-spec rule of 0.50 × suprasternale put the hem at z 0.755, mid-thigh, which reads as a short coat on this long-legged figure: `suit_ba/tt0.png`, left). Below the hip the rings are sliced over torso + thighs, so the skirt clears the thighs instead of cutting through them. Rounded front quarters.
- **Waist suppression** 0.726 (waist width over chest width, 31.7 cm over 43.7 cm).
- **Gorge and lapel.** The gorge seam drops 4.5 cm below the top ring (`gorge_drop_m`): gorge z 1.482, 3.2 cm below the suprasternale. The collar's front end now lies on the lapel roll line (a crest point, then the roll line down to the gorge) instead of standing out from the shoulder. This removes the "lapel wings" Track E flagged at the shoulders in the rest pose. The collar seam follows the neck (`neck_clear_m` 5 mm over a narrow band, lift limited to 4 cm so the ray can't climb the jaw). The strip between the top ring and the neckline is pushed clear of the body (it was letting the shirt and skin through). A canvas bridge (`bridge_columns`) spans the collarbone hollow, so the chest reads as one convex plane instead of dipping into the hollow.
- **Lapel edge.** It's now a rounded, pressed edge 3.5 mm thick (a bead of 1.2 mm radius on the edge, a soft fall to the roll), with a 16 mm roll and two lip rows on the gorge edge. The edge stitch is a mark 6 mm in from the edge, and the notch has a clean step.
- **Shoulder and sleeve.** Natural shoulder: the pad is thinner and the rope rises 6 mm at the head, then drops. The shoulder line drops 4.5 mm from the neck point to the shoulder point. That is the body's own slope (about 9–10°) plus the cloth, not an extra 2–3° shoulder drop on top (see §4).
- **Armpit sliver.** A clearance pass (`clear_armpits`) pushes jacket vertices in the scye zone 4 mm off the body (139 vertices), run twice.
- **Sleeve-head pinch.** In the shoulder zone, weights are blended over torso + arm (`shoulder_weights`) and then spatially smoothed (3 cm radius, 2 passes, top 4 kept, `Garment.smooth_weights`). Before this, the nearest-vertex weights flipped from torso to upper arm along one row, which pinched the head when the arm was raised.
- **Skirt on a raised thigh.** Each skirt column takes an angle-dependent leg share (front 0.85, side 0.5, back 0.3) of its own panel's thigh, plus pelvis, with grid smoothing (4 passes) and top 4 kept. The left panel follows the left leg and the right panel the right. Before this, the skirt took pelvis weights only and rode up through a raised thigh.
- **Pockets, buttons.** The pocket flaps have thickness (an edge turned in 2.5 mm), rounded bottom corners (12 mm) and stitch marks. The buttons have a rim and a dish (`disc(..., rim=True)`, 16 segments). The welted breast pocket, double vents and the four cuff buttons were already there and are kept.

### Trousers (`suit_trousers.py`, a fork merged in this round)

Parametric trousers built on the body replace the stock shell:

- flat front, natural rise, with the waistband top at 0.627 × stature, under the waistcoat
- slim straight leg: thigh 30.2 cm flat, knee 21.4 cm, opening 19.2 cm
- quarter break (front hem on the vamp at z 0.108, back hem at 0.035)
- 1.5 mm pressed-crease ridges
- slanted side pockets, jetted back pockets, side adjusters

In this round I also flipped the face winding. The quads faced into the leg on both sides; the faces' signed volume was negative. That zeroed the facing-gated drape regions (knee back, break) and inverted the fold sign. In a single-sided game material, it would also have culled the trousers.

### Face orientation (all garments)

Checked against the skeleton (`/tmp/suitwork/ncheck4.py`: a face points out when its normal points away from the nearest bone segment; the skin can't be the reference because `hide_body` deletes it under the cloth). Two more inverted pieces were found and fixed:

- **The left sleeve** (about 860 faces) pointed in. Both sleeves' columns turn the same way about their own arm axis, so they need the same winding, but the code flipped only the right one.
- **The left shirt cuff** pointed in for the same reason.

Blender shades back faces, so neither showed in renders. But Track F's rest-pose tuck sinks inner layers along −normal. On the inverted pieces it pushed the left shirt cuff out through the sleeve: a white band with a sawtooth edge, visible at the left wrist (`20261012T204934Z-suitD-v2a/suit_studio/cuff_x.png`; the pair is `suit_ba/cuff.png` in v2c).

The shoes, trousers, waistcoat and tie are now all outward. The only inward faces left are 17 at the back of the shirt collar, where the single-sheet collar folds over, which is expected for a fold.

### Fixes after Track F's merge (`suit_inner.py`, `suit_jacket.py`, `suit.py`; runs sf1–sf6, v2c)

- **Shirt front under the collar points.** The front panel's top edge was a level line at the centre-front height, while the collar band's bottom edge rises round the neck, so a white ledge stood out under each collar point. `front_to_neckline` now stretches each column up to 1.5 mm under the band and re-lofts it on the torso: fully for |x| < 4.5 cm, fading out by 6.5 cm, where the jacket collar covers it. Running it into the band (sf1) made the shirt self-intersect (suit_collar 179 > 120).
- **White diamond under the knot.** The tie blade's dimple pulled the blade behind the shirt just under the knot. Now:
  - The dimple is a smooth profile kept 2.5 mm off the shirt.
  - There is no dimple on the first row, which tucks up inside the knot (sf3, with a dimple there, raised the tie/shirt overlaps and failed suit_collar at 121).
  - The blade's top row is raycast against the shirt and held 1.5 mm in front of it.
- **Vent underlaps.** Each vent's underlap strip now runs toward the centre back, in the panel's tangent plane, 3.5 mm under the back panel. Before, the strip followed a fixed column step, which sent the left one outward through the side panel, so it poked out at the vent top (`suit_ba/vent.png`). Two intermediate rules tried in sf5 made both vents poke out.
- **Surface noise.** The roughness noise went from 0.06 to 0.03 and the albedo noise from 1.5 % to 0.8 %. At the larger values the lapels and the chest read as stained in the close-ups (`suit_ba/gorge.png`).

### Cloth-sim folds (`suit_drape.py`)

The jacket and trousers are simulated from P0 (arms raised 12°) to P1 (elbow −18°, knee 14°, hip 8°) on a subdivided copy. The fold height is the high-passed normal offset of the cloth from the skinned shape. It is gated by region (elbow, armpit, lower back, button pull, crotch, knee back, break), soft-clamped to 4 mm and baked into the normal, AO and cavity maps through the UVs. A quality gate (penetration, strain, settle, wavelength, amplitude) drops the folds rather than shipping crumpled paper. This round:

- Regions are placed on rest positions (the posed knee and foot move several cm from the rest landmarks).
- Trouser pins: the waistband and seat are pinned, the leg is soft (0.12), and the hem is fully pinned below 12 cm, ramping to 20 cm. With the hem soft, the shoe collider pushed the break into a crumpled ring (p99 strain 0.78), and the gate dropped all the trouser folds.
- The jacket gain outside the regions went from 0.35 to 0.1, and the denoise from 2 to 4 graph-smoothing passes. At 0.35 the sim's grid-aligned ripples printed on every panel as a faint windowpane check (visible in the lookdev front view of `suitD-v2a`).
- Result (`suitD-v2b`; `suitD-v2c` reuses the same cached sims and gets the same numbers): both gates pass.
  - Jacket: p99 strain 0.093, fold RMS 1.34 mm, wavelength about 9 cm, 0.2 % inside the body. The region vertices are elbow 748, armpit 2522, lower back 1481, button 3692.
  - Trousers: p99 strain 0.118, fold RMS 0.92 mm, 0 inside. The regions are knee back 1154, crotch 313, lower back 437 and break 1908; the break is pinned, so its folds stay faint.
  - The drape cache key changed (winding, gain), so this was a fresh sim: 114 s on the drape.

### Materials (`suit_textures.py`, `suit_leather.py`, new `suit_hero.py`)

- **Wool**: albedo (0.013, 0.014, 0.019) linear, a blue-black about 0.014, roughness 0.68, specular 0.15. Sheen 0.35, sheen roughness 0.4, tint (0.72, 0.8, 1.0). The baked surface maps carry roughness and albedo noise, cavity and fold AO, and Kuwahara r 1. The swept variants on the hero rig (`/tmp/suitwork/w1cmp.png`, `w1tt.png`) were:
  - (0.020, 0.021, 0.025) with sheen 0.22: dark brown under the 3000 K key (Track E's flag)
  - ×(0.7, 0.76, 0.95) with sheen 0.3: still warm
  - ×(0.6, 0.64, 0.8) with sheen 0.35 and a cool tint: reads as a warm black, not brown, while the turntable stays a dark charcoal with a faint cool cast

  The shipped value sits between the last two.
- **Shirt-to-wool luminance** (median, suit_views `--lum`, EEVEE, `suitD-v2c`): 47.2 : 1 (bust) and 50.0 : 1 (body) under the neon rig; 27.7 : 1 and 24.0 : 1 under the studio rig. The target is ≥ 20 : 1. The round's starting point (`/tmp/suitwork/base`, same tool) gave 21.9 / 24.9 under neon and 12.6 / 11.1 under studio. The mean ratio is lower (16.7–28.0) because the sheen rim and the lit shoulders lift the wool's mean.
- **Hero-only detail** (`suit_hero.py`, a new `suit_hero` build step after `export_glb`, so the GLB is unchanged): a 0.6 mm 2/2 twill as a procedural bump (yarn-modulated diagonal rib, strength 0.4, 0.2 mm), chained after the baked normal map on every wool material, and subsurface on the shirt (0.15, 1.5 mm, red-shifted radius). The atlas twill is only a faint 1.9 mm pattern (period > 2 px, so it doesn't alias).
- Shoes (a fork, merged): parametric cap-toe derbies on a last fitted to the foot:
  - V-split upper with a cap step, back-stay, tongue, collar lip, punched eyelets, crossed laces with a bow
  - welt with wheeling, bevelled sole edge, stacked heel
  - leather CRM map: clear coat 0.92 on the cap, 0.45 on the quarters; roughness 0.17 cap, 0.28 quarters; flex creases on the vamp

## 2. Measurements (direction config)

| | value |
|---|---|
| stature | 1.851 m |
| jacket hem | z 0.8675 (0.573 × suprasternale) |
| button stance | 0.615 × stature |
| gorge | z 1.4818, 3.2 cm below the suprasternale |
| lapel width | 8.0 cm |
| waist suppression | 0.726 |
| shoulder over body | 2.4 cm |
| trousers waistband top | 0.627 × stature, 2.5 cm under the waistcoat bottom |
| leg opening, knee, thigh (flat) | 19.2, 21.4, 30.2 cm |
| seat ease | 2.4 cm |
| suit tris (GLB) | jacket 13108, shirt 2199, waistcoat 3000, buttons 2130, tie 456, shoes 4824, trousers 3824 (29541) |
| character total (`suitD-v2c`) | 129537 tris (≤ 150k), 81 bones with Track F's helpers and skirt bones (≤ 90), ≤ 4 weights per vertex, 0 glTF errors |

## 3. Verdicts per defect

All verdicts are on `suitD-v2c`, judged by the beauty frames (hero rig, turntable, EEVEE close-ups). The guards come first:

- `suit_check`: PASS (all 15 silhouettes 0 px, armhole edges open 0)
- `suit_collar`: PASS (skin 0 px in all four views; self-intersection shirt 44, jacket 65, tie 3, total 112 ≤ 120; every layer pair 0)
- `suit_pose_test`: the same per-layer counts as `v2b`
- Track F's `deform_test`: rest 0, knee_up 8, arm_raise 4, head_turn 3, walk 2 pokes

| defect | verdict | evidence |
|---|---|---|
| Grey, boxy costume; should read as black wool under neon | **Fixed.** Under the hero key the wool reads as a warm black with a cool sheen rim, and the turntable is a dark charcoal. Shirt:wool median luminance is 47.2 : 1 (bust) and 50.0 : 1 (body) under neon, and 27.7 / 24.0 : 1 under studio. The base was 21.9 / 24.9 and 12.6 / 11.1. The EEVEE neon close-ups at high exposure (`suit_gorge/`) show the wool taking the amber key's colour, as any black cloth does. | `suit_hero/hero_bust.png`, `suit_ba/hero_bust.png`, `suit_lum/lum.json` |
| Brown cast under the hero key (Track E) | **Fixed** (cooler, darker albedo, cool sheen tint) | `suit_ba/hero_bust.png` |
| Lapel wings at the shoulders (Track E) | **Fixed.** The collar end lies on the roll line, and the gorge is dropped. | `suit_ba/tt0.png`, `suit_clay/` |
| Seat-length jacket, waist suppression | **Fixed.** The hem covers the seat; suppression is 0.726. | `suit_ba/tt180.png` |
| Natural shoulder, roped head | **Partly fixed.** The shoulder line follows the body with a thin pad, and the 6 mm rope at the head reads in the clay shoulder view but only faintly in the beauty frames. | `suit_clay/shoulder_front.png` |
| Shirt cuff 1–1.5 cm | **Fixed** on both wrists. The left cuff's sawtooth band in `v2a` came from the inverted faces. | `suit_ba/cuff.png` |
| Rounded lapel edge, stitch, clean notch | **Partly fixed.** The edge bead, the 6 mm stitch and the roll read in every view. The notch reads in the hero bust. In the EEVEE close-up, though, the collar end still looks like a long strap with a small fold at its corner (`suit_clay/notch.png`). The lapel point also sits high and reads a little peaked from below. | `suit_studio/notch.png`, `suit_clay/notch.png` |
| Welted breast pocket, flapped hip pockets, 4 cuff buttons, real buttons | **Fixed.** The flaps have thickness and rounded corners, and the buttons are rimmed and dished. | `suit_studio/pocket_x.png`, `suit_studio/cuff_x.png` |
| Double vents | **Fixed.** In `v2b` the left vent's underlap poked out at the vent top; both are clean slits now. | `suit_ba/vent.png` |
| Waistcoat with buttons | **Kept from v1.** In the V it reads only as a dark layer, and its buttons don't read at hero exposure. | `suit_hero/hero_bust.png` |
| Trousers: flat front, slim leg, quarter break, crease | **Fixed** (parametric; 19.2 cm opening, crease ridge, break on the vamp) | `suit_hero/turntable_*.png` |
| Baked cloth-sim folds (elbow, inner arm, knee back, button, crotch) | **Partly fixed.** Both gates pass and there is no crumple. The folds are deliberately soft (RMS 1.3 mm on the jacket, 0.9 mm on the trousers), so they read as soft shading at the elbow and knee back rather than as defined folds. A faint ring line remains at the elbow. | `suit_hero/hero_full.png` |
| Wool sheen, twill, fuzz, glossy facing; silk tie; translucent shirt; polished cap-toe shoes | **Fixed.** Fuzz is carried by the sheen. The twill is a faint baked pattern in the GLB plus a 0.6 mm bump in the hero `.blend`. The facing is 0.10 smoother. The roughness and albedo noise were halved in `v2c` because they read as stains. | `suit_studio/shoe_x.png`, `suit_final/` |
| Armpit sliver | **Fixed at rest** (clearance pass; deform test rest 0) | `deform-suitD/sheet_rest.png` |
| Skirt riding up through a raised thigh | **Partly fixed.** The skirt now follows its own thigh instead of the pelvis, so it no longer cuts through the leg. On a raised knee it is a flat board (Track F issue 4). | `deform-suitD/sheet_knee_up.png` |
| Sleeve-head pinch | **Fixed** in the arms-up and arm_raise poses: the head stays round. | `deform-suitD/sheet_arm_raise.png` |
| EEVEE-only: shadow speckle on the shirt beside the lapels | **Open, EEVEE only.** It is absent in Cycles, so it is a look-dev artefact, not geometry. | `suit_studio/bust.png` |
| (found this round) horizontal crease across both fronts at the button | **Open.** The fronts follow the body's front waist dip, about 8 mm at x ±6 cm, which bends sharply just under the button (z 1.13–1.15); the baked button-pull folds sit on the same line. It reads as a soft waist seam in the hero bust. Tried in fb1 and fb2 (§8) and reverted: a full chest-to-belly hull stood the front 2 cm off the waist, and an outward smoothing round the button moved it only about 2 mm. The likely fix is a front dart (suppression taken out along a vertical line rather than following the body), plus a check that the button region doesn't fold horizontally. | `suit_final/hero_bust.png`, `suit_waist_clay/torso.png` |
| (found this round) the collar ends stand up beside the neck as two straps | **Open.** In the clay front view the collar's front ends rise from the notch to the neck as narrow vertical strips. That is the same defect as the notch's "long strap" above. | `suit_waist_clay/torso.png` |

### Track F's four issues

1. **Trousers pierce the jacket skirt by up to 27 mm at rest.** **Fixed by the v2 trousers.** In F's rest test, `trousers>jacket` is 605 covered and 0 outside at rest, and my pierce test (`/tmp/suitwork/fpierce.py`, F's method) gives 0 trouser vertices outside the jacket at rest (run on v2b; the trousers are unchanged in v2c). The old stock shell was the one piercing.
2. **Lapel crumple and a jagged collar edge.** **Improved.**
   - The v2 collar seam follows the neck, and the lapel edge is rounded and pressed.
   - The shirt front now ends 1.5 mm under the collar band instead of standing as a white ledge under the collar points.
   - The left shirt cuff and sleeve are no longer inverted, so the tuck can't push them out.

   In the arm_raise and head_turn tiles the lapel is smooth. head_turn still has 3 shirt-through-jacket pokes of ≤ 3 mm at the collar.
3. **Body remnants under the right shoulder.** **Not fixed in the mesh, but not visible at rest.**
   - The remnants are body patches that `hide_body` keeps under the cloth, because they are not fully covered in every view.
   - Rest gives 0 pokes. In the posed tests they give 1–2 body pokes at the deltoid helpers: knee_up 1 (6 mm); arm_raise 2 (up to 31 mm, at x 0.05, z 1.53, behind the tie and shirt in the beauty tile); walk 2 (up to 20 mm).
   - None of these shows in the beauty tiles of `deform-suitD`.
   - I did not change `hide_body` this round, so the remnants stay a known item for the next deletion pass. The risk there is opening holes where the cloth stands off the body.
4. **The raised skirt reads as a flat board on a raised knee.** **Not fixed; handed to F's cloth-settle correctives**, as F proposed. The garments are final for this round (`suitD-v2c`).

## 4. Deviations from direction.md (numbers were starting points)

- **Wool albedo and sheen.** Sheen 0.35 and sheen roughness 0.4 as directed. The albedo is darker and cooler than the directed 0.025: (0.013, 0.014, 0.019) linear. The sheen also has a cool tint (0.72, 0.8, 1.0), which direction.md doesn't specify. At 0.025 with a white sheen, the wool read dark brown under the 3000 K hero key (Track E's flag, reproduced in `hero0` and the sweep `/tmp/suitwork/w1cmp.png`). The darker, cooler value keeps the turntable a dark charcoal rather than a flat black, and puts shirt:wool at 47–50 : 1 under neon.
- **Surface noise.** The roughness noise is ±0.03 and the albedo noise ±0.8 % (they were 0.06 and 1.5 %). At the larger values the lapel and gorge close-ups read as stains rather than fibre.
- **Twill** is procedural (Cycles bump in the hero `.blend`), not a downloaded tile. No external texture asset was added, so there is nothing new for `provenance/mesh.jsonl`.
- **Jacket hem** is at 0.573 × suprasternale (2.5 cm under the gluteal fold), not the look-spec 0.50. At 0.50 the hem sat mid-thigh (z 0.755, the round's starting point) and read as a short coat on these long legs. The rule is now "just covers the seat", driven by the seat fold, which on this figure also matches the knuckle rule.
- **Shoulder drop.** No extra 2–3° drop is built in. The body's shoulder line already slopes about 9–10°, and the jacket shoulder follows it with a 4.5 mm drop from the neck point to the shoulder point, plus the rope rising 6 mm at the head. Read the 2–3° as "don't square the shoulder", which is satisfied.
- **Sleeve pitch** comes from the arm in the rest pose (the forearm hangs well forward); there is no separate 10° pitch on the sleeve.
- **Shoe "heel pull"** is read as the back-stay strip.

## 5. Shared-file edits

- `blender/build_character.py`: one additive line, `b.step("suit_hero", suit.hero)` between `export_glb` and `save_blend` (hero-only Cycles detail goes into the `.blend`, never the GLB).

## 6. Notes for Track F (deformation, merged at ff03f62)

- **Order of the stages.** The suit writes its own weights, and F's `deform_rig` stage then remaps them (helper bones, generic garment smoothing, arm-free core, skirt bones by azimuth, correctives, rest-pose tuck). The suit's weights are F's input:
  - shoulder zone: torso + arm, spatially smoothed
  - skirt: each panel's own thigh + pelvis, grid-smoothed
  - all at ≤ 4 influences, normalised

  F's `skirt_weights` reads the leg share from them.
- **Face winding matters to the tuck.** `tuck` sinks hidden inner layers along −normal, so an inward-facing garment is pushed out through its cover. This round found and fixed two such pieces: the left sleeve and the left shirt cuff (§1, face orientation). All garments now face out, apart from 17 faces where the shirt collar folds over. A winding check in F's harness, such as signed volume per closed garment or the normal against the nearest bone, would catch a regression.
- **The suit is final for this round.** F's cloth-settle correctives for the raised-knee skirt (issue 4) can be built on `suitD-v2c`.

## 7. Evidence

The official runs are under `data/build/lookdev/`, built with `THREADS=3 KEEP_BLEND=1 bench/m1/lookdev.sh --config bench/m1/variants/direction.json <label>`:

- `20261012T204934Z-suitD-v2a`: the first build on main with Track F (left cuff through the sleeve)
- `20261012T205805Z-suitD-v2b`: winding fixes and the drape gain; guards and F's deform test
- **`20261012T212723Z-suitD-v2c`**: final. Built on main 3315819 (Track A skin v2 + Track F). 129537 tris, 81 bones, ≤ 4 w/v, 0 glTF errors.

Inside `suitD-v2c`:

| dir | what |
|---|---|
| `suit_ba/` | before/after pairs (left = before): `hero_bust.png`, `tt0.png`, `tt180.png` (the round's start `/tmp/suitwork/base` → v2c, hero rig and turntable at preview quality; the base is a scratch build without head refine or hair, so compare only the suit); `cuff.png` (v2a → v2c, left cuff); `vent.png` (v2b → v2c left, v2c right); `gorge.png` (v2b → v2c, studio: the white diamond under the knot and the stain-like noise gone) |
| `suit_final/` | Cycles at 256 samples, full resolution: `hero_bust.png` (hero light), `turntable_tt0.png` |
| `suit_hero/` | Cycles preview: hero bust, full, back, hands; turntable at 0°, 45°, 180°, 270° |
| `suit_studio/`, `suit_neon/` | EEVEE close-ups: notch, lapel edge, pocket, cuff, shoe, bust |
| `suit_clay/` | clay: notch, lapel edge, collar side, collar close-up, pocket, shoulder |
| `suit_vent/`, `suit_gorge/`, `suit_gorge_studio/` | both vents (studio); gorge, knot, neck front (neon); gorge (studio) |
| `suit_waist_clay/` | clay: V bottom, front, torso (the button crease and the collar ends) |
| `suit_lum/`, `suit_lum_studio/` | shirt:wool luminance (`lum.json`) |
| `suit_check/`, `suit_collar/`, `suit_pose/` | the suit guards |
| `deform-suitD/` | Track F's `deform_test` (rest, knee_up, arm_raise, head_turn, walk) |

## 8. Iteration log (run dir → change → verdict)

All scratch runs are under `/tmp/suitwork/` (no-head-refine builds for iteration). The official runs are listed in §7.

| run | change | verdict |
|---|---|---|
| base | the round's starting point (grey boxy jacket, stock trousers, stock shoes) | grey, block shoulders, flat lapel stripe, lapel wings at the shoulder |
| hero0 | base under the Track E hero rig | confirmed the wings and the brown cast under the amber key |
| mat (sweep) | wool albedo, sheen and tint grid in EEVEE | sheen alone does not make it read black, and the floor bounce dominates |
| dr1–dr3 | first cloth-sim drape on the jacket (level 1, then pins and stiffness on the canvas) | dr1 crumpled (no canvas stiffness); dr3 passes the gate with elbow and armpit folds |
| cut1 | jacket covers the seat, rounded quarters | length right; wings still at the shoulder (`cut1_wings.png`) |
| cut2–cut4 | gorge dropped 4.5 cm, collar end moved onto the roll line, neck seam close | wings gone in clay; a shelf at the gorge and a gap at the collar side |
| cut5, cut5b | strip between the ring and the neckline pushed clear; lift limited to 4 cm | the collar-side "hole" (skin through the strip) closed |
| cut6, cut6g | rounded lapel edge (3.5 mm, 1.2 mm bead), 16 mm roll, edge stitch 6 mm | the lapel reads as cloth with an edge; notch clean |
| m1 | shoes fork merged | derbies with cap, welt and laces read at close-up |
| s1 | armpit clearance pass | sliver at rest gone |
| s2–s4 | shoulder-zone weights over torso + arm, smoothing; skirt leg weights | arms-up pinch reduced; kick pose: the skirt follows the leg |
| p1 | pocket flaps with thickness and rounded corners, rimmed buttons | flap reads as a separate layer; cuff 1–1.5 cm shirt shows |
| f1, f2 | full builds after the trousers merge, with drape | guards pass; the trousers drape failed the strain gate (the folds were dropped) |
| t1 | trousers faces flipped outward, hem pin over the break 0.6 | p99 strain 0.78 → 0.36, still failing (the hem crumples against the shoe) |
| t2 | hem fully pinned below 12 cm | trousers gate passes (p99 0.13, 0 inside); knee-back and crotch folds baked |
| w1 (sweep) | wool albedo, sheen and tint on the hero rig and the turntable | (0.6, 0.64, 0.8) × with a cool sheen reads black, not brown (§1 materials) |
| `suitD-v2a` | first official build, rebased on main with Track F's deform stage; cool wool | the left shirt cuff sawtooths out through the left sleeve at the wrist; faint windowpane check on the jacket |
| `suitD-v2b` | the left sleeve and left shirt cuff faces flipped outward; drape base gain 0.35 → 0.1, 4 denoise passes | cuff band gone; check gone; guards pass; F's deform test: rest 0, knee_up 8, arm_raise 4, head_turn 5, walk 2 |
| sf1 | shirt front's top edge raised into the collar band (white ledge under the collar points) | ledge gone, but shirt self-intersection 179 > 120: suit_collar fails |
| sf2 | the front stops 1.5 mm under the band, following it near the centre only | ledge gone; collar isect 113, passes |
| sf3 | smooth tie dimple, blade top tucked in front of the shirt (white diamond under the knot) | diamond gone, but tie/shirt overlaps 4 → 12: collar isect 121 fails |
| sf4 | no dimple on the blade's first row (it tucks up inside the knot) | diamond gone; collar isect 109, tie/shirt 0 |
| sf5 | intermediate underlap-direction rules (neighbour column picked by the sign of x, then away from the panel's own faces) | both vents poke out at the vent top (`/tmp/suitwork/sf5_vent.png`) |
| sf6 | vent underlap toward the centre back, in the tangent plane, 3.5 mm under the panel | both vents are clean slits (`/tmp/suitwork/sf6_vent.png`); collar isect 109 |
| `suitD-v2c` | sf6 + wool roughness noise 0.06 → 0.03, albedo noise 1.5 % → 0.8 %; rebased on main (Track A skin v2) | final: see §3 and §7 |
| fb1 | front waist: upper hull of each front column's radius, belly to chest (after v2c) | the front stood 2 cm off the waist with a shelf at the button; reverted |
| fb2 | front waist: outward 1-2-1 smoothing (4 passes, capped at 5 mm) round the button | the crease softened only slightly (about 2 mm); guards pass; not worth regenerating the evidence; reverted, open in §3 |

## 9. Branch

`worktree-agent-a7cee946dd031f936`, rebased on main d7f2b1a (Track C facial hair, after Track E's hero stage).

- `suitD-v2c` was built from aea7fcd on main 3315819. After the rebase that commit is bb21732, and the suit files are identical.
- A cut build on the rebased tree (`/tmp/suitwork/final_main`) passes `suit_check` and `suit_collar` (isect 109).
- The report commit sits on top of bb21732 and changes only this file.
