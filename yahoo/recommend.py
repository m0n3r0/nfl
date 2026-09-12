"""Weekly start/sit recommendation: roster snapshot + weekly projections -> exact moves.

Pure decision layer: no CDP, no I/O. The tool wrapper (tools/weekly_lineup.py)
supplies the live TeamSnapshot and the src weekly projection table; this module
emits the exact LineupMove tuples the verified operator can apply, plus the
warnings a human must see. Fail-closed: unevaluated players stay put.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, replace
from typing import Any

import pandas as pd

from .identity import TEAM_ALIASES, YahooPlayerIdentity, reconcile_identities
from .lineup import LineupMove
from .team import INJURED_RESERVE_SLOTS, RosterPlayer, TeamSnapshot

# Slots the optimizer may change, in fill order (flex last so RB/WR depth is
# not stranded). K/DEF are never moved: the roster carries exactly one of each
# and nflverse player stats carry no K/DEF projection to compare against.
OPTIMIZED_SLOTS = ("QB", "RB", "RB", "WR", "WR", "TE", "W/R/T")
SLOT_ELIGIBILITY = {
    "QB": {"QB"}, "RB": {"RB"}, "WR": {"WR"}, "TE": {"TE"},
    "W/R/T": {"RB", "WR", "TE"},
}


@dataclass(frozen=True)
class PlayerPlan:
    """One roster player's evaluated start/sit outcome."""

    yahoo_id: str
    name: str
    position: str
    current_slot: str
    proposed_slot: str
    proj_week: float | None
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LineupProposal:
    """The full weekly recommendation: exact moves + per-player plan + warnings."""

    week: int
    moves: tuple[LineupMove, ...]
    plan: tuple[PlayerPlan, ...]
    warnings: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "week": self.week,
            "moves": [asdict(move) for move in self.moves],
            "plan": [player.as_dict() for player in self.plan],
            "warnings": list(self.warnings),
        }


def _evaluation_maps(projections: pd.DataFrame) -> tuple[dict, dict, dict]:
    by_id = projections.set_index("player_id")
    proj_week = by_id["proj_week"].to_dict()
    on_bye = by_id["on_bye"].to_dict() if "on_bye" in by_id.columns else {}
    injury = by_id["injury_status"].to_dict() if "injury_status" in by_id.columns else {}
    return proj_week, on_bye, injury


