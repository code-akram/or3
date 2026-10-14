# m1 v4 track T9b: silver plates, rim pickup, warm scatter, brows (follow-up to T9)

_Track T9b report, 2026-10-14. Brief: `t9-cards.md` "What still reads wrong", items 1, 2, 4, 5 and 6. Public build only (`bench/m1/variants/direction.json`), no fan overlay._

**Final build:** `data/build/lookdev/20261014T155504Z-t9b-b1`. Its engine frames were re-shot with the final viewer (commit `35687fa`).
**Cycles hero of the same build:** `data/build/hero/20261014T161745Z-t9b-b1`.
**Before:** T9 final `…/lookdev/20261014T145202Z-t9-c6`, copied to `data/build/t9b/dev0`. The before engine frames (`pre_*`, `prelin_*`) are main's viewer (`d9e3a46`) on that copy. They reproduce T9's parity exactly (hair 0.978).

## Gate

| Metric | Before (T9 c6) | After (T9b b1) | Target |
|---|---|---|---|
| Hair region, engine / Cycles (neutral closeup, linear mean) | 0.978 | **0.936** | ±20 % ✓ |
| Hair p10 / p50 / p90 / p99, engine (Cycles) | 0.005 / 0.117 / 0.69 / **2.04** (0.027 / 0.109 / 0.81 / 1.45) | 0.005 / 0.102 / 0.72 / **1.67** | (info) |
| Hair r/g, b/g (Cycles 1.51, 0.73) | **1.15**, 0.91 | **1.44**, 0.67 | (info) |
| Hair per light, key / fill / rim (engine / Cycles) | ≈2.1 / ≈3.0 / **≈0.52** (see note) | 1.12 / 1.43 / 0.85 | (info) |
| Beard region | 1.147 | **1.090** | ±20 % ✓ |
| Brows region (new, blue mask from `brows_hero`) | 0.820 (p50 0.078 vs 0.161) | **1.031** (p50 0.135 vs 0.161) | ±25 % ✓ |
| Hero portrait: hair beside the face, luminance relative to the forehead (Cycles 0.098) | 0.238 (2.4x) | 0.124 (1.27x) | (info) |
| Same box, blue relative to the forehead's (Cycles 4.09) | **6.40** | 4.42 | (info) |
| Crown box, relative luminance (Cycles 0.120) | 0.120 | 0.114 | (info) |
| Hair + beard + brows tris | 35,886 | **35,978** (23,034 + 11,952 + 992) | ≤ 40,000 ✓ |
| glTF validator | 0 errors, 16 warnings | **0 errors**, 16 warnings | ✓ |

