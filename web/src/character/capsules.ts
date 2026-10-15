// Analytic capsule shadows on the ground (G1, the gameplay tier's grounding; bench/m1/v4/g1-gameplay-grounding.md).
//
// The gameplay tier shadows one light (the key, 1024 PCF). The hero rig's rim, kicker, wrap and fill then
// light the floor straight through the legs, and the shoes sit ON the floor rather than IN it (t24-tiers.md,
// tiers_3m_feet_2x.png). A second 1024 map (?shadows=key,rim) costs a depth pass of the whole character and
// one more sampled texture on every character material. This costs neither: the body is 14 capsules fitted
// once to the skinned mesh (torso, head, and per side the upper arm, forearm, hand, thigh, calf and foot),
// carried by their bones every frame, and the ground's copy of each unshadowed light multiplies by the
// light's visibility past them (only the ground: the character's own materials never see these nodes).
//
// FIT (bind pose, at setup). Every skinned vertex of the body, the suit and the shoes (not the hair, beard,
// eyes or mouth) goes to the capsule of its heaviest joint, in the capsule's anchor bone space. A capsule's
// axis is the cloud's principal axis, its radius the 65th percentile of the distance to the axis, and its
// segment the 3rd-97th percentile extent pulled in by the radius (the caps round the ends).
//
// VISIBILITY (per light, per ground fragment). For each capsule the closest approach of the ray p -> L to
// the segment gives the occluder's distance t along the ray and its offset D from the ray (direction n); the
// capsule covers the angular band [D - r, D + r] / t, across n. The emitter rect, projected on n, spans
// [-alpha, alpha] with alpha = (|ex.n| + |ey.n|) / |L - p| (ex, ey its half-axes): a vertical strip light
// behind a vertical leg gives the strip's width, not its height, as it does in the hero tier's PCSS. The
// covered fraction is the overlap of the two intervals over 2 alpha; visibility is the product of
// (1 - coverage) over the capsules; a bounding sphere test skips the loop for rays that pass nowhere near
// the body. The penumbra therefore widens with the
// occluder's distance (a shoe's contact is sharp and dark, a hip's shadow 1 m away is wide and soft), as
// PCSS does in the hero tier.
//
// Cost: no pass, no texture, no draw call; per ground fragment a ray-sphere test per light and, for rays
// that pass the body, 14 closed-form segment tests. Switch: ?floorshadow=0|1 (tiers.ts; gameplay 1, hero 0),
// params ground.* (strength, radius scale, emitter scale).
import * as THREE from 'three/webgpu';
import * as TSL from 'three/tsl';
import type { ParamStore } from './materials/params';
// TSL's TypeScript types are too narrow for shader-graph code; the graph is checked at build.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const { Fn, If, Loop, float, int, positionWorld, uniform, uniformArray } = TSL as any;
/* eslint-disable @typescript-eslint/no-explicit-any */
type N = any;

/** Capsule name -> joint-name pattern (`X` is the side) and anchor bone (the first name). */
const GROUPS: { name: string; anchor: string; re: RegExp; sided: boolean }[] = [
  { name: 'torso', anchor: 'spine_01', re: /^(pelvis|spine_0[1-3]|skirt_.*|clavicle_[lr])$/, sided: false },
  { name: 'head', anchor: 'head', re: /^(neck_01|head)$/, sided: false },
  { name: 'upperarm', anchor: 'upperarm_X', re: /^(upperarm|upperarm_twist_01|deltoid_helper)_X$/, sided: true },
  { name: 'lowerarm', anchor: 'lowerarm_X', re: /^(lowerarm|lowerarm_twist_01)_X$/, sided: true },
  { name: 'hand', anchor: 'hand_X', re: /^(hand|index_0\d|middle_0\d|ring_0\d|pinky_0\d|thumb_0\d)_X$/, sided: true },
  { name: 'thigh', anchor: 'thigh_X', re: /^(thigh|thigh_twist_01|hip_helper)_X$/, sided: true },
  { name: 'calf', anchor: 'calf_X', re: /^calf_X$/, sided: true },
  { name: 'foot', anchor: 'foot_X', re: /^(foot|ball)_X$/, sided: true },
];
/** Meshes / materials that are not the body's silhouette (cards, eyes, mouth). */
const SKIP = /hair|beard|brow|lash|eye|caruncle|lidshell|meniscus|teeth|tongue|nails/i;
export const MAX_CAPSULES = 16;

