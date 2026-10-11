#!/usr/bin/env node
// Bench server: serves the production web build with cross-origin isolation headers and records
// telemetry POSTs as JSONL. Binds to 127.0.0.1 only; reach it from another machine via `ssh -L`.
//
//   node bench/server.mjs [--root web/dist] [--port 8787] [--out bench/m0/telemetry]
//
// No dependencies (Node >= 20).
import { createServer } from 'node:http';
import { appendFile, mkdir, readFile, stat } from 'node:fs/promises';
import { extname, join, normalize, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';

const here = fileURLToPath(new URL('.', import.meta.url));
const args = Object.fromEntries(
  process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith('--') ? [...acc, [a.slice(2), all[i + 1]]] : acc), []),
);
const root = resolve(args.root ?? join(here, '..', 'web', 'dist'));
const outDir = resolve(args.out ?? join(here, 'm0', 'telemetry'));
const port = Number(args.port ?? 8787);
const host = '127.0.0.1';
const MAX_BODY = 2 * 1024 * 1024;
const SESSION_RE = /^[0-9A-Za-z]{8,20}-[a-z0-9]{1,12}$/;

// Keep in sync with web/public/_headers and web/vite.config.ts.
const ISOLATION = {
  'Cross-Origin-Opener-Policy': 'same-origin',
  'Cross-Origin-Embedder-Policy': 'require-corp',
  'Cross-Origin-Resource-Policy': 'same-origin',
  'X-Content-Type-Options': 'nosniff',
};

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json',
  '.wasm': 'application/wasm',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
  '.ktx2': 'image/ktx2',
  '.glb': 'model/gltf-binary',
};
const COMPRESSIBLE = new Set(['.html', '.js', '.mjs', '.css', '.json', '.wasm', '.svg']);
const gzCache = new Map();

await mkdir(outDir, { recursive: true });

function send(res, status, headers, body) {
  res.writeHead(status, { ...ISOLATION, ...headers });
  res.end(body);
}

async function serveStatic(req, res) {
  const url = new URL(req.url, 'http://local');
  let rel = decodeURIComponent(url.pathname);
  if (rel.endsWith('/')) rel += 'index.html';
  const file = normalize(join(root, rel));
  if (file !== root && !file.startsWith(root + sep)) return send(res, 403, {}, 'forbidden');
  let info;
  try {
    info = await stat(file);
  } catch {
    return send(res, 404, { 'content-type': 'text/plain' }, 'not found');
  }
  if (!info.isFile()) return send(res, 404, { 'content-type': 'text/plain' }, 'not found');
  const ext = extname(file);
  const headers = {
    'content-type': MIME[ext] ?? 'application/octet-stream',
    'cache-control': rel.startsWith('/assets/') ? 'public, max-age=31536000, immutable' : 'no-store',
  };
  const key = `${file}:${info.mtimeMs}`;
  if (COMPRESSIBLE.has(ext) && /\bgzip\b/.test(req.headers['accept-encoding'] ?? '')) {
    let gz = gzCache.get(key);
    if (!gz) {
      gz = gzipSync(await readFile(file), { level: 6 });
      gzCache.set(key, gz);
    }
    return send(res, 200, { ...headers, 'content-encoding': 'gzip', vary: 'accept-encoding', 'content-length': gz.length }, req.method === 'HEAD' ? undefined : gz);
  }
  const body = await readFile(file);
  return send(res, 200, { ...headers, 'content-length': body.length }, req.method === 'HEAD' ? undefined : body);
}

async function telemetry(req, res) {
  const chunks = [];
  let size = 0;
  for await (const c of req) {
    size += c.length;
    if (size > MAX_BODY) return send(res, 413, {}, 'too large');
    chunks.push(c);
  }
  let record;
  try {
    record = JSON.parse(Buffer.concat(chunks).toString('utf8'));
  } catch {
    return send(res, 400, {}, 'bad json');
  }
  if (!record || typeof record !== 'object' || typeof record.session !== 'string' || !SESSION_RE.test(record.session)) {
    return send(res, 400, {}, 'bad session');
  }
  const line = JSON.stringify({ receivedAt: new Date().toISOString(), ...record }) + '\n';
  await appendFile(join(outDir, `${record.session}.jsonl`), line);
  const t = record.type === 'window' ? `window #${record.seq} t=${Math.round(record.tEndS)}s` : String(record.type);
  console.log(`[telemetry] ${record.session} ${t}`);
  return send(res, 204, {}, undefined);
}

const server = createServer((req, res) => {
  const path = (req.url ?? '/').split('?')[0];
  const handler =
    req.method === 'POST' && path === '/telemetry' ? telemetry : req.method === 'GET' || req.method === 'HEAD' ? serveStatic : null;
  if (!handler) return send(res, 405, {}, 'method not allowed');
  handler(req, res).catch((err) => {
    console.error('[server] error:', err?.message ?? err);
    if (!res.headersSent) send(res, 500, {}, 'error');
  });
});

server.listen(port, host, () => {
  console.log(`bench server: http://${host}:${port}/  root=${root}  telemetry -> ${outDir}`);
});
