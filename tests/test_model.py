"""Tests for the win-probability model (real backtest against cached data)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import model  # noqa: E402


def test_backtest_runs_and_is_sane():
    res = model.train_and_backtest()
    # we have a real holdout
    assert res["n_test"] > 200
    # model accuracy is in a believable range and not degenerate
    assert 0.5 < res["model_accuracy"] < 0.85
    # vegas baseline is reported
    assert 0.5 < res["vegas_baseline_accuracy"] < 0.85


def test_predict_2026_returns_week1():
    preds = model.predict_2026(week=1)
    assert len(preds) == 16  # 16 games in week 1
    assert (preds["home_win_prob"] >= 0).all()
    assert (preds["home_win_prob"] <= 1).all()


if __name__ == "__main__":
    test_backtest_runs_and_is_sane()
    test_predict_2026_returns_week1()
    print("All model tests passed.")
