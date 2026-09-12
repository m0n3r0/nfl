"""Available-player wire scan: paginate Yahoo players pages and rank by projection.

Read-only. Shared by tools/waiver_targets.py and the team operator so the wire
scan logic lives in one place.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Protocol
from urllib.parse import urlencode, urlparse

import pandas as pd

from .identity import YahooPlayerIdentity, reconcile_identities
from .players import AvailablePlayer, PlayerReadError, YahooPlayerReader
from .team import LEAGUE_ID

BASE = "https://football.fantasysports.yahoo.com"
PLAYERS_PATH = f"/f1/{LEAGUE_ID}/players"
POSITIONS = ("QB", "RB", "WR", "TE")


class WireClient(Protocol):
    def evaluate(self, expression: str) -> Any: ...
    def navigate(self, url: str, expected: Callable[[str], bool], timeout: float = 20) -> str: ...


class WireScanBlocked(PlayerReadError):
    """Yahoo is serving its 'Request denied' WAF page; abort immediately."""


def _denied(client: WireClient) -> bool:
    try:
        return bool(client.evaluate(
            "!!document.body && /Request denied/i.test(document.body.innerText)"))
    except Exception:
        return False


def scan_available(client: WireClient, week: int, positions: tuple[str, ...] = POSITIONS,
                   max_pages: int = 4, pause: float = 2.0) -> dict[str, AvailablePlayer]:
    """Paginate the available-player lists; return yahoo_id -> AvailablePlayer.

    Navigates only (never clicks). Pages are sorted by projected points, so
    the best targets sit on the first pages — the default 4 pages per position
    keeps coverage of every plausible add while staying polite with Yahoo's
    WAF (a full 12-page sweep tripped a 'Request denied' block on 2026-09-13).
    A denial page aborts the whole scan instantly instead of hammering on.
    """
    available: dict[str, AvailablePlayer] = {}
    reader = YahooPlayerReader(client)
    for position in positions:
        for count in range(0, max_pages * 25, 25):
            query = urlencode({"status": "A", "pos": position, "cut_type": "33",
                               "stat1": f"S_PW_{week}", "count": count})
            client.navigate(f"{BASE}{PLAYERS_PATH}?{query}",
                            lambda url: urlparse(url).path == PLAYERS_PATH, 30)
            time.sleep(pause)  # pace every page; the WAF watches bursts
            # The SPA renders asynchronously after the URL matches: retry the
            # parse until the players page has actually rendered (identity +
            # rows), not just changed location. Still fail-closed: a page that
            # never renders raises after the deadline.
            deadline = time.monotonic() + 10
            while True:
                try:
                    page = reader.page()
                    if page or count > 0 or time.monotonic() > deadline:
                        break
                    time.sleep(pause)  # first page: empty may mean rows not rendered yet
                except PlayerReadError:
                    if _denied(client):
                        raise WireScanBlocked(
                            "Yahoo served 'Request denied'; aborting the scan") from None
                    if time.monotonic() > deadline:
                        raise
                    time.sleep(pause)
            if not page:
                break
            for player in page:
                available.setdefault(player.yahoo_id, player)
            if len(page) < 25:
                break
    return available


def rank_targets(available: dict[str, AvailablePlayer], projections: pd.DataFrame) -> tuple[list[dict], dict[str, int]]:
    """Rank available players by proj_week via identity reconciliation.

    Unmapped, ambiguous, and team-mismatched players are counted and dropped —
    never guessed (nflverse team assignments lag trades).
    """
    mappings = reconcile_identities(
        [YahooPlayerIdentity(p.yahoo_id, p.name, p.team, p.position) for p in available.values()],
        projections,
    )
    proj_week = projections.set_index("player_id")["proj_week"].to_dict()
    ranked: list[dict] = []
    skipped: dict[str, int] = {}
    for mapping in mappings:
        player = available[mapping.yahoo_id]
        if not mapping.actionable:
            skipped[mapping.status] = skipped.get(mapping.status, 0) + 1
            continue
        ranked.append({
            "yahoo_id": player.yahoo_id, "name": player.name, "team": player.team,
            "position": player.position, "availability": player.availability,
            "injury_status": player.injury_status,
            "proj_week": round(float(proj_week[mapping.internal_id]), 2),
        })
    ranked.sort(key=lambda row: row["proj_week"], reverse=True)
    return ranked, skipped
