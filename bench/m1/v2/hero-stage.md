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
| portrait (§5 #1) | 85 mm, f/2 on the near eye, head and shoulders, ¾ (az 30), face on the right third | stand | base rig, rims 2.2 / 1.2, drizzle (700 streaks), haze 0.008 |
| sign (#2), 1152x2048 poster | 50 mm f/4, full body, camera at 1.1 m | stand | magenta key 1.2 x 0.4 m above-right 1.3, teal across the street 0.5, sodium 2,000 K 0.3, heavy rain (2,200), puddles |
| profile (#3) | 100 mm f/2.8, bust profile | stand, head straight, chin 3° down | amber key 0.3, teal rim 2.5 from beyond the face, magenta kicker 0.35 |
| draw (#4) | 35 mm f/5.6, ¾ full body, camera at 1.2 m | ready (compressed high-ready, empty hands) | hard 4,300 K "headlight" 0.18 m source, low right, 1.0; magenta top 0.4 |
| hands (#5) | 100 mm f/4 on the left hand and cuff | stand | key 0.8 |
| eye (#6) | 135 mm f/2.8, eyes and brow | stand | soft key 1.2 m, eye light 0.3 |
| bust | 50 mm f/2.8, ¾ | stand | base rig + rims |
| back | 50 mm f/2.8, back ¾ (az 150): hair and suit back | stand | base rig + rims |
| walk | 35 mm f/5.6, ¾ full body (az −35) | walk (mid-stride) | base rig + rims, rain |
| turntable (#7) | 50 mm, 8 views at 45°, 1080x1620 | rest (A-pose) and stand | turntable rig; beauty + clay + normal |

The shot list follows direction §5, with two substitutions: no "buttoning the jacket" or "adjusting the cuff" pose (I didn't attempt those hand-on-garment poses before Track F's correctives land), and the brief's bust, back and walk shots added.

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
