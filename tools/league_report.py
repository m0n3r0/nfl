#!/usr/bin/env python3
"""Print league standings and the current matchup score (read-only).

Other managers' team names appear in this output: keep it in the console or
local logs, never in committed files (this repo is public).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from yahoo.cdp import CdpClient, CdpError  # noqa: E402
from yahoo.league import LeagueWafBlocked, matchup, opponent_roster, opponent_team_id, standings  # noqa: E402
from yahoo.team import TEAM_PATH, find_team_target  # noqa: E402

BASE = "https://football.fantasysports.yahoo.com"


def write_report(path: str, report: dict) -> None:
    """Persist the report JSON atomically (unique tmp file + rename).

    The persisted copy gains a captured_at timestamp (the stdout contract is
    unchanged). The temp file is unique per process, so an overlapping
    manual/cron run can't rename another writer's half-written file. The path
    must stay under a gitignored directory (logs/): the report carries real
    manager names, which never belong in committed files.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    stamped = {"captured_at": datetime.now(timezone.utc).isoformat(), **report}
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.",
                                    suffix=".tmp", text=True)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(stamped, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--opponent-roster", action="store_true",
                        help="also read the matchup opponent's roster")
    parser.add_argument("--endpoint", default="http://127.0.0.1:9222")
    parser.add_argument("--out", metavar="PATH",
                        help="also persist the report JSON to PATH (e.g. logs/league-report.json)")
    args = parser.parse_args()

    target = find_team_target(args.endpoint)
    with CdpClient(target, args.endpoint, timeout=25) as client:
        blocked = False
        try:
            report = {
                "standings": [row.as_dict() for row in standings(client)],
                "matchup": matchup(client).as_dict(),
            }
            if args.opponent_roster:
                opp_id = opponent_team_id(client)
                report["opponent_team_id"] = opp_id
                report["opponent_roster"] = list(opponent_roster(client, opp_id))
        except LeagueWafBlocked:
            blocked = True
            report = {"status": "waf_blocked"}
        finally:
            # After a WAF block even one navigation can extend the throttle;
            # the tab is restored by the next green run instead.
            if not blocked:
                try:  # best-effort restore; never mask an earlier failure
                    client.navigate(f"{BASE}{TEAM_PATH}",
                                    lambda url: url.rstrip("/").endswith(TEAM_PATH), 25)
                except CdpError as exc:
                    print(f"warning: tab restore failed: {exc}", file=sys.stderr)
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.out:
        if report.get("status") == "waf_blocked":
            # Never overwrite the last good snapshot with a throttle stub;
            # exit 2 already signals the condition to cron.
            print("not persisting a waf_blocked stub over the last good snapshot",
                  file=sys.stderr)
        else:
            try:
                write_report(args.out, report)
            except OSError as exc:  # the live-fetched report must still stand
                print(f"warning: could not persist report to {args.out}: {exc}",
                      file=sys.stderr)
    return 2 if report.get("status") == "waf_blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
