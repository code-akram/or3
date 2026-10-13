# m1 v2 Track A: head forms, skin and eyes

Track A report (BRIEF.md). Branch: `worktree-agent-ae8e46d215f90ce05`.

Merged commits:
- 00a177d, forms freeze (merged 4881440).
- b4911f6, forms v2 (merged 8fa40c6).
- 1431541, skin v2 (merged 3315819).

Also merged: 55723d9 (under-eye forms parameters) and 931c0d8 (pores as relief, micro relief, eye pass; merged 291b2b5).

On the branch now: the skin-direction pass (`bench/m1/v2/skin-direction.md`, Track A list) and the orchestrator's skin20 and skin21 reviews, section 8. It covers chromatic albedo, hero mid-band relief, a softer cross-hatch, hero vellus, the pore and micro-relief bump layer, the under-eye and glabella fixes, and the pass-criteria numbers. Where section 8 differs from sections 2 and 5, section 8 is current.

## 1. What changed

### Two paths: game and hero

The game GLB and the Cycles hero renders share one bake but get different materials.

- **Game (GLB).**
  - One Principled per slot.
  - Head: 4k albedo (sRGB), 4k normal and 2k ORM. Hands use the same scheme.
  - Built by `skin_tex.build` in the `head.refine` step. These maps are all the glTF exporter sees.
- **Hero (Cycles).** `head.hero` is a new build step that runs after `export_glb`, so none of this reaches the GLB. It:
  - swaps the body skin slots for `skin_head_hero` and `skin_hands_hero`;
  - adds the hero eye parts to the `hero_only` collection;
  - hides the game eye in renders;
  - retunes the teeth and tongue.

  The kept `character.blend` carries all of this, and `blender/hero/rig.py` renders it under both rigs.

### Files

| File | Change |
|---|---|
| `blender/character/head_forms.py` (new, frozen) | Soft-tissue forms stage, run before any proxy is fitted:<br>- malar pad, tear trough and lid bag;<br>- nasolabial fold with cheek overhang;<br>- marionette, mentalis and labiomental forms;<br>- lids rotated about the eyeball, so the upper lid covers about 2–2.5 mm of an 11.7 mm iris;<br>- seeded asymmetry;<br>- forms v2: a soft brow shelf of +1.5 mm over a 0.8 mm upper-orbit hollow. |
| `blender/character/skin_synth.py` (new) | All map synthesis, in numpy on the baked surface data:<br>- face frame and regions; region pores;<br>- lines: forehead, two soft glabellar furrows, crow's feet, under-eye, nasolabial, lip creases and neck;<br>- lid and under-eye crepe;<br>- albedo zones: forehead yellow, mid-face red, a cool darker beard zone, violet-brown under-eye, moderate socket, lid and roof shading;<br>- temple veins, alar capillaries, stubble, freckles and blemishes (no moles, no scars);<br>- mouth-corner lift;<br>- roughness map;<br>- hero masks (pores, oil, fuzz, micro). |
| `blender/character/skin_tex.py` (rewritten) | Bake, plus the pose-stable rest-position attribute `hero_rest`. 3D noises (Voronoi pore fields, anisotropic noise). Game images. The hero material and the hero step. |
| `blender/character/eyes_hq.py` (rewritten) | Eyeball with a bulge profile.<br>Lid maps ray-cast against the body (coverage, aperture flood fill, canthi).<br>Iris: fibres, crypts, collarette and limbal ring.<br>Sclera: warm, with meandering sectored vessels, a limbal halo and darker corners.<br>Lid occlusion baked into the game albedo and ORM.<br>Hero eye: a recessed conical iris, a separate refractive cornea (IOR 1.376, shadow-transparent), a lower tear meniscus (IOR 1.336) and a caruncle at the inner canthus. |
| `blender/character/skin_vellus.py` (new) | Hero-only vellus: about 20k strands, 0.8–2 mm long, radius 0.008 mm, melanin 0.1. Roots follow the fuzz mask and sit on the hero displacement. Built with C's `beard_groom` helpers into `hero_only`, bound to the head bone (section 8). |
| `blender/character/head.py` | The `hero()` step (skin, vellus, eyes, mouth). The mouth hero darkens the teeth to 0.78 and the tongue to 0.85, with roughness and SSS, so the teeth no longer glow. |
| `bench/m1/variants/direction.json` | Forms tissue keys. Skin base `#b8927b`. Approved under-eye change: lid_bag_mm 0.8 → 0.3, tear_trough_mm 1.2 → 0.9. |
| `bench/m1/head_closeups.py` | Studio close-ups (face, eye, pores, mouth, cheek, forehead) from a kept `.blend`. Track tool. |
| `provenance/mesh.jsonl` | One record: Blender Studio Human Base Meshes 1.4.1 (CC0). It was evaluated as a forms reference and **rejected**; nothing from it is shipped (section 6). |

**Shared-file edits:** one line in `blender/build_character.py`, `b.step("head_hero", head.hero)`, right after `export_glb`. The coordinator approved it.

## 2. Hero skin material (Cycles)

- **Principled BSDF**, Random Walk (Skin) subsurface:
  - weight 1.0; radius (1.0, 0.22, 0.10) × 3.4 mm (was × 2.5 mm before section 8);
  - anisotropy 0.8; IOR 1.4.
- **Specular:** IOR level 0.5, IOR 1.4.
- **Roughness map.** Mean 0.485; face mean 0.51.

  | Area | Roughness |
  |---|---|
  | T-zone | 0.37, smooth (no patches; section 8) |
  | Cheeks | ~0.47–0.50 |
  | Beard | 0.58 |
  | Lips | 0.45, with vertical crease breakup |
  | Ears | 0.48 |
  | Under-eye | +0.10 |
  | Crepe | +0.08 |
  | Micro scale (hero) | plateaus −0.03, furrow valleys +0.10, pore openings +0.16 |
  | Wet lid margin | none on the skin since section 8.7; the hero tear meniscus carries the wet line |