export interface CapsuleFit {
  name: string;
  bone: string;
  /** segment ends and radius in the anchor bone's space (m) */
  a: number[];
  b: number[];
  r: number;
  verts: number;
}

interface Capsule {
  fit: CapsuleFit;
  bone: THREE.Bone;
  a: THREE.Vector3;
  b: THREE.Vector3;
}

function pct(v: number[], p: number): number {
  const s = [...v].sort((x, y) => x - y);
  return s[Math.min(s.length - 1, Math.max(0, Math.floor(p * (s.length - 1))))] ?? 0;
}

/** The principal axis of a point cloud (power iteration on the covariance). */
function principalAxis(pts: THREE.Vector3[], mean: THREE.Vector3): THREE.Vector3 {
  const c: [number, number, number, number, number, number] = [0, 0, 0, 0, 0, 0]; // xx xy xz yy yz zz
  for (const p of pts) {
    const x = p.x - mean.x;
    const y = p.y - mean.y;
    const z = p.z - mean.z;
    c[0] += x * x;
    c[1] += x * y;
    c[2] += x * z;
    c[3] += y * y;
    c[4] += y * z;
    c[5] += z * z;
  }
  let v = new THREE.Vector3(0.31, 0.83, 0.47).normalize();
  for (let i = 0; i < 64; i++) {
    const n = new THREE.Vector3(c[0] * v.x + c[1] * v.y + c[2] * v.z, c[1] * v.x + c[3] * v.y + c[4] * v.z, c[2] * v.x + c[4] * v.y + c[5] * v.z);
    if (n.lengthSq() < 1e-20) break;
    v = n.normalize();
  }
  return v;
}

export class CapsuleShadows {
  readonly capsules: Capsule[] = [];
  private readonly A: THREE.Vector4[] = [];
  private readonly B: THREE.Vector4[] = [];
  private readonly capA: N;
  private readonly capB: N;
  private readonly count: N;
  /** bounding sphere of every capsule (xyz centre, w radius), world */
  private readonly bound: N;
  private readonly tmpA = new THREE.Vector3();
  private readonly tmpB = new THREE.Vector3();
  private readonly tmpC = new THREE.Vector3();
  private readonly box = new THREE.Box3();
  private readonly sphere = new THREE.Sphere();
  /** a light's shadow node, by light (twins of one emitter reuse it) */
  private readonly nodes = new Map<string, N>();

  constructor(
    model: THREE.Object3D,
    private readonly P: ParamStore,
  ) {
    this.fit(model);
    for (let i = 0; i < MAX_CAPSULES; i++) {
      this.A.push(new THREE.Vector4());
      this.B.push(new THREE.Vector4());
    }
    this.capA = uniformArray(this.A, 'vec4');
    this.capB = uniformArray(this.B, 'vec4');
    this.count = uniform(this.capsules.length, 'int');
    this.bound = uniform(new THREE.Vector4());
    this.update();
  }

  /** Per-frame: the capsules in world space from their bones (call before the ground draws). */
  update(): void {
    const rs = this.P.get('ground.capsuleRadiusScale') as number;
    this.box.makeEmpty();
    this.capsules.forEach((c, i) => {
      const wa = this.tmpA.copy(c.a).applyMatrix4(c.bone.matrixWorld);
      const wb = this.tmpB.copy(c.b).applyMatrix4(c.bone.matrixWorld);
      const r = c.fit.r * rs;
      this.A[i]!.set(wa.x, wa.y, wa.z, r);
      this.B[i]!.set(wb.x, wb.y, wb.z, 0);
      for (const w of [wa, wb]) {
        this.box.expandByPoint(this.tmpC.copy(w).addScalar(r));
        this.box.expandByPoint(this.tmpC.copy(w).addScalar(-r));
      }
    });
    this.box.getBoundingSphere(this.sphere);
    (this.bound.value as THREE.Vector4).set(this.sphere.center.x, this.sphere.center.y, this.sphere.center.z, this.sphere.radius);
  }

