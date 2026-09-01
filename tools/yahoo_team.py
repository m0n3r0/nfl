#!/usr/bin/env python3
"""Print the authoritative FD nation roster and lineup without mutating Yahoo."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from yahoo.cdp import CdpClient  # noqa: E402
from yahoo.team import YahooTeamReader, find_team_target  # noqa: E402


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--endpoint", default="http://127.0.0.1:9222")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    target = find_team_target(args.endpoint)
    with CdpClient(target, args.endpoint) as client:
        snapshot = YahooTeamReader(client).snapshot()
    print(json.dumps(snapshot.as_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
