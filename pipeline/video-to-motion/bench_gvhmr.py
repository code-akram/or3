"""Per-stage CPU benchmark of the GVHMR video-to-motion pipeline (Phase 0 spike 3).

Runs each stage of the ryanrudes/gvhmr fork *serially* (no SimpleVO overlap, so every stage is timed
on its own) and records seconds/frame, thread count and /proc/loadavg per stage:

    stage (resample to 30 fps) -> YOLO track -> crop -> ViTPose-H -> HMR2 ViT-H features -> SimpleVO -> GVHMR

Optional ``--bf16 vitpose,hmr2,yolo,gvhmr`` wraps those stages in ``torch.autocast("cpu", bfloat16)``
(the fork only autocasts on CUDA). Outputs (preprocess caches, hmr4d_results.pt, timings.json, an
SMPL-X params npz) go to ``--out`` and must stay under private/.

Run with the fork's venv (thread caps must be in the environment before torch is imported):

    export OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 GVHMR_CHECKPOINTS=.../private/models/gvhmr
    .venv/bin/python -I pipeline/video-to-motion/bench_gvhmr.py CLIP.mp4 --out RUN_DIR --threads 4
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import platform
import shutil
import sys
import time
from pathlib import Path


def loadavg() -> list[str]:
    return Path("/proc/loadavg").read_text().split()[:3]


def stitch_protagonist(track_history, W, H, max_gap=24, max_center_dist=0.75, max_size_ratio=2.0, seed=None,
                       exclude=()):
    """Protagonist = a chain of non-overlapping tracker fragments, seeded by the largest area-sum track
    and extended both ways with the fragment whose boundary box best continues the chain. ``seed`` overrides
    the seed track id (manual pick, or protagonist_id.py's appearance pick). Fragments in ``exclude``
    (appearance says: someone else) are never joined.

    BoT-SORT fragments one person into many IDs through fast motion, blur and darkness (falls, fights);
    GVHMR's default keeps only the single top ID and linearly interpolates the rest. This is the cheap,
    appearance-free half of NOTES.md §8's protagonist ID (face/body embeddings would gate the joins)."""
    import numpy as np

    frags: dict[int, dict[int, np.ndarray]] = {}
    for f, dets in enumerate(track_history):
        for d in dets:
            frags.setdefault(d["id"], {})[f] = np.asarray(d["bbx_xyxy"], dtype=np.float64)
    if not frags:
        raise RuntimeError("no person tracks")

    def area(b):
        return max(b[2] - b[0], 1.0) * max(b[3] - b[1], 1.0)

    score = {k: sum(area(b) for b in v.values()) / (W * H) for k, v in frags.items()}
    if seed is None:
        seed = max(score, key=score.get)
    elif seed not in frags:
        raise RuntimeError(f"seed track {seed} not in tracks {sorted(frags)}")
    chain, frame_box = [seed], dict(frags[seed])

    def joinable(b_from, b_to, gap):
        c1, c2 = (b_from[:2] + b_from[2:]) / 2, (b_to[:2] + b_to[2:]) / 2
        diag = max(np.hypot(*(b_from[2:] - b_from[:2])), np.hypot(*(b_to[2:] - b_to[:2])))
        ratio = max(area(b_from), area(b_to)) / min(area(b_from), area(b_to))
        return np.linalg.norm(c1 - c2) <= max_center_dist * diag * (1 + gap / max_gap) and ratio <= max_size_ratio**2

    while True:
        lo, hi = min(frame_box), max(frame_box)
        best = None
        for k, v in frags.items():
            if k in chain or k in exclude:
                continue
            s, e = min(v), max(v)
            if s > hi - 2:  # extends forward
                gap = s - hi
                ok = gap <= max_gap and joinable(frame_box[hi], v[s], max(gap, 0))
            elif e < lo + 2:  # extends backward
                gap = lo - e
                ok = gap <= max_gap and joinable(frame_box[lo], v[e], max(gap, 0))
            else:
                continue
            if ok and (best is None or (gap, -score[k]) < (best[1], -score[best[0]])):
                best = (k, gap)
        if best is None:
            break
        chain.append(best[0])
        for f, b in frags[best[0]].items():
            frame_box.setdefault(f, b)
    return chain, frame_box


def interpolate_track(frame_box, L):
    """Same post-processing as GVHMR's Tracker.get_one_track: fill gaps linearly, hold the ends, smooth."""
    import numpy as np
    import torch

    from gvhmr.utils.net_utils import moving_average_smooth

    fs = np.array(sorted(frame_box))
    boxes = np.stack([frame_box[f] for f in fs])
    out = np.stack([np.interp(np.arange(L), fs, boxes[:, i]) for i in range(4)], -1)
    out = torch.from_numpy(out).float()
    out = moving_average_smooth(out, window_size=5, dim=0)
    return moving_average_smooth(out, window_size=5, dim=0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--out", required=True)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--static", action="store_true", help="static camera (skip SimpleVO)")
    ap.add_argument("--bf16", default="", help="comma list of stages to run under CPU bf16 autocast")
    ap.add_argument("--no-flip", action="store_true", help="ViTPose flip-test off (the 'fast' trade)")
    ap.add_argument("--fresh", action="store_true", help="delete --out first")
    ap.add_argument("--reuse", default="", help="comma list of stages whose cached output to reuse")
    ap.add_argument("--stitch", action="store_true",
                    help="protagonist = chain of tracker fragments stitched by box continuity (default: GVHMR's top track)")
    ap.add_argument("--seed-id", type=int, default=None,
                    help="with --stitch: seed the protagonist chain on this track id; with --reuse yolo, reselects from the saved track history")
    ap.add_argument("--auto-id", action="store_true",
                    help="with --stitch --reuse yolo: seed and exclusions from OUT/protagonist.json (protagonist_id.py score)")
    ap.add_argument("--set", action="append", default=[], help="extra Hydra override, e.g. detector.conf=0.25")
    ap.add_argument("--stop-after", default="", help="stop after this stage (e.g. yolo)")
    ap.add_argument("--vitpose-probe", type=int, default=0, metavar="N",
                    help="ViTPose on N evenly spaced frames of the selected track only; writes OUT/vitpose-probe.json "
                         "(mean body-joint confidence, a cheap pre-GVHMR visibility check) and stops")
    a = ap.parse_args()
    sys.path.append(str(Path(__file__).resolve().parent.parent / "likeness"))
    import containment  # outputs derive from film frames: private only (NOTES.md §14)

    containment.assert_outputs(a, "out")

    for var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        if os.environ.get(var) != str(a.threads):
            sys.exit(f"set {var}={a.threads} in the environment before running (thread caps must precede torch import)")
    os.environ.setdefault("GVHMR_NO_VO_OVERLAP", "1")

    import cv2
    import numpy as np
    import torch

    torch.set_num_threads(a.threads)
    cv2.setNumThreads(a.threads)

    import hydra

    from gvhmr.cli.demo import _ctor_kwargs, build_demo_cfg, load_data_dict, recover_motion
    from gvhmr.utils.device import predict_device
    from gvhmr.utils.geo.hmr_cam import get_bbx_xys_from_xyxy
    from gvhmr.utils.preproc.base import make_backbone, make_detector, make_pose2d
    from gvhmr.utils.preproc.vitfeat_extractor import get_batch

    out = Path(a.out).resolve()
    if a.fresh and out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    bf16 = {s for s in a.bf16.split(",") if s}
    reuse = {s for s in a.reuse.split(",") if s}

    def amp(stage: str):
        if stage in bf16:
            return torch.autocast("cpu", dtype=torch.bfloat16)
        return contextlib.nullcontext()

    timings: dict[str, dict] = {}

    def record(stage: str, seconds: float, frames: int, load_s: float | None = None) -> None:
        torch.set_num_threads(a.threads)  # some libs (ultralytics) reset it; re-pin after every stage
        timings[stage] = {
            "seconds": round(seconds, 3),
            "frames": frames,
            "s_per_frame": round(seconds / max(frames, 1), 4),
            "model_load_s": None if load_s is None else round(load_s, 2),
            "torch_threads": torch.get_num_threads(),
            "bf16": stage in bf16,
            "loadavg_after": loadavg(),
        }
        print(f"[{stage}] {seconds:.2f}s  {seconds / max(frames, 1):.4f} s/frame  (load {load_s or 0:.1f}s) "
              f"threads={torch.get_num_threads()} loadavg={' '.join(loadavg())}", flush=True)

    overrides = []
    if a.no_flip:
        overrides.append("pose2d.flip_test=false")
    overrides += a.set
    t0 = time.perf_counter()
    cfg = build_demo_cfg(
        Path(a.video), output_root=str(out), static_cam=a.static, use_dpvo=False, f_mm=None, verbose=False,
        render_scale=None, config_overrides=overrides,
    )
    from gvhmr.utils.video_io_utils import get_video_lwh

    L, W, H = get_video_lwh(cfg.video_path)
    record("stage_30fps", time.perf_counter() - t0, L)
    paths = cfg.paths

    # 1) YOLO + BoT-SORT tracking, top track by area-sum = protagonist.
    th_path = Path(paths.bbx).with_name("track_history.pt")
    exclude: list[int] = []
    if a.auto_id:
        pj = out / "protagonist.json"
        if not pj.exists():
            sys.exit(f"--auto-id: {pj} missing (run protagonist_id.py embed + score first)")
        pick = json.loads(pj.read_text())
        if pick["seed"] is None:
            sys.exit("--auto-id: no protagonist track in this shot")
        a.seed_id, exclude = int(pick["seed"]), [int(k) for k in pick.get("exclude", [])]
    if "yolo" in reuse and a.seed_id is not None and th_path.exists():
        t = time.perf_counter()
        chain, frame_box = stitch_protagonist(torch.load(th_path, weights_only=False), W, H, seed=a.seed_id,
                                              exclude=exclude)
        bbx_xyxy = interpolate_track(frame_box, L)
        bbx_xys = get_bbx_xys_from_xyxy(bbx_xyxy, base_enlarge=1.2).float()
        torch.save({"bbx_xyxy": bbx_xyxy, "bbx_xys": bbx_xys}, paths.bbx)
        record("yolo_track", 0.0, L)
        timings["yolo_track"].update({"reselected": True, "seed_id": a.seed_id, "auto_id": a.auto_id,
                                      "exclude": exclude, "stitch": True, "chain": [int(c) for c in chain],
                                      "selected_frame_coverage": round(len(frame_box) / L, 3),
                                      "select_s": round(time.perf_counter() - t, 3)})
    elif "yolo" in reuse and Path(paths.bbx).exists():
        bbx_xys = torch.load(paths.bbx, weights_only=False)["bbx_xys"]
    else:
        # ultralytics' select_device() calls torch.set_num_threads(NUM_THREADS) with NUM_THREADS =
        # min(8, cpu_count - 1) on every predict/track setup, overriding our cap: YOLO always ran on 8
        # threads (flat 0.18 s/frame at 1-16 threads, and 4 concurrent processes oversubscribed to 32).
        import ultralytics.utils.torch_utils as _ul_tu

        _ul_tu.NUM_THREADS = a.threads
        t = time.perf_counter()
        tracker = make_detector(cfg.detector.name, **_ctor_kwargs(cfg.detector))
        load_s = time.perf_counter() - t
        torch.set_num_threads(a.threads)
        t = time.perf_counter()
        with amp("yolo"):
            track_history = tracker.track(cfg.video_path)
        track_s = time.perf_counter() - t
        torch.save(track_history, Path(paths.bbx).with_name("track_history.pt"))
        id_to_frame_ids, _, id_sorted = tracker.sort_track_length(track_history, cfg.video_path)
        n_tracks = len(id_sorted)
        top_cov = len(id_to_frame_ids[id_sorted[0]]) / L if id_sorted else 0.0
        t = time.perf_counter()
        if a.stitch:
            chain, frame_box = stitch_protagonist(track_history, W, H, seed=a.seed_id)
            bbx_xyxy = interpolate_track(frame_box, L)
            cov = len(frame_box) / L
        else:
            # get_one_track re-runs the tracker; reproduce its post-processing on our history instead.
            tracker.track = lambda _p, _h=track_history: _h
            bbx_xyxy = tracker.get_one_track(cfg.video_path).float()
            chain, cov = [id_sorted[0]], top_cov
        select_s = time.perf_counter() - t
        bbx_xys = get_bbx_xys_from_xyxy(bbx_xyxy, base_enlarge=1.2).float()
        torch.save({"bbx_xyxy": bbx_xyxy, "bbx_xys": bbx_xys}, paths.bbx)
        record("yolo_track", track_s, L, load_s)
        timings["yolo_track"].update({
            "n_tracks": n_tracks, "top_track_frame_coverage": round(top_cov, 3), "stitch": a.stitch,
            "chain": [int(c) for c in chain], "selected_frame_coverage": round(cov, 3), "select_s": round(select_s, 3),
        })
        del tracker

    if a.stop_after == "yolo":
        (out / "timings.json").write_text(json.dumps({"stages": timings}, indent=1))
        return

    # 2) shared decode + crop (ViTPose and HMR2 consume the same 256x256 crops)
    t = time.perf_counter()
    imgs, bbx_ds = get_batch(cfg.video_path, bbx_xys, img_ds=0.5)
    record("decode_crop", time.perf_counter() - t, L)

    if a.vitpose_probe:
        idx = torch.from_numpy(np.linspace(0, L - 1, min(a.vitpose_probe, L)).round().astype(np.int64)).unique()
        t = time.perf_counter()
        vp = make_pose2d(cfg.pose2d.name, **_ctor_kwargs(cfg.pose2d))
        with amp("vitpose"):
            kp = vp.extract(imgs[idx], bbx_ds[idx])
        conf = kp[:, 5:, 2].float()  # body joints (COCO 5-16), as motion_qc.py / footage_run.py
        (out / "vitpose-probe.json").write_text(json.dumps({
            "frames": len(idx), "mean_conf": round(float(conf.mean()), 3),
            "seed_id": a.seed_id, "s": round(time.perf_counter() - t, 2)}, indent=1))
        (out / "timings.json").write_text(json.dumps({"stages": timings}, indent=1))
        return

    # 3) ViTPose-H 2D keypoints
    if "vitpose" in reuse and Path(paths.vitpose).exists():
        pass
    else:
        t = time.perf_counter()
        vp = make_pose2d(cfg.pose2d.name, **_ctor_kwargs(cfg.pose2d))
        load_s = time.perf_counter() - t
        t = time.perf_counter()
        with amp("vitpose"):
            kp2d = vp.extract(imgs, bbx_ds)
        record("vitpose", time.perf_counter() - t, L, load_s)
        timings["vitpose"]["flip_test"] = bool(vp.flip_test)
        torch.save(kp2d, paths.vitpose)
        del vp

    # 4) HMR2 ViT-H image features
    if "hmr2" in reuse and Path(paths.vit_features).exists():
        pass
    else:
        t = time.perf_counter()
        ex = make_backbone(cfg.backbone.name, **_ctor_kwargs(cfg.backbone))
        load_s = time.perf_counter() - t
        t = time.perf_counter()
        with amp("hmr2"):
            feats = ex.extract_video_features(imgs, bbx_ds)
        record("hmr2_features", time.perf_counter() - t, L, load_s)
        torch.save(feats, paths.vit_features)
        del ex
    del imgs

    # 5) SimpleVO camera rotation (pycolmap SIFT)
    if not a.static:
        if "vo" in reuse and Path(paths.slam).exists():
            pass
        else:
            from gvhmr.utils.preproc import SimpleVO

            cam = cfg.camera
            t = time.perf_counter()
            vo = SimpleVO(cfg.video_path, scale=cam.scale, step=cam.step, method=cam.method, f_mm=cfg.f_mm, progress=False)
            torch.save(vo.compute(), paths.slam)
            record("simplevo", time.perf_counter() - t, L)

    # 6) GVHMR network
    data = load_data_dict(cfg)
    t = time.perf_counter()
    model = hydra.utils.instantiate(cfg.model, _recursive_=False)
    model.load_pretrained_model(cfg.ckpt_path)
    model = model.eval().to(predict_device())
    load_s = time.perf_counter() - t
    torch.set_num_threads(a.threads)
    t = time.perf_counter()
    with amp("gvhmr"):
        pred = recover_motion(model, data, static_cam=cfg.static_cam, world_from_incam=cfg.static_cam,
                              cam_name=cfg.camera.name, slam_path=paths.slam)
    record("gvhmr", time.perf_counter() - t, L, load_s)
    torch.save(pred, paths.hmr4d_results)

    # Export SMPL-X params (world + in-cam) and intrinsics as a plain npz.
    arrs = {}
    for frame in ("global", "incam"):
        for k, v in pred[f"smpl_params_{frame}"].items():
            arrs[f"{frame}_{k}"] = v.float().numpy()
    arrs["K_fullimg"] = pred["K_fullimg"].float().numpy()
    arrs["bbx_xys"] = bbx_xys.numpy()
    arrs["kp2d"] = torch.load(paths.vitpose, weights_only=False).numpy()
    arrs["fps"] = np.array(30.0)
    arrs["img_wh"] = np.array([W, H])
    np.savez(out / "smplx_params.npz", **arrs)

    total = sum(v["seconds"] for k, v in timings.items())
    res = {
        "video": str(Path(a.video).resolve()),
        "frames_30fps": L,
        "resolution": [W, H],
        "threads": a.threads,
        "bf16_stages": sorted(bf16),
        "vitpose_flip_test": not a.no_flip,
        "static_cam": a.static,
        "overrides": overrides,
        "stitch": a.stitch,
        "torch": torch.__version__,
        "python": platform.python_version(),
        "cpu": platform.processor() or platform.machine(),
        "loadavg_start_end": loadavg(),
        "stages": timings,
        "total_compute_s": round(total, 2),
        "total_s_per_frame": round(total / L, 4),
    }
    (out / "timings.json").write_text(json.dumps(res, indent=1))
    print(f"TOTAL {total:.1f}s for {L} frames = {total / L:.3f} s/frame")


if __name__ == "__main__":
    main()
