# T13 phase B: the pattern-drafted suit rebuild (running report)

The suit is being rebuilt as real tailoring: drafted panels, sewn and draped (numpy XPBD), then made up with a modelled rever, turned edges, lining, pockets, vents and buttons. Phase A (spike 2) is in `t13a-suit-spike2.md`. This file gets one section per §6 item, in order.

| item | what | state |
|---|---|---|
| 1 | jacket detail, plus the phase A review fixes | **done**, accepted (open points below, to be fixed before item 6) |
| 2 | UVs from panels (grain), port the `suit_textures.py` marks | **done** |
| 2b | item-1 review points 1–3 (back collar roll, vents visible, front quarters cutaway) | next, before item 6 |
| 3 | trousers | |
| 4 | waistcoat | |
| 5 | shirt (collar band and fall to the `suit_neck.py` frame) | |
| 6 | rigging (weights, Dem Bones, correctives); re-measure the armpit/cuff hinges | |
| 7 | per-pose wrinkle maps | |
| 8 | integration behind a config switch, with guards and caching by body hash | |

Runs for item 1 (all under `data/build/suit_spike/`, lookdev base `20261014T205840Z-t15-a5`, body sha `38e72e8b4511`, 13,380 verts, post-T22):

- `20261014T222326Z-t13b-j5` is the drape (XPBD, debug rever).
- `20261014T223453Z-t13b-j5det` is its determinism twin.
- `20261014T224347Z-t13b-d4` is the made jacket from j5's drape: clay A/B, detail close-ups and LODs. Its `beauty_*.png` are the Cycles frames.

Gate pictures are in `data/build/t13/gate/phaseB/item1/`.

## Item 1: the jacket made up

**Answer: done.** The coordinator's four review points are fixed, with the numbers below.

The jacket now has every detail asked for, each placed from a pattern mark:

- flap pockets with jets;
- a breast welt;
- double back vents and sleeve vents;
- a keyhole buttonhole with the front button;
- four kissing cuff buttons per sleeve;
- turned edges with thickness on every free edge;
- a lining inside, with wool facings and turn-ups.

All guards pass. Clay at 100 % reads as a single-breasted, one-button, notch-lapel suit jacket, and the Cycles frames show it in its lookdev wool.

The textured wool weave waits for item 2: the pattern meshes have no UVs yet.

### What I see (frames at 100 %, before the numbers)

- **Front (clay, `pattern_front.png`).**
  - The hem ends at the crotch line and the front quarters cut away from the button.
  - The waist is shaped, with the front dart running into the pocket line, and the skirt hangs straight, with no flare.
  - The flap pockets sit level across the hips. The breast welt rises toward the armhole on the wearer's left.
  - The one button sits on the waist line with the buttonhole slit running toward the side.
  - The lapel edge is clean. The sawtooth along it is gone; see the fixes below.
- **¾ (clay and beauty).**
  - The lapel rolls from the break to the notch.
  - The pocket flaps follow the hip, and the jet shows as a thin lip above each flap.
  - The sleeves are slim to the cuff, with the shirt cuff showing.
  - The beauty frame reads as a dark suit. The edges, flaps and welt catch the key light the way pressed edges do.
- **Profile.**
  - The back follows the shoulder blades and comes in at the waist; it is less of a tube than in phase A.
  - The sleeve narrows from elbow to cuff, and the cuff buttons show at the back of the cuff.
- **Back.**
  - The back is smooth, with the waist shaped and the collar lying down onto the back.
  - Two vent lines run up 22 cm from the hem on the back/side seams. Closed and on a standing figure they are subtle, as real vents are.
  - The ends of the pocket flaps peek round the sides.
- **Close-ups.**
  - Pocket: the flap has rounded lower corners, a 2.6 mm thickness and a turned edge.
  - Button: the dished face has four holes and a raised rim, and it stands on its shank off the cloth.
  - Cuff: four kissing buttons sit beside the hind seam.
  - Hem: the front edge and hem have a rounded turned edge.
  - Collar back: stand, roll and fall read, and the fall edge lies on the back with no gap.
- **LOD1 and LOD2.** Both hold the silhouette, the pockets and the lapels. LOD2's flaps are lumpy at 9k tris.

