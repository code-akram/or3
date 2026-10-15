"""Export the look-dev and hero stages (cameras, lights, poses) as JSON for
the web character viewer, so the engine frame matches Blender by data, not
by hand (bench/m1/v4/t5-viewer.md).

    blender -b -t 3 --factory-startup --python-exit-code 1 \\
        --python blender/hero/export_rig.py -- --glb RUN/character.glb \\
        --out RUN/engine_stage.json [--shots portrait] [--rig-json RUN/character.rig.json]

Everything is written in glTF space: Blender (x, y, z) -> (x, z, -y), metres;
the character faces +Z, +X is its left.

  landmarks  floor height, the head midpoint lookdev_render.py frames on, the
             rest-pose eye centres
  lookdev    blender/lookdev_render.py's studio (build_studio) and fixed views
             (make_cameras), replicated here (that module parses argv on import)
  hero       the hero rig constants (HERO_LIGHTS as camera-relative specs, the
             grade's colour fields) and, per shot, the posed skeleton (one
             deform matrix per bone: D = W_posed * W_rest^-1, independent of
             the importer's bone orientation), the camera, the placed lights
             with their light-linking groups, and the corrective weights
             Blender's deformation runtime computed (to check the TS port).

Set, haze, rain and beads are skipped (the engine has no set). The gaze is
exported as per-eye rotations (wet.gaze_rotations); DoF as f-stop + focus.
"""

import argparse
import json
import math
import os
import sys
import time

import bpy
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.dirname(HERE) not in sys.path:
    sys.path.insert(0, os.path.dirname(HERE))

from hero import grade, poses, rig, shots, wet  # noqa: E402

# --------------------------------------------------------------- lookdev_render.py copies
# Keep in sync with blender/lookdev_render.py (VIEWS, BODY_*, HEAD_FRAME_H,
# STUDIO_EXPOSURE, build_studio, view_target, make_cameras, landmarks).
LD_VIEWS = {
    "front": (0.0, "body"),
    "three_quarter": (40.0, "body"),
    "profile": (90.0, "body"),
    "closeup": (25.0, "head"),
}
LD_BODY_TARGET_Z = 0.98
LD_BODY_FRAME_H = 2.15
LD_HEAD_FRAME_H = 0.42
LD_RES = 512
LD_EXPOSURE = float(os.environ.get("LOOKDEV_EXPOSURE", "-2.5"))
LD_WORLD = (0.045, 0.045, 0.05)
LD_FLOOR = {"albedo": [0.08, 0.08, 0.085], "roughness": 0.8, "size": 60}
LD_AIM_Z = 1.1
LD_LIGHTS = [("key", (-2.2, -2.6, 2.8), 900, 1.5, (1.0, 0.96, 0.9)),
             ("fill", (2.6, -2.0, 1.4), 250, 2.0, (0.85, 0.9, 1.0)),
             ("rim", (0.8, 2.8, 2.6), 700, 1.0, (1.0, 1.0, 1.0))]
LD_SKIN = {"saturation": 0.55, "value": 0.88, "roughness": 0.62,
           "note": "lookdev_render.lookdev_skin only touches body materials NOT named skin_*; "
                   "builds with the generated skin_head / skin_hands materials render the asset "
                   "skin textures unchanged in the EEVEE views (render_metrics.json skin.materials "
                   "lists what it changed)"}

# Blender Z-up -> glTF Y-up
C = Matrix(((1, 0, 0, 0), (0, 0, 1, 0), (0, -1, 0, 0), (0, 0, 0, 1)))
C_INV = C.inverted()


def gl(v):
    return [round(float(v[0]), 6), round(float(v[2]), 6), round(float(-v[1]), 6)]


def gl_mat(m):
    """Blender world-space 4x4 -> glTF space, column-major (three.js fromArray)."""
    g = C @ m @ C_INV
    return [round(g[r][c], 7) for c in range(4) for r in range(4)]


def gl_quat(q):
    """Blender world rotation -> glTF space [x, y, z, w]."""
    g = (C.to_3x3() @ q.to_matrix() @ C_INV.to_3x3()).to_quaternion()
    return [round(g.x, 7), round(g.y, 7), round(g.z, 7), round(g.w, 7)]


# --------------------------------------------------------------- blackbody
def _g(x, mu, s1, s2):
    s = s1 if x < mu else s2
    t = (x - mu) / s
    return math.exp(-0.5 * t * t)


def _cmf(lam):
    """CIE 1931 2deg colour matching functions, Wyman, Sloan & Shirley 2013
    multi-lobe fit (lam in nm)."""
    x = 1.056 * _g(lam, 599.8, 37.9, 31.0) + 0.362 * _g(lam, 442.0, 16.0, 26.7) \
        - 0.065 * _g(lam, 501.1, 20.4, 26.2)
    y = 0.821 * _g(lam, 568.8, 46.9, 40.5) + 0.286 * _g(lam, 530.9, 16.3, 31.1)
    z = 1.217 * _g(lam, 437.0, 11.8, 36.0) + 0.681 * _g(lam, 459.0, 26.0, 13.8)
    return x, y, z


