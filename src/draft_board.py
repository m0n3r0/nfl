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

from .config import SKILL_POSITIONS, HISTORY_SEASONS, SCHEDULE_SEASON
from . import corpus as corpus_mod, projections

REPO_ROOT = Path(__file__).resolve().parents[1]
INJURY_GLOB = str(REPO_ROOT / "data" / "raw" / "injuries_*.csv")

# Injury statuses that exclude a player from the draft board entirely.
# "Out" = confirmed unavailable; "IR" = on injured reserve (season or long-term).
INJURY_EXCLUDE_STATUSES = {"Out", "IR", "Reserve/Injured", "Reserve/PUP", "Reserve/NFI"}
# Injury statuses that reduce projection confidence but don't exclude.
INJURY_PENALTY_STATUSES = {"Doubtful", "Questionable"}
INJURY_PENALTY_FACTOR = {"Doubtful": 0.60, "Questionable": 0.85}

# Season weights (most recent gets the most say) — mirrors projections.py.
_SEASON_WEIGHTS = {
    y: w for y, w in zip(HISTORY_SEASONS, [1.0, 1.5, 2.0, 2.5][-len(HISTORY_SEASONS):])
}

# Depth we surface per position.
#
# The board must outlast the WHOLE draft, not just the early rounds: a 10-team x
# 15-round snake consumes 150 players, and rivals take ~9 names between each of
# our picks. The old caps (15/30/35/15 + 12 K + 12 DEF = ~121) ran dry around
# round 12, at which point choose_pick() returned None and Yahoo auto-drafted the
# rest of our team -- including the K and DEF slots. See issue #9.
#
# These depths total ~250, i.e. ~100 spare names of headroom. The underlying
# projection pool is much deeper (3,300+ players), so raising these is free.
_SKILL_DEPTH = {"QB": 32, "RB": 60, "WR": 70, "TE": 32}
K_TOP = 28
DEF_TOP = 28

# Team games in an NFL regular season. K and skill-position projections are
# already season totals; the defense model is derived per game, so it is
# multiplied by this to land on the same footing. See _defense_board().
GAMES_PER_SEASON = 17

# Smallest board we are willing to ship. Guards against a future edit quietly
# reintroducing the round-12 exhaustion: 10 teams x 15 rounds = 150 picks, and we
# want meaningful headroom above that. write_original_board() raises if it is short.
MIN_BOARD_SIZE = 250

# Floor for the rookie-starter carve-out. Deliberately low: a rookie holding a
# real starting role is board-worthy for depth even at a weak projection, and the
# board now has room to carry him. Was 20.0, which (with the old caps) excluded
# most of the 2026 class.
_ROOKIE_MIN_PROJ = 5.0

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


def _load_injury_flags(current_season: int = SCHEDULE_SEASON) -> dict[str, str]:
    """Load the latest injury report status per gsis_id from nflverse injury CSVs.

    Returns {gsis_id: report_status} for the most recent week available.
    Returns {} if no injury data is present (e.g. fresh install before ingest).

    Staleness guard (issue #50): nflverse only publishes injury reports for the
    current season once Week 1 practice reports exist, so before then the newest
    file on disk is LAST season's, current through that season's final weeks.
    Applying those flags would exclude/penalize healthy stars (Nico Collins,
    Jayden Daniels, ... were "Out" in the Feb 2026 Super Bowl report). Flags from
    a season older than ``current_season`` are therefore ignored entirely, with a
    loud warning. A stale "Out"/IR is strictly worse than no filter at all.
    """
    import glob as _glob
    import re as _re
    import warnings as _warnings
    files = sorted(_glob.glob(INJURY_GLOB))
    if not files:
        return {}
    path = files[-1]
    m = _re.search(r"injuries_(\d{4})\.csv$", path)
    if m:
        season = int(m.group(1))
    else:  # unexpected name: fall back to the data's own season column
        season = int(pd.read_csv(path, usecols=["season"])["season"].max())
    if season < current_season:
        _warnings.warn(
            f"STALE INJURY DATA: newest injury file is {path} (season {season}) "
            f"but the current season is {current_season}. Ignoring ALL injury "
            f"flags -- no player is excluded or penalized by last season's "
            f"reports. Re-run ingest once nflverse publishes "
            f"injuries_{current_season}.csv.",
            stacklevel=2,
        )
        return {}
    df = pd.read_csv(path, usecols=["gsis_id", "report_status"], low_memory=False)
    df = df.dropna(subset=["gsis_id", "report_status"])
    # keep the last occurrence per player (latest report wins)
    return dict(zip(df["gsis_id"], df["report_status"]))


