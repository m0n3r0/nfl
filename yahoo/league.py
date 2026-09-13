"""Read-only league-level Yahoo pages: standings, matchup score, opponent roster.

Runtime-only data: standings and matchup rows contain other managers' team
names, which are fine in console output and local logs but must never be
committed to this public repo (see memory/fantasy_fd_nation.md privacy note).
"""

from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable, Protocol
from urllib.parse import urlparse

from .cdp import CdpError
from .team import LEAGUE_ID, TEAM_ID
from .waf import denied as _waf_denied

BASE = "https://football.fantasysports.yahoo.com"
LEAGUE_HOME = f"/f1/{LEAGUE_ID}"
MATCHUP_PATH = f"/f1/{LEAGUE_ID}/matchup"


class LeagueReadError(CdpError):
    """A league page failed identity or parse validation."""


class LeagueWafBlocked(LeagueReadError):
    """Yahoo is serving its 'Request denied' WAF page; abort the run fast."""


def _fail_if_denied(client: "LeagueClient") -> None:
    """A WAF page parses as misleading empty payloads — name the true cause.
    A probe hiccup is not a block: proceed and let the parse validate."""
    try:
        blocked = _waf_denied(client)
    except Exception:
        blocked = False
    if blocked:
        raise LeagueWafBlocked("Yahoo served 'Request denied'; aborting the read")


class LeagueClient(Protocol):
    def evaluate(self, expression: str) -> Any: ...
    def navigate(self, url: str, expected: Callable[[str], bool], timeout: float = 20) -> str: ...


@dataclass(frozen=True)
class StandingsRow:
    rank: int
    team: str
    record: str
    points_for: float
    points_against: float
    waiver: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MatchupScore:
    week: int
    team: str
    score: float
    opponent: str
    opponent_score: float
    team_proj: float
    opponent_proj: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_standings_rows(header: Any, rows: Any) -> tuple[StandingsRow, ...]:
    if not isinstance(rows, list) or not isinstance(header, list):
        raise LeagueReadError("standings rows are missing")
    columns = {str(cell).strip(): i for i, cell in enumerate(header)}
    required = {"Team", "W-L-T", "PF", "PA", "Waiver"}
    if not required.issubset(columns):
        raise LeagueReadError(f"standings header is missing columns: {sorted(required - set(columns))}")
    out = []
    for row in rows:
        if not isinstance(row, list):
            continue
        cells = [str(cell).strip() for cell in row]
        try:
            record = cells[columns["W-L-T"]]
            team = cells[columns["Team"]]
            if not re.fullmatch(r"\d+-\d+-\d+", record) or not team:
                continue
            out.append(StandingsRow(
                rank=len(out) + 1,
                team=team,
                record=record,
                points_for=float(cells[columns["PF"]] or 0),
                points_against=float(cells[columns["PA"]] or 0),
                waiver=int(re.sub(r"\D", "", cells[columns["Waiver"]]) or "0"),
            ))
        except (IndexError, ValueError):
            continue
    if not out:
        raise LeagueReadError("no parseable standings rows")
    return tuple(out)


def standings(client: LeagueClient, timeout: float = 30) -> tuple[StandingsRow, ...]:
    """Read the league standings table from the league home page."""
    client.navigate(f"{BASE}{LEAGUE_HOME}", lambda url: url.rstrip("/").endswith(LEAGUE_HOME), timeout)
    time.sleep(2)
    _fail_if_denied(client)
    payload = client.evaluate(
        r'''/* yahoo-league-standings */ (() => {
          const table = [...document.querySelectorAll('table')].find(t => {
            const head = t.rows[0]?.innerText || '';
            return head.includes('W-L-T') && head.includes('PF');
          });
          return {
            path: location.pathname.replace(/\/$/, ''),
            header: table ? [...table.rows[0].cells].map(cell => (cell.innerText || '').trim()) : [],
            rows: table ? [...table.rows].slice(1).map(row =>
              [...row.cells].map(cell => (cell.innerText || '').trim())) : [],
          };
        })()'''
    )
    if not isinstance(payload, dict) or payload.get("path") != LEAGUE_HOME:
        raise LeagueReadError("not on the league home page")
    return _parse_standings_rows(payload.get("header"), payload.get("rows"))


