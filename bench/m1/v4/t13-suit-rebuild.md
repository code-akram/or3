# T13 phase B: the pattern-drafted suit rebuild (running report)

The suit is being rebuilt as real tailoring: drafted panels, sewn and draped (numpy XPBD), then made up with a modelled rever, turned edges, lining, pockets, vents and buttons. Phase A (spike 2) is in `t13a-suit-spike2.md`. This file gets one section per §6 item, in order.

| item | what | state |
|---|---|---|
| 1 | jacket detail, plus the phase A review fixes | **done**, accepted (open points below, to be fixed before item 6) |
| 2 | UVs from panels (grain), port the `suit_textures.py` marks | **done** |
| 2b | item-1 review points 1–4 (back collar roll, vents visible, front quarters cutaway, pressed lapel edge) | **done** (point 5, the back skirt, done with item 3: the jacket over the made trousers) |
| 3 | trousers, plus review point 5 (the jacket re-draped over them) | **done** |
| 4 | waistcoat | **done** (the back neck fixed in item 5; open: the shoulder-seam end points) |
| 5 | shirt (collar band and fall to the `suit_neck.py` frame), the jacket re-draped over the made layers | **done** |
| 6 | rigging (weights, Dem Bones, correctives); re-measure the armpit/cuff hinges | **in progress** (posed sims, weights, fit and checks done; the drive needs a wider pose set; export) |
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

## Item 2b: the item-1 review points 1–4

Runs (base `20261014T205840Z-t15-a5`, all full drapes):

- `20261015T005546Z-t13c-k5` is the final run: clay, made jacket, LODs, textures and Cycles frames.
- `20261015T011946Z-t13c-k5det` is its determinism twin. X1, Xw and X2 hash the same: `fdaf39b6`, `ccc4b096`, `bdc05b8c`.
- `t13c-k1`…`k4` were the way there. `t13c-e2` is k4's drape with the lapel changes only.

Gate pictures are in `data/build/t13/gate/phaseB/item2b/`:

- `cmp_u6_k5_sheet.png`: item 2 against now, for the back collar, front, back and profile.
- `cmp_button_k4_k5.png` and `cmp_lapel_k4_k5.png`.
- `beauty_pattern_*.png`: the closes, including `close_front_hem`, `close_vent` and `close_collar_side`.
- `beauty_sheet.png`, `grain_sheet.png`, `ab_sheet.png`, `closeup_sheet.png`.
- The clay `pattern_*.png`.

### What I see (frames at 100 %, before the numbers)

- **Back collar.** The fall now covers the stand and rolls over at the top. The shirt collar shows a clean white band above it all round the back neck. The pick stitching runs along the fall's edge.
  - One fault: a soft horizontal drag line about 2 cm under the collar seam at the centre back. The back neck pulls slightly, which a tailor would fix with a touch more back-neck length.
- **Vents.** In `close_vent` and the back view, each back panel's lap reads as a pressed edge with a lip, running from the hem 22 cm up. The vents are closed and overlapped at rest, and the lap edge catches the light. At full body they are still subtle, as closed vents on a dark cloth are.
- **Front quarters.** Below the button the front edges run straight about 6 cm and then round away to the hem at about 50°. The opening between them shows the trousers, as a lounge jacket's does. The pick stitching follows the curve. This is in `close_front_hem` and the front and ¾ views.
- **Lapel edge.**
  - It now reads as a pressed edge: a fine highlight line along the edge with a crease where it meets the lapel face, instead of a broad rounded band (`cmp_lapel_k4_k5.png`).
  - The edge stands 3.8 mm off the front, from 4.5 mm.
  - The jacket's other turned edges (fronts, hem, cuffs, vents) get the same crease.
- **Below the button** (found in k4's frames, now fixed). The left front's edge showed a stepped jag where it rounds away below the button (`cmp_button_k4_k5.png`, left). Three of its edge vertices had gone 2.3 mm behind the right front.

### What was done

- **Point 1: back collar** (commit `bfb2d0d`). Rever stand 3.0 → 2.1 cm, fall below the seam 1.2 → 1.7 cm, and collar roll radius 0.3 → 0.45 cm.
- **Point 2: vents** (`bfb2d0d`). The lap's pressed edge is a lip in the atlas, a ridge mark 0.8 mm high and 2.4 mm wide, 1.5 mm in from the lap edge. The under panel keeps its groove there, which is the shadow line under the lap.
- **Point 3: cutaway** (`bfb2d0d`).
  - The draft's front edge below the button is a Bézier: straight for 6 cm (`cutaway.straight_cm`), then meeting the hem at 50° (`hem_angle_deg`). The hem corner is 6 cm inside the centre front (`front_hem_in_cm`).
  - Self-contact went 10 → 12 mm. With the fronts cut away, the right sleeve's inner elbow folded through itself (a 117–120° fore-seam hinge in k1 and k2), and 12 mm holds it.
- **Point 4: lapel edge** (`c4f6dcb`).
  - The fall lies lower: `h_lay_cm` 0.42 → 0.34, and the rever's final clearance 0.15 → 0.08 cm.
  - New `suit_made_tex.crisp_normals`: per-corner normals are smoothed only within each face kind (outside, inside, turned edge). Every half-round edge now meets its sheets in a crease.
  - New stat: `rever.lapel_edge_mm`, the lapel edge's height over the jacket front.
- **The layer fix** (`c4f6dcb`).
  - **Cause.** The lofted waistcoat's front edge has faces that look inward (its turned edge's inner rim). In the drape's distance field and in `push_out`, a point in front of them read as "inside the waistcoat".
  - **Effect.** The cut-away left front, which now crosses that edge, was pushed 2 cm forward in the drape. `push_out` then sent three of its vertices back through the right front.
  - **Fix.** A garment face now means "inside" only if a ray away from the body hits a garment (`garment_covers`, the rule the inside count already used).

### Numbers (k5)

| | value |
|---|---|
| shirt collar above the jacket collar at CB | **11.7 mm** (target 10–15; item 1: 3.8) |
| lapel edge over the front | median **3.84 mm**, p95 5.66 (target 3–4; was 4.49 / 6.19) |
| fronts below the button | the left front is 3.0–8.4 mm in front of the right (k4: −2.4 mm, through) |
| buttons over the drape | min **+1.07 mm**, 0 below (k4: −1.29, 17 below) |
| inside the body or under-garments | 0 by both rules; 1 vertex pushed (k4: 7); rever inside 0 (k4: 59) |
| seams | stage-1 gap p95 1.13 mm; strain mean 2.5 %, p99 14.9 % |
| hinges over 20° | 30: armhole 23 (16 at the underarm), side/front 3, hind 4. The A-pose underarm, as agreed; re-measured after item 6 |
| texel density | shell 0.91 / 1.00 / 1.10, pockets 0.96 / 1.00 / 1.12, rever 0.82 / 0.98 / 2.16; LOD1 0.80 / 1.02 / 1.44, LOD2 0.69 / 1.01 / 1.46 |
| tris | LOD0 **61,074**, LOD1 24,428, LOD2 9,102 |
| determinism | k5 and k5det: X1, Xw and X2 hashes equal |
| checks | `npm run build` ok; containment 73/73; provenance audit 0 errors, 0 warnings |

### Left from the review

