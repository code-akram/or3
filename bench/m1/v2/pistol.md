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
  - a beavertail tang;
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
| Height with the base pad | 150 mm |
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
| game | 10 042 | 1 | 20 |

**Hero materials.** Procedural Cycles, in gun-space millimetres:

| Material | Character | Base | Roughness |
|---|---|---|---|
| Black nitride (slide, comp) | Machining streaks along the bore in the roughness; edge wear from a bevel-normal mask times local AO times noise, which bares steel only on convex edges | 0.10 | 0.40 |
| Steel (controls, sights) | — | 0.075 | 0.44 |
| Anodised (magwell, pad) | — | 0.06 | 0.38 |
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
  - The in-hand code: socket, aim, seat, support hand, digit placement and the
    thumb solver.
  - The game export: atlas, bake, glTF material, export.
- **`bench/m1/pistol_render.py`** (new). Gun close-ups from fixed gun-space
  views under the hero rig (the alley) and the studio turntable rig.
  `--glb` renders the exported game asset.
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
    `pistol.hold()` (socket, aim, seat).
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

The code is in `pistol.py`, "in the hand".

1. **Socket.**
   - The hand frame is built from joint positions (wrist→middle MCP; across
     the knuckles; back of the hand), so it does not depend on bone roll.
   - The bore is that frame's finger axis turned 12° toward the index.
   - The web crotch (between the thumb MCP and the index metacarpal) goes on
     the backstrap under the beavertail.
   - The gun is parented to `hand_r`.
2. **Aim.** The hand bone turns about the palm normal until the bore sits
   2° nose-down in the world (−18° of wrist turn). The high-ready hand was
   authored for an empty fist, so the muzzle otherwise points 20° down.
3. **Seat.** Rigid moves of the gun against the palm skin, each to first
   contact minus 0.4 mm:
   - out of the palm;
   - then twice: onto the palm, up the grip (at most 4 mm: higher crowds the
     middle finger under the guard), back into the web.
