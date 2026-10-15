// Screen-space contact shadows for the key light (T19, bench/m1/v4/checkpoint-3.md §2.5): the shadow at
// the scale a shadow map cannot hold (its bias and normal offset are a few millimetres): collar on neck,
// lid on globe, under the nose, the hair edge on the forehead.
//
// A 'pre' pass of Output's hook (output.ts header), after GTAO: on the GTAO prepass depth + view normals
// (ao.ts, half resolution, the jittered camera of this frame), per pixel a ray from the surface (offset
// along its normal) toward a random point of the key's rect (a new point every frame: the temporal AA
// averages them into the area light's soft contact edge, as the stills' 24 subframes do), light.contactSteps
// steps over light.contactDistance, quadratically spaced so the first millimetres are dense. A step is
// occluded when the depth buffer's surface is in front of it by more than a pixel's footprint and less
// than light.contactThickness; the result fades out over the last 40 % of the ray. It is the same
// screen-space shadow as three's SSSNode (tsl/display), but toward a point / area light at a fixed step
// count, sized by Output instead of by the canvas, with a soft end.
//
// The key light's shadow node multiplies by it (stage.ts), so it darkens the key's diffuse and specular
// on every material but the hair (whose key twin has the deep hair shadow).
//
// T24: the target is allocated once (CAP², R8) and each frame renders into its top-left w x h (viewport);
// the scene samples it through a UV scale. A resize used to rt.setSize(), which destroys the GPU texture
// while the materials' bind groups still hold it (three re-binds only on a full refresh of a render object,
// and the key's shadow node is not a material property it watches): "Destroyed texture [contact shadows]
// used in a submit" on canvas frames after a capture at another size. Growing past CAP (rare) swaps in a
// larger target and forces that refresh.
import * as THREE from 'three/webgpu';
import * as TSL from 'three/tsl';
import type { SceneAO } from './ao';
import type { FrameContext, OutputPass } from './output';
import type { ParamStore } from './materials/params';
import { temporalFrame } from './temporal';
// TSL's TypeScript types are too narrow for shader-graph code; the graph is checked at build.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const T = TSL as any;
const { Fn, float, vec2, vec3, vec4, uv, uniform, texture, screenCoordinate, screenUV, interleavedGradientNoise, getViewPosition, getScreenPosition, perspectiveDepthToViewZ, smoothstep, mix, max, fract } = T;

/* eslint-disable @typescript-eslint/no-explicit-any */
type N = any;

export class ContactShadows implements OutputPass {
  readonly name = 'contact';
  readonly stage = 'pre' as const;
  readonly order = 10;
  enabled = true;
  static CAP = 2048;
  rt = ContactShadows.target(ContactShadows.CAP, ContactShadows.CAP);
  /** T24: the sampled texture node, the scale from screen UV to the used rect, and the last texel's centre */
  private readonly texNode: N;
  private readonly uvScale = uniform(new THREE.Vector2(1, 1));
  private readonly uvMax = uniform(new THREE.Vector2(1, 1));
  private readonly retired: THREE.RenderTarget[] = [];
  /** 1 once the pass has run with a key light (the shadow node reads white before) */
  private readonly on = uniform(0);
  /** the contact term at this fragment (1 = lit), for the key's shadow node */
  readonly node: N;
  private readonly quad: THREE.QuadMesh;
  private readonly proj = uniform(new THREE.Matrix4());
  private readonly projInv = uniform(new THREE.Matrix4());
  private readonly near = uniform(0.05);
  private readonly far = uniform(200);
  private readonly lightPos = uniform(new THREE.Vector3());
  private readonly halfW = uniform(new THREE.Vector3());
  private readonly halfH = uniform(new THREE.Vector3());
  /** world size of one prepass pixel per metre of depth */
  private readonly pxScale = uniform(0.001);
  lastMs = 0;

  constructor(
    private readonly ao: SceneAO,
    private readonly P: ParamStore,
    private readonly keyLight: () => THREE.Light | null,
  ) {
    this.texNode = texture(this.rt.texture, screenUV.mul(this.uvScale).min(this.uvMax));
    this.node = mix(float(1), this.texNode.r, this.on);
    const m = new THREE.NodeMaterial();
    m.name = 'contact shadows';
    m.fragmentNode = this.shader();
    this.quad = new THREE.QuadMesh(m);
  }

