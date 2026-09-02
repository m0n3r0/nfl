"""Tests for exact-ID, read-back-verified Yahoo lineup changes."""

from __future__ import annotations

from dataclasses import replace
from typing import Callable

import pytest

from yahoo.lineup import LineupError, LineupMove, YahooLineupOperator
from yahoo.team import RosterPlayer, TeamSnapshot


SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "W/R/T", "BN", "BN", "BN", "BN", "BN", "BN", "K", "DEF"]
POSITIONS = ["QB", "RB", "RB", "WR", "WR", "TE", "RB", "WR", "WR", "RB", "WR", "RB", "WR", "K", "DEF"]


def snapshot() -> TeamSnapshot:
    return TeamSnapshot(
        league_id="1329011", team_id="2", team_name="Shiba Innu", record="0-0-0",
        week=1, opponent="QB Sack Corey", waiver_priority=4,
        roster=tuple(
            RosterPlayer(str(index), f"Player {index}", "NE", position, slot, "", "Sun")
            for index, (slot, position) in enumerate(zip(SLOTS, POSITIONS), 1)
        ),
    )


class Client:
    def __init__(self, current: TeamSnapshot, *, disabled: bool = False):
        self.current = current
        self.pending = None
        self.disabled = disabled
        self.submissions = 0

    def read_snapshot(self) -> TeamSnapshot:
        return self.current

    def evaluate(self, expression):
        if "yahoo-lineup-read-form" in expression:
            return {
                "path": "/f1/1329011/2", "action": "/f1/1329011/2/editroster",
                "fields": {
                    player.yahoo_id: {
                        "value": player.slot,
                        "options": {slot: self.disabled for slot in eligible(player.position)},
                    }
                    for player in self.current.roster
                },
            }
        if "yahoo-lineup-submit" in expression:
            self.submissions += 1
            slots = {"7": "BN", "8": "W/R/T"}
            self.pending = replace(
                self.current,
                roster=tuple(replace(player, slot=slots.get(player.yahoo_id, player.slot)) for player in self.current.roster),
            )
            return True
        if "yahoo-lineup-post-state" in expression:
            return {"path": "/f1/1329011/2/editroster", "ready": "complete"}
        raise AssertionError("unexpected expression")

    def navigate(self, url: str, expected: Callable[[str], bool], timeout: float = 20) -> str:
        assert self.pending is not None
        assert expected(url)
        self.current = self.pending
        self.pending = None
        return url


def eligible(position: str) -> list[str]:
    values = {"QB": ["QB"], "RB": ["RB", "W/R/T"], "WR": ["WR", "W/R/T"], "TE": ["TE", "W/R/T"], "K": ["K"], "DEF": ["DEF"]}[position]
    return values + ["BN"]


def flex_swap() -> tuple[LineupMove, ...]:
    return (LineupMove("7", "W/R/T", "BN"), LineupMove("8", "BN", "W/R/T"))


def test_applies_legal_swap_and_confirms_read_back():
    client = Client(snapshot())
    receipt = YahooLineupOperator(client, client.read_snapshot, timeout=0.01).apply(flex_swap())

    assert receipt.status == "applied"
    assert client.submissions == 1
    assert {player.yahoo_id: player.slot for player in client.current.roster}["8"] == "W/R/T"


def test_already_applied_is_idempotent_and_does_not_resubmit():
    client = Client(snapshot())
    operator = YahooLineupOperator(client, client.read_snapshot, timeout=0.01)
    operator.apply(flex_swap())

    second = operator.apply(flex_swap())

    assert second.status == "already_applied"
    assert client.submissions == 1


def test_rejects_stale_expected_slot():
    client = Client(snapshot())
    with pytest.raises(LineupError, match="expected in RB"):
        YahooLineupOperator(client, client.read_snapshot).apply((LineupMove("7", "RB", "BN"),))
    assert client.submissions == 0


def test_rejects_move_that_does_not_preserve_roster_slots():
    client = Client(snapshot())
    with pytest.raises(LineupError, match="illegal slot layout"):
        YahooLineupOperator(client, client.read_snapshot).apply((LineupMove("7", "W/R/T", "BN"),))
    assert client.submissions == 0


def test_rejects_locked_or_disabled_target():
    client = Client(snapshot(), disabled=True)
    with pytest.raises(LineupError, match="cannot move"):
        YahooLineupOperator(client, client.read_snapshot).apply(flex_swap())
    assert client.submissions == 0
