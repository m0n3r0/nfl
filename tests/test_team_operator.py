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
                    week=None, waiver_scan=False, apply=False, top=10)
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
