# m1 v2 Track G: hands

Branch `worktree-agent-a8e2c19fa29180942`.

- **Final build:** `data/build/lookdev/20261013T022716Z-G-hands4` (full
  `lookdev.sh`, `variants/direction.json`, `KEEP_BLEND`).
- **Final hand evidence:** `data/build/trackG/final4/`, rendered by
  `bench/m1/hands_render.py` under both the hero rig and the turntable light,
  at `--pct 100`, 32 spp, 800 px, DOF off.
- **Baseline:** the main build `data/build/lookdev/20261013T000424Z-heroE-main5`,
  rendered with the same tool into `data/build/trackG/base/` and
  `data/build/trackG/base_cuff/` (the shard).

**Budgets (hands4).**

| | hands4 | main5 |
|---|---|---|
| Tris | 123 055 | 121 351 |
| Weights per vertex (max) | 4 | 4 |
| glTF validator errors | 0 | 0 |
| glTF validator warnings | 16 | 15 |
| GLB | 73.30 MB | 72.96 MB |
| Build | 225 s | 205 s |

- The extra tris are the nail mesh (+1 696 tris).
- The extra warning is the usual `NODE_SKINNED_MESH_NON_ROOT` for the new nail
  mesh, the same as every other skinned part.
- The build is 20 s slower, all of it in `head_refine` (the forms and the
  detail layer).

**Track F's correctives still fire on the final, hand-finished poses.** After
the hands are settled, the deform runtime is re-run (logged in
`final4/hands.json`), e.g.:

- cuff: `corr_arm_down_l 0.41, corr_arm_fwd_r 0.12, corr_elbow_l 0.12, …`
- ready: `corr_elbow_l 0.50, corr_elbow_r 0.47, …`
- twist: `corr_elbow_l/r 0.70`

## The shard: diagnosis and fix

The "black shard" on the right knuckles in the cuff pose is not a skin or
shading artefact. It is the **left arm's shirt cuff and jacket sleeve showing
through the back of the right hand.**

- **How I found it.** I fired camera rays at the shard pixels. The hits were
  `suit_shirt` faces weighted to `hand_l` / `lowerarm_twist_01_l`, and jacket
  sleeve faces, sitting *inside* the right hand
  (`base_cuff/hero_az-20_el10_…png`, and its clay pass).
- **Cause.** Track E's `cuff_arms` puts the right hand around the left wrist,
  but the hand's volume ends up inside the left sleeve. The cloth is skinned to
  the left arm, so it pokes out of the right hand wherever the two intersect.
- **Fix at the source.** I added a pose-finishing pass (`hand_pose.settle`),
  called from `hero/poses.apply` after the arm pose. Per hand:
  1. Apply the authored finger shape.
  2. **Clear:** move the hand out of any foreign geometry. Contact is tested
     with real triangle overlap (`BVHTree.overlap`) against the other arm,
     the body and the suit. The move is a two-bone IK that keeps the hand's
     orientation, and the direction is searched, then bisected to a 2 mm gap.
  3. **Wrap:** curl the wrap digits from open until just before first
     contact. The thumb falls back to a swing and lift search if it cannot
     clear.
  4. **Spread:** separate any touching adjacent fingers.
  5. When every hand is done, re-wrap any hand that a later clear moved into,
     and re-run Track F's deform runtime.

  In the cuff, the right hand moves 41 mm back out of the sleeve and its
  fingers wrap the left wrist (k ≈ 0.4–0.5). `pierce` reports **0 foreign
  triangles** inside either hand in rest, stand (hero), cuff, high_ready and
  f:twist (`final4/hands.json`).

**Post-rebase check (main b2ab739, suit round 3).** Build
`data/build/lookdev/20261013T024735Z-G-hands5-rebased`: 123 139 tris, 0
glTF errors, 4 weights per vertex. Hand pierce is 0 in stand, cuff, ready and
f:twist, and the correctives are active after the hand finishing.

## What changed

