//! Hermetic tests: pin store parity with src/pins.py, artifact parsing,
//! native page rendering through the real templates, and the proxy
//! (stub backend on an ephemeral loopback port).

use std::path::{Path, PathBuf};
use std::time::Duration;

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
        "teamview.html",
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
    // menu order: League, My Team, Cron — then the prediction engines
    assert!(idx("FD nation") < idx("href=\"/league\""));
    assert!(idx("href=\"/league\"") < idx("href=\"/team\""));
    assert!(idx("href=\"/team\"") < idx("href=\"/cron\""));
    assert!(idx("href=\"/cron\"") < idx("Prediction engines"));
    assert!(idx("href=\"/players\"") > idx("Prediction engines"));
    assert!(idx("href=\"/predictions\"") > idx("Prediction engines"));
    assert!(idx("href=\"/dashboard\"") > idx("Prediction engines"));
}

// --- native pages through the real templates ---

#[tokio::test]
async fn root_redirects_to_league() {
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    let res = router(cfg(&root))
        .oneshot(Request::builder().uri("/").body(Body::empty()).unwrap())
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::FOUND);
    assert_eq!(res.headers()["location"], "/league");
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
    assert!(html.contains("/league/teamview?a=Shiba%20Innu&amp;b=Team%20Beta"));
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

// --- Team View (players side by side) ---

fn teamview_fixtures(root: &Path) {
    write_runs(root, &[operator_record("ok")]);
    let report = json!({
        "captured_at": "2026-09-13T12:19:00+00:00",
        "matchup": {"week": 2, "team": "Shiba Innu", "opponent": "Team Beta",
                    "score": 0, "opponent_score": 0, "team_proj": 100.0,
                    "opponent_proj": 99.0},
        "standings": [
            {"rank": 3, "team": "Shiba Innu", "record": "8-2-0"},
            {"rank": 5, "team": "Team Beta", "record": "5-5-0"}],
        "scoreboard": [{"week": 2, "team1": "Shiba Innu", "team2": "Team Beta",
                        "score1": 0, "score2": 4.7}],
        "rosters": {
            "Shiba Innu": [
                {"name": "Quarter Back", "team": "SF", "position": "QB",
                 "slot": "QB", "injury_status": "", "proj": null},
                {"name": "Running Back", "team": "DAL", "position": "RB",
                 "slot": "RB", "injury_status": "", "proj": null}],
            "Team Beta": [
                {"name": "Enemy Qb", "team": "KC", "position": "QB", "slot": "QB",
                 "injury_status": "", "proj": 15.2},
                {"name": "Enemy Rb", "team": "DAL", "position": "RB", "slot": "RB",
                 "injury_status": "Q", "proj": null},
                {"name": "Enemy Bench", "team": "MIN", "position": "WR", "slot": "BN",
                 "injury_status": "", "proj": 8.0}]}
    });
    std::fs::write(root.join("logs/league-report.json"), report.to_string()).unwrap();
    // live artifact for the same week: Fan Pts column + game info + totals
    let live = json!({
        "week": 2,
        "players": {"quarter back": {"points": 21.35}, "enemy qb": {"points": 9.1}},
        "def_named": {},
        "totals": {"Shiba Innu": 21.35, "Team Beta": 9.1},
        "games": {"g1": {"state": "in", "date": "2026-09-13T17:00Z",
                         "teams": {"KC": {"home": true}, "DAL": {"home": false}}}}
    });
    std::fs::write(root.join("logs/live-points.json"), live.to_string()).unwrap();
}

#[tokio::test]
async fn live_points_route_serves_artifact_or_404() {
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    let app = router(cfg(&root));
    let (status, body) = get_body(app.clone(), "/live-points").await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert!(body.contains("no live points yet"));
    std::fs::write(
        root.join("logs/live-points.json"),
        r#"{"week":11,"totals":{"Team Alpha":42.5}}"#,
    )
    .unwrap();
    let (status, body) = get_body(app, "/live-points").await;
    assert_eq!(status, StatusCode::OK);
    assert!(body.contains("42.5"));
}

