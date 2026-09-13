"""Hermetic tests for the fantasy pages of the local web UI (web/app.py).

The pages under test read only local artifacts (logs/team-operator.jsonl and
logs/league-report.json); tests point those paths at tmp fixtures. Fixtures
use fake team names — this repo is public, real manager names never commit.
"""

from __future__ import annotations

import json

import pytest

import web.app as webapp


@pytest.fixture
def client():
    webapp.app.config["TESTING"] = True
    return webapp.app.test_client()


def operator_record(status="ok", week=1):
    return {
        "time": "2026-09-12T23:24:01+00:00",
        "status": status,
        "week": week,
        "record": "0-0-0",
        "waiver_priority": 4,
        "matchup": {"week": week, "team": "Shiba Innu", "score": 35.6,
                    "opponent": "Team Beta", "opponent_score": 0.0,
                    "team_proj": 100.7, "opponent_proj": 112.7},
        "proposal": {"moves": [], "plan": [
            {"current_slot": "QB", "proposed_slot": "QB", "name": "Quarter Back",
             "position": "QB", "proj_week": 17.8, "note": "locked", "yahoo_id": "1"},
            {"current_slot": "RB", "proposed_slot": "RB", "name": "Running Back",
             "position": "RB", "proj_week": 18.8, "note": "", "yahoo_id": "2"},
        ]},
        "monitor": {"needs_attention": False, "locked_starters": ["Quarter Back"],
                    "injury_tags": [], "bye_players": [], "week": week,
                    "roster_count": 15, "starter_count": 9},
    }


def league_report():
    return {
        "captured_at": "2026-09-13T12:19:00+00:00",
        "standings": [
            {"rank": 1, "team": "Team Alpha", "record": "1-0-0",
             "points_for": 140.5, "points_against": 90.1, "waiver": 3},
            {"rank": 2, "team": "Shiba Innu", "record": "1-0-0",
             "points_for": 130.2, "points_against": 95.4, "waiver": 4},
            {"rank": 3, "team": "Team Beta", "record": "0-1-0",
             "points_for": 95.4, "points_against": 130.2, "waiver": 7},
        ],
        "matchup": {"week": 1, "team": "Shiba Innu", "score": 35.6,
                    "opponent": "Team Beta", "opponent_score": 0.0,
                    "team_proj": 100.7, "opponent_proj": 112.7},
    }


def write_jsonl(path, records):
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


def test_team_page_renders_matchup_and_lineup(client, tmp_path, monkeypatch):
    audit = tmp_path / "audit.jsonl"
    write_jsonl(audit, [operator_record()])
    monkeypatch.setattr(webapp, "OPERATOR_AUDIT", audit)
    html = client.get("/team").get_data(as_text=True)
    assert "Shiba Innu" in html
    assert "Team Beta" in html
    assert "Quarter Back" in html and "17.8" in html
    assert "0 move(s)" in html


def test_team_page_without_audit_shows_notice(client, tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "OPERATOR_AUDIT", tmp_path / "missing.jsonl")
    html = client.get("/team").get_data(as_text=True)
    assert "No operator report yet" in html


def test_team_page_falls_back_to_last_ok_run(client, tmp_path, monkeypatch):
    audit = tmp_path / "audit.jsonl"
    newest_first = [operator_record(status="ok"),  # older line first in file
                    {"time": "2026-09-13T11:24:01+00:00", "status": "waf_blocked"}]
    write_jsonl(audit, newest_first)
    monkeypatch.setattr(webapp, "OPERATOR_AUDIT", audit)
    html = client.get("/team").get_data(as_text=True)
    assert "waf_blocked" in html  # banner reports the newest run
    assert "Shiba Innu" in html   # body still shows the last healthy report


def test_league_page_renders_standings_and_marks_my_team(client, tmp_path, monkeypatch):
    snap = tmp_path / "league.json"
    snap.write_text(json.dumps(league_report()), encoding="utf-8")
    monkeypatch.setattr(webapp, "LEAGUE_REPORT", snap)
    html = client.get("/league").get_data(as_text=True)
    assert "Team Alpha" in html
    assert '<b><a href="/league/team/Shiba%20Innu">Shiba Innu</a></b>' in html
    assert '<a href="/league/team/Team%20Alpha">Team Alpha</a>' in html
    assert "140.5" in html


def test_league_page_missing_file_shows_notice(client, tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "LEAGUE_REPORT", tmp_path / "missing.json")
    html = client.get("/league").get_data(as_text=True)
    assert "No league snapshot yet" in html


