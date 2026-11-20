"""Hermetic tests for tools/predictions_report.py — the offline artifact
producer behind the native Rust analytics pages (FD nation method)."""

import json

import pandas as pd
import pytest

from tools import predictions_report as pr


@pytest.fixture()
def fake_engine(monkeypatch):
    hist = pd.DataFrame({
        "player_id": ["p1", "p1", "p2"],
        "player_display_name": ["Alpha QB", "Alpha QB", "Beta RB"],
        "position": ["QB", "QB", "RB"],
        "season": [2024, 2025, 2025],
        "week": [1, 1, 2],
        "fantasy_points": [20.0, 24.0, 12.5],
    })
    proj = pd.DataFrame({
        "player_id": ["p1", "p2"],
        "player_display_name": ["Alpha QB", "Beta RB"],
        "position": ["QB", "RB"],
        "rank": [1, 2],
        "proj_ppg": [22.0, 12.5],
        "proj_total": [374.0, 212.5],
        "last_team": ["BUF", "DET"],
        "games": [17, 17],
        "baseline_ppg": [21.0, 12.0],
        "role_share": [0.6, 0.55],
        "team_sos": [0.1, -0.2],
    })
    monkeypatch.setattr(pr.corpus, "build", lambda preset=None: {"weekly_history": hist})
    monkeypatch.setattr(pr.projections, "project_players", lambda c: proj)
    monkeypatch.setattr(pr.model, "train_and_evaluate", lambda a, b: {
        "model_no_spread": {"accuracy": 0.612, "log_loss": 0.654, "brier": 0.231},
        "model_with_spread": {"accuracy": 0.68, "log_loss": 0.616, "brier": 0.214},
        "vegas_baseline_accuracy": 0.684, "n_test": 544,
    })
    monkeypatch.setattr(pr.model, "time_series_cv", lambda seasons: {
        "mean_accuracy": 0.663,
        "folds": [{"test_season": 2024, "accuracy": 0.695}],
    })
    monkeypatch.setattr(pr.model, "predict_2026", lambda week=None: pd.DataFrame({
        "week": [1], "home_team": ["BUF"], "away_team": ["KC"],
        "home_win_prob": [0.62], "epa_diff": [0.08], "spread": [None],
        "model": ["no_spread"],
    }))

    def ratings(season, week, refresh=False):
        if season == 2022 and week == 1:
            return pd.DataFrame()  # no strictly-prior season
        return pd.DataFrame({"team": ["BUF"], "off_epa_per_play": [0.12],
                             "def_epa_allowed_per_play": [None]})
    monkeypatch.setattr(pr.features, "team_ratings_asof", ratings)
    monkeypatch.setattr(pr.ingest, "load_pbp",
                        lambda season: pd.DataFrame({"posteam": ["BUF", "KC"]}))
    monkeypatch.setattr(pr.features, "strategy_breakdown",
                        lambda pbp, team: {"overall": {"epa_per_play": 0.1,
                                                       "success_rate": 0.45, "n": 100}})
    monkeypatch.setattr(pr.analysis, "sos_ranking",
                        lambda c: pd.DataFrame({"rank": [1], "team": ["BUF"], "sos": [0.3]}))
    return hist


def test_build_all_writes_every_artifact(tmp_path, fake_engine):
    summary = pr.build_all(tmp_path)
    assert summary["errors"] == {}
    assert set(summary["sections"]) == {
        "dashboard", "modelcard", "players", "predictions", "ratings", "strategy", "sos"}
    for name in ("dashboard.json", "players.json", "predictions.json",
                 "ratings.json", "strategy.json", "sos.json", "modelcard.json"):
        payload = json.loads((tmp_path / name).read_text())  # valid JSON, no NaN
        assert payload["generated_at"]


def test_dashboard_and_modelcard_shapes(tmp_path, fake_engine):
    pr.build_all(tmp_path)
    d = json.loads((tmp_path / "dashboard.json").read_text())
    assert d["projections"][0]["player_display_name"] == "Alpha QB"
    assert d["backtest"]["vegas"] == 0.684
    assert d["backtest"]["cv_folds"][0]["test_season"] == 2024
    mc = json.loads((tmp_path / "modelcard.json").read_text())
    assert mc["evaluation"]["n_test"] == 544
    assert mc["cv"]["mean_accuracy"] == 0.663


def test_player_files_history_and_projection(tmp_path, fake_engine):
    pr.build_all(tmp_path)
    p1 = json.loads((tmp_path / "players" / "p1.json").read_text())
    assert p1["name"] == "Alpha QB" and p1["pos"] == "QB"
    assert [h["season"] for h in p1["history"]] == [2024, 2025]
    assert p1["history"][0]["ppg"] == 20.0
    assert p1["projection"]["proj_ppg"] == 22.0
    p2 = json.loads((tmp_path / "players" / "p2.json").read_text())
    assert p2["projection"]["proj_total"] == 212.5


def test_ratings_empty_week1_2022_and_nan_filled(tmp_path, fake_engine):
    pr.build_all(tmp_path)
    r = json.loads((tmp_path / "ratings.json").read_text())
    assert r["ratings"]["2022-1"] == []          # honest empty, not fabricated
    row = r["ratings"]["2025-3"][0]
    assert row["def_epa_allowed_per_play"] == 0  # fillna(0) like the Flask page
    assert r["seasons"] == sorted(set(r["seasons"]))


def test_strategy_all_teams_and_seasons(tmp_path, fake_engine):
    pr.build_all(tmp_path)
    s = json.loads((tmp_path / "strategy.json").read_text())
    for season in s["seasons"]:
        assert set(s["strategy"][str(season)]) == {"BUF", "KC"}


def test_section_failure_is_fail_soft(tmp_path, fake_engine, monkeypatch):
    def boom(week=None):
        raise RuntimeError("model unavailable")
    monkeypatch.setattr(pr.model, "predict_2026", boom)
    summary = pr.build_all(tmp_path)
    assert "predictions" in summary["errors"]
    assert not (tmp_path / "predictions.json").exists()
    # the other sections still landed
    assert (tmp_path / "players.json").exists()
    assert (tmp_path / "sos.json").exists()


def test_predictions_null_spread_stays_null(tmp_path, fake_engine):
    pr.build_all(tmp_path)
    p = json.loads((tmp_path / "predictions.json").read_text())
    assert p["predictions"][0]["spread"] is None
    assert p["weeks"] == list(range(1, 19))