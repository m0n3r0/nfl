"""Hermetic tests for tools/trade_check.py player lookup."""

import sys

import pandas as pd
import pytest

sys.path.insert(0, "tools")

import trade_check  # noqa: E402


def _proj() -> pd.DataFrame:
    return pd.DataFrame([
        {"player_display_name": "Chris Olave", "position": "WR",
         "last_team": "NO", "proj_ppg": 11.0, "proj_total": 187.0},
        {"player_display_name": "Chase Brown", "position": "RB",
         "last_team": "CIN", "proj_ppg": 12.5, "proj_total": 212.5},
        {"player_display_name": "Chris Godwin", "position": "WR",
         "last_team": "TB", "proj_ppg": 9.0, "proj_total": 153.0},
    ])


def test_find_player_exact_single_hit():
    hit = trade_check.find_player(_proj(), "olave")
    assert hit["name"] == "Chris Olave"
    assert hit["position"] == "WR"
    assert hit["proj_total"] == 187.0


def test_find_player_ambiguous_is_loud():
    with pytest.raises(SystemExit, match="matched 2 players"):
        trade_check.find_player(_proj(), "chris")


def test_find_player_missing_is_loud():
    with pytest.raises(SystemExit, match="matched 0 players"):
        trade_check.find_player(_proj(), "nobody")