def test_league_page_waf_blocked_notice(client, tmp_path, monkeypatch):
    snap = tmp_path / "league.json"
    snap.write_text(json.dumps({"status": "waf_blocked",
                                "captured_at": "2026-09-13T12:19:00+00:00"}), encoding="utf-8")
    monkeypatch.setattr(webapp, "LEAGUE_REPORT", snap)
    html = client.get("/league").get_data(as_text=True)
    assert "WAF-throttled" in html


def test_cron_page_lists_runs_and_schedule(client, tmp_path, monkeypatch):
    audit = tmp_path / "audit.jsonl"
    write_jsonl(audit, [operator_record(), {"time": "2026-09-13T11:24:01+00:00",
                                            "status": "already_running"}])
    monkeypatch.setattr(webapp, "OPERATOR_AUDIT", audit)
    html = client.get("/cron").get_data(as_text=True)
    assert "already_running" in html
    assert "47 23 * * 0" in html  # schedule table rendered
    assert "league_report.py --all-rosters" in html


def test_nav_contains_fantasy_links(client, tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "OPERATOR_AUDIT", tmp_path / "missing.jsonl")
    html = client.get("/team").get_data(as_text=True)
    for href in ('href="/team"', 'href="/league"', 'href="/cron"'):
        assert href in html


def test_nav_groups_yahoo_pages_apart_from_prediction_pages(client, tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "OPERATOR_AUDIT", tmp_path / "missing.jsonl")
    html = client.get("/team").get_data(as_text=True)
    assert "FD nation" in html and "Prediction engines" in html
    # Yahoo group comes first, led by its label; prediction links live after
    # the second label.
    assert html.index("FD nation") < html.index('href="/team"')
    assert html.index('href="/team"') < html.index("Prediction engines")
    assert html.index('href="/league"') < html.index("Prediction engines")
    assert html.index('href="/cron"') < html.index("Prediction engines")
    assert html.index('href="/players"') > html.index("Prediction engines")
    assert html.index('href="/predictions"') > html.index("Prediction engines")


def test_read_operator_runs_skips_bad_lines(tmp_path):
    audit = tmp_path / "audit.jsonl"
    audit.write_text('{"status": "ok", "time": "t1"}\nnot-json\n{"status": "ok", "time": "t2"}\n',
                     encoding="utf-8")
    runs = webapp._read_operator_runs(path=audit)
    assert [r["time"] for r in runs] == ["t2", "t1"]  # newest first, junk skipped


def test_read_league_report_tolerates_garbage(tmp_path):
    snap = tmp_path / "league.json"
    snap.write_text("{not json", encoding="utf-8")
    assert webapp._read_league_report(path=snap) is None
    snap.write_text('["a", "list"]', encoding="utf-8")
    assert webapp._read_league_report(path=snap) is None


def test_team_page_reports_unhealthy_runs_instead_of_empty(client, tmp_path, monkeypatch):
    audit = tmp_path / "audit.jsonl"
    write_jsonl(audit, [{"time": "2026-09-13T11:24:01+00:00", "status": "waf_blocked"}])
    monkeypatch.setattr(webapp, "OPERATOR_AUDIT", audit)
    html = client.get("/team").get_data(as_text=True)
    assert "No operator report yet" not in html
    assert "none is healthy yet" in html and "waf_blocked" in html


def test_read_operator_runs_skips_non_dict_lines(tmp_path):
    audit = tmp_path / "audit.jsonl"
    audit.write_text('[1, 2]\nnull\n{"status": "ok", "time": "t1"}\n"str"\n', encoding="utf-8")
    runs = webapp._read_operator_runs(path=audit)
    assert [r["time"] for r in runs] == ["t1"]


def test_read_operator_runs_tolerates_bad_utf8(tmp_path):
    audit = tmp_path / "audit.jsonl"
    audit.write_bytes(b'{"status": "ok", "time": "t1"}\n\xff\xfe{bad\n')
    runs = webapp._read_operator_runs(path=audit)
    assert [r["time"] for r in runs] == ["t1"]


def test_league_page_tolerates_non_dict_matchup(client, tmp_path, monkeypatch):
    snap = tmp_path / "league.json"
    snap.write_text(json.dumps({"captured_at": "t", "standings": [], "matchup": ["junk"]}),
                    encoding="utf-8")
    monkeypatch.setattr(webapp, "LEAGUE_REPORT", snap)
    assert client.get("/league").status_code == 200


