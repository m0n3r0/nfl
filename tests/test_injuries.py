"""Hermetic tests for the injury pipeline (src/injuries.py + weekly adjustments)."""

from __future__ import annotations

import pandas as pd
import pytest

from src import analysis, injuries, projections


def _write(path, season, rows):
    path.write_text("season,week,gsis_id,report_status\n" + "\n".join(
        f"{season},{week},{gsis},{status}" for week, gsis, status in rows))


def test_load_injury_flags_ignores_stale_season(tmp_path, monkeypatch):
    _write(tmp_path / "injuries_2025.csv", 2025, [(17, "00-1", "Out")])
    monkeypatch.setattr(injuries, "INJURY_GLOB", str(tmp_path / "injuries_*.csv"))

    with pytest.warns(UserWarning, match="STALE INJURY DATA"):
        assert injuries.load_injury_flags(2026) == {}


def test_load_injury_flags_latest_report_wins(tmp_path, monkeypatch):
    _write(tmp_path / "injuries_2026.csv", 2026, [(1, "00-1", "Questionable"), (2, "00-1", "Out"), (2, "00-2", "Doubtful")])
    monkeypatch.setattr(injuries, "INJURY_GLOB", str(tmp_path / "injuries_*.csv"))

    assert injuries.load_injury_flags(2026) == {"00-1": "Out", "00-2": "Doubtful"}


def test_load_injury_flags_blank_status_clears(tmp_path, monkeypatch):
    _write(tmp_path / "injuries_2026.csv", 2026, [(5, "00-1", "Out"), (6, "00-1", "")])
    monkeypatch.setattr(injuries, "INJURY_GLOB", str(tmp_path / "injuries_*.csv"))
    monkeypatch.setattr(projections, "project_players", lambda corpus: _players())

    assert injuries.load_injury_flags(2026) == {}
    corpus = _corpus([])
    corpus["injuries"] = injuries.build_injuries(2026)
    proj = projections.project_for_week(corpus, week=1).set_index("player_id")
    assert proj.loc["00-1", "proj_week"] == pytest.approx(10.0)


def test_load_injury_flags_absent_from_recent_window_clears(tmp_path, monkeypatch):
    _write(tmp_path / "injuries_2026.csv", 2026, [(1, "00-1", "Out"), (4, "00-2", "Questionable")])
    monkeypatch.setattr(injuries, "INJURY_GLOB", str(tmp_path / "injuries_*.csv"))
    monkeypatch.setattr(projections, "project_players", lambda corpus: _players())

    assert injuries.load_injury_flags(2026) == {"00-2": "Questionable"}
    corpus = _corpus([])
    corpus["injuries"] = injuries.build_injuries(2026)
    proj = projections.project_for_week(corpus, week=1).set_index("player_id")
    assert proj.loc["00-1", "proj_week"] == pytest.approx(10.0)
    assert proj.loc["00-2", "proj_week"] == pytest.approx(8.5)


def test_load_injury_flags_out_in_latest_week(tmp_path, monkeypatch):
    _write(tmp_path / "injuries_2026.csv", 2026, [(6, "00-1", "Out"), (6, "00-2", "")])
    monkeypatch.setattr(injuries, "INJURY_GLOB", str(tmp_path / "injuries_*.csv"))
    monkeypatch.setattr(projections, "project_players", lambda corpus: _players())

    assert injuries.load_injury_flags(2026) == {"00-1": "Out"}
    corpus = _corpus([])
    corpus["injuries"] = injuries.build_injuries(2026)
    proj = projections.project_for_week(corpus, week=1).set_index("player_id")
    assert proj.loc["00-1", "proj_week"] == 0.0
    board = analysis.weekly_matchups(corpus, week=1)
    assert "Out Guy" not in board["player_display_name"].tolist()


def test_load_injury_flags_out_in_prior_week_still_flagged(tmp_path, monkeypatch):
    _write(tmp_path / "injuries_2026.csv", 2026, [(4, "00-1", "Out"), (5, "00-2", "Questionable")])
    monkeypatch.setattr(injuries, "INJURY_GLOB", str(tmp_path / "injuries_*.csv"))

    assert injuries.load_injury_flags(2026) == {"00-1": "Out", "00-2": "Questionable"}


