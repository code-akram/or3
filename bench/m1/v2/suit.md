# m1 v2 Track D: the suit

Goal (BRIEF, direction.md defect 7): turn the grey, boxy costume into a sharp, close-cut near-black three-piece that reads as black wool under the neon-noir hero light and the turntable. Everything is still built on the body by script; the GLB stays game-ready and the Cycles-only detail goes into the kept `.blend` after the export.

## 1. What changed

### Jacket cut (`suit_jacket.py`, `suit_neck.py`, `suit_build.py`, `suit.py` DEFAULTS)

- **Length and skirt.** The hem comes from the seat fold (`seat_fold`), so the jacket just covers the seat: hem z 0.8675 = 0.573 × suprasternale height (look-spec said 0.50, which left the seat bare on this body). Below the hip the rings are sliced over torso + thighs, so the skirt clears the thighs instead of cutting through them. Rounded front quarters.
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

### Cloth-sim folds (`suit_drape.py`)

The jacket and trousers are simulated from P0 (arms raised 12°) to P1 (elbow −18°, knee 14°, hip 8°) on a subdivided copy. The fold height is the high-passed normal offset of the cloth from the skinned shape. It is gated by region (elbow, armpit, lower back, button pull, crotch, knee back, break), soft-clamped to 4 mm and baked into the normal, AO and cavity maps through the UVs. A quality gate (penetration, strain, settle, wavelength, amplitude) drops the folds rather than shipping crumpled paper. This round:

- Regions are placed on rest positions (the posed knee and foot move several cm from the rest landmarks).
- Trouser pins: the waistband and seat are pinned, the leg is soft (0.12), and the hem is fully pinned below 12 cm, ramping to 20 cm. With the hem soft, the shoe collider pushed the break into a crumpled ring (p99 strain 0.78), and the gate dropped all the trouser folds.
- Result: TODO

### Materials (`suit_textures.py`, `suit_leather.py`, new `suit_hero.py`)

- Wool: TODO final values.
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
| character total | TODO tris, 53 bones, ≤ 4 weights |

## 3. Verdicts per defect

TODO

## 4. Deviations from direction.md (numbers were starting points)

- **Sheen** TODO.
- **Twill** is procedural (Cycles bump in the hero `.blend`), not a downloaded tile. No external texture asset was added, so there is nothing new for `provenance/mesh.jsonl`.
- **Jacket hem** is at 0.573 × suprasternale, not the look-spec 0.50, because at 0.50 the seat showed below the hem on this body. The rule is "covers the seat", driven by the seat fold.
- **Shoulder drop.** No extra 2–3° drop is built in. The body's shoulder line already slopes about 9–10°, and the jacket shoulder follows it with a 4.5 mm drop from the neck point to the shoulder point, plus the rope rising 6 mm at the head. Read the 2–3° as "don't square the shoulder", which is satisfied.
- **Sleeve pitch** comes from the arm in the rest pose (the forearm hangs well forward); there is no separate 10° pitch on the sleeve.
- **Shoe "heel pull"** is read as the back-stay strip.

## 5. Shared-file edits

- `blender/build_character.py`: one additive line, `b.step("suit_hero", suit.hero)` between `export_glb` and `save_blend` (hero-only Cycles detail goes into the `.blend`, never the GLB).

## 6. Notes for Track F (rig.py owner)

- No helper bones are needed by the suit. The jacket's shoulder-zone and skirt weights are computed in `suit_jacket.py` from the body weights:
  - shoulder zone: torso + arm, spatially smoothed
  - skirt: each panel's own thigh + pelvis, grid-smoothed
- Everything stays at ≤ 4 influences, normalised.
- If rig.py adds twist or helper bones, the suit picks them up through `body.weights()`. The bone sets are `suit_build.TORSO / ARM / LEG`, so a new deforming bone must be added there for the garments to use it.

## 7. Evidence

TODO

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