def test_pages_tolerate_null_moves_in_audit(client, tmp_path, monkeypatch):
    audit = tmp_path / "audit.jsonl"
    record = operator_record()
    record["proposal"]["moves"] = None  # corrupted record must not 500 either page
    write_jsonl(audit, [record])
    monkeypatch.setattr(webapp, "OPERATOR_AUDIT", audit)
    assert client.get("/team").status_code == 200
    assert client.get("/cron").status_code == 200
    runs = webapp._read_operator_runs(path=audit)
    assert runs[0]["proposal"]["moves"] == []  # normalized at the boundary


def test_write_report_sequential_writes_and_no_tmp_residue(tmp_path):
    from tools.league_report import write_report
    out = tmp_path / "league.json"
    write_report(str(out), {"standings": [{"team": "First"}]})
    write_report(str(out), {"standings": [{"team": "Second"}]})
    persisted = json.loads(out.read_text())
    assert persisted["standings"] == [{"team": "Second"}]
    assert list(tmp_path.glob("*.tmp")) == []  # unique tmp files cleaned up


def test_league_report_write_report_atomic(tmp_path):
    from tools.league_report import write_report
    out = tmp_path / "sub" / "league-report.json"
    write_report(str(out), {"standings": []})
    persisted = json.loads(out.read_text())
    assert persisted["standings"] == []
    assert "captured_at" in persisted  # persisted copy is timestamped
    assert not (tmp_path / "sub" / "league-report.json.tmp").exists()


def league_snapshot_with_roster():
    report = league_report()
    report["opponent_team_id"] = "7"
    report["opponent_roster"] = [
        {"name": "Enemy Qb", "team": "KC", "position": "QB", "slot": "QB",
         "injury_status": ""},
        {"name": "Enemy Wr", "team": "MIN", "position": "WR", "slot": "WR",
         "injury_status": "Q"},
    ]
    return report


def test_league_team_detail_shows_standing_and_roster(client, tmp_path, monkeypatch):
    snap = tmp_path / "league.json"
    snap.write_text(json.dumps(league_snapshot_with_roster()), encoding="utf-8")
    monkeypatch.setattr(webapp, "LEAGUE_REPORT", snap)
    monkeypatch.setattr(webapp, "LEAGUE_AUDIT", tmp_path / "missing.jsonl")
    html = client.get("/league/team/Team Beta").get_data(as_text=True)
    assert "Enemy Qb" in html          # opponent roster rendered
    assert "Playing us this week" in html
    assert "no roster on file" not in html


def test_league_team_detail_without_roster_says_so(client, tmp_path, monkeypatch):
    snap = tmp_path / "league.json"
    snap.write_text(json.dumps(league_report()), encoding="utf-8")
    monkeypatch.setattr(webapp, "LEAGUE_REPORT", snap)
    monkeypatch.setattr(webapp, "LEAGUE_AUDIT", tmp_path / "missing.jsonl")
    html = client.get("/league/team/Team Alpha").get_data(as_text=True)
    assert "Team Alpha" in html
    assert "No roster captured for this team yet" in html


def test_league_team_detail_roster_from_all_teams_map(client, tmp_path, monkeypatch):
    report = league_report()
    report["rosters"] = {"Team Alpha": [
        {"name": "Alpha Rb", "team": "DAL", "position": "RB", "slot": "RB",
         "injury_status": ""}]}
    snap = tmp_path / "league.json"
    snap.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(webapp, "LEAGUE_REPORT", snap)
    monkeypatch.setattr(webapp, "LEAGUE_AUDIT", tmp_path / "missing.jsonl")
    html = client.get("/league/team/Team Alpha").get_data(as_text=True)
    assert "Alpha Rb" in html  # non-opponent roster renders from the rosters map


def test_league_team_detail_unknown_team_404(client, tmp_path, monkeypatch):
    snap = tmp_path / "league.json"
    snap.write_text(json.dumps(league_report()), encoding="utf-8")
    monkeypatch.setattr(webapp, "LEAGUE_REPORT", snap)
    monkeypatch.setattr(webapp, "LEAGUE_AUDIT", tmp_path / "missing.jsonl")
    resp = client.get("/league/team/Nobody FC")
    assert resp.status_code == 404
    assert "No team named" in resp.get_data(as_text=True)


