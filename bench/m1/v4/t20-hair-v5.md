_SwiftShader only: every engine frame here is WebGPU in headless Chromium on the CPU (port 8798, CPUs 0-3, a shared machine at load 25-40). Track T20 (hair v5 cards), m1 v4, 2026-10-15. Brief: `checkpoint-3.md` §2.3 and the T20 row of §4. Public build only. TRAA with hashed hair alpha is the primary path; the MSAA / A2C path (`?aa=msaa`) is gated alongside it._

# m1 v4 track T20: hair v5 cards

## The pictures (`data/build/t20/gate/`)

Every panel is a 100 % crop of a 1024² frame. "before" is the base build (main + T22 + T13A, `20261014T220131Z-t20-base`) under main's viewer; "after" is `20261015T012639Z-t20-f2` under this branch's viewer. Cycles is the hero strand groom on the same camera and studio lights.

| File | What |
|---|---|
| `t20_tq_base_f2_cycles.png` | ¾ head camera (T15's), studio lights, AgX: before \| after \| Cycles hero |
| `t20_profile_base_f2_cycles.png` | profile head camera: before \| after \| Cycles hero |
| `t20_closeup_hero_base_f2.png` | `closeup:hero` (T10's hero-rig closeup): before \| after |
| `t20_closeup_studio_base_f2.png` | lookdev closeup, studio lights: before \| after |
| `t20_iou_tq_base_f2_profile_base_f2.png` | silhouette overlays, ¾ base, ¾ after, profile base, profile after. Red is hero-only, green is game-only, grey is both |
| `t20_dirocc_default_nodeep_dirocc.png` | gameplay-tier occlusion, closeup at 512: deep shadow (default) \| deep shadow off \| deep shadow off + `hair.dirOcclusion` 1 |

**My read of these frames at 100 %.**
1. The hair is now a dark brown mass with a lit, warm rim on the lengths, close to the Cycles value structure; before, it was a uniform light-brown straw. It still lacks Cycles' soft gradient: the profile lengths show mottled grey-brown patches where the hero is a smooth dark brown.
2. Individual cards are still readable in places. The front falls beside the face read as dark strips. A row of dark, pointed card ends sits along the hairline at the temple. So the "no single card readable as a ribbon at 100 %" test fails.
3. The silhouette now sits on the hero's at ¾ (IoU 0.902). Over the shoulder in profile, the lengths still stop about 4–5 cm short of the hero's sparse tips. The narrow outer cards and one-strand fly-aways do break the contour into strands.

## Before → after

| Metric | Target | Before (base) | After (f2) |
|---|---|---|---|
| Engine / Cycles luminance, crown (TRAA) | 0.85–1.15 | 0.954 | **0.894** ✓ |
| … side | 0.85–1.15 | 1.824 | **1.114** ✓ |
| … back | 0.85–1.15 | 1.294 | **1.122** ✓ |
| … front falls | 0.85–1.15 | 1.157 | **0.917** ✓ |
| Engine / Cycles r/g, crown / side / back / front (TRAA) | 0.85–1.15 | 1.242 / 1.057 / 1.059 / 1.296 | **0.967 / 0.995 / 0.867 / 0.959** ✓ |
| Same, MSAA path, luminance | 0.85–1.15 | — | 0.933 / **1.273** / **1.240** / 1.035 ✗ (side, back) |
| Same, MSAA path, r/g | 0.85–1.15 | — | 0.964 / 0.982 / 0.867 / 0.963 ✓ |
| Silhouette IoU, ¾ | ≥ 0.90 | 0.8703 | **0.9019** ✓ |
| … profile / front / lookdev closeup | report | 0.8408 / 0.8552 / 0.8429 | 0.8587 / 0.8780 / 0.8749 |
| T10 closeup parity per light, key / fill / rim (TRAA) | 0.8–1.2 | 0.991 / 1.166 / 0.984 (T16) | **0.985 / 0.959 / 0.882** ✓ (all lights 0.914) |
| … MSAA path | 0.8–1.2 | — | **0.956 / 0.912 / 1.057** ✓ |
| Hero hair r/g, portrait crop PNG | ≤ 1.412 | 1.393 (T15) | 1.386 (not re-rendered: see below) ✓ |
| Hair test p10 | ≥ 0.0314 | 0.0328 (T15) | **0.0412** ✓ |
| Hair triangles | 45–55k | 28,448 | **45,972** ✓ |
| Character LOD0 | ≤ 170k | 147,442 | **166,370** ✓ |
| glTF errors | 0 | 0 | **0** ✓ |

How the numbers were taken:
- **Region tones and IoU.** `bench/m1/hair_views.sh` (T15's measure), unchanged: hero region masks, game alpha ≥ 0.5, region pixels eroded 2 px inside the game mask, all four head views pooled. The after-frames are TRAA at 8 still frames (`hair_views` re-shot with `?params={"aa":{"stillFrames":8}}`, because 24-frame stills took 10–20 min each on the shared CPUs). They were not compared against a 24-frame capture: region means over 10k+ pixels should be insensitive to the accumulation length, but that is an assumption. The MSAA row is the same capture with `?aa=msaa` (`hair_test.py --parts views_measure --engine-prefix msaa_`, key `views_msaa`).
- **T10 parity.** `lookdev_report.py hairparity` on the lookdev closeup, Cycles per-light references from `hair_test.py --parts parity --parity-lights key,fill,rim` on this build. TRAA at the default 24 frames.
- **Hero r/g.** The hero groom and its shader are untouched (`hair_groom.py`, the groom config and the strand shader have no diff against main), so the number is the latest hero portrait on main's groom (T18's `20261014T230104Z-t18-nosss`, `/tmp/t12/hairrg.py` boxes): 1.386. I did not spend a Cycles portrait on an unchanged groom.
- **Determinism.** Two builds of the same commit (f2, and m1 after merging main's T13) give identical IoU to four decimals in every view and third: the per-card generators (below) make the groom-to-card assignment stable, so one build is enough per step.

## Why the engine hair was 1.2–2× Cycles

Ruled out first (numbers from the base and a4 builds):
- **Colour space, mips, KTX2 tags.** The coverage-weighted mean card colour is constant within 1.5 % from mip 1 to 5; the tags are correct.
- **See-through.** 98–99 % of region pixels have game alpha ≥ 0.98, and opaque-only pixels give the same ratio.

What it was (per term and per studio light, each lobe rendered alone on the region masks against a Cycles frame per light):
1. **A Lambertian body the hero does not have.** Under the studio lights the Cycles hero takes 1–5 % of its crown / side / back light from the key and 93–96 % from the rim. Near-black Chiang fibres scatter almost nothing diffusely. The engine's albedo diffuse (gain 1.3) made the key the engine's main light on those regions. Every fit on the v5 basis put this term at 0.
2. **A unit-luminance tint on TT and scatter.** It gave a near-black strand the glow of a grey strand, in a dark strand's hue. That is the side region's 1.3× from TT alone and the front falls' 1.23× r/g. These terms now use the strand's own fibre transmittance, exp(−ttDepth (ln c)²), from the atlas albedo (Chiang: c = exp(−√(σ path)·fac), so a pass of about two radii transmits exp(−2σ)).
3. **The card albedo was lightened.** `path` 0.68 lightened every strand (the near-black ones about 4×) as a stand-in for multiple scattering. Now `path` is 1.0, the hero shader's own mapping, and the multiple scattering comes from item 2.
4. **R without Fresnel.** At the rim's grazing angles a fibre's R is about 4× its normal-incidence value. The engine's Kajiya R had no such rise, so fits pushed every other term up to light the rim regions. R now carries Schlick's Fresnel (IOR 1.55).
5. **T10 fitted its lobes on a holey mask.** T10's parity mask had coverage holes that T15 filled. With identical lobes, parity went from 1.07 to 1.38 (×1.29) once the holes were filled.

The fit: the per-term, per-light basis on the v5 cards (a2 build, 4 views × 3 lights × 5 terms) gives the gains. Albedo diffuse 0; fibre-tint scatter 0.024; R 0.031 with Fresnel; TT 1.62. Front-fall specular scale is 0.8 (was 0.4); the T9 white-ribbon problem it guarded against came from the old light albedo. TT went from the fitted 1.08 to 1.62 to bring the T10 rim closeup from 0.69 to 0.90 under TRAA. The per-region fit cannot do better than about ±19 % across the four regions: rim-lit crown and back respond 1.45× differently in the engine than in Cycles. Neither the deep shadow (off: ≤ 3 % change) nor the root AO (off: ≤ 3 %) is the cause. The measured TRAA result above landed inside ±15 % anyway.

## What changed

**Cards** (`blender/character/hair_groom_cards.py`, baker "v5 (T20)"):
- **Outer layer.** 402 narrow twisted cards, half-width ≤ 4 mm, each from a group of 10 of a top clump's outer strands. There are at most 2 per clump, on 16 baked 32 px cells, with a twist of 8–50° root to tip (random sign and phase) and 8 segments.
- **One-strand fly-aways.** 60 of them, on 4 one-strand cells at 0.55 cover.
- **Baby hairs.** 90 one-strand cards on single hairline edge strands, spread ≥ 3 mm apart, 8–18 mm long, the tip lifted 1.5 mm. They are 1.2 mm wide on a 16 px cell, about 0.075 mm per texel.
- **Bent normals.** Each card row's edge vertices lean 55° outward from the smoothed proxy normal (a half-cylinder), written as custom split normals.
- **Directional occlusion.** Baked per vertex from the groom: voxel strand density at 4 mm, the optical depth toward ±x, ±y, ±z, and an L1 fit (mean + gradient) packed into 4 × 6 bits in TEXCOORD_1 y. Two extra UV sets would have put the hair mesh at 10 vertex attributes, over WebGPU's 8 vertex buffers, and the frame rendered black; that is how a1 / a2 failed in the engine. `hair.dirOcclusion` 1 applies it per light (gameplay tier, deep shadow off). At k 0.15 it darkens the back lengths 16 % more than the deep shadow does (`t20_dirocc_*.png`); k ≈ 0.1 would match.
- **Silhouette.**
  - The cap is pulled behind the hairline: its coverage fades in over 6–18 mm from its open edge. Its strands, projected flat onto the scalp, drew a dense fringe ahead of the hero's hairline.
  - Under cards are kept off the neck: their hanging part rides the members' 70th-percentile outward offset.
  - Cards run to the 90th percentile of their strands' lengths (was 80), and outer cards to the 95th.
  - The cap's strands use a physical alpha.
- **Staggered strand roots.** Each strand fades in from its own start, spread over 8 mm. A card's narrow root end had drawn a solid tooth.
- **Hairline cells.** Drawn at 0.6 cover.
- **Stable per-card randomness.** Each card's random choices come from its own generator, keyed by its clump, group or strand id. A parameter change to one layer no longer reshuffles the others.

**Viewer** (`materials/index.ts` hair class, `params.ts` hair block): the fibre transmittance (`hair.fibreTint`, `hair.ttDepth`), Fresnel R (`hair.fresnel`), the packed occlusion decode in the vertex stage (`hair.dirOcclusion`), and the refit gains above. The alpha / coverage code (T16) is untouched.

**Tools.**
- `hair_test.py --views-lights key,fill,rim`: Cycles frames per studio light, for the per-light fit.
- `hair_test.py --views-game-only`: game masks only; IoU against a kept hero mask in about a minute.
- `hair_views.sh` passes `VIEWS_ARGS`.

## Not met, and what is left

- **The ribbon test fails.** Three tells remain at 100 %:
  - the front falls are dark strips;
  - pointed dark card ends sit along the temple hairline. Pulling the cap, the hairline cover at 0.6 and the staggered roots softened them, but did not remove them; they are the top / outer cards' root ends where the hero's strands stand off the scalp;
  - the profile lengths are mottled, probably the grey strands' fibre transmittance at the sharper mip.
- **Lengths over the shoulder.** In profile the lower third still loses about 14k hero pixels; the profile IoU is 0.859. Neither longer cards (p80 → p90) nor dropping the jacket holdout changes it: the cards' tips curl back off the shoulder where the hero's sparse tips hang straight down. That needs work in the hang / collision of the card centrelines, not their length.
- **Sideburn continuity: not done.** The hero groom has no sideburn either: the temple hair ends above the ear and the beard starts below it in the Cycles hero. Joining them changes the hero, which belongs with T21's beard sideburn cards.
- **MSAA path: side and back miss.** The side is 1.27× and the back 1.24× Cycles (r/g in range; T10 per-light parity passes at 0.96 / 0.91 / 1.06). The gains were fitted under TRAA, the primary path. A2C's opaque card edges show more of the rim-lit TT than TRAA's hashed coverage does: the same frames were 1.03 / 1.21 at TT 1.08. A second gain set behind `?aa=msaa` would fix it, if the MSAA path stays a gate.
- **Per-light structure.** The engine's crown / back relative response to the rim is 1.45× Cycles'. The pooled regions pass, but a lighting change (T19's per-light balance) may move them; re-run the region measure when T19 lands.

## Run dirs

- **base:** `data/build/lookdev/20261014T220131Z-t20-base`.
- **after (the gate build):** `data/build/lookdev/20261015T012639Z-t20-f2`, which holds `hair_test/hair_test.json` (`views`, `views_msaa`, `parity`, `test`), `hp_t20.json` (TRAA parity) and `hp_t20m.json` (MSAA parity).
- **after, merged with main's T13:** `…/20261015T020101Z-t20-m1`. It is identical: 166,370 tris and the same IoU.
- **The per-term basis:**
  - `data/build/t20/a2v`: `L<term><light>_<view>.png`, plus the `Z` (root AO off) and `Y` (deep shadow off) sets;
  - the a1 per-light Cycles frames are in `…/20261014T223758Z-t20-a1/hair_test`.
