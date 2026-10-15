// Vite dev-server plugin for the character viewer: GET /asset/<path> serves files from ONE root.
// Default root: <main checkout>/data/build (public builds). CHARACTER_ASSET_ROOT=<absolute dir>
// replaces it with exactly that directory (e.g. one private fan run dir); the two are never served
// together. The dev server binds 127.0.0.1 only (vite.config.ts server.host).
// T24: POST /upload/<name>?session=<id> (device capture and the ?perf=1 overlay, upload-sink.mjs) writes
// into <root>/air/<id>/ with the default root; with CHARACTER_ASSET_ROOT set, only into
// CHARACTER_UPLOAD_DIR=<absolute dir>/<id>/ when that is given (no upload otherwise).
import { execFileSync } from 'node:child_process';
import { createReadStream, realpathSync, statSync } from 'node:fs';
import { dirname, extname, isAbsolute, join, normalize, resolve, sep } from 'node:path';
import { SESSION, receiveUpload } from './upload-sink.mjs';

/** Build inputs: both pages, or only the character viewer (VIEWER_ONLY=1, into dist-viewer/, so
 * bench/m1/engine_shots.sh needs neither the WASM core nor touches the spike page's dist/). */
export function buildEntries(here) {
  const viewerOnly = process.env.VIEWER_ONLY === '1';
  return {
    outDir: viewerOnly ? 'dist-viewer' : 'dist',
    input: viewerOnly ? { character: here + 'character.html' } : { main: here + 'index.html', character: here + 'character.html' },
  };
}

const MIME = { '.glb': 'model/gltf-binary', '.json': 'application/json', '.png': 'image/png', '.ktx2': 'image/ktx2' };

/** @param {string} here  the web/ directory @param {Record<string,string>} headers */
export function characterAssets(here, headers) {
  return {
    name: 'character-assets',
    apply: 'serve',
    configureServer(server) {
      const override = process.env.CHARACTER_ASSET_ROOT;
      let root;
      if (override) {
        if (!isAbsolute(override)) throw new Error('CHARACTER_ASSET_ROOT must be absolute');
        root = realpathSync(resolve(override));
      } else {
        const common = execFileSync('git', ['-C', here, 'rev-parse', '--path-format=absolute', '--git-common-dir'], {
          encoding: 'utf8',
        }).trim();
        root = realpathSync(join(dirname(common), 'data', 'build'));
      }
      server.config.logger.info(`[character-assets] /asset/ -> ${root}`);
      const upOverride = process.env.CHARACTER_UPLOAD_DIR;
      if (upOverride && !isAbsolute(upOverride)) throw new Error('CHARACTER_UPLOAD_DIR must be absolute');
      const uploadRoot = upOverride ? resolve(upOverride) : override ? null : join(root, 'air');
      server.config.logger.info(`[character-assets] /upload/ -> ${uploadRoot ? uploadRoot + '/<session>/' : 'off (CHARACTER_ASSET_ROOT without CHARACTER_UPLOAD_DIR)'}`);
      server.middlewares.use('/upload', (req, res, next) => {
        if (req.method !== 'POST') return next();
        const [path, query] = (req.url ?? '/').split('?');
        const session = new URLSearchParams(query ?? '').get('session') ?? '';
        const fail = (code) => {
          res.writeHead(code, { ...headers, 'content-type': 'text/plain' });
          res.end(String(code));
        };
        if (!uploadRoot || !SESSION.test(session)) return fail(403);
        const name = decodeURIComponent(path.replace(/^\/+/, ''));
        receiveUpload(req, name, join(uploadRoot, session), { session })
          .then((r) => {
            if (r.status === 200) server.config.logger.info(`[character-assets] upload ${session}/${r.name} (${r.bytes} bytes)`);
            fail(r.status);
          })
          .catch(() => fail(500));
      });
      server.middlewares.use('/asset', (req, res, next) => {
        if (req.method !== 'GET' && req.method !== 'HEAD') return next();
        let file;
        try {
          // resolve symlinks (lookdev/latest), then re-check containment
          file = realpathSync(normalize(join(root, decodeURIComponent((req.url ?? '/').split('?')[0]))));
        } catch {
          res.statusCode = 404;
          return res.end('not found');
        }
        const type = MIME[extname(file)];
        if (!file.startsWith(root + sep) || !type) {
          res.statusCode = 403;
          return res.end('forbidden');
        }
        let st = null;
        try {
          st = statSync(file);
        } catch {
          st = null;
        }
        if (!st || !st.isFile()) {
          res.statusCode = 404;
          return res.end('not found');
        }
        res.writeHead(200, { ...headers, 'content-type': type, 'content-length': st.size, 'cache-control': 'no-store' });
        if (req.method === 'HEAD') return res.end();
        createReadStream(file).pipe(res);
      });
    },
  };
}
