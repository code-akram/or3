# Spike 7: audio pipeline (NOTES.md §12, §18 item 7)

**Status: done. Waiting on the user's listening gate.** All 7 steps of §12 run from one script on this machine, with no manual DAW work:

1. Scripted, licence-filtered fetch from Freesound (OAuth originals) and Internet Archive.
2. Measured analysis plus a quality gate.
3. Cleaning.
4. A seamless 82 s ambience loop, and an 8-take dress-shoe pool with 8 synthesised wet variants.
5. Convolution with the **real spike-6 alley IR**.
6. FLAC masters plus Opus web encodes.
7. A listening page and a playlist.

A draft provenance format and its audit are implemented under `provenance/`. The audit passes: 113 records, 0 errors.

Branch `worktree-agent-a199afabbfee56047`. Code lives in `pipeline/audio/` (uv project, package `audiopipe`) and `provenance/`.

## Versions

| Tool | Version |
|---|---|
| ffmpeg | n9.0.2 (soxr resampler, libopus, afir, firequalizer, adeclick, afftdn, amix, acrossfade, ebur128, astats, showspectrumpic) |
| libopus | 1.6.1 |
| rubberband | 4.0.0 (measured, not used for the pool, see 4b) |
| libsoxr | 0.1.3 |
| flac | 1.5.0 |
| libsndfile | 1.2.2 |
| Python (uv env) | 3.14.7 |
| numpy | 2.5.4 |
| scipy | 1.18.1 |
| soundfile | 0.14.0 |
| uv | 0.12.20 |
| IR | Steam Audio 4.8.1 bake from spike 6: `data/build/audio/ir/alley-01.wav`, sha256 `ccaa57f351d2…` |

The pipeline itself caps ffmpeg at 3 threads with 1 filter thread, and the numpy work is single-threaded.

## 1. Fetch (13 files, 574 MiB, all CC0 / CC-BY / noted)

`audiopipe.fetch` reads `pipeline/audio/sources.toml`. For each entry it:
- re-checks the licence URL against `provenance/licences.json`;
- downloads into a **new per-item directory** under `data/raw/audio/{freesound,archive}/<id>/`;
- appends one record per file to `provenance/audio.jsonl`.

Handling of the Freesound token:
- It is read from `.env` inside Python and sent as an `Authorization` header.
- It is added with `add_unredirected_header`, so it never follows a CDN redirect.
- It is never printed.
- It is refreshed through `freesound-auth.sh --refresh` when it is within 30 min of expiry. A refresh was not needed in this run.

Candidate search is scripted too (`audiopipe.search`: licence filter, `{!geofilt}` geotag, tag filters).

The fetch took 4 min 27 s wall time. It made 26 requests: 20 to Freesound (2 s spacing, at most 30/min) and 6 to IA. Load average at the start was 2.15.

| id | what | licence | original |
|---|---|---|---|
| freesound:679335 | takecha, Shinjuku 22:07, geotag 35.6906,139.7073 | CC0 | WAV 48k/16 |
| freesound:679333 | takecha, Shinjuku 00:55 (karaoke leak, sirens) | CC0 | WAV 48k/16 |
| freesound:679334 | takecha, Shinjuku 19:06 | CC0 | WAV 48k/16 |
| freesound:380726 | sergeeo, "Shinjuku – August 2016" | CC-BY 3.0 | WAV 48k/24 |
| freesound:364865 | RutgerMuller, Tokyo street evening/night | CC0 | WAV 96k/24 |
| freesound:677641 | moky-sound, "In front of Shinjuku Station" (iPhone) | CC0 | WAV 96k/24 |
| freesound:205748 | Yuval, leather shoes on concrete (contact mics) | CC0 | WAV 48k/24 |
| freesound:560478 | jeroberts92, concrete dress shoes (MKH-50) | CC0 | WAV 48k/24 |
| freesound:742969 | Artninja, leather-sole slow walk, hard ground | CC-BY 4.0 | WAV 44.1k/32 |
| freesound:569313 | stecman, rain on tin roof | CC0 | FLAC 96k/16 |
| archive:aporee_70134_81690 | radio aporee, Shinjuku JR platform 2025, binaural | PDM 1.0 (noted) | WAV 48k/24 |
| archive:aporee_17483_20360 | radio aporee, Yurakucho alley 2013 | PDM 1.0 (noted) | **MP3** |
| archive:aporee_20539_23862 | radio aporee, Shibuya Dogenzaka crossings 2013 | CC BY-SA 3.0 (noted) | **MP3** |

