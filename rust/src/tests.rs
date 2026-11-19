//! Hermetic tests: pin store parity with src/pins.py, artifact parsing,
//! native page rendering through the real templates, and the proxy
//! (stub backend on an ephemeral loopback port).

use std::path::{Path, PathBuf};

use axum::body::Body;
use axum::http::{Request, StatusCode};
use http_body_util::BodyExt;
use serde_json::{json, Value};
use tower::ServiceExt;

use crate::{pins, router, Config};

const REPO_ROOT: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/..");

/// tmp root with the REAL templates copied in + fixture artifacts.
fn fixture_root(tmp: &Path) -> PathBuf {
    let root = tmp.to_path_buf();
    let tpl_dst = root.join("web/templates");
    std::fs::create_dir_all(&tpl_dst).unwrap();
    let tpl_src = Path::new(REPO_ROOT).join("web/templates");
    for name in [
        "layout.html",
        "team.html",
        "league.html",
        "league_team.html",
        "cron.html",
    ] {
        std::fs::copy(tpl_src.join(name), tpl_dst.join(name)).unwrap();
    }
    std::fs::create_dir_all(root.join("logs")).unwrap();
    std::fs::create_dir_all(root.join("data")).unwrap();
    root
}

fn operator_record(status: &str) -> Value {
    json!({
        "time": "2026-09-12T23:24:01+00:00", "status": status, "week": 1,
        "record": "0-0-0", "waiver_priority": 4,
        "matchup": {"week": 1, "team": "Shiba Innu", "score": 35.6,
                    "opponent": "Team Beta", "opponent_score": 0.0,
                    "team_proj": 100.7, "opponent_proj": 112.7},
        "proposal": {"moves": [], "plan": [
            {"current_slot": "QB", "proposed_slot": "QB", "name": "Quarter Back",
             "position": "QB", "proj_week": 17.8, "note": "locked", "yahoo_id": "1"},
            {"current_slot": "RB", "proposed_slot": "RB", "name": "Running Back",
             "position": "RB", "proj_week": 18.8, "note": "", "yahoo_id": "2"}]},
        "monitor": {"needs_attention": false, "locked_starters": ["Quarter Back"],
                    "injury_tags": [], "bye_players": [], "week": 1,
                    "roster_count": 15, "starter_count": 9}
    })
}

fn write_runs(root: &Path, records: &[Value]) {
    let body: String = records.iter().map(|r| r.to_string() + "\n").collect();
    std::fs::write(root.join("logs/team-operator.jsonl"), body).unwrap();
}

fn cfg(root: &Path) -> Config {
    Config {
        bind: "127.0.0.1:0".into(),
        backend: "http://127.0.0.1:1".into(), // unroutable: proxy tests override
        root: root.to_path_buf(),
    }
}

async fn get_body(app: axum::Router, uri: &str) -> (StatusCode, String) {
    let res = app
        .oneshot(Request::builder().uri(uri).body(Body::empty()).unwrap())
        .await
        .unwrap();
    let status = res.status();
    let bytes = res.into_body().collect().await.unwrap().to_bytes();
    (status, String::from_utf8_lossy(&bytes).to_string())
}

// --- pin store (parity with tests/test_pins.py) ---

#[test]
fn pins_missing_file_means_no_pins() {
    let tmp = tempfile_dir();
    let p = tmp.join("pins.json");
    assert!(pins::load_pins(&p).unwrap().is_empty());
}

#[test]
fn pins_toggle_roundtrip() {
    let tmp = tempfile_dir();
    let p = tmp.join("pins.json");
    assert!(pins::toggle_pin("42", "Some Player", &p).unwrap());
    let stored = pins::load_pins(&p).unwrap();
    assert_eq!(stored["42"]["name"], "Some Player");
    assert!(stored["42"]["pinned_at"]
        .as_str()
        .unwrap()
        .contains("+00:00"));
    assert!(!pins::toggle_pin("42", "Some Player", &p).unwrap());
    assert!(pins::load_pins(&p).unwrap().is_empty());
}

