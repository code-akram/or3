# Checkpoint 3: the realism roadmap (m1 v4, 2026-10-14, Fable)

> **Orchestrator notes:** C2 full realism, full suit rebuild and costume kept are the user's decisions of 2026-10-14 (NOTES Decision log). Wave 0 launched: T22 (hands and neck) beside T10, T13, T15. T25's plate test needs the user's yes before any photos are collected.

Read-only. Viewed: the `t12-b2` engine frames (`game_portrait_beauty`, `game_closeup`, `game_front`, `game_three_quarter`, `game_profile`, `detail_strip`), the `t12-b2` Cycles hero (`portrait`, `portrait_crop`, `sheet`), the T11 and T12 gate sheets, the code in `web/src/character/` on `main`, the T10 worktree's `ao.ts` / `hairshadow.ts` headers and commit list, `engine_stage.json`, `character.stats.json`, `game_shots.json`, the three r186 `tsl/display` node set, NOTES (decision log, §7, §10, §15, §16), HANDOFF, `fable_review.md` §3–5, both checkpoints and every v4 report. Nothing under `private/` opened; nothing modified, built or rendered.

**One fact that changes how the frames must be read.** The `game_*.png` in `…/lookdev/20261014T184620Z-t12-b2/` were re-shot at 19:08 UTC by a viewer that reports `hair_shadow: "deep (hair twins)"`, `fill_shadow: true`, `gtao: {half_res: true}`, 22 draw calls and 10 shadow maps (`game_shots.json`). None of those exist on `main` (`grep gtao web/src` is empty); they are T10's (worktree `agent-a17e23dad5f61f565`, five commits, merged T12 at `e3f085f`). So the engine frames below already **include** T10's deep hair shadow, shadowed fill and GTAO. Everything I list as a gap is a gap *after* T10.

---

## 1. The realism bar

### 1.1 Definition for this project

"Believable AAA realtime hero" is a 3-second test at two distances, in the engine on the Air, with the user as the judge and no prompt:

- **Gameplay distance** (third-person camera, 2.5–4 m, head 60–120 px at 1470×956): the figure reads as a man in a tailored suit, not a mannequin. What carries it: garment structure (shoulder line, lapel roll, sleeve pitch, skirt hang, trouser break), silhouette of the hair against the background with single flyaways, contact shadows at collar/jaw/hairline, a cloth sheen that moves with the camera, weight in the pose.
- **Cinematic bust** (85 mm, head ~400 px at 1080p, the hero portrait): a viewer cannot name a CG tell in 3 seconds. The tells to kill, in order of how often they are named on today's frames: single-sheet skin specular; porcelain sclera and oversized glassy irises; hair as ribbons with a uniform tone; beard as fur with a cut edge; flat lapel panel; no shadow where surfaces meet (lid on globe, collar on neck, hair on scalp, ear on head).

Concretely, per system, the engine frame must show: a soft red-shifted terminator with transmission at ears and nose; two specular lobes broken by a micro-normal at 2.6 px/mm; pores and fine lines resolved at the portrait distance; hair with a dark core, a lit rim through a self-shadowing mass, individual strands at the silhouette and hairline; beard fading through stubble into skin on cheek and neck; eyes with a refracted iris that parallaxes, a lid contact shadow, a wet meniscus line and an emitter-shaped catchlight; a jacket with real drape; soft area shadows whose penumbra grows with distance; grain, bloom and a physically parametrised DoF; and all of it temporally stable in a 2 s turntable.

**For the Cycles hero** the bar is photographic: the portrait next to lighting/material plates (not face references) survives "which is the photo?" more often than chance. Today's hero fails that test by itself; see §3.

### 1.2 Comparables and what they do that we don't

