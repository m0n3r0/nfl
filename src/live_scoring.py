"""Live fantasy scoring engine — exact FD nation (Yahoo) weights.

Computes fantasy points from ESPN's free boxscore / scoringPlays JSON under
the authoritative Yahoo league settings captured in data/league-scoring.json
(the single source of truth — never hand-tune weights here).

Accuracy contract: outputs must match Yahoo's own fantasy points. Validated
against Yahoo's week-10 finals for all 15 roster players (see
tests/test_live_scoring.py). Any drift is a bug, not a rounding nuance.

Stdlib only — used by the cron/launchd poller and the tests, no pandas.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCORING_PATH = ROOT / "data" / "league-scoring.json"

_SUFFIXES = {"sr", "jr", "ii", "iii", "iv", "v"}


def load_scoring(path: Path = SCORING_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def norm_name(name: str) -> str:
    """Normalize a player name for ESPN<->Yahoo matching (suffixes, case)."""
    tokens = re.sub(r"[^a-z0-9 ]", " ", str(name).lower()).split()
    while tokens and tokens[-1] in _SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def _num(value: str) -> float:
    """ESPN stat cell -> number ('249' -> 249, '23/33' -> 23, '-' -> 0)."""
    m = re.match(r"^-?\d+(\.\d+)?", str(value).strip())
    return float(m.group(0)) if m else 0.0


def parse_game(summary: dict) -> dict:
    """Flatten one ESPN summary into player stat lines + team context.

    Returns {
      players: {norm_name: {display, team, cats: {category: {label: str}}}},
      team_stats: {abbr: {name: displayValue}},
      scores: {abbr: int},            # current/final team scores
      scoring_plays: [raw plays],
      teams: {abbr: displayName},
    }
    """
    players: dict[str, dict] = {}
    for group in summary.get("boxscore", {}).get("players", []):
        abbr = group.get("team", {}).get("abbreviation", "")
        for cat in group.get("statistics", []):
            labels = cat.get("labels", [])
            for athlete in cat.get("athletes", []):
                name = athlete.get("athlete", {}).get("displayName", "")
                if not name:
                    continue
                key = norm_name(name)
                entry = players.setdefault(
                    key, {"display": name, "team": abbr, "cats": {}})
                entry["cats"][cat.get("name", "")] = dict(
                    zip(labels, athlete.get("stats", [])))
    team_stats = {
        t.get("team", {}).get("abbreviation", ""): {
            s.get("name"): s.get("displayValue")
            for s in t.get("statistics", [])}
        for t in summary.get("boxscore", {}).get("teams", [])}
    scores, teams = {}, {}
    comps = summary.get("header", {}).get("competitions", [])
    for c in comps[:1]:
        for side in c.get("competitors", []):
            abbr = side.get("team", {}).get("abbreviation", "")
            teams[abbr] = side.get("team", {}).get("displayName", "")
            try:
                scores[abbr] = int(side.get("score", "0"))
            except (TypeError, ValueError):
                scores[abbr] = 0
    return {"players": players, "team_stats": team_stats, "scores": scores,
            "scoring_plays": summary.get("scoringPlays", []), "teams": teams}


def _cat(cats: dict, category: str, label: str) -> float:
    return _num(cats.get(category, {}).get(label, "0"))


def offense_points(cats: dict, scoring: dict, *, two_pt: int = 0,
                   off_fumble_return_td: int = 0) -> float:
    """One player's offensive fantasy points under the Yahoo weights."""
    o = scoring["offense"]
    pts = 0.0
    pts += _cat(cats, "passing", "YDS") / o["passing_yards_per_point"]
    pts += _cat(cats, "passing", "TD") * o["passing_td"]
    pts += _cat(cats, "passing", "INT") * o["interceptions"]
    pts += _cat(cats, "rushing", "YDS") / o["rushing_yards_per_point"]
    pts += _cat(cats, "rushing", "TD") * o["rushing_td"]
    pts += _cat(cats, "receiving", "REC") * o["receptions"]
    pts += _cat(cats, "receiving", "YDS") / o["receiving_yards_per_point"]
    pts += _cat(cats, "receiving", "TD") * o["receiving_td"]
    pts += _cat(cats, "fumbles", "LOST") * o["fumbles_lost"]
    pts += (_cat(cats, "kickReturns", "TD")
            + _cat(cats, "puntReturns", "TD")) * o["return_td"]
    pts += two_pt * o["two_point_conversions"]
    pts += off_fumble_return_td * o["offensive_fumble_return_td"]
    return pts


