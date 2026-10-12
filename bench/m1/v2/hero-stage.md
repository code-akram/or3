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
