# m1 v2 art direction: the man in the black suit

_Consultation (Fable, strategy only), 2026-10-12. Scope: Cycles hero renders plus the game GLB. No actor names anywhere; the face is ours._

> **Orchestrator overrides (binding):**
> - **No scars.** User ruling 2026-10-12 ("no scar"). Drop the brow-tail scar, its hairless brow gap, and the cheekbone nick from §3 and Track C. Keep the mole and every other asymmetry.
> - Track E: ship the base light rig as a callable script first (commit it on your branch early), before the set dressing; §7.
> - Numbers here are starting points. Your eyes on the renders decide; note the deviations in your report.

## 1. Diagnosis: why the baseline reads as scripted CG

Ranked by visual impact at the hero close-up.

| # | What the pixels show | Why | Track |
|---|---|---|---|
| 1 | **Waxy, uniform skin.** The cheek, nose and forehead are one pink-beige tone with one roughness. The terminator is a hard diffuse falloff with no red bleed. | `skin.sss` is **0.0**. Albedo is a single tone, too light and too pink (mean sRGB 0.73/0.63/0.56). Roughness is nearly flat (mean 0.58). No displacement at render time. | A |
| 2 | **Mannequin facets.** The cheek "plane break" is a creased dent, the brow shelf a bevelled bump and the chin a block. Everything is mirror-symmetric. | `replanarise` runs at 1.0 on malar and submalar and 0.9 on the jaw. Geometry at 1.0 makes a low-poly head. No asymmetry anywhere. | A |
| 3 | **Dead eyes.** Wide-open, level, parallel gaze. The iris is an over-saturated amber. No lid-contact shadow, no wet line, no visible lashes at bust distance. | Aperture too open. No eye-occlusion geometry, no tear meniscus, no limbal ring. Iris albedo too bright. | A (+C lashes) |
| 4 | **Beard like a pasted patch.** A single-value black mass with a hard cheek line and a visible shell-dash texture. The moustache and beard don't flow into each other. | The shell atlas uses one hair colour: no hue or grey variation, only value (σ 0.45). No gloss and no visible direction flow. 20 shells read as stacked dashes at 1k. | C |
| 5 | **Glassy hair straps.** Cards read as flat strips with one continuous anisotropic streak and one value. No root-to-tip gradient. The silhouette is a helmet with a tail. | Cards only in the hero render, with roughness 0.68 and a uniform tangent. No strand groom for Cycles and no scattering. | B |
| 6 | **Brows like paint dashes.** Sparse black ticks floating in a line above the ridge. | 10 shells × 156 tris. Too sparse, too dark and too uniform, with no skin shadow under the brow. | C |
| 7 | **Grey, boxy suit.** The cloth reads mid-grey, the shoulders are blocks, the lapel is a flat dark stripe, the sleeves are straight tubes and the stock trousers bag. No wrinkles at the elbow, armpit or knee. | A wide area key over a grey floor lifts the 0.028 albedo to mid-grey. No sheen fuzz, detail normal or baked wrinkles. No sleeve pitch and no shoulder drop. | D |
| 8 | **A-pose with splayed fingers.** The hands are the second-largest skin area on screen, posed like a rig test. | No hero pose, no finger pose, no contrapposto. | F |
| 9 | **Flat studio light.** One soft key, a grey floor and a black card. No rim, haze, grade or catchlight. | No hero stage exists yet. | E |
| 10 | **No micro-scale.** At 1024² the cheek should show pores at 2–3 px and shows none. The hairline is a hard edge in the close-up. | The normal map's height range is only −0.69/+0.11 mm. No displacement, and the hairline feathering is too short. | A, B |

The first three account for most of the gap. A believable face under a bad light still reads as a person. With this face, a perfect suit under a perfect light still doesn't.

## 2. Targets per track

Units are metres in code and mm in this text. Material values are linear unless marked sRGB.

### Track A: head forms, skin, eyes

**Forms.**
- Drop `replanarise` to malar 0.45, submalar 0.35, jaw_side 0.5, brow_front/under 0.5, nose 0.6, chin 0.4 and forehead 0.5. The planes should be a hint the light reveals, not facets.
- Add soft tissue the lattice can't make:
  - a malar fat pad, 2 mm forward with a 20 mm radius under the zygion;
  - tear trough 1.2 mm;
  - lower-lid bag 0.8 mm;
  - nasolabial fold, 1.5 mm deep at the alar, fading to 0.3 mm at the mouth corner;
  - a glabellar frown line.
- Lower the upper lid so it covers the top of the iris by 1.5–2 mm. The lower lid touches the iris bottom.
- Converge the eyes 2° toward a point 1.2 m ahead.
- Asymmetry is mandatory (§3).

