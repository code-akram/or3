# m1 hair and beard (wave 2)

The stock MPFB card hair (`long01`, light brown, down to the waist) is replaced by **generated clump-mesh hair** and a **beard**, both built by script in `blender/character/`. They are generated post-staging on the baked body, so they follow head edits and body-macro changes. The spec is [`look-spec.md`](look-spec.md) §3.

| File | What |
|---|---|
| `hair.py` | Stage hooks. `add` keeps the old MPFB card path; `post` measures the head, then builds the hair and the beard. |
| `hair_frame.py` | `HeadFrame`: landmarks and colliders, all from MPFB's topology-bound vertex groups (`scalp`, `lips`, `ears`, `head`) and the rig. No fixed coordinates. |
| `hair_clumps.py` | Roots, guide curves and clump tubes; the scalp cap. |
| `hair_beard.py` | Beard region, shell and tufts. |
| `hair_mesh.py` | Shared plumbing: body-derived shells, edge relaxing, tapered tubes, skinning, the look-dev material. |
| `config.py` → `hair` | All parameters (defaults = the `shoulder` variant). |
| `variants/hair-shoulder.json`, `variants/hair-collar.json` | The two length options for the direction checkpoint. |

## Construction

**Landmarks** (`HeadFrame`, rest pose, world space):
- Cranium centre: midway front to back over the `scalp` group, and midway between the crown and the ear centre.
- Ear band from the `ears` group, mouth from `lips`, chin from the lowest head-weighted point in front.
- Neck and shoulder heights from the `neck_01` and `upperarm_*` joints.

**Colliders**: the body plus the suit meshes in one BVH. Ear faces are left out: they are thin flaps whose two-sided normals kicked strands outward, so the hair now passes over them.

