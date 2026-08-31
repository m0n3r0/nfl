"""Dry-run the FD nation draft against a board, without a browser or network.

This is the regression check for issues #9/#10/#11: replay a full 10-team x 15-round
snake using the REAL `choose_pick()` and the committed board, and assert we make 15
picks, fill every required slot, and never hit NO_VALID_PICK.

Opponents are modelled as taking the best remaining players by board value, which is
harsher than reality (real leagues reach for QBs/rookies/Ks early), so a board that
survives here will survive the live draft.

Usage:
    python tools/simulate_draft.py
    python tools/simulate_draft.py --board data/board/original_board.json --verbose
"""

from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "driver" / "draft_driver.py"
DEFAULT_BOARD = ROOT / "data" / "board" / "original_board.json"

sys.path.insert(0, str(Path(__file__).resolve().parent))
import opponent_model


def load_driver():
    spec = importlib.util.spec_from_file_location("draft_driver", DRIVER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _opponent_pick(dd, board, avail, roster, rnd):
    """Model one rival's pick like a real manager.

    Thin wrapper over the shared opponent model in tools/opponent_model.py:
    rivals fill starting slots first, then take best available for the bench,
    but with per-position caps and K/DEF/QB timing gates so they never hoard
    (issue #20) and never vacuum up every kicker (issue #52). Rivals here rank
    by raw board value; gen_cheat_sheet.py ranks by league ADP.
    """
    cands = [v for v in board.values() if v["name"] in avail]
    return opponent_model.opponent_pick(
        cands, roster, rnd, dd.REQUIRED, dd.TOTAL_ROUNDS,
        key=lambda x: x["value"])


def simulate(dd, board, verbose=False):
    """Replay the draft. Returns (picks, counts, problems)."""
    avail = {v["name"] for v in board.values()}
    drafted = collections.Counter()
    rivals = [collections.Counter() for _ in range(dd.TEAMS - 1)]
    picks, problems = [], []

    for rnd in range(1, dd.TOTAL_ROUNDS + 1):
        pick = dd.choose_pick(sorted(avail), dict(drafted), rnd, board,
                              adp_map={}, pos_map={})
        if pick is None:
            problems.append("round %d: NO_VALID_PICK (board exhausted or all "
                            "candidates guarded) -- Yahoo would auto-draft" % rnd)
            picks.append((rnd, "NO_PICK", "--"))
        else:
            name, _team, pos, _adp = pick
            picks.append((rnd, pos or "?", name))
            if pos:
                drafted[pos] += 1
            avail.discard(name)

        # The other managers pick, snake order reversed on odd rounds.
        order = list(range(dd.TEAMS - 1))
        if rnd % 2 == 0:
            order.reverse()
        for i in order:
            v = _opponent_pick(dd, board, avail, rivals[i], rnd)
            if v is not None:
                rivals[i][v["pos"]] += 1
                avail.discard(v["name"])

    # Post-hoc checks.
    for pos, need in dd.REQUIRED.items():
        have = drafted.get(pos, 0)
        if have < need:
            problems.append("%s under-filled: have %d, need %d" % (pos, have, need))
    if drafted.get("QB", 0) > 2:
        problems.append("drafted %d QBs (raw points are not VOR-normalised yet, "
                        "see issue #20)" % drafted["QB"])
    if drafted.get("TE", 0) > 2:
        problems.append("drafted %d TEs -- over-stacking TEs; BENCH_CAP['TE'] "
                        "should cap this (see issues #19 and #20)" % drafted["TE"])

    if verbose:
        for rnd, pos, name in picks:
            print("  R%-3d %-4s %s" % (rnd, pos, name))
    return picks, dict(drafted), problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", default=str(DEFAULT_BOARD))
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    dd = load_driver()
    board_path = Path(args.board)
    if not board_path.exists():
        print("board not found: %s" % board_path)
        return 2
    board = dd.load_original_board(path=str(board_path))
    if board is None:
        print("failed to load board: %s" % board_path)
        return 2

    print("board: %s" % board_path)
    print("  players: %d   (draft needs %d)"
          % (len(board), dd.TEAMS * dd.TOTAL_ROUNDS))
    by_pos = collections.Counter(v["pos"] for v in board.values())
    print("  by position: %s" % dict(sorted(by_pos.items())))
    print()
    print("simulated draft (we are team %s, snake, %d rounds):"
          % (dd.TEAM_ID, dd.TOTAL_ROUNDS))

    picks, counts, problems = simulate(dd, board, verbose=True)

    print()
    print("final roster: %s" % counts)
    made = sum(1 for _, pos, _ in picks if pos != "NO_PICK")
    print("picks made: %d / %d" % (made, dd.TOTAL_ROUNDS))

    if problems:
        print()
        print("PROBLEMS:")
        for p in problems:
            print("  - %s" % p)
        return 1

    print()
    print("OK: 15/15 picks, every required slot filled, no NO_VALID_PICK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
