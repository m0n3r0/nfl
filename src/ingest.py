"""Data ingestion from the public nflverse release assets.

nflverse publishes flat CSVs as GitHub *release* assets (not as files on the
default branch). We download the ones we need into ``data/raw`` and cache them,
re-downloading only when explicitly forced.

The schedule is pulled for ``SCHEDULE_SEASON`` (2026 by default) while player
stats are pulled for ``STATS_SEASON`` (the most recent season with published
game stats -- 2025 as of late Aug 2026, since the 2026 season hasn't produced
player stats yet).
"""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import requests

from .config import SCHEDULE_SEASON, STATS_SEASON

# Base URL for nflverse-data release assets.
_RELEASE_BASE = "https://github.com/nflverse/nflverse-data/releases/download"


def _datasets(stats_season: int = STATS_SEASON) -> dict[str, tuple[str, str]]:
    """Logical name -> (url, local filename) for the given stats season."""
    return {
        "players": (
            f"{_RELEASE_BASE}/players/players.csv",
            "players.csv",
        ),
        "games": (
            f"{_RELEASE_BASE}/schedules/games.csv",
            "games.csv",
        ),
        "player_week_stats": (
            f"{_RELEASE_BASE}/stats_player/stats_player_week_{stats_season}.csv",
            f"player_week_stats_{stats_season}.csv",
        ),
    }


# Repo root is two levels up from this file (src/ -> repo root).
REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = REPO_ROOT / "data" / "raw"


def _datasets_map(stats_season: int = STATS_SEASON) -> dict[str, tuple[str, str]]:
    return _datasets(stats_season)


def _url(name: str, stats_season: int = STATS_SEASON) -> str:
    try:
        return _datasets(stats_season)[name][0]
    except KeyError as exc:
        raise KeyError(f"unknown dataset {name!r}; known: {sorted(_datasets(stats_season))}") from exc


def _dest_path(name: str, stats_season: int = STATS_SEASON) -> Path:
    return RAW_DIR / _datasets(stats_season)[name][1]


def download(name: str, refresh: bool = False, timeout: int = 180,
             stats_season: int = STATS_SEASON) -> Path:
    """Download ``name`` into data/raw, returning the local path.

    Skips the download if a cached copy exists unless ``refresh`` is set.
    """
    url = _url(name, stats_season)
    dest = _dest_path(name, stats_season)
    if dest.exists() and not refresh:
        return dest

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with requests.get(url, stream=True, timeout=timeout) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0))
            written = 0
            with open(tmp, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    if not chunk:
                        continue
                    fh.write(chunk)
                    written += len(chunk)
            if total:
                print(f"  downloaded {name}: {written/1e6:.1f}/{total/1e6:.1f} MB", flush=True)
            else:
                print(f"  downloaded {name}: {written/1e6:.1f} MB", flush=True)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise

    tmp.replace(dest)
    return dest


def load(name: str, refresh: bool = False, stats_season: int = STATS_SEASON) -> pd.DataFrame:
    """Download (if needed) and return ``name`` as a DataFrame."""
    dest = download(name, refresh=refresh, stats_season=stats_season)
    return pd.read_csv(dest, low_memory=False)


def load_all(refresh: bool = False, stats_season: int = STATS_SEASON) -> dict[str, pd.DataFrame]:
    """Download and load every known dataset. Returns a name->DataFrame dict."""
    out = {}
    for name in _datasets(stats_season):
        print(f"Loading {name}...")
        out[name] = load(name, refresh=refresh, stats_season=stats_season)
    return out


def load_schedule(season: int = SCHEDULE_SEASON, refresh: bool = False) -> pd.DataFrame:
    """Return the game schedule filtered to ``season`` (default 2026)."""
    games = load("games", refresh=refresh)
    games = games[games["season"] == season].reset_index(drop=True)
    return games
