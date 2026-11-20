"""Hermetic tests for tools/live_points.py (totals, reconciliation, writes)."""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, "tools")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import live_points  # noqa: E402


def roster(slots):
    return [{"name": n, "team": t, "position": pos, "slot": slot}
            for n, t, pos, slot in slots]


def test_team_totals_starters_only_and_def_named():
    rosters = {"Us": roster([
        ("Quarter Back", "SF", "QB", "QB"),
        ("Bench Guy", "NO", "WR", "BN"),
        ("Ir Guy", "GB", "RB", "IR"),
        ("Steelers", "Pit", "DEF", "DEF"),
    ])}
    players = {"quarter back": {"points": 20.0}, "bench guy": {"points": 99.0}}
    defs = {"DEF:PIT": -3.0}
    game_teams = {"g1": {"PIT": "Pittsburgh Steelers"}}
    totals, unmatched, def_named = live_points.team_totals(
        rosters, players, defs, game_teams)
    assert totals["Us"] == 17.0  # 20 + (-3); bench/IR excluded
    assert def_named == {"Steelers": -3.0}
    assert unmatched == []


def test_unmatched_starter_is_reported_not_silent():
    rosters = {"Us": roster([("Mystery Man", "FA", "WR", "WR")])}
    totals, unmatched, _ = live_points.team_totals(rosters, {}, {}, {})
    assert totals["Us"] == 0.0
    assert unmatched and unmatched[0]["name"] == "Mystery Man"


def _report(tmp_path, age_seconds, score):
    ts = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    report = {"captured_at": ts.isoformat(),
              "scoreboard": [{"team1": "Us", "team2": "Them",
                              "score1": score, "score2": 0}]}
    (tmp_path / "league-report.json").write_text(json.dumps(report))
    return report


def test_reconcile_fresh_snapshot_detects_drift(tmp_path, monkeypatch):
    monkeypatch.setattr(live_points, "LEAGUE_REPORT", tmp_path / "league-report.json")
    _report(tmp_path, age_seconds=30, score=50.0)
    recon = live_points.reconcile({"Us": 57.0})
    assert recon["drift"] is True
    assert recon["comparisons"][0]["delta"] == 7.0


def test_reconcile_stale_snapshot_never_flags_drift(tmp_path, monkeypatch):
    monkeypatch.setattr(live_points, "LEAGUE_REPORT", tmp_path / "league-report.json")
    _report(tmp_path, age_seconds=1200, score=50.0)
    recon = live_points.reconcile({"Us": 57.0})
    assert recon["drift"] is False  # old snapshot legitimately trails
    assert "stale" in recon["note"]


def test_reconcile_fresh_and_matching_is_clean(tmp_path, monkeypatch):
    monkeypatch.setattr(live_points, "LEAGUE_REPORT", tmp_path / "league-report.json")
    _report(tmp_path, age_seconds=30, score=57.0)
    recon = live_points.reconcile({"Us": 57.2})
    assert recon["drift"] is False  # within 0.5 tolerance


def test_write_artifact_atomic_and_audited(tmp_path):
    artifact = {"captured_at": "t", "reconciliation": {
        "drift": False, "comparisons": [{"team": "Us", "yahoo": 1, "ours": 1, "delta": 0}]}}
    out = tmp_path / "live-points.json"
    live_points.AUDIT = tmp_path / "audit.jsonl"
    live_points.write_artifact(artifact, out)
    assert json.loads(out.read_text()) == artifact
    assert not list(tmp_path.glob("*.tmp.*"))
    assert json.loads((tmp_path / "audit.jsonl").read_text())["drift"] is False


def test_next_window_caps_and_floors():
    import pytest
    now = datetime.now(timezone.utc)
    soon = {"date": (now + timedelta(seconds=300)).isoformat(), "state": "pre"}
    far = {"date": (now + timedelta(hours=5)).isoformat(), "state": "pre"}
    assert live_points._next_window([soon]) == pytest.approx(180.0, abs=1)
    assert live_points._next_window([far]) == 900.0  # capped
    assert live_points._next_window([]) == 900.0


def test_clamp_interval_floor():
    assert live_points.clamp_interval(10) == 10.0
    assert live_points.clamp_interval(1) == live_points.MIN_POLL_SECONDS
    assert live_points.clamp_interval(0.1) == live_points.MIN_POLL_SECONDS


def _board(play_id, clock=700.0, score="7"):
    return {"week": {"number": 11}, "events": [{
        "id": "g1", "name": "A at B", "date": "2026-11-20T01:15Z",
        "competitions": [{
            "status": {"type": {"state": "in", "shortDetail": "1st"},
                       "period": 1, "displayClock": "11:40", "clock": clock},
            "situation": {"lastPlay": {"id": play_id}},
            "competitors": [
                {"team": {"abbreviation": "A", "displayName": "Team A"},
                 "score": score},
                {"team": {"abbreviation": "B", "displayName": "Team B"},
                 "score": "0"}]}]}]}


