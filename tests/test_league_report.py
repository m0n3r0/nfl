"""Hermetic tests for tools/league_report.py WAF handling."""

import contextlib
import json
import sys
import types

import pytest

sys.path.insert(0, "tools")

import league_report  # noqa: E402
from yahoo.league import LeagueWafBlocked  # noqa: E402


class FakeClient:
    def __init__(self):
        self.urls = []

    def navigate(self, url, expected, timeout=25):
        assert expected(url)
        self.urls.append(url)
        return url


@pytest.fixture
def harness(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["league_report.py"])
    monkeypatch.setattr(league_report, "find_team_target", lambda endpoint: object())
    client = FakeClient()

    @contextlib.contextmanager
    def ctx(target, endpoint, timeout):
        yield client
    monkeypatch.setattr(league_report, "CdpClient", ctx)
    return client


def test_waf_block_reports_status_and_skips_restore(harness, monkeypatch, capsys):
    def blocked(client):
        raise LeagueWafBlocked("denied")
    monkeypatch.setattr(league_report, "standings", blocked)

    assert league_report.main() == 2
    out = json.loads(capsys.readouterr().out)
    assert out == {"status": "waf_blocked"}
    assert harness.urls == []  # restore skipped: no extra request into the block


def test_green_run_reports_and_restores(harness, monkeypatch, capsys):
    monkeypatch.setattr(league_report, "standings", lambda client: ())
    monkeypatch.setattr(league_report, "matchup",
                        lambda client: types.SimpleNamespace(as_dict=lambda: {"week": 1}))

    assert league_report.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {"standings": [], "matchup": {"week": 1}}
    assert harness.urls == [f"{league_report.BASE}{league_report.TEAM_PATH}"]


def test_out_failure_still_prints_report_and_exits_0(harness, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(sys, "argv", ["league_report.py", "--out", str(tmp_path / "x.json")])
    monkeypatch.setattr(league_report, "standings", lambda client: ())
    monkeypatch.setattr(league_report, "matchup",
                        lambda client: types.SimpleNamespace(as_dict=lambda: {"week": 1}))

    def explode(path, report):
        raise OSError("disk full")
    monkeypatch.setattr(league_report, "write_report", explode)

    assert league_report.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {"standings": [], "matchup": {"week": 1}}


def test_waf_block_is_not_persisted_over_good_snapshot(harness, monkeypatch, capsys, tmp_path):
    out_path = tmp_path / "league.json"
    out_path.write_text('{"standings": [{"team": "Good Data"}]}', encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["league_report.py", "--out", str(out_path)])

    def blocked(client):
        raise LeagueWafBlocked("denied")
    monkeypatch.setattr(league_report, "standings", blocked)

    assert league_report.main() == 2
    assert json.loads(capsys.readouterr().out) == {"status": "waf_blocked"}
    assert "Good Data" in out_path.read_text()  # previous snapshot untouched
