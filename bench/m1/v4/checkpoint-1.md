# Checkpoint review: m1 v4 step 0 + viewer (2026-10-14, Fable)

> **Orchestrator notes (2026-10-14, after this review):**
> - §1.1 item 1 and item 4 (chmod) were already done before this review: the fan builds and the worktree-attic archive moved to `private/likeness/work/moved-from-data-20261014/`; `private/` is `o-rwx` (the 22 remaining `o+r` entries are symlinks). The old `codes*.npz` embeddings wait on the user's ArcFace ruling.
> - ArcFace `w600k_r50` is "offline-only, pending user ack" (NOTES §14 rule 8). T7's originality check runs it offline in private and reports one scalar, as earlier identity work already did; the ack is still the user's.
> - FLAME 2023 Open needs the MPI login, which the user types themselves; T7 uses it only if it is fetchable without a new login, otherwise ICT-FaceKit (MIT).

Read-only. Sources: the merged diffs `1c4e2c8..main`, `containment.py`, `check_staged.py`, `build_character.py`, `lookdev.sh`, `beard_bake.py`/`hair_mesh.py`/`config.py`, `web/src/character/{output,stage,materials/index,materials/params,main}.ts`, `web/vite.config.ts`, `character-assets.mjs`, the four track reports, `engine_sheet.png`, `game_portrait.png`, `closeup_before_after.png`, `game_shots.json`, `fetch_flame.sh`, NOTES §14/§17, HANDOFF machine rules, `/proc/loadavg`. Nothing under `private/` was opened. No file modified, no render run.

## 1. Step 0 and the viewer: verification

### 1.1 Containment (T1): sound, four leftovers

The structure is right: `assert_private()` resolves symlinks, finds the main checkout through `--git-common-dir`, refuses anything under the repo that is not `private/`, any work tree, and any non-700 directory outside. `core.hooksPath=tools/hooks` is set in the main checkout (checked). `lookdev.sh` routing, `hero.sh` fail-closed, and the `FAN_CONFIG` default removal all read correctly. Vite's `/@fs/` cannot reach `private/`: there is no workspace root above `web/`, so `server.fs.allow` is `web/` only (checked). The asset middleware is single-root, loopback, `cache-control: no-store`.

Remaining paths, ranked:

1. **Two fan builds are still on disk under `data/`**: `data/build/trackA/fantest/`, `data/build/trackA/fanproof/`. T1 left this to the orchestrator. Delete them (gitignored, so no history risk), today.
2. **The pre-commit hook does not stop a renamed render.** It refuses binaries only under `bench/`; a PNG staged anywhere else (`web/public/`, `docs/`) passes unless the path says `fan`/`likeness`. Fix: refuse every staged raster/mesh/array repo-wide except an explicit allowlist (`web/public/*.png` icons, `provenance/`), and keep `git add -f` as the deliberate override. 10 lines in `check_staged.py`.
3. **`--no-verify` bypass.** Agents commit. Add the same check to `provenance/audit.py --check-files` (runs in CI mode) so a bypass is caught at the next audit. Low effort.
4. `chmod -R o-rwx private` (22 entries still `o+r`), and rewrite or delete the old `codes*.npz` embeddings. Both in T1's "left over", both one command.

Design limit, accepted: likeness content in JSON is detected by the `fan` key and the `private/likeness/` string. A renamed key would pass. Fine while the key is a convention; document it in NOTES §14.

### 1.2 Asset fixes (T2): correct, one consequence not propagated

sRGB fix, trousers ORM and shoe determinism are all verified by the GLB reader; the closeup A/B shows brows and beard as hair rather than a black bar. **But T5 was built in parallel against the pre-T2 build and compensates for the same bug in the engine** (`params.ts`: `facialHair.linearFix: 1` sets the atlas `colorSpace = NoColorSpace`; `albedoGain: 0.45`). On any post-T2 GLB the engine now reads sRGB bytes as linear: beard fill 79/255 decodes to 0.31 instead of 0.077, about 4× too bright, then ×0.45. **The engine beard is wrong on every build from now on until this is flipped.** No frame of a T2 build has been captured in the engine yet (checked: `t2-after2/` has no `game_*.png`).

