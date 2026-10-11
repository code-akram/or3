//! Minimal GLB (binary glTF 2.0) reader/writer: just enough to read nusamai's output
//! (interleaved float vertex buffer, u32 indices, EXT_structural_metadata property
//! tables) and to write a plain chunk GLB.

use anyhow::{bail, ensure, Context, Result};
use serde_json::{json, Map, Value};
use std::path::Path;

pub struct Glb {
    pub json: Value,
    pub bin: Vec<u8>,
}

const FLOAT: u64 = 5126;
const UNSIGNED_INT: u64 = 5125;
const UNSIGNED_SHORT: u64 = 5123;
const UNSIGNED_BYTE: u64 = 5121;

fn u32le(b: &[u8], o: usize) -> u32 {
    u32::from_le_bytes(b[o..o + 4].try_into().unwrap())
}

impl Glb {
    pub fn read(path: &Path) -> Result<Self> {
        let data = std::fs::read(path).with_context(|| format!("reading {}", path.display()))?;
        ensure!(data.len() >= 20 && &data[0..4] == b"glTF", "not a GLB file");
        ensure!(u32le(&data, 4) == 2, "unsupported glTF version");
        let total = u32le(&data, 8) as usize;
        ensure!(total <= data.len(), "truncated GLB");
        let mut off = 12;
        let mut json = None;
        let mut bin = Vec::new();
        while off + 8 <= total {
            let len = u32le(&data, off) as usize;
            let kind = &data[off + 4..off + 8];
            let body = &data[off + 8..off + 8 + len];
            match kind {
                b"JSON" => json = Some(serde_json::from_slice(body)?),
                b"BIN\0" => bin = body.to_vec(),
                _ => {}
            }
            off += 8 + len;
        }
        Ok(Glb {
            json: json.context("GLB has no JSON chunk")?,
            bin,
        })
    }

    fn get(&self, kind: &str, idx: u64) -> Result<&Value> {
        self.json[kind]
            .get(idx as usize)
            .with_context(|| format!("{kind}[{idx}] missing"))
    }

    pub fn view_bytes(&self, view: u64) -> Result<&[u8]> {
        let v = self.get("bufferViews", view)?;
        ensure!(
            v["buffer"].as_u64().unwrap_or(0) == 0,
            "only buffer 0 supported"
        );
        let off = v["byteOffset"].as_u64().unwrap_or(0) as usize;
        let len = v["byteLength"].as_u64().context("byteLength")? as usize;
        Ok(&self.bin[off..off + len])
    }

    /// Reads an accessor as f32 components (FLOAT only), flattened.
    pub fn accessor_f32(&self, idx: u64) -> Result<(Vec<f32>, usize)> {
        let a = self.get("accessors", idx)?;
        ensure!(
            a["componentType"].as_u64() == Some(FLOAT),
            "accessor {idx} is not FLOAT"
        );
        let ncomp = match a["type"].as_str() {
            Some("SCALAR") => 1,
            Some("VEC2") => 2,
            Some("VEC3") => 3,
            Some("VEC4") => 4,
            t => bail!("unsupported accessor type {t:?}"),
        };
        let count = a["count"].as_u64().context("count")? as usize;
        let view = a["bufferView"].as_u64().context("bufferView")?;
        let stride = self.get("bufferViews", view)?["byteStride"]
            .as_u64()
            .unwrap_or(4 * ncomp as u64) as usize;
        let base = a["byteOffset"].as_u64().unwrap_or(0) as usize;
        let bytes = self.view_bytes(view)?;
        let mut out = Vec::with_capacity(count * ncomp);
        for i in 0..count {
            for c in 0..ncomp {
                let o = base + i * stride + 4 * c;
                out.push(f32::from_le_bytes(bytes[o..o + 4].try_into().unwrap()));
            }
        }
        Ok((out, ncomp))
    }

    /// Reads an index accessor (u8/u16/u32) as u32.
    pub fn accessor_indices(&self, idx: u64) -> Result<Vec<u32>> {
        let a = self.get("accessors", idx)?;
        let count = a["count"].as_u64().context("count")? as usize;
        let view = a["bufferView"].as_u64().context("bufferView")?;
        let base = a["byteOffset"].as_u64().unwrap_or(0) as usize;
        let bytes = &self.view_bytes(view)?[base..];
        Ok(match a["componentType"].as_u64() {
            Some(UNSIGNED_INT) => (0..count).map(|i| u32le(bytes, 4 * i)).collect(),
            Some(UNSIGNED_SHORT) => (0..count)
                .map(|i| u16::from_le_bytes([bytes[2 * i], bytes[2 * i + 1]]) as u32)
                .collect(),
            Some(UNSIGNED_BYTE) => bytes[..count].iter().map(|&b| b as u32).collect(),
            t => bail!("unsupported index component type {t:?}"),
        })
    }

