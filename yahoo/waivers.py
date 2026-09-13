"""Exact-ID Yahoo waiver claims with confirmation and pending-state read-back.

Applied claims verify two ways, because Yahoo reports them differently:
waiver claims create a pending transaction; immediate free-agent adds never
do, so they are confirmed by an exact-ID roster read-back instead (#105).
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable, Protocol
from urllib.parse import urlencode, urlparse

from .cdp import CdpError
from .team import LEAGUE_ID, TEAM_ID, TEAM_PATH, TeamSnapshot, YahooTeamReader

BASE = "https://football.fantasysports.yahoo.com"
ADD_PATH = f"/f1/{LEAGUE_ID}/addplayer"
TEAM_ADD_PATH = f"/f1/{LEAGUE_ID}/{TEAM_ID}/addplayer"
TRANSACTIONS_PATH = f"/f1/{LEAGUE_ID}/transactions"


class WaiverError(CdpError):
    """A waiver claim failed identity, state, or read-back validation."""


class WaiverClient(Protocol):
    def evaluate(self, expression: str) -> Any: ...
    def navigate(self, url: str, expected: Callable[[str], bool], timeout: float = 20) -> str: ...


ACTIVE_ROSTER_SIZE = 15


@dataclass(frozen=True)
class WaiverClaim:
    add_yahoo_id: str
    add_name: str
    drop_yahoo_id: str = ""
    drop_name: str = ""


@dataclass(frozen=True)
class WaiverReceipt:
    status: str
    claim: WaiverClaim

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, "claim": asdict(self.claim)}


class YahooWaiverOperator:
    """Prepare or submit one exact waiver claim; never retries a POST."""

    def __init__(
        self,
        client: WaiverClient,
        snapshot: Callable[[], TeamSnapshot] | None = None,
        timeout: float = 20,
    ):
        self.client = client
        self._snapshot = snapshot or YahooTeamReader(client).snapshot
        self.timeout = timeout

    def _team(self):
        return self._snapshot()

    def _restore_team(self) -> None:
        self.client.navigate(f"{BASE}{TEAM_PATH}", lambda url: urlparse(url).path.rstrip("/") == TEAM_PATH, self.timeout)

    def restore_team(self) -> None:
        """Return the controlled tab to the canonical authorized team page."""
        self._restore_team()

    def _pending(self, claim: WaiverClaim) -> bool:
        query = urlencode({"transactionsfilter": "waiver"})
        self.client.navigate(f"{BASE}{TRANSACTIONS_PATH}?{query}", lambda url: urlparse(url).path == TRANSACTIONS_PATH, self.timeout)
        rows = self.client.evaluate(
            "/* yahoo-waiver-pending */ [...document.querySelectorAll('tr')].map(row => (row.innerText || '').trim()).filter(Boolean)"
        )
        if not isinstance(rows, list):
            raise WaiverError("waiver transaction rows are missing")
        add = claim.add_name.casefold()
        drop = claim.drop_name.casefold()
        return any(
            add in str(row).casefold() and (not drop or drop in str(row).casefold())
            for row in rows
        )

    def _on_roster(self, claim: WaiverClaim) -> bool:
        """Immediate-add verification: exact-ID roster read-back.

        Free-agent adds execute instantly and never create a pending waiver
        transaction, so the only authoritative signal is the roster itself:
        the add player present with the exact identity, the drop player gone.
        """
        roster = {player.yahoo_id: player for player in self._team().roster}
        added = roster.get(claim.add_yahoo_id)
        if added is None or added.name != claim.add_name:
            return False
        if claim.drop_yahoo_id and claim.drop_yahoo_id in roster:
            return False
        return True

    def _stage(self) -> Any:
        return self.client.evaluate(
            r'''/* yahoo-waiver-stage */ (() => {
              const form = [...document.forms].find(form => new URL(form.action).pathname === '/f1/1329011/2/addplayer');
              if (!form) return null;
              const hidden = Object.fromEntries([...form.querySelectorAll('input[type=hidden][name]')].map(input => [input.name, input.value]));
              const drops = Object.fromEntries([...form.querySelectorAll('input[name=dpid]')].map(input => {
                const row = input.closest('tr');
                const link = row?.querySelector('.ysf-player-name a, td.player a[title]');
                return [input.value, link?.title || link?.innerText?.trim() || ''];
              }));
              return {path: location.pathname, action: new URL(form.action).pathname, hidden, drops};
            })()'''
        )

    def _submit_stage_two(self, claim: WaiverClaim) -> None:
        payload = json.dumps({"add": claim.add_yahoo_id, "drop": claim.drop_yahoo_id})
        submitted = self.client.evaluate(
            f'''/* yahoo-waiver-stage-two-submit */ (() => {{
              const intent = {payload};
              const form = [...document.forms].find(form => new URL(form.action).pathname === {TEAM_ADD_PATH!r});
              if (!form || form.elements.namedItem('stage')?.value !== '2' || form.elements.namedItem('apid')?.value !== intent.add) return false;
              if (intent.drop) {{
                const drop = [...form.querySelectorAll('input[name=dpid]')].find(input => input.value === intent.drop && !input.disabled);
                if (!drop) return false;
                drop.checked = true;
              }}
              form.submit(); return true;
            }})()'''
        )
        if submitted is not True:
            raise WaiverError("waiver selection form was not submitted")

    def _wait_stage_three(self, claim: WaiverClaim) -> None:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            stage = self._stage()
            hidden = stage.get("hidden", {}) if isinstance(stage, dict) else {}
            if stage and stage.get("path") == TEAM_ADD_PATH and hidden.get("stage") == "3":
                if hidden.get("apid") != claim.add_yahoo_id:
                    raise WaiverError("waiver confirmation IDs disagree with intent")
                if claim.drop_yahoo_id and hidden.get("dpid") != claim.drop_yahoo_id:
                    raise WaiverError("waiver confirmation IDs disagree with intent")
                if not claim.drop_yahoo_id and hidden.get("dpid"):
                    raise WaiverError("add-only claim was offered a confirmation that includes a drop")
                return
            time.sleep(0.1)
        raise WaiverError("waiver confirmation page did not load")

    def prepare(self, claim: WaiverClaim) -> WaiverReceipt:
        snapshot = self._team()
        roster = {player.yahoo_id: player for player in snapshot.roster}
        if claim.drop_yahoo_id:
            drop = roster.get(claim.drop_yahoo_id)
            if drop is None or drop.name != claim.drop_name:
                raise WaiverError("drop-player precondition failed")
        else:
            active = sum(1 for player in snapshot.roster if player.slot not in {"IR", "IL"})
            if active >= ACTIVE_ROSTER_SIZE:
                raise WaiverError("roster is full; a free-agent add requires a drop player")
        if self._pending(claim):
            self._restore_team()
            return WaiverReceipt("already_pending", claim)
        self._restore_team()
        self.client.navigate(
            f"{BASE}{ADD_PATH}?{urlencode({'apid': claim.add_yahoo_id})}",
            lambda url: urlparse(url).path == ADD_PATH,
            self.timeout,
        )
        stage = self._stage()
        hidden = stage.get("hidden", {}) if isinstance(stage, dict) else {}
        drops = stage.get("drops", {}) if isinstance(stage, dict) else {}
        if not stage or hidden.get("stage") != "2" or hidden.get("apid") != claim.add_yahoo_id:
            raise WaiverError("waiver selection page identity failed")
        if claim.drop_yahoo_id and drops.get(claim.drop_yahoo_id) != claim.drop_name:
            raise WaiverError("drop player is not offered with the expected identity")
        self._submit_stage_two(claim)
        self._wait_stage_three(claim)
        return WaiverReceipt("prepared", claim)

    def apply(self, claim: WaiverClaim) -> WaiverReceipt:
        prepared = self.prepare(claim)
        if prepared.status == "already_pending":
            return prepared
        submitted = self.client.evaluate(
            r'''/* yahoo-waiver-confirm-submit */ (() => {
              const form = [...document.forms].find(form => new URL(form.action).pathname === '/f1/1329011/2/addplayer');
              if (!form || form.elements.namedItem('stage')?.value !== '3') return false;
              window.__yahooWaiverSubmission = 'in-flight'; form.submit(); return true;
            })()'''
        )
        if submitted is not True:
            raise WaiverError("waiver confirmation was not submitted")
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            try:
                marker = self.client.evaluate("/* yahoo-waiver-post-marker */ window.__yahooWaiverSubmission || null")
                if marker is None:
                    break
            except CdpError:
                pass
            time.sleep(0.1)
        else:
            raise WaiverError("waiver POST response did not finish")
        if self._pending(claim):
            self._restore_team()
            return WaiverReceipt("pending", claim)
        # The roster read-back only works on the team page, and _pending leaves
        # the tab on transactions — restore first or the snapshot read raises.
        # One fresh read is enough: the POST completed at the marker check, and
        # extra Yahoo page loads are expensive (WAF), so no poll loop.
        self._restore_team()
        if self._on_roster(claim):
            return WaiverReceipt("completed", claim)
        raise WaiverError("submitted claim is absent from authoritative pending "
                          "transactions and the roster read-back does not confirm it")