### 1.3 Viewer (T5): trustworthy for geometry and deformation, not yet for look

Checked and correct:
- Colour pipeline: `outputColorSpace = Linear`, `NoToneMapping`, own exposure → grade → AgX → sRGB encode in one pass; grade applied in scene-linear before the view transform, as `grade.py` does. GLTF base-colour maps are sRGB-decoded by the texture node, ORM/normal linear. Readback target is RGBA8 with the encode in the quad: right.
- Light units: for a small Lambertian emitter, Blender area power P gives E = P/(π d²); three SpotLight I = P/π gives the same. Hemisphere intensity π·Lw for a uniform world: right. 80° cone with full penumbra approximates the cosine to within ~10 % at 40° off-axis.
- Skinning and correctives: port matches `deform_runtime.py` to < 1e-5 on all 14 rules, helpers to 0.036°. This is the strongest result of the day: deformation work can now be judged in the engine without a Blender render.
- Alpha: A2C with 4× MSAA on a half-float target, hashed alpha without MSAA, no sorted MASK. Right.

Must-fix, ranked (all small):

| # | Item | Why it breaks the gate | Fix |
|---|---|---|---|
| 1 | `facialHair.linearFix` / `albedoGain` (above) | Beard/brows/lashes wrong on every post-T2 build | Default `linearFix 0`, `albedoGain 1.0`; derive from the build: if `character.stats.json` carries `atlas_fill_linear`, the atlas is encoded. Remove the knob once main9 is retired. |
| 2 | Baked AO is dead in the hero frame | three's `aoMap` only attenuates indirect light; hero world is 0.003, so the skin/suit AO channel does nothing. Cycles has AO baked into the skin albedo (0.10) and real occlusion. | Multiply AO into direct diffuse at 0.5 (`SkinLightingModel.direct`, cloth likewise) until GTAO lands. |
| 3 | Twill moiré across the whole jacket (visible in `game_portrait.png` as diagonal bands at ~15 px period on lapel, shoulder and sleeve) | The strongest engine-only artefact in the portrait; Cycles hides it with DoF and the 1.5 px filter | Drop the 1.9 mm weave from the baked normal/ORM in `suit_textures.py` (keep seams, wrinkles, hems); weave as a tiled 256² detail normal with mips, faded by `fwidth` as the procedural twill already is. |
| 4 | SwiftShader is not the Air | Every "engine" pixel so far is a CPU rasteriser pinned to 4 cores: no anisotropic filtering guarantee, different MSAA resolve, 25 s/frame | Add a `?capture=1` mode that renders all views on the Air's Chrome and POSTs the PNGs back through the tunnel to the loopback server into the run dir (the server already whitelists one run dir). SwiftShader stays as the headless fallback. |
| 5 | Parity target is the wrong Cycles render | The hero final has DoF, bloom, halation, grain, OIDN, 1.5 px filter; the engine has none, so numeric comparison is meaningless | Add a `--parity` Cycles variant for the portrait: filter 1.0 px, DoF off, no bloom/grain, 64 spp + OIDN. Use that for the metric row; keep the beauty for the eye. |
| 6 | `ENGINE_SHOTS` is off by default | The gate is not produced unless asked | Leave off for loop runs; make it default-on for `--signoff` and `hero.sh`. |
| 7 | Rims are 0.3×1.5 m strips at 1.5 m (subtend 53°) but are spot lights | Rim and kicker land harder and narrower than Cycles (T5 saw this) | LTC rect lights (Q2). |
| 8 | Eye gaze | `wet.gaze` skipped; portrait gaze differs from the Cycles shot | Apply the shot's gaze from `engine_stage.json`. |

Minor: three's AgX is Blender's AgX + "Base Contrast" look via a polynomial approximation; verify once with a grey chart (0.18/0.5/1.0 rendered in both, tolerance ±3/255) and move on. The sheen model differs (three Charlie vs Blender 4.x Principled sheen); handle by calibration, not porting (Q2 item 3).

## 2. Is the engine frame a sound oracle?