**Finding: open Shinjuku recordings do exist.** NOTES §12 says no CC0/CC-BY Shinjuku-specific recordings exist. That is not right:
- **takecha's 2023 Shinjuku pack** (Freesound pack 37936, CC0) is geotagged at 35.6906,139.7073, on the east side about 500 m from Kabukicho.
- **sergeeo** (CC-BY 3.0) is geotagged in Shinjuku.
- There is a 2025 Shinjuku-station WAV on radio aporee (PDM).

None of these is Golden Gai or Omoide Yokocho specifically.

**Finding: the IA route is weaker than NOTES assumes.** NOTES says radio aporee mirrors are "often lossless". Of the 5 Tokyo aporee items inspected, only 1 has a lossless original; the others are MP3. Licences are also mostly BY-SA, NC-ND or the Public Domain Mark.

## 2. Analysis and quality gate

`audiopipe.analyse` measures each file and writes `data/build/audio/analysis/<id>.{json,png}`:
- ffmpeg `ebur128` (with true peak) and `astats`, which gives DC offset, flat factor, peak count and effective bit depth;
- numpy measures: clipped runs (≥ 3 samples at the absolute peak, near 0 dBFS); a noise floor (10th percentile of 50 ms RMS); an SNR proxy (p95 − p10); and the digital-silence fraction;
- a spectral cutoff check: the content edge plus the **steepest 1 kHz drop above 8 kHz**.

The numpy BS.1770 implementation (`audiopipe.loudness`) matches ffmpeg to 0.1 LU and 0.1 dB TP. It was checked on two files: −20.2/−20.2 LUFS and −31.37/−31.4.

Analysis of the 13 files took 46 s wall time; load average went from 4.59 to 6.73.

**Quality floor:**
- Reject lossy originals.
- Reject a ≥ 25 dB/kHz brick wall below 20.5 kHz even inside a WAV, because that is a lossy origin that was upsampled.
- Reject effective bandwidth under 18 kHz. **Correction (2026-10-14, [t4](../m1/v4/t4-audio-bandwidth.md)):** this rule never fired. The content-edge smoothing zero-padded the dB spectrum, which lifted the bins under Nyquist, so every file read as full-band. With edge-safe smoothing, a content edge under 18 kHz behind a wall (codec or resampler) is still rejected. A gentle roll-off with no wall is now accepted with a **FLAG** for the listening gate: these are dark sources, not band-limited files.
- Reject clipped runs above 1e‑5 of all samples.
- For footsteps, reject an SNR proxy under 30 dB.

A brick wall at 20.5–22 kHz (an ADC or resampler filter) is accepted and noted.

