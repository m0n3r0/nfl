//! nfl-webd: single local surface for the FD nation web UI — the jra-van-re
//! jv-webd method, now applied to BOTH halves of the app:
//!
//!   /            -> 302 to /league (the public face is the league)
//!   /team, /team/pin, /league, /league/team/<name>, /league/teamview,
//!   /logos/<file>, /cron
//!       -> fantasy pages served NATIVELY by axum + minijinja from
//!          web/templates/, reading local artifacts (logs/*.json[l],
//!          data/pins.json). No Python involved.
//!   /dashboard, /players, /player/<id>, /predictions, /ratings, /strategy,
//!   /sos, /api/predictions, /api/modelcard
//!       -> prediction-engine pages, ALSO native: the Python engine
//!          (src/) computes OFFLINE via tools/predictions_report.py into
//!          data/web/*.json (com.fdnation.predreport launchd agent);
//!          these handlers only read those artifacts. The Flask web
//!          backend and the reverse proxy are gone.
//!   /live-points -> the live points artifact as JSON (poll fallback)
//!   /ws          -> WebSocket push of logs/live-points.json: a watcher
//!          task broadcasts every file change; the poller (cron/launchd,
//!          tools/live_points.py) owns the writes. Points are computed
//!          from ESPN raw stats under the exact Yahoo league weights and
//!          reconciled against Yahoo's own totals (drift flag).
//!
//! Same trust model as jv-webd: this daemon binds loopback; public exposure
//! goes through the com.fdnation.cloudflared quick tunnel. Every page is a
//! local artifact read — nothing is computed in the request path.

pub mod analytics;
pub mod artifacts;
pub mod pages;
pub mod pins;
pub mod render;

use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use axum::{
    extract::{
        ws::{Message, WebSocket, WebSocketUpgrade},
        Path, Request, State,
    },
    http::{header, StatusCode},
    response::{IntoResponse, Response},
    routing::{get, post},
    Router,
};
use futures_util::{SinkExt, StreamExt};
use tokio::sync::broadcast;

#[derive(Clone)]
pub struct Config {
    pub bind: String,
    pub root: PathBuf,
}

impl Config {
    pub fn from_env() -> Self {
        let get = |k: &str, d: &str| std::env::var(k).unwrap_or_else(|_| d.to_string());
        Self {
            bind: get("NFL_WEBD_BIND", "127.0.0.1:5000"),
            root: discover_root(std::env::var("NFL_WEBD_ROOT").ok()),
        }
    }
}

/// Repo root: explicit env, else cwd when it holds web/templates, else walk
/// up from the executable (rust/target/release/nfl-webd -> repo root).
fn discover_root(explicit: Option<String>) -> PathBuf {
    if let Some(p) = explicit.filter(|p| !p.is_empty()) {
        return PathBuf::from(p);
    }
    let cwd = std::env::current_dir().unwrap_or_default();
    if cwd.join("web/templates").is_dir() {
        return cwd;
    }
    if let Ok(exe) = std::env::current_exe() {
        for anc in exe.ancestors().skip(1) {
            if anc.join("web/templates").is_dir() {
                return anc.to_path_buf();
            }
        }
    }
    cwd
}

#[derive(Clone)]
pub struct AppState {
    pub cfg: Config,
    pub env: Arc<minijinja::Environment<'static>>,
    /// Live points push: the file watcher broadcasts artifact changes here.
    pub live_tx: broadcast::Sender<String>,
}

pub fn router(cfg: Config) -> Router {
    let env = Arc::new(render::environment(&cfg.root));
    let (live_tx, _) = broadcast::channel::<String>(64);
    spawn_live_watcher(cfg.root.clone(), live_tx.clone());
    let st = AppState { cfg, env, live_tx };
    Router::new()
        // The public face of the stack is the league, not the model card:
        // / lands on League; the dashboard lives at /dashboard.
        .route(
            "/",
            get(|| async { (StatusCode::FOUND, [(header::LOCATION, "/league")]).into_response() }),
        )
        .route("/dashboard", get(analytics::dashboard))
        .route("/team", get(pages::team))
        .route("/team/pin", post(pages::pin_toggle))
        .route("/league", get(pages::league))
        .route("/league/team/{name}", get(pages::league_team))
        .route("/league/teamview", get(pages::teamview))
        .route("/logos/{file}", get(logo))
        .route("/live-points", get(live_points))
        .route("/ws", get(ws_upgrade))
        .route("/cron", get(pages::cron))
        // Prediction engine — native reads of data/web/*.json.
        .route("/players", get(analytics::players))
        .route("/player/{pid}", get(analytics::player_detail))
        .route("/predictions", get(analytics::predictions))
        .route("/ratings", get(analytics::ratings))
        .route("/strategy", get(analytics::strategy))
        .route("/sos", get(analytics::sos))
        .route("/api/predictions", get(analytics::api_predictions))
        .route("/api/modelcard", get(analytics::api_modelcard))
        .fallback(not_found)
        .with_state(st)
}

