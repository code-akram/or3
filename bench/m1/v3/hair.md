# m1 v3 Track B: scalp hair for the fan build

_2026-10-13. Brief: `bench/m1/v3/BRIEF.md`. The likeness-specific hair values, the reference notes and the evidence verdicts live in `private/likeness/` (`hair_fan.json`, `hair_report.md`); this file covers the public, generic code only._

## What changed in the code (generic, default off)

The v2 groom (`hair_groom.py`) combs every root back from an off-centre part. v3 adds a second style family, a **hanging part-comb**, plus the controls it needs. Every new key defaults to the v2 behaviour, so the public build (no private input) still produces the v2 hair. Checked: `hairB-public` gives 20,832 tris, width/skull 1.253, temple break 36 / 37 mm, against v2 round 3's 20,816 / 1.249 / 36 / 36.

| Key (`hair.groom`) | Default | What it does |
|---|---|---|
| `comb.mode` | `"back"` | `"part"`: roots comb sideways off the part (`side`, `back`, `drop`). Forward-facing roots comb `forward` and hold up (`front_hold`, `front_side_cut`), and the sideways push starts at `part_ramp` × full at the part line. |
| `comb.fall_az_deg`, `fall_above_ear_m` | – | Gravity starts past the temple (by \|azimuth\|) and below the upper skull. |
| `comb.hug`, `hug_above_ear_m` | 0 | Strands are pulled back onto the skull while above the ear. Without it the sideways strands leave the curved skull in straight lines and splay out (the "spider" look). |
| `comb.free_fall_m` | None | Gravity ramps to full by strand length everywhere. Without it, strands combed forward off the face never reach the temple azimuth and run away horizontally. |
| `tuck.left / right` | 1.0 / 1.0 | Share of roots per side that steer behind the ear. The rest drape over it, kept off by the ear collider (`Strand.tuck`, `Strand.hug_above_z` in `hair_clumps.march`). No random draw at 1.0, so the v2 grooms are bit-identical. |
| `part_density`, `part_back_m` | 0, 0.03 | Extra root density along the part line, so a part reads as a thin line instead of a bald stripe. |
| `part_lift_rise_m` | None | The part lift rises over this length instead of the profile's rise. |
| `shader.coat`, `shader.radial_roughness` | None | Set when the model is `CHIANG` (wet look). Huang has neither. |
| `front_fall[].gravity` | 0.95 | Per-fall gravity (diagonal ropes across the forehead, strands stuck to the skin). |
| `game.ear_test` | `"box"` | Card ear test. `"box"` checks the card edges in the ear's box (tucked styles). `"ellipsoid"` checks only a centreline inside the ear, so hair can drape over the ear. `None` disables it. |
| `game.front_lock.max_halfwidth_m` (`CARDS`) | 7 mm | Caps the front-fall lock card, which otherwise became a wide ribbon off the face. |

`bench/m1/hair_inspect.py` gains `--hide-obj a,b`, which hides objects from the render. It drives the gate render, the same portrait with and without the groom (`--hide-obj hair_groom,hair_groom_scalp`).

## Shading note for Track E

On the shadow side the hair picks up the rims' colour (magenta and blue) through the specular R lobe: it is reflection, not diffuse. I A/B'd it on one build with Huang and Chiang, coat 0 to 0.3, radial roughness 0.08 to 0.3, and IOR 1.4 to 1.55. Saturation on the shadow side stays at 0.58 to 0.62 in every case; lower IOR only scales the brightness (about −20 %). The wet look needs a glossy R lobe, so a rim colour that floods less has to come from the rim lights themselves (colour or power).

## Budget

Fan build (`data/build/lookdev/20261013T114304Z-hairB-v3jw2`):
- Hero groom: 60,000 strands + 1,400 vellus, 1.45 M control points.
- Game cards: 341 cards, 13,876 tris (≤ 25k), atlas unchanged. 30 cards dropped by the ear test.
- LOD0: 119,910 tris. Validator: 0 errors.