| id | role | original | LUFS-I | LRA | TP | DC | eff. bits | noise floor dBFS | SNR proxy dB | clipped | steepest drop | gate |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| fs:679335 | amb | 48k/16 121 s | −20.2 | 8.3 | −2.4 | −0.0004 | 15/16 | −30.5 | 11.9 | 0 | 12.8 dB @ 22.7k | accepted |
| fs:679333 | amb | 48k/16 67 s | −34.6 | 3.1 | −14.5 | 0.0006 | 13/16 | −38.7 | 4.5 | 0 | 13.6 dB @ 20.1k | accepted |
| fs:679334 | amb | 48k/16 63 s | −25.9 | 9.1 | −2.2 | 0.0007 | 15/16 | −37.3 | 13.4 | 0 | 18.6 dB @ 20.6k | accepted |
| fs:380726 | amb | 48k/24 488 s | −21.8 | 12.4 | +0.2 | 0.0000 | 24/24 | −34.9 | 13.3 | 3 | 64.6 dB @ 22.1k (ADC) | accepted |
| fs:364865 | amb | 96k/24 165 s | −19.9 | 12.1 | −0.0 | 0.0000 | 23/24 | −32.5 | 13.6 | 0 | 3.4 dB @ 14.9k | accepted |
| fs:677641 | amb | 96k/24 151 s | −27.1 | 6.7 | −9.1 | 0.0000 | 22/24 | −34.5 | 8.1 | 0 | **49.0 dB @ 19.7k** | **rejected**: AAC/MP3 origin inside a 96 kHz WAV (iPhone) |
| fs:205748 | steps | 48k/24 38 s | −33.6 | 7.5 | −8.0 | 0.0000 | 22/24 | −85.2 | 56.2 | 0 | 3.0 dB @ 9.1k | accepted; 11.4 % digital silence (gated) |
| fs:560478 | steps | 48k/24 90 s | −42.0 | 9.4 | −9.5 | 0.0000 | 22/24 | −71.1 | 31.4 | 0 | 5.3 dB @ 22.9k | accepted |
| fs:742969 | steps | 44.1k/32 56 s | −31.5 | 3.7 | +0.1 | −0.0002 | 31/32 | −67.7 | 40.0 | 0 | 1.5 dB @ 20.6k | accepted; 4.2 % digital silence |
| fs:569313 | rain | 96k/16 117 s | −31.0 | 3.9 | −13.2 | 0.0000 | 13/16 | −37.0 | 6.3 | 0 | 9.4 dB @ 22.2k | accepted |
| ia:aporee_70134 | amb | 48k/24 465 s | −22.6 | 16.3 | −5.6 | 0.0000 | 23/24 | −40.4 | 16.2 | 0 | 6.6 dB @ 22.5k | accepted |
| ia:aporee_17483 | amb | MP3 164 s | −21.3 | 7.2 | −3.0 | −0.0001 | – | −28.3 | 9.0 | 0 | 27.4 dB @ 19.1k | **rejected**: lossy original |
| ia:aporee_20539 | amb | MP3 233 s | −22.6 | 8.4 | −1.2 | 0.0000 | – | −29.2 | 7.6 | 0 | 30.2 dB @ 19.1k | **rejected**: lossy original |

I inspected the spectrograms (`data/build/audio/analysis/*.png`) directly. What they show:
- **677641:** a hard wall at about 19.4 kHz, plus a second shelf near 5.5 kHz. That is typical of AAC. It was rejected, which confirms the detector.
- **679335 and 380726:** short ultrasonic tones at 19–21 kHz. These are likely pest repellers or electronics.
- **679333:** a **steady 20 kHz line** for the whole file, plus faint steady lines near 10 kHz and 11.8 kHz.
- **205748 (Yuval):** contact-mic character. There is a strong sub/low-mid thump and gated digital silence between steps, and the last 10 s are long scrape events rather than steps.
- **742969 (Artninja):** a clean heel-then-toe pair per step, about 100–200 ms apart.
- **560478:** quiet and busy (runs, shuffles), so it was not used.

## 3. Cleaning (`audiopipe.clean`, per-source recipes, 48 kHz / 24-bit FLAC)

**Ambience:**
- Trim 1 s from each end.
- `highpass=35 Hz`.
- `adeclick` (threshold 4).
- A linear-phase `firequalizer` low-pass: flat to 16 kHz, −24 dB at 17.5 kHz, −60 dB at 19 kHz. This removes the ultrasonic tones. On a re-rendered spectrogram of 679333 the 20 kHz line is gone.
- No denoise, because for ambience the noise *is* the content.

**Footsteps:**
- `highpass=50 Hz`.
- `afftdn` with noise tracking, at nr 10–12 dB and a per-source noise floor.
- No de-click, because it would eat the heel transient.
- Yuval only: an EQ that cuts 60–250 Hz contact-mic boom and adds +3 dB around 4 kHz.

**Resampling:** soxr, precision 28.

Cleaning all 10 accepted files took 64 s wall time; load average went from 8.39 to 15.30, mostly from other spikes. The exact filter chain is stored per file in `clean/<id>.json` and copied into provenance.

## 4a. Ambience loop: `shinjuku-night-street-loop` (82.0 s)

The loop has three layers. Each is loudness-matched to the bed, then offset, then summed with ffmpeg `amix` (normalize=0):

| Layer | Source | Level | Processing |
|---|---|---|---|
| Bed | takecha 679335 (Shinjuku 22:07) | 0 dB | none |
| Distance | sergeeo 380726, from 0 s | −10 dB | low-passed 6 kHz |
| Far traffic | RutgerMuller 364865, from 35 s | −14 dB | band 60 Hz–2.5 kHz |

