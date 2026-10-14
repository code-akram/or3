"""Automatic protagonist ID for the video-to-motion pipeline (NOTES.md §8): which tracker fragment is Wick.

Each person track from the YOLO stage (``track_history.pt``) is embedded on up to 12 sampled frames:

* **body**: OSNet-AIN x1.0 person re-ID (Zhou et al.; MIT code, MSMT17-trained weights from the author's
  model zoo), 512-d, on the whole box. Re-ID features describe clothes, hair and build, not background.
* **face**: OpenCV YuNet detector (MIT) on the top of the box, 5-point alignment, ArcFace ``w600k_r50``
  (InsightFace buffalo_l recogniser, 512-d; InsightFace models are licensed for non-commercial research
  only: offline use here, never shipped). Each face keeps its detector score, size and frontality, and
  only faces passing the quality gate count: on dark, blurred or profile film faces ArcFace is noise.

Per track and modality, the similarity to a **reference gallery** (embeddings of hand-verified Wick
tracks) is the median over its sampled frames of the mean of the top-k cosine similarities.

* **Seed**: among tracks covering >= 20 % of the shot, the highest body similarity. (Ranking by face
  first was worse: opponents' faces sometimes match. Validated leave-one-clip-out on batch 1, see
  bench/m1/footage-batch-2.md.)
* **Present**: the seed's face matches, or its body similarity clears ``BODY_YES``; a confident face
  mismatch vetoes. This is a pre-filter tuned for recall, not a verdict: dark-suited extras and crew
  pass it, so the selected tracks of the shots headed to GVHMR are still checked on one contact sheet.
* **Exclude**: fragments whose face clearly mismatches, or whose body similarity is far below the
  seed's, are never stitched into the protagonist chain.

``score`` writes ``RUN_DIR/protagonist.json`` (seed, present, exclusions, chain, coverage, subject size),
which footage_run.py ``select --auto-id`` and bench_gvhmr.py ``--auto-id`` read.

Weights live in ``private/models/protagonist-id/``; the OSNet-AIN model definition is the upstream
``torchreid/models/osnet_ain.py`` (deep-person-reid @ 566a56a, MIT) in ``private/src/deep-person-reid/``.
Embeddings, galleries and crops derive from film frames and stay under private/.

    python -I protagonist_id.py embed RUN_DIR [...] [--runs-file F]      # cache per-track embeddings
    python -I protagonist_id.py gallery --gt gt.json --out G.npz         # from hand-verified tracks
    python -I protagonist_id.py score --gallery G.npz RUN_DIR [...]      # writes RUN_DIR/protagonist.json
    python -I protagonist_id.py validate --gt gt.json --out val.json     # leave-one-clip-out check
    python -I protagonist_id.py sheet --runs-file F --out sheet.jpg      # contact sheet of the chosen chains
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I drops the script dir from sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent / "likeness"))
import containment  # noqa: E402

ROOT = Path(os.environ.get("MAIN_ROOT", "/home/akram/code/or3"))
MODELS = ROOT / "private/models/protagonist-id"
OSNET_SRC = ROOT / "private/src/deep-person-reid"
YUNET = MODELS / "face_detection_yunet_2023mar.onnx"
ARCFACE = MODELS / "arcface_w600k_r50.onnx"
OSNET = MODELS / "osnet_ain_x1_0_msmt17.pth"
BODY_HW = (256, 128)
DIM = 512
# ArcFace 112x112 alignment template (InsightFace), in YuNet landmark order: eyes, nose, mouth corners.
ARC_TEMPLATE = np.array([[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366],
                         [41.5493, 92.3655], [70.7299, 92.2041]], np.float32)

# Face quality gate (applied when scoring; the cache keeps every YuNet face >= 0.7).
FACE_MIN_SCORE = 0.85
FACE_MIN_PX = 28
FACE_MAX_OFFSET = 0.3   # |nose - eye midpoint| / eye distance (0 = frontal)
# Decision rule, calibrated on batch 1 (bench/m1/footage-batch-2.md, "Protagonist ID").
MIN_COVERAGE = 0.2      # a seed must cover this share of the shot
FACE_YES = 0.30         # ArcFace similarity that counts as a Wick face
FACE_NO = 0.12          # ... and below which (with >= 2 gated faces) a track is someone else
BODY_YES = 0.58         # OSNet similarity that counts as Wick without a face
BODY_GAP = 0.08         # fragments this far below the seed's body similarity are not stitched


class Embedder:
    def __init__(self, threads: int = 4):
        import cv2
        import torch

        torch.set_num_threads(threads)
        cv2.setNumThreads(threads)
        self.cv2, self.torch = cv2, torch
        self.det = cv2.FaceDetectorYN.create(str(YUNET), "", (320, 320), 0.7, 0.3, 50)
        self.arc = cv2.dnn.readNetFromONNX(str(ARCFACE))
        sys.path.insert(0, str(OSNET_SRC))
        import osnet_ain

        self.body_net = osnet_ain.osnet_ain_x1_0(num_classes=1, pretrained=False, loss="softmax")
        sd = torch.load(OSNET, map_location="cpu", weights_only=False)
        sd = {k.removeprefix("module."): v for k, v in sd.get("state_dict", sd).items()}
        sd = {k: v for k, v in sd.items() if not k.startswith("classifier")}
        missing, unexpected = self.body_net.load_state_dict(sd, strict=False)
        if unexpected or set(missing) - {"classifier.weight", "classifier.bias"}:
            raise RuntimeError(f"OSNet weights do not match: missing {missing}, unexpected {unexpected}")
        self.body_net.eval()
        self.mean = np.array([0.485, 0.456, 0.406], np.float32)
        self.std = np.array([0.229, 0.224, 0.225], np.float32)

    def face(self, img: np.ndarray, box: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
        """Best face in the top 45 % of the person box (expanded 15 % sideways): (ArcFace embedding,
        quality [detector score, min side px, frontal offset])."""
        cv2 = self.cv2
        H, W = img.shape[:2]
        x0, y0, x1, y1 = box
        w, h = x1 - x0, y1 - y0
        cx0, cx1 = int(max(0, x0 - 0.15 * w)), int(min(W, x1 + 0.15 * w))
        cy0, cy1 = int(max(0, y0 - 0.05 * h)), int(min(H, y0 + 0.45 * h))
        if cx1 - cx0 < 24 or cy1 - cy0 < 24:
            return None
        crop = img[cy0:cy1, cx0:cx1]
        self.det.setInputSize((crop.shape[1], crop.shape[0]))
        _, faces = self.det.detect(crop)
        if faces is None or len(faces) == 0:
            return None
        f = max(faces, key=lambda r: r[-1] * r[2] * r[3])
        if min(f[2], f[3]) < 16:
            return None
        lm = f[4:14].reshape(5, 2).astype(np.float32)
        eye = abs(lm[1, 0] - lm[0, 0])
        offset = abs(lm[2, 0] - (lm[0, 0] + lm[1, 0]) / 2) / max(eye, 1.0)
        M, _ = cv2.estimateAffinePartial2D(lm, ARC_TEMPLATE)
        if M is None:
            return None
        aligned = cv2.warpAffine(crop, M, (112, 112), borderValue=0)
        blob = cv2.dnn.blobFromImage(aligned, 1 / 127.5, (112, 112), (127.5, 127.5, 127.5), swapRB=True)
        self.arc.setInput(blob)
        e = self.arc.forward().reshape(-1).astype(np.float32)
        return e / (np.linalg.norm(e) + 1e-9), np.array([f[-1], min(f[2], f[3]), offset], np.float32)

    def body(self, crops: list[np.ndarray]) -> np.ndarray:
        if not crops:
            return np.zeros((0, DIM), np.float32)
        cv2 = self.cv2
        x = np.stack([
            (cv2.cvtColor(cv2.resize(c, BODY_HW[::-1], interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
             .astype(np.float32) / 255 - self.mean) / self.std
            for c in crops
        ]).transpose(0, 3, 1, 2)
        with self.torch.no_grad():
            e = self.body_net(self.torch.from_numpy(np.ascontiguousarray(x))).numpy()
        return e / (np.linalg.norm(e, axis=1, keepdims=True) + 1e-9)


def fragments(track_history) -> dict[int, dict[int, np.ndarray]]:
    frags: dict[int, dict[int, np.ndarray]] = {}
    for f, dets in enumerate(track_history):
        for d in dets:
            frags.setdefault(int(d["id"]), {})[f] = np.asarray(d["bbx_xyxy"], dtype=np.float64)
    return frags


def embed_tracks(video: str, track_history, emb: Embedder, per_track: int = 12, min_frames: int = 6,
                 min_h: float = 64) -> dict[int, dict]:
    """Per track: sampled frames, body embeddings, faces with quality. Tracks shorter than ``min_frames``
    (with boxes >= ``min_h`` px) get no embeddings and so can neither seed nor be scored."""
    import cv2

    frags = fragments(track_history)
    want: dict[int, list[tuple[int, np.ndarray]]] = {}
    for k, v in frags.items():
        fs = [f for f in sorted(v) if v[f][3] - v[f][1] >= min_h]
        if len(fs) < min_frames:
            continue
        for f in np.array(fs)[np.linspace(0, len(fs) - 1, min(per_track, len(fs))).round().astype(int)]:
            want.setdefault(int(f), []).append((k, v[int(f)]))
    out = {k: {"n_frames": len(v), "frames": [], "face": [], "face_q": [], "crops": []} for k, v in frags.items()}
    cap = cv2.VideoCapture(video)
    f, last = 0, max(want) if want else -1
    while f <= last:
        ok, img = cap.read()
        if not ok:
            break
        for k, box in want.get(f, []):
            x0, y0 = max(int(round(box[0])), 0), max(int(round(box[1])), 0)
            x1, y1 = min(int(round(box[2])), img.shape[1]), min(int(round(box[3])), img.shape[0])
            if x1 - x0 < 8 or y1 - y0 < 16:
                continue
            o = out[k]
            o["frames"].append(f)
            o["crops"].append(img[y0:y1, x0:x1])
            fe = emb.face(img, box)
            if fe is not None:
                o["face"].append(fe[0])
                o["face_q"].append(fe[1])
        f += 1
    cap.release()
    for o in out.values():
        o["body"] = emb.body(o.pop("crops"))
        o["face"] = np.array(o["face"], np.float32).reshape(-1, DIM)
        o["face_q"] = np.array(o["face_q"], np.float32).reshape(-1, 3)
    return out


def save_tracks(path: Path, tracks: dict[int, dict]) -> None:
    arr = {}
    for k, t in tracks.items():
        arr |= {f"{k}_face": t["face"], f"{k}_faceq": t["face_q"], f"{k}_body": t["body"],
                f"{k}_frames": np.array(t["frames"], np.int32), f"{k}_n": np.array(t["n_frames"])}
    np.savez(path, **arr)


def load_tracks(path: Path) -> dict[int, dict]:
    z = np.load(path)
    ids = sorted({int(n.split("_")[0]) for n in z.files})
    return {k: {"face": z[f"{k}_face"], "face_q": z[f"{k}_faceq"], "body": z[f"{k}_body"],
                "frames": z[f"{k}_frames"].tolist(), "n_frames": int(z[f"{k}_n"])} for k in ids}


def good_faces(t: dict) -> np.ndarray:
    q = t["face_q"]
    keep = (q[:, 0] >= FACE_MIN_SCORE) & (q[:, 1] >= FACE_MIN_PX) & (q[:, 2] <= FACE_MAX_OFFSET)
    return t["face"][keep]


def _sim(q: np.ndarray, g: np.ndarray, k: int) -> float | None:
    if len(q) == 0 or len(g) == 0:
        return None
    s = q @ g.T
    return float(np.median(np.sort(s, axis=1)[:, -min(k, s.shape[1]):].mean(axis=1)))


def score_tracks(tracks: dict[int, dict], gallery: dict[str, np.ndarray], L: int) -> dict[int, dict]:
    res = {}
    for k, t in tracks.items():
        if len(t["body"]) == 0:
            continue
        faces = good_faces(t)
        face = _sim(faces, gallery["face"], 3)
        res[k] = {"n_frames": t["n_frames"], "coverage": round(t["n_frames"] / L, 3), "n_faces": len(faces),
                  "face_sim": None if face is None else round(face, 3),
                  "body_sim": round(_sim(t["body"], gallery["body"], 5), 3)}
    return res


def face_yes(v: dict) -> bool:
    return v["face_sim"] is not None and v["face_sim"] >= FACE_YES


def face_no(v: dict) -> bool:
    return v["face_sim"] is not None and v["n_faces"] >= 2 and v["face_sim"] < FACE_NO


def choose(scores: dict[int, dict]) -> tuple[int | None, dict]:
    cand = {k: v for k, v in scores.items() if v["coverage"] >= MIN_COVERAGE} or scores
    if not cand:
        return None, {"present": False, "reason": "no embeddable track"}
    rank = sorted(cand, key=lambda k: cand[k]["body_sim"], reverse=True)
    seed, v = rank[0], cand[rank[0]]
    present = (face_yes(v) or v["body_sim"] >= BODY_YES) and not face_no(v)
    exclude = sorted(k for k, w in scores.items()
                     if k != seed and (face_no(w) or w["body_sim"] < v["body_sim"] - BODY_GAP) and not face_yes(w))
    reason = "face" if face_yes(v) else "body" if present else "face mismatch" if face_no(v) else "low body"
    return seed, {"present": present, "reason": reason, "body_sim": v["body_sim"], "face_sim": v["face_sim"],
                  "margin": round(v["body_sim"] - (cand[rank[1]]["body_sim"] if len(rank) > 1 else 0.0), 3),
                  "exclude": exclude}


def load_gallery(path: str | Path) -> dict[str, np.ndarray]:
    z = np.load(path)
    return {k: z[k] for k in z.files}


def build_gallery(chains: list[tuple[dict[int, dict], list[int]]], min_face_consensus: float = 0.15) -> dict:
    """Gallery from verified chains: every body crop; quality-gated faces that agree with the other
    gallery faces (median similarity >= ``min_face_consensus``), which drops stunt doubles, opponents'
    faces caught in the head crop and detector misfires."""
    bodies, faces = [], []
    for tracks, chain in chains:
        for k in chain:
            if k in tracks:
                bodies.append(tracks[k]["body"])
                faces.append(good_faces(tracks[k]))
    face = np.concatenate(faces) if faces else np.zeros((0, DIM), np.float32)
    if len(face) >= 3:
        s = face @ face.T
        np.fill_diagonal(s, np.nan)
        face = face[np.nanmedian(s, axis=1) >= min_face_consensus]
    return {"face": face, "body": np.concatenate(bodies)}


def run_paths(run_dir: Path) -> tuple[Path, Path, Path]:
    """(stage video, track_history.pt, embedding cache) of a bench_gvhmr.py run directory."""
    vids = sorted(run_dir.glob("*/0_input_video.mp4"))
    if not vids:
        raise FileNotFoundError(f"no stage video under {run_dir}")
    pre = vids[0].parent / "preprocess"
    return vids[0], pre / "track_history.pt", pre / "track_emb.npz"


def run_paths_ok(rd: Path, i: int = 2) -> bool:
    """run_paths(rd)[i] exists (default: the embedding cache; 1: the track history)."""
    try:
        return run_paths(rd)[i].exists()
    except FileNotFoundError:
        return False


def video_wh(vid: Path) -> tuple[int, int]:
    import cv2

    cap = cv2.VideoCapture(str(vid))
    wh = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    return wh


def pick(rd: Path, gallery: dict[str, np.ndarray]) -> dict:
    """Seed, presence and the resulting protagonist chain for one run directory (cached embeddings)."""
    import torch

    from bench_gvhmr import stitch_protagonist

    vid, th, cache = run_paths(rd)
    hist = torch.load(th, weights_only=False)
    W, H = video_wh(vid)
    scores = score_tracks(load_tracks(cache), gallery, len(hist))
    seed, info = choose(scores)
    info["seed"] = seed
    if seed is not None:
        chain, fb = stitch_protagonist(hist, W, H, seed=seed, exclude=info["exclude"])
        info |= {"chain": [int(c) for c in chain], "coverage": round(len(fb) / len(hist), 3),
                 "subject_px": round(float(np.median([b[3] - b[1] for b in fb.values()])), 1)}
    info["tracks"] = {str(k): v for k, v in scores.items()}
    return info


def run_list(a) -> list[Path]:
    runs = list(a.runs)
    if a.runs_file:
        runs += [line.strip() for line in Path(a.runs_file).read_text().splitlines() if line.strip()]
    return [Path(r) for r in runs]


def cmd_embed(a) -> None:
    import torch

    emb = Embedder(a.threads)
    for rd in run_list(a):
        if not run_paths_ok(rd, 1):  # no person tracked (or the YOLO stage has not finished)
            continue
        vid, th, cache = run_paths(rd)
        if cache.exists() and not a.force:
            continue
        tracks = embed_tracks(str(vid), torch.load(th, weights_only=False), emb, per_track=a.per_track)
        save_tracks(cache, tracks)
        print(f"{rd.name}: {sum(len(t['body']) > 0 for t in tracks.values())} tracks embedded, "
              f"{sum(len(good_faces(t)) for t in tracks.values())} good faces", flush=True)


def gt_chains(gt: dict, root: Path, prefix: str) -> dict[str, tuple[dict, list[int], dict]]:
    """shot -> (track embeddings, verified chain, verified frame boxes)."""
    import torch

    from bench_gvhmr import stitch_protagonist

    out = {}
    for shot, seed in gt["positives"].items():
        vid, th, cache = run_paths(root / f"{prefix}{shot}")
        hist = torch.load(th, weights_only=False)
        W, H = video_wh(vid)
        chain, fb = stitch_protagonist(hist, W, H, seed=None if seed == "default" else int(seed))
        out[shot] = (load_tracks(cache), chain, fb)
    return out


def cmd_gallery(a) -> None:
    gt = json.loads(Path(a.gt).read_text())
    chains = gt_chains(gt, Path(a.runs_root), a.prefix)
    g = build_gallery([(t, c) for t, c, _ in chains.values()])
    np.savez(a.out, **g, shots=np.array(sorted(chains)))
    print(f"gallery {a.out}: {len(g['face'])} faces, {len(g['body'])} body crops from {len(chains)} verified shots")


def cmd_score(a) -> None:
    gal = load_gallery(a.gallery)
    for rd in run_list(a):
        if not run_paths_ok(rd):
            continue
        info = pick(rd, gal)
        (rd / "protagonist.json").write_text(json.dumps(info, indent=1))
        print(f"{rd.name}: seed {info['seed']} present={info['present']} ({info['reason']}) "
              f"body {info.get('body_sim')} face {info.get('face_sim')} cov {info.get('coverage')}", flush=True)


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    i = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i
    return i / u if u > 0 else 0.0


def agreement(fb_auto: dict[int, np.ndarray], fb_gt: dict[int, np.ndarray]) -> float:
    """Share of the verified chain's frames where the automatic chain has a box with IoU >= 0.5."""
    return float(np.mean([f in fb_auto and _iou(fb_auto[f], b) >= 0.5 for f, b in fb_gt.items()]))


