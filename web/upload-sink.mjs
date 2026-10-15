// Upload sink for the viewer's device capture (T24): POST /upload/<name> from character.html
// ?capture=1&upload=1 (and the ?perf=1 overlay's "save"). Shared by the Vite dev server
// (character-assets.mjs: <data/build>/air/<session>/) and bench/m1/engine_shots.mjs --serve (its run dir).
//
// Only whitelisted names are written, only into the one directory the caller gives, never outside it:
//   game_<view>.png / game_shots.json            the T6 device-capture names (lookdev_report reads them)
//   <tier>_<view>[_rig][_beauty].png             tier stills (tier = hero | gameplay)
//   <tier>_tt/frame_NNN.png                      2 s turntable frames
//   <tier>_shots.json, <tier>_perf.json          per-tier summary and frame-time report
//   live_perf.json, session.json                 the overlay's report; the end-of-session summary
// A .png body is either a PNG file (content-type image/png: checked for the signature and the size) or raw
// RGBA8 rows with x-width / x-height headers (encoded here). JSON is parsed and re-written with `received`.
import { mkdir, writeFile } from 'node:fs/promises';
import { dirname, join, normalize, sep } from 'node:path';
import { crc32, deflateSync } from 'node:zlib';

export const UPLOAD_NAME = /^(?:game_(?:front|three_quarter|profile|closeup|closeup_hero|portrait|portrait_beauty|gameplay|gameplay_hero)\.png|game_shots\.json|(?:hero|gameplay)_[a-z_]{1,48}\.png|(?:hero|gameplay)_tt\/frame_\d{3}\.png|(?:hero|gameplay)_(?:shots|perf)\.json|live_perf\.json|session\.json)$/;
export const SESSION = /^[0-9A-Za-z_-]{1,64}$/;
const MAX_UPLOAD = 4096 * 4096 * 4;

/** RGB8 PNG from RGBA8 rows (no deps). */
export function png(w, h, rgba) {
  const raw = Buffer.alloc((w * 3 + 1) * h);
  for (let y = 0; y < h; y++) {
    raw[y * (w * 3 + 1)] = 0;
    for (let x = 0; x < w; x++) {
      const s = (y * w + x) * 4;
      const d = y * (w * 3 + 1) + 1 + x * 3;
      raw[d] = rgba[s];
      raw[d + 1] = rgba[s + 1];
      raw[d + 2] = rgba[s + 2];
    }
  }
  const chunk = (type, data) => {
    const len = Buffer.alloc(4);
    len.writeUInt32BE(data.length);
    const td = Buffer.concat([Buffer.from(type), data]);
    const crc = Buffer.alloc(4);
    crc.writeUInt32BE(crc32(td) >>> 0);
    return Buffer.concat([len, td, crc]);
  };
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(w, 0);
  ihdr.writeUInt32BE(h, 4);
  ihdr[8] = 8;
  ihdr[9] = 2;
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', ihdr), chunk('IDAT', deflateSync(raw, { level: 6 })), chunk('IEND', Buffer.alloc(0))]);
}

const PNG_SIG = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);

/**
 * Receive one upload into `dir` (created if needed). Returns { status, name?, bytes? }; the caller sends the
 * status. `name` is the decoded path after /upload/ (query string stripped).
 */
export async function receiveUpload(req, name, dir, extra = {}) {
  if (!UPLOAD_NAME.test(name)) return { status: 403 };
  const file = normalize(join(dir, name));
  if (!file.startsWith(normalize(dir) + sep)) return { status: 403 };
  const chunks = [];
  let n = 0;
  for await (const c of req) {
    n += c.length;
    if (n > MAX_UPLOAD) return { status: 413 };
    chunks.push(c);
  }
  const body = Buffer.concat(chunks);
  let out;
  if (name.endsWith('.png')) {
    if (String(req.headers['content-type'] ?? '').startsWith('image/png')) {
      if (body.length < 33 || !body.subarray(0, 8).equals(PNG_SIG)) return { status: 400 };
      const w = body.readUInt32BE(16);
      const h = body.readUInt32BE(20);
      if (!(w > 0 && h > 0 && w <= 4096 && h <= 4096)) return { status: 400 };
      out = body;
    } else {
      const w = Number(req.headers['x-width']);
      const h = Number(req.headers['x-height']);
      if (!(w > 0 && h > 0 && w <= 4096 && h <= 4096) || body.length !== w * h * 4) return { status: 400 };
      out = png(w, h, body);
    }
  } else {
    let j;
    try {
      j = JSON.parse(body.toString('utf8'));
    } catch {
      return { status: 400 };
    }
    if (!j || typeof j !== 'object' || Array.isArray(j)) return { status: 400 };
    out = JSON.stringify({ ...j, ...extra, received: new Date().toISOString() }, null, 1);
  }
  await mkdir(dirname(file), { recursive: true });
  await writeFile(file, out);
  return { status: 200, name, bytes: body.length };
}
