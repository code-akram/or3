// Types for three r186 addon modules that @types/three 0.186 does not ship (T16).
declare module 'three/addons/tsl/utils/TAAUtils.js' {
  /* eslint-disable @typescript-eslint/no-explicit-any */
  export const clipAABB: any;
  export const flickerReduction: any;
  export const sampleCurrentDepth: any;
  export const samplePreviousDepth: any;
  export function computeHaltonOffsets(length: number): [number, number][];
}
