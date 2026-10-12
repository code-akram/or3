# m1 look spec: the character the look-dev loop is scored against

_Written 2026-10-12 (m1 wave 1, track C). The contract for the m1 look-dev loop (NOTES §7, §15 `m1`). Every target is tagged **[auto]** (the harness measures it) or **[visual]** (judged on the render set by the critic and the user). Targets marked *(cal.)* get calibrated at the direction checkpoint (§6)._

**Baseline** = the spike-1 build (`blender/build_character.py`, MPFB 2.0.18, macros gender 1.0 / age 0.55 / muscle 0.6 / weight 0.5 / height 0.6 / proportions 0.6). Body landmarks come from a **nude** build of the same macros, because the staged clothed body has its covered polygons deleted. Measured with [`look_spec_landmarks.py`](look_spec_landmarks.py) (§1.1 defines each landmark).

## 0. Design intent in one paragraph

A grounded, heroic adult man in his forties. He is lean and broad-shouldered, and he is still. The face is built from a few large, sharp planes: a heavy brow shelf that throws the eyes into shadow, high cheek planes, and an angular jaw under a short full beard. He wears long dark hair swept back off the face, a black three-piece suit cut close, a white shirt and a black tie. The style follows Sifu's two stated pillars: a *speed-painting approach to texture and volume simplification*, and a *cinematic approach to light and grade* ([Boucher, ArtStation](https://peboucher.artstation.com/projects/OmE5n6)). In Sloclap's words it is "sharp and stylized" ([Game Rant interview](https://gamerant.com/sifu-interview-sloclap-cultural-sensitivity-inspiration-brawler/)). **He is an original person.** The archetype is "the man in the black suit", never a specific actor (§2.4).

## 1. Proportions

### 1.1 Landmark definitions (the contract)

Coordinates: metres, world space, rest pose (MPFB A-pose), Z up, front = −Y. A vertex belongs to the bone with its largest deform weight. Helper and joint-cube vertices are excluded.

| Landmark | Definition |
|---|---|
| `stature` | Top-of-skull vertex z minus floor (soles at z ≈ 0), barefoot |
| `menton` | Midline (\|x\| < 6 mm) profile. The pogonion is the most forward point 8–15 cm below eye centre. The menton is the lowest midline point within 2.5 cm of the pogonion's depth. This skips the throat, which also carries head weights. |
| `head_height` | Vertex z − menton z |
| `heads_tall` | `stature / head_height` |
| `bideltoid` | Lateral extent of upper-arm and clavicle vertices no more than 6 cm down the upper-arm axis from the shoulder joint. This is independent of the A-pose angle. |
| `hip_breadth` | Widest pelvis or thigh section from 10 cm below to 2 cm above the hip joints. The A-pose spreads the thighs, so this reads about 5–10 % above a standing anthropometric hip breadth. |
| `shoulder_to_hip` | `bideltoid / hip_breadth` |
| `crotch_height` | Lowest midline body vertex above 0.5 m and below the hip joints |
| `leg_ratio` | `crotch_height / stature` |
| `suprasternale` | z of the clavicle bone heads (stand-in for the sternal notch) |
| `leg_to_torso` | `crotch_height / (suprasternale − crotch_height)` |
| `eye_z` | Centroid z of the eye meshes |
| `bizygomatic` | Head-mesh width at 80–90 % of the way from menton to eye_z, counting only vertices more than 5 cm in front of the head bone, so the ears stay out |
| `bigonial` | Head-mesh width at 30 % of the way from menton to eye_z (jaw angles) |
| `jaw_to_cheek` | `bigonial / bizygomatic` |
| `lower_face_index` | `(eye_z − menton) / bizygomatic` |

### 1.2 Targets

Reference values come from the ANSUR II male means (US Army 2012, n = 4,082): stature 1,756 mm, bideltoid 510 mm, biacromial 416 mm, hip breadth 346 mm. Source: [search summary of the public data](https://dimensionspot.com/blog/ansur-ii-military-anthropometric-database/); the official tables are in [Gordon et al. 2014, NATICK/TR-15/007](https://apps.dtic.mil/sti/tr/pdf/ADA611869.pdf), and I did not check them line by line. "Heroic" means about +1 SD in the shoulders, not a comic-book V.

| Measure | Baseline | Target | Tol. | Tag | Note |
|---|---|---|---|---|---|
| `stature` | 1.840 m | **1.85 m** | ±0.02 | [auto] | Barefoot; shoes add ~2.5 cm |
| `heads_tall` | 7.84 | **7.8** | ±0.15 | [auto] | Grounded heroic. Don't push to 8+: the head must read at game distance |
| `bideltoid` | 0.545 m | **0.56 m** | ±0.015 | [auto] | ANSUR mean scaled to 1.85 m is 0.538; +1 SD is 0.570 |
| `shoulder_to_hip` | 1.41 | **1.50** | ±0.04 | [auto] | ANSUR mean is 1.47 on standing breadths; ours reads low because the A-pose widens the hips. Raise the shoulders and narrow the hips; don't bulk the arms |
| `leg_ratio` | 0.490 | **0.49** | ±0.01 | [auto] | Already slightly long-legged; keep |
| `leg_to_torso` | 1.49 | **1.49** | ±0.05 | [auto] | Keep |
| `bizygomatic` | 0.139 m | **0.140 m** | ±0.006 | [auto] | |
| `jaw_to_cheek` | 0.84 | **0.87** | ±0.03 | [auto] | Squarer, angular jaw |
| `lower_face_index` | 0.86 | **0.88** | ±0.04 | [auto] | Slightly longer, leaner lower face |
| Brow overhang | not yet measured | **≥ 12 mm** | — | [auto] *(cal.)* | On the mid-pupil vertical: most forward brow point minus cornea front (y). The harness adds this. |
| Neck | — | Thick, short-looking; trapezius slope visible above the collar | — | [visual] | |
| Hands | — | Large, square, visible knuckles | — | [visual] | They hold a pistol on screen a lot |

**Levers, in order of preference:** MPFB macros (`muscle`, `proportions`, `height`), then MPFB measurement and shape targets (shoulder, hip, neck, jaw and chin targets in MPFB's `data/targets`), then lattice edits (§2.3). Once the user approves the direction checkpoint, the proportion numbers are frozen as regression guards.

## 2. Face

### 2.1 Plane breakdown (what the head edits build)

Sifu's surfaces read as *simplified volumes*: a few large planes with sharp transitions, and painted value inside each plane rather than modelled detail. Our planes:

| Plane group | Shape |
|---|---|
| **Forehead** | Two broad planes meeting at a soft vertical ridge, sloping back about 10° from vertical. Flat, not domed. |
| **Brow shelf** | The signature. A strong horizontal shelf, straight with a slight downward angle toward the nose (a resting stern set), overhanging the eye ≥ 12 mm. Its underside is a separate plane that holds the eye-socket shadow band in any top or key light. Compress the brow-to-lid gap. |
| **Eye sockets** | Recessed. The upper lid is slightly hooded and the aperture narrow, almond-shaped and level. The eyes are not large. |
| **Nose** | Long straight dorsum plane with crisp side planes (a hard edge where dorsum meets side), narrow bridge, angular tip. A slight dorsal hump is allowed. |
| **Cheekbones** | High. A defined **diagonal plane break** runs from the zygion down and in toward the mouth corner, with a sub-zygomatic hollow below it as a separate, slightly recessed plane. This is the main "planar" read at mid distance. |
| **Jaw** | Strong mandible. The jaw side plane meets the under-jaw plane at a crisp edge that the beard follows. Gonial angle about 115–120° (squarer than average). |
| **Chin** | Square, moderately projecting, mostly under the beard. Its front plane is flat. |
| **Mouth** | Straight line, thin-to-medium lips, upper lip slightly thinner. Neutral-to-stern at rest. |
| **Ears** | Mostly covered by hair. Keep MPFB's shape and shrink 5 % if they poke through. |

### 2.2 What reads at game distance

At the third-person camera (about 3–4 m) on the Air's ~1470 × 956 view, the character is about 300–350 px tall and **the head is about 40 px**. At that size only these read:
1. The **eye-socket shadow band** under the brow shelf.
2. **Beard mass against skin**.
3. **The hair silhouette** against the background.
4. The **cheek plane break** under a side or rim light.

Everything else (lip shape, nose detail, wrinkles) is for the close-up and cutscene camera only. It must be right, but it must not be what carries the read.

**40 px read test** [auto] *(cal.)*: render the ¾ view under the standard key light and downsample until the head is 40 px tall.
- The eye band must be ≥ 15 % darker (relative luminance) than the cheek plane.
- The beard must differ from the skin by ≥ 25 %.
- The hair silhouette must separate from a mid-grey background in the silhouette pass.

### 2.3 Parametric controls for the scripted head edits

These are low-dimensional so the best-of-N loop explores a small, meaningful space. They are implemented as **lattice deforms** (3 × 3 × 3 or 4 × 4 × 4, bound to vertex-group masks on the MPFB head) plus **MPFB face targets** where one exists. Each control is a scalar in [−1, 1] with a documented mm range, and all edits are mirrored.

| # | Control | Region (vertex-group mask) | Effect |
|---|---|---|---|
| 1 | `brow_depth` | Brow shelf, from the brow line to the upper orbit | Forward projection 0–8 mm |
| 2 | `brow_angle` | Brow shelf, medial vs lateral lattice points | Inner end down / outer end up, ±6° |
| 3 | `brow_flatten` | Same | Collapses the brow's vertical curvature toward one plane |
| 4 | `socket_depth` | Orbit and upper lid | Recess 0–4 mm |
| 5 | `lid_hood` | Upper lid | Lid fold down 0–2 mm |
| 6 | `nose_length` | Nose | ±5 mm |
| 7 | `nose_bridge_width` | Nose | ±2 mm |
| 8 | `dorsum_crease` | Nose | Sharpens the dorsum/side edge (edge-crease weight + plane snap) |
| 9 | `cheek_height` | Malar region | ±4 mm |
| 10 | `cheek_plane_break` | Malar and sub-malar | Flattens the two planes and sharpens their shared edge |
| 11 | `submalar_hollow` | Below the cheek line | 0–4 mm |
| 12 | `jaw_width` | Gonial region | ±6 mm per side |
| 13 | `jaw_angle` | Gonial region | Gonion up/back ±5 mm, which sets the gonial angle |
| 14 | `chin_width` | Chin | ±4 mm |
| 15 | `chin_projection` | Chin | ±4 mm |
| 16 | `lip_thickness` | Lips | ±1.5 mm |
| 17 | `forehead_slope` | Forehead | ±5° |

**Planarisation pass**: after the lattice edits, a masked "flatten toward fitted plane" step (least-squares plane per face patch, blend 0–1) per plane group in §2.1. This gives the Sifu facet look without destroying topology, which the eyelids, mouth and future blendshapes need. Patch boundaries are the plane edges in §2.1. They are drawn once as vertex groups on the MPFB base-mesh topology, which is stable across macros, so they survive every rebuild.

**Loop rule:** one edit = change 1–3 controls by a small step. Render, score, keep or revert (best-of-N; NOTES §7).

### 2.4 Anti-likeness rules

The character is inspired by an archetype, not a person. NOTES §3 forbids the actor's likeness.
1. **No photos of any real person enter the look loop.** That means no reference photos, no image-to-3D, no landmark fitting to photos, and no film stills or frames used for look. Footage exists only for motion (NOTES §8), and it never reaches `blender/` or the look harness.
2. **No real names in any prompt.** Critic prompts, generator prompts and commit messages describe the design in the terms of this spec (planes, ratios, materials), never "make him look like …".
3. **The face is defined only by this spec**: the MPFB macros (mixed `race` macro), §1 ratios, and §2.3 controls. Anything outside these is an untracked edit and gets reverted.
4. **Human check at two gates.** At the direction checkpoint (§6) and at `m1` sign-off, the user is asked one explicit question: *"Does this look like a specific real person to you?"* A yes blocks the gate.
5. **Optional automated check** (open question Q4): face-recognition similarity between our renders and a small private negative set. Not recommended now:
   - It needs photos of the actor on disk, kept in `private/` only.
   - Open face-embedding weights (InsightFace models, VGGFace2-trained FaceNet) carry research or non-commercial terms. That's acceptable offline (NOTES §14 rule 8), but it adds a dependency for a risk that rules 1–3 already prevent by construction.

## 3. Hair and beard

### 3.1 Design

| Item | Spec | Tag |
|---|---|---|
| Colour | Near-black brown, base albedo about sRGB `#1d1915`. Cool, desaturated highlight. No grey in the head hair. | [visual] |
| Length | Tips at about the **shoulder line / collar** (z ≈ 1.48–1.52 m at 1.85 m stature). Clears the jacket collar by at most ~3 cm so it doesn't fight the collar sim. | [auto] (tip-z percentile) |
| Part | Slightly off-centre, soft, not a hard line | [visual] |
| Mass | Swept back from the hairline, falling behind the ears. **Two to four front clumps fall forward**, framing the face and crossing the temple or cheekbone on one side (asymmetric), so the silhouette isn't a helmet. | [visual] |
| Volume | Lies close at the crown (no volume bump), heavier at the nape and sides. Total silhouette width ≤ 1.35 × bizygomatic at eye level. | [auto] *(cal.)* |
| Beard | Short and full: 8–12 mm, with a connected moustache, a clean cheek line following the cheek plane break (§2.1), and a neckline about 2 cm above the Adam's apple. Same colour as the hair; slight warm variation allowed. | [visual] |
| Brows | Dark, straight, heavy, following the brow-shelf angle. Keep the MPFB card brows as a stopgap; replace them with clump cards in the hair pass. | [visual] |

### 3.2 Construction (Blender hair curves → clump meshes)

1. **Scalp emitter**: a duplicate of the head scalp region (vertex-group mask) with a stored *parting line* and a *growth direction field* (painted or analytic: back from the hairline, down at the nape).
2. **Guide curves**: 30–45 clump guides placed procedurally along rows from the part, plus 2–4 hand-tagged "front fall" guides. Each guide has 8–12 points. It's shaped by deterministic scripted rules (gravity, comb direction, a seeded noise curl of ±1 cm), never by manual combing, so every build is reproducible.
3. **Clump geometry** via Geometry Nodes (`Curve to Mesh`):
   - Main clumps are **tapered tubes**, 5–6 sides by 8–10 segments, radius 0.9–1.4 cm at the root falling to 0.2 cm at the tip, slightly flattened (ribbon-ish, aspect 1.6).
   - Edge clumps are **ribbons** (2 tris per segment).
   - A **scalp cap shell** (offset 2 mm from the scalp, hair-coloured) prevents see-through between clumps.
4. **Attributes baked to vertex data**: `root_to_tip` (V), `clump_id`, `side` (for Kajiya-Kay tangent sign), a random per-clump hue jitter, and `spring_weight` (0 at the root, 1 at the tip) for binding to spring chains.
5. **Flyaways**: 15–30 thin cards (alpha) along the silhouette and parting only.
6. **Beard**:
   - A **shell mesh** offset 3–8 mm from the jaw, chin and upper-lip region (masked from the head). It carries painted clump texture plus alpha-to-coverage at the cheek line and neckline.
   - Plus 40–80 short card or ribbon clumps on the jaw silhouette and moustache edge, for profile breakup.
   - It deforms with the head and jaw bones (no springs).

### 3.3 Shading notes (Kajiya-Kay, NOTES §7)

- Tangent = mesh V direction (root→tip). Use two shifted lobes:
  - Primary: shifted toward the tip, tinted white-ish.
  - Secondary: shifted toward the root, tinted with the hair colour, plus sparkle noise from a shift texture.
- **Banded**: quantise the specular into 2–3 painted bands to match the painted world. Diffuse is a 2-tone ramp with a soft terminator.
- Alpha:
  - **Alpha-to-coverage with 4× MSAA** only for the fringe, flyaways and beard edges.
  - Clump bodies are opaque.
  - The shadow pass uses a **fixed alphaTest** (0.5).
- The neon rim (magenta and teal) must catch the hair mass edge. Check this in the neon test rig (§6).

## 4. Suit

### 4.1 Garment spec

Conventions come from tailoring guides ([Bond Suits, proportions](https://www.bondsuits.com/the-suits-ideal-proportions/), [Westwood Hart, lapels](https://westwoodhart.com/blogs/westwood-hart/guide-suit-lapel-width-classic-wide-skinny), [Caprice Bespoke](https://capricebespoke.com/blogs/sartorial-glossary/glossary-waistcoat-meaning-odd-vest) and [Hero and Villain Style](https://heroandvillainstyle.com/how-to-wear-a-waistcoat-rules/) on waistcoats). They're scaled to our 1.85 m, 0.56 m bideltoid figure. Where a value is house style rather than sourced convention, it says so.

| Part | Spec | Measure / tag |
|---|---|---|
| **Cloth and colour** | Black worsted wool, matte with a soft sheen. Not pure black: albedo linear 0.025–0.035, with a sheen/rim term so it reads under neon. No pinstripe. | [visual] |
| **Jacket cut** | Single-breasted, **two-button**, closed (top button fastened) by default. Close but not tight; clean chest, suppressed waist. | Waist suppression: jacket width at the button stance ÷ jacket chest width ≤ 0.88 [auto] *(cal.)* |
| **Shoulder** | Natural with light padding, a **sharp, straight shoulder line** (Sifu sharpness), slight roped sleeve head | Suit shoulder width (same definition as `bideltoid`, on jacket vertices) = body bideltoid + 2.0–3.5 cm [auto] |
| **Jacket length** | Covers the seat. The hem sits at about half the distance from the base of the neck to the floor (Bond Suits). | Hem z ÷ suprasternale z = **0.50 ± 0.015** [auto]. Baseline 0.855 / 1.507 = 0.57: **about 10 cm too short** |
| **Button stance** | The fastening button about 1 inch above the navel (Bond Suits). ANSUR male navel height is about 0.596 × stature, so the target is **z = 0.61 × stature**. Second button 11 cm below. | ±0.01 × stature [auto]. Baseline 0.618 (pass) |
| **Lapel** | **Notch lapel, 8.5 cm** at its widest: about half the collar-to-shoulder span, the 3–3½″ classic range, slightly up for a broad build. Soft roll down to the top button (bevelled roll line, not a crease). | ±0.7 cm [auto] *(cal.)* |
| **Gorge** | Medium-high: the notch about 5 cm below the shoulder seam's neck point. Too low pulls the eye from the face; too high weakens the chest (Bond Suits). | [visual] |
| **Pockets** | Straight flapped hip pockets, flap depth about 0.75 × lapel width (≈ 6.4 cm; Bond Suits). Welt breast pocket, **no pocket square**. Texture or normal only, no geometry. | [visual] |
| **Vents** | **Double side vents, 24 cm** (recommended; Q1). They give two flaps that react to the legs, and spring or Dem Bones motion reads better. The alternative is a single centre vent, 20–25 cm (8–10″ is the convention). | [visual] |
| **Sleeves** | Show **1–1.5 cm of shirt cuff** with arms down. Four-button cuffs as normal map or texture. | Cuff reveal [auto] |
| **Waistcoat** | Single-breasted, **5 buttons, bottom one undone** (cut so the points fall open slightly), no lapels. The V opening is visible inside the jacket's V: the vest's top button is about 12–14 cm above the jacket's fastening button. The points cover the trouser waistband by 2–3 cm (no shirt between vest and waistband). Black wool front. The back is black satin, lower panel only (§4.3). | Vest bottom z < waistband top z − 0.02 [auto] |
| **Trousers** | Flat front, **natural-waist rise** (waistband top at about navel height, 0.59–0.63 × stature; hidden under the vest), no belt (side adjusters, house style). Slim straight leg, leg opening about 19 cm flat (house style). **Quarter break**: the back hem sits at the top of the heel counter, the front rests on the vamp with one soft fold. **Centre crease** front and back as a ridge edge loop plus a normal-map line. | Waistband top z ÷ stature 0.59–0.63 [auto] (baseline 0.623, pass). Back hem z 0.035 ± 0.01 m [auto] |
| **Shirt** | White poplin (albedo linear ~0.75, not 1.0). **Semi-spread collar**, points about 7 cm (about 0.8 × lapel width; Bond Suits notes collar points usually a bit shorter than the lapel). Collar stand about 4 cm, showing 1–1.5 cm above the jacket collar at the back. Barrel cuffs 6.5 cm (about the collar-point length). | [visual] + cuff reveal [auto] |
| **Tie** | Black, solid, matte silk. **Blade width 8 cm** (tie width matches lapel width within ±1 cm; Bond Suits). Small **four-in-hand** knot, about 4 × 4.5 cm, with a subtle dimple. The tip is tucked under the waistcoat and ends at the waistband top. No tie bar. | Tie tip z within 0–4 cm above the waistband top [auto]. Baseline tip 1.250 vs waistband 1.147: **10 cm short** |
| **Shoes** | Black cap-toe oxfords, polished (`shoes04` stays as a placeholder) | [visual] |

### 4.2 Mapping `toigo_male_suit_tie_and_jacket` (suits01, CC0) to shells

These are the loose parts measured in the staged spike-1 build (world z at 1.84 m stature):

| Source shell (quads) | z range | Becomes | Work |
|---|---|---|---|
| 6,267 (jacket body, sleeves, collar, lapels) | 0.855–1.606 | **Jacket** | Retopo or decimate to ≤ 9k tris. Lengthen the hem about 10 cm. Cut the double vents, with overlap and the inner face. Bevel the lapel roll. Re-cut the notch and gorge. Sharpen the shoulder line. |
| 1,094 (trousers) | 0.065–1.147 | **Trousers** | Hem to a quarter break. Crease edge loops. Leg-opening taper. ≤ 3.5k tris. |
| 628 (shirt front and collar) | 1.270–1.633 | **Shirt** (collar, placket V) | Re-cut the collar to semi-spread. Add **cuff rings** generated from the sleeve ends (the source has no shirt sleeves). Keep only the regions that can be seen (§4.3). |
| 678 (tie blade) + 382 (knot) | 1.250–1.564 | **Tie** | Re-texture solid black. Re-shape the knot to a four-in-hand. Lengthen the blade to the waistband, then delete the blade below the vest V (always hidden). |
| 2 × 276 (jacket buttons) | 1.047–1.149 | **Buttons** | Replace with ≤ 24-tri discs, or a normal-map decal plus one disc for the fastened button. 552 quads for two buttons is waste. |
| — | — | **Waistcoat (new)** | No MPFB or suits01 asset has a waistcoat; all eight suits01 garments and the system-pack suits were checked. Build it: offset the nude-body torso surface 6–8 mm, cut the V, points and armholes, and transfer weights from the body. |

Alternative bases worth one A/B in the loop: `toigo_male_suit_3` (jacket shell 4,121 quads, a lighter starting point; trousers 2,008 quads) and `male_elegantsuit01` (system pack; jacket and shirt merged in 6,165 quads, so it's harder to split). All are CC0 and audited clean in spike 1.

### 4.3 Hidden-surface removal (body and layers)

The rule is that **every polygon must be able to show in some pose of the m2/m3 clip set**. The rest goes.
- **Body.** Keep the head, a neck band down to 2 cm below the shirt-collar top, and the hands up to 3 cm inside the shirt cuff. Delete the rest. This extends MPFB's `delete_verts` masks; check by the poke-through test below.
- **Shirt.** Keep the collar, the placket V above the vest, a 4 cm strip below each vest point, and the cuffs plus 8 cm of sleeve. Delete the back and the body under the vest.
- **Waistcoat.** Keep the full front. For the back, keep only the lower satin panel (waist to the vest hem), because double vents can open there. Delete the upper back and the armhole interiors.
- **Tie.** Delete the blade below the vest V.
- **Trousers.** Keep everything. The seat shows through the vents and in hood slides.
- **Poke-through test** [auto]: pose the character through the spike-1 `pose_check.py` extremes plus the m2 locomotion set (once it exists). Render an ID pass from the 4 views and the game camera. **Zero visible pixels** of a deleted-region neighbour or of an inner layer through an outer layer.

## 5. Budgets and deformation prep

### 5.1 Triangle budget (LOD0)

NOTES §7 sets LOD0 at 40–60k. The aim is **≤ 50k**, so there is headroom for the pistol and holster at m3.

| Part | Spike-1 baseline | m1 target | Note |
|---|---|---|---|
| Body (head, neck, hands after §4.3) | 15,240 | **≤ 10,000** | Head and face density stays; the torso and legs are deleted |
| Eyes, brows, lashes, tongue | 1,180 | **≤ 1,200** | |
| Teeth | 7,120 | **≤ 500** | All six MPFB teeth variants are 7,120 tris, so swapping variants doesn't help. **Decimate**: they're barely visible, and the mouth is closed or near-closed. |
| Jacket | 12.5k (inside the 19.2k suit) | **≤ 9,000** | |
| Waistcoat | — | **≤ 2,000** | Front plus lower back panel |
| Shirt (visible regions) | 1.3k (inside the suit) | **≤ 1,500** | |
| Tie and knot | 2.1k (inside the suit) | **≤ 700** | |
| Trousers | 2.2k (inside the suit) | **≤ 3,500** | Crease loops and break fold |
| Buttons | 1.1k (inside the suit) | **≤ 200** | |
| Hair (clumps, cap, flyaways) | 4,108 (placeholder) | **8,000–9,500** | |
| Beard (shell and clumps) | — | **≤ 2,500** | Hair plus beard ≤ 12k (NOTES §7 hair 8–12k) |
| Shoes | 3,320 | **≤ 3,000** | |
| **Total** | **50,170** | **≤ 50,000** (hard cap 60k) | [auto] per part, from the GLB |

**Other budgets:**
- 4 weights per vertex [auto].
- Textures 2048 for the body and suit, 1024 for the hair (NOTES §7).
- Materials ≤ 8.

### 5.2 Bone budget (60–90; baseline 53)

| Group | Bones | Count | Purpose |
|---|---|---|---|
| Baseline `game_engine` | as built | 53 | |
| Twist | `upperarm_twist_01_{l,r}`, `lowerarm_twist_01_{l,r}`, `thigh_twist_01_{l,r}` | +6 | Forearm and upper-arm candy-wrapping; jacket sleeves |
| Helpers / correctives | `deltoid_helper_{l,r}` (shoulder volume when raising the arm, *the* suit problem), `glute_helper_{l,r}` (seat under jacket and vents) | +4 | Driven by rotation (no sim) |
| Face | `jaw`, `eye_{l,r}` | +3 | Jaw for the beard shell; eyes for look-at (NOTES §8 look-at) |
| Jacket (Dem Bones virtual + springs) | 2 front hem, 2 side, 2 vent flaps × 2 segments | +8 | Dem Bones SSDR from the offline cloth sim (NOTES §7) |
| Hair springs | 4 chains × 3 (back mass L/R, two front-fall clumps) | +12 | VRM spring-bone model with head and shoulder capsule colliders |
| Tie springs | **0** | 0 | With a waistcoat the tie is tucked and barely moves, so the springs NOTES §7 lists for the tie are not needed (Q5) |
| **Total** | | **86** | Under the 90 cap. Adding more hair chains means taking from the jacket. |

**Deformation-prep work for m1** (rig only; the sims are m2/m3):
- Add the bones above with UE-mannequin naming, and weight-transfer onto all garments.
- Rotation-driven helper rules.
- Joint ROM sheet for the poke-through test.
- The Dem Bones bake itself is m2/m3. m1 only reserves the bones and checks the jacket's skinning in the `pose_check` extremes.

## 6. Early direction checkpoint (before polishing)

**When:** after the first wave of the loop:
- macros tuned to §1,
- the head lattice framework working,
- blockout hair and beard,
- the suit retopo blockout (black, untextured, lengthened, with vest).

This comes before any painterly texture work or fine tuning.

**What the user sees:** one contact sheet, `bench/m1/img/checkpoint-1.png`.
- **3 variants** (A/B/C), each a different point in the §2.3 control space, all within the §1 tolerances. For example:
  - **A** lean and angular: high cheek break, narrow jaw end of the range.
  - **B** heavier: wide jaw, deeper brow.
  - **C** weathered: deeper sockets, hollows, slightly longer face.
  - Each pairs with one of 2 hair-mass options: swept-back plus a front fall, or fuller and looser.
- Per variant, these views:
  - **front, ¾, profile, close-up**: EEVEE iGPU, 512², neutral 3-point light, clay plus base colour;
  - the **game-camera view**: 3.5 m behind and above, 1470 × 956 framing, head about 40 px;
  - a **silhouette pass**;
  - one **neon test-rig** close-up: magenta and teal rims, amber key.
- A table of the §1 and §5 numbers per variant.

**What the user decides:**
1. Pick a variant, or a mix such as "A's face, B's jaw, hair option 2".
2. Answer the anti-likeness question (§2.4 rule 4).
3. Answer the open questions in §8.

**What it freezes:**
- The chosen variant's front and profile silhouettes become the **silhouette-IoU reference**. Regressions after that need IoU ≥ 0.97 for the body and ≥ 0.95 for the close-up head silhouette *(cal.)*.
- The §1 numbers freeze at their checkpoint values ±½ tolerance.

## 7. Style references and licensing (look only; never committed, traced or fed to a generator)

| Source | Licence | What it's for | Read? |
|---|---|---|---|
| Paul-Emile Boucher, *Sifu* project page ([ArtStation](https://peboucher.artstation.com/projects/OmE5n6)) | © Sloclap, all rights reserved | The two style pillars quoted in §0 | Via search summary (direct fetch blocked, 403) |
| Boucher, GDC 2023, "Kung-fu and Speed Painting: Sifu's Art Direction and World Building Approach" ([GDC Vault](https://www.gdcvault.com/play/1028808/Kung-fu-and-Speed-Painting), free) | © GDC / Sloclap | How speed painting shaped volumes, shapes and textures. **Watch before the painterly texture pass.** | Description only; the talk has not been watched |
| Boucher, "From inspiration to coherence, building the world of Sifu" ([Game Developer](https://www.gamedeveloper.com/design/from-inspiration-to-coherence-building-the-world-of-i-sifu-i-)) | © Informa | World framework only. Nothing on character modelling. | Read |
| Sloclap interview ([Game Rant](https://gamerant.com/sifu-interview-sloclap-cultural-sensitivity-inspiration-brawler/)) | © Valnet | "Sharp and stylized" intent for the protagonist's features | Via search summary |
| Chen-Yang Hsu, "Sifu and 5 young bosses design process" ([ArtStation](https://www.artstation.com/artwork/RnzAnE)) | © artist / Sloclap | Shape-study process for heads | Not read (403). Look in a browser if useful. |
| Tailoring guides: Bond Suits, Westwood Hart, Caprice Bespoke, Hero and Villain Style (links in §4.1) | © their authors | Garment proportion conventions (facts, restated in our own words) | Read (Bond Suits fully; the others via search summaries) |
| ANSUR II (US Army) | US Government work | Proportion reference numbers | Via search summary plus the DTIC report link |
| MPFB2 / MakeHuman CC0 assets | CC0 (audited, spike 1) | Our base: these *are* committed into the build | — |

**Forbidden as look references** (never in the loop, never in `bench/`, never in a prompt):
- Photos, stills, frames or posters of the actor or of the films' costumes.
- Photos of any real person, as face targets.
- Ripped game assets (Sifu or others).
- Fan sculpts (unclear rights).
- Any "in the style of <living artist>" generator prompt.

Footage stays in `private/` for motion only (NOTES §8, §14).

## 8. Open questions for the user

1. **Q1 Vents:** double side vents (recommended) or a single centre vent?
2. **Q2 Hair length:** tips at the shoulder line, as specified, or shorter, at collar level?
3. **Q3 A distinguishing original feature** (optional): for example a small scar through the left brow, or a slightly broken nose line. It helps originality and reads at close-up.
4. **Q4 Automated likeness check** (§2.4 rule 5): skip, as recommended, or add it with a private negative photo set?
5. **Q5 Tie springs:** drop them, as recommended, because the tie is tucked under the waistcoat?

## 9. Concept boards with a local image model (optional item 8)

**Recommendation: don't set one up for m1.**
- **Licence.**
  - SD-Turbo is under Stability's non-commercial community licence.
  - SDXS checkpoints vary by release.
  - Either is acceptable *offline only*, under the same logic as NOTES §14 rule 8. Neither is the blocker.
- **The real problem is likeness leakage.**
  - Prompting "man, long dark hair, beard, black three-piece suit" makes these models drift toward the most-photographed person matching that description.
  - That works against §2.4.
- **The blockout renders are the better concept board.**
  - At ~1.1 s per 512² EEVEE view, the §6 checkpoint sheet *is* the concept art.
  - It is parametric, so the choice converts directly into controls.
- **Worth revisiting later** for **environment and palette mood** only (Kabukicho at night in rain, at m4). Likeness doesn't matter there, and it's quick to try.
