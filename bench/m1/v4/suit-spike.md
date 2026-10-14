# Suit pattern spike: drafted, sewn, draped jacket (m1 v4 step 5, 2026-10-14)

**Question.** Can a jacket that is pattern-drafted and draped with sewing springs give the structure the lofted jacket cannot? The three tests are a lapel roll, a sleeve pitched forward and bent at the elbow, and a skirt that hangs off the seat. It has to be built headless and deterministically from the body landmarks the pipeline already measures, at an acceptable build time and triangle count.

**Answer: a conditional go.** The drafted body, sleeves and skirt pass. The sleeve and skirt structure is real, and so is the determinism, the build time and the triangle count. Blender's built-in cloth cannot finish the jacket as it is, though. The collar fails, every sewn seam settles as a hinge, and the back clings to the anatomy. Overall, the spike output today looks worse than the lofted jacket.

So before committing to the full rebuild (about 13 working days, range 11 to 16), run a short spike 2 (1.5 to 2 days). Its job is to close those three failures with the fixes in §5. Then gate on its pictures.

Public build only. The base was `data/build/lookdev/20261014T101019Z-t6-base/character.blend`, with no fan config. Nothing under `private/` was opened.

## 1. What was built

| File | What it does |
|---|---|
| `blender/character/suit_pattern.py` | Draft only, numpy, no bpy. **Measuring:** girths are convex-hull plane sections of the rest body (a tape bridges hollows), and lengths come from sagittal profile tapes. Faces are split torso/legs/arms by dominant bone. **Draft:** an Aldrich-style men's block in cm, with front, side body, back with centre seam, two-piece sleeve and undercollar. Suppression is shared over the CB, back/side and side/front seams. The sleeve cap is solved by bisection to the armhole plus 3 cm ease. Sleeve pitch and cuff slant are in the pattern. The lapel has a roll line. The shoulder sits 1.75 cm past the acromion, plus the pad. **Output:** seams with 1:1 sampled pairs, notches, and an SVG pattern sheet with 1 cm seam allowance. |
| `bench/m1/v4/suit_spike.py` | The spike runner (`blender -b`). **Place:** loads the base build, captures the rest body and places the panels. Below the chest line they are wrapped on eased hull rings. Above it, a thin-plate spline through the body landmarks places them. Sleeves are wrapped on the bent rest-pose arm axis; the lapel is pre-folded on the roll line; the collar is stood up on the neckline. **Sew and drape:** one cloth object is sewn with sewing springs, and its rest shape key is the flat pattern. The collider set is the body, two shoulder-pad domes, and the shipped shirt, waistcoat and trousers. Gravity ramps in after the sewing phase, and self-collision is on. **Keep and render:** the settled cloth is kept as a welded mesh. Renders are EEVEE clay A/B against the lofted jacket at the same ortho cameras, plus a bent-arm pose. |
| `bench/m1/v4/suit_spike.sh` | The wrapper. It finds `data/` via `git rev-parse --git-common-dir`, refuses private inputs, runs `nice -n 10 blender -b -t 3`, and builds the A/B sheets. Output goes to `data/build/suit_spike/<UTC>-<label>/`. |

Nothing in the shipped suit path was touched (`suit_build.py`, `suit_jacket.py`, `suit_drape.py`, `suit_textures.py`, `export.py`, `config.py`).

**Measurements (t6 base, cm).**

| Measure | Value |
|---|---|
| Stature | 185.1 |
| Chest / waist / seat | 104.4 / 77.7 / 94.1 |
| Neck | 40.5 |
| Nape to waist | 41.8 |
| Scye depth | 18.2 |
| Sleeve length | 57.1 |
| Bicep / wrist | 31.7 / 14.8 |
| Bideltoid | 64.5 |
| Rest elbow bend | 45° |

`across_back` reads 52 cm because it is the hull arc between the arm roots, not a tailor's across-back. The draft does not use it.

**Draft (cm), from `spike_stats.json`.**

| Item | Value |
|---|---|
| Shoulder seam (back / front) | 15.7 / 15.1 |
| Back neck | 15.0 |
| Armhole | 48.8 against a cap of 51.8 (3 cm ease) |
| CB | 77.4 |
| Sleeve hind seam | 49.9 |
| Collar neck edge, per side | 24.6 |

## 2. Pictures

The run is `data/build/suit_spike/20261014T122746Z-sim3/` (the final iteration). In every sheet the lofted jacket is on the left and the spike on the right, at the same camera.

- `ab_sheet.png`: front, ¾, profile and back at rest.
- `ab_bent_sheet.png`: the bent pose (shoulder flex 35°, elbow +30°) in front, ¾ and profile. The lofted jacket is skinned; the spike is re-simulated.
- `closeup_sheet.png`: ¾ chest and profile close-ups, lofted then spike. I cropped this by hand from the single views; the wrapper does not make it.
- `pattern.png` / `pattern.svg`: the drafted pattern sheet, with seam allowance, roll lines and notches.
- Single views: `lofted_*.png`, `pattern_*.png`, `lofted_bent_*.png`, `pattern_bent_*.png`.
- `spike.blend`: holds `spike_jacket_rest`, `spike_jacket_bent` and the cloth object.