def blackbody(kelvin):
    """Linear Rec.709 colour of a blackbody, luminance 1 (an approximation of
    Blender's blackbody table: Planck x CIE 1931 fit, XYZ -> sRGB primaries)."""
    h, c, k = 6.62607015e-34, 2.99792458e8, 1.380649e-23
    X = Y = Z = 0.0
    for lam in range(380, 781, 5):
        l = lam * 1e-9
        p = (2 * h * c * c) / (l ** 5 * (math.exp(h * c / (l * k * kelvin)) - 1.0))
        cx, cy, cz = _cmf(lam)
        X, Y, Z = X + p * cx, Y + p * cy, Z + p * cz
    r = 3.2404542 * X - 1.5371385 * Y - 0.4985314 * Z
    g = -0.9692660 * X + 1.8760108 * Y + 0.0415560 * Z
    b = 0.0556434 * X - 0.2040259 * Y + 1.0572252 * Z
    rgb = [max(r, 0.0), max(g, 0.0), max(b, 0.0)]
    lum = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
    return [round(v / lum, 6) for v in rgb]


def colour(c):
    if isinstance(c, (int, float)):
        return blackbody(float(c)), float(c)
    return [round(float(v), 6) for v in c], None


# --------------------------------------------------------------- landmarks
def landmarks(ch):
    arm = ch.arm
    meshes = [o for o in ch.objs if o.type == "MESH" and o.parent == arm]
    floor_z = min(float(min((o.matrix_world @ Vector(c)).z for c in o.bound_box)) for o in meshes)
    mw = arm.matrix_world
    if "head" in arm.data.bones:
        b = arm.data.bones["head"]
        head = mw @ ((b.head_local + b.tail_local) * 0.5)
    else:  # lookdev_render's fallback: top of the body - 0.13
        body = next(o for o in meshes if o.name == "Human_export")
        top = max((body.matrix_world @ v.co).z for v in body.data.vertices)
        head = Vector((0, 0, top - 0.13))
    el, er = ch.eyes()
    return floor_z, head, el, er


def lookdev(floor_z, head):
    aim = Vector((0, 0, floor_z + LD_AIM_Z))
    lights = []
    for name, loc, energy, size, col in LD_LIGHTS:
        p = Vector(loc) + Vector((0, 0, floor_z))
        lights.append({"name": name, "type": "AREA", "position": gl(p), "target": gl(aim),
                       "color": list(col), "power_w": energy, "size": [size, size]})
    cams = {}
    for view, (az, framing) in LD_VIEWS.items():
        if framing == "body":
            target, frame_h = Vector((0.0, 0.0, floor_z + LD_BODY_TARGET_Z)), LD_BODY_FRAME_H
            lens = 50.0
        else:
            target = head.copy()
            target.z -= 0.03
            frame_h, lens = LD_HEAD_FRAME_H, 85.0
        a = math.radians(az)
        axis = Vector((math.sin(a), -math.cos(a), 0.0))
        sensor = 36.0
        dist = (frame_h * 0.5) / math.tan(math.atan(sensor * 0.5 / lens))
        cams[view] = {"position": gl(target + axis * dist), "target": gl(target), "up": [0, 1, 0],
                      "lens_mm": lens, "sensor_fit": "AUTO", "sensor_mm": sensor,
                      "vfov_deg": round(math.degrees(2 * math.atan(sensor * 0.5 / lens)), 6),
                      "res": [LD_RES, LD_RES], "shift": [0.0, 0.0], "azimuth_deg": az,
                      "frame_h_m": frame_h}
    return {"exposure": LD_EXPOSURE, "view_transform": "AgX", "look": "None",
            "world": {"color": list(LD_WORLD), "strength": 1.0},
            "floor": {"y": round(floor_z, 6), **LD_FLOOR},
            "lights": lights, "cameras": cams}


# --------------------------------------------------------------- hero
def light_groups(ch):
    """object name -> rig.TWIN_GROUPS group names."""
    out = {}
    for g, fn in rig.TWIN_GROUPS.items():
        for o in fn(ch):
            out.setdefault(o.name, set()).add(g)
    return out


def receivers(ob, groups_of):
    rc = ob.light_linking.receiver_collection
    if rc is None or not rc.objects:
        return {"mode": "all", "groups": []}
    states = {co.light_linking.link_state for co in rc.collection_objects}
    mode = "include" if states == {"INCLUDE"} else "exclude" if states == {"EXCLUDE"} else "mixed"
    gs = set()
    for o in rc.objects:
        gs |= groups_of.get(o.name, set())
    return {"mode": mode, "groups": sorted(gs),
            "objects": sorted(o.name for o in rc.objects)}


