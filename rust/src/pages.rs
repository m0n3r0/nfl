//! Native fantasy pages — port of web/app.py's /team, /team/pin, /league,
//! /league/team/<name>, /cron routes. Same artifacts, same templates, same
//! fallback semantics (newest ok report, history roster fallback, 404).

use std::collections::HashMap;

use axum::{
    extract::{Form, Path, Query, State},
    http::{header, StatusCode},
    response::{Html, IntoResponse, Response},
};
use serde::Deserialize;
use serde_json::{json, Value};

use crate::{artifacts, pins, AppState};

/// The host crontab (docs/TEAM_OPERATOR.md is the authoritative runbook) —
/// kept in sync with web/app.py CRON_SCHEDULE.
const CRON_SCHEDULE: [(&str, &str, &str); 9] = [
    (
        "24 8,20 * * *",
        "twice daily 08:24 / 20:24",
        "team_operator.py — monitor + report",
    ),
    (
        "47 23 * * 0",
        "Sun 23:47",
        "team_operator.py --apply — lineup safety net",
    ),
    (
        "23 1 * * 1",
        "Mon 01:23",
        "team_operator.py --apply — final pre-kickoff set",
    ),
    (
        "11 20 * * 3",
        "Wed 20:11",
        "team_operator.py --waiver-scan --refresh-data",
    ),
    (
        "19 21 * * *",
        "nightly 21:19",
        "league_report.py --all-rosters --out --audit — league snapshot",
    ),
    (
        "5,35 8-13 * * 5",
        "Fri 08:05–13:35 (TNF)",
        "league_report.py --light — score refresh",
    ),
    (
        "5,35 2-13 * * 1",
        "Mon 02:05–13:35 (Sun slate)",
        "league_report.py --light — score refresh",
    ),
    (
        "5,35 8-13 * * 2",
        "Tue 08:05–13:35 (MNF)",
        "league_report.py --light — score refresh",
    ),
    (
        "37 9 * * 0",
        "Sun 09:37",
        "profile_backup.py — browser-profile backup",
    ),
];

fn render(st: &AppState, template: &str, ctx: Value) -> Response {
    match st.env.get_template(template).and_then(|t| t.render(ctx)) {
        Ok(html) => Html(html).into_response(),
        Err(e) => {
            tracing::error!("render {template}: {e}");
            (StatusCode::INTERNAL_SERVER_ERROR, "template render failed").into_response()
        }
    }
}

/// Shared /team context: newest runs, ok-fallback report, live pins.
/// A corrupt pin file is shown as a notice — the operator refuses to run
/// until it is fixed, so the page must say so loudly.
fn team_context(st: &AppState) -> Value {
    let runs = artifacts::read_operator_runs(&st.cfg.root, 200);
    let latest = runs.first().cloned().unwrap_or(Value::Null);
    let report = runs
        .iter()
        .find(|r| r.get("status").and_then(Value::as_str) == Some("ok"))
        .cloned()
        .unwrap_or(Value::Null);
    let (pins, pins_error) = match pins::load_pins(&pins::pins_path(&st.cfg.root)) {
        Ok(p) => (json!(p), Value::Null),
        Err(e) => (json!({}), Value::String(e.to_string())),
    };
    json!({"latest": latest, "report": report, "pins": pins, "pins_error": pins_error})
}

pub async fn team(State(st): State<AppState>) -> Response {
    render(&st, "team.html", team_context(&st))
}

#[derive(Deserialize)]
pub struct PinForm {
    yahoo_id: Option<String>,
    name: Option<String>,
}

/// Tick one player's pin on/off, then redirect (POST/redirect/GET).
/// On a corrupt pin file: refuse to overwrite it, re-render with the error
/// (409) — the user's protection must not be silently reset.
pub async fn pin_toggle(State(st): State<AppState>, Form(form): Form<PinForm>) -> Response {
    let yahoo_id = form.yahoo_id.unwrap_or_default().trim().to_string();
    let name = form.name.unwrap_or_default();
    if yahoo_id.is_empty() {
        return (StatusCode::BAD_REQUEST, "missing yahoo_id").into_response();
    }
    match pins::toggle_pin(&yahoo_id, &name, &pins::pins_path(&st.cfg.root)) {
        Ok(_) => (StatusCode::FOUND, [(header::LOCATION, "/team")]).into_response(),
        Err(e) => {
            let mut ctx = team_context(&st);
            ctx["pins_error"] = Value::String(e.to_string());
            (StatusCode::CONFLICT, render(&st, "team.html", ctx)).into_response()
        }
    }
}

