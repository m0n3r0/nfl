"""Hermetic tests for week/kickoff awareness (src/schedule.py)."""

from __future__ import annotations

import pandas as pd
import pytest

from src import schedule as sched_mod
from src.schedule import UTC

GAMES = [
    # week 1: TNF, two Sunday 1pm, MNF
    (1, "KC", "SF", "2026-09-10", "20:15", "REG"),
    (1, "TB", "CIN", "2026-09-13", "13:00", "REG"),
    (1, "DET", "NO", "2026-09-13", "13:00", "REG"),
    (1, "DEN", "BAL", "2026-09-14", "20:15", "REG"),
    # week 2: TNF, London 9:30am, two Sunday 1pm
    (2, "BAL", "KC", "2026-09-17", "20:15", "REG"),
    (2, "NO", "TB", "2026-09-20", "09:30", "REG"),
    (2, "CIN", "SF", "2026-09-20", "13:00", "REG"),
    (2, "DEN", "DET", "2026-09-20", "13:00", "REG"),
    # postseason rows must never drive the current week
    (19, "SF", "KC", "2027-01-16", "18:30", "POST"),
]


def exploded():
    rows = []
    for week, away, home, day, time, game_type in GAMES:
        for team, opponent, is_home in ((home, away, True), (away, home, False)):
            rows.append({
                "week": week, "team": team, "opponent": opponent, "home": is_home,
                "game_id": f"2026_{week:02d}_{away}_{home}", "game_type": game_type,
                "gameday": day, "gametime": time,
            })
    return pd.DataFrame(rows)


def at(iso: str) -> pd.Timestamp:
    return pd.Timestamp(iso, tz=UTC)


def test_kickoff_utc_converts_eastern_wall_clock():
    kickoff = sched_mod.kickoff_utc("2026-09-10", "20:15")

    assert kickoff == at("2026-09-11 00:15")  # September EDT = UTC-4
    assert kickoff.tzinfo is not None


def test_kickoff_utc_missing_values_never_fabricate():
    assert sched_mod.kickoff_utc(None, "20:15") is pd.NaT
    assert sched_mod.kickoff_utc("2026-09-10", None) is pd.NaT
    assert sched_mod.kickoff_utc(float("nan"), float("nan")) is pd.NaT


def test_current_week_boundaries():
    schedule = exploded()

    assert sched_mod.current_week(schedule, at("2026-09-09 12:00")) == 1  # Wed before TNF
    assert sched_mod.current_week(schedule, at("2026-09-12 12:00")) == 1  # Sat, TNF played
    assert sched_mod.current_week(schedule, at("2026-09-14 12:00")) == 1  # Mon before MNF
    assert sched_mod.current_week(schedule, at("2026-09-15 12:00")) == 2  # Tue after MNF
    assert sched_mod.current_week(schedule, at("2026-09-21 12:00")) == 2  # all REG done


def test_current_week_ignores_postseason_rows():
    schedule = exploded()

    assert sched_mod.current_week(schedule, at("2026-12-25 12:00")) == 2  # max REG week, not 19


def test_locked_teams_follow_kickoffs():
    schedule = exploded()

    assert sched_mod.locked_teams(schedule, 1, at("2026-09-09 12:00")) == set()
    assert sched_mod.locked_teams(schedule, 1, at("2026-09-12 12:00")) == {"KC", "SF"}
    assert sched_mod.locked_teams(schedule, 2, at("2026-09-12 12:00")) == set()
    assert sched_mod.locked_teams(schedule, 1, at("2026-09-15 12:00")) == {
        "KC", "SF", "TB", "CIN", "DET", "NO", "DEN", "BAL"}


def test_lock_times_cover_only_teams_that_play():
    times = sched_mod.lock_times(exploded(), 1)

    assert set(times) == {"KC", "SF", "TB", "CIN", "DET", "NO", "DEN", "BAL"}
    assert times["SF"] == at("2026-09-11 00:15")
    assert all(t.tzinfo is not None for t in times.values())


def test_london_game_kickoff_converts():
    times = sched_mod.lock_times(exploded(), 2)

    assert times["TB"] == at("2026-09-20 13:30")  # 09:30 ET London


def test_earliest_kickoff_is_next_lineup_deadline():
    schedule = exploded()

    assert sched_mod.earliest_kickoff(schedule, 1, at("2026-09-09 12:00")) == at("2026-09-11 00:15")
    assert sched_mod.earliest_kickoff(schedule, 1, at("2026-09-12 12:00")) == at("2026-09-13 17:00")
    assert sched_mod.earliest_kickoff(schedule, 1, at("2026-09-15 12:00")) is None


def test_naive_now_is_treated_as_utc():
    schedule = exploded()

    assert sched_mod.current_week(schedule, pd.Timestamp("2026-09-15 12:00")) == 2
    assert sched_mod.locked_teams(schedule, 1, pd.Timestamp("2026-09-12 12:00")) == {"KC", "SF"}
