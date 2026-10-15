// Cameras and lights: the neutral look-dev studio (blender/lookdev_render.py build_studio +
// make_cameras) and the hero neon rig (blender/hero/rig.py + shots.py), both read from the
// engine_stage.json that blender/hero/export_rig.py writes next to the GLB, so the engine matches the
// Blender stages by data.
//
// Units. Blender area light of power P (W) at distance d gives on-axis irradiance E = P / (pi d^2)
// (rig._light_power); a Lambert surface then renders albedo * E / pi (scene-linear). three.js:
// a SpotLight of intensity I gives E = I / d^2 (decay 2) and the same albedo * E / pi, so
// I = P / pi, with no other scale. The area emitter's cosine falloff is approximated by an 80 deg
// cone with full penumbra; its size by the shadow blur radius (no area-light specular shape).
// A uniform world of radiance Lw (Blender background colour x strength) is a hemisphere light with
// sky = ground = Lw / |Lw| and intensity pi |Lw| (irradiance pi Lw on any normal).
//
// Area lights (T6, ?area=none|rims|all, default none): LTC rect lights (three's RectAreaLight, Heitz et
// al. 2016) of the Blender size. A Blender area light of power P and size w x h is a Lambertian emitter
// of radiance L = P / (pi w h), which is three's RectAreaLight intensity (power = I w h pi). Rect lights
// cast no shadow in three, so the key / wrap / fill stay shadowed spots unless area=all; the rims and
// kickers (0.3 x 1.2-1.5 m strips at 1.5 m) are where the spot's narrow, hard lobe was most wrong.
// Measured: unshadowed rims leak under the jaw, so 'none' (shadowed spots) is the default; rims/all opt-in.
//
// T19 (lighting.ts): HYBRID LTC is the default (light.ltc 1, i.e. area 'all'): every light an LTC rect of its
// Blender size, shadowed by an invisible spot proxy's depth map aimed at the view's frame (fitShadow), PCSS
// filtered; a light's twins sample their parent's map (one map per light: hero 10 -> 5); the key's shadow
// also takes the screen-space contact shadows (contact.ts). The eye light reaches every material at full
// diffuse (light.eyeAll), as Cycles renders it: Cycles ignores the light's diffuse_factor 0.3 (the per-light
// grey chart measures 1.06 x the full-diffuse prediction), and T5-T16 linked it to the eyes only, which
// left the chart 2-11/255 low in G / B and the face without its frontal fill (t16-aa-post.md §3).
import * as THREE from 'three/webgpu';
import { lights as lightsNodeOf } from 'three/tsl';
import { RectAreaLightTexturesLib } from 'three/addons/lights/RectAreaLightTexturesLib.js';
import { groupOf, roleOf } from './materials';
import type { ParamStore } from './materials/params';
import { deepHairFilter, setupHairShadow } from './hairshadow';
import { LinkedShadowNode, OwnedShadowNode, discDiameter, fitShadow, linkedShadow, pcssFilter } from './lighting';

export interface StageCamera {
  position: number[];
  target: number[];
  up?: number[];
  lens_mm: number;
  sensor_fit: string;
  sensor_mm: number;
  vfov_deg: number;
  res: number[];
  shift: number[];
  fstop?: number | null;
  focus_m?: number;
  azimuth_deg?: number;
  frame_h_m?: number;
}
export interface StageLight {
  name: string;
  position: number[];
  target: number[];
  color: number[];
  power_w: number;
  size: number[];
  use_shadow?: boolean;
  diffuse_factor?: number;
  /** Blender light world rotation in glTF space (x, y, z, w); the light shines along its local -Z. */
  quaternion?: number[];
  receivers?: { mode: 'all' | 'include' | 'exclude'; groups: string[] };
  /** T10: a hair-only twin made by the viewer (hairshadow.ts), not exported */
  viewer_twin?: boolean;
}
interface LightSpec {
  color: number[];
  ratio: number;
  size: number[];
  az: number;
  el: number;
  dist: number | null;
}
export interface EngineStage {
  version: number;
  landmarks: { floor_y: number; head_mid: number[]; eyes_rest: { l: number[]; r: number[] } };
  lookdev: {
    exposure: number;
    world: { color: number[]; strength: number };
    floor: { y: number; albedo: number[]; roughness: number; size: number };
    lights: StageLight[];
    cameras: Record<string, StageCamera>;
  };
  hero: {
    e_key: number;
    exposure: number;
    grade: { slope: number[]; offset: number[]; power: number[]; saturation: number; black_lift: number; vignette_ev: number; wb_kelvin: number; wb_rgb: number[] };
    world: { color: number[] };
    light_specs: Record<string, LightSpec>;
    shots: Record<
      string,
      {
        pose: string;
        camera: StageCamera;
        subject: number[];
        exposure: number;
        lights: StageLight[];
        bones: Record<string, number[]>;
        corrective_weights: Record<string, number>;
        helper_world_quats?: Record<string, number[]>;
        gaze?: Gaze | null;
      }
    >;
  };
}

