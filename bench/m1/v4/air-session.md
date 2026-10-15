# Air session: the first device capture (T24, about 10 minutes)

This is the first time the viewer runs on the M4 Air. Every engine number so far comes from SwiftShader. In one page load per quality tier, the Air captures its own frames and timings and uploads them to this machine. You click two links and save two overlays. Nothing else is needed from you.

## Before you start (on this machine, `archlinux`)

1. Start the dev server from the main checkout and leave it running:
   ```bash
   cd ~/code/or3/web && npm run dev
   ```
   It binds 127.0.0.1:5173. It serves `/asset/` from `data/build` and writes uploads to `data/build/air/<session>/`. Its log prints one line per received file.
2. The asset is the T24 build `data/build/lookdev/20261015T045719Z-t24-a1`, which is the T20 character (main since T20/T19). It holds:
   - `character.ktx2.glb` (166k tris, 45 MB) for the hero tier;
   - `character.lod1.ktx2.glb` (57.9k tris, 38 MB) for the gameplay tier;
   - `engine_stage.json`, `grade_lut.json` and `set_bounce.json`.

## On the Mac

| # | Step | Time |
|---|---|---|
| 0 | Plug in. Turn off Low Power Mode. Quit heavy apps. Use Chrome, which has WebGPU and `timestamp-query`.<br>Optional, once: `chrome://flags/#enable-webgpu-developer-features` → Enabled, then Relaunch. Without it Chrome rounds every GPU timestamp to 0.1 ms. The means stay usable; the per-pass p50s become 0.1 ms steps. | 1 min |
| 1 | In Terminal, open the tunnel and leave it open:<br>`ssh -N -L 5173:127.0.0.1:5173 archlinux` | 0.5 min |
| 2 | **Both tiers, automatic.** Open a new Chrome window and press **Ctrl+Cmd+F** for full screen. Then open:<br>`http://127.0.0.1:5173/character.html?asset=lookdev/20261015T045719Z-t24-a1&ktx2=1&dpr=1&ui=0&capture=1&upload=1&tiers=hero,gameplay&session=air1`<br>Don't touch the page and keep it in front. The HUD (top left) shows each step. Per tier, the page loads, then:<br>• captures the stills;<br>• renders a 2 s turntable (48 frames);<br>• runs a 600-frame perf loop at the window size;<br>• runs a 30-frame synced per-pass profile;<br>• uploads everything.<br>The page then reloads itself for the gameplay tier and repeats. It is finished when the HUD says `done (session air1)`. | 4–5 min |
| 3 | **Hero tier, live.** Open:<br>`http://127.0.0.1:5173/character.html?asset=lookdev/20261015T045719Z-t24-a1&ktx2=1&dpr=1&tier=hero&view=portrait&perf=1&session=air1-live-hero`<br>Let it run for 30 s; the overlay at bottom left fills. Optionally, tick `turntable` in the panel to see it in motion. Then click **save** in the overlay.<br>If the HUD shows `! adapter allows 16 sampled textures…`, or the character has no eyes or is missing, reload with `&shadows=key,rim,kicker` added to the URL and `session=air1-live-hero3` (see *If something goes wrong*). | 1.5 min |
| 4 | **Gameplay tier, live.** Open:<br>`http://127.0.0.1:5173/character.html?asset=lookdev/20261015T045719Z-t24-a1&ktx2=1&dpr=1&tier=gameplay&view=gameplay&rig=hero&perf=1&session=air1-live-gameplay`<br>Same as step 3: 30 s, then **save**. While it runs, press **Shift+Esc** (Chrome Task Manager) and note the tab's *Memory footprint* and *GPU memory*. | 1.5 min |
| 4b | **G1: gameplay grounding and texture LOD (A/B), automatic.** Two links, one after the other. Each loads the G1 asset (`lookdev/20261015T094709Z-g1-a2`: the texture-LOD `character.lod1.ktx2.glb`, 23 MB), captures the gameplay tier and uploads, like step 2 (about 1.5 min each). Capsule floor shadows on (the tier default):<br>`http://127.0.0.1:5173/character.html?asset=lookdev/20261015T094709Z-g1-a2&ktx2=1&dpr=1&ui=0&capture=1&upload=1&tiers=gameplay&texcheck=1&session=air1-g1`<br>Capsule floor shadows off (the A/B for their cost):<br>`http://127.0.0.1:5173/character.html?asset=lookdev/20261015T094709Z-g1-a2&ktx2=1&dpr=1&ui=0&capture=1&upload=1&tiers=gameplay&texcheck=1&floorshadow=0&session=air1-g1-off`<br>`texcheck=1` puts the per-material texture count and the live GPU texture memory in `gameplay_shots.json` (`texture_audit`, `texture_memory`). | 3 min |
| 5 | Close the tunnel (Ctrl+C) and tell Claude: "Air session done, air1". | — |