**Skin material (Cycles).**
- Principled BSDF, Random Walk (Skin). Subsurface weight **1.0**, radius (1.0, 0.25, 0.12), scale **0.0025** (2.5 mm red, 0.6 green, 0.3 blue), anisotropy 0.8, IOR 1.4. Keep red ≤ 3 mm, or the skin turns to wax.
- Specular IOR level 0.5 (F0 ≈ 0.028).
- Roughness is a **map**, not a value: T-zone 0.38–0.42, cheeks 0.50, beard zone 0.58, lips 0.45 with vertical crease breakup, ears 0.48. Mean ≈ 0.48.
- Add a Coat at weight 0.15, roughness 0.25, IOR 1.4 as the second specular lobe. This is Cycles only; the game uses one lobe with the roughness map.

**Albedo.**
- Mean sRGB target ≈ (0.70, 0.55, 0.46): darker and less pink than now.
- Three zones:
  - Forehead: +4 % yellow.
  - Mid-face: +8–12 % red at the nose tip, alar, cheek apples and ears.
  - Lower face: cool. The beard zone is darkened 15 % and shifted toward blue-grey, even under the shells.
- Under-eye 10 % darker, violet-brown. Faint blue veins at the temples (3 % effect). AO in the albedo stays ≤ 0.25.

**Micro detail.**
- Pores (normal depth 0.03–0.06 mm):

  | Region | Density | Diameter |
  |---|---|---|
  | Nose | 60/cm² | 0.3–0.4 mm |
  | Cheeks | 35/cm² | 0.25–0.35 mm |
  | Forehead | 20/cm² | 0.15 mm |
- Forehead lines: two, broken, 0.2 mm deep and 1.5 mm wide.
- Crow's feet: 3–4 per side, 0.1 mm deep.
- The nasolabial and frown lines go into **displacement** for the hero renders (adaptive subdivision, dicing 1 px). The game keeps the 4k normal and the 2k ORM.

**Eyes.**
- Iris 11.5–12 mm, dark brown sRGB ≈ (0.30, 0.18, 0.10), with fibre structure and a limbal ring 30 % darker over the outer 12 %. Pupil 4 mm under the hero light.
- Cornea as a separate refractive mesh (IOR 1.376, roughness 0.02), bulging 2.5 mm over an iris plane recessed 0.5 mm, so the parallax reads.
- Sclera (0.88, 0.82, 0.78) with veins, 15 % darker at the corners.
- Tear meniscus along the lower lid: 0.3 mm, roughness 0.05.
- Eye-occlusion shell: an alpha gradient 1.5 mm from the upper lid, opacity 0.6.
- Caruncle present.
- The catchlight is Track E's job, but the material must take a hard one.

**Failure modes:** plastic doll (no SSS, or red radius > 4 mm); faceted mannequin (planarise ≥ 0.7); one roughness and one colour.

**Sources:** MPFB CC0 skin textures as a low-frequency mottle base only; everything else generated.

### Track B: scalp hair

**Cycles groom (render-only, `hero_only`).**
- Blender hair curves: 450–600 guides, interpolated to **18,000–24,000 strands**, 16–24 points each.
- Strand radius 0.045 mm at the root, 0.02 mm at the tip.
- Two-level clumping: 32–40 primary clumps 15–25 mm wide (factor 0.6), secondary clumps 6–8 mm (factor 0.4), and 10 % strays.
- Wave: period 12–18 cm, amplitude 4–8 mm.
- Flyaways: 4 % of strands, with 1–2 cm of noise, mostly at the silhouette and the part.
- Hairline:
  - Temples recede 8–10 mm (an age marker).
  - Feather over 10–12 mm with a density ramp.
  - Vellus hairs 3–6 mm long along the whole hairline.
- Shape (per the spec):
  - Off-centre part 12 mm left.
  - Swept back with a 10 mm front lift.
  - Flat crown, fullest at the occiput.
  - Tucked behind the ears, with tips at the collar ±20 mm.
  - 2–3 front falls on the right, crossing from temple to cheekbone; one thin lock over the left brow.

**Hair shader.**
- Principled Hair BSDF (Huang model in 5.x).
- Melanin 0.95, redness 0.55.
- Roughness 0.22 at the root to 0.30 at the tip; radial roughness 0.3; coat 0.15.
- Random colour 0.08, random roughness 0.1, IOR 1.55.
- The base lands near sRGB #1d1915. No grey.

