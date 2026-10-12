# m1 v2 Track E: the Cycles hero stage

_2026-10-12. Owner: Track E. Code: `blender/hero/`, `bench/m1/hero.sh`. Recipe: `direction.md` §5._

## What it is

A scripted, headless stage that takes a character build (the kept `character.blend`, including any
`hero_only` render-only geometry, or a GLB) and renders the review set: nine hero shots in a wet
neon-noir alley, graded, plus the honesty turntable.

```sh
KEEP_BLEND=1 bench/m1/lookdev.sh --config bench/m1/variants/direction.json <label>   # the build
bench/m1/hero.sh [--preview|--final|--draft] [--shots LIST] [--no-turntable] <character.blend> <label>
bench/m1/hero.sh --regrade <run dir>        # re-grade the EXRs without re-rendering
```

Runs land in `data/build/hero/<UTC>-<label>/` (main checkout, gitignored): `<shot>.png` (graded),
`<shot>_paint.png` (painterly A/B), `exr/<shot>.exr` (scene-linear, Combined + IndexOB),
`turntable/<pose>_<view>[_clay|_normal].png`, `sheet.png`, `stage.json` (seconds, samples, pose logs), `grade.json`.

| Module | Job |
|---|---|
| `rig.py` | **The shared light rigs** (every track's evidence renders): `hero` = the §5 base rig placed relative to the camera; `turntable` = 5,600 K three-point on an 18 % grey cove. Cameras (presets, `tt<deg>`, custom `az=..,el=..,lens=..,aim=..,frame=..,f=..`), Cycles settings, clay and normal passes, grey-card calibration. Also a CLI. |
| `poses.py` | Poses on the game_engine rig, in armature space (roll-independent): analytic two-bone IK with a hinge-preserving twist, planted feet (yaw, heel lift, flat toes), hand orientation with the roll on the forearm, finger curl, head look. Poses: `rest`, `stand`, `stand_profile`, `walk`, `ready` (compressed high-ready), `ready_low`. |
| `sets.py` | The alley: Poly Haven CC0 wet asphalt (height-map + noise puddles, roughness 0.035, rain-ripple bump), brick and concrete walls with a wet base band, kerbs, invented neon signs (blade signs HOTEL / RAMEN / OPEN, wall words BAR / KISSA, tube ring / arrow / zigzag / bars; magenta, teal, amber, red) each with a colour spill light, a doorway bulkhead lamp, pipes, AC units, a dumpster, sagging overhead cables, sodium and cool street lights at the two ends; rain streaks generated per shot in the camera's view volume. The whole set turns on one root so every camera looks down the alley. |
| `shots.py` | The shot list (lens, pose, resolution, rig overrides, haze, rain, framing shift, exposure). |
| `stage.py` | Renders the shots to EXR and the turntable to PNG; fills in Cycles SSS on the skin only when the build has none (reported). |
| `grade.py` | Compositor grade on the EXRs (separate compositor-only scene). |
| `sheet.py` | Contact sheet. |
| `fetch_textures.py` | Fetches the three Poly Haven sets into `data/vendor/polyhaven/` and prints their provenance records. |

## The shared rig (`rig.py`, merged to main at 53bc1a8)

```sh
blender -b -t 3 --factory-startup --python-exit-code 1 --python blender/hero/rig.py -- \
    --in RUN/character.blend --out DIR --light hero|turntable|both \
    --cam portrait,bust,profile,back,full,draw,hands,eye | tt | tt90 | "az=30,el=5,lens=85,aim=head,frame=0.45,f=2" \
    --pose rest|stand|walk|ready --quality draft|preview|final --passes beauty,clay,normal [--haze] [--calibrate]
```

- **Ratios are irradiance ratios at the subject**: each area light's power is `ratio * E_key * pi * d^2`, so a light can move without changing its ratio. The rig is placed relative to the camera (azimuth measured from the camera axis, + = camera-left), so every view gets the same light.
- **Hero rig** (direction §5): key 3,000 K, 0.8 m square, 1.5 m, 40° camera-left, 25° up, 1.0; magenta rim strip (0.3 x 1.5 m) behind-right; teal kicker strip behind-left; cool fill 0.08; 10 cm eye light at the lens, 0.12, no shadow, diffuse 0.3 (mostly a catchlight). Emitters are invisible to the camera. Near-black world, AgX "Medium High Contrast", exposure −0.6 EV, `HERO_E` = 3.0.
  - **Deviation**: rim 1.4 and kicker 0.8 in the shared rig (spec 0.7 / 0.4). At the spec ratios the rims did not separate the hair from black. In the alley shots they go to 2.2 / 1.2 (`shots.RIMS`), because the rims there also compete with the sign spill.
- **Turntable**: 5,600 K key 1.0 (45° camera-left, 30° up), fill 0.3, rim 0.5, an 18 % grey cove that turns with the camera, AgX look None, exposure 0, no DOF, haze or grade. Calibrated with `--calibrate`: an 18 % card at the chest reads 0.44 display, a 35 % card 0.57.
- **Passes**: `clay` (grey 0.5, roughness 0.55, normal maps off, alpha cut-outs kept) and `normal` (camera-space shading normal including normal maps, Standard view, 16 spp).
- **Cameras**: 24 mm vertical sensor fit, so `frame` is the frame height in metres at the aim point. Aim points are `eyes`, `head`, `chest`, `body`, `hands`, `hand_l` and `hand_r`, posed. DOF focuses on the near eye for head shots, at the shot's f-stop.

## The hero stage

### Shot list (`shots.py`)

| Shot | Lens / framing | Pose | Light (on top of the hero rig and the set) |
|---|---|---|---|
| portrait (§5 #1) | 85 mm, f/2 on the near cornea, head and shoulders, ¾ (az 30), face on the right third | stand (F `hero`), eyes to camera | base rig, rims 2.2 / 1.2, drizzle (700 streaks), haze 0.008, wet hair tips, 35 water beads per shoulder |
| sign (#2), 1152x2048 poster | 50 mm f/4, full body, camera at 1.1 m | stand (F `hero`: left hand at the jacket button) | magenta key 1.2 x 0.4 m above-right 1.3, teal across the street 0.5, sodium 2,000 K 0.3, heavy rain (2,200), puddles |
| profile (#3) | 100 mm f/2.8, bust profile | stand, head straight, chin 2–3° down | amber key 0.3, teal rim 2.5 from beyond the face, magenta kicker 0.35, wet tips, beads |
| draw (#4) | 35 mm f/5.6, ¾ full body, camera at 1.2 m | ready (F `high_ready`, empty hands) | hard 4,300 K "headlight" 0.18 m source, low right, 1.0; magenta top 0.4 |
| hands (#5), 1152x2048 poster | 100 mm f/5.6 from 5.4 m, camera at 0.75 m: from the cuff to the floor, so the shoe and trouser break are in frame; focus on the cuff | cuff (F `hero` body, E's arms: the right hand pinches the left shirt cuff) | key 0.8 |
| eye (#6) | 135 mm at 0.42 m, f/16 (about 9 mm depth of field, the same as f/5.6 at 0.73 m) on the near cornea, eyes and brow | stand, gaze 5° off camera | soft key 1.2 m, eye light 0.3 |
| bust | 50 mm f/2.8, ¾ | stand, eyes to camera | base rig + rims, wet tips, beads |
| back | 50 mm f/2.8, back ¾ (az 150): hair and suit back | stand | base rig + rims, wet tips, beads |
| walk | 35 mm f/5.6, ¾ full body (az −35) | walk (mid-stride) | base rig + rims, rain |
| turntable (#7) | 50 mm, 8 views at 45°, 1080x1620 | rest (A-pose) and stand | turntable rig; beauty + clay + normal |

The shot list follows direction §5, plus the brief's bust, back and walk shots. Deviations:
- **Under the sign** uses F's canonical `hero` pose, with the left hand at the jacket button (that is the "buttoning" read). Its weight is on the left leg, not §5's right.
- **Eye close-up**: §5 gives 135 mm at 0.4 m but no f-stop. At 0.4 m, f/2.8 holds only about 1.6 mm in focus, so lids, lashes and skin go soft. f/16 holds about 9 mm, the same as f/5.6 from 0.73 m.
- **Every head shot focuses on the near cornea**, the eyeball centre plus 12 mm toward the camera. Focusing on the centre (Track A's diagnosis) put the focal plane 12 mm behind the lashes.

**Wet look (`wet.py`, render side, transient)**:
- **Water beads**: 35 per shoulder (0.5–1.5 mm, flattened water drops, IOR 1.33, transmission) on the posed jacket surface, on top of the shoulder between the clavicle and the arm joint. They are added in the close-ups and are in the character mask and the flagged-light receivers.
- **Wet hair tips**: on the outer 30 % of each strand (UV0.v root → tip), the base colour drops to ×0.55 and the roughness to ×0.45. One value node per hair material drives it, set to 1 in every rain shot.
- **Eyes to camera**: the eyeballs (one skinned mesh on the head bone) turn toward the camera, or `gaze` degrees off it, by rotating each eyeball's rest vertices about its centre. The turn is capped at 28° because the lids don't follow. `stage.json` logs the angles, and the change is undone before the next shot.

**100 % crops**: `hero.sh --crop close` (or a shot list) also renders each listed shot at 100 % resolution, cropped to half the frame each way around the near eye (head shots) or the cuff (hands): `<shot>_crop.png`, with no vignette or paint. Preview renders at 50 %, so this is the close-up evidence. A crop costs about as much as the preview shot itself.

### Set and render decisions

- **The set turns, not the camera** (`sets.turn`): the alley is parented to one root and turned to the camera's azimuth + 15°, so every shot looks down the alley with depth and signs instead of at a flat wall (it1 showed flat brick behind the profile and the portrait).
- **Flags (Cycles light linking)**: in the alley, the camera-relative key, fill and eye light light only the character (`rig.receivers`). Without the flags the cheat key lit the walls behind him (it4: a beige wall behind the portrait). The sign and draw shots keep their keys unflagged, because those keys are motivated sources that should hit the ground.
- **Haze**: one homogeneous volume box that starts 0.6 m behind the subject, as seen from the camera ("haze behind the face, not in front of it"), density 0.006–0.012 /m. The spec's 0.03 /m over a 16 m deep box washed the frame in it1.
- **Puddles**: the Poly Haven height map plus 0.35 /m noise, thresholded (about 35 % wet). Water is roughness 0.035, albedo ×0.35, with a faint ripple bump. The rest of the asphalt is wet (albedo ×0.5, roughness ×0.55).
- **Rain**: per shot, 500–2,200 thin tilted 3-sided cylinders in the camera's view volume (1.3–16 m), transparent plus glossy, kept 0.35 m away from the eyes. No motion blur: they read as streaks because they are long.
- **Skin SSS (render side, reported)**: the current build ships `skin_head` and `skin_hands` with Subsurface Weight 0. Cycles has no other route to red bleed, so `stage.py --skin-sss auto` (the default) sets direction §2's values (Random Walk Skin, weight 1, radius (1, 0.25, 0.12), scale 2.5 mm, anisotropy 0.8), but **only when the build has none**. `stage.json` and the sheet header list the materials it touched. Once Track A ships its own SSS, the stage leaves it alone.
- **Grade** (`grade.py`, linear, before AgX Medium High Contrast):
  - Kuwahara painterly A/B: anisotropic, 5 px at 1080p, mix 0.6, **masked off the character** by IndexOB (§4: the face stays real).
  - Bloom: threshold 1.0, strength 0.35.
  - Red-orange halation: Fog Glow, threshold 2.0, strength 0.12.
  - 0.8 % lateral dispersion.
  - CDL: slope (1.04, 1.0, 0.94), offset (−0.0008, 0.0004, 0.0016), so shadows go teal and highlights amber.
  - Black lift 0.0011, saturation 1.04.
  - Vignette −0.3 EV.
  - Grain 2 %, multiplicative.
  - Grading one image takes 0.2–0.8 s, so `hero.sh --regrade RUN` re-tunes the grade without re-rendering.

### Poses (`poses.py`) and Track F's runtime

- `stand`, `ready` and `ready_low` are Track F's canonical `hero`, `high_ready` and `low_ready` (`blender/character/deform_poses.POSES`). `stand_profile` is F's `hero` with the head straight ahead and the chin 2–3° down. Every other deform_poses name works too, as does `f:<name>` for one shadowed by an E pose (`f:walk`).
- E's own solver poses stay available as `stand_e`, `ready_e`, `ready_low_e` and `walk`. F only has a walk as a deformation test pose, so the hero `walk` (¾ mid-stride, heel contact, push-off foot) is still E's.
- **Every pose runs F's deformation runtime afterwards** (`poses.deform`, called by `poses.apply`, which `rig.pose` and `stage.py` both use). It sets the helper bones (twist split, deltoid and hip helpers, jacket-skirt follow) and the corrective shape keys from the armature's `deform_rules` property, or from `character.rig.json` next to the .blend. Shape keys that are not correctives keep their values; the reference runtime zeroes every key it doesn't drive. Builds from before F merged carry no rules, and the pose log says "no rules (helpers at bind)".
- The log of each pose (source, active correctives with their weights) goes to `stage.json` / `rig.json`.
- `bench/m1/deform_hero.py` (Track F's wrapper) is now redundant: it applies the same runtime a second time, which is idempotent.
- What broke with E's solver poses on the pre-F build (main2): in `ready`, the hands interpenetrate (a support hand wrapped around a closed hand needs contact, which pose data alone doesn't give), and the hands read as mittens or claws in every pose.

## Runs (evidence)

All under `data/build/hero/` in the main checkout. Builds come from `data/build/lookdev/`.

| Run | Build | What changed / what it showed |
|---|---|---|
| `20261012T192008Z-it1` … `20261012T194137Z-it4` | pre-forms main | first set and rig passes: haze too thick (0.03 /m), flat brick behind portrait/profile (→ the set turns), cheat key washing the walls (→ flags), spill and far-end glow too strong, wall words facing the wall |
| `20261012T200818Z-main2-preview` | `20261012T194340Z-heroE-main2` (main + track A forms freeze) | all nine shots + rest turntable (interrupted at tt135 by the load cap); `sheet.png` |
| `20261012T203233Z-main2-flags` | same | light-linked key/fill/eye; portrait, sign, draw, profile |
| `20261012T204204Z-main2-final-timing` | same | final portrait at `-t 3`: stopped after 35 min with the shot unfinished (to free the one Blender slot for the track F integration) |
| **`20261012T212025Z-main3-F`** | **`20261012T211741Z-heroE-main3` (main ff03f62, track F merged)** | F's poses + runtime: portrait, draw, profile, hands, walk, stand turntable tt0/tt90 (beauty, clay, normal); `sheet.png` |

## Render time per shot

Measured at `-t 3` on a shared, loaded machine (load 9–50 on 16 cores), so the numbers are upper bounds.

**Preview** (64 spp, adaptive 0.05, 50 % resolution = 960x540 / 576x1024, OIDN):

| Shot | s | Shot | s |
|---|---|---|---|
| portrait | 105–119 | eye | 140 |
| sign (poster) | 148–151 | bust | 126 |
| profile | 102–144 | back | 123 |
| draw | 106–129 | walk | 146–169 |
| hands | 86–122 | turntable view (1080x1620 @ 50 %) | beauty 13–25, clay 14–21, normal 4–7 |

- One preview set (9 shots, plus 8 views x 2 poses x 3 passes) is about 19 min of shots plus 12 min of turntable at `-t 3`.
- Grading takes 0.2–0.8 s per image.
- Building the set takes 0.1–0.2 s.

**Final** (768 spp, adaptive 0.012, 100 %, OIDN): see "Final timing" below.

## What the stage shows about the character (main ff03f62, run main3-F)

For the owning tracks. The stage doesn't fix any of these.

- **A (head, skin)**: the skin is waxy and peach. The build ships no subsurface on `skin_head` / `skin_hands` (the stage adds direction §2's values render-side, as reported), and the lips read orange. Under the 85 mm key the face planes are still broad.
- **B (hair)**: the cards read as strips or ribbons in the portrait and the back ¾, with no fine strands at the silhouette under the magenta rim.
- **C (beard, brows)**: the beard is a dark felt mass with a hard edge against the cheek, and the brows are dash strokes.
- **D (suit)**:
  - Collar and lapel "wings" stand above the shoulders, in rest pose too.
  - The shoulders are boxy.
  - There is a torn flap at the jacket's back hem.
  - The wool reads brown-grey under the warm key (no sheen).
  - Sleeves and trousers are tubes.
  - New in the hands shot: a jagged, sawtooth black edge along the shirt cuff where it meets the sleeve.
- **F (deformation)**: the runtime runs; the portrait's pose log shows `corr_arm_down_l 0.58, corr_arm_down_r 0.80, corr_elbow_l 0.33, corr_hip_fwd_r 0.11, …` active.
  - `hero` with the left hand at the jacket button gives the hands shot a natural "hand on the garment" read.
  - The hands still read as mittens or closed fists (no articulated fingers).
  - In `high_ready` the clasped hands sit high on the chest and the stance is square, not bladed.

## Verdicts

- **Shared rig + turntable**: done, merged earlier (53bc1a8). The calibration cards read as intended.
- **Alley set, haze, rain, signs**: done. It reads as a wet neon-noir alley with depth behind every shot.
  - Limits:
    - No rain motion blur.
    - No water beads or wet hair.
    - The alley's far end is a flat emissive plane.
- **Grade**: done.
  - The painterly A/B is subtle at preview resolution. It is masked off the character on purpose (§4).
- **Shot list**: 9 shots + turntable, all render.
  - §5's "buttoning / cuff" hand-on-garment shot is effectively covered by F's `hero` pose in the hands shot.
- **Poses**: F's canonical poses plus the runtime are in every render. E's walk is kept.
- **hero.sh**: writes PNGs, painterly A/B, the sheet and stage.json, including for an interrupted stage (`--regrade` re-grades).
- **Final quality**: see "Final timing".