**What is still not real tailoring:**

- The lapel's last 2 cm into the break reads as two fine ridges (the lapel edge and the roll line) rather than a lapel lying flat. It is visible only in the 0.10 m button close-up.
- The vents are a line with a 3.5 mm step. A real vent's extension and the lap's turned edge are not modelled as separate cloth.
- The wool has no weave (item 2). The beauty frames use the lookdev `suit_wool` without UVs, so it reads smoother and a little more satin than the lofted jacket's.
- Each hip-pocket jet dips about 1 mm where it crosses the front dart, following the dart seam.
- The buttons' holes are blind, with no thread.
- In the collar-back beauty frame, a sliver of the white shirt collar shows where the collar's fall ends at the shoulder seam (about 3 mm).

### The phase A review, point by point

| review point | change | result |
|---|---|---|
| 1. 8–10 cm too long; should end at about the crotch | `length_frac` 0.475 → 0.44 (nape to hem 69.8 cm; CB seam 71.9 cm) | hem at z 0.888 m against a crotch at 0.910 m, so 2.2 cm below the crotch line (it was 7.7 cm) |
| 2. too little suppression at the front and side; boxy; the skirt flares | fisheye front dart (13 % of the waist suppression, from 4 cm below the chest line into the pocket line), side suppression shares cb 0.22, back/side 0.40, side/front 0.25, `hem_flare_cm` 0, a 4 cm canvas band at the hem | jacket half waist 47.7 against half chest 58.2 (0.82); the skirt hangs straight; the dart seam is clean (hinge max 8.6°, 0 over threshold); the CB hinge is 8.9° max (the neck-edge 42° of run j1 is gone) |
| 3. sleeves bell at the cuff; 13–14 cm half cuff, keep the 25° pitch | cuff ease 13 → 11 (cuff 25.8 cm, **12.9 cm half**), no extra elbow width (elbow 33.2 cm), **no canvas band at the cuff**; the 25° bend is kept | the draped sleeve narrows monotonically: 29.8 cm round 10 cm above the cuff, 31.7 at 18 cm, 34.6 at 30 cm. The bell had two causes: the forearm taper was too gentle, and a stiff cuff band (flat-rest bending round a 4 cm tube) opened the end. 12.9 is 0.1 cm under the asked range; I kept it because 13.4 still read as a bell at this body's 14.8 cm wrist |
| 4. shoulders slope a little | `pad_cm` 1.2 → 1.5, `shoulder_drop_deg` 3.0 → 1.0 | the shoulder line runs nearly level to the pad, with a natural round over the sleeve head (front and back frames); no roping |

The A/B sheet has labelled columns (lofted | pattern) at front, ¾, profile and back: `ab_sheet.png`. The Cycles A/B is `beauty_sheet.png`.

### What was built (`blender/character/suit_detail.py`, new)

Everything is placed by draft marks: `suit_pattern.py` now carries notches `hip_pocket`, `breast_welt`, `buttonhole` and `cuff_buttons`, drawn on `pattern.svg`. A `PanelMap` maps them onto the drape: it finds the flat triangle holding the point and applies the same barycentrics on the draped triangle. A point between a dart's legs snaps to a leg. So each detail sits where a cutter would mark it, and later it moves with the cloth.

| part | geometry | numbers |
|---|---|---|
| shell | outside; lining one cloth thickness (3 mm) in; a 5-segment half-round turned edge on every free edge; wool inside the fronts (7 cm facing) and the hem and cuff turn-ups (4 cm) | 36,208 tris (14,318 lining faces). Part tag per face: 0 wool, 1 lining, 2 edge, 3 button |
| hip pockets | flap 15.7 × 5.5 cm, lower corners rounded 1 cm, 2.6 mm thick, under a 0.5 cm jet, 8 cm below the waist; the front dart ends in the line; front end 6 cm in front of the dart (8 cm from CF) | together with the breast welt, 7,280 tris, min clearance 0.39 mm |
| breast welt | 10 × 2.4 cm, rising 1.5 cm toward the side, wearer's left | |
| back vents | back/side seams split from the hem up 22 cm; the back laps over the side body; the lap band steps 3.5 mm proud, fading out over the 3 cm below the vent top | 19 verts per side |
| sleeve vents | hind seam split 10.5 cm up from the cuff; the top sleeve laps | 9 verts per side |
| buttons | 4-hole, dished, raised rim, half-round edge, 1.5 mm thread shank; front 20 mm × 3.6 mm on CF at the waist; cuff 15 mm × 3 mm, four kissing per sleeve, 1.4 cm from the hind seam, the first 3 cm above the cuff | 7,406 tris, min clearance 1.09 mm |
| buttonhole | keyhole on the left front: eye 0.3 cm past CF under the button, 2.4 cm slit toward the side, corded lips (0.9 mm cord) | 384 tris |