### Hand forms: `blender/character/hand_forms.py` (new)

- **Where it runs.** On the dense hands, after `head_refine` and before the
  skin bake, so the baked normal map, AO and hero displacement all see the
  forms.
- **What it touches.** Vertices move along their normals only. The MPFB
  topology, UVs and weights are unchanged. hands4 moves 7 899 vertices, by up
  to +1.43 / −0.68 mm.
- **Back of the hand:**
  - metacarpal-head knuckle bumps, with valleys on the knuckle line;
  - four extensor tendons fanning from the wrist;
  - the two thumb extensors framing the snuffbox;
  - the first dorsal interosseous mound.
- **Palm:** the thenar and hypothenar pads, the central hollow, and cushions
  under the finger roots.
- **Fingers:** palm-side pads and pulp, a little volume at the PIP and DIP
  joints, and slimmer shafts between them.
- **Placement.** Everything is placed in the hand frame from the rest skeleton
  (`head_refine.hand_frames`).
- **Config.** `hands.forms`. Setting `hands: null` switches off all of
  Track G's build stages.

### Skin detail: `blender/character/hand_detail.py` (new)

This is a texture-space layer on top of Track A's `skin_synth.synth_hands`,
baked into the same hand maps (game normal, albedo, ORM and hero height).

**Handed-over terms.** A's `knuckle_crease`, `palm_crease` and `palm_line` are
set to 0 when this layer calls `synth_hands`. They made the "Michelin" triple
rings in the baseline. This layer draws those features anatomically instead.

**Height (raised features are positive):**

- **Dorsal knuckle folds:** curved, broken, irregular folds in an oval field
  over each joint (PIP 0.34 mm, DIP 0.22, MCP 0.16, thumb 0.26).
- **Flexion creases:**
  - double at the PIP and single at the DIP;
  - digital creases at the finger roots;
  - two wrist bracelets.
- **Palm lines:** the thenar, proximal and distal transverse lines, placed in
  normalised palm coordinates, plus faint minor lines.
- **Veins:** the dorsal venous network as raised (0.45 mm, 1.5 mm wide),
  partly sunk, corner-rounded paths, with a different jitter on each hand.
- **Cuticle:** a slight roll of skin.

**Albedo:**

- Redder knuckles and fingertips, and a little palm flush. This uses A's
  chromatic haemoglobin direction: G and B drop, R holds.
- Subtly bluish veins.
- A slightly darker cuticle.

**Roughness:** rougher in the folds and creases and on the knuckles.

**Config:** `hands.detail`.

### Nails: `blender/character/hand_nails.py` (new)

Each nail is real geometry: a separate mesh, `Human.hand_nails_export`, with
10 nails and 1 696 tris. It is built in two stages.

- **Plate.** It is built from the body's `fingernails` faces (weight > 0.5),
  as one island per digit.
  - It is lifted 0.40 mm, easing to 0.06 mm at the proximal and lateral
    borders, so it rises out of the folds rather than floating on them.
  - The plate carries on over the skin to the fingertip ("reach", still nail
    bed).
  - It then overhangs the tip by 0.55 mm (0.75 mm on the thumbs), with a
    slight curl, a 0.45 mm thickness, an underside, a rim and closed ends.
- **Texture.** One shared 512² texture with its own UV (thumbs on the right
  half), coloured as follows:
  - pink bed;
  - lunula (faint on the fingers, clearer on the thumbs);
  - onychodermal band;
  - off-white free edge (only on the overhang);
  - faint longitudinal ridges.

  Roughness is 0.22 on the plate and 0.34 on the free edge, against the
  skin's ~0.45.
- **Rigging.** Weights are copied per source vertex from the body after
  `rig.post`, so they match F's final finger weights (1 influence per vertex,
  the distal bone). There is an Armature modifier, and the mesh goes into the
  GLB.
- **Hero.** `hand_nails.hero` adds a Cycles-only variant: coat 0.35 / 0.08 and
  random-walk SSS 0.25, because the plate is translucent.
