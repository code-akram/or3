SwiftShader

_Every engine frame here is WebGPU in headless Chromium on the CPU (port 8794, CPUs 4–7, a shared machine at load 30–38). Track T18b (eyes, second pass), m1 v4, 2026-10-15. Public build only (`bench/m1/variants/direction.json`). ArcFace was not run (its tooling is under `private/`); the run dirs are listed at the end._

# m1 v4 track T18b: eyes

**What I see in my own frames at 100 %** (`data/build/t18b/gate/eyes_triptych_100.png`, three sentences):
1. The engine eye now sits close to the Cycles one: a dark, plainly brown iris with a soft collarette instead of T18's lighter ring, a small sharp catchlight where Cycles has it, and a clean lower lid with no row of black specks.
2. The far eye's outer (temporal) sclera is still lighter than in Cycles, where the lid and socket keep it almost black, and the bags under both eyes stay much darker than Cycles' (about 40–50 % of its luminance).
3. In the eye-crop turntable the catchlight holds steady under TRAA instead of fading and pulsing; it keeps more of its peak than stock TRAA does (see §4), but it is a hard 2 × 2 px dot where Cycles' is a soft round blob.

## The pictures (`data/build/t18b/gate/`)

Panels left to right: **engine before (main at T17, `t17-a8`) | engine after (`t18b-a3`) | Cycles after (`t18b-a3` hero, alley)**. Engine frames are the `portrait` view (same camera and shot lights as the Cycles hero portrait); Cycles is its `portrait_crop` (960 × 540 at (556, 98)). All three are cut to the same window of the 1920 × 1080 frame.

- `eyes_triptych_100.png` / `eyes_triptych_300.png` (×3 nearest): the eye strip (280 × 100 at (896, 318)), beauty frame (bounce, bloom, grade) against the alley render.
- `eyes_parity_triptych_300.png`: the same with the engine parity frame and Cycles `--parity` (void set, no DoF, 1 px filter) after.
- `head_triptych_100.png`: the head (480 × 480 at (780, 120)).
- `eye_turntable_traa.mp4` + `eye_turntable_traa_strip.png`: the 2 s `closeup:hero` turntable at 1920 px under TRAA (48 Hz, 24 fps out), cut to the eye band (896 × 200 at (576, 780)); the strip is every 8th frame. `eye_turntable_stock.mp4` and `eye_turntable_msaa.mp4` are the 1 s A/B (stock TRAA, MSAA).

## Gate metrics

Eye metrics: `bench/m1/eye_metrics.py` (new; T18's and T19's metric scripts were scratch). Iris centre found per frame (limbus edge, R = 13 px in both renderers); near = key side (image left), far = image right. "after" = `t18b-a3` in both renderers.

