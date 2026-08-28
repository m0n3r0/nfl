"""Regression tests for the live FantasyPros value board in the draft driver.

Key guarantee (regression for a real bug): a player whose FantasyPros feed
reports ADP=0 -- e.g. an undrafted rookie, or any player the API legitimately
scores 0 -- must NOT be dropped from the live board. The original parser used
`adp = p.get("adp") or p.get("rank_adp") or ...`; since `0 or ...` is falsy,
a 0 ADP was coerced to None and the player fell back to the static board.
We assert full coverage and that the 0 value is preserved.

Run with:  python -m pytest tests/test_draft_driver.py
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import driver.draft_driver as dd  # noqa: E402

_ORIG_FP_GET = dd._fp_get
_ORIG_KEY = dd.FP_API_KEY


def _install_mock_fp(offsets):
    """Faithful mock of the FantasyPros consensus-rankings response for every
    position in BOARD. The 2nd player of each group gets adp=0 to exercise the
    previously-broken path."""
    positions = {}
    for (name, team, pos, adp) in dd.BOARD:
        positions.setdefault(pos, []).append((name, team, adp))

    def mock_fp_get(path):
        pos = re.search(r"position=(\w+)", path).group(1)
        out = []
        for i, (name, team, adp) in enumerate(positions.get(pos, [])):
            out.append({
                "player_name": name, "player_team_id": team, "position": pos,
                "rank_ecr": i + 1,
                "adp": i + 1 + offsets[i % len(offsets)],
                "tier": 1,
            })
        return {"players": out}

    dd._fp_get = mock_fp_get


def teardown_module(module):
    dd._fp_get = _ORIG_FP_GET
    dd.FP_API_KEY = _ORIG_KEY


def test_fetch_fp_consensus_keeps_zero_adp():
    """adp=0 must be returned, not coerced to None by `or` coalescing."""
    dd._fp_get = lambda path: {"players": [
        {"player_name": "Zero Adp Guy", "player_team_id": "FA",
         "position": "RB", "rank_ecr": 3, "adp": 0, "tier": 1}]}
    rows = dd.fetch_fp_consensus("RB")
    assert len(rows) == 1
    assert rows[0]["adp"] == 0
    assert rows[0]["ecr"] == 3


def test_build_value_board_full_coverage_with_zero_adp():
    """All BOARD names survive build_value_board even when some have adp=0."""
    offsets = [4, -2, 6, -3, 2, -1, 5, -4, 3, -2,
               1, -5, 4, 3, -1, 2, 5, -3, 4, -2]
    _install_mock_fp(offsets)
    dd.FP_API_KEY = "MOCK"
    try:
        vb = dd.build_value_board()
    finally:
        dd.FP_API_KEY = None
    assert vb is not None, "expected a live board, got None"
    assert len(vb) == len(dd.BOARD), "lost players from the board"
    # every player must carry a real ecr (proves it took the live branch)
    for name, row in vb.items():
        assert "ecr" in row, f"{name} missing ecr (dropped from live board)"
        assert row["ecr"] is not None


def test_build_value_board_static_fallback_without_key():
    """Without a key we must fall back (return None), not crash."""
    dd.FP_API_KEY = None
    dd._fp_get = _ORIG_FP_GET
    vb = dd.build_value_board()
    assert vb is None


if __name__ == "__main__":
    test_fetch_fp_consensus_keeps_zero_adp()
    test_build_value_board_full_coverage_with_zero_adp()
    test_build_value_board_static_fallback_without_key()
    print("All draft-driver tests passed.")
