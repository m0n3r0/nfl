"""Simple fantasy lineup optimizer.

Given ranked players with fantasy points, greedily build the standard starting
lineup (1 QB, 2 RB, 2 WR, 1 TE, 1 FLEX, 1 K, 1 DEF) by picking the top available
player at each slot, allowing one skill player to fill the FLEX. This is a
greedy heuristic, not an optimal ILP solver -- adequate for a weekly "best
available" suggestion.

NOTE: the nflverse *player* stat table scores Kickers and Team-Defense as 0
(defense is team-level data), so in this dataset the K/DEF slots will be empty
and reported as such rather than fabricated. Feed a roster that includes those
positions with real points (e.g. from the schedules/team tables) to fill them.
"""

from __future__ import annotations

import pandas as pd

# Standard starting lineup slot -> how many, and which positions may fill it.
LINEUP_TEMPLATE = {
    "QB": {"n": 1, "positions": ["QB"]},
    "RB": {"n": 2, "positions": ["RB"]},
    "WR": {"n": 2, "positions": ["WR"]},
    "TE": {"n": 1, "positions": ["TE"]},
    "FLEX": {"n": 1, "positions": ["RB", "WR", "TE"]},
    "K": {"n": 1, "positions": ["K"]},
    "DEF": {"n": 1, "positions": ["DEF"]},
}


def _team_col(df: pd.DataFrame) -> str:
    for candidate in ("recent_team", "team"):
        if candidate in df.columns:
            return candidate
    return "recent_team"


def optimize_lineup(
    ranked: pd.DataFrame,
    preset: str = "ppr",
) -> dict[str, list[dict]]:
    """Greedily fill ``LINEUP_TEMPLATE`` slots from ``ranked`` (a scored table).

    ``ranked`` must contain columns: player_id, player_display_name, position,
    and a team column (``recent_team`` or ``team``), plus ``fantasy_points``.
    Returns slot -> list of chosen player dicts. Slots with no eligible scorable
    players are returned empty.
    """
    if "fantasy_points" not in ranked.columns:
        raise KeyError("ranked must include a 'fantasy_points' column")

    pool = ranked.sort_values("fantasy_points", ascending=False).reset_index(drop=True)
    team = _team_col(pool)
    used_ids: set[str] = set()
    lineup: dict[str, list[dict]] = {}

    for slot, spec in LINEUP_TEMPLATE.items():
        chosen: list[dict] = []
        # If no eligible player in this dataset actually scores points
        # (e.g. K/DEF in the nflverse player table, which scores them 0),
        # leave the slot empty rather than fabricate a 0-point pick.
        eligible = pool[pool["position"].isin(spec["positions"])]
        if len(eligible) == 0 or (eligible["fantasy_points"] <= 0).all():
            lineup[slot] = []
            continue
        for _ in range(spec["n"]):
            pick = None
            for _, row in pool.iterrows():
                pid = row["player_id"]
                if pid in used_ids:
                    continue
                if row["position"] in spec["positions"]:
                    pick = row
                    break
            if pick is None:
                break
            used_ids.add(pick["player_id"])
            chosen.append({
                "player": pick["player_display_name"],
                "position": pick["position"],
                "team": pick.get(team, ""),
                "points": round(float(pick["fantasy_points"]), 2),
            })
        lineup[slot] = chosen

    return lineup


def lineup_total(lineup: dict[str, list[dict]]) -> float:
    return round(sum(p["points"] for picks in lineup.values() for p in picks), 2)
