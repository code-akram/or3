// Poses for the viewer: the bind pose, the exported hero-stage poses (per-bone deform matrices from
// blender/hero/export_rig.py), and debug presets that drive the corrective rules toward their targets
// so the correctives can be seen working.
import * as THREE from 'three/webgpu';
import type { DeformRuntime, ConeRule } from './deform';

/** Bones sorted parents-first. */
function ordered(rt: DeformRuntime): THREE.Bone[] {
  const out: THREE.Bone[] = [];
  const seen = new Set<THREE.Bone>();
  const visit = (b: THREE.Bone) => {
    if (seen.has(b)) return;
    const p = b.parent as THREE.Bone | null;
    if (p && p.isBone) visit(p);
    seen.add(b);
    out.push(b);
  };
  for (const b of rt.bones.values()) visit(b);
  return out;
}

export class Poser {
  private readonly bindLocal = new Map<THREE.Bone, { p: THREE.Vector3; q: THREE.Quaternion; s: THREE.Vector3 }>();
  private readonly order: THREE.Bone[];

  constructor(private readonly rt: DeformRuntime) {
    this.order = ordered(rt);
    for (const b of this.order) this.bindLocal.set(b, { p: b.position.clone(), q: b.quaternion.clone(), s: b.scale.clone() });
  }

  reset(): void {
    for (const [b, t] of this.bindLocal) {
      b.position.copy(t.p);
      b.quaternion.copy(t.q);
      b.scale.copy(t.s);
    }
    this.rt.bones.values().next().value?.parent?.updateMatrixWorld(true);
  }

  /** Apply per-bone deform matrices D (W_posed = D * W_bind, glTF model space), column-major arrays. */
  applyDeform(bones: Record<string, number[]>, amount = 1): number {
    this.reset();
    let n = 0;
    const root = this.order[0]?.parent;
    root?.updateMatrixWorld(true);
    const posedWorld = new Map<THREE.Object3D, THREE.Matrix4>();
    const bindWorld = new Map<THREE.Bone, THREE.Matrix4>();
    for (const b of this.order) bindWorld.set(b, b.matrixWorld.clone());
    for (const b of this.order) {
      const arr = bones[b.name];
      const Wb = bindWorld.get(b)!;
      let W: THREE.Matrix4;
      if (arr && arr.length === 16) {
        const D = new THREE.Matrix4().fromArray(arr);
        if (amount < 1) D.copy(lerpRigid(D, amount));
        W = D.multiply(Wb);
        n++;
      } else {
        // not in the export: keep its bind local transform under the posed parent
        const p = b.parent as THREE.Bone;
        const pw = posedWorld.get(p) ?? (p ? p.matrixWorld.clone() : new THREE.Matrix4());
        W = pw.clone().multiply(b.matrix);
      }
      posedWorld.set(b, W);
      const p = b.parent;
      const pw = p ? (posedWorld.get(p) ?? p.matrixWorld) : new THREE.Matrix4();
      const local = pw.clone().invert().multiply(W);
      local.decompose(b.position, b.quaternion, b.scale);
    }
    root?.updateMatrixWorld(true);
    return n;
  }

  /** Rotate bone `name` (model space) by delta q on top of its current pose, about its own head. */
  private rotateModel(name: string, q: THREE.Quaternion): void {
    const b = this.rt.bones.get(name);
    if (!b) return;
    b.parent?.updateMatrixWorld(true);
    const cur = this.rt.worldRot(b);
    const want = q.clone().multiply(cur);
    const pr = b.parent ? this.rt.worldRot(b.parent) : new THREE.Quaternion();
    b.quaternion.copy(pr.invert().multiply(want));
    b.updateMatrixWorld(true);
  }

