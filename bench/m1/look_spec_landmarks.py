"""Reference implementation of the landmark definitions in bench/m1/look-spec.md (section 1).

Run on a staged character .blend (the one blender/build_character.py saves):

    blender -b data/build/character/character.blend --factory-startup \
        --python bench/m1/look_spec_landmarks.py -- [--json out.json]

All measures are in metres, world space, rest pose, Z up, front = -Y. The body mesh is the
MPFB staged base mesh (the "<name>_export" object with no dot in its name). A vertex belongs
to the bone with its largest deform weight. The look-dev harness may absorb this file; the
definitions in look-spec.md are the contract, this is one implementation of them.
"""
import json
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
out_json = argv[argv.index("--json") + 1] if "--json" in argv else None

arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
# The MPFB base mesh carries a "body" vertex group. Body landmarks need the unclothed mesh:
# a staged clothed build has the covered polygons deleted, so measure a nude build.
body = max((o for o in bpy.data.objects if o.type == "MESH" and "body" in o.vertex_groups),
           key=lambda o: len(o.data.vertices))
eyes = next((o for o in bpy.data.objects if o.type == "MESH" and "low-poly" in o.name), None)
HELPERS = {"HelperGeometry", "JointCubes"}
deps = bpy.context.evaluated_depsgraph_get()


def bone_head(name):
    return arm.matrix_world @ arm.data.bones[name].head_local


def world_verts(obj):
    """(world position, dominant bone) per vertex of the evaluated mesh."""
    ev = obj.evaluated_get(deps)
    me = ev.to_mesh()
    groups = {g.index: g.name for g in obj.vertex_groups}
    bones = set(arm.data.bones.keys())
    out = []
    for v in me.vertices:
        vg = obj.data.vertices[v.index].groups
        if any(groups.get(g.group) in HELPERS and g.weight > 0 for g in vg):
            continue
        best, bw = None, 0.0
        for g in vg:
            n = groups.get(g.group)
            if n in bones and g.weight > bw:
                best, bw = n, g.weight
        out.append((obj.matrix_world @ v.co, best))
    ev.to_mesh_clear()
    return out


V = world_verts(body)
zs = [p.z for p, _ in V]
m = {}
m["stature"] = max(zs) - min(min(zs), 0.0)  # vertex (top of skull) to floor; soles at z~0
head_v = [p for p, b in V if b == "head"]
head_y = bone_head("head").y
ez = (sum((eyes.matrix_world @ v.co).z for v in eyes.data.vertices) / len(eyes.data.vertices)
      if eyes is not None else bone_head("head").z + 0.04)
# Midline profile (|x| < 6 mm, in front of the head bone). Pogonion = most forward point
# 8-15 cm below the eyes; menton = lowest midline point within 2.5 cm of the pogonion's depth
# (this skips the throat, which also carries head weights).
mid = [p for p, b in V if abs(p.x) < 0.006 and p.y < head_y and p.z > ez - 0.25]
pog = min((p for p in mid if ez - 0.15 < p.z < ez - 0.08), key=lambda p: p.y)
chin = min((p for p in mid if p.y < pog.y + 0.025 and p.z <= pog.z), key=lambda p: p.z)
m["head_height"] = max(zs) - chin.z  # vertex to menton
m["heads_tall"] = m["stature"] / m["head_height"]


def along(p, bone):
    """Distance of p along the bone's axis from its head (rest pose)."""
    b = arm.data.bones[bone]
    h, t = arm.matrix_world @ b.head_local, arm.matrix_world @ b.tail_local
    return (p - h).dot((t - h).normalized())


# Bideltoid: lateral extent of the deltoid cap = shoulder-girdle vertices no more than 6 cm
# down the upper-arm axis from the shoulder joint (independent of the A-pose arm angle).
delt = [p for p, b in V if b in ("upperarm_l", "upperarm_r", "clavicle_l", "clavicle_r")
        and along(p, "upperarm_l" if p.x > 0 else "upperarm_r") < 0.06]
m["bideltoid"] = max(p.x for p in delt) - min(p.x for p in delt)
hip_z = bone_head("thigh_l").z
# Hip breadth: widest pelvis/thigh section from 10 cm below to 2 cm above the hip joints.
hips = [p for p, b in V if b in ("pelvis", "thigh_l", "thigh_r", "spine_01")
        and hip_z - 0.10 < p.z < hip_z + 0.02]
if not hips:
    sys.exit("look_spec_landmarks: no hip vertices; the body has its covered polygons deleted. "
             "Measure a nude build (same macros, no clothes, not staged for export).")
m["hip_breadth"] = max(p.x for p in hips) - min(p.x for p in hips)
m["shoulder_to_hip"] = m["bideltoid"] / m["hip_breadth"]
m["biacromial_joints"] = bone_head("upperarm_l").x - bone_head("upperarm_r").x

crotch = min((p for p, b in V if abs(p.x) < 0.006 and 0.5 < p.z < hip_z), key=lambda p: p.z)
m["crotch_height"] = crotch.z
m["leg_ratio"] = m["crotch_height"] / m["stature"]
m["suprasternale_height"] = bone_head("clavicle_l").z
m["torso_length"] = m["suprasternale_height"] - m["crotch_height"]
m["leg_to_torso"] = m["crotch_height"] / m["torso_length"]

# Face: head-mesh widths at fixed fractions between menton (0) and eye centre (1).
if eyes is not None:
    m["eye_height"] = ez

    def width_at(frac, front_of, band=0.006):
        """Head-mesh width at a height between menton (0) and eye centre (1), counting only
        vertices more than `front_of` metres in front of the head bone (keeps ears out)."""
        z = chin.z + frac * (ez - chin.z)
        pts = [p for p in head_v if abs(p.z - z) < band and p.y < head_y - front_of]
        return (max(p.x for p in pts) - min(p.x for p in pts)) if pts else float("nan")

    m["bizygomatic"] = max(width_at(f, 0.05) for f in (0.80, 0.85, 0.9))  # cheekbones
    m["bigonial"] = width_at(0.30, 0.0)  # jaw angles
    m["jaw_to_cheek"] = m["bigonial"] / m["bizygomatic"]
    m["eye_menton"] = ez - chin.z
    m["lower_face_index"] = m["eye_menton"] / m["bizygomatic"]

m = {k: round(v, 4) for k, v in m.items()}
for k, v in m.items():
    print(f"LANDMARK {k:22s} {v}")
if out_json:
    with open(out_json, "w") as f:
        json.dump(m, f, indent=1)