def propose_lineup(snapshot: TeamSnapshot, projections: pd.DataFrame, week: int) -> LineupProposal:
    """Recommend the best legal lineup and the exact moves to reach it.

    Locked players (their game already kicked off) keep their slot — Yahoo will
    not move them anyway. Unmapped players keep their slot with a warning: a
    player we cannot evaluate is never swapped on a guess. Bye-week players
    count as 0 and sink below any evaluated bench replacement; if no
    replacement exists the starter stays and a warning says the slot is
    effectively empty.
    """
    identities = [
        YahooPlayerIdentity(yahoo_id=p.yahoo_id, name=p.name, team=p.team, position=p.position)
        for p in snapshot.roster
    ]
    mappings = {m.yahoo_id: m for m in reconcile_identities(identities, projections)}
    proj_week, on_bye, injury = _evaluation_maps(projections)

    warnings: list[str] = []
    if "on_bye" not in projections.columns:
        warnings.append("projection frame has no bye data; bye-week players are evaluated at full projection")
    if "injury_status" not in projections.columns:
        warnings.append("projection frame has no injury data; injured players are evaluated at full projection")
    evaluated: dict[str, float | None] = {}
    notes: dict[str, str] = {}
    for player in snapshot.roster:
        mapping = mappings[player.yahoo_id]
        note = ""
        value: float | None = None
        if mapping.actionable:
            value = float(proj_week[mapping.internal_id])
            if on_bye.get(mapping.internal_id):
                value = 0.0
                note = "bye"
            elif injury.get(mapping.internal_id):
                note = f"injury: {injury[mapping.internal_id]}"
        elif player.position in {"K", "DEF"}:
            note = "no projection data; kept"
        else:
            note = f"unmapped ({mapping.status})"
            warnings.append(f"{player.name} ({player.position}) is {mapping.status}; kept in {player.slot}")
        if player.locked:
            note = (note + ", " if note else "") + "locked"
        evaluated[player.yahoo_id] = value
        notes[player.yahoo_id] = note
        if note == "bye" and player.slot != "BN":
            warnings.append(f"{player.name} is on BYE in week {week} and currently in {player.slot}")
        if note.startswith("injury:") and player.slot != "BN":
            warnings.append(f"{player.name} is {note.split(': ')[1]} and currently in {player.slot}")

    fixed: dict[str, str] = {}  # yahoo_id -> slot kept
    for player in snapshot.roster:
        if player.locked or player.position in {"K", "DEF"} or player.slot in {"IR", "IL"}:
            fixed[player.yahoo_id] = player.slot

    open_slots = list(OPTIMIZED_SLOTS)
    for player in snapshot.roster:
        if player.yahoo_id in fixed and player.slot in open_slots:
            open_slots.remove(player.slot)

    movable = [p for p in snapshot.roster if p.yahoo_id not in fixed]

    # An unevaluated starter blocks his slot: we never swap a player we cannot
    # evaluate, in either direction. The bench candidate behind him stays benched.
    blocked: set[str] = set()
    fill_slots: list[str] = []
    for slot in ("QB", "RB", "WR", "TE", "W/R/T"):
        n_open = open_slots.count(slot)
        for player in movable:
            if player.slot == slot and evaluated[player.yahoo_id] is None and n_open > 0:
                blocked.add(player.yahoo_id)
                n_open -= 1
        fill_slots.extend([slot] * n_open)

    ranked = sorted(
        (p for p in movable if evaluated[p.yahoo_id] is not None),
        key=lambda p: evaluated[p.yahoo_id],  # type: ignore[arg-type]
        reverse=True,
    )
    # A starter leaves his slot only when an evaluated replacement can backfill
    # it; otherwise the current occupant stays, so the emitted move set always
    # preserves the roster's slot counts.
    assigned: dict[str, str] = {}
    while True:
        assigned = {}
        used: set[str] = set()
        for slot in fill_slots:
            eligible = SLOT_ELIGIBILITY[slot]
            pick = next(
                (p for p in ranked
                 if p.yahoo_id not in used and p.yahoo_id not in blocked and p.position in eligible),
                None,
            )
            if pick is not None:
                assigned[pick.yahoo_id] = slot
                used.add(pick.yahoo_id)
        covered = Counter(assigned.values())
        hole = next(
            (slot for slot in dict.fromkeys(fill_slots) if covered[slot] < fill_slots.count(slot)),
            None,
        )
        if hole is None:
            break
        keeper = next(
            (p for p in movable
             if p.slot == hole and p.yahoo_id not in blocked and assigned.get(p.yahoo_id) != hole),
            None,
        )
        if keeper is None:
            break
        blocked.add(keeper.yahoo_id)
        fill_slots.remove(hole)
        warnings.append(f"no evaluated {hole} replacement for week {week}; {keeper.name} stays in {hole}")

    proposed: dict[str, str] = {}
    for player in movable:
        if player.yahoo_id in assigned:
            proposed[player.yahoo_id] = assigned[player.yahoo_id]
        elif player.yahoo_id in blocked or player.slot not in OPTIMIZED_SLOTS:
            proposed[player.yahoo_id] = player.slot  # blocked starter or bench stays
        else:
            proposed[player.yahoo_id] = "BN"  # evaluated starter, outranked

    needed = Counter(open_slots)
    filled = Counter(assigned.values())
    for player in movable:
        if player.yahoo_id in blocked and evaluated[player.yahoo_id] is not None:
            filled[player.slot] += 1
    for slot, n in sorted(needed.items()):
        if filled[slot] < n:
            warnings.append(f"slot {slot} has no evaluated starter for week {week}")

    moves = tuple(
        LineupMove(yahoo_id=p.yahoo_id, from_slot=p.slot, to_slot=proposed[p.yahoo_id])
        for p in snapshot.roster
        if proposed.get(p.yahoo_id, p.slot) != p.slot
    )
    plan = tuple(
        PlayerPlan(
            yahoo_id=p.yahoo_id, name=p.name, position=p.position,
            current_slot=p.slot, proposed_slot=proposed.get(p.yahoo_id, p.slot),
            proj_week=evaluated[p.yahoo_id], note=notes[p.yahoo_id],
        )
        for p in snapshot.roster
    )
    return LineupProposal(week=week, moves=moves, plan=plan, warnings=tuple(warnings))


def apply_schedule_locks(snapshot: TeamSnapshot, locked_teams: set[str]) -> tuple[TeamSnapshot, tuple[str, ...]]:
    """Cross-check DOM lock state against the schedule for the week.

    A player counts as locked when the page says so OR his team's game has
    already kicked off — a stale page must never make a started player look
    movable. Disagreements between the two sources come back as warnings.
    Injured-reserve rows are skipped: they are immovable either way, and Yahoo
    disables their selects regardless of kickoff.
    """
    warnings: list[str] = []
    roster = []
    for player in snapshot.roster:
        if player.slot in INJURED_RESERVE_SLOTS:
            roster.append(player)
            continue
        schedule_locked = TEAM_ALIASES.get(player.team, player.team) in locked_teams
        if schedule_locked and not player.locked:
            warnings.append(
                f"{player.name} ({player.team}) has kicked off per the schedule "
                "but the page shows him movable; treating as locked"
            )
        elif player.locked and not schedule_locked:
            warnings.append(
                f"{player.name} ({player.team}) is locked on the page "
                "but his team has not kicked off per the schedule"
            )
        roster.append(replace(player, locked=player.locked or schedule_locked))
    return replace(snapshot, roster=tuple(roster)), tuple(warnings)
