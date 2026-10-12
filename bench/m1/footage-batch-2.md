# m1 footage batch 2: automatic protagonist ID and official scene clips

Follow-up to the spike-3 footage run (`bench/m0/spike-3-gvhmr.md`, "Footage run"). That run produced 18.1 s of QC-clean Wick motion from 563 s of footage. It found two problems:

- protagonist ID was the bottleneck: the largest-area track was wrong in 12 of 28 multi-person shots, and a human had to read contact sheets;
- the NOTES §8 locomotion targets were not in the featurettes it used.

This batch adds embedding-based protagonist ID, fetches official scene clips for the §8 targets and runs the whole pipeline on them with one driver script.

## Summary (2026-10-12)

- **53.0 s of QC-clean, ID-checked Wick motion from 2247 s of footage (2.4 %), in 21 shots.** Spike 3 got 18.1 s from 563 s.
  - By category: fight 23.6 s, stairs 14.8 s (one Sacré-Cœur climb), other 9.0 s, walk 3.2 s, idle 2.4 s.
  - Turn, draw and reload: 0 s.
- **Automatic protagonist ID.** The seed is right on 22 of 27 batch-1 shots, against 16 for the old default, and on 10 of the 12 shots that needed a hand seed.
  - Presence on batch 1 (thresholds tuned on the same shots): precision 0.64, recall 0.78.
  - **Out of sample on batch 2, auto-picked shots that reached QC-clean: 18 of 22 confirmed Wick, 2 wrong person, 4 unconfirmable.**
  - Probe-passing candidates from the trailer and the range featurette, checked before GVHMR: 7 of 16 right, 4 wrong, 5 unconfirmable.
  - Batch-2 recall is not measured: that would mean labelling all 577 shots.
  - Presence is therefore still checked by eye, but only on the shots that survive QC (one montage per 10 shots), not on every shot.
- **Two pipeline changes did most of the work:**
  - **Luma floor 15 → 6.** 39.5 s of the 53.0 s (13 of 21 shots) comes from shots the spike-3 floor would have dropped (the JW3/JW4 night grade).
  - **ViTPose probe**: 16 frames of the chosen track, about 20 s per shot. It matched the full-run mean confidence within 0.01 on all 7 shots compared, and cut the 215 shots passing coverage and subject size to 47 GVHMR runs.
- **Locomotion is still scarce:** scene clips are mostly fights. Walk / turn / draw stays with 100STYLE / CMU for m2, as planned.

## Yield

All 16 clips ran through `footage-batch.sh` (batch `b2`) under `nice -n 10`:

- YOLO at 3 + 2 processes × 4 threads, then ID, select, probe, GVHMR (bf16 ViTPose + HMR2, 4 × 4 threads), then `motion_qc.py` (foot lock v2) and the summary.
- The machine was shared with Blender look-dev (load average 20–25 on 16 cores).

The table is `footage_run.py summary` output; each column counts the shots still alive after that filter.

- "Wick" is the automatic presence call, overridden where a shot was checked by eye: 15 shots rejected or unconfirmable, in `private/work/b2/content.json`.
- The luma column uses floor 6.