#[tokio::test]
async fn ws_pushes_initial_artifact_and_live_updates() {
    use futures_util::StreamExt;
    use tokio_tungstenite::tungstenite::Message;

    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    std::fs::write(
        root.join("logs/live-points.json"),
        r#"{"captured_at":"t0","totals":{"Team Alpha":10.0}}"#,
    )
    .unwrap();
    // real server on an ephemeral port (WS needs a live socket, not oneshot)
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let app = router(cfg(&root));
    tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });

    let (mut ws, _resp) = tokio_tungstenite::connect_async(format!("ws://{addr}/ws"))
        .await
        .expect("ws connect");
    // initial payload = current artifact
    let first = tokio::time::timeout(Duration::from_secs(5), ws.next())
        .await
        .expect("initial msg timeout")
        .unwrap()
        .unwrap();
    assert!(first.into_text().unwrap().contains("\"t0\""));

    // poller-style atomic update -> watcher broadcasts within ~2s
    std::fs::write(
        root.join("logs/live-points.json.tmp"),
        r#"{"captured_at":"t1","totals":{"Team Alpha":17.5}}"#,
    )
    .unwrap();
    std::fs::rename(
        root.join("logs/live-points.json.tmp"),
        root.join("logs/live-points.json"),
    )
    .unwrap();
    let update = tokio::time::timeout(Duration::from_secs(8), async {
        loop {
            match ws.next().await {
                Some(Ok(Message::Text(t))) if t.contains("\"t1\"") => break t,
                Some(Ok(_)) => continue, // ping/pong
                other => panic!("unexpected ws item: {other:?}"),
            }
        }
    })
    .await
    .expect("broadcast update timeout");
    assert!(update.contains("17.5"));
    let _ = ws.close(None).await;
}

#[tokio::test]
async fn logos_route_serves_local_files_only() {
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    std::fs::create_dir_all(root.join("data/logos")).unwrap();
    std::fs::write(root.join("data/logos/2.png"), b"\x89PNG fake").unwrap();
    std::fs::write(
        root.join("data/logos.json"),
        r#"{"Team Alpha": {"id": "2", "url": "https://cdn/x.png", "file": "2.png"}}"#,
    )
    .unwrap();
    let report = json!({
        "captured_at": "2026-11-20T00:00:00+00:00",
        "standings": [{"rank": 1, "team": "Team Alpha", "record": "8-2-0"}],
        "matchup": {"week": 11, "team": "Team Alpha", "opponent": "Team Beta"},
        "scoreboard": [{"team1": "Team Alpha", "team2": "Team Beta",
                        "score1": 0, "score2": 0}]
    });
    std::fs::write(root.join("logs/league-report.json"), report.to_string()).unwrap();
    let app = router(cfg(&root));

    let res = app
        .clone()
        .oneshot(Request::get("/logos/2.png").body(Body::empty()).unwrap())
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    assert_eq!(res.headers()["content-type"], "image/png");
    let bytes = res.into_body().collect().await.unwrap().to_bytes();
    assert_eq!(&bytes[..], b"\x89PNG fake");

    // traversal and unknown files -> 404, never a read outside data/logos
    for path in ["/logos/..%2f..%2fetc%2fpasswd", "/logos/nope.png"] {
        let (status, _) = get_body(app.clone(), path).await;
        assert_eq!(status, StatusCode::NOT_FOUND, "{path}");
    }

    // the league page renders the logo img when manifest + file exist
    // (minijinja HTML-escapes "/" in attributes as &#x2f; — browsers decode it)
    let (_, html) = get_body(app, "/league").await;
    assert!(html.contains("<img class=\"mu-logo\" src=\"&#x2f;logos&#x2f;2.png\""));
}

