"""Fast regression tests for corpus filtering and defensive baselines."""

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import corpus  # noqa: E402


def _stats(season_type):
    return pd.DataFrame([
        {
            "player_id": "p1",
            "player_display_name": "Player One",
            "position": "RB",
            "team": "AAA",
            "week": 1,
            "season_type": season_type,
            "rushing_yards": 100,
        }
    ])


def test_weekly_history_excludes_postseason(monkeypatch):
    monkeypatch.setattr(corpus, "HISTORY_SEASONS", (2025,))
    monkeypatch.setattr(corpus.ingest, "load", lambda name: _stats("POST"))

    result = corpus._weekly_history(preset="standard")

    assert result.empty


def test_team_defense_uses_recent_scored_games_only(monkeypatch):
    games = pd.DataFrame([
        {"season": 2023, "game_type": "REG", "away_team": "OLD", "home_team": "AAA", "home_score": 99, "away_score": 10},
        {"season": 2024, "game_type": "REG", "away_team": "AAA", "home_team": "BBB", "home_score": 20, "away_score": 14},
        {"season": 2025, "game_type": "POST", "away_team": "BBB", "home_team": "AAA", "home_score": 17, "away_score": 21},
        {"season": 2026, "game_type": "REG", "away_team": "AAA", "home_team": "BBB", "home_score": None, "away_score": None},
    ])
    monkeypatch.setattr(corpus.ingest, "load", lambda name: games)

    result = corpus.build_team_defense(schedule_season=2026)

    assert set(result["team"]) == {"AAA", "BBB"}
    assert "OLD" not in set(result["team"])
    assert result.set_index("team").loc["AAA", "games"] == 2
    assert result.set_index("team").loc["BBB", "games"] == 2