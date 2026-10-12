# m1 suit track: black three-piece

The stock CC0 suits01 `toigo_male_suit_tie_and_jacket` shell, tailored by script into the black three-piece in [`look-spec.md` §4](look-spec.md#4-suit). All the work is in `blender/character/suit.py` (stage hooks and options) and `blender/character/suit_ops.py` (geometry helpers). It runs on the staged export meshes in rest pose; no module outside the suit track was edited.

Final run: `data/build/lookdev/20261012T093706Z-suit-final/`. It includes `suit_views/` (detail renders and the `pose_check` stress pose).

## What the build does now

`suit.add` fits the stock garments, as before, and keeps a copy of the **unmasked body**: the clothes' `Delete.*` masks are muted, the helpers stay hidden, the targets are applied and the skin weights kept. The staged body has its covered polygons deleted, so the waistcoat can't be built from it. `suit.post` then works through these steps:

1. **Split the shell** by loose part, classified by size and position: jacket, trousers, shirt, tie blade plus knot (joined into one tie), and two buttons. The parts are named `<human>.suit_<part>_export`, so the harness counts tris per part.
2. **Jacket.**
   - **Hem.** Torso vertices below z 1.00 are stretched so the hem lands at 0.50 × suprasternale height. x and y are unchanged, so the skirt hangs straight.
   - **Front re-cut.** The stock lapels close at z ≈ 1.23, 10 cm above the fastening button, which hid the waistcoat. Each front panel's edge strip is compressed outward between the button and z 1.40, eased in over 15 cm. This opens the V down to the button. The panel side comes from neighbourhood mean x, because the panels overlap across x = 0. The parameters are the best of 6 candidates, judged on the torso and V-bottom close-ups.
   - **Vents.** `vents`: `double` (default; user ruling 2026-10-12) or `centre` / `none`. 24 cm slits, cut along the most vertical edge chain from the back hem at ±0.55 of the hem half-width. The outer flap is lifted 4 mm, tapering to 0 at the top.
   - **Sleeves.** Pulled back to 5 mm past the hand joint (a 1.5 cm shift), with a smoothstep fade over 8 cm.
3. **Tie.** The blade is stretched so its tip ends 2 cm above the trouser waistband (it tucks under the vest). Faces more than 3 cm below the vest V are then deleted (look-spec §4.3).
4. **Trousers.**
   - **Quarter break.** Below the knee the hem stretches down to 3.5 cm at the back and stays put at the front, blended by depth.
   - **Creases.** Front creases run from hem to z 0.98 and back creases to z 0.80, on each leg. Each is an edge chain pushed out 2.5 mm and marked sharp.
5. **Shirt.**
   - **Clearance.** Shirt vertices with the jacket closer than 12 mm along the normal are pulled in. At 6 mm the white still showed through at the lapel undersides.
   - **Cuffs.** The shirt shell has no sleeves, so a 16-segment cuff band is built inside each sleeve end. It shows 13 mm past the sleeve, with a rolled lip; weights come from the nearest sleeve vertex.
6. **Waistcoat**, built from the unmasked body's torso faces (dominant bone pelvis, spine or clavicle):
   - **Panels.** Full front plus a 12 cm lower back panel.
   - **Opening.** V from the neck point (±7.5 cm, suprasternale + 2 cm) down to the top button.
   - **Hem.** The sides sit 2.5 cm below the waistband top; the points drop 5 cm further, with a notch between them.
   - **Snapping.** The cut edges are snapped to the hem, V and panel lines.
   - **Offset.** 7 mm off the body, pushed clear of the shirt and tie by ray casts (+3 mm), smoothed, then clamped 4 mm inside the jacket (348 vertices clamped).
   - **Weights** are the body's own.
7. **Buttons.** All seven are 8-segment discs of 22 tris, weighted to the nearest host vertex:
   - The two 276-quad stock jacket buttons are replaced at the same positions.
   - Five vest buttons run down the centre line; the bottom one sits on the points.
8. **Materials.** Flat look-dev materials, no textures:
   - `suit_wool`: linear albedo 0.03, roughness 0.72, sheen 0.06.
   - `suit_shirt`: 0.75.
   - `suit_silk`: 0.02, roughness 0.4, sheen 0.12.
   - `suit_button`.
   - The glTF exporter writes Sheen *Tint* as `sheenColorFactor` and ignores Sheen Weight, so the strength goes in the tint. A first pass with weight 0.35 and a white tint exported a full white sheen.
9. **Budgets** per part (collapse decimation through `budgets.decimate`): jacket 9,000; tie 700; waistcoat 2,000; shirt 1,500; trousers 3,500; shoes 3,000.
10. **Hidden body.** A body vertex counts as covered when all 5 rays in a 34° cone around its normal hit a garment within 6 cm. Covered vertices more than 3 cm from a visible one are deleted. The head is never touched, and hair is not an occluder.

Every option is in `suit.DEFAULTS` and can be overridden through the build config's `suit` section, e.g. `{"suit": {"vents": "centre"}}`. `{"suit": {"tailor": false}}` gives the stock shell back (19,202 tris, as in spike 1). The resolved options and every measurement below land in `character.stats.json["suit"]`.

## Measurements against look-spec §4.1 (final run)

| Check | Spec | Before (stock) | After | |
|---|---|---|---|---|
| Jacket hem ÷ suprasternale z | 0.50 ± 0.015 | 0.567 | **0.500** (hem z 0.753) | ✅ |
| Fastening button z ÷ stature | 0.61 ± 0.01 | 0.619 | 0.619 | ✅ (unchanged) |
| Jacket shoulder width − body bideltoid | +2.0–3.5 cm | +3.3 cm | +3.3 cm (0.578 vs 0.545 m) | ✅ |
| Waist suppression (width at button ÷ chest) | ≤ 0.88 *(cal.)* | 0.79 | 0.79 | ✅ |
| Tie tip above waistband top | 0–4 cm | −10.3 cm (1.250 vs 1.147) | **+2.0 cm** (tucked under the vest) | ✅ |
| Waistband top ÷ stature | 0.59–0.63 | 0.623 | 0.623 | ✅ |
| Trouser back hem z | 0.035 ± 0.01 m | 0.065 | **0.0355** | ✅ |
| Vest bottom below the waistband top | > 2 cm | – | 2.5 cm at the sides, 7.5 cm at the points | ✅ |
| Vest top button above the jacket button | 12–14 cm | – | 12.8 cm | ✅ |
| Vents | double, 24 cm | none | double, 24.7 / 26.0 cm | ✅ |
| Cuff reveal | 1–1.5 cm | 0 (no cuff) | 1.3 cm by construction | ✅ |
| Lapel width 8.5 cm, gorge, roll to the button | [auto] / [visual] | stock notch lapel | stock lapel kept. The V is opened to the button by vertex compression (see issues) | 🟡 |
| Max weights per vertex / glTF errors | 4 / 0 | 4 / 0 | 4 / 0 (14 warnings, all the known `NODE_SKINNED_MESH_NON_ROOT`, one per skinned mesh) | ✅ |

### Triangles

| Part | Spec | Stock | After |
|---|---|---|---|
| Jacket | ≤ 9,000 | 12,534 (inside the 19,202 shell) | 8,999 |
| Waistcoat | ≤ 2,000 | – | 1,524 |
| Shirt (with cuffs) | ≤ 1,500 | ~1,256 | 1,448 |
| Tie and knot | ≤ 700 | ~2,120 | 700 |
| Trousers | ≤ 3,500 | 2,188 | 2,188 |
| Buttons (7) | ≤ 200 | 1,104 (2) | 154 |
| **Suit total** | | **19,202** | **15,013** |
| Shoes | ≤ 3,000 | 3,320 | 3,000 |
| Body | ≤ 10,000 | 15,240 | 15,164 ❌ |

**Character total: 43,949 → 39,364 tris.**

The **body** is outside the suit's reach. MPFB's delete masks had already removed the covered torso, and what remains is **8,156 tris of head and 6,380 of hands** (392 neck, 62 torso/arm). Getting to ≤ 10k means reducing head and hand density, which belongs to the head/body track (or a budgets entry).

Loop iteration with the suit: 6.8–7.0 s per harness run, with the build at 2.4 s in Blender. `suit.post` itself takes about 0.4 s.

## Remaining issues and deformation risks (for m2/m3)

- **Jacket skirt in leg raises.** In `pose_check` (thigh −50°, knee 80°), the front skirt over the raised thigh lifts with it and shows its single-sided inside. The lengthened skirt carries the stock hem's thigh weights. This is the job of the planned `glute_helper` bones and the Dem Bones jacket bones (look-spec §5.2).
- **Lapel tip.** Opening the V by compressing vertices leaves a small fold where the top panel's lapel tip curves back to its overlap at the button (visible in `suit_views/v_bottom.png`). A clean fix re-cuts the roll line and notch as new geometry (look-spec §4.2 "bevel the lapel roll, re-cut the notch and gorge"); that's not done. The lapel width is not measured yet.
- **Single-sided garments.** All materials export `doubleSided`. The insides of the vents and the V are the same black wool, and the jacket has no lining.
- **Waistcoat vs jacket in motion.** The vest is clamped only 4 mm inside the jacket in rest pose, and the two share torso weights but not identical ones. Expect poke-through when the torso twists. The automated poke-through test (look-spec §4.3: ID pass over the pose set) is not built yet.
- **Not done from §4:**
  - Sharper shoulder line (the width already passes).
  - Waist suppression reshape (passes).
  - Shirt hidden-region culling (shirt is within budget).
  - Satin back panel on the vest (one wool material).
  - Trouser leg-opening taper.
  - Crease normal-map line (geometry ridge only).
  - Pockets and cuff buttons (texture work).
- **Harness notes, for its owner:**
  - The studio rig runs about 2 EV hot. Floor albedo 0.08 renders light grey, and the spec's 0.03 black wool reads mid-grey in `sheet.png`. `bench/m1/suit_views.py` renders at −3 EV for this.
  - `lookdev.sh` carries on after a failed build, because Blender exits 0 on a Python exception. The visible error is then a Node `ENOENT` on `character.glb`.
  - `latest` and the default `--prev` are shared across parallel tracks, so pass `--prev` explicitly.

## Tools

- `bench/m1/lookdev.sh <label>`: the harness. Suit parts show in `metrics.json` as `tris.parts.suit_*`.
- `blender -b --factory-startup --python bench/m1/suit_views.py -- --glb RUN/character.glb --out-dir DIR`: renders back, back hem, torso, torso ¾, V bottom, cuff, and trouser hem front and back, at −3 EV (the harness has no back view).
- `blender -b --factory-startup --python blender/pose_check.py -- --glb RUN/character.glb --out DIR/pose.png`: the spike-1 stress pose.
