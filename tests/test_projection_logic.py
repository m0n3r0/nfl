"""Hermetic regression tests for projection aggregation and priors."""

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import projections  # noqa: E402


def _corpus():
    weekly = pd.DataFrame([
        {"player_id": "v", "player_display_name": "Veteran", "position": "RB", "recent_team": "OLD", "season": 2024, "week": 1, "fantasy_points": 10.0},
        {"player_id": "v", "player_display_name": "Veteran", "position": "RB", "recent_team": "OLD", "season": 2025, "week": 1, "fantasy_points": 20.0},
        {"player_id": "v", "player_display_name": "Veteran", "position": "RB", "recent_team": "NEW", "season": 2025, "week": 2, "fantasy_points": 20.0},
        {"player_id": "o", "player_display_name": "Other", "position": "RB", "recent_team": "NEW", "season": 2025, "week": 1, "fantasy_points": 10.0},
    ])
    roles = pd.DataFrame([
        {"gsis_id": "v", "team": "NEW", "role_share": 0.60},
        {"gsis_id": "o", "team": "NEW", "role_share": 0.60},
        {"gsis_id": "r", "team": "NEW", "role_share": 0.60},
    ])
    return {
        "weekly_history": weekly,
        "depth_roles": roles,
        "schedule_2026": pd.DataFrame([{"team": "NEW", "opponent": "DEF"}]),
        "team_defense": pd.DataFrame([{"team": "DEF", "def_sos_factor": 0.0}]),
        "players": pd.DataFrame([{
            "gsis_id": "r", "display_name": "Rookie", "position": "RB",
            "draft_year": 2026, "draft_team": "NEW", "draft_round": 1,
        }]),
    }


def test_team_change_keeps_history_and_counts_rows(monkeypatch):
    monkeypatch.setattr(projections, "HISTORY_SEASONS", (2024, 2025))
    result = projections.project_players(_corpus())
    veteran = result[result["player_id"] == "v"].iloc[0]

    assert veteran["last_team"] == "NEW"
    assert veteran["games"] == 3
    assert veteran["expected_games"] < 17


def test_first_round_starter_rookie_is_not_capped_below_mean(monkeypatch):
    monkeypatch.setattr(projections, "HISTORY_SEASONS", (2024, 2025))
    result = projections.project_players(_corpus())
    rookie = result[result["player_id"] == "r"].iloc[0]

    assert rookie["is_rookie"]
    assert rookie["proj_ppg"] > rookie["pos_mean"]