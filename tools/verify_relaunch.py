#!/usr/bin/env python3
"""Relaunch drill: prove a fresh browser with a profile copy is still logged in.

Answers "if Chrome has to be relaunched, will the Yahoo session come back?"
without risking the live operator browser: the drill copies the profile (or,
with --from-backup, the latest backup in ~/edge-profile-backups) to a temp dir,
launches a throwaway headless Chrome-for-Testing against the copy, runs the
canonical signed-in check (same-origin fetch of the protected team page), then
kills the throwaway instance and deletes the copy.

The live browser is never touched: by default the throwaway browser gets an
OS-assigned CDP port read back from its own DevToolsActivePort file, so the
drill can only ever attach to the child it launched. An explicit --port is
refused when it is the live operator port or already answers CDP.

Exit codes:
  0  signed in — a relaunch with this profile/backup needs no human login
  1  NOT signed in — positive evidence (login page, 4xx); do a manual login,
     then re-run tools/profile_backup.py
  2  inconclusive (Yahoo WAF throttling, no clean answer — back off and retry)
     or infrastructure error (no Chrome binary, source missing, ...)
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from yahoo.browser import (  # noqa: E402
    BACKUP_ROOT,
    DEFAULT_ENDPOINT,
    DEFAULT_PROFILE,
    DEFAULT_URL,
    _copy_profile,
    cdp_alive,
    find_chrome,
)

DRILL_PORT = 0  # 0 = OS-assigned, read back from the child's DevToolsActivePort
MANAGER = "Doge"
TEAM_PAGE = "/f1/1329011/team/002"


class DrillError(RuntimeError):
    """Infrastructure failure that prevented the drill from answering."""


def pick_source(profile: str = DEFAULT_PROFILE, backup_root: str = BACKUP_ROOT,
                from_backup: bool = False, isdir=None) -> str:
    """Resolve which tree the drill copies: the live profile or its backup."""
    isdir = isdir or (lambda p: Path(p).is_dir())
    source = Path(backup_root) / Path(profile).name if from_backup else Path(profile)
    if not isdir(str(source)):
        kind = "backup" if from_backup else "profile"
        raise DrillError(f"{kind} not found: {source}")
    return str(source)


def drill_launch_args(binary: str, profile_copy: str, port: int, url: str) -> list[str]:
    """Launch flags for the throwaway instance (browser.launch + --headless=new)."""
    return [
        binary,
        "--headless=new",
        f"--remote-debugging-port={port}",
        "--remote-debugging-address=127.0.0.1",
        "--remote-allow-origins=*",
        "--use-mock-keychain",
        f"--user-data-dir={profile_copy}",
        "--no-first-run",
        "--no-default-browser-check",
        "--window-size=1400,900",
        url,
    ]


def check_port_free(port: int, live_endpoint: str = DEFAULT_ENDPOINT, alive=cdp_alive) -> None:
    """Refuse an explicit port that collides with the live browser or any CDP answer."""
    if port == 0:
        return  # OS-assigned; no collision possible
    live_port = int(urlparse(live_endpoint).port or 9222)
    if port == live_port:
        raise DrillError(f"port {port} is the live operator port; pick another")
    endpoint = f"http://127.0.0.1:{port}"
    if alive(endpoint):
        raise DrillError(f"something already answers CDP on {endpoint}; refusing to disturb it")


def read_devtools_port(profile_copy: str) -> int | None:
    """Return the CDP port the drill child wrote into its user-data-dir, if any."""
    try:
        first_line = (Path(profile_copy) / "DevToolsActivePort").read_text().splitlines()[0]
        return int(first_line)
    except (OSError, IndexError, ValueError):
        return None


def verdict(team_status: int | None, manager_found: bool, denied: bool = False) -> str:
    """Map the signed-in check to a drill verdict.

    Denial wins: a WAF denial (or status 999) is throttling, never a logout —
    the drill cannot judge the session while throttled. 429 and 5xx are
    throttling/outage, and no answer at all (status None: connection dropped,
    fetch failed) is likewise inconclusive. Only positive evidence (a 200
    without the manager, a 401/403 auth rejection, or a login-page redirect)
    means the session is really dead; any other status (404 = stale probe
    path, ...) is not auth evidence and stays inconclusive.
    """
    if denied or team_status in (429, 999) or (team_status or 0) >= 500:
        return "inconclusive"
    if team_status == 200:
        return "signed_in" if manager_found else "login_required"
    if team_status is None:
        return "inconclusive"
    if team_status in (401, 403) or 300 <= team_status < 400:
        return "login_required"
    return "inconclusive"


def _ws_eval(ws, expr: str, await_promise: bool = False, msg_id: int = 1):
    ws.send(json.dumps({"id": msg_id, "method": "Runtime.evaluate",
                        "params": {"expression": expr, "returnByValue": True,
                                   "awaitPromise": await_promise}}))
    while True:
        msg = json.loads(ws.recv())
        if msg.get("id") == msg_id:
            return msg.get("result", {}).get("result", {}).get("value")


def signed_in_check(endpoint: str, url: str, manager: str = MANAGER,
                    probe_path: str = TEAM_PAGE, settle: float = 6.0,
                    retries: int = 3) -> dict:
    """Run the canonical same-origin probe on the drill browser's league tab.

    A fresh browser loads its cookie store asynchronously, so an early probe
    can go out anonymously and miss the manager name on a perfectly valid
    session. The probe therefore retries with escalating waits and only
    returns early on a definitive answer (manager found, WAF denial, a
    non-200 response, or a login redirect).

    The fetch uses redirect: 'manual' because a logged-out team fetch
    redirects cross-origin to login.yahoo.com, which CORS-mode fetch can
    reject — that would surface as status None (inconclusive) and hide a
    real logout. With manual redirects the 3xx is seen directly and maps to
    login_required.
    """
    import websocket  # websocket-client; imported lazily so pure tests stay stdlib

    expr = """(function(){
        return fetch(%r, {credentials: 'same-origin', redirect: 'manual'})
          .then(function(r){
              if (r.type === 'opaqueredirect' || (r.status >= 300 && r.status < 400)) {
                  return {status: 302, manager_found: false, denied: false,
                          redirected: true, final_url: r.url};
              }
              return r.text().then(function(h){
                  return {status: r.status, manager_found: (h.toLowerCase().indexOf(%r) >= 0),
                          denied: /request denied/i.test(h),
                          final_url: r.url};
              });
          })
          .catch(function(e){ return {status: null, manager_found: false,
                                      denied: false, error: String(e)}; });
    })()""" % (probe_path, manager.lower())
    last: dict = {"status": None, "manager_found": False, "denied": False}
    for attempt in range(retries + 1):
        tabs = json.loads(urllib.request.urlopen(endpoint + "/json", timeout=8).read())
        pages = [t for t in tabs if t.get("type") == "page"]
        if not pages:
            time.sleep(settle)
            continue
        tab = next((t for t in pages if "fantasysports" in t.get("url", "")), pages[0])
        ws = websocket.create_connection(tab["webSocketDebuggerUrl"], timeout=20,
                                         header={"Origin": endpoint})
        try:
            if "fantasysports" not in tab.get("url", ""):
                ws.send(json.dumps({"id": 99, "method": "Page.navigate",
                                    "params": {"url": url}}))
                time.sleep(settle)
            result = _ws_eval(ws, expr, await_promise=True)
        finally:
            ws.close()
        if isinstance(result, dict):
            last = result
            # 302 is deliberately NOT definitive: an early probe can go out
            # anonymously while the cookie store loads and redirect exactly
            # like a real logout. A real logout persists across retries.
            definitive = (result.get("manager_found") or result.get("denied")
                          or (result.get("status") not in (None, 200, 302))
                          or "login.yahoo" in str(result.get("final_url", "")))
            if definitive:
                return last
        if attempt < retries:
            time.sleep(settle * (attempt + 1))
    return last


def run_drill(source: str, port: int = DRILL_PORT, url: str = DEFAULT_URL,
              manager: str = MANAGER, probe_path: str = TEAM_PAGE,
              binary: str | None = None, launch_timeout: float = 25.0) -> dict:
    """Copy source, launch the throwaway browser, probe, clean up. Returns a report."""
    binary = binary or find_chrome()
    if binary is None:
        raise DrillError("no Chrome binary found (see yahoo.browser.chrome_candidates)")
    check_port_free(port)  # the live-browser safety invariant lives here
    workdir = tempfile.mkdtemp(prefix="relaunch-drill-")
    process: subprocess.Popen | None = None
    try:
        profile_copy = str(Path(workdir) / "profile")
        _copy_profile(Path(source), Path(profile_copy))
        log = open(Path(workdir) / "chrome.log", "ab")
        process = subprocess.Popen(drill_launch_args(binary, profile_copy, port, url),
                                   stdout=log, stderr=log, start_new_session=True)
        endpoint = None
        deadline = time.monotonic() + launch_timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise DrillError(f"drill browser exited early; see {workdir}/chrome.log")
            actual = port or read_devtools_port(profile_copy)
            if actual and cdp_alive(f"http://127.0.0.1:{actual}"):
                endpoint = f"http://127.0.0.1:{actual}"
                break
            time.sleep(0.5)
        if endpoint is None:
            raise DrillError(f"drill browser did not expose CDP within {launch_timeout}s")
        time.sleep(6)  # let the league tab finish loading before probing
        check = signed_in_check(endpoint, url, manager=manager, probe_path=probe_path)
        return {"verdict": verdict(check.get("status"), bool(check.get("manager_found")),
                                   bool(check.get("denied"))),
                "source": source, "port": str(urlparse(endpoint).port),
                "team_page_status": str(check.get("status")),
                "manager_found": str(bool(check.get("manager_found"))),
                "redirected": str(bool(check.get("redirected"))),
                "final_url": str(check.get("final_url", ""))}
    finally:
        try:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        pass
        except OSError:
            pass  # child already gone; the temp dir must still be removed
        shutil.rmtree(workdir, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from-backup", action="store_true",
                        help="drill the latest backup instead of the live profile")
    parser.add_argument("--port", type=int, default=DRILL_PORT,
                        help="CDP port for the throwaway browser (default 0 = OS-assigned)")
    parser.add_argument("--manager", default=MANAGER,
                        help="manager name expected on the protected team page")
    args = parser.parse_args(argv)
    try:
        source = pick_source(from_backup=args.from_backup)
        report = run_drill(source, port=args.port, manager=args.manager)
    except DrillError as exc:
        print(json.dumps({"status": "error", "detail": str(exc)}, indent=1))
        return 2
    except Exception as exc:  # infra failures must never read as "session dead"
        print(json.dumps({"status": "error", "detail": f"{type(exc).__name__}: {exc}"}, indent=1))
        return 2
    report["status"] = report["verdict"]
    print(json.dumps(report, indent=1, sort_keys=True))
    if report["verdict"] == "signed_in":
        return 0
    if report["verdict"] == "login_required":
        return 1
    return 2  # inconclusive (e.g. WAF throttling) — retry after a backoff


if __name__ == "__main__":
    sys.exit(main())
