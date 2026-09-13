"""League-wide roster-strength analysis: pure functions, no browser involved.

Given every league roster (name/team/position/slot dicts) and the model's
projection frames, answer "is my team any good, and what needs doing":
optimal-lineup strength per team, per-position ranks vs the league, bye-week
concentration, dead roster spots, and a rule-based recommendation list.

The browser/CDP glue that gathers the inputs lives in tools/team_analyzer.py.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from .identity import YahooPlayerIdentity, reconcile_identities

STARTER_SLOTS = ("QB", "RB", "WR", "TE", "W/R/T", "K", "DEF")
BENCH_SLOTS = ("BN", "IR", "IL")
SKILL_POSITIONS = ("QB", "RB", "WR", "TE")
LINEUP_REQUIREMENTS = (("QB", 1), ("RB", 2), ("WR", 2), ("TE", 1), ("K", 1), ("DEF", 1))
FLEX_POSITIONS = ("RB", "WR", "TE")
UPGRADE_THRESHOLD = 2.0  # a wire target must out-project the starter by this much


def evaluate_roster(roster: list[dict], frame: pd.DataFrame, value_col: str,
                    id_base: int) -> list[dict]:
    """Attach model values to one roster.

    Every player gets `value` (float or None when the model cannot evaluate
    him) and `map_status` (matched, no_projection, team_mismatch, unmapped,
    ambiguous). `no_projection` means he was identified in the dataset but
    the model produced no number — typical for rookies and new call-ups.
    `id_base` namespaces the synthetic Yahoo IDs so several rosters can be
    evaluated without ID collisions.
    """
    identities = [
        YahooPlayerIdentity(yahoo_id=str(id_base + i), name=p["name"],
                            team=p["team"], position=p["position"])
        for i, p in enumerate(roster)
    ]
    mappings = {m.yahoo_id: m for m in reconcile_identities(identities, frame)}
    evaluated = []
    for i, player in enumerate(roster):
        mapping = mappings[str(id_base + i)]
        value = None
        status = mapping.status
        if mapping.actionable:
            hit = frame[frame["player_id"] == mapping.internal_id]
            if len(hit) and pd.notna(hit.iloc[0][value_col]):
                value = float(hit.iloc[0][value_col])
            else:
                status = "no_projection"
        evaluated.append({**player, "value": value, "map_status": status})
    return evaluated


def optimal_lineup(players: list[dict]) -> list[dict]:
    """Best legal 1QB/2RB/2WR/1TE/flex/1K/1DEF from evaluated players."""
    by_pos: dict[str, list[dict]] = {}
    for player in players:
        if player["value"] is None:
            continue
        by_pos.setdefault(player["position"], []).append(player)
    for group in by_pos.values():
        group.sort(key=lambda p: p["value"], reverse=True)
    lineup = []
    for position, count in LINEUP_REQUIREMENTS:
        lineup.extend(by_pos.get(position, [])[:count])
    slotted = {id(p) for p in lineup}
    flex_pool = [p for pos in FLEX_POSITIONS for p in by_pos.get(pos, [])
                 if id(p) not in slotted]
    if flex_pool:
        lineup.append(max(flex_pool, key=lambda p: p["value"]))
    return lineup


def optimal_score(players: list[dict]) -> float:
    return round(sum(p["value"] for p in optimal_lineup(players)), 1)


def position_ranks(league: dict[str, list[dict]], my_team_id: str) -> list[dict]:
    """For each position, where my best rostered player ranks vs the league's best."""
    ranks = []
    for position in ("QB", "RB", "WR", "TE", "K"):
        leaderboard = []
        for tid, players in league.items():
            best = None
            for player in players:
                if player["position"] == position and player["value"] is not None:
                    if best is None or player["value"] > best["value"]:
                        best = player
            if best is not None:
                leaderboard.append((best["value"], tid, best["name"]))
        leaderboard.sort(reverse=True)
        mine = next(((sum(1 for v, _, _ in leaderboard if v > value) + 1, name, value)
                     for value, tid, name in leaderboard if tid == my_team_id), None)
        ranks.append({
            "position": position,
            "rank": mine[0] if mine else None,
            "of": len(leaderboard),
            "my_player": mine[1] if mine else None,
            "my_value": mine[2] if mine else None,
            "best_player": leaderboard[0][2] if leaderboard else None,
        })
    return ranks


