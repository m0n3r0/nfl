"""Hermetic tests for tools/team_operator.py fail-closed plumbing."""

import json
import sys

import pytest

sys.path.insert(0, "tools")

import team_operator  # noqa: E402
from yahoo.browser import BrowserError  # noqa: E402


@pytest.fixture
def operator(tmp_path, monkeypatch):
    monkeypatch.setattr(team_operator, "AUDIT_LOG", tmp_path / "audit.jsonl")
    monkeypatch.setattr(team_operator, "LOCK_PATH", tmp_path / "lock")
    monkeypatch.setattr(sys, "argv", ["team_operator.py"])
    return team_operator


def _args(**kw):
    import argparse
    defaults = dict(endpoint="http://127.0.0.1:9222", refresh_data=False,
                    week=None, waiver_scan=False, apply=False, top=10, jev=0)
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def test_preflight_browser_error_fails_closed(operator, monkeypatch):
    def boom(endpoint):
        raise BrowserError("no chrome")
    monkeypatch.setattr(operator.preflight_mod, "preflight", boom)

    report = operator.run(_args())

    assert report["status"] == "preflight_failed"
    assert "no chrome" in report["error"]


def test_preflight_unhealthy_fails_closed(operator, monkeypatch):
    monkeypatch.setattr(operator.preflight_mod, "preflight",
                        lambda endpoint: {"cdp": True, "team_tab": True, "auth": False})

    report = operator.run(_args())

    assert report["status"] == "preflight_failed"


def test_preflight_waf_block_reports_distinctly(operator, monkeypatch):
    monkeypatch.setattr(operator.preflight_mod, "preflight",
                        lambda endpoint: {"cdp": True, "team_tab": True,
                                          "auth": False, "waf_blocked": True})

    report = operator.run(_args())

    assert report["status"] == "waf_blocked"


