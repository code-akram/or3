# m1 v2 Track E: the Cycles hero stage

_2026-10-12/13. Owner: Track E. Code: `blender/hero/`, `bench/m1/hero.sh`. Recipe: `direction.md` §5, lighting and grade superseded by `skin-direction.md` (Track E action list)._

## What it is

A scripted, headless stage that takes a character build (the kept `character.blend`, including any
`hero_only` render-only geometry, or a GLB) and renders the review set: nine hero shots in a wet
neon-noir alley, graded, plus the honesty turntable.

```sh
KEEP_BLEND=1 bench/m1/lookdev.sh --config bench/m1/variants/direction.json <label>   # the build
bench/m1/hero.sh [--preview|--final|--max|--draft] [--pct N] [--shots LIST] [--crop close|LIST] \
    [--no-turntable] [--tt-views LIST] [--tt-poses LIST] [--wb K] <character.blend> <label>
bench/m1/hero.sh --regrade <run dir>        # re-grade the EXRs without re-rendering (WB=K env for the white point)
```

Runs land in `data/build/hero/<UTC>-<label>/` (main checkout, gitignored): `<shot>.png` (graded),
`<shot>_paint.png` (painterly A/B), `exr/<shot>.exr` (scene-linear, Combined + IndexOB),
`turntable/<pose>_<view>[_clay|_normal].png`, `sheet.png`, `stage.json` (seconds, samples, pose logs), `grade.json`.

