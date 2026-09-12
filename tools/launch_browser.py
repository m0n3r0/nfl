#!/usr/bin/env python3
"""Launch (or find) the operator browser with CDP on loopback. Idempotent."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from yahoo.browser import (  # noqa: E402
    DEFAULT_ENDPOINT,
    DEFAULT_PROFILE,
    DEFAULT_URL,
    BrowserError,
    ensure_browser,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--profile", default=DEFAULT_PROFILE)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--no-install", action="store_true",
                        help="fail instead of downloading Chrome for Testing")
    args = parser.parse_args()
    try:
        status = ensure_browser(endpoint=args.endpoint, profile=args.profile,
                                url=args.url, install=not args.no_install)
    except BrowserError as exc:
        print(f"BROWSER LAUNCH FAILED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
