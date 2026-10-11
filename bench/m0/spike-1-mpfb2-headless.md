# Spike 1: MPFB2 headless character build

**Status: PASS.** MPFB2 runs fully headless (`blender -b`) on Blender 5.2.2 LTS. One script creates a human, adds the `game_engine` rig and the CC0 `suits01` suit (plus body parts, hair and shoes), and exports a skinned GLB. The GLB passes the Khronos glTF-Validator with 0 errors. **A full build takes 2.2 s.** No fallback (Anny or a direct base-mesh import) was needed.

Date: 2026-10-12. Branch: `worktree-agent-ae7709a9aedba6d2d`.

## What was done

| Item | Version / source |
|---|---|
| Blender | 5.2.2 LTS (Arch `blender 17:5.2.2-2`, bundled Python 3.14) |
| MPFB2 | **2.0.18** (build 20261010) from extensions.blender.org, user repo `blender_org`. Installed headless with `blender -b --online-mode --command extension install -s -e mpfb` in 3.6 s. |
| MakeHuman system assets | `makehuman_system_assets_cc0.zip`, sha256 `b542127a…0107` (267 MB zip, 287 MB unpacked) |
| suits01 | `suits01_cc0.zip`, sha256 `2b1d8676…1f19` (40 MB zip, 49 MB unpacked) |
| glTF validation | Khronos `gltf-validator` 2.0.0-dev.3.10, `@gltf-transform/cli` 4.5.1 (`inspect`), Node 24.21 |

**Pipeline** (`blender/build_character.py`, run as `blender -b -t 3 --factory-startup --python … -- args`):

1. **Enable MPFB.** Two asset roots are injected into MPFB's *in-memory* preferences only: `mpfb_second_root` points at the system pack and `mh_user_data` at suits01. Each pack therefore stays in its own `data/raw` directory. No copying is needed and no global preferences are saved.
2. **`HumanService.create_human()`** with macros: gender 1.0, age 0.55, muscle 0.6, height 0.6, proportions 0.6, mixed race.
3. **Skin.** `young_caucasian_male.mhmat`, with MPFB `GAMEENGINE` materials (a single Principled BSDF).
4. **`add_builtin_rig(basemesh, "game_engine")`.**
5. **Body parts.** Low-poly eyes, eyebrow001, eyelashes01, teeth_base, tongue01, hair `long01`. All use `subdiv_levels=0`.
6. **Suit.** `toigo_male_suit_tie_and_jacket` (suits01) plus `shoes04` (black dress shoes, system pack).
7. **Stage for export.** `ExportService.create_character_copy` + `bake_modifiers_remove_helpers`, which bakes the clothes delete-masks, removes helpers and joint cubes, and deletes the un-staged original.
8. **Two fixes MPFB's own export path needs for glTF** (see Failures).
9. **Export** with `export_scene.gltf`: GLB, skins, 4 influences, tangents, no animation or morphs. The staged `.blend` is also saved for renders.

**Outputs** (gitignored): `data/build/character/character.{glb,blend,stats.json,glbstats.json,inspect.txt}`.

## Measured numbers

Timings: 3 runs, `-t 3`. Other Phase 0 spikes were running at the same time. Loadavg at the start of each run: `4.15 2.66 1.44`, `4.06 2.67 1.45`, `4.06 2.67 1.45`.

| Step | Run 1 (s) | Run 2 (s) | Run 3 (s) |
|---|---|---|---|
| enable MPFB + asset roots | 0.12 | 0.12 | 0.12 |
| create human (base mesh + macro targets) | 0.21 | 0.20 | 0.20 |
| skin | 0.03 | 0.03 | 0.03 |
| add `game_engine` rig + weights | 0.09 | 0.09 | 0.09 |
| body parts (eyes, brows, lashes, teeth, tongue, hair) | 0.13 | 0.13 | 0.13 |
| suit + shoes | 0.41 | 0.41 | 0.41 |
| stage for export (copy, bake masks, strip helpers) | 0.34 | 0.34 | 0.34 |
| bake targets + alpha fix | 0.00 | 0.00 | 0.00 |
| export GLB | 0.37 | 0.37 | 0.37 |
| **process wall (Blender start → quit)** | **2.38** | **2.26** | **2.20** |

The GLB (Human.rig_export root; 1.85 m tall) per mesh:

