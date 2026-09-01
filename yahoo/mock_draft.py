"""Yahoo ten-team mock-lobby and current draft-client workflows.

This module is intentionally mock-only.  It rejects the configured real league
and requires eight-digit Yahoo mock room identifiers before any mutation.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .cdp import CdpClient, CdpError, Target, list_targets

REAL_LEAGUE_ID = "1329011"
ROOM_RE = re.compile(r"^\d{8}$")
STATUS_RE = re.compile(r"Round\s+(\d+)\s*,\s*Pick\s+(\d+)", re.I)


@dataclass(frozen=True)
class MockRoom:
    """One mock-lobby room and its currently open draft slots."""

    room: str
    teams: int
    description: str
    slots: tuple[int, ...]

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {"room": self.room, "teams": self.teams, "description": self.description, "slots": list(self.slots)}


@dataclass(frozen=True)
class PlayerRow:
    """A uniquely selectable player row in Yahoo's current draft client."""

    id: str
    name: str
    team: str
    pos: str
    injury: str
    xrank: float
    adp: float
    text: str

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> "PlayerRow":
        """Validate a JavaScript row payload."""
        return cls(
            id=str(row["id"]),
            name=str(row["name"]),
            team=str(row["team"]).upper(),
            pos="DEF" if str(row["pos"]).upper() == "DST" else str(row["pos"]).upper(),
            injury=str(row.get("injury", "")).upper(),
            xrank=float(row["xrank"]),
            adp=float(row["adp"]),
            text=str(row["text"]),
        )


@dataclass(frozen=True)
class DraftState:
    """Authoritative state visible in the current Yahoo draft client."""

    status: str
    round: int | None
    pick: int | None
    my_turn: bool
    team_count: int
    total_roster: int
    complete: bool
    forced_autodraft: bool
    autodraft_checked: bool
    rows: tuple[PlayerRow, ...]


@dataclass(frozen=True)
class Pick:
    """One mock selection confirmed by an authoritative roster-count change."""

    round: int
    pick: int
    player: PlayerRow

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable audit record."""
        return {
            "round": self.round,
            "pick": self.pick,
            "id": self.player.id,
            "name": self.player.name,
            "team": self.player.team,
            "pos": self.player.pos,
            "xrank": self.player.xrank,
            "adp": self.player.adp,
        }


def _validate_mock_room(room: str) -> None:
    if room == REAL_LEAGUE_ID or not ROOM_RE.fullmatch(room):
        raise ValueError("mock room must be an eight-digit Yahoo mock ID, never the real league ID")


def find_mock_draft_target(room: str, endpoint: str = "http://127.0.0.1:9222") -> Target:
    """Find exactly one current draft-client target for a mock room."""
    _validate_mock_room(room)
    matches = [
        target
        for target in list_targets(endpoint)
        if target.type == "page" and f"/draftclient/f1/{room}/" in target.url
    ]
    if len(matches) != 1:
        raise CdpError(f"expected exactly one draft target for mock room {room}, found {len(matches)}")
    return matches[0]


class MockLobby:
    """Read and join exact rooms from Yahoo's authenticated mock lobby."""

    def __init__(self, client: CdpClient, endpoint: str = "http://127.0.0.1:9222"):
        self.client = client
        self.endpoint = endpoint

    def rooms(self, teams: int | None = None) -> list[MockRoom]:
        """Read available rooms, preserving every open slot."""
        payload = self.client.evaluate(
            r'''(() => {
              const clean = value => (value || '').replace(/\s+/g, ' ').trim();
              const grouped = {};
              for (const link of document.querySelectorAll('a[href*="mock_join"]')) {
                const url = new URL(link.href, location.href);
                const room = url.searchParams.get('mlid');
                const slot = Number(url.searchParams.get('slot'));
                const row = link.closest('tr') || link.closest('li') || link.parentElement;
                if (!room || !slot || !row) continue;
                const text = clean(row.innerText);
                const count = Number((text.match(/(\d+)\s*Teams?/i) || [])[1]);
                if (!grouped[room]) grouped[room] = {room, teams: count, description: text, slots: []};
                grouped[room].slots.push(slot);
              }
              return Object.values(grouped);
            })()'''
        )
        rooms = [
            MockRoom(
                room=str(row["room"]),
                teams=int(row.get("teams") or 0),
                description=str(row.get("description", "")),
                slots=tuple(sorted({int(slot) for slot in row.get("slots", [])})),
            )
            for row in (payload or [])
        ]
        return [room for room in rooms if teams is None or room.teams == teams]

    def join(self, room: str, slot: int, timeout: float = 15) -> Target:
        """Join one exact room/slot and verify the waiting/draft target appears."""
        _validate_mock_room(room)
        if not 1 <= slot <= 10:
            raise ValueError("mock slot must be between 1 and 10")
        available = next((candidate for candidate in self.rooms(teams=10) if candidate.room == room), None)
        if available is None or slot not in available.slots:
            raise CdpError("exact ten-team mock room and slot are no longer available")
        result = self.client.evaluate(
            f'''(() => {{
              const link = [...document.querySelectorAll('a[href*="mock_join"]')].find(item => {{
                const url = new URL(item.href, location.href);
                return url.searchParams.get('mlid') === {json.dumps(room)} &&
                       url.searchParams.get('slot') === {json.dumps(str(slot))};
              }});
              if (!link) return false;
              location.assign(link.href);
              return true;
            }})()'''
        )
        if result is not True:
            raise CdpError("mock join navigation was not submitted")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            matches = [
                target
                for target in list_targets(self.endpoint)
                if target.type == "page"
                and (
                    f"mock_waiting?mlid={room}" in target.url
                    or f"/draftclient/f1/{room}/{slot}" in target.url
                )
            ]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                raise CdpError("mock join produced ambiguous Yahoo targets")
            time.sleep(0.2)
        raise CdpError("Yahoo did not confirm the requested mock room and slot")