def bye_weeks(schedule: pd.DataFrame, max_week: int = 18) -> dict[str, int]:
    """Team -> its bye week (the REG week with no row), when one exists."""
    byes = {}
    for team in schedule["team"].unique():
        played = set(schedule[schedule["team"] == team]["week"])
        missing = [w for w in range(1, max_week + 1) if w not in played]
        if missing:
            byes[team] = min(missing)
    return byes


def bye_concentration(players: list[dict], byes: dict[str, int],
                      team_aliases: dict[str, str] | None = None) -> dict[int, list[str]]:
    """Week -> starter names on bye that week, for weeks with 2+ starters out."""
    aliases = team_aliases or {}
    weeks: dict[int, list[str]] = {}
    for player in players:
        if player["slot"] in BENCH_SLOTS:
            continue
        team = aliases.get(player["team"], player["team"])
        week = byes.get(team)
        if week is not None:
            weeks.setdefault(week, []).append(player["name"])
    return {week: sorted(names) for week, names in weeks.items() if len(names) >= 2}


def dead_spots(players: list[dict]) -> list[dict]:
    """Rostered players the model sees as worthless or cannot evaluate at all."""
    spots = []
    for player in players:
        if player["position"] in ("K", "DEF"):
            continue  # K/DEF projections are thin by design; never call them dead
        if player["value"] is None:
            spots.append({**player, "reason": player["map_status"]})
        elif player["value"] <= 0.0:
            spots.append({**player, "reason": "zero projection"})
    return spots


def drop_candidates(players: list[dict]) -> list[dict]:
    """Bench players with no model value — the only safe drop nominations.

    Starters are never nominated, team_mismatch stays flagged as a possible
    nflverse trade lag, and no_projection players are excluded: the model
    cannot price them (rookies, new call-ups), which is a blind spot, not
    proof of worthlessness.
    """
    return [p for p in dead_spots(players)
            if p["slot"] in BENCH_SLOTS and p["reason"] != "no_projection"]


