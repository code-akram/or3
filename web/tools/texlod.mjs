#!/usr/bin/env node
// Texture LOD for the gameplay tier (G1, bench/m1/v4/g1-gameplay-grounding.md): every PNG texture of a GLB is
// halved until its top mip is no finer than the gameplay camera can sample at its closest.
//   node web/tools/texlod.mjs IN.glb OUT.glb [--px-per-m 450] [--margin 2] [--max-drop 4] [--min 256] [--sharp-levels 2] [--dry]
//
// The gameplay framing (tiers.ts gameplayCamera: 46 deg vertical FOV, 956 px internal height on the Air,
// 2.5-4 m, the game camera 3-8 m) puts 956 / (2 x 2.5 m x tan 23 deg) = 450 px on a metre at 2.5 m, its
// closest. A texture's density is the texels per metre of surface it lands on: per triangle
// sqrt(uv area x W x H / world area) (world positions through the node's world matrix, the texture's own
// texCoord set), the 90th percentile by area over every primitive whose material samples it. The texture
// keeps the largest power-of-two reduction whose density stays >= margin x px-per-m (margin 2: one mip of
// headroom for oblique surfaces under anisotropic filtering and the TAAU's negative bias). So the dropped
// levels are the ones trilinear filtering would not have read at >= 2.5 m: the 3 m frame is unchanged up to
// the filter, and memory and bandwidth drop with the square of the reduction. The card materials (hair,
// beard, brows, lashes: /cards/) read their strand ID and fibre colour at hair.idLodBias (-2, two mips
// sharper), so their textures keep --sharp-levels more.
//
// Filter: 2 x 2 box per halving, in linear light for the colour slots (baseColor, sheenColor, emissive,
// specularColor: sRGB), renormalised for normal maps, raw for data maps and alpha (the hair cards' hashed
// alpha is coverage: its mean is what a mip would hold). PNG only (run it before ktx2.mjs). Prints one JSON
// line: per texture its slots, density, size before / after, and the RGBA8 + mips MB before / after.
import { readFile, writeFile } from 'node:fs/promises';
import { NodeIO, VertexLayout } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import { PNG } from 'pngjs';

const argv = process.argv.slice(2);
const [src, dst] = argv.filter((a, i) => !a.startsWith('--') && !(i > 0 && argv[i - 1].startsWith('--') && argv[i - 1] !== '--dry'));
const opt = (n, d) => {
  const i = argv.indexOf(`--${n}`);
  return i >= 0 ? Number(argv[i + 1]) : d;
};
if (!src || !dst) {
  console.error('usage: texlod.mjs IN.glb OUT.glb [--px-per-m 450] [--margin 2] [--max-drop 4] [--min 256] [--dry]');
  process.exit(2);
}
const pxPerM = opt('px-per-m', 450);
const margin = opt('margin', 2);
const maxDrop = opt('max-drop', 4);
const minSize = opt('min', 256);
const sharpLevels = opt('sharp-levels', 2);
const SHARP = /cards/;
const dry = argv.includes('--dry');
const COLOUR = /^(baseColor|sheenColor|emissive|specularColor)Texture$/;
const NORMAL = /^(normal|clearcoatNormal)Texture$/;

const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).setVertexLayout(VertexLayout.SEPARATE);
const doc = await io.readBinary(new Uint8Array(await readFile(src)));
const root = doc.getRoot();

// texture -> [{ material, slot, texCoord }]
const uses = new Map();
for (const tex of root.listTextures()) {
  const list = [];
  for (const edge of doc.getGraph().listParentEdges(tex)) {
    const parent = edge.getParent();
    const slot = edge.getName();
    const info = parent[`get${slot[0].toUpperCase()}${slot.slice(1)}Info`]?.();
    const texCoord = info?.getTexCoord?.() ?? 0;
    // a material, or an extension property whose parent is the material
    const mats = parent.propertyType === 'Material' ? [parent] : parent.listParents().filter((p) => p.propertyType === 'Material');
    for (const m of mats) list.push({ material: m, slot, texCoord });
  }
  uses.set(tex, list);
}

// material + texCoord -> per-triangle (density^2 / texel area, world area) samples, from every primitive
const samples = new Map();
function trianglesOf(material, texCoord) {
  const key = `${material.getName()}|${texCoord}`;
  if (samples.has(key)) return samples.get(key);
  const out = [];
  for (const node of root.listNodes()) {
    const mesh = node.getMesh();
    if (!mesh) continue;
    const M = node.getWorldMatrix();
    for (const prim of mesh.listPrimitives()) {
      if (prim.getMaterial() !== material || prim.getMode() !== 4) continue;
      const pos = prim.getAttribute('POSITION')?.getArray();
      const uv = prim.getAttribute(`TEXCOORD_${texCoord}`)?.getArray();
      const idx = prim.getIndices()?.getArray();
      if (!pos || !uv || !idx) continue;
      const w = (i) => {
        const x = pos[i * 3];
        const y = pos[i * 3 + 1];
        const z = pos[i * 3 + 2];
        return [M[0] * x + M[4] * y + M[8] * z + M[12], M[1] * x + M[5] * y + M[9] * z + M[13], M[2] * x + M[6] * y + M[10] * z + M[14]];
      };
      for (let t = 0; t < idx.length; t += 3) {
        const [a, b, c] = [idx[t], idx[t + 1], idx[t + 2]];
        const [pa, pb, pc] = [w(a), w(b), w(c)];
        const e1 = [pb[0] - pa[0], pb[1] - pa[1], pb[2] - pa[2]];
        const e2 = [pc[0] - pa[0], pc[1] - pa[1], pc[2] - pa[2]];
        const cx = e1[1] * e2[2] - e1[2] * e2[1];
        const cy = e1[2] * e2[0] - e1[0] * e2[2];
        const cz = e1[0] * e2[1] - e1[1] * e2[0];
        const area = 0.5 * Math.hypot(cx, cy, cz);
        const uvArea = 0.5 * Math.abs((uv[b * 2] - uv[a * 2]) * (uv[c * 2 + 1] - uv[a * 2 + 1]) - (uv[c * 2] - uv[a * 2]) * (uv[b * 2 + 1] - uv[a * 2 + 1]));
        if (area < 1e-10 || uvArea < 1e-12) continue;
        out.push([uvArea / area, area]);
      }
    }
  }
  samples.set(key, out);
  return out;
}