4. **Strong-hand settle** (G's `hand_pose`). A grip shape (80/92/50) with the
   index nearly straight; middle, ring and pinky curl to first contact round
   the front strap.
5. **Support hand.**
   - The strong hand's frame is mirrored through the gun's mid-plane, turned
     38° fingers-down about the gun's Y axis, and offset (10, 8, −14) mm.
   - The left hand bone is rotated to it and the wrist moved there by
     `move_hand`'s two-bone IK.
   - Then G's clear lifts its palm out of the strong fingers, and its fingers
     wrap the front of the strong fingers.
6. **Digits.**
   - The strong index is aimed straight along the right of the frame above
     the trigger guard. It is never on the trigger.
   - Each thumb starts from the best of three seed chains (MCP, IP and tip
     points in gun space). A greedy search then turns each thumb bone ±16°,
     8°, 4° and 2°. Its cost is 1000 × the triangles it cuts (anything but
     its own arm, plus the index skin) + the tip's distance from its mark.

## Iteration log

### Gun

| Run | Change | Verdict |
|---|---|---|
| r1 | First full build | Too plain. Wedge beavertail, a slab frame with a hard edge, a plain comp, a light slide. |
| r2–r4 | Horizontal-ring grip top covering the frame side to x 97; rounded tongue beavertail; comp chamfer and slots; thicker guard; bigger trigger; frame pins; materials darkened and rebalanced; alley set for metal reflections | Reads as a custom race gun (orchestrator review of q34l). |
| r5–r6 (G2) | Answers the orchestrator's critique, listed below | The comp reads machined; the stipple panel is clean; the guard is heavier; the hood reads from the right and from above. |

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
   - 12 % longer (stations to 68 mm) and 2 mm slimmer (29 mm).
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

### Hands

Measured with `hands_render.py --pierce`, which counts triangle overlaps per
hand and digit.

| Run | State | Pierce or verdict |
|---|---|---|
| h1–h4 | Single-direction seat; socket web_grip (−10, −8) | Overlap not clearable within 26 mm. |
| h5–h7 | Iterative seat; support hand mirrored; tip aims | r thumb 633–665, r palm 47, l thumb 44. Fingers barely curl. The thumb went through the slide. |
| h8 | Diagnosis (`ready+pistol1`) | This hand's thumb root is ~40 mm right of the bore plane with a 34 mm metacarpal and a 24 mm thick palm pad. The thumb cannot reach high on the left of the frame without cutting through the slide or backstrap. Yawing the socket only pushed the palm further out. |
| h9 | Thumb as a joint chain: MCP behind the backstrap under the beavertail, forward along the left of the frame | r thumb 140. |
| h10 | Support hand moved into its own settle pass after the strong hand (it used to block the strong fingers' re-wrap); the greedy thumb solver; the seat's "up" limited to 4 mm (a move bug fixed on the way) | **0 / 0**. |
| h11 | SUPPORT turn 38°, offset (10, 8, −14) | 0 / 0. The support index wraps under the guard, the support thumb points forward along the frame, and the curl is higher. |
| G2 | The same pipeline on the new gun, and on the F round-2 build (deformF-r4, with corr_fist) | 0 / 0. corr_fist stays at 0: the grip's curl, ×0.47 of an 80/92° shape, is inside its 45 % dead zone. |

## Evidence

Run dirs are in the main checkout's `data/`. The character for every in-hand
render is `data/build/lookdev/20261013T050241Z-deformF-r4/character.blend`:
F round 2, which is main 18cd96f, with G's hands and corr_fist.

- **Game asset:** `data/build/lookdev/20261013T080000Z-pistolH2-game/`
  - Files: `pistol.glb`, `pistol.blend`, `pistol.json`, the maps
    `pistol_{basecolor,normal,orm}.png`, `glb_stats.json`, and `render/`
    (the GLB under both rigs).
  - The glTF validator reports **0 errors and 5 warnings**. Every warning is
    `MESH_PRIMITIVE_GENERATED_TANGENT_SPACE`: tangents are left to the engine.
    Blender's exported tangents carried two zero vectors from sliver UV
    faces, which the validator rejects. The mesh is triangulated on export,
    so an engine's MikkTSpace matches the bake.
  - **10 042 tris:**

    | Node | Tris |
    |---|---|
    | slide | 3 000 |
    | barrel and comp | 1 814 |
    | frame | 4 472 |
    | trigger (origin on its hinge) | 368 |
    | magazine | 388 |

  - One material on three maps: 2048 base colour, 2048 tangent normal, and a
    1024 ORM (AO softened to 0.35–1). They were baked in Cycles at 16 spp from
    the hero materials, in 145 s.
  - A `grip_socket` empty sits on the backstrap where the web goes.
  - The GLB is 4.5 MB.
- **Hero gun close-ups:** `data/build/lookdev/20261013T081000Z-pistolH2-hero/`.
  - `{hero,studio}_{q34l,right,top,muzzle}.png` at preview quality,
    1600×1000.
  - `hero_{slide_cu,comp_cu,grip_cu}.png`.
- **Hands on the gun:** `data/build/lookdev/20261013T081000Z-pistolH2-hands/`.
  - `{hero,turntable}_ready_{front,side,r,top}.png` at preview quality, 1000
    px, `--pct 100`.
  - `hands.json`: pierce `ready` `{l: {}, r: {}}`.
  - `regress.json`: pierce is 0 / 0 in stand, cuff, walk, ready, walk+pistol
    and stand+pistol. The gun is hidden in stand, cuff and walk, and shown in
    the poses that hold it.
- **Draw shot:** `data/build/hero/20261013T063042Z-pistolH2-draw/draw.png`,
  from `hero.sh --preview --shots draw --no-turntable`.

The PNGs to look at first:

1. `20261013T081000Z-pistolH2-hero/hero_q34l.png`
2. `20261013T081000Z-pistolH2-hero/studio_right.png`
3. `20261013T081000Z-pistolH2-hero/hero_comp_cu.png`
4. `20261013T081000Z-pistolH2-hands/hero_ready_front.png`
5. `20261013T081000Z-pistolH2-hands/turntable_ready_r.png`
6. `20261013T080000Z-pistolH2-game/render/studio_q34l.png`

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
- **Still plain.**
  - The comp side flats are flat.
  - The rail and dust cover are simple extrusions.
  - Edge wear is subtle. It shows on the comp's and the sights' edges, but
    hardly on the slide.
- **Materials: hold under both rigs.**
  - The nitride, polymer and stipple separate.
  - The bronze hood is the one warm note. Under the hero rig it reads olive
    rather than bronze from the right side, because it is lit by teal.
- **Grip proportions (orchestrator point 3): improved.** The grip is longer
  and slimmer, the flare and pad are modest, and the stipple border is clean.
  - The tang is a pointed wedge from the side. A softer, rounder tip would
    read better.
- **Game asset: met** (≤ 12k tris, 0 validator errors, 1–2k maps).
  - The atlas packing is loose. Many small islands leave about 40 % of the
    sheet unused.
  - The GLB under the studio light shows a soft smudge on the slide's flank,
    from the 1-segment bevels' shading.
- **Two-hand grip, 0 interpenetration: met** (pierce 0 / 0, strong hand
  and support hand).
  - The strong index lies along the frame above the trigger guard, never on
    the trigger.
  - The support hand wraps the strong fingers, with its index under the
    guard.
  - The support thumb lies forward along the frame.
- **Grip compromises.**
  - The strong thumb is **wrapped low round the back of the grip and along
    the left of the frame**, not high under the slide. This hand's thumb root
    and palm pad cannot reach the classic high-thumb position without cutting
    through the backstrap. In the front view it reads as two thumbs forward,
    but from the left the strong thumb is mostly hidden by the support hand.
  - The support wrist is bent hard (about 40°).
  - The strong fingers curl only to ×0.47 of the authored shape. They touch
    the gun, and the middle finger rides just under the guard.
  - I would call it a credible thumbs-forward grip at game-cinematic
    distance. It is not a firearms-instructor-perfect grip.
- **The gun in the draw shot: present, but it does not read.** The shot
  looks down the muzzle at 50 % preview resolution. The gun is a small, dark,
  foreshortened block between the hands. A 3/4 camera, or the `--final`
  resolution, would show it. The framing is Track E's.
- **The gun stays out of the other shots: met.** It is hidden in every pose
  without a hold, so portrait, profile and eye are unchanged.
- **Low hold: implemented but not rendered.** `walk+pistol` and
  `stand+pistol` hold it one-handed at pierce 0 / 0, but I have not checked
  them visually (the thigh clearance in walk, for example). shots.py is
  unchanged.
- **G's settle and E's `bladed()`: kept.** They are untouched. The pistol
  settles through `hand_pose.settle`, and `ready` is still E's bladed high
  ready.
- **corr_fist: no effect on the grip.** On the F round-2 build it stays at 0
  in `ready`: the grip curl is under its 45 % dead zone.