#[test]
fn pins_corrupt_raises_and_toggle_refuses_overwrite() {
    let tmp = tempfile_dir();
    let p = tmp.join("pins.json");
    std::fs::write(&p, "{corrupt").unwrap();
    let err = pins::load_pins(&p).unwrap_err().to_string();
    assert!(err.contains("not valid JSON"), "{err}");
    assert!(pins::toggle_pin("1", "One", &p).is_err());
    assert_eq!(std::fs::read_to_string(&p).unwrap(), "{corrupt");
}

#[test]
fn pins_wrong_shape_raises() {
    let tmp = tempfile_dir();
    let p = tmp.join("pins.json");
    for payload in [
        "[]",
        "{\"pinned\": []}",
        "{\"pinned\": {\"5\": \"name\"}}",
        "{\"pinned\": {\"5\": {\"name\": 7}}}",
        "{\"nope\": {}}",
    ] {
        std::fs::write(&p, payload).unwrap();
        assert!(pins::load_pins(&p).is_err(), "{payload}");
    }
}

#[test]
fn pins_save_leaves_no_tmp() {
    let tmp = tempfile_dir();
    let p = tmp.join("pins.json");
    pins::toggle_pin("9", "Nine", &p).unwrap();
    assert!(!p.with_file_name("pins.json.tmp").exists());
    let v: Value = serde_json::from_str(&std::fs::read_to_string(&p).unwrap()).unwrap();
    assert!(v.get("pinned").unwrap().get("9").is_some());
}

// --- artifact parsing ---

#[test]
fn operator_runs_newest_first_and_normalizes() {
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    let mut broken = operator_record("ok");
    broken["proposal"]["moves"] = json!("garbage");
    broken["proposal"]["plan"] = json!(42);
    write_runs(&root, &[operator_record("error"), broken]);
    let runs = crate::artifacts::read_operator_runs(&root, 30);
    assert_eq!(runs.len(), 2);
    assert_eq!(runs[0]["status"], "ok"); // newest first
    assert_eq!(runs[0]["proposal"]["moves"], json!([]));
    assert_eq!(runs[0]["proposal"]["plan"], Value::Null);
}

#[test]
fn operator_runs_skips_bad_and_non_dict_lines() {
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    let body = format!(
        "not json at all\n[1,2,3]\n\"a string\"\n{}\n",
        operator_record("ok")
    );
    std::fs::write(root.join("logs/team-operator.jsonl"), body).unwrap();
    let runs = crate::artifacts::read_operator_runs(&root, 30);
    assert_eq!(runs.len(), 1);
    assert_eq!(runs[0]["status"], "ok");
}

#[test]
fn operator_runs_tolerates_bad_utf8() {
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    let mut body = operator_record("ok").to_string().into_bytes();
    body.extend_from_slice(b"\n\xff\xfe invalid utf8 line\n");
    body.extend_from_slice(operator_record("error").to_string().as_bytes());
    std::fs::write(root.join("logs/team-operator.jsonl"), body).unwrap();
    let runs = crate::artifacts::read_operator_runs(&root, 30);
    assert_eq!(runs.len(), 2); // bad line skipped, good lines survive
    assert_eq!(runs[0]["status"], "error");
}

#[test]
fn league_report_garbage_is_none() {
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    std::fs::write(root.join("logs/league-report.json"), "{garbage").unwrap();
    assert!(crate::artifacts::read_league_report(&root).is_none());
    std::fs::write(root.join("logs/league-report.json"), "[1,2]").unwrap();
    assert!(crate::artifacts::read_league_report(&root).is_none());
}

#[tokio::test]
async fn nav_groups_fantasy_apart_from_prediction_pages() {
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    write_runs(&root, &[operator_record("ok")]);
    let (_, html) = get_body(router(cfg(&root)), "/team").await;
    for href in ["href=\"/team\"", "href=\"/league\"", "href=\"/cron\""] {
        assert!(html.contains(href), "{href} missing");
    }
    assert!(html.contains("FD nation") && html.contains("Prediction engines"));
    let idx = |s: &str| html.find(s).unwrap();
    assert!(idx("FD nation") < idx("href=\"/team\""));
    assert!(idx("href=\"/team\"") < idx("Prediction engines"));
    assert!(idx("href=\"/league\"") < idx("Prediction engines"));
    assert!(idx("href=\"/cron\"") < idx("Prediction engines"));
    assert!(idx("href=\"/players\"") > idx("Prediction engines"));
    assert!(idx("href=\"/predictions\"") > idx("Prediction engines"));
    assert!(idx("href=\"/dashboard\"") > idx("Prediction engines"));
}