- **Coat:** 0.02 + 0.10 × the oil mask, roughness 0.28. The oil mask covers the T-zone and some cheek, not the under-eye, and varies smoothly (× 0.8–1.2 on a ~2 cm noise). Both the base and the coat follow the micro bump.
- **Sheen:** 0.1 × the fuzz mask.
- **Pores** are three 3D Voronoi pit fields evaluated on `hero_rest`, so they don't swim when the character is posed. They match the game bake one-to-one and are weighted per region.
  - **Densities.** The surface density of a 3D field sliced by the skin is scale³ × 2r, so the scales are set from these targets:

    | Region | Target density | Pit radius |
    |---|---|---|
    | Nose | 60/cm² | 0.20 mm |
    | Cheek | 35/cm² | 0.17 mm |
    | Forehead | 20/cm² | 0.09 mm |

  - **Depth:** 0.04–0.07 mm × 1.6.
  - **Openings:** at most 2 % darker; otherwise relief only.
  - **Albedo:** the baked cavity darkening is 3 %, down from 30 %. Pores and lines are relief, not colour.
- **Micro relief** (hero only). The skin-tension cross-hatch:
  - three distorted wave fields: lines at +38° (weight 1.0), −42° (0.9) and 85° (0.5);
  - 0.5 mm spacing, narrow valleys, 0.025 mm deep (0.035 before section 8), broken in ~1.4 mm patches (break 0.5);
  - a 0.05 mm, 0.004 mm grain.

  The orchestrator asked for a 0.15–0.3 mm secondary net. That is under a pixel even in the 135 mm close-up (0.12–0.15 mm/px), so it only averages into roughness. The 0.5 mm primary lines are what resolve; the grain stands in for the rest.
- **Displacement**, in world space and in mm: baked lines, crepe and (section 8) the mid band.
- **Micro bump** (section 8.7): the pores (with a shallow funnel round each), the cross-hatch and the grain go to a Bump node on the Principled `Normal` and `Coat Normal`, at 1.5 × their physical depth on the head (1.0 and no funnel on the hands). It is evaluated per shading sample on `hero_rest`, so it is limited by neither the texel nor the dicing.
- **Dicing:** an adaptive Subdivision modifier (`hero_dice`) in PIXEL space at 1 px; scene dicing rate 1, max subdivisions 10.
- **Albedo face mean:** sRGB (0.66, 0.52, 0.45). Direction target: (0.70, 0.55, 0.46).

## 3. Evidence

Final build `data/build/lookdev/20261012T233759Z-A-skin11`:
- 124,543 tris, 81 bones, 4 weights per vertex, 0 glTF errors;
- spec guards 0 out; read40 eye band 63 %.

After the rebase onto main 51a0e8b (D suit v3, B hair round 3), `…-A-skin11r` stays green: 121,351 tris, 83 bones, 4 weights per vertex, 0 glTF errors, spec 0 out, read40 63 %.

**Raking specular test** (orchestrator item 4).
- Setup: one 4 cm 5600 K light at 75° from the camera and 12° up, a 3 % fill, 135 mm, DOF off, 100 % crops. Script: `~/.cache/or3-trackA/rake.py`.
- Crops, before (skin9) next to after (skin10; skin11 changes only the under-eye lines):
  - `data/build/trackA/rake/rake_cmp_cheek.png`
  - `data/build/trackA/rake/rake_cmp_forehead.png`
- Overview: `rake/rake_skin10_face.png`.
- Lab steps: `rake/rake_micro{1..4}_*.png`.

**Eye close-up, hero rig, 100 %, DOF off.**
- `trackA/skin11/eye_nodof.png`, against `trackA/skin10/eye_nodof.png`.

**Studio close-ups.**
- `…-A-skin10/hc/studio_{eye_macro,pores,cheek,mouth}.png`, against `…-A-skin9/hc/`.

**Skin9 renders.** In `data/build/trackA/final/` (the skin9 build) and `…-A-skin9/hc/`. Each rig render is one Blender job at `-t 3`; the close shots are 1920×1080 at 100 %. For the pores and eyes, the skin10/11 crops above supersede these.

| Distance | Studio / turntable | Hero (neon) rig |
|---|---|---|
| Full body | `final/tt_body/turntable_tt0.png` (1024 px tall) | — |
| Bust | `final/tt_close/turntable_portrait.png` | `final/hero/hero_portrait.png` |
| Close-up | `final/tt_close/turntable_az-30_el3_lens135_aimeyes_frame0.16.png`, `…-A-skin9/hc/studio_{eye_macro,pores,cheek,forehead,mouth}.png` | `final/eye_nodof.png` (eye cam, DOF off, full frame), `final/eye_focus.png` (crop, f/2.8 focused on the cornea) |

**Before:**
- v1 sign-off: `data/build/m1-signoff/closeup.png`.
- First v2 hero pass: `data/build/trackA/skin1/hero_eye.png`.
- Pre-fix hero eye: `data/build/trackA/skin6/hero_eye.png` (preview, DOF on the eyeball centre).

**Pore A/B:** `data/build/trackA/ab_eye/eye_{base,focus,nodof,raw}.png` (A-final, 100 % crop).

## 4. Iteration log

