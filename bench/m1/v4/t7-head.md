# T7: head structure and an original public identity (m1 v4)

_2026-10-14. Track T7 of `bench/m1/v4/checkpoint-1.md` §3 (fable_review.md §3.4, §4.1, §4.7)._

The egg-shaped head now has bony structure. The public face is no longer near an actor. It is an
original face, authored by hand in a statistical shape space, and both builds share one sculpt
layer.

Build order in `head.edit_base`:

1. targets
2. `head_shape`
3. `head_forms`
4. **`head_layer`**: the identity delta. The public face, or the private fan delta, which replaces it.
5. **`head_sculpt`**: the landmark-anchored bony fields and the eye block.

`head_refine` then adds the crisp band of the same fields on the dense face.

## Prior and licence

- **FLAME 2023 Open (CC BY 4.0): not used.** It needs the flame.is.tue.mpg.de login. `download.php` returns the login page, and I do not handle credentials.
- **FLAME 2020: not used.** The private fan fit uses it, but it is academic-only, so it must not shape a public mesh.
- **Used: ICT-FaceKit (USC ICT, MIT).** It is fetched without a login by `pipeline/likeness/fetch_ict.sh`, pinned to commit `da5f95a6`, into `data/raw/ict-facekit/` (untrusted data, parsed with `python -I`).
  - Files: the generic neutral mesh and 100 identity PCA shapes.
  - Only the shape space is used. No ICT topology, texture or expression ships.
- **Provenance:** `provenance/mesh.jsonl` id `ict:facekit/da5f95a6`, with sha256 of the 104-file `SHA256SUMS` manifest (audit: 0 errors).
- **`CREDITS.md`** (new file) has the line: "ICT-FaceKit, USC Institute for Creative Technologies, MIT licence (identity shape coefficients only)".

## What was built

| Piece | File |
|---|---|
| ICT loader (cm, y-up → Blender m, z-up) | `pipeline/likeness/ict.py` |
| Public face author: `features` (per-component effect table and a least-norm drafting solve), `mesh`, `base-mesh`, `embed` (MediaPipe multi-view triangulation onto a mesh), `wrap` (wrap.py + clean-up: seam blend, rigid ears, spike removal, relaxed alar base) | `pipeline/likeness/author_public.py` → `data/build/identity/public_face.npz` (delta, base, coeffs, prior) |
| Coefficients: 12 components, all within ±1.5σ (cap 2.5σ), chosen from the effect table toward the brief (strong supraorbital, wide zygomatic over a square mandible, long lower face, thin lips, ~45). No photo or person as input. | `bench/m1/variants/public_identity.json` |
| Workbench views of any mesh (for the landmarker) | `pipeline/likeness/mesh_views.py` |
| Embedding prep, one run per base-mesh change | `bench/m1/identity.sh` |
| `head_fan.py` → **`head_layer.py`**. `head.identity` is public, with auto-rebuild on base drift or a coefficient change. A `fan` block replaces it (key `fan_face` vs `identity_face`). | `blender/character/head_layer.py` |
| Sculpt layer: brow ridge, orbital socket (upper and infraorbital), zygoma to the ear with a submalar plane break, mandibular border dropped to the true lower border with a submandibular recess, gonion, ramus and retromandibular, nasal bones and dorsum sides, mentalis/chin, temporal line and hollow. Anchors are MediaPipe landmarks re-evaluated after the identity delta. Two bands: soft on the base mesh, sharp minus soft on the dense face after `replanarise`. | `blender/character/head_sculpt.py` |
| Eye block: globe 12.0 mm (apex kept, then 0.6 mm forward), lids re-seated, then an iterative loop to the targets (upper lid 1.5 mm over a 5.9 mm iris, aperture, lateral canthus tilt). A dense-mesh clearance stops the eyeball showing through the lids. | `head_sculpt.eye_block`, `head_sculpt.refine` |
| New measures, plus the redefined `brow_overhang` (rim minus cornea apex) | `blender/character/head_measure.py` |
| `compare`: ArcFace w600k_r50 cosine, prints one number, writes nothing | `pipeline/likeness/identity_codes.py compare` |
| Bald clay strip and turntable from a kept public build; quick head loop | `bench/m1/head_quick.py --blend RUN/character.blend --turntable` |

