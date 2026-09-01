"""Fantasy scoring, projections, and player rankings.

We compute fantasy points from raw stat-line columns so the math is explicit and
tunable. The nflverse tables also ship ``fantasy_points`` / ``fantasy_points_ppr``;
``validate_against_nflverse`` confirms our recomputed values track theirs.
"""

from __future__ import annotations

import pandas as pd

from .config import (
    SCORING_PRESETS,
    STANDARD_SCORING,
    PPR_SCORING,
    HALF_PPR_SCORING,
    SCORING_STATS,
)

# nflverse season tables use `recent_team`; weekly tables use `team`.
# Centralize the lookup so callers don't have to care which one exists.
def _team_col(df: pd.DataFrame) -> str:
    for candidate in ("recent_team", "team"):
        if candidate in df.columns:
            return candidate
    return "recent_team"


def score_row(stats: pd.Series, scoring: dict[str, float]) -> float:
    """Fantasy points for one player's stat line under ``scoring`` weights."""
    points = 0.0
    for col, weight in scoring.items():
        val = stats.get(col, 0)
        if pd.isna(val) or val is None:
            val = 0
        points += float(val) * weight
    return round(points, 2)


def add_scores(
    df: pd.DataFrame,
    preset: str = "ppr",
    copy: bool = True,
) -> pd.DataFrame:
    """Return a DataFrame with a ``fantasy_points`` column added.

    ``preset`` is one of ``standard`` / ``ppr`` / ``half-ppr`` / ``fd-nation``.
    """
    scoring = SCORING_PRESETS[preset]
    out = df.copy() if copy else df
    out["fantasy_points"] = out.apply(lambda r: score_row(r, scoring), axis=1)
    return out


def rank_players(
    df: pd.DataFrame,
    preset: str = "ppr",
    positions: list[str] | None = None,
    top_n: int = 20,
) -> pd.DataFrame:
    """Rank players by total fantasy points for the season (or aggregate).

    Expects a per-game/weekly table; it sums ``fantasy_points`` per player across
    weeks, then ranks within each requested position.
    """
    scored = add_scores(df, preset=preset, copy=True)

    team = _team_col(scored)
    agg = (
        scored.groupby(
            ["player_id", "player_display_name", "position", team],
            as_index=False,
        )
        .agg(fantasy_points=("fantasy_points", "sum"), games=("week", "nunique"))
    )

    if positions:
        agg = agg[agg["position"].isin(positions)]

    agg = agg.sort_values("fantasy_points", ascending=False).reset_index(drop=True)
    agg.insert(0, "rank", agg.index + 1)
    return agg.head(top_n)


def weekly_rankings(
    df: pd.DataFrame,
    week: int,
    preset: str = "ppr",
    positions: list[str] | None = None,
    top_n: int = 20,
) -> pd.DataFrame:
    """Rank players by fantasy points scored *in a specific week*."""
    wk = df[df["week"] == week]
    scored = add_scores(wk, preset=preset, copy=True)
    if positions:
        scored = scored[scored["position"].isin(positions)]
    scored = scored.sort_values("fantasy_points", ascending=False).reset_index(drop=True)
    scored.insert(0, "rank", scored.index + 1)
    cols = ["rank", "player_display_name", "position", _team_col(scored),
            "week", "fantasy_points"]
    return scored[cols].head(top_n)


def validate_against_nflverse(
    df: pd.DataFrame,
    preset: str = "ppr",
) -> pd.DataFrame:
    """Compare our recomputed score to nflverse's shipped ``fantasy_points_ppr``.

    Returns a small DataFrame of sample rows with both values and the delta.
    """
    nflverse_col = {
        "standard": "fantasy_points",
        "ppr": "fantasy_points_ppr",
        "half-ppr": "fantasy_points_ppr",
    }[preset]

    if nflverse_col not in df.columns:
        raise KeyError(f"nflverse column {nflverse_col!r} not present in data")

    scored = add_scores(df, preset=preset, copy=True)
    sample = scored[["player_display_name", "position", "fantasy_points"]].copy()
    sample = sample.rename(columns={"fantasy_points": "computed_points"})

    # nflverse only publishes `fantasy_points` (standard) and `fantasy_points_ppr`.
    # There is no half-PPR column, so derive nflverse's half-PPR as
    # standard + 0.5 * receptions; derive full PPR as standard + receptions.
    if preset == "standard":
        nflverse_points = df["fantasy_points"].values
    elif preset == "ppr":
        nflverse_points = df["fantasy_points_ppr"].values
    else:  # half-ppr
        nflverse_points = df["fantasy_points"].values + 0.5 * df["receptions"].fillna(0).values

    sample["nflverse_points"] = nflverse_points
    sample["delta"] = (sample["nflverse_points"] - sample["computed_points"]).round(2)
    return sample
