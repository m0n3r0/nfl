"""Assemble the 2026 fantasy projection corpus from raw nflverse tables.

Combines:
  * historical weekly player stats (2022-2025) -> per-player game-level fantasy points
  * the 2026 roster (players) and 2026 depth charts -> role / starter status
  * the 2026 schedule -> each team's opponents and a Strength-of-Schedule signal
  * derived team defense (points allowed) from the games table

The output of :func:`build` is a dict of tidy tables consumed by
projections.py and analysis.py.
"""

from __future__ import annotations

import pandas as pd

from . import ingest, scoring
from .config import SCHEDULE_SEASON, STATS_SEASON, HISTORY_SEASONS, SKILL_POSITIONS


def _weekly_history(preset: str = "ppr") -> pd.DataFrame:
    """Stack 2022-2025 weekly player stats with a 'season' tag and fantasy points."""
    frames = []
    for y in HISTORY_SEASONS:
        key = "player_week_stats" if y == STATS_SEASON else f"player_week_stats_{y}"
        df = ingest.load(key)
        df = df.copy()
        df["season"] = y
        # Weekly files use `team`; normalize so callers can rely on `recent_team`.
        if "recent_team" not in df.columns and "team" in df.columns:
            df["recent_team"] = df["team"]
        df = scoring.add_scores(df, preset=preset, copy=False)
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    return out


def build_team_defense(schedule_season: int = SCHEDULE_SEASON) -> pd.DataFrame:
    """Derive each team's points allowed (reg + post) from the games table."""
    games = ingest.load("games")
    games = games[games["season"] <= schedule_season]
    # Regular + post-reg season games only (exclude preseason if present).
    games = games[games["game_type"].isin(["REG", "POST"])]
    rows = []
    for _, r in games.iterrows():
        # away team allowed home_score; home team allowed away_score
        rows.append((r["away_team"], r["home_score"], r["season"]))
        rows.append((r["home_team"], r["away_score"], r["season"]))
    pa = pd.DataFrame(rows, columns=["team", "points_allowed", "season"])
    agg = (
        pa.groupby("team")["points_allowed"]
        .agg(avg_points_allowed="mean", games="count")
        .reset_index()
    )
    # Rank: 1 = toughest defense (fewest points allowed)
    agg = agg.sort_values("avg_points_allowed").reset_index(drop=True)
    agg["def_rank"] = agg.index + 1
    # SOS factor: how many points above/below league average a defense allows
    league = agg["avg_points_allowed"].mean()
    agg["def_sos_factor"] = (agg["avg_points_allowed"] - league) / league  # + = easier
    return agg


def build_schedule_2026() -> pd.DataFrame:
    """2026 schedule with each team's weekly opponent and home/away."""
    games = ingest.load_schedule(season=SCHEDULE_SEASON)
    games = games[games["game_type"].isin(["REG", "POST"])]
    out = []
    for _, r in games.iterrows():
        out.append({
            "week": int(r["week"]), "team": r["home_team"], "opponent": r["away_team"],
            "home": True, "game_id": r["game_id"],
        })
        out.append({
            "week": int(r["week"]), "team": r["away_team"], "opponent": r["home_team"],
            "home": False, "game_id": r["game_id"],
        })
    sched = pd.DataFrame(out)
    return sched.sort_values(["team", "week"]).reset_index(drop=True)


def build_depth_roles(season: int = SCHEDULE_SEASON) -> pd.DataFrame:
    """2026 depth-chart roles for skill positions.

    Returns one row per (team, player) with position, depth rank, and a
    'starter' flag (pos_rank == 1) plus a role share estimate.
    """
    dc = ingest.load_depth_charts(season=season)
    # The nflverse depth-charts file carries every dated snapshot of the
    # offseason (March -> cutdowns). Keep only each player-slot's LATEST
    # snapshot so roles reflect the current depth chart, not stale ones.
    if "dt" in dc.columns:
        dc = dc.sort_values("dt").drop_duplicates(
            ["team", "pos_abb", "gsis_id"], keep="last"
        )
    dc = dc[dc["pos_abb"].isin(SKILL_POSITIONS)].copy()
    dc["pos_rank"] = pd.to_numeric(dc["pos_rank"], errors="coerce")
    dc["starter"] = dc["pos_rank"] == 1
    # Role share within a (team, position) group: starter gets the lion's share.
    dc = dc.sort_values(["team", "pos_abb", "pos_rank"])
    roles = []
    for (team, pos), g in dc.groupby(["team", "pos_abb"]):
        n = len(g)
        for i, (_, row) in enumerate(g.iterrows(), start=1):
            # simple decaying share: 1st ~0.6, 2nd ~0.25, 3rd ~0.1, rest split
            weights = {1: 0.60, 2: 0.25, 3: 0.10}
            share = weights.get(i, max(0.05 / max(n - 3, 1), 0.02))
            roles.append({
                "team": team, "pos_abb": pos, "gsis_id": row["gsis_id"],
                "player_name": row["player_name"], "pos_rank": int(row["pos_rank"]),
                "starter": bool(row["starter"]), "role_share": round(share, 3),
            })
    return pd.DataFrame(roles)


def build(preset: str = "ppr") -> dict:
    """Assemble the full corpus. Returns a dict of tidy tables."""
    weekly = _weekly_history(preset=preset)
    team_def = build_team_defense()
    schedule = build_schedule_2026()
    roles = build_depth_roles()
    players = ingest.load("players")
    return {
        "weekly_history": weekly,
        "team_defense": team_def,
        "schedule_2026": schedule,
        "depth_roles": roles,
        "players": players,
    }
