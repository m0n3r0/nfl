"""Shared pytest fixtures.

Session-scoped data loaders so the heavy nflverse corpus (~95 MB PBP) is read
once per test *session* instead of once per test. The data-backed test modules
(test_scoring, test_model, test_projections) are marked `slow` and run in CI
nightly; `pytest -m "not slow"` exercises only the fast, hermetic tests (draft
board + driver logic), which finish in seconds. See issue #25.
"""
import pytest


@pytest.fixture(scope="session")
def games_df():
    from src import ingest

    return ingest.load("games")


@pytest.fixture(scope="session")
def weekly_stats_df():
    from src import ingest

    return ingest.load("player_week_stats")
