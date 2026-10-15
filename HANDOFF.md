# Handoff: m1 v4 "engine first, structure first" in progress

_Updated 2026-10-14 by the m1 v4 orchestrator session (user AFK, autonomous run). The m1 v3, m1 v2 and m0 sections below still apply where not superseded._

## m1 v4: where things stand

The user approved the plan from `fable_review.md` §3–5 (2026-10-14): stop polishing in Cycles, build the engine character viewer and make its frame the look gate, then rebuild form (head, hair, suit). Round 4 of the fan build is parked. Reports for every track are in `bench/m1/v4/`; the Fable checkpoint with specs is `bench/m1/v4/checkpoint-1.md`.

**Merged to `main`:**

| Track | What | Report |
|---|---|---|
| T1 | Likeness containment is structural: `pipeline/likeness/containment.py` `assert_private()` at every writer, fan builds refuse non-private outputs, `--compare` and run routing fail closed, gitignore patterns | `t1-containment.md` |
| hook | `tools/hooks/` pre-commit (installed: `core.hooksPath tools/hooks`) refuses likeness paths and any tracked binary repo-wide; `provenance/audit.py --check-files` repeats the binary check | `test_containment.sh` (69 cases) |
| T2 | Facial-hair atlases sRGB-encoded (were ~10× too dark), trousers own ORM, deterministic shoe vertex order | `t2-asset-fixes.md` |
| T3 | Light twins for every saturated hero light (sign-shot suit no longer purple), PROP_SAT fix | `t3-light-twins.md` |
| T4 | 18 kHz bandwidth gate works; 5 sources flagged (incl. the approved Artninja footsteps at 15.4 kHz) for the listening gate; wet steps aligned | `t4-audio-bandwidth.md` |
| T5 | Engine character viewer (`web/character.html`, `web/src/character/`): GLB, rig.json correctives (match Blender to 1e-5), TSL materials, Blender-exported stages, headless capture into look-dev (`ENGINE_SHOTS=1`) | `t5-viewer.md` |
| T6 | Engine look parity: shader-ball gate 6/6, weave as a tiled detail map (moiré gone), SSS LUT, post pass, KTX2 (`--ktx2`, 69 → 32 MB), device capture (`?capture=1&upload=1`) | `t6-engine-parity.md` |
| T7 | Original public face from ICT-FaceKit (MIT, `CREDITS.md`) + shared head sculpt layer (`head_layer.py`, `head_sculpt.py`), new head measures all in range, ArcFace 0.045 vs the private reference | `t7-head.md` |
| T8 | Hair v4 groom: 70k strands, direction field, 4-level clumps, layered uneven cut, melanin 0.90, front falls as dark locks; beard tone matched to the hero strands | `t8-hair.md` |
| T7b | Calm lids (aperture 9.0 mm, robust measure), skull vault, teal back-face fix (viewer + geometry) | `t7b-head.md` |
| T9 | Layered scalp cards from the v4 groom, strand maps in the GLB, beard/moustache/brows as cards (shells retired), hair 0.98× and beard 1.15× Cycles | `t9-cards.md` |
| T9b | Silver hair plates fixed, hair rim pickup and warm scatter fitted per light, brows 1.03× Cycles | `t9b-hair.md` |
| suit spike | Pattern-drafted, sewn jacket (`suit_pattern.py`, additive): sleeve pitch and skirt pass, collar/seams/back fail; conditional go, ~13 days for the full rebuild | `suit-spike.md` |

Latest integrated build of main: `data/build/lookdev/20261014T155504Z-t9b-b1/` (engine frames `game_*.png`), its Cycles hero `data/build/hero/20261014T161745Z-t9b-b1/`; 0 glTF errors, all head measures in range, hair+beard+brows 36k tris.

**Checkpoint 2 (Fable, `bench/m1/v4/checkpoint-2.md`)**: head form and the engine frame are real steps; the look is not yet "believable AAA hero". Weakest links: the suit at full-body distance, waxy skin at portrait distance, a hero hair colour that drifted warm-brown, a beard that reads 55+ in the engine. The engine frame is trustworthy for geometry/rig/tone, not yet for look (no hair self-shadow, unshadowed fill, no AO, no Air capture). The public face reads original; the **costume ensemble** (long dark hair, full beard, black suit, neon alley) still reads as the film character, which is a design decision for the user, alongside C2.

