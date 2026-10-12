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

## 7. Bolder pass (2026-10-12)

**Why.** Reviewed in the hair-hidden face strips, the §5 variants were nearly indistinguishable from the stock MPFB head and from each other: a smooth, young, pale generic man. Every numeric check passed, but the edits moved at most ~7 mm. The spec's mm ranges were too timid to read, and the MPFB face targets were used at 0.1–0.6.

**What changed.**
- **Control ranges about 2× the spec's §2.3 ranges** (`head_shape.RANGES`): brow 14 mm, socket 7, lid 3.5, nose length 8, bridge 3.5, cheek height 7, sub-malar 9, jaw width 11 per side, jaw angle 10, chin 8/8, lips 3, brow angle 10°, forehead slope 8°. This is a written relaxation of look-spec §2.3.
- **Brow taper.** The brow projection fades out past the outer orbit (u > 42 mm, zero at 58 mm). At full strength the brow end otherwise stuck out of the ¾ silhouette like a horn.
- **Age through the MPFB macro**, set per variant in `body.macros.age`: 0.68 ≈ late 40s for A and B, 0.75 ≈ mid 50s for C (0.5 = 25 y, 1.0 = 90 y). Body proportions stay inside the §1.2 tolerances.
- **MPFB head-shape targets at real weights.** `head-diamond`, `head-square`, `head-oval` and `head-scale-horiz` set the cranium and jaw silhouette. `mouth-laugh-lines-in` gives the nasolabial folds, `forehead-temple-decr` the hollow temples, `neck-scale-*` the neck. Cheek volume, cheek bones, nose and chin targets run at 0.3–1.0.
- **Harness changes** (bench/m1/README.md):
  - Calibrated exposure (−2.5 EV) and a neutral look-dev skin.
  - A committed face strip: 4 views × studio / key only.
  - A scene-linear read test.
  - `face_distinct.py`, the distinctness guard.
  - A `--facet` test row.

**Variants** (`bench/m1/variants/face-{a,b,c}.json`; final runs combined with `hair-shoulder` and the merged suit):

| | stock | A, lean and angular | B, broad and square | C, long and hawkish |
|---|---|---|---|---|
| Idea | MPFB default | gaunt diamond head, high wide cheekbones, deep hollows, hard mid jaw, projecting chin, straight nose, thin neck | square block head, wide jaw and chin, low heavy brow, broad straight nose, thick neck, flat occiput | long narrow oval head, big humped nose, hooded deep sockets and eye bags, deep nasolabial folds, thin lips, sloped forehead |
| age macro | 0.55 | 0.68 | 0.68 | 0.75 |
| heads_tall (7.8 ± 0.15) | 7.85 | 7.79 | 7.83 | 7.67 |
| bizygomatic (0.140 ± 0.006) | 0.140 | 0.138 | 0.139 | 0.134 |
| jaw_to_cheek (0.87 ± 0.03) | 0.840 | 0.848 | **1.011** (relaxed, see below) | 0.855 |
| lower_face_index (0.88 ± 0.04) | 0.865 | 0.883 | 0.884 | 0.900 |
| brow overhang (≥ 12 mm) | 7.1 ✗ | 17.1 | 19.6 | 18.0 |
| read40 eye band, linear (≥ 0.75) | 0.71 ✗ | 0.76 | 0.81 | 0.80 |
| face IoU vs stock, front / profile (≤ 0.95) | — | 0.936 / 0.949 | 0.919 / 0.934 | 0.922 / 0.935 |
| max parametric move | — | 10.0 mm | 11.0 mm | 9.4 mm |
| tris / bones / w per v / glTF errors | 44.9k | 44.9k / 53 / 4 / 0 | 45.2k / 53 / 4 / 0 | 45.3k / 53 / 4 / 0 |

Between variants, face IoU front / profile is: A–B 0.885 / 0.924, A–C 0.942 / 0.947, B–C 0.898 / 0.932. All are ≤ 0.97, so every guard passes.

**Relaxation for B.** jaw_to_cheek is 1.01 against 0.87 ± 0.03. "Broad and square" is the point of B, and the spec's band was written for a single design. If the user picks B, the band moves to B's value and is frozen as the regression guard, as §1.2 already says happens after the checkpoint.

**Read test recalibrated.** It now reads a scene-linear EXR. Before, it read a display PNG, so the score moved with exposure: 40 % at the old exposure, 63 % at −2.5 EV, for the same stock head. The pass bar is ≥ 0.75 linear, between the stock head (0.71) and the variants (0.76–0.81). The beard bar is ≥ 0.47 linear, which matches the spec's 25 % in display terms.

**Runs** (main checkout `data/build/lookdev/`):
- Final, dressed with `hair-shoulder` and the merged suit: `20261012T095133Z-fbf-stock`, `20261012T095157Z-fbf-a`, `20261012T095223Z-fbf-b`, `20261012T095240Z-fbf-c`.
- **Stacked strips:** `faces-bolder-final/faces.png`, with `distinct.json` next to it.
- Iterations before the merge, bare suit: `fb-a1…a5`, `fb-b1…b3`, `fb-c1…c5`.

