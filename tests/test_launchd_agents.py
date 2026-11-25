"""Render checks for the launchd agent templates (browser + web)."""

import sys

import pytest

sys.path.insert(0, "tools")

import install_launchd  # noqa: E402


def test_browser_template_renders_repo_root():
    plist = install_launchd.render("browser")
    assert plist["Label"] == "com.fdnation.browser"
    args = plist["ProgramArguments"]
    assert any(a.endswith("tools/preflight.py") for a in args)
    assert all("@REPO_ROOT@" not in a for a in args)


def test_web_template_renders_axum_front_door():
    plist = install_launchd.render("web")
    assert plist["Label"] == "com.fdnation.web"
    assert plist["KeepAlive"] is True
    (program,) = plist["ProgramArguments"]
    assert program.endswith("rust/target/release/nfl-webd")
    assert "@REPO_ROOT@" not in program
    env = plist["EnvironmentVariables"]
    assert env["NFL_WEBD_BIND"] == "127.0.0.1:5000"
    assert "NFL_WEBD_BACKEND" not in env  # no upstream anymore
    assert "@REPO_ROOT@" not in env["NFL_WEBD_ROOT"]
    assert plist["StandardOutPath"].endswith("logs/web.log")


def test_predreport_template_renders_calendar_producer():
    plist = install_launchd.render("predreport")
    assert plist["Label"] == "com.fdnation.predreport"
    assert plist["RunAtLoad"] is True
    python, script = plist["ProgramArguments"]
    assert python.endswith(".venv/bin/python")
    assert script.endswith("tools/predictions_report.py")
    assert "@REPO_ROOT@" not in script
    cal = plist["StartCalendarInterval"]
    assert {"Hour": 6, "Minute": 12} in cal          # daily
    assert {"Weekday": 3, "Hour": 21, "Minute": 5} in cal  # post-refresh Wed
    assert plist["StandardOutPath"].endswith("logs/predictions-report.log")


def test_unknown_agent_rejected():
    with pytest.raises(ValueError, match="unknown agent"):
        install_launchd.render("nope")


def test_livepoints_template_renders_loop_poller():
    plist = install_launchd.render("livepoints")
    assert plist["Label"] == "com.fdnation.livepoints"
    assert plist["KeepAlive"] is True
    python, script, flag = plist["ProgramArguments"]
    assert python.endswith(".venv/bin/python")
    assert script.endswith("tools/live_points.py")
    assert flag == "--loop"
    assert "@REPO_ROOT@" not in script
    assert plist["StandardOutPath"].endswith("logs/live-points.log")
