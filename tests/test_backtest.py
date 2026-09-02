"""Hermetic tests for historical fantasy projection backtests."""

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.backtest import backtest_metrics, project_historical_season


def weekly():
    rows = []
    for player, position, old, actual in [
        ("a", "QB", 20.0, 22.0), ("b", "QB", 10.0, 11.0),
        ("c", "RB", 15.0, 14.0), ("d", "RB", 5.0, 6.0),
    ]:
        for season in (2023, 2024):
            for week in range(1, 5):
                rows.append({"player_id": player, "player_display_name": player, "position": position, "season": season, "week": week, "fantasy_points": old})
        for week in range(1, 5):
            rows.append({"player_id": player, "player_display_name": player, "position": position, "season": 2025, "week": week, "fantasy_points": actual})
    return pd.DataFrame(rows)


def test_backtest_uses_only_pre_target_rows_and_counts_actual_games():
    frame = project_historical_season(weekly(), 2025, {2023: 1.0, 2024: 1.5})
    top = frame.set_index("player_id").loc["a"]
    assert top["games"] == 8
    assert top["actual_games"] == 4
    assert top["model_ppg"] < top["actual_ppg"]


def test_metrics_report_rank_error_and_top_n_recall():
    frame = project_historical_season(weekly(), 2025, {2023: 1.0, 2024: 1.5})
    metrics = backtest_metrics(frame)
    overall = metrics[0]
    assert overall.scope == "ALL"
    assert overall.players == 4
    assert overall.spearman > 0.7
    assert overall.mae_ppg > 0
    assert {metric.scope for metric in metrics} == {"ALL", "QB", "RB"}
