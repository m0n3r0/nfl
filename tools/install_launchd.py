#!/usr/bin/env python3
"""Render and install FD nation LaunchAgents.

Reads tools/launchd/com.fdnation.<agent>.plist.template, substitutes the
actual repo root, writes ~/Library/LaunchAgents/com.fdnation.<agent>.plist,
and loads it with launchctl (macOS only). Idempotent.

Agents:
  browser      browser keepalive (preflight chain)
  cloudflared  quick tunnel exposing the local web UI (127.0.0.1:5000) on an
               ephemeral *.trycloudflare.com URL — unauthenticated; the live
               URL lands in logs/cloudflared-url.txt (mode 0600)
  web          the Flask web UI itself on 127.0.0.1:5000 (loopback only)
"""

from __future__ import annotations

import argparse
import plistlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ("browser", "cloudflared", "web")


def template_path(agent: str, repo_root: Path = ROOT) -> Path:
    if agent not in AGENTS:
        raise ValueError(f"unknown agent {agent!r} (choose from {', '.join(AGENTS)})")
    return repo_root / "tools" / "launchd" / f"com.fdnation.{agent}.plist.template"


def dest_path(agent: str) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"com.fdnation.{agent}.plist"


def render(agent: str = "browser", repo_root: Path = ROOT) -> dict:
    """Render an agent's plist template for repo_root and return the plist object."""
    text = template_path(agent, repo_root).read_text(encoding="utf-8").replace(
        "@REPO_ROOT@", str(repo_root))
    return plistlib.loads(text.encode())


def install(agent: str = "browser", load: bool = True) -> Path:
    """Write the rendered plist and (re)load it with launchctl."""
    rendered = render(agent)
    dest = dest_path(agent)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        subprocess.run(["launchctl", "unload", str(dest)], check=False)
    dest.write_bytes(plistlib.dumps(rendered))
    if load:
        subprocess.run(["launchctl", "load", str(dest)], check=True)
    return dest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--agent", choices=AGENTS, default="browser")
    parser.add_argument("--no-load", action="store_true", help="write the plist without loading it")
    args = parser.parse_args()
    if sys.platform != "darwin":
        print("launchd agents are macOS-only", file=sys.stderr)
        return 2
    dest = install(args.agent, load=not args.no_load)
    print(f"installed {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
