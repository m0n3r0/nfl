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
5. Rookie prior (post-draft): players from the SCHEDULE_SEASON draft class have
   no weekly history, so they are injected with a position-mean baseline scaled
   by depth-chart role share and a draft-capital discount (round 1 > round 2
   > later). They therefore appear on the board with honest, conservative
   projections instead of being invisible.

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

# Rookie prior: with zero games the regression step yields exactly the position
# mean; these discounts (applied after the role-share scaling) keep projected
# rookies below proven veterans unless they hold a clear starting role.
ROOKIE_DISCOUNT_BY_ROUND = {1: 0.80, 2: 0.65}
ROOKIE_DISCOUNT_DEFAULT = 0.50


def _position_league_means(weekly: pd.DataFrame) -> pd.DataFrame:
    """Per-game fantasy mean per (position) across all history, for regression."""
    g = weekly.groupby(["player_id", "position", "season"])["fantasy_points"].mean().reset_index()
    return g.groupby("position")["fantasy_points"].mean().rename("pos_mean").reset_index()


def project_players(corpus: dict) -> pd.DataFrame:
    """Note: scoring is baked into the corpus at build time (corpus.build
    scores weekly_history with the preset), so there is no preset arg here."""
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

    # ---- 2b. rookie prior: draft-class players have no weekly history, so they
    # are absent from `base`. Inject them with games = 0 (confidence 0, so the
    # regression step yields exactly the position mean). The role (step 3) and
    # SOS (step 4) adjustments then apply unchanged; the draft-capital discount
    # in 3b keeps them conservative.
    players_tbl = corpus.get("players")
    _need = {"gsis_id", "display_name", "position", "draft_year"}
    if players_tbl is not None and _need.issubset(players_tbl.columns):
        _have = set(base["player_id"])
        rk = players_tbl[
            (players_tbl["draft_year"] == SCHEDULE_SEASON)
            & (players_tbl["position"].isin(SKILL_POSITIONS))
            & (~players_tbl["gsis_id"].isin(_have))
        ].dropna(subset=["gsis_id"]).drop_duplicates("gsis_id")
        if len(rk):
            _team = rk["draft_team"] if "draft_team" in rk.columns else ""
            _round = rk["draft_round"] if "draft_round" in rk.columns else float("nan")
            base = pd.concat([base, pd.DataFrame({
                "player_id": rk["gsis_id"].values,
                "player_display_name": rk["display_name"].values,
                "position": rk["position"].values,
                "games": 0.0,
                "last_season": SCHEDULE_SEASON,
                "last_team": _team.values if hasattr(_team, "values") else _team,
                "baseline_ppg": 0.0,
                "draft_round": _round.values if hasattr(_round, "values") else _round,
                "is_rookie": True,
            })], ignore_index=True)
            base["is_rookie"] = base["is_rookie"].fillna(False)

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

    # ---- 3b. draft-capital discount for injected rookies ----
    if base.get("is_rookie", pd.Series(dtype=bool)).any():
        _mask = base["is_rookie"].astype(bool)
        _disc = base["draft_round"].map(
            lambda r: ROOKIE_DISCOUNT_BY_ROUND.get(int(r), ROOKIE_DISCOUNT_DEFAULT)
            if pd.notna(r) else ROOKIE_DISCOUNT_DEFAULT
        )
        base.loc[_mask, "role_ppg"] = base.loc[_mask, "role_ppg"] * _disc[_mask]

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

    if "draft_round" not in base.columns:
        base["draft_round"] = np.nan
    if "is_rookie" not in base.columns:
        base["is_rookie"] = False
    out = base[[
        "player_id", "player_display_name", "position", "last_team",
        "games", "baseline_ppg", "pos_mean", "role_share", "team_sos",
        "proj_ppg", "proj_total", "draft_round", "is_rookie",
    ]].copy()
    out = out.sort_values("proj_total", ascending=False).reset_index(drop=True)
    out.insert(0, "rank", out.index + 1)
    return out


def project_for_week(corpus: dict, week: int) -> pd.DataFrame:
    """Projected fantasy points for a specific 2026 week (uses that week's SOS)."""
    proj = project_players(corpus)
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