| Mesh | Tris | Verts (GLB) | Max weights/vertex, source | Max weights/vertex, GLB |
|---|---|---|---|---|
| body (`Human`, covered polys masked) | 15,240 | 8,320 | 5 | 4 |
| suit `toigo_male_suit_tie_and_jacket` (one shell: jacket + shirt + tie + trousers) | 19,202 | 10,610 | 6 | 4 |
| hair `long01` | 4,108 | 3,312 | 7 | 4 |
| shoes `shoes04` | 3,320 | 1,846 | 3 | 3 |
| teeth `teeth_base` | 7,120 | 4,494 | 1 | 1 |
| tongue | 448 | 253 | 1 | 1 |
| eyelashes | 368 | 250 | 1 | 1 |
| eyebrows | 192 | 124 | 1 | 1 |
| eyes (low-poly) | 172 | 96 | 1 | 1 |
| **Total** | **50,170** | 29,305 | | |

| Property | Value |
|---|---|
| Bones / joints | **53** (all deform). UE-mannequin naming: `Root pelvis spine_01..03 clavicle upperarm lowerarm hand` + 3×5 finger bones per hand, `neck_01 head thigh calf foot ball`. No twist, helper, face or eye bones. |
| Skins | 1 skin, shared by all 9 meshes |
| Max weights per vertex in GLB | **4** (`JOINTS_0`/`WEIGHTS_0` only; the exporter trims 5–7 → 4 and renormalises) |
| GLB size | **14.0 MB** (14,005,772 B). About 11.7 MB of that is 10 embedded PNG textures (three at 2048², the rest 1024² or 512²). Geometry is about 2.1 MB uncompressed f32. |
| Materials | 9. Alpha modes after the fix: hair, brows, lashes `MASK@0.5`; the rest `OPAQUE` |
| glTF-Validator | **0 errors**, 9 warnings, all `NODE_SKINNED_MESH_NON_ROOT`. Blender parents skinned meshes under the armature node. This is harmless because the armature node has an identity transform. |
| Licence audit | 1,538 MPFB bundled files + 478 pack files: **0 flagged** (see below) |

The budget check against NOTES §7 is in "Risks and recommendation".

## Licence audit (NOTES §14 rule 5)

`provenance/audit_makehuman.py` checks every file in each pack. It reads each file's own header for licence or author lines and flags AGPL, GPL, CC-BY, Creative Commons, NC or SA text. It then cross-checks the pack JSON. Results are in `data/build/provenance/*.csv`.

| Pack | Files | Result |
|---|---|---|
| makehuman_system_assets | 421 | 0 flagged. 209 text files carry the "explicitly released as CC0 in september 2020" header (copyright holders: Data Collection AB, Joel Palmius, Jonas Hauquier). 205 binaries (PNG/thumb) have no header. 6 shoe `.mhw` files have no header but pack JSON says CC0. |
| suits01 | 57 | 0 flagged. 16 files carry `# author MRT` / `# license CC0`. 8 `.mhmat` files have no header; pack JSON says CC0, author MargaretToigo. 32 binaries. |
| MPFB 2.0.18 bundled `data/` (base mesh, targets, rigs, weights) | 1,538 | 0 flagged. Only `base.obj` has the CC0-release header, and the `weights.*.json` files carry `"license": "CC0"`. Rig JSON and the 1,273 `.target.gz` files have no per-file header; MPFB's `LICENSE.md` §C covers them: "The base mesh and proxies, Targets and modifiers, … Rigs, poses and expressions … released under CC0 1.0". MPFB *code* is GPL-3.0, but it only runs offline and is never shipped. |

**Verdict:** the AGPL/CC-BY headers NOTES warns about appear in **neither** pack used here. The audit stays in CI for any future pack.

## Commands to reproduce

```sh
blender/install_mpfb.sh                                   # MPFB2 user extension, headless
blender/fetch_mpfb_assets.sh /home/akram/code/or3/data    # zips + sha256 + bsdtar unpack into data/raw/makehuman/
uv run --no-project --python 3.12 python -I provenance/audit_makehuman.py \
  --out /home/akram/code/or3/data/build/provenance/makehuman_audit.csv \
  /home/akram/code/or3/data/raw/makehuman/makehuman_system_assets/unpacked \
  /home/akram/code/or3/data/raw/makehuman/suits01/unpacked
npm install --prefix bench/m0/glb-stats
DATA=/home/akram/code/or3/data bench/m0/bench_spike1_build.sh 3 3   # 3 builds, -t 3, validate + inspect
```

## Failures and workarounds

