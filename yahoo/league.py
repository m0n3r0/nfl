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


@dataclass(frozen=True)
class ScoreboardEntry:
    """One league matchup from the league-home scoreboard section."""
    week: int
    team1: str
    team1_id: str
    score1: float
    proj1: float
    team2: str
    team2_id: str
    score2: float
    proj2: float

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
                # Yahoo renders thousands with commas once PF/PA cross 1,000
                points_for=float(re.sub(r"[,\s]", "", cells[columns["PF"]]) or 0),
                points_against=float(re.sub(r"[,\s]", "", cells[columns["PA"]]) or 0),
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


def team_ids(client: LeagueClient) -> dict[str, str]:
    """Map league team names to Yahoo roster numbers.

    Evaluates on the league home page — call it right after standings()
    (which navigates there), so this costs no extra request. Fails closed
    when the browser is anywhere else, like the sibling readers.
    """
    payload = client.evaluate(
        r'''/* yahoo-league-team-ids */ (() => {
          const out = {};
          document.querySelectorAll('table a[href*="%s"]').forEach(a => {
            const m = (a.getAttribute('href') || '').match(/\/f1\/\d+\/(\d+)([/?#]|$)/);
            const name = (a.innerText || '').trim();
            if (m && name && !(name in out)) out[name] = m[1];
          });
          return {path: location.pathname.replace(/\/$/, ''), ids: out};
        })()''' % LEAGUE_HOME
    )
    if not isinstance(payload, dict) or payload.get("path") != LEAGUE_HOME:
        raise LeagueReadError("not on the league home page")
    ids = payload.get("ids")
    if not isinstance(ids, dict) or not ids:
        raise LeagueReadError("no team links found on the league home page")
    return ids


def _parse_scoreboard_entries(entries: Any) -> tuple[ScoreboardEntry, ...]:
    """Turn the league-home JS payload into ScoreboardEntries (pure; testable).

    An entry qualifies on identity alone (matchup link + two named teams);
    the four floats around "vs" (score/proj per side) degrade to 0.0 — the
    pre-game page can render without them, and a scoreless entry still tells
    the web UI who plays whom.
    """
    if not isinstance(entries, list):
        raise LeagueReadError("scoreboard payload is missing")
    out = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        ids = entry.get("ids")
        names = entry.get("names")
        if (not isinstance(ids, list) or len(ids) != 2
                or not isinstance(names, list) or len(names) != 2
                or not entry.get("week")):
            continue
        nums = entry.get("nums")
        try:
            vals = ([float(n) for n in nums]
                    if isinstance(nums, list) and len(nums) == 4 else None)
            score1, proj1, score2, proj2 = vals if vals else (0.0, 0.0, 0.0, 0.0)
            out.append(ScoreboardEntry(
                week=int(entry["week"]),
                team1=str(names[0]), team1_id=str(ids[0]),
                score1=score1, proj1=proj1,
                team2=str(names[1]), team2_id=str(ids[1]),
                score2=score2, proj2=proj2,
            ))
        except (TypeError, ValueError):
            continue  # one mangled entry must not kill the rest (standings idiom)
    if not out:
        raise LeagueReadError("no parseable scoreboard entries")
    return tuple(out)


