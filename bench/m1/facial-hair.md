# m1 facial hair: shell-textured beard and brows

The direction check rejected the beard as implemented (a thick, jagged, pitch-dark card mass with a bare ring around the mouth, chunky tufts at the cheek line, no individual hairs). This pass replaces it with **shell texturing**, the standard short-fur technique, and replaces the MPFB stopgap eyebrow cards with the same method. The grooming target is the spec's short, dense-but-scruffy full beard (0.5–1.5 cm, longer at the chin, cheek line fading through stubble, moustache blending into the beard at the corners and overlapping the lip edge, connected soul patch, neckline fading under the jaw) and dark, heavy, slightly unruly brows. The face itself is untouched (NOTES §3, §14 rule 7).

| File | What |
|---|---|
| `blender/character/facial_hair.py` | The shell generator: field smoothing, patch decimation, atlas texture, shell stacking, material. Shared by the beard and the brows. |
| `blender/character/hair_beard.py` | Beard region (landmark lines, nose and lip rules) and its fields: density, stubble length factor, hair length, comb direction. |
| `blender/character/brows.py` | Brow band from the fitted MPFB eyebrow proxy, its fields, and dropping the proxy from the export. |
| `blender/character/config.py` → `hair.beard`, `hair.brows` | All parameters. |
| `blender/character/hair.py` | Calls both after the scalp hair (`post`). |

The scalp hair (`hair_clumps.py`, `hair_mesh.py`) is unchanged; `hair_mesh` still supplies the body-derived patch, boundary relaxing, materials and skinning. The beard section of [`hair.md`](hair.md) describes the superseded card beard.

## How the shells work

