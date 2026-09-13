"""Hermetic tests for yahoo/league_strength.py."""

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from yahoo import league_strength as ls  # noqa: E402


def _frame():
    rows = [
        ("q1", "Qb One", "QB", "KC", 250.0, 18.0),
        ("q2", "Qb Two", "QB", "BUF", 300.0, 22.0),
        ("r1", "Rb One", "RB", "KC", 280.0, 15.0),
        ("r2", "Rb Two", "RB", "BUF", 200.0, 12.0),
        ("r3", "Rb Three", "RB", "MIA", 150.0, 9.0),
        ("w1", "Wr One", "WR", "KC", 220.0, 13.0),
        ("w2", "Wr Two", "WR", "BUF", 210.0, 11.0),
        ("w3", "Wr Three", "WR", "MIA", 180.0, 10.0),
        ("t1", "Te One", "TE", "KC", 160.0, 8.0),
        ("k1", "K One", "K", "KC", 0.0, 0.0),
        ("n1", "Rookie One", "WR", "TEN", None, None),  # identified, but model has no number
    ]
    return pd.DataFrame(rows, columns=["player_id", "player_display_name",
                                       "position", "last_team", "proj_total", "proj_week"])


def _roster(*specs):
    return [{"name": name, "team": team, "position": pos, "slot": slot, "injury_status": ""}
            for name, team, pos, slot in specs]


def test_evaluate_roster_marks_values_and_statuses():
    roster = _roster(("Qb One", "KC", "QB", "QB"),
                     ("Qb One", "MIA", "QB", "BN"),       # team mismatch
                     ("Ghost Player", "KC", "QB", "BN"),  # unmapped
                     ("Rookie One", "TEN", "WR", "BN"))   # matched, but no projection
    evaluated = ls.evaluate_roster(roster, _frame(), "proj_total", 1000)

    assert evaluated[0]["value"] == 250.0 and evaluated[0]["map_status"] == "matched"
    assert evaluated[1]["value"] is None and evaluated[1]["map_status"] == "team_mismatch"
    assert evaluated[2]["value"] is None and evaluated[2]["map_status"] == "unmapped"
    assert evaluated[3]["value"] is None and evaluated[3]["map_status"] == "no_projection"


def test_optimal_lineup_picks_best_surplus_for_flex():
    players = [
        {"name": "qb", "position": "QB", "value": 20.0, "slot": "QB"},
        {"name": "rb1", "position": "RB", "value": 15.0, "slot": "RB"},
        {"name": "rb2", "position": "RB", "value": 14.0, "slot": "RB"},
        {"name": "wr1", "position": "WR", "value": 13.0, "slot": "WR"},
        {"name": "wr2", "position": "WR", "value": 12.0, "slot": "WR"},
        {"name": "wr3", "position": "WR", "value": 11.0, "slot": "W/R/T"},
        {"name": "rb3", "position": "RB", "value": 10.5, "slot": "BN"},
        {"name": "te1", "position": "TE", "value": 9.0, "slot": "TE"},
        {"name": "k", "position": "K", "value": 7.0, "slot": "K"},
        {"name": "unvalued", "position": "DEF", "value": None, "slot": "DEF"},
    ]
    lineup = ls.optimal_lineup(players)
    names = [p["name"] for p in lineup]

    assert "wr3" in names and "rb3" not in names  # 11.0 beats 10.5 for the flex
    assert "unvalued" not in names                # None values never slotted
    assert ls.optimal_score(players) == 20.0 + 15 + 14 + 13 + 12 + 11 + 9 + 7


def test_position_ranks_marks_bottom_tier():
    league = {
        "1": [{"name": "Qb Two", "position": "QB", "value": 300.0},
              {"name": "Rb One", "position": "RB", "value": 280.0}],
        "2": [{"name": "Qb One", "position": "QB", "value": 250.0},
              {"name": "Rb Three", "position": "RB", "value": 150.0}],
    }
    ranks = {r["position"]: r for r in ls.position_ranks(league, "2")}

    assert ranks["QB"]["rank"] == 2 and ranks["QB"]["of"] == 2
    assert ranks["QB"]["my_player"] == "Qb One"
    assert ranks["RB"]["rank"] == 2 and ranks["RB"]["best_player"] == "Rb One"


def test_bye_weeks_and_concentration_only_count_starters():
    schedule = pd.DataFrame([
        {"team": "SF", "week": w} for w in range(1, 19) if w != 8
    ] + [
        {"team": "NO", "week": w} for w in range(1, 19) if w != 8
    ] + [
        {"team": "KC", "week": w} for w in range(1, 19) if w != 5
    ])
    byes = ls.bye_weeks(schedule)
    assert byes == {"SF": 8, "NO": 8, "KC": 5}

    players = [
        {"name": "sf starter", "team": "SF", "slot": "QB"},
        {"name": "no starter", "team": "NO", "slot": "WR"},
        {"name": "kc starter", "team": "KC", "slot": "RB"},
        {"name": "sf bench", "team": "SF", "slot": "BN"},
    ]
    concentration = ls.bye_concentration(players, byes)
    assert concentration == {8: ["no starter", "sf starter"]}  # KC is alone; bench ignored


