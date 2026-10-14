// TypeScript port of blender/character/deform_runtime.py (the reference implementation): helper
// joints (twist / swing / follow) and cone-driven corrective morph weights from character.rig.json.
//
// All rule vectors are in glTF model space in the bind pose. Per joint J:
//   R_J = rot(W_J) * rot(W_J_bind)^-1      (model-space rotation of J away from its bind pose)
//   D_S = R_P^-1 * R_S                      (S's own rotation; P = S's parent, or the rule's frame)
// Run after the animation pose and before rendering: helpers first (in file order, each followed by a
// world-matrix update, as the Blender emulation does), then the morph weights.
import * as THREE from 'three/webgpu';

export interface Gain {
  'flex+': number;
  'flex-': number;
  'abd+': number;
  'abd-': number;
}
interface HelperBase {
  bone: string;
  source: string;
  frame?: string;
  source_frame?: string;
}
export interface TwistRule extends HelperBase {
  type: 'twist';
  axis: number[];
  factor: number;
}
export interface SwingRule extends HelperBase {
  type: 'swing';
  axis: number[];
  factor: number;
}
export interface FollowRule extends HelperBase {
  type: 'follow';
  rest_dir: number[];
  flex_axis: number[];
  abd_axis: number[];
  gain: Gain;
}
export type HelperRule = TwistRule | SwingRule | FollowRule;
export interface ConeRule {
  type: 'cone';
  name: string;
  bone: string;
  ref: string;
  rest_dir: number[];
  target_dir: number[];
  power?: number;
  start?: number;
  meshes?: string[];
  angle_deg?: number;
}
export interface RigRules {
  version: number;
  helpers?: HelperRule[];
  morphs?: ConeRule[];
}

const v3 = (a: number[]) => new THREE.Vector3(a[0] ?? 0, a[1] ?? 0, a[2] ?? 0);
const IDENTITY = new THREE.Quaternion();

/** q = swing * twist, twist about unit axis a. Returns [swing, twist, angle]. Mirrors swing_twist(). */
export function swingTwist(q: THREE.Quaternion, a: THREE.Vector3): [THREE.Quaternion, THREE.Quaternion, number] {
  const p = q.x * a.x + q.y * a.y + q.z * a.z;
  const tw = new THREE.Quaternion(a.x * p, a.y * p, a.z * p, q.w);
  const mag = Math.hypot(tw.x, tw.y, tw.z, tw.w);
  if (mag < 1e-9) tw.identity();
  else tw.set(tw.x / mag, tw.y / mag, tw.z / mag, tw.w / mag);
  let ang = 2 * Math.atan2(p, q.w);
  if (ang > Math.PI) ang -= 2 * Math.PI;
  else if (ang < -Math.PI) ang += 2 * Math.PI;
  const sw = q.clone().multiply(tw.clone().invert());
  return [sw, tw, ang];
}

function rotvec(v: THREE.Vector3): THREE.Quaternion {
  const a = v.length();
  if (a < 1e-9) return new THREE.Quaternion();
  return new THREE.Quaternion().setFromAxisAngle(v.clone().divideScalar(a), a);
}

export function coneWeight(d: THREE.Vector3, d0: THREE.Vector3, t: THREE.Vector3, p = 1, start = 0): number {
  const span = d0.angleTo(t);
  if (span < 1e-6) return 0;
  let w = 1 - d.angleTo(t) / span;
  if (start > 0) w = (w - start) / (1 - start);
  w = Math.max(0, Math.min(1, w));
  return w ** p;
}

/** The rules bound to one skeleton (bones found by name under the glTF scene root). */
export class DeformRuntime {
  readonly bones = new Map<string, THREE.Bone>();
  /** rot(W_J_bind) in model space. */
  private readonly restRot = new Map<string, THREE.Quaternion>();
  private readonly modelInv = new THREE.Matrix4();
  private readonly meshes: THREE.Mesh[] = [];
  readonly missing: string[] = [];
  lastWeights: Record<string, number> = {};

  constructor(
    private readonly root: THREE.Object3D,
    readonly rules: RigRules,
  ) {
    root.updateMatrixWorld(true);
    this.modelInv.copy(root.matrixWorld).invert();
    root.traverse((o) => {
      if ((o as THREE.Bone).isBone) this.bones.set(o.name, o as THREE.Bone);
      const m = o as THREE.Mesh;
      if (m.isMesh && m.morphTargetDictionary) this.meshes.push(m);
    });
    for (const [name, b] of this.bones) this.restRot.set(name, this.worldRot(b));
    for (const h of rules.helpers ?? []) for (const n of [h.bone, h.source]) if (!this.bones.has(n)) this.missing.push(n);
    for (const m of rules.morphs ?? []) for (const n of [m.bone, m.ref]) if (!this.bones.has(n)) this.missing.push(n);
  }