| Clip | Shots | ≥ 1 s | luma ≥ 6 | blur | Wick (auto + check) | coverage ≥ 90 % | subject ≥ 256 px | probe ≥ 0.65 | GVHMR'd | ViTPose ≥ 0.7 | QC-clean | **Clean s** |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| JW4 trailer | 121 | 71 | 67 | 65 | 46 | 33 | 33 | 4 | 4 | 2 | 1 | **1.7** |
| JW3 "Taxi" | 13 | 13 | 13 | 13 | 12 | 6 | 6 | 0 | 0 | 0 | 0 | **0** |
| JW2 "Suited Up" | 18 | 16 | 14 | 13 | 11 | 10 | 10 | 0 | 0 | 0 | 0 | **0** |
| Ballerina "Baba Yaga" | 17 | 17 | 14 | 2 | 2 | 2 | 2 | 0 | 0 | 0 | 0 | **0** |
| JW2 "Training" | 84 | 43 | 40 | 38 | 29 | 13 | 13 | 2 | 2 | 2 | 2 | **3.4** |
| JW3 "Training for John Wick" | 56 | 45 | 44 | 39 | 28 | 17 | 17 | 4 | 4 | 2 | 1 | **1.4** |
| JW3 "Art of Action" | 41 | 33 | 31 | 30 | 17 | 5 | 5 | 0 | 0 | 0 | 0 | **0** |
| JW4 "Stairway Team-Up" | 54 | 50 | 44 | 37 | 34 | 15 | 15 | 5 | 5 | 4 | 2 | **16.8** |
| JW4 "Duel With Pistols" | 47 | 41 | 41 | 40 | 31 | 24 | 21 | 3 | 3 | 3 | 0 | **0** |
| JW4 "Paris Street Fight" | 45 | 43 | 42 | 40 | 33 | 12 | 12 | 3 | 3 | 2 | 2 | **3.3** |
| JW4 "Paint It Black" | 49 | 46 | 42 | 41 | 33 | 4 | 4 | 0 | 0 | 0 | 0 | **0** |
| JW4 "Paris Car Chase" | 59 | 56 | 52 | 48 | 37 | 6 | 6 | 1 | 1 | 1 | 1 | **1.8** |
| JW4 "vs. Caine" | 60 | 55 | 53 | 53 | 47 | 31 | 31 | 9 | 9 | 5 | 2 | **3.4** |
| JW3 "Horse Stable Fight" | 51 | 45 | 39 | 39 | 33 | 5 | 5 | 4 | 4 | 2 | 2 | **5.6** |
| JW3 "Throwing Knives" | 56 | 48 | 47 | 47 | 40 | 20 | 20 | 12 | 12 | 10 | 8 | **15.7** |
| JW3 "Long Live the King" | 39 | 35 | 32 | 32 | 21 | 15 | 15 | 0 | 0 | 0 | 0 | **0** |
| **Total** | 809 | 657 | 615 | 577 | 454 | 218 | 215 | 47 | 47 | 33 | 21 | **53.0** |

### By motion category (QC-clean, checked by eye)

| Category | Shots | Seconds | Content |
|---|---|---|---|
| walk | 2 | 3.2 | Trocadéro walk toward camera (trailer); Osaka Continental gallery walk (vs. Caine) |
| turn | 0 | 0 | |
| stairs | 1 | 14.8 | Sacré-Cœur: up from the ground, stand-off, climb (Stairway Team-Up) |
| idle | 2 | 2.4 | standing among bodies (Throwing Knives); beside the motorbike (Paris Street Fight) |
| draw | 0 | 0 | |
| reload | 0 | 0 | |
| fight | 11 | 23.6 | Throwing Knives ×6, Horse Stable, vs. Caine, Paris street, car chase, judo training (BTS) |
| other | 5 | 9.0 | range shooting ×2 (JW2 training), horseback (JW3), seated on the floor, lying on the stairs |

### Where the shots went

- **Coverage ≥ 90 %** is the largest loss after ID: 454 → 218. Fights fragment the tracker, and short trailer shots are mostly close-ups.
- **The probe** removed 168 of 215: close-ups, medium shots, legs out of frame. Everything from JW3 "Taxi", JW2 "Suited Up" and Ballerina is medium or close.
- **After GVHMR** (47 shots):
  - 14 fail ViTPose ≥ 0.7.
  - Of the 33 that pass ViTPose, 12 fail QC. Reprojection fails on fast motion, partial occlusion and the driver in a car; jitter and spikes fail on fast strikes, as in spike 3.
