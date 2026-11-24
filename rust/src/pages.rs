//! Native fantasy pages (originally ported from the retired Flask backend's
//! /team, /team/pin, /league, /league/team/<name>, /cron routes). Same
//! artifacts, same templates, same fallback semantics (newest ok report,
//! history roster fallback, 404).

use std::collections::HashMap;

use axum::{
    extract::{Form, Path, Query, State},
    http::{header, StatusCode},
    response::{Html, IntoResponse, Response},
};
use serde::Deserialize;
use serde_json::{json, Map, Value};

use crate::{artifacts, pins, AppState};

/// The host crontab (docs/TEAM_OPERATOR.md is the authoritative runbook),
/// mirrored here for the /cron page — update both when the crontab changes.
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

pub(crate) fn render(st: &AppState, template: &str, ctx: Value) -> Response {
    match st.env.get_template(template).and_then(|t| t.render(ctx)) {
        Ok(html) => Html(html).into_response(),
        Err(e) => {
            tracing::error!("render {template}: {e}");
            (StatusCode::INTERNAL_SERVER_ERROR, "template render failed").into_response()
        }
    }
}

/// All league team names from a snapshot: standings order, or sorted roster
/// keys when standings are absent. The team picker and the matchup page both
/// need this list — one place keeps them consistent.
fn team_names(report: Option<&Value>) -> Vec<String> {
    let from_standings: Vec<String> = report
        .and_then(|r| r.get("standings"))
        .and_then(Value::as_array)
        .map(|rows| {
            rows.iter()
                .filter_map(|r| r.get("team").and_then(Value::as_str).map(str::to_string))
                .collect()
        })
        .unwrap_or_default();
    if !from_standings.is_empty() {
        return from_standings;
    }
    let mut names: Vec<String> = report
        .and_then(|r| r.get("rosters"))
        .and_then(Value::as_object)
        .map(|o| o.keys().cloned().collect())
        .unwrap_or_default();
    names.sort();
    names
}

