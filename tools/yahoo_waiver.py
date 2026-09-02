#!/usr/bin/env python3
"""Prepare or submit one exact Yahoo waiver claim."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from yahoo.cdp import CdpClient
from yahoo.team import find_team_target
from yahoo.waivers import WaiverClaim, WaiverError, YahooWaiverOperator


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--add-id", required=True)
    parser.add_argument("--add-name", required=True)
    parser.add_argument("--drop-id", required=True)
    parser.add_argument("--drop-name", required=True)
    parser.add_argument("--apply", action="store_true", help="create the claim; default stops at confirmation")
    parser.add_argument("--audit", type=Path, default=Path("logs/yahoo-waiver-audit.jsonl"))
    parser.add_argument("--endpoint", default="http://127.0.0.1:9222")
    args = parser.parse_args()
    claim = WaiverClaim(args.add_id, args.add_name, args.drop_id, args.drop_name)
    try:
        with CdpClient(find_team_target(args.endpoint), endpoint=args.endpoint, timeout=20) as client:
            operator = YahooWaiverOperator(client)
            try:
                receipt = operator.apply(claim) if args.apply else operator.prepare(claim)
            finally:
                operator.restore_team()
    except WaiverError as exc:
        print(f"WAIVER HALTED: {exc}", file=sys.stderr)
        return 2
    audit = {"at": datetime.now(timezone.utc).isoformat(), "apply": args.apply, **receipt.as_dict()}
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    with args.audit.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(audit, sort_keys=True) + "\n")
    print(json.dumps(receipt.as_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
