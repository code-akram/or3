# T4: audio bandwidth gate (m1 v4, step 0)

**Status: done; the corrected listening page is rebuilt.** The 18 kHz bandwidth floor now measures. It puts five accepted sources below 18 kHz, and one of them is the approved main footstep source (Artninja 742969). None of the five is a band-limited file: they are dark sounds with a natural roll-off. They are **accepted with a flag** and put in front of the user's ears, not rejected. That is a policy call the user should confirm (see "Decision for the user").

Input: `fable_review.md` §1.6. Branch `worktree-agent-a0455af6a8ba987b8`.

## 1. The bug and the fix

`analyse.spectral` smoothed the Welch dB spectrum with `np.convolve(pdb, ones(k)/k, mode="same")`. That zero-pads, and in dB a 0 pad sits about 100 dB above a real noise floor. So the last k/2 bins under Nyquist were lifted and the content edge read as Nyquist for every file, MP3s included. The floor could never fire.

What changed in `pipeline/audio/src/audiopipe/analyse.py`:

- **Edge-safe smoothing.** `smooth_db` reflect-pads, so a flat spectrum stays flat at both ends. Reflect padding and `mode="valid"` agree to within 0.1 kHz on all 26 sources.
- **Content edge on two spectra.**
  - The median Welch spectrum is the typical frame. For a gated or sparse source (footsteps, crow calls) that is the background *between* the events.
  - The power-mean spectrum is dominated by the loud frames.
  - The edge reported is the higher of the two. Example: Artninja reads 4.1 kHz on the median (room tone between steps) and 15.4 kHz on the mean (the steps).
  - A spectrum that never rises 10 dB above its own floor (white) now reads Nyquist, not 0.
- **Wall search starts at 4 kHz** (was 8 kHz). An upsampled 16 kHz-rate file now shows its wall at 8 kHz. No accepted source turned into a wall because of this.
- **Gate.**
  - A content edge under 18 kHz behind a ≥ 25 dB/kHz wall below 20.5 kHz is still **rejected** (lossy codec or upsampled).
  - A content edge under 18 kHz with a gentle roll-off and no such wall is **accepted with a FLAG**. The marker "passes floor with a bandwidth flag" goes into `status_reason` in `provenance/audio.jsonl`, together with both edges and the 15–18 kHz band level relative to 1–4 kHz (typical / loud frames).
- **Unit check:** `pipeline/audio/tests/test_bandwidth.py`, offline, no data needed:

      uv run --project pipeline/audio python -I pipeline/audio/tests/test_bandwidth.py   # 7 passed

  | Case | Required result |
  |---|---|
  | Flat spectrum | stays flat at the edges |
  | Full-band white noise | Nyquist |
  | Noise through a 22 kHz ADC-style wall | ≥ 21.6 kHz, accepted, no flag |
  | Noise low-passed at 15 kHz | 15 kHz ± 0.6, rejected |
  | Noise low-passed at 7.6 kHz (16 kHz rate) | wall found, rejected |
  | Gentle 12 dB/oct roll-off | flagged, not rejected |
  | Bright clicks over a dark background | edge taken from the loud frames |

  With the old zero-padded smoothing swapped back in, the 15 kHz, 7.6 kHz and flat-spectrum cases fail. The 15 kHz case reads 24.0 kHz.

**Validation on real material.** I encoded three accepted full-band sources (454261, 786004, 742969; 60 s each) and decoded them back to 48 kHz WAV. In every lossy case the gate rejects them through the wall detector, at the wall frequency shown:

| Encode | Wall found |
|---|---|
| MP3 128k | 16.2–16.4 kHz |
| MP3 192k | 18.5–18.6 kHz |
| MP3 320k | 19.8–20.3 kHz |
| AAC 128k | 16.8–17.0 kHz |
| resampled through 32 kHz | 17.9–18.2 kHz |
| resampled through 22.05 kHz | 12.0–12.2 kHz |

Only AAC 256k passes, with a wall at 21.1–21.3 kHz or none; the old gate could not catch it either. So the flag route does not open a hole for lossy or upsampled files.

## 2. Which sources fall below 18 kHz

