# m1 v4 track T22: hands and neck

_Track T22 report, 2026-10-14. Brief: `checkpoint-3.md` §2.8 and the T22 row in §4. Public build only (`bench/m1/variants/direction.json`), no fan overlay. Engine frames are WebGPU on SwiftShader (headless Chromium, port 8794), like every engine number so far. ArcFace was **not run** here, because its tooling lives under `private/`; see the last section._

**What I see in my own frames at 100 %.**
1. In the Cycles hero-rig hand shots (`gate/cycles_hands_before_after.png`), the back of the hand is now an adult man's:
   - the four extensor tendons fan from the wrist to the knuckles;
   - a dorsal venous arch with two branches sits at the wrist;
   - the metacarpal heads read as a row of separate knuckles rather than one soft pad, and they stay visible in the fist.

   The veins are too regular and slightly graphic: where two branches cross near the cuff the junction reads like a stitched X. The dorsum skin is still clean and young, with no crepe.
2. In the engine, the hand is about 40 px tall at gameplay distance in the 3/4 view. At that size the change is a few tendon highlights on the dorsum (visible at ×3 in `gate/engine_three_quarter_hand_before_after_x3.png`). In the hero closeup the neck is almost the same as before, because it is mostly beard and shadow. **The neck work is a sculpt-level and EEVEE/Cycles-level gain, not an engine-visible one yet.**
3. In clay and in EEVEE (`gate/neck_*`), the sternocleidomastoid now runs as a soft oblique band from behind the ear toward the collar, with a recess in front and behind. The larynx is a faint midline V, mostly under the beard and the tie knot. The clavicle heads are not sculpted: they are under the shirt, where the body is deleted.

## Runs

| | Run dir (`data/build/…`) |
|---|---|
| Before | `lookdev/20261014T184620Z-t12-b2` (T12 final, on main at 1e8b0fd). I did not render into it: engine frames with today's viewer are in `t22/base-engine/`, a dir of my own whose inputs are links into the run. |
| **After (final)** | **`lookdev/20261014T203831Z-t22-a5`** (engine frames inside it) |
| Iterations | `…-t22-a1`, `…-t22-a2`, `…-t22-a3` (what each one taught is below). `a4` was stopped and deleted. |
| Evidence | `t22/{base,a1,a2,a3,a5}-views`, `-twist-l`, `-twist-r`, `-raise` (EEVEE, `bench/m1/hands_neck_views.py`); `t22/{base,a5}-cycles` (Cycles, `hands_render.py`, hero light, 32 spp, in the flock); `t22/{base,a1,a5}-deform` (deform_test); `t22/base_measure_r10.json`, `t22/a5_measure.json` |
| Gate pictures | `t22/gate/` (listed at the end) |

## Gate