**Config:**

- `config.py`: `head.identity: None`, and `head.sculpt: {}` (on by default, so the fan build shares the layer).
- `direction.json`:
  - adds `head.identity` and `head.sculpt`;
  - `refine.sculpt.lid_margin_mm` 1.5;
  - `refine.eyes` iris 11.8 / converge 1.2 m;
  - mouth stack halved: horiz-decr, upperlip-height-decr and cupidsbow-incr at 0.5, the rest dropped.
- `replanarise` 1.0 / `plane_sharp` 3.0 were already the defaults.

### How the new measures are defined

All are on the still-nude base mesh at the build's measure step; each is the mean of both sides, with per-side values in `*_lr`.

- **`brow_overhang`**: the most forward skin 6–25 mm above the eye centre on the mid-pupil line, ahead of the cornea apex.
- **`forehead_behind_brow_mm`**: the profile 25 mm above that rim point, measured behind it.
- **`orbit_recess_mm`**: the cornea apex behind the rim line, taken at apex height. The rim line joins that supraorbital point to the infraorbital point (most forward skin 10–16 mm below the eye centre).
- **`eye_aperture_mm` and `canthal_tilt_deg`**: front rays that reach the eye before the skin. The aperture is the column through the pupil; the tilt runs from the medial to the lateral extreme column.
- **`gonial_angle_deg`**:
  - The lower border of the mandible is traced as an occluding contour seen from 45° above-lateral.
  - Gonion is the border point farthest behind-below the menton–condyle chord.
  - The angle is between the menton tangent to the border and the line from gonion to condyle (front of the ear at mid height).

## Metrics

Before is the main direction build (`t7-base` config: `head_quick` q0, re-measured with this code). After is `20261014T115239Z-t7-v4`. The full lookdev reports `spec ... (0 out)`.

| Measure | Target | Before (main) | After | L / R after |
|---|---|---|---|---|
| gonial angle | 115–120° | 112.5 | **118.7** | 120.6 / 116.9 |
| eye aperture | 9.5–11 mm | 6.4 | **10.4** | 10.75 / 10.0 |
| canthal tilt | +2–4° | 5.4 | **2.7** | 2.5 / 2.9 |
| orbit recess | 2–3 mm | 14.3 | **2.9** | 2.5 / 3.35 |
| brow overhang | ≥ 8 mm | 21.2 | **10.8** | |
| forehead behind brow | ≥ 3 mm | 13.7 | **6.8** | 6.5 / 7.1 |
| bigonial / bizygomatic | 0.84–0.88 | 0.865 | **0.870** | |
| bizygomatic | 0.140 ± 0.006 m | 0.135 | 0.142 | |
| lower-face index | 0.88 ± 0.04 | 0.898 | 0.845 | |
| globe radius | 12 mm | 15.0 | 12.2 | |
| read40 eye band (pass ≥ 75 %) | | 60 % | 71 % | |
| ArcFace cosine vs the private reference median | ≤ 0.25 | 0.101 (EEVEE closeup), 0.064 (engine) | **0.049** (EEVEE closeup), **0.005** (engine) | |

Notes on the "before" column:

- The before brow (21 mm) passed the old test because of a forehead bulge.
- Before, the recess was 14 mm because the eye sat in a deep, lidded socket under that bulge.
- Before, the gonial angle passed 115 only because the old jaw border was low and flat.

Other build facts:

- GLB has 126.9k tris, 0 validator errors.
- The refine crisp band moves up to 1.49 mm on 1,266 verts.
- The dense eye clearance pushed 144 verts.
- The public delta was rebuilt automatically (9 s wrap): 433 shared landmarks, landmark rms 3.69 → 2.25 mm.