// --- native pages through the real templates ---

#[tokio::test]
async fn root_redirects_to_my_team() {
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    let res = router(cfg(&root))
        .oneshot(Request::builder().uri("/").body(Body::empty()).unwrap())
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::FOUND);
    assert_eq!(res.headers()["location"], "/team");
}

#[tokio::test]
async fn dashboard_proxies_to_backend_root() {
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    let mut c = cfg(&root);
    c.backend = spawn_backend().await;
    let (status, body) = get_body(router(c), "/dashboard").await;
    assert_eq!(status, StatusCode::OK);
    let v: Value = serde_json::from_str(&body).unwrap();
    assert_eq!(v["path"], "/"); // rewritten to the Flask dashboard root
}

#[tokio::test]
async fn team_page_renders_plan_and_pin_buttons() {
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    write_runs(&root, &[operator_record("ok")]);
    let (status, html) = get_body(router(cfg(&root)), "/team").await;
    assert_eq!(status, StatusCode::OK);
    assert!(html.contains("Running Back"), "{html}");
    // minijinja escapes "/" as &#x2f; in attributes (browser-identical);
    // Flask/Jinja leaves it literal — accept both.
    assert!(
        html.contains("action=\"/team/pin\"") || html.contains("action=\"&#x2f;team&#x2f;pin\""),
        "{html}"
    );
    assert!(html.contains("name=\"yahoo_id\" value=\"2\""));
}

#[tokio::test]
async fn team_page_falls_back_to_last_ok_run() {
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    write_runs(&root, &[operator_record("ok"), operator_record("error")]);
    let (status, html) = get_body(router(cfg(&root)), "/team").await;
    assert_eq!(status, StatusCode::OK);
    assert!(html.contains("Latest operator run: <b>error</b>"));
    assert!(html.contains("Running Back")); // from the ok fallback
}

#[tokio::test]
async fn pin_toggle_roundtrip_over_http() {
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    write_runs(&root, &[operator_record("ok")]);
    let app = router(cfg(&root));
    let res = app
        .clone()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/team/pin")
                .header("content-type", "application/x-www-form-urlencoded")
                .body(Body::from("yahoo_id=2&name=Running+Back"))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::FOUND);
    assert_eq!(res.headers()["location"], "/team");
    let p = root.join("data/pins.json");
    let v: Value = serde_json::from_str(&std::fs::read_to_string(&p).unwrap()).unwrap();
    assert_eq!(v["pinned"]["2"]["name"], "Running Back");
    let (_, html) = get_body(app.clone(), "/team").await;
    assert!(html.contains("pin-btn on"));
    assert!(html.contains("📌 Running Back"));
    // tick again -> unpinned
    app.oneshot(
        Request::builder()
            .method("POST")
            .uri("/team/pin")
            .header("content-type", "application/x-www-form-urlencoded")
            .body(Body::from("yahoo_id=2&name=Running+Back"))
            .unwrap(),
    )
    .await
    .unwrap();
    let v: Value = serde_json::from_str(&std::fs::read_to_string(&p).unwrap()).unwrap();
    assert_eq!(v["pinned"], json!({}));
}

#[tokio::test]
async fn pin_toggle_requires_id_and_refuses_corrupt_file() {
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    write_runs(&root, &[operator_record("ok")]);
    let app = router(cfg(&root));
    let res = app
        .clone()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/team/pin")
                .header("content-type", "application/x-www-form-urlencoded")
                .body(Body::from("name=Nobody"))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::BAD_REQUEST);
    let p = root.join("data/pins.json");
    std::fs::write(&p, "{corrupt").unwrap();
    let (_, html) = get_body(app.clone(), "/team").await;
    assert!(html.contains("Pin file problem"));
    let res = app
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/team/pin")
                .header("content-type", "application/x-www-form-urlencoded")
                .body(Body::from("yahoo_id=2&name=X"))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::CONFLICT);
    assert_eq!(std::fs::read_to_string(&p).unwrap(), "{corrupt");
}

