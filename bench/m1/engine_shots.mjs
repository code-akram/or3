#!/usr/bin/env node
// Engine frames for a character build: serves the web character viewer (web/dist) and ONE build dir
// on loopback, drives headless Chromium (Playwright; WebGPU on SwiftShader, WebGL2 fallback) and
// writes game_<view>.png + game_shots.json into that build dir.
//
//   node bench/m1/engine_shots.mjs --build RUN_DIR [--views front,three_quarter,profile,closeup,portrait,closeup:hero]
//        [--size 1024] [--portrait 1920x1080] [--backend auto|webgpu|webgl2] [--port 8796] [--timeout 600]
//        [--query 'k=v&...' (extra viewer URL params, URL-encoded; A/B only)] [--prefix game_] [--pose arms_up]
//        [--balls auto|on|off]  shader-ball parity frame (game_balls.png) when RUN_DIR has shader_balls.json
//        [--turntable SECONDS] [--tt-view closeup:hero] [--tt-fps 24] [--tt-size 640] [--tt-hz 48] [--tt-warmup 24]
//        [--chart]  the grey chart (T16; RUN_DIR has chart.glb + chart.json): <prefix>chart.png (graded) and
//                   <prefix>chart_linear.npy (scene-linear float32 H x W x 4)
//
// A view is `name` (its own rig: the hero rig for the portrait, the neutral look-dev rig otherwise) or
// `name:hero` / `name:neutral` (T10): `closeup:hero` is the closeup camera under the hero rig re-placed
// around the head (rig._around), the standard head / hair / beard gate frame -> game_closeup_hero.png.
// --turntable (T10): the view's frames while the model turns at the viewer's 20 deg/s for SECONDS, into
// RUN_DIR/<prefix>turntable/ and <prefix>turntable.mp4, with a temporal-noise (shimmer) number per frame
// in <prefix>shots.json (the mean |second temporal difference| of the luma, 0..255).
// Temporal AA (T16, the viewer's default ?aa=traa; --query aa=msaa for the MSAA / alpha-to-coverage path):
// stills accumulate aa.stillFrames jittered frames; the turntable runs at --tt-hz (default = --tt-fps,
// must be a multiple of it) with the in-between frames rendered into the history but not written, after
// --tt-warmup frames (default 24) of turning before the first written frame, so the history is in its
// steady state as in the live viewer.
//   node bench/m1/engine_shots.mjs --build RUN_DIR --serve [--port 8796] [--selftest] [--query 'tiers=hero,gameplay']
//        Device capture (the M4 Air): serve only, no browser. Open the printed URL on the device (through
//        `ssh -N -L 8796:127.0.0.1:8796 <this host>`); the page renders every view on its own GPU and POSTs
//        the frames and a summary back; the server writes them into RUN_DIR (whitelisted names only,
//        web/upload-sink.mjs) and exits after session.json (T24: the page's last upload). --selftest drives
//        the same URL from local headless Chromium. With tiers (T24) the page captures each tier in turn
//        (stills, a 2 s turntable, the perf loop) as <tier>_*.png / <tier>_tt/ / <tier>_shots.json /
//        <tier>_perf.json (bench/m1/v4/air-session.md).
//   --texcheck ['q1;q2;...'] (T18b): no frames; the sampled-texture audit (web texbudget.ts) of every pipeline of
//        each view under each URL variant (default: the hero tier, ltc=0, sharemaps=0, pcss=0, contact=0, the
//        gameplay tier, hairshadow=0) -> <prefix>texcheck.json; exit 1 if any binds > 16 per stage (WebGPU's default)
//   --crop x,y,w,h / --tt-crop x,y,w,h (T18b): only that window of each still / turntable frame (same camera)
//   --tier hero|gameplay (T24): the quality tier for the headless shots (= --query tier=X --prefix X_; X_shots.json)
//
// Containment: the server exposes only web/dist-viewer and RUN_DIR (under /asset/), bound to 127.0.0.1, and
// every output file goes into RUN_DIR. For a fan build RUN_DIR is the private run dir, so nothing
// from it is served beside public data or written outside private/ (lookdev.sh passes it).
// Run it under `taskset` on the shared machine (engine_shots.sh does).
import { spawnSync } from 'node:child_process';
import { createServer } from 'node:http';
import { mkdir, readFile, realpath, stat, writeFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { extname, join, normalize, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
import { png, receiveUpload } from '../../web/upload-sink.mjs';

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
const views = opt('views', 'front,three_quarter,profile,closeup,portrait,closeup:hero').split(',').filter(Boolean);
const ttSeconds = Number(opt('turntable', 0));
const ttView = opt('tt-view', 'closeup:hero');
const ttFps = Number(opt('tt-fps', 24));
const ttSize = Number(opt('tt-size', 640));
const ttHz = Number(opt('tt-hz', ttFps));
const ttWarmup = Number(opt('tt-warmup', 24));
const wantChart = argv.includes('--chart');
// T18b: --crop x,y,w,h renders only that window of every still (same camera; e.g. the eyes of the 1920x1080
// portrait), --tt-crop x,y,w,h the same for the turntable frames (of the --tt-size frame)
const parseCrop = (v) => (v ? v.split(',').map(Number) : null);
const cropArg = parseCrop(opt('crop', null));
const ttCrop = parseCrop(opt('tt-crop', null));
// T18b: --texcheck [VARIANTS]: no frames; per view (--views) and per URL variant (';'-separated query strings,
// default below), a fresh page load renders one frame with the texture audit on (main.ts textureAudit,
// texbudget.ts) -> <prefix>texcheck.json; exits 1 when any pipeline binds more than 16 sampled textures in a stage
const texcheckArg = argv.includes('--texcheck') ? (argv[argv.indexOf('--texcheck') + 1] ?? '') : null;
const TEXCHECK_VARIANTS = ['', 'ltc=0', 'sharemaps=0', 'pcss=0', 'contact=0', 'tier=gameplay', 'hairshadow=0'];
const TT_DEG_PER_S = 20; // main.ts turntable speed
/** 'closeup:hero' -> [view, rig, file stem] (the default rig: hero for the portrait, else neutral) */
function viewSpec(v) {
  const [name, r] = v.split(':');
  const rig = r === 'hero' || r === 'neutral' ? r : name === 'portrait' ? 'hero' : 'neutral';
  const stem = r && rig !== (name === 'portrait' ? 'hero' : 'neutral') ? `${name}_${rig}` : name;
  return [name, rig, stem];
}
const size = Number(opt('size', 1024));
const [pw, ph] = opt('portrait', '1920x1080').split('x').map(Number);
const backendWanted = opt('backend', 'auto');
const port = Number(opt('port', 8796));
const timeoutS = Number(opt('timeout', 900));
const tierArg = opt('tier', null); // T24 quality tier: hero | gameplay
let extraQuery = opt('query', ''); // extra viewer URL params, URL-encoded (A/B only)
if (tierArg) extraQuery = `tier=${encodeURIComponent(tierArg)}${extraQuery ? '&' + extraQuery : ''}`;
const outPrefix = opt('prefix', tierArg ? `${tierArg}_` : 'game_');
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
const ASSET_OK = /^(character\.glb|character\.ktx2\.glb|character\.lod1\.glb|character\.lod1\.ktx2\.glb|character\.rig\.json|character\.stats\.json|engine_stage\.json|material_params\.json|suit_detail\.json|suit_twill_detail\.png|shader_balls\.(glb|json)|skin_(head|hands)_curvature\.png|grade_lut\.json|set_bounce\.json|chart\.(glb|json))$/;

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
let uploadDone = null;
const uploadFinished = new Promise((r) => (uploadDone = r));
const uploaded = [];

async function receive(req, res) {
  const url = new URL(req.url, 'http://local');
  const name = decodeURIComponent(url.pathname.slice('/upload/'.length));
  if (!serveMode) return send(res, 403);
  const r = await receiveUpload(req, name, build, { build });
  if (r.status !== 200) return send(res, r.status);
  uploaded.push(name);
  console.error(`[engine_shots] received ${name} (${r.bytes} bytes)`);
  send(res, 200);
  if (name === 'session.json') uploadDone(name);
}

const server = createServer((req, res) => {
  if (req.method === 'POST' && req.url.startsWith('/upload/')) return void receive(req, res).catch(() => send(res, 500));
  if (req.method !== 'GET' && req.method !== 'HEAD') return send(res, 405);
  serve(req, res).catch(() => send(res, 500));
});
await new Promise((r, rej) => {
  // a busy port (another track's capture) would otherwise hang here silently
  server.once('error', (e) => rej(new Error(`[engine_shots] cannot listen on 127.0.0.1:${port}: ${e.code} (try --port)`)));
  server.listen(port, '127.0.0.1', r);
});

/** A float32 .npy (little endian, C order) of raw bytes with this shape. */
function npy(raw, shape) {
  let head = `{'descr': '<f4', 'fortran_order': False, 'shape': (${shape.join(', ')}), }`;
  const pad = 16 - ((10 + head.length + 1) % 16);
  head += ' '.repeat(pad % 16) + '\n';
  const pre = Buffer.alloc(10);
  pre.write('\x93NUMPY', 0, 'latin1');
  pre[6] = 1;
  pre[7] = 0;
  pre.writeUInt16LE(head.length, 8);
  return Buffer.concat([pre, Buffer.from(head, 'latin1'), raw]);
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
    // name the URL behind a bare "Failed to load resource" console error
    page.on('response', (r) => {
      if (r.status() >= 400) log.push(`http ${r.status()}: ${r.url().replace(/^http:\/\/127\.0\.0\.1:\d+/, '')}`.slice(0, 300));
    });
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
    for (const [spec, post] of jobs) {
      const [v, rig, stem] = viewSpec(spec);
      const [fw, fh] = v === 'portrait' ? [pw, ph] : [size, size];
      const [w, h] = cropArg ? [cropArg[2], cropArg[3]] : [fw, fh];
      const name = `${outPrefix}${stem}${post ? '_beauty' : ''}.png`;
      const t = Date.now();
      const r = await page.evaluate(([v, rig, w, h, p, post, crop]) => window.__viewer.capture(v, rig, w, h, p ?? undefined, post, 0, crop ? { crop } : {}), [v, rig, fw, fh, poseArg, post, cropArg]);
      const px = Buffer.from(r.b64, 'base64');
      if (px.length !== w * h * 4) throw new Error(`${v}: got ${px.length} bytes for ${w}x${h}`);
      await writeFile(join(build, name), png(w, h, px));
      shots.push({ view: v, rig, post, file: name, res: [w, h], crop: cropArg, render_ms: r.ms, wall_ms: Date.now() - t, draw_calls: r.draw_calls, triangles: r.triangles, lights: r.lights, pose: poseArg, weights: r.weights });
      console.error(`[engine_shots] ${backend} ${name} ${w}x${h}: ${Date.now() - t} ms`);
    }
    const turntable = ttSeconds > 0 ? await captureTurntable(page, backend) : null;
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
    let chart = null;
    if (wantChart) {
      const cj = JSON.parse(await readFile(join(build, 'chart.json'), 'utf8'));
      const [cw, ch] = cj.res;
      const qc = new URLSearchParams(q);
      qc.set('scene', 'chart');
      await page.goto(`http://127.0.0.1:${port}/character.html?${qc}`, { waitUntil: 'load' });
      await page.waitForFunction(() => window.__viewerState?.ready || window.__viewerState?.phase === 'error', null, { timeout: timeoutS * 1000, polling: 500 });
      const sc = await page.evaluate(() => window.__viewerState);
      if (sc.phase === 'error') throw new Error(`chart viewer error: ${sc.error}`);
      const t = Date.now();
      const r = await page.evaluate(([w, h]) => window.__viewer.captureChart(w, h, false), [cw, ch]);
      await writeFile(join(build, `${outPrefix}chart.png`), png(cw, ch, Buffer.from(r.b64, 'base64')));
      const rl = await page.evaluate(([w, h]) => window.__viewer.captureChart(w, h, true), [cw, ch]);
      await writeFile(join(build, `${outPrefix}chart_linear.npy`), npy(Buffer.from(rl.b64, 'base64'), [ch, cw, 4]));
      chart = { file: `${outPrefix}chart.png`, linear: `${outPrefix}chart_linear.npy`, res: [cw, ch], render_ms: r.ms, frames: r.frames, grade: r.grade, lights: r.lights, wall_ms: Date.now() - t, warnings: sc.warnings };
      console.error(`[engine_shots] ${backend} chart ${cw}x${ch}: ${Date.now() - t} ms`);
    }
    const adapter = await page.evaluate(async () => {
      try {
        const a = await navigator.gpu?.requestAdapter();
        return a ? { vendor: a.info.vendor, architecture: a.info.architecture, description: a.info.description } : null;
      } catch {
        return null;
      }
    });
    return { ok: true, backend: st.backend, adapter, boot_ms: bootMs, load: st.load, verify: st.verify, warnings: st.warnings, hair_maps: st.hairMaps, hair_prepass: st.hairPrepass, gaze: st.gaze, stats, shots, turntable, balls, chart, browser: browser.version(), console: [...new Set(log)].slice(0, 40) };
  } finally {
    await browser.close();
  }
}

// ------------------------------------------------------------------ turntable (T10)
/** The --tt-view frames while the model turns (TT_DEG_PER_S, --tt-fps) for --turntable seconds: PNGs in
 * RUN/<prefix>turntable/, an H.264 <prefix>turntable.mp4 (ffmpeg, when present), and per frame the
 * temporal noise: mean |L(t-1) - 2 L(t) + L(t+1)| of the luma (0..255). A second difference cancels
 * the smooth turn to first order, so what stays is frame-to-frame flicker: shimmer, crawling
 * highlights, alpha-to-coverage and PCF noise. */
async function captureTurntable(page, backend) {
  const [v, rig, stem] = viewSpec(ttView);
  const n = Math.max(3, Math.round(ttSeconds * ttFps));
  const dir = join(build, `${outPrefix}turntable`);
  await mkdir(dir, { recursive: true });
  const lumas = [];
  const frames = [];
  const t0 = Date.now();
  // temporal AA: render at ttHz with a history (warm-up, in-between frames), write every (ttHz / ttFps)-th
  const aaMode = (await page.evaluate(() => window.__viewer.stats().aa?.mode)) ?? 'msaa';
  const temporal = aaMode !== 'msaa';
  const sub = temporal ? Math.round(ttHz / ttFps) : 1;
  if (temporal && Math.abs(sub * ttFps - ttHz) > 1e-6) throw new Error(`--tt-hz ${ttHz} must be a multiple of --tt-fps ${ttFps}`);
  const stepDeg = TT_DEG_PER_S / (ttFps * sub);
  if (temporal) {
    const warm = Math.max(0, ttWarmup);
    // the view, pose and a fresh history at the first warm-up angle, then turn into frame 0
    await page.evaluate(([v, rig, w, h, p, a, crop]) => window.__viewer.capture(v, rig, w, h, p ?? undefined, false, a, crop ? { frames: 1, crop } : { frames: 1 }), [v, rig, ttSize, ttSize, poseArg, -warm * stepDeg, ttCrop]);
    for (let k = warm - 1; k >= 1; k--) await page.evaluate(([a, w, crop]) => window.__viewer.advance(a, w, w, crop ?? undefined), [-k * stepDeg, ttSize, ttCrop]);
  }
  const [tw, th] = ttCrop ? [ttCrop[2], ttCrop[3]] : [ttSize, ttSize];
  for (let i = 0; i < n; i++) {
    const deg = (i / ttFps) * TT_DEG_PER_S;
    if (temporal) for (let k = sub - 1; k >= 1; k--) await page.evaluate(([a, w, crop]) => window.__viewer.advance(a, w, w, crop ?? undefined), [deg - k * stepDeg, ttSize, ttCrop]);
    const r = temporal
      ? await page.evaluate(([v, rig, w, h, p, a, crop]) => window.__viewer.capture(v, rig, w, h, p ?? undefined, false, a, crop ? { keep: true, frames: 1, crop } : { keep: true, frames: 1 }), [v, rig, ttSize, ttSize, poseArg, deg, ttCrop])
      : await page.evaluate(([v, rig, w, h, p, a, crop]) => window.__viewer.capture(v, rig, w, h, p ?? undefined, false, a, crop ? { crop } : {}), [v, rig, ttSize, ttSize, poseArg, deg, ttCrop]);
    const px = Buffer.from(r.b64, 'base64');
    const file = `frame_${String(i).padStart(3, '0')}.png`;
    await writeFile(join(dir, file), png(tw, th, px));
    const L = new Float32Array(tw * th);
    for (let k = 0; k < L.length; k++) L[k] = 0.2126 * px[k * 4] + 0.7152 * px[k * 4 + 1] + 0.0722 * px[k * 4 + 2];
    lumas.push(L);
    frames.push({ file, deg: +deg.toFixed(3), render_ms: r.ms });
    console.error(`[engine_shots] ${backend} turntable ${i + 1}/${n} ${deg.toFixed(2)} deg: ${r.ms} ms`);
  }
  const noise = [];
  for (let i = 1; i + 1 < n; i++) {
    const [a, b, c] = [lumas[i - 1], lumas[i], lumas[i + 1]];
    let s = 0;
    for (let k = 0; k < b.length; k++) s += Math.abs(a[k] - 2 * b[k] + c[k]);
    noise.push(+(s / b.length).toFixed(4));
  }
  let video = null;
  const ff = spawnSync('ffmpeg', ['-loglevel', 'error', '-y', '-framerate', String(ttFps), '-i', join(dir, 'frame_%03d.png'), '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '12', join(build, `${outPrefix}turntable.mp4`)]);
  if (ff.status === 0) video = `${outPrefix}turntable.mp4`;
  const mean = noise.reduce((x, y) => x + y, 0) / Math.max(1, noise.length);
  return { view: v, rig, stem, seconds: ttSeconds, fps: ttFps, aa: aaMode, hz: temporal ? ttHz : ttFps, warmup: temporal ? ttWarmup : 0, deg_per_s: TT_DEG_PER_S, res: [ttSize, ttSize], crop: ttCrop, frames, dir: `${outPrefix}turntable`, video, temporal_noise: noise, temporal_noise_mean: +mean.toFixed(4), wall_ms: Date.now() - t0 };
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

/** --texcheck: the texture audit per view x variant, each a fresh page (the pipelines of that config only). */
async function runTexcheck() {
  const variants = texcheckArg && !texcheckArg.startsWith('--') ? texcheckArg.split(';') : TEXCHECK_VARIANTS;
  const browser = await chromium.launch({ headless: true, channel: 'chromium', args: ARGS });
  const runs = [];
  try {
    for (const variant of variants) {
      for (const spec of views) {
        const [v, rig] = viewSpec(spec);
        const posts = v === 'portrait' && beauty ? [false, true] : [false];
        const page = await browser.newPage({ viewport: { width: 256, height: 256 } });
        const errors = [];
        page.on('console', (m) => m.type() === 'error' && errors.push(m.text().slice(0, 300)));
        page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`.slice(0, 300)));
        page.setDefaultTimeout(timeoutS * 1000);
        const q = new URLSearchParams({ asset: '.', capture: '1', ui: '0', dpr: '1', view: v, rig });
        for (const [k, val] of new URLSearchParams(extraQuery)) q.set(k, val);
        for (const [k, val] of new URLSearchParams(variant)) q.set(k, val);
        const t = Date.now();
        await page.goto(`http://127.0.0.1:${port}/character.html?${q}`, { waitUntil: 'load' });
        await page.waitForFunction(() => window.__viewerState?.ready || window.__viewerState?.phase === 'error', null, { timeout: timeoutS * 1000, polling: 500 });
        const st = await page.evaluate(() => window.__viewerState);
        if (st.phase === 'error') throw new Error(`viewer error: ${st.error}`);
        for (const post of posts) {
          const a = await page.evaluate(([v, rig, post]) => window.__viewer.textureAudit(v, rig, 128, 128, post), [v, rig, post]);
          // the pipeline errors of an over-limit shader arrive asynchronously
          await page.waitForTimeout(500);
          runs.push({ variant: variant || '(default)', view: spec, post, ...a, console_errors: [...new Set(errors)].slice(0, 10), wall_ms: Date.now() - t });
          const top = a.materials.slice(0, 3).map((m) => `${m.material} ${m.fragment}`).join(', ');
          console.error(`[engine_shots] texcheck ${variant || '(default)'} ${spec}${post ? ' beauty' : ''}: max ${a.max_fragment} frag / ${a.max_vertex} vert (${a.shadow_maps} maps; ${top}), ${a.over.length} over, ${errors.length} console errors`);
        }
        await page.close();
      }
    }
  } finally {
    await browser.close();
  }
  const over = runs.flatMap((r) => r.over.map((o) => ({ variant: r.variant, view: r.view, post: r.post, ...o })));
  // per material, the worst over every run
  const worst = {};
  for (const r of runs)
    for (const m of r.materials) if (!worst[m.material] || m.fragment > worst[m.material].fragment) worst[m.material] = { ...m, variant: r.variant, view: r.view, post: r.post };
  const out = { build, when: new Date().toISOString(), limit: 16, ok: over.length === 0, max_fragment: Math.max(0, ...runs.map((r) => r.max_fragment)), over, worst_per_material: Object.values(worst).sort((a, b) => b.fragment - a.fragment), runs };
  await writeFile(join(build, `${outPrefix}texcheck.json`), JSON.stringify(out, null, 1));
  console.log(JSON.stringify({ ok: out.ok, max_fragment: out.max_fragment, over: over.length, worst: out.worst_per_material.slice(0, 6).map((m) => `${m.material}: ${m.fragment} (${m.variant} ${m.view})`) }, null, 1));
  return out.ok;
}

if (texcheckArg !== null) {
  let ok = false;
  try {
    ok = await runTexcheck();
  } catch (e) {
    console.error(`[engine_shots] texcheck failed: ${String(e?.message ?? e).slice(0, 500)}`);
  }
  server.close();
  process.exit(ok ? 0 : 1);
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
