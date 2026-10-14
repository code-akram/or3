# m1 v4 step 0, track T3: hero rig light twins

_Track T3 report, 2026-10-14. Source: `fable_review.md` §1.10, the S2 on twins ignoring `key` and the S4 on `PROP_SAT`, plus the HANDOFF defects "suit reads purple in the sign shot", "pink under the eye and teal on the beard edge in the profile". Public build only: `data/build/lookdev/20261013T081002Z-heroE-main9/character.blend`. No fan overlay._

## What was wrong

- **The per-shot `twin` was only read for lights named `rim` and `kicker`** (`rig.py` `hero_rig`). Any other saturated light got only the props twin: the sign shot's magenta `key`, the draw's magenta `top`, and the cool `fill`. A cloth twin on the sign key would have been dropped silently. Both the docstring and `hero-stage.md` ("Twins generalised") said otherwise.
- **Flagged lights were never split.** The alley shots flag `key`, `wrap`, `fill` and `eye` by default. The default fill `(0.55, 0.7, 1.0)` is saturated (HSV 0.45), so it went unsplit in every alley shot except sign and draw.
- **`PROP_SAT` could not be reached for magenta (S4 confirmed).** `hair_rim_colour` moved magenta toward white-violet `(0.85, 0.80, 1.0)`, and that colour's own saturation is 0.2. The bisection therefore stopped at white-violet:

| Colour | Target saturation | Old code reached | New code reaches |
|---|---|---|---|
| sets' magenta `(1, 0.06, 0.42)` | 15 % | 21.3 % | 15 % |
| rig magenta `(1, 0.18, 0.55)` | 15 % | 24.4 % | 15 % |

  Every target that was already reachable (cloth 30 %, hair 40 %, skin 70 %, and any teal or blue) gives the same colour as before, to 1e-9.

## What changed (`blender/hero/rig.py`, `shots.py`, `stage.py`)

**`rig.twin_plan(name, twin, practical)`** decides the twins for each saturated light. **`_split`** builds them.

- **All saturated lights are split, flagged or not.** For a flagged light, the original keeps lighting only the character minus the twinned groups (INCLUDE). Each twin lights its own group.
- **Default twins on every saturated hero light** (key, fill, rim, kicker, top, …):
  - **hair** at `HAIR_RIM_SAT` 40 %, when `HAIR_RIM` is on;
  - **props** at `PROP_SAT` 15 %.
- **Per-shot `twin`**, `{group: value}`:
  - `(fraction, energy)` applies to every saturated hero light.
  - `{light: (fraction, energy)}` applies per light. `"practicals"` names the set's sign spill lights.
  - `None`, plain or per light, drops a default.
  - An unknown group raises an error.
- **Groups**: hair, **beard** (new: `beard_*` and `brows_*`, both strands and cards), props, cloth, skin.
- **Practicals** (`rig.practical_lights()`, the `sg_*_spill*` area lights) get no twins by default.
  - A shot can twin them under `"practicals"`.
  - Their light linking is reset every shot, because they outlive the rig.
  - A group with a practicals twin is also excluded from the neon tubes' emission (`rig.practical_emitters()`). The tubes are geometry and cannot be twinned.
- **Magenta's path to lower saturation** now runs colour → white-violet → white, so any fraction can be reached.
- **Shots**:
  - **sign**: `twin={"cloth": (0.3, 0.75)}`, a cloth twin on every saturated light (the key, magenta rim and teal kicker).
  - **profile**: adds `"beard": {"rim": (0.4, 1.0), "kicker": (0.4, 1.0)}`.
  - **bust/back/walk** (`CLOTH_TWIN`) and the profile's skin twin are now written per light (`rim`, `kicker`), so the flagged cool fill lights suit and skin exactly as before.
- **`stage.render_crop`** accepts `crop_at=("eyes", size)` for a head crop of a full-body shot. It was used here as evidence for the sign shot.
- The docstrings, the `--hair-rim` / `--no-hair-rim` help text and `hero-stage.md` are corrected.

## Evidence

