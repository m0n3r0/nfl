"""Hermetic tests for the model training frame and in-season rating guards."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import features, model  # noqa: E402


def _ratings(teams):
    """Minimal as-of ratings frame with every column game_feature_row reads."""
    return pd.DataFrame({
        "team": list(teams),
        "off_epa_per_play": 0.05,
        "def_epa_allowed_per_play": 0.02,
        "off_rz_td_rate": 0.5,
        "off_3d_epa_per_play": 0.0,
        "off_pass_epa": 10.0,
        "off_plays": 100.0,
        "off_rush_epa": 4.0,
    })


def test_build_model_frame_drops_unplayed_games(monkeypatch):
    """Games without published scores must not reach the training frame.

    NaN > NaN is False, so an unplayed game used to be labelled a home loss --
    and with its spread already published it survived the dropna in
    model.build_frame, biasing training toward home losses.
    """
    games = pd.DataFrame([
        {"season": 2099, "week": 1, "game_type": "REG",
         "home_team": "AAA", "away_team": "BBB",
         "home_score": 24.0, "away_score": 17.0, "spread_line": -3.0},
        {"season": 2099, "week": 1, "game_type": "REG",
         "home_team": "CCC", "away_team": "DDD",
         "home_score": 10.0, "away_score": 20.0, "spread_line": 3.0},
        {"season": 2099, "week": 2, "game_type": "REG",
         "home_team": "AAA", "away_team": "CCC",
         "home_score": np.nan, "away_score": np.nan, "spread_line": -2.5},
    ])
    monkeypatch.setattr(features.ingest, "load", lambda name: games)
    monkeypatch.setattr(
        features, "team_ratings_asof",
        lambda season, week, refresh=False: _ratings(["AAA", "BBB", "CCC", "DDD"]),
    )
    features._RATINGS_CACHE.clear()

    frame = features.build_model_frame((2099,))

    assert len(frame) == 2, "the unplayed week-2 game must be excluded"
    assert set(frame["week"]) == {1}
    by_home = frame.set_index("home_team")["home_win"]
    assert by_home["AAA"] == 1  # 24-17 is a home win
    assert by_home["CCC"] == 0  # 10-20 is a home loss


def test_predict_2026_warns_when_every_game_is_unrated(monkeypatch):
    """Every game unrated must surface the warning, not a silent empty board."""
    schedule = pd.DataFrame([
        {"week": 1, "home_team": "AAA", "away_team": "BBB", "spread_line": np.nan},
        {"week": 1, "home_team": "CCC", "away_team": "DDD", "spread_line": np.nan},
    ])
    monkeypatch.setattr(model.ingest, "load_schedule", lambda season: schedule)
    # Ratings exist for the week but cover neither team, so game_feature_row
    # returns None for every game.
    monkeypatch.setattr(
        model.features, "team_ratings_asof",
        lambda season, week, refresh=False: _ratings(["XXX", "YYY"]),
    )
    with pytest.warns(UserWarning, match="game.*skipped"):
        out = model.predict_2026(week=1, auto_train=False)
    assert out.empty


# ---------- load_model() artifact guards (sklearn version skew) ----------


class _FakeEstimator:
    def predict_proba(self, x):
        return [[0.4, 0.6]]


def _valid_bundle(**extra):
    bundle = {
        "no_spread": _FakeEstimator(),
        "with_spread": _FakeEstimator(),
        "features": ["a"],
        "features_with_spread": ["a", "spread"],
    }
    bundle.update(extra)
    return bundle


def _dump(tmp_path, obj):
    import joblib

    path = tmp_path / "bundle.joblib"
    joblib.dump(obj, path)
    return path


def test_load_model_returns_none_for_missing_file(tmp_path):
    assert model.load_model(tmp_path / "nope.joblib") is None


def test_load_model_rejects_a_structurally_invalid_bundle(tmp_path):
    """A file that unpickles but is not a usable bundle must degrade, not crash.

    sklearn only guarantees pickle compat within a version; an artifact from
    another version can load into something wrong. predict_2026() would then
    die on a bare KeyError instead of falling back to the linear formula.
    """
    with pytest.warns(UserWarning, match="not a valid bundle"):
        assert model.load_model(_dump(tmp_path, {"features": []})) is None


def test_load_model_rejects_estimators_without_predict_proba(tmp_path):
    bogus = _valid_bundle(no_spread=object())
    with pytest.warns(UserWarning, match="predict_proba"):
        assert model.load_model(_dump(tmp_path, bogus)) is None


def test_load_model_accepts_a_valid_bundle(tmp_path, recwarn):
    bundle = model.load_model(_dump(tmp_path, _valid_bundle()))
    assert bundle is not None and bundle["features"] == ["a"]
    assert not [w for w in recwarn.list if "sklearn" in str(w.message)]


def test_load_model_warns_on_sklearn_version_mismatch(tmp_path):
    """A stamped bundle from another sklearn version must say so precisely."""
    path = _dump(tmp_path, _valid_bundle(sklearn_version="0.0.0"))
    with pytest.warns(UserWarning, match="trained with sklearn 0.0.0"):
        bundle = model.load_model(path)
    # warned but still served: the estimators unpickled fine and are usable
    assert bundle is not None


def test_train_and_persist_stamps_the_sklearn_version(tmp_path, monkeypatch):
    """New bundles carry sklearn_version so load_model can flag skew precisely."""
    import sklearn

    rows = [
        {"season": 2099, "week": 1 + i % 4,
         **{c: (i % 7) * 0.01 for c in features.FEATURE_COLS},
         "spread": (i % 5) - 2.0, "home_win": i % 2}
        for i in range(40)
    ]
    monkeypatch.setattr(model, "build_frame",
                        lambda seasons, refresh=False: pd.DataFrame(rows))
    path = tmp_path / "m.joblib"
    bundle = model.train_and_persist(seasons=(2099,), path=path)

    assert bundle["sklearn_version"] == sklearn.__version__
    assert path.exists()
    # the freshly written artifact passes load_model validation cleanly
    assert model.load_model(path) is not None


def _pbp_row(game_id, posteam, play_type, epa, success, down, yardline_100):
    """One offensive play with every column _offense_plays selects."""
    return {
        "play_type": play_type, "epa": epa, "game_id": game_id, "season": 2099,
        "week": 1, "posteam": posteam, "defteam": "OPP", "success": success,
        "down": down, "ydstogo": 7, "yardline_100": yardline_100,
        "rush": 1 if play_type == "run" else 0,
        "pass": 1 if play_type == "pass" else 0,
        "touchdown": 0, "interception": 0, "fumble": 0, "sack": 0,
        "qb_scramble": 0, "shotgun": 1, "no_huddle": 0,
    }


def test_strategy_breakdown_empty_split_is_null_not_nan():
    """A team with zero red-zone plays must get a null split, not NaN --
    json.dumps(allow_nan=True) would otherwise write literal NaN and make
    the whole strategy.json artifact invalid JSON."""
    import json

    pbp = pd.DataFrame([
        _pbp_row("g1", "AAA", "pass", 0.2, 1, 3, 50),
        _pbp_row("g1", "AAA", "run", -0.1, 0, 1, 80),
        _pbp_row("g1", "AAA", "pass", 0.4, 1, 1, 65),
    ])

    result = features.strategy_breakdown(pbp, "AAA")

    assert result["red_zone"] is None
    assert result["third_down"] is not None
    json.dumps(result, allow_nan=False)  # raises if any value is NaN