class MockDraftPage:
    """Current Yahoo draft-client parser and identity-safe submitter."""

    def __init__(self, client: CdpClient, room: str):
        _validate_mock_room(room)
        if f"/draftclient/f1/{room}/" not in client.target.url:
            raise CdpError("connected target is not the requested Yahoo mock draft")
        self.client = client
        self.room = room

    def read_state(self) -> DraftState:
        """Read turn, roster count, autodraft state, and selectable rows."""
        payload = self.client.evaluate(
            r'''(() => {
              const clean = value => (value || '').replace(/\s+/g, ' ').trim();
              const statuses = [...document.querySelectorAll('span,div')]
                .map(element => clean(element.innerText))
                .filter(text => /Round\s+\d+\s*,\s*Pick\s+\d+/i.test(text))
                .sort((left, right) => left.length - right.length);
              const status = statuses[0] || '';
              const rows = [];
              for (const player of document.querySelectorAll('.ys-player[data-id]')) {
                const row = player.closest('tr');
                if (!row) continue;
                const buttons = [...row.querySelectorAll('button')]
                  .filter(button => /^Draft$/i.test(clean(button.innerText)) && !button.disabled);
                if (buttons.length !== 1) continue;
                const text = clean(row.innerText).replace(/^Draft\s+/i, '');
                const match = text.match(/^(.*?)\s+(?:(Q|D|O|IR|PUP|SUSP|NA|CEL)\s+)?(QB|RB|WR|TE|K|DEF|DST)\s+([A-Za-z]{2,4})\s+Bye\s+\d+\s+(\d+)\s+([\d.]+)/i);
                if (!match) continue;
                rows.push({id: player.dataset.id, name: match[1], injury: match[2] || '',
                  pos: match[3], team: match[4], xrank: Number(match[5]),
                  adp: Number(match[6]), text});
              }
              const body = clean(document.body?.innerText);
              const team = body.match(/YOUR TEAM\s*\((\d+)\/(\d+)\)/i);
              const auto = [...document.querySelectorAll('button')]
                .find(button => clean(button.innerText) === 'Autodraft');
              return {status, rows, teamCount: Number(team?.[1] || 0),
                totalRoster: Number(team?.[2] || 15),
                complete: /DRAFT COMPLETE/i.test(body) || Number(team?.[1] || 0) === 15,
                forcedAutodraft: /put into autopick mode due to inactivity/i.test(body),
                autodraftChecked: !!auto?.querySelector('svg[data-icon="checkmark-default"]')};
            })()'''
        )
        if not isinstance(payload, dict):
            raise CdpError("draft state did not return an object")
        match = STATUS_RE.search(str(payload.get("status", "")))
        return DraftState(
            status=str(payload.get("status", "")),
            round=int(match.group(1)) if match else None,
            pick=int(match.group(2)) if match else None,
            my_turn=str(payload.get("status", "")).upper().startswith("YOUR TURN"),
            team_count=int(payload.get("teamCount", 0)),
            total_roster=int(payload.get("totalRoster", 15)),
            complete=bool(payload.get("complete")),
            forced_autodraft=bool(payload.get("forcedAutodraft")),
            autodraft_checked=bool(payload.get("autodraftChecked")),
            rows=tuple(PlayerRow.from_dict(row) for row in payload.get("rows", [])),
        )

    def disable_autodraft(self) -> None:
        """Disable Yahoo autodraft when its checked state is authoritative."""
        state = self.read_state()
        if not (state.forced_autodraft or state.autodraft_checked):
            return
        clicked = self.client.evaluate(
            r'''(() => {
              const clean = value => (value || '').replace(/\s+/g, ' ').trim();
              const button = [...document.querySelectorAll('button')]
                .find(item => clean(item.innerText) === 'Autodraft' && !item.disabled);
              if (!button) return false;
              button.click();
              return true;
            })()'''
        )
        if clicked is not True:
            raise CdpError("autodraft was active but could not be disabled")
        time.sleep(0.2)
        after = self.read_state()
        if after.autodraft_checked:
            raise CdpError("Yahoo still reports autodraft enabled")

    def submit(self, player: PlayerRow, pick: int) -> None:
        """Click exactly one identity-qualified row after rechecking the turn."""
        target = json.dumps({"id": player.id, "team": player.team, "pos": player.pos, "pick": pick})
        result = self.client.evaluate(
            r'''(target => {
              const clean = value => (value || '').replace(/\s+/g, ' ').trim();
              const status = [...document.querySelectorAll('span,div')]
                .map(element => clean(element.innerText))
                .filter(text => /Round\s+\d+\s*,\s*Pick\s+\d+/i.test(text))
                .sort((left, right) => left.length - right.length)[0] || '';
              const current = Number((status.match(/Pick\s+(\d+)/i) || [])[1]);
              if (!/^YOUR TURN/i.test(status) || current !== target.pick)
                return {ok: false, reason: 'turn changed'};
              const players = [...document.querySelectorAll('.ys-player[data-id]')]
                .filter(player => player.dataset.id === target.id);
              if (players.length !== 1) return {ok: false, reason: 'player id count'};
              const row = players[0].closest('tr');
              const text = clean(row?.innerText).toUpperCase();
              if (!text.includes(target.team) || !new RegExp('\\b' + target.pos + '\\b', 'i').test(text))
                return {ok: false, reason: 'identity mismatch'};
              const buttons = [...row.querySelectorAll('button')]
                .filter(button => /^Draft$/i.test(clean(button.innerText)) && !button.disabled);
              if (buttons.length !== 1) return {ok: false, reason: 'draft button count'};
              buttons[0].click();
              return {ok: true};
            })(''' + target + ")"
        )
        if not isinstance(result, dict) or result.get("ok") is not True:
            reason = result.get("reason") if isinstance(result, dict) else "invalid submit response"
            raise CdpError(f"mock pick was not submitted: {reason}")