/** Eye turn of a hero shot (blender/hero/wet.gaze_rotations): rest-world centre + rotation per eye. */
export interface Gaze {
  deg: number[];
  l: { centre: number[]; quat: number[] };
  r: { centre: number[]; quat: number[] };
}

export const VIEWS = ['front', 'three_quarter', 'profile', 'closeup', 'portrait'] as const;
export type ViewName = (typeof VIEWS)[number];
export type RigName = 'neutral' | 'hero';

const v3 = (a: number[] | undefined) => new THREE.Vector3(a?.[0] ?? 0, a?.[1] ?? 0, a?.[2] ?? 0);

/** Fallback stage when the build has no engine_stage.json (approximate, from the bounds). */
export function fallbackStage(model: THREE.Object3D): EngineStage {
  const box = new THREE.Box3().setFromObject(model);
  const floor = box.min.y;
  const top = box.max.y;
  const head = [0, top - 0.12, 0.04];
  const cam = (az: number, target: number[], lens: number, frame: number): StageCamera => {
    const a = (az * Math.PI) / 180;
    const dist = (frame * 0.5 * lens) / 18;
    return {
      position: [target[0]! + Math.sin(a) * dist, target[1]!, target[2]! + Math.cos(a) * dist],
      target,
      lens_mm: lens,
      sensor_fit: 'AUTO',
      sensor_mm: 36,
      vfov_deg: (2 * Math.atan(18 / lens) * 180) / Math.PI,
      res: [512, 512],
      shift: [0, 0],
    };
  };
  const body = [0, floor + 0.98, 0];
  const area = (name: string, p: number[], power: number, size: number, color: number[]): StageLight => ({
    name,
    position: [p[0]!, p[2]! + floor, -p[1]!],
    target: [0, floor + 1.1, 0],
    color,
    power_w: power,
    size: [size, size],
  });
  return {
    version: 0,
    landmarks: { floor_y: floor, head_mid: head, eyes_rest: { l: [0.03, top - 0.13, 0.13], r: [-0.03, top - 0.13, 0.13] } },
    lookdev: {
      exposure: -2.5,
      world: { color: [0.045, 0.045, 0.05], strength: 1 },
      floor: { y: floor, albedo: [0.08, 0.08, 0.085], roughness: 0.8, size: 60 },
      lights: [
        area('key', [-2.2, -2.6, 2.8], 900, 1.5, [1, 0.96, 0.9]),
        area('fill', [2.6, -2.0, 1.4], 250, 2.0, [0.85, 0.9, 1]),
        area('rim', [0.8, 2.8, 2.6], 700, 1.0, [1, 1, 1]),
      ],
      cameras: {
        front: cam(0, body, 50, 2.15),
        three_quarter: cam(40, body, 50, 2.15),
        profile: cam(90, body, 50, 2.15),
        closeup: cam(25, [head[0]!, head[1]! - 0.03, head[2]!], 85, 0.42),
      },
    },
    hero: {
      e_key: 3,
      exposure: -0.6,
      grade: { slope: [1.04, 1, 0.94], offset: [-0.0008, 0.0004, 0.0016], power: [1.08, 1.08, 1.08], saturation: 0.97, black_lift: 0.0011, vignette_ev: -0.3, wb_kelvin: 3900, wb_rgb: [1.432, 0.921, 0.508] },
      world: { color: [0.003, 0.003, 0.004] },
      light_specs: {
        key: { color: [1.755, 0.849, 0.271], ratio: 1, size: [0.3, 0.3], az: 55, el: 30, dist: 1.5 },
        wrap: { color: [1.755, 0.849, 0.271], ratio: 0.25, size: [1.5, 1.5], az: 35, el: 10, dist: 2 },
        // T25 (rig.py HERO_LIGHTS / shots.RIMS): rims at or below the key; the fill is the set's bounce (4,800 K)
        rim: { color: [1, 0.06, 0.42], ratio: 1, size: [0.3, 1.5], az: -125, el: 20, dist: 1.5 },
        kicker: { color: [0.02, 0.85, 0.8], ratio: 0.7, size: [0.3, 1.2], az: 135, el: 15, dist: 1.6 },
        fill: { color: [1.241, 0.957, 0.719], ratio: 0.15, size: [3, 2.5], az: -60, el: -20, dist: 2.5 },
      },
      shots: {},
    },
  };
}

