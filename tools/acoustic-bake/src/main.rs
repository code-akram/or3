//! acoustic-bake: bake an impulse response for a spot in a world chunk with Steam Audio.
//!
//! 1. Loads the chunk GLB written by plateau-chunk (buildings + roads, local Y-up metres).
//! 2. Finds a narrow alley automatically (or takes `--alley x,z,deg`), and places a source
//!    and a listener `--sep` metres apart along it, both 1.6 m above the ground.
//! 3. Builds a Steam Audio scene (static mesh; concrete / glass materials, plus a ground
//!    plane), runs the reflections simulation (convolution type, 1st-order Ambisonics) and
//!    renders the reflection IR by pushing a unit impulse through a reflection effect.
//! 4. Calibrates the reflection level: the same simulation with only the ground plane must
//!    match the image-source energy of a single ground reflection (Steam Audio's raw
//!    reflection energy is not on the same scale as a 1/r direct path; see the report).
//! 5. Adds the direct path (1/r) encoded in Ambisonics at t = 0 (Steam Audio's reflection
//!    IRs use the direct arrival as t = 0), decodes to mono, stereo and binaural with
//!    Steam Audio's decoder, measures the decay and writes 48 kHz 24-bit WAVs + JSON.

mod analysis;
mod geom;
mod phonon_sys;

use anyhow::{bail, Context, Result};
use phonon_sys::*;
use serde_json::{json, Value};
use std::collections::HashMap;
use std::path::PathBuf;
use std::ptr::null_mut;
use std::time::Instant;

const FS: i32 = 48_000;
const FRAME: i32 = 1024;
const ORDER: i32 = 1;
const NCH: usize = 4; // (ORDER + 1)^2

// Steam Audio material presets (absorption 3 bands, scattering, transmission 3 bands).
// Concrete as listed in the SDK docs (doc/scene.html); glass from the Unity/FMOD plugin
// presets. Ground uses concrete (asphalt is not a preset; similar at these bands).
const CONCRETE: IPLMaterial = IPLMaterial {
    absorption: [0.05, 0.07, 0.08],
    scattering: 0.05,
    transmission: [0.015, 0.002, 0.001],
};
const GLASS: IPLMaterial = IPLMaterial {
    absorption: [0.06, 0.03, 0.02],
    scattering: 0.05,
    transmission: [0.060, 0.044, 0.011],
};

fn ck(r: IPLerror, what: &str) -> Result<()> {
    if r != IPLerror::IPL_STATUS_SUCCESS {
        bail!("{what} failed: {r:?}");
    }
    Ok(())
}

fn v3(a: [f64; 3]) -> IPLVector3 {
    IPLVector3 {
        x: a[0] as f32,
        y: a[1] as f32,
        z: a[2] as f32,
    }
}

fn space(origin: [f64; 3], ahead: [f64; 3]) -> IPLCoordinateSpace3 {
    // right-handed, +y up: right = ahead x up
    let up = [0.0, 1.0, 0.0];
    let right = [
        ahead[1] * up[2] - ahead[2] * up[1],
        ahead[2] * up[0] - ahead[0] * up[2],
        ahead[0] * up[1] - ahead[1] * up[0],
    ];
    IPLCoordinateSpace3 {
        right: v3(right),
        up: v3(up),
        ahead: v3(ahead),
        origin: v3(origin),
    }
}

unsafe extern "C" fn log_cb(level: IPLLogLevel, msg: *const std::os::raw::c_char) {
    let s = unsafe { std::ffi::CStr::from_ptr(msg) }.to_string_lossy();
    eprintln!("[phonon {level:?}] {}", s.trim_end());
}

