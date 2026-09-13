#!/usr/bin/env python3
"""Print league standings, the week scoreboard, and our matchup (read-only).

Other managers' team names appear in this output: keep it in the console or
local logs, never in committed files (this repo is public).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from yahoo.cdp import CdpClient, CdpError  # noqa: E402
from yahoo.league import (  # noqa: E402
    LeagueReadError,
    LeagueWafBlocked,
    matchup,
    opponent_roster,
    opponent_team_id,
    scoreboard,
    standings,
    team_ids,
)
from yahoo.team import TEAM_ID, TEAM_PATH, find_team_target  # noqa: E402

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


def merge_report(path: str, report: dict) -> None:
    """Light-mode persist: refresh the snapshot without dropping roster data.

    A light run captures no rosters, so writing it plainly would erase the
    roster map the web detail pages rely on. Merging old-then-new keeps the
    last good `rosters`/`opponent_roster` keys; refreshed keys (standings,
    matchup, and the scoreboard when its read succeeds) come from the new
    report, otherwise the old values carry forward as last-good. Missing or
    corrupt existing files degrade to a plain write (a light report still
    stands on its own).
    """
    try:
        old = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = None
    if isinstance(old, dict):
        # write_report re-stamps; a stale capture time or a leftover
        # waf_blocked status must not survive a healthy merged write.
        old.pop("captured_at", None)
        old.pop("status", None)
        report = {**old, **report}
    write_report(path, report)


def append_audit(path: str, report: dict) -> None:
    """Append the report as one JSON line (season history of snapshots).

    Same captured_at stamping and gitignored-path rule as write_report. One
    line is ~3 KB — well under the text buffer — so a single write() call
    keeps concurrent writers from interleaving a line in practice. A crash
    mid-append can leave a partial line that merges with the next one; the
    web reader skips unparseable lines, so the history self-heals.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    stamped = {"captured_at": datetime.now(timezone.utc).isoformat(), **report}
    with open(target, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(stamped, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--opponent-roster", action="store_true",
                        help="also read the matchup opponent's roster")
    parser.add_argument("--all-rosters", action="store_true",
                        help="also read every other team's roster (paced, nightly use)")
    parser.add_argument("--light", action="store_true",
                        help="game-day refresh: standings + scoreboard + matchup only "
                             "(no roster reads); --out merges so prior rosters survive")
    parser.add_argument("--roster-delay", type=float, default=3.0, metavar="SECONDS",
                        help="pause between per-team roster reads (default 3.0)")
    parser.add_argument("--endpoint", default="http://127.0.0.1:9222")
    parser.add_argument("--out", metavar="PATH",
                        help="also persist the report JSON to PATH (e.g. logs/league-report.json)")
    parser.add_argument("--audit", metavar="PATH",
                        help="also append the report as one JSON line to PATH (season history)")
    args = parser.parse_args()
    if args.roster_delay < 0:
        parser.error("--roster-delay must be >= 0")
    if args.light and (args.all_rosters or args.opponent_roster):
        parser.error("--light reads no rosters; it conflicts with --all-rosters/--opponent-roster")

    target = find_team_target(args.endpoint)
    with CdpClient(target, args.endpoint, timeout=25) as client:
        blocked = False
        try:
            report = {
                "standings": [row.as_dict() for row in standings(client)],
            }
            try:
                # Free like team_ids: evaluates on the page standings() loaded.
                report["scoreboard"] = [e.as_dict() for e in scoreboard(client)]
            except LeagueWafBlocked:
                raise  # never downgrade a block to a warning, same as rosters
            except CdpError as exc:
                # A scoreboard miss — parse failure OR a CDP hiccup on this
                # free read — must never kill the standings+matchup core.
                print(f"warning: scoreboard skipped: {exc}", file=sys.stderr)
            ids = {}
            if args.all_rosters:
                try:
                    ids = team_ids(client)  # free: still on the standings page
                except LeagueReadError as exc:
                    print(f"warning: team id map skipped: {exc}", file=sys.stderr)
            report["matchup"] = matchup(client).as_dict()
            if args.opponent_roster:
                try:
                    opp_id = opponent_team_id(client)
                    report["opponent_team_id"] = opp_id
                    report["opponent_roster"] = list(opponent_roster(client, opp_id))
                except LeagueWafBlocked:
                    raise  # never downgrade a block to a warning: exit 2 + skip restore
                except LeagueReadError as exc:
                    # The roster is a bonus read on a fragile page; its failure
                    # must never kill the standings+matchup snapshot.
                    print(f"warning: opponent roster skipped: {exc}", file=sys.stderr)
            if args.all_rosters:
                rosters = {}
                others = [(name, tid) for name, tid in ids.items() if tid != TEAM_ID]
                # opponent_roster refuses our own team by design, so it is
                # filtered before the paced loop (and never costs a delay).
                for i, (name, tid) in enumerate(others):
                    if i:
                        time.sleep(args.roster_delay)  # pace the batch for the WAF
                    try:
                        rosters[name] = list(opponent_roster(client, tid))
                    except LeagueWafBlocked:
                        raise  # full waf_blocked contract, see above
                    except LeagueReadError as exc:
                        print(f"warning: roster for {name!r} skipped: {exc}",
                              file=sys.stderr)
                report["rosters"] = rosters
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
    if report.get("status") == "waf_blocked":
        if args.out or args.audit:
            # Never overwrite the last good snapshot with a throttle stub,
            # and never pollute the season history with one either; exit 2
            # already signals the condition to cron.
            print("not persisting a waf_blocked stub", file=sys.stderr)
    else:
        for persist, path in ((write_report, args.out), (append_audit, args.audit)):
            if not path:
                continue
            if args.light and persist is write_report:
                persist = merge_report  # keep the last good roster map
            try:
                persist(path, report)
            except OSError as exc:  # the live-fetched report must still stand
                print(f"warning: could not persist report to {path}: {exc}",
                      file=sys.stderr)
    return 2 if report.get("status") == "waf_blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
