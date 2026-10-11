# Spike 6: Steam Audio alley impulse response

**Status: done with Steam Audio. The pyroomacoustics fallback was not needed.**
- The IR is baked from the spike-5 Kabukicho chunk for a 2.0 m-wide alley on the west edge of Golden Gai.
- It's written to **`/home/akram/code/or3/data/build/audio/ir/alley-01.wav`** (48 kHz, 24-bit, stereo, ~1.05 s).
- Variants sit next to it: `-wet`, `-binaural` and `-mono`, plus `alley-01.json` with every number.

Date: 2026-10-12. Ryzen 7 7700, shared with other spikes. Steam Audio ran with 3 threads.

## What was done (exact versions)

| Item | Version / value |
|---|---|
| SDK | **Steam Audio 4.8.1** C SDK (`steamaudio_4.8.1.zip`, GitHub release 2026-02-11). 181,171,027 B, SHA-256 `4a0aa5ec…1d5449`. Linux x64 `libphonon.so` (40 MB). Apache-2.0, plus `THIRDPARTY.md` (Intel IPP Simplified Licence, Embree, FFTS, PFFFT, MySOFA, …). |
| Bindings | `bindgen-cli` **0.73.2** (cargo install, `-j3`) with libclang **18.1.1** from the PyPI `libclang` wheel in a uv venv. The system only has `libclang-cpp`. Generated once and committed: `tools/acoustic-bake/src/phonon_sys.rs`. Reproducible with `bench/m0/spike6/bindgen.sh`. |
| Program | `tools/acoustic-bake` (Rust 1.98.1, workspace member; reuses `plateau-chunk`'s GLB reader). Links `libphonon.so` from `data/raw` via rpath. Nothing from the SDK is committed. |
| Geometry | `chunk_e-11800_n-34000_s200.raw.glb` from spike 5: 190 LOD2 buildings + roads, 23,303 triangles, plus a 600 m ground plane |

I chose Rust FFI over Python ctypes because bindgen gets the large `IPLSimulationInputs` and `IPLSimulationSettings` structs right mechanically. ctypes would have meant hand-transcribing them.

### Bake pipeline (`acoustic-bake`)

1. **Load the chunk.** `bldg` and `tran` meshes in local Y-up metres. Steam Audio also uses right-handed Y-up, so no conversion is needed.
2. **Find an alley automatically.**
   - Search a 1 m grid inside the chunk. For each point, find the ground height (road surface below, or the nearest building base if there's no road polygon).
   - Reject points under a building or roof. Require open sky.
   - At 1.6 m, cast 16 horizontal rays (our own uniform-grid ray caster). Keep points where:
     - the narrowest opposite ray pair hits building walls 2–5 m apart;
     - the point is centred to within 1 m;
     - the perpendicular direction is open for at least 16 m.
   - Score by length and narrowness. 403 candidates were found in 1.5 s.
   - Winner:
     - **width 2.0 m**, open length 72 m, ground at T.P. 31.0 m;
     - EPSG:6677 ≈ E −11672, N −33948 (≈ 35.6939 N, 139.7044 E): the west edge of Golden Gai, between the long building on Shiki-no-michi and the first Golden Gai row.
   - See the close-up `img/chunk-kabukicho-alley.png` (red = source, blue = listener).
3. **Place source and listener.** Both at 1.6 m above ground, **4.0 m apart along the alley axis**. The listener faces the source. Line of sight is clear.
4. **Build the scene.** `iplSceneCreate` (default Phonon ray tracer), one `IPLStaticMesh`, three materials (Steam Audio presets):
   - **concrete** {0.05, 0.07, 0.08 | scat 0.05 | trans 0.015, 0.002, 0.001} on every building surface, the roads and the ground plane;
   - **glass** {0.06, 0.03, 0.02 | 0.05 | 0.060, 0.044, 0.011} on vertical walls of 401/402/403 buildings (10,328 triangles);
   - a 600 × 600 m concrete ground plane 2 cm below the alley's ground. Most alleys have no `tran` polygon.
5. **Simulate.**
   - `iplSimulatorCreate`: REFLECTIONS, CONVOLUTION, 262,144 rays, 1,024 diffuse samples, 64 bounces, 2.0 s, Ambisonic order 1, 3 threads.
   - Then one source, `iplSimulatorRunReflections`, and `iplSourceGetOutputs`.
6. **Render the IR.**
   - Create an `IPLReflectionEffect` with the simulated IR handle.
   - Prime it with 4 silent frames so the IR cross-fade has settled.
   - Push a unit impulse through it, then zeros until 2 s. The result is a 4-channel (ACN, orthonormal SH) reflection IR.
7. **Set the time base.** I read the Steam Audio source (`reflection_simulator.cpp`). The simulator **subtracts the direct-path delay**, so a reflection IR's t = 0 is the direct-sound arrival. We keep that convention: the direct impulse goes at sample 0, and the 4 m / 11.7 ms (560-sample) propagation delay is removed and recorded.
8. **Calibrate the level** (see below). Reflections are scaled by **−8.6 dB**.
9. **Add the direct path.** Gain 1/r = 0.25, encoded with `iplAmbisonicsEncodeEffect` (primed, so the first-order channels aren't cross-faded away) in the same world frame.
10. **Decode with Steam Audio's own `iplAmbisonicsDecodeEffect`.** Listener orientation:
    - mono (`-mono`);
    - stereo panning (`alley-01.wav`, `-wet`);
    - binaural with the default HRTF (`-binaural`).
11. **Trim and write.**
    - Trim where the energy decay curve reaches −60 dB, with a 10 ms fade-out.
    - Normalise every file with one shared gain (+12.2 dB), so the loudest full IR peaks at −1 dBFS. The wet IR keeps its true level relative to the full one.
    - Write 24-bit PCM WAV.

### What each file is

| File | Content | Use |
|---|---|---|
| `alley-01.wav` | Direct + reflections, stereo (Steam Audio panning decode), listener facing the source | Offline `afir` convolution of dry one-shots ("this sound, 4 m away in the alley"). **Spike 7 uses this.** |
| `alley-01-wet.wav` | Reflections only, stereo, same gain | Shared `ConvolverNode` reverb bus (dry path rendered separately) |
| `alley-01-binaural.wav` | Direct + reflections, default-HRTF binaural | Headphone listening review |
| `alley-01-mono.wav` | Direct + reflections, mono | Analysis |

### Level calibration (important)

Steam Audio's raw reflection energy isn't on the same scale as a 1/r direct path. I ran the same bake with **only the ground plane**:
- A single specular and diffuse reflector should give image-path energy (1 − ᾱ)/d² = 0.9333 / 5.12² = **0.0356**, relative to a unit source at 1 m.
- Steam Audio returned **0.258** (W channel × √4π, because Steam Audio uses orthonormal SH; its mono decode of a plane wave is exactly ×√4π, measured as 1.000).
- That is **+8.6 dB hot**.

The calibration run is repeated automatically on every bake (0.02 s) and its gain applied to the reflections. With it, DRR is −7.9 dB; without it, −16.5 dB. A rough image-source estimate for a 2 m concrete canyon with ground (≈ −8 to −10 dB) favours the calibrated value.

**The listening gate should confirm this.** If the user prefers it wetter, `--calibrate 0` gives Steam Audio's raw balance.

## Measured numbers

Measured on the mono decode of the full IR (Schroeder backward integration over the untrimmed 2 s). Repeats are the same bake re-run, because the ray tracer is stochastic. Load average was 8–9 (other spikes running); threads = 3.

| Metric | Shipped bake | Repeats 1 / 2 / 3 |
|---|---:|---|
| EDT | **0.205 s** | 0.201 / 0.202 / 0.203 |
| T20 → RT60 | **0.344 s** | 0.332 / 0.340 / 0.336 |
| T30 → RT60 | **0.777 s** | 0.729 / 0.763 / 0.699 |
| EDC −20 dB at | 0.089 s | |
| EDC −60 dB at (= file length) | **1.050 s** | 0.683 / 1.203 / 0.682 |
| DRR (calibrated) | **−7.98 dB** | −7.92 / −7.94 / −7.94 |
| T20 per octave, 125 / 250 / 500 / 1k / 2k / 4k / 8k Hz | 0.53 / 0.38 / 0.44 / 0.47 / 0.46 / 0.46 / 0.37 s (band-passed, noisy) | |
| `alley-01.wav` | 48 kHz, s24le, 2 ch, 1.050 s, 302,540 B | |

The decay is double-sloped. Fast early decay inside the canyon (EDT 0.2 s, T20 0.34 s) is followed by a weak, slower, sparse tail: paths escaping along the alley, and long ground/façade bounces. The −60 dB point varies run to run (0.68–1.2 s) because the late 10 ms bins are sparsely sampled.

| Timing (3 threads) | Seconds |
|---|---:|
| Load chunk + build ray grid | 0.005 |
| Alley search (our ray caster, ~29k candidate points × 18 rays) | 1.50 |
| Steam Audio scene build (23,305 tris) | 0.027 |
| **`iplSimulatorRunReflections`** (262,144 rays, 64 bounces) | **0.56–0.67** |
| Render IR through the reflection effect | 0.009 |
| Calibration run (ground only) | 0.026 |
| Decode × 5 | 0.029 |
| **Total bake** | **2.2–2.3** |

Ray-count scaling: 8,192 rays → 0.023 s; 65,536 → 0.16 s; 262,144 → 0.6 s. EDT and T20 are already stable at 65k rays. More rays mainly fill in the sparse tail.

## Commands to reproduce

```sh
bench/m0/spike6/fetch-sdk.sh            # SDK zip + sha256 + extract into data/raw/steam-audio/sdk
bench/m0/spike6/bindgen.sh              # optional: regenerate phonon_sys.rs (cargo-installs bindgen, uv venv for libclang)
bench/m0/spike5/chunk.sh                # the chunk (spike 5) if not present
bench/m0/spike6/bake.sh 3 3             # bake + 3 repeat runs → data/build/audio/ir/alley-01*.wav, alley-01.json
# single run with options:
target/release/acoustic-bake --chunk data/build/world/chunk_e-11800_n-34000_s200.raw.glb \
  --out data/build/audio/ir/alley-01.wav --report data/build/audio/ir/alley-01.json \
  [--rays 262144] [--bounces 64] [--duration 2.0] [--threads 3] [--sep 4.0] \
  [--alley x,z,deg] [--calibrate 0|1] [--save-obj /tmp/scene]
```

## Failures and workarounds

| Problem | Workaround |
|---|---|
| `bindgen` needs `libclang.so`; the system has only `libclang-cpp.so` | PyPI `libclang` 18.1.1 wheel in a uv venv → `LIBCLANG_PATH` (userland, no sudo) |
| Flag enums (`IPLSimulationFlags`, …) as Rust enums would be UB when OR-ed | `--bitfield-enum 'IPL.*Flags'` |
| The first reflection IR came out with energy from t = 0 | Not a bug: Steam Audio's time base is the direct arrival (confirmed in source). Direct impulse placed at sample 0. |
| The encode effect cross-fades its direction over the first frame, so the impulse at sample 0 had only W (first-order ≈ 0) | Prime the encode and decode effects with silent frames |
| Raw reflection level +8.6 dB above geometric theory | Automatic ground-plane calibration (above) |
| Stochastic late tail makes the file length vary (0.68–1.2 s) | Trim at EDC −60 dB. Optionally average several runs later. |

## Risks and recommendation

- **Steam Audio is practical:**
  - ~0.6 s per IR at high ray counts on 3 cores, and ~2 s end to end;
  - straightforward FFI;
  - Apache-2.0;
  - nothing to vendor.

  Baking one IR per zone (alley, Golden Gai, underground mall, concourse, open street), or a small grid per zone, is trivial in compute terms.
- **Early-reflection detail is limited.**
  - Steam Audio's real-time convolution path builds the IR from **10 ms energy bins** filled with noise. The first 10 ms is flat noise, and discrete flutter echoes between the 2 m-apart walls aren't resolved.
  - The early profile in `alley-01.json` (2 ms bins: 0, −3.4, −3.5, −4.5, …, −8.2 dB over 20 ms) shows this.
  - If the listening review finds the alley "smeared", combine an image-source early part (pyroomacoustics-style, or our own ISM, 0–50 ms) with the Steam Audio late part.
- **Level calibration is our own.** It's documented and easy to switch off, but the user's ears decide (listening gate).
- **Geometry is idealised.**
  - LOD2 boxes have no signage, AC units, awnings or clutter, so a real Golden Gai alley is more diffuse and more absorptive.
  - The glass/concrete split is a heuristic.
  - The ground plane is flat at the alley's height.
  - Consider raising `scattering` to ~0.3–0.5 for "street clutter" and comparing by ear.
- **Licensing.** `libphonon.so` bundles third-party binaries (Intel IPP under a no-reverse-engineering licence, and others). We only use it offline, and the shipped outputs (WAV IRs) are our own CC BY 4.0 content. Don't redistribute the SDK in the repo.
- Steam Audio also ships `lib/wasm/libphonon.a` (7 MB). Runtime use in the browser is possible later, but NOTES plans Web Audio `ConvolverNode`, which is fine.

**Recommendation:** adopt Steam Audio for zone IRs, with the calibration step and the "t = 0 = direct arrival" convention. Ship the `-wet` variant for the runtime reverb bus, and keep full IRs for offline one-shot placement. Revisit the early-reflection model only if the listening gate asks for it.

## User actions

- **Listening review** of `data/build/audio/ir/alley-01-binaural.wav` on headphones, and `alley-01.wav` on speakers, once spike 7 convolves real footsteps with it. Questions:
  - Does the −8.6 dB calibration sound right, or should it be wetter?
  - Is the early part acceptably "alley-like"?
- None blocking. No sudo was needed.

## Proposed NOTES.md updates

- §12 Acoustics, Steam Audio bullet. Add:
  - "Verified in spike 6: Steam Audio 4.8.1 via Rust FFI (`tools/acoustic-bake`), ~0.6 s per IR (262k rays, 64 bounces, 3 threads), 2 s max, order 1.
  - Steam Audio's reflection IR time base is the **direct arrival** (it subtracts the direct-path delay).
  - Its raw reflection energy is ~8.6 dB above geometric acoustics relative to a 1/r direct path, so bakes are **calibrated against a ground-plane-only run**.
  - Early reflections are 10 ms-binned noise, so there are no discrete flutter echoes. If needed, add an image-source early part."
- §12 Acoustics: "First alley IR (Golden Gai west edge, 2.0 m wide): EDT 0.20 s, T20 0.34 s, T30 ~0.75 s, DRR −8 dB at 4 m. Files: full (direct + reverb), `-wet` (reverb bus), `-binaural`, `-mono`; 48 kHz s24."
- §6 Offline pipeline: "Rust FFI bindings generated with bindgen 0.73.2 + libclang from the PyPI wheel (uv venv); the Arch box has no `libclang.so`."
- §14 Licensing: "Steam Audio SDK binaries (and their bundled IPP/Embree licences) are build-time only. Never commit or ship them. Baked IRs are our own output."
