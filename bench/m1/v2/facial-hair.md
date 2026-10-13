# m1 v2 track C: beard, moustache, stubble, brows and lashes

_Track C report, 2026-10-12. Brief: [`BRIEF.md`](BRIEF.md); art direction: [`direction.md`](direction.md) §2 C. Supersedes the shell-only beard in [`../facial-hair.md`](../facial-hair.md)._

The baseline beard was a pasted, single-tone black patch with a hard outline, the brows were paint strokes, and the lashes were MPFB's stock cards. Now one **strand groom** is the source of truth for each of the three (Blender hair curves, Geometry Nodes clump and frizz, all seeded). The hero renders use the strands directly. The game version is **baked from the same groom**: shells and silhouette cards for the beard and brows, and two strips per eye for the lashes.

Everything is placed off landmarks and by surface sampling: lip, ear, head and neck groups, profile lines, brow-proxy spines, and lid margins ray-cast on the final skin. So Track A's forms v1 → v2 change rebuilt the grooms with no edits.

## Round 4 (brow weight back)

Evidence run: `data/build/lookdev/20261012T235802Z-fhv2-full9`, built on main `81d0c14`. Renders are in `fh/`.

Round 3 left the brows too light and sparse for the archetype's heavy, dark brow. Round 4 brings the weight back by about 30 %:

- **Density:** `groom.per_cm2` 185 → 240. That gives 1,051 and 1,021 strands per side, up from about 810.
- **Tone:** melanin 0.975 → 0.982, and the lighter-hair share 20 % → 12 %.
- **Game:** brow shell `albedo_gain` 2.0 → 1.8.
- **Unchanged:** the strand radius, the soft and irregular top edge (`top_soft` 0.5, `top_jag` 0.35), and the thinning tail.

**Verdict.**
- **Hero:** the brows read heavy and dark at bust distance (`fh/hero_turntable_bust.png`, `fh/hero_hero_bust.png`). At eye distance the individual strands and the skin between them still show, and the top edge stays soft (`fh/hero_turntable_eye.png`, `fh/hero_turntable_brow.png`).
- **Game:** the bust render shows a dark, defined brow that matches the hero (`fh/game_turntable_bust.png`). In extreme close-up the shells are still dashes (`fh/game_turntable_brow.png`).

**Checks.**
- read40 eye band: 0.598 (0.593 in full8).
- Beard contrast: 0.893.
- glTF: 0 errors; LOD0 is 121,359 triangles.

## Round 3 (lashes and brows from the main4 eye close-up)

Evidence run: `data/build/lookdev/20261012T232216Z-fhv2-full8`, built on main `1e8d26f`. Renders are in `fh/`.

| Item | Change | Verdict |
|---|---|---|
| Lashes read as a few thick black spikes | **Upper:** 165 → 190 per eye. Root radius 0.04–0.05 mm (was up to 0.055), tapering to 15 % at the tip (was 25 %). Clump guide distance 1.2 → 0.6 mm, giving clumps of about 3–5. Dark brown: melanin 0.99 → 0.96, redness 0.45. **Lower:** 80 → 60 per eye at 0.7× the radius. **Game:** the strip draws finer, brown lines (1.6 px, `#2a1f17`). | **Fixed.** A fine, dark-brown, clumped fringe curving up and out; the lower lashes are sparse and fine. full8 was built with a finer first pass (radius 0.035–0.045 mm, tip 5 %, melanin 0.94), and at close-up the fringe there is almost too faint (`fh/hero_turntable_eye.png`). The committed values are one step back toward visible. They are checked on `20261012T235412Z-fhv2-dev16/fh/hero_turntable_eye.png`, a no-refine build with the same lash code, against full8's settings in `…231727Z-fhv2-dev15`. |
| Brows are dense, dark, thick bars with a hard top edge | **Density:** 230 → 185 roots/cm² (1,050 → about 810 per side). **Strands:** radius 0.03–0.045 mm, tip 15 %. **Values:** 20 % of the hairs are a lighter brown (melanin 0.9). **Top edge:** a softer falloff (+0.5 band height) with an irregular wobble. **Tail:** thins from 50 % along the brow to 10 % density. **Game:** the shells bake 55 % of the strands at 1.0× width and 2× albedo, with `visible_shadow` off. | **Fixed** (hero), **improved** (game). **Hero:** fine strands with skin showing through, lighter hairs mixed in, a soft irregular top, and a tail that thins out (`fh/hero_turntable_brow.png`, `fh/hero_turntable_eye.png`). At bust distance the brow is now softer and lighter than round 1's "heavy" brow (`fh/hero_turntable_bust.png`). If the review wants more weight back, the knob is `groom.per_cm2`. **Game:** lighter and sparser. In extreme close-up the shells are still black dashes (`fh/game_turntable_brow.png`), but at bust distance the game brows read close to the hero's (`fh/game_turntable_bust.png`). |
| Game upper strip short at the outer corner | Over the outer 40 % of the lid the strip keeps its full forward run (it no longer sinks into the recess under the hood). | **Improved.** The upper strip now runs to about 90 % of the lid toward the outer corner (about 2/3 in dev14); see `fh/game_turntable_eye.png`. |

