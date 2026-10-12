"""Micro-benchmark of the two ViT-H stages (ViTPose-H, HMR2 ViT-H) on CPU backends.

Times one forward pass per frame (no ViTPose flip-test, so every backend does the same work) on
real crops from a finished bench run, for: torch fp32, torch bf16 autocast, and (if installed)
OpenVINO f32 / bf16. Reports s/frame and the deviation from torch fp32 (heatmap argmax shift in
pixels for ViTPose; cosine similarity for HMR2 features).

    OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 python -I vit_backends.py RUN_DIR [--frames 64] [--openvino]
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch


def timed(fn, x, batch):
    outs = []
    t = time.perf_counter()
    for i in range(0, len(x), batch):
        outs.append(fn(x[i : i + batch]))
    return time.perf_counter() - t, torch.cat(outs)


def argmax_xy(hm: torch.Tensor) -> torch.Tensor:
    B, J, H, W = hm.shape
    idx = hm.reshape(B, J, -1).argmax(-1)
    return torch.stack([idx % W, idx // W], -1).float()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--frames", type=int, default=64)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--openvino", action="store_true")
    ap.add_argument("--stages", default="vitpose,hmr2")
    ap.add_argument("--tag", default="", help="suffix for the output json")
    a = ap.parse_args()
    torch.set_num_threads(a.threads)

    from gvhmr.network.hmr2 import load_hmr2
    from gvhmr.utils.preproc.vitfeat_extractor import get_batch
    from gvhmr.utils.preproc.vitpose import VitPoseExtractor

    run = next(Path(a.run_dir).glob("*/0_input_video.mp4")).parent
    bbx_xys = torch.load(run / "preprocess/bbx.pt", weights_only=False)["bbx_xys"]
    imgs, _ = get_batch(str(run / "0_input_video.mp4"), bbx_xys, img_ds=0.5)
    imgs = imgs[: a.frames].contiguous()
    n = len(imgs)
    res = {"frames": n, "threads": a.threads, "batch": a.batch, "loadavg": Path("/proc/loadavg").read_text().split()[:3]}

    class HMR2Feat(torch.nn.Module):
        """Plain-module view of HMR2's feature path (the LightningModule itself won't trace)."""

        def __init__(self, m):
            super().__init__()
            self.backbone, self.smpl_head = m.backbone, m.smpl_head

        def forward(self, x):
            return self.smpl_head(self.backbone(x[:, :, :, 32:-32]), only_return_token_out=True)

    class VitPoseCrop(torch.nn.Module):
        def __init__(self, m):
            super().__init__()
            self.m = m

        def forward(self, x):
            return self.m(x[:, :, :, 32:224])

    want = a.stages.split(",")
    vp = VitPoseCrop(VitPoseExtractor(flip_test=False).pose).eval() if "vitpose" in want else None
    hmr = HMR2Feat(load_hmr2()).eval() if "hmr2" in want else None
    stages = {k: v for k, v in {"vitpose": vp, "hmr2": hmr}.items() if k in a.stages.split(",")}
    for name, model in stages.items():
        r = {}
        with torch.no_grad():
            model(imgs[:2])  # warm-up
            t, ref = timed(model, imgs, a.batch)
            r["torch_fp32_s_per_frame"] = round(t / n, 4)
            with torch.autocast("cpu", dtype=torch.bfloat16):
                model(imgs[:2])
                t, out = timed(model, imgs, a.batch)
            r["torch_bf16_s_per_frame"] = round(t / n, 4)
            r["torch_bf16_dev"] = deviation(name, ref, out.float())
        if a.openvino:
            import openvino as ov

            ex = torch.zeros(a.batch, 3, 256, 256)
            t0 = time.perf_counter()
            ovm = ov.convert_model(model, example_input=ex)
            r["openvino_convert_s"] = round(time.perf_counter() - t0, 1)
            core = ov.Core()
            for prec in ("f32", "bf16"):
                cm = core.compile_model(ovm, "CPU", {"INFERENCE_NUM_THREADS": a.threads, "INFERENCE_PRECISION_HINT": prec})
                xin = imgs
                fn = lambda x, cm=cm: torch.from_numpy(cm(x.numpy())[0])  # noqa: E731
                usable = (n // a.batch) * a.batch  # static batch shape
                fn(xin[: a.batch])
                t, out = timed(fn, xin[:usable], a.batch)
                r[f"openvino_{prec}_s_per_frame"] = round(t / usable, 4)
                r[f"openvino_{prec}_dev"] = deviation(name, ref[:usable], out.float())
        res[name] = r
        print(name, json.dumps(r), flush=True)
    out = Path(a.run_dir) / f"vit_backends{a.tag}.json"
    prev = json.loads(out.read_text()) if out.exists() else {}
    out.write_text(json.dumps(prev | res, indent=1))


def deviation(name: str, ref: torch.Tensor, out: torch.Tensor) -> dict:
    if name == "vitpose":
        d = (argmax_xy(ref) - argmax_xy(out)).norm(dim=-1)  # heatmap px (64x48 grid; 1 px = 4 input px)
        return {"argmax_shift_mean_hm_px": round(float(d.mean()), 4), "argmax_shift_gt1_frac": round(float((d > 1).float().mean()), 4),
                "heatmap_max_abs": round(float((ref - out).abs().max()), 4)}
    cos = torch.nn.functional.cosine_similarity(ref, out, dim=-1)
    return {"cos_mean": round(float(cos.mean()), 6), "cos_min": round(float(cos.min()), 6)}


if __name__ == "__main__":
    main()