- **Point 5** (the back skirt onto the seat) goes with item 3: the jacket is re-draped over the made trousers.
  - In k5 the jacket's back is 15–37 mm off the body over the small of the back (z 1.06–1.12) and 6 mm at the seat's fullest point.
  - The hull's lumbar bridge (`alpha_back` 0.55) and the centre-back suppression are the levers.
- **The back-neck drag line** under the collar (above).


## Item 3: the trousers

Runs (base `20261014T205840Z-t15-a5`, all full drapes):

- `20261015T013450Z-t13t-d5` is the final run: draft, drape, the made trousers, LODs, textures, and the Cycles beauty, grain and LOD frames.
- `20261015T013733Z-t13t-d5det` is its determinism twin. X1, Xw and X2 hash the same: `cc740430`, `f0a3d0ae`, `1efb597c`.
- `t13t-d1`…`d4` were the way there. In d4 the left back hem buckled into a fold (see below).
- `20261015T014000Z-t13c-p5b` (and `-p5c`, the same with the trousers' materials kept) is the jacket re-draped over d5's made trousers, for review point 5.

Gate pictures are in `data/build/t13/gate/phaseB/item3/`:

- `beauty_sheet.png`: lofted | pattern, front, ¾, profile and back.
- `closeup_sheet.png`: hem, hem from the side, knee, seat, fly, band. The single frames are `beauty_pattern_close_*.png`.
- `grain_sheet.png` and `beauty_grain_close_{seat,knee}.png`: the pinstripe check.
- `beauty_lod{1,2}_*.png`; clay `pattern_*.png`; `pattern.png` (the draft); `atlas_normal_1k.png`.
- `cmp_hem_d4_d5.png`: the back hem before and after the placement fix.
- `p5_*.png`: the jacket over the made trousers (point 5).

### What I see (frames at 100 %, before the numbers)

- **Overall.** Against the lofted trousers, which are skin-tight and stop above the shoe, these hang as cloth. The legs fall straight from the seat and the knee with a gentle taper. They rest on the shoe with a slight break at the front, and the hem slopes down toward the heel. The rise is high, as a three-piece suit's is, with the band at the natural waist under the waistcoat.
- **Front.** A pressed crease runs from the band to the hem on each leg. The fly reads as a lip on the left front (wearer's left over right) with the J-stitch pick-stitched beside it, curving in at the bottom. The slant side pockets show as a lip with pick stitching in from it.
- **Back.** The two back darts run from the band toward the jetted pockets. Each pocket is two jets with a button under it. The centre-back seam runs into the band's own CB seam. The seat is smooth with no drag lines, and the back crease starts below the seat.
- **Grain.** The warp runs straight down each leg, front and back. On the seat the stripes meet the CB seam in a chevron, as they do on real trousers, because the back's seat seam is cut on the bias.
- **Hem.**
  - In d4 the left leg's back hem had a crumpled fold near the outseam (`cmp_hem_d4_d5.png`, left): a 178° fold, already there after stage 1, on one leg only.
  - In d5 both hems are clean. They sit on the heel counter at the back and break softly over the vamp at the front.
- **LODs.** LOD1 reads the same as LOD0 at full body. LOD2 shows a few dark and light specks on the lower legs at 100 %, where the inside layer of the decimated 1.2 mm shell comes through. They are sub-pixel at the distance LOD2 is used.
- **The clay profile frame.** The dark patch on the thigh is the hand's shadow in EEVEE. It is not in the geometry and not in the Cycles frames.

### What was built

- **`blender/character/suit_trouser_pattern.py`** (new): the trouser draft. It is a standard block, front and back built off the crease line, from the body's measurements (`measure_legs`): waist, seat, crotch depth, knee, calf and ankle.
  - Front: waist, fly, crotch, inseam, hem and side; the crease line; notches for the J-stitch, the slant pocket and the fly's end.
  - Back: seat angle 10°, back rise 3.5 cm, a 1.5 × 10 cm dart, the fork S/8 dropped 0.8 cm; the crease 1 cm in from the front's and starting 8 cm below the fork; the back-pocket notch.
  - Band: 4 cm, split at CB and CF.
  - Knee 42 cm and hem 38 cm round. The hem is 8.5 cm above the floor at the front, 7.0 at the side and 5.5 at the back.
  - Seams: outseam, inseam, front rise, seat, band, band CB and CF, and the back dart.
- **The drape** (`suit_spike.py --trousers`):
  - Same two-stage XPBD as the jacket: sew without gravity, weld, then drape with gravity, the band top held.
  - Placement: above the fork, rows wrap a half-section ring of the trunk; the crotch extensions follow the body's midline profile; below the fork, rows wrap the leg rings.
  - The shoes collide as convex hulls (`shoe_hulls`), so the hem can't fall into the throat; the shirt collides too.
  - Placement fix (d5): the lower leg is compressed over 40 cm (`hem_place.span_m`) so the hem starts 3 cm above the shoe. In d4 the last few centimetres were squashed 4:1, and the back hem buckled into the d4 fold as stage 1 released it.
- **`blender/character/suit_trouser_detail.py`** (new): the made trousers.
  - Shell: 1.2 mm cloth, 3 mm band, half-round turned edges.
  - Creases: geometry raised 1.2 mm with a 7 mm falloff, plus a pressed ridge in the atlas.
  - Back pockets: two jets, 5 mm each, and a 17 mm button under each.
  - Atlas marks: pressed-open seams, the fly lip and J-stitch, the slant pocket's lip and pick stitching, the crease ridge.
  - Its own wool atlas (`t13t_*` materials, `suit_made_tex` with a `name` option).
- **The jacket over the made trousers** (`--trousers-from RUN`): the made trousers replace the lofted ones as collider, hull and render layer. `suit_beauty.py --garment trousers` makes the trousers' Cycles frames; in jacket mode it uses a run's made trousers when present.

### Numbers (d5)

| | value |
|---|---|
| measurements | waist 81.3 cm, seat 94.1, crotch at z 0.910 m; draft S 100.1, W 83.3; outseam 105.8 / 105.5 cm (front / back), inseam 82.6 / 82.5 |
| seams after stage 1 | gap mean 0.18 mm, p95 0.67, max 1.72 |
| strain against the flat pattern | mean 1.85 %, p99 12.4 % |
| inside the body, shirt or shoes | 0 before push-out, 0 after (d4: 1) |
| hinges over 20° | 32, all at the fork or the break. Front rise 6 (124° max) and seat 10 (98°) at z 0.86, where four panels meet at the fork. Outseam 10 (44°) at z 0.19–0.20 and inseam 6 (33°) at z 0.13–0.24, where the leg folds onto the shoe |
| sharpest folds below the fork | 79° at the front break (z 0.12); the d4 back-hem fold (178°) is gone |
| hem | z 0.036–0.098 m |
| texel density | shell 0.91 / 1.00 / 1.04 (p05 / median / p95); pockets 0.94 / 1.07 / 1.53; LOD1 0.82 / 1.00 / 1.18; LOD2 0.69 / 0.99 / 1.25 |
| atlas | 4096 px over 1.45 m (0.355 mm/px), 10 rects, 41 marks |
| tris | LOD0 **29,812** (shell 24,856, pockets 3,296, buttons 1,660); LOD1 11,924; LOD2 4,470 |
| determinism | d5 and d5det: X1, Xw and X2 hashes equal |
| checks | `npm run build` ok; containment 73/73; provenance audit 0 errors, 0 warnings |

### Review point 5: the back skirt onto the seat (the jacket over the made trousers)

Run `20261015T015643Z-t13c-p5c`: the jacket's k5 draft and options, re-draped with d5's made trousers as the collider. Its drape hashes equal its twin `t13c-p5b`'s (X1 `da99755e`, Xw `58a2cdb9`, X2 `fbbd6b49`). The frames are the `p5_*.png` in the gate.

- **What I see.** In the profile and back frames the jacket hangs from the shoulder blades, comes in a little over the small of the back, and lies on the seat at its fullest point. Below that the skirt hangs plumb past the seat's undercurve, as a jacket's skirt does. The vent laps lie closed on the seat (`p5_beauty_close_vent.png`). The front quarters open onto the made trousers. Jacket and trousers read as one cloth.
- **Measured** (back surface, jacket minus the trousers under it, 15 mm either side of x = 0.075 m):

  | z (m) | 0.89 (hem) | 0.95 | 0.98 | 1.01 (seat) | 1.04 | 1.07 | 1.10 | 1.13 | 1.16 |
  |---|---|---|---|---|---|---|---|---|---|
  | gap (mm) | 22.8 | 8.6 | 5.4 | **3.9** | 9.7 | 15.3 | 21.8 | 24.3 | 30.2 |

  - At the centre back it is 8–10 mm over the seat (z 0.98–1.04).
  - Over the lumbar hollow the jacket stands 20–37 mm off the body at z 1.10–1.19. That includes the shirt and the waistcoat, and it is the cloth bridging from the blades to the seat.
- **Tried and not taken** (`t13c-p5a`): the hull's lumbar bridge `alpha_back` 0.55 → 0.30 and the CB suppression 0.22 → 0.30. It moved the lumbar gap by 5 mm at most, and lifted the skirt 3–4 mm further off the seat. The k5 draft stays.
- Guards on p5c (over the made trousers):
  - inside 0 by both rules, 3 vertices pushed;
  - hinges 29: armhole 22 (16 at the underarm), side/front 3, hind 4;
  - buttons clearance +1.07 mm;
  - LOD0 61,074 tris.
- **A fix on the way.** The made trousers came into the jacket run without their materials: the clay renders took their slots, and the `t13t_*` materials were then dropped at save. `load_made` now keeps them (fake user), and the spike and `suit_beauty.py` give them back their slots.

### What is left in item 3's scope

- **Side adjusters and the band's closure** (the extension and hook) are not built. In a three-piece suit the waistcoat covers the band, so they are left until the waistcoat (item 4) shows whether anything of the band is visible.
- **LOD2 specks** (above) go to item 8: a single-sided outer sheet for LOD2, or decimation that keeps the shell's two layers apart.
- **The final layering** (shirt, then trousers, then waistcoat, then jacket) is settled in items 4–5. The jacket is re-draped once more over the made waistcoat.

## Item 4: the waistcoat

Runs (base `20261014T205840Z-t15-a5`, over d5's made trousers via `--trousers-from`):

- `20261015T023852Z-t13w-a8` is the final drape: clay frames, LODs.
- `20261015T024450Z-t13w-a8det` is its determinism twin. X1, Xw and X2 hash the same: `495a1524`, `a52ad6fb`, `1361f041`.
- `20261015T025525Z-t13w-a8b` is a8's drape made up again with the matte lining (`--from-run`). Its `beauty_*.png` are the Cycles frames.
- `t13w-a1`…`a7` and `a9` were the way there (below).

Gate pictures are in `data/build/t13/gate/phaseB/item4/`:

- `beauty_sheet.png`: lofted | pattern.
- `beauty_pattern_close_{v,point,wwelt,breast,wback,wside}.png`.
- `grain_sheet.png` and `beauty_grain_close_{v,point}.png`.
- `beauty_lod{1,2}_*.png`; the clay `pattern_*.png`; `pattern.png`.
- `clay_back_neck.png` and `clay_profile_neck.png`: the open point below.

### What I see (frames at 100 %, before the numbers)

- **Front.** A single-breasted waistcoat with a V to 17 cm above the jacket's button. Four buttons are done up and the fifth left undone: its buttonhole shows as a corded slit on the left front, with no button showing. Below the last button the fronts cut away to two points with an inverted V between them, and the hem rises from the points to the side seams.
  - Lower welts on both sides and a breast welt on the left.
  - Pick stitching 6 mm in from the front edge, the V and the hem.
  - A front dart from under the breast welt through the lower welt to just above the hem.
  - The V's edge sits inside the lapels' line, over the shirt and tie.
- **Back.** The back is lining (Cycles: a dark satin), cut from the block's back with a CB seam. It covers the trousers' band all round: the side and back hem are about 2.5 cm below the band top. The back neck is scooped and sits under the shirt collar, which shows above it all round.
- **Grain.** The warp runs straight down each front, parallel to the button edge.
- **Faults I can see:**
  - **The back neck in profile** (`clay_profile_neck.png`). The back neck stands about 2 cm off the shirt collar behind the nape: the upper back bridges from the blades to the collar instead of lying in. The jacket's collar covers it once the jacket is on, but the jacket must go over it (item 8's layering). Tried: a closer neck point (`np_out` 1.0, run a9), which made no visible difference.
  - **Small points at the shoulder seam's two ends**, a few millimetres each (`close_wback`, top corners): the 33° hinge in the numbers.
  - **The lower welt bends slightly** where the dart runs under it. It is laid out with the dart closed, but the drape has a soft crease along the sewn dart.
  - **The back lining follows the body closely** and shows the blades and spine. A real waistcoat back hangs a little freer; a back strap would also show. The strap is not built.

### What was built

- **`blender/character/suit_waistcoat_pattern.py`** (new): the waistcoat drafted from the jacket's block (`suit_pattern.draft`) with waistcoat options.
  - Block options: chest ease 6 cm, waist 5 cm; the armhole 5 cm under the armpit; the shoulder ending 2.5 cm inside the acromion with no pad; the neck point 1.8 cm out.
  - Suppression: CB 0.28, back/side 0.50, front dart 0.22, none at the side front.
  - The block's side body and front become one front panel, so the waistcoat has the classic two pieces: a front with a fisheye dart, and a lining back.
  - Points, V and buttons are placed from the trousers' band top (`band_top_z`) and the jacket's button.
  - Notches: buttons, buttonholes, welts.
  - Because the front and back come from the jacket's block, the jacket's `Placer` and `build_cloth` place and sew them unchanged.
- **The drape** (`suit_spike.py --waistcoat`, `main_waistcoat`):
  - `drape_xpbd` now takes a list of button pairs (`C["buttons"]`); the jacket keeps its one.
  - Colliders: shirt, tie, and the made trousers.
  - **Holds.** Stage 1 holds the shoulder seams and the hem where they were placed; stage 2 holds the shoulders only, lightly. Without holds, stage 1 slid the whole waistcoat 5 cm up (a2). Holding the back neck rippled it (a6, 83° at the CB) or pinched it (a5, 69°).
  - **The draft's fixes.**
    - The hem is cut 2.5 cm lower than the block's straight drop (`hang_comp_cm`): the sewn waistcoat hangs that much higher, measured in a3–a5.
    - The back neck is scooped 3 cm at the CB: level with the neck point, it rode 4.6 cm up the shirt collar (a7).
- **`blender/character/suit_waistcoat_detail.py`** (new): the made waistcoat.
  - Shell: the fronts 2.0 mm thick (wool, canvas, lining), the back 0.8 mm of lining, with half-round turned edges everywhere.
  - Welts: laid out with the dart closed (`_dart_warp`); patched straight over the dart, a1's welt broke in two at it.
  - Buttons: four 15 mm buttons on the left front.
  - Marks: seams and dart, pick stitching, the buttonholes' corded lips.
  - Its own atlas (`t13w_*`), with a twill lining (rough 0.55) in place of the jacket's satin, which read as black chrome across the back.
- `suit_beauty.py --garment waistcoat` gives the waistcoat's Cycles frames over the made trousers.

### Numbers (a8 / a8b)

| | value |
|---|---|
| draft | half chest 55.2 cm, half waist 41.4; side hem drafted at z 1.104, points 1.044, top button 1.329 m; CB 47.6 cm; side seam 28.6 / 28.6; shoulder 12.8 / 12.2 (back eased) |
| where it hangs | hem z 1.065 (points) to 1.134 (back); the band top is at 1.159. Top button 1.33 |
| seams after stage 1 | gap mean 0.51 mm, p95 1.73, max 4.15. The hem hold slows the sewing; it reaches the 40 extra frames allowed |
| strain against the flat pattern | mean 1.6 %, p99 11.4 % |
| inside the body, shirt, tie or trousers | 0; 0 vertices pushed |
| left front over the right at the buttons | 3.8–4.9 mm |
| buttons and welts over the drape | buttons min +1.32 mm, welts +0.38, 0 below |
| hinges over 20° | 12: shoulder 6 (34° max, at the neck end), CB 4 (30°, the back neck), side 2 (23°, the underarm) |
| texel density | shell 0.94 / 0.99 / 1.04 (p05 / median / p95); welts 0.94 / 0.98 / 1.14; LOD1 0.84 / 1.00 / 1.24; LOD2 0.78 / 0.99 / 1.29; atlas 0.28 mm/px |
| tris | LOD0 **22,456** (shell 16,128, welts 3,024, buttons 3,304); LOD1 8,982; LOD2 3,368 |
| determinism | a8 and a8det: X1, Xw and X2 hashes equal |
| checks | `npm run build` ok; containment 73/73; provenance audit 0 errors, 0 warnings |

### What is left in item 4's scope

- The back neck's stand-off in profile, and the shoulder seam's end points.
- The back strap and buckle (they show only with the jacket off).
- The welt's slight bend at the dart.
- The jacket re-draped over the made waistcoat (and the made trousers): it goes with item 5, once the shirt is made, so the jacket drapes over the final layers once.

## Item 5: the shirt, and the jacket over the made layers

Runs (under `data/build/suit_spike/`, lookdev base `20261014T205840Z-t15-a5`):

| run | what |
|---|---|
| `20261015T042335Z-t13s-s6` (twin `…043909Z-t13s-s6det`) | the shirt over d5's made trousers; its cuff placed from the p5c jacket's sleeve end |
| `20261015T051002Z-t13w-b7` (twin `…052711Z-t13w-b7det`) | the waistcoat re-draped over the made shirt (pressed) and trousers; the rendered shirt pressed under it |
| `20261015T051851Z-t13c-q7` (twin `…052416Z-t13c-q7det`) | the jacket re-draped once over the final layers: shirt, waistcoat and trousers as b7 left them |

Gate sheets are in `data/build/t13/gate/phaseB/item5/`: `shirt_sheet.png`, `shirt_close_sheet.png`, `shirt_lod_sheet.png`, `waistcoat_sheet.png`, `stack_sheet.png` and `lofted_vs_made.png`.

### What I see (frames at 100 %, before the numbers)

**The shirt alone** (s6, over the made trousers):

- It reads as a white dress shirt tucked into the trousers.
- **Collar.** A spread collar: the band stands round the neck and the fall turns over it, with the points spread under the knot. The front closure sits under the tie.
- **Back.** A yoke seam across the back, and the two back darts shaping the waist. The tuck is smooth at the band.
- **Sleeves.** A clean sleeve head. The sleeve blouses a little over a barrel cuff, and the cuff has a lapped closure with a button and a topstitch row.
- **Front.** A placket with buttons and an edge stitch. At the elbow the sleeve is pressed close to the arm (see below), so it reads slimmer than a shirt worn alone would.
- Faults:
  - At the back sides, the fall's lower edge steps slightly where it ends: a small tab at each side.
  - The lofted tie stops at z ≈ 1.25. It was built only down to where the jacket covers it, so in shirt-only frames it ends mid-chest.

**The waistcoat over the made shirt** (b7):

- The back neck now lies on the shirt. In profile the upper back no longer bridges from the blades to the collar.
- The back is clean, the armholes are clean, and the shirt shows only through the armholes and above the V.
- One small white sliver shows at the front edge between the third and fourth buttons. That is the shirt placket in the lap (button lap 2.6 mm there).

**The full stack** (q7, Cycles):

- It reads as a three-piece suit.
- A white band of shirt collar shows above the jacket collar all round the back neck, and the shirt cuff shows past the sleeve at the front of the wrist.
- The crook of the arm folds softly, with no shirt coming through.
- The back is smooth under the collar. The drag line of p5c is gone.
- The cuff shows less at the back of the wrist. The jacket's hem hangs slanted along the forearm: 23.7 cm from the elbow at the front, 28.4 at the back.
- The lofted jacket in `lofted_vs_made.png` is a different case: it was fitted to the lofted shirt, so the made shirt comes through it. That frame only compares the two jackets; it is not a guard.

### What was built

**`blender/character/suit_shirt_pattern.py`** (new): the shirt drafted from the jacket block.
- Panels: yoke, back with two fisheye darts, front with a buttoned placket, and a one-piece sleeve.
  - The sleeve has a 1 cm head ease, 7 cm bicep ease, two 1.5 cm pleats and a 2 cm blouse.
  - The sleeve is bent 30° in the cut: part of the A-pose elbow taken out of the crook.
- A barrel cuff placed so it shows 1.3 cm past the reference jacket's sleeve end.
- The neckline is sized to the band base of the collar frame (25.3 cm per half).

**`blender/character/suit_shirt_detail.py`** (new): the made shirt.
- The shell has a 0.45 mm solid, with felled seams as a groove and a topstitch.
- The placket is lifted, with edge stitching and buttonholes.
- The collar is the band and fall from `suit_neck.build_shirt_collar` on the same frame the lofted path uses, thickened, with topstitching.
- Each cuff is fitted to the wrist section: it is offset to its round and hangs on the wrist with a 1.5 mm gap at the top.
- Front and cuff buttons. A cotton atlas through `suit_made_tex` (`cloth: "shirt"`).

**`bench/m1/v4/suit_spike.py`**:
- `--shirt` (`main_shirt`), with these hooks:
  - holds the collar band's ring;
  - holds the cuff on its frame;
  - a tuck hook below the trousers' band;
  - a tie hook that keeps the front behind the tie;
  - an elbow press (`zone_hook`, 5 mm off the arm within 6 cm of the elbow, fading out by 14 cm).
- `--shirt-from` and `--waistcoat-from`, beside `--trousers-from` (`use_layers`):
  - The made garment replaces the lofted one.
  - The drape collides with a hidden join of its made parts, outer faces only. The made parts are solids, and the field reads a garment shell by its nearest face. The inner face looks at the body, so a point under the shirt but nearer its inner face read as outside. In b1 the waistcoat settled inside the shirt in four places.
- The waistcoat's back-neck cling: within 3 mm of the layer under it, from the back neck down 4 cm, fading out by 12 cm.
- `press_under`:
  - A made under-garment that comes through the garment draped over it is pressed in behind that garment's surface, together with its neighbours within 15 mm.
  - The clearance is 3 mm under the waistcoat and 4.5 mm under the jacket.
  - The pressed objects are saved in the run's `spike.blend`, and the next layer loads them from there.
- The waistcoat drapes over a pressed collider of the shirt, capped 6 mm off the body with a quarter of the excess kept.
- The made under-garments get their own clay tint in the clay frames.

**`bench/m1/v4/suit_beauty.py`**: `--garment shirt`, the shirt close-ups, and the stack close-ups (`close_stack_neck`, `close_stack_neck_s`, `close_stack_cuff`).

**`suit_waistcoat_pattern.py`**: the armhole is 7 cm under the armpit (it was 5). At 5 cm the made shirt's underarm caught the armhole's lower edge.

The jacket keeps k5's draft and options (`bench/m1/v4/suit_opts/jacket_q7.json`, passed with `--opts @…`), except two:
- the sleeve ends 3.5 cm above the wrist (it was 2.0), because over the made layers it hung 1.7 cm lower;
- the rever's stand stays at the default 2.1 cm.

### Fixes made on the way (each found in a frame)

| run | what I saw | cause | fix |
|---|---|---|---|
| s2–s4 | a 30 cm waist blouse, hard walls beside the tie, a flap at the crook | ease, the tie limit, a straight-cut sleeve | waist ease 16 with darts; a soft tie field; the sleeve bent in the cut |
| b1 | a keyhole of shirt through the waistcoat at the CB, and blobs at the sides | the inner faces of the made solids in the collider | outer faces only |
| b2–b6 | the waistcoat's armholes torn open to the waist, strain p99 39–50 % | a 6 cm-ease waistcoat round a rigid shirt's bulk | a pressed shirt collider, then the shirt pressed under the waistcoat (b7: p99 15 %) |
| q1 | the shirt sleeve through the jacket's under sleeve, jacket strain p99 39 % | the shirt sleeve stood as far off the arm as the jacket's (p90 38 mm at the elbow, against 32) | a fitted sleeve: bicep ease 10 → 7, elbow extra 2 → 0, blouse 3 → 2 |
| q2, q3 | the shirt's crook fold through the jacket's crook | the two crook folds in the same place | the elbow press on the shirt (p90 at the elbow 29 → 17 mm), plus `press_under` |
| q4 | the shirt cuff hidden (−0.5 cm) | the jacket sleeve hung 1.7 cm lower over the made layers | jacket sleeve end 2.0 → 3.5 cm above the wrist |
| q2–q6 | the shirt showing 7.8 / 10.6 / 19.6 mm at the CB | the jacket collar's height follows the layers under it | the stand back to 2.1 cm over the final layers: 14.9 mm |

### Numbers

| | shirt s6 | waistcoat b7 | jacket q7 |
|---|---|---|---|
| stage-1 seam gap (mean / p95 / max mm) | 0.27 / 1.06 / 2.01 | 0.68 / 2.59 / 4.89 | 0.49 / 1.50 / 5.25 |
| inside after push (nearest face / both rules) | 0 / – | 0 / 0 | 0 / 0 (rever 0) |
| strain vs flat (mean / p99) | 3.4 % / 21.6 % | 2.4 % / 15.0 % | 3.0 % / 17.5 % (p5c: 2.6 / 14.9) |
| seam hinges over 20° | 66 (armhole underarm and the CB yoke fold) | 4 | 21 (p5c: 29) |
| tris LOD0 / LOD1 / LOD2 | 53,922 / 21,568 / 8,088 | 22,380 / 8,952 / 3,356 | 60,802 / 24,319 / 9,061 |
| determinism (X1, Xw, X2) | `3b907334 a88f7f80 b10d6dd0` (= twin) | `354c1384 f0f44c14 87187f7d` (= twin) | `bae1b10e 04ab9fa8 efb93760` (= twin, and = q6) |

- **Collar seating against T22's neck** (`neck_check`, the hero mesh from the lookdev blend against the frame's body):
  - under the band: hero minus frame at most 0.9 mm (p99 0.79);
  - above the band: 1.62 mm;
  - the collar's inner face to the hero: min 3.4 mm, median 10.1, none inside.
- **Shirt collar above the jacket collar at the CB:** 14.9 mm (target 10–15).
- **Shirt cuff past the jacket sleeve** (left arm, median over 12 sectors round the forearm): 1.15 cm (target 1–1.5). It is 1.5 cm at the front of the wrist, and the jacket covers it at the back.
- **Tuck:** the shirt is at most 0.59 mm behind the trousers' band surface. 64 of 1,698 vertices are inside the trousers (the tuck), and none stand outside mid-band.
- **Front through the tie:** 0.
- **Pressing:**
  - under the waistcoat: 2,383 shirt shell vertices, at most 21.2 mm (the bulk under the arms); the collar 117 vertices at 2.9 mm;
  - under the jacket: 1,912 shirt vertices at most 13.1 mm, the cuffs 640 at 1.6 mm, the waistcoat 857 at 2.2 mm.
- **Shirt atlas:** 4,096 px, 0.34 mm/px, 72 marks. The shell's UV area ratio is median 1.00, p05–p95 0.91–1.14.
- **Checks:** `npm run build` ok; containment 73/73; provenance audit 0 errors, 0 warnings.

### What is left in item 5's scope

- **Triangle budget.** The made shirt is 54k triangles at LOD0, and it is mostly hidden. In item 8 the stack has to come down to the character budget (LOD0 ≤ 170k for the whole character): the shirt's LOD1 (21.6k) should be its LOD0 under the jacket.
- **Strain.** The shirt's p99 strain (21.6 %) is at the underarm, where the armhole hinges are.
- **Layering order.** The pressing is a stand-in for real two-way contact. Each layer is draped over the ones under it, which are taken as rigid, and the under layers are then pressed in. Posed states (item 6) need the same order.
- **Fall ends.** The collar fall's end tabs at the back sides.
- **Tie.** The tie is the lofted one (cut at z ≈ 1.25).
- **Cuff at the back.** The jacket's slanted sleeve hem covers the cuff at the back of the wrist.

## Item 6: rigging (in progress)

Run `20261015T061555Z-t13r-a2` (twin `…062046Z-t13r-a2det`: the posed drapes, the weights and the bone transforms are bit-identical). It is the jacket q7 rigged and simulated over the pose set, with the made shirt, waistcoat and trousers skinned under it.

Gate sheet: `data/build/t13/gate/phaseB/item6/posed_sheet.png`. Each row is one pose (arm raise, knee up, walk, fist), shown three ways: plain skinning (LBS with the weights taken from the body), simulated, and LBS plus the Dem Bones jacket bones. The frames are clay; the cool grey is the under-layers.

### What I see

- **Knee up.**
  - Plain skinning: the raised thigh cuts through the jacket's front skirt.
  - Simulated: the skirt rides up over the thigh and drapes from it.
  - The fit with the jacket bones lifts the skirt most of the way.
- **Walk and fist (arms down).** The simulated jacket hangs cleanly: the front stays closed at the button, the collar sits, and the sleeves fall to the cuffs.
- **Arm raise.**
  - The simulated jacket opens and rides up with the arm, as a real one does.
  - Plain skinning collapses the shoulder.
  - The fit leaves the shirt and waistcoat showing through in patches. The error left there is large (below), so the sleeves and shoulders need their correctives.
- **Rever.** Its roll edge is a little ragged in the posed frames. The rever follows its nearest body vertex, both through the skinning and through what the simulation adds on top of it. It needs its own weights, smoothed along the roll.

### What was built

- **`blender/character/suit_rig.py`** (new, numpy only):
  - `transfer`: the body's weights at the nearest body point, barycentric, smoothed over the garment's mesh, top 4 kept.
  - `skin`: linear blend skinning.
  - `fit_bones`: Dem Bones (SSDR) with the body's bones fixed. It alternates weighted Kabsch transforms per bone and pose with per-vertex non-negative, sum-to-one weights over the vertex's body bones and its three nearest jacket bones.
  - `drive`: ridge regression of each jacket bone's transform, relative to its parent and taken about its centre, on its drivers' local rotations.
  - `correctives`: what is left, un-skinned to rest space, as `deform_correctives` stores it.
- **`suit_spike.py --posed <jacket run>`** (`main_posed`):
  - It loads the run's made layers (from its `*_from` records) and transfers the weights.
  - Per pose:
    1. `deform_poses.apply_pose`, with the lookdev rig's helper rules when the rig file is present.
    2. The posed body and the skinned under-layer colliders form a distance field.
    3. XPBD runs 40 frames from the skinned rest drape. Its rest lengths come from the flat pattern; the button pair and the neckline are held at their skinned positions.
    4. `push_out`, then the checks.
  - Then the Dem Bones fit, the drive, the correctives, `rig.npz`, and the frames.
- **The eight jacket bones**, by design: skirt front and back, chest front, and the side body under the arm, each side.
  - Placed from the data instead (k-means on the vertices worst served by plain skinning, run `t13r-a1`), six of the eight went to the sleeves, and none could be driven from the skeleton.
  - The sleeves stay on the arm's bones and their correctives.

### Numbers (a2)

| pose | jacket inside (after push) | seam hinges > 20° (p99) | strain p99 | LBS vs sim RMS / p99 mm | LBS + jacket bones RMS / p99 mm | shirt collar above jacket collar at CB (mm, neck frame) | shirt cuffs / collar inside the body |
|---|---|---|---|---|---|---|---|
| rest | 0 | 53 (51°) | 17.0 % | – | – | 14.9 | 0 / 0 |
| relaxed | 6 | 90 (118°) | 25.2 % | 9.3 / 19.9 | 7.4 / 19.8 | 17.0 | 0 / 0 |
| arm raise | 0 | 65 (162°) | 27.7 % | 71.6 / 128.7 | 52.7 / 127.5 | 11.3 | 0 / 0 |
| knee up | 8 | 102 (156°) | 29.5 % | 17.6 / 53.7 | 10.1 / 32.0 | 14.7 | 0 / 0 |
| walk | 1 | 86 (163°) | 27.0 % | 19.8 / 57.5 | 11.5 / 27.3 | 14.7 | 0 / 0 |
| high ready | 7 | 114 (129°) | 36.0 % | 20.6 / 46.1 | 15.9 / 38.6 | 16.5 | 10 / 0 |
| twist | 5 | 90 (70°) | 26.5 % | 24.0 / 52.4 | 20.1 / 51.6 | 14.6 | 6 / 0 |
| fist | 4 | 99 (154°) | 28.0 % | 11.9 / 25.7 | 9.5 / 22.1 | 14.7 | 0 / 0 |

- **Collar and cuffs in the arms-up and fist poses.**
  - The shirt collar stays 11–17 mm above the jacket collar at the CB in every pose. The rever never enters the neck, and the collar never enters the body.
  - In the fist the cuffs are clear of the hand.
  - In the high-ready and twist poses, 10 and 6 sampled vertices of the (skinned, not simulated) shirt cuffs are inside the wrist.
- **Seam hinges in posed states.**
  - Over 20°, they rise from 53 at rest to 65–114.
  - The p99 of 154–163° in the arm raise, knee up, walk and fist poses means some seams fold right over. I have not yet looked at where.
- **Drive** (about each bone's centre, leave-one-out over the 8 poses):
  - It fits the training poses (front_r 2°/5 mm, side 5°/13 mm), but the leave-one-out error is close to each bone's whole range (front_l 10° of 8°; side_l 15° of 15°).
  - skirt_front_l reads 117° in the knee-up pose. That is a fold the rigid fit cannot follow.
  - With 8 poses, a linear map from the skeleton does not generalise. The pose set has to grow before the jacket bones can be driven.
- **Correctives left after the fit** (max / p95 mm): relaxed 30 / 14, arm raise 155 / 126, knee up 68 / 21, walk 33 / 22, high ready 50 / 34, twist 59 / 48, fist 30 / 18.
- **Cost:** 27–35 s of simulation per pose. The weights take 1.3 s and the fit 8 s.

### What is left in item 6 (where the next agent picks up)

1. **A wider pose set.**
   - About 30 poses: thigh flexion and abduction ramps, arm abduction and flexion ramps at 30/60/90/120°, spine twist and bend ramps, plus the library poses.
   - `--poses` takes the list; add ramp specs beside `POSED`.
   - Refit, check the drive's leave-one-out error, and keep only drivable bones (a bone whose leave-one-out error stays near its range should become a corrective instead).
2. **The arm raise.**
   - Plain skinning is off by 72 mm RMS there. Check that the helper rules applied (deltoid helper, twist): `character.rig.json` beside the base blend. Then run the shoulder as correctives.
   - Look at what sits behind the 154–163° hinge p99, by rendering the hinge positions.
3. **The rever.** Give it its own weights (smoothed along the roll) instead of following the nearest body vertex.
4. **Export.**
   - The jacket bones go into the armature as children of pelvis or spine_03 at their centres, with `deform_runtime` rules from the drive coefficients.
   - The correctives go out as shape keys with cone drivers. `deform_correctives` already does this for the lofted suit, and finds garments by name.
   - This joins item 8's integration.
5. **The shirt and waistcoat.** Simulate them per pose too (they are skinned only here), in the same order as at rest: shirt, then waistcoat, then jacket, each pressed under the next.

## Item 6, continued (T13c): 35 poses, every layer simulated, correctives, layer tuck

Runs:
- sims `20261015T064307Z-t13r-c1`: 35 poses; shirt, then waistcoat, then jacket, each over the posed body and the layers under it;
- refit `20261015T073655Z-t13r-c1f`: `--posed-cache c1` with λ 0.03, no cone masks, the layer tuck, the wrinkle bake and the export;
- determinism twin `20261015T073153Z-t13r-c1det`: the same sims from scratch, compared in pickup item 4.

Gate sheets, in `data/build/t13/gate/phaseB/item6c/`:
- `posed_sheet_{0..5}.png`: rows are the poses, in the order listed in `posed_sheet.txt`; columns are sim front, sim ¾, runtime front, runtime ¾.
- `lbs_sheet_0.png`: relaxed, arm raise, knee up, walk and fist, each shown as sim | runtime | plain LBS.

### What I see (frames at 100 %, before the numbers)

- **Shoulders.**
  - Plain LBS still puts a square ridge on both shoulders in relaxed, knee up, walk and fist.
  - The runtime (LBS + skirt bones + correctives) removes it. Its shoulder line stays within a few mm of the sim.
- **The runtime matches the sim** in every library pose. What is wrong in the runtime is already wrong in the sim:
  - Walk: a hole in the left jacket sleeve at the back of the upper arm shows the shirt sleeve.
  - Relaxed, knee up, fist and high ready: below the button, the two fronts meet in a ragged vertical tear where the overlap interpenetrates.
  - Arm raise, high ready and fist: the shirt cuffs crumple into spikes round the fist.
- **Arm raise.**
  - The jacket rides up with the arm and the shoulder stays smooth.
  - No shirt shows through the jacket body any more. T13b's fit error here was 52.7 mm; it is now 8.1 mm.

### What was built

- **`suit_spike.py` `POSED`:**
  - 35 poses:
    - the library 8;
    - arm abduction and flexion at 30/60/90/120°;
    - elbow at 45/90/120°;
    - thigh flexion, abduction and extension ramps;
    - spine turn, bend, back and tilt.
  - Each layer is simulated per pose in rest order.
  - 34 suit cones over arm, elbow, thigh and spine. The `_h` twins give a piecewise response.
  - Also: the skirt follow-gain fit, and a Dem Bones diagnostic with a leave-one-out drive.
- **Correctives:** pose-space shapes per layer.
  - I scanned λ (numpy on `rig.npz`).
    - At λ 1e-4 the fit overfitted. The jacket's leave-one-out p90 was 118 mm, and 798 mm for a cone that only one pose drives.
    - At λ 0.03 the training fit stays ≤ 13.8 mm and the leave-one-out p90 drops to 24 mm.
  - The spatial cone masks cost 7–10 mm of fit, so they are off.
- **Layer tuck (`tuck_layers`):**
  - An under-layer vertex counts as covered when a ray along its normal meets a layer further out within 5 cm. Covered vertices sink along their normal: the shirt by 12 mm, the waistcoat by 7 mm.
  - The sink is feathered over 3 cm from the visible vertices.
  - Covered: 7309 of 7561 shirt vertices and 3312 of 3577 waistcoat vertices.
- **Rever:** its own weights (the wrap weights, then smoothed spatially at 3 cm, three times).
- **Export:**
  - Every made part goes out as `rig_<part>`, with the shipped weights and one shape key per cone. The keys are fitted on the part itself, on the tucked rest.
  - `suit_rules.json` holds the cone rules and the fitted skirt gains.

### Numbers (c1f)

| Check | Gate | Result | Met |
|---|---|---|---|
| Fit RMS per pose (runtime vs sim, worst layer) | ≤ 15 mm | ≤ 13.8 mm in all 35 poses | yes |
| Runtime penetration, jacket | 0 | 16–460 per pose | no |
| Collar band at CB (runtime) | 10–17 mm | in band in 19 of 35 poses | no |

- **Fit RMS** by pose: high ready 13.8, bend20 10.3, turnr20 9.3, arm raise 8.1 mm. The leave-one-out p90 is about 25 mm; the worst poses are high ready (37.5) and flex120 (34.7).
- **Shoulder rise over the sim:** the runtime is ≤ 10 mm in every pose; plain LBS is 13–56 mm.
- **Penetration:**
  - Runtime: 16–460 jacket vertices per pose sit inside the layers under it (relaxed 148, arm raise 129, walk 151, turnr20 460). Where the waistcoat shows, at most 64 of its vertices are inside.
  - Sim, after the push: jacket ≤ 13, waistcoat ≤ 2.
  - Root cause: each layer's corrective fit misses by 1–14 mm RMS, independently of the others. That is more than the 2–7 mm gap between layers.
  - The tuck cut the jacket count by about half (relaxed 287 → 148).
  - Next step: bind the covered under-layer regions to the outer layer's runtime instead of fitting them separately.
- **Collar band** (shirt collar above the jacket collar at the CB, runtime):
  - Out of band: high ready −12, twist −13, the elbow and flexion ramps 1–8, flex90 23, back15 19 mm.
  - The sim misses in the same poses (high ready −18, twist −23). With the arms forward, the jacket's neck rides up past the shirt collar; the neck hold is too weak there.
- **Seam hinges** (runtime: count over 20°, p99, max):

  | pose | > 20° | p99 | max |
  |---|---|---|---|
  | arm raise | 69 | 103° | 163° |
  | knee up | 102 | 160° | 177° |
  | walk | 112 | 169° | 178° |
  | fist | 83 | 160° | 179° |

  The folds sit on the under-sleeve seams, against the side and front panels: the armpit seam folds over.
- **Jacket bones:**
  - Of the eight designed bones, only `front_l` can be driven: leave-one-out 5.2° over a 10.6° range.
  - The skirt bones' leave-one-out is close to their whole range (front 18–19° of 25–28°).
  - The skirt keeps the follow bones, with fitted gains; skirt RMS went from 48.2 to 44.6 mm.
  - The chest and side are left to the correctives. No bones were added to the armature.
- **Determinism:** the twin c1det, simulated from scratch, matches c1 bit for bit: shirt `dc4d2b86`, waistcoat `ed9d8562`, jacket `203a6b81`. The cache record carries it (`--twin posed=…c1det`); the determinism guard passes.
- **Export deviation** (made-part shapes vs the drape runtime, worst pose):
  - jacket body 5.3 mm, waistcoat 2.5 mm, shirt shell 20 mm;
  - shirt collar 71 mm and cuffs 115 mm. This is the wrap of a thick ring through a bent wrist.

## Item 7: wrinkle maps and the suit cloth path

### Cloth path (`web/src/character/cloth.ts`, `suitCloth.*` in `params.ts`)

- **`SuitClothMaterial`** is now the material for every suit cloth: the lofted `suit_*` and the made `t13*`. Setting `suitCloth.on` to 0 restores T6.
  - Each kind (wool, silk, lining, shirt) has a sheen scale, a fuzz term on the interpolated geometric normal, and a falloff of the base specular at grazing angles: `1 − specGraze·(1 − N·V)^specGrazePower`.
- **Fit on T19's shader balls.**
  - Each kind is fitted per light, net of the world, against Cycles (`bench/m1/v4/cloth_balls.py fit`; the output is `data/build/t13/balls/cloth_fit.json`).
  - The fit was then checked with fresh renders (`v_*`). Engine/Cycles ratios:

    | ball | key | fill | rim | T19 (key / fill / rim) |
    |---|---|---|---|---|
    | wool | 0.989 | 1.012 | 1.034 | 1.02 / 1.04 / 0.67 |
    | silk | 0.995 | 1.010 | 1.002 | 1.06 / 1.09 / 2.20 |

  - Fitted values:
    - wool: sheen 0.01, fuzz 0.37, graze 0.08 at power 3;
    - silk: sheen 0.16, fuzz 0, graze 0.8 at power 1.5.
  - The silk's excess under the rim came from its GGX lobe at grazing angles: 2.0× Cycles with no sheen and no fuzz at all.
- **Terminator specks on the wool ball** (seen at 100 %): 4–8 single bright pixels along the key light's terminator.
  - Cause: the wrapped fuzz reaches past N·L = 0 and meets shadow-map acne. T6's path had the same specks at strength 0.15.
  - `fuzzWrap` 0 removes them but drops the rim to 0.40, so the wrap stays.
  - The fix belongs in the shadow terms. TRAA hides the specks in motion.
- **Texture budget:** the wrinkle maps are one three-layer array texture per material, which is a single binding. The cloth stays within WebGPU's limit of 16 sampled textures.

### Wrinkle maps (`blender/character/suit_wrinkle.py`, baked in the posed export)

- **Bake steps:**
  1. Per made part and pose, take the sim normal minus the runtime normal (LBS + shapes). Both are taken back to rest by the blended skinning rotation.
  2. Fit the deltas per vertex over four groups (arms up, arms down / crook, hip, torso), per side. The centre line is blended over ±4 cm.
  3. Project per triangle onto that triangle's own tangent frame.
  4. Rasterise into the material atlas with 6 px dilation.
- **Output:** `suit_wrinkle.json` and `suit_wrinkle_<material>_{0,1,2}.png`, in the posed run. `suit_made.swap` copies them next to the GLB.
- **c1f numbers:**
  - normal deltas p95 0.13–0.30 (the cuffs are the worst);
  - group maps p99 0.03–0.29;
  - under 0.2 % of texels clipped.
- **Engine:** `cloth.ts` blends the groups by the same cone weights the correctives use (`DeformRuntime.morphWeights`) and adds them to the tangent normal.
- No engine frame of the made suit yet. The A/B build that will give one is still running.

## Item 8 (started): integration

- **`blender/character/suit_made.py`:**
  - Body hash: a sha of the captured rest body. It is `f7053e02ea3b` for the current build.
  - Cache record at `data/build/suit_cache/<hash>.json`, written by `bench/m1/v4/suit_made_cache.py`.
  - Guards: seam gap, strain, penetration at rest and in the poses, and the determinism twins.
  - `swap`:
    - joins the made parts per garment and names them as the lofted ones, with `made_suit` = 1;
    - skins the LODs from the full part (`lod_from`);
    - copies the wrinkle maps beside the GLB.
  - `apply_rules` writes the suit cones and skirt gains into `character.rig.json`.
- **Build wiring:**
  - `suit.post` swaps in the made suit after the lofted build when `suit.made.enabled` is set (`config.py`; off by default) and the guards pass. `force` swaps anyway, for A/B builds.
  - The skirt pivots are taken from the lofted jacket before the swap, so the made suit's fitted gains still apply.
  - `deform_rig` (weights, tuck) and `deform_correctives` skip `made_suit` objects. `rig.post` appends the suit cones.
- **Guards today:** they fail on penetration in the poses (runtime jacket up to 460; where the waistcoat shows, 64). The default stays lofted.
- **Budget:**
  - The made LOD0 is 167k tris on its own.
  - With the default LOD choice the suit is about 103k: jacket LOD0 61k, shirt LOD1 21.6k, waistcoat LOD1 9k, trousers LOD1 11.9k. The character LOD0 would then be about 200k, over the 190k cap.
  - Jacket LOD1 (24.3k) brings it to about 166k.
  - This needs a decision from the orchestrator and T24.

### Pickup list (exact)

1. **Runtime penetration.**
   - Wrap-bind the tucked (covered) shirt and waistcoat regions to the jacket's runtime: `sr.wrap_bind` onto the jacket drape at rest, with a negative offset.
   - Fit their correctives on those targets.
   - Rerun `--posed-cache c1` and check that `inside_rt` reaches 0.
2. **Sim faults** (fix in the sim, then re-simulate):
   - Walk sleeve hole: the jacket sleeve passes inside the shirt sleeve at the back of the upper arm. Look at the shirt sleeve's collider and clearance.
   - Front-overlap tear below the button: self-contact between the two fronts, or a second hold along the button line.
   - Cuff crumple: the cuff hold is too stiff against the wrist, or the collider is wrong.
   - Neck riding up with the arms forward: a stronger neck hold in the arm-forward poses.
3. **Shirt collar and cuff wrap deviation (71 / 115 mm):** bind those parts to the drape with smaller offsets, or rig them directly from the drape weights.
4. **Twin determinism:** compare c1det's `hash` with c1's, then add `--twin posed=<c1det>` to `suit_made_cache.py`.
5. **Item 8:**
   - the A/B engine frame of `lookdev t13c-made1` (made suit forced in);
   - the LOD choice, with T24;
   - then the extras: four-in-hand tie, collar-fall tabs, atlas packing ≥ 70 %, rever UV roll, lapel sheen patch, LOD2 specks, waistcoat shoulder points and welt bend, the 60k gameplay LOD1, and the NOTES update.

### Pickup list, revised after the coordinator's decisions (do these in this order)

1. **Fix the sim faults at the source, then re-run the 35 sims** (`suit_spike.sh ... -- --posed <q7>`).
   - The walk sleeve hole: shirt shows through the upper arm in the row-5 poses of `posed_sheet_0`.
   - The front-overlap tear with the knee raised (row 4).
   - Cuffs crumpled in nearly every pose, with blobs at the wrist when the arms are out. Look at the collisions between the sleeve, the shirt cuff and the hand. Try cuff stiffness, the cuff-to-wrist distance, and self-collision there.
   - The grainy, stippled patch on the left front in the arm-raised poses (row 3, columns 1 and 3).
   - Shirt patches poking through the sleeves (row 2).
   - When the 35 sims are re-run, send main a progress note with the new sheets.
2. **Penetration: cull first, then wrap-bind.** Gate: 0 runtime jacket vertices inside, in every pose.
   - Delete the shirt and waistcoat faces the jacket hides in all 35 poses.
   - Keep:
     - the collar;
     - the front V;
     - the shirt cuff, about 1.5 cm past the sleeve;
     - anything visible when the front opens.
   - Wrap-bind what is left near the jacket to the jacket's runtime. The cull also cuts triangles.
3. **Collar band: 10–17 mm in at least 32 of 35 poses.**
   - Pin the shirt collar band to the neck frame, or constrain it there, or add a pose-driven corrective.
   - Fix the jacket neck riding up when the arms come forward. This is a sim fault.
   - Report the poses that still miss.
4. **Budget: character LOD0 ≤ 190k (cap), target ≤ 170k.**
   - Get there by culling hidden faces (item 2).
   - Jacket LOD1 at hero distance only if it holds up at 100 % in the close-up and half-body views. Show that A/B if it is used.
5. **The body hash does not match.**
   - The full build's captured body hashes to `03b724119b2a` (`lookdev 20261015T074544Z-t13c-made1`, `notes.suit.body_hash`). The spike's hashes to `f7053e02ea3b`.
   - So the A/B build found no cache record and stayed lofted. It does show the new cloth path on the lofted suit.
   - The spike's `capture_body` runs create, edit_base, rig.add and suit.add. The build also runs head_parts and hair.add before suit.add, and maybe with a different config.
   - Find which step changes the body. Then either drape the made suit on the build's body, or make the hash ignore what the suit never touches. Then rebuild the A/B and take its engine frame (port 8795).
6. **Keep the default lofted until the guards pass.**
   - The skirt keeps the follow bones with fitted gains; the chest and side are left to the correctives. This is accepted.
   - Twin determinism: done (c1det matches c1; in the cache record).
7. **Item 8 extras:**
   - four-in-hand tie;
   - collar-fall tabs;
   - atlas packing ≥ 70 %;
   - rever UV roll;
   - lapel sheen patch;
   - LOD2 specks;
   - waistcoat shoulder points and welt bend;
   - the 60k gameplay LOD1, with T24;
   - the NOTES update.
