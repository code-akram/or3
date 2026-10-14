"""Identity shape codes from reference frames with a MICA-class regressor (encoder only).

Runs the ArcFace IResNet-100 backbone and the mapping network from a MICA-style checkpoint
on 5-point-aligned 112 px face crops, one shape code per frame (FLAME shape coefficients,
300-d), and writes the weighted coordinate-wise median over a chosen neutral set. Only the median
(what fit.py --init reads) and its frame ids and weights are written: the per-frame codes and the
per-frame ArcFace embeddings (a face-recognition template) are not persisted. Outputs must be
private (containment.py). No FLAME decode happens here: decoding needs the FLAME model (see
flame.py).

The network is defined here (same layer names as the checkpoint), so no third-party model code
is imported or executed; the checkpoint loads with torch.load(weights_only=True) and an
allowlist of plain numpy array globals only.

Inputs come from a reference directory written by refboard.py (index.json, crops, landmarks):

    python -I identity_codes.py --ckpt CKPT --ref REF_DIR --out codes.npz \
        [--ids 3,8,12 | --auto] [--weight-flat 2.0]

Run with OMP_NUM_THREADS=3.

`compare` (T7 originality check) prints ONE number and writes nothing: the cosine similarity
between ArcFace (w600k_r50, ONNX via cv2.dnn) embeddings of a render and of the reference set
(the normalised coordinate-wise median over the --ids / --auto frames), for checking that an
authored face is not the reference identity (target <= 0.25):

    python -I identity_codes.py compare --arcface ONNX --yunet ONNX --ref REF_DIR [--auto] IMG...

The render's five points come from YuNet; the reference crops use their stored landmarks.
"""

import argparse
import codecs
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import torch
from torch import nn

sys.path.insert(0, str(Path(__file__).resolve().parent))
import containment  # noqa: E402

# ArcFace 112x112 5-point template (InsightFace): image-left eye, image-right eye, nose tip,
# image-left mouth corner, image-right mouth corner.
ARCFACE_DST = np.array([[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366],
                        [41.5493, 92.3655], [70.7299, 92.2041]], np.float64)
# The same five points from the MediaPipe 478-point mesh: iris centres (subject's right = image
# left), pronasale, mouth corners.
MP_FIVE = (468, 473, 1, 61, 291)


# ----------------------------------------------------------------------------------- network
def conv3x3(i, o, stride=1):
    return nn.Conv2d(i, o, 3, stride, 1, bias=False)


class IBasicBlock(nn.Module):
    def __init__(self, inplanes, planes, stride=1, downsample=None):
        super().__init__()
        self.bn1 = nn.BatchNorm2d(inplanes, eps=1e-5)
        self.conv1 = conv3x3(inplanes, planes)
        self.bn2 = nn.BatchNorm2d(planes, eps=1e-5)
        self.prelu = nn.PReLU(planes)
        self.conv2 = conv3x3(planes, planes, stride)
        self.bn3 = nn.BatchNorm2d(planes, eps=1e-5)
        self.downsample = downsample

    def forward(self, x):
        out = self.bn3(self.conv2(self.prelu(self.bn2(self.conv1(self.bn1(x))))))
        return out + (self.downsample(x) if self.downsample is not None else x)