All 26 sources were re-analysed offline from `data/raw/audio`; nothing was refetched. Rejections are unchanged: the six Shinjuku street recordings and the three aporee items (human presence and/or lossy).

Accepted sources below 18 kHz (edges in kHz; band = 15–18 kHz level relative to 1–4 kHz):

| Source | Used for | Edge, typical frame | Edge, loud frames | Band, typical / loud | Verdict |
|---|---|---|---|---|---|
| **freesound:742969** Artninja, leather soles | **main footstep pool** (`dress-concrete`, user-approved dry takes) | 4.1 | **15.4** | −10.6 / −36.0 dB | **FLAG** |
| freesound:786004 newlocknew, winter wind | bed layer `wind` (the reference layer) | 15.4 | **16.8** | −10.1 / −11.0 dB | **FLAG** |
| freesound:730438 HECKFRICKER, vending hum | bed layer `vending` | 16.4 | **16.4** | −28.9 / −28.7 dB | **FLAG** |
| freesound:612817 xkeril, courtyard rain | bed layer `rain-light` | 17.2 | **17.9** | −29.8 / −29.1 dB | **FLAG** |
| freesound:476139 cupido-1, crow | bed events `crow-04..06` | 4.6 | **8.8** | −21.9 / −34.0 dB | **FLAG** |

The "loud" band figures come from the power-mean spectrum. The provenance `status_reason` carries both values.

Just at or above the floor, so not flagged: 81731 rain-drips 18.0, 205748 Yuval 18.2, 568820 cricket 18.2.

**Against the review's prediction:**

- **rain-light 612817: confirmed** below the floor, at 17.2 kHz typical frame and 17.9 loud (review: 17.5).
- **vending 730438: confirmed** at 16.4 kHz.
- **Yuval 205748: corrected.**
  - 13.2 kHz is its *median* edge, which is the gated digital silence and room tone between steps.
  - Its steps reach 18.2 kHz, so it passes.
  - It is also not "the main footstep pool candidate". The user picked the main pool at the 2026-10-12 gate. That pool is **Artninja 742969**, and the Yuval contact-mic pool was dropped (`master.py`, `page.py` docstring).
- **Missed by the review:**
  - **Artninja 742969**, the main pool source that actually ships, at 15.4 kHz.
  - The **wind** bed layer 786004, at 16.8 kHz.
  - The **crow** 476139, at 8.8 kHz.

**Why these are dark sources, not band-limited files.** I looked at every spectrogram:

- **Artninja:** heel transients reach 15–18 kHz, and its room tone runs flat to Nyquist.
- **Yuval:** steps reach Nyquist.
- **Rain and vending:** a smooth decline with noise up to Nyquist.
- **Wind:** still only 17.5 dB below the 1–4 kHz band at 23 kHz.
- **Crow:** flat white noise floor to Nyquist; the calls simply have no energy above about 9 kHz.

None of them has a shelf or a wall. The "10 dB above the floor" edge measures where a sound's spectrum comes within 10 dB of its own top-octave minimum. On a sloped or white-floored source, that is not the recording chain's bandwidth. Spectrograms: `data/build/audio/analysis/freesound-<id>.png`.

## 3. Decision for the user (policy)

Applied literally, the old rule ("effective bandwidth < 18 kHz → reject") would reject all five sources. That would:

- remove the approved main footstep pool;
- remove three of the eight bed layers, including `wind`, which every other layer's level is set against;
- remove three of the six crow takes.

The bed could not be rebuilt without new fetches (network), and the footsteps would have to move to another pool. The brief rules out doing that silently. So:

- **Done:** a wall below 20.5 kHz → reject (as before). A gentle roll-off below 18 kHz → accept with a FLAG, listed on the listening page for the user's ears. The NOTES §12 quality-floor line ("Effective bandwidth ≥ 18 kHz") should be updated if the user agrees. I did not edit NOTES.
- **Alternative,** if the user wants the literal rule: reject the five, and fetch brighter replacements for wind, vending, light rain and one crow, plus a new main footstep source. That needs Freesound and a new footstep listening round.

## 4. Other §1.6 fixes

