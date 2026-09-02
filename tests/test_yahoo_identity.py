"""Tests for authoritative available-player reads and stable identity mapping."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from yahoo.identity import YahooPlayerIdentity, reconcile_identities, write_identity_map
from yahoo.players import PlayerReadError, _parse_payload


def player_payload():
    return {
        "identity": {"signedIn": True, "origin": True, "league": True, "path": True},
        "players": [{
            "yahoo_id": "30971", "name": "Baker Mayfield", "team": "TB", "position": "QB",
            "availability": "W (Sep 4)", "injury_status": "", "game": "Sun 1:00 pm @ Cin",
        }],
    }


def model():
    return pd.DataFrame([
        {"player_id": "baker", "player_display_name": "Baker Mayfield", "position": "QB", "last_team": "TB"},
        {"player_id": "brian", "player_display_name": "Brian Robinson", "position": "RB", "last_team": "SF"},
        {"player_id": "bijan", "player_display_name": "Bijan Robinson", "position": "RB", "last_team": "ATL"},
        {"player_id": "josh-a", "player_display_name": "Josh Allen", "position": "QB", "last_team": "BUF"},
        {"player_id": "josh-b", "player_display_name": "Josh Allen", "position": "QB", "last_team": "JAX"},
    ])


def test_parses_available_player_by_yahoo_id():
    players = _parse_payload(player_payload())
    assert players[0].yahoo_id == "30971"
    assert players[0].availability == "W (Sep 4)"


def test_rejects_non_yahoo_or_duplicate_page_state():
    payload = player_payload()
    payload["identity"]["origin"] = False
    with pytest.raises(PlayerReadError, match="identity check"):
        _parse_payload(payload)

    payload = player_payload()
    payload["players"].append(dict(payload["players"][0]))
    with pytest.raises(PlayerReadError, match="duplicate Yahoo IDs"):
        _parse_payload(payload)


def test_exact_id_bridge_matches_and_flags_current_team_drift():
    mappings = reconcile_identities([
        YahooPlayerIdentity("30971", "Baker Mayfield", "TB", "QB"),
        YahooPlayerIdentity("34054", "Brian Robinson", "ATL", "RB"),
    ], model())

    assert mappings[0].internal_id == "baker" and mappings[0].actionable
    assert mappings[1].internal_id == "brian"
    assert mappings[1].status == "team_mismatch"
    assert not mappings[1].actionable


def test_never_expands_abbreviation_and_rejects_ambiguous_full_name():
    mappings = reconcile_identities([
        YahooPlayerIdentity("1", "J. Allen", "BUF", "QB"),
        YahooPlayerIdentity("2", "Josh Allen", "BUF", "QB"),
    ], model())
    assert mappings[0].status == "unmapped"
    assert mappings[1].status == "ambiguous"


def test_persisted_map_is_keyed_by_yahoo_id(tmp_path):
    mappings = reconcile_identities([YahooPlayerIdentity("30971", "Baker Mayfield", "TB", "QB")], model())
    target = tmp_path / "map.json"
    write_identity_map(target, mappings)
    row = json.loads(target.read_text())["players"][0]
    assert row == {
        "actionable": True, "internal_id": "baker", "internal_name": "Baker Mayfield",
        "internal_team": "TB", "position": "QB", "status": "matched", "yahoo_id": "30971",
        "yahoo_name": "Baker Mayfield", "yahoo_team": "TB",
    }
