"""Tests for the 2026 projection corpus, projections, and analysis.

These run against the real cached nflverse corpus, so they double as a smoke
test that the pipeline assembles and produces sane numbers. Ensure
`python cli.py corpus` (or the relevant ingest) has populated data/raw first.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import corpus, projections, analysis  # noqa: E402
from src.config import STATS_SEASON  # noqa: E402

# Runs against the real cached nflverse corpus -> slow. CI nightly, not every push.
# See issue #25.
pytestmark = pytest.mark.slow


def _corpus():
    return corpus.build(preset="ppr")


def test_corpus_assembles():
    c = _corpus()
    assert c["weekly_history"].shape[0] > 50000
    assert c["schedule_2026"]["week"].max() >= 17  # full 2026 regular season
    assert c["depth_roles"].shape[0] > 1000
    # team defense has one row per team
    assert c["team_defense"].shape[0] >= 30


def test_projections_sane():
    c = _corpus()
    proj = projections.project_players(c, preset="ppr")
    # no duplicate player rows after dedup
    assert proj["player_id"].is_unique
    # top projection is positive and within a believable range
    top = proj.iloc[0]
    assert 5 < top["proj_ppg"] < 40
    assert top["proj_total"] > 0
    # role_share is in (0, 1]
    assert (proj["role_share"] > 0).all()
    assert (proj["role_share"] <= 1.0).all()


def test_matchups_week1():
    c = _corpus()
    board = analysis.weekly_matchups(c, week=1, preset="ppr", top_n=10)
    assert board.shape[0] == 10
    assert "opponent" in board.columns
    assert (board["proj_week"] > 0).all()


def test_consistency_skill_only():
    c = _corpus()
    cons = analysis.consistency(c, preset="ppr")
    # punters etc. excluded
    assert not cons["position"].isin(["P", "K", "LS"]).any()
    # CV is finite and positive
    assert (cons["cv"] > 0).all()


if __name__ == "__main__":
    test_corpus_assembles()
    test_projections_sane()
    test_matchups_week1()
    test_consistency_skill_only()
    print("All projection tests passed.")
