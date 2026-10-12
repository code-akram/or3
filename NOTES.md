# or3 — project notes

> Living document. The single source of truth for vision, decisions, constraints, research and risks.
> Update it whenever a decision is made or a finding changes. Newest decisions go to the top of the [Decision log](#decision-log).
>
> `or3` is a **temporary codename**. Never use it in identifiers (variables, functions, methods, types, packages).

Brainstorming closed: **2026-10-11**.

---

## 1. Vision

A third-person gun-fu RPG shooter in the browser. One character, inspired by John Wick and honouring that legacy, walks a real Shinjuku rebuilt from open data. The art direction is **Painted Neon-Noir**.

- **Fully open source and non-commercial.**
- **A personal benchmark for frontier AI models.** It measures how far a model can push a no-compromise game on fixed, constrained hardware. Milestones are measurable and git-tagged so future models can be scored on the same ladder. See [§15](#15-benchmark-ladder).
- **Constraints are the design.** We build with them and around them, not against them.

## 2. Story base

- **Era:** after recursive intelligence. Humanity reached Type-II civilisation and left Earth for intergalactic pursuits.
- **No humans remain on Earth**, except one: **or3**, who stayed by choice.
- The world keeps turning without us. Day and night, weather, and the city's lights and infrastructure carry on.
- No NPCs, crowds or dialogue (until enemies, much later).
- Real brand signage and logos do not exist in this world. They have faded, gone blank or been rewritten. This also keeps us clean legally.
- The story is developed later. This premise is the base.

## 3. Locked decisions

| Area | Decision |
|---|---|
| Genre | Third-person gun-fu RPG shooter |
| Character | One original character inspired by the John Wick archetype: long dark hair, beard, black tailored three-piece suit, white shirt, black tie, dress shoes. **Not Keanu Reeves' likeness.** |
| Build order | **Character → open world → story → enemies and combat** |
| Traversal | **Grounded**: walk, jog, run, sprint, turn-in-place, stairs, slopes, curbs. The only exception is **knee-high hops and car-hood slides**. No parkour, no climbing. |
| World | Open world: **Shinjuku, Tokyo**, from PLATEAU open 3D city data. Starts with Kabukicho, Golden Gai, Omoide Yokocho and the station east side (~1.5 km²). |
| Simulation | Day/night cycle and weather. No other characters. |
| Camera and controls | Standard third-person RPG feel, with Sifu as reference. **Keyboard first** (MacBook, trackpad only). |
| Art direction | **Painted Neon-Noir.** See [§10](#10-art-direction--painted-neon-noir). |
| Target client | MacBook Air M4, **Chrome only** for now (Safari and Firefox later), **locked 60 fps** |
| Compute | **This machine only** for all offline processing. No rented GPUs. |
| Motion source | John Wick footage via video-to-motion, **as much as needed**. Open mocap fills the gaps. No self-filmed mocap. |
| Licence | Fully open source: **MIT for code, CC BY 4.0 for original assets** (art, motion, audio). Third-party assets keep their own licences. Every asset must be redistributable. See [§14](#14-licensing--provenance-rules). |
| Hosting | Public GitHub repo **`code-akram/or3`**. Playable build on **Cloudflare Pages** (it serves the COOP/COEP headers). |
| Large binaries | **Rebuildable from the pipeline.** Commit scripts and small sources only. Large outputs (GLB chunks, KTX2, Opus, animation DBs) are published as release artifacts or on the CDN. No Git LFS. |
| Weapon | **Original fictional competition pistol**: compensated, stippled, striker-fired, so it reads like Wick's. No real marks or trademark trade dress. Built in Blender like the suit. |
| Vehicles | **Abandoned fictional cars** (kei cars, taxis, vans) left behind when humanity departed. Unbranded, dusty or slightly overgrown. They are hood-slide obstacles and set dressing. No traffic. |
| Time flow | **Accelerated, configurable day** (e.g. 48 min) replaying a curated slice of the real Shinjuku weather tape. Debug controls jump to any time or weather. |
| Music | **Diegetic only.** No score. Music comes from the world (bar speakers, vending jingles, crossing melodies), all original or synthesised. |

## 4. Constraints

### Build machine (offline pipeline)
- AMD Ryzen 7 7700: 8 cores / 16 threads, Zen 4, AVX-512 including bf16/VNNI.
- 62 GB RAM, ~1.6 TB free.
- iGPU (Raphael, 2 CUs, 64 MB carve-out) is **useless for ML and Cycles**. ROCm on gfx1036 is not viable.
  - It **does run EEVEE headless** via Mesa radeonsi/EGL: ~1.1 s per 512² look-dev frame at 16 samples, ~7 s per 1024² frame at 64 samples.
  - Otherwise treat the machine as CPU-only.
- Arch Linux, headless (no display). `blender -b` creates its own surfaceless EGL context. No Vulkan ICD is installed.
- Available: Rust/cargo (stable + a nightly for WASM threads), Node 24, Python 3.14 (system), uv, ffmpeg, yt-dlp.
- Installed 2026-10-12: Blender 5.2.2 LTS, OpenVINO 2026.4 and onnxruntime-cpu 1.29 (native libraries only; Python bindings come from uv envs).
- Headless Chromium is available through Playwright (`~/.cache/ms-playwright`), with WebGPU on SwiftShader. Use it for correctness checks only.
- Research codebases run in **uv-managed Python envs at the version their lockfile requires**: 3.10, or 3.11 for the GVHMR fork. Never use the system Python for them. The 3.11 fork is confirmed and pinned (2026-10-12).
- The machine is a **Hetzner** host: both its IPv4 and IPv6 addresses are in datacenter ranges (AS24940). This affects YouTube (§8).

### Play client
- MacBook Air M4: fanless, 60 Hz display, unified memory, Apple tile-based GPU.
- **Sustained GPU throttle of about 20%** under constant load (Notebookcheck).
- **Frame budget: about 12 ms** on a warm machine. Dynamic resolution is the safety valve.
- **Tab memory budget: ≤ 1.5 GB total**, including GPU resources.
- Trackpad only, so **mouse-look must never be required**.

## 5. Scope and build order

1. **Character.** Look, rig, deformation, secondary motion, locomotion, Wick mannerisms, gun handling without enemies, camera. Tested in a graybox gym and a shooting range.
2. **Open world.** One Kabukicho block first, then the starting district. Day/night, weather, audio.
3. **Story.**
4. **Enemies and gun-fu combat.** Grapples, takedowns and AI come last.

### Working agreement (decided 2026-10-11)
- **Claude works autonomously and stops only at gates**:
  - `m1` look sign-off.
  - Audio listening review.
  - M4 Air measurement sessions.
  - Credentials and licence registrations.
  - System installs.
- **Independent work runs in parallel**, using git worktrees where that applies.
- **System installs**: Claude gives one exact `sudo pacman -S …` command per batch, and the user runs it.

## 6. Tech stack

### Runtime (browser)
| Layer | Choice |
|---|---|
| Renderer | **Three.js WebGPURenderer + TSL**, with our own stylised nodes (toon ramps, ink lines, LUT grade, wet surfaces). No open-source TSL stylisation stack exists, so we write it. |
| Core | **One Rust → WASM module** (wasm32, SIMD, threads via SharedArrayBuffer). It holds motion matching, inertialisation, IK, spring chains and **Rapier** physics, all in shared memory, and the renderer reads poses zero-copy. |
| Gameplay and UI | TypeScript (strict) |
| Navigation | Recast/Detour, baked offline (later) |
| Audio | Web Audio API: sample pools, granular beds, zone convolution reverb, custom HRTF |
| Build | Vite 8 + TS 7. Cargo **nightly (pinned)** with `-Z build-std=std,panic_abort` and `+atomics,+bulk-memory,+simd128` plus shared-memory/TLS link args (spike 4). The wasm-bindgen CLI is pinned to the crate version, and `wasm-opt -O3` runs last. Keep O3: Oz is 28 % smaller but makes the sim 1.8× slower. Stable Rust silently builds a single-threaded module. |
| Threading | The sim runs in a dedicated Web Worker at a fixed 60 Hz and hands poses to the renderer through a lock-free triple buffer in shared memory. The main thread never blocks. three r186 `InstancedMesh` caches `instanceMatrix.array`, so WASM-driven transforms use our own `InstancedInterleavedBuffer`. |
| Headers | `COOP: same-origin` + `COEP: require-corp` (Chrome allows `credentialless` too). Self-host all assets. |

### Offline pipeline (this machine)
- **Blender 5.x headless** (`blender -b --python`): character construction, tailoring, cloth bakes, retargeting, painterly texture bakes (compositor Kuwahara), lightmaps (Cycles CPU), turntable renders.
- **Python 3.10 uv envs**: GVHMR, shot detection, tracking, cleanup.
- **Rust tools**: PLATEAU parsing (`nusamai`), facade and chunk generation, animation database baking.
- **Asset optimisation**: glTF-Transform (meshopt, KTX2), a custom compressed animation format.

### Repo layout (proposed, approval due at the `m0` gate)
```
Cargo.toml     Cargo workspace (core + tools)
web/           Vite + strict TS client: gameplay, UI, TSL renderer nodes, audio
core/          Rust crate → WASM: motion matching, inertialisation, IK, springs, Rapier
tools/         Rust CLI tools: PLATEAU parse/mesh, facade + chunk gen, anim DB bake
pipeline/      Python uv projects, one env each: video-to-motion (3.10), audio DSP
blender/       Headless bpy scripts: character, suit, hair, bakes, retarget, turntables
assets/        Small committed sources: fonts (OFL), palettes, LUTs, configs
provenance/    Provenance manifest + audit script (CI)
bench/         Telemetry endpoint + recorded results per milestone tag
data/raw/      (gitignored) scripted downloads
private/       (gitignored) footage, SMPL, weights, commercial material
```

## 7. Character spec (must be nailed, no compromise)

### Method: agent-driven look-dev loop
**Image-to-3D is ruled out.** TRELLIS, Hunyuan3D, SAM 3D and TripoSG all have one or more of: CUDA-only, an EU/UK licence exclusion, poor topology, no style control. Instead:

1. **Base body**: MPFB2 (MakeHuman for Blender). Core assets are CC0. Uses the `game_engine` rig.
   - **Verified headless** (spike 1, MPFB 2.0.18 on Blender 5.2.2): a full build takes ~2 s and is single-threaded. Script: `blender/build_character.py`.
   - Bake the macro shape keys (`TargetService.bake_targets`) before glTF export, or the Basis shape ships.
   - Fix the GAMEENGINE alpha links (opaque vs MASK) before export.
2. **Head**:
   - Sifu-style angular, planar, readable face, **original** (no likeness).
   - Built by scripted, low-dimensional parametric edits (control points or lattices) on the MPFB head.
   - Optional refs: FLAME 2023 Open (CC-BY-4.0), ICT-FaceKit Light (MIT) for later blendshapes.
3. **Loop**:
   - Fixed views: front, ¾, profile, close-up.
   - **Loop renders**: EEVEE headless on the iGPU, 512², 16 samples, ~1.1 s per view.
   - **Sign-off renders**: Cycles CPU, 1024², 128 spp + OIDN, ~13–18 s per view at 16 threads.
   - Scripts: `blender/render_turntable.py`, `bench/m0/bench_spike2_render.sh`.
   - Agent critique, then **best-of-N small edits with revert**. BlenderGym (CVPR 2025) found verifier-heavy compute works best.
   - Measurable checks: silhouette IoU against reference, landmark ratios, poly budget.
4. **Concept guidance** (optional): SD-Turbo / SDXS via OpenVINO on CPU (~1.5–3 s per image) for mood boards only.

### Suit
- **Base**: MPFB CC0 `suits01` (toigo suit, tie and jacket). Retopo, then **script-tailor**:
  - Separate shells for shirt, vest, jacket and tie.
  - Bevelled lapel roll and notch, shoulder volume, a real jacket vent, trouser crease (ridge + normal line).
  - Seams driven by curvature masks.
  - Hide covered body polygons.
- **Deformation**:
  - Helper and twist bones (shoulder, elbow, hip, thigh).
  - **Offline Blender cloth sim → Dem Bones (EA, BSD-3) SSDR**, baked into extra "virtual" bones, so we get cloth-quality motion at skinning cost.
  - Morph correctives only where artifacts remain.
- **Secondary motion**: tie, jacket hem, vent flaps and hair clumps use **spring/Verlet chains in Rust** (VRM springbone parameter model) with body capsule colliders. Estimated cost < 0.1 ms.

### Hair and beard
- **Clump meshes** (tapered ribbons and tubes) for the mass, in Sifu/Arcane style, plus a few cards for flyaways.
- Generated from Blender hair curves by script.
- Shading: banded Kajiya-Kay with shifted tangents. Alpha-to-coverage + 4× MSAA only for the fringe and beard edges. Fixed alphaTest in shadows.

### Budgets (initial, to calibrate)
- LOD0: 40–60k tris (body ~15k, suit 15–20k, hair 8–12k, face/eyes ~5k). LOD1 50%, LOD2 20% (meshoptimizer).
  - Spike-1 baseline: 50.2k tris (body 15.2k, suit 19.2k, hair 4.1k, **teeth 7.1k: swap them for a lighter shape**, shoes 3.3k), 53 bones, 4 weights per vertex.
- 60–90 bones, 4 weights per vertex.
- Textures 2048 (body, suit) and 1024 (hair), KTX2.

### Identity in motion
- The Wick walk, posture, suit adjusting.
- Draw and holster, with the original fictional competition pistol (§3).
- **C.A.R.-style stance**:
  - High position: gun close to the chest. Extended position: strong arm half-extended, support elbow down, slight inward cant.
  - Sources debate whether the films show true C.A.R. or a modified high-ready, so **we follow the footage**.
- Reloads, including the lateral mag-flick eject.
- Knee-high hop and hood slide.

## 8. Motion pipeline

### Layering
| Layer | Source |
|---|---|
| Core locomotion coverage (all speeds, turns, starts, stops) | **100STYLE** (CC BY 4.0) + **CMU** (likely free for all uses, verify) |
| Wick identity: walk, stance, draws, reloads, stairs, idles | **John Wick footage → GVHMR** |
| Hops and hood slides | CMU 127_25 ("run jump over"), subject 41 (step/jump over). PARC dataset (HF MIT label; verify provenance, strip Epic seed clips). SFU vaults (licence unverified). Plus Arc de Triomphe shots. |
| Fill-in transitions | NVIDIA **Kimodo**, SOMA checkpoint only (NVIDIA Open Model License). Offline. |
| Fingers and grips | Hand-authored grip pose library (pistol, relaxed, fist) + two-hand IK |

### Video → motion (CPU)
**Footage source:** official studio-uploaded scene clips, trailers and behind-the-scenes featurettes, fetched with `yt-dlp` into `private/`. Full-film scenes are not used.
- **YouTube** answers this machine with "confirm you're not a bot" whatever the client, IP family or PO token, because of the datacenter IP. Fetching needs the user's exported cookies at `private/youtube-cookies.txt` (mode 600), run through `pipeline/video-to-motion/fetch-youtube.sh`. yt-dlp warns that the account can be banned, so use a secondary account.
- **Lionsgate UK/US TikTok** downloads without auth, but gives vertical re-edits (576–960 px) with captions. Use it only as a fallback.
- **Studio-supplied featurettes hosted by press outlets count as official** (ruling 2026-10-12). Example: the behind-the-scenes Sacré-Cœur stair clip, an IGN exclusive. Same rules as all footage: `private/` only, never committed.

`yt-dlp` → shot split from the **union of TransNetV2 and PySceneDetect** cuts (TransNetV2 alone missed a hard cut) → filter out:
- shots < 1 s
- median luma < ~15/255 (night Wick footage measures 6–36)
- blur
- subject < 256 px
- protagonist track coverage < 90 %
- ViTPose mean confidence < 0.7

→ YOLO + ByteTrack → protagonist ID (face + body embeddings, seeded with reference crops) → **GVHMR** (SimpleVO, or static camera via `-s`; bf16 / OpenVINO) → cleanup:
- One Euro / Butterworth smoothing
- foot-contact lock
- floor clamp
- root de-drift

(reference: `squall01337/mixamo-llm-mocap`, MIT) → **own `bpy` retarget** (SMPL joint rotations → our rig with rest-pose correction, root scaled by leg ratio) → bake.

- **GVHMR build**:
  - The `ryanrudes/gvhmr` fork (CPU-native, Python 3.11), pinned at `e3876097` and installed `--frozen`.
  - Keep a source bundle in `private/src/`. Treat its ZJU non-commercial `LICENSE` as binding.
  - bf16 autocast for ViTPose and HMR2 is 2.8× faster with a 1.2 mm MPJPE change. OpenVINO adds only about 15 % more.
- **Throughput (measured idle, Phase 0, 30 fps frames, per 60 min of footage)**:
  - fp32 as shipped: **~35 h**. The old estimate of 22 h was too optimistic.
  - bf16, accuracy-neutral, run as 4 processes × 4 threads: **17.8 h**.
  - Skipping duplicated frames: ~15 h.
  - With ViTPose flip-test off and YOLO at source fps: **~11–12 h**. This costs about +2.3 mm PA-MPJPE.
  - 16 threads is no faster than 8 (8 physical cores).
  - Stage shares: ViTPose 48 %, YOLO 28 %, HMR2 24 %.
  - Ultralytics overrides the thread cap. `bench_gvhmr.py` pins it.
- **Cleanup, foot lock v2**: contact detection (height + speed, hysteresis, minimum duration) plus **two-bone leg IK** that pins the heel and then the ball. The root's horizontal path is left alone.
  - Measured: contact slide 23.7 → 2.5 cm/s on the walk clip and 4.0 → 1.3 cm/s on the Osaka clip.
  - At least 99.4 % of travel is kept.
- **Weak spots:**
  - Camera cuts (split first).
  - Fast strikes (smoothed).
  - Falls and ground work.
  - Dark, motion-blurred or inverted bodies, where the person detector fails: every YOLO variant found the Sacré-Cœur tumble in under 12 % of frames.
  - Long coats hiding crossing legs.
  - Two-person grapples (deferred with enemies).
- **Falls and stumbles** come from mocap (CMU) plus physics blending or Kimodo, not from video.
- **Video data never enters git.** Only derived motion on our own skeleton.

### Extraction targets (priority, from research)
1. **JW4** Sacré-Cœur stairs: the **climb and walk** wide shots only, because the tumble is unusable (spike 3). Plus its **behind-the-scenes stair clip** (cleanest framing; IGN-hosted, accepted 2026-10-12).
2. **JW4** Paris duel / street walks, Paris Metro meeting (idle, suit adjust), Osaka Continental (walks, turns, draws).
3. **JW4** top-down apartment oner (shooting while moving, reloads; check GVHMR's camera assumption).
4. **JW4** Arc de Triomphe (hood slides, hops; night and occlusion make it hard, so cleanest shots only).
5. **JW3** stable, library, injured NYC run, desert limp walk.
6. **Ballerina** Wick clip.
7. **Behind the scenes**: Taran Butler range training (reloads, transitions), 87Eleven training reels, Ballerina rehearsal featurette.
- **Skip**: Red Circle club, JW2 catacombs, Killa's club, vehicle and horse scenes, montages.

### Runtime animation
- **Motion matching** + **inertialisation**.
- References:
  - `orangeduck/Motion-Matching` (MIT); its `database.bin` is LaFAN1-derived, so don't reuse it.
  - Bollo GDC 2018 inertialisation.
  - `Siroko/kansei` (MIT, Rust/WASM/WebGPU, very new; reference only).
- Foot IK (stairs, slopes, curbs), aim IK, look-at.
- **Motion warping** for hops and hood slides to the obstacle height.
- Data needs: ~15–30 min clean locomotion + 2–5 min per action set. The database is ~24 MB per hour of motion. Tag by clip and range.

## 9. World — Shinjuku from PLATEAU

- **Data**: PLATEAU Shinjuku-ku (13104) **FY2025**, spec v5.0, ~773 MB CityGML, CC BY 4.0-compatible (credit 出典：国土交通省 PLATEAU; note modifications).
  - Buildings: LOD0/1/2.0/2.2 (**no LOD3**; LOD2 coverage partial, check the index-map PDF).
  - Roads (`tran`): LOD1–3.
  - City furniture (`frn`) and vegetation (`veg`): LOD1/3.
  - **Underground mall (`ubld`)**: LOD1/4.1. A grounded exploration space.
  - Bridges.
  - Terrain (`dem`): CityGML only.
- **Attributes**: `measuredHeight`, `storeysAboveGround`, `usage` (401 office, 402 commercial, 403 hotel, 411 house, 412 apartment, 413 shop-house, …). These drive facades and night lighting. LOD1 heights are medians, so they are imprecise.
- **Tooling**:
  - **`nusamai` / PLATEAU GIS Converter** 0.1.19 (MIT, Rust) for parsing and projection.
  - **Our own chunk writer** (`tools/plateau-chunk`), because nusamai's glTF sink is not usable: array attributes including `usage` come out corrupt, the origin is lost, there are no surface semantics, and FY2025 `veg` fails.
  - CRS: EPSG:6697 (lat, lon, orthometric) → **EPSG:6677** (JGD2011 zone IX), re-origined locally. Verified against GSI to 0 mm.
- **Data facts (spike 5)**:
  - FY2025 confirmed: 772,888,884 B.
  - Files are per 3rd-level mesh (1 km). Kabukicho/Golden Gai = `53394536`. The starting district spans `53394525/26/35/36`, with a LOD2 share of 61/39/49/37 % (46 % overall).
  - Sentinels −9999 (height), 9999 (storeys) and usage 461 mean unknown: about 8 % of buildings.
- **Chunk contract (spike 5)**:
  - 200 m squares on the EPSG:6677 grid, named by SW corner: `chunk_e<E>_n<N>_s200`.
  - Origin at the chunk centre: x = E − E0, y = height, z = −(N − N0).
  - Buildings are assigned whole by footprint centre. Roads are clipped per triangle.
  - The per-building attribute table sits in mesh extras. The PLATEAU credit is in scene extras.
  - First chunk: 190 LOD2 buildings, 23k tris, 342 KB after meshopt.
- Arch's Blender 5.2.2 can't import meshopt GLBs, so inspect the uncompressed GLB.
- **OSM**: only for alleys, steps and footways PLATEAU lacks. Keep it a separate ODbL layer with attribution.
- **Facades**: pure art (grounded traversal means no climb rules).
  - Our own split-grammar generator driven by footprint, height, storeys and usage.
  - Plus a **procedural Japanese street kit** built in Blender: vending machines, utility poles and overhead wires, shutters, AC units, lanterns, fictional signage in OFL fonts.
  - Plus **abandoned fictional vehicles** (kei cars, taxis, vans): unbranded, dusty, slightly overgrown. They double as hood-slide obstacles, with collision and traverse markup.
- **Streaming**: **fixed 100–200 m baked GLB chunks** (meshopt + KTX2) with a simple streamer. Avoid runtime 3D Tiles: 3DTilesRendererJS plugins break under WebGPU. Impostors for the far skyline.
- **Textures**: PLATEAU photo textures may contain third-party logos and municipal rights. **Prefer our own stylised atlases.**

## 10. Art direction — Painted Neon-Noir

- **Surfaces**: Sifu-style painted look, **baked offline in Blender**:
  - Curvature, AO and cavity bakes.
  - Procedural brush strokes.
  - Compositor **anisotropic Kuwahara** applied to textures, never at runtime (too heavy for the Air).
- **Light language**: John Wick palette of saturated magenta, teal and amber neon. Wet reflective streets, rain, haze.
- **Palettes** shift by time of day and weather (from Sable).
- **Ink lines on or3 only**, so the character pops off the painted world. No comic halftone.
- **Blender is the look-dev oracle**: offline "ideal" renders are the target the runtime is compared against.

### Neon-rain stack (estimates, M4 Air, ~1470×956, throttled; **unmeasured**)
| # | Technique | Est. ms |
|---|---|---|
| 1 | Wet PBR material (Lagarde: darken albedo by porosity, lower roughness, puddle mask, procedural ripples), driven by weather wetness | 0.3–0.5 |
| 2 | Bloom from emissive MRT (half-res pyramid) + halation + anamorphic streak, reusing mips; one final grade / CA / vignette / grain pass | 1.0–1.8 |
| 3 | **Blender-baked neon spill** + top-down **street-light map** (Neon Zenith technique). Hundreds of signs light street, rain and fog. Faded by time of day. | < 0.2 |
| 4 | Half-res **planar reflection** of a stripped scene, roughness mip-blur, vertical stretch for neon streaks (Threejs-Punk chose this over SSR) | 1.5–2.5 |
| 5 | Rain: height-map-occluded GPU streaks, splashes, awning drips, coloured by the street-light map | 0.5–0.8 |
| 6 | Analytic height fog + billboard glow sprites (no froxels) | 0.2–0.5 |
| 7 | ClusteredLighting for 16–32 hero lights near the player | 0.5–1.0 |
| 8 | Optional half-res SSR for character and props | 1.5–2.0 |

Target total ~11–12 ms, including 5–6 ms scene shading.
- **Warning:** the closest open project (Neon Zenith) measures p95 18.6 ms on an M4 **Max** at a higher resolution with adaptive resolution. Our budget is tight. **Measure on the Air early.**
- **References**: `ektogamat/threejs-conference` (Threejs-Punk, MIT code), `billpwchan/neon-zenith` (MIT code, CC-BY models), three.js toon/SSGI examples, Maxime Heckel's Moebius and painterly posts.
- **Apple GPU notes**:
  - 4× MSAA is cheap (on-tile resolve).
  - Keep the post chain short: one HDR target, everything after tonemap in RGBA8.
  - Avoid transmissive materials with `reflector` (three.js #34635).
  - `PostProcessing` was renamed `RenderPipeline` in r183.

## 11. Sky, day/night, weather

- **Sky**: **`@pmndrs/sky`** (MIT): Hillaire-2020 atmosphere in TSL with sun, moon and stars. Needs three ≥ r186. Sky LUT updated ≤ 1×/s.
- **Ephemeris**: real sun and moon for Shinjuku. Rust `solar-positioning` / `solunatus`, or `astronomy-engine` (MIT) / SunCalc (BSD-2).
- **Stars**: HYG v4.4 (CC BY-SA 4.0, Codeberg). A baked ~5k-star subset; that file stays CC BY-SA.
- **Time flow**: an accelerated, configurable day (e.g. 48 min) with real ephemeris for the simulated date. Debug controls jump to any time or weather.
- **Weather**: **Open-Meteo** (CC BY 4.0; ERA5 1940→now, JMA MSM 5 km), baked into a **"weather tape"** that replays real Shinjuku weather.
  - No fog or visibility variable: derive fog from dew-point spread, humidity and wind.
  - Weather codes never encode thunder: trigger lightning from CAPE or at random.
- **Clouds**: stylised 2D layers driven by low, mid and high cloud cover. No raymarched volumetrics.
- **Night windows**: lit fraction and colour by PLATEAU `usage`. **Interior mapping** for fake rooms. Neon on 402/403 buildings.

## 12. Audio — impeccable and authentic

- **Real recordings are the base. Synthesis is only for variation and gap-filling.**
- **No score. Music is diegetic only**: bar speakers, vending jingles, crossing melodies. All of it is original or synthesised.
- **Known gap (updated by spike 7)**: open Shinjuku recordings exist, but there are few of them.
  - Freesound takecha pack 37936 (CC0, 2023, Shinjuku east side).
  - sergeeo 380726 (CC-BY 3.0, 2016).
  - radio aporee aporee_70134_81690 (Public Domain Mark, 2025, JR platform).
  - Nothing open covers **Kabukicho, Golden Gai or Omoide Yokocho** specifically. The good libraries are commercial and non-redistributable. Field recording remains the upgrade path. See [Open questions](#17-open-questions).
- Several Tokyo street recordings carry steady 19–21 kHz ultrasonic tones, so ambience is low-passed at 17 kHz.
- **Sources**:
  - **Freesound** CC0/CC-BY, audited per file. Examples: Yuval 205748 (CC0 dress shoes, dry concrete, 24/48), stecman 569313 (CC0 rain on metal, 96 kHz), RutgerMuller Japan pack (check each file).
  - **radio aporee** / Internet Archive. Tokyo items are **mostly MP3 originals**, and the licences are mostly BY-SA, NC-ND or PDM, so they are case by case. Lossless items are rare.
  - **Quality floor (spike 7)**:
    - No lossy originals.
    - No ≥ 25 dB/kHz spectral wall below 20.5 kHz. This catches upsampled AAC inside WAV, e.g. iPhone recordings uploaded at 96 kHz.
    - Effective bandwidth ≥ 18 kHz.
    - Footstep SNR ≥ 30 dB.
  - Kenney (CC0).
- **Not allowed in repo**: Sonniss, BBC RemArc, raw Pixabay, NC licences. Commercial libraries only as local-only `private/` material.
- **Gaps to record**: dress shoes on wet ground, stairs, metal and tile; suit rustle; umbrella rain; Japanese ambience (crossings, cicadas, crows, vending machine hum, neon buzz).
- **Crossing signals**: Tōryanse melody is public domain (sequence it ourselves). "Piyo-piyo / kakkō" chirps are synthesised. **Station departure melodies are copyrighted**, so compose originals.
- **Acoustics**:
  - **Steam Audio** (Apache 2.0) bakes impulse responses offline from PLATEAU geometry per zone (alley, Golden Gai, underground mall, concourse, open street).
    - **Verified (spike 6)**: Steam Audio 4.8.1 via Rust FFI (`tools/acoustic-bake`), 0.13 s per IR at 16 threads.
    - Its reflection IR time base is the direct arrival.
    - Raw reflection energy runs ~8.6 dB hot, so bakes are calibrated against a ground-plane-only run.
    - Early reflections are 10 ms-binned noise, with no discrete flutter echoes. Add an image-source early part if needed.
    - The first alley IR (Golden Gai west edge, 2.0 m wide): EDT 0.20 s, T20 0.34 s, DRR −8 dB.
    - The SDK binaries are build-time only. Never commit or ship them.
  - In the browser: one shared `ConvolverNode` reverb bus with zone crossfade. IRs ≤ ~2 s, decoded at zone load, because Chrome sets convolver buffers on the main thread.
  - Fallback: pyroomacoustics.
- **Occlusion**: raycast against simplified geometry → per-source lowpass + gain.
- **Spatialisation**: **SADIE II** HRTF (Apache 2.0) via a custom convolver, or native `PannerNode` HRTF as fallback.
- **Anti-repetition**:
  - Round-robin pools of 8–12 takes per surface, with ± pitch and gain.
  - Granular ambience beds in an AudioWorklet.
  - Incommensurate loop layering.
  - Rain layers driven by the weather tape.

### Programmatic audio production (decided 2026-10-11)
**Claude sources and produces all audio programmatically.** It downloads openly licensed recordings by script and builds the game's tracks with **ffmpeg** plus Python DSP. No manual DAW work. Field recordings stay an *optional upgrade* that plugs into the same pipeline.

1. **Fetch** (scripted, licence-filtered, provenance logged per file):
   - **Freesound API v2.**
     - Query by tags, geotag (Tokyo/Japan) and licence filter (CC0 / CC-BY only).
     - Token auth only returns ~128 kbps previews. **Original-quality downloads need a one-time OAuth2 authorisation by the user** (Freesound account + API credentials).
   - **Internet Archive** (radio aporee mirrors, often lossless). The advanced search API needs no auth. Licence per item, so SA is case by case.
   - **Kenney** (CC0) direct downloads.
   - Raw downloads go to `data/raw/audio/` (gitignored), re-fetchable from the manifest.
2. **Analyse** (Claude can't listen, so it measures):
   - `ebur128` / `loudnorm` loudness.
   - `astats` clipping and DC offset.
   - Noise floor.
   - Sample rate and bit depth, plus true quality (detect upsampled MP3 via spectral cutoff).
   - **Spectrogram images** (`showspectrumpic`) that Claude inspects visually.
   - Reject files below the quality floor.
3. **Clean**:
   - Trim, de-click, high-pass rumble.
   - Denoise: `afftdn` / `anlmdn` / `arnndn`.
   - EQ: `firequalizer`.
   - Resample to 48 kHz.
4. **Synthesise and design** (ffmpeg filtergraphs + Python numpy/scipy/soundfile):
   - Layering: `amix`.
   - Seamless loops: `acrossfade`, zero-crossing and spectral-match loop points.
   - Pitch and time variants for round-robin pools: `rubberband`, `asetrate`.
   - **Surface variants** synthesised from clean sources. Examples: wet footstep = dry step + splash transient + shelf EQ; metal grating = step + resonant comb.
   - Granular ambience beds.
   - Procedural layers: wind, rain density, hums, crossing chirps, the Tōryanse melody.
5. **Spatialise offline where useful**: convolve with the **Steam Audio IRs baked from PLATEAU geometry** via `afir`. Example: an alley-reverb bake for one-shots. Real-time zone reverb stays in Web Audio.
6. **Master and encode**:
   - Loudness targets per category (ambience, foley, signals, music).
   - **Opus** (`libopus`) for the web. FLAC masters kept locally.
   - Commit only shipped outputs that are CC0/CC-BY (or our own synthesis), with full provenance.
7. **Review gate**: every batch ships with a listening playlist. The **user's ears sign off**, because measurement alone can't judge "authentic".

**Toolchain check (this machine, ffmpeg n9.0.2):** `rubberband`, `afir`, `loudnorm`, `ebur128`, `afftdn`, `anlmdn`, `arnndn`, `amix`, `acrossfade`, `firequalizer`, `showspectrumpic`, `libopus`, `libvorbis`, `flac` are all present.

**Honest limits**:
- This gets **authentic Tokyo, acoustically placed in Shinjuku geometry**, not recordings of the actual Kabukicho, Golden Gai or Omoide Yokocho.
- Gaps with no open source (umbrella rain, dress shoes on wet tile/metal, suit rustle) are **synthesised from the nearest real recordings**. That's good, but a field recording would beat it.

## 13. Input, camera, browser

- **Camera (keyboard-only capable)**:
  - Smoothed auto-follow behind velocity, with a free-move zone.
  - **Q/E orbit**, recenter key, ease back after manual input.
  - Collision pull-in (dense alleys).
  - Optional pointer-lock look: try `unadjustedMovement`, fall back to normal, make it a setting.
  - Lock-on comes later, for combat.
- **Keys**:
  - **≤ 3 simultaneous keys** per action (laptop rollover).
  - Prefer tap or toggle (sprint toggle, buffered actions). A context-sensitive **traverse key** for hops and hood slides.
  - **No Cmd bindings**, no F-keys or Fn, no Ctrl+arrows.
  - Esc = pause (pointer-lock exit).
  - Rebinding screen.
  - Keyboard Lock API in fullscreen (Chrome).
  - `beforeunload` guard.
- **Simulation**: fixed-timestep simulation decoupled from rAF. Measure the actual rAF interval.
- **Chrome WebGPU**:
  - Feature-detect `shader-f16`, `subgroups`, `timestamp-query` (timestamps quantised to 100 µs). Keep fallbacks.
  - Profile with our own frame-time graph.
  - **wasm32 only** (no memory64); keep the shared memory maximum modest.
  - Chrome Battery Saver can throttle frame rate, so detect it and hint.

## 14. Licensing & provenance rules

1. **Never commit**:
   - Film footage, frames or film audio (John Wick or otherwise).
   - SMPL / SMPL-X model files or SMPL-based checkpoints.
   - LaFAN1 (CC BY-NC-ND).
   - AMASS and its constituents, HumanML3D, Motion-X, BONES-SEED.
   - Raw Mixamo files.
   - Sonniss, BBC RemArc, raw Pixabay files.
   - NC-licensed assets.
   - Share Textures files.
   - Model weights.

   These live only in `private/` (gitignored) or are fetched by scripts.
2. **Derived motion** ships only as joint rotations on **our own skeleton**.
3. **Every shipped asset** gets a provenance entry: source URL, author, licence, transformation applied, tool/model + seed if generated. CI audits it. Kept in a manifest (`provenance/` — format TBD).
4. **Prefer CC0 / CC-BY / MIT / Apache / BSD / OFL.** CC BY-SA only case by case, with the file kept under SA. ODbL for any OSM-derived layer.
5. **Audit MakeHuman "CC0" packs per file.** Some files carry AGPL or CC-BY headers.
6. **Required attributions**: PLATEAU (出典：国土交通省 PLATEAU, modified), Open-Meteo (CC BY 4.0), 100STYLE, CMU, HYG, SADIE II, every CC-BY asset → `CREDITS.md`.
7. **The character is original** (no likeness). Real brand signage and logos are never reproduced.
8. Research tool licences acceptable for this non-commercial open project: GVHMR (non-profit, derivatives open source), SMPL (non-commercial art), NVIDIA source licences.
   - These tools run offline only and never ship:
     - YOLO weights: AGPL-3.0.
     - HMR2 checkpoint: SMPL-based.
     - ViTPose: Apache-2.0.
     - GVHMR fork: ZJU non-commercial (its `pyproject` "MIT" classifier is wrong).
     - Steam Audio SDK binaries.
9. **Exception: motion derived through SMPL/SMPL-X** (GVHMR on film footage) ships under **CC BY-NC 4.0**, not CC BY 4.0, as a documented exception (decided 2026-10-12, §17 q6). It stays separate from the CC BY 4.0 motion (100STYLE, CMU, Kimodo fill) so the rest of the project stays freely reusable. The audit policy (`licences.json`) gets a scoped entry for it when the first such clip ships.

## 15. Benchmark ladder

Each milestone has measurable pass criteria and a git tag. Thresholds marked *(cal.)* are calibrated in Phase 0.

| Tag | Milestone | Pass criteria |
|---|---|---|
| `m0` | **Phase 0 spikes** | All spikes in [§18](#18-phase-0--spikes) run with recorded numbers |
| `m1` | **Character look** | Turntable set (front/¾/profile/close-up) approved by the user. Budgets in §7 met. Licence audit clean. |
| `m2` | **Character in browser gym** | Motion-matched locomotion (idle → sprint, starts, stops, pivots, turn-in-place, stairs, slopes). Foot slide during contact < *(cal.)* cm/s. **p95 frame ≤ 16.6 ms and median ≤ 12 ms on the M4 Air after 20 min warm-up.** Tab memory ≤ 1.5 GB. Keyboard-only playable. |
| `m3` | **Wick identity** | Wick walk, draw/holster, C.A.R.-style stance + aim, reloads, hop and hood slide, shooting-range targets. Secondary motion (tie, hem, hair) stable in all clips. |
| `m4` | **One Kabukicho block** | Painted Neon-Noir at night in rain, matching the Blender look-dev target. `m2` performance criteria still hold. |
| `m5` | **Starting district** | ~1.5 km² streamed, day/night with real ephemeris, weather tape replay. Performance and memory criteria hold while traversing. |
| `m6` | **Soundscape** | Zone IR reverb, occlusion, per-surface footsteps, weather-driven rain, no audible repetition in a 10-minute walk. |
| `m7` | **Story** | TBD |
| `m8` | **Enemies and gun-fu** | TBD |

## 16. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Stylised face via scripted sculpting falls short | 🔴 | Verifier-heavy best-of-N loop, measurable checks, many iterations. User sign-off gates `m1`. |
| Neon-rain look over budget on the Air | 🔴 | Measure on the Air in Phase 0 / `m4`. Dynamic resolution, half-res passes, baked spill. |
| No authentic Shinjuku audio under open licences | 🟠 | Programmatic pipeline (§12): real Tokyo CC0/CC-BY recordings + ffmpeg synthesis + PLATEAU-baked acoustics, with a user listening gate. Field recording as an optional upgrade. |
| GVHMR CPU throughput / quality on film footage | 🟠 | **Measured**: 17.8 h per 60 min with bf16 (4 × 4), ~11–12 h with the accuracy trade. Clean walks look plausible (8.7 px reprojection error). Shot filtering, bf16, 100STYLE/CMU carry core locomotion. |
| Detector failure on night and action shots means a low usable yield | 🔴 | Filter by track coverage and confidence. Take falls and stunts from mocap. Prioritise clean day or BTS footage. |
| Third-party GVHMR fork | 🟡 | Pinned commit + `--frozen` lockfile + a source bundle in `private/src/`. Upstream plus CPU patches is the fallback. |
| ~~MPFB2 headless untested~~ | ✅ | **Retired 2026-10-12**: verified in spike 1. |
| WASM threads depend on nightly + build-std | 🟠 | Pin a dated nightly in `core/build-web.sh` and bump it deliberately. The stable fallback is single-threaded WASM with the sim on the main thread. |
| WASM size: Rapier + parry ≈ 86 % of 506 KB (brotli) | 🟡 | Fine for now. Revisit if load time matters (lazy-load physics, or a slimmer collider set). |
| YouTube blocks yt-dlp from this machine ("not a bot", datacenter IP) | 🔴 until the cookies land | Root-caused in spike 3. Every documented yt-dlp route failed. **One user step fixes it:** export cookies, then `fetch-youtube.sh`. |
| Suit deformation in extreme poses | 🟠 | Helper bones + Dem Bones baking + correctives |
| PLATEAU LOD2 coverage, `nusamai` glTF sink thin | 🟡 | **Confirmed**: the sink's attributes are broken, and LOD2 is 46 % across the district. Mitigation in place: our own chunk writer, plus procedural facades for LOD1. |
| Licence drift (PLATEAU wording, CMU, PARC provenance, SFU) | 🟡 | Provenance manifest + audit before use |

## 17. Open questions

1. ~~Audio route~~ **Resolved 2026-10-11**: programmatic fetch + ffmpeg/Python synthesis by Claude (§12). Still open: whether field recordings (home foley, Shinjuku ambience) are added later as an optional upgrade.
2. Story development (after world).
3. ~~Provenance manifest format~~ **Adopted 2026-10-12** as the working format (it evolves as needed; changes go in the Decision log):
   - One `provenance/<domain>.jsonl` per domain (`audio`, `mesh`, `data`), validated against `record.schema.json`.
   - A licence policy in `licences.json` with allow, note and deny lists.
   - A stdlib `audit.py` with `--check-files` and `--release` modes. It fails on duplicate ids, disallowed licences and rejected inputs.
   - `audit_makehuman.py` checks MakeHuman file headers.
4. Whether Kimodo's licence text and the PARC raw-mocap provenance hold up.
5. ~~Repo layout~~ **Adopted 2026-10-12** as a living convention (where new things go), not a freeze. The spikes built it as proposed, plus `core/build-web.sh`, `bench/server.mjs` and `pipeline/{audio,video-to-motion}/`. Changes go in the Decision log.
6. ~~Licensing of motion derived through SMPL/SMPL-X~~ **Resolved 2026-10-12: non-commercial exception** (see §14 rule 9). Background:
   - The SMPL-X model licence allows "non-commercial … artistic projects".
   - It forbids making derivatives of the Model & Software available to third parties without Max Planck's written permission.
   - It is silent on motion estimated with the model.
   - Our CC BY 4.0 asset licence allows commercial reuse downstream, which conflicts with that.
   - Options were: email smpl@max-planck-innovation.de, or ship GVHMR-derived motion under a non-commercial licence as a documented exception. The user chose the exception.
7. ~~Public Domain Mark items~~ **Resolved 2026-10-12: accepted with a note** (each record needs a `licence_note`; credit the recordist anyway). `licences.json` keeps them under "note".
8. **m2 frame-time definition** (proposed in spike 4; **used provisionally** until the user decides):
   - "p95 ≤ 16.6 ms" applies to the rAF interval.
   - "median ≤ 12 ms" applies to max(CPU frame p50, GPU pass p50).
   - Measure after 5 min warm-up, for at least 20 min.

## 18. Phase 0 — spikes

**User prerequisites (before Phase 0, so nothing blocks):**
- Register for **SMPL / SMPL-X** and accept the licence (GVHMR needs them). The files go in `private/`.
- Create **Freesound** API credentials and complete the OAuth2 authorisation. Tokens go in a gitignored `.env`.
- Run the `sudo pacman -S …` line Claude provides (Blender, openvino, onnxruntime-cpu).

**Execution:**
- Spikes run **in parallel, in git worktrees where applicable**.
- Track A runs spikes 1 → 2 (Blender). Spikes 4 and 5 are separate tracks.
- Spike 6 follows 5.
- Spikes 3 and 7 start as soon as the credentials land.
- The result is one synthesised `m0` report.

**Status (2026-10-12).** All reports are in `bench/m0/`. Idle 16-thread reruns are in `bench/m0/idle-rerun.md`. Handoff: `HANDOFF.md`.

| # | Spike | Status | Remaining |
|---|---|---|---|
| 1 | MPFB2 headless | ✅ pass | – |
| 2 | Render test | ✅ pass | – |
| 3 | GVHMR on CPU | 🟡 done except footage | User: YouTube cookie export |
| 4 | Browser skeleton | 🟡 done except Air run | User: 20–30 min Air telemetry session |
| 5 | PLATEAU chunk | ✅ pass | – |
| 6 | Steam Audio IR | ✅ pass | User: headphone check of `alley-01-binaural.wav` |
| 7 | Audio pipeline | 🟡 done except listening | User: listening gate (`bench/m0/listening-playlist.md`) |

**M4 Air measurement:** the user opens the tunnel URL in Chrome and keeps the tab in front. The page POSTs frame-time histograms and memory to a local `bench/` endpoint on this machine, so Claude reads the results directly.

1. **Install** Blender 5.2 (pacman). Run MPFB2 headless: create a human, add the `game_engine` rig, add the CC0 suit, export glTF.
2. **Render** test: Cycles CPU turntable and EEVEE via llvmpipe/lavapipe, with timings.
3. **GVHMR** on CPU in a uv Python 3.11 env (fork; see §8), on one clean JW4 stair or behind-the-scenes shot. Measure s/frame per stage (YOLO, ViTPose, features, GVHMR) and output quality.
4. **Browser skeleton**: Vite + three WebGPU + Rust/WASM threads with COOP/COEP. Served over an SSH tunnel and measured on the M4 Air (frame time, memory).
5. **PLATEAU**: fetch the Shinjuku FY2025 data, parse one Kabukicho mesh cell with `nusamai`, reproject to EPSG:6677, export one chunk.
6. **Steam Audio**: bake one alley impulse response from that chunk.
7. **Audio pipeline**:
   - Fetch ~10 CC0/CC-BY Tokyo and footstep files via Freesound + Internet Archive.
   - Analyse them (loudness, spectrogram).
   - Produce one seamless ambience loop and one 8-take footstep pool (dry + synthesised wet) through ffmpeg.
   - Convolve with the spike-6 IR.
   - Hand the listening playlist to the user.

## 19. Research references

**Motion**
- GVHMR https://github.com/zju3dv/GVHMR
- GVHMR CPU/MPS fork https://github.com/ryanrudes/gvhmr
- PromptHMR https://github.com/yufu-wang/PromptHMR
- mixamo-llm-mocap https://github.com/squall01337/mixamo-llm-mocap
- 100STYLE https://zenodo.org/records/8127870
- CMU https://mocap.cs.cmu.edu/
- PARC dataset https://huggingface.co/datasets/mxucg/PARC
- Kimodo https://github.com/nv-tlabs/kimodo
- Motion-Matching https://github.com/orangeduck/Motion-Matching
- Kansei https://github.com/Siroko/kansei
- Bollo inertialization https://media.gdcvault.com/gdc2018/presentations/bollo_david_inertialization_high_performance.pdf
- TransNetV2 https://pypi.org/project/transnetv2-pytorch/

**Character**
- MPFB2 https://static.makehumancommunity.org/mpfb/
- MPFB script samples https://github.com/makehumancommunity/mpfb2/blob/master/script_samples/index.md
- suits01 https://static.makehumancommunity.org/assets/assetpacks/suits01.html
- Anny https://github.com/naver/anny
- FLAME licence https://flame.is.tue.mpg.de/modellicense.html
- ICT-FaceKit https://github.com/USC-ICT/ICT-FaceKit
- Dem Bones https://github.com/electronicarts/dem-bones
- three-vrm springbone https://www.npmjs.com/package/@pixiv/three-vrm-springbone
- BlenderGym https://arxiv.org/abs/2504.01786
- BlenderAlchemy https://arxiv.org/pdf/2404.17672
- Kajiya-Kay / Scheuermann https://web.engr.oregonstate.edu/~mjb/cs557/Projects/Papers/HairRendering.pdf

**World**
- PLATEAU Shinjuku FY2025 https://www.geospatial.jp/ckan/dataset/plateau-13104-shinjuku-ku-2025
- PLATEAU site policy https://www.mlit.go.jp/plateau/site-policy/
- PLATEAU GIS Converter https://github.com/MIERUNE/plateau-gis-converter
- Building attributes spec https://www.mlit.go.jp/plateaudocument/toc4/toc4_02/toc4_02_03/toc4_02_03_01/_bldgbuilding/
- Tokyo point cloud https://www.geospatial.jp/ckan/dataset/tokyopc-23ku-2024
- Poly Haven https://polyhaven.com/license
- ambientCG https://docs.ambientcg.com/license/

**Rendering**
- Threejs-Punk https://github.com/ektogamat/threejs-conference
- Neon Zenith https://github.com/billpwchan/neon-zenith
- Hi-Fi Rush toon rendering https://gdcvault.com/play/1034330/3D-Toon-Rendering-in-Hi
- Sable / Moebius in three https://blog.maximeheckel.com/posts/moebius-style-post-processing/
- Lagarde wet surfaces https://seblagarde.wordpress.com/2013/03/19/water-drop-3a-physically-based-wet-surfaces/
- three ClusteredLighting https://threejs.org/docs/pages/ClusteredLighting.html

**Sky / weather**
- @pmndrs/sky https://github.com/pmndrs/sky
- Open-Meteo https://open-meteo.com/en/docs/historical-weather-api
- astronomy-engine https://github.com/cosinekitty/astronomy
- HYG https://codeberg.org/astronexus/hyg

**Audio**
- Freesound https://freesound.org/help/faq/
- radio aporee https://aporee.org/maps/info/
- Steam Audio https://github.com/ValveSoftware/steam-audio
- SADIE II https://www.york.ac.uk/sadie-project/database.html
- pyroomacoustics https://pyroomacoustics.readthedocs.io/

**Browser / Mac**
- Keyboard Lock https://developer.chrome.com/docs/capabilities/web-apis/keyboard-lock
- M4 Air throttling https://www.notebookcheck.net/The-passively-cooled-M4-SoC-makes-the-competition-look-old-Apple-MacBook-Air-13-M4-base-model-review.1002534.0.html

---

## Decision log

### 2026-10-12 — m0 gate rulings (user)
- **GVHMR**: Python 3.11 + `ryanrudes/gvhmr` fork accepted, pinned.
- **Footage**: studio-supplied featurettes hosted by press outlets (e.g. IGN) count as official. The IGN Sacré-Cœur behind-the-scenes clip is added to the fetch list.
- **Public Domain Mark** audio: accepted with a note.
- **Repo layout and provenance format**: adopted as living conventions, not frozen. Changes are logged here.
- **SMPL-derived motion**: ships under a non-commercial exception (CC BY-NC 4.0), §14 rule 9.
- **m2 frame-time definition**: used provisionally; user to review.
- SMPL password rotation: done by the user.

### 2026-10-12 — Phase 0 executed (autonomous run)
- All seven spikes ran as parallel agents in git worktrees and were merged to `main`. Spike 3 got a follow-up agent to find root causes and finish it.
- **Findings folded into this file:**
  - The iGPU runs EEVEE headless.
  - MPFB2 headless works; that risk is retired.
  - nusamai's glTF sink was replaced by our own chunk writer.
  - Steam Audio calibration.
  - The WASM threads recipe (nightly).
  - Measured GVHMR throughput.
  - Foot lock v2.
  - The YouTube datacenter-IP root cause.
- **Provenance:** a JSONL manifest format adopted as a draft (pending approval; §17 q3).
- **Security fix:** credentials no longer reach `curl` via argv in `fetch-body-models.sh` and `freesound-auth.sh`. One SMPL password leaked through `pgrep -a`; the user is rotating it.
- **Pending user gates:** listed in §18 Status and in `HANDOFF.md`.

### 2026-10-11 — alignment interview
- **Working agreement**: Claude works autonomously and stops only at gates (`m1` look, audio listening, Air measurements, credentials, installs). Independent work runs in parallel, in git worktrees where that applies. The user runs `sudo` installs from commands Claude provides.
- **Licence**: MIT for code, CC BY 4.0 for original assets.
- **Hosting**: public GitHub `code-akram/or3`, with Cloudflare Pages for the playable build. Large binaries are rebuilt by the pipeline and published as releases or on the CDN. No LFS.
- **Footage**: official studio clips, trailers and behind-the-scenes featurettes, fetched with `yt-dlp`.
- **Air benchmark**: automatic telemetry, POSTed from the page to a local endpoint.
- **Credentials**: the user sets up SMPL/SMPL-X and Freesound OAuth before Phase 0.
- **Weapon**: an original fictional competition pistol. No real marks.
- **Vehicles**: abandoned, unbranded fictional cars. No traffic.
- **Time**: accelerated, configurable day with tape-replayed weather.
- **Music**: diegetic only.
- **Repo layout**: proposed in §6, approved at the `m0` gate.

### 2026-10-11 — audio route
- **Claude produces all audio programmatically.** It downloads openly licensed recordings (Freesound API, Internet Archive, Kenney) and builds tracks with ffmpeg + Python DSP. The pipeline is in §12.
- The user's listening review is the quality gate.
- Field recordings are an optional later upgrade.

### 2026-10-11 — brainstorming closed
- Art direction **Painted Neon-Noir** confirmed.
- Brainstorming closed. Project directory created. Phase 0 defined.
- Audio field-recording route still open.

### 2026-10-11 — scope refinement
- **Parkour and climbing dropped**: traversal is grounded. **Knee-high hop / car-hood slide kept.**
- Chrome only for now.
- Character must be nailed without compromise. Audio must be authentic.
- John Wick footage used as much as needed. Never committed verbatim.

### 2026-10-11 — foundations
- Codename `or3` (replacing "John Wicked"). Never used in identifiers.
- Personal, non-commercial, fully open source. A frontier-model benchmark.
- Locked 60 fps on MacBook Air M4 (60 Hz).
- City: **Tokyo Shinjuku** (PLATEAU), over NYC: open data and art fit.
- Compute: this machine only.
- Keyboard first.
- Story base: post-recursive-intelligence, humanity Type-II and gone, or3 remains by choice. No NPCs.
- Stack: Three.js WebGPU + TSL, single Rust→WASM core (animation + Rapier), Blender headless pipeline. Godot, Unity and Unreal rejected (web performance, export, licensing).
