# m1 v2 Track D: the suit

Goal (BRIEF, direction.md defect 7): turn the grey, boxy costume into a sharp, close-cut near-black three-piece that reads as black wool under the neon-noir hero light and the turntable. Everything is still built on the body by script; the GLB stays game-ready and the Cycles-only detail goes into the kept `.blend` after the export.

The rounds come newest first: round 4, round 3, round 2, then sections 1–9 (round 1, as reported on `suitD-v2c`). Where they disagree, the later round wins.

## Round 4: v3h (from the review of v3e)

Round 3 was merged at b2ab739. The review asked for a small round 4. Two more items came in while it ran:

1. **The collar beside the neck.** In `crop_tt0_collar_x3.png` the jacket collar still formed a lumpy, folded tab where it met the shirt collar at each side of the neck. The target is a clean stand that wraps the neck and lies flat on the shirt collar, with the roll line running on from the stand to the notch: no tab and no doubled edge.
2. **The arm_raise shirt-collar bulge**, 5.1 mm in v3e (1.9 mm in v3b). Bring it back to 2 mm or less. Fix it on my side first (body hide, shirt weights). If the cause is Track F's `corr_arm_up_l`, change only its shape on the shirt, and say so.
3. **Faceted cuffs** (added after main 9ac04e9). In `trackG/final4/hero_cuff.png` the shirt cuff ring read as a polygon. Make the cuff and sleeve openings read round at 100 % in a hand close-up, within the tri budget.
4. **The cuff zigzag** (added after main 82d99a7). In `hero/…-main6-hands/hero_ready_side.png` the right shirt cuff folded into a jagged zigzag in high_ready. The cuff is stiff, interfaced cloth: it should stay round and turn with the forearm, not shear. A Track H pistol will sit in these hands soon.

The final run is **`20261013T032928Z-suitD-v3h`**, built from 3c032bb on main 82d99a7 (Track G's hands and Track E's bladed high-ready included).

### R4.1 What changed, and the files touched

**The collar beside the neck** (`suit_neck.py build_jacket_collar`; `suit.py` DEFAULTS `jacket.collar`)

*Diagnosis.* Cross sections of v3e in the neck frame showed where the tab came from.

- The shirt band leans in toward the neck, by about 0.7 m per metre at the side.
- The jacket's stand was a straight line from the seam to the fold. The fold took its radius from the widest shirt in the 15 mm below it, which is the band's flared base. That held the fold 1–2.5 cm off the band at the side of the neck.
- In front views this showed as a hollow between the two collars, with the jacket's stand standing up beside it: the tab and the doubled edge.
- The fold also dropped toward the gorge from 30 % of the way round (`drop_frac` 0.3). That held it low beside the neck, and the outer edge turned a corner where the end patch met the natural fall.

*Fix.*

- **The fold hugs the band at its own height** (`fold_win_m` 4 mm, was an implicit 15 mm). `shirt_clear_m` goes from 3 to 1.5 mm.
- **The stand has a knee** (`knee_m` 3 mm, `knee()`).
  - The stand's middle row is a knee 3 mm above the shirt band's base. The stand runs from the seam over the shoulder to the band's base, then up the band, leaning in with it.
  - The knee goes far enough out that both halves clear the shirt and the body (`need_at()`).
  - Below the knee the body clearance ramps from the seam's own (the block's, about 5 mm) up to `body_clear_m`.
  - The fold fairing re-places the knee. The fall is draped a collar thickness off the bent stand, along its normal (`stand_r()`).
- **The roll line peaks beside the neck** (`drop_frac` 0.3 → 0.2). The fold drops toward the gorge only in front of the side, so it runs down to the notch without a step.
- **The end patch runs past the side** (`patch_frac` 0.2; it defaulted to `end_frac`, 0.09), so the outer edge is one curve from the collar point round the side.
  - Only the end columns, up to `i_e`, are resampled onto the roll line. The columns past it keep their own stand and fold.
  - Resampled all the way to `i_b`, the fold slid along the neckline and the straight end stands crossed the next columns' fold rows (q29, jacket self-intersection 68).
- **The fall is held off the stand.** A last pass, after the edge settle, puts every fall point at least a collar thickness off the stand, along the stand's normal.
  - Where the seam swings out at the side of the neck, the knee's lower half lies nearly flat on the trapezius.
  - There the radial rest held the fall only about 2 mm off it. Fall rows 6–7 crossed it, which showed as a speck on the fall (q31).

**The trapezius ring under the shirt** (`suit.py hide_body`; DEFAULTS `hide_enclosed.trim_edge`)

- Under the enclosed bones (upper arm, clavicle, torso), a face that is covered all round now goes as soon as one of its vertices is past the 3 cm margin.
- Kept whole, those faces left a ring of vertices 4–5 cm out on the trapezius. The nearest truly visible vertex was 47.9 mm away. They survived only because they shared faces with vertices inside the margin.
- That ring is what `corr_arm_up_l` lifted 3.3 mm through the shirt in arm_raise (R4.4).
- 52 faces go; the body goes from 15648 to 15544 tris. The head and neck rule and the margin itself are unchanged.

**The cuffs and the sleeve ends** (`suit_inner.py build_cuffs`, `suit_build.py ring_points_smooth`, `suit_jacket.py` sleeve; DEFAULTS `shirt.cuff_*`, `jacket.sleeve`, `budgets`)

- **The shirt was being decimated.** It had 2812 tris against a 2200 budget, so `budgets.decimate` collapsed it every build.
  - The collapse ate the cuff rings first: 16 segments, with bands 2–3 mm wide. That is the polygon in `hero_cuff.png`.
  - The shirt's collar was being decimated too.
  - The shirt budget is now 3600, and the shirt ships undecimated (3580 tris).
- **The cuff is round.**
  - 48 segments (`cuff_segments`) round a closed Catmull-Rom curve through the sleeve end, instead of a straight resample of the sleeve's polygon.
  - The outer edge is a quarter round of 1.2 mm (`cuff_edge_r_m`). It was a square corner.
- **The cuff is rigid** (`cuff_rigid`).
  - Every cuff vertex is weighted 1.0 to `lowerarm`. Track F's twist split then moves it onto the forearm twist bone, so the ring turns with the forearm as one piece.
  - Weighted from the nearest skin, the cuff's reveal had taken up to 0.72 `hand` and 0.14 `thumb_01`, and it sheared into the zigzag when the wrist bent.
- **The sleeve is rounder.** It has 40 columns, up from 28, so the end reads round. The jacket budget goes from 16000 to 18000; the jacket is 17747 tris.
- **The sleeve end is rigid too** (`end_rigid_m` 4 cm).
  - Over the last 4 cm, the hand's and fingers' share of the weights goes to the forearm: in full over the last 1.3 cm, eased in over the 2.7 cm above.
  - The end had about 0.24 hand weight. It turns with the forearm round the rigid cuff and does not shear with the wrist.

**Bench** (`bench/m1/suit_pose_test.py`; `suit_views.py`)

- **`suit_pose_test`'s ID pass broke with the hand nails.** Track G added a 14th mesh, the nails.
  - Adjacent IDs, 1/255 apart, decoded one low in the dark sRGB range. The background sphere counted as the body, and every pose read thousands of px "over rest".
  - The IDs are now spread over the 8-bit range (`STEP`). The numbers below for v3f and v3h are both from the fixed tool.
- **New views:**
  - `tt0_collar` and `bust_collar`: the collar along the turntable's and the hero bust's camera rays;
  - `collar_rf`, `collar_lf`: each side, square on;
  - `collar_rs`: the right side from a little forward.

Files: `blender/character/suit.py`, `suit_neck.py`, `suit_inner.py`, `suit_jacket.py`, `suit_build.py`; `bench/m1/suit_views.py`, `suit_pose_test.py`.