def test_load_injury_flags_ignores_stray_csv(tmp_path, monkeypatch):
    (tmp_path / "injuries_notes.csv").write_text("not,an,injury,file\n1,2,3\n")
    _write(tmp_path / "injuries_2026.csv", 2026, [(1, "00-1", "Out")])
    monkeypatch.setattr(injuries, "INJURY_GLOB", str(tmp_path / "injuries_[0-9]*.csv"))

    assert injuries.load_injury_flags(2026) == {"00-1": "Out"}


def test_load_injury_flags_no_files(tmp_path, monkeypatch):
    monkeypatch.setattr(injuries, "INJURY_GLOB", str(tmp_path / "injuries_*.csv"))

    assert injuries.load_injury_flags(2026) == {}
    empty = injuries.build_injuries(2026)
    assert list(empty.columns) == ["player_id", "injury_status"]
    assert empty.empty


def test_penalty_factor():
    assert injuries.penalty_factor("Out") == 0.0
    assert injuries.penalty_factor("IR") == 0.0
    assert injuries.penalty_factor("Reserve/PUP") == 0.0
    assert injuries.penalty_factor("Doubtful") == 0.60
    assert injuries.penalty_factor("Questionable") == 0.85
    assert injuries.penalty_factor("") == 1.0
    assert injuries.penalty_factor(None) == 1.0


def _corpus(injury_rows):
    schedule = pd.DataFrame([
        {"week": 1, "team": "KC", "opponent": "CIN", "home": True, "game_id": "g1"},
        {"week": 1, "team": "CIN", "opponent": "KC", "home": False, "game_id": "g1"},
    ])
    team_def = pd.DataFrame({"team": ["KC", "CIN"], "def_sos_factor": [0.0, 0.0]})
    return {"schedule_2026": schedule, "team_defense": team_def,
            "injuries": pd.DataFrame(injury_rows, columns=["player_id", "injury_status"])}


def _players():
    return pd.DataFrame([
        {"player_id": "00-1", "player_display_name": "Out Guy", "position": "RB",
         "last_team": "KC", "proj_ppg": 10.0, "team_sos": 0.0},
        {"player_id": "00-2", "player_display_name": "Q Guy", "position": "WR",
         "last_team": "KC", "proj_ppg": 10.0, "team_sos": 0.0},
        {"player_id": "00-3", "player_display_name": "Clean Guy", "position": "RB",
         "last_team": "CIN", "proj_ppg": 10.0, "team_sos": 0.0},
    ])


def test_project_for_week_applies_injury_factors(monkeypatch):
    monkeypatch.setattr(projections, "project_players", lambda corpus: _players())
    corpus = _corpus([("00-1", "Out"), ("00-2", "Questionable")])

    proj = projections.project_for_week(corpus, week=1).set_index("player_id")

    assert proj.loc["00-1", "proj_week"] == 0.0
    assert proj.loc["00-2", "proj_week"] == pytest.approx(8.5)
    assert proj.loc["00-3", "proj_week"] == pytest.approx(10.0)
    assert proj.loc["00-1", "injury_status"] == "Out"
    assert proj.loc["00-3", "injury_status"] == ""


def test_project_for_week_without_injuries_table(monkeypatch):
    monkeypatch.setattr(projections, "project_players", lambda corpus: _players())
    corpus = _corpus([])
    corpus["injuries"] = corpus["injuries"].iloc[0:0]

    proj = projections.project_for_week(corpus, week=1).set_index("player_id")

    assert proj.loc["00-1", "proj_week"] == pytest.approx(10.0)
    assert (proj["injury_status"] == "").all()


def test_weekly_matchups_excludes_out_players(monkeypatch):
    monkeypatch.setattr(projections, "project_players", lambda corpus: _players())
    corpus = _corpus([("00-1", "Out"), ("00-2", "Questionable")])

    board = analysis.weekly_matchups(corpus, week=1)

    assert board["player_display_name"].tolist() == ["Clean Guy", "Q Guy"]
    assert board.iloc[1]["injury_status"] == "Questionable"
    assert board.iloc[1]["proj_week"] == pytest.approx(8.5)