| Run | What changed | Verdict |
|---|---|---|
| `20261012T190247Z-A-dev0` | Baseline: the v1 head with the direction config | Faceted mannequin with waxy one-colour skin. read40 77 %. |
| `…-A-forms1` → `…-A-forms4` | Forms stage: soft tissue; softer planes (blends 0.35–0.6, dense re-planarise off); lids; asymmetry; real iris size; age 0.66 | The planes became hints, the lids are believable and the asymmetry reads. Frozen (00a177d). read40 fell to 64 % because the softer brow lost shadow. |
| `…-A-skin1` | First generated skin v2 and the first hero pass | Problems: the caruncle sat as a bead on the upper lid; the lines were too hard; the sclera looked like porcelain; no pores showed; read40 60 %. |
| `…-A-skin2`, `…-A-skin3` | Socket, lid and roof albedo shading; aperture flood fill; caruncle placed at the canthus | Caruncle fixed. read40 62 %. The dark socket was drifting into an albedo hack, so I reverted it to moderate values (coordinator: keep the skin honest). |
| `…-A-skin4` | Lips: colour, creases, and a corner lift for the sour mouth. Mouth hero for the teeth. | Teeth no longer glow. Pores still invisible; under-eye specular smear. |
| `…-A-formsv2` | Brow shelf +1.5 mm over a 0.8 mm upper-orbit hollow | Soft brow, no shelf. Checked in clay on the hero bust and the turntable. read40 64 %. Merged 8fa40c6. |
| `trackA/lab_smear` | Lab: coat off, sheen off, no subdivision | The smear is mostly geometric: the lid-bag ridge under a lobe at roughness 0.5. The coat and sheen add only a little. |
| `…-A-skin5` | Pore scales from the slice-density formula. Lips `#955c53`. Sclera `#c4b4a6`. | Under the SSS, sub-mm displacement barely shades. Pores showed only as albedo dots. The sclera vessels were straight hairlines. |
| `trackA/lab_micro` | Lab on skin5: micro relief 0.02 mm, pore floor 0.8, pores ×1.5 | The even network looked like reptile skin. Deeper pits alone didn't change the read. |
| `…-A-skin6` | Lid and under-eye crepe. Micro relief up to the lid margin, 0.014 mm. Pores ×1.3; cheek pore floor 0.6. No coat oil under the eye. Meandering, sectored sclera vessels. | The smear softened. Sclera vessels now read. The coordinator flagged: (1) no pores in the 135 mm close-up; (2) orange under the hero key; (3) puffy under-eye; (4) no forehead lines. |
| `…-A-skin7` / `…-A-final` | Under-eye roughness +0.10; muted lips `#8e5f56`; forehead 0.20 mm; flatter caruncle; first 4k build; rebased on F | At 4k the pores and crepe resolve in the studio close-ups. Merged as 1431541. |
| `trackA/ab_eye` | A/B of the eye cam at 100 % | Diagnosis below: depth of field, not the skin, was hiding the pores. |
| `…-A-skin8` | Pore openings darker and rougher (same Voronoi). Coat capped at 0.15 with roughness 0.28. Forehead lines 0.30 mm, as a wide valley plus a narrow core. Lid bag 0.3 / trough 0.9. | Pores resolve at 2–3 px with DOF off or focus on the cornea. The under-eye is softer. The forehead lines read but looked like wavy worms. |
| `…-A-skin9` | Forehead lines less wavy and more continuous. pore_dark 0.30. | The orchestrator found it airbrushed plastic with dark freckle specks. The raking test agreed: the highlights were smooth sheens with pepper dots. |
| `trackA/rake` micro1–4 | Lab on skin9: the cross-hatch at 0.25 mm, then at 0.6 mm at 0.02 and 0.05 mm, then three directions with more distortion and patches | At 0.25 mm the net is under a pixel and invisible. At 0.05 mm it looks woven, like fabric. micro4 (0.55 mm, 0.03 mm, three directions) breaks the highlight without a pattern. |
| `…-A-skin10` | Pores as relief: albedo cavity 3 %, pore_dark 0.02, pores ×1.6. The cross-hatch micro relief (0.5 mm, 0.035 mm, three directions) plus grain. Micro roughness. Freckles fainter. Wet lid ring narrowed to the margin. Iris: stronger fibres, a lighter collarette, limbal ring 0.55. Sclera darker, with a warm-pink falloff at the corners. Meniscus 0.15 mm. | The pepper dots are gone. Under the raking light the highlights break into a stipple and fine diagonal texture. The iris has a visible collarette and fibres. The under-eye still has a bright streak along the lower edge of the lid bag. |
| `…-A-skin11` | Under-eye lines shallower, with no raised shoulders | The streak barely changes. It is the convex lower edge of the bag form catching the key, so materials can't remove it (see verdicts). |

### Why the pores did not show in the eye close-up (`trackA/ab_eye`)

All four variants are 100 % crops of the same frame:
- `base` is the rig default;
- `focus` moves the focus 12 mm forward to the cornea;
- `nodof` turns depth of field off;
- `raw` is DOF off, no denoise, 256 spp.

1. **Depth of field (main cause).** rig.py's `eye` cam shoots 135 mm at f/2.8 from 0.73 m, which gives about 5 mm of depth of field. `camera()` focuses on the eyeball *centre*, about 12 mm behind the cornea. So the lashes, lids, cheek, nose and forehead were all out of focus.
   - With focus on the cornea, the lashes, lid margin and the cheek under the eye go sharp, and the pores show.
   - With DOF off, the nose and cheek pores resolve over the whole face.
   - Passed to Track E: focus on the eye centre + 12 mm toward the camera, and f/4–5.6.
2. **Resolution.** `preview` renders at 50 %, which puts 0.27–0.35 mm pores at about 1 px. Evidence is now at 100 %.
3. **OIDN.** Compared with `raw`, the denoiser smooths the sub-pore micro grain but keeps the pore dots.
4. **SSS.** The 2.5 mm red scatter washes out the diffuse shading of sub-mm pits, physically correctly. That is why the openings also get albedo and roughness. In real skin the pores read through shadowed openings and specular breakup, not through diffuse shading.
5. **Bump chain.** Verified wired: displacement in BOTH mode, `hero_rest` present (26,324 points), adaptive dicing at 1 px.

**Orange under the hero key.** It comes from the rig, not the skin.
- Albedo: on target.
- Turntable: the forehead reads a neutral sRGB (0.79, 0.69, 0.63).
- Hero key: the forehead reads (0.78, 0.47, 0.22), and the white shirt (0.69, 0.53, 0.40).

The 3000 K key is rendered at a daylight white balance, plus the Medium High Contrast look. I passed this to Track E: white balance on the hero rig.

**read40.** It sits at 62 %. The coordinator accepted about 64–66 % for v2 and asked me not to chase it with albedo hacks. The 0.75 bar was calibrated on v1 under a low key and will be re-calibrated under the game light.

## 5. Verdicts (judged at three distances under both rigs)