/** rig._around: a point `dist` from subject, az deg from the subject->camera axis (+ = camera-left), el up. */
export function around(subject: THREE.Vector3, cam: THREE.Vector3, az: number, el: number, dist: number): THREE.Vector3 {
  // Blender's Z-up math in glTF axes: Blender (x, y) ground plane = glTF (x, -z).
  const c = new THREE.Vector2(cam.x - subject.x, -(cam.z - subject.z)).normalize();
  const a = (-az * Math.PI) / 180;
  const e = (el * Math.PI) / 180;
  const dx = c.x * Math.cos(a) - c.y * Math.sin(a);
  const dy = c.x * Math.sin(a) + c.y * Math.cos(a);
  return new THREE.Vector3(subject.x + dx * Math.cos(e) * dist, subject.y + Math.sin(e) * dist, subject.z - dy * Math.cos(e) * dist);
}

export interface ViewSetup {
  name: ViewName;
  rig: RigName;
  camera: StageCamera;
  exposure: number;
  grade: boolean;
  /** Hero shot whose pose this view uses (portrait), or null for the bind pose. */
  shot: string | null;
}

export class Stage {
  readonly group = new THREE.Group();
  private readonly floor: THREE.Mesh;
  private readonly hemi = new THREE.HemisphereLight(0xffffff, 0xffffff, 0);
  private lights: { light: THREE.SpotLight | THREE.RectAreaLight; spec: StageLight }[] = [];
  /** T19: the spot proxies that own a shadow map, by light name (the parents; twins link to them) */
  private rigs = new Map<string, { proxy: THREE.SpotLight; size: number }>();
  /** T19: the screen-space contact term (contact.ts ContactShadows.node), multiplied into the key's shadow */
  contactNode: unknown = null;
  view: ViewSetup | null = null;
  shadowMapSize = 2048;
  /** Which lights become LTC rect lights: none (default: shadowed spots), the rims and kickers, or all. */
  areaMode: 'none' | 'rims' | 'all' = 'none';
  /** Debug (?lights=key,rim): build only the lights with these names (and their _hair twins); null = all. */
  only: string[] | null = null;
  /** T10: hair-only twins with the deep hair shadow (hairshadow.ts) for every shadowed light that reaches
   * the hair (needs P; ?hairshadow=0 or hair.deepShadow 0 = the T9b binary shadow on the hair). */
  deepHair = true;
  /** T10: the fill (and the hero wrap) cast shadows too; false (?fillshadow=0) = T5-T9b: key, rims, kickers. */
  shadowFill = true;
  /** T19 A/B (?noshadow=rim,kicker): lights (by parent name) that cast no shadow. */
  noShadow: string[] = [];
  private static ltcReady = false;

  constructor(
    readonly data: EngineStage,
    private readonly scene: THREE.Scene,
    private readonly materials: Map<string, THREE.MeshPhysicalNodeMaterial>,
    private readonly P: ParamStore | null = null,
  ) {
    const f = data.lookdev.floor;
    this.floor = new THREE.Mesh(
      new THREE.PlaneGeometry(f.size, f.size),
      new THREE.MeshStandardNodeMaterial({ color: new THREE.Color().setRGB(f.albedo[0]!, f.albedo[1]!, f.albedo[2]!), roughness: f.roughness }),
    );
    this.floor.rotation.x = -Math.PI / 2;
    this.floor.position.y = f.y;
    this.floor.receiveShadow = true;
    this.group.add(this.floor, this.hemi);
    scene.add(this.group);
  }

