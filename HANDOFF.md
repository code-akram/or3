# Handoff: Phase 0 (m0) complete, waiting on user gates

_Written 2026-10-12 by the autonomous Phase 0 session. This is for the user and for any new Claude Code session picking up from here._

**For a new session, read these first, in order:**
1. This file.
2. [`NOTES.md`](NOTES.md), the single source of truth. §18 has the status table and the Decision log has the 2026-10-12 entry.
3. The per-spike reports in [`bench/m0/`](bench/m0/).

## 1. Where things stand

All seven Phase 0 spikes ran as parallel agents in git worktrees. Everything is merged to `main` and pushed to `github.com/code-akram/or3`. The work that can run on this machine is finished. What's left needs a person: the user's hands, ears, or an M4 Air.

| # | Spike | Status | Headline numbers | Report |
|---|---|---|---|---|
| 1 | MPFB2 headless character | ✅ | ~2 s per build; 50.2k tris, 53 bones, 4 weights per vertex; GLB 0 validator errors | [spike-1](bench/m0/spike-1-mpfb2-headless.md) |
| 2 | Render test | ✅ | EEVEE **headless on the iGPU** 1.1 s at 512² / 7 s at 1024²; Cycles 128 spp + OIDN 13–18 s per view at 16 threads | [spike-2](bench/m0/spike-2-render-test.md), [idle reruns](bench/m0/idle-rerun.md) |
| 3 | GVHMR video → motion (CPU) | 🟡 **footage blocked** | bf16 17.8 h per 60 min footage (4 × 4 threads), fp32 35 h; foot lock v2: slide 23.7 → 2.5 cm/s, 99.4 % travel kept | [spike-3](bench/m0/spike-3-gvhmr.md) |
| 4 | Browser skeleton | 🟡 **Air run pending** | WebGPU + WASM threads + shared-memory poses work headless; WASM 506 KB br; sim tick p50 0.9 ms | [spike-4](bench/m0/spike-4-browser-skeleton.md) |
| 5 | PLATEAU chunk | ✅ | Kabukicho/Golden Gai 200 m chunk: 190 LOD2 buildings, 23k tris, 342 KB meshopt; CRS exact to GSI | [spike-5](bench/m0/spike-5-plateau.md) |
| 6 | Steam Audio alley IR | ✅ | 0.13 s per IR at 16 threads; EDT 0.20 s, T20 0.34 s, DRR −8 dB | [spike-6](bench/m0/spike-6-steam-audio.md) |
| 7 | Audio pipeline | 🟡 **listening pending** | 13 fetched / 3 rejected (lossy disguised as lossless); 82 s seamless loop; 8 dry + 8 wet footstep takes; 16 alley-convolved | [spike-7](bench/m0/spike-7-audio.md), [playlist](bench/m0/listening-playlist.md) |

**Also done in this run:**
- **Provenance unified** on JSONL manifests (`provenance/{audio,mesh,data}.jsonl`, schema, `licences.json`, `audit.py`). 116 records pass the audit in all modes.
- **Credential handling hardened.** Neither fetch script passes credentials on the command line any more.
- NOTES.md now holds every measured finding, the updated risks and the new open questions.
- The idle 16-thread benches were rerun.

**Not done yet: tagging `m0`.** It needs the Air numbers (spike 4) and the user's approval at the m0 gate (repo layout, provenance format).

## 2. User actions, in priority order