  /** Current model-space rotation of a bone (assumes matrixWorld is up to date). */
  worldRot(b: THREE.Object3D): THREE.Quaternion {
    const m = new THREE.Matrix4().multiplyMatrices(this.modelInv, b.matrixWorld);
    const q = new THREE.Quaternion();
    m.decompose(new THREE.Vector3(), q, new THREE.Vector3());
    return q;
  }

  restRotation(name: string): THREE.Quaternion | undefined {
    return this.restRot.get(name);
  }

  /** R_J: rotation of J away from its bind pose, model space. Identity for unknown / null. */
  R(name: string | undefined): THREE.Quaternion {
    if (!name) return new THREE.Quaternion();
    const b = this.bones.get(name);
    const r0 = this.restRot.get(name);
    if (!b || !r0) return new THREE.Quaternion();
    return this.worldRot(b).multiply(r0.clone().invert());
  }

  private parentBoneName(name: string): string | undefined {
    const p = this.bones.get(name)?.parent as THREE.Bone | null | undefined;
    return p && p.isBone ? p.name : undefined;
  }

  D(s: string, frame?: string): THREE.Quaternion {
    const p = frame ?? this.parentBoneName(s);
    return this.R(p).invert().multiply(this.R(s));
  }

  /** Set a bone's model-space rotation delta (R_H); its translation stays the bind offset. */
  setWorldRot(name: string, Rw: THREE.Quaternion): void {
    const b = this.bones.get(name);
    const r0 = this.restRot.get(name);
    if (!b || !r0) return;
    const want = Rw.clone().multiply(r0); // model-space world rotation
    const parent = b.parent;
    const parentRot = parent ? this.worldRot(parent) : new THREE.Quaternion();
    b.quaternion.copy(parentRot.invert().multiply(want));
    b.updateMatrixWorld(true);
  }

  helperRotation(h: HelperRule): THREE.Quaternion {
    const F = this.R(h.frame);
    if (h.type === 'twist') {
      const a = v3(h.axis).normalize();
      const [, , ang] = swingTwist(this.D(h.source, h.source_frame), a);
      return F.multiply(new THREE.Quaternion().setFromAxisAngle(a, h.factor * ang));
    }
    if (h.type === 'swing') {
      const a = v3(h.axis).normalize();
      const [sw] = swingTwist(this.D(h.source, h.source_frame), a);
      return F.multiply(IDENTITY.clone().slerp(sw, h.factor));
    }
    const q = this.D(h.source, h.source_frame);
    const d0 = v3(h.rest_dir).normalize();
    const d = d0.clone().applyQuaternion(q);
    const sw = new THREE.Quaternion().setFromUnitVectors(d0, d.normalize());
    // to_axis_angle of the shortest arc
    const ang = 2 * Math.acos(Math.min(1, Math.max(-1, sw.w)));
    const s = Math.sqrt(Math.max(0, 1 - sw.w * sw.w));
    const ax = s < 1e-9 ? new THREE.Vector3(1, 0, 0) : new THREE.Vector3(sw.x / s, sw.y / s, sw.z / s);
    const v = ax.multiplyScalar(ang);
    const L = v3(h.flex_axis).normalize();
    const N = v3(h.abd_axis).normalize();
    const g = h.gain;
    const fl = v.dot(L);
    const ab = v.dot(N);
    const gf = fl >= 0 ? g['flex+'] : g['flex-'];
    const ga = ab >= 0 ? g['abd+'] : g['abd-'];
    return F.multiply(rotvec(L.multiplyScalar(gf * fl).add(N.multiplyScalar(ga * ab))));
  }

  morphWeights(): Record<string, number> {
    const out: Record<string, number> = {};
    for (const m of this.rules.morphs ?? []) {
      const d0 = v3(m.rest_dir).normalize();
      const t = v3(m.target_dir).normalize();
      const q = this.R(m.ref).invert().multiply(this.R(m.bone));
      out[m.name] = coneWeight(d0.clone().applyQuaternion(q), d0, t, m.power ?? 1, m.start ?? 0);
    }
    return out;
  }

  /** Helpers, then corrective weights on every mesh carrying a target of that name (others zeroed). */
  apply(morphs = true): Record<string, number> {
    this.root.updateMatrixWorld(true);
    for (const h of this.rules.helpers ?? []) {
      if (!this.bones.has(h.bone)) continue;
      this.setWorldRot(h.bone, this.helperRotation(h));
    }
    const w = morphs ? this.morphWeights() : {};
    for (const mesh of this.meshes) {
      const dict = mesh.morphTargetDictionary;
      const infl = mesh.morphTargetInfluences;
      if (!dict || !infl) continue;
      for (const [name, idx] of Object.entries(dict)) infl[idx] = w[name] ?? 0;
    }
    this.lastWeights = w;
    return w;
  }
}