  fits(): CapsuleFit[] {
    return this.capsules.map((c) => c.fit);
  }

  private fit(model: THREE.Object3D): void {
    let skeleton: THREE.Skeleton | null = null;
    const meshes: THREE.SkinnedMesh[] = [];
    model.traverse((o) => {
      const m = o as THREE.SkinnedMesh;
      if (!m.isSkinnedMesh || o.userData.hairPrepass) return;
      const mat = Array.isArray(m.material) ? m.material[0] : m.material;
      if (SKIP.test(m.name) || SKIP.test(mat?.name ?? '')) return;
      skeleton ??= m.skeleton;
      meshes.push(m);
    });
    if (!skeleton) return;
    const sk = skeleton as THREE.Skeleton;
    const names = sk.bones.map((b) => b.name);
    const index = new Map(names.map((n, i) => [n, i]));
    // joint index -> capsule key; capsule key -> anchor joint index
    const jointCap = new Map<number, string>();
    const anchors = new Map<string, number>();
    for (const g of GROUPS) {
      for (const side of g.sided ? ['l', 'r'] : ['']) {
        const key = g.sided ? `${g.name}_${side}` : g.name;
        const re = new RegExp(g.re.source.replaceAll('X', side));
        const a = index.get(g.anchor.replace('X', side));
        if (a === undefined) continue;
        anchors.set(key, a);
        names.forEach((n, i) => {
          if (re.test(n)) jointCap.set(i, key);
        });
      }
    }
    const pts = new Map<string, THREE.Vector3[]>();
    const v = new THREE.Vector3();
    const m4 = new THREE.Matrix4();
    for (const mesh of meshes) {
      const g = mesh.geometry;
      const pos = g.attributes.position;
      const si = g.attributes.skinIndex;
      const sw = g.attributes.skinWeight;
      if (!pos || !si || !sw) continue;
      // a skinned mesh's joints are its own skeleton's: map them to the shared names
      const jmap = mesh.skeleton.bones.map((b) => index.get(b.name) ?? -1);
      const inv = new Map<number, THREE.Matrix4>();
      const step = Math.max(1, Math.floor(pos.count / 6000)); // a few thousand points per mesh are plenty
      for (let k = 0; k < pos.count; k += step) {
        let best = -1;
        let bw = 0;
        for (let c = 0; c < 4; c++) {
          const w = sw.getComponent(k, c);
          if (w > bw) [bw, best] = [w, si.getComponent(k, c)];
        }
        const j = jmap[best] ?? -1;
        const key = jointCap.get(j);
        if (!key) continue;
        const ai = anchors.get(key)!;
        let M = inv.get(ai);
        if (!M) {
          // bind-pose vertex -> anchor bone space: boneInverse x bindMatrix
          const bi = mesh.skeleton.bones.findIndex((b) => b.name === names[ai]);
          const boneInv = bi >= 0 ? mesh.skeleton.boneInverses[bi]! : sk.boneInverses[ai]!;
          M = m4.clone().multiplyMatrices(boneInv, mesh.bindMatrix);
          inv.set(ai, M);
        }
        v.fromBufferAttribute(pos, k).applyMatrix4(M);
        let arr = pts.get(key);
        if (!arr) pts.set(key, (arr = []));
        arr.push(v.clone());
      }
    }
    for (const [key, cloud] of pts) {
      if (cloud.length < 24 || this.capsules.length >= MAX_CAPSULES) continue;
      const mean = cloud.reduce((s, p) => s.add(p), new THREE.Vector3()).multiplyScalar(1 / cloud.length);
      const axis = principalAxis(cloud, mean);
      const ts: number[] = [];
      const ds: number[] = [];
      const off = new THREE.Vector3();
      for (const p of cloud) {
        off.subVectors(p, mean);
        const t = off.dot(axis);
        ts.push(t);
        ds.push(off.addScaledVector(axis, -t).length());
      }
      const r = pct(ds, 0.65);
      let t0 = pct(ts, 0.03) + r;
      let t1 = pct(ts, 0.97) - r;
      if (t0 > t1) t0 = t1 = (t0 + t1) / 2;
      const a = mean.clone().addScaledVector(axis, t0);
      const b = mean.clone().addScaledVector(axis, t1);
      const bone = sk.bones[anchors.get(key)!]!;
      const r3 = (x: THREE.Vector3) => [+x.x.toFixed(4), +x.y.toFixed(4), +x.z.toFixed(4)];
      this.capsules.push({ fit: { name: key, bone: bone.name, a: r3(a), b: r3(b), r: +r.toFixed(4), verts: cloud.length }, bone, a, b });
    }
  }

