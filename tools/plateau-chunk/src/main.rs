//! plateau-chunk: cut fixed-grid world chunks out of nusamai glTF output.
//!
//! nusamai (PLATEAU GIS Converter) writes one GLB per feature type, with vertices in a
//! Japan Plane Rectangular CS mapped Z-up -> Y-up as [easting, height, -northing] and the
//! per-feature attributes in EXT_structural_metadata. This tool:
//!   * `inspect`    — prints counts, bounds and attribute coverage of such a GLB.
//!   * `project`    — projects lat/lon (JGD2011) to EPSG:6677 with our own Krüger series.
//!   * `verify-crs` — compares GML vertices, projected by us, with nusamai's output.
//!   * `chunk`      — selects a fixed square of the EPSG:6677 grid, re-origins it to the
//!     chunk centre (three.js Y-up: +x east, +y up, -z north) and writes one GLB with the
//!     building attributes in mesh extras.

use plateau_chunk::{glb, tm};

use anyhow::{bail, Context, Result};
use serde_json::{json, Map, Value};
use std::collections::{BTreeMap, HashMap};
use std::path::{Path, PathBuf};
use std::time::Instant;

const CREDIT: &str = "出典：国土交通省 PLATEAU（3D都市モデル 新宿区 2025年度, https://www.geospatial.jp/ckan/dataset/plateau-13104-shinjuku-ku-2025）を加工して作成";

/// Attributes copied into the GLB extras (the full set goes to the sidecar JSON).
/// Values from the GML scan take precedence over nusamai's property table.
const KEEP_ATTRS: &[&str] = &[
    "id",
    "measuredHeight",
    "storeysAboveGround",
    "storeysBelowGround",
    "usage",
    "usageLabel",
    "class",
    "lod",
    "lodType",
];

fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let Some(cmd) = args.first() else {
        bail!("usage: plateau-chunk <inspect|project|verify-crs|chunk> ...");
    };
    let rest = &args[1..];
    match cmd.as_str() {
        "inspect" => inspect(Path::new(rest.first().context("inspect <glb>")?)),
        "project" => {
            let lat: f64 = rest.first().context("project <lat> <lon>")?.parse()?;
            let lon: f64 = rest.get(1).context("project <lat> <lon>")?.parse()?;
            let (e, n) = tm::forward(tm::ZONE_IX, lat, lon);
            println!("{{\"lat\":{lat},\"lon\":{lon},\"easting\":{e:.4},\"northing\":{n:.4}}}");
            Ok(())
        }
        "verify-crs" => verify_crs(&Opts::parse(rest)?),
        "chunk" => chunk(&Opts::parse(rest)?),
        _ => bail!("unknown command {cmd}"),
    }
}

struct Opts {
    kv: HashMap<String, String>,
    layers: Vec<String>,
}

impl Opts {
    fn parse(args: &[String]) -> Result<Self> {
        let mut kv = HashMap::new();
        let mut layers = vec![];
        let mut it = args.iter();
        while let Some(a) = it.next() {
            let key = a
                .strip_prefix("--")
                .with_context(|| format!("bad arg {a}"))?;
            let val = it
                .next()
                .with_context(|| format!("--{key} needs a value"))?;
            if key == "layer" {
                layers.push(val.clone());
            } else {
                kv.insert(key.to_string(), val.clone());
            }
        }
        Ok(Opts { kv, layers })
    }
    fn get(&self, k: &str) -> Result<&str> {
        self.kv
            .get(k)
            .map(|s| s.as_str())
            .with_context(|| format!("missing --{k}"))
    }
    fn f64(&self, k: &str) -> Result<f64> {
        Ok(self.get(k)?.parse()?)
    }
}

/// Geometry of one nusamai GLB, flattened: absolute EPSG:6677 positions in f64
/// (easting, northing, height), normals in glTF Y-up, feature id per vertex, triangles.
struct Source {
    pos_enh: Vec<[f64; 3]>,
    normals: Vec<[f32; 3]>,
    fid: Vec<u32>,
    tris: Vec<[u32; 3]>,
    attrs: Vec<Map<String, Value>>,
}

