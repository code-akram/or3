# m1 v4 step 0, track T2: character asset bug fixes

_Track T2 report, 2026-10-14. Source: `fable_review.md` §1.8 (shoes, trousers AO), §1.9 and §5.3 item 8 (facial-hair sRGB). Public build only (`bench/m1/variants/direction.json`), no fan overlay._

There are three fixes. Each one is checked in the exported GLB with `bench/m1/v4/t2_glb_check.py`, a small glTF reader that needs no Blender. ImageMagick decodes the PNGs.

## Runs

All runs are under `data/build/lookdev/`, built with `THREADS=6` in loop (EEVEE) mode. Comparison images and JSON are in `data/build/t2/`.

| Run | Code | Use |
|---|---|---|
| `20261014T092202Z-t2-before` | main `1c4e2c8` (unchanged; built from a temporary detached worktree) | before |
| `20261014T092825Z-t2-after1` | this branch, all three fixes | after, build 1 |
| `20261014T093536Z-t2-after2` | same | after, build 2 (determinism) |

The reference `…-heroE-main9` predates the track B/C merges, so `t2-before` is the like-for-like baseline. The only difference in budget is beard 6954 → 6960 and brows 1224 → 1240 tris, and that comes from those merges.

**Budgets are unchanged by T2.**

| | before | after1 / after2 |
|---|---|---|
| Total tris | 126,884 | 126,884 (every part identical) |
| Bones | 83 | 83 |
| Weights per vertex | 4 | 4 |
| glTF validator | 0 errors, 16 warnings | 0 errors, 16 warnings |

The GLB grows from 73.5 to 74.0 MB. Two things add to it: the trousers now carry their own ORM PNG, and the lighter atlases compress less well.

## 1. Facial-hair atlases were linear in sRGB images

**Cause.** `beard_bake.make_image` wrote linear RGB into an sRGB-tagged byte image. Blender stores the `pixels` of a byte image as-is, so a renderer decoded the values a second time. That made the colours far too dark, and the dark tones landed on a handful of byte levels. It affected the beard shells and cards, the brow shells and cards, and the lash strip.

**Fix.**
- `hair_mesh.rgba_image(name, rgba, srgb)` is now the one helper for both kinds of image:
  - Colour: encoded with `linear_to_srgb` and tagged sRGB.
  - Data: tagged Non-Color and written as-is.
- `beard_bake.make_image` delegates to it with `srgb=True`. That covers every consumer: `hair_beard`, `brows` and `lashes`.
- `hair_groom_cards`, which was already correct, now uses the shared `hair_mesh.linear_to_srgb`. Its output bytes are unchanged.
- The build records the linear fill colour under the transparent texels as `beard`/`brows` → `atlas_fill_linear` and `card_fill_linear` in `character.stats.json`, so the PNG can be read back and checked against it.

**Retune** (`config.py`; `direction.json` overrides none of these, and neither does the private overlay). The gains were compensating for the bug, so they are set to 1 and the atlases carry the configured swatch colours:

| Setting | Before | After |
|---|---|---|
| Beard shells `albedo_gain` | 1.6 | 1.0 |
| Beard shells `saturation` | 0.8 | 1.0 |
| Beard shells `grey_gain` | 1.0 (now a no-op; the key stays as a knob) | 1.0 |
| Brow shells `albedo_gain` | 1.8 | 1.0 |
| Brow shells `saturation` | 0.85 | 1.0 |

The cards and the lash strip never had a gain.

**Read-back** (`t2_glb_check.py atlas`; JSON in `data/build/t2/atlas_before.json` and `atlas_after1.json`). The transparent texels hold exactly the recorded fill colour:

| Atlas | Fill (linear) | Expected sRGB bytes | Before | After |
|---|---|---|---|---|
| beard_atlas | 0.0773 0.0658 0.0596 | 79 73 69 | 20 17 15 (= linear × 255: the bug) | **79 73 69** |
| beard_cards | 0.0540 0.0463 0.0420 | 66 61 58 | 14 12 11 | **66 61 58** |
| brows_atlas | 0.0147 0.0088 0.0058 | 32 23 18 | 4 2 1 | **32 23 18** |
| brows_cards | 0.0121 0.0073 0.0049 | 29 21 15 | 3 2 1 | **29 21 15** |
| eyelash strip | `#2a1f17` | 42 31 23 | 6 3 2 | **42 31 23** |

The hair texels (alpha ≥ 0.5) are now close to the swatches. The table gives the stored colour at the median luminance, and the number of distinct red byte levels:

| Atlas | Before | After | Target swatch |
|---|---|---|---|
| beard_atlas | `#140c09` | **`#423024`** | `#3e2e23` (melanin 0.98) to `#30241b` (1.0), × root shade 0.8–1 |
| brows_atlas | `#070403`, 66 levels | **`#211913`**, 101 levels | `#2a1f18` (0.97) to `#1e1712` (1.0) |
| brows_cards | `#040202`, 18 levels | **`#1f1813`**, 62 levels | same |
| eyelash strip | `#050302`, 4 levels | **`#241a13`**, 14 levels | `#2a1f17` × root shade 0.6–1 |

