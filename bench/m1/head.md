# m1 head and proportions track (wave 2)

_2026-10-12. Scope: unify the harness metrics with the look spec, move the body to the spec proportions, cut the teeth to budget, build the parametric face controls and three face variants for the direction checkpoint ([`look-spec.md`](look-spec.md) §1, §2, §5.1, §6)._

**Result:** all three variants pass every automatic spec check (§1.2 proportions and face ratios, brow overhang ≥ 12 mm, 40 px read test). The stock head fails brow overhang (7 mm). The body is at the §1.2 targets in every variant. Teeth are 479 tris. With neutral parameters the build is byte-identical to before (checked against the track-A merge run).

## 1. Metric unification

The two landmark sets disagreed because they measure different things:

| | Track A harness (old) | Look spec (contract) |
|---|---|---|
| Mesh | staged, clothed GLB: covered body polygons deleted, shoes on | nude MPFB body |
| Shoulder / hip | joint distances (`upperarm`, `thigh`) | surface breadths: bideltoid, widest pelvis/thigh section |
| Head height | crown to the lowest head-weighted vertex | crown to menton (midline profile) |
| Spike-1 build | heads 7.56, shoulder:hip 1.744 | heads 7.84, shoulder:hip 1.41 |

What changed:
- **`blender/character/head_measure.py`** implements look-spec §1.1 once, plus **brow overhang** (both sides, mean: most forward brow vertex within 4 mm of the eye-centroid x and 8–40 mm above the eye centre, minus the cornea front, along −Y). It bypasses modifiers when reading coordinates, because the live human's MASK modifier drops helper vertices and would break the vertex-index mapping.
- **`head.add_parts`** calls it on the live human after the face parts are fitted and before hair or clothes exist. The body is still nude and fully topological there, so no second build is needed. The numbers go into `character.stats.json` as `spec_landmarks` and `spec_checks`.
- **`bench/m1/lookdev_report.py`** makes them `metrics.json` `landmarks` and `spec_checks`. The old joint measures move to `landmarks_glb` (context; they include shoes). The sheet header prints every spec check with `+` / `!`.
- **40 px read test** (`blender/lookdev_render.py`, `read40`): ¾ view from the key-light side (azimuth −40°), key light only. The head is rendered 320 px tall and box-averaged ×8 to 40 px. Sample boxes are projected from 3D: the eye band (±14 mm around the near eye, −6 to +12 mm in z) and the cheek below it (24–42 mm under the eye centre). `eye_band_darker = 1 − L_eye / L_cheek` in relative luminance. The beard check runs once a mesh named `*beard*` exists; it is skipped until then. `read40.png` shows the 40 px image with the boxes drawn.
- **Face mask views** `face_front` and `face_profile`: body and eyes only. The long hair makes the `closeup` silhouette blind to face edits (IoU 0.999+ for every variant against the stock head). These masks show the change (0.98–0.99).
- `bench/m1/look_spec_landmarks.py` is now a thin wrapper around `head_measure` for one-off `.blend` files. It still reproduces the spec's baseline numbers exactly (1.8404 m, 7.84, 0.545 m, 1.41, …).
- Cost: the build measure is ~0.2 s, the read test 0.3 s, and the face masks 0.15 s. A full iteration was 6.5–7.5 s at a load average of 5–7 (other agents running), against 5.4–5.6 s idle before.

**Calibration note.** The eye-band threshold (≥ 15 %) is too loose: the stock head already scores 40 % under the key light alone, and the variants 46–49 %. Calibrate at the checkpoint against what the user reads as "shadowed eyes" in game, probably ≥ 45 %.

## 2. Proportions

MPFB detail targets on the body, applied before the rig is fitted, so the joints follow. Measured effect per unit weight (nude, spec definitions): `measure-shoulder-dist-incr` +36 mm bideltoid, `torso-vshape-incr` +24 mm, `hip-scale-horiz-decr` −74 mm hip breadth. The weights interact once the rig refits (the first try overshot to a 0.575 m bideltoid), so they were tuned in two runs.

New defaults in `blender/character/config.py`:

```json
"body": {"macros": {"height": 0.607},
         "targets": {"measure-shoulder-dist-incr": 0.12, "torso-vshape-incr": 0.15, "hip-scale-horiz-decr": 0.18}}
```

| Spec measure | Spike-1 build | Now | Target |
|---|---|---|---|
| stature | 1.840 m | 1.850 m | 1.85 ± 0.02 |
| heads_tall | 7.84 | 7.85 (stock head) | 7.8 ± 0.15 |
| bideltoid | 0.545 m | 0.561 m | 0.56 ± 0.015 |
| hip breadth | 0.386 m | 0.373 m | — |
| shoulder_to_hip | 1.41 | 1.50 | 1.50 ± 0.04 |
| leg_ratio / leg_to_torso | 0.490 / 1.49 | 0.490 / 1.49 | keep |