fn load_source(path: &Path) -> Result<Source> {
    let g = glb::Glb::read(path)?;
    let prims = g.json["meshes"][0]["primitives"]
        .as_array()
        .context("no primitives")?
        .clone();
    let attrs0 = &prims[0]["attributes"];
    let (p, _) = g.accessor_f32(attrs0["POSITION"].as_u64().context("POSITION")?)?;
    let (nrm, _) = g.accessor_f32(attrs0["NORMAL"].as_u64().context("NORMAL")?)?;
    let (f, _) = g.accessor_f32(attrs0["_FEATURE_ID_0"].as_u64().context("_FEATURE_ID_0")?)?;
    let mut tris = vec![];
    for prim in &prims {
        // all nusamai primitives share the same vertex accessors
        if prim["attributes"]["POSITION"] != attrs0["POSITION"] {
            bail!("primitives with separate vertex buffers are not supported");
        }
        let idx = g.accessor_indices(prim["indices"].as_u64().context("indices")?)?;
        tris.extend(idx.chunks_exact(3).map(|t| [t[0], t[1], t[2]]));
    }
    let pos_enh = p
        .chunks_exact(3)
        .map(|v| [v[0] as f64, -(v[2] as f64), v[1] as f64])
        .collect();
    let normals = nrm.chunks_exact(3).map(|v| [v[0], v[1], v[2]]).collect();
    let fid = f.iter().map(|&x| x as u32).collect();
    let attrs = if g.json["extensions"]["EXT_structural_metadata"].is_object() {
        g.property_table(0)?
    } else {
        vec![]
    };
    Ok(Source {
        pos_enh,
        normals,
        fid,
        tris,
        attrs,
    })
}

fn inspect(path: &Path) -> Result<()> {
    let t = Instant::now();
    let s = load_source(path)?;
    let mut min = [f64::MAX; 3];
    let mut max = [f64::MIN; 3];
    for p in &s.pos_enh {
        for c in 0..3 {
            min[c] = min[c].min(p[c]);
            max[c] = max[c].max(p[c]);
        }
    }
    let mut cover: BTreeMap<String, usize> = BTreeMap::new();
    for row in &s.attrs {
        for k in row.keys() {
            *cover.entry(k.clone()).or_default() += 1;
        }
    }
    let out = json!({
        "file": path.display().to_string(),
        "vertices": s.pos_enh.len(),
        "triangles": s.tris.len(),
        "features": s.attrs.len(),
        "min_enh": min, "max_enh": max,
        "attribute_coverage": cover,
        "sample_feature": s.attrs.first(),
        "load_ms": t.elapsed().as_millis(),
    });
    println!("{}", serde_json::to_string_pretty(&out)?);
    Ok(())
}

/// Reads a PLATEAU codelist (gml:Dictionary): code -> label.
fn read_codelist(path: &Path) -> HashMap<String, String> {
    let Ok(text) = std::fs::read_to_string(path) else {
        return HashMap::new();
    };
    let mut out = HashMap::new();
    let mut desc = String::new();
    for l in text.lines().map(str::trim) {
        if let Some(r) = l.strip_prefix("<gml:description>") {
            desc = r.split('<').next().unwrap_or("").to_string();
        } else if let Some(r) = l.strip_prefix("<gml:name>") {
            out.insert(r.split('<').next().unwrap_or("").to_string(), desc.clone());
        }
    }
    out
}

fn tag_text<'a>(l: &'a str, tag: &str) -> Option<&'a str> {
    // matches `<tag>text</tag>` and `<tag attr="..">text</tag>` on one line
    let rest = l.strip_prefix(tag)?;
    if !rest.starts_with(['>', ' ']) {
        return None;
    }
    let (_, body) = rest.split_once('>')?;
    body.split('<').next()
}