def _skill_board(corpus: dict, preset: str, injury_flags: dict[str, str] | None = None) -> list[dict]:
    proj = projections.project_players(corpus)
    if injury_flags is None:
        injury_flags = _load_injury_flags()

    # Recency filter (#35 follow-up): exclude players who did not appear in
    # the most recent season's weekly data — UNLESS they are rookies (#83
    # follow-up). Rookies have no 2025 games because they are new, not
    # retired. Without this carve-out, the filter removes all 80 rookies
    # from the board (Jeremiyah Love, Carnell Tate, etc.).
    weekly = corpus["weekly_history"]
    recent_ids = set(
        weekly[weekly["season"] == weekly["season"].max()]["player_id"]
    )
    is_rookie = (
        proj["is_rookie"].fillna(False).astype(bool)
        if "is_rookie" in proj.columns
        else pd.Series(False, index=proj.index)
    )
    proj = proj[proj["player_id"].isin(recent_ids) | is_rookie]

    rows = []
    for _, r in proj.iterrows():
        pos = r["position"]
        if pos not in SKILL_POSITIONS:
            continue
        # Injury filter (#35): exclude players whose latest report says Out/IR.
        gsis = str(r.get("player_id", ""))
        status = injury_flags.get(gsis, "")
        if status in INJURY_EXCLUDE_STATUSES:
            continue
        value = float(r["proj_total"])
        if not np.isfinite(value):
            continue
        # Penalize (don't exclude) Questionable/Doubtful players.
        if status in INJURY_PENALTY_STATUSES:
            value *= INJURY_PENALTY_FACTOR.get(status, 1.0)
        rows.append({
            "name": r["player_display_name"],
            "team": r["last_team"],
            "pos": pos,
            "value": round(value, 1),
            "injury": status or None,
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
    # Rookie-starter carve-out: a 2026 draft-class player holding a clear
    # starting role (full starter role share) is board-worthy even when his
    # conservative projection sits below the veteran cutoff. Deep rookies and
    # backups stay off the board — no noise, no hype spikes.
    on_board = {(r["name"], r["pos"]) for r in capped}
    for _, r in proj.iterrows():
        if not bool(r.get("is_rookie", False)):
            continue
        if float(r.get("role_share", 0) or 0) < 0.60:
            continue
        rookie_value = float(r["proj_total"])
        if not np.isfinite(rookie_value) or rookie_value < _ROOKIE_MIN_PROJ:
            continue
        key = (r["player_display_name"], r["position"])
        if key in on_board:
            continue
        capped.append({
            "name": r["player_display_name"],
            "team": r["last_team"], "pos": r["position"],
            "value": rookie_value,
        })
        on_board.add(key)
    return capped


def _kicker_board(corpus: dict) -> list[dict]:
    weekly = corpus["weekly_history"]
    team_col = _team_col(weekly)
    k = weekly[weekly["position"].isin(["K", "PK"])].copy()
    if k.shape[0] == 0:
        return []
    # Recency filter (#35 follow-up): kickers who last played before the
    # most recent complete season are retired or irrelevant. Without this,
    # a 2022-only kicker (e.g. Ryan Succop) outranks current starters.
    latest = k["season"].max()
    k = k[k["season"] >= latest - 1]
    k["k_pts"] = k.apply(score_kicker_row, axis=1)
    k["w"] = k["season"].map(_SEASON_WEIGHTS)
    k["wp"] = k["k_pts"] * k["w"]
    # Group by player only: a kicker may appear under several teams across
    # seasons (journeymen like Matthew Wright show up for KC/PIT/SF), but he is
    # ONE draftee. Collapse to one row per player_id and use his highest-weighted
    # team as the canonical one so we never carry 3 copies of the same kicker.
    grp = k.groupby(["player_id", "player_display_name"])
    agg = grp.agg(wp=("wp", "sum"), wsum=("w", "sum"),
                  games=("week", "nunique")).reset_index()
    best_team = (k.groupby(["player_id", team_col])["wp"].sum()
                   .reset_index().sort_values("wp", ascending=False)
                   .drop_duplicates("player_id").set_index("player_id")[team_col])
    agg = agg[agg["wsum"] > 0]
    agg["ppg"] = agg["wp"] / agg["wsum"]
    agg["proj_total"] = (agg["ppg"] * 17).round(1)
    agg["team"] = agg["player_id"].map(best_team)
    agg = agg.sort_values("proj_total", ascending=False).head(K_TOP)
    return [{
        "name": r["player_display_name"], "team": r["team"],
        "pos": "K", "value": float(r["proj_total"]),
    } for _, r in agg.iterrows()]


def _defense_board(corpus: dict) -> list[dict]:
    td = corpus["team_defense"].copy()
    if td.shape[0] == 0:
        return []
    league_avg = td["avg_points_allowed"].mean()
    # Lower points allowed = better defense = higher fantasy value. Linear map
    # anchored so a league-average defense is worth ~4 pts PER GAME; each PA
    # above/below the average moves value by 0.5.
    td["def_value"] = 4.0 + (league_avg - td["avg_points_allowed"]) * 0.5
    if "def_sos_factor" in td.columns:
        # positive def_sos_factor = allows more (easier opponents) -> worse for D
        td["def_value"] = td["def_value"] * (1.0 - 0.4 * td["def_sos_factor"].fillna(0.0))
    td["def_value"] = td["def_value"].clip(-2.0, 14.0).round(1)
    # Convert PER-GAME to SEASON points so DEF is commensurable with K and the
    # skill positions. Issue #19: a board value of 6.1 (DEF, per game) sat next
    # to 153.0 (K, season) and 392.8 (QB, season), so any cross-position
    # comparison silently treated a top defense as worthless. VOR later
    # differences the scale away, but the board itself must be consistent.
    td["def_value"] = (td["def_value"] * GAMES_PER_SEASON).round(1)
    td = td.sort_values("def_value", ascending=False).head(DEF_TOP)
    out = []
    for _, r in td.iterrows():
        # nflverse historically used LA for the Rams. Yahoo's current stable
        # code is LAR, which is also the key expected by TEAM_SHORT and the
        # identity-qualified draft click path.
        code = "LAR" if r["team"] == "LA" else r["team"]
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

    Keys are the player name; if two distinct players share a display name we
    disambiguate with the team (e.g. "Matthew Wright (KC)") so neither entry is
    silently dropped. Note: choose_pick matches on the stored plain `name`, not
    the key, so disambiguation here is purely defensive against dict collisions.
    """
    out: dict[str, dict] = {}
    suffix: dict[str, int] = {}
    for b in board:
        key = b["name"]
        if key in out:
            key = "%s (%s)" % (b["name"], b["team"])
            while key in out:
                suffix[key] = suffix.get(key, 0) + 1
                key = "%s (%s)%d" % (b["name"], b["team"], suffix[key])
        out[key] = {"name": b["name"], "team": b["team"], "pos": b["pos"],
                    "adp": None, "ecr": None, "value": b["value"]}
    return out


def _adp_name_key(name: str) -> str:
    """Normalize a player name for ADP matching (case/apostrophes/suffixes out)."""
    n = name.replace("'", "").replace(".", "").strip().lower()
    parts = n.split()
    if parts and parts[-1] in ("iii", "ii", "iv", "jr", "sr"):
        parts = parts[:-1]
    return " ".join(parts)


YAHOO_TEAM_ALIASES = {"LAR": "LA", "WSH": "WAS", "JAC": "JAX", "OAK": "LV", "WFT": "WAS"}


def load_league_adp(path: str | Path = "data/scrapes/yahoo_league_adp.json") -> dict:
    """Load the league-scoped ADP scrape (tools/scrape_league_adp.py output).

    Returns {(adp_name_key, TEAM_UPPER): avg_pick}. Yahoo team codes are mapped
    to the board's code set (LAR->LA etc). Missing file -> {} so board building
    still works before the first scrape.
    """
    p = Path(path)
    if not p.exists():
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    out: dict = {}
    for row in data.get("players", []):
        adp = row.get("adp_all_drafts")
        if adp is None:
            continue
        team = YAHOO_TEAM_ALIASES.get(str(row.get("team", "")).upper(),
                                      str(row.get("team", "")).upper())
        out[(_adp_name_key(row["name"]), team)] = float(adp)
    return out


def merge_league_adp(board: list[dict],
                     adp_map: dict | None = None) -> list[dict]:
    """Annotate board rows with the league ADP where a match exists (in place).

    Primary key is normalized name + team code. Fall back to name-only when the
    name matches exactly one board row and one ADP entry -- this captures players
    whose team changed between our data snapshot and Yahoo's live data (e.g.
    deadline trades such as A.J. Brown PHI->NE, Kenneth Walker III SEA->KC,
    verified live 2026-08-30); the row keeps its own team but inherits the ADP.
    Unmatched rows keep adp=None (driver's reach guard passes them through).
    """
    if not adp_map:
        return board
    # name-only reverse index for the fallback (skip ambiguous names)
    name_count: dict[str, int] = {}
    for key in adp_map:
        name_count[key[0]] = name_count.get(key[0], 0) + 1
    board_name_count: dict[str, int] = {}
    for b in board:
        k = _adp_name_key(b["name"])
        board_name_count[k] = board_name_count.get(k, 0) + 1
    for b in board:
        nk = _adp_name_key(b["name"])
        adp = adp_map.get((nk, str(b["team"]).upper()))
        if adp is None and name_count.get(nk, 0) == 1 and board_name_count.get(nk, 0) == 1:
            adp = next(v for k, v in adp_map.items() if k[0] == nk)
            b["adp_team_changed"] = True
        if adp is not None:
            b["adp"] = adp
    return board


def write_original_board(path: str | Path, corpus: dict | None = None,
                         preset: str = "half-ppr",
                         league_adp_path: str | Path | None = "data/scrapes/yahoo_league_adp.json",
                         min_size: int | None = MIN_BOARD_SIZE) -> list[dict]:
    """Compute the board, merge the league ADP scrape (if present), serialize.

    `min_size` guards against shipping a board that is too small to finish the
    draft (see MIN_BOARD_SIZE). It defaults on for the real pipeline; tests that
    build a board from a synthetic corpus pass min_size=None.
    """
    board = build_original_board(corpus=corpus, preset=preset)
    if min_size is not None and len(board) < min_size:
        # Loud, not silent: a short board strands the late rounds (issue #9).
        raise ValueError(
            "draft board has only %d players, need >= %d to survive a 10-team "
            "x 15-round draft (raise _SKILL_DEPTH/K_TOP/DEF_TOP)"
            % (len(board), min_size)
        )
    merge_league_adp(board, load_league_adp(league_adp_path)
                     if league_adp_path is not None else None)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(board, f, indent=2, allow_nan=False)
    return board
