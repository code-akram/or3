#!/usr/bin/env node
// Stand-in for the Air (T24): drive a device-capture URL (?capture=1&upload=1[&tiers=...]) in local
// headless Chromium on SwiftShader, through every tier's page load, until the page reports `uploaded`
// (or an error), and print the console errors and page errors seen on the way. Use it against the Vite
// dev server (npm run dev, or `npx vite --port 8797` for a test) to check the upload round trip of
// bench/m1/v4/air-session.md without the Mac. SwiftShader timings are not the Air's.
//
//   node bench/m1/air_selftest.mjs --url 'http://127.0.0.1:8797/character.html?...&capture=1&upload=1' [--timeout 3600]
//        [--viewport 640x360]
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
const [vw, vh] = opt('viewport', '640x360').split('x').map(Number);
const ARGS = ['--enable-unsafe-webgpu', '--enable-unsafe-swiftshader', '--enable-features=Vulkan', '--use-vulkan=swiftshader', '--use-angle=swiftshader', '--use-webgpu-adapter=swiftshader', '--disable-vulkan-surface', '--renderer-process-limit=1'];
const browser = await chromium.launch({ headless: true, channel: 'chromium', args: ARGS });
const errors = [];
const pages = [];
let result = { ok: false };
try {
  const page = await browser.newPage({ viewport: { width: vw, height: vh } });
  page.on('console', (m) => {
    if (m.type() === 'error') errors.push(`console: ${m.text()}`.slice(0, 300));
  });
  page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`.slice(0, 300)));
  page.on('framenavigated', (f) => {
    if (f === page.mainFrame()) pages.push(f.url().replace(/^http:\/\/127\.0\.0\.1:\d+/, ''));
  });
  const t0 = Date.now();
  await page.goto(url, { waitUntil: 'load' });
  let st = null;
  while (Date.now() - t0 < timeoutS * 1000) {
    await new Promise((r) => setTimeout(r, 2000));
    try {
      st = await page.evaluate(() => {
        const s = window.__viewerState;
        return s ? { phase: s.phase, error: s.error ?? null, warnings: s.warnings, hud: document.getElementById('hud')?.textContent ?? '' } : null;
      });
    } catch {
      continue; // navigating to the next tier
    }
    if (st && (st.phase === 'uploaded' || st.phase === 'error')) break;
  }
  result = { ok: st?.phase === 'uploaded' && errors.length === 0, phase: st?.phase ?? null, error: st?.error ?? null, hud: st?.hud ?? null, warnings: st?.warnings ?? [], seconds: Math.round((Date.now() - t0) / 1000), pages, console_errors: errors };
} finally {
  await browser.close();
}
console.log(JSON.stringify(result, null, 1));
process.exit(result.ok ? 0 : 1);
