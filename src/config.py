"""Scoring configuration and shared constants for the fantasy football toolkit.

Fantasy points are computed from raw stat-line columns. The nflverse weekly/season
stat tables also ship ``fantasy_points`` / ``fantasy_points_ppr`` columns; our
scoring functions recompute them from first principles so the logic is transparent
and adjustable.

The weights below were *reverse-engineered from nflverse's own shipped standard
scoring* via least-squares regression (R^2 = 1.000 on the 2024 weekly table, residual
~1e-13), so they reproduce nflverse's numbers exactly rather than a generic textbook
scheme. Key findings:
  * interceptions cost -2.0 (not -1)
  * every fumble LOST costs -2.0 (split across rushing / receiving / sack fumbles)
  * 2-point conversions are worth +2.0
  * K/DEF/ST players are scored 0 in the *player* stat table (defense is team-level)

SEASONS
-------
SCHEDULE_SEASON is the season whose game schedule we pull (2026 by default).
STATS_SEASON is the most recent season with published *player* stats. As of late
August 2026 the 2026 regular season has not yet produced game stats, so the latest
available player stat year is 2025. When nflverse publishes 2026 weekly stats, bump
STATS_SEASON to 2026 and re-run ``python cli.py ingest --refresh``.
"""

# Season whose game schedule we use for the "current" year.
SCHEDULE_SEASON = 2026

# Most recent season with published player stats (2026 stats not out yet).
STATS_SEASON = 2025

# Seasons of historical weekly player stats used to build 2026 projections.
HISTORY_SEASONS = (2022, 2023, 2024, 2025)

# Seasons of play-by-play data used for strategy / team-efficiency features.
PBP_SEASONS = (2022, 2023, 2024, 2025)

# Backwards-compatible alias used by ingest/ranking.
DEFAULT_SEASON = STATS_SEASON

# Raw stat-line columns that drive fantasy scoring (nflverse stat table names).
SCORING_STATS = [
    "passing_yards",
    "passing_tds",
    "passing_interceptions",
    "rushing_yards",
    "rushing_tds",
    "rushing_fumbles_lost",
    "receiving_yards",
    "receiving_tds",
    "receiving_fumbles_lost",
    "sack_fumbles_lost",
    "receptions",
    "passing_2pt_conversions",
    "rushing_2pt_conversions",
    "receiving_2pt_conversions",
    "special_teams_tds",
]

# Points awarded per unit of each stat. nflverse "standard" (their fantasy_points).
STANDARD_SCORING = {
    "passing_yards": 0.04,            # 1 / 25 yds
    "passing_tds": 4.0,
    "passing_interceptions": -2.0,
    "rushing_yards": 0.10,            # 1 / 10 yds
    "rushing_tds": 6.0,
    "rushing_fumbles_lost": -2.0,
    "receiving_yards": 0.10,
    "receiving_tds": 6.0,
    "receiving_fumbles_lost": -2.0,
    "sack_fumbles_lost": -2.0,
    "receptions": 0.0,                # standard: no PPR bonus
    "passing_2pt_conversions": 2.0,
    "rushing_2pt_conversions": 2.0,
    "receiving_2pt_conversions": 2.0,
    "special_teams_tds": 6.0,
}

# Full PPR: 1 point per reception on top of standard.
PPR_SCORING = dict(STANDARD_SCORING, receptions=1.0)

# Half-PPR: 0.5 points per reception.
HALF_PPR_SCORING = dict(STANDARD_SCORING, receptions=0.5)

SCORING_PRESETS = {
    "standard": STANDARD_SCORING,
    "ppr": PPR_SCORING,
    "half-ppr": HALF_PPR_SCORING,
}

# Positions we surface in rankings.
FANTASY_POSITIONS = ["QB", "RB", "WR", "TE", "K", "DEF"]

# Offensive skill positions we project / analyze.
SKILL_POSITIONS = ("QB", "RB", "WR", "TE")
