"""Authoritative read-only Yahoo available-player page models."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Protocol

from .cdp import CdpError
from .team import LEAGUE_ID, YAHOO_FANTASY_HOST

PLAYERS_PATH = f"/f1/{LEAGUE_ID}/players"


class PlayerReadError(CdpError):
    """An available-player page failed identity or row validation."""


class ReadClient(Protocol):
    def evaluate(self, expression: str) -> Any:
        """Evaluate JavaScript and return its value."""


@dataclass(frozen=True)
class AvailablePlayer:
    yahoo_id: str
    name: str
    team: str
    position: str
    availability: str
    injury_status: str
    game: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def _parse_payload(payload: Any) -> tuple[AvailablePlayer, ...]:
    if not isinstance(payload, dict):
        raise PlayerReadError("players page returned a non-object payload")
    identity = payload.get("identity")
    if not isinstance(identity, dict) or not all(identity.get(key) for key in ("signedIn", "origin", "league", "path")):
        raise PlayerReadError("authenticated Yahoo players-page identity check failed")
    rows = payload.get("players")
    if not isinstance(rows, list):
        raise PlayerReadError("available-player rows are missing")

    players = []
    for row in rows:
        if not isinstance(row, dict):
            raise PlayerReadError("available-player row is not an object")
        required = ("yahoo_id", "name", "team", "position", "availability")
        if not all(str(row.get(key) or "").strip() for key in required):
            raise PlayerReadError("available-player row is missing identity or availability")
        availability = str(row["availability"]).strip()
        if availability != "FA" and not re.fullmatch(r"W \([^)]+\)", availability):
            raise PlayerReadError(f"unexpected player availability: {availability}")
        players.append(AvailablePlayer(
            yahoo_id=str(row["yahoo_id"]),
            name=str(row["name"]).strip(),
            team=str(row["team"]).upper(),
            position=str(row["position"]).upper(),
            availability=availability,
            injury_status=str(row.get("injury_status") or "").upper(),
            game=str(row.get("game") or "").strip(),
        ))
    ids = [player.yahoo_id for player in players]
    if len(ids) != len(set(ids)):
        raise PlayerReadError("available-player page contains duplicate Yahoo IDs")
    return tuple(players)


class YahooPlayerReader:
    """Read one current Yahoo available-player result page without mutation."""

    def __init__(self, client: ReadClient):
        self.client = client

    def page(self) -> tuple[AvailablePlayer, ...]:
        payload = self.client.evaluate(
            rf'''(() => {{
              const body = document.body?.innerText || '';
              const players = [...document.querySelectorAll('tr')].map(row => {{
                const add = row.querySelector('a[title="Add Player"][href*="apid="]');
                const cell = row.querySelector('td.player');
                if (!add || !cell) return null;
                const link = cell.querySelector('a[href*="/playernotes?"]') || cell.querySelector('a.Nowrap');
                const text = cell.innerText || '';
                const teamPos = text.match(/\b([A-Za-z]{{2,3}})\s+-\s+(QB|RB|WR|TE|K|DEF)\b/i);
                const status = cell.querySelector('.ysf-player-status')?.innerText?.trim() || '';
                const game = cell.querySelector('.ysf-game-status a')?.innerText?.trim() || '';
                const availability = (row.innerText || '').match(/W \([^)]+\)|\bFA\b/)?.[0] || '';
                return {{
                  yahoo_id: new URL(add.href).searchParams.get('apid') || '',
                  name: link?.title || link?.innerText?.trim() || '',
                  team: teamPos?.[1] || '', position: teamPos?.[2] || '',
                  availability, injury_status: status, game,
                }};
              }}).filter(Boolean);
              return {{
                identity: {{
                  signedIn: !/Sign in to Yahoo/i.test(body),
                  origin: location.protocol === 'https:' && location.hostname === {YAHOO_FANTASY_HOST!r},
                  league: /FD nation|ID#\s*{LEAGUE_ID}/i.test(body),
                  path: location.pathname.replace(/\/$/, '') === {PLAYERS_PATH!r},
                }}, players,
              }};
            }})()'''
        )
        return _parse_payload(payload)