pub async fn league(State(st): State<AppState>) -> Response {
    let report = artifacts::read_league_report(&st.cfg.root);
    let standings = report
        .as_ref()
        .and_then(|r| r.get("standings"))
        .filter(|v| v.is_array())
        .cloned()
        .unwrap_or(Value::Null);
    let matchup = report
        .as_ref()
        .and_then(|r| r.get("matchup"))
        .cloned()
        .unwrap_or(Value::Null);
    let my_name = matchup
        .as_object()
        .and_then(|m| m.get("team"))
        .cloned()
        .unwrap_or(Value::Null);
    let scoreboard = report
        .as_ref()
        .and_then(|r| r.get("scoreboard"))
        .filter(|v| {
            v.as_array()
                .map(|a| a.iter().all(Value::is_object))
                .unwrap_or(false)
        })
        .cloned()
        .unwrap_or(Value::Null);
    // Initials for the matchup avatars (minijinja strings have no .split();
    // the template falls back to the first letter when these are absent).
    let scoreboard = match scoreboard {
        Value::Array(entries) => Value::Array(
            entries
                .into_iter()
                .map(|mut e| {
                    if let Some(obj) = e.as_object_mut() {
                        for (team_key, out_key) in
                            [("team1", "t1_initials"), ("team2", "t2_initials")]
                        {
                            if let Some(name) = obj.get(team_key).and_then(Value::as_str) {
                                obj.insert(out_key.into(), Value::String(initials(name)));
                            }
                        }
                    }
                    e
                })
                .collect(),
        ),
        other => other,
    };
    let ctx = json!({"report": report.unwrap_or(Value::Null), "standings": standings,
                     "scoreboard": scoreboard, "my_name": my_name});
    render(&st, "league.html", ctx)
}

/// First letters of the first two words, uppercased ("Shiba Innu" -> "SI").
fn initials(name: &str) -> String {
    name.split_whitespace()
        .take(2)
        .filter_map(|w| w.chars().next())
        .flat_map(|c| c.to_uppercase())
        .collect()
}

/// One team's row in a standings list (exact name match), with PF/PA
/// coerced to finite floats at the boundary (port of _team_row).
fn team_row(standings: Option<&Value>, team_name: &str) -> Option<Value> {
    let rows = standings?.as_array()?;
    let row = rows
        .iter()
        .find(|r| r.is_object() && r.get("team").and_then(Value::as_str) == Some(team_name))?;
    let num = |key: &str| -> f64 {
        let v = match row.get(key) {
            None | Some(Value::Null) => return 0.0,
            Some(v) => v,
        };
        let f = match v {
            Value::Number(n) => n.as_f64().unwrap_or(0.0),
            Value::String(s) => s.trim().parse::<f64>().unwrap_or(0.0),
            Value::Bool(b) => {
                if *b {
                    1.0
                } else {
                    0.0
                }
            }
            _ => 0.0,
        };
        if f.is_finite() {
            f
        } else {
            0.0
        }
    };
    let mut out = row.as_object().cloned().unwrap_or_default();
    out.insert("points_for".into(), json!(num("points_for")));
    out.insert("points_against".into(), json!(num("points_against")));
    Some(Value::Object(out))
}

/// Games played from a 'W-L-T' record string (0 when unparseable).
fn record_games(record: &Value) -> i64 {
    let s = artifacts::as_display_string(Some(record));
    let parts: Vec<&str> = s.split('-').take(3).collect();
    let mut total = 0i64;
    for p in parts {
        match p.trim().parse::<i64>() {
            Ok(n) => total += n,
            Err(_) => return 0,
        }
    }
    total
}