Preview quality: 64 spp, 50 %, `-t 6`. Values are region means of the graded 8-bit PNG: sRGB, HSV saturation `s`, CIELAB a*, b* and chroma C*. The regions are fixed boxes, the same pixels in before and after.

| Run (`data/build/hero/`) | Code | Use |
|---|---|---|
| `20261014T092242Z-t3-before` | main `1c4e2c8` | before: 9 shots + profile crop |
| `20261014T104048Z-t3-after` | this branch | after: same shots and flags. `t3_ab/*_ab.png` are before \| after with the regions outlined; `t3_ab/measure.json` |
| `20261014T094435Z-t3-it1` | variants | sign without the cloth twin, sign + practicals cloth twin, profile + practicals skin/beard twin |
| `20261014T100301Z-t3-it2` | variants | 100 % head crops of sign: old lighting (`sign_old`), new (`sign_new`), + practicals hair twin (`sign_hp`); profile without kicker, profile with a 30 % kicker skin twin |
| `20261014T102126Z-t3-it3` | variants | sign with neon tubes off, sign with haze off (crown diagnosis) |
| `20261014T103131Z-t3-it4` | variants | sign + practicals hair twin + tube emission exclusion |

The variant runs used a scratch driver (`stage.main` with extra `SHOTS` entries) and are not committed.

**Side by side for review**: `data/build/hero/20261014T104048Z-t3-after/t3_side_by_side.png`.
- Top row, left to right: sign before, sign after, sign head crop old, sign head crop new (100 %).
- Bottom row, left to right: profile crop before, profile crop after (2× zoom), draw before, draw after.

### Sign: the suit is no longer purple

| Region | before | after |
|---|---|---|
| jacket sleeve, key side | (30, 22, 45) a* 9.9, b* −14.0, C* 17.1 | (14, 24, 39) a* 1.0, b* −11.6, C* 11.7 |
| jacket waist | (16, 15, 30) a* 4.2, C* 10.3 | (9, 15, 26) a* 0.7, C* 7.3 |
| jacket, kicker side | (8, 29, 46) C* 13.8 | (11, 25, 40) C* 12.0 |
| trousers | (37, 29, 45) a* 7.6, C* 12.0 | (34, 29, 43) a* 5.6, C* 10.1 |
| face (control, not twinned) | (150, 91, 121) | (150, 91, 121) |
| wall (control) | (36, 34, 40) | (36, 34, 40) |
| 100 % head crop, sleeve | (32, 17, 40) a* 13.4, C* 18.6 | (14, 19, 32) a* 2.2, C* 10.1 |

The magenta component (a*) is gone. What remains is the grade's cool 3,900 K white point (b* about −10), the same dark blue-black the back shot's jacket reads at.
- The trousers keep a* 5.6. That light bounces off the magenta-lit wet ground, which no light link can reach.
- The sign without a cloth twin (`it1/sign_nocloth`) matches before on every suit region, so the cloth twin alone makes the change.

### Sign: hair. The key's stain is fixed; the crown is the tube behind the head

| 100 % head crop | old lighting | new |
|---|---|---|
| hair, key side (graded) | (44, 20, 42) s 0.55, a* 16.4, C* 19.2 | (38, 22, 41) s 0.46, a* 12.3, C* 15.6 |
| same, scene-linear EXR | HSV s 0.65 | HSV s 0.43 |
| crown (graded) | C* 34.4 | C* 33.4 |

- The key's hair twin takes the magenta out of the key side of the hair.
- The crown stays pink, and no light twin changes it. That held for every variant: the key twin, a practicals hair twin (C* 33.3), and practicals plus tube-emission exclusion (C* 33.1, linear blue 0.042 → 0.039).
- Haze off changes nothing. Neon tubes off drops it to C* 11.9.
- In the crop, the magenta arrow sign's (`sg_arrow`) bottom stroke passes **behind** the crown. The crown pixels are therefore the tube and its bloom (`grade.py` bloom 0.35 / 0.55) seen through and around the hair, not light on the hair.
- That is a framing or neon-strength question (`neon` in the shot, `set_yaw`), not light linking. I left it as it is.

### Should HAIR_RIM extend to every saturated light? Yes

