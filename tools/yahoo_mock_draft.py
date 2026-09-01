#!/usr/bin/env python3
"""Inspect, join, or operate a Yahoo mock draft through loopback CDP only."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from yahoo.mock_draft import MockDraftOperator, MockLobby, find_mock_draft_target  # noqa: E402
from yahoo.cdp import CdpClient, select_target  # noqa: E402


def parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--endpoint", default="http://127.0.0.1:9222")
    sub = result.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list available ten-team mock rooms and slots")
    join = sub.add_parser("join", help="join one exact mock room and slot")
    join.add_argument("--room", required=True)
    join.add_argument("--slot", required=True, type=int)
    run = sub.add_parser("run", help="draft all 15 rounds in an already-open mock room")
    run.add_argument("--room", required=True)
    run.add_argument("--log", type=Path)
    return result


def main(argv: list[str] | None = None) -> int:
    """Execute the selected mock-only workflow."""
    args = parser().parse_args(argv)
    if args.command in {"list", "join"}:
        target = select_target(
            lambda item: "football.fantasysports.yahoo.com" in item.url and "mock_lobby" in item.url,
            args.endpoint,
        )
        with CdpClient(target, args.endpoint) as client:
            lobby = MockLobby(client, args.endpoint)
            if args.command == "list":
                print(json.dumps([room.as_dict() for room in lobby.rooms(teams=10)], indent=2))
            else:
                joined = lobby.join(args.room, args.slot)
                print(json.dumps({"room": args.room, "slot": args.slot, "target": joined.url}))
        return 0

    target = find_mock_draft_target(args.room, args.endpoint)
    with CdpClient(target, args.endpoint) as client:
        picks = MockDraftOperator(client, args.room, log_path=args.log).run()
    print(json.dumps([pick.as_dict() for pick in picks], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