class MockDraftOperator:
    """Complete a fresh 15-round mock with board strategy and read-back checks."""

    def __init__(self, client: CdpClient, room: str, log_path: Path | None = None):
        self.page = MockDraftPage(client, room)
        self.room = room
        self.log_path = log_path
        self.board = self._load_board()

    @staticmethod
    def _load_board() -> dict[str, dict[str, Any]]:
        from driver import draft_driver as driver

        board = driver.load_original_board() or driver.static_board()
        driver.rebuild_abbrev_maps(board)
        return board

    def _log(self, event: str, **fields: Any) -> None:
        record = {"time": dt.datetime.now(dt.timezone.utc).isoformat(), "event": event, **fields}
        line = json.dumps(record, sort_keys=True)
        print(line, flush=True)
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    def _choose(self, state: DraftState, roster: Counter[str]) -> PlayerRow:
        from driver import draft_driver as driver

        healthy = [row for row in state.rows if row.injury not in {"O", "IR", "PUP", "CEL"}]
        raw = [[row.name, row.team, row.pos, row.text] for row in healthy]
        names, adp, positions = driver.normalize_available(raw, {
            value["team"].upper(): value["name"]
            for value in self.board.values()
            if value["pos"] == "DEF"
        })
        if state.round is None:
            raise CdpError("Yahoo did not expose the current draft round")
        choice = driver.choose_pick(names, dict(roster), state.round, self.board, adp, positions)
        if choice:
            wanted_name, wanted_team, wanted_pos, _ = choice
            for row in healthy:
                normalized, _, _ = driver.normalize_available(
                    [[row.name, row.team, row.pos, row.text]],
                    {value["team"].upper(): value["name"] for value in self.board.values() if value["pos"] == "DEF"},
                )
                if normalized and normalized[0] == wanted_name and row.team.upper() == wanted_team.upper() and row.pos == wanted_pos:
                    return row
        allowed = self._fallback_positions(state.round, roster)
        candidates = [row for row in healthy if row.pos in allowed]
        if not candidates:
            raise CdpError(f"no selectable player for round {state.round} positions {allowed}")
        return min(candidates, key=lambda row: (row.xrank, row.adp, row.name))

    @staticmethod
    def _fallback_positions(round_number: int, roster: Counter[str]) -> set[str]:
        if round_number == 15:
            return {"DEF"}
        if round_number == 14:
            return {"K"}
        if round_number <= 5:
            return {"RB", "WR"}
        if round_number <= 8 and roster["TE"] == 0:
            return {"RB", "WR", "TE"}
        if roster["QB"] == 0:
            return {"QB"}
        if roster["TE"] == 0:
            return {"TE"}
        return {"RB", "WR", "TE"}

    def run(self, poll_interval: float = 0.25) -> list[Pick]:
        """Run only from a fresh mock and verify each roster-count transition."""
        self.page.client.bring_to_front()
        self.page.disable_autodraft()
        initial = self.page.read_state()
        if initial.team_count != 0 or (initial.round is not None and initial.round > 1):
            raise CdpError("mock operator requires a fresh room; refusing unsafe mid-draft reconstruction")
        picks: list[Pick] = []
        roster: Counter[str] = Counter()
        last_status = ""
        while len(picks) < 15:
            state = self.page.read_state()
            if state.status != last_status:
                self._log("status", status=state.status, team_count=state.team_count)
                last_status = state.status
            if state.team_count != len(picks):
                raise CdpError("Yahoo roster changed without a confirmed operator pick; refusing to guess")
            if not state.my_turn:
                time.sleep(poll_interval)
                continue
            if state.round != len(picks) + 1 or state.pick is None:
                raise CdpError("authoritative Yahoo round does not match confirmed roster count")
            player = self._choose(state, roster)
            self._log("decision", round=state.round, pick=state.pick, player=player.name, team=player.team, pos=player.pos)
            self.page.submit(player, state.pick)
            deadline = time.monotonic() + 10
            after = state
            while time.monotonic() < deadline:
                after = self.page.read_state()
                if after.team_count == state.team_count + 1:
                    break
                time.sleep(0.1)
            else:
                raise CdpError("pick submission outcome is uncertain; no retry was attempted")
            if any(row.id == player.id for row in after.rows):
                raise CdpError("roster count advanced but selected player remains available")
            assert state.round is not None
            confirmed = Pick(state.round, state.pick, player)
            picks.append(confirmed)
            roster[player.pos] += 1
            self._log("confirmed", count=len(picks), **confirmed.as_dict())
        final = self.page.read_state()
        if final.team_count != 15 or final.total_roster != 15 or not final.complete:
            raise CdpError("Yahoo did not authoritatively report YOUR TEAM (15/15)")
        self._log("complete", team_count=final.team_count, total=final.total_roster)
        return picks
