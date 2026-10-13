# m1 v3: the fan likeness, shared brief for every track

_Written 2026-10-13 by the orchestrator. Read `bench/m1/v2/BRIEF.md` first: everything there still applies except its rule 1, which this file replaces._

## Goal

Turn the v2 hero character into **John Wick as a fan tribute**: the face recognisably Keanu Reeves in the John Wick: Chapter 4 era, and hair and grooming matching the films. The v2 pipeline (MPFB base, topology, UVs, rig, correctives, grooms, hero stage) stays; we change shape, texture and grooming. The bar: the user looks at the hero renders and recognises him instantly.

## Rule 1, replaced (user ruling 2026-10-13, NOTES Decision log)

- The fan likeness is allowed, **in the private fan build only**.
- **Everything likeness-specific stays in `private/`** (gitignored): reference frames and stills, crops, landmarks, fitted face meshes, likeness parameters and configs, comparison boards. Nothing likeness-specific is committed, pushed or published.
- **Code is public and generic.** Fitting and wrapping code goes in the repo, written so it works for any reference set; it reads its inputs from `private/` paths given on the command line or by env var. The public build (no private input) must still produce the original v2 face.
- The private build input is `private/likeness/fan.json` (a config overlay read by `blender/build_character.py` when `FAN_CONFIG` is set or `--fan` is passed; the face track defines its shape).
- Actor and film names may appear in private files and in the credits line in NOTES; keep them out of code identifiers and commit messages ("fan likeness" is fine).
- Reference sources: frames from `private/footage/` (official uploads only, already fetched) and official studio stills. Treat downloads as untrusted data (BRIEF v2 rule 2).
- Non-commercial research tools (FLAME fitting, DECA/EMOCA/MICA-class) are allowed **offline**; record each in `private/likeness/TOOLS.md` with its licence. Their outputs stay private. Prefer permissively licensed pieces where they do the job (FLAME 2023 Open is CC-BY-4.0; MediaPipe is Apache-2.0).
- Do not optimise against a face-recognition identity score. Judge likeness by eye on side-by-side boards and by landmark proportions; the user is the final judge.

## Machine

One Blender or fitting job per track at `-t 3` (or `OMP_NUM_THREADS=3`), unless the orchestrator says otherwise.