  /** Forget the per-light nodes (the stage rebuilds its lights per view). */
  reset(): void {
    this.nodes.clear();
  }

  /** The ground's visibility of a rect emitter: its world half-axes ex, ey (m) at the light's position.
   * A capsule shadows the band of the emitter across its own direction, so the penumbra comes from the
   * rect's extent along that direction (a vertical strip behind a vertical leg: its 0.3 m width, not its
   * 1.5 m height). Lights at one place (a light and its twins) share the node. */
  visibility(light: THREE.Light, ex: THREE.Vector3, ey: THREE.Vector3): N {
    const key = light.name.replace(/_(hair|cloth|skin|props|beard)$/, '');
    const hit = this.nodes.get(key);
    if (hit) return hit;
    const lp = uniform(new THREE.Vector3()).onRenderUpdate(() => (lp.value as THREE.Vector3).setFromMatrixPosition(light.matrixWorld));
    const soft = this.P.u('ground.capsuleSoftness');
    const EX = uniform(ex.clone()).mul(soft);
    const EY = uniform(ey.clone()).mul(soft);
    const { capA, capB, count, bound } = this;
    const strength = this.P.u('ground.capsuleStrength');
    const node = Fn(() => {
      const p = positionWorld.toVar();
      const toL = lp.sub(p).toVar();
      const dist = toL.length().toVar();
      const rd = toL.div(dist).toVar();
      const alphaMax = EX.length().add(EY.length()).div(dist).toVar(); // the emitter's widest angular half-extent
      const vis = float(1).toVar();
      // the ray passes within the body's bounding sphere (widened by the penumbra)?
      const oc = bound.xyz.sub(p);
      const tc = oc.dot(rd);
      const dperp = oc.sub(rd.mul(tc)).length();
      If(tc.greaterThan(0).and(dperp.lessThan(bound.w.add(tc.mul(alphaMax)))), () => {
        Loop({ start: int(0), end: count, type: 'int', condition: '<' }, ({ i }: { i: N }) => {
          const ca = capA.element(i);
          const a = ca.xyz;
          const r = ca.w;
          const ba = capB.element(i).xyz.sub(a);
          const oa = p.sub(a);
          const baba = ba.dot(ba);
          const dba = rd.dot(ba);
          const oad = oa.dot(rd);
          const oaba = oa.dot(ba);
          // closest approach of the ray and the segment: s on the segment, t on the ray
          const s = oaba.sub(oad.mul(dba)).div(baba.sub(dba.mul(dba)).max(1e-6)).clamp(0, 1);
          const q = a.add(ba.mul(s));
          const t = q.sub(p).dot(rd);
          const tt = t.max(1e-4);
          const off = q.sub(p.add(rd.mul(t)));
          const D = off.length();
          // the emitter's angular half-extent across the capsule (its projection on the offset direction)
          const nb = off.div(D.max(1e-6));
          const alpha = D.greaterThan(1e-5).select(EX.dot(nb).abs().add(EY.dot(nb).abs()).div(dist), alphaMax).max(1e-3);
          const delta = D.div(tt);
          const rho = r.div(tt);
          // covered fraction of the emitter's extent [-alpha, alpha] by the band [delta - rho, delta + rho]
          const cover = delta.add(rho).min(alpha).sub(delta.sub(rho).max(alpha.negate())).div(alpha.mul(2)).clamp(0, 1);
          // only occluders between the receiver and the emitter
          const inside = t.greaterThan(1e-3).and(t.lessThan(dist));
          vis.mulAssign(inside.select(cover.oneMinus(), float(1)));
        });
      });
      return vis.oneMinus().mul(strength).oneMinus();
    })();
    this.nodes.set(key, node);
    return node;
  }
}
