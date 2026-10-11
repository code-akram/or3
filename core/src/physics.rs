//! Small Rapier scene: a walled arena with pillars and one yaw-only capsule per instance that
//! wanders under random impulses. It exists to measure the real WASM size and step cost.

use rapier3d::prelude::*;

use crate::pose::{INSTANCES, Root};

pub const HALF_EXTENT: f32 = 20.0;
const CAPSULE_HALF_HEIGHT: f32 = 0.6;
const CAPSULE_RADIUS: f32 = 0.3;
/// Pelvis height above the capsule centre's floor contact.
const PELVIS_Y: f32 = 0.9;

pub struct Arena {
    world: PhysicsWorld,
    agents: Vec<RigidBodyHandle>,
    phases: Vec<f32>,
    rng: u32,
}

fn xorshift(s: &mut u32) -> f32 {
    *s ^= *s << 13;
    *s ^= *s >> 17;
    *s ^= *s << 5;
    (*s >> 8) as f32 / (1u32 << 24) as f32
}

pub const PILLARS: usize = 24;
pub const PILLAR_HALF: f32 = 0.6;
pub const ARENA_SEED: u32 = 0x5eed_1234;

/// Static pillar centres (x, z). Consumes `rng` exactly as `Arena::new` does.
pub fn pillars(rng: &mut u32) -> Vec<[f32; 2]> {
    (0..PILLARS)
        .map(|_| {
            let x = (xorshift(rng) - 0.5) * 2.0 * (HALF_EXTENT - 3.0);
            let z = (xorshift(rng) - 0.5) * 2.0 * (HALF_EXTENT - 3.0);
            [x, z]
        })
        .collect()
}

/// Agent start positions on a grid (also used by the pose micro benchmark).
pub fn grid_roots() -> Vec<Root> {
    (0..INSTANCES)
        .map(|i| {
            let (gx, gz) = ((i % 20) as f32, (i / 20) as f32);
            Root { pos: [gx * 1.8 - 17.0, PELVIS_Y, gz * 3.0 - 14.0], yaw: 0.0, speed: 1.0, phase: i as f32 * 0.7 }
        })
        .collect()
}

impl Arena {
    pub fn new(count: usize, seed: u32) -> Self {
        let mut world = PhysicsWorld::new();
        world.integration_parameters.dt = (1.0 / crate::TICK_HZ) as f32;

        let ground = world.insert_body(RigidBodyBuilder::fixed());
        world.insert_collider(ColliderBuilder::cuboid(HALF_EXTENT, 0.1, HALF_EXTENT).translation(Vector::new(0.0, -0.1, 0.0)), Some(ground));
        for (x, z, hx, hz) in [
            (HALF_EXTENT, 0.0, 0.2, HALF_EXTENT),
            (-HALF_EXTENT, 0.0, 0.2, HALF_EXTENT),
            (0.0, HALF_EXTENT, HALF_EXTENT, 0.2),
            (0.0, -HALF_EXTENT, HALF_EXTENT, 0.2),
        ] {
            world.insert_collider(ColliderBuilder::cuboid(hx, 1.5, hz).translation(Vector::new(x, 1.5, z)), Some(ground));
        }
        let mut rng = seed | 1;
        for [x, z] in pillars(&mut rng) {
            world.insert_collider(ColliderBuilder::cuboid(PILLAR_HALF, 2.0, PILLAR_HALF).translation(Vector::new(x, 2.0, z)), Some(ground));
        }

        let roots = grid_roots();
        let mut agents = Vec::with_capacity(count);
        let mut phases = Vec::with_capacity(count);
        for r in roots.iter().take(count) {
            let body = RigidBodyBuilder::dynamic()
                .translation(Vector::new(r.pos[0], CAPSULE_HALF_HEIGHT + CAPSULE_RADIUS, r.pos[2]))
                .enabled_rotations(false, true, false)
                .linear_damping(0.4)
                .angular_damping(2.0)
                .linvel(Vector::new(xorshift(&mut rng) * 4.0 - 2.0, 0.0, xorshift(&mut rng) * 4.0 - 2.0));
            let (h, _) = world.insert(body, ColliderBuilder::capsule_y(CAPSULE_HALF_HEIGHT, CAPSULE_RADIUS).friction(0.2));
            agents.push(h);
            phases.push(r.phase);
        }
        Arena { world, agents, phases, rng }
    }

    /// One fixed step: random wander impulses, then the Rapier step.
    pub fn step(&mut self, _tick: u64) {
        for &h in &self.agents {
            if xorshift(&mut self.rng) < 1.0 / 90.0 {
                let ix = (xorshift(&mut self.rng) - 0.5) * 6.0;
                let iz = (xorshift(&mut self.rng) - 0.5) * 6.0;
                let jump = if xorshift(&mut self.rng) < 0.1 { 3.0 } else { 0.0 };
                if let Some(b) = self.world.bodies.get_mut(h) {
                    b.apply_impulse(Vector::new(ix, jump, iz), true);
                }
            }
        }
        self.world.step();
    }

    pub fn roots(&self, out: &mut [Root]) {
        for (i, (&h, r)) in self.agents.iter().zip(out.iter_mut()).enumerate() {
            let b = &self.world.bodies[h];
            let p = b.translation();
            let v = b.linvel();
            let speed = (v.x * v.x + v.z * v.z).sqrt();
            // Face the direction of travel when moving; otherwise keep the previous yaw.
            if speed > 0.2 {
                r.yaw = v.x.atan2(v.z);
            }
            r.pos = [p.x, p.y - (CAPSULE_HALF_HEIGHT + CAPSULE_RADIUS) + PELVIS_Y, p.z];
            r.speed = speed;
            r.phase = self.phases[i];
        }
    }

    pub fn awake(&self) -> usize {
        self.agents.iter().filter(|&&h| !self.world.bodies[h].is_sleeping()).count()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn arena_steps() {
        let mut a = Arena::new(INSTANCES, 7);
        for t in 0..120 {
            a.step(t);
        }
        let mut roots = vec![Root::default(); INSTANCES];
        a.roots(&mut roots);
        assert!(roots.iter().all(|r| r.pos.iter().all(|v| v.is_finite()) && r.pos[1] > 0.0));
    }
}
