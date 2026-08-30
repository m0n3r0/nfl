"""Data ingestion from the public nflverse release assets.

nflverse publishes flat CSVs as GitHub *release* assets (not as files on the
default branch). We download the ones we need into ``data/raw`` and cache them,
re-downloading only when explicitly forced.

Seasons (see src/config.py):
  * SCHEDULE_SEASON (2026) -- game schedule we pull.
  * STATS_SEASON (2025)    -- most recent published player stats.
  * HISTORY_SEASONS        -- weekly player stats used to build 2026 projections.
"""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import requests

from .config import SCHEDULE_SEASON, STATS_SEASON, HISTORY_SEASONS, SKILL_POSITIONS

# Base URL for nflverse-data release assets.
_RELEASE_BASE = "https://github.com/nflverse/nflverse-data/releases/download"


def _datasets(stats_season: int = STATS_SEASON) -> dict[str, tuple[str, str]]:
    """Core datasets for the current stats season: players, games, weekly stats."""
    return {
        "players": (f"{_RELEASE_BASE}/players/players.csv", "players.csv"),
        "games": (f"{_RELEASE_BASE}/schedules/games.csv", "games.csv"),
        "player_week_stats": (
            f"{_RELEASE_BASE}/stats_player/stats_player_week_{stats_season}.csv",
            f"player_week_stats_{stats_season}.csv",
        ),
    }


def _corpus_datasets() -> dict[str, tuple[str, str]]:
    """Every dataset that makes up the 2026 projection corpus."""
    d = dict(_datasets(STATS_SEASON))
    for y in HISTORY_SEASONS:
        if y == STATS_SEASON:
            continue
        d[f"player_week_stats_{y}"] = (
            f"{_RELEASE_BASE}/stats_player/stats_player_week_{y}.csv",
            f"player_week_stats_{y}.csv",
        )
    d["depth_charts"] = (
        f"{_RELEASE_BASE}/depth_charts/depth_charts_{SCHEDULE_SEASON}.csv",
        f"depth_charts_{SCHEDULE_SEASON}.csv",
    )
    d["draft_picks"] = (
        f"{_RELEASE_BASE}/draft_picks/draft_picks.csv",
        "draft_picks.csv",
    )
    d["injuries"] = (
        f"{_RELEASE_BASE}/injuries/injuries_{STATS_SEASON}.csv",
        f"injuries_{STATS_SEASON}.csv",
    )
    return d


def download_asset(tag: str, name: str, refresh: bool = False, timeout: int = 600) -> Path:
    """Download an arbitrary release asset by (tag, filename) into data/raw/."""
    url = f"{_RELEASE_BASE}/{tag}/{name}"
    dest = RAW_DIR / name
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


def load_pbp(season: int, refresh: bool = False) -> pd.DataFrame:
    """Play-by-play for a season (the professional-grade strategy source)."""
    name = f"play_by_play_{season}.csv"
    dest = download_asset("pbp", name, refresh=refresh)
    return pd.read_csv(dest, low_memory=False)


def load_draft_picks(season: int | None = None, refresh: bool = False) -> pd.DataFrame:
    """NFL draft picks 1980-present (nflverse, updated after each real draft).

    Columns include season, round, pick, team, gsis_id, pfr_player_id,
    position, college, age and career-production/AV columns. Pass ``season``
    (e.g. 2026) to return just that draft class; the default returns all.
    """
    df = pd.read_csv(download("draft_picks", refresh=refresh), low_memory=False)
    if season is not None:
        df = df[df["season"] == season].reset_index(drop=True)
    return df


def load_team_stats(season: int, refresh: bool = False) -> pd.DataFrame:
    """Team-level season stats (offense/defense EPA, etc.)."""
    name = f"stats_team_reg_{season}.csv"
    dest = download_asset("stats_team", name, refresh=refresh)
    return pd.read_csv(dest, low_memory=False)


# Repo root is two levels up from this file (src/ -> repo root).
REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = REPO_ROOT / "data" / "raw"


def _url(name: str, stats_season: int = STATS_SEASON) -> str:
    try:
        return _datasets(stats_season)[name][0]
    except KeyError:
        try:
            return _corpus_datasets()[name][0]
        except KeyError as exc:
            raise KeyError(f"unknown dataset {name!r}") from exc


def _dest_path(name: str, stats_season: int = STATS_SEASON) -> Path:
    src = _datasets(stats_season)
    if name not in src:
        src = _corpus_datasets()
    return RAW_DIR / src[name][1]


def download(name: str, refresh: bool = False, timeout: int = 240,
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
    """Download and load the core datasets. Returns a name->DataFrame dict."""
    out = {}
    for name in _datasets(stats_season):
        print(f"Loading {name}...")
        out[name] = load(name, refresh=refresh, stats_season=stats_season)
    return out


def collect_corpus(refresh: bool = False) -> dict[str, pd.DataFrame]:
    """Download and load the full 2026 projection corpus.

    Returns a dict with keys: players, games, injuries, depth_charts, and
    player_week_stats_{y} for each year in HISTORY_SEASONS.
    """
    out: dict[str, pd.DataFrame] = {}
    for name in ("players", "games", "injuries", "depth_charts"):
        print(f"Loading {name}...")
        try:
            out[name] = load(name, refresh=refresh)
        except Exception as exc:  # e.g. a 404 release that isn't out yet
            print(f"  skipped {name}: {exc}")
    for y in HISTORY_SEASONS:
        key = "player_week_stats" if y == STATS_SEASON else f"player_week_stats_{y}"
        print(f"Loading {key}...")
        out[key] = load(key, refresh=refresh)
    return out


def load_schedule(season: int = SCHEDULE_SEASON, refresh: bool = False) -> pd.DataFrame:
    """Return the game schedule filtered to ``season`` (default 2026)."""
    games = load("games", refresh=refresh)
    games = games[games["season"] == season].reset_index(drop=True)
    return games


def load_depth_charts(season: int = SCHEDULE_SEASON, refresh: bool = False) -> pd.DataFrame:
    return load("depth_charts", refresh=refresh)
