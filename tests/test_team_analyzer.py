"""Hermetic tests for tools/team_analyzer.py control flow (light mode, WAF aborts)."""

import contextlib
import sys
import types

import pandas as pd
import pytest

sys.path.insert(0, "tools")

import team_analyzer  # noqa: E402
from yahoo.league import LeagueWafBlocked  # noqa: E402

FRAME = pd.DataFrame(columns=["player_id", "player_display_name", "position",
                              "last_team", "proj_total", "proj_week"])


class FakeClient:
    def __init__(self):
        self.urls = []

    def navigate(self, url, expected, timeout=25):
        assert expected(url)
        self.urls.append(url)
        return url

    def evaluate(self, expression, timeout=12):
        return True  # _wait_render sees its marker immediately


@pytest.fixture
def harness(monkeypatch):
    monkeypatch.setattr(team_analyzer.preflight_mod, "preflight",
                        lambda endpoint: {"cdp": True, "team_tab": True, "auth": True})
    monkeypatch.setattr(team_analyzer, "_league_tab", lambda endpoint: object())
    client = FakeClient()

    @contextlib.contextmanager
    def ctx(target, endpoint, timeout):
        yield client
    monkeypatch.setattr(team_analyzer, "CdpClient", ctx)
    monkeypatch.setattr(team_analyzer, "YahooTeamReader", lambda c: types.SimpleNamespace(
        snapshot=lambda: types.SimpleNamespace(week=1, roster=())))
    monkeypatch.setattr(team_analyzer.corpus_mod, "build", lambda preset: {
        "schedule_2026": pd.DataFrame({"team": ["SF"], "week": [1]})})
    monkeypatch.setattr(team_analyzer, "projections",
                        types.SimpleNamespace(project_for_week=lambda corp, week: FRAME,
                                              project_players=lambda corp: FRAME))
    monkeypatch.setattr(team_analyzer, "standings", lambda c: ())
    monkeypatch.setattr(team_analyzer, "matchup",
                        lambda c: types.SimpleNamespace(as_dict=lambda: {"week": 1}))
    monkeypatch.setattr(team_analyzer, "propose_lineup",
                        lambda snap, weekly, week: types.SimpleNamespace(plan=(), warnings=()))
    monkeypatch.setattr(team_analyzer, "monitor_report",
                        lambda snap, weekly, week: {"locked_starters": [],
                                                    "injury_tags": [], "unevaluated": []})
    return client


def _boom(what):
    def call(*args, **kwargs):
        raise AssertionError(f"{what} must not be called here")
    return call


def test_light_mode_skips_league_pulls_and_wire(harness, monkeypatch):
    # Record rather than raise for the roster pull: the full-mode loop catches
    # Exception, so a raised boom would be swallowed and the test false-pass.
    roster_calls = []
    monkeypatch.setattr(team_analyzer, "opponent_roster",
                        lambda *a, **k: roster_calls.append(a))
    monkeypatch.setattr(team_analyzer, "scan_available", _boom("scan_available"))

    report = team_analyzer.analyze("http://127.0.0.1:9222", with_wire=True, light=True)

    assert report["status"] == "ok"
    assert report["mode"] == "light"
    assert report["season_strength"] is None
    assert report["position_ranks"] == []
    assert [r["kind"] for r in report["recommendations"]] == ["lineup"]
    assert roster_calls == []  # not one league pull happened
    team_url = f"{team_analyzer.BASE}{team_analyzer.TEAM_PATH}"
    assert harness.urls.count(team_url) == 2  # initial navigate + finally restore


def test_preflight_waf_block_short_circuits(harness, monkeypatch):
    monkeypatch.setattr(team_analyzer.preflight_mod, "preflight",
                        lambda endpoint: {"cdp": True, "team_tab": True,
                                          "auth": False, "waf_blocked": True})

    report = team_analyzer.analyze("http://127.0.0.1:9222", with_wire=False, light=True)

    assert report["status"] == "waf_blocked"


def test_roster_waf_block_aborts_run_without_extra_requests(harness, monkeypatch):
    def blocked(client, tid):
        raise LeagueWafBlocked("denied")
    monkeypatch.setattr(team_analyzer, "opponent_roster", blocked)

    report = team_analyzer.analyze("http://127.0.0.1:9222", with_wire=False, light=False)

    assert report["status"] == "waf_blocked"
    assert "denied" in report["error"]
    team_url = f"{team_analyzer.BASE}{team_analyzer.TEAM_PATH}"
    assert harness.urls.count(team_url) == 1  # restore skipped: no requests into a block


def test_wire_block_alert_skips_restore_but_completes(harness, monkeypatch):
    from yahoo.wire import WireScanBlocked

    # one rostered player so the full-mode strength math has my team to score
    one = types.SimpleNamespace(name="P One", team="SF", position="QB",
                                slot="QB", injury_status="")
    monkeypatch.setattr(team_analyzer, "YahooTeamReader", lambda c: types.SimpleNamespace(
        snapshot=lambda: types.SimpleNamespace(week=1, roster=(one,))))
    monkeypatch.setattr(team_analyzer, "opponent_roster", lambda client, tid: ())

    def scan_boom(client, week):
        raise WireScanBlocked("denied mid-scan")
    monkeypatch.setattr(team_analyzer, "scan_available", scan_boom)

    report = team_analyzer.analyze("http://127.0.0.1:9222", with_wire=True, light=False)

    assert report["status"] == "ok"  # the wire section degrades, the run completes
    assert any("Request denied" in alert for alert in report["alerts"])
    team_url = f"{team_analyzer.BASE}{team_analyzer.TEAM_PATH}"
    assert harness.urls.count(team_url) == 1  # no extra navigation into the block
