# m1 v2 Track F: deformation

Branch `worktree-agent-a7a08faeda34b3e8c`. Final evidence run:
`data/build/lookdev/20261012T202211Z-deformF-full1` (full `lookdev.sh`,
`variants/direction.json`, KEEP_BLEND). Baseline: the same main with the stage
switched off (`{"rig": {"deform": null}}`),
`data/build/lookdev/20261012T192529Z-deformF-base2`.

Budgets (full1): 124 575 tris, 81 bones (65 + 16 helpers, cap 90), 4 weights
per vertex, 0 glTF validator errors. 12 sparse morph targets: the GLB grows
73.3 → 74.5 MB. The stage (`rig_post`) costs 16 s of the build.

## What the stage does

`blender/character/rig.py:post` runs after `head_refine` on the staged export
objects. Config `rig.deform` (null switches it off); the defaults live in
`deform_rig.DEFAULTS` and `deform_correctives.DEFAULTS`.

1. **Helper bones** (`deform_rig.add_bones`), 16:
   - `upperarm_twist_01`, `lowerarm_twist_01` and `thigh_twist_01` per side.
   - `deltoid_helper` (child of the clavicle, 50 % of the arm swing).
   - `hip_helper` (child of the pelvis, 50 % of the thigh swing).
   - `skirt_{front,side,back}` per side: children of the pelvis, with pivots
     found on the jacket cloth near the waist (front 15 cm, side and back 10 cm
     above the hip joint).
2. **Weight remaps.** These are generic: they read only the existing weights
   and vertex positions, so they survive Track D's rebuilds.
   - Half-joint remap at the shoulder and hip: the middle of the trunk/limb
     blend goes to the 50 % helper.
   - Twist splits by position along the bone.
   - A 3-bone finger falloff: smooth bands at each knuckle over hand/01/02/03.
   - Garments only:
     - Spatial (cross-island) Gaussian smoothing, so separate islands that
       meet at a seam carry the same weights. The collar zone is kept.
     - An "arm-free core": the chest and back of the torso garments ignore the
       arm, and the shoulder cap above the joint rides on the clavicle.
     - Skirt weights by azimuth sector, ramped in below the pivot height.
     - The body gets the shoulder-cap rule only.
   - Every mesh is then pruned to 4 influences.
3. **Correctives** (`deform_correctives`). There are 12 shape keys, one per
   side for each of these:

   | key | bake pose |
   |---|---|
   | `corr_arm_up` | arm out at 95° |
   | `corr_arm_fwd` | arm forward at 95° |
   | `corr_arm_down` | arm by the side |
   | `corr_elbow` | elbow at 86° |
   | `corr_hip_fwd` | thigh at 95° |
   | `corr_knee` | knee at 120° |

   Each key is baked in its pose:
   - Take the skinned mesh, apply delta mush (Corrective Smooth) inside the
     joint region, then a layer-collision push (each outer garment clears the
     inner layers it covers at rest by 6 mm, and the body sinks under them).
   - Spatially smooth the garment deltas, so islands don't separate.
   - Inverse-skin the result to bind space: d = M⁻¹(Y − X).
   - Buttons follow the jacket.
4. **Rest-pose tuck** (`deform_rig.tuck`):
   - Inner layers that are hidden under an outer one sink 2–8 mm under it,
     so poses have clearance.
   - Inner cloth that already pierces its cover at rest (up to 30 mm) sinks
     under it, feathered over 2 cm.
   - Not applied to visible skin or the collar zone.
5. **Rules**: `character.rig.json` next to the GLB, also stored as
   `arm["deform_rules"]` in the .blend.

### Runtime (what the game must do)

The spec is in the docstring of `blender/character/deform_runtime.py`, which
is also the Blender reference implementation. Every frame in three.js, after
`mixer.update()` and before render, apply the rules in file order:

- **`twist`**: `R_T = R_F · rot(a, f·θ)`, where θ is the twist of the source
  joint about axis a.
- **`swing`**: `R_H = R_F · slerp(I, swing, f)`.
- **`follow`** (the skirt): the source swing's rotation vector is split into
  flexion and abduction, each scaled by a signed gain.
- **`cone`** (morphs):
  `w = clamp(1 − ∠(d, t)/∠(d0, t), 0, 1)^p`, with d = the bone direction in
  its ref frame. Write it to `morphTargetInfluences[morphTargetDictionary[name]]`
  on every mesh that has a target with that name.