def recommendations(*, my_eval: list[dict], week_eval: list[dict] | None,
                    lineup_moves: tuple, wire_targets: list[dict],
                    ranks: list[dict], concentration: dict[int, list[str]],
                    season_strength: tuple[int, int, float]) -> list[dict]:
    """Rule-based, ranked 'what needs doing' list. Every rule is transparent."""
    recs: list[dict] = []

    for move in lineup_moves:
        recs.append({"kind": "lineup", "priority": 1,
                     "text": f"lineup move available: {move}"})
    if not lineup_moves:
        recs.append({"kind": "lineup", "priority": 1,
                     "text": "lineup is already optimal; the Monday cron keeps it that way"})

    weakest = [r for r in ranks if r["rank"] is not None and r["rank"] >= 7]
    for row in weakest:
        recs.append({"kind": "weak_slot", "priority": 2,
                     "text": f"{row['position']} is a bottom-tier slot "
                             f"({row['rank']}/{row['of']} with {row['my_player']}); "
                             f"prioritize upgrades here"})

    if wire_targets and week_eval:
        weakest_starter: dict[str, dict] = {}
        for p in week_eval:
            if p["slot"] in BENCH_SLOTS or p["value"] is None:
                continue
            current = weakest_starter.get(p["position"])
            if current is None or p["value"] < current["value"]:
                weakest_starter[p["position"]] = p
        drops = drop_candidates(my_eval)
        for target in wire_targets:
            pos = target.get("position")
            current = weakest_starter.get(pos)
            if current is None or target.get("proj_week", 0) < current["value"] + UPGRADE_THRESHOLD:
                continue
            if drops:
                drop = drops[0]
                note = " (possible trade lag — verify first)" if drop["reason"] == "team_mismatch" else ""
                drop_text = f"; drop {drop['name']}{note}"
            else:
                drop_text = " (no obvious drop candidate)"
            recs.append({"kind": "waiver", "priority": 2,
                         "text": f"wire upgrade: {target['name']} ({pos}, "
                                 f"{target.get('proj_week')} proj) beats {current['name']} "
                                 f"({current['value']}){drop_text}"})

    for drop in dead_spots(my_eval):
        if drop["reason"] == "no_projection":
            recs.append({"kind": "hygiene", "priority": 3,
                         "text": f"model blind spot: {drop['name']} has no projection "
                                 f"(rookie or new to the dataset) — verify manually; "
                                 f"not an auto-drop"})
            continue
        reason = "possible trade lag — verify" if drop["reason"] == "team_mismatch" else drop["reason"]
        recs.append({"kind": "hygiene", "priority": 3,
                     "text": f"dead spot: {drop['name']} ({reason}) — "
                             f"convert this slot into any startable value"})

    for week, names in sorted(concentration.items()):
        severity = "URGENT" if len(names) >= 3 else "plan ahead"
        recs.append({"kind": "bye", "priority": 3,
                     "text": f"week {week}: {len(names)} starters on bye "
                             f"({', '.join(names)}) — {severity}"})

    rank, of, score = season_strength
    playoff_line = 4
    note = "inside" if rank <= playoff_line else "outside"
    recs.append({"kind": "standing", "priority": 4,
                 "text": f"season strength {rank}/{of} ({score}) — {note} the "
                         f"top-{playoff_line} playoff line"})
    return recs


def render_report(analysis: dict[str, Any]) -> str:
    """Plain-text rendering of the analyzer output for the terminal."""
    lines = [f"FD nation team analysis — {analysis['date']} (week {analysis['week']})",
             "=" * 60]
    if analysis.get("mode") == "light":
        lines.append("MODE: light — league-wide sections skipped (run without "
                     "--light for strength ranks and waiver advice)")
    matchup = analysis.get("matchup")
    if matchup:
        lines.append(f"MATCHUP: vs {matchup['opponent']} — "
                     f"{matchup['score']} : {matchup['opponent_score']} "
                     f"(proj {matchup['team_proj']} vs {matchup['opponent_proj']})")
    missing = analysis.get("teams_missing") or []
    if missing:
        lines.append(f"NOTE: {len(missing)} team roster(s) unreadable this run "
                     f"(ids: {', '.join(missing)}); ranks cover the rest")
    strength = analysis.get("season_strength")
    if strength:
        lines.append(f"LEAGUE STRENGTH (season, optimal lineup): "
                     f"{strength['rank']}/{strength['of']} "
                     f"({strength['score']} pts; leader {strength['leader']}, "
                     f"playoff line ~{strength['playoff_line']})")
    rank_rows = analysis.get("position_ranks") or []
    if rank_rows:
        lines.append("Position ranks vs league (best rostered):")
        for row in rank_rows:
            if row["rank"] is None:
                lines.append(f"  {row['position']:>3}  n/a")
            else:
                flag = "  <-- weakest" if row["rank"] >= 7 else ""
                lines.append(f"  {row['position']:>3}  {row['rank']}/{row['of']}  "
                             f"{row['my_player']} ({row['my_value']}){flag}")
    alerts = analysis.get("alerts") or []
    if alerts:
        lines.append("ALERTS:")
        lines.extend(f"  - {alert}" for alert in alerts)
    lines.append("RECOMMENDATIONS (ranked):")
    for i, rec in enumerate(analysis["recommendations"], 1):
        lines.append(f"  {i}. [{rec['kind']}] {rec['text']}")
    return "\n".join(lines)
