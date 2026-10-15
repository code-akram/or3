// Quality tiers and their per-feature switches (T24, bench/m1/v4/checkpoint-3.md §5.2-5.3).
//
//   ?tier=hero      the closeup / cinematic tier (the default: every feature on, as T10-T20 built them)
//   ?tier=gameplay  the third-person tier at 2.5-4 m (checkpoint 3 §5.2): one light shadowed at 1024, PCF,
//                   quarter-res GTAO, the baked hair occlusion instead of the deep hair shadow, no contact
//                   shadows, no DoF, no screen-space SSS, TAAU at 0.8, LOD1 (character.lod1[.ktx2].glb)
//
// Every switch below can be given on the URL as well and then wins over the tier (?tier=gameplay&gtao=0).
// Switches read at setup (materials, lights and the GLB are built once): change them by reloading.
//
//   switch      values        what it turns (owner)                                   hero      gameplay
//   aa          traa|taau|msaa temporal AA / TAAU / 4x MSAA + A2C parity path (T16)   traa      taau
//   scale       0.5..1        TAAU render scale (T16; aa.scale)                         1         0.8
//   dof         0|1|only      thin-lens DoF on the beauty frames (T16)                  1         0
//   hairshadow  0|1           deep hair shadow on hair twins (T10, hairshadow.ts)       1         0
//   hairocc     0..1          baked 6-dir hair occlusion (T20, hair.dirOcclusion)       0         1
//   fillshadow  0|1           fill / wrap cast shadows (T10)                            1         0
//   shadows     all|key,...   lights that cast at all (T19 stage.noShadow = the rest)   all       key
//   shadowmap   px            shadow map size of every light (T19 light.mapSize)        2048      1024
//   sharemaps   0|1           twins sample the parent's map (T19 light.shareMaps)       1         1
//   pcss        0|1           PCSS (1) or 5-tap PCF (0) (T19 light.pcss)                1         0
//   contact     0|1           key contact shadows (T19 contact.ts, light.contact)       1         0
//   specocc     0|1           GTAO specular occlusion (T19 light.specOcclusion)         1         1
//   ltc         0|1           hybrid LTC rect lights (T19 light.ltc)                    1         1
//   eyeall      0|1           eye light on every material (T19 light.eyeAll)            1         1
//   gtao        0|1           screen-space AO (T10, ao.ts; 0 = baked direct-AO stand-in) 1        1
//   aores       0.25|0.5      GTAO + prepass resolution (ao.ts SceneAO.resolution)      0.5       0.25
//   ssss        0|1           separable screen-space SSS (T17: pass 'ssss' / skin.ssss) 1         0
//   detail      0|1           skin detail normals (T17: skin.detailNormal)              1         1
//   lod         0|1           1 = load character.lod1[.ktx2].glb (web/tools/lod1.mjs)   0         1
//
// SSSS and the detail normals are T17's (not merged when this was written): until a pass named 'ssss' or
// the params skin.ssss / skin.detailNormal exist the switches are no-ops and stats().tier says so.
// Cut order if the Air cannot hold the hero tier (checkpoint 3 §5.3): dof=0, ssss=0, hairshadow on the
// rim twin only (not a switch yet), aores=0.25, shadowmap=1024, pcss=0&contact=0, aa=taau&scale=0.8.
import type { ParamStore } from './materials/params';
import type { EngineStage, StageCamera } from './stage';

export type TierName = 'hero' | 'gameplay';
export type AASwitch = 'traa' | 'taau' | 'msaa';

export interface TierFlags {
  aa: AASwitch;
  scale: number;
  dof: '0' | '1' | 'only';
  hairshadow: number;
  hairocc: number;
  fillshadow: number;
  shadows: string;
  shadowmap: number;
  sharemaps: number;
  pcss: number;
  contact: number;
  specocc: number;
  ltc: number;
  eyeall: number;
  gtao: number;
  aores: number;
  ssss: number;
  detail: number;
  lod: number;
}

export const TIERS: Record<TierName, TierFlags> = {
  hero: { aa: 'traa', scale: 1, dof: '1', hairshadow: 1, hairocc: 0, fillshadow: 1, shadows: 'all', shadowmap: 2048, sharemaps: 1, pcss: 1, contact: 1, specocc: 1, ltc: 1, eyeall: 1, gtao: 1, aores: 0.5, ssss: 1, detail: 1, lod: 0 },
  gameplay: { aa: 'taau', scale: 0.8, dof: '0', hairshadow: 0, hairocc: 1, fillshadow: 0, shadows: 'key', shadowmap: 1024, sharemaps: 1, pcss: 0, contact: 0, specocc: 1, ltc: 1, eyeall: 1, gtao: 1, aores: 0.25, ssss: 0, detail: 1, lod: 1 },
};

export interface ResolvedTier {
  tier: TierName;
  flags: TierFlags;
  /** the switches the URL set over the tier */
  url: string[];
}

