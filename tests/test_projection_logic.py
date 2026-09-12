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


def test_season_weights_match_history_seasons():
    assert projections._SEASON_WEIGHTS == {
        2022: 1.0, 2023: 1.5, 2024: 2.0, 2025: 2.5, 2026: 3.0,
    }
    assert tuple(projections._SEASON_WEIGHTS) == tuple(projections.HISTORY_SEASONS)


def test_current_season_availability_uses_elapsed_weeks(monkeypatch):
    """One appearance in a part-played season must not dent expected games.

    With 2026 only one week old, measuring a durable veteran's single 2026
    game against a full 34-game slate (17 x 2 seasons) dropped expected_games
    to 13.0, while a player with no 2026 rows at all kept 17.0 -- a ~30%
    proj_total boost for being inactive. The current season's denominator is
    the weeks elapsed (max week observed), not 17.
    """
    monkeypatch.setattr(projections, "STATS_SEASON", 2026)
    weekly = pd.DataFrame(
        [{"player_id": "a", "player_display_name": "Active", "position": "RB",
          "recent_team": "NEW", "season": 2025, "week": w, "fantasy_points": 10.0}
         for w in range(1, 18)]
        + [{"player_id": "a", "player_display_name": "Active", "position": "RB",
            "recent_team": "NEW", "season": 2026, "week": 1, "fantasy_points": 10.0}]
        + [{"player_id": "b", "player_display_name": "Inactive", "position": "RB",
            "recent_team": "NEW", "season": 2025, "week": w, "fantasy_points": 10.0}
           for w in range(1, 18)]
    )
    corpus = {
        "weekly_history": weekly,
        "depth_roles": pd.DataFrame([
            {"gsis_id": "a", "team": "NEW", "role_share": 0.60},
            {"gsis_id": "b", "team": "NEW", "role_share": 0.60},
        ]),
        "schedule_2026": pd.DataFrame([{"team": "NEW", "opponent": "DEF"}]),
        "team_defense": pd.DataFrame([{"team": "DEF", "def_sos_factor": 0.0}]),
    }
    result = projections.project_players(corpus).set_index("player_id")

    assert result.loc["a", "expected_games"] == 17.0
    assert result.loc["b", "expected_games"] == 17.0

def _negative_baseline_corpus():
    rows = [
        {"player_id": "p", "player_display_name": "Punter", "position": "P",
         "recent_team": "NEW", "season": 2025, "week": w, "fantasy_points": -1.0}
        for w in range(1, 21)
    ]
    rows.append({"player_id": "v", "player_display_name": "Veteran", "position": "RB",
                 "recent_team": "NEW", "season": 2025, "week": 1, "fantasy_points": 20.0})
    schedule = pd.DataFrame([
        {"team": "NEW", "opponent": "DEF", "week": 1},
        {"team": "DEF", "opponent": "NEW", "week": 1},
        {"team": "NEW", "opponent": "MID", "week": 2},
        {"team": "MID", "opponent": "NEW", "week": 2},
    ])
    roles = pd.DataFrame([
        {"gsis_id": "p", "team": "NEW", "role_share": 0.60},
        {"gsis_id": "v", "team": "NEW", "role_share": 0.60},
    ])
    return {
        "weekly_history": pd.DataFrame(rows),
        "depth_roles": roles,
        "schedule_2026": schedule,
        "team_defense": pd.DataFrame([
            {"team": "DEF", "def_sos_factor": -1.0},
            {"team": "MID", "def_sos_factor": 0.0},
        ]),
    }


def test_negative_baseline_floors_at_zero_not_negative(monkeypatch):
    monkeypatch.setattr(projections, "HISTORY_SEASONS", (2025,))
    result = projections.project_players(_negative_baseline_corpus())
    punter = result[result["player_id"] == "p"].iloc[0]

    assert punter["baseline_ppg"] < 0
    assert punter["proj_ppg"] == 0.0
    assert punter["proj_total"] == 0.0


def test_week_projection_never_negative_and_shutout_sos_zeroes(monkeypatch):
    monkeypatch.setattr(projections, "HISTORY_SEASONS", (2025,))
    corp = _negative_baseline_corpus()

    shutout = projections.project_for_week(corp, 1)  # NEW faces DEF (-1.0)
    assert (shutout["proj_week"] >= 0).all()
    assert shutout[shutout["player_id"] == "v"].iloc[0]["proj_week"] == 0.0

    normal = projections.project_for_week(corp, 2)  # NEW faces MID (0.0)
    punter = normal[normal["player_id"] == "p"].iloc[0]
    veteran = normal[normal["player_id"] == "v"].iloc[0]
    assert punter["proj_week"] == 0.0  # clamped at source, not negative
    assert veteran["proj_week"] > 0.0  # clamp leaves real projections untouched