1. **Shape keys were not baked, so the head ended up at chest height.** MPFB keeps the macro targets as 16 shape keys on the base mesh. `bake_modifiers_remove_helpers` deliberately preserves them. The glTF exporter (with `export_morph=False`) then writes the **Basis**: the un-morphed neutral body, which no longer matches the fitted rig, hair and clothes. The first renders showed a face floating at the collar. **Fix:** `TargetService.bake_targets()` on every staged mesh before export. If we later want morphs (face shapes or correctives), export them explicitly as morph targets instead.
2. **Every material exported as `alphaMode: BLEND`.** MPFB `GAMEENGINE` materials link texture alpha into every BSDF. The exporter maps that to BLEND, which caused EEVEE sorting artefacts (blocky suit and face) and will cost us depth-write in three.js. **Fix:** drop the alpha link on opaque materials, and route it through a Math `ROUND` node for hair, brows and lashes. The exporter recognises that pattern and writes `MASK` with cutoff 0.5.
3. **No `unzip` on the machine.** I used `bsdtar` (libarchive), which refuses absolute and `../` entries without `-P`.
4. Minor: the first run used `shoes01` (tan brogues). Switched to `shoes04` (black dress shoes) after checking the pack thumbnails.
5. The extension CLI takes `install -s -e mpfb`, not `--sync … --enable mpfb` as a trailing package list.

## Risks and recommendation

- **Recommendation: keep MPFB2 as the base-body tool.** It works headless, is fast (~2 s per build, so a best-of-N look-dev loop is cheap), deterministic and fully CC0 on the data side. Drop the Anny fallback from the risk table (§16): the risk is retired.
- **Budget check against NOTES §7** (LOD0 40–60k tris, body ~15k, suit 15–20k, hair 8–12k, face/eyes ~5k; 60–90 bones; 4 weights/vertex):
  - Tris: 50.2k total. The body (15.2k) and suit (19.2k) already fit their budgets.
  - **Teeth are 7.1k tris** (14 % of the budget, for something barely visible) and should be swapped for `teeth_shape0x`, a proxy, or decimated.
  - Hair is `long01` at 4.1k as a placeholder. It will be replaced by our clump-mesh hair (8–12k).
  - Bones: 53, under the 60–90 budget. That leaves room for the planned twist and helper bones and the Dem Bones virtual bones.
  - Weights: max 4 per vertex in the GLB, as budgeted.
- **The suit is a single shell** with all garments in one mesh and one 2048² diffuse texture: grey pinstripe, no normal map. The tailoring plan in §7 (separate shirt, vest, jacket and tie shells; lapel roll; vent) means substantial scripted work on top. That is expected; the CC0 base is clean to start from.
- **Textures dominate size** (11.7 of 14 MB as PNG). KTX2 (glTF-Transform `etc1s`/`uastc`) plus meshopt will be the shipping path. Out of scope here.
- **API-stability risk.** MPFB's Python services are an internal API with no stability promise. I access them through the extension module name (found dynamically), and the scripts pin MPFB 2.0.18 in this report. Re-run `bench_spike1_build.sh` after MPFB updates.

## User actions

- None required for spike 1.
- Optional: `sudo pacman -S unzip`. Not needed; `bsdtar` is used.

## Proposed NOTES.md updates

- §7 Method 1: replace "Headless operation is **unverified** and is spike #1" with "**Verified headless** (spike 1, MPFB 2.0.18 on Blender 5.2.2): ~2.2 s per full build; scripts in `blender/build_character.py`".
- §7 add an export note: "MPFB keeps macro targets as shape keys. Bake them (`TargetService.bake_targets`) before glTF export, or the Basis ships. Fix GAMEENGINE alpha links (opaque vs MASK) before export."
- §7 Budgets: record the measured baseline: 50.2k tris (body 15.2k, suit 19.2k, hair 4.1k, teeth 7.1k, shoes 3.3k, small parts 1.2k), 53 bones, 4 weights/vertex. Add: "swap `teeth_base` (7.1k tris) for a lighter shape".
- §14 rule 5: "Audited 2026-10-12 with `provenance/audit_makehuman.py`: system assets, suits01 and MPFB-bundled data clean (0 AGPL/CC-BY headers)."
- §16 Risks: mark "MPFB2 headless untested" **retired**.
- §17 Q3 (provenance format): propose the TOML layout in `provenance/sources.toml`. Each upstream archive is one `[[source]]` with URL, sha256, author, licence and audit result. Each shipped file is one `[[asset]]` that references sources by id, plus transform, tool and seed. CI checks that the coverage is complete, the licences are on the allow-list, and re-fetched sha256 values still match.
- §6 repo layout: `bench/m0/glb-stats/` is a tiny Node package (gltf-validator + gltf-transform). It could move to `tools/` or `pipeline/` once `tools/` exists.
