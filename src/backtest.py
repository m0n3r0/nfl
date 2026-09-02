"""Historical fantasy projection backtests without future-season leakage."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from .projections import _GAMES_FOR_CONFIDENCE

TOP_N = {"QB": 12, "RB": 24, "WR": 24, "TE": 12}


@dataclass(frozen=True)
class BacktestMetric:
    scope: str
    players: int
    spearman: float
    mae_ppg: float
    top_n: int | None
    top_n_recall: float | None

    def as_dict(self) -> dict:
        return asdict(self)


def _rank_correlation(predicted: pd.Series, actual: pd.Series) -> float:
    return float(predicted.rank(method="average").corr(actual.rank(method="average")))


def _metrics(frame: pd.DataFrame, prediction: str, scope: str, top_n: int | None = None) -> BacktestMetric:
    clean = frame.dropna(subset=[prediction, "actual_ppg"])
    if len(clean) < 2:
        raise ValueError(f"not enough players to score {scope}")
    recall = None
    if top_n is not None:
        n = min(top_n, len(clean))
        predicted_top = set(clean.nlargest(n, prediction)["player_id"])
        actual_top = set(clean.nlargest(n, "actual_ppg")["player_id"])
        recall = len(predicted_top & actual_top) / n
    return BacktestMetric(
        scope=scope,
        players=len(clean),
        spearman=round(_rank_correlation(clean[prediction], clean["actual_ppg"]), 3),
        mae_ppg=round(float((clean[prediction] - clean["actual_ppg"]).abs().mean()), 3),
        top_n=top_n,
        top_n_recall=round(recall, 3) if recall is not None else None,
    )


def project_historical_season(
    weekly: pd.DataFrame,
    target_season: int,
    season_weights: dict[int, float],
    min_actual_games: int = 4,
) -> pd.DataFrame:
    """Project returning players for ``target_season`` using only earlier rows."""
    required = {"player_id", "player_display_name", "position", "season", "week", "fantasy_points"}
    if not required.issubset(weekly.columns):
        raise KeyError(f"weekly data is missing: {sorted(required - set(weekly.columns))}")
    history = weekly[(weekly["season"] < target_season) & weekly["season"].isin(season_weights)].copy()
    actual_rows = weekly[weekly["season"] == target_season].copy()
    history = history[history["position"].isin(TOP_N)]
    actual_rows = actual_rows[actual_rows["position"].isin(TOP_N)]
    if history.empty or actual_rows.empty:
        raise ValueError("backtest requires both historical and target-season rows")

    history["weight"] = history["season"].map(season_weights).astype(float)
    history["weighted_points"] = history["fantasy_points"] * history["weight"]
    grouped = history.groupby(["player_id", "player_display_name", "position"])
    predicted = grouped.agg(
        weighted_points=("weighted_points", "sum"),
        weight_sum=("weight", "sum"),
        games=("week", "size"),
    ).reset_index()
    predicted["weighted_ppg"] = predicted["weighted_points"] / predicted["weight_sum"]

    player_seasons = history.groupby(["player_id", "position", "season"])["fantasy_points"].mean().reset_index()
    position_mean = player_seasons.groupby("position")["fantasy_points"].mean().rename("position_mean")
    predicted = predicted.merge(position_mean, on="position", how="left")
    confidence = (predicted["games"] / _GAMES_FOR_CONFIDENCE).clip(upper=1.0)
    predicted["model_ppg"] = predicted["weighted_ppg"] * confidence + predicted["position_mean"] * (1 - confidence)

    prior = history[history["season"] == target_season - 1].groupby("player_id")["fantasy_points"].mean().rename("prior_year_ppg")
    actual = actual_rows.groupby(["player_id", "position"]).agg(
        actual_ppg=("fantasy_points", "mean"), actual_games=("week", "size")
    ).reset_index()
    actual = actual[actual["actual_games"] >= min_actual_games]
    return predicted.merge(prior, on="player_id", how="left").merge(actual, on=["player_id", "position"], how="inner")


def backtest_metrics(frame: pd.DataFrame, prediction: str = "model_ppg") -> tuple[BacktestMetric, ...]:
    """Return overall and fantasy-position rank/error/hit-rate metrics."""
    metrics = [_metrics(frame, prediction, "ALL")]
    for position, top_n in TOP_N.items():
        subset = frame[frame["position"] == position]
        if len(subset.dropna(subset=[prediction, "actual_ppg"])) >= 2:
            metrics.append(_metrics(subset, prediction, position, top_n))
    return tuple(metrics)
