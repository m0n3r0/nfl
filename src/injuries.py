"""In-season injury awareness from nflverse injury reports.

Shared by the corpus builder (which carries the latest status table) and the
weekly projection path (which adjusts proj_week by status). Lifted from the
retired draft board (git history, commit cd16d8c) and generalized.

Staleness guard (issue #50): nflverse only publishes current-season injury
reports once Week 1 practice reports exist. A file from an older season is
ignored entirely — a stale "Out"/IR flag on a healthy star is strictly worse
than no filter at all.
"""

from __future__ import annotations

import glob
import re
import warnings
from pathlib import Path

import pandas as pd

from .config import SCHEDULE_SEASON

REPO_ROOT = Path(__file__).resolve().parents[1]
INJURY_GLOB = str(REPO_ROOT / "data" / "raw" / "injuries_[0-9]*.csv")

# Statuses that make a player unstartable for the week.
INJURY_EXCLUDE_STATUSES = {"Out", "IR", "Reserve/Injured", "Reserve/PUP", "Reserve/NFI"}
# Statuses that reduce confidence but keep the player startable.
INJURY_PENALTY_FACTOR = {"Doubtful": 0.60, "Questionable": 0.85}


def _latest_injury_file(current_season: int) -> str | None:
    """Return the newest injuries CSV, or None when none is usable.

    A file older than current_season is rejected with a loud warning (see the
    staleness guard in the module docstring).
    """
    files = sorted(glob.glob(INJURY_GLOB))
    if not files:
        return None
    path = files[-1]
    match = re.search(r"injuries_(\d{4})\.csv$", path)
    if match:
        season = int(match.group(1))
    else:  # unexpected name: fall back to the data's own season column
        season = int(pd.read_csv(path, usecols=["season"])["season"].max())
    if season < current_season:
        warnings.warn(
            f"STALE INJURY DATA: newest injury file is {path} (season {season}) "
            f"but the current season is {current_season}. Ignoring ALL injury "
            f"flags. Re-run ingest once nflverse publishes "
            f"injuries_{current_season}.csv.",
            stacklevel=2,
        )
        return None
    return path


def load_injury_flags(current_season: int = SCHEDULE_SEASON) -> dict[str, str]:
    """Return {gsis_id: report_status} from the newest usable injury file.

    The nflverse file is cumulative (one row per player per week), so only the
    latest two weeks of reports count — a 2-week window covers bye-week teams
    that file no report. Within the window a player's last row decides: a
    blank report_status means cleared (full participation, expected to play),
    and a player with no row in the window has fallen off the report, which
    also means cleared. Empty dict when no usable data exists.
    """
    path = _latest_injury_file(current_season)
    if path is None:
        return {}
    df = pd.read_csv(path, usecols=["gsis_id", "week", "report_status"], low_memory=False)
    df = df.dropna(subset=["gsis_id", "week"])
    if df.empty:
        return {}
    recent = df[df["week"] >= df["week"].max() - 1]
    recent = recent.sort_values("week", kind="stable")
    recent = recent.drop_duplicates(subset=["gsis_id"], keep="last")
    return {
        gsis: status
        for gsis, status in zip(recent["gsis_id"], recent["report_status"])
        if pd.notna(status) and status != ""
    }


def build_injuries(current_season: int = SCHEDULE_SEASON) -> pd.DataFrame:
    """Latest injury status table for the corpus: player_id + report_status."""
    flags = load_injury_flags(current_season)
    return pd.DataFrame(
        {"player_id": list(flags), "injury_status": list(flags.values())},
        columns=["player_id", "injury_status"],
    )


def penalty_factor(status: object) -> float:
    """Projection multiplier for an injury status (0 = unstartable)."""
    if status in INJURY_EXCLUDE_STATUSES:
        return 0.0
    return INJURY_PENALTY_FACTOR.get(status, 1.0)
