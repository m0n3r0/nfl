#!/usr/bin/env python3
"""Apply an exact, preconditioned Yahoo lineup permutation and verify it."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from yahoo.cdp import CdpClient
from yahoo.lineup import LineupError, LineupMove, YahooLineupOperator
from yahoo.team import find_team_target


def _move(value: str) -> LineupMove:
    parts = value.split(":")
    if len(parts) != 3 or not all(parts):
        raise argparse.ArgumentTypeError("move must be YAHOO_ID:FROM_SLOT:TO_SLOT")
    return LineupMove(*parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--move", action="append", type=_move, required=True)
    parser.add_argument("--apply", action="store_true", help="submit; without this flag, only print intent")
    parser.add_argument("--endpoint", default="http://127.0.0.1:9222")
    args = parser.parse_args()
    moves = tuple(args.move)
    if not args.apply:
        print(json.dumps({"status": "dry_run", "moves": [asdict(move) for move in moves]}, indent=2, sort_keys=True))
        return 0
    try:
        target = find_team_target(args.endpoint)
        with CdpClient(target, endpoint=args.endpoint) as client:
            receipt = YahooLineupOperator(client).apply(moves)
    except LineupError as exc:
        print(f"LINEUP HALTED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(receipt.as_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