_MIN_SUMMARY = {
    "boxscore": {"players": [], "teams": []},
    "header": {"competitions": [{"competitors": [
        {"team": {"abbreviation": "A", "displayName": "Team A"}, "score": "7"},
        {"team": {"abbreviation": "B", "displayName": "Team B"}, "score": "0"}]}]},
    "scoringPlays": [],
}


def test_signature_gating_skips_unchanged_games(monkeypatch):
    calls = []
    monkeypatch.setattr(live_points, "fetch_json",
                        lambda url: calls.append(url) or dict(_MIN_SUMMARY))
    monkeypatch.setattr(live_points.time, "sleep", lambda s: None)
    board = _board("play1")
    monkeypatch.setattr(live_points, "scoreboard", lambda week=None: board)
    monkeypatch.setattr(live_points, "load_rosters", lambda: ({}, None))

    cache = {}
    a1 = live_points.compute_week(cache=cache)
    assert a1["fetch_stats"] == {"fresh": 1, "cached": 0}
    a2 = live_points.compute_week(cache=cache)          # same signature
    assert a2["fetch_stats"] == {"fresh": 0, "cached": 1}
    assert len(calls) == 1                               # NO second request
    assert a2["games"]["g1"]["fetch"] == "cached"

    board2 = _board("play2")                             # new play -> fetch
    monkeypatch.setattr(live_points, "scoreboard", lambda week=None: board2)
    a3 = live_points.compute_week(cache=cache)
    assert a3["fetch_stats"]["fresh"] == 1 and len(calls) == 2

    a4 = live_points.compute_week(cache=cache, force=True)  # sweep -> fetch
    assert a4["fetch_stats"]["fresh"] == 1 and len(calls) == 3


def test_signature_gating_score_change_triggers_fetch(monkeypatch):
    calls = []
    monkeypatch.setattr(live_points, "fetch_json",
                        lambda url: calls.append(url) or dict(_MIN_SUMMARY))
    monkeypatch.setattr(live_points.time, "sleep", lambda s: None)
    monkeypatch.setattr(live_points, "load_rosters", lambda: ({}, None))
    cache = {}
    monkeypatch.setattr(live_points, "scoreboard", lambda week=None: _board("p1"))
    live_points.compute_week(cache=cache)
    # same play id and clock, but the score moved (e.g. correction) -> fetch
    monkeypatch.setattr(live_points, "scoreboard",
                        lambda week=None: _board("p1", score="10"))
    a = live_points.compute_week(cache=cache)
    assert a["fetch_stats"]["fresh"] == 1 and len(calls) == 2


def test_fetch_failure_serves_last_good_cache(monkeypatch):
    monkeypatch.setattr(live_points.time, "sleep", lambda s: None)
    monkeypatch.setattr(live_points, "load_rosters", lambda: ({}, None))
    cache = {}
    monkeypatch.setattr(live_points, "scoreboard", lambda week=None: _board("p1"))
    monkeypatch.setattr(live_points, "fetch_json", lambda url: dict(_MIN_SUMMARY))
    live_points.compute_week(cache=cache)

    def boom(url):
        raise OSError("network blip")
    monkeypatch.setattr(live_points, "fetch_json", boom)
    monkeypatch.setattr(live_points, "scoreboard",
                        lambda week=None: _board("p2"))
    a = live_points.compute_week(cache=cache)
    assert a["games"]["g1"]["fetch"] == "stale"
    assert "DEF:A" in a["def"]  # last good points still served


def _final_artifact(week=10, points=21.35):
    return {"week": week, "scoring_sha": "abc",
            "players": {"qb": {"points": points}}, "def": {}, "def_named": {},
            "totals": {"Us": points},
            "games": {"g1": {"state": "post"}, "g2": {"state": "post"}}}


def test_archive_written_only_when_week_final(tmp_path):
    art = _final_artifact()
    art["games"]["g2"]["state"] = "in"  # one game still live
    assert live_points.archive_if_final(art, tmp_path) is None
    assert not list(tmp_path.glob("live-points-week-*.json"))

    art["games"]["g2"]["state"] = "post"
    path = live_points.archive_if_final(art, tmp_path)
    assert path is not None and path.name == "live-points-week-10.json"
    saved = json.loads(path.read_text())
    assert saved["players"]["qb"]["points"] == 21.35
    assert saved["archived_at"]


def test_archive_rewritten_only_on_content_change(tmp_path):
    art = _final_artifact()
    p1 = live_points.archive_if_final(art, tmp_path)
    mtime1 = p1.stat().st_mtime_ns
    live_points.archive_if_final(art, tmp_path)          # identical -> skip
    assert p1.stat().st_mtime_ns == mtime1
    art["players"]["qb"]["points"] = 22.0                # correction -> rewrite
    live_points.archive_if_final(art, tmp_path)
    assert json.loads(p1.read_text())["players"]["qb"]["points"] == 22.0