The suit refits cleanly (MPFB proxy fitting follows the shape-key mix), and the sheets show no poke-through at A-pose.
- Body silhouette IoU against the spike-1-proportion build: front 0.944, ¾ 0.957, profile 0.973.
- The front silhouette grows 13 mm taller and 25 mm wider across the A-posed arms.
- Run `20261012T093419Z-iou-check-proportions` scores this against `20261012T091907Z-ht-baseline`.

## 3. Teeth

`budgets.decimate.teeth` 900 → 480, giving **479 tris** (look-spec §5.1: ≤ 500). Same collapse decimation as track A. The teeth are barely visible with the mouth closed; recheck them in the mouth-open blendshapes later.

## 4. Face controls (`blender/character/head_shape.py`)

`head.edit_base` first loads the MPFB face targets in `head.targets`, then applies the parametric edits. The edits become one shape key, `head_edits` (value 1), on the live human before any proxy is fitted, so eyes, brows, lashes, hair and clothes follow it. `export.bake_targets` bakes it with the macros.

- **Face frame:** origin at the midpoint of the two eye-helper centroids. Axes are u = |x|, h = up and f = forward (−Y), all scaled by the interpupillary distance against the default build (61.6 mm), so regions follow head size.
- **Controls:** all 17 from look-spec §2.3, scalars in [−1, 1] at the spec's mm ranges. Each control is a smooth, **mirrored** displacement field over an anisotropic Gaussian region (`REGIONS`): brow, socket, lid, nose, bridge, malar, sub-malar, gonial, chin, forehead, and the `lips` vertex group. Mirroring is exact: fields use |x| and flip the x component by side.
- **Lattice vs. field.** These Gaussian displacement fields stand in for the spec's 3 × 3 × 3 lattices: the same low-dimensional, smooth, mirrored deformation, with no lattice objects to keep in step with the macros.
- **Planarisation pass:** 9 plane groups (`PLANES`): forehead, brow front, brow underside, nose dorsum, nose sides, malar, sub-malar, jaw side, chin front. Each is pulled toward its weighted least-squares plane by a 0..1 blend.
  - Masks are plateau-shaped (exp(−r⁴/2)), so a group moves as one facet with a quick edge. Plain Gaussians barely flattened anything visible.
  - Midline groups fit one plane symmetric about x = 0. Lateral groups fit the left side and mirror it.
  - Helpers and anything within 20 mm of an eye centre are never planarised. Without that exclusion, an early malar group cut a seam under the lower lid.
  - `brow_flatten`, `dorsum_crease` and `cheek_plane_break` drive their plane groups; `head.planes` sets the rest directly.
- **Region check:** each region was exaggerated (×3) once and rendered to confirm it lands where the spec names it. The gonial region was moved lower and back after that check: it was widening the cheek at mouth level instead of the jaw corner.
- **No untracked edits** (look-spec §2.4 rule 3). Everything is in the JSON, and unknown control or plane names raise an error.

## 5. Variants (direction checkpoint)

Configs: `bench/m1/variants/face-{a,b,c}.json`. Run them with `bench/m1/lookdev.sh --config bench/m1/variants/face-a.json face-a`.

