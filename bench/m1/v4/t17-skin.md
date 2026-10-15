_SwiftShader only: every engine frame here is WebGPU in headless Chromium on the CPU (port 8794, CPUs 0-3, a shared machine). Track T17 (skin, both renderers), m1 v4, 2026-10-15. Brief: `checkpoint-3.md` §2.2, §5.2 and the T17 row of §4, plus the coordinator's revision after a6 (colour gate below). Public build only (`bench/m1/variants/direction.json`). ArcFace was not run (its tooling is under `private/`); the run dirs are listed at the end._

# m1 v4 track T17: skin

## The pictures (`data/build/t17/gate/`)

The final run is **a8**: main at `5900412` (T19 lighting, T20 hair v5) merged in, then built.

- `head_triptych.png` (100 %): **engine before | engine after (`t17-a8`) | Cycles after (`t17-a8` hero `portrait_crop`)**.
  - The engine frames are the `portrait` view, which uses the hero portrait camera and shot lights, cut to Cycles' crop window (960 × 540 at (556, 98) of 1920 × 1080).
  - "Engine before" is the `t18-b2` build (main before T17) rendered with today's engine and `?ssss=0&detail=0` (`data/build/t17/before_t19`). Its lighting is T19's, the same as the after frame, so the panels differ only by T17. Its hair is the old hair.
- `cycles_pair.png` (100 %): Cycles before (`t18-b2` hero) | after (`t17-a8` hero). Cycles' lights are unchanged between them.
- `detail_strip.png` (×3 nearest): forehead, cheek and nose boxes. Columns: engine before | engine after | Cycles before | Cycles after. These are the boxes every colour and highlight metric uses.
- `closeup_pair.png` (100 %): engine `closeup:hero` (1024²) before | after. This view has its own camera and is for looking only; no metric uses it.

**What I see in my own frames at 100 %** (three sentences):
1. The salmon blotches of a6 are gone in both renderers. Forehead and cheeks read as even skin, with the colour in broad soft zones: warmer cheeks, nose tip and ears, a slightly yellower forehead, and a cooler beard area. Next to the before frame the face is no longer orange.
2. The zoning is subtle, so the face reads clean and a little flat, closer to the before frame than to a6, and Cycles' cheeks are a shade pinker than the engine's.
3. On the engine forehead the detail tiles break the highlight into a fine glitter of small clumps, a little wetter than Cycles' smoother sheen, and SSSS softens the nose and cheek terminators.

## Before → after

