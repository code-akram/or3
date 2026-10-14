# T15: head hair volume, silhouette, hairline, engine tone

Branch `worktree-agent-acdf73f04f95082e8`. The final run is **a4**, `data/build/lookdev/20261014T203210Z-t15-a4`. It was built at e54e211. HEAD 95d40c9 has the same parameters.

The before run is `data/build/t15/base`, a copy of `lookdev/20261014T184620Z-t12-b2` built from main be74470. Its engine frames were re-shot with the T10 viewer (main 4809be0).

**Verdict: the IoU and per-region luminance targets are not met.**
- **Silhouette:** the ¾ IoU is 0.826 against a target of 0.9.
- **Luminance:** engine hair is still 1.2–2.0× the Cycles hero's luminance per region.
- **Asset fix limit:** the luminance cannot be fixed from the asset side. A viewer lobe change that would fix it is recommended below, with A/B numbers.
- **Constraints:** the hero colour, p10, triangle and glTF constraints hold.

## Gate pictures (100 % head crops, `data/build/t15/gate/`)

All pictures are 100 % crops of 1024² frames at the T15 head cameras. The camera frame is 0.56 m high at 85 mm, at the az given, under the studio lights. The panels are: before (engine) | after (engine) | Cycles hero strands.

- `t15_trip_three_quarter.png`: ¾ view (az 40°).
- `t15_trip_profile.png`: profile (az 90°).
- `t15_pair_front_hairline.png`: front hairline, after (engine) | Cycles hero. The before run has no head-framed front camera.
- `t15_iou_base_a4_tq_pr.png`: silhouette overlays at ¾ and profile, base then a4. Red is hero-only, green is game-only, grey is both.
- `t15_engine_closeup_hero_a4.png`: engine `closeup:hero` (T10's hero-rig closeup).
- `t15_hero_portrait_crop_a4.png`: Cycles hero portrait crop (preview), used for the r/g check.

**Honest read of my own ¾ engine frame at 100 %:**
1. Under the studio lights the engine hair still reads mid-brown with bright, streaky tan highlights, nowhere near the near-black of the Cycles hero. Under the hero rig (`closeup:hero`) it reads dark brown and much closer.
2. The crown and back contour now sit on the hero's, but the temple shows a hard dark smudge of cap and hairline cards ahead of the hero's hairline. The lengths over the shoulder end about 3 cm short of the hero's, in separated spiky clumps rather than one continuous fall.
3. The new M and widow's peak are visible but subtle at this size, and the fly-aways now read as a few real strands instead of sub-pixel noise. Overall it still reads as game cards: shorter, lighter and flatter than the hero.

## Metrics

| Metric | Target | Before (base) | After (a4) |
|---|---|---|---|
| Silhouette IoU, ¾ (head cam) | ≥ 0.90 | 0.8205 | **0.8263** ✗ |
| Silhouette IoU, profile | report | 0.8536 | 0.8668 |
| Silhouette IoU, front (head cam) | report | (not staged) a1: 0.7897 | 0.8546 |
| Silhouette IoU, lookdev closeup | report | 0.7763 | 0.8245 |
| Engine / Cycles hair luminance, crown | 0.85–1.15 | 1.49 | 1.70 ✗ |
| Engine / Cycles luminance, side | 0.85–1.15 | 1.92 | 1.96 ✗ |
| Engine / Cycles luminance, back | 0.85–1.15 | 1.69 | 1.55 ✗ |
| Engine / Cycles luminance, front falls | 0.85–1.15 | 1.23 | 1.23 ✗ |
| Engine / Cycles r/g, crown | 0.85–1.15 | 1.13 | 1.125 ✓ |
| Engine / Cycles r/g, side | 0.85–1.15 | 0.976 | 1.019 ✓ |
| Engine / Cycles r/g, back | 0.85–1.15 | 1.047 | 1.040 ✓ |
| Engine / Cycles r/g, front falls | 0.85–1.15 | 1.29 | 1.229 ✗ |
| Hero hair r/g, portrait crop PNG (main9 1.284) | ≤ 1.412 (+10 %) | 1.380 (T12) | **1.393** (+8.5 %) ✓ |
| Hair test p10 | ≥ 0.0314 | 0.0367 (T12) | **0.0328** ✓ |
| Scalp hair tris | ≤ 2× (46.1 k) | 23,034 | **21,206** (−8 %) ✓ |
| glTF errors | 0 | 0 | **0** ✓ |
| T10 closeup parity, hair mean (`hairparity`) | ±20 % | 1.069 | 1.384 ✗ |
| T10 crown / back ratio, engine vs Cycles | — | 1.129 vs 0.634 | 0.771 vs 0.867 |
| Fly-away cards | fewer, thicker | 60 × 1.2 mm half-width, 3 strands per cell | 30 × 2.6 mm, 6 strands per cell, 1.0× strand px |
| Hairline cards | — | 139 | 105 |

**Tone pooling.** The pooled numbers are taken over the head views. Base is ¾, profile and closeup; a4 adds front. Each pixel is a pure region pixel, eroded 2 px, inside the eroded game mask. The engine value comes from the Standard-view `lin_<view>.png` divided by 2^exposure; the Cycles value comes from the scene-linear EXR.

**Why the T10 closeup parity rose from 1.07 to 1.38.** The parity mean is taken over the hero strand mask, and the cards now fill more of it:
- The engine p10 rose from 0.0087 to 0.0205, because the gaps that used to count as near-black are now covered.
- The engine p90 rose from 0.81 to 0.99.
- The p50 ratio is 1.03 (0.1023 vs 0.0993).

On card pixels alone the tone barely moved; the region rows above show this. T10's spatial crown/back balance did move toward Cycles: the engine went from 1.129 to 0.771, against 0.867 for Cycles.

## How the masks are made (`hair_test.py --parts views`, then `views_measure`)

**Cameras.**
- `views` writes `hair_test/views/engine_stage.json`, with head cameras: the target is head_mid − 9 cm, 85 mm, 0.56 m frame, at az 40 / 90 / 0.
- The engine and Cycles use the same cameras, so the viewer reads `lookdev.cameras`.

**Hero mask.**
- The scalp groom strands are rendered as emitters in Cycles, with every mesh as a holdout.
- A pixel counts if alpha ≥ 0.5.

**Game mask.**
- The GLB's `hair_export` meshes (cap and cards) are rendered in Cycles with the viewer's cut-out.
- Coverage is albedo alpha × (alpha > `hair.alphaTest` 0.32), which is the coverage a hashed alpha resolves to.
- Every other GLB mesh is a holdout. A pixel counts if alpha ≥ 0.5.

**IoU.**
- IoU is computed on those two masks.
- It is reported per height third, as game-only and hero-only pixel counts.
- An overlay `hv_<view>_iou.png` is written for each view.

**Regions.**
- Each groom curve's root is classified around head_mid: front falls (kind 2); crown (elevation ≥ 45°); back (|az| ≥ 120°); side (everything else).
- The regions are written as a curve attribute and rendered as an emitter colour code.

`bench/m1/hair_views.sh [--measure] RUN` runs the whole chain. Engine shots go to port 8798 under a flock.

## What changed (`blender/character/hair_groom_cards.py`, `hair_groom.py`)

1. **Card colour follows the hero model.**
   - `CARDS.albedo` random_color, root_dark, tip_light and radial_roughness are `None`, which means they are inherited from `hair.groom.shader` (T12: random 0.08, tip_light 0). Melanin and redness already came from the groom.
   - Effect: per-region r/g is within 15 % of Cycles for crown, side and back. The front falls are 1.23×.
   - A3 tried a separate `front_path` 0.45 for the falls. It made them redder (1.29×), so it is kept as a `None` hook.
2. **Lengths.** `CARDS.length` {pct 80, under_pct 70, fade 0.12} (`clump_profile` `length`):
   - Mid, top and under cards now run to the p80 / p70 strand length, on one arc grid. T9 used the members' mean length, which lost the cut's long strands.
   - The centreline is the live strands' fade-weighted mean, and the cell draws each strand to its own end.
   - In a3, p92 / p85 made the tips sparser and lowered ¾ IoU, so it was reverted.
3. **Top-card lift.** `top_lift` raised from 80 / 12 mm to p90 / 15 mm, which moves the crown contour onto the hero's outer envelope.
4. **Hairline.**
   - **Groom M.** `hair_groom` `hairline.recess_m` went from 11 to 14 mm. The left side recess went from [1.0, 0°] to [0.85, −2°]; the right stays [1.3, 4°]. This gives an asymmetric M.
   - **Widow's peak.** A new `hairline.peak` adds two notches 7 mm deep at ±11° around −3° (σ 4.5°), with the right side at 0.7×. That leaves an off-centre widow's peak between them.
   - **Cards and cap.** They follow the groom roots. The hairline cards are sparser (5.5 → 6.5 mm), narrower (2.5–5.5 → 1.8–4 mm) and finer (cell strands 0.6×), and they start one groom point behind the root (`root_skip`).
   - **Cap edge.** The cap's core alpha follows root density, over [0.55, 0.95] instead of [0.3, 0.75]. Each cap strand's alpha now ramps with the root density at its root (`edge_alpha` [0, 0.75]).
5. **Fly-aways.** 60 → 30 cards, half-width 1.2 → 2.6 mm, each cell 6 strands at full lock-strand width (T9: 3 strands at 0.85×).
6. **Tips.** `tip_width` 0.5 → 0.7 and atlas `tip_alpha` 0.15 → 0.3. In a5, `tip_width` 0.5 measured lower at every view.

## Runs

| Run | Change | ¾ | Profile | Front | Closeup |
|---|---|---|---|---|---|
| base `t15/base` | main be74470 | 0.8205 | 0.8536 | — | 0.7763 |
| a1 `20261014T191418Z-t15-a1` | colour model, peak 5 mm, fly-aways | 0.8505 | 0.875 | 0.7897 | 0.8027 |
| a2 `20261014T192740Z-t15-a2` | + p80 lengths, cap edge alpha, thinner hairline, lift 90 / 15 | 0.8484 | 0.8675 | 0.7988 | 0.8079 |
| a3 `20261014T195642Z-t15-a3` | + stronger M / peak, p92 lengths, tip 0.7 / 0.3, root skip, cap [0.55, 0.95], front_path 0.45 | 0.8274 | 0.8761 | 0.8496 | 0.8286 |
| **a4** `20261014T203210Z-t15-a4` | a3 with lengths back to p80 / p70, front_path off | **0.8263** | **0.8668** | **0.8546** | **0.8245** |
| a5 `20261014T205840Z-t15-a5` | a4 with tip_width 0.5 | 0.8152 | 0.859 | 0.8412 | 0.8159 |

The hero portrait is in `data/build/hero/20261014T205911Z-t15-a4`.

**Build-to-build noise.** About ±0.02 IoU is noise from regrooming, not from parameters:
- The groom change regenerates every root, so the clump membership and the 10 shared lock cells change.
- Between a2 and a4, the ¾ low-third hero-only pixels went from 2868 to 4603 with the lengths reverted. The lock cells' mean coverage was the same (0.58–0.89).
- This is why a1 and a2 beat a4 at ¾ while a4 wins at front and profile.

I kept a4 because it is the only run that carries the hairline task, which needs the groom change.

## Why ¾ IoU stops at ~0.83 (a4: hero 75.7 k px, game 73.4 k)

- **Game-only pixels: 5.9 k.**
  - **Cap: about 3.4 k.**
    - Most of these are at the temple and hairline, where the cap runs about 5 mm ahead of the hero's ≥ 0.5 coverage edge.
    - Thinning the cap by root density did not pull it back, so the cap shell boundary itself (`keep`, edge taper) is the next lever.
  - **Hairline cards: about 0.7 k.**
- **Hero-only pixels: 6.2 k**, mostly the lowest third.
  - **Tips: about 4.6 k.**
    - The hero's lengths run about 3 cm further over the shoulder.
    - On the profile, a projection test shows the cards lie within 4 mm of those strand points (median). So the missing pixels are coverage, not geometry.
    - The lock cells' tails are sparse once most strands have ended, and the hashed-alpha cut drops them below 0.5. In profile about 40 % of the hero-only pixels are covered by card geometry with no alpha cut at all.
    - The card vertices are not inside the jacket (24 of 1269 low vertices near it).
  - **Neck: a small band.** On the profile, a band behind the ear and down the neck is covered by under-card centrelines that pass behind the neck, where the hero strands pass in front of it.
- **Next steps (not done):**
  - A tail-density term in `raster_clump`: compress each strand's v toward the card end, so the cell's tail keeps its coverage.
  - Pull the cap shell boundary back with the groom's feather.
  - Push under-card centrelines to the outer side of the neck.
  - Expect each to be worth 0.01–0.03, against ±0.02 of regroom noise.

## Recommendation for the viewer owner (T10): hair lobes / surface depth

I did not edit `params.ts` or `materials/*`. I ran A/B tests on the a4 GLB with `?params=` over the four head views, using the same measurement as above. Luminance is engine / Cycles; ✓ means within ±15 %.

| `?params=` (hair) | Crown | Side | Back | Front | T10 closeup parity |
|---|---|---|---|---|---|
| current (scatter 0.008, R 0.0175, TT 0.36) | 1.70 | 1.96 | 1.55 | 1.23 | 1.384 |
| surfaceDepth 0.15 | 1.43 | 1.11 ✓ | 1.28 | 0.90 ✓ | — |
| surfaceDepth 0.15, spec1 0 (R off) | 0.92 ✓ | 0.98 ✓ | 0.76 | 0.74 | — |
| surfaceDepth 0.15, tt 0 | 1.32 | 0.44 | 1.15 ✓ | 0.43 | — |
| **surfaceDepth 0.12, spec1 0.01** | 1.25 | 1.16 | 1.09 ✓ | 0.88 ✓ | **0.882** ✓ |
| scatter 0.004 (a2) | 1.27 | 1.65 | 1.35 | — | — |
| albedoGain 1.0 (a2) | 1.27 | 1.66 | 1.35 | — | — |

**What the A/B tests show.** Side-mass excess is TT through the full layer, and T10's `surfaceDepth` (currently 0) is the right knob for it. The crown and back excess is the R lobe on the top cards.

**Recommendation.** Use `surfaceDepth` ≈ 0.12 with `spec1` 0.0175 → 0.010.
- It brings back and front within ±15 %, with side at 1.16 and crown at 1.25.
- It also brings T10's closeup parity to 0.88.
- It needs re-checking against T10's per-light closeups before adoption.

**Front-fall r/g.** The front falls stay at 1.23–1.26× r/g under every lobe setting. That is the asset's front-fall albedo, a T15 leftover.

## Leftovers

1. **¾ IoU is 0.826, short of the 0.9 target.**
   - The remaining gaps are the cap at the temple, the sparse lock-cell tails and the under cards behind the neck.
   - Regroom noise of ±0.02 means any single change needs several builds to confirm.
2. **Engine hair luminance is 1.2–2× Cycles per region under the studio lights.**
   - This is viewer-side; see the recommendation above.
   - Under the hero rig the engine hair reads dark brown.
3. **Front-fall card r/g is 1.23× Cycles.** It needs a calibrated front-fall albedo; a lower path made it redder.
4. **T10 closeup parity went from 1.07 to 1.38**, from better coverage and brighter p90. It goes back within ±20 % with the recommended lobe change.
5. **Widow's peak.** It is in the groom and the cards, but subtle at 100 % front. The hero shows it more clearly than the engine.

## Gate checks

- `cd web && npm run build`: ok. A fresh worktree needed `npm run build:core` first for the wasm module.
- `bash bench/m1/test_containment.sh`: 69 passed, 0 failed.
- `python3 -I provenance/audit.py --data-root <main>/data --check-files --release`: 178 records, 0 errors, 0 warnings.
