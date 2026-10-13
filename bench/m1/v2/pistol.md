# m1 v2 Track H: the hero's pistol

Branch `worktree-agent-a650b08073c145945`. Own work only: no external asset,
so there is no provenance entry.

## What it is

The gun is an original, fictional, compensated competition pistol. It has no
marks, logos, model names or serials, and every outline is our own numbers in
`blender/props/pistol.py`.

- **Slide.** Striker-fired, with a flat top and steep side chamfers.
  - Rear cocking serrations (8) and front serrations (6), leaning forward.
  - An optic-ready cut with a cover plate and two hex screws.
  - A ramped rear sight, and a recessed front sight with a fibre insert.
  - An ejection port on the right, with a bronze (TiN) barrel hood as the one
    warm accent.
  - An extractor and a striker cover plate.
- **Compensator.** A separate two-piece comp with three filleted top ports,
  front chamfers and a recessed crown.
- **Frame.** Polymer, with:
  - an accessory rail;
  - a heavy squared trigger guard with an undercut behind it;
  - a rounded beavertail tang;
  - a stippled grip with a palm swell and a raised smooth border round the
    stipple;
  - a flared magwell and a flared base pad.
- **Controls.** Slide stop, takedown, magazine release, a bladed trigger with
  its safety, and frame pins.

**Scale.**

| | Size |
|---|---|
| Slide | 186 mm |
| Slide and comp | 214 mm |
| Overall length | 244 mm |
| Height with the base pad | 157 mm |
| Width | 32 mm (slide 23.6 mm) |

Against the hero's hand, wrist to middle knuckle is 114 mm, so the slide is
about 1.6 hand lengths.

**Method.** Procedural Blender Python, run headless in Blender 5.2:

- bmesh prisms, lofts and hulls;
- exact booleans;
- bevel with hardened normals, then weighted normals, all applied.

The two detail levels share every number:

| Detail | Tris | Bevel segments | Cylinder sides |
|---|---|---|---|
| hero | 30 074 | 3 | 48 |
| game | 10 266 | 1 | 20 |

**Hero materials.** Procedural Cycles, in gun-space millimetres:

| Material | Character | Base | Roughness |
|---|---|---|---|
| Black nitride (slide, comp) | Machining streaks along the bore in the roughness; edge wear from a bevel-normal mask times local AO times noise, which bares steel only on convex edges | 0.035 | 0.40 |
| Steel (controls, sights) | — | 0.045 | 0.44 |
| Anodised (magwell, pad) | — | 0.04 | 0.38 |
| Bronze hood | — | (0.52, 0.34, 0.15) | 0.24 |
| Polymer | See below | 0.022 | 0.48 |

The polymer has:

- a moulded noise;
- a stippled band, drawn from the position along the grip axis. It is a
  two-octave Voronoi pit-and-rim bump with roughness 0.74, framed by a
  1.6 mm smooth raised border;
- lighter, smoother worn edges.

## Files

- **`blender/props/__init__.py`, `blender/props/pistol.py`** (new).
  - The build and the materials.
  - The in-hand code: socket, orient, straighten, seat, support hand (with
    elbow swivel), digit placement, the thumb fan and solver, and the soft
    contact.
  - The game export: atlas, bake, glTF material, export.
- **`bench/m1/pistol_render.py`** (new). Gun close-ups from fixed gun-space
  views under the hero rig (the alley) and the studio turntable rig.
  `--glb` renders the exported game asset. Round 3 lowers the frame centre
  7 mm for the longer grip.
- **`bench/m1/v2/pistol.md`**: this report.

### Shared-file edits (all small and additive)

- **`blender/character/hand_pose.py`** (Track G):
  - `settle(..., spec=None)` takes an explicit POSE_HANDS-style spec.
  - The spec's `shape` may be a shape dict, not only a HAND_SHAPES name (it
    logs `shape_name`).
  - In `Scene.build`, an unskinned mesh parented to the armature (the pistol)
    counts whole once any vertex is near: its big flat faces span past the
    radius.
