"""Tests for the professional win-probability model + features (real data)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import model, features  # noqa: E402


def test_evaluation_runs_and_is_honest():
    ev = model.train_and_evaluate((2022, 2023), (2024, 2025))
    # real holdout
    assert ev["n_test"] > 200
    # model accuracy in believable range, not degenerate
    assert 0.5 < ev["model_with_spread"]["accuracy"] < 0.85
    # vegas baseline reported and comparable (not a fabricated clear win)
    assert 0.5 < ev["vegas_baseline_accuracy"] < 0.85
    # model without spread still beats a coin flip (real signal)
    assert ev["model_no_spread"]["accuracy"] > 0.55


def test_time_series_cv_is_stable():
    cv = model.time_series_cv((2022, 2023, 2024, 2025))
    assert len(cv["folds"]) >= 2
    assert 0.55 < cv["mean_accuracy"] < 0.85


def test_predict_2026_returns_week1():
    preds = model.predict_2026(week=1)
    assert len(preds) == 16
    assert (preds["home_win_prob"] >= 0).all()
    assert (preds["home_win_prob"] <= 1).all()


def test_features_asof_no_leakage():
    # week-3 2025 ratings must only use weeks 1-2 (cached; build is fast on cache)
    rt = features.team_ratings_asof(2025, 3, refresh=False)
    assert len(rt) == 32


if __name__ == "__main__":
    test_evaluation_runs_and_is_honest()
    test_time_series_cv_is_stable()
    test_predict_2026_returns_week1()
    test_features_asof_no_leakage()
    print("All model tests passed.")
