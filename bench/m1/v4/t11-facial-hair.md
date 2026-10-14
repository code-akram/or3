# m1 v4 track T11: facial-hair read, age and edge

_Track T11 report, 2026-10-14. All engine frames here are SwiftShader (headless Chromium, WebGPU on the CPU); nothing was captured on the Air. Spec: `checkpoint-2.md` §1 (beard / brows row), §4 row T11, §5 items 1-2. Public build only (`bench/m1/variants/direction.json`), no fan overlay._

**What I see in my own final frames at 100 %** (`…-t11-f2/game_closeup.png`, `game_portrait.png`):
- **Beard.** In the neutral closeup the beard is now a dark charcoal mass. The salt is concentrated on the chin and lower jaw, and the moustache and upper cheeks are dark, so it reads as a greying man in his forties rather than the T9b steel wool. The cheek line now fades into the skin through a stubble shadow.
- **Brows.** They are a soft dark-brown band with hair texture, not black pen strokes, and they are no longer ginger under the hero key. They are still lighter and less solid than the heavy Cycles band, and their outer tails end in visible strokes.
- **What still reads wrong.** Under the hero rig the beard reads warm olive-brown where Cycles is cool charcoal with a blue kicker rim that the engine beard does not take. The moustache's lower edge is still a fringe of dark spikes over the upper lip, and the beard's back edge at the jaw is still a cut.

**Final build:** `data/build/lookdev/20261014T182932Z-t11-f2` (code at `d3514cb`; engine frames from that viewer).
**Cycles reference:** the hero is unchanged. Only the game bake, the game-skin under-layer and the viewer brow block moved. The `f2` parity render reproduces the T9b b1 Cycles numbers exactly (beard 0.1916, brows 0.1954). The reference frames are:
- Cycles hero portrait: `data/build/hero/20261014T161745Z-t9b-b1`.
- Cycles closeup strands: `…-t11-f2/hair_test/parity_cycles.png`.

**Before:** T9b final `…/lookdev/20261014T155504Z-t9b-b1`.

**T10's hero-rig closeup is not on main** (main is still `2e393fc`). The gate pictures are therefore the neutral closeup plus the 1920 × 1080 hero portrait's head crop at 100 %.

## Gate pictures (before | after | Cycles), all in `data/build/t11/gate/`

| File | What |
|---|---|
| `closeup_head_before_after_cycles.png` | neutral closeup, engine 1024 px crop at 100 % (Cycles strands are 512 px, shown ×2) |
| `portrait_head_before_after_cycles.png` | hero rig, engine 1920 × 1080 portrait head crop at 100 % (the Cycles hero preview is 960 px, shown ×2). The framing agrees to a few px |
| `detail_brows_closeup.png`, `detail_brows_hero.png` | brows, neutral rig and hero rig, ×2 |
| `detail_cheek_line.png` | cheek line, ×1.5 |
| `detail_moustache.png` | moustache over the lip, ×2 |

## Gate metrics

Method: `hair_test.py --parts parity` on `f2`:
- Cycles 64 spp on the kept .blend, under `flock /tmp/or3-cycles.lock`, `-t 6`.
- The engine frame is `lin_closeup.png` (Standard view, decoded to linear).
- Regions are masks from the hero grooms `beard_hero*` and `brows_hero`.

The tone record (new, see §5) is measured on each region's core:
- the beard eroded 3 px further, because its edge band is skin showing through the cheek-line fade;
- the brows eroded 1 px further.

