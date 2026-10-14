// Output: the scene renders scene-linear into a half-float MSAA target; one full-screen pass applies
// exposure, the hero grade (white balance, CDL, saturation, vignette; blender/hero/grade.py) and AgX,
// and encodes sRGB itself. The same pass draws to the canvas or into an RGBA8 target that is read
// back for headless screenshots (the WebGPU canvas does not reach headless screenshots).
// A later ink-line / paint pass slots in here (style.ts).
import * as THREE from 'three/webgpu';
import * as TSL from 'three/tsl';
// TSL's TypeScript types are too narrow for shader-graph code; the graph is checked at build.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const { agxToneMapping, float, max, mix, pow, texture, uniform, uv, vec3, vec4 } = TSL as any;

/* eslint-disable @typescript-eslint/no-explicit-any */
type N = any;

export interface Grade {
  slope: number[];
  offset: number[];
  power: number[];
  saturation: number;
  vignette_ev: number;
  wb_rgb: number[];
}

function srgbEncode(c: N): N {
  const lo = c.mul(12.92);
  const hi = pow(c, vec3(1 / 2.4)).mul(1.055).sub(0.055);
  return mix(lo, hi, c.greaterThan(vec3(0.0031308)));
}

export class Output {
  readonly samples: number;
  lastScene = { drawCalls: 0, triangles: 0 };
  private sceneRT: THREE.RenderTarget;
  private readonly quad: THREE.QuadMesh;
  private readonly mat: THREE.NodeMaterial;
  private readonly tex: N;
  readonly exposure = uniform(0);
  readonly gradeOn = uniform(0);
  readonly wb = uniform(new THREE.Vector3(1, 1, 1));
  readonly slope = uniform(new THREE.Vector3(1, 1, 1));
  readonly offset = uniform(new THREE.Vector3(0, 0, 0));
  readonly power = uniform(new THREE.Vector3(1, 1, 1));
  readonly saturation = uniform(1);
  readonly vignette = uniform(0);
  /** 1 = AgX view transform (the look-dev and hero frames); 0 = Standard (clamp + sRGB), the
   * shader-ball parity row, whose Cycles side renders with Blender's Standard view. */
  readonly viewAgX = uniform(1);

  constructor(
    private readonly renderer: THREE.WebGPURenderer,
    samples: number,
  ) {
    this.samples = samples;
    this.sceneRT = this.makeSceneRT(4, 4);
    this.tex = texture(this.sceneRT.texture);
    this.mat = new THREE.NodeMaterial();
    let c: N = this.tex.rgb.mul(pow(float(2), this.exposure));
    // grade (linear, before the view transform), on for the hero rig
    let g: N = c.div(this.wb);
    g = max(g.mul(this.slope).add(this.offset), vec3(0)).pow(this.power);
    const lum = g.dot(vec3(0.2126, 0.7152, 0.0722));
    g = mix(vec3(lum), g, this.saturation);
    const d = uv().sub(0.5).mul(2);
    g = g.mul(pow(float(2), this.vignette.mul(d.dot(d).mul(0.5))));
    c = mix(c, g, this.gradeOn);
    const mapped = mix(c, agxToneMapping(c, float(1)), this.viewAgX);
    this.mat.fragmentNode = vec4(srgbEncode(mapped.clamp(0, 1)), 1);
    this.quad = new THREE.QuadMesh(this.mat);
  }

  private makeSceneRT(w: number, h: number): THREE.RenderTarget {
    return new THREE.RenderTarget(w, h, { type: THREE.HalfFloatType, samples: this.samples, depthBuffer: true });
  }

  setGrade(on: boolean, exposureEV: number, g?: Grade): void {
    this.exposure.value = exposureEV;
    this.gradeOn.value = on ? 1 : 0;
    if (g) {
      const lum = 0.2126 * g.wb_rgb[0]! + 0.7152 * g.wb_rgb[1]! + 0.0722 * g.wb_rgb[2]!;
      this.wb.value.set(g.wb_rgb[0]! / lum, g.wb_rgb[1]! / lum, g.wb_rgb[2]! / lum);
      this.slope.value.fromArray(g.slope);
      this.offset.value.fromArray(g.offset);
      this.power.value.fromArray(g.power);
      this.saturation.value = g.saturation;
      this.vignette.value = g.vignette_ev;
    }
  }

  private ensure(w: number, h: number): void {
    if (this.sceneRT.width !== w || this.sceneRT.height !== h) this.sceneRT.setSize(w, h);
  }

  /** Render scene -> graded output into `target` (null = canvas). */
  render(scene: THREE.Scene, camera: THREE.Camera, w: number, h: number, target: THREE.RenderTarget | null = null): void {
    this.ensure(w, h);
    const r = this.renderer;
    r.setRenderTarget(this.sceneRT);
    const info = r.info.render;
    const [d0, t0] = [info.drawCalls, info.triangles];
    r.render(scene, camera);
    // scene pass only (incl. shadow passes), robust to the per-frame info reset
    this.lastScene = info.drawCalls >= d0 ? { drawCalls: info.drawCalls - d0, triangles: info.triangles - t0 } : { drawCalls: info.drawCalls, triangles: info.triangles };
    r.setRenderTarget(target);
    this.quad.render(r);
    r.setRenderTarget(null);
  }

  /** Render a w x h frame and read it back as top-down RGBA8 rows. */
  async capture(scene: THREE.Scene, camera: THREE.Camera, w: number, h: number): Promise<Uint8Array> {
    const out = new THREE.RenderTarget(w, h, { type: THREE.UnsignedByteType, depthBuffer: false });
    this.render(scene, camera, w, h, out);
    const px = new Uint8Array((await this.renderer.readRenderTargetPixelsAsync(out, 0, 0, w, h)) as Uint8Array);
    out.dispose();
    // WebGL2 readPixels returns bottom-up rows; WebGPU's buffer copy is top-down
    if (!(this.renderer.backend as unknown as { isWebGPUBackend?: boolean }).isWebGPUBackend) {
      const row = w * 4;
      const tmp = new Uint8Array(row);
      for (let y = 0; y < h >> 1; y++) {
        const a = y * row;
        const b = (h - 1 - y) * row;
        tmp.set(px.subarray(a, a + row));
        px.copyWithin(a, b, b + row);
        px.set(tmp, b);
      }
    }
    return px;
  }
}