- **Wet footsteps 10 ms late: fixed.**
  - `footsteps.eq_wet` measures the firequalizer's group delay once with an impulse (480 samples, its 10 ms default delay). It pads the input by that much and trims it off the front.
  - Cross-correlating every dry/wet pair gives an onset lag of +480 samples before the fix and 0 after, for all 8 wet and 8 wet-v1 takes.
  - The laptop-speaker splash metrics change because they were measured on misaligned pairs. Old → new, round 1 / round 2:

    | Metric | Round 1 | Round 2 |
    |---|---|---|
    | splash-to-step band | 1.9 → 4.6 dB | 1.8 → 5.6 dB |
    | band wet−dry | 6.2 → 5.3 dB | 9.4 → 8.6 dB |
    | unmasked fraction | 0.91 → 0.92 | 0.87 → 0.89 |
    | dM | unchanged | unchanged |

- **Stale files: fixed.**
  - `common.clear_outputs` removes a stage's previous output files before it writes new ones. It runs on the bed premaster `layers/` and `events/`, the ambience-v2 masters and Opus files, the footstep `dry/`, `wet/` and `wet-v1/` folders, the alley folders, and the foley Opus files.
  - `master.main` drops all `audio:ambience-v2/` and `audio:foley/dress-concrete/` records before re-recording them. A rerun with fewer takes can therefore no longer crash, or leave dead records in `audio.jsonl`.
  - One side effect: the ambience-v2 records now come before the foley records in the manifest (a one-time reorder in the diff).
- **Listening-gate wording.**
  - The round-2 page (`page.py` → `data/build/audio/index.html` and `bench/m1/listening-round-2.md`) now says the 8.6 dB calibration question covers only the alley footstep takes. The bed normalises the IR itself, so the calibration has no effect there.
  - It also gains a "Dark sources" section that lists the flagged sources with a tick box each.
  - `bench/m0/listening-playlist.md` gets a superseded note with both corrections.
  - **HANDOFF.md** (not edited, per the brief) still says "Pick the main footstep pool: Artninja, or the Yuval alternate" and "is the 8.6 dB calibration right". Both lines are stale. Please reword them at the next handoff.
- **Not done:** the other §1.6 items (token on redirects, gating human checks, the seam metric, model hashes, event takes ending at their peak, S4 items). They were out of scope for this track; none needs network to fix.

## 5. Rebuild

`pipeline/audio/run.sh build` ran offline against the main checkout's `data/`: `common.DATA_ROOT` resolves through `git --git-common-dir`, so a worktree uses `/home/akram/code/or3/data`. It took 789 s at load average 41–54 (other sessions were rendering). After the `band_15_18k_rel_db_loud` addition, I reran `analyse` and `page` once more.

- **Previous outputs** are kept in `data/build/audio-pre-t4-20261014/` (a full copy, 1.1 GB).
- **Bit-identical to before:**
  - the IR record;
  - all 8 bed layers, 21 events and the preview (FLAC and Opus);
  - all 8 dry takes, which the user approved, because the pool gain did not move.
- **Changed (64 records):**
  - wet, wet-v1 and alley-wet takes: the alignment fix;
  - alley-dry takes: the alley pool gain is computed over the dry and wet pairs together, so it shifted.
- **`status_reason` changed** for 11 sources: 5 flagged, the rest get the new "content stops near" note or the new wall verdict text. No status changed: every accepted source is still accepted, every rejected one still rejected.

**Audit:**

    python3 -I provenance/audit.py --data-root /home/akram/code/or3/data --check-files --release
    audit: 177 records (35 source, 142 derived) in 3 manifest(s): 0 error(s), 0 warning(s)

## 6. Before listening

- **The approved main footstep source sits below the 18 kHz floor**: Artninja, with steps reaching about 15.4 kHz. The user approved these dry takes by ear on 2026-10-12, so this is information, not a new defect. If anything, small speakers make it moot.
- The four bed sources are flagged for the same reason: wind, vending, light rain, one crow. **Question for the user:** does any of them sound dull next to the rest? Page section 4, playlist section 5.
- The wet takes moved 10 ms earlier to line up with the dry takes. Their sound is unchanged otherwise.
- **The 8.6 dB IR calibration question is for the alley footstep takes only.**
