"""Professional-grade feature engineering from play-by-play.

This is the rigor layer that separates a toy model from a real one:

* Team efficiency is computed from play-by-play, not season-total summaries,
  so we can derive situation splits (3rd down, red zone, pass vs run).
* Ratings are computed **as-of** a (season, week) window using only PRIOR games
  in that season (no future leakage). A game in week W uses team ratings built
  from weeks 1..W-1 of the same season; week 1 uses the prior completed season.
* Results are cached to data/processed/ as parquet so the web UI and model are
  fast and fully reproducible.

Outputs:
  * team_ratings(season, week) -> DataFrame of per-team offensive/defensive
    efficiency metrics "as of" that week.
  * build_model_frame(seasons) -> labeled game rows with leakage-safe features
    for the win-probability model.
"""

from __future__ import annotations

import warnings

import pandas as pd
from pathlib import Path

from . import ingest
from .config import PBP_SEASONS

PROCESSED = ingest.RAW_DIR.parent / "processed"
PROCESSED.mkdir(parents=True, exist_ok=True)


# ---------- raw play filtering ----------
def _offense_plays(pbp: pd.DataFrame) -> pd.DataFrame:
    """Keep real offensive plays (pass/rush) with valid EPA, tagged by team."""
    p = pbp.copy()
    p = p[p["play_type"].isin(["pass", "run"])]
    p = p[p["epa"].notna()]
    # posteam = team with possession (offense); defteam = opponent
    return p[["game_id", "season", "week", "posteam", "defteam", "epa",
              "success", "down", "ydstogo", "yardline_100", "rush", "pass",
              "touchdown", "interception", "fumble", "sack", "qb_scramble",
              "shotgun", "no_huddle"]]


def _team_efficiency_from_plays(plays: pd.DataFrame) -> pd.DataFrame:
    """Aggregate a set of offensive plays into per-team efficiency metrics.

    Offense metrics are grouped by `posteam`; defense metrics by `defteam`
    (EPA allowed per play, success rate allowed, red-zone TD rate allowed).
    """
    # Precompute situation flags on the same-indexed frame so groupby lambdas
    # can align by index without re-indexing plays.
    p = plays.copy()
    p["is_pass"] = (p["pass"] == 1).astype(float)
    p["is_rush"] = (p["rush"] == 1).astype(float)
    p["is_rz"] = (p["yardline_100"] <= 20).astype(float)
    p["is_3d"] = (p["down"] == 3).astype(float)
    p["is_td"] = (p["touchdown"] == 1).astype(float)

    off = p.groupby("posteam").agg(
        off_plays=("epa", "size"),
        off_epa=("epa", "sum"),
        off_success=("success", "mean"),
        off_pass_epa=("epa", lambda s: s[p.loc[s.index, "is_pass"] == 1].sum()),
        off_rush_epa=("epa", lambda s: s[p.loc[s.index, "is_rush"] == 1].sum()),
        off_rz_td=("is_td", lambda s: s[p.loc[s.index, "is_rz"] == 1].sum()),
        off_rz_plays=("is_rz", lambda s: s[p.loc[s.index, "is_rz"] == 1].sum()),
        off_3d_epa=("epa", lambda s: s[p.loc[s.index, "is_3d"] == 1].sum()),
        off_3d_plays=("is_3d", lambda s: s[p.loc[s.index, "is_3d"] == 1].sum()),
    ).reset_index().rename(columns={"posteam": "team"})

    deff = p.groupby("defteam").agg(
        def_plays=("epa", "size"),
        def_epa_allowed=("epa", "sum"),
        def_success_allowed=("success", "mean"),
        def_pass_epa_allowed=("epa", lambda s: s[p.loc[s.index, "is_pass"] == 1].sum()),
        def_rush_epa_allowed=("epa", lambda s: s[p.loc[s.index, "is_rush"] == 1].sum()),
        def_rz_td_allowed=("is_td", lambda s: s[p.loc[s.index, "is_rz"] == 1].sum()),
        def_rz_plays_allowed=("is_rz", lambda s: s[p.loc[s.index, "is_rz"] == 1].sum()),
        def_3d_epa_allowed=("epa", lambda s: s[p.loc[s.index, "is_3d"] == 1].sum()),
        def_3d_plays_allowed=("is_3d", lambda s: s[p.loc[s.index, "is_3d"] == 1].sum()),
    ).reset_index().rename(columns={"defteam": "team"})

    out = off.merge(deff, on="team", how="outer")
    # per-play rates
    out["off_epa_per_play"] = out["off_epa"] / out["off_plays"]
    out["def_epa_allowed_per_play"] = out["def_epa_allowed"] / out["def_plays"]
    out["off_rz_td_rate"] = (out["off_rz_td"] / out["off_rz_plays"]).fillna(0)
    out["def_rz_td_rate_allowed"] = (out["def_rz_td_allowed"] / out["def_rz_plays_allowed"]).fillna(0)
    out["off_3d_epa_per_play"] = out["off_3d_epa"] / out["off_3d_plays"]
    out["def_3d_epa_allowed_per_play"] = out["def_3d_epa_allowed"] / out["def_3d_plays_allowed"]
    return out


