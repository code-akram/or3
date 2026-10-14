# T7b: calm eyes, the teal back-face bug, a skull vault (m1 v4)

_2026-10-14. Follow-up to `bench/m1/v4/t7-head.md`._

Before is T7's last build, `20261014T122918Z-t7-v5`. After is `20261014T134936Z-t7b-v3`. Both
are under `data/build/lookdev/` and both built with `bench/m1/variants/direction.json`.

## 1. Teal crescents and specks: root cause

Teal crescents showed under both irises and specks showed at the alae. They appeared in the
engine only, never in EEVEE.

**Viewer cause.** These were back-facing skin fragments, shaded with an unflipped normal.

- In three.js TSL, `normalView` is flipped on back faces, but `normalViewGeometry` is not.
- The skin shader blurs the normal per channel. It mixes `normalView` toward the geometric
  normal by `[0.7, 0.35, 0.2]` for R, G and B.
- On a back face, red is mostly the unflipped geometric normal, so its N·L inverts and goes
  dark. Green and blue stay mostly on the flipped normal and stay lit.
- The fragment therefore reads green-blue, which is teal.
- EEVEE flips both normals, so the same mesh looked right there.

**Viewer fix** (`web/src/character/materials/index.ts`):

- Define `geometryNormal = normalViewGeometry * faceDirection` and use it everywhere the
  geometric normal is read: the skin blur, the curvature `fwidth`, and the cornea `Ng` in
  both direct-light paths.
- Proof on the same GLB (t7-v5), viewer before and after:
  `data/build/lookdev/t7b-compare/teal_viewer_ab_same_glb.png`. Both crops are also in
  `data/build/lookdev/20261014T150000Z-t7b-viewer-ab/`.

**Geometry cause.** The back faces were real folds, and the viewer only exposed them.

- **Lower lid.** The infraorbital socket push folded the lower-lid skin into the globe.
- **Alae.** After the identity wrap, the nasal cavity walls poked out through the alar groove.

**Geometry fixes.** All four ship, and each is described in section 3:

- the socket globe guard;
- the cavity follow;
- the shipped globes;
- the lid-lining seat.

**Result.** I counted back-facing skin pixels in a front ray map of the face. The count went
from 1450 on t7-v5 to 7 on t7b-v3.

## 2. Calm eyes

### Aperture target: 8.5–9.5 mm

The target is a calm, slightly hooded adult male eye:

- the upper lid covers 1.5–2.5 mm of the iris top;
- the lower lid covers 0.5–1.0 mm of the iris bottom;
- so no sclera shows above or below the iris.

The iris diameter is 11.8 mm (r 5.9). That gives an aperture of 11.8 − (1.5..2.5) − (0.5..1.0)
= 8.3–9.8 mm, with MRD1 3.4–4.4 mm and MRD2 4.9–5.4 mm. Adult male norms sit around MRD1 ≈ 4,
MRD2 ≈ 5 and a fissure of 9–10 mm, and a hooded eye sits at the low end. The `head_measure`
range is `eye_aperture_mm: (8.5, 9.5)`, replacing `(9.5, 11.0)`.

The eye block now targets both lids:

- `upper_over_iris_mm` changes from 1.5 to 2.0.
- `lower_over_iris_mm: 0.75` is new and replaces `aperture_mm`.

### Why the left aperture swung 8–12 mm, and the new measure

There were four causes:

1. **Coarse eye proxy.** The measure ray-cast a 48-vertex polyhedral eye proxy.
2. **Mismatched spheres.** The upper lid sat almost tangent to the globe, within 0–0.3 mm.
   The measure used the proxy sphere (r 12.2 mm), but the lid loop used the helper sphere
   (r 12.0 mm). A 0.2 mm difference flipped whole rows between open and closed.
3. **Flood leak.** The open region's flood fill leaked into the slit under the lower lid.
4. **Eye out of place.** The shipped eye is a back-half fit, and it sat 0.86 mm forward of the
   globe the lids were shaped on.

`head_measure._aperture` now works like this:

- It ray-casts the analytic sphere, not a mesh.
- A ray counts as open only if the skin hit lies more than 0.5 mm in front of the sphere hit.
  Lid skin up to 0.5 mm inside the globe still counts as lid.
- From the pupil column it walks outward. In each column it keeps the contiguous open run
  that overlaps the neighbour's run, so it cannot jump into a slit.
- The top and bottom margins are medians over the columns within ±0.75 mm of the pupil.
- The canthi come from the extreme columns.
- `measure` and `measure_live` measure against the globes actually shipped.
- One sphere fit (`eye_sphere`, a back-half fit) is used everywhere.

### Lid margins (dense mesh, relative to the eye centre)

Upper and lower values are the lid margin heights. Covered is how much of the iris (r 5.9 mm)
the lid hides.

