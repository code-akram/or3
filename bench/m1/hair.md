# m1 scalp hair (collar-length, swept back)

The scalp hair is **generated layered hair** built by script in `blender/character/`, post-staging on the baked body, after the suit, so it follows head edits, body macros and the final collar. The head refine stage (dense face, re-planarised, 4k skin) runs *after* the hair; `bench/m1/hair_fit.py` checks the hairline against that refined surface on the shipped GLB. The spec is [`look-spec.md`](look-spec.md) §3; the direction is face C + collar length (`variants/direction.json`), styled after the John Wick character: long dark brown-black hair to the collar, a slightly off-centre part, pushed back off the forehead, tucked behind the ears, a few heavier strands falling forward at one temple, piecey thin locks, not fluffy, not a helmet. The face is not touched by this track.

The beard and brows moved to shell texturing in the facial-hair track: see [`facial-hair.md`](facial-hair.md). The card beard described in earlier versions of this file is gone.

| File | What |
|---|---|
| `hair.py` | Stage hooks. `add` keeps the old MPFB card path; `post` measures the head, then builds the scalp hair, the beard and the brows. |
| `hair_frame.py` | `HeadFrame`: landmarks, colliders and the two **ear ellipsoids**, all from MPFB's topology-bound vertex groups (`scalp`, `lips`, `ears`, `head`) and the rig. No fixed coordinates. |
| `hair_clumps.py` | Roots, guide curves and the layers: cap, under tubes, top cards, hairline cards, front falls, flyaways; per-vertex colour and the hang distance for the springs. |
| `hair_springs.py` | The spring-bone chains: bones on the staged armature and the hang-distance binding. |
| `hair_mesh.py` | Shared plumbing: body-derived shells, edge relaxing, tapered tubes, twisted curved cards, generated strand textures (tip / card-atlas / edge kinds), skinning, look-dev materials. |
| `config.py` → `hair.clumps` | All parameters (defaults = the `shoulder` length; `direction.json` sets collar length). |
| `bench/m1/hair_inspect.py` | 1024² head renders of a look-dev run from 6 views (eyes only, no metrics). |
| `bench/m1/hair_fit.py` | On a run's GLB: the cap's edge rings against the **refined** body (mm, per ring), hair under the skin, and the collar zone against the suit. |
| `bench/m1/hair_springtest.py` | Poses the 12 spring bones and renders back / side / close-up at 0° and 35°. |

## Construction

**Stage order.** `build_character.py` runs `hair.post` after `suit.post`, so the hair colliders see the final suit split (`<human>.suit_<part>_export`).

**Landmarks** (`HeadFrame`, rest pose, world space): cranium centre (midway front to back over `scalp`, midway crown to ear centre), the ear band from `ears`, mouth from `lips`, chin from the lowest head-weighted point in front, neck and shoulder heights from `neck_01` and `upperarm_*`. Each ear is also an **ellipsoid** (centre and radii of its `ears` ≥ 0.5 vertices), listed in `stats.head_frame.ear_ellipsoids`.

**Colliders**: the body plus every suit part in one BVH, with the ear faces left out (thin two-sided flaps that flung strands sideways). The ears are handled by the ellipsoids instead: a guide point inside an ellipsoid grown by the strand's offset plus `ear_margin_m` is pushed out along its gradient.

**Hair** (one mesh `hair`, three materials). The layers, from the inside out:

