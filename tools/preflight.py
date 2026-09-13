#!/usr/bin/env python3
"""Preflight for the in-season operators: CDP alive, team tab, session authed.

Heals what it can — launches the browser when CDP is down, navigates a tab to
the authorized FD nation team page when none is there — then verifies the
Yahoo session. Exits 0 only when the whole chain is green, 3 when Yahoo's WAF
is serving 'Request denied' (the session is fine; back off, do NOT re-login),
and 2 for any other failure.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from yahoo.browser import DEFAULT_ENDPOINT, DEFAULT_URL, BrowserError, cdp_alive, ensure_browser  # noqa: E402
from yahoo.cdp import CdpClient, CdpError, list_targets  # noqa: E402
from yahoo.team import is_team_target, is_team_url  # noqa: E402

AUTH_PROBE = r"""(function(){
  return fetch('/f1/1329011/team/002', {credentials: 'same-origin'})
    .then(function(r){ return r.text().then(function(html){
      return {status: r.status, doge: /Doge/i.test(html), denied: /Request denied/i.test(html)}; }); })
    .catch(function(e){ return {status: 0, doge: false, denied: false, error: String(e)}; });
})()"""

READY_PROBE = "({url: location.href, ready: document.readyState})"


def _probe_flags(probe: dict | None) -> dict:
    """Interpret the auth probe. A WAF block (denial body or Yahoo's 999) is a
    throttle, not a logout — report it apart so nobody re-logins pointlessly.
    Denial wins over doge on purpose: a false block costs a skipped run, a
    false pass hammers a throttled session — fail closed."""
    probe = probe or {}
    denied = bool(probe.get("denied")) or probe.get("status") == 999
    return {"waf_blocked": denied,
            "auth": bool(not denied and probe.get("status") == 200 and probe.get("doge"))}


def _wait_ready(client: CdpClient, timeout: float = 15) -> bool:
    """Wait until the tab has committed exactly the authorized team route."""
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = client.evaluate(READY_PROBE)
        if state and state.get("ready") in {"interactive", "complete"} \
                and is_team_url(state.get("url") or ""):
            return True
        time.sleep(0.25)
    return False


def _new_tab(endpoint: str, url: str, timeout: float = 8) -> str:
    """Open a fresh tab via the CDP HTTP endpoint; return its target id.

    Never hijacks an existing tab: an unattended preflight must not clobber a
    page the user (or another flow) is using. Modern Chrome requires PUT.
    """
    request = urllib.request.Request(f"{endpoint}/json/new?{url}", method="PUT")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return str(json.load(response)["id"])
    except (OSError, ValueError, KeyError) as exc:
        raise CdpError(f"new-tab creation failed: {exc}") from exc


def preflight(endpoint: str = DEFAULT_ENDPOINT, url: str = DEFAULT_URL) -> dict:
    report: dict = {"endpoint": endpoint, "cdp": False, "launched": False,
                    "team_tab": False, "auth": False}
    if not cdp_alive(endpoint):
        ensure_browser(endpoint=endpoint, url=url)
        report["launched"] = True
    report["cdp"] = cdp_alive(endpoint)
    if not report["cdp"]:
        return report

    targets = list_targets(endpoint)
    if any(is_team_target(t) for t in targets):
        report["team_tab"] = True
        target = next(t for t in targets if is_team_target(t))
    else:
        target_id = _new_tab(endpoint, url)
        refreshed = {t.id: t for t in list_targets(endpoint)}
        if target_id not in refreshed:
            report["error"] = "new tab did not register as a target"
            return report
        target = refreshed[target_id]
        report["new_tab"] = True

    with CdpClient(target, endpoint) as client:
        if not _wait_ready(client):
            report["error"] = "team page did not finish loading"
            return report
        probe = client.evaluate(AUTH_PROBE, timeout=20)
    report["team_tab"] = True
    report.update(_probe_flags(probe))
    report["auth_probe"] = probe
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--url", default=DEFAULT_URL)
    args = parser.parse_args()
    try:
        report = preflight(endpoint=args.endpoint, url=args.url)
    except (BrowserError, CdpError) as exc:
        print(json.dumps({"cdp": False, "error": str(exc)}, indent=2, sort_keys=True))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    if report.get("waf_blocked"):
        return 3
    return 0 if report.get("cdp") and report.get("team_tab") and report.get("auth") else 2


if __name__ == "__main__":
    raise SystemExit(main())
