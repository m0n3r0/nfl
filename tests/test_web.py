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
    assert "<b>Shiba Innu</b>" in html  # my row is highlighted
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
    assert "league_report.py --out" in html


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