**read40 eye band:** 0.593 here, against 0.626 in full7. Lighter, see-through brows darken the eye band less. That is the cost of this request; the metric is still mostly the socket shading.

## Round 2 (after the first merge)

Evidence run: `data/build/lookdev/20261012T221954Z-fhv2-full7`, built on main `2949bf7` (A's skin v2, E's stage, B's hair). Renders are in `fh/`.

| Item | Verdict | Notes |
|---|---|---|
| Under-lip bare strip (hero) | **Fixed** | The strip was lip-group skin: the lower lip's bottom band, under its curl and facing forward again, which A's texture paints close to skin. The beard kept off the whole `lips` group, so that band stayed bare. That band (3 mm, `lower_lip_root_m`) now takes roots. A projection probe along the moustache camera shows strands start right at the lip's curl, where before there was 4 mm of bare skin. See `fh/hero_hero_moustache.png` and `fh/hero_turntable_moustache.png`. The game shells still leave a thin strip there. |
| Game beard near-black and blotchy | **Improved** | **Bake:** the shells take 60 % of the beard strands and 35 % of the stubble (`beard_keep`, `stubble_keep`), because a baked hair is about 3× a real hair's width at this atlas resolution. Colour ×1.6 with saturation 0.8 (lifted warm strands went orange), root shade 0.8, and `visible_shadow` off on the shell object, so the 14 alpha layers don't self-shadow. **Result:** at bust under the turntable the beard's value is now close to the hero's (it was about 50 % darker in full5), with warm and grey specks and skin showing through at the edges. It still reads grainier, more salt-and-pepper, than the strands. In extreme close-up it is blotchy, as shells are. See `fh/game_turntable_bust.png` against `fh/hero_turntable_bust.png`. |
| Game upper lash strip short at the outer corner | **Improved** (hero), **not re-checked** (game) | The upper lashes fan 40° toward the outer corner and are longer there (7.5 mm), so the hero fringe now reaches the corner (`fh/hero_turntable_eye.png`). The margin finder admits narrower openings (0.6 mm). |

**Render script:**
- Game mode now keeps the hero skin and eyes; only hero hair curves toggle.
- Close-ups hide Track B's scalp strands (out of frame, and they multiply render time).
- Game mode does not show B's game hair cards (the head reads bald). That is a visibility issue in the kept blend, not in the GLB.

## Evidence (round 1)

The final run is `data/build/lookdev/20261012T212117Z-fhv2-full5`, built on main `8fa40c6` (A's forms v2) plus this branch's own commits (it was rebased onto `ff03f62`, Track F, afterwards with no conflicts), with `direction.json`. Its renders are in `fh/`.

- Hero rig and turntable rig: `blender/hero/rig.py` (Track E).
- Render script: `bench/m1/v2/facial_hair_render.py`.
- Settings: Cycles, 768 px, 64 samples, `-t 3` (the machine was overloaded).
- File names are `<hero|game>_<hero|turntable>_<view>.png`.

| | Before (baseline `20261012T185610Z-fhv2-baseline`, main as given) | After (`20261012T212117Z-fhv2-full5`) |
|---|---|---|
| Bust, turntable | `fh/game_turntable_bust.png` | `fh/hero_turntable_bust.png`, `fh/game_turntable_bust.png` |
| Moustache over the lip | `fh/game_turntable_moustache.png` | `fh/hero_turntable_moustache.png`, `fh/hero_hero_moustache.png` |
| Cheek line | `fh/game_turntable_cheek.png` | `fh/hero_turntable_cheek.png` |
| Profile | `fh/game_turntable_profile.png` | `fh/hero_hero_profile.png` |
| Brow and lashes | `fh/game_turntable_eye.png` | `fh/hero_turntable_eye.png`, `fh/game_turntable_eye.png` |
| Contact sheets | `fh/sheet_game_turntable.png` | `fh/sheet_{hero,game}_{hero,turntable}.png` |

Also relevant: `data/build/m1-signoff/{closeup,face}.png` (the m1 sign-off baseline) and the lookdev harness sheet of the final run (`sheet.png`, `closeup.png`).

## What changed

| File | What |
|---|---|
| `blender/character/beard_groom.py` (new) | Groom toolkit used by all three: area-weighted root sampling with a density map, strand growth (elevation relaxing from root to tip, comb, yaw, curl, helix share), skin collision, hair-curves objects in `hero_only`, the bundled `Clump Hair Curves` / `Frizz Hair Curves` node groups through the Blender 5.x modifier API (factors from per-curve attributes), Principled Hair BSDF (melanin/redness per strand, root darkening), bone binding, and `SkinRefit` + the `facial_hair_refit` stage. |
| `blender/character/beard_bake.py` (new) | Game bake from the evaluated groom. **Shells:** the patch is stacked along the normal under a canopy height measured from the groom; each atlas tile is the groom's volumetric slice at that height, drawn at the strand foot points with an anti-aliased line rasteriser. **Cards:** 2-vertex-wide strips along groom clumps (spine = clump mean, rolled between lying flat and standing as a fin), each with its own atlas cell. |
| `blender/character/hair_beard.py` (rewritten) | Region and fields: density, stubble, length by zone, comb, grey, chin and soul weights. Also the beard build: groom → GN → read back → shells + cards. Spherical UV for the beard tiles (no under-jaw squash). The upper-lip top band joins the shell patch with zero roots, so the shells carry the moustache overhang. The mouth interior is excluded. `inside_dist` keeps its old signature for `skin_tex.beard_depth`, which follows the same lines. |
| `blender/character/brows.py` (rewritten) | Brow band from the MPFB eyebrow proxy's centre spine: 8 mm tall at the head, 4 mm at the tail. Groom with direction by thirds, then 12 shells plus 20 edge cards per brow. The proxy is dropped. No scar gap. |
| `blender/character/lashes.py` (new) | **Roots** sit on the lid margins, found by ray-casting the final skin against the eyeball; the proxy gives only the base direction. **Lashes:** upper 165 per eye curving up, lower 80 per eye curving down, ragged rows, clumped, skin-collided. **Game:** one 3-row strip per lid with a lash line, 96 tris in total. The MPFB lashes are dropped through the config. |
| `blender/character/facial_hair.py` | Trimmed to the shared helpers (`smooth_field`, `tangent`, `decimate_patch`, `clean_patch`, `guard_tangents`). The old atlas and shell code went to `beard_bake.py`. |
| `bench/m1/v2/facial_hair_render.py` (new) | Close-up evidence renders on the shared rig. Views: bust, profile, moustache, cheek, chin, brow and eye. Cameras are placed from the lips, eyes and the beard's cheek line in the stats. `--mode hero` shows the strands; `--mode game` shows the GLB meshes. |

**Shared-file edits** (all additive):

- `blender/build_character.py`: `beard_groom` added to the import, plus one stage, `b.step("facial_hair_refit", beard_groom.refit)`, after `head_refine`. It carries every groom point and baked vertex by the nearest-surface shift of the refined skin (max 3.1 mm on this build).
- `blender/character/hair.py` (B's dispatcher): `lashes` added to the import, and two lines at the end of `post` call `lashes.build` when `hair.lashes` is set.
- `blender/character/config.py`: only my sections changed. `hair.beard` and `hair.brows` were rewritten and `hair.lashes` is new. `hair.beard.fade_m` (10 mm) was kept for `skin_tex.beard_depth`. Without it the skin's stubble shadow fell back to the frame heuristic (`KeyError('fade_m')` in full1 and full2).
- `hair_mesh.py`, `head.py` and `skin_tex.py` are untouched.

## Numbers (full5)

The direction's numbers are starting points; deviations are noted.

**Beard**
- **Strands:** 44,372 beard + 6,810 stubble. That is above the 25k–40k start point at 200/cm²: the patch, which includes the neck fade, is larger than assumed.
- **Length:** p10 / p50 / p90 = 4.9 / 7.1 / 9.3 mm. By zone: cheek 7.5, jaw 10.5, chin up to 16, soul 10, moustache 9.5 with a 2 mm lip overlap, neck 9.
- **Density:** 200/cm² full and 60/cm² stubble.
  - The cheek line fades over 10 mm in: full → 0.15 line density → 1–2 mm stubble.
  - The neckline fades over 14 mm in and 6 mm out.
- **Strand radius:** 0.04–0.07 mm (hero).
- **Curl:** 25 % of strands curl, with an 8–15 mm radius.
- **Roots:** 0.5 mm into the skin.
- **Tone:** melanin 0.98, redness 0.45, plus a 12 % warm-brown share. Grey is 2.5 % everywhere plus up to 5 % extra at the chin and sideburns, measured at 3.0 % overall.
  - The local share at the chin and sideburns is about 5–7 %, but the overall share is under the 5–8 % start point.
  - Raise `tone.grey_share` if the beard should read greyer.
- **Game:**
  - Shells: 14 on a 420-tri base = 5,880 tris; atlas 2048 × 3584.
  - Silhouette cards: 180 = 1,074 tris; atlas 2016 × 640.
  - Beard total: **6,954 tris**.
- **Shells vs direction:** 14 shells rather than about 16. This is a budget choice: 16 shells would add 840 tris.

**Brows**
- **Strands:** 1,063 / 1,047 per side. That is above the 500–700 start point: at 230/cm² they hold the "dark, heavy" read and the eye-band darkness. Set `per_cm2` to 150 for about 700.
- **Length:** 6–8.5 mm, p50 6.2 mm.
- **Direction by thirds:** the head goes up and out, the middle is flat, the tail runs out and down.
- **Lie:** elevation 22° at the root relaxing to 4° at the tip, i.e. 68–86° to the normal (direction: 80°).
- **Game:** 12 shells + 20 cards per brow = **1,220 tris**.

**Lashes**
- **Upper:** 165 per eye, 4.5–10 mm, longest at the outer middle. Curl 55°, mostly forward.
- **Lower:** 80 per eye, 1.8–4.5 mm.
- **Game:** 2 strips per eye, **96 tris** in total, 512² atlas.
  - The strips are built on the collided lashes.
  - The upper strip's forward run is scaled by 0.6, so it faces the viewer rather than lying edge-on.

**Totals**
- Facial hair: **8,270 tris** (budget about 10k).
- LOD0: 116,893 tris.
- glTF validator: 0 errors.
- Tangent guard: 0 nudged / 0 culled on all three.
- Weights: ≤ 4 per vertex.

**read40**
- Beard contrast 0.955 (pass).
- The eye band is 0.652 (≥ 0.75 fails), against about 0.636 for main's own head at A's forms freeze, 0.628 for full1 and 0.670 for full4. Most of that metric is the head's eye-socket shading (Track A). In no-refine builds the brows and lashes alone moved it by about ±0.08.

## Beard extents for Track B (direction §7)

From `character.stats.json` → `beard` (world metres, rest pose, `direction.json` on forms v2).

- **Sideburn top: z = 1.707.**
  - It sits 4 mm below the ear landmark (`sideburn_up_m` −0.004) and 4 mm in front of the ear's front edge (`sideburn_back_m` −0.004).
  - Under the stubble fade, stubble reaches about 4–6 mm higher.
  - Hair that falls in front of the ear should land at or above z ≈ 1.71, or overlap the sideburn's top 1 cm. The sideburn's top 1 cm is stubble-density fade, not a hard edge.
- **Cheek line (y, z),** from the sideburn to 10 mm above the mouth corner: (−0.071, 1.707) → (−0.104, 1.672) → (−0.138, 1.678). Full density starts 10 mm inside this line, and stubble runs 4 mm outside it.
- **Neckline (y, z):** (−0.108, 1.586) under the chin → (−0.055, 1.651) under the ear.
- All of these are computed from landmarks every build. If A's head changes again, read the new values from the stats rather than these numbers.

## Verdict per defect

| Defect | Verdict | Notes (what still reads as CG) |
|---|---|---|
| Beard reads as a pasted single-tone patch | **Fixed** (hero), **mixed** (game) | **Hero:** strands with direction flow (down and back on the cheek, forward at the chin, down at the moustache), a near-black brown with warm strands and a few grey, and visible skin at the edges. It holds under both rigs. **Game:** at bust distance it reads as a full dark beard with an irregular, stubbled edge, which beats the baseline's hard patch. But it renders near-black, much darker than the strands; in Cycles the 14 alpha layers self-shadow. In extreme close-up it is a blotchy black mass, arguably worse than the baseline's brown dashes. The lookdev `closeup.png` (the GLB) shows the same, with a ragged dark neck fade under the jaw. See `fh/before_after_turntable.png`. |
| Hard cheek outline | **Fixed** (hero), **improved** (game) | **Hero:** a density gradient with stubble specks past the line and a wobble along it. **Game:** the shell density follows the same field, but the stubble band is weak at the 1024-tile resolution, so the edge is softer than the baseline but still a visible boundary up close. |
| Moustache does not connect / sit over the lip | **Fixed** (hero), **improved** (game) | **Hero:** it overhangs the upper lip by about 2 mm, connects at the corners, and leaves a natural parting at the philtrum. **Game:** the shells now cover the lip's top band, which has no roots, so the overhang reads. Two centre cards hang a little straight, like wisps. |
| Neckline | **Fixed** (hero) | The neckline sits 15 mm under the jaw edge and fades through stubble on the neck. It is mostly hidden by the shirt collar in the bust. |
| Under the lower lip | **Not fixed** (small) | A strip of about 3 mm stays bare under the lower vermilion and shows as a light patch at bust distance. **Cause:** the beard keeps off the whole `lips` vertex group (weight > 0.5), and that group runs about 3 mm past the visible vermilion. The hairs rooted in the fold below are there (200/cm², standing about 3 mm off the skin) but grow downward, so the strip's top is covered only by their roots. full4 stopped treating the lip's underside as "under the jaw", which had combed those hairs back into the fold; that is in the build but the strip shows no visible change. dev9 also tried standing those hairs up and forward; it changed nothing visible and was reverted. **Real fix:** root on lip-group skin outside A's vermilion mask (`skin_tex`'s `lw`), which needs a shared mask from Track A. |
| Brows like paint strokes | **Fixed** (hero), **improved** (game) | **Hero:** individual dark hairs that lie flat, run in a direction by thirds, and thin out toward the tail. A slightly too even top edge. **Game:** fine at bust distance. In extreme close-up the shells are black dashes, and the tail's cards stick out a little. |
| Lashes (no visible lashes, MPFB cards) | **Fixed** (hero), **partly** (game) | **Hero:** a clumped upper fringe curving up over the iris and thin lower lashes. Up to full3 the upper lashes were invisible: snapping the proxy roots to the nearest skin had put them **inside the eyeball** after A reshaped the lids. Ray-cast lid margins fixed that. **Game:** the upper strip reads as a dark fringe over the iris since full5, but it is narrower than the lid at the outer corner. In extreme close-up it is a flat card, weaker than MPFB's stock lash cards, which were heavy but very visible. Up to full4 it was nearly invisible: it was built on the pre-collision lashes, which run inside the hooded lid, and it lay edge-on. |
| Grey share | **Deviation** | 3 % overall; 5–8 % only locally at the chin and sideburns. It is a one-number config change if the review wants more. |

## Iteration log

| Run (`data/build/lookdev/…`) | Change | Verdict |
|---|---|---|
| `20261012T185610Z-fhv2-baseline` | Main as given (shell beard, MPFB lashes) | Pasted single-tone patch, hard line, paint brows. |
| `…T1905*–T1907*-fhv2-dev1` (5 runs) | First groom (hair curves, density, comb) | Crash fixes: the node library path, Blender 5.x modifier inputs (`mod.properties.inputs`), and `fh_root` vs leftover base verts. |
| `20261012T191308Z-fhv2-dev2`, `…191611Z-dev3` | Hero groom tuning: lengths and elevations by zone, GN clump and frizz, cheek fade | Iterated to the zone lengths and lie in the config. |
| `20261012T192055Z-fhv2-dev4`, `…192514Z-dev5` | Game shells and cards baked from the evaluated groom; spherical UV for the beard tiles | The game version follows the groom. Shells render darker than the strands. |
| `20261012T193540Z-fhv2-dev6` | Brow and lash grooms, brow patch selection, lighter shell swatches | Brows read as hair. The no-refine read40 eye band dropped from 0.83 to 0.75 because the brows were too light. |
| `20261012T194100Z-fhv2-full1` | First full build (refine plus the `facial_hair_refit` stage) | Beard convincing under the turntable; the coordinator agreed. Too ginger; upper lashes missing; read40 eye band 0.628. |
| `20261012T200522Z-fhv2-full2` | Melanin 0.98, darker brows, upper-lip shell band, mouth-interior exclusion, lash skin collision | Tone right; the game moustache covers the lip. Upper lashes still missing. Found `skin_tex` falling back on `KeyError('fade_m')`. |
| `20261012T201647Z-fhv2-dev7` | Lash curl 85° → 55°, forward 0.4 → 0.8 | Still no upper lashes. Measured: the roots were 8 mm from the eye centre, behind the eyeball surface. |
| `20261012T202422Z-fhv2-dev8` | Lash roots on ray-cast lid margins | Upper lashes visible, on the margin, curving up. |
| `20261012T203013Z-fhv2-full3` | Rebased on A's forms v2; heavier lashes; `beard_depth` API restored | All good except a 3–4 mm bare band under the lower lip. Traced to the "under jaw" rule catching the lip's underside. |
| `20261012T205240Z-fhv2-full4` | "Under jaw" only 20 mm or more below the mouth | No visible change under the lip (see the verdicts). The game upper lash strip is nearly invisible. |
| `20261012T211335Z-fhv2-dev9` | Under-lip hairs stand up 25° more and comb forward | No visible change; reverted. The bare strip is lip-group skin (see the verdicts). |
| `20261012T211746Z-fhv2-dev10` | Upper lash strip tilted toward the viewer | Still faint: the strip followed lashes before the skin collision, so it sat inside the lid. |
| `20261012T211953Z-fhv2-dev11` | Strips built on the collided lashes, then pushed 0.3 mm off the skin | The upper strip reads as a fringe. |
| `20261012T212117Z-fhv2-full5` | Full build of the above | **Final evidence.** |

## Open items

- **Game beard tone.** In Cycles the shells self-shadow and render darker than the strands. A real-time engine would not self-shadow them at this scale. If the in-engine read is still too dark, raise the shell swatches about 15 % or cut the root shade.
- **Atlas size.** The beard shell atlas is 2048 × 3584, which is not a power of two. It is fine for glTF and WebGL2; repack to 2048 × 4096 if the runtime wants mips on every axis.
- **Brows after A's forms v2.** They pick up the +1.5 mm brow shelf automatically through sampling. Their position is not locked.