def fg_tier_points(distance: float, scoring: dict) -> float:
    k = scoring["kicker"]
    if distance < 20:
        return k["fg_0_19"]
    if distance < 30:
        return k["fg_20_29"]
    if distance < 40:
        return k["fg_30_39"]
    if distance < 50:
        return k["fg_40_49"]
    return k["fg_50_plus"]


def kicker_points(cats: dict, made_fg_distances: list[float],
                  scoring: dict) -> float:
    """Kicker: FG tiers from scoring plays (boxscore lacks distances) + XPs.

    This league has no miss penalties (no such row in the Yahoo settings).
    """
    pts = sum(fg_tier_points(d, scoring) for d in made_fg_distances)
    xp = cats.get("kicking", {}).get("XP", "0/0")
    made = _num(str(xp).split("/")[0])
    return pts + made * scoring["kicker"]["xp_made"]


_DEF_TD_TYPES = {
    "Interception Return Touchdown", "Fumble Return Touchdown",
    "Sack Opp Fumble Recovery", "Defensive Touchdown",
}
_BLOCK_TYPES = {"Blocked Field Goal", "Blocked Punt", "Blocked Extra Point"}


def def_points(abbr: str, game: dict, scoring: dict) -> float:
    """Team DEF/ST points: boxscore aggregates + scoring-play events.

    Sacks/INTs come from the defensive stat lines; fumble recoveries equal
    the opponent's lost fumbles; TDs/safeties/blocks from scoringPlays (the
    authoritative event list — avoids double counting stat-column TDs).
    Return TDs count for the DEF unit regardless of who returned them.
    """
    d = scoring["def"]
    others = [a for a in game["scores"] if a != abbr]
    opp = others[0] if others else None
    pts = 0.0
    sacks = ints = ret_td = 0.0
    for p in game["players"].values():
        if p["team"] != abbr:
            continue
        sacks += _cat(p["cats"], "defensive", "SACKS")
        ints += _cat(p["cats"], "interceptions", "INT")
        ret_td += (_cat(p["cats"], "kickReturns", "TD")
                   + _cat(p["cats"], "puntReturns", "TD"))
    pts += sacks * d["sack"] + ints * d["interception"] + ret_td * d["return_td"]
    if opp:
        fum_lost = _num(game["team_stats"].get(opp, {}).get("fumblesLost", "0"))
        pts += fum_lost * d["fumble_recovery"]
        allowed = game["scores"].get(opp, 0)
        for lo, hi, value in d["points_allowed_tiers"]:
            if allowed >= lo and (hi is None or allowed <= hi):
                pts += value
                break
    for play in game["scoring_plays"]:
        if play.get("team", {}).get("abbreviation") != abbr:
            continue
        ttype = play.get("type", {}).get("text", "")
        if ttype in _DEF_TD_TYPES:
            pts += d["td"]
        elif ttype == "Safety":
            pts += d["safety"]
        elif ttype in _BLOCK_TYPES:
            pts += d["block_kick"]
        elif ttype == "Extra Point Returned":
            pts += d["xp_returned"]
    return pts