| Eye | Upper | Covered top | Lower | Covered bottom |
|---|---|---|---|---|
| t7-v5 L | +5.60 | 0.30 | −6.05 | **−0.15** (sclera shows) |
| t7-v5 R | +4.75 | 1.15 | −5.53 | 0.37 |
| t7b-v3 L | +3.89 | 2.01 | −5.06 | 0.84 |
| t7b-v3 R | +3.73 | 2.17 | −4.83 | 1.07 |

The right lower lid covers 1.07 mm, just past the 1.0 mm upper bound. The measured aperture is
9.0 / 9.0 mm, left / right.

## 3. Geometry changes (`head_sculpt.py`, `head_measure.py`, `eyes_hq.py`, `author_public.py`)

- **Socket globe guard.**
  - The socket field's backward push is soft-clamped so the skin stays at least `LID_MM` =
    1.5 mm in front of the globe. The clamp uses logaddexp with k = 0.5 mm.
  - At 1.0 mm the fold came back.
- **Cavity follow** (`author_public.clean_delta`).
  - Nasal-cavity vertices within 25 mm of the nostril landmarks, with an inward normal, take
    the Gaussian-weighted delta (σ 2 mm) of the outer skin in front of them.
  - The cavity now moves with the ala instead of poking through it.
- **Shipped globes.**
  - `eyes_hq` used to seat the eyes on its own back-half sphere fit, which sat 0.86 mm forward
    of the globe the lids were sculpted against.
  - It now ships the sculpt layer's globes. `head_sculpt.shipped_spheres` uses them wherever
    they lie within 4 mm of the fit.
  - The measure and the eyes now agree.
- **Lid-lining seat.**
  - The dense pass moves the lid's inner lining onto the globe surface plus 0.2 mm.
  - It acts on inward-facing verts between R + 0.2 mm and R + 2.5 mm, in front of the eye
    centre.
  - This removed the last back faces under the lower lid.

## 4. Skull vault

There are new fields in `head_sculpt.DEFAULTS`. They are anchored by `vault_frame`, which uses
the ear mid-height, the ear front and the vertex.

| Field | Amount | Purpose |
|---|---|---|
| `crown` | −4.0 mm, r 32 | flatter crown |
| `parietal` | +5.0 mm, r 28 | parietal eminences; widens the back view into a pentagon |
| `temporal_fossa` | −3.5 mm ridge band | flattens below the temporal line (5-point arc) |
| `occiput` | +4.5 mm, r 22 | occipital bun at opisthocranion (ear height + 0.28 H) |
| `nuchal` | −5.5 mm ridge | nuchal shelf under the inion (ear height + 0.08 H) |

**Results:**

- The back view reads as a skull: a pentagonal outline, a parietal shelf, and an occipital
  bun over a nuchal shelf.
- The crown is about 2.6 mm lower.
- The occiput is 3.5 mm further back.
- Width at the plane behind the ear:
  - 80 mm above the ear centre: 65.6 → 67.5 mm;
  - 100 mm above the ear centre: 57.1 → 61.2 mm.
- The temporal fossa effect is modest.

**Scalp cap fit is unchanged:**

- cap median 2.0 mm off the skin;
- 0 cap verts more than 2 mm inside;
- 1160 hair-card verts more than 2 mm inside, against 1145 before.

**Caveat:** v3 was built before T8's hair v4 merged. The T8 groom grows from the body's scalp
region at build time, so it should follow the vault. A merged build has not been run.

## 5. identity.sh rerun and retune

`bench/m1/identity.sh` ran once on the new base, with `IDENTITY_OUT=data/build/identity/v2`.
I wrote to v2 so that T8's in-flight builds kept the old files.

- It changed no tracked output.
- Landmarks moved against the old embedding by: median 0.63 mm, p90 1.91 mm, max 7.66 mm.
- The public delta was rewrapped, and the landmark rms went from 3.58 to 2.35 mm.
- `direction.json` now points the identity and sculpt embeddings at `v2/`.

The new delta retruded the menton by about 5 mm. That pushed the gonial angle to 121.9° and
the nose hump to 2.72. The retune is in `direction.json` `head.sculpt`:

- `gonion` +12.5 mm;
- `nasal` 0;
- `socket.lower_mm` −5.5.

Shipping the helper globes also put the eye 0.86 mm deeper. Two more settings bring the orbit
recess back mid-range:

- `eyes.forward_mm` 1.8;
- `brow` −2.6.

## 6. Metrics, before and after

The spec is 0 out in both builds.

