"""Head and hand refinement on the staged body (m1 face-C fidelity push).

Runs after the suit has hidden the covered body polygons and after the hair
and beard are built (they sample the low-res surface, so their budgets and
collisions don't change). What it does, all driven by cfg["head"]["refine"]:

  1. subdivide     one level of grid subdivision on the face (head-weighted,
                   in front of the head joint) and on the hands; the scalp,
                   back of the head and neck keep their density. Skin weights
                   and UVs are interpolated. New vertices are offset toward a
                   smooth surface ("smooth"), so quads don't stay flat.
  2. replanarise   the look-spec §2.1 plane groups (head.planes + the plane
                   controls) are re-fitted on the dense mesh with a crisper
                   plateau edge, so the facets read instead of blending over a
                   few centimetres (head.md §7 option 1).
  3. sculpt        mid-frequency forms along the normal: knuckle bumps and
                   extensor tendons on the back of the hands, raised nail
                   plates, a slight lid-margin thickness. Fine detail (pores,
                   lines) lives in the baked normal map (skin_tex).
  4. uvs           the body's UV islands are re-packed into two maps: head
                   (face, scalp, ears, neck: the face island fills the height
                   of a 4k square) and hands. skin_tex bakes into them.

The face frame after staging comes from the fitted eye meshes (the eye
helpers are stripped at export). Everything is parameters in the JSON; the
face stays defined by the spec controls only (look-spec §2.4).
"""

import bmesh
import numpy as np

from . import head_shape

HAND_BONES = ("hand_", "index_", "middle_", "ring_", "pinky_", "thumb_")
FINGERS = ("index", "middle", "ring", "pinky")


# --- mesh access -----------------------------------------------------------------------------

def staged_body(b):
    return max((o for o in b.meshes() if "body" in o.vertex_groups),
               key=lambda o: len(o.data.vertices))


def find_eyes(b):
    return next((o for o in b.meshes() if "poly" in o.name or "eyes_hq" in o.name), None)


def eye_centres(eyes):
    """(left, right) eye centroids, world space (left = character's left, +x)."""
    co = np.array([(eyes.matrix_world @ v.co)[:] for v in eyes.data.vertices])
    return co[co[:, 0] > 0].mean(0), co[co[:, 0] < 0].mean(0)


def coords(obj):
    n = len(obj.data.vertices)
    co = np.empty(n * 3)
    obj.data.vertices.foreach_get("co", co)
    return co.reshape(n, 3)


def normals(obj):
    n = len(obj.data.vertices)
    out = np.empty(n * 3)
    obj.data.vertices.foreach_get("normal", out)
    return out.reshape(n, 3)


def set_coords(obj, co):
    obj.data.vertices.foreach_set("co", np.ascontiguousarray(co, dtype=np.float64).ravel())
    obj.data.update()


def group_weights(obj, name):
    w = np.zeros(len(obj.data.vertices))
    g = obj.vertex_groups.get(name)
    if g is None:
        return w
    gi = g.index
    for v in obj.data.vertices:
        for vg in v.groups:
            if vg.group == gi:
                w[v.index] = vg.weight
                break
    return w


def dominant_bones(obj, bones):
    names = {g.index: g.name for g in obj.vertex_groups}
    out = []
    for v in obj.data.vertices:
        best, bw = "", 0.0
        for g in v.groups:
            n = names.get(g.group)
            if n in bones and g.weight > bw:
                best, bw = n, g.weight
        out.append(best)
    return np.array(out)


def is_hand_bone(name):
    return any(name.startswith(p) for p in HAND_BONES)


def classify(body, arm):
    """Per-vertex region labels: 'face', 'head' (scalp/back), 'neck', 'hand', ''."""
    bones = set(arm.data.bones.keys())
    dom = dominant_bones(body, bones)
    co = coords(body)
    head_y = (arm.matrix_world @ arm.data.bones["head"].head_local).y
    ears = group_weights(body, "ears") > 0
    scalp = group_weights(body, "scalp") > 0
    lab = np.full(len(co), "", dtype=object)
    is_hand = np.array([is_hand_bone(d) for d in dom])
    lab[is_hand] = "hand"
    lab[dom == "neck_01"] = "neck"
    head = dom == "head"
    lab[head] = "head"
    face = head & (co[:, 1] < head_y - 0.015) & ~scalp
    lab[face] = "face"
    lab[head & ears] = "head"
    return lab, dom


# --- 1. subdivision ---------------------------------------------------------------------------

