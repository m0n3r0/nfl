//! Hermetic tests: pin store parity with src/pins.py, artifact parsing,
//! native page rendering through the real templates — fantasy AND the
//! prediction-engine analytics pages (data/web fixtures).

use std::path::{Path, PathBuf};
use std::time::Duration;

use axum::body::Body;
use axum::http::{header, Request, StatusCode};
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
    // Copy every template including partials — never let a new include go
    // stale in the fixture (this bit us once with the team-picker partial).
    for entry in std::fs::read_dir(&tpl_src).unwrap() {
        let src = entry.unwrap().path();
        if src.extension().is_some_and(|e| e == "html") {
            std::fs::copy(&src, tpl_dst.join(src.file_name().unwrap())).unwrap();
        }
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
async fn team_page_renders_plan_and_pin_buttons() {
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    write_runs(&root, &[operator_record("ok")]);
    // The on-page picker needs the league snapshot for its team list.
    std::fs::write(
        root.join("logs/league-report.json"),
        json!({"standings": [{"team": "Shiba Innu"}, {"team": "Team Beta"}]}).to_string(),
    )
    .unwrap();
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
    // On-page team picker (NOT the top menu): all teams listed, my team
    // selected, each option jumps to that team's page.
    assert!(html.contains("Viewing team:"));
    assert!(html.contains("<select id=\"team-pick\""));
    assert!(html.contains("/league/team/Team%20Beta"));
    assert!(
        html.contains("value=\"/league/team/Shiba%20Innu\" selected")
            || html.contains("value=\"&#x2f;league&#x2f;team&#x2f;Shiba%20Innu\" selected")
    );
}

#[tokio::test]
async fn team_page_picker_is_absent_from_top_menu() {
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    write_runs(&root, &[operator_record("ok")]);
    let (_, html) = get_body(router(cfg(&root)), "/team").await;
    // The FD nation header still has plain links, no select.
    let header = html.split("</header>").next().unwrap_or("");
    assert!(!header.contains("<select"));
    assert!(header.contains(">My Team</a>"));
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
    // Mirrors the real crontab — the Wed waiver job carries --jev 5.
    assert!(html.contains("11 20 * * 3"));
    assert!(html.contains("--waiver-scan --refresh-data --jev 5"));
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
    // FD nation nav is plain links — no team-picker dropdown.
    assert!(html.contains(">My Team</a>"));
    assert!(html.contains("/league/team/Team%20Beta")); // standings link
    assert!(html.contains("mu-score mu-leading"));
    assert!(html.contains("Week 2 matchups"));
    assert!(html.contains("/league/matchup/Shiba%20Innu"));
    // Yahoo /matchup interaction: the whole card highlights on hover and
    // is clickable anywhere (stretched link); team names stay separate links.
    assert!(html.contains("class=\"mu-open\""));
    assert!(html.contains("mu-card:hover"));
    assert!(html.contains(":focus-within"));
    let (status, html) = get_body(app.clone(), "/league/team/Team%20Beta").await;
    assert_eq!(status, StatusCode::OK);
    assert!(html.contains("Beta Rb"));
    assert!(html.contains("Playing us this week")); // opponent matchup card
    assert!(html.contains("/league/matchup/Team%20Beta")); // Matchup link
    let (_, team_html) = get_body(app.clone(), "/team").await;
    assert!(team_html.contains("<h1>My Team")); // /team page still loads
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

// --- Matchup (players side by side) ---

fn matchup_fixtures(root: &Path) {
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
async fn matchup_pairs_players_by_slot() {
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    matchup_fixtures(&root);
    let (status, html) = get_body(router(cfg(&root)), "/league/matchup").await;
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
async fn legacy_teamview_route_redirects_to_matchup_with_query() {
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    let app = router(cfg(&root));
    // Old bookmarks 302 to the new path with the query string intact.
    let res = app
        .clone()
        .oneshot(
            Request::builder()
                .uri("/league/teamview?a=Team%20Beta&week=2")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::FOUND);
    assert_eq!(
        res.headers().get(header::LOCATION).unwrap(),
        "/league/matchup?a=Team%20Beta&week=2"
    );
    // The redirect target itself renders the matchup page.
    let (status, html) = get_body(app, "/league/matchup?a=Team%20Beta").await;
    assert_eq!(status, StatusCode::OK);
    assert!(html.contains("tv-tname\">Team Beta<"));
}

#[tokio::test]
async fn matchup_path_route_selects_team_and_schedule_opponent() {
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    matchup_fixtures(&root);
    let app = router(cfg(&root));
    // Clean path URL: team in the path, no ?a=&b= query needed.
    let (status, html) = get_body(app.clone(), "/league/matchup/Team%20Beta").await;
    assert_eq!(status, StatusCode::OK);
    let names: Vec<&str> = html.split("tv-tname\">").skip(1).collect();
    assert!(names.len() >= 2);
    assert!(names[0].starts_with("Team Beta"));
    assert!(names[1].starts_with("Shiba Innu")); // schedule opponent
}

#[tokio::test]
async fn matchup_current_opponent_is_schedule_locked_no_dropdown() {
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    matchup_fixtures(&root); // week 2: Shiba Innu vs Team Beta
    let app = router(cfg(&root));
    // No opponent dropdown in the current week — only team A is selectable.
    let (_, html) = get_body(app.clone(), "/league/matchup").await;
    assert!(!html.contains("<select name=\"b\""));
    assert!(html.contains("tv-locked"));
    assert!(!html.contains("TV_OPPONENTS"));
    // A stale b param must NOT pair a team with the wrong opponent.
    let (_, html) = get_body(app, "/league/matchup?a=Shiba%20Innu&b=No%20Such%20Team").await;
    assert!(!html.contains("No Such Team"));
    assert!(html.contains("tv-tname\">Team Beta<")); // still the scheduled opponent
}

#[tokio::test]
async fn matchup_historical_week_from_archive() {
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    matchup_fixtures(&root); // current week 2; operator run for week 1 exists
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
        "/league/matchup?week=1&a=Team%20Beta&b=Team%20Beta",
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
    let (_, html) = get_body(app, "/league/matchup").await;
    assert!(html.contains("Enemy Qb") && !html.contains("Old Qb"));
}

#[tokio::test]
async fn matchup_past_own_side_borrows_current_teampos() {
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    matchup_fixtures(&root); // current rosters + week-1 operator plan
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
    let (status, html) = get_body(app, "/league/matchup?week=1").await;
    assert_eq!(status, StatusCode::OK);
    assert!(html.contains("25.10")); // archived points via the week-1 plan
    assert!(html.contains("SF - QB")); // team/pos borrowed from current roster
    assert!(html.contains("Enemy Qb")); // opponent from the historical roster
}

#[test]
fn matchup_def_abbr_resolves_city_and_nickname_forms() {
    use crate::pages::matchup_def_abbr;
    // Yahoo flips DEF display between nickname and city/state run to run.
    assert_eq!(matchup_def_abbr("Bears"), Some("CHI"));
    assert_eq!(matchup_def_abbr("Chicago"), Some("CHI"));
    assert_eq!(matchup_def_abbr("Minnesota"), Some("MIN"));
    assert_eq!(matchup_def_abbr("Jacksonville"), Some("JAX"));
    assert_eq!(matchup_def_abbr("Steelers D/ST"), Some("PIT"));
    assert_eq!(matchup_def_abbr("Pittsburgh"), Some("PIT"));
    // two-team cities resolve on the full name, never the first token
    assert_eq!(matchup_def_abbr("New York Giants"), Some("NYG"));
    assert_eq!(matchup_def_abbr("Los Angeles Rams"), Some("LAR"));
    assert_eq!(matchup_def_abbr("Los Angeles Chargers"), Some("LAC"));
    assert_eq!(matchup_def_abbr("New York"), None);
    assert_eq!(matchup_def_abbr("Los Angeles"), None);
    assert_eq!(matchup_def_abbr("Not A Team"), None);
}

#[tokio::test]
async fn matchup_past_def_resolves_city_name_from_plan() {
    // The week-8 production bug: the operator plan carries the DEF under
    // its CITY name ("Chicago") with no team field, while the archive keys
    // points by abbr/nickname — every lookup missed and Fan Pts showed "–".
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    matchup_fixtures(&root); // current week 2; Shiba roster has no DEF row
    let mut run = operator_record("ok");
    run["proposal"]["plan"].as_array_mut().unwrap().push(
        json!({"current_slot": "DEF", "proposed_slot": "DEF",
                     "name": "Chicago", "position": "DEF", "proj_week": null,
                     "note": "no projection data; kept, locked",
                     "yahoo_id": "100003"}),
    );
    write_runs(&root, &[run]);
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
    let arch = json!({"week": 1, "players": {},
                    "def_named": {"Bears": 6.0}, "def": {"DEF:CHI": 6.0},
                    "totals": {}, "games": {}});
    std::fs::write(root.join("logs/live-points-week-1.json"), arch.to_string()).unwrap();
    let app = router(cfg(&root));
    let (status, html) = get_body(app, "/league/matchup?week=1").await;
    assert_eq!(status, StatusCode::OK);
    assert!(html.contains("Chicago")); // the plan row renders
    assert!(html.contains("6.00")); // city name -> CHI -> archived DEF points
}

#[tokio::test]
async fn matchup_other_team_history_keeps_selected_team() {
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    matchup_fixtures(&root);
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
    let (status, html) = get_body(app.clone(), "/league/matchup?week=1&a=Team%20Beta").await;
    assert_eq!(status, StatusCode::OK);
    assert!(html.contains("Old Qb")); // selected team's historical roster
    assert!(html.contains("12.34")); // its archived points
    assert!(html.contains("Quarter Back")); // opponent side = our week-1 plan
    assert!(html.contains("25.10"));
    // Week selector keeps the selected team in the path; b is never carried
    // (each week's opponent is fixed by the schedule).
    assert!(html.contains("/league/matchup/Team%20Beta?week=2"));
    // Team picker preselects the team; opponent is locked text, not a dropdown
    assert!(html.contains("<select name=\"a\""));
    assert!(html.contains("value=\"Team Beta\" selected"));
    assert!(html.contains("tv-locked"));
    assert!(!html.contains("<select name=\"b\""));
    // A stale/wrong b param must NOT override the scheduled opponent
    let (_, html) = get_body(
        app.clone(),
        "/league/matchup?week=1&a=Team%20Beta&b=No%20Such%20Team",
    )
    .await;
    assert!(html.contains("Quarter Back")); // still Shiba Innu's week-1 plan
    assert!(!html.contains("No Such Team"));
    // Current week with a only: opponent from the current scoreboard.
    // There is NO b dropdown — the opponent is always schedule-locked.
    let (_, html) = get_body(app, "/league/matchup?a=Team%20Beta").await;
    assert!(html.contains("Enemy Qb") && html.contains("Quarter Back"));
    assert!(!html.contains("<select name=\"b\""));
    assert!(html.contains("tv-locked"));
}

#[tokio::test]
async fn matchup_past_header_uses_final_scoreboard() {
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    matchup_fixtures(&root);
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
    let (status, html) = get_body(app, "/league/matchup?week=1&a=Team%20Beta").await;
    assert_eq!(status, StatusCode::OK);
    assert!(html.contains("Old Qb")); // rosters still from the mid snapshot
    assert!(html.contains("105.50")); // header = FINAL score, not 60.00
    assert!(!html.contains("60.00"));
    assert!(html.contains("0-1-0")); // final record overlaid too
}

#[tokio::test]
async fn matchup_query_override_and_missing_roster() {
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    matchup_fixtures(&root);
    let app = router(cfg(&root));
    // b is ignored — Team Beta's scheduled opponent is Shiba Innu, not
    // Team Beta. Only one side shows Enemy Qb now.
    let (status, html) = get_body(app.clone(), "/league/matchup?a=Team%20Beta&b=Team%20Beta").await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(html.matches("tv-name\">Enemy Qb").count(), 1);
    assert!(html.contains("tv-tname\">Shiba Innu<")); // schedule-locked opponent
    let (status, html) = get_body(app, "/league/matchup?a=No%20Such%20Team&b=Team%20Beta").await;
    assert_eq!(status, StatusCode::OK);
    assert!(html.contains("roster for one of these teams"));
}

#[tokio::test]
async fn matchup_current_week_follows_scoreboard_over_matchup() {
    // Rollover window: the matchup page can lag a week behind while the
    // scoreboard already shows the new week. snapshot_week() says the
    // scoreboard is authoritative — the new week must be treated as the
    // CURRENT week (not routed to the history/archive path).
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    matchup_fixtures(&root); // matchup week 2, scoreboard week 2, live week 2
    let mut report: Value = serde_json::from_str(
        &std::fs::read_to_string(root.join("logs/league-report.json")).unwrap(),
    )
    .unwrap();
    report["scoreboard"][0]["week"] = json!(3);
    std::fs::write(root.join("logs/league-report.json"), report.to_string()).unwrap();
    let live = json!({"week": 3, "players": {}, "def_named": {}, "totals": {},
                      "games": {}});
    std::fs::write(root.join("logs/live-points.json"), live.to_string()).unwrap();
    let app = router(cfg(&root));
    let (status, html) = get_body(app.clone(), "/league/matchup").await;
    assert_eq!(status, StatusCode::OK);
    assert!(html.contains("data-week=\"3\""), "{html}");
    assert!(!html.contains("finals from the archive"), "{html}");
    // Asking for the true current week must not take the past path.
    let (_, html) = get_body(app.clone(), "/league/matchup?week=3").await;
    assert!(!html.contains("finals from the archive"), "{html}");
    // Week 2 is the past one now.
    let (_, html) = get_body(app, "/league/matchup?week=2").await;
    assert!(html.contains("finals from the archive"), "{html}");
}

#[tokio::test]
async fn matchup_week_param_is_bounded() {
    // The week selector allocates 1..=max_week — an unbounded week param
    // would be a memory-exhaustion DoS. Out-of-range and future weeks (no
    // snapshots can exist) fall back to the current week.
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    matchup_fixtures(&root); // current week 2
    let app = router(cfg(&root));
    for uri in [
        "/league/matchup?week=999999999999",
        "/league/matchup?week=-5",
        "/league/matchup?week=0",
        "/league/matchup?week=3", // future week
    ] {
        let (status, html) = get_body(app.clone(), uri).await;
        assert_eq!(status, StatusCode::OK, "{uri}");
        assert!(html.contains("Quarter Back"), "{uri}"); // current week rendered
        assert!(!html.contains("finals from the archive"), "{uri}");
    }
    // Past weeks still work.
    let (_, html) = get_body(app, "/league/matchup?week=1").await;
    assert!(html.contains("finals from the archive"));
}

// --- prediction-engine analytics (native, data/web artifacts) ---

fn web_fixtures(root: &Path) {
    let web = root.join("data/web");
    std::fs::create_dir_all(web.join("players")).unwrap();
    let dash = json!({
        "generated_at": "2026-11-20T00:00:00+00:00", "season": 2026, "stats_season": 2026,
        "projections": [{"rank": 1, "player_id": "p1", "player_display_name": "Alpha QB",
                         "position": "QB", "last_team": "BUF", "proj_ppg": 22.0,
                         "proj_total": 374.0}],
        "backtest": {"model_no_spread": {"accuracy": 0.612, "log_loss": 0.654, "brier": 0.231},
                     "model_with_spread": {"accuracy": 0.68, "log_loss": 0.616, "brier": 0.214},
                     "vegas": 0.684, "n_test": 544, "cv_mean": 0.663,
                     "cv_folds": [{"test_season": 2024, "accuracy": 0.695}]}
    });
    std::fs::write(web.join("dashboard.json"), dash.to_string()).unwrap();
    let players = json!({
        "players": [
            {"rank": 1, "player_id": "p1", "player_display_name": "Alpha QB",
             "position": "QB", "last_team": "BUF", "games": 17, "baseline_ppg": 21.0,
             "role_share": 0.6, "team_sos": 0.1, "proj_ppg": 22.0, "proj_total": 374.0},
            {"rank": 2, "player_id": "p2", "player_display_name": "Beta RB",
             "position": "RB", "last_team": "DET", "games": 17, "baseline_ppg": 12.0,
             "role_share": 0.55, "team_sos": -0.2, "proj_ppg": 12.5, "proj_total": 212.5}],
        "positions": ["QB", "RB", "WR", "TE"]
    });
    std::fs::write(web.join("players.json"), players.to_string()).unwrap();
    let p1 = json!({"pid": "p1", "name": "Alpha QB", "pos": "QB",
                  "history": [{"season": 2025, "games": 17, "ppg": 21.5}],
                  "projection": {"proj_ppg": 22.0, "proj_total": 374.0,
                                 "baseline_ppg": 21.0, "role_share": 0.6, "team_sos": 0.1}});
    std::fs::write(web.join("players/p1.json"), p1.to_string()).unwrap();
    let preds = json!({
        "season": 2026, "weeks": [1, 2],
        "predictions": [
            {"week": 1, "home_team": "BUF", "away_team": "KC", "home_win_prob": 0.62,
             "epa_diff": 0.08, "spread": null, "model": "no_spread"},
            {"week": 2, "home_team": "DET", "away_team": "GB", "home_win_prob": 0.55,
             "epa_diff": 0.02, "spread": -2.5, "model": "with_spread"}]
    });
    std::fs::write(web.join("predictions.json"), preds.to_string()).unwrap();
    let ratings = json!({
        "seasons": [2022, 2025, 2026],
        "ratings": {"2022-1": [],
                    "2026-1": [{"team": "BUF", "off_epa_per_play": 0.12,
                                "def_epa_allowed_per_play": 0.01, "off_rz_td_rate": 0.6,
                                "off_3d_epa_per_play": 0.05, "off_pass_epa_pp": 0.15,
                                "off_rush_epa_pp": 0.02}]}
    });
    std::fs::write(web.join("ratings.json"), ratings.to_string()).unwrap();
    let strategy = json!({
        "seasons": [2025, 2026],
        "strategy": {"2026": {"BUF": {"overall": {"epa_per_play": 0.1, "success_rate": 0.45, "n": 100},
                                      "red_zone": {"epa_per_play": 0.2, "success_rate": 0.5, "n": 20},
                                      "third_down": {"epa_per_play": 0.05, "success_rate": 0.4, "n": 30},
                                      "pass": {"epa_per_play": 0.15, "success_rate": 0.44, "n": 60},
                                      "rush": {"epa_per_play": 0.02, "success_rate": 0.46, "n": 40},
                                      "pass_rate": 0.6, "shotgun_rate": 0.7}}}
    });
    std::fs::write(web.join("strategy.json"), strategy.to_string()).unwrap();
    let sos = json!({"sos": [{"rank": 1, "team": "BUF", "sos": 0.3}]});
    std::fs::write(web.join("sos.json"), sos.to_string()).unwrap();
    let mc = json!({"evaluation": {"n_test": 544}, "cv": {"mean_accuracy": 0.663}});
    std::fs::write(web.join("modelcard.json"), mc.to_string()).unwrap();
}

#[tokio::test]
async fn analytics_pages_render_from_artifacts() {
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    web_fixtures(&root);
    let app = router(cfg(&root));
    let (status, html) = get_body(app.clone(), "/dashboard").await;
    assert_eq!(status, StatusCode::OK);
    assert!(html.contains("Alpha QB") && html.contains("0.684"));
    assert!(html.contains("2024=0.695")); // CV fold
    let (_, html) = get_body(app.clone(), "/players").await;
    assert!(html.contains("Alpha QB") && html.contains("Beta RB"));
    let (_, html) = get_body(app.clone(), "/players?q=beta&pos=RB").await;
    assert!(html.contains("Beta RB") && !html.contains("Alpha QB")); // filter
    let (_, html) = get_body(app.clone(), "/player/p1").await;
    assert!(html.contains("Alpha QB") && html.contains("21.5")); // history ppg
    let (status, _) = get_body(app.clone(), "/player/nope").await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    let (status, _) = get_body(app.clone(), "/player/..%2f..%2fetc").await;
    assert_eq!(status, StatusCode::NOT_FOUND); // traversal guard
    let (_, html) = get_body(app.clone(), "/predictions").await;
    assert!(html.contains("BUF") && html.contains("DET"));
    let (_, html) = get_body(app.clone(), "/predictions?week=1").await;
    assert!(html.contains("BUF") && !html.contains("DET")); // week filter
    assert!(html.contains("—")); // null spread dash
    let (_, html) = get_body(app.clone(), "/ratings").await;
    assert!(html.contains("BUF") && html.contains("0.12")); // default = latest season
    let (_, html) = get_body(app.clone(), "/ratings?season=2022&week=1").await;
    assert!(html.contains("No ratings for 2022 week 1")); // honest empty notice
    let (_, html) = get_body(app.clone(), "/strategy?team=BUF").await;
    assert!(html.contains("0.45") && html.contains("Shotgun"), "{html}"); // breakdown + rates
    let (_, html) = get_body(app.clone(), "/strategy?team=XXX").await;
    assert!(html.contains("No plays found"));
    let (_, html) = get_body(app, "/sos").await;
    assert!(html.contains("BUF") && html.contains("0.3"));
}

#[tokio::test]
async fn analytics_apis_and_missing_artifacts() {
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    web_fixtures(&root);
    let app = router(cfg(&root));
    let (status, body) = get_body(app.clone(), "/api/predictions?week=2").await;
    assert_eq!(status, StatusCode::OK);
    let v: Value = serde_json::from_str(&body).unwrap();
    assert_eq!(v.as_array().unwrap().len(), 1);
    assert_eq!(v[0]["home_team"], "DET");
    let (_, body) = get_body(app.clone(), "/api/modelcard").await;
    let v: Value = serde_json::from_str(&body).unwrap();
    assert_eq!(v["evaluation"]["n_test"], 544);
    // No artifacts at all -> honest notice pages, 404 JSON APIs, no 500s.
    let bare = fixture_root(&tempfile_dir());
    let app = router(cfg(&bare));
    for path in [
        "/dashboard",
        "/players",
        "/predictions",
        "/ratings",
        "/strategy",
        "/sos",
    ] {
        let (status, html) = get_body(app.clone(), path).await;
        assert_eq!(status, StatusCode::OK, "{path}");
        assert!(html.contains("tools/predictions_report.py"), "{path}");
    }
    let (status, _) = get_body(app.clone(), "/api/predictions").await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    let (status, _) = get_body(app, "/no/such/route").await;
    assert_eq!(status, StatusCode::NOT_FOUND); // fallback, no upstream
}

#[tokio::test]
async fn predictions_tolerate_null_probability() {
    // records() = pandas to_json: NaN becomes null. A null home_win_prob must
    // not 500 — minijinja cannot multiply none (same guard idiom as spread).
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    web_fixtures(&root);
    let preds = json!({
        "season": 2026, "weeks": [1],
        "predictions": [{"week": 1, "home_team": "BUF", "away_team": "KC",
                         "home_win_prob": null, "epa_diff": null,
                         "spread": null, "model": "no_spread"}]
    });
    std::fs::write(root.join("data/web/predictions.json"), preds.to_string()).unwrap();
    let (status, html) = get_body(router(cfg(&root)), "/predictions").await;
    assert_eq!(status, StatusCode::OK);
    assert!(html.contains("BUF") && html.contains("—"), "{html}");
}

#[tokio::test]
async fn dashboard_tolerates_partial_artifact() {
    // Schema drift / a hand-truncated artifact: minijinja errors on attribute
    // access OF an undefined `backtest` — the card must be skipped, not 500.
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    web_fixtures(&root);
    let dash = json!({"season": 2026, "stats_season": 2026, "projections": []});
    std::fs::write(root.join("data/web/dashboard.json"), dash.to_string()).unwrap();
    let (status, html) = get_body(router(cfg(&root)), "/dashboard").await;
    assert_eq!(status, StatusCode::OK);
    assert!(html.contains("2026"), "{html}");
}

#[tokio::test]
async fn strategy_tolerates_partial_breakdown() {
    // A breakdown missing situation keys must render what it has — indexing
    // a missing key yields undefined, and .epa_per_play on undefined errors.
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    web_fixtures(&root);
    let strategy = json!({"seasons": [2026], "strategy": {"2026": {"BUF": {
        "overall": {"epa_per_play": 0.1, "success_rate": 0.45, "n": 100},
        "pass_rate": 0.6, "shotgun_rate": 0.7}}}});
    std::fs::write(root.join("data/web/strategy.json"), strategy.to_string()).unwrap();
    let (status, html) = get_body(router(cfg(&root)), "/strategy?team=BUF").await;
    assert_eq!(status, StatusCode::OK);
    assert!(html.contains("0.45"), "{html}");
    assert!(!html.contains("red zone"), "{html}"); // missing row skipped
}

#[tokio::test]
async fn logos_reject_hidden_files() {
    // The /logos docstring promises "no hidden files" — hold it to that.
    let tmp = tempfile_dir();
    let root = fixture_root(&tmp);
    std::fs::create_dir_all(root.join("data/logos")).unwrap();
    std::fs::write(root.join("data/logos/.secret"), b"nope").unwrap();
    let (status, _) = get_body(router(cfg(&root)), "/logos/.secret").await;
    assert_eq!(status, StatusCode::NOT_FOUND);
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
