# m1 hair and beard (wave 2 + quality pass)

The stock MPFB card hair (`long01`, light brown, down to the waist) is replaced by **generated layered hair** and a **beard**, both built by script in `blender/character/`. They are generated post-staging on the baked body, after the suit, so they follow head edits, body-macro changes and the final suit collar. The spec is [`look-spec.md`](look-spec.md) §3.

The **quality pass** (2026-10-12) replaced the first version's opaque flattened tubes with:
- curved alpha cards over an opaque under-layer,
- generated strand textures,
- a beard with volume, a ragged edge and card tufts.

The brief was "matte, layered, no rope or plastic look". The user raised the budget for it: about 35k tris for hair and beard, and up to about 120k for LOD0.

| File | What |
|---|---|
| `hair.py` | Stage hooks. `add` keeps the old MPFB card path; `post` measures the head, then builds the hair and the beard. |
| `hair_frame.py` | `HeadFrame`: landmarks and colliders, all from MPFB's topology-bound vertex groups (`scalp`, `lips`, `ears`, `head`) and the rig. No fixed coordinates. |
| `hair_clumps.py` | Roots, guide curves and the hair layers: cap, under tubes, top cards, hairline cards, front falls and flyaways. |
| `hair_beard.py` | Beard region, shell and tufts. |
| `hair_mesh.py` | Shared plumbing: body-derived shells, edge relaxing, tapered tubes, curved cards, strand textures, skinning, the look-dev materials. |
| `config.py` → `hair` | All parameters (defaults = the `shoulder` variant). |
| `variants/hair-shoulder.json`, `variants/hair-collar.json` | The two length options for the direction checkpoint. |
| `bench/m1/hair_inspect.py` | 1024² head renders of a look-dev run from 6 views (eyes only, no metrics). |

## Construction

**Stage order.** `build_character.py` runs `hair.post` after `suit.post`, so the hair colliders see the final suit split (`<human>.suit_<part>_export`).

**Landmarks** (`HeadFrame`, rest pose, world space):
- Cranium centre: midway front to back over the `scalp` group, and midway between the crown and the ear centre.
- Ear band from the `ears` group, mouth from `lips`, chin from the lowest head-weighted point in front.
- Neck and shoulder heights from the `neck_01` and `upperarm_*` joints.

**Colliders**: the body plus the stock clothes and every `.suit_` part, in one BVH. `stats.hair_colliders` lists them. Ear faces are left out: they are thin flaps whose two-sided normals kicked strands outward, so the hair passes over them.

