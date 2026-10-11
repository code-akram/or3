#!/usr/bin/env node
// Headless smoke test of the production build on this (GPU-less) Linux box:
// boots the page in Playwright Chromium (WebGPU on SwiftShader), checks cross-origin isolation,
// that the WASM worker thread ticks, and that telemetry reaches the bench server.
//
//   node bench/headless-check.mjs [--seconds 20] [--port 8788] [--shot capture.ppm] [--query k=v]
//
// Frame numbers from this machine are NOT representative of the M4 Air.
import { spawn } from 'node:child_process';
import { readFile, readdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const here = fileURLToPath(new URL('.', import.meta.url));
const argv = process.argv.slice(2);
const opt = (n, d) => {
  const i = argv.indexOf(`--${n}`);
  return i >= 0 ? argv[i + 1] : d;
};
const seconds = Number(opt('seconds', 20));
const port = Number(opt('port', 8788));
const shot = opt('shot', null);
// 'chromium' = full Chromium in new headless mode (better WebGPU); default Playwright uses headless-shell.
const channel = opt('channel', 'chromium');
const extraQuery = opt('query', '');
const outDir = join(here, 'm0', 'telemetry');

const server = spawn(process.execPath, [join(here, 'server.mjs'), '--port', String(port), '--out', outDir], { stdio: ['ignore', 'pipe', 'inherit'] });
let serverLog = '';
server.stdout.on('data', (d) => (serverLog += d));
await new Promise((r) => setTimeout(r, 500));

const result = { ok: false, checks: {}, notes: [] };
const browser = await chromium.launch({
  headless: true,
  channel,
  // Found by trial (Chromium 156, no GPU, no X): without Vulkan-on-SwiftShader plus
  // --disable-vulkan-surface the WebGPU canvas swap chain cannot allocate its shared image and the
  // device is lost on first present ("Instance dropped in popErrorScope").
  args: [
    '--enable-unsafe-webgpu',
    '--enable-unsafe-swiftshader',
    '--enable-features=Vulkan',
    '--use-vulkan=swiftshader',
    '--use-angle=swiftshader',
    '--use-webgpu-adapter=swiftshader',
    '--disable-vulkan-surface',
    '--enable-precise-memory-info',
  ],
});
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  const consoleLines = [];
  page.on('console', (m) => consoleLines.push(`${m.type()}: ${m.text()}`));
  page.on('pageerror', (e) => consoleLines.push(`pageerror: ${e.message}`));

  const resp = await page.goto(`http://127.0.0.1:${port}/?label=headless-linux&window=2&memEvery=6${extraQuery ? '&' + extraQuery : ''}`, { waitUntil: 'load' });
  const h = resp.headers();
  result.checks.coop = h['cross-origin-opener-policy'];
  result.checks.coep = h['cross-origin-embedder-policy'];

  await page.waitForFunction(() => ['running', 'error'].includes(window.__boot?.phase), null, { timeout: 60000 });
  const t0 = Date.now();
  await page.waitForTimeout(seconds * 1000);
  const boot = await page.evaluate(() => window.__boot);
  const elapsed = (Date.now() - t0) / 1000;
  result.boot = boot;
  result.checks.crossOriginIsolated = boot.crossOriginIsolated === true;
  result.checks.running = boot.phase === 'running';
  result.checks.webgpuBackend = boot.backend === 'webgpu';
  result.checks.workerTicking = (boot.workerTicks ?? 0) > 30 * elapsed;
  result.checks.telemetryPosted = (boot.telemetryOk ?? 0) >= 2;
  result.hud = await page.evaluate(() => document.getElementById('hud')?.textContent ?? '');
  // The WebGPU canvas does not reach headless screenshots, so read back an offscreen render.
  // Width is a multiple of 64 so WebGPU readback rows (256-byte aligned) are unpadded.
  const [cw, ch] = [512, 320];
  const b64 = await page.evaluate(([w, h]) => window.__capture(w, h), [cw, ch]);
  const px = Buffer.from(b64, 'base64');
  let lit = 0;
  let neon = 0;
  for (let i = 0; i < px.length; i += 4) {
    const [r, g, b] = [px[i], px[i + 1], px[i + 2]];
    if (r + g + b > 30) lit++;
    if (Math.max(r, g, b) - Math.min(r, g, b) > 60) neon++;
  }
  result.capture = { width: cw, height: ch, litFraction: +(lit / (cw * ch)).toFixed(3), saturatedFraction: +(neon / (cw * ch)).toFixed(3) };
  result.checks.rendersBones = neon / (cw * ch) > 0.005;
  if (shot) {
    // Binary PPM (P6); convert with e.g. `ffmpeg -i x.ppm x.png`.
    const rgb = Buffer.alloc(cw * ch * 3);
    for (let i = 0, j = 0; i < px.length; i += 4, j += 3) px.copy(rgb, j, i, i + 3);
    await writeFile(shot, Buffer.concat([Buffer.from(`P6\n${cw} ${ch}\n255\n`), rgb]));
  }
  // De-duplicate repeated console lines (first 200 chars) so the report stays readable.
  const seen = new Map();
  for (const l of consoleLines) {
    const k = l.slice(0, 200);
    seen.set(k, (seen.get(k) ?? 0) + 1);
  }
  result.console = [...seen].map(([k, n]) => (n > 1 ? `${n}x ${k}` : k));

  // Telemetry must be on disk, written by the server.
  const files = (await readdir(outDir)).filter((f) => f.startsWith(boot.session ?? '?'));
  const lines = files.length ? (await readFile(join(outDir, files[0]), 'utf8')).trim().split('\n') : [];
  result.checks.telemetryOnDisk = lines.some((l) => l.includes('"type":"meta"')) && lines.some((l) => l.includes('"type":"window"'));
  result.telemetryFile = files[0] ?? null;
  result.telemetryLines = lines.length;
  result.ok = Object.values(result.checks).every((v) => v === true || typeof v === 'string');
} catch (e) {
  result.error = String(e?.stack ?? e);
} finally {
  await browser.close();
  server.kill();
}
console.log(JSON.stringify(result, null, 2));
process.exit(result.ok ? 0 : 1);
