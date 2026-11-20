//! nfl-webd: single local surface for the FD nation web UI — the jra-van-re
//! jv-webd method applied to nfl:
//!
//!   /            -> 302 to /league (the public face is the league)
//!   /dashboard   -> backend / (Flask keeps the dashboard at its root)
//!   /team, /team/pin, /league, /league/team/<name>, /cron
//!       -> served NATIVELY by axum + minijinja from the same Jinja
//!          templates Flask uses (web/templates/), reading the same local
//!          artifacts (logs/*.json[l], data/pins.json). No Python involved.
//!   /live-points -> the live points artifact as JSON (poll fallback)
//!   /ws          -> WebSocket push of logs/live-points.json: a watcher
//!          task broadcasts every file change; the poller (cron/launchd,
//!          tools/live_points.py) owns the writes. Points are computed
//!          from ESPN raw stats under the exact Yahoo league weights and
//!          reconciled against Yahoo's own totals (drift flag).
//!   everything else (/players, /player/<id>, /predictions, /sos,
//!       /ratings, /strategy, /api/*)
//!       -> reverse-proxied to the Python compute backend (Flask on
//!          loopback, NFL_WEBD_BACKEND) which owns the pandas/sklearn
//!          analytics. The backend is never exposed directly.
//!
//! Same trust model as jv-webd: this daemon binds loopback (public exposure
//! goes through the com.fdnation.cloudflared quick tunnel), hop-by-hop
//! headers are stripped both ways, and client-supplied forwarding headers
//! are replaced from the real peer (anti-spoof).

pub mod artifacts;
pub mod pages;
pub mod pins;
pub mod render;

use std::net::{IpAddr, SocketAddr};
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use axum::{
    body::Body,
    extract::{
        ws::{Message, WebSocket, WebSocketUpgrade},
        ConnectInfo, Path, Request, State,
    },
    http::{header, StatusCode},
    response::{IntoResponse, Response},
    routing::{any, get, post},
    Router,
};
use futures_util::{SinkExt, StreamExt};
use tokio::sync::broadcast;

#[derive(Clone)]
pub struct Config {
    pub bind: String,
    pub backend: String,
    pub root: PathBuf,
}

