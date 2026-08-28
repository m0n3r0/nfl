"""Original, self-contained draft board built ONLY from nflverse-derived data.

This is the "do not depend on others" engine: the board is computed entirely from
our own corpus (nflverse weekly history + depth charts + schedule + derived team
defense). No FantasyPros ECR/ADP, no Yahoo ADP, no third-party feed at draft time.

  * Skill QB/RB/WR/TE  -> src.projections.project_players (multi-year weighted
    baseline -> regression to mean -> 2026 depth-chart role -> SOS).
  * K                  -> scored from the weekly kicking columns (nflverse zeroes K
    in the player table, so we score FG/XPs ourselves, distance-tiered).
  * DEF                -> from the derived team defense (points allowed + SOS).

The board is a list of {name, team, pos, value} where `value` is the projected 2026
fantasy points (higher = better). It is serialized to JSON so the stdlib-only
deployed driver (which cannot import src) can consume it with `json` only.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .config import SKILL_POSITIONS, HISTORY_SEASONS
from . import corpus as corpus_mod, projections

# Season weights (most recent gets the most say) — mirrors projections.py.
_SEASON_WEIGHTS = {
    y: w for y, w in zip(HISTORY_SEASONS, [1.0, 1.5, 2.0, 2.5][-len(HISTORY_SEASONS):])
}

# Depth we surface per position. Generous enough that a 10-team anchor-forced pick
# is never stranded even if rivals snipe the top names before our turn.
_SKILL_DEPTH = {"QB": 15, "RB": 30, "WR": 35, "TE": 15}
K_TOP = 12
DEF_TOP = 12

# Standard fantasy kicker weights (distance-tiered FG + XP). nflverse zeroes K/DEF
# in the player table, so we score K ourselves from the raw kicking columns.
_FG_TIER_WEIGHTS = {
    "fg_made_0_19": 3.0,
    "fg_made_20_29": 3.0,
    "fg_made_30_39": 3.0,
    "fg_made_40_49": 4.0,
    "fg_made_50_59": 5.0,
    "fg_made_60_": 5.0,
}

# Team code -> short name. Used so a defense entry resolves to the same short key
# the deployed driver expects (Yahoo shows "LAR - DEF"; the driver maps the code
# to this short name before matching the board).
TEAM_SHORT = {
    "ARI": "Cardinals", "ATL": "Falcons", "BAL": "Ravens", "BUF": "Bills",
    "CAR": "Panthers", "CHI": "Bears", "CIN": "Bengals", "CLE": "Browns",
    "DAL": "Cowboys", "DEN": "Broncos", "DET": "Lions", "GB": "Packers",
    "HOU": "Texans", "IND": "Colts", "JAX": "Jaguars", "KC": "Chiefs",
    "LV": "Raiders", "LAC": "Chargers", "LAR": "Rams", "MIA": "Dolphins",
    "MIN": "Vikings", "NE": "Patriots", "NO": "Saints", "NYG": "Giants",
    "NYJ": "Jets", "PHI": "Eagles", "PIT": "Steelers", "SF": "49ers",
    "SEA": "Seahawks", "TB": "Buccaneers", "TEN": "Titans", "WAS": "Commanders",
}


def score_kicker_row(stats: pd.Series) -> float:
    """Fantasy points for one kicker-week from the raw kicking columns."""
    pts = 0.0
    for col, w in _FG_TIER_WEIGHTS.items():
        v = stats.get(col, 0) or 0
        pts += float(v) * w
    # Extra points: prefer an explicit made column, else derive from att - missed.
    xp = stats.get("xp_made", None)
    if xp is None or (isinstance(xp, float) and np.isnan(xp)):
        att = stats.get("xp_att", 0) or 0
        miss = stats.get("xp_missed", 0) or 0
        xp = max(0.0, float(att) - float(miss))
    pts += float(xp) * 1.0
    return round(pts, 2)


def _team_col(df: pd.DataFrame) -> str:
    for c in ("recent_team", "team"):
        if c in df.columns:
            return c
    return "recent_team"


def _skill_board(corpus: dict, preset: str) -> list[dict]:
    proj = projections.project_players(corpus, preset=preset)
    rows = []
    for _, r in proj.iterrows():
        pos = r["position"]
        if pos not in SKILL_POSITIONS:
            continue
        rows.append({
            "name": r["player_display_name"],
            "team": r["last_team"],
            "pos": pos,
            "value": float(r["proj_total"]),
        })
    # cap depth per position (keep the highest-projected)
    capped: list[dict] = []
    seen: dict[str, int] = {}
    for row in sorted(rows, key=lambda x: x["value"], reverse=True):
        n = seen.get(row["pos"], 0)
        if n >= _SKILL_DEPTH.get(row["pos"], 20):
            continue
        capped.append(row)
        seen[row["pos"]] = n + 1
    return capped


def _kicker_board(corpus: dict) -> list[dict]:
    weekly = corpus["weekly_history"]
    team_col = _team_col(weekly)
    k = weekly[weekly["position"].isin(["K", "PK"])].copy()
    if k.shape[0] == 0:
        return []
    k["k_pts"] = k.apply(score_kicker_row, axis=1)
    k["w"] = k["season"].map(_SEASON_WEIGHTS)
    k["wp"] = k["k_pts"] * k["w"]
    grp = k.groupby(["player_id", "player_display_name", team_col])
    agg = grp.agg(wp=("wp", "sum"), wsum=("w", "sum"),
                  games=("week", "nunique")).reset_index()
    agg = agg[agg["wsum"] > 0]
    agg["ppg"] = agg["wp"] / agg["wsum"]
    agg["proj_total"] = (agg["ppg"] * 17).round(1)
    agg = agg.sort_values("proj_total", ascending=False).head(K_TOP)
    return [{
        "name": r["player_display_name"], "team": r[team_col],
        "pos": "K", "value": float(r["proj_total"]),
    } for _, r in agg.iterrows()]


def _defense_board(corpus: dict) -> list[dict]:
    td = corpus["team_defense"].copy()
    if td.shape[0] == 0:
        return []
    league_avg = td["avg_points_allowed"].mean()
    # Lower points allowed = better defense = higher fantasy value. Linear map
    # anchored so a league-average defense is worth ~4 pts; each PA above/below
    # the average moves value by 0.5.
    td["def_value"] = 4.0 + (league_avg - td["avg_points_allowed"]) * 0.5
    if "def_sos_factor" in td.columns:
        # positive def_sos_factor = allows more (easier opponents) -> worse for D
        td["def_value"] = td["def_value"] * (1.0 - 0.4 * td["def_sos_factor"].fillna(0.0))
    td["def_value"] = td["def_value"].clip(-2.0, 14.0).round(1)
    td = td.sort_values("def_value", ascending=False).head(DEF_TOP)
    out = []
    for _, r in td.iterrows():
        code = r["team"]
        out.append({
            "name": TEAM_SHORT.get(code, code), "team": code,
            "pos": "DEF", "value": float(r["def_value"]),
        })
    return out


def build_original_board(corpus: dict | None = None, preset: str = "half-ppr") -> list[dict]:
    """Build the original draft board from nflverse-derived data only.

    Returns a list of {name, team, pos, value} sorted by value desc. If `corpus`
    is None it is assembled via corpus.build() (downloads nflverse data on first
    run). Pass a pre-built corpus (e.g. a test fixture) to avoid network.
    """
    if corpus is None:
        corpus = corpus_mod.build(preset=preset)
    board = _skill_board(corpus, preset) + _kicker_board(corpus) + _defense_board(corpus)
    board.sort(key=lambda r: r["value"], reverse=True)
    return board


def board_to_driver_map(board: list[dict]) -> dict:
    """Convert the board list into the dict shape driver.choose_pick expects.

    ecr/adp are None so choose_pick drives purely off `value` (our projection),
    applying the existing scarcity premium + anchor guardrails unchanged.
    """
    return {
        b["name"]: {"name": b["name"], "team": b["team"], "pos": b["pos"],
                    "adp": None, "ecr": None, "value": b["value"]}
        for b in board
    }


def write_original_board(path: str | Path, corpus: dict | None = None,
                         preset: str = "half-ppr") -> list[dict]:
    """Compute the board and serialize it to JSON at `path`."""
    board = build_original_board(corpus=corpus, preset=preset)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(board, f, indent=2)
    return board