- **`blender/hero/poses.py`** (Track E):
  - `apply()` parses a held prop from the pose name.
  - `HOLD = {"ready": {"r": "pistol"}}` and `TWO_HAND = ("ready",)`.
  - `"+pistol"` holds the gun in any pose (one-handed unless the pose is
    two-handed), `"+pistol1"` holds it one-handed, and `"+none"` drops it.
  - `_hands()` runs `_props()`, which hides props not held and calls
    `pistol.hold()` (socket, orient, straighten, seat).
  - The strong hand then settles with `pistol.hand_spec()`.
  - After the settle, `pistol.finish_hold()` puts on the support hand and
    settles it with its own pass, then places the index and both thumbs.
  - `names()` gains `ready+none`, `ready+pistol1`, `walk+pistol` and
    `stand+pistol`.
- **`blender/hero/rig.py`** (Track E): `pose()` calls the new `sync_props(ch)`.
  It adds objects tagged `hero_prop` to `ch.objs` (light linking, the IndexOB
  mask) with `pass_index` 1.
- **`blender/hero/stage.py`** (Track E): `rig.sync_props(ch)` after posing,
  in both `render_shot` and `render_turntable`.
- **`bench/m1/hands_render.py`** (Track G):
  - shots `ready_front`, `ready_r` and `ready_top`;
  - `--pose` overrides every shot's pose (e.g. `ready+pistol1`).

The gun is hidden in every pose that does not hold it, and
`hand_pose._meshes` skips hidden meshes. So stand, cuff, walk, portrait,
profile and eye are unchanged.

## How the gun gets into the hands

The code is in `pistol.py`, "in the hand". This is the round-3 pipeline,
rebuilt after the orchestrator's review of the hold. The hand is the
constraint, and the gun is placed in it.

1. **Socket** (`socket_matrix`). This is authored from the hand.
   - The hand frame comes from joint positions: wrist to middle MCP, across
     the knuckles, and the back of the hand. It does not depend on bone roll.
   - The bore is the finger axis turned 4° toward the index. The gun's up is
     the index side, and its left is the palm normal.
   - The gun is rolled 10° about the bore (`cant`), so the fingers wrap level
     round the front strap.
   - The middle of the knuckle row (index and pinky MCPs) goes on the grip at
     station 26 mm, 46 mm forward of the backstrap. That puts the index
     beside the frame above the guard and the middle finger just under the
     guard.
   - The gun is parented to `hand_r`.
2. **Orient** (`orient`). The hand turns about the wrist so the gun is level
   (2° nose-down), upright, and pointing at the target: the character's
   forward (armature −Y), the line E's bladed ready keeps the eyes on. Round 3
   first pointed it along the forearm, which in the bladed stance aimed it
   across the chest.
3. **Straighten** (`straighten`). The wrist moves, with two-bone IK and the
   hand keeping its world orientation, to the spot where the wrist bends
   least. It is a coarse grid, then a fine one, over 90 mm. The levelled
   hand was bent 30.5°; after a 138 mm move it is bent **0.6°**, and the
   forearm is 10° off the bore.
4. **Seat** (`seat`). The gun slides along the palm normal (bisection) until
   the palm skin sits 2 mm into the grip and the thenar pad sits at most
   6 mm in. Both are soft tissue that `contact()` squashes back onto the
   surface at the end.