class IResNet(nn.Module):
    """ArcFace IResNet (layers [3, 13, 30, 3] = IResNet-100), 112x112 RGB in [-1, 1] -> 512-d."""

    def __init__(self, layers=(3, 13, 30, 3), num_features=512):
        super().__init__()
        self.inplanes = 64
        self.conv1 = nn.Conv2d(3, 64, 3, 1, 1, bias=False)
        self.bn1 = nn.BatchNorm2d(64, eps=1e-5)
        self.prelu = nn.PReLU(64)
        self.layer1 = self._layer(64, layers[0])
        self.layer2 = self._layer(128, layers[1])
        self.layer3 = self._layer(256, layers[2])
        self.layer4 = self._layer(512, layers[3])
        self.bn2 = nn.BatchNorm2d(512, eps=1e-5)
        self.dropout = nn.Dropout(0.0)
        self.fc = nn.Linear(512 * 7 * 7, num_features)
        self.features = nn.BatchNorm1d(num_features, eps=1e-5)

    def _layer(self, planes, blocks):
        down = nn.Sequential(nn.Conv2d(self.inplanes, planes, 1, 2, bias=False), nn.BatchNorm2d(planes, eps=1e-5))
        mods = [IBasicBlock(self.inplanes, planes, 2, down)]
        self.inplanes = planes
        mods += [IBasicBlock(planes, planes) for _ in range(1, blocks)]
        return nn.Sequential(*mods)

    def forward(self, x):
        x = self.prelu(self.bn1(self.conv1(x)))
        x = self.layer4(self.layer3(self.layer2(self.layer1(x))))
        x = torch.flatten(self.bn2(x), 1)
        return self.features(self.fc(self.dropout(x)))


class Mapping(nn.Module):
    """MLP from the normalised 512-d identity embedding to shape coefficients (leaky ReLU 0.2)."""

    def __init__(self, sd, prefix):
        super().__init__()
        n = 0
        while f"{prefix}network.{n}.weight" in sd:
            n += 1
        self.network = nn.ModuleList(nn.Linear(sd[f"{prefix}network.{i}.weight"].shape[1],
                                               sd[f"{prefix}network.{i}.weight"].shape[0]) for i in range(n))
        w = sd[f"{prefix}output.weight"]
        self.output = nn.Linear(w.shape[1], w.shape[0])

    def forward(self, z):
        for lin in self.network:
            z = nn.functional.leaky_relu(lin(z), 0.2)
        return self.output(z)


def load_checkpoint(path):
    from numpy._core.multiarray import _reconstruct
    allow = [(_reconstruct, "numpy.core.multiarray._reconstruct"), np.ndarray, (np.dtype, "numpy.dtype"),
             codecs.encode] + [type(np.dtype(t)) for t in ("float32", "float64", "int64", "int32", "uint8", "bool")]
    with torch.serialization.safe_globals(allow):
        return torch.load(path, map_location="cpu", weights_only=True)


class Encoder:
    def __init__(self, ckpt):
        ck = load_checkpoint(ckpt)
        self.backbone = IResNet()
        self.backbone.load_state_dict(ck["arcface"])
        sd = ck["flameModel"]
        self.mapping = Mapping(sd, "regressor.")
        self.mapping.load_state_dict({k[len("regressor."):]: v for k, v in sd.items() if k.startswith("regressor.")})
        self.backbone.eval()
        self.mapping.eval()

    @torch.no_grad()
    def __call__(self, aligned_bgr):
        """aligned_bgr: list of 112x112x3 uint8 BGR crops -> (codes N x K, embeddings N x 512)."""
        x = np.stack([cv2.cvtColor(a, cv2.COLOR_BGR2RGB) for a in aligned_bgr]).astype(np.float32)
        x = torch.from_numpy((x - 127.5) / 127.5).permute(0, 3, 1, 2).contiguous()
        emb = nn.functional.normalize(self.backbone(x))
        return self.mapping(emb).numpy(), emb.numpy()


# ----------------------------------------------------------------------------------- alignment
def similarity(src, dst):
    """Least-squares similarity (Umeyama) mapping src (N x 2) onto dst: 2x3 matrix."""
    ms, md = src.mean(0), dst.mean(0)
    s0, d0 = src - ms, dst - md
    cov = d0.T @ s0 / len(src)
    U, S, Vt = np.linalg.svd(cov)
    D = np.diag([1.0, np.sign(np.linalg.det(U @ Vt))])
    R = U @ D @ Vt
    scale = np.trace(np.diag(S) @ D) / max(s0.var(0).sum(), 1e-12)
    t = md - scale * R @ ms
    return np.c_[scale * R, t]