def rest_world(arm):
    return {b.name: arm.matrix_world @ b.matrix_local for b in arm.data.bones}


def bone_deforms(arm):
    mw, mwi = arm.matrix_world, arm.matrix_world.inverted()
    return {pb.name: gl_mat(mw @ pb.matrix @ pb.bone.matrix_local.inverted() @ mwi)
            for pb in arm.pose.bones}


def helper_quats(arm, rules):
    out = {}
    for h in (rules or {}).get("helpers", []):
        pb = arm.pose.bones.get(h["bone"])
        if pb is None:
            continue
        q = (arm.matrix_world @ pb.matrix @ pb.bone.matrix_local.inverted() @ arm.matrix_world.inverted()) \
            .to_quaternion()
        out[h["bone"]] = gl_quat(q)
    return out


def shot(ch, name, rules, groups_of):
    spec = shots.SHOTS[name]
    log = poses.apply(ch.arm, spec["pose"])
    bpy.context.view_layer.update()
    cam = rig.camera(ch, spec["cam"])
    cd = cam["obj"].data
    cd.shift_x = spec.get("shift", 0.0)
    cd.shift_y = spec.get("shift_y", 0.0)
    made = rig.hero_rig(ch, cam, lights=dict(spec.get("lights") or {}), twin=spec.get("twin"))
    bpy.context.view_layer.update()
    co = cam["obj"]
    q = co.matrix_world.to_quaternion()
    up = q @ Vector((0, 1, 0))
    res = spec["res"]
    lights = []
    for key, ob in made.items():
        ld = ob.data
        if getattr(ld, "use_temperature", False):
            col = blackbody(ld.temperature)
            col = [round(c * v, 6) for c, v in zip(col, ld.color)]
            kelvin = ld.temperature
        else:
            col, kelvin = [round(v, 6) for v in ld.color], None
        fwd = ob.matrix_world.to_quaternion() @ Vector((0, 0, -1))
        # rig.hero_rig aims every light at the subject, the eye light at the eyes
        aim = ch.aim("eyes") if key == "eye" else cam["subject"]
        lights.append({
            "name": key, "position": gl(ob.matrix_world.translation), "target": gl(aim),
            "direction": gl(fwd), "quaternion": gl_quat(ob.matrix_world.to_quaternion()),
            "color": col, "kelvin": kelvin, "power_w": round(ld.energy, 6),
            "size": [round(ld.size, 6), round(ld.size_y if ld.shape in ("RECTANGLE", "ELLIPSE") else ld.size, 6)],
            "use_shadow": bool(ld.use_shadow), "diffuse_factor": round(ld.diffuse_factor, 4),
            "specular_factor": round(ld.specular_factor, 4),
            "receivers": receivers(ob, groups_of)})
    gz = None
    if spec.get("gaze") is not None:
        # stage.render_shot turns the eyes to the camera (wet.gaze); export the turn, not the mesh edit
        wet.restore(ch)
        rots, deg, objs = wet.gaze_rotations(ch, co.matrix_world.translation, off_deg=spec["gaze"])
        if rots:
            gz = {"off_deg": spec["gaze"], "deg": deg, "objects": [o.name for o in objs],
                  "note": "rotate the eye meshes' bind-pose vertices about centre (rest world); "
                          "l = +X side (the character's left)",
                  "l": {"centre": gl(rots[1][0]), "quat": gl_quat(rots[1][1].to_quaternion())},
                  "r": {"centre": gl(rots[-1][0]), "quat": gl_quat(rots[-1][1].to_quaternion())}}
    from character import deform_runtime as drt
    meshes = poses._meshes(ch.arm)
    weights = drt.Runtime(ch.arm, meshes, rules).morph_weights() if rules else {}
    return {
        "pose": spec["pose"], "pose_log": log,
        "camera": {"position": gl(co.matrix_world.translation), "target": gl(cam["aim"]),
                   "up": gl(up), "quaternion": gl_quat(q),
                   "lens_mm": cd.lens, "sensor_fit": cd.sensor_fit, "sensor_mm": cd.sensor_height,
                   "vfov_deg": round(math.degrees(2 * math.atan(cd.sensor_height * 0.5 / cd.lens)), 6),
                   "res": list(res), "shift": [cd.shift_x, cd.shift_y],
                   "fstop": cam["fstop"],
                   "focus_m": round(cd.dof.focus_distance, 6) if cd.dof.use_dof else None,
                   "spec": spec["cam"], "frame_h_m": cam["frame_h"], "azimuth_deg": cam["az"]},
        "subject": gl(cam["subject"]), "aim": gl(cam["aim"]),
        "eyes": {"l": gl(ch.eyes()[0]), "r": gl(ch.eyes()[1])},
        "exposure": rig.HERO_EXPOSURE + spec.get("ev", 0.0),
        "rim_key": {k: round(v, 4) for k, v in rig.rim_key_ratios(spec.get("lights")).items()},
        "gaze": gz,
        "skipped": ["set", "haze", "rain", "beads"],
        "lights": lights,
        "bones": bone_deforms(ch.arm),
        "corrective_weights": {k: round(v, 6) for k, v in sorted(weights.items())},
        "helper_world_quats": helper_quats(ch.arm, rules),
    }


