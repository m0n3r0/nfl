"""Hermetic tests for tools/league_report.py WAF handling."""

import contextlib
import json
import sys
import types

import pytest

sys.path.insert(0, "tools")

import league_report  # noqa: E402
from yahoo.league import LeagueReadError, LeagueWafBlocked  # noqa: E402


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


def test_waf_block_skips_audit_too(harness, monkeypatch, capsys, tmp_path):
    audit_path = tmp_path / "league.jsonl"
    monkeypatch.setattr(sys, "argv", ["league_report.py", "--audit", str(audit_path)])

    def blocked(client):
        raise LeagueWafBlocked("denied")
    monkeypatch.setattr(league_report, "standings", blocked)

    assert league_report.main() == 2
    assert not audit_path.exists()  # throttle stubs never enter the history


def test_roster_failure_degrades_to_rosterless_report(harness, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["league_report.py", "--opponent-roster"])
    monkeypatch.setattr(league_report, "standings", lambda client: ())
    monkeypatch.setattr(league_report, "matchup",
                        lambda client: types.SimpleNamespace(as_dict=lambda: {"week": 1}))

    def explode(client):
        raise LeagueReadError("markup changed")
    monkeypatch.setattr(league_report, "opponent_team_id", explode)

    assert league_report.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {"standings": [], "matchup": {"week": 1}}  # no roster keys, no crash


def test_roster_phase_waf_still_exits_2_and_skips_restore(harness, monkeypatch, capsys, tmp_path):
    out_path = tmp_path / "league.json"
    out_path.write_text('{"standings": [{"team": "Good Data"}]}', encoding="utf-8")
    audit_path = tmp_path / "league.jsonl"
    monkeypatch.setattr(sys, "argv", ["league_report.py", "--opponent-roster",
                                      "--out", str(out_path), "--audit", str(audit_path)])
    monkeypatch.setattr(league_report, "standings", lambda client: ())
    monkeypatch.setattr(league_report, "matchup",
                        lambda client: types.SimpleNamespace(as_dict=lambda: {"week": 1}))

    def blocked(client):
        raise LeagueWafBlocked("denied")
    monkeypatch.setattr(league_report, "opponent_team_id", blocked)

    assert league_report.main() == 2  # never downgraded to a roster-less green run
    assert json.loads(capsys.readouterr().out) == {"status": "waf_blocked"}
    assert harness.urls == []  # no restore navigation into the active block
    assert "Good Data" in out_path.read_text()
    assert not audit_path.exists()


def _green_stubs(monkeypatch):
    monkeypatch.setattr(league_report, "standings", lambda client: ())
    monkeypatch.setattr(league_report, "matchup",
                        lambda client: types.SimpleNamespace(as_dict=lambda: {"week": 1}))


def test_all_rosters_excludes_own_team(harness, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv",
                        ["league_report.py", "--all-rosters", "--roster-delay", "0"])
    _green_stubs(monkeypatch)
    from yahoo.team import TEAM_ID
    monkeypatch.setattr(league_report, "team_ids",
                        lambda client: {"Team Alpha": "3", "Shiba Innu": TEAM_ID,
                                        "Team Beta": "4"})
    called_with = []
    monkeypatch.setattr(league_report, "opponent_roster",
                        lambda client, tid: called_with.append(tid) or [{"name": f"Player {tid}"}])

    assert league_report.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out["rosters"] == {"Team Alpha": [{"name": "Player 3"}],
                              "Team Beta": [{"name": "Player 4"}]}
    assert TEAM_ID not in called_with  # ours is never read


def test_all_rosters_reads_ids_before_leaving_standings_page(harness, monkeypatch, capsys):
    """team_ids only works on the standings page; the order is load-bearing."""
    monkeypatch.setattr(sys, "argv",
                        ["league_report.py", "--all-rosters", "--roster-delay", "0"])
    calls = []
    monkeypatch.setattr(league_report, "standings",
                        lambda client: calls.append("standings") or ())
    monkeypatch.setattr(league_report, "team_ids",
                        lambda client: calls.append("team_ids") or {"Team Alpha": "3"})
    monkeypatch.setattr(league_report, "matchup",
                        lambda client: calls.append("matchup") or
                        types.SimpleNamespace(as_dict=lambda: {"week": 1}))
    monkeypatch.setattr(league_report, "opponent_roster",
                        lambda client, tid: [{"name": "Player 3"}])

    assert league_report.main() == 0
    assert calls == ["standings", "team_ids", "matchup"]


def test_all_rosters_per_team_failure_degrades(harness, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv",
                        ["league_report.py", "--all-rosters", "--roster-delay", "0"])
    _green_stubs(monkeypatch)
    monkeypatch.setattr(league_report, "team_ids",
                        lambda client: {"Team Alpha": "3", "Team Beta": "4"})

    def flaky(client, tid):
        if tid == "3":
            raise LeagueReadError("markup changed")
        return [{"name": "Player 4"}]
    monkeypatch.setattr(league_report, "opponent_roster", flaky)

    assert league_report.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out["rosters"] == {"Team Beta": [{"name": "Player 4"}]}


def test_all_rosters_waf_keeps_full_contract(harness, monkeypatch, capsys, tmp_path):
    out_path = tmp_path / "league.json"
    monkeypatch.setattr(sys, "argv", ["league_report.py", "--all-rosters",
                                      "--roster-delay", "0", "--out", str(out_path)])
    _green_stubs(monkeypatch)
    monkeypatch.setattr(league_report, "team_ids",
                        lambda client: {"Team Alpha": "3"})

    def blocked(client, tid):
        raise LeagueWafBlocked("denied")
    monkeypatch.setattr(league_report, "opponent_roster", blocked)

    assert league_report.main() == 2
    assert json.loads(capsys.readouterr().out) == {"status": "waf_blocked"}
    assert harness.urls == []  # no restore navigation into the block
    assert not out_path.exists()