| Metric | Before (T9b b1) | After (T11 f2) | Cycles | Target |
|---|---|---|---|---|
| **Beard grey fraction** (core px with linear lum > 0.3 and sat < 0.45) | 0.208 (**1.46×**) | 0.149 (**1.05×**) | 0.143 | ±20 % ✓ |
| **Beard chroma** (median saturation of the core) | 0.257 (**1.31×**) | 0.189 (**0.96×**) | 0.197 | ±20 % ✓ |
| Beard grey by thirds of height, low (chin / jaw) / mid / high (moustache / cheeks) | 0.30 / 0.22 / 0.07 | 0.25 / 0.15 / 0.01 | 0.25 / 0.13 / 0.04 | (spatial) |
| Beard bright fraction (lum > 0.4) | 0.151 | 0.078 | 0.060 | (info) |
| Beard core p10 / p50 / p90 | 0.038 / 0.130 / **0.49** | 0.059 / 0.130 / 0.36 | 0.049 / 0.127 / 0.35 | (info) |
| Beard region mean, engine / Cycles | 1.090 | **0.968** | | ±20 % ✓ |
| Brows region mean, engine / Cycles | 1.031 | **0.874** | | ±25 % ✓ |
| Brows core p10 / p50 / p90 | 0.068 / 0.121 / **0.37** | 0.084 / 0.119 / 0.24 | 0.086 / 0.139 / 0.29 | (info) |
| **Brows chroma** (median saturation; the grey fraction is under 5 % in Cycles, so it is not gated) | 0.600 (1.10×) | 0.518 (**0.95×**) | 0.546 | ±20 % ✓ |
| Hero rig, brow box r/g relative to the forehead's: char. right / left brow | 1.01 / 0.91 | 0.99 / 0.84 | 0.89 / 0.87 | (ginger check) |
| Hero rig, chin / mid-beard box luminance relative to the forehead | 0.114 / 0.134 | 0.087 / 0.119 | 0.114 / 0.146 | (info) |
| Hair + beard + brows tris | 35,978 (23,034 + 11,952 + 992) | **35,862** (23,034 + 11,952 + 876) | | ≤ 40,000 ✓ |
| glTF validator | 0 errors, 16 warnings | **0 errors**, 16 warnings (the same skinned-node warnings) | | ✓ |
| read40 (lookdev) eye band darker / beard contrast | 0.7547 / 0.82 | 0.7679 / 0.85 | | (side effect: the darker brows add margin to the eye band) |

Notes on the table:
- **Hero-rig boxes.** The script is `/tmp/t11/pbox.py` (scratch). It uses fixed boxes in the head crop:
  - engine `linp_portrait.png` (Standard view, `post=0`) against the first layer of the Cycles `exr/portrait.exr`;
  - both normalised by a forehead box, which cancels the exposure and white-balance difference.
- **The brow-box chroma is skin-dominated.** It is the weakest number here. The read "not ginger" is from `detail_brows_hero.png`.
- **The hair region is untouched.** Hair is 0.936, as in T9b.

## 1. Beard age: the bake's grey is the hero's visible grey

**Root cause.** The hero groom's grey share is right for the hero: 20.8 % of beard strands, 44 % at the chin (NOTES §7). In Cycles a grey strand sits inside a dense dark mass that covers and shadows it. Each card cell draws its member strands back to front at about 2-3× real width. The T9 bake gave every grey strand:
- a full-width stroke;
- full Chiang brightness (melanin 0.06 is near white);
- beige chroma;
- 1.25× width (`grey_radius`).

The dark strands are linear ~(1e-3, 1e-4, 0), which is black. The engine beard's luminance therefore came almost entirely from bright beige flecks: the grey fraction was 1.46×, the bright fraction 2.5× and the chroma 1.31×.

**Fix** (`hair_beard.game_cards`, `config.py` beard `game_cards.grey`; the hero strands are unchanged):

| Change | Value |
|---|---|
| Zoned keep of the hero's grey strands; the rest take the dark base tone | `keep` 0.6 on the cheeks / sides, `keep_chin` 1.0 by the chin field, `keep_moustache` 0.3. Bake grey share: all 13.6 % (hero 20.8 %); chin 38 % (44 %); moustache 4.4 % (15 %); sides 13 % (20 %). Own RNG, so the card centres and every other stream are unchanged |
| The grey strands left | × `gain` 0.7, desaturated 50 %, × 0.85 width |
| `body` floor on every strand | `#2a2622` sRGB (linear ~0.02), × 0.6 on the moustache |

Why the body floor is needed:
- **First pass (a1): grey thinned with no floor.** The beard fell to 0.59× and read black.
- **The engine has no multiple-scatter lobe for facial hair** (`facialHair.scatter` 0). The floor stands in for the charcoal that Cycles gets from multiple scattering and the under-coat.
- **Body tone was swept:**
  - `#1f1c1a` gave beard 0.80×, grey fraction 0.55×.
  - A cooler `#282523` with desaturation 0.6 gave chroma 0.64×.
  - `#2a2622` matched mean, median, p10 / p90 and chroma.