**Game cards (in the GLB).**
- Bake the groom to a 2048² atlas (albedo, alpha, depth, root, ID, flow) with 10–12 lock variants.
- 450–600 cards in cap, under, mid, top and flyaway layers, ≤ 25k tris.
- Vertex colour carries AO and a 35 % root darkening.
- The silhouette must break ≥ 30 mm beyond the cap at the sides.

**Failure modes:**
- A continuous anisotropic streak (break it with a ±15° flow-map jitter).
- A helmet silhouette.
- The cap or roots visible at the part and hairline.

### Track C: beard, moustache, brows, stubble, lashes

**Cycles beard.**
- Strands: 25k–40k.
- Length: cheeks 6–8 mm, jaw 9–11, chin 12–15, soul patch 10. The moustache is 8–10 mm and overlaps the lip edge by 2 mm.
- Density: 180–220/cm² where full, 60/cm² in the stubble band.
- Cheek line: from the sideburn to 10 mm above the mouth corner. It fades over 10 mm: full density → 0.15 → stubble of 1–2 mm → none.
- Neckline: 15 mm under the jaw edge, with a 20 mm fade.
- Radius 0.06–0.09 mm, coarser than scalp hair. 25 % of strands curl with a radius of 8–15 mm.
- Colour: melanin 0.9, redness 0.6, random colour 0.15. **5–8 % grey at the chin and sideburns** (melanin 0.2). It's the cheapest "real person" signal there is, and it stays off the head hair.
- Roots sit 0.5 mm inside the skin, with a 10 % painted shadow in the skin albedo.

**Game.** Keep the shells (16 layers), but bake the strand groom down to their atlas so the two match. Add 150–250 silhouette cards at the jaw and moustache edge.

**Brows.**
- 500–700 strands per side, 6–9 mm long, lying at 80° to the normal.
- Direction: up and out in the inner third, out in the middle, down and out at the tail.
- Height: 8 mm at the head, 4 mm at the tail. Straight, following the brow-shelf angle.
- Skin under the brow 10 % darker.
- **No scar gap** (override above).
- Game: 12 shells plus 20 edge cards per brow.

**Lashes.**
- Upper: 150–180 per eye, 8–10 mm, curving up.
- Lower: 70–90 per eye, 5–6 mm.
- A 0.3 mm dark lash line painted at the lid margin.
- Game: two strips per eye, ≤ 64 tris.

**Failure modes:** a flat black patch (needs per-strand variance σ ≥ 0.3 plus grey); a hard cheek line; hair floating off the skin.

### Track D: suit

**Why it reads grey.** The albedo isn't the problem: under a big soft key with floor bounce, 0.028 renders mid-grey. Three things fix it: a fuzz lobe, a detail weave, and a stage where the suit is the darkest thing in frame. Target a shirt-to-wool luminance ratio of at least 20 : 1 in every hero frame.

**Materials.**
- **Wool:**
  - Albedo 0.025, roughness 0.62 ± 0.08 fibre noise.
  - Sheen weight 0.35, sheen roughness 0.4, tint (0.9, 0.9, 1.0).
  - Detail normal: a 2/2 twill at 0.5 mm period from a Poly Haven CC0 fabric tile, tiled at 10 cm, strength 0.4, blended over the script-drawn seam map.
- **Shirt:** albedo 0.72, roughness 0.5, sheen 0.2.
- **Tie:** silk, albedo 0.015, roughness 0.35, anisotropy 0.5 along the warp, sheen 0.1. A true dimple 5 mm deep.
- **Shoe:**
  - Leather albedo 0.012. Roughness: cap 0.18, quarters 0.28. Coat 0.6 at roughness 0.08.
  - Add the tongue, heel pull, welt stitch and sole edge.

**Fit.**
- Shoulder: 2–3° drop from the neck point. The roped sleeve head rises 6 mm, then falls.
- Sleeves pitched 10° forward, with a baked wrinkle at the elbow crook.
- Lapel: roll height 16 mm with a bevel so it catches a highlight. Edge stitch 6 mm in.
- Quarters closed 10 mm.
- Collar stand: 35 mm visible from behind.
- **Trousers rebuilt on the body**, like the jacket: flat front, natural rise, the crease as a 1.5 mm ridge, 19 cm leg opening, quarter break.

**The biggest single upgrade: baked wrinkles.**
- Run a Blender cloth sim on the lofted garments: 10–20 settle frames, pressure 0, high stiffness.
- Bake the delta to a wrinkle normal map and a 1–2 mm displacement at the elbow crook, the armpit, the lower back under the waistcoat, the trouser crotch, the back of the knee, and the break at the shoe.
- Amplitude 1.5–3 mm, wavelength 20–40 mm.
- Nothing else makes cloth read as cloth.

