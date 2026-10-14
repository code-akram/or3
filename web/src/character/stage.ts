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
// Area lights (T6, ?area=none|rims|all, default rims): LTC rect lights (three's RectAreaLight, Heitz et
// al. 2016) of the Blender size. A Blender area light of power P and size w x h is a Lambertian emitter
// of radiance L = P / (pi w h), which is three's RectAreaLight intensity (power = I w h pi). Rect lights
// cast no shadow in three, so the key / wrap / fill stay shadowed spots unless area=all; the rims and
// kickers (0.3 x 1.2-1.5 m strips at 1.5 m) are where the spot's narrow, hard lobe was most wrong.
import * as THREE from 'three/webgpu';
import { lights as lightsNodeOf } from 'three/tsl';
import { RectAreaLightTexturesLib } from 'three/addons/lights/RectAreaLightTexturesLib.js';
import { groupOf, roleOf } from './materials';

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
        rim: { color: [1, 0.06, 0.42], ratio: 2.2, size: [0.3, 1.5], az: -125, el: 20, dist: 1.5 },
        kicker: { color: [0.02, 0.85, 0.8], ratio: 1.2, size: [0.3, 1.2], az: 135, el: 15, dist: 1.6 },
        fill: { color: [0.55, 0.7, 1], ratio: 0.08, size: [2, 2], az: -55, el: -5, dist: 2.5 },
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
  view: ViewSetup | null = null;
  shadowMapSize = 2048;
  /** Which lights become LTC rect lights: none, the rims and kickers (default), or all. */
  areaMode: 'none' | 'rims' | 'all' = 'rims';
  private static ltcReady = false;

  constructor(
    readonly data: EngineStage,
    private readonly scene: THREE.Scene,
    private readonly materials: Map<string, THREE.MeshPhysicalNodeMaterial>,
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
  }

  private isArea(s: StageLight): boolean {
    if (this.areaMode === 'none' || s.name === 'eye') return false;
    // the hair twins keep the Kajiya-Kay path (custom direct(); LTC would shade the cards as GGX)
    if (/_hair$/.test(s.name)) return false;
    if (this.areaMode === 'all') return true;
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

  private buildLights(): void {
    this.clearLights();
    const view = this.view!;
    const hero = view.rig === 'hero';
    const specs = hero ? this.heroLights(view.camera, this.eyesMid()) : this.data.lookdev.lights;
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
    for (const s of specs) {
      if (this.isArea(s)) {
        const r = this.rectLight(s);
        this.group.add(r);
        this.lights.push({ light: r, spec: s });
        continue;
      }
      const l = new THREE.SpotLight(new THREE.Color().setRGB(s.color[0]!, s.color[1]!, s.color[2]!), s.power_w / Math.PI, 0, (80 * Math.PI) / 180, 1, 2);
      l.name = s.name;
      l.position.copy(v3(s.position));
      l.target.position.copy(v3(s.target));
      const d = l.position.distanceTo(l.target.position);
      // shadows: the key always; the rims too (they only hit edges, which is exactly where a
      // shadowless rim leaks through the head)
      const shadowed = (s.use_shadow ?? true) && /^(key|rim|kicker)/.test(s.name);
      if (shadowed) {
        l.castShadow = true;
        l.shadow.mapSize.set(this.shadowMapSize, this.shadowMapSize);
        l.shadow.camera.near = Math.max(0.05, d - 2.5);
        l.shadow.camera.far = d + 3;
        l.shadow.bias = -0.0004;
        l.shadow.normalBias = 0.004;
        // penumbra from the emitter size (Blender area size): radius in shadow-map texels
        const size = Math.max(s.size[0] ?? 0.3, s.size[1] ?? 0.3);
        l.shadow.radius = Math.min(12, 1 + (size / d) * 6);
        // tighten the frustum on the subject
        l.angle = Math.min((80 * Math.PI) / 180, Math.atan(1.4 / d) + 0.2);
      }
      this.group.add(l, l.target);
      this.lights.push({ light: l, spec: s });
    }
    this.link(hero);
  }

  /** Light linking (rig.py twins): per material, the lights whose receivers include its group. */
  private link(hero: boolean): void {
    const all = this.lights.map((x) => x.light as THREE.Light);
    for (const [name, mat] of this.materials) {
      if (!hero) {
        mat.lightsNode = lightsNodeOf([...all.filter((l) => l.name !== 'eye'), this.hemi]);
      } else {
        const g = groupOf(name);
        const eye = roleOf(name) === 'eye';
        const use = this.lights
          .filter(({ spec }) => {
            if (spec.name === 'eye') return eye; // the eye light is a catchlight (diffuse 0.3 in Blender)
            const r = spec.receivers;
            if (!r || r.mode === 'all') return true;
            const hit = r.groups.includes(g);
            return r.mode === 'include' ? hit : !hit;
          })
          .map((x) => x.light as THREE.Light);
        mat.lightsNode = lightsNodeOf([...use, this.hemi]);
      }
      mat.needsUpdate = true;
    }
  }

  lightCount(): number {
    return this.lights.length;
  }

  describeLights(): { name: string; type: string; intensity: number; shadow: boolean }[] {
    return this.lights.map(({ light }) => ({ name: light.name, type: light.type, intensity: +light.intensity.toFixed(3), shadow: light.castShadow }));
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
  if (s.sensor_fit === 'AUTO' && w < h) {
    // AUTO fit: the sensor spans the larger dimension
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
