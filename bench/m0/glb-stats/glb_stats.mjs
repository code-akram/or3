// Validate a skinned GLB with the Khronos glTF-Validator and report, per mesh:
// triangles, vertices, skin joint count and the histogram of non-zero
// weights per vertex (across all JOINTS_n/WEIGHTS_n sets).
//
// Usage: node glb_stats.mjs path/to/character.glb [--json out.json]
import { readFile, writeFile } from 'node:fs/promises';
import { NodeIO } from '@gltf-transform/core';
import validator from 'gltf-validator';

const file = process.argv[2];
const jsonOut = process.argv.includes('--json') ? process.argv[process.argv.indexOf('--json') + 1] : null;
const bytes = new Uint8Array(await readFile(file));

const report = await validator.validateBytes(bytes, { maxIssues: 200 });
const v = report.issues;
const validation = {
  validatorVersion: report.validatorVersion,
  errors: v.numErrors, warnings: v.numWarnings, infos: v.numInfos, hints: v.numHints,
  messages: v.messages.filter((m) => m.severity <= 1).slice(0, 30)
    .map((m) => `${m.severity === 0 ? 'E' : 'W'} ${m.code} ${m.pointer ?? ''} ${m.message}`),
};

const doc = await new NodeIO().readBinary(bytes);
const root = doc.getRoot();
const meshes = [];
for (const node of root.listNodes()) {
  const mesh = node.getMesh();
  if (!mesh) continue;
  const skin = node.getSkin();
  let tris = 0, verts = 0;
  const hist = {};
  for (const prim of mesh.listPrimitives()) {
    const idx = prim.getIndices();
    const pos = prim.getAttribute('POSITION');
    verts += pos.getCount();
    tris += (idx ? idx.getCount() : pos.getCount()) / 3;
    const wsets = prim.listSemantics().filter((s) => s.startsWith('WEIGHTS_'))
      .map((s) => prim.getAttribute(s));
    const el = [];
    for (let i = 0; i < pos.getCount(); i++) {
      let n = 0;
      for (const w of wsets) { w.getElement(i, el); for (const x of el) if (x > 1e-4) n++; }
      hist[n] = (hist[n] ?? 0) + 1;
    }
  }
  meshes.push({ node: node.getName(), mesh: mesh.getName(), tris, verts,
    joints: skin ? skin.listJoints().length : 0, weightsPerVertex: hist });
}
const out = {
  file, bytes: bytes.length, validation, meshes,
  totalTris: meshes.reduce((a, m) => a + m.tris, 0),
  skins: root.listSkins().map((s) => s.listJoints().length),
  textures: root.listTextures().map((t) => ({ name: t.getName() || t.getURI(), mime: t.getMimeType(),
    size: t.getSize(), bytes: t.getImage()?.byteLength })),
  materials: root.listMaterials().map((m) => m.getName()),
};
console.log(JSON.stringify(out, null, 2));
if (jsonOut) await writeFile(jsonOut, JSON.stringify(out, null, 2));
process.exitCode = validation.errors > 0 ? 1 : 0;
