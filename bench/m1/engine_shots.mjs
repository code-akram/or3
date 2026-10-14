#!/usr/bin/env node
// Engine frames for a character build: serves the web character viewer (web/dist) and ONE build dir
// on loopback, drives headless Chromium (Playwright; WebGPU on SwiftShader, WebGL2 fallback) and
// writes game_<view>.png + game_shots.json into that build dir.
//
//   node bench/m1/engine_shots.mjs --build RUN_DIR [--views front,three_quarter,profile,closeup,portrait]
//        [--size 1024] [--portrait 1920x1080] [--backend auto|webgpu|webgl2] [--port 8791] [--timeout 600]
//        [--query 'k=v&...' (extra viewer URL params, URL-encoded; A/B only)] [--prefix game_] [--pose arms_up]
//        [--balls auto|on|off]  shader-ball parity frame (game_balls.png) when RUN_DIR has shader_balls.json
//   node bench/m1/engine_shots.mjs --build RUN_DIR --serve [--port 8791] [--selftest]
//        Device capture (the M4 Air): serve only, no browser. Open the printed URL on the device (through
//        `ssh -N -L 8791:127.0.0.1:8791 <this host>`); the page renders every view on its own GPU and POSTs
//        the frames and a summary back; the server writes them into RUN_DIR (whitelisted names only) and
//        exits after game_shots.json. --selftest drives the same URL from local headless Chromium.
//
// Containment: the server exposes only web/dist-viewer and RUN_DIR (under /asset/), bound to 127.0.0.1, and
// every output file goes into RUN_DIR. For a fan build RUN_DIR is the private run dir, so nothing
// from it is served beside public data or written outside private/ (lookdev.sh passes it).
// Run it under `taskset` on the shared machine (engine_shots.sh does).
import { spawnSync } from 'node:child_process';
import { createServer } from 'node:http';
import { readFile, realpath, stat, writeFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { extname, join, normalize, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { deflateSync, crc32 } from 'node:zlib';
import { chromium } from 'playwright';

const here = fileURLToPath(new URL('.', import.meta.url));
const repo = resolve(here, '..', '..');
const argv = process.argv.slice(2);
const opt = (n, d) => {
  const i = argv.indexOf(`--${n}`);
  return i >= 0 ? argv[i + 1] : d;
};
const buildArg = opt('build', null);
if (!buildArg) {
  console.error('usage: engine_shots.mjs --build RUN_DIR [...]');
  process.exit(2);
}
const build = await realpath(resolve(buildArg));
const views = opt('views', 'front,three_quarter,profile,closeup,portrait').split(',').filter(Boolean);
const size = Number(opt('size', 1024));
const [pw, ph] = opt('portrait', '1920x1080').split('x').map(Number);
const backendWanted = opt('backend', 'auto');
const port = Number(opt('port', 8791));
const timeoutS = Number(opt('timeout', 900));
const extraQuery = opt('query', ''); // extra viewer URL params, URL-encoded (A/B only)
const outPrefix = opt('prefix', 'game_');
const poseArg = opt('pose', null); // debug preset for every view (e.g. arms_up), else the view's own
const dist = join(repo, 'web', opt('dist', 'dist-viewer'));
const BASIS = join(repo, 'web', 'node_modules', 'three', 'examples', 'jsm', 'libs', 'basis');
const ballsArg = opt('balls', 'auto');
const beauty = opt('beauty', 'on') !== 'off'; // --beauty off: no game_portrait_beauty.png
const wantBalls = ballsArg === 'on' || (ballsArg === 'auto' && existsSync(join(build, 'shader_balls.json')));

if (!existsSync(join(build, 'character.glb'))) {
  console.error(`no character.glb in ${build}`);
  process.exit(2);
}
if (!existsSync(join(dist, 'character.html'))) {
  console.error('[engine_shots] building the viewer (npm run build:viewer)');
  const r = spawnSync('npm', ['run', 'build:viewer', '--silent'], { cwd: join(repo, 'web'), stdio: 'inherit' });
  if (r.status !== 0) process.exit(1);
}

// ------------------------------------------------------------------ loopback server
const ISOLATION = {
  'Cross-Origin-Opener-Policy': 'same-origin',
  'Cross-Origin-Embedder-Policy': 'require-corp',
  'Cross-Origin-Resource-Policy': 'same-origin',
  'X-Content-Type-Options': 'nosniff',
};
const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json',
  '.wasm': 'application/wasm',
  '.png': 'image/png',
  '.glb': 'model/gltf-binary',
};
// From the build dir only what the viewer reads.
const ASSET_OK = /^(character\.glb|character\.ktx2\.glb|character\.rig\.json|character\.stats\.json|engine_stage\.json|material_params\.json|suit_detail\.json|suit_twill_detail\.png|shader_balls\.(glb|json)|skin_(head|hands)_curvature\.png|hair_atlas_(flow|data)\.png)$/;

async function serve(req, res) {
  const url = new URL(req.url, 'http://local');
  let rel = decodeURIComponent(url.pathname);
  let root = dist;
  if (rel.startsWith('/basis/')) {
    // the KTX2 transcoder (two files) from three's examples, for ?ktx2=1
    rel = rel.slice('/basis/'.length);
    if (!/^basis_transcoder\.(js|wasm)$/.test(rel)) return send(res, 404);
    root = BASIS;
  } else if (rel.startsWith('/asset/')) {
    rel = rel.slice('/asset/'.length);
    if (!ASSET_OK.test(rel)) return send(res, 404);
    root = build;
  } else if (rel.endsWith('/')) rel += 'index.html';
  const file = normalize(join(root, rel));
  if (!file.startsWith(root + sep)) return send(res, 403);
  let info;
  try {
    info = await stat(file);
  } catch {
    return send(res, 404);
  }
  if (!info.isFile()) return send(res, 404);
  const body = await readFile(file);
  res.writeHead(200, { ...ISOLATION, 'content-type': MIME[extname(file)] ?? 'application/octet-stream', 'content-length': body.length, 'cache-control': 'no-store' });
  res.end(req.method === 'HEAD' ? undefined : body);
}
function send(res, code) {
  res.writeHead(code, { ...ISOLATION, 'content-type': 'text/plain' });
  res.end(String(code));
}
// ------------------------------------------------------------------ device upload (--serve)
const serveMode = argv.includes('--serve');
const UPLOAD_OK = /^game_(front|three_quarter|profile|closeup|portrait|portrait_beauty)\.png$|^game_shots\.json$/;
const MAX_UPLOAD = 4096 * 4096 * 4;
let uploadDone = null;
const uploadFinished = new Promise((r) => (uploadDone = r));
const uploaded = [];

async function receive(req, res) {
  const url = new URL(req.url, 'http://local');
  const name = decodeURIComponent(url.pathname.slice('/upload/'.length));
  if (!serveMode || !UPLOAD_OK.test(name)) return send(res, 403);
  const chunks = [];
  let n = 0;
  for await (const c of req) {
    n += c.length;
    if (n > MAX_UPLOAD) return send(res, 413);
    chunks.push(c);
  }
  const body = Buffer.concat(chunks);
  if (name.endsWith('.png')) {
    const w = Number(req.headers['x-width']);
    const h = Number(req.headers['x-height']);
    if (!(w > 0 && h > 0 && w <= 4096 && h <= 4096) || body.length !== w * h * 4) return send(res, 400);
    await writeFile(join(build, name), png(w, h, body));
  } else {
    const j = JSON.parse(body.toString('utf8'));
    j.build = build;
    j.received = new Date().toISOString();
    j.uploaded = [...uploaded];
    await writeFile(join(build, name), JSON.stringify(j, null, 1));
  }
  uploaded.push(name);
  console.error(`[engine_shots] received ${name} (${body.length} bytes)`);
  send(res, 200);
  if (name === 'game_shots.json') uploadDone(name);
}

const server = createServer((req, res) => {
  if (req.method === 'POST' && req.url.startsWith('/upload/')) return void receive(req, res).catch(() => send(res, 500));
  if (req.method !== 'GET' && req.method !== 'HEAD') return send(res, 405);
  serve(req, res).catch(() => send(res, 500));
});
await new Promise((r) => server.listen(port, '127.0.0.1', r));

// ------------------------------------------------------------------ PNG (RGB8, no deps)
function png(w, h, rgba) {
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

// ------------------------------------------------------------------ browser
const ARGS = [
  // bench/headless-check.mjs: WebGPU on SwiftShader needs Vulkan-on-SwiftShader and no Vulkan surface
  '--enable-unsafe-webgpu',
  '--enable-unsafe-swiftshader',
  '--enable-features=Vulkan',
  '--use-vulkan=swiftshader',
  '--use-angle=swiftshader',
  '--use-webgpu-adapter=swiftshader',
  '--disable-vulkan-surface',
  '--renderer-process-limit=1',
];

async function run(backend) {
  const browser = await chromium.launch({ headless: true, channel: 'chromium', args: ARGS });
  const log = [];
  try {
    const page = await browser.newPage({ viewport: { width: 256, height: 256 } });
    page.on('console', (m) => log.push(`${m.type()}: ${m.text()}`.slice(0, 300)));
    page.on('pageerror', (e) => log.push(`pageerror: ${e.message}`.slice(0, 300)));
    page.setDefaultTimeout(timeoutS * 1000);
    const q = new URLSearchParams({ asset: '.', capture: '1', ui: '0', dpr: '1' });
    if (backend === 'webgl2') q.set('gl', '1');
    for (const [k, v] of new URLSearchParams(extraQuery)) q.set(k, v);
    const t0 = Date.now();
    await page.goto(`http://127.0.0.1:${port}/character.html?${q}`, { waitUntil: 'load' });
    await page.waitForFunction(() => window.__viewerState?.ready || window.__viewerState?.phase === 'error', null, { timeout: timeoutS * 1000, polling: 500 });
    const st = await page.evaluate(() => window.__viewerState);
    if (st.phase === 'error') throw new Error(`viewer error: ${st.error}`);
    const bootMs = Date.now() - t0;
    const shots = [];
    // the portrait twice: game_portrait.png without post (the parity frame, compared with
    // hero.sh --parity) and game_portrait_beauty.png with bloom, halation and grain
    const jobs = views.flatMap((v) => (v === 'portrait' && beauty ? [[v, false], [v, true]] : [[v, false]]));
    for (const [v, post] of jobs) {
      const [w, h] = v === 'portrait' ? [pw, ph] : [size, size];
      const rig = v === 'portrait' ? 'hero' : 'neutral';
      const name = `${outPrefix}${v}${post ? '_beauty' : ''}.png`;
      const t = Date.now();
      const r = await page.evaluate(([v, rig, w, h, p, post]) => window.__viewer.capture(v, rig, w, h, p ?? undefined, post), [v, rig, w, h, poseArg, post]);
      const px = Buffer.from(r.b64, 'base64');
      if (px.length !== w * h * 4) throw new Error(`${v}: got ${px.length} bytes for ${w}x${h}`);
      await writeFile(join(build, name), png(w, h, px));
      shots.push({ view: v, rig, post, file: name, res: [w, h], render_ms: r.ms, wall_ms: Date.now() - t, draw_calls: r.draw_calls, triangles: r.triangles, lights: r.lights, pose: poseArg, weights: r.weights });
      console.error(`[engine_shots] ${backend} ${name} ${w}x${h}: ${Date.now() - t} ms`);
    }
    const stats = await page.evaluate(() => window.__viewer.stats());
    let balls = null;
    if (wantBalls) {
      const bj = JSON.parse(await readFile(join(build, 'shader_balls.json'), 'utf8'));
      const [bw, bh] = bj.res;
      const qb = new URLSearchParams(q);
      qb.set('scene', 'balls');
      const t = Date.now();
      await page.goto(`http://127.0.0.1:${port}/character.html?${qb}`, { waitUntil: 'load' });
      await page.waitForFunction(() => window.__viewerState?.ready || window.__viewerState?.phase === 'error', null, { timeout: timeoutS * 1000, polling: 500 });
      const sb = await page.evaluate(() => window.__viewerState);
      if (sb.phase === 'error') throw new Error(`balls viewer error: ${sb.error}`);
      const r = await page.evaluate(([w, h]) => window.__viewer.captureBalls(w, h), [bw, bh]);
      const px = Buffer.from(r.b64, 'base64');
      await writeFile(join(build, `${outPrefix}balls.png`), png(bw, bh, px));
      balls = { file: `${outPrefix}balls.png`, res: [bw, bh], render_ms: r.ms, wall_ms: Date.now() - t, draw_calls: r.draw_calls, warnings: sb.warnings };
      console.error(`[engine_shots] ${backend} balls ${bw}x${bh}: ${Date.now() - t} ms`);
    }
    const adapter = await page.evaluate(async () => {
      try {
        const a = await navigator.gpu?.requestAdapter();
        return a ? { vendor: a.info.vendor, architecture: a.info.architecture, description: a.info.description } : null;
      } catch {
        return null;
      }
    });
    return { ok: true, backend: st.backend, adapter, boot_ms: bootMs, load: st.load, verify: st.verify, warnings: st.warnings, facial_atlas: st.facialAtlas, gaze: st.gaze, stats, shots, balls, browser: browser.version(), console: [...new Set(log)].slice(0, 40) };
  } finally {
    await browser.close();
  }
}

if (serveMode) {
  const q = new URLSearchParams({ asset: '.', capture: '1', upload: '1', ui: '0', dpr: '1' });
  for (const [k, v] of new URLSearchParams(extraQuery)) q.set(k, v);
  const url = `http://127.0.0.1:${port}/character.html?${q}`;
  console.log(`[engine_shots] serving ${build} on 127.0.0.1:${port}; open on the device:\n  ${url}`);
  if (argv.includes('--selftest')) {
    // stands in for the Air: the same URL in local headless Chromium (SwiftShader), short perf loop
    const browser = await chromium.launch({ headless: true, channel: 'chromium', args: ARGS });
    const page = await browser.newPage({ viewport: { width: 640, height: 360 } });
    page.on('pageerror', (e) => console.error(`pageerror: ${e.message}`.slice(0, 300)));
    page.setDefaultTimeout(timeoutS * 1000);
    await page.goto(`${url}&perf=3`, { waitUntil: 'load' });
    await Promise.race([uploadFinished, new Promise((_, rej) => setTimeout(() => rej(new Error('selftest timeout')), timeoutS * 1000))]);
    await browser.close();
  } else {
    await uploadFinished;
  }
  server.close();
  console.log(JSON.stringify({ ok: true, device_capture: true, uploaded }, null, 1));
  process.exit(0);
}

const result = { build, when: new Date().toISOString(), attempts: [] };
let ok = null;
for (const b of backendWanted === 'auto' ? ['webgpu', 'webgl2'] : [backendWanted]) {
  try {
    ok = await run(b);
    break;
  } catch (e) {
    result.attempts.push({ backend: b, error: String(e?.message ?? e).slice(0, 2000) });
    console.error(`[engine_shots] ${b} failed: ${String(e?.message ?? e).slice(0, 300)}`);
  }
}
server.close();
Object.assign(result, ok ?? { ok: false });
await writeFile(join(build, `${outPrefix}shots.json`), JSON.stringify(result, null, 1));
console.log(JSON.stringify({ ok: result.ok, backend: result.backend, shots: (result.shots ?? []).map((s) => s.file), verify: result.verify }, null, 1));
process.exit(result.ok ? 0 : 1);
