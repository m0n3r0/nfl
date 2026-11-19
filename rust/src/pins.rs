//! Manual pin store — exact port of src/pins.py (same file, same shape,
//! same fail-closed contract). The Python operator reads data/pins.json;
//! both writers (this daemon and the Flask backend) serialize toggles with
//! an flock on data/pins.json.lock and persist atomically (tmp + rename).

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use fs2::FileExt;
use serde_json::{json, Value};

pub type Pins = BTreeMap<String, Value>;

#[derive(Debug)]
pub struct PinsError(pub String);

impl std::fmt::Display for PinsError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for PinsError {}

pub fn pins_path(root: &Path) -> PathBuf {
    root.join("data/pins.json")
}

/// Return {yahoo_id: {"name", "pinned_at"}}; missing file means no pins.
/// Any corruption is an error — callers must not fall back to an empty set
/// when the user's protection cannot be read.
pub fn load_pins(path: &Path) -> Result<Pins, PinsError> {
    let raw = match std::fs::read_to_string(path) {
        Ok(t) => t,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(Pins::new()),
        Err(e) => {
            return Err(PinsError(format!(
                "cannot read pin file {}: {e}",
                path.display()
            )))
        }
    };
    let data: Value = serde_json::from_str(&raw).map_err(|e| {
        PinsError(format!(
            "pin file {} is not valid JSON: {e}",
            path.display()
        ))
    })?;
    let pinned = data
        .get("pinned")
        .and_then(Value::as_object)
        .ok_or_else(|| {
            PinsError(format!(
                "pin file {} must be an object with a 'pinned' object",
                path.display()
            ))
        })?;
    let mut out = Pins::new();
    for (id, meta) in pinned {
        let ok = meta.is_object() && meta.get("name").map(Value::is_string).unwrap_or(false);
        if !ok {
            return Err(PinsError(format!(
                "pin file {} has a malformed entry: {id:?}",
                path.display()
            )));
        }
        out.insert(id.clone(), meta.clone());
    }
    Ok(out)
}

/// Atomically persist the pin set (tmp file + rename; readers never see a
/// partial write).
pub fn save_pins(pinned: &Pins, path: &Path) -> Result<(), PinsError> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)
            .map_err(|e| PinsError(format!("cannot create {}: {e}", parent.display())))?;
    }
    let map: serde_json::Map<String, Value> =
        pinned.iter().map(|(k, v)| (k.clone(), v.clone())).collect();
    let body =
        serde_json::to_string_pretty(&json!({ "pinned": map })).expect("pins serialize") + "\n";
    let tmp = path.with_file_name(format!(
        "{}.tmp",
        path.file_name().unwrap_or_default().to_string_lossy()
    ));
    std::fs::write(&tmp, body)
        .map_err(|e| PinsError(format!("cannot write {}: {e}", tmp.display())))?;
    std::fs::rename(&tmp, path)
        .map_err(|e| PinsError(format!("cannot rename into {}: {e}", path.display())))?;
    Ok(())
}

/// Flip one player's pin; returns the new state (true = pinned).
/// Serialized with an flock so concurrent toggles cannot lose an update.
pub fn toggle_pin(yahoo_id: &str, name: &str, path: &Path) -> Result<bool, PinsError> {
    let id = yahoo_id.trim();
    if id.is_empty() {
        return Err(PinsError("yahoo_id must be a non-empty string".into()));
    }
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)
            .map_err(|e| PinsError(format!("cannot create {}: {e}", parent.display())))?;
    }
    let lock_path = path.with_file_name(format!(
        "{}.lock",
        path.file_name().unwrap_or_default().to_string_lossy()
    ));
    let lock = std::fs::OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(false)
        .open(&lock_path)
        .map_err(|e| PinsError(format!("cannot open {}: {e}", lock_path.display())))?;
    lock.lock_exclusive()
        .map_err(|e| PinsError(format!("cannot lock {}: {e}", lock_path.display())))?;
    let result = (|| {
        let mut pinned = load_pins(path)?;
        let state = if pinned.contains_key(id) {
            pinned.remove(id);
            false
        } else {
            let display_name = if name.trim().is_empty() {
                id
            } else {
                name.trim()
            };
            pinned.insert(
                id.to_string(),
                json!({
                    "name": display_name,
                    "pinned_at": chrono::Utc::now()
                        .to_rfc3339_opts(chrono::SecondsFormat::Micros, false),
                }),
            );
            true
        };
        save_pins(&pinned, path)?;
        Ok(state)
    })();
    let _ = lock.unlock();
    result
}
