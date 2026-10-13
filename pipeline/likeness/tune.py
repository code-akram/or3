"""Local edits on a face delta, checked against render ratios predicted from the 3D mesh.

Prediction: the MediaPipe points embedded on the base mesh (clay_views.py embed) are taken on
base + delta, projected through a render camera (cameras.json from clay_views.py render), and the
refboard.py ratio definitions applied. Contour ratios (bizygomatic, bigonial) follow the silhouette,
not surface points, so they are not predicted. A calibration render of a known delta (its measured
ratios.json, same camera) gives a per-ratio offset, measured minus predicted, added to every
prediction; that absorbs the render pipeline (subdivision, sculpt) and the landmarker's own bias.

Edits act on the skin and the field helpers (lashes, hair, joint cubes); each rigid helper (eye,
teeth, tongue) translates by the edit field's mean over its vertices, so a mouth-corner move leaves
the teeth and a lower-face stretch carries them. Two kinds, in the base frame (+x the character's
left, +y backward, +z up; millimetres):

  move:    a smooth local move centred on an embedded landmark, or on the left eyeball centre with
           "at": "eye" (Wendland C2 falloff to "radius_mm", full weight inside "core_mm"; or an
           ellipsoid with "radius_mm": [x, y, z] and "core_frac"), optionally
           mirrored across the midline; a core larger than the eyeball moves the eye and its lids
           as one, so the lids keep their fit on the eye;
  scale:   per-axis scaling about landmark "at" by "factor_xyz" (e.g. [-0.2, 0, 0] narrows a
           region toward the midline without bunching it), weighted like a move;
  stretch: vertical lengthening below landmark "at" by "factor" down to landmark "to" (what lies
           below "to" moves with it, down to landmark "carry_to" if given, then tapers to zero
           over "below_mm"); full in front of "fade_back_mm"[0] behind the eye line, none
           behind [1];
  relax:   after the other edits, the delta inside the falloff around "at" is blended toward its
           Laplacian-smoothed self ("iters", default 30; "amount", default 1), so fine detail of the
           base survives the wrap and the broad moves;
  rigid:   likewise, but toward the delta's mean over the full-weight core, which then moves as one
           piece (a nostril-and-alar block keeps the base's nostril shape).

    {"edits": [{"name": "narrower mouth", "at": 291, "move_mm": [-2.5, 0, 0], "radius_mm": 14, "mirror": true},
               {"name": "longer face", "type": "stretch", "at": 168, "to": 152, "factor": 0.05,
                "below_mm": 80, "fade_back_mm": [30, 80]}]}

    python -I tune.py --base base.npz --embedding emb.npz --delta in.npz [--edits edits.json --out out.npz] \
        --cameras CLAY/cameras.json --view front [--calibrate CLAY/ratios.json --calibrate-delta used.npz] \
        [--ref ref/ratios.json]
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import refboard as rb
import wrap

CONTOUR = ("bizygomatic", "bigonial")


def landmarks(co, emb):
    """(478, 3) embedded landmark positions on a mesh with vertices co; invalid rows are nan."""
    P = np.einsum("lk,lkd->ld", emb["bary"], co[emb["tri_verts"]])
    P[~emb["valid"].astype(bool)] = np.nan
    return P


def project(P, view):
    K, M = np.array(view["K"]), np.array(view["world_to_cam"])
    X = P @ M[:3, :3].T + M[:3, 3]
    uv = X @ K.T
    return uv[:, :2] / uv[:, 2:]


def predict(co, emb, view):
    r = rb.ratios_2d(project(landmarks(co, emb), view))
    return {k: (np.nan if k in CONTOUR else v) for k, v in r.items()}


def wendland(r, R):
    t = np.clip(r / R, 0, 1)
    return (1 - t) ** 4 * (4 * t + 1)


def smoothstep(x, a, b):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def one_field(base, lm, co, e):
    """Unmasked displacement field (V, 3) of one edit."""
    name = e.get("name", e.get("at"))
    if e.get("type", "move") == "stretch":
        top, bot = lm[int(e["at"])], lm[int(e["to"])]
        if np.isnan(top).any() or np.isnan(bot).any():
            raise ValueError(f"edit {name}: landmark not embedded")
        span = top[2] - bot[2]
        carry = top[2] - lm[int(e["carry_to"])][2] if "carry_to" in e else span
        below = float(e.get("below_mm", 80)) / 1000.0
        s = top[2] - co[:, 2]                                  # depth below the top landmark
        amount = float(e["factor"]) * np.clip(s, 0, span)      # metres down
        amount *= 1 - smoothstep(s, carry, carry + below)      # taper below "carry_to" (default "to")
        eye_y = 0.5 * (base.eye_l[1] + base.eye_r[1])
        fb = np.asarray(e.get("fade_back_mm", [30, 80]), np.float64) / 1000.0
        amount *= 1 - smoothstep(co[:, 1] - eye_y, fb[0], fb[1])
        f = np.zeros_like(co)
        f[:, 2] = -amount
        return f
    if e.get("type") == "scale":                               # per-axis scaling about a landmark
        c = lm[int(e["at"])]
        if np.isnan(c).any():
            raise ValueError(f"edit {name}: landmark {e['at']} is not embedded")
        return weight(co, c, e)[:, None] * (co - c) * np.asarray(e["factor_xyz"], np.float64)
    if e["at"] == "eye":                                       # the character's left eyeball centre
        c = co[(base.group("helper-l-eye") > 0) & base.helper].mean(0)
    else:
        c = lm[int(e["at"])]
    if np.isnan(c).any():
        raise ValueError(f"edit {name}: landmark {e['at']} is not embedded")
    mv = np.asarray(e["move_mm"], np.float64) / 1000.0
    centres = [(c, mv)] + ([(c * [-1, 1, 1], mv * [-1, 1, 1])] if e.get("mirror") else [])
    f = np.zeros_like(co)
    for cc, m in centres:
        f += weight(co, cc, e)[:, None] * m
    return f


def weight(co, c, e):
    """Falloff of an edit around c: "radius_mm" a scalar (sphere; full weight inside "core_mm") or
    an x, y, z triple (ellipsoid; full weight inside the "core_frac" fraction of it)."""
    R = np.asarray(e["radius_mm"], np.float64) / 1000.0
    if R.ndim == 0:
        core = float(e.get("core_mm", 0.0)) / 1000.0
        r = np.maximum(np.linalg.norm(co - c, axis=1) - core, 0)
        return wendland(r, float(R) - core)
    rho = np.linalg.norm((co - c) / R, axis=1)
    k = float(e.get("core_frac", 0.0))
    return wendland(np.maximum(rho - k, 0), 1.0 - k)


POST = ("relax", "rigid")


def relax(base, emb, delta, edits):
    """Apply the "relax" and "rigid" edits to a delta. Inside each edit's falloff the skin delta is
    blended toward its Laplacian-smoothed self ("relax", "iters" rounds over the skin graph) or toward
    its mean over the full-weight core ("rigid": the core moves as one piece), so fine detail the base
    had there (nostril openings, alar rims) comes back while the broad change is kept."""
    out = delta.copy()
    for e in edits:
        lm = landmarks(base.co + out, emb)
        c = lm[int(e["at"])]
        if np.isnan(c).any():
            raise ValueError(f"edit {e.get('name', e['at'])}: landmark {e['at']} is not embedded")
        w = weight(base.co + out, c, e) * base.skin
        if e["type"] == "rigid":
            core = w > 0.999
            if not core.any():
                raise ValueError(f"edit {e.get('name', e['at'])}: empty core (raise core_mm / core_frac)")
            target = np.broadcast_to(out[core].mean(0), out.shape)
        else:
            target = base.smooth(out, int(e.get("iters", 30)))
        out += (w * float(e.get("amount", 1.0)))[:, None] * (target - out)
    return out


def edit_field(base, emb, co, edits):
    """Displacement field (V, 3) of the edits, evaluated on the current surface co: the skin and
    field helpers take it per vertex, each rigid helper its mean over the helper's vertices.
    "relax" and "rigid" edits are not fields; relax() applies them to the edited delta."""
    edits = [e for e in edits if e.get("type") not in POST]
    lm = landmarks(co, emb)
    movable = base.skin.copy()
    for g in wrap.FIELD_HELPERS:
        movable |= (base.group(g) > 0) & base.helper
    total = sum(one_field(base, lm, co, e) for e in edits)
    field = total * movable[:, None]
    for g in wrap.RIGID_HELPERS:
        m = (base.group(g) > 0) & base.helper
        if m.any():
            field[m] = total[m].mean(0)
    return field


def table(rows, ref):
    keys = [k for k in rows[0][1] if k not in CONTOUR]
    head = f"{'ratio':15s}" + (f" {'ref':>6s}" if ref else "") + "".join(f" {n:>16s}" for n, _ in rows)
    out = [head]
    for k in keys:
        line = f"{k:15s}" + (f" {ref[k]['median']:6.3f}" if ref else "")
        for _, r in rows:
            v = r[k]
            line += f" {v:6.3f}" + (f" {100 * (v / ref[k]['median'] - 1):+6.1f} %  " if ref else " " * 10)
        out.append(line)
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", required=True)
    ap.add_argument("--embedding", required=True, help="clay_views.py embed output for the base")
    ap.add_argument("--delta", required=True, help="face delta .npz (wrap.py output)")
    ap.add_argument("--edits", default="", help="JSON with an 'edits' list")
    ap.add_argument("--out", default="", help="edited delta .npz")
    ap.add_argument("--cameras", required=True)
    ap.add_argument("--view", default="front")
    ap.add_argument("--calibrate", default="", help="measured ratios.json of a render of --calibrate-delta")
    ap.add_argument("--calibrate-delta", default="", help="the delta that render used (default: --delta)")
    ap.add_argument("--ref", default="", help="reference ratios.json (medians) for the % columns")
    ap.add_argument("--symmetrise", action="store_true", help="average the edited delta with its mirror image")
    a = ap.parse_args(argv)

    base = wrap.Base(a.base)
    emb = dict(np.load(a.embedding))
    src = dict(np.load(a.delta))
    delta = src["delta"]
    view = json.load(open(a.cameras))["views"][a.view]
    ref = json.load(open(a.ref))["ratios"] if a.ref else None

    offset = {}
    if a.calibrate:
        cd = np.load(a.calibrate_delta)["delta"] if a.calibrate_delta else delta
        pred = predict(base.co + cd, emb, view)
        meas = next(r for r in json.load(open(a.calibrate))["per_image"] if r["image"] == f"{a.view}.png")
        offset = {k: meas[k] - pred[k] for k in pred if k not in CONTOUR}

    def calibrated(co):
        p = predict(co, emb, view)
        return {k: v + offset.get(k, 0.0) for k, v in p.items()}

    rows = [("in" + (" (cal)" if offset else ""), calibrated(base.co + delta))]
    if a.edits:
        edits = json.load(open(a.edits))["edits"]
        field = edit_field(base, emb, base.co + delta, edits)
        new = relax(base, emb, delta + field, [e for e in edits if e.get("type") in POST])
        field = new - delta
        if a.symmetrise:                                       # average with the mirror image
            mm = wrap.mirror_map(base.co)
            ok = mm >= 0
            asym = np.abs(new[ok] - new[mm[ok]] * [-1, 1, 1]).max() * 1000
            new[ok] = 0.5 * (new[ok] + new[mm[ok]] * [-1, 1, 1])
            print(f"[tune] symmetrised {int(ok.sum())} verts (largest asymmetry was {asym:.2f} mm)")
        rows.append(("edited" + (" (cal)" if offset else ""), calibrated(base.co + new)))
        mv = np.linalg.norm(field, axis=1) * 1000
        print(f"[tune] {len(edits)} edits; field max {mv.max():.2f} mm, {int((mv > 0.1).sum())} verts over 0.1 mm")
        if a.out:
            notes = str(src.get("notes", "")) + f"; tune: {json.dumps(edits)}"
            np.savez(a.out, **{**src, "delta": new, "notes": notes})
            print(f"[tune] -> {a.out}")
    print(table(rows, ref))
    if offset:
        print("calibration offsets (measured - predicted): " + ", ".join(f"{k} {v:+.3f}" for k, v in offset.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
