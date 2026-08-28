"""Tests for the original, nflverse-only draft board engine.

These are HERMETIC: they build a small synthetic corpus in-memory so they need no
network and no cached nflverse data. They verify the engine produces a board for
every position (skill + K + DEF) with sensible, ranked values, and that the
deployed driver consumes that board (via JSON) and still enforces the legal-lineup
guardrails (anchor deadlines, scarcity premium, K/DEF-late, QB-late).
"""

import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import draft_board  # noqa: E402
import driver.draft_driver as dd  # noqa: E402


# --------------------------------------------------------------------------- #
# Synthetic corpus (no network)
# --------------------------------------------------------------------------- #
def _synthetic_corpus():
    rows = []
    skill = [("p1", "Josh Allen", "QB", "BUF", 25.0),
             ("p2", "Christian McCaffrey", "RB", "SF", 22.0),
             ("p3", "Ja'Marr Chase", "WR", "CIN", 20.0),
             ("p4", "Travis Kelce", "TE", "KC", 15.0)]
    for sid, name, pos, team, fp in skill:
        for season in (2024, 2025):
            for wk in range(1, 4):
                rows.append(dict(player_id=sid, player_display_name=name,
                                 position=pos, recent_team=team,
                                 season=season, week=wk, fantasy_points=fp))
    kick = [("p5", "Harrison Butker", "K", "KC", (2, 1, 2, 1, 0, 0), 3),
            ("p6", "Brandon Aubrey", "K", "DAL", (1, 2, 2, 2, 1, 0), 3)]
    for kid, name, pos, team, fg, xp in kick:
        for season in (2024, 2025):
            for wk in range(1, 3):
                rows.append(dict(player_id=kid, player_display_name=name,
                                 position=pos, recent_team=team,
                                 season=season, week=wk, fantasy_points=0.0,
                                 fg_made_0_19=float(fg[0]),
                                 fg_made_20_29=float(fg[1]),
                                 fg_made_30_39=float(fg[2]),
                                 fg_made_40_49=float(fg[3]),
                                 fg_made_50_59=float(fg[4]),
                                 fg_made_60_=float(fg[5]),
                                 xp_made=float(xp)))
    weekly = pd.DataFrame(rows)
    depth = pd.DataFrame([
        dict(gsis_id="p1", team="BUF", pos_abb="QB", pos_rank=1, starter=True, role_share=0.60),
        dict(gsis_id="p2", team="SF", pos_abb="RB", pos_rank=1, starter=True, role_share=0.60),
        dict(gsis_id="p3", team="CIN", pos_abb="WR", pos_rank=1, starter=True, role_share=0.60),
        dict(gsis_id="p4", team="KC", pos_abb="TE", pos_rank=1, starter=True, role_share=0.60),
    ])
    team_def = pd.DataFrame([
        dict(team="LAR", avg_points_allowed=16.0, def_sos_factor=-0.10, def_rank=1),
        dict(team="BUF", avg_points_allowed=21.0, def_sos_factor=0.00, def_rank=2),
        dict(team="SF", avg_points_allowed=19.0, def_sos_factor=0.05, def_rank=3),
        dict(team="CIN", avg_points_allowed=23.0, def_sos_factor=0.10, def_rank=4),
        dict(team="KC", avg_points_allowed=20.0, def_sos_factor=-0.05, def_rank=5),
        dict(team="DAL", avg_points_allowed=22.0, def_sos_factor=0.02, def_rank=6),
    ])
    sched = pd.DataFrame([
        dict(week=1, team="BUF", opponent="MIA", home=True, game_id="g1"),
        dict(week=2, team="BUF", opponent="MIA", home=False, game_id="g2"),
        dict(week=1, team="SF", opponent="SEA", home=True, game_id="g3"),
        dict(week=2, team="SF", opponent="SEA", home=False, game_id="g4"),
        dict(week=1, team="CIN", opponent="BAL", home=True, game_id="g5"),
        dict(week=2, team="CIN", opponent="BAL", home=False, game_id="g6"),
        dict(week=1, team="KC", opponent="DEN", home=True, game_id="g7"),
        dict(week=2, team="KC", opponent="DEN", home=False, game_id="g8"),
    ])
    players = pd.DataFrame([dict(player_id="p%d" % i) for i in range(1, 7)])
    return dict(weekly_history=weekly, depth_roles=depth, team_defense=team_def,
                schedule_2026=sched, players=players)


# --------------------------------------------------------------------------- #
# Engine tests
# --------------------------------------------------------------------------- #
def test_build_original_board_covers_all_positions():
    board = draft_board.build_original_board(corpus=_synthetic_corpus(), preset="half-ppr")
    counts = Counter(b["pos"] for b in board)
    for pos in ("QB", "RB", "WR", "TE", "K", "DEF"):
        assert counts.get(pos, 0) >= 1, "missing position %s" % pos
    # every entry has the driver-expected shape
    for b in board:
        assert set(["name", "team", "pos", "value"]).issubset(b)
        assert b["value"] is not None


def test_skill_projections_positive():
    board = draft_board.build_original_board(corpus=_synthetic_corpus(), preset="half-ppr")
    for b in board:
        if b["pos"] in ("QB", "RB", "WR", "TE"):
            assert b["value"] > 0, "%s projection not positive" % b["name"]