| | A, lean and angular | B, heavier | C, weathered |
|---|---|---|---|
| Idea | high cheek break, hollow cheeks, leaner head (`head-fat-decr`), narrow end of the jaw range | wide square jaw, deeper and lower brow, thick neck, broad nose | deepest sockets, hooded lids, hollow cheeks, eye bags, longer face, dorsal hump, thinner lips, some MPFB head ageing |
| MPFB face targets | head-fat-decr 0.6, cheek-volume-decr 0.5, cheek-bones-incr 0.5, chin-height-incr 0.1, eye-scale-decr 0.3, nose-point-width-decr 0.3, nose-hump-incr 0.2 | head-age-incr 0.2, chin-prominent-incr 0.4, cheek-volume-decr 0.2, neck-scale-horiz-incr 0.3, nose-scale-horiz-incr 0.3, nose-flaring-incr 0.2, eye-scale-decr 0.3, eyebrows-trans-down 0.3 | head-age-incr 0.6, chin-height-incr 0.12, cheek-volume-decr 0.6, nose-hump-incr 0.4, nose-scale-vert-incr 0.2, eye-bag-incr 0.3, eye-scale-decr 0.2 |
| Key controls | brow_depth 0.9, cheek_plane_break 1.0, submalar_hollow 0.9, cheek_height 0.7, jaw_width 0.3 | brow_depth 1.0, socket_depth 0.7, jaw_width 0.6, jaw_angle 0.6, chin_width 0.8, nose_bridge_width 0.6 | socket_depth 1.0, lid_hood 0.9, submalar_hollow 1.0, nose_length 0.4, lip_thickness −0.4 |
| heads_tall | 7.78 ✓ | 7.81 ✓ | 7.75 ✓ |
| bizygomatic | 0.138 m ✓ | 0.140 m ✓ | 0.140 m ✓ |
| jaw_to_cheek | 0.847 ✓ | 0.898 ✓ | 0.867 ✓ |
| lower_face_index | 0.894 ✓ | 0.873 ✓ | 0.887 ✓ |
| brow overhang (≥ 12 mm) | 12.2 mm ✓ | 14.0 mm ✓ | 14.5 mm ✓ |
| read40 eye band darker (≥ 15 %) | 48 % ✓ | 46 % ✓ | 49 % ✓ |
| face IoU vs stock (front / profile) | 0.997 / 0.990 | 0.983 / 0.994 | 0.995 / 0.990 |
| max vertex move (edits only) | 7.0 mm | 7.1 mm | 6.7 mm |
| tris / bones / w per v / glTF errors | 43,530 / 53 / 4 / 0 | 43,529 / 53 / 4 / 0 | 43,529 / 53 / 4 / 0 |

The stock head on the new body scores heads 7.85, jaw 0.84, LFI 0.865, brow 7.1 mm (out) and eye band 40 %.

**Best-of-N with revert.** Each variant started from a hand-set base. It was fixed until every check passed: A first had jaw 0.829 and brow 11.6 mm; B's jaw was 0.91; A and C had heads ~7.6 from a 0.3–0.4 `chin-height-incr`, now 0.10–0.12. Then one best-of-3 round per variant. Each candidate changed 1–2 controls; any spec failure was rejected; the rest ranked on the read test; a winner had to beat the base by more than 0.5 points.

| Variant | Candidates (Δ) | Read score base → candidates | Kept |
|---|---|---|---|
| A | brow_flatten +0.2 & socket +0.1 / malar+submalar planes 1.0 / lid_hood +0.3 | 48.2 → 48.2 / 48.1 / 48.3 | base (no candidate cleared the margin) |
| B | socket +0.3 / brow_angle +0.2 & lid +0.2 / submalar +0.3 | 45.8 → **46.3** / 45.7 / 45.7 | socket_depth 0.4 → 0.7 |
| C | brow_depth +0.2 / lid −0.2 & brow_flatten +0.3 / brow_under plane 1.0 | 47.9 → **49.0** / 47.9 / 48.0 | brow_depth 0.7 → 0.9 |

**What I saw in the close-ups** (hair hidden, front / ¾ / profile, key+fill and key only):
- A reads leanest. It has a visible diagonal cheek plane break and hollows under the cheekbones, and the narrowest jaw.
- B reads broad and blocky: square jaw corners, thick neck, lower and heavier brow.
- C reads oldest and longest: deep-set hooded eyes, a nose with a hump, hollow cheeks, thin mouth.
- All three still carry MPFB's smooth skin shading. The geometry gives the planes, but the Sifu look will come mostly from the painted texture pass (look-spec §0). Expect the faces to read more "sculpted" than "faceted" until then.
- At game distance the brow shelf is what reads: every variant raises the eye-band score.
- None is built toward any real person. They are parameters only, and the user's likeness question is still due at the checkpoint (§2.4 rule 4).

**Run directories** (main checkout, `data/build/lookdev/`; each has `sheet.png`, `read40.png` and `face_strip.png`, the hair-hidden close-up strip):
- `20261012T093052Z-face-stock`: stock head on the new body (reference for the IoU column)
- `20261012T093109Z-face-a`
- `20261012T093122Z-face-b`
- `20261012T093134Z-face-c`

## 6. Open items

- **Calibrate the read test** at the checkpoint (see §1). The hair-vs-grey separation check is left to the hair track; the beard check activates once a `*beard*` mesh exists.
- **Checkpoint sheet** (look-spec §6) still needs the hair options, the suit blockout, the game-camera view and the neon rig. These variant configs drop into it as `--config` overrides.
- **Brow cards.** The MPFB eyebrow cards follow the edited brow (fitted after the edits), but they sit flat on the shelf. The hair track's clump brows should follow `brow_angle`.
- **Teeth at 479 tris** need a check once there are mouth-open poses.
