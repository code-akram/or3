"""Reference board from video: candidate face frames, landmarks, head pose, curation sheets.

Generic: it works for any set of videos of one subject. Every input and output is a path
on the command line; nothing subject-specific lives in this file. Run it with ``python -I``
(the videos are untrusted data).

Pipeline:

1. ``scan``: decode each video at ``--fps`` with ffmpeg, find faces with OpenCV YuNet,
   run the MediaPipe Face Landmarker on a square crop around each face, and record
   one JSON line per face. The record holds the 478 landmarks (frame pixels and z),
   the 52 blendshapes, the head pose (yaw, pitch, roll in degrees, from the landmarker's
   facial transformation matrix), the face size, a blur-normalised sharpness, the
   luma, a light-flatness score, and an expression score. A 512 px crop is saved
   per face.
2. ``sheet``: contact sheets of the best candidates per yaw bin, numbered, for
   identity and occlusion checks by eye.
3. ``board``: the hand-picked faces (a JSON list of candidate keys) become the
   board. It writes the crops, the landmarks in crop pixels, ``index.json`` (clip
   id and timestamp per frame) and ``board.jpg``.
4. ``ratios``: IPD-normalised landmark ratios over the near-frontal board frames
   (median and spread), plus a per-frame focal-length estimate from a perspective
   fit of the canonical face model.

    python -I refboard.py scan --landmarker face_landmarker.task --yunet yunet.onnx \\
        --out CAND_DIR --fps 2 VIDEO[=CLIP_ID] ...
    python -I refboard.py sheet --cands CAND_DIR --out SHEET_DIR [--per-bin 24]
    python -I refboard.py board --cands CAND_DIR --pick picks.json --out REF_DIR
    python -I refboard.py ratios --ref REF_DIR --canonical canonical_face_model.obj [--max-yaw 10]

``ratios`` also runs on renders: ``python -I refboard.py measure --landmarker ... IMG ...``
writes the same ratio table for any images, so reference and render are measured the same way.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import containment  # noqa: E402

# MediaPipe Face Mesh indices used below (478-point model with irises).
IRIS_R, IRIS_L = 468, 473                 # iris centres (subject's right, left)
EYE_R = (33, 133, 159, 145)               # outer, inner corner, upper lid, lower lid (subject's right)
EYE_L = (263, 362, 386, 374)
BROW_R_LOW, BROW_L_LOW = 52, 282          # lower brow edge above the pupil
ZYGO = (234, 454)                         # face contour at the cheekbones
GONION = (172, 397)                       # face contour at the jaw angle
MOUTH = (61, 291)                         # mouth corners
NASION, SUBNASALE, MENTON, PRONASALE = 168, 2, 152, 1
ALAR = (129, 358)
CHEEK_PATCH = (205, 425)                  # mid-cheek points (light flatness)
# Rigid landmarks for the perspective fit: eyes, brows, nose, not the mouth or jaw.
RIGID = sorted({33, 133, 159, 145, 263, 362, 386, 374, 70, 63, 105, 66, 107, 300, 293, 334, 296, 336,
                168, 6, 197, 195, 5, 4, 1, 2, 98, 327, 129, 358, 49, 279, 234, 454, 127, 356})
# Expression blendshapes that count against "neutral".
EXPR = ("jawOpen", "mouthSmileLeft", "mouthSmileRight", "eyeBlinkLeft", "eyeBlinkRight", "browInnerUp",
        "mouthPucker", "mouthFunnel", "cheekSquintLeft", "cheekSquintRight", "mouthStretchLeft",
        "mouthStretchRight", "eyeWideLeft", "eyeWideRight", "mouthRollLower", "mouthRollUpper")
CROP = 512


# ------------------------------------------------------------------------------------- io
def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height", "-of", "csv=p=0:s=x", str(path)],
                         capture_output=True, text=True, check=True).stdout.strip()
    w, h = out.split("x")[:2]
    return int(w), int(h)


def frames(path, fps, threads=3):
    """Yield (t, rgb) at ``fps`` via an ffmpeg pipe."""
    w, h = probe(path)
    cmd = ["ffmpeg", "-v", "error", "-threads", str(threads), "-i", str(path), "-vf", f"fps={fps}",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    n, size = 0, w * h * 3
    try:
        while True:
            buf = p.stdout.read(size)
            if len(buf) < size:
                break
            yield n / fps, np.frombuffer(buf, np.uint8).reshape(h, w, 3)
            n += 1
    finally:
        p.stdout.close()
        p.wait()


# ----------------------------------------------------------------------------- face models
class Landmarker:
    def __init__(self, model):
        import mediapipe as mp
        from mediapipe.tasks.python import vision
        from mediapipe.tasks.python.core.base_options import BaseOptions
        self.mp = mp
        opts = vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model)), running_mode=vision.RunningMode.IMAGE,
            num_faces=1, output_face_blendshapes=True, output_facial_transformation_matrixes=True,
            min_face_detection_confidence=0.4, min_face_presence_confidence=0.4)
        self.lm = vision.FaceLandmarker.create_from_options(opts)

    def __call__(self, rgb):
        r = self.lm.detect(self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)))
        if not r.face_landmarks:
            return None
        h, w = rgb.shape[:2]
        pts = np.array([(p.x * w, p.y * h, p.z * w) for p in r.face_landmarks[0]], np.float32)
        bs = {c.category_name: float(c.score) for c in r.face_blendshapes[0]} if r.face_blendshapes else {}
        M = np.array(r.facial_transformation_matrixes[0], np.float64) if r.facial_transformation_matrixes else None
        return pts, bs, M


def pose_from_matrix(M):
    """Yaw, pitch, roll (degrees) of the landmarker's canonical-face-to-camera rotation.
    Yaw > 0: the face turns toward image left (the subject's right side faces the camera)."""
    R = M[:3, :3] / np.linalg.norm(M[:3, :3], axis=0)
    yaw = math.degrees(math.asin(-np.clip(R[2, 0], -1, 1)))
    pitch = math.degrees(math.atan2(R[2, 1], R[2, 2]))
    roll = math.degrees(math.atan2(R[1, 0], R[0, 0]))
    return yaw, pitch, roll


def sharpness(gray, pts):
    """Laplacian variance on the inner face (eyes to mouth), scaled to a 64 px IPD-equivalent
    face height, so it compares across face sizes."""
    x0, y0 = pts[[33, 263, 61, 291, 168], :2].min(0)
    x1, y1 = pts[[33, 263, 61, 291, 168], :2].max(0)
    h = max(y1 - y0, 1.0)
    pad = 0.15 * h
    x0, y0, x1, y1 = int(max(x0 - pad, 0)), int(max(y0 - pad, 0)), int(x1 + pad), int(y1 + pad)
    roi = gray[y0:y1, x0:x1]
    if roi.size < 100:
        return 0.0
    s = 96.0 / max(roi.shape[0], 1)
    roi = cv2.resize(roi, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    return float(cv2.Laplacian(roi.astype(np.float32), cv2.CV_32F).var())


def light_flatness(gray, pts, face_h):
    r = max(int(0.06 * face_h), 2)
    vals = []
    for i in CHEEK_PATCH:
        x, y = int(pts[i, 0]), int(pts[i, 1])
        patch = gray[max(y - r, 0):y + r, max(x - r, 0):x + r]
        vals.append(float(patch.mean()) if patch.size else 0.0)
    a, b = vals
    return 1.0 - abs(a - b) / max(a + b, 1e-3), (a + b) / 2


def square_crop(rgb, cx, cy, side, out):
    """Crop a square (padding with black past the frame) and resize to ``out``; return the
    crop and the affine (scale, x0, y0) mapping frame pixels to crop pixels."""
    x0, y0 = cx - side / 2, cy - side / 2
    s = out / side
    M = np.array([[s, 0, -x0 * s], [0, s, -y0 * s]], np.float32)
    crop = cv2.warpAffine(rgb, M, (out, out), flags=cv2.INTER_AREA, borderMode=cv2.BORDER_CONSTANT)
    return crop, (float(s), float(x0), float(y0))


# ------------------------------------------------------------------------------------ scan
def cmd_scan(a):
    out = Path(a.out)
    (out / "crops").mkdir(parents=True, exist_ok=True)
    lm = Landmarker(a.landmarker)
    det = cv2.FaceDetectorYN.create(str(a.yunet), "", (320, 320), 0.6, 0.3, 50) if a.yunet else None
    cands = open(out / "cands.jsonl", "a")
    for spec in a.videos:
        path, _, clip = spec.partition("=")
        clip = clip or Path(path).parent.name
        n_face = n_frame = 0
        for t, rgb in frames(path, a.fps, a.threads):
            n_frame += 1
            h, w = rgb.shape[:2]
            boxes = []
            if det is not None:
                s = min(1.0, a.det_width / w)
                small = cv2.resize(rgb, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else rgb
                det.setInputSize((small.shape[1], small.shape[0]))
                _, faces = det.detect(cv2.cvtColor(small, cv2.COLOR_RGB2BGR))
                for f in (faces if faces is not None else []):
                    bx, by, bw, bh = (f[:4] / s).tolist()
                    if max(bw, bh) >= a.min_face:
                        five = (f[4:14] / s).reshape(5, 2)          # eyes, nose, mouth corners
                        boxes.append((bx + bw / 2, by + bh / 2, max(bw, bh), float(f[14]), five))
            else:
                boxes.append((w / 2, h / 2, float(min(w, h)), 1.0, None))
            for k, (cx, cy, size, score, five) in enumerate(boxes):
                side = size * 2.2 if det is not None else size
                crop, (s, x0, y0) = square_crop(rgb, cx, cy, side, CROP)
                res = lm(crop)
                if res is None:
                    # the landmarker fails past ~50 deg of yaw; keep the detector's face as a
                    # profile candidate with a rough yaw from its five points
                    if a.keep_profiles and five is not None:
                        save_profile(out, cands, rgb, clip, t, k, cx, cy, size, score, five)
                    continue
                pts, bs, M = res
                fpts = pts.copy()                                  # crop -> frame pixels
                fpts[:, 0] = pts[:, 0] / s + x0
                fpts[:, 1] = pts[:, 1] / s + y0
                fpts[:, 2] = pts[:, 2] / s
                gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
                face_h = float(np.linalg.norm(fpts[10, :2] - fpts[MENTON, :2]))
                ipd = float(np.linalg.norm(fpts[IRIS_R, :2] - fpts[IRIS_L, :2]))
                yaw, pitch, roll = pose_from_matrix(M) if M is not None else (0.0, 0.0, 0.0)
                flat, luma = light_flatness(gray, fpts, face_h)
                expr = max((bs.get(n, 0.0) for n in EXPR), default=0.0)
                key = f"{clip}@{t:08.2f}#{k}"
                # the saved crop: centred on the landmarks, 1.7 x the face height
                lx0, ly0 = fpts[:, :2].min(0)
                lx1, ly1 = fpts[:, :2].max(0)
                c2, (s2, x2, y2) = square_crop(rgb, (lx0 + lx1) / 2, (ly0 + ly1) / 2,
                                               1.7 * max(lx1 - lx0, ly1 - ly0), CROP)
                name = key.replace("@", "_").replace("#", "_") + ".jpg"
                cv2.imwrite(str(out / "crops" / name), cv2.cvtColor(c2, cv2.COLOR_RGB2BGR),
                            [cv2.IMWRITE_JPEG_QUALITY, 92])
                rec = {"key": key, "clip": clip, "t": round(t, 3), "frame_wh": [w, h], "det": round(score, 3),
                       "yaw": round(yaw, 1), "pitch": round(pitch, 1), "roll": round(roll, 1),
                       "face_h": round(face_h, 1), "ipd": round(ipd, 1), "sharp": round(sharpness(gray, fpts), 1),
                       "flat": round(flat, 3), "luma": round(luma, 1), "expr": round(expr, 3),
                       "blend": {n: round(v, 3) for n, v in bs.items() if v > 0.05},
                       "crop": name, "crop_affine": [float(s2), float(x2), float(y2)],
                       "lm": np.round(fpts, 2).tolist(), "M": np.round(M, 5).tolist() if M is not None else None}
                cands.write(json.dumps(rec) + "\n")
                n_face += 1
        cands.flush()
        print(f"[scan] {clip}: {n_frame} frames, {n_face} faces", flush=True)
    cands.close()


def save_profile(out, cands, rgb, clip, t, k, cx, cy, size, score, five):
    eyes_mid = five[:2].mean(0)
    eye_d = float(np.linalg.norm(five[0] - five[1]))
    # nose offset from the eye midpoint over the box size: ~0 frontal, ~0.3 at profile
    off = float(five[2, 0] - eyes_mid[0]) / size
    yaw = float(np.degrees(np.arcsin(np.clip(off / 0.32, -1, 1))))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    x0, y0 = int(max(cx - size / 2, 0)), int(max(cy - size / 2, 0))
    roi = gray[y0:int(cy + size / 2), x0:int(cx + size / 2)]
    sharp = 0.0
    if roi.size > 100:
        sc = 96.0 / max(roi.shape[0], 1)
        small = cv2.resize(roi, None, fx=sc, fy=sc, interpolation=cv2.INTER_AREA).astype(np.float32)
        sharp = float(cv2.Laplacian(small, cv2.CV_32F).var())
    key = f"{clip}@{t:08.2f}#{k}"
    c2, aff = square_crop(rgb, cx, cy, 1.6 * size, CROP)
    name = key.replace("@", "_").replace("#", "_") + ".jpg"
    cv2.imwrite(str(out / "crops" / name), cv2.cvtColor(c2, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 92])
    rec = {"key": key, "clip": clip, "t": round(t, 3), "frame_wh": [rgb.shape[1], rgb.shape[0]],
           "det": round(score, 3), "yaw": round(yaw, 1), "pitch": 0.0, "roll": 0.0, "face_h": round(size, 1),
           "ipd": round(eye_d, 1), "sharp": round(sharp, 1), "flat": 0.5,
           "luma": round(float(roi.mean()), 1) if roi.size else 0.0, "expr": 0.0, "blend": {}, "crop": name,
           "crop_affine": list(aff), "lm": None, "M": None, "src": "detector", "five": np.round(five, 1).tolist()}
    cands.write(json.dumps(rec) + "\n")


def load(cdir):
    with open(Path(cdir) / "cands.jsonl") as f:
        return [json.loads(line) for line in f if line.strip()]


def quality(r):
    """Ranking score: sharp, large, neutral, evenly lit."""
    return (min(r["sharp"], 400.0) / 400.0) * min(r["face_h"] / 500.0, 1.0) ** 0.5 \
        * (1.0 - min(r["expr"], 0.6)) * (0.6 + 0.4 * r["flat"])


# ----------------------------------------------------------------------------------- sheets
def contact(items, label, out, cols=8, cell=192):
    rows = max(1, math.ceil(len(items) / cols))
    sheet = np.full((rows * (cell + 18), cols * cell, 3), 24, np.uint8)
    for i, (img_path, text) in enumerate(items):
        im = cv2.imread(str(img_path))
        if im is None:
            continue
        im = cv2.resize(im, (cell, cell), interpolation=cv2.INTER_AREA)
        r, c = divmod(i, cols)
        y, x = r * (cell + 18), c * cell
        sheet[y:y + cell, x:x + cell] = im
        cv2.putText(sheet, text, (x + 3, y + cell + 13), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (230, 230, 230), 1,
                    cv2.LINE_AA)
    cv2.putText(sheet, label, (4, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1, cv2.LINE_AA)
    cv2.imwrite(str(out), sheet, [cv2.IMWRITE_JPEG_QUALITY, 88])


def cmd_sheet(a):
    recs = [r for r in load(a.cands) if r["sharp"] >= a.min_sharp and r["face_h"] >= a.min_face_h
            and r["expr"] <= a.max_expr and (r.get("src") == "detector") == a.profiles]
    if a.ident:
        sims = json.load(open(a.ident))
        recs = [r for r in recs if sims.get(r["key"], -1) >= a.min_sim]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    edges = list(range(-90, 91, a.bin))
    numbered = {}
    for lo, hi in zip(edges[:-1], edges[1:]):
        b = [r for r in recs if lo <= r["yaw"] < hi]
        # one face per clip second, the best of it
        best = {}
        for r in b:
            k = (r["clip"], int(r["t"]))
            if k not in best or quality(r) > quality(best[k]):
                best[k] = r
        b = sorted(best.values(), key=quality, reverse=True)[:a.per_bin]
        if not b:
            continue
        items = []
        for r in b:
            n = len(numbered)
            numbered[n] = r["key"]
            items.append((Path(a.cands) / "crops" / r["crop"], f"{n} y{r['yaw']:.0f} p{r['pitch']:.0f} e{r['expr']:.2f}"))
        contact(items, f"yaw {lo}..{hi}  ({len(b)})", out / f"sheet_yaw{lo:+04d}.jpg")
    with open(out / "numbered.json", "w") as f:
        json.dump(numbered, f, indent=0)
    print(f"[sheet] {len(numbered)} candidates in {out}")


# --------------------------------------------------------------------------------- identity
def cmd_ident(a):
    """Similarity of every candidate to a few hand-verified seed faces (OpenCV SFace on
    YuNet-aligned crops). Only a pre-sort for curation by eye: the board is still checked
    face by face, and nothing downstream optimises against this score."""
    recs = load(a.cands)
    det = cv2.FaceDetectorYN.create(str(a.yunet), "", (CROP, CROP), 0.5, 0.3, 5)
    rec_net = cv2.FaceRecognizerSF.create(str(a.sface), "")
    feats = {}
    for r in recs:
        im = cv2.imread(str(Path(a.cands) / "crops" / r["crop"]))
        _, faces = det.detect(im)
        if faces is None or not len(faces):
            continue
        f = min(faces, key=lambda f: np.hypot(f[0] + f[2] / 2 - CROP / 2, f[1] + f[3] / 2 - CROP / 2))
        feat = rec_net.feature(rec_net.alignCrop(im, f)).ravel()
        feats[r["key"]] = feat / np.linalg.norm(feat)
    seed_keys = json.load(open(a.seed))
    seeds = np.array([feats[k] for k in seed_keys if k in feats])
    sims = {k: round(float(np.sort(seeds @ v)[-3:].mean()), 4) for k, v in feats.items()}
    out = Path(a.out) if a.out else Path(a.cands) / "ident.json"
    with open(out, "w") as f:
        json.dump(sims, f)
    vals = np.array(list(sims.values()))
    print(f"[ident] {len(sims)} faces, seeds {len(seeds)}; sim pct 10/50/90: {np.percentile(vals, [10, 50, 90]).round(3)}")


# ------------------------------------------------------------------------------------ board
def cmd_board(a):
    recs = {r["key"]: r for r in load(a.cands)}
    pick = json.load(open(a.pick))
    keys = pick["keys"] if isinstance(pick, dict) else pick
    # by-eye yaw for frames whose estimate is poor (detector-only profiles; the landmarker reads low past ~30 deg)
    by_eye = pick.get("yaw", {}) if isinstance(pick, dict) else {}
    out = Path(a.out)
    (out / "crops").mkdir(parents=True, exist_ok=True)
    for old in (out / "crops").glob("*"):        # a re-run with fewer picks must not leave stale crops
        old.unlink()
    index, items = [], []
    for i, key in enumerate(sorted(keys, key=lambda k: by_eye.get(k, recs[k]["yaw"]))):
        r = dict(recs[key])
        r["yaw_src"] = "by-eye" if key in by_eye else ("landmarker" if r["lm"] is not None else "detector")
        r["yaw"] = float(by_eye.get(key, r["yaw"]))
        src = Path(a.cands) / "crops" / r["crop"]
        name = f"{i:03d}.jpg"
        im = cv2.imread(str(src))
        cv2.imwrite(str(out / "crops" / name), im, [cv2.IMWRITE_JPEG_QUALITY, 95])
        s, x0, y0 = r["crop_affine"]
        if r["lm"] is not None:
            lm = np.array(r["lm"], np.float32)
            lm_crop = np.c_[(lm[:, 0] - x0) * s, (lm[:, 1] - y0) * s, lm[:, 2] * s]
        else:                                    # profile: the detector's five points only
            lm = np.array(r["five"], np.float32)
            lm_crop = np.c_[(lm[:, 0] - x0) * s, (lm[:, 1] - y0) * s, np.zeros(len(lm))]
        np.save(out / "crops" / f"{i:03d}_lm.npy", lm_crop.astype(np.float32))
        index.append({"id": i, "crop": f"crops/{name}", "landmarks": f"crops/{i:03d}_lm.npy",
                      "landmark_set": "mediapipe478" if r["lm"] is not None else "detector5", "clip": r["clip"],
                      "t": r["t"], "frame_wh": r["frame_wh"], "yaw": r["yaw"], "yaw_src": r["yaw_src"],
                      "pitch": r["pitch"],
                      "roll": r["roll"], "face_h_px": r["face_h"], "ipd_px": r["ipd"], "sharp": r["sharp"],
                      "flat": r["flat"], "expr": r["expr"], "frame_landmarks_affine": r["crop_affine"],
                      "note": (pick.get("notes", {}) if isinstance(pick, dict) else {}).get(key, "")})
        tag = {"by-eye": " (eye)", "detector": " (det)"}.get(r["yaw_src"], "")
        items.append((out / "crops" / name, f"{i} y{r['yaw']:.0f} p{r['pitch']:.0f}{tag}"))
    with open(out / "index.json", "w") as f:
        json.dump({"frames": index, "landmark_model": "MediaPipe Face Landmarker (478 points, crop pixels, z in "
                   "pixel units)"}, f, indent=1)
    contact(items, f"reference board, {len(items)} frames, sorted by yaw", out / "board.jpg", cols=10, cell=192)
    print(f"[board] {len(items)} frames -> {out}")


# ----------------------------------------------------------------------------------- ratios
RATIO_DEFS = {
    # name: (description, function of 2D landmarks (frame pixels) / IPD)
    "bizygomatic": "cheek contour width at the cheekbones (234-454)",
    "bigonial": "jaw contour width at the jaw angle (172-397); beard-affected",
    "mouth_width": "mouth corners (61-291)",
    "nose_length": "nasion to subnasale (168-2)",
    "alar_width": "alar base width (129-358)",
    "brow_to_pupil": "pupil to the lower brow edge, vertical, mean of both sides",
    "palpebral_hw": "palpebral fissure height / width, mean of both eyes",
    "lower_face": "subnasale-to-menton / nasion-to-menton; menton is beard-affected",
}


def ratios_2d(lm):
    p = lm[:, :2].astype(np.float64)

    def d(i, j):
        return float(np.linalg.norm(p[i] - p[j]))
    ipd = d(IRIS_R, IRIS_L)
    # face vertical axis: nasion -> menton direction (roll-invariant vertical distances)
    v = p[MENTON] - p[NASION]
    v /= np.linalg.norm(v)

    def vert(i, j):
        return abs(float(np.dot(p[i] - p[j], v)))
    pal = []
    for o, i_, u, l in (EYE_R, EYE_L):
        pal.append(d(u, l) / max(d(o, i_), 1e-6))
    return {
        "bizygomatic": d(*ZYGO) / ipd,
        "bigonial": d(*GONION) / ipd,
        "mouth_width": d(*MOUTH) / ipd,
        "nose_length": d(NASION, SUBNASALE) / ipd,
        "alar_width": d(*ALAR) / ipd,
        "brow_to_pupil": 0.5 * (vert(IRIS_R, BROW_R_LOW) + vert(IRIS_L, BROW_L_LOW)) / ipd,
        "palpebral_hw": float(np.mean(pal)),
        "lower_face": d(SUBNASALE, MENTON) / max(d(NASION, MENTON), 1e-6),
    }


def read_obj_vertices(path):
    vs = []
    with open(path) as f:
        for line in f:
            if line.startswith("v "):
                vs.append([float(x) for x in line.split()[1:4]])
    return np.array(vs, np.float64)


# Contour points (234, 454, 127, 356) are silhouette, not surface points: keep them out of the camera fit.
CAM_POINTS = [i for i in RIGID if i not in (234, 454, 127, 356)]


def focal_estimate(lm2d, wh, canon, tol=0.05):
    """Perspective of one frame from the canonical face (cm units) fitted to the rigid landmarks.

    Returns a dict: f35_mm (horizontal 35 mm equivalent, 36 mm across the frame width), f_px,
    dist_m (camera to face, assuming an average-sized face), rms_px, and the band of f35 whose
    reprojection error is within tol (relative) + 0.1 px of the best. The perspective cue is the
    nose-to-cheek depth, so small faces give a wide band: 'determined' is False when the band
    spans more than 2x. What the render must match is dist_m (with any focal and a crop), not f35."""
    w, h = wh
    obj = canon[CAM_POINTS]
    img = lm2d[CAM_POINTS, :2].astype(np.float64)
    fits = []
    for feq in np.geomspace(10, 600, 72):
        f = feq / 36.0 * w
        K = np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1]], np.float64)
        ok, rv, tv = cv2.solvePnP(obj, img, K, None, flags=cv2.SOLVEPNP_ITERATIVE)
        if not ok:
            continue
        proj, _ = cv2.projectPoints(obj, rv, tv, K, None)
        err = float(np.sqrt(((proj[:, 0] - img) ** 2).sum(1).mean()))
        fits.append((float(feq), err, float(tv[2][0]) / 100.0, f))
    if not fits:
        return None
    best = min(fits, key=lambda t: t[1])
    ok = [t for t in fits if t[1] <= best[1] * (1 + tol) + 0.1]
    lo, hi = min(t[0] for t in ok), max(t[0] for t in ok)
    dlo, dhi = min(t[2] for t in ok), max(t[2] for t in ok)
    return {"f35_mm": round(best[0], 1), "f_px": round(best[3], 1), "dist_m": round(best[2], 2),
            "rms_px": round(best[1], 2), "f35_band": [round(lo, 1), round(hi, 1)],
            "dist_band_m": [round(dlo, 2), round(dhi, 2)], "determined": bool(hi / lo <= 2.0),
            "at_bound": bool(best[0] in (fits[0][0], fits[-1][0]))}


def table(rows, keys):
    out = {}
    for k in keys:
        vals = np.array([r[k] for r in rows])
        out[k] = {"median": round(float(np.median(vals)), 4), "iqr": [round(float(np.percentile(vals, 25)), 4),
                  round(float(np.percentile(vals, 75)), 4)], "n": len(vals), "def": RATIO_DEFS[k]}
    return out


def cmd_ratios(a):
    ref = Path(a.ref)
    idx = json.load(open(ref / "index.json"))["frames"]
    canon = read_obj_vertices(a.canonical) if a.canonical else None
    rows, cams = [], []
    for fr in idx:
        lm = np.load(ref / fr["landmarks"])
        if len(lm) < 468:                        # profile frame: detector points only
            continue
        s, x0, y0 = fr["frame_landmarks_affine"]
        flm = np.c_[lm[:, 0] / s + x0, lm[:, 1] / s + y0]
        if canon is not None:
            est = focal_estimate(flm, fr["frame_wh"], canon)
            if est:
                est.update({"id": fr["id"], "yaw": fr["yaw"], "frame_wh": fr["frame_wh"]})
                cams.append(est)
        if abs(fr["yaw"]) <= a.max_yaw and abs(fr["pitch"]) <= a.max_pitch:
            r = ratios_2d(flm)
            r["id"] = fr["id"]
            rows.append(r)
    res = {"frontal_frames": [r["id"] for r in rows], "ratios": table(rows, list(RATIO_DEFS)) if rows else {},
           "per_frame": [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()} for r in rows],
           "camera": cams}
    out = Path(a.out) if a.out else ref / "ratios.json"
    with open(out, "w") as f:
        json.dump(res, f, indent=1)
    for k, v in res["ratios"].items():
        print(f"{k:14s} {v['median']:.3f}  iqr {v['iqr'][0]:.3f}-{v['iqr'][1]:.3f}  n {v['n']}")
    det = [c for c in cams if c["determined"]]
    print(f"camera: {len(det)} of {len(cams)} frames determined (f35 band within 2x)")
    if det:
        ds = np.array([c["dist_m"] for c in det])
        print(f"  subject distance (avg-size face): median {np.median(ds):.2f} m, range {ds.min():.2f}-{ds.max():.2f}")