def test_dead_spots_skip_kickers_and_defense():
    players = [
        {"name": "ghost", "position": "RB", "value": None, "map_status": "unmapped", "slot": "BN"},
        {"name": "zero", "position": "WR", "value": 0.0, "map_status": "matched", "slot": "BN"},
        {"name": "kicker", "position": "K", "value": 0.0, "map_status": "matched", "slot": "K"},
        {"name": "defense", "position": "DEF", "value": None, "map_status": "unmapped", "slot": "DEF"},
    ]
    spots = ls.dead_spots(players)
    assert [s["name"] for s in spots] == ["ghost", "zero"]


def test_recommendations_fire_each_rule():
    my_eval = [{"name": "ghost", "position": "RB", "value": None,
                "map_status": "team_mismatch", "slot": "BN"}]
    week_eval = [{"name": "Purdy", "position": "QB", "value": 17.0, "slot": "QB"}]
    ranks = [{"position": "QB", "rank": 10, "of": 10, "my_player": "Purdy",
              "my_value": 267.0, "best_player": "Allen"}]
    wire = [{"name": "Mayfield", "position": "QB", "proj_week": 21.0},
            {"name": "Scrub", "position": "QB", "proj_week": 17.5}]
    recs = ls.recommendations(
        my_eval=my_eval, week_eval=week_eval, lineup_moves=(),
        wire_targets=wire, ranks=ranks, concentration={8: ["A", "B", "C"]},
        season_strength=(5, 10, 1430.0))

    kinds = [r["kind"] for r in recs]
    assert kinds.count("weak_slot") == 1
    waiver = [r for r in recs if r["kind"] == "waiver"]
    assert len(waiver) == 1 and "Mayfield" in waiver[0]["text"]  # Scrub is below threshold
    assert "drop ghost" in waiver[0]["text"]
    assert any(r["kind"] == "hygiene" and "ghost" in r["text"] for r in recs)
    assert any(r["kind"] == "bye" and "URGENT" in r["text"] for r in recs)
    assert any(r["kind"] == "standing" and "outside" in r["text"] for r in recs)
    assert recs[0]["kind"] == "lineup"  # lineup note always first


def test_render_report_has_all_sections():
    report = {
        "date": "2026-09-13", "week": 1,
        "matchup": {"opponent": "Opp", "score": 35.6, "opponent_score": 0.0,
                    "team_proj": 100.5, "opponent_proj": 112.7},
        "season_strength": {"rank": 5, "of": 10, "score": 1430.4,
                            "leader": 1577.7, "playoff_line": 1492.1},
        "position_ranks": [{"position": "QB", "rank": 10, "of": 10,
                            "my_player": "Purdy", "my_value": 267.4,
                            "best_player": "Allen"}],
        "alerts": ["locked starters: Purdy"],
        "recommendations": [{"kind": "lineup", "priority": 1, "text": "lineup is optimal"}],
    }
    text = ls.render_report(report)
    for marker in ("MATCHUP", "LEAGUE STRENGTH", "Position ranks", "ALERTS",
                   "RECOMMENDATIONS", "10/10"):
        assert marker in text


def test_waiver_rule_compares_weakest_starter_at_position():
    week_eval = [
        {"name": "Rb Star", "position": "RB", "value": 18.0, "slot": "RB"},
        {"name": "Rb Weak", "position": "RB", "value": 12.0, "slot": "RB"},
        {"name": "Wr Flex", "position": "WR", "value": 9.0, "slot": "W/R/T"},
    ]
    wire = [{"name": "Rb Target", "position": "RB", "proj_week": 14.5},
            {"name": "Rb Small", "position": "RB", "proj_week": 13.0}]
    recs = ls.recommendations(
        my_eval=[], week_eval=week_eval, lineup_moves=(), wire_targets=wire,
        ranks=[], concentration={}, season_strength=(1, 10, 1500.0))

    waiver = [r for r in recs if r["kind"] == "waiver"]
    assert len(waiver) == 1
    assert "Rb Target" in waiver[0]["text"] and "beats Rb Weak" in waiver[0]["text"]
    assert "no obvious drop candidate" in waiver[0]["text"]


