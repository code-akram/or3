#!/usr/bin/env node
// GPU texture memory of a character's textures as the Air would hold them (G1, per-tier table):
//   node web/tools/texmem.mjs FILE... [--json]      (GLBs and sidecar PNGs)
//
// Per texture: its size and encoding, and the bytes of its full mip chain on the GPU
//   - KTX2 UASTC (Zstandard, data maps) -> ASTC 4x4 on Apple GPUs (three's KTX2Loader order): 1 byte/texel
//   - KTX2 ETC1S (base colour) -> ETC1 RGB (0.5 byte/texel), or ETC2 RGBA with alpha (1 byte/texel)
//   - PNG -> RGBA8 (4 bytes/texel) with a generated mip chain
// and, for comparison, the same texture as RGBA8 + mips (what a PNG GLB costs, and what a browser without
// compressed formats transcodes KTX2 to). The mip chain is the levels the KTX2 holds (encoder-generated), or
// the full chain for a PNG. Prints a table and totals; --json prints one JSON line.
import { readFile } from 'node:fs/promises';
import { basename } from 'node:path';
import { NodeIO } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';

const files = process.argv.slice(2).filter((a) => !a.startsWith('--'));
const asJson = process.argv.includes('--json');
if (!files.length) {
  console.error('usage: texmem.mjs FILE.glb|FILE.png ... [--json]');
  process.exit(2);
}

function chain(w, h, levels, bpt, block) {
  let b = 0;
  for (let l = 0; l < levels; l++) {
    const lw = Math.max(1, w >> l);
    const lh = Math.max(1, h >> l);
    b += (block ? Math.ceil(lw / 4) * 4 * Math.ceil(lh / 4) * 4 : lw * lh) * bpt;
  }
  return b;
}
const fullLevels = (w, h) => Math.floor(Math.log2(Math.max(w, h))) + 1;

/** { width, height, levels, kind, alpha } of a KTX2 file (header + the basic data format descriptor). */
function ktx2Info(buf) {
  const dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  const width = dv.getUint32(20, true);
  const height = dv.getUint32(24, true);
  const levels = Math.max(1, dv.getUint32(40, true));
  const scheme = dv.getUint32(44, true);
  const dfdOff = dv.getUint32(48, true);
  // DFD: totalSize u32, then the basic block: vendor/type u32, version/blockSize u32, colorModel u8, ...
  const blockSize = dv.getUint16(dfdOff + 4 + 6, true);
  const model = dv.getUint8(dfdOff + 4 + 8);
  const nSamples = Math.max(0, (blockSize - 24) / 16);
  const ch = (i) => dv.getUint8(dfdOff + 4 + 24 + i * 16 + 3) & 0x0f;
  let kind = 'ktx2';
  let alpha = false;
  if (model === 163 || scheme === 1) {
    kind = 'etc1s';
    alpha = nSamples > 1; // RGB slice + AAA slice
  } else if (model === 166 || scheme === 2) {
    kind = 'uastc';
    alpha = nSamples > 0 && [3, 5].includes(ch(0)); // RGBA / RRRG
  }
  return { width, height, levels, kind, alpha };
}

function pngSize(buf) {
  const dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  return { width: dv.getUint32(16), height: dv.getUint32(20) };
}

function row(file, name, mime, buf) {
  if (mime === 'image/ktx2') {
    const k = ktx2Info(buf);
    const bpt = k.kind === 'uastc' ? 1 : k.alpha ? 1 : 0.5;
    return { file, name, enc: `${k.kind}${k.alpha ? '+a' : ''}`, size: [k.width, k.height], gpu: k.kind === 'uastc' ? 'astc-4x4' : k.alpha ? 'etc2-rgba8' : 'etc2-rgb8', air_mb: chain(k.width, k.height, k.levels, bpt, true) / 1e6, rgba8_mb: chain(k.width, k.height, fullLevels(k.width, k.height), 4, false) / 1e6, file_mb: buf.byteLength / 1e6 };
  }
  const p = pngSize(buf);
  const mb = chain(p.width, p.height, fullLevels(p.width, p.height), 4, false) / 1e6;
  return { file, name, enc: 'png', size: [p.width, p.height], gpu: 'rgba8', air_mb: mb, rgba8_mb: mb, file_mb: buf.byteLength / 1e6 };
}

const io = new NodeIO().registerExtensions(ALL_EXTENSIONS);
const rows = [];
for (const f of files) {
  const buf = new Uint8Array(await readFile(f));
  if (f.endsWith('.png')) {
    rows.push(row(basename(f), basename(f), 'image/png', buf));
    continue;
  }
  const doc = await io.readBinary(buf);
  for (const t of doc.getRoot().listTextures()) rows.push(row(basename(f), t.getName(), t.getMimeType(), t.getImage()));
}
const tot = (k, pred = () => true) => +rows.filter(pred).reduce((s, r) => s + r[k], 0).toFixed(1);
const out = {
  textures: rows.length,
  air_mb: tot('air_mb'),
  rgba8_mb: tot('rgba8_mb'),
  file_mb: tot('file_mb'),
  by_file: Object.fromEntries([...new Set(rows.map((r) => r.file))].map((f) => [f, { textures: rows.filter((r) => r.file === f).length, air_mb: tot('air_mb', (r) => r.file === f), rgba8_mb: tot('rgba8_mb', (r) => r.file === f) }])),
  rows: rows.map((r) => ({ ...r, air_mb: +r.air_mb.toFixed(3), rgba8_mb: +r.rgba8_mb.toFixed(3), file_mb: +r.file_mb.toFixed(3) })),
};
if (asJson) console.log(JSON.stringify(out));
else {
  for (const r of out.rows) console.log(`${r.file.padEnd(28)} ${r.name.padEnd(24)} ${r.enc.padEnd(8)} ${`${r.size[0]}x${r.size[1]}`.padStart(10)} ${r.gpu.padEnd(10)} ${r.air_mb.toFixed(2).padStart(7)} MB  (rgba8 ${r.rgba8_mb.toFixed(1)})`);
  console.log(`total ${out.textures} textures: ${out.air_mb} MB on the GPU (Air formats), ${out.rgba8_mb} MB as RGBA8 + mips, ${out.file_mb} MB in the files`);
}
