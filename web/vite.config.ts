import { defineConfig } from 'vite';

// SharedArrayBuffer (WASM threads) needs a cross-origin isolated page.
// Keep in sync with public/_headers (Cloudflare Pages) and bench/server.mjs.
const isolation = {
  'Cross-Origin-Opener-Policy': 'same-origin',
  'Cross-Origin-Embedder-Policy': 'require-corp',
  'Cross-Origin-Resource-Policy': 'same-origin',
};

export default defineConfig({
  server: { host: '127.0.0.1', port: 5173, strictPort: true, headers: isolation },
  preview: { host: '127.0.0.1', port: 4173, strictPort: true, headers: isolation },
  worker: { format: 'es' },
  build: {
    target: 'esnext',
    sourcemap: false,
    reportCompressedSize: true,
    // The WASM core is fetched as a separate asset; never inline it.
    assetsInlineLimit: 0,
  },
});
