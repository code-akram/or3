"""Track T2 evidence: read a character GLB (no Blender) and check

  materials   which images feed each suit material (base colour, ORM, occlusion)
  atlas       the facial-hair atlases' stored texels against the linear values the
              build recorded (character.stats.json: atlas_fill_linear,
              card_fill_linear; the lash colour from the config): is the PNG
              sRGB-encoded or linear-in-sRGB?
  same A B    whether two GLBs carry identical vertex data (POSITION, NORMAL,
              indices, ...) for every mesh, or only the meshes named.

Usage (python3 -I):
  t2_glb_check.py materials RUN_DIR
  t2_glb_check.py atlas RUN_DIR [--json OUT]
  t2_glb_check.py same RUN_A RUN_B [mesh substring ...]
"""

import json
import struct
import subprocess
import sys
from pathlib import Path

import numpy as np


def load_glb(path):
    b = Path(path).read_bytes()
    assert b[:4] == b"glTF", path
    off, js, binc = 12, None, None
    while off < len(b):
        ln, typ = struct.unpack("<I4s", b[off:off + 8])
        chunk = b[off + 8:off + 8 + ln]
        if typ == b"JSON":
            js = json.loads(chunk)
        elif typ == b"BIN\x00":
            binc = chunk
        off += 8 + ln
    return js, binc


def view_bytes(js, binc, vi):
    v = js["bufferViews"][vi]
    o = v.get("byteOffset", 0)
    return binc[o:o + v["byteLength"]]


CT = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def accessor(js, binc, ai):
    a = js["accessors"][ai]
    v = js["bufferViews"][a["bufferView"]]
    dt = np.dtype(CT[a["componentType"]])
    nc = NC[a["type"]]
    stride = v.get("byteStride", 0) or dt.itemsize * nc
    raw = view_bytes(js, binc, a["bufferView"])[a.get("byteOffset", 0):]
    arr = np.ndarray((a["count"], nc), dtype=dt, buffer=raw, strides=(stride, dt.itemsize))
    return np.array(arr)