def five_points(lm):
    lm = np.asarray(lm)
    if len(lm) >= 478:
        return lm[list(MP_FIVE), :2].astype(np.float64)
    return lm[:5, :2].astype(np.float64)       # detector 5 points (YuNet order matches the template)


def align(img, five):
    M = similarity(five, ARCFACE_DST)
    return cv2.warpAffine(img, M, (112, 112), borderValue=0.0)


# ----------------------------------------------------------------------------------- selection
def auto_pick(frames, max_yaw, max_pitch, max_roll, max_expr, min_sharp):
    out = []
    for f in frames:
        if f["landmark_set"] != "mediapipe478":
            continue
        if abs(f["yaw"]) > max_yaw or abs(f["pitch"]) > max_pitch or abs(f.get("roll", 0)) > max_roll:
            continue
        if f["expr"] > max_expr or f["sharp"] < min_sharp:
            continue
        out.append(f["id"])
    return out


def weighted_median(X, w):
    """Coordinate-wise weighted median of rows of X."""
    order = np.argsort(X, axis=0)
    Xs = np.take_along_axis(X, order, 0)
    ws = w[order]
    cw = np.cumsum(ws, axis=0)
    half = 0.5 * w.sum()
    idx = (cw >= half).argmax(0)
    return Xs[idx, np.arange(X.shape[1])]