| Module | Job |
|---|---|
| `rig.py` | **The shared light rigs** (every track's evidence renders): `hero` = the §5 base rig placed relative to the camera; `turntable` = 5,600 K three-point on an 18 % grey cove. Cameras (presets, `tt<deg>`, custom `az=..,el=..,lens=..,aim=..,frame=..,f=..`), Cycles settings, clay and normal passes, grey-card calibration. Also a CLI. |
| `poses.py` | Track F's canonical poses (`deform_poses`) plus E's solver, then Track F's deformation runtime after every pose. The solver works in armature space (roll-independent): analytic two-bone IK with a hinge-preserving twist, planted feet, hand orientation with the roll on the forearm, finger curl, head look. Poses: `rest`, `stand` (F `hero`), `stand_profile`, `ready` (F `high_ready`), `ready_low` (F `low_ready`), `cuff` (F `hero` body + E arms), `walk` (E); E's own versions as `*_e`. |
| `wet.py` | Render-side wet look: water beads on the shoulders, wet hair tips (cards and strand grooms), eyes turned to the camera. |
| `sets.py` | The alley: Poly Haven CC0 wet asphalt (height-map + noise puddles, roughness 0.035, rain-ripple bump), brick and concrete walls with a wet base band, kerbs, invented neon signs (blade signs HOTEL / RAMEN / OPEN, wall words BAR / KISSA, tube ring / arrow / zigzag / bars; magenta, teal, amber, red) each with a colour spill light, a doorway bulkhead lamp, pipes, AC units, a dumpster, sagging overhead cables, sodium and cool street lights at the two ends; rain streaks generated per shot in the camera's view volume. The whole set turns on one root so every camera looks down the alley. |
| `shots.py` | The shot list (lens, pose, resolution, rig overrides, haze, rain, framing shift, exposure). |
| `stage.py` | Renders the shots to EXR (and the optional 100 % crops) and the turntable to PNG; fills in Cycles SSS on the skin only when the build has none (reported). |
| `grade.py` | Compositor grade on the EXRs (separate compositor-only scene). |
| `sheet.py` | Contact sheet. |
| `fetch_textures.py` | Fetches the three Poly Haven sets into `data/vendor/polyhaven/` and prints their provenance records. |

## The shared rig (`rig.py`, merged to main at 53bc1a8)

```sh
blender -b -t 3 --factory-startup --python-exit-code 1 --python blender/hero/rig.py -- \
    --in RUN/character.blend --out DIR --light hero|turntable|both \
    --cam portrait,bust,profile,back,full,draw,hands,eye | tt | tt90 | "az=30,el=5,lens=85,aim=head,frame=0.45,f=2" \
    --pose rest|stand|walk|ready|cuff|<any deform_poses name> --quality draft|preview|final|max [--pct N] \
    --passes beauty,clay,normal [--haze] [--calibrate]
# cameras: ';' between cameras; a single spec containing '=' is one camera
```

- **Ratios are irradiance ratios at the subject**: each area light's power is `ratio * E_key * pi * d^2`, so a light can move without changing its ratio. The rig is placed relative to the camera (azimuth measured from the camera axis, + = camera-left), so every view gets the same light.
- **Hero rig** (`skin-direction.md`, binding; it supersedes §5's 0.8 m key and Medium High Contrast look):
  - Key: 3,000 K, 0.3 × 0.3 m at 1.5 m, 55° camera-left (short lighting on the ¾ face), 30° up, ratio 1.0.
  - Wrap: same colour, 1.5 × 1.5 m at 2.0 m (my distance; the spec gives none), 35°, 10° up, ratio 0.25.
  - Magenta rim strip (0.3 × 1.5 m) at −125°, 20° up, grazing the jaw and cheek edge. Teal kicker strip behind-left.
  - Cool fill 0.08. Eye light: 5 cm at the lens, 0.08, no shadow, diffuse 0.3 (mostly a catchlight).
  - Emitters are invisible to the camera. Near-black world, exposure −0.6 EV, `HERO_E` = 3.0.
  - In the alley the key, wrap, fill and eye light are light-linked to the character (flags).
  - Ungraded `rig.py` renders use AgX Base Contrast plus the view's 3,900 K white balance; the stage's EXRs get the full grade.
  - **Deviation**: rim 1.4 and kicker 0.8 in the shared rig (spec 0.7 / 0.4). At the spec ratios the rims did not separate the hair from black. In the alley shots they go to 2.2 / 1.2 (`shots.RIMS`), because the rims there also compete with the sign spill.
  - **Measured** (portrait at 100 %, main5 build, display Rec.709 luma):
    - Lit (far) cheek: 0.51–0.52, inside the 0.50–0.55 target.
    - Shadow (near) cheek: 0.15–0.19 in the core and 0.21–0.25 in the half-tone, slightly above the 0.12–0.18 target.
    - Breakdown at 16 spp, change in shadow-cheek luma when each is removed: fill + eye light −0.043, wrap −0.043, set lights −0.033, rims 0. Even fill 0, catchlight-only eye light and a 0.15 wrap at 45° only bring the half-tone to 0.21. The rest is the key's own half-tone and bounce, so the spec values stay.
- **Turntable**: 5,600 K key 1.0 (45° camera-left, 30° up), fill 0.3, rim 0.5, an 18 % grey cove that turns with the camera, AgX look None, exposure 0, no DOF, haze or grade. Calibrated with `--calibrate`: an 18 % card at the chest reads 0.44 display, a 35 % card 0.57.
- **Passes**: `clay` (grey 0.5, roughness 0.55, normal maps off, alpha cut-outs kept) and `normal` (camera-space shading normal including normal maps, Standard view, 16 spp).
- **Cameras**: 24 mm vertical sensor fit, so `frame` is the frame height in metres at the aim point, and `shift` / `shift_y` are fractions of the frame height. Aim points are `eyes`, `head`, `chest`, `body`, `hands`, `hand_l`, `hand_r` and `cuff_feet`, posed.
  - DOF focuses on the near eye's cornea for head shots (eyeball centre + 12 mm toward the camera; Track A's diagnosis: the centre left the lashes 12 mm out of focus).
  - Hand shots focus on the hands or the cuff, not on the aim point below them.

## The hero stage

### Shot list (`shots.py`)

| Shot | Lens / framing | Pose | Light (on top of the hero rig and the set) |
|---|---|---|---|
| portrait (§5 #1) | 85 mm, f/2 on the near cornea, head and shoulders (0.42 m frame), ¾ (az 30), eyes on the upper third | stand (F `hero`), eyes to camera | base rig, rims 2.2 / 1.2, drizzle (700 streaks), haze 0.008, wet hair tips, 35 water beads per shoulder |
| sign (#2), 1152x2048 poster | 50 mm f/4, full body, camera at 1.1 m | stand (F `hero`: left hand at the jacket button) | magenta key 1.2 x 0.4 m above-right 1.3, teal across the street 0.5, sodium 2,000 K 0.3, heavy rain (2,200), puddles |
| profile (#3) | 100 mm f/2.8, bust profile | stand, head straight, chin 2–3° down | amber key 0.3, teal rim 2.5 from beyond the face, magenta kicker 0.35, wet tips, beads |
| draw (#4) | 35 mm f/5.6, full body, camera at 1.2 m, az 20 (Track H: at az 5 the gun reads as a dark square); 100 % crop on the hands on the gun | ready (bladed `high_ready`, holding H's pistol two-handed) | hard 4,300 K "headlight" 0.18 m source, low right, 1.0; magenta top 0.4 |
| hands (#5), 1152x2048 poster | 100 mm f/5.6 from 6 m, camera at 0.8 m: from the cuff to the floor, so the shoe and trouser break are in frame; focus on the cuff | cuff (F `hero` body, E's arms: the right hand pinches the left shirt cuff) | key 0.8 |
| eye (#6) | 135 mm at 0.73 m, f/8 focused 6 mm in front of the near cornea (about 14 mm in focus, from the far cornea to the brows), eyes and brow | stand, gaze 5° off camera | base (skin-direction) key, eye light 0.3 |
| bust | 50 mm f/2.8, ¾ | stand, eyes to camera | base rig + rims, wet tips, beads |
| back | 50 mm f/2.8, back ¾ (az 150): hair and suit back | stand | base rig + rims, wet tips, beads |
| walk | 35 mm f/5.6, ¾ full body (az −35) | walk (mid-stride) | base rig + rims, rain |
| turntable (#7) | 50 mm, 8 views at 45°, 1080x1620 | rest (A-pose) and stand | turntable rig; beauty + clay + normal |

The shot list follows direction §5, plus the brief's bust, back and walk shots. Deviations:
- **Under the sign** uses F's canonical `hero` pose, with the left hand at the jacket button (that is the "buttoning" read). Its weight is on the left leg, not §5's right.
- **Eye close-up**: shot from 0.73 m (a 0.13 m frame) instead of §5's 0.4 m. skin-direction.md's f/4 holds about 7 mm there, which left the brows and forehead soft once A's pores landed. It's now f/8 with the focal plane 6 mm in front of the near cornea (`fo=6` in the camera spec), which holds about 14 mm. Measured depths relative to the near cornea: far cornea −3 mm, brow ridge +19 mm, nose +34 mm. Both eyes and the brows are crisp and the nose stays soft (main7 eye A/B below).
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
- **Skin SSS (render side, reported)**: builds up to main3 shipped `skin_head` and `skin_hands` with Subsurface Weight 0. Since main4, Track A's hero skin carries its own SSS, so the stage adds none ("render-side SSS: none" on the sheet). Cycles has no other route to red bleed, so `stage.py --skin-sss auto` (the default) sets direction §2's values (Random Walk Skin, weight 1, radius (1, 0.25, 0.12), scale 2.5 mm, anisotropy 0.8), but **only when the build has none**. `stage.json` and the sheet header list the materials it touched. Once Track A ships its own SSS, the stage leaves it alone.
- **Grade** (`grade.py`, linear, before AgX Base Contrast; values from `skin-direction.md` where it sets them):
  - White point 3,900 K: ColorBalance in White Point mode, before the CDL. `--wb K`, 0 = off.
  - CDL power 1.08 for the contrast (+15 %), instead of the Medium High Contrast look, which flattened the skin's SSS.
  - Kuwahara painterly A/B: anisotropic, 5 px at 1080p, mix 0.6, **masked off the character** by IndexOB (§4: the face stays real).
  - Bloom: threshold 1.0, strength 0.35.
  - Red-orange halation: Fog Glow, threshold 2.0, strength 0.12.
  - 0.8 % lateral dispersion.
  - CDL: slope (1.04, 1.0, 0.94), offset (−0.0008, 0.0004, 0.0016), so shadows go teal and highlights amber.
  - Black lift 0.0011, saturation 0.97.
  - Vignette −0.3 EV (off on 100 % crops).
  - Grain 2 %, multiplicative.
  - Grading one image takes 0.2–0.8 s, so `hero.sh --regrade RUN` re-tunes the grade without re-rendering.

### Poses (`poses.py`) and Track F's runtime

- `stand` and `ready_low` are Track F's canonical `hero` and `low_ready` (`blender/character/deform_poses.POSES`). `ready` is F/G's `high_ready`, **bladed** by `poses.bladed()` (see below). `stand_profile` is F's `hero` with the head straight ahead and the chin 2–3° down. Every other deform_poses name works too, as does `f:<name>` for one shadowed by an E pose (`f:walk`).
- E's own solver poses stay available as `stand_e`, `ready_e`, `ready_low_e` and `walk`. F only has a walk as a deformation test pose, so the hero `walk` (¾ mid-stride, heel contact, push-off foot) is still E's.
- **Every pose runs F's deformation runtime afterwards** (`poses.deform`, called by `poses.apply`, which `rig.pose` and `stage.py` both use). It sets the helper bones (twist split, deltoid and hip helpers, jacket-skirt follow) and the corrective shape keys from the armature's `deform_rules` property, or from `character.rig.json` next to the .blend. Shape keys that are not correctives keep their values; the reference runtime zeroes every key it doesn't drive. Builds from before F merged carry no rules, and the pose log says "no rules (helpers at bind)".
- The log of each pose (source, active correctives with their weights) goes to `stage.json` / `rig.json`.
- `bench/m1/deform_hero.py` (Track F's wrapper) is now redundant: it applies the same runtime a second time, which is idempotent.
- **Bladed high-ready** (`poses.bladed`, applied to F/G's `high_ready` on the fly; deform_poses.py is untouched):
  - The torso turns 32° to the character's right, spread pelvis 18°, spine_01 4°, spine_02 4°, spine_03 6° (`BLADE`), so the gun-side shoulder is back and the support shoulder forward.
  - The neck and head take the turn back (45 % and 55 % + 4°), keeping the eyes on the target (−Y).
  - Stagger: the support (left) foot is 0.45 m forward of the gun-side foot (foot_l y −0.155, foot_r y +0.294), and both knees are soft (calf flex 20° / 12°).
  - The arms' IK offsets and poles and the hand orientations are chest-frame values, so they're turned back by the same 32° about the chest. G's grip geometry is preserved exactly: the same wrap log, with the gun hand on the sternum line in front of the face-target axis (hands at x ≈ 0, z 1.24–1.27).
  - Measured (run `20261013T030500Z-readyx2`): chest yaw 31.9°, pelvis 18°, head 4.5° off the target line, and `hand_pose.pierce` 0 overlaps for both hands.
- **Track G's hand settle** (`hand_pose.settle`) runs at the end of every pose through `poses._hands`, keyed by the stage name, its F pose and `HAND_FALLBACK`. That covers the stage-only poses: `walk` and `stand_profile` settle with G's `hero` entry, and E's solver poses likewise. `stand_profile` had a 25-triangle right-palm overlap without it, and the cleared hand moved 3.9 mm.
- **Walk arm swing fixed**: the left arm used to swing forward with the left leg, and the wrists brushed the hips (palm overlaps). Now each arm swings against its leg (−0.18 / +0.16 m), with wrists 6 cm outside the shoulder line, and the overlaps are 0.
- `ready_low` (F's `low_ready`, used by no shot) still overlaps: l palm 250 and thumb 97, r palm 96 triangles. Its IK targets put the two wrists 3 cm apart, and G has no settle entry for it (the high_ready wrap doesn't clear it). That's for F/G if the pose is wanted.
- What broke with E's solver poses on the pre-F build (main2): in `ready`, the hands interpenetrate (a support hand wrapped around a closed hand needs contact, which pose data alone doesn't give), and the hands read as mittens or claws in every pose.

## Runs (evidence)

All under `data/build/hero/` in the main checkout. Builds come from `data/build/lookdev/`.

| Run | Build | What changed / what it showed |
|---|---|---|
| `20261012T192008Z-it1` … `20261012T194137Z-it4` | pre-forms main | first set and rig passes: haze too thick (0.03 /m), flat brick behind portrait/profile (→ the set turns), cheat key washing the walls (→ flags), spill and far-end glow too strong, wall words facing the wall |
| `20261012T200818Z-main2-preview` | `20261012T194340Z-heroE-main2` (main + track A forms freeze) | all nine shots + rest turntable (interrupted at tt135 by the load cap); `sheet.png` |
| `20261012T203233Z-main2-flags` | same | light-linked key/fill/eye; portrait, sign, draw, profile |
| `20261012T204204Z-main2-final-timing` | same | final portrait at `-t 3`: stopped after 35 min with the shot unfinished (to free the one Blender slot for the track F integration) |
| `20261012T212025Z-main3-F` | `20261012T211741Z-heroE-main3` (main ff03f62, track F merged) | F's poses + runtime: portrait, draw, profile, hands, walk, stand turntable tt0/tt90 (beauty, clay, normal); `sheet.png` |
| `20261012T213139Z-main3-final-portrait` | same | final portrait (768 / 0.012) at `-t 3`: stopped unfinished after 57 min |
| `20261012T224500Z-main4-check` | `20261012T222907Z-heroE-main4` (main with B's strand groom, C, D v2, A's hero eyes) | first wet look (beads, wet strand tips, eyes to camera incl. the hero cornea), cuff pose, eye cam at 0.4 m, 100 % crops; `portrait_wb4200.png`: a global 4,200 K white point fixed the shirt but turned the whole alley blue |
| `20261012T231000Z-main4-k4300` | same | key-warmth tests (4,300 / 5,000 K) and the grade A/Bs (`*_lookNone`, `*_plain`, `*_base`, `*_sat85`, `*_base85`); turntable tt0 as the skin reference |
| `20261012T232500Z-ftime` | same | the final-vs-preview cost on the portrait's face region (see the final timing above) |
| `20261012T233000Z-lightx` | same | the orange face isn't the set: the void set is as orange as the alley |
| `20261012T233130Z-main4-sheet` | same | full preview sheet under the 5,000 K + 0.85-saturation grade (superseded) |
| `20261013T000810Z-main5-skinrig` | **`20261013T000424Z-heroE-main5` (main ede62d6: A's skin pass, C round 3)** | the skin-direction rig: portrait at 100 % |
| `20261013T001800Z-main5-ttbust` | same | turntable bust at 100 % (85 mm, az 30 and 0) |
| `20261013T002500Z-shadowx` | same | shadow-cheek breakdown (each light group removed; fill / eye / wrap variants) |
| **`20261013T002954Z-main5-sheet`** | same | **the full preview set under the skin-direction rig: 9 shots, 100 % crops of portrait / profile / hands / eye, turntable rest + stand at 4 views (beauty, clay, normal); `sheet.png`** |
| `20261013T010935Z-main5-amber` | same | warmer set-only amber practicals vs the 3,900 K white point: sign, draw, back, walk |
| `20261013T030500Z-readyx2`, `20261013T030500Z-readyx3` | **`20261013T025642Z-heroE-main6` (main 9ac04e9: G's hands, D suit round 3)** | bladed ready / walk / stand_profile / ready_low: `hand_pose.pierce`, chest, pelvis and head yaw, feet, hands (`readyx.json`) |
| `20261013T030716Z-main6-draft` | same | the 9-shot draft sheet (16 spp, 25 %, 1.9 min at `-t 3`) |
| **`20261013T031023Z-main6-draft50`** | same | **the same at 50 % plus 100 % crops of portrait / profile / hands / eye (10.1 min): the regression check** |
| `20261013T033000Z-main6-hands` | same | G's `hands_render.py --pierce`: ready, ready_side, cuff, hero_r; pierce 0 / 0 in ready, cuff and stand |
| `20261013T061348Z-main7-before` | **`20261013T060824Z-heroE-main7` (main c672cab: A's pores and micro bump)** | portrait + eye at preview with 100 % crops, before the eye and fill tests |
| `20261013T063000Z-main7-var`, `20261013T070500Z-main7-var2` | same | 100 % crops at preview: eye f/5.6 fo6, f/8 fo6, f/8 fo9, f/11 fo8; portrait without wrap, without fill, wrap 0.5 m, wrap raised to 45°/35°, without key, without eye light |
| `20261013T081402Z-main9-draft`, `20261013T081540Z-main8-draft-base` | `20261013T081002Z-heroE-main9` (main 61726e1: C 5b dense beard), and main8 | draft sanity before the final, with C 5b against main8: time per shot +0–5 %, peak RSS 4.63 vs 4.31 GB |
| `20261013T090051Z-main9-draw-draft` | main9 build, code at 4b2e49a (H's pistol) | draw at az 20 with the pistol, and the hands-on-gun crop |
| **`20261013T081828Z-main9-final`** | **main9 build; draw with H's pistol (4b2e49a)** | **THE FINAL REVIEW SET: 9 shots at 256 spp / 100 %, painterly variants, 100 % crops (portrait, eye, profile, hands, draw), turntable rest + stand × 8 views × beauty / clay / normal; `sheet.png`** |
| **`20261013T070829Z-main7-after`** | same | **eye at f/8 fo6, preview with its 100 % crop; `eye_before_after.png` (the portrait is unchanged: see before)** |

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

Main5 build (strand grooms, hero eyes, A's skin) at `-t 3`: portrait 124–176 s, sign 160, profile 143, draw 115, hands 104–132, eye 262–311, bust 104, back 105, walk 113. The full portrait at 100 % with preview samples took 540 s, and a 100 % half-frame crop 180–260 s.

### Final timing and projection

- The final could not be run to completion on this machine under the load cap:
  - The final portrait (768 spp / 0.012) at `-t 3` was stopped unfinished twice: after 35 min (main2) and after 57 min (main3), each time to free the one Blender slot for coordinator work.
- **Measurement**: the portrait's face region (a 1/16-area border crop at 100 %, `data/build/hero/20261012T232500Z-ftime`, main4) took 28.2 s at preview and 838 s at 768 / 0.012.
  - The full preview frame took 176 s. That fits a fixed per-render cost of about 18 s plus 16 regions.
  - So the full 768 / 0.012 frame ≈ 18 + 16 × (838 − 18) ≈ 13,100 s ≈ **3.6 h at `-t 3`** on the loaded machine, about 75× its preview time. The face region holds the strands, SSS and DOF, so the whole frame may average a little cheaper.
- **Projection to 16 threads, otherwise idle**: the machine is a Ryzen 7 7700 (8 cores, 16 threads), and I assume 3–4× the throughput of `-t 3` under load.
  - At 768 / 0.012 a shot costs about 19–25× its `-t 3` preview time: the portrait about 45–65 min, the 9 shots about 7–9 h (their previews add up to about 1,250 s), and the turntable (8 views × 2 poses, beauty + clay, about 720 s of preview) about 4–5 h more. **That doesn't fit one night.**
  - So `--final` is now **256 spp / adaptive 0.02** (OIDN), and `--max` keeps 768 / 0.012 for single hero frames. Unmeasured estimate: roughly a third of the 768 cost, so about 7× the `-t 3` preview time per shot. That is about 15–20 min for the portrait, about 2.5 h for the 9 shots and about 1.5 h for the turntable: **about 4 h for the full final set at 16 threads**.
  - The first scheduled final run's `stage.json` will give the real per-shot seconds.
  - If the night is short, use `--tt-views tt0,tt90,tt180,tt270` (half the turntable), or render the turntable at `--preview --pct 100`.

### The final set (measured): `data/build/hero/20261013T081828Z-main9-final`

Three passes into one run dir (`hero.sh --into`):
1. The eight shots with crops at `-t 12` (5,145 s wall), while Track H held 3 cores.
2. draw with its crop at `-t 16` (467 s), after H's pistol merged.
3. The turntable at `-t 16` (1,239 s).

The build is `20261013T081002Z-heroE-main9` (main 61726e1, C 5b). The pistol is spawned at pose time from `blender/props` (H, 4b2e49a), so it needed no rebuild. Ryzen 7 7700, 62 GB RAM, otherwise mostly idle.

| Render | Resolution | spp | Seconds | Peak RSS (GB) |
|---|---|---|---|---|
| portrait | 1920x1080 @ 100 % | 256 | 545 | 6.9 |
| portrait_crop | 960x540 (100 % crop) | 256 | 209 | 7.0 |
| eye | 1920x1080 @ 100 % | 256 | 1128 | 11.6 |
| eye_crop | 960x540 (100 % crop) | 256 | 333 | 11.8 |
| profile | 1920x1080 @ 100 % | 256 | 519 | 11.8 |
| profile_crop | 960x540 (100 % crop) | 256 | 162 | 11.8 |
| bust | 1920x1080 @ 100 % | 256 | 399 | 11.8 |
| back | 1920x1080 @ 100 % | 256 | 417 | 11.8 |
| sign | 1152x2048 @ 100 % | 256 | 545 | 11.8 |
| walk | 1920x1080 @ 100 % | 256 | 420 | 11.8 |
| hands | 1152x2048 @ 100 % | 256 | 341 | 11.8 |
| hands_crop | 576x1024 (100 % crop) | 256 | 74 | 11.8 |
| draw | 1920x1080 @ 100 % | 256 | 364 | 6.5 |
| draw_crop | 576x324 (100 % crop) | 256 | 34 | 6.5 |
| turntable beauty (16 views) | 1080x1620 | 256 | 586 (33–41 each) | 5.3 |
| turntable clay (16 views) | 1080x1620 | 256 | 491 (28–34 each) | 5.3 |
| turntable normal (16 views) | 1080x1620 | 16 | 117 (7–8 each) | 5.3 |
| **total render** | | | **6682** (1.86 h) | **11.8** |

- Peak RSS is the Blender process's running maximum (`resource.ru_maxrss`), so a row is the peak up to and including that render.
  - The eye frame (135 mm at f/8 through the dense beard and the strand groom) raised it from 7 to 11.6 GB.
  - draw and the turntable ran in fresh processes (6.5 and 5.3 GB).
  - That leaves ample room on 62 GB. C 5b's denser grooms added +0.3 GB and +0–5 % time at draft.
- **Total render time is 1.86 h** (1.9 h wall, about 6 minutes of it setup, grading and sheets), against the projected about 4 h at 16 threads.
  - 256 spp with adaptive 0.02 converges well below its cap, and per-shot cost is about 6–9 min at 12 threads; the eye is the outlier at 19 min.
  - The turntable is about 75 s per view for all three passes.

## v3 prep (main bc983b6)

**Fan builds render privately.** See bench/m1/v3/BRIEF.md.
- `bench/m1/lookdev.sh --fan FILE` (or `$FAN_CONFIG`) passes `--fan` to the build and puts the run under `<main>/private/likeness/lookdev/`.
- `bench/m1/hero.sh` puts a fan build's runs under `<main>/private/likeness/hero/`. It detects a fan build from:
  - a `"fan"` block in the build's `character.stats.json` config,
  - an input under `private/`,
  - `$FAN_CONFIG`, or `--fan`.
- With `--into`, it refuses to write a fan render outside `private/`. The public flow is unchanged.
- Tested at draft quality with A's test face delta plus B's hanging-groom hair overlay, merged into one private test config. The build and every render landed under `private/`, and nothing was added under `data/`.

**Hair rim** (`rig.HAIR_RIM`, on by default; `hero.sh --no-hair-rim` turns it off). Track B found that the shadow-side magenta in the hair is the magenta rim mirrored in the wet coat specular.
- Every magenta rim or kicker is now split by Cycles light linking:
  - The original lights everything except the head hair (`hair_*` objects, excluded through its receiver collection).
  - A twin at the same place lights only the hair. Its colour is pulled toward white-violet (0.85, 0.80, 1.0) until it has 40 % of the original saturation, with its power scaled to keep the luminance.
  - For the sets' magenta (1.0, 0.06, 0.42) the twin is a light pink-violet.
- Teal rims, face, suit and set are untouched.
- Measured on the 50 % drafts (mean of a region, HSV saturation):

| Region | before | after |
|---|---|---|
| portrait, shadow-side hair (public build main10) | 0.61 (27, 10, 23) | 0.36 (17, 14, 22) |
| portrait, shadow-side hair (fan test build) | 0.63 | 0.33, same luminance |
| portrait, cheek rim (public) | 0.47 | 0.46 |
| portrait, suit shoulder rim (public) | 0.40 | 0.39 |

- The hair still takes the rim shape and the wet highlight, now violet-grey instead of magenta.
- **Generalised (main a18c362)**: every saturated rim or kicker now gets a hair twin, not only the magenta ones. The test is HSV saturation above `HAIR_RIM_MIN_SAT` = 0.3; Kelvin lights are excluded.
  - Magenta still goes toward white-violet. Other hues go toward white, keeping their own hue.
  - This removes the teal kicker's sheen on the part. On the fan build's 100 % portrait crop, against Track B's `hairB-fan2` (before → after):
    - Part sheen saturation: 0.75 → 0.39.
    - Teal-side hair: 0.46 → 0.17.
    - Teal cheek rim: 0.15 → 0.15. Magenta-side hair: 0.37 → 0.37.
  - Verified on a private fan-build run (not committed).
- In back, the teal kicker dominates the hair once the magenta is gone.
- Public evidence: `data/build/hero/20261013T125442Z-main10-rim-before50` and `20261013T125649Z-main10-rim-after50` (`rim_before_after.png`: portrait, profile and back).

**Profile with the hanging groom (fan test build)**: the eye still reads at az 90.
- The near rope falls behind the eye, across the temple and the cheek.
- I tested az 90, 80, 72, and 80 with el 6, as 100 % crops (private run `fan-profile-var`).
  - Turning toward the front (az 72, or el 6) brings a rope across the eye.
  - az 80 is as clear as 90.
- So the profile camera stays at az 90, with az 85 as a fallback if the final groom moves.

## v3 rig fixes from the fan preview (main cbd0c4c)

Three defects from the fan preview review came from the lights, not the character. Each was diagnosed by dropping one light at a time (64 spp crops, same build), then fixed and checked against the preview. Values are region means of the graded 8-bit image (R G B, HSV saturation).

**Twins generalised** (`rig._split`, `rig.TWIN_GROUPS`). The hair rim's light-linking split now takes several groups per light:
- The original lights everything except the twinned objects.
- Each group gets its own twin at the same place, desaturated to its fraction of the original saturation at the same luminance, times an energy factor.
- The groups:
  - **hair**: every saturated rim or kicker, as before (`HAIR_RIM`, 40 %). Unchanged.
  - **props**: every saturated hero light, at `PROP_SAT` = 15 %.
  - **cloth** (the suit, not the shirt) and **skin** (the body mesh and vellus): opt-in per shot through the spec's `twin` key, `{group: (fraction, energy)}` or `{group: {light: (fraction, energy)}}`.

**Pistol (draw).**
- The plum slide is the default magenta rim. Without it the slide is (8, 8, 12); dropping the magenta top or the teal kicker changes nothing.
- A metal slide is nearly all specular, so it takes the rim's colour outright.
- With the props twin, the slide goes from (41, 25, 50) to (22, 30, 46), dark gunmetal. The grade's cool white point keeps the HSV saturation around 0.5 in the near-black.
- The hand on the grip is unchanged at (41, 34, 39).

**Profile.**
- At az 140 the teal rim reached the forward-facing cheek plane through the gap under the hair lock. It blew out to a pale blob below the eye, (77, 81, 89).
- At az 160 it grazes only the nose, brow and beard edge. Halving the rim at az 140 only dimmed the blob.
- A skin twin (70 %, 0.8 energy) softens the brow ridge: saturation 0.33 → 0.25. The nose edge goes 0.25 → 0.23 at the same brightness.
- **Left:** a faint pink tint under the eye, (79, 48, 52), which the blob used to cover. It is the set's magenta neon spill through the same hair gap:
  - With the neon off it turns warm, (71, 45, 43).
  - Neither a kicker skin twin nor moving the kicker to −155° changes it.
  - Track B's re-grooming of that lock should close the gap. Otherwise the shot's `neon` can be dimmed.

**Back.**
- The jacket's plum edge is the magenta rim, and the elbow glint is the teal kicker; I confirmed both by dropping each light.
- A cloth twin of both (30 %, 0.75 energy):
  - Jacket edge: (45, 30, 54) → (29, 32, 46).
  - Elbow glint: (2, 27, 39), saturation 0.93 → (10, 22, 34), saturation 0.69, now a dim grey-blue.
  - Back centre: unchanged, (10, 13, 21) → (9, 13, 20).
- The hair keeps its own twin.

Not done here: cloth twins for the bust and walk shots (their far shoulder also takes the magenta rim), and set-light twins.

## What the stage shows about the character (main ede62d6, run main5-sheet)

For the owning tracks. The stage doesn't fix any of these.

- **A (skin, eyes)**: the skin is warm-neutral under the skin-direction rig.
  - It still reads as one continuous sheen with no mid-frequency relief: Track A's next pass, per skin-direction.md.
  - The hero eyes (refractive cornea, meniscus, caruncle) read well in the 100 % eye crop.
  - Earlier the face went orange-tan. That was the 3,000 K key under a 6,500 K white plus the Medium High Contrast look (HSV saturation 0.66–0.78 against the turntable's 0.30–0.39), not the albedo. The new rig and grade fix it.
- **B (hair)**: the strand groom reads as hair: fine strands at the silhouette, and the wet tips catch the rims. It takes the magenta rim strongly, and in the portrait the hair reads magenta on the rim side. That's a rim-strength question for E if the review wants it calmer.
- **C (beard, brows, lashes)**: the strand beard has a soft edge now. Round 3 brows and lashes look fine at 100 %.
- **D (suit)**:
  - Shoulders are still boxy, and the lapel rolls catch the rim as hard edges.
  - The trousers are clean tubes.
  - Earlier builds had a sawtooth black edge on the shirt cuff (main3).
- **F (deformation)**: the runtime runs on every pose; the portrait's log shows `corr_arm_down_l 0.58, corr_arm_down_r 0.80, corr_elbow_l 0.33, …`.
  - In the cuff pose (hands, hands_crop) a black shard shows on the right hand's knuckles: mesh interpenetration in the closed fingers.
  - The hands still read as mittens.
  - In `high_ready` the hands sit high and the stance is square.

## Regression check on main 9ac04e9 (G's hands, D's suit round 3; run main6-draft50)

Every shot was compared against main5-sheet. No regressions from the merge:
- **portrait, eye, profile**: unchanged. The near-cornea focus and the eyes on the upper third hold.
- **hands**: the black shard on the right knuckles is gone (G's settle). The right hand lies over the left wrist and cuff (the left cuff peeks out under its little finger), and the left hand is relaxed and curled. The fingers now read as fingers, not mittens. 0 overlaps.
- **draw**: the bladed stance reads (support shoulder and foot forward, compact grip at the chest, eyes on target). Close up (`main6-hands/hero_ready_side.png`), the right shirt cuff folds into a jagged white zigzag at the wrist. It was already present in G's square high_ready (`trackG/ready2`), and the bladed forearm's larger twist makes it a bit sharper. It's for D/G and is invisible at the draw shot's scale.
- **sign, bust, back**: the hands in the `hero` pose (left at the jacket button, right hanging) are clean. The suit's round-3 collar and waistcoat edges read smoothly, and nothing pokes through.
- **walk**: the arm swing is now opposite the legs, with no hand/hip contact.
- Still open (from main5, not regressions): A's skin relief, D's boxy shoulders and the hard lapel-roll highlights.

## Render visibility (C round 5, main 3efcf05)

The stage never un-hides geometry. Its character set (`rig._character_from_scene`) skips every object with `hide_render`. The only visibility it ever writes is `hide_render = True` (stray import helpers, and the alley during the turntable, restored after). Light linking uses that set, so hidden meshes are never receivers either.

Checked on `20261013T071846Z-heroE-main8`:
- The .blend hides `Human.beard_export`, `brows_export`, `eyelash_cards_export`, `eyes_hq_export` and `hair_export`.
- None of them is in the character set, none is visible after pose plus rig, and none is a light-link receiver.
- In `20261013T072432Z-main8-check` (`portrait_main7_vs_main8.png`), the black beard spatter is gone. Every hero render before main8 (main2 to main7) also drew the game shells over the strands.

## Eye focus and portrait fill on main c672cab (A's pores)

**Eye: changed to f/8, focus 6 mm in front of the cornea.** Sharpness is the Laplacian std (×1000) of the graded 100 % crop per region. The 2 % grain sets a floor of about 25 on flat skin.

| Variant | near eye | near brow | far eye | far brow | forehead | nose |
|---|---|---|---|---|---|---|
| f/4 on the cornea (before) | 59.0 | 78.7 | 104.0 | 89.4 | 25.4 | 25.3 |
| f/5.6, fo 6 | 44.4 | 87.5 | 81.3 | 106.3 | 26.4 | 27.7 |
| **f/8, fo 6 (kept)** | **59.6** | **96.7** | **100.5** | **118.3** | 26.5 | 29.0 |
| f/8, fo 9 | 47.1 | 90.0 | 76.9 | 113.4 | 26.8 | 30.3 |
| f/11, fo 8 | 60.6 | 100.3 | 98.3 | 123.7 | 26.8 | 30.2 |

- f/8 fo6 keeps both corneas as sharp as before and the brows gain 23–32 %. Brow hairs read as single hairs, and the lit temple shows A's pore stipple.
- The glabella and nose (19–34 mm in front) stay soft, which is the intended gentle falloff.
- f/11 is only marginally crisper and outside the requested range. Moving the focus further forward (fo 9) or opening up (f/5.6) softens the corneas.

**Portrait: no change kept.** The nose-ridge highlight is not the fill's reflection:
- Removing the wrap (A's "large fill", 1.5 m at 35°/10°) or the fill (2 m at −55°), shrinking the wrap to 0.5 m, or raising it to 45°/35° all leave the streak. Nose and forehead sharpness stays within ±1.5 of before.
- Removing the key leaves a blue streak from the fill and wrap instead. A narrow ridge draws a line highlight from every source.
- What hides the pore breakup on the nose is scale:
  - At the portrait's framing (0.42 m frame) a 100 % pixel is 0.39 mm, so pores (0.1–0.3 mm) are sub-pixel.
  - The nose is about 30 mm in front of the f/2 focal plane, so it's blurred by about 2 px.
- Pore stipple can show only in the eye shot (0.12 mm/px), where it now does on the lit temple.

## Verdicts

- **Shared rig + turntable**: done.
  - The hero rig is now skin-direction.md's: small short key, wrap, grazing rim, hard eye light.
  - Exposure is measured: lit cheek 0.51–0.52, shadow core 0.15–0.19. The coordinator accepted it.
- **Alley set, haze, rain, signs**: done.
  - Neon behind faces is dimmed per shot (`neon`).
  - The 3,900 K white point turned the alley teal and blue (main5-sheet). The set-only amber practicals are now pushed to compensate: amber neon (1.0, 0.30, 0.015), amber signs, bulkhead and sodium ×1.6 (`sets.AMBER_GAIN`), bulkhead 1,900 K, the near street lamp 4,500 → 3,200 K. The magenta / teal / amber triad is back (`20261013T010935Z-main5-amber`). Character light and white point are unchanged.
  - Limits: no rain motion blur, and the alley's far end is a flat emissive plane.
- **Wet look**: done, render side: shoulder beads, wet strand tips, eyes to camera.
- **Eye shot**: f/8 with split focus (cornea to brows); A's pores read at 100 %. **Portrait**: unchanged (the fill isn't the nose streak, and pores are sub-pixel at its scale).
- **Grade**: done (white point, CDL power, saturation 0.97). The painterly A/B stays masked off the character (§4).
- **Shot list**: all of §5 is covered, with deviations:
  - The eye close-up is shot from 0.73 m, not 0.4 m.
  - Under the sign uses F's `hero` (left hand at the button), so his weight is on the left.
  - The brief's bust, back and walk shots are added.
- **Poses**: F's canonical poses plus the runtime and G's hand settle in every render, and the bladed high-ready (`ready`) for the draw. E's walk (arm swing fixed) and cuff arms. 0 hand overlaps in every pose a shot uses.
- **Evidence tooling**: `--crop` (100 % crops), `--pct`, `--wb`, `--regrade`. hero.sh always grades and draws the sheet, even after a failed stage.
- **Final**: done. `data/build/hero/20261013T081828Z-main9-final/sheet.png` holds all 9 shots, the crops, the painterly variants and the 48-image turntable. It took 1.86 h of render at 256 spp / 0.02, with peak RSS 11.8 GB. `--max` = 768 / 0.012 stays available for single hero frames.

## Branch and commits

`worktree-agent-a6abc868df2544cd8`, rebased on main a18c362. Rig and stage code merged by the coordinator through 457d552. This report is the last commit.
