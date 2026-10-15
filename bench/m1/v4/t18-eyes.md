_SwiftShader only: every engine frame here is WebGPU in headless Chromium on the CPU (port 8794, CPUs 0-3, a shared machine). Track T18 (eyes), m1 v4, 2026-10-15. Brief: `checkpoint-3.md` §2.4 and the T18 row of §4. Public build only (`bench/m1/variants/direction.json`). ArcFace was not run (its tooling is under `private/`); the run dirs are listed at the end._

# m1 v4 track T18: eyes

## The pictures (`data/build/t18/gate/`)

Panels in every strip, left to right: **engine before (main at T22, `t22-a5`) | engine after (`t18-b2`) | Cycles after (`t18-b2` hero)**.

- `portrait_eyes_triptych_100.png` / `_300.png` (x3 nearest): the parity frame. The engine `portrait` view uses the same camera and shot lights as the Cycles hero portrait. Both are cut to the window of Cycles' `portrait_crop` (960 × 540 at (556, 98) of the 1920 × 1080 frame), then to the eyes (280 × 100 at (340, 220)).
- `portrait_head_triptych_100.png`: the same window, the head.
- `eyes_triptych_100.png` / `_300.png` and `head_triptych_100.png`: the engine `closeup:hero` (1024², as the brief asks) next to the Cycles `portrait_crop`. The closeup has its own camera and the hero lights re-aimed at it, so it is a look comparison, not a parity frame; no metric below uses it.
- `cycles_eyes_before_after_300.png`: Cycles before | after.

**What I see in my own frames at 100 %** (three sentences):
1. In the parity portrait the engine eye now reads like the Cycles one: the upper lid hoods the iris top, the iris is a dark desaturated brown with a limbal ring instead of T22's orange disc, and the key's catchlight is one soft blob in the upper left where Cycles has it.
2. It is still not Cycles: the engine iris keeps a lighter collarette ring, its temporal sclera is darker and lavender where Cycles' lid shadows it, and the lower lash cards read as black specks along the lid margin.
3. TRAA cleans the stills (the wrap light's hard grey LTC square in the pupil is now a faint patch like Cycles' teal-grey one), but in motion it smears the 1–2 px catchlight to about half its MSAA peak.

## Before → after

Parity metrics use the engine `portrait` frame, cut to the Cycles crop window, against Cycles' `portrait_crop` (scripts in the notes below). Engine "after" is the non-beauty frame (TRAA, LUT grade). The beauty frame (set bounce on) gives the same numbers within 2 %.

| Measure | Target | Engine before | Engine after | Cycles before | Cycles after |
|---|---|---|---|---|---|
| Sclera / iris luminance | within 15 % of Cycles | 45.3 ¹ | **11.24** (Cycles ×0.68) ✗ | 15.0 | 16.6 |
| Catchlight area, share of the iris disc | within 30 % of Cycles | 0.0047 | **0.0063** (Cycles ×0.50) ✗ | 0.0126 | 0.0125 |
| Iris saturation (HSV, median) | Cycles −30 % | 0.930 | 0.765 | 0.851 | **0.725 (−15 %)** |
| read40 eye band darker | ≥ 0.80 | 0.8163 | **0.8278** (+0.028 margin) ✓ | | |
| Eye aperture (mm) | 8.5–9.5 | 9.00 | **8.75** ✓ | | |
| Upper lid over the iris (mm, left / right) | about +1 mm | 2.01 / 2.17 | **2.74 / 2.90** (+0.73) | | |
| Head measures (spec checks) | all in range | 0 out | **0 out** ✓ | | |
| glTF validator errors | 0 | 0 | **0** ✓ | | |
| LOD0 tris | ≤ 170k | 141,697 | **143,053** ✓ | | |

¹ The engine "before" frames are main at T22, rendered before T16 (MSAA, analytic grade), so they differ in AA and grade as well as in the eye. T22's engine pupil was about 10 px in radius against a 15.5 px iris, so the outer-iris annulus partly sampled the pupil. That before number overstates the contrast.

