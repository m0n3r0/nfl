"""Tests for exact-ID, pending-state-verified Yahoo waiver claims."""

from __future__ import annotations

from urllib.parse import urlparse

import pytest

from yahoo.team import RosterPlayer, TeamSnapshot
from yahoo.waivers import WaiverClaim, WaiverError, YahooWaiverOperator


def snapshot():
    players = [RosterPlayer("34054", "Brian Robinson", "ATL", "RB", "BN", "", "Sun")]
    return TeamSnapshot("1329011", "2", "Shiba Innu", "0-0-0", 1, "Opponent", 4, tuple(players))


class Client:
    def __init__(self):
        self.page = "team"
        self.pending = False
        self.stage_two_submits = 0
        self.confirm_submits = 0

    def navigate(self, url, expected, timeout=20):
        assert expected(url)
        path = urlparse(url).path
        if path.endswith("/transactions"):
            self.page = "transactions"
        elif path.endswith("/addplayer"):
            self.page = "add2"
        else:
            self.page = "team"
        return url

    def evaluate(self, expression):
        if "yahoo-waiver-pending" in expression:
            return ["Add: Baker Mayfield Drop: Brian Robinson"] if self.pending else ["No recent transactions"]
        if "yahoo-waiver-stage-two-submit" in expression:
            assert self.page == "add2"
            self.stage_two_submits += 1
            self.page = "add3"
            return True
        if "yahoo-waiver-stage" in expression:
            if self.page == "add2":
                return {"path": "/f1/1329011/addplayer", "action": "/f1/1329011/2/addplayer", "hidden": {"stage": "2", "apid": "30971"}, "drops": {"34054": "Brian Robinson"}}
            if self.page == "add3":
                return {"path": "/f1/1329011/2/addplayer", "action": "/f1/1329011/2/addplayer", "hidden": {"stage": "3", "apid": "30971", "dpid": "34054"}, "drops": {}}
            return None
        if "yahoo-waiver-confirm-submit" in expression:
            assert self.page == "add3"
            self.confirm_submits += 1
            self.pending = True
            self.page = "response"
            return True
        if "yahoo-waiver-post-marker" in expression:
            return None
        raise AssertionError("unexpected expression")


def claim():
    return WaiverClaim("30971", "Baker Mayfield", "34054", "Brian Robinson")


def test_prepares_exact_confirmation_without_creating_claim():
    client = Client()
    receipt = YahooWaiverOperator(client, snapshot, timeout=0.01).prepare(claim())
    assert receipt.status == "prepared"
    assert client.stage_two_submits == 1
    assert client.confirm_submits == 0


def test_applies_once_and_verifies_pending_transaction():
    client = Client()
    operator = YahooWaiverOperator(client, snapshot, timeout=0.01)
    assert operator.apply(claim()).status == "pending"
    assert operator.apply(claim()).status == "already_pending"
    assert client.confirm_submits == 1


def test_rejects_stale_drop_identity_before_navigation():
    client = Client()
    stale = WaiverClaim("30971", "Baker Mayfield", "34054", "Bijan Robinson")
    with pytest.raises(WaiverError, match="drop-player precondition"):
        YahooWaiverOperator(client, snapshot).prepare(stale)
    assert client.page == "team"


def test_rejects_confirmation_id_drift():
    client = Client()
    original = client.evaluate

    def drift(expression):
        value = original(expression)
        if "/* yahoo-waiver-stage */" in expression and client.page == "add3":
            value["hidden"]["dpid"] = "wrong"
        return value

    client.evaluate = drift
    with pytest.raises(WaiverError, match="confirmation IDs disagree"):
        YahooWaiverOperator(client, snapshot, timeout=0.01).prepare(claim())


class AddOnlyClient(Client):
    def evaluate(self, expression):
        if "yahoo-waiver-pending" in expression:
            return ["Add: Baker Mayfield"] if self.pending else ["No recent transactions"]
        if "yahoo-waiver-stage" in expression and "two-submit" not in expression:
            if self.page == "add3":
                return {"path": "/f1/1329011/2/addplayer", "action": "/f1/1329011/2/addplayer",
                        "hidden": {"stage": "3", "apid": "30971"}, "drops": {}}
        return super().evaluate(expression)


class DropLeakingAddOnlyClient(AddOnlyClient):
    """Stage three comes back with an unexpected dpid for an add-only claim."""

    def evaluate(self, expression):
        if "yahoo-waiver-stage" in expression and "two-submit" not in expression:
            if self.page == "add3":
                return {"path": "/f1/1329011/2/addplayer", "action": "/f1/1329011/2/addplayer",
                        "hidden": {"stage": "3", "apid": "30971", "dpid": "34054"}, "drops": {}}
        return super().evaluate(expression)


def test_add_only_claim_full_flow():
    client = AddOnlyClient()
    operator = YahooWaiverOperator(client, snapshot=snapshot)
    claim = WaiverClaim(add_yahoo_id="30971", add_name="Baker Mayfield")

    receipt = operator.apply(claim)

    assert receipt.status == "pending"
    assert client.stage_two_submits == 1
    assert client.confirm_submits == 1