**Failure modes:** a grey suit; block shoulders and tube sleeves; plastic shoes.

### Track E: Cycles hero stage

See §5 for the recipe. Deliver the rig as a script every track can call on day one.

### Track F: deformation and pose

**Hero pose:**
- Weight on the left leg (contrapposto) with a 4° pelvis tilt.
- Shoulders 5° back.
- Head turned 10° toward the camera and tilted 3°.
- Right hand relaxed: MCP 20°, PIP 35°, DIP 15°.
- Left hand buttoning the jacket or at the cuff.

**Second pose:** a high-ready pistol stance, elbows in.

**Requirements:**
- `deltoid_helper` at 50 % of arm raise.
- An elbow corrective for the sleeve.
- A 3-bone finger falloff.
- No collar intersection at a 30° head turn.
- Per-pose jacket correctives from a short cloth settle, for the renders only.

**Failure modes:** candy-wrapper forearms; the collar through the neck; the skirt riding the thigh.

## 3. The face: original, weathered, believable

Age 44–46. Build it from numbers, seeded, with mirroring off.

**Age markers:**
- Temples receding 8–10 mm.
- Two broken forehead lines.
- A glabellar frown line on the **left only**, 8 mm long and 0.3 mm deep.
- Crow's feet, with the left set longer.
- Tear trough and soft under-eye bags.
- The nasolabial fold as above, plus a faint marionette crease of 0.5 mm.
- Hooded upper lids.
- 5–8 % grey in the beard.

**Asymmetry (all intentional, all small):**
- Left brow 1.5 mm higher.
- Nose dorsum deviated 1.5 mm to the character's right at the bridge, with a 2 mm hump (within the 2.5 mm guard), as from an old break.
- Left mouth corner 1 mm lower.
- Left eye aperture 0.5 mm narrower.
- Left ear 1 mm lower; the tops of both ears protrude 3 mm.
- ~~Brow scar, cheek nick~~ (removed: user ruling, no scars).
- One 1.5 mm mole, 20 mm below the right outer eye corner.

**Proportions:**
- Eye spacing 0.46 × bizygomatic.
- Mouth 0.36 × bizygomatic.
- Upper lip 6 mm, lower lip 9 mm, philtrum 14 mm.
- Gonial angle 118°.
- Chin 38 mm wide.
- Alar base 0.27 × bizygomatic.
- Resting expression: stern, mouth corners 1 mm down, lids heavy.

**Skin story:** indoor-pale with no tan line; broken capillaries on the alar; ears and nose reddened by cold; dark circles; wind-dried lips with vertical creases.

**Guardrails:**
- No reference photos, no names. Every feature lives in the config with its seed.
- All asymmetries come from a single seed, so they can be re-rolled if the human gate ("does this look like a specific real person?") says yes.
- If a re-roll is needed, change the nose and mouth parameters first: they carry more identity than the eyes.

## 4. Painterly realism: where it goes

**Applies:**
- Environment and set textures: Kuwahara r 3–5 px at 2k, flat value blocks.
- Suit and shoe albedo: Kuwahara r 1–2. Keep the normal maps clean.
- Hair-card albedo for the game: lock blocks with a 2-tone ramp.
- The grade (§5).
- Ink lines, in the game only: 1.2 px, colour #101018, on the silhouette and on creases ≥ 60°, never inside the face.

**Must not apply:**
- Skin albedo beyond the existing `plane_paint` of 0.06.
- Skin normal, roughness or displacement.
- Eyes and lips.
- The Cycles hair and beard.
- Any posterised shading on skin.

The face is where realism lives; the paint goes around it and into the light.

## 5. Hero shot list and lighting recipe

**Base rig**, with strengths as ratios of the key:
- **Key:** amber 3,000 K area light, 0.8 × 0.8 m, 1.5 m away, 40° camera-left and 25° up. 1.0.
- **Magenta rim:** colour (1.0, 0.18, 0.55), a vertical strip 0.3 × 1.5 m, behind-right. 0.7.
- **Teal kicker:** colour (0.1, 0.8, 0.9), behind-left. 0.4.
- **Fill:** cool bounce. 0.08.
- **Eye light:** a 10 cm area light at the camera. 0.12.

**Haze:** volume density 0.03/m, anisotropy 0.6.

**Wet set:**
- Poly Haven CC0 asphalt with a puddle mask; roughness 0.05 in the puddles.
- Rain cards.
- In close-ups, 30–40 water beads of 0.5–1.5 mm on each shoulder.
- Emissive signs show our own invented brands.

**Grade:** AgX base, contrast +15 %, black point 0.02, shadows toward teal, highlights toward amber, halation 1.5 %, grain 2 %, vignette −0.3 EV.