## 2. Cheek-line fade

**Card fade by root density** (`game_cards.edge_fade`, `beard_bake.build_groom_cards` per-strand `alpha` / `px`):
- Each strand's alpha in its cell ramps with its root's beard density: 0 at density 0.08 (the line), 1 at 0.8, power 1.5.
- The strand narrows to 0.5× at the line.
- The hero thins over the 15 mm `fade.in_m`, but the T9 cards drew the thin edge strands at full alpha, so the cards stopped in an arc. Now the last ~1 cm of cards fade out.

**Under-layer** (`beard.underlayer`): this carries the transition.
- Gamma 0.7 → 0.6, so low cover reads darker.
- Stubble weight 0.5 → 0.8.
- Blur 3 → 8 px.
- The colour is now the dark strands' median (it includes the body floor), a charcoal instead of the near-black red.

**Result** (`detail_cheek_line.png`): the line is a soft gradient with a stubble shadow above it, close to Cycles. I did not find a reliable numeric edge-width measure on these frames: a column profile across the line mixes in the jaw's shading.

## 3. Moustache

Changes:
- **Roll:** 35° → 20°.
- **Lip clearance:** the lip-edge cards (280) stand `lip_gap_m` 1.2 mm off the skin past the root row. At 0.3 mm the overhang lay on the vermilion.
- **Tip fade:** those cards' strands fade over 65 % of their length (`lip_tip_fade`; the default is 40 %).
- **Grey and body:** the moustache keeps 0.3 of its grey and has a 0.6× body.

Result:
- The grey bar is gone; the moustache is the darkest zone, as in Cycles.
- **Still wrong:** the lower edge is a fringe of dark spikes over the upper lip (`detail_moustache.png`). Cycles has a soft overhang with a thin lip line under it.

## 4. Brows

