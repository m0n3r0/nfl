#!/usr/bin/env python3
"""Render and install the FD nation browser-keepalive LaunchAgent.

Reads tools/launchd/com.fdnation.browser.plist.template, substitutes the
actual repo root, writes ~/Library/LaunchAgents/com.fdnation.browser.plist,
and loads it with launchctl (macOS only). Idempotent.
"""

from __future__ import annotations

import argparse
import plistlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "tools" / "launchd" / "com.fdnation.browser.plist.template"
DEST = Path.home() / "Library" / "LaunchAgents" / "com.fdnation.browser.plist"


def render(template: Path = TEMPLATE, repo_root: Path = ROOT) -> dict:
    """Render the plist template for repo_root and return the plist object."""
    text = template.read_text(encoding="utf-8").replace("@REPO_ROOT@", str(repo_root))
    return plistlib.loads(text.encode())


def install(dest: Path = DEST, load: bool = True) -> Path:
    """Write the rendered plist and (re)load it with launchctl."""
    rendered = render()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        subprocess.run(["launchctl", "unload", str(dest)], check=False)
    dest.write_bytes(plistlib.dumps(rendered))
    if load:
        subprocess.run(["launchctl", "load", str(dest)], check=True)
    return dest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-load", action="store_true", help="write the plist without loading it")
    args = parser.parse_args()
    if sys.platform != "darwin":
        print("launchd agents are macOS-only", file=sys.stderr)
        return 2
    dest = install(load=not args.no_load)
    print(f"installed {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
