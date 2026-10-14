# T13 phase A: suit spike 2 (sewn, draped jacket with a modelled rever)

**Answer: pass, with one stated exception.** The pattern jacket now beats the lofted jacket at front, ¾ and back:

- The back is smooth. No shoulder blades, lumbar muscles or seat show through, and there is no CB hinge.
- The lapel rolls from the break to the gorge and the notch reads.
- The collar sits round the neck without a frill.
- The sleeves hang with a soft fold in the elbow crook.

The other numeric gates pass:

- p95 sewing gap: 1.61 mm against a limit of 3 mm.
- Jacket vertices inside the body or the under-garments: 0.
- Determinism: bitwise.

**The exception is seam crease count 0. It is not met as written.**

- Read literally (any sewn-seam edge with a dihedral over 20°), the count is 56. Most of these are the round of the sleeve tube at a 1.2 cm mesh, where every edge along the sleeve bends about 20°. That is not a crease.
- Measured as a hinge (the bend across the seam against the cloth's own bend in the same direction 1–4 cm away), the count is 30. Of these:
  - 27 are in the armpit corner of the A-pose (armhole 22, back/side 5);
  - 3 are near the cuff, at 20–22°;
  - CB, shoulder, side/front and sleeve-fore have none.
- The armpit render, looking up from below, shows a smooth web with no pleat and no fold-back.

Spike 1's failure was the CB hinge into the spine groove. It is gone: the worst CB hinge is 3.6°.

The fallback that §6 named became the main path. Blender cloth could not fix the hinge, for the root cause below, so the drape now runs on a deterministic XPBD solver in numpy (`blender/character/suit_xpbd.py`).

## 1. Gate

| Gate | Spike 1 (`122746Z-sim3`) | Spike 2 (`205353Z-t13a-x13`) | |
|---|---|---|---|
| A/B sheet beats lofted, front / ¾ / back | worse | better at all three (§3) | pass |
| Sewn-seam hinge > 20° (hinge measure) | CB, side, sleeve hinges | 30, all in the armpit or near the cuff; CB/shoulder/side-front/sleeve-fore 0 | **not met** (see above) |
| Sewn-seam dihedral > 20° (raw) | n/a | 56 (sleeve tube curvature plus armpit) | **not met** |
| Sewing gap p95 (stage 1, before the weld) | 5.9 mm | 1.61 mm (mean 0.42, max 4.57) | pass |
| Jacket verts inside body or under-garments | 80 | 0 (3 before the final push-out, 12 moved) | pass |
| Strain against the flat pattern, mean / p99 | 9.9 % / 74 % | 2.5 % / 15 % | |
| Determinism (X1, Xw, X2 sha256, two runs) | yes | identical (`x13` against `x13det`) | pass |

Per-seam numbers on the final drape (dihedral in degrees; "hinge" is the excess over the parallel cloth nearby):

| Seam | Edges | Raw > 20° | Raw max | Hinge > 20° | Hinge max | Where |
|---|---|---|---|---|---|---|
| CB | 49 | 0 | 10.5 | 0 | 3.6 | |
| shoulder | 20 | 2 | 26.5 | 0 | 18.2 | the raw 2 are at the neck-point end (free edge) |
| side/front | 70 | 2 | 22.8 | 0 | 12.3 | |
| back/side | 74 | 9 | 37.4 | 5 | 29.6 | back armpit, z 1.33–1.37 |
| armhole | ~66 | 35 | 65.0 | 22 | 59.6 | armpit (front axillary fold, z 1.38) |
| sleeve fore | 58 | 0 | 14.5 | 0 | 6.9 | |
| sleeve hind | 62 | 34 | 33.8 | 3 | 21.9 | the raw count is the tube; the hinges are 5 cm above the cuff |

## 2. Root causes found and fixed

1. **Blender cloth ignores the rest shape key.**
   - Spike 1 draped with the TPS-placed shape (9 % off the flat pattern) as its rest, whatever `rest_shape_key` said.
   - The two-stage weld in Blender therefore bakes the sewing crumple into the rest. The result was 10 % rest strain and a 16–17° mean dihedral inside the panels; lower friction did not help (runs `192737Z-t13a-s1`, `193109Z-t13a-s2fric`).
   - Fix: `suit_xpbd.py`, a small-steps XPBD solver:
     - Gauss–Seidel per greedy colour, vectorised;
     - edge stretch and compression from the flat rest lengths;
     - Bergou isometric bending;
     - sewing with a log-ramped stiffness, then a weld and stage 2 under gravity;
     - SDF collision with friction, soft holds, a left-over-right lap constraint, and vertex self-contact (new).
   - Stage 1 sews the unwelded panels against the flat rest. The weld then averages each seam pair and its rest lengths, and stage 2 drapes the welded mesh, so bending works across every seam.
2. **The back clung to the anatomy.**
   - Fix: a hull tube collider (`suit_hull.py`): a horizontal convex hull per level of torso plus garments, with a vertical upper hull on the back (alpha 0.75).
   - The garment shells go into the body SDF, so the jacket clears the shirt where it is fuller than the body.
3. **The collar frill.** This was two separate bugs:
   - Per-vertex stand clearing ruffled the stand. Fix: one lean angle per column, searched against the shirt, then a moving min and a Gaussian along the neckline.
   - The real frill was the final `clear()`. A stand vertex above the jacket's neck edge took the open edge below it as its nearest jacket point. The test read it as "behind the face" and snapped it 30 mm down onto the edge. Fix: a test counts only when the vertex is over the face (offset mostly along the normal). Layers run outermost first, and a vertex that is outside the jacket is done.
4. **Gathers in the jacket back neck.** `neck_scale` 1.15 was spike 1's compensation for Blender's placed-shape rest. With flat rest lengths it put 2 cm of gathers into the back neck. It is now 1.0 for the XPBD path.
5. **The underarm sliver.**
   - The back/side seam met the armhole where the armhole was vertical, so it was tangent to it. The side panel had a 12° spike at the top.
   - The back now takes 18 % of the armhole bottom, and the seam leaves square to it. The corners are 91.9° + 90.2°, against 175.5° + 12.7° before.
   - Uniform Catmull–Rom also looped at short seam-top spans (a 0.04 cm switch-back at the side/front seam). Centripetal Catmull–Rom fixes it: that corner sum went from 191.6° to 182.6°.
6. **Cuff kinks.** The two straight cuff pieces met the seams at 200.5° (fore) and 170.0° (hind). The cuff is now one sinusoid round the arm, at 183° and 176° (the residual is the seam sampling).
7. **Sleeve-head ease.** The head ease was spread evenly round the armhole. It now goes over the crown, and the underarm (back pitch to front pitch) is sewn 1:1, as a tailor sews it.
8. **Fold-backs in the elbow crook.** There were 22 edges over 120° and a visible lip with back faces showing. Three changes, all needed:
   - the sleeve is cut for a 25° bend (crook −2.4 cm, elbow point +2.4 cm, the same map on both pieces so the seams still match);
   - the sleeve bending stiffness is 6e-5 (wool and lining together), against 2e-5 for the body;
   - the mesh is 1.2 cm instead of 1.6 cm.

   The crook now has 0 fold-backs, and the render shows two soft diagonal folds. Vertex self-contact (10 mm radius) is on as a guard. On its own it did not change the fold count.
9. **A crevice vertex.** A vertex where the shirt goes into the waistband was pushed out of one layer into the other. The push-out now ends by marching such a vertex out along the cloth normal.
10. **The rever frame.** The edge frame took its normal from the nearest face, and a pinch at CB flipped it. It is now a 2 cm Gaussian-averaged surface normal.

## 3. Pictures

All pictures are in `data/build/t13/gate/phaseA/`:

- `ab_sheet.png`: lofted on the left, pattern on the right; rows are front, ¾, profile and back.
- `closeup_sheet.png`
- `pattern_close_{34,back,profile,armpit,cuff,underarm_f,underarm_b}.png`
- `spike1_ab_sheet.png`, for reference.

What I see at 100 %:

- **Front.** The fronts close at the one button, with a clean V above it. The cutaway skirt opens below. The shoulder line is square on the pad, and the sleeves hang with the shirt cuff showing. The lofted jacket's pockets are not modelled yet (phase B item 1).
- **¾ close.**
  - The lapel rolls from the break, and the roll line is soft rather than pressed.
  - The notch and gorge read, and the collar end sits on the lapel.
  - The lapel edge has thickness.
  - At the side neck on the far side, the collar's fall edge has a small pucker (open).
- **Back.**
  - The collar sits round the neck with no frill.
  - The back is smooth from the collar to the hem, and the waist suppression shows.
  - There is a slight fullness just below the collar at CB.
  - Seat and blades do not show.
- **Profile.** The back skirt drops straight from the blades. The jacket reads slightly tubular, with little hollow at the small of the back (open). The sleeve pitch is forward.
- **Armpit, from below.** A smooth web between sleeve and side, with no pleat.
- **Cuff from behind.** A clean hind seam and a level cuff.

## 4. Rever (modelled collar and lapel)

- Built in an (s, q) chart on the draped free edge (back neck, then gorge, then the roll edge). The sheet runs stand, then a roll (a half circle), then a fall laid over the jacket.
- Meshed by CDT, Taubin-relaxed, cleared and thickened: 4,444 verts, 8,242 faces, built in 0.8 s.
- Penetration by the nearest-face rule is 59 sheet vertices. A second reading casts a ray from the vertex away from the body. Of the 59:
  - 11 are under a garment: all on the attachment line at the side neck, at 0.5–0.7 mm;
  - the other 48 are on the CB fall edge, beside the shirt collar's folded edge. The nearest-face rule misreads them, and the renders confirm they are outside.

## 5. Cost and size

| | |
|---|---|
| Build | SDF 8.5 s, stage 1 75.6 s, stage 2 49.4 s, push-out 1.0 s, rever 0.8 s (numpy, `-t 4`, `nice 10`) |
| Mesh | jacket body 9,342 verts / 17,292 tris; rever 8,472 tris; 25,764 in all (sim mesh; LOD0/1/2 in phase B item 1) |

## 6. Open (carried into phase B)

- The armpit hinges in the A-pose (27 edges, up to 60°). Re-check them in the bent and down-arm poses at item 6/7. Real jackets fold here too.
- The collar fall-edge pucker at the side neck (s about 13–19 cm, where the stand dies away).
- The neck-point corner is 145° + 111° = 256°: the back neck meets the shoulder obliquely. The collar hides it, but a tailor would true it. That needs a back-neck rise the body barely has (nape 1.586, neck point 1.582).
- The profile reads slightly tubular; try more CB shaping at the small of the back.
- The bent pose was not run (optional in §6).

## 7. Reproduce

```
bench/m1/v4/suit_spike.sh --base 20261014T184620Z-t12-b2 <label> -- --v2                           # full run, about 6 min
bench/m1/v4/suit_spike.sh --base 20261014T184620Z-t12-b2 <label> -- --v2 --from-run <run dir>      # rever + renders only
bench/m1/v4/suit_spike.sh --base 20261014T184620Z-t12-b2 <label> -- --v2 --opts @opts.json         # overrides from a file
```

Run directories, all under `data/build/suit_spike/`:

- `20261014T205353Z-t13a-x13`: the drape.
- `20261014T210204Z-t13a-r16`: the renders.
- `20261014T210756Z-t13a-r19`: the final stats.
- `20261014T2*-t13a-x13det`: the determinism twin.

Earlier iterations are `t13a-x1` … `x12` and `r1` … `r18`.