/// A multichannel frame buffer with stable channel pointers for IPLAudioBuffer.
struct Buf {
    ch: Vec<Vec<f32>>,
    ptrs: Vec<*mut f32>,
}
impl Buf {
    fn new(n: usize) -> Self {
        let mut ch = vec![vec![0f32; FRAME as usize]; n];
        let ptrs = ch.iter_mut().map(|c| c.as_mut_ptr()).collect();
        Buf { ch, ptrs }
    }
    fn ipl(&mut self) -> IPLAudioBuffer {
        IPLAudioBuffer {
            numChannels: self.ch.len() as i32,
            numSamples: FRAME,
            data: self.ptrs.as_mut_ptr(),
        }
    }
    fn zero(&mut self) {
        for c in &mut self.ch {
            c.fill(0.0);
        }
    }
}

struct Mesh {
    verts: Vec<IPLVector3>,
    tris: Vec<IPLTriangle>,
    mat_idx: Vec<i32>,
    materials: Vec<IPLMaterial>,
}

struct SimParams {
    rays: i32,
    bounces: i32,
    duration: f32,
    threads: i32,
    src: [f64; 3],
    lis: [f64; 3],
    to_src: [f64; 3],
}

/// Runs the reflection simulation for one source/listener pair and renders the
/// first-order Ambisonic reflection IR (t = 0 at the direct arrival).
/// Returns (ambisonic IR, timings).
unsafe fn reflection_ir(
    ctx: IPLContext,
    mesh: &mut Mesh,
    p: &SimParams,
    obj: Option<&str>,
) -> Result<(Vec<Vec<f32>>, Value)> {
    unsafe {
        let t = Instant::now();
        let mut scene_settings: IPLSceneSettings = std::mem::zeroed();
        scene_settings.type_ = IPLSceneType::IPL_SCENETYPE_DEFAULT;
        let mut scene: IPLScene = null_mut();
        ck(
            iplSceneCreate(ctx, &mut scene_settings, &mut scene),
            "iplSceneCreate",
        )?;
        let mut ms = IPLStaticMeshSettings {
            numVertices: mesh.verts.len() as i32,
            numTriangles: mesh.tris.len() as i32,
            numMaterials: mesh.materials.len() as i32,
            vertices: mesh.verts.as_mut_ptr(),
            triangles: mesh.tris.as_mut_ptr(),
            materialIndices: mesh.mat_idx.as_mut_ptr(),
            materials: mesh.materials.as_mut_ptr(),
        };
        let mut smesh: IPLStaticMesh = null_mut();
        ck(
            iplStaticMeshCreate(scene, &mut ms, &mut smesh),
            "iplStaticMeshCreate",
        )?;
        iplStaticMeshAdd(smesh, scene);
        iplSceneCommit(scene);
        let scene_s = t.elapsed().as_secs_f64();
        if let Some(obj) = obj {
            let c = std::ffi::CString::new(obj)?;
            iplSceneSaveOBJ(scene, c.as_ptr() as *mut _);
        }

        let mut audio = IPLAudioSettings {
            samplingRate: FS,
            frameSize: FRAME,
        };
        let mut ss: IPLSimulationSettings = std::mem::zeroed();
        ss.flags = IPLSimulationFlags::IPL_SIMULATIONFLAGS_REFLECTIONS;
        ss.sceneType = IPLSceneType::IPL_SCENETYPE_DEFAULT;
        ss.reflectionType = IPLReflectionEffectType::IPL_REFLECTIONEFFECTTYPE_CONVOLUTION;
        ss.maxNumOcclusionSamples = 1;
        ss.maxNumRays = p.rays;
        ss.numDiffuseSamples = 1024;
        ss.maxDuration = p.duration;
        ss.maxOrder = ORDER;
        ss.maxNumSources = 1;
        ss.numThreads = p.threads;
        ss.rayBatchSize = 1;
        ss.samplingRate = FS;
        ss.frameSize = FRAME;
        let mut sim: IPLSimulator = null_mut();
        ck(
            iplSimulatorCreate(ctx, &mut ss, &mut sim),
            "iplSimulatorCreate",
        )?;
        iplSimulatorSetScene(sim, scene);
        iplSimulatorCommit(sim);

        let mut src_settings = IPLSourceSettings {
            flags: IPLSimulationFlags::IPL_SIMULATIONFLAGS_REFLECTIONS,
        };
        let mut source: IPLSource = null_mut();
        ck(
            iplSourceCreate(sim, &mut src_settings, &mut source),
            "iplSourceCreate",
        )?;
        iplSourceAdd(source, sim);
        iplSimulatorCommit(sim);

        let mut inputs: IPLSimulationInputs = std::mem::zeroed();
        inputs.flags = IPLSimulationFlags::IPL_SIMULATIONFLAGS_REFLECTIONS;
        inputs.directFlags = IPLDirectSimulationFlags(0);
        inputs.source = space(p.src, [-p.to_src[0], -p.to_src[1], -p.to_src[2]]);
        inputs.distanceAttenuationModel.type_ =
            IPLDistanceAttenuationModelType::IPL_DISTANCEATTENUATIONTYPE_DEFAULT;
        inputs.airAbsorptionModel.type_ = IPLAirAbsorptionModelType::IPL_AIRABSORPTIONTYPE_DEFAULT;
        inputs.directivity.dipoleWeight = 0.0;
        inputs.directivity.dipolePower = 1.0;
        inputs.reverbScale = [1.0, 1.0, 1.0];
        inputs.hybridReverbTransitionTime = 1.0;
        inputs.hybridReverbOverlapPercent = 0.25;
        inputs.baked = IPLbool::IPL_FALSE;
        iplSourceSetInputs(
            source,
            IPLSimulationFlags::IPL_SIMULATIONFLAGS_REFLECTIONS,
            &mut inputs,
        );

        let mut shared: IPLSimulationSharedInputs = std::mem::zeroed();
        shared.listener = space(p.lis, p.to_src);
        shared.numRays = p.rays;
        shared.numBounces = p.bounces;
        shared.duration = p.duration;
        shared.order = ORDER;
        shared.irradianceMinDistance = 1.0;
        iplSimulatorSetSharedInputs(
            sim,
            IPLSimulationFlags::IPL_SIMULATIONFLAGS_REFLECTIONS,
            &mut shared,
        );

        let t = Instant::now();
        iplSimulatorRunReflections(sim);
        let run_s = t.elapsed().as_secs_f64();

        let mut outputs: IPLSimulationOutputs = std::mem::zeroed();
        iplSourceGetOutputs(
            source,
            IPLSimulationFlags::IPL_SIMULATIONFLAGS_REFLECTIONS,
            &mut outputs,
        );
        let ir_size = (p.duration * FS as f32).round() as i32;
        let mut params = outputs.reflections;
        params.type_ = IPLReflectionEffectType::IPL_REFLECTIONEFFECTTYPE_CONVOLUTION;
        params.numChannels = NCH as i32;
        params.irSize = ir_size;

        let t = Instant::now();
        let mut fx_settings = IPLReflectionEffectSettings {
            type_: IPLReflectionEffectType::IPL_REFLECTIONEFFECTTYPE_CONVOLUTION,
            irSize: ir_size,
            numChannels: NCH as i32,
        };
        let mut fx: IPLReflectionEffect = null_mut();
        ck(
            iplReflectionEffectCreate(ctx, &mut audio, &mut fx_settings, &mut fx),
            "iplReflectionEffectCreate",
        )?;
        let mut inb = Buf::new(1);
        let mut outb = Buf::new(NCH);
        // prime: let the effect load (and cross-fade into) the new IR on silent input
        for _ in 0..4 {
            inb.zero();
            let (mut i, mut o) = (inb.ipl(), outb.ipl());
            iplReflectionEffectApply(fx, &mut params, &mut i, &mut o, null_mut());
        }
        let total = (ir_size + 2 * FRAME) as usize;
        let mut ambi = vec![Vec::with_capacity(total); NCH];
        let mut first = true;
        while ambi[0].len() < total {
            inb.zero();
            if first {
                inb.ch[0][0] = 1.0;
                first = false;
            }
            let (mut i, mut o) = (inb.ipl(), outb.ipl());
            iplReflectionEffectApply(fx, &mut params, &mut i, &mut o, null_mut());
            for c in 0..NCH {
                ambi[c].extend_from_slice(&outb.ch[c]);
            }
        }
        for c in &mut ambi {
            c.truncate(ir_size as usize);
        }
        let render_s = t.elapsed().as_secs_f64();

        iplReflectionEffectRelease(&mut fx);
        iplSourceRemove(source, sim);
        iplSourceRelease(&mut source);
        iplSimulatorRelease(&mut sim);
        iplStaticMeshRemove(smesh, scene);
        iplStaticMeshRelease(&mut smesh);
        iplSceneRelease(&mut scene);
        Ok((
            ambi,
            json!({"scene_build_s": scene_s, "run_reflections_s": run_s, "render_ir_s": render_s}),
        ))
    }
}

