//! Native analytics pages — the FD nation method applied to the prediction
//! engine: Python computes OFFLINE (tools/predictions_report.py writes
//! data/web/*.json), axum + minijinja serve straight from those artifacts.
//! No Flask, nothing computed in the request path. Missing artifacts render
//! an honest notice, never a stale or fabricated number.

use std::collections::HashMap;

use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use serde_json::{json, Value};

use crate::{artifacts, pages, safe_segment, AppState};

fn missing(st: &AppState, page: &str) -> Response {
    pages::render(st, "analytics_missing.html", json!({"page": page}))
}

fn arr(v: Option<&Value>) -> Vec<Value> {
    v.and_then(Value::as_array).cloned().unwrap_or_default()
}

/// /dashboard — top projections + the honest model evaluation.
pub async fn dashboard(State(st): State<AppState>) -> Response {
    match artifacts::read_web_artifact(&st.cfg.root, "dashboard.json") {
        Some(a) => pages::render(&st, "dashboard.html", a),
        None => missing(&st, "Dashboard"),
    }
}

/// /players?q=&pos= — search/filter the precomputed projection board.
pub async fn players(
    State(st): State<AppState>,
    Query(params): Query<HashMap<String, String>>,
) -> Response {
    let Some(a) = artifacts::read_web_artifact(&st.cfg.root, "players.json") else {
        return missing(&st, "Players");
    };
    let q = params
        .get("q")
        .map(|s| s.trim().to_uppercase())
        .unwrap_or_default();
    let pos = params
        .get("pos")
        .map(|s| s.trim().to_uppercase())
        .unwrap_or_default();
    let mut rows = arr(a.get("players"));
    if !q.is_empty() {
        rows.retain(|p| {
            p.get("player_display_name")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_uppercase()
                .contains(&q)
        });
    }
    if !pos.is_empty() {
        rows.retain(|p| p.get("position").and_then(Value::as_str) == Some(pos.as_str()));
    }
    rows.truncate(200);
    let ctx = json!({
        "players": rows, "q": q, "pos": pos,
        "positions": a.get("positions").cloned().unwrap_or(json!(["QB", "RB", "WR", "TE"])),
    });
    pages::render(&st, "players.html", ctx)
}

/// /player/<pid> — per-player history + projection from its own artifact.
pub async fn player_detail(State(st): State<AppState>, Path(pid): Path<String>) -> Response {
    if !safe_segment(&pid, 32) {
        return (StatusCode::NOT_FOUND, "player not found").into_response();
    }
    match artifacts::read_web_artifact(&st.cfg.root, &format!("players/{pid}.json")) {
        Some(a) => pages::render(&st, "player.html", a),
        None => (StatusCode::NOT_FOUND, "player not found").into_response(),
    }
}

/// /predictions?week=N — win probabilities, week-filtered from the artifact.
pub async fn predictions(
    State(st): State<AppState>,
    Query(params): Query<HashMap<String, String>>,
) -> Response {
    let Some(a) = artifacts::read_web_artifact(&st.cfg.root, "predictions.json") else {
        return missing(&st, "Win Predictions");
    };
    let week: Option<i64> = params.get("week").and_then(|s| s.trim().parse().ok());
    let mut rows = arr(a.get("predictions"));
    if let Some(w) = week {
        rows.retain(|g| g.get("week").and_then(Value::as_i64) == Some(w));
    }
    let ctx = json!({
        "predictions": rows, "week": week,
        "weeks": a.get("weeks").cloned().unwrap_or(json!([])),
        "season": a.get("season").cloned().unwrap_or(Value::Null),
    });
    pages::render(&st, "predictions.html", ctx)
}