def test_league_team_detail_trend_from_history(client, tmp_path, monkeypatch):
    older = league_report()
    older["captured_at"] = "2026-09-12T12:19:00+00:00"
    older["standings"][0]["points_for"] = 122.0
    monkeypatch.setattr(webapp, "LEAGUE_REPORT", tmp_path / "missing.json")
    audit = tmp_path / "league.jsonl"
    audit.write_text(json.dumps(older) + "\n" + json.dumps(league_report()) + "\n",
                     encoding="utf-8")
    monkeypatch.setattr(webapp, "LEAGUE_AUDIT", audit)
    html = client.get("/league/team/Team Alpha").get_data(as_text=True)
    assert "Season trajectory" in html
    assert "2026-09-12" in html and "122.0" in html and "140.5" in html


def test_helpers_team_row_and_record_games():
    rows = [{"team": "A"}, {"team": "B"}]
    row = webapp._team_row(rows, "B")
    assert row["team"] == "B"
    assert row["points_for"] == 0.0 and row["points_against"] == 0.0  # coerced
    assert webapp._team_row(rows, "C") is None
    assert webapp._team_row("junk", "A") is None
    assert webapp._record_games("2-1-0") == 3
    assert webapp._record_games("bad") == 0


def test_append_audit_appends_stamped_lines(tmp_path):
    from tools.league_report import append_audit
    out = tmp_path / "sub" / "league.jsonl"
    append_audit(str(out), {"standings": []})
    append_audit(str(out), {"standings": [{"team": "X"}]})
    lines = out.read_text().splitlines()
    assert len(lines) == 2
    first, second = (json.loads(l) for l in lines)
    assert first["standings"] == [] and "captured_at" in first
    assert second["standings"] == [{"team": "X"}]


def test_league_team_detail_tolerates_junk_types(client, tmp_path, monkeypatch):
    junk = league_report()
    junk["standings"][0]["points_for"] = "140.5"     # string instead of float
    junk["standings"][0]["points_against"] = None    # null instead of float
    snap = tmp_path / "league.json"
    snap.write_text(json.dumps(junk), encoding="utf-8")
    monkeypatch.setattr(webapp, "LEAGUE_REPORT", snap)
    audit = tmp_path / "league.jsonl"
    bad = league_report()
    bad["captured_at"] = 12345  # non-string stamp must not 500 the trend slice
    audit.write_text(json.dumps(bad) + "\n", encoding="utf-8")
    monkeypatch.setattr(webapp, "LEAGUE_AUDIT", audit)
    assert client.get("/league/team/Team Alpha").status_code == 200


def test_league_team_detail_slash_and_unicode_names(client, tmp_path, monkeypatch):
    report = league_report()
    report["standings"].append({"rank": 9, "team": "A/B Sébastien", "record": "0-0-0",
                                "points_for": 0.0, "points_against": 0.0, "waiver": 9})
    snap = tmp_path / "league.json"
    snap.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(webapp, "LEAGUE_REPORT", snap)
    monkeypatch.setattr(webapp, "LEAGUE_AUDIT", tmp_path / "missing.jsonl")
    assert client.get("/league/team/A/B%20S%C3%A9bastien").status_code == 200


def test_league_team_roster_falls_back_to_history(client, tmp_path, monkeypatch):
    # Tonight's snapshot lacks the roster (per-team read failed) ...
    latest = league_report()
    monkeypatch.setattr(webapp, "LEAGUE_REPORT",
                        _write := tmp_path / "league.json")
    _write.write_text(json.dumps(latest), encoding="utf-8")
    # ... but history lines still hold it; the NEWEST holder must win.
    older = league_report()
    older["captured_at"] = "2026-09-12T12:19:00+00:00"
    older["rosters"] = {"Team Alpha": [
        {"name": "Old Rb", "team": "DAL", "position": "RB", "slot": "RB",
         "injury_status": ""}]}
    newer = league_report()
    newer["captured_at"] = "2026-09-13T12:19:00+00:00"
    newer["rosters"] = {"Team Alpha": [
        {"name": "Alpha Rb", "team": "DAL", "position": "RB", "slot": "RB",
         "injury_status": ""}]}
    audit = tmp_path / "league.jsonl"
    audit.write_text(json.dumps(older) + "\n" + json.dumps(newer) + "\n", encoding="utf-8")
    monkeypatch.setattr(webapp, "LEAGUE_AUDIT", audit)
    html = client.get("/league/team/Team Alpha").get_data(as_text=True)
    assert "Alpha Rb" in html and "Old Rb" not in html
    assert "2026-09-13" in html  # dated-snapshot note rendered
