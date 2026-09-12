#!/usr/bin/env python3
"""Rank available free agents/waiver players by our weekly projection.

Read-only: paginates the Yahoo players pages (never clicks), reconciles every
available player against the projection model, and prints the best available
per week. Use before deciding a waiver claim; the claim itself goes through
tools/yahoo_waiver.py with exact IDs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import corpus as corpus_mod, projections  # noqa: E402
from src.config import league_preset  # noqa: E402
from yahoo.cdp import CdpClient  # noqa: E402
from yahoo.team import TEAM_PATH, YahooTeamReader, find_team_target  # noqa: E402
from yahoo.wire import rank_targets, scan_available  # noqa: E402

BASE = "https://football.fantasysports.yahoo.com"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--week", type=int, default=None,
                        help="projection week (default: the roster page's current week)")
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--endpoint", default="http://127.0.0.1:9222")
    args = parser.parse_args()
    if args.top < 0:
        parser.error("--top must be >= 0")

    with CdpClient(find_team_target(args.endpoint), endpoint=args.endpoint, timeout=25) as client:
        snapshot = YahooTeamReader(client).snapshot()
        week = args.week or snapshot.week
        try:
            available = scan_available(client, week)
        finally:
            client.navigate(f"{BASE}{TEAM_PATH}",
                            lambda url: urlparse(url).path.rstrip("/") == TEAM_PATH, 30)

    corp = corpus_mod.build(preset=league_preset())
    proj = projections.project_for_week(corp, week)
    ranked, skipped = rank_targets(available, proj)

    print(json.dumps({
        "week": week,
        "available_scanned": len(available),
        "skipped": skipped,
        "targets": ranked[: args.top],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