  hasShot(name: string): boolean {
    return name in this.data.hero.shots;
  }

  /** Camera + rig for a view name (portrait uses the hero shot's camera and pose). */
  setup(name: ViewName, rig: RigName): ViewSetup {
    const shot = name === 'portrait' && this.hasShot('portrait') ? this.data.hero.shots.portrait! : null;
    let camera: StageCamera;
    if (name === 'portrait') {
      camera = shot?.camera ?? portraitFallback(this.data);
    } else {
      camera = this.data.lookdev.cameras[name] ?? Object.values(this.data.lookdev.cameras)[0]!;
    }
    const hero = rig === 'hero';
    const exposure = hero ? (shot?.exposure ?? this.data.hero.exposure) : this.data.lookdev.exposure;
    this.view = { name, rig, camera, exposure, grade: hero, shot: shot ? 'portrait' : null };
    this.buildLights();
    return this.view;
  }

  private clearLights(): void {
    for (const { light } of this.lights) {
      if ((light as THREE.SpotLight).isSpotLight) {
        const sp = light as THREE.SpotLight;
        sp.shadow.map?.dispose();
        this.group.remove(sp.target);
      }
      light.dispose();
      this.group.remove(light);
    }
    this.lights = [];
    for (const { proxy } of this.rigs.values()) {
      proxy.shadow.map?.dispose();
      proxy.dispose();
      this.group.remove(proxy, proxy.target);
    }
    this.rigs.clear();
  }

  /** The light whose shadow camera this is (profile.ts labels), or null. */
  shadowCameraName(cam: THREE.Camera): string | null {
    for (const [name, { proxy }] of this.rigs) if (proxy.shadow.camera === cam) return name;
    return null;
  }

  /** The key light (the parent, not its hair twin), for the contact shadows; null when not built. */
  keyLight(): THREE.Light | null {
    return this.lights.find(({ spec }) => spec.name === 'key')?.light ?? null;
  }

  /** The sphere (centre, radius) holding the view's frame at the camera's target distance: the shadow
   * frustums are fitted to it (lighting.ts fitShadow). */
  private frameSphere(): { c: THREE.Vector3; R: number } {
    const cam = this.view!.camera;
    const pos = v3(cam.position);
    const tgt = v3(cam.target);
    const dist = pos.distanceTo(tgt);
    const aspect = (cam.res[0] ?? 1) / (cam.res[1] ?? 1);
    const span = 2 * dist * Math.tan((cam.vfov_deg * Math.PI) / 360);
    const [fw, fh] = cam.sensor_fit === 'VERTICAL' ? [span * aspect, span] : aspect >= 1 ? [span, span / aspect] : [span * aspect, span];
    const unit = cam.sensor_fit === 'VERTICAL' ? fh : Math.max(fw, fh);
    const fwd = tgt.clone().sub(pos).normalize();
    const right = fwd.clone().cross(new THREE.Vector3(0, 1, 0)).normalize();
    const up = right.clone().cross(fwd).normalize();
    const c = tgt.clone().addScaledVector(right, (cam.shift[0] ?? 0) * unit).addScaledVector(up, (cam.shift[1] ?? 0) * unit);
    const margin = this.P ? (this.P.get('light.fitMargin') as number) : 1.15;
    return { c, R: 0.5 * Math.hypot(fw, fh) * margin };
  }

  private param(path: string, fallback: number): number {
    return this.P ? (this.P.get(path) as number) : fallback;
  }

