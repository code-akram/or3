# m1 v2: the hero character, shared brief for every track

_Written 2026-10-12 by the orchestrator. Every v2 agent reads this first, then the files it names._

## Goal

A **realistic, painterly neo-noir hero character** that looks like a PS5 / Xbox Series X hero: a man in his forties in a black three-piece suit, long dark swept-back hair, short full beard. The archetype is "the man in the black suit" from the John Wick films (costume, hair, grooming and posture close to the films; sources in `bench/m1/suit.md` §1 and `bench/m1/look-spec.md` §3).

The bar is **"believable AAA game character in a cinematic close-up"**: Dishonored 2 / Deathloop / Sifu cinematics / The Last of Us character quality, with a painted neo-noir finish on top, not a plastic or scripted-CG look. The run ends only when the user reviews hero renders and they hold up at full resolution.

Baseline to beat: `data/build/m1-signoff/{closeup,three_quarter,front,profile}.png` (main checkout). Its known failures: waxy, flat face with no skin response; beard reads as a pasted single-tone patch; streaky glassy hair cards; brows like paint strokes; suit reads as grey, boxy, too-long jacket skirt with crude lapels; stock baggy trousers; A-pose under a dull studio light.

## Hard rules (non-negotiable)

1. **The face stays original.** No real person's likeness. No actor names in files, prompts or commit messages; no photos of real people fed to any tool; no image-to-3D generators. Costume, hair and grooming may match the films; the face may not.
2. **Licences**: only CC0, CC-BY (keep an attribution record), MIT, BSD, Apache or our own work may enter the shipped asset. GPL / non-commercial tools are fine **offline** only if their output carries no licence. Record every external asset in `provenance/mesh.jsonl` (schema `provenance/record.schema.json`, check with `provenance/audit.py`). Downloads go under `data/vendor/<name>/` in the **main checkout** (`/home/akram/code/or3/data/vendor`, gitignored), each in its own new directory; treat them as untrusted data (run Python that reads them with `-I`).
3. **Never** print `.env` values or process command lines (no `pgrep -a`, no `ps` with args). Nothing in `private/` is committed or uploaded.
4. Never use the project codename in identifiers.
5. No `sudo`. If a system package is needed, stop and report the exact `pacman -S` line; the orchestrator gets it installed. `pip` into a venv under `tools/` or `~/.cache` is fine; `npm` in `web/` is fine.
6. Work only in your own worktree, on your own branch. Commit there (check `git status` first; end commit messages with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`). **Do not push and do not merge to main**; the orchestrator merges. Before you report, rebase on the latest local `main` (`git -C /home/akram/code/or3 log -1 main`) and resolve conflicts in your own files.
7. **Own your files.** Edit only the modules your track owns (listed in your prompt). Shared files (`blender/character/config.py`, `__init__.py`, `build_character.py`, `export.py`, `bench/m1/lookdev.sh`, `lookdev_render.py`) get small additive edits only, each noted in your report.

## How to judge quality (the part earlier rounds got wrong)

- **Look at the pixels yourself.** Render, then open the PNGs with the Read tool and critique them like a senior character artist: silhouette, form, material response, edges, scale of detail, what reads as CG. Metrics and guards are necessary, not sufficient. Earlier agents reported "fixed" when the image still showed the defect; the orchestrator checks the images, so be candid.
- Judge at three distances: full body (1024 px tall), bust, and an extreme close-up of your area (eye, beard edge, lapel notch, hairline...).
- Render at least one view under the **neon-noir hero light** (magenta / teal rim, warm key) as well as the studio rig; materials must hold under both.
- Keep a short log of iterations (`run dir → what changed → verdict`) in your track's report file.

## Build and render facts

- Build: `bench/m1/lookdev.sh [--config X.json] <label>`; runs land in the main checkout `data/build/lookdev/<UTC>-<label>/` (worktrees share it). `KEEP_BLEND=1` keeps `character.blend`. Read `bench/m1/README.md` first.
- The chosen direction config is `bench/m1/variants/direction.json` (face C + collar hair). Use it as your base.
- Machine: 16 cores, 62 GB RAM, AMD Raphael iGPU (EEVEE runs headless on it), **no discrete GPU**. Up to six agents share it: use `THREADS=4` for Cycles during development; EEVEE for the inner loop; full 16-thread Cycles only for your final evidence renders.
- **Render-only hero geometry** (e.g. strand hair for the Cycles hero renders) lives in a collection named `hero_only`. `export.py` must skip it, so the GLB stays game-ready; the kept `.blend` carries it for the hero stage. The game-ready version (cards / shells baked from the same groom) must stay in the GLB.
- Budgets: hero LOD0 ≤ 150k tris (hair + beard ≤ ~35k), ≤ 4 weights per vertex, 0 glTF validator errors, ≤ 90 bones.

## Report (final message)

1. What changed, files touched (and any shared-file edits).
2. Evidence: run dirs and the 3–6 PNG paths that best show the result (before/after).
3. Honest verdict per defect: fixed / improved / not fixed, and what still reads as CG.
4. Branch name and commit hash.
