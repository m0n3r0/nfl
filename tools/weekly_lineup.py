#!/usr/bin/env python3
"""Recommend (and optionally apply) the weekly lineup from live roster + our projections.

Dry-run by default: prints the evaluated plan, warnings, and the exact moves.
Both paths append a durable audit record to logs/yahoo-lineup-audit.jsonl;
`--apply` additionally submits the moves through the verified lineup operator.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import corpus as corpus_mod, projections, schedule as sched  # noqa: E402
from yahoo.cdp import CdpClient  # noqa: E402
from yahoo.lineup import LineupError, YahooLineupOperator  # noqa: E402
from yahoo.recommend import apply_schedule_locks, propose_lineup  # noqa: E402
from yahoo.team import YahooTeamReader, find_team_target  # noqa: E402

AUDIT_LOG = ROOT / "logs" / "yahoo-lineup-audit.jsonl"


def _audit(record: dict) -> None:
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(AUDIT_LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


def _derive_on_bye(proj: pd.DataFrame, schedule: pd.DataFrame, week: int) -> pd.DataFrame | None:
    """Derive on_bye from the schedule: teams with a REG row this week play, the rest sit.

    Returns None when the schedule has no rows for the week at all, leaving the
    caller to fail closed rather than guess who is on bye.
    """
    reg = schedule[schedule["week"] == week]
    if "game_type" in reg.columns:
        reg = reg[reg["game_type"] == "REG"]
    if reg.empty:
        return None
    playing = set(reg["team"])
    out = proj.copy()
    out["on_bye"] = ~out["last_team"].isin(playing)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--week", type=int, default=None,
                        help="NFL week (default: current week from the schedule)")
    parser.add_argument("--preset", default="fd-nation")
    parser.add_argument("--apply", action="store_true", help="submit the moves (default: dry run)")
    parser.add_argument("--endpoint", default="http://127.0.0.1:9222")
    args = parser.parse_args()

    target = find_team_target(args.endpoint)
    with CdpClient(target, args.endpoint) as client:
        snapshot = YahooTeamReader(client).snapshot()

    corp = corpus_mod.build(preset=args.preset)
    week = args.week or sched.current_week(corp["schedule_2026"])
    proj = projections.project_for_week(corp, week)
    extra_warnings: list[str] = []
    fail_closed = False
    if "on_bye" not in proj.columns:
        derived = _derive_on_bye(proj, corp["schedule_2026"], week)
        if derived is None:
            fail_closed = True
            extra_warnings.append(
                f"schedule has no REG rows for week {week}; cannot determine byes, proposing no moves"
            )
        else:
            proj = derived
    snapshot, lock_warnings = apply_schedule_locks(
        snapshot, sched.locked_teams(corp["schedule_2026"], week))
    extra_warnings.extend(lock_warnings)
    proposal = propose_lineup(snapshot, proj, week)
    proposal = replace(
        proposal,
        moves=() if fail_closed else proposal.moves,
        warnings=tuple(extra_warnings) + proposal.warnings,
    )
    report = proposal.as_dict()

    record = {"time": datetime.now(timezone.utc).isoformat(),
              "week": week, "moves": report["moves"]}
    if not args.apply:
        record["status"] = "dry_run"
        _audit(record)
        print(json.dumps({"status": "dry_run", **report}, indent=2, sort_keys=True))
        return 0

    if not proposal.moves:
        record["status"] = "no_moves"
        _audit(record)
        print(json.dumps(record, indent=2, sort_keys=True))
        return 0
    try:
        with CdpClient(target, args.endpoint) as client:
            receipt = YahooLineupOperator(client).apply(proposal.moves)
    except LineupError as exc:
        record["status"] = "halted"
        record["error"] = str(exc)
        _audit(record)
        print(f"LINEUP HALTED: {exc}", file=sys.stderr)
        return 2
    record["status"] = "applied"
    record["receipt"] = receipt.as_dict()
    _audit(record)
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