- **Visual check of the 25 QC-clean overlays** (`private/work/b2/sheets/ovl-*.jpg`, 4 frames per shot):
  - 3 had been checked before GVHMR.
  - Of the 22 auto picks, 18 are Wick.
  - 2 are the wrong person: a crew member at a railing (Art of Action BTS) and a man in a green jacket crawling (Paint It Black).
  - 4 cannot be confirmed: a helmeted motorbike rider, a tiny distant figure at the duel, and two small figures in crowds. All 6 non-confirmed shots were dropped.

### Wall clock (shared machine, not comparable to the idle bench)

| Stage | Wall clock |
|---|---|
| YOLO, 577 shots, 3 + 2 processes × 4 threads | ~4 h 30 min |
| ID (embed + score), 16 threads | ~5 min |
| Probe, 219 candidates, 4 processes | ~11 min |
| GVHMR + QC, final 30 shots, 4 processes (17 earlier, alongside YOLO) | ~25 min |

## Protagonist ID (`protagonist_id.py`)

### Method

Every person track from the YOLO + BoT-SORT stage (`preprocess/track_history.pt`) is embedded on up to 12 evenly spaced frames. Tracks shorter than 6 frames or under 64 px tall are skipped.

- **Body:** OSNet-AIN x1.0, a person re-ID network trained on MSMT17. Input is the 256 × 128 box crop; output is 512-d. Re-ID features describe clothes, hair and build rather than background, which suits a suited, long-haired lead.
- **Face:**
  - YuNet finds faces in the top 45 % of the box.
  - Each face is aligned on 5 points to the ArcFace template and embedded with ArcFace `w600k_r50` (512-d).
  - Each face keeps its detector score, size and frontal offset. Only faces with score ≥ 0.85, ≥ 28 px and offset ≤ 0.3 count.

A **gallery** holds the embeddings of hand-verified Wick tracks: the 27 verified batch-1 shots, giving 358 body crops and 37 faces. Gallery faces are cluster-cleaned: a face is dropped when its median similarity to the other gallery faces is below 0.15, because the verified chains contain stray faces (an opponent in the same box, motion blur).

**Similarity** of a track to the gallery, per modality: for each sampled frame, the mean of its top-k cosine similarities to the gallery; then the median over frames.

**Decision** (`choose`):

- **Seed:** among tracks covering ≥ 20 % of the shot, the one with the highest body similarity.
- **Present:** the seed's face similarity is ≥ 0.30, or its body similarity is ≥ 0.58, and no confident face mismatch (≥ 2 gated faces with similarity < 0.12) vetoes it.
- **Exclude:** fragments that are never stitched into the chain. These are fragments with a confident face mismatch, or with body similarity more than 0.08 below the seed's, unless their face matches.

`bench_gvhmr.py stitch_protagonist` takes `seed` and `exclude`. `protagonist_id.py score` writes `RUN_DIR/protagonist.json`, which two readers use:

- `footage_run.py select --auto-id` takes coverage, subject size and presence from it;
- `bench_gvhmr.py --auto-id --reuse yolo` restitches the chain from it.

`protagonist_id.py sheet` draws the chosen chain (red) on 3 frames per shot for the one remaining manual step: accept or reject the GVHMR candidates.

### What did not work

All of these were measured on batch 1 before settling on the method above.

- **DINOv2 ViT-S/14 body features and the SFace recogniser:** separation AUC about 0.6, and the pick was right in 17 of 25 shots. DINOv2 describes scene and pose, not identity.
- **Ungated ArcFace:** on film frames (dark grade, motion blur, profiles) the median pairwise similarity between verified Wick faces was about 0.1, which is noise. With the quality gate, the few faces that remain agree (median about 0.36).
- **Ranking by face first:** worse than body only. In fights, the opponent's face sometimes matched, and that face outvoted the body ranking.

### Validation against the batch-1 hand seeds

Ground truth is `private/work/protagonist-id/gt-batch1.json`:

- **27 positives:** the 25 shots the batch-1 track check confirmed (12 hand-reseeded with `--seed-id`, 13 where the default seed was verified correct), plus two BTS shots of Keanu in costume that the content review had labelled "other" (IGN BTS #7, #82).
- **16 negatives:** shots labelled "other" with no Wick.
- **5 dropped** as ambiguous.

The gallery is rebuilt leave-one-clip-out, so each shot is scored against a gallery built only from the other clips. A pick counts as correct when its stitched chain overlaps the verified chain (IoU ≥ 0.5) on ≥ 80 % of the verified chain's frames.

| | Automatic | Batch-1 default (largest area) |
|---|---|---|
| Correct seed, all 27 positives | **22 / 27 (81 %)** | 16 / 27 (59 %)¹ |
| Correct seed, the 12 shots a human reseeded | **10 / 12** | 1 / 12² |
| Correct seed, the 13 shots where the default was verified right | 11 / 13 | 13 / 13 |
| Correct seed, the 2 BTS shots added afterwards | 1 / 2 | 2 / 2 |
| Presence: precision / recall (positive = Wick present and the right track chosen) | **0.64 / 0.78** (21 true of 33 called) | n/a (manual) |
| Negatives called present | 8 / 16 | n/a |
| Wrong person called present on a positive | 4 / 27 | |

¹ Counted with the same chain-agreement test as the automatic pick.
² New Challenges #28: the hand seed and the default chain overlap on ≥ 80 % of frames.

**Reading:**

- Seed choice is automatic now: it is right on 81 % of shots, against 59 % for the default, and on 10 of the 12 shots that needed a human.
- Presence is not: dark-suited crew, extras and stunt doubles clear the body threshold. Presence is therefore a recall-tuned pre-filter. The contact sheet of GVHMR candidates replaces labelling every shot and hand-seeding, but it is still a manual check.
- **Caveat:** the thresholds were tuned on these same 43 shots; only the gallery is held out. Batch 2 below is the out-of-sample check.

### Models and licences

None of these ship; all run offline on CPU, and the weights live in `private/models/protagonist-id/`. Embeddings, galleries and crops are under `private/work/`.

| File | What | Source | Licence | sha256 |
|---|---|---|---|---|
| `face_detection_yunet_2023mar.onnx` | YuNet face detector | opencv_zoo | MIT | `8f2383e4…52fa4` |
| `arcface_w600k_r50.onnx` | ArcFace R50 recogniser (InsightFace buffalo_l) | HF `immich-app/buffalo_l` `recognition/model.onnx` | InsightFace pretrained models: **non-commercial research only** | `4c06341c…19e43` |
| `osnet_ain_x1_0_msmt17.pth` | OSNet-AIN x1.0 re-ID, MSMT17 | HF `kaiyangzhou/osnet` (deep-person-reid model zoo) | MIT (repo label) | `8a07e8da…d919f` |
| `private/src/deep-person-reid/osnet_ain.py` | OSNet-AIN model definition | deep-person-reid @ 566a56a | MIT | `a43b4958…cd25` |
| `face_recognition_sface_2021dec.onnx` | SFace (tried, unused) | opencv_zoo | Apache-2.0 | `0ba9fbfa…79c34` |

ArcFace falls under the user's non-commercial exception (2026-10-12). It is an offline pipeline tool and never ships. If that ever changes, the face path can be dropped: body only is the stronger signal (see "What did not work").

Runtime: embedding and scoring 577 runs took about 5 min at 16 threads. Embeddings are cached per run (`preprocess/track_emb.npz`).

**Batch-2 observation:** on sharp 1080p scene clips (the trailer), gated faces separate cleanly: Wick 0.50–0.65, everyone else ≤ 0.23. Body similarity sat at 0.60–0.79 for nearly every dark-clothed person, so the batch-1 `BODY_YES` calls almost everyone present. A loosened face veto was tried; on batch 1 it would have vetoed 25–50 % of true Wick tracks (featurette faces score low), so it was not adopted.

## Clip selection

### Sources

- **Lionsgate Movies uploads no JW4 scene clips.** Its JW4 uploads are trailers and featurettes; the full films it hosts are not used (§8). From Lionsgate Movies this batch takes:
  - the JW4 trailer, which has short Sacré-Cœur, Osaka and Paris shots;
  - the JW2 and JW3 clips and featurettes, which carry training-range footage (§8's Taran Butler target).
- **Official JW4 scene clips are on Movieclips (Fandango).** That channel is the studios' licensed scene-clip outlet; JoBlo, KinoCheck, Boxoffice and similar re-uploads are not official.
  - I treated Movieclips as studio-supplied clips under the 2026-10-12 ruling.
  - **This is an interpretation for the user to confirm.** The Movieclips block in `fetch-footage.sh` is self-contained and commented, so it can be dropped.
- **§8 targets not found as standalone official clips:** the Osaka Continental walks and draws, the Paris Metro idle, the top-down apartment oner, and the Arc de Triomphe hood slides as their own clip.
  - The Arc de Triomphe is inside "Paris Car Chase"; Sacré-Cœur is in "Stairway Team-Up"; Paris street walks are in "Duel With Pistols" and "Paris Street Fight".
  - No §8 target was found with a known timestamp short enough to justify trimming, so all entries are `full`.

All 16 were fetched at 1920 × 1080, 23.976 fps, into `private/footage/<id>/source.mp4`.

| Clip | Channel | Title | §8 target |
|---|---|---|---|
| `yt-qEVUtrk8_B4` | Lionsgate Movies | JW4 official trailer | Sacré-Cœur, Osaka, Paris shots |
| `yt-Mioo2uqCSG0` | Lionsgate Movies | JW3 clip "Taxi" | injured walk / run |
| `yt-y7pLCd7BgZA` | Lionsgate Movies | JW2 clip "Suited Up" | suit adjust, idle |
| `yt-5O2SZVS26Dg` | Lionsgate Movies | Ballerina clip "Baba Yaga" | (Wick cameo) |
| `yt-4r5_5eOmxzA` | Lionsgate Movies | JW2 featurette "Training" | Taran Butler range |
| `yt-MW0mu_TPua4` | Lionsgate Movies | JW3 BTS "Training for John Wick" | range, judo |
| `yt-YO3cBrcDiT0` | Lionsgate Movies | JW3 BTS "Art of Action" | fight training |
| `yt-hrq7sSV3dkA` | Movieclips | JW4 "Stairway Team-Up" | Sacré-Cœur stairs |
| `yt-Xw70HfHVfWQ` | Movieclips | JW4 "The Duel With Pistols" | Paris walk, draw |
| `yt-oa7BjVtvA7w` | Movieclips | JW4 "Paris Street Fight" | Paris street |
| `yt-jUIZdspS32E` | Movieclips | JW4 "Paint It Black" (Paris nightclub fight) | fight (the top-down oner was not found) |
| `yt-Lqii8YkcCDI` | Movieclips | JW4 "Paris Car Chase" | Arc de Triomphe |
| `yt-SyEU1pN1Uj0` | Movieclips | JW4 "John Wick vs. Caine" | fight |
| `yt-Sw4pvbkQ-jk` | Movieclips | JW3 "Horse Stable Fight" | fight |
| `yt-v00zKyXbfD4` | Movieclips | JW3 "Throwing Knives" | fight |
| `yt-L-zzxADqlu8` | Movieclips | JW3 "Long Live the King" | fight, walk |

### Luma floor lowered to 6 for this batch

JW4's night grade sits below the spike-3 floor of median luma ≥ 15. At 15:

- "Stairway Team-Up" kept 3 of 54 shots;
- "Paris Street Fight" kept 3 of 45;
- "Paris Car Chase" kept 10 of 59.

Their median shot luma is 8–14, and YOLO and ViTPose still work there. `MIN_LUMA=6` (new `footage-batch.sh filter`) raised the stage-1 survivors from 271 to 577 shots. Below 6, shots are fades and black frames. The yield table shows what the extra shots bought.

## Recommendations

1. **Scene clips over featurettes, with the luma floor at 6 for graded film.**
   - The two Movieclips scenes with long, wide takes ("Throwing Knives" and "Stairway Team-Up") gave 32.5 of the 53 s.
   - Trailers and featurettes yield almost nothing once the probe drops close-ups.
2. **Keep the probe in front of GVHMR, and consider raising it to 0.70.** It costs about 20 s per shot, against minutes for GVHMR, and it tracked the full-run ViTPose mean within 0.01.
3. **Do not chase full automation of presence with these models.**
   - Faces decide only when a gated face is visible.
   - Otherwise body re-ID says "dark-suited man", which matches guards, doubles and Caine.
   - The cheap, reliable check is the overlay montage of QC-clean shots.
4. **m2 locomotion stays on 100STYLE / CMU.**
   - Official scene clips contain 3.2 s of walk and no turn, draw or reload.
   - The film yield feeds m3: fights, the stair climb and idle stance.
   - The Osaka Continental walks, Metro idle and apartment oner have no official standalone clip. They remain a gap unless another studio-supplied source turns up.
5. **The next lever is coverage** (454 → 218 shots). Stitch across longer tracker gaps in fights: `max_gap` 24 → 48, or use the body embeddings already computed to bridge fragments.

## Reproduce

```bash
pipeline/video-to-motion/fetch-youtube.sh          # the batch-2 entries in fetch-footage.sh (cookies)
PY=private/src/gvhmr-rudes/.venv/bin/python
# one-time: gallery from the hand-verified batch-1 tracks, and the leave-one-clip-out check
$PY -I pipeline/video-to-motion/protagonist_id.py gallery --gt private/work/protagonist-id/gt-batch1.json \
  --out private/work/protagonist-id/gallery.npz
$PY -I pipeline/video-to-motion/protagonist_id.py validate --gt private/work/protagonist-id/gt-batch1.json \
  --out private/work/protagonist-id/val-final.json
CLIPS="yt-qEVUtrk8_B4 yt-Mioo2uqCSG0 yt-y7pLCd7BgZA yt-5O2SZVS26Dg yt-4r5_5eOmxzA yt-MW0mu_TPua4 yt-YO3cBrcDiT0
  yt-hrq7sSV3dkA yt-Xw70HfHVfWQ yt-oa7BjVtvA7w yt-jUIZdspS32E yt-Lqii8YkcCDI yt-SyEU1pN1Uj0 yt-Sw4pvbkQ-jk
  yt-v00zKyXbfD4 yt-L-zzxADqlu8"
MIN_LUMA=6 pipeline/video-to-motion/footage-batch.sh all b2 $CLIPS
# check private/work/vis/b2-*/overlay_2d.mp4 of the QC-clean shots; list rejects in private/work/b2/content.json
# ({clip: {"not_wick": [idx]}}), then re-run the `probe` stage (probes are cached; it re-selects) and `summary`
```

## Files

Committed:

- `pipeline/video-to-motion/protagonist_id.py` (new): embed / gallery / score / validate / sheet.
- `pipeline/video-to-motion/footage-batch.sh` (new): the batch driver.
- `pipeline/video-to-motion/bench_gvhmr.py`:
  - `stitch_protagonist(seed=, exclude=)`;
  - `--auto-id`;
  - `--vitpose-probe N`.
- `pipeline/video-to-motion/footage_run.py`:
  - `select --auto-id`, `--min-probe`, and `--content` overrides;
  - a probe column in the summary.
- `pipeline/video-to-motion/fetch-footage.sh`: the batch-2 entries.

Private (film-derived, never committed):

- `private/work/protagonist-id/`: ground truth, gallery, validation rows.
- `private/work/b2/`: selections, labels, categories, sheets, logs.
- `private/motion/b2-*`: npz and BVH.
- `private/work/vis/b2-*`: overlays.