/// On-page team picker data (the top nav stays plain links): every league
/// team, plus which one is currently shown so the select marks it selected.
fn add_team_picker(st: &AppState, ctx: &mut Value, current: &str) {
    let teams = team_names(artifacts::read_league_report(&st.cfg.root).as_ref());
    if let Some(obj) = ctx.as_object_mut() {
        obj.insert("picker_teams".into(), json!(teams));
        obj.insert("picker_current".into(), json!(current));
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
    let my = report
        .get("matchup")
        .and_then(|m| m.get("team"))
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    let mut ctx =
        json!({"latest": latest, "report": report, "pins": pins, "pins_error": pins_error});
    add_team_picker(st, &mut ctx, &my);
    ctx
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
            Value::Bool(b) => f64::from(*b),
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
        let mut ctx = json!({"name": name, "row": Value::Null, "trend": [], "games": 0,
                             "matchup": Value::Null, "roster": Value::Null,
                             "roster_date": Value::Null, "captured_at": Value::Null,
                             "logo": Value::Null});
        add_team_picker(&st, &mut ctx, &name);
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
    let mut ctx = json!({
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
    add_team_picker(&st, &mut ctx, &name);
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

// --- Matchup: players side by side (Yahoo GameChannel method) ---

/// One player row entry. Our own team comes from the operator plan (has
/// projections); other teams from the league snapshot rosters. Fan Pts and
/// game info come from the live-points artifact when its week matches.
struct MatchupEntry {
    name: String,
    team: String,
    position: String,
    slot: String,
    proj: Option<f64>,
    fan_pts: Option<f64>,
    note: String,
    game_info: String,
}

impl MatchupEntry {
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
fn matchup_norm_name(s: &str) -> String {
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

/// NFL team identifiers -> ESPN abbrs. Yahoo shows a DEF as its nickname
/// ("Bears"), its city/state ("Chicago", "Minnesota"), or a full "City
/// Nickname" with a "D/ST" suffix — the capture page varies run to run, and
/// historical plan rows may carry no team at all. This resolves their
/// points/game info from the name alone. Static league facts, not fantasy
/// data.
pub(crate) fn matchup_def_abbr(name: &str) -> Option<&'static str> {
    let norm = name.trim().to_lowercase();
    let norm = norm
        .strip_suffix("d/st")
        .map(str::trim_end)
        .unwrap_or(&norm);
    // Shared-prefix cities resolve on the full name only — "New York"/"Los
    // Angeles" host two teams each, so a first-token match would be a guess.
    match norm {
        "new england" | "new england patriots" => return Some("NE"),
        "new orleans" | "new orleans saints" => return Some("NO"),
        "new york giants" => return Some("NYG"),
        "new york jets" => return Some("NYJ"),
        "los angeles rams" => return Some("LAR"),
        "los angeles chargers" => return Some("LAC"),
        _ => {}
    }
    let first = norm.split_whitespace().next()?;
    Some(match first {
        "cardinals" | "arizona" => "ARI",
        "falcons" | "atlanta" => "ATL",
        "ravens" | "baltimore" => "BAL",
        "bills" | "buffalo" => "BUF",
        "panthers" | "carolina" => "CAR",
        "bears" | "chicago" => "CHI",
        "bengals" | "cincinnati" => "CIN",
        "browns" | "cleveland" => "CLE",
        "cowboys" | "dallas" => "DAL",
        "broncos" | "denver" => "DEN",
        "lions" | "detroit" => "DET",
        "packers" | "green" => "GB",
        "texans" | "houston" => "HOU",
        "colts" | "indianapolis" => "IND",
        "jaguars" | "jacksonville" => "JAX",
        "chiefs" | "kansas" => "KC",
        "raiders" | "las" => "LV",
        "chargers" => "LAC",
        "rams" => "LAR",
        "dolphins" | "miami" => "MIA",
        "vikings" | "minnesota" => "MIN",
        "patriots" => "NE",
        "saints" => "NO",
        "giants" => "NYG",
        "jets" => "NYJ",
        "eagles" | "philadelphia" => "PHI",
        "steelers" | "pittsburgh" => "PIT",
        "49ers" | "san" => "SF",
        "seahawks" | "seattle" => "SEA",
        "buccaneers" | "tampa" => "TB",
        "titans" | "tennessee" => "TEN",
        "commanders" | "washington" => "WSH",
        _ => return None,
    })
}

/// Yahoo team abbr -> ESPN abbr (uppercase + the irregular ones).
fn matchup_canon_team(abbr: &str) -> String {
    let up = abbr.trim().to_uppercase();
    match up.as_str() {
        "WAS" => "WSH".to_string(),
        "LA" | "ST" | "STL" => "LAR".to_string(),
        _ => up,
    }
}

struct MatchupGame {
    opp: String,
    date: String,
    state: String,
    home: bool,
}

/// team abbr -> this week's game, from the live artifact's games meta.
fn matchup_team_games(live: Option<&Value>) -> HashMap<String, MatchupGame> {
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
                MatchupGame {
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
fn matchup_game_info(games: &HashMap<String, MatchupGame>, team: &str, has_live: bool) -> String {
    if team.trim().is_empty() || !has_live {
        return String::new();
    }
    match games.get(&matchup_canon_team(team)) {
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

/// Live fan points maps, populated only when the artifact's week matches
/// the page week (has_live=false otherwise). DEF points are keyed both by
/// Yahoo roster name (def_named) and by ESPN abbr (def map) — historical
/// weeks need the abbr path because def_named reflects the roster at
/// capture time, not the historical one.
#[derive(Default)]
struct MatchupLiveMaps {
    players: HashMap<String, f64>,
    defs: HashMap<String, f64>,
    defs_abbr: HashMap<String, f64>,
    has_live: bool,
}

fn matchup_live_maps(live: Option<&Value>, week: &Value) -> MatchupLiveMaps {
    let mut out = MatchupLiveMaps::default();
    let live_week = live.and_then(|l| l.get("week"));
    let matches = match (live_week, week) {
        (Some(lw), w) if !w.is_null() => lw == w,
        _ => false,
    };
    if !matches {
        return out;
    }
    let Some(l) = live else {
        return out; // no live artifact → has_live stays false
    };
    if let Some(obj) = l.get("players").and_then(Value::as_object) {
        for (key, p) in obj {
            if let Some(pts) = p.get("points").and_then(Value::as_f64) {
                out.players.insert(key.clone(), pts);
            }
        }
    }
    if let Some(obj) = l.get("def_named").and_then(Value::as_object) {
        for (key, v) in obj {
            if let Some(pts) = v.as_f64() {
                out.defs.insert(key.clone(), pts);
            }
        }
    }
    if let Some(obj) = l.get("def").and_then(Value::as_object) {
        for (key, v) in obj {
            if let (Some(abbr), Some(pts)) = (key.strip_prefix("DEF:"), v.as_f64()) {
                out.defs_abbr.insert(abbr.to_string(), pts);
            }
        }
    }
    out.has_live = true;
    out
}

fn matchup_side(
    team: &str,
    my_name: Option<&str>,
    plan: Option<&Vec<Value>>,
    rosters: Option<&Value>,
    fallback_rosters: Option<&Value>,
    live: &MatchupLiveMaps,
    games: &HashMap<String, MatchupGame>,
) -> Option<Vec<MatchupEntry>> {
    // roster lookup for NFL team/position (the operator plan lacks team)
    let roster_rows = rosters.and_then(|r| r.get(team)).and_then(Value::as_array);
    let build_info = |src: Option<&Value>| -> HashMap<String, (String, String)> {
        src.and_then(|r| r.get(team))
            .and_then(Value::as_array)
            .map(|rows| {
                rows.iter()
                    .map(|p| {
                        (
                            matchup_norm_name(&artifacts::as_display_string(p.get("name"))),
                            (
                                artifacts::as_display_string(p.get("team")),
                                artifacts::as_display_string(p.get("position")),
                            ),
                        )
                    })
                    .collect()
            })
            .unwrap_or_default()
    };
    let mut roster_info = build_info(rosters);
    if roster_info.is_empty() {
        // Historical snapshots predate own-roster capture: borrow team/pos
        // from the CURRENT roster (points/game info stay week-archived).
        roster_info = build_info(fallback_rosters);
    }
    let fan_pts = |name: &str, slot: &str, team_abbr: &str| -> Option<f64> {
        if slot == "DEF" {
            live.defs
                .get(name)
                .or_else(|| live.defs_abbr.get(&matchup_canon_team(team_abbr)))
                .or_else(|| matchup_def_abbr(name).and_then(|a| live.defs_abbr.get(a)))
                .copied()
        } else {
            live.players.get(&matchup_norm_name(name)).copied()
        }
    };
    if Some(team) == my_name {
        if let Some(plan) = plan {
            return Some(
                plan.iter()
                    .map(|p| {
                        let name = artifacts::as_display_string(p.get("name"));
                        let slot = artifacts::as_display_string(p.get("current_slot"));
                        let (mut rteam, rpos) = roster_info
                            .get(&matchup_norm_name(&name))
                            .cloned()
                            .unwrap_or_default();
                        if slot == "DEF" && rteam.is_empty() {
                            // Historical plan rows can lack a team (the
                            // snapshot roster changed after the week) —
                            // the DEF nickname resolves it.
                            rteam = matchup_def_abbr(&name).unwrap_or("").to_string();
                        }
                        let position = {
                            let pp = artifacts::as_display_string(p.get("position"));
                            if pp.is_empty() {
                                rpos
                            } else {
                                pp
                            }
                        };
                        let fp = fan_pts(&name, &slot, &rteam);
                        MatchupEntry {
                            game_info: matchup_game_info(games, &rteam, live.has_live),
                            team: rteam,
                            position,
                            fan_pts: fp,
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
                let fp = fan_pts(&name, &slot, &team_abbr);
                MatchupEntry {
                    game_info: matchup_game_info(games, &team_abbr, live.has_live),
                    team: team_abbr,
                    position: artifacts::as_display_string(p.get("position")),
                    fan_pts: fp,
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
fn matchup_rows(
    a: Option<&Vec<MatchupEntry>>,
    b: Option<&Vec<MatchupEntry>>,
) -> (Vec<Value>, Vec<Value>) {
    let empty: Vec<MatchupEntry> = Vec::new();
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
        let ga: Vec<&MatchupEntry> = a.iter().filter(|e| &e.slot == slot).collect();
        let gb: Vec<&MatchupEntry> = b.iter().filter(|e| &e.slot == slot).collect();
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

/// The week a snapshot belongs to: the scoreboard's week is authoritative
/// (the matchup page can lag across the week boundary).
fn snapshot_week(r: &Value) -> Option<i64> {
    r.get("scoreboard")
        .and_then(Value::as_array)
        .and_then(|a| a.first())
        .and_then(|e| e.get("week"))
        .and_then(Value::as_i64)
        .or_else(|| {
            r.get("matchup")
                .and_then(|m| m.get("week"))
                .and_then(Value::as_i64)
        })
}

/// Sum one optional field over the non-bench players of a Matchup side,
/// rounded to 2dp; Null when no player has that field (never a fake 0).
fn side_sum(
    side: &Option<Vec<MatchupEntry>>,
    field: impl Fn(&MatchupEntry) -> Option<f64>,
) -> Value {
    let known: Vec<f64> = side
        .as_ref()
        .map(|entries| {
            entries
                .iter()
                .filter(|e| !e.is_bench())
                .filter_map(&field)
                .collect()
        })
        .unwrap_or_default();
    if known.is_empty() {
        Value::Null
    } else {
        json!((known.iter().sum::<f64>() * 100.0).round() / 100.0)
    }
}

/// Pick the snapshot for a past week: the newest one WITH rosters supplies
/// the rosters (late light runs drop them), the newest overall supplies the
/// FINAL scoreboard/standings (the with-rosters run is mid-week).
fn past_week_snapshot(hist: &[Value], week: i64) -> Option<Value> {
    let in_week: Vec<&Value> = hist
        .iter()
        .filter(|r| snapshot_week(r) == Some(week))
        .collect();
    let captured = |r: &Value| artifacts::as_display_string(r.get("captured_at"));
    let latest_any = in_week.iter().max_by_key(|r| captured(r)).copied();
    let latest_rosters = in_week
        .iter()
        .filter(|r| {
            r.get("rosters")
                .and_then(Value::as_object)
                .map(|o| !o.is_empty())
                .unwrap_or(false)
        })
        .max_by_key(|r| captured(r))
        .copied();
    match (latest_rosters, latest_any) {
        (Some(base), Some(final_scores)) => {
            let mut merged = base.clone();
            for key in ["scoreboard", "standings"] {
                if let Some(v) = final_scores.get(key) {
                    merged[key] = v.clone();
                }
            }
            Some(merged)
        }
        (Some(base), None) => Some(base.clone()),
        (None, other) => other.cloned(),
    }
}

/// The operator plan to show alongside a side: for a past week the run must
/// be from that week; for the current week the newest verified run wins.
fn operator_plan(runs: &[Value], week: Option<i64>) -> Option<Vec<Value>> {
    runs.iter()
        .find(|r| {
            r.get("status").and_then(Value::as_str) == Some("ok")
                && match week {
                    Some(w) => r.get("week").and_then(Value::as_i64) == Some(w),
                    None => true,
                }
        })
        .and_then(|r| r.get("proposal"))
        .and_then(|p| p.get("plan"))
        .and_then(Value::as_array)
        .cloned()
}

/// /league/matchup — defaults to our own matchup (query a= still accepted
/// for old bookmarks). The opponent is ALWAYS the team's scheduled opponent
/// from that week's scoreboard (no dropdown, b= is ignored).
pub async fn matchup(
    State(st): State<AppState>,
    Query(params): Query<HashMap<String, String>>,
) -> Response {
    matchup_for(st, params, None).await
}

/// /league/matchup/<team> — the card's clean click target: the selected
/// team is a path segment, no query string. Opponent comes from the schedule.
pub async fn matchup_named(
    State(st): State<AppState>,
    Path(team): Path<String>,
    Query(params): Query<HashMap<String, String>>,
) -> Response {
    matchup_for(st, params, Some(team)).await
}

/// Shared implementation for both the path and legacy-query routes.
async fn matchup_for(
    st: AppState,
    params: HashMap<String, String>,
    path_team: Option<String>,
) -> Response {
    let current = artifacts::read_league_report(&st.cfg.root);
    // The scoreboard's week is authoritative — the matchup page can lag
    // across the week boundary (see snapshot_week).
    let current_week = current.as_ref().and_then(snapshot_week).unwrap_or(0);
    // NFL weeks are 1..=18 and only weeks <= current can have snapshots;
    // anything else falls back to the current week. The bound also keeps
    // the week-selector allocation below from being user-controlled.
    let requested: Option<i64> = params
        .get("week")
        .and_then(|s| s.trim().parse().ok())
        .filter(|&w| w >= 1 && w <= current_week.min(18));
    let is_past = requested.map(|w| w != current_week).unwrap_or(false);
    let (report, live, plan_week) = if let Some(w) = requested.filter(|_| is_past) {
        (
            past_week_snapshot(&artifacts::read_league_history(&st.cfg.root), w),
            artifacts::read_live_points_week(&st.cfg.root, w),
            Some(w),
        )
    } else {
        (
            current.clone(),
            artifacts::read_live_points(&st.cfg.root),
            None,
        )
    };
    let matchup = report.as_ref().and_then(|r| r.get("matchup"));
    let my_name = matchup
        .and_then(|m| m.get("team"))
        .and_then(Value::as_str)
        .map(str::to_string);
    let a_name = path_team
        .filter(|s| !s.trim().is_empty())
        .or_else(|| params.get("a").filter(|s| !s.trim().is_empty()).cloned())
        .or_else(|| my_name.clone())
        .unwrap_or_default();
    // b defaults to team a's OPPONENT in this week's scoreboard — not to
    // our own matchup's opponent (that would snap back to our team when
    // browsing another team's history).
    let sb_rows = report
        .as_ref()
        .and_then(|r| r.get("scoreboard"))
        .and_then(Value::as_array);
    let opponent_of = |name: &str| -> Option<String> {
        sb_rows.and_then(|rows| {
            rows.iter().find_map(|e| {
                let t1 = e.get("team1").and_then(Value::as_str)?;
                let t2 = e.get("team2").and_then(Value::as_str)?;
                if t1 == name {
                    Some(t2.to_string())
                } else if t2 == name {
                    Some(t1.to_string())
                } else {
                    None
                }
            })
        })
    };
    // The opponent is ALWAYS fixed by this week's schedule, past or current.
    // An arbitrary b param (left over from the team picker) must never
    // override it — there is no opponent dropdown, so a stale b can't pair
    // a team with the previous selection's opponent.
    let b_name = opponent_of(&a_name)
        .or_else(|| {
            if Some(a_name.as_str()) == my_name.as_deref() {
                matchup
                    .and_then(|m| m.get("opponent"))
                    .and_then(Value::as_str)
                    .map(str::to_string)
            } else {
                None
            }
        })
        .unwrap_or_default();
    // Week shown in the header: the explicit past week, else the current
    // one; Null only when no snapshot has established a week yet.
    let week = match requested.filter(|_| is_past) {
        Some(w) => json!(w),
        None if current_week > 0 => json!(current_week),
        None => Value::Null,
    };
    let rosters = report.as_ref().and_then(|r| r.get("rosters"));
    let plan = operator_plan(&artifacts::read_operator_runs(&st.cfg.root, 200), plan_week);
    let live_maps = matchup_live_maps(live.as_ref(), &week);
    let games = matchup_team_games(live.as_ref());
    let current_rosters = current.as_ref().and_then(|r| r.get("rosters"));
    let a = matchup_side(
        &a_name,
        my_name.as_deref(),
        plan.as_ref(),
        rosters,
        current_rosters,
        &live_maps,
        &games,
    );
    let b = matchup_side(
        &b_name,
        my_name.as_deref(),
        plan.as_ref(),
        rosters,
        current_rosters,
        &live_maps,
        &games,
    );
    let missing = a.is_none() || b.is_none();
    let (starters, bench) = matchup_rows(a.as_ref(), b.as_ref());

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
    // Past weeks: Yahoo's official final (snapshot) outranks our recomputed
    // archive sum; current week: live totals preferred.
    let live_totals = live
        .as_ref()
        .and_then(|l| l.get("totals"))
        .filter(|_| live_maps.has_live && !is_past);
    let score_of = |name: &str| -> Value {
        live_totals
            .and_then(|t| t.get(name))
            .and_then(Value::as_f64)
            .map(|v| json!(v))
            .or_else(|| snapshot_score(name).map(|v| json!(v)))
            .unwrap_or(Value::Null)
    };
    let proj_sum = |side: &Option<Vec<MatchupEntry>>| side_sum(side, |e| e.proj);
    let remaining = |side: &Option<Vec<MatchupEntry>>| -> Value {
        if !live_maps.has_live {
            return Value::Null;
        }
        side.as_ref()
            .map(|entries| {
                let n = entries
                    .iter()
                    .filter(|e| !e.is_bench())
                    .filter(|e| {
                        games
                            .get(&matchup_canon_team(&e.team))
                            .map(|g| g.state == "pre" || g.state == "in")
                            .unwrap_or(false)
                    })
                    .count();
                json!(n)
            })
            .unwrap_or(Value::Null)
    };
    let fan_sum = |side: &Option<Vec<MatchupEntry>>| side_sum(side, |e| e.fan_pts);
    let max_week = current_week.clamp(0, 18);
    let weeks: Vec<i64> = (1..=max_week).collect();
    let teams = team_names(report.as_ref());
    let ctx = json!({
        "a_name": a_name, "b_name": b_name, "week": week,
        "starters": starters, "bench": bench, "missing": missing,
        "logos": logo_urls(&st.cfg.root),
        "a_record": record_of(&a_name), "b_record": record_of(&b_name),
        "a_score": score_of(&a_name), "b_score": score_of(&b_name),
        "a_proj": proj_sum(&a), "b_proj": proj_sum(&b),
        "a_fan_total": fan_sum(&a), "b_fan_total": fan_sum(&b),
        "a_remaining": remaining(&a), "b_remaining": remaining(&b),
        "has_live": live_maps.has_live, "is_past": is_past, "weeks": weeks,
        "teams": teams,
    });
    render(&st, "matchup.html", ctx)
}
