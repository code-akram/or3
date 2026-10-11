//! Chunk geometry for acoustics: load the chunk GLB (local Y-up metres), a uniform 2D
//! grid ray caster, and an automatic "narrow alley" finder.

use anyhow::{Context, Result};
use plateau_chunk::glb::Glb;
use serde_json::Value;
use std::collections::HashSet;
use std::path::Path;

pub type V3 = [f64; 3];

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Layer {
    Building,
    Road,
}

pub struct Tri {
    pub v: [V3; 3],
    pub layer: Layer,
    pub feature: u32,
    pub normal: V3,
}

pub struct Scene {
    pub tris: Vec<Tri>,
    /// per-building attribute rows from the chunk's mesh extras
    pub buildings: Vec<Value>,
    pub scene_extras: Value,
}

fn sub(a: V3, b: V3) -> V3 {
    [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
}
fn cross(a: V3, b: V3) -> V3 {
    [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]
}
fn dot(a: V3, b: V3) -> f64 {
    a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
}
fn norm(a: V3) -> V3 {
    let l = dot(a, a).sqrt().max(1e-12);
    [a[0] / l, a[1] / l, a[2] / l]
}

pub fn load(path: &Path) -> Result<Scene> {
    let g = Glb::read(path)?;
    let mut tris = vec![];
    let mut buildings = vec![];
    let meshes = g.json["meshes"].as_array().context("meshes")?.clone();
    for m in &meshes {
        let name = m["name"].as_str().unwrap_or("");
        let layer = match name {
            "bldg" => Layer::Building,
            "tran" => Layer::Road,
            _ => continue, // furniture/vegetation ignored acoustically
        };
        if layer == Layer::Building {
            buildings = m["extras"]["features"]
                .as_array()
                .cloned()
                .unwrap_or_default();
        }
        for p in m["primitives"].as_array().context("primitives")? {
            let (pos, _) =
                g.accessor_f32(p["attributes"]["POSITION"].as_u64().context("POSITION")?)?;
            let (fid, _) =
                g.accessor_f32(p["attributes"]["_FEATURE_ID_0"].as_u64().context("fid")?)?;
            let idx = g.accessor_indices(p["indices"].as_u64().context("indices")?)?;
            for t in idx.chunks_exact(3) {
                let v = [0, 1, 2].map(|k| {
                    let i = t[k] as usize * 3;
                    [pos[i] as f64, pos[i + 1] as f64, pos[i + 2] as f64]
                });
                let n = cross(sub(v[1], v[0]), sub(v[2], v[0]));
                if dot(n, n) < 1e-10 {
                    continue; // degenerate
                }
                tris.push(Tri {
                    v,
                    layer,
                    feature: fid[t[0] as usize] as u32,
                    normal: norm(n),
                });
            }
        }
    }
    Ok(Scene {
        tris,
        buildings,
        scene_extras: g.json["scenes"][0]["extras"].clone(),
    })
}

/// Uniform grid over x/z holding triangle indices, for ray casting.
pub struct Grid {
    cell: f64,
    min: [f64; 2],
    nx: usize,
    nz: usize,
    cells: Vec<Vec<u32>>,
}

impl Grid {
    pub fn build(scene: &Scene, cell: f64) -> Self {
        let mut min = [f64::MAX; 2];
        let mut max = [f64::MIN; 2];
        for t in &scene.tris {
            for v in &t.v {
                min[0] = min[0].min(v[0]);
                min[1] = min[1].min(v[2]);
                max[0] = max[0].max(v[0]);
                max[1] = max[1].max(v[2]);
            }
        }
        let nx = ((max[0] - min[0]) / cell).ceil() as usize + 1;
        let nz = ((max[1] - min[1]) / cell).ceil() as usize + 1;
        let mut cells = vec![vec![]; nx * nz];
        for (i, t) in scene.tris.iter().enumerate() {
            let (mut x0, mut z0, mut x1, mut z1) = (f64::MAX, f64::MAX, f64::MIN, f64::MIN);
            for v in &t.v {
                x0 = x0.min(v[0]);
                x1 = x1.max(v[0]);
                z0 = z0.min(v[2]);
                z1 = z1.max(v[2]);
            }
            let cx0 = ((x0 - min[0]) / cell) as usize;
            let cx1 = ((x1 - min[0]) / cell) as usize;
            let cz0 = ((z0 - min[1]) / cell) as usize;
            let cz1 = ((z1 - min[1]) / cell) as usize;
            for cz in cz0..=cz1.min(nz - 1) {
                for cx in cx0..=cx1.min(nx - 1) {
                    cells[cz * nx + cx].push(i as u32);
                }
            }
        }
        Grid {
            cell,
            min,
            nx,
            nz,
            cells,
        }
    }

    /// Closest hit along a ray: (distance, triangle index). Möller–Trumbore, 2D DDA.
    pub fn cast(&self, scene: &Scene, o: V3, d: V3, max_t: f64) -> Option<(f64, usize)> {
        let mut best: Option<(f64, usize)> = None;
        let mut seen: HashSet<u32> = HashSet::new();
        // DDA over x/z
        let fx = (o[0] - self.min[0]) / self.cell;
        let fz = (o[2] - self.min[1]) / self.cell;
        let (mut cx, mut cz) = (fx.floor() as i64, fz.floor() as i64);
        let step_x = if d[0] > 0.0 { 1 } else { -1 };
        let step_z = if d[2] > 0.0 { 1 } else { -1 };
        let inv = |v: f64| {
            if v.abs() < 1e-12 {
                f64::INFINITY
            } else {
                1.0 / v.abs()
            }
        };
        let tdx = self.cell * inv(d[0]);
        let tdz = self.cell * inv(d[2]);
        let mut tmx = (if d[0] > 0.0 {
            cx as f64 + 1.0 - fx
        } else {
            fx - cx as f64
        }) * tdx;
        let mut tmz = (if d[2] > 0.0 {
            cz as f64 + 1.0 - fz
        } else {
            fz - cz as f64
        }) * tdz;
        if !tmx.is_finite() {
            tmx = f64::INFINITY;
        }
        if !tmz.is_finite() {
            tmz = f64::INFINITY;
        }
        let mut t_cell = 0.0;
        loop {
            if cx >= 0 && cz >= 0 && (cx as usize) < self.nx && (cz as usize) < self.nz {
                for &ti in &self.cells[cz as usize * self.nx + cx as usize] {
                    if !seen.insert(ti) {
                        continue;
                    }
                    if let Some(t) = intersect(&scene.tris[ti as usize].v, o, d) {
                        if t > 1e-4 && t < max_t && best.is_none_or(|b| t < b.0) {
                            best = Some((t, ti as usize));
                        }
                    }
                }
            }
            if let Some(b) = best {
                if b.0 <= t_cell {
                    break;
                }
            }
            if tmx < tmz {
                t_cell = tmx;
                tmx += tdx;
                cx += step_x;
            } else {
                t_cell = tmz;
                tmz += tdz;
                cz += step_z;
            }
            if t_cell > max_t || !t_cell.is_finite() {
                break;
            }
            if best.is_some_and(|b| b.0 <= t_cell) {
                break;
            }
        }
        best
    }
}

fn intersect(v: &[V3; 3], o: V3, d: V3) -> Option<f64> {
    let e1 = sub(v[1], v[0]);
    let e2 = sub(v[2], v[0]);
    let p = cross(d, e2);
    let det = dot(e1, p);
    if det.abs() < 1e-12 {
        return None;
    }
    let inv = 1.0 / det;
    let s = sub(o, v[0]);
    let u = dot(s, p) * inv;
    if !(0.0..=1.0).contains(&u) {
        return None;
    }
    let q = cross(s, e1);
    let w = dot(d, q) * inv;
    if w < 0.0 || u + w > 1.0 {
        return None;
    }
    Some(dot(e2, q) * inv)
}

#[derive(Debug, Clone)]
pub struct Alley {
    pub center: V3, // at ground level
    pub axis: V3,   // unit, horizontal, along the alley
    pub width: f64,
    pub length: f64,
    pub ground: f64,
}

/// Ground height at (x, z): the road surface if a downward ray hits one first, else the
/// lowest building base within `r` metres. None if the point is under a building.
pub fn ground_at(scene: &Scene, grid: &Grid, base: &[f64], x: f64, z: f64) -> Option<f64> {
    match grid.cast(scene, [x, 400.0, z], [0.0, -1.0, 0.0], 800.0) {
        Some((t, ti)) => {
            let tri = &scene.tris[ti];
            match tri.layer {
                Layer::Building => None,
                _ => Some(400.0 - t),
            }
        }
        None => {
            // no road polygon here (narrow alleys often have none): use the nearest base
            let mut best = (f64::MAX, None);
            for tri in &scene.tris {
                if tri.layer != Layer::Building {
                    continue;
                }
                let v = tri.v[0];
                let d = (v[0] - x).hypot(v[2] - z);
                if d < 12.0 && d < best.0 {
                    best = (d, Some(base[tri.feature as usize]));
                }
            }
            best.1
        }
    }
}

/// Searches a 1 m grid inside the chunk for points where, at ear height, the narrowest
/// pair of opposite horizontal rays spans `w_min..w_max` metres between building walls,
/// the perpendicular direction stays open for at least `min_len` metres, and the sky is
/// open. Returns candidates sorted best first.
/// Lowest vertex height per building feature id (its base).
pub fn building_bases(scene: &Scene) -> Vec<f64> {
    let nb = scene
        .buildings
        .len()
        .max(1 + scene.tris.iter().map(|t| t.feature).max().unwrap_or(0) as usize);
    let mut base = vec![f64::MAX; nb];
    for t in &scene.tris {
        if t.layer == Layer::Building {
            for v in &t.v {
                let b = &mut base[t.feature as usize];
                *b = b.min(v[1]);
            }
        }
    }
    base
}

pub fn find_alleys(
    scene: &Scene,
    grid: &Grid,
    half: f64,
    w_min: f64,
    w_max: f64,
    min_len: f64,
) -> Vec<Alley> {
    let base = building_bases(scene);
    let dirs: Vec<V3> = (0..16)
        .map(|k| {
            let a = k as f64 * std::f64::consts::PI / 8.0;
            [a.cos(), 0.0, a.sin()]
        })
        .collect();
    let mut out = vec![];
    let margin = 15.0;
    let mut z = -half + margin;
    while z <= half - margin {
        let mut x = -half + margin;
        while x <= half - margin {
            if let Some(g) = ground_at(scene, grid, &base, x, z) {
                let y = g + 1.6;
                let o = [x, y, z];
                let open_sky = grid.cast(scene, o, [0.0, 1.0, 0.0], 300.0).is_none();
                if open_sky {
                    let hits: Vec<Option<(f64, usize)>> =
                        dirs.iter().map(|&d| grid.cast(scene, o, d, 60.0)).collect();
                    let dist = |k: usize| -> (f64, bool) {
                        match hits[k % 16] {
                            Some((t, ti)) => (t, scene.tris[ti].layer == Layer::Building),
                            None => (60.0, false),
                        }
                    };
                    // narrowest opposite pair (both sides building walls)
                    let mut best: Option<(f64, usize)> = None;
                    for k in 0..8 {
                        let (a, ba) = dist(k);
                        let (b, bb) = dist(k + 8);
                        if ba && bb && best.is_none_or(|bst| a + b < bst.0) {
                            best = Some((a + b, k));
                        }
                    }
                    if let Some((w, k)) = best {
                        let along = k + 4; // perpendicular
                        let len = dist(along).0 + dist(along + 8).0;
                        // centred-ness: prefer points midway between the walls
                        let off = (dist(k).0 - dist(k + 8).0).abs();
                        if w >= w_min && w <= w_max && len >= min_len && off < 1.0 {
                            out.push(Alley {
                                center: [x, g, z],
                                axis: dirs[along % 16],
                                width: w,
                                length: len,
                                ground: g,
                            });
                        }
                    }
                }
            }
            x += 1.0;
        }
        z += 1.0;
    }
    // prefer long, narrow, well-enclosed alleys
    out.sort_by(|a, b| {
        let sa = a.length.min(40.0) - 4.0 * a.width;
        let sb = b.length.min(40.0) - 4.0 * b.width;
        sb.partial_cmp(&sa).unwrap()
    });
    out
}