def test_add_only_rejected_when_roster_full():
    players = [
        RosterPlayer(str(i), f"Player {i}", "KC", "RB", "BN" if i > 9 else "WR", "", "Sun")
        for i in range(1, 16)
    ]
    full = TeamSnapshot("1329011", "2", "Shiba Innu", "0-0-0", 1, "Opponent", 4, tuple(players))
    operator = YahooWaiverOperator(AddOnlyClient(), snapshot=lambda: full)

    with pytest.raises(WaiverError, match="roster is full"):
        operator.prepare(WaiverClaim(add_yahoo_id="30971", add_name="Baker Mayfield"))


def test_add_only_rejects_confirmation_that_includes_a_drop():
    client = DropLeakingAddOnlyClient()
    operator = YahooWaiverOperator(client, snapshot=snapshot)

    with pytest.raises(WaiverError, match="includes a drop"):
        operator.apply(WaiverClaim(add_yahoo_id="30971", add_name="Baker Mayfield"))


class ImmediateAddClient(Client):
    """Free-agent adds execute instantly: no pending claim ever appears."""

    def evaluate(self, expression):
        if "yahoo-waiver-confirm-submit" in expression:
            assert self.page == "add3"
            self.confirm_submits += 1
            self.page = "response"
            return True
        return super().evaluate(expression)


def roster_snapshot(players):
    return TeamSnapshot("1329011", "2", "Shiba Innu", "0-0-0", 1, "Opponent", 4, tuple(players))


def on_team_page(client):
    """The production snapshot only works on the team page; pin that contract."""
    assert client.page == "team", "roster read-back must run on the team page"


def test_apply_accepts_immediate_fa_add_via_roster_readback():
    client = ImmediateAddClient()

    def live_snapshot():
        on_team_page(client)
        if client.confirm_submits:
            return roster_snapshot([RosterPlayer("30971", "Baker Mayfield", "TB", "QB", "BN", "", "Sun")])
        return snapshot()

    receipt = YahooWaiverOperator(client, live_snapshot, timeout=0.01).apply(claim())

    assert receipt.status == "completed"
    assert client.confirm_submits == 1
    assert client.page == "team"  # restored after success


def test_apply_halts_when_neither_pending_nor_roster_confirm():
    client = ImmediateAddClient()  # roster never changes: static snapshot()

    def static_snapshot():
        on_team_page(client)
        return snapshot()

    with pytest.raises(WaiverError, match="roster read-back"):
        YahooWaiverOperator(client, static_snapshot, timeout=0.01).apply(claim())
    assert client.confirm_submits == 1
    assert client.page == "team"  # still restored after the halt


def test_immediate_add_requires_exact_identity_on_readback():
    client = ImmediateAddClient()

    def wrong_name():
        on_team_page(client)
        if client.confirm_submits:
            return roster_snapshot([RosterPlayer("30971", "Baker Mayfield Jr.", "TB", "QB", "BN", "", "Sun")])
        return snapshot()

    with pytest.raises(WaiverError, match="roster read-back"):
        YahooWaiverOperator(client, wrong_name, timeout=0.01).apply(claim())


def test_immediate_add_halts_when_drop_player_still_on_roster():
    client = ImmediateAddClient()

    def drop_still_there():
        on_team_page(client)
        if client.confirm_submits:
            return roster_snapshot([
                RosterPlayer("30971", "Baker Mayfield", "TB", "QB", "BN", "", "Sun"),
                RosterPlayer("34054", "Brian Robinson", "ATL", "RB", "BN", "", "Sun"),
            ])
        return snapshot()

    with pytest.raises(WaiverError, match="roster read-back"):
        YahooWaiverOperator(client, drop_still_there, timeout=0.01).apply(claim())


class ImmediateAddOnlyClient(AddOnlyClient):
    """Add-only FA add: add-only stage payloads, no pending claim afterwards."""

    def evaluate(self, expression):
        if "yahoo-waiver-confirm-submit" in expression:
            assert self.page == "add3"
            self.confirm_submits += 1
            self.page = "response"
            return True
        return super().evaluate(expression)


def test_add_only_immediate_add_verified_by_readback():
    client = ImmediateAddOnlyClient()

    def live_snapshot():
        on_team_page(client)
        if client.confirm_submits:
            return roster_snapshot([
                RosterPlayer("34054", "Brian Robinson", "ATL", "RB", "BN", "", "Sun"),
                RosterPlayer("30971", "Baker Mayfield", "TB", "QB", "BN", "", "Sun"),
            ])
        return snapshot()

    claim = WaiverClaim(add_yahoo_id="30971", add_name="Baker Mayfield")
    receipt = YahooWaiverOperator(client, live_snapshot, timeout=0.01).apply(claim)

    assert receipt.status == "completed"
    assert client.confirm_submits == 1