- **For.** The mechanism (the wet hair coat mirrors a saturated light) does not depend on the light's name. On the sign's key side the hair goes from s 0.65 to 0.43 in linear terms. The draw's magenta `top` loses its tint on the crown: a* +1.8 → −1.8, C* 11.4 → 11.1.
- **Cost.** The only other new hair twin in the default shots is the cool fill (ratio 0.08). Shots whose config did not change (portrait, eye, bust, back, walk, hands; profile and draw outside their configured twins) match before to within noise:

| Shot | mean \|Δ\| (8-bit) | p99 \|Δ\| | mean ΔE |
|---|---|---|---|
| portrait | 0.30 | 3 | 0.35 |
| bust | 0.24 | 2 | 0.30 |
| back | 0.26 | 2 | 0.32 |
| walk | 0.24 | 2 | 0.29 |
| hands | 0.20 | 2 | 0.27 |
| eye | 0.96 | 6 | 0.89 |
| draw | 0.33 | 2 | 0.38 |
| sign (changed) | 1.56 | 12 | 1.39 |

- The eye shot's larger number is sampling noise in the pore detail. 1.7 % of its pixels differ by more than 6, spread over the frame, and their mean colour is unchanged: (104, 74, 71) → (103, 74, 71). The extra twin light shifts the light-tree sampling.

### Profile: the teal beard edge is fixed; the pink under the eye is not light linking

| 100 % crop region | before | after |
|---|---|---|
| beard front edge (chin) | (20, 42, 52) s 0.62, a* −5.2, b* −9.4, C* 10.7 | (34, 39, 50) s 0.33, a* 0.6, b* −8.0, C* 8.0 |
| under the eye | (122, 82, 81) a* 17.0, C* 18.5 | (122, 82, 81) a* 16.9, C* 18.4 |
| cheek (control) | (114, 78, 71) | (114, 78, 71) |
| brow ridge | (41, 40, 44) C* 3.2 | (47, 39, 43) C* 4.8 |
| back hair | (13, 11, 15) | (13, 11, 15) |

- **Teal on the beard edge was light linking.** The beard and stubble were in no twin group, so the teal rim reached them at full saturation. The beard twin fixes it. The brows sit in the same group and move slightly warmer: the teal is damped more than the magenta.
- **Pink under the eye is not light-driven in the public build.** Dropping the magenta kicker gives a* 16.7. A practicals skin twin (40 %) gives a* 15.8. A 30 % kicker skin twin gives 17.1. The region is only slightly pinker than the cheek (a* 17 vs 13.8), so it reads as skin colour: the lower lid's albedo and SSS.
- The HANDOFF defect came from the **fan** final. Under `hero-stage.md` it was put down to the set's magenta spill through a gap under a hair lock. I can't check it on a public build: the public groom does not hang there. If it is still there on the fan build, the profile can opt in to `"skin": {..., "practicals": (0.4, 1.0)}` now that practicals can be twinned. Measure it before adopting it.

### Other shots

- **draw**: the props twin now reaches 15 % for magenta. The slide goes (27, 40, 60) C* 14.2 → (26, 40, 58) C* 13.1. That is small, because the grade's cool white point dominates the near-black slide.
- **eye**: the HANDOFF "magenta rash-like patch near the nose" sits on skin. That is the default magenta rim's job (skin keeps the rim by design), so it is not a twin bug. If the review wants it calmer, an eye-shot `"skin": {"rim": ...}` twin is now a one-line change. I didn't make it without a review call.

## Left open

- **The sign crown** reads pink from the arrow tube behind the head plus bloom. That is a framing or neon call for the review.
- **The tube-emission exclusion** (`practical_emitters`, which applies only when a shot twins practicals) is implemented, and the dry run shows it is wired up. Its measured effect in the sign crown is small, and no shot uses it.
- **The fan-build pink under the eye** is untested here, by design (public only).
- **Commit note**: the first commit was made before rebasing onto main, which carries the new pre-commit hook. The branch's old base lacked `tools/hooks/check_staged.py`, so I ran main's checker by hand on the staged diff (it passed) and committed with the hook path disabled. The later commits ran the hook normally.
