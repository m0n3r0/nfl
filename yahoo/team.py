"""Read-only authoritative Yahoo team state for FD nation.

This module deliberately exposes no mutations. It reads the authenticated team
page through loopback CDP and validates league, team, and player identities
before returning a snapshot.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any, Protocol
from urllib.parse import urlparse

from .cdp import CdpError, Target, select_target

LEAGUE_ID = "1329011"
TEAM_ID = "2"
TEAM_PATH = f"/f1/{LEAGUE_ID}/{TEAM_ID}"
EXPECTED_ACTIVE_SLOTS = Counter({"QB": 1, "RB": 2, "WR": 2, "TE": 1, "W/R/T": 1, "K": 1, "DEF": 1, "BN": 6})
INJURED_RESERVE_SLOTS = {"IR", "IL"}


class TeamReadError(CdpError):
    """The team page did not satisfy a read-only identity or roster invariant."""


class ReadClient(Protocol):
    """Minimal CDP surface needed by the read-only team reader."""

    def evaluate(self, expression: str) -> Any:
        """Evaluate a JavaScript expression and return its value."""


@dataclass(frozen=True)
class RosterPlayer:
    """One Yahoo roster row keyed by Yahoo's player ID."""

    yahoo_id: str
    name: str
    team: str
    position: str
    slot: str
    injury_status: str
    game: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class TeamSnapshot:
    """Validated current state of the authorized fantasy team."""

    league_id: str
    team_id: str
    team_name: str
    record: str
    week: int
    opponent: str
    waiver_priority: int
    roster: tuple[RosterPlayer, ...]

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["roster"] = [player.as_dict() for player in self.roster]
        return value


def find_team_target(endpoint: str = "http://127.0.0.1:9222") -> Target:
    """Return exactly one browser tab on the authorized team route."""
    return select_target(
        lambda target: urlparse(target.url).path.rstrip("/") == TEAM_PATH,
        endpoint,
    )


def _parse_payload(payload: Any) -> TeamSnapshot:
    if not isinstance(payload, dict):
        raise TeamReadError("team page returned a non-object snapshot")
    identity = payload.get("identity")
    if not isinstance(identity, dict) or not all(identity.get(key) for key in ("signedIn", "league", "team", "path")):
        raise TeamReadError("authenticated FD nation/team identity check failed")

    rows = payload.get("roster")
    if not isinstance(rows, list):
        raise TeamReadError("team roster payload is missing")
    roster = []
    for row in rows:
        if not isinstance(row, dict):
            raise TeamReadError("team roster contains a non-object row")
        required = ("yahoo_id", "name", "team", "position", "slot")
        if not all(str(row.get(key) or "").strip() for key in required):
            raise TeamReadError("team roster row is missing identity or slot data")
        roster.append(RosterPlayer(
            yahoo_id=str(row["yahoo_id"]),
            name=str(row["name"]).strip(),
            team=str(row["team"]).upper(),
            position=str(row["position"]).upper(),
            slot=str(row["slot"]).upper(),
            injury_status=str(row.get("injury_status") or "").upper(),
            game=str(row.get("game") or "").strip(),
        ))
    if not 15 <= len(roster) <= 17:
        raise TeamReadError(f"expected 15-17 roster players including IR, found {len(roster)}")
    ids = [player.yahoo_id for player in roster]
    if len(ids) != len(set(ids)):
        raise TeamReadError("team roster contains duplicate Yahoo player IDs")
    slots = Counter(player.slot for player in roster)
    injured_reserve = sum(slots.pop(slot, 0) for slot in INJURED_RESERVE_SLOTS)
    if slots != EXPECTED_ACTIVE_SLOTS or injured_reserve > 2:
        raise TeamReadError(f"unexpected lineup slots: {dict(slots)}")

    summary = payload.get("summary")
    if not isinstance(summary, dict):
        raise TeamReadError("team summary payload is missing")
    record = str(summary.get("record") or "")
    matchup = str(summary.get("matchup") or "")
    waiver = str(summary.get("waiver") or "")
    week_match = re.search(r"Week\s+(\d+)\s+vs\s+(.+)", matchup, re.I)
    waiver_match = re.search(r"(\d+)(?:st|nd|rd|th)", waiver, re.I)
    if not re.fullmatch(r"\d+-\d+-\d+", record) or not week_match or not waiver_match:
        raise TeamReadError("team record, matchup, or waiver priority could not be parsed")

    return TeamSnapshot(
        league_id=LEAGUE_ID,
        team_id=TEAM_ID,
        team_name=str(summary.get("team_name") or "").strip(),
        record=record,
        week=int(week_match.group(1)),
        opponent=week_match.group(2).strip(),
        waiver_priority=int(waiver_match.group(1)),
        roster=tuple(roster),
    )


class YahooTeamReader:
    """Read the exact authorized team page without modifying Yahoo state."""

    def __init__(self, client: ReadClient):
        self.client = client

    def snapshot(self) -> TeamSnapshot:
        payload = self.client.evaluate(
            r'''(() => {
              const path = location.pathname.replace(/\/$/, '');
              const body = document.body?.innerText || '';
              const roster = [...document.querySelectorAll('tr.editable')].map(row => {
                const link = row.querySelector('.ysf-player-name a[data-ys-playerid]');
                const playerCell = row.querySelector('td.player');
                const playerText = playerCell?.innerText || '';
                const teamPos = playerText.match(/\b([A-Za-z]{2,3})\s+-\s+(QB|RB|WR|TE|K|DEF)\b/i);
                const select = row.querySelector('select');
                const slot = select?.selectedOptions?.[0]?.value || row.querySelector('.pos-label')?.dataset?.pos || '';
                const status = row.querySelector('.ysf-player-status')?.innerText?.trim() || '';
                const game = row.querySelector('.ysf-game-status a')?.innerText?.trim() || '';
                return {
                  yahoo_id: link?.dataset?.ysPlayerid || select?.name || '',
                  name: link?.title || link?.innerText?.trim() || '',
                  team: teamPos?.[1] || '', position: teamPos?.[2] || '',
                  slot, injury_status: status, game,
                };
              }).filter(row => row.yahoo_id || row.name);
              const matchup = body.match(/Week\s+\d+\s+vs\s+[^\n]+/i)?.[0] || '';
              const record = body.match(/\b\d+-\d+-\d+\b/)?.[0] || '';
              const waiver = body.match(/Waiver Priority:\s*\d+(?:st|nd|rd|th)/i)?.[0] || '';
              return {
                identity: {
                  signedIn: !/Sign in to Yahoo/i.test(body),
                  league: /FD nation|ID#\s*1329011/i.test(body),
                  team: /Shiba Innu/i.test(body), path: path === '/f1/1329011/2',
                },
                summary: {team_name: 'Shiba Innu', record, matchup, waiver}, roster,
              };
            })()'''
        )
        return _parse_payload(payload)
