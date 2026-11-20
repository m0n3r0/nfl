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
use serde_json::{json, Map, Value};

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

/// Team name -> served logo path, for entries whose file exists on disk.
/// Cron (tools/logo_sync.py) owns the downloads; we only serve local files.
fn logo_urls(root: &std::path::Path) -> Map<String, Value> {
    let mut out = Map::new();
    if let Some(manifest) = artifacts::read_logo_manifest(root) {
        if let Some(obj) = manifest.as_object() {
            for (name, entry) in obj {
                if let Some(file) = entry.get("file").and_then(Value::as_str) {
                    if root.join("data/logos").join(file).is_file() {
                        out.insert(name.clone(), json!(format!("/logos/{file}")));
                    }
                }
            }
        }
    }
    out
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
                     "scoreboard": scoreboard, "my_name": my_name,
                     "logos": logo_urls(&st.cfg.root)});
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
                         "roster_date": Value::Null, "captured_at": Value::Null,
                         "logo": Value::Null});
        return (StatusCode::NOT_FOUND, render(&st, "league_team.html", ctx)).into_response();
    }
    let games = row
        .as_ref()
        .map(|r| record_games(r.get("record").unwrap_or(&Value::Null)))
        .unwrap_or(0);
    let logo = logo_urls(&st.cfg.root)
        .get(&name)
        .cloned()
        .unwrap_or(Value::Null);
    let ctx = json!({
        "name": name,
        "row": row.unwrap_or(Value::Null),
        "trend": trend,
        "games": games,
        "matchup": if is_opponent { matchup } else { Value::Null },
        "roster": roster.unwrap_or(Value::Null),
        "roster_date": roster_date.map(Value::String).unwrap_or(Value::Null),
        "captured_at": get("captured_at").unwrap_or(Value::Null),
        "logo": logo,
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
/// projections); other teams from the league snapshot rosters. Fan Pts and
/// game info come from the live-points artifact when its week matches.
struct TvEntry {
    name: String,
    team: String,
    position: String,
    slot: String,
    proj: Option<f64>,
    fan_pts: Option<f64>,
    note: String,
    game_info: String,
}

impl TvEntry {
    fn to_json(&self) -> Value {
        json!({"name": self.name, "team": self.team, "position": self.position,
               "slot": self.slot, "proj": self.proj, "fan_pts": self.fan_pts,
               "note": self.note, "game_info": self.game_info})
    }
    fn is_bench(&self) -> bool {
        matches!(self.slot.as_str(), "BN" | "IR" | "IL")
    }
}

/// ESPN<->Yahoo player-name normalization (mirrors src/live_scoring.py).
fn tv_norm_name(s: &str) -> String {
    let mut tokens: Vec<String> = s
        .to_lowercase()
        .chars()
        .map(|c| if c.is_ascii_alphanumeric() { c } else { ' ' })
        .collect::<String>()
        .split_whitespace()
        .map(str::to_string)
        .collect();
    while tokens
        .last()
        .map(|t| matches!(t.as_str(), "sr" | "jr" | "ii" | "iii" | "iv" | "v"))
        .unwrap_or(false)
    {
        tokens.pop();
    }
    tokens.join(" ")
}

/// Yahoo team abbr -> ESPN abbr (uppercase + the irregular ones).
fn tv_canon_team(abbr: &str) -> String {
    let up = abbr.trim().to_uppercase();
    match up.as_str() {
        "WAS" => "WSH".to_string(),
        "LA" | "ST" | "STL" => "LAR".to_string(),
        _ => up,
    }
}

struct TvGame {
    opp: String,
    date: String,
    state: String,
    home: bool,
}

/// team abbr -> this week's game, from the live artifact's games meta.
fn tv_team_games(live: Option<&Value>) -> HashMap<String, TvGame> {
    let mut out = HashMap::new();
    let games = match live.and_then(|l| l.get("games")).and_then(Value::as_object) {
        Some(g) => g,
        None => return out,
    };
    for g in games.values() {
        let teams = match g.get("teams").and_then(Value::as_object) {
            Some(t) => t,
            None => continue,
        };
        let abbrs: Vec<&String> = teams.keys().collect();
        for abbr in &abbrs {
            let opp = abbrs
                .iter()
                .find(|a| a != &abbr)
                .map(|a| a.to_string())
                .unwrap_or_default();
            out.insert(
                (*abbr).clone(),
                TvGame {
                    opp,
                    date: artifacts::as_display_string(g.get("date")),
                    state: artifacts::as_display_string(g.get("state")),
                    home: teams[*abbr]
                        .get("home")
                        .and_then(Value::as_bool)
                        .unwrap_or(false),
                },
            );
        }
    }
    out
}

/// "Sun 8:20 pm JST vs Min" / "Mon 9:25 am JST @ NYG" — host-local (JST),
/// honest about the zone. Empty when no live artifact covers the week.
fn tv_game_info(games: &HashMap<String, TvGame>, team: &str, has_live: bool) -> String {
    if team.trim().is_empty() || !has_live {
        return String::new();
    }
    match games.get(&tv_canon_team(team)) {
        None => "Bye".to_string(),
        Some(g) => {
            // ESPN dates come as "2026-11-22T18:00Z" (no seconds) — RFC3339
            // needs seconds, so try both shapes.
            let jst = chrono::FixedOffset::east_opt(9 * 3600).unwrap();
            let parsed = chrono::DateTime::parse_from_rfc3339(&g.date)
                .map(|dt| dt.with_timezone(&jst))
                .or_else(|_| {
                    chrono::NaiveDateTime::parse_from_str(&g.date, "%Y-%m-%dT%H:%MZ")
                        .map(|n| n.and_utc().with_timezone(&jst))
                });
            let when = parsed
                .map(|dt| {
                    dt.format("%a %I:%M %p")
                        .to_string()
                        .replace("AM", "am")
                        .replace("PM", "pm")
                        .replace(" 0", " ") // 12-hour without leading zero
                })
                .unwrap_or_default();
            let prefix = if g.home { "vs" } else { "@" };
            format!("{when} JST {prefix} {}", g.opp)
        }
    }
}

/// Live fan points maps, only when the artifact's week matches the page week.
fn tv_live_maps(
    live: Option<&Value>,
    week: &Value,
) -> (HashMap<String, f64>, HashMap<String, f64>, bool) {
    let mut players = HashMap::new();
    let mut defs = HashMap::new();
    let live_week = live.and_then(|l| l.get("week"));
    let matches = match (live_week, week) {
        (Some(lw), w) if !w.is_null() => lw == w,
        _ => false,
    };
    if !matches {
        return (players, defs, false);
    }
    let l = live.unwrap();
    if let Some(obj) = l.get("players").and_then(Value::as_object) {
        for (key, p) in obj {
            if let Some(pts) = p.get("points").and_then(Value::as_f64) {
                players.insert(key.clone(), pts);
            }
        }
    }
    if let Some(obj) = l.get("def_named").and_then(Value::as_object) {
        for (key, v) in obj {
            if let Some(pts) = v.as_f64() {
                defs.insert(key.clone(), pts);
            }
        }
    }
    (players, defs, true)
}

fn tv_side(
    team: &str,
    my_name: Option<&str>,
    plan: Option<&Vec<Value>>,
    rosters: Option<&Value>,
    live_players: &HashMap<String, f64>,
    live_defs: &HashMap<String, f64>,
    games: &HashMap<String, TvGame>,
    has_live: bool,
) -> Option<Vec<TvEntry>> {
    // roster lookup for NFL team/position (the operator plan lacks team)
    let roster_rows = rosters.and_then(|r| r.get(team)).and_then(Value::as_array);
    let roster_info: HashMap<String, (String, String)> = roster_rows
        .map(|rows| {
            rows.iter()
                .map(|p| {
                    (
                        tv_norm_name(&artifacts::as_display_string(p.get("name"))),
                        (
                            artifacts::as_display_string(p.get("team")),
                            artifacts::as_display_string(p.get("position")),
                        ),
                    )
                })
                .collect()
        })
        .unwrap_or_default();
    let fan_pts = |name: &str, slot: &str| -> Option<f64> {
        if slot == "DEF" {
            live_defs.get(name).copied()
        } else {
            live_players.get(&tv_norm_name(name)).copied()
        }
    };
    if Some(team) == my_name {
        if let Some(plan) = plan {
            return Some(
                plan.iter()
                    .map(|p| {
                        let name = artifacts::as_display_string(p.get("name"));
                        let slot = artifacts::as_display_string(p.get("current_slot"));
                        let (rteam, rpos) = roster_info
                            .get(&tv_norm_name(&name))
                            .cloned()
                            .unwrap_or_default();
                        let position = {
                            let pp = artifacts::as_display_string(p.get("position"));
                            if pp.is_empty() {
                                rpos
                            } else {
                                pp
                            }
                        };
                        TvEntry {
                            game_info: tv_game_info(games, &rteam, has_live),
                            team: rteam,
                            position,
                            fan_pts: fan_pts(&name, &slot),
                            name,
                            slot,
                            proj: p.get("proj_week").and_then(Value::as_f64),
                            note: artifacts::as_display_string(p.get("note")),
                        }
                    })
                    .collect(),
            );
        }
    }
    let rows = roster_rows?;
    Some(
        rows.iter()
            .map(|p| {
                let name = artifacts::as_display_string(p.get("name"));
                let team_abbr = artifacts::as_display_string(p.get("team"));
                let slot = artifacts::as_display_string(p.get("slot"));
                TvEntry {
                    game_info: tv_game_info(games, &team_abbr, has_live),
                    team: team_abbr,
                    position: artifacts::as_display_string(p.get("position")),
                    fan_pts: fan_pts(&name, &slot),
                    name,
                    slot,
                    // Yahoo "Proj Pts" captured by the nightly roster reads;
                    // null for bye players / older artifacts.
                    proj: p.get("proj").and_then(Value::as_f64),
                    note: artifacts::as_display_string(p.get("injury_status")),
                }
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
    let live = artifacts::read_live_points(&st.cfg.root);
    let (live_players, live_defs, has_live) = tv_live_maps(live.as_ref(), &week);
    let games = tv_team_games(live.as_ref());
    let a = tv_side(
        &a_name,
        my_name.as_deref(),
        plan.as_ref(),
        rosters,
        &live_players,
        &live_defs,
        &games,
        has_live,
    );
    let b = tv_side(
        &b_name,
        my_name.as_deref(),
        plan.as_ref(),
        rosters,
        &live_players,
        &live_defs,
        &games,
        has_live,
    );
    let missing = a.is_none() || b.is_none();
    let (starters, bench) = tv_rows(a.as_ref(), b.as_ref());

    // Header: records from standings, scores (live totals preferred, else
    // the Yahoo snapshot), starter projection sums, players remaining.
    let standings = report
        .as_ref()
        .and_then(|r| r.get("standings"))
        .and_then(Value::as_array);
    let record_of = |name: &str| -> String {
        standings
            .and_then(|rows| {
                rows.iter()
                    .find(|r| r.get("team").and_then(Value::as_str) == Some(name))
            })
            .map(|r| {
                format!(
                    "{} | #{}",
                    artifacts::as_display_string(r.get("record")),
                    artifacts::as_display_string(r.get("rank"))
                )
            })
            .unwrap_or_default()
    };
    let snapshot_score = |name: &str| -> Option<f64> {
        report
            .as_ref()?
            .get("scoreboard")?
            .as_array()?
            .iter()
            .find_map(|e| {
                if e.get("team1").and_then(Value::as_str) == Some(name) {
                    e.get("score1").and_then(Value::as_f64)
                } else if e.get("team2").and_then(Value::as_str) == Some(name) {
                    e.get("score2").and_then(Value::as_f64)
                } else {
                    None
                }
            })
    };
    let live_totals = live
        .as_ref()
        .and_then(|l| l.get("totals"))
        .filter(|_| has_live);
    let score_of = |name: &str| -> Value {
        live_totals
            .and_then(|t| t.get(name))
            .and_then(Value::as_f64)
            .map(|v| json!(v))
            .or_else(|| snapshot_score(name).map(|v| json!(v)))
            .unwrap_or(Value::Null)
    };
    let proj_sum = |side: &Option<Vec<TvEntry>>| -> Value {
        side.as_ref()
            .map(|entries| {
                let known: Vec<f64> = entries
                    .iter()
                    .filter(|e| !e.is_bench())
                    .filter_map(|e| e.proj)
                    .collect();
                if known.is_empty() {
                    Value::Null
                } else {
                    json!((known.iter().sum::<f64>() * 100.0).round() / 100.0)
                }
            })
            .unwrap_or(Value::Null)
    };
    let remaining = |side: &Option<Vec<TvEntry>>| -> Value {
        if !has_live {
            return Value::Null;
        }
        side.as_ref()
            .map(|entries| {
                let n = entries
                    .iter()
                    .filter(|e| !e.is_bench())
                    .filter(|e| {
                        games
                            .get(&tv_canon_team(&e.team))
                            .map(|g| g.state == "pre" || g.state == "in")
                            .unwrap_or(false)
                    })
                    .count();
                json!(n)
            })
            .unwrap_or(Value::Null)
    };
    let fan_sum = |side: &Option<Vec<TvEntry>>| -> Value {
        side.as_ref()
            .map(|entries| {
                let known: Vec<f64> = entries
                    .iter()
                    .filter(|e| !e.is_bench())
                    .filter_map(|e| e.fan_pts)
                    .collect();
                if known.is_empty() {
                    Value::Null
                } else {
                    json!((known.iter().sum::<f64>() * 100.0).round() / 100.0)
                }
            })
            .unwrap_or(Value::Null)
    };
    let ctx = json!({
        "a_name": a_name, "b_name": b_name, "week": week,
        "starters": starters, "bench": bench, "missing": missing,
        "logos": logo_urls(&st.cfg.root),
        "a_record": record_of(&a_name), "b_record": record_of(&b_name),
        "a_score": score_of(&a_name), "b_score": score_of(&b_name),
        "a_proj": proj_sum(&a), "b_proj": proj_sum(&b),
        "a_fan_total": fan_sum(&a), "b_fan_total": fan_sum(&b),
        "a_remaining": remaining(&a), "b_remaining": remaining(&b),
        "has_live": has_live,
    });
    render(&st, "teamview.html", ctx)
}
