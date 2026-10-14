// Pre-integrated skin scattering (Penner and Borshukov, GPU Pro 2, 2011): the diffuse falloff of a
// sphere of radius r lit at angle theta, integrated against a diffusion profile, as a 2D LUT over
// (N.L, curvature). Curvature comes from the build (skin_<part>_curvature.png, blender/character/
// skin_tex.curvature): v = clamp(k / KMAX, 0, 1) with k = 1/r in 1/m, so v = 1 is a 1 cm radius.
//
// Profile, per channel c: two normalised 2D Gaussians, sigma = 0.5 r_c and 1.5 r_c, equal weight, with
// r_c the hero skin's Cycles subsurface radii (skin_tex.HERO: radius (1.0, 0.22, 0.10) x scale
// 3.4 mm = 3.4 / 0.75 / 0.34 mm), the near / far pair standing in for Burley's d and 3d exponentials.
// The ring integral follows Penner: D(theta, r) = int cos+(theta + x) R(2 r sin(x/2)) dx / int R dx.
import * as THREE from 'three/webgpu';

export const CURV_KMAX = 100; // 1/m, skin_tex.CURV_KMAX
export const HERO_RADII_MM: [number, number, number] = [3.4, 0.748, 0.34];

function profile(d: number, r: number): number {
  const g = (s: number) => Math.exp(-(d * d) / (2 * s * s)) / (2 * Math.PI * s * s);
  return 0.5 * g(0.5 * r) + 0.5 * g(1.5 * r);
}

/** One LUT value: N.L = cos(theta), curvature radius rad (m), profile radius rc (m). */
function integrate(cosT: number, rad: number, rc: number, steps = 256): number {
  const theta = Math.acos(Math.max(-1, Math.min(1, cosT)));
  let num = 0;
  let den = 0;
  // the profile is negligible past ~6 sigma of its wide lobe: integrate only there (resolves small radii)
  const xMax = Math.min(Math.PI, (9 * rc) / rad);
  for (let i = 0; i < steps; i++) {
    const x = -xMax + ((i + 0.5) / steps) * 2 * xMax;
    const w = profile(Math.abs(2 * rad * Math.sin(x / 2)), rc);
    num += Math.max(0, Math.cos(theta + x)) * w;
    den += w;
  }
  return den > 0 ? num / den : Math.max(0, cosT);
}

/** size x size LUT: u = N.L * 0.5 + 0.5, v = encoded curvature; RGB = per-channel D (cosine included). */
export function skinLUT(radiiMM: number[] = HERO_RADII_MM, scale = 1, size = 128): THREE.DataTexture {
  const data = new Uint16Array(size * size * 4);
  for (let j = 0; j < size; j++) {
    const v = (j + 0.5) / size;
    const rad = 1 / (v * CURV_KMAX);
    for (let i = 0; i < size; i++) {
      const nl = ((i + 0.5) / size) * 2 - 1;
      const o = (j * size + i) * 4;
      for (let c = 0; c < 3; c++) data[o + c] = THREE.DataUtils.toHalfFloat(integrate(nl, rad, (radiiMM[c]! * scale) / 1000));
      data[o + 3] = THREE.DataUtils.toHalfFloat(1);
    }
  }
  const t = new THREE.DataTexture(data, size, size, THREE.RGBAFormat, THREE.HalfFloatType);
  t.minFilter = THREE.LinearFilter;
  t.magFilter = THREE.LinearFilter;
  t.wrapS = t.wrapT = THREE.ClampToEdgeWrapping;
  t.colorSpace = THREE.NoColorSpace;
  t.generateMipmaps = false;
  t.needsUpdate = true;
  return t;
}