5. **Strong-hand settle** (G's `hand_pose`). An 80/92/50 grip shape with the
   index nearly straight. Middle, ring and pinky curl to first contact round
   the front strap (×0.49, ×0.43 and ×0.32 of the shape).
6. **Support hand** (`support`).
   - The strong hand's frame is mirrored through the gun's mid-plane. A search
     covers:
     - turn (0–25°, fingers down);
     - yaw (0–60°);
     - **elbow swivel** (±45° about the shoulder–wrist line, with the hand
       held still).
   - The pose is offset (20, 4, −30) mm: forward, out of the strong fingers,
     and down so the index comes under the guard.
   - The wrist goes there by two-bone IK, and the search keeps the
     straightest wrist. The elbow swivel is what fixed the 40° support wrist:
     it is now **1.5°** (turn 10, yaw 60, swivel +45).
   - G's clear lifts the support palm off the strong fingers. Its index,
     middle and ring then wrap the front of the strong fingers.
7. **Digits** (`place_digits`).
   - The strong index is aimed straight along the right of the frame above
     the guard. It is never on the trigger.
   - Each thumb starts from the best of its seed chains, plus a fan
     (`_thumb_fan`) built from the thumb's own root. The fan tries MCP points
     one metacarpal out and IP points one phalanx beyond. Every bone, sampled
     along its length, keeps its skin radius (10, 9 and 8 mm) off the gun,
     and the tip aims at its mark.
   - A greedy search then turns each thumb bone ±16°, 8°, 4° and 2°. Its
     cost is:
     - 1000 × the triangles of thumb skin (proximal and distal) cutting
       anything but its own arm, or the index skin;
     - plus the tip's distance from its mark;
     - plus half the IP joint's distance from its mark.
   - Marks:
     - **strong:** tip (40, 21, −28), IP (8, 24, −29): high on the left of the
       frame, pointing forward;
     - **support:** tip (126, 21, −37), IP (98, 22, −38): forward along the
       frame, under the strong thumb, at the target.
8. **Soft contact** (`contact`). Hand skin within 6 mm of the gun that lies
   inside it is pushed onto the surface, plus 0.2 mm, by a shrinkwrap
   (outside mode) right after the skin's armature modifier. It covers both
   hands and the nails, limited to a vertex group so that skin further off,
   where the inside test is unreliable, is never touched. `hide()` and the
   next `spawn()` remove it.

## Iteration log

### Gun

| Run | Change | Verdict |
|---|---|---|
| r1 | First full build | Too plain. Wedge beavertail, a slab frame with a hard edge, a plain comp, a light slide. |
| r2–r4 | Horizontal-ring grip top covering the frame side to x 97; rounded tongue beavertail; comp chamfer and slots; thicker guard; bigger trigger; frame pins; materials darkened and rebalanced; alley set for metal reflections | Reads as a custom race gun (orchestrator review of q34l). |
| r5–r6 (G2) | Answers the orchestrator's critique, listed below | The comp reads machined; the stipple panel is clean; the guard is heavier; the hood reads from the right and from above. |
| G3 | Review 2, below | Black slide in the studio; a round tang; the grip fits the hand. |

The orchestrator's points and what G2 did about each:

1. **Slide.**
   - A narrower top flat with a longer chamfer, which catches a line of light
     its whole length.
   - A stronger lower nose taper and a 2.6 mm top-front chamfer.
   - The port opens past the centre line, so the bronze hood shows as a block
     from the right and from above.
   - The port was always on the right. q34l looks at the left side.
2. **Comp.**
   - The oval side window is gone.
   - Three filleted top ports, narrowing forward.
   - Top-front, bottom-front and rear chamfers.
   - A recessed 3 mm crown cone.
3. **Grip.**
   - 12 % longer and 2 mm slimmer (29 mm).
   - The magwell flare is halved (+1.1 mm width, +2.8 mm front).
   - The base pad is thinner: 5.8 mm, down from 7.8.
   - An undercut behind the guard.
   - A longer upswept tang.
   - The stipple is a shader band with a smooth raised border. Before, it was
     a per-face mask with a stepped edge.
4. **Guard.**
   - 12 mm wide, up from 10.8.
   - An 8 mm bottom bar tapering to the front, and a squared front.
   - A 2 mm bevel.
5. **Edges.** Bevels are 0.45–0.9 mm on the main parts (slide 0.7, comp 0.65,
   frame 0.9, guard 2.0), with hardened and weighted normals.
6. **Sights.** The front sight and its fibre insert are kept: an orange-red
   rod with a little emission.

Review 2 (G3):

- **Black slide.** The nitride albedo is 0.035, down from 0.10. Steel is
  0.045 and anodised 0.04. The edge wear (bare steel, 0.42) is unchanged.
  The slide now reads black in the studio, and the polymer reads a step
  lighter.
- **Tang.** The pointed wedge is now a rounded tang: a circle in plan of
  radius 10.4 mm, also rounded in side view, and thick to its tip, so the web
  has something to sit in.
- **Grip length.** It is 8 mm longer (stations to 76 mm, stipple to 69 mm),
  for the scale check. On the old grip the pinky landed on the magwell's
  flare. See the verdicts.

### Hands

Measured with `hands_render.py --pierce`, which counts triangle overlaps per
hand and digit (skin against the gun, the other hand and the body).

| Run | State | Pierce or verdict |
|---|---|---|
| h1–h4 | Single-direction seat; socket web_grip (−10, −8) | Overlap not clearable within 26 mm. |
| h5–h7 | Iterative seat; support hand mirrored; tip aims | r thumb 633–665, r palm 47, l thumb 44. Fingers barely curl. The thumb went through the slide. |
| h8 | Diagnosis (`ready+pistol1`) | The thumb root is ~40 mm right of the bore plane with a 34 mm metacarpal. |
| h9–h11, G2 | Thumb chain, support in its own settle pass, greedy thumb solver | 0 / 0, but the **hold was wrong** (orchestrator review): the grip sat behind the palm, the frame lay on top of the hand, the support wrist was bent 40°, and the strong thumb was wrapped low. |
| h12 | Hand-first socket (knuckles on the front strap), orient, straighten, seat by bisection, contact squash | Strong wrist 4°, but the support wrist was 22–35°, the support index was blocked open (l index 366–630), and the strong thumb wrapped behind the grip (44 mm off its mark). |
| h13 | Socket cant 0 / 10 / 20 / 35 and yaw sweeps | cant 20 dropped the fingertips 27 mm. cant 10 was best. Yaw made the support worse. |
| h14 | Elbow swivel in the support search | Support wrist 22° → 1–10°. |
| h15 | Support offset forward (20, 4, −30) | Support index out of the strong middle: l 0. |
| h16 | Thumb fan from its own root | Strong thumb clear, high on the left, tip 18 mm from its mark (was 44–88). |
| h17 | Grip +8 mm; support thumb marks forward | 0 / 0. |
| H3 | Aim at the target, not along the forearm (coordinator: the gun pointed across the chest in the front view) | **0 / 0.** Bore at −Y, level, −2° pitch. Strong wrist 0.6°, support 1.5°. |

## Evidence

Run dirs are in the main checkout's `data/`. The character for every in-hand
render is `data/build/lookdev/20261013T050241Z-deformF-r4/character.blend`:
F round 2 (main 18cd96f), with G's hands and corr_fist.

- **Game asset:** `data/build/lookdev/20261013T071700Z-pistolH3-game/`
  - Files: `pistol.glb`, `pistol.blend`, `pistol.json`, the maps
    `pistol_{basecolor,normal,orm}.png`, `glb_stats.json`, and `render/`
    (the GLB under both rigs).
  - The glTF validator reports **0 errors and 5 warnings**. Every warning is
    `MESH_PRIMITIVE_GENERATED_TANGENT_SPACE`: tangents are left to the engine.
    Blender's exported tangents carried two zero vectors from sliver UV
    faces, which the validator rejects. The mesh is triangulated on export,
    so an engine's MikkTSpace matches the bake.
  - **10 266 tris:**

    | Node | Tris |
    |---|---|
    | slide | 3 000 |
    | barrel and comp | 1 814 |
    | frame | 4 696 |
    | trigger (origin on its hinge) | 368 |
    | magazine | 388 |

  - One material on three maps: 2048 base colour, 2048 tangent normal, and a
    1024 ORM (AO softened to 0.35–1). They were baked in Cycles at 16 spp from
    the hero materials, in 145 s.
  - A `grip_socket` empty sits on the backstrap under the tang, where the web
    goes (`WEB_GRIP`).
  - The overall size is 246 × 32 × 157 mm.
- **Hero gun:** `data/build/lookdev/20261013T072000Z-pistolH3-hero/`
  - `{hero,studio}_{q34l,left,right,top,muzzle,rear34}.png` at preview
    quality, 1600×1000.
  - `hero_{slide_cu,comp_cu,grip_cu}.png`.
  - The side views were framed for the old grip and clip the base pad's
    bottom edge. The frame centre has been lowered since.
- **Hands on the gun:** `data/build/lookdev/20261013T072000Z-pistolH3-hands/`
  - `{hero,turntable}_ready_{front,side,r,top}.png` at preview quality, 1000
    px, `--pct 100`.
  - `hands.json`: pierce `ready` `{l: {}, r: {}}`.
  - `regress.json`: pierce, wrist bends, the pinky gap and the bore direction
    per pose.
- **Draw shot:**
  - As shot (az 5): `data/build/hero/20261013T075343Z-pistolH3-draw/draw.png`.
  - Camera at **az 20**: `data/build/hero/20261013T084857Z-pistolH3-draw-az20/draw.png`.
    This was a local, uncommitted edit of `shots.py`, since reverted.
  - Both from `hero.sh --preview --shots draw --no-turntable`.

The PNGs to look at first:

1. `20261013T072000Z-pistolH3-hands/hero_ready_front.png`: the muzzle at the
   camera, the hands round the grip.
2. `20261013T072000Z-pistolH3-hands/turntable_ready_r.png`: the strong index
   along the frame, the support fingers over the strong fingers.
3. `20261013T072000Z-pistolH3-hands/hero_ready_top.png`: both wrists in line,
   both thumbs on the left of the frame.
4. `20261013T072000Z-pistolH3-hero/studio_left.png`: the black slide and the
   round tang.
5. `20261013T084857Z-pistolH3-draw-az20/draw.png`.
6. `20261013T072000Z-pistolH3-hero/hero_q34l.png`.

**Note for Track E (draw camera).**

- At az 5 the bladed high ready points the muzzle straight down the lens. The
  gun is then a small dark square between the hands.
- At **az 20** it reads as a pistol: the slide's top edge catches the magenta
  rim, and the side silhouette is clear.
- I suggest `cam="lens=35,az=20,..."` for `draw`. `shots.py` is yours, so I
  have not changed it.

## Verdicts

Each item is a defect or requirement and its honest state.

- **Original design, no marks: met.** Every outline is our own numbers. There
  is no text, logo or serial.
- **Features: all present.**
  - compensated, stippled and striker-fired;
  - serrations front and rear;
  - an extended (flared) magwell and a flared base pad;
  - an optic cut with a plate;
  - a rail.
- **Close-up detail: met at hero distance.**
  - The bevels and weighted normals catch a line of light on every main edge
    under the neon.
  - The slide-to-frame gap is visible.
  - The barrel crown and the comp's recessed crown read from the muzzle.
  - The front sight sits in its trench.
- **Slide reads silver: fixed.** The nitride albedo is 0.035. In the studio
  the slide is black, with the edge wear on the corners. Under the hero rig
  the slide is near-black, and the teal and magenta only come in as
  specular. The teal flank the coordinator saw in the WIP front view was a
  mirror reflection of the teal light: there the gun was side-on to the
  camera.
- **Bronze under teal: olive.** Accepted per the review.
- **Beavertail: fixed.** It is a rounded tang, not a pointed wedge.
- **Still plain.**
  - The comp side flats are flat.
  - The rail and dust cover are simple extrusions.
  - Edge wear is subtle on the slide.
- **Game asset: met** (≤ 12k tris, 0 validator errors, 1–2k maps).
  - The atlas packing is loose. Many small islands leave about 40 % of the
    sheet unused.
  - The GLB under the studio light shows a soft smudge on the slide's flank,
    from the 1-segment bevels' shading.
- **Gun direction: fixed.** The bore points at the target (world −Y, the
  eye line of E's bladed ready), level, 2° nose-down. In the front view the
  muzzle faces the camera.
- **Wrists ≤ 15°: met.** Strong 0.6° (forearm 10° off the bore), support
  1.5°. The support wrist had been 40°. The elbow swivel fixed it.
- **Strong hand: mostly met.**
  - **Met:**
    - the web sits under the rounded tang;
    - the bore is about 25 mm above the top of the hand;
    - the palm is on the right panel, with the grip running down through the
      palm to the heel;
    - the index lies straight along the frame above the guard and is never on
      the trigger;
    - the middle finger is right under the guard;
    - middle, ring and pinky wrap the front strap.
  - **Short:**
    - The fingers curl only to ×0.3–0.5 of the shape. They stop at first
      contact, so the grip is a firm wrap, not a crush grip.
    - The thenar pad only just reaches the backstrap (−1.1 mm, so it touches
      without squashing). The palm on the right panel is what stops the gun
      going deeper.
- **Strong thumb: partly met.**
  - It is high on the left of the frame and points forward. It wraps from
    behind the backstrap under the tang, so it is no longer low behind the
    grip.
  - But its tip reaches about x 23 mm, 17 mm short of its mark and about
    40 mm behind the slide stop (x 64–100). It is not under the slide stop.
  - This rig's thumb root sits 37 mm right of the bore plane and 27 mm behind
    the slide's rear face. With a 34 mm metacarpal, every fan and solver
    run that reached further forward cut the backstrap or the tang.
  - What I tried and what each did:
    - moving the knuckles back 6 mm: the thumb went behind the grip, tip
      62 mm off;
    - more thenar squash (10 mm) and palm squash (4 mm): no gain;
    - yawing the socket: the support index got worse.
  - What it would take: a rig change to the thumb's CMC (deeper in the
    palm), or a deliberate thenar squash past 6 mm.
- **Support hand: met.**
  - Its heel is on the left of the grip.
  - Its index, middle and ring wrap the front of the strong fingers, with the
    index under the guard.
  - Its thumb lies forward along the frame below the slide and under the
    strong thumb, pointing at the target.
  - **Short:** from the top view the support palm sits a few millimetres off
    the left grip panel: G's clear lifted it 21 mm off the strong fingers. The
    gap is hidden from the front and both sides.
- **0 interpenetration: met** in `ready` (pierce 0 / 0). Contact pushed only 4
  skin vertices, by at most 0.2 mm.
- **Scale and the pinky gap: partly met.**
  - The grip fills the palm, and the slide is 1.6 hand lengths.
  - The pinky's lowest skin ends 6 mm above the magwell mouth: about a third
    of a finger width, not a full one.
  - I lengthened the grip by 8 mm. With the old grip the pinky sat on the
    magwell flare. A full finger's gap would take another ~12 mm of grip, or
    the hand 10 mm higher, but higher puts the middle finger into the guard.
    I stopped at 8 mm to keep the gun's proportions.
- **One-handed `walk+pistol` and `stand+pistol`: regressed. Not usable.**
  These extra pose names are not in any shot. The hold now aims the gun level
  at the target, so in walk and stand the one-handed level gun leaves:
  - r palm pierce 46 and 23;
  - strong wrist bends of 11.6° and 17.6°.

  They need a real low-ready hold of their own (muzzle down, the wrist
  following the arm). I have not done that.
- **The gun stays out of the other shots: met.** stand, cuff and walk are at
  pierce 0 / 0 with the gun hidden. portrait, profile and eye use those poses.
- **G's settle and E's `bladed()`: kept.** They are untouched. The pistol
  settles through `hand_pose.settle`, and `ready` is still E's bladed high
  ready. The hold then moves the arms (the strong wrist 138 mm, the support
  arm by IK and elbow swivel) so that the wrists stay straight.
- **corr_fist: no effect on the grip.** On the F round-2 build, the rendered
  `ready` is at 0 / 0 with corr_fist in the rig. The grip's curl is under its
  dead zone.