- **Config:** `hands.nails`.

### Poses: `blender/character/deform_poses.py` (my hand values) and `hand_pose.py` (new)

**Engine fix.** Finger `abduct` is now mirror-symmetric (+ = radial on both
hands). It was unused before, so no existing pose changes.

**Pose helper.** `hand()` gains two keyword arguments, both backward
compatible:
- `cascade`: curl falloff, increasing from index to pinky;
- `thumb_abduct`.

The MPFB rest hand is already splayed (index +8°, ring −18°, pinky −25°), so
the relaxed shapes *close* the spread slightly (`spread −3…−4`).

**Values:**
- `RELAXED_HAND`, `HERO_RIGHT_HAND`, `GRIP`, `SUPPORT_GRIP`, `FIST` and the new
  `BUTTON_HAND` (used for the left hand in `hero`) are re-tuned, with a
  cascade and a relaxed, slightly adducted thumb.

**New `orient` op.** It aims a hand by finger and thumb directions in the
chest frame.

**high_ready** is re-authored with `orient` on both hands, plus a new left IK
offset. The baseline had the two hands interlocked through each other. Now
the right hand presents the grip and the left hand cups it.

**`POSE_HANDS`** is a per-pose spec for `hand_pose.settle`. It sets the
shape, clear, wrap digits, `wrap_max` and `own_palm`, for these poses:
`cuff`, `hero`, `high_ready`, `relaxed` and `twist`.

F's API and the other poses are untouched.

### Evidence tool: `bench/m1/hands_render.py` (new)

- **What it does.** Loads a staged `.blend` once, poses it with the hero rig's
  `rig.pose`, and renders hand close-ups framed in the posed hand's own frame.
  The shots are:
  - rest back, palm, side, nails and knuckles;
  - hero right and left;
  - cuff and cuff top;
  - ready and ready side;
  - the f:twist fist.
- **Options.** `--light hero|turntable|both`, `--pct` (default 100),
  `--quality`, `--samples`, `--res` and `--passes`. `--pierce` writes the
  per-pose overlap counts to `hands.json`.

### Shared-file and other-track edits

All of these are minimal and additive.

| File | Owner | Edit |
|---|---|---|
| `blender/build_character.py` | shared | `hand_nails` in the import; `b.step("hand_nails", hand_nails.build)` after `rig_post`; `b.step("hand_nails_hero", hand_nails.hero)` after `head_hero` |
| `blender/character/head.py` (`refine`) | A | `hand_forms` in the local import; `hand_forms.apply(b)` before `skin_tex.build(b)` |
| `blender/character/skin_tex.py` | A | `hand_detail` in the import; the one `synth_hands` call becomes `hand_detail.synth(…, b.cfg.hands.detail)`, which calls A's `synth_hands` itself |
| `blender/hero/poses.py` | E | both `apply` return paths become `return log + _hands(arm, name)`; new 9-line `_hands()` that calls `hand_pose.settle` and re-runs `deform(arm)` |

## Evidence

Each shot exists under both lights: `hero_<shot>.png` and
`turntable_<shot>.png`. "Before" is the main5 build with the main poses.
"After" is hands4 with the hand finishing.

| Shot | Before | After |
|---|---|---|
| Cuff (the shard) | `trackG/base_cuff/hero_az-20_el10_lens100_aimhand_r_frame0.2.png` | `trackG/final4/hero_cuff.png`, `turntable_cuff.png` |
| Back of the hand | `trackG/base/hero_rest_back_l.png` | `trackG/final4/*_rest_back_l.png` |
| Palm | `trackG/base/hero_rest_palm_l.png` | `trackG/final4/*_rest_palm_l.png` |
| Nails | `trackG/base/hero_rest_nails_l.png` | `trackG/final4/*_rest_nails_l.png` |
| Hero right hand | `trackG/base/hero_hero_r.png` | `trackG/final4/*_hero_r.png` |
| High-ready grip | `trackG/base/hero_ready.png` | `trackG/final4/*_ready.png` |
| Fist (f:twist) | `trackG/base/hero_fist_l.png` | `trackG/final4/*_fist_l.png` |

