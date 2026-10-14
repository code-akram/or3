// The hero grade as data (T16, bench/m1/v4/checkpoint-3.md §2.6): Blender's own grade baked into two
// 33^3 3D LUTs and a vignette gain map by `blender/hero/grade.py --lut` (grade_lut.json, next to the GLB):
//
//   grade  the compositor's colour grade (white point 3,900 K -> ASC-CDL -> black lift -> Hue/Sat), on
//          scene-linear values through a log2 shaper; the table holds log2 of the graded linear value
//   view   view exposure 0 + AgX + "AgX - Base Contrast" + sRGB display, on the exposed scene-linear value
//          through a log2 shaper; the table holds display values (already encoded)
//   vignette  the compositor's vignette gain (ellipse 0.95 -> Gaussian w/3 -> 2^ev..1), 96x54, for 16:9
//
// Output.render applies them in Blender's order: bloom / halation -> grade LUT -> vignette -> grain ->
// exposure -> view LUT. The analytic TSL grade and three's AgX approximation stay as the fallback
// (?lut=0 or no sidecar). Lookups go through three's Lut3DNode (trilinear on a half-float 3D texture).
import * as THREE from 'three/webgpu';
import * as TSL from 'three/tsl';
import { lut3D } from 'three/addons/tsl/display/Lut3DNode.js';
// TSL's TypeScript types are too narrow for shader-graph code; the graph is checked at build.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const T = TSL as any;
const { exp2, float, log2, max, mix, texture, texture3D, uniform, vec3, vec4 } = T;

/* eslint-disable @typescript-eslint/no-explicit-any */
type N = any;

interface LutBlock {
  min: number;
  max: number;
  out: string;
  data: string;
}
export interface GradeLutJson {
  version: number;
  size: number;
  look?: string;
  grade: LutBlock;
  view: LutBlock;
  vignette?: { w: number; h: number; ev: number; data: string };
}

function f32(b64: string): Float32Array {
  const bin = atob(b64);
  const u8 = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
  return new Float32Array(u8.buffer);
}

function lut3DTexture(size: number, rgb: Float32Array | null): THREE.Data3DTexture {
  const n = size * size * size;
  const half = new Uint16Array(n * 4);
  for (let i = 0; i < n; i++) {
    for (let c = 0; c < 3; c++) half[i * 4 + c] = THREE.DataUtils.toHalfFloat(rgb ? rgb[i * 3 + c]! : 0);
    half[i * 4 + 3] = THREE.DataUtils.toHalfFloat(1);
  }
  const t = new THREE.Data3DTexture(half, size, size, size);
  t.format = THREE.RGBAFormat;
  t.type = THREE.HalfFloatType;
  t.minFilter = t.magFilter = THREE.LinearFilter;
  t.wrapS = t.wrapT = t.wrapR = THREE.ClampToEdgeWrapping;
  t.unpackAlignment = 1;
  t.generateMipmaps = false;
  t.needsUpdate = true;
  return t;
}

/** The LUT stage of the output pass: uniforms + nodes; `load` swaps in a sidecar's tables. */
export class GradeLUT {
  readonly on = uniform(0);
  readonly hasVignette = uniform(0);
  private readonly gMin = uniform(-16);
  private readonly gMax = uniform(6);
  private readonly vMin = uniform(-13);
  private readonly vMax = uniform(5);
  /** the Lut3DNodes made by grade() / view(); their `size` uniforms follow load() */
  private readonly lutNodes: N[] = [];
  private lutSize = 2;
  private readonly gTex: N;
  private readonly vTex: N;
  private readonly vigTex: N;
  info: { size: number; look?: string | undefined; grade: number[]; view: number[] } | null = null;

  constructor() {
    this.gTex = texture3D(lut3DTexture(2, null));
    this.vTex = texture3D(lut3DTexture(2, null));
    const vt = new THREE.DataTexture(new Uint16Array(4).fill(THREE.DataUtils.toHalfFloat(1)), 1, 1, THREE.RGBAFormat, THREE.HalfFloatType);
    vt.needsUpdate = true;
    this.vigTex = texture(vt);
  }

  load(j: GradeLutJson): void {
    const s = j.size;
    this.gTex.value = lut3DTexture(s, f32(j.grade.data));
    this.vTex.value = lut3DTexture(s, f32(j.view.data));
    this.lutSize = s;
    for (const n of this.lutNodes) n.size.value = s;
    this.gMin.value = j.grade.min;
    this.gMax.value = j.grade.max;
    this.vMin.value = j.view.min;
    this.vMax.value = j.view.max;
    if (j.vignette) {
      const g = f32(j.vignette.data);
      const half = new Uint16Array(j.vignette.w * j.vignette.h * 4);
      for (let i = 0; i < g.length; i++) {
        const h = THREE.DataUtils.toHalfFloat(g[i]!);
        half.set([h, h, h, THREE.DataUtils.toHalfFloat(1)], i * 4);
      }
      const vt = new THREE.DataTexture(half, j.vignette.w, j.vignette.h, THREE.RGBAFormat, THREE.HalfFloatType);
      vt.minFilter = vt.magFilter = THREE.LinearFilter;
      vt.needsUpdate = true;
      this.vigTex.value = vt;
      this.hasVignette.value = 1;
    }
    this.on.value = 1;
    this.info = { size: s, look: j.look, grade: [j.grade.min, j.grade.max], view: [j.view.min, j.view.max] };
  }

  private static shaper(c: N, lo: N, hi: N): N {
    return log2(max(c, exp2(lo))).sub(lo).div(hi.sub(lo)).clamp(0, 1);
  }

  /** scene-linear -> graded scene-linear (Blender compositor grade, no vignette) */
  grade(c: N): N {
    const n: N = lut3D(vec4(GradeLUT.shaper(c, this.gMin, this.gMax), 1), this.gTex, this.lutSize, float(1));
    this.lutNodes.push(n);
    return exp2(n.rgb);
  }

  /** exposed scene-linear -> display (AgX + look + sRGB) */
  view(c: N): N {
    const n: N = lut3D(vec4(GradeLUT.shaper(c, this.vMin, this.vMax), 1), this.vTex, this.lutSize, float(1));
    this.lutNodes.push(n);
    return n.rgb;
  }

  /** Blender's vignette gain at screen uv (16:9 map; `analytic` where the sidecar has none) */
  vignette(u: N, analytic: N): N {
    return mix(analytic, vec3(this.vigTex.sample(u).r), this.hasVignette);
  }
}
