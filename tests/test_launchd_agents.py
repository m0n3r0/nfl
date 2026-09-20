"""Render checks for the launchd agent templates (browser + cloudflared)."""

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


def test_cloudflared_template_renders_keepalive_tunnel():
    plist = install_launchd.render("cloudflared")
    assert plist["Label"] == "com.fdnation.cloudflared"
    assert plist["RunAtLoad"] is True
    assert plist["KeepAlive"] is True
    (program,) = plist["ProgramArguments"]
    assert program.endswith("tools/launchd/cloudflared-run")
    assert "@REPO_ROOT@" not in program
    assert plist["StandardOutPath"].endswith("logs/cloudflared.log")


def test_unknown_agent_rejected():
    with pytest.raises(ValueError, match="unknown agent"):
        install_launchd.render("nope")