  /** T19: the light's shadow: its own map from a spot proxy (parents, or any light when maps are not
   * shared), or a link to its parent's map (twins). Sets light.shadow / castShadow. */
  private attachShadow(l: THREE.SpotLight | THREE.RectAreaLight, s: StageLight, sphere: { c: THREE.Vector3; R: number }): string {
    const base = s.name.replace(/_(hair|cloth|skin|props|beard)$/, '');
    const hairTwin = /_hair$/.test(s.name) && this.deepHair && !!this.P;
    const size = Math.max(s.size[0] ?? 0.3, 1e-3);
    const disc = discDiameter(size, Math.max(s.size[1] ?? size, 1e-3));
    const pcss = !!this.P && this.param('light.pcss', 0) > 0;
    const parent = base !== s.name && this.param('light.shareMaps', 1) > 0 ? this.rigs.get(base) : undefined;
    const L = l as unknown as { shadow: THREE.LightShadow; castShadow: boolean };
    if (parent) {
      const ts = linkedShadow(parent.proxy.shadow);
      const tn = ts as unknown as { filterNode: unknown; shadowNode: unknown; radius: number };
      if (hairTwin) tn.filterNode = deepHairFilter(this.P!);
      else if (pcss) tn.filterNode = pcssFilter(this.P!, disc);
      else ts.radius = Math.min(12, 1 + (Math.max(size, s.size[1] ?? size) / Math.max(v3(s.position).distanceTo(v3(s.target)), 1e-3)) * 6);
      // the grazing normal offset on the surface twins only (a card normal says nothing about the strands)
      tn.shadowNode = new LinkedShadowNode(parent.proxy, ts, parent.proxy.shadow, hairTwin ? null : (this.P ?? null));
      L.shadow = ts;
      L.castShadow = true;
      return hairTwin ? `deep (${base} map)` : `${pcss ? 'pcss' : 'pcf'} (${base} map)`;
    }
    const proxy = new THREE.SpotLight(0xffffff, 0);
    proxy.name = `${s.name}_shadow`;
    proxy.visible = false;
    proxy.castShadow = false; // three's own ShadowNode is not made; OwnedShadowNode renders the map
    proxy.position.copy(v3(s.position));
    this.group.add(proxy, proxy.target);
    const sh = proxy.shadow;
    const ms = hairTwin && this.param('light.shareMaps', 1) <= 0 ? this.param('hair.shadowMapSize', 2048) : this.param('light.mapSize', this.shadowMapSize);
    sh.mapSize.set(ms, ms);
    fitShadow(proxy, sphere.c, sphere.R);
    const sn = sh as unknown as { filterNode: unknown; shadowNode: unknown };
    let label: string;
    if (hairTwin) {
      // a twin with its own map (light.shareMaps 0): T10's head-focused frustum
      proxy.target.position.copy(v3(s.target));
      proxy.angle = Math.min((80 * Math.PI) / 180, Math.atan(1.4 / Math.max(proxy.position.distanceTo(proxy.target.position), 1e-3)) + 0.2);
      proxy.updateMatrixWorld();
      proxy.target.updateMatrixWorld();
      setupHairShadow(proxy, this.P!, v3(this.data.landmarks.head_mid));
      label = `deep ${ms}`;
    } else {
      sh.bias = pcss ? 0 : -0.0004;
      sh.normalBias = this.param('light.normalBias', 0.004);
      if (pcss) sn.filterNode = pcssFilter(this.P!, disc);
      else sh.radius = Math.min(12, 1 + (Math.max(size, s.size[1] ?? size) / Math.max(v3(s.position).distanceTo(v3(s.target)), 1e-3)) * 6);
      label = `${pcss ? 'pcss' : 'pcf'} ${ms}`;
    }
    const own = new OwnedShadowNode(proxy, this.P ?? null);
    const contact = s.name === 'key' && this.contactNode ? this.contactNode : null;
    sn.shadowNode = contact ? (own as unknown as { mul(x: unknown): unknown }).mul(contact) : own;
    if (contact) label += ' + contact';
    this.rigs.set(s.name, { proxy, size: disc });
    L.shadow = sh;
    L.castShadow = true;
    return label;
  }

  private isArea(s: StageLight): boolean {
    if (this.areaMode === 'none') return false;
    // T19: everything in 'all', the eye light and the hair twins too (the hair models' directRectArea
    // shades the cards from the rect's form-factor point equivalent, never as GGX)
    if (this.areaMode === 'all') return true;
    if (s.name === 'eye' || /_hair$/.test(s.name)) return false;
    return /^(rim|kicker)/.test(s.name);
  }