#[tokio::test]
async fn teamview_pairs_players_by_slot() {
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    teamview_fixtures(&root);
    let (status, html) = get_body(router(cfg(&root)), "/league/teamview").await;
    assert_eq!(status, StatusCode::OK);
    // matchup-page header: team blocks flanking the score
    assert!(html.contains("tv-tname\">Shiba Innu<") && html.contains("tv-tname\">Team Beta<"));
    assert!(html.contains("8-2-0 | #3") && html.contains("5-5-0 | #5"));
    // our side from the operator plan (with proj), opponent from the roster
    assert!(html.contains("Quarter Back") && html.contains("Enemy Qb"));
    assert!(html.contains("17.8")); // our QB projection (model)
    assert!(html.contains("15.2")); // opponent QB projection (Yahoo capture)
    assert!(html.contains("tv-pos\">QB<")); // the Pos spine
    assert!(html.contains("tv-note\">Q</span>")); // opponent injury tag (Stats col)
    assert!(html.contains("Starters") && html.contains("Bench / IR"));
    assert!(html.contains("Enemy Bench"));
    // bye opponent (proj null) -> dash, never fabricated
    assert!(html.contains("tv-empty"));
    // 9-column mirrored header, Yahoo matchup style
    assert!(html.contains("Fan Pts"));
    assert_eq!(html.matches(">Fan Pts</th>").count(), 2);
    // live Fan Pts column (week-matched artifact) + game info + totals
    assert!(html.contains("21.35")); // our QB live points
    assert!(html.contains("9.10")); // enemy QB live points
    assert!(html.contains("Mon 2:00 am JST vs DAL")); // KC home, ESPN no-seconds date, JST
    assert!(html.contains("Mon 2:00 am JST @ KC")); // DAL away game
    assert!(html.contains("Bye")); // SF has no game this week
    assert!(html.contains("tv-total")); // totals row
    assert!(html.contains("players remaining"));
    assert!(html.contains("data-live-fanpts=\"Quarter Back\""));
}

