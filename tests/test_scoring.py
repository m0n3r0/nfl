"""Regression tests for the fantasy football toolkit.

The key guarantee: our recomputed scoring reproduces nflverse's own shipped
fantasy_points / fantasy_points_ppr for the 2024 weekly table (within rounding).
Run with:  python -m pytest tests/   (or just this file).
"""

import os
import sys
from pathlib import Path

import pandas as pd
import pytest

# Make `src` importable when run directly.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import ingest, scoring  # noqa: E402
from src.config import STATS_SEASON  # noqa: E402

# Loads the ~95 MB PBP corpus on every test -> slow. Run in CI nightly, not on
# every push. See issue #25.
pytestmark = pytest.mark.slow


def test_scoring_reproduces_nflverse():
    """Our scoring must match nflverse's shipped numbers for all presets."""
    df = ingest.load("player_week_stats", stats_season=STATS_SEASON)
    for preset in ("standard", "ppr", "half-ppr"):
        v = scoring.validate_against_nflverse(df, preset=preset)
        max_delta = v["delta"].abs().max()
        assert max_delta < 0.05, f"{preset} max delta {max_delta} too large"
        # spot-check a known top PPR scorer is present and positive
        top = scoring.rank_players(df, preset="ppr", top_n=1).iloc[0]
        assert top["fantasy_points"] > 0


def test_ppr_equals_standard_plus_receptions():
    """PPR should equal standard scoring plus one point per reception."""
    df = ingest.load("player_week_stats", stats_season=STATS_SEASON)
    std = scoring.add_scores(df, preset="standard")["fantasy_points"]
    ppr = scoring.add_scores(df, preset="ppr")["fantasy_points"]
    rec = df["receptions"].fillna(0)
    diff = (ppr - std - rec).abs().max()
    assert diff < 0.05, f"PPR != standard + receptions (max {diff})"


def test_optimize_lineup_fills_skill_slots():
    """Greedy optimizer should fill QB/RB/WR/TE/FLEX from player stats."""
    df = ingest.load("player_week_stats", stats_season=STATS_SEASON)
    ranked = scoring.add_scores(df, preset="ppr")
    from src import lineup
    picks = lineup.optimize_lineup(ranked, preset="ppr")
    for slot in ("QB", "RB", "WR", "TE", "FLEX"):
        assert len(picks[slot]) > 0, f"slot {slot} not filled"


if __name__ == "__main__":
    test_scoring_reproduces_nflverse()
    test_ppr_equals_standard_plus_receptions()
    test_optimize_lineup_fills_skill_slots()
    print("All tests passed.")
