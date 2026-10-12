# m1 v2 skin direction (Fable consult, 2026-10-13)

_Strategy consult on why the face skin still reads as CG at portrait distance, and what to do. Binding for Track A (skin) and Track E (lighting and grade); deviations go in the track report._

## Why it reads as CG at 85 mm (ranked)

1. **The specular is one continuous sheen.** A 0.8 m key at 1.5 m (about 30°), combined with roughness 0.4–0.5, averages away the pore and cross-hatch relief. The rake test proves the relief exists. This is a lighting problem first.
2. **No mid-frequency surface (2–20 mm).** Missing:
   - orange peel: 2–4 mm cells, 0.05–0.1 mm deep;
   - subdermal lumps: 6–15 mm, 0.15–0.3 mm;
   - follicle and sebaceous bumps;
   - rolled shoulders beside the lines.

   Because nothing else is there, the 0.5 mm cross-hatch reads as woven linen.
3. **One hue.** The albedo mottle is luminance-only. Missing:
   - haemoglobin blotching at 5–15 mm;
   - melanin drift at 20–50 mm;
   - a desaturated violet under-eye.
4. **No visible SSS at the terminators.** The big soft key and the AgX Medium High Contrast look flatten it.
5. **Value structure.** Broad lighting gives no half-tones and no nose or core shadow.
6. The under-eye bag edge catches a bright streak.
7. **No peach fuzz.** The skin silhouette is a hard edge under the rims.

## Approaches (ranked gain per effort)

1. Lighting: a small key plus a soft wrap, short lighting, and exposure (Track E). Do this first; judge everything else under it.
2. Hero-only mid-frequency displacement through adaptive subdivision, with the normal baked into the game 4k map (Track A). It doesn't touch the topology or UVs.
3. Chromatic two-layer albedo: melanin and haemoglobin fields (Track A).
4. Hero-only vellus hair (Track A, with C's groom tools).
5. Grade: AgX base, contrast through CDL, saturation 0.97, WB 3800–4000.
6. Under-eye edge: −0.15 mm hero displacement, not a forms change.
7. Texture sources: no verified CC0 or CC-BY skin micro-detail set exists, so procedural stays the path. The Blender Studio *Charge* files (CC-BY) are an unverified lead.
8. CPU diffusion tiles: lowest priority; only if the procedural haemoglobin looks too Perlin.

## Action list

**Track E (first):**
1. Key: 0.3 × 0.3 m at 1.5 m, ratio 1.0, azimuth 55° camera-left (short lighting on the ¾ face), elevation 30°.
2. Wrap: 1.5 × 1.5 m, ratio 0.25, azimuth 35°, elevation 10°, same colour as the key.
3. Fill stays at 0.08. The magenta rim grazes the jaw and cheek edge (azimuth −125°, elevation 20°).
4. Eye light 0.08, 5 cm (a hard catchlight point).
5. Exposure: lit cheek 0.50–0.55 display, shadow cheek 0.12–0.18. WB 3900. AgX base look, contrast +15 % via CDL power 1.08, saturation 0.97.
6. Focus: eye centre + 12 mm, f/4.

**Track A:**
1. `skin_synth`:
   - Haemoglobin field: noise 90/m, detail 2, threshold 0.55. Weight 0.12 on the cheeks, nose, centre forehead and neck; 0.04 elsewhere. It acts on G and B only: albedo ≈ base × (1 − hb × (0, 0.10, 0.12)).
   - Melanin field: noise 30/m, ±6 %, tint (1.02, 1.00, 0.95).
   - `ao_in_albedo` 0.10; hero `plane_paint` 0.
2. Hero displacement, mid band:
   - Lumps (noise 120/m, detail 1): 0.25 mm on the cheeks, 0.15 mm on the forehead, 0.3 mm under the eye.
   - Orange peel: Voronoi F2−F1 at 350/m, distortion 1.5, anisotropic 1.5:1 along the Langer lines, 0.07 mm.
   - Line shoulders: +0.08 mm over 1.5 mm on each side.
   - Nose tip and alar bumps: 0.6 mm cells, 0.06 mm.
   - Lip ridges: 0.12 mm at 0.8 mm spacing, with 1.5 mm lateral bumps.
3. Cross-hatch: `micro_mm` 0.035 → 0.025, `micro_break` 0.7 → 0.5.
4. Under-eye edge: −0.15 mm hero displacement.
5. Vellus pass (hero only): about 20k strands, 0.8–2 mm long, radius 0.008 mm, melanin 0.1, on the cheeks, forehead, jaw and ears.
6. Bake the mid-band normal into the game 4k map, then re-run the spec guards.
7. Re-render shot 1, the 135 mm close-up and the turntable under the new rig, then repeat the rake test.

## Pass criterion (shot 1, 1920×1080, face ≈ 450 px tall, graded)

- **Specular:** the top 5 % of T-zone luminance forms ≥ 4 disconnected components on the forehead and ≥ 3 on the nose dorsum. No highlight is longer than 25 px.
- **Mid-frequency:** in a 120×120 px cheek crop with structure above 40 px removed, luminance std is 1.5–3 %, and Lab a* std is ≥ 1.5 at the 8–30 px scale.
- **Colour:** mean hue differs by ≥ 5° between forehead, cheek apple and chin. The under-eye is less saturated than the cheek.
- **SSS:** the cheek terminator and nostril wing shift ≥ 6° in hue toward red; the ear rim transmits under the rim light.
- **Honesty:** the same metrics hold at ≥ 60 % strength on the turntable bust.
- **Human gate:** no skin "CG tell" within 3 s at full resolution.