The intermediate runs are listed in the iteration log.

## Iteration log

| Run dir | Change | Verdict |
|---|---|---|
| `trackG/base_cuff`, `trackG/base` | baseline renders and ray picks | Mittens. A's knuckle creases make triple "Michelin" rings. Nails are faint and flat; no veins or tendons. The hero_r thumb is awkward. high_ready hands interpenetrate. The fist's nails poke out through the back of the hand. The shard is the left sleeve inside the right hand. |
| `trackG/pose1` | first `hand_pose.settle` (clear + wrap) | Shard gone in the cuff. A wrap at k=1.4 passed *through* the obstacle (non-monotonic). Rewrote it as a scan from open to first contact. |
| `trackG/ready2` | high_ready | Hands interlocked, and no clear direction existed. Re-authored the orientation (`orient`), opened the wrap digits before clearing, added the thumb fallback. pierce 0. |
| `trackG/pose2` | spec order (r then l), re-wrap pass, `own_palm` fist, abduct sign fix, negative spread | Cuff reads as one hand holding the other wrist, fingers separate. hero_r relaxed with a natural cascade. Fist is looser but clean. |
| `lookdev/…G-hands1`, `trackG/h1` | first build with forms, detail and nails | Knuckle bumps, tendons and palm lines appear. Nails are real but read as a "French manicure": a barcode of ridges, a 2–3 mm white tip, a heavy lunula. Folds are too faint to see. |
| `lookdev/…G-hands2`, `trackG/h2` | nail UV split into reach (bed) + overhang (free edge); ridges ×0.3; lunula 0.35 / 0.65; folds ×2; veins 0.42 mm | Nails read as clean short male nails. DIP and PIP folds visible. Veins read as thin wires. |
| `lookdev/…G-hands3`, `trackG/final` | veins 0.5 mm and 1.5 mm wide | Veins read as soft raised tubes, but the network's corners are angular and a little graphic in the cuff light. |
| `lookdev/…G-hands4`, `trackG/final4` | veins corner-rounded (Chaikin ×2), 0.45 mm | Final. |

## Verdict per defect (senior character artist's eye)

| Defect | Verdict | What remains |
|---|---|---|
| Shard on the right knuckles (cuff) | **Fixed at the source.** The hand is moved out of the left sleeve; pierce is 0 in all evidence poses. | The fix depends on the finishing pass. If E changes `cuff_arms`, `settle` re-clears automatically. |
| Fingers fused in the cuff | **Fixed.** The fingers wrap the wrist with visible gaps and a curl cascade. | |
| Mittens: no knuckles, nails, tendons, veins or creases | **Largely fixed.** Knuckle bumps and valleys, tendons, thenar and hypothenar pads, joint volume, dorsal folds, palm and flexion creases, veins, and real nail plates with lunula, band and free edge are all present at 100 %. | The back of the hand is still a little soft in a tight fist: the MPFB mesh plus linear skinning gives a puffy dorsum, and the knuckles don't sharpen under stretch. A fist corrective (F's area) or a wrinkle map driven by the finger curl would be the next step. |
| Nails | **Good.** A short male nail, pink bed, faint lunula, a thin off-white overhang, lower roughness with a coat. | On the hero light, one coat specular sits on the lateral edge of a nail. Acceptable. |
| Michelin triple creases | **Fixed.** A's terms are handed over; the layer draws irregular, broken folds. | |
| Poses | **hero_r, hero_l and the cuff read naturally. high_ready is clean** (no interpenetration) and plausible as a two-hand grip with no gun. | The **fist** (f:twist) is looser than a punch: the `own_palm` wrap stops at the first contact with the palm skin. A tighter fist needs a palm-side corrective. |