def cmd_validate(a) -> None:
    """Leave-one-clip-out validation against hand-verified protagonist tracks.

    For each clip, the gallery holds the verified Wick chains of the *other* clips only. A positive shot
    is correct when the automatic chain agrees with the verified chain on >= 80 % of its frames and the
    shot is called present. Negative shots (verified: no Wick) should be called absent."""
    import torch

    from bench_gvhmr import stitch_protagonist

    gt = json.loads(Path(a.gt).read_text())
    root = Path(a.runs_root)
    clip_of = lambda s: s.rsplit("-s", 1)[0]  # noqa: E731
    pos = gt_chains(gt, root, a.prefix)
    rows = []
    for shot in [*pos, *gt["negatives"]]:
        clip = clip_of(shot)
        gal = build_gallery([(t, c) for s, (t, c, _) in pos.items() if clip_of(s) != clip])
        rd = root / f"{a.prefix}{shot}"
        info = pick(rd, gal)
        row = {"shot": shot, "positive": shot in pos, "seed": info["seed"], "present": info["present"],
               "reason": info["reason"], "body_sim": info.get("body_sim"), "face_sim": info.get("face_sim")}
        if shot in pos:
            vid, th, _ = run_paths(rd)
            hist = torch.load(th, weights_only=False)
            W, H = video_wh(vid)
            _, dfb = stitch_protagonist(hist, W, H)
            _, fb = stitch_protagonist(hist, W, H, seed=info["seed"], exclude=info["exclude"])
            row |= {"agreement": round(agreement(fb, pos[shot][2]), 3),
                    "default_agreement": round(agreement(dfb, pos[shot][2]), 3)}
            row["seed_ok"] = row["agreement"] >= 0.8
            row["default_ok"] = row["default_agreement"] >= 0.8
        print(row, flush=True)
        row["tracks"] = info["tracks"]
        if shot in pos:
            row["gt_chain"] = [int(c) for c in pos[shot][1]]
        rows.append(row)
    P = [r for r in rows if r["positive"]]
    N = [r for r in rows if not r["positive"]]
    tp = sum(r["present"] and r["seed_ok"] for r in P)
    claimed = sum(r["present"] for r in rows)
    res = {"positives": len(P), "negatives": len(N),
           "seed_correct": sum(r["seed_ok"] for r in P), "default_seed_correct": sum(r["default_ok"] for r in P),
           "called_present": claimed, "true_positive": tp,
           "false_present_on_negatives": sum(r["present"] for r in N),
           "wrong_person_called_present": sum(r["present"] and not r["seed_ok"] for r in P),
           "precision": round(tp / max(claimed, 1), 3), "recall": round(tp / max(len(P), 1), 3),
           "params": {k: globals()[k] for k in ("MIN_COVERAGE", "FACE_YES", "FACE_NO", "BODY_YES", "BODY_GAP",
                                                "FACE_MIN_SCORE", "FACE_MIN_PX", "FACE_MAX_OFFSET")},
           "rows": rows}
    Path(a.out).write_text(json.dumps(res, indent=1))
    print({k: v for k, v in res.items() if k != "rows"})