pub async fn league_team(State(st): State<AppState>, Path(name): Path<String>) -> Response {
    let latest = artifacts::read_league_report(&st.cfg.root);
    let get = |k: &str| latest.as_ref().and_then(|r| r.get(k)).cloned();
    let row = team_row(get("standings").as_ref(), &name);
    let matchup = get("matchup").unwrap_or(Value::Null);
    let is_opponent = matchup.is_object()
        && matchup.get("opponent").and_then(Value::as_str) == Some(name.as_str());

    let mut roster: Option<Value> = None;
    let mut roster_date: Option<String> = None;
    if let Some(rosters) = get("rosters") {
        if let Some(r) = rosters.get(&name).filter(|v| v.is_array()) {
            roster = Some(r.clone());
        }
    }
    if roster.is_none() && is_opponent {
        roster = get("opponent_roster").filter(|v| v.is_array());
    }
    let history = artifacts::read_league_history(&st.cfg.root);
    if roster.is_none() {
        for snap in history.iter().rev() {
            if let Some(r) = snap
                .get("rosters")
                .and_then(|rs| rs.get(&name))
                .filter(|v| v.is_array())
            {
                roster = Some(r.clone());
                let captured = artifacts::as_display_string(snap.get("captured_at"));
                roster_date = Some(captured.chars().take(10).collect());
                break;
            }
        }
    }
    let mut trend: Vec<Value> = Vec::new();
    for snap in &history {
        if let Some(mut mine) = team_row(snap.get("standings"), &name) {
            let captured = artifacts::as_display_string(snap.get("captured_at"));
            mine.as_object_mut()
                .expect("team_row returns object")
                .insert("captured_at".into(), Value::String(captured));
            trend.push(mine);
        }
    }

    if row.is_none() && trend.is_empty() {
        let ctx = json!({"name": name, "row": Value::Null, "trend": [], "games": 0,
                         "matchup": Value::Null, "roster": Value::Null,
                         "roster_date": Value::Null, "captured_at": Value::Null});
        return (StatusCode::NOT_FOUND, render(&st, "league_team.html", ctx)).into_response();
    }
    let games = row
        .as_ref()
        .map(|r| record_games(r.get("record").unwrap_or(&Value::Null)))
        .unwrap_or(0);
    let ctx = json!({
        "name": name,
        "row": row.unwrap_or(Value::Null),
        "trend": trend,
        "games": games,
        "matchup": if is_opponent { matchup } else { Value::Null },
        "roster": roster.unwrap_or(Value::Null),
        "roster_date": roster_date.map(Value::String).unwrap_or(Value::Null),
        "captured_at": get("captured_at").unwrap_or(Value::Null),
    });
    render(&st, "league_team.html", ctx)
}

pub async fn cron(State(st): State<AppState>) -> Response {
    let runs = artifacts::read_operator_runs(&st.cfg.root, 14);
    let schedule: Vec<Value> = CRON_SCHEDULE
        .iter()
        .map(|(a, b, c)| json!([a, b, c]))
        .collect();
    let ctx = json!({"runs": runs, "schedule": schedule});
    render(&st, "cron.html", ctx)
}

// --- Team View: players side by side (Yahoo GameChannel method) ---

/// One player row entry. Our own team comes from the operator plan (has
/// projections); other teams from the league snapshot rosters (no proj).
struct TvEntry {
    name: String,
    team: String,
    slot: String,
    proj: Option<f64>,
    note: String,
}

impl TvEntry {
    fn to_json(&self) -> Value {
        json!({"name": self.name, "team": self.team, "slot": self.slot,
               "proj": self.proj, "note": self.note})
    }
}

fn tv_side(
    team: &str,
    my_name: Option<&str>,
    plan: Option<&Vec<Value>>,
    rosters: Option<&Value>,
) -> Option<Vec<TvEntry>> {
    if Some(team) == my_name {
        if let Some(plan) = plan {
            return Some(
                plan.iter()
                    .map(|p| TvEntry {
                        name: artifacts::as_display_string(p.get("name")),
                        team: String::new(),
                        slot: artifacts::as_display_string(p.get("current_slot")),
                        proj: p.get("proj_week").and_then(Value::as_f64),
                        note: artifacts::as_display_string(p.get("note")),
                    })
                    .collect(),
            );
        }
    }
    let rows = rosters?.get(team)?.as_array()?;
    Some(
        rows.iter()
            .map(|p| TvEntry {
                name: artifacts::as_display_string(p.get("name")),
                team: artifacts::as_display_string(p.get("team")),
                slot: artifacts::as_display_string(p.get("slot")),
                proj: None,
                note: artifacts::as_display_string(p.get("injury_status")),
            })
            .collect(),
    )
}

