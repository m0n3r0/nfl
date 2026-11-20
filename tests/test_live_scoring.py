"""Accuracy gate: live scoring must match Yahoo exactly.

Golden fixtures are real ESPN week-10 summaries (trimmed) + Yahoo's own
final points for our week-10 roster, captured 2026-11-20. The engine was
validated 15/15 against these before going live; this suite freezes that.
Synthetic cases cover events week 10 didn't contain (safeties, blocks,
return TDs, failed 2pt, DEF points-allowed tiers).
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.live_scoring import (  # noqa: E402
    compute_game, def_key_for, def_points, fg_tier_points, load_scoring,
    norm_name, offense_points, parse_game, play_extras,
)

FIX = Path(__file__).parent / "fixtures" / "live_scoring"
GAMES = ["sf-dal", "car-no", "min-gb", "jax-ten", "pit-cin", "was-nyg",
         "buf-nyj", "lac-bal"]


@pytest.fixture(scope="module")
def scoring():
    return load_scoring()


@pytest.fixture(scope="module")
def computed(scoring):
    out = {}
    for slug in GAMES:
        summary = json.loads((FIX / f"{slug}.json").read_text())
        out[slug] = (compute_game(summary, scoring), parse_game(summary))
    return out


def test_week10_matches_yahoo_for_every_roster_player(computed):
    """THE requirement: computed points == Yahoo's own finals, all 15."""
    finals = json.loads((FIX / "yahoo-week10-finals.json").read_text())
    checked = 0
    for r in finals["rows"]:
        if r["fanPts"] in ("Bye", ""):
            continue
        yahoo = float(r["fanPts"])
        key = norm_name(r["name"])
        found = None
        if r["position"] == "DEF":
            for pts, g in computed.values():
                k = def_key_for(r["name"], r["team"], g["teams"])
                if k and k in pts:
                    found = pts[k]
                    break
        else:
            for pts, _g in computed.values():
                if key in pts:
                    found = pts[key]
                    break
        if found is None:
            assert yahoo == 0.0, f"{r['name']} missing from ESPN boxscores"
            found = 0.0  # DNP (IR / inactive)
        assert found == pytest.approx(yahoo, abs=0.005), (
            f"{r['name']}: yahoo {yahoo} != computed {found}")
        checked += 1
    assert checked == 15


def test_two_point_conversion_credits_passer_and_receiver(computed):
    pts, _ = computed["sf-dal"]
    # Purdy->McCaffrey 2pt after the 66-yd TD: both +2 (Yahoo 31.66/44.30)
    assert pts["brock purdy"] == 31.66
    assert pts["christian mccaffrey"] == 44.30


def test_failed_two_point_never_counts(computed):
    pts, _ = computed["sf-dal"]
    # Prescott: 343/25 + 5*4 - 1 + 7/10 = 33.42, +2 for his SUCCESSFUL
    # 2pt run after the Lamb TD; the FAILED 2pt pass after the Pickens TD
    # must not count -> 35.42.
    assert pts["dak prescott"] == 35.42


def test_def_includes_points_allowed_tier_and_events(computed):
    pts, _ = computed["pit-cin"]
    assert pts["DEF:PIT"] == -3.0  # Yahoo's Steelers final


def test_kicker_fg_tiers_from_scoring_plays(computed):
    pts, _ = computed["buf-nyj"]
    assert pts["jason sanders"] == 14.0  # Yahoo's Sanders final


def test_norm_name_strips_suffixes_and_punctuation():
    assert norm_name("Deebo Samuel Sr.") == norm_name("Deebo Samuel")
    assert norm_name("Amon-Ra St. Brown") == "amon ra st brown"
    assert norm_name("Christian McCaffrey") == "christian mccaffrey"


def test_def_key_matches_mascot_and_alias():
    teams = {"PIT": "Pittsburgh Steelers", "WSH": "Washington Commanders"}
    assert def_key_for("Steelers", "Pit", teams) == "DEF:PIT"
    assert def_key_for("Commanders", "Was", teams) == "DEF:WSH"
    assert def_key_for("Bears", "Chi", teams) is None  # not in this game


def test_fg_tier_boundaries(scoring):
    assert fg_tier_points(19, scoring) == 3
    assert fg_tier_points(20, scoring) == 3
    assert fg_tier_points(39, scoring) == 3
    assert fg_tier_points(40, scoring) == 4
    assert fg_tier_points(49, scoring) == 4
    assert fg_tier_points(50, scoring) == 5
    assert fg_tier_points(63, scoring) == 5


def _game(players=None, team_stats=None, scores=None, plays=None):
    return {"players": players or {}, "team_stats": team_stats or {},
            "scores": scores or {"A": 0, "B": 0},
            "scoring_plays": plays or [], "teams": {"A": "Team A", "B": "Team B"}}


def test_def_safety_block_and_return_td(scoring):
    plays = [
        {"text": "Safety", "type": {"text": "Safety"},
         "team": {"abbreviation": "A"}},
        {"text": "Blocked Punt", "type": {"text": "Blocked Punt"},
         "team": {"abbreviation": "A"}},
    ]
    players = {"returner": {"display": "Returner", "team": "A", "cats": {
        "puntReturns": {"TD": "1"}}}}
    g = _game(players=players, scores={"A": 10, "B": 24}, plays=plays)
    # return TD 6 + safety 2 + block 2 + points allowed 21-27 -> 0
    assert def_points("A", g, scoring) == 10.0


def test_def_fumble_recovery_and_int(scoring):
    players = {"defender": {"display": "Defender", "team": "A", "cats": {
        "defensive": {"SACKS": "2"}, "interceptions": {"INT": "1"}}}}
    g = _game(players=players,
              team_stats={"B": {"fumblesLost": "1"}},
              scores={"A": 17, "B": 6})
    # sacks 2*1 + INT 2 + fum rec 2 + allowed 1-6 -> 7
    assert def_points("A", g, scoring) == 13.0


def test_offense_fumbles_returns_and_2pt(scoring):
    cats = {"passing": {"YDS": "250", "TD": "2", "INT": "1"},
            "rushing": {"YDS": "30", "TD": "1"},
            "receiving": {"REC": "4", "YDS": "40", "TD": "1"},
            "fumbles": {"LOST": "1"},
            "kickReturns": {"TD": "1"}}
    # 10 + 8 - 1 + 3 + 6 + 2 + 4 + 6 - 2 + 6 + 2(2pt) = 44
    assert offense_points(cats, scoring, two_pt=1) == 44.0


def test_play_extras_failed_conversion_ignored():
    g = _game(plays=[
        {"text": "X 1 Yd pass from Y (Two-Point Pass Conversion Failed)",
         "type": {"text": "Passing Touchdown"}, "team": {"abbreviation": "A"}},
        {"text": "X 1 Yd pass from Y (Y Pass to X for Two-Point Conversion)",
         "type": {"text": "Passing Touchdown"}, "team": {"abbreviation": "A"}},
        {"text": "Z 2 Yd Rush (Z Run for Two-Point Conversion)",
         "type": {"text": "Rushing Touchdown"}, "team": {"abbreviation": "A"}},
    ])
    extras = play_extras(g)
    assert extras["two_pt"] == {"y": 1, "x": 1, "z": 1}
