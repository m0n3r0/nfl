"""Hermetic tests for tools/preflight.py auth-probe interpretation."""

import sys

sys.path.insert(0, "tools")

import preflight  # noqa: E402


def test_probe_authed_when_200_and_doge():
    flags = preflight._probe_flags({"status": 200, "doge": True, "denied": False})
    assert flags == {"waf_blocked": False, "auth": True}


def test_probe_waf_block_is_not_a_logout():
    flags = preflight._probe_flags({"status": 200, "doge": True, "denied": True})
    assert flags["waf_blocked"] is True
    assert flags["auth"] is False


def test_probe_status_999_means_waf_block():
    flags = preflight._probe_flags({"status": 999, "doge": False})
    assert flags["waf_blocked"] is True
    assert flags["auth"] is False


def test_probe_unreachable_is_neither_blocked_nor_authed():
    assert preflight._probe_flags({"status": 0, "doge": False, "error": "netdown"}) == \
        {"waf_blocked": False, "auth": False}
    assert preflight._probe_flags(None) == {"waf_blocked": False, "auth": False}


def test_main_exits_3_on_waf_block(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["preflight.py"])
    monkeypatch.setattr(preflight, "preflight",
                        lambda endpoint, url: {"cdp": True, "team_tab": True,
                                               "auth": False, "waf_blocked": True})
    assert preflight.main() == 3