def subdivide(body, select, smooth):
    """Grid-subdivide the faces whose vertices are all selected (bool per
    vertex); border faces get split where their edges are. Interpolates
    UVs and the deform layer (skin weights)."""
    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.verts.ensure_lookup_table()
    edges = [e for e in bm.edges if select[e.verts[0].index] and select[e.verts[1].index]]
    before = len(bm.faces)
    bmesh.ops.subdivide_edges(bm, edges=edges, cuts=1, use_grid_fill=True, smooth=smooth,
                              use_only_quads=False)
    # Border quads with one split edge become 5-gons whose new vertex is
    # (nearly) collinear with its neighbours; the glTF exporter's ear-clip
    # triangulation can then emit a zero-area sliver and a zero tangent
    # (validator ACCESSOR_VECTOR3_NON_UNIT). Triangulate them here instead.
    ngons = [f for f in bm.faces if len(f.verts) > 4]
    if ngons:
        bmesh.ops.triangulate(bm, faces=ngons, quad_method="BEAUTY", ngon_method="BEAUTY")
    after = len(bm.faces)
    bm.to_mesh(body.data)
    bm.free()
    body.data.update()
    for p in body.data.polygons:
        p.use_smooth = True
    return before, after


# --- 2. re-planarisation --------------------------------------------------------------------

def replanarise(body, eyes, cfg_head, rcfg):
    """Re-fit the plane groups on the dense mesh. Blends come from head.planes
    and the plane controls (as head_shape.apply resolves them), scaled by
    refine.replanarise; the plateau edge uses refine.plane_sharp."""
    scale = float(rcfg.get("replanarise", 0.0))
    if not scale:
        return None
    planes = dict(cfg_head.get("planes") or {})
    ctl = cfg_head.get("edits") or {}
    for c, groups in head_shape.PLANE_CONTROLS.items():
        if ctl.get(c):
            for g in groups:
                planes[g] = max(planes.get(g, 0.0), float(ctl[c]))
    planes = {k: min(1.0, v * scale) for k, v in planes.items() if v}
    if not planes:
        return None
    co = coords(body)
    cl, cr = eye_centres(eyes)
    fr = head_shape.Frame(co, cl, cr)
    near_eye = np.minimum(np.linalg.norm(co - cl, axis=1), np.linalg.norm(co - cr, axis=1)) < 0.020 * fr.s
    lips = group_weights(body, "lips") > 0
    out = head_shape.planarise(fr, co, planes, near_eye | lips, sharp=float(rcfg.get("plane_sharp", 3.0)))
    set_coords(body, out)
    moved = np.linalg.norm(out - co, axis=1)
    return {"planes": planes, "max_move_mm": round(float(moved.max()) * 1000, 2),
            "verts_moved_over_0.1mm": int((moved > 1e-4).sum())}


# --- 3. mid-frequency sculpt ----------------------------------------------------------------

def hand_frames(arm):
    """Per side: finger direction, back-of-hand direction, joint positions."""
    mw = arm.matrix_world
    out = {}
    for side in ("l", "r"):
        def head(n, side=side):
            return np.array((mw @ arm.data.bones[f"{n}_{side}"].head_local)[:])
        wrist = head("hand")
        mcp = {f: head(f"{f}_01") for f in FINGERS}
        pip = {f: head(f"{f}_02") for f in FINGERS}
        dip = {f: head(f"{f}_03") for f in FINGERS}
        fingers = mcp["middle"] - wrist
        fingers /= np.linalg.norm(fingers)
        across = mcp["pinky"] - mcp["index"]
        across -= fingers * across.dot(fingers)
        across /= np.linalg.norm(across)
        back = np.cross(fingers, across)
        # The thumb root sits on the palm side of the hand's mid-plane.
        if (head("thumb_01") - wrist).dot(back) > 0:
            back = -back
        out[side] = {"wrist": wrist, "mcp": mcp, "pip": pip, "dip": dip,
                     "fingers": fingers, "across": across, "back": back,
                     "thumb": [head("thumb_01"), head("thumb_02"), head("thumb_03")]}
    return out


def seg_dist(p, a, b):
    """Distance from points p (n,3) to segment ab, and the parameter t."""
    ab = b - a
    t = np.clip(((p - a) @ ab) / max(ab.dot(ab), 1e-12), 0.0, 1.0)
    d = np.linalg.norm(p - (a + t[:, None] * ab[None, :]), axis=1)
    return d, t