#[tokio::test]
async fn teamview_historical_week_from_archive() {
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    teamview_fixtures(&root); // current week 2; operator run for week 1 exists
    let old = json!({
        "captured_at": "2026-09-06T12:00:00+00:00",
        "matchup": {"week": 1, "team": "Shiba Innu", "opponent": "Team Beta"},
        "scoreboard": [{"week": 1, "team1": "Shiba Innu", "team2": "Team Beta",
                        "score1": 120.5, "score2": 99.0}],
        "standings": [{"rank": 1, "team": "Shiba Innu", "record": "1-0-0"}],
        "rosters": {"Team Beta": [
            {"name": "Old Qb", "team": "KC", "position": "QB", "slot": "QB",
             "injury_status": "", "proj": 11.1},
            {"name": "Steelers D/ST", "team": "", "position": "DEF", "slot": "DEF",
             "injury_status": "", "proj": null}]}
    });
    // A LATER light-run snapshot of the same week without rosters must not
    // win the pick — otherwise the opponent side renders empty.
    let light = json!({
        "captured_at": "2026-09-08T12:00:00+00:00",
        "matchup": {"week": 1, "team": "Shiba Innu", "opponent": "Team Beta"},
        "scoreboard": [{"week": 1, "team1": "Shiba Innu", "team2": "Team Beta",
                        "score1": 120.5, "score2": 99.0}],
        "standings": [{"rank": 1, "team": "Shiba Innu", "record": "1-0-0"}]
    });
    let mut hist_text = old.to_string();
    hist_text.push('\n');
    hist_text.push_str(&light.to_string());
    hist_text.push('\n');
    std::fs::write(root.join("logs/league-report.jsonl"), hist_text).unwrap();
    let arch = json!({"week": 1, "players": {"old qb": {"points": 12.34}},
                    "def_named": {}, "def": {"DEF:PIT": -3.0},
                    "totals": {"Team Beta": 12.34}, "games": {}});
    std::fs::write(root.join("logs/live-points-week-1.json"), arch.to_string()).unwrap();
    let app = router(cfg(&root));
    let (status, html) = get_body(
        app.clone(),
        "/league/teamview?week=1&a=Team%20Beta&b=Team%20Beta",
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert!(html.contains("Old Qb")); // historical roster, not the current one
    assert!(html.contains("12.34")); // archived per-player finals
                                     // b is FORCED to the scheduled opponent (Shiba Innu) even though the
                                     // URL asked for b=Team Beta — past-week opponents are not pickable.
    assert!(html.contains("Shiba Innu"));
    assert!(html.contains("120.50")); // Shiba's official final on the b side
    assert!(html.contains("Quarter Back")); // b side = our week-1 plan
    assert!(html.contains("99.00")); // a side = Team Beta's own final
    assert!(html.contains("-3.00")); // DEF resolved via abbr, not def_named
    assert!(html.contains("finals from the archive"));
    assert!(html.contains("tv-week on")); // selector highlights week 1
    assert!(html.contains("tv-locked")); // opponent shown as fixed text
    assert!(!html.contains("<select name=\"b\"")); // no opponent dropdown
    assert!(!html.contains("players remaining")); // suppressed for past weeks
    let (_, html) = get_body(app, "/league/teamview").await;
    assert!(html.contains("Enemy Qb") && !html.contains("Old Qb"));
}

#[tokio::test]
async fn teamview_past_own_side_borrows_current_teampos() {
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    teamview_fixtures(&root); // current rosters + week-1 operator plan
                              // Week-1 snapshot WITHOUT our own roster (pre own-roster capture era).
    let old = json!({
        "captured_at": "2026-09-06T12:00:00+00:00",
        "matchup": {"week": 1, "team": "Shiba Innu", "opponent": "Team Beta"},
        "scoreboard": [{"week": 1, "team1": "Shiba Innu", "team2": "Team Beta",
                        "score1": 120.5, "score2": 99.0}],
        "rosters": {"Team Beta": [
            {"name": "Enemy Qb", "team": "KC", "position": "QB", "slot": "QB",
             "injury_status": "", "proj": 15.2}]}
    });
    std::fs::write(
        root.join("logs/league-report.jsonl"),
        old.to_string() + "\n",
    )
    .unwrap();
    let arch = json!({"week": 1, "players": {"quarter back": {"points": 25.10}},
                    "def_named": {}, "def": {}, "totals": {}, "games": {}});
    std::fs::write(root.join("logs/live-points-week-1.json"), arch.to_string()).unwrap();
    let app = router(cfg(&root));
    let (status, html) = get_body(app, "/league/teamview?week=1").await;
    assert_eq!(status, StatusCode::OK);
    assert!(html.contains("25.10")); // archived points via the week-1 plan
    assert!(html.contains("SF - QB")); // team/pos borrowed from current roster
    assert!(html.contains("Enemy Qb")); // opponent from the historical roster
}

#[tokio::test]
async fn teamview_other_team_history_keeps_selected_team() {
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    teamview_fixtures(&root);
    let old = json!({
        "captured_at": "2026-09-06T12:00:00+00:00",
        "matchup": {"week": 1, "team": "Shiba Innu", "opponent": "Team Beta"},
        "scoreboard": [{"week": 1, "team1": "Shiba Innu", "team2": "Team Beta",
                        "score1": 120.5, "score2": 99.0}],
        "standings": [{"rank": 1, "team": "Shiba Innu", "record": "1-0-0"},
                      {"rank": 2, "team": "Team Beta", "record": "0-1-0"}],
        "rosters": {"Team Beta": [
            {"name": "Old Qb", "team": "KC", "position": "QB", "slot": "QB",
             "injury_status": "", "proj": 11.1}]}
    });
    std::fs::write(
        root.join("logs/league-report.jsonl"),
        old.to_string() + "\n",
    )
    .unwrap();
    let arch = json!({"week": 1,
                    "players": {"old qb": {"points": 12.34},
                                "quarter back": {"points": 25.10}},
                    "def_named": {}, "def": {}, "totals": {}, "games": {}});
    std::fs::write(root.join("logs/live-points-week-1.json"), arch.to_string()).unwrap();
    let app = router(cfg(&root));
    // Only a given: b must resolve to Team Beta's week-1 OPPONENT from the
    // historical scoreboard — not snap back to our own matchup.
    let (status, html) = get_body(app.clone(), "/league/teamview?week=1&a=Team%20Beta").await;
    assert_eq!(status, StatusCode::OK);
    assert!(html.contains("Old Qb")); // selected team's historical roster
    assert!(html.contains("12.34")); // its archived points
    assert!(html.contains("Quarter Back")); // opponent side = our week-1 plan
    assert!(html.contains("25.10"));
    // Week selector keeps the selected team; b is never carried (each
    // week's opponent is fixed by the schedule).
    assert!(html.contains("week=2&amp;a=Team%20Beta"));
    assert!(!html.contains("week=2&amp;a=Team%20Beta&amp;b="));
    // Team picker preselects the team; opponent is locked text, not a dropdown
    assert!(html.contains("<select name=\"a\""));
    assert!(html.contains("value=\"Team Beta\" selected"));
    assert!(html.contains("tv-locked"));
    assert!(!html.contains("<select name=\"b\""));
    // A stale/wrong b param must NOT override the scheduled opponent
    let (_, html) = get_body(
        app.clone(),
        "/league/teamview?week=1&a=Team%20Beta&b=No%20Such%20Team",
    )
    .await;
    assert!(html.contains("Quarter Back")); // still Shiba Innu's week-1 plan
    assert!(!html.contains("No Such Team"));
    // Current week with a only: opponent from the current scoreboard,
    // and the b dropdown IS available for ad-hoc comparison
    let (_, html) = get_body(app, "/league/teamview?a=Team%20Beta").await;
    assert!(html.contains("Enemy Qb") && html.contains("Quarter Back"));
    assert!(html.contains("<select name=\"b\""));
}

#[tokio::test]
async fn teamview_past_header_uses_final_scoreboard() {
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    teamview_fixtures(&root);
    // With-rosters snapshot carries MID-WEEK scores...
    let mid = json!({
        "captured_at": "2026-09-06T12:00:00+00:00",
        "matchup": {"week": 1, "team": "Shiba Innu", "opponent": "Team Beta"},
        "scoreboard": [{"week": 1, "team1": "Shiba Innu", "team2": "Team Beta",
                        "score1": 80.0, "score2": 60.0}],
        "standings": [{"rank": 1, "team": "Shiba Innu", "record": "0-0-0"},
                      {"rank": 2, "team": "Team Beta", "record": "0-0-0"}],
        "rosters": {"Team Beta": [
            {"name": "Old Qb", "team": "KC", "position": "QB", "slot": "QB",
             "injury_status": "", "proj": 11.1}]}
    });
    // ...the later light run carries the FINALS (no rosters).
    let fin = json!({
        "captured_at": "2026-09-08T12:00:00+00:00",
        "matchup": {"week": 1, "team": "Shiba Innu", "opponent": "Team Beta"},
        "scoreboard": [{"week": 1, "team1": "Shiba Innu", "team2": "Team Beta",
                        "score1": 130.0, "score2": 105.5}],
        "standings": [{"rank": 1, "team": "Shiba Innu", "record": "1-0-0"},
                      {"rank": 2, "team": "Team Beta", "record": "0-1-0"}]
    });
    let text = format!("{}\n{}\n", mid, fin);
    std::fs::write(root.join("logs/league-report.jsonl"), text).unwrap();
    let arch = json!({"week": 1, "players": {"old qb": {"points": 12.34}},
                    "def_named": {}, "def": {}, "totals": {}, "games": {}});
    std::fs::write(root.join("logs/live-points-week-1.json"), arch.to_string()).unwrap();
    let app = router(cfg(&root));
    let (status, html) = get_body(app, "/league/teamview?week=1&a=Team%20Beta").await;
    assert_eq!(status, StatusCode::OK);
    assert!(html.contains("Old Qb")); // rosters still from the mid snapshot
    assert!(html.contains("105.50")); // header = FINAL score, not 60.00
    assert!(!html.contains("60.00"));
    assert!(html.contains("0-1-0")); // final record overlaid too
}

#[tokio::test]
async fn teamview_query_override_and_missing_roster() {
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    teamview_fixtures(&root);
    let app = router(cfg(&root));
    let (status, html) =
        get_body(app.clone(), "/league/teamview?a=Team%20Beta&b=Team%20Beta").await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(html.matches("tv-name\">Enemy Qb").count(), 2); // both sides same roster
    let (status, html) = get_body(app, "/league/teamview?a=No%20Such%20Team&b=Team%20Beta").await;
    assert_eq!(status, StatusCode::OK);
    assert!(html.contains("roster for one of these teams"));
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