def compare(argv):
    """Print the ArcFace cosine between render image(s) and the reference set; write nothing."""
    ap = argparse.ArgumentParser(prog="identity_codes.py compare")
    ap.add_argument("--arcface", required=True, help="w600k_r50 ONNX")
    ap.add_argument("--yunet", required=True, help="YuNet face detector ONNX (render five points)")
    ap.add_argument("--ref", required=True, help="reference dir from refboard.py board")
    ap.add_argument("--ids", default="")
    ap.add_argument("--auto", action="store_true")
    ap.add_argument("--max-yaw", type=float, default=25.0)
    ap.add_argument("--max-pitch", type=float, default=15.0)
    ap.add_argument("--max-roll", type=float, default=20.0)
    ap.add_argument("--max-expr", type=float, default=0.25)
    ap.add_argument("--min-sharp", type=float, default=40.0)
    ap.add_argument("images", nargs="+", help="render(s) of the authored face")
    a = ap.parse_args(argv)
    cv2.setNumThreads(3)
    net = cv2.dnn.readNetFromONNX(a.arcface)

    def embed(crop):
        blob = cv2.dnn.blobFromImage(crop, 1.0 / 127.5, (112, 112), (127.5, 127.5, 127.5), swapRB=True)
        net.setInput(blob)
        e = net.forward().reshape(-1).astype(np.float64)
        return e / np.linalg.norm(e)

    ref = Path(a.ref)
    frames = json.load(open(ref / "index.json"))["frames"]
    if a.ids:
        sel = {int(x) for x in a.ids.split(",") if x.strip()}
    elif a.auto:
        sel = set(auto_pick(frames, a.max_yaw, a.max_pitch, a.max_roll, a.max_expr, a.min_sharp))
    else:
        sel = {f["id"] for f in frames}
    R = np.array([embed(align(cv2.imread(str(ref / f["crop"])), five_points(np.load(ref / f["landmarks"]))))
                  for f in frames if f["id"] in sel])
    if not len(R):
        raise SystemExit("compare: empty reference set")
    r = np.median(R, axis=0)
    r /= np.linalg.norm(r)
    out = []
    for path in a.images:
        img = cv2.imread(path)
        if img is None:
            raise SystemExit(f"compare: cannot read {path}")
        h, w = img.shape[:2]
        det = cv2.FaceDetectorYN.create(a.yunet, "", (w, h), 0.5, 0.3, 5)
        _, faces = det.detect(img)
        if faces is None or not len(faces):
            raise SystemExit(f"compare: no face found in {path}")
        f = faces[np.argmax(faces[:, -1])]
        out.append(embed(align(img, f[4:14].reshape(5, 2).astype(np.float64))))
    e = np.mean(out, axis=0)
    e /= np.linalg.norm(e)
    print(f"{float(e @ r):.3f}")
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "compare":
        return compare(argv[1:])
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ckpt", required=True, help="MICA-style checkpoint (arcface + flameModel.regressor)")
    ap.add_argument("--ref", required=True, help="reference dir from refboard.py board")
    ap.add_argument("--out", required=True, help="output .npz")
    ap.add_argument("--ids", default="", help="comma-separated frame ids for the median set")
    ap.add_argument("--auto", action="store_true", help="pick the median set by pose / expression / sharpness")
    ap.add_argument("--max-yaw", type=float, default=25.0)
    ap.add_argument("--max-pitch", type=float, default=15.0)
    ap.add_argument("--max-roll", type=float, default=20.0)
    ap.add_argument("--max-expr", type=float, default=0.25)
    ap.add_argument("--min-sharp", type=float, default=40.0)
    ap.add_argument("--weight-flat", type=float, default=2.0, help="weight = 1 + this * light flatness (0..1)")
    ap.add_argument("--save-aligned", default="", help="directory for the 112 px aligned crops (inspection)")
    a = ap.parse_args(argv)
    containment.assert_private(a.out, "--out")
    if a.save_aligned:
        containment.assert_private(a.save_aligned, "--save-aligned")
    torch.set_num_threads(3)

    ref = Path(a.ref)
    frames = json.load(open(ref / "index.json"))["frames"]
    enc = Encoder(a.ckpt)
    crops, ids = [], []
    for f in frames:
        img = cv2.imread(str(ref / f["crop"]))
        lm = np.load(ref / f["landmarks"])
        crops.append(align(img, five_points(lm)))
        ids.append(f["id"])
    if a.save_aligned:
        d = Path(a.save_aligned)
        d.mkdir(parents=True, exist_ok=True)
        for i, c in zip(ids, crops):
            cv2.imwrite(str(d / f"{i:03d}.jpg"), c)
    codes = np.concatenate([enc(crops[k:k + 8])[0] for k in range(0, len(crops), 8)])

    by_id = {f["id"]: f for f in frames}
    if a.ids:
        sel = [int(x) for x in a.ids.split(",") if x.strip()]
    elif a.auto:
        sel = auto_pick(frames, a.max_yaw, a.max_pitch, a.max_roll, a.max_expr, a.min_sharp)
    else:
        sel = []
    rows = [ids.index(i) for i in sel]
    w = np.array([1.0 + a.weight_flat * float(np.clip(by_id[i]["flat"], 0, 1)) for i in sel])
    median = weighted_median(codes[rows], w) if rows else np.zeros(codes.shape[1], np.float32)
    np.savez(a.out, median_ids=np.array(sel, int), median_weights=w, median=median)
    if rows:
        d = np.linalg.norm(codes[rows] - median, axis=1)
        spread = np.linalg.norm(codes[rows] - codes[rows].mean(0), axis=1).mean()
        print(f"[codes] {len(ids)} frames encoded; median over {len(sel)} (weights {w.min():.2f}-{w.max():.2f}); "
              f"|median| {np.linalg.norm(median):.3f}; mean distance to median {d.mean():.3f}; spread {spread:.3f}")
        for i, dd, ww in zip(sel, d, w):
            f = by_id[i]
            print(f"  {i:3d} yaw {f['yaw']:+5.1f} pitch {f['pitch']:+5.1f} flat {f['flat']:.2f} "
                  f"w {ww:.2f} |code-median| {dd:.3f}")
    else:
        print(f"[codes] {len(ids)} frames encoded; no median set given (--ids or --auto)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