For the second and third layers, the pipeline picked the most stationary window by short-term-loudness spread. The far-traffic layer stays eventful: spread 13 LU, with 13 passes more than 6 LU above its median.

**Construction:**

    loop = acrossfade(P = s[X : X+L], Q = s[0 : X], ns = X, c1 = c2 = qsin)

The file ends on s[X−1] and starts on s[X], so the wrap is the recording's own sample continuity. The blend sits inside the file, in its last 6 s.

**Choosing the loop point:**
- A grid search over source offset and length, every 0.25 s: 8,778 candidates with L in 80–115 s.
- Score = 1/3-octave RMS distance between the two fade regions + 2 × their loudness difference + 2 × transient excess + 1 × distance from the median level + a small preference for longer loops.
- All three cut points are then snapped to rising zero crossings of the mid signal where the side signal is quiet (±5 ms).

**Result:**
- Offset 14.25 s, L = 82.001 s, X = 6.002 s.
- Fade-region spectral distance 4.6 dB RMS, loudness difference 2.5 LU.

The X = 4 s version had a 1.2 LU dip through the fade; with X = 6 s it is 0.2 LU.

**Seam verification** compares the doubled file with its own statistics:

| Metric | Master (FLAC) | Opus decode |
|---|---|---|
| wrap sample = source continuity s[X−1]→s[X] | exact (error 0.0) | – |
| wrap step, percentile of all sample steps | 86th (−41 dBFS step; it sits on a zero crossing, so the slope is high) | – |
| **wrap 2nd difference (click detector), percentile** | **80th** | **75th** |
| spectral flux at the wrap, percentile | 38th | – |
| short-term loudness in the fade vs elsewhere | −20.44 vs −20.23 LUFS (pre-master) | – |
| decoded length = master length | – | **exact (3,936,045 samples)** |

The wrap is statistically an ordinary moment of the recording: no click, and no spectral or level step. `analysis/loop-seam.png` shows the last 8 s followed by the first 8 s, with no line at the centre.

**Master:** −26.0 LUFS-I, LRA 5.4 LU, TP −8.5 dBTP, gain only (no limiter). Opus at 96 kb/s: 875 KiB.

## 4b. Footstep pool: `dress-concrete` (8 dry + 8 wet)

**Source.** Artninja 742969 (CC-BY 4.0) is airborne, clean, has a heel-then-toe structure and an SNR proxy of 40 dB. The detector found 73 step candidates. Selection keeps steps that are:
- isolated (gap ≥ 400 ms) and not truncated;
- at SNR ≥ 40 dB;
- within ±3 dB of the median peak;
- 150–450 ms long.

From those it picks the 8 most typical, at least 2 s apart. Each take is extracted as mono (L+R)/2, with a 5 ms pre-roll and 2/40 ms fades.

**Variation (seed 7).** The pitch offsets are {−50, −35, −20, −5, +5, +20, +35, +50} cents and the gain offsets {−1.5, −1, −0.5, 0, 0, +0.5, +1, +1.5} dB. Each set is a fixed permutation, applied after loudness-matching every take.

Pitch uses `asetrate` + soxr, which changes pitch and length together like Web Audio playbackRate. I measured `rubberband` (crisp, percussive, short window) on the same takes. Median 10–90 % attack time:

| Shift | Original | asetrate | rubberband |
|---|---|---|---|
| −50 cents | 0.62 ms | 0.65 ms | 0.75 ms |
| +50 cents | 0.62 ms | 0.60 ms | 0.65 ms |

So asetrate keeps the heel transient intact, and was used.

**Wet variants** = dry take + a synthesised splash + shelf EQ:
- The splash is built in numpy (seeded) at the detected heel and toe impacts. It has three parts:
  - a band-passed slap: 350 Hz–2.6 kHz, 25 ms decay;
  - a high-band spray: 2.5–12 kHz, 50 ms decay;
  - 5–11 Minnaert bubble droplets: 1.1–4.2 kHz, rising glide, 4–15 ms decay, exponential timing.
- Splash peak is −10 dB relative to the step peak.
- Shelf EQ via `firequalizer`: −2 dB below 150 Hz, +3 dB above 6–8 kHz.
- Each wet take is set to the dry take + 1 LU (momentary max).

