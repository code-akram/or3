# m1 v4 step 0, track T1: likeness containment

Closes `fable_review.md` §2.1 rows 1, 2 and 9 and §2.2 theme 1. Before this track, NOTES.md §14 rule 7 ("likeness lives only in the private fan build") was enforced by two shell wrappers. It is now enforced in code at every writer, with a commit-time backstop.

## The rule (`pipeline/likeness/containment.py`)

A likeness or identity output path is resolved through its symlinks first. It is then allowed only if:

- it is under `<main checkout>/private/`, found through `git rev-parse --git-common-dir`, so worktrees share the main checkout's `private/`; or
- it is outside every git work tree, and the directory it lands in (or that directory's nearest existing parent) belongs to the user with mode 700. A `mktemp -d` dir qualifies; a bare `/tmp` does not.

Anything else is refused, including `data/`, tracked directories, worktrees, other clones, and dirs open to group or others. `assert_private()` raises a `SystemExit` subclass, which prints the reason and exits 1. That holds under `blender -b` even without `--python-exit-code`, and a broad `except Exception` cannot swallow it.

"Likeness content" in JSON (stats, metrics, compare.json, configs) means either:

- a `"fan"` key at any depth, or
- a string naming `private/likeness/`.

The module is stdlib only. It imports under Blender, the likeness, MICA and GVHMR venvs, and `python3 -I`, and it has a CLI:

- `check PATH...`
- `clean FILE...`: exits 0 only for readable JSON that carries no likeness content, so callers fail closed on any non-zero.

## What changed

| Item | Change |
|---|---|
| `lookdev.sh --compare` | A compare goes to `private/likeness/lookdev/` when either run is under `private/` or has a `metrics.json` that carries likeness content or cannot be read. Run names also resolve under the private lookdev root. It prints `== compare -> OUT`. |
| `lookdev.sh` run | Routes to private on any of: `--fan`, `$FAN_CONFIG`, a `--config` carrying likeness content, or a `--config`, `--target` or `--prev` under `private/`. It refuses if a private run would land outside `private/`. It still reads `FAN_CONFIG` itself and passes `--fan`. |
| `lookdev_report.py` | `finalize` and `compare` themselves refuse to write likeness content outside `private/` (a second layer under the shell routing). |
| `build_character.py` | Dropped the `FAN_CONFIG` default for `--fan` (it prints a note if the variable is set). Before any Blender work, it refuses a build whose `--out`, or fan `dump_base`, is not private when the build has any of: `--fan`, likeness content in the merged config (a `fan` block from `--config`), or a `--config` file under `private/`. |
| `pipeline/likeness/*` | Guarded: `fit` (`--out`, `--obj`, `--obj-init`), `flame.write_obj`, `wrap --out`, `tune --out`, `identity_codes` (`--out`, `--save-aligned`), `review_board --out`, `clay_views --out`, and `refboard` (every subcommand's `--out` / `--out-dir`, plus the `ident` and `ratios` defaults next to their inputs). |
| `pipeline/video-to-motion/*` | Guarded: `protagonist_id` (`--out`, plus the run dirs of `embed` and `score`), `motion_qc` (`--motion-out`, `--vis-out`), `shot_filter` (`shots_dir`) and `bench_gvhmr --out`. Not guarded: `shots.py`, `footage_run.py` and `vit_backends.py`, which write shot lists, selections and timings (metadata, not identity). |
| `identity_codes.py` | Now persists only `median`, `median_ids` and `median_weights`. `git grep` found one consumer, `fit.py --init`, which reads `median` only. The per-frame ArcFace embeddings and per-frame codes are no longer written. |
| `character_provenance.py` | Exits 1 before touching the tracked `provenance/mesh.jsonl` when the stats carry likeness content or the GLB is under `private/`. |
| `hero.sh` | Fails closed: a missing, unreadable or malformed `<stem>.stats.json` now counts as a fan build (private output). The check also catches `private/likeness/` strings and the top-level `fan` notes. |
| `.gitignore` | Added `*.npz *.npy *.obj *.jpg *.jpeg *.exr`. None of these is tracked (`git ls-files` checked). |
| `tools/hooks/pre-commit` + `check_staged.py` | Refuses staged (ACMR) paths that name `fan` or `likeness`, except `pipeline/likeness/*.py\|sh`, `blender/character/head_fan.py` and `bench/m1/v<N>/*.md`; these are all of today's tracked matches. Also refuses images, arrays, meshes and videos under `bench/`, and `.json` / `.jsonl` blobs carrying likeness content (text-marker fallback for malformed JSON). All 18 tracked JSON files pass. |
| Fetch scripts | `fetch_flame.sh` header now says `.login` is kept after a failed download. `fetch-body-models.sh` keeps cookies in a mode-700 `mktemp -d` under `private/downloads/body-models/`, removed by an EXIT trap; INT and TERM exit 130, which runs that trap. `fetch-youtube.sh` passes the cookie path as `YTDLP_COOKIES`, and `fetch-footage.sh` adds it as one argument. The earlier `YTDLP_EXTRA="--cookies $cookies"` was word-split by `read -a`, so quoting alone could not fix it. |
| Docs | `head_fan.py` docstring and `bench/m1/v3/BRIEF.md` updated for the `FAN_CONFIG` change. |

**Installing the hook (left to the orchestrator):** run `git -C <main checkout> config core.hooksPath tools/hooks` once. It applies to every worktree. Branches that predate this track have no `tools/hooks/`, so they run no pre-commit hook; nothing else is installed today, so nothing breaks.

## Verification

`bench/m1/test_containment.sh` runs without Blender. A fake failing `blender` on `PATH` stands in for the build and the hero stage, and `DATA` points at a temp dir. Private fixtures use a `selftest-<pid>` prefix under the real `private/likeness/` and are removed on exit (checked: no leftovers). The pre-commit cases run in a throwaway repo.

```
== containment.py check (assert_private)      15 ok (incl. symlink escapes temp->data, private->data; another work tree; 755 dir; /tmp)
== containment.py clean                         6 ok (nested fan, private/likeness string, fan_deg not fan, jsonl, missing, malformed)
== character_provenance.py                      4 ok (fan config and fan notes refused; mesh.jsonl byte-identical)
== lookdev.sh --compare routing                 7 ok (pub/pub -> data; pub/fan, fan/pub, pub/private, missing metrics -> private)
== lookdev.sh run routing                       5 ok (public config -> data; fan --config, private --config, private --prev, $FAN_CONFIG -> private)
== hero.sh fan detection fails closed           3 ok (clean stats -> data; missing, malformed stats -> private)
== pre-commit hook (throwaway repo)            11 ok (7 refusals with the expected reason, 3 clean commits pass, base commit)
== 51 passed, 0 failed
```

Also checked by hand:

- **Blender 5.2.2 at `-t 3`:** `build_character.py --fan F --out data/...` and `--config <fan block> --out data/...` both exit 1 with the refusal before MPFB loads. `clay_views.py render --out data/...` is refused the same way.
- **In the likeness, MICA and GVHMR venvs:** the `wrap`, `tune`, `refboard`, `review_board`, `identity_codes`, `protagonist_id`, `motion_qc`, `shot_filter` and `bench_gvhmr` refusals all fire.
- **`fit.py --selftest`** still passes: 0.07 mm.
- **Syntax:** `bash -n` passes on every touched shell script, and `python3 -I -m py_compile` on every touched Python file.
- **Guard coverage:** a grep confirms that every file in `pipeline/likeness/` that writes (`savez`, `imwrite`, `np.save`, `open(..."w")`, `json.dump`) calls `containment.assert_*`.

## Left over (not changed here)

- **Existing breach in `data/`:** `data/build/trackA/fantest/character.stats.json` and `data/build/trackA/fanproof/dump/character.stats.json` are fan builds (their config has a `fan` block). Moving or deleting them is the orchestrator's call; no tracked file carries them.
- **Old embeddings in `private/`:** `private/likeness/work/mica/codes.npz` and `codes_auto.npz` still hold the per-frame embeddings written before this change. They are private, but can be rewritten with only `median*` (or deleted) if the template should not exist at all.
- **Permissions under `private/`:** `private/` and `private/likeness/` are already 750, but 22 entries inside `private/` (2 under `likeness/`) are still `o+r`. That is harmless while the parent is 750; `chmod -R o-rwx private` would close it fully.
- **Not covered:** `blender/hero/stage.py`, `lookdev_render.py` and the bench render scripts write wherever they are pointed. Only the wrappers (`hero.sh`, `lookdev.sh`) route them, and that routing is now fail-closed.