| Comparable | What it is | What it does that we don't (specifically) |
|---|---|---|
| **The Last of Us Part II (Joel, PS4)** | The reference for a bearded hero on 2018 console GPU budgets, at our camera distances | Card beard with per-card alpha + flow + baked AO and a *stubble normal + albedo pass* under it; pose-space wrinkle maps on face and jacket; screen-space SSS; hair cards with deep-opacity shadows; dual-lobe skin spec with a tiled micro-normal. |
| **Death Stranding (Decima, Sam)** | Hair, cloth and rain under coloured rims, our light language | Deep shadow maps on hair with the rim treated as transmission; cloth with anisotropic sheen that reads as fibres at bust distance; PCSS-style soft shadows from area emitters; a short post chain (TAA, DoF, grain) that sells the lighting. |
| **Hellblade II (Ninja Theory, UE5)** | The ceiling for eyes and lighting | Eye: physically refracted iris with caustic, meniscus and lid AO geometry, sclera with vein normals, catchlights shaped by real area lights. Lighting: everything is an area light with shadows; nothing is a point/spot. Their strand hair and 4D capture are out of reach and not needed for the bar. |
| **Unity "Enemies" (2022, Lee Perry-Smith's "Digital Human" package, MIT)** | The one place the skin recipe is open code | Tension/wrinkle maps driven by the rig; a 0.1 mm detail-normal tile sampled 50×; roughness variation 20–30 % with specular occlusion from cavity; screen-space SSS with a thickness map for transmission; eye refraction shader. The package's shaders are readable as a spec for our TSL port. |
| **Red Dead Redemption 2 (Arthur's coats)** | Garments in a third-person game | Pattern-based garments with drape geometry, cloth bones from sim, per-pose wrinkle normals, a dust/cavity layer in the roughness. This is T13's target. |

There is no browser project at this bar; the nearest web work (Threejs-Punk, Neon Zenith) is environment, not character. The bar we are importing is 2018–2022 console hero quality, not 2024 strand/MetaHuman quality, and that is the right bar for a fanless Air.

---

## 2. Gap list by system, ranked by impact on the read

Rank is by how much each system moves the 3-second verdict on today's frames. Two are already owned by running tracks and are marked.

### 2.1 Suit and cloth (gameplay distance: the single biggest tell) — **T13 running**

- **Now.** `game_three_quarter.png`, `game_front.png`, `game_profile.png`: a lofted shell. Straight sleeve tubes with no pitch, square shoulders, a flat lapel panel with a drawn edge, no fold anywhere except the baked wrinkle normal, a skirt that follows the seat. In the engine the wool reads correctly dark (T3/T6) with a visible twill tile, but the surface is a smooth sheet with a uniform sheen. In the Cycles portrait the lapel is still a flat plane (`c_portrait.png`).
- **Realism requires.** Drape geometry (T13), then: a sheen that breaks up (fibre-scale normal + roughness variation), a cavity/dust term in roughness from the drape, pose-space wrinkle normals (T13 item 7), cloth bones from the sim (T13 item 6).
- **Feasible technique.** Nothing new in the engine beyond what T13 already plans; the cloth model (sheen + fuzz rim + weave tile) is adequate once the geometry is real. Add: roughness micro-variation tile for wool (0.5 mm period), a `KHR_materials_anisotropy`-driven sheen direction per panel (the pattern UVs give grain for free).

### 2.2 Skin (bust distance: the biggest tell once the hair is right)

- **Now.** `game_portrait_beauty.png`: one continuous warm specular sheet across forehead, nose and cheek; the surface reads as painted vinyl. `g12_engine_face_crop_before_after.png` (right) shows T12's gain: forehead lines, a broken highlight on the forehead, periorbital darkening. But cheeks, nose and chin are still smooth, and the specular is still one lobe in practice (lobe mix 0.2 at 1.45× roughness is invisible against roughness std 12 %). Cycles (`c_portrait_crop.png`): soft, even, waxy; forehead lines show, cheeks do not; `hero_mid_gain` 1.5 was needed to see anything at f/2.
- **Realism requires.** 0.1–0.3 mm micro-normal everywhere (not just height in a 4k map: the 4k map is 0.13–0.25 mm/texel, so pores are 1–2 texels and the mip chain erases them), roughness structure 20–30 % with specular occlusion from cavity, SSS that blurs the *shading* (not only the terminator), transmission at ears/nose/lids, lip wetness, albedo structure at 1–20 mm (haemoglobin/melanin layers; today's Lab a* σ is 0.86 vs ≥ 1.5).
- **Feasible on the Air (TSL).**
  - **Detail normals**: two tiled 512² normal tiles (pore tile at ~1.5 mm period, micro at ~0.3 mm), blended by the existing `skin_head_hero_pores.png` and a region mask (pores dense on nose/cheek, fine on lids), faded by `fwidth` beyond ~40 px/mm so distance does not sparkle. Cost ~0.1 ms. This is the single highest-value skin change for the engine.
  - **Dual-lobe spec that shows**: lobe2 roughness ×1.45 → ×2.0, mix 0.2 → 0.35, and a cavity term (bake `cavity` into ORM blue, it is free in `skin_tex.py`) multiplying lobe1 only. Roughness std 12 % → 22 % with the structure terms, spatially correlated with the pore mask.
  - **Screen-space SSS (Jimenez separable, 2015)**: a skin stencil (write 1 into the MRT alpha for skin materials), two separable blur passes with the hero profile in world mm using depth, on the half-float scene target before post. ~0.5–0.7 ms at 1470×956. Replaces the LUT for the diffuse where present; the LUT (`sss.ts`) stays as the fallback tier. Add a baked thickness map (Cycles AO-inverted bake, 1k) for a transmission term at ears, nostrils and lids.
  - **Hero (Cycles)**: add a micro-displacement tile to `hgt_hero` at the pore scale; keep random-walk; drop OIDN to a lighter prefilter on a skin mask and set the film filter to 1.0 px (fable_review §4.7 item 7); these two alone currently erase the detail T12 added.

### 2.3 Hair (bust: second tell; silhouette at gameplay distance) — **T15 running (volume/hairline/colour)**

- **Now.** `game_closeup.png` (neutral rig): light-brown straw ribbons; individual cards legible as ribbons at the temples and crown; the ear-side lengths are flat plates; no connection between sideburn and beard (a bare skin gap at the jaw). `game_portrait_beauty.png` (hero rig, with T10's deep shadow): the crown is now dark and the back-lengths glow, which is the right value structure, but each card still reads as a ribbon with a hard alpha edge and no strand-level breakup at the silhouette. Cycles (`c_portrait.png`): a soft dark mass, bluish rim, but warm/mauve lengths, not the brief's near-black (T12 left this at "within 10 % of main9" and not near-black).
- **Realism requires.** Strand-level alpha at the silhouette and hairline; a dense core so no scalp shows through at any angle; cards that bend out of plane so highlights break; 2× today's card count with thinner, longer, twisted cards in the outer layers; single flyaways (1-strand cards, 1–1.5 px wide, hashed alpha); self-shadow (T10, done); a multiple-scatter colour term (T9b, done).
- **Strands vs cards: cards, finally.** The §5.4 revision stands and the user decision does not reopen it. WGSL has 32-bit atomics only; the one WebGPU strand renderer found runs 3.3 ms on an RTX 3060 for the fine pass with flicker and no TAA; on an Air with thermal throttling the realistic estimate is 4–8 ms for a close-up and an unknown amount of flicker, for a feature that only the cinematic camera sees. Dense cards with deep-opacity shadows is exactly what TLOU2 and Death Stranding shipped. A strand *cinematic mode* can be a post-m1 experiment (NOTES §7 already says so).
- **Feasible technique.** Hair v5 cards: 45–55k tris (from 23k), four outer layers of narrow (≤ 8 mm) twisted cards baked from 8–12 strands each, 1-strand flyaway cards (hashed alpha, no A2C), hairline baby-hair cards at 0.5 mm/px; a per-card bent normal (half-cylinder) replacing the flat proxy normal; a baked per-card directional occlusion (6 directions from groom density) as a fallback where the deep shadow is off (gameplay tier). Alpha: switch from A2C+MSAA to **hashed alpha + TRAA** (see 2.8) for the shipping path.

### 2.4 Eyes

- **Now.** Both renderers: irises too saturated (amber), sclera too white and lit from both sides, no lid contact shadow, no meniscus, a hard point catchlight; the lids do not wrap the globe (full iris top visible in `c_portrait_crop.png`), and lashes are a few black strokes (`e_detail_strip.png` left). The Cycles crop's eyes are the main reason that face reads as a doll. Engine `g12_engine_face_crop` right: the periorbital ring helped; the globe itself is unchanged.
- **Realism requires.** Refraction through the cornea (IOR 1.376) with iris depth; iris normal/structure map; caustic (light-direction brightening on the iris side opposite the light); sclera that darkens toward the canthi with a vein normal; lid AO (a shell or a baked occlusion by lid angle); a meniscus and caruncle; an emitter-shaped catchlight; 2–3 rows of lashes with a root shadow strip; a less saturated, darker iris.
- **Feasible technique (TSL).** Parallax exists (`eye.irisDepth`); replace it by a true ray refraction against the cornea sphere in tangent space (the eye UV is already polar); iris albedo+normal (procedural at bake time in `eyes.py`), a caustic term `max(0, dot(refractedL, irisN))` scaled by `1 − irisDepth`; sclera redness gradient and a 512² vein normal; a lid-AO shell (two 60-tri strips per lid, alpha gradient) and a meniscus strip exported from the hero's `eye_meniscus_hero`; cornea GGX against the **rect** emitter (LTC, exists in `EyeLightingModel`) so the catchlight is strip-shaped. Cost negligible. Hero side: iris saturation −30 %, upper lid −1 mm over the iris (T7b set aperture; the wrap is still short), sclera `#bdab9d` → with a darkening toward the canthi.

### 2.5 Lighting, shadows and AO

- **Now (with T10).** Key/rim/kicker/fill are PCF spots with radius from emitter size; the hero rig is 9 lights and 10 shadow maps at 2048² (`game_shots.json`); GTAO half-res multiplies direct diffuse; LTC rects exist but are opt-in because they cast no shadow; a near-black world with no bounce. The shadows in `game_three_quarter.png` on the floor are the right softness; on the body the terminator and the collar/jaw contact still read hard (`game_portrait_beauty.png`: the collar sits on the neck without a contact gradient).
- **Realism requires.** Penumbra that grows with blocker distance (PCSS); contact-scale shadows under the lid, nose, collar, hair edge; specular occlusion (GTAO drives diffuse only); a dim bounce from the set so shadow sides are not pure rim.
- **Feasible technique.** PCSS as a custom `LightShadow.filterNode` (T10 already wrote one for hair: same mechanism, blocker search + variable kernel), 3 shadowed lights at 2048, twins share their parent's depth. **Screen-space contact shadows**: three r186 has `SSSNode` (screen-space shadows) in `tsl/display`; run for the key only, 8–12 steps, 0.3 ms. **Specular occlusion** from the GTAO term (Lagarde's `so = saturate(pow(nv + ao, exp2(-16 r − 1)) − 1 + ao)`). **Hybrid LTC**: LTC specular for all lights + shadowed-spot diffuse (T6's own proposal), so the rim gives a strip highlight on hair and wet eyes and still casts. **Set bounce**: a 32² cubemap of the alley set rendered once in Cycles (no character) exported as a sidecar, used as environment at ~0.02 of the key; it removes the "black box" read of the engine beauty portrait (`e_game_portrait_beauty.png` background is pure black while the Cycles portrait has the set).

### 2.6 Post: AA, TAA, DoF, grade

- **Now.** 4× MSAA with A2C, no TAA, no DoF, bloom/halation/grain ported, AgX via three's approximation never checked against Blender's with a chart. `idLodBias −2` will shimmer in motion (T9b said so; T10 added a 2 s turntable to see it).
- **Realism requires.** Temporal stability (the single biggest realism cue in motion), a physically parametrised DoF for the bust camera, grade identical to the Cycles compositor.
- **Feasible technique.** **TRAA** (`TRAANode`, r186; velocity for skinned meshes is supported by three's velocity node) with **hashed alpha** for hair and MSAA off; this is the AAA default and it also fixes A2C dither on thin cards. Risk: ghosting on hair; mitigation: a hair-responsive history clamp (variance clipping is in TRAANode) and keep the MSAA path for parity stills. **DoF**: `DepthOfFieldNode` driven by `camera.fstop`/`focus_m` from `engine_stage.json` (85 mm f/2 at 1.466 m → CoC from the thin-lens formula, not the node's arbitrary units), beauty only. **Grade as data**: export `grade.py` as a 33³ 3D LUT (`Lut3DNode`) so the engine grade is the Blender grade by construction, and run the grey/colour-chart check once in both renderers (±3/255). **TAAU** (r186) as the dynamic-resolution path: render at 0.75–0.85 scale and reconstruct, which is the Air's safety valve.

### 2.7 Beard and brows — partly T11 done

- **Now.** `g11_detail_moustache.png` (middle): the moustache's lower edge is a fringe of dark spikes over the lip where Cycles (bottom) is a soft overhang. `e_detail_strip.png` centre: the beard is a dense card fur with a visible tile direction; the cheek fade is good now; the back edge at the jaw is a cut; sideburn-to-beard is a gap. Brows: a soft band now (`g11_detail_brows_hero`), still lighter and spikier at the tail than Cycles. The engine beard reads warmer than the cool Cycles beard under the hero rig (T11 §1: the blue kicker does not reach it).
- **Realism requires.** A stubble layer (normal + albedo, not only albedo) under the cards, lip-edge cards that follow the lip curve with an alpha gradient across the overhang, a multiple-scatter body term for facial hair (`facialHair.scatter` is 0), sideburn continuity cards, and self-shadow between beard cards.
- **Feasible technique.** Fewer, broader lip-edge cards (T11's own fix); a stubble normal tile in the skin detail layer weighted by the beard root density (shares T17's detail-normal machinery); facial hair gets the hair twins' deep shadow (T10's filter applies by material group; check the beard is in the receivers); `facialHair.scatter` ≈ 0.004 fitted on the hero-rig closeup. Cheap: 1–1.5 days.

### 2.8 Hands and neck

- **Now.** `e_detail_strip.png` right two panels: smooth doughy fingers, no knuckle planes, no tendons, a tube wrist; T12 added a subtle vein normal. Neck: one bone, no SCM/larynx form (`game_profile.png`).
- **Realism requires.** Knuckle planes, extensor tendons, metacarpal heads, nail bed/cuticle, skin folds at the PIP joints, veins as 0.5–1 mm relief; neck SCM and larynx.
- **Feasible technique.** The `head_sculpt.py` landmark-field machinery applied to hand and neck landmarks (fable_review §4.7 item 1), baked into `skin_hands_normal` and geometry; `corr_fist` correctives for the joints. Blender-only, 2 days, no engine work.

### 2.9 Animation and deformation

- **Now.** LBS, 83 bones, 14 correctives, no neck/wrist/clavicle correctives; the hero pose is a static A-pose with a slight stand. Nothing moves yet, so this ranks last for the still-frame gate but first for m2.
- **Realism requires.** DQ or hybrid skinning (candy-wrapper at wrists/shoulders), cloth bones from the drape, pose-space wrinkle maps, neck/clavicle correctives, breathing and micro-saccade idle (huge for the "alive" read at bust distance, and nearly free).
- **Feasible technique.** DQ skinning in TSL is a `skinning` node override (~0.1 ms); Dem Bones after T13 provides the drape; wrinkle-map blend rides the existing cone rules (`deform.ts` port is verified to 1e-5); an idle layer (breath 0.25 Hz chest/shoulder, blink 12/min, saccade jitter) in the viewer as a first motion test of TRAA.

---

## 3. Engine renderer work beyond T10, and the gate

### 3.1 Work beyond T10 (summarised from §2)

1. TRAA + hashed alpha + velocity, with the MSAA path kept for parity stills; TAAU for dynamic resolution.
2. Skin: detail-normal tiles, cavity/spec-occlusion, visible dual lobe, separable screen-space SSS on a skin stencil, thickness transmission.
3. Eyes: refraction, iris normal/caustic, sclera, lid AO shell, meniscus, strip catchlight.
4. Lights: PCSS filter, screen-space contact shadows (key), specular occlusion, hybrid LTC, set-bounce environment.
5. Post: thin-lens DoF (beauty), Lut3D grade from `grade.py`, chart check.
6. Hair v5 shader side: bent card normals, hashed flyaways, baked directional occlusion for the gameplay tier.
7. Two quality tiers switched by camera distance (hero closeup vs gameplay), see §5.

### 3.2 Does parity-to-Cycles stay the gate?

**Keep it as the regression instrument; stop treating it as the realism gate.** Three reasons from today's evidence:

- The Cycles hero itself fails as realism: doll eyes, waxy cheeks, a flat lapel, a warm hair mass (`c_portrait_crop.png`). Converging the engine on it converges on a 2015 cinematic, not on the bar. T6 said it in other words: "parity with a render that already fails as realism".
- Mean-ratio parity passed twice while the picture was wrong (checkpoint 2 §5.1). Spatial terms (T10) help, but SSIM against a different-silhouette render will plateau at ~0.8 and say nothing about believability.
- The two renderers must now **both** move, and in the same direction, which parity cannot express.

**Proposed two-tier gate.**

1. **Parity row (unchanged purpose):** engine vs the Cycles `--parity` render, shader balls ±10 %, per-region p10/p50/p90, hair crown/back profile, SSIM at 100 % head. It catches drift and calibrates gains. It never approves a look.
2. **Realism row (new): a blind plate test, judged by the user.** A sheet of 6 tiles at identical crop and 100 %: the engine hero closeup (Air capture), the Cycles hero crop, and 3–4 **lighting/material plates**: photographs of anonymous bearded men under a hard key plus coloured rim, at a similar lens. Question: "which tiles are renders?" Pass: the engine tile is picked as a render no more often than a plate across ≥ 6 sheets (different plates each time). Rules so the likeness policy holds: plates are **never** face or form targets, never fed to any fitting or measuring step, never committed (gitignored `bench/ref/plates/`, the pre-commit hook already refuses rasters), selected by the user or by a Sonnet agent from CC0/public-domain sources with a licence record in `provenance/`, and never the actor (private likeness references stay in `private/`, offline, as today). This is consistent with look-spec §7, which forbids photos "as face targets"; plates are a lighting/material comparison and the user can veto the whole idea if they want the stricter reading.
3. **Standing scalars on every realism track:** ArcFace ≤ 0.25 (offline, private, scalar only: realism makes the costume read stronger, and the face must stay original as the look sharpens), head measures in range, tris/texture budget, and the Air frame time once the capture exists.

Also, finally run the **chart check**: an 18 %/50 %/90 % grey chart and a grey ball under the hero rig in both renderers, tolerance ±3/255 after grade. Three AgX vs Blender AgX has never been verified; every colour judgement so far rests on it.

---

## 4. Tracks, T16 onward

Constraints: at most 4 concurrent; T10 (finishing, merge first), T13 (spike 2 → rebuild, ~13 days, holds one slot for the whole period), T15 (1.5 days) are running. Effort is in agent-days as the reports count them; today's observed compression on engine/Blender tracks was about 4–6× (T6's "1 day" landed in ~2 h). The suit does not compress (2.5 min per drape, iteration-bound). Every track: worktree, `nice 10`, Blender `-t 4`, one Cycles render at a time via `flock`, report leads with a 100 % head crop triptych and a three-sentence read, "view your own frame at 100 %" is a required step, ArcFace scalar on the sheet.

| # | Track | Goal | Gate (picture + metric) | Days | Owns / conflicts | Start when |
|---|---|---|---|---|---|---|
| **T16** | **Engine AA/post architecture** | TRAA + hashed alpha + velocity (MSAA path kept for parity), TAAU dynamic resolution, thin-lens DoF from stage f-stop/focus (beauty), `Lut3DNode` grade exported from `grade.py`, grey-chart check, set-bounce cubemap sidecar | 2 s turntable (T10's) with no shimmer at 100 % on hair; chart ±3/255 in both renderers; beauty portrait with DoF next to the Cycles portrait, bokeh radius within 15 % at the ear | 2 | `output.ts`, `main.ts`, hair alpha paths in `materials/index.ts`, `grade.py` LUT export, `lookdev_report.py` chart row. **Conflicts with T10** on `output.ts`: starts after T10 merges | after T10 merge |
| **T17** | **Skin realism (both renderers)** | Detail-normal tiles weighted by pore/region masks, cavity in ORM.b + specular occlusion, visible dual lobe, roughness structure 12 → 22 %, separable screen-space SSS on a skin stencil + thickness transmission (LUT stays as the low tier); hero: pore micro-displacement tile, film filter 1.0, OIDN prefilter on a skin mask, albedo haemoglobin/melanin layers (Lab a* σ ≥ 1.5) | Engine hero closeup at 100 % (T10's capture) next to Cycles crop: forehead/cheek/nose all show relief; metric: skin highlight p99/p50 ratio within 20 % of Cycles, roughness std 20–25 %, a* σ ≥ 1.5, ArcFace ≤ 0.25 | 3 | `skin_tex.py`, `skin_synth.py`, `config.py` skin block, `materials/index.ts` skin class, `sss.ts`, new `ssss.ts`, `hero/stage.py` filter/denoise. Conflicts: T16 on `output.ts` (the SSS passes hook into `Output.render`): land T16 first or expose a pass hook in T16 | after T16 merge (Blender half can start immediately) |
| **T18** | **Eyes** | Refraction + iris depth/normal + caustic, sclera darkening/veins, strip catchlight via LTC, lid-AO shell + meniscus + caruncle game meshes, 2-row lashes with root shadow; hero: iris −30 % saturation, lid wrap −1 mm, sclera gradient | Eye crop triptych at 100 %; metric: sclera/iris luminance ratio within 15 % of Cycles, catchlight area ratio within 30 %, read40 eye band ≥ 0.80 kept | 2.5 | `eyes.py`, `head_refine` eye calls, `wet.py` game export of meniscus/caruncle, `materials/index.ts` eye class, `config.py` eyes block. Conflicts: T17 on `materials/index.ts` (different classes, append-only); T17 on `head_refine` ordering (eye meshes before skin bake) | now (Blender) |
| **T19** | **Lighting and shadows** | PCSS filterNode from emitter size, screen-space contact shadows for the key (`SSSNode`), specular occlusion from GTAO, hybrid LTC (spec for all lights, shadowed-spot diffuse), twins share parent depth maps (10 → 5 maps), set bounce from T16's cubemap | Hero closeup: collar/jaw/lid contact gradient visible at 100 %; metric: per-light hair/skin ratios 0.8–1.2 kept, shadow-map count ≤ 5, Air frame time recorded | 2 | `stage.ts`, `ao.ts`, `hairshadow.ts` (T10's). Conflicts: T10 only; none with T16/T17 if `Output.render` exposes a pass list | after T10 merge |
| **T20** | **Hair v5 cards** | 45–55k tris: narrow twisted outer layers, 1-strand flyaway cards (hashed), hairline baby hairs at 0.5 mm/px, bent card normals, baked 6-direction occlusion, sideburn continuity; engine card albedo mirrors the hero shader (T12 leftover 1 if T15 has not) | ¾ and portrait triptych; metric: hair silhouette IoU vs Cycles ≥ 0.9 (T15's), crown/back profile within 20 % (T10's), no visible single card at 100 % in the portrait (user read) | 4 | `hair_groom_cards.py`, `hair_strand_raster.py`, `export.pack_hair_maps`, `materials/index.ts` hair class. **Conflicts with T15**: sequence after T15 merges | after T15 merge |
| **T21** | **Beard and brows v2** | Lip-edge cards along the lip curve with cross-card alpha, stubble normal under the cards (uses T17's detail layer), back-edge and sideburn continuity, `facialHair.scatter` fitted, beard in the deep-shadow receivers | Moustache/cheek/jaw detail triptych; metric: T11's tone record within 20 %, hero-rig chin box luminance 0.76× → ≥ 0.9× Cycles | 1.5 | `beard_bake.py`, `hair_beard.py`, `brows.py`, `config.py` beard/brows. Conflicts: T17 on the skin albedo under-layer call order; T20 on the hair material class if gains move | after T17 and T20 |
| **T22** | **Hands and neck sculpt** | Landmark fields for knuckle planes, tendons, MCP heads, PIP folds, veins; nail bed; neck SCM/larynx; `corr_fist`, wrist and clavicle correctives | `detail_strip` hands at 100 % before/after; metric: `hand_width_ratio` ≈ 0.55, relief p99 ≥ 0.8 mm on the dorsum, no new pose-test failures | 2 | `hands.py`, `head_sculpt.py` (new field set), `skin_tex.py` hands bake, `deform_rules`. No conflicts with running tracks (T13's sleeves end at the cuff) | **now** |
| **T23** | **Deformation realism** | DQ skinning node, Dem Bones from T13's drape (T13 item 6 produces the data), pose-space wrinkle blend, idle layer (breath/blink/saccade) as the TRAA motion test | Arms-up/fist A/B strip; 2 s idle capture with no ghosting; metric: candy-wrapper angle error at wrist ≤ 5°, wrinkle blend matches Blender to 1e-3 | 3 | `deform.ts`, `poses.ts`, materials skinning node, `blender/character/deform*.py`. Conflicts with T13 on the jacket bones: after T13 | after T13 |
| **T24** | **Air session + tiers** | First device capture (the standing ask), GPU timestamps per pass, the two quality tiers (hero closeup / gameplay) with per-feature toggles, LOD1 (meshopt) at 60k, KTX2 as the gate asset | Air row on the sheet; metric table in §5 filled with measured numbers; 60 fps at the gameplay tier | 1 + user | `main.ts` tiers, `engine_shots.mjs`, `export.py` LOD. Conflicts: T16 (toggles) — coordinate, T16 first | **as soon as the user is at the Mac**; code part now |
| **T25** | **Cycles target retune + plate harness** | Rims ≤ key, a dim wide set fill, film filter 1.0 px, same light colour on all materials (twins only for hair), plate-sheet generator (6-tile blind test, gitignored plate dir, provenance record) | The first blind sheet; chart check passes; metric: lit:shadow ratio ≤ 8:1 on the cheek | 1.5 | `hero/rig.py`, `hero/stage.py`, new `bench/m1/plates.py`, `provenance/`. No conflicts (T3 is merged) | now |
| **T26** | **Integration and m1 realism candidate** | Regression strip main9 → latest, blind sheets ×6, HANDOFF, budget table, LOD chain check, licence audit | User sign-off session | 1.5 | docs, `lookdev_report.py` | last |

**Sequence (4 slots; S = slot).**

- **Wave 0 (now):** S1 T10 → finishing; S2 T13 (through the whole period); S3 T15; S4 **T22** (hands/neck, Blender-only, zero conflicts). T24's code part and T25 can be given to the T22 agent's queue or to a Sonnet-class agent if the orchestrator wants a fifth light thread; otherwise T25 goes next.
- **Wave 1 (T10 merged):** S1 **T16**, S3 (after T15) **T18** or **T25**; T19 waits for T16's pass hook or starts in parallel with a strict "no `output.ts`" rule.
- **Wave 2 (T16 merged):** S1 **T17**, S3 **T19**, S4 **T20** (after T15 and T22).
- **Wave 3:** **T21**, **T24** device session, **T18** if not done.
- **Wave 4 (T13 merged):** **T23**, then **T26**.

---

## 5. Risks and budget

### 5.1 Calendar

Critical path is **T13 at 13 working days (11–16)**; everything else fits beside it in three slots: T16–T22 + T24/T25 ≈ 22 agent-days over three slots ≈ 8 calendar days at the reports' own estimates, and plausibly 2–3 days at today's observed compression. T23 (+3) and T26 (+1.5) follow T13. **Total: about 3.5 working weeks to an m1 realism candidate, dominated by the suit; 2.5–3 weeks if T13 lands at the low end.** The user's two Mac sessions (Air capture; blind sheets) are the only non-agent dependencies, and the first one is already overdue: every engine number so far is SwiftShader, including the T10 frames above.

### 5.2 Hardware: frame-time budget on the Air

Assumptions: 1470×956 internal (TAAU to the panel), one character, hero-rig lights, warm fanless machine (the 12 ms work budget from NOTES §4; m2 criterion is max(CPU, GPU) p50 ≤ 12 ms). Estimates; T24 replaces them with measurements.

| Feature | Hero-closeup tier (ms) | Gameplay tier (ms) | Note |
|---|---|---|---|
| Base skinned character shading (130–170k tris, 22 draws) | 1.8–2.2 | 1.2–1.5 | LOD1 at 60k for gameplay |
| Shadow maps (3 lights × 2048, twins share depth) | 1.0–1.4 | 0.6 (1 light, 1024) | 10 maps today is not shippable |
| Deep hair shadow filter (T10) | 0.5–0.8 | 0 (baked directional occlusion) | |
| GTAO half-res | 0.5–0.7 | 0.3 (quarter) | |
| Contact shadows (key) | 0.3 | 0 | |
| PCSS filter | 0.3–0.5 | 0 (PCF) | |
| Hair cards 50k, hashed alpha, depth prepass | 1.5–2.5 | 0.8 | Overdraw is the real cost; measure |
| Skin detail normals + cavity | 0.1 | 0.1 | |
| Separable SSS (skin stencil) | 0.5–0.7 | 0 (LUT) | |
| Eyes | 0.1 | 0.05 | |
| TRAA + velocity | 0.5–0.8 | 0.5–0.8 | Replaces 4× MSAA (which is ~free on tile GPUs; the swap is a net cost) |
| DoF (beauty) | 0.6 | 0 | |
| Bloom/halation/LUT grade/grain | 0.5–0.8 | 0.5–0.8 | |
| **Total** | **8.8–11.6** | **4.1–5.4** | |

Candid consequence: **the hero-closeup tier consumes the whole 12 ms by itself.** It is a cinematic/portrait mode and can never run with the m4 city stack (NOTES §10 budgets 5–6 ms of scene shading plus ~5 ms of neon-rain). The gameplay tier at ~5 ms leaves the city its 6–7 ms, which is tight but in line with §10. The two-tier design is therefore not optional; T24 builds it, and the "realism bar" for gameplay distance (§1.1) is what the gameplay tier is judged on.

Memory: textures are 602 MB estimated as RGBA8 today (`game_shots.json`); the KTX2 copy is ~70–280 MB depending on transcode target, within the 1.5 GB tab budget with the city. Detail tiles add < 2 MB. Hair v5 atlases should stay at 2048×4096 (bake narrower cells, not more pixels).

### 5.3 Cut order if the Air cannot hold the hero tier at 60 fps

1. DoF → off except in captures (0.6).
2. Separable SSS → LUT (0.6).
3. Deep hair shadow on 3 twins → 1 twin (rim only) (0.4).
4. GTAO half → quarter res (0.3).
5. Shadow maps 2048 → 1024 (0.5).
6. Contact shadows and PCSS → PCF (0.6).
7. Hair 50k → 35k outer layers only at > 1 m (0.7).
8. TRAA at full res → TAAU at 0.8 scale (dynamic resolution, 1.5–2.0 across everything).
9. Never: strands; never reintroduce the direct-AO multiply or the gain hacks.

### 5.4 Other risks

- **The Cycles target is wrong in the same places the engine is** (eyes, cheeks, lapel). If T25/T17/T18 do not move the hero, parity will converge on a doll. Mitigation: the blind plate test, with the user as judge.
- **TRAA + hair.** Ghosting and a softer look are the classic failure; the hashed-alpha switch also changes every hair gate number (A2C dither vs hash). T16 must re-baseline the parity numbers before anyone tunes hair again, and keep the MSAA path for stills so T15/T20 are not blocked.
- **SwiftShader as the only oracle.** A2C dither, anisotropic filtering, timestamp queries and MSAA resolve all differ on Metal. The Air session is the single highest-leverage user action in the plan.
- **Three r186 API churn** (`PostProcessing` → `RenderPipeline`; TRAA requires MSAA off; `GTAONode` sizes from the canvas, which T10 already had to subclass). Pin r186.1 for m1.
- **Likeness drift under realism.** A sharper, more photographic face with the kept costume reads more like the actor, not less. ArcFace ≤ 0.25 stays a standing scalar on every realism track; the user answers the likeness question at the blind-sheet session.
- **Budget creep.** We are at 133.7k tris against a 120k target and 150k cap (NOTES §7), with hair v5 (+25k) and T13 (−8k jacket, +trousers/shirt/waistcoat detail) ahead. Recommend the user raise LOD0 to **170k (cap 190k)** now, with LOD1 at 60k mandatory for gameplay distance, rather than discovering the cap mid-T20. The body alone is 52k (26k verts for head+hands+neck at one subdivision); a 30 % decimation of the back of the skull and the neck under the collar would recover ~10k without a visible change.
- **Agent throughput assumptions.** The estimates above are the reports' own; if the suit rebuild hits the XPBD fallback (+3 days) it is the only item that moves the calendar materially.

### 5.5 Process notes carried forward

- Every realism report leads with the 100 % head triptych and a three-sentence read (checkpoint 2 §5.2); add "which plate tile did you mistake for a render" once T25's sheet exists.
- Mean-ratio gates must carry spatial terms (T10 adds them); no gate on hair or beard passes on a mean alone.
- Record "SwiftShader" in the first line of every report until the Air row exists.
- Keep `fable_review.md` §5.4's "stop doing" list in force, plus: stop tuning gains against Cycles numbers for systems whose Cycles side is itself scheduled to change (eyes, skin spec) until T17/T18/T25 land.