| Measure | Range | t7-v5 | t7b-v3 |
|---|---|---|---|
| eye aperture mm (L / R) | 8.5–9.5 (was 9.5–11) | 10.4 (10.75 / 10.0) | **9.0 (9.0 / 9.0)** |
| canthal tilt ° | 2–4 | 2.72 | 3.14 |
| orbit recess mm (L / R) | 2–3 | 2.92 (2.48 / 3.35) | 2.38 (2.10 / 2.67) |
| brow overhang mm | ≥ 8 | 10.8 | 9.1 |
| forehead behind brow mm | ≥ 3 | 6.79 | 6.85 |
| gonial ° (L / R) | 115–120 | 118.7 (120.6 / 116.9) | 119.7 (119.4 / 119.9) |
| nose hump | | 2.50 | 2.45 |
| bizygomatic | | 0.142 | 0.142 |
| lower-face index | | 0.845 | 0.857 |
| jaw : cheek | | 0.870 | 0.875 |
| back-facing skin px (front ray map) | | 1450 | 7 |
| ArcFace cosine vs ref, EEVEE closeup | ≤ 0.25 | 0.045 | 0.036 |
| ArcFace cosine vs ref, engine closeup | ≤ 0.25 | 0.017 | 0.051 |
| glTF errors | 0 | 0 | 0 |
| total tris | | 126631 | 126755 |
| jacket tris | ≤ 18000 | 17590 | 17747 |

All other meshes are within the `suit.py` budgets, and the bones (83) and weights per vertex (4)
are unchanged.

**Notes on the metrics:**

- The jacket's 17747 is the figure that `bench/m1/v2/suit.md` records.
- The brow overhang is still above the gate of 8, but it is further from the look-spec aim of 12.
- ArcFace was run in private and printed one scalar per image; it wrote nothing.

## Fan build (numbers only)

Build: `private/likeness/lookdev/20261014T140247Z-t7b-fan1`, with the default config plus
`fan.json` and no `direction.json`, as in T7.

- The shared-layer changes reach it: the vault, the socket guard, the shipped globes and the
  lid-lining seat.
- The lid-target loop is still off on the fan build.

The gate is the refboard ratios against the private reference, tolerance ±3 %, measured on a
clay front view.

- **Before** is T7's `20261014T122817Z-t7-fan3`. I re-measured it with the same script, and it
  reproduced T7's numbers exactly.
- **After** is `20261014T140247Z-t7b-fan1`.

| Ratio | T7 fan3 | T7b fan1 |
|---|---|---|
| bizygomatic | −1.4 % | −0.4 % |
| bigonial | −2.2 % | −1.3 % |
| mouth width | −1.5 % | −2.4 % |
| nose length | −2.8 % | −1.9 % |
| alar width | **−3.0 %** | **−4.0 %** |
| brow to pupil | +1.6 % | +2.5 % |
| palpebral half-width | **+9.0 %** | **+9.8 %** |
| lower face | −0.1 % | +0.0 % |

**Reading the table:**

- **Alar width did not change on the mesh.** The two fan builds' skin is bit-identical within
  30 mm of the nose tip (0.000 mm max), and the cavity follow touches only the public delta.
  The −1 point comes from MediaPipe's whole-face fit: its alar landmarks shift because the eye
  region changed.
- **The geometry change is all in the eyes and the vault.** Over the face, the skin moved by
  p95 0.45 mm and at most 2.4 mm.
- **Palpebral half-width** was already out (+6.7 % on main). It is now 0.8 points further out.
- **The fan gate still needs its own fix.** As T7 said, that means a fan-only `eyes` override,
  or refitting the fan delta on the sculpted base. With lids now targeted on the public face, a
  fan-only lid target is the obvious next step.

## Images (all public, under `data/build/lookdev/`)

**In `t7b-compare/`:**

- `closeup_before_after.png`: EEVEE closeup, t7-v5 (top) vs t7b-v3 (bottom).
- `engine_closeup_before_after.png` and `engine_face_t7v5_vs_t7b.png`: engine (WebGPU) closeup,
  before and after. The teal is gone.
- `teal_viewer_ab_same_glb.png`: the viewer fix alone, on the same GLB.
- `clay_strip_before_after.png`: bald clay strip.
- `clay_turntable_before_after.png`: eight-view bald turntable.
- `clay_vault_before_after.png`: profile, back, back-¾ and top of the vault.

**Full runs:**

- `20261014T134936Z-t7b-v3/`: the full after run. It includes `game_*.png` and `sheet.png`.

## Left

- **Fan likeness gate: two ratios are out.**
  - Palpebral half-width is +9.8 %. It was already out on main.
  - Alar width is −4.0 %. This comes from the landmarker; the mesh is unchanged.
  - The fix is fan-side and is not done.
- **Two views of the vault have not been checked.**
  - A build with T8's hair v4 merged has not been run against the new vault.
  - The vault has had no engine view.
- **The right lower lid** covers 1.07 mm, just past the 1.0 mm bound. The right orbit recess is
  2.67 against 2.10 on the left.
- **7 back-facing pixels remain** in the front ray map. With the viewer fix they shade
  correctly, but the fold behind them still exists.
- **`direction.json` depends on the v2 identity files.** It now points at
  `data/build/identity/v2/`, and those files exist only in the main checkout's `data/`. Promote
  them to the default paths once T8 and T9 no longer need the old files.
- **`bench/m1/engine_shots.sh` hardcodes port 8791** and has no `--port` passthrough. I called
  `engine_shots.mjs` directly.
