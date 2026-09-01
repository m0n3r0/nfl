#!/usr/bin/env python3
"""Cron-safe entry point for the explicitly authorized FD nation real draft."""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from yahoo.cdp import CdpClient, CdpError
from yahoo.real_draft import (
    AUTHORIZATION,
    RealDraftOperator,
    RealDraftSafetyError,
    UncertainSubmission,
    real_draft_preflight,
    require_real_authorization,
    wait_for_real_draft_target,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="http://127.0.0.1:9222")
    parser.add_argument("--confirm-real-draft", required=True)
    parser.add_argument("--expected-date", required=True, help="local ISO date; prevents stale cron execution")
    parser.add_argument("--audit", type=Path, default=ROOT / "logs" / "real-draft-audit.jsonl")
    parser.add_argument("--wait-minutes", type=float, default=90)
    parser.add_argument("--deadline-hours", type=float, default=4)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--lock", type=Path, default=ROOT / "logs" / "real-draft.lock")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    require_real_authorization(args.confirm_real_draft)
    if dt.date.today().isoformat() != args.expected_date:
        raise SystemExit(f"date gate refused execution: expected {args.expected_date}")
    if args.preflight_only:
        import json

        print(json.dumps(real_draft_preflight(args.endpoint), sort_keys=True))
        return 0
    args.lock.parent.mkdir(parents=True, exist_ok=True)
    lock = args.lock.open("w", encoding="utf-8")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("real draft orchestrator is already running", flush=True)
        return 0

    orchestration_deadline = time.monotonic() + (args.wait_minutes * 60) + (args.deadline_hours * 3600)
    target = None
    while time.monotonic() < orchestration_deadline:
        try:
            if target is None:
                target = wait_for_real_draft_target(args.endpoint, timeout=args.wait_minutes * 60)
            with CdpClient(target, args.endpoint) as client:
                picks = RealDraftOperator(client, args.audit).run(args.deadline_hours)
            print(f"REAL DRAFT COMPLETE: {len(picks)}/15", flush=True)
            return 0
        except UncertainSubmission as exc:
            print(f"REAL DRAFT HALTED: {exc}", flush=True)
            return 3
        except RealDraftSafetyError as exc:
            print(f"REAL DRAFT HALTED: {exc}", flush=True)
            return 5
        except CdpError as exc:
            print(f"CDP RECOVERY: {type(exc).__name__}: {exc}", flush=True)
            time.sleep(2)
            target = None
    print("REAL DRAFT HALTED: orchestration deadline exceeded", flush=True)
    return 4


if __name__ == "__main__":
    raise SystemExit(main())
