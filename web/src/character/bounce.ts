// Set bounce (T16, bench/m1/v4/checkpoint-3.md §2.5): the alley set's radiance around the head, rendered
// once in Cycles without the character (blender/hero/refs.py bounce: six 32^2 cube faces resampled to a
// 128x64 equirect in three's world frame), as the hero rig's environment. It is the dim fill a set
// gives a subject (the walls lit by the rig and the practicals), so the engine beauty is not lit from a
// black box; three pre-filters it (PMREM) for the materials' indirect diffuse and specular.
//
// It belongs to the beauty frame only: the parity renders are on the void set (stage.py --parity), so
// main.ts turns the environment off (environmentIntensity 0) and keeps the world hemisphere there.
import * as THREE from 'three/webgpu';

export interface BounceJson {
  version: number;
  width: number;
  height: number;
  row0: 'bottom' | 'top';
  data: string;
  irradiance?: Record<string, number>;
}

/** The equirect DataTexture (half float, scene-linear) of a set_bounce.json. */
export function bounceTexture(j: BounceJson): THREE.DataTexture {
  const bin = atob(j.data);
  const u8 = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
  const rgb = new Float32Array(u8.buffer);
  const { width: w, height: h } = j;
  const half = new Uint16Array(w * h * 4);
  for (let y = 0; y < h; y++) {
    // three's equirect: v = 0 at the nadir; a DataTexture's first row is v = 0
    const sy = j.row0 === 'bottom' ? y : h - 1 - y;
    for (let x = 0; x < w; x++) {
      const s = (sy * w + x) * 3;
      const d = (y * w + x) * 4;
      half[d] = THREE.DataUtils.toHalfFloat(rgb[s]!);
      half[d + 1] = THREE.DataUtils.toHalfFloat(rgb[s + 1]!);
      half[d + 2] = THREE.DataUtils.toHalfFloat(rgb[s + 2]!);
      half[d + 3] = THREE.DataUtils.toHalfFloat(1);
    }
  }
  const t = new THREE.DataTexture(half, w, h, THREE.RGBAFormat, THREE.HalfFloatType);
  t.mapping = THREE.EquirectangularReflectionMapping;
  t.colorSpace = THREE.LinearSRGBColorSpace;
  t.minFilter = t.magFilter = THREE.LinearFilter;
  t.wrapS = THREE.RepeatWrapping;
  t.needsUpdate = true;
  return t;
}