def prior_season(season: int) -> int | None:
    """Most recent season we have PBP for that is STRICTLY before `season`.

    Returns None when no such season exists (e.g. season=2022, the first year we
    have play-by-play for). Callers MUST treat None as "no leakage-free prior"
    and drop the game -- never substitute a newer season, which would leak
    future results into the training features. See issue #17.

    This is deliberately a separate pure function (no PBP load) so the leakage
    rule can be unit-tested without downloading ~95 MB per season.
    """
    priors = [s for s in PBP_SEASONS if s < season]
    return max(priors) if priors else None


# ---------- model feature columns ----------
# Defined here (not in model.py) because features.py is the lower layer: model.py
# imports features, so the canonical column list has to live on this side for both
# the training frame and the inference frame to use it.
EPA_FEATURE_COLS = [
    "home_off_epa_pp", "away_off_epa_pp",
    "home_def_epa_pp", "away_def_epa_pp",
    "home_rz_td", "away_rz_td",
    "home_3d_epa_pp", "away_3d_epa_pp",
    "home_pass_epa_pp", "away_pass_epa_pp",
    "home_rush_epa_pp", "away_rush_epa_pp",
]
REST_FEATURE_COLS = ["home_rest", "away_rest"]
FEATURE_COLS = EPA_FEATURE_COLS + REST_FEATURE_COLS

# Only used if the schedule has no rest columns at all. Historical schedules
# always carry them (mean ~7.4 days, never null), so this is defensive.
DEFAULT_REST = 0


def game_feature_row(rt: pd.DataFrame, home_team: str, away_team: str,
                     home_rest=DEFAULT_REST, away_rest=DEFAULT_REST) -> dict | None:
    """Leakage-safe feature row for one game, given as-of ratings `rt`.

    SHARED by `build_model_frame()` (training) and `model.predict_2026()`
    (inference) so the two can never drift apart. Before issue #18 the inference
    path ignored this entirely and used a hardcoded `0.5 + 1.2 * epa_diff`, a
    function of one number that had nothing to do with the 14 features the
    model was actually fitted on.

    Returns None when either team has no as-of rating, so callers skip the game.
    """
    if home_team not in rt.index or away_team not in rt.index:
        return None
    h, a = rt.loc[home_team], rt.loc[away_team]
    return {
        "home_off_epa_pp": h["off_epa_per_play"],
        "away_off_epa_pp": a["off_epa_per_play"],
        "home_def_epa_pp": h["def_epa_allowed_per_play"],
        "away_def_epa_pp": a["def_epa_allowed_per_play"],
        "home_rz_td": h["off_rz_td_rate"],
        "away_rz_td": a["off_rz_td_rate"],
        "home_3d_epa_pp": h["off_3d_epa_per_play"],
        "away_3d_epa_pp": a["off_3d_epa_per_play"],
        "home_pass_epa_pp": h["off_pass_epa"] / h["off_plays"],
        "away_pass_epa_pp": a["off_pass_epa"] / a["off_plays"],
        "home_rush_epa_pp": h["off_rush_epa"] / h["off_plays"],
        "away_rush_epa_pp": a["off_rush_epa"] / a["off_plays"],
        "home_rest": home_rest,
        "away_rest": away_rest,
    }


_WARNED_MISSING_SEASONS: set[int] = set()


def _load_pbp_or_empty(season: int) -> pd.DataFrame | None:
    """Load a season of play-by-play, or None if we know we do not have it.

    Seasons outside PBP_SEASONS (e.g. 2026 before it kicks off) have no published
    play-by-play, and nflverse answers with a 404. That is a legitimate "no data"
    state, not an error: a caller asking for as-of ratings in a season that has
    not started should get an empty result, not an unhandled HTTPError.

    The membership check happens BEFORE any network call. Without it, a
    full-season prediction asked for 17 unrated weeks and made 17 doomed HTTP
    requests, which made `/predictions` unusably slow.

    A season we DO claim to have (in PBP_SEASONS) propagates its errors --
    swallowing a real download failure there would silently drop training rows.
    """
    if season not in PBP_SEASONS:
        # Warn once per season: callers ask week by week, so without this a
        # full-season prediction would emit the same warning 17 times.
        if season not in _WARNED_MISSING_SEASONS:
            _WARNED_MISSING_SEASONS.add(season)
            warnings.warn(
                f"no play-by-play for {season}: not in PBP_SEASONS="
                f"{list(PBP_SEASONS)}, so this season is treated as unrated.",
                stacklevel=2,
            )
        return None
    return ingest.load_pbp(season)