The spectral centroid moves up by 440–890 Hz. `analysis/pool-dry.png` and `pool-wet.png` show the heel/toe pairs kept, and the droplet chirps visible at 1–4 kHz.

**Levels.** A heel click has a peak-to-loudness ratio of about 30 dB. My first target (−18 LUFS‑M per take) put peaks at +12.8 dBFS, which clipped a 24-bit intermediate; that is the first failure listed below. One-shots are therefore loudness-matched within the pool, and then one pool gain puts the hottest take at −1.5 dBTP.

| Set | Takes | Momentary max (mean / range) | Max TP | Length | Opus total |
|---|---|---|---|---|---|
| dry (mono) | 8 | −32.6 / −34.1…−31.0 LUFS | −1.50 dBTP | 0.33–0.39 s | 22.5 KiB @ 64k |
| wet (mono) | 8 | −31.6 / −33.1…−30.0 | −2.58 | 0.45–0.51 s | 29.6 KiB @ 64k |
| alley-dry (stereo) | 8 | −27.3 / −28.7…−25.3 | −7.59 | 1.21–1.27 s | 92 KiB @ 96k |
| alley-wet (stereo) | 8 | −26.8 / −28.3…−24.8 | −8.18 | 1.23–1.44 s | 91 KiB @ 96k |

**Alternative pool for A/B.** `dress-concrete-contactmic` uses Yuval 205748 (CC0, as NOTES names it). It has 8 dry and 8 wet takes built the same way, with a "contact" profile: steps ring for 450–720 ms. Mean momentary max is −28.9 LUFS for dry and −27.9 for wet.

## 5. Spatialisation: the real spike-6 IR was used

**IR used.** `data/build/audio/ir/alley-01.wav`: a full IR, stereo, 48 kHz, 1.05 s, with the direct sound at t = 0.
- Measured DRR −7.7 dB; L/R correlation 0.99, so it is close to mono.
- It arrived at 00:57 while I was building. I polled again at 01:12; the sha was unchanged.
- **Every alley output (16 masters + 16 Opus) used the real IR.**

**Placeholder.** A synthetic placeholder exists and was exercised once for the fallback path. It is now kept only at `data/build/audio/spatialise/PLACEHOLDER-synthetic-alley.wav` (+ `.json` labelling it), out of spike 6's folder. It models 2 m flutter images and a 3-band tail. Provenance marks any placeholder-built output as `synthetic_placeholder`, and `audit.py --release` fails on it.

**Method:**
- The IR is scaled so the direct path has unity gain.
- Each mono take is upmixed to stereo and padded by the IR length.
- Then `afir=gtype=none:irnorm=-1:irfmt=input`.
- Trailing audio below −90 dBFS is trimmed, with a 20 ms fade.
- One pool gain sets the alley mean to the source + 2 LU, capped at −1.5 dBTP. That is −8.2 dB here.

A reflections-only IR (`alley-01-wet.wav` or the placeholder) is handled too, as dry + IR scaled to DRR +4 dB.

**Rerun with a new IR, one command:** `pipeline/audio/run.sh spatial`. It runs spatialise → master → page → audit in 11–12 s and records the IR's sha256 in provenance and on the page.

## 6. Master and encode

| Category | File-level target | Why |
|---|---|---|
| ambience | **−26 LUFS-I**, TP ≤ −1.5 dBTP, gain only | A bed sits under foley and diegetic music. This leaves about 18 dB of headroom, and stays inside ASWG-R001's −24 ± 2 home/console region. No limiter, because limiter state at the loop end would differ from the start and could tick at the wrap. |
| foley one-shots | loudness-matched within the pool, pool hottest take at **−1.5 dBTP** | Transients bind on peak, not LUFS (PLR ≈ 30 dB). Matching keeps round-robin consistent; the baked ±1.5 dB is deliberate. |
| signals | −20 LUFS-I, ≤ −1.5 dBTP (defined, not produced) | Crossing chirps must cut through traffic. |
| music (diegetic) | −23 LUFS-I, ≤ −1.5 dBTP before diegetic attenuation (defined, not produced) | EBU R128 programme level; the speaker distance model attenuates at runtime. |
| runtime starting bus gains | ambience −6 dB, foley +6 dB | Used in the page's "walk over the ambience" demo. For the user to tune by ear. |

