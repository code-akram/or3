//! Procedural forward kinematics standing in for motion matching: a 64-bone tree per instance
//! (spine, two arms, two legs), animated with per-bone sines, composed parent-to-child.
//!
//! Output is one column-major 4x4 matrix per bone, pre-multiplied by a display scale so the
//! renderer can draw each bone as a unit box with the matrix as its instance transform.

pub const INSTANCES: usize = 200;
pub const BONES: usize = 64;

#[derive(Clone, Copy, Default)]
pub struct Root {
    pub pos: [f32; 3],
    pub yaw: f32,
    /// Horizontal speed, drives the gait.
    pub speed: f32,
    pub phase: f32,
}

pub struct Rig {
    parent: [u8; BONES],
    /// Translation of each bone in its parent's frame (along the parent's +Y).
    offset: [f32; BONES],
    /// Segment length (display only).
    len: [f32; BONES],
    width: [f32; BONES],
    /// Rest rotation about Z (radians), applied before the animated sway.
    rest_z: [f32; BONES],
    amp: [f32; BONES],
    freq: [f32; BONES],
    /// Animated axis: 0 = X, 1 = Z.
    axis: [u8; BONES],
    world: Vec<Mat>,
}

/// Bone layout: 0..16 spine (pelvis up), 16..28 left arm, 28..40 right arm,
/// 40..52 left leg, 52..64 right leg.
const SPINE: (usize, usize) = (0, 16);
const ARM_L: (usize, usize) = (16, 28);
const ARM_R: (usize, usize) = (28, 40);
const LEG_L: (usize, usize) = (40, 52);
const LEG_R: (usize, usize) = (52, 64);
const SHOULDER: usize = 13;

impl Rig {
    pub fn new() -> Self {
        let mut r = Rig {
            parent: [0; BONES],
            offset: [0.0; BONES],
            len: [0.0; BONES],
            width: [0.0; BONES],
            rest_z: [0.0; BONES],
            amp: [0.0; BONES],
            freq: [0.0; BONES],
            axis: [0; BONES],
            world: vec![Mat::IDENTITY; BONES],
        };
        let mut chain = |(a, b): (usize, usize), from: usize, len: f32, w: f32, rest: f32, amp: f32, axis: u8| {
            for i in a..b {
                let first = i == a;
                r.parent[i] = if first { from as u8 } else { (i - 1) as u8 };
                r.offset[i] = if first { if from == 0 && a != 0 { 0.0 } else { r.len[from] } } else { len };
                r.len[i] = len;
                r.width[i] = w;
                r.rest_z[i] = if first { rest } else { 0.0 };
                r.amp[i] = amp;
                r.freq[i] = 1.0 + 0.05 * (i - a) as f32;
                r.axis[i] = axis;
            }
        };
        chain(SPINE, 0, 0.045, 0.16, 0.0, 0.03, 1);
        chain(ARM_L, SHOULDER, 0.055, 0.06, 1.75, 0.05, 0);
        chain(ARM_R, SHOULDER, 0.055, 0.06, -1.75, 0.05, 0);
        chain(LEG_L, 0, 0.075, 0.08, std::f32::consts::PI - 0.12, 0.05, 0);
        chain(LEG_R, 0, 0.075, 0.08, std::f32::consts::PI + 0.12, 0.05, 0);
        r.parent[0] = 0;
        r.offset[0] = 0.0;
        r
    }

    /// Writes `INSTANCES * BONES` matrices into `out`.
    pub fn write(&mut self, roots: &[Root], t: f32, out: &mut [f32]) {
        debug_assert_eq!(out.len(), INSTANCES * BONES * 16);
        for (inst, root) in roots.iter().enumerate().take(INSTANCES) {
            let gait = root.phase + t * (2.0 + 4.0 * root.speed.min(3.0));
            let stride = 0.4 + 0.25 * root.speed.min(3.0);
            let root_m = Mat::from_yaw_translation(root.yaw, root.pos);
            for b in 0..BONES {
                let mut angle = self.amp[b] * (gait * self.freq[b] + b as f32 * 0.35).sin();
                if b == LEG_L.0 || b == ARM_R.0 {
                    angle += stride * gait.sin();
                } else if b == LEG_R.0 || b == ARM_L.0 {
                    angle -= stride * gait.sin();
                }
                let local = Mat::local(self.rest_z[b], angle, self.axis[b], self.offset[b]);
                let w = if b == 0 { root_m.mul(&local) } else { self.world[self.parent[b] as usize].mul(&local) };
                self.world[b] = w;
                let base = (inst * BONES + b) * 16;
                w.scaled(self.width[b], self.len[b], self.width[b]).store(&mut out[base..base + 16]);
            }
        }
    }
}

impl Default for Rig {
    fn default() -> Self {
        Self::new()
    }
}

// ---------------------------------------------------------------------------------------------
// 4x4 column-major matrix, SIMD (wasm simd128) with a scalar fallback for native builds/tests.
// ---------------------------------------------------------------------------------------------

#[cfg(all(target_arch = "wasm32", target_feature = "simd128"))]
mod simd {
    use core::arch::wasm32::*;

    #[derive(Clone, Copy)]
    pub struct Mat(pub [v128; 4]);

