"""2026 fantasy projections.

Method (transparent and defensible, no black box):

1. Baseline per-game fantasy points from 2022-2025 weekly history.
   - Recent seasons weighted more heavily (1.0 / 1.5 / 2.0 / 2.5 for 2022..2025).
   - Per-game mean computed only over games the player actually appeared in.
2. Regression to the mean: blend the player's baseline with the position's
   league mean using a "confidence" weight that grows with games played, so
   lightly-used players don't get extreme projections.
3. Role adjustment: scale the baseline by the player's 2026 depth-chart role
   share (starters ~0.60, backups less). This accounts for 2026-specific
   workload (e.g. a player who changed teams / rose up the depth chart).
4. Strength-of-Schedule: adjust by the average def_sos_factor of the player's
   2026 opponents (easier schedules -> higher projection).

Output is a per-player 2026 projection in fantasy points per game and total
(assuming a 17-game regular season).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import SCHEDULE_SEASON, STATS_SEASON, HISTORY_SEASONS, SKILL_POSITIONS
from . import corpus as corpus_mod

# Season weights (most recent gets the most say).
_SEASON_WEIGHTS = {y: w for y, w in zip(HISTORY_SEASONS, [1.0, 1.5, 2.0, 2.5][-len(HISTORY_SEASONS):])}

# Games played needed to be fully confident in a player's own baseline.
_GAMES_FOR_CONFIDENCE = 20.0
REGULAR_SEASON_GAMES = 17


def _position_league_means(weekly: pd.DataFrame) -> pd.DataFrame:
    """Per-game fantasy mean per (position) across all history, for regression."""
    g = weekly.groupby(["player_id", "position", "season"])["fantasy_points"].mean().reset_index()
    return g.groupby("position")["fantasy_points"].mean().rename("pos_mean").reset_index()


def project_players(corpus: dict, preset: str = "ppr") -> pd.DataFrame:
    weekly = corpus["weekly_history"]
    roles = corpus["depth_roles"]
    schedule = corpus["schedule_2026"]
    team_def = corpus["team_defense"]

    # ---- 1. weighted per-game baseline per player ----
    weekly = weekly.copy()
    weekly["w"] = weekly["season"].map(_SEASON_WEIGHTS)
    weekly["wp"] = weekly["fantasy_points"] * weekly["w"]
    grp = weekly.groupby(["player_id", "player_display_name", "position", "recent_team"])
    base = grp.agg(
        weighted_ppg=("wp", "sum"),
        weight_sum=("w", "sum"),
        games=("week", "nunique"),
        last_season=("season", "max"),
        last_team=("recent_team", lambda s: s.iloc[-1]),
    ).reset_index()
    base["baseline_ppg"] = base["weighted_ppg"] / base["weight_sum"]
    # A player who changed teams appears on multiple rows; keep the most recent
    # team's row as his 2026 projection (the depth chart drives his 2026 role).
    base = base.sort_values("last_season").drop_duplicates("player_id", keep="last")

    # ---- 2. regression to position mean ----
    pos_means = _position_league_means(weekly)
    base = base.merge(pos_means, on="position", how="left")
    conf = (base["games"] / _GAMES_FOR_CONFIDENCE).clip(upper=1.0)
    base["regressed_ppg"] = base["baseline_ppg"] * conf + base["pos_mean"] * (1 - conf)

    # ---- 3. role adjustment from 2026 depth chart ----
    role_map = roles.groupby(["gsis_id"])["role_share"].max().rename("role_share").reset_index()
    base = base.merge(
        role_map, left_on="player_id", right_on="gsis_id", how="left"
    )
    base["role_share"] = base["role_share"].fillna(0.15)  # unranked = low share
    base["role_ppg"] = base["regressed_ppg"] * base["role_share"] / 0.60  # vs starter baseline

    # ---- 4. SOS adjustment ----
    # average opponent def_sos_factor over the player's 2026 team schedule
    team_sos = schedule.merge(
        team_def[["team", "def_sos_factor"]].rename(columns={"team": "opp_team"}),
        left_on="opponent", right_on="opp_team", how="left",
    ).drop(columns=["opp_team"]).groupby("team")["def_sos_factor"].mean().rename("team_sos").reset_index()
    base = base.merge(team_sos, left_on="last_team", right_on="team", how="left")
    base["team_sos"] = base["team_sos"].fillna(0.0)
    base["proj_ppg"] = base["role_ppg"] * (1 + base["team_sos"])
    base["proj_total"] = (base["proj_ppg"] * REGULAR_SEASON_GAMES).round(1)
    base["proj_ppg"] = base["proj_ppg"].round(2)

    out = base[[
        "player_id", "player_display_name", "position", "last_team",
        "games", "baseline_ppg", "pos_mean", "role_share", "team_sos",
        "proj_ppg", "proj_total",
    ]].copy()
    out = out.sort_values("proj_total", ascending=False).reset_index(drop=True)
    out.insert(0, "rank", out.index + 1)
    return out


def project_for_week(corpus: dict, week: int, preset: str = "ppr") -> pd.DataFrame:
    """Projected fantasy points for a specific 2026 week (uses that week's SOS)."""
    proj = project_players(corpus, preset=preset)
    schedule = corpus["schedule_2026"]
    team_def = corpus["team_defense"]
    wk = schedule[schedule["week"] == week]
    wk = wk.merge(
        team_def[["team", "def_sos_factor"]].rename(columns={"team": "opp_team"}),
        left_on="opponent", right_on="opp_team", how="left",
    ).drop(columns=["opp_team"])
    wk_sos = wk[["team", "def_sos_factor"]].rename(
        columns={"team": "last_team", "def_sos_factor": "week_sos"}
    )
    proj = proj.merge(wk_sos, on="last_team", how="left")
    proj["week_sos"] = proj["week_sos"].fillna(0.0)
    # Recover the role-only per-game baseline (strip the season-long SOS) and
    # re-apply just this week's opponent SOS.
    base_role = proj["proj_ppg"] / (1 + proj["team_sos"].fillna(0.0))
    proj["proj_week"] = (base_role * (1 + proj["week_sos"])).round(2)
    return proj