def cmd_sheet(a) -> None:
    """Per run, 3 frames: chosen chain red with its id, other tracks thin green, excluded thin grey."""
    import cv2
    import torch

    rows = []
    for rd in run_list(a):
        pj = rd / "protagonist.json"
        if not pj.exists():
            continue
        info = json.loads(pj.read_text())
        chain, excl = set(info.get("chain", [])), set(info.get("exclude", []))
        vid, th, _ = run_paths(rd)
        hist = torch.load(th, weights_only=False)
        cap = cv2.VideoCapture(str(vid))
        tiles = []
        for f in np.linspace(0, len(hist) - 1, 3).round().astype(int):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(f))
            ok, img = cap.read()
            if not ok:
                img = np.zeros((270, 480, 3), np.uint8)
            for d in hist[f]:
                x0, y0, x1, y1 = map(int, d["bbx_xyxy"])
                col, w = ((0, 0, 255), 6) if d["id"] in chain else ((128, 128, 128), 2) if d["id"] in excl else ((0, 255, 0), 2)
                cv2.rectangle(img, (x0, y0), (x1, y1), col, w)
                cv2.putText(img, str(d["id"]), (x0 + 5, y0 + 40), cv2.FONT_HERSHEY_SIMPLEX, 1.5, col, 3)
            tiles.append(cv2.resize(img, (480, 270)))
        cap.release()
        row = np.hstack(tiles)
        label = f"{rd.name} seed {info['seed']} {info['reason']} b{info.get('body_sim')} f{info.get('face_sim')}"
        cv2.putText(row, label, (5, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        rows.append(row)
    for i in range(0, len(rows), a.per_sheet):  # one JPEG per PER_SHEET rows: out.jpg, out-1.jpg, ...
        out = Path(a.out) if i == 0 else Path(a.out).with_stem(f"{Path(a.out).stem}-{i // a.per_sheet}")
        cv2.imwrite(str(out), np.vstack(rows[i : i + a.per_sheet]), [cv2.IMWRITE_JPEG_QUALITY, 80])
        print(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("embed")
    p.add_argument("runs", nargs="*")
    p.add_argument("--runs-file", help="text file with one run directory per line")
    p.add_argument("--threads", type=int, default=4)
    p.add_argument("--per-track", type=int, default=12)
    p.add_argument("--force", action="store_true")
    for name in ("gallery", "validate"):
        p = sub.add_parser(name)
        p.add_argument("--gt", required=True, help="verified protagonist tracks (see footage-batch-2.md)")
        p.add_argument("--out", required=True)
        p.add_argument("--runs-root", default=str(ROOT / "private/work/runs"))
        p.add_argument("--prefix", default="fr-")
    p = sub.add_parser("score")
    p.add_argument("runs", nargs="*")
    p.add_argument("--runs-file", help="text file with one run directory per line")
    p.add_argument("--gallery", required=True)
    p = sub.add_parser("sheet")
    p.add_argument("runs", nargs="*")
    p.add_argument("--runs-file", help="text file with one run directory per line")
    p.add_argument("--out", required=True)
    p.add_argument("--per-sheet", type=int, default=8)
    a = ap.parse_args()
    # embeddings, galleries, sheets and protagonist.json derive from film frames: private only
    containment.assert_outputs(a, "out")
    if a.cmd in ("embed", "score"):
        for rd in run_list(a):
            containment.assert_private(rd, "run dir (embeddings / protagonist.json)")
    {"embed": cmd_embed, "gallery": cmd_gallery, "score": cmd_score, "validate": cmd_validate,
     "sheet": cmd_sheet}[a.cmd](a)


if __name__ == "__main__":
    main()
