"""Fail-closed operator for the FD nation real Yahoo draft.

Unlike the mock module, this path requires an exact league/team authorization
at process start and reconstructs local state from Yahoo before every decision.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import time
from collections import Counter
from pathlib import Path
from typing import Any

from .cdp import CdpClient, CdpError, Target, list_targets, select_target
from .mock_draft import DraftPage, DraftState, Pick, PlayerRow, RosterPick

LEAGUE_ID = "1329011"
TEAM_ID = "2"
AUTHORIZATION = f"{LEAGUE_ID}/{TEAM_ID}"
DRAFT_PATH = f"/draftclient/f1/{LEAGUE_ID}/{TEAM_ID}"
LEAGUE_DRAFT_PATH = f"/f1/{LEAGUE_ID}/draft"


class RealDraftSafetyError(CdpError):
    """A real-draft invariant failed and execution must stop."""


class UncertainSubmission(RealDraftSafetyError):
    """A prior click cannot safely be replayed."""


def require_real_authorization(cli_confirmation: str) -> None:
    """Require two independent exact-value opt-ins for the real account."""
    if cli_confirmation != AUTHORIZATION:
        raise RealDraftSafetyError("--confirm-real-draft must name the exact league/team")
    if os.environ.get("FD_REAL_DRAFT_AUTHORIZATION") != AUTHORIZATION:
        raise RealDraftSafetyError("FD_REAL_DRAFT_AUTHORIZATION must name the exact league/team")


def find_real_draft_target(endpoint: str = "http://127.0.0.1:9222") -> Target:
    """Select exactly the authorized real draft-client target."""
    return select_target(
        lambda target: target.url.split("?", 1)[0].rstrip("/").endswith(DRAFT_PATH),
        endpoint,
    )


def _find_league_target(endpoint: str) -> Target:
    allowed = {
        LEAGUE_DRAFT_PATH,
        f"/f1/{LEAGUE_ID}",
        f"/f1/{LEAGUE_ID}/{TEAM_ID}",
    }
    matches = [
        target
        for target in list_targets(endpoint)
        if target.type == "page" and any(target.url.split("?", 1)[0].rstrip("/").endswith(path) for path in allowed)
    ]
    if len(matches) != 1:
        raise RealDraftSafetyError(f"expected exactly one authenticated FD nation page, found {len(matches)}")
    return matches[0]


def real_draft_preflight(endpoint: str = "http://127.0.0.1:9222") -> dict[str, Any]:
    """Read authenticated league identity, format, and countdown without mutation."""
    try:
        target = find_real_draft_target(endpoint)
    except CdpError:
        target = _find_league_target(endpoint)
    with CdpClient(target, endpoint) as client:
        result = client.evaluate(
            r'''(() => { const body = document.body?.innerText || '';
              const countdown = body.match(/\d+\s+days?\s+\d{2}:\d{2}:\d{2}/i);
              return {signedIn: !/Sign in to Yahoo/i.test(body),
                league: /FD nation|ID#\s*1329011/i.test(body),
                team: /Shiba Innu|Doge/i.test(body),
                tenTeams: /10\s+Teams/i.test(body), rounds: /15\s+Rounds/i.test(body),
                oneMinute: /1\s+minute/i.test(body), countdown: countdown?.[0] || null,
                inClient: location.pathname.replace(/\/$/, '') === '/draftclient/f1/1329011/2'}; })()'''
        )
    if not isinstance(result, dict) or not all(
        result.get(key) for key in ("signedIn", "league", "team")
    ):
        raise RealDraftSafetyError("real draft preflight identity check failed")
    return result


def wait_for_real_draft_target(
    endpoint: str = "http://127.0.0.1:9222",
    timeout: float = 90 * 60,
    refresh_interval: float = 20,
) -> Target:
    """Wait for Yahoo's exact real-draft link, then enter it without exposing auth."""
    deadline = time.monotonic() + timeout
    last_refresh = 0.0
    while time.monotonic() < deadline:
        matches = [
            target
            for target in list_targets(endpoint)
            if target.type == "page" and target.url.split("?", 1)[0].rstrip("/").endswith(DRAFT_PATH)
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise RealDraftSafetyError("multiple real draft targets are open")

        target = _find_league_target(endpoint)
        with CdpClient(target, endpoint) as client:
            identity = client.evaluate(
                r'''(() => { const body = document.body?.innerText || '';
                  return {signedIn: !/Sign in to Yahoo/i.test(body),
                    league: /FD nation|ID#\s*1329011/i.test(body),
                    team: /Shiba Innu|Doge/i.test(body)}; })()'''
            )
            if not identity or not all(identity.values()):
                raise RealDraftSafetyError("authenticated FD nation/team identity check failed")
            entered = client.evaluate(
                r'''(() => { const links = [...document.querySelectorAll('a[href]')]
                    .filter(link => new URL(link.href, location.href).pathname.replace(/\/$/, '') ===
                      '/draftclient/f1/1329011/2');
                  if (links.length !== 1) return false;
                  location.assign(links[0].href); return true; })()'''
            )
            if entered is not True and time.monotonic() - last_refresh >= refresh_interval:
                if not target.url.split("?", 1)[0].rstrip("/").endswith(LEAGUE_DRAFT_PATH):
                    client.navigate(
                        f"https://football.fantasysports.yahoo.com{LEAGUE_DRAFT_PATH}",
                        lambda url: LEAGUE_DRAFT_PATH in url,
                    )
                else:
                    client.call("Page.reload")
                last_refresh = time.monotonic()
        time.sleep(1)
    raise RealDraftSafetyError("real draft client did not become available before the deadline")


class RealDraftPage(DraftPage):
    """Current Yahoo draft page constrained to FD nation/team 2."""

    def __init__(self, client: CdpClient):
        path = client.target.url.split("?", 1)[0].rstrip("/")
        if not path.endswith(DRAFT_PATH):
            raise RealDraftSafetyError("target is not FD nation team 2's draft client")
        super().__init__(client, LEAGUE_ID)

    def verify_identity(self) -> None:
        identity = self.client.evaluate(
            r'''(() => { const body = document.body?.innerText || '';
              return {signedIn: !/Sign in to Yahoo/i.test(body),
                league: /FD nation/i.test(body), team: /Doge|Shiba Innu/i.test(body)}; })()'''
        )
        if not identity or not all(identity.values()):
            raise RealDraftSafetyError("real draft identity precondition failed")


class RealDraftOperator:
    """Resume-safe real draft operator backed by Yahoo roster history."""

    def __init__(self, client: CdpClient, audit_path: Path):
        self.page = RealDraftPage(client)
        self.audit_path = audit_path
        from driver import draft_driver as driver

        self.board = driver.load_original_board() or driver.static_board()
        driver.rebuild_abbrev_maps(self.board)

    def _log(self, event: str, **fields: Any) -> None:
        record = {"time": dt.datetime.now(dt.timezone.utc).isoformat(), "event": event,
                  "league": LEAGUE_ID, "team": TEAM_ID, **fields}
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with self.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
        print(json.dumps(record, sort_keys=True), flush=True)

    def _records(self) -> list[dict[str, Any]]:
        if not self.audit_path.exists():
            return []
        records = []
        for line in self.audit_path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("league") == LEAGUE_ID and record.get("team") == TEAM_ID:
                records.append(record)
        return records

    def _pending_submission(self) -> dict[str, Any] | None:
        pending: dict[str, Any] | None = None
        for record in self._records():
            if record.get("event") == "submit_intent":
                pending = record
            elif pending and record.get("overall") == pending.get("overall") and record.get("event") in {
                "confirmed", "recovered_confirmed", "recovered_other"
            }:
                pending = None
        return pending

    def _known_unavailable_names(self) -> set[str]:
        return {
            str(record["player"]).lower()
            for record in self._records()
            if record.get("event") == "search_unavailable" and record.get("player")
        }

    @staticmethod
    def _validate_state(state: DraftState) -> None:
        if state.total_roster != 15:
            raise RealDraftSafetyError(f"unexpected roster size {state.total_roster}")
        if len(state.roster) != state.team_count:
            raise RealDraftSafetyError(
                f"Yahoo roster parser returned {len(state.roster)} picks for count {state.team_count}"
            )
        ids = [pick.player.id for pick in state.roster]
        if len(ids) != len(set(ids)):
            raise RealDraftSafetyError("Yahoo roster history contains duplicate player IDs")
        rounds = sorted(pick.round for pick in state.roster)
        if rounds != list(range(1, state.team_count + 1)):
            raise RealDraftSafetyError("Yahoo roster history is not one authoritative pick per completed round")

    def _reconcile_pending(self, state: DraftState) -> None:
        pending = self._pending_submission()
        if not pending:
            return
        player_id = str(pending["player_id"])
        if any(pick.player.id == player_id for pick in state.roster):
            self._log("recovered_confirmed", overall=pending["overall"], player_id=player_id)
            return
        if (state.pick is not None and state.pick > int(pending["overall"])) or (
            state.team_count >= int(pending["round"])
        ):
            self._log("recovered_other", overall=pending["overall"], player_id=player_id)
            return
        raise UncertainSubmission(
            "an earlier submit may still be pending at this overall pick; refusing to replay it"
        )

    @staticmethod
    def _position_counts(roster: tuple[RosterPick, ...]) -> Counter[str]:
        return Counter(pick.player.pos for pick in roster)

    def _canonical_roster_names(self, roster: tuple[RosterPick, ...]) -> set[str]:
        from driver import draft_driver as driver

        rows = [[pick.player.name, pick.player.team, pick.player.pos,
                 f"{pick.player.name} {pick.player.team} - {pick.player.pos}"] for pick in roster]
        names, _, _ = driver.normalize_available(rows)
        return {name.lower() for name in names}

    def _resolve_choice(self, rows: tuple[PlayerRow, ...], choice: tuple[Any, ...]) -> PlayerRow | None:
        from driver import draft_driver as driver

        wanted_name, wanted_team, wanted_pos, _ = choice
        matches = []
        for row in rows:
            names, _, _ = driver.normalize_available(
                [[row.name, row.team, row.pos, f"{row.name} {row.team} - {row.pos} ADP {row.adp}"]]
            )
            if (names and names[0] == wanted_name
                    and (not wanted_team or row.team.upper() == str(wanted_team).upper())
                    and (not wanted_pos or row.pos == wanted_pos)):
                matches.append(row)
        return matches[0] if len(matches) == 1 else None

    def _choose(self, state: DraftState) -> PlayerRow:
        from driver import draft_driver as driver

        if state.round is None:
            raise RealDraftSafetyError("Yahoo did not expose the current round")
        roster_names = self._canonical_roster_names(state.roster)
        unavailable_names = self._known_unavailable_names()
        remaining = [value["name"] for value in self.board.values()
                     if value["name"].lower() not in roster_names | unavailable_names]
        choice = None
        for _ in range(20):
            choice = driver.choose_pick(
                remaining, dict(self._position_counts(state.roster)), state.round, self.board
            )
            if not choice:
                break
            wanted_name, wanted_team, wanted_pos, _ = choice
            self.page.set_search(driver.to_display(wanted_name, wanted_team))
            time.sleep(0.5)
            searched = self.page.read_state()
            row = self._resolve_choice(searched.rows, choice)
            if row:
                return row
            self._log("search_unavailable", round=state.round, overall=state.pick,
                      player=wanted_name, player_team=wanted_team, pos=wanted_pos)
            remaining = [name for name in remaining if name != wanted_name]
        self.page.set_search("")
        time.sleep(0.2)
        visible = self.page.read_state()
        healthy = [row for row in visible.rows if row.injury not in {"O", "IR", "PUP", "CEL"}]
        if not healthy:
            raise RealDraftSafetyError("no identity-safe selectable player is visible")
        raw = [[row.name, row.team, row.pos, f"{row.name} {row.team} - {row.pos} ADP {row.adp}"]
               for row in healthy]
        names, adp, positions = driver.normalize_available(raw)
        fallback = driver.choose_pick(
            names, dict(self._position_counts(state.roster)), state.round, self.board, adp, positions
        )
        row = self._resolve_choice(tuple(healthy), fallback) if fallback else None
        if not row:
            raise RealDraftSafetyError("no exact row matched the visible fallback decision")
        return row

    def run(self, deadline_hours: float = 4, poll_interval: float = 0.25) -> list[Pick]:
        self.page.client.bring_to_front()
        self.page.verify_identity()
        self.page.disable_autodraft()
        deadline = time.monotonic() + deadline_hours * 3600
        while time.monotonic() < deadline:
            state = self.page.read_state()
            self._validate_state(state)
            self._reconcile_pending(state)
            if state.complete and state.team_count == 15:
                self._log("complete", count=15)
                return [Pick(p.round, p.overall, p.player) for p in state.roster]
            if not state.my_turn:
                time.sleep(poll_interval)
                continue
            if state.round != state.team_count + 1 or state.pick is None:
                raise RealDraftSafetyError("Yahoo round/pick does not match authoritative roster history")
            player = self._choose(state)
            self._log("decision", round=state.round, overall=state.pick, player_id=player.id,
                      player=player.name, player_team=player.team, pos=player.pos)
            self._log("submit_intent", round=state.round, overall=state.pick,
                      player_id=player.id, player=player.name)
            self.page.submit(player, state.pick)
            confirmation_deadline = time.monotonic() + 10
            after = state
            while time.monotonic() < confirmation_deadline:
                after = self.page.read_state()
                if after.team_count == state.team_count + 1:
                    break
                time.sleep(0.1)
            else:
                self._log("uncertain", overall=state.pick, player_id=player.id)
                raise UncertainSubmission("real pick outcome is uncertain; no retry will be attempted")
            self._validate_state(after)
            matching = [pick for pick in after.roster if pick.player.id == player.id]
            if len(matching) != 1 or matching[0].overall != state.pick:
                raise RealDraftSafetyError("roster advanced without the exact submitted player/pick")
            self._log("confirmed", round=state.round, overall=state.pick,
                      player_id=player.id, player=player.name, pos=player.pos)
            self.page.set_search("")
        raise RealDraftSafetyError("real draft operator exceeded its overall deadline")
