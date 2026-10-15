# H2: hair v5b (ribbon read, lengths, MSAA path, portrait crown)

> **SwiftShader only.** Every engine number here is WebGPU on SwiftShader (headless Chromium, CPU), not a GPU.

_Draft; in progress. The pickup list at the end is the state._

## Pickup list

- Branch `worktree-agent-a6c98b48769440b0d`; main f9d9069 (T25) merged at 3463c4b.
- Groom changes (`blender/character/hair_groom_cards.py`): `front_groups` (the front falls as 2 layers x ~12 uneven groups, per-strand alpha, tip fade, twist), `root_fade` (COLOR_0 alpha root fade of cards rooted near the hairline), `sec_twist_deg`, 120 single flyaways. `hair_strand_raster.card_material(vertex_alpha=)` routes COLOR_0 alpha into the BSDF alpha so the exporter writes VEC4.
- Engine (`web/src/character/materials/index.ts`, additive): `hair.vertexAlpha` (COLOR_0 alpha x coverage on the TRAA hash, the MSAA A2C and the depth prepass), `aa.msaaHairCoverage` (MSAA: fractional coverage instead of the A2C step).
- Bench: `hair_test.py` back view (az 180) and `length` (tip line vs the hero in profile / back / ¾); `hair_views.sh` ENGINE_QUERY; `engine_shots.mjs --texcount`.
- Run dirs: base `lookdev/20261015T094649Z-h2-base`, a2 `...102355Z-h2-a2`, a3 `...105245Z-h2-a3`.
- Next: crown / back on the T25 rig (per-light: Cycles `data/build/h2/lights_a3`, engine `data/build/h2/eng_a3`), then hair views + MSAA on the final, texcount, turntable, read40, report.
