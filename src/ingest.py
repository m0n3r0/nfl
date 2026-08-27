"""Data ingestion from the public nflverse release assets.

nflverse publishes flat CSVs as GitHub *release* assets (not as files on the
default branch). We download the ones we need into ``data/raw`` and cache them,
re-downloading only when explicitly forced.
"""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import requests

from .config import DEFAULT_SEASON

# Base URL for nflverse-data release assets.
_RELEASE_BASE = (
    "https://github.com/nflverse/nflverse-data/releases/download"
)

# Logical name -> (url, local filename).
DATASETS = {
    "players": (
        f"{_RELEASE_BASE}/players/players.csv",
        "players.csv",
    ),
    "games": (
        f"{_RELEASE_BASE}/schedules/games.csv",
        "games.csv",
    ),
    "player_week_stats": (
        f"{_RELEASE_BASE}/stats_player/stats_player_week_{DEFAULT_SEASON}.csv",
        f"player_week_stats_{DEFAULT_SEASON}.csv",
    ),
}

# Repo root is two levels up from this file (src/ -> repo root).
REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = REPO_ROOT / "data" / "raw"


def _url(name: str) -> str:
    try:
        return DATASETS[name][0]
    except KeyError as exc:
        raise KeyError(f"unknown dataset {name!r}; known: {sorted(DATASETS)}") from exc


def _dest_path(name: str) -> Path:
    return RAW_DIR / DATASETS[name][1]


def download(name: str, refresh: bool = False, timeout: int = 180) -> Path:
    """Download ``name`` into data/raw, returning the local path.

    Skips the download if a cached copy exists unless ``refresh`` is set.
    """
    url = _url(name)
    dest = _dest_path(name)
    if dest.exists() and not refresh:
        return dest

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with requests.get(url, stream=True, timeout=timeout) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0))
            written = 0
            start = time.time()
            with open(tmp, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    if not chunk:
                        continue
                    fh.write(chunk)
                    written += len(chunk)
            # Minimal progress hint to stderr.
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


def load(name: str, refresh: bool = False) -> pd.DataFrame:
    """Download (if needed) and return ``name`` as a DataFrame."""
    dest = download(name, refresh=refresh)
    return pd.read_csv(dest)


def load_all(refresh: bool = False) -> dict[str, pd.DataFrame]:
    """Download and load every known dataset. Returns a name->DataFrame dict."""
    out = {}
    for name in DATASETS:
        print(f"Loading {name}...")
        out[name] = load(name, refresh=refresh)
    return out
