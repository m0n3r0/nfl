"""Analysis helpers: consistency, strength-of-schedule, and matchups.

These sit on top of the projection corpus to answer the questions a serious
fantasy manager actually has:
  * Is this player reliable (low weekly variance) or boom/bust?
  * How does his 2026 schedule grade out (SOS)?
  * Who are the start/sit plays for a given 2026 week?
"""

from __future__ import annotations

import pandas as pd

from . import corpus as corpus_mod


def consistency(corpus: dict, preset: str = "ppr", min_games: int = 8) -> pd.DataFrame:
    """Per-player weekly consistency metrics from 2022-2025 history.

    Returns coefficient of variation (lower = steadier), boom rate (weeks at or
    above mean + 1 std) and bust rate (weeks at or below half the player's mean).
    Restricted to offensive skill positions; players with a near-zero mean are
    excluded because their CV is undefined/uninformative.
    """
    from .config import SKILL_POSITIONS

    weekly = corpus["weekly_history"]
    weekly = weekly[weekly["position"].isin(SKILL_POSITIONS)]
    rows = []
    for (pid, name, pos), g in weekly.groupby(
        ["player_id", "player_display_name", "position"]
    ):
        if len(g) < min_games:
            continue
        pts = g["fantasy_points"].astype(float)
        mean = pts.mean()
        if mean <= 1.0:  # skip near-zero-mean players (punters, etc.)
            continue
        std = pts.std(ddof=0)
        cv = std / mean
        boom = (pts >= mean + std).mean()
        bust = (pts <= 0.5 * mean).mean()
        rows.append({
            "player_id": pid, "player_display_name": name, "position": pos,
            "games": len(g), "mean_ppg": round(mean, 2), "cv": round(cv, 3),
            "boom_rate": round(boom, 3), "bust_rate": round(bust, 3),
        })
    out = pd.DataFrame(rows).sort_values("cv").reset_index(drop=True)
    return out


def sos_ranking(corpus: dict) -> pd.DataFrame:
    """2026 Strength-of-Schedule ranking by team (easier = higher sos)."""
    team_def = corpus["team_defense"]
    sched = corpus["schedule_2026"]
    sos = sched.merge(
        team_def[["team", "def_sos_factor"]].rename(columns={"team": "opp_team"}),
        left_on="opponent", right_on="opp_team", how="left",
    ).drop(columns=["opp_team"]).groupby("team")["def_sos_factor"].mean().rename("sos").reset_index()
    sos = sos.sort_values("sos", ascending=False).reset_index(drop=True)
    sos.insert(0, "rank", sos.index + 1)
    return sos


def weekly_matchups(corpus: dict, week: int, preset: str = "ppr", top_n: int = 25):
    """Start/sit-style board for a 2026 week: each skill player vs that week's
    opponent defensive strength."""
    from . import projections

    proj = projections.project_for_week(corpus, week=week, preset=preset)
    board = proj[proj["position"].isin(["QB", "RB", "WR", "TE"])].copy()
    board = board.sort_values("proj_week", ascending=False).reset_index(drop=True)
    board = board.drop(columns=[c for c in ["rank"] if c in board.columns])
    board.insert(0, "rank", board.index + 1)
    # annotate opponent and whether the matchup is favorable
    sched = corpus["schedule_2026"]
    wk = sched[sched["week"] == week][["team", "opponent"]].rename(
        columns={"team": "last_team"}
    )
    board = board.merge(wk, on="last_team", how="left")
    out_cols = ["rank", "player_display_name", "position", "last_team", "opponent",
                "week_sos", "proj_week"]
    return board[out_cols].head(top_n)