| Change | Value |
|---|---|
| Fewer, fuller cards | 256 → 220 cards, spacing 1.6 → 1.7 mm, clump 1.6 → 2.1 mm (p50 35 members) |
| Finer strokes | `strand_px` 0.42 → 0.36, `tip_px` 0.18, `tip_fade` 0.5 |
| Dark-brown `body` floor | `#2a1e18` (Chiang at melanin 0.995 is black-red) |
| Under-layer | 0.4 → **0.88**, in an explicit neutral dark brown `#262220` (`underlayer.colour`; it was the strands' near-black red median) |
| Viewer `brows.scatter` | 0.01 → 0.004. The wrapped scatter in the albedo's red tint was the ginger under the hero key |

What was swept:
- Semi-transparent strands (`alpha` 0.6 / 0.45, kept as an option) dither into broken dots under alpha-to-coverage on SwiftShader, so they are off.
- `b5` (body `#2a1e18`, under-layer 0.88) was chosen over `f1` (`#2b211b`, 0.8). It is the darker band of the hero brow: brow region 0.87× vs 0.93×, chroma 0.95× vs 0.89×.

## 5. Tooling (checkpoint-2 §5.1)

`bench/m1/hair_test.py`, parity part:

**Tone record.** Every region now carries a `tone` record on its core:
- p10 / p50 / p90;
- grey fraction (`GREY_LUM` 0.3 linear, `GREY_SAT` 0.45);
- bright fraction;
- chroma (median saturation, r/g, b/g);
- the same split into thirds of the region's height (low / mid / high), which gives the spatial term;
- engine / Cycles ratios with `engine_within_20pct`. A Cycles grey fraction under 5 % (the brows) is not gated.

**`--parts measure`.** It recomputes the parity metrics from the files without rendering, either:
- for a re-shot engine frame; or
- with `--cycles-ref DIR`, against another run's Cycles frame and mask (valid while the hero grooms are unchanged).

This made each bake iteration cost only the build and the engine shots, not a Cycles render.

The hair region gets the record too, for information:
- engine / Cycles grey fraction 1.22×, chroma 1.37× (T12's colour work, not changed here);
- by thirds, the engine hair is bright at the top and dark low, Cycles the other way round. This is checkpoint-2's crown / back-length value inversion (T10).

## What still reads wrong (candid)

1. **Hero-rig beard tone.** The engine beard reads warmer (olive-brown) under the hero key than the cool Cycles beard: chin r/g relative to the forehead 0.67 vs 0.57. Its chin and mid boxes are 0.76× / 0.82× the Cycles luminance. Most of this is the light rig, not the bake:
   - the Cycles beard takes a strong blue kicker on the shadow side that the engine beard does not take (light-linking / kicker twins: T10's area);
   - the warm key on the floor colour adds the rest.

   A cooler body cost the neutral chroma gate (0.64×), so I left it.
2. **Moustache fringe** (§3). A real fix is probably fewer, broader lip-edge cards that follow the lip curve, or an alpha gradient across the overhang instead of along each card.
3. **Brows** are softer and the right colour, but lighter and less solid than the Cycles band (p50 0.119 vs 0.139). The tail still ends in strokes.

   There is also a dark wedge on the upper lid at the inner corner of the character's right eye. It is in every build, the T9b one included. I believe it is the lash strip or an inner brow card hanging down, but I have not checked.
4. **Beard back edge and silhouette.** The back edge at the jaw / sideburn is still a cut line, and the jaw-fin silhouette is unchanged.
5. **Mid third slightly grey** (0.15 vs 0.13), and the moustache / cheek third less grey than Cycles (0.01 vs 0.04). This follows the brief's "dark moustache and sides" more than the hero render does.
6. **SwiftShader only.** Alpha-to-coverage dithering, the strand look and the fade can all differ on the Air.

## Runs (`data/build/lookdev/`)

| Run | Change | Beard e/c, grey, chroma | Brows e/c |
|---|---|---|---|
| `…155504Z-t9b-b1` | before (T9b) | 1.09, 1.46, 1.31 | 1.03 |
| `…170740Z-t11-a1` | zoned grey keep (0.4 / 0.9 / 0.2), gain 0.7, no body; fade [0.05, 0.6]; roll 20°; brows 180 cards, 0.32 px, under-layer 0.7 | **0.59**, 0.37, 0.89 | 0.90 |
| `…172421Z-t11-a2` / `…172426Z-t11-b2` | body `#2a2622` / `#1f1c1a`; keep 0.55 / 1.0 / 0.3, gain 0.55; fade [0.08, 0.8]^1.5 | 0.93, 0.80, 1.01 / 0.80, 0.55, 0.79 | 0.80 |
| `…174358Z-t11-a3` / `…174406Z-t11-b3` | keep 0.6, gain 0.7, moustache body 0.6, under-layer gamma 0.6 / keep 0.65, gain 0.85; brow strands at alpha 0.6 / 0.45 | 0.96, 1.04, 0.96 / 1.04, 1.28, 0.95 | 1.24 / 1.36 |
| `…180057Z-t11-a4` / `…180106Z-t11-b4` | body `#282523`, desat 0.6; brow body `#2c241f`, opaque / + 220 cards, 0.36 px | 0.95, 1.01, **0.64** | 1.08 / 0.98 |
| `…181611Z-t11-f1` / `…181629Z-t11-b5` | a3's beard + lip tip fade; brows 220 cards, body `#2b211b`, under-layer 0.8 / body `#2a1e18`, 0.88 | 0.97, 1.05, 0.96 | 0.93 / 0.87 |
| **`…182932Z-t11-f2`** | **final** (= `b5`, from the committed config); full engine set, `lin_` / `linp_` frames, Cycles parity | **0.97, 1.05, 0.96** | **0.87** |

Variant runs were built two at a time (Blender `-t 4`). Engine shots were taken one browser at a time on port 8799, because 8797 was taken by another session.

## Commits

| Commit | What |
|---|---|
| `d212e87` | bake grey (zoned keep, gain, desaturation, width), cheek-line alpha / width fade, moustache roll + lip gap, brow cards / under-layer; `hair_test.py` tone record and `--parts measure` |
| `f97c485` | body floor (moustache × 0.6), keep 0.6 / gain 0.7, under-layer gamma 0.6 / stubble 0.8; brow alpha option |
| `c451498` | brow body floor, denser finer brow cards, lip-edge tip fade, brows scatter 0.004, brow tone gate on chroma only |
| `d3514cb` | brows body `#2a1e18`, under-layer 0.88 |
| (this commit) | report |
