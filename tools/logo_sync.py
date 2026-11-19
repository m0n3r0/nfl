#!/usr/bin/env python3
"""Sync fantasy team logos to local artifacts (cron-driven, fail-soft).

Takes the team -> logo URL map captured from the league home page
(yahoo.league.team_logos), downloads each image from the PUBLIC CDN
(s.yimg.com / cloudinary — no Yahoo fantasy requests involved), and
maintains data/logos.json + data/logos/<team_id>.<ext>.

Cache: an unchanged URL with an existing file is never re-downloaded.
The web layer (nfl-webd) serves these local files only — live reads
belong to the cron jobs, per the architecture rule.

Integrated into tools/league_report.py (nightly --all-rosters and
game-day --light runs both read the league home page, so logos stay
fresh automatically). Standalone retry:

    python tools/logo_sync.py [--endpoint http://127.0.0.1:9222]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for entry in (str(ROOT), str(ROOT / "tools")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

LOGO_DIR = ROOT / "data" / "logos"
MANIFEST = ROOT / "data" / "logos.json"
MAX_BYTES = 2_000_000  # logos are tiny; anything bigger is not a logo


def _ext(data: bytes) -> str | None:
    """Sniff the image type from magic bytes (CDN URLs often lack one)."""
    if data.startswith(b"\x89PNG"):
        return ".png"
    if data.startswith(b"\xff\xd8"):
        return ".jpg"
    if data.startswith(b"GIF8"):
        return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (nfl-logo-sync)"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read(MAX_BYTES)


def _load_manifest(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def sync_logos(logos: dict, *, fetch=_fetch, delay: float = 0.5,
               manifest_path: Path = MANIFEST, logo_dir: Path = LOGO_DIR) -> dict:
    """Download new/changed logos; return the updated manifest.

    Fail-soft per team: a bad URL or non-image response is a warning, never
    an exception — logos are decorative and must not break the report.
    """
    manifest = _load_manifest(manifest_path)
    logo_dir.mkdir(parents=True, exist_ok=True)
    for name, entry in logos.items():
        if not isinstance(entry, dict):
            continue
        url = str(entry.get("url") or "")
        tid = str(entry.get("id") or "")
        if not url or not tid.isalnum():
            continue
        prev = manifest.get(name) or {}
        prev_file = str(prev.get("file") or "")
        if prev.get("url") == url and prev_file and (logo_dir / prev_file).is_file():
            continue  # cached: same URL, file present
        try:
            data = fetch(url)
        except Exception as exc:  # noqa: BLE001 - decorative, fail-soft
            print(f"warning: logo for {name!r} not fetched: {exc}", file=sys.stderr)
            continue
        ext = _ext(data)
        if ext is None:
            print(f"warning: logo for {name!r} is not a recognized image; skipped",
                  file=sys.stderr)
            continue
        fname = f"{tid}{ext}"
        tmp = logo_dir / (fname + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(logo_dir / fname)
        manifest[name] = {"id": tid, "url": url, "file": fname,
                          "fetched_at": datetime.now(timezone.utc).isoformat()}
        if delay:
            time.sleep(delay)  # pace even CDN downloads; be a polite client
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = manifest_path.with_name(manifest_path.name + ".tmp")
    tmp.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(manifest_path)
    return manifest


def main() -> int:
    from yahoo.cdp import CdpClient  # noqa: E402
    from yahoo.league import BASE, LEAGUE_HOME, team_logos  # noqa: E402
    from yahoo.team import TEAM_URL, find_team_target, is_team_url  # noqa: E402

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="http://127.0.0.1:9222")
    args = parser.parse_args()
    target = find_team_target(args.endpoint)
    with CdpClient(target, args.endpoint, timeout=25) as client:
        client.navigate(f"{BASE}{LEAGUE_HOME}",
                        lambda url: url.rstrip("/").endswith(LEAGUE_HOME), 25)
        time.sleep(2)
        logos = team_logos(client)
        client.navigate(TEAM_URL, is_team_url, 25)
    manifest = sync_logos(logos)
    print(json.dumps({"teams_with_logos": len(manifest)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
