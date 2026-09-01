"""Regression gate for issue #52: the manual failover cheat sheet must
prescribe a LEGAL roster.

The sheet's opponent model used to have no position gates or caps, so rivals
vacuumed up all 28 kickers by round 13 and the sheet's own force-fill K step
no-opped -- prescribing a roster with zero kickers. Rivals must now use the
shared model in tools/opponent_model.py (per-position caps, K/DEF/QB timing
gates), and the sheet must refuse to emit an illegal roster.
"""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHEET_PATH = ROOT / "tools" / "gen_cheat_sheet.py"
SIM_PATH = ROOT / "tools" / "simulate_draft.py"
BOARD_PATH = ROOT / "data" / "board" / "original_board.json"
GENERATED_SHEET_PATH = ROOT / "docs" / "DRAFT_CHEAT_SHEET.md"


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_cheat_sheet_prescribes_legal_roster():
    sheet = _load(SHEET_PATH, "gen_cheat_sheet")
    with open(BOARD_PATH) as f:
        board = json.load(f)

    picks = sheet.simulate(board, sheet.OUR_TEAM, sheet.N_TEAMS, sheet.ROUNDS)

    assert not sheet.roster_problems(picks), \
        "sheet prescribes an illegal roster: %s" % sheet.roster_problems(picks)
    assert len(picks) == sheet.ROUNDS, \
        "only %d/%d picks prescribed" % (len(picks), sheet.ROUNDS)

    # Every required slot filled -- including the 1 K and 1 DEF that issue #52
    # lost to rival kicker hoarding.
    counts = {}
    for _r, _o, p, _role in picks:
        counts[p["pos"]] = counts.get(p["pos"], 0) + 1
    for pos, need in sheet.REQUIRED.items():
        assert counts.get(pos, 0) >= need, \
            "%s under-filled in prescribed roster: %s" % (pos, counts)


def test_opponent_model_shared_between_tools():
    """gen_cheat_sheet.py and simulate_draft.py must model opponents with the
    same shared code (issue #52 acceptance criterion)."""
    sheet = _load(SHEET_PATH, "gen_cheat_sheet")
    sim = _load(SIM_PATH, "simulate_draft")
    assert sheet.opponent_model is sim.opponent_model
    caps = sheet.opponent_model.RIVAL_CAP
    assert caps.get("K") == 1 and caps.get("DEF") == 1, \
        "rival K/DEF caps missing -- hoarding regression: %s" % caps


def test_committed_cheat_sheet_matches_canonical_board():
    """Issue #56: generated player advice must carry the current board hash."""
    sheet = _load(SHEET_PATH, "gen_cheat_sheet_hash")
    with open(BOARD_PATH) as handle:
        board = json.load(handle)
    text = GENERATED_SHEET_PATH.read_text(encoding="utf-8")
    assert f"SHA-256 `{sheet.board_hash(board)}`" in text
    assert f"({len(board)} players," in text


if __name__ == "__main__":
    test_cheat_sheet_prescribes_legal_roster()
    test_opponent_model_shared_between_tools()
    print("cheat sheet regression tests passed")
