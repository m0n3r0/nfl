#!/usr/bin/env python3
"""Print league standings and the current matchup score (read-only).

Other managers' team names appear in this output: keep it in the console or
local logs, never in committed files (this repo is public).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from yahoo.cdp import CdpClient  # noqa: E402
from yahoo.league import matchup, opponent_roster, opponent_team_id, standings  # noqa: E402
from yahoo.team import TEAM_PATH, find_team_target  # noqa: E402

BASE = "https://football.fantasysports.yahoo.com"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--opponent-roster", action="store_true",
                        help="also read the matchup opponent's roster")
    parser.add_argument("--endpoint", default="http://127.0.0.1:9222")
    args = parser.parse_args()

    target = find_team_target(args.endpoint)
    with CdpClient(target, args.endpoint, timeout=25) as client:
        try:
            report = {
                "standings": [row.as_dict() for row in standings(client)],
                "matchup": matchup(client).as_dict(),
            }
            if args.opponent_roster:
                opp_id = opponent_team_id(client)
                report["opponent_team_id"] = opp_id
                report["opponent_roster"] = list(opponent_roster(client, opp_id))
        finally:
            client.navigate(f"{BASE}{TEAM_PATH}",
                            lambda url: url.rstrip("/").endswith(TEAM_PATH), 25)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
