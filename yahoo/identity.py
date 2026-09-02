"""Stable Yahoo-ID to internal-player-ID reconciliation.

Names, teams, and positions validate a mapping; Yahoo IDs are the persisted key.
Team mismatches are retained as diagnostics but are not actionable projections.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

TEAM_ALIASES = {"JAC": "JAX", "WSH": "WAS", "LAR": "LA", "OAK": "LV", "SD": "LAC", "STL": "LA"}


@dataclass(frozen=True)
class YahooPlayerIdentity:
    yahoo_id: str
    name: str
    team: str
    position: str


@dataclass(frozen=True)
class IdentityMapping:
    yahoo_id: str
    yahoo_name: str
    yahoo_team: str
    position: str
    internal_id: str | None
    internal_name: str | None
    internal_team: str | None
    status: str

    @property
    def actionable(self) -> bool:
        return self.status == "matched"

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["actionable"] = self.actionable
        return value


def _name_key(name: str) -> str:
    value = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", value, flags=re.I)
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _team_key(team: str) -> str:
    value = str(team or "").upper()
    return TEAM_ALIASES.get(value, value)


def reconcile_identities(
    yahoo_players: Iterable[YahooPlayerIdentity],
    model: pd.DataFrame,
) -> tuple[IdentityMapping, ...]:
    """Resolve full Yahoo identities uniquely; never expand abbreviations."""
    required = {"player_id", "player_display_name", "position", "last_team"}
    if not required.issubset(model.columns):
        raise KeyError(f"model is missing identity columns: {sorted(required - set(model.columns))}")

    index: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in model[list(required)].drop_duplicates().to_dict("records"):
        key = (_name_key(str(row["player_display_name"])), str(row["position"]).upper())
        index.setdefault(key, []).append({key: str(value) for key, value in row.items()})

    mappings = []
    seen: set[str] = set()
    for player in yahoo_players:
        if player.yahoo_id in seen:
            raise ValueError(f"duplicate Yahoo ID: {player.yahoo_id}")
        seen.add(player.yahoo_id)
        candidates = index.get((_name_key(player.name), player.position.upper()), [])
        if not candidates:
            status = "unmapped"
            candidate = None
        elif len(candidates) > 1:
            status = "ambiguous"
            candidate = None
        else:
            candidate = candidates[0]
            status = "matched" if _team_key(player.team) == _team_key(candidate["last_team"]) else "team_mismatch"
        mappings.append(IdentityMapping(
            yahoo_id=player.yahoo_id,
            yahoo_name=player.name,
            yahoo_team=player.team.upper(),
            position=player.position.upper(),
            internal_id=candidate["player_id"] if candidate else None,
            internal_name=candidate["player_display_name"] if candidate else None,
            internal_team=candidate["last_team"] if candidate else None,
            status=status,
        ))
    return tuple(mappings)


def write_identity_map(path: str | Path, mappings: Iterable[IdentityMapping]) -> None:
    """Persist a deterministic diagnostic map without authentication data."""
    rows = sorted((mapping.as_dict() for mapping in mappings), key=lambda row: int(row["yahoo_id"]))
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"players": rows}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