| Defect | Verdict | What still reads as CG |
|---|---|---|
| Faceted mannequin forms | **Fixed** (frozen, 00a177d, 8fa40c6, 55723d9) | Brow, cheek and jaw planes now read as soft tissue. Lips are still slightly full and pillowy (form, frozen). |
| Waxy one-colour skin | **Improved** | Zones, mottling, capillaries and veins read under the turntable. Mid-distance colour variation is still subtle: at bust distance the face is fairly even. |
| SSS / plastic | **Fixed** in Cycles | Random-walk skin at 2.5 mm red, no wax. EEVEE and the game have no SSS (game path unchanged). |
| Pores and micro detail | **Improved** | Pores are now relief, not colour. Under the raking light the nose and forehead highlights break into a stipple and fine cross-hatch at 100 %. Still CG: under the big soft hero key, at portrait distance, the skin reads fairly smooth. At 2 cm macro the cross-hatch is a little regular (woven). In the rig's current eye shot (DOF on the eye centre) all of it stays blurred until E's focus fix lands. |
| Roughness / specular | **Improved** | Roughness map plus micro variation (plateaus glossier; valleys and pores rougher); the coat capped at 0.15. The nose dorsum highlight is still a fairly continuous streak. |
| Under-eye smear and bulge | **Improved, not fixed** | The 0.3/0.9 forms, crepe, no oil, roughness +0.10, a wet ring only at the margin, and shallow under-eye lines with no shoulders took it from a wet, bright rim to a softer bag. It still leaves one bright streak along the bag's lower edge under the hero key (`trackA/skin11/eye_nodof.png`). This is the form's convex edge. Materials can't remove it without faking the roughness. The honest fix is softening that edge in head_forms, which needs your call. |
| Forehead lines | **Fixed** | Two long, broken lines read at bust and close-up distances. Crow's feet are subtle (0.15 mm). |
| Age detail and asymmetry | **Improved** | One-sided frown, crow's feet longer on the left, seeded form asymmetry. No moles, no scars (coordinator rule). |
| Eyes | **Improved** | Done: iris depth and parallax; radial fibres; a lighter collarette; a darker limbal ring; refracting cornea; catchlight; tear meniscus (0.15 mm); caruncle; upper-lid occlusion; a warm sclera with a pink falloff at the corners and vessels. Still CG: under the hero grade (WB 4200) the sclera still reads light next to the orange skin. The caruncle is a smooth bulb. The lower waterline has no visible wet pink band. The lashes (C) are clumped. |
| Mouth and teeth | **Improved** | Muted rose-brown lips with vertical creases and a corner lift; the teeth no longer glow. The lips still read slightly inflated (form). The pale skin band between lip and beard is the beard edge (C's coverage) against black hair. |
| Orange under the hero key | **Not mine; handed to E** | The skin is neutral under the turntable. |
| read40 eye band | **Not fixed (accepted)** | 62 %, versus the accepted ~64–66 %. |

## 6. Provenance

- **Blender Studio Human Base Meshes 1.4.1 (CC0).** Downloaded to `data/vendor/human-base-meshes/` and inspected as untrusted data (renders in `data/build/trackA/hbm/`). It was rejected as a base: it has a different topology, and our MPFB rig and proxies depend on ours. Nothing from it is shipped. It is recorded in `provenance/mesh.jsonl` with status `rejected`; `provenance/audit.py` reports 0 errors.
- **Everything else is our own procedural work:** skin, eye and line synthesis, all generated from noise and the face frame. No photos, no scans, no real person's likeness.

## 7. Settings that deviate from direction §2 Track A

| Setting | Direction | Ours | Why |
|---|---|---|---|
| Cornea bulge | 2.5 mm over the iris plane | 1.3 mm over the eyeball sphere, about 3.8 mm over the 0.5 mm-recessed iris plane | The sphere cap already gives about 2 mm at the limbus. |
| Tear meniscus | 0.3 mm | A 0.24 mm tube | — |
| Coat | 0.15 flat | 0.02 + 0.10 × the smooth oil mask (8.7); roughness 0.28 | Less coat away from the oily zones; a thin film, no islands. |
| Forehead lines | 0.2 mm | 0.30 mm with a 1.2 mm valley | So they survive the SSS. |

## 8. Skin-direction pass (skin13–skin24)

**Sources.**
- Binding: `bench/m1/v2/skin-direction.md`, the Track A list.
- Then the orchestrator's reviews:
  - skin16: halve the broad haemoglobin; take a* from fine-scale variation; break up the forehead spec;
  - skin20: the fine red reads as a lace of flecks, the sebum islands as wet camouflage, and the pores still don't read (a micro-detail normal layer);
  - skin21: wet crescents under the eyes, a slit-like glabella line, and confirm the pores under the hero rig.
- Sections 8.1–8.6 describe skin13–skin20; section 8.7 is the skin21–skin24 pass and supersedes them where they differ.
- Final measured build: `data/build/lookdev/20261013T042837Z-A-skin24`, on main 416132c (section 8.7).

### 8.1 What changed

**Albedo** (`skin_synth`, game and hero maps):
- **Broad haemoglobin**:
  - noise 90/m, detail 2;
  - soft threshold 0.55 ± 0.20, zero mean over the skin;
  - weight 0.18 on the cheeks, nose, apples, centre forehead and neck, 0.045 elsewhere (half of skin16);
  - acts as R +0.7, G −0.83, B −1.0 per unit.
- **Fine redness** (new bake `noiseG`), as of skin20 (changed in 8.7):
  - noise 150/m and 300/m, i.e. features of about 3–7 mm;
  - normalised to unit std, then one-sided (softplus), so it gives red flecks on an even ground rather than a red/green speckle;
  - weight 0.060 on the cheeks, nose, alar, ears, chin (×0.6) and neck (×0.5); 0.030 elsewhere; 0 under the eye;
  - per unit: R +1.6, G −1.0, B −1.1, which shifts luminance by only about −1 %.
- **Melanin**: noise 30/m, ±6 % value; the darker side is tinted (1.02, 1.00, 0.95).
- **Zone hues** now differ:

  | Zone | Tint |
  |---|---|
  | Nose tip and alar | (1.20, 0.89, 0.92) |
  | Apples | (1.06, 0.95, 0.92) |
  | Forehead | (1.03, 1.02, 0.91) |

- **AO and plane paint**:
  - `ao_in_albedo` 0.22 → 0.10;
  - the hero albedo (`skin_head_hero_albedo`) has no plane paint (hero `plane_paint` 0); the game keeps 0.06.

**Mid-band relief** (`hgt_hero`, so in the hero displacement):
- It is also added to `hgt_game`, which bakes it into the game 4k normal (item 6).
- After it, the game spec guards are still 0 out, with 0 glTF errors.

| Feature | Setting |
|---|---|
| Lumps | Noise 120/m, detail 1. 0.25 mm on the cheeks; 0.22 mm on the forehead (direction 0.15); 0.30 mm under the eye; 0.10 mm elsewhere on the face. |
| Orange peel | Voronoi distance-to-edge at 350/m, stretched 1.5:1 along world x, distortion 1.5. Shaped as soft round domes, 0.05 mm (direction 0.07). |
| Line shoulders | +0.08 mm Gaussians 1.3 mm out from the forehead lines, frown and nasolabial (crow's feet ×0.6). |
| Nose and alar bumps | 0.6 mm Voronoi cells, 0.06 mm. |
| Lip ridges | 0.12 mm at 0.8 mm spacing (phase-warped), with 1.5 mm lateral bumps of 0.03 mm. |
| Under-eye edge | −0.15 mm along the bag's convex lower edge. No forms change, no lash re-groom. |
| Cross-hatch | `micro_mm` 0.025, `micro_break` 0.5. |

**Specular** (as of skin20; the sebum patches and coat islands are gone in 8.7):
- **Sebum patches**:
  - two noises (180/m and 450/m), renormalised, so the patches are 2–5 mm;
  - roughness ±0.20 over the T-zone, forehead, temples and (×0.6) cheeks;
  - the oil mask follows the same patches, so the coat (0.15 × oil, no base coat) sits in islands;
  - T-zone base roughness stays 0.40.
- **Pore openings**: +0.16 roughness.
- **SSS**: radius (1.0, 0.22, 0.10) × 3.4 mm, up from × 2.5 mm, for a redder terminator.

**Vellus** (`skin_vellus.py`, item 5):
- 19,949 strands, 0.8–2 mm long, radius 0.008 mm tapering to half, 4 points.
- Melanin 0.10 ± 0.03, redness 0.3.
- Roots follow the fuzz mask (cheeks, forehead, ears and neck; none in the beard, lips, eyes or scalp), peaking at about 89/cm².
- Each root sits on the hero height + 0.03 mm. The strands lie down toward the jaw and out.
- Uses C's `beard_groom.sample_roots`, `grow`, `make_curves`, `hair_material` and `bind` (head bone), in `hero_only`.
- It is sub-pixel at portrait distance. I can't see it in shot 1 or in the eye shot, so it is unverified visually.

### 8.2 How it is measured

**Script and boxes.**
- Script: `~/.cache/or3-trackA/measure.py` (numpy; the PNG goes through ImageMagick to a 16-bit PPM).
- Boxes:
  - shot 1: `~/.cache/or3-trackA/boxes_e_tz.json`;
  - turntable portrait: the script's built-in boxes.

**Shot 1.**
- Rendered with `bench/m1/hero.sh --shots portrait --pct 100 --paint 0 --no-turntable`. That is E's skin rig and grade, in the alley, at 64 spp plus OIDN, f/2 on the near eye.
- Baseline: E's reference `data/build/hero/20261013T000810Z-main5-skinrig/portrait.png`, which is my previously merged skin under the same rig.

**Metric definitions.**

| Metric | Definition |
|---|---|
| Specular | Pixels at or above the 95th luminance percentile in the box; 8-connected components; length = the longer side of each component's bounding box. |
| Mid band | Luminance minus a Gaussian blur with σ 7.5 px (half power at 40 px), as a std over the mean. a*: Gaussian σ 1.5 minus σ 5.6 px (an 8–30 px band). An 8 px border is dropped. |
| Hue | Lab h_ab of the box mean. |
| Saturation | C*/L*. |
| SSS shift | Lit cheek apple hue minus terminator hue; nose dorsum hue minus nostril-wing hue. |

**Where the measurement deviates from the doc.**
- **Chin.** It is under the beard, so I use the nose tip as the third zone.
- **Cheek crop.** It is 80×60 px (x 1068–1148, y 405–465), not 120×120: at this framing the nose shadow, the under-eye and the beard bound the clean cheek.
- **Forehead box.** It is the central T-zone (x 975–1095, y 215–300). On the full-width forehead box (x 925–1140), the top 5 % is the far temple's grazing highlight. That highlight is DOF-blurred at f/2 and runs 61 px on skin20 (65 px on main5).
- **Grain.** The grade adds about 2 % of 1-px grain, which puts about 1.15 % into the luminance std in quadrature.
- **Honesty render.** `rig.py --light turntable --cam portrait --no-dof --pct 100`: the same 85 mm framing in the rest pose.

### 8.3 Numbers

| Run | Forehead comps (all / ≥3 px) | Forehead max px | Nose comps | Nose max px | Lum high-pass % | a* 8–30 px | Hue Δ forehead–apple / forehead–nose / apple–nose (°) | Sat under-eye < cheek | Terminator Δhue (°) | Nostril Δhue (°) |
|---|---|---|---|---|---|---|---|---|---|---|
| E-main5 (before) | 6/3 | 34 | 3/1 | 57 | 2.38 | 0.39 | 8.9 / 10.4 / 1.5 | 0.554 < 0.585 | 5.3 | 13.9 |
| E-skin16 | 10/4 | 37 | 3/2 | 41 | 2.29 | 1.11 | 8.5 / 13.3 / 4.8 | 0.549 < 0.581 | 6.4 | 15.0 |
| E-skin17 | 10/4 | 27 | 2/2 | 42 | 2.29 | 1.23 | 7.6 / 13.7 / 6.1 | 0.569 < 0.575 | 7.1 | 15.4 |
| E-skin18 | 12/7 | 28 | 3/3 | 41 | 2.41 | 1.58 | 8.0 / 13.9 / 5.9 | 0.575 > 0.572 ✗ | 7.2 | 15.7 |
| **E-skin20 (final)** | **17/11** | **27** | **2/2** | **39** | **2.31** | **1.41** | **7.9 / 13.6 / 5.7** | **0.561 < 0.572** | **7.4** | **15.8** |
| TT-skin11 (before) | 12/3 | 42 | 34/11 | 25 | 1.23 | 0.31 | 4.9 / 6.9 / 2.0 | 0.272 < 0.362 | −3.5 | 0.9 |
| **TT-skin20** | **20/17** | **42** | **9/8** | **18** | **1.43** | **1.45** | **5.1 / 13.1 / 8.0** | **0.281 < 0.379** | **−3.0** | **1.5** |

**Against the pass criteria (skin20):**

| Criterion | Target | Result |
|---|---|---|
| Specular, forehead | ≥ 4 components, none > 25 px | **Pass** on components (17, 11 of them ≥ 3 px). **Miss** on length: 27 px, against 34 before. |
| Specular, nose | ≥ 3 components, none > 25 px | **Miss**: 2 components, 39 px (57 before). |
| Luminance high-pass | 1.5–3 % | **Pass**: 2.31 % (about 2.0 % without the grade's grain). |
| a* at 8–30 px | ≥ 1.5 | **Miss**: 1.41 (0.39 before). skin18 reached 1.58, but with a red/green speckle (see 8.4). |
| Hue | ≥ 5° between zones | **Pass**: 7.9 / 13.6 / 5.7° (forehead–apple, forehead–nose tip, apple–nose tip). |
| Under-eye saturation | Less than the cheek | **Pass**: 0.561 < 0.572 (narrow). |
| SSS terminator | ≥ 6° toward red | **Pass**: 7.4°. |
| SSS nostril wing | ≥ 6° toward red | **Pass**: 15.8°. |
| SSS ear rim | Transmits under the rim | **Not shown.** In shot 1 the ear is DOF-blurred and lit magenta. |
| Honesty | Turntable ≥ 60 % of shot 1 | a* 1.45 (103 %), luminance 1.43 % (62 %), forehead components 20 (> 100 %), nose 9 components at 18 px max, hue and under-eye hold. The terminator shift does not hold (−3°): the soft turntable key has no hard terminator. |

**Why the nose misses.** The dorsum streak is the reflection of E's 2 × 2 m blue fill. It is blue-white, and it does not change across ±0.2 roughness patches or when the coat moves into islands, which are exactly the behaviours of a reflection of a large source. Skin can't break it; a smaller fill would.

**Coordinator's 40×40 cheek baseline** (centre of the cheek apple, 100 %, DOF off where the rig allows):

| Render | sRGB | Luminance std |
|---|---|---|
| Turntable, skin11 | (0.704, 0.536, 0.452) | 0.0170 (3.0 %) |
| Old hero rig, skin11 | (0.641, 0.321, 0.119) | 0.0229 (6.1 %) |
| E's skin rig, main5 | (0.601, 0.380, 0.320) | 0.0325 (7.7 %) |
| E's skin rig, skin20 | (0.589, 0.378, 0.314) | 0.0338 (8.1 %) |
| Turntable, skin20 | (0.700, 0.526, 0.437) | 0.0161 (2.9 %) |

The 40×40 std includes the shading gradient; the high-pass numbers above remove it.

### 8.4 Evidence and verdicts

**Shot 1:**
- `data/build/hero/20261013T024900Z-A-skin20/portrait.png`.
- 2× face crop, before | after: `data/build/trackA/skin20/portrait_face_2x_main5_vs_skin20.png`.

**Eye shot** (135 mm, f/4, 100 %):
- `…/20261013T024900Z-A-skin20/eye.png`.
- Against main5 (`…/20261013T002954Z-main5-sheet/eye.png`): `trackA/skin20/eye_main5_vs_skin20.png`.

**Turntable:**
- `data/build/trackA/skin20/turntable_portrait.png`.
- Against skin11: `trackA/skin20/turntable_face_skin11_vs_skin20.png`.

**Rake** (same setup as before; E's camera change moved the crops): `data/build/trackA/rake/rake_skin20_{face,cheek,forehead}.png`.

**Intermediate runs:**
- skin13–19 portraits: `data/build/hero/*-A-skin1{3..9}`.
- Turntables: `data/build/trackA/skin1{3..7}`.

**Verdicts at three distances:**
- **Portrait distance (shot 1, 100 %).** The single hue and the smooth cheek and forehead are gone. The cheeks carry fine ruddy variation; the nose tip is redder than the apples, and the forehead yellower. The forehead highlight breaks into damp islands.
  - Pores still don't resolve individually. At 2.6 px/mm, a 0.2–0.35 mm pore is 0.5–0.9 px, and the 64-spp OIDN preview flattens what is left. They show only as highlight breakup.
  - Remaining tell: the nose streak (lighting).
- **135 mm eye shot.** The skin has lumps, peel, damp sebum islands and fine colour variation.
  - CG tell: at this scale the fine red layer reads as a pink lace or fleck pattern on the cheeks and forehead. skin16's broad blotches are gone, but this is the next thing to tone down.
  - If the orchestrator prefers the look over the a* number, the fix is one parameter: `hb_fine_strong` 0.06 → 0.035, as in skin17 (a* 1.23).
  - The under-eye still shows a thin bright line along the bag edge under the eye light.
- **Turntable.** The same fine red reads on the nose and cheeks, and the forehead looks damp. It is honest (the metrics hold), but it is a ruddier, oilier man than before.
- **Rake.** The lumps and peel read as real relief. Under a 75° raking light the peel cells still look slightly hammered, even after the switch to soft domes at 0.05 mm.

### 8.5 Rebase and guards

- **Rebased onto main 9ac04e9** (Track G hands), then onto **416132c** (D's suit round 4) for section 8.7, and finally onto **18cd96f** (F's round 2; no conflicts, F touches only `deform_*`). G's lines are kept as they are:
  - `hand_forms.apply(b)` in `head.refine`;
  - the `hand_detail` import and the `hand_detail.synth(...)` hook in `skin_tex.build`.
- **The only interface change on my side:** `Maps` takes an optional `nG` (default 0.5), and `build` bakes `noiseG`.
- **Post-rebase builds:**
  - `…-A-skin20r` (on 9ac04e9): 123,139 tris, 83 bones, 4 weights per vertex, 0 glTF errors, spec 0 out, read40 58 %;
  - `20261013T050942Z-A-skin25` (on 416132c, final): 126,872 tris (D's undecimated shirt), 83 bones, 4 weights per vertex, 0 glTF errors, spec 0 out, read40 58 %.
  - `20261013T060205Z-A-skin25r` (the committed tree, rebased onto 18cd96f, F's round 2): the same, with 126,872 tris, 83 bones, 4 weights per vertex, 0 glTF errors, spec 0 out, read40 58 %.
- **Hair export, not mine:** two of the six skin2x builds on 416132c (skin23c, skin24) exported 84 joints. The extra one is the glTF exporter's `neutral_bone`, which it adds because 135 `Human.hair_export` vertices came out unweighted. The other builds (skin22, skin23, skin23b, skin25) have 83, with no hair-related change between them, so this looks nondeterministic in the hair build. Passed to the coordinator.
- **read40** went from 63 % to 58 %. Cause: `ao_in_albedo` 0.22 → 0.10, as skin-direction asked. No albedo hacks.

### 8.6 Deviations from skin-direction.md (Track A)

| Item | Direction | Ours | Why |
|---|---|---|---|
| Haemoglobin | G and B only; 0.12 strong, 0.04 weak | Broad layer R +0.7, G −0.83, B −1.0 at 0.18 / 0.045, zero mean, soft threshold. Plus a fine layer (3–7 mm) at 0.060 / 0.030. | With G and B only at 0.12, a* stayed at about 0.5. Raising it far enough to reach 1.5 darkened the blotches into dirt and pushed the luminance std over 3 %. The R lift keeps them reading as colour. The orchestrator then asked for the energy at fine scale. |
| Forehead lumps | 0.15 mm | 0.22 mm | Coordinator: the forehead was still smooth between the features. |
| Orange peel | F2−F1, 0.07 mm | Distance-to-edge as soft round domes, 0.05 mm | At 0.07 mm with the sharp profile, the 135 mm and rake shots looked like crackle or crumpled foil. |
| Orange-peel anisotropy | Along the Langer lines | 1.5:1 along world x (left–right) | On the forehead and cheeks the Langer lines run mostly horizontal; a per-region Langer field wasn't worth it at 0.05 mm. |
| Mid band | Hero displacement through adaptive subdivision | Baked into the hero height map (4k, about 0.13–0.25 mm per texel), then displaced. | It is the same field the game normal gets (item 6). The finest part, the 0.6 mm nose cells, is close to the texel size. |
| Added: pore roughness 0.16, SSS 3.4 mm, zone tints | — | — | To break up the T-zone spec, reach the terminator and nose-to-apple hue targets, and do what the orchestrator asked. |
| Under-eye edge | −0.15 mm | Removed (8.7) | Orchestrator skin21 review: the under-eye skin stays matte with soft relief, no edge. |
| Haemoglobin a* | ≥ 1.5 | 0.86 (8.7) | Orchestrator skin20 review: continuous, very low-contrast fine variation with no discrete dots. a* 1.4–1.6 needed the flecked layer. |
| Removed (8.7): sebum patches and coat islands | — | — | Orchestrator skin20 review: they read as wet camouflage. |

### 8.7 skin21–skin25: the skin20 and skin21 reviews

**Builds.** skin21 (first pass), skin22–skin24 (under-eye and glabella), skin25 (final: stronger pore funnels). All on main 416132c except skin21.

**Albedo** (`skin_synth`, game and hero maps):
- **Fine redness**, now continuous: 0.6 × noise 150/m + 0.4 × noise 300/m (features about 3–7 mm), normalised to unit std and clipped at ±2.5. It is symmetric, with no threshold and no softplus, so it mottles and never forms flecks.
  - Weight 0.020 on the cheeks, apples, nose, alar, ears, chin (× 0.6) and neck (× 0.5); 0.010 elsewhere (skin20: 0.060 and 0.030).
  - 0 under the eye and in the beard. Same swing per unit: R +1.6, G −1.0, B −1.1.
- **Smooth zone gradients:**
  - a broad cheek flush: the cheek region × 0.6 in the apple tint (1.06, 0.95, 0.92);
  - warmth around the eyes: the lid region × 0.5 in (1.04, 0.97, 0.97);
  - on top of the nose, apple, ear and forehead tints.
- **Kept:** the broad haemoglobin, melanin, the yellower forehead, the violet-brown under-eye, the even base.

**Specular:**
- **Sebum patches removed**, and the oil mask is no longer gated by them.
- T-zone roughness 0.40 → 0.37, smooth.
- Oil mask × (0.8 + 0.4 × the 55/m noise): it varies over about 2 cm and has no edges.
- Coat 0.02 + 0.10 × oil (skin20: 0.15 × the patchy oil).

**Pores and micro relief, the micro-detail layer** (`skin_tex.hero_material`):
- The procedural pores (three Voronoi layers on `hero_rest`), the cross-hatch and the grain moved from the displacement to a **Bump node on the Principled `Normal` and `Coat Normal`**. They are evaluated per shading sample, so neither the 4k texel (0.13 mm) nor the dicing limits them. Bump distance: 1.5 × the physical depth.
- **Funnels.** Each pore sits in a shallow funnel: radius 2.6 × the opening (capped at half a Voronoi cell), depth 0.6 × the pit. That puts funnel radii at about 0.45 mm on the nose, 0.45 mm on the cheek and 0.24 mm on the forehead. The funnel is what reads in a highlight at distances where the opening itself is sub-pixel.
- **Masks:**
  - pores × (1 − 0.85 × beard);
  - micro relief × (1 − 0.85 × beard) × (1 − 0.5 × lid);
  - lips off; the pores were already off within the eye clearance.
- **Why procedural rather than a tiling texture.** It is the same technique, a detail normal blended over the base, but evaluated on the rest position. So there is no tiling, no UV seam and no texel limit, and the pores sit where the game bake's pores are.
- **Displacement** now carries only the baked map (lines, crepe, mid band).
- **Hands:** bump at 1.0 and no funnel, which is the same relief they had through the displacement. G's hands look the same.
- **Game normal.** It already carries the pores: `hgt_game` is the hero height minus the texel-filtered pores. The funnels and the cross-hatch are below the 4k texel, so they stay hero only.

**Wet crescents under the eyes** (skin21 review, item 1):
- **Cause.** The skin's wet lid band was radial: `eye_d` 16.2 ± 0.4 frame units, i.e. within about 0.4 mm of the eyeball radius, at roughness 0.2. The lower lid and the under-eye skin lie within a millimetre of the eyeball radius for several millimetres, so the band spread onto them and gave the glossy crescent.
- **Proof.** With the roughness forced to a constant 0.5, the crescents vanish: `trackA/skin21/cmp_rough.png` (top: skin22; bottom: constant roughness). The clay pass shows only a soft lid-cheek fold there: `trackA/skin21/ue_diag.png`. Hiding the eyeballs doesn't change the streak: `trackA/skin21/cmp_noeyes.png`.
- **Fix.** The skin wet band is removed. I tried a surface-distance band (1 mm from where the lid tucks behind the eyeball, counted across the UV). At bake time the eye centroid sits forward of the eyeball centre, so 85 % of the lid island counts as tucked, and the band covered the whole lid. The tear line against the eyeball is the hero meniscus (`eyes_hq`: a tube of 0.15 mm radius along the lower lid, roughness 0.05, IOR 1.336), which is what the orchestrator described.
- **Relief.** The −0.15 mm under-eye edge is removed (`undereye_edge_mm` 0), and the under-eye lumps are halved (0.30 → 0.15 mm), so the under-eye is matte with soft relief.
- Before and after at 50 %: `trackA/skin24/cmp_22v24_q.png`.

**Glabella** (item 2):
- **Before:** the frown line was a 0.30 mm Gaussian groove with σ 0.5 mm and raised shoulders, which read as a cut.
- **Now:** two soft furrows, 0.10 mm (left) and 0.05 mm (right), each σ 1.6 mm, with no shoulders and faded at both ends.

**Numbers** (same method as 8.2):

| Run | Forehead comps (all / ≥3 px) | Forehead max px | Nose comps | Nose max px | Lum high-pass % | a* 8–30 px | Hue Δ forehead–apple / forehead–nose / apple–nose (°) | Sat under-eye < cheek | Terminator Δhue (°) | Nostril Δhue (°) |
|---|---|---|---|---|---|---|---|---|---|---|
| E-skin20 | 17/11 | 27 | 2/2 | 39 | 2.31 | 1.41 | 7.9 / 13.6 / 5.7 | 0.561 < 0.572 | 7.4 | 15.8 |
| E-skin24 | 20/3 | 31 | 2/1 | 57 | 2.24 | 0.84 | 8.7 / 13.8 / 5.1 | 0.583 < 0.626 | 5.2 | 12.0 |
| **E-skin25 (final)** | **23/6** | **32** | **3/2** | **42** | **2.30** | **0.86** | **8.7 / 14.1 / 5.4** | **0.583 < 0.627** | **5.2** | **11.4** |
| TT-skin20 | 20/17 | 42 | 9/8 | 18 | 1.43 | 1.45 | 5.1 / 13.1 / 8.0 | 0.281 < 0.379 | −3.0 | 1.5 |
| TT-skin24 | 13/8 | 44 | 38/15 | 17 | 1.29 | 0.70 | 5.7 / 12.5 / 6.8 | 0.284 < 0.397 | −3.9 | 1.6 |
| **TT-skin25 (final)** | **19/8** | **47** | **34/17** | **16** | **1.28** | **0.70** | **5.7 / 12.5 / 6.8** | **0.283 < 0.396** | **−3.8** | **1.6** |

**Against the pass criteria (skin25):**

| Criterion | Target | Result |
|---|---|---|
| Specular, forehead | ≥ 4 components, none > 25 px | **Pass** on components (23). **Miss** on length: 32 px. |
| Specular, nose | ≥ 3 components, none > 25 px | **Pass** on components (3). **Miss** on length: 42 px (57 on skin24, which had the same skin with shallower funnels). The streak is the fill's reflection (8.3). |
| Luminance high-pass | 1.5–3 % | **Pass**: 2.30 %. |
| a* at 8–30 px | ≥ 1.5 | **Miss**: 0.86. This is the price of "no discrete dots"; the colour now comes from smooth zones (hue holds). |
| Hue | ≥ 5° between zones | **Pass**: 8.7 / 14.1 / 5.4°. |
| Under-eye saturation | Less than the cheek | **Pass**: 0.583 < 0.627 (wider margin than skin20). |
| SSS terminator | ≥ 6° toward red | **Miss**: 5.2° (7.4 on skin20). The broad cheek flush reddens the lit apple as well as the terminator. SSS is unchanged. |
| SSS nostril wing | ≥ 6° toward red | **Pass**: 11.4°. |
| Honesty | Turntable ≥ 60 % of shot 1 | a* 0.70 (81 %); luminance high-pass 1.28 % (56 %, a narrow **miss**; skin20 was 62 %); forehead components 19 (83 %); the nose breaks better than in shot 1 (34 components, 16 px max); hue and the under-eye hold. The terminator shift does not hold (−3.8°): the soft turntable key has no hard terminator. |

**Evidence:**
- **135 mm close-up, DOF off, 100 %, turntable light** (8.3 px/mm), the pore check:
  - skin25: `data/build/trackA/skin25/close/turntable_lens135_az20_el5_aimeyes_frame0.13.png`, with crops `crop_fh.png` and `crop_nose.png`;
  - skin21 → skin25 nose at 2×: `trackA/skin25/close/z_nose_21v25.png`.
- **Shot 1:** `data/build/hero/20261013T051448Z-A-skin25/portrait.png`.
  - 2× face against skin19: `trackA/skin24/portrait_face_2x_skin19_vs_skin24.png`;
  - skin24 against skin25: `trackA/skin25/portrait_face_2x_skin24_vs_skin25.png`;
  - forehead top-5 % mask, skin24 against skin25: `trackA/skin25/spec_fh_24v25.png`.
- **Eye shot:** `data/build/hero/20261013T053734Z-A-skin25/eye.png`. Against skin20: `trackA/skin25/eye_fh_20v25.png` and `eye_nose_20v25.png`; the near eye (skin24, which is the same around the eye): `trackA/skin24/eye_near_20v24.png`.
- **Turntable:** `data/build/trackA/skin25/turntable_portrait.png`; against skin20: `trackA/skin25/turntable_face_skin20_vs_skin25.png`.
- **Rake:** `data/build/trackA/rake/rake_skin25_{face,cheek,forehead}.png`.

**Verdicts:**
- **Red lace.** Gone at every distance. The fine variation is a soft mottle, and the zone hues carry the colour.
- **Wet islands.** Gone. The T-zone is a little shinier and smooth; the coat is a thin even film.
- **Under-eye.** Matte; no crescent under either light.
- **Glabella.** A soft, shallow pair of furrows, not a cut.
- **Pores:**
  - **135 mm close-up (8.3 px/mm).** The pores read as dimples with a lit rim. They break the nose and forehead highlights, and the cheek carries a fine stipple. Under the turntable key at portrait framing, the nose highlight breaks into 38 components (9 on skin20).
  - **Hero rig, portrait (2.6 px/mm).** A funnel is about 1–1.3 px. The forehead key highlight fragments at its edges (23 components against main5's 6) and shows a faint grain, but it doesn't break into a visible stipple at 64 spp with OIDN. The nose streak is the 2 × 2 m fill's reflection; a normal perturbation only shortens it (57 → 42 px).
  - **Hero rig, eye.png.** f/4 focused on the cornea holds about 7 mm. The forehead and nose are outside it, so no skin detail can show there. The in-focus lids and under-eye have no pores by design (eye clearance).

  So pores read where the pixel scale allows. Getting a clear stipple in shot 1 would need either a smaller fill (E's rig) or a deliberate exaggeration that would turn the close-up into orange peel.