  /** Swing rule bone B (relative to its ref) from rest_dir toward target_dir by `amount`. */
  driveCone(rule: ConeRule, amount: number): void {
    const d0 = new THREE.Vector3().fromArray(rule.rest_dir).normalize();
    const t = new THREE.Vector3().fromArray(rule.target_dir).normalize();
    const b = this.rt.bones.get(rule.bone);
    if (!b) return;
    let full: THREE.Quaternion;
    const ang = d0.angleTo(t);
    if (ang > (150 * Math.PI) / 180) {
      // near-antiparallel (the fist): curl about the knuckle line, the sign that moves d0 toward t
      const side = rule.bone.endsWith('_l') ? '_l' : '_r';
      const i = this.rt.bones.get('index_01' + side);
      const p = this.rt.bones.get('pinky_01' + side);
      const ax = i && p ? i.getWorldPosition(new THREE.Vector3()).sub(p.getWorldPosition(new THREE.Vector3())).normalize() : new THREE.Vector3(1, 0, 0);
      const qa = new THREE.Quaternion().setFromAxisAngle(ax, ang);
      const qb = new THREE.Quaternion().setFromAxisAngle(ax, -ang);
      full = d0.clone().applyQuaternion(qa).angleTo(t) < d0.clone().applyQuaternion(qb).angleTo(t) ? qa : qb;
    } else {
      full = new THREE.Quaternion().setFromUnitVectors(d0, t);
    }
    // current rotation of B relative to ref, replaced by the driven one: R_B = R_ref * slerp(I, full, a)
    const Rref = this.rt.R(rule.ref);
    const RB = Rref.multiply(new THREE.Quaternion().slerp(full, amount));
    const cur = this.rt.R(rule.bone);
    this.rotateModel(rule.bone, RB.multiply(cur.invert()));
  }

  /** Curl the fingers of one hand (for the fist corrective's driver look; middle_02 is driven by the rule). */
  curlFingers(side: '_l' | '_r', amount: number, skip?: string): void {
    const i = this.rt.bones.get('index_01' + side);
    const p = this.rt.bones.get('pinky_01' + side);
    if (!i || !p) return;
    const ax = i.getWorldPosition(new THREE.Vector3()).sub(p.getWorldPosition(new THREE.Vector3())).normalize();
    const s = side === '_l' ? 1 : -1;
    for (const f of ['index', 'middle', 'ring', 'pinky']) {
      for (const [seg, deg] of [['01', 65], ['02', 80], ['03', 55]] as const) {
        const n = `${f}_${seg}${side}`;
        if (n === skip) continue;
        this.rotateModel(n, new THREE.Quaternion().setFromAxisAngle(ax, s * amount * (deg * Math.PI) / 180));
      }
    }
  }

  /** Twist a hand about the forearm axis (drives lowerarm_twist_01). */
  twistHand(side: '_l' | '_r', amount: number): void {
    const rule = this.rt.rules.helpers?.find((h) => h.bone === 'lowerarm_twist_01' + side);
    if (!rule || rule.type !== 'twist') return;
    const a = new THREE.Vector3().fromArray(rule.axis).normalize();
    this.rotateModel('hand' + side, new THREE.Quaternion().setFromAxisAngle(a, amount * (80 * Math.PI) / 180));
  }
}

function lerpRigid(D: THREE.Matrix4, t: number): THREE.Matrix4 {
  const p = new THREE.Vector3();
  const q = new THREE.Quaternion();
  const s = new THREE.Vector3();
  D.decompose(p, q, s);
  return new THREE.Matrix4().compose(p.multiplyScalar(t), new THREE.Quaternion().slerp(q, t), new THREE.Vector3(1, 1, 1));
}

/** Debug presets: cone rules (both sides) driven toward their targets, plus a few extras. */
export const PRESETS: Record<string, string[]> = {
  rest: [],
  arms_up: ['corr_arm_up_l', 'corr_arm_up_r'],
  arms_fwd: ['corr_arm_fwd_l', 'corr_arm_fwd_r'],
  arms_down: ['corr_arm_down_l', 'corr_arm_down_r'],
  elbows: ['corr_elbow_l', 'corr_elbow_r'],
  hips_fwd: ['corr_hip_fwd_l', 'corr_hip_fwd_r'],
  knees: ['corr_hip_fwd_l', 'corr_hip_fwd_r', 'corr_knee_l', 'corr_knee_r'],
  fists: ['corr_fist_l', 'corr_fist_r', '+curl'],
  twist: ['+twist'],
};

export function applyPreset(poser: Poser, rt: DeformRuntime, name: string, amount: number): void {
  poser.reset();
  const list = PRESETS[name] ?? [];
  for (const item of list) {
    if (item === '+curl') {
      poser.curlFingers('_l', amount, 'middle_02_l');
      poser.curlFingers('_r', amount, 'middle_02_r');
      continue;
    }
    if (item === '+twist') {
      poser.twistHand('_l', amount);
      poser.twistHand('_r', amount);
      continue;
    }
    const rule = rt.rules.morphs?.find((m) => m.name === item);
    if (rule) poser.driveCone(rule, amount);
  }
}
