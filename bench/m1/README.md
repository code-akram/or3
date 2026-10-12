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
| `body` (macros, race, skin) | `body.py` | `create` |
| `head` (face parts, cut-outs, `edits`) | `head.py` | `edit_base` (base mesh, before fitting), `add_parts`, `post` |
| `hair` | `hair.py` | `add`, `post` |
| `suit` (clothes list) | `suit.py` | `add`, `post` |
| `rig` (builtin, `helpers`) | `rig.py` | `add`, `post` |
| `budgets.decimate` (`{name part: max tris}`) | `budgets.py` | `apply` |
| `export` | `export.py` | staging, target bake, alpha fix, GLB |

The stage order is listed in `blender/character/__init__.py`. `post` hooks run on the staged export meshes after the macro targets are baked. In an override, `null` disables a default dict entry, e.g. `{"budgets": {"decimate": {"teeth": null}}}` reproduces the spike-1 GLB byte for byte.

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
| `render_metrics.json` | raw metrics from the render pass |
| `metrics.json` | the merged record (below) |
| `sheet.png` | contact sheet: header with key metrics, beauty row, masks row |
| `build.log`, `render.log` | Blender logs |

`--compare` writes `data/build/lookdev/compare-<A>--<B>/`: `compare.md` (changed metrics only), `compare.json` (all numeric metrics, A, B, delta, plus both configs) and `sheet.png` (both sheets stacked, then a mask overlay per view: white = both, **red = only A**, **cyan = only B**).

### Cameras and lighting

- **Body views use fixed world-space cameras** (target 0.98 m above the floor, 2.15 m frame height). Proportion changes therefore show up in the picture instead of being reframed away. The close-up tracks the `head` bone (0.42 m frame), so it shows the face whatever the height.
- **Masks use orthographic cameras** along the same axis, 512², with a fixed metric size per pixel (2.15 m / 512 = 4.2 mm for body views, 0.82 mm for the close-up). That makes IoU and silhouette widths comparable between runs. They are rendered with EEVEE at 1 sample, film transparent, floor hidden. Hair cut-outs (MASK) are respected.
- Studio: spike-2 rig at fixed positions (key front-left-high 900 W, fill front-right 250 W, rim behind 700 W, area lights, near-black world, dark floor).

## Metrics (`metrics.json`)

| Key | Definition |
|---|---|
| `tris.total`, `tris.parts.<part>` | evaluated triangles per imported GLB mesh (`body`, `long01`, `toigo_male_suit_tie_and_jacket`, `teeth_base`, ...) |
| `bones` | joints in the GLB skeleton |
| `max_weights_per_vertex` | max non-zero weights on any vertex in the GLB (from the validator pass) |
| `gltf_validator.errors/warnings` | Khronos glTF-Validator counts (9 known `NODE_SKINNED_MESH_NON_ROOT` warnings) |
| `landmarks.stature_m` | top of the body mesh to the lowest point of any mesh (shoe soles) |
| `landmarks.head_height_m / width_m / depth_m` | extent of body vertices with ≥ 0.5 weight on `head`: crown to the lowest such vertex (≈ chin/jaw), and its x / y extent (incl. ears) |
| `landmarks.heads_tall` | stature / head height |
| `landmarks.shoulder_joint_width_m` | distance between the `upperarm_l` and `upperarm_r` joints |
| `landmarks.hip_joint_width_m` | distance between the `thigh_l` and `thigh_r` joints |
| `landmarks.shoulder_to_hip` | shoulder joint width / hip joint width |
| `landmarks.leg_length_m`, `torso_length_m`, `leg_to_torso` | hip joints → floor; hip joints → `neck_01`; their ratio |
| `landmarks.arm_length_m`, `arm_to_stature` | `upperarm_l` → `lowerarm_l` → `hand_l` |
| `landmarks.head_width_to_height`, `head_width_to_shoulder` | face/head shape and head-to-body scale |
| `silhouette.<view>` | mask bbox `height_m`, `width_m` and `area_px` |
| `iou_prev.<view>` | mask IoU against the previous (or `--prev`) run: 1.000 = identical silhouette |
| `iou_target.<view>` | mask IoU against `--target DIR/<view>_mask.png` (same 512² orthographic framing) |
| `timings_s` | build stages, Blender build total, beauty seconds per view, mask total, whole process |

Joint names are the MPFB `game_engine` (UE-mannequin) names. The landmarks are measured in the rest (A-)pose and are meant for **relative** comparison between runs, not anthropometry.

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
| **Whole loop iteration** | **5.4–5.6 s** |
| Sign-off beauty, Cycles 1024² / 128 spp + OIDN, 16 threads | 10.5–16.5 s per view (close-up slowest); 53 s per run |

## Provenance

After a build you intend to ship, write it to `data/build/character/character.glb` and refresh its record:

```sh
python3 -I bench/m1/character_provenance.py --data-root /home/akram/code/or3/data
python3 -I provenance/audit.py --data-root /home/akram/code/or3/data --check-files
```