Not yet. It is a sound **geometry, rig and material-correctness** oracle today (cameras by data, pose by data, correctives verified). It becomes a **look** oracle after, in this order:

| # | Item | Effort | Depends on C2? |
|---|---|---|---|
| 1 | The §1.3 must-fixes 1, 2, 3, 5, 6, 8 | 1 day | no |
| 2 | Air capture path (§1.3 #4) and first Air numbers (frame time, GPU timestamps) | 0.5 day + user's Mac | no |
| 3 | **Shader-ball parity row**: each material (skin, wool, silk, leather, hair card, eye) on a sphere under the neutral rig, Cycles vs engine, in the sheet; metric: per-material mean luminance ratio within ±10 %, highlight-peak ratio within ±20 %. This is what calibrates sheen scale, skin wrap, hair lobe gains without taste. | 1 day | no |
| 4 | GTAO (or SSAO at half res) + the direct-AO hack removed | 1 day | no |
| 5 | LTC rect area lights for key, wrap, rim, kicker (sizes from `engine_stage.json`): fixes rim hardness and gives strip highlights on hair and wet eyes | 1–1.5 days | no |
| 6 | Pre-integrated SSS: curvature bake into the ORM alpha (or a 1k map) in `skin_tex.py`, LUT in `SkinLightingModel`; replaces the normal-blur stand-in | 1 day | no (realism and stylised both need the soft terminator) |
| 7 | Output pass: bloom, halation, grain, vignette are already in `grade.py` numbers; DoF for the portrait only | 0.5 day | no |
| 8 | KTX2: `gltf-transform` UASTC for normals/ORM, ETC1S for albedo, target ASTC 4×4 on Metal; 579 MB → ~60 MB GPU | 0.5 day | no |
| 9 | Painted albedo bake, 3-band ramp tuning, ink pass | 2–3 days | **yes** |

After 1–8 the engine frame is the gate; 9 waits on the user.

## 3. Track specs

Common to all three: worktree per track; `nice -n 10`; builds at `blender -t 4`; one Cycles gate render per track at `-t 6` only through `flock /tmp/or3-cycles.lock`; EEVEE for iteration. Reports go to `bench/m1/v4/t{6,7,8}-*.md`, images under `data/build/`, links not binaries. Do not touch `blender/hero/rig.py` (T3 owns it). Do not edit `NOTES.md` beyond a decision-log line each.

### T6: engine look parity (no C2 dependence)

**Goal.** Make `engine_sheet.png` a trustworthy look gate: items Q2 #1–8.

**Files.** `web/src/character/materials/{index,params}.ts` (linearFix removal, direct AO, SSS LUT, hair gains), `web/src/character/{output,stage,main}.ts` (bloom/grain/DoF, LTC lights, capture mode), `bench/m1/engine_shots.{sh,mjs}` (parity row, Air capture receiver, default-on for signoff), `bench/m1/lookdev_report.py` (shader-ball row), `blender/lookdev_render.py` (shader-ball scene, `--parity` portrait variant), `blender/character/suit_textures.py` (weave out of the bake, detail tile exported as a sidecar `suit_twill_detail.png`), `blender/character/skin_tex.py` (curvature channel), `blender/character/export.py` (KTX2 post-step via `gltf-transform`, behind `--ktx2`), `web/package.json` (`@gltf-transform/cli` dev dep, KTX2Loader transcoder path).

**Parameters.** Direct-AO 0.5; LTC sizes from stage JSON; SSS LUT 128×128 curvature×N·L with Penner's profile scaled to the hero radii 3.4/0.75/0.34 mm; bloom threshold/strength and grain from `grade.py` values; portrait DoF f-stop and focus from `engine_stage.json`; KTX2 UASTC quality 2, ETC1S quality 128.

**Gate.** Picture: `engine_sheet.png` row 3 (Cycles parity portrait vs engine portrait, captured on the Air). Metric: shader-ball luminance ratios within ±10 % for all six materials; portrait SSIM (luma, 512 px) ≥ 0.80 against the parity Cycles render (today's SwiftShader frame will be ~0.6; record the baseline first).

**Do not.** Do not change the BRDF structure or add stylisation (C2). Do not retune the beard/brow atlases (T8). Do not touch `hair_groom*.py`, `head_*.py`. Do not raise MSAA above 4×. Do not port Blender's sheen; calibrate `cloth.sheenScale` on the ball.

**Conflicts.** `suit_textures.py` and `export.py` are T6-only this round (the suit spike, if started, must not touch them). `lookdev_report.py`: T8 adds a hair test row to the same file; coordinate by appending separate functions, merge T6 first.

### T7: head structure + original public identity

**Goal.** Replace the egg with a skull and the actor-adjacent public face with an original, statistically authored one, through one sculpt layer that both builds share.

**Licence finding (blocking).** `pipeline/likeness/fetch_flame.sh` downloads **FLAME2020.zip**, and HANDOFF line 9 confirms it. Per the official licence page, FLAME 2017/2019/2020/2023 are under the academic licence (non-commercial research, education, artistic projects; no redistribution of derivatives). Only **FLAME 2023 Open** (released 2025-11) is CC-BY-4.0. NOTES line 140 already names "FLAME 2023 Open (CC-BY-4.0)" as the intended reference, so the fetch script is simply behind. A public mesh derived from FLAME 2020 would repeat the SMPL conflict of §17 q6 (the repo's assets are CC BY 4.0). **Decision for T7: fetch FLAME 2023 Open (`flame2023_Open.pkl`; verify the exact `sfile=` name on the download page), load it through `flame.py` (dict loader, should be format-compatible; assert key set and 300 shape PCs), author the public identity only in that space, and add a `CREDITS.md`/provenance entry ("FLAME 2023 Open, MPI-IS, CC BY 4.0, shape coefficients only").** The private fan fit may stay on 2020 (never shipped). If 2023 Open cannot be fetched without the academic click-through, the FLAME-free alternative is **ICT-FaceKit** (MIT: identity PCA, face topology, landmark indices): same `wrap.py` path with an ICT target embedding; or, as the floor, no statistical prior at all (MPFB targets + the sculpt layer below), which loses the skull-shape prior but nothing else.

Sources: [FLAME](https://flame.is.tue.mpg.de/), [FLAME model licence](https://flame.is.tue.mpg.de/modellicense.html).

**Files.**
- `pipeline/likeness/fetch_flame.sh` (2023 Open), `flame.py` (version assert), `wrap.py` (unchanged; reuse).
- New `pipeline/likeness/author_public.py`: shape coefficients → FLAME neutral mesh → `wrap.py` → `data/build/identity/public_face.npz` (`delta`, `base`, coefficients, FLAME version). Coefficients live in `bench/m1/variants/public_identity.json` (300 floats, tracked). The delta is rebuilt by the build when missing; optionally committed with `git add -f` (35 KB) plus provenance. Key name `identity`, never `fan` (containment treats `fan` as likeness).
- `blender/character/head_fan.py` → generalise to `head_layer.py`: applies `head.identity_delta` (public) **or** `fan.face_delta` (private, replaces it), same code path.
- New `blender/character/head_sculpt.py`, called in `head.edit_base` **after** the identity layer: landmark-anchored displacement fields at 1–2 mm sampling on a temporary 2× subdivided head, baked back as (a) vertex offsets on the base mesh and (b) a mid-frequency normal into `skin_head_normal` via `head_refine`. Fields: supraorbital ridge, orbital rim (recess 2–3 mm inside it), zygomatic arch to the ear, mandibular border and gonial angle, nasal bones and dorsum edge, mentalis/chin, temporal line. Anchors come from the MediaPipe embedding of the base mesh (`clay_views.py embed`), re-evaluated after the identity delta so they follow the face.
- `blender/character/config.py`: `head.sculpt` block (mm per field, sigma, direction), `head.replanarise` back to 1.0 with `plane_sharp` 3.0; halve the mouth target stack in `bench/m1/variants/direction.json` (keep `mouth-scale-horiz-decr`, `upperlip-height-decr`, `cupidsbow-incr` at ≤ 0.5; drop the rest to 0); globe radius 12.0 mm, iris 5.9, lid margin 1.5 mm, upper lid −1.5 mm over the iris, lateral canthus +2°, convergence 2° to 1.2 m.
- `blender/character/head_measure.py`: add `gonial_angle_deg`, `orbit_recess_mm` (rim plane to cornea apex), `eye_aperture_mm`, `canthal_tilt_deg`, `forehead_behind_brow_mm`; redefine `brow_overhang` as supraorbital rim minus cornea apex along the profile axis (not "most forward vertex in 8–40 mm").
- Metric targets: gonial 115–120°; aperture 9.5–11 mm; canthal tilt +2–4°; orbit recess 2–3 mm; brow overhang ≥ 8 mm with `forehead_behind_brow_mm ≥ 3` (kills the bulge that passed the old test); bizygomatic/bigonial ratio 0.84–0.88; lower-face index per spec.

**Originality gate.** Author coefficients by hand within ±2.5σ from the §3.4 brief (strong supraorbital, wide zygomatic, square mandible, age 45), no photo input: original by construction. Verification runs **in private** and reports one scalar: ArcFace cosine similarity between the public closeup render and the private reference median (`identity_codes.py` already keeps `median`; add a `compare` subcommand that prints a number and writes nothing). Target **≤ 0.25** (same-identity threshold for `w600k_r50` is ~0.45–0.5). ArcFace is offline-only and pending the user's ack (NOTES §14 rule 8); run it, do not ship it. Also render the private fan build once with the new sculpt layer to confirm the layer composes (`head_layer` + fan delta) and the fan gate still holds; report numbers only.

**Gate.** Picture: clay turntable + bald face strip with a visible brow shelf, zygomatic plane break and gonial angle; engine closeup on the sheet. Metric: all five new measures in range, ArcFace ≤ 0.25.

**Do not.** No skin micro-detail work. No hair/beard changes. No touching `hair_groom*.py`, `suit_*`, `web/`. Do not run Cycles finals; EEVEE + the engine frame + one 64 spp parity portrait at the end.

**Conflicts.** Owns `head*.py`, `config.py` head block, `direction.json` head/mouth keys, `head_measure.py`, `pipeline/likeness/*`. T8 owns `config.py` hair/beard blocks: edit different dict literals, merge will be textual-clean if neither reformats the file.

### T8: hair v4 steps 1–3

**Goal.** `fable_review.md` §5.5 steps 1–3: the groom the cards will be baked from, hairline/scalp, and shading. Blender-only; no cards yet (step 4 is next round, judged on the engine).

**Files.** `blender/character/hair_groom.py` (direction field replacing the global comb; 4-level clumps; trim cut; stand-off halved at sides; front falls as guides; flyaways as stray hairs), `hair_frame.py` (whorl/field helpers), `hair_groom_cards.py` only to keep the build running (no card changes), `config.py` hair/beard tone blocks, `blender/character/skin_synth.py` scalp albedo darkening, `hair_beard.py`/`beard_groom.py` tone only, `blender/lookdev_render.py` + `lookdev_report.py` (neutral two-light hair test row), `hair.md`.

**Parameters.** 60–80k strands, radius 0.04 mm blunt (profile factor min 1 except flyaway/vellus); clumps L1 40–60 @ 0.3, L2 ~400 @ 0.4, L3 3–5k @ 0.35, L4 micro 0.2, Preserve Length on, Tip Spread; trim with 5–8 % random offset, 2–3 cm end taper; noise 1.5 mm, frizz 0.5 mm after clumps; hairline distance field perturbed by 2–3 octaves of 1–2 mm noise, M-recession asymmetric, single forward edge hairs, vellus 2–3× denser at r 0.025; scalp tint shell from 0 mm; melanin 0.82 ± Random Color 0.2, 12 % grey weighted to temples, root-dark/tip-light; Chiang vs Huang A/B; 3D Curves; glossy bounces 16. 48-point resample (the cards will need it).

**Beard grey retune: yes, here, scoped to tone.** The grey now visible is the configured `grey_chin 0.45 / grey_share 0.08` (§7 wants a greying beard, so the intent stands). What is wrong is that hero strands and game shells no longer agree. In T8 step 3 set the beard tone once (`tone.grey_*`, swatches) so the hero strands and the baked atlas carry the same colour, then remove the engine's `facialHair.albedoGain` dependence (T6 drops the knob). Metric: beard-region linear mean luminance in the EEVEE closeup within ±25 % of the Cycles closeup under the neutral rig. Do not touch shells/cards geometry (step 6).

**Gate.** Picture: back view + clay turntable show layered ends and no helmet; `portrait_crop` hairline reads skin-to-hair; two distinct highlights under the neutral two-light hair test. Metric: hair-region luminance histogram under the hair test has ≥ 2 modes (R and TRT) and the 10th-percentile value ≥ 2× today's (no longer black); strand count and clump factors recorded in `character.stats.json`.

**Do not.** No cards, no engine shader tuning, no `beard_bake.py` changes, no Cycles finals (hair test at 64 spp, 768², hair only, ≤ 4 min at -t 6).

**Conflicts.** Owns `hair_*.py`, `beard_groom.py`, `hair_beard.py`, config hair/beard blocks, `lookdev_report.py` hair row (append-only; T6 merges first).

### Suit spike (step 5): start, but small and later in the day

The suit's risk is design (pattern drafting), not compute, and it is the longest item. Start a **1-day spike** only after T6 lands its first merge (it is the shortest) or when the other project's load drops: `blender/character/suit_pattern.py` draft-only (Aldrich-style jacket body + two-piece sleeve from the body landmarks already measured), one sewing-spring drape of the jacket body on the rest pose at `-t 2`, clay render. Gate: lapel roll and a sleeve pitch visible in clay. Not touching `suit_textures.py`/`export.py` (T6) or any shipped path.

## 4. Machine

Now: load 43 on 16 threads; **three headless Chrome processes of the other project (or4) take ~14 cores with affinity `ffff`** (pinning is not applied there), plus T3's Blender at ~2 cores. Any plan for today runs on top of that.

- Run **three** tracks: T6, T7, T8. Not four. Queue the suit spike behind T6.
- Caps: `blender -t 4` per track for builds (HANDOFF says 3 when load is high; use 3 while or4's Chromes are up); one Cycles gate render at a time via `flock`, `-t 6`; EEVEE for everything else; `ENGINE_CPUS=12-15` for SwiftShader; `nice -n 10` on all of it. No `--signoff` or hero finals until load < 20.
- Ask the user to pin or pause or4's headless Chrome; it is the dominant load and it is not ours.

## 5. What today's results should change in the plan

1. **FLAME 2020 → 2023 Open is a blocker for T7's public face.** Fix the fetch before any coefficient authoring. The fan fit can stay on 2020 privately.
2. **The engine frame is currently wrong for facial hair on every post-T2 build** (`linearFix`). Flip it before anyone judges a beard in the engine.
3. **The oracle is SwiftShader until the Air capture exists.** Treat `engine_*.png` as geometry/material-correctness evidence this round, not look evidence; the Air path is T6 item 2.
4. **The engine sharpens the identity question.** Under the hard engine light, the public build reads as the actor's costume (long hair, beard, black suit) more than the face itself; the face is generic-soft. The originality gate (ArcFace ≤ 0.25, run in private, scalar only) should be a standing metric on the sheet from T7 onward, and the hair v4 cut/length and beard shape are part of originality as much as the face is. Flag this to the user with the C2 decision.
5. **C2 should be decided now**, not after T6. The T5 frame shows that the realistic path needs GTAO, LTC, SSS, DoF, bloom and KTX2 just to reach parity with a render that already fails as realism (§3.1). My recommendation stands: painterly-stylised realism on the character. T6 is sized to be useful either way.
6. **Twill moiré** is a bake problem exposed by the engine; take the weave out of the shipped maps (T6). This also drops GLB size.
7. **Deformation can move to the engine.** With correctives verified to 1e-5, the step-8 deform work (DQ skinning, Dem Bones) no longer needs Blender renders for its gate.
8. Beard grey is not a bug but a mismatch; resolve tone in T8, geometry in hair v4 step 6, and stop compensating in the engine.
9. T3 (light twins) touches `hero/rig.py`; none of T6/T7/T8 should, so the merges stay clean.