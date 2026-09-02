#!/usr/bin/env python3
"""Build a read-only Yahoo-ID/internal-ID reconciliation report."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlencode, urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import corpus, projections
from src.config import league_preset
from yahoo.cdp import CdpClient
from yahoo.identity import YahooPlayerIdentity, reconcile_identities, write_identity_map
from yahoo.players import YahooPlayerReader
from yahoo.team import TEAM_PATH, YahooTeamReader, find_team_target

BASE = "https://football.fantasysports.yahoo.com"
POSITIONS = ("QB", "RB", "WR", "TE")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="http://127.0.0.1:9222")
    parser.add_argument("--output", default="logs/yahoo-player-map.json")
    args = parser.parse_args()

    identities: dict[str, YahooPlayerIdentity] = {}
    with CdpClient(find_team_target(args.endpoint), endpoint=args.endpoint, timeout=20) as client:
        snapshot = YahooTeamReader(client).snapshot()
        for player in snapshot.roster:
            identities[player.yahoo_id] = YahooPlayerIdentity(player.yahoo_id, player.name, player.team, player.position)
        try:
            for position in POSITIONS:
                for count in range(0, 500, 25):
                    query = urlencode({"status": "A", "pos": position, "cut_type": "33", "stat1": f"S_PW_{snapshot.week}", "count": count})
                    client.navigate(f"{BASE}/f1/1329011/players?{query}", lambda url: urlparse(url).path == "/f1/1329011/players", 30)
                    time.sleep(0.5)
                    page = YahooPlayerReader(client).page()
                    if not page:
                        break
                    new_ids = 0
                    for player in page:
                        if player.yahoo_id not in identities:
                            new_ids += 1
                        identities[player.yahoo_id] = YahooPlayerIdentity(player.yahoo_id, player.name, player.team, player.position)
                    if len(page) < 25 or new_ids == 0:
                        break
        finally:
            client.navigate(f"{BASE}{TEAM_PATH}", lambda url: urlparse(url).path.rstrip("/") == TEAM_PATH, 30)

    model = projections.project_players(corpus.build(preset=league_preset()))
    mappings = reconcile_identities(identities.values(), model)
    write_identity_map(args.output, mappings)
    counts: dict[str, int] = {}
    for mapping in mappings:
        counts[mapping.status] = counts.get(mapping.status, 0) + 1
    print(json.dumps({"output": str(Path(args.output).resolve()), "total": len(mappings), "statuses": counts}, indent=2, sort_keys=True))
    return 0 if counts.get("ambiguous", 0) == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
