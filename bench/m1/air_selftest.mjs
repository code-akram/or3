#!/usr/bin/env node
// Stand-in for the Air (T24): drive a device-capture URL (?capture=1&upload=1[&tiers=...]) in local
// headless Chromium on SwiftShader, through every tier's page load, until the page reports `uploaded`
// (or an error), and print the console errors and page errors seen on the way. Use it against the Vite
// dev server (npm run dev, or `npx vite --port 8797` for a test) to check the upload round trip of
// bench/m1/v4/air-session.md without the Mac. SwiftShader timings are not the Air's.
//
//   node bench/m1/air_selftest.mjs --url 'http://127.0.0.1:8797/character.html?...&capture=1&upload=1' [--timeout 3600]
//        [--viewport 640x360]
//   node bench/m1/air_selftest.mjs --live 60 --url '...character.html?...&perf=1': the overlay runs S seconds, then "save"
// Run it under taskset on the shared machine.
import { chromium } from 'playwright';

const argv = process.argv.slice(2);
const opt = (n, d) => {
  const i = argv.indexOf(`--${n}`);
  return i >= 0 ? argv[i + 1] : d;
};
const url = opt('url', null);
if (!url || !/^http:\/\/127\.0\.0\.1:\d+\//.test(url)) {
  console.error('usage: air_selftest.mjs --url http://127.0.0.1:PORT/character.html?...&capture=1&upload=1 [--timeout S]');
  process.exit(2);
}
const timeoutS = Number(opt('timeout', 3600));
const liveS = Number(opt('live', 0)); // --live S: the ?perf=1 overlay instead of a capture
const [vw, vh] = opt('viewport', '640x360').split('x').map(Number);
const ARGS = ['--enable-unsafe-webgpu', '--enable-unsafe-swiftshader', '--enable-features=Vulkan', '--use-vulkan=swiftshader', '--use-angle=swiftshader', '--use-webgpu-adapter=swiftshader', '--disable-vulkan-surface', '--renderer-process-limit=1'];
const browser = await chromium.launch({ headless: true, channel: 'chromium', args: ARGS });
const errors = [];
const pages = [];
let result = { ok: false };
try {
  const page = await browser.newPage({ viewport: { width: vw, height: vh } });
  // each error with the step the HUD showed last (which tier, which phase)
  let lastHud = '';
  page.on('console', (m) => {
    if (m.type() === 'error') errors.push(`console: ${m.text()}`.slice(0, 300) + (lastHud ? `  [at: ${lastHud.slice(0, 120)}]` : ''));
  });
  page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`.slice(0, 300)));
  page.on('response', (r) => {
    if (r.status() >= 400) errors.push(`http ${r.status()}: ${r.url().replace(/^http:\/\/127\.0\.0\.1:\d+/, '')}`.slice(0, 300));
  });
  page.on('framenavigated', (f) => {
    if (f === page.mainFrame()) pages.push(f.url().replace(/^http:\/\/127\.0\.0\.1:\d+/, ''));
  });
  const t0 = Date.now();
  await page.goto(url, { waitUntil: 'load' });
  let st = null;
  if (liveS > 0) {
    // the ?perf=1 overlay: run, then "save" (POST /upload/live_perf.json) and wait for its answer
    await page.waitForFunction(() => window.__viewerState?.ready || window.__viewerState?.phase === 'error', null, { timeout: timeoutS * 1000, polling: 1000 });
    await new Promise((r) => setTimeout(r, liveS * 1000));
    const pre = await page.evaluate(() => ({ phase: window.__viewerState?.phase, error: window.__viewerState?.error ?? null, warnings: window.__viewerState?.warnings ?? [] }));
    if (pre.phase === 'error') throw new Error(`viewer error: ${String(pre.error).slice(0, 400)}`);
    // a SwiftShader hero frame is ~10 s; the click's stability check needs two of them
    await page.getByRole('button', { name: 'save' }).click({ timeout: timeoutS * 1000 });
    await page.waitForFunction(() => [...document.querySelectorAll('button')].some((b) => /^(saved|downloaded)/.test(b.textContent ?? '')), null, { timeout: timeoutS * 1000, polling: 1000 });
    const out = await page.evaluate(() => ({
      phase: window.__viewerState.phase,
      button: [...document.querySelectorAll('button')].map((b) => b.textContent).find((t) => /^(saved|downloaded)/.test(t ?? '')),
      overlay: [...document.querySelectorAll('div')].map((d) => d.textContent ?? '').find((t) => t.includes('per pass')) ?? null,
    }));
    result = { ok: /^saved/.test(out.button ?? '') && errors.length === 0, live_s: liveS, ...out, seconds: Math.round((Date.now() - t0) / 1000), console_errors: errors };
  }
  while (!liveS && Date.now() - t0 < timeoutS * 1000) {
    await new Promise((r) => setTimeout(r, 2000));
    try {
      st = await page.evaluate(() => {
        const s = window.__viewerState;
        return s ? { phase: s.phase, error: s.error ?? null, warnings: s.warnings, hud: document.getElementById('hud')?.textContent ?? '' } : null;
      });
    } catch {
      continue; // navigating to the next tier
    }
    if (st?.hud) lastHud = st.hud.split('\n')[0];
    if (st && (st.phase === 'uploaded' || st.phase === 'error')) break;
  }
  if (!liveS) result = { ok: st?.phase === 'uploaded' && errors.length === 0, phase: st?.phase ?? null, error: st?.error ?? null, hud: st?.hud ?? null, warnings: st?.warnings ?? [], seconds: Math.round((Date.now() - t0) / 1000), pages, console_errors: errors };
} catch (e) {
  result = { ok: false, failure: String(e?.message ?? e).slice(0, 600), console_errors: errors };
} finally {
  await browser.close();
}
console.log(JSON.stringify(result, null, 1));
process.exit(result.ok ? 0 : 1);
