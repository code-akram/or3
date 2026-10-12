# m1 look-dev harness

One command builds the character, renders the fixed look-dev views and silhouette masks, scores them and draws a contact sheet. It is the inner loop for the m1 tracks (head, suit, hair, deformation): make an edit, run, compare, keep or revert. See NOTES.md §7.

## Run

```sh
bench/m1/lookdev.sh <label>                          # loop: EEVEE (iGPU) 512², 16 samples
bench/m1/lookdev.sh --config cand.json <label>       # a candidate: JSON override of the build config
bench/m1/lookdev.sh --target DIR <label>             # also score against DIR/<view>_mask.png
bench/m1/lookdev.sh --prev <run>|none <label>        # score against a chosen run (default: latest)
bench/m1/lookdev.sh --signoff <label>                # Cycles CPU 1024², 128 spp + OIDN HIGH, 16 threads
bench/m1/lookdev.sh --compare <runA> <runB>          # side-by-side sheet + metrics diff
```

- Runs land in `data/build/lookdev/<UTC timestamp>-<label>/` in the **main checkout** (gitignored); `latest` links to the newest run. Override with `DATA=`.
- `THREADS` sets Blender's `-t` (default 4 for the loop, 16 for sign-off). The loop renders on the iGPU, so it barely competes with CPU jobs.
- `KEEP_BLEND=1` keeps the staged `.blend` (deleted by default; the GLB is what gets rendered).
- Labels: letters, digits, `. _ -`.

### Build config

`blender/build_character.py` drives the stage modules in `blender/character/` from one config: defaults in `blender/character/config.py`, deep-merged with the `--config` JSON. Each section belongs to one module, so tracks can work in parallel without touching each other's files:

| Section | Module | Stage hooks |
|---|---|---|
| `body` (macros, race, skin, `targets`) | `body.py` | `create` |
| `head` (face parts, cut-outs, `targets`, `edits`, `planes`) | `head.py` (+ `head_shape.py`, `head_measure.py`) | `edit_base` (base mesh, before fitting), `add_parts` (then measures the spec landmarks on the still-nude human), `post` |
| `hair` | `hair.py` | `add`, `post` |
| `suit` (clothes list) | `suit.py` | `add`, `post` |
| `rig` (builtin, `helpers`) | `rig.py` | `add`, `post` |
| `budgets.decimate` (`{name part: max tris}`) | `budgets.py` | `apply` |
| `export` | `export.py` | staging, target bake, alpha fix, GLB |

The stage order is listed in `blender/character/__init__.py`. `post` hooks run on the staged export meshes after the macro targets are baked. In an override, `null` disables a default dict entry. The m1 defaults carry the tuned proportions (`body.macros.height` 0.607 and three `body.targets`, see `head.md`) and the 480-tri teeth budget. Reverting them gives the earlier GLBs byte for byte, e.g. the spike-1 GLB:

```json
{"body": {"macros": {"height": 0.6}, "targets": {"measure-shoulder-dist-incr": null, "torso-vshape-incr": null, "hip-scale-horiz-decr": null}},
 "budgets": {"decimate": {"teeth": null}}}
```

**Head and body controls** (look-spec §1–2; details and the variant configs in [`head.md`](head.md)):
- `body.targets` / `head.targets`: MPFB detail targets `{file stem: weight}`, e.g. `"measure-shoulder-dist-incr": 0.12`. `"lr-<stem>"` loads the mirrored `l-`/`r-` pair.
- `head.edits`: the 17 look-spec §2.3 controls, each in [−1, 1] (`head_shape.CONTROLS`).
- `head.planes`: planarisation blend 0..1 per plane group (`head_shape.PLANES`); `brow_flatten`, `dorsum_crease` and `cheek_plane_break` drive their groups too.
- Face variants for the direction checkpoint: `bench/m1/variants/face-{a,b,c}.json`.

Example candidate:

```json
{"body": {"macros": {"muscle": 0.8, "height": 0.7}}}
```

## Outputs (per run)

