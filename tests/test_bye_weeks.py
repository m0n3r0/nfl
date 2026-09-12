"""Hermetic tests for bye-week handling in weekly projections and boards."""

from __future__ import annotations

import pandas as pd

from src import analysis, projections


def schedule():
    rows = []
    for week, teams in ((1, ("KC", "SF", "CIN", "TB")), (2, ("KC", "SF"))):
        for team in teams:
            rows.append({"week": week, "team": team, "opponent": "X", "home": True,
                         "game_id": f"g{week}{team}"})
    return pd.DataFrame(rows)


def players():
    return pd.DataFrame([
        {"player_display_name": "A", "last_team": "KC", "position": "RB", "proj_week": 12.0},
        {"player_display_name": "B", "last_team": "CIN", "position": "WR", "proj_week": 10.0},
        {"player_display_name": "C", "last_team": "DET", "position": "RB", "proj_week": 9.5},
    ])


def test_mark_byes_zeros_projection_and_flags():
    marked = projections._mark_byes(players(), schedule(), week=2)

    assert marked.set_index("player_display_name")["on_bye"].to_dict() == {
        "A": False, "B": True, "C": True}
    assert marked.set_index("player_display_name")["proj_week"].to_dict() == {
        "A": 12.0, "B": 0.0, "C": 0.0}


def test_weekly_matchups_excludes_bye_players(monkeypatch):
    proj = players().assign(position=["RB", "WR", "RB"], week_sos=0.0)
    proj = projections._mark_byes(proj, schedule(), week=2)
    monkeypatch.setattr(projections, "project_for_week", lambda corpus, week: proj)

    board = analysis.weekly_matchups({"schedule_2026": schedule()}, week=2)

    assert board["player_display_name"].tolist() == ["A"]
    assert board.iloc[0]["opponent"] == "X"