Earlier iterations are in the same folder, for the record:

- `20261014T120304Z-sim0`: neck seams torn open.
- `20261014T121033Z-sim1`: self-collision on.
- `20261014T121919Z-sim2`: neckline under-drafted, canvas hinge at the waist.

## 3. The three structure tests

| Test | Lofted | Spike (sim3) | Verdict |
|---|---|---|---|
| **Sleeve pitched forward, bent at the elbow** | A straight tube. In the bent pose it stays a skinned tube with no crook folds. | The sleeve hangs forward of the side seam (profile). In the bent pose it folds at the crook, and the top sleeve stretches over the elbow (`ab_bent_sheet.png`). Sleeve strain is \|0.08\| mean and seam gaps are 0.4 to 3 mm. | **Pass.** The lofted method cannot do this. |
| **Skirt hanging off the seat** | Follows the body down to the hem. | The back skirt leaves the seat and hangs straight (profile, back). The hem is level. | **Pass.** |
| **Lapel roll** | A flat lapel shape: lapel and front are one sheet with a drawn edge. | The lapel is turned on the roll line and lies back over the front with a rounded break (`closeup_sheet.png`). The edge is ragged, and the roll is soft rather than crisp. | **Partial.** The roll is real geometry, but it is not production quality. |

## 4. Numbers

**Build time (sim3, `-t 3`).** The machine load was about 30 on 16 cores, with two spike runs going at once.

| Step | Time |
|---|---|
| Body capture | 3.3 s |
| Measure | 0.2 s |
| Draft | 0.01 s |
| Mesh and place | 0.7 s |
| Colliders | 0.2 s |
| Sewing phase (f1–30) | 28.8 s |
| Gravity and settle (to f70, the rest drape) | 49.5 s |
| Bent pose (f71–115) | 71.3 s |
| **Total simulation** | **149.6 s** |
| Render (8 EEVEE views) | 65 s |

End to end it is about 3.7 min. That is about 1.6 s per frame at cloth quality 8, collision quality 3, with self-collision on. sim2 under a lighter load gave 145.8 s for the simulation.

**Triangles.** The spike rest jacket is **10,312 tris / 5,277 verts** after the weld, against **17,747** for the lofted jacket. Mesh density is set by `h_cm`: 1.6 cm here, and 1.8 to 2.0 cm gives about 8k to 6.6k. Either way it is well inside the hero LOD0 budget (NOTES, Budgets: ~120k total).

**Determinism.** sim3 and sim3b used the same inputs and ran at the same time. Their `placed.npz` and every saved frame of `drape.npz` (f1, f30, f70, f115) are **bit-identical**: the maximum absolute difference is 0.0.

**Drape quality (rest frame f70).**

| Metric | Value |
|---|---|
| Strain, mean edge (all panels) | 0.099 |
| Strain, back / front / sleeves | \|0.09\| / \|0.10\| / \|0.08\| |
| Strain, collar | +0.40 mean, \|0.52\| |
| Sewing gap, mean | 1.9 mm |
| Sewing gap, p95 | 5.9 mm |
| Sewing gap, max | 50 mm (collar) |
| Body seams (CB, side, sleeve) | 0.4 to 0.8 mm mean |
| Shoulder and armhole seams | 2 to 3 mm mean |
| Left collar to neckline | 23 mm mean (torn open) |
| Right collar to neckline | 5 mm mean |
| Verts inside the body | 0 |
| Verts inside any collider | 80 of 5,734 (1.4 %): shirt and waistcoat poke-through risk |

## 5. Failure modes, with causes

1. **The collar is a frill (fail).**
   - It sits at +40 % strain, and the left neck seam pulls 23 to 50 mm open.
   - The first cause was that the placed neckline was 26 % longer than the drafted one (54.0 against 42.9 cm in sim2): it rides out over the shirt collar. sim3 lengthened the drafted neckline to match (`neck_scale` 1.15), and the bodice settles. The collar did not.
   - The collar is stood up vertically from the neckline and turned down with a fixed radial offset. A 3D shape that far from the flat annulus is more than the sim can recover.
   - **Fix:** do not simulate the collar. Build the collar and the lapel facing as shaped geometry from the draft's roll line and the existing neck frame (`suit_neck.py` layer order), and attach it to the welded neckline after the drape.
2. **Sewn seams are hinges.**
   - Blender cloth has no bending stiffness across a sewing spring. The CB seam therefore folds into the spine groove as a crease with sawtooth shading. Post-weld smoothing (6 iterations over a 2-ring band) does not remove it, because the whole panel edge follows the groove.
   - **Fix:** two stages. Sew unwelded against the pattern rest (f1–30), weld the pairs, then drape the welded mesh with the sewn state as rest, so bending works across seams. Body-panel placement strain is ≤ 3 % mean, so using the sewn state as rest costs little.