/// Align two sides by slot occurrence (QB vs QB, 1st RB vs 1st RB, ...),
/// starters first then bench/IR — Yahoo pairs rows around the Pos spine.
fn tv_rows(a: Option<&Vec<TvEntry>>, b: Option<&Vec<TvEntry>>) -> (Vec<Value>, Vec<Value>) {
    let empty: Vec<TvEntry> = Vec::new();
    let a = a.unwrap_or(&empty);
    let b = b.unwrap_or(&empty);
    let mut slots: Vec<String> = [
        "QB", "RB", "WR", "TE", "W/R/T", "K", "DEF", "BN", "IR", "IL",
    ]
    .iter()
    .map(|s| s.to_string())
    .collect();
    for e in a.iter().chain(b.iter()) {
        if !slots.contains(&e.slot) {
            slots.push(e.slot.clone());
        }
    }
    let (mut starters, mut bench) = (Vec::new(), Vec::new());
    for slot in &slots {
        let ga: Vec<&TvEntry> = a.iter().filter(|e| &e.slot == slot).collect();
        let gb: Vec<&TvEntry> = b.iter().filter(|e| &e.slot == slot).collect();
        for i in 0..ga.len().max(gb.len()) {
            let row = json!({
                "slot": slot,
                "left": ga.get(i).map(|e| e.to_json()).unwrap_or(Value::Null),
                "right": gb.get(i).map(|e| e.to_json()).unwrap_or(Value::Null),
            });
            if matches!(slot.as_str(), "BN" | "IR" | "IL") {
                bench.push(row);
            } else {
                starters.push(row);
            }
        }
    }
    (starters, bench)
}

/// /league/teamview?a=<team>&b=<team> — defaults to the current matchup.
pub async fn teamview(
    State(st): State<AppState>,
    Query(params): Query<HashMap<String, String>>,
) -> Response {
    let report = artifacts::read_league_report(&st.cfg.root);
    let matchup = report.as_ref().and_then(|r| r.get("matchup"));
    let my_name = matchup
        .and_then(|m| m.get("team"))
        .and_then(Value::as_str)
        .map(str::to_string);
    let a_name = params
        .get("a")
        .filter(|s| !s.trim().is_empty())
        .cloned()
        .or_else(|| my_name.clone())
        .unwrap_or_default();
    let b_name = params
        .get("b")
        .filter(|s| !s.trim().is_empty())
        .cloned()
        .or_else(|| {
            matchup
                .and_then(|m| m.get("opponent"))
                .and_then(Value::as_str)
                .map(str::to_string)
        })
        .unwrap_or_default();
    let week = matchup
        .and_then(|m| m.get("week"))
        .cloned()
        .unwrap_or(Value::Null);
    let rosters = report.as_ref().and_then(|r| r.get("rosters"));
    let runs = artifacts::read_operator_runs(&st.cfg.root, 200);
    let plan: Option<Vec<Value>> = runs
        .iter()
        .find(|r| r.get("status").and_then(Value::as_str) == Some("ok"))
        .and_then(|r| r.get("proposal"))
        .and_then(|p| p.get("plan"))
        .and_then(Value::as_array)
        .cloned();
    let a = tv_side(&a_name, my_name.as_deref(), plan.as_ref(), rosters);
    let b = tv_side(&b_name, my_name.as_deref(), plan.as_ref(), rosters);
    let missing = a.is_none() || b.is_none();
    let (starters, bench) = tv_rows(a.as_ref(), b.as_ref());
    let ctx = json!({
        "a_name": a_name, "b_name": b_name, "week": week,
        "starters": starters, "bench": bench, "missing": missing,
    });
    render(&st, "teamview.html", ctx)
}