| # | Shot | Lens / framing | Pose | Light |
|---|---|---|---|---|
| 1 | Rain portrait | 85 mm, head and shoulders, ¾ left, f/2 focused on the near eye | Eyes to camera, stern | Base rig, drizzle, wet hair tips |
| 2 | Under the sign | 50 mm, full body, camera at 1.1 m | Buttoning the jacket, weight on the right | Magenta sign 1.2 × 0.4 m above-right as key; teal sign across the street 0.5; sodium lamp 0.3; heavy rain, puddles |
| 3 | Profile, teal | 100 mm, bust profile | Still, chin 3° down | Teal rim 0.9 from behind, amber key 0.3. The silhouette shot |
| 4 | The draw | 35 mm, ¾ full body, camera at 1.2 m | High-ready stance | Hard 4,300 K source 0.2 m off the ground, low right (a headlight), 1.0; magenta top 0.4 |
| 5 | Hands and cuff | 100 mm, hands at the cuff, with the shoe and trouser break in frame | Adjusting the cuff | Base rig, key 0.8 |
| 6 | Eye close-up | 135 mm at 0.4 m, eyes and brow | Gaze 5° off camera | Soft key 1.0, eye light 0.3. Shows the iris and lashes |
| 7 | **Honesty turntable** | 50 mm, 8 frames at 45° steps, 18 % grey backdrop | A-pose and hero pose | 5,600 K three-point: key 1.0 at 45°/30°, fill 0.3, rim 0.5. No haze, grade or DOF. Plus clay and normal passes |

## 6. Review rubric

Score each area 1–5. **4 passes**; 3 means "improved, not done".

| Area | 4/5 passes when |
|---|---|
| Face form | Planes read under the key, but no facet edge is visible at 1024². Three asymmetries are visible in the front view. Lids are hooded. The profile shows the hump and the deviation. |
| Skin | Red bleed is visible at the nose and ear terminators. Roughness varies across the T-zone. Pores resolve at 2–3 px in the close-up. No single-tone region is larger than the cheek. |
| Eyes | A lid-contact shadow is present. The catchlight is one hard point plus a soft one. The iris reads dark brown with a limbal ring. The cornea refracts at the ¾ view. |
| Hair | No continuous highlight streak. The tips feather. The silhouette breaks ≥ 30 mm beyond the cap. The hairline shows skin through a density ramp. Cards and strands match in mass and value. |
| Beard and brows | Strand direction is visible, with ≥ 3 values in the mass. The cheek line fades over ≥ 10 mm. Grey shows at the chin. The brows are connected to the skin and shadowed. |
| Suit fit | The shoulder drop and roped sleeve head are visible. The sleeves are pitched. Elbow and armpit wrinkles are present. The trousers break once. Hem and button stance are within spec. |
| Suit materials | Shirt-to-wool luminance is ≥ 20 : 1. A sheen rim shows under the magenta rim light. The twill resolves in the close-up, but not as hatching. |
| Shoes | The cap highlight is sharper than the quarter's. The tongue and welt are present. No flat sole cap. |
| Pose and deformation | Contrapposto. Fingers curled. No intersections at the collar, armpit or cuff. The skirt doesn't ride up. |
| Lighting and grade | The three light colours are separable on the hair edge. Blacks sit at 0.02, not 0. The eyes have a catchlight. Haze reads behind the face, not in front of it. |
| **AAA read** | A senior artist looking at shot 1 at full resolution finds no "that's CG" tell in the first 3 seconds, and the turntable doesn't contradict it. |

Anything that scores 4 under the hero light but ≤ 2 on the turntable is rejected as a lighting trick.

## 7. Sequencing risks

- **Track A's forms freeze first.** Hair, beard, brows, lashes and the collar all anchor on the skin surface. B and C groom on a frozen head; any later lattice change re-rolls their roots. Freeze the forms by the first checkpoint. Skin and eye material work can continue after the freeze.
- **E delivers the rig on day one**, as a script, before any stage dressing. Every track's evidence renders use it; otherwise six agents build six lights.
- **C goes before B at the face.** The beard decides where the hair's front falls may land.
- **B's cards are baked after the strand groom is frozen**, not in parallel with it.
- **D's trouser rebuild and wrinkle bake don't depend on the head**, so they start immediately. The collar depends on A's neck only if the neck changes; agree now that it doesn't.
- **F goes last**, on the integrated character. F's cloth-settle correctives depend on D's final garments.
- **Integration order:** A → C → B → D → F → E final renders. Run the turntable (shot 7) at every merge, not only at the end.