def detector_points(det, bgr):
    """YuNet's five points (eyes, nose tip, mouth corners) of the largest face, as (5, 3), or None."""
    det.setInputSize((bgr.shape[1], bgr.shape[0]))
    _, faces = det.detect(bgr)
    if faces is None or not len(faces):
        return None
    f = max(faces, key=lambda f: f[2] * f[3])
    return np.c_[f[4:14].reshape(5, 2), np.zeros(5)].astype(np.float32)


def cmd_measure(a):
    """The same ratios for arbitrary images (renders): one landmarker pass per image. With
    --yunet, an image the landmarker misses (a near-profile) still gets the detector's five
    points saved for alignment, without ratios."""
    lm = Landmarker(a.landmarker)
    det = cv2.FaceDetectorYN.create(str(a.yunet), "", (320, 320), 0.5, 0.3, 5) if a.yunet else None
    rows = []
    for p in a.images:
        bgr = cv2.imread(p)
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        res = lm(rgb)
        if res is None:
            five = detector_points(det, bgr) if det is not None else None
            if five is not None and a.out_dir:
                np.save(Path(a.out_dir) / (Path(p).stem + "_lm.npy"), five)
            print(f"[measure] no landmarker face: {p}" + (" (detector points saved)" if five is not None else ""),
                  file=sys.stderr)
            continue
        pts, _bs, M = res
        r = ratios_2d(pts)
        yaw, pitch, _roll = pose_from_matrix(M) if M is not None else (0, 0, 0)
        r.update({"image": os.path.basename(p), "yaw": round(yaw, 1), "pitch": round(pitch, 1)})
        rows.append(r)
        np.save(Path(a.out_dir) / (Path(p).stem + "_lm.npy"), pts) if a.out_dir else None
    res = {"ratios": table(rows, list(RATIO_DEFS)) if rows else {}, "per_image": rows}
    if a.out:
        with open(a.out, "w") as f:
            json.dump(res, f, indent=1)
    for k, v in res["ratios"].items():
        print(f"{k:14s} {v['median']:.3f}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="refboard.py", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("--landmarker", required=True)
    s.add_argument("--yunet", default="")
    s.add_argument("--out", required=True)
    s.add_argument("--fps", type=float, default=2.0)
    s.add_argument("--min-face", type=float, default=140.0, help="min YuNet box size, frame px")
    s.add_argument("--det-width", type=int, default=960, help="detector input width")
    s.add_argument("--threads", type=int, default=3)
    s.add_argument("--keep-profiles", action="store_true", help="keep detector-only faces (landmarker failed)")
    s.add_argument("videos", nargs="+", help="VIDEO or VIDEO=CLIP_ID")
    s = sub.add_parser("sheet")
    s.add_argument("--cands", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--bin", type=int, default=15)
    s.add_argument("--per-bin", type=int, default=32)
    s.add_argument("--min-sharp", type=float, default=40.0)
    s.add_argument("--min-face-h", type=float, default=200.0)
    s.add_argument("--max-expr", type=float, default=0.45)
    s.add_argument("--ident", default="", help="ident.json from the ident step")
    s.add_argument("--profiles", action="store_true", help="sheet the detector-only (profile) faces instead")
    s.add_argument("--min-sim", type=float, default=0.35)
    s = sub.add_parser("ident")
    s.add_argument("--cands", required=True)
    s.add_argument("--yunet", required=True)
    s.add_argument("--sface", required=True)
    s.add_argument("--seed", required=True, help="JSON list of hand-verified candidate keys")
    s.add_argument("--out", default="")
    s = sub.add_parser("board")
    s.add_argument("--cands", required=True)
    s.add_argument("--pick", required=True, help='JSON: ["key", ...] or {"keys": [...], "notes": {key: text}, '
                   '"yaw": {key: degrees by eye}}')
    s.add_argument("--out", required=True)
    s = sub.add_parser("ratios")
    s.add_argument("--ref", required=True)
    s.add_argument("--canonical", default="")
    s.add_argument("--max-yaw", type=float, default=10.0)
    s.add_argument("--max-pitch", type=float, default=12.0)
    s.add_argument("--out", default="")
    s = sub.add_parser("measure")
    s.add_argument("--landmarker", required=True)
    s.add_argument("--yunet", default="", help="YuNet model: five-point fallback when the landmarker misses")
    s.add_argument("--out", default="")
    s.add_argument("--out-dir", default="")
    s.add_argument("images", nargs="+")
    a = ap.parse_args(argv)
    # every output is likeness data; ident and ratios default to a file next to their input
    containment.assert_outputs(a, "out", "out_dir")
    if a.cmd == "ident" and not a.out:
        containment.assert_private(Path(a.cands) / "ident.json", "ident output")
    if a.cmd == "ratios" and not a.out:
        containment.assert_private(Path(a.ref) / "ratios.json", "ratios output")
    os.environ.setdefault("OMP_NUM_THREADS", "3")
    cv2.setNumThreads(3)
    {"scan": cmd_scan, "sheet": cmd_sheet, "ident": cmd_ident, "board": cmd_board, "ratios": cmd_ratios,
     "measure": cmd_measure}[a.cmd](a)


if __name__ == "__main__":
    main()
