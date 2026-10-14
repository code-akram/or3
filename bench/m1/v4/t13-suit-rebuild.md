# T13 phase B: the pattern-drafted suit rebuild (running report)

The suit is being rebuilt as real tailoring: drafted panels, sewn and draped (numpy XPBD), then made up with a modelled rever, turned edges, lining, pockets, vents and buttons. Phase A (spike 2) is in `t13a-suit-spike2.md`. This file gets one section per §6 item, in order.

| item | what | state |
|---|---|---|
| 1 | jacket detail, plus the phase A review fixes | **done** (this section) |
| 2 | UVs from panels (grain), port the `suit_textures.py` marks | next |
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
