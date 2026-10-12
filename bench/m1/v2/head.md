# m1 v2 Track A: head forms, skin and eyes

Track A report (BRIEF.md). Branch: `worktree-agent-ae8e46d215f90ce05`.

Merged commits:
- 00a177d, forms freeze (merged 4881440).
- b4911f6, forms v2 (merged 8fa40c6).
- 1431541, skin v2 (merged 3315819).

On the branch since then:
- 55723d9, the under-eye forms parameters (approved).
- The skin8–11 commit: pores as relief, micro relief, and the eye pass.

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
| `blender/character/skin_synth.py` (new) | All map synthesis, in numpy on the baked surface data:<br>- face frame and regions; region pores;<br>- lines: forehead, frown, crow's feet, under-eye, nasolabial, lip creases and neck;<br>- lid and under-eye crepe;<br>- albedo zones: forehead yellow, mid-face red, a cool darker beard zone, violet-brown under-eye, moderate socket, lid and roof shading;<br>- temple veins, alar capillaries, stubble, freckles and blemishes (no moles, no scars);<br>- mouth-corner lift;<br>- roughness map;<br>- hero masks (pores, oil, fuzz, micro). |
| `blender/character/skin_tex.py` (rewritten) | Bake, plus the pose-stable rest-position attribute `hero_rest`. 3D noises (Voronoi pore fields, anisotropic noise). Game images. The hero material and the hero step. |
| `blender/character/eyes_hq.py` (rewritten) | Eyeball with a bulge profile.<br>Lid maps ray-cast against the body (coverage, aperture flood fill, canthi).<br>Iris: fibres, crypts, collarette and limbal ring.<br>Sclera: warm, with meandering sectored vessels, a limbal halo and darker corners.<br>Lid occlusion baked into the game albedo and ORM.<br>Hero eye: a recessed conical iris, a separate refractive cornea (IOR 1.376, shadow-transparent), a lower tear meniscus (IOR 1.336) and a caruncle at the inner canthus. |
| `blender/character/head.py` | The `hero()` step (skin, eyes, mouth). The mouth hero darkens the teeth to 0.78 and the tongue to 0.85, with roughness and SSS, so the teeth no longer glow. |
| `bench/m1/variants/direction.json` | Forms tissue keys. Skin base `#b8927b`. Approved under-eye change: lid_bag_mm 0.8 → 0.3, tear_trough_mm 1.2 → 0.9. |
| `bench/m1/head_closeups.py` | Studio close-ups (face, eye, pores, mouth, cheek, forehead) from a kept `.blend`. Track tool. |
| `provenance/mesh.jsonl` | One record: Blender Studio Human Base Meshes 1.4.1 (CC0). It was evaluated as a forms reference and **rejected**; nothing from it is shipped (section 6). |

**Shared-file edits:** one line in `blender/build_character.py`, `b.step("head_hero", head.hero)`, right after `export_glb`. The coordinator approved it.

## 2. Hero skin material (Cycles)

- **Principled BSDF**, Random Walk (Skin) subsurface:
  - weight 1.0; radius (1.0, 0.25, 0.12) × 2.5 mm;
  - anisotropy 0.8; IOR 1.4.
- **Specular:** IOR level 0.5, IOR 1.4.
- **Roughness map.** Mean 0.485; face mean 0.51.

  | Area | Roughness |
  |---|---|
  | T-zone | 0.40 |
  | Cheeks | ~0.47–0.50 |
  | Beard | 0.58 |
  | Lips | 0.45, with vertical crease breakup |
  | Ears | 0.48 |
  | Under-eye | +0.10 |
  | Crepe | +0.08 |
  | Micro scale (hero) | plateaus −0.03, furrow valleys +0.10, pore openings +0.12 |
  | Wet lid margin | 0.2, on the rim touching the eye only |

- **Coat:** 0.04 + 0.11 × the oil mask, so at most 0.15 (direction §2), roughness 0.28. The oil mask covers the T-zone and some cheek, but not the under-eye.
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
  - 0.5 mm spacing, narrow valleys, 0.035 mm deep, broken in ~1.4 mm patches;
  - a 0.05 mm, 0.004 mm grain.

  The orchestrator asked for a 0.15–0.3 mm secondary net. That is under a pixel even in the 135 mm close-up (0.12–0.15 mm/px), so it only averages into roughness. The 0.5 mm primary lines are what resolve; the grain stands in for the rest.
- **Displacement**, in world space and in mm: baked lines and crepe, minus the pores, minus the micro relief.
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
| Coat | 0.15 flat | 0.04–0.15 on the oil mask, roughness 0.28 | Less coat away from the oily zones. |
| Forehead lines | 0.2 mm | 0.30 mm with a 1.2 mm valley | So they survive the 2.5 mm SSS. |