**Triangle counts:**

| | tris |
|---|---|
| LOD0 total | **61,594** (shell 36,208 + rever 10,316 + pockets 7,280 + buttons 7,406 + buttonhole 384) |
| LOD1 (decimated to 0.4) | 24,636 |
| LOD2 (decimated to 0.15, no buttonhole) | 9,181 |
| drape mesh | 16,094 |

### Guards (run j5 and d4)

| guard | value | limit / note |
|---|---|---|
| stage-1 sewing gap | mean 0.33 mm, p95 **1.11 mm**, max 3.49 mm | p95 < 3 mm |
| strain against the flat pattern | mean 2.5 %, p99 14.7 % | as phase A (2.5 %) |
| jacket vertices inside body/under-garments | nearest-face rule 1 (−1.3 mm); ray rule 2; **both rules 1** | that one vertex is the right front's button point, under the left front's lap and inside the lofted waistcoat's front; it cannot be seen |
| right front through the left front | worst −1.6 mm (behind) | 0 in front |
| seam hinges | 25: armhole/underarm 21, sleeve hind 4 (2 at the cuff edge) | accepted for the A-pose until item 6 (phase A: 30) |
| rever inside under-layers | 2 by the ray rule (attach line, under the stand) | nearest-face 50 is the known CB fall-edge misreading |
| detail clearance | pockets ≥ 0.39 mm, buttons ≥ 1.09 mm, buttonhole cord touching (0.0) | none sunk into the cloth |
| determinism | X1, Xw and X2 sha256 identical across j5 and j5det | `4e95a46e…` / `57997523…` / `79f5fadd…` |
| sim time | stage 1 64.9 s, stage 2 46.5 s (load average about 25) | |

### Fixes made on the way (each found by looking at a frame)

- **Lapel-edge sawtooth.** The rever's rim was a flat quad strip at 90° to the sheet, sharing smooth-shaded vertices. Its normal tilt followed how many triangles fanned into each boundary vertex, so the edge shaded as teeth about 1.5 cm apart. It is now a half-round rim (5 rings) with the boundary normals smoothed along the loop.
- **Collar split into a V at CB** (`close_collar_back` view, new). The rever's `clear` misread stand vertices that lean in over the neck: they sat in front of a jacket neck edge that rolls in. It snapped them 2–3 cm down onto the jacket, folding the collar flat. Pushes deeper than 1 cm are now treated as misreadings and skipped.
- **Pimples on the collar fall.** Each clearing lift is spread into a 2 cm smooth swell.
- **Back neckline stepped 1.4 cm.** The placement stepped where the back wraps into the shoulder (z jumped 13.6 mm between two neighbouring placed vertices), and the stage-1 neck hold kept it. The hold targets are now the placed line faired (Taubin) and re-spaced by the pattern's arc length; the largest move is 25 mm. A firmer stage-2 hold on the faired line crumpled the collar ends (run `t13b-j4`), so stage 2 keeps stage 1's line.
- **Right front through the left front at the button** (13.5 mm). This had two causes:
  - The button pair was a plain distance constraint, which let the right front's button point pass to the front. It is now a one-sided layer pair in the solver.
  - `push_out`'s crevice march stepped a misread vertex 20 mm out along its normal. The march now requires the ray rule to agree, and it gives up (leaves the vertex in place) if 2 cm is not enough.
- **Lapel tips stood 4 mm off the front at the break.** Over the last 4 cm the lapel now lies down to its own thickness, so its edge meets the front edge.

### What is left in item 1's scope

