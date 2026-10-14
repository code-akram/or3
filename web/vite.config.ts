import { defineConfig } from 'vite';
import { buildEntries, characterAssets } from './character-assets.mjs';

// SharedArrayBuffer (WASM threads) needs a cross-origin isolated page.
// Keep in sync with public/_headers (Cloudflare Pages) and bench/server.mjs.
const isolation = {
  'Cross-Origin-Opener-Policy': 'same-origin',
  'Cross-Origin-Embedder-Policy': 'require-corp',
  'Cross-Origin-Resource-Policy': 'same-origin',
};

const here = new URL('.', import.meta.url).pathname;
// Both pages into dist/, or only the character viewer into dist-viewer/ (VIEWER_ONLY=1).
const entries = buildEntries(here);

export default defineConfig({
  // Character viewer assets (dev only): /asset/ -> <main>/data/build, or CHARACTER_ASSET_ROOT.
  plugins: [characterAssets(here, isolation)],
  server: { host: '127.0.0.1', port: 5173, strictPort: true, headers: isolation },
  preview: { host: '127.0.0.1', port: 4173, strictPort: true, headers: isolation },
  worker: { format: 'es' },
  build: {
    target: 'esnext',
    outDir: entries.outDir,
    sourcemap: false,
    reportCompressedSize: true,
    // The WASM core is fetched as a separate asset; never inline it.
    assetsInlineLimit: 0,
    rolldownOptions: { input: entries.input },
  },
});