| Metric | Target | Before (t12-b2) | **After (t22-a5)** |
|---|---|---|---|
| `hand_width_ratio` (metacarpal breadth without the thumb, at the MCP line, over wrist-to-middle-tip length) | ≈ 0.55 | 0.478 (96.9 / 202.7 mm) | **0.484** (98.1 / 202.7 mm) ✗ (see below) |
| Same ratio, breadth including the thumb at the thumb MCP | (info) | 0.520 | **0.528** |
| Dorsum relief p99: quadric-fit residual over a 10 mm window, dorsum wrist to MCP | ≥ 0.8 mm | 0.453 mm (p50 0.044) | **0.607 mm** (p50 0.128, p95 0.436) ✗ |
| New pose-test failures (deform_test pokes per pose, 11 poses) | none | low_ready 34, crouch 22, knee_up 6, arm_raise 2, hero 1, head_turn 1, others 0 | **identical in every pose** ✓ |
| Fist knuckle skin height over the joint (twist pose, `corr_fist` on), MCP / PIP, mm | (info: rest height is 6.9–7.9 / 5.6–6.0) | **4.2–4.7 / 3.2–4.0** (the old corrective *lowered* the corner below LBS's 5.0–5.2) | **5.3–6.5 / 4.5–5.4** (LBS alone 4.5–4.8 / 3.3–3.7) |
| Wrist correctives in the twist pose (pronated fist with 40° flexion / extension) | drive | none existed | `corr_wrist_flex_l` 0.78, `corr_wrist_ext_r` 0.74 |
| Head measures (`spec … out`), landmarks, head-sculpt stats | all in range / unchanged | 0 out | **0 out**; `spec_landmarks`, `spec_checks` and `head_sculpt` stats are byte-identical ✓ |
| ArcFace (offline scalar) | ≤ 0.25 | 0.034 (T12) | **not run** (private tooling). Face-unchanged evidence is below. |
| glTF validator | 0 errors | 0 | **0** ✓ |
| LOD0 triangles | ≤ 170k | 133,683 | **141,697** (+8,014: body +7,974, nails +40) ✓ |
| Containment / provenance / web build | pass | | 69/69; audit 0 errors, 0 warnings; `npm run build` ok ✓ |

**Why `hand_width_ratio` is not 0.55, and why I did not force it.**
- On the ISO 7250 definition (hand breadth at the metacarpals over hand length), adult men average about 0.46 (ANSUR II), and 0.55 would be a broad hand more than 3 SD out.
- 0.55 is roughly what you get when the breadth includes the thumb: that ratio is 0.528 here.
- The fields widen the palm a little (ulnar border +1.6 mm, index head +0.7 mm), which moved the ratio from 0.478 to 0.484.
- Reaching 0.55 on the metacarpal definition would mean +13 mm of palm, which is a skeleton (MPFB proportions) change, not a sculpt. If the orchestrator wants that, it is a one-line `hands` breadth edit in a later track, and it needs a look first.

**Why relief p99 stops at 0.61 mm.**
- The metric is mine: the residual of a weighted quadric fit, σ 5 mm, over 10 mm. I chose it after 15 mm windows scored the old soft lumps at 1.33 mm.
- The quadric absorbs most of a 2 mm-wide tendon. Raising the tendons 1.3 → 1.8 mm and the veins 1.0 → 1.6 mm moved p99 only 0.49 → 0.61, while the clay already reads as a lean hand.
- Getting to 0.8 would need roughly 2.5 mm tendons, which is a body-builder's hand.
- The normal map carries the vein crests on top of this (hands map residual p1/p99 −0.08 / +0.13 mm), but those are not geometry and the metric does not count them.

**Face unchanged (in place of ArcFace).**
- `head_sculpt` and the head measures are identical.
- Lookdev face crops, before vs after RMSE: studio front 0.38 %, ¾ key 0.84 %, profile 1.29 %. The profile includes the neck.
- **Please run the ArcFace scalar on `…-t22-a5`:** EEVEE closeup and `game_closeup_hero.png`.

## What changed

**Hands** (`head_sculpt.hand_field`, a new appended section, and `hand_forms.apply`):
- **What the field sculpts.** A field in each hand's own frame (wrist, finger and across axes from the rig), analytic in position and normal so texels can evaluate it too:
  - metacarpal heads and the valleys and gutters between them;
  - extensor tendons fanning from the wrist, plus the extensor hood over the proximal phalanx;
  - EPL/EPB and the anatomical snuffbox;
  - PIP/DIP dorsal pads, joint widening and shaft slimming;
  - the ulnar border and index head;
  - a flatter wrist, with the ulnar head, the radial styloid and the palmar flexor cords;
  - dorsal veins on Track G's trunk paths, Chaikin-rounded, with a slow deterministic "sunk" modulation;
  - nail folds (geometry): the proximal fold up, the bed slightly down.
- **What it replaces.** The overlapping Track G terms and `refine.sculpt` knuckle/tendon/nail amplitudes (`hand_forms.SUPERSEDED`, `config.refine.sculpt`), so nothing is applied twice.
- **Mesh.** The dorsum, from the wrist to just past the MCP line, is subdivided once (+7.9k triangles). The thumb phalanges and the palm sides are excluded; in a1 they were included and cost +18.5k.
- **Normal map (`skin_tex` T22 section).** Only the terms finer than the mesh go into the hands height map: the veins and the flexor cords, as a texture-space high-pass (3 mm) at 0.6. a1 and a2 showed both alternatives fail:
  - the vertex-interpolation residual draws a zigzag along every ridge;
  - a high-pass of every term sharpens the tendons into hard creases.
- **Skin detail (`hand_detail`).** With T22 present, the old painted vein loop and vein height are off, and the vein tint follows the same vein mask. PIP/DIP/MCP fold lines and the cuticle line are slightly stronger (`T22_DETAIL`).
- **Hard masks removed.** Hard masks inside the field (`b > cen`, the hood start, the neck midline) drew one-texel lines in the map (a2). They are now smoothsteps.

**Neck** (`head_sculpt.neck`, run after `hand_forms.apply` in `head.refine`):
- The SCM ridge runs from the mastoid (from the ear lobe) to the sternal head, with recesses for the carotid triangle and the posterior triangle in front and behind. The larynx is a V-shaped midline blob.
- The neck verts above the collar are subdivided once (+584 faces).
- Every term is scaled by `collar_weight`:
  - 0 on any skin a shirt, jacket or tie ray-hits within 4 cm along the normal, and for 3 mm beyond;
  - rising to 1 over the next 12 mm.

  So **the surface the collar is fitted to does not move**. The larynx sits at weight 0.99 because it is above the collar line; in the frames it is under the beard and the knot.
- The head height map gets the neck field's 4 mm high-pass, with the weight blurred first (in a2 it showed facets).

**Correctives** (`deform_correctives`, `deform_runtime`, `web/src/character/deform.ts` and `poses.ts`):
- **`corr_fist` knuckle term.** Per flexed MCP and PIP, the skin is pushed back out along the joint's outer corner toward its rest height plus 1.0 / 0.6 mm, and the valleys between the heads deepen. About half of the push survives from the FIST_TIGHT bake to the FIST pose, so the caps are 3.5 / 3.0 mm. See the knuckle row in the table.
- **`corr_wrist_flex` (60°) and `corr_wrist_ext` (−55°).** Skin only, delta mush, so the tendons, the ulnar head and the flat wrist survive.
- **New cone option `inverse: true`.** d = (R_ref⁻¹ R_bone)⁻¹ d0, the forearm's direction seen from the hand. The hand bone carries pronation as twist, and without this a pronated wrist that flexes never drove the corrective (a1: `corr_wrist_flex_l` = 0 in the twist pose). The option is backward compatible: absent means the old rule. It is implemented in the Python runtime, the TS runtime and the TS `driveCone` debug poser.
- **No clavicle corrective.** a1–a3 baked `corr_shrug` (clavicle abduct 16°, all meshes). It moved the jacket (415 verts, up to 5 mm) and broke the shirt collar edge in arm_raise, and the exposed neck held its forms under LBS without it. I dropped it. The brief asked for one, so this is a deliberate miss.

**Evidence tools (new):**
- `bench/m1/hands_measure.py` (the two metrics on a kept .blend).
- `bench/m1/hands_neck_views.py`: EEVEE hand and neck close-ups of a GLB in beauty and clay, `--side`, and `--pose` with the shipped rig.json rules applied.

## Iterations

| Run | What it showed |
|---|---|
| a1 | Fields in, relief p99 0.49. Zigzag in the normal map (vertex residual), +18.5k tris (dorsum selection too wide), SCM too faint. Wrist correctives never drove in the twist pose. |
| a2 | High-pass residual, tighter subdivision (+8k), stronger fields: p99 0.59. Tendons rendered as hard creases (high-pass of broad terms), a one-texel line along `b = cen`, neck facets (piecewise-linear weight). |
| a3 | Soft masks, map from the fine terms only, blurred weight, inverse cone: wrist correctives drive, creases and facets gone. Veins read as beads; the shrug corrective broke the collar in arm_raise. |
| **a5** | Softer vein modulation, map 3 mm and 0.6×, tendons 1.8 / veins 1.6 mm, knuckle caps up, shrug dropped. |

## For the orchestrator

- **Collar / neck surface (T13).**
  - The neck is subdivided above the collar, and the fields are zero on and within 3 mm of anything the shirt, jacket or tie covers. The collar-fitted skin is unchanged.
  - The new triangles change the body's vertex count. Anything in T13 that indexes body vertices by number, rather than by position or BVH, would need a rebuild on the merged body. I did not audit T13's branch for this.
- **Shared runtime change.**
  - `cone` rules accept `inverse: true` (Python and TS runtimes, and the `driveCone` debug path). It is additive.
  - `main.ts` and `output.ts` (T16's files) are untouched.
- **Clavicle corrective dropped.** The reasons are above. If one is wanted later, it should be skin-only and masked to uncovered skin, which would be T13-adjacent work.
- **Pre-existing issues seen, not mine, not fixed.**
  - In the posed fist, small nail-like slivers float above the dorsum in both before and after (`gate/pose_strip_*`, first tile).
  - Inside the left cuff, the body's cut edge shows jagged spikes when the wrist flexes (second tile, before and after).
- **Worktree note.** A fresh worktree needs `npm run build:core` before `npm run build`, because `web/src/core-wasm` is generated and gitignored.

## What is left

- ArcFace scalar on `…-t22-a5` (private).
- If wanted:
  - irregular vein calibre and a third branch, so the network is less schematic;
  - dorsum crepe in the hands skin synth (out of scope here; it is T12/T19-style skin work).
- The `hand_width_ratio` target needs a decision (definition, or a skeleton change).

## Gate pictures (`data/build/t22/gate/`)

| File | What |
|---|---|
| `detail_strip_before_after.png` | lookdev `detail_strip`, before over after, 100 % |
| `detail_hands_before_after.png` | its hand-back and palm tiles, before \| after, 100 % |
| `cycles_hands_before_after.png` | Cycles hero light: back of the hand at rest and the fist, before \| after, 800 px at 100 % |
| `hand_{hand_back,knuckles,hand_side,wrist}_before_after.png` | EEVEE raking key, beauty over clay, before \| after |
| `neck_{profile,34,34r}_before_after.png` | neck profile and both ¾, beauty over clay, before \| after |
| `pose_strip_{clay,beauty}_before_after.png` | fist knuckles, flexed wrist (L), extended wrist and hand (R), arm_raise neck ¾ and profile; top before, bottom after |
| `engine_closeup_hero_neck_before_after.png`, `engine_three_quarter_hand_before_after_x3.png` | engine (SwiftShader) crops at 100 % and ×3 |
