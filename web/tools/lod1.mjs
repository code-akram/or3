#!/usr/bin/env node
// LOD1 of a character GLB for the gameplay tier (T24, bench/m1/v4/checkpoint-3.md §5.2: ~60k tris, cap 65k):
//   node web/tools/lod1.mjs IN.glb OUT.glb [--stats character.stats.json] [--budget 65000] [--hair-drop fly,flyone]
//
// Per primitive a target triangle count (TARGETS below, by node + material), reached with meshoptimizer's
// simplifyWithAttributes (edge collapse onto existing vertices: positions, skin weights and the corrective
// morph targets of the kept vertices stay exact, only the index buffer changes; UV seams are detected by
// position and kept). Before that the scalp hair drops whole cards by their atlas cell: the fly-aways
// (`fly*`, 1-strand `flyone*`, which also hold the 90 baby hairs) go, the core (under / lock / front /
// hairline) and the T20 outer layer stay and are shortened in segments instead. The cells come from the
// build's character.stats.json (hair.atlas.cells, next to IN by default). Unreferenced vertices are
// compacted out of every attribute and morph target. Textures pass through untouched, so a KTX2 input
// (character.ktx2.glb) gives a KTX2 LOD1 (character.lod1.ktx2.glb), the gate asset. Since G1 the export
// (blender/character/export.py lod1()) runs this on the PNG GLB, then web/tools/texlod.mjs (textures cut to
// the 3-8 m camera's texel density), then ktx2.mjs, so the gameplay tier's textures are reduced too.
// Prints one JSON line: per primitive before / after, the total, and whether it is within --budget.
// The suit targets stand in until T13b's own suit LODs are in the build (then they are taken as exported).
import { readFile, writeFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { NodeIO, VertexLayout } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import { MeshoptSimplifier } from 'meshoptimizer';

const argv = process.argv.slice(2);
const [src, dst] = argv.filter((a, i) => !a.startsWith('--') && !(i > 0 && argv[i - 1].startsWith('--')));
const opt = (n, d) => {
  const i = argv.indexOf(`--${n}`);
  return i >= 0 ? argv[i + 1] : d;
};
if (!src || !dst) {
  console.error('usage: lod1.mjs IN.glb OUT.glb [--stats character.stats.json] [--budget 65000] [--hair-drop fly,flyone]');
  process.exit(2);
}
const budget = Number(opt('budget', 65000));
const hairDrop = opt('hair-drop', 'fly,flyone').split(',').filter(Boolean);

/** Target tris per primitive: [node regex, material regex | null, target tris]; first match wins; no
 * match = kept as is. ~58k in all on the T20 build (166k): body 18k, suit 13k, hair 16k, beard 5k. */
const TARGETS = [
  [/^Human_export$/, /skin_head/, 10500],
  [/^Human_export$/, /skin_hands/, 7500],
  [/hair_export$/, /hair_cards/, 15500],
  [/hair_export$/, /^hair$/, 600],
  [/beard_export$/, null, 5000],
  [/eyes_hq_export$/, null, 2000],
  [/hand_nails_export$/, null, 600],
  [/suit_jacket_export$/, null, 6000],
  [/suit_shirt_export$/, null, 1400],
  [/suit_waistcoat_export$/, null, 1200],
  [/suit_trousers_export$/, null, 2000],
  [/suit_buttons_export$/, null, 700],
  [/suit_shoes_export$/, /leather/, 1200],
  [/suit_shoes_export$/, /sole/, 450],
  [/teeth_base_export$/, null, 300],
  [/tongue01_export$/, null, 200],
];

const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).setVertexLayout(VertexLayout.SEPARATE);
const doc = await io.readBinary(new Uint8Array(await readFile(src)));
await MeshoptSimplifier.ready;

// the hair atlas cells (u ranges in texels) whose cards LOD1 drops
const statsPath = opt('stats', join(dirname(src), 'character.stats.json'));
let dropRanges = [];
let atlasW = 2048;
if (existsSync(statsPath)) {
  const st = JSON.parse(await readFile(statsPath, 'utf8'));
  const atlas = st?.hair?.atlas;
  if (atlas?.cells) {
    atlasW = atlas.size[0];
    const kind = (name) => name.replace(/\d+$/, '');
    dropRanges = atlas.cells.filter((c) => hairDrop.includes(kind(c.cell))).map((c) => [c.x0, c.x0 + c.px[0], c.y0, c.y0 + c.px[1], c.cell]);
  }
}
if (!dropRanges.length && hairDrop.length) console.error(`[lod1] no hair atlas cells in ${statsPath}: no hair cards dropped`);