def sculpt(body, arm, eyes, lab, scfg):
    """Displace along vertex normals (metres). Returns per-form max mm."""
    if not scfg:
        return None
    co = coords(body)
    nr = normals(body)
    disp = np.zeros(len(co))
    hands = lab == "hand"
    hf = hand_frames(arm)
    mm = 0.001
    report = {}

    k = float(scfg.get("knuckle_mm", 0.0))
    t = float(scfg.get("tendon_mm", 0.0))
    if hands.any() and (k or t):
        for f in hf.values():
            facing = nr @ f["back"]           # > 0: back of the hand
            w_back = np.clip(facing, 0.0, 1.0) ** 1.5
            if k:
                for fi, name in enumerate(FINGERS):
                    for joint, amp, r in ((f["mcp"][name], 1.0, 0.0085), (f["pip"][name], 0.55, 0.0055),
                                          (f["dip"][name], 0.3, 0.0045)):
                        # Knuckle: the joint head sits on the bone axis; the bump
                        # is centred slightly back of it (on the skin).
                        c = joint + f["back"] * 0.004
                        d2 = ((co - c) ** 2).sum(1)
                        disp += k * mm * amp * np.exp(-0.5 * d2 / (r * r)) * w_back
                        if joint is f["dip"][name]:
                            continue
                        # Crease across the joint on the back: a shallow
                        # groove just distal of the bump (skin folds over the
                        # joint when the finger straightens).
                        wide = 0.006 if joint is f["mcp"][name] else 0.0045
                        g = joint + f["back"] * 0.004 + f["fingers"] * (0.007 if wide > 0.005 else 0.005)
                        along = (co - g) @ f["fingers"]
                        across = np.linalg.norm(co - g - np.outer(along, f["fingers"]), axis=1)
                        disp -= 0.3 * k * mm * amp * np.exp(-0.5 * (along / 0.0012) ** 2) \
                            * np.exp(-0.5 * (across / wide) ** 2) * w_back
            if t:
                for name in FINGERS:
                    a = f["wrist"] + f["fingers"] * 0.02 + f["back"] * 0.006
                    bpt = f["mcp"][name] + f["back"] * 0.004 - f["fingers"] * 0.012
                    d, tt = seg_dist(co, a, bpt)
                    prof = np.exp(-0.5 * (d / 0.0028) ** 2)
                    fade = np.sin(np.pi * tt) ** 0.6
                    disp += t * mm * prof * fade * w_back
        report["knuckle_mm"] = k
        report["tendon_mm"] = t

    n = float(scfg.get("nail_mm", 0.0))
    if n:
        w = group_weights(body, "fingernails")
        disp += n * mm * w
        report["nail_mm"] = n

    lid = float(scfg.get("lid_margin_mm", 0.0))
    if lid and eyes is not None:
        cl, cr = eye_centres(eyes)
        eco = np.array([(eyes.matrix_world @ v.co)[:] for v in eyes.data.vertices])
        r_eye = float(np.linalg.norm(eco[eco[:, 0] > 0] - cl, axis=1).max())
        for c in (cl, cr):
            d = np.linalg.norm(co - c, axis=1)
            to_eye = (c - co) / np.maximum(d, 1e-9)[:, None]
            inward = np.clip((nr * to_eye).sum(1), 0.0, 1.0)
            # Lid margin: just outside the eyeball, facing it: push outward
            # (away from the eye) a little so the lid edge has thickness.
            band = np.exp(-0.5 * ((d - r_eye - 0.0015) / 0.0015) ** 2)
            disp -= lid * mm * band * inward
        report["lid_margin_mm"] = lid

    if np.any(disp):
        set_coords(body, co + nr * disp[:, None])
    report["max_mm"] = round(float(np.abs(disp).max()) * 1000, 3)
    return report


# --- 4. UV re-pack ---------------------------------------------------------------------------

def uv_islands(me, uv_name):
    """Face index lists of the UV islands (faces connected through edges whose
    loops agree in UV on both sides)."""
    uv = me.uv_layers[uv_name].data
    n = len(me.polygons)
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    # (vertex, rounded uv) -> faces, per edge
    edge_faces = {}
    for p in me.polygons:
        li = list(p.loop_indices)
        for a, bq in zip(li, li[1:] + li[:1]):
            va, vb = me.loops[a].vertex_index, me.loops[bq].vertex_index
            ka = (va, round(uv[a].uv[0], 5), round(uv[a].uv[1], 5))
            kb = (vb, round(uv[bq].uv[0], 5), round(uv[bq].uv[1], 5))
            key = (ka, kb) if ka < kb else (kb, ka)
            edge_faces.setdefault(key, []).append(p.index)
    for faces in edge_faces.values():
        for f in faces[1:]:
            ra, rb = find(faces[0]), find(f)
            if ra != rb:
                parent[rb] = ra
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def guillotine_pack(rects, pad):
    """Pack (w, h) rects into the unit square at scale 1 if possible.
    Returns [(x, y)] or None. Best-area-fit guillotine, largest first."""
    free = [(0.0, 0.0, 1.0, 1.0)]
    order = sorted(range(len(rects)), key=lambda i: -(rects[i][0] * rects[i][1]))
    pos = [None] * len(rects)
    for i in order:
        w, h = rects[i][0] + pad, rects[i][1] + pad
        best = None
        for j, (fx, fy, fw, fh) in enumerate(free):
            if w <= fw and h <= fh:
                waste = fw * fh - w * h
                if best is None or waste < best[0]:
                    best = (waste, j)
        if best is None:
            return None
        fx, fy, fw, fh = free.pop(best[1])
        pos[i] = (fx, fy)
        # Split the remaining L into two rects (shorter-leftover axis split).
        right = (fx + w, fy, fw - w, h)
        top = (fx, fy + h, fw, fh - h)
        if fw - w > fh - h:
            right = (fx + w, fy, fw - w, fh)
            top = (fx, fy + h, w, fh - h)
        for r in (right, top):
            if r[2] > 1e-6 and r[3] > 1e-6:
                free.append(r)
    return pos