  /** LTC rect light for a Blender area light (see the header for the units). */
  private rectLight(s: StageLight): THREE.RectAreaLight {
    if (!Stage.ltcReady) {
      THREE.RectAreaLightNode.setLTC(RectAreaLightTexturesLib.init());
      Stage.ltcReady = true;
    }
    const w = Math.max(s.size[0] ?? 0.3, 1e-3);
    const h = Math.max(s.size[1] ?? s.size[0] ?? 0.3, 1e-3);
    const l = new THREE.RectAreaLight(new THREE.Color().setRGB(s.color[0]!, s.color[1]!, s.color[2]!), s.power_w / (Math.PI * w * h), w, h);
    l.name = s.name;
    l.position.copy(v3(s.position));
    l.userData.aoWeight = Math.min(1, Math.max(w, h) / Math.max(v3(s.position).distanceTo(v3(s.target)), 1e-3));
    if (s.quaternion && this.view?.name === 'portrait') {
      // Blender local axes = three local axes (both shine along -Z); world: glTF rotation * C, where
      // C maps a Blender-space vector into glTF space ((x, y, z) -> (x, z, -y))
      const C = new THREE.Matrix4().set(1, 0, 0, 0, 0, 0, 1, 0, 0, -1, 0, 0, 0, 0, 0, 1);
      const qc = new THREE.Quaternion().setFromRotationMatrix(C);
      l.quaternion.fromArray(s.quaternion).multiply(qc);
    } else {
      l.lookAt(v3(s.target));
    }
    return l;
  }

  private heroLights(cam: StageCamera, eyesMid: THREE.Vector3): StageLight[] {
    const shot = this.data.hero.shots.portrait;
    const camPos = v3(cam.position);
    const subject = this.view?.name === 'closeup' || this.view?.name === 'portrait' ? eyesMid : v3(cam.target);
    if (shot && this.view?.name === 'portrait') return shot.lights;
    // re-place the camera-relative rig (rig.hero_rig) for this camera; colours / powers / linking
    // from the portrait shot when present, else from the base specs
    const base: StageLight[] = shot
      ? shot.lights
      : Object.entries(this.data.hero.light_specs).map(([n, s]) => ({
          name: n,
          position: [0, 0, 0],
          target: [0, 0, 0],
          color: s.color,
          power_w: s.ratio * this.data.hero.e_key * Math.PI * (s.dist ?? 1.5) ** 2,
          size: s.size,
          use_shadow: n !== 'eye',
        }));
    const out: StageLight[] = [];
    for (const l of base) {
      const spec = this.data.hero.light_specs[l.name.replace(/_(hair|cloth|skin|props)$/, '')];
      if (!spec) continue;
      let pos: THREE.Vector3;
      let aim = subject;
      if (spec.dist === null) {
        pos = camPos.clone().add(new THREE.Vector3(0, 0.08, 0));
        aim = eyesMid;
      } else pos = around(subject, camPos, spec.az, spec.el, spec.dist);
      out.push({ ...l, position: pos.toArray(), target: aim.toArray() });
    }
    return out;
  }

  private eyesMid(): THREE.Vector3 {
    const e = this.data.landmarks.eyes_rest;
    return v3(e.l).add(v3(e.r)).multiplyScalar(0.5);
  }

  private shadowRe(): RegExp {
    return this.shadowFill ? /^(key|rim|kicker|fill|wrap)/ : /^(key|rim|kicker)/;
  }

  private castsShadow(s: StageLight): boolean {
    const base = s.name.replace(/_(hair|cloth|skin|props|beard)$/, '');
    return (s.use_shadow ?? true) && s.name !== 'eye' && !this.noShadow.includes(base) && this.shadowRe().test(s.name);
  }

  /** Does a light with these receivers reach the hair group? */
  private static reachesHair(r: StageLight['receivers']): boolean {
    if (!r || r.mode === 'all') return true;
    const hit = r.groups.includes('hair');
    return r.mode === 'include' ? hit : !hit;
  }

  /** T10: give every shadowed light that reaches the hair a hair-only twin (the exported rim_hair /
   * kicker_hair / fill_hair are kept as they are) and take the hair off the parent, so the hair is lit
   * only by twins, whose shadow is the deep hair shadow. */
  private withHairTwins(specs: StageLight[]): StageLight[] {
    if (!this.deepHair || !this.P) return specs;
    const names = new Set(specs.map((s) => s.name));
    const out: StageLight[] = [];
    for (const s of specs) {
      if (/_hair$/.test(s.name) || !this.castsShadow(s) || !Stage.reachesHair(s.receivers) || names.has(`${s.name}_hair`)) {
        out.push(s);
        continue;
      }
      const r = s.receivers;
      const parent: StageLight['receivers'] =
        !r || r.mode === 'all'
          ? { mode: 'exclude', groups: ['hair'] }
          : r.mode === 'exclude'
            ? { mode: 'exclude', groups: [...r.groups, 'hair'] }
            : { mode: 'include', groups: r.groups.filter((g) => g !== 'hair') };
      out.push({ ...s, receivers: parent });
      out.push({ ...s, name: `${s.name}_hair`, receivers: { mode: 'include', groups: ['hair'] }, viewer_twin: true });
    }
    return out;
  }