#[tokio::test]
async fn cron_page_lists_schedule_and_runs() {
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    write_runs(&root, &[operator_record("ok")]);
    let (status, html) = get_body(router(cfg(&root)), "/cron").await;
    assert_eq!(status, StatusCode::OK);
    assert!(html.contains("47 23 * * 0"));
    assert!(html.contains("team_operator.py --apply"));
}

#[tokio::test]
async fn league_page_and_team_detail_and_404() {
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    let report = json!({
        "captured_at": "2026-09-13T12:19:00+00:00",
        "standings": [
            {"rank": 1, "team": "Shiba Innu", "record": "1-0-0",
             "points_for": "140.5", "points_against": 90.1, "waiver": 3},
            {"rank": 2, "team": "Team Beta", "record": "0-1-0",
             "points_for": 90.1, "points_against": 140.5, "waiver": 7}],
        "matchup": {"week": 2, "team": "Shiba Innu", "opponent": "Team Beta",
                    "score": 0, "opponent_score": 0, "team_proj": 100.0,
                    "opponent_proj": 99.0},
        "rosters": {"Team Beta": [{"name": "Beta Rb", "team": "DAL",
                    "position": "RB", "slot": "RB", "injury_status": ""}]},
        "scoreboard": [{"week": 2, "team1": "Shiba Innu", "team2": "Team Beta",
                        "score1": 0, "score2": 0, "proj1": 100.0, "proj2": 99.0}]
    });
    std::fs::write(root.join("logs/league-report.json"), report.to_string()).unwrap();
    let app = router(cfg(&root));
    let (status, html) = get_body(app.clone(), "/league").await;
    assert_eq!(status, StatusCode::OK);
    assert!(html.contains("Shiba Innu"));
    assert!(html.contains("/league/team/Team%20Beta")); // urlencode filter
                                                        // GameChannel-style matchup cards: 5:3:5 flex, vs badge, proj row,
                                                        // record|rank joined from standings, initials avatar, mine highlight,
                                                        // projection leader marked (100.0 > 99.0 pre-kickoff).
    assert!(html.contains("mu-card"), "{html}");
    assert!(html.contains("mu-vs"));
    assert!(html.contains("Proj Pts"));
    assert!(html.contains("1-0-0 | #1"));
    assert!(html.contains(">SI</div>")); // Shiba Innu initials
    assert!(html.contains(">TB</div>")); // Team Beta initials
    assert!(html.contains("mu-card mine"));
    assert!(html.contains("mu-score mu-leading"));
    assert!(html.contains("Week 2 matchups"));
    let (status, html) = get_body(app.clone(), "/league/team/Team%20Beta").await;
    assert_eq!(status, StatusCode::OK);
    assert!(html.contains("Beta Rb"));
    assert!(html.contains("Playing us this week")); // opponent matchup card
    assert!(html.contains("50.4")); // PF-PA diff rounded: 90.1-140.5 = -50.4
    let (status, html) = get_body(app, "/league/team/No%20Such%20Team").await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert!(html.contains("No team named"));
}

