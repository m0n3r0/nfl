"""Regression gate for the offline draft simulation (issues #9/#10/#11/#19/#20).

Loads the committed board and replays a full 10-team x 15-round snake through the
REAL choose_pick(). This is the cheapest way to prove the board is deep enough, the
DEF map resolves, VOR keeps the roster balanced, and no pick stalls. It also guards
against regressions in the simulation's own opponent model: rivals must draft for
need (capped per position), not hoard quarterbacks and produce an impossible
QB-shutout that has nothing to do with our bot.
"""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIM_PATH = ROOT / "tools" / "simulate_draft.py"
BOARD_PATH = ROOT / "data" / "board" / "original_board.json"


def _load_sim():
    spec = importlib.util.spec_from_file_location("simulate_draft", SIM_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_simulation_produces_full_balanced_roster():
    sim = _load_sim()
    dd = sim.load_driver()
    board = dd.load_original_board(path=str(BOARD_PATH))
    assert board is not None, "failed to load %s" % BOARD_PATH
    assert len(board) >= dd.TEAMS * dd.TOTAL_ROUNDS, (
        "board (%d) smaller than the draft (%d picks)"
        % (len(board), dd.TEAMS * dd.TOTAL_ROUNDS))

    picks, counts, problems = sim.simulate(dd, board, verbose=False)
    assert not problems, "simulation reported problems: %s" % problems

    made = sum(1 for _, pos, _ in picks if pos != "NO_PICK")
    assert made == dd.TOTAL_ROUNDS, "only %d/%d picks made" % (made, dd.TOTAL_ROUNDS)

    # Required slots filled, and VOR keeps the bench sane.
    for pos, need in dd.REQUIRED.items():
        assert counts.get(pos, 0) >= need, "%s under-filled: %s" % (pos, counts)
    assert counts.get("QB", 0) <= 2, "drafted %d QBs (VOR bench cap broken)" % counts.get("QB", 0)
    assert counts.get("TE", 0) <= 2, "drafted %d TEs (over-stacked)" % counts.get("TE", 0)


if __name__ == "__main__":
    test_simulation_produces_full_balanced_roster()
    print("simulation regression test passed")