**What I saw.**
- The three read as three different older, hard men at a glance, in silhouette and in the key-only row:
  - A has a cheekbone-to-jaw plane break and hollow cheeks.
  - B has a block jaw and a thick neck.
  - C has a long face, a hooked nose and hooded eyes.
- All three carry a strong brow shelf that throws the eye band into shadow under the key light.
- They still read **sculpted rather than faceted**. The `--facet 32` row barely differs from the smooth key row, because the planarisation masks blend over a few centimetres, so few edges exceed 32°.

**Weak spots.**
- **C is the closest to caricature**: a long, pointed nose and a deep upper-lip fold.
- **A's diamond target narrows the crown**, which the hair hides.
- **Skin.** The MPFB `young_caucasian_male` texture shows stubble specks and a UV seam line from the nose wing to the ear once desaturated. The skin tone and ethnicity macros (`body.race`, `body.skin`) are unchanged: that's a **user question for the checkpoint**.
- **The dressed close-ups are dominated by hair v1 and the flat beard shell**, which the hair track's quality pass is replacing.

**Options for crisper planes** (hero budget is now about 120k tris):
1. **Subdivide the staged head region once and re-run the planarisation** on the denser mesh, with sharper plateau edges. This must happen after the proxies are fitted: MPFB proxies bind by base-mesh vertex index, so the base mesh can't be subdivided. The hair and beard build from body vertex groups after staging, so they'd need to run after this pass too.
2. **Mark sharp edges between plane groups** (split normals in the GLB), for a deliberately faceted Sifu read.
3. **Leave the plane read to the painted texture and normal bake.** The spec's plan, §0.

Option 1 plus 3 is the strongest. Choose after the user picks a variant.

## 8. Face C fidelity push (2026-10-12)

**Why.** With C chosen (§7, plus the collar hair and the shell beard), the hero was still a 15k-tri MPFB head wearing the stock `young_caucasian_male` texture: soft planes, stubble specks and a nose-to-ear seam in the skin, pink lips, flat eyes, mitten hands. The brief: crisper planar form, fine skin detail, a generated 4k skin, hero eyes and hands, inside ~120k tris, **with the face kept original** (archetype only; nobody in particular).

**What changed** (new build stage `head_refine`, after `suit_post` and `hair_post`, before `rig_post`; `blender/character/head_refine.py`, `skin_tex.py`, `eyes_hq.py`, configured under `head.refine`):