- **Engine:** "before" is `t17/before_t19` (t18-b2 under today's engine); the t18-b2 engine frame from yesterday's engine is in brackets. "After" is lookdev `20261015T045405Z-t17-a8`.
- **Cycles:** "before" is hero `20261014T220643Z-t18-b2`; "after" is hero `20261015T051208Z-t17-a8`.

**The colour gate** is the coordinator's revision; it replaces a* σ ≥ 1.5:
- Lab a* on the forehead, cheek and nose boxes of the parity crop, at about 1.6 px/mm.
- **Zone Δa*** is the mean a* of the cheek box minus that of the forehead box.
- **Small-scale σ** is the std of a* band-passed at 3–15 mm, a difference of Gaussians with σ = λ/2π. It is gated on the forehead and cheek boxes.
- **Face chroma** is the mean C*ab over all four boxes.
- The engine numbers use the non-beauty `portrait` frame (TRAA, LUT grade); the beauty frame gives the same within 0.2.

| Measure | Target | Engine before | Engine after | Cycles before | Cycles after |
|---|---|---|---|---|---|
| Zone Δa* (cheek − forehead) | +2 to +5 | 3.84 [3.50] | **3.49** ✓ | 3.78 | **3.60** ✓ |
| Small-scale a* σ, 3–15 mm, forehead / cheek | ≤ 0.8 | 0.63 / 0.68 [0.70 / 0.69] | **0.57 / 0.57** ✓ | 0.63 / 0.66 | **0.56 / 0.65** ✓ |
| Small-scale a* σ, nose box (information) | | 1.02 [1.31] | 0.84 | 1.49 | 1.38 |
| Face chroma C*ab | within 10 % of t18-b2 | 24.60 [27.46] | **25.25**: −8.0 % of t18-b2, +2.6 % of the same lighting ✓ | 25.32 | **26.05 (+2.9 %)** ✓ |
| Old a* σ (DoG σ 1.5 / 5.6 px; information) | was ≥ 1.5 | 0.69 [0.72] | 0.59 (a6: 1.54) | 0.74 | 0.66 (a6: 1.67) |
| Skin highlight p99/p50, engine vs Cycles | within 20 % | 1.41 [1.47] vs 1.24 | **1.285 vs 1.248 (+3.0 %)** ✓ | | |
| Face roughness std / mean | 20–25 % | 11.9 % | **21.7 %** ✓ ¹ | | |
| T16 turntable noise (closeup:hero, 2 s, 48 Hz, 640²) | ≤ 3.47 | 3.47 | **3.051** ✓ (frame max 3.49; a5 before the T19 and T20 merge: 2.949) | | |
| Shader balls within ±10 % | keep | | skin_head mean **0.896 ✗**, peak 0.854 ✓ ² | | |
| Head measures (spec checks) | all in range | 0 out | **0 of 17 out** ✓ | | |
| glTF validator errors | 0 | 0 | **0** ✓ | | |
| LOD0 tris | ≤ 170k | 143,053 | **156,817** ✓ ³ | | |
| read40 eye band | ≥ 0.80 | 0.83 | **0.83** ✓ | | |

¹ The ORM of a8 is byte-identical to a6's; the colour pass changed only the albedo. The figure is face roughness std 0.119 over mean 0.548.

² **The skin ball misses, and T17's engine code is not the cause.**
- With `?ssss=0&detail=0` the engine balls give exactly the same numbers (`data/build/t17/balls_off`); the balls scene doesn't use SSSS or the detail tiles.
- The ratio fell from a6's 0.957 to 0.896 when main's T19 lighting came in. T19 replaced the skin's rect-light point equivalent, which had been 24 % hot on the fill and 16 % on the wrap, with the exact form factor.
- T19's per-light skin_head numbers are key 0.944, fill 0.920, rim 0.40.
- The other balls: wool 0.968, silk 1.015 and leather 0.944 ✓; hair_cards 0.457 / 0.286 and eyes_hq 1.124 / 1.273 miss. Those are T20's and T18's materials.
- Raising the skin's gain now would tune against lights that T25 is about to change (rims ≤ key, a dim set fill), so I left it. It should be re-checked once T25 lands.

³ The tris went up with main's T20 hair v5 (46k hair tris). T17 changes no geometry.

**Per-pass cost (SwiftShader).**
- A/B on the a6 `closeup:hero` still: 1024², 24 TRAA frames, one run each, load average 23–33.
- The four times were default 397.1 s, `?ssss=0` 426.6 s, `?detail=0` 389.5 s and both off 472.5 s.
- The run with both features off was the slowest, so the spread is machine load: about 21 %, or about 3.5 s per frame. That is bigger than either pass, so this run can't resolve their cost.
- All it bounds: the whole frame is about 16.5 s on SwiftShader, and neither SSSS nor detail adds anything measurable above that noise.
- SSSS is two full-screen passes of 13 taps each, reading colour, the skin MRT and depth at every tap. Detail is 2 extra texture reads per skin fragment.
- The GPU per-pass ms needs timestamp queries on real hardware: the Air, with T19's `&timestamps=1` and `__viewer.profile()`.

Engine still times for a8 (24 TRAA frames each, load average about 30): portrait 666 s and beauty 751 s.

## What changed

**Shared albedo (`skin_synth.py`, `config.py` head block).**
- **The a7/a8 colour pass, from the coordinator's revision:**
  - the 5–12 mm haemoglobin and melanin patch layers are off (`hb_patch` 0, `mel_patch` 0; the code stays, default off);
  - the broad zones are stronger: `zones` 1.0 → 1.3 (forehead yellow; cheek, apple, nose tip and ear warmth), `beard_shadow` 1.0 → 1.3 (cool grey-blue over the upper lip and jaw);
  - new warm inner eye corners (`canthus`, σ 5 mm, ~14 mm medial of the globe centre);
  - the pre-T17 thresholded 5–15 mm Hb blotching is lowered from 0.18 to 0.10 (`hb_strong`);
  - the periorbital darkening was already there (T12's `orbit_dark` / `lid_dark` / `socket_dark` in the direction variant) and is unchanged.
- **Kept from a6:**
  - lips: wetness 1.0, roughness 0.22, coat 0.6;
  - the roughness structure (patch, mid, density, pore and second-patch terms) that gives the 21.7 % std;
  - the fixed pore-pit sign: `rough_pore` had no effect before.

**Bakes (`skin_tex.py`).**
- 512² pore tile (1.5 mm period) and micro tile (0.3 mm), in `skin_detail_{pore,micro}.png`.
- `skin_detail.json` sidecar with repeats per material, cells, slope variance and thickness distance.
- Cavity in ORM.b; `pack_orm` restores it after the glTF exporter drops it.
- Thickness from inside-AO: head p5 8.8 mm; 0.5 % thinner than 4 mm.
- No transmission within 5–9 mm of the eyeballs. The eyeball isn't in the AO bake, so without this the lids glowed red.
- Hands use the same path; the T22 hands bake inputs are unchanged.

**Engine (`materials/index.ts`, new `ssss.ts`, `main.ts`, `params.ts`).**
- Detail normals:
  - the pore and micro tiles, mixed by the pore map and the region mask;
  - faded out by pixels per period from `fwidth` (2.5 → 1.2 px);
  - Toksvig roughness widening for the slope variance the fade loses.
- **The two tiles are one 2-layer `DataArrayTexture`.**
  - After the T19 merge the skin's fragment stage sampled 17 textures; WebGPU allows 16, so the frames came out black.
  - One array texture sampled twice is one binding (three dedupes texture uniforms by uuid), which leaves the skin at 16.
- Lobe 1 specular is multiplied by the cavity (the ORM cavity plus a pore term). Dual lobe: lobe 2 roughness ×2.0, mix 0.35.
- Transmission at ears, nostrils and lids:
  - from the thickness map, using the unshadowed light colour and a two-Gaussian profile from the hero radii;
  - punctual lights only.
- Separable SSS (Jimenez 2015), in `ssss.ts`:
  - the skin material writes `skin` (specular) and `skinAlbedo` MRTs;
  - two 13-tap passes (H then V) using the hero radii [3.4, 0.748, 0.34] mm, with the depth falloff in mm and pre/post albedo 0.2;
  - registered as a 'scene' pass, so TRAA cleans it.
- The LUT in `sss.ts` is the low tier:
  - under MSAA;
  - on WebGL;
  - with `?ssss=0`;
  - when the adapter can't give 40 colour-attachment bytes per sample.

**Hero (`blender/hero/stage.py`, `skin_tex.py` hero material).**
- The pore tile goes into the micro-displacement.
- Film filter 1.0 px (`HERO_FILTER_PX` overrides it).
- Lighter denoise on the skin only:
  - Cycles keeps its own OIDN;
  - a compositor Denoise with prefilter None runs on Cycles' noisy image with albedo and normal guides;
  - its result is mixed in on material index 7 through an anti-aliased ID mask, and the multi-part EXR is rewritten through OIIO;
  - `HERO_SKIN_DENOISE=0` turns it off.

**Flags:** `?ssss=0` (LUT diffuse), `?detail=0` (no detail tiles, none loaded), `HERO_SKIN_DENOISE=0`, `HERO_FILTER_PX=<px>`.

## Notes and misses

- **a6 and its a* gate.**
  - a6 met a* σ ≥ 1.5 (engine 1.54, Cycles 1.67) with a 0.28 haemoglobin patch layer, and that layer read as a rash at 100 %.
  - The band behind that gate (DoG σ 1.5 / 5.6 px) peaks near a 9 mm wavelength, so meeting it takes visible patches of that size.
  - The coordinator replaced the gate. a6's renders stay in `lookdev/20261015T025800Z-t17-a6` and `hero/20261015T031020Z-t17-a6` for reference.
- **The skin ball** misses at 0.896; see note ² for the cause and why I didn't retune it.
- **The texture budget is at the limit.**
  - The skin's fragment stage now samples exactly 16 textures.
  - Anything that adds a shadow map or screen texture to the skin (T25's extra fill, if it casts shadows) would go black again.
  - The next saving would be to share the GTAO and contact-shadow textures, or to move the detail map's three channels into spare alpha.
- **Compositor crash.**
  - Blender 5.2.2 crashes (`free(): invalid size`) on a compositor Denoise set to prefilter 'Accurate' with guides. 'Fast' and 'None' work.
  - That is why the hero keeps Cycles' own denoise and adds a 'None' pass on the skin only (0.6–1.0 s per shot).
- **The 40-byte MRT.**
  - output + velocity + hair + skin + skinAlbedo at RGBA16F is 40 bytes per sample; WebGPU's default limit is 32.
  - `main.ts` asks the adapter for its limit and passes `requiredLimits`. SwiftShader reports 128.
  - Not tested on the Air (M-series reports 64 or more). Any adapter that reports less falls back to the LUT with a console warning.
- **Transmission is not shadowed.**
  - It uses the unshadowed light colour, gated by thickness, and the lids over the eyeball are masked out.
  - Shadow-map thickness (Jimenez's version) is the proper fix.
- ArcFace was not run (`private/`).

## Run dirs

- lookdev `data/build/lookdev/20261015T045405Z-t17-a8`:
  - `game_portrait.png`, `game_portrait_beauty.png`, `game_closeup_hero.png`;
  - `cycles_balls.png`, `game_balls.png`, `engine_parity.json`;
  - turntable `tt_turntable.mp4` / `tt_shots.json`.
- hero `data/build/hero/20261015T051208Z-t17-a8`.
- engine before under today's engine: `data/build/t17/before_t19`. These are symlinks to t18-b2 plus new `game_*` frames; nothing in t18-b2 was written.
- balls with T17's engine features off: `data/build/t17/balls_off`.
- before: lookdev `20261014T215617Z-t18-b2`, hero `20261014T220643Z-t18-b2`.
- a6, for reference: lookdev `20261015T025800Z-t17-a6`, hero `20261015T031020Z-t17-a6`, turntable `20261015T023618Z-t17-a5`.
- gate pictures `data/build/t17/gate/`.

The metric scripts are scratch scripts and are not in the repo:
- `/tmp/t17/colgate.py`: the colour gate;
- `skinmetrics.py`: highlight percentiles;
- `synth_iter2.py`: the offline albedo proxy;
- `gate2.py`: the pictures.

The definitions are above.