  private buildLights(): void {
    this.clearLights();
    const view = this.view!;
    const hero = view.rig === 'hero';
    const all = this.withHairTwins(hero ? this.heroLights(view.camera, this.eyesMid()) : this.data.lookdev.lights);
    // parents before their twins (a twin links to its parent's shadow map)
    const isTwin = (n: string) => /_(hair|cloth|skin|props|beard)$/.test(n);
    const specs = [...all.filter((x) => !isTwin(x.name)), ...all.filter((x) => isTwin(x.name))];
    const world = hero ? this.data.hero.world.color : this.data.lookdev.world.color.map((c) => c * this.data.lookdev.world.strength);
    const lw = Math.max(world[0]!, world[1]!, world[2]!, 1e-6);
    this.hemi.color.setRGB(world[0]! / lw, world[1]! / lw, world[2]! / lw);
    this.hemi.groundColor.copy(this.hemi.color);
    this.hemi.intensity = Math.PI * lw;
    this.scene.background = new THREE.Color().setRGB(world[0]!, world[1]!, world[2]!);
    const fl = this.floor.material as THREE.MeshStandardNodeMaterial;
    const fa = hero ? [0.03, 0.03, 0.03] : this.data.lookdev.floor.albedo;
    fl.color.setRGB(fa[0]!, fa[1]!, fa[2]!);
    fl.roughness = hero ? 0.45 : this.data.lookdev.floor.roughness;
    const sphere = this.frameSphere();
    for (const s of specs) {
      if (this.only && !this.only.includes(s.name.replace(/_(hair|cloth|skin|props|beard)$/, ''))) continue;
      const size = Math.max(s.size[0] ?? 0.3, s.size[1] ?? 0.3);
      const d = v3(s.position).distanceTo(v3(s.target));
      let l: THREE.SpotLight | THREE.RectAreaLight;
      if (this.isArea(s)) {
        l = this.rectLight(s);
        this.group.add(l);
      } else {
        const sp = new THREE.SpotLight(new THREE.Color().setRGB(s.color[0]!, s.color[1]!, s.color[2]!), s.power_w / Math.PI, 0, (80 * Math.PI) / 180, 1, 2);
        sp.name = s.name;
        sp.position.copy(v3(s.position));
        sp.target.position.copy(v3(s.target));
        // the spot's own cone (T5-T10): tightened on the subject
        if (this.castsShadow(s)) sp.angle = Math.min((80 * Math.PI) / 180, Math.atan(1.4 / Math.max(d, 1e-3)) + 0.2);
        // AO weight (ao.ts): how much of the screen-space AO this light's direct diffuse takes; a big soft
        // light (fill, wrap, rim strips) is what AO stands in for
        sp.userData.aoWeight = Math.min(1, size / Math.max(d, 1e-3));
        this.group.add(sp, sp.target);
        l = sp;
      }
      // the emitter rect (contact.ts marches toward it): size and world orientation, both paths
      l.userData.rectW = Math.max(s.size[0] ?? 0.3, 1e-3);
      l.userData.rectH = Math.max(s.size[1] ?? s.size[0] ?? 0.3, 1e-3);
      if ((l as THREE.RectAreaLight).isRectAreaLight) l.userData.rectQuat = l.quaternion.clone();
      else {
        const o = new THREE.Object3D();
        o.position.copy(v3(s.position));
        o.lookAt(v3(s.target));
        // Object3D.lookAt points +z at the target; a rect shines along -z
        o.rotateY(Math.PI);
        l.userData.rectQuat = o.quaternion.clone();
      }
      // T18: the Blender emitter's rectangle (the eye material's cornea reflects it, LTC), placed as
      // rectLight() would place a RectAreaLight here
      l.userData.rect = { w: s.size[0] ?? 0.3, h: s.size[1] ?? s.size[0] ?? 0.3, quaternion: s.quaternion && this.view?.name === 'portrait' ? s.quaternion : null };
      // shadows (T19): every shadowed light from its spot proxy's map, the twins from their parent's
      if (this.castsShadow(s)) {
        const label = this.attachShadow(l, s, sphere);
        l.userData.shadowLabel = label;
        if (label.startsWith('deep')) l.userData.deepHair = true;
      }
      this.lights.push({ light: l, spec: s });
    }
    this.link(hero);
  }

