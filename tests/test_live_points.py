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