3. **The back clings to the anatomy.**
   - Shoulder blades and lumbar muscles show through, even with bending raised from 4 to 12 (canvas 25 to 60).
   - A real jacket bridges these hollows with cloth, canvas and lining.
   - **Fix:** collide the back against a hull-smoothed collider rather than the bare body. This is deterministic and cheap, and the measurement code already builds the hulls. After that, bending can stay moderate.
4. **The lapel edge is ragged.** The pre-fold is a rest-shape trick: the lapel's flat rest is folded 168°. The lapel's turned edge is a boundary at 1.6 cm resolution, and nothing gives it thickness. **Fix:** the lapel joins the shaped collar and facing from item 1, with a turned edge, and the drape supplies only the front's roll.
5. **Front V and button.** The fronts close only at the button spring, and the V above it is wavy and opens wider than the lofted jacket. A stiffness hinge at the waist (a hard canvas step) caused a drawstring line in sim2. sim3 fixed it with a feathered full-canvas weight.
6. **Poke-through.** 1.4 % of verts are inside the shirt or waistcoat at rest. These need either a final push-out or a shared layer order with the under-garments.

What did not fail:

- Shoulder seams close (2 mm).
- Sleeves set in with the cap ease absorbed (+2.8 % strain).
- Side seams 0.6 to 0.8 mm.
- The skirt and hem.
- Determinism.
- Build time.

## 6. Full rebuild: plan and estimate

**Gate first: spike 2 (1.5 to 2 days).** It covers items 1 to 3 of §5:

- two-stage weld
- hull back collider
- shaped collar and lapel from the draft

It passes when the A/B sheet beats the lofted jacket at front, ¾ and back, with collar strain no longer relevant (the collar is not simulated) and no seam crease. If the two-stage weld cannot fix the hinge, the fallback is a small deterministic XPBD solver in numpy: welded seams, per-edge rest lengths, dihedral bending, and an SDF body collider. That adds about 3 days.

After that gate, the full rebuild (working days):

| # | Work | Days |
|---|---|---|
| 1 | Jacket detail: welt and flap pockets, breast welt, vents, buttons and holes, cuff buttons, turned edges (solidify plus a rolled edge), hidden lining. Remesh to budget (about 10k LOD0) and LOD1/2. | 2 |
| 2 | UVs from panels: the flat pattern is the UV layout, grain-aligned per panel. Pack it, then port the `suit_textures.py` marks (stripes follow the grain for free). | 1 |
| 3 | Trousers: front and back block from the leg measures, waistband, fly, crease (canvas-weighted line), sewn and draped on the legs. | 1–1.5 |
| 4 | Waistcoat: front and back, close-fitting. Its back is lining, so the drape is light. | 0.5–1 |
| 5 | Shirt: body, yoke, sleeves, collar band and fall to the `suit_neck.py` frame. Mostly hidden, so simple. | 1–1.5 |
| 6 | Rigging: transfer weights from the body, then Dem Bones fit for the 8 jacket bones in the bone plan using the simulated pose set, plus correctives. | 1.5–2 |
| 7 | Per-pose wrinkle maps: cache the rest drape, re-simulate each key pose (about 1 to 1.5 min each at today's cost), and bake the normal delta against rest into wrinkle maps blended by pose in the engine. | 1.5–2 |
| 8 | Integration: a config switch beside the lofted path, then guards. The guards cover seam gap, strain, penetration count and a determinism hash. Also caching keyed on the body hash, and the NOTES update. | 1–1.5 |
| | **Rebuild after the gate** | **9.5–12.5** |
| | **Including spike 2** | **11–14.5** |
| | **Risk reserve (XPBD fallback)** | **+3** |

**Point estimate: about 13 working days, range 11 to 16.**

The steady-state build cost would be about 2.5 min of simulation for the jacket rest drape at `-t 3`, plus about 1 to 1.5 min per extra pose. The other garments come on top and drape cheaper, because they are smaller and closer to the body. Everything is cacheable per body hash.

## 7. Reproduce

```
bench/m1/v4/suit_spike.sh --base 20261014T101019Z-t6-base <label>        # full run, ~4 min
bench/m1/v4/suit_spike.sh --base 20261014T101019Z-t6-base <label> -- --measure-only
bench/m1/v4/suit_spike.sh --base 20261014T101019Z-t6-base <label> -- --opts '{"h_cm": 2.0}'
```

Outputs per run are `measure.json`, `pattern.svg`/`.png`, `placed.npz`, `drape.npz`, `spike_stats.json` (timings, draft frame, seam lengths, strain and gap stats, options), the renders, and `spike.blend`.