/** area-weighted percentile of sqrt(uvArea / area) (texels per metre per texel of size: x sqrt(W H)) */
function densityPerTexel(list, p = 0.9) {
  if (!list.length) return 0;
  const s = list.map(([r, a]) => [Math.sqrt(r), a]).sort((x, y) => x[0] - y[0]);
  const total = s.reduce((n, [, a]) => n + a, 0);
  let acc = 0;
  for (const [d, a] of s) {
    acc += a;
    if (acc >= p * total) return d;
  }
  return s[s.length - 1][0];
}

const toLin = new Float32Array(256).map((_, i) => {
  const c = i / 255;
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
});
const toSrgb = (l) => {
  const c = l <= 0.0031308 ? l * 12.92 : 1.055 * l ** (1 / 2.4) - 0.055;
  return Math.max(0, Math.min(255, Math.round(c * 255)));
};
function halve(png, mode) {
  const w = png.width >> 1;
  const h = png.height >> 1;
  const out = new PNG({ width: w, height: h });
  const d = png.data;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const i00 = ((2 * y) * png.width + 2 * x) * 4;
      const i10 = i00 + 4;
      const i01 = i00 + png.width * 4;
      const i11 = i01 + 4;
      const o = (y * w + x) * 4;
      if (mode === 'colour') {
        for (let c = 0; c < 3; c++) out.data[o + c] = toSrgb((toLin[d[i00 + c]] + toLin[d[i10 + c]] + toLin[d[i01 + c]] + toLin[d[i11 + c]]) / 4);
      } else if (mode === 'normal') {
        let v = [0, 0, 0];
        for (const i of [i00, i10, i01, i11]) for (let c = 0; c < 3; c++) v[c] += d[i + c] / 127.5 - 1;
        const n = Math.hypot(v[0], v[1], v[2]) || 1;
        for (let c = 0; c < 3; c++) out.data[o + c] = Math.max(0, Math.min(255, Math.round((v[c] / n + 1) * 127.5)));
      } else {
        for (let c = 0; c < 3; c++) out.data[o + c] = (d[i00 + c] + d[i10 + c] + d[i01 + c] + d[i11 + c] + 2) >> 2;
      }
      out.data[o + 3] = (d[i00 + 3] + d[i10 + 3] + d[i01 + 3] + d[i11 + 3] + 2) >> 2;
    }
  }
  return out;
}

const target = pxPerM * margin;
const rows = [];
let mbBefore = 0;
let mbAfter = 0;
for (const tex of root.listTextures()) {
  const u = uses.get(tex) ?? [];
  const slots = [...new Set(u.map((x) => x.slot))];
  const row = { name: tex.getName(), slots, materials: [...new Set(u.map((x) => x.material.getName()))] };
  if (tex.getMimeType() !== 'image/png') {
    rows.push({ ...row, skipped: tex.getMimeType() });
    continue;
  }
  const size = tex.getSize();
  const [W, H] = size;
  const perTexel = Math.max(0, ...u.map((x) => densityPerTexel(trianglesOf(x.material, x.texCoord))));
  const density = perTexel * Math.sqrt(W * H);
  const sharp = u.some((x) => SHARP.test(x.material.getName()));
  const need = target * (sharp ? 2 ** sharpLevels : 1);
  let drop = 0;
  while (drop < maxDrop && density / 2 ** (drop + 1) >= need && Math.min(W, H) >> (drop + 1) >= minSize) drop++;
  const mb = (w, h) => (w * h * 4 * 4) / 3 / 1e6;
  mbBefore += mb(W, H);
  mbAfter += mb(W >> drop, H >> drop);
  const mode = slots.some((s) => COLOUR.test(s)) ? 'colour' : slots.some((s) => NORMAL.test(s)) ? 'normal' : 'data';
  if (drop && !dry) {
    let png = PNG.sync.read(Buffer.from(tex.getImage()));
    for (let k = 0; k < drop; k++) png = halve(png, mode);
    tex.setImage(new Uint8Array(PNG.sync.write(png)));
  }
  rows.push({ ...row, mode, sharp, density_texels_per_m: Math.round(density), from: [W, H], to: [W >> drop, H >> drop], drop });
}
if (!dry) await writeFile(dst, await io.writeBinary(doc));
console.log(JSON.stringify({ in: src, out: dry ? null : dst, px_per_m: pxPerM, margin, target_texels_per_m: target, rgba8_mips_mb_before: +mbBefore.toFixed(1), rgba8_mips_mb_after: +mbAfter.toFixed(1), textures: rows }));