The −1.5 dBTP ceiling leaves room for Opus overshoot. Measured: the decoded true peak never exceeded the master by more than 0.22 dB; the hottest decode is −1.57 dBTP.

**Encodes:**
- Opus via libopus with VBR, `compression_level 10`, 20 ms frames, `application=audio` and `+bitexact`.
- Ambience 96 kb/s stereo; dry/wet steps 64 kb/s mono; alley steps 96 kb/s stereo.
- All 49 Opus files decode to **exactly** the master's sample count, thanks to Ogg end trimming.

**Reproducibility.** With `+bitexact` (a fixed Ogg serial), two rebuilds give identical sha256 for every derived record (the 49 FLAC masters, the 49 Opus files and the IR). Without it, every Opus file differed between runs; that is the last failure listed below.

**Timings:**
- A full offline rebuild (`run.sh build`: analyse → page + audit) took 122 s wall time; load average went from 10.90 to 8.25 while other spikes were running.
- `run.sh spatial` takes 11 s.

**Output layout** under `data/build/audio/`:
- `masters/` (FLAC, 49 MiB including a 31 MiB pre-master .npy);
- `web/` (Opus, 1.3 MiB);
- `analysis/` (PNGs, JSON);
- `index.html`.

## 7. Listening gate

- **Playlist:** `bench/m0/listening-playlist.md`. It lists every output with what to listen for and the measured stats, plus checkboxes.
- **Page:** `data/build/audio/index.html`. It has:
  - a sample-accurate Web Audio loop player, with a "jump to 8 s before the wrap" button and a decoded-length check (it warns if Chrome's Opus decode is not exact);
  - a round-robin "walk" (cadence slider, no immediate repeats, ±15 ms jitter) across dry, wet, alley-dry, alley-wet and the alt pool, optionally over the ambience with the suggested bus gains;
  - an Opus/FLAC codec toggle for A/B;
  - per-take buttons with stats;
  - the source and gate table with links to the spectrograms.

I smoke-tested the page over HTTP (index, Opus `audio/ogg`, FLAC and PNGs all served; the JS passes `node --check`). **No server is left running.**

### How to listen (from the Mac)

Option A, SSH tunnel, one command on the Mac. Ctrl‑C stops both the tunnel and the server:

    ssh -t -L 8790:127.0.0.1:8790 <host> \
      'python3 -I -m http.server 8790 --bind 127.0.0.1 --directory /home/akram/code/or3/data/build/audio'

Then open **http://localhost:8790/** in Chrome, with headphones.

The same thing in two steps:
1. On the server, run `python3 -I -m http.server 8790 --bind 127.0.0.1 --directory /home/akram/code/or3/data/build/audio`.
2. On the Mac, run `ssh -N -L 8790:127.0.0.1:8790 <host>`.

Option B, rsync a copy (about 40 MiB) and serve it locally:

    rsync -av --exclude '*.npy' --exclude 'clean/' --exclude 'ir/' --exclude 'spatialise/' \
      <host>:/home/akram/code/or3/data/build/audio/ ~/audio-gate/
    cd ~/audio-gate && python3 -m http.server 8790 --bind 127.0.0.1   # then http://localhost:8790/

The page must be served over HTTP. With `file://`, Chrome blocks the `fetch()` that the Web Audio players use.

## Commands to reproduce

    cd pipeline/audio && uv sync                          # Python 3.14 env, numpy/scipy/soundfile
    pipeline/audio/run.sh all                             # fetch (network, OAuth) + everything below
    pipeline/audio/run.sh build                           # offline: analyse, clean, loop, pools, spatialise, master, page, audit
    pipeline/audio/run.sh spatial                         # rerun from the IR onwards (new alley-01.wav)
    python3 -I provenance/audit.py --data-root /home/akram/code/or3/data --check-files   # add --release to fail on placeholders
    uv run --project pipeline/audio python -I -m audiopipe.search '' --geo 35.6938,139.7034,4 --filter 'duration:[60 TO 1200]' --sort downloads_desc
    uv run --project pipeline/audio python -I -m audiopipe.footsteps --compare-pitch   # asetrate vs rubberband attack

## Provenance format (draft for NOTES §14.3 / §17 Q3)

- **`provenance/<domain>.jsonl`:** one JSON object per line, sorted sources first, then derived records. This spike adds `audio.jsonl`, with 14 sources and 99 derived records.
- **`provenance/record.schema.json`:** a JSON Schema 2020-12 record definition.
  - **Source records** carry: the source URL and download URL (credential-free), author, an SPDX licence id plus `licence_url`, the CREDITS `attribution` line, the retrieval date, `original_format` (container, codec, rate, bit depth, channels, duration), `path` + `sha256` + `bytes`, and the quality-gate `status` and `status_reason`.
  - **Derived records** carry: `inputs` (ids), ordered human-readable `transformations` (the exact filter chains), `tool` (versions, seeds), `path` + `sha256`, and `synthetic_placeholder`.
- **`provenance/licences.json`:** the policy, in three tiers:
  - `allow`: CC0, CC-BY-3.0/4.0, MIT, Apache, BSD, OFL, own synthesis.
  - `note`: CC-BY-SA, ODbL, the Public Domain Mark. A non-empty `licence_note` is required.
  - `deny_patterns`: -nc, -nd, sampling+, sonniss, pixabay, remarc.
- **`provenance/audit.py`:** standard library only, so CI can run it with any `python3 -I`. It fails on:
  - schema violations and duplicate ids;
  - an unknown or denied licence, a licence URL that doesn't match the licence, and a missing note or attribution;
  - a derived record whose input is missing or **rejected**;
  - share-alike not propagated (an SA input forces the same SA licence, and two different SA licences cannot mix);
  - a derived asset that isn't CC-BY-4.0 when it has no SA input;
  - a sha256 mismatch (with `--check-files`) and synthetic placeholders (with `--release`).

  I tested it negatively: an NC record, an SA record with no note, and a derived record with a rejected SA input plus a missing attribution all fail, with exit code 1.

## Failures and fixes along the way

- **Clipped intermediate.** The first foley loudness target (−18 LUFS‑M) drove the peaks to +12.8 dBFS and clipped the 24-bit FLAC write. Replaced with loudness matching plus a pool TP ceiling, as described in 4b.
- **Clipped alley write.** The alley convolution hit 0 dBFS before normalisation, also in a 24-bit write. It is now kept as float until the pool gain is applied.
- **Useless spectral metric.** The first cutoff metric (−70 dB below 1–4 kHz) put every file at Nyquist, MP3s included. It was replaced by a brick-wall slope detector with a 20.5 kHz lossy threshold. The content edge kept reading Nyquist for a second reason, found in the 2026-10-14 review: `np.convolve(mode="same")` zero-pads the dB spectrum. Fixed in [t4](../m1/v4/t4-audio-bandwidth.md).
- **Contact-mic selection.** Yuval's contact-mic steps are 450–700 ms long, so the default selector found only 1 usable step. A "contact" profile was added.
- **Non-reproducible encodes.** Opus outputs differed between rebuilds because of the random Ogg serial. Fixed with `+bitexact`.
- **Crash on a non-audio record.** `analyse` crashed on the PLATEAU source record, which has no local path. Fixed by filtering.
- **Ambiguous zero-crossing test.** A plain "wrap step" percentile on a zero crossing reads as high (86th), because a crossing is where the slope is steepest. The second difference is the right click metric, and both are reported.

## Risks and recommendation

**Recommendation: adopt the pipeline as the audio production path, conditional on the listening gate.** Measurement shows the loop is seamless and the pools are consistent, but authenticity is the user's call.

**Risks:**
- **Synthesised wet steps may read as "hiss + bubbles".** The parameters were chosen blind (splash −10 dB, spray 50 ms, 5–11 droplets). They are the most likely to need tuning by ear. A field recording of dress shoes on a wet street would beat this.
- **The alley IR may be too wet for the player's own steps.** It was baked for a source 4 m away (DRR −7.7 dB) and is almost mono (L/R correlation 0.99, from first-order Ambisonics decoded to stereo). For runtime, prefer the binaural or wet-only variant plus HRTF, and drive DRR from distance.
- **The far-traffic layer is eventful** (13 passes more than 6 LU above its median). After a few loops one car pass may become recognisable. Mitigation (NOTES §12): ship the layers as separate incommensurate loops (e.g. 82 s, 67 s, 53 s) mixed at runtime, not one baked loop. This spike's single loop is the required deliverable.
- **The 17 kHz low-pass on ambience** costs a little air. It is needed to remove the ultrasonic tones found in 3 of 6 Shinjuku files.
- **Decoding in Chrome.** Opus is exact in ffmpeg, but Chrome's `decodeAudioData` has to honour Ogg end trimming for the loop to stay seamless. The page checks this and shows the result. **Unverified until the user opens the page.**
- **Licence edge cases.** The Public Domain Mark is a label, not a waiver, and BY-SA items need separate handling. Neither is an input to any output; all outputs derive only from CC0 + CC-BY-3.0/4.0 + PLATEAU (CC-BY-4.0 compatible) + own synthesis.
- **Credentials on curl's command line.** `pipeline/freesound-auth.sh` passes the client secret and the refresh token as `curl --data-urlencode` arguments, so they are briefly visible in `/proc/<pid>/cmdline` to other local users during a refresh. This is low risk on a single-user machine, but it contradicts the "never on argv" rule. Fix: feed the form body on stdin (`--data-binary @-`) or through a curl config on stdin. I did not change it: it is outside this spike, and it rewrites `.env`.

## User actions

1. **Listen** (gate): use Option A above, then tick boxes and leave notes in `bench/m0/listening-playlist.md`, or tell Claude. Specifically:
   - Is the loop seamless and authentic?
   - Do the wet steps sound right?
   - Is the alley too wet?
   - Main pool (Artninja, airborne) or alt pool (Yuval, contact mic)?
   - Are the bus gains right?
2. **Decide the Public Domain Mark policy.** Allow it with a note, as drafted, or treat it as denied?
3. **Optional:** approve the `freesound-auth.sh` hardening described under Risks.
4. No `sudo pacman` installs are needed. Everything used was already present.

## Proposed NOTES.md updates

- **§12 "Known gap":**
  - Replace it with: "Open Shinjuku recordings exist but are thin. Freesound takecha pack 37936 (CC0, 2023, geotagged Shinjuku east side), sergeeo 380726 (CC-BY 3.0, Shinjuku 2016), and radio aporee aporee_70134_81690 (PDM, 2025, Shinjuku JR platform, WAV). Nothing open is specific to Kabukicho, Golden Gai or Omoide Yokocho."
  - Add: "Several Tokyo street recordings carry steady 19–21 kHz ultrasonic tones; ambience is low-passed at 17 kHz."
- **§12 Sources:** change "radio aporee / Internet Archive (often lossless)" to "mostly MP3 originals for Tokyo; licences mostly BY-SA, NC-ND or PDM; lossless ones are rare". Add the Public Domain Mark to the case-by-case list.
- **§12 step 2:** record the quality floor: no lossy originals; no ≥ 25 dB/kHz wall below 20.5 kHz (catches upsampled AAC/MP3 inside WAV, e.g. iPhone recordings uploaded at 96 kHz); effective bandwidth ≥ 18 kHz; clipped runs ≤ 1e‑5; footstep SNR ≥ 30 dB.
- **§12 step 4:**
  - Round-robin pitch uses `asetrate`; rubberband measurably softens heel transients.
  - Loops are built as `acrossfade(s[X:X+L], s[0:X])`, so the wrap is source continuity; X = 6 s for street beds.
- **§12 step 6:** record the targets: ambience −26 LUFS-I (gain only, no limiter on loops); foley pool-matched with the hottest take at −1.5 dBTP (PLR ≈ 30 dB, so peak binds); signals −20; music −23; all ≤ −1.5 dBTP; Opus 96k stereo / 64k mono with `+bitexact`.
- **§14.3 / §17 Q3:** adopt the draft format above: `provenance/<domain>.jsonl` + `record.schema.json` + `licences.json` + stdlib `audit.py` (with `--check-files` and `--release`). Spike 5 should own the canonical PLATEAU source record; this spike added `plateau:13104-shinjuku-ku-2025` to `audio.jsonl` so the IR's chain audits. Dedupe on merge (the audit fails on duplicate ids across manifests).
- **§18 item 7:** mark it done, with links to this report and the playlist.