def matchup(client: LeagueClient, timeout: float = 30) -> MatchupScore:
    """Read the current matchup scoreboard (live during the week).

    Attribution follows Yahoo's header order: our team block precedes the
    score line, the opponent block follows it.
    """
    client.navigate(f"{BASE}{MATCHUP_PATH}", lambda url: urlparse(url).path == MATCHUP_PATH, timeout)
    time.sleep(2)
    _fail_if_denied(client)
    payload = client.evaluate(
        r'''/* yahoo-league-matchup */ (() => {
          const body = document.body?.innerText || '';
          const week = (body.match(/Week\s+(\d+):/) || [])[1] || '';
          const names = [...new Set([...document.querySelectorAll('a[href]')]
            .filter(a => /^(?:https?:\/\/[^/]+)?\/f1\/\d+\/\d+\/?$/.test(a.getAttribute('href') || ''))
            .map(a => (a.innerText || '').trim())
            .filter(t => t && t !== 'My Team' && t.length < 40))];
          const score = body.match(/(\d+\.\d+)\s*\n\s*vs\s*\n\s*(\d+\.\d+)/);
          const live = body.match(/(\d+\.\d+)\s*\t?\s*Live\s+Proj\s*\t?\s*(\d+\.\d+)/);
          return {week, names: names.slice(0, 2),
                  score: score && [parseFloat(score[1]), parseFloat(score[2])],
                  live: live && [parseFloat(live[1]), parseFloat(live[2])]};
        })()'''
    )
    if not isinstance(payload, dict) or not payload.get("week"):
        raise LeagueReadError("matchup page did not parse")
    if not payload.get("score"):
        raise LeagueReadError("matchup scores are missing")
    names = payload.get("names") or ["", ""]
    live = payload.get("live") or [0.0, 0.0]
    return MatchupScore(
        week=int(payload["week"]),
        team=names[0],
        score=float(payload["score"][0]),
        opponent=names[1] if len(names) > 1 else "",
        opponent_score=float(payload["score"][1]),
        team_proj=float(live[0]),
        opponent_proj=float(live[1]),
    )


def opponent_roster(client: LeagueClient, team_id: str, timeout: float = 30) -> tuple[dict[str, str], ...]:
    """Read another team's roster (read-only). team_id is the Yahoo roster number."""
    if team_id == TEAM_ID:
        raise LeagueReadError("use YahooTeamReader for the authorized team")
    path = f"/f1/{LEAGUE_ID}/{team_id}"
    client.navigate(f"{BASE}{path}", lambda url: urlparse(url).path.rstrip("/") == path, timeout)
    time.sleep(2)
    _fail_if_denied(client)
    payload = client.evaluate(
        r'''/* yahoo-league-opponent-roster */ (() => {
          const rows = [...document.querySelectorAll('tr')].filter(r => r.querySelector('.ysf-player-name')).map(row => {
            const link = row.querySelector('.ysf-player-name a');
            const cell = row.querySelector('td.player');
            const teamPos = (cell?.innerText || '').match(/\b([A-Za-z]{2,3})\s+-\s+(QB|RB|WR|TE|K|DEF)\b/i);
            const slot = row.querySelector('td')?.innerText?.trim() || '';
            const status = row.querySelector('.ysf-player-status')?.innerText?.trim() || '';
            return {name: link?.title || link?.innerText?.trim() || '',
                    team: teamPos?.[1] || '', position: teamPos?.[2] || '',
                    slot, injury_status: status};
          });
          return {path: location.pathname.replace(/\/$/, ''), rows};
        })()'''
    )
    if not isinstance(payload, dict) or payload.get("path") != path:
        raise LeagueReadError("opponent team page did not load")
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        raise LeagueReadError("opponent roster rows are missing")
    return tuple(
        {k: str(v) for k, v in row.items()}
        for row in rows
        if isinstance(row, dict) and row.get("name")
    )


def opponent_team_id(client: LeagueClient, timeout: float = 30) -> str:
    """Return the current matchup opponent's Yahoo team id (from matchup page links)."""
    client.navigate(f"{BASE}{MATCHUP_PATH}", lambda url: urlparse(url).path == MATCHUP_PATH, timeout)
    time.sleep(2)
    _fail_if_denied(client)
    payload = client.evaluate(
        r'''/* yahoo-league-opponent-id */ (() => {
          const ids = [...document.querySelectorAll('a[href]')]
            .map(a => (a.getAttribute('href') || '').match(/^(?:https?:\/\/[^/]+)?\/f1\/\d+\/(\d+)\/?$/))
            .filter(Boolean).map(m => m[1]);
          return [...new Set(ids)];
        })()'''
    )
    ids = [str(i) for i in payload or [] if str(i) != TEAM_ID]
    if len(ids) != 1:
        raise LeagueReadError(f"could not isolate opponent team id: {ids}")
    return ids[0]
