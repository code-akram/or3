#!/usr/bin/env python3
"""Attribute WASM code bytes to crates using the `name` section.

Run on the cargo output (before wasm-bindgen/wasm-opt strip names):

    python3 -I bench/wasm-size.py target/wasm32-unknown-unknown/wasm/game_core.wasm

Attribution is by the earliest known crate path found in each (mangled) function name, so generic
code is credited to whichever crate's path appears first. Good enough to see what dominates.
"""
import collections
import re
import sys

CRATES = [
    "rapier3d", "parry3d", "nalgebra", "glamx", "glam", "simba", "wide", "game_core",
    "wasm_bindgen", "dlmalloc", "hashbrown", "smallvec", "arrayvec", "spade", "ordered_float",
    "num_traits", "core", "alloc", "std",
]


def leb(b, i):
    r = s = 0
    while True:
        x = b[i]
        i += 1
        r |= (x & 0x7F) << s
        s += 7
        if x < 0x80:
            return r, i


def main(path):
    d = open(path, "rb").read()
    i = 8
    sections = []
    while i < len(d):
        sid = d[i]
        size, i = leb(d, i + 1)
        sections.append((sid, i, size))
        i += size

    n_imported_funcs = 0
    names = {}
    bodies = []
    sec = collections.Counter()
    for sid, off, size in sections:
        if sid == 0:
            nl, j = leb(d, off)
            nm = d[j : j + nl].decode()
            sec["custom:" + nm] += size
            if nm == "name":
                j += nl
                end = off + size
                while j < end:
                    sub = d[j]
                    ss, j = leb(d, j + 1)
                    se = j + ss
                    if sub == 1:
                        cnt, j = leb(d, j)
                        for _ in range(cnt):
                            idx, j = leb(d, j)
                            ln, j = leb(d, j)
                            names[idx] = d[j : j + ln].decode("utf8", "replace")
                            j += ln
                    j = se
            continue
        sec[{1: "type", 2: "import", 3: "func", 5: "memory", 6: "global", 7: "export", 9: "elem", 10: "code", 11: "data"}.get(sid, str(sid))] += size
        if sid == 2:
            cnt, j = leb(d, off)
            for _ in range(cnt):
                ln, j = leb(d, j)
                j += ln
                ln, j = leb(d, j)
                j += ln
                kind = d[j]
                j += 1
                if kind == 0:
                    _, j = leb(d, j)
                    n_imported_funcs += 1
                elif kind == 1:
                    j += 1
                    fl, j = leb(d, j)
                    _, j = leb(d, j)
                    if fl & 1:
                        _, j = leb(d, j)
                elif kind == 2:
                    fl, j = leb(d, j)
                    _, j = leb(d, j)
                    if fl & 1:
                        _, j = leb(d, j)
                elif kind == 3:
                    j += 2
        if sid == 10:
            cnt, j = leb(d, off)
            for k in range(cnt):
                sz, j = leb(d, j)
                bodies.append((n_imported_funcs + k, sz))
                j += sz

    by_crate = collections.Counter()
    total = 0
    for idx, sz in bodies:
        n = names.get(idx, "?")
        total += sz
        # Earliest crate path in the name wins (legacy `_ZN8rapier3d`, v0 `_8rapier3d`, or demangled).
        key, best = "other", len(n) + 1
        for c in CRATES:
            m = re.search(r"(?<![0-9])" + str(len(c)) + c + r"(?![a-z_])|(?<![a-z_])" + c + "::", n)
            if m and m.start() < best:
                key, best = c, m.start()
        by_crate[key] += sz
    print(f"file {len(d)} bytes; sections: " + ", ".join(f"{k}={v}" for k, v in sec.most_common()))
    print(f"code {total} bytes in {len(bodies)} functions")
    for k, v in by_crate.most_common():
        print(f"  {k:14s} {v:9d} {100 * v / total:5.1f}%")


if __name__ == "__main__":
    main(sys.argv[1])