/// Scans a PLATEAU bldg GML line by line (PLATEAU files are one element per line) and
/// returns, per building gml:id, the attributes we need straight from the source:
/// geometric LOD (lod1Solid / lod2Solid / lod3*), uro:lodType, usage (+ label),
/// measuredHeight and storeys. This sidesteps nusamai 0.1.19's broken array attributes.
fn scan_buildings(gml: &Path) -> Result<HashMap<String, Map<String, Value>>> {
    use std::io::{BufRead, BufReader};
    let usage_labels = gml
        .parent()
        .and_then(|p| p.parent())
        .and_then(|p| p.parent())
        .map(|root| read_codelist(&root.join("codelists/Building_usage.xml")))
        .unwrap_or_default();
    let f = BufReader::with_capacity(1 << 20, std::fs::File::open(gml)?);
    let mut out: HashMap<String, Map<String, Value>> = HashMap::new();
    let mut cur: Option<String> = None;
    for line in f.lines() {
        let line = line?;
        let l = line.trim_start();
        if let Some(rest) = l.strip_prefix("<bldg:Building gml:id=\"") {
            let id = rest.split('"').next().unwrap_or("").to_string();
            out.insert(id.clone(), Map::new());
            cur = Some(id);
            continue;
        }
        let Some(id) = &cur else { continue };
        let row = out.get_mut(id).unwrap();
        let lod = if l.starts_with("<bldg:lod3") {
            3
        } else if l.starts_with("<bldg:lod2Solid") {
            2
        } else if l.starts_with("<bldg:lod1Solid") {
            1
        } else {
            0
        };
        if lod > 0 {
            let prev = row.get("lod").and_then(|v| v.as_u64()).unwrap_or(0);
            row.insert("lod".into(), json!(prev.max(lod)));
        } else if let Some(v) = tag_text(l, "<uro:lodType") {
            row.insert("lodType".into(), json!(v));
        } else if let Some(v) = tag_text(l, "<bldg:usage") {
            if !row.contains_key("usage") {
                row.insert("usage".into(), json!(v));
                if let Some(lbl) = usage_labels.get(v) {
                    row.insert("usageLabel".into(), json!(lbl));
                }
            }
        } else if let Some(v) = tag_text(l, "<bldg:measuredHeight") {
            if let Ok(x) = v.parse::<f64>() {
                row.insert("measuredHeight".into(), json!(x));
            }
        } else if let Some(v) = tag_text(l, "<bldg:storeysAboveGround") {
            if let Ok(x) = v.parse::<i64>() {
                row.insert("storeysAboveGround".into(), json!(x));
            }
        } else if let Some(v) = tag_text(l, "<bldg:storeysBelowGround") {
            if let Ok(x) = v.parse::<i64>() {
                row.insert("storeysBelowGround".into(), json!(x));
            }
        }
    }
    Ok(out)
}

/// Reads up to `max` (lat, lon, h) triples from gml:posList elements.
fn gml_vertices(gml: &Path, max: usize) -> Result<Vec<[f64; 3]>> {
    use std::io::{BufRead, BufReader};
    let f = BufReader::with_capacity(1 << 20, std::fs::File::open(gml)?);
    let mut out = vec![];
    for line in f.lines() {
        let line = line?;
        if let Some(i) = line.find("<gml:posList>") {
            let body = &line[i + 13..];
            let body = body.split('<').next().unwrap_or("");
            let nums: Vec<f64> = body
                .split_whitespace()
                .filter_map(|x| x.parse().ok())
                .collect();
            // take the first vertex of each ring: spreads samples across the file
            if nums.len() >= 3 {
                out.push([nums[0], nums[1], nums[2]]);
                if out.len() >= max {
                    break;
                }
            }
        }
    }
    Ok(out)
}

fn verify_crs(o: &Opts) -> Result<()> {
    let gml = PathBuf::from(o.get("gml")?);
    let glb_path = PathBuf::from(o.get("glb")?);
    let max: usize = o.get("max").unwrap_or("5000").parse()?;
    let s = load_source(&glb_path)?;
    // spatial hash of nusamai vertices (1 m cells)
    let mut grid: HashMap<(i64, i64), Vec<usize>> = HashMap::new();
    for (i, p) in s.pos_enh.iter().enumerate() {
        grid.entry((p[0].floor() as i64, p[1].floor() as i64))
            .or_default()
            .push(i);
    }
    let verts = gml_vertices(&gml, max)?;
    // Nearest nusamai vertex (3D) to each GML vertex we project ourselves. Vertices of
    // geometry nusamai did not emit (LOD1 solids of LOD2 buildings, LOD0 footprints)
    // find a different, far vertex, so report percentiles and the "exact" share.
    let mut d3: Vec<f64> = vec![];
    let mut dh_exact: Vec<f64> = vec![];
    let mut missing = 0usize;
    for v in &verts {
        let (e, nn) = tm::forward(tm::ZONE_IX, v[0], v[1]);
        let mut best = (f64::MAX, 0.0);
        for dx in -1..=1 {
            for dy in -1..=1 {
                if let Some(ids) = grid.get(&(e.floor() as i64 + dx, nn.floor() as i64 + dy)) {
                    for &i in ids {
                        let p = s.pos_enh[i];
                        let dh = ((p[0] - e).powi(2) + (p[1] - nn).powi(2)).sqrt();
                        let d = dh + (p[2] - v[2]).abs();
                        if d < best.0 {
                            best = (d, dh);
                        }
                    }
                }
            }
        }
        if best.0 == f64::MAX {
            missing += 1; // ring not emitted (e.g. LOD1 solid when LOD2 was selected)
            continue;
        }
        d3.push(best.0);
        if best.0 < 0.05 {
            dh_exact.push(best.1);
        }
    }
    let pct = |v: &mut Vec<f64>, p: f64| -> f64 {
        if v.is_empty() {
            return f64::NAN;
        }
        v.sort_by(|a, b| a.partial_cmp(b).unwrap());
        v[((v.len() - 1) as f64 * p).round() as usize]
    };
    let n_exact = dh_exact.len();
    let out = json!({
        "gml_vertices_sampled": verts.len(),
        "no_vertex_within_1m": missing,
        "nearest_3d_p50_m": pct(&mut d3, 0.5),
        "nearest_3d_p90_m": pct(&mut d3, 0.9),
        "matched_within_5cm": n_exact,
        "matched_horizontal_mean_m": dh_exact.iter().sum::<f64>() / n_exact.max(1) as f64,
        "matched_horizontal_p99_m": pct(&mut dh_exact, 0.99),
        "matched_horizontal_max_m": pct(&mut dh_exact, 1.0),
        "note": "ours = Krüger 6th-order GRS80 zone IX in f64 (matches GSI bl2xy to 0.1 mm); theirs = nusamai GLB vertices (f32 absolute)",
    });
    println!("{}", serde_json::to_string_pretty(&out)?);
    Ok(())
}

