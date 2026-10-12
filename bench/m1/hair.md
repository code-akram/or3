# m1 scalp hair (collar-length, swept back)

The scalp hair is **generated layered hair** built by script in `blender/character/`, post-staging on the baked body, after the suit, so it follows head edits, body macros and the final collar. The spec is [`look-spec.md`](look-spec.md) §3; the direction is face C + collar length (`variants/direction.json`), styled after the John Wick character: long dark brown-black hair to the collar, a slightly off-centre part, pushed back off the forehead, tucked behind the ears, a few heavier strands falling forward at one temple, piecey thin locks, not fluffy, not a helmet. The face is not touched by this track.

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

## Construction

**Stage order.** `build_character.py` runs `hair.post` after `suit.post`, so the hair colliders see the final suit split (`<human>.suit_<part>_export`).

**Landmarks** (`HeadFrame`, rest pose, world space): cranium centre (midway front to back over `scalp`, midway crown to ear centre), the ear band from `ears`, mouth from `lips`, chin from the lowest head-weighted point in front, neck and shoulder heights from `neck_01` and `upperarm_*`. Each ear is also an **ellipsoid** (centre and radii of its `ears` ≥ 0.5 vertices), listed in `stats.head_frame.ear_ellipsoids`.

**Colliders**: the body plus every suit part in one BVH, with the ear faces left out (thin two-sided flaps that flung strands sideways). The ears are handled by the ellipsoids instead: a guide point inside an ellipsoid grown by the strand's offset plus `ear_margin_m` is pushed out along its gradient.

**Hair** (one mesh `hair`, three materials). The layers, from the inside out:

1. **Growth region and roots.** MPFB's `scalp` group plus a landmark-bound temple and nape band (`region.*`). Roots are a Fibonacci spread ray-cast onto it: under 36, top 360.
2. **Guides.** Each root is marched in 1 cm steps, deterministically:
   - Comb back from the hairline, away from an off-centre part (+12 mm, the character's left; `part_push` 0.5 decaying over `part_width_m` 3 cm), with a little drop for side roots.
   - While touching the head the step is projected onto the surface (`turn` 0.6). Gravity takes over behind the crown or below the ear lobes, **but is held off while the point is above an ear and not yet behind it**, and the desired direction gets a +y push there: side strands slide back along the skull and **tuck behind the ears** rather than draping over them. The ellipsoid push keeps them out of the ear.
   - Hanging strands get a slow **lateral wave** (`wave`: direction amplitude 0.35, 10–15 cm period, random phase per strand), so the lengths cross instead of hanging as a curtain of parallel verticals.
   - Every step is pushed out of the colliders by the layer's offset plus a 1.5 mm gap and a 0–8 mm layer jitter.
   - **Tip height** = `neck_01` z + `length.f` × (shoulder-joint z − `neck_01` z) ± jitter. `shoulder` uses f = 0.85, `collar` (the direction) f = 0.05, jitter 15 mm.
3. **Cap** (`hair` material). The growth faces pushed out 2.5 mm, the edge tapered into the skin over 3 rings, the boundary relaxed along the skin (6 iterations). **Its UV v is the depth from the cap's open boundary** (`cap.v_span_m` 3 cm, clamped under 1), u the arc length round the head. The texture is the `edge` kind, like the beard's old feather: 1,200 fine short hairs (0.12–0.24 mm wide, 9–23 mm long, combed back along +v, slant 0.06). 60 % start in the **feather band** (`edge_v` 0.3 → 9 mm), whose density ramps as depth² (`ramp_pow` 2) and whose hairs grow from 35 % length at the edge to full; the opaque core starts at an uneven line beyond it. So the hairline is a **density ramp of fine hairs over about 1 cm with skin showing through**, instead of the old cap outline with three ragged rings. The cap's vertex colour is 0.75 (darker than the cards), which is what shows at the part.
4. **Under layer** (`hair_under` material): 36 wide (16 mm), flat (4 : 1) opaque 6-sided tubes hugging the scalp, ending 4.5 cm short of the top layer. They keep the `tip` texture (opaque core to v 0.62, strand tips beyond) so their ends feather; vertex colour 0.7, texture value 0.42: the dark mass seen in the gaps.
5. **Top layer** (`hair_cards` material): 360 **curved, twisted cards**, 3 vertices wide, centre lifted by 0.35 × half-width, each twisted root → tip by a random angle up to ±1 rad, so locks turn and catch the light differently. Half-width 8 mm ± 35 %, widening 15 % where a card hangs free; the taper `1 − 0.7·t^1.3` leaves a flat, square-ish tip that the texture feathers. Roots start at 60 % width, but **cards rooted within 2.5 cm of the cap's edge start at 20 %** (hairline cards always), so no card root shows as a dark notch in the feather band.
   - **Lock atlas.** The card texture is 512 × 512 with **4 variants side by side**; each card samples one variant (u range). A variant has 1–3 **sub-locks**: 13 strands each, clustered round a lock centre (σ 16 px = 2 mm), with its own root start and tip, the strands' tips spread under the lock's tip (`tip_sigma_v` 0.14, tapered over 10 % of the length), the density falling off toward the card edges. So a card reads as two or three thin piecey locks with see-through gaps and a feathered end, and neighbouring cards differ (`variant_sigma` 0.15 in value).
6. **Hairline cards**: narrow cards rooted on the cap's **ring-1** vertices (one ring inside the boundary, so the feather band lies in front of them), from in front of the ears round the forehead; 43 on face C. They are combed back with the rest and twisted like top cards.
7. **Front fall**: 4 cards rooted at the hairline on the character's right (azimuth 28–38.5°, elevation 22°), 15 mm segments, no twist, rounder (`curve` 0.5), combed down with a 0.3 **surface hug** (pulled toward the skin when clear of it), so they drape along the temple and cheek to about 3.5 cm above the lips: the asymmetric break of the helmet silhouette (spec). The left group exists in the config at `count` 0: two short cards there read as painted stripes on the temple.
8. **Flyaways**: 70 thin cards (3 mm) leaving random top and hairline guides 8–70 % of the way down, drifting 1.5 cm out with a wave; none where the guide's normal points up (`max_up` 0.6), which used to leave sticks standing on the crown.

**Per-vertex colour `lock`** (exported as **COLOR_0**, float RGB, multiplied into the base colour): per-clump lognormal value (σ 0.22) × depth (cards lifted higher in the layer jitter are lighter, `depth` 0.35) × a dark root (0.8 at the root rising to 1 by v 0.3) × the layer's base (under 0.7, cap 0.75, hairline 0.85 × , front 0.85, top 1.0). This is the under-layer-darker / highlights-on-top read without extra textures, and the runtime shader can keep using it.

**Strand textures** (`hair_mesh.strand_image`, numpy, packed into the `.blend` and exported in the GLB):
- `edge` kind (cap): described above. `tip` kind (under tubes): 260 strands over 256 × 512, opaque below `core_v`. `card` kind (cards, flyaways): the lock atlas above. The card sampler is EXTEND (no wrap); the cap and tubes REPEAT across u.

All three hair materials export as glTF `alphaMode: MASK` (`export.fix_alpha`, `hair_export` in `b.cutouts`).

**Materials** (look-dev Principled, placeholders for the runtime TSL shader): roughness 0.62, specular 0.15, **anisotropy 0.4** with the tangent from the UV map rotated a quarter turn so the lobe stretches across the fibres (exported as `KHR_materials_anisotropy` strength 0.4, rotation π/2; the runtime ignores it). The brief's "matte to slight sheen": most of the sheen is the rim light on the twisted cards.

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

| | Before (`20261012T104352Z-direction-c-collar`, main) | After (`20261012T112210Z-hair2-v9-rebased`, on main + facial hair) |
|---|---|---|
| Hair tris | 21,196 (319 top + 67 hairline + 7 front cards, 36 tubes, cap 816, flyaways 1,364) | **22,312** (clumps 20,428: 360 top + 43 hairline + 4 front cards, 36 tubes; cap 816; flyaways 1,068) |
| Beard | 5,918 (card beard) | 14,000 (shell beard, facial-hair track) + brows |
| LOD0 total | 61,953 | 72,519 |
| Bones | 53 | **65** (12 hair) |
| Validator / max weights | 0 errors / 4 | 0 errors / 4 |
| Tip z p10 / p50 / p90 (target 1.584) | 1.566 / 1.579 / 1.593 | 1.565 / 1.579 / 1.593 |
| Width / skull at eye level (≤ 1.35) | 1.095 | 1.145 (the side masses now clear the ears) |

Cycles sign-off (1024², 128 spp + OIDN): `20261012T111950Z-hair2-v8-signoff` (pre-rebase config, card beard) and the final `…-hair2-final-signoff`. The hair build adds about 3 s; the lock atlas and the feather texture are most of it.

**Budget**: hair 22.3k of the ~30k it may use; hair + beard + brows ≈ 37k, LOD0 72.5k of 120k.

## Iteration log (quality pass 2, judged on `hair_inspect` sheets at 1024²)

| Run (`data/build/lookdev/…`) | Change | Result |
|---|---|---|
| `104611Z-hair2-base` | baseline of the direction (face C, collar) | Hard jagged cap edge on the forehead, side mass a sheet of parallel streaks, ear buried, one dark value. |
| `110009Z-hair2-v1` | cap depth-UV + feather texture; lock atlas; vertex colour; ear ellipsoids and tuck; twist; anisotropic material; springs | Ears tucked, no cap outline. But the lock atlas was saturated (each lock an opaque strap with a square end), the ear ellipsoid (built from weight > 0.05) pushed the front falls off the face, and the sheen was plastic. |
| `110300Z-hair2-v2` | 13 strands per lock, feathered lock tips; ellipsoid from weight ≥ 0.5; no ear push for front falls; longer, sparser feather hairs | Locks separate. Front falls still straps; under tubes sampled the feather texture backwards (sparse roots, solid blunt tips); dark root bars at the hairline. |
| `110717Z-hair2-v3` | under tubes get their own `tip` material; root width by distance to the cap edge; root shade 0.8; front-fall hug off, comb_side 0.15; darker cards, specular 0.2 | Hairline clean. Front falls still a rigid curtain (5 segments); front chains unbound. |
| `111112Z-hair2-v4` | front falls 15 mm segments, hang from 2 cm, roots at azimuth 20° | Front falls became opaque bars across the forehead (too far forward); straight vertical curtain at the back; 36 under-tube spikes under the hem. |
| `111400Z-hair2-v5` | lateral wave on hanging strands; front falls back at 28° with a 0.3 hug; under tubes narrower, ending 4.5 cm higher; less widening; specular 0.15, anisotropy 0.4 | **The back ¾ reads as piecey locks with depth.** 12 bones bound. Left front falls still painted stripes; a flyaway stood up on the crown. |
| `111601Z-hair2-v6`, `111734Z-hair2-v7` | no crown flyaways; left front falls thinner, then removed | Accepted look. |
| `111836Z-hair2-v8` | side chains 3 bones (12 total without front_l) | Pose test and Cycles sign-off. |
| `112210Z-hair2-v9-rebased` | rebased on main (shell beard and brows) | The hairline sits well over the new brows; the sideburn's top meets the temple hair's lower edge with a small skin gap in profile. |
| `112441Z-hair2-v10-temple` | temple band 1 cm lower, to close that gap | Worse: cap faces wrap over the ear's front, brownish cap texture shows over the ear. Reverted; v9 is the keeper. |

## Known limits and next steps

- **Front falls** read as a few straight dark ribbons on the cheek. They drape by a surface hug; a real lock would curl away at the end. A curl term in the march (or a second, shorter card per fall) is the next step.
- **Hairline cards**: 43, because ring 1 at the front has fewer vertices than `count` 64. Rooting on rings 1 and 2 alternately would give the number.
- **Temple gap**: in profile, a triangle of skin between the temple hair's lower edge and the beard's sideburn. Lowering the growth band wraps the cap over the ear (v10). The fix is a few short cards rooted on the temple band's lower edge falling onto the sideburn, not more cap.
- **Determinism**: two builds of the same config give close-up IoU 0.994 (profile 1.000). Something in the hair or suit stage is not bit-stable (BVH or KD-tree tie-breaking is the suspect); the earlier pass claimed 1.000 but was not re-measured here.
- **Sheen**: in Cycles the crown's anisotropic highlight is a little strong at the sign-off exposure; specular 0.12 would be the matte end. The runtime shader decides this anyway.
- **Ears** are fully exposed; no strand crosses the ear top. The reference often has one. The ellipsoid push plus a per-strand "over the ear" flag would do it.
- **No strand curl or wave across the crown**: the top still lies flat and reads smooth where the light is flat; the lock structure shows where the rim light catches the twisted cards.
- **Spring parameters** live in this file, not in the GLB (see the binding plan).
- **The look-dev loop's 512² close-up is too coarse** to judge strand detail. Use `hair_inspect.py`.
- The `hair_inspect.py` closeup azimuth (25°) is the key-light side; the shadow side has not been inspected at 1024².