def repack(me, uv_name, face_sets, px, pad_px=8):
    """Re-pack the islands made of the faces in face_sets (list of face index
    lists, one entry per output map) into the unit square each, writing the
    UVs in place. Returns per map: scale, islands, texel density proxy."""
    uv = me.uv_layers[uv_name].data
    islands = uv_islands(me, uv_name)
    out = []
    for faces, size in zip(face_sets, px):
        fset = set(faces)
        mine = [isl for isl in islands if isl[0] in fset]
        boxes = []
        for isl in mine:
            pts = np.array([uv[li].uv[:] for f in isl for li in me.polygons[f].loop_indices])
            boxes.append((pts.min(0), pts.max(0)))
        pad = pad_px / size
        lo, hi = 0.05, 20.0
        for _ in range(40):  # bisection on the common scale
            s = (lo + hi) / 2
            rects = [((b[1][0] - b[0][0]) * s, (b[1][1] - b[0][1]) * s) for b in boxes]
            if guillotine_pack(rects, pad) is not None:
                lo = s
            else:
                hi = s
        s = lo
        rects = [((b[1][0] - b[0][0]) * s, (b[1][1] - b[0][1]) * s) for b in boxes]
        pos = guillotine_pack(rects, pad)
        for isl, (bmin, _), (x, y) in zip(mine, boxes, pos):
            for f in isl:
                for li in me.polygons[f].loop_indices:
                    u, v = uv[li].uv
                    uv[li].uv = ((u - bmin[0]) * s + x + pad / 2, (v - bmin[1]) * s + y + pad / 2)
        out.append({"scale": round(s, 4), "islands": len(mine), "px": size})
    return out


def repack_uvs(body, lab, rcfg):
    """Head islands into map 0, hand islands into map 1; assigns material
    slots 0 / 1 per face (skin_tex fills them)."""
    me = body.data
    uv_name = me.uv_layers.active.name
    head_faces, hand_faces = [], []
    for p in me.polygons:
        if all(lab[v] == "hand" for v in p.vertices) or sum(lab[v] == "hand" for v in p.vertices) > len(p.vertices) / 2:
            hand_faces.append(p.index)
        else:
            head_faces.append(p.index)
    # Islands are whole: a face set is extended to the islands it touches.
    info = repack(me, uv_name, [head_faces, hand_faces],
                  [int(rcfg.get("head_px", 4096)), int(rcfg.get("hands_px", 2048))])
    hand_set = set(hand_faces)
    for p in me.polygons:
        p.material_index = 1 if p.index in hand_set else 0
    return {"head": info[0], "hands": info[1], "uv_layer": uv_name,
            "faces": {"head": len(head_faces), "hands": len(hand_faces)}}


# --- stage -----------------------------------------------------------------------------------

def refine(b):
    rcfg = b.cfg["head"].get("refine") or {}
    if not rcfg or not rcfg.get("enabled", True):
        return
    body = staged_body(b)
    arm = b.armature()
    eyes = find_eyes(b)
    notes = {}
    lab, _ = classify(body, arm)
    sub = rcfg.get("subdiv") or {}
    sel = np.zeros(len(lab), dtype=bool)
    if sub.get("face"):
        sel |= lab == "face"
    if sub.get("hands"):
        sel |= lab == "hand"
    if sel.any():
        before, after = subdivide(body, sel, float(sub.get("smooth", 0.5)))
        notes["subdiv"] = {"faces_before": before, "faces_after": after,
                           "regions": {k: int((lab == k).sum()) for k in ("face", "head", "neck", "hand")}}
        lab, _ = classify(body, arm)  # new vertices
    if eyes is not None:
        r = replanarise(body, eyes, b.cfg["head"], rcfg)
        if r:
            notes["replanarise"] = r
    from . import head_sculpt
    r = head_sculpt.refine(b, body, lab, eyes)  # crisp band of the bony fields (head_sculpt.py)
    if r:
        notes["head_sculpt"] = r
    s = sculpt(body, arm, eyes, lab, rcfg.get("sculpt"))
    if s:
        notes["sculpt"] = s
    if rcfg.get("uv", True):
        notes["uv"] = repack_uvs(body, lab, rcfg.get("uv_px") or {})
    b.notes["head_refine"] = notes
    b.refine_labels = lab
    return notes