    /// Decodes EXT_structural_metadata property table `table` into one JSON object per
    /// feature. noData values (as declared in the class) are omitted.
    pub fn property_table(&self, table: usize) -> Result<Vec<Map<String, Value>>> {
        let ext = &self.json["extensions"]["EXT_structural_metadata"];
        let pt = ext["propertyTables"]
            .get(table)
            .context("no such property table")?;
        let class = pt["class"].as_str().context("class")?;
        let schema = &ext["schema"];
        let class_props = &schema["classes"][class]["properties"];
        let count = pt["count"].as_u64().context("count")? as usize;
        let mut rows = vec![Map::new(); count];
        let props = pt["properties"].as_object().context("properties")?;
        for (name, p) in props {
            let def = &class_props[name];
            let ty = def["type"].as_str().unwrap_or("");
            let comp = def["componentType"].as_str().unwrap_or("");
            let is_array = def["array"].as_bool().unwrap_or(false);
            let no_data = &def["noData"];
            let values = self.view_bytes(p["values"].as_u64().context("values")?)?;
            let offs = |key: &str| -> Result<Option<Vec<u32>>> {
                Ok(match p[key].as_u64() {
                    Some(v) => {
                        let b = self.view_bytes(v)?;
                        Some((0..b.len() / 4).map(|i| u32le(b, 4 * i)).collect())
                    }
                    None => None,
                })
            };
            let string_offsets = offs("stringOffsets")?;
            let array_offsets = offs("arrayOffsets")?;
            // nusamai 0.1.19 writes inconsistent offset tables for some properties
            // (array-typed in the schema, scalar in the data). Skip those, loudly.
            if is_array && array_offsets.as_ref().is_none_or(|a| a.len() != count + 1) {
                eprintln!(
                    "warning: property {name}: arrayOffsets has {} entries, expected {}; skipped",
                    array_offsets.as_ref().map_or(0, |a| a.len()),
                    count + 1
                );
                continue;
            }
            let enum_names: Vec<String> = if ty == "ENUM" {
                let e = def["enumType"].as_str().unwrap_or("");
                let mut names: Vec<String> = Vec::new();
                if let Some(vals) = schema["enums"][e]["values"].as_array() {
                    let max = vals
                        .iter()
                        .filter_map(|v| v["value"].as_u64())
                        .max()
                        .unwrap_or(0);
                    names = vec![String::new(); max as usize + 1];
                    for v in vals {
                        names[v["value"].as_u64().unwrap() as usize] =
                            v["name"].as_str().unwrap_or("").to_string();
                    }
                }
                names
            } else {
                vec![]
            };
            let elem = |i: usize| -> Value {
                match ty {
                    "STRING" => {
                        let so = string_offsets.as_ref().unwrap();
                        let s = &values[so[i] as usize..so[i + 1] as usize];
                        Value::String(String::from_utf8_lossy(s).into_owned())
                    }
                    "ENUM" => {
                        let v = u32le(values, 4 * i) as usize;
                        Value::String(enum_names.get(v).cloned().unwrap_or_default())
                    }
                    "SCALAR" => {
                        let b: [u8; 8] = values[8 * i..8 * i + 8].try_into().unwrap();
                        match comp {
                            "FLOAT64" => json!(f64::from_le_bytes(b)),
                            "INT64" => json!(i64::from_le_bytes(b)),
                            "UINT64" => json!(u64::from_le_bytes(b)),
                            _ => Value::Null,
                        }
                    }
                    _ => Value::Null,
                }
            };
            for (row, out) in rows.iter_mut().enumerate() {
                let v = if is_array {
                    let ao = array_offsets.as_ref().context("arrayOffsets")?;
                    let (a, b) = (ao[row] as usize, ao[row + 1] as usize);
                    let items: Vec<Value> = (a..b).map(elem).collect();
                    if items.is_empty() {
                        continue;
                    }
                    Value::Array(items)
                } else {
                    elem(row)
                };
                if &v == no_data || v == Value::Null {
                    continue;
                }
                if let Value::String(s) = &v {
                    if s.is_empty() {
                        continue;
                    }
                }
                out.insert(name.clone(), v);
            }
        }
        Ok(rows)
    }
}

/// One mesh to write: positions (xyz), normals (xyz), per-vertex feature ids, u32 indices.
pub struct OutMesh {
    pub name: String,
    pub color: [f32; 4],
    pub positions: Vec<[f32; 3]>,
    pub normals: Vec<[f32; 3]>,
    pub feature_ids: Vec<f32>,
    pub indices: Vec<u32>,
    pub extras: Value,
}