def test_lock_contention_audits_and_exits_3(operator):
    import fcntl
    with open(operator.LOCK_PATH, "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        assert operator.main() == 3

    lines = operator.AUDIT_LOG.read_text().splitlines()
    assert json.loads(lines[-1])["status"] == "already_running"


def test_crashed_run_is_audited(operator, monkeypatch):
    def boom(args):
        raise RuntimeError("corpus exploded")
    monkeypatch.setattr(operator, "run", boom)

    assert operator.main() == 2

    lines = operator.AUDIT_LOG.read_text().splitlines()
    record = json.loads(lines[-1])
    assert record["status"] == "error"
    assert "corpus exploded" in record["error"]


def test_apply_with_wrong_week_is_refused(operator, monkeypatch):
    import contextlib
    import types

    monkeypatch.setattr(operator.preflight_mod, "preflight",
                        lambda endpoint: {"cdp": True, "team_tab": True, "auth": True})
    monkeypatch.setattr(operator, "find_team_target", lambda endpoint: object())

    @contextlib.contextmanager
    def fake_client(target, endpoint, timeout):
        yield object()
    monkeypatch.setattr(operator, "CdpClient", fake_client)

    class FakeReader:
        def __init__(self, client):
            pass

        def snapshot(self):
            return types.SimpleNamespace(week=1)
    monkeypatch.setattr(operator, "YahooTeamReader", FakeReader)

    report = operator.run(_args(week=2, apply=True))

    assert report["status"] == "week_mismatch"
    assert report["yahoo_week"] == 1
    assert report["requested_week"] == 2


def _stub_run_pipeline(operator, monkeypatch, fake_client):
    """Stub everything run() touches except the restore navigation under test."""
    import contextlib
    import types

    monkeypatch.setattr(operator.preflight_mod, "preflight",
                        lambda endpoint: {"cdp": True, "team_tab": True, "auth": True})
    monkeypatch.setattr(operator, "find_team_target", lambda endpoint: object())

    @contextlib.contextmanager
    def ctx(target, endpoint, timeout):
        yield fake_client
    monkeypatch.setattr(operator, "CdpClient", ctx)
    monkeypatch.setattr(operator, "YahooTeamReader", lambda client: types.SimpleNamespace(
        snapshot=lambda: types.SimpleNamespace(week=1, record="0-0-0",
                                               waiver_priority=4, roster=())))
    monkeypatch.setattr(operator.corpus_mod, "build", lambda preset: {"schedule_2026": None})
    monkeypatch.setattr(operator.sched, "locked_teams", lambda schedule, week: ())
    monkeypatch.setattr(operator, "projections",
                        types.SimpleNamespace(project_for_week=lambda corp, week: None))
    monkeypatch.setattr(operator, "apply_schedule_locks", lambda snap, locked: (snap, ()))
    monkeypatch.setattr(operator, "propose_lineup",
                        lambda snap, proj, week: types.SimpleNamespace(
                            moves=(), as_dict=lambda: {}))
    monkeypatch.setattr(operator, "monitor_report", lambda snap, proj, week: {})


def test_restore_failure_does_not_mask_matchup_error(operator, monkeypatch, capsys):
    from yahoo.cdp import CdpError

    class RestoreBoom:
        def navigate(self, url, expected, timeout=25):
            raise CdpError("restore boom")

    _stub_run_pipeline(operator, monkeypatch, RestoreBoom())

    def matchup_boom(client):
        raise RuntimeError("matchup parse exploded")
    monkeypatch.setattr(operator, "matchup", matchup_boom)

    report = operator.run(_args())

    assert report["status"] == "ok"
    assert "matchup parse exploded" in report["matchup_error"]
    assert "tab restore failed: restore boom" in capsys.readouterr().err


def test_wire_waf_block_aborts_run_distinctly(operator, monkeypatch):
    from yahoo.cdp import CdpError
    from yahoo.wire import WireScanBlocked

    class RestoreBoom:
        def __init__(self):
            self.calls = 0

        def navigate(self, url, expected, timeout=25):
            self.calls += 1
            raise CdpError("restore boom")

    client = RestoreBoom()
    _stub_run_pipeline(operator, monkeypatch, client)
    monkeypatch.setattr(operator, "matchup",
                        lambda client: __import__("types").SimpleNamespace(as_dict=lambda: {}))

    def scan_boom(client, week):
        raise WireScanBlocked("denied mid-scan")
    monkeypatch.setattr(operator, "scan_available", scan_boom)

    report = operator.run(_args(waiver_scan=True))

    assert report["status"] == "waf_blocked"  # distinct from a crash
    assert "denied mid-scan" in report["wire_error"]
    assert client.calls == 1  # only the matchup-block restore; scan restore skipped


def test_matchup_waf_block_aborts_run_distinctly(operator, monkeypatch):
    from yahoo.league import LeagueWafBlocked

    class RecordingClient:
        def __init__(self):
            self.urls = []

        def navigate(self, url, expected, timeout=25):
            self.urls.append(url)
            return url

    client = RecordingClient()
    _stub_run_pipeline(operator, monkeypatch, client)

    def matchup_blocked(client):
        raise LeagueWafBlocked("denied")
    monkeypatch.setattr(operator, "matchup", matchup_blocked)

    report = operator.run(_args())

    assert report["status"] == "waf_blocked"
    assert "matchup_error" not in report
    assert client.urls == []  # restore skipped: no extra request into the block


def _stub_jev_pipeline(operator, monkeypatch):
    """Full pipeline stub with an injured roster player and one wire target."""
    import contextlib
    import types

    _stub_run_pipeline(operator, monkeypatch, types.SimpleNamespace(
        navigate=lambda url, expected, timeout=25: None))
    injured = types.SimpleNamespace(
        yahoo_id="1", name="Chris Olave", position="WR", team="NO",
        slot="WR", injury_status="Q", game="", locked=False)
    healthy = types.SimpleNamespace(
        yahoo_id="2", name="Brock Purdy", position="QB", team="SF",
        slot="QB", injury_status="", game="", locked=False)
    monkeypatch.setattr(operator, "YahooTeamReader", lambda client: types.SimpleNamespace(
        snapshot=lambda: types.SimpleNamespace(
            week=2, record="1-0-0", waiver_priority=4, roster=(injured, healthy))))
    monkeypatch.setattr(operator, "propose_lineup",
                        lambda snap, proj, week: types.SimpleNamespace(
                            moves=(), as_dict=lambda: {
                                "week": 2, "moves": [], "warnings": [],
                                "plan": [{"yahoo_id": "1", "proj_week": 11.0}]}))
    monkeypatch.setattr(operator, "matchup",
                        lambda client: types.SimpleNamespace(as_dict=lambda: {}))
    monkeypatch.setattr(operator, "scan_available", lambda client, week: {"1": object()})
    monkeypatch.setattr(operator, "rank_targets",
                        lambda available, proj: ([{"name": "T", "proj_week": 9.0}], {}))


def _fake_jev(operator, monkeypatch, connect_exc=None):
    """Install a fake src.jev: review fns attach marker blocks in place."""
    import contextlib
    import types

    from src.jev import JevError

    @contextlib.contextmanager
    def connect():
        if connect_exc:
            raise connect_exc
        yield object()

    def review_injured(players, week, client=None):
        for p in players:
            p["jev"] = {"likely_out": 0.35}
        return []

    def review_wire(targets, week, client=None):
        for t in targets:
            t["jev"] = {"profile": "breakout"}
        return []

    monkeypatch.setattr(operator, "jev", types.SimpleNamespace(
        JevError=JevError, connect=connect,
        review_injured_players=review_injured,
        review_waiver_targets=review_wire))


def test_jev_advisory_blocks_attach(operator, monkeypatch):
    _stub_jev_pipeline(operator, monkeypatch)
    _fake_jev(operator, monkeypatch)

    report = operator.run(_args(waiver_scan=True, jev=3))

    assert report["status"] == "ok"
    (injured,) = report["jev_injuries"]
    assert injured["name"] == "Chris Olave"
    assert injured["proj_week"] == 11.0  # joined from the proposal plan
    assert injured["jev"] == {"likely_out": 0.35}
    assert report["wire"]["targets"][0]["jev"] == {"profile": "breakout"}


def test_jev_down_never_breaks_the_run(operator, monkeypatch):
    from src.jev import JevError

    _stub_jev_pipeline(operator, monkeypatch)
    _fake_jev(operator, monkeypatch, connect_exc=JevError("no key"))

    report = operator.run(_args(waiver_scan=True, jev=3))

    assert report["status"] == "ok"  # advisory layer must not affect the run
    assert report["jev_error"] == "no key"
    assert "jev_injuries" not in report