fn energy(v: &[f32]) -> f64 {
    v.iter().map(|&x| (x as f64).powi(2)).sum()
}

fn main() -> Result<()> {
    let raw: Vec<String> = std::env::args().skip(1).collect();
    let mut kv: HashMap<String, String> = HashMap::new();
    let mut it = raw.iter();
    while let Some(a) = it.next() {
        let k = a
            .strip_prefix("--")
            .with_context(|| format!("bad arg {a}"))?;
        kv.insert(
            k.to_string(),
            it.next().with_context(|| format!("--{k} value"))?.clone(),
        );
    }
    let get = |k: &str, d: &str| kv.get(k).cloned().unwrap_or_else(|| d.to_string());
    let chunk = PathBuf::from(get("chunk", ""));
    let out_wav = PathBuf::from(get("out", "alley-01.wav"));
    let report_path = PathBuf::from(get("report", "alley-01.json"));
    let rays: i32 = get("rays", "262144").parse()?;
    let bounces: i32 = get("bounces", "64").parse()?;
    let duration: f32 = get("duration", "2.0").parse()?;
    let threads: i32 = get("threads", "3").parse()?;
    let sep: f64 = get("sep", "4.0").parse()?;
    let calibrate = get("calibrate", "1") == "1";
    let ear = 1.6;

    let t_all = Instant::now();
    let mut timings = serde_json::Map::new();
    // ---- geometry + alley -------------------------------------------------------------
    let t = Instant::now();
    let scene = geom::load(&chunk)?;
    let grid = geom::Grid::build(&scene, 4.0);
    timings.insert("load_s".into(), json!(t.elapsed().as_secs_f64()));
    let t = Instant::now();
    let alley = if let Some(spec) = kv.get("alley") {
        let p: Vec<f64> = spec.split(',').map(|v| v.parse().unwrap()).collect();
        let a = p[2].to_radians();
        let base = geom::building_bases(&scene);
        let g = geom::ground_at(&scene, &grid, &base, p[0], p[1])
            .context("alley point is under a building")?;
        geom::Alley {
            center: [p[0], g, p[1]],
            axis: [a.cos(), 0.0, a.sin()],
            width: f64::NAN,
            length: f64::NAN,
            ground: g,
        }
    } else {
        let cands = geom::find_alleys(&scene, &grid, 100.0, 2.0, 5.0, 16.0);
        eprintln!("alley candidates: {}", cands.len());
        for c in cands.iter().take(5) {
            eprintln!("  {c:?}");
        }
        cands.into_iter().next().context("no alley found")?
    };
    timings.insert("alley_search_s".into(), json!(t.elapsed().as_secs_f64()));
    let c = alley.center;
    let src = [
        c[0] - alley.axis[0] * sep / 2.0,
        alley.ground + ear,
        c[2] - alley.axis[2] * sep / 2.0,
    ];
    let lis = [
        c[0] + alley.axis[0] * sep / 2.0,
        alley.ground + ear,
        c[2] + alley.axis[2] * sep / 2.0,
    ];
    let to_src = [
        (src[0] - lis[0]) / sep,
        (src[1] - lis[1]) / sep,
        (src[2] - lis[2]) / sep,
    ];
    let los = grid.cast(&scene, lis, to_src, sep).is_none();

    // ---- Steam Audio meshes -------------------------------------------------------------
    let ground_plane = |m: &mut Mesh, mat: i32| {
        let g = alley.ground as f32 - 0.02;
        let base = m.verts.len() as i32;
        for (x, z) in [
            (-300.0, -300.0),
            (300.0, -300.0),
            (300.0, 300.0),
            (-300.0, 300.0),
        ] {
            m.verts.push(IPLVector3 { x, y: g, z });
        }
        m.tris.push(IPLTriangle {
            indices: [base, base + 2, base + 1],
        }); // normal +y
        m.tris.push(IPLTriangle {
            indices: [base, base + 3, base + 2],
        });
        m.mat_idx.extend([mat, mat]);
    };
    let mut full = Mesh {
        verts: vec![],
        tris: vec![],
        mat_idx: vec![],
        materials: vec![CONCRETE, GLASS],
    };
    let mut n_glass = 0usize;
    for t in &scene.tris {
        let base = full.verts.len() as i32;
        full.verts.extend(t.v.iter().map(|v| v3(*v)));
        full.tris.push(IPLTriangle {
            indices: [base, base + 1, base + 2],
        });
        let usage = scene
            .buildings
            .get(t.feature as usize)
            .and_then(|b| b["usage"].as_str())
            .unwrap_or("");
        let glass = t.layer == geom::Layer::Building
            && t.normal[1].abs() < 0.3
            && matches!(usage, "401" | "402" | "403");
        n_glass += glass as usize;
        full.mat_idx.push(glass as i32);
    }
    ground_plane(&mut full, 0);
    let mut ground_only = Mesh {
        verts: vec![],
        tris: vec![],
        mat_idx: vec![],
        materials: vec![CONCRETE],
    };
    ground_plane(&mut ground_only, 0);

    let mut report = json!({
        "steam_audio": "4.8.1",
        "chunk": chunk.display().to_string(),
        "chunk_scene_extras": scene.scene_extras,
        "triangles": full.tris.len(),
        "glass_triangles": n_glass,
        "alley": {
            "center_local": alley.center, "axis_local": alley.axis,
            "width_m": alley.width, "open_length_m": alley.length, "ground_y": alley.ground,
        },
        "source_local": src, "listener_local": lis,
        "separation_m": sep, "line_of_sight": los,
        "settings": {"rays": rays, "bounces": bounces, "duration_s": duration, "order": ORDER,
                     "fs": FS, "frame": FRAME, "threads": threads, "diffuse_samples": 1024,
                     "materials": {"buildings": "concrete", "vertical walls of usage 401/402/403": "glass",
                                   "roads + 600 m ground plane": "concrete"}},
    });
    if let (Some(e), Some(n)) = (
        report["chunk_scene_extras"]["origin_easting"].as_f64(),
        report["chunk_scene_extras"]["origin_northing"].as_f64(),
    ) {
        report["source_epsg6677"] =
            json!({"easting": e + src[0], "northing": n - src[2], "height": src[1]});
        report["listener_epsg6677"] =
            json!({"easting": e + lis[0], "northing": n - lis[2], "height": lis[1]});
    }

    let sp = SimParams {
        rays,
        bounces,
        duration,
        threads,
        src,
        lis,
        to_src,
    };
    let fs = FS as f64;
    unsafe {
        let mut ctx_settings = IPLContextSettings {
            version: (4 << 16) | (8 << 8) | 1,
            logCallback: Some(log_cb),
            allocateCallback: None,
            freeCallback: None,
            simdLevel: IPLSIMDLevel::IPL_SIMDLEVEL_AVX2,
            flags: IPLContextFlags(0),
        };
        let mut ctx: IPLContext = null_mut();
        ck(
            iplContextCreate(&mut ctx_settings, &mut ctx),
            "iplContextCreate",
        )?;
        let mut audio = IPLAudioSettings {
            samplingRate: FS,
            frameSize: FRAME,
        };

        let (mut ambi_wet, t_full) =
            reflection_ir(ctx, &mut full, &sp, kv.get("save-obj").map(|s| s.as_str()))?;
        timings.insert("full_scene".into(), t_full);

        // ---- level calibration against a single ground reflection ----------------------
        // Mono decode = W * sqrt(4 pi) (Steam Audio uses orthonormal SH). Theory for one
        // reflector: E = (1 - mean absorption) / d_image^2, with d_image the mirror path.
        let w_to_mono = (4.0 * std::f64::consts::PI).sqrt();
        let mut cal_gain = 1.0f64;
        if calibrate {
            let (ambi_g, t_g) = reflection_ir(ctx, &mut ground_only, &sp, None)?;
            timings.insert("calibration_scene".into(), t_g);
            let e_meas = energy(&ambi_g[0]) * w_to_mono * w_to_mono;
            let h = ear;
            let d_img = (sep * sep + 4.0 * h * h).sqrt();
            let alpha = CONCRETE.absorption.iter().map(|&a| a as f64).sum::<f64>() / 3.0;
            let e_th = (1.0 - alpha) / (d_img * d_img);
            cal_gain = (e_th / e_meas).sqrt();
            report["calibration"] = json!({
                "method": "ground-plane-only run vs image-source energy of one specular+diffuse reflection",
                "image_path_m": d_img,
                "energy_theory": e_th,
                "energy_steam_audio": e_meas,
                "gain_applied_to_reflections_db": 20.0 * cal_gain.log10(),
            });
            for c in &mut ambi_wet {
                for x in c.iter_mut() {
                    *x *= cal_gain as f32;
                }
            }
        }

        // ---- direct path, encoded to Ambisonics in the same (world) frame ---------------
        // Steam Audio's reflection IR uses the direct-sound arrival as t = 0 (the
        // simulator subtracts DirectSimulator::directPathDelay). We keep that time base:
        // the direct impulse goes at sample 0; the propagation delay is only reported.
        let mut ambi_full = ambi_wet.clone();
        let delay = (sep / 343.0 * fs).round() as usize;
        let gain = if los { 1.0 / sep.max(1.0) } else { 0.0 } as f32;
        {
            let mut es = IPLAmbisonicsEncodeEffectSettings { maxOrder: ORDER };
            let mut enc: IPLAmbisonicsEncodeEffect = null_mut();
            ck(
                iplAmbisonicsEncodeEffectCreate(ctx, &mut audio, &mut es, &mut enc),
                "encode create",
            )?;
            let mut dirac = Buf::new(1);
            let mut ob = Buf::new(NCH);
            let mut p = IPLAmbisonicsEncodeEffectParams {
                direction: v3(to_src),
                order: ORDER,
            };
            // prime on silence so the direction cross-fade has settled before the impulse
            for _ in 0..2 {
                let (mut i, mut o) = (dirac.ipl(), ob.ipl());
                iplAmbisonicsEncodeEffectApply(enc, &mut p, &mut i, &mut o);
            }
            dirac.ch[0][0] = gain;
            let (mut i, mut o) = (dirac.ipl(), ob.ipl());
            iplAmbisonicsEncodeEffectApply(enc, &mut p, &mut i, &mut o);
            report["direct_encode_gain_per_channel"] = json!((0..NCH)
                .map(|c| ob.ch[c][0] / gain.max(1e-9))
                .collect::<Vec<_>>());
            for c in 0..NCH {
                for k in 0..FRAME as usize {
                    ambi_full[c][k] += ob.ch[c][k];
                }
            }
            iplAmbisonicsEncodeEffectRelease(&mut enc);
        }

        // ---- decode: mono, stereo (panning), binaural (default HRTF) ---------------------
        let t = Instant::now();
        let mut hs = IPLHRTFSettings {
            type_: IPLHRTFType::IPL_HRTFTYPE_DEFAULT,
            sofaFileName: std::ptr::null(),
            sofaData: std::ptr::null(),
            sofaDataSize: 0,
            volume: 1.0,
            normType: IPLHRTFNormType::IPL_HRTFNORMTYPE_NONE,
        };
        let mut hrtf: IPLHRTF = null_mut();
        ck(
            iplHRTFCreate(ctx, &mut audio, &mut hs, &mut hrtf),
            "iplHRTFCreate",
        )?;
        let listener = space(lis, to_src);
        let mut decode = |ambi: &Vec<Vec<f32>>,
                          layout: IPLSpeakerLayoutType,
                          nout: usize,
                          binaural: bool|
         -> Result<Vec<Vec<f32>>> {
            let mut ds = IPLAmbisonicsDecodeEffectSettings {
                speakerLayout: IPLSpeakerLayout {
                    type_: layout,
                    numSpeakers: 0,
                    speakers: null_mut(),
                },
                hrtf,
                maxOrder: ORDER,
            };
            let mut dec: IPLAmbisonicsDecodeEffect = null_mut();
            ck(
                iplAmbisonicsDecodeEffectCreate(ctx, &mut audio, &mut ds, &mut dec),
                "decode create",
            )?;
            let mut p = IPLAmbisonicsDecodeEffectParams {
                order: ORDER,
                hrtf,
                orientation: listener,
                binaural: if binaural {
                    IPLbool::IPL_TRUE
                } else {
                    IPLbool::IPL_FALSE
                },
            };
            let n = ambi[0].len();
            let mut out = vec![Vec::with_capacity(n + FRAME as usize); nout];
            let mut ib = Buf::new(NCH);
            let mut ob = Buf::new(nout);
            // prime (orientation cross-fade) on silence
            for _ in 0..2 {
                let (mut i, mut o) = (ib.ipl(), ob.ipl());
                iplAmbisonicsDecodeEffectApply(dec, &mut p, &mut i, &mut o);
            }
            let mut pos = 0;
            while pos < n + FRAME as usize {
                for c in 0..NCH {
                    for k in 0..FRAME as usize {
                        ib.ch[c][k] = *ambi[c].get(pos + k).unwrap_or(&0.0);
                    }
                }
                let (mut i, mut o) = (ib.ipl(), ob.ipl());
                iplAmbisonicsDecodeEffectApply(dec, &mut p, &mut i, &mut o);
                for c in 0..nout {
                    out[c].extend_from_slice(&ob.ch[c]);
                }
                pos += FRAME as usize;
            }
            for c in &mut out {
                c.truncate(n);
            }
            iplAmbisonicsDecodeEffectRelease(&mut dec);
            Ok(out)
        };
        let full_mono = decode(
            &ambi_full,
            IPLSpeakerLayoutType::IPL_SPEAKERLAYOUTTYPE_MONO,
            1,
            false,
        )?;
        let wet_mono = decode(
            &ambi_wet,
            IPLSpeakerLayoutType::IPL_SPEAKERLAYOUTTYPE_MONO,
            1,
            false,
        )?;
        let full_st = decode(
            &ambi_full,
            IPLSpeakerLayoutType::IPL_SPEAKERLAYOUTTYPE_STEREO,
            2,
            false,
        )?;
        let wet_st = decode(
            &ambi_wet,
            IPLSpeakerLayoutType::IPL_SPEAKERLAYOUTTYPE_STEREO,
            2,
            false,
        )?;
        let full_bin = decode(
            &ambi_full,
            IPLSpeakerLayoutType::IPL_SPEAKERLAYOUTTYPE_STEREO,
            2,
            true,
        )?;
        timings.insert("decode_s".into(), json!(t.elapsed().as_secs_f64()));
        iplHRTFRelease(&mut hrtf);
        iplContextRelease(&mut ctx);

        // ---- measure, trim, normalise, write -------------------------------------------
        report["measure_full_mono"] = analysis::measure(&full_mono[0], fs);
        report["measure_wet_mono"] = analysis::measure(&wet_mono[0], fs);
        report["octave_bands_full_mono"] = analysis::octave_bands(&full_mono[0], fs);
        let direct: Vec<f32> = full_mono[0]
            .iter()
            .zip(&wet_mono[0])
            .map(|(a, b)| a - b)
            .collect();
        report["drr_db"] =
            json!(10.0 * (energy(&direct) / energy(&wet_mono[0]).max(1e-30)).log10());
        report["drr_db_uncalibrated"] = json!(
            10.0 * (energy(&direct) / (energy(&wet_mono[0]) / (cal_gain * cal_gain)).max(1e-30))
                .log10()
        );
        report["direct"] = json!({
            "placed_at_sample": 0,
            "propagation_delay_removed_samples": delay,
            "propagation_delay_removed_ms": delay as f64 / fs * 1000.0,
            "gain_inverse_distance": gain,
            "time_base": "t = 0 is the direct-sound arrival (Steam Audio convention)",
        });
        // trim where the full IR's energy decay reaches -60 dB (sparse stochastic late bins
        // beyond that are dropped), 10 ms fade-out
        let edc = analysis::edc_db(&full_mono[0]);
        let end = edc.iter().position(|&v| v <= -60.0).unwrap_or(edc.len());
        let fade = (0.010 * fs) as usize;
        let shape = |chs: &Vec<Vec<f32>>, g: f32| -> Vec<Vec<f32>> {
            chs.iter()
                .map(|c| {
                    let mut v: Vec<f32> = c[..end.min(c.len())].iter().map(|x| x * g).collect();
                    let n = v.len();
                    for k in 0..fade.min(n) {
                        v[n - 1 - k] *= k as f32 / fade as f32;
                    }
                    v
                })
                .collect()
        };
        // one gain for every file: the loudest of the full IRs -> -1 dBFS, so the wet IR
        // keeps its true level relative to the full one
        let peak = full_st
            .iter()
            .chain(full_bin.iter())
            .chain(full_mono.iter())
            .flatten()
            .fold(0.0f32, |m, v| m.max(v.abs()));
        let g = 10f32.powf(-1.0 / 20.0) / peak.max(1e-9);
        report["normalisation_gain_db"] = json!(20.0 * g.log10());
        report["trimmed_samples"] = json!(end);
        report["trimmed_seconds"] = json!(end as f64 / fs);
        let stem = out_wav.with_extension("");
        let name = |suffix: &str| PathBuf::from(format!("{}{suffix}.wav", stem.display()));
        if let Some(dir) = out_wav.parent() {
            std::fs::create_dir_all(dir)?;
        }
        analysis::write_wav24(&out_wav, &shape(&full_st, g), FS as u32)?;
        analysis::write_wav24(&name("-wet"), &shape(&wet_st, g), FS as u32)?;
        analysis::write_wav24(&name("-binaural"), &shape(&full_bin, g), FS as u32)?;
        analysis::write_wav24(&name("-mono"), &shape(&full_mono, g), FS as u32)?;
        report["files"] = json!({
            "full_stereo": out_wav.display().to_string(),
            "wet_stereo": name("-wet").display().to_string(),
            "full_binaural": name("-binaural").display().to_string(),
            "full_mono": name("-mono").display().to_string(),
        });
    }
    timings.insert("total_s".into(), json!(t_all.elapsed().as_secs_f64()));
    report["timings"] = Value::Object(timings);
    report["loadavg"] = json!(std::fs::read_to_string("/proc/loadavg")
        .unwrap_or_default()
        .trim());
    std::fs::write(&report_path, serde_json::to_string_pretty(&report)?)?;
    println!("{}", serde_json::to_string_pretty(&report)?);
    Ok(())
}
