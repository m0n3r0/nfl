#!/usr/bin/env python3
"""Back up (or restore) the operator browser profile, including the Yahoo session.

The backup preserves cookies and saved logins for same-machine restores: a
later launch with a restored profile picks the session up without a human
login. Restores only decrypt on the machine/user that created the backup.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from yahoo.browser import (  # noqa: E402
    BACKUP_ROOT,
    DEFAULT_ENDPOINT,
    DEFAULT_PROFILE,
    BrowserError,
    backup_profile,
    restore_profile,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=DEFAULT_PROFILE)
    parser.add_argument("--backup-root", default=BACKUP_ROOT)
    parser.add_argument("--stop-browser", action="store_true",
                        help="terminate the browser first for a consistent snapshot, then relaunch it")
    parser.add_argument("--restore", action="store_true",
                        help="restore the profile from backup instead of backing it up")
    args = parser.parse_args()
    try:
        if args.restore:
            if not restore_profile(profile=args.profile, backup_root=args.backup_root):
                raise BrowserError(f"no backup found under {args.backup_root}")
            report = {"status": "restored", "profile": args.profile}
        else:
            report = backup_profile(profile=args.profile, backup_root=args.backup_root,
                                    stop_browser=args.stop_browser, endpoint=DEFAULT_ENDPOINT)
    except BrowserError as exc:
        print(f"PROFILE BACKUP FAILED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