/// Everything else is a plain 404 — there is no upstream anymore.
async fn not_found(req: Request) -> Response {
    (
        StatusCode::NOT_FOUND,
        [(header::CONTENT_TYPE, "text/plain; charset=utf-8")],
        format!("no route for {}", req.uri().path()),
    )
        .into_response()
}

/// Watch logs/live-points.json (written by tools/live_points.py) and
/// broadcast every change to /ws subscribers. mtime polling at 2s — no
/// extra dependency, and the poller's atomic rename makes reads safe.
fn spawn_live_watcher(root: PathBuf, tx: broadcast::Sender<String>) {
    tokio::spawn(async move {
        let path = root.join("logs/live-points.json");
        let mut last: Option<std::time::SystemTime> = None;
        let mut tick = tokio::time::interval(Duration::from_secs(2));
        loop {
            tick.tick().await;
            if !root.exists() {
                break; // fixture/tmp root removed — stop the task
            }
            let mtime = std::fs::metadata(&path).and_then(|m| m.modified()).ok();
            if mtime.is_some() && mtime != last {
                if let Ok(text) = std::fs::read_to_string(&path) {
                    let _ = tx.send(text);
                }
                last = mtime;
            }
        }
    });
}

/// /live-points — the artifact as JSON (initial load + polling fallback).
async fn live_points(State(st): State<AppState>) -> Response {
    match std::fs::read_to_string(st.cfg.root.join("logs/live-points.json")) {
        Ok(text) => (
            StatusCode::OK,
            [
                (header::CONTENT_TYPE, "application/json"),
                (header::CACHE_CONTROL, "no-store"),
            ],
            text,
        )
            .into_response(),
        Err(_) => (
            StatusCode::NOT_FOUND,
            [(header::CONTENT_TYPE, "application/json")],
            "{\"error\":\"no live points yet\"}",
        )
            .into_response(),
    }
}

/// /ws — push live points. Sends the current artifact on connect, then
/// every watcher broadcast; 30s pings keep the cloudflared tunnel alive.
async fn ws_upgrade(State(st): State<AppState>, ws: WebSocketUpgrade) -> Response {
    ws.on_upgrade(move |socket| ws_conn(socket, st))
}

async fn ws_conn(socket: WebSocket, st: AppState) {
    let (mut sender, mut receiver) = socket.split();
    let mut rx = st.live_tx.subscribe();
    if let Ok(text) = std::fs::read_to_string(st.cfg.root.join("logs/live-points.json")) {
        if sender.send(Message::Text(text.into())).await.is_err() {
            return;
        }
    }
    let mut ping = tokio::time::interval(Duration::from_secs(30));
    ping.tick().await; // consume the immediate first tick
    loop {
        tokio::select! {
            msg = rx.recv() => match msg {
                Ok(text) => {
                    if sender.send(Message::Text(text.into())).await.is_err() {
                        break;
                    }
                }
                Err(broadcast::error::RecvError::Lagged(_)) => continue,
                Err(broadcast::error::RecvError::Closed) => break,
            },
            _ = ping.tick() => {
                if sender.send(Message::Ping(Vec::new().into())).await.is_err() {
                    break;
                }
            }
            incoming = receiver.next() => match incoming {
                Some(Ok(Message::Close(_))) | None => break,
                Some(Ok(_)) => {} // client text/pong: nothing to do
                Some(Err(_)) => break,
            },
        }
    }
}

/// /logos/<file> — team logos captured by cron into data/logos/.
/// Strict filename allowlist: no path traversal, no hidden files.
async fn logo(State(st): State<AppState>, Path(file): Path<String>) -> Response {
    let ok = !file.is_empty()
        && file.len() <= 64
        && !file.contains("..")
        && !file.starts_with('.')
        && file
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || "._-".contains(c));
    if !ok {
        return StatusCode::NOT_FOUND.into_response();
    }
    let bytes = match std::fs::read(st.cfg.root.join("data/logos").join(&file)) {
        Ok(b) => b,
        Err(_) => return StatusCode::NOT_FOUND.into_response(),
    };
    let ctype = match file.rsplit('.').next().unwrap_or("") {
        "png" => "image/png",
        "jpg" | "jpeg" => "image/jpeg",
        "gif" => "image/gif",
        "webp" => "image/webp",
        _ => "application/octet-stream",
    };
    (
        StatusCode::OK,
        [
            (header::CONTENT_TYPE, ctype),
            (header::CACHE_CONTROL, "public, max-age=86400"),
        ],
        bytes,
    )
        .into_response()
}

#[cfg(test)]
mod tests;
