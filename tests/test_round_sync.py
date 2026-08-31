"""Regression tests for issue #44: round_num must track the page pick number,
not the driver's own counter, so a restart or missed pick doesn't desync the
anchor schedule."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import driver.draft_driver as dd  # noqa: E402


def test_round_derived_from_pick_number_10_team():
    # 10-team league: picks 1-10 = R1, 11-20 = R2, 21-30 = R3 ...
    assert dd.round_from_pick_number(1, 1, teams=10) == 1
    assert dd.round_from_pick_number(10, 1, teams=10) == 1
    assert dd.round_from_pick_number(11, 1, teams=10) == 2
    assert dd.round_from_pick_number(20, 1, teams=10) == 2
    assert dd.round_from_pick_number(21, 1, teams=10) == 3
    assert dd.round_from_pick_number(65, 1, teams=10) == 7


def test_restart_midway_resumes_at_correct_round():
    # Driver restarts: its local counter is back at 1, but the room is at pick 65
    # (round 7). The page number must win so anchors don't fire two rounds late.
    local_round = 1
    assert dd.round_from_pick_number(65, local_round, teams=10) == 7


def test_missed_pick_does_not_shift_round():
    # Our counter thinks we're at R6, but the page shows overall pick 71 (R8):
    # a pick was auto-drafted for us. The anchor schedule should follow the page.
    assert dd.round_from_pick_number(71, 6, teams=10) == 8


def test_unreadable_pick_number_falls_back_to_local():
    assert dd.round_from_pick_number(None, 4, teams=10) == 4
    assert dd.round_from_pick_number("garbage", 4, teams=10) == 4
    assert dd.round_from_pick_number(0, 4, teams=10) == 4
    assert dd.round_from_pick_number(-3, 4, teams=10) == 4


def test_uses_module_team_count_by_default():
    # Default teams= should be the module's configured league size.
    assert dd.round_from_pick_number(dd.TEAMS + 1, 1) == 2