/// /ratings?season=&week= — as-of team ratings for the requested combo.
pub async fn ratings(
    State(st): State<AppState>,
    Query(params): Query<HashMap<String, String>>,
) -> Response {
    let Some(a) = artifacts::read_web_artifact(&st.cfg.root, "ratings.json") else {
        return missing(&st, "Team Ratings");
    };
    let seasons = arr(a.get("seasons"));
    let default_season = seasons.last().and_then(Value::as_i64).unwrap_or(2026);
    let season: i64 = params
        .get("season")
        .and_then(|s| s.trim().parse().ok())
        .unwrap_or(default_season);
    let week: i64 = params
        .get("week")
        .and_then(|s| s.trim().parse().ok())
        .unwrap_or(1);
    let rows = arr(a
        .get("ratings")
        .and_then(|t| t.get(format!("{season}-{week}"))));
    let earliest = seasons.first().and_then(Value::as_i64).unwrap_or(season);
    let notice = if rows.is_empty() {
        json!(format!(
            "No ratings for {season} week {week}: week 1 needs play-by-play from a \
             season before {season}, and {earliest} is the earliest available."
        ))
    } else {
        Value::Null
    };
    let ctx = json!({"ratings": rows, "season": season, "week": week,
                     "seasons": seasons, "notice": notice});
    pages::render(&st, "ratings.html", ctx)
}

/// /strategy?team=&season= — situation splits for one team.
pub async fn strategy(
    State(st): State<AppState>,
    Query(params): Query<HashMap<String, String>>,
) -> Response {
    let Some(a) = artifacts::read_web_artifact(&st.cfg.root, "strategy.json") else {
        return missing(&st, "Game Strategy");
    };
    let team = params
        .get("team")
        .map(|s| s.trim().to_uppercase())
        .filter(|s| !s.is_empty())
        .unwrap_or_else(|| "BUF".to_string());
    let seasons = arr(a.get("seasons"));
    let default_season = seasons.last().and_then(Value::as_i64).unwrap_or(2026);
    let season: i64 = params
        .get("season")
        .and_then(|s| s.trim().parse().ok())
        .unwrap_or(default_season);
    let breakdown = a
        .get("strategy")
        .and_then(|t| t.get(season.to_string()))
        .and_then(|t| t.get(&team))
        .cloned()
        .unwrap_or(Value::Null);
    let ctx = json!({"team": team, "season": season, "breakdown": breakdown,
                     "seasons": seasons});
    pages::render(&st, "strategy.html", ctx)
}

/// /sos — 2026 strength-of-schedule ranking.
pub async fn sos(State(st): State<AppState>) -> Response {
    match artifacts::read_web_artifact(&st.cfg.root, "sos.json") {
        Some(a) => pages::render(&st, "sos.html", a),
        None => missing(&st, "Strength of Schedule"),
    }
}

/// /api/predictions?week=N — the records as JSON.
pub async fn api_predictions(
    State(st): State<AppState>,
    Query(params): Query<HashMap<String, String>>,
) -> Response {
    let Some(a) = artifacts::read_web_artifact(&st.cfg.root, "predictions.json") else {
        return (
            StatusCode::NOT_FOUND,
            Json(json!({"error": "predictions artifact not built yet"})),
        )
            .into_response();
    };
    let week: Option<i64> = params.get("week").and_then(|s| s.trim().parse().ok());
    let mut rows = arr(a.get("predictions"));
    if let Some(w) = week {
        rows.retain(|g| g.get("week").and_then(Value::as_i64) == Some(w));
    }
    Json(Value::Array(rows)).into_response()
}

/// /api/modelcard — evaluation + CV as JSON.
pub async fn api_modelcard(State(st): State<AppState>) -> Response {
    match artifacts::read_web_artifact(&st.cfg.root, "modelcard.json") {
        Some(a) => Json(json!({
            "evaluation": a.get("evaluation").cloned().unwrap_or(Value::Null),
            "cv": a.get("cv").cloned().unwrap_or(Value::Null),
        }))
        .into_response(),
        None => (
            StatusCode::NOT_FOUND,
            Json(json!({"error": "modelcard artifact not built yet"})),
        )
            .into_response(),
    }
}
