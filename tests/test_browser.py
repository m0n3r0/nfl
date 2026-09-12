"""Hermetic tests for the browser lifecycle module (yahoo/browser.py)."""

from __future__ import annotations

import json

import pytest

from yahoo import browser

CFT_TMP = "/tmp/cft/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
REAL_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def test_find_chrome_prefers_env_override():
    isfile = lambda p: p == "/custom/chrome"
    assert browser.find_chrome({"CHROME_PATH": "/custom/chrome"}, isfile) == "/custom/chrome"


def test_find_chrome_candidate_order(monkeypatch):
    monkeypatch.setattr(browser.platform, "machine", lambda: "arm64")
    isfile = lambda p: p in {CFT_TMP, REAL_CHROME}
    assert browser.find_chrome({}, isfile) == CFT_TMP


def test_find_chrome_skips_missing_tmp_for_persistent_install():
    isfile = lambda p: p == REAL_CHROME
    assert browser.find_chrome({}, isfile) == REAL_CHROME


def test_find_chrome_returns_none_when_nothing_exists():
    assert browser.find_chrome({}, lambda p: False) is None


def test_cdp_alive_true_when_version_answers(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return json.dumps({"Browser": "Chrome/153"}).encode()

    monkeypatch.setattr(browser.urllib.request, "urlopen", lambda *a, **k: Response())

    assert browser.cdp_alive() is True


def test_cdp_alive_false_on_connection_error(monkeypatch):
    def down(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr(browser.urllib.request, "urlopen", down)

    assert browser.cdp_alive() is False


def test_ensure_browser_is_idempotent_when_alive(monkeypatch):
    monkeypatch.setattr(browser, "cdp_alive", lambda *a, **k: True)

    def forbidden_launch(*a, **k):
        raise AssertionError("launch must not run when CDP is alive")

    monkeypatch.setattr(browser, "launch", forbidden_launch)

    assert browser.ensure_browser()["status"] == "already_running"


def test_ensure_browser_launches_when_down(monkeypatch):
    calls = {"alive": 0}

    def flapping_alive(*a, **k):
        calls["alive"] += 1
        return calls["alive"] > 1

    class Proc:
        pid = 4242

        def poll(self):
            return None

    launched = {}

    monkeypatch.setattr(browser, "cdp_alive", flapping_alive)
    monkeypatch.setattr(browser, "find_chrome", lambda: "/fake/chrome")
    monkeypatch.setattr(browser, "launch", lambda binary, profile, url, port: launched.update(
        binary=binary, profile=profile, url=url, port=port) or Proc())
    monkeypatch.setattr(browser.time, "sleep", lambda *_: None)

    status = browser.ensure_browser(profile="/fake/profile", url="https://example.test/")

    assert status["status"] == "launched"
    assert launched["binary"] == "/fake/chrome"
    assert launched["port"] == 9222
    assert status["pid"] == "4242"


def test_ensure_browser_reports_immediate_exit(monkeypatch):
    monkeypatch.setattr(browser, "cdp_alive", lambda *a, **k: False)
    monkeypatch.setattr(browser, "find_chrome", lambda: "/fake/chrome")

    class Proc:
        pid = 1

        def poll(self):
            return 0  # process exited immediately -> launch failure

    monkeypatch.setattr(browser, "launch", lambda *a, **k: Proc())
    monkeypatch.setattr(browser.time, "sleep", lambda *_: None)

    with pytest.raises(browser.BrowserError, match="exited during launch"):
        browser.ensure_browser()


def test_ensure_browser_refuses_install_when_disabled(monkeypatch):
    monkeypatch.setattr(browser, "cdp_alive", lambda *a, **k: False)
    monkeypatch.setattr(browser, "find_chrome", lambda: None)

    with pytest.raises(browser.BrowserError, match="install disabled"):
        browser.ensure_browser(install=False)


def _fake_profile(root):
    profile = root / "edge-draft-profile"
    (profile / "Default" / "Network").mkdir(parents=True)
    (profile / "Default" / "Network" / "Cookies").write_text("session")
    (profile / "Local State").write_text("{}")
    (profile / "Cache").mkdir()
    (profile / "Cache" / "junk").write_text("x")
    (profile / "SingletonLock").write_text("pid")
    return profile


def test_backup_excludes_caches_and_locks(tmp_path):
    profile = _fake_profile(tmp_path / "live")
    report = browser.backup_profile(profile=str(profile),
                                    backup_root=str(tmp_path / "backups"))
    dest = tmp_path / "backups" / profile.name

    assert report["status"] == "backed_up"
    assert (dest / "Default" / "Network" / "Cookies").read_text() == "session"
    assert (dest / "Local State").exists()
    assert not (dest / "Cache").exists()
    assert not (dest / "SingletonLock").exists()


def test_restore_roundtrip_recreates_missing_profile(tmp_path):
    profile = _fake_profile(tmp_path / "live")
    backup_root = tmp_path / "backups"
    browser.backup_profile(profile=str(profile), backup_root=str(backup_root))
    import shutil
    shutil.rmtree(profile)

    assert browser.restore_profile(profile=str(profile), backup_root=str(backup_root)) is True
    assert (profile / "Default" / "Network" / "Cookies").read_text() == "session"


def test_restore_returns_false_without_backup(tmp_path):
    assert browser.restore_profile(profile=str(tmp_path / "nope"),
                                   backup_root=str(tmp_path / "empty")) is False


def test_backup_missing_profile_raises(tmp_path):
    with pytest.raises(browser.BrowserError, match="profile not found"):
        browser.backup_profile(profile=str(tmp_path / "missing"),
                               backup_root=str(tmp_path / "backups"))


def test_ensure_browser_restores_missing_profile(monkeypatch, tmp_path):
    calls = {"alive": 0}

    def flapping_alive(*a, **k):
        calls["alive"] += 1
        return calls["alive"] > 1

    class Proc:
        pid = 7

        def poll(self):
            return None

    restored = {}
    missing = str(tmp_path / "edge-draft-profile")

    monkeypatch.setattr(browser, "cdp_alive", flapping_alive)
    monkeypatch.setattr(browser, "find_chrome", lambda: "/fake/chrome")
    monkeypatch.setattr(browser, "launch", lambda *a, **k: Proc())
    monkeypatch.setattr(browser, "restore_profile",
                        lambda profile, **k: restored.setdefault("profile", profile) or True)
    monkeypatch.setattr(browser.time, "sleep", lambda *_: None)

    status = browser.ensure_browser(profile=missing)

    assert restored["profile"] == missing
    assert status["profile_restored"] == "true"


def test_chrome_candidates_follow_cpu_platform(monkeypatch):
    monkeypatch.setattr(browser.platform, "machine", lambda: "x86_64")

    assert any("/tmp/cft/chrome-mac-x64/" in c for c in browser.chrome_candidates())
    assert not any("chrome-mac-arm64" in c for c in browser.chrome_candidates())


def _fake_urlopen(payload, json_payload=None):
    import io

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def fake(url, *a, **k):
        if json_payload is not None and "versions" in str(url):
            return Response(json_payload)
        return Response(payload)

    return fake


def test_cft_download_url_reads_channel_metadata(monkeypatch):
    monkeypatch.setattr(browser.platform, "machine", lambda: "x86_64")
    payload = json.dumps({"channels": {"Stable": {"downloads": {"chrome": [
        {"platform": "mac-arm64", "url": "https://example.test/arm.zip"},
        {"platform": "mac-x64", "url": "https://example.test/x64.zip"},
    ]}}}}).encode()

    url = browser._cft_download_url(_fake_urlopen(payload))

    assert url == "https://example.test/x64.zip"


def test_install_chrome_for_testing_layout(monkeypatch, tmp_path):
    import io
    import zipfile

    monkeypatch.setattr(browser.platform, "machine", lambda: "x86_64")
    versions = json.dumps({"channels": {"Stable": {"downloads": {"chrome": [
        {"platform": "mac-x64", "url": "https://example.test/x64.zip"},
    ]}}}}).encode()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("chrome-mac-x64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing", "bin")
        zf.writestr("chrome-mac-x64/Google Chrome for Testing.app/Contents/Info.plist", "plist")

    dest = tmp_path / "Applications"
    binary = browser.install_chrome_for_testing(
        dest_dir=str(dest),
        urlopen=_fake_urlopen(buffer.getvalue(), json_payload=versions))

    assert (dest / "Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing").read_text() == "bin"
    assert binary.endswith("Google Chrome for Testing")
    assert not (dest / "chrome-mac-x64").exists()


def test_copy_profile_skips_transient_files(monkeypatch, tmp_path):
    profile = _fake_profile(tmp_path / "live")
    (profile / "RunningChromeVersion").write_text("v")
    dest = tmp_path / "backup"

    real_copy2 = browser.shutil.copy2

    def flaky_copy2(src, dst):
        if "Local State" in str(src):
            raise FileNotFoundError(src)  # vanished mid-copy
        return real_copy2(src, dst)

    monkeypatch.setattr(browser.shutil, "copy2", flaky_copy2)
    browser._copy_profile(profile, dest)

    assert (dest / "Default" / "Network" / "Cookies").exists()
    assert not (dest / "Local State").exists()
    assert not (dest / "RunningChromeVersion").exists()