def png_decode(data):
    """PNG -> (H, W, 4) uint8 RGBA, row 0 = top (ImageMagick does the decode;
    raw output, no colour management)."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = struct.unpack(">II", data[16:24])
    raw = subprocess.run(["magick", "png:-", "-depth", "8", "rgba:-"], input=data,
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(h, w, 4)


def image(js, binc, name):
    for im in js["images"]:
        if im.get("name") == name:
            return png_decode(view_bytes(js, binc, im["bufferView"]))
    raise KeyError(name)


def tex_image_name(js, ref):
    if not ref:
        return None
    return js["images"][js["textures"][ref["index"]]["source"]].get("name")


def cmd_materials(run):
    js, _ = load_glb(Path(run) / "character.glb")
    mats = {}
    for mesh in js["meshes"]:
        for p in mesh["primitives"]:
            if "material" in p:
                mats.setdefault(p["material"], []).append(mesh["name"])
    out = {}
    for i, m in enumerate(js["materials"]):
        if not m["name"].startswith("suit_"):
            continue
        pbr = m.get("pbrMetallicRoughness", {})
        out[m["name"]] = {
            "meshes": mats.get(i, []),
            "baseColor": tex_image_name(js, pbr.get("baseColorTexture")),
            "metallicRoughness": tex_image_name(js, pbr.get("metallicRoughnessTexture")),
            "occlusion": tex_image_name(js, m.get("occlusionTexture")),
            "normal": tex_image_name(js, m.get("normalTexture")),
        }
    print(json.dumps(out, indent=1))
    return out


def srgb(lin):
    lin = np.asarray(lin, float)
    return np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.power(np.maximum(lin, 0), 1 / 2.4) - 0.055)


def to_linear(s):
    s = np.asarray(s, float)
    return np.where(s <= 0.04045, s / 12.92, ((s + 0.055) / 1.055) ** 2.4)


def hex_rgb(h):
    return np.array([int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)])


def cmd_atlas(run, out_json=None):
    run = Path(run)
    js, binc = load_glb(run / "character.glb")
    st = json.loads((run / "character.stats.json").read_text())
    lash_hex = st["config"]["hair"]["lashes"]["color"]
    checks = [("beard_atlas", st["beard"]["atlas_fill_linear"] if "atlas_fill_linear" in st["beard"] else None),
              ("beard_cards", st["beard"].get("card_fill_linear")),
              ("brows_atlas", st["brows"].get("atlas_fill_linear")),
              ("brows_cards", st["brows"].get("card_fill_linear")),
              ("eyelash_cards_atlas", list(to_linear(hex_rgb(lash_hex))))]
    res = {}
    for name, fill in checks:
        px = image(js, binc, name)
        a = px[..., 3]
        rgb = px[..., :3].astype(float) / 255
        clear = a == 0
        r = {"size": [px.shape[1], px.shape[0]], "transparent_px": int(clear.sum())}
        if clear.any():
            vals, counts = np.unique(px[..., :3][clear], axis=0, return_counts=True)
            r["transparent_rgb_mode"] = vals[counts.argmax()].tolist()
        if fill is not None:
            fill = np.asarray(fill, float)
            r["fill_linear"] = [round(x, 5) for x in fill]
            r["expect_srgb_bytes"] = np.round(255 * srgb(fill)).astype(int).tolist()
            r["expect_if_linear_stored"] = np.round(255 * fill).astype(int).tolist()
            if clear.any():
                m = np.asarray(r["transparent_rgb_mode"])
                r["encoding"] = ("sRGB (correct)" if np.abs(m - r["expect_srgb_bytes"]).max() <= 1 else
                                 "linear in sRGB (bug)" if np.abs(m - r["expect_if_linear_stored"]).max() <= 1
                                 else "neither")
        # opaque hair texels: what a renderer decodes (linear), and how many
        # byte levels the dark half uses (banding)
        op = a >= 128
        if op.any():
            lin = to_linear(rgb[op])
            r["opaque_px"] = int(op.sum())
            r["opaque_mean_linear"] = [round(float(x), 5) for x in lin.mean(0)]
            r["opaque_mean_srgb_hex"] = "#" + "".join(f"{int(round(255 * float(x))):02x}" for x in srgb(lin.mean(0)))
            r["opaque_median_linear"] = [round(float(x), 5) for x in np.median(lin, 0)]
            r["opaque_red_byte_levels"] = int(len(np.unique(px[..., 0][op])))
            # stored colour at the 10th / 50th / 90th luminance percentile
            lum = lin @ np.array([0.2126, 0.7152, 0.0722])
            order = np.argsort(lum, kind="stable")
            r["opaque_srgb_hex_p10_p50_p90"] = [
                "#" + "".join(f"{int(x):02x}" for x in px[..., :3][op][order[int(q * (len(order) - 1))]])
                for q in (0.1, 0.5, 0.9)]
            r["opaque_dark_share"] = round(float((lum < 0.06).mean()), 4)
        res[name] = r
    print(json.dumps(res, indent=1))
    if out_json:
        Path(out_json).write_text(json.dumps(res, indent=1))
    return res


ATTRS = ("POSITION", "NORMAL", "TEXCOORD_0", "JOINTS_0", "WEIGHTS_0")


def cmd_same(ra, rb, names):
    ja, ba = load_glb(Path(ra) / "character.glb")
    jb, bb = load_glb(Path(rb) / "character.glb")
    ma = {m["name"]: m for m in ja["meshes"]}
    mb = {m["name"]: m for m in jb["meshes"]}
    sel = [n for n in ma if not names or any(s in n for s in names)]
    ok_all = True
    for n in sel:
        if n not in mb:
            print(f"{n}: missing in B")
            ok_all = False
            continue
        pa, pb = ma[n]["primitives"], mb[n]["primitives"]
        if len(pa) != len(pb):
            print(f"{n}: primitive count {len(pa)} vs {len(pb)}")
            ok_all = False
            continue
        rep = []
        for k, (x, y) in enumerate(zip(pa, pb)):
            for at in ATTRS:
                if at not in x["attributes"]:
                    continue
                A = accessor(ja, ba, x["attributes"][at])
                B = accessor(jb, bb, y["attributes"][at])
                if A.shape != B.shape:
                    rep.append(f"p{k} {at} shape {A.shape} vs {B.shape}")
                elif not np.array_equal(A, B):
                    d = np.abs(A.astype(float) - B.astype(float))
                    rep.append(f"p{k} {at} differs: {int((d.max(1) > 0).sum())}/{len(A)} rows, max {d.max():.3g}")
            if "indices" in x:
                A, B = accessor(ja, ba, x["indices"]), accessor(jb, bb, y["indices"])
                if A.shape != B.shape or not np.array_equal(A, B):
                    rep.append(f"p{k} indices differ")
        nv = sum(ja["accessors"][p["attributes"]["POSITION"]]["count"] for p in pa)
        print(f"{n}: {'IDENTICAL' if not rep else 'DIFFERENT'} ({nv} verts)" + ("".join("\n  " + r for r in rep)))
        ok_all &= not rep
    print("ALL IDENTICAL" if ok_all else "SOME DIFFER")
    return ok_all


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[0] == "materials":
        cmd_materials(a[1])
    elif a[0] == "atlas":
        cmd_atlas(a[1], a[3] if len(a) > 3 and a[2] == "--json" else None)
    elif a[0] == "same":
        sys.exit(0 if cmd_same(a[1], a[2], a[3:]) else 1)