fn pad4(buf: &mut Vec<u8>, byte: u8) {
    while buf.len() % 4 != 0 {
        buf.push(byte);
    }
}

/// Writes a GLB with one node+mesh+material per OutMesh, all at the scene origin.
pub fn write(path: &Path, meshes: &[OutMesh], scene_extras: Value) -> Result<()> {
    let mut bin: Vec<u8> = Vec::new();
    let mut views = vec![];
    let mut accessors = vec![];
    let mut gl_meshes = vec![];
    let mut nodes = vec![];
    let mut materials = vec![];
    let mut push_view = |bin: &mut Vec<u8>, data: &[u8], target: u64| -> usize {
        pad4(bin, 0);
        let off = bin.len();
        bin.extend_from_slice(data);
        views.push(
            json!({"buffer": 0, "byteOffset": off, "byteLength": data.len(), "target": target}),
        );
        views.len() - 1
    };
    for (mi, m) in meshes.iter().enumerate() {
        if m.indices.is_empty() {
            continue;
        }
        let mut min = [f32::MAX; 3];
        let mut max = [f32::MIN; 3];
        let mut pbytes = Vec::with_capacity(m.positions.len() * 12);
        for p in &m.positions {
            for c in 0..3 {
                min[c] = min[c].min(p[c]);
                max[c] = max[c].max(p[c]);
                pbytes.extend_from_slice(&p[c].to_le_bytes());
            }
        }
        let nbytes: Vec<u8> = m
            .normals
            .iter()
            .flatten()
            .flat_map(|f| f.to_le_bytes())
            .collect();
        // feature ids stay f32 here: a tightly packed u16 scalar attribute would break the
        // 4-byte vertex-element alignment rule; meshopt re-packs it later anyway.
        let fbytes: Vec<u8> = m.feature_ids.iter().flat_map(|f| f.to_le_bytes()).collect();
        let ibytes: Vec<u8> = m.indices.iter().flat_map(|i| i.to_le_bytes()).collect();
        let vp = push_view(&mut bin, &pbytes, 34962);
        let vn = push_view(&mut bin, &nbytes, 34962);
        let vf = push_view(&mut bin, &fbytes, 34962);
        let vi = push_view(&mut bin, &ibytes, 34963);
        let n = m.positions.len();
        let a0 = accessors.len();
        accessors.push(json!({"bufferView": vp, "componentType": FLOAT, "count": n, "type": "VEC3", "min": min, "max": max}));
        accessors
            .push(json!({"bufferView": vn, "componentType": FLOAT, "count": n, "type": "VEC3"}));
        accessors
            .push(json!({"bufferView": vf, "componentType": FLOAT, "count": n, "type": "SCALAR"}));
        accessors.push(json!({"bufferView": vi, "componentType": UNSIGNED_INT, "count": m.indices.len(), "type": "SCALAR"}));
        materials.push(json!({
            "name": m.name,
            "pbrMetallicRoughness": {"baseColorFactor": m.color, "metallicFactor": 0.0, "roughnessFactor": 0.9},
            "doubleSided": true
        }));
        gl_meshes.push(json!({
            "name": m.name,
            "primitives": [{
                "attributes": {"POSITION": a0, "NORMAL": a0 + 1, "_FEATURE_ID_0": a0 + 2},
                "indices": a0 + 3,
                "material": materials.len() - 1,
                "mode": 4
            }],
            "extras": m.extras
        }));
        nodes.push(json!({"name": m.name, "mesh": gl_meshes.len() - 1}));
        let _ = mi;
    }
    pad4(&mut bin, 0);
    let root = json!({
        "asset": {"version": "2.0", "generator": "plateau-chunk"},
        "scene": 0,
        "scenes": [{"nodes": (0..nodes.len()).collect::<Vec<_>>(), "extras": scene_extras}],
        "nodes": nodes,
        "meshes": gl_meshes,
        "materials": materials,
        "accessors": accessors,
        "bufferViews": views,
        "buffers": [{"byteLength": bin.len()}]
    });
    let mut js = serde_json::to_vec(&root)?;
    pad4(&mut js, b' ');
    let total = 12 + 8 + js.len() + 8 + bin.len();
    let mut out = Vec::with_capacity(total);
    out.extend_from_slice(b"glTF");
    out.extend_from_slice(&2u32.to_le_bytes());
    out.extend_from_slice(&(total as u32).to_le_bytes());
    out.extend_from_slice(&(js.len() as u32).to_le_bytes());
    out.extend_from_slice(b"JSON");
    out.extend_from_slice(&js);
    out.extend_from_slice(&(bin.len() as u32).to_le_bytes());
    out.extend_from_slice(b"BIN\0");
    out.extend_from_slice(&bin);
    std::fs::write(path, out)?;
    Ok(())
}
