// Stylisation hook (C2, open user decision). Every lighting model sends its diffuse light term
// through `diffuseRamp`, so a painterly pass (3-band ramp with a soft terminator) switches on with
// params.style.banded = 1 without touching the BRDFs. Painted albedo plugs in at `albedo` and ink
// lines will be a post pass on the output (output.ts), so neither needs the materials rewritten.
import * as TSL from 'three/tsl';
import type { ParamStore } from './params';
// TSL's TypeScript types are too narrow for shader-graph code; the graph is checked at build.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const { float, floor, fract, mix, smoothstep, vec3 } = TSL as any;

/* eslint-disable @typescript-eslint/no-explicit-any */
type N = any;

/** x in [0, 1] (a wrapped / clamped N.L term, scalar or vec3) -> realistic or banded. */
export function diffuseRamp(P: ParamStore, x: N): N {
  const bands = P.u('style.bands');
  const soft = P.u('style.softness');
  const t = x.mul(bands);
  const step = floor(t).add(smoothstep(float(0.5).sub(soft.mul(bands)), float(0.5).add(soft.mul(bands)), fract(t)));
  const banded = step.div(bands).clamp(0, 1);
  return mix(x, banded, P.u('style.banded'));
}

/** Albedo hook: gain and saturation now; a painted-albedo texture swap later. */
export function albedo(P: ParamStore, prefix: string, rgb: N): N {
  const gain = P.u(`${prefix}.albedoGain`);
  let c = rgb.mul(gain);
  if (prefix === 'skin') {
    const lum = c.dot(vec3(0.2126, 0.7152, 0.0722));
    c = mix(vec3(lum), c, P.u('skin.saturation'));
  }
  return c;
}
