"""Tests for the read-only Yahoo team snapshot."""

from __future__ import annotations

import pytest

from yahoo.team import TeamReadError, YahooTeamReader, _parse_payload


SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "W/R/T", "BN", "BN", "BN", "BN", "BN", "BN", "K", "DEF"]
POSITIONS = ["QB", "RB", "RB", "WR", "WR", "TE", "RB", "WR", "WR", "RB", "WR", "RB", "WR", "K", "DEF"]


def payload():
    return {
        "identity": {"signedIn": True, "league": True, "team": True, "path": True},
        "summary": {
            "team_name": "Shiba Innu", "record": "0-0-0",
            "matchup": "Week 1 vs QB Sack Corey", "waiver": "Waiver Priority: 4th",
        },
        "roster": [
            {
                "yahoo_id": str(index), "name": f"Player {index}", "team": "NE",
                "position": position, "slot": slot,
                "injury_status": "Q" if index == 1 else "", "game": "Sun 1:00 pm vs NYJ",
            }
            for index, (slot, position) in enumerate(zip(SLOTS, POSITIONS), 1)
        ],
    }


def test_parse_authoritative_team_snapshot():
    snapshot = _parse_payload(payload())

    assert snapshot.league_id == "1329011"
    assert snapshot.team_id == "2"
    assert snapshot.week == 1
    assert snapshot.opponent == "QB Sack Corey"
    assert snapshot.waiver_priority == 4
    assert len(snapshot.roster) == 15
    assert snapshot.roster[0].injury_status == "Q"


def test_rejects_identity_failure():
    current = payload()
    current["identity"]["team"] = False
    with pytest.raises(TeamReadError, match="identity check"):
        _parse_payload(current)


def test_rejects_duplicate_yahoo_player_ids():
    current = payload()
    current["roster"][1]["yahoo_id"] = current["roster"][0]["yahoo_id"]
    with pytest.raises(TeamReadError, match="duplicate Yahoo player IDs"):
        _parse_payload(current)


def test_rejects_unexpected_lineup_slots():
    current = payload()
    current["roster"][6]["slot"] = "BN"
    with pytest.raises(TeamReadError, match="unexpected lineup slots"):
        _parse_payload(current)


def test_accepts_two_injured_reserve_players_in_addition_to_active_roster():
    current = payload()
    current["roster"].extend([
        {
            "yahoo_id": "16", "name": "Player 16", "team": "NE",
            "position": "RB", "slot": "IR", "injury_status": "IR", "game": "",
        },
        {
            "yahoo_id": "17", "name": "Player 17", "team": "NE",
            "position": "WR", "slot": "IR", "injury_status": "IR", "game": "",
        },
    ])

    snapshot = _parse_payload(current)

    assert len(snapshot.roster) == 17


def test_reader_only_evaluates_page():
    class Client:
        def __init__(self):
            self.expression = ""

        def evaluate(self, expression):
            self.expression = expression
            return payload()

    client = Client()
    snapshot = YahooTeamReader(client).snapshot()

    assert len(snapshot.roster) == 15
    assert "querySelectorAll('tr.editable')" in client.expression
    assert not hasattr(client, "navigate")
