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

import numpy as np
import pandas as pd

from . import ingest, features
from .config import PBP_SEASONS, SCHEDULE_SEASON, STATS_SEASON


def _feature_cols():
    return [
        "home_off_epa_pp", "away_off_epa_pp",
        "home_def_epa_pp", "away_def_epa_pp",
        "home_rz_td", "away_rz_td",
        "home_3d_epa_pp", "away_3d_epa_pp",
        "home_pass_epa_pp", "away_pass_epa_pp",
        "home_rush_epa_pp", "away_rush_epa_pp",
        "home_rest", "away_rest",
    ]


def build_frame(seasons, refresh: bool = False) -> pd.DataFrame:
    mf = features.build_model_frame(seasons, refresh=refresh)
    mf = mf.dropna(subset=_feature_cols() + ["spread", "home_win"])
    # model-only features exclude the spread; model+spread includes it
    mf["epa_diff"] = (mf["home_off_epa_pp"] - mf["away_off_epa_pp"]) - (mf["home_def_epa_pp"] - mf["away_def_epa_pp"])
    return mf


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


def predict_2026(week: int = None) -> pd.DataFrame:
    """2026 win probabilities using as-of-week-1 2026 ratings (prior season)."""
    # 2026 week 1 uses 2025 full-year ratings (leakage-safe: prior completed season)
    ratings = features.team_ratings_asof(SCHEDULE_SEASON, 1, refresh=False)
    if ratings is None or ratings.empty:
        # team_ratings_asof() returns empty rather than leaking a FUTURE season in
        # as a stand-in prior. Fail loudly instead of silently producing junk.
        raise RuntimeError(
            f"No leakage-free team ratings for {SCHEDULE_SEASON} week 1. Week 1 needs "
            f"play-by-play for a season strictly before {SCHEDULE_SEASON}; "
            f"PBP_SEASONS={list(PBP_SEASONS)}. Run the ingest for prior seasons first."
        )
    rt = ratings.set_index("team")
    sched = ingest.load_schedule(season=SCHEDULE_SEASON)
    if week is not None:
        sched = sched[sched["week"] == week]
    rows = []
    for _, g in sched.iterrows():
        ht, at = g["home_team"], g["away_team"]
        if ht not in rt.index or at not in rt.index:
            continue
        h, a = rt.loc[ht], rt.loc[at]
        epa_diff = (h["off_epa_per_play"] - a["off_epa_per_play"]) - (h["def_epa_allowed_per_play"] - a["def_epa_allowed_per_play"])
        rows.append({
            "week": int(g["week"]), "home_team": ht, "away_team": at,
            "home_win_prob": float(np.clip(0.5 + 1.2 * epa_diff, 0.05, 0.95)),
            "epa_diff": round(float(epa_diff), 3),
        })
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values("home_win_prob", ascending=False).reset_index(drop=True)
    return out
