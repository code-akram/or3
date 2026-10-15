#!/usr/bin/env node
// Per-primitive triangle / vertex / attribute counts of a GLB (LOD checks, T24):
//   node web/tools/glbinfo.mjs FILE.glb [--json]
import { readFile } from 'node:fs/promises';
import { NodeIO, VertexLayout } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';

const file = process.argv[2];
if (!file) {
  console.error('usage: glbinfo.mjs FILE.glb [--json]');
  process.exit(2);
}
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).setVertexLayout(VertexLayout.SEPARATE);
const doc = await io.readBinary(new Uint8Array(await readFile(file)));
const rows = [];
for (const n of doc.getRoot().listNodes()) {
  const m = n.getMesh();
  if (!m) continue;
  for (const p of m.listPrimitives()) {
    const idx = p.getIndices();
    const verts = p.getAttribute('POSITION').getCount();
    rows.push({ node: n.getName(), material: p.getMaterial()?.getName() ?? null, tris: (idx ? idx.getCount() : verts) / 3, verts, attributes: p.listSemantics(), targets: p.listTargets().length });
  }
}
const total = rows.reduce((s, r) => s + r.tris, 0);
if (process.argv.includes('--json')) console.log(JSON.stringify({ file, total_tris: total, primitives: rows }));
else {
  for (const r of rows) console.log(`${r.node.padEnd(34)} ${String(r.material).padEnd(16)} ${String(r.tris).padStart(7)} ${String(r.verts).padStart(7)}  ${r.attributes.join(',')}${r.targets ? `  targets ${r.targets}` : ''}`);
  console.log(`total ${total} tris`);
}