The total is about 12–13 minutes with step 4b (9–10 without). Step 2 is the long one. Most of its time is transfer, because `archlinux` is a remote host: the two GLBs come down the tunnel (83 MB) and about 25 MB of PNG frames go up. The GPU work itself takes seconds. If a step fails, the page shows a red box. Take a screenshot and send it; re-running a step with `session=air2` keeps the first run's files.

## What gets uploaded, and where it lands

Everything goes to `~/code/or3/data/build/air/<session>/` on this machine. The server accepts only the whitelisted names in `web/upload-sink.mjs`, and only into that directory.

| File | What |
|---|---|
| `hero_portrait.png`, `hero_portrait_beauty.png` | The portrait, 1920×1080: parity frame, and beauty frame (post, DoF, bounce) |
| `hero_closeup_hero.png`, `hero_gameplay_hero.png` | The hero-rig closeup and the gameplay framing (3 m), 1024² |
| `gameplay_gameplay_hero.png`, `gameplay_three_quarter.png`, `gameplay_closeup_hero.png` | The same views for the gameplay tier (LOD1) |
| `hero_tt/frame_000..047.png`, `gameplay_tt/…` | 2 s turntables at 24 fps, 640². Hero tier: the closeup; gameplay tier: the gameplay framing |
| `hero_perf.json`, `gameplay_perf.json` | **The perf report.** It records the tier and its switches, the adapter (vendor, architecture, `timestamp_query`, `max_sampled_textures_per_stage`), the canvas size, and stats (draws, tris, shadow maps, passes). Under `perf`:<br>• `frame_ms` (rAF interval), `cpu_render_ms` and `gpu_ms` (sum of the frame's pass timestamps), each as p50 / p95 / mean over 600 frames;<br>• `passes[]`, per label (each shadow map by light, the GTAO prepass, contact, the scene MRT, the TAA resolve, DoF, the post): `gpu_ms`, `cpu_ms` and `share`;<br>• `synced`, T19's profile: every frame waited for, per-pass p50 / p95. |
| `hero_shots.json`, `gameplay_shots.json` | Per-tier summary: the shots, the turntable's temporal noise, and the T6 keys `frame_ms_p50`, `gpu_ms_p50` |
| `session.json` | Written last. It closes the session. |
| `air1-live-hero/live_perf.json`, `air1-live-gameplay/live_perf.json` | The overlay's report from steps 3–4 (what you saw). These are in their own session directories. |

**G1 (step 4b).** Compare `air1-g1/gameplay_perf.json` with `air1-g1-off/gameplay_perf.json`. The capsule floor shadows add no pass, so the difference shows up only in the scene-MRT row of `passes[]` and in `gpu_ms`. In `texture_memory`, `material_mb` is the live GPU size of every sampled texture. The offline estimate (`bench/m1/v4/g1-gameplay-grounding.md`) is 51 MB for the gameplay tier against 115 MB for the hero tier. In `texture_audit`, `over` must be empty.

**Reading it.** The budget question is `gpu_ms.p50` per tier against checkpoint 3 §5.2:
- hero tier: 8.8–11.6 ms estimated;
- gameplay tier: 4.1–5.4 ms;
- the m2 criterion: max(CPU, GPU) p50 ≤ 12 ms.

`frame_ms` is display-paced (16.7 ms at 60 Hz), so it only shows whether a tier holds 60. If the hero tier misses, `passes[]` shows where the time goes, and the cut order is checkpoint 3 §5.3. Each cut is a URL switch (`web/src/character/tiers.ts`) and can be re-measured without a rebuild, for example `&tier=hero&dof=0&pcss=0`.

## If something goes wrong

- **Red box "no character.lod1.ktx2.glb"**: the gameplay tier falls back to LOD0 and says so in `stats.tier`. That is not fatal.
- **`timestamp_query: false` in the adapter**: the GPU columns are null; the per-pass rows are CPU encode times and `frame_ms` is still valid. Safari may not expose `timestamp-query`; use Chrome.
- **Step 3: the hero portrait fails live** (a warning on the HUD, or eyes missing, or the console showing `exceeds the maximum per-stage limit (16)`). In the live hero portrait the eye shader binds 18 textures: 5 PCSS shadow maps, contact shadows, the set-bounce environment and the eye's own maps. WebGPU's default is 16 per shader stage. The viewer asks for the adapter's limit; Chrome 146 and later offer up to 48 on capable GPUs. SwiftShader offers 16, so this step fails locally. If the Air also offers only 16, add `&shadows=key,rim,kicker` (3 shadowed lights; 16 textures). `hero_perf.json` → `adapter.max_sampled_textures_per_stage` records what the Air offers. The device capture (step 2) is not affected.
- **Upload 403**: the dev server was started with `CHARACTER_ASSET_ROOT`, which turns uploads off. Start it plainly.
- **Alternative server** (no Vite): `node bench/m1/engine_shots.mjs --build data/build/lookdev/20261015T045719Z-t24-a1 --serve --port 8798 --query 'ktx2=1&tiers=hero,gameplay'`, tunnel 8798 instead of 5173 (any free port; 8796–8797 belong to the engine runs), and open the printed URL. Uploads then land in the run dir, and the server exits after `session.json`.
