// ?passcheck=1: a self-test of Output's pass hook (output.ts header), and the smallest worked example
// for the tracks that plug into it (T17 screen-space SSS at 'scene', T19 contact shadows / PCSS).
// It adds an MRT attachment 'probe' (every material writes 0.5; the temporal modes only), and a 'scene'
// pass that multiplies the frame by (1, 2 x probe, 0.5) into its own target and hands that on. A capture
// with the flag is the normal frame with green unchanged (probe 0.5 x 2 = 1, read back from the MRT)
// and blue halved; a broken hook shows as an unchanged frame (pass not run) or a green-free one (the
// MRT attachment not written or not readable).
import * as THREE from 'three/webgpu';
import * as TSL from 'three/tsl';
import type { FrameContext, Output } from './output';
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const { float, mix, texture, uniform, uv, vec3, vec4 } = TSL as any;

export function installPassCheck(output: Output): void {
  output.addMRT('probe', float(0.5));
  let rt: THREE.RenderTarget | null = null;
  const placeholder = new THREE.DataTexture(new Uint8Array([255, 255, 255, 255]), 1, 1);
  placeholder.needsUpdate = true;
  const src = texture(placeholder);
  const probe = texture(placeholder);
  const hasProbe = uniform(0);
  const m = new THREE.NodeMaterial();
  const k = mix(float(1), probe.sample(uv()).r.mul(2), hasProbe);
  m.fragmentNode = vec4(src.sample(uv()).rgb.mul(vec3(1, k, 0.5)), 1);
  const quad = new THREE.QuadMesh(m);
  output.addPass({
    name: 'passcheck',
    stage: 'scene',
    render(ctx: FrameContext) {
      if (!rt || rt.width !== ctx.width || rt.height !== ctx.height) {
        rt?.dispose();
        rt = new THREE.RenderTarget(ctx.width, ctx.height, { type: THREE.HalfFloatType, depthBuffer: false });
      }
      src.value = ctx.color;
      const p = ctx.mrt.probe;
      hasProbe.value = p ? 1 : 0;
      probe.value = p ?? placeholder;
      ctx.renderer.setRenderTarget(rt);
      quad.render(ctx.renderer);
      return rt.texture;
    },
    dispose() {
      rt?.dispose();
    },
  });
}
