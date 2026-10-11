//! Impulse-response measurements (Schroeder backward integration) and a WAV writer.

use anyhow::Result;
use serde_json::{json, Value};
use std::io::Write;
use std::path::Path;

/// Energy decay curve in dB (0 dB at t = 0).
pub fn edc_db(ir: &[f32]) -> Vec<f64> {
    let mut acc = 0.0f64;
    let mut e = vec![0.0; ir.len()];
    for i in (0..ir.len()).rev() {
        acc += (ir[i] as f64).powi(2);
        e[i] = acc;
    }
    let total = e.first().copied().unwrap_or(0.0).max(1e-30);
    e.iter()
        .map(|x| 10.0 * (x / total).max(1e-30).log10())
        .collect()
}

/// Least-squares slope (dB/s) of the EDC between `hi` and `lo` dB, extrapolated to 60 dB.
fn decay_time(edc: &[f64], fs: f64, hi: f64, lo: f64) -> Option<f64> {
    let i0 = edc.iter().position(|&v| v <= hi)?;
    let i1 = edc.iter().position(|&v| v <= lo)?;
    if i1 <= i0 + 2 {
        return None;
    }
    let n = (i1 - i0) as f64;
    let (mut sx, mut sy, mut sxx, mut sxy) = (0.0, 0.0, 0.0, 0.0);
    for (k, &y) in edc[i0..i1].iter().enumerate() {
        let x = (i0 + k) as f64 / fs;
        sx += x;
        sy += y;
        sxx += x * x;
        sxy += x * y;
    }
    let slope = (n * sxy - sx * sy) / (n * sxx - sx * sx);
    (slope < 0.0).then(|| -60.0 / slope)
}

pub fn measure(ir: &[f32], fs: f64) -> Value {
    let edc = edc_db(ir);
    let peak = ir.iter().fold(0.0f32, |m, v| m.max(v.abs()));
    // onset: first sample within 40 dB of the peak
    let onset = ir.iter().position(|v| v.abs() > peak * 0.01).unwrap_or(0);
    // early energy profile: 2 ms bins over the first 60 ms, dB relative to the loudest bin
    let bin = (0.002 * fs) as usize;
    let bins: Vec<f64> = (0..30)
        .map(|b| {
            ir.iter()
                .skip(b * bin)
                .take(bin)
                .map(|&x| (x as f64).powi(2))
                .sum::<f64>()
        })
        .collect();
    let bmax = bins.iter().cloned().fold(1e-30, f64::max);
    let early: Vec<f64> = bins
        .iter()
        .map(|e| (10.0 * (e / bmax).max(1e-12).log10() * 10.0).round() / 10.0)
        .collect();
    let t_at = |db: f64| edc.iter().position(|&v| v <= db).map(|i| i as f64 / fs);
    json!({
        "samples": ir.len(),
        "seconds": ir.len() as f64 / fs,
        "onset_ms_40db": onset as f64 / fs * 1000.0,
        "early_profile_2ms_db": early,
        "peak": peak,
        "edt_s": decay_time(&edc, fs, -0.0001, -10.0),
        "t20_s": decay_time(&edc, fs, -5.0, -25.0),
        "t30_s": decay_time(&edc, fs, -5.0, -35.0),
        "edc_minus20db_at_s": t_at(-20.0),
        "edc_minus40db_at_s": t_at(-40.0),
        "edc_minus60db_at_s": t_at(-60.0),
    })
}

/// RBJ band-pass (constant 0 dB peak gain), applied forward only.
pub fn bandpass(x: &[f32], fs: f64, f0: f64, q: f64) -> Vec<f32> {
    let w0 = 2.0 * std::f64::consts::PI * f0 / fs;
    let alpha = w0.sin() / (2.0 * q);
    let (b0, b1, b2) = (alpha, 0.0, -alpha);
    let (a0, a1, a2) = (1.0 + alpha, -2.0 * w0.cos(), 1.0 - alpha);
    let (mut x1, mut x2, mut y1, mut y2) = (0.0, 0.0, 0.0, 0.0);
    x.iter()
        .map(|&s| {
            let s = s as f64;
            let y = (b0 * s + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2) / a0;
            x2 = x1;
            x1 = s;
            y2 = y1;
            y1 = y;
            y as f32
        })
        .collect()
}

pub fn octave_bands(ir: &[f32], fs: f64) -> Value {
    let mut out = serde_json::Map::new();
    for f in [125.0, 250.0, 500.0, 1000.0, 2000.0, 4000.0, 8000.0] {
        let b = bandpass(ir, fs, f, std::f64::consts::SQRT_2);
        let edc = edc_db(&b);
        out.insert(
            format!("{f}"),
            json!({
                "t20_s": decay_time(&edc, fs, -5.0, -25.0),
                "edt_s": decay_time(&edc, fs, -0.0001, -10.0),
            }),
        );
    }
    Value::Object(out)
}

/// Writes interleaved 24-bit PCM WAV.
pub fn write_wav24(path: &Path, channels: &[Vec<f32>], fs: u32) -> Result<()> {
    let nch = channels.len() as u16;
    let n = channels[0].len();
    let data_len = (n * nch as usize * 3) as u32;
    let mut f = std::io::BufWriter::new(std::fs::File::create(path)?);
    f.write_all(b"RIFF")?;
    f.write_all(&(36 + data_len).to_le_bytes())?;
    f.write_all(b"WAVEfmt ")?;
    f.write_all(&16u32.to_le_bytes())?;
    f.write_all(&1u16.to_le_bytes())?; // PCM
    f.write_all(&nch.to_le_bytes())?;
    f.write_all(&fs.to_le_bytes())?;
    f.write_all(&(fs * nch as u32 * 3).to_le_bytes())?;
    f.write_all(&(nch * 3).to_le_bytes())?;
    f.write_all(&24u16.to_le_bytes())?;
    f.write_all(b"data")?;
    f.write_all(&data_len.to_le_bytes())?;
    for i in 0..n {
        for ch in channels {
            let v = (ch[i].clamp(-1.0, 1.0) as f64 * 8_388_607.0).round() as i32;
            f.write_all(&v.to_le_bytes()[..3])?;
        }
    }
    Ok(())
}