#[tokio::test]
async fn league_team_roster_falls_back_to_history() {
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    let latest = json!({"captured_at": "2026-09-13T12:19:00+00:00",
        "standings": [{"rank": 1, "team": "Team Alpha", "record": "1-0-0",
                       "points_for": 100, "points_against": 90, "waiver": 3}]});
    let older = json!({"captured_at": "2026-09-12T12:19:00+00:00",
        "standings": [{"rank": 1, "team": "Team Alpha", "record": "0-0-0",
                       "points_for": 0, "points_against": 0, "waiver": 3}],
        "rosters": {"Team Alpha": [{"name": "Old Rb", "team": "DAL",
                     "position": "RB", "slot": "RB", "injury_status": ""}]}});
    let newer = json!({"captured_at": "2026-09-13T12:19:00+00:00",
        "standings": [{"rank": 1, "team": "Team Alpha", "record": "1-0-0",
                       "points_for": 100, "points_against": 90, "waiver": 3}],
        "rosters": {"Team Alpha": [{"name": "Alpha Rb", "team": "DAL",
                     "position": "RB", "slot": "RB", "injury_status": ""}]}});
    std::fs::write(root.join("logs/league-report.json"), latest.to_string()).unwrap();
    std::fs::write(
        root.join("logs/league-report.jsonl"),
        format!("{}\n{}\n", older, newer),
    )
    .unwrap();
    let (status, html) = get_body(router(cfg(&root)), "/league/team/Team%20Alpha").await;
    assert_eq!(status, StatusCode::OK);
    assert!(html.contains("Alpha Rb") && !html.contains("Old Rb")); // newest holder wins
    assert!(html.contains("2026-09-13")); // dated-snapshot note
    assert!(html.contains("Season trajectory"));
}

// --- proxy (jv-webd method) ---

/// Stub compute backend: echoes path + received XFF as JSON.
async fn spawn_backend() -> String {
    let app = axum::Router::new().fallback(|req: Request<Body>| async move {
        let xff = req
            .headers()
            .get("x-forwarded-for")
            .and_then(|v| v.to_str().ok())
            .unwrap_or("")
            .to_string();
        let host = req
            .headers()
            .get("host")
            .and_then(|v| v.to_str().ok())
            .unwrap_or("")
            .to_string();
        axum::Json(json!({"path": req.uri().path(), "query": req.uri().query(),
                          "xff": xff, "host": host}))
    });
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
    format!("http://{addr}")
}

#[tokio::test]
async fn proxy_forwards_path_query_and_replaces_spoofed_xff() {
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    let mut c = cfg(&root);
    c.backend = spawn_backend().await;
    let res = router(c)
        .oneshot(
            Request::builder()
                .uri("/players?q=RB&pos=RB")
                .header("x-forwarded-for", "6.6.6.6") // spoofed: must be replaced
                .header("x-real-ip", "6.6.6.6")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    let bytes = res.into_body().collect().await.unwrap().to_bytes();
    let v: Value = serde_json::from_slice(&bytes).unwrap();
    assert_eq!(v["path"], "/players");
    assert_eq!(v["query"], "q=RB&pos=RB");
    // oneshot has no ConnectInfo peer: prior chain is passed through only
    // when there is no peer to assert; with a real socket the peer wins.
    assert_eq!(v["xff"], "6.6.6.6");
}

#[tokio::test]
async fn proxy_sets_xff_from_real_peer() {
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    let mut c = cfg(&root);
    c.backend = spawn_backend().await;
    // full socket path so ConnectInfo is present (loopback peer keeps chain)
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let app = router(c).into_make_service_with_connect_info::<std::net::SocketAddr>();
    tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
    let client = reqwest::Client::new();
    let body = client
        .get(format!("http://{addr}/predictions"))
        .header("x-forwarded-for", "203.0.113.9")
        .send()
        .await
        .unwrap()
        .text()
        .await
        .unwrap();
    let v: Value = serde_json::from_str(&body).unwrap();
    assert_eq!(v["path"], "/predictions");
    assert_eq!(v["xff"], "203.0.113.9, 127.0.0.1"); // loopback peer appends
    assert_ne!(v["host"], format!("{addr}")); // host rewritten to upstream
}

#[tokio::test]
async fn proxy_backend_down_is_502() {
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    let (status, body) = get_body(router(cfg(&root)), "/predictions").await;
    assert_eq!(status, StatusCode::BAD_GATEWAY);
    assert!(body.contains("backend unreachable"));
}

// --- helpers ---

fn tempfile_dir() -> PathBuf {
    use std::sync::atomic::{AtomicU64, Ordering};
    static SEQ: AtomicU64 = AtomicU64::new(0);
    let base = std::env::temp_dir().join(format!(
        "nfl-webd-test-{}-{}-{:?}",
        std::process::id(),
        SEQ.fetch_add(1, Ordering::Relaxed),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&base).unwrap();
    base
}