def main(argv):
    ap = argparse.ArgumentParser(prog="export_rig.py")
    ap.add_argument("--glb", required=True, help="character.glb (or a kept character.blend)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--shots", default="portrait")
    ap.add_argument("--rig-json", default=None)
    a = ap.parse_args(argv)
    t0 = time.perf_counter()
    ch = rig.load_character(a.glb)
    arm = ch.arm
    # hand_pose.Scene finds the body mesh by a "body" vertex group, which the
    # glTF round trip drops (only joint groups survive); an empty marker group
    # restores the lookup without changing any weight (the group is skipped
    # as a dominant-bone name).
    body = next((o for o in ch.objs if o.type == "MESH" and o.name == "Human_export"), None)
    if body is not None and not any("body" in o.vertex_groups for o in ch.objs if o.type == "MESH"):
        body.vertex_groups.new(name="body")
    rules = None
    if "deform_rules" in arm:
        rules = json.loads(arm["deform_rules"])
    else:
        p = a.rig_json or os.path.join(os.path.dirname(os.path.abspath(a.glb)), "character.rig.json")
        if os.path.exists(p):
            with open(p) as f:
                rules = json.load(f)
            arm["deform_rules"] = json.dumps(rules)
    bpy.context.view_layer.update()
    floor_z, head, el, er = landmarks(ch)
    groups_of = light_groups(ch)
    specs = {}
    for n, (c, ratio, size, az, el_, dist) in rig.HERO_LIGHTS.items():
        rgb, k = colour(c)
        specs[n] = {"color": rgb, "kelvin": k, "ratio": ratio, "size": list(size), "az": az, "el": el_,
                    "dist": dist}
    G = grade.GRADE
    out = {
        "version": 1, "space": "glTF model (Y up, m; character faces +Z, +X its left)",
        "source": {"glb": os.path.basename(a.glb), "blender": bpy.app.version_string,
                   "script": "blender/hero/export_rig.py"},
        "blackbody": "Planck x CIE 1931 (Wyman-Sloan-Shirley 2013 fit) -> linear Rec.709, luminance 1; "
                     "an approximation of Blender's blackbody",
        "bones": len(arm.data.bones),
        "rules": bool(rules),
        "landmarks": {"floor_y": round(floor_z, 6), "head_mid": gl(head),
                      "eyes_rest": {"l": gl(el), "r": gl(er)}},
        "lookdev": lookdev(floor_z, head),
        "lookdev_skin": LD_SKIN,
        "hero": {
            "e_key": rig.HERO_E, "exposure": rig.HERO_EXPOSURE, "look": rig.HERO_LOOK,
            "eye_diffuse": rig.EYE_DIFFUSE,
            "rim_max": rig.RIM_MAX,
            "grade": {k: G[k] for k in ("slope", "offset", "power", "saturation", "black_lift",
                                        "vignette_ev", "wb_kelvin")}
            | {"wb_rgb": blackbody(G["wb_kelvin"]) if G.get("wb_kelvin") else [1.0, 1.0, 1.0]},
            "world": {"color": [0.003, 0.003, 0.004]},
            "light_specs": specs,
            "light_power": "power_w = ratio * e_key * pi * dist^2 (rig._light_power); "
                           "for a camera-less eye light dist = |camera - subject|",
            "hair_rim": {"enabled": rig.HAIR_RIM, "sat": rig.HAIR_RIM_SAT, "min_sat": rig.HAIR_RIM_MIN_SAT,
                         "toward": list(rig.HAIR_RIM_TOWARD)},
            "twin_groups": {g: sorted(o.name for o in fn(ch)) for g, fn in rig.TWIN_GROUPS.items()},
            "shots": {},
        },
    }
    for n in [s for s in a.shots.split(",") if s]:
        out["hero"]["shots"][n] = shot(ch, n, rules, groups_of)
    out["seconds"] = round(time.perf_counter() - t0, 2)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w") as f:
        json.dump(out, f, indent=1)
    print(f"[export_rig] wrote {a.out} in {out['seconds']} s", flush=True)


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