All vectors are in glTF model space at the bind pose. Rotations are
R_J = rot(W_J)·rot(W_J,bind)⁻¹, so the math doesn't depend on bone roll.
Without the runtime, the GLB still skins correctly, but the helpers stay at
bind: no twist split, no 50 % helpers, the skirt stays put, no correctives.

**For Track E**: `bench/m1/deform_hero.py` wraps `blender/hero/rig.py` with the
runtime and registers my poses (`--pose hero|high_ready|arm_raise|...`). A
plain `rig.py --pose` render of the new .blend shows the helpers at bind.

### Poses (canonical data for Track E)

`blender/character/deform_poses.py:POSES` holds the poses as data. The ops are
anatomical and computed from joint positions: flex, abduct, twist, turn, tilt,
aim, analytic two-bone `ik` with a hinge-aligned twist, and ground. They are:

- `relaxed`, `walk` (¾ mid-stride), `low_ready`, `knee_up`, `arm_raise` (95°), `crouch`.
- `hero`:
  - Weight on the left leg, pelvis tilt 4°, shoulders 5° back.
  - Head and neck turned 5° + 5° and tilted 1.5° + 1.5°.
  - Right hand MCP/PIP/DIP 20/35/15.
  - Left hand IK to the front button.
- `high_ready` (elbows in).
- `head_turn` (30°, collar test).
- `twist` (forearm pronation and supination, fist).

IK offsets and poles are written for the left side, and `_r` mirrors x. Until
this pass the right poles were written pre-mirrored, which crossed the
forearms through the chest.

## Harness

- `bench/m1/deform_test.sh RUN [label] [-- --poses a,b --light neon ...]` runs
  `bench/m1/deform_test.py`. It renders each pose (full, clay, and joint
  close-ups clothed and `_skin` with the garments hidden), measures
  poke-through per layer pair, and writes `poke.json`, `tiles.txt` and contact
  sheets.
- How a vertex counts as poking through:
  - **Covered at rest**: the nearest surface of the outer layer is outside it,
    a ray along the normal hits that layer, and nothing is crossed from an
    interior bone-axis anchor.
  - **Pokes in a pose**: it is outside the same part of the outer layer (the
    rest face centroid is within 4 cm), or the anchor→vertex segment crosses
    the outer layer an odd number of times and it is deeper than 1.5 mm.
- `bench/m1/deform_compare.sh A B out.png pose/tile...` builds a before/after
  strip.
- `bench/m1/deform_dev.py` reruns the stage on a kept stage-less .blend in
  about 15 s.

## Results

Poke-through counts by pose (the same harness and metric for both columns):

| pose | base (no stage) | final | notes |
|---|---|---|---|
| rest | 0 | 0 | |
| relaxed | 9 | 3 | |
| walk | 24 | 0 | trousers through the skirt are gone |
| low_ready | 65 | 43 | 38 are the left sleeve into the chest (an arm-to-body collision in the pose) |
| knee_up | 26 | 6 | before: trousers 116 mm through the jacket |
| arm_raise | 24 | 3 | before: body 109 mm through the jacket at the armpit |
| crouch | 103 | 20 | before: waistcoat 201 mm through the jacket |
| hero | 42 | 9 | |
| high_ready | 21 | 4 | |
| head_turn | 11 | 4 | |
| twist | 8 | 2 | |
| **total** | **333** | **94** | |

The remaining 2–4 body>jacket points in most poses are the same few body
remnants at the right shoulder, which Track D's hide_body leaves at rest.

### Per joint, judged from the renders

Before/after strips (top = base, bottom = final) are in
`20261012T202211Z-deformF-full1/evidence/`.

- **Sleeve head at 95°** (`cmp_shoulder.png`): **fixed.**
  - Before: the sleeve tears away from the armhole and skin shows at the
    armpit front and back, the shoulder top crumples, and the left back panel
    folds.
  - After: the sleeve stays attached, the deltoid carries a rounded cap, and
    there is no skin gap.
  - Still CG: the armpit is a smooth tube with none of the drag folds a real
    sleeve makes.
- **Shoulder, arms down**: **fixed.** Before, the shirt and body poked through
  the jacket's shoulder top. The shoulder cap rule now holds it.
- **Elbow** (`corr_elbow`): **improved.** The sleeve keeps its volume at 90°
  with no inner-elbow collapse. There are no elbow folds; it reads as a bent
  tube.