def team_ratings_asof(season: int, week: int, refresh: bool = False) -> pd.DataFrame:
    """Per-team efficiency 'as of' (season, week): uses weeks 1..week-1.

    Week 1 uses the most recent **strictly-prior** season's full-year efficiency.
    Returns an EMPTY DataFrame when no strictly-prior season exists (e.g. 2022
    week 1), so callers drop those games instead of rating them on future data.
    Also returns empty when the season's play-by-play is not published yet.

    Cached to data/processed/team_ratings_{season}_w{week}.csv.gz. The empty
    case is deliberately NOT cached.
    """
    if week < 1:
        raise ValueError(f"week must be >= 1, got {week}")

    cache = PROCESSED / f"team_ratings_{season}_w{week}.csv.gz"
    if cache.exists() and not refresh:
        return pd.read_csv(cache, low_memory=False)

    if week > 1:
        pbp = _load_pbp_or_empty(season)
        if pbp is None:
            return pd.DataFrame()
        pbp = pbp[pbp["week"] < week]
        plays = _offense_plays(pbp)
        ratings = _team_efficiency_from_plays(plays)
    else:
        # Preseason prior: the most recent STRICTLY-prior season.
        #
        # This used to be max([s for s in PBP_SEASONS if s < season] + [STATS_SEASON]).
        # Because STATS_SEASON (2025) is the newest season in PBP_SEASONS, that
        # max() returned 2025 for EVERY season <= 2025 -- so a 2022 week-1 game was
        # rated on full-year 2025 efficiency. Concretely, the 2022_w1 and 2024_w1
        # caches were byte-identical: the same 2025 data labelled two different
        # seasons. That leaks up to four years of future results into BOTH the
        # train split (2022-23) and the test split (2024-25). See issue #17.
        prev = prior_season(season)
        if prev is None:
            # No leakage-free prior exists. Returning empty (rather than reaching
            # forward to STATS_SEASON) means build_model_frame() drops the game.
            return pd.DataFrame()
        pbp = ingest.load_pbp(prev)
        plays = _offense_plays(pbp)
        ratings = _team_efficiency_from_plays(plays)
    ratings.to_csv(cache, index=False, compression="gzip")
    return ratings


def build_model_frame(seasons, refresh: bool = False) -> pd.DataFrame:
    """Labeled game rows with leakage-safe features (home-team perspective).

    For each game we look up each team's ratings *as of that game's week*
    (weeks 1..week-1). Features: EPA-per-play differential, red-zone TD-rate
    differential, 3rd-down EPA differential, pass/rush EPA differential.
    Target: home_win.
    """
    games = ingest.load("games")
    games = games[games["game_type"].isin(["REG", "POST"])]
    games = games[games["season"].isin(seasons)]

    rows = []
    for _, g in games.iterrows():
        season, week = int(g["season"]), int(g["week"])
        ratings_df = team_ratings_asof(season, week, refresh=refresh)
        if ratings_df is None or ratings_df.empty:
            # No leakage-free prior for this game (e.g. 2022 week 1, the first
            # season we have PBP for). Drop it rather than substitute future data.
            continue
        rt = ratings_df.set_index("team")
        ht, at = g["home_team"], g["away_team"]
        feats = game_feature_row(rt, ht, at,
                                 g.get("home_rest", DEFAULT_REST),
                                 g.get("away_rest", DEFAULT_REST))
        if feats is None:
            continue
        rows.append({
            "season": season, "week": week,
            "home_team": ht, "away_team": at,
            **feats,
            "spread": g["spread_line"],
            "home_win": 1 if g["home_score"] > g["away_score"] else 0,
        })
    return pd.DataFrame(rows)


def strategy_breakdown(pbp: pd.DataFrame, team: str) -> dict:
    """Situation-level splits for one team (game-strategy analysis)."""
    p = _offense_plays(pbp)
    p = p[p["posteam"] == team]
    if p.empty:
        return {}
    def agg(df):
        return {
            "epa_per_play": round(df["epa"].mean(), 3),
            "success_rate": round(df["success"].mean(), 3),
            "n": int(len(df)),
        }
    rz = p[p["yardline_100"] <= 20]
    third = p[p["down"] == 3]
    passp = p[p["pass"] == 1]
    rushp = p[p["rush"] == 1]
    return {
        "overall": agg(p),
        "red_zone": agg(rz),
        "third_down": agg(third),
        "pass": agg(passp),
        "rush": agg(rushp),
        "pass_rate": round(len(passp) / len(p), 3),
        "shotgun_rate": round((p["shotgun"] == 1).mean(), 3),
    }