ArcFace was run in private (the mica venv: `identity_codes.py compare --auto` against `private/likeness/ref`). It printed one scalar per image and wrote nothing.

## Fan build (numbers only)

FANGATE

## Images (all public, under `data/build/lookdev/`)

- `t7-compare/clay_strip_before_after.png`: bald clay strip, main (top) vs T7 (bottom). Shows front, raking key, ¾, profile and low ¾ for the jaw.
- `t7-compare/clay_turntable_before_after.png`: eight-view bald turntable, main vs T7.
- `t7-compare/closeup_before_after.png`: EEVEE closeup.
- `t7-compare/engine_closeup_before_after.png`: engine closeup. "Before" is `20261014T103057Z-t6-after`, the main face; the `t7-base` engine shots failed twice because port 8791 was busy with another browser.
- `20261014T115239Z-t7-v4/sheet.png`: the lookdev sheet with the engine row. `game_closeup.png` and `game_portrait.png` are in the same dir.
- `compare-20261014T101355Z-t7-base--20261014T115239Z-t7-v4/sheet.png`: lookdev compare.

The brow shelf, the zygomatic plane break (cheekbone corner over a submalar plane) and the jaw corner all read in the clay profile and low ¾.

## What still reads wrong

1. **The cranium is still the MPFB egg from behind.** The back views of the turntable are unchanged. T7 built the face skeleton (brow, orbit, zygoma, mandible), not the vault: no parietal or occipital shaping and no temporal-fossa flattening beyond the temporal line.
2. **Staring eyes.** A 10 mm aperture on a 12 mm globe, with the lower lid at the limbus, reads startled next to the old sleepy 6.4 mm fissure. Two things would soften it:
   - an aperture nearer 9.5;
   - a lower lid covering about 0.8 mm of iris.

   The aperture measure itself is fragile. The left eye proxy sits differently from its helper sphere, and over the tuning runs its measured aperture swung between 8.25 and 11.75 mm for small edits while the right stayed at 10.0. The loop drives the helper, not the fitted eye.
3. **Teal crescents in the engine** under both irises, and small specks at the alar base. They do not appear in EEVEE.
   - The specks came from the identity wrap pushing the alar-base skin behind the nostril's inner wall. The relax step around the alar base removed most of that.
   - The crescents come from the newly exposed lower-lid region. I could not trace which engine material draws teal. I checked the eye, skin, lash and beard textures and none contain teal. This needs the T6 viewer owner.
4. **The gonial angle is a soft-tissue construction, not a cephalometric one.**
   - Hitting 115–120 needed the mandibular border dropped 16 mm below MediaPipe's frontal jaw contour at the corner, plus a 7.5 mm gonion push. The ICT components move a 3-point gonial angle only about 1° per σ.
   - Per side, it is 120.6 / 116.9.
   - The measure depends on the occluding contour (the first overhang below the cheek). A softer jaw that does not overhang the neck would read as no border.
5. **The orbit recess is right at the edge.** Its mean is 2.9, but the right eye is 3.35.
   - It is limited by the 12 mm globe: the infraorbital skin cannot go further back without the eyeball showing through.
   - Getting it into range also took the brow field to −0.5 mm, a slight push back. Brow overhang is 10.8 mm, against the look-spec §2.1 aim of 12. The checkpoint gate is ≥ 8.
6. **No mid-frequency normal-map component.** The spec's "(b) a mid-frequency normal into `skin_head_normal`" would go through `skin_tex.py`, which T6 owns. The crisp band is geometry on the dense face instead.
7. **The lower-face index (0.845) is at the low end of 0.88 ± 0.04.** The authored face is long but also wider at the cheeks (bizygomatic 142 mm).
8. **The fan face's base drifted.** See the fan section.

## Commits (branch `worktree-agent-ab7eb3a69fdee3a7c`)

COMMITS