  private shader(): N {
    const P = this.P;
    const steps = Math.max(2, P.get('light.contactSteps') as number);
    const depthTex = this.ao.depthTexture;
    const normalTex = this.ao.normalTexture;
    return Fn(() => {
      const q = uv();
      const d = texture(depthTex).sample(q).r;
      const pos = getViewPosition(q, d, this.projInv).toVar();
      const n = texture(normalTex).sample(q).xyz.normalize();
      const f = temporalFrame.mod(64);
      const n1 = interleavedGradientNoise(screenCoordinate.xy.add(f.mul(5.588238)));
      const n2 = interleavedGradientNoise(screenCoordinate.yx.mul(1.37).add(vec2(23.1, 7.7)).add(f.mul(3.31)));
      const xi = fract(vec2(n1, n2).add(f.mul(vec2(0.7548777, 0.5698403))));
      const target = this.lightPos.add(this.halfW.mul(xi.x.mul(2).sub(1))).add(this.halfH.mul(xi.y.mul(2).sub(1)));
      const dir = target.sub(pos).normalize().toVar();
      const facing = n.dot(dir).greaterThan(0.02);
      const nv = n.dot(pos.normalize().negate()).clamp(0.15, 1);
      const p0 = pos.add(n.mul(P.u('light.contactBias'))).toVar();
      const maxD = P.u('light.contactDistance');
      const thick = P.u('light.contactThickness');
      const jit = fract(n1.add(f.mul(0.618034)));
      let occ: N = float(0);
      for (let i = 0; i < steps; i++) {
        const s = jit.add(i).div(steps);
        const t = maxD.mul(s.mul(s));
        const Q = p0.add(dir.mul(t));
        const sq = getScreenPosition(Q, this.proj);
        const zs = perspectiveDepthToViewZ(texture(depthTex).sample(sq).r, this.near, this.far);
        const delta = zs.sub(Q.z); // > 0: the depth buffer's surface is in front of the ray point
        // a pixel's depth footprint, wider at grazing view (silhouettes: the half-res depth there mixes
        // the surface with what is behind it and would self-shadow the lit edge)
        const eps = max(P.u('light.contactBias'), Q.z.negate().mul(this.pxScale).mul(0.75).div(nv));
        const inside = sq.x.greaterThan(0).and(sq.x.lessThan(1)).and(sq.y.greaterThan(0)).and(sq.y.lessThan(1));
        const hit = delta.greaterThan(eps).and(delta.lessThan(thick)).and(inside);
        const fade = float(1).sub(smoothstep(0.6, 1.0, s));
        occ = max(occ, hit.select(fade, float(0)));
      }
      const lit = float(1).sub(occ.mul(P.u('light.contactIntensity')).clamp(0, 1));
      const bg = d.greaterThanEqual(0.999999);
      return vec4(vec3(bg.or(facing.not()).select(float(1), lit)), 1);
    })();
  }

  render(ctx: FrameContext): void {
    const light = this.keyLight();
    if (!light) {
      this.on.value = 0;
      return;
    }
    const t = performance.now();
    const src = this.ao.depthTexture.image as { width: number; height: number };
    const w = Math.max(1, src.width);
    const h = Math.max(1, src.height);
    if (w > this.rt.width || h > this.rt.height) this.grow(ctx.scene, w, h);
    const W = this.rt.width;
    const H = this.rt.height;
    this.rt.viewport.set(0, 0, w, h);
    this.uvScale.value.set(w / W, h / H);
    this.uvMax.value.set((w - 0.5) / W, (h - 0.5) / H);
    const cam = ctx.camera;
    this.proj.value.copy(this.ao.prepassProjection);
    this.projInv.value.copy(this.ao.prepassProjectionInverse);
    this.near.value = cam.near;
    this.far.value = cam.far;
    this.pxScale.value = (2 * Math.tan(((cam.fov * Math.PI) / 180) * 0.5)) / (h * (cam.view?.enabled ? cam.view.fullHeight / cam.view.height : 1) || 1);
    // the key's rect in view space (stage.ts keeps its size and orientation in userData for both paths)
    const view = cam.matrixWorldInverse;
    light.updateMatrixWorld();
    const pw = new THREE.Vector3().setFromMatrixPosition(light.matrixWorld).applyMatrix4(view);
    const q = (light.userData.rectQuat as THREE.Quaternion | undefined) ?? new THREE.Quaternion().setFromRotationMatrix(light.matrixWorld);
    const rot = new THREE.Matrix4().extractRotation(view).multiply(new THREE.Matrix4().makeRotationFromQuaternion(q));
    const rw = (light.userData.rectW as number | undefined) ?? 0.3;
    const rh = (light.userData.rectH as number | undefined) ?? rw;
    this.lightPos.value.copy(pw);
    this.halfW.value.set(rw * 0.5, 0, 0).applyMatrix4(rot);
    this.halfH.value.set(0, rh * 0.5, 0).applyMatrix4(rot);
    const r = ctx.renderer;
    r.setRenderTarget(this.rt);
    this.quad.render(r);
    this.on.value = 1;
    this.lastMs = performance.now() - t;
  }

  private static target(w: number, h: number): THREE.RenderTarget {
    const rt = new THREE.RenderTarget(w, h, { depthBuffer: false, type: THREE.UnsignedByteType, format: THREE.RedFormat });
    rt.texture.name = 'contact shadows';
    return rt;
  }

  /** A larger target: the old one stays alive (a bind group may still hold it) until dispose(). */
  private grow(scene: THREE.Scene, w: number, h: number): void {
    const n = Math.max(w, h, this.rt.width, this.rt.height);
    console.warn(`contact shadows: target grows to ${n}x${n} (prepass ${w}x${h})`);
    this.retired.push(this.rt);
    this.rt = ContactShadows.target(n, n);
    this.texNode.value = this.rt.texture;
    scene.traverse((o) => {
      const m = (o as THREE.Mesh).material;
      for (const x of Array.isArray(m) ? m : m ? [m] : []) x.needsUpdate = true;
    });
  }

  dispose(): void {
    for (const r of this.retired.splice(0)) r.dispose();
    this.rt.dispose();
  }
}