/** The tier from ?tier= (default hero) with every switch the URL gives on top. */
export function resolveTier(q: URLSearchParams): ResolvedTier {
  const tier: TierName = q.get('tier') === 'gameplay' ? 'gameplay' : 'hero';
  const flags: TierFlags = { ...TIERS[tier] };
  const url: string[] = [];
  const f = flags as unknown as Record<string, number | string>;
  for (const k of Object.keys(flags)) {
    const v = q.get(k);
    if (v === null || v === '') continue;
    if (k === 'aa') {
      if (v === 'traa' || v === 'taau' || v === 'msaa') flags.aa = v;
      else continue;
    } else if (k === 'dof') {
      if (v === '0' || v === '1' || v === 'only') flags.dof = v;
      else continue;
    } else if (k === 'shadows') {
      if (!/^[a-z_,]+$/.test(v)) continue;
      flags.shadows = v;
    } else {
      const n = Number(v);
      if (!Number.isFinite(n)) continue;
      f[k] = n;
    }
    url.push(k);
  }
  flags.scale = Math.min(1, Math.max(0.5, flags.scale));
  flags.aores = Math.min(1, Math.max(0.125, flags.aores));
  return { tier, flags, url };
}

function hasParam(P: ParamStore, path: string): boolean {
  try {
    P.get(path);
    return true;
  } catch {
    return false;
  }
}

/** The setup-time params the switches drive (before the materials, lights and AO are built). Returns the
 * switches that are no-ops in this build (their feature has not landed). */
export function applyTierParams(P: ParamStore, f: TierFlags): string[] {
  const noop: string[] = [];
  const set = (path: string, v: number, sw: string) => {
    if (hasParam(P, path)) P.set(path, v);
    else noop.push(sw);
  };
  set('light.ltc', f.ltc, 'ltc');
  set('light.pcss', f.pcss, 'pcss');
  set('light.contact', f.contact, 'contact');
  set('light.specOcclusion', f.specocc, 'specocc');
  set('light.shareMaps', f.sharemaps, 'sharemaps');
  set('light.eyeAll', f.eyeall, 'eyeall');
  set('light.mapSize', f.shadowmap, 'shadowmap');
  set('hair.deepShadow', f.hairshadow ? 1 : 0, 'hairshadow');
  set('hair.dirOcclusion', f.hairocc, 'hairocc');
  set('ao.gtao', f.gtao ? 1 : 0, 'gtao');
  set('dof.on', f.dof === '0' ? 0 : 1, 'dof');
  set('aa.scale', f.scale, 'scale');
  // T17 (not merged at T24): no-ops until the params exist
  if (hasParam(P, 'skin.ssss')) P.set('skin.ssss', f.ssss);
  if (hasParam(P, 'skin.detailNormal')) P.set('skin.detailNormal', f.detail);
  return noop;
}

/** Lights (parent names) that cast no shadow under `shadows` (all = none), from every light the stage
 * data names: the look-dev studio, the hero rig specs and the exported hero shots. */
export function noShadowList(shadows: string, data: EngineStage | null): string[] {
  if (shadows === 'all' || !data) return [];
  const cast = new Set(shadows.split(',').filter(Boolean));
  const base = (n: string) => n.replace(/_(hair|cloth|skin|props|beard)$/, '');
  const names = new Set<string>();
  for (const l of data.lookdev.lights) names.add(base(l.name));
  for (const k of Object.keys(data.hero.light_specs ?? {})) names.add(base(k));
  for (const s of Object.values(data.hero.shots ?? {})) for (const l of s.lights ?? []) names.add(base(l.name));
  return [...names].filter((n) => !cast.has(n));
}

/** The gameplay framing (checkpoint 3 §1.1): a third-person camera `dist` m from the chest at the
 * three-quarter azimuth, a little above eye height, 46 deg vertical FOV (head ~90 px of 956 at 3 m, 60-120
 * px over 2.5-4 m). No f-stop: no DoF. */
export function gameplayCamera(data: EngineStage, dist = 3, azimuthDeg = 35): StageCamera {
  const head = data.landmarks.head_mid;
  const target = [0, head[1]! - 0.38, 0];
  const camY = head[1]! + 0.05;
  const dy = camY - target[1]!;
  const horiz = Math.sqrt(Math.max(0.01, dist * dist - dy * dy));
  const a = (azimuthDeg * Math.PI) / 180;
  const vfov = 46;
  return {
    position: [Math.sin(a) * horiz, camY, Math.cos(a) * horiz],
    target,
    up: [0, 1, 0],
    lens_mm: 12 / Math.tan(((vfov / 2) * Math.PI) / 180),
    sensor_fit: 'VERTICAL',
    sensor_mm: 24,
    vfov_deg: vfov,
    res: [1470, 956],
    shift: [0, 0],
    fstop: null,
    azimuth_deg: azimuthDeg,
  };
}
