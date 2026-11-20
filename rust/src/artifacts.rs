//! Local artifact readers — port of web/app.py's _read_operator_runs /
//! _read_league_report / _read_league_history. The web layer reads LOCAL
//! artifacts only; live Yahoo reads belong to the WAF-aware cron jobs.

use std::path::Path;

use serde_json::Value;

/// Parse the operator audit log, newest first; non-dict/broken lines skipped.
/// Normalizes proposal.moves/plan at the artifact boundary so templates
/// never see a non-list (a corrupted record must not 500 the page).
/// Invalid UTF-8 is replaced, not fatal (parity with the old Python reader).
pub fn read_operator_runs(root: &Path, limit: usize) -> Vec<Value> {
    let path = root.join("logs/team-operator.jsonl");
    let bytes = match std::fs::read(&path) {
        Ok(b) => b,
        Err(_) => return Vec::new(),
    };
    let text = String::from_utf8_lossy(&bytes);
    let mut runs = Vec::new();
    for line in text.lines().rev() {
        let Ok(mut record) = serde_json::from_str::<Value>(line) else {
            continue;
        };
        if !record.is_object() {
            continue;
        }
        if let Some(proposal) = record.get_mut("proposal").and_then(Value::as_object_mut) {
            if !proposal.get("moves").map(Value::is_array).unwrap_or(false) {
                proposal.insert("moves".into(), Value::Array(Vec::new()));
            }
            if !matches!(
                proposal.get("plan"),
                Some(Value::Array(_)) | Some(Value::Null) | None
            ) {
                proposal.insert("plan".into(), Value::Null);
            }
        }
        runs.push(record);
        if runs.len() >= limit {
            break;
        }
    }
    runs
}

/// Latest persisted league snapshot, or None when absent/invalid.
pub fn read_league_report(root: &Path) -> Option<Value> {
    let text = std::fs::read_to_string(root.join("logs/league-report.json")).ok()?;
    let report: Value = serde_json::from_str(&text).ok()?;
    report.is_object().then_some(report)
}

/// The season's nightly league snapshots, oldest first.
pub fn read_league_history(root: &Path) -> Vec<Value> {
    let Ok(bytes) = std::fs::read(root.join("logs/league-report.jsonl")) else {
        return Vec::new();
    };
    let text = String::from_utf8_lossy(&bytes);
    text.lines()
        .filter_map(|l| serde_json::from_str::<Value>(l).ok())
        .filter(Value::is_object)
        .collect()
}

/// Team logo manifest (data/logos.json, written by tools/logo_sync.py via
/// cron). Maps team name -> {id, url, file, fetched_at}; None when absent
/// or invalid — logos are decorative, never fatal.
pub fn read_logo_manifest(root: &Path) -> Option<Value> {
    let text = std::fs::read_to_string(root.join("data/logos.json")).ok()?;
    let manifest: Value = serde_json::from_str(&text).ok()?;
    manifest.is_object().then_some(manifest)
}

/// Live points artifact (logs/live-points.json, written by the ESPN poller).
/// None when absent/invalid — pages fall back to snapshot data.
pub fn read_live_points(root: &Path) -> Option<Value> {
    let text = std::fs::read_to_string(root.join("logs/live-points.json")).ok()?;
    serde_json::from_str(&text).ok()
}

/// A completed week's archived finals (logs/live-points-week-<N>.json,
/// written by the poller once every game of the week is final).
pub fn read_live_points_week(root: &Path, week: i64) -> Option<Value> {
    let path = root.join(format!("logs/live-points-week-{week}.json"));
    let text = std::fs::read_to_string(path).ok()?;
    serde_json::from_str(&text).ok()
}

/// JSON value -> display string the way Python str() would for the artifact
/// fields we slice (captured_at): strings verbatim, null -> "", else JSON.
pub fn as_display_string(v: Option<&Value>) -> String {
    match v {
        Some(Value::String(s)) => s.clone(),
        Some(Value::Null) | None => String::new(),
        Some(other) => other.to_string(),
    }
}
