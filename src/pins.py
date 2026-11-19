"""Manual lineup pins: players the operator must never move.

Local state toggled from the web UI (/team) and stored in data/pins.json
(git-ignored, like logs/). The operator loads the pin set before proposing
moves; a pinned player keeps his current slot exactly like a game-locked
player — starter or bench, the optimizer works around him.

Fail-closed: a corrupt pin file raises PinsError. The operator aborts the
run (status "pins_error") rather than silently ignoring the user's
protection and overwriting a manually set lineup.

File shape:
    {"pinned": {"<yahoo_id>": {"name": "...", "pinned_at": "<iso8601>"}}}
"""

from __future__ import annotations

import fcntl
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PINS_PATH = ROOT / "data" / "pins.json"


class PinsError(Exception):
    """The pin file exists but cannot be trusted (unreadable/invalid shape)."""


def load_pins(path: Path | str | None = None) -> dict[str, dict[str, Any]]:
    """Return {yahoo_id: {"name", "pinned_at"}}; missing file means no pins.

    Raises PinsError on any corruption — callers must not fall back to an
    empty set when the user's protection cannot be read.
    """
    path = Path(path) if path is not None else PINS_PATH
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise PinsError(f"cannot read pin file {path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise PinsError(f"pin file {path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("pinned"), dict):
        raise PinsError(f"pin file {path} must be an object with a 'pinned' object")
    pinned = data["pinned"]
    for yahoo_id, meta in pinned.items():
        if not isinstance(yahoo_id, str) or not isinstance(meta, dict) \
                or not isinstance(meta.get("name"), str):
            raise PinsError(f"pin file {path} has a malformed entry: {yahoo_id!r}")
    return pinned


def save_pins(pinned: dict[str, dict[str, Any]], path: Path | str | None = None) -> None:
    """Atomically persist the pin set (tmp file + rename; readers never see a partial write)."""
    path = Path(path) if path is not None else PINS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"pinned": pinned}, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)


def pinned_ids(path: Path | str | None = None) -> set[str]:
    """The set of pinned Yahoo player IDs (what propose_lineup consumes)."""
    return set(load_pins(path))


def toggle_pin(yahoo_id: str, name: str = "", path: Path | str | None = None) -> bool:
    """Flip one player's pin; returns the new state (True = pinned).

    Serialized with an flock so two concurrent web requests cannot lose an
    update. The operator only reads, and reads are atomic via save_pins.
    """
    if not isinstance(yahoo_id, str) or not yahoo_id.strip():
        raise PinsError("yahoo_id must be a non-empty string")
    yahoo_id = yahoo_id.strip()
    path = Path(path) if path is not None else PINS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    with open(lock_path, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        pinned = load_pins(path)
        if yahoo_id in pinned:
            del pinned[yahoo_id]
            state = False
        else:
            pinned[yahoo_id] = {
                "name": name or yahoo_id,
                "pinned_at": datetime.now(timezone.utc).isoformat(),
            }
            state = True
        save_pins(pinned, path)
    return state
