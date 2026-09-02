"""Fail-closed Yahoo lineup changes with exact-ID preconditions and read-back.

Only starter/bench slot changes are supported. Transactions, adds, drops, and
waiver claims are intentionally outside this module.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any, Callable, Protocol
from urllib.parse import urlparse
from .cdp import CdpError
from .team import EXPECTED_ACTIVE_SLOTS, INJURED_RESERVE_SLOTS, TEAM_PATH, TeamSnapshot, YahooTeamReader

TEAM_URL = f"https://football.fantasysports.yahoo.com{TEAM_PATH}"


class LineupError(CdpError):
    """A lineup mutation failed a precondition or authoritative read-back."""


class LineupClient(Protocol):
    def evaluate(self, expression: str) -> Any:
        """Evaluate JavaScript in the authorized team target."""

    def navigate(self, url: str, expected: Callable[[str], bool], timeout: float = 20) -> str:
        """Navigate to the canonical team page after a form response."""
        ...


@dataclass(frozen=True)
class LineupMove:
    """Move one exact Yahoo player ID from an expected slot to a target slot."""

    yahoo_id: str
    from_slot: str
    to_slot: str


@dataclass(frozen=True)
class LineupReceipt:
    """Verified result of a lineup request."""

    status: str
    week: int
    moves: tuple[LineupMove, ...]

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, "week": self.week, "moves": [asdict(move) for move in self.moves]}


def _validate_moves(snapshot: TeamSnapshot, moves: tuple[LineupMove, ...], form: Any) -> None:
    if not moves:
        raise LineupError("at least one lineup move is required")
    ids = [move.yahoo_id for move in moves]
    if len(ids) != len(set(ids)):
        raise LineupError("each Yahoo player ID may appear only once")

    current = {player.yahoo_id: player.slot for player in snapshot.roster}
    if not isinstance(form, dict) or form.get("path") != TEAM_PATH or form.get("action") != f"{TEAM_PATH}/editroster":
        raise LineupError("lineup form identity check failed")
    fields = form.get("fields")
    if not isinstance(fields, dict):
        raise LineupError("lineup form fields are missing")

    resulting = Counter(player.slot for player in snapshot.roster)
    for move in moves:
        if current.get(move.yahoo_id) != move.from_slot:
            raise LineupError(
                f"Yahoo ID {move.yahoo_id} expected in {move.from_slot}, found {current.get(move.yahoo_id, 'missing')}"
            )
        field = fields.get(move.yahoo_id)
        if not isinstance(field, dict) or field.get("value") != move.from_slot:
            raise LineupError(f"lineup form disagrees for Yahoo ID {move.yahoo_id}")
        options = field.get("options")
        if not isinstance(options, dict) or move.to_slot not in options or options[move.to_slot]:
            raise LineupError(f"Yahoo ID {move.yahoo_id} cannot move to unlocked slot {move.to_slot}")
        resulting[move.from_slot] -= 1
        resulting[move.to_slot] += 1

    ir_count = sum(resulting.pop(slot, 0) for slot in INJURED_RESERVE_SLOTS)
    if resulting != EXPECTED_ACTIVE_SLOTS or ir_count > 2:
        raise LineupError(f"moves would produce an illegal slot layout: {dict(resulting)}")


class YahooLineupOperator:
    """Apply an exact lineup permutation and verify Yahoo's resulting slots."""

    def __init__(
        self,
        client: LineupClient,
        snapshot: Callable[[], TeamSnapshot] | None = None,
        timeout: float = 20,
    ):
        self.client = client
        self._snapshot = snapshot or YahooTeamReader(client).snapshot
        self.timeout = timeout

    def _read_form(self) -> Any:
        return self.client.evaluate(
            r'''/* yahoo-lineup-read-form */ (() => {
              const form = document.querySelector('#roster-edit-form');
              if (!form) return null;
              const fields = {};
              for (const select of form.querySelectorAll('select[name]')) {
                fields[select.name] = {
                  value: select.value,
                  options: Object.fromEntries([...select.options].map(option => [option.value, option.disabled])),
                };
              }
              return {path: location.pathname.replace(/\/$/, ''), action: new URL(form.action).pathname, fields};
            })()'''
        )

    def apply(self, moves: tuple[LineupMove, ...]) -> LineupReceipt:
        before = self._snapshot()
        desired = {move.yahoo_id: move.to_slot for move in moves}
        current = {player.yahoo_id: player.slot for player in before.roster}
        if moves and all(current.get(yahoo_id) == slot for yahoo_id, slot in desired.items()):
            return LineupReceipt("already_applied", before.week, moves)

        form = self._read_form()
        _validate_moves(before, moves, form)
        payload = json.dumps({move.yahoo_id: move.to_slot for move in moves})
        submitted = self.client.evaluate(
            f'''/* yahoo-lineup-submit */ (() => {{
              const form = document.querySelector('#roster-edit-form');
              const changes = {payload};
              const path = location.pathname.endsWith('/') ? location.pathname.slice(0, -1) : location.pathname;
              if (!form || path !== {TEAM_PATH!r}
                  || new URL(form.action).pathname !== {f"{TEAM_PATH}/editroster"!r}) return false;
              for (const [id, slot] of Object.entries(changes)) {{
                const select = form.querySelector(`select[name="${{CSS.escape(id)}}"]`);
                if (!select || ![...select.options].some(option => option.value === slot && !option.disabled)) return false;
                select.value = slot;
              }}
              form.submit();
              return true;
            }})()'''
        )
        if submitted is not True:
            raise LineupError("lineup form was not submitted")

        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            state = self.client.evaluate(
                "/* yahoo-lineup-post-state */ ({path: location.pathname, ready: document.readyState})"
            )
            if isinstance(state, dict) and state.get("path") == f"{TEAM_PATH}/editroster" and state.get("ready") == "complete":
                break
            time.sleep(0.1)
        else:
            raise LineupError("lineup POST response did not finish")

        self.client.navigate(
            TEAM_URL,
            lambda url: urlparse(url).path.rstrip("/") == TEAM_PATH,
            timeout=self.timeout,
        )

        deadline = time.monotonic() + self.timeout
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                after = self._snapshot()
                slots = {player.yahoo_id: player.slot for player in after.roster}
                if all(slots.get(yahoo_id) == slot for yahoo_id, slot in desired.items()):
                    return LineupReceipt("applied", after.week, moves)
            except CdpError as exc:
                last_error = exc
            time.sleep(0.1)
        detail = f": {last_error}" if last_error else ""
        raise LineupError(f"lineup submission was not confirmed by authoritative read-back{detail}")
