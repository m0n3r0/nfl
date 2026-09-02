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