def scoreboard(client: LeagueClient) -> tuple[ScoreboardEntry, ...]:
    """Read every matchup of the current week from the league-home scoreboard.

    Evaluates on the league home page — call it right after standings()
    (which navigates there), so a full league overview costs no extra
    request. Fails closed when the browser is anywhere else, like the
    sibling readers.
    """
    payload = client.evaluate(
        r'''/* yahoo-league-scoreboard */ (() => {
          const ul = [...document.querySelectorAll('ul')].find(el =>
            (el.innerText || '').length < 2000 &&
            el.querySelector('a[href*="%s/matchup?"]'));
          const entries = ul ? [...ul.children].map(li => {
            const links = [...li.querySelectorAll('a[href]')];
            const mu = links.map(a => a.getAttribute('href') || '')
              .map(h => h.match(/\/f1\/\d+\/matchup\?week=(\d+)&mid1=(\d+)&mid2=(\d+)/))
              .find(Boolean);
            // (id, name) pairs per anchor, deduped by id, in DOM order — the
            // same order the nums regex reads scores in, so name↔score
            // alignment is structural; the matchup link is needed only for
            // the week (duplicate team names survive via distinct ids).
            const seen = {};
            const teams = [];
            links.forEach(a => {
              const m = (a.getAttribute('href') || '').match(/\/f1\/\d+\/(\d+)\/?$/);
              const t = (a.innerText || '').trim();
              if (m && t && !seen[m[1]]) { seen[m[1]] = 1; teams.push({id: m[1], name: t}); }
            });
            const two = teams.slice(0, 2);
            const m = (li.innerText || '').match(
              /(\d+\.\d+)\s*\n\s*(\d+\.\d+)\s*\n\s*\t?\s*vs\.?\s*\t?\s*\n\s*(\d+\.\d+)\s*\n\s*(\d+\.\d+)/);
            return {week: mu && mu[1], ids: two.map(t => t.id),
                    names: two.map(t => t.name),
                    nums: m && [m[1], m[2], m[3], m[4]].map(parseFloat)};
          }) : [];
          return {path: location.pathname.replace(/\/$/, ''), entries};
        })()''' % LEAGUE_HOME
    )
    if not isinstance(payload, dict) or payload.get("path") != LEAGUE_HOME:
        raise LeagueReadError("not on the league home page")
    return _parse_scoreboard_entries(payload.get("entries"))


def _build_matchup_score(payload: Any) -> MatchupScore:
    """Turn the matchup-page JS payload into a MatchupScore (pure; testable).

    The pre-game page shows "NN.N Live Proj NN.N" (team, opponent); the
    live-game page relabels to "Orig Proj" and orders the pair
    (opponent, team). Scores are mandatory — a missing pair means the page
    did not render (raise), projections degrade to 0.0.
    """
    if not isinstance(payload, dict) or not payload.get("week"):
        raise LeagueReadError("matchup page did not parse")
    if not payload.get("score"):
        raise LeagueReadError("matchup scores are missing")
    names = payload.get("names") or ["", ""]
    live, orig = payload.get("live"), payload.get("orig")
    if live:
        team_proj, opponent_proj = float(live[0]), float(live[1])
    elif orig:
        team_proj, opponent_proj = float(orig[1]), float(orig[0])
    else:
        team_proj = opponent_proj = 0.0
    return MatchupScore(
        week=int(payload["week"]),
        team=names[0],
        score=float(payload["score"][0]),
        opponent=names[1] if len(names) > 1 else "",
        opponent_score=float(payload["score"][1]),
        team_proj=team_proj,
        opponent_proj=opponent_proj,
    )


def matchup(client: LeagueClient, timeout: float = 30) -> MatchupScore:
    """Read the current matchup scoreboard (live during the week).

    Attribution follows Yahoo's header order: our team block precedes the
    score line, the opponent block follows it. The score line renders as
    "vs" pre-game and "vs." during live games.
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
          const score = body.match(/(\d+\.\d+)\s*\n\s*vs\.?\s*\n\s*(\d+\.\d+)/);
          const live = body.match(/(\d+\.\d+)\s*\t?\s*Live\s+Proj\s*\t?\s*(\d+\.\d+)/);
          const orig = body.match(/Orig\s+Proj\s*\n\s*(\d+\.\d+)\s*\n\s*(\d+\.\d+)/);
          return {week, names: names.slice(0, 2),
                  score: score && [parseFloat(score[1]), parseFloat(score[2])],
                  live: live && [parseFloat(live[1]), parseFloat(live[2])],
                  orig: orig && [parseFloat(orig[1]), parseFloat(orig[2])]};
        })()'''
    )
    return _build_matchup_score(payload)


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
