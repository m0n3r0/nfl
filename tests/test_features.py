"""Hermetic tests for the model training frame and in-season rating guards."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import features, model  # noqa: E402


def _ratings(teams):
    """Minimal as-of ratings frame with every column game_feature_row reads."""
    return pd.DataFrame({
        "team": list(teams),
        "off_epa_per_play": 0.05,
        "def_epa_allowed_per_play": 0.02,
        "off_rz_td_rate": 0.5,
        "off_3d_epa_per_play": 0.0,
        "off_pass_epa": 10.0,
        "off_plays": 100.0,
        "off_rush_epa": 4.0,
    })


def test_build_model_frame_drops_unplayed_games(monkeypatch):
    """Games without published scores must not reach the training frame.

    NaN > NaN is False, so an unplayed game used to be labelled a home loss --
    and with its spread already published it survived the dropna in
    model.build_frame, biasing training toward home losses.
    """
    games = pd.DataFrame([
        {"season": 2099, "week": 1, "game_type": "REG",
         "home_team": "AAA", "away_team": "BBB",
         "home_score": 24.0, "away_score": 17.0, "spread_line": -3.0},
        {"season": 2099, "week": 1, "game_type": "REG",
         "home_team": "CCC", "away_team": "DDD",
         "home_score": 10.0, "away_score": 20.0, "spread_line": 3.0},
        {"season": 2099, "week": 2, "game_type": "REG",
         "home_team": "AAA", "away_team": "CCC",
         "home_score": np.nan, "away_score": np.nan, "spread_line": -2.5},
    ])
    monkeypatch.setattr(features.ingest, "load", lambda name: games)
    monkeypatch.setattr(
        features, "team_ratings_asof",
        lambda season, week, refresh=False: _ratings(["AAA", "BBB", "CCC", "DDD"]),
    )
    features._RATINGS_CACHE.clear()

    frame = features.build_model_frame((2099,))

    assert len(frame) == 2, "the unplayed week-2 game must be excluded"
    assert set(frame["week"]) == {1}
    by_home = frame.set_index("home_team")["home_win"]
    assert by_home["AAA"] == 1  # 24-17 is a home win
    assert by_home["CCC"] == 0  # 10-20 is a home loss


def test_predict_2026_warns_when_every_game_is_unrated(monkeypatch):
    """Every game unrated must surface the warning, not a silent empty board."""
    schedule = pd.DataFrame([
        {"week": 1, "home_team": "AAA", "away_team": "BBB", "spread_line": np.nan},
        {"week": 1, "home_team": "CCC", "away_team": "DDD", "spread_line": np.nan},
    ])
    monkeypatch.setattr(model.ingest, "load_schedule", lambda season: schedule)
    # Ratings exist for the week but cover neither team, so game_feature_row
    # returns None for every game.
    monkeypatch.setattr(
        model.features, "team_ratings_asof",
        lambda season, week, refresh=False: _ratings(["XXX", "YYY"]),
    )
    with pytest.warns(UserWarning, match="game.*skipped"):
        out = model.predict_2026(week=1, auto_train=False)
    assert out.empty