The linear mean of the hair texels rose 4.2× for the beard shells and 7–13× for the brows and lashes.

**Look** (EEVEE, the GLB):
- `data/build/t2/closeup_before_after.png`: left before, right after.
- `eye_before_after.png`
- `face_front_before_after.png`
- `mouth_before_after.png`

The brows are now dark brown hair instead of a flat black bar. The lashes are near-black brown. The beard is no longer a near-black mass. read40 still passes: beard contrast 88 % → 76 %, and the eye band is 60 % → 59 %.

**Art-direction flag.** With the atlases correct, the game beard now reads clearly **salt-and-pepper grey**, mostly at the chin. The configured grey is large and light: grey share 17.7 % overall and 45 % at the chin, with the grey swatch at `#948e86`. Grey strands carry about half the beard's linear mean. Before, the bug crushed the dark strands far more than the grey, so the old game read hid this. If the beard should read darker, change the tone settings (`tone.grey_*` or the grey swatch), not the gains. The hero strands were not re-rendered: that needs the hero rig, which is out of scope for this track.

## 2. Trousers shipped the jacket's AO

**Cause.**
- `suit_textures.apply` built the trousers' material (`wool_b`) by copying the jacket's material after the jacket's maps had been wired into it.
- `attach_surface` relinked the copy's base colour and roughness to the trousers' maps. But the copy kept the jacket's "glTF Material Output" group, with occlusion still linked to the jacket ORM's R channel, sitting beside the new group.
- The exporter used the stale group and merged the two maps into `suit_wool_a_orm-suit_wool_b_orm`.

**Fix.** Before any group is wired, `apply` takes an unwired snapshot of the wool material. Groups without their own material copy that snapshot, and the snapshot is removed at the end.

**GLB check** (`t2_glb_check.py materials`):

| | Material | Metallic-roughness | Occlusion |
|---|---|---|---|
| Before | `suit_wool_b` (trousers) | `suit_wool_a_orm-suit_wool_b_orm` | `suit_wool_a_orm-suit_wool_b_orm` |
| After | `suit_wool_b` | **`suit_wool_b_orm`** | **`suit_wool_b_orm`** |

The jacket (`suit_wool_a_orm`) and the vest (`suit_vest_orm`) are unchanged.

Pixel check:
- Before, the trousers' ORM R channel was byte-identical to the jacket's ORM R.
- After, it is the trousers' own (mean |Δ| 2.4 levels against the jacket's).
- Roughness and metallic (G and B) are byte-identical to before.
- The jacket's ORM is byte-identical to before.

`data/build/t2/trousers_orm_R_before_after.png` shows the two contrast-stretched. The left half (before) is the jacket's sleeve and body layout; the right half is the trousers' legs, with the knee folds.

## 3. Shoes vertex order not build-stable

**Cause.** `suit_shoes.py` deleted the toe-tip vertices with `for v in set(tip)`, which runs in address order. bmesh reuses freed slots for later `verts.new()` calls, so the order of every vertex created after that point changed from run to run.

**Fix.** `dict.fromkeys(tip)`. The back-stay loop over `set(up.rows[k])` also changed to `dict.fromkeys`; it only moves coordinates, but now it follows the same pattern.

**The rest of `blender/` was swept for the same class of bug.** Every remaining `set` iteration is one of:
- over ints or tuples, which is deterministic;
- feeding `bmesh.ops.delete`, which deletes in mesh order whatever order it is given;
- order-free, such as `f.smooth = True` or membership tests.

**Determinism check** (`t2_glb_check.py same`). `data/build/t2/same_after1_after2.txt` compares after1 with after2: every mesh in the GLB (all 16) has identical POSITION, NORMAL, TEXCOORD_0, JOINTS_0, WEIGHTS_0 and indices, `Human.suit_shoes_export` (3,260 verts) included.

`same_before_after1.txt` compares the before build with after1:
- Only the shoes differ.
- 20 of 2,344 rows are in a different slot. The vertex set and the triangle set are equal, so it is a pure reorder.
- Every other mesh is identical.

Comparing main10 with before for the shoes also showed a reorder (39 rows), but main10 was built from older code, so that is only consistent with the bug, not proof of it.

## Left over

- **GLB bytes are not yet identical across builds.** Of all the images, only `skin_head_normal` (11 px) and `skin_hands_normal` (7 px) differ, by ±1 level. This is probably float or threading noise in the skin normal bake. The meshes and all other textures are identical. This is not in T2's scope.
- **The game beard reads greyer** now that it is correct. This is the art-direction call flagged in §1.
- The other §1.8 / §1.9 items were not touched. They include the lapel weight wipe, the `suit.post` `for … else` misbinding, the drape cache key, and the cap UV seam.