**Hair** (one mesh `hair`, two materials, skinned 100 % to `head`). The layers, from the inside out:
1. **Growth region and roots.** The growth region is MPFB's `scalp` group plus a landmark-bound temple and nape band (`region.*`). Roots are a Fibonacci spread ray-cast onto it. Each layer has its own root count: under 36, top 320.
2. **Guides.** Each root is marched in 1 cm steps, deterministically:
   - Comb back from the hairline, away from an off-centre part (+12 mm, to the character's left). Side roots get extra drop over the ears.
   - While touching the head, the step is projected onto the surface (`turn` 0.6). Gravity takes over behind the crown or below the ear lobes.
   - Every step is pushed out of the colliders by the layer's offset plus a 1.5 mm gap and a 0–4 mm layer jitter.
   - **Tip height** = `neck_01` z + `length.f` × (shoulder-joint z − `neck_01` z), ± jitter. `shoulder` uses f = 0.85, `collar` f = 0.05.
3. **Cap.** The growth faces pushed out 2.5 mm, the edge tapered into the skin over 3 rings, and the hairline boundary relaxed along the skin (6 iterations).
   - It carries the under-layer strand texture: v = 0.3 inside, which is opaque, and v = 0.70 / 0.66 / 0.62 on the outer rings. That gives a slightly broken hairline, not a painted line.
4. **Under layer** (the mass, `under`): 36 wide (20 mm), flat (4 : 1), opaque 6-sided tubes that hug the scalp and end 1.5 cm short of the top layer.
   - The texture is darker (`base_value` 0.42) and has an opaque core up to v = 0.62, with strand tips beyond that.
   - It is what you see in the gaps of the top layer, so the head never shows through.
5. **Top layer** (the visible hair): 320 curved cards, each 3 vertices wide with the centre lifted by 0.25 × half-width.
   - Half-width 9.5 mm ± 35 %, widening up to 35 % where a card hangs free. The taper `1 − 0.7·t^1.3` ends in a flat, square-ish tip, not a point.
   - The roots start at 60 % width and widen over the first 12 % of the length.
   - The cards sit 3 mm over the under layer.
6. **Hairline cards**: 60 narrow cards rooted on the cap's front boundary, from in front of the ears round the forehead. The roots start at 25 % width, so the hairline is made of strands rather than the cap's edge.
7. **Front fall**: 7 cards rooted at the front hairline on the character's right, combed down and to the side. They hang past the temple to about 3.5 cm above the lips, an asymmetric break of the helmet silhouette (spec).
8. **Flyaways**: 80 thin cards (3 mm) that leave random top and hairline guides 8–70 % of the way down. They drift 2.5 cm outward with a slight wave, for silhouette breakup, including on the crown.
   - With the 0–7 mm layer jitter, the crown's silhouette is separate locks, not a smooth helmet.

**Strand textures** (`hair_mesh.strand_image`, numpy, packed into the `.blend` and exported in the GLB):
- **`tip`** (under layer and cap): 260 strands over a 256 × 512 image.
  - Each strand has a lognormal value, a wave, and a tapered tip ending at a random v in [0.72, 0.99]. Bands of lighter and darker hair run across u.
  - Alpha comes only from the strands past `core_v`.
- **`card`** (top-layer cards): 75 strands over 128 × 512. Strand density and length fall off toward the card edges (`edge_pow`, `edge_short`), and the strand roots are staggered (`root_v`).
  - So a card reads as a lock of loose hairs with no outline. The sampler is EXTEND, not REPEAT, so a card's edge never picks up the opposite edge.
- **`edge`** (beard shell): UV v = depth into the beard. 2,600 short slanted hairs (6–15 mm).
  - 55 % start in the **feather band**, whose density ramps up linearly with depth. Their length grows from 30 % (stubble) at the outer edge to full.
  - The solid part starts at an uneven line (4 wrapping sines across u), so it has no edge parallel to the beard line.
  - So the beard thins out into stubble over about 2.8 cm, not in an outline.

All hair and beard materials export as glTF `alphaMode: MASK`: `export.fix_alpha` handles objects listed in `b.cutouts`.

**Beard** (one mesh `beard`, two materials, keeping the skin weights of the faces it covers: `head` and `neck_01`):
- **Region**: two lines in profile (y, z), not in `ears`.
  - The **cheek line** runs sideburn → a 2 cm dip under the cheekbone → 9 mm above the mouth corner.
  - The **neckline** runs from 5.5 cm under the ear centre to 8 mm under the chin.
  - Each body vertex gets a signed distance to the region, plus a low-frequency ±4 mm wobble (3 sines), so the lines are irregular.
  - The **lip line feathers too**: depth is capped by (distance to the nearest lip vertex − 3 mm) × 2.5. So the moustache and the hair under the lower lip thin out toward the lips, as if grown, instead of ending at a cut-out.
  - The shell is every face with depth > −2 cm: a **2 cm stubble band** past the lines. Lip vertices (weight > 0.02) are excluded.
- **Shell**: boundary relaxed along the skin (6 iterations). Volume comes from the thickness profile:
  - 3 mm on the cheeks and moustache, 4.5 mm below the mouth, plus a 3 mm Gaussian at the chin (r 3.5 cm): fuller at the chin, thinner on the cheeks, still a *short* full beard.
  - It fades across the stubble band to a 0.4 mm floor, so the band never z-fights the skin.
- **Tufts**: 520 small curved cards (4 tris each, 8 mm long, 1.8 mm half-width) over the beard, at least 4 mm inside the lines.
  - Chin-weighted: up to 3 × denser and 1.15 × longer at the chin.
  - None where the shell faces down (normal z < −0.4, under the jaw and chin). There they hung down in a fringe and made the beard read long; the shell's texture carries that area.
  - The roots are sunk 3 mm into the shell. Growth is down along the skin, out by `lift` 0.22, plus jitter.
  - On the moustache, the tufts grow sideways away from the philtrum, with half the lift.
  - No tuft may root within 6 mm of a lip vertex, and above the mouth a tuft needs 5 mm of depth into the beard. So none crosses the lip line.
  - No tuft may cross or come within 3 mm of the clothes (an unsigned test, because the collar is a thin open shell).
- **Colour**: `#17110d` (very dark brown) with a per-strand lognormal value spread. Never `#000`.

**Runtime data already in the mesh** (for banded Kajiya-Kay, NOTES §7):
- **UV0**: v runs root → tip on tubes and cards, so the tangent is +v. `export_tangents` is on.
  - The beard shell's v is depth into the beard instead.
  - For the planned spring chains, card and tube v doubles as `spring_weight`.
- **UV1** (`strand`): (per-clump random, side sign) for hue jitter and the shift texture.

**Materials**: look-dev Principled, roughness 0.8, specular 0.12 (hair) and 0.25 (beard). This is the matte read the brief asked for. They are placeholders for the runtime TSL shader, which will use the same textures' alpha.

## Numbers

All final runs: 53 bones, max 4 weights per vertex, 0 glTF-validator errors, and every hair and beard material is `MASK`. The hair and beard build adds about 2.5 s; texture generation is most of it.

**Before → after** (face A, suit, shoulder):

| | Before (`20261012T092830Z-hair-shoulder`) | After (`20261012T102612Z-hair-hq-face-a-shoulder`) |
|---|---|---|
| Hair tris | 9,084 (68 tubes + cap) | 28,006 (432 cards and tubes + cap + flyaways) |
| Beard tris | 892 (shell 676 + 24 spikes) | 5,810 (shell 1,650 + 520 tuft cards 4,160) |
| Total LOD0 | 49,817 | 68,650 |

**Final six combos** (face variants from the head track's bolder pass, the suit from the suit track; each run has `hair/sheet.png` from `hair_inspect.py`):

| Face × hair | Run (`data/build/lookdev/…`) | Hair tris | Beard tris (shell + tufts) | Hair + beard | LOD0 total | Tip z p10 / p50 / p90 (target) | Width / skull |
|---|---|---|---|---|---|---|---|
| A × shoulder | `20261012T102612Z-hair-hq-face-a-shoulder` | 28,006 | 5,810 (1,650 + 4,160) | 33,816 | 68,650 | 1.477 / 1.493 / 1.513 (1.501) | 1.09 |
| A × collar | `20261012T102650Z-hair-hq-face-a-collar` | 20,798 | 5,810 | 26,608 | 61,442 | 1.569 / 1.581 / 1.595 (1.587) | 1.07 |
| B × shoulder | `20261012T102731Z-hair-hq-face-b-shoulder` | 28,264 | 5,862 (1,702 + 4,160) | 34,126 | 68,959 | 1.478 / 1.493 / 1.513 (1.501) | 1.09 |
| B × collar | `20261012T102813Z-hair-hq-face-b-collar` | 21,500 | 5,862 | 27,362 | 62,195 | 1.568 / 1.580 / 1.596 (1.587) | 1.13 |
| C × shoulder | `20261012T102854Z-hair-hq-face-c-shoulder` | 28,612 | 5,918 (1,758 + 4,160) | 34,530 | 69,369 | 1.475 / 1.490 / 1.509 (1.498) | 1.12 |
| C × collar | `20261012T102935Z-hair-hq-face-c-collar` | 21,168 | 5,918 | 27,086 | 61,925 | 1.567 / 1.579 / 1.593 (1.584) | 1.11 |

Hair layers (A × shoulder): under 37, top 321, front 7, hairline 67 cards. Clump tris are 25,770, the cap 816, flyaways 1,420. The whole build is 6.4–8.8 s, of which hair and beard take 2.3–3.0 s.

**Budgets** (user ruling 2026-10-12: hair + beard ≈ 35k, LOD0 ≤ 120k, hard cap 150k):
- Hair + beard is 33.8k–34.5k for shoulder and 26.6k–27.4k for collar ✓.
- LOD0 is 61k–69k ✓.
- Shoulder tips p50 sit 7 mm under the target, inside the spec's 1.48–1.52 at 1.85 m ✓. Width ≤ 1.35 × skull ✓.

**Clipping** (rest pose, exported GLB, a BVH nearest-point sign test against each suit part): hair and beard vertices within 12 mm of the shirt or jacket that are more than 5 mm on the inside.
- Beard vs shirt and jacket: 0 on face A. 5–7 on B and C: stubble-band shell, 0.4 mm off the throat skin, where the band reaches under the shirt collar. That is hidden, because the skin under it is covered too.
- Hair vs jacket: 0–6 on A and C, and 43–59 on B (wide head and neck). These are under-layer vertices tucked beneath the jacket's collar roll at the sides of the neck, hidden in every view. The march only clears a guide's centreline, so a wide tube's edge can dip under.
- A wider radius gives false positives. Up to 50 beard vertices read "inside the shirt" at 2–3 cm under the chin, against the collar's downward-facing edge, so the sign test is meaningless that far out.

**Reproduce:**
```sh
bench/m1/lookdev.sh --prev none --config bench/m1/variants/hair-shoulder.json hair-shoulder
bench/m1/lookdev.sh --prev none --config bench/m1/variants/hair-collar.json hair-collar
blender -b -t 4 --factory-startup --python bench/m1/hair_inspect.py -- data/build/lookdev/<run>
```
For a face variant, deep-merge its JSON with the hair variant into one config. `lookdev.sh` takes a single `--config`.

## Iteration log

### Wave 2 (best-of-N by eye plus the metrics)

| Run | Change | Result |
|---|---|---|
| v1 | first pass: 56 round-ish clumps (r 12 mm), 3 front falls, face-selected beard | Read as dreadlocks. Front falls arched like spider legs. Beard edge was a staircase. |
| v2 | wider, flatter clumps (r 20 mm, 2.6:1); temple/nape growth band; soft-offset beard edge | Better mass. The temple was still bare; beard stairs persisted. |
| v3 | flatter (3.2), lower comb drop, `turn` 0.6 | Closer to the head. Root rings stood up as fins at the hairline. |
| v4 | buried, upstream root start; **boundary relaxation** for the cap and beard | The hairline and beard line became smooth curves. This was the biggest single win. |
| v5 | side drop over the ears, late taper, gravity below the ear lobes | Some strands were kicked out sideways by ear collisions. |
| v6 | ears out of the colliders; clumps widen when hanging; front falls moved to the temple | Swept-back mass, sheet-like back. Accepted as the shoulder base. |
| final | beard neckline 8 mm under the chin (was 20 mm) | Removed the 15 mm beard-in-collar penetration. |

### Quality pass (judged on `hair_inspect` sheets at the look-dev exposure)

| Run (`data/build/lookdev/…`) | Change | Result |
|---|---|---|
| `…hq-beard1`, `…hq-beard2` | beard thickness profile, edge strand texture, margin band | The edge broke up and the chin gained volume. It was too brown and light, and opaque spike tufts read as pale thorns. |
| `…hq-hair3` | strand textures on the tubes; 2 layers | Strands visible, but each clump still read as a rope or plank. |
| `…hq-hair4` – `…hq-hair6` | more, thinner tubes; matte material (rough 0.8, spec 0.12); hair after suit | Matte, but more tubes just made more ropes. |
| `…hq-hair7` | **top layer → curved alpha cards** with the edge-falloff `card` texture over an opaque, darker under layer | The biggest win of the pass: loose locks instead of ropes, and a soft crown. |
| `…hq-hair8` | beard tufts → alpha cards, sunk roots, staggered strand starts; colour `#17110d` | Tufts read as hair, not scales or thorns. |
| `…hq-hair9` | hairline cards with narrow roots; cap edge v 0.70–0.62 (was 0.95–0.74, which read as a receding hairline) | Hairline is soft but full. |
| `…hq-b-shoulder-t1` | lips: tuft clearance via a lip KDTree, moustache depth minimum, lip vertices out of the shell | No more specks or cards on the lips. |
| `…100909Z-hair-hq-face-a-shoulder` | tuft–clothes test; chin length 0.3 (0.6 hung in long streaks) | Coordinator review: hair layering reads. The beard reads as a dark mass pasted on, with a hard cheek edge; it is too long and bushy below the chin; the lip line looks cut. |
| `…102259Z-hq-beard-f1` | **feather band** (1.6 cm stubble ramp, uneven solid onset); **lip feather**; line wobble; trims (jaw 4.5 mm, chin +3 mm, tufts 8 mm) | The moustache and lip line now look grown, and the profile edge feathers. Blocky tuft ends hung under the chin. |
| `…102420Z-hq-beard-f2` | band 2 cm, linear ramp, stubble 30 %; no tufts under the jaw | Short beard, with no fringe under the chin. The cheek line thins into stubble. |
| `…102523Z-hq-crown-1` | layer jitter 7 mm (was 4); 80 flyaways, from 8 % down | The crown silhouette breaks into locks, so less helmet. Accepted. |

## Known limits and next steps

- **No spring bones yet.** The whole mass is 100 % `head`, so shoulder-length hair will swing rigidly through the shoulders when the head turns. Planned: 4 chains × 3 bones (back mass L/R, front fall, possibly the flyaways), bound by UV0 `v` (look-spec §5 bone plan). The collar variant suffers less.
- **Hairline.** It is soft, but at 1024² the temple corners still show small notches where the cap edge and the first hairline cards don't quite meet. A painted hairline-density mask on the cap would fix it.
- **Beard edge vs skin.** The feather is done only with hair density: MASK alpha is binary, and the skin is not ours to texture. A stubble or shadow layer in the *skin* texture under the band (head track) would make the transition read even softer at a distance.
- **Sideburn back edge.** The edge in front of the ear is a plane (`sideburn_back_m`). Hair covers it in most views, but in a straight front view it is the straightest part of the beard outline.
- **Beard interior.** From the front, the mass is still one dark value. The 520 tufts add depth at the edges and in profile, but not much inside; a second, lighter card texture, or banded shading at runtime, would add internal structure.
- **Ear tops** can peek through the side hair on face B (wide head). Ears are not colliders by design (see above); an ear-specific offset would fix it.
- **Sorting.** Everything is alpha-*tested* (MASK), so there are no sorting problems, but the edges alias at game distance without alpha-to-coverage (runtime shader work).
- **The look-dev loop's 512² close-up is too coarse** to judge strand detail. Use `hair_inspect.py`.
- **Beard and hairline follow topology groups.** If the head track moves the `lips`/`ears` regions a lot, re-check `cheek_dip_m` and `moustache_m`. All three face variants (A, B with the wide jaw, C long) currently place correctly.