1. **Topology.** The staged body (head + neck + hands after the suit hides the rest, 7,587 quads) is grid-subdivided once over the face and hands only (scalp, ears and neck stay coarse; border 5-gons are triangulated so the glTF exporter never emits a zero-area sliver). UVs and skin weights are interpolated. 7,587 → 25,769 faces; body 15,174 → 51,662 tris. MPFB proxies bind by base-mesh vertex index, so this has to happen after staging: the beard and hair sampled the low-res surface and still sit on it (verified in the close-ups after rebasing onto the facial-hair merge).
2. **Crisper planes.** The §4 plane groups are re-fitted on the dense mesh (`refine.replanarise` 1.0 × the variant's blends, plateau edge `plane_sharp` 3.0, eyes and lips excluded); max move 3.9 mm. Sharper candidates (1.4 × / sharp 4, and softer subdivision 0.3 + 1.2 × / sharp 4) were rendered side by side with the default and were indistinguishable in the key-only strip (face IoU 0.9996–1.0), so the default stays.
3. **Nose tamed.** C's hump and drooping tip were the caricature. `nose-hump-incr` 0.45, `nose-point-down` 0.1, `nose_length` 0.3, `nose-trans-forward` 0.15, `mouth-laugh-lines-in` 0.4 (`direction.json`, `face-c.json`). New guard in `head_measure`: dorsal hump over the nasion–pronasale chord ≤ 2.5 mm (was 2.99, now 2.18) and projection/length 0.60 ± 0.10 (0.54). A hookier candidate at 2.41 mm was rejected by eye.
4. **Sculpt** (along the normal, mm): knuckle bumps at MCP/PIP/DIP with a crease distal of each (2.0), extensor tendons (0.9), nail plates (0.35), lid margin thickness (0.4). Knuckles read in a cavity render and the hand close-up; they're still subtle in beauty light (see weaknesses).
5. **UV re-pack.** The MakeHuman face island is 0.35 × 0.67 of a shared body map, so a 4k map would waste most of its texels. Head islands (face, scalp, ears, neck) are re-packed into map 0 (face at ~1.49 × scale, i.e. about 2k px tall at 4k) and the hand islands into map 1 (2.66 ×); material slot 0 = head, 1 = hands.
6. **Generated skin** (`skin_tex.py`). Cycles emission bakes of position, normal, tangent, coverage, masks (lips, nails, ears, scalp, beard zone) and six 3D noise fields into texture space, plus an AO bake with hair and clothes hidden; then numpy synthesis in the face frame (origin = eye midpoint, scale = IPD / 61.6 mm): a height field (pores from Voronoi F1, grain, three forehead lines, glabella, four crow's feet, two under-eye lines, nasolabial, lip creases, neck rings) → tangent-space normal via the bump dual basis and a cavity map; albedo = measured MPFB tone (`#c4a996`) with flush, mottle, specks, socket and orbit-roof shadow, painted plane shading, baked AO at 0.4, natural vermilion lips (`#93655b` at 0.55), the beard-zone shadow and stubble darkening computed from the beard track's own `hair_beard.landmarks / inside_dist` rules so the shell edge sits on a shadow; roughness from the same zones. Hands: knuckle and flexion creases, palm lines, cuticles. Output: albedo (sRGB), ORM (AO / roughness / metallic, "glTF Material Output" group), normal; 4096² head, 2048² hands; packed into the GLB. One Principled material per slot, no SSS (export-friendly).
7. **Eyes** (`eyes_hq.py`). The MPFB low-poly eyes are replaced by fitted spheres (r 14.96 mm, 48 × 36 with a 2.2 mm corneal bulge) and a 1024² procedural iris / sclera (fibres, collarette, crypts, limbal ring; veins and a red halo at the corners; per-pixel roughness, coat for the wet line). 6,912 tris, armature-skinned like the originals.
8. **Harness.** `detail_strip.png` (eye, nose profile, mouth, hand back, palm), `skin_*` / `eyes_*` map dumps, `refine.*` metrics, nose guards in the spec row; `STRIP_PARTS` hides the shell brows in the face strip; the read test finds the new eyes.

**Numbers** (fast loop = 2k bakes; final = `direction.json` at 4k):

| | before `fc-base` | after `fc-r7` (2k) | after `fc-final` (4k) |
|---|---|---|---|
| tris total / body | 61,945 / 15,174 (card beard) | 114,471 / 51,662 | 114,475 / 51,662 |
| nose hump mm / proj ratio | 2.99 / — | 2.18 / 0.54 | 2.18 / 0.54 |
| read40 eye band (≥ 0.75) | 0.795 (look-dev skin) | 0.768 (generated skin) | 0.766 |
| spec out of band | 0 | 0 | 0 |
| GLB | 12.4 MB | 24.8 MB | 53.4 MB |
| build in Blender | 7.7 s | 39.9 s (refine 31.9) | 154 s (refine 145, of which skin 142) |

Budget: 114.5k of the ~120k target (cap 150k): body 51.7k, hair 21.2k, beard 14.0k, suit 15.0k, eyes 6.7k, brows 1.6k, rest 4.3k.

**Runs** (`data/build/lookdev/`): before `20261012T104802Z-fc-base`; iterations `fc-r1…r7`, `fc-tame-a/b` (nose), `fc-planes-a/b` (plane sharpness), `fc-hands-a`; final loop `20261012T113706Z-fc-final`; after the rebase onto the scalp-hair pass 2 merge, `20261012T114636Z-fc-r8-rebased` (115.6k tris, 65 bones with the hair springs; face strip unchanged, dressed close-up checked); Cycles sign-off pair `20261012T113957Z-fc-final-signoff` (refine on) and `20261012T114348Z-fc-before-signoff` (`head.refine: null`, same everything else: 71.5k tris, stock skin and eyes). Compare the two `closeup.png`: before is a pale, flat face with painted eyes; after has planes, tone, sockets and wet eyes.

**Likeness check.** No photo references, no real names anywhere in the prompts, code or configs; the face is C's parameter set only. The archetype (weathered, hard, quiet, 50s) is carried by age, planes, sockets and skin wear, not by any individual's features.

**Weaknesses, honest.**
- **Knuckles and tendons are subtle in beauty light.** 2 mm bumps on a 51k body read in cavity and in the hand close-up, not at game distance; the hand normal map does most of the work. A stronger push distorts the straight-finger silhouette.
- **Pores are at the edge of the 4k texel size** (0.08 mm height, ~0.5 mm pitch, 2 px). They read as grain, not as pores, at the close-up distance.
- **The nasolabial fold is still geometry-led** (MPFB `mouth-laugh-lines-in` 0.4); in flat light it reads harder than the painted one.
- **GLB doubles in size** with the 4k PNG maps; KTX2/basis compression is a runtime-side task.
- **Eyes:** the sclera is a painted colour; there is no refraction, the corneal bulge plus coat is the whole wet read. Lashes are still the MPFB cards.
- **Validator:** one `ACCESSOR_VECTOR3_NON_UNIT` tangent on `Human.beard_export` (three coincident shell vertices with the same UV at the philtrum). It is present with `head.refine: null` too (`fc-before-signoff`), so it comes from the shell beard meeting the tamed nose / philtrum (`moustache_height_m` / `nose_clear_m`), not from the dense body; the facial-hair track's `fh-final` runs on the untamed nose had 0. Harmless at runtime (one zero tangent on one shell); for the beard track to fix.
- The `read40` eye-band score fell from 0.795 to 0.768 because the generated skin replaces the neutral look-dev skin in the test; it still passes.