| Measure | Target | Before (`t17-a8`) | After (`t18b-a3`) |
|---|---|---|---|
| Max sampled textures per material per stage, every texcheck variant | ≤ 16 | eye 18 (T24's hero-rig failure) | **TEXMAX** (see §1) |
| Sclera / iris, engine ÷ Cycles, beauty vs alley, T18's two-box median (near / far) | within 15 % | 1.18 / 0.86 | **1.15 / 0.65** ✗ far |
| — same, parity vs `--parity` | within 15 % | — | **1.03 / 0.63** ✗ far |
| Sclera / iris, engine ÷ Cycles, mean of the two box medians (`ratio2`), beauty vs alley | within 15 % | 1.02 / 1.00 | **0.99 / 0.97** ✓ |
| — same, parity vs `--parity` | within 15 % | — | **0.99 / 1.00** ✓ |
| Catchlight area, pixel count ≥ ½ peak, beauty vs alley (near / far) | within 30 % | 6 vs 5 / 4 vs 5 px | **4 vs 5 / 6 vs 5 px (0.80 / 1.20)** ✓ |
| — parity vs `--parity` | within 30 % | — | 4 vs 3 / 7 vs 6 px (1.33 ✗ / 1.17) |
| Catchlight equal-filter area (flux ÷ peak, px), parity / beauty | within 30 % | — | **1.18 / 0.86** and **0.77 / 0.85** ✓ |
| Iris saturation, engine (T12 `t22-a5`: 0.857 / 0.830) | −30 % | 0.583 / 0.571 | **0.529 / 0.514 (−38 % / −38 %)** ✓ (past) |
| Iris saturation, Cycles (T12: 0.721 / 0.722) | −30 % | 0.600 / 0.606 | **0.500 / 0.485 (−31 % / −33 %)** ✓ |
| read40 eye band darker | ≥ 0.80 | | **0.8231** ✓ |
| Eye aperture (mm) | 8.5–9.5 | 8.75 | **8.75** ✓ |
| Head measures (spec checks) | all in range | 0 out | **0 out** ✓ |
| glTF validator errors | 0 | 0 | **0** ✓ |
| LOD0 tris | ≤ 170k | 156,817 | **156,817** ✓ |
| Turntable temporal noise (T19 recipe: TRAA 48 Hz, warm-up 24, `lut=0`, 640 px, 2 s) | ≤ 3.39 | 3.05 (T17's, same recipe but LUT on) | **TTNOISE** |
| Under-eye "bag" box, linear L, engine ÷ Cycles (beauty vs alley) | (T19: 92 vs 118 sRGB) | 0.39 / 0.55 | **0.39 / 0.48** ✗ (§6) |

## 1. Texture budget

**Root cause of T24's 18.** The eye bound, per fragment stage: albedo, ORM, normal, DFG LUT, PMREM, GTAO, contact depth, the 5 shadow maps of the hero rig, three's two LTC tables (bound by every rect light node) and **a second pair of LTC tables of its own** (the HALF tables in `ltcSpec`, while three binds the FLOAT ones when float32 is filterable). That is 16 in the frame `textureAudit` caught; the 18 in the console was the 64 px first frame's pipeline (a different render object, with the AO prepass and contact maps already bound), which a per-frame audit never sees.

**Fixes (eye).**
- `ltcTextures()` returns the same tables three uses (FLOAT when filterable, else HALF), and the cornea catchlight in `directRectArea` takes three's own `ltc_1` / `ltc_2` nodes: −2.
- No ORM: the eye's roughness is the bake's own split on the cornea mask (`eye.roughSclera` / `eye.corneaEnvRoughness`), and its lid occlusion was already in the albedo (`eyes_hq.py` bakes `albedo × occl`; T18 also applied the ORM's copy as `aoMap`, a double count): −1.
- The new lid-contact test reads each light's **own** shadow depth texture (`lighting.ts shadowDepthTexture`: the same texture object, so the same binding): +0.

**The test.** `engine_shots.mjs --texcheck` (T18b, `texbudget.ts`):
- a fresh page per view × variant, with `?texaudit=1`: the audit records **every pipeline from the first frame on** (the session), not just the audited frame;
- variants: default, `ltc=0`, `sharemaps=0`, `pcss=0`, `contact=0`, `tier=gameplay`, `hairshadow=0`; views `portrait` (+ its beauty frame) and `closeup:hero`;
- WebGPU's own verdict is folded in: any "sampled textures (N) … exceeds" console error fails it too;
- writes `<run>/t18b_texcheck.json`, exits 1 when anything is over 16.

TEXCHECK

## 2. Sclera / iris

**What changed in the eye shader (`materials/index.ts`, eye class + `eye` params).**
- **The hero cornea.** Cycles refracts through the hero cornea (`eyes_hq.HERO`: 1.3 mm bulge, 20 µm film); the game mesh's cornea bulges 2.2 mm (kept: read40 anchors on it). `heroCornea()` fits a sphere to the hero bulge profile; the view ray is intersected with it per pixel and refracted / reflected there (apex radius 7.1 mm against the mesh's 6.0 mm). The iris plane is the hero's: 0.5 mm recess, 0.15 mm cone (T18 had 0 / none). The catchlight was 0.84× Cycles' linear size on the mesh cornea; it is now the same size (§3).
- **The cornea reflects the set bounce.** T18's `envVeil` (a constant emissive) is gone. The cornea's indirect specular is three's own, on the cornea normal, at `eye.corneaEnvRoughness` 0.05 and the cornea's f0 share; the sclera keeps its own lobe.
- **Lid contact shadows.** The eye no longer casts shadows (in Cycles it shades only the lids' hidden inner faces). Per shadowed light, `lidShadow()` reads that light's depth map (8 Vogel taps, rotated per pixel and frame) and counts occluders between 0.2 mm and 6 mm in front of the eye surface. Those are the lids and lashes, which the shadow node misses under its 1.5 mm depth + 3 mm normal bias. A/B on the T17 character (parity frame): sclera −8 % near, −24 % far; the far temporal box −15 %.
- **No sclera wrap** (`eye.scleraWrap` 0.15 → 0). The hero eyeball's subsurface (0.3 × 1.5 mm) does not carry light past the terminator of a 12 mm globe; with the wrap the far eye's temporal sclera sat at 2.4× Cycles' (sweep `sw1` / `sw2`).

**The collarette ring: root cause.** The ring is in the iris albedo itself (theta 16–17°, 3–4× the luminance of the rest of the iris). Cycles lost it because the hero eyeball's random-walk subsurface (weight 0.3, radius 1.5 mm × (1, .45, .3)) also covered the iris. It blurred the ring at the 0.5 mm scale and bled the sclera's red into the iris. A real iris is an opaque pigmented stroma, so `eyes_hq.HERO` now takes the subsurface off under the cornea (`iris_sss` 0, mapped on the same UV edge as the roughness). With that and the desaturated albedo the two renderers draw the same soft ring (the 300 % triptych). Cycles' iris got slightly brighter without the SSS loss: 0.0079 → 0.0084 near.

**Numbers (after, `t18b-a3`).**

| | iris L near / far | sclera nasal near / far | sclera temporal near / far | T18 ratio | `ratio2` |
|---|---|---|---|---|---|
| Engine beauty | 0.0099 / 0.0107 | 0.0508 / 0.1054 | 0.1724 / 0.0287 | 9.21 / 4.25 | 11.28 / 6.27 |
| Cycles alley | 0.0091 / 0.0088 | 0.0502 / 0.1040 | 0.1570 / 0.0099 | 8.01 / 6.57 | 11.41 / 6.47 |
| Engine parity | 0.0093 / 0.0099 | 0.0461 / 0.1019 | 0.1648 / 0.0240 | 8.73 / 3.82 | 11.36 / 6.38 |
| Cycles `--parity` | 0.0087 / 0.0076 | 0.0466 / 0.0898 | 0.1543 / 0.0064 | 8.46 / 6.09 | 11.52 / 6.37 |

**The far eye: missed on T18's measure.** T18's ratio takes the median of the two sclera boxes pooled. One box is lit and one shaded (2–15× apart), so that median falls in the gap between the two populations and moves with a few pixels: the same frame gave 3.98 or 4.44 for small sweep changes (`sw1`, `sw2`). `eye_metrics` therefore also reports `ratio2`, the mean of the two box medians, which is within 3 % in both comparisons. I report both and do not claim the first.

What is genuinely off:
- The far eye's **temporal sclera is 2.9× Cycles'** (0.0287 vs 0.0099; parity 3.8×). Cycles keeps it almost black.
- The far **iris is 1.22× (beauty) / 1.30× (parity)** Cycles'.

These are causes I ruled out on the far temporal box:
- the wrap (removed: −20 %);
- the lid-contact shadow (on: −15 %; a 12 mm band and 3-texel filter: no further change);
- the lid shell (0 %).

The one unshadowed light in the hero rig is the camera-side `eye` light (`shadow: false` in the stage). Every other light has a PCSS map, and the lid test runs only on shadowed lights. Whether Cycles' socket blocks that light I have not split per light: the next step is a per-light Cycles AOV of the far eye.

## 3. Catchlight

**Size: no fudge left.** `eye.corneaRoughness` 0.18 (T18's stand-in for Cycles' pixel filter and OIDN on the mesh's tighter cornea) is now **0.02, Cycles' own** (`HERO cornea_rough`). With the hero cornea, the parity catchlight is 4 / 7 px against Cycles' 3 / 6, and 4 / 6 against 5 / 5 on the beauty frames.

**Equal-filter measure.** At 3–7 px a pixel count moves ±1 px (±15–33 %) with sub-pixel position alone, and Cycles' 1 px Blackman-Harris filter + OIDN spread a highlight that TRAA resolves to its true size. `eye_metrics` therefore also measures the highlight's **flux** (Σ(L − iris) over the 7 × 7 px around the peak, scene-linear). A pixel filter or denoiser redistributes flux but keeps it, so flux ÷ peak is an area that compares across filters:
- parity: 4.5 vs 3.8 px (1.18) near, 5.1 vs 5.9 (0.86) far;
- beauty: 4.6 vs 6.0 (0.77), 5.1 vs 6.0 (0.85);
- flux itself, parity: 1.03 / 0.81.

All are within 30 %. The one plain count outside it (parity near, 4 vs 3 px) is that ±1 px. A Gaussian blur on both frames (`--blur`) is not a usable equal filter here: blurred, the peak search lands on other features.

## 4. TRAA and the catchlight (`temporal.ts`)

**Cause.**
- **Flicker reduction.** `HairTRAA` resolves with three's `flickerReduction`, which weights each sample by 1 / (1 + luma of the tonemapped colour). A 1–2 px catchlight that the Halton jitter puts in a pixel some frames and not others averages toward its dark frames, which is T18's −45 % peak.
- **Clipping.** The 3 × 3 variance clip cuts the history when the highlight is in only one neighbour, which is the ±10 % pulse.

**Fix (specular-aware history).**
- The eye writes (0, 1) into the temporal target's `hair` attachment (hair writes 1s); only in temporal modes, since MSAA has no such attachment.
- On those 3 × 3-dilated pixels the resolve blends **linearly** (`aa.specLinear` 1).
- The clip gamma is wider while still (`aa.specGamma` 1.5, to the stock moving gamma over `aa.hairMotionPx`).
- The current-frame floor is 0.1 (`aa.specMinWeight`) instead of 0.05, because the history follows the surface and a reflection does not, so trails stay short.
- `aa.specAware` 0 turns it off for the A/B.

`ao.ts` is untouched.

TRAATABLE

## 5. Iris saturation and lower lashes

- **Iris saturation.** The iris hexes are HSV S × 0.68 overall against T18's (`eyes_hq.DEFAULTS`: `#3f342b` / `#1b1512` / `#27201b`, collarette `#796554`), plus the Cycles iris without subsurface (§2). Cycles is at −31 % / −33 % against T12. The engine is past it at −38 % / −38 %, because since T12 the engine already dropped further than Cycles (T18 left it at −30 % with Cycles at −17 %). Both renderers now agree within 6 % (0.529 / 0.514 vs 0.500 / 0.485), which I took over hitting −30 % in the engine exactly.
- **Lower lashes.** The game strip's lower lashes have their own stroke and line settings (`config.py` `hair.lashes.lower`, read by `lashes.py`): stroke radius 0.9 px (was 1.6), floor 0.35 px, no lash line (was 1.5 px at half colour), root darkening 0.15 (was 0.4) and value × 1.5. At 100 % the lower lid now reads as a soft line with faint lashes, as in Cycles, instead of a row of black specks (`eyes_triptych_300.png`, far eye). The upper lashes, the hero strands and the tri count are unchanged.

## 6. Under-eye: not GTAO

T19 put the dark under-eye (92 vs 118 sRGB) down to GTAO + the key's shadow. That box was not scripted, so `eye_metrics` adds two: 16 × 6 px on the iris column, 20 px ("bag") and 36 px ("cheek") below the iris centre. Engine vs Cycles, beauty / alley: bag **0.0207 vs 0.0527 near, 0.0295 vs 0.0618 far** (sRGB 62, 31, 27 against 104, 48, 39), cheek 0.115 vs 0.142.

One live sweep on the T17 character (parity frame, `t18b/base`, bag luminance near / far):

| Change | bag near | bag far |
|---|---|---|
| default | 0.0184 | 0.0262 |
| `?gtao=0` | 0.0180 | 0.0250 |
| `?contact=0` | 0.0184 | 0.0262 |
| `?noshadow=key` | 0.0209 | 0.0267 |
| baked AO off (`skin.aoIntensity` 0, `ao.bakedMix` 0) | 0.0208 | 0.0284 |
| lash coverage step (`aa.hairCoverage` 0) | 0.0183 | 0.0263 |
| lid shell off | 0.0183 | 0.0307 |

- GTAO, contact shadows, the key's shadow, the baked AO, the lash cards and the lid shell together account for at most ~15 % of a 2.5× gap.
- The game and hero skin albedos are identical there (median ratio 1.00).
- What is left is the skin's own response in that concave, downward-facing band: Cycles' random-walk SSS fills it with red light in all three channels (2.2–3.1×). That is T17's skin and `sss.ts` / `ssss.ts` domain.

I made **no `ao.ts` change**: there is nothing in GTAO to fix. **This item is open: under-eye bag at 0.39 / 0.48 of Cycles, root cause outside GTAO.**

## Run dirs (`<main>/data/build/`)

- Look-dev:
  - `lookdev/20261015T083512Z-t18b-a3`: final; engine frames `t18b_*`, texcheck `t18b_texcheck.json`.
  - `lookdev/20261015T080357Z-t18b-a2` and `lookdev/20261015T073942Z-t18b-a1`: intermediate.
- Cycles: `hero/20261015T084949Z-t18b-a3` (alley) and `hero/20261015T085453Z-t18b-a3-parity`.
  - Before: `hero/20261015T051208Z-t17-a8`.
- Engine before: `lookdev/20261015T045405Z-t17-a8` (`game_portrait*.png`).
- `t18b/base/`: symlinks to `t17-a8` plus the sweep crops (`e0*`, `sw1_*` … `sw4_*`).
- Gate pictures: `t18b/gate/`.

## What is left

- The far eye's temporal sclera (2.9×) and iris (1.2–1.3×); next, per-light Cycles AOVs of the far eye, starting with the unshadowed camera-side `eye` light.
- The under-eye bag (0.39 / 0.48 of Cycles), in the skin path, not GTAO (§6), for T17.
- MSAAFINDING
- The catchlight is a hard 2 × 2 dot at 0.02 roughness; Cycles' is a soft round blob of the same flux. That is the pixel filter, so I did not widen the lobe to imitate it.