def test_drop_candidates_are_bench_only_and_flag_trade_lag():
    players = [
        {"name": "starter mismatch", "position": "WR", "value": None,
         "map_status": "team_mismatch", "slot": "WR"},
        {"name": "bench zero", "position": "RB", "value": 0.0,
         "map_status": "matched", "slot": "BN"},
    ]
    drops = ls.drop_candidates(players)
    assert [d["name"] for d in drops] == ["bench zero"]


def test_waiver_rec_warns_when_drop_is_trade_lag():
    my_eval = [{"name": "B Robinson", "position": "RB", "value": None,
                "map_status": "team_mismatch", "slot": "BN"}]
    week_eval = [{"name": "Purdy", "position": "QB", "value": 17.0, "slot": "QB"}]
    wire = [{"name": "Mayfield", "position": "QB", "proj_week": 21.0}]
    recs = ls.recommendations(
        my_eval=my_eval, week_eval=week_eval, lineup_moves=(), wire_targets=wire,
        ranks=[], concentration={}, season_strength=(5, 10, 1430.0))

    waiver = next(r for r in recs if r["kind"] == "waiver")
    assert "drop B Robinson" in waiver["text"] and "trade lag" in waiver["text"]


def test_render_report_notes_missing_teams():
    report = {
        "date": "2026-09-13", "week": 1, "matchup": None,
        "teams_missing": ["7"],
        "season_strength": {"rank": 5, "of": 9, "score": 1430.4,
                            "leader": 1577.7, "playoff_line": 1492.1},
        "position_ranks": [], "alerts": [],
        "recommendations": [{"kind": "lineup", "priority": 1, "text": "x"}],
    }
    text = ls.render_report(report)
    assert "1 team roster(s) unreadable" in text and "ids: 7" in text


def test_render_report_light_mode_skips_league_sections():
    report = {
        "date": "2026-09-13", "week": 1, "mode": "light", "matchup": None,
        "season_strength": None, "position_ranks": [], "alerts": [],
        "recommendations": [{"kind": "lineup", "priority": 1, "text": "x"}],
    }
    text = ls.render_report(report)
    assert "MODE: light" in text
    assert "LEAGUE STRENGTH" not in text
    assert "Position ranks" not in text
    assert "RECOMMENDATIONS" in text


def test_position_ranks_share_tied_values():
    league = {
        "1": [{"name": "Qb A", "position": "QB", "value": 300.0}],
        "2": [{"name": "Qb B", "position": "QB", "value": 300.0}],
        "3": [{"name": "Qb C", "position": "QB", "value": 250.0}],
    }
    ranks = {tid: next(r for r in ls.position_ranks(league, tid) if r["position"] == "QB")
             for tid in league}

    assert ranks["1"]["rank"] == 1 and ranks["2"]["rank"] == 1
    assert ranks["3"]["rank"] == 3  # two players strictly above, not second


def test_drop_candidates_exclude_model_blind_spots():
    players = [
        {"name": "rookie", "position": "WR", "value": None,
         "map_status": "no_projection", "slot": "BN"},
        {"name": "bench zero", "position": "RB", "value": 0.0,
         "map_status": "matched", "slot": "BN"},
        {"name": "ghost", "position": "RB", "value": None,
         "map_status": "unmapped", "slot": "BN"},
    ]
    drops = ls.drop_candidates(players)
    assert [d["name"] for d in drops] == ["bench zero", "ghost"]


def test_blind_spot_hygiene_rec_is_not_drop_advice():
    my_eval = [{"name": "C Tate", "position": "WR", "value": None,
                "map_status": "no_projection", "slot": "BN"}]
    recs = ls.recommendations(
        my_eval=my_eval, week_eval=None, lineup_moves=(), wire_targets=[],
        ranks=[], concentration={}, season_strength=(5, 10, 1430.0))

    hygiene = [r for r in recs if r["kind"] == "hygiene"]
    assert len(hygiene) == 1
    assert "model blind spot" in hygiene[0]["text"]
    assert "not an auto-drop" in hygiene[0]["text"]
    assert "convert this slot" not in hygiene[0]["text"]


def test_waiver_rec_falls_back_when_only_blind_spot_drops():
    my_eval = [{"name": "C Tate", "position": "WR", "value": None,
                "map_status": "no_projection", "slot": "BN"}]
    week_eval = [{"name": "Purdy", "position": "QB", "value": 17.0, "slot": "QB"}]
    wire = [{"name": "Mayfield", "position": "QB", "proj_week": 21.0}]
    recs = ls.recommendations(
        my_eval=my_eval, week_eval=week_eval, lineup_moves=(), wire_targets=wire,
        ranks=[], concentration={}, season_strength=(5, 10, 1430.0))

    waiver = next(r for r in recs if r["kind"] == "waiver")
    assert "no obvious drop candidate" in waiver["text"]
    assert "drop C Tate" not in waiver["text"]
