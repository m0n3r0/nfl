"""Browser lifecycle for the Yahoo operators: find, (re)launch, health-check.

The operators only need a Chromium browser with CDP on loopback. This module
owns *which* binary runs and *how* it comes back after a reboot or a purged
/tmp, so the session is never stranded. Everything is stdlib-only.

Cookie persistence: Chrome for Testing is ad-hoc signed and cannot use the
macOS Keychain (no "Chrome Safe Storage" item), so by default its cookie
store is memory-only and every login dies with the browser process. The
launcher therefore passes --use-mock-keychain: cookies persist to disk
encrypted with Chrome's built-in mock key, and any later launch with the same
flag decrypts them. Tradeoff: anyone with read access to the profile dir can
decrypt its cookies — the profile is user-owned under $HOME and the CDP
endpoint is loopback-only, which this repo already treats as the trust
boundary.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import time
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urlparse

CHROME_PATH_ENV = "CHROME_PATH"
DEFAULT_ENDPOINT = "http://127.0.0.1:9222"
DEFAULT_PROFILE = str(Path.home() / "edge-draft-profile")
DEFAULT_URL = "https://football.fantasysports.yahoo.com/f1/1329011/2"
LAUNCH_LOG = "logs/chrome-launch.log"

CFT_VERSIONS_URL = (
    "https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json"
)
CFT_APP = "Google Chrome for Testing.app"
CFT_BINARY = f"{CFT_APP}/Contents/MacOS/Google Chrome for Testing"


class BrowserError(RuntimeError):
    """The browser could not be found, installed, or reached."""


def cft_platform() -> str:
    """Return the Chrome-for-Testing download platform for this CPU."""
    return "mac-arm64" if platform.machine() == "arm64" else "mac-x64"


def chrome_candidates(home: str | None = None) -> list[str]:
    """Return Chrome-family binary paths in preference order.

    The /tmp/cft entry is shared with the ~/games repo; /tmp clears on reboot,
    so persistent installs under ~/Applications come next.
    """
    home = home or str(Path.home())
    return [
        f"/tmp/cft/chrome-{cft_platform()}/{CFT_BINARY}",
        f"{home}/Applications/{CFT_BINARY}",
        f"{home}/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ]


def find_chrome(environ: dict[str, str] | None = None, isfile=os.path.isfile) -> str | None:
    """Return the first usable Chrome binary, or None."""
    environ = os.environ if environ is None else environ
    override = environ.get(CHROME_PATH_ENV)
    candidates = [override] if override else []
    candidates += chrome_candidates()
    for path in candidates:
        if path and isfile(path):
            return path
    return None


def cdp_alive(endpoint: str = DEFAULT_ENDPOINT, timeout: float = 5) -> bool:
    """Return whether a CDP HTTP endpoint answers /json/version."""
    try:
        with urllib.request.urlopen(endpoint + "/json/version", timeout=timeout) as response:
            return bool(json.load(response).get("Browser"))
    except (OSError, ValueError):
        return False


def _cft_download_url(urlopen=urllib.request.urlopen) -> str:
    """Return the latest stable Chrome-for-Testing download URL for this CPU."""
    arch = cft_platform()
    with urlopen(CFT_VERSIONS_URL, timeout=30) as response:
        data = json.load(response)
    stable = data["channels"]["Stable"]
    for download in stable["downloads"]["chrome"]:
        if download["platform"] == arch:
            return download["url"]
    raise BrowserError(f"no Chrome-for-Testing build for platform {arch}")


def install_chrome_for_testing(dest_dir: str | None = None, urlopen=urllib.request.urlopen) -> str:
    """Download and unpack Chrome for Testing; return the binary path.

    Used only when no candidate binary exists (e.g. after a reboot cleared
    /tmp). ~150 MB download.
    """
    dest = Path(dest_dir or Path.home() / "Applications")
    binary = dest / CFT_BINARY
    if binary.is_file():
        return str(binary)
    dest.mkdir(parents=True, exist_ok=True)
    archive = dest / "chrome-for-testing.zip"
    with urlopen(_cft_download_url(urlopen), timeout=120) as response, open(archive, "wb") as out:
        while chunk := response.read(1 << 20):
            out.write(chunk)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(dest)
    archive.unlink()
    extracted_dir = dest / f"chrome-{cft_platform()}"
    extracted = extracted_dir / CFT_BINARY
    if not extracted.is_file():
        raise BrowserError(f"unexpected archive layout: {extracted} missing")
    # Move the versioned top folder to the stable app path used by candidates.
    target = dest / CFT_APP
    if target.exists():
        raise BrowserError(f"cannot install: {target} already exists")
    (extracted_dir / CFT_APP).rename(target)
    try:
        extracted_dir.rmdir()
    except OSError:
        pass
    if not binary.is_file():
        raise BrowserError(f"install failed: {binary} missing")
    return str(binary)


def launch(binary: str, profile: str = DEFAULT_PROFILE, url: str = DEFAULT_URL,
           port: int = 9222) -> subprocess.Popen:
    """Launch the browser detached with the standard operator flags."""
    Path(profile).mkdir(parents=True, exist_ok=True)
    log_path = Path(LAUNCH_LOG)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = open(log_path, "ab")
    args = [
        binary,
        f"--remote-debugging-port={port}",
        "--remote-debugging-address=127.0.0.1",
        "--remote-allow-origins=*",
        "--use-mock-keychain",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--window-size=1400,900",
        url,
    ]
    return subprocess.Popen(args, stdout=log, stderr=log, start_new_session=True)


def ensure_browser(endpoint: str = DEFAULT_ENDPOINT, profile: str = DEFAULT_PROFILE,
                   url: str = DEFAULT_URL, install: bool = True,
                   timeout: float = 25) -> dict[str, str]:
    """Guarantee a CDP browser answers at endpoint, launching one if needed.

    Idempotent: an already-answering endpoint is left untouched. A missing
    profile is first restored from backup (see backup_profile) so the Yahoo
    session comes back without a human login.
    """
    if cdp_alive(endpoint):
        return {"status": "already_running", "endpoint": endpoint}
    restored = not Path(profile).is_dir() and restore_profile(profile)
    binary = find_chrome()
    if binary is None:
        if not install:
            raise BrowserError("no Chrome binary found and install disabled")
        binary = install_chrome_for_testing()
    port = int(urlparse(endpoint).port or 9222)
    process = launch(binary, profile=profile, url=url, port=port)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cdp_alive(endpoint):
            status = {"status": "launched", "endpoint": endpoint, "binary": binary,
                      "pid": str(process.pid)}
            if restored:
                status["profile_restored"] = "true"
            return status
        if process.poll() is not None:
            raise BrowserError(f"browser exited during launch; see {LAUNCH_LOG}")
        time.sleep(0.5)
    raise BrowserError(f"browser did not expose CDP within {timeout}s; see {LAUNCH_LOG}")


BACKUP_ROOT = str(Path.home() / "edge-profile-backups")

# Top-level profile entries that are regenerable caches or runtime locks —
# copying them wastes space, and stale Singleton* locks break a restore.
PROFILE_SKIP = {
    "Cache", "Code Cache", "GPUCache", "GrShaderCache", "ShaderCache",
    "GraphiteDawnCache", "Service Worker", "Crashpad", "blob_storage",
    "SingletonLock", "SingletonSocket", "SingletonCookie", "lockfile",
    "RunningChromeVersion",
}


def _copy_profile(src: Path, dest: Path) -> None:
    """Copy a Chrome profile tree minus caches and runtime locks.

    A live browser creates and deletes runtime files mid-copy (e.g.
    RunningChromeVersion); those are transient by definition, so a file that
    vanishes between listing and copy is skipped rather than fatal.
    """
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for entry in os.listdir(src):
        if entry in PROFILE_SKIP:
            continue
        source, target = src / entry, dest / entry
        try:
            if source.is_dir():
                shutil.copytree(source, target, dirs_exist_ok=True)
            else:
                shutil.copy2(source, target)
        except FileNotFoundError:
            continue


def backup_profile(profile: str = DEFAULT_PROFILE, backup_root: str = BACKUP_ROOT,
                   stop_browser: bool = False, endpoint: str = DEFAULT_ENDPOINT,
                   timeout: float = 20) -> dict[str, str]:
    """Snapshot the browser profile (cookies, saved logins) for same-machine restore.

    With stop_browser=True the operator browser is terminated first (consistent
    SQLite snapshot) and relaunched afterwards. With the default live copy the
    SQLite files may lag the running browser slightly; the session cookies
    Chrome has flushed still restore fine. Backups decrypt only on the machine
    and user account that created them (macOS Keychain holds the Chrome key).
    """
    src = Path(profile)
    if not src.is_dir():
        raise BrowserError(f"profile not found: {src}")
    stopped = False
    if stop_browser and cdp_alive(endpoint):
        subprocess.run(["pkill", "-f", f"user-data-dir={profile}"], check=False)
        stopped = True
        deadline = time.monotonic() + timeout
        while cdp_alive(endpoint) and time.monotonic() < deadline:
            time.sleep(0.5)
        if cdp_alive(endpoint):
            raise BrowserError(f"browser still running with profile {profile}")
    dest = Path(backup_root) / src.name
    _copy_profile(src, dest)
    report = {"status": "backed_up", "src": str(src), "dest": str(dest),
              "stopped_browser": str(stopped)}
    if stopped:
        ensure_browser(endpoint=endpoint, profile=profile)
        report["relaunched"] = "true"
    return report


def restore_profile(profile: str = DEFAULT_PROFILE, backup_root: str = BACKUP_ROOT,
                    backup_name: str | None = None) -> bool:
    """Restore a profile from a backup; return False when no backup exists.

    backup_name defaults to the profile's own directory name; pass it
    explicitly to restore a backup under a different target name.
    """
    src = Path(backup_root) / (backup_name or Path(profile).name)
    if not src.is_dir():
        return False
    _copy_profile(src, Path(profile))
    return True