1. **Growth region and roots.** MPFB's `scalp` group plus a landmark-bound temple and nape band (`region.*`). Roots are a Fibonacci spread ray-cast onto it: under 36, top 360.
2. **Guides.** Each root is marched in 1 cm steps, deterministically:
   - **Root.** The first guide point is 6 mm upstream of the root, snapped to the skin and buried 3 mm; the strand emerges at skin level (root + 1 mm) and its stand-off grows over the next steps through the collision push. (A straight 12 mm segment from under the skin to a root already lifted to its stand-off bridged the hollow temple of face C as a dark wedge in profile.) The first mesh row sits at the buried point and is a near-point (10 % width), the second at the root.
   - Comb back from the hairline, away from an off-centre part (+12 mm, the character's left; `part_push` 0.5 decaying over `part_width_m` 3 cm), with a little drop for side roots.
   - **Volume** (`volume`, `Strand.lift`): every strand carries an extra stand-off from the skull along its length: 0 at the root, rising to its amplitude over `rise_m` 6 cm, held `hold_m` 3 cm, decaying over `fall_m` 8 cm to `keep` 0.4 of it (the back keeps 4 mm). Amplitude: `top_m` 10 mm on the crown (root normal up) blending to `side_m` 2 mm on the sides and nape, x (0.8-1.2 by the card's layer jitter, so the layers stack) x (0.6-1 random); under tubes x 0.6, hairline cards x 0.4. The collision push realises it: the strand is kept `off + lift` from the colliders while it lies on the skull, so the top stands ~1 cm off the scalp before it falls, and the layers show as locks over locks instead of a wet shell.
   - While touching the head (within its stand-off + 6 mm) the step is projected onto the surface (`turn` 0.6). Gravity takes over behind the crown or below the ear lobes, **but is held off while the point is above an ear and not yet behind it**, and the desired direction gets a +y push there: side strands slide back along the skull and **tuck behind the ears** rather than draping over them. The ellipsoid push keeps them out of the ear.
   - **Hanging** (gravity weight > 0.5): the direction blend per step rises to `hang_turn` 0.85 and the strand leans toward the head axis by `cling` 0.2, so the lengths drop close along the neck instead of belling out on the momentum they had leaving the skull. A slow **lateral wave** (`wave`: amplitude 0.25, 10-15 cm period, random phase per strand) crosses the lengths so they are not a curtain of parallel verticals. Below the jaw and in front of the ear line, `neck_tuck` 0.5 pushes side lengths back (+y) so they hang beside the neck and the collar's side, not forward over the shirt collar and the lapel.
   - **Colliders.** The skin (ear faces left out) and the suit are separate BVHs (`HeadFrame.signed(p, cloth_gap)`): the nearer one by true distance decides, the suit inflated by `cloth_gap_m` 4 mm, so strands hover over the collar and lapel with a shadow instead of being painted on. (Taking the smaller *signed* distance instead was wrong: far above a collar edge the collar's plane distance is near zero, and it pushed every hanging strand 6-7 cm outward into a bell.) Garments are **solid to the hair**: a suit face whose normal points at the neck axis is flipped, so a strand that reaches the collar from the neck side is pushed out over it instead of being trapped between neck and collar (which left 15 % of the hair inside the collar and showed as black chips through the shirt collar). Every step is pushed out by the layer's offset plus a 1.5 mm gap, a 0-8 mm layer jitter and the volume lift.
   - **Tip height** = `neck_01` z + `length.f` x (shoulder-joint z - `neck_01` z) +- jitter. `shoulder` uses f = 0.85; `collar` (the direction) f = 0.25, jitter 20 mm: the ends lie about 2 cm over the jacket collar (collar top 1.583 m, tips p50 1.561) instead of stopping at its edge as a row of points against the shirt.
3. **Cap** (`hair` material). The growth faces pushed out 2.5 mm, the edge tapered into the skin over 3 rings, the boundary relaxed along the skin (6 iterations). **Its UV v is the depth from the cap's open boundary** (`cap.v_span_m` 3 cm, clamped under 1), u the arc length round the head. The texture is the `edge` kind, like the beard's old feather: 1,200 fine short hairs (0.12–0.24 mm wide, 9–23 mm long, combed back along +v, slant 0.06). **The image wraps in v as well as u** (one sampler mode per texture, in Blender and in glTF), so the pattern lives in rows `v_band` [0.08, 0.92] with the rest transparent and the cap's v runs 0.10-0.88: at the open edge v = 0 used to be filtered together with the opaque core at v = 1, which drew a dark line along the whole hairline and solid black slivers wherever a cap face lay entirely on the boundary (the "black streak" at the temple in profile). 60 % start in the **feather band** (`edge_v` 0.3 → 9 mm), whose density ramps as depth² (`ramp_pow` 2) and whose hairs grow from 35 % length at the edge to full; the opaque core starts at an uneven line beyond it. So the hairline is a **density ramp of fine hairs over about 1 cm with skin showing through**, instead of the old cap outline with three ragged rings. The cap's vertex colour is 0.75 (darker than the cards), which is what shows at the part.
4. **Under layer** (`hair_under` material): 44 wide (16 mm), flat (4 : 1) opaque 6-sided tubes hugging the scalp (lifted 0.6 x the volume), ending 1.5 cm short of the top layer so the mass reaches the collar. They keep the `tip` texture (opaque core to v 0.7, strand tips beyond, pattern in `v_band` [0.04, 0.92] with the tube's v mapped 0.06-0.88 for the same wrap reason as the cap) so their ends feather; vertex colour 0.7, texture value 0.42: the dark mass seen in the gaps. Their first ring is a near-point like the cards' first row.
5. **Top layer** (`hair_cards` material): 360 **curved, twisted cards**, 3 vertices wide, centre lifted by 0.35 × half-width, each twisted by a random angle up to ±1 rad **peaking mid-length and flat again at the tip** (`tw · sin πt`; a twist that peaked at the tip turned the free ends edge-on over the collar: dark shards), so locks turn and catch the light differently. Half-width 8 mm ± 35 %, widening 5 % where a card hangs free; the taper `1 − 0.7·t^1.3` (`tip_width` 0.3) leaves a narrow tip that the texture feathers. Roots start at 60 % width, but **cards rooted within 2.5 cm of the cap's edge start at 20 %** (hairline cards always), so no card root shows as a dark notch in the feather band.
   - **Lock atlas.** The card texture is 512 × 512 with **4 variants side by side**; each card samples one variant (u range). A variant has 1–3 **sub-locks**: 22 strands each (0.3-0.6 mm wide, wave 3 px), clustered round a lock centre (σ 14 px), with its own root start and tip (0.5-0.95), the strands' tips spread under the lock's tip (`tip_sigma_v` 0.14, tapered over 18 % of the length), the density falling off toward the card edges. So a card reads as two or three thin piecey locks with see-through gaps and a feathered end, and neighbouring cards differ (`variant_sigma` 0.15 in value).
6. **Hairline cards**: narrow cards rooted on the cap's **ring-1** vertices (one ring inside the boundary, so the feather band lies in front of them), from in front of the ears round the forehead; 43 on face C. They are combed back with the rest and twisted like top cards.
7. **Front fall**: 2 cards rooted at the hairline on the character's right (azimuth 34-39°, elevation 22°), 15 mm segments, half-width 0.35 x a top card, a little twist (0.3), no wave, rounder (`curve` 0.5), combed down with a 0.15 **surface hug** but kept `clear_m` 6 mm off the skin so they cast a shadow instead of reading as a painted stripe, and from 9 cm on a `flare` 0.12 that curls the end away from the cheek. They drape along the temple and cheekbone to about 3.5 cm above the lips: the asymmetric break of the helmet silhouette (spec). The left group exists in the config at `count` 0.
8. **Flyaways**: 70 thin cards (3 mm) leaving random top and hairline guides 8–70 % of the way down, drifting 1.5 cm out with a wave; none where the guide's normal points up (`max_up` 0.6), which used to leave sticks standing on the crown.

**Per-vertex colour `lock`** (exported as **COLOR_0**, float RGB, multiplied into the base colour): per-clump lognormal value (σ 0.22) × depth (cards lifted higher in the layer jitter are lighter, `depth` 0.35) × a dark root (0.8 at the root rising to 1 by v 0.3) × the layer's base (under 0.7, cap 0.75, hairline 0.85 × , front 0.85, top 1.0). This is the under-layer-darker / highlights-on-top read without extra textures, and the runtime shader can keep using it.

**Strand textures** (`hair_mesh.strand_image`, numpy, packed into the `.blend` and exported in the GLB):
- `edge` kind (cap): described above. `tip` kind (under tubes): 260 strands over 256 × 512, opaque below `core_v`. `card` kind (cards, flyaways): the lock atlas above. The card sampler is EXTEND (no wrap); the cap and tubes REPEAT across u.

All three hair materials export as glTF `alphaMode: MASK` (`export.fix_alpha`, `hair_export` in `b.cutouts`).

**Materials** (look-dev Principled, placeholders for the runtime TSL shader): roughness 0.68, specular 0.1, **anisotropy 0.3** with the tangent from the UV map rotated a quarter turn so the lobe stretches across the fibres (exported as `KHR_materials_anisotropy` strength 0.3, rotation π/2; the runtime ignores it). The brief's "slightly greasy, not wet": the sheen is the rim light on the twisted cards; the crown reads dry because it is lifted and layered, not because of the material.

**The three materials reach the GLB.** Until pass 3 `hair_mesh.finish` set the material slots *after* `bm.to_mesh`, and `Mesh.materials.clear()` resets every face's `material_index` to 0, so the whole hair shipped as one primitive on the cap's feather material: the cards and tubes rendered with the `edge` texture (opaque above v 0.3, feathered at the *root*). The lock atlas and the tip texture described above were never visible in passes 1-2; the "flat opaque straps with square tips" were that. The indices are now written back after the slots are set (3 primitives: cap 816, cards ~21k, tubes ~6k tris).

## Runtime data in the mesh (banded Kajiya-Kay, NOTES §7)

- **Fibre direction** = the UV0 **v** axis, root → tip on tubes, cards and flyaways (flyaways map v 0.3 → 1; the cap's v is depth from the hairline, which is also the comb direction there). glTF `TANGENT` is the **u** axis (MikkTSpace), so in the shader the fibre tangent is the bitangent: `T = cross(N, tangent.xyz) * tangent.w`. The sign does not matter for Kajiya-Kay. `v` itself is the root-to-tip coordinate for the root darkening and the tip fade.
- **UV1** (`strand`): (per-clump random, side sign) on tubes and cards, (0.5, 0) on the cap: hue jitter and the shift-texture offset.
- **COLOR_0**: the per-lock value above.
- **Alpha**: MASK at 0.5 everywhere; the runtime adds alpha-to-coverage for the card edges and a fixed alpha test in the shadow pass (spec §3.3).

## Spring chains (`hair_springs.py`)

The plan (look-spec §5: 12 hair bones) is implemented at build time, so the hero GLB ships **65 bones**: the 53 of `game_engine` plus 12 hair bones parented to `head`, named `hair_<sector>_<k>` and found by name at runtime.

- Every clump vertex records a **sector** and `hang_s`, metres past the point where its strand stops lying on the skull and starts to hang: the first guide point clear of the colliders, or below ear level behind the head; front falls hang from 2 cm past their root. Sectors are decided at the hang point: `back_l/r` (behind the cranium centre), `side_l/r`, `front_l/r` (the front falls); l/r follow the rig's `upperarm_l` side, not the world x sign.
- Each configured sector becomes a chain (`springs.chains`: back 2 + 2, side 3 + 3, front_r 2 = 12 bones; `front_l` is in the config but builds nothing while it has no cards). The chain's knots split the sector's 90th-percentile hang length evenly; a station is the mean position of the sector's vertices near that hang distance, so the bones lie on the mass's mean hanging path. A sector with fewer than `min_verts` (20) hanging vertices stays on `head`.
- **Weights by hang distance**: `head` 1 at the hang point → 0 at the first knot; bone *k* is a hat (0 at knot *k*, 1 at *k*+1, 0 at *k*+2), the last bone stays 1 past its tail. At most two chain bones plus `head` per vertex, so ≤ 4 weights holds (measured max 4). On face C, 8,787 of 17,512 hair vertices are rebound; the cap keeps the body's skin weights.
- Checked with a pose test (`bench/m1/hair_springtest.py`, writes `spring_*.png` into the run's `hair/` folder): rotating `hair_*_01` by 35° and `*_02/_03` by 25° swings the lengths as masses while the scalp part stays put, with no tearing at the hang points.
- **Runtime binding plan (what the Rust spring sim needs)**: for each chain, the bone list in order (the parent of `_01` is `head`), rest-pose head/tail positions (in the skin), and per chain: stiffness ≈ 0.6 (sides and back) / 0.45 (front), drag 0.25, gravity 0.35 m s⁻², a hit radius of 1.5 cm per joint, colliders = head sphere (the cranium centre, radius ≈ 10 cm), neck capsule (`neck_01` → `head`) and the two shoulder capsules (`upperarm_*` → `lowerarm_*`, which the collar-length hair barely reaches). These numbers are starting values for m2 tuning on the Air; they are not in the GLB (the exporter drops custom properties unless `export_extras` is on, which is track A's call).

## Numbers

| | Pass 2 (`20261012T112210Z-hair2-v9-rebased`) | Pass 3 baseline on main 75eba80 (`20261012T122430Z-hair3-base`) | **Pass 3 final** (`20261012T132430Z-hair3-final2`, main 75eba80 + this branch) |
|---|---|---|---|
| Hair tris | 22,312 | 22,852 | **27,548** (clumps 25,556: 360 top + 43 hairline + 2 front cards, 44 tubes; cap 816; flyaways 1,176) |
| GLB primitives (materials) | 1 (`hair` only: the index bug) | 1 | **3**: `hair` 816, `hair_cards` ~21k, `hair_under` ~6k |
| LOD0 total | 72,519 | 119,918 (with refine, 4k skin) | **124,614** |
| Bones | 65 | 66 | 66 (12 hair) |
| Validator / max weights | 0 / 4 | 0 / 4 | **0 / 4** |
| Tip z p10 / p50 / p90 | 1.565 / 1.579 / 1.593 (collar top 1.583) | 1.565 / 1.574 / 1.590 | **1.540 / 1.560 / 1.575** (2 cm over the jacket collar) |
| Width / skull at eye level (<= 1.35) | 1.145 | 1.145 | **1.18** |
| Cap edge ring 0 / 1 over the *refined* skin (mm, p50) | - | 0.49 / 1.24 | **0.50 / 1.24** (designed 0.5 / 1.25; 4 of 126 edge vertices <= 0.1 mm under) |
| Hair vertices > 0.5 mm under the skin | - | 9.9 % | **8.2 %** (the buried root rows) |
| Spring rebound vertices | 8,787 | 9,081 | 11,822 (back 10.9k, sides 0.88k, front 42) |

Budget: hair 27.5k of the ~30k it may use; hair + beard + brows ~43k; LOD0 124.6k of the ~120k target (150k cap). The hair stage takes ~5 s.

Cycles sign-off (1024², 128 spp + OIDN): `20261012T132433Z-hair3-final2-signoff`. Spring pose test: `…-hair3-final2/hair/spring_{back,side,closeup}_{0,35}.png`.

## Iteration log (quality pass 3: volume, collar, front falls, temple streak; judged on `hair_inspect` sheets at 1024² and 2-3x crops)

Fast loop: `head.refine: null` in the config drops a build from ~150 s to ~30 s and the hair is byte-identical (`fastD` = `v2`), so the hair iterations ran without the refine stage and the final runs with it.

| Run (`data/build/lookdev/…`) | Change | Result |
|---|---|---|
| `122430Z-hair3-base` | main 75eba80 as merged (new suit, refine) | Crown plastered and shiny, flat black strands on the shirt collar and lapel, front falls as stripes, a black wedge in front of the temple in profile, the cards opaque straps. **Found: the GLB has one hair primitive**, every face on the cap material (`materials.clear()` reset the indices); true of every hair run so far. |
| `123424Z-hair3-v1` | material indices fixed; volume lift (14 mm); separate cloth BVH with 6 mm gap; root snapped; front falls 6 mm off the skin with flare; sheen down | Locks and the feather read for the first time. But the hair belled out to width/skull 1.70, a brush of stubs stood up at the part, the back was a broom of fine parallel strands, the front falls a zig-zag ribbon in the air, the temple wedge unchanged. |
| `124450Z-hair3-v2` | lift 10 / 2 mm over 6 cm; cling + faster turn when hanging; wave 0.25; denser lock atlas (22 strands, wider, longer feathered tips); thinner card tips; front falls tamer | Back reads as layered locks. Bell still 1.59. |
| `fastA/B/C` | bisect with the refine off | The bell came from the two-tree `signed()` taking the smaller *signed* distance (a collar edge's plane distance is ~0 far above it), not from the lift. |
| `125344Z-hair3-v3` | nearest tree by true distance; first card quad short (buried point -> root); hairline twist halved | Width 1.16. Crown dry and layered, forehead feather clean, front collar clean. Tips ended at the collar edge as points against the white shirt collar; wedge still there. |
| `125606Z-hair3-v4` | collar hair 2 cm longer (`direction.json` f 0.25, jitter 20 mm); tip width 0.3; cloth gap 4 mm; 2 thinner front falls; hairline lift 0.4 | Ends over the jacket collar, but the shirt-collar band showed through as chips: strands trapped between neck and collar (15 % of the hair under the skin). |
| `125854Z-hair3-v5`, `130210Z-hair3-v6` | under tubes to 1.5 cm above the tips; **garments solid to the hair** (inward suit normals flipped); tube first ring a near-point | Hair lies over the collar, under-skin share back to 7.4 %. Wedge still there (not flyaways, not hairline cards, not tubes: `isoA`, `isoB`, probes). |
| `130745Z-hair3-v7` | cards emerge at skin level, stand-off grows by the push | Wedge still there. Projecting the hair faces into the side camera found it: **cap faces on the boundary, all v = 0**, and the cap texture wraps in v. |
| `131411Z-hair3-v9` | pattern in a v band, transparent rows at both ends; cap v 0.10-0.88, tube v 0.06-0.88 | **Wedge gone**; the hairline lost its dark edge line too. |
| `131634Z-hair3-v10` | twist peaks mid-length (flat tips); 44 under tubes; tube core to v 0.7 | The keeper. Collar ends still ragged at 2x (below). |
| `131844Z-hair3-final` | v10 with the head refine | Full build. The Cycles close-up showed a brush of short bristles standing up along the front hairline: flyaways starting at the first 10-70 % of the guide (some within a centimetre of the root) and the hairline cards lifted 0.4 x the volume. |
| `132430Z-hair3-final2` | flyaways start 25-70 % along the guide; hairline lift 0.3 | Full build, pose test, Cycles sign-off. |

## Known limits and next steps

- **Collar ends.** At 2x on the back view the ends over the jacket collar are a row of dark card and tube ends hovering 4 mm over the collar, the shirt-collar band showing between them; at the sheet scale it is a ragged hair edge. Card hair ends want a curl under and alpha-to-coverage; the runtime shader (spec §3.3) will soften the edge, and a short "end curl" term in the march (bend toward the collar surface over the last 3 cm) is the next geometric step. Earlier, with the tips at the collar edge, they read as a comb of points against the white collar, which was worse.
- **Front fall** is now one thin loose lock at the right temple, off the skin with a shadow and a slight curl at the end. It still falls straight; a real lock would also turn with the cheekbone. The second card is behind it.
- **The hair over the ear top** is a stack of flat side cards passing to the tuck behind the ear; at 3x it reads as a shelf. Narrower cards in the ear zone, or one or two strands allowed over the ear, would break it.
- **Hairline feather** reads as a brush of uniform fine strokes at 2x; more width and length variance in the `edge` texture would make it wispier. At 512² (the look-dev close-up) MASK minification thickens it into a harder edge; `hair_inspect` at 1024² is the judge, and alpha-to-coverage is the runtime fix.
- **Geometry vs refined head**: verified with `hair_fit.py`: the cap edge sits where it was designed (0.5 / 1.25 / 2.0 mm rings) over the refined, re-planarised forehead; no refit stage is needed. Re-check if the head track moves the hairline skin by more than ~0.5 mm.
- **Texture wrap**: the cap and tube images wrap in v; the pattern is squeezed into a band and the UVs stay inside it with margins of 0.02-0.04 (~10-20 rows), which holds up to mip level ~4. The runtime sampler can clamp v and drop the band.
- **Determinism**: not re-measured this pass.
- The `hair_inspect.py` closeup azimuth (25°) is the key-light side; the shadow side has not been inspected at 1024².
- Spring parameters live in this file, not in the GLB (see the binding plan).