const rows = [];
for (const node of doc.getRoot().listNodes()) {
  const mesh = node.getMesh();
  if (!mesh) continue;
  for (const prim of mesh.listPrimitives()) {
    const name = node.getName();
    const mat = prim.getMaterial()?.getName() ?? '';
    const idxAcc = prim.getIndices();
    if (!idxAcc || prim.getMode() !== 4) continue;
    let indices = Uint32Array.from(idxAcc.getArray());
    const before = indices.length / 3;
    const rule = TARGETS.find(([n, m]) => n.test(name) && (!m || m.test(mat)));
    const row = { node: name, material: mat, before, after: before };
    // 1. hair: whole cards in the dropped cells (triangle UV centroid in the cell's texel range)
    if (/hair_export$/.test(name) && /hair_cards/.test(mat) && dropRanges.length) {
      // by column only: every dropped kind owns whole atlas columns (fly / flyone are full height)
      const uv = prim.getAttribute('TEXCOORD_0').getArray();
      const keep = [];
      let dropped = 0;
      for (let t = 0; t < indices.length; t += 3) {
        let u = 0;
        for (let k = 0; k < 3; k++) u += uv[indices[t + k] * 2] / 3;
        const x = u * atlasW;
        if (dropRanges.some(([x0, x1]) => x >= x0 && x < x1)) dropped++;
        else keep.push(indices[t], indices[t + 1], indices[t + 2]);
      }
      indices = Uint32Array.from(keep);
      row.dropped_cards_tris = dropped;
      row.dropped_cells = dropRanges.map((r) => r[4]);
    }
    // 2. simplify toward the target
    if (rule && indices.length / 3 > rule[2]) {
      const pos = prim.getAttribute('POSITION').getArray();
      const nrm = prim.getAttribute('NORMAL')?.getArray();
      const uv = prim.getAttribute('TEXCOORD_0')?.getArray();
      const nv = pos.length / 3;
      const stride = 5;
      const attr = new Float32Array(nv * stride);
      for (let i = 0; i < nv; i++) {
        if (nrm) attr.set([nrm[i * 3], nrm[i * 3 + 1], nrm[i * 3 + 2]], i * stride);
        if (uv) attr.set([uv[i * 2], uv[i * 2 + 1]], i * stride + 3);
      }
      // normals ~ shading, UVs light (seams are kept by position anyway)
      const weights = [0.5, 0.5, 0.5, 0.2, 0.2];
      const target = rule[2] * 3;
      let out = indices;
      let err = 0;
      for (const e of [0.01, 0.03, 0.08, 0.2]) {
        [out, err] = MeshoptSimplifier.simplifyWithAttributes(indices, Float32Array.from(pos), 3, attr, stride, weights, null, target, e, []);
        if (out.length <= target * 1.05) break;
      }
      indices = out;
      row.error = +err.toFixed(5);
      // meshopt error is relative to the primitive extent: in mm (glTF metres)
      row.error_mm = +(err * MeshoptSimplifier.getScale(Float32Array.from(pos), 3) * 1000).toFixed(2);
    }
    row.after = indices.length / 3;
    if (row.after !== before) setIndicesCompact(prim, indices);
    rows.push(row);
  }
}
// accessors left without a user (the replaced ones)
for (const a of doc.getRoot().listAccessors()) if (a.listParents().length <= 1) a.dispose();

const total = rows.reduce((s, r) => s + r.after, 0);
const totalBefore = rows.reduce((s, r) => s + r.before, 0);
await writeFile(dst, await io.writeBinary(doc));
const rec = { ok: total <= budget, in: src, out: dst, tris_before: totalBefore, tris: total, budget, hair_drop: hairDrop, primitives: rows };
console.log(JSON.stringify(rec));
process.exit(rec.ok ? 0 : 1);

/** Replace the primitive's indices and drop the vertices no triangle references any more (every
 * attribute and morph target attribute gathered through the same remap). */
function setIndicesCompact(prim, indices) {
  const nv = prim.getAttribute('POSITION').getCount();
  const remap = new Int32Array(nv).fill(-1);
  const order = [];
  for (const i of indices) if (remap[i] < 0) remap[i] = order.push(i) - 1;
  const gather = (acc) => {
    const n = acc.getElementSize();
    const a = acc.getArray();
    const outArr = new a.constructor(order.length * n);
    for (let k = 0; k < order.length; k++) for (let c = 0; c < n; c++) outArr[k * n + c] = a[order[k] * n + c];
    return acc.clone().setArray(outArr);
  };
  for (const sem of prim.listSemantics()) prim.setAttribute(sem, gather(prim.getAttribute(sem)));
  for (const t of prim.listTargets()) for (const sem of t.listSemantics()) t.setAttribute(sem, gather(t.getAttribute(sem)));
  const idx = new Uint32Array(indices.length);
  for (let k = 0; k < indices.length; k++) idx[k] = remap[indices[k]];
  const ia = prim.getIndices().clone().setArray(order.length < 65536 ? Uint16Array.from(idx) : idx);
  prim.setIndices(ia);
}