- The lapel's last 2 cm into the break, as above.
- Vent extensions as their own cloth.
- LOD2 should drop the lining under the outside rather than decimate both.
- The hinges are re-measured after item 6.
- The collar's seating on the post-T22 base: the frames above use the post-T22 body (13,380 verts), and the collar sits clear of the lofted shirt collar in `close_collar_back`. I have not yet checked T22's claim that the neck forms are zero under the collar. That check, and the seat against the rebuilt shirt collar, belong to item 5.

### Item 1 review (coordinator): accepted, with open points

Length, waist suppression, cuff taper and the shoulder line are accepted. Five open points remain. Points 1–3 are fixed before item 6, so that the bone fit uses the final shape:

1. **Back collar.** It stands up like a band. A turned collar rolls over: the fall covers the stand, and the shirt collar shows 1–1.5 cm above it at the back neck.
2. **Vents.** They are not visible on the back. The double side vents (22 cm, the back lapping the side body, 3.5 mm step) are in the geometry but do not read. They should read as closed and overlapped at rest.
3. **Front quarters.** They run nearly straight down below the button. They need the usual rounded cutaway to the hem.
4. **Lapel edge.** It reads as rounded and thick. It should be a crisper pressed edge, 3–4 mm.
5. **Profile.** The skirt stands slightly off the seat. The back skirt should hang onto the seat at rest.

## Item 2: UVs from the pattern, the wool atlas