impl Config {
    pub fn from_env() -> Self {
        let get = |k: &str, d: &str| std::env::var(k).unwrap_or_else(|_| d.to_string());
        Self {
            bind: get("NFL_WEBD_BIND", "127.0.0.1:5000"),
            backend: get("NFL_WEBD_BACKEND", "http://127.0.0.1:5001"),
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
    pub http: reqwest::Client,
    pub env: Arc<minijinja::Environment<'static>>,
    /// Live points push: the file watcher broadcasts artifact changes here.
    pub live_tx: broadcast::Sender<String>,
}

pub fn router(cfg: Config) -> Router {
    let env = Arc::new(render::environment(&cfg.root));
    let http = reqwest::Client::builder()
        .connect_timeout(Duration::from_secs(5))
        // analytics pages can train models / build the corpus on a cold cache
        .timeout(Duration::from_secs(300))
        .redirect(reqwest::redirect::Policy::none())
        .build()
        .expect("reqwest client");
    let (live_tx, _) = broadcast::channel::<String>(64);
    spawn_live_watcher(cfg.root.clone(), live_tx.clone());
    let st = AppState {
        cfg,
        http,
        env,
        live_tx,
    };
    Router::new()
        // The public face of the stack is the league, not the model card:
        // / lands on League; the dashboard lives at /dashboard.
        .route(
            "/",
            get(|| async { (StatusCode::FOUND, [(header::LOCATION, "/league")]).into_response() }),
        )
        .route("/dashboard", get(dashboard))
        .route("/team", get(pages::team))
        .route("/team/pin", post(pages::pin_toggle))
        .route("/league", get(pages::league))
        .route("/league/team/{name}", get(pages::league_team))
        .route("/league/teamview", get(pages::teamview))
        .route("/logos/{file}", get(logo))
        .route("/live-points", get(live_points))
        .route("/ws", get(ws_upgrade))
        .route("/cron", get(pages::cron))
        .fallback(any(proxy))
        .with_state(st)
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

/// /dashboard -> the backend's / (Flask keeps the dashboard at its root).
async fn dashboard(State(st): State<AppState>, mut req: Request) -> Response {
    *req.uri_mut() = "/".parse().expect("static uri");
    proxy(State(st), req).await
}

/// /logos/<file> — team logos captured by cron into data/logos/.
/// Strict filename allowlist: no path traversal, no hidden files.
async fn logo(State(st): State<AppState>, Path(file): Path<String>) -> Response {
    let ok = !file.is_empty()
        && file.len() <= 64
        && !file.contains("..")
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

/// RFC 7230 hop-by-hop headers, never forwarded in either direction.
fn is_hop_by_header(name: &header::HeaderName) -> bool {
    matches!(
        name.as_str(),
        "connection"
            | "keep-alive"
            | "proxy-authenticate"
            | "proxy-authorization"
            | "te"
            | "trailer"
            | "transfer-encoding"
            | "upgrade"
    )
}

/// X-Forwarded-For for the backend (jv-webd trust model):
/// - loopback peer (cloudflared / local proxy): preserve the incoming chain
///   and append the peer;
/// - remote peer: DISCARD any client-supplied XFF (spoofable), send the peer.
fn forwarded_for(peer: Option<IpAddr>, prior: Option<&str>) -> Option<String> {
    match peer {
        Some(p) if p.is_loopback() => match prior.map(str::trim).filter(|s| !s.is_empty()) {
            Some(chain) => Some(format!("{chain}, {p}")),
            None => Some(p.to_string()),
        },
        Some(p) => Some(p.to_string()),
        None => prior.map(str::to_string),
    }
}

/// Path-based reverse proxy to the Python compute backend (jv-webd method,
/// single upstream, no prefix rewrite).
async fn proxy(State(st): State<AppState>, req: Request) -> Response {
    let (parts, body) = req.into_parts();
    let mut url = format!(
        "{}{}",
        st.cfg.backend.trim_end_matches('/'),
        parts.uri.path()
    );
    if let Some(q) = parts.uri.query() {
        url.push('?');
        url.push_str(q);
    }

    let mut rb = st.http.request(parts.method.clone(), &url);
    // RFC 7230 §6.1: the Connection header can NAME extra hop-by-hop
    // headers — strip those too, not just the fixed list.
    let conn_named: Vec<String> = parts
        .headers
        .get(header::CONNECTION)
        .and_then(|v| v.to_str().ok())
        .map(|v| {
            v.split(',')
                .map(|t| t.trim().to_ascii_lowercase())
                .filter(|t| !t.is_empty())
                .collect()
        })
        .unwrap_or_default();
    let peer = parts
        .extensions
        .get::<ConnectInfo<SocketAddr>>()
        .map(|c| c.0.ip());
    let prior_xff = parts
        .headers
        .get("x-forwarded-for")
        .and_then(|v| v.to_str().ok())
        .map(str::to_string);
    for (name, value) in &parts.headers {
        // client-supplied forwarding headers are replaced below (anti-spoof)
        if is_hop_by_header(name)
            || name == header::HOST
            || matches!(name.as_str(), "x-forwarded-for" | "x-real-ip" | "forwarded")
            || conn_named.iter().any(|t| t == name.as_str())
        {
            continue;
        }
        rb = rb.header(name, value);
    }
    if let Some(xff) = forwarded_for(peer, prior_xff.as_deref()) {
        rb = rb.header("x-forwarded-for", xff);
    }

    let up = match rb
        .body(reqwest::Body::wrap_stream(body.into_data_stream()))
        .send()
        .await
    {
        Ok(r) => r,
        Err(e) => {
            tracing::warn!("proxy {url}: {e}");
            return (
                StatusCode::BAD_GATEWAY,
                [(header::CONTENT_TYPE, "text/plain; charset=utf-8")],
                "compute backend unreachable — is com.fdnation.backend running?",
            )
                .into_response();
        }
    };

    let mut b = Response::builder().status(up.status());
    for (name, value) in up.headers() {
        if is_hop_by_header(name) || name == header::CONTENT_LENGTH {
            continue; // streamed body -> chunked, upstream length is stale
        }
        b = b.header(name, value);
    }
    b.body(Body::from_stream(up.bytes_stream()))
        .expect("proxy response")
}

#[cfg(test)]
mod tests;