**Shared files: none edited in round 4.** One experiment (R4.4) patched Track F's `deform_correctives.py` for a single labelled build. The patch was reverted straight after the build and is not committed.

### R4.2 Measurements (direction config)

| | v3e | v3h |
|---|---|---|
| gap from the shirt collar to the jacket collar's inner face, mean over the top 10 mm of the stand (`/tmp/suitwork/gap.py`; 0° = the wearer's left, 90° = back): side 0° / 180° | 9.1 / 9.1 mm | 3.6 / 3.6 mm |
| the same, 20° / 160° (just behind the side, where the tab stood) | 13.7 / 13.9 mm | 4.2 / 4.4 mm |
| the same, 40° / 140° · 60° / 120° · back 90° | 9.7 / 9.7 · 4.9 / 4.9 · 3.9 mm | 3.2 / 3.5 · 2.0 / 2.2 · 1.9 mm |
| the same, −20° / 200° (the collar end, in front of the side) | 10.8 / 11.1 mm | 8.1 / 8.4 mm |
| top of the jacket's stand at the side of the neck | z 1.588 | z 1.597 |
| `suit_collar` self-intersection (≤ 120) | 79 (shirt 42, jacket 34, tie 3) | 86 (shirt 47, jacket 36, tie 3). Skin 0 px, all garment pairs 0, order 0. The shirt's +5 come from the undecimated shirt; v3f, with the decimated shirt, had 42 |
| `suit_collar` backface px (closeup / front / 3/4 / profile) | 110 / 242 / 147 / 86 | 110 / 242 / 147 / 81 |
| deform poke-through: rest / knee_up / arm_raise / head_turn / walk | 0 / 2 / 3 / 1 / 0 | 0 / 6 / 1 / 0 / 0 |
| arm_raise body > shirt | 2 vertices, 5.1 mm | 1 vertex, **2.0 mm** (the right throat) |
| arm_raise shirt > jacket (right clavicle) | 6.3 mm | none |
| knee_up shirt > jacket | none | 5 vertices, 3.1 mm: the left cuff's thumb side against the jacket's skirt at the hip, where the hanging arm rests (R4.3, item 4) |
| knee_up body > trousers (code unchanged) | 5.1 mm | 5.1 mm |
| `suit_pose_test` px over rest (fixed tool), v3f → v3h: arms_up / kick / crouch / stress | 110 / 46 / 866 / 989 (v3f) | 110 / 36 / 840 / 955 |
| shirt tris | 2199 (decimated from 2812) | 3580 (undecimated; the cuffs 48 round with a rounded edge) |
| jacket tris | 15347 | 17747 (40-column sleeves) |
| body tris after `hide_body` | 15648 | 15544 (52 trapezius faces trimmed) |
| character total (main6 = main before this round, with the hands) | 123139 tris (main6) | 126872 tris (≤ 150k). 83 bones (≤ 90), ≤ 4 weights per vertex, 0 glTF errors. Hair +56, because its cards collide with the collar |
| hands pierce (`hands_render --pierce`): cuff, ready | 0, 0 (main6) | 0, 0 |

**Guards on `suitD-v3h`:** `suit_check` PASS, `suit_collar` PASS, `suit_pose_test` as above, and Track F's `deform_test` as above. The materials and the lighting are unchanged.

### R4.3 Verdicts

| item | verdict | evidence (in `suitD-v3h/suit_ba/`) |
|---|---|---|
| 1. The collar beside the neck | **Fixed, with a softer corner left on the outer edge.** In the turntable crop the upright ear and the hollow between the collars are gone on both sides. The jacket collar rises from the shoulder and lies against the shirt collar as one stand: the gap at the top of the stand is now 2–4.5 mm all round the back and sides (it was 4–14 mm). Its inner edge runs on into the lapel's roll line. There is no doubled edge. At the hero light the collar wraps the neck more tightly, and the roll line runs from behind the neck down to the notch. **What is left:** where the outer edge turns over the shoulder it still makes a corner, most visible on the left of the tt0 frame. At the hero light, on the far side of the neck, the same turn reads as a peak at the top of the roll. It is softer than v3e's tab and lies flat; it is not folded. Smoothing it means re-cutting the fall's outline at the side (`fall_side_m` against `fall_back_m`, and the end path), which I left. | `crop_tt0_collar_x3.png` (v3e above, v3h below), `crop_hero_bust_collar.png`, `crop_hero_bust_collar_x3.png`, `tt0_final.png`, `hero_bust_final.png`; studio and clay pairs `tt0_collar`, `bust_collar`, `collar_rf`, `collar_lf`, `neck34`, `neck34r`, `neck_front` |
| 2. arm_raise shirt-collar bulge ≤ 2 mm | **Met, at 2.0 mm, on my side only.** The 3.3 mm trapezius poke is gone (the hide trim). The skin blob at the shirt collar's front in the arm_raise tile is gone. The one vertex left is at the right throat, at 2.0 mm; it is moved by Track F's `corr_arm_fwd_r`, not `corr_arm_up_l`. **I did not change any corrective's shape on the shirt.** The shirt does not move in either corrective, the body does, and the target was met without it. The cause, a correction to round 3 and a tested fix for Track F are in R4.4. | `deform_arm_raise.png` (v3e above, v3h below), `deform_arm_raise_shoulder_top_l.png`, `../deform-suitD/` |
| 3. Faceted cuff and sleeve ends | **Fixed.** At 100 % and at 2x the cuff is a round ring with a rounded edge, and the sleeve end's rim is round. The polygon came mostly from the shirt's decimation (R4.1). | `hero_cuff.png` (left: `trackG/final4`, right: v3h), `crop_hero_cuff_x2.png`, `../suit_cuff/` |
| 4. Cuff zigzag in high_ready | **Fixed.** Both cuffs stay round in high_ready and turn with the forearm; the wrist bends inside them. With 8 mm of ease round the wrist, the ring stands a little off the back of the bent wrist, as a stiff cuff does. **Side effect, for the record:** in knee_up the left cuff's thumb side now touches the jacket's skirt at the hip by 3.1 mm. The arm hangs against the hip there, and the cuff no longer bends away with the hand (v3f 0, v3g with the hand-weighted cuff 1.6 mm). It is hidden between the wrist and the skirt in the knee_up tiles. For Track H's pistol, the cuff and the last 4 cm of the sleeve now ride on the forearm only, and hand pierce is 0 in the cuff and ready poses. | `hero_ready_side.png`, `hero_ready.png` (left: main6's blend, right: v3h, both posed with today's high-ready), `../suit_ready/` |

### R4.4 Item 2: cause, a correction to round 3, and a tested fix for Track F

**Which vertices poke.** I used a copy of `deform_test` that prints the poking vertices (`/tmp/suitwork/deform_dbg2.py`). I ran it on v3f with the runtime rules cut down, so that each morph's share shows.

| v3f body vertex (rest) | depth | cause | why it is there |
|---|---|---|---|
| left trapezius (0.134, −0.007, 1.558) and its neighbour | 3.3, 2.1 mm | `corr_arm_up_l`'s body shape moves it 8.2 mm; the shirt above moves 0.7 mm. With no morphs it does not poke | past the hide margin (47.9 mm from the nearest visible vertex); kept only through shared faces. **Fixed** by the hide trim |
| right throat (−0.033, −0.072, 1.545) | 2.2 mm (v3h: its neighbour, 2.0 mm) | `corr_arm_fwd_r`'s body shape moves it 12.7 mm; the shirt there moves 0 | 12.8 mm from the neck's kept skin: inside the margin, so it cannot be hidden |
| right trapezius (−0.107, −0.021, 1.564) | 1.6 mm | plain skinning (with no morphs too) | under 2 mm |

