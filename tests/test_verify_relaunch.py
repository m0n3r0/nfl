"""Hermetic tests for the relaunch drill (tools/verify_relaunch.py)."""

from __future__ import annotations

import json

import pytest

import tools.verify_relaunch as drill


def test_pick_source_defaults_to_live_profile():
    source = drill.pick_source(isdir=lambda p: p == drill.DEFAULT_PROFILE)
    assert source == drill.DEFAULT_PROFILE


def test_pick_source_from_backup_uses_backup_root():
    expected = f"{drill.BACKUP_ROOT}/edge-draft-profile"
    source = drill.pick_source(from_backup=True, isdir=lambda p: p == expected)
    assert source == expected


def test_pick_source_missing_raises():
    with pytest.raises(drill.DrillError, match="profile not found"):
        drill.pick_source(isdir=lambda p: False)
    with pytest.raises(drill.DrillError, match="backup not found"):
        drill.pick_source(from_backup=True, isdir=lambda p: False)


def test_drill_launch_args_headless_and_isolated():
    args = drill.drill_launch_args("/bin/chrome", "/tmp/copy", 9223, "https://example.test")
    assert args[0] == "/bin/chrome"
    assert "--headless=new" in args
    assert "--remote-debugging-port=9223" in args
    assert "--user-data-dir=/tmp/copy" in args
    assert "--use-mock-keychain" in args
    assert args[-1] == "https://example.test"


def test_drill_launch_args_port_zero_asks_os_for_a_port():
    args = drill.drill_launch_args("/bin/chrome", "/tmp/copy", 0, "https://example.test")
    assert "--remote-debugging-port=0" in args


def test_check_port_free_ignores_os_assigned_port():
    drill.check_port_free(0, alive=lambda endpoint: True)  # alive must not be consulted


def test_check_port_free_refuses_live_operator_port():
    with pytest.raises(drill.DrillError, match="live operator port"):
        drill.check_port_free(9222, alive=lambda endpoint: False)


def test_check_port_free_refuses_busy_port():
    with pytest.raises(drill.DrillError, match="refusing to disturb"):
        drill.check_port_free(9223, alive=lambda endpoint: True)


def test_check_port_free_accepts_spare_port():
    drill.check_port_free(9223, alive=lambda endpoint: False)


def test_read_devtools_port(tmp_path):
    (tmp_path / "DevToolsActivePort").write_text("51234\n/devtools/browser/abc\n")
    assert drill.read_devtools_port(str(tmp_path)) == 51234


def test_read_devtools_port_missing_or_garbage(tmp_path):
    assert drill.read_devtools_port(str(tmp_path)) is None
    (tmp_path / "DevToolsActivePort").write_text("not-a-port\n")
    assert drill.read_devtools_port(str(tmp_path)) is None


def test_verdict_signed_in_only_on_200_and_manager():
    assert drill.verdict(200, True) == "signed_in"
    assert drill.verdict(200, False) == "login_required"
    assert drill.verdict(302, True) == "login_required"


def test_verdict_denial_wins_over_manager_match():
    assert drill.verdict(200, True, denied=True) == "inconclusive"
    assert drill.verdict(999, False) == "inconclusive"


def test_verdict_no_answer_is_inconclusive_never_logout():
    assert drill.verdict(None, False) == "inconclusive"
    assert drill.verdict(None, True) == "inconclusive"


def test_verdict_throttling_and_outage_are_inconclusive():
    assert drill.verdict(429, False) == "inconclusive"
    assert drill.verdict(500, False) == "inconclusive"
    assert drill.verdict(503, False) == "inconclusive"


def test_verdict_auth_rejection_is_login_required():
    assert drill.verdict(401, False) == "login_required"
    assert drill.verdict(403, False) == "login_required"


def test_verdict_unrelated_4xx_is_not_auth_evidence():
    assert drill.verdict(404, False) == "inconclusive"
    assert drill.verdict(400, False) == "inconclusive"


def test_run_drill_cleans_temp_dir_when_copy_fails(monkeypatch, tmp_path):
    workdir = tmp_path / "drill-work"
    workdir.mkdir()
    monkeypatch.setattr(drill.tempfile, "mkdtemp", lambda prefix: str(workdir))
    monkeypatch.setattr(drill, "check_port_free", lambda port: None)
    monkeypatch.setattr(drill, "find_chrome", lambda: "/bin/chrome")

    def explode(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(drill, "_copy_profile", explode)
    with pytest.raises(OSError, match="disk full"):
        drill.run_drill("/src")
    assert not workdir.exists()


def test_main_reports_error_and_exits_2(monkeypatch, capsys):
    monkeypatch.setattr(drill, "pick_source",
                        lambda **kw: (_ for _ in ()).throw(drill.DrillError("no profile")))
    assert drill.main([]) == 2
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "error" and "no profile" in out["detail"]


def test_main_unexpected_infra_exception_exits_2_not_1(monkeypatch, capsys):
    monkeypatch.setattr(drill, "pick_source", lambda **kw: "/src")
    monkeypatch.setattr(drill, "run_drill",
                        lambda *a, **kw: (_ for _ in ()).throw(OSError("boom")))
    assert drill.main([]) == 2
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "error" and "boom" in out["detail"]


def test_main_signed_in_exits_0(monkeypatch, capsys):
    monkeypatch.setattr(drill, "pick_source", lambda **kw: "/src")
    monkeypatch.setattr(drill, "run_drill",
                        lambda *a, **kw: {"verdict": "signed_in", "source": "/src"})
    assert drill.main(["--from-backup"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "signed_in"


def test_main_login_required_exits_1(monkeypatch, capsys):
    monkeypatch.setattr(drill, "pick_source", lambda **kw: "/src")
    monkeypatch.setattr(drill, "run_drill", lambda *a, **kw: {"verdict": "login_required"})
    assert drill.main([]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "login_required"


def test_main_inconclusive_exits_2(monkeypatch, capsys):
    monkeypatch.setattr(drill, "pick_source", lambda **kw: "/src")
    monkeypatch.setattr(drill, "run_drill", lambda *a, **kw: {"verdict": "inconclusive"})
    assert drill.main([]) == 2
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "inconclusive"