**Hair** (one mesh `hair`, skinned 100 % to `head`):
1. **Growth region.** MPFB's `scalp` group, plus the band it leaves bare: the temples in front of and above the ears, and the nape above the neck. Both are bound to landmarks (`region.*`).
2. **Roots.** A Fibonacci spread of directions from the cranium centre, ray-cast onto the growth faces. The count is iterated to about `clumps` (68).
3. **Guides.** Each root is marched in 1 cm steps, deterministically:
   - Comb back from the hairline, pushed away from an off-centre part (+12 mm, to the character's left). Side roots get extra drop, so they sweep back over the ears.
   - While touching the head, the step direction is projected onto the surface tangent. A `turn` of 0.6 keeps strands hugging the surface.
   - Gravity takes over once the strand is behind the crown or below the ear lobes.
   - Every step is pushed out of the colliders by the clump's half-thickness plus a 1.5 mm gap, plus a 0–2 mm layer jitter. A strand stops at its tip height.
   - **Tip height** = `neck_01` z + `length.f` × (shoulder-joint z − `neck_01` z), ± jitter. `shoulder` uses f = 0.85, `collar` f = 0.05.
4. **Front fall.** Two thinner clumps rooted at the front hairline on the character's right. They are combed down and to the side from the start, and hang past the temple to cheekbone height. This breaks the helmet silhouette asymmetrically, per the spec.
5. **Clumps.** Each guide is resampled to segments of about 3.5 cm (5–12 per clump) and swept into a 6-sided tube, flattened 3.6 : 1 so it lies flat on the surface.
   - Half-width 22 mm ± 20 %. The taper `1 − t^1.6` holds the width and narrows late; the root starts at 55 %.
   - Where a clump hangs free it widens by up to 50 %, so the back mass reads as a sheet rather than noodles.
   - Each root ring starts 3 mm under the skin and 12 mm upstream, so the open end is hidden and lies along the scalp; an early version had root rings standing up like fins.
6. **Cap.** The growth-region faces, pushed out 2.5 mm, with the edge tapered over 3 rings into the skin. The hairline boundary is **relaxed along the skin** (6 iterations), so it is a smooth curve instead of a staircase of faces. Same material as the hair, so the gaps between clumps read as hair.

**Beard** (one mesh `beard`, keeping the skin weights of the faces it covers: `head` and `neck_01`):
- **Region**: body faces whose vertices are all inside two lines in profile (y, z), not in `lips` or `ears`, and in front of the ear.
  - The **cheek line** runs sideburn → a 2 cm dip under the cheekbone → 9 mm above the mouth corner.
  - The **neckline** runs from 5.5 cm under the ear centre to 8 mm under the chin. That is about 2 cm above the Adam's apple, and it clears the shirt collar (at 2 cm below the chin, the shell dipped 15 mm into the collar).
- **Shell**: boundary relaxed along the skin (6 iterations), offset 5 mm (+3 mm below the mouth), edge tapered over 3 rings.
- **Tufts**: 24 short 3-sided spikes (6–10 mm) on the down-facing under-jaw, inside the edge, for profile breakup.

**Runtime data already in the mesh** (for banded Kajiya-Kay, NOTES §7):
- **UV0**: `u` around the clump, `v` root → tip. The tangent is +v. `export_tangents` is on.
- **UV1** (`strand`): (per-clump random, side sign) for hue jitter and the shift texture.
- For the planned spring chains, `v` doubles as `spring_weight` (0 at the root, 1 at the tip). The cap and beard have v = 0.
- No textures or alpha yet. Flyaway cards and alpha-to-coverage edges are left for the shading pass.

**Material**: flat look-dev Principled, hair `#1d1915` at roughness 0.5, beard `#201a15` at 0.6. These are placeholders for the runtime TSL shader.

## Numbers

All runs: 53 bones, max 4 weights per vertex, 0 glTF-validator errors. There are 10 `NODE_SKINNED_MESH_NON_ROOT` warnings, one per skinned mesh, the known category. The build adds about 0.6 s.

| Run (`data/build/lookdev/…`) | Hair tris (clumps + cap) | Beard tris (shell + tufts) | Total | Tip z p10 / p50 / p90 (m) | Width at eye level |
|---|---|---|---|---|---|
| `20261012T092830Z-hair-shoulder` | 9,084 (8,268 + 816), 68 clumps | 892 (676 + 216) | 49,817 | 1.471 / 1.485 / 1.505 (target 1.493) | 0.199 m, 1.09 × skull |
| `20261012T092857Z-hair-collar` | 7,080 (6,264 + 816) | 892 | 47,813 | 1.562 / 1.574 / 1.587 (target 1.579) | 0.197 m, 1.08 × skull |
| `20261012T091345Z-hair-base` (stock MPFB hair, for reference) | 4,108 (`long01`) | — | 43,949 | down to z = 1.07 | — |

**Budgets** (look-spec §5): hair 8,000–9,500 (shoulder 9,084 ✓; collar 7,080, under because the strands are shorter); beard ≤ 2,500 ✓; hair + beard ≤ 12k (9,976 and 7,972 ✓). The spec puts the shoulder-line tips at z ≈ 1.48–1.52 at 1.85 m, and the shoulder p50 is 1.485 ✓. Width ≤ 1.35 × skull ✓.

**Checks:**
- **Deterministic.** The same config rebuilds an identical result: 49,817 tris and IoU 1.000 in all 4 views (`20261012T093047Z-hair-shoulder-repeat` against `hair-shoulder`).
- **Stock path unchanged.** `{"hair": {"asset": "long01.mhclo", "clumps": null, "beard": null}}` rebuilds the 43,949-tri baseline with IoU 1.000 (`20261012T092948Z-hair-stockcheck`).
- **Robust to the body.** A body at 2.04 m, more muscle, different proportions and a different race mix (`20261012T092925Z-hair-robust`) gets a correctly fitted cap, beard and tips (tip target 1.661). Nothing is hard-coded to the stock head.
- **Clipping (shoulder run, rest pose), vertices more than 2 mm inside:**
  - Hair vs body: 1 of 5,933, at the ear, which is not a collider by design.
  - Hair vs suit: 7, where the hair lies against the shirt collar at the side of the neck (worst 9.9 mm).
  - Beard vs body and vs suit: 0.
  - Root rings and the cap, which are buried on purpose, are excluded from the count.

**Reproduce:**
```sh
bench/m1/lookdev.sh --config bench/m1/variants/hair-shoulder.json hair-shoulder
bench/m1/lookdev.sh --config bench/m1/variants/hair-collar.json hair-collar
```
Pass `--prev <run>` explicitly when comparing. `latest` is shared with the other m1 tracks and was pointing at a head-track run during this work.

## Iteration log (best-of-N by eye plus the metrics above)

| Run | Change | Result |
|---|---|---|
| v1 | first pass: 56 round-ish clumps (r 12 mm), 3 front falls, face-selected beard | Read as dreadlocks. Front falls arched like spider legs. Beard edge was a staircase, with comb-teeth tufts on the neckline. |
| v2 | wider, flatter clumps (r 20 mm, 2.6:1); temple/nape growth band; soft-offset beard edge | Better mass. The temple was still bare; beard stairs persisted. |
| v3 | flatter (3.2), lower comb drop, `turn` 0.6 | Closer to the head. Root rings stood up as fins at the hairline. |
| v4 | buried, upstream root start; **boundary relaxation** for the cap and beard | The hairline and beard line became smooth curves. This was the biggest single win. |
| v5 | side drop over the ears, late taper, gravity below the ear lobes | Some strands were kicked out sideways by ear collisions. |
| v6 | ears out of the colliders; clumps widen when hanging; front falls moved to the temple | Swept-back mass, sheet-like back. Accepted as the shoulder base. |
| final | beard neckline 8 mm under the chin (was 20 mm) | Removed the 15 mm beard-in-collar penetration. |

## Known limits and next steps

- **No spring bones yet.** The whole mass is 100 % `head`, so shoulder-length hair will swing rigidly through the shoulders when the head turns. Planned: 4 chains × 3 bones (back mass L/R, two front falls), bound by UV0 `v` (look-spec §5 bone plan). The collar variant suffers less.
- **Stage order.** `hair.post` runs before `suit.post`, so any suit change made in `suit.post` (the suit track's waistcoat and collar) is invisible to the hair colliders. Moving `hair.post` after `suit.post` in `build_character.py` would fix it. I didn't change it, because that file is the driver.
- **Spec items not done:** flyaway cards (15–30 alpha cards) and alpha-to-coverage edges need textures and the shading pass. The brows are still MPFB cards (spec stopgap).
- **Close-up look.** At close range the top still shows individual ribbon ridges with slick highlights. Painted textures and banded shading should carry it. At game distance the silhouette reads as long, dark and swept back.
- **Beard and hairline:** both follow topology groups. If the head track moves the `lips`/`ears` regions a lot, re-check `cheek_dip_m` and `moustache_m`.
