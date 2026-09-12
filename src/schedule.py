"""NFL week and kickoff awareness for the 2026 schedule.

nflverse gametimes are US Eastern local wall-clock; every kickoff here is
converted to a timezone-aware UTC timestamp so the rest of the system (this
box runs JST) can reason about "who plays when" and "who is already locked"
without caring about the local timezone.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

import pandas as pd

EASTERN = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def kickoff_utc(gameday: object, gametime: object) -> pd.Timestamp:
    """Convert an nflverse gameday ("2026-09-10") + gametime ("20:15", ET) to UTC.

    Returns NaT when either value is missing, so unscheduled rows never
    fabricate a lock time.
    """
    if pd.isna(gameday) or pd.isna(gametime):
        return pd.NaT
    local = pd.Timestamp(f"{gameday} {gametime}", tz=EASTERN)
    return local.tz_convert(UTC)


def with_kickoffs(schedule: pd.DataFrame) -> pd.DataFrame:
    """Return the schedule with a kickoff_utc column added."""
    out = schedule.copy()
    out["kickoff_utc"] = [kickoff_utc(day, time) for day, time in zip(out["gameday"], out["gametime"])]
    return out


def _regular_season(schedule: pd.DataFrame) -> pd.DataFrame:
    if "game_type" in schedule.columns:
        return schedule[schedule["game_type"] == "REG"]
    return schedule


def current_week(schedule: pd.DataFrame, now: pd.Timestamp | None = None) -> int:
    """Return the regular-season week currently in progress (or next up).

    The smallest REG week containing a game whose kickoff is still ahead of
    `now`: before Thursday kickoff resolves to this week; once the week's
    final game kicks off (e.g. Monday night), it already resolves to the
    next. Once every game has been played, the last REG week.
    """
    now = now or pd.Timestamp.now(tz=UTC)
    if now.tzinfo is None:
        now = now.tz_localize(UTC)
    reg = _regular_season(with_kickoffs(schedule))
    future = reg[reg["kickoff_utc"] > now]
    if future.empty:
        return int(reg["week"].max())
    return int(future["week"].min())


def lock_times(schedule: pd.DataFrame, week: int) -> dict[str, pd.Timestamp]:
    """Return team -> kickoff_utc for every team playing in `week`.

    Teams on bye simply have no entry; missing gametimes never appear.
    """
    games = with_kickoffs(schedule)
    games = games[(games["week"] == week) & games["kickoff_utc"].notna()]
    return dict(zip(games["team"], games["kickoff_utc"]))


def locked_teams(schedule: pd.DataFrame, week: int, now: pd.Timestamp | None = None) -> set[str]:
    """Return the teams whose week-`week` game has already kicked off."""
    now = now or pd.Timestamp.now(tz=UTC)
    if now.tzinfo is None:
        now = now.tz_localize(UTC)
    return {team for team, kickoff in lock_times(schedule, week).items() if kickoff <= now}


def earliest_kickoff(schedule: pd.DataFrame, week: int, now: pd.Timestamp | None = None) -> pd.Timestamp | None:
    """Return the first still-future kickoff of the week (cron lineup deadline)."""
    now = now or pd.Timestamp.now(tz=UTC)
    if now.tzinfo is None:
        now = now.tz_localize(UTC)
    future = [kickoff for kickoff in lock_times(schedule, week).values() if kickoff > now]
    return min(future) if future else None