Runs (from j5's drape, base `20261014T205840Z-t15-a5`):

- `20261014T235644Z-t13b-u6` is the final run: clay, the LODs, the textures in `spike.blend`, and Cycles beauty, grain and LOD frames.
- `t13b-u2` is the first run with a 2048 atlas. `t13b-u3` (2048) and `t13b-u4k` (4096) are the resolution comparison.

Gate pictures are in `data/build/t13/gate/phaseB/item2/`:

- `beauty_sheet.png`: lofted | pattern.
- `grain_sheet.png`: the pinstripe check.
- `beauty_pattern_close_*.png`.
- `beauty_lod{1,2}_*.png`.
- `atlas_normal_1k.png`.
- `cmp_2048_vs_4096_{button,lapel}.png`.

### What I see (frames at 100 %, before the numbers)

- **Grain** (`grain_*`: white lines every ½ in along the grain, red every 5 cm across).
  - The lines run straight down the fronts, back and side bodies, and along the sleeves, with the cross lines level at chest and hem.
  - The front dart shows as the lines converging under the welt, as it would on a striped cloth.
  - The flaps and the welt are on the front's grain.
  - The lapel facings carry their stripes parallel to the lapel edge. The top collar's run up the centre back.
  - The stripes continue round the turned cuff and hem edges.
  - The right and left halves are mirror images.
- **Beauty** (`beauty_pattern_*`).
  - From the front and ¾ the cloth reads as a fine worsted. The twill is visible from about 30 cm (the button and lapel close-ups) and runs diagonally to the grain.
  - The seams read as pressed-open grooves with no stitching: CB, the back and side seams, shoulder, armhole, the sleeve seams and the front dart.
  - The pick stitching shows as a row of small dimples 6 mm in from the fronts' edge below the break, the lapel edge, the notch, and the collar end and fall. It is visible in `close_button`, `close_lapel` and `close_collar_back`.
  - The buttonhole cord shows its purl, as ridges across the cord.
  - The lofted jacket in the same light reads the same tone; the pattern jacket's surface is cleaner.
- **2048 against 4096** (`cmp_*`). At 2048 (0.76 mm/px) the pick stitches are soft 2–3 px blobs and the purl barely resolves. At 4096 (0.38 mm/px) they read as stitches. The made jacket bakes at 4096.
- **LODs.** The textured LOD1 and LOD2 hold the same cloth and seams. The decimation shows only in the silhouette of LOD2's cuff buttons and pocket corners.
- **Not right yet.**
  - A grey mottled patch on the wearer's right lapel roll near the top (`close_lapel`, top left). It is the sheen catching the twill bump at grazing angles on the roll; it is in the 2048 run too.
  - The rever's chart is 21 % short along q on the lapel roll, so the twill is a little finer over that 1 cm band (see the numbers). It cannot be seen at 30 cm.

### What was built

- **`suit_detail.shell_uv`** puts every face corner of the welded drape at its panel's flat pattern coordinates, in metres:
  - The corner coordinates come from the unwelded triangle the face came from, so a seam vertex has one UV per panel.
  - v runs up the panel (the grain). The right-hand copies are mirrored, so the twill has one handedness on the outside.
  - Per panel, it checks that every outside face winds counter-clockwise in UV, and flips u where one does not.
- **The `solid` and `thicken` rims** continue the panel UVs outward across the edge, round the half round (π r per rim), mitred at the corners. The lining and facing faces take the outside's UVs reversed.
- **Pockets.** The flaps, jets and welt use the front's pattern coordinates, each as its own atlas rectangle.
- **Buttonhole cord.** UVs run along and round the cord, ×4, so the purl gets texels.
- **The rever** (`suit_rever.chart_uv`) is cut as a tailor cuts it:
  - The top collar is one piece with its grain up the CB.
  - Each lapel facing has its grain along the front edge.
  - The pieces are split at the gorge seam line in the chart.
- **Marks** (`suit_textures.draw_marks`, which gains seam kwargs and the kinds `pick` and `ridge`):
  - every visible sewn edge and both dart legs: a pressed-open seam (a groove, no stitches);
  - the gorge seam on both sides;
  - pick stitching: 6 mm in, 6 mm pitch;
  - the purl.
- **`suit_made_tex`** (new) sets the UV layer and panel tags. Its bake step packs through `suit_textures.pack_group` and builds the materials:
  - the weave and marks height into a 4096 normal;
  - albedo and ORM at 2048 (`surface_maps`, with smoother pressed lapels and collar);
  - the twill detail record and tile for the engine;
  - the lining: black viscose twill, roughness 0.34.

  Its assign step fills the material slots from the face's `part`. The bake runs before the LODs, so their copies carry the atlas UVs.
- **The beauty script** keeps the run's own materials and adds the Cycles weave and the hero twill (the same as the lofted `suit_wool`). It also gained:
  - `--grain`: the pinstripe check;
  - `--lods`: textured LOD frames;
  - the atlas PNGs.

### Numbers

| | value |
|---|---|
| atlas | 1.563 m square, 19 rectangles (10 panels, 3 rever pieces, 5 pocket patches, the cord), 144 marks; normal 4096 (**0.38 mm/px**), albedo and ORM 2048; bake 5.1 s |
| texel density (UV area / 3D area per face; 1 = the flat panel) | shell p05 0.91, median **1.00**, p95 1.10 (the drape's own strain); pockets 0.96 / 1.00 / 1.12; rever 0.79 / 0.98 / 2.41 (along q at the lapel roll 0.79, the roll is tighter in 3D than in the chart; the p95 is the inner sheet and the rim near the taper); cord ×16 by design |
| UV winding | all 10 panels and 3 rever pieces: outside faces 100 % counter-clockwise (no flips needed); the insides are the reversed copies (44 % of the shell's faces) |
| LOD UVs | LOD1 0.80 / 1.02 / 1.47, LOD2 0.67 / 1.01 / 1.53 (the collapse decimation stretches a little at UV seams) |
| atlas use | 47 % of the square is cloth: shelf packing of bounding rectangles, tapered panels |
| geometry | `kept.npz` and `made.npz` are bit-identical to d4: item 2 changes no vertex |
| tris | LOD0 61,594, LOD1 24,636, LOD2 9,181 (unchanged) |
| guards | drape and inside counts as item 1 (same drape); `npm run build` ok; containment 73/73; provenance audit 0 errors, 0 warnings |

### What is left in item 2's scope

- **Atlas packing.** 47 % use is low. Packing the panel shapes, with 180° turns allowed (a 180° turn keeps the grain and the twill's hand), would reach about 65–70 %: about 0.32 mm/px at 4096, or room to drop to 2048 for the engine. Item 8 decides the engine's texture budget.
- **The rever chart's roll** is 21 % short along q. A UV relax toward the 3D lengths would even out the twill there.
- **The sheen patch** on the lapel roll (above).
- **The trousers, waistcoat and shirt** get the same treatment in items 3–5. `shell_uv` and `solid` are panel-generic.