    impl Mat {
        pub const IDENTITY: Mat = Mat([
            f32x4(1.0, 0.0, 0.0, 0.0),
            f32x4(0.0, 1.0, 0.0, 0.0),
            f32x4(0.0, 0.0, 1.0, 0.0),
            f32x4(0.0, 0.0, 0.0, 1.0),
        ]);

        pub fn from_cols(c: [[f32; 4]; 4]) -> Mat {
            Mat(c.map(|c| f32x4(c[0], c[1], c[2], c[3])))
        }

        #[inline(always)]
        pub fn mul(&self, b: &Mat) -> Mat {
            let a = &self.0;
            let col = |v: v128| {
                let x = i32x4_shuffle::<0, 0, 0, 0>(v, v);
                let y = i32x4_shuffle::<1, 1, 1, 1>(v, v);
                let z = i32x4_shuffle::<2, 2, 2, 2>(v, v);
                let w = i32x4_shuffle::<3, 3, 3, 3>(v, v);
                f32x4_add(
                    f32x4_add(f32x4_mul(a[0], x), f32x4_mul(a[1], y)),
                    f32x4_add(f32x4_mul(a[2], z), f32x4_mul(a[3], w)),
                )
            };
            Mat([col(b.0[0]), col(b.0[1]), col(b.0[2]), col(b.0[3])])
        }

        #[inline(always)]
        pub fn scaled(&self, sx: f32, sy: f32, sz: f32) -> Mat {
            Mat([
                f32x4_mul(self.0[0], f32x4_splat(sx)),
                f32x4_mul(self.0[1], f32x4_splat(sy)),
                f32x4_mul(self.0[2], f32x4_splat(sz)),
                self.0[3],
            ])
        }

        #[inline(always)]
        pub fn store(&self, out: &mut [f32]) {
            assert!(out.len() >= 16);
            let p = out.as_mut_ptr() as *mut v128;
            // SAFETY: bounds checked above; v128 stores are unaligned-safe on wasm.
            unsafe {
                v128_store(p, self.0[0]);
                v128_store(p.add(1), self.0[1]);
                v128_store(p.add(2), self.0[2]);
                v128_store(p.add(3), self.0[3]);
            }
        }
    }
}

#[cfg(not(all(target_arch = "wasm32", target_feature = "simd128")))]
mod simd {
    #[derive(Clone, Copy)]
    pub struct Mat(pub [[f32; 4]; 4]);

    impl Mat {
        pub const IDENTITY: Mat =
            Mat([[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]);

        pub fn from_cols(c: [[f32; 4]; 4]) -> Mat {
            Mat(c)
        }

        pub fn mul(&self, b: &Mat) -> Mat {
            let mut r = [[0.0; 4]; 4];
            for (j, rc) in r.iter_mut().enumerate() {
                for (i, v) in rc.iter_mut().enumerate() {
                    *v = (0..4).map(|k| self.0[k][i] * b.0[j][k]).sum();
                }
            }
            Mat(r)
        }

        pub fn scaled(&self, sx: f32, sy: f32, sz: f32) -> Mat {
            let mut m = *self;
            m.0[0].iter_mut().for_each(|v| *v *= sx);
            m.0[1].iter_mut().for_each(|v| *v *= sy);
            m.0[2].iter_mut().for_each(|v| *v *= sz);
            m
        }

        pub fn store(&self, out: &mut [f32]) {
            for c in 0..4 {
                out[c * 4..c * 4 + 4].copy_from_slice(&self.0[c]);
            }
        }
    }
}

pub use simd::Mat;

impl Mat {
    pub fn from_yaw_translation(yaw: f32, p: [f32; 3]) -> Mat {
        let (s, c) = yaw.sin_cos();
        Mat::from_cols([[c, 0.0, -s, 0.0], [0.0, 1.0, 0.0, 0.0], [s, 0.0, c, 0.0], [p[0], p[1], p[2], 1.0]])
    }

    /// `T(0, offset, 0) * Rz(rest_z) * R_axis(angle)`.
    pub fn local(rest_z: f32, angle: f32, axis: u8, offset: f32) -> Mat {
        let (sz, cz) = rest_z.sin_cos();
        let (sa, ca) = angle.sin_cos();
        // Rz * Rx or Rz * Rz, written out to avoid a second multiply.
        let cols = if axis == 0 {
            // Rz * Rx: columns of Rz times Rx.
            [
                [cz, sz, 0.0, 0.0],
                [-sz * ca, cz * ca, sa, 0.0],
                [sz * sa, -cz * sa, ca, 0.0],
                [0.0, offset, 0.0, 1.0],
            ]
        } else {
            let (s, c) = (rest_z + angle).sin_cos();
            [[c, s, 0.0, 0.0], [-s, c, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, offset, 0.0, 1.0]]
        };
        Mat::from_cols(cols)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn writes_finite_matrices() {
        let mut rig = Rig::new();
        let roots = vec![Root { pos: [1.0, 0.9, 2.0], yaw: 0.3, speed: 1.0, phase: 0.0 }; INSTANCES];
        let mut out = vec![0.0f32; INSTANCES * BONES * 16];
        rig.write(&roots, 0.5, &mut out);
        assert!(out.iter().all(|v| v.is_finite()));
        // Bone 0 translation equals the root position.
        assert_eq!(&out[12..15], &[1.0, 0.9, 2.0]);
    }
}
