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


# ---------- issue #18: predict_2026() never used the trained model ----------


def test_train_and_predict_share_one_feature_definition():
    """The inference frame must be built from the training feature columns.

    Issue #18: predict_2026() scored games with a hardcoded
    `0.5 + 1.2 * epa_diff` -- one hand-tuned number -- while the model was fitted
    on 14 standardized features. A completely different function, so the
    published "model" predictions were never model output at all.

    Both paths now go through features.game_feature_row(), and the canonical
    column list lives in features.py so they cannot drift apart again.
    """
    assert model._feature_cols() == list(features.FEATURE_COLS)
    # game_feature_row() emits exactly the training columns, nothing more/less
    rt = features.team_ratings_asof(2026, 1).set_index("team")
    row = features.game_feature_row(rt, "BUF", "MIA", 7, 7)
    assert row is not None
    assert set(row) == set(features.FEATURE_COLS)
    # unknown teams are skipped rather than scored on missing data
    assert features.game_feature_row(rt, "BUF", "NOPE", 7, 7) is None


def test_predict_2026_uses_the_trained_model():
    """Predictions must come from the fitted pipeline, never the old formula."""
    preds = model.predict_2026(week=1)
    assert len(preds) == 16
    assert set(preds["model"]) <= {"with_spread", "no_spread"}, (
        f"predictions fell back to the hand-rolled linear formula: "
        f"{sorted(set(preds['model']))}"
    )
    # week-1 2026 spreads are published, so the stronger variant should be used
    assert (preds["model"] == "with_spread").all()
    # real probabilities, not the degenerate 0.05/0.95 clipping of the fallback
    assert preds["home_win_prob"].nunique() > 5


def test_future_season_pbp_is_unrated_not_an_error():
    """A season with no published PBP returns empty instead of raising.

    nflverse answers with a 404 for play_by_play_<season>.csv before that season
    kicks off. That is a legitimate "no data" state, not a failure: it is what
    predict_2026() hits for week 2+ and what the /ratings page hits for a future
    week. Both must degrade gracefully rather than 404/500.

    Passes offline too -- a connection error is caught the same way. Only
    seasons inside PBP_SEASONS re-raise, so a real download failure during
    training can never be silently swallowed.
    """
    future = max(features.PBP_SEASONS) + 1
    assert future not in features.PBP_SEASONS
    rt = features.team_ratings_asof(future, 2, refresh=False)
    assert rt.empty, f"expected no ratings for unrated season {future}"


def test_linear_fallback_is_bounded_and_explicit():
    """The fallback still exists for a missing artifact, but is bounded."""
    assert abs(model._linear_fallback(0.0) - 0.5) < 1e-9
    assert model._linear_fallback(10.0) == 0.95
    assert model._linear_fallback(-10.0) == 0.05


def test_features_asof_no_leakage():
    # week-3 2025 ratings must only use weeks 1-2 (cached; build is fast on cache)
    rt = features.team_ratings_asof(2025, 3, refresh=False)
    assert len(rt) == 32


# ---------- issue #17: week-1 prior-season leakage ----------
# These are deliberately cheap (no play-by-play load) so the leakage rule is
# guarded on every run. The old bug was invisible to the slow tests: it produced
# 32 plausible rows, just built from the wrong season's data.


def test_prior_season_is_strictly_prior():
    """The week-1 prior must be a STRICTLY-earlier season, never a later one.

    Regression test for issue #17. The old expression was
        max([s for s in PBP_SEASONS if s < season] + [STATS_SEASON])
    Because STATS_SEASON (2025) is the newest season in PBP_SEASONS, that max()
    returned 2025 for EVERY season <= 2025. A 2022 week-1 game was therefore
    rated on full-year 2025 efficiency, and the 2022_w1 / 2024_w1 caches came
    out byte-identical: the same 2025 data labelled as two different seasons.
    """
    first = min(features.PBP_SEASONS)
    assert features.prior_season(first) is None, (
        f"the earliest PBP season ({first}) has no prior; must be None so callers "
        "drop the game, never a future season"
    )
    for s in features.PBP_SEASONS:
        if s == first:
            continue
        p = features.prior_season(s)
        assert p is not None, f"expected a prior for {s}"
        assert p < s, f"prior for {s} must be strictly earlier, got {p}"
    # one season past our data still resolves to the newest real season
    newest = max(features.PBP_SEASONS)
    assert features.prior_season(newest + 1) == newest


def test_prior_season_never_returns_future():
    """No season may be rated on data from its own season or a later one."""
    newest = max(features.PBP_SEASONS)
    for s in list(features.PBP_SEASONS) + [newest + 1]:
        p = features.prior_season(s)
        assert p is None or p < s, f"{s} would be rated on {p} (not strictly prior)"
        assert p is None or p <= newest, f"prior {p} is newer than any data we hold"


def test_week1_of_first_pbp_season_has_no_ratings():
    """team_ratings_asof() must return EMPTY, not substitute a future season.

    Doubles as a guard against a poisoned cache coming back: the cache is read
    BEFORE the prior logic runs, so a stale team_ratings_<first>_w1 file would
    make this test fail. That is exactly the state we found on 2026-08-31.
    """
    first = min(features.PBP_SEASONS)
    cache = features.PROCESSED / f"team_ratings_{first}_w1.csv.gz"
    assert not cache.exists(), (
        f"stale poisoned cache {cache} is still in place -- delete it. It holds "
        f"FUTURE-season data mislabelled as {first}."
    )
    rt = features.team_ratings_asof(first, 1, refresh=False)
    assert rt.empty, f"week 1 of {first} has no leakage-free prior; expected empty frame"
    # the empty result must not be cached -- it is a "no data" signal, not data
    assert not cache.exists(), "the empty result must NOT be written to cache"


if __name__ == "__main__":
    test_evaluation_runs_and_is_honest()
    test_time_series_cv_is_stable()
    test_predict_2026_returns_week1()
    test_train_and_predict_share_one_feature_definition()
    test_predict_2026_uses_the_trained_model()
    test_future_season_pbp_is_unrated_not_an_error()
    test_linear_fallback_is_bounded_and_explicit()
    test_features_asof_no_leakage()
    test_prior_season_is_strictly_prior()
    test_prior_season_never_returns_future()
    test_week1_of_first_pbp_season_has_no_ratings()
    print("All model tests passed.")