1. **Base patch.** Skin faces of the staged body selected by the fields below, so the patch keeps the body's skin weights (`head`, `neck_01`; ≤ 4 per vertex). The open boundary is relaxed along the skin, then the patch is **collapse-decimated** to `base_tris` (700 beard, 160 brows) with the per-vertex fields carried through as attributes and the result snapped back onto the skin. N shells cost N × base tris, so this is where the budget is set.
2. **Shells.** The patch is duplicated `layers` times (20 beard, 10 brows; 156–160 base tris for the brows). Shell *i* sits at t = i / N of the local hair length `L(v)`, displaced by `L (n (t − lean t²/2) + comb · lean t²/2)`: the integral of a direction that turns from the skin normal toward the per-vertex comb direction, so hairs rise and lie down (`lean` 1.0 beard, 1.5 brows). UV1 `u` holds t per vertex.
3. **Atlas.** One generated RGBA image; tile *i* is the alpha-tested cross-section of the hair field at height t. Hairs are scattered on a jittered grid (`spacing_px`), kept with probability `density` (rasterised from the patch's density field), with a length (× the rasterised stubble factor), a lognormal value, a radius that tapers toward the tip and is thinner for short hairs, a sideways drift (random plus a share of the comb direction) so each hair bends its own way, and a dash **elongated along that bend** so the dashes of consecutive shells overlap into one strand instead of a row of dots. Colour darkens toward the root (`root_shade`), the self-shadow that gives the mass depth.
   - Beard: cylindrical projection around the head axis into 1024 × 512 tiles (≈ 0.33 mm per texel), 20 tiles in a 4096 × 2560 atlas, ~13k hairs. Brows: planar (x, z) into 512 × 128 tiles, 1024 × 640 atlas, ~1.1k hairs.
   - Every shell material exports as glTF `alphaMode: MASK` through `export.fix_alpha` (`beard_export`, `brows_export` in `b.cutouts`); EXTEND sampling, so tiles never bleed across the atlas.
4. **Validity guards** (`facial_hair.clean_patch`, `guard_tangents`). Before stacking, coincident base vertices are welded (0.02 mm) and faces degenerate in 3D or in the tile projection are culled. After the mesh is finished, Blender's own mikktspace pass (the one the glTF exporter runs) is checked: a loop whose tangent comes back zero (a shell folded edge-on over a crease, e.g. where the lip-edge hairs turn down harder than their neighbours on the tamed face-C nose) has its vertex nudged 0.2 mm along the normal and is re-checked; after two nudges the face is deleted. Stats: `welded_verts`, `culled_degenerate_faces`, `tangent_nudged_loops`, `tangent_culled_faces`. On the fidelity-merge main (`25bebf6`) the beard needed one nudge on face C and the validator is back to 0 errors on `direction.json`, `face-a.json` and `face-b.json`.
5. **Runtime path.** The per-shell atlas exists so the look-dev GLB carries the look with a stock material. The runtime TSL shader needs only tile 0's hair field plus the per-vertex height (UV1 `u`): `alpha = length_tex(uv) ≥ t`, which also makes alpha-to-coverage and a proper hair BRDF straightforward. The 4096 × 2560 atlas (~5 MB in the GLB) is a look-dev cost, not a ship cost.

## Beard fields (`hair_beard.py`)

- **Region**: the cheek line (sideburn → dip under the cheekbone → 12 mm above the upper lip at the mouth corner) and the neckline (55 mm under the ear → 8 mm under the chin), as before, as signed depths in profile, with a ±4 mm wobble. New rules, because profile lines ignore x:
  - In front of the mouth corners the beard is capped at the **moustache top** (`moustache_height_m` 12 mm over the upper lip), with its own narrow stubble band (3 mm).
  - Skin above the lips and more than 4 mm **in front of the lip front is the nose**: excluded.
  - The vermilion (`lips` group) is out of the patch; nothing else keeps hair off the lips. The moustache's lower edge and the hair under the lower lip grow from the vermilion border and lean down over it (comb turns down within 6 mm of the lips), so the bare ring is gone and the soul patch connects.
- **Density**: 1 inside, `x²` across the band from `fade_m` (8 mm) inside the line to the patch edge (`margin_m` 9 mm past the cheek line, 9 mm past the neckline, 6 mm behind the sideburn). The band's hairs also shorten (`stubble_short` 0.25 at the edge) and thin (`short_thin`), so the cheek line fades through fine stubble rather than ending in flecks.
- **Length**: cheeks and moustache 7–8 mm, jaw 10 mm, chin +6 mm (Gaussian, r 30 mm), under the jaw 8 mm, × 0.8 at the lips.
- **Comb**: down and slightly back on the cheeks, down and forward at the chin, back toward the throat under the jaw, sideways from the philtrum plus down on the moustache; projected onto the skin and smoothed twice.
- **Colour** `#2a1d14` × lognormal value (σ 0.45): near-black with visible dark-brown strands, never flat black.

## Brow fields (`brows.py`)

- The MPFB `eyebrow001` proxy is still fitted by `head.add_parts` (it follows the head track's brow edits) and used as the **landmark**: its vertices snapped to the skin give, per side and per x bin, a linear fit of z over x (so the arch's slope does not count as thickness), a centre and a half-height, smoothed across bins and clamped to 2.5–4.5 mm. The proxy is then removed from the export.
- Patch: head-group skin within the band + 2.5 mm, within the proxy's x range + 3 mm, on the face front. Density: full in the core (|dz| < 0.5 hh), feathered to the band edge, denser inner third, the tail thinning to nothing over the outer 55 % and its band narrowing by 45 %.
- Length 5 mm (× 0.7 at the tail), lean 1.5 (flat), comb outward with an upward component near the nose and a slight downward turn at the tail; upper-edge hairs turn down and lower-edge hairs up.

## Numbers (face C + collar, `direction.json`)

| | Before `20261012T104624Z-fh-baseline` | After `20261012T111535Z-fh-final` |
|---|---|---|
| Beard tris | 5,918 (shell 1,758 + 520 tuft cards 4,160) | **14,000** (20 shells × 700) |
| Brows tris | 192 (MPFB proxy cards) | **1,560** (10 shells × 156) |
| Facial hair total | 6,110 | **15,560** |
| LOD0 total | 61,945 | **71,407** |
| GLB | 12.4 MB | 17.4 MB (atlas; see runtime path) |
| `hair_post` | 2.8 s | 2.8–4.7 s |
| glTF validator errors | 0 | 0 |

Facial hair sits at the ~15k the direction brief allowed; LOD0 is well inside the 120k hero budget. Skin weights: shells inherit the body's (1–4 bones per vertex, `head` / `neck_01`).

Also checked on face A (`20261012T111224Z-fh-face-a`): the cheek line, neckline, moustache cap and nose exclusion all place from that head's own landmarks.

Sign-off (Cycles 1024², 128 spp): `20261012T111629Z-fh-final-signoff` (and `20261012T111319Z-fh-signoff` for the brows5 checkpoint).

## Iteration log (judged on `hair_inspect.py` sheets and 2× crops)

| Run (`data/build/lookdev/…`) | Change | Result |
|---|---|---|
| `…105711Z-fh-shell1` | first shells: 16 × 800 tris, dots, lean 1.2 | Already reads as hair out of skin; no bulk, no lip ring, soul patch connects. But stubble ran onto the nose and under the eyes (profile lines ignore x), the band dominated, hairs were specks (consecutive shell dots don't overlap), pure black. |
| `…110035Z-fh-shell2` | moustache cap for the nose, per-line margins, dashes elongated along each hair's bend, 20 × 700, warmer colour | Nose bare, neck fades above the collar, profile edge natural. Stubble still coarse black flecks. |
| `…110320Z-fh-brows1` | short hairs thinner, colour value up (σ 0.45), first brows | Beard value variation reads. Brows far too tall (bin z spread included the arch slope). |
| `…110543Z-fh-brows2` | linear-fit brow thickness, narrower band; moustache leans down more, cheek-line corner raised to meet the moustache top | Moustache full. Brows the right scale but sparse scribbles. |
| `…110745Z-fh-brows3` | explicit nose exclusion; brows denser | Specks off the nostril. Brows a solid black sticker with a square tail. |
| `…110920Z-fh-brows4` | brows finer, lighter roots, more drift, tail to zero | Brows read as hair, spiky top edge, asymmetric tail bump. |
| `…111102Z-fh-brows5` | spine smoothed and clamped, drift biased to the comb | Dense, straight, slightly unruly brows. Committed checkpoint. |
| `…111535Z-fh-final` | brow band narrows toward the tail (×0.55 at the end) | Final: the tail flap is gone. |

## Known limits and next steps

- **Shell stacking at grazing angles.** 20 shells over ≤ 16 mm is 0.8 mm per shell; at the chin silhouette in a close-up the stack can show as a fine sawtooth. More shells or a few silhouette cards at the chin would hide it; none were needed at the look-dev views, so the budget was kept.
- **Lip edge.** The moustache leans over the vermilion border geometrically, but with MASK alpha the overlap is a hard hair edge, not a soft one; alpha-to-coverage at runtime (look-spec §3.3) is the fix.
- **Nose rule is a plane.** "Above the lips and > 4 mm in front of the lip front" leaves a straight bare line along the nose-wing crease; it reads as the natural bare strip there, but a face with a much shorter or longer philtrum should re-check `moustache_height_m` and `nose_clear_m`.
- **Brow tail.** The proxy's outer end is a wide flap; the band narrows and thins to cover it. If the head track replaces the eyebrow asset, `brows.proxy` is the name fragment to update, or any thin strip mesh over the brows will do as the landmark.
- **Mip filtering.** MASK at the look-dev 512² views thickens hairs where the atlas is minified; at game distance the beard still reads as a dense beard and the brows as dark brows. The runtime shader's alpha-to-coverage handles this properly.
- **Skin under the beard** is untextured. A stubble shadow in the 4k skin (head track) would help the band's transition at distance, as `hair.md` already noted.
- **No per-strand specular / Kajiya-Kay** yet: look-dev Principled, roughness 0.75, specular 0.2.

## Reproduce

```sh
bench/m1/lookdev.sh --prev none --config bench/m1/variants/direction.json facial-hair
blender -b -t 4 --factory-startup --python bench/m1/hair_inspect.py -- data/build/lookdev/<run>
bench/m1/lookdev.sh --signoff --config bench/m1/variants/direction.json facial-hair-signoff
```