struct LayerSpec {
    mode: String,
    name: String,
    path: PathBuf,
}

fn chunk(o: &Opts) -> Result<()> {
    let t_all = Instant::now();
    let size = o.f64("size")?;
    let (e0, n0) = (o.f64("min-e")?, o.f64("min-n")?);
    let (ec, nc) = (e0 + size / 2.0, n0 + size / 2.0);
    let inside = |e: f64, n: f64| e >= e0 && e < e0 + size && n >= n0 && n < n0 + size;
    let out_path = PathBuf::from(o.get("out")?);
    let meta_path = PathBuf::from(o.get("meta")?);
    let lods = match o.kv.get("gml") {
        Some(g) => scan_buildings(Path::new(g))?,
        None => HashMap::new(),
    };
    let specs: Vec<LayerSpec> = o
        .layers
        .iter()
        .map(|l| {
            let mut it = l.splitn(3, ':');
            Ok(LayerSpec {
                mode: it.next().context("layer mode")?.into(),
                name: it.next().context("layer name")?.into(),
                path: it.next().context("layer path")?.into(),
            })
        })
        .collect::<Result<_>>()?;

    let mut meshes = vec![];
    let mut report = Map::new();
    for spec in &specs {
        let t = Instant::now();
        let s = load_source(&spec.path)?;
        let load_ms = t.elapsed().as_millis();
        // decide which triangles to keep
        let keep_feature: Vec<bool> = if spec.mode == "whole" {
            // per-feature centroid of the footprint bbox decides membership
            let nf = s
                .attrs
                .len()
                .max(s.fid.iter().max().map_or(0, |m| *m as usize + 1));
            let mut bb = vec![[f64::MAX, f64::MAX, f64::MIN, f64::MIN]; nf];
            for tri in &s.tris {
                for &v in tri {
                    let p = s.pos_enh[v as usize];
                    let b = &mut bb[s.fid[v as usize] as usize];
                    b[0] = b[0].min(p[0]);
                    b[1] = b[1].min(p[1]);
                    b[2] = b[2].max(p[0]);
                    b[3] = b[3].max(p[1]);
                }
            }
            bb.iter()
                .map(|b| b[0] <= b[2] && inside((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0))
                .collect()
        } else {
            vec![]
        };
        let mut remap_v: HashMap<u32, u32> = HashMap::new();
        let mut remap_f: BTreeMap<u32, u32> = BTreeMap::new();
        let mut m = glb::OutMesh {
            name: spec.name.clone(),
            color: match spec.name.as_str() {
                "bldg" => [0.78, 0.76, 0.72, 1.0],
                "tran" => [0.25, 0.25, 0.27, 1.0],
                "frn" => [0.55, 0.35, 0.25, 1.0],
                _ => [0.3, 0.6, 0.3, 1.0],
            },
            positions: vec![],
            normals: vec![],
            feature_ids: vec![],
            indices: vec![],
            extras: Value::Null,
        };
        for tri in &s.tris {
            let keep = if spec.mode == "whole" {
                keep_feature[s.fid[tri[0] as usize] as usize]
            } else {
                let c = tri.iter().fold([0.0, 0.0], |a, &v| {
                    let p = s.pos_enh[v as usize];
                    [a[0] + p[0] / 3.0, a[1] + p[1] / 3.0]
                });
                inside(c[0], c[1])
            };
            if !keep {
                continue;
            }
            for &v in tri {
                let ni = *remap_v.entry(v).or_insert_with(|| {
                    let p = s.pos_enh[v as usize];
                    let f = s.fid[v as usize];
                    let nf = remap_f.len() as u32;
                    let lf = *remap_f.entry(f).or_insert(nf);
                    // three.js Y-up, chunk-centre origin: x = east, y = height, z = -north
                    m.positions
                        .push([(p[0] - ec) as f32, p[2] as f32, -(p[1] - nc) as f32]);
                    m.normals.push(s.normals[v as usize]);
                    m.feature_ids.push(lf as f32);
                    m.positions.len() as u32 - 1
                });
                m.indices.push(ni);
            }
        }
        // feature attribute tables, in local feature-id order
        let mut full = vec![];
        let mut slim = vec![];
        let mut cover: BTreeMap<String, usize> = BTreeMap::new();
        let mut lod_hist: BTreeMap<String, usize> = BTreeMap::new();
        let mut usage_hist: BTreeMap<String, usize> = BTreeMap::new();
        // local feature id -> source feature id
        let mut order = vec![0u32; remap_f.len()];
        for (&g, &l) in &remap_f {
            order[l as usize] = g;
        }
        for &f in &order {
            let mut row = s.attrs.get(f as usize).cloned().unwrap_or_default();
            for k in row.keys() {
                *cover.entry(format!("nusamai:{k}")).or_default() += 1;
            }
            let gml_row = row
                .get("id")
                .and_then(|v| v.as_str())
                .and_then(|id| lods.get(id))
                .cloned()
                .unwrap_or_default();
            for (k, v) in &gml_row {
                *cover.entry(format!("gml:{k}")).or_default() += 1;
                if k == "storeysAboveGround" && v.as_i64() != Some(9999) {
                    *cover
                        .entry("gml:storeysAboveGround(known)".into())
                        .or_default() += 1;
                }
            }
            if let Some(l) = gml_row.get("lod") {
                let t = gml_row
                    .get("lodType")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                *lod_hist
                    .entry(format!("LOD{l} {t}").trim().to_string())
                    .or_default() += 1;
            }
            if let Some(u) = gml_row.get("usage").and_then(|v| v.as_str()) {
                let lbl = gml_row
                    .get("usageLabel")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                *usage_hist.entry(format!("{u} {lbl}")).or_default() += 1;
            }
            let mut s_row = Map::new();
            for k in KEEP_ATTRS {
                if let Some(v) = gml_row.get(*k).or_else(|| row.get(*k)) {
                    s_row.insert((*k).into(), v.clone());
                }
            }
            if !gml_row.is_empty() {
                row.insert("gml".into(), Value::Object(gml_row));
            }
            slim.push(Value::Object(s_row));
            full.push(Value::Object(row));
        }
        m.extras = json!({"typename": spec.name, "features": slim});
        report.insert(
            spec.name.clone(),
            json!({
                "mode": spec.mode,
                "source_features": s.attrs.len(),
                "features": remap_f.len(),
                "vertices": m.positions.len(),
                "triangles": m.indices.len() / 3,
                "attribute_coverage": cover,
                "lod_histogram": lod_hist,
                "usage_histogram": usage_hist,
                "load_ms": load_ms,
                "total_ms": t.elapsed().as_millis(),
                "attributes": full,
            }),
        );
        meshes.push(m);
    }
    let scene_extras = json!({
        "crs": "EPSG:6677 (JGD2011 / Japan Plane Rectangular CS IX) + JGD2011 vertical (T.P.) height",
        "chunk_min_easting": e0, "chunk_min_northing": n0, "chunk_size_m": size,
        "origin_easting": ec, "origin_northing": nc,
        "axes": "x = easting - origin_easting, y = orthometric height (m), z = -(northing - origin_northing)",
        "credit": CREDIT,
        "modifications": "Converted from CityGML with nusamai 0.1.19 (glTF sink, EPSG:6677, max LOD, textures dropped); clipped to this chunk; re-origined; attributes reduced; meshopt-compressed.",
    });
    let t_write = Instant::now();
    glb::write(&out_path, &meshes, scene_extras.clone())?;
    report.insert("scene".into(), scene_extras);
    report.insert("write_ms".into(), json!(t_write.elapsed().as_millis()));
    report.insert("total_ms".into(), json!(t_all.elapsed().as_millis()));
    std::fs::write(
        &meta_path,
        serde_json::to_string_pretty(&Value::Object(report.clone()))?,
    )?;
    // short summary on stdout (without the attribute dump)
    for (k, v) in report.iter_mut() {
        if let Some(o) = v.as_object_mut() {
            o.remove("attributes");
        }
        let _ = k;
    }
    println!("{}", serde_json::to_string_pretty(&Value::Object(report))?);
    Ok(())
}
