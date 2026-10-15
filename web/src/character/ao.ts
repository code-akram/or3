// Screen-space ambient occlusion for the character (T10, bench/m1/v4/checkpoint-2.md §2 item 3).
//
// Replaces the T6 stand-in (the baked AO multiplied into the direct diffuse at 0.5): three's GTAONode
// (Activision GTAO, quadratic ray stepping) at HALF resolution on a depth + view-normal prepass of the
// same camera. The prepass draws every mesh with a small unlit material that writes its view normal;
// the hair, beard, brow and lash cards keep their alpha test (map alpha >= 0.5), so the cards occlude
// and receive like the strands would (the jaw under the beard, the neck and ear under the hair).
// The materials read the AO texture at their screen position and multiply it into the DIRECT diffuse,
// weighted per light by light.userData.aoWeight (stage.ts: min(1, size / distance), floored by
// ao.lightWeightMin): the occlusion of a large soft emitter, which a point-light shadow map misses.
// Speculars are left alone. The hemisphere (indirect) keeps three's own aoNode (the baked map).
//
// The prepass + GTAO run in Output.render before the scene pass, at the capture's own size (GTAONode
// sizes itself from the canvas otherwise; the headless canvas is 256 px).
import * as THREE from 'three/webgpu';
import * as TSL from 'three/tsl';
import GTAONode from 'three/addons/tsl/display/GTAONode.js';
import type { ParamStore } from './materials/params';
// TSL's TypeScript types are too narrow for shader-graph code; the graph is checked at build.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const { float, normalView, texture, vec4 } = TSL as any;

/* eslint-disable @typescript-eslint/no-explicit-any */
type N = any;

/** GTAONode that renders at a size we give it, not the drawing buffer's. */
class SizedGTAO extends GTAONode {
  size: [number, number] = [1, 1];
  override setSize(): void {
    super.setSize(this.size[0], this.size[1]);
  }
}

export class SceneAO {
  readonly texture: THREE.Texture;
  /** the prepass view normals (debug: ?aoview=normal) */
  get normalTexture(): THREE.Texture {
    return this.prepass.texture;
  }
  /** the prepass depth (float; T19 contact shadows march it) */
  get depthTexture(): THREE.DepthTexture {
    return this.prepass.depthTexture as THREE.DepthTexture;
  }
  /** the camera matrices the prepass was drawn with (T19 contact shadows reconstruct from them) */
  readonly prepassProjection = new THREE.Matrix4();
  readonly prepassProjectionInverse = new THREE.Matrix4();
  private readonly prepass: THREE.RenderTarget;
  private readonly node: SizedGTAO;
  private readonly trigger: THREE.QuadMesh;
  private readonly triggerRT = new THREE.RenderTarget(1, 1, { depthBuffer: false });
  private readonly swaps = new Map<THREE.Material, THREE.MeshBasicNodeMaterial>();
  lastMs = 0;
  /** T24 quality tiers: the prepass + GTAO size as a fraction of the frame (0.5 half, 0.25 quarter res) */
  resolution = 0.5;

  constructor(
    private readonly renderer: THREE.WebGPURenderer,
    camera: THREE.Camera,
    /** the character (the scene passed to render() is what the prepass draws) */
    readonly root: THREE.Object3D,
    private readonly P: ParamStore,
  ) {
    const depth = new THREE.DepthTexture(1, 1);
    depth.type = THREE.FloatType;
    this.prepass = new THREE.RenderTarget(1, 1, { type: THREE.HalfFloatType, depthBuffer: true, depthTexture: depth });
    this.prepass.texture.name = 'AO prepass normal';
    this.node = new SizedGTAO(texture(depth), texture(this.prepass.texture), camera);
    this.node.resolutionScale = 1;
    // the node's own uniforms, replaced by the live params before the node is built
    (this.node as unknown as { radius: N; thickness: N }).radius = P.u('ao.radius');
    (this.node as unknown as { radius: N; thickness: N }).thickness = P.u('ao.thickness');
    this.node.samples.value = P.get('ao.samples') as number;
    this.texture = this.node.getTextureNode().value as THREE.Texture;
    const m = new THREE.NodeMaterial();
    m.fragmentNode = vec4(this.node, float(0), float(0), float(1));
    this.trigger = new THREE.QuadMesh(m);
  }

  /** The prepass material of a source material: view normal out, the source's alpha test kept. */
  private swapOf(src: THREE.Material): THREE.MeshBasicNodeMaterial {
    let m = this.swaps.get(src);
    if (m) return m;
    m = new THREE.MeshBasicNodeMaterial();
    m.name = `${src.name}_aoprepass`;
    m.colorNode = vec4(normalView, 1);
    m.side = src.side;
    const s = src as THREE.MeshStandardMaterial;
    if (s.alphaTest > 0 && s.map) {
      // cards: map alpha (the coverage of the strands), test at 0.5
      m.opacityNode = texture(s.map).a;
      m.alphaTest = 0.5;
    }
    this.swaps.set(src, m);
    return m;
  }

  /** Depth + normal prepass and GTAO at `resolution` (half) of w x h (call before the scene pass). */
  render(scene: THREE.Scene, camera: THREE.Camera, w: number, h: number): void {
    const t = performance.now();
    const hw = Math.max(1, Math.floor(w * this.resolution));
    const hh = Math.max(1, Math.floor(h * this.resolution));
    if (this.prepass.width !== hw || this.prepass.height !== hh) this.prepass.setSize(hw, hh);
    this.node.size = [hw, hh];
    this.node.samples.value = this.P.get('ao.samples') as number;
    const restore: [THREE.Mesh, THREE.Material | THREE.Material[]][] = [];
    const hidden: THREE.Object3D[] = [];
    // L2: every mesh of the scene, not only the character's: the stage floor drew its lit material here
    // (its shaded colour went into the normal target under the feet, and binding the key's contact term
    // before the contact pass had rendered its target made the first render recreate that texture under
    // the floor's bind group: "Destroyed texture [contact shadows] used in a submit" on every live frame)
    scene.traverse((o) => {
      const mesh = o as THREE.Mesh;
      if (!mesh.isMesh) return;
      if (o.userData.hairPrepass) {
        if (o.visible) hidden.push(o);
        o.visible = false;
        return;
      }
      restore.push([mesh, mesh.material]);
      mesh.material = Array.isArray(mesh.material) ? mesh.material.map((x) => this.swapOf(x)) : this.swapOf(mesh.material);
    });
    const r = this.renderer;
    const bg = scene.background;
    scene.background = null;
    const prevTarget = r.getRenderTarget();
    const clear = new THREE.Color();
    r.getClearColor(clear);
    const alpha = r.getClearAlpha();
    r.setClearColor(0x000000, 0);
    r.setRenderTarget(this.prepass);
    r.render(scene, camera);
    this.prepassProjection.copy(camera.projectionMatrix);
    this.prepassProjectionInverse.copy(camera.projectionMatrixInverse);
    for (const [mesh, mat] of restore) mesh.material = mat;
    for (const o of hidden) o.visible = true;
    scene.background = bg;
    // GTAO: rendering a quad that samples the node runs its pass (updateBefore) into its own target
    r.setRenderTarget(this.triggerRT);
    this.trigger.render(r);
    r.setRenderTarget(prevTarget);
    r.setClearColor(clear, alpha);
    this.lastMs = performance.now() - t;
  }
}
