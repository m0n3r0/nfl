"""Professional win-probability model with honest evaluation.

Uses leakage-safe team-efficiency features from src.features (as-of-game PBP
ratings), trains a calibrated logistic-regression baseline, and evaluates with:
  * a strict time-based train/test split (never leak future games),
  * time-series cross-validation for stability,
  * probability calibration (Platt),
  * explicit reporting of accuracy + log-loss BOTH with and without the Vegas
    spread as a feature, benchmarked against the Vegas-favorite baseline.

This is an analytical model, not a betting system. Beating the closing spread
is genuinely hard; we report results honestly rather than overstating them.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from . import ingest, features
from .config import PBP_SEASONS, SCHEDULE_SEASON, STATS_SEASON


def _feature_cols():
    # Canonical list lives in features.py so the training frame and the
    # inference frame are built from the same definition.
    return list(features.FEATURE_COLS)


def build_frame(seasons, refresh: bool = False) -> pd.DataFrame:
    mf = features.build_model_frame(seasons, refresh=refresh)
    mf = mf.dropna(subset=_feature_cols() + ["spread", "home_win"])
    # model-only features exclude the spread; model+spread includes it
    mf["epa_diff"] = (mf["home_off_epa_pp"] - mf["away_off_epa_pp"]) - (mf["home_def_epa_pp"] - mf["away_def_epa_pp"])
    return mf


# Persisted fitted models. Lives under data/processed/ (gitignored, like the
# rating caches) -- it is a build artifact, not source.
MODEL_PATH = features.PROCESSED / "win_prob_model.joblib"

# Fallback only, when the fitted artifact is unavailable. Kept so predict_2026()
# degrades to the old behaviour instead of raising, but it is NOT the model.
_LINEAR_FALLBACK_SLOPE = 1.2
_LINEAR_FALLBACK_CLIP = (0.05, 0.95)


def _make_estimator():
    """Calibrated (Platt) logistic regression on standardized features."""
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    base = Pipeline([("scaler", StandardScaler()),
                     ("lr", LogisticRegression(max_iter=2000))])
    return CalibratedClassifierCV(base, method="sigmoid", cv=5)


def train_and_persist(seasons=None, path=MODEL_PATH, refresh: bool = False) -> dict:
    """Fit both model variants on all completed seasons and save them.

    Trains two estimators over the SAME leakage-safe features:
      * `no_spread`    -- the 14 EPA/rest features only
      * `with_spread`  -- those plus the Vegas spread (more accurate, but only
        usable for games whose spread is already published)
    Returns the in-memory bundle; it is also written to `path`.
    """
    seasons = tuple(seasons) if seasons is not None else tuple(PBP_SEASONS)
    data = build_frame(seasons, refresh=refresh)
    if data.empty:
        raise RuntimeError(f"no training rows for seasons {seasons}")

    feat = _feature_cols()
    y = data["home_win"].values

    est_no = _make_estimator()
    est_no.fit(data[feat].values, y)

    feat_s = feat + ["spread"]
    est_yes = _make_estimator()
    est_yes.fit(data[feat_s].values, y)

    bundle = {
        "no_spread": est_no,
        "with_spread": est_yes,
        "features": feat,
        "features_with_spread": feat_s,
        "seasons": list(seasons),
        "n_train": int(len(data)),
    }

    import joblib
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, path)
    bundle["path"] = str(path)
    # serve the freshly fitted model from cache too
    _MODEL_CACHE[str(Path(path).resolve())] = bundle
    return bundle


# Deserializing the two calibrated estimators costs ~2s and importing joblib
# several more, so the bundle is memoized. Without this every web request
# re-unpickled the model for no reason.
_MODEL_CACHE: dict[str, dict | None] = {}


def load_model(path=MODEL_PATH):
    """Return the persisted bundle, or None if it has not been trained yet."""
    key = str(Path(path).resolve())
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key]

    import joblib
    if not Path(path).exists():
        _MODEL_CACHE[key] = None
        return None
    try:
        bundle = joblib.load(path)
    except Exception:
        # A half-written or version-incompatible artifact must not brick the CLI;
        # callers fall back to the linear formula.
        bundle = None
    _MODEL_CACHE[key] = bundle
    return bundle


def _metrics(y_true, proba):
    from sklearn.metrics import log_loss, accuracy_score, brier_score_loss
    pred = (proba >= 0.5).astype(int)
    return {
        "accuracy": round(float(accuracy_score(y_true, pred)), 4),
        "log_loss": round(float(log_loss(y_true, proba)), 4),
        "brier": round(float(brier_score_loss(y_true, proba)), 4),
    }


def train_and_evaluate(train_seasons, test_seasons, refresh: bool = False) -> dict:
    """Train on train_seasons, evaluate on test_seasons (time split)."""
    data = build_frame(train_seasons + test_seasons, refresh=refresh)
    train = data[data["season"].isin(train_seasons)]
    test = data[data["season"].isin(test_seasons)]

    feat = _feature_cols()
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.calibration import CalibratedClassifierCV

    base = Pipeline([("scaler", StandardScaler()), ("lr", LogisticRegression(max_iter=2000))])
    cal = CalibratedClassifierCV(base, method="sigmoid", cv=5)

    # model WITHOUT spread
    Xtr, ytr = train[feat].values, train["home_win"].values
    Xte, yte = test[feat].values, test["home_win"].values
    cal.fit(Xtr, ytr)
    p_no = cal.predict_proba(Xte)[:, 1]
    m_no = _metrics(yte, p_no)

    # model WITH spread
    feat_s = feat + ["spread"]
    cal2 = CalibratedClassifierCV(Pipeline([("scaler", StandardScaler()),
                                             ("lr", LogisticRegression(max_iter=2000))]),
                                   method="sigmoid", cv=5)
    cal2.fit(train[feat_s].values, ytr)
    p_yes = cal2.predict_proba(test[feat_s].values)[:, 1]
    m_yes = _metrics(yte, p_yes)

    # vegas-favorite baseline (pick home if spread > 0)
    vegas = round(float((test["spread"] > 0).astype(int).eq(test["home_win"]).mean()), 4)

    return {
        "n_train": len(train), "n_test": len(test),
        "model_no_spread": m_no, "model_with_spread": m_yes,
        "vegas_baseline_accuracy": vegas,
        "test_seasons": list(test_seasons),
    }


def time_series_cv(seasons, refresh: bool = False) -> dict:
    """Expanding-window CV: each later season is tested on all prior seasons."""
    data = build_frame(seasons, refresh=refresh)
    feat = _feature_cols() + ["spread"]
    rows = []
    seasons_sorted = sorted(seasons)
    for i in range(1, len(seasons_sorted)):
        tr = data[data["season"].isin(seasons_sorted[:i])]
        te = data[data["season"].isin([seasons_sorted[i]])]
        if len(tr) < 50 or len(te) < 50:
            continue
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler
        clf = Pipeline([("scaler", StandardScaler()), ("lr", LogisticRegression(max_iter=2000))])
        clf.fit(tr[feat].values, tr["home_win"].values)
        proba = clf.predict_proba(te[feat].values)[:, 1]
        from sklearn.metrics import accuracy_score, log_loss
        acc = float(accuracy_score(te["home_win"].values, (proba >= 0.5).astype(int)))
        ll = float(log_loss(te["home_win"].values, proba))
        rows.append({"test_season": seasons_sorted[i], "accuracy": round(acc, 4), "log_loss": round(ll, 4),
                     "n": len(te)})
    return {"folds": rows, "mean_accuracy": round(float(np.mean([r["accuracy"] for r in rows])), 4)}


def _linear_fallback(epa_diff: float) -> float:
    """Old hand-rolled formula. Used ONLY when the fitted artifact is missing.

    It is a function of one number and is not the trained model -- every row it
    produces is tagged `model="fallback_linear"` so it can never be mistaken
    for a real prediction.
    """
    lo, hi = _LINEAR_FALLBACK_CLIP
    return float(np.clip(0.5 + _LINEAR_FALLBACK_SLOPE * epa_diff, lo, hi))


def predict_2026(week: int = None, auto_train: bool = True) -> pd.DataFrame:
    """2026 win probabilities from the trained, calibrated model.

    Each game is scored with ratings **as of that game's own week**, using the
    same 14 leakage-safe features the model was fitted on (see
    `features.game_feature_row`). Rows whose spread is already published use the
    more accurate with-spread variant; the rest use the EPA-only variant. The
    `model` column records which one produced each row.

    Only week 1 is computable before the season starts: weeks 2+ need in-season
    2026 play-by-play to build as-of ratings, and `team_ratings_asof()` returns
    empty rather than reaching forward into the future.
    """
    sched = ingest.load_schedule(season=SCHEDULE_SEASON)
    if week is not None:
        sched = sched[sched["week"] == week]
    if sched.empty:
        return pd.DataFrame()

    bundle = load_model()
    if bundle is None and auto_train:
        bundle = train_and_persist()

    rows = []
    skipped_weeks = []
    # One ratings lookup per week, not per game (issue #24), and each week gets
    # its own as-of ratings rather than reusing week 1's for the whole season.
    for wk, group in sched.groupby("week"):
        wk = int(wk)
        ratings = features.team_ratings_asof(SCHEDULE_SEASON, wk, refresh=False)
        if ratings is None or ratings.empty:
            # Before the season starts only week 1 is computable: it uses the
            # prior season, while later weeks need in-season play-by-play that
            # does not exist yet. Skip them rather than scoring a week-12 game
            # on week-1 knowledge, but say so loudly.
            skipped_weeks.append(wk)
            continue
        rt = ratings.set_index("team")

        for _, g in group.iterrows():
            ht, at = g["home_team"], g["away_team"]
            feats = features.game_feature_row(
                rt, ht, at,
                g.get("home_rest", features.DEFAULT_REST),
                g.get("away_rest", features.DEFAULT_REST),
            )
            if feats is None:
                continue

            epa_diff = ((feats["home_off_epa_pp"] - feats["away_off_epa_pp"])
                        - (feats["home_def_epa_pp"] - feats["away_def_epa_pp"]))
            spread = g.get("spread_line")

            if bundle is not None and pd.notna(spread):
                est, cols, used = bundle["with_spread"], bundle["features_with_spread"], "with_spread"
                x = dict(feats, spread=float(spread))
            elif bundle is not None:
                est, cols, used = bundle["no_spread"], bundle["features"], "no_spread"
                x = feats
            else:
                est, cols, x, used = None, None, None, "fallback_linear"

            if est is not None:
                prob = float(est.predict_proba(np.array([[x[c] for c in cols]],
                                                        dtype=float))[:, 1][0])
            else:
                prob = _linear_fallback(epa_diff)

            rows.append({
                "week": wk, "home_team": ht, "away_team": at,
                "home_win_prob": round(prob, 4),
                "epa_diff": round(float(epa_diff), 3),
                "spread": None if pd.isna(spread) else float(spread),
                "model": used,
            })

    if skipped_weeks and not rows:
        raise RuntimeError(
            f"No leakage-free team ratings for {SCHEDULE_SEASON} week(s) "
            f"{sorted(skipped_weeks)}. Week 1 uses the prior season "
            f"({features.prior_season(SCHEDULE_SEASON)}); later weeks need in-season "
            f"{SCHEDULE_SEASON} play-by-play, which does not exist yet. "
            f"PBP_SEASONS={list(PBP_SEASONS)}."
        )
    if skipped_weeks:
        warnings.warn(
            f"skipped {SCHEDULE_SEASON} week(s) {sorted(skipped_weeks)}: no in-season "
            f"play-by-play yet, so no as-of ratings. Showing the "
            f"{len({r['week'] for r in rows})} week(s) that are computable.",
            stacklevel=2,
        )

    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values("home_win_prob", ascending=False).reset_index(drop=True)
    return out