Notes on the table:
- **Per-light "before" numbers.** These are approximate: the T9 lobes with the old jitter, run on the new code path (`?lights=` does not exist in main's viewer). The exact per-light baseline cannot be measured with main's viewer.
- **Portrait boxes.** These are fixed boxes, not masks:
  - Engine boxes are in the 1920 × 1080 frame and Cycles boxes in the 960 × 540 EXR.
  - Both are normalised by a forehead box, which cancels the exposure and white-balance difference between the engine's Standard/`post=0` output and the Cycles EXR.
  - Script: `/tmp/t9b/pbox.py` (scratch).

**Pictures** (in `data/build/t9b/gate/`):
- `closeup_before_after_cycles.png`: neutral closeup, engine T9 | engine T9b | Cycles hero strands of the b1 build (AgX).
- `portrait_before_after_cycles.png`: hero rig, engine T9 | engine T9b | Cycles hero of b1.
- `portrait_head_before_after_cycles.png`: the same at 100 %, head only.

Individual frames:
- b1 engine: `…-t9b-b1/{game_*,lin_closeup,linp_portrait}.png`.
- b1 Cycles: `…-t9b-b1/hair_test/parity_cycles*.{png,exr}` (including per-light `_key/_fill/_rim`) and `hero/…-t9b-b1/portrait.png`.

## 1. Silver plates: root cause and fix

**Root cause.** The plates came from the shader, not mainly from the geometry. The lobe-shift jitter reads the strand ID from the ORM map (B). That map is half-res and trilinear filtered. At closeup distance a front-lock card is minified about 3-4×, so the sampled ID is the mip average of many strands, about 0.5. The jitter therefore went to about 0, and every texel of a wide, straight card sat at the same Kajiya-Kay angle. With `spec1` 0.19 against a near-black albedo (median linear 0.008 / 0.002 / 0.0001), a card at the highlight angle is about 12× its own diffuse: a white sheet. `layer_spec` 0.4 only dimmed it.

**Viewer fixes** (`web/src/character/materials/index.ts`, `HairMaterial`):
- `hair.idLodBias` -2: the ID and root-tip used for the jitter are read at a sharper mip.
- Per-card jitter (`cardJitter` 0.1): the COLOR_0 per-card value, hashed.
- A slow wave tilt along each strand (`waveTilt` 0.2, 1-2.5 waves root to tip, phase and frequency from the ID). This stands in for the groom's wave, which tilts fibres out of the card plane.
- The strand occlusion (root, density and back-of-card AO) now also scales the lobes (`specAO` 1). T9 only darkened the albedo.

**Geometry fix** (`hair_groom_cards.py`, `CARDS.front_lock`): each front fall is now 2 strips instead of one wide card.
- Strip half-width ×0.6, centres at ±0.45 hw.
- The two strips twist in opposite directions, 8° → 40° root to tip, and cross.
- The V profile is deeper (`curve` 0.6).
- Cost: +92 tris (8 front_lock cards, up from 4). The RNG stream of the other layers is unchanged.

**Result:** no white sheets in the closeup or the portrait. The locks read as darker, separated strands.

## 2. Rims on the hair

The engine already had the light-linked desaturated hair twins:
- `export_rig.py` writes `rim_hair`, `kicker_hair` and `fill_hair` with receivers, and `stage.ts` links them per material group.
- They have been in `engine_stage.json` since T6.
- No export change was needed.

The over-strong pickup was the same white R lobe as item 1, applied to the twins. With the reworked lobes, the hair beside the face goes from 2.4× to 1.27× the Cycles brightness (relative to the forehead), and the violet cast is gone: blue relative to skin is 6.4 before, 4.4 after, 4.1 in Cycles. The crown now reads slightly less blue than Cycles (3.1 vs 5.0).

## 3. Warm scattered component (and why the old balance was wrong)

New tooling:
- `hair_test.py --parity-lights key,fill,rim` renders one Cycles frame per studio light.
- The viewer's `?lights=` builds only the named lights.

With these, the hero hair's closeup luminance splits as key 0.025, fill 0.033, **rim 0.222**. About 80 % is the back light, as warm TT/TRT through the fibres. T9 matched the mean by accident: the key and fill were 2-3× too bright (white R), and the rim 0.5×.

New lobes (`HairLightingModel`):
- **TT:** an R-like cone on the jittered tangent (`ttExponent` 16) times a forward-scattering azimuth term `((1 - Lp·Vp)/2)^ttPow` (`ttPow` 2), gain `tt` 0.13.
- **Multiple-scatter body:** a fully wrapped diffuse, `scatter` 0.004.
- **Tint:** both use a unit-luminance tint, the albedo's chroma ^ `scatterSat` (0.4).
- **TRT (`spec2`)** takes the same tint. It was `sqrt(albedo)`, which is near grey and about 0.05 luminance.
- **Fit:** gains fitted per light from basis renders (one term at a time, per light), then trimmed on the hero portrait. Final values: R 0.035, TRT 0.007, TT 0.13, scatter 0.004.
- **Facial hair:** `facialHair.spec2` 0.012 → 0.002, the same strength in the new tint.

## 4. Brows

- **Brow region in the parity metric.** It is now measured (blue, from `brows_hero`, closed 2 px and eroded 1 px; 918 px).
- **Before:** mean 0.82, but the median was half the Cycles median: near-black strokes over skin.
- **Viewer:** brows have their own param block (`brows.*`, split from `facialHair`), with `scatter` 0.01.
- **Bake (`config.py` brows `game_cards`):**
  - Finer strands: `strand_px` 0.42, `tip_px` 0.25, `tip_fade` 0.45, `tip_alpha` 0.05.
  - A soft brow under-layer in the game skin: `hair_beard.paint_underlayer(b, "brows")`, r 2 mm, strength 0.4, blur 10 px, 177k texels.
- **After:** brow region 1.03×, p50 0.135 vs 0.161.

## 5. Beard (cheap pass)

- Jaw fins 80° → 55° and `tip_fade` 0.4.
- Beard region 1.147 → 1.090.
- The jaw edge is a little less spiky.
- The cheek fade is unchanged (the under-layer already handles it).

## What still reads wrong (candid)

- **Value structure on the crown.** In AgX the engine hair reads as a warm mid-brown over the whole top of the head. Cycles is dark at the front/top and glows on the lengths behind and at the crown.
  - The means, percentiles and r/g now match, but the spatial distribution does not.
  - Cycles gets that front-to-back fall-off from volumetric self-shadowing of the rim through the hair mass. The cards have none: the rim reaches every top card unoccluded.
  - Candidate fix: a "depth toward the light" term (cards cast into a hair-only shadow map, or a baked per-card light-occlusion from the groom's density along a few directions).
- **Fill parity.** The fill is still 1.4× on the hair and 1.3× on the beard. It is an unshadowed spot in the engine (only key / rim / kicker cast shadows), while in Cycles a 2 m area light that the hair mass shadows.
- **Brows in the hero rig.** They read lighter and a little ginger next to the Cycles brows. They are still strokes rather than the soft band (the under-layer at 0.4 barely shows). The silhouette is still somewhat spiky.
- **Hero portrait framing.** The Cycles hero preview portrait frames the head lower and larger than the engine portrait from the same `engine_stage.json` camera. This was visible in T9's gate too. Not investigated (not hair).
- **The "hero rig" closeup does not exist.** `engine_shots.mjs` captures the closeup under the neutral rig even with `?rig=hero`, so the only hero-rig engine frame is the portrait.
- **Motion.** The sharper ID mip (`idLodBias` -2) adds per-pixel highlight variation at distance. In motion without TAA this will shimmer; it has not been checked on a device. `idLodBias` is a live param if it does.
- **Not done:** item 3 of T9 (volume / silhouette), the hairline arc, the moustache overhang.

## Runs

| Run | Use |
|---|---|
| `data/build/t9b/dev0` | copy of T9 c6 for shader iteration (`s_*`: sweep frames; `pre_*`, `prelin_*`, `prelinp_*`: main's viewer) |
| `lookdev/20261014T155504Z-t9b-b1` | **final** build (front-lock strips, brow under-layer, brow / beard bake changes); `s_*` sweep frames |
| `hero/20261014T161745Z-t9b-b1` | Cycles hero portrait of b1 |
| `t9b/gate/*.png` | comparison sheets |

## Commits

| Commit | What |
|---|---|
| `6330c84` | shading rework (ID mip bias, card / wave jitter, spec AO, TT, scatter, tinted TRT, `brows` block); `hair_test.py` brow region and `--parity-lights`; viewer `?lights=` |
| `af2de08` | front-lock crossing strips, brow under-layer and finer brow strands, softer jaw fins |
| `35687fa` | final lobe gains (trimmed on the hero portrait) |
| (this commit) | report |
