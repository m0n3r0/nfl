#!/usr/bin/env python3
"""In-season FD nation team operator: check -> monitor -> advise -> adjust -> report.

Run manually or via cron. Read-only by default: prints one JSON report and
appends one durable audit line to logs/team-operator.jsonl. --apply submits
the recommended lineup moves through the verified operator (lineup only;
waiver claims always remain a human decision -- the report just ranks targets).
An flock prevents overlapping cron/manual runs.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for entry in (str(ROOT), str(ROOT / "tools")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from src import corpus as corpus_mod, ingest, projections, schedule as sched  # noqa: E402
from src.config import league_preset  # noqa: E402
from yahoo.browser import BrowserError  # noqa: E402
from yahoo.cdp import CdpClient, CdpError  # noqa: E402
from yahoo.league import matchup  # noqa: E402
from yahoo.lineup import LineupError, YahooLineupOperator  # noqa: E402
from yahoo.recommend import apply_schedule_locks, monitor_report, propose_lineup  # noqa: E402
from yahoo.team import TEAM_PATH, YahooTeamReader, find_team_target  # noqa: E402
from yahoo.wire import rank_targets, scan_available  # noqa: E402

import preflight as preflight_mod  # noqa: E402  # tools/preflight.py

BASE = "https://football.fantasysports.yahoo.com"
AUDIT_LOG = ROOT / "logs" / "team-operator.jsonl"
LOCK_PATH = ROOT / "logs" / "team-operator.lock"


def _audit(record: dict) -> None:
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(AUDIT_LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


def run(args) -> dict:
    report: dict = {"time": datetime.now(timezone.utc).isoformat()}
    try:
        health = preflight_mod.preflight(endpoint=args.endpoint)
    except (BrowserError, CdpError) as exc:
        report.update({"status": "preflight_failed", "error": str(exc)})
        return report
    report["preflight"] = health
    if not (health.get("cdp") and health.get("team_tab") and health.get("auth")):
        report["status"] = "preflight_failed"
        return report

    if args.refresh_data:
        ingest.collect_corpus(refresh=True)

    target = find_team_target(args.endpoint)
    with CdpClient(target, args.endpoint, timeout=25) as client:
        snapshot = YahooTeamReader(client).snapshot()
        if args.apply and args.week is not None and args.week != snapshot.week:
            report.update({"status": "week_mismatch", "yahoo_week": snapshot.week,
                           "requested_week": args.week})
            return report
        corp = corpus_mod.build(preset=league_preset())
        week = args.week if args.week is not None else snapshot.week
        proj = projections.project_for_week(corp, week)
        snapshot, lock_warnings = apply_schedule_locks(
            snapshot, sched.locked_teams(corp["schedule_2026"], week))
        proposal = propose_lineup(snapshot, proj, week)

        report.update({
            "week": week,
            "record": snapshot.record,
            "waiver_priority": snapshot.waiver_priority,
            "lock_warnings": list(lock_warnings),
            "monitor": monitor_report(snapshot, proj, week),
            "proposal": proposal.as_dict(),
        })
        try:
            report["matchup"] = matchup(client).as_dict()
        except Exception as exc:  # decorative context; never abort the run
            report["matchup_error"] = str(exc)
        finally:
            client.navigate(f"{BASE}{TEAM_PATH}",
                            lambda url: url.rstrip("/").endswith(TEAM_PATH), 25)

        if args.waiver_scan:
            try:
                available = scan_available(client, week)
                targets, skipped = rank_targets(available, proj)
                report["wire"] = {"scanned": len(available), "skipped": skipped,
                                  "targets": targets[: args.top]}
            finally:
                client.navigate(f"{BASE}{TEAM_PATH}",
                                lambda url: url.rstrip("/").endswith(TEAM_PATH), 25)

        if args.apply and proposal.moves:
            try:
                receipt = YahooLineupOperator(client).apply(proposal.moves)
                report["applied"] = receipt.as_dict()
            except LineupError as exc:
                report["status"] = "lineup_halted"
                report["error"] = str(exc)
                return report

    report["status"] = "ok"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--week", type=int, default=None)
    parser.add_argument("--apply", action="store_true",
                        help="submit recommended lineup moves (default: report only)")
    parser.add_argument("--waiver-scan", action="store_true",
                        help="also scan and rank the wire (slow, ~1 min)")
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--refresh-data", action="store_true",
                        help="re-download nflverse data first")
    parser.add_argument("--endpoint", default="http://127.0.0.1:9222")
    args = parser.parse_args()

    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK_PATH, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            report = {"time": datetime.now(timezone.utc).isoformat(),
                      "status": "already_running"}
            _audit(report)
            print(json.dumps(report))
            return 3
        try:
            report = run(args)
        except Exception as exc:  # a crashed run still leaves an audit trace
            report = {"time": datetime.now(timezone.utc).isoformat(),
                      "status": "error", "error": str(exc)}

    _audit(report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("status") == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