**Merged since:** T11 facial hair (249aa40; beard grey fraction 1.46x -> 1.05x and chroma 1.31x -> 0.96x of the Cycles hero, brows a dark-brown band; report `bench/m1/v4/t11-facial-hair.md`; left for later: hero-rig beard warmth, moustache spikes, the lash wedge at the right inner eyelid, the beard back edge). T12 skin/hair colour/eye band (be74470; eye band 0.7547 -> 0.8163, hero hair r/g +7.5 % of main9, skin 0.5-3 mm relief, identity v2 at default paths; report `bench/m1/v4/t12-skin-hair-colour.md`; left: engine card hair still light brown (T15), thin eye-band margin, cheeks smooth at portrait distance, warm lid tint).

T10 engine gate (hair self-shadow via hair twins, shadowed fill, half-res GTAO, `closeup:hero` view, 2 s turntable, spatial hair metrics, regression strip; per-light hair 1.015/1.149/1.082, crown/back 0.93x of Cycles; report `t10-engine-gate.md`; left: crown warm vs Cycles' cool sheen, beard misses the cyan rim (no beard twins), brows 0.80 after GTAO, AgX chart check; known side effect: `hero.sh` writes its engine sheet into the .blend's source run via symlinks). T22 hands/neck (hand forms, SCM/larynx, wrist + fist correctives, `inverse` cone rules in deform runtime/viewer; dorsum relief 0.45 -> 0.61 mm, LOD0 141.7k; ArcFace 0.033 EEVEE / 0.028 engine hero closeup, run by the orchestrator; `hand_width_ratio` 0.55 target dropped as non-anatomical (ANSUR II mean ~0.46); left: veins too regular (X near the cuff), dark smear on the neck above the collar in EEVEE beauty, nail slivers in the fist pose, jagged body cut inside the left cuff on wrist flex; fresh worktrees need `npm run build:core`). T13 phase A, suit spike 2 (f5fd61c; deterministic numpy XPBD drape `suit_xpbd.py`, shaped collar/rever `suit_rever.py`, trued draft; pattern jacket beats lofted front/¾/back, sewing gap p95 1.61 mm, 0 penetrations, strain 2.5 %; 30 hinge creases left in the A-pose armpit/cuff; report `t13a-suit-spike2.md`; orchestrator notes for phase B: ~8–10 cm too long, too little waist suppression, bell cuffs, slight shoulder slope). T15 hair volume/hairline (asymmetric M + widow's peak, thicker fly-aways, card colour on the hero model, IoU tooling `hair_views.sh`; ¾ IoU 0.826 vs 0.9 missed, engine hair 1.2–2× Cycles brightness missed, hero colour/p10/tris held; report `t15-hair-volume.md`; carried into T20). T16 AA/post (TRAA default with hashed hair alpha `aa.hairCoverage` 1, MSAA path behind a flag; turntable noise 6.08 -> 3.47; thin-lens DoF `dof.radiusScale` 0.835; grade as 33³ LUT (matches each renderer to <0.6/255); character-only set bounce; `Output.addPass`/`addMRT` pass hook, contract in `output.ts`; new hair baseline per light 0.991/1.166/0.984, brows 1.07; grey chart fails because the engine eye light lights only the eyes while Cycles' lights everything at 0.3 and fill/wrap run 16–24 % hot (T19); left: TRAA softness/sharpen, TAAU smoke-tested only; report `t16-aa-post.md`). T18 eyes (refracted iris + caustic, rect catchlights, sclera gradient + vein/fibre normals, lid shadow strip/meniscus/caruncle meshes in `eyes_hq.py`, 2-row lashes, darker iris; read40 0.8278, aperture 8.75 mm, ArcFace 0.022 EEVEE / 0.014 engine hero closeup; missed: sclera/iris −32 % and catchlight area −50 % vs Cycles, iris saturation −15 % of −30 %; left: TRAA smears the 1–2 px catchlight ~45 % in motion (temporal.ts), lower lashes read as specks, re-measure after T19's eye-light fix; report `t18-eyes.md`). T13 items 1–4 (eb1bfc8, 436b1d8): made jacket (pockets, welts, buttons, turned edges, double vents, rolled collar, cutaway, pressed lapel edge; length/waist/cuff/shoulder fixed), pattern UVs + own wool atlas, pattern-drafted trousers (creases, fly, pockets, break), waistcoat (from the jacket block, lined back); not yet the default build (item 8 switch); report `t13-suit-rebuild.md`.

**Running at handoff time** (results land in `bench/m1/v4/`): T13b (suit items 5–8: shirt, rigging, wrinkle maps, integration), T20 hair v5, T19 lighting/shadows, T17 skin. T13 suit rebuild (spike 2 gate, then the full rebuild); T14 painterly dropped. **Checkpoint 3 (Fable, `bench/m1/v4/checkpoint-3.md`)** is the realism roadmap: tracks T16–T26 in waves around T10/T13/T15, a two-tier gate (Cycles parity as regression instrument + a blind plate test judged by the user), and two quality tiers (hero closeup ~9–12 ms, gameplay ~4–5 ms on the Air). Wave 0: T22 hands/neck started. Character LOD0 budget raised to 170k (cap 190k) with LOD1 60k mandatory, under the user's standing quality-over-budget preference (checkpoint 3 §5.4).

**Engine viewer from the Mac:** in `web/`, `npm run dev` (127.0.0.1:5173); tunnel `ssh -N -L 5173:127.0.0.1:5173 archlinux`; open `http://127.0.0.1:5173/character.html?asset=lookdev/<run>&view=portrait&rig=hero`. Device capture for the Air: see `t6-engine-parity.md`.

**User decisions open:**
0. **Air session** (standing ask): one 10-minute capture on the Mac (`t6-engine-parity.md`, device capture). Every engine number so far is SwiftShader.
1–2b. **Decided 2026-10-14 (user):** C2 full realism, suit full pattern rebuild, costume ensemble kept (NOTES Decision log).
3. **Listening gate**: accept-with-flag vs reject for the 5 sources under 18 kHz (`t4-audio-bandwidth.md` §3); the 8.6 dB calibration question applies to the alley footstep takes only.
3b. **Plate test** (checkpoint 3 §3.2): OK to collect CC0/public-domain photos of anonymous men as lighting/material plates (gitignored, never face targets, never fitted)? T25 builds the harness either way.
4. **ArcFace** ruling (still pending; T7 used it offline, private, scalar only). Old per-frame embeddings `private/likeness/work/mica/codes*.npz` kept until the ruling.
5. Still pending from before: m1 base approval, Movieclips ruling. Fan build: palpebral +9.8 % and alar −4.0 % are outside the ±3 % gate after T7b; the fix belongs in the private fan block.

**Housekeeping done:** `private/` is `o-rwx`; fan builds and the worktree-attic archive moved from `data/` to `private/likeness/work/moved-from-data-20261014/`.

**Machine:** the other project (or4) was stopped by the user 2026-10-14 evening (it ran headless Chrome on up to ~14 cores); v4 agents ran at `nice 10`, Blender `-t 3/4`, Cycles one at a time via `flock /tmp/or3-cycles.lock`.

---

## m1 v3: where things stand

The private fan build (likeness tribute, NOTES §14 rule 7 and the 2026-10-13 Decision log entry) is fitted, groomed and rendered as a final review set. **The run waits on the user's review.** All generic code is merged to `main` and pushed; every likeness input and output lives in `private/` and is never committed.

- **Likeness pipeline** (`pipeline/likeness/`): `fetch_flame.sh` downloads FLAME 2020 (login saved once with `--login` in the user's terminal; the host needs a browser User-Agent), then `fit.py` fits FLAME to private reference stills, `wrap.py` wraps the fit onto the MPFB head (eye cores keep the lids on the eyeballs), `tune.py` applies hand edits (scale, ellipsoid falloff, symmetrise, relax, rigid) and `review_board.py`, `clay_views.py`, `refboard.py` build comparison boards. Gate: bizygomatic, mouth width, nose length, alar width and lower-face ratios within ±3 %.
- **Fan build:** `private/likeness/fan.json` (face delta, skin and lip colours, lashes, hair). Run `bench/m1/lookdev.sh --fan` then `bench/m1/hero.sh --fan` (`--preview`, `--final`, `--shots`, `--crop`, `--tt-poses`, `--tt-views`); fan runs are routed to `private/likeness/{lookdev,hero,review}/`, never `data/`. A copy of the final config is archived in `private/likeness/work/fan_final_hair3.json`.
- **Final review set:** `private/likeness/review/fan-final/` (9 shots, crops, painterly variants, turntables in beauty, clay and normal; 256 spp, 95 min at 16 threads). Preview set: `private/likeness/review/fan-preview/`.
- **Generic features added this round, all off by default** (public build unchanged):
  - skin: lip seam, soft vermilion border, beard-to-lip fill and shadow colour, expression-line albedo; float32-safe lip distances.
  - scalp hair: ragged tapered ends, flyaway melanin and roughness, cling.
  - beard: philtrum roots, moustache overhang, grown-in cheek line, per-strand roughness, salt-and-pepper zones (chin and mouth corners).
  - hero rig: light-linking twins (hair, props, cloth, skin) so saturated rims don't stain hair, pistol or suit (`shots.CLOTH_TWIN`).
- **Reports:** `bench/m1/v3/BRIEF.md`, `bench/m1/v3/hair.md`, `bench/m1/v2/hero-stage.md`.

**Viewing the review pages from the Mac.** The servers bind to `127.0.0.1` on this machine only (private content). Tunnel from the Mac and leave it open:
```bash
ssh -N -L 8793:127.0.0.1:8793 -L 8792:127.0.0.1:8792 -L 8791:127.0.0.1:8791 -L 8790:127.0.0.1:8790 archlinux
```
8793 fan final, 8792 fan preview, 8791 m1 v2 review, 8790 audio round 2. If the session ended, restart one with `python3 -I -m http.server <port> --bind 127.0.0.1 --directory <dir>`.

**User gates now open:**
1. Review the fan final set (8793) and say what reads wrong; that drives round 4.
2. Still pending: m1 base approval, the Movieclips and ArcFace rulings, audio round 2 listening (8790).
3. City work using the cybercity techniques (NOTES §19, study only, licence unclear): offered, not started.

**Known defects in the fan final** (round 4 candidates):
- Lower lip a pale, too-regular lozenge; the upper lip barely shows.
- Fine hair strands cross the face like cobweb; a lock sits over the near eye; the side lock curtains the face at turntable 270–315°; the ear pokes through the hair.
- Crown is a smooth shell with one broad highlight and a hard bright part; the back reads as one clump.
- Forehead lines read as thin scratches; lids heavy and slightly uneven.
- Magenta rash-like patch near the nose (eye shot); suit reads purple in the sign shot (needs a cloth twin on the sign key); pink under the eye and teal on the beard edge in the profile.
- v2 carry-overs: boxy suit shoulders, back band, wrist crease, doughy fingers.

**Machine:** the user okayed heavier compute (2026-10-13): agents may run renders at `-t 6` in parallel; final renders still run alone at full threads. Another project's session (or4) shares the machine.

**Housekeeping:** agent worktrees cleaned up 2026-10-14; their untracked scratch files are archived in `data/build/worktree-attic/leftovers-20261014.tgz`.

## m1 v2: where things stand

The hero character is built, merged to `main` (4b2e49a and later) and rendered as a final review set. **The run waits on the user's review.**

- **Final renders:** `data/build/hero/20261013T081828Z-main9-final/` (9 shots, 100 % crops, painterly variants, turntable in beauty, clay and normal; 256 spp). Build: `data/build/lookdev/20261013T081002Z-heroE-main9/` (`character.blend`, `character.glb`). The review page packages them (`data/build/review/m1v2/`).
- **Rebuild and re-render:** `KEEP_BLEND=1 bench/m1/lookdev.sh --config bench/m1/variants/direction.json <label>`, then `bench/m1/hero.sh` (`--final`, `--shots`, `--into`; see `blender/hero/` and `bench/m1/v2/hero-stage.md`). Pass 1 took 91.5 min at 12–16 threads.
- **Tracks, all merged** (reports in `bench/m1/v2/`): A head, skin, eyes (`head.md`); B scalp hair (`hair.md`); C beard, brows, lashes (`facial-hair.md`); D suit (`suit.md`); E hero stage (`hero-stage.md`); F deformation, 16 helper bones and 14 correctives (`deform.md`); G hands (`hands.md`); H original pistol (`pistol.md`). Direction: `BRIEF.md`, `direction.md`, `skin-direction.md`.
- **Budgets:** character GLB 126,872 tris, 83 bones, 4 weights per vertex, 0 glTF errors; pistol GLB 10,266 tris, 0 errors.

**User gates now open:**
1. Likeness check on the face (NOTES §14: the face must stay original).
2. Look sign-off for m1, or a list of what to change.
3. Still pending from earlier: the m1 base approval, the Movieclips and ArcFace rulings, and audio round 2 listening (`data/build/audio`, served locally on port 8790 while the session runs).

**Known weak spots** (candidates for a v3 round if the user wants one):
- Skin reads smooth at portrait distance (pores are sub-pixel there; mid-scale relief carries it).
- Suit wool reads soft and slightly rubbery; the far lapel in the portrait folds into a flat panel.
- Magenta rim floods the hair on the shadow side.
- Pistol hold: strong thumb about 4 cm short of the slide stop, pinky gap a third of a finger; one-handed holds (`walk+pistol`, `stand+pistol`) pierce and need their own muzzle-down hold.
- Fist (no shot uses it): fingertip pads crumple and the thumb lies flat.
- Game-GLB beard and brow shells are blotchy in extreme close-up; `Human.suit_shoes_export` vertex order is not build-stable (weights are fine).
- read40 eye band 0.58 against the 0.75 bar (waived for v2; recalibrate under the game light).

**Machine rules for agents** (learned the hard way: load hit 51): one Blender job per track at `-t 3`, at most two cloth sims, EEVEE or draft for iteration, and final renders only with nothing else running.

---

# Handoff (m0): Phase 0 complete

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