**A correction to round 3.** R3.3 said that in v3e `corr_arm_up_l` "moves the shirt by 15.3 mm and the body by 0". That was wrong: I had read the offsets of the wrong mesh. In v3e that corrective moved the left throat skin by 30.7 mm (its neighbour by 15.3 mm), and the shirt there by about 0. Its largest body offset was 54.9 mm. The poke is the body being pushed out, not the shirt.

**Why the throat moves (Track F's bake).**

- `Baker._rest_cover` marks a body vertex as under a garment when the nearest garment point within `cover_m` (7 cm) lies on its inside (s < 0). There is no check that the garment is actually over the skin.
- A replay of the test on v3e (`/tmp/suitwork/bakecover.py`) marked 40 front neck-base vertices under the jacket. For the ones it listed, the nearest jacket point was 67–69 mm away, with s between −0.2 and −5 mm.
- In the pose, `collide` then pushes those vertices along −n of whichever jacket face is nearest. Near the neck that can be the folded collar, whose stand faces the neck. That means the throat skin is pushed out, through the shirt collar.
- `deform_test` itself already rules such vertices out: a covered vertex must also hit the garment along its own normal.

**Experiment** (`20261013T025101Z-suitD-v3f-fexp`, `/tmp/suitwork/fexp_patch.py`; reverted, not committed).

- The same ray rule was added to `_rest_cover` for the body.
- On v3f, `corr_arm_up_l`'s body shape fell from 94 vertices at up to 32.5 mm to 65 at up to 8.4 mm. Its body > jacket pushes fell from 11 to 5.
- The right-throat poke went. The trapezius pair stayed (3.3 mm), as the table predicts; the hide trim deals with those.
- In v3h, `corr_arm_up_l` still moves the body by up to 45.8 mm and `corr_arm_fwd_r` by up to 34.4 mm. The 2.0 mm is met, but only just.

**Suggested for Track F:** require the ray hit in `_rest_cover` for the body, the rule `deform_test` already uses.

### R4.5 Evidence (`data/build/lookdev/`)

- `20261013T023414Z-suitD-v3f`: the collar fix alone, on main b2ab739. Its `suit_ba/` holds the v3e-vs-v3f collar pairs, and `suit_ba/v3e/` holds v3e's studio and clay views.
- `20261013T025101Z-suitD-v3f-fexp`: v3f with Track F's cover test given the ray rule. Experiment only (R4.4).
- `20261013T030630Z-suitD-v3g`: + the round cuffs, the undecimated shirt, the 40-column sleeves and the hide trim, on main 9ac04e9.
- **`20261013T032928Z-suitD-v3h`**: final. It adds the rigid cuff and the forearm-rigid sleeve end, on main 82d99a7. Built with `THREADS=3 KEEP_BLEND=1 bench/m1/lookdev.sh --config bench/m1/variants/direction.json suitD-v3h`.

Inside `suitD-v3h`:

| dir | what |
|---|---|
| `suit_ba/` | before and after.<br>**The crops asked for:** `crop_tt0_collar_x3.png` (Cycles 256 spp, 3x; v3e above, v3h below), `crop_hero_bust_collar.png` and `crop_hero_bust_collar_x3.png` (the hero light, Cycles 256 spp; v3e left), `deform_arm_raise.png` (Track F's arm_raise sheets, v3e above, v3h below) with `deform_arm_raise_shoulder_top_l.png`.<br>**Full frames:** `tt0_final.png`, `hero_bust_final.png`.<br>**EEVEE studio and clay pairs:** `tt0_collar`, `bust_collar`, `collar_rf`, `collar_lf`, `neck34`, `neck34r`, `neck_front` (v3e left).<br>**Hands:** `hero_cuff.png`, `crop_hero_cuff_x2.png` (left: `trackG/final4`, the same tool at 32 spp, 800 px), `hero_ready_side.png`, `hero_ready.png` (left: main6's blend posed today, 16 spp, 720 px, as in `hero/…-main6-hands`). |
| `suit_final/` | Cycles at 256 spp: `hero_bust.png`, `turntable_tt0.png` |
| `suit_cuff/`, `suit_ready/` | `bench/m1/hands_render.py` (hero light): cuff, cuff_top; ready, ready_side. `suit_ready/main6/` is the before |
| `suit_v5/`, `suit_v5_clay/` | EEVEE studio and clay views of v3h |
| `suit_check/`, `suit_collar/`, `suit_pose/` | the suit guards |
| `deform-suitD/` | Track F's `deform_test` (rest, knee_up, arm_raise, head_turn, walk) |

### R4.6 Iteration log (run → change → verdict)

The q runs are scratch builds under `/tmp/suitwork/`: no head refine, drape off. "isect" is `suit_collar`'s gated self-intersection count (the limit is 120).

| run | change | verdict |
|---|---|---|
| q22 | v3e's defaults | reference (isect 76): the hollow and the upright stand beside the neck |
| q24 | `fold_win_m` 4 mm + the knee | the fold lies on the band; the knee was thrown 1 cm out where the lower half is short (109) |
| q25 | the clearance below the knee ramps up from the seam's own | fixed (79) |
| q26 | `shirt_clear_m` 1.5 mm | kept (84) |
| q27 | `drop_frac` 0.2 | the roll line peaks beside the neck, not in front of it (102) |
| q28 | `patch_frac` 0.2 alone | tested alone (104); combined with q27 in q29 |
| q29 | q27 + `patch_frac` 0.2 | one smooth diagonal from the collar point, but jacket self-intersection 68: the resample to `i_b` slid the fold and the straight end stands crossed it (110) |
| q30 | `patch_frac` 0.25 | the hollow came back at the side (115); back to 0.2 |
| q31 | the end columns resampled only to `i_e` | the stands no longer cross (92); a speck on the fall at the side, where fall rows 6–7 cross the knee's lower half |
| q32 | a blend between the patch and the natural columns | no change (92); reverted |
| q33 | the fall draped a thickness off the stand along its normal | the speck stayed (96) |
| q34 | + the last pass that holds the fall off the stand | the speck is gone; isect 78, jacket 36 |
| q35 | q34 as the DEFAULTS | 78 |
| `suitD-v3f` | official build of the collar | item 1 as in R4.3. arm_raise body > shirt 3 at 3.3 mm |
| v3f, rules cut down | `deform_test` with no morphs, with each morph alone, and with the body left out of `corr_arm_up_l` | the poking vertices and their causes, as in R4.4 |
| `suitD-v3f-fexp` | Track F's cover test given the ray rule (experiment) | the body corrective max went from 32.5 to 8.4 mm and the throat poke went; the trapezius 3.3 mm stayed |
| `hidewhy.py` | a replay of the hide test on v3f | the trapezius pair is 47.9 mm from the nearest visible vertex, kept only through shared faces |
| `suitD-v3g` | + the hide trim, 48-segment cuffs, the undecimated shirt, 40-column sleeves | arm_raise 1 at 2.0 mm; the cuffs read round. knee_up shirt > jacket 1.6 mm (the cuff's thumb side, weighted to the thumb). The pose test read thousands of px: the ID bug, fixed |
| `suitD-v3h` | + the rigid cuff and the forearm-rigid sleeve end; on main 82d99a7 | final; see R4.2 and R4.3 |

### R4.7 Branch

`worktree-agent-a7cee946dd031f936` contains main 82d99a7 and adds three commits:

- 0af22f0: the collar beside the neck (v3f)
- 3c032bb: the cuffs, the sleeves, the hide trim and the pose-test IDs (v3h)
- the report commit, which changes only this file

`suitD-v3h` was built from 3c032bb.

## Round 3: v3e (from the review of v3b)

The review of v3b (merged at 51a0e8b) asked for one last round of three items:

1. **Collar edge (the priority).** The collar's jagged outer edge and the dark tab beside the neck show in every portrait. Make the edge a clean, smooth curve with thickness.
2. **Waistcoat edge in the hero bust.** Give the front edge a thin highlight (a slightly rounded, bevelled edge plus the sheen) so the V reads in the lapels' shadow. Don't brighten the cloth.
3. **Body patch in arm_raise.** A patch of body pokes 45 mm through the jacket in arm_raise. Delete or tuck the body faces fully covered by the jacket and shirt, if that's safe for the deformation.

The final run is **`20261013T011529Z-suitD-v3e`**. It was built from 946033f on main 0954592, which includes the hero-stage rig changes, Track C round 4 and Track A.

### R3.1 What changed, and the files touched

**The collar** (`suit_neck.py build_jacket_collar`; `suit.py` DEFAULTS `jacket.collar`)

- **The edge is faired** (`edge_fair_passes` 20).
  - The edge row is smoothed 1-2-1 as angle, height and radius in the neck frame. The angle is unwrapped first, so the edge does not shrink round the neck. The collar points stay fixed.
  - The fall rows follow the edge in proportion to their distance from the fold.
  - Each point is then put back outside every layer beneath it:
    - outside the stand (a new BVH of rows 0–4), because the fall must not cross its own stand;
    - outside the block and the lapels, along the ray from the neck axis;
    - `rest_m` off the nearest surface beneath, measured along that surface's normal. On the sloping shoulder the radial clearance alone let the fall cut into the jacket (q3, self-intersection 284).
- **The edge is settled** (`edge_settle_passes` 30).
  - The rest above lifts single points back over the lapels and the stand, which left bumps of up to 1.2 mm across the edge at the sides of the neck.
  - Each settle pass smooths the height 1-2-1, moves the radius outward only, then rests again. The edge ends up lying over the bumps as one curve.
- **The edge has thickness** (`edge_r_m` 1.25 mm, `under_m` 4 mm).
  - The outer edge is now a rounded bead: two rows go round the edge (at 90° and 180°), then a lip turns 4 mm under. The edge is 2.5 mm thick and catches a highlight line.
  - In v3b the edge was a single-sided lip row. It read as a hairline that flickered against the layers under it.
  - Each end (from the collar point down to the notch) gets its own rounded strip, `collar_end_l` / `collar_end_r` (24 faces). The thickness therefore carries on round the point.
- **The ends are held as built** (`hold_end`). The rest pass had snapped the collar point 7 mm up, off the lapel's rounded top edge, which kinked the point into a flap. The end path, from the notch to the collar point, now keeps its built position.
- **The fold is faired** (`fold_fair_passes` 6).
  - The stand and fold rows are smoothed along the collar, outside the end patches: height 1-2-1, radius outward only.
  - The fold is the collar's top roll line, the part that shows above the shoulder in a front view. Its bumps fall from a 4.6 mm maximum (rms 1.45) to 2.3 mm (rms 0.53).
- **The side fall is shorter:** `fall_side_m` 4.2 → 3.5 cm. At 4.2 cm the fall beside the neck stood out as a wing.
- **Debug:** `SUIT_NECK_DUMP=<prefix>` writes the collar grid as JSON after the Coons patch and after the fairing. It is unset in builds.

**The waistcoat edge** (`suit_inner.py front_panel(round_edge=)`; `suit.py` `waistcoat.edge_m`, `edge_press_m`)

- The V's edge rolls from the front over a quarter round (radius 1.25 mm) to its apex. One extra column 2 mm in from the edge marks the pressed flat.
- The rounded normals pick up the key and rim light, so a thin highlight line runs down the V in the lapels' shadow.
- The material is unchanged; the cloth is not brightened.
- The first version, in `suitD-v3c`, was a half round turned under. Its back faces looked backwards, so the deform rig's rest tuck (`deform_rig.tuck`) read 4 of them as pierced through the lapel. It sank them along −n by up to 3 cm, which made a dark spike beside the tie. The quarter round has no backward-facing normals: `pierced_at_rest` is 0 for the waistcoat.

**The body under the jacket** (`suit.py hide_body`; DEFAULTS `hide_enclosed`, `hide_self_m`)

- **Diagnosis.** The kept patch was a core of inner-arm and armpit vertices that the cone test called visible, plus the 3 cm margin round it.
  - Their rays crossed the hollow under the arm and met the jacket 8–15 cm away, beyond `hide_ray_m` (6 cm).
  - Other rays passed through the torso and met a garment 0.3–1 m away. The torso is not an occluder, and its own covered faces go.
  - The shirt does not reach there; the jacket alone covers the armpit.
- **Fix, part 1.** For vertices whose dominant bone is under `upperarm`, `clavicle` or `spine`, a cone ray may travel 20 cm before it meets a garment (`hide_enclosed`). The jacket closes round these parts; the only ways out are the collar, the cuffs and the hem.
- **Fix, part 2.** A ray that meets the body before any garment counts as blocked if, carried on through the body, it ends on a garment within 1.5 m (`hide_self_m`). The line of sight then ends inside the suit.
- **Unchanged:** the head and neck are never touched, and the 3 cm margin round any truly visible vertex stays.
- **Result.** Arm and shoulder body vertices left after the hide fall from 164 to 18. The 18 are at the base of the neck, inside the neck's margin. Body tris go from 15912 to 15648, and the armpit patch is gone in the body-only renders.
- **Deformation.** Body > jacket poke-through is 0 in every pose of Track F's `deform_test` (v3b: up to 45.8 mm).

**Views** (`bench/m1/suit_views.py`): new `neck34`, `neck34r` and `neck_front_p` (perspective at 85 mm, 30 cm frame), and `cpoint_rx` (an extreme close-up of the right collar point).

Files: `blender/character/suit.py`, `suit_neck.py`, `suit_inner.py` and `bench/m1/suit_views.py`.

**Shared files: none edited in round 3.** `deform_rig.py` and `deform_correctives.py` are Track F's and were not touched.

### R3.2 Measurements (`suitD-v3e`, direction config)

| | v3b | v3e |
|---|---|---|
| collar outer edge | a single-sided lip row | a rounded bead 2.5 mm thick (radius 1.25 mm) with a 4 mm lip under it; rounded strips round both collar points |
| collar fold line (top roll): bump across the curve between the end patches* | rms 1.45 mm, max 4.64 mm | rms 0.53 mm, max 2.28 mm |
| collar outer edge: bump across the curve between the end patches* | rms 0.17 mm, max 0.66 mm | rms 0.17 mm, max 0.55 mm |
| collar fall at the side of the neck | 4.2 cm | 3.5 cm |
| `suit_collar` self-intersection (≤ 120) | 75 (shirt 42, jacket 30, tie 3) | 79 (shirt 42, jacket 34, tie 3); skin 0 px; backface px (closeup / front / 3/4 / profile) 107 / 242 / 153 / 192 → 110 / 242 / 147 / 86 |
| waistcoat V edge | a 2.5 mm lip turned under | a quarter round, radius 1.25 mm, pressed flat 2 mm; `pierced_at_rest` 0 |
| shirt in front of the waistcoat (`speck.py`) | 0 | 0 |
| body tris after `hide_body` | 15912 | 15648; arm and shoulder remnant 164 → 18 vertices |
| deform poke-through: rest / knee_up / arm_raise / head_turn / walk | 0 / 7 / 4 / 3 / 3 | 0 / 2 / 3 / 1 / 0 |
| largest body > jacket poke-through | 45.8 mm (arm_raise) | none in any pose |
| suit tris (GLB) | 32283 | 32619: jacket 15347 (+336 for the bead and the end strips); shirt, waistcoat, buttons, tie, shoes and trousers unchanged |
| character total | 121351 tris, 83 bones | 121443 tris (≤ 150k), 83 bones (≤ 90), ≤ 4 weights per vertex, 0 glTF errors |
| shirt:wool median luminance, neon (bust / body) | 39.25 / 36.88 | 37.41 / 36.32 |
| shirt:wool median luminance, studio (bust / body) | 26.72 / 22.82 | 24.14 / 22.40 (target ≥ 20) |

\* Measured on the scratch collar grids q4 (v3b's edge row and fold) and q22 (v3e's settings), dumped with `SUIT_NECK_DUMP`. The metric (`/tmp/suitwork/edgemetric.py`) is each point's distance off the cubic through its two neighbours on each side, across the curve. That cancels the collar's own curvature round the neck and any uneven spacing along it. The end patches are reported apart, because the collar point is a corner by design.

The edge row was already within 0.7 mm of a smooth curve in v3b. What read as jagged was three other things:

- the one-sided lip (a hairline with no thickness);
- the bumpy fold line above it;
- the ends: teeth near the point, and the 7 mm kink at the collar point.

**Guards on `suitD-v3e`:**

- `suit_check`: PASS
- `suit_collar`: PASS
- `suit_pose_test`: arms_up 94, kick 50, crouch 871, stress 1096 px (the same as v3b)
- Track F's `deform_test`:
  - rest 0
  - knee_up 2: body > shirt 1.5 mm, body > trousers 5.1 mm
  - arm_raise 3: body > shirt 2 at 5.1 mm, shirt > jacket 1 at 6.3 mm
  - head_turn 1: body > shirt 1.5 mm
  - walk 0

The shirt's luminance ratio moves a little because the waistcoat's rounded edge and the jacket's bead add lit pixels to the wool. The material settings are the same as in v3b.

### R3.3 Verdicts

| item | verdict | evidence (in `suitD-v3e/suit_ba/`; left = v3b, right = v3e) |
|---|---|---|
| 1. Collar: jagged outer edge, dark tab beside the neck | **Edge fixed. Tab smaller and smooth, but still there.** The outer edge is a clean rounded curve with thickness. In the turntable, the hero bust and the 3/4 close-ups it reads as a rolled edge with a highlight along it. The steps and the hairline are gone, the collar point is clean, and the fold line above the shoulder is smooth. Seen from the front, the collar's side still shows as a dark shape beside the neck, where it lies over the trapezius on its way back. It is now a smooth, rounded collar side, not a ragged upright tab. Making it narrower would mean changing the collar's cut (the fall and the end path), which I did not attempt in this last round. | `crop_tt0_collar_x3.png`, `crop_tt0_collar.png`, `tt0_final.png`, `crop_hero_bust_collar_vest.png`, `neck34_studio.png`, `neck34_clay.png`, `neck34r_*.png`, `neck_front_*.png`, `cpoint_rx_*.png` |
| 2. Waistcoat edge in the hero bust | **Done, subtle at full frame.** The V's edge is a rounded, pressed edge. In the neon close-up it shows a clear highlight band along the edge. In the Cycles hero bust it reads as a thin, continuous light line from under the lapel down to the top button, a little clearer than v3b's lip. The cloth is not brightened. | `crop_hero_bust_vest_edge_x3.png`, `vest_top_r_neon.png`, `vest_top_r_studio.png`, `vest_top_r_clay.png`, `hero_bust_final.png` |
| 3. Body patch in arm_raise | **Fixed.** The armpit patch is gone from the body-only renders, and body > jacket is 0 in all five deform poses (v3b: 45.8 mm in arm_raise). The rest pose shows no holes. **One side effect, for Track F:** the small poke-through at the base of the neck, under the shirt collar's front, grew in arm_raise (v3b 1 vertex at 1.9 mm; v3c 0; v3d 6.9 mm; v3e 2 vertices at 5.1 mm). It shows as a small skin bulge at the collar's front in the arm_raise tiles. The rest geometry there is identical in all four builds, and so are the skin weights. What changes is Track F's `corr_arm_up_l` corrective: in v3b it moved the body there by 5.6 mm, and in v3e it moves the shirt by 15.3 mm and the body by 0 (wrong: the body moves, see R4.4). The corrective is baked from delta mush over the body mesh, so the body's new topology changes it. | `body_front.png`, `body_armpit.png`, `body_shoulder_front.png`, `deform_arm_raise.png`, `../deform-suitD/` |

### R3.4 Evidence (`data/build/lookdev/`)

- `20261013T003728Z-suitD-v3c`: the first round-3 build. It had the waistcoat spike (the half-round edge under the rest tuck). Its `suit_ba/v3b/` holds the v3b re-renders.
- `20261013T010947Z-suitD-v3d`: the quarter-round edge, without the collar settle. Superseded.
- **`20261013T011529Z-suitD-v3e`**: final. Built with `THREADS=3 KEEP_BLEND=1 bench/m1/lookdev.sh --config bench/m1/variants/direction.json suitD-v3e` from 946033f on main 0954592.

Inside `suitD-v3e`:

| dir | what |
|---|---|
| `suit_ba/` | before/after pairs, left = v3b, right = v3e.<br>Crops: `crop_tt0_collar_x3.png`, `crop_tt0_collar.png`, `crop_hero_bust_collar_vest.png`, `crop_hero_bust_vest_edge_x3.png`.<br>Cycles 256 samples: `tt0_final.png`, `hero_bust_final.png`.<br>Cycles preview: `tt0.png`, `tt45.png`, `hero_bust.png`.<br>EEVEE studio and clay: `neck_front`, `neck34`, `neck34r`, `neck_front_p`, `cpoint_rx`, `vest_top_r`.<br>Neon: `neck34`, `vest_top_r`.<br>Body only: `body_front.png`, `body_shoulder_front.png`, `body_armpit.png`.<br>Deform: `deform_arm_raise.png`, v3b's sheet above and v3e's below.<br>The v3b halves are in `suit_ba/v3b/`. They were re-rendered with today's hero rig, because main changed the lighting after v3b; the two sides of each pair are lit alike. |
| `suit_final/` | Cycles at 256 samples: `hero_bust.png`, `turntable_tt0.png` |
| `suit_hero/` | Cycles preview: hero bust, full, back, hands; turntable at 0°, 45°, 180°, 270° |
| `suit_v3c/`, `suit_v3c_clay/`, `suit_v3c_neon/` | EEVEE close-ups: neck front, neck 3/4 both sides, neck front in perspective, notch, collar point, waistcoat top, torso, bust, front. The directory names come from the round-3 evidence script; the images are v3e's. |
| `suit_body/` | the body alone (clay): front, back, shoulder, armpit |
| `suit_lum/`, `suit_lum_studio/` | shirt:wool luminance (`lum.json`) |
| `suit_check/`, `suit_collar/`, `suit_pose/` | the suit guards |
| `deform-suitD/` | Track F's `deform_test` (rest, knee_up, arm_raise, head_turn, walk) |

### R3.5 Iteration log (run → change → verdict)

All scratch runs are under `/tmp/suitwork/`. They are no-head-refine builds with the drape off. "isect" is `suit_collar`'s gated self-intersection count (the limit is 120).

| run | change | verdict |
|---|---|---|
| q0 | v3b's defaults | reference (isect 72): the edge is a one-sided lip with steps; a tab at each side of the neck |
| q1, q2 | all the fall rows faired in the neck frame; a longer Coons patch at the ends (`patch_frac` 0.3) | the fall crossed its own stand (isect 159, backface px); 287; both dropped |
| q3 | edge fairing and the bead, radial push only | isect 284: on the sloping shoulder the radial clearance let the fall cut into the jacket |
| q4 | the bead only (1.25 mm radius, 4 mm lip) | the edge has thickness and a highlight (77) |
| q7 | q4 + edge fairing (20 passes), the stand BVH and `rest_on` along the surface normal | the edge is one curve round the back; a flap at the collar point (77) |
| q8 | 50 fairing passes | the side wing moved out (91); back to 20 |
| q9–q12 | bead normals from one grid orientation; a tangent-based bead direction at the ends | the flap at the collar point stayed |
| q13 | `hold_end`: the end path is not re-rested | the collar point is clean; the rest pass had lifted it 7 mm (74) |
| q14 | `fold_fair_passes` 6 | the fold line behind and beside the neck is smooth (74) |
| q15 | `fall_side_m` 4.2 → 3.5 cm | the wing beside the neck is smaller (74) |
| q16 | + the rounded end strips and the waistcoat's rounded edge (a half round) | isect 74, 0 specks, jacket +336 tris |
| q17, q18 | `hide_body`: a ray that meets the body before a garment is blocked when it carries on to one (within 6 cm, then at any range) | no change (164 → 163 vertices): the armpit core's rays cross the hollow under the arm and meet the jacket at 8–15 cm without touching the body |
| q19 | + under the upper arm, clavicle and torso, a ray may travel 20 cm | the armpit patch is gone (164 → 18, those 18 at the neck base inside its margin). Scratch deform test: body > jacket in arm_raise 9 (112.5 mm) → 0 |
| `suitD-v3c` | official build | the collar and the armpit as in q19. A dark spike beside the tie: the rest tuck sank 4 backward-facing vertices of the half-round edge by up to 3 cm |
| q20 | the waistcoat's edge as a quarter round | 0 pierced in a replay of the tuck's test (`vpierce.py`), 0 specks, isect 74 |
| `suitD-v3d` | official build of q20 | no spike; superseded by v3e |
| q21, q22 | `edge_settle_passes` 10, 30 | the edge's largest bump 1.16 → 0.70 → 0.55 mm; isect 75, 76 |
| `suitD-v3e` | final (946033f on main 0954592) | see R3.2–R3.3 |

### R3.6 Branch

`worktree-agent-a7cee946dd031f936` contains main 207d4df and adds four commits:

- abb5ed0: the collar edge, the waistcoat's rounded edge and the armpit hide
- a347bdb: the waistcoat edge as a quarter round
- 892bb75: the collar edge settle
- the report commit, which changes only this file

`suitD-v3e` was built from 946033f, which is 892bb75 before the rebase onto 207d4df. The rebase brought in only main's hero-set change (`blender/hero/sets.py`, `hero-stage.md`); the suit code is identical.

## Round 2: v3 (from the review of v2c)

The review of `suit_final/turntable_tt0.png` and `hero_bust.png` (v2c, merged at a5ea570) listed five items, in this order:

1. the shoulders and upper arms read as football padding
2. the waistcoat is invisible
3. the collar ends stand up beside the neck like straps
4. the button crease (try a front dart)
5. folds at the elbow crook and the back of the knee should read as folds, not only as shading

The final run is **`20261012T232535Z-suitD-v3b`**, built from 01101ce on main 7d82def (Track B hair round 3 and Track C facial hair are in).

### R2.1 What changed, and the files touched

- **Natural shoulder** (`suit_jacket.py`, `suit.py` DEFAULTS `jacket.shoulder`).
  - In v2c the shoulder point was placed past the A-pose deltoids, with the line held level from the neck and then dropping, so it read square. The point now comes from the acromion: the place where the body's top line turns down more steeply than 40° (`point_from: "acromion"`), plus 1.2 cm.
  - The line runs straight from the neck point (`slope_ease: "linear"`) and is lifted 2 cm clear above the point so it doesn't cut the trapezius (`clear_above_point_m`).
  - The deltoid belongs to the sleeve head, which covers it with ease.
  - Result: the shoulder half-width is 25.7 cm (29.2 cm in v2c, 3.5 cm in per side). The line falls 3.2 cm from the neck point to the shoulder point, about 10°.
- **Slimmer sleeve** (`suit.py` `jacket.sleeve`).
  - It tapers from the bicep to the cuff: top radius 6.6 → 5.8 cm, cuff 4.6 → 4.4 cm, ease 10 → 8 mm.
  - The measured mean radius at the bicep is 6.2 cm (6.7 in v2c), about 39 cm round instead of 42; the forearm is about 4.8 cm.
- **Waistcoat that reads** (`suit_inner.py`, `suit.py` `waistcoat` and `materials.vest`, `suit_textures.py`, `suit_hero.py`).
  - The V's bottom is raised: the top button sits 17 cm above the jacket's button (13 cm in v2c; measured 15.8 cm once the V is lofted). That puts the closed front and 2–3 of its 5 buttons above the jacket's buttoning point.
  - The V's top half-width is 5 cm (7.5 cm in v2c), narrower than the jacket's opening (7.2 cm). A band of waistcoat now shows between each lapel and the shirt, up to the collar; at 7.5 cm both edges hid under the lapels.
  - The waistcoat has its own cloth, a finer, harder-finished worsted than the jacket: roughness 0.52 (jacket 0.68), sheen 0.55 at roughness 0.28 (jacket 0.35 at 0.4), specular 0.3 (jacket 0.15), and an albedo a shade lighter, (0.015, 0.016, 0.021). It has its own 1024 px atlas (`vest_px`) instead of sharing the trousers' atlas, and the hero-only twill bump is applied to it too.
  - **White specks** beside each lapel (found in `suitD-v3a`). Once the V narrowed, collar-band faces of the shirt sat in front of the waistcoat's edge. The fix has two parts:
    - A new `tuck_under_vest` samples every shirt and tie face near the V (corners, edge midpoints and centre), casts front-on rays at the waistcoat, and moves the face back 1.5 mm behind it. It runs two passes and moved 95 vertices.
    - The waistcoat's front clears the shirt by 4.5 mm (it was 3 mm). That is more than its 2.5 mm edge lip; at 3 mm the lip's edge sat up to 0.7 mm behind the shirt front.
  - Check: `/tmp/suitwork/speck.py` casts front-on rays over x ±2–8 cm, z 1.40–1.56 and finds 0 points where the shirt is in front of the waistcoat.
- **Collar ends lie down** (`suit_neck.py`, `suit.py` `jacket.lapel` and `jacket.collar`).
  - The gorge drop is gone: `gorge_drop_m` 0.045 → 0. With the gorge dropped 4.5 cm, the collar's front end ran from the notch down the roll line, so it stood beside the neck as a strap. The drop had been added for the lapel wings at the shoulders, and the wings came from the old square shoulder line, which is gone now.
  - The collar's fold is lowered by 2.5 cm in front of the neck point (`drop_m` 0.012 → 0.025, `drop_frac` 0.2 → 0.3), so the ends lie onto the lapel.
  - `end_relax` (2 passes) smooths single-point teeth along the notch and the outer edge, then puts each point back outside the layers beneath.
  - The collar's self-intersection total falls from 112 to 75.
- **Front dart and the button crease** (`suit_jacket.py` `front_dart`, `levels`). The crease had two causes:
  - **A 1 mm sliver row.** A regular ring row at z_b + 0.011 sat beside the extra row at z_b + 0.012, and its shading drew a hard line across the whole jacket at the button. `levels()` now drops any regular row within 4 mm of an extra row.
  - **The waist dip.** The fronts followed the body's waist dip, about 8 mm deep at x ±6 cm.
    - `front_dart` bridges the dip panel by panel at fixed x (5 mm steps). Per x, it takes the cloth's depth over the rows from 4 cm below to 10 cm above the button, then takes the upper hull over z, capped at 8 mm.
    - It then smooths outward only, along z and across x, and fades the move out on the side of the body. It moved 116 vertices.
    - The dart line is marked from the flap pocket to under the chest (x 10 cm, up to 15 cm above the button).
    - A first version worked per column. The columns drift about 2 cm in x and the centre wanders 5 mm per row, so it made a ridge at the button rows.
  - The front profile at x 6 cm is now smooth: y −0.1553 at z 1.109 to −0.1609 at z 1.209, with no dip at the button.
- **Modelled folds** (new `suit_folds.py`; `suit.py` calls it after the drape).
  - These are parametric crescent folds displaced along the merged vertex normals, so they are in the geometry and show in the GLB too:
    - **Elbow crook:** 5 mm amplitude, 5 cm wavelength, a Gaussian fall-off of 5 cm along the arm, a 1.2 cm crescent bend, crook side only (cos^1.5 about the bisector).
    - **Back of the knee:** 4 mm, 4.5 cm wavelength, 4.5 cm fall-off, a 1 cm bend.
  - Inward moves are clipped against the body.
  - The rows got denser so they can carry the folds: sleeve rows 1.6 → 1.1 cm (at 1.6 cm the 5 cm folds aliased), trouser knee rows 2.5 → 1.2 cm. The suit budgets went up to match (below).
  - Result: jacket 892 vertices moved, max 4.96 mm, 6 clipped; trousers 308 moved, max 3.44 mm.
  - The cloth-sim normal-map folds of round 1 are kept underneath. Both drape gates pass: the jacket's p99 strain is 0.092 and its fold RMS 1.44 mm; the trousers' p99 strain is 0.109 and their fold RMS 0.96 mm.
- **Budgets** (`suit.py` `budgets`): jacket 14000 → 16000 and trousers 4000 → 5000, for the denser sleeve and knee rows. The suit is 32283 tris (29541 in v2c).
- **Views** (`bench/m1/suit_views.py`): new close-ups `notch_r`, `notch_l`, `cpoint_r`, `vest_top_r`, `waist_r`, `elbow_side`, `legs_back`.

Files: `blender/character/suit.py`, `suit_jacket.py`, `suit_neck.py`, `suit_inner.py`, `suit_textures.py`, `suit_hero.py`, the new `suit_folds.py`, and `bench/m1/suit_views.py`.

**Shared files: none edited in round 2.**

### R2.2 Measurements (`suitD-v3b`, direction config)

| | v2c | v3b |
|---|---|---|
| jacket shoulder half-width | 29.19 cm | 25.70 cm |
| jacket shoulder width − body bideltoid (56.0 cm) | +2.4 cm | −4.6 cm (the sleeve head covers the deltoid) |
| shoulder line, neck point → shoulder point | level, then dropping | straight, 3.2 cm fall (about 10°) |
| sleeve top / cuff radius, ease | 6.6 / 4.6 cm, 10 mm | 5.8 / 4.4 cm, 8 mm |
| sleeve mean radius at the bicep | 6.7 cm | 6.2 cm |
| jacket chest width | 43.66 cm | 43.18 cm |
| waist suppression | 0.726 | 0.7345 |
| gorge | z 1.4818, 3.2 cm below the suprasternale | z 1.5268, 1.3 cm above it |
| waistcoat V bottom, top button above the jacket button | 13 cm (setting) | z 1.3081, 15.8 cm (measured); 5 buttons |
| waistcoat V top half-width | 7.5 cm | 5.0 cm |
| front dart | none | 116 vertices, ≤ 8 mm |
| modelled folds | none | elbow 892 vertices (max 4.96 mm), knee back 308 (max 3.44 mm) |
| suit tris (GLB) | 29541 | 32283: jacket 15011, shirt 2199, waistcoat 2999, buttons 2130, tie 432, shoes 4824, trousers 4688 |
| character total | 129537 tris, 81 bones | 121351 tris (≤ 150k), 83 bones (≤ 90), ≤ 4 weights per vertex, 0 glTF errors |
| shirt:wool median luminance, neon (bust / body) | 47.2 / 50.0 | 39.25 / 36.88 |
| shirt:wool median luminance, studio (bust / body) | 27.7 / 24.0 | 26.72 / 22.82 (target ≥ 20) |

The character's total went down, even though the suit went up by 2.7k, because main's hair and facial hair changed underneath (Tracks B and C).

The luminance ratio fell under neon because the waistcoat band now fills part of the V where v2c showed shirt, and the waistcoat's sheen lifts the wool's median. It is still well above 20 : 1.

**Guards on `suitD-v3b`:**

- `suit_check`: PASS
- `suit_collar`: PASS. Skin 0 px. Self-intersection: shirt 42, jacket 30, tie 3, total 75 ≤ 120 (v2c 112).
- `suit_pose_test`: arms_up 94, kick 50, crouch 871, stress 1096 (v2c 94, 51, 837, 1078).
- Track F's `deform_test`: rest 0, knee_up 7, arm_raise 4, head_turn 3, walk 3 pokes (v2c 0, 8, 4, 3, 2).
  - The largest is still body > jacket, from the body remnants that `hide_body` keeps under the cloth (Track F issue 3, §3 below). In arm_raise it is now 45.8 mm (30.6 in v2c), at upperarm_twist weights.
  - None of them shows in the beauty tiles of `deform-suitD/sheet_*.png`.

### R2.3 Verdicts

| item | verdict | evidence (in `suitD-v3b`) |
|---|---|---|
| 1. Shoulders and upper arms read as football padding | **Fixed.** The shoulder line slopes from the neck straight to a point just past the shoulder's edge, and the sleeve tapers from a slimmer bicep to the cuff. In the turntable the silhouette reads lean rather than padded. The figure's own deltoids are broad (bideltoid 56 cm at 1.85 m), so in the A-pose the shoulders still look broad. That width is the body's, under a sleeve head with 8 mm of ease; it is not the jacket's. | `suit_ba/tt0_final.png`, `suit_ba/tt0.png`, `suit_ba/tt180.png`, `suit_ba/hero_bust_final.png` |
| 2. The waistcoat is invisible | **Fixed in the front views; partly in the 3/4 hero bust.** In the front studio and neon close-ups, the waistcoat's edges run inside the lapels and 3 buttons show above the jacket's button. In the Cycles hero bust, the shirt now narrows into a dark V with its edge and a button glint above the jacket's button, but much of it sits in the lapels' shadow. The sheen difference is real in the material but subtle on screen: an EEVEE A/B of the waistcoat's cloth against the jacket's (`vmat1`) showed no visible change, because the band is in shadow. I kept the material anyway, since it is the correct cloth and shows where the key reaches the band. | `suit_ba/waistcoat_studio.png`, `suit_ba/waistcoat_neon.png`, `suit_ba/hero_bust_final.png`, `suit_v3/vest_top_r.png` |
| 3. Collar ends stand up beside the neck like straps | **The straps are fixed; jagged steps remain at the collar's edge.** The ends are short and lie down onto the lapel with a notch in the neon front, the clay front and the Cycles turntable; the long upright straps of v2c are gone. In the clay close-ups (`neck_front`, `torso`), the collar's outer edge beside the neck still shows small jagged steps. In the turntable they read only as a small dark tab at each side of the neck. A cleaner edge there is the next collar job. | `suit_ba/collar_neon.png`, `suit_ba/collar_clay.png`, `suit_v3/notch_r.png`, `suit_v3/notch_l.png` |
| 4. The button crease | **Fixed.** The hard line across the jacket was a 1 mm sliver row; the waist dip is bridged by the front dart. The clay torso has no line across at the button. A faint horizontal line from the baked button-pull normals remains at the right front, just under the button. It is visible only in the waist close-up, and minor. | `suit_ba/crease_clay.png`, `suit_v3_clay/waist_r.png` |
| 5. Folds at the elbow crook and the back of the knee | **Elbow: fixed. Knee: partly fixed.** At the elbow, crescent folds read at the crook in studio and clay as modelled geometry rather than shading, and as soft folds at bust distance. In the studio close-up, a small pucker sits at the centre of the crook where the crescents meet. At the knee, the folds read clearly in clay and as a soft band of folds in the studio render; at full distance they are soft shading. Their amplitude was held at 4 mm to keep the trousers clean. | `suit_ba/elbow.png`, `suit_ba/elbow_clay.png`, `suit_ba/knee_back.png`, `suit_ba/knee_back_clay.png` |

### R2.4 Deviations

- **Shoulder width.** "About 1–1.5 cm past the deltoid" is read as past the shoulder's edge (the acromion), where a tailor sets the sleeve seam. The v2c shoulder was already 1.2 cm per side past the measured bideltoid and read as padding: in the A-pose the deltoid's widest point sits low on the arm, so a seam out there squares the shoulder. Now the seam is 1.2 cm past the acromion, the jacket's shoulder width is 4.6 cm under the bideltoid, and the sleeve head carries the deltoid.
- **Gorge.** It is no longer dropped. It sits at the top ring, 1.3 cm above the suprasternale (v2c: 3.2 cm below). With the natural shoulder there are no lapel wings to hide, and the drop was what stood the collar ends up.
- **The waistcoat's V and cloth.** The V bottom is at 17 cm above the jacket's button and the V top at a 5 cm half-width, chosen for visibility. Raising it further to 20 cm (`va`, `vb`) made more shirt-in-front specks. The waistcoat now has its own cloth and a 1024 px atlas: the GLB gains one texture set.
- **Folds.** They are modelled in the geometry, not taken from the sim. Displacing the mesh by the sim's fold field (`d2`) gave one dent at the crook, not a row of folds. The sim's normal-map folds are kept as the soft layer under the modelled ones.
- **Budgets.** Jacket 16000 and trousers 5000 (14000 and 4000 in round 1). The character is at 121k tris against the 150k budget.

### R2.5 Evidence (`data/build/lookdev/`)

- `20261012T225641Z-suitD-v3a`: the first round-2 build. It had white specks at the waistcoat edge beside each lapel. It was superseded before its Cycles finals.
- **`20261012T232535Z-suitD-v3b`**: final. Built with `THREADS=3 KEEP_BLEND=1 bench/m1/lookdev.sh --config bench/m1/variants/direction.json suitD-v3b` from 01101ce on main 7d82def.

Inside `suitD-v3b`:

| dir | what |
|---|---|
| `suit_ba/` | before/after pairs, left = v2c, right = v3b.<br>Cycles 256 samples: `tt0_final.png`, `hero_bust_final.png`.<br>Cycles preview: `tt0.png`, `tt180.png`, `hero_bust.png`.<br>Waistcoat: `waistcoat_neon.png`, `waistcoat_studio.png`.<br>Collar: `collar_neon.png`, `collar_clay.png`.<br>Button crease: `crease_clay.png`.<br>Folds: `elbow.png`, `elbow_clay.png`, `knee_back.png`, `knee_back_clay.png`.<br>The v2c halves are rendered into `suit_ba/v2c/`. |
| `suit_final/` | Cycles at 256 samples: `hero_bust.png`, `turntable_tt0.png` |
| `suit_hero/` | Cycles preview: hero bust, full, back, hands; turntable at 0°, 45°, 180°, 270° |
| `suit_v3/`, `suit_v3_neon/`, `suit_v3_clay/` | EEVEE studio, neon and clay close-ups: torso, neck front, both notches, collar point, waistcoat top, V bottom, waist, elbow, elbow side, legs back, bust, front |
| `suit_lum/`, `suit_lum_studio/` | shirt:wool luminance (`lum.json`) |
| `suit_check/`, `suit_collar/`, `suit_pose/` | the suit guards |
| `deform-suitD/` | Track F's `deform_test` (rest, knee_up, arm_raise, head_turn, walk) |

### R2.6 Iteration log (run → change → verdict)

All scratch runs are under `/tmp/suitwork/`. They are no-head-refine builds with the drape off unless noted. The collar isect is `suit_collar`'s gated self-intersection count (the limit is 120).

| run | change | verdict |
|---|---|---|
| body0 | v2c jacket with `hide_body` off | reference: where the body's shoulder, acromion and deltoid sit under the cloth |
| sh1 | shoulder point from the acromion (+1.2 cm), straight slope from the neck; sleeve 5.8 / 4.4 cm, 8 mm ease | 3.5 cm narrower per side, a natural slope and a lean sleeve; the straight line cut into the trapezius near the neck |
| sh2 | sh1 + the line held 2 cm clear above the point | clean over the trapezius; kept |
| c0 | the new shoulder with the round-1 collar | the straps still stand beside the neck (isect 100) |
| c1 | gorge drop 4.5 → 2 cm | shorter straps, still standing, with a jagged notch (98) |
| c2 | c1 + the collar's fold lowered 2.5 cm in front of the neck point (`drop_frac` 0.3) | the ends fold over and start to lie down (96) |
| c3 | c2 + collar fall at the side 4.2 → 5.2 cm | no better (96); dropped |
| c4 | c2 with gorge drop 0.8 cm | the ends still stand a little beside the neck (102) |
| c5 | c2 with gorge drop 0 | the ends are short and lie on the lapel with a notch, but have single-point teeth along the notch (81); kept |
| r1 | all round-2 defaults so far: c5 + `end_relax` 2 (the teeth), the waistcoat V at 17 cm | teeth smoothed (isect 80); the waistcoat's edges hid under the lapels |
| r2 | waistcoat V top 7.5 → 5 cm half-width | a band of waistcoat between the lapel and the shirt (72) |
| r3 | front dart at fixed x (after a per-column version made a ridge at the button rows) | the waist dip is gone from the front profile; a hard line still crossed the jacket at the button (72) |
| r4 | no regular ring row within 4 mm of the extra rows | the line is gone: it was a 1 mm sliver row (72) |
| d1 | r4 with the drape on | the sim's normal-map folds, as soft as in v2c |
| d2 | the mesh displaced by the sim's low-passed fold field at the elbow and knee back | one dent at the crook, not folds; reverted |
| d3 | modelled crescent folds (`suit_folds`), sleeve rows 1.1 cm, knee rows 1.2 cm | folds read at the crook in clay and studio, and behind the knee in clay; kept |
| `suitD-v3a` | the official build of the above | white specks at the waistcoat edge beside each lapel; the waistcoat weak in the hero bust |
| vmat1 | the waistcoat's own cloth (smoother, brighter sheen) A/B in EEVEE | no visible change (the band is in the lapels' shadow); the material kept |
| va, vb | V bottom 20 cm, V top 4 and 5 cm | more white specks; back to 17 cm and 5 cm |
| vt–vt4 | tucking the shirt and tie behind the waistcoat: vertices only; clearance 3 → 4.5 mm only; then face-sampled rays (corners, edge midpoints, centre; 2 passes) with 4.5 mm clearance | the first two left specks (they are face interiors, not vertices); the face-sampled tuck with 4.5 mm gives 0 specks in `speck.py`; collar isect 72 |
| `suitD-v3b` | final (01101ce on main 7d82def) | see R2.2–R2.3 |

### R2.7 Branch

`worktree-agent-a7cee946dd031f936` contains main 7d82def and adds three commits:

- 8f5790d: the round-2 suit changes
- 01101ce: the tuck under the waistcoat and the 4.5 mm clearance
- the report commit, which changes only this file

`suitD-v3b` was built from 01101ce.

## Round 1: v2 (suitD-v2c)

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