- **Forearm and wrist twist** (`cmp_forearm.png`): **improved.**
  - Before, the sleeve twisted into a candy-wrapper crease near the cuff.
    Now the twist spreads along the forearm.
  - The body forearm itself can't be judged: it is deleted under the sleeve.
  - The cuff opening shows a dark gap at ±70° pronation.
- **Fingers**: **improved.** The 3-bone falloff gives clean knuckles in the
  relaxed hand.
  - The fist thumb is still wrong: it sticks down beside the fist.
  - The ready-pose grips read as claws without a gun prop. That is pose data:
    the grips need a prop to be authored against.
- **Neck and collar at the 30° head turn** (`cmp_neck_hero.png`): **fixed.**
  - The neck doesn't go through the collar; 2 body>shirt points remain at 3 mm.
  - The back of the collar now stays smooth, where before it had a ridge.
  - The crumpled lapels and the white patches at the front of the collar are
    the same before and after: they come from Track D's rest geometry.
- **Hip and skirt** (`cmp_skirt.png`): **fixed for riding up; still reads as
  CG.**
  - Before: with the thigh raised, the thigh comes out in front of the jacket
    and pushes through the front panel. In the crouch the panels fold into the
    belly and the trousers poke through.
  - After: the front panel swings up over the thigh from a waist-height pivot
    and stays on top, and the crouch front is clean.
  - Still CG: the raised panel is a rigid flat board, a "shelf" (see
    `hero-stage/knee_up/turntable_az60_*.png`). Real cloth would wrap around
    the thigh and drape at the sides. This is what the cloth-settle
    correctives below are for.
- **Hero and high_ready under E's lights**: the hero pose reads as relaxed
  contrapposto with the left hand at the button. In high_ready the elbows are
  in and there is nothing through the chest. The hands are the weak point.

### Not done

- **Per-pose cloth-settle correctives "for renders only"** (direction §2) were
  not built. They are the next step for the knee and crouch shelf, and for the
  folds at the armpit and elbow. Approach:
  1. Pose with the runtime.
  2. Run 20–40 frames of Blender cloth on the jacket against the body and
     trousers. The machine allows two single-threaded sims at a time.
  3. Store the result as a render-only shape key per pose.
- **Dem Bones** (stretch goal): not attempted. It would need the cloth-sim
  sequences above as input. The hand-built helpers already meet the budget, so
  my guess is it only pays off for the skirt.

### Notes for Track D (rest geometry)

- The trousers pierced the jacket side skirt by up to 27 mm at the hips (62
  vertices). The tuck hides this now; the fit should be fixed at the source.
- The lapel crumple and the jagged collar edge are in the rest mesh.
- The body remnants under the right shoulder poke at rest.

## Iteration log

Dev runs are in `data/build/lookdev/deformF-dev/vN` (stage on the base2
.blend), with the harness output in `vN/deform-vN`.

| run | what changed | verdict |
|---|---|---|
| base (`…192529Z-deformF-base2`) | stage off | sleeves tear at 95°, skin at the armpit, the skirt rides up, the crouch pierces |
| v1 | helpers, remaps, correctives | sleeves connect at 95°, no armpit gaps; the skirt still pierces |
| v2 | rebased; ray cover test in the metric | metric false positives at the jaw and collar gone |
| v3 | front skirt gain 1.08 | the panel lifts more but still pierces |
| v4 | tuck, collar keep-zone, arm-free core | fewer layer pokes; a white shirt patch at the collar |
| v5 | rest-pierce fix, skirt ramp 0.01/0.10, collide cover 0.07 | better walk; the collar patch remains |
| v6 | neck zone skipped in the tuck | collar patch gone |
| v7 | shoulder cap (garments) | shirt>jacket at the shoulder top ~0 |
| v8 | shoulder cap on the body | body>shirt ~0; with the crossing metric, knee_up 102 and crouch 326: the waist folds into the belly |
| v9 | **skirt pivots moved to the cloth at the waist** | knee_up 6, crouch 20; the panel lies over the thigh |
| v10 | front pivot +15 cm, collision clearance 6 mm; IK mirror fix (pose data) | hero 114→9, high_ready 175→4 |
| v11 | trousers tuck 8 mm | walk 0; trouser speckle under the skirt gone |
| v12 | rest pierce up to 30 mm, feathered | rest trousers-through-skirt at the hips gone |
| full1 | full build with the same code | same numbers as v12 |