| File | What |
|---|---|
| `character.glb`, `character.stats.json` | the build, per-stage timings, per-mesh stats, the full resolved config |
| `glbstats.json` | Khronos glTF-Validator result + per-mesh weights-per-vertex histogram |
| `<view>.png` | beauty frame: `front`, `three_quarter` (40°), `profile` (90°, character's left), `closeup` (25°, head) |
| `<view>_mask.png` | silhouette, white = character |
| `face_front_mask.png`, `face_profile_mask.png` | head silhouette with only the body and eyes shown (hair, clothes and face cards hidden), orthographic, 0.42 m frame; long hair hides head edits from `closeup`, these don't |
| `face_strip.png`, `face/` | hair-hidden face strip (body, eyes, brows, lashes, mouth parts): front, ¾ key side (−35°), ¾ shadow side (+35°), profile (−90°), 320² each; row 1 full studio, row 2 key only, optional row 3 key only with the body shaded smooth-by-angle (`--facet DEG` on `lookdev_render.py`, a planarity test that doesn't ship) |
| `detail_strip.png`, `detail/` | fidelity close-ups, everything shown, studio light, 384² each: left eye, nose in profile, mouth, back and palm of the left hand (face-C fidelity track, `head.md` §8) |
| `skin_*.png`, `eyes_*.png` | the generated skin and eye maps (albedo, ORM, normal) when `head.refine.skin.save_maps` is on; the same images are packed into the GLB |
| `read40.png` | the 40 px read test image (48 px, upscaled ×4) with its sample boxes: eye band red, cheek cyan, beard yellow |
| `render_metrics.json` | raw metrics from the render pass |
| `metrics.json` | the merged record (below) |
| `sheet.png` | contact sheet: header with key metrics, beauty row, masks row |
| `build.log`, `render.log` | Blender logs |

`--compare` writes `data/build/lookdev/compare-<A>--<B>/`: `compare.md` (changed metrics only), `compare.json` (all numeric metrics, A, B, delta, plus both configs) and `sheet.png` (both sheets stacked, then a mask overlay per view: white = both, **red = only A**, **cyan = only B**).

### Cameras and lighting

- **Body views use fixed world-space cameras** (target 0.98 m above the floor, 2.15 m frame height). Proportion changes therefore show up in the picture instead of being reframed away. The close-up tracks the `head` bone (0.42 m frame), so it shows the face whatever the height.
- **Masks use orthographic cameras** along the same axis, 512², with a fixed metric size per pixel (2.15 m / 512 = 4.2 mm for body views, 0.82 mm for the close-up). That makes IoU and silhouette widths comparable between runs. They are rendered with EEVEE at 1 sample, film transparent, floor hidden. Hair cut-outs (MASK) are respected.
- Studio: spike-2 rig at fixed positions (key front-left-high 900 W, fill front-right 250 W, rim behind 700 W, area lights, near-black world, dark floor).
- **Exposure** (2026-10-12): AgX, look None, **−2.5 EV** (`STUDIO_EXPOSURE`; `LOOKDEV_EXPOSURE` overrides). Calibrated with `lookdev_render.py --calibrate`, which renders Lambertian cards at face and chest height and writes `calibration.json`. At −2.5 EV the full rig gives: 3 % black wool 0.18 display, 18 % grey 0.47, 30 % skin-mid 0.58, 80 % white shirt 0.74 (no clipping). Before, at 0 EV, the same cards read 0.47 / 0.78 / 0.84 / 0.92, so black cloth rendered mid-grey.
- **Look-dev skin** (`--skin lookdev`, default; render-side only, the GLB keeps the MPFB material): the body texture desaturated (0.55) and darkened (0.88), multiplied by low-frequency value noise (0.86–1.06), roughness 0.62, specular 0.35. `--skin asset` renders the shipped material.

### Face variants: distinctness guard

`python3 -I bench/m1/face_distinct.py --stock RUN --variant a=RUN --variant b=RUN --variant c=RUN --out DIR` scores the hair-hidden face masks: every variant must be at IoU ≤ 0.95 against the stock head and ≤ 0.97 against every other variant, in both `face_front` and `face_profile`. Writes `distinct.json` and `faces.png` (the face strips stacked, labelled). Exit 1 on a failed guard.

### Failing fast

Blender exits 0 on a Python error, so both Blender calls run with `--python-exit-code 1`, and the script also checks that `character.glb` and `render_metrics.json` exist before going on.

## Metrics (`metrics.json`)

| Key | Definition |
|---|---|
| `tris.total`, `tris.parts.<part>` | evaluated triangles per imported GLB mesh (`body`, `long01`, `toigo_male_suit_tie_and_jacket`, `teeth_base`, ...) |
| `bones` | joints in the GLB skeleton |
| `max_weights_per_vertex` | max non-zero weights on any vertex in the GLB (from the validator pass) |
| `gltf_validator.errors/warnings` | Khronos glTF-Validator counts (9 known `NODE_SKINNED_MESH_NON_ROOT` warnings) |
| `landmarks.<name>` | **the look-spec §1.1 landmarks** (the m1 contract), measured in the build on the live, still-nude MPFB human after the face parts are fitted (`blender/character/head_measure.py`): `stature`, `head_height`, `heads_tall`, `bideltoid`, `hip_breadth`, `shoulder_to_hip`, `crotch_height`, `leg_ratio`, `leg_to_torso`, `bizygomatic`, `bigonial`, `jaw_to_cheek`, `lower_face_index`, plus `brow_overhang` (mean of both sides: most forward brow point on the mid-pupil vertical, 8–40 mm above the eye centre, minus the cornea front), `menton_z`, `eye_height`, `interpupillary` |
| `spec_checks.<name>` | `{value, target, tol, ok}` against look-spec §1.2 (`brow_overhang`: ≥ 12 mm). The sheet header shows them, `+` = within tolerance, `!` = out |
| `read40` | look-spec §2.2 read test: a ¾ render from the key-light side (azimuth −40°), key light only, the head rendered 320 px tall and box-averaged ×8 to 40 px, read from a **scene-linear EXR** (independent of exposure and view transform). `eye_band_darker` = 1 − L(eye band) / L(cheek); pass ≥ 0.75 (`READ_EYE_MIN`; calibrated 2026-10-12: stock head 0.71, the checkpoint variants 0.76–0.81). `beard_contrast` = \|L(beard) − L(cheek)\| / L(cheek); pass ≥ 0.47 (the spec's 25 % in display terms), skipped until a mesh named `*beard*` exists. The hair-vs-grey separation check is not implemented yet (hair track). |
| `head_edits` | the resolved controls and plane blends, max vertex move (mm), vertices moved |
| `spec_checks.nose_hump_mm`, `nose_proj_ratio` | caricature guard for face C (`head_measure.py`): dorsal hump over the nasion–pronasale chord ≤ 2.5 mm; nose projection ÷ length 0.60 ± 0.10 |
| `refine.head_refine / skin / eyes` | the fidelity stage: subdivision face counts, re-planarisation move, sculpt amplitudes, UV re-pack scales, skin map sizes and timing, eye sphere fit |
| `landmarks_glb.stature_m` | (context) joint/vertex measures of the **shipped** GLB: top of the body mesh to the lowest point of any mesh (shoe soles) |
| `landmarks_glb.head_height_m / width_m / depth_m` | extent of body vertices with ≥ 0.5 weight on `head`: crown to the lowest such vertex (≈ chin/jaw), and its x / y extent (incl. ears) |
| `landmarks_glb.heads_tall` | stature / head height (shoes included; reads lower than the spec value) |
| `landmarks_glb.shoulder_joint_width_m`, `hip_joint_width_m`, `shoulder_to_hip` | joint distances `upperarm_l`–`upperarm_r`, `thigh_l`–`thigh_r`, and their ratio (not the spec's surface breadths) |
| `landmarks_glb.leg_length_m`, `torso_length_m`, `leg_to_torso` | hip joints → floor; hip joints → `neck_01`; their ratio |
| `landmarks_glb.arm_length_m`, `arm_to_stature` | `upperarm_l` → `lowerarm_l` → `hand_l` |
| `landmarks_glb.head_width_to_height`, `head_width_to_shoulder` | face/head shape and head-to-body scale |
| `silhouette.<view>` | mask bbox `height_m`, `width_m` and `area_px` |
| `iou_prev.<view>` | mask IoU against the previous (or `--prev`) run, for the 4 views and the 2 face mask views: 1.000 = identical silhouette |
| `iou_target.<view>` | mask IoU against `--target DIR/<view>_mask.png` (same 512² orthographic framing) |
| `timings_s` | build stages, Blender build total, beauty seconds per view, mask total, whole process |

Joint names are the MPFB `game_engine` (UE-mannequin) names. All landmarks are measured in the rest (A-)pose. The spec landmarks follow look-spec §1.1 exactly (one implementation, shared with `look_spec_landmarks.py`); `landmarks_glb` is for relative comparison only.

**Why two landmark sets.** Track A measured the clothed, staged GLB (joint distances; covered body polygons deleted), which gave heads 7.56 and shoulder:hip 1.744 on the spike-1 build. The spec measures surface breadths on a nude body, which gives 7.84 and 1.41 on the same build. The spec numbers are the contract, so the build now measures them on the live human before any clothes are fitted, in the same build (no second nude build).

### Using it in a best-of-N loop

1. Write N candidate configs (or N edits behind config keys in the module you own).
2. Run each with `--prev <the current accepted run>`, so every candidate is scored against the same base.
3. Reject candidates that break budgets (`tris`, `max_weights_per_vertex`, validator errors) or move a landmark ratio the wrong way. Rank the rest by the check that matters for the edit (e.g. `iou_target`, `head_width_to_height`) and by looking at the sheets.
4. `--compare` the winner against the base, then make it the new base.

Builds are deterministic: the same config gives IoU 1.000 against itself.

## Measured (2026-10-12, Blender 5.2.2, radeonsi iGPU, idle machine)

| Step | Time |
|---|---|
| Build in Blender (all stages + GLB export) | 1.8 s (process ~2.5 s) |
| Validator | 0.2 s |
| Loop beauty, EEVEE 512² / 16 samples | 0.45–0.68 s per view (mean 0.51 s; first view pays shader compile) |
| Masks (4 views) | 0.3 s total |
| **Whole loop iteration** | **5.4–5.6 s** (track A); **6.5–7.5 s** with the spec landmarks, read test (+0.3 s) and face masks (+0.15 s), at load average 5–7 from other jobs |
| Sign-off beauty, Cycles 1024² / 128 spp + OIDN, 16 threads | 10.5–16.5 s per view (close-up slowest); 53 s per run |

## Provenance

After a build you intend to ship, write it to `data/build/character/character.glb` and refresh its record:

```sh
python3 -I bench/m1/character_provenance.py --data-root /home/akram/code/or3/data
python3 -I provenance/audit.py --data-root /home/akram/code/or3/data --check-files
```