  /** Light linking (rig.py twins): per material, the lights whose receivers include its group (the
   * look-dev studio has no exported twins; its lights reach everything unless the viewer made hair twins). */
  private link(hero: boolean): void {
    for (const [name, mat] of this.materials) {
      const g = groupOf(name);
      const eye = roleOf(name) === 'eye';
      const use = this.lights
        .filter(({ spec }) => {
          // the eye light: every material, as Cycles (T19, light.eyeAll); T5-T16: the eyes only (a catchlight)
          if (spec.name === 'eye') return hero && (eye || this.param('light.eyeAll', 0) > 0);
          const r = spec.receivers;
          if (!r || r.mode === 'all') return true;
          const hit = r.groups.includes(g);
          return r.mode === 'include' ? hit : !hit;
        })
        .map((x) => x.light as THREE.Light);
      mat.lightsNode = lightsNodeOf([...use, this.hemi]);
      mat.needsUpdate = true;
    }
  }

  lightCount(): number {
    return this.lights.length;
  }

  describeLights(): { name: string; type: string; intensity: number; shadow: boolean | string }[] {
    return this.lights.map(({ light }) => ({
      name: light.name,
      type: light.type,
      intensity: +light.intensity.toFixed(3),
      shadow: light.castShadow ? ((light.userData.shadowLabel as string | undefined) ?? true) : false,
    }));
  }

  /** Shadow maps rendered per frame (each a pass over the casters): one per spot proxy (T19). */
  shadowMapCount(): number {
    return this.rigs.size;
  }
}

function portraitFallback(data: EngineStage): StageCamera {
  const e = data.landmarks.eyes_rest;
  const t = [((e.l[0] ?? 0) + (e.r[0] ?? 0)) / 2, ((e.l[1] ?? 0) + (e.r[1] ?? 0)) / 2, ((e.l[2] ?? 0) + (e.r[2] ?? 0)) / 2];
  const dist = (85 / 24) * 0.42;
  const a = (30 * Math.PI) / 180;
  const el = (2 * Math.PI) / 180;
  return {
    position: [t[0]! + Math.sin(a) * Math.cos(el) * dist, t[1]! + Math.sin(el) * dist, t[2]! + Math.cos(a) * Math.cos(el) * dist],
    target: t,
    lens_mm: 85,
    sensor_fit: 'VERTICAL',
    sensor_mm: 24,
    vfov_deg: (2 * Math.atan(12 / 85) * 180) / Math.PI,
    res: [1920, 1080],
    shift: [-0.07, -0.16],
  };
}

/** Put a three camera on a stage camera for a w x h frame (vertical FOV, Blender shift). */
export function applyCamera(cam: THREE.PerspectiveCamera, s: StageCamera, w: number, h: number): void {
  cam.position.copy(v3(s.position));
  cam.up.copy(new THREE.Vector3(0, 1, 0));
  cam.lookAt(v3(s.target));
  let vfov = s.vfov_deg;
  if (s.sensor_fit === 'AUTO' && w > h) {
    // AUTO fit: the sensor (vfov_deg) spans the larger dimension, so a landscape frame's vertical FOV is
    // narrower (the 2:1 shader-ball frame; lookdev frames are square, the hero portrait is VERTICAL)
    vfov = (2 * Math.atan((Math.tan((vfov * Math.PI) / 360) * h) / w) * 180) / Math.PI;
  }
  cam.fov = vfov;
  cam.aspect = w / h;
  cam.near = 0.05;
  cam.far = 200;
  const sx = s.shift[0] ?? 0;
  const sy = s.shift[1] ?? 0;
  if (sx || sy) {
    const unit = s.sensor_fit === 'VERTICAL' ? h : Math.max(w, h);
    cam.setViewOffset(w, h, sx * unit, -sy * unit, w, h);
  } else cam.clearViewOffset();
  cam.updateProjectionMatrix();
}