def play_extras(game: dict) -> dict:
    """Attribute scoring-play events the boxscore doesn't carry.

    Returns {two_pt: {norm_name: count}, fg: {norm_name: [distances]},
             off_fumble_return_td: {norm_name: count}}.
    """
    two_pt: dict[str, int] = {}
    fg: dict[str, list] = {}
    off_fum_td: dict[str, int] = {}
    for play in game["scoring_plays"]:
        text = play.get("text", "")
        ttype = play.get("type", {}).get("text", "")
        # ESPN embeds successful 2-point conversions in the parent TD's
        # parenthetical: "(Brock Purdy Pass to Christian McCaffrey for
        # Two-Point Conversion)" / "(Dak Prescott Run for Two-Point
        # Conversion)". Failed attempts say "Failed" — never count them.
        if "Failed" not in text:
            m = re.search(r"\((.+?) Pass to (.+?) for Two-Point Conversion\)", text)
            if m:
                for name in (m.group(1), m.group(2)):
                    key = norm_name(name)
                    two_pt[key] = two_pt.get(key, 0) + 1
            else:
                m = re.search(r"\((.+?) (?:Run|Rush) for Two-Point Conversion\)", text)
                if m:
                    key = norm_name(m.group(1))
                    two_pt[key] = two_pt.get(key, 0) + 1
        if "Two-Point" in ttype or "Two Point" in ttype:
            # "A pass to B for 2 points" -> both; "A rush for 2 points" -> A
            m = re.match(r"(.+?) pass to (.+?) for 2 points", text)
            if m:
                for name in (m.group(1), m.group(2)):
                    key = norm_name(name)
                    two_pt[key] = two_pt.get(key, 0) + 1
            else:
                m = re.match(r"(.+?) (?:rush|run) for 2 points", text)
                if m:
                    key = norm_name(m.group(1))
                    two_pt[key] = two_pt.get(key, 0) + 1
        elif ttype == "Field Goal Good":
            m = re.match(r"(.+?) (\d+) Yd Field Goal", text)
            if m:
                fg.setdefault(norm_name(m.group(1)), []).append(float(m.group(2)))
        elif ttype == "Fumble Return Touchdown":
            # offensive player returning a fumble for a TD (rare); defensive
            # ones are credited to the DEF unit via def_points instead.
            m = re.match(r"(.+?) \d+ Yd Fumble Return", text)
            if m:
                key = norm_name(m.group(1))
                off_fum_td[key] = off_fum_td.get(key, 0) + 1
    return {"two_pt": two_pt, "fg": fg, "off_fumble_return_td": off_fum_td}


def compute_game(summary: dict, scoring: dict) -> dict:
    """All fantasy points for one game: {norm_name | 'DEF:<abbr>': points}.

    Values rounded to 2 decimals exactly as Yahoo displays them.
    """
    game = parse_game(summary)
    extras = play_extras(game)
    out: dict[str, float] = {}
    for key, p in game["players"].items():
        cats = p["cats"]
        if "kicking" in cats:
            pts = kicker_points(cats, extras["fg"].get(key, []), scoring)
        else:
            pts = offense_points(
                cats, scoring,
                two_pt=extras["two_pt"].get(key, 0),
                off_fumble_return_td=extras["off_fumble_return_td"].get(key, 0))
        out[key] = round(pts, 2)
    for abbr in game["scores"]:
        out[f"DEF:{abbr}"] = round(def_points(abbr, game, scoring), 2)
    return out


def def_key_for(yahoo_def_name: str, yahoo_team_abbr: str,
                teams: dict[str, str]) -> str | None:
    """Match a Yahoo DEF entry ('Steelers', 'Pit') to an ESPN team abbr."""
    target = norm_name(yahoo_def_name)
    for abbr, display in teams.items():
        if norm_name(display).endswith(target):
            return f"DEF:{abbr}"
    alias = {"was": "WSH", "jax": "JAX", "cin": "CIN", "pit": "PIT",
             "bal": "BAL", "chi": "CHI", "ne": "NE", "no": "NO", "gb": "GB",
             "sf": "SF", "nyj": "NYJ", "nyg": "NYG", "lar": "LAR", "la": "LAR"}
    abbr = alias.get(str(yahoo_team_abbr).lower(), str(yahoo_team_abbr).upper())
    return f"DEF:{abbr}" if abbr in teams else None