**Missed targets.**
- **Sclera/iris: 11.24 against 16.6 (−32 %).** The engine iris is too bright (0.0093 against Cycles' 0.0077) and its sclera too dark (0.104 against 0.128).
  - Without my caustic and the env veil it is 13.1 (−21 %). Cycles has neither: the hero sets `caustics_refractive` False, and its set barely reflects in the cornea.
  - Taking the subsurface scattering off the hero iris moved Cycles only to 15.5 (`data/build/hero/20261014T230104Z-t18-nosss`, an experiment, not kept).
  - The remaining gap shows in the picture as the lighter collarette ring the engine keeps and Cycles loses, plus the temporal sclera difference above. I did not fudge an iris albedo gain to close it.
- **Catchlight: 6 px against 9–10 px.** The engine blob is the key's real reflection size: a 0.3 m emitter at 1.5 m in a 7.8 mm cornea is 0.78 mm, which is 2 px here. Cycles' extra area is its 1.5 px pixel filter plus OIDN. Raising cornea roughness from 0.08 to 0.30 grew the engine blob only from 6 to 8 px, and I stopped at 0.18 for the look.
- **Iris saturation: −15 %, against the brief's about −30 %.**

**TRAA (main merged at b908d6e).** Measured on a 1 s `closeup:hero` turntable at 640 px (24 frames, 20°/s), as the mean |L(t−1) − 2L(t) + L(t+1)| in the near-eye box:

| 640 px turntable, near-eye box (60 × 36 px) | MSAA (`?aa=msaa`) | TRAA (default) |
|---|---|---|
| Eye-box temporal noise (0–255) | 21.9 | **13.9** (−37 %) |
| Whole-frame temporal noise | 4.84 | **2.90** |
| Catchlight peak while it faces the camera (frames 8–18) | 158–192 (3–5 px) | **71–108** (−45 %, spread over 4–28 px) |
| Frame-to-frame change in the catchlight peak | 15.5 | **8.6** |

- The refracted iris itself does not shimmer under TRAA.
- The 1–2 px catchlight is the one casualty. The jittered history spreads it, so it loses about half its peak and alternates 84 ↔ 108 on frames 9–14.
- This is a TRAA property (T16's `temporal.ts`), not something the eye shader can fix without a fatter highlight. Candidates for T16:
  - a highlight-preserving neighbourhood clamp;
  - excluding the cornea from the history's colour clamp through an MRT flag, the way the hair writes `hair`.

Frames: `data/build/t18/dbg2/tt{traa,msaa}_turntable/`.

## What changed

**Blender (`blender/character/eyes_hq.py`)**
- Iris: darker and desaturated colours (#3f2e22 / #1b130e / #271d15 / collarette #795c43; fibre gain 0.75).
- Sclera: darkens toward both canthi, by 0.6 over 2–20° with a warm tint, plus a 5 % band under the lids.
- `eyes_normal` (512², tangent space on the polar UV):
  - iris fibres, crypts and the collarette as relief;
  - conjunctival vessels on the sclera;
  - on the game eye and the hero eyeball.
- Game parts, built from the lid map and exported in the GLB (Cycles hides them):
  - `eye_lidshell`: a 7-row strip per lid, from 0.6 mm under the margin to 2.4 mm (upper) or 1.1 mm (lower) over the globe. Black, with an alpha of contact occlusion plus the lash root shadow, capped at 0.45 so the GTAO prepass's alpha test drops it. glTF BLEND, 720 tris. The first build had 3 rows, and its one inner chord dipped under the cornea bulge: the upper shell was invisible.
  - `eye_meniscus`: a 4-sided tube along the lower lid, BLEND, 392 tris.
  - `eye_caruncle`: 200 tris.
- `config.py`: the lid wrap is now `upper_over_iris_mm` 2.8 and `lower` 0.3.
- `lashes.py`: a second, shorter upper row 0.25 mm behind the first (40 %, 0.8 length, 1.15 curl), with its own atlas slot and game strip (+56 tris).
- `cornea_bulge_mm` stays at 2.2. At 1.3, read40 fell to 0.775, because read40's eye-band box is anchored on the cornea apex. With the box moved back 0.9 mm it gave 0.827, so the eye itself was fine, but I kept the harness and the bulge rather than edit `lookdev_render.py`.

**Engine (`web/src/character/materials/index.ts`, eye section; `params.ts`, eye block)**

Per-eye frames:
- fitted in JS from the bind geometry: globe sphere, axis, cornea sphere and limbus angle;
- carried through the head bone;
- refitted when gaze moves the vertices.

The iris:
- **Refraction.** The view ray refracts at the cornea (IOR 1.376) onto the iris plane, with a polar UV lookup using explicit gradients. Rays past the iris root read the root, not the sclera.
- **Irradiance.** The light enters where the path from the iris hit leaves the cornea sphere: E = T·E0·cos i·nI / cos t. The 1 / cos t replaced a divide by the iris-axis cosine that overlit the iris under oblique lights, which moved the parity ratio from 8.9 to 11.2.
- **Limbal visibility.**
- **The iris normal** from `eyes_normal`, plus a 0.05 cone.
- **A caustic** (gain 0.25) on the iris side away from the light.

The sclera:
- wrapped Lambert on the vessel normal;
- specular masked off on the cornea.

The cornea:
- **Catchlight.** GGX via LTC against each spot's Blender emitter rectangle. `stage.ts` puts the size and orientation in `userData.rect`. Shadow and cone come from three's light colour. Roughness is 0.18.
- **`envVeil`.** A constant Fresnel reflection (0.03 / 0.035 / 0.045 × corneaStrength) stands in for the set's reflection on the cornea. The cornea's own env specular is masked, so T16's set bounce does not reach it yet.

The game parts:
- `EyeShellMaterial`: black, transparent, no depth write, no shadow cast.
- `EyeWetMaterial`: the meniscus's LTC wet specular.

**Outside my listed files (one line each unless noted):**
- `stage.ts`: `userData.rect` on spots. T19 owns it now.
- `export.py`: `fix_alpha` keeps materials flagged `alpha_blend`.
- `lashes.py`: the second row, above.
- `params.ts`: the eye block.

The brief put the game meniscus and caruncle in `wet.py`. They live in `eyes_hq.py` instead, next to the lid map that places them; `wet.py` is untouched.

## Checks

- `cd web && npm run build`: exit 0, no errors.
- `bash bench/m1/test_containment.sh`: 73 passed, 0 failed.
- `python3 -I provenance/audit.py --data-root <main>/data --check-files --release`: 178 records, 0 errors, 0 warnings.

## Run dirs (for ArcFace)

- Final build: `data/build/lookdev/20261014T215617Z-t18-b2` (game frames `game_closeup_hero.png`, `game_portrait.png`, `game_portrait_beauty.png`, made with `ENGINE_BOUNCE` = T16's `refs/bounce/set_bounce.json`).
- Cycles after: `data/build/hero/20261014T220643Z-t18-b2`. Cycles before: `data/build/hero/20261014T211841Z-t18-before`.
- Engine before: `data/build/lookdev/20261014T203831Z-t22-a5`.
- Superseded: `20261014T212645Z-t18-b1` (bulge 1.3, read40 0.775) and its hero `20261014T213720Z-t18-b1`.

## Left

- Close the sclera/iris gap without a fudge. Candidates:
  - give the cornea the set bounce's PMREM reflection instead of `envVeil`;
  - shadow the rim and kicker on the temporal sclera, the lid contact in the shadow maps;
  - find why the engine keeps the collarette that Cycles loses.
- Re-check the eye after T19's eye-light change: the eye diffuse is `eyeLightDiffuse` 0.3 in the eye material only, and T19 will light everything with it.
- The lower lash cards read as specks at 100 %.
- TRAA halves the catchlight peak in motion (T16's history clamp; see the TRAA table).
- Iris saturation is at −15 %, not −30 %.

## Notes

- Metric scripts (scratch, not committed): iris = median luminance over 0.6–0.92 × the iris radius (15.5 px), excluding the sector under the upper lid, with the brightest 8 % dropped. Sclera = median of two 8 × 6–9 px boxes placed relative to each frame's iris centre. Catchlight = pixels in the disc at ≥ 0.5 × the disc peak and ≥ 2 × the iris.
- One experimental Cycles run went under `private/likeness/hero/20261014T225753Z-t18-nosss`, because `hero.sh` fails closed to private output when a blend has no `character.stats.json` beside it. I did not open it. It holds only the public build. Re-run with the stats linked: `data/build/hero/20261014T230104Z-t18-nosss`.

_Orchestrator, after the merge: ArcFace on `…-t18-b2` is 0.022 (EEVEE closeup) and 0.014 (engine hero closeup), ≤ 0.25 ✓. The stray private copy of the `t18-nosss` Cycles run was deleted._