1. **Rotate the SMPL / SMPL-X password** on both MPI sites, and anywhere else it was reused. It leaked into the session transcript through `pgrep -a`. The user said they would handle this, together with scrubbing the local transcript.
2. **YouTube cookies**, which unblock spike 3. This takes about 3 minutes. Full steps are in [spike-3 › User actions](bench/m0/spike-3-gvhmr.md#user-actions). In short:
   1. Use a **secondary YouTube account**, because yt-dlp warns that accounts can get banned.
   2. Open a private window, log in, then go to `youtube.com/robots.txt` in the same tab.
   3. Export the cookies with "Get cookies.txt LOCALLY", then close the window.
   4. Copy and lock down the file:
      ```bash
      scp -p ~/Downloads/youtube-cookies.txt akram@<this-machine>:/home/akram/code/or3/private/youtube-cookies.txt
      ssh akram@<this-machine> chmod 600 /home/akram/code/or3/private/youtube-cookies.txt
      ```
   5. Delete the copy on the Mac.
   6. Then run, or ask Claude to run: `pipeline/video-to-motion/fetch-youtube.sh`.
3. **M4 Air session**, which closes spike 4 and the m0 performance numbers. Full checklist: [spike-4 › M4 Air session](bench/m0/spike-4-browser-skeleton.md#m4-air-session-user).
   - **This machine:**
     ```bash
     cd ~/code/or3 && core/build-web.sh && (cd web && npm ci && npm run build) && node bench/server.mjs
     ```
   - **Mac:**
     1. Plug in, turn off Low Power Mode and Chrome Energy Saver.
     2. Open the tunnel:
        ```bash
        ssh -N -L 8787:127.0.0.1:8787 akram@<this-machine>
        ```
     3. In Chrome, open `http://localhost:8787/?label=air-1x` and go full screen.
     4. Keep the tab in front for **at least 30 min**.
     5. Before closing, note the tab's Memory footprint and GPU memory from Chrome Task Manager.
   - **Afterwards:** `node bench/summarize.mjs` reads the results.
4. **Listening gate** for spikes 7 and 6. Use headphones.
   - Run this on the Mac:
     ```bash
     ssh -t -L 8790:127.0.0.1:8790 akram@<this-machine> \
       'python3 -I -m http.server 8790 --bind 127.0.0.1 --directory /home/akram/code/or3/data/build/audio'
     ```
   - Open `http://localhost:8790/`.
   - Tick the boxes in [`bench/m0/listening-playlist.md`](bench/m0/listening-playlist.md).
   - Pick the main footstep pool: Artninja, or the Yuval alternate.
   - Judge the alley IR (`ir/alley-01-binaural.wav`): is the 8.6 dB calibration right, or should it be wetter?
5. **Decisions**, also listed in NOTES §17:
   - **Python 3.11 + the `ryanrudes/gvhmr` fork** for GVHMR. Recommendation: accept, pinned.
   - **IGN-hosted studio featurettes**: do they count as "official"? This includes the behind-the-scenes Sacré-Cœur stair clip.
   - **Public Domain Mark items** (radio aporee): accept with a note, or reject?
   - **Provenance format** (§17 q3): approve the JSONL draft?
   - **Repo layout** (§6 / §17 q5): approve it as built?
   - **m2 frame-time definition** (§17 q8).
   - **SMPL-derived motion licensing** (§17 q6): email MPI, or ship under a non-commercial exception? This must be settled before any Wick-derived motion ships.
6. **Optional:**
   - `sudo pacman -S vulkan-radeon vulkan-swrast` to test Blender's Vulkan backend.
   - `sudo pacman -S unzip`.
   - File the nusamai bug reports upstream.

## 3. Picking up as a new Claude Code session

**Read first.**
- `NOTES.md` and this file.
- Memory is in `~/.claude/projects/-home-akram-code-or3/memory/`:
  - `3d-web-game-exploration`
  - `or3-working-style`
  - `secrets-handling`

  It loads automatically when Claude Code is started from `~/code/or3`.

**Working agreement** (NOTES §5):
- Work autonomously, and stop only at gates.
- Run independent work in parallel worktrees.
- When an agent ends partial, start a follow-up agent to find the root cause and finish it.
- The user runs `sudo`. Give them one exact `! sudo pacman -S …` line.

**Hard rules:**
- **Secrets.**
  - Never print `.env` values or process command lines (no `pgrep -a`, no `ps` args).
  - Never pass secrets as argv. Use `/dev/fd` pipes or stdin.
  - The user types credentials in their own terminal, never in chat.
- **Licensing** (NOTES §14). Footage, frames, SMPL files, weights and film-derived motion stay in `private/` and are never committed. Check `git status` before every commit.
- **Naming.** Never use the codename `or3` in identifiers.

**Environment map:**

| What | Where |
|---|---|
| Freesound OAuth (client + tokens, mode 600) | `.env`; refresh with `pipeline/freesound-auth.sh --refresh` (24 h tokens) |
| SMPL / SMPL-X models | `private/body-models/{smpl,smplx}/` (v1.1.0 chumpy pickles; the fork's shims load them) |
| GVHMR fork, venv, checkpoints, footage, motion | `private/src/`, `private/models/`, `private/footage/`, `private/motion/` |
| Downloads (PLATEAU 773 MB, MPFB packs, Steam Audio SDK, audio) | `data/raw/` |
| Build outputs (character GLB, world chunk, audio, IRs, idle bench logs) | `data/build/` |
| WASM threads toolchain | rustup nightly + `rust-src`; wasm-bindgen 0.2.129 and binaryen in `~/opt/` (see `core/build-web.sh`) |
| Headless Chromium | Playwright cache `~/.cache/ms-playwright` |
| Blender | 5.2.2 LTS with MPFB2 2.0.18 user extension |

**Rebuild everything:**
```bash
blender -b --python blender/build_character.py            # see spike-1 for args; or bench/m0/bench_spike1_build.sh
bench/m0/bench_spike2_render.sh 16 1024                   # turntables
bench/m0/spike5/{fetch,convert,chunk,render}.sh           # PLATEAU → chunk
bench/m0/spike6/bake.sh 16 3                              # alley IR
pipeline/audio/run.sh build                               # audio (offline); `all` refetches
core/build-web.sh && (cd web && npm ci && npm run build) && node bench/headless-check.mjs --seconds 15
python3 -I provenance/audit.py --data-root /home/akram/code/or3/data --check-files --release
```

**Housekeeping:**
- `.claude/worktrees/agent-a6b466bebcbfb1e15` is fully merged but still locked by its agent session. Remove it with `git worktree remove -f -f .claude/worktrees/agent-a6b466bebcbfb1e15 && git branch -d worktree-agent-a6b466bebcbfb1e15` once nothing holds it.
- Headless spike-4 telemetry is archived in `data/build/spike4-headless-telemetry/`.

## 4. What comes next

**When the gates land:**
1. **Cookies arrive:** run `fetch-youtube.sh`. Then run the pipeline (bf16, 4 × 4 schedule) on the §8 targets: the Sacré-Cœur climb and walk shots, an Osaka Continental walk or turn, and the Paris walks. Report the usable yield.
2. **Air telemetry arrives:** summarise it and check it against the m2 criteria in NOTES §15. Record the numbers in spike-4. If the m0 gate is approved, **tag `m0`**.
3. **Listening sign-off:** apply the feedback, for example retuning the wet splash and the IR wetness, then rerun `pipeline/audio/run.sh spatial`.

**m1, character look, which is the next milestone.** None of it is blocked:
- **Look-dev loop:** EEVEE on the iGPU at 512² (~1.1 s per view) with fixed front, ¾, profile and close-up views. Use best-of-N edits with revert and measurable checks (silhouette IoU, landmark ratios, poly budget), per NOTES §7.
- **Head:** a Sifu-style angular, planar, original face, built by parametric lattice edits.
- **Suit:** tailor it from the stock grey pinstripe into a **black three-piece** with a white shirt and black tie. Add the lapel roll, vent and trouser crease. Hide body polygons the suit covers.
- **Hair and beard:** clump meshes generated from Blender hair curves. There is no beard yet.
- **Budgets:** swap the 7.1k-tri teeth.
- **Deformation prep:** helper and twist bones, ready for the Dem Bones bake later.
- **Also unblocked (m2 groundwork):** retarget 100STYLE / CMU locomotion to our rig. These datasets carry no SMPL licence issue. Start the motion-matching database.

## 5. Known issues and caveats

- **The character still looks like stock MPFB.** The light hair, grey pinstripe and patterned tie only prove the pipeline. They are not the look; that's m1.
- **Spike 4:**
  - Headless frame numbers mean nothing for the Air.
  - The console shows one 404, probably the missing favicon.
  - `playwright install` removed older cached browsers.
- **Spike 6:** early reflections are binned noise with no discrete flutter echo, and the IR is very wet and nearly mono.
- **Spike 7:** the wet-splash parameters were tuned blind, and seamless looping in Chrome is unverified until someone listens.
- **Spike 3:**
  - Usable yield on night and action footage will be low, because the detector fails on dark, blurred or inverted bodies.
  - Falls come from mocap instead.
  - The third-party fork is pinned. Its `pyproject` says MIT, but the ZJU non-commercial licence is the binding one.
- **Arch's Blender 5.2.2 can't import meshopt GLBs.** Inspect the uncompressed one.