def test_k_ranked_not_zero():
    board = draft_board.build_original_board(corpus=_synthetic_corpus(), preset="half-ppr")
    ks = [b for b in board if b["pos"] == "K"]
    assert ks, "no kickers on board"
    for k in ks:
        assert k["value"] > 0, "kicker %s scored 0 (kicking columns not read)" % k["name"]


def test_def_best_pa_ranks_first():
    board = draft_board.build_original_board(corpus=_synthetic_corpus(), preset="half-ppr")
    defs = [b for b in board if b["pos"] == "DEF"]
    assert defs, "no defenses on board"
    # LAR allowed the fewest points -> should be the top defense (Rams)
    assert defs[0]["name"] == "Rams", "best defense should rank first, got %s" % defs[0]["name"]
    for d in defs:
        assert d["value"] is not None


def test_no_duplicate_names_across_positions():
    board = draft_board.build_original_board(corpus=_synthetic_corpus(), preset="half-ppr")
    names = [b["name"] for b in board]
    assert len(names) == len(set(names)), "duplicate player names on board"


def test_real_board_depth_if_present():
    """If the real nflverse-derived board JSON has been generated (cli.py
    original-board, needs network once), a 10-team draft must have enough
    candidates at every one-slot position so an anchor-forced pick is never
    stranded. Skipped when the artifact is absent."""
    path = ROOT / "data" / "board" / "original_board.json"
    if not path.exists():
        import pytest
        pytest.skip("real board not generated yet (run: cli.py original-board)")
    board = json.loads(path.read_text(encoding="utf-8"))
    counts = Counter(b["pos"] for b in board)
    for pos in ("QB", "TE", "K", "DEF"):
        assert counts.get(pos, 0) >= 10, "%s has %d (need >=10 for 10-team)" % (pos, counts.get(pos, 0))


# --------------------------------------------------------------------------- #
# Driver consumption tests (JSON -> choose_pick guardrails)
# --------------------------------------------------------------------------- #
def _write_tmp_board(board_list):
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(board_list, f)
    return path


def test_load_original_board_reads_json():
    board_list = [
        {"name": "Josh Allen", "team": "BUF", "pos": "QB", "value": 380.0},
        {"name": "Rams", "team": "LAR", "pos": "DEF", "value": 6.0},
    ]
    path = _write_tmp_board(board_list)
    try:
        m = dd.load_original_board(path=path)
        assert m is not None
        assert m["Josh Allen"]["value"] == 380.0
        assert m["Josh Allen"]["ecr"] is None
        assert m["Rams"]["team"] == "LAR"
    finally:
        os.unlink(path)


def test_load_original_board_missing_returns_none():
    assert dd.load_original_board(path="C:/nonexistent/original_board.json") is None


def _oboard(*rows):
    """Original-mode board map: value = our projection, ecr=None."""
    return {n: {"name": n, "team": "T", "pos": p, "adp": None, "ecr": None, "value": v}
            for (n, p, v) in rows}


def test_original_board_respects_rb_anchor():
    """With ecr=None the driver sorts by our projection; the RB anchor must still
    force the 1st RB by R3 even when a higher-value WR is available."""
    board = _oboard(("RB A", "RB", 1.0), ("WR A", "WR", 20.0))
    assert dd.choose_pick(["RB A", "WR A"], {}, 2, board)[0] == "WR A"   # not forced yet
    assert dd.choose_pick(["RB A", "WR A"], {}, 3, board)[0] == "RB A"   # forced by R3


def test_original_board_keeps_k_def_late():
    """K/DEF must not be drafted before the last rounds even if they are the
    highest-projected available players."""
    board = _oboard(("K Stud", "K", 500.0), ("RB A", "RB", 1.0))
    # round 1: K gated out, RB taken instead
    pick = dd.choose_pick(["K Stud", "RB A"], {}, 1, board)
    assert pick[0] == "RB A"
    # last round with skill filled: K now allowed (and best value) -> K
    drafted = {"QB": 1, "RB": 2, "WR": 2, "TE": 1}
    pick = dd.choose_pick(["K Stud", "RB A"], drafted, 14, board)
    assert pick[0] == "K Stud"


def test_original_board_keeps_qb_late():
    board = _oboard(("QB Stud", "QB", 500.0), ("RB A", "RB", 1.0))
    # round 1: QB gated out, RB taken instead
    assert dd.choose_pick(["QB Stud", "RB A"], {}, 1, board)[0] == "RB A"
    # round 10 with RB already filled: QB allowed (and best value) -> QB
    assert dd.choose_pick(["QB Stud", "RB A"], {"RB": 2, "WR": 2, "TE": 1}, 10, board)[0] == "QB Stud"


if __name__ == "__main__":
    test_build_original_board_covers_all_positions()
    test_skill_projections_positive()
    test_k_ranked_not_zero()
    test_def_best_pa_ranks_first()
    test_no_duplicate_names_across_positions()
    test_load_original_board_reads_json()
    test_load_original_board_missing_returns_none()
    test_original_board_respects_rb_anchor()
    test_original_board_keeps_k_def_late()
    test_original_board_keeps_qb_late()
    print("All original-board tests passed.")